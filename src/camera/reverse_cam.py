"""Reverse camera — show rear camera feed on dashboard when in reverse gear.

On `power.reverse_gear` event, activates rear camera overlay on 4.3" display.
On x86: shows a placeholder/test pattern.
On OPi: feeds rear AHD camera via GStreamer to framebuffer overlay.

Entry point: start_camera() is called from main.py.
"""

import subprocess
import threading
from typing import Any, Optional

from src.core.event_bus import EventBus
from src.core.logger import get_logger
from src.camera.ahd_grabber import AHDGrabber
from src.camera.dashcam import DashcamRecorder

log = get_logger("camera.reverse")


class ReverseCamera:
    """Manages reverse camera overlay activation.

    When reverse gear is engaged:
        1. Publishes parking mode event
        2. Feeds rear camera to 4.3" display overlay
        3. On disengage, restores normal dashboard view
    """

    def __init__(self, config: Any, event_bus: EventBus, grabber: AHDGrabber):
        self._config = config
        self._event_bus = event_bus
        self._grabber = grabber
        self._platform = config.get("system.platform", "x86")
        self._active = False
        self._overlay_process: Optional[subprocess.Popen] = None

        # Subscribe to reverse gear events
        self._event_bus.subscribe("power.reverse_gear", self._on_reverse_gear)

        log.info("ReverseCamera initialized (rear=%s)",
                 "available" if grabber.has_rear else "none")

    @property
    def active(self) -> bool:
        return self._active

    def activate(self) -> None:
        """Activate reverse camera overlay."""
        if self._active:
            return

        self._active = True
        self._event_bus.publish("camera.reverse_active", True)
        self._event_bus.publish("dashboard.overlay", "reverse_camera")
        log.info("Reverse camera activated")

        if self._grabber.has_rear:
            self._start_overlay()

    def deactivate(self) -> None:
        """Deactivate reverse camera overlay."""
        if not self._active:
            return

        self._stop_overlay()
        self._active = False
        self._event_bus.publish("camera.reverse_active", False)
        self._event_bus.publish("dashboard.overlay", None)
        log.info("Reverse camera deactivated")

    def _start_overlay(self) -> None:
        """Start GStreamer pipeline to display rear camera."""
        device = self._grabber.rear_device
        if not device:
            return

        w, h = self._grabber.get_resolution("rear")

        # On OPi: render to framebuffer; on x86: use autovideosink
        if self._platform == "opi":
            sink = "fbdevsink device=/dev/fb0"
        else:
            sink = "autovideosink"

        pipeline = (
            f"v4l2src device={device} ! "
            f"video/x-raw,width={w},height={h},framerate=25/1 ! "
            f"videoconvert ! videoscale ! "
            f"{sink}"
        )

        try:
            self._overlay_process = subprocess.Popen(
                ["gst-launch-1.0"] + pipeline.split(),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            log.info("Reverse camera overlay pipeline started")
        except FileNotFoundError:
            log.warning("gst-launch-1.0 not found — overlay not available")

    def _stop_overlay(self) -> None:
        """Stop the overlay pipeline."""
        if self._overlay_process and self._overlay_process.poll() is None:
            self._overlay_process.terminate()
            try:
                self._overlay_process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._overlay_process.kill()
            self._overlay_process = None
            log.info("Reverse camera overlay stopped")

    def _on_reverse_gear(self, topic: str, value: Any, timestamp: float) -> None:
        if value:
            self.activate()
        else:
            self.deactivate()


def start_camera(config: Any, event_bus: EventBus, hal: Any = None,
                 **kwargs) -> None:
    """Entry point called from main.py to start the camera module."""
    # AHD grabber (V4L2 device detection)
    grabber = AHDGrabber(config, event_bus)

    # Dashcam recorder
    dashcam = DashcamRecorder(config, event_bus, grabber)

    # Auto-start recording if configured
    if config.get("camera.auto_record", False) and grabber.has_front:
        dashcam.start_recording()

    # Reverse camera overlay
    reverse_cam = ReverseCamera(config, event_bus, grabber)

    log.info("Camera module running (front=%s, rear=%s)",
             "active" if grabber.has_front else "none",
             "active" if grabber.has_rear else "none")

    event_bus.publish("camera._internals", {
        "grabber": grabber,
        "dashcam": dashcam,
        "reverse_cam": reverse_cam,
    })
