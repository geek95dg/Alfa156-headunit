"""Map keycodes to actions and dispatch to event bus.

Handles keycodes from:
    - Arduino rotary encoder (USB HID keyboard)
    - BT steering wheel remote (BT HID)
    - Keyboard fallback (x86 development)

Entry point: start_input() is called from main.py.
"""

from typing import Any

from src.core.event_bus import EventBus
from src.core.logger import get_logger

log = get_logger("input.dispatch")

# evdev key code constants (from linux/input-event-codes.h)
# These match what Arduino Pro Micro sends as USB HID keyboard
KEY_UP = 103
KEY_DOWN = 108
KEY_ENTER = 28
KEY_HOME = 102
KEY_BACK = 158  # KEY_BACK
KEY_MEDIA = 226  # KEY_MEDIA (or a custom mapping)
KEY_VOLUMEUP = 115
KEY_VOLUMEDOWN = 114
KEY_NEXTSONG = 163
KEY_PREVIOUSSONG = 165
KEY_PLAYPAUSE = 164
KEY_PHONE = 169

# Map evdev keycodes → event bus topics
KEYCODE_MAP: dict[int, str] = {
    KEY_UP: "input.menu_up",
    KEY_DOWN: "input.menu_down",
    KEY_ENTER: "input.menu_select",
    KEY_HOME: "input.home",
    KEY_BACK: "input.back",
    KEY_MEDIA: "input.media_button",
    KEY_VOLUMEUP: "input.volume_up",
    KEY_VOLUMEDOWN: "input.volume_down",
    KEY_NEXTSONG: "input.next_track",
    KEY_PREVIOUSSONG: "input.prev_track",
    KEY_PLAYPAUSE: "input.play_pause",
    KEY_PHONE: "input.phone",
}

# Keyboard key names → keycodes (for x86 development without HID devices)
KEYBOARD_MAP: dict[str, int] = {
    "up": KEY_UP,
    "down": KEY_DOWN,
    "enter": KEY_ENTER,
    "home": KEY_HOME,
    "backspace": KEY_BACK,
    "m": KEY_MEDIA,
    "+": KEY_VOLUMEUP,
    "-": KEY_VOLUMEDOWN,
    "n": KEY_NEXTSONG,
    "p": KEY_PREVIOUSSONG,
    "space": KEY_PLAYPAUSE,
}


class ActionDispatcher:
    """Maps input keycodes to event bus actions.

    Receives keycodes from rotary encoder, BT remote, or keyboard
    and publishes the corresponding action events.
    """

    def __init__(self, event_bus: EventBus):
        self._event_bus = event_bus
        self._keymap = dict(KEYCODE_MAP)

        # Subscribe to raw keycode events from input devices
        self._event_bus.subscribe("input.raw_keycode", self._on_keycode)
        self._event_bus.subscribe("input.raw_keyname", self._on_keyname)

        log.info("ActionDispatcher initialized (%d mappings)", len(self._keymap))

    def dispatch_keycode(self, keycode: int) -> bool:
        """Dispatch an action for a keycode.

        Args:
            keycode: evdev keycode.

        Returns:
            True if the keycode was mapped to an action.
        """
        action = self._keymap.get(keycode)
        if action:
            self._event_bus.publish(action, True)
            log.debug("Key %d → %s", keycode, action)
            return True
        log.debug("Unmapped keycode: %d", keycode)
        return False

    def dispatch_keyname(self, name: str) -> bool:
        """Dispatch an action for a key name (keyboard fallback).

        Args:
            name: Key name (e.g. 'up', 'enter', '+').

        Returns:
            True if mapped.
        """
        keycode = KEYBOARD_MAP.get(name.lower())
        if keycode is not None:
            return self.dispatch_keycode(keycode)
        return False

    def _on_keycode(self, topic: str, value: Any, timestamp: float) -> None:
        if isinstance(value, int):
            self.dispatch_keycode(value)

    def _on_keyname(self, topic: str, value: Any, timestamp: float) -> None:
        if isinstance(value, str):
            self.dispatch_keyname(value)
