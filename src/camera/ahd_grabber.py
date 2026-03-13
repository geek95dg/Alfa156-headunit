"""AHD USB3.0 grabber interface — V4L2 camera device management.

Detects and manages AHD camera inputs via V4L2. On x86, falls back
to USB webcam or test pattern.

Hardware: 4-channel USB3.0 AHD grabber → presents as /dev/video0..N
Cameras: 2× AHD 720P (front windshield + rear license plate frame)
"""

import subprocess
from pathlib import Path
from typing import Any, Optional

from src.core.event_bus import EventBus
from src.core.logger import get_logger

log = get_logger("camera.grabber")

# AHD grabber typically presents multiple V4L2 devices
DEFAULT_FRONT_DEVICE = "/dev/video0"
DEFAULT_REAR_DEVICE = "/dev/video1"

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

    Detects front and rear cameras and provides device paths
    for GStreamer pipelines.
    """

    def __init__(self, config: Any, event_bus: EventBus):
        self._config = config
        self._event_bus = event_bus
        self._platform = config.get("system.platform", "x86")

        # Device assignments
        self._front_device: Optional[str] = None
        self._rear_device: Optional[str] = None
        self._front_info: Optional[dict] = None
        self._rear_info: Optional[dict] = None

        self._detect_cameras()

    def _detect_cameras(self) -> None:
        """Auto-detect camera devices."""
        devices = list_video_devices()
        log.info("Video devices found: %s", devices)

        if not devices:
            log.warning("No video devices found — camera will be simulated")
            return

        # Configure front camera
        front_cfg = self._config.get("camera.front_device", DEFAULT_FRONT_DEVICE)
        if front_cfg in devices:
            self._front_info = _probe_v4l2_device(front_cfg)
            if self._front_info:
                self._front_device = front_cfg
                log.info("Front camera: %s (%s)",
                         front_cfg, self._front_info.get("card", "unknown"))

        # Configure rear camera
        rear_cfg = self._config.get("camera.rear_device", DEFAULT_REAR_DEVICE)
        if rear_cfg in devices:
            self._rear_info = _probe_v4l2_device(rear_cfg)
            if self._rear_info:
                self._rear_device = rear_cfg
                log.info("Rear camera: %s (%s)",
                         rear_cfg, self._rear_info.get("card", "unknown"))

        # Fallback: if only one device, use it as front
        if not self._front_device and devices:
            info = _probe_v4l2_device(devices[0])
            if info:
                self._front_device = devices[0]
                self._front_info = info
                log.info("Using %s as front camera (fallback)", devices[0])

    @property
    def front_device(self) -> Optional[str]:
        return self._front_device

    @property
    def rear_device(self) -> Optional[str]:
        return self._rear_device

    @property
    def has_front(self) -> bool:
        return self._front_device is not None

    @property
    def has_rear(self) -> bool:
        return self._rear_device is not None

    def get_resolution(self, camera: str = "front") -> tuple[int, int]:
        """Get the resolution for a camera.

        Args:
            camera: 'front' or 'rear'.

        Returns:
            (width, height) tuple.
        """
        info = self._front_info if camera == "front" else self._rear_info
        if info and "width" in info:
            return (info["width"], info["height"])

        # AHD cameras are 720p, webcams may be 480p
        if self._platform == "opi":
            return RESOLUTION_720P
        return RESOLUTION_480P
