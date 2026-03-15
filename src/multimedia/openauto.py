"""OpenAuto launcher and control interface.

Manages the open-source OpenAuto (openDsh) process for Android Auto.
On x86 headless: runs with QT_QPA_PLATFORM=offscreen, BT+TCP wireless AA.
On OPi: full-screen on HDMI-2 (1024x600) with EGL/SDL2 rendering.

Entry point: start_multimedia() is called from main.py.
"""

import os
import signal
import subprocess
import threading
import time
from typing import Any, Optional

from src.core.event_bus import EventBus
from src.core.logger import get_logger
from src.multimedia.bluetooth import BluetoothManager

log = get_logger("multimedia.openauto")

# OpenAuto binary paths (common install locations)
OPENAUTO_PATHS = [
    "/usr/local/bin/autoapp",
    "/opt/openauto/bin/autoapp",
    "/usr/bin/autoapp",
]


def _find_openauto() -> Optional[str]:
    """Find OpenAuto binary."""
    for path in OPENAUTO_PATHS:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def _create_openauto_config(project_dir: str, app_config: Any = None) -> None:
    """Create openauto.ini in the project directory (autoapp's working dir).

    Only creates the file if it doesn't exist — autoapp manages its own
    config at runtime (stores last BT device, settings, etc.).
    """
    config_path = os.path.join(project_dir, "openauto.ini")
    if os.path.exists(config_path):
        return

    ssid = ""
    password = ""
    if app_config:
        ssid = app_config.get("wifi.ssid", "")
        password = app_config.get("wifi.password", "")

    config_content = f"""; OpenAuto configuration for Alfa156 Headunit
[General]
HandednessOfTrafficType=0

[Video]
FPS=1
Resolution=3
MarginWidth=0
MarginHeight=0

[Audio]
MusicAudioChannelEnabled=1
SpeechAudioChannelEnabled=1
MediaAudioDelay=0

[Bluetooth]
AdapterType=0
RemoteAdapterAddress=

[Input]
ButtonCodes.Enter=23
ButtonCodes.Left=21
ButtonCodes.Right=22
ButtonCodes.Up=19
ButtonCodes.Down=20
ButtonCodes.Back=4
ButtonCodes.Home=3
TouchscreenEnabled=1
TouchscreenWidth=800
TouchscreenHeight=480

[WiFi]
SSID={ssid}
Password={password}
MAC=
"""
    with open(config_path, "w") as f:
        f.write(config_content)

    log.info("Created openauto config at %s (SSID=%s)", config_path,
             ssid or "(empty)")


class OpenAutoController:
    """Manages OpenAuto process lifecycle.

    Launches autoapp (openDsh) and monitors its status.
    On headless x86, runs with QT_QPA_PLATFORM=offscreen.
    The btservice inside autoapp handles AA wireless BT bootstrapping.
    """

    def __init__(self, config: Any, event_bus: EventBus):
        self._config = config
        self._event_bus = event_bus
        self._platform = config.get("system.platform", "x86")
        self._binary = _find_openauto()
        self._process: Optional[subprocess.Popen] = None
        self._running = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._log_thread: Optional[threading.Thread] = None

        if self._binary:
            log.info("OpenAuto found: %s", self._binary)
            # Create config in project root (autoapp reads from cwd)
            project_dir = os.path.dirname(os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))))
            _create_openauto_config(project_dir, app_config=config)
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
        """Launch OpenAuto.

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

        log.info("Starting OpenAuto: binary=%s, platform=%s",
                 self._binary, self._platform)

        # Kill any stale autoapp processes from previous runs
        self._kill_stale()

        env = os.environ.copy()

        if self._platform == "opi":
            # On OPi: set display to HDMI-2
            env["DISPLAY"] = ":0"
            env["SDL_VIDEODRIVER"] = "kmsdrm"
            log.info("OPi display config: DISPLAY=:0, SDL_VIDEODRIVER=kmsdrm")
        else:
            # On x86 headless: use offscreen Qt platform
            if not env.get("DISPLAY"):
                env["QT_QPA_PLATFORM"] = "offscreen"
                log.info("x86 headless: QT_QPA_PLATFORM=offscreen")
            else:
                log.info("x86 with display: DISPLAY=%s", env.get("DISPLAY"))

        # Ensure XDG_RUNTIME_DIR is set with correct permissions (0700)
        if "XDG_RUNTIME_DIR" not in env:
            runtime_dir = "/tmp/runtime-root"
            env["XDG_RUNTIME_DIR"] = runtime_dir
            os.makedirs(runtime_dir, exist_ok=True)
            os.chmod(runtime_dir, 0o700)
            log.debug("Set XDG_RUNTIME_DIR=%s (mode 0700)", runtime_dir)

        # Connect to PipeWire-pulse if running under different user
        if "PULSE_SERVER" not in env:
            # Try common PipeWire-pulse socket paths
            for uid in [1000, os.getuid()]:
                sock = f"/run/user/{uid}/pulse/native"
                if os.path.exists(sock):
                    env["PULSE_SERVER"] = f"unix:{sock}"
                    log.info("PulseAudio socket: %s", sock)
                    break
            else:
                log.warning("No PulseAudio socket found — audio may not work")

        try:
            self._process = subprocess.Popen(
                [self._binary],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            self._running = True

            # Start log reader thread
            self._log_thread = threading.Thread(
                target=self._read_logs, daemon=True
            )
            self._log_thread.start()

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
        """Stop OpenAuto."""
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

    def _kill_stale(self) -> None:
        """Kill any stale autoapp processes from previous runs."""
        try:
            result = subprocess.run(
                ["pgrep", "-f", "autoapp"],
                capture_output=True, text=True, timeout=3,
            )
            if result.returncode == 0 and result.stdout.strip():
                pids = result.stdout.strip().split()
                for pid in pids:
                    try:
                        pid_int = int(pid)
                        os.kill(pid_int, signal.SIGTERM)
                        log.info("Killed stale autoapp process (PID %d)", pid_int)
                    except (ValueError, ProcessLookupError):
                        pass
                time.sleep(1)  # Wait for port release
        except Exception:
            pass

    def _read_logs(self) -> None:
        """Forward autoapp stdout/stderr to our logger."""
        if not self._process or not self._process.stdout:
            return
        try:
            for line in self._process.stdout:
                if not self._running:
                    break
                text = line.decode("utf-8", errors="replace").rstrip()
                if text:
                    # Detect AA connection events from autoapp logs
                    if "Device Connected" in text:
                        self._event_bus.publish("multimedia.openauto_status",
                                                "connected")
                        log.info("[AA] Device connected: %s", text)
                    elif "SocketInfoRequest" in text and "Sent" in text:
                        log.info("[AA] Wireless handshake: %s", text)
                    elif "btservice" in text.lower():
                        log.info("[AA-BT] %s", text)
                    elif "error" in text.lower() or "fail" in text.lower():
                        log.warning("[autoapp] %s", text)
                    elif "wifi" in text.lower() or "wlan" in text.lower():
                        log.info("[AA-WiFi] %s", text)
                    elif "connect" in text.lower() or "disconnect" in text.lower():
                        log.info("[AA] %s", text)
                    elif "socket" in text.lower() or "tcp" in text.lower():
                        log.info("[AA-Net] %s", text)
                    elif "usb" in text.lower():
                        log.info("[AA-USB] %s", text)
                    else:
                        log.debug("[autoapp] %s", text)
        except Exception:
            log.exception("Error reading autoapp logs")

    def _watchdog(self) -> None:
        """Monitor OpenAuto process and restart on crash."""
        _restart_count = 0
        _max_restarts = 3
        while self._running:
            if self._process and self._process.poll() is not None:
                exit_code = self._process.returncode
                _restart_count += 1
                self._process = None

                if _restart_count > _max_restarts:
                    log.error("OpenAuto crashed %d times — giving up. "
                              "Check port 5000 and BT service conflicts.",
                              _restart_count)
                    self._event_bus.publish("multimedia.openauto_status",
                                            "error")
                    self._running = False
                    return

                # Exponential backoff: 3s, 6s, 12s
                delay = 3 * (2 ** (_restart_count - 1))
                log.warning("OpenAuto exited (code %d) — restart %d/%d in %ds",
                            exit_code, _restart_count, _max_restarts, delay)
                self._event_bus.publish("multimedia.openauto_status",
                                        "restarting")

                time.sleep(delay)
                if self._running:
                    self.start()
                return

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
    log.info("=== Multimedia module starting ===")

    # Reuse existing BluetoothManager if provided (avoids double D-Bus agent)
    if bt_manager is not None:
        bt_mgr = bt_manager
        log.info("Using shared BluetoothManager (available=%s, connected=%s)",
                 bt_mgr.available, bt_mgr.connected)
    else:
        log.info("Creating new BluetoothManager")
        bt_mgr = BluetoothManager(config, event_bus)
        bt_mgr.start_monitor()
        log.info("BluetoothManager created (available=%s)", bt_mgr.available)

    # OpenAuto controller
    openauto = OpenAutoController(config, event_bus)

    # Auto-launch OpenAuto if configured
    auto_start = config.get("multimedia.auto_start_openauto", True)
    log.info("OpenAuto auto_start=%s, available=%s", auto_start, openauto.available)
    if auto_start:
        if openauto.available:
            openauto.start()
        else:
            log.warning("OpenAuto auto_start enabled but binary not found")

    # Auto-connect to last BT device if configured
    last_device = config.get("multimedia.last_bt_device", None)
    if last_device and bt_mgr.available:
        log.info("Auto-connecting to last BT device: %s", last_device)
        bt_mgr.connect(last_device)
    elif last_device:
        log.info("Last BT device configured (%s) but BT not available", last_device)

    # Check WiFi AP status for wireless AA
    wifi_enabled = config.get("wifi.enabled", False)
    if not wifi_enabled:
        log.warning("WiFi AP is DISABLED in config — wireless Android Auto "
                     "will NOT work. Set wifi.enabled=true in bcm_config.yaml")

    log.info("=== Multimedia module running (openauto=%s, bt=%s, wifi=%s) ===",
             "active" if openauto.running else "unavailable",
             "active" if bt_mgr.available else "simulated",
             "enabled" if wifi_enabled else "DISABLED")

    event_bus.publish("multimedia._internals", {
        "openauto": openauto,
        "bluetooth": bt_mgr,
    })
