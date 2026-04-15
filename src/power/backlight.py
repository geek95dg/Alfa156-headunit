"""PWM backlight control for 2× displays (4.3" and 7").

On OPi: GPIO PWM2 (pin 32) for 4.3", PWM3 (pin 33) for 7" display.
         BC547 → IRLZ44N MOSFET driver circuit.
On x86: Simulated — publishes brightness events for UI feedback.

Supports independent fade-in/fade-out with configurable duration.
"""

import threading
import time
from typing import Any, Optional

from src.core.event_bus import EventBus
from src.core.logger import get_logger

log = get_logger("power.backlight")

FADE_DURATION = 1.0  # 1 second fade
FADE_STEPS = 50      # Smoothness
PWM_FREQUENCY = 1000  # Hz

# GPIO PWM channels (OPi 5 Plus)
PWM_CHANNEL_43 = 2   # Pin 32 — 4.3" display
PWM_CHANNEL_7 = 3    # Pin 33 — 7" display


class BacklightController:
    """Controls PWM backlights for both displays.

    Each display has independent brightness and fade control.

    Events consumed:
        - power.backlight_fade: 'in' or 'out'
        - power.backlight_brightness: {display: str, brightness: int}

    Events published:
        - power.backlight_level: {display: str, brightness: int}
    """

    def __init__(self, config: Any, event_bus: EventBus, hal: Any = None):
        self._config = config
        self._event_bus = event_bus
        self._hal = hal
        self._platform = config.get("system.platform", "x86")

        # Brightness state (0-100%)
        self._brightness = {
            "small": 0,  # 4.3" display
            "large": 0,  # 7" display
        }
        self._target_brightness = {
            "small": config.get("power.backlight_small", 80),
            "large": config.get("power.backlight_large", 80),
        }

        self._fade_threads: dict[str, Optional[threading.Thread]] = {
            "small": None,
            "large": None,
        }
        self._fade_cancel: dict[str, bool] = {
            "small": False,
            "large": False,
        }

        # Subscribe to events
        self._event_bus.subscribe("power.backlight_fade", self._on_fade)
        self._event_bus.subscribe("power.backlight_brightness", self._on_brightness)

        # Initialize PWM on OPi
        if self._platform == "opi" and hal:
            self._init_pwm()

        log.info("BacklightController initialized (platform=%s)", self._platform)

    def _init_pwm(self) -> None:
        """Initialize hardware PWM channels."""
        if self._hal:
            try:
                self._hal.pwm_setup(PWM_CHANNEL_43, PWM_FREQUENCY)
                self._hal.pwm_setup(PWM_CHANNEL_7, PWM_FREQUENCY)
                log.info("PWM channels initialized")
            except Exception as e:
                log.error("PWM init failed: %s", e)

    def get_brightness(self, display: str) -> int:
        """Get current brightness for a display (0-100)."""
        return self._brightness.get(display, 0)

    def set_brightness(self, display: str, brightness: int) -> None:
        """Set brightness immediately (no fade).

        Args:
            display: 'small' (4.3") or 'large' (7").
            brightness: 0-100 percentage.
        """
        brightness = max(0, min(100, brightness))
        self._brightness[display] = brightness
        self._apply_pwm(display, brightness)
        self._event_bus.publish("power.backlight_level", {
            "display": display,
            "brightness": brightness,
        })

    def fade_in(self, display: Optional[str] = None, duration: float = FADE_DURATION) -> None:
        """Fade in backlight(s) to target brightness.

        Args:
            display: 'small', 'large', or None for both.
            duration: Fade duration in seconds.
        """
        displays = [display] if display else ["small", "large"]
        for d in displays:
            target = self._target_brightness.get(d, 80)
            self._start_fade(d, self._brightness[d], target, duration)

    def fade_out(self, display: Optional[str] = None, duration: float = FADE_DURATION) -> None:
        """Fade out backlight(s) to 0.

        Args:
            display: 'small', 'large', or None for both.
            duration: Fade duration in seconds.
        """
        displays = [display] if display else ["small", "large"]
        for d in displays:
            self._start_fade(d, self._brightness[d], 0, duration)

    def _start_fade(self, display: str, start: int, end: int, duration: float) -> None:
        """Start a fade thread for a display."""
        self._fade_cancel[display] = True  # Cancel existing fade
        time.sleep(0.01)  # Brief pause for thread to see cancel

        self._fade_cancel[display] = False
        thread = threading.Thread(
            target=self._fade_loop,
            args=(display, start, end, duration),
            daemon=True,
        )
        self._fade_threads[display] = thread
        thread.start()

    def _fade_loop(self, display: str, start: int, end: int, duration: float) -> None:
        """Smooth brightness transition."""
        step_duration = duration / FADE_STEPS
        diff = end - start

        for i in range(FADE_STEPS + 1):
            if self._fade_cancel.get(display, False):
                return

            current = int(start + (diff * i / FADE_STEPS))
            self.set_brightness(display, current)
            if i < FADE_STEPS:
                time.sleep(step_duration)

        log.debug("Fade complete: %s → %d%%", display, end)

    def _apply_pwm(self, display: str, brightness: int) -> None:
        """Apply PWM duty cycle to hardware."""
        if self._platform != "opi" or not self._hal:
            return

        channel = PWM_CHANNEL_43 if display == "small" else PWM_CHANNEL_7
        duty = brightness / 100.0
        try:
            self._hal.pwm_write(channel, duty)
        except Exception as e:
            log.error("PWM write failed: %s", e)

    # --- Event handlers ---

    def _on_fade(self, topic: str, value: Any, timestamp: float) -> None:
        if value == "in":
            self.fade_in()
        elif value == "out":
            self.fade_out()

    def _on_brightness(self, topic: str, value: Any, timestamp: float) -> None:
        if isinstance(value, dict):
            display = value.get("display")
            brightness = value.get("brightness")
            if display and brightness is not None:
                self.set_brightness(display, brightness)
