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

    def test_storage_path_default(self):
        dashcam = DashcamRecorder(self.config, self.bus, self.grabber)
        assert dashcam.storage_path == Path("/tmp/bcm_dashcam")

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

class TestReverseCamera:
    def setup_method(self):
        self.bus = EventBus()
        self.config = BCMConfig(platform_override="x86")
        self.grabber = AHDGrabber(self.config, self.bus)

    def test_init(self):
        rev = ReverseCamera(self.config, self.bus, self.grabber)
        assert not rev.active

    def test_activate(self):
        rev = ReverseCamera(self.config, self.bus, self.grabber)
        received = {}

        def capture(topic, value, ts):
            received[topic] = value

        self.bus.subscribe("camera.reverse_active", capture)
        self.bus.subscribe("dashboard.overlay", capture)

        rev.activate()
        assert rev.active
        assert received.get("camera.reverse_active") is True
        assert received.get("dashboard.overlay") == "reverse_camera"

    def test_deactivate(self):
        rev = ReverseCamera(self.config, self.bus, self.grabber)
        received = {}

        def capture(topic, value, ts):
            received[topic] = value

        self.bus.subscribe("camera.reverse_active", capture)
        self.bus.subscribe("dashboard.overlay", capture)

        rev.activate()
        rev.deactivate()
        assert not rev.active
        assert received.get("camera.reverse_active") is False
        assert received.get("dashboard.overlay") is None

    def test_double_activate(self):
        rev = ReverseCamera(self.config, self.bus, self.grabber)
        rev.activate()
        rev.activate()  # Should be idempotent
        assert rev.active

    def test_deactivate_when_inactive(self):
        rev = ReverseCamera(self.config, self.bus, self.grabber)
        rev.deactivate()  # Should not raise
        assert not rev.active

    def test_reverse_gear_event(self):
        rev = ReverseCamera(self.config, self.bus, self.grabber)

        self.bus.publish("power.reverse_gear", True)
        assert rev.active

        self.bus.publish("power.reverse_gear", False)
        assert not rev.active
