"""Tests for the always-on Nano JSON bridge (src/vehicle/central_lock.py).

Exercises the JSON line protocol without any real serial port: the
module is constructed but never start()-ed, so ``_serial`` stays None
and ``_send`` runs in mock mode.
"""

import json

import pytest

from src.core.event_bus import EventBus
from src.vehicle.central_lock import CentralLockModule


class _Config:
    def get(self, key, default=None):
        return default


@pytest.fixture()
def module():
    bus = EventBus()
    mod = CentralLockModule(_Config(), bus, hal=None)
    events: list[tuple[str, object]] = []
    for topic in (
        "vehicle.window",
        "vehicle.trunk",
        "vehicle.trunk_denied",
        "vehicle.ble_learned",
        "vehicle.window_code_learned",
        "vehicle.rf_unknown",
    ):
        bus.subscribe(topic, lambda t, v, ts: events.append((t, v)))
    mod._test_events = events
    return mod


def _feed(module, payload: dict):
    """Simulate a JSON line arriving from the Nano."""
    module._handle_response(json.loads(json.dumps(payload)))


class TestInboundEvents:
    def test_window_press(self, module):
        _feed(module, {"event": "window", "slot": "FL_DOWN"})
        assert module._test_events == [
            ("vehicle.window", {"slot": "FL_DOWN", "phase": "press"}),
        ]

    def test_window_release(self, module):
        _feed(module, {"event": "window_release", "slot": "FL_DOWN"})
        assert module._test_events == [
            ("vehicle.window", {"slot": "FL_DOWN", "phase": "release"}),
        ]

    def test_trunk_opened(self, module):
        _feed(module, {"event": "trunk", "rssi": -62})
        assert module._test_events == [
            ("vehicle.trunk", {"opened": True, "rssi": -62}),
        ]

    def test_trunk_denied(self, module):
        _feed(module, {"event": "trunk_denied", "reason": "ble_far", "rssi": -95})
        topic, value = module._test_events[0]
        assert topic == "vehicle.trunk_denied"
        assert value["reason"] == "ble_far"
        assert value["rssi"] == -95

    def test_ble_learned(self, module):
        _feed(module, {"event": "ble_learned", "mac": "AABBCCDDEEFF", "rssi": -55})
        assert module._test_events == [
            ("vehicle.ble_learned", {"mac": "AABBCCDDEEFF", "rssi": -55}),
        ]

    def test_window_code_learned(self, module):
        _feed(module, {"event": "learned", "slot": "RR_UP", "code": 123456})
        assert module._test_events == [
            ("vehicle.window_code_learned", {"slot": "RR_UP", "code": 123456}),
        ]

    def test_rf_unknown(self, module):
        _feed(module, {"event": "rf_unknown", "code": 987654})
        assert module._test_events == [("vehicle.rf_unknown", 987654)]

    def test_ready_publishes_nothing(self, module):
        _feed(module, {"event": "ready", "fw": "1.2.3"})
        assert module._test_events == []

    def test_error_publishes_nothing(self, module):
        _feed(module, {"event": "error", "msg": "boom"})
        assert module._test_events == []

    def test_unknown_event_ignored(self, module):
        _feed(module, {"event": "totally_new_thing"})
        assert module._test_events == []

    def test_missing_event_key_ignored(self, module):
        _feed(module, {"foo": "bar"})
        assert module._test_events == []


class TestOutboundCommands:
    @pytest.fixture()
    def sent(self, module, monkeypatch):
        commands: list[dict] = []
        monkeypatch.setattr(module, "_send", commands.append)
        return commands

    def test_learn_window(self, module, sent):
        module.learn_window("FL_DOWN")
        assert sent == [{"cmd": "learn_window", "slot": "FL_DOWN"}]

    def test_learn_window_empty_slot_not_sent(self, module, sent):
        module.learn_window("")
        assert sent == []

    def test_learn_ble(self, module, sent):
        module.learn_ble()
        assert sent == [{"cmd": "learn_ble"}]

    def test_set_ble_mac(self, module, sent):
        module.set_ble_mac("AABBCCDDEEFF")
        assert sent == [{"cmd": "set_ble_mac", "mac": "AABBCCDDEEFF"}]

    def test_set_ble_mac_rejects_bad_length(self, module, sent):
        module.set_ble_mac("AABB")
        module.set_ble_mac("")
        assert sent == []

    def test_set_ble_rssi(self, module, sent):
        module.set_ble_rssi(-70)
        assert sent == [{"cmd": "set_ble_rssi", "threshold": -70}]

    def test_backlight_event_forwarded(self, module, sent):
        module.bus.publish("power.backlight_brightness",
                           {"display": "small", "brightness": 80})
        assert sent == [
            {"cmd": "backlight", "display": "small", "brightness": 80},
        ]

    def test_backlight_event_malformed_ignored(self, module, sent):
        module.bus.publish("power.backlight_brightness", "not-a-dict")
        module.bus.publish("power.backlight_brightness", {"display": "small"})
        assert sent == []

    def test_learn_window_via_event_bus(self, module, sent):
        module.bus.publish("vehicle.cmd.learn_window", "RL_UP")
        assert sent == [{"cmd": "learn_window", "slot": "RL_UP"}]

    def test_send_without_serial_does_not_raise(self, module):
        # _serial is None (never started) — mock mode must be silent
        module.ping()
