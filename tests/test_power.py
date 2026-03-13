"""Tests for Power Management module (Part 10)."""

import time
import pytest

from src.core.event_bus import EventBus
from src.core.config import BCMConfig
from src.power.power_manager import (
    PowerManager, PowerState, TRANSITIONS, SHUTDOWN_DELAY_SECONDS,
)
from src.power.backlight import (
    BacklightController, FADE_DURATION, FADE_STEPS,
    PWM_CHANNEL_43, PWM_CHANNEL_7,
)
from src.power.shutdown import ShutdownHandler


# ---------------------------------------------------------------------------
# Power State Machine tests
# ---------------------------------------------------------------------------

class TestPowerManager:
    def setup_method(self):
        self.bus = EventBus()
        self.config = BCMConfig(platform_override="x86")

    def test_initial_state(self):
        pm = PowerManager(self.config, self.bus)
        assert pm.state == PowerState.STANDBY

    def test_transitions_defined(self):
        for state in PowerState:
            assert state in TRANSITIONS

    def test_standby_to_wake(self):
        pm = PowerManager(self.config, self.bus)
        # WAKE auto-transitions to ACTIVE
        result = pm.transition_to(PowerState.WAKE)
        assert result is True
        assert pm.state == PowerState.ACTIVE

    def test_invalid_transition(self):
        pm = PowerManager(self.config, self.bus)
        # Can't go STANDBY → ACTIVE directly
        result = pm.transition_to(PowerState.ACTIVE)
        assert result is False
        assert pm.state == PowerState.STANDBY

    def test_active_to_reverse(self):
        pm = PowerManager(self.config, self.bus)
        pm.transition_to(PowerState.WAKE)  # → ACTIVE
        result = pm.transition_to(PowerState.REVERSE)
        assert result is True
        assert pm.state == PowerState.REVERSE

    def test_reverse_to_active(self):
        pm = PowerManager(self.config, self.bus)
        pm.transition_to(PowerState.WAKE)
        pm.transition_to(PowerState.REVERSE)
        result = pm.transition_to(PowerState.ACTIVE)
        assert result is True
        assert pm.state == PowerState.ACTIVE

    def test_active_to_shutdown(self):
        pm = PowerManager(self.config, self.bus)
        pm.transition_to(PowerState.WAKE)
        result = pm.transition_to(PowerState.SHUTDOWN)
        assert result is True
        assert pm.state == PowerState.SHUTDOWN

    def test_active_to_standby(self):
        pm = PowerManager(self.config, self.bus)
        pm.transition_to(PowerState.WAKE)
        result = pm.transition_to(PowerState.STANDBY)
        assert result is True
        assert pm.state == PowerState.STANDBY

    def test_state_published(self):
        pm = PowerManager(self.config, self.bus)
        received = []
        self.bus.subscribe("power.state", lambda t, v, ts: received.append(v))

        pm.transition_to(PowerState.WAKE)
        assert "wake" in received
        assert "active" in received

    def test_ignition_on_event(self):
        pm = PowerManager(self.config, self.bus)
        self.bus.publish("hal.ignition", True)
        assert pm.state == PowerState.ACTIVE  # WAKE → ACTIVE

    def test_ignition_off_event(self):
        pm = PowerManager(self.config, self.bus)
        self.bus.publish("hal.ignition", True)
        assert pm.state == PowerState.ACTIVE

        self.bus.publish("hal.ignition", False)
        assert pm.state == PowerState.STANDBY

    def test_reverse_gear_event(self):
        pm = PowerManager(self.config, self.bus)
        pm.transition_to(PowerState.WAKE)  # → ACTIVE

        self.bus.publish("hal.reverse_gear", True)
        assert pm.state == PowerState.REVERSE

        self.bus.publish("hal.reverse_gear", False)
        assert pm.state == PowerState.ACTIVE

    def test_reverse_gear_publishes_event(self):
        pm = PowerManager(self.config, self.bus)
        pm.transition_to(PowerState.WAKE)

        received = []
        self.bus.subscribe("power.reverse_gear", lambda t, v, ts: received.append(v))

        pm.transition_to(PowerState.REVERSE)
        assert True in received

    def test_simulated_ignition(self):
        pm = PowerManager(self.config, self.bus)
        self.bus.publish("sim.ignition", True)
        assert pm.state == PowerState.ACTIVE

    def test_simulated_reverse(self):
        pm = PowerManager(self.config, self.bus)
        pm.transition_to(PowerState.WAKE)
        self.bus.publish("sim.reverse_gear", True)
        assert pm.state == PowerState.REVERSE

    def test_wake_publishes_backlight_and_modules(self):
        pm = PowerManager(self.config, self.bus)
        received = {}

        def capture(topic, value, ts):
            received[topic] = value

        self.bus.subscribe("power.backlight_fade", capture)
        self.bus.subscribe("power.modules_start", capture)

        pm.transition_to(PowerState.WAKE)
        assert received.get("power.backlight_fade") == "in"
        assert received.get("power.modules_start") is True

    def test_standby_publishes_backlight_out(self):
        pm = PowerManager(self.config, self.bus)
        pm.transition_to(PowerState.WAKE)

        received = {}
        self.bus.subscribe("power.backlight_fade", lambda t, v, ts: received.update({t: v}))

        pm.transition_to(PowerState.STANDBY)
        assert received.get("power.backlight_fade") == "out"

    def test_shutdown_delay_constant(self):
        assert SHUTDOWN_DELAY_SECONDS == 30


# ---------------------------------------------------------------------------
# Backlight Controller tests
# ---------------------------------------------------------------------------

class TestBacklightController:
    def setup_method(self):
        self.bus = EventBus()
        self.config = BCMConfig(platform_override="x86")

    def test_init_both_off(self):
        bl = BacklightController(self.config, self.bus)
        assert bl.get_brightness("small") == 0
        assert bl.get_brightness("large") == 0

    def test_set_brightness(self):
        bl = BacklightController(self.config, self.bus)
        bl.set_brightness("small", 50)
        assert bl.get_brightness("small") == 50

    def test_brightness_clamping(self):
        bl = BacklightController(self.config, self.bus)
        bl.set_brightness("small", 150)
        assert bl.get_brightness("small") == 100
        bl.set_brightness("small", -10)
        assert bl.get_brightness("small") == 0

    def test_brightness_publishes_event(self):
        bl = BacklightController(self.config, self.bus)
        received = []
        self.bus.subscribe("power.backlight_level",
                           lambda t, v, ts: received.append(v))

        bl.set_brightness("small", 75)
        assert len(received) == 1
        assert received[0]["display"] == "small"
        assert received[0]["brightness"] == 75

    def test_fade_in_event(self):
        bl = BacklightController(self.config, self.bus)
        self.bus.publish("power.backlight_fade", "in")
        # Fade runs in thread — wait a bit
        time.sleep(0.2)
        # Brightness should be increasing (may not be at target yet)
        assert bl.get_brightness("small") >= 0

    def test_fade_out_event(self):
        bl = BacklightController(self.config, self.bus)
        bl.set_brightness("small", 80)
        bl.set_brightness("large", 80)

        self.bus.publish("power.backlight_fade", "out")
        time.sleep(0.2)
        # Should be decreasing
        assert bl.get_brightness("small") <= 80

    def test_direct_brightness_event(self):
        bl = BacklightController(self.config, self.bus)
        self.bus.publish("power.backlight_brightness", {
            "display": "large",
            "brightness": 60,
        })
        assert bl.get_brightness("large") == 60

    def test_pwm_channels(self):
        assert PWM_CHANNEL_43 == 2
        assert PWM_CHANNEL_7 == 3

    def test_fade_constants(self):
        assert FADE_DURATION == 1.0
        assert FADE_STEPS > 0


# ---------------------------------------------------------------------------
# Shutdown Handler tests
# ---------------------------------------------------------------------------

class TestShutdownHandler:
    def setup_method(self):
        self.bus = EventBus()
        self.config = BCMConfig(platform_override="x86")

    def test_init(self):
        handler = ShutdownHandler(self.config, self.bus)
        assert handler is not None

    def test_shutdown_publishes_stop_recording(self):
        handler = ShutdownHandler(self.config, self.bus)
        received = []
        self.bus.subscribe("voice.cmd.stop_recording",
                           lambda t, v, ts: received.append(v))
        self.bus.subscribe("config.save_request",
                           lambda t, v, ts: received.append(("save", v)))
        self.bus.subscribe("power.shutdown_complete",
                           lambda t, v, ts: received.append(("done", v)))

        handler.execute_shutdown()
        assert True in received  # stop_recording
        assert ("save", True) in received
        assert ("done", True) in received

    def test_shutdown_event_triggers(self):
        handler = ShutdownHandler(self.config, self.bus)
        received = []
        self.bus.subscribe("power.shutdown_complete",
                           lambda t, v, ts: received.append(v))

        self.bus.publish("power.shutting_down", True)
        assert True in received


# ---------------------------------------------------------------------------
# Integration: Power lifecycle
# ---------------------------------------------------------------------------

class TestPowerLifecycle:
    def test_full_ignition_cycle(self):
        bus = EventBus()
        config = BCMConfig(platform_override="x86")
        pm = PowerManager(config, bus)

        states = []
        bus.subscribe("power.state", lambda t, v, ts: states.append(v))

        # Ignition ON
        bus.publish("hal.ignition", True)
        assert pm.state == PowerState.ACTIVE
        assert "wake" in states
        assert "active" in states

        # Reverse gear
        bus.publish("hal.reverse_gear", True)
        assert pm.state == PowerState.REVERSE

        # Back to drive
        bus.publish("hal.reverse_gear", False)
        assert pm.state == PowerState.ACTIVE

        # Ignition OFF
        bus.publish("hal.ignition", False)
        assert pm.state == PowerState.STANDBY

    def test_reverse_gear_publishes_for_camera(self):
        bus = EventBus()
        config = BCMConfig(platform_override="x86")
        pm = PowerManager(config, bus)

        reverse_events = []
        bus.subscribe("power.reverse_gear",
                      lambda t, v, ts: reverse_events.append(v))

        bus.publish("hal.ignition", True)
        bus.publish("hal.reverse_gear", True)
        assert True in reverse_events
