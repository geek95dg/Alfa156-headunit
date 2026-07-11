"""Lighting control — follow-me-home, greeting blinks, leaving-home.

Works with the central lock Arduino module (blinker + headlight relays).
"""

import threading
import time
from src.core.logger import get_logger

log = get_logger("lighting")


class LightingModule:
    """Intelligent lighting control triggered by lock/unlock events."""

    def __init__(self, config, event_bus, hal):
        self.config = config
        self.bus = event_bus
        self.hal = hal
        self._lock_module = None
        self._follow_me_seconds = config.get("lighting.follow_me_home_seconds", 60)
        self._greeting_blinks = config.get("lighting.greeting_blinks", 2)
        self._leaving_home = config.get("lighting.leaving_home", True)
        self._is_dark = False

        # Subscribe to lock/unlock and light sensor events
        self.bus.subscribe("vehicle.locked", self._on_lock_change)
        self.bus.subscribe("input.light_level", self._on_light_level)

    def set_lock_module(self, lock_module):
        self._lock_module = lock_module

    def start(self):
        log.info("Lighting module started (follow-me: %ds, greeting: %d blinks, leaving: %s)",
                 self._follow_me_seconds, self._greeting_blinks, self._leaving_home)

    def stop(self):
        pass

    def _on_lock_change(self, topic, locked, ts):
        if not self._lock_module:
            return

        if locked:
            # Lock → single blink greeting + follow-me-home
            log.info("Lock detected — greeting blink (1x) + follow-me-home (%ds)", self._follow_me_seconds)
            self._lock_module.blink(count=1)
            self._start_follow_me_home()
        else:
            # Unlock → double blink greeting + leaving-home (if dark)
            log.info("Unlock detected — greeting blink (%dx)", self._greeting_blinks)
            self._lock_module.blink(count=self._greeting_blinks)
            if self._leaving_home and self._is_dark:
                self._start_leaving_home()

    def _on_light_level(self, topic, value, ts):
        # LDR value: 0 (bright) to 1023 (dark)
        self._is_dark = value > 500

    def _start_follow_me_home(self):
        if self._follow_me_seconds <= 0:
            return

        def _run():
            if self._lock_module:
                self._lock_module.headlights(self._follow_me_seconds)
            self.bus.publish("vehicle.lights_follow_me", True)
            time.sleep(self._follow_me_seconds)
            self.bus.publish("vehicle.lights_follow_me", False)
            log.info("Follow-me-home timer expired")

        threading.Thread(target=_run, daemon=True).start()

    def _start_leaving_home(self):
        def _run():
            if self._lock_module:
                self._lock_module.headlights(5)
            self.bus.publish("vehicle.lights_leaving", True)
            time.sleep(5)
            self.bus.publish("vehicle.lights_leaving", False)
            log.info("Leaving-home lights off")

        threading.Thread(target=_run, daemon=True).start()


def start_lighting(config, event_bus, hal, **kwargs):
    """Module registry entry point."""
    mod = LightingModule(config, event_bus, hal)
    mod.start()
    return mod
