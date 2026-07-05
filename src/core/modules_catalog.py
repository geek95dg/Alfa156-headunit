"""Single source of truth for every switchable BCM module/subsystem.

Used by main.py (module startup) and by the Settings → Modules screen
(/api/modules in web_viewer) so the UI always lists exactly what the
runtime knows about.

Two kinds of entries:
  - registry modules: have an ``entry`` (module path, start function) and
    are started generically by main.py,
  - subsystems: started explicitly in main.py (Bluetooth, WiFi AP,
    phonebook, ...) but still toggled with the same ``modules.<name>``
    convention.

Toggle resolution (``is_enabled``): ``modules.<name>`` wins; if absent,
the legacy ad-hoc key (``bluetooth.enabled``, ``wifi.enabled``,
``fuel_sender.enabled``, ``modules_v85.*``) is honoured; else the
catalog default applies.
"""

from typing import Optional

# name -> {part, description, entry?, legacy_key?, default}
MODULES: dict[str, dict] = {
    # --- dashboard (started specially — blocks the main thread) ---
    "dashboard":   {"part": 2,  "description": "BCM Dashboard Renderer (web frontend / Pygame)",
                    "default": True},

    # --- registry modules (generic start via entry) ---
    "obd":         {"part": 3,  "description": "OBD-II / K-Line Communication",
                    "entry": ("src.obd.simulator", "start_obd"), "default": False},
    "parking":     {"part": 4,  "description": "Parking Sensors System",
                    "entry": ("src.parking.simulator", "start_parking"), "default": False},
    "environment": {"part": 5,  "description": "Temperature & Environment Monitoring",
                    "entry": ("src.environment.simulator", "start_environment"), "default": False},
    "audio":       {"part": 6,  "description": "Audio System & PipeWire",
                    "entry": ("src.audio.volume", "start_audio"), "default": False},
    "input":       {"part": 8,  "description": "Input Controllers",
                    "entry": ("src.input.bt_remote", "start_input"), "default": False},
    "camera":      {"part": 9,  "description": "Camera & Dashcam",
                    "entry": ("src.camera.reverse_cam", "start_camera"), "default": False},
    "power":       {"part": 10, "description": "Power Management",
                    "entry": ("src.power.shutdown", "start_power"), "default": False},
    "multimedia":  {"part": 11, "description": "Android Auto / Multimedia",
                    "entry": ("src.multimedia.openauto", "start_multimedia"), "default": False},
    "location":    {"part": 12, "description": "GPS/GNSS Positioning",
                    "entry": ("src.location.gps", "start_location"), "default": False},
    "tracking":    {"part": 12, "description": "GPS Route Logger (SQLite + GPX)",
                    "entry": ("src.location.tracker", "start_tracker"), "default": False},
    "network":     {"part": 13, "description": "LTE/Cellular Connectivity",
                    "entry": ("src.network.lte", "start_network"), "default": False},
    "weather":     {"part": 14, "description": "Weather Data (OpenWeatherMap)",
                    "entry": ("src.weather.weather", "start_weather"), "default": False},
    "rain_sensor": {"part": 15, "description": "Rain Sensor + Auto Wipers",
                    "entry": ("src.vehicle.rain_sensor", "start_rain_sensor"), "default": False},
    "blinker_monitor": {"part": 15, "description": "Turn Signal GPIO Monitor",
                    "entry": ("src.vehicle.blinker_monitor", "start_blinker_monitor"), "default": False},
    "central_lock": {"part": 16, "description": "Always-on Nano bridge (window remote + BLE trunk + backlight PWM)",
                    "entry": ("src.vehicle.central_lock", "start_central_lock"), "default": False},
    "lighting":    {"part": 17, "description": "Lighting (Follow-me-home, Greeting)",
                    "entry": ("src.vehicle.lighting", "start_lighting"), "default": False},
    "performance": {"part": 18, "description": "Performance (0-100 Timer, Boost)",
                    "entry": ("src.performance.timer", "start_performance"), "default": False},
    "alarm":       {"part": 19, "description": "Car Alarm (PIR, Tilt, Shock, Siren)",
                    "entry": ("src.vehicle.alarm", "start_alarm"), "default": False},
    "crash_detect": {"part": 20, "description": "Crash Detection + DVR Protection",
                    "entry": ("src.camera.crash_detect", "start_crash_detect"), "default": False},
    "battery":     {"part": 21, "description": "Battery Backup Monitor",
                    "entry": ("src.power.battery", "start_battery"), "default": False},

    # --- subsystems started explicitly in main.py ---
    "bluetooth":    {"part": 11, "description": "Bluetooth (BlueZ) — pairing, A2DP/HFP, media",
                     "legacy_key": "bluetooth.enabled", "default": True},
    "phonebook":    {"part": 11, "description": "PBAP phonebook + call history sync (A8 phone screen)",
                     "default": True},
    "fuel_sender":  {"part": 21, "description": "Fuel tank sender calibration (Arduino ADC → %)",
                     "legacy_key": "fuel_sender.enabled", "default": True},
    "wifi_ap":      {"part": 11, "description": "WiFi dla Android Auto wireless (Wi-Fi Direct / P2P-GO, karta wewnętrzna)",
                     "legacy_key": "wifi.enabled", "default": False},
    "wifi_hotspot": {"part": 11, "description": "Dodatkowy Access Point ALFA-NET (współdzielenie internetu — wymaga osobnego dongla WiFi)",
                     "legacy_key": "wifi.alfa_net.enabled", "default": False},
    "route_planner": {"part": 12, "description": "Travel plan (OpenRouteService/TomTom routing)",
                     "default": True},
    "small_display": {"part": 2,  "description": "4.3\" stats display server (port 5003)",
                     "default": True},
}


def is_enabled(config, name: str) -> Optional[bool]:
    """Effective on/off state of a module/subsystem for the given config."""
    info = MODULES.get(name)
    if info is None:
        return None
    val = config.get(f"modules.{name}")
    if val is not None:
        return bool(val)
    legacy = info.get("legacy_key")
    if legacy is not None:
        val = config.get(legacy)
        if val is not None:
            return bool(val)
    if "entry" in info or name == "dashboard":
        # registry modules also honour the pre-v8.5.2 modules_v85 block
        if config.is_module_enabled(name):
            return True
    # phonebook without its own key follows bluetooth
    if name == "phonebook":
        bt = is_enabled(config, "bluetooth")
        if bt is not None:
            return bt
    return bool(info.get("default", False))


def catalog_state(config) -> list[dict]:
    """Full module list with effective state — payload for /api/modules."""
    out = []
    for name, info in MODULES.items():
        out.append({
            "name": name,
            "part": info["part"],
            "description": info["description"],
            "enabled": is_enabled(config, name),
            "kind": "module" if "entry" in info or name == "dashboard" else "subsystem",
        })
    return out
