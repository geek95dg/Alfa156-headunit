"""Performance timer — 0-100 km/h tracking + boost peak.

Subscribes to GPS speed and OBD boost, tracks acceleration runs.
"""

import json
import os
import time
from src.core.logger import get_logger

log = get_logger("performance")


class PerformanceTracker:
    """Tracks 0-100 km/h times and boost peaks."""

    HISTORY_FILE = "data/performance_history.json"

    def __init__(self, event_bus):
        self.bus = event_bus
        self._timer_start = 0
        self._timer_running = False
        self._peak_boost = 0.0
        self._history = []
        self._load_history()

        self.bus.subscribe("gps.speed", self._on_speed)
        self.bus.subscribe("obd.boost", self._on_boost)

    def _on_speed(self, topic, speed, ts):
        if not self._timer_running and 3 <= speed < 10:
            self._timer_running = True
            self._timer_start = time.time()
            self.bus.publish("performance.timer_running", True)
            log.info("0-100 timer started")

        if self._timer_running and speed >= 100:
            elapsed = round(time.time() - self._timer_start, 1)
            self._timer_running = False
            self.bus.publish("performance.timer_running", False)
            self.bus.publish("performance.timer_result", elapsed)
            self._history.append({"time": elapsed, "ts": time.time()})
            self._history = self._history[-10:]  # Keep last 10
            self._save_history()
            log.info("0-100 result: %.1fs", elapsed)

        if self._timer_running and speed < 2:
            self._timer_running = False
            self.bus.publish("performance.timer_running", False)

    def _on_boost(self, topic, boost, ts):
        if boost > self._peak_boost:
            self._peak_boost = boost
            self.bus.publish("performance.boost_peak", self._peak_boost)

    def _load_history(self):
        try:
            if os.path.exists(self.HISTORY_FILE):
                with open(self.HISTORY_FILE) as f:
                    self._history = json.load(f)
        except Exception:
            self._history = []

    def _save_history(self):
        try:
            os.makedirs(os.path.dirname(self.HISTORY_FILE), exist_ok=True)
            with open(self.HISTORY_FILE, "w") as f:
                json.dump(self._history, f)
        except Exception:
            pass


def start_performance(config, event_bus, hal=None, **kwargs):
    """Module registry entry point."""
    tracker = PerformanceTracker(event_bus)
    log.info("Performance tracker started")
    return tracker
