"""Auto-brightness controller — light sensor + manual stalk button override.

Reads ambient light level from Arduino serial (LDR on A1) and adjusts both
screen backlights automatically. A spare stalk button cycles through 6 manual
brightness levels that override the sensor until ignition off.

Brightness levels (manual):
    Step 1: 15%   (night driving)
    Step 2: 30%   (dark)
    Step 3: 45%   (dusk/dawn)
    Step 4: 60%   (cloudy)
    Step 5: 80%   (normal)
    Step 6: 100%  (bright sun)

Light sensor mapping (auto mode):
    ADC 0-100   → 100% (bright direct sunlight)
    ADC 100-300 → 80%
    ADC 300-500 → 60%
    ADC 500-700 → 45%
    ADC 700-900 → 30%
    ADC 900+    → 15%  (darkness, high LDR resistance)
"""

from typing import Any

from src.core.event_bus import EventBus
from src.core.logger import get_logger

log = get_logger("power.brightness")

# Manual brightness steps (6 levels)
BRIGHTNESS_STEPS = [15, 30, 45, 60, 80, 100]

# Light sensor ADC thresholds → brightness (LDR: low ADC = bright, high ADC = dark)
# Sorted by ADC ascending (bright → dark)
LIGHT_SENSOR_MAP = [
    (100, 100),   # ADC < 100 → 100%
    (300, 80),    # ADC < 300 → 80%
    (500, 60),    # ADC < 500 → 60%
    (700, 45),    # ADC < 700 → 45%
    (900, 30),    # ADC < 900 → 30%
]
LIGHT_SENSOR_DARK = 15  # ADC >= 900 → 15%


class BrightnessController:
    """Manages auto/manual brightness for both displays.

    Both screens are always linked to the same brightness level.

    Events consumed:
        - input.brightness_cycle: Stalk button pressed (F9)
        - arduino.light_level: Light sensor ADC value from Arduino
        - power.ignition_off: Reset manual override

    Events published:
        - power.backlight_brightness: {display: str, brightness: int}
        - power.brightness_mode: 'auto' | 'manual'
        - power.brightness_level: int (current brightness %)
    """

    def __init__(self, config: Any, event_bus: EventBus):
        self._config = config
        self._bus = event_bus

        # Manual override state
        self._manual_override = False
        self._manual_step_index = 4  # Start at step 5 (80%) if manually cycled

        # Current brightness
        self._current_brightness = config.get("display.dashboard.brightness", 80)
        self._last_light_adc = 500  # Mid-range default

        # Subscribe to events
        self._bus.subscribe("input.brightness_cycle", self._on_stalk_press)
        self._bus.subscribe("arduino.light_level", self._on_light_level)
        self._bus.subscribe("power.ignition_off", self._on_ignition_off)

        log.info("BrightnessController initialized (mode=auto, brightness=%d%%)",
                 self._current_brightness)

    @property
    def mode(self) -> str:
        return "manual" if self._manual_override else "auto"

    @property
    def brightness(self) -> int:
        return self._current_brightness

    @property
    def manual_step(self) -> int:
        """Current manual step index (0-5), or -1 if in auto mode."""
        return self._manual_step_index if self._manual_override else -1

    def cycle_brightness(self) -> int:
        """Cycle to next manual brightness step. Returns new brightness."""
        if not self._manual_override:
            # First press: enter manual mode, find closest step to current
            self._manual_override = True
            self._manual_step_index = self._find_closest_step(self._current_brightness)
            log.info("Brightness: switched to manual mode (step %d = %d%%)",
                     self._manual_step_index + 1,
                     BRIGHTNESS_STEPS[self._manual_step_index])
        else:
            # Subsequent presses: cycle to next step
            self._manual_step_index = (self._manual_step_index + 1) % len(BRIGHTNESS_STEPS)

        new_brightness = BRIGHTNESS_STEPS[self._manual_step_index]
        self._apply_brightness(new_brightness)

        self._bus.publish("power.brightness_mode", "manual")
        log.info("Brightness: manual step %d/%d = %d%%",
                 self._manual_step_index + 1, len(BRIGHTNESS_STEPS), new_brightness)

        return new_brightness

    def update_from_sensor(self, adc_value: int) -> int | None:
        """Update brightness from light sensor. Returns new brightness or None if manual."""
        self._last_light_adc = adc_value

        if self._manual_override:
            return None  # Manual mode active, ignore sensor

        new_brightness = self._adc_to_brightness(adc_value)

        # Only update if changed by at least 5% to avoid flicker
        if abs(new_brightness - self._current_brightness) >= 5:
            self._apply_brightness(new_brightness)
            log.debug("Brightness: auto %d%% (ADC=%d)", new_brightness, adc_value)
            return new_brightness

        return None

    def reset_manual_override(self) -> None:
        """Reset to auto mode (called on ignition off)."""
        if self._manual_override:
            self._manual_override = False
            self._bus.publish("power.brightness_mode", "auto")
            log.info("Brightness: reset to auto mode (ignition off)")
            # Re-apply from last sensor reading
            new_brightness = self._adc_to_brightness(self._last_light_adc)
            self._apply_brightness(new_brightness)

    def _apply_brightness(self, brightness: int) -> None:
        """Apply brightness to both screens."""
        self._current_brightness = brightness

        # Both screens linked
        for display in ("small", "large"):
            self._bus.publish("power.backlight_brightness", {
                "display": display,
                "brightness": brightness,
            })

        self._bus.publish("power.brightness_level", brightness)

    def _adc_to_brightness(self, adc: int) -> int:
        """Convert light sensor ADC value to brightness percentage."""
        for threshold, brightness in LIGHT_SENSOR_MAP:
            if adc < threshold:
                return brightness
        return LIGHT_SENSOR_DARK

    def _find_closest_step(self, brightness: int) -> int:
        """Find the closest manual step to a given brightness."""
        best_idx = 0
        best_diff = abs(BRIGHTNESS_STEPS[0] - brightness)
        for i, step in enumerate(BRIGHTNESS_STEPS):
            diff = abs(step - brightness)
            if diff < best_diff:
                best_diff = diff
                best_idx = i
        return best_idx

    # --- Event handlers ---

    def _on_stalk_press(self, topic: str, value: Any, timestamp: float) -> None:
        self.cycle_brightness()

    def _on_light_level(self, topic: str, value: Any, timestamp: float) -> None:
        if isinstance(value, (int, float)):
            self.update_from_sensor(int(value))

    def _on_ignition_off(self, topic: str, value: Any, timestamp: float) -> None:
        self.reset_manual_override()
