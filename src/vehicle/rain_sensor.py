"""Rain sensor module — auto-wiper control.

Reads rain sensor digital signal from GPIO 87 (optoisolated input).
Activates wiper relay on GPIO 88 when rain is detected.
"""

import threading
import time
from src.core.logger import get_logger

log = get_logger("rain_sensor")


class RainSensorModule:
    """Rain sensor with auto-wiper relay control."""

    def __init__(self, config, event_bus, hal):
        self.config = config
        self.bus = event_bus
        self.hal = hal
        self._running = False
        self._thread = None
        self._rain_pin = config.get("gpio.rain_sensor", 87)
        self._wiper_pin = config.get("gpio.sprayer", 88)
        self._sensitivity = config.get("rain_sensor.sensitivity", "medium")
        self._wiper_duration = {"light": 2, "medium": 5, "heavy": 10}
        self._wiper_active = False

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        log.info("Rain sensor started (pin %d → wiper pin %d)", self._rain_pin, self._wiper_pin)

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)

    def _loop(self):
        while self._running:
            try:
                rain = self.hal.gpio(self._rain_pin, "in")
                if rain and not self._wiper_active:
                    self._activate_wipers()
                    self.bus.publish("vehicle.rain_detected", True)
                elif not rain:
                    self.bus.publish("vehicle.rain_detected", False)
            except Exception:
                pass
            time.sleep(0.5)

    def _activate_wipers(self):
        self._wiper_active = True
        duration = self._wiper_duration.get(self._sensitivity, 5)
        self.bus.publish("vehicle.wipers_active", True)
        log.info("Rain detected — wipers ON for %ds", duration)

        def _off():
            time.sleep(duration)
            try:
                self.hal.gpio(self._wiper_pin, "out", 0)
            except Exception:
                pass
            self._wiper_active = False
            self.bus.publish("vehicle.wipers_active", False)

        try:
            self.hal.gpio(self._wiper_pin, "out", 1)
        except Exception:
            pass
        threading.Thread(target=_off, daemon=True).start()


def start_rain_sensor(config, event_bus, hal, **kwargs):
    """Module registry entry point."""
    mod = RainSensorModule(config, event_bus, hal)
    mod.start()
    return mod
