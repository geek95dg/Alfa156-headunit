#!/usr/bin/env python3
"""Ignition Watcher — systemd service that monitors the ignition GPIO.

Runs at boot as a lightweight daemon. When the ignition signal arrives
(12V via PC817 optoisolator → GPIO LOW), it starts the main BCM headunit
service. When ignition goes OFF, it triggers graceful BCM shutdown.

The OPi stays powered via a small backup battery. The OS never shuts
down — it idles without BCM (deep idle) until the next wake signal.
After 12 hours without a fresh boot, the next wake replays the boot
splash (cold-like wake) and resets the 12h window.

Wake signals:
  - Ignition ON (GPIO / bench button / sim file)
  - SWC MODE button press (Arduino evdev KEY_F10)

Supports two GPIO input modes:
  1. Optoisolator input (production/car): 12V ignition → PC817 → GPIO
     Active-low: GPIO reads LOW when 12V is present (PC817 pulls down)
  2. Bench button (test rig): momentary push button on a GPIO pin
     Active-low with internal pull-up: press = LOW

Usage:
    # As systemd service (primary):
    python -m src.power.ignition_watcher

    # Manual testing:
    python -m src.power.ignition_watcher --simulate
    python -m src.power.ignition_watcher --config config/bcm_config_opi_pc.yaml
"""

import argparse
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

# Attempt to import gpiod — fall back to simulation if not available
try:
    import gpiod  # type: ignore
    from gpiod.line import Direction, Bias, Edge  # type: ignore
    HAS_GPIOD = True
except ImportError:
    HAS_GPIOD = False

# Minimal YAML loader for config
try:
    import yaml
except ImportError:
    yaml = None  # type: ignore


# ── Defaults ────────────────────────────────────────────────────────────────

DEFAULT_CONFIG = "config/bcm_config_opi_pc.yaml"
DEFAULT_CHIP = "gpiochip0"

# OPi PC (Allwinner H3) 40-pin header safe defaults — the old draft
# of this module had DEFAULT_BENCH_BUTTON_LINE=37 but line 37 is PB5
# on the H3, which is NOT exposed on the 40-pin header at all. BCM
# never could have claimed that line on real hardware. Pick two
# libgpiod lines that are actually on the header and marked "unused"
# by `gpioinfo gpiochip0` on a stock Armbian Trixie image:
#   ignition_line     = 7    → PA7,  physical pin 29
#   bench_button_line = 203  → PG11, physical pin 38
DEFAULT_IGNITION_LINE = 7
DEFAULT_BENCH_BUTTON_LINE = 203
DEFAULT_DEBOUNCE_MS = 200
DEFAULT_ACTIVE_LOW = True
BCM_SERVICE_NAME = "bcm-headunit.service"
SPLASH_SERVICE_NAME = "bcm-splash-main.service"
POLL_INTERVAL_S = 0.1
STATE_FILE = Path("/tmp/bcm_power_state")
DEFAULT_STANDBY_MAX_HOURS = 12
DEFAULT_SPLASH_DURATION_S = 15


# ── Config loader ──────────────────────────────────────────────────────────

def load_config(config_path: str) -> dict:
    """Load ignition watcher settings from BCM config YAML."""
    defaults = {
        "gpio_chip": DEFAULT_CHIP,
        "ignition_line": DEFAULT_IGNITION_LINE,
        "bench_button_line": DEFAULT_BENCH_BUTTON_LINE,
        "debounce_ms": DEFAULT_DEBOUNCE_MS,
        "active_low": DEFAULT_ACTIVE_LOW,
        "standby_max_hours": DEFAULT_STANDBY_MAX_HOURS,
        "splash_duration_seconds": DEFAULT_SPLASH_DURATION_S,
        "suspend_on_stop": False,
        "suspend_delay_seconds": 5,
    }
    path = Path(config_path)
    if not path.exists() or yaml is None:
        return defaults

    with open(path) as f:
        data = yaml.safe_load(f) or {}

    power = data.get("power", {})
    iw = power.get("ignition_watcher", {})
    for key in ("gpio_chip", "ignition_line", "bench_button_line",
                "debounce_ms", "active_low"):
        if key in iw:
            defaults[key] = iw[key]

    if "standby_max_hours" in power:
        defaults["standby_max_hours"] = power["standby_max_hours"]
    if "splash_duration_seconds" in power:
        defaults["splash_duration_seconds"] = power["splash_duration_seconds"]

    return defaults


# ── Systemd helpers ────────────────────────────────────────────────────────

def systemctl(action: str, service: str) -> bool:
    """Run systemctl action on a service. Returns True on success."""
    try:
        cmd = ["systemctl", action] + ([service] if service else [])
        result = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            log(f"systemctl {action} {service} — OK")
            return True
        else:
            log(f"systemctl {action} {service} — FAILED: {result.stderr.strip()}")
            return False
    except Exception as e:
        log(f"systemctl {action} {service} — ERROR: {e}")
        return False


def is_service_active(service: str) -> bool:
    """Check if a systemd service is currently active."""
    try:
        result = subprocess.run(
            ["systemctl", "is-active", service],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() == "active"
    except Exception:
        return False


# ── Logging ────────────────────────────────────────────────────────────────

def log(msg: str) -> None:
    """Print timestamped log message to stdout (captured by journald)."""
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] ignition-watcher: {msg}", flush=True)


# ── GPIO watcher (real hardware) ───────────────────────────────────────────

class GPIOIgnitionWatcher:
    """Watches ignition GPIO line using libgpiod."""

    def __init__(self, cfg: dict):
        self._chip_name = cfg["gpio_chip"]
        self._ign_line = cfg["ignition_line"]
        self._btn_line = cfg["bench_button_line"]
        self._debounce_us = cfg["debounce_ms"] * 1000
        self._active_low = cfg["active_low"]
        self._chip: Optional[gpiod.Chip] = None
        self._request = None

    def setup(self) -> None:
        """Open GPIO chip and request ignition + bench button lines."""
        self._chip = gpiod.Chip(self._chip_name)
        log(f"Opened GPIO chip: {self._chip_name}")

        # Configure both lines as inputs with pull-up and edge detection
        ign_settings = gpiod.LineSettings(
            direction=Direction.INPUT,
            bias=Bias.PULL_UP,
            debounce_period=__import__("datetime").timedelta(
                microseconds=self._debounce_us),
        )
        btn_settings = gpiod.LineSettings(
            direction=Direction.INPUT,
            bias=Bias.PULL_UP,
            debounce_period=__import__("datetime").timedelta(
                microseconds=self._debounce_us),
        )

        line_config = {
            self._ign_line: ign_settings,
            self._btn_line: btn_settings,
        }

        self._request = self._chip.request_lines(
            consumer="bcm-ignition-watcher",
            config=line_config,
        )
        log(f"Watching: ignition=line {self._ign_line}, "
            f"button=line {self._btn_line}")

    def read_ignition(self) -> bool:
        """Read current ignition state. Returns True if ignition is ON."""
        val = self._request.get_value(self._ign_line)
        if self._active_low:
            return val == gpiod.line.Value.INACTIVE  # LOW = active
        return val == gpiod.line.Value.ACTIVE

    def read_bench_button(self) -> bool:
        """Read bench button state. Returns True if pressed."""
        val = self._request.get_value(self._btn_line)
        # Button is active-low (pressed = LOW)
        return val == gpiod.line.Value.INACTIVE

    def close(self) -> None:
        if self._request:
            self._request.release()
        if self._chip:
            self._chip.close()


# ── Simulation watcher (for testing without GPIO) ──────────────────────────

class SimulatedIgnitionWatcher:
    """Simulates ignition via keyboard input or file-based trigger."""

    def __init__(self):
        self._state = False
        self._trigger_file = Path("/tmp/bcm_ignition_on")

    def setup(self) -> None:
        log("SIMULATION MODE — ignition watcher")
        log(f"  Create file {self._trigger_file} to simulate ignition ON")
        log(f"  Remove file {self._trigger_file} to simulate ignition OFF")

    def read_ignition(self) -> bool:
        return self._trigger_file.exists()

    def read_bench_button(self) -> bool:
        return False

    def close(self) -> None:
        pass


# ── State file ────────────────────────────────────────────────────────────

def write_state(boot_mode: str, first_boot_ts: float) -> None:
    """Write power state file atomically for the frontend to read."""
    tmp = STATE_FILE.with_suffix(".tmp")
    try:
        tmp.write_text(
            f"first_boot_ts={first_boot_ts}\n"
            f"boot_mode={boot_mode}\n"
        )
        tmp.rename(STATE_FILE)
    except OSError as e:
        log(f"WARNING: Failed to write state file: {e}")


# ── 12-hour standby timer ────────────────────────────────────────────────

class StandbyTimer:
    """Background timer that sets past_12h flag after the standby window."""

    def __init__(self, standby_max_s: float):
        self._standby_max_s = standby_max_s
        self._first_boot_ts = time.time()
        self._past_12h = False
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @property
    def first_boot_ts(self) -> float:
        with self._lock:
            return self._first_boot_ts

    @property
    def past_12h(self) -> bool:
        with self._lock:
            return self._past_12h

    def reset(self) -> None:
        """Reset the 12h window (called on cold-like wake)."""
        with self._lock:
            self._first_boot_ts = time.time()
            self._past_12h = False
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        self._stop_event.clear()
        self._start_thread()

    def start(self) -> None:
        self._start_thread()

    def stop(self) -> None:
        self._stop_event.set()

    def _start_thread(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        with self._lock:
            deadline = self._first_boot_ts + self._standby_max_s
        remaining = deadline - time.time()
        if remaining > 0:
            self._stop_event.wait(timeout=remaining)
        if not self._stop_event.is_set():
            with self._lock:
                self._past_12h = True
            log(f"12h standby window expired — next wake will be cold-like")


# ── SWC evdev monitor ────────────────────────────────────────────────────

try:
    import evdev  # type: ignore
    HAS_EVDEV = True
except ImportError:
    HAS_EVDEV = False

KEY_F10 = 68


class EvdevWakeMonitor:
    """Monitors the Arduino's evdev device for SWC MODE (KEY_F10)."""

    DEVICE_PATTERNS = ("arduino", "pro micro", "leonardo", "atmega32u4")
    RESCAN_INTERVAL_S = 30

    def __init__(self):
        self._device = None
        self._last_scan = 0.0

    def check_f10(self) -> bool:
        """Non-blocking check for KEY_F10 press. Returns True once per press."""
        if not HAS_EVDEV:
            return False

        now = time.time()
        if self._device is None:
            if now - self._last_scan < self.RESCAN_INTERVAL_S:
                return False
            self._find_device()
            self._last_scan = now
            if self._device is None:
                return False

        import select as _select
        try:
            r, _, _ = _select.select([self._device.fd], [], [], 0)
            if not r:
                return False
            for event in self._device.read():
                if (event.type == evdev.ecodes.EV_KEY
                        and event.code == KEY_F10
                        and event.value == 1):
                    return True
        except OSError:
            log("Arduino evdev device disconnected — will rescan")
            self._device = None
        return False

    def close(self) -> None:
        if self._device:
            try:
                self._device.close()
            except Exception:
                pass

    def _find_device(self) -> None:
        try:
            for path in evdev.list_devices():
                dev = evdev.InputDevice(path)
                name = dev.name.lower()
                if any(p in name for p in self.DEVICE_PATTERNS):
                    log(f"Found Arduino evdev device: {dev.name} ({path})")
                    self._device = dev
                    return
                dev.close()
        except Exception as e:
            log(f"evdev scan error: {e}")


class SimulatedSwcMonitor:
    """Simulates SWC F10 via /tmp/bcm_swc_toggle file."""

    TRIGGER = Path("/tmp/bcm_swc_toggle")

    def check_f10(self) -> bool:
        if self.TRIGGER.exists():
            try:
                self.TRIGGER.unlink()
            except OSError:
                pass
            return True
        return False

    def close(self) -> None:
        pass


# ── Main loop ──────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="BCM Ignition Watcher — starts headunit on ignition signal",
    )
    parser.add_argument(
        "--config", default=DEFAULT_CONFIG,
        help=f"Path to BCM config YAML (default: {DEFAULT_CONFIG})",
    )
    parser.add_argument(
        "--simulate", action="store_true",
        help="Run in simulation mode (no GPIO, use /tmp/bcm_ignition_on file)",
    )
    parser.add_argument(
        "--service", default=BCM_SERVICE_NAME,
        help=f"Systemd service to start/stop (default: {BCM_SERVICE_NAME})",
    )
    args = parser.parse_args()

    cfg = load_config(args.config)
    service = args.service
    standby_max_s = cfg["standby_max_hours"] * 3600
    splash_duration = cfg["splash_duration_seconds"]
    simulate = args.simulate or not HAS_GPIOD

    # Select watcher implementation
    if simulate:
        if not HAS_GPIOD:
            log("gpiod not available — falling back to simulation mode")
        watcher = SimulatedIgnitionWatcher()
    else:
        watcher = GPIOIgnitionWatcher(cfg)

    try:
        watcher.setup()
    except (FileNotFoundError, PermissionError, OSError) as exc:
        if not simulate:
            log(f"GPIO setup failed: {exc}")
            log("Falling back to simulation mode — "
                "check that /dev/gpiochip0 exists (ls /dev/gpiochip*)")
            simulate = True
            watcher = SimulatedIgnitionWatcher()
            watcher.setup()
        else:
            raise

    # Select SWC monitor
    if simulate:
        swc_monitor = SimulatedSwcMonitor()
        log(f"  SWC sim: touch /tmp/bcm_swc_toggle to toggle BCM")
    elif HAS_EVDEV:
        swc_monitor = EvdevWakeMonitor()
    else:
        swc_monitor = SimulatedSwcMonitor()
        log("evdev not available — SWC monitor uses file trigger")

    # State tracking
    bcm_running = False
    ignition_on = False
    bcm_started_once = False
    user_standby = False
    shutdown_requested = False

    # 12h standby timer
    timer = StandbyTimer(standby_max_s)
    timer.start()
    log(f"  Standby window: {cfg['standby_max_hours']}h")
    log(f"  Splash duration: {splash_duration}s")

    def handle_signal(signum, frame):
        nonlocal shutdown_requested
        log(f"Received signal {signum}, shutting down...")
        shutdown_requested = True

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    log("Ignition watcher started — waiting for ignition signal...")
    log(f"  Target service: {service}")
    log(f"  Active-low: {cfg['active_low']}")

    # Track bench button state for toggle behavior
    btn_was_pressed = False
    prev_ignition_on = False

    def start_bcm() -> bool:
        """Determine boot mode, write state, optionally start splash, start BCM."""
        nonlocal bcm_started_once

        # Determine boot mode
        if not bcm_started_once:
            boot_mode = "cold"
        elif timer.past_12h:
            boot_mode = "cold"
            timer.reset()
            log("12h window reset — cold-like wake")
        else:
            boot_mode = "warm"

        write_state(boot_mode, timer.first_boot_ts)
        log(f"Boot mode: {boot_mode}")

        # Cold-like wake from deep idle: replay splash
        if boot_mode == "cold" and bcm_started_once:
            log(f"Starting splash for cold-like wake ({splash_duration}s)...")
            systemctl("start", SPLASH_SERVICE_NAME)
            time.sleep(splash_duration)

        bcm_started_once = True

        if systemctl("start", service):
            log("BCM headunit service started successfully")
            return True
        else:
            log("WARNING: Failed to start BCM headunit service")
            return False

    suspend_on_stop = cfg.get("suspend_on_stop", False)
    suspend_delay = cfg.get("suspend_delay_seconds", 5)

    def stop_bcm(do_suspend: bool = False) -> bool:
        """Stop BCM headunit. Optionally suspend to S3 after."""
        if systemctl("stop", service):
            log("BCM headunit service stopped — OS stays in deep idle")
            if do_suspend and suspend_on_stop:
                log(f"Suspending to S3 in {suspend_delay}s...")
                time.sleep(suspend_delay)
                if not ignition_on:
                    systemctl("suspend", "")
                    log("System suspended (S3)")
                else:
                    log("Ignition came back during delay — skip suspend")
            return True
        else:
            log("WARNING: Failed to stop BCM headunit service")
            return False

    try:
        while not shutdown_requested:
            # Read ignition line
            ign_state = watcher.read_ignition()

            # Read bench button (toggle on press)
            btn_pressed = watcher.read_bench_button()
            if btn_pressed and not btn_was_pressed:
                ignition_on = not ignition_on
                log(f"Bench button pressed — ignition "
                    f"{'ON' if ignition_on else 'OFF'}")
            elif ign_state != ignition_on and not btn_pressed:
                ignition_on = ign_state
                log(f"Ignition signal changed — "
                    f"{'ON' if ignition_on else 'OFF'}")
            btn_was_pressed = btn_pressed

            # Edge detection: only act on transitions
            ign_rising = ignition_on and not prev_ignition_on
            ign_falling = not ignition_on and prev_ignition_on
            prev_ignition_on = ignition_on

            # Check SWC MODE button (F10)
            f10 = swc_monitor.check_f10()

            # --- SWC toggle ---
            if f10 and bcm_running:
                log("=== SWC MODE — Putting BCM in standby ===")
                if stop_bcm():
                    bcm_running = False
                    user_standby = True

            elif f10 and not bcm_running:
                log("=== SWC MODE — Waking BCM from standby ===")
                user_standby = False
                if start_bcm():
                    bcm_running = True

            # --- Ignition OFF clears user_standby ---
            if ign_falling and user_standby:
                user_standby = False

            # --- Ignition-driven start/stop (edge-triggered) ---
            if ign_rising and not bcm_running and not user_standby:
                log("=== IGNITION ON — Starting BCM headunit ===")
                if start_bcm():
                    bcm_running = True

            elif ign_falling and bcm_running:
                log("=== IGNITION OFF — Stopping BCM headunit ===")
                if stop_bcm(do_suspend=True):
                    bcm_running = False

            time.sleep(POLL_INTERVAL_S)

    finally:
        timer.stop()
        swc_monitor.close()
        if bcm_running:
            log("Watcher exiting — stopping BCM headunit...")
            systemctl("stop", service)
        watcher.close()
        log("Ignition watcher stopped.")


if __name__ == "__main__":
    main()
