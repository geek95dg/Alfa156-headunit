"""GStreamer dashcam pipeline — capture, encode, loop-record to USB drive.

Pipeline: v4l2src → videoconvert → x264enc/mpph264enc → splitmuxsink
Loop recording: 5-minute segments, oldest deleted when storage full.
Capacity: ~47 hours on 128GB USB drive.

x86: software x264 encoding
OPi: hardware H.264 via mpph264enc (RK3588 VPU)
"""

import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Optional

from src.core.event_bus import EventBus
from src.core.logger import get_logger
from src.camera.ahd_grabber import AHDGrabber

log = get_logger("camera.dashcam")

SEGMENT_DURATION_SEC = 300  # 5 minutes per segment
MAX_STORAGE_BYTES = 128 * 1024 * 1024 * 1024  # 128GB
STORAGE_CLEANUP_THRESHOLD = 0.95  # Cleanup at 95% full


class DashcamRecorder:
    """Dual-channel dashcam recorder using GStreamer.

    Records front (and optionally rear) camera to segmented
    H.264 MP4 files on USB drive with automatic loop-deletion.
    """

    def __init__(self, config: Any, event_bus: EventBus, grabber: AHDGrabber):
        self._config = config
        self._event_bus = event_bus
        self._grabber = grabber
        self._platform = config.get("system.platform", "x86")

        # Recording state
        self._recording = False
        self._front_process: Optional[subprocess.Popen] = None
        self._rear_process: Optional[subprocess.Popen] = None
        self._cleanup_thread: Optional[threading.Thread] = None

        # Storage path
        self._storage_path = Path(
            config.get("camera.storage_path", "/tmp/bcm_dashcam")
        )
        self._segment_duration = config.get(
            "camera.segment_duration", SEGMENT_DURATION_SEC
        )

        # Subscribe to voice/input commands
        self._event_bus.subscribe("voice.cmd.start_recording", self._on_start)
        self._event_bus.subscribe("voice.cmd.stop_recording", self._on_stop)

        log.info("DashcamRecorder initialized (storage=%s)", self._storage_path)

    @property
    def recording(self) -> bool:
        return self._recording

    @property
    def storage_path(self) -> Path:
        return self._storage_path

    def start_recording(self) -> bool:
        """Start recording from available cameras.

        Returns:
            True if recording started successfully.
        """
        if self._recording:
            log.warning("Already recording")
            return False

        # Ensure storage directory exists
        self._storage_path.mkdir(parents=True, exist_ok=True)

        success = False

        # Start front camera recording
        if self._grabber.has_front:
            self._front_process = self._launch_pipeline(
                self._grabber.front_device,
                "front",
                self._grabber.get_resolution("front"),
            )
            if self._front_process:
                success = True

        # Start rear camera recording
        if self._grabber.has_rear:
            self._rear_process = self._launch_pipeline(
                self._grabber.rear_device,
                "rear",
                self._grabber.get_resolution("rear"),
            )
            if self._rear_process:
                success = True

        if success:
            self._recording = True
            self._start_cleanup_monitor()
            self._event_bus.publish("camera.recording", True)
            log.info("Dashcam recording started")
        else:
            log.warning("No cameras available for recording")

        return success

    def stop_recording(self) -> None:
        """Stop all recordings."""
        self._recording = False

        for proc, name in [
            (self._front_process, "front"),
            (self._rear_process, "rear"),
        ]:
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                log.info("Stopped %s recording", name)

        self._front_process = None
        self._rear_process = None
        self._event_bus.publish("camera.recording", False)
        log.info("Dashcam recording stopped")

    def _build_pipeline(self, device: str, prefix: str,
                        resolution: tuple[int, int]) -> str:
        """Build a GStreamer pipeline string.

        Args:
            device: V4L2 device path.
            prefix: Filename prefix ('front' or 'rear').
            resolution: (width, height) tuple.

        Returns:
            GStreamer pipeline string for gst-launch-1.0.
        """
        w, h = resolution
        output_pattern = str(
            self._storage_path / f"{prefix}_%05d.mp4"
        )

        # Select encoder based on platform
        if self._platform == "opi":
            encoder = "mpph264enc"
        else:
            encoder = "x264enc tune=zerolatency speed-preset=ultrafast bitrate=2000"

        pipeline = (
            f"v4l2src device={device} ! "
            f"video/x-raw,width={w},height={h},framerate=25/1 ! "
            f"videoconvert ! "
            f"{encoder} ! "
            f"h264parse ! "
            f"splitmuxsink location={output_pattern} "
            f"max-size-time={self._segment_duration * 1_000_000_000}"
        )
        return pipeline

    def _launch_pipeline(self, device: str, prefix: str,
                         resolution: tuple[int, int]) -> Optional[subprocess.Popen]:
        """Launch a GStreamer recording pipeline.

        Returns:
            Popen process or None on failure.
        """
        pipeline = self._build_pipeline(device, prefix, resolution)
        log.info("Launching pipeline: gst-launch-1.0 %s", pipeline)

        try:
            proc = subprocess.Popen(
                ["gst-launch-1.0", "-e"] + pipeline.split(),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            # Quick check that it didn't fail immediately
            time.sleep(0.5)
            if proc.poll() is not None:
                stderr = proc.stderr.read().decode() if proc.stderr else ""
                log.error("Pipeline failed for %s: %s", prefix, stderr)
                return None
            return proc
        except FileNotFoundError:
            log.error("gst-launch-1.0 not found — GStreamer not installed")
            return None

    def _start_cleanup_monitor(self) -> None:
        """Start background thread to manage storage usage."""
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop, daemon=True
        )
        self._cleanup_thread.start()

    def _cleanup_loop(self) -> None:
        """Periodically check and clean up old recordings."""
        while self._recording:
            self._cleanup_old_segments()
            time.sleep(60)  # Check every minute

    def _cleanup_old_segments(self) -> None:
        """Delete oldest segments when storage exceeds threshold."""
        max_bytes = self._config.get("camera.max_storage_bytes", MAX_STORAGE_BYTES)
        threshold = max_bytes * STORAGE_CLEANUP_THRESHOLD

        total = self._get_storage_usage()
        if total < threshold:
            return

        # Sort segments by modification time (oldest first)
        segments = sorted(
            self._storage_path.glob("*.mp4"),
            key=lambda p: p.stat().st_mtime,
        )

        while total >= threshold and segments:
            oldest = segments.pop(0)
            size = oldest.stat().st_size
            oldest.unlink()
            total -= size
            log.info("Deleted old segment: %s (freed %dMB)",
                     oldest.name, size // (1024 * 1024))

    def _get_storage_usage(self) -> int:
        """Get total size of recordings in bytes."""
        total = 0
        for f in self._storage_path.glob("*.mp4"):
            total += f.stat().st_size
        return total

    # --- Event handlers ---

    def _on_start(self, topic: str, value: Any, timestamp: float) -> None:
        self.start_recording()

    def _on_stop(self, topic: str, value: Any, timestamp: float) -> None:
        self.stop_recording()
