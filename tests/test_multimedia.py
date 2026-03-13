"""Tests for Multimedia module (Part 11) — Bluetooth + OpenAuto."""

import pytest

from src.core.event_bus import EventBus
from src.core.config import BCMConfig
from src.multimedia.bluetooth import BluetoothManager
from src.multimedia.openauto import OpenAutoController, _find_openauto


# ---------------------------------------------------------------------------
# Bluetooth Manager tests
# ---------------------------------------------------------------------------

class TestBluetoothManager:
    def setup_method(self):
        self.bus = EventBus()
        self.config = BCMConfig(platform_override="x86")

    def test_initial_state(self):
        bt = BluetoothManager(self.config, self.bus)
        assert bt.connected is False
        assert bt.connected_device is None
        assert bt.a2dp_active is False
        assert bt.hfp_active is False

    def test_simulated_connect(self):
        bt = BluetoothManager(self.config, self.bus)
        # On x86 without real BT, will be simulated
        events = []
        self.bus.subscribe("bt.connected", lambda t, v, ts: events.append(("connected", v)))
        self.bus.subscribe("bt.a2dp_active", lambda t, v, ts: events.append(("a2dp", v)))

        result = bt.connect("AA:BB:CC:DD:EE:FF")

        if not bt.available:
            # Simulated mode — always succeeds
            assert result is True
            assert bt.connected is True
            assert bt.a2dp_active is True
            assert bt.connected_device["address"] == "AA:BB:CC:DD:EE:FF"
            assert any(e[0] == "connected" for e in events)
            assert any(e[0] == "a2dp" and e[1] is True for e in events)
        # If real BT is available, result depends on actual device

    def test_simulated_disconnect(self):
        bt = BluetoothManager(self.config, self.bus)
        bt.connect("AA:BB:CC:DD:EE:FF")

        events = []
        self.bus.subscribe("bt.disconnected", lambda t, v, ts: events.append(("disconnected", v)))
        self.bus.subscribe("bt.a2dp_active", lambda t, v, ts: events.append(("a2dp", v)))

        bt.disconnect()

        assert bt.connected is False
        assert bt.a2dp_active is False
        assert bt.connected_device is None
        assert any(e[0] == "disconnected" for e in events)

    def test_disconnect_when_not_connected(self):
        bt = BluetoothManager(self.config, self.bus)
        # Should not raise
        bt.disconnect()
        assert bt.connected is False

    def test_paired_devices_empty_when_unavailable(self):
        bt = BluetoothManager(self.config, self.bus)
        if not bt.available:
            devices = bt.get_paired_devices()
            assert devices == []

    def test_hfp_call_events(self):
        bt = BluetoothManager(self.config, self.bus)
        bt.connect("AA:BB:CC:DD:EE:FF")

        hfp_events = []
        self.bus.subscribe("bt.hfp_active", lambda t, v, ts: hfp_events.append(v))
        call_events = []
        self.bus.subscribe("audio.phone_call", lambda t, v, ts: call_events.append(v))

        # Simulate incoming call
        self.bus.publish("bt.call_incoming", True)

        assert bt.hfp_active is True
        assert True in hfp_events
        assert True in call_events

        # Simulate call end
        self.bus.publish("bt.call_ended", True)

        assert bt.hfp_active is False
        assert False in hfp_events
        assert False in call_events

    def test_discoverable_simulated(self):
        bt = BluetoothManager(self.config, self.bus)
        if not bt.available:
            assert bt.enable_discoverable(timeout=10) is True

    def test_monitor_start_stop(self):
        bt = BluetoothManager(self.config, self.bus)
        bt.start_monitor()
        bt.stop_monitor()
        # Should not raise


# ---------------------------------------------------------------------------
# OpenAuto Controller tests
# ---------------------------------------------------------------------------

class TestOpenAutoController:
    def setup_method(self):
        self.bus = EventBus()
        self.config = BCMConfig(platform_override="x86")

    def test_find_openauto_not_installed(self):
        """On test machines, OpenAuto is typically not installed."""
        # _find_openauto may or may not find it
        result = _find_openauto()
        # We just ensure it returns str or None
        assert result is None or isinstance(result, str)

    def test_initial_state(self):
        ctrl = OpenAutoController(self.config, self.bus)
        assert ctrl.running is False

    def test_start_without_binary(self):
        ctrl = OpenAutoController(self.config, self.bus)
        if not ctrl.available:
            events = []
            self.bus.subscribe("multimedia.openauto_status",
                               lambda t, v, ts: events.append(v))
            result = ctrl.start()
            assert result is False
            assert "unavailable" in events

    def test_stop_when_not_running(self):
        ctrl = OpenAutoController(self.config, self.bus)
        # Should not raise
        ctrl.stop()
        assert ctrl.running is False

    def test_shutdown_event_stops_openauto(self):
        ctrl = OpenAutoController(self.config, self.bus)
        self.bus.publish("power.shutting_down", True)
        assert ctrl.running is False


# ---------------------------------------------------------------------------
# Integration: start_multimedia entry point
# ---------------------------------------------------------------------------

class TestMultimediaEntryPoint:
    def test_start_multimedia_runs(self):
        from src.multimedia.openauto import start_multimedia
        bus = EventBus()
        config = BCMConfig(platform_override="x86")

        internals = []
        bus.subscribe("multimedia._internals", lambda t, v, ts: internals.append(v))

        start_multimedia(config, bus)

        assert len(internals) == 1
        assert "openauto" in internals[0]
        assert "bluetooth" in internals[0]

        # Cleanup
        internals[0]["openauto"].stop()
        internals[0]["bluetooth"].stop_monitor()
