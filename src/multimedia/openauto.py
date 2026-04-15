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


def _aa_canvas_size(app_config: Any) -> tuple[int, int]:
    """Return the (width, height) that AA / Xvfb should use.

    BCM renders a 48 px AppBar at the top and a 48 px NavBar at the
    bottom of every A-screen, so the actual content area available to
    the Android Auto iframe is ``(dashboard.width, dashboard.height -
    48 - 48)``.  If ``display.multimedia.{width,height}`` is explicitly
    set in the config we honour it verbatim; otherwise we compute the
    inner-frame size so the AA canvas never gets clipped behind the
    header or the nav bar.
    """
    dash_w = int(app_config.get("display.dashboard.width", 1024))
    dash_h = int(app_config.get("display.dashboard.height", 600))
    appbar = int(app_config.get("display.appbar_px", 48))
    navbar = int(app_config.get("display.navbar_px", 48))
    inner_h = max(240, dash_h - appbar - navbar)
    w = int(app_config.get("display.multimedia.width", dash_w))
    h = int(app_config.get("display.multimedia.height", inner_h))
    return w, h


def _create_openauto_config(project_dir: str, app_config: Any = None) -> None:
    """Create openauto.ini in the project directory (autoapp's working dir).

    Only creates the file if it doesn't exist — autoapp manages its own
    config at runtime (stores last BT device, settings, etc.).
    """
    config_path = os.path.join(project_dir, "openauto.ini")
    # Regenerate if missing or outdated (version marker check).
    # V4 bumped so older config files with the hardcoded 800x480
    # touchscreen dimensions get regenerated with the correct values.
    VERSION_MARKER = "; BCM_CONFIG_V4"
    if os.path.exists(config_path):
        try:
            with open(config_path) as f:
                if VERSION_MARKER in f.read():
                    return  # Already up to date
        except Exception:
            pass

    ssid = ""
    password = ""
    width = 1024
    height = 504  # 600 - AppBar 48 - NavBar 48
    if app_config:
        ssid = app_config.get("wifi.ssid", "")
        password = app_config.get("wifi.password", "")
        width, height = _aa_canvas_size(app_config)

    # OpenAuto Resolution codes (per autoapp source):
    #   0 = 480p, 1 = 720p, 2 = 1080p, 3 = auto/stretch
    # Pick the closest match so the AA canvas actually fills the panel.
    if height >= 1080:
        resolution_code = 2
    elif height >= 720:
        resolution_code = 1
    else:
        resolution_code = 0

    config_content = f"""; BCM_CONFIG_V4 — OpenAuto configuration for Alfa156 Headunit
[General]
HandednessOfTrafficType=0

[Video]
FPS=1
Resolution={resolution_code}
ScreenDPI=140
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
TouchscreenWidth={width}
TouchscreenHeight={height}

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

    XVFB_DISPLAY = ":99"

    def __init__(self, config: Any, event_bus: EventBus):
        self._config = config
        self._event_bus = event_bus
        self._platform = config.get("system.platform", "x86")
        self._binary = _find_openauto()
        self._process: Optional[subprocess.Popen] = None
        self._xvfb_process: Optional[subprocess.Popen] = None
        self._wm_process: Optional[subprocess.Popen] = None
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
            # On a real OPi the framebuffer usually doesn't have a WM
            # either (bcm-kiosk runs Chromium directly via Xorg). Start
            # a matchbox-window-manager on :0 so the autoapp window is
            # forced fullscreen, same trick as the x86 Xvfb path.
            self._start_window_manager(":0")
        else:
            # On x86: render to Xvfb virtual display for browser streaming
            if not env.get("DISPLAY"):
                xvfb_display = self._start_xvfb()
                if xvfb_display:
                    env["DISPLAY"] = xvfb_display
                    # Force Qt to use xcb platform with Xvfb (not offscreen)
                    env["QT_QPA_PLATFORM"] = "xcb"
                    log.info("x86: rendering to Xvfb %s (Qt xcb)", xvfb_display)
                else:
                    env["QT_QPA_PLATFORM"] = "offscreen"
                    log.warning("x86: Xvfb failed, falling back to offscreen "
                                "(AA video will NOT work)")
            else:
                log.info("x86 with display: DISPLAY=%s", env.get("DISPLAY"))

        # Connect to PipeWire-pulse if running under different user.
        # Set PULSE_SERVER so autoapp can reach PipeWire-pulse socket.
        # XDG_RUNTIME_DIR must point to our own process (root) runtime dir
        # to avoid Qt warnings, but PULSE_SERVER can reference another user.
        if "PULSE_SERVER" not in env:
            for uid in [1000, os.getuid()]:
                sock = f"/run/user/{uid}/pulse/native"
                if os.path.exists(sock):
                    env["PULSE_SERVER"] = f"unix:{sock}"
                    env["PIPEWIRE_RUNTIME_DIR"] = f"/run/user/{uid}"
                    log.info("Audio: PULSE_SERVER=%s", sock)
                    break
            else:
                log.warning("No PulseAudio socket found — audio may not work")

        # Ensure XDG_RUNTIME_DIR is set for the running process's own UID
        if "XDG_RUNTIME_DIR" not in env:
            my_uid = os.getuid()
            runtime_dir = f"/run/user/{my_uid}"
            if not os.path.isdir(runtime_dir):
                runtime_dir = "/tmp/runtime-root"
                os.makedirs(runtime_dir, exist_ok=True)
                os.chmod(runtime_dir, 0o700)
            env["XDG_RUNTIME_DIR"] = runtime_dir
            log.debug("Set XDG_RUNTIME_DIR=%s", runtime_dir)

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

            # Kick off a one-shot window-resizer thread — without a window
            # manager inside Xvfb the Qt window comes up at its own default
            # size (typically 800x480) and leaves black space on the right,
            # which also makes touch coordinate mapping wrong because the
            # browser's relative clicks end up outside the autoapp window.
            threading.Thread(
                target=self._force_fullscreen_window,
                args=(env.get("DISPLAY", self.XVFB_DISPLAY),),
                daemon=True,
                name="aa-window-resizer",
            ).start()

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
        self._stop_xvfb()
        self._event_bus.publish("multimedia.openauto_status", "stopped")
        self._event_bus.publish("audio.source_available", {
            "source": "android_auto", "available": False,
        })

    def _force_fullscreen_window(self, display: str) -> None:
        """Force the autoapp Qt window to cover the full Xvfb canvas.

        Without a window manager inside Xvfb, Qt opens windows at their
        native default size (usually 800x480 for openauto/autoapp). That
        leaves black space on the right of the captured MJPEG stream and,
        more importantly, breaks touch coordinate mapping — browser clicks
        get translated to the full 1024x600 canvas but the AA window
        itself only occupies a sub-region.

        This helper polls xdotool until the autoapp window appears, then
        issues windowmove + windowsize so it fills the canvas from (0,0).
        Also calls windowactivate so the window is focused, and loops a
        few times in case the window gets re-created after a phone
        reconnect.
        """
        width, height = _aa_canvas_size(self._config)
        env = {**os.environ, "DISPLAY": display}
        candidates = ["autoapp", "OpenAuto", "openauto", "openDsh"]
        last_wid: Optional[str] = None
        deadline = time.time() + 30.0     # 30 s bootstrap window

        def _find_window_id() -> Optional[str]:
            for name in candidates:
                try:
                    r = subprocess.run(
                        ["xdotool", "search", "--name", name],
                        capture_output=True, text=True, timeout=2, env=env,
                    )
                    lines = [l for l in r.stdout.splitlines() if l.strip()]
                    if lines:
                        return lines[-1]
                except Exception:
                    continue
            # Fallback: any top-level X window.
            try:
                r = subprocess.run(
                    ["xdotool", "search", "--onlyvisible", "--class", ".*"],
                    capture_output=True, text=True, timeout=2, env=env,
                )
                lines = [l for l in r.stdout.splitlines() if l.strip()]
                if lines:
                    return lines[-1]
            except Exception:
                pass
            return None

        while self._running and time.time() < deadline:
            wid = _find_window_id()
            if wid and wid != last_wid:
                try:
                    subprocess.run(
                        ["xdotool",
                         "windowmove", wid, "0", "0",
                         "windowsize", wid, str(width), str(height),
                         "windowactivate", wid],
                        timeout=2, env=env, capture_output=True,
                    )
                    log.info("Resized autoapp window %s to %dx%d",
                             wid, width, height)
                    last_wid = wid
                    deadline = time.time() + 10.0  # keep monitoring briefly
                except Exception as e:
                    log.debug("windowsize failed: %s", e)
            time.sleep(0.5)

    def _start_window_manager(self, display: str) -> None:
        """Launch a minimal WM inside Xvfb so every window auto-maximises.

        Tries candidates in order of preference:
          1. matchbox-window-manager — tiny, kiosk-friendly, always-fullscreen
          2. openbox — slightly heavier but widely available
          3. twm — ancient fallback, ships with X.org

        Each candidate is launched non-blocking; if none are available
        the worker falls back to the xdotool windowsize trick in
        _force_fullscreen_window(). Logs a warning but never raises.
        """
        if self._wm_process and self._wm_process.poll() is None:
            return

        env = {**os.environ, "DISPLAY": display}
        candidates = [
            ["matchbox-window-manager", "-use_titlebar", "no",
             "-use_cursor", "no"],
            ["openbox"],
            ["twm"],
        ]
        for cmd in candidates:
            try:
                self._wm_process = subprocess.Popen(
                    cmd, env=env,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                time.sleep(0.3)
                if self._wm_process.poll() is None:
                    log.info("Window manager running inside %s: %s",
                             display, cmd[0])
                    return
            except FileNotFoundError:
                continue
            except Exception as e:
                log.debug("WM candidate %s failed: %s", cmd[0], e)
                continue

        log.warning(
            "No window manager found inside Xvfb — install "
            "`matchbox-window-manager` (apt) for best results. Falling "
            "back to xdotool windowsize which is less reliable."
        )
        self._wm_process = None

    def _stop_window_manager(self) -> None:
        if self._wm_process and self._wm_process.poll() is None:
            self._wm_process.terminate()
            try:
                self._wm_process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._wm_process.kill()
            self._wm_process = None

    def _start_xvfb(self) -> Optional[str]:
        """Start Xvfb virtual framebuffer for AA rendering."""
        if self._xvfb_process and self._xvfb_process.poll() is None:
            return self.XVFB_DISPLAY

        display_num = self.XVFB_DISPLAY  # e.g. ":99"

        # Clean up stale Xvfb on this display (previous crash / unclean shutdown)
        self._cleanup_stale_xvfb(display_num)

        try:
            width, height = _aa_canvas_size(self._config)
            self._xvfb_process = subprocess.Popen(
                ["Xvfb", display_num, "-screen", "0",
                 f"{width}x{height}x24", "-ac"],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            )
            time.sleep(0.5)
            if self._xvfb_process.poll() is not None:
                stderr = ""
                try:
                    stderr = self._xvfb_process.stderr.read().decode(
                        errors="replace")[:200]
                except Exception:
                    pass
                log.error("Xvfb exited immediately: %s", stderr)
                return None
            log.info("Xvfb started on %s (%dx%d)", display_num, width, height)

            # Launch a minimal window manager inside Xvfb so that every
            # top-level window created by openauto/autoapp is forced to
            # maximize to the full canvas. Without a WM, Qt apps open at
            # their internal default size (typically 800x480) leaving a
            # black strip on the right and breaking touch coordinate
            # mapping.
            self._start_window_manager(display_num)

            return display_num
        except FileNotFoundError:
            log.warning("Xvfb not installed")
            return None
        except Exception as e:
            log.error("Xvfb start failed: %s", e)
            return None

    @staticmethod
    def _cleanup_stale_xvfb(display: str) -> None:
        """Kill stale Xvfb process and remove lock file for given display."""
        num = display.lstrip(":")
        lock_file = f"/tmp/.X{num}-lock"
        try:
            if os.path.exists(lock_file):
                with open(lock_file) as f:
                    old_pid = int(f.read().strip())
                # Check if that PID is still an Xvfb process
                try:
                    cmdline_path = f"/proc/{old_pid}/cmdline"
                    if os.path.exists(cmdline_path):
                        with open(cmdline_path, "rb") as cf:
                            cmdline = cf.read().decode(errors="replace")
                        if "Xvfb" in cmdline:
                            os.kill(old_pid, signal.SIGTERM)
                            time.sleep(0.5)
                            # Force kill if still alive
                            try:
                                os.kill(old_pid, signal.SIGKILL)
                            except ProcessLookupError:
                                pass
                            log.info("Killed stale Xvfb (PID %d) on %s",
                                     old_pid, display)
                except (ProcessLookupError, PermissionError):
                    pass
                # Remove lock and socket files
                for path in [lock_file, f"/tmp/.X11-unix/X{num}"]:
                    try:
                        os.remove(path)
                    except FileNotFoundError:
                        pass
        except Exception as e:
            log.debug("Xvfb stale cleanup: %s", e)

    def _stop_xvfb(self) -> None:
        """Stop Xvfb and any window manager we launched inside it."""
        self._stop_window_manager()
        if self._xvfb_process and self._xvfb_process.poll() is None:
            self._xvfb_process.terminate()
            try:
                self._xvfb_process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._xvfb_process.kill()
            log.info("Xvfb stopped")
        self._xvfb_process = None

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
        """Monitor OpenAuto process and restart on crash.

        Uses exponential backoff (3s→6s→12s) and stops after max restarts.
        Publishes detailed status to event bus so the web UI can show the state.
        """
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
                                            "failed")
                    self._event_bus.publish("multimedia.openauto_error",
                                            f"Crashed {_restart_count} times "
                                            f"(last exit code: {exit_code})")
                    self._running = False
                    return

                # Exponential backoff: 3s, 6s, 12s
                delay = min(60, 3 * (2 ** (_restart_count - 1)))
                log.warning("OpenAuto exited (code %d) — restart %d/%d in %ds",
                            exit_code, _restart_count, _max_restarts, delay)
                self._event_bus.publish("multimedia.openauto_status",
                                        "restarting")

                # Clean up Xvfb between restarts to prevent stale display
                self._stop_xvfb()
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
