"""Backward-compatibility shim for the legacy reverse camera module.

The original ``ReverseCamera`` class handled only the rear camera
feed triggered by ``power.reverse_gear``. It has been superseded by
:class:`src.camera.camera_controller.CameraController`, which manages
all four cameras (front / rear / left / right) with priority logic.

This module keeps the old public names so existing imports and event
wiring continue to work. Internally it delegates to the new controller.

Entry point ``start_camera()`` still exists and now instantiates:
    - :class:`AHDGrabber` for V4L2 enumeration
    - :class:`DashcamRecorder` for loop recording
    - :class:`CameraController` for reverse + blinker triggered feeds

and publishes handles via the ``camera._internals`` event topic so
other modules can locate them.
"""

from __future__ import annotations

from typing import Any

from src.camera.ahd_grabber import AHDGrabber
from src.camera.camera_controller import CameraController
from src.camera.dashcam import DashcamRecorder
from src.core.event_bus import EventBus
from src.core.logger import get_logger

log = get_logger("camera.reverse")


# Legacy alias — kept so `from src.camera.reverse_cam import ReverseCamera`
# still resolves. Prefer importing CameraController directly.
ReverseCamera = CameraController


def start_camera(config: Any, event_bus: EventBus, hal: Any = None,
                 **kwargs) -> None:
    """Entry point called from main.py to start the camera module."""
    grabber = AHDGrabber(config, event_bus)
    dashcam = DashcamRecorder(config, event_bus, grabber)

    if config.get("camera.auto_record", False) and grabber.has_front:
        dashcam.start_recording()

    controller = CameraController(config, event_bus, grabber)

    log.info(
        "Camera module running (front=%s, rear=%s, left=%s, right=%s)",
        "active" if grabber.has_front else "none",
        "active" if grabber.has_rear  else "none",
        "active" if grabber.has_left  else "none",
        "active" if grabber.has_right else "none",
    )

    event_bus.publish("camera._internals", {
        "grabber": grabber,
        "dashcam": dashcam,
        "reverse_cam": controller,     # legacy key
        "controller": controller,
    })
