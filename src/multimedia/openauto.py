"""OpenAuto Pro launcher and control interface.

Manages OpenAuto Pro lifecycle on the 7" HDMI touchscreen.
On x86: windowed mode stub or skipped if not installed.
On OPi: full-screen on HDMI-2 (1024x600) with EGL/SDL2 rendering.

Entry point: start_multimedia() is called from main.py.
"""

import os
import signal
import subprocess
import threading
from typing import Any, Optional

from src.core.event_bus import EventBus
from src.core.logger import get_logger
from src.multimedia.bluetooth import BluetoothManager

log = get_logger("multimedia.openauto")

# OpenAuto Pro binary paths (common install locations)
OPENAUTO_PATHS = [
    "/usr/local/bin/autoapp",
    "/opt/openauto/bin/autoapp",
    "/usr/bin/autoapp",
]


def _find_openauto() -> Optional[str]:
    """Find OpenAuto Pro binary."""
    for path in OPENAUTO_PATHS:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


class OpenAutoController:
    """Manages OpenAuto Pro process lifecycle.

    Launches OpenAuto on the 7" screen (HDMI-2) and monitors
    its status. Restarts on crash.
    """

    def __init__(self, config: Any, event_bus: EventBus):
        self._config = config
        self._event_bus = event_bus
        self._platform = config.get("system.platform", "x86")
        self._binary = _find_openauto()
        self._process: Optional[subprocess.Popen] = None
        self._running = False
        self._monitor_thread: Optional[threading.Thread] = None

        if self._binary:
            log.info("OpenAuto found: %s", self._binary)
        else:
            log.info("OpenAuto not installed — AA will be unavailable")

        # Subscribe to lifecycle events
        self._event_bus.subscribe("power.shutting_down", self._on_shutdown)

    @property
    def available(self) -> bool:
        return self._binary is not None

    @property
    def running(self) -> bool:
        return self._running and self._process is not None and self._process.poll() is None

    def start(self) -> bool:
        """Launch OpenAuto Pro.

        Returns:
            True if launched successfully.
        """
        if self._running:
            log.warning("OpenAuto already running")
            return False

        if not self._binary:
            log.info("OpenAuto not available — skipping launch")
            self._event_bus.publish("multimedia.openauto_status", "unavailable")
            return False

        env = os.environ.copy()

        # On OPi: set display to HDMI-2
        if self._platform == "opi":
            env["DISPLAY"] = ":0"
            env["SDL_VIDEODRIVER"] = "kmsdrm"

        try:
            self._process = subprocess.Popen(
                [self._binary],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            self._running = True

            # Start watchdog
            self._monitor_thread = threading.Thread(
                target=self._watchdog, daemon=True
            )
            self._monitor_thread.start()

            self._event_bus.publish("multimedia.openauto_status", "running")
            self._event_bus.publish("audio.source_available", {
                "source": "android_auto", "available": True,
            })
            log.info("OpenAuto launched (PID %d)", self._process.pid)
            return True

        except Exception as e:
            log.error("Failed to launch OpenAuto: %s", e)
            self._event_bus.publish("multimedia.openauto_status", "error")
            return False

    def stop(self) -> None:
        """Stop OpenAuto Pro."""
        self._running = False

        if self._process and self._process.poll() is None:
            self._process.send_signal(signal.SIGTERM)
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
            log.info("OpenAuto stopped")

        self._process = None
        self._event_bus.publish("multimedia.openauto_status", "stopped")
        self._event_bus.publish("audio.source_available", {
            "source": "android_auto", "available": False,
        })

    def _watchdog(self) -> None:
        """Monitor OpenAuto process and restart on crash."""
        while self._running:
            if self._process and self._process.poll() is not None:
                exit_code = self._process.returncode
                log.warning("OpenAuto exited (code %d) — restarting", exit_code)
                self._event_bus.publish("multimedia.openauto_status", "restarting")
                self._process = None

                # Restart after brief delay
                import time
                time.sleep(2)
                if self._running:
                    self.start()
                return

            import time
            time.sleep(1)

    def _on_shutdown(self, topic: str, value: Any, timestamp: float) -> None:
        if value:
            self.stop()


def start_multimedia(config: Any, event_bus: EventBus, hal: Any = None,
                     bt_manager: Any = None, **kwargs) -> None:
    """Entry point called from main.py to start the multimedia module.

    Args:
        bt_manager: Existing BluetoothManager instance from main.py.
                    If None, a new one is created (backward compat).
    """
    # Reuse existing BluetoothManager if provided (avoids double D-Bus agent)
    if bt_manager is not None:
        bt_mgr = bt_manager
    else:
        bt_mgr = BluetoothManager(config, event_bus)
        bt_mgr.start_monitor()

    # OpenAuto controller
    openauto = OpenAutoController(config, event_bus)

    # Auto-launch OpenAuto if configured
    if config.get("multimedia.auto_start_openauto", True):
        openauto.start()

    # Auto-connect to last BT device if configured
    last_device = config.get("multimedia.last_bt_device", None)
    if last_device and bt_mgr.available:
        bt_mgr.connect(last_device)

    log.info("Multimedia module running (openauto=%s, bt=%s)",
             "active" if openauto.running else "unavailable",
             "active" if bt_mgr.available else "simulated")

    event_bus.publish("multimedia._internals", {
        "openauto": openauto,
        "bluetooth": bt_mgr,
    })
