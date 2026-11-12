"""Phone status for the top bar (src/multimedia/phone_status.py).

Everything runs against an injected reader that returns oFono/BlueZ
property dicts (no D-Bus here), plus a fake wall clock; ``tick()`` is driven
directly. The default D-Bus reader is exercised against a fake ``dbus``
module (private connection, no activation, error mapping). Only the
lifecycle tests start the worker thread — with the same fake reader.
"""

import logging
import threading
import time
import types
from pathlib import Path

import pytest

from src.core import modules_catalog
from src.core.config import BCMConfig
from src.core.event_bus import EventBus
from src.dashboard.web_viewer import WebViewer
from src.multimedia import phone_status as ps
from src.multimedia.phone_status import (
    PhoneStatusMonitor,
    ServiceUnavailable,
    battery_pct_from_level,
    clean_operator,
    modem_for_mac,
    percent,
    read_phone_status,
    registration_of,
    sanitize_status,
)

REPO = Path(__file__).resolve().parent.parent
PHONE = "AA:BB:CC:DD:EE:01"
OTHER = "AA:BB:CC:DD:EE:02"
HF = "org.ofono.Handsfree"
NR = "org.ofono.NetworkRegistration"
PATH = "/hfp/org/bluez/hci0/dev_AA_BB_CC_DD_EE_01"
OTHER_PATH = "/hfp/org/bluez/hci0/dev_AA_BB_CC_DD_EE_02"


class FakeReader:
    """oFono/BlueZ as property dicts. ``None`` for a service = not running."""

    def __init__(self):
        self.modems = [(PATH, {"Interfaces": [HF, NR, "org.ofono.VoiceCallManager"]})]
        self.props = {
            (PATH, HF): {"BatteryChargeLevel": 3, "Features": ["voice-recognition"]},
            (PATH, NR): {"Strength": 80, "Name": "Orange PL", "Status": "registered"},
        }
        self.bluez = {}                    # MAC -> Battery1.Percentage
        self.ofono_up = True
        self.bluez_up = True
        self.fail = set()                  # method names raising a plain error
        self.calls = []
        self.closed = 0
        self.on_modems = None              # hook: runs inside ofono_modems()

    def ofono_modems(self):
        self.calls.append(("modems",))
        if self.on_modems:
            self.on_modems()
        if not self.ofono_up:
            raise ServiceUnavailable("org.ofono not running")
        if "modems" in self.fail:
            raise RuntimeError("timeout")
        return list(self.modems)

    def ofono_properties(self, path, interface):
        self.calls.append(("props", path, interface))
        if not self.ofono_up:
            raise ServiceUnavailable("org.ofono not running")
        if "props" in self.fail:
            raise RuntimeError("org.freedesktop.DBus.Error.UnknownObject")
        return dict(self.props.get((path, interface), {}))

    def bluez_battery(self, mac):
        self.calls.append(("bluez", mac))
        if not self.bluez_up:
            raise ServiceUnavailable("org.bluez not running")
        if "bluez" in self.fail:
            raise RuntimeError("timeout")
        return self.bluez.get(mac)

    def close(self):
        self.closed += 1


class WallClock:
    def __init__(self, t=1_700_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def published(bus):
    """Every bt.phone_status value, in order (synchronous EventBus)."""
    out = []
    bus.subscribe(ps.TOPIC, lambda t, v, ts: out.append(v))
    return out


def make(reader=None, config=None, bus=None):
    bus = bus or EventBus()
    seen = published(bus)
    mon = PhoneStatusMonitor(config or {}, bus, reader=reader or FakeReader(),
                             wall_clock=WallClock())
    for topic, cb in mon._subscriptions():
        bus.subscribe(topic, cb)
    return mon, bus, seen


def strip_ts(value):
    return {k: v for k, v in value.items() if k != "ts"}


# ── pure helpers ───────────────────────────────────────────────────────────

class TestMapping:
    @pytest.mark.parametrize("level, expected", [
        (0, 0), (1, 20), (3, 60), (5, 100),
        (7, 100), (-1, 0), (2.6, 60),                  # clamped / rounded
        (True, None), ("3", None), (None, None), (float("nan"), None), ([3], None),
    ])
    def test_battery_level_to_percent(self, level, expected):
        assert battery_pct_from_level(level) == expected

    @pytest.mark.parametrize("value, expected", [
        (80, 80), (0, 0), (100, 100), (150, 100), (-5, 0), (79.6, 80),
        (True, None), ("80", None), (float("inf"), None), (None, None),
    ])
    def test_percent(self, value, expected):
        assert percent(value) == expected

    @pytest.mark.parametrize("value, expected", [
        ("Orange PL", "Orange PL"),
        ("  Orange\x00 \n PL\t", "Orange PL"),               # control chars, whitespace
        ("‮LP egnarO", "LP egnarO"),                     # bidi override removed
        ("Play" + " " * 20 + "x" * 40, "Play " + "x" * 19),  # collapsed, then <= 24
        ("A" * 100, "A" * 24),
        ("", None), ("   ", None), ("\x07\x1b", None),
        (None, None), (42, None), (b"Orange", None),
        ("<img src=x onerror=alert(1)>", "<img src=x onerror=alert"),   # text, UI uses textContent
    ])
    def test_operator_is_cleaned(self, value, expected):
        got = clean_operator(value)
        assert got == expected
        if got is not None:
            assert len(got) <= ps.OPERATOR_MAX

    @pytest.mark.parametrize("value, expected", [
        ("registered", "registered"), ("Roaming", "roaming"), (" searching ", "searching"),
        ("denied", "denied"), ("unregistered", "unregistered"), ("unknown", "unknown"),
        ("<b>", "unknown"), ("", "unknown"), (None, None), (5, None),
    ])
    def test_registration(self, value, expected):
        assert registration_of(value) == expected


class TestModemByMac:
    def test_picks_the_phone_among_several(self):
        modems = [
            ("/hfp/org/bluez/hci0/dev_AA_BB_CC_DD_EE_02", {"Interfaces": [HF, NR]}),
            ("/ril_0", {"Interfaces": [NR]}),
            (PATH, {"Interfaces": [HF]}),
            ("/hfp/org/bluez/hci0/dev_AA_BB_CC_DD_EE_010", {"Interfaces": [HF, NR]}),
        ]
        assert modem_for_mac(modems, PHONE) == (PATH, {"Interfaces": [HF]})
        assert modem_for_mac(modems, OTHER)[0].endswith("EE_02")

    def test_hex_case_does_not_matter(self):
        path = "/hfp/org/bluez/hci1/dev_aa_bb_cc_dd_ee_01"
        assert modem_for_mac([(path, {})], PHONE) == (path, {})

    def test_the_one_with_interfaces_wins_a_tie(self):
        modems = [(PATH, {"Interfaces": []}),
                  ("/hfp/org/bluez/hci1/dev_AA_BB_CC_DD_EE_01", {"Interfaces": [HF, NR]})]
        assert modem_for_mac(modems, PHONE)[0].startswith("/hfp/org/bluez/hci1/")

    @pytest.mark.parametrize("modems", [
        [], None, "nope", [("only-one",)], [(None, {})], [(PATH * 20, {})],
        [("/hfp/dev_AA_BB_CC_DD_EE_011", {})],
    ])
    def test_garbage_or_no_match(self, modems):
        assert modem_for_mac(modems, PHONE) is None


# ── one read through the reader ──────────────────────────────────────────

class TestReadPhoneStatus:
    def test_full_ofono_record(self):
        record, down = read_phone_status(FakeReader(), PHONE)
        assert down == set()
        assert record == {"available": True, "battery_pct": 60, "signal_pct": 80,
                          "operator": "Orange PL", "registration": "registered",
                          "roaming": False, "source": "ofono"}

    def test_roaming(self):
        r = FakeReader()
        r.props[(PATH, NR)]["Status"] = "roaming"
        record, _ = read_phone_status(r, PHONE)
        assert record["registration"] == "roaming" and record["roaming"] is True

    def test_ag_without_signal_and_operator(self):
        """An AG may report neither: those fields stay None, the battery shows."""
        r = FakeReader()
        r.props[(PATH, NR)] = {"Status": "registered"}
        record, _ = read_phone_status(r, PHONE)
        assert record["signal_pct"] is None and record["operator"] is None
        assert record["battery_pct"] == 60 and record["source"] == "ofono"

    def test_only_the_listed_interfaces_are_asked(self):
        r = FakeReader()
        r.modems = [(PATH, {"Interfaces": [HF]})]
        record, _ = read_phone_status(r, PHONE)
        assert ("props", PATH, NR) not in r.calls
        assert record["battery_pct"] == 60 and record["signal_pct"] is None
        assert record["registration"] is None and record["roaming"] is None

    def test_other_phones_modem_is_never_read(self):
        r = FakeReader()
        r.modems = [(OTHER_PATH, {"Interfaces": [HF, NR]})]
        r.props = {(OTHER_PATH, HF): {"BatteryChargeLevel": 5}}
        record, _ = read_phone_status(r, PHONE)
        assert not any(c[0] == "props" for c in r.calls)
        assert record == ps.UNAVAILABLE

    def test_bluez_fallback_without_ofono_modem(self):
        r = FakeReader()
        r.modems = []
        r.bluez = {PHONE: 45}
        record, down = read_phone_status(r, PHONE)
        assert down == set()
        assert record == {"available": True, "battery_pct": 45, "signal_pct": None,
                          "operator": None, "registration": None, "roaming": None,
                          "source": "bluez"}

    def test_bluez_fallback_when_ofono_is_not_running(self):
        r = FakeReader()
        r.ofono_up = False
        r.bluez = {PHONE: 77}
        record, down = read_phone_status(r, PHONE)
        assert down == {"ofono"}
        assert record["battery_pct"] == 77 and record["source"] == "bluez"

    def test_bluez_fills_a_missing_ofono_battery(self):
        r = FakeReader()
        r.props[(PATH, HF)] = {}
        r.bluez = {PHONE: 30}
        record, _ = read_phone_status(r, PHONE)
        assert record["battery_pct"] == 30 and record["signal_pct"] == 80
        assert record["source"] == "ofono"

    def test_bluez_not_asked_when_ofono_has_the_battery(self):
        r = FakeReader()
        read_phone_status(r, PHONE)
        assert not any(c[0] == "bluez" for c in r.calls)

    def test_nothing_reachable(self):
        r = FakeReader()
        r.ofono_up = r.bluez_up = False
        record, down = read_phone_status(r, PHONE)
        assert record == ps.UNAVAILABLE and down == {"ofono", "bluez"}

    def test_failing_calls_leave_fields_empty(self):
        r = FakeReader()
        r.fail = {"props", "bluez"}
        record, down = read_phone_status(r, PHONE)
        assert record == ps.UNAVAILABLE and down == set()

    def test_garbage_property_values(self):
        r = FakeReader()
        r.props[(PATH, HF)] = {"BatteryChargeLevel": "full"}
        r.props[(PATH, NR)] = {"Strength": 250, "Name": "\x1b[31mEvil\x1b[0m",
                               "Status": ["registered"]}
        r.bluez = {PHONE: True}
        record, _ = read_phone_status(r, PHONE)
        assert record["battery_pct"] is None              # not 1 %
        assert record["signal_pct"] == 100
        assert record["operator"] == "[31mEvil [0m"      # no ESC chars left
        assert record["registration"] is None


# ── the monitor ───────────────────────────────────────────────────────────

class TestMonitor:
    def test_no_phone_publishes_unavailable_once(self):
        mon, bus, seen = make()
        mon.tick()
        mon.tick()
        assert [strip_ts(v) for v in seen] == [ps.UNAVAILABLE]
        assert mon.next_wait() is None
        assert mon._reader.calls == []

    def test_connected_reads_and_publishes(self):
        mon, bus, seen = make()
        bus.publish("bt.connected", {"address": PHONE, "name": "Pixel"})
        mon.tick()
        assert strip_ts(seen[-1]) == {"available": True, "battery_pct": 60, "signal_pct": 80,
                                      "operator": "Orange PL", "registration": "registered",
                                      "roaming": False, "source": "ofono"}
        assert seen[-1]["ts"] == 1_700_000_000.0
        assert mon.next_wait() == 20.0

    def test_publishes_only_on_change(self):
        mon, bus, seen = make()
        bus.publish("bt.connected", {"address": PHONE})
        mon.tick()
        mon.tick()
        mon.tick()
        assert len(seen) == 1
        mon._reader.props[(PATH, HF)]["BatteryChargeLevel"] = 2
        mon._wall.t += 60
        mon.tick()
        assert len(seen) == 2
        assert seen[-1]["battery_pct"] == 40 and seen[-1]["ts"] == 1_700_000_060.0
        mon.tick()
        assert len(seen) == 2

    def test_disconnect_publishes_unavailable_and_stops_polling(self):
        mon, bus, seen = make()
        bus.publish("bt.connected", {"address": PHONE})
        mon.tick()
        reads = len(mon._reader.calls)
        bus.publish("bt.disconnected", {"address": PHONE})
        mon.tick()
        assert strip_ts(seen[-1]) == ps.UNAVAILABLE
        assert mon.next_wait() is None
        mon.tick()
        assert len(mon._reader.calls) == reads           # nothing read while gone
        assert len(seen) == 2

    def test_disconnect_of_another_device_is_ignored(self):
        mon, bus, seen = make()
        bus.publish("bt.connected", {"address": PHONE})
        mon.tick()
        bus.publish("bt.disconnected", {"address": OTHER})
        mon.tick()
        assert seen[-1]["available"] is True

    def test_bt_connected_false_means_gone(self):
        mon, bus, seen = make()
        bus.publish("bt.connected", {"address": PHONE})
        mon.tick()
        bus.publish("bt.connected", False)
        mon.tick()
        assert seen[-1]["available"] is False

    def test_invalid_address_never_reaches_the_reader(self, caplog):
        mon, bus, seen = make()
        bus.publish("bt.connected", {"address": "AA:BB/../../x"})
        with caplog.at_level(logging.WARNING):
            mon.tick()
            mon.tick()
        assert mon._reader.calls == []
        assert seen[-1]["available"] is False
        assert len([r for r in caplog.records if "invalid phone address" in r.message]) == 1

    def test_last_bt_device_when_the_event_has_no_address(self):
        mon, bus, seen = make(config={"multimedia": {"last_bt_device": PHONE.lower()}})
        bus.publish("bt.connected", {"name": "Pixel"})
        mon.tick()
        assert seen[-1]["available"] is True
        assert ("bluez", PHONE) not in mon._reader.calls

    def test_read_straddling_a_disconnect_is_dropped(self):
        mon, bus, seen = make()
        bus.publish("bt.connected", {"address": PHONE})
        mon._reader.on_modems = lambda: bus.publish("bt.disconnected", {"address": PHONE})
        mon.tick()
        assert all(v["available"] is False for v in seen)
        mon._reader.on_modems = None
        mon.tick()
        assert strip_ts(seen[-1]) == ps.UNAVAILABLE

    def test_service_down_slow_retry_and_one_warning(self, caplog):
        r = FakeReader()
        r.ofono_up = r.bluez_up = False
        mon, bus, seen = make(reader=r)
        bus.publish("bt.connected", {"address": PHONE})
        with caplog.at_level(logging.WARNING):
            for _ in range(5):
                mon.tick()
        assert mon.next_wait() == 120.0
        assert [strip_ts(v) for v in seen] == [ps.UNAVAILABLE]
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1 and "neither oFono nor BlueZ" in warnings[0].message
        # The services come back: normal polling, data published.
        r.ofono_up = r.bluez_up = True
        mon.tick()
        assert seen[-1]["available"] is True and mon.next_wait() == 20.0

    def test_ofono_down_with_bluez_battery_warns_once(self, caplog):
        r = FakeReader()
        r.ofono_up = False
        r.bluez = {PHONE: 88}
        mon, bus, seen = make(reader=r)
        bus.publish("bt.connected", {"address": PHONE})
        with caplog.at_level(logging.WARNING):
            mon.tick()
            mon.tick()
        assert seen[-1]["source"] == "bluez" and seen[-1]["battery_pct"] == 88
        assert mon.next_wait() == 20.0
        assert len([r for r in caplog.records if "oFono not reachable" in r.message]) == 1

    def test_without_dbus_python_nothing_crashes(self, monkeypatch, caplog):
        """The default reader on a machine without dbus-python."""
        monkeypatch.setattr(ps, "HAS_DBUS", False)
        monkeypatch.setattr(ps, "dbus", None)
        bus = EventBus()
        seen = published(bus)
        mon = PhoneStatusMonitor({}, bus)            # default DBusPhoneReader
        for topic, cb in mon._subscriptions():
            bus.subscribe(topic, cb)
        bus.publish("bt.connected", {"address": PHONE})
        with caplog.at_level(logging.WARNING):
            mon.tick()
            mon.tick()
        assert [strip_ts(v) for v in seen] == [ps.UNAVAILABLE]
        assert mon.next_wait() == mon.retry_sec
        warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1 and "dbus-python not installed" in warnings[0]

    def test_a_crashing_reader_does_not_kill_the_pass(self):
        class Broken(FakeReader):
            def ofono_modems(self):
                raise KeyError("boom")

            def bluez_battery(self, mac):
                raise ValueError("boom")
        mon, bus, seen = make(reader=Broken())
        bus.publish("bt.connected", {"address": PHONE})
        assert mon.tick()["available"] is False

    def test_seed_from_bus(self):
        bus = EventBus()
        bus.publish("bt.connected", {"address": PHONE})
        mon, _, seen = make(bus=bus)
        mon.seed_from_bus()
        mon.tick()
        assert seen[-1]["available"] is True

    def test_seed_ignores_an_older_connect(self):
        bus = EventBus()
        bus.publish("bt.connected", {"address": PHONE})
        time.sleep(0.01)
        bus.publish("bt.disconnected", {"address": PHONE})
        mon, _, seen = make(bus=bus)
        mon.seed_from_bus()
        mon.tick()
        assert seen[-1]["available"] is False

    @pytest.mark.parametrize("section, poll, retry", [
        ({}, 20.0, 120.0),
        ({"poll_sec": 1, "retry_sec": 10**6}, 5.0, 3600.0),
        ({"poll_sec": "fast", "retry_sec": True}, 20.0, 120.0),
        ({"poll_sec": 300, "retry_sec": 60}, 300.0, 300.0),      # retry >= poll
        ("nope", 20.0, 120.0),
    ])
    def test_config_values_are_clamped(self, section, poll, retry):
        mon = PhoneStatusMonitor({"bluetooth": {"phone_status": section}}, EventBus(),
                                 reader=FakeReader())
        assert (mon.poll_sec, mon.retry_sec) == (poll, retry)


class TestLifecycle:
    def _wait_for(self, predicate, timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.01)
        return False

    def test_thread_reads_on_connect_and_hides_on_stop(self):
        bus = EventBus()
        seen = published(bus)
        reader = FakeReader()
        mon = PhoneStatusMonitor({}, bus, reader=reader)
        mon.start()
        try:
            assert self._wait_for(lambda: seen and seen[-1]["available"] is False)
            bus.publish("bt.connected", {"address": PHONE})
            assert self._wait_for(lambda: seen[-1]["available"] is True)
        finally:
            mon.stop()
        mon._thread.join(timeout=5)
        assert not mon._thread.is_alive()
        assert seen[-1]["available"] is False
        assert reader.closed == 1
        n = len(seen)
        bus.publish("bt.connected", {"address": PHONE})       # unsubscribed
        assert len(seen) == n

    def test_shutdown_event_stops_it(self):
        bus = EventBus()
        mon = PhoneStatusMonitor({}, bus, reader=FakeReader())
        mon.start()
        bus.publish("power.shutting_down", True)
        mon._thread.join(timeout=5)
        assert not mon._thread.is_alive()

    def test_stop_without_thread_closes_the_reader(self):
        reader = FakeReader()
        mon = PhoneStatusMonitor({}, EventBus(), reader=reader)
        mon.stop()
        mon.stop()
        assert reader.closed == 1


# ── the default D-Bus reader against a fake dbus module ──────────────────

class FakeDBusError(Exception):
    def __init__(self, name):
        super().__init__(name)
        self._name = name

    def get_dbus_name(self):
        return self._name


class FakeBoolean(int):
    """dbus.Boolean is an int subclass, not a bool."""


class FakeSystemBus:
    def __init__(self, owners, replies):
        self.owners = owners
        self.replies = replies
        self.calls = []
        self.closed = False

    def name_has_owner(self, name):
        self.calls.append(("owner", name))
        return name in self.owners

    def call_blocking(self, service, path, iface, method, signature, args, timeout=-1.0):
        self.calls.append((service, path, iface, method, signature, tuple(args), timeout))
        reply = self.replies[(service, path, iface, method)]
        if isinstance(reply, Exception):
            raise reply
        return reply

    def close(self):
        self.closed = True


@pytest.fixture
def fake_dbus(monkeypatch):
    state = types.SimpleNamespace(buses=[], kwargs=[], owners={"org.ofono", "org.bluez"},
                                  replies={})
    null_loop = object()

    def system_bus(**kwargs):
        state.kwargs.append(kwargs)
        bus = FakeSystemBus(state.owners, state.replies)
        state.buses.append(bus)
        return bus

    module = types.SimpleNamespace(SystemBus=system_bus, Boolean=FakeBoolean,
                                   mainloop=types.SimpleNamespace(NULL_MAIN_LOOP=null_loop))
    monkeypatch.setattr(ps, "dbus", module)
    monkeypatch.setattr(ps, "HAS_DBUS", True)
    state.null_loop = null_loop
    return state


class TestDBusReader:
    def _replies(self, state):
        state.replies.update({
            ("org.ofono", "/", "org.ofono.Manager", "GetModems"): [
                (OTHER_PATH, {"Interfaces": [HF], "Online": FakeBoolean(1)}),
                (PATH, {"Interfaces": [HF, NR], "Powered": FakeBoolean(1)}),
            ],
            ("org.ofono", PATH, HF, "GetProperties"): {"BatteryChargeLevel": 4},
            ("org.ofono", PATH, NR, "GetProperties"): {"Strength": 60, "Name": "Plus",
                                                       "Status": "roaming"},
        })

    def test_private_connection_without_main_loop(self, fake_dbus):
        self._replies(fake_dbus)
        reader = ps.DBusPhoneReader()
        modems = reader.ofono_modems()
        assert fake_dbus.kwargs == [{"private": True, "mainloop": fake_dbus.null_loop}]
        assert modems[1] == (PATH, {"Interfaces": [HF, NR], "Powered": True})
        assert modems[0][1]["Online"] is True                  # dbus.Boolean -> bool
        reader.ofono_modems()
        assert len(fake_dbus.buses) == 1                        # connection reused

    def test_full_read_through_the_monitor(self, fake_dbus):
        self._replies(fake_dbus)
        bus = EventBus()
        seen = published(bus)
        mon = PhoneStatusMonitor({}, bus, reader=ps.DBusPhoneReader())
        for topic, cb in mon._subscriptions():
            bus.subscribe(topic, cb)
        bus.publish("bt.connected", {"address": PHONE})
        mon.tick()
        assert strip_ts(seen[-1]) == {"available": True, "battery_pct": 80, "signal_pct": 60,
                                      "operator": "Plus", "registration": "roaming",
                                      "roaming": True, "source": "ofono"}
        calls = [c for c in fake_dbus.buses[0].calls if c[0] != "owner"]
        assert all(c[4] == "" and c[5] == () and c[6] == ps.DBUS_TIMEOUT_S for c in calls)
        assert all(c[1] != OTHER_PATH for c in calls)

    def test_service_without_owner_is_never_called(self, fake_dbus):
        """No call to a name without an owner: that would D-Bus-activate it."""
        fake_dbus.owners.clear()
        reader = ps.DBusPhoneReader()
        with pytest.raises(ServiceUnavailable):
            reader.ofono_modems()
        with pytest.raises(ServiceUnavailable):
            reader.bluez_battery(PHONE)
        assert all(c[0] == "owner" for c in fake_dbus.buses[0].calls)

    def test_service_unknown_maps_to_unavailable(self, fake_dbus):
        fake_dbus.replies[("org.ofono", "/", "org.ofono.Manager", "GetModems")] = \
            FakeDBusError("org.freedesktop.DBus.Error.ServiceUnknown")
        with pytest.raises(ServiceUnavailable):
            ps.DBusPhoneReader().ofono_modems()

    def test_lost_connection_is_dropped_and_reopened(self, fake_dbus):
        key = ("org.ofono", "/", "org.ofono.Manager", "GetModems")
        fake_dbus.replies[key] = FakeDBusError("org.freedesktop.DBus.Error.Disconnected")
        reader = ps.DBusPhoneReader()
        with pytest.raises(ServiceUnavailable):
            reader.ofono_modems()
        assert fake_dbus.buses[0].closed
        fake_dbus.replies[key] = []
        assert reader.ofono_modems() == []
        assert len(fake_dbus.buses) == 2

    def test_other_errors_propagate_as_failed_reads(self, fake_dbus):
        fake_dbus.replies[("org.ofono", PATH, HF, "GetProperties")] = \
            FakeDBusError("org.freedesktop.DBus.Error.UnknownObject")
        with pytest.raises(FakeDBusError):
            ps.DBusPhoneReader().ofono_properties(PATH, HF)

    def test_no_system_bus(self, fake_dbus, monkeypatch):
        def broken(**kwargs):
            raise FakeDBusError("org.freedesktop.DBus.Error.FileNotFound")
        monkeypatch.setattr(ps.dbus, "SystemBus", broken)
        with pytest.raises(ServiceUnavailable):
            ps.DBusPhoneReader().ofono_modems()

    def test_bluez_battery_by_device_path(self, fake_dbus):
        fake_dbus.replies[("org.bluez", "/", "org.freedesktop.DBus.ObjectManager",
                           "GetManagedObjects")] = {
            "/org/bluez/hci0": {"org.bluez.Adapter1": {}},
            "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_02": {"org.bluez.Battery1": {"Percentage": 10}},
            "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_01/sep1": {"org.bluez.Battery1": {"Percentage": 20}},
            "/org/bluez/hci1/dev_AA_BB_CC_DD_EE_01": {"org.bluez.Device1": {},
                                                      "org.bluez.Battery1": {"Percentage": 67}},
        }
        reader = ps.DBusPhoneReader()
        assert reader.bluez_battery(PHONE) == 67
        assert reader.bluez_battery("AA:BB:CC:DD:EE:03") is None

    def test_close(self, fake_dbus):
        fake_dbus.replies[("org.ofono", "/", "org.ofono.Manager", "GetModems")] = []
        reader = ps.DBusPhoneReader()
        reader.ofono_modems()
        reader.close()
        reader.close()
        assert fake_dbus.buses[0].closed

    def test_plain_is_bounded(self):
        deep = {"a": {"b": {"c": {"d": {"e": {"f": 1}}}}}}
        assert ps._plain(deep) == {"a": {"b": {"c": {"d": {"e": None}}}}}
        assert len(ps._plain(list(range(1000)))) == 64
        assert len(ps._plain("x" * 10_000)) == ps.MAX_RAW_TEXT
        assert ps._plain(b"\x00") is None


# ── dashboard payload + registration ─────────────────────────────────────

class TestSanitizeStatus:
    def test_never_published_is_none(self):
        assert sanitize_status(None) is None
        assert sanitize_status("available") is None

    def test_unavailable(self):
        assert sanitize_status({"available": False, "operator": "<b>x"}) == ps.UNAVAILABLE
        assert sanitize_status({"available": 1, "battery_pct": 50,
                                "source": "ofono"}) == ps.UNAVAILABLE

    def test_good_record_passes(self):
        record = {"available": True, "battery_pct": 60, "signal_pct": 80, "operator": "Orange",
                  "registration": "roaming", "roaming": True, "source": "ofono", "ts": 5}
        out = sanitize_status(record)
        assert out == {k: v for k, v in record.items() if k != "ts"}

    def test_garbage_is_neutralised(self):
        out = sanitize_status({"available": True, "battery_pct": 900, "signal_pct": "x",
                               "operator": "‮" + "E" * 50, "registration": "<script>",
                               "roaming": "yes", "source": "ofono", "extra": "drop me"})
        assert out == {"available": True, "battery_pct": 100, "signal_pct": None,
                       "operator": "E" * 24, "registration": None, "roaming": None,
                       "source": "ofono"}

    def test_unknown_source_means_unavailable(self):
        assert sanitize_status({"available": True, "battery_pct": 5,
                                "source": "evil"}) == ps.UNAVAILABLE

    def test_dashboard_payload(self):
        bus = EventBus()
        cfg = BCMConfig(platform_override="x86")
        viewer = WebViewer(host="127.0.0.1", port=5099, event_bus=bus, config=cfg)
        assert viewer._get_dashboard_data()["phone_status"] is None       # module off
        bus.publish(ps.TOPIC, {"available": True, "battery_pct": 60, "signal_pct": None,
                               "operator": "Orange\x00\x00PL", "registration": "registered",
                               "roaming": False, "source": "ofono", "ts": 1.0})
        assert viewer._get_dashboard_data()["phone_status"] == {
            "available": True, "battery_pct": 60, "signal_pct": None, "operator": "Orange PL",
            "registration": "registered", "roaming": False, "source": "ofono"}


class TestRegistration:
    def test_catalog_entry_is_an_off_by_default_subsystem(self):
        info = modules_catalog.MODULES["phone_status"]
        assert "entry" not in info and info["default"] is False
        state = {m["name"]: m for m in
                 modules_catalog.catalog_state(BCMConfig(platform_override="x86"))}
        assert state["phone_status"]["kind"] == "subsystem"
        assert state["phone_status"]["enabled"] is False

    def test_production_off_test_config_on(self):
        prod = BCMConfig(config_path=str(REPO / "config" / "bcm_config.yaml"),
                         platform_override="x86")
        test = BCMConfig(config_path=str(REPO / "config" / "bcm_config_test.yaml"),
                         platform_override="x86")
        assert modules_catalog.is_enabled(prod, "phone_status") is False
        assert modules_catalog.is_enabled(test, "phone_status") is True
        assert modules_catalog.is_enabled(test, "bluetooth") is True

    def test_test_config_block_is_read(self):
        cfg = BCMConfig(config_path=str(REPO / "config" / "bcm_config_test.yaml"),
                        platform_override="x86")
        mon = PhoneStatusMonitor(cfg, EventBus(), reader=FakeReader())
        assert (mon.poll_sec, mon.retry_sec) == (20.0, 120.0)

    def test_main_starts_it_only_with_bluetooth(self):
        text = (REPO / "main.py").read_text(encoding="utf-8")
        # The catalog says it requires bluetooth; main.py starts it only when
        # the dependency check (plan_modules) says it runs.
        assert modules_catalog.MODULES["phone_status"]["requires"] == ("bluetooth",)
        assert 'if _runs("phone_status"):' in text
        assert "start_phone_status(config, event_bus)" in text

    def test_entry_point_starts_the_monitor(self):
        bus = EventBus()
        mon = ps.start_phone_status({}, bus, reader=FakeReader())
        try:
            assert isinstance(mon._thread, threading.Thread) and mon._thread.is_alive()
            assert mon._on_bt_connected in bus._subscribers["bt.connected"]
        finally:
            mon.stop()
