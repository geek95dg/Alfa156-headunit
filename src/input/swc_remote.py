"""Steering wheel control (SWC) remote — analog resistor-ladder buttons.

The SWC decoder box converts button presses into analog voltages on a single
wire. The Arduino Pro Micro reads this via ADC pin A0 and sends USB HID
keycodes to the host (same as rotary encoder — single Arduino handles both).

This module provides:
    - SWC-specific keycode constants
    - Simulator for x86 development (keyboard shortcuts)
    - Button name/action mapping for UI display

The actual hardware input is handled by the Arduino firmware
(arduino/rotary_encoder/rotary_encoder.ino) which outputs standard USB HID
keycodes. Those keycodes are received by RotaryEncoderListener (same evdev
device) and dispatched through ActionDispatcher.

SWC button layout (2x round pods, 6 buttons each):

  Pod 1 (media/nav):        Pod 2 (phone/audio):
    VOL+  VOL-                PICKUP  HANGUP
    UP    DOWN                PREV    NEXT
    MUTE  MODE                VOICE   SRC
"""

from src.core.logger import get_logger

log = get_logger("input.swc")

# SWC buttons and their Arduino USB HID output keycodes
# These match the keycodes sent by the Arduino firmware
SWC_BUTTONS = {
    "SWC_VOLUP":  "volume_up",       # Consumer: MEDIA_VOLUME_UP
    "SWC_VOLDN":  "volume_down",     # Consumer: MEDIA_VOLUME_DOWN
    "SWC_UP":     "menu_up",         # KEY_UP_ARROW
    "SWC_DOWN":   "menu_down",       # KEY_DOWN_ARROW
    "SWC_MUTE":   "mute",            # Consumer: MEDIA_VOLUME_MUTE
    "SWC_MODE":   "home",            # KEY_HOME
    "SWC_NEXT":   "next_track",      # Consumer: MEDIA_NEXT
    "SWC_PREV":   "prev_track",      # Consumer: MEDIA_PREVIOUS
    "SWC_PICKUP": "phone_pickup",    # KEY_F5
    "SWC_HANGUP": "phone_hangup",    # KEY_F6
    "SWC_VOICE":  "voice_trigger",   # KEY_F7
    "SWC_SRC":    "source_cycle",    # KEY_F8
}

# evdev keycodes for the F-key SWC actions (phone, voice, source)
# These are the Linux input event codes for the keys the Arduino sends
KEY_F5 = 63     # Phone pickup
KEY_F6 = 64     # Phone hangup
KEY_F7 = 65     # Voice assistant
KEY_F8 = 66     # Audio source cycle
KEY_MUTE = 113  # Volume mute


def get_swc_button_names() -> list[str]:
    """Return list of SWC button names for UI/config display."""
    return list(SWC_BUTTONS.keys())


def get_swc_action(button_name: str) -> str | None:
    """Map SWC button name to event bus action suffix."""
    return SWC_BUTTONS.get(button_name)
