"""Bluetooth steering wheel remote — listen for BT HID events via evdev.

Scans for paired BT HID input devices and forwards key events
to the ActionDispatcher via the event bus.

Entry point: start_input() in this module is called from main.py.
"""

import threading
from typing import Any, Optional

from src.core.event_bus import EventBus
from src.core.logger import get_logger
from src.input.action_dispatch import ActionDispatcher
from src.input.rotary_encoder import RotaryEncoderListener

log = get_logger("input.bt_remote")

try:
    import evdev
    from evdev import InputDevice, ecodes
    _EVDEV_AVAILABLE = True
except ImportError:
    _EVDEV_AVAILABLE = False

# BT HID remotes typically have "remote" or "bluetooth" in the name
BT_REMOTE_PATTERNS = ["remote", "bluetooth", "bt", "steering", "media"]


def find_bt_remote() -> Optional[Any]:
    """Find a BT HID remote among input devices."""
    if not _EVDEV_AVAILABLE:
        return None

    try:
        devices = [evdev.InputDevice(path) for path in evdev.list_devices()]
        for dev in devices:
            name_lower = dev.name.lower()
            # Skip Arduino devices (handled by rotary_encoder)
            if any(p in name_lower for p in ["arduino", "pro micro", "leonardo"]):
                continue
            if any(pat in name_lower for pat in BT_REMOTE_PATTERNS):
                log.info("BT remote found: %s (%s)", dev.name, dev.path)
                return dev
        log.info("No BT HID remote found")
    except Exception as e:
        log.warning("Error scanning for BT remote: %s", e)
    return None


class BTRemoteListener:
    """Listens for Bluetooth HID remote key events.

    Publishes raw keycodes to the event bus for ActionDispatcher.
    """

    def __init__(self, event_bus: EventBus):
        self._event_bus = event_bus
        self._device: Optional[Any] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None

        self._device = find_bt_remote()

    @property
    def available(self) -> bool:
        return self._device is not None

    @property
    def device_name(self) -> str:
        if self._device:
            return self._device.name
        return "none"

    def start(self) -> None:
        """Start listening for BT remote events."""
        if self._running:
            return

        self._running = True

        if self.available:
            self._thread = threading.Thread(target=self._listen_loop, daemon=True)
            self._thread.start()
            log.info("BT remote listener started: %s", self.device_name)
        else:
            log.info("BT remote: no device paired")

    def stop(self) -> None:
        """Stop listening."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _listen_loop(self) -> None:
        """Read events from the BT HID device."""
        try:
            for event in self._device.read_loop():
                if not self._running:
                    break
                if event.type == ecodes.EV_KEY and event.value == 1:  # Key press
                    self._event_bus.publish("input.raw_keycode", event.code)
                    log.debug("BT remote key: %d", event.code)
        except OSError as e:
            log.error("BT remote device lost: %s", e)
            self._running = False
        except Exception as e:
            log.error("BT remote listener error: %s", e)
            self._running = False


def start_input(config: Any, event_bus: EventBus, hal: Any = None,
                **kwargs) -> None:
    """Entry point called from main.py to start the input module."""
    # Action dispatcher (keycode → event bus actions)
    dispatcher = ActionDispatcher(event_bus)

    # Rotary encoder (Arduino USB HID)
    encoder = RotaryEncoderListener(event_bus)
    encoder.start()

    # BT steering wheel remote
    bt_remote = BTRemoteListener(event_bus)
    bt_remote.start()

    log.info("Input module running (encoder=%s, bt_remote=%s)",
             "active" if encoder.available else "simulated",
             "active" if bt_remote.available else "simulated")

    event_bus.publish("input._internals", {
        "dispatcher": dispatcher,
        "encoder": encoder,
        "bt_remote": bt_remote,
    })
