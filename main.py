#!/usr/bin/env python3
"""BCM v7 — Alfa Romeo 156 Head Unit — Entry Point.

Usage:
    python main.py                              # auto-detect platform, start all enabled modules
    python main.py --platform x86               # force x86 platform
    python main.py --platform x86 --headless    # x86 without X display (dashboard via WebViewer)
    python main.py --platform x86 --dry-run     # list modules without starting them
    python main.py --platform x86 --modules obd,dashboard
"""

import argparse
import os
import signal
import sys
import time

from src.core.config import BCMConfig
from src.core.logger import setup_logging, get_logger
from src.core.event_bus import EventBus
from src.core.hal import HAL
from src.dashboard.renderer import start_dashboard
from src.obd.simulator import start_obd
from src.parking.simulator import start_parking
from src.environment.simulator import start_environment
from src.audio.volume import start_audio
from src.voice.recognizer import start_voice
from src.input.bt_remote import start_input
from src.camera.reverse_cam import start_camera
from src.power.shutdown import start_power
from src.multimedia.openauto import start_multimedia


# Module registry — maps module names to their (future) start functions.
# Each Part will register its module here when implemented.
# NOTE: "dashboard" is handled separately because start_dashboard() blocks
# (PyGame main-thread event loop). All other modules must start first.
MODULE_REGISTRY: dict[str, dict] = {
    "obd":         {"part": 3, "description": "OBD-II / K-Line Communication", "start": start_obd},
    "parking":     {"part": 4, "description": "Parking Sensors System", "start": start_parking},
    "environment": {"part": 5, "description": "Temperature & Environment Monitoring", "start": start_environment},
    "audio":       {"part": 6, "description": "Audio System & PipeWire", "start": start_audio},
    "voice":       {"part": 7, "description": "Voice Control (Vosk)", "start": start_voice},
    "input":       {"part": 8, "description": "Input Controllers", "start": start_input},
    "camera":      {"part": 9, "description": "Camera & Dashcam", "start": start_camera},
    "power":       {"part": 10, "description": "Power Management", "start": start_power},
    "multimedia":  {"part": 11, "description": "Android Auto / Multimedia", "start": start_multimedia},
}

# Dashboard is listed for --dry-run reporting but started separately
DASHBOARD_INFO = {"part": 2, "description": "BCM Dashboard Renderer (4.3\" screen)", "start": start_dashboard}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="BCM v7 — Alfa Romeo 156 Head Unit",
    )
    parser.add_argument(
        "--platform",
        choices=["x86", "opi", "auto"],
        default="auto",
        help="Target platform (default: auto-detect)",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to config YAML (default: config/bcm_config.yaml)",
    )
    parser.add_argument(
        "--modules",
        default=None,
        help="Comma-separated list of modules to load (default: all enabled in config)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List modules and exit without starting them",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run PyGame with dummy video/audio drivers (no X display needed)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # Headless mode: set SDL dummy drivers before anything imports PyGame
    if args.headless:
        os.environ["SDL_VIDEODRIVER"] = "dummy"
        os.environ["SDL_AUDIODRIVER"] = "dummy"

    # Load configuration
    platform_override = args.platform if args.platform != "auto" else None
    config = BCMConfig(config_path=args.config, platform_override=platform_override)

    # Initialize logging
    log_level = config.get("system.log_level", "INFO")
    log_file = config.get("system.log_file")
    root_log = setup_logging(level=log_level, log_file=log_file)
    log = get_logger("main")

    log.info("=" * 60)
    log.info("BCM v7 — Alfa Romeo 156 Head Unit")
    log.info("Version: %s", config.get("system.version", "unknown"))
    log.info("Platform: %s", config.platform)
    log.info("Config: %s", config.config_path)
    log.info("=" * 60)

    # Initialize core components
    event_bus = EventBus()
    hal = HAL(platform=config.platform)

    log.info("Core initialized: EventBus, HAL (%s)", config.platform)

    # Determine which modules to load
    if args.modules:
        requested = [m.strip() for m in args.modules.split(",")]
    else:
        requested = ["dashboard"] + [
            name for name in MODULE_REGISTRY
            if config.is_module_enabled(name)
        ]

    # Report module status
    log.info("--- Module Status ---")

    # Report dashboard first
    dashboard_enabled = "dashboard" in requested
    dash_status = "ENABLED" if dashboard_enabled else "disabled"
    log.info("  %-14s [Part %2d] %s — %s", "dashboard", 2, dash_status,
             DASHBOARD_INFO["description"])

    started_modules = []
    for name, info in MODULE_REGISTRY.items():
        enabled = name in requested
        has_impl = "start" in info
        status = "ENABLED" if enabled else "disabled"

        if enabled and not has_impl:
            status = "ENABLED (not yet implemented — Part %d)" % info["part"]

        log.info("  %-14s [Part %2d] %s — %s", name, info["part"], status, info["description"])

        if enabled and has_impl:
            started_modules.append((name, info))

    if args.dry_run:
        log.info("--- Dry run complete. %d modules would load (%d implemented). ---",
                 len(requested), len(started_modules) + (1 if dashboard_enabled else 0))
        return

    # Create BluetoothManager early so it can be shared with AA display
    bt_manager = None
    try:
        from src.multimedia.bluetooth import BluetoothManager
        bt_manager = BluetoothManager(config, event_bus)
        bt_manager.start_monitor()
        log.info("BluetoothManager initialized")
    except Exception:
        log.exception("BluetoothManager failed to init (non-critical)")

    # Start Android Auto display + BT management web UI on x86
    aa_display = None
    if config.platform == "x86":
        try:
            from src.multimedia.aa_display import start_aa_display
            aa_display = start_aa_display(config, event_bus, bt_manager=bt_manager)
            log.info("AA display + BT management web UI started (http://localhost:5001)")
        except Exception:
            log.exception("AA display failed to start")

    # Start non-blocking modules first
    for name, info in started_modules:
        log.info("Starting module: %s", name)
        try:
            info["start"](config=config, event_bus=event_bus, hal=hal)
            log.info("Module started: %s", name)
        except Exception:
            log.exception("Failed to start module: %s", name)

    # Set up shutdown handler
    shutdown = False
    dashboard_renderer = None

    def signal_handler(signum, frame):
        nonlocal shutdown
        log.info("Received signal %d, shutting down...", signum)
        shutdown = True
        # Stop the dashboard renderer if it's blocking the main thread
        if dashboard_renderer is not None:
            dashboard_renderer.stop()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start dashboard LAST — it blocks the main thread with PyGame event loop.
    # All other modules (BT, AA display, etc.) are already running in their
    # daemon threads by this point.
    if dashboard_enabled:
        log.info("Starting dashboard (main thread — blocking)...")
        try:
            # Create renderer before starting so signal handler can stop it
            from src.dashboard.renderer import DashboardRenderer, DemoDataGenerator
            dashboard_renderer = DashboardRenderer(config, event_bus)
            demo = None
            if config.platform == "x86":
                demo = DemoDataGenerator(event_bus)
                demo.start()
            try:
                dashboard_renderer.run()
            finally:
                if demo:
                    demo.stop()
        except Exception:
            log.exception("Dashboard failed")
    else:
        if started_modules:
            log.info("BCM v7 running (no dashboard). Press Ctrl+C to stop.")
            while not shutdown:
                time.sleep(0.5)
            log.info("BCM v7 shutdown complete.")
        else:
            log.info("No implemented modules to start. Core infrastructure is ready.")


if __name__ == "__main__":
    main()
