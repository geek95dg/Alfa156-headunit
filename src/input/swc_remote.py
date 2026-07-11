"""Steering wheel control (SWC) remote — dual-pod analog resistor-ladder buttons.

Two identical AliExpress button pods (12 buttons each, 24 total) connected via
resistor ladders to Arduino ADC pins A0 (Pod 1) and A6 (Pod 2). (A1 is the
LDR light sensor — see rotary_encoder.ino.) The Arduino decodes voltage
levels and sends USB HID keycodes to the host.

Config format (action-centric, supports 2 buttons per action):

    swc:
      mapping:
        volume_up:   [SWC_VOLUP, SWC2_VOLUP]
        next_track:  [SWC_NEXT,  ""]           # Pod 2 slot disabled

Physical button names: SWC_VOLUP..SWC_SRC for Pod 1,
SWC2_VOLUP..SWC2_SRC for Pod 2.

SWC button layout (2x round pods, 6 buttons each, duplicated for 2 kits):

  Pod 1 kit 1 (media/nav):     Pod 1 kit 2 (phone/audio):
    VOL+  VOL-                    PICKUP  HANGUP
    UP    DOWN                    PREV    NEXT
    MUTE  MODE                    VOICE   SRC

  Pod 2 kit 1:                  Pod 2 kit 2:
    (same layout as above, prefixed SWC2_)
"""

from typing import Any

from src.core.logger import get_logger

log = get_logger("input.swc")

# All 24 physical SWC button names (12 per pod)
POD1_BUTTONS = [
    "SWC_VOLUP", "SWC_VOLDN", "SWC_UP", "SWC_DOWN", "SWC_MUTE", "SWC_MODE",
    "SWC_NEXT", "SWC_PREV", "SWC_PICKUP", "SWC_HANGUP", "SWC_VOICE", "SWC_SRC",
]

POD2_BUTTONS = [
    "SWC2_VOLUP", "SWC2_VOLDN", "SWC2_UP", "SWC2_DOWN", "SWC2_MUTE", "SWC2_MODE",
    "SWC2_NEXT", "SWC2_PREV", "SWC2_PICKUP", "SWC2_HANGUP", "SWC2_VOICE", "SWC2_SRC",
]

ALL_BUTTONS = POD1_BUTTONS + POD2_BUTTONS

ACTIONS = [
    "volume_up", "volume_down", "mute",
    "menu_up", "menu_down",
    "next_track", "prev_track", "play_pause",
    "phone_pickup", "phone_hangup",
    "bcm_power_toggle", "voice_aa_trigger", "navigate_aa",
    "home", "back", "source_cycle", "brightness_cycle",
    "disabled",
]

# Default mapping: action → [pod1_button, pod2_button]
DEFAULT_MAPPING: dict[str, list[str]] = {
    "volume_up":        ["SWC_VOLUP",   "SWC2_VOLUP"],
    "volume_down":      ["SWC_VOLDN",   "SWC2_VOLDN"],
    "next_track":       ["SWC_NEXT",    "SWC2_NEXT"],
    "prev_track":       ["SWC_PREV",    "SWC2_PREV"],
    "mute":             ["SWC_MUTE",    "SWC2_MUTE"],
    "phone_pickup":     ["SWC_PICKUP",  "SWC2_PICKUP"],
    "phone_hangup":     ["SWC_HANGUP",  "SWC2_HANGUP"],
    "bcm_power_toggle": ["SWC_MODE",    "SWC2_MODE"],
    "voice_aa_trigger": ["SWC_VOICE",   "SWC2_VOICE"],
    "navigate_aa":      ["SWC_SRC",     "SWC2_SRC"],
    "menu_up":          ["SWC_UP",      "SWC2_UP"],
    "menu_down":        ["SWC_DOWN",    "SWC2_DOWN"],
}

# evdev keycodes for the F-key SWC actions (phone, voice, source)
KEY_F5 = 63     # Phone pickup
KEY_F6 = 64     # Phone hangup
KEY_F7 = 65     # Voice assistant
KEY_F8 = 66     # Audio source cycle
KEY_MUTE = 113  # Volume mute

KEYCODE_TO_BUTTON: dict[int, tuple[str, str]] = {
    115: ("SWC_VOLUP",  "SWC2_VOLUP"),
    114: ("SWC_VOLDN",  "SWC2_VOLDN"),
    103: ("SWC_UP",     "SWC2_UP"),
    108: ("SWC_DOWN",   "SWC2_DOWN"),
    113: ("SWC_MUTE",   "SWC2_MUTE"),
    68:  ("SWC_MODE",   "SWC2_MODE"),
    163: ("SWC_NEXT",   "SWC2_NEXT"),
    165: ("SWC_PREV",   "SWC2_PREV"),
    63:  ("SWC_PICKUP", "SWC2_PICKUP"),
    64:  ("SWC_HANGUP", "SWC2_HANGUP"),
    65:  ("SWC_VOICE",  "SWC2_VOICE"),
    66:  ("SWC_SRC",    "SWC2_SRC"),
}


def get_all_button_names() -> list[str]:
    """Return all 24 physical SWC button names."""
    return list(ALL_BUTTONS)


def build_button_to_action_map(config: Any = None) -> dict[str, str]:
    """Build inverted button→action lookup from the action→[btn1,btn2] config.

    Reads swc.mapping from config (action-centric), inverts it into
    a flat dict: {"SWC_VOLUP": "volume_up", "SWC2_VOLUP": "volume_up", ...}.
    """
    mapping = DEFAULT_MAPPING
    if config:
        cfg_mapping = config.get("swc.mapping")
        if isinstance(cfg_mapping, dict):
            mapping = cfg_mapping

    result: dict[str, str] = {}
    for action, buttons in mapping.items():
        if action == "disabled" or action not in ACTIONS:
            continue
        if not isinstance(buttons, list):
            buttons = [buttons]
        for btn in buttons:
            if btn and isinstance(btn, str) and btn in ALL_BUTTONS:
                result[btn] = action
    return result


def get_swc_action_with_override(button_name: str, config: Any) -> str | None:
    """Get the effective action for a SWC button from the config mapping."""
    btn_map = build_button_to_action_map(config)
    action = btn_map.get(button_name)
    if action == "disabled":
        return None
    return action
