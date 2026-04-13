"""Multi-camera controller with priority-based activation.

Manages 4 cameras (front, rear, left, right) and decides which feed
the 4.3" small display should show based on driver inputs:

    Priority (highest → lowest):
        1. power.reverse_gear  → rear camera
        2. vehicle.left_blinker  → left camera
        3. vehicle.right_blinker → right camera
        otherwise                → no overlay (grid view)

Publishes:
    camera.active_feed   — "rear" | "left" | "right" | None
    camera.reverse_active — bool (kept for backwards compatibility)
    dashboard.overlay    — "reverse_camera" | "side_camera" | None

On OPi it can also start a GStreamer pipeline to render the active
camera to the framebuffer. The MJPEG stream endpoint in
small_viewer.py is the primary consumer — the framebuffer overlay
is optional and only used when the small display runs in pure HDMI
mode with no browser.
"""

from __future__ import annotations

import subprocess
import threading
from typing import Any, Optional

from src.camera.ahd_grabber import AHDGrabber
from src.core.event_bus import EventBus
from src.core.logger import get_logger

log = get_logger("camera.controller")

# Role constants
ROLE_REAR = "rear"
ROLE_LEFT = "left"
ROLE_RIGHT = "right"
ROLE_FRONT = "front"


class CameraController:
    """Selects the appropriate camera feed based on event-bus state."""

    def __init__(self, config: Any, event_bus: EventBus, grabber: AHDGrabber):
        self._config = config
        self._bus = event_bus
        self._grabber = grabber
        self._platform = config.get("system.platform", "x86")
        self._lock = threading.Lock()

        self._reverse = False
        self._left_blinker = False
        self._right_blinker = False

        self._active_role: Optional[str] = None
        self._overlay_process: Optional[subprocess.Popen] = None

        # Subscribe to the three input events
        self._bus.subscribe("power.reverse_gear", self._on_reverse)
        self._bus.subscribe("vehicle.left_blinker", self._on_left)
        self._bus.subscribe("vehicle.right_blinker", self._on_right)

        log.info(
            "CameraController initialised (rear=%s, left=%s, right=%s)",
            "yes" if grabber.has("rear") else "no",
            "yes" if grabber.has("left") else "no",
            "yes" if grabber.has("right") else "no",
        )

        # Initial state broadcast — ensures small_viewer sees None early on
        self._bus.publish("camera.active_feed", None)

    # ------------------------------------------------------------------ #
    # Event handlers                                                     #
    # ------------------------------------------------------------------ #

    def _on_reverse(self, topic: str, value: Any, timestamp: float) -> None:
        self._reverse = bool(value)
        self._recompute()

    def _on_left(self, topic: str, value: Any, timestamp: float) -> None:
        self._left_blinker = bool(value)
        self._recompute()

    def _on_right(self, topic: str, value: Any, timestamp: float) -> None:
        self._right_blinker = bool(value)
        self._recompute()

    # ------------------------------------------------------------------ #
    # Priority engine                                                    #
    # ------------------------------------------------------------------ #

    def _resolve_role(self) -> Optional[str]:
        if self._reverse:
            return ROLE_REAR
        if self._left_blinker:
            return ROLE_LEFT
        if self._right_blinker:
            return ROLE_RIGHT
        return None

    def _recompute(self) -> None:
        new_role = self._resolve_role()
        with self._lock:
            if new_role == self._active_role:
                return
            prev = self._active_role
            self._active_role = new_role

        log.info("Active camera feed: %s → %s", prev, new_role)
        self._bus.publish("camera.active_feed", new_role)

        # Keep legacy topics working so existing subscribers (dashboard
        # renderer, parking system) don't have to change.
        self._bus.publish("camera.reverse_active", new_role == ROLE_REAR)
        if new_role is None:
            self._bus.publish("dashboard.overlay", None)
        elif new_role == ROLE_REAR:
            self._bus.publish("dashboard.overlay", "reverse_camera")
        else:
            self._bus.publish("dashboard.overlay", "side_camera")

        # Optional framebuffer pipeline (OPi only)
        self._stop_overlay()
        if new_role is not None:
            self._start_overlay(new_role)

    # ------------------------------------------------------------------ #
    # Framebuffer overlay (optional, OPi only)                           #
    # ------------------------------------------------------------------ #

    def _start_overlay(self, role: str) -> None:
        device = self._grabber.device(role)
        if not device:
            log.debug("No device for role %s — skipping framebuffer overlay", role)
            return
        if self._platform not in ("opi", "opi_pc"):
            return  # x86: UI consumes MJPEG stream instead
        if not self._config.get("camera.framebuffer_overlay", False):
            return

        w, h = self._grabber.get_resolution(role)
        sink = "fbdevsink device=/dev/fb0"
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
            log.info("Framebuffer overlay started for %s (%s)", role, device)
        except FileNotFoundError:
            log.warning("gst-launch-1.0 not found — framebuffer overlay unavailable")

    def _stop_overlay(self) -> None:
        if self._overlay_process and self._overlay_process.poll() is None:
            self._overlay_process.terminate()
            try:
                self._overlay_process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._overlay_process.kill()
            self._overlay_process = None
            log.info("Framebuffer overlay stopped")

    # ------------------------------------------------------------------ #
    # Accessors                                                          #
    # ------------------------------------------------------------------ #

    @property
    def active_role(self) -> Optional[str]:
        return self._active_role

    @property
    def grabber(self) -> AHDGrabber:
        return self._grabber
