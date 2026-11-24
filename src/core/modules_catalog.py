"""Single source of truth for every switchable BCM module/subsystem.

Used by main.py (module startup) and by the Settings → Modules screen
(/api/modules in web_viewer) so the UI always lists exactly what the
runtime knows about.

Three kinds of entries:
  - registry modules: have an ``entry`` (module path, start function) and
    are started generically by main.py,
  - subsystems: started explicitly in main.py (Bluetooth, WiFi AP,
    phonebook, ...) but still toggled with the same ``modules.<name>``
    convention,
  - planned modules (``planned: True``): the toggle exists so the UI can
    show it (and local.yaml can carry it), but this version has no code for
    it — it is listed as "niedostępny w tej wersji", cannot be switched on
    from the UI and never starts. Implementing one = adding ``entry`` (or a
    start path in main.py) and dropping ``planned``.

Toggle resolution (``is_enabled``): ``modules.<name>`` wins; if absent,
the legacy ad-hoc key (``bluetooth.enabled``, ``wifi.enabled``,
``fuel_sender.enabled``, ``modules_v85.*``) is honoured; else the
catalog default applies. Every module added for the car phone / safety
features (plan sections C–I) defaults to False here, so a config that does
not name it — production — behaves exactly as before.

Dependencies (optional keys of an entry):
  - ``requires``: names that must ALL be running,
  - ``requires_any``: groups of names; each group needs at least ONE running
    member (e.g. a light sensor from the car phone OR the Arduino),
  - ``hardware``: short Polish note shown in Settings (what has to be
    plugged in / installed for the module to do anything),
  - ``group``: heading the Settings screen lists the module under.

A module whose dependencies are not running is not started; main.py logs
ONE warning naming the missing dependency (:func:`block_message`) and, when
that dependency is switched on but blocked itself, the toggle that actually
has to be switched on (:func:`root_blockers`). The UI
warns before such a toggle is saved and offers to switch the dependencies
on too — explicitly, there is never a silent cascade. The graph logic is in
pure functions (:func:`resolve`, :func:`enable_plan`, :func:`find_cycles`)
so it is tested without a config file, and an unknown name or a cycle in the
catalog makes the affected module "not running" instead of a crash or a hang.
"""

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional

# name -> {part, description, entry?, legacy_key?, default, requires?,
#          requires_any?, hardware?, group?, planned?}
MODULES: dict[str, dict] = {
    # --- dashboard (started specially — blocks the main thread) ---
    "dashboard":   {"part": 2,  "description": "BCM Dashboard Renderer (web frontend / Pygame)",
                    "default": True},

    # --- registry modules (generic start via entry) ---
    "esp32_display": {"part": 2, "description": "Wyświetlacz pomocniczy 1,8\" na ESP32 (metadane + tempomat po USB)",
                    "entry": ("src.dashboard.esp32_link", "start_esp32_link"), "default": False},
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
    # Partia 12: refuels entered on A3 ("Zatankowano") → consumption from
    # full to full, cost, range (src/trip/fuel_log.py). Needs tracking: the
    # GPS distance between fills when no odometer reading was entered. Off
    # in code (default False); the car's config/bcm_config.yaml decides.
    "fuel_log":    {"part": 12, "description": "Dziennik tankowań: spalanie od pełna do pełna, koszt, zasięg",
                    "entry": ("src.trip.fuel_log", "start_fuel_log"), "default": False,
                    "requires": ("tracking",),
                    "hardware": "nic — litry (i opcjonalnie cena, licznik) wpisujesz na "
                                "ekranie trasy (A3) po tankowaniu"},
    "network":    {"part": 13, "description": "LTE/Cellular Connectivity",
                    "entry": ("src.network.lte", "start_network"), "default": False},
    # Off in code (default False; config/bcm_config.yaml decides); this
    # toggle is its only switch.
    # Needs bluetooth: it follows bt.connected from the BluetoothManager.
    "phone_tether": {"part": 13, "description": "Internet z telefonu (Bluetooth PAN przez NetworkManager)",
                    "entry": ("src.network.phone_tether", "start_phone_tether"), "default": False,
                    "requires": ("bluetooth",),
                    "hardware": "telefon z włączonym tetheringiem Bluetooth"},
    # Off in code (default False; config/bcm_config.yaml decides); this
    # toggle is its only switch.
    # Plan C + D1: the phone mounted in the car on USB (adb) — tethering,
    # GPS forward, battery/heat, clock. No dependency: it does not need
    # Bluetooth, and autoapp must be built wireless-only (BCM_AA_USB=0 in
    # install-openauto.sh) or it flips the phone into AA accessory mode.
    # Switching it OFF stops BCM's supervision only: the NetworkManager
    # profile it created (autoconnect, metric 650, any rndis_host/cdc_ncm
    # device) stays and keeps routing through ANY phone with USB tethering
    # on — hence the note in "hardware" (shown in Settings → Moduły) and
    # docs/WDROZENIE_TESTOWE.md §5.7.
    "car_phone":    {"part": 22, "description": "Telefon w aucie: internet (tethering USB), GPS, bateria i czas z telefonu",
                    "entry": ("src.network.car_phone", "start_car_phone"), "default": False,
                    "group": "telefon_w_aucie",
                    "hardware": "Redmi na USB (adb, debugowanie USB); autoapp z BCM_AA_USB=0. "
                                "Po wyłączeniu usuń profil: sudo nmcli connection delete "
                                "bcm-car-phone"},
    # Plan D3: accelerometer + light of the car phone (SensorServer through
    # car_phone's "sensors" adb forward — car_phone is the only adb user).
    # Publishes phone.g_force / phone.light_lux, never alarm.sensor.*.
    "phone_sensors": {"part": 22, "description": "Czujniki telefonu w aucie: światło i akcelerometr",
                    "entry": ("src.sensors.phone_sensors", "start_phone_sensors"),
                    "default": False, "group": "telefon_w_aucie",
                    "requires": ("car_phone",),
                    "hardware": "Redmi z aplikacją SensorServer (Local Host, port 8080, "
                                "próbkowanie 10000 µs), sztywny uchwyt"},
    # Plan F (shared by D4, H, I): the Termux agent on the car phone, through
    # car_phone's "agent" adb forward. HMAC-signed requests AND answers;
    # the secret comes from /etc/bcm/bcm.env (BCM_CAR_PHONE_AGENT_SECRET).
    # Health, config sync and pairing only — the SMS flow is crash_sms.
    "car_phone_agent": {"part": 22, "description": "Agent w telefonie w aucie (Termux): SMS, alarm postojowy, budzenie",
                    "entry": ("src.network.car_phone_agent", "start_car_phone_agent"),
                    "default": False, "group": "telefon_w_aucie",
                    "requires": ("car_phone",),
                    "hardware": "Redmi: Termux, Termux:API, Termux:Boot i bcm_agent.py "
                                "(tools/car_phone/termux); sekret BCM_CAR_PHONE_AGENT_SECRET "
                                "w /etc/bcm/bcm.env"},
    "weather":     {"part": 14, "description": "Weather Data (OpenWeatherMap)",
                    "entry": ("src.weather.weather", "start_weather"), "default": False},
    # Partia 12: warnings from the OWM data the weather module already
    # fetches (src/weather/alerts.py rules, src/weather/weather_alerts.py
    # runtime): icing, snow, heavy rain, storm, wind, fog — here, ahead and
    # along the planned route. Toast + voice request (voice.announce), A4
    # strip and top-bar icon; the kiosk icing popup stays off. Off in code.
    "weather_alerts": {"part": 14, "description": "Ostrzeżenia pogodowe: oblodzenie, śnieg, ulewa, burza, wiatr, mgła",
                    "entry": ("src.weather.weather_alerts", "start_weather_alerts"),
                    "default": False, "requires": ("weather",),
                    "hardware": "internet i klucz BCM_OWM_API_KEY (moduł weather); GPS dla "
                                "prognozy w miejscu auta i na trasie"},
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
    # Plan F: no camera needed (it never did). Speed comes from GPS only, so
    # it requires location; the accelerometer path needs phone_sensors too,
    # without it only the GPS fallback runs (logs + DVR, never an SMS).
    "crash_detect": {"part": 20, "description": "Wykrywanie stłuczki (akcelerometr telefonu, "
                                                "zapasowo sam GPS) + ochrona nagrań DVR",
                    "entry": ("src.safety.crash_detect", "start_crash_detect"), "default": False,
                    "group": "bezpieczenstwo",
                    "requires": ("location",),
                    "hardware": "GPS (moduł location); pełne wykrywanie z czujnikami telefonu "
                                "(phone_sensors), sam GPS tylko zapisuje zdarzenie"},
    # Plan F "Przebieg": the countdown window and the SMS flow. The PHONE
    # (car_phone_agent) holds the deadline and sends; BCM arms it, shows the
    # window and forwards cancel / send now. Test mode (dry_run) until the
    # safety gate passes — see src/safety/crash_sms.py.
    "crash_sms":   {"part": 20, "description": "SMS do bliskich po wykryciu stłuczki (z odliczaniem i anulowaniem)",
                    "entry": ("src.safety.crash_sms", "start_crash_sms"), "default": False,
                    "group": "bezpieczenstwo",
                    "requires": ("crash_detect", "phone_sensors", "car_phone_agent"),
                    "hardware": "Redmi z kartą SIM, sztywny uchwyt; odbiorcy w Ustawieniach"},
    # Plan H: the 112 button in the crash window (src/safety/call112.py) —
    # ALWAYS manual (held 2 s, loopback-only route). Two paths, chosen at
    # the press: the main phone over HFP (only with a microphone, oFono and
    # network — checked at run time; main.py passes the shared
    # BluetoothManager) or the car phone on its speaker (the agent).
    "call112":      {"part": 20, "description": "Przycisk „Zadzwoń na 112” w oknie wypadku (zawsze ręcznie)",
                     "entry": ("src.safety.call112", "start_call112"), "default": False,
                     "group": "bezpieczenstwo",
                     "requires": ("crash_detect",),
                     "requires_any": (("car_phone_agent", "bluetooth"),),
                     "hardware": "Redmi z rootem (głośnik) albo główny telefon przez HFP "
                                 "+ mikrofon i phone_status; najpierw test_mode z numerem "
                                 "testowym"},
    # Plan D4: the alarm on the parked car runs ON THE PHONE (bcm_agent.py,
    # ParkGuard) — BCM is off when the car is parked. BCM's part
    # (src/safety/parking_guard.py): the owner proof on the phone's
    # authenticated Bluetooth (HFP) link (disarm), the phone's park state on
    # park.state and the Settings row "Postój" (Uzbrój / Rozbrój, loopback
    # only). Never alarm.sensor.* (that is the siren alarm module).
    # Bluetooth is NOT in ``requires``: without it the module still shows
    # the state and disarms with the TOTP code — it warns at start and the
    # row says so (the owner's phone cannot be the proof then).
    "parking_guard": {"part": 22, "description": "Pozycja i alarm auta na postoju (działa w telefonie)",
                     "entry": ("src.safety.parking_guard", "start_parking_guard"),
                     "default": False, "group": "telefon_w_aucie",
                     "requires": ("car_phone_agent",),
                     "hardware": "Redmi z kartą SIM (SMS), agent ≥ 1.2.0; sekret TOTP: "
                                 "bcm_agent.py --park-setup; numery i dom w local.yaml "
                                 "(parking_guard); Bluetooth z HFP (oFono) — telefon "
                                 "właściciela rozbraja tylko z nim"},
    # Plan I: the cabin watch is a layer ON TOP of the parking guard and
    # runs on the phone too (bcm_agent.py, CabinWatch: light + motion → 3
    # photos with the front camera, analysed on the phone, alarm SMS after the
    # entry window). BCM only shows it (src/safety/cabin_watch.py: GET
    # /v1/cabin → park.cabin_state / park.cabin_event history, Settings row
    # "Czuwanie kabiny") — never a photo, never alarm.sensor.*.
    "cabin_watch":  {"part": 22, "description": "Czuwanie kabiny na postoju: zdjęcia przednią kamerą telefonu",
                     "entry": ("src.safety.cabin_watch", "start_cabin_watch"),
                     "default": False, "group": "telefon_w_aucie",
                     "requires": ("car_phone_agent", "parking_guard"),
                     "hardware": "Redmi z rootem: przednia kamera, blokada ekranu „Brak”, "
                                 "agent ≥ 1.3.0; analiza zdjęć z Pillow "
                                 "(pkg install python-pillow)"},
    # Partia 12: the car's position on the owner's Traccar server — sent by
    # the PHONE (bcm_agent.py TraccarReporter, agent >= 1.6.0: OsmAnd over
    # HTTPS, offline queue), because BCM is off while parked. BCM's part
    # (src/network/traccar.py): the settings in the agent's config push
    # (traccar.url + BCM_TRACCAR_DEVICE_ID from bcm.env), the Settings row
    # and "Wyślij pozycję teraz". Off in code (default False;
    # config/bcm_config.yaml decides).
    "traccar":      {"part": 22, "description": "Pozycja auta na Twoim serwerze Traccar (wysyła telefon w aucie)",
                     "entry": ("src.network.traccar", "start_traccar"),
                     "default": False, "group": "telefon_w_aucie",
                     "requires": ("car_phone_agent",),
                     "hardware": "własny serwer Traccar (docs/TRACCAR_SERWER.md), "
                                 "traccar.url w local.yaml, BCM_TRACCAR_DEVICE_ID w "
                                 "/etc/bcm/bcm.env, agent ≥ 1.6.0"},
    # Partia 12: where the car last stood (src/location/last_park.py) — from
    # BCM's own GPS, saved atomically under data/ (the test car's power is
    # simply cut, so also after a minute standing still), shown in Settings
    # and on /trips. Needs only GPS; works without the phone agent. Off in
    # code (default False); the car's config/bcm_config.yaml decides.
    "last_park":    {"part": 12, "description": "Ostatni postój: gdzie auto ostatnio stało (link do mapy)",
                     "entry": ("src.location.last_park", "start_last_park"),
                     "default": False, "requires": ("location",),
                     "hardware": "GPS (moduł location)"},
    # Plan D3 "Światło (lux)": the old BrightnessController (src/power/
    # brightness.py), finally started — light from the car phone
    # (phone.light_lux) OR the Arduino LDR (LIGHT: lines, read by
    # arduino_serial, which the input module starts); the phone wins when
    # both are fresh. The screen in the test car has no brightness control
    # wired, so the default backend dims the IMAGE (an overlay in the
    # kiosk); DDC/CI (ddcutil) is optional, chosen and probed in Settings →
    # "Jasność ekranu". Without the module nothing is dimmed (production).
    "auto_brightness": {"part": 10, "description": "Automatyczna jasność ekranu z czujnika światła",
                     "entry": ("src.power.brightness", "start_auto_brightness"),
                     "default": False, "group": "zasilanie",
                     "requires_any": (("phone_sensors", "input"),),
                     "hardware": "czujnik światła: telefon w aucie (phone_sensors) albo LDR "
                                 "Arduino (input); ściemnianie programowe (nakładka), "
                                 "sprzętowe DDC/CI opcjonalnie (ddcutil)"},
    "battery":     {"part": 21, "description": "Battery Backup Monitor",
                    "entry": ("src.power.battery", "start_battery"), "default": False},

    # --- subsystems started explicitly in main.py ---
    "bluetooth":    {"part": 11, "description": "Bluetooth (BlueZ) — pairing, A2DP/HFP, media",
                     "legacy_key": "bluetooth.enabled", "default": True},
    "phonebook":    {"part": 11, "description": "PBAP phonebook + call history sync (A8 phone screen)",
                     "default": True, "requires": ("bluetooth",)},
    # Off in code (default False; config/bcm_config.yaml decides); started
    # only with Bluetooth on.
    "phone_status": {"part": 11, "description": "Stan telefonu w pasku górnym (bateria, zasięg, operator — oFono/BlueZ)",
                     "default": False, "requires": ("bluetooth",)},
    "fuel_sender":  {"part": 21, "description": "Fuel tank sender calibration (Arduino ADC → %)",
                     "legacy_key": "fuel_sender.enabled", "default": True},
    "wifi_ap":      {"part": 11, "description": "WiFi dla Android Auto wireless (Wi-Fi Direct / P2P-GO, karta wewnętrzna)",
                     "legacy_key": "wifi.enabled", "default": False},
    "wifi_hotspot": {"part": 11, "description": "Dodatkowy Access Point ALFA-NET (współdzielenie internetu — wymaga osobnego dongla WiFi)",
                     "legacy_key": "wifi.alfa_net.enabled", "default": False},
    "route_planner": {"part": 12, "description": "Travel plan (OpenRouteService/TomTom routing)",
                     "default": True},
    # Partia 12: trip.* on A3 (distance, time, average speed) from GPS in
    # --frontend mode, plus consumption/range from fuel_log when it runs.
    # Started with the dashboard (no entry of its own). Off in code: it
    # changes what production A3 shows.
    "trip_gps":     {"part": 12, "description": "Komputer podróży z GPS (dystans, czas, średnia na ekranie trasy)",
                     "default": False, "requires": ("location",),
                     "hardware": "GPS (telefon albo odbiornik) — bez fixu pola pokazują „—”"},
    # Partia 12: TomTom incidents while driving (src/trip/traffic.py pure
    # part, src/trip/traffic_alerts.py runtime): polls incidentDetails every
    # poll_min minutes when moving — a corridor along the planned route
    # (route_planner, optional) or a box ahead of the car — with a daily
    # request budget; toast + voice request for new incidents ahead,
    # traffic.alert for the route screen and small_viewer. Off in code.
    "traffic_alerts": {"part": 12, "description": "Utrudnienia TomTom w trakcie jazdy: korki, wypadki, zamknięcia przed autem",
                     "entry": ("src.trip.traffic_alerts", "start_traffic_alerts"),
                     "default": False, "requires": ("location",),
                     "hardware": "internet i klucz BCM_TOMTOM_API_KEY; GPS z kursem; cel na "
                                 "ekranie trasy (planer tras) dla korytarza wzdłuż trasy"},
    # Partia 12: spoken warnings (src/audio/voice_announce.py): consumes the
    # voice.announce requests of weather_alerts / traffic_alerts — queue with
    # priorities, dedupe and a rate limit, never during a call; Piper (Polish
    # voice) or espeak-ng; played past the EQ on the hardware sink while the
    # music is really ducked (pipewire_ctrl.MusicDucker). Off in code.
    "voice_announce": {"part": 12, "description": "Komunikaty głosowe (Piper / espeak-ng) ze ściszaniem muzyki",
                     "entry": ("src.audio.voice_announce", "start_voice_announce"),
                     "default": False, "requires": ("audio",),
                     "hardware": "Piper z polskim głosem albo espeak-ng (apply-fixes.sh), "
                                 "pw-play (PipeWire) w sesji użytkownika"},
    "small_display": {"part": 2,  "description": "4.3\" stats display server (port 5003)",
                     "default": True},

    # --- add-ons read inside other modules, and the buffered-power build ---
    # Every one defaults to False and is the ONLY switch of its feature
    # (no ``enabled`` sub-keys in the config blocks). None is ``planned``
    # any more (the mechanism is described in the module docstring).
    # Plan D2 — read inside car_phone (no start path of its own): the
    # hotspot status in its Settings row. Read-only; the hotspot itself is
    # configured and switched on the phone.
    "car_phone_hotspot": {"part": 22, "description": "Hotspot Wi-Fi dla pasażerów z telefonu w aucie (stan w Ustawieniach)",
                     "default": False, "group": "telefon_w_aucie",
                     "requires": ("car_phone",),
                     "hardware": "Redmi: hotspot skonfigurowany w telefonie"},
    # Partia 12: "connected" from car_phone / phone_tether only meant the
    # link to the phone was up. This switches on the internet probe in both
    # (src/network/net_probe.py: default route, DNS, HTTPS — at most every
    # 60 s), the Settings row "Internet i usługi" and its "Test" button
    # (POST /api/net/test: key presence + one request per service). Needs
    # neither module: without them the row still shows the keys and tests.
    "net_diag":     {"part": 13, "description": "Diagnostyka internetu i kluczy API (sonda łącza, test OWM/ORS/TomTom)",
                     "default": False,
                     "hardware": "klucze w /etc/bcm/bcm.env (BCM_OWM_API_KEY, BCM_ORS_API_KEY, "
                                 "BCM_TOMTOM_API_KEY)"},
    # Plan E (the buffered build only): the session after Nano #2 woke the
    # computer (driver's door, IR from the car phone, EXT pulse) —
    # src/power/remote_session.py. WAKE:/LEASE: lines come through
    # arduino_serial (started by input); HOLD/RELEASE go back the same way.
    # Nothing here can wake the computer; the firmware owns the rules.
    "remote_session": {"part": 10, "description": "Sesja po zdalnym wybudzeniu (drzwi, telefon): baner i auto-uśpienie",
                     "entry": ("src.power.remote_session", "start_remote_session"),
                     "default": False, "group": "zasilanie",
                     "requires": ("input",),
                     "hardware": "wersja z buforem: Nano #2 (sensor_hub) z FEATURE_WAKE_* "
                                 "i FEATURE_PWRLED, przekaźnik przycisku zasilania; IR — "
                                 "odbiornik TSOP na A3 i telefon w aucie z nadajnikiem IR"},
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


# ── dependency graph (pure functions; no config, no I/O) ──────────────────

#: Why a module does not run (``ModuleStatus.reason``).
REASON_OK = "ok"
REASON_DISABLED = "disabled"
REASON_UNAVAILABLE = "unavailable"      # planned, no code in this version
REASON_MISSING_DEPS = "missing_deps"
REASON_CYCLE = "cycle"                  # catalog bug: guarded, never a hang
REASON_UNKNOWN = "unknown"


@dataclass(frozen=True)
class ModuleStatus:
    """Resolved state of one module for a given set of toggles.

    ``blocked_by`` lists the requirement groups that are NOT satisfied (a
    group is satisfied when any of its members runs), whether or not the
    module itself is enabled — the UI uses it to warn before enabling.
    """
    name: str
    enabled: bool
    available: bool
    runs: bool
    blocked_by: tuple[tuple[str, ...], ...]
    reason: str


def requirement_groups(info: Mapping[str, Any]) -> tuple[tuple[str, ...], ...]:
    """``requires`` + ``requires_any`` as groups: every group needs at least
    one running member, so ``requires: (a, b)`` is ``((a,), (b,))``.

    Malformed entries (a bare string where a tuple is expected) are read the
    forgiving way rather than iterated character by character.
    """
    groups: list[tuple[str, ...]] = []
    req = info.get("requires") or ()
    if isinstance(req, str):
        req = (req,)
    for name in req:
        groups.append((str(name),))
    for group in info.get("requires_any") or ():
        if isinstance(group, str):
            group = (group,)
        members = tuple(str(m) for m in group)
        if members:
            groups.append(members)
    return tuple(groups)


def is_available(info: Mapping[str, Any]) -> bool:
    """False for a planned module (listed, but no code in this version)."""
    return not info.get("planned", False)


def find_cycles(catalog: Mapping[str, Mapping[str, Any]]) -> set[str]:
    """Names that lie on a dependency cycle (Tarjan's SCC; edges to unknown
    names are ignored). The shipped catalog has none — a test pins that —
    but :func:`resolve` must still terminate if someone adds one."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    out: set[str] = set()
    counter = [0]

    def edges(name: str) -> Iterable[str]:
        for group in requirement_groups(catalog[name]):
            for dep in group:
                if dep in catalog:
                    yield dep

    def visit(name: str) -> None:
        index[name] = low[name] = counter[0]
        counter[0] += 1
        stack.append(name)
        on_stack.add(name)
        for dep in edges(name):
            if dep not in index:
                visit(dep)
                low[name] = min(low[name], low[dep])
            elif dep in on_stack:
                low[name] = min(low[name], index[dep])
        if low[name] == index[name]:
            scc = []
            while True:
                top = stack.pop()
                on_stack.discard(top)
                scc.append(top)
                if top == name:
                    break
            if len(scc) > 1 or name in set(edges(name)):
                out.update(scc)

    for name in catalog:
        if name not in index:
            visit(name)
    return out


def resolve(catalog: Mapping[str, Mapping[str, Any]],
            enabled: Mapping[str, bool],
            cycles: Optional[set[str]] = None) -> dict[str, ModuleStatus]:
    """Which modules would start with these toggles, and why not.

    A module runs when it is enabled, available, not on a cycle, and every
    requirement group has a running member — transitively: a dependency
    that is enabled but itself blocked does not count. Unknown names never
    run (a typo in ``requires`` blocks the module instead of being ignored).
    ``cycles``: :func:`find_cycles` of this catalog, if the caller has it.
    """
    if cycles is None:
        cycles = find_cycles(catalog)
    memo: dict[str, bool] = {}

    def runs(name: str) -> bool:
        if name in memo:
            return memo[name]
        info = catalog.get(name)
        if info is None or name in cycles:
            memo[name] = False
            return False
        # Cycle nodes are cut off above, so the recursion below only walks
        # an acyclic graph and terminates.
        ok = bool(enabled.get(name)) and is_available(info) and all(
            any(runs(dep) for dep in group) for group in requirement_groups(info))
        memo[name] = ok
        return ok

    out: dict[str, ModuleStatus] = {}
    for name, info in catalog.items():
        on = bool(enabled.get(name))
        available = is_available(info)
        blocked = tuple(group for group in requirement_groups(info)
                        if not any(runs(dep) for dep in group))
        running = runs(name)
        if running:
            reason = REASON_OK
        elif not on:
            reason = REASON_DISABLED
        elif not available:
            reason = REASON_UNAVAILABLE
        elif name in cycles:
            reason = REASON_CYCLE
        else:
            reason = REASON_MISSING_DEPS
        out[name] = ModuleStatus(name=name, enabled=on, available=available,
                                 runs=running, blocked_by=blocked, reason=reason)
    return out


def enable_plan(catalog: Mapping[str, Mapping[str, Any]], enabled: Mapping[str, bool],
                name: str) -> Optional[list[str]]:
    """Modules to switch on (besides ``name``) so that ``name`` runs.

    Dependencies first, in start order, without duplicates and without
    modules that are already on. For a ``requires_any`` group a member that
    already runs wins; otherwise the members are tried in catalog order (the
    first listed is the preferred one). None when it cannot be done: the
    module or every alternative of some group is unknown, planned or on a
    cycle. Only a proposal — the caller asks the driver before applying it.
    """
    cycles = find_cycles(catalog)

    def make_run(target: str, want: dict[str, bool], stack: tuple[str, ...]) \
            -> Optional[tuple[dict[str, bool], list[str]]]:
        info = catalog.get(target)
        if info is None or target in cycles or target in stack or not is_available(info):
            return None
        want = dict(want)
        plan: list[str] = []
        for group in requirement_groups(info):
            current = resolve(catalog, want, cycles)
            if any(current[d].runs for d in group if d in current):
                continue
            for dep in group:
                got = make_run(dep, want, stack + (target,))
                if got is not None:
                    want, sub = got
                    plan += [m for m in sub if m not in plan]
                    break
            else:
                return None
        if not want.get(target):
            want[target] = True
            plan.append(target)
        return want, plan

    got = make_run(name, dict(enabled), ())
    if got is None:
        return None
    return [m for m in got[1] if m != name]


def would_stop(catalog: Mapping[str, Mapping[str, Any]], enabled: Mapping[str, bool],
               name: str, cycles: Optional[set[str]] = None) -> list[str]:
    """Modules that run now but would not with ``name`` switched off
    (transitively, ``name`` itself excluded) — what the UI names before the
    driver turns off e.g. bluetooth."""
    if cycles is None:
        cycles = find_cycles(catalog)
    before = resolve(catalog, enabled, cycles)
    after = resolve(catalog, dict(enabled, **{name: False}), cycles)
    return [n for n in catalog if n != name and before[n].runs and not after[n].runs]


def root_blockers(states: Mapping[str, ModuleStatus], name: str) -> list[str]:
    """What actually stops ``name``: follows each unsatisfied requirement
    through dependencies that are switched ON but do not run themselves,
    down to the modules that are off, not available in this version, on a
    cycle or unknown. For ``parking_guard -> car_phone_agent (on) ->
    car_phone (off)`` that is ``["car_phone"]`` — the toggle the driver has
    to touch, where ``blocked_by`` would only name ``car_phone_agent``.
    Order of first appearance, no duplicates; the walk is bounded by the
    visited set, so a cycle cannot loop."""
    out: list[str] = []
    seen: set[str] = {name}

    def walk(current: str) -> None:
        st = states.get(current)
        if st is None:
            return
        for group in st.blocked_by:
            for dep in group:
                if dep in seen:
                    continue
                seen.add(dep)
                dep_st = states.get(dep)
                if dep_st is not None and dep_st.enabled and dep_st.reason == REASON_MISSING_DEPS:
                    walk(dep)
                elif dep not in out:
                    out.append(dep)

    walk(name)
    return out


def block_message(status: ModuleStatus,
                  catalog: Optional[Mapping[str, Mapping[str, Any]]] = None,
                  states: Optional[Mapping[str, ModuleStatus]] = None) -> str:
    """The ONE start-up log line for an enabled module that will not start
    (English, like the rest of main.py's log); '' when it starts or is off.
    ``catalog`` (default :data:`MODULES`) only marks names it does not know.
    ``states`` (:func:`resolve` of the same toggles) lets the line tell a
    dependency that is off from one that is ON but blocked itself — the
    latter is labelled so, and the line names the toggles to switch on
    (:func:`root_blockers`) instead of sending the driver to a module that
    is already enabled."""
    if status.runs or not status.enabled:
        return ""
    if status.reason == REASON_UNAVAILABLE:
        return (f"Module {status.name}: enabled in config but not available in this "
                f"version — ignored")
    if status.reason == REASON_CYCLE:
        return f"Module {status.name} not started: dependency cycle in the module catalog"
    known = MODULES if catalog is None else catalog
    states = states or {}

    def label(dep: str) -> str:
        if dep not in known:
            return f"{dep} (unknown module)"
        st = states.get(dep)
        if st is None or st.runs:
            return dep
        # ``available``, not the reason: a planned module that is OFF has
        # reason "disabled", yet Settings cannot switch it on either.
        if not st.available:
            return f"{dep} (not available in this version)"
        if st.reason == REASON_CYCLE:
            return f"{dep} (dependency cycle)"
        if st.enabled:
            return f"{dep} (enabled, but not running)"
        return dep

    def switchable(dep: str) -> bool:
        st = states.get(dep)
        return dep in known and (st is None or (st.available and st.reason != REASON_CYCLE))

    missing = ", ".join(" or ".join(label(d) for d in group)
                        for group in status.blocked_by) or "?"
    direct = [d for group in status.blocked_by for d in group]
    roots = [r for r in root_blockers(states, status.name) if r not in direct]
    text = f"Module {status.name} not started: missing dependency {missing}"
    if roots:
        text += f"; the cause: {', '.join(label(r) for r in roots)}"
    # Point at Settings only when there is something there to switch on;
    # otherwise the labels (unknown / not available / cycle) say why not.
    if any(switchable(d) for d in (roots or direct)):
        text += " (enable it in Settings → Moduły / modules.* in local.yaml)"
    return text


# ── config-facing helpers ──────────────────────────────────────────────────

def enabled_map(config, overrides: Optional[Mapping[str, bool]] = None) -> dict[str, bool]:
    """``is_enabled`` for every catalog entry, ``overrides`` applied on top
    (main.py's ``--modules`` list decides registry modules on its own)."""
    out = {name: bool(is_enabled(config, name)) for name in MODULES}
    if overrides:
        for name, value in overrides.items():
            if name in out:
                out[name] = bool(value)
    return out


def module_states(config, overrides: Optional[Mapping[str, bool]] = None) \
        -> dict[str, ModuleStatus]:
    """:func:`resolve` over the real catalog for this config."""
    return resolve(MODULES, enabled_map(config, overrides))


def _kind(info: Mapping[str, Any], name: str) -> str:
    if not is_available(info):
        return "planned"
    return "module" if "entry" in info or name == "dashboard" else "subsystem"


def catalog_state(config, boot_runs: Optional[Mapping[str, bool]] = None) -> list[dict]:
    """Full module list with effective state — payload for /api/modules.

    Per module: ``enabled`` (the toggle), ``available`` (False = planned),
    ``runs`` (would start with the saved toggles), ``requires`` /
    ``requires_any`` (catalog), ``blocked_by`` (unsatisfied groups, also for
    a module that is off), ``needs`` (what else to switch on for it to run;
    None if impossible), ``would_stop`` (running modules that stop when this
    one is switched off), ``hardware``, ``group``. With ``boot_runs`` (what
    ran when BCM started) also ``restart_pending``: the saved toggles differ
    from the running process in a way only a restart applies.
    """
    toggles = enabled_map(config)
    cycles = find_cycles(MODULES)
    states = resolve(MODULES, toggles, cycles)
    out = []
    for name, info in MODULES.items():
        st = states[name]
        item = {
            "name": name,
            "part": info["part"],
            "description": info["description"],
            "enabled": st.enabled,
            "kind": _kind(info, name),
            "available": st.available,
            "runs": st.runs,
            "reason": st.reason,
            "group": info.get("group", ""),
            "hardware": info.get("hardware", ""),
            "requires": [g[0] for g in requirement_groups({"requires": info.get("requires")})],
            "requires_any": [list(g) for g in requirement_groups(
                {"requires_any": info.get("requires_any")})],
            "blocked_by": [list(g) for g in st.blocked_by],
            "needs": [] if st.runs else enable_plan(MODULES, toggles, name),
            "would_stop": would_stop(MODULES, toggles, name, cycles) if st.runs else [],
        }
        if boot_runs is not None:
            item["restart_pending"] = bool(boot_runs.get(name, False)) != st.runs
        out.append(item)
    return out
