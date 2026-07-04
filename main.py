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

# ALL module entry points are imported lazily: importing them eagerly
# pulled dbus/GLib/numpy/etc. into the boot path for modules that may
# be disabled in config (measured ~2.3 s just to import main.py).
# _lazy() defers the import to the moment the module actually starts,
# so a disabled module costs nothing.
def _lazy(module_path: str, func_name: str):
    def _starter(*args, **kwargs):
        import importlib
        mod = importlib.import_module(module_path)
        return getattr(mod, func_name)(*args, **kwargs)
    _starter.__name__ = func_name
    return _starter


start_dashboard = _lazy("src.dashboard.renderer", "start_dashboard")

# Module registry — maps module names to their start functions.
# NOTE: "dashboard" is handled separately because start_dashboard() blocks
# (PyGame main-thread event loop). All other modules must start first.
MODULE_REGISTRY: dict[str, dict] = {
    "obd":         {"part": 3, "description": "OBD-II / K-Line Communication", "start": _lazy("src.obd.simulator", "start_obd")},
    "parking":     {"part": 4, "description": "Parking Sensors System", "start": _lazy("src.parking.simulator", "start_parking")},
    "environment": {"part": 5, "description": "Temperature & Environment Monitoring", "start": _lazy("src.environment.simulator", "start_environment")},
    "audio":       {"part": 6, "description": "Audio System & PipeWire", "start": _lazy("src.audio.volume", "start_audio")},
    "input":       {"part": 8, "description": "Input Controllers", "start": _lazy("src.input.bt_remote", "start_input")},
    "camera":      {"part": 9, "description": "Camera & Dashcam", "start": _lazy("src.camera.reverse_cam", "start_camera")},
    "power":       {"part": 10, "description": "Power Management", "start": _lazy("src.power.shutdown", "start_power")},
    "multimedia":  {"part": 11, "description": "Android Auto / Multimedia", "start": _lazy("src.multimedia.openauto", "start_multimedia")},
    "location":    {"part": 12, "description": "GPS/GNSS Positioning", "start": _lazy("src.location.gps", "start_location")},
    "tracking":    {"part": 12, "description": "GPS Route Logger (SQLite + GPX)", "start": _lazy("src.location.tracker", "start_tracker")},
    "network":     {"part": 13, "description": "LTE/Cellular Connectivity", "start": _lazy("src.network.lte", "start_network")},
    "weather":     {"part": 14, "description": "Weather Data (OpenWeatherMap)", "start": _lazy("src.weather.weather", "start_weather")},
    "rain_sensor": {"part": 15, "description": "Rain Sensor + Auto Wipers", "start": _lazy("src.vehicle.rain_sensor", "start_rain_sensor")},
    "blinker_monitor": {"part": 15, "description": "Turn Signal GPIO Monitor", "start": _lazy("src.vehicle.blinker_monitor", "start_blinker_monitor")},
    "central_lock":{"part": 16, "description": "Always-on Nano bridge (window remote + BLE trunk + backlight PWM)", "start": _lazy("src.vehicle.central_lock", "start_central_lock")},
    "lighting":    {"part": 17, "description": "Lighting (Follow-me-home, Greeting)", "start": _lazy("src.vehicle.lighting", "start_lighting")},
    "performance": {"part": 18, "description": "Performance (0-100 Timer, Boost)", "start": _lazy("src.performance.timer", "start_performance")},
    "alarm":       {"part": 19, "description": "Car Alarm (PIR, Tilt, Shock, Siren)", "start": _lazy("src.vehicle.alarm", "start_alarm")},
    "crash_detect":{"part": 20, "description": "Crash Detection + DVR Protection", "start": _lazy("src.camera.crash_detect", "start_crash_detect")},
    "battery":     {"part": 21, "description": "Battery Backup Monitor", "start": _lazy("src.power.battery", "start_battery")},
}

# Dashboard is listed for --dry-run reporting but started separately
DASHBOARD_INFO = {"part": 2, "description": "BCM Dashboard Renderer (4.3\" screen)", "start": start_dashboard}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="BCM v7 — Alfa Romeo 156 Head Unit",
    )
    parser.add_argument(
        "--platform",
        choices=["x86", "opi", "opi_pc", "auto"],
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
    parser.add_argument(
        "--frontend",
        action="store_true",
        help="Use HTML5/Tailwind web frontend instead of Pygame renderer. "
             "Dashboard served at http://localhost:5002",
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
    # Keep BT/multimedia at DEBUG for investigation, rest at configured level
    module_levels = {
        "multimedia.bluetooth": "DEBUG",
        "multimedia.openauto": "DEBUG",
        "multimedia.wifi_ap": "DEBUG",
        "multimedia.aa_display": "INFO",
    }
    root_log = setup_logging(level=log_level, log_file=log_file,
                             module_levels=module_levels)
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

    # Create BluetoothManager early so it can be shared with AA display.
    # bluetooth.enabled=false skips the whole probe (saves ~10 s on
    # hardware without a BT adapter — the probe retries 5x with 2 s
    # sleeps before giving up).
    bt_manager = None
    bt_enabled = config.get("bluetooth.enabled", True)
    log.info("--- Bluetooth Init (enabled=%s) ---", bt_enabled)
    if bt_enabled:
        try:
            from src.multimedia.bluetooth import BluetoothManager
            bt_manager = BluetoothManager(config, event_bus)
            bt_manager.start_monitor()
            log.info("BluetoothManager initialized (available=%s)", bt_manager.available)
            if bt_manager.available:
                ctrl_info = bt_manager.get_controller_info()
                log.info("BT Controller: %s (%s), powered=%s, discoverable=%s",
                         ctrl_info.get("name", "?"), ctrl_info.get("address", "?"),
                         ctrl_info.get("powered", False),
                         ctrl_info.get("discoverable", False))
                paired = bt_manager.get_paired_devices()
                log.info("BT Paired devices: %d", len(paired))
                for dev in paired:
                    info = bt_manager.get_device_info(dev["address"])
                    log.info("  %s (%s) connected=%s",
                             dev["name"], dev["address"],
                             info.get("connected", False))
        except Exception:
            log.exception("BluetoothManager failed to init (non-critical)")

    # Fuel sender calibration (ADC from Arduino → fuel level percentage)
    fuel_sender = None
    if config.get("fuel_sender.enabled", True):
        try:
            from src.vehicle.fuel_sender import FuelSender
            fuel_sender = FuelSender(config, event_bus)
            log.info("FuelSender initialized")
        except Exception:
            log.exception("FuelSender failed to init (non-critical)")
    # PBAP phonebook + call-history puller. Subscribes to bt.connected and
    # publishes bt.contacts / bt.call_history that the A8 phone screen
    # consumes via /api/phone/{contacts,history}. Without this the phone
    # screen renders empty even when pairing advertises PCE/MCE correctly.
    # Pointless without Bluetooth, so it follows the bluetooth.enabled toggle.
    if bt_enabled:
        try:
            from src.multimedia.phonebook import start_phonebook_sync
            start_phonebook_sync(event_bus)
        except Exception:
            log.exception("PBAP phonebook sync failed to init (non-critical)")

    # Start WiFi AP for Android Auto wireless data link
    wifi_ap = None
    wifi_enabled = config.get("wifi.enabled", False)
    log.info("--- WiFi AP Init (enabled=%s) ---", wifi_enabled)
    if wifi_enabled:
        try:
            from src.multimedia.wifi_ap import WiFiAPManager
            wifi_ap = WiFiAPManager(config, event_bus)
            if wifi_ap.start():
                log.info("WiFi AP active — SSID: %s, IP: %s, Interface: %s",
                         config.get("wifi.ssid", "Alfa156_AA"),
                         wifi_ap.ip_address, wifi_ap.interface)
            else:
                log.warning("WiFi AP failed to start (AA wireless may not work)")
        except Exception:
            log.exception("WiFi AP init failed")
    else:
        log.warning("WiFi AP disabled — wireless Android Auto will not work. "
                     "Set wifi.enabled=true in config.")

    # NOTE: Port 5001 (aa_display.py) is no longer used.
    # AA MJPEG stream + BT management are now served directly from
    # the BCM dashboard on port 5002 (web_viewer.py).

    # Start non-blocking modules first
    for name, info in started_modules:
        log.info("Starting module: %s", name)
        try:
            # Pass existing bt_manager to multimedia to avoid double registration
            if name == "multimedia" and bt_manager is not None:
                info["start"](config=config, event_bus=event_bus, hal=hal,
                              bt_manager=bt_manager)
            else:
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
        # Stop WiFi AP
        if wifi_ap is not None:
            wifi_ap.stop()
        # Stop the dashboard renderer if it's blocking the main thread
        if dashboard_renderer is not None:
            dashboard_renderer.stop()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start dashboard LAST — it blocks the main thread.
    # In --frontend mode: start web server + demo data, block main thread.
    # In Pygame mode: start Pygame renderer which blocks main thread.
    if dashboard_enabled:
        demo = None
        demo_media = None
        if config.platform == "x86" and config.get("system.simulation", True):
            from src.dashboard.renderer import DemoDataGenerator
            from src.multimedia.bluetooth import DemoMediaGenerator
            demo = DemoDataGenerator(event_bus)
            demo.start()
            demo_media = DemoMediaGenerator(event_bus)
            demo_media.start()
            log.info("Demo data generators started (OBD + Media) "
                     "[platform=%s]", config.platform)

        if args.frontend:
            # HTML5/Tailwind frontend mode — no Pygame needed
            log.info("Starting HTML5/Tailwind dashboard frontend...")
            try:
                from src.dashboard.web_viewer import WebViewer
                from src.dashboard.trip_computer import TripComputer
                try:
                    from src.trip.route_planner import RoutePlanner
                    _rp = RoutePlanner(config, event_bus)
                except Exception as _e:
                    log.warning("RoutePlanner unavailable: %s", _e)
                    _rp = None
                _tc = TripComputer(event_bus=event_bus, route_planner=_rp)
                web_viewer = WebViewer(
                    host="0.0.0.0", port=5002,
                    event_bus=event_bus, config=config,
                    bt_manager=bt_manager,
                    trip_computer=_tc,
                    route_planner=_rp,
                    wifi_ap=wifi_ap,
                )
                web_viewer.start()
                log.info("Main display started at http://localhost:5002")

                # Start small display server (4.3" stats carousel)
                from src.dashboard.small_viewer import SmallDisplayServer
                small_display = SmallDisplayServer(
                    host="0.0.0.0", port=5003,
                    event_bus=event_bus, config=config,
                )
                small_display.start()
                log.info("Small display started at http://localhost:5003")

                log.info("  Themes: Heritage / Modern / Autodelta")
                log.info("  Main:  A1-A7 + Settings (7/8\" touch)")
                log.info("  Small: Stats carousel + reverse camera (4.3\")")
                log.info("BCM v8.5 running (frontend mode). Press Ctrl+C to stop.")
                while not shutdown:
                    time.sleep(0.5)
            except Exception:
                log.exception("Frontend dashboard failed")
            finally:
                if demo:
                    demo.stop()
                if demo_media:
                    demo_media.stop()
        else:
            # Legacy Pygame renderer mode
            log.info("Starting Pygame dashboard (main thread — blocking)...")
            try:
                from src.dashboard.renderer import DashboardRenderer
                dashboard_renderer = DashboardRenderer(config, event_bus)
                try:
                    dashboard_renderer.run()
                finally:
                    if demo:
                        demo.stop()
                    if demo_media:
                        demo_media.stop()
            except Exception:
                log.exception("Dashboard failed")
    else:
        if started_modules:
            log.info("BCM v8 running (no dashboard). Press Ctrl+C to stop.")
            while not shutdown:
                time.sleep(0.5)
            log.info("BCM v8 shutdown complete.")
        else:
            log.info("No implemented modules to start. Core infrastructure is ready.")


if __name__ == "__main__":
    main()
