#!/usr/bin/env python3
"""BCM v8.5 — Alfa Romeo 156 Head Unit — Entry Point.

Usage:
    python main.py                              # auto-detect platform, start all enabled modules
    python main.py --platform x86               # force x86 platform
    python main.py --platform x86 --headless    # x86 without X display (dashboard via WebViewer)
    python main.py --platform x86 --dry-run     # list modules without starting them
    python main.py --platform x86 --modules obd,dashboard
    python main.py --config config/bcm_config_test.yaml --local-config /tmp/l.yaml
    python main.py --config config/bcm_config_test.yaml --no-local-config

Configuration = base YAML (--config, never written) + local overlay
(--local-config, default config/local.yaml next to the base; runtime changes
from the UI are saved there) + secrets from the environment
(/etc/bcm/bcm.env via systemd, or <repo>/.env for development).
"""

import argparse
import os
import signal
import time
from pathlib import Path
from typing import Optional

from src.core.config import (
    SECRET_ENV_MAP,
    BCMConfig,
    count_leaves,
    default_local_path,
    resolve_base_path,
)
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

# Module registry — built from the shared catalog (src/core/modules_catalog),
# which is also what the Settings → Modules screen lists via /api/modules.
# NOTE: "dashboard" is handled separately because start_dashboard() blocks
# (PyGame main-thread event loop). All other modules must start first.
from src.core import modules_catalog

MODULE_REGISTRY: dict[str, dict] = {
    name: {
        "part": info["part"],
        "description": info["description"],
        "start": _lazy(*info["entry"]),
    }
    for name, info in modules_catalog.MODULES.items()
    if "entry" in info
}

# Dashboard is listed for --dry-run reporting but started separately
DASHBOARD_INFO = {"part": 2, "description": "BCM Dashboard Renderer (web frontend / Pygame)", "start": start_dashboard}


def plan_modules(config, cli_modules: Optional[list[str]] = None) -> dict:
    """What starts: ``modules.*`` toggles (or ``--modules``) after the
    dependency check of the catalog. Returns ``{name: ModuleStatus}`` for
    every catalog entry; ``.runs`` is the only thing the start path looks at.

    A module that is on but whose ``requires``/``requires_any`` are not
    running (or that has no code in this version) gets ``runs == False`` —
    main() logs ONE warning for it (:func:`modules_catalog.block_message`)
    and never calls its entry point. ``--modules`` decides the registry
    modules and the dashboard on its own; subsystems keep their toggles.
    """
    overrides = None
    if cli_modules is not None:
        wanted = set(cli_modules)
        overrides = {name: name in wanted for name in ["dashboard", *MODULE_REGISTRY]}
    return modules_catalog.module_states(config, overrides)


def registry_to_start(module_states) -> list:
    """``[(name, MODULE_REGISTRY entry)]`` of the registry modules that run
    (toggle on, dependencies running), in registry order. A module that is
    off or blocked is not in the list, so its entry point is never imported
    or called."""
    return [(name, info) for name, info in MODULE_REGISTRY.items()
            if getattr(module_states.get(name), "runs", False)]


def report_blocked_modules(module_states, log) -> int:
    """ONE warning per module that is switched on but will not start
    (missing dependency, or no code for it in this version) — registry
    modules and subsystems alike, so the log says why instead of staying
    silent. Returns how many were reported. The whole map goes along, so a
    dependency that is on but blocked itself is named as such, with the
    toggle that actually has to be switched on (``root_blockers``)."""
    count = 0
    for st in module_states.values():
        message = modules_catalog.block_message(st, states=module_states)
        if message:
            log.warning(message)
            count += 1
    return count


def start_modules(started_modules, config, event_bus, hal, bt_manager=None) -> None:
    """Start the registry modules main() selected (non-blocking ones; the
    dashboard comes last). One failing module never stops the others."""
    log = get_logger("main")
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="BCM v8.5 — Alfa Romeo 156 Head Unit",
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
        help="Path to the base config YAML (default: config/bcm_config.yaml). "
             "BCM never writes this file.",
    )
    parser.add_argument(
        "--local-config",
        default=None,
        metavar="PATH",
        help="Local overlay with runtime changes (default: $BCM_LOCAL_CONFIG, "
             "else local.yaml next to the base config)",
    )
    parser.add_argument(
        "--no-local-config",
        action="store_true",
        help="Do not load or write a local overlay (UI changes last until restart)",
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


REPO_ROOT = Path(__file__).resolve().parent


def resolve_local_config(args: argparse.Namespace, base_path: Path) -> Optional[Path]:
    """Where the local overlay lives (None = disabled).

    Precedence: --no-local-config > --local-config > $BCM_LOCAL_CONFIG >
    local.yaml next to the base config.
    """
    if args.no_local_config:
        return None
    if args.local_config:
        return Path(args.local_config)
    env_path = os.environ.get("BCM_LOCAL_CONFIG", "").strip()
    if env_path:
        return Path(env_path)
    return default_local_path(base_path)


def main() -> None:
    args = parse_args()

    # Headless mode: set SDL dummy drivers before anything imports PyGame
    if args.headless:
        os.environ["SDL_VIDEODRIVER"] = "dummy"
        os.environ["SDL_AUDIODRIVER"] = "dummy"

    # Load configuration: base YAML + local overlay + secrets from env
    platform_override = args.platform if args.platform != "auto" else None
    base_path = resolve_base_path(args.config, platform_override)
    local_path = resolve_local_config(args, base_path)
    config = BCMConfig(config_path=args.config, platform_override=platform_override,
                       local_path=local_path, env=os.environ,
                       dotenv_path=REPO_ROOT / ".env")
    # The secrets now live in the config object. Drop them from our own
    # environment so autoapp, nmcli & co. (spawned with os.environ) do not
    # inherit API keys they have no use for.
    for var in SECRET_ENV_MAP.values():
        os.environ.pop(var, None)

    # Initialize logging. Per-module levels come from system.module_levels
    # (logger name relative to "bcm" → level); empty by default.
    log_level = config.get("system.log_level", "INFO")
    log_file = config.get("system.log_file")
    module_levels = config.get("system.module_levels") or {}
    if not isinstance(module_levels, dict):
        module_levels = {}
    setup_logging(level=log_level, log_file=log_file,
                  module_levels=module_levels,
                  max_mb=config.get("system.log_max_mb", 5),
                  backups=config.get("system.log_backups", 3))
    log = get_logger("main")

    log.info("=" * 60)
    log.info("BCM v8.5 — Alfa Romeo 156 Head Unit")
    log.info("Version: %s", config.get("system.version", "unknown"))
    log.info("Platform: %s", config.platform)
    log.info("Config: %s", config.config_path)
    if config.local_path is not None:
        log.info("Local overlay: %s (%s, %d overridden value(s))",
                 config.local_path,
                 "present" if config.local_path.exists() else "absent",
                 count_leaves(config.overlay()))
    else:
        log.info("Local overlay: disabled — UI changes will not survive a restart")
    if config.secret_sources:
        # Names only — never the values.
        log.info("Secrets from environment: %s",
                 ", ".join(sorted(config.secret_sources.values())))
    if module_levels:
        log.info("Module log levels: %s",
                 ", ".join(f"{k}={v}" for k, v in sorted(module_levels.items(), key=str)))
    for warning in config.load_warnings:
        log.warning("Config: %s", warning)
    log.info("=" * 60)

    # Initialize core components. async_dispatch: subscriber callbacks
    # run on a dispatcher thread, so a blocking subscriber cannot stall
    # the sensor thread that published the event.
    event_bus = EventBus(async_dispatch=True)
    hal = HAL(platform=config.platform)

    log.info("Core initialized: EventBus, HAL (%s)", config.platform)

    # Determine which modules to load (modules.* toggles via the catalog,
    # then the dependency check: a module whose dependency is off does not
    # start — see plan_modules()).
    cli_modules = [m.strip() for m in args.modules.split(",")] if args.modules else None
    module_states = plan_modules(config, cli_modules)

    def _runs(name: str) -> bool:
        st = module_states.get(name)
        return bool(st and st.runs)

    if cli_modules is not None:
        requested = cli_modules
    else:
        requested = [name for name in ["dashboard", *MODULE_REGISTRY]
                     if module_states[name].enabled]

    # Report module status
    log.info("--- Module Status ---")

    # Report dashboard first
    dashboard_enabled = _runs("dashboard")
    dash_status = "ENABLED" if dashboard_enabled else "disabled"
    log.info("  %-14s [Part %2d] %s — %s", "dashboard", 2, dash_status,
             DASHBOARD_INFO["description"])

    for name, info in MODULE_REGISTRY.items():
        st = module_states[name]
        if st.runs:
            status = "ENABLED"
        elif st.enabled:
            status = "NOT STARTED (%s)" % st.reason
        else:
            status = "disabled"
        log.info("  %-14s [Part %2d] %s — %s", name, info["part"], status, info["description"])
    started_modules = registry_to_start(module_states)
    report_blocked_modules(module_states, log)

    if args.dry_run:
        log.info("--- Dry run complete. %d modules would load (%d implemented). ---",
                 len(requested), len(started_modules) + (1 if dashboard_enabled else 0))
        return

    # Create BluetoothManager early so it can be shared with AA display.
    # bluetooth.enabled=false skips the whole probe (saves ~10 s on
    # hardware without a BT adapter — the probe retries 5x with 2 s
    # sleeps before giving up).
    bt_manager = None
    bt_enabled = _runs("bluetooth")
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
    if _runs("fuel_sender"):
        try:
            from src.vehicle.fuel_sender import FuelSender
            # instance stays alive via its event-bus subscriptions
            FuelSender(config, event_bus)
            log.info("FuelSender initialized")
        except Exception:
            log.exception("FuelSender failed to init (non-critical)")
    # PBAP phonebook + call-history puller. Subscribes to bt.connected and
    # publishes bt.contacts / bt.call_history that the A8 phone screen
    # consumes via /api/phone/{contacts,history}. Without this the phone
    # screen renders empty even when pairing advertises PCE/MCE correctly.
    # Pointless without Bluetooth, so by default it follows the bluetooth
    # toggle (modules.phonebook overrides) and requires it (catalog).
    if _runs("phonebook"):
        try:
            from src.multimedia.phonebook import start_phonebook_sync
            start_phonebook_sync(event_bus, config)
        except Exception:
            log.exception("PBAP phonebook sync failed to init (non-critical)")

    # Phone battery / signal / operator for the top bar (bt.phone_status,
    # read from oFono/BlueZ over a private D-Bus connection). Off unless
    # modules.phone_status is set (test config); requires bluetooth (catalog).
    if _runs("phone_status"):
        try:
            from src.multimedia.phone_status import start_phone_status
            start_phone_status(config, event_bus)
        except Exception:
            log.exception("Phone status monitor failed to init (non-critical)")

    # Start WiFi AP for Android Auto wireless data link
    wifi_ap = None
    wifi_enabled = _runs("wifi_ap")
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
    start_modules(started_modules, config, event_bus, hal, bt_manager)

    # Set up shutdown handler
    shutdown = False
    dashboard_renderer = None

    def signal_handler(signum, frame):
        nonlocal shutdown
        log.info("Received signal %d, shutting down...", signum)
        shutdown = True
        # Tell every module we are going down.
        #
        # Several of them already subscribe to this (openauto stops autoapp,
        # audio kills the EQ filter-chain and hands the sink back), but until
        # now the only publisher was PowerManager — so with modules.power off
        # the topic never fired and those cleanups never ran. Orphaned autoapp
        # and `pipewire -c` processes came from exactly this.
        event_bus.publish("power.shutting_down", True)
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
                _rp = None
                if _runs("route_planner"):
                    try:
                        from src.trip.route_planner import RoutePlanner
                        _rp = RoutePlanner(config, event_bus)
                    except Exception as _e:
                        log.warning("RoutePlanner unavailable: %s", _e)
                _tc = TripComputer(event_bus=event_bus, route_planner=_rp)
                web_viewer = WebViewer(
                    host="0.0.0.0", port=5002,
                    event_bus=event_bus, config=config,
                    bt_manager=bt_manager,
                    trip_computer=_tc,
                    route_planner=_rp,
                    wifi_ap=wifi_ap,
                    # What THIS process started (incl. --modules), the
                    # baseline of "wymaga restartu BCM" in Settings → Moduły.
                    boot_module_runs={n: st.runs for n, st in module_states.items()},
                )
                web_viewer.start()
                log.info("Main display started at http://localhost:5002")

                # Start small display server (4.3" stats carousel)
                if _runs("small_display"):
                    from src.dashboard.small_viewer import SmallDisplayServer
                    small_display = SmallDisplayServer(
                        host="0.0.0.0", port=5003,
                        event_bus=event_bus, config=config,
                    )
                    small_display.start()
                    log.info("Small display started at http://localhost:5003")
                else:
                    log.info("Small display disabled (modules.small_display)")

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
