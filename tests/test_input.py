"""Tests for Input Controllers module (Part 8)."""

import pytest

from src.core.event_bus import EventBus
from src.input.action_dispatch import (
    ActionDispatcher, KEYCODE_MAP, KEYBOARD_MAP,
    KEY_UP, KEY_DOWN, KEY_ENTER, KEY_HOME, KEY_BACK,
    KEY_VOLUMEUP, KEY_VOLUMEDOWN, KEY_MUTE, KEY_NEXTSONG, KEY_PREVIOUSSONG,
    KEY_PLAYPAUSE, KEY_PHONE, KEY_MEDIA,
    KEY_F5, KEY_F6, KEY_F7, KEY_F8,
)
from src.input.swc_remote import (
    SWC_BUTTONS, get_swc_button_names, get_swc_action,
    KEY_F5 as SWC_KEY_F5, KEY_MUTE as SWC_KEY_MUTE,
)


# ---------------------------------------------------------------------------
# Action Dispatcher tests
# ---------------------------------------------------------------------------

class TestActionDispatcher:
    def setup_method(self):
        self.bus = EventBus()
        self.disp = ActionDispatcher(self.bus)

    def test_keycode_map_defined(self):
        assert len(KEYCODE_MAP) > 0
        assert KEY_UP in KEYCODE_MAP
        assert KEY_DOWN in KEYCODE_MAP
        assert KEY_ENTER in KEYCODE_MAP

    def test_keyboard_map_defined(self):
        assert len(KEYBOARD_MAP) > 0
        assert "up" in KEYBOARD_MAP
        assert "down" in KEYBOARD_MAP

    def test_dispatch_menu_up(self):
        received = []
        self.bus.subscribe("input.menu_up", lambda t, v, ts: received.append(t))

        assert self.disp.dispatch_keycode(KEY_UP)
        assert len(received) == 1

    def test_dispatch_menu_down(self):
        received = []
        self.bus.subscribe("input.menu_down", lambda t, v, ts: received.append(t))

        assert self.disp.dispatch_keycode(KEY_DOWN)
        assert len(received) == 1

    def test_dispatch_enter(self):
        received = []
        self.bus.subscribe("input.menu_select", lambda t, v, ts: received.append(t))

        assert self.disp.dispatch_keycode(KEY_ENTER)
        assert len(received) == 1

    def test_dispatch_home(self):
        received = []
        self.bus.subscribe("input.home", lambda t, v, ts: received.append(t))

        assert self.disp.dispatch_keycode(KEY_HOME)
        assert len(received) == 1

    def test_dispatch_back(self):
        received = []
        self.bus.subscribe("input.back", lambda t, v, ts: received.append(t))

        assert self.disp.dispatch_keycode(KEY_BACK)
        assert len(received) == 1

    def test_dispatch_volume_up(self):
        received = []
        self.bus.subscribe("input.volume_up", lambda t, v, ts: received.append(t))

        assert self.disp.dispatch_keycode(KEY_VOLUMEUP)
        assert len(received) == 1

    def test_dispatch_volume_down(self):
        received = []
        self.bus.subscribe("input.volume_down", lambda t, v, ts: received.append(t))

        assert self.disp.dispatch_keycode(KEY_VOLUMEDOWN)
        assert len(received) == 1

    def test_dispatch_next_track(self):
        received = []
        self.bus.subscribe("input.next_track", lambda t, v, ts: received.append(t))

        assert self.disp.dispatch_keycode(KEY_NEXTSONG)
        assert len(received) == 1

    def test_dispatch_prev_track(self):
        received = []
        self.bus.subscribe("input.prev_track", lambda t, v, ts: received.append(t))

        assert self.disp.dispatch_keycode(KEY_PREVIOUSSONG)
        assert len(received) == 1

    def test_dispatch_play_pause(self):
        received = []
        self.bus.subscribe("input.play_pause", lambda t, v, ts: received.append(t))

        assert self.disp.dispatch_keycode(KEY_PLAYPAUSE)
        assert len(received) == 1

    def test_dispatch_phone(self):
        received = []
        self.bus.subscribe("input.phone", lambda t, v, ts: received.append(t))

        assert self.disp.dispatch_keycode(KEY_PHONE)
        assert len(received) == 1

    def test_dispatch_media_button(self):
        received = []
        self.bus.subscribe("input.media_button", lambda t, v, ts: received.append(t))

        assert self.disp.dispatch_keycode(KEY_MEDIA)
        assert len(received) == 1

    def test_dispatch_mute(self):
        received = []
        self.bus.subscribe("input.mute", lambda t, v, ts: received.append(t))

        assert self.disp.dispatch_keycode(KEY_MUTE)
        assert len(received) == 1

    def test_dispatch_swc_phone_pickup(self):
        received = []
        self.bus.subscribe("input.phone_pickup", lambda t, v, ts: received.append(t))

        assert self.disp.dispatch_keycode(KEY_F5)
        assert len(received) == 1

    def test_dispatch_swc_phone_hangup(self):
        received = []
        self.bus.subscribe("input.phone_hangup", lambda t, v, ts: received.append(t))

        assert self.disp.dispatch_keycode(KEY_F6)
        assert len(received) == 1

    def test_dispatch_swc_voice_trigger(self):
        received = []
        self.bus.subscribe("input.voice_trigger", lambda t, v, ts: received.append(t))

        assert self.disp.dispatch_keycode(KEY_F7)
        assert len(received) == 1

    def test_dispatch_swc_source_cycle(self):
        received = []
        self.bus.subscribe("input.source_cycle", lambda t, v, ts: received.append(t))

        assert self.disp.dispatch_keycode(KEY_F8)
        assert len(received) == 1

    def test_unmapped_keycode(self):
        assert not self.disp.dispatch_keycode(999)

    def test_dispatch_keyname(self):
        received = []
        self.bus.subscribe("input.menu_up", lambda t, v, ts: received.append(t))

        assert self.disp.dispatch_keyname("up")
        assert len(received) == 1

    def test_dispatch_keyname_case_insensitive(self):
        received = []
        self.bus.subscribe("input.menu_down", lambda t, v, ts: received.append(t))

        assert self.disp.dispatch_keyname("DOWN")
        assert len(received) == 1

    def test_dispatch_keyname_unknown(self):
        assert not self.disp.dispatch_keyname("nonexistent")

    def test_keyboard_volume_keys(self):
        received = []
        self.bus.subscribe("input.volume_up", lambda t, v, ts: received.append(t))
        self.bus.subscribe("input.volume_down", lambda t, v, ts: received.append(t))

        self.disp.dispatch_keyname("+")
        self.disp.dispatch_keyname("-")
        assert len(received) == 2

    def test_event_bus_raw_keycode(self):
        received = []
        self.bus.subscribe("input.menu_up", lambda t, v, ts: received.append(t))

        self.bus.publish("input.raw_keycode", KEY_UP)
        assert len(received) == 1

    def test_event_bus_raw_keyname(self):
        received = []
        self.bus.subscribe("input.menu_select", lambda t, v, ts: received.append(t))

        self.bus.publish("input.raw_keyname", "enter")
        assert len(received) == 1


# ---------------------------------------------------------------------------
# All keycodes have valid event bus topics
# ---------------------------------------------------------------------------

class TestKeycodeMapping:
    def test_all_keycode_actions_have_prefix(self):
        for code, action in KEYCODE_MAP.items():
            assert action.startswith("input."), f"Action {action} missing 'input.' prefix"

    def test_all_keyboard_keys_map_to_valid_keycodes(self):
        for name, code in KEYBOARD_MAP.items():
            assert code in KEYCODE_MAP, f"Keyboard key '{name}' maps to unmapped code {code}"

    def test_expected_keycodes_present(self):
        expected = [
            KEY_UP, KEY_DOWN, KEY_ENTER, KEY_HOME, KEY_BACK,
            KEY_VOLUMEUP, KEY_VOLUMEDOWN, KEY_MUTE, KEY_NEXTSONG,
            KEY_PREVIOUSSONG, KEY_PLAYPAUSE, KEY_PHONE, KEY_MEDIA,
            KEY_F5, KEY_F6, KEY_F7, KEY_F8,
        ]
        for code in expected:
            assert code in KEYCODE_MAP, f"Keycode {code} not in map"


# ---------------------------------------------------------------------------
# SWC Remote module tests
# ---------------------------------------------------------------------------

class TestSWCRemote:
    def test_swc_buttons_defined(self):
        assert len(SWC_BUTTONS) == 12

    def test_get_swc_button_names(self):
        names = get_swc_button_names()
        assert len(names) == 12
        assert "SWC_VOLUP" in names
        assert "SWC_VOICE" in names
        assert "SWC_SRC" in names

    def test_get_swc_action(self):
        assert get_swc_action("SWC_VOLUP") == "volume_up"
        assert get_swc_action("SWC_PICKUP") == "phone_pickup"
        assert get_swc_action("SWC_VOICE") == "voice_trigger"
        assert get_swc_action("SWC_SRC") == "source_cycle"

    def test_get_swc_action_unknown(self):
        assert get_swc_action("NONEXISTENT") is None

    def test_swc_keycodes_match_dispatch(self):
        """SWC F-key keycodes should be in the action dispatch map."""
        assert SWC_KEY_F5 in KEYCODE_MAP
        assert SWC_KEY_MUTE in KEYCODE_MAP

    def test_all_swc_actions_have_matching_dispatch(self):
        """Every SWC action should have a corresponding input.* event in KEYCODE_MAP."""
        dispatch_actions = set(KEYCODE_MAP.values())
        for btn_name, action_suffix in SWC_BUTTONS.items():
            event = f"input.{action_suffix}"
            assert event in dispatch_actions, \
                f"SWC {btn_name} → input.{action_suffix} not in KEYCODE_MAP"
