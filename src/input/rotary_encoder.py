"""Rotary encoder input — listen for USB HID events from Arduino Pro Micro.

The Arduino presents as a USB HID keyboard. We listen for key events
using evdev and forward them to the ActionDispatcher.

Falls back gracefully if evdev is not available or no device found.
"""

import threading
from typing import Any, Optional

from src.core.event_bus import EventBus
from src.core.logger import get_logger

log = get_logger("input.rotary")

try:
    import evdev
    from evdev import InputDevice, categorize, ecodes
    _EVDEV_AVAILABLE = True
except ImportError:
    _EVDEV_AVAILABLE = False
    log.info("evdev not installed — rotary encoder will be simulated")

# Arduino Pro Micro identifies with these USB IDs
ARDUINO_VENDOR_IDS = [0x2341, 0x1B4F, 0x2A03]  # Arduino, SparkFun, Arduino.org
ARDUINO_DEVICE_NAME_PATTERNS = ["Arduino", "Pro Micro", "Leonardo", "ATmega32U4"]


def find_arduino_device() -> Optional[Any]:
    """Find the Arduino HID device among input devices."""
    if not _EVDEV_AVAILABLE:
        return None

    try:
        devices = [evdev.InputDevice(path) for path in evdev.list_devices()]
        for dev in devices:
            # Match by name
            if any(pat.lower() in dev.name.lower() for pat in ARDUINO_DEVICE_NAME_PATTERNS):
                log.info("Arduino found: %s (%s)", dev.name, dev.path)
                return dev
            # Match by vendor ID
            info = dev.info
            if info.vendor in ARDUINO_VENDOR_IDS:
                log.info("Arduino found by vendor ID: %s (%s)", dev.name, dev.path)
                return dev
        log.info("No Arduino HID device found")
    except Exception as e:
        log.warning("Error scanning input devices: %s", e)
    return None


class RotaryEncoderListener:
    """Listens for USB HID key events from the Arduino rotary encoder.

    Publishes raw keycodes to the event bus for ActionDispatcher.
    """

    def __init__(self, event_bus: EventBus):
        self._event_bus = event_bus
        self._device: Optional[Any] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None

        self._device = find_arduino_device()

    @property
    def available(self) -> bool:
        return self._device is not None

    @property
    def device_name(self) -> str:
        if self._device:
            return self._device.name
        return "none"

    def start(self) -> None:
        """Start listening for encoder events."""
        if self._running:
            return

        self._running = True

        if self.available:
            self._thread = threading.Thread(target=self._listen_loop, daemon=True)
            self._thread.start()
            log.info("Rotary encoder listener started: %s", self.device_name)
        else:
            log.info("Rotary encoder: no device (use keyboard fallback)")

    def stop(self) -> None:
        """Stop listening."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _listen_loop(self) -> None:
        """Read events from the input device."""
        try:
            for event in self._device.read_loop():
                if not self._running:
                    break
                if event.type == ecodes.EV_KEY and event.value == 1:  # Key press
                    self._event_bus.publish("input.raw_keycode", event.code)
                    log.debug("Encoder key: %d", event.code)
        except OSError as e:
            log.error("Encoder device lost: %s", e)
            self._running = False
        except Exception as e:
            log.error("Encoder listener error: %s", e)
            self._running = False
