"""Blinker (turn signal) monitor.

Watches two GPIO input lines (left and right turn signal) and publishes
`vehicle.left_blinker` / `vehicle.right_blinker` boolean events to the
event bus whenever the state changes.

Hardware wiring (see Archive/orange-pi-5/OPI5PRO_SETUP.md; on the M910q
the same PC817 stage feeds an Arduino input instead of an OPi GPIO):
    Car 12V turn-signal wire ─ [4.7 kΩ] ─ PC817 anode
                                         PC817 cathode ─ GND
    3.3V ─ [10 kΩ] ─ PC817 collector ──── OPi GPIO pin
                     PC817 emitter ───── GND
Active-low: when 12V is present on the blinker wire the PC817 pulls the
GPIO line LOW. We invert via `active_low=True` in the config.

Bench simulation (no GPIO): create/delete the files
    /tmp/bcm_blinker_left
    /tmp/bcm_blinker_right
and the monitor will react as if the signal toggled.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from src.core.logger import get_logger

log = get_logger("vehicle.blinker")

SIM_LEFT = Path("/tmp/bcm_blinker_left")
SIM_RIGHT = Path("/tmp/bcm_blinker_right")

# Debounce window — blinkers flash on/off every ~400 ms so we use a
# short debounce and let downstream consumers decide what "active" means.
DEFAULT_POLL_S = 0.05
DEFAULT_DEBOUNCE_S = 0.02
# How long after the last high edge we still consider the blinker "active"
# (so the camera overlay doesn't flicker between blinker flashes).
DEFAULT_HOLD_S = 0.8


class BlinkerMonitor:
    """Polls two GPIO lines and publishes blinker state to the event bus."""

    def __init__(self, config: Any, event_bus: Any, hal: Any = None):
        self.config = config
        self.bus = event_bus
        self.hal = hal

        self._left_pin = int(config.get("gpio.blinker_left", 17))
        self._right_pin = int(config.get("gpio.blinker_right", 27))
        self._active_low = bool(
            config.get("vehicle.blinker_active_low", True)
        )
        self._hold = float(
            config.get("vehicle.blinker_hold_sec", DEFAULT_HOLD_S)
        )

        self._running = False
        self._thread: threading.Thread | None = None

        self._left_state = False
        self._right_state = False
        self._last_left_high: float = 0.0
        self._last_right_high: float = 0.0

    # ------------------------------------------------------------------ #
    # Lifecycle                                                          #
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="blinker-monitor"
        )
        self._thread.start()
        log.info(
            "Blinker monitor started — left=pin %d, right=pin %d (active_low=%s)",
            self._left_pin, self._right_pin, self._active_low,
        )

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)

    # ------------------------------------------------------------------ #
    # Polling loop                                                       #
    # ------------------------------------------------------------------ #

    def _read_raw(self, pin: int, sim_file: Path) -> bool:
        """Return the raw (not-yet-held) active state for one input.

        Tries HAL GPIO first; falls back to simulation file so bench
        testing works without any GPIO hardware.
        """
        if self.hal is not None:
            try:
                raw = self.hal.gpio(pin, "in")
                value = bool(raw)
                if self._active_low:
                    value = not value
                return value
            except Exception:
                # Fall through to simulation
                pass
        return sim_file.exists()

    def _loop(self) -> None:
        while self._running:
            now = time.monotonic()
            try:
                left_raw = self._read_raw(self._left_pin, SIM_LEFT)
                right_raw = self._read_raw(self._right_pin, SIM_RIGHT)

                if left_raw:
                    self._last_left_high = now
                if right_raw:
                    self._last_right_high = now

                # Apply hold window so we don't drop out between flashes
                new_left = left_raw or (now - self._last_left_high) < self._hold
                new_right = right_raw or (now - self._last_right_high) < self._hold

                if new_left != self._left_state:
                    self._left_state = new_left
                    self.bus.publish("vehicle.left_blinker", new_left)
                    log.info("Left blinker %s", "ON" if new_left else "OFF")

                if new_right != self._right_state:
                    self._right_state = new_right
                    self.bus.publish("vehicle.right_blinker", new_right)
                    log.info("Right blinker %s", "ON" if new_right else "OFF")

            except Exception as e:
                log.debug("Blinker read error: %s", e)

            time.sleep(DEFAULT_POLL_S)


def start_blinker_monitor(config, event_bus, hal=None, **kwargs):
    """Module registry entry point — instantiates and starts BlinkerMonitor."""
    mon = BlinkerMonitor(config, event_bus, hal)
    mon.start()
    return mon
