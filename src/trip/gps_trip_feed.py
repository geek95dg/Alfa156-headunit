"""Komputer podróży z GPS (tryb ``--frontend``, bez OBD).

Ekran trasy (A3) czyta ``trip.distance``, ``trip.avg_speed``,
``trip.time_str``, ``trip.avg_consumption`` i ``trip.estimated_range``, ale
w trybie frontend nikt ich nie publikował (TripComputer liczy z OBD, a OBD
w aucie testowym nie ma) — ekran pokazywał same zera. Ten moduł liczy
bieżącą jazdę z ``gps.position``, a spalanie i zasięg bierze z dziennika
tankowań (``fuel.stats``, src/trip/fuel_log.py). Bez dziennika te dwa pola
są ``None`` (ekran pokazuje „—”), a chwilowego spalania bez OBD nie ma
wcale — zmyślona liczba byłaby gorsza niż kreska.

Jazda:
* zaczyna się, gdy prędkość przekroczy ``tracking.trip_start_kmh`` (5 km/h),
  a poprzednia jazda stała dłużej niż :data:`NEW_TRIP_AFTER_S` (postój na
  światłach czy na stacji nie zaczyna nowej jazdy);
* dystans to suma odcinków między pozycjami; odcinek z prędkością
  wynikającą > :data:`MAX_JUMP_KMH` (skok pozycji) albo po przerwie
  > :data:`MAX_GAP_S` (tunel, brak GPS) nie jest liczony, a drobne
  przesunięcia na postoju (dryf GPS) też nie;
* czas to czas od startu jazdy (z krótkimi postojami); po długim postoju
  zatrzymuje się na chwili zaparkowania i jazda czeka na następną;
* średnia prędkość = dystans / czas.

Auto testowe nie ma zasilania buforowanego, więc każde zgaszenie silnika
restartuje BCM — nowa jazda zaczyna się wtedy sama.
"""

from __future__ import annotations

import math
import threading
import time
from typing import Any, Callable, Optional

from src.core.logger import get_logger

log = get_logger("trip.gps_feed")

#: Parked longer than this → the next drive is a new trip.
NEW_TRIP_AFTER_S = 600.0
#: A segment faster than this is a GPS jump, not driving.
MAX_JUMP_KMH = 250.0
#: Positions further apart in time: the path between is unknown.
MAX_GAP_S = 120.0
#: Below the stop speed, moves shorter than this are GPS drift (km).
DRIFT_KM = 0.03
#: trip.* at most this often (positions come at 1–2 Hz).
PUBLISH_EVERY_S = 1.0


def _finite(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        value = float(value)
    except (OverflowError, ValueError):     # 400-digit int from the bus
        return None
    return value if math.isfinite(value) else None


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(min(1.0, math.sqrt(a)))


def format_duration(seconds: float) -> str:
    s = max(0, int(seconds))
    h, rest = divmod(s, 3600)
    m, s = divmod(rest, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


class GpsTripFeed:
    """Publishes the current trip's ``trip.*`` from GPS and ``fuel.stats``."""

    def __init__(self, event_bus, config=None,
                 clock: Callable[[], float] = time.monotonic):
        self.bus = event_bus
        cfg = (lambda k, d: config.get(k, d)) if config is not None else (lambda k, d: d)
        start = _finite(cfg("tracking.trip_start_kmh", 5))
        stop = _finite(cfg("tracking.trip_end_kmh", 2))
        self.start_kmh = start if start is not None and 0 < start < 50 else 5.0
        self.stop_kmh = stop if stop is not None and 0 <= stop < self.start_kmh else 2.0
        self._clock = clock
        self._lock = threading.Lock()
        self._started: Optional[float] = None     # monotonic start of the trip
        self._parked_since: Optional[float] = None
        self._last: Optional[tuple[float, float, float]] = None   # lat, lon, t
        self.distance_km = 0.0
        self._last_publish: Optional[float] = None
        self._l100: Optional[float] = None
        self._range: Optional[float] = None

    def start(self) -> None:
        self.bus.subscribe("gps.position", self._on_position)
        self.bus.subscribe("fuel.stats", self._on_fuel_stats)
        last = self.bus.get_last("fuel.stats")
        if last is not None:
            self._take_fuel(last[0])
        # No OBD in this mode: no instant consumption, never a made-up one.
        self.bus.publish("trip.instant_consumption", None)
        self.bus.publish("trip.fuel_used", None)
        self._publish(force=True)

    def stop(self) -> None:
        self.bus.unsubscribe("gps.position", self._on_position)
        self.bus.unsubscribe("fuel.stats", self._on_fuel_stats)

    # ── inputs ───────────────────────────────────────────────────────────

    def _take_fuel(self, stats: Any) -> None:
        if not isinstance(stats, dict):
            return
        avg = _finite(stats.get("avg_l100_overall"))
        if avg is None:
            avg = _finite(stats.get("avg_l100_last"))
        rng = _finite(stats.get("est_range_km"))
        with self._lock:
            self._l100 = round(avg, 1) if avg is not None and 0 < avg < 100 else None
            self._range = round(rng) if rng is not None and 0 <= rng < 5000 else None

    def _on_fuel_stats(self, topic, value, ts=None) -> None:
        self._take_fuel(value)
        self._publish(force=True)

    def _on_position(self, topic, pos, ts=None) -> None:
        if not isinstance(pos, dict) or pos.get("fix") is False:
            return
        lat, lon = _finite(pos.get("lat")), _finite(pos.get("lon"))
        if lat is None or lon is None or abs(lat) > 90 or abs(lon) > 180 \
                or (lat == 0.0 and lon == 0.0):
            return
        now = self._clock()
        speed = _finite(pos.get("speed"))
        with self._lock:
            seg_km, implied = 0.0, None
            if self._last is not None:
                dt = now - self._last[2]
                if dt > 0:
                    seg_km = _haversine_km(self._last[0], self._last[1], lat, lon)
                    implied = seg_km / (dt / 3600.0)
                    if dt > MAX_GAP_S or implied > MAX_JUMP_KMH:
                        seg_km = 0.0
                else:
                    seg_km = 0.0
            v = speed if speed is not None else implied
            moving = v is not None and v > self.start_kmh
            stopped = v is not None and v <= self.stop_kmh
            if moving:
                if self._started is None or (self._parked_since is not None
                                             and now - self._parked_since >= NEW_TRIP_AFTER_S):
                    self._started = now
                    self.distance_km = 0.0
                    seg_km = 0.0           # the first segment belongs to the stop
                    log.info("Nowa jazda (GPS)")
                self._parked_since = None
            elif stopped and self._started is not None and self._parked_since is None:
                self._parked_since = now
            if self._started is not None and not self._ended(now):
                if not (stopped and seg_km < DRIFT_KM):
                    self.distance_km += seg_km
            self._last = (lat, lon, now)
        self._publish()

    def _ended(self, now: float) -> bool:
        return self._parked_since is not None and now - self._parked_since >= NEW_TRIP_AFTER_S

    # ── output ───────────────────────────────────────────────────────────

    def snapshot(self) -> dict:
        now = self._clock()
        with self._lock:
            if self._started is None:
                elapsed = 0.0
            elif self._ended(now):
                elapsed = self._parked_since - self._started
            else:
                elapsed = now - self._started
            dist = self.distance_km
            avg = dist / (elapsed / 3600.0) if elapsed >= 60 else 0.0
            return {"distance": round(dist, 2), "avg_speed": round(avg, 1),
                    "time_str": format_duration(elapsed),
                    "avg_consumption": self._l100, "estimated_range": self._range}

    def _publish(self, force: bool = False) -> None:
        now = self._clock()
        if not force and self._last_publish is not None \
                and 0 <= now - self._last_publish < PUBLISH_EVERY_S:
            return
        self._last_publish = now
        snap = self.snapshot()
        for key, value in snap.items():
            self.bus.publish(f"trip.{key}", value)
