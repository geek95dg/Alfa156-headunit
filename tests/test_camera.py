"""Tests for Camera & Dashcam System (Part 9)."""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from src.core.event_bus import EventBus
from src.core.config import BCMConfig
from src.camera.ahd_grabber import (
    AHDGrabber, list_video_devices,
    DEFAULT_FRONT_DEVICE, DEFAULT_REAR_DEVICE,
    RESOLUTION_720P, RESOLUTION_480P,
)
from src.camera.dashcam import (
    DashcamRecorder, SEGMENT_DURATION_SEC,
    MAX_STORAGE_BYTES, STORAGE_CLEANUP_THRESHOLD,
)
from src.camera.camera_controller import (
    CameraController, ROLE_REAR, ROLE_LEFT, ROLE_RIGHT,
)
from src.camera.reverse_cam import ReverseCamera


# ---------------------------------------------------------------------------
# AHD Grabber tests
# ---------------------------------------------------------------------------

class TestAHDGrabber:
    def setup_method(self):
        self.bus = EventBus()
        self.config = BCMConfig(platform_override="x86")

    def test_init_no_devices(self):
        grabber = AHDGrabber(self.config, self.bus)
        # On CI/test env, likely no video devices
        assert isinstance(grabber.has_front, bool)
        assert isinstance(grabber.has_rear, bool)

    def test_resolution_x86_default(self):
        grabber = AHDGrabber(self.config, self.bus)
        w, h = grabber.get_resolution("front")
        assert w > 0 and h > 0

    def test_resolution_opi(self):
        config = BCMConfig(platform_override="opi")
        grabber = AHDGrabber(config, self.bus)
        # OPi should default to 720p for AHD cameras
        w, h = grabber.get_resolution("front")
        assert (w, h) == RESOLUTION_720P

    def test_resolution_x86(self):
        grabber = AHDGrabber(self.config, self.bus)
        # x86 defaults to 480p if no device info
        if not grabber.has_front:
            w, h = grabber.get_resolution("front")
            assert (w, h) == RESOLUTION_480P

    def test_default_device_paths(self):
        assert DEFAULT_FRONT_DEVICE == "/dev/video0"
        assert DEFAULT_REAR_DEVICE == "/dev/video1"


# ---------------------------------------------------------------------------
# Dashcam Recorder tests
# ---------------------------------------------------------------------------

class TestDashcamRecorder:
    def setup_method(self):
        self.bus = EventBus()
        self.config = BCMConfig(platform_override="x86")
        self.grabber = AHDGrabber(self.config, self.bus)

    def test_init(self):
        dashcam = DashcamRecorder(self.config, self.bus, self.grabber)
        assert not dashcam.recording

    def test_storage_path_from_config(self):
        dashcam = DashcamRecorder(self.config, self.bus, self.grabber)
        expected = self.config.get(
            "camera.recording_path",
            self.config.get("camera.storage_path", "/tmp/bcm_dashcam"),
        )
        assert dashcam.storage_path == Path(expected)

    def test_start_no_cameras(self):
        dashcam = DashcamRecorder(self.config, self.bus, self.grabber)
        if not self.grabber.has_front and not self.grabber.has_rear:
            result = dashcam.start_recording()
            assert result is False
            assert not dashcam.recording

    def test_stop_when_not_recording(self):
        dashcam = DashcamRecorder(self.config, self.bus, self.grabber)
        dashcam.stop_recording()  # Should not raise
        assert not dashcam.recording

    def test_recording_event_published(self):
        dashcam = DashcamRecorder(self.config, self.bus, self.grabber)
        received = []
        self.bus.subscribe("camera.recording", lambda t, v, ts: received.append(v))

        dashcam.stop_recording()
        assert False in received

    def test_voice_command_start(self):
        dashcam = DashcamRecorder(self.config, self.bus, self.grabber)
        # Voice command should trigger start
        self.bus.publish("voice.cmd.start_recording", True)
        # Without cameras, recording won't actually start
        # but the handler should not raise

    def test_voice_command_stop(self):
        dashcam = DashcamRecorder(self.config, self.bus, self.grabber)
        self.bus.publish("voice.cmd.stop_recording", True)
        assert not dashcam.recording

    def test_build_pipeline_x86(self):
        dashcam = DashcamRecorder(self.config, self.bus, self.grabber)
        pipeline = dashcam._build_pipeline("/dev/video0", "front", (640, 480))
        assert "x264enc" in pipeline
        assert "front_" in pipeline
        assert "splitmuxsink" in pipeline

    def test_build_pipeline_opi(self):
        config = BCMConfig(platform_override="opi")
        grabber = AHDGrabber(config, self.bus)
        dashcam = DashcamRecorder(config, self.bus, grabber)
        pipeline = dashcam._build_pipeline("/dev/video0", "front", (1280, 720))
        assert "mpph264enc" in pipeline

    def test_cleanup_old_segments(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = BCMConfig(platform_override="x86")
            # Override storage path
            dashcam = DashcamRecorder(config, self.bus, self.grabber)
            dashcam._storage_path = Path(tmpdir)

            # Create fake segments
            for i in range(3):
                f = Path(tmpdir) / f"front_{i:05d}.mp4"
                f.write_bytes(b"x" * 1000)

            usage = dashcam._get_storage_usage()
            assert usage == 3000

    def test_segment_duration_constant(self):
        assert SEGMENT_DURATION_SEC == 300  # 5 minutes

    def test_storage_constants(self):
        assert MAX_STORAGE_BYTES == 128 * 1024 * 1024 * 1024
        assert 0 < STORAGE_CLEANUP_THRESHOLD < 1.0


# ---------------------------------------------------------------------------
# Reverse Camera tests
# ---------------------------------------------------------------------------

class TestCameraController:
    def setup_method(self):
        self.bus = EventBus()
        self.config = BCMConfig(platform_override="x86")
        self.grabber = AHDGrabber(self.config, self.bus)

    def test_legacy_alias(self):
        """ReverseCamera must still resolve, pointing at CameraController."""
        assert ReverseCamera is CameraController

    def test_init(self):
        ctrl = CameraController(self.config, self.bus, self.grabber)
        assert ctrl.active_role is None
        assert ctrl.grabber is self.grabber

    def test_init_broadcasts_no_feed(self):
        received = []
        self.bus.subscribe("camera.active_feed", lambda t, v, ts: received.append(v))
        CameraController(self.config, self.bus, self.grabber)
        assert received == [None]

    def test_reverse_gear_activates_rear(self):
        ctrl = CameraController(self.config, self.bus, self.grabber)
        received = {}

        def capture(topic, value, ts):
            received[topic] = value

        self.bus.subscribe("camera.active_feed", capture)
        self.bus.subscribe("camera.reverse_active", capture)
        self.bus.subscribe("dashboard.overlay", capture)

        self.bus.publish("power.reverse_gear", True)
        assert ctrl.active_role == ROLE_REAR
        assert received.get("camera.active_feed") == ROLE_REAR
        assert received.get("camera.reverse_active") is True
        assert received.get("dashboard.overlay") == "reverse_camera"

    def test_reverse_gear_off_deactivates(self):
        ctrl = CameraController(self.config, self.bus, self.grabber)
        received = {}

        def capture(topic, value, ts):
            received[topic] = value

        self.bus.subscribe("camera.reverse_active", capture)
        self.bus.subscribe("dashboard.overlay", capture)

        self.bus.publish("power.reverse_gear", True)
        self.bus.publish("power.reverse_gear", False)
        assert ctrl.active_role is None
        assert received.get("camera.reverse_active") is False
        assert received.get("dashboard.overlay") is None

    def test_left_blinker_activates_left(self):
        ctrl = CameraController(self.config, self.bus, self.grabber)
        received = {}

        def capture(topic, value, ts):
            received[topic] = value

        self.bus.subscribe("camera.active_feed", capture)
        self.bus.subscribe("dashboard.overlay", capture)

        self.bus.publish("vehicle.left_blinker", True)
        assert ctrl.active_role == ROLE_LEFT
        assert received.get("camera.active_feed") == ROLE_LEFT
        assert received.get("dashboard.overlay") == "side_camera"

        self.bus.publish("vehicle.left_blinker", False)
        assert ctrl.active_role is None

    def test_right_blinker_activates_right(self):
        ctrl = CameraController(self.config, self.bus, self.grabber)
        self.bus.publish("vehicle.right_blinker", True)
        assert ctrl.active_role == ROLE_RIGHT

        self.bus.publish("vehicle.right_blinker", False)
        assert ctrl.active_role is None

    def test_reverse_has_priority_over_blinkers(self):
        ctrl = CameraController(self.config, self.bus, self.grabber)
        self.bus.publish("vehicle.left_blinker", True)
        assert ctrl.active_role == ROLE_LEFT

        self.bus.publish("power.reverse_gear", True)
        assert ctrl.active_role == ROLE_REAR

        # Reverse off — falls back to the still-active blinker
        self.bus.publish("power.reverse_gear", False)
        assert ctrl.active_role == ROLE_LEFT

    def test_left_blinker_priority_over_right(self):
        ctrl = CameraController(self.config, self.bus, self.grabber)
        self.bus.publish("vehicle.right_blinker", True)
        self.bus.publish("vehicle.left_blinker", True)
        assert ctrl.active_role == ROLE_LEFT

    def test_repeated_event_is_idempotent(self):
        ctrl = CameraController(self.config, self.bus, self.grabber)
        received = []
        self.bus.subscribe("camera.active_feed", lambda t, v, ts: received.append(v))

        self.bus.publish("power.reverse_gear", True)
        self.bus.publish("power.reverse_gear", True)
        assert ctrl.active_role == ROLE_REAR
        # Only one transition published
        assert received.count(ROLE_REAR) == 1

    def test_deactivate_when_inactive(self):
        ctrl = CameraController(self.config, self.bus, self.grabber)
        self.bus.publish("power.reverse_gear", False)  # Should not raise
        assert ctrl.active_role is None
