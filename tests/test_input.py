"""Tests for Input Controllers module (Part 8)."""

import pytest

from src.core.event_bus import EventBus
from src.input.action_dispatch import (
    ActionDispatcher, KEYCODE_MAP, KEYBOARD_MAP,
    KEY_UP, KEY_DOWN, KEY_ENTER, KEY_HOME, KEY_BACK,
    KEY_VOLUMEUP, KEY_VOLUMEDOWN, KEY_MUTE, KEY_NEXTSONG, KEY_PREVIOUSSONG,
    KEY_PLAYPAUSE, KEY_PHONE, KEY_MEDIA,
    KEY_F5, KEY_F6, KEY_F7, KEY_F8, KEY_F9,
)
from src.input.swc_remote import (
    SWC_BUTTONS, get_swc_button_names, get_swc_action,
    get_swc_action_with_override,
    KEY_F5 as SWC_KEY_F5, KEY_MUTE as SWC_KEY_MUTE,
)
from src.power.brightness import (
    BrightnessController, BRIGHTNESS_STEPS, LIGHT_SENSOR_MAP,
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

    def test_dispatch_brightness_cycle(self):
        received = []
        self.bus.subscribe("input.brightness_cycle", lambda t, v, ts: received.append(t))

        assert self.disp.dispatch_keycode(KEY_F9)
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
            KEY_F5, KEY_F6, KEY_F7, KEY_F8, KEY_F9,
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

    def test_get_swc_action_with_override_default(self):
        """Without config, should return default action."""
        assert get_swc_action_with_override("SWC_VOLUP", None) == "volume_up"

    def test_get_swc_action_with_override_disabled(self):
        """Config set to 'disabled' should return None."""
        class MockConfig:
            def get(self, key):
                if key == "swc.buttons.SWC_VOLUP":
                    return "disabled"
                return None
        assert get_swc_action_with_override("SWC_VOLUP", MockConfig()) is None

    def test_get_swc_action_with_override_custom(self):
        """Config override should take precedence."""
        class MockConfig:
            def get(self, key):
                if key == "swc.buttons.SWC_VOLUP":
                    return "brightness_cycle"
                return None
        assert get_swc_action_with_override("SWC_VOLUP", MockConfig()) == "brightness_cycle"


# ---------------------------------------------------------------------------
# Brightness Controller tests
# ---------------------------------------------------------------------------

class _FakeConfig:
    """Minimal config mock for BrightnessController."""
    def __init__(self):
        self._data = {"display": {"dashboard": {"brightness": 80}}}

    def get(self, dotpath, default=None):
        keys = dotpath.split(".")
        node = self._data
        for k in keys:
            if isinstance(node, dict) and k in node:
                node = node[k]
            else:
                return default
        return node


class TestBrightnessController:
    def setup_method(self):
        self.bus = EventBus()
        self.config = _FakeConfig()
        self.ctrl = BrightnessController(self.config, self.bus)

    def test_initial_mode_is_auto(self):
        assert self.ctrl.mode == "auto"

    def test_initial_brightness(self):
        assert self.ctrl.brightness == 80

    def test_manual_step_in_auto_mode(self):
        assert self.ctrl.manual_step == -1

    def test_cycle_brightness_enters_manual(self):
        self.ctrl.cycle_brightness()
        assert self.ctrl.mode == "manual"
        assert self.ctrl.manual_step >= 0

    def test_cycle_brightness_6_steps(self):
        """Cycling 6 times should visit all steps."""
        seen = set()
        for _ in range(6):
            b = self.ctrl.cycle_brightness()
            seen.add(b)
        assert seen == set(BRIGHTNESS_STEPS)

    def test_cycle_brightness_wraps(self):
        """Cycling 7 times wraps back to the first step after manual entry."""
        # First press enters manual, finds closest to 80 → step 4 (80%)
        self.ctrl.cycle_brightness()  # → 80% (closest to current)
        values = []
        for _ in range(6):
            values.append(self.ctrl.cycle_brightness())
        # Should wrap around: 100, 15, 30, 45, 60, 80
        assert values[0] == 100
        assert values[1] == 15

    def test_sensor_updates_auto_brightness(self):
        """In auto mode, sensor readings should change brightness."""
        # ADC < 100 → 100% brightness
        result = self.ctrl.update_from_sensor(50)
        assert result == 100
        assert self.ctrl.brightness == 100

    def test_sensor_dark_low_brightness(self):
        """High ADC (dark) should give low brightness."""
        result = self.ctrl.update_from_sensor(950)
        assert result == 15
        assert self.ctrl.brightness == 15

    def test_sensor_ignored_in_manual_mode(self):
        """Sensor should be ignored when manual override is active."""
        self.ctrl.cycle_brightness()  # Enter manual
        assert self.ctrl.mode == "manual"

        result = self.ctrl.update_from_sensor(50)
        assert result is None  # Ignored

    def test_ignition_off_resets_to_auto(self):
        """Ignition off should reset manual override."""
        self.ctrl.cycle_brightness()
        assert self.ctrl.mode == "manual"

        self.ctrl.reset_manual_override()
        assert self.ctrl.mode == "auto"

    def test_brightness_publishes_events(self):
        """Brightness changes should publish events to both screens."""
        received = []
        self.bus.subscribe("power.backlight_brightness",
                           lambda t, v, ts: received.append(v))

        self.ctrl.update_from_sensor(50)  # → 100%
        # Should publish for both "small" and "large"
        assert len(received) == 2
        displays = {r["display"] for r in received}
        assert displays == {"small", "large"}

    def test_event_bus_stalk_press(self):
        """Stalk press event should trigger brightness cycle."""
        self.bus.publish("input.brightness_cycle", True)
        assert self.ctrl.mode == "manual"

    def test_event_bus_light_level(self):
        """Arduino light level event should update auto brightness."""
        received = []
        self.bus.subscribe("power.brightness_level",
                           lambda t, v, ts: received.append(v))

        self.bus.publish("arduino.light_level", 50)
        assert len(received) == 1
        assert received[0] == 100

    def test_event_bus_ignition_off(self):
        """Ignition off event should reset manual override."""
        self.ctrl.cycle_brightness()
        self.bus.publish("power.ignition_off", True)
        assert self.ctrl.mode == "auto"

    def test_small_change_ignored(self):
        """Changes less than 5% should be suppressed to avoid flicker."""
        # Start at 80%, sensor gives 80% (ADC 300-500 range)
        # First set to 80% explicitly
        self.ctrl._current_brightness = 80
        result = self.ctrl.update_from_sensor(350)  # → 60%, diff = 20, should update
        assert result == 60

        result = self.ctrl.update_from_sensor(360)  # → still 60%, no change
        assert result is None

    def test_brightness_steps_constant(self):
        """Verify brightness steps are correct."""
        assert BRIGHTNESS_STEPS == [15, 30, 45, 60, 80, 100]
        assert len(BRIGHTNESS_STEPS) == 6
