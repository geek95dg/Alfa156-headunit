"""Power state machine — STANDBY → WAKE → ACTIVE → REVERSE → SHUTDOWN.

Manages system lifecycle based on ignition, central lock, and reverse gear signals.
On OPi: reads GPIO via HAL optoisolator inputs.
On x86: simulated via event bus (keyboard: I=ignition, R=reverse, L=lock).
"""

import threading
import time
from enum import Enum
from typing import Any, Optional

from src.core.event_bus import EventBus
from src.core.logger import get_logger

log = get_logger("power.manager")

SHUTDOWN_DELAY_SECONDS = 30  # Delay before shutdown after central lock


class PowerState(Enum):
    """System power states."""
    STANDBY = "standby"
    WAKE = "wake"
    ACTIVE = "active"
    REVERSE = "reverse"
    SHUTDOWN = "shutdown"


# Valid state transitions: current → allowed next states
TRANSITIONS: dict[PowerState, set[PowerState]] = {
    PowerState.STANDBY:  {PowerState.WAKE},
    PowerState.WAKE:     {PowerState.ACTIVE, PowerState.STANDBY},
    PowerState.ACTIVE:   {PowerState.REVERSE, PowerState.SHUTDOWN, PowerState.STANDBY},
    PowerState.REVERSE:  {PowerState.ACTIVE},
    PowerState.SHUTDOWN: {PowerState.STANDBY},
}


class PowerManager:
    """Manages system power state and lifecycle transitions.

    Signals (via event bus or HAL GPIO):
        - Ignition ON → STANDBY→WAKE→ACTIVE
        - Ignition OFF → ACTIVE→STANDBY
        - Reverse gear → ACTIVE→REVERSE (and back)
        - Central lock → start SHUTDOWN timer (30s)

    Events published:
        - power.state: current PowerState value
        - power.reverse_gear: bool
        - power.shutdown_countdown: seconds remaining
    """

    def __init__(self, config: Any, event_bus: EventBus, hal: Any = None):
        self._config = config
        self._event_bus = event_bus
        self._hal = hal
        self._state = PowerState.STANDBY
        self._lock = threading.Lock()
        self._shutdown_timer: Optional[threading.Thread] = None
        self._shutdown_cancel = False

        # Subscribe to input signals
        self._event_bus.subscribe("hal.ignition", self._on_ignition)
        self._event_bus.subscribe("hal.central_lock", self._on_central_lock)
        self._event_bus.subscribe("hal.reverse_gear", self._on_reverse_gear)

        # Keyboard simulation events (x86)
        self._event_bus.subscribe("sim.ignition", self._on_ignition)
        self._event_bus.subscribe("sim.central_lock", self._on_central_lock)
        self._event_bus.subscribe("sim.reverse_gear", self._on_reverse_gear)

        self._event_bus.publish("power.state", self._state.value)
        log.info("PowerManager initialized (state=%s)", self._state.value)

    @property
    def state(self) -> PowerState:
        return self._state

    def transition_to(self, new_state: PowerState) -> bool:
        """Attempt a state transition.

        Args:
            new_state: Target state.

        Returns:
            True if transition was valid and executed.
        """
        with self._lock:
            allowed = TRANSITIONS.get(self._state, set())
            if new_state not in allowed:
                log.warning("Invalid transition: %s → %s (allowed: %s)",
                            self._state.value, new_state.value,
                            [s.value for s in allowed])
                return False

            old_state = self._state
            self._state = new_state

        log.info("Power state: %s → %s", old_state.value, new_state.value)
        self._event_bus.publish("power.state", new_state.value)
        self._on_state_enter(new_state, old_state)
        return True

    def _on_state_enter(self, state: PowerState, prev: PowerState) -> None:
        """Execute actions when entering a new state."""
        if state == PowerState.WAKE:
            self._event_bus.publish("power.backlight_fade", "in")
            self._event_bus.publish("power.modules_start", True)
            # Auto-transition to ACTIVE after wake sequence
            self.transition_to(PowerState.ACTIVE)

        elif state == PowerState.ACTIVE:
            self._event_bus.publish("power.active", True)

        elif state == PowerState.REVERSE:
            self._event_bus.publish("power.reverse_gear", True)

        elif state == PowerState.STANDBY:
            self._event_bus.publish("power.backlight_fade", "out")
            self._event_bus.publish("power.active", False)
            if prev == PowerState.REVERSE:
                self._event_bus.publish("power.reverse_gear", False)

        elif state == PowerState.SHUTDOWN:
            self._event_bus.publish("power.shutting_down", True)

    # --- Signal handlers ---

    def _on_ignition(self, topic: str, value: Any, timestamp: float) -> None:
        if value:  # Ignition ON
            if self._state == PowerState.STANDBY:
                self._cancel_shutdown()
                self.transition_to(PowerState.WAKE)
        else:  # Ignition OFF
            if self._state in (PowerState.ACTIVE, PowerState.REVERSE):
                if self._state == PowerState.REVERSE:
                    self.transition_to(PowerState.ACTIVE)
                self.transition_to(PowerState.STANDBY)

    def _on_central_lock(self, topic: str, value: Any, timestamp: float) -> None:
        if value:  # Lock signal received
            self._start_shutdown_timer()

    def _on_reverse_gear(self, topic: str, value: Any, timestamp: float) -> None:
        if value:
            if self._state == PowerState.ACTIVE:
                self.transition_to(PowerState.REVERSE)
        else:
            if self._state == PowerState.REVERSE:
                self.transition_to(PowerState.ACTIVE)

    # --- Shutdown timer ---

    def _start_shutdown_timer(self) -> None:
        """Start countdown to shutdown."""
        self._shutdown_cancel = False
        delay = self._config.get("power.shutdown_delay", SHUTDOWN_DELAY_SECONDS)
        log.info("Shutdown timer started (%ds)", delay)

        self._shutdown_timer = threading.Thread(
            target=self._shutdown_countdown, args=(delay,), daemon=True
        )
        self._shutdown_timer.start()

    def _shutdown_countdown(self, delay: int) -> None:
        """Countdown thread for shutdown."""
        for remaining in range(delay, 0, -1):
            if self._shutdown_cancel:
                log.info("Shutdown cancelled")
                return
            if remaining <= 10 or remaining % 10 == 0:
                self._event_bus.publish("power.shutdown_countdown", remaining)
            time.sleep(1)

        if not self._shutdown_cancel:
            # Force transition through ACTIVE if needed
            if self._state == PowerState.REVERSE:
                self.transition_to(PowerState.ACTIVE)
            if self._state != PowerState.ACTIVE:
                self._state = PowerState.ACTIVE  # Force for shutdown path
            self.transition_to(PowerState.SHUTDOWN)

    def _cancel_shutdown(self) -> None:
        """Cancel pending shutdown."""
        self._shutdown_cancel = True
