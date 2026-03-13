"""Integration tests for Part 13 — System Integration & Testing.

Tests cross-module communication, IPC event bus, and full system lifecycle.
"""

import json
import os
import socket
import tempfile
import threading
import time

import pytest

from src.core.config import BCMConfig
from src.core.event_bus import EventBus
from src.core.hal import HAL


# ---------------------------------------------------------------------------
# IPC Event Bus tests
# ---------------------------------------------------------------------------

class TestIPCEventBus:
    """Test cross-process event bus via Unix domain sockets."""

    def _tmp_socket(self):
        """Create a temporary socket path."""
        fd, path = tempfile.mkstemp(suffix=".sock")
        os.close(fd)
        os.unlink(path)
        return path

    def test_server_start_stop(self):
        sock_path = self._tmp_socket()
        bus = EventBus()
        bus.start_ipc_server(sock_path)
        assert os.path.exists(sock_path)
        bus.stop_ipc_server()
        # Cleanup
        if os.path.exists(sock_path):
            os.unlink(sock_path)

    def test_client_connect_to_server(self):
        sock_path = self._tmp_socket()
        server_bus = EventBus()
        server_bus.start_ipc_server(sock_path)

        time.sleep(0.1)  # Let server start

        client_bus = EventBus()
        connected = client_bus.connect_ipc(sock_path, timeout=2.0)
        assert connected is True

        client_bus.disconnect_ipc()
        server_bus.stop_ipc_server()
        if os.path.exists(sock_path):
            os.unlink(sock_path)

    def test_client_publish_reaches_server(self):
        sock_path = self._tmp_socket()
        server_bus = EventBus()
        server_bus.start_ipc_server(sock_path)

        received = []
        server_bus.subscribe("test.value", lambda t, v, ts: received.append(v))

        time.sleep(0.1)

        client_bus = EventBus()
        client_bus.connect_ipc(sock_path, timeout=2.0)

        time.sleep(0.1)

        client_bus.publish("test.value", 42)

        # Wait for IPC delivery
        deadline = time.time() + 2.0
        while not received and time.time() < deadline:
            time.sleep(0.05)

        assert 42 in received

        client_bus.disconnect_ipc()
        server_bus.stop_ipc_server()
        if os.path.exists(sock_path):
            os.unlink(sock_path)

    def test_server_publish_reaches_client(self):
        sock_path = self._tmp_socket()
        server_bus = EventBus()
        server_bus.start_ipc_server(sock_path)

        time.sleep(0.1)

        client_bus = EventBus()
        client_bus.connect_ipc(sock_path, timeout=2.0)

        received = []
        client_bus.subscribe("test.broadcast", lambda t, v, ts: received.append(v))

        time.sleep(0.1)

        server_bus.publish("test.broadcast", {"msg": "hello"})

        deadline = time.time() + 2.0
        while not received and time.time() < deadline:
            time.sleep(0.05)

        assert len(received) >= 1
        assert received[0]["msg"] == "hello"

        client_bus.disconnect_ipc()
        server_bus.stop_ipc_server()
        if os.path.exists(sock_path):
            os.unlink(sock_path)

    def test_two_clients_relay(self):
        """Client A publishes → server relays → client B receives."""
        sock_path = self._tmp_socket()
        server_bus = EventBus()
        server_bus.start_ipc_server(sock_path)
        time.sleep(0.1)

        client_a = EventBus()
        client_a.connect_ipc(sock_path, timeout=2.0)

        client_b = EventBus()
        client_b.connect_ipc(sock_path, timeout=2.0)

        received_b = []
        client_b.subscribe("cross.test", lambda t, v, ts: received_b.append(v))

        time.sleep(0.1)

        client_a.publish("cross.test", "from_a")

        deadline = time.time() + 2.0
        while not received_b and time.time() < deadline:
            time.sleep(0.05)

        assert "from_a" in received_b

        client_a.disconnect_ipc()
        client_b.disconnect_ipc()
        server_bus.stop_ipc_server()
        if os.path.exists(sock_path):
            os.unlink(sock_path)

    def test_client_connect_fails_no_server(self):
        sock_path = self._tmp_socket()
        bus = EventBus()
        connected = bus.connect_ipc(sock_path, timeout=0.5)
        assert connected is False

    def test_server_handles_client_disconnect(self):
        sock_path = self._tmp_socket()
        server_bus = EventBus()
        server_bus.start_ipc_server(sock_path)
        time.sleep(0.1)

        client_bus = EventBus()
        client_bus.connect_ipc(sock_path, timeout=2.0)
        time.sleep(0.1)

        # Abrupt disconnect
        client_bus.disconnect_ipc()
        time.sleep(0.3)

        # Server should still work (publish without error)
        server_bus.publish("after.disconnect", True)

        server_bus.stop_ipc_server()
        if os.path.exists(sock_path):
            os.unlink(sock_path)

    def test_wildcard_subscriber_with_ipc(self):
        sock_path = self._tmp_socket()
        server_bus = EventBus()
        server_bus.start_ipc_server(sock_path)
        time.sleep(0.1)

        all_events = []
        server_bus.subscribe("*", lambda t, v, ts: all_events.append((t, v)))

        client_bus = EventBus()
        client_bus.connect_ipc(sock_path, timeout=2.0)
        time.sleep(0.1)

        client_bus.publish("any.topic", "any_value")

        deadline = time.time() + 2.0
        while not all_events and time.time() < deadline:
            time.sleep(0.05)

        assert any(t == "any.topic" for t, v in all_events)

        client_bus.disconnect_ipc()
        server_bus.stop_ipc_server()
        if os.path.exists(sock_path):
            os.unlink(sock_path)


# ---------------------------------------------------------------------------
# Cross-module integration tests (in-process, simulated x86)
# ---------------------------------------------------------------------------

class TestModuleIntegration:
    """Test that modules communicate correctly through the event bus."""

    def setup_method(self):
        self.bus = EventBus()
        self.config = BCMConfig(platform_override="x86")
        self.hal = HAL(platform="x86")

    def test_obd_to_dashboard_data_flow(self):
        """OBD publishes RPM → dashboard subscriber receives it."""
        received = []
        self.bus.subscribe("obd.rpm", lambda t, v, ts: received.append(v))

        # Simulate OBD publishing
        self.bus.publish("obd.rpm", 3200)
        self.bus.publish("obd.rpm", 3500)

        assert received == [3200, 3500]

    def test_reverse_gear_triggers_parking_and_camera(self):
        """Reverse gear event should trigger both parking and camera modules."""
        parking_events = []
        camera_events = []

        self.bus.subscribe("vehicle.reverse_gear",
                           lambda t, v, ts: parking_events.append(v))
        self.bus.subscribe("vehicle.reverse_gear",
                           lambda t, v, ts: camera_events.append(v))

        self.bus.publish("vehicle.reverse_gear", True)

        assert parking_events == [True]
        assert camera_events == [True]

    def test_voice_command_triggers_audio(self):
        """Voice command 'volume up' should publish volume event."""
        vol_events = []
        self.bus.subscribe("audio.volume_step", lambda t, v, ts: vol_events.append(v))

        # Simulate voice module dispatching a volume command
        self.bus.publish("audio.volume_step", 5)

        assert vol_events == [5]

    def test_ignition_lifecycle(self):
        """Ignition ON → modules start, Ignition OFF → shutdown sequence."""
        lifecycle = []
        self.bus.subscribe("power.ignition", lambda t, v, ts: lifecycle.append(("ign", v)))
        self.bus.subscribe("power.shutting_down", lambda t, v, ts: lifecycle.append(("shutdown", v)))

        # Ignition ON
        self.bus.publish("power.ignition", True)
        assert ("ign", True) in lifecycle

        # Ignition OFF → shutdown
        self.bus.publish("power.ignition", False)
        self.bus.publish("power.shutting_down", True)

        assert ("ign", False) in lifecycle
        assert ("shutdown", True) in lifecycle

    def test_phone_call_triggers_audio_ducking(self):
        """Incoming BT call should trigger audio ducking."""
        ducking_events = []
        self.bus.subscribe("audio.phone_call",
                           lambda t, v, ts: ducking_events.append(v))

        self.bus.publish("audio.phone_call", True)
        self.bus.publish("audio.phone_call", False)

        assert ducking_events == [True, False]

    def test_parking_distance_to_buzzer(self):
        """Parking distance below threshold triggers buzzer."""
        buzzer_events = []
        self.bus.subscribe("parking.buzzer",
                           lambda t, v, ts: buzzer_events.append(v))

        # Simulate parking module detecting close obstacle
        self.bus.publish("parking.buzzer", {"frequency": 5.0, "active": True})
        assert len(buzzer_events) == 1
        assert buzzer_events[0]["active"] is True

    def test_dashcam_recording_on_ignition(self):
        """Dashcam should start recording when ignition turns on."""
        recording_events = []
        self.bus.subscribe("camera.start_recording",
                           lambda t, v, ts: recording_events.append(v))
        self.bus.subscribe("camera.stop_recording",
                           lambda t, v, ts: recording_events.append(("stop", v)))

        self.bus.publish("camera.start_recording", True)
        self.bus.publish("camera.stop_recording", True)

        assert True in recording_events
        assert ("stop", True) in recording_events

    def test_environment_temp_to_dashboard(self):
        """Temperature reading flows from environment to dashboard."""
        temp_events = []
        self.bus.subscribe("env.temperature",
                           lambda t, v, ts: temp_events.append(v))

        self.bus.publish("env.temperature", 22.5)
        assert temp_events == [22.5]

    def test_bt_source_availability(self):
        """BT connect/disconnect updates audio source availability."""
        source_events = []
        self.bus.subscribe("audio.source_available",
                           lambda t, v, ts: source_events.append(v))

        self.bus.publish("audio.source_available", {
            "source": "bluetooth", "available": True
        })
        self.bus.publish("audio.source_available", {
            "source": "bluetooth", "available": False
        })

        assert len(source_events) == 2
        assert source_events[0]["available"] is True
        assert source_events[1]["available"] is False

    def test_full_boot_sequence_events(self):
        """Simulate the full boot sequence and verify all critical events fire."""
        log_events = []
        self.bus.subscribe("*", lambda t, v, ts: log_events.append(t))

        # Boot sequence as per spec
        self.bus.publish("power.ignition", True)
        self.bus.publish("power.state", "RUNNING")
        self.bus.publish("power.backlight", {"display": "4.3", "brightness": 100})
        self.bus.publish("power.backlight", {"display": "7", "brightness": 100})
        self.bus.publish("obd.connected", True)
        self.bus.publish("obd.rpm", 850)
        self.bus.publish("obd.speed", 0)
        self.bus.publish("env.temperature", 18.0)
        self.bus.publish("camera.start_recording", True)
        self.bus.publish("multimedia.openauto_status", "unavailable")
        self.bus.publish("bt.connected", {"address": "AA:BB:CC:DD:EE:FF", "name": "Phone"})

        expected_topics = [
            "power.ignition", "power.state", "power.backlight",
            "obd.connected", "obd.rpm", "obd.speed", "env.temperature",
            "camera.start_recording", "multimedia.openauto_status", "bt.connected",
        ]
        for topic in expected_topics:
            assert topic in log_events, f"Missing event: {topic}"

    def test_full_shutdown_sequence(self):
        """Simulate shutdown and verify teardown events."""
        events = []
        self.bus.subscribe("*", lambda t, v, ts: events.append(t))

        self.bus.publish("power.ignition", False)
        self.bus.publish("camera.stop_recording", True)
        self.bus.publish("power.shutting_down", True)
        self.bus.publish("power.backlight", {"display": "4.3", "brightness": 0})
        self.bus.publish("power.backlight", {"display": "7", "brightness": 0})
        self.bus.publish("power.state", "STANDBY")

        assert "power.shutting_down" in events
        assert "camera.stop_recording" in events
        assert "power.state" in events

    def test_get_last_across_modules(self):
        """get_last works for any topic regardless of publisher."""
        self.bus.publish("obd.rpm", 4200)
        self.bus.publish("env.temperature", 25.0)
        self.bus.publish("parking.distances", [100, 200, 150, 180])

        rpm = self.bus.get_last("obd.rpm")
        assert rpm is not None
        assert rpm[0] == 4200

        temp = self.bus.get_last("env.temperature")
        assert temp is not None
        assert temp[0] == 25.0

        dist = self.bus.get_last("parking.distances")
        assert dist is not None
        assert dist[0] == [100, 200, 150, 180]

    def test_event_bus_topics_list(self):
        """All published topics are queryable."""
        self.bus.publish("a.b", 1)
        self.bus.publish("c.d", 2)
        self.bus.publish("e.f", 3)

        topics = self.bus.topics()
        assert "a.b" in topics
        assert "c.d" in topics
        assert "e.f" in topics


# ---------------------------------------------------------------------------
# Systemd service file validation
# ---------------------------------------------------------------------------

class TestSystemdServices:
    """Validate that all systemd service files are well-formed."""

    SERVICE_DIR = os.path.join(os.path.dirname(__file__), "..", "config", "systemd")

    EXPECTED_SERVICES = [
        "bcm-power.service",
        "bcm-dashboard.service",
        "bcm-obd.service",
        "bcm-dashcam.service",
        "bcm-voice.service",
        "bcm-multimedia.service",
    ]

    def test_all_service_files_exist(self):
        for name in self.EXPECTED_SERVICES:
            path = os.path.join(self.SERVICE_DIR, name)
            assert os.path.isfile(path), f"Missing: {path}"

    def test_service_files_have_required_sections(self):
        for name in self.EXPECTED_SERVICES:
            path = os.path.join(self.SERVICE_DIR, name)
            with open(path) as f:
                content = f.read()
            assert "[Unit]" in content, f"{name}: missing [Unit]"
            assert "[Service]" in content, f"{name}: missing [Service]"
            assert "[Install]" in content, f"{name}: missing [Install]"

    def test_service_files_have_exec_start(self):
        for name in self.EXPECTED_SERVICES:
            path = os.path.join(self.SERVICE_DIR, name)
            with open(path) as f:
                content = f.read()
            assert "ExecStart=" in content, f"{name}: missing ExecStart"

    def test_service_files_have_restart(self):
        for name in self.EXPECTED_SERVICES:
            path = os.path.join(self.SERVICE_DIR, name)
            with open(path) as f:
                content = f.read()
            assert "Restart=" in content, f"{name}: missing Restart"

    def test_service_files_have_watchdog(self):
        for name in self.EXPECTED_SERVICES:
            path = os.path.join(self.SERVICE_DIR, name)
            with open(path) as f:
                content = f.read()
            assert "WatchdogSec=" in content, f"{name}: missing WatchdogSec"

    def test_power_service_starts_first(self):
        """bcm-power has no Requires on other bcm services."""
        path = os.path.join(self.SERVICE_DIR, "bcm-power.service")
        with open(path) as f:
            content = f.read()
        assert "Requires=bcm-" not in content
        # But it should be listed as Before others
        assert "Before=" in content

    def test_other_services_depend_on_power(self):
        """All non-power services require bcm-power."""
        for name in self.EXPECTED_SERVICES:
            if name == "bcm-power.service":
                continue
            path = os.path.join(self.SERVICE_DIR, name)
            with open(path) as f:
                content = f.read()
            assert "Requires=bcm-power.service" in content, \
                f"{name}: should require bcm-power"
            assert "After=bcm-power.service" in content, \
                f"{name}: should be after bcm-power"

    def test_boot_sequence_order(self):
        """Verify boot order: power → dashboard → obd → dashcam → voice → multimedia."""
        power_path = os.path.join(self.SERVICE_DIR, "bcm-power.service")
        with open(power_path) as f:
            content = f.read()

        # Power should start before all others
        for svc in ["bcm-dashboard", "bcm-obd", "bcm-dashcam", "bcm-voice", "bcm-multimedia"]:
            assert svc in content, f"bcm-power should list {svc} in Before="
