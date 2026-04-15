"""Graceful shutdown — stop services, flush logs, sync filesystem.

Shutdown sequence:
    1. Stop dashcam recording
    2. Save current state/config
    3. Flush logs
    4. Sync filesystem
    5. Power down (OPi) or exit (x86)

Entry point: start_power() is called from main.py.
"""

import subprocess
import sys
from typing import Any

from src.core.event_bus import EventBus
from src.core.logger import get_logger
from src.power.power_manager import PowerManager, PowerState
from src.power.backlight import BacklightController

log = get_logger("power.shutdown")


class ShutdownHandler:
    """Handles graceful system shutdown.

    Subscribes to power.shutting_down event and executes
    the shutdown sequence.
    """

    def __init__(self, config: Any, event_bus: EventBus):
        self._config = config
        self._event_bus = event_bus
        self._platform = config.get("system.platform", "x86")

        self._event_bus.subscribe("power.shutting_down", self._on_shutdown)
        log.info("ShutdownHandler initialized")

    def execute_shutdown(self) -> None:
        """Execute the shutdown sequence."""
        log.info("=== SHUTDOWN SEQUENCE STARTED ===")

        # 1. Stop dashcam recording
        log.info("[1/5] Stopping dashcam...")
        self._event_bus.publish("voice.cmd.stop_recording", True)

        # 2. Save state
        log.info("[2/5] Saving state...")
        self._event_bus.publish("config.save_request", True)

        # 3. Flush logs
        log.info("[3/5] Flushing logs...")
        # Python logging flushes on handler close

        # 4. Sync filesystem
        log.info("[4/5] Syncing filesystem...")
        try:
            subprocess.run(["sync"], timeout=10)
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            log.warning("Sync failed: %s", e)

        # 5. Power down or exit
        log.info("[5/5] Powering down...")
        if self._platform == "opi":
            self._power_down()
        else:
            log.info("=== SHUTDOWN COMPLETE (x86 — exiting) ===")
            self._event_bus.publish("power.shutdown_complete", True)

    def _power_down(self) -> None:
        """Issue system poweroff command (OPi only)."""
        log.info("Issuing system poweroff")
        try:
            subprocess.run(["sudo", "poweroff"], timeout=5)
        except Exception as e:
            log.error("Poweroff failed: %s", e)

    def _on_shutdown(self, topic: str, value: Any, timestamp: float) -> None:
        if value:
            self.execute_shutdown()


def start_power(config: Any, event_bus: EventBus, hal: Any = None,
                **kwargs) -> None:
    """Entry point called from main.py to start the power module."""
    # Power state machine
    power_mgr = PowerManager(config, event_bus, hal)

    # Backlight controller
    backlight = BacklightController(config, event_bus, hal)

    # Shutdown handler
    shutdown = ShutdownHandler(config, event_bus)

    # If ignition is already on at startup, transition to active
    if hal and hasattr(hal, 'read_gpio'):
        ign_pin = config.get("power.ignition_pin", None)
        if ign_pin is not None:
            try:
                if hal.read_gpio(ign_pin):
                    power_mgr.transition_to(PowerState.WAKE)
            except Exception as e:
                log.warning("Could not read ignition GPIO: %s", e)

    log.info("Power module running (state=%s)", power_mgr.state.value)

    event_bus.publish("power._internals", {
        "power_manager": power_mgr,
        "backlight": backlight,
        "shutdown": shutdown,
    })
