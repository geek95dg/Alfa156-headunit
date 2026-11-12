"""Tests for the buffer-bank monitor (src/power/battery.py).

12 V AGM thresholds from docs/ZASILANIE_BUFOROWANE.md §13.4; time comes from
a fake clock, so staleness is tested without sleeping.
"""

import math

import pytest

from src.core.event_bus import EventBus
from src.input.arduino_serial import ArduinoSerialListener
from src.power import battery as battery_mod
from src.power.battery import DEFAULTS, BatteryBackup, BatteryMonitor, load_settings


class _Clock:
    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


@pytest.fixture()
def rig():
    """(bus, monitor factory, recorded battery.* events, clock)."""
    bus = EventBus()
    clock = _Clock()
    events: list[tuple[str, object]] = []
    bus.subscribe("*", lambda t, v, ts: events.append((t, v)) if t.startswith("battery.") else None)

    def make(**battery_cfg):
        return BatteryMonitor(bus, {"battery": battery_cfg}, clock=clock)
    return bus, make, events, clock


def _feed(bus, clock, volts, amps=None, dt=2.0):
    """One BATT: line, as arduino_serial publishes it (current first)."""
    clock.t += dt
    if amps is not None:
        bus.publish("arduino.battery_current", amps)
    bus.publish("arduino.battery_voltage", volts)


def _last(events, topic):
    vals = [v for t, v in events if t == topic]
    return vals[-1] if vals else None


def _count(events, topic):
    return sum(1 for t, _ in events if t == topic)


class TestThresholds:
    @pytest.mark.parametrize("sequence, expected", [
        # (voltages fed one by one, state after the last one)
        ([12.90], "full"),
        ([12.85], "full"),
        ([12.60], "ok"),
        ([11.80], "ok"),                  # at low_v is still ok
        ([11.79], "low"),
        ([11.79, 11.85], "low"),          # hysteresis: stays low …
        ([11.79, 11.90], "low"),          # … up to and including low_v + 0.10
        ([11.79, 11.91], "ok"),           # … and leaves above it
        ([11.19], "critical"),
        ([11.19, 11.25], "critical"),
        ([11.19, 11.30], "critical"),
        ([11.19, 11.31], "low"),          # out of critical, still below low_v + h
        ([11.19, 11.95], "ok"),
        ([12.90, 12.80], "full"),         # full until below full_v - 0.10
        ([12.90, 12.74], "ok"),
        ([11.85], "ok"),                  # no history: 11.85 is simply ok
    ])
    def test_table(self, rig, sequence, expected):
        bus, make, events, clock = rig
        mon = make(smoothing_samples=1)
        for v in sequence:
            _feed(bus, clock, v)
        assert mon.state == expected
        assert _last(events, "battery.state") == expected

    def test_voltage_and_pct_published(self, rig):
        bus, make, events, clock = rig
        make(smoothing_samples=1)
        _feed(bus, clock, 12.85)
        assert _last(events, "battery.voltage") == pytest.approx(12.85)
        assert _last(events, "battery.pct") == 100
        _feed(bus, clock, 11.20)
        assert _last(events, "battery.pct") == 0
        _feed(bus, clock, 12.025)              # halfway between 11.20 and 12.85
        assert _last(events, "battery.pct") == 50
        _feed(bus, clock, 6.0)
        assert _last(events, "battery.pct") == 0   # clamped


class TestCharging:
    def test_charging_by_voltage(self, rig):
        bus, make, events, clock = rig
        mon = make(smoothing_samples=1)
        _feed(bus, clock, 13.21)
        assert mon.state == "charging"
        assert _last(events, "battery.pct_reliable") is False

    def test_charging_by_current(self, rig):
        bus, make, events, clock = rig
        mon = make(smoothing_samples=1)
        _feed(bus, clock, 12.50, amps=0.5)
        assert mon.state == "charging"
        assert _last(events, "battery.current") == pytest.approx(0.5)

    def test_small_current_is_not_charging_and_pct_is_reliable(self, rig):
        bus, make, events, clock = rig
        mon = make(smoothing_samples=1)
        _feed(bus, clock, 12.50, amps=0.1)
        assert mon.state == "ok"
        assert _last(events, "battery.pct_reliable") is True

    def test_under_load_pct_is_a_hint_only(self, rig):
        bus, make, events, clock = rig
        mon = make(smoothing_samples=1)
        _feed(bus, clock, 12.30, amps=-3.4)          # M910q running from the bank
        assert mon.state == "ok"
        assert _last(events, "battery.pct_reliable") is False

    def test_without_current_pct_is_never_reliable(self, rig):
        bus, make, events, clock = rig
        make(smoothing_samples=1)
        _feed(bus, clock, 12.50)
        assert _last(events, "battery.pct_reliable") is False
        assert _count(events, "battery.current") == 0

    def test_current_sign_flips_a_reversed_shunt(self, rig):
        bus, make, events, clock = rig
        mon = make(smoothing_samples=1, current_sign=-1)
        _feed(bus, clock, 12.50, amps=-5.0)          # wired backwards: charging reads < 0
        assert mon.state == "charging"
        assert _last(events, "battery.current") == pytest.approx(5.0)

    def test_hysteresis_survives_a_charging_spell(self, rig):
        bus, make, events, clock = rig
        mon = make(smoothing_samples=1)
        _feed(bus, clock, 12.90)
        _feed(bus, clock, 13.80)
        assert mon.state == "charging"
        _feed(bus, clock, 12.78)          # surface charge fading: still "full"
        assert mon.state == "full"


class TestStale:
    def test_stale_means_unknown(self, rig):
        bus, make, events, clock = rig
        mon = make(smoothing_samples=1, stale_sec=30)
        _feed(bus, clock, 12.50)
        assert mon.state == "ok"
        clock.t += 29
        mon.tick()
        assert mon.state == "ok"
        clock.t += 2                      # 31 s since the last sample
        mon.tick()
        assert mon.state == "unknown"
        assert _last(events, "battery.pct") is None
        assert _last(events, "battery.pct_reliable") is False
        _feed(bus, clock, 12.50)
        assert mon.state == "ok"

    def test_stale_current_is_forgotten(self, rig):
        bus, make, events, clock = rig
        mon = make(smoothing_samples=1, stale_sec=30)
        _feed(bus, clock, 12.50, amps=1.0)
        assert mon.state == "charging"
        _feed(bus, clock, 12.50, dt=40)   # voltage keeps coming, current stopped
        assert mon.state == "ok"

    def test_unknown_does_not_touch_the_low_flag(self, rig):
        bus, make, events, clock = rig
        mon = make(smoothing_samples=1, stale_sec=30)
        _feed(bus, clock, 11.70)
        assert _count(events, "battery.low") == 1
        clock.t += 60
        mon.tick()
        assert mon.state == "unknown"
        _feed(bus, clock, 11.70)
        assert _count(events, "battery.low") == 1   # no False/True chatter

    def test_start_announces_unknown_and_stop_joins(self, rig):
        bus, make, events, clock = rig
        mon = make()
        mon.start()
        try:
            assert _last(events, "battery.state") == "unknown"
            assert mon._thread is not None and mon._thread.is_alive()
        finally:
            mon.stop()
        assert mon._thread is None
        events.clear()
        _feed(bus, clock, 12.5)                     # unsubscribed after stop()
        assert events == []


class TestEdges:
    def test_low_and_critical_only_on_edges(self, rig):
        bus, make, events, clock = rig
        make(smoothing_samples=1)
        for v in (12.5, 11.75, 11.70, 11.72, 11.10, 11.05, 11.15, 11.40, 11.50, 12.0, 12.1):
            _feed(bus, clock, v)
        assert [(t, v) for t, v in events if t in ("battery.low", "battery.critical")] == [
            ("battery.low", True),        # 11.75
            ("battery.critical", True),   # 11.10
            ("battery.critical", False),  # 11.40 (> 11.30)
            ("battery.low", False),       # 12.0 (> 11.90)
        ]

    def test_straight_to_critical_raises_both(self, rig):
        bus, make, events, clock = rig
        make(smoothing_samples=1)
        _feed(bus, clock, 11.0)
        assert ("battery.low", True) in events
        assert ("battery.critical", True) in events

    def test_state_published_only_on_change(self, rig):
        bus, make, events, clock = rig
        make(smoothing_samples=1)
        for _ in range(5):
            _feed(bus, clock, 12.5)
        assert _count(events, "battery.state") == 1
        assert _count(events, "battery.voltage") == 1


class TestSmoothing:
    def test_median_ignores_a_single_spike(self, rig):
        bus, make, events, clock = rig
        mon = make(smoothing_samples=5)
        for v in (12.50, 12.52, 6.0, 12.51, 12.49):   # one bogus 6 V reading
            _feed(bus, clock, v)
        assert mon.state == "ok"
        assert ("battery.low", True) not in events
        assert _last(events, "battery.voltage") == pytest.approx(12.50)

    def test_window_follows_a_real_drop(self, rig):
        bus, make, events, clock = rig
        mon = make(smoothing_samples=3)
        for v in (12.5, 12.5, 12.5, 11.6, 11.6):
            _feed(bus, clock, v)
        assert mon.state == "low"

    @pytest.mark.parametrize("bad", [True, "12.5", None, math.nan, math.inf, 25.0, 4.0])
    def test_implausible_voltage_is_ignored(self, rig, bad):
        bus, make, events, clock = rig
        mon = make(smoothing_samples=1)
        _feed(bus, clock, 12.5)
        bus.publish("arduino.battery_voltage", bad)
        assert mon.state == "ok"
        assert _last(events, "battery.voltage") == pytest.approx(12.5)

    @pytest.mark.parametrize("bad", [True, "5", None, math.nan, -math.inf, 101.0, -150.0])
    def test_implausible_current_is_ignored(self, rig, bad):
        bus, make, events, clock = rig
        mon = make(smoothing_samples=1)
        clock.t += 2
        bus.publish("arduino.battery_current", bad)
        bus.publish("arduino.battery_voltage", 12.5)
        assert mon.state == "ok"                     # a bogus +101 A would say "charging"
        assert _count(events, "battery.current") == 0


class TestSettings:
    def test_defaults_match_the_doc(self):
        cfg = load_settings(None)
        assert (cfg["full_v"], cfg["nominal_v"], cfg["low_v"], cfg["critical_v"]) == \
            (12.85, 12.40, 11.80, 11.20)
        assert cfg == DEFAULTS

    def test_out_of_order_thresholds_fall_back_to_defaults(self):
        cfg = load_settings({"battery": {"low_v": 11.0, "critical_v": 11.5}})
        assert cfg["low_v"] == DEFAULTS["low_v"]
        assert cfg["critical_v"] == DEFAULTS["critical_v"]

    def test_bad_values(self):
        cfg = load_settings({"battery": {"hysteresis_v": "lots", "stale_sec": 1,
                                         "smoothing_samples": 1000, "current_sign": 2}})
        assert cfg["hysteresis_v"] == DEFAULTS["hysteresis_v"]
        assert cfg["stale_sec"] == 5                 # clamped
        assert cfg["smoothing_samples"] == 31
        assert cfg["current_sign"] == 1

    def test_non_dict_block(self):
        assert load_settings({"battery": "yes"}) == DEFAULTS


class TestCompat:
    def test_old_name_is_an_alias(self):
        assert BatteryBackup is BatteryMonitor

    def test_start_battery_entry_point(self):
        bus = EventBus()
        mon = battery_mod.start_battery(config={"battery": {}}, event_bus=bus, hal=None)
        try:
            assert isinstance(mon, BatteryMonitor)
            assert bus.get_last("battery.state")[0] == "unknown"
        finally:
            mon.stop()

    def test_no_legacy_backup_topics(self, rig):
        bus, make, events, clock = rig
        make(smoothing_samples=1)
        _feed(bus, clock, 11.0)
        assert not [t for t, _ in events if t.startswith("battery.backup_")]


def test_end_to_end_from_the_serial_line(monkeypatch):
    """BATT: line → arduino_serial → BatteryMonitor on one bus."""
    import src.input.arduino_serial as arduino_serial
    monkeypatch.setattr(arduino_serial, "find_arduino_serial", lambda: None)
    bus = EventBus()
    clock = _Clock()
    mon = BatteryMonitor(bus, {"battery": {"smoothing_samples": 1}}, clock=clock)
    lst = ArduinoSerialListener(bus)
    lst._parse_line("BATT:12650,-3400")
    assert mon.state == "ok"
    assert bus.get_last("battery.current")[0] == pytest.approx(-3.4)
    assert bus.get_last("battery.pct_reliable")[0] is False
    lst._parse_line("BATT:13900,6200")
    assert mon.state == "charging"
