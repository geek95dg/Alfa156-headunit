"""Buzzer control — beep frequency proportional to distance.

Beep pattern:
    >1.0m  — no beep (safe zone)
    0.5-1m — slow beep (1 Hz)
    0.3-0.5m — fast beep (4 Hz)
    <0.3m  — continuous tone

Electrical (OPi):
    GPIO_BUZZ -> [1kOhm] -> BC547 base -> collector -> Buzzer -> +5V
    [1N4148 flyback diode across buzzer]
"""

import time
import threading
from typing import Any, Optional

from src.core.event_bus import EventBus
from src.core.logger import get_logger
from src.parking.distance import Zone, classify_distance

log = get_logger("parking.buzzer")

# Beep intervals per zone (on_time, off_time) in seconds
BEEP_PATTERNS: dict[Zone, tuple[float, float]] = {
    Zone.SAFE: (0, 0),           # No beep
    Zone.CAUTION: (0.1, 0.9),    # 1 Hz — short beep, long pause
    Zone.WARNING: (0.1, 0.15),   # 4 Hz — short beep, short pause
    Zone.DANGER: (1.0, 0),       # Continuous tone
}


class BuzzerController:
    """Controls the parking buzzer based on distance zone.

    Listens to parking.min_distance events and adjusts beep pattern.
    Uses a background thread for non-blocking beep timing.
    """

    def __init__(self, hal: Any, config: Any, event_bus: EventBus):
        """
        Args:
            hal: HAL instance for GPIO access.
            config: BCMConfig instance.
            event_bus: EventBus for subscribing to distance events.
        """
        buzzer_pin = config.get("gpio.buzzer", 84)
        self._pin = hal.gpio(buzzer_pin, "out")
        self._event_bus = event_bus
        self._current_zone = Zone.SAFE
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        log.info("BuzzerController initialized on pin %d", buzzer_pin)

    def start(self) -> None:
        """Start the buzzer control thread and subscribe to events."""
        if self._running:
            return

        self._running = True
        self._event_bus.subscribe("parking.min_distance", self._on_distance)

        self._thread = threading.Thread(target=self._beep_loop, daemon=True)
        self._thread.start()
        log.info("Buzzer started")

    def stop(self) -> None:
        """Stop the buzzer and unsubscribe."""
        self._running = False
        self._event_bus.unsubscribe("parking.min_distance", self._on_distance)

        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

        # Ensure buzzer is off
        self._pin.write(0)
        log.info("Buzzer stopped")

    def _on_distance(self, topic: str, value: Any, timestamp: float) -> None:
        """Handle parking.min_distance events."""
        zone = classify_distance(value)
        with self._lock:
            self._current_zone = zone

    def _beep_loop(self) -> None:
        """Background loop that drives the buzzer according to current zone."""
        while self._running:
            with self._lock:
                zone = self._current_zone

            on_time, off_time = BEEP_PATTERNS[zone]

            if on_time == 0:
                # No beep — buzzer off, check again shortly
                self._pin.write(0)
                time.sleep(0.1)
                continue

            if off_time == 0:
                # Continuous — buzzer stays on
                self._pin.write(1)
                time.sleep(0.05)
                continue

            # Beep pattern
            self._pin.write(1)
            time.sleep(on_time)
            if not self._running:
                break
            self._pin.write(0)
            time.sleep(off_time)

    def force_off(self) -> None:
        """Immediately silence the buzzer."""
        with self._lock:
            self._current_zone = Zone.SAFE
        self._pin.write(0)
