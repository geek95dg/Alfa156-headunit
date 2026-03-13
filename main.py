#!/usr/bin/env python3
"""BCM v7 — Alfa Romeo 156 Head Unit — Entry Point.

Usage:
    python main.py                              # auto-detect platform, start all enabled modules
    python main.py --platform x86               # force x86 platform
    python main.py --platform x86 --dry-run     # list modules without starting them
    python main.py --platform x86 --modules obd,dashboard
"""

import argparse
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


# Module registry — maps module names to their (future) start functions.
# Each Part will register its module here when implemented.
MODULE_REGISTRY: dict[str, dict] = {
    "dashboard":   {"part": 2, "description": "BCM Dashboard Renderer (4.3\" screen)", "start": start_dashboard},
    "obd":         {"part": 3, "description": "OBD-II / K-Line Communication", "start": start_obd},
    "parking":     {"part": 4, "description": "Parking Sensors System", "start": start_parking},
    "environment": {"part": 5, "description": "Temperature & Environment Monitoring", "start": start_environment},
    "audio":       {"part": 6, "description": "Audio System & PipeWire"},
    "voice":       {"part": 7, "description": "Voice Control (Vosk)"},
    "input":       {"part": 8, "description": "Input Controllers"},
    "camera":      {"part": 9, "description": "Camera & Dashcam"},
    "power":       {"part": 10, "description": "Power Management"},
    "multimedia":  {"part": 11, "description": "Android Auto / Multimedia"},
}


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
    return parser.parse_args()


def main() -> None:
    args = parse_args()

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
        requested = [
            name for name in MODULE_REGISTRY
            if config.is_module_enabled(name)
        ]

    # Report module status
    log.info("--- Module Status ---")
    started_modules = []
    for name, info in MODULE_REGISTRY.items():
        enabled = name in requested
        has_impl = "start" in info  # Will be True once each Part adds its start function
        status = "ENABLED" if enabled else "disabled"

        if enabled and not has_impl:
            status = "ENABLED (not yet implemented — Part %d)" % info["part"]

        log.info("  %-14s [Part %2d] %s — %s", name, info["part"], status, info["description"])

        if enabled and has_impl:
            started_modules.append((name, info))

    if args.dry_run:
        log.info("--- Dry run complete. %d modules would load (%d implemented). ---",
                 len(requested), len(started_modules))
        return

    # Start implemented modules
    for name, info in started_modules:
        log.info("Starting module: %s", name)
        try:
            info["start"](config=config, event_bus=event_bus, hal=hal)
            log.info("Module started: %s", name)
        except Exception:
            log.exception("Failed to start module: %s", name)

    if not started_modules:
        log.info("No implemented modules to start. Core infrastructure is ready.")
        log.info("Implement Part 2+ to add functional modules.")

    # Main loop (waits for shutdown signal)
    shutdown = False

    def signal_handler(signum, frame):
        nonlocal shutdown
        log.info("Received signal %d, shutting down...", signum)
        shutdown = True

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    if not args.dry_run and started_modules:
        log.info("BCM v7 running. Press Ctrl+C to stop.")
        while not shutdown:
            time.sleep(0.5)
        log.info("BCM v7 shutdown complete.")
    else:
        log.info("BCM v7 core ready. No active modules running.")


if __name__ == "__main__":
    main()
