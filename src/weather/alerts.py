"""Weather warnings for the driver — the pure rule engine.

No bus, no network, no clock of its own: :func:`evaluate` turns the current
conditions and the 3-hour forecast slots (src/weather/weather.py) into a
short list of alerts, and :class:`AlertAnnouncer` decides which of them to
announce (toast + voice) and which were already said. The runtime around
both is src/weather/weather_alerts.py.

Inputs are untrusted (OpenWeatherMap answers, the event bus): every value
goes through :func:`observation`, which keeps only finite numbers in sane
ranges — a missing or odd field switches a rule off, it never raises.

Kinds (each one at most ONCE in the result, the most severe occurrence;
also the ``weather_alerts.categories`` switch and the notification key
``weather_<kind>``):

* ``icing`` — danger: freezing rain (OWM 511) or liquid precipitation at
  T ≤ 0 °C; warning: T ≤ ``icing_temp_c`` (2 °C) with precipitation, fog,
  humidity ≥ ``icing_humidity_pct`` (90 %) or a dew-point spread ≤
  ``icing_dew_spread_c`` (1 °C), or the temperature falling through 0 °C
  within 3 h after rain; info: "zimna nawierzchnia" on a clear night at
  0…``cold_surface_max_c`` (3 °C).
  Not src/environment/icing.py: that one reads the car's DS18B20, which the
  test car does not have (the module runs on a simulator on x86).
* ``snow`` — warning: any snow; danger: heavy (OWM 602/622 or ≥
  ``snow_heavy_mm_3h`` per 3 h).
* ``rain`` — warning: ≥ ``heavy_rain_mm_3h`` (10 mm) per 3 h or OWM
  502/503/504/522/531; danger: twice the threshold or 503/504.
* ``storm`` — warning: OWM 2xx; danger: the heavy ones (202, 212, 221, 232).
* ``wind`` — warning: gusts ≥ ``gust_ms`` (15 m/s) or wind ≥ ``wind_ms``
  (14 m/s); danger: gusts ≥ ``gust_danger_ms`` (25 m/s).
* ``fog`` — warning: OWM 741 or visibility < ``fog_visibility_m`` (200 m);
  danger: visibility < a quarter of it.

Alert: ``{id, kind, severity, title, text, where, valid_until, eta_min}``.
``text`` is Polish, short and written to be read aloud (stage 6 speaks it):
"2 stopnie", "za około 2 godziny" — never "°C" or "~".
"""

from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional

KINDS = ("icing", "snow", "rain", "storm", "wind", "fog")
SEVERITIES = ("info", "warning", "danger")
RANK = {s: i for i, s in enumerate(SEVERITIES)}
#: ``where`` values (the UI shows them; "za ~N h" is built from these).
WHERE_NOW, WHERE_ROUTE = "teraz", "na trasie"

#: A forecast slot describes 3 hours; one this close to "now" is "teraz".
NOW_WINDOW_MIN = 90.0
#: "Temperature falls through 0 °C within this many minutes after rain".
CROSSING_WINDOW_MIN = 180.0
#: How long an alert built from the current conditions stays valid.
CURRENT_VALID_S = 3600.0
#: A forecast slot's alert is valid until its 3-hour period is over.
SLOT_VALID_S = 1.5 * 3600.0

_STORM_HEAVY = frozenset({202, 212, 221, 232})
_RAIN_HEAVY = frozenset({502, 503, 504, 522, 531})
_RAIN_EXTREME = frozenset({503, 504})
_SNOW_HEAVY = frozenset({602, 622})
_FREEZING_RAIN = 511
_FOG_IDS = frozenset({741})
_MIST_IDS = frozenset({701, 741})
_CLEAR_IDS = frozenset({800, 801})
_ICON_RE = re.compile(r"^[0-9]{2}[dn]$")


# ── configuration ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class AlertConfig:
    """``weather_alerts`` block, every number bounded (see :func:`load_config`)."""
    categories: dict = field(default_factory=lambda: {k: True for k in KINDS})
    lookahead_h: float = 6.0
    cooldown_min: float = 60.0
    icing_temp_c: float = 2.0
    icing_humidity_pct: float = 90.0
    icing_dew_spread_c: float = 1.0
    cold_surface_max_c: float = 3.0
    heavy_rain_mm_3h: float = 10.0
    snow_heavy_mm_3h: float = 3.0
    gust_ms: float = 15.0
    gust_danger_ms: float = 25.0
    wind_ms: float = 14.0
    fog_visibility_m: float = 200.0
    voice: bool = True
    voice_min_severity: str = "warning"
    quiet_hours: Optional[tuple[int, int]] = None   # (start_min, end_min) local
    route: bool = True

    def enabled(self, kind: str) -> bool:
        return bool(self.categories.get(kind, False))


#: key -> (default, lo, hi) of the numeric options.
_NUMERIC = {
    "lookahead_h": (6.0, 1.0, 24.0),
    "cooldown_min": (60.0, 5.0, 720.0),
    "icing_temp_c": (2.0, 0.0, 5.0),
    "icing_humidity_pct": (90.0, 50.0, 100.0),
    "icing_dew_spread_c": (1.0, 0.0, 5.0),
    "cold_surface_max_c": (3.0, 0.0, 6.0),
    "heavy_rain_mm_3h": (10.0, 1.0, 100.0),
    "snow_heavy_mm_3h": (3.0, 0.5, 50.0),
    "gust_ms": (15.0, 5.0, 60.0),
    "gust_danger_ms": (25.0, 5.0, 80.0),
    "wind_ms": (14.0, 5.0, 60.0),
    "fog_visibility_m": (200.0, 20.0, 2000.0),
}
_QUIET_RE = re.compile(r"^\s*([01]?\d|2[0-3]):([0-5]\d)\s*-\s*([01]?\d|2[0-3]):([0-5]\d)\s*$")


def _num(value: Any, lo: float = -math.inf, hi: float = math.inf) -> Optional[float]:
    """A finite number within [lo, hi], else None (bools are not numbers)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        value = float(value)
    except (OverflowError, ValueError):
        return None
    return value if math.isfinite(value) and lo <= value <= hi else None


def parse_quiet_hours(value: Any) -> Optional[tuple[int, int]]:
    """``"22:00-06:00"`` → (1320, 360) minutes; '' / invalid / equal → None."""
    if not isinstance(value, str) or not value.strip():
        return None
    m = _QUIET_RE.match(value)
    if not m:
        return None
    start = int(m.group(1)) * 60 + int(m.group(2))
    end = int(m.group(3)) * 60 + int(m.group(4))
    return None if start == end else (start, end)


def in_quiet_hours(quiet: Optional[tuple[int, int]], minute_of_day: int) -> bool:
    """Whether ``minute_of_day`` (0..1439) falls in the window (may wrap midnight)."""
    if not quiet:
        return False
    start, end = quiet
    if start < end:
        return start <= minute_of_day < end
    return minute_of_day >= start or minute_of_day < end


def load_config(raw: Any, warn: Optional[Callable[[str], None]] = None) -> AlertConfig:
    """``weather_alerts`` from the config → :class:`AlertConfig`.

    A wrong value never stops the module: it is replaced by the default and
    reported once through ``warn`` (the caller's logger).
    """
    raw = raw if isinstance(raw, dict) else {}
    say = warn or (lambda _msg: None)
    out: dict[str, Any] = {}
    for key, (default, lo, hi) in _NUMERIC.items():
        if key not in raw or raw[key] is None:
            out[key] = default
            continue
        value = _num(raw[key], lo, hi)
        if value is None:
            say(f"weather_alerts.{key}={raw[key]!r} poza zakresem {lo:g}..{hi:g} — biorę {default:g}")
            value = default
        out[key] = value
    if out["gust_danger_ms"] < out["gust_ms"]:
        say("weather_alerts.gust_danger_ms < gust_ms — biorę gust_ms")
        out["gust_danger_ms"] = out["gust_ms"]
    cats = raw.get("categories")
    categories = {k: True for k in KINDS}
    if isinstance(cats, dict):
        for k, v in cats.items():
            if k in categories and isinstance(v, bool):
                categories[k] = v
            else:
                say(f"weather_alerts.categories.{k!s:.40}: nieznana kategoria albo nie true/false")
    elif cats is not None:
        say("weather_alerts.categories nie jest słownikiem — wszystkie włączone")
    voice_min = raw.get("voice_min_severity", "warning")
    if voice_min not in SEVERITIES:
        say(f"weather_alerts.voice_min_severity={voice_min!r:.40} — biorę warning")
        voice_min = "warning"
    quiet_raw = raw.get("quiet_hours", "")
    quiet = parse_quiet_hours(quiet_raw)
    if quiet is None and isinstance(quiet_raw, str) and quiet_raw.strip():
        say(f"weather_alerts.quiet_hours={quiet_raw!r:.40} — oczekuję GG:MM-GG:MM, cisza wyłączona")
    return AlertConfig(categories=categories, voice=raw.get("voice", True) is not False,
                       voice_min_severity=voice_min, quiet_hours=quiet,
                       route=raw.get("route", True) is not False, **out)


# ── observations ────────────────────────────────────────────────────────

def dew_point(temp_c: float, humidity_pct: float) -> Optional[float]:
    """Dew point in °C (Magnus formula; ±0.4 °C between -40 and 50 °C)."""
    if humidity_pct <= 0:
        return None
    a, b = 17.62, 243.12
    gamma = math.log(humidity_pct / 100.0) + a * temp_c / (b + temp_c)
    return b * gamma / (a - gamma)


def observation(raw: Any, *, now: float, source: str,
                eta_min: Optional[float] = None) -> Optional[dict]:
    """One normalised observation from ``weather.current`` (source
    ``current``) or a 3-hour slot (``forecast`` / ``route``), or None.

    Units: temperatures °C, rain/snow mm per 3 h, wind and gusts m/s,
    visibility m. ``eta_min``: minutes from ``now`` (0 for the current
    conditions; for a slot from its time unless given — route points pass
    their own ETA along the route).
    """
    if not isinstance(raw, dict):
        return None
    temp = _num(raw.get("temp"), -90, 70)
    wid = _num(raw.get("weather_id"), 100, 999)
    humidity = _num(raw.get("humidity"), 0, 100)
    icon = raw.get("icon") if isinstance(raw.get("icon"), str) and \
        _ICON_RE.match(raw.get("icon")) else None
    if source == "current":
        ts = now
        eta = 0.0
        # weather.current: wind in km/h, rain/snow per hour (OWM "1h").
        rain_h = _num(raw.get("rain_1h"), 0, 300)
        snow_h = _num(raw.get("snow_1h"), 0, 300)
        rain = rain_h * 3 if rain_h is not None else None
        snow = snow_h * 3 if snow_h is not None else None
        wind_kmh = _num(raw.get("wind_speed"), 0, 450)
    else:
        ts = _num(raw.get("slot_ts", raw.get("ts")), 1e9, 1e10)
        if ts is None:
            return None
        given = _num(eta_min, -1e6, 1e6)
        eta = given if given is not None else (ts - now) / 60.0
        rain = _num(raw.get("rain_mm"), 0, 500)
        snow = _num(raw.get("snow_mm"), 0, 500)
        wind_kmh = _num(raw.get("wind_kmh"), 0, 450)
    gust_kmh = _num(raw.get("gust_kmh"), 0, 540)
    if temp is None and wid is None and wind_kmh is None and gust_kmh is None:
        return None
    return {
        "source": source,
        "ts": ts,
        "eta_min": eta,
        "temp": temp,
        "humidity": humidity,
        "weather_id": int(wid) if wid is not None else None,
        "rain_mm_3h": rain or 0.0,
        "snow_mm_3h": snow or 0.0,
        "wind_ms": wind_kmh / 3.6 if wind_kmh is not None else None,
        "gust_ms": gust_kmh / 3.6 if gust_kmh is not None else None,
        "visibility_m": _num(raw.get("visibility_m"), 0, 100000),
        "night": bool(icon and icon.endswith("n")),
    }


def _group(wid: Optional[int]) -> int:
    return wid // 100 if wid is not None else 0


def _liquid(obs: dict) -> bool:
    """Rain or drizzle (also rain in a thunderstorm), not snow."""
    g = _group(obs["weather_id"])
    return g in (3, 5) or obs["weather_id"] in (200, 201, 202, 230, 231, 232) \
        or obs["rain_mm_3h"] > 0.05


def _snowing(obs: dict) -> bool:
    return _group(obs["weather_id"]) == 6 or obs["snow_mm_3h"] > 0.05


# ── Polish, speakable ───────────────────────────────────────────────────

def _plural(n: int, one: str, few: str, many: str) -> str:
    n = abs(n)
    if n == 1:
        return one
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return few
    return many


def degrees_text(temp: float) -> str:
    """-3.4 → "minus 3 stopnie" (rounded; speakable)."""
    n = int(round(temp))
    word = _plural(n, "stopień", "stopnie", "stopni")
    return f"minus {abs(n)} {word}" if n < 0 else f"{n} {word}"


def hours_text(hours: int) -> str:
    """2 → "za około 2 godziny"."""
    hours = max(1, hours)
    return f"za około {hours} {_plural(hours, 'godzinę', 'godziny', 'godzin')}"


def _when(obs: dict) -> tuple[str, str]:
    """(``where`` for the UI, the same said aloud)."""
    if obs["source"] == "route":
        return WHERE_ROUTE, WHERE_ROUTE
    if obs["eta_min"] <= NOW_WINDOW_MIN:
        return WHERE_NOW, WHERE_NOW
    hours = max(1, int(round(obs["eta_min"] / 60.0)))
    return f"za ~{hours} h", hours_text(hours)


# ── rules ───────────────────────────────────────────────────────────────

def _candidate(kind: str, severity: str, title: str, text: str, obs: dict,
               now: float) -> dict:
    where, _ = _when(obs)
    valid = now + CURRENT_VALID_S if obs["source"] == "current" else obs["ts"] + SLOT_VALID_S
    return {"id": f"weather_{kind}", "kind": kind, "severity": severity, "title": title,
            "text": text, "where": where, "valid_until": round(valid, 1),
            "eta_min": round(max(0.0, obs["eta_min"]), 1)}


def _icing(obs: dict, cfg: AlertConfig, now: float) -> Optional[dict]:
    temp = obs["temp"]
    if temp is None:
        return None
    _, said = _when(obs)
    deg = degrees_text(temp)
    if obs["weather_id"] == _FREEZING_RAIN or (temp <= 0.0 and _liquid(obs)):
        return _candidate("icing", "danger", "Gołoledź",
                          f"Marznący opad, {deg}, {said}. Jedź bardzo ostrożnie.", obs, now)
    if temp <= cfg.icing_temp_c:
        reason = None
        if _liquid(obs) or _snowing(obs):
            reason = "opady"
        elif obs["weather_id"] in _MIST_IDS:
            reason = "mgła"
        elif obs["humidity"] is not None:
            dp = dew_point(temp, obs["humidity"])
            if obs["humidity"] >= cfg.icing_humidity_pct or \
                    (dp is not None and temp - dp <= cfg.icing_dew_spread_c):
                reason = "duża wilgotność"
        if reason:
            return _candidate("icing", "warning", "Ryzyko oblodzenia",
                              f"{deg} i {reason}, {said}. Uważaj na mostach i w cieniu.",
                              obs, now)
    if 0.0 <= temp <= cfg.cold_surface_max_c and obs["night"] \
            and obs["weather_id"] in _CLEAR_IDS:
        return _candidate("icing", "info", "Zimna nawierzchnia",
                          f"Bezchmurna noc, {deg}. Na mostach i w cieniu może być ślisko.",
                          obs, now)
    return None


def _crossing(here: list[dict], recent_rain: bool, now: float,
              cur: Optional[dict] = None) -> Optional[dict]:
    """T falls through 0 °C within 3 h after (or during) rain."""
    # Start from the current observation when there is one: a slot that
    # has just passed (sorted ahead of it) must not decide "already ≤ 0".
    start = cur if cur is not None else (here[0] if here else None)
    if start is None or start["temp"] is None or start["temp"] <= 0.0:
        return None
    wet = recent_rain
    for obs in here:
        if obs["eta_min"] < 0:
            continue
        if obs["eta_min"] > CROSSING_WINDOW_MIN:
            break
        if obs["temp"] is not None and obs["temp"] <= 0.0 and wet:
            _, said = _when(obs)
            return _candidate("icing", "warning", "Ryzyko oblodzenia",
                              f"Po deszczu temperatura spadnie poniżej zera, {said}. "
                              "Możliwa gołoledź.", obs, now)
        wet = wet or _liquid(obs)
    return None


def _snow(obs: dict, cfg: AlertConfig, now: float) -> Optional[dict]:
    if not _snowing(obs):
        return None
    _, said = _when(obs)
    if obs["weather_id"] in _SNOW_HEAVY or obs["snow_mm_3h"] >= cfg.snow_heavy_mm_3h:
        return _candidate("snow", "danger", "Intensywne opady śniegu",
                          f"Intensywne opady śniegu, {said}. Zwolnij i zwiększ odstęp.",
                          obs, now)
    return _candidate("snow", "warning", "Opady śniegu",
                      f"Opady śniegu, {said}. Droga może być śliska.", obs, now)


def _rain(obs: dict, cfg: AlertConfig, now: float) -> Optional[dict]:
    mm, wid = obs["rain_mm_3h"], obs["weather_id"]
    if wid in _RAIN_EXTREME or mm >= 2 * cfg.heavy_rain_mm_3h:
        severity = "danger"
    elif wid in _RAIN_HEAVY or mm >= cfg.heavy_rain_mm_3h:
        severity = "warning"
    else:
        return None
    _, said = _when(obs)
    return _candidate("rain", severity, "Ulewa",
                      f"Intensywny deszcz, {said}. Zwolnij, uważaj na aquaplaning.", obs, now)


def _storm(obs: dict, cfg: AlertConfig, now: float) -> Optional[dict]:
    if _group(obs["weather_id"]) != 2:
        return None
    _, said = _when(obs)
    severity = "danger" if obs["weather_id"] in _STORM_HEAVY else "warning"
    return _candidate("storm", severity, "Burza",
                      f"Burza, {said}. Możliwe porywy wiatru i ulewa.", obs, now)


def _wind(obs: dict, cfg: AlertConfig, now: float) -> Optional[dict]:
    gust, wind = obs["gust_ms"], obs["wind_ms"]
    peak = max(v for v in (gust, wind, 0.0) if v is not None)
    if gust is not None and gust >= cfg.gust_danger_ms:
        severity = "danger"
    elif (gust is not None and gust >= cfg.gust_ms) or (wind is not None and wind >= cfg.wind_ms):
        severity = "warning"
    else:
        return None
    _, said = _when(obs)
    kmh = int(round(peak * 3.6))
    # Speak of gusts only when a gust actually triggered the alert.
    lead = "Porywy wiatru" if gust is not None and gust >= cfg.gust_ms else "Silny wiatr"
    return _candidate("wind", severity, "Silny wiatr",
                      f"{lead} do {kmh} kilometrów na godzinę, {said}. "
                      "Trzymaj mocno kierownicę.", obs, now)


def _fog(obs: dict, cfg: AlertConfig, now: float) -> Optional[dict]:
    vis = obs["visibility_m"]
    if vis is not None and vis < cfg.fog_visibility_m / 4:
        severity = "danger"
    elif (vis is not None and vis < cfg.fog_visibility_m) or obs["weather_id"] in _FOG_IDS:
        severity = "warning"
    else:
        return None
    _, said = _when(obs)
    limit = int(cfg.fog_visibility_m if severity == "warning" else cfg.fog_visibility_m / 4)
    # A visibility figure only when the visibility itself is below it
    # (OWM 741 alone says nothing about how far one can see).
    seen = f", widoczność poniżej {limit} metrów" if vis is not None and vis < limit else ""
    return _candidate("fog", severity, "Gęsta mgła",
                      f"Gęsta mgła{seen}, {said}. "
                      "Włącz światła przeciwmgielne.", obs, now)


_RULES = (("icing", _icing), ("snow", _snow), ("rain", _rain), ("storm", _storm),
          ("wind", _wind), ("fog", _fog))


def _better(a: dict, b: Optional[dict]) -> bool:
    """``a`` beats ``b``: more severe, then sooner ("teraz" before later)."""
    if b is None:
        return True
    if RANK[a["severity"]] != RANK[b["severity"]]:
        return RANK[a["severity"]] > RANK[b["severity"]]
    if (a["where"] == WHERE_ROUTE) != (b["where"] == WHERE_ROUTE):
        return b["where"] == WHERE_ROUTE      # here before "na trasie"
    return a["eta_min"] < b["eta_min"]


def evaluate(current: Any, slots: Iterable[Any], *, now: float,
             cfg: Optional[AlertConfig] = None, route: Iterable[Any] = (),
             recent_rain: bool = False) -> list[dict]:
    """Alerts for the driver, most severe first (one per kind at most).

    ``current``: ``weather.current`` (or None when stale / demo).
    ``slots``: the 3-hour slots for the car's position (``ts`` or
    ``slot_ts``); only those after ``now`` (from ``now - 90 min`` when
    ``current`` is None) up to ``now + lookahead_h`` count. ``route``: ``(slot, eta_min)`` pairs from ``forecast_at`` for
    points ahead on the route. ``recent_rain``: it rained here in the last
    3 hours (the runtime remembers it — OWM has no past slots).
    """
    cfg = cfg or AlertConfig()
    here: list[dict] = []
    cur = observation(current, now=now, source="current") if current is not None else None
    if cur is not None:
        here.append(cur)
    horizon = cfg.lookahead_h * 60.0
    for raw in slots or ():
        obs = observation(raw, now=now, source="forecast")
        # OWM rain.3h / snow.3h is the volume for the 3 h ENDING at dt, so a
        # slot already past describes weather that may be over. With current
        # conditions at hand they alone stand for "teraz"; the past-slot
        # tolerance stays only for when current is stale or demo.
        if obs is None or obs["eta_min"] > horizon:
            continue
        if (obs["eta_min"] > 0) if cur is not None else (obs["eta_min"] >= -NOW_WINDOW_MIN):
            here.append(obs)
    here.sort(key=lambda o: (o["eta_min"], o["source"] != "current"))
    along: list[dict] = []
    if cfg.route:
        for item in route or ():
            if not isinstance(item, (tuple, list)) or len(item) != 2:
                continue
            obs = observation(item[0], now=now, source="route", eta_min=item[1])
            if obs is not None and 0 <= obs["eta_min"] <= max(horizon, 24 * 60.0):
                along.append(obs)

    best: dict[str, dict] = {}
    for obs in here + along:
        for kind, rule in _RULES:
            if not cfg.enabled(kind):
                continue
            cand = rule(obs, cfg, now)
            if cand is not None and _better(cand, best.get(kind)):
                best[kind] = cand
    if cfg.enabled("icing"):
        cand = _crossing(here, recent_rain, now, cur)
        if cand is not None and _better(cand, best.get("icing")):
            best["icing"] = cand
    return sorted(best.values(),
                  key=lambda a: (-RANK[a["severity"]], KINDS.index(a["kind"])))


def rain_now(current: Any) -> bool:
    """Whether ``weather.current`` says it is raining / drizzling now
    (the runtime remembers the time for the 0 °C crossing rule)."""
    obs = observation(current, now=time.time(), source="current") \
        if isinstance(current, dict) else None
    return bool(obs and _liquid(obs))


# ── what to announce ───────────────────────────────────────────────────

class AlertAnnouncer:
    """Dedupe of announcements per kind.

    An alert is announced (toast, and voice when allowed) when its kind was
    not announced within ``cooldown_min``, or when it ESCALATED above the
    severity announced last — never just because the same warning is still
    active or came back. A de-escalation is silent; the remembered severity
    stays until the cooldown runs out, so info ↔ warning flapping on the
    15-minute poll does not repeat the warning. ``clock`` is monotonic: the
    wall clock may jump when bcm-timesync corrects it.
    """

    def __init__(self, cfg: AlertConfig, clock: Callable[[], float] = time.monotonic):
        self._cfg = cfg
        self._clock = clock
        self._state: dict[str, tuple[int, float]] = {}   # kind -> (rank, announced_at)

    def due(self, alerts: Iterable[dict]) -> list[dict]:
        """The alerts to announce now (and remember them as announced)."""
        now = self._clock()
        cooldown = self._cfg.cooldown_min * 60.0
        out = []
        for alert in alerts:
            kind, sev = alert.get("kind"), alert.get("severity")
            if kind not in KINDS or sev not in RANK:
                continue
            rank = RANK[sev]
            prev = self._state.get(kind)
            if prev is None or now - prev[1] >= cooldown or now < prev[1] or rank > prev[0]:
                self._state[kind] = (rank, now)
                out.append(alert)
        return out

    def speak(self, alert: dict, minute_of_day: int) -> bool:
        """Whether this announced alert is also spoken: voice on, severity
        ≥ ``voice_min_severity``, and outside the quiet hours — except a
        danger, which is spoken even then (black ice at 3 a.m. matters)."""
        if not self._cfg.voice:
            return False
        sev = alert.get("severity")
        if sev not in RANK or RANK[sev] < RANK[self._cfg.voice_min_severity]:
            return False
        if sev == "danger":
            return True
        return not in_quiet_hours(self._cfg.quiet_hours, minute_of_day)
