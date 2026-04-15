"""Icing detection algorithm.

Rules:
    - Temperature < 3°C with falling trend -> icing alert (one-shot popup + 3x buzzer)
    - Temperature <= 0°C -> permanent snowflake icon on status bar
    - Alert re-triggers only after temperature rises above 5°C (hysteresis)

Published events:
    - env.icing_alert: True when icing warning triggered
    - env.icing_icon: True when snowflake icon should be shown (temp <= 0°C)
"""

from typing import Any

from src.core.event_bus import EventBus
from src.core.logger import get_logger

log = get_logger("environment.icing")

# Thresholds
ICING_ALERT_THRESHOLD = 3.0     # °C — alert when dropping below this
ICING_ICON_THRESHOLD = 0.0      # °C — snowflake icon when at or below
ICING_RESET_THRESHOLD = 5.0     # °C — reset alert after rising above this
MIN_TREND_SAMPLES = 3           # Minimum samples to detect falling trend


class IcingDetector:
    """Detects icing conditions based on temperature readings.

    Subscribes to `env.temperature` events and publishes icing alerts.
    Uses hysteresis to prevent alert flapping near the threshold.
    """

    def __init__(self, event_bus: EventBus):
        self._event_bus = event_bus
        self._history: list[float] = []
        self._alert_active = False
        self._alert_armed = True  # Can trigger alert
        self._icon_active = False

        # Subscribe to temperature events
        self._event_bus.subscribe("env.temperature", self._on_temperature)
        log.info("IcingDetector initialized")

    def _on_temperature(self, topic: str, value: Any, timestamp: float) -> None:
        """Handle temperature readings."""
        if not isinstance(value, (int, float)):
            return

        temp = float(value)
        self._history.append(temp)

        # Keep limited history
        if len(self._history) > 10:
            self._history.pop(0)

        # Check snowflake icon
        should_show_icon = temp <= ICING_ICON_THRESHOLD
        if should_show_icon != self._icon_active:
            self._icon_active = should_show_icon
            self._event_bus.publish("env.icing_icon", should_show_icon)
            log.info("Icing icon %s (temp=%.1f°C)",
                     "ON" if should_show_icon else "OFF", temp)

        # Reset alert arm when temperature rises above hysteresis threshold
        if temp > ICING_RESET_THRESHOLD and not self._alert_armed:
            self._alert_armed = True
            self._alert_active = False
            log.debug("Icing alert re-armed (temp=%.1f°C)", temp)

        # Check icing alert condition
        if self._alert_armed and temp < ICING_ALERT_THRESHOLD:
            if self._is_falling_trend():
                self._trigger_alert(temp)

    def _is_falling_trend(self) -> bool:
        """Check if temperature has a falling trend."""
        if len(self._history) < MIN_TREND_SAMPLES:
            return True  # Not enough data — err on the side of caution

        recent = self._history[-MIN_TREND_SAMPLES:]
        # Falling if each reading is lower than or equal to the previous
        falling = all(recent[i] <= recent[i - 1] for i in range(1, len(recent)))
        return falling

    def _trigger_alert(self, temp: float) -> None:
        """Trigger the icing alert."""
        self._alert_active = True
        self._alert_armed = False  # Won't re-trigger until reset

        self._event_bus.publish("env.icing_alert", True)
        log.warning("ICING ALERT triggered at %.1f°C", temp)

    @property
    def alert_active(self) -> bool:
        return self._alert_active

    @property
    def icon_active(self) -> bool:
        return self._icon_active

    def reset(self) -> None:
        """Reset all state."""
        self._history.clear()
        self._alert_active = False
        self._alert_armed = True
        self._icon_active = False
