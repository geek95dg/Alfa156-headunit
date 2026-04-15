"""AHD USB3.0 grabber interface — V4L2 camera device management.

Detects and manages AHD camera inputs via V4L2. On x86, falls back
to USB webcam or test pattern.

Hardware: 4-channel USB3.0 AHD grabber → presents as /dev/video0..N
Cameras (default mapping, config-overridable):
    video0 = front   (windscreen / dashcam front)
    video1 = rear    (license plate frame, reverse camera)
    video2 = left    (left wing, activated by left blinker)
    video3 = right   (right wing, activated by right blinker)
"""

import subprocess
from pathlib import Path
from typing import Any, Optional

from src.core.event_bus import EventBus
from src.core.logger import get_logger

log = get_logger("camera.grabber")

# AHD grabber typically presents multiple V4L2 devices — one per camera input.
# The defaults match the AliExpress 4-camera set + 4-ch USB AHD grabber setup.
DEFAULT_FRONT_DEVICE = "/dev/video0"
DEFAULT_REAR_DEVICE = "/dev/video1"
DEFAULT_LEFT_DEVICE = "/dev/video2"
DEFAULT_RIGHT_DEVICE = "/dev/video3"

CAMERA_ROLES = ("front", "rear", "left", "right")

RESOLUTION_720P = (1280, 720)
RESOLUTION_480P = (640, 480)  # Fallback for webcams


def _probe_v4l2_device(device: str) -> Optional[dict[str, Any]]:
    """Probe a V4L2 device for capabilities.

    Returns:
        Device info dict or None if not available.
    """
    path = Path(device)
    if not path.exists():
        return None

    try:
        result = subprocess.run(
            ["v4l2-ctl", "--device", device, "--all"],
            capture_output=True, text=True, timeout=5.0,
        )
        if result.returncode != 0:
            return None

        info: dict[str, Any] = {"device": device, "raw": result.stdout}

        # Parse driver and card name
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("Driver name"):
                info["driver"] = line.split(":", 1)[-1].strip()
            elif line.startswith("Card type"):
                info["card"] = line.split(":", 1)[-1].strip()
            elif "Width/Height" in line:
                try:
                    dims = line.split(":", 1)[-1].strip()
                    w, h = dims.split("/")
                    info["width"] = int(w)
                    info["height"] = int(h)
                except (ValueError, IndexError):
                    pass

        return info
    except FileNotFoundError:
        log.debug("v4l2-ctl not available")
        return None
    except subprocess.TimeoutExpired:
        return None


def list_video_devices() -> list[str]:
    """List available /dev/videoN devices."""
    devices = sorted(Path("/dev").glob("video[0-9]*"))
    return [str(d) for d in devices]


class AHDGrabber:
    """Manages AHD camera devices via V4L2.

    Detects up to 4 cameras (front, rear, left, right) and provides
    device paths for GStreamer pipelines / MJPEG stream endpoints.
    """

    def __init__(self, config: Any, event_bus: EventBus):
        self._config = config
        self._event_bus = event_bus
        self._platform = config.get("system.platform", "x86")

        # Device assignments — one per role
        self._devices: dict[str, Optional[str]] = {r: None for r in CAMERA_ROLES}
        self._infos: dict[str, Optional[dict]] = {r: None for r in CAMERA_ROLES}

        self._detect_cameras()

    def _detect_cameras(self) -> None:
        """Auto-detect camera devices for all 4 roles."""
        devices = list_video_devices()
        log.info("Video devices found: %s", devices)

        if not devices:
            log.warning("No video devices found — camera will be simulated")
            return

        defaults = {
            "front": DEFAULT_FRONT_DEVICE,
            "rear":  DEFAULT_REAR_DEVICE,
            "left":  DEFAULT_LEFT_DEVICE,
            "right": DEFAULT_RIGHT_DEVICE,
        }

        for role, default_dev in defaults.items():
            cfg_dev = self._config.get(f"camera.{role}_device", default_dev)
            if cfg_dev in devices:
                info = _probe_v4l2_device(cfg_dev)
                if info:
                    self._devices[role] = cfg_dev
                    self._infos[role] = info
                    log.info(
                        "%s camera: %s (%s)",
                        role.capitalize(), cfg_dev, info.get("card", "unknown"),
                    )

        # Fallback: if no front camera but some device exists, use the first.
        if not self._devices["front"] and devices:
            first = devices[0]
            info = _probe_v4l2_device(first)
            if info:
                self._devices["front"] = first
                self._infos["front"] = info
                log.info("Using %s as front camera (fallback)", first)

    # ------------------------------------------------------------------ #
    # Role-based accessors (new API)                                     #
    # ------------------------------------------------------------------ #

    def device(self, role: str) -> Optional[str]:
        """Return the /dev/videoN path for a camera role, or None if absent."""
        return self._devices.get(role)

    def has(self, role: str) -> bool:
        return self._devices.get(role) is not None

    def get_resolution(self, role: str = "front") -> tuple[int, int]:
        """Get the resolution for a camera role.

        Args:
            role: one of 'front', 'rear', 'left', 'right'.

        Returns:
            (width, height) tuple.
        """
        info = self._infos.get(role)
        if info and "width" in info:
            return (info["width"], info["height"])

        # AHD cameras are 720p, webcams may be 480p
        if self._platform in ("opi", "opi_pc"):
            return RESOLUTION_720P
        return RESOLUTION_480P

    # ------------------------------------------------------------------ #
    # Legacy property accessors (kept for backward compatibility)        #
    # ------------------------------------------------------------------ #

    @property
    def front_device(self) -> Optional[str]:
        return self._devices["front"]

    @property
    def rear_device(self) -> Optional[str]:
        return self._devices["rear"]

    @property
    def left_device(self) -> Optional[str]:
        return self._devices["left"]

    @property
    def right_device(self) -> Optional[str]:
        return self._devices["right"]

    @property
    def has_front(self) -> bool:
        return self.has("front")

    @property
    def has_rear(self) -> bool:
        return self.has("rear")

    @property
    def has_left(self) -> bool:
        return self.has("left")

    @property
    def has_right(self) -> bool:
        return self.has("right")
