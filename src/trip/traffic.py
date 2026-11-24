"""TomTom traffic incidents while driving — the pure part (no threads, no bus).

Used by the runtime in :mod:`src.trip.traffic_alerts`. Everything here is a
function of its arguments (plus an injectable clock / file path), so the
geometry, the filters, the dedupe and the daily budget are unit-testable
without the network.

* **Geometry** — :func:`box_ahead` (a rectangle in front of the car, turned
  with its heading) and :func:`route_corridor` (the next ``lookahead_km`` of
  the planned route); both give the ``(min_lat, min_lon, max_lat, max_lon)``
  box TomTom's ``incidentDetails`` takes (at most 10 000 km², checked).
* **Parsing** — :func:`parse_incidents` reads ``incidentDetails`` v5 answers
  field by field. The answer comes from the network: every field is
  type-, range- and length-checked, texts are cleaned, unknown categories
  are dropped, the list is capped.
* **Filtering** — :func:`select_ahead`: only what is in front of the car
  (bearing within ±60° of the heading, closer than ``lookahead_km``) or on
  the route ahead, never the other carriageway (a line incident whose
  direction is opposite to ours).
* **Announcements** — :class:`IncidentAnnouncer`: only new incidents (by
  id) and escalations, at most one every :data:`MIN_ANNOUNCE_GAP_S`.
* **Budget** — :class:`DailyBudget`: a hard per-day request counter
  persisted on disk (the free TomTom key allows about 2500 requests a day,
  shared with the route planner and the Settings test).
* **Backoff** — :class:`Backoff` after errors, longer after 429 / bad key.
* **Text** — :func:`speech_text` / :func:`notification_texts`: short Polish
  sentences, written to be read aloud ("za 3 kilometry", "około 10 minut").
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from src.core.notifications import clean_text

EARTH_R_KM = 6371.0

#: TomTom refuses a bbox larger than this (incidentDetails v5).
MAX_BBOX_KM2 = 10_000.0
#: Half of the box's width (3 km across) and how far it reaches behind the
#: car (GPS jitter at the moment of the request).
HALF_WIDTH_KM = 1.5
BEHIND_KM = 0.5
#: "In front of the car": the bearing to the incident within this many
#: degrees of the heading.
AHEAD_ANGLE_DEG = 60.0
#: Closer than this the bearing is noise (GPS jitter of a few metres turns
#: it around): accept anything not clearly behind (±90°).
NEAR_KM = 0.3
#: An incident this close to the route ahead is "on the route".
ON_ROUTE_KM = 0.25
#: The car farther than this from the planned route: it left it (detour,
#: old plan) — fall back to the box ahead.
OFF_ROUTE_KM = 2.0
#: A line incident whose direction differs from ours by more than this is on
#: the other carriageway (motorway carriageways are ~30 m apart).
OPPOSITE_DEG = 100.0
#: Never announce more often than this, whatever arrives.
MIN_ANNOUNCE_GAP_S = 120.0
#: Forget an incident not seen for this long (it can be announced again).
FORGET_S = 3600.0
#: Caps on what an answer may make us hold.
MAX_INCIDENTS = 200
MAX_POINTS = 500
MAX_ROUTE_POINTS = 20_000

#: incidentDetails ``iconCategory`` → (kind slug, Polish noun read aloud,
#: notification title). The filter asks for 0, 1 and 6–11 only (the same
#: as RoutePlanner) — anything else in an answer is ignored.
CATEGORIES: dict[int, tuple[str, str, str]] = {
    0: ("other", "utrudnienie", "Utrudnienie"),
    1: ("accident", "wypadek", "Wypadek"),
    6: ("jam", "korek", "Korek"),
    7: ("lane", "zwężenie", "Zwężenie"),
    8: ("closed", "droga zamknięta", "Droga zamknięta"),
    9: ("works", "roboty drogowe", "Roboty drogowe"),
    10: ("wind", "silny wiatr", "Silny wiatr"),
    11: ("flood", "zalana droga", "Zalana droga"),
}
CATEGORY_FILTER = "0,1,6,7,8,9,10,11"
#: Announced whatever the delay (TomTom often gives no delay for them).
ALWAYS_ANNOUNCE = (1, 8)
#: magnitudeOfDelay: 0 unknown, 1 minor, 2 moderate, 3 major,
#: 4 undefined (closures). Closures rank as major for escalation.
MAGNITUDES = (0, 1, 2, 3, 4)
#: Fields asked from TomTom — only what the parser reads.
FIELDS = ("{incidents{type,geometry{type,coordinates},properties{id,iconCategory,"
          "magnitudeOfDelay,events{description,code,iconCategory},from,to,length,"
          "delay,roadNumbers}}}")

_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_ROAD_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 /.-]{0,11}$")
_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
#: A budget file dated at most this many days ahead of the clock is trusted
#: (the clock went back); farther ahead it is ignored.
MAX_FUTURE_DAYS = 3


# ── numbers and config ──────────────────────────────────────────────────

def _num(value: Any, lo: float = -math.inf, hi: float = math.inf) -> Optional[float]:
    """A finite number within [lo, hi], else None (bools are not numbers)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        value = float(value)
    except (OverflowError, ValueError):
        return None
    return value if math.isfinite(value) and lo <= value <= hi else None


def valid_point(lat: Any, lon: Any) -> Optional[tuple[float, float]]:
    """(lat, lon) when both are finite and in range, and not 0,0 (no fix)."""
    la, lo = _num(lat, -90.0, 90.0), _num(lon, -180.0, 180.0)
    if la is None or lo is None or (la == 0.0 and lo == 0.0):
        return None
    return la, lo


@dataclass(frozen=True)
class TrafficConfig:
    poll_min: float = 5.0
    daily_budget: int = 300
    lookahead_km: float = 10.0
    min_delay_s: float = 180.0
    voice: bool = True


#: key → (default, min, max). poll_min ≥ 2: at 2 min and 8 h of driving a
#: day that is 240 requests — inside the default budget of 300.
_NUMERIC = {
    "poll_min": (5.0, 2.0, 60.0),
    "daily_budget": (300, 1, 2500),
    "lookahead_km": (10.0, 2.0, 50.0),
    "min_delay_s": (180.0, 0.0, 3600.0),
}


def load_config(raw: Any, warn: Optional[Callable[[str], None]] = None) -> TrafficConfig:
    """``traffic_alerts`` from the config → :class:`TrafficConfig`. A wrong
    value is replaced by the default and reported once through ``warn``."""
    raw = raw if isinstance(raw, dict) else {}
    say = warn or (lambda _msg: None)
    out: dict[str, Any] = {}
    for key, (default, lo, hi) in _NUMERIC.items():
        if key not in raw or raw[key] is None:
            out[key] = default
            continue
        value = _num(raw[key], lo, hi)
        if value is None:
            say(f"traffic_alerts.{key}={raw[key]!r:.40} poza zakresem {lo:g}..{hi:g} — biorę {default:g}")
            value = default
        out[key] = value
    out["daily_budget"] = int(out["daily_budget"])
    return TrafficConfig(voice=raw.get("voice", True) is not False, **out)


# ── geometry ────────────────────────────────────────────────────────────

def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + \
        math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_R_KM * math.asin(min(1.0, math.sqrt(h)))


def bearing_deg(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Initial bearing a → b, 0 = north, clockwise, [0, 360)."""
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    dlon = math.radians(b[1] - a[1])
    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return math.degrees(math.atan2(y, x)) % 360.0


def angle_diff(a: float, b: float) -> float:
    """Smallest difference between two bearings, [0, 180]."""
    d = abs(a - b) % 360.0
    return 360.0 - d if d > 180.0 else d


def destination(origin: tuple[float, float], bearing: float, km: float) -> tuple[float, float]:
    """The point ``km`` from ``origin`` along ``bearing`` (great circle)."""
    lat1, lon1 = math.radians(origin[0]), math.radians(origin[1])
    brg, d = math.radians(bearing), km / EARTH_R_KM
    lat2 = math.asin(math.sin(lat1) * math.cos(d) + math.cos(lat1) * math.sin(d) * math.cos(brg))
    lon2 = lon1 + math.atan2(math.sin(brg) * math.sin(d) * math.cos(lat1),
                             math.cos(d) - math.sin(lat1) * math.sin(lat2))
    return math.degrees(lat2), (math.degrees(lon2) + 540.0) % 360.0 - 180.0


def bbox_of(points: Iterable[tuple[float, float]], margin_km: float = 0.0
            ) -> Optional[tuple[float, float, float, float]]:
    """``(min_lat, min_lon, max_lat, max_lon)`` of the points, grown by
    ``margin_km`` on every side; None for no points."""
    pts = list(points)
    if not pts:
        return None
    min_lat, max_lat = min(p[0] for p in pts), max(p[0] for p in pts)
    min_lon, max_lon = min(p[1] for p in pts), max(p[1] for p in pts)
    dlat = margin_km / 111.32
    coslat = max(0.01, math.cos(math.radians(max(abs(min_lat), abs(max_lat)))))
    dlon = margin_km / (111.32 * coslat)
    return (max(-90.0, min_lat - dlat), max(-180.0, min_lon - dlon),
            min(90.0, max_lat + dlat), min(180.0, max_lon + dlon))


def bbox_area_km2(bbox: tuple[float, float, float, float]) -> float:
    min_lat, min_lon, max_lat, max_lon = bbox
    mid = math.radians((min_lat + max_lat) / 2)
    return (max_lat - min_lat) * 111.32 * (max_lon - min_lon) * 111.32 * math.cos(mid)


def box_ahead(pos: tuple[float, float], heading: float, ahead_km: float,
              half_width_km: float = HALF_WIDTH_KM,
              behind_km: float = BEHIND_KM) -> tuple[float, float, float, float]:
    """The axis-aligned box around a rectangle ``ahead_km`` long and
    ``2 × half_width_km`` wide in front of the car, turned with its heading
    (from ``behind_km`` behind it). Going north-east the box is larger than
    the rectangle — the ahead-filter removes what is beside the road."""
    back = destination(pos, (heading + 180.0) % 360.0, behind_km)
    front = destination(pos, heading, ahead_km)
    corners = []
    for end in (back, front):
        for side in (-90.0, 90.0):
            corners.append(destination(end, (heading + side) % 360.0, half_width_km))
    return bbox_of(corners)  # type: ignore[return-value]


def clean_route(geometry: Any) -> list[tuple[float, float]]:
    """``trip.route`` geometry ([(lat, lon), …]) with invalid points dropped
    (the bus may carry anything), capped at :data:`MAX_ROUTE_POINTS`."""
    if not isinstance(geometry, (list, tuple)):
        return []
    out = []
    for p in geometry[:MAX_ROUTE_POINTS]:
        if isinstance(p, (list, tuple)) and len(p) >= 2:
            pt = valid_point(p[0], p[1])
            if pt is not None:
                out.append(pt)
    return out


def route_ahead(route: list[tuple[float, float]], pos: tuple[float, float],
                ahead_km: float) -> Optional[list[tuple[float, float, float]]]:
    """The part of the route in front of the car, up to ``ahead_km`` along
    it, as ``(lat, lon, km_from_car)``. None when the car is more than
    :data:`OFF_ROUTE_KM` from every route SEGMENT (it left the route) or the
    route is too short.

    The car is projected onto the nearest segment (not the nearest vertex):
    on a straight motorway the vertices can be kilometres apart, and starting
    at a vertex behind the car would announce an incident the car already
    passed, while a car between two far vertices would look "off route".
    Anything behind the projection is simply not part of the result."""
    if len(route) < 2 or ahead_km <= 0:
        return None
    best_d, best_i, best_t = math.inf, 1, 0.0
    for i in range(1, len(route)):
        d, t = _point_segment_km(pos, route[i - 1], route[i])
        if d < best_d:
            best_d, best_i, best_t = d, i, t
    if best_d > OFF_ROUTE_KM:
        return None
    a, b = route[best_i - 1], route[best_i]
    # Interpolated in lat/lon — fine at the scale of one segment.
    proj = (a[0] + best_t * (b[0] - a[0]), a[1] + best_t * (b[1] - a[1]))
    out = [(proj[0], proj[1], 0.0)]
    prev, along = proj, 0.0
    for i in range(best_i, len(route)):
        seg = haversine_km(prev, route[i])
        if seg <= 0.0:
            prev = route[i]
            continue  # the projection sits on this vertex (t == 1)
        if along + seg >= ahead_km:
            # Cut the last segment at exactly ahead_km: one long segment
            # (a sparse polyline) must not stretch the corridor box.
            f = (ahead_km - along) / seg
            out.append((prev[0] + f * (route[i][0] - prev[0]),
                        prev[1] + f * (route[i][1] - prev[1]), ahead_km))
            break
        along += seg
        out.append((route[i][0], route[i][1], along))
        prev = route[i]
    return out if len(out) >= 2 else None


def route_corridor(ahead: list[tuple[float, float, float]],
                   half_width_km: float = HALF_WIDTH_KM
                   ) -> Optional[tuple[float, float, float, float]]:
    return bbox_of(((p[0], p[1]) for p in ahead), half_width_km)


def _point_segment_km(p: tuple[float, float], a: tuple[float, float],
                      b: tuple[float, float]) -> tuple[float, float]:
    """(distance from p to segment a–b, fraction along it), on a local flat
    projection — good to metres over the few-km segments of a route."""
    coslat = math.cos(math.radians(p[0]))
    ax, ay = (a[1] - p[1]) * 111.32 * coslat, (a[0] - p[0]) * 111.32
    bx, by = (b[1] - p[1]) * 111.32 * coslat, (b[0] - p[0]) * 111.32
    dx, dy = bx - ax, by - ay
    seg2 = dx * dx + dy * dy
    t = 0.0 if seg2 == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / seg2))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(cx, cy), t


def locate_on_route(point: tuple[float, float], ahead: list[tuple[float, float, float]]
                    ) -> Optional[tuple[float, float, float]]:
    """``(distance from the route, km along it from the car, route bearing
    there)`` for the nearest segment of the route ahead, or None."""
    best = None
    for i in range(1, len(ahead)):
        a, b = (ahead[i - 1][0], ahead[i - 1][1]), (ahead[i][0], ahead[i][1])
        d, t = _point_segment_km(point, a, b)
        if best is None or d < best[0]:
            along = ahead[i - 1][2] + t * (ahead[i][2] - ahead[i - 1][2])
            best = (d, along, bearing_deg(a, b) if a != b else None)
    if best is None or best[2] is None:
        return None
    return best  # type: ignore[return-value]


# ── parsing ─────────────────────────────────────────────────────────────

def incident_key(incident_id: str) -> str:
    """A short, safe key for notifications and voice (``traffic_<hash>``):
    TomTom ids are long and not ours to put into keys verbatim."""
    return "traffic_" + hashlib.sha1(incident_id.encode("utf-8")).hexdigest()[:16]


def _coords(geometry: Any) -> list[tuple[float, float]]:
    """GeoJSON Point / LineString coordinates ([lon, lat]) → [(lat, lon)]."""
    if not isinstance(geometry, dict):
        return []
    kind, coords = geometry.get("type"), geometry.get("coordinates")
    if kind == "Point":
        coords = [coords]
    elif kind != "LineString":
        return []
    if not isinstance(coords, list):
        return []
    out = []
    for c in coords[:MAX_POINTS]:
        if isinstance(c, (list, tuple)) and len(c) >= 2:
            pt = valid_point(c[1], c[0])
            if pt is not None:
                out.append(pt)
    return out


def _direction(points: list[tuple[float, float]]) -> Optional[float]:
    """Bearing of a line incident from its first point to the first point
    at least 50 m away (traffic direction); None for a point incident."""
    for p in points[1:]:
        if haversine_km(points[0], p) >= 0.05:
            return bearing_deg(points[0], p)
    return None


def parse_incident(raw: Any) -> Optional[dict]:
    """One ``incidents[]`` entry → a normalised incident, or None."""
    if not isinstance(raw, dict):
        return None
    props = raw.get("properties")
    if not isinstance(props, dict):
        return None
    iid = props.get("id")
    if not isinstance(iid, str) or not _ID_RE.match(iid):
        return None
    cat = props.get("iconCategory")
    if isinstance(cat, bool) or not isinstance(cat, int) or cat not in CATEGORIES:
        return None
    points = _coords(raw.get("geometry"))
    if not points:
        return None
    mag = props.get("magnitudeOfDelay")
    mag = mag if isinstance(mag, int) and not isinstance(mag, bool) and mag in MAGNITUDES else 0
    delay = _num(props.get("delay"), 0, 86_400)
    length = _num(props.get("length"), 0, 1_000_000)
    roads = props.get("roadNumbers")
    roads = [r.strip() for r in roads[:5] if isinstance(r, str) and _ROAD_RE.match(r.strip())] \
        if isinstance(roads, list) else []
    events = props.get("events")
    desc = ""
    if isinstance(events, list):
        for e in events[:5]:
            if isinstance(e, dict) and isinstance(e.get("description"), str):
                desc = clean_text(e["description"], 100)
                if desc:
                    break
    kind = CATEGORIES[cat][0]
    return {
        "id": iid,
        "key": incident_key(iid),
        "category": cat,
        "kind": kind,
        "magnitude": mag,
        "delay_s": int(delay) if delay is not None else None,
        "length_m": int(length) if length is not None else None,
        "from": clean_text(props.get("from"), 60) if isinstance(props.get("from"), str) else "",
        "to": clean_text(props.get("to"), 60) if isinstance(props.get("to"), str) else "",
        "roads": roads[:3],
        "description": desc,
        "lat": points[0][0],
        "lon": points[0][1],
        "dir_deg": _direction(points),
    }


def parse_incidents(data: Any) -> Optional[list[dict]]:
    """An ``incidentDetails`` answer → incidents (at most
    :data:`MAX_INCIDENTS`, duplicates by id dropped). None when the answer
    is not the expected shape at all (counts as a bad response)."""
    if not isinstance(data, dict) or not isinstance(data.get("incidents"), list):
        return None
    out, seen = [], set()
    for raw in data["incidents"][: MAX_INCIDENTS * 2]:
        inc = parse_incident(raw)
        if inc is None or inc["id"] in seen:
            continue
        seen.add(inc["id"])
        out.append(inc)
        if len(out) >= MAX_INCIDENTS:
            break
    return out


# ── filtering ───────────────────────────────────────────────────────────

def _opposite(inc: dict, our_bearing: Optional[float]) -> bool:
    d = inc.get("dir_deg")
    return d is not None and our_bearing is not None and angle_diff(d, our_bearing) > OPPOSITE_DEG


def select_ahead(incidents: Iterable[dict], pos: tuple[float, float], heading: Optional[float],
                 lookahead_km: float,
                 route: Optional[list[tuple[float, float, float]]] = None) -> list[dict]:
    """The incidents in front of the car, each a copy with ``distance_km``
    and ``on_route``; nearest first.

    With ``route`` (from :func:`route_ahead`): only an incident within
    :data:`ON_ROUTE_KM` of the route ahead is kept, its distance measured
    along the route. Without a route: bearing
    from the car within ±:data:`AHEAD_ANGLE_DEG` of the heading and closer
    than ``lookahead_km``. A line incident running the other way is on the
    other carriageway and never kept."""
    out = []
    for inc in incidents:
        point = (inc["lat"], inc["lon"])
        straight = haversine_km(pos, point)
        if route:
            # The corridor's box also holds crossing and parallel roads:
            # with a route only what lies ON it counts.
            loc = locate_on_route(point, route)
            if loc is not None and loc[0] <= ON_ROUTE_KM and 0.0 <= loc[1] <= lookahead_km \
                    and not _opposite(inc, loc[2]):
                out.append(dict(inc, distance_km=round(loc[1], 2), on_route=True))
            continue
        if heading is None or straight > lookahead_km or _opposite(inc, heading):
            continue
        diff = angle_diff(bearing_deg(pos, point), heading)
        limit = 90.0 if straight < NEAR_KM else AHEAD_ANGLE_DEG
        if diff <= limit:
            out.append(dict(inc, distance_km=round(straight, 2), on_route=False))
    out.sort(key=lambda i: i["distance_km"])
    return out


def worth_announcing(inc: dict, min_delay_s: float) -> bool:
    """Accidents and closures always; the rest when the delay is at least
    ``min_delay_s`` or TomTom calls it major."""
    if inc.get("category") in ALWAYS_ANNOUNCE:
        return True
    delay = inc.get("delay_s")
    return (delay is not None and delay >= max(1.0, min_delay_s)) or inc.get("magnitude") == 3


def _level(inc: dict) -> int:
    """Escalation rank: closures and accidents high, then magnitude."""
    if inc.get("category") == 8:
        return 5
    if inc.get("category") == 1:
        return max(4, int(inc.get("magnitude") or 0))
    mag = int(inc.get("magnitude") or 0)
    return 3 if mag == 4 else mag


class IncidentAnnouncer:
    """New incidents (by id) and escalations, at most one announcement per
    :data:`MIN_ANNOUNCE_GAP_S`.

    An escalation is a higher rank (e.g. a jam that became major, a lane
    closure that became a closure) or a delay that grew by at least 5 min
    and by half. Incidents not announced because of the gap stay pending:
    the next call (the runtime re-filters every few seconds) picks the
    nearest still ahead. ``clock`` is monotonic."""

    def __init__(self, min_delay_s: float, clock: Callable[[], float] = time.monotonic,
                 gap_s: float = MIN_ANNOUNCE_GAP_S):
        self._min_delay = min_delay_s
        self._clock = clock
        self._gap = gap_s
        self._last_at: Optional[float] = None
        self._state: dict[str, dict] = {}   # id -> {level, delay, seen}

    def _escalated(self, inc: dict, prev: dict) -> bool:
        if _level(inc) > prev["level"]:
            return True
        delay, before = inc.get("delay_s"), prev.get("delay")
        return delay is not None and before is not None and \
            delay - before >= 300 and delay >= before * 1.5

    def due(self, ahead: list[dict]) -> Optional[tuple[dict, bool]]:
        """``(incident, escalation)`` to announce now, or None. ``ahead`` is
        nearest first (:func:`select_ahead`)."""
        now = self._clock()
        for inc in ahead:
            prev = self._state.get(inc["id"])
            if prev is not None:
                prev["seen"] = now
        for iid in [k for k, v in self._state.items() if not 0 <= now - v["seen"] <= FORGET_S]:
            del self._state[iid]
        if self._last_at is not None and 0 <= now - self._last_at < self._gap:
            return None
        for inc in ahead:
            if not worth_announcing(inc, self._min_delay):
                continue
            prev = self._state.get(inc["id"])
            if prev is not None and not self._escalated(inc, prev):
                continue
            self._state[inc["id"]] = {"level": _level(inc), "delay": inc.get("delay_s"),
                                      "seen": now}
            self._last_at = now
            return inc, prev is not None
        return None


# ── budget and backoff ──────────────────────────────────────────────────

class DailyBudget:
    """A hard cap on TomTom requests per UTC day (the key's quota resets
    by UTC), persisted so a restart — or a power cut — does not reset it.

    The counter is taken BEFORE a request (a failed request may still count
    at TomTom). A corrupt or foreign file is treated as "nothing used today"
    and rewritten; a write failure keeps the count in memory."""

    def __init__(self, path: Any, limit: int, *, wall: Callable[[], float] = time.time,
                 warn: Optional[Callable[[str], None]] = None):
        self._path = Path(path) if path else None
        self.limit = int(limit)
        self._wall = wall
        self._warn = warn or (lambda _m: None)
        self._day = ""
        self.used = 0
        self._load()

    def _today(self) -> str:
        return time.strftime("%Y-%m-%d", time.gmtime(self._wall()))

    def _load(self) -> None:
        self._day = self._today()
        if self._path is None:
            return
        try:
            if not self._path.is_file():
                return
            with open(self._path, "rb") as f:
                raw = f.read(4097)
            data = json.loads(raw.decode("utf-8")) if len(raw) <= 4096 else None
        except (OSError, ValueError, UnicodeDecodeError):
            data = None
            self._warn("traffic_alerts: uszkodzony plik licznika zapytań — liczę od zera")
        if not isinstance(data, dict):
            return
        day, used = data.get("day"), data.get("used")
        # A stored day later than today means the clock went back (or the
        # RTC is wrong at boot): keep that day and its count rather than
        # starting a fresh budget; _rollover resets once the clock passes it.
        # More than MAX_FUTURE_DAYS ahead is an RTC that was far off when the
        # file was written: ignore it, or the budget would be stuck at that
        # count until the far date.
        if isinstance(day, str) and _DAY_RE.match(day) and \
                self._day <= day <= self._day_plus(MAX_FUTURE_DAYS) and \
                isinstance(used, int) and not isinstance(used, bool) and 0 <= used <= 1_000_000:
            self._day, self.used = day, used

    def _day_plus(self, days: int) -> str:
        return time.strftime("%Y-%m-%d", time.gmtime(self._wall() + days * 86400))

    def _rollover(self) -> None:
        today = self._today()
        # Only a LATER day resets the counter (YYYY-MM-DD compares as text).
        # A clock jumping back (wrong RTC at boot, corrected later) must not
        # hand out another full budget: keep the later day and its count.
        # A stored day far in the future (clock was far off, now fixed)
        # resets as well, or the budget would be stuck until that date.
        if today > self._day or self._day > self._day_plus(MAX_FUTURE_DAYS):
            self._day, self.used = today, 0

    def remaining(self) -> int:
        self._rollover()
        return max(0, self.limit - self.used)

    def try_consume(self) -> bool:
        """Take one request from today's budget; False when none is left."""
        self._rollover()
        if self.used >= self.limit:
            return False
        self.used += 1
        self._save()
        return True

    def _save(self) -> None:
        if self._path is None:
            return
        from src.core.fsutil import atomic_write_text
        try:
            atomic_write_text(self._path, json.dumps({"day": self._day, "used": self.used}),
                              mode=0o600)
        except OSError as e:
            self._warn(f"traffic_alerts: nie zapisuję licznika zapytań ({type(e).__name__})")


class Backoff:
    """Pause after failed requests: 1 min doubling up to 30 min; a 429
    (quota) at least 15 min doubling up to 2 h; 401/403 (bad key) 1 h."""

    BASE_S, MAX_S = 60.0, 1800.0
    LIMIT_BASE_S, LIMIT_MAX_S = 900.0, 7200.0
    AUTH_S = 3600.0

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self.failures = 0
        self.until: Optional[float] = None

    def active(self) -> bool:
        if self.until is None:
            return False
        now = self._clock()
        # A monotonic clock never goes back; guard anyway (tests, suspend).
        return now < self.until and self.until - now <= self.LIMIT_MAX_S

    def remaining_s(self) -> float:
        return max(0.0, self.until - self._clock()) if self.active() else 0.0

    def success(self) -> None:
        self.failures, self.until = 0, None

    def failure(self, http_code: Optional[int] = None) -> float:
        """Record one failure; returns the pause in seconds."""
        self.failures += 1
        n = min(self.failures - 1, 10)
        if http_code == 429:
            pause = min(self.LIMIT_MAX_S, self.LIMIT_BASE_S * 2 ** n)
        elif http_code in (401, 403):
            pause = self.AUTH_S
        else:
            pause = min(self.MAX_S, self.BASE_S * 2 ** n)
        self.until = self._clock() + pause
        return pause


# ── text ────────────────────────────────────────────────────────────────

def _plural(n: int, one: str, few: str, many: str) -> str:
    """Polish plural: 1 → one, 2–4 (not 12–14) → few, else many."""
    if n == 1:
        return one
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return few
    return many


def distance_words(km: float) -> str:
    """"za 3 kilometry" / "za 500 metrów" / "za kilometr" (read aloud)."""
    if km < 0.95:
        m = max(100, int(round(km * 10)) * 100)
        return f"za {m} metrów"
    n = int(round(km))
    if n == 1:
        return "za kilometr"
    return f"za {n} {_plural(n, 'kilometr', 'kilometry', 'kilometrów')}"


def delay_words(delay_s: Optional[int]) -> str:
    """"opóźnienie około 10 minut" ('' under a minute or unknown)."""
    if delay_s is None or delay_s < 60:
        return ""
    minutes = int(round(delay_s / 60.0))
    if minutes >= 60:
        hours = int(round(minutes / 60.0))
        return "opóźnienie około godziny" if hours == 1 else f"opóźnienie około {hours} godzin"
    if minutes == 1:
        return "opóźnienie około minuty"
    return f"opóźnienie około {minutes} minut"


def speech_text(inc: dict, escalation: bool = False) -> str:
    """One sentence to read aloud, e.g. "Uwaga, korek za 3 kilometry na
    drodze S8, opóźnienie około 10 minut." """
    noun = CATEGORIES.get(inc.get("category"), CATEGORIES[0])[1]
    parts = [f"{'Aktualizacja' if escalation else 'Uwaga'}, {noun} "
             f"{distance_words(float(inc.get('distance_km') or 0.0))}"]
    if inc.get("roads"):
        parts[0] += f" na drodze {inc['roads'][0]}"
    delay = delay_words(inc.get("delay_s"))
    if delay:
        parts.append(delay)
    return ", ".join(parts) + "."


def _km_short(km: float) -> str:
    if km < 0.95:
        return f"{max(100, int(round(km * 10)) * 100)} m"
    return f"{km:.0f} km" if km >= 10 else f"{km:.1f} km".replace(".", ",")


def notification_texts(inc: dict) -> tuple[str, str]:
    """(title, description) for the toast and the lists: "Korek za 3,2 km",
    "S8 · opóźnienie ok. 10 min · Gdańsk → Elbląg"."""
    title = CATEGORIES.get(inc.get("category"), CATEGORIES[0])[2]
    title = f"{title} za {_km_short(float(inc.get('distance_km') or 0.0))}"
    bits = []
    if inc.get("roads"):
        bits.append(", ".join(inc["roads"]))
    delay = inc.get("delay_s")
    if isinstance(delay, int) and delay >= 60:
        bits.append(f"opóźnienie ok. {int(round(delay / 60.0))} min")
    length = inc.get("length_m")
    if isinstance(length, int) and length >= 100:
        bits.append(f"długość {_km_short(length / 1000.0)}")
    if inc.get("from") and inc.get("to"):
        bits.append(f"{inc['from']} → {inc['to']}")
    elif inc.get("description"):
        bits.append(inc["description"])
    return clean_text(title, 60), clean_text(" · ".join(bits), 200)
