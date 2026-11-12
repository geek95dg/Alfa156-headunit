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
    "network":     {"part": 13, "description": "LTE/Cellular Connectivity",
                    "entry": ("src.network.lte", "start_network"), "default": False},
    # Off in code (production unchanged); this toggle is its only switch.
    # Needs bluetooth: it follows bt.connected from the BluetoothManager.
    "phone_tether": {"part": 13, "description": "Internet z telefonu (Bluetooth PAN przez NetworkManager)",
                    "entry": ("src.network.phone_tether", "start_phone_tether"), "default": False,
                    "requires": ("bluetooth",),
                    "hardware": "telefon z włączonym tetheringiem Bluetooth"},
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
                    "entry": ("src.camera.crash_detect", "start_crash_detect"), "default": False,
                    "group": "bezpieczenstwo"},
    "battery":     {"part": 21, "description": "Battery Backup Monitor",
                    "entry": ("src.power.battery", "start_battery"), "default": False},

    # --- subsystems started explicitly in main.py ---
    "bluetooth":    {"part": 11, "description": "Bluetooth (BlueZ) — pairing, A2DP/HFP, media",
                     "legacy_key": "bluetooth.enabled", "default": True},
    "phonebook":    {"part": 11, "description": "PBAP phonebook + call history sync (A8 phone screen)",
                     "default": True, "requires": ("bluetooth",)},
    # Off in code (production unchanged); started only with Bluetooth on.
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
    "small_display": {"part": 2,  "description": "4.3\" stats display server (port 5003)",
                     "default": True},

    # --- planned modules (plan sections C–I): listed, never started ---
    # Every one defaults to False and is the ONLY switch of its feature
    # (no ``enabled`` sub-keys in the config blocks). ``planned`` goes away
    # when the code lands; ``requires`` already describes the final graph.
    "car_phone":    {"part": 22, "description": "Telefon w aucie: internet (tethering USB), GPS, bateria i czas z telefonu",
                     "default": False, "planned": True, "group": "telefon_w_aucie",
                     "hardware": "Redmi na USB (adb, debugowanie USB)"},
    "car_phone_hotspot": {"part": 22, "description": "Hotspot Wi-Fi dla pasażerów z telefonu w aucie (stan w Ustawieniach)",
                     "default": False, "planned": True, "group": "telefon_w_aucie",
                     "requires": ("car_phone",),
                     "hardware": "Redmi: hotspot skonfigurowany w telefonie"},
    "phone_sensors": {"part": 22, "description": "Czujniki telefonu w aucie: światło i akcelerometr",
                     "default": False, "planned": True, "group": "telefon_w_aucie",
                     "requires": ("car_phone",),
                     "hardware": "Redmi z aplikacją SensorServer, sztywny uchwyt"},
    "car_phone_agent": {"part": 22, "description": "Agent w telefonie w aucie (Termux): SMS, alarm postojowy, budzenie",
                     "default": False, "planned": True, "group": "telefon_w_aucie",
                     "requires": ("car_phone",),
                     "hardware": "Redmi: Termux, Termux:API, Termux:Boot"},
    "parking_guard": {"part": 22, "description": "Pozycja i alarm auta na postoju (działa w telefonie)",
                     "default": False, "planned": True, "group": "telefon_w_aucie",
                     "requires": ("car_phone_agent",),
                     "hardware": "Redmi z kartą SIM (SMS)"},
    "cabin_watch":  {"part": 22, "description": "Czuwanie kabiny na postoju: zdjęcia przednią kamerą telefonu",
                     "default": False, "planned": True, "group": "telefon_w_aucie",
                     "requires": ("car_phone_agent",),
                     "hardware": "Redmi: przednia kamera, blokada ekranu „Brak”"},
    "crash_sms":    {"part": 20, "description": "SMS do bliskich po wykryciu stłuczki (z odliczaniem i anulowaniem)",
                     "default": False, "planned": True, "group": "bezpieczenstwo",
                     "requires": ("crash_detect", "phone_sensors", "car_phone_agent"),
                     "hardware": "Redmi z kartą SIM, sztywny uchwyt"},
    # The 112 button lives in the crash window (crash_detect). Two paths:
    # the car phone on speaker (agent) or the main phone over HFP — the
    # latter only with a microphone, which is checked at run time.
    "call112":      {"part": 20, "description": "Przycisk „Zadzwoń na 112” w oknie wypadku (zawsze ręcznie)",
                     "default": False, "planned": True, "group": "bezpieczenstwo",
                     "requires": ("crash_detect",),
                     "requires_any": (("car_phone_agent", "bluetooth"),),
                     "hardware": "Redmi (głośnik) albo główny telefon przez HFP + mikrofon"},
    # Light from the car phone OR the Arduino light sensor (LIGHT: lines,
    # read by arduino_serial, which the input module starts).
    "auto_brightness": {"part": 10, "description": "Automatyczna jasność ekranu z czujnika światła",
                     "default": False, "planned": True, "group": "zasilanie",
                     "requires_any": (("phone_sensors", "input"),),
                     "hardware": "czujnik światła: telefon w aucie albo Arduino; DDC/CI lub xrandr"},
    # WAKE:/LEASE: lines come from Nano #2 through arduino_serial (input).
    "remote_session": {"part": 10, "description": "Sesja po zdalnym wybudzeniu (drzwi, telefon): baner i auto-uśpienie",
                     "default": False, "planned": True, "group": "zasilanie",
                     "requires": ("input",),
                     "hardware": "Nano #2 (sensor_hub) z FEATURE_WAKE_* i przekaźnikiem przycisku zasilania"},
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
