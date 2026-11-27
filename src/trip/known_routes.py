"""Known routes: which past trip is the car repeating right now?

Traffic warnings without a destination look at a box in front of the car,
and that box also holds roads the driver is not going to take. Most trips
in a car are repeats (home → work, work → home, the shop …), and the
tracker (``src/location/tracker.py``) already keeps every trip in SQLite.
This module:

* loads the recent trips from that database (read-only, thinned to a point
  every :data:`SAMPLE_KM`), both directions of each;
* compares the last few kilometres the car has driven (``trace``) with each
  of them: a past trip matches when nearly every trace point lies within
  :data:`MATCH_KM` of it and the car moves along it the same way;
* returns the matching past trips, so the caller can treat "the rest of
  that trip" like a planned route (only incidents ON it count).

Pure functions plus a small loader; no threads, no bus. The database is
opened with ``mode=ro`` — this module never writes the tracker's file.
"""

from __future__ import annotations

import math
import os
import sqlite3
from typing import Iterable, Optional

from src.trip import traffic as engine

#: Thin every trip (and the live trace) to one point per this distance.
SAMPLE_KM = 0.1
#: A trace point this close to a past trip lies "on" it (GPS error + the
#: other carriageway + a different lane on a roundabout).
MATCH_KM = 0.15
#: This share of the trace points must lie on the past trip.
MATCH_SHARE = 0.85
#: The trace must cover at least this much road before anything matches
#: (the first kilometre out of the garage is the same for every trip).
MIN_TRACE_KM = 2.0
#: Only the last this-many km of the trace are compared (an old detour
#: must not stop a match for the rest of the trip).
TRACE_KM = 4.0
#: Trips shorter than this are not worth learning.
MIN_TRIP_KM = 3.0
#: How many recent trips are loaded, and caps on what they may cost.
MAX_TRIPS = 80
MAX_POINTS_PER_TRIP = 3000
#: At most this many matching trips are used (the most recent ones).
MAX_MATCHES = 3


def thin(points: Iterable[tuple[float, float]], step_km: float = SAMPLE_KM
         ) -> list[tuple[float, float]]:
    """Keep a point only when it is ``step_km`` from the last kept one."""
    out: list[tuple[float, float]] = []
    for p in points:
        if not out or engine.haversine_km(out[-1], p) >= step_km:
            out.append(p)
    if len(out) > MAX_POINTS_PER_TRIP:
        stride = math.ceil(len(out) / MAX_POINTS_PER_TRIP)
        out = out[::stride]
    return out


def load_routes(db_path: str, max_trips: int = MAX_TRIPS,
                min_km: float = MIN_TRIP_KM) -> list[list[tuple[float, float]]]:
    """Recent trips from the tracker database as thinned polylines (both
    directions are tried later by :func:`match`). [] when the file is
    missing or unreadable — the caller simply falls back to the box ahead."""
    if not db_path or not os.path.isfile(db_path):
        return []
    uri = "file:" + os.path.abspath(db_path) + "?mode=ro"
    try:
        db = sqlite3.connect(uri, uri=True, timeout=2.0)
    except sqlite3.Error:
        return []
    routes: list[list[tuple[float, float]]] = []
    try:
        trips = db.execute(
            "SELECT id FROM trips WHERE end_ts IS NOT NULL AND distance_km >= ? "
            "ORDER BY id DESC LIMIT ?", (float(min_km), int(max_trips))).fetchall()
        for (trip_id,) in trips:
            rows = db.execute("SELECT lat, lon FROM tracks WHERE trip_id=? ORDER BY ts",
                              (trip_id,)).fetchall()
            pts = [p for p in (engine.valid_point(r[0], r[1]) for r in rows) if p is not None]
            line = thin(pts)
            if len(line) >= 10:
                routes.append(line)
    except sqlite3.Error:
        return routes
    finally:
        db.close()
    return routes


def _nearest(point: tuple[float, float], route: list[tuple[float, float]],
             lo: int = 1, hi: Optional[int] = None) -> tuple[float, int]:
    """(distance km, segment index) of the nearest segment ``lo..hi`` of
    ``route`` (segment i joins points i-1 and i)."""
    best_d, best_i = math.inf, max(1, lo)
    for i in range(max(1, lo), min(len(route), hi if hi is not None else len(route))):
        d, _t = engine._point_segment_km(point, route[i - 1], route[i])
        if d < best_d:
            best_d, best_i = d, i
    return best_d, best_i


def trace_km(trace: list[tuple[float, float]]) -> float:
    return sum(engine.haversine_km(trace[i - 1], trace[i]) for i in range(1, len(trace)))


def recent_trace(trace: list[tuple[float, float]], km: float = TRACE_KM
                 ) -> list[tuple[float, float]]:
    """The tail of ``trace`` covering at most ``km``."""
    out = list(trace)
    total = trace_km(out)
    while len(out) > 2 and total > km:
        total -= engine.haversine_km(out[0], out[1])
        out.pop(0)
    return out


def _window(trace: list[tuple[float, float]], route: list[tuple[float, float]]
            ) -> Optional[tuple[int, int]]:
    """Segment range of ``route`` near the trace (its points inside the
    trace's box, plus one segment each side), or None when the route never
    comes near — keeps matching cheap for 80 trips × thousands of points."""
    box = engine.bbox_of(trace, MATCH_KM + 0.05)
    if box is None:
        return None
    inside = [i for i, p in enumerate(route)
              if box[0] <= p[0] <= box[2] and box[1] <= p[1] <= box[3]]
    if not inside:
        return None
    return max(1, inside[0]), min(len(route), inside[-1] + 2)


def matches(trace: list[tuple[float, float]], route: list[tuple[float, float]]) -> bool:
    """Does the car's recent ``trace`` follow ``route`` in its direction?"""
    if len(trace) < 3 or len(route) < 2:
        return False
    win = _window(trace, route)
    if win is None:
        return False
    on, idx = 0, []
    for p in trace:
        d, i = _nearest(p, route, win[0], win[1])
        if d <= MATCH_KM:
            on += 1
            idx.append(i)
    if on < MATCH_SHARE * len(trace) or len(idx) < 3:
        return False
    # Same direction: the matched segments move forward along the route
    # (a few steps back are GPS noise around a vertex).
    forward = sum(1 for a, b in zip(idx, idx[1:]) if b >= a)
    return idx[-1] > idx[0] and forward >= 0.8 * (len(idx) - 1)


def match(trace: list[tuple[float, float]], routes: list[list[tuple[float, float]]],
          limit: int = MAX_MATCHES) -> list[list[tuple[float, float]]]:
    """The past trips (each in the direction the car drives it) the trace
    follows, most recent first — at most ``limit``. [] until the trace
    covers :data:`MIN_TRACE_KM`."""
    tail = recent_trace(trace)
    if trace_km(tail) < MIN_TRACE_KM:
        return []
    out = []
    for route in routes:
        for cand in (route, route[::-1]):
            if matches(tail, cand):
                out.append(cand)
                break
        if len(out) >= limit:
            break
    return out


def heading_stable(trace: list[tuple[float, float]], heading: Optional[float],
                   km: float = 1.0, max_deg: float = 25.0) -> Optional[bool]:
    """Has the car kept roughly ``heading`` over the last ``km``? (A city
    with turns every few hundred metres: the box ahead is a guess.) None
    while the trace is too short to tell."""
    if heading is None or len(trace) < 2:
        return None
    tail = recent_trace(trace, km)
    if trace_km(tail) < 0.8 * km:
        return None
    return engine.angle_diff(engine.bearing_deg(tail[0], tail[-1]), heading) <= max_deg
