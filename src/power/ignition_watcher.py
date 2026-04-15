#!/usr/bin/env python3
"""Ignition Watcher — systemd service that monitors the ignition GPIO.

Runs at boot as a lightweight daemon. When the ignition signal arrives
(12V via PC817 optoisolator → GPIO LOW), it starts the main BCM headunit
service. When ignition goes OFF, it triggers graceful BCM shutdown.

This mimics real in-car behavior: the OPi PC is always powered (standby),
but the BCM application only runs while the ignition key is turned.

Supports two input modes:
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
POLL_INTERVAL_S = 0.1


# ── Config loader ──────────────────────────────────────────────────────────

def load_config(config_path: str) -> dict:
    """Load ignition watcher settings from BCM config YAML."""
    defaults = {
        "gpio_chip": DEFAULT_CHIP,
        "ignition_line": DEFAULT_IGNITION_LINE,
        "bench_button_line": DEFAULT_BENCH_BUTTON_LINE,
        "debounce_ms": DEFAULT_DEBOUNCE_MS,
        "active_low": DEFAULT_ACTIVE_LOW,
    }
    path = Path(config_path)
    if not path.exists() or yaml is None:
        return defaults

    with open(path) as f:
        data = yaml.safe_load(f) or {}

    iw = data.get("power", {}).get("ignition_watcher", {})
    for key in defaults:
        if key in iw:
            defaults[key] = iw[key]
    return defaults


# ── Systemd helpers ────────────────────────────────────────────────────────

def systemctl(action: str, service: str) -> bool:
    """Run systemctl action on a service. Returns True on success."""
    try:
        result = subprocess.run(
            ["systemctl", action, service],
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

    # Select watcher implementation
    if args.simulate or not HAS_GPIOD:
        if not HAS_GPIOD:
            log("gpiod not available — falling back to simulation mode")
        watcher = SimulatedIgnitionWatcher()
    else:
        watcher = GPIOIgnitionWatcher(cfg)

    watcher.setup()

    # State tracking
    bcm_running = False
    ignition_on = False
    shutdown_requested = False

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

    try:
        while not shutdown_requested:
            # Read ignition line
            ign_state = watcher.read_ignition()

            # Read bench button (toggle on press)
            btn_pressed = watcher.read_bench_button()
            if btn_pressed and not btn_was_pressed:
                # Rising edge of button press — toggle ignition
                ignition_on = not ignition_on
                log(f"Bench button pressed — ignition {'ON' if ignition_on else 'OFF'}")
            elif ign_state != ignition_on and not btn_pressed:
                # Ignition line changed (and button not overriding)
                ignition_on = ign_state
                log(f"Ignition signal changed — {'ON' if ignition_on else 'OFF'}")
            btn_was_pressed = btn_pressed

            # Act on state changes
            if ignition_on and not bcm_running:
                log("=== IGNITION ON — Starting BCM headunit ===")
                if systemctl("start", service):
                    bcm_running = True
                    log("BCM headunit service started successfully")
                else:
                    log("WARNING: Failed to start BCM headunit service")

            elif not ignition_on and bcm_running:
                log("=== IGNITION OFF — Stopping BCM headunit ===")
                if systemctl("stop", service):
                    bcm_running = False
                    log("BCM headunit service stopped")
                else:
                    log("WARNING: Failed to stop BCM headunit service")

            time.sleep(POLL_INTERVAL_S)

    finally:
        # Ensure BCM is stopped on exit
        if bcm_running:
            log("Watcher exiting — stopping BCM headunit...")
            systemctl("stop", service)
        watcher.close()
        log("Ignition watcher stopped.")


if __name__ == "__main__":
    main()
