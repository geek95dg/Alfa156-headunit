"""GPS route tracker — continuous logging to SQLite.

Logs GPS positions from the ``gps.position`` event-bus topic,
auto-detects trip start/stop, computes per-trip statistics and
exports GPX. Enabled via ``modules.tracking`` in the YAML config.

Config keys (block ``tracking:``):
    db_path            — SQLite file (default: data/gps_tracks.db)
    interval_sec       — min seconds between logged points (default 30)
    trip_start_kmh     — speed that opens a trip (default 5)
    trip_end_kmh       — speed treated as "parked" (default 2)
    trip_end_idle_sec  — parked time that closes a trip (default 60)
    no_fix_close_sec   — no GPS position for this long closes the open trip
                         (default 300; the phone left the car, GPS app died)

Power cuts: the car has no buffered supply, every engine stop is a hard
power cut. The database therefore runs in WAL mode with
``synchronous=NORMAL`` — a cut can lose the last second of points but never
corrupts the file — and a trip left open by a cut is closed on the next
start WITH its statistics (end = its last point).

The web viewer reaches the tracker through ``tracking._internals``
(``{"tracker": GPSTracker}``) for the trip list and the GPX download.
"""

import math
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional
from xml.sax.saxutils import escape

from src.core.logger import get_logger

log = get_logger("gps_tracker")

GPX_NS = "http://www.topografix.com/GPX/1/1"
#: list_trips() limit bounds (the web route clamps to the same range).
MAX_LIST_LIMIT = 500
#: How often the no-fix check runs.
TICK_SEC = 10.0
#: SQLite waits this long for a lock instead of failing at once.
BUSY_TIMEOUT_MS = 2000


def _haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _finite(value: Any) -> Optional[float]:
    """``value`` as a finite float, else None (bools are not numbers here)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _dec(value: float, places: int = 7) -> str:
    """Plain decimal for XML (``repr`` would give ``1e-05`` for small values)."""
    text = f"{value:.{places}f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def _iso_utc(ts: Any) -> Optional[str]:
    """Epoch seconds → ``2026-11-08T12:34:56Z`` (None if not a sane time)."""
    ts = _finite(ts)
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (OverflowError, OSError, ValueError):
        return None


class GPSTracker:
    """Continuous GPS logging with trip detection.

    Args:
        event_bus: EventBus (``gps.position`` in, ``tracking.trip_ended`` out).
        config: BCMConfig-like object with a dotted ``get``.
        clock: monotonic seconds — idle/no-fix timing (a wall-clock jump
            from bcm-timesync must not end or stretch a trip).
        wall_clock: epoch seconds stored with every point and trip.
    """

    def __init__(self, event_bus, config=None,
                 clock: Callable[[], float] = time.monotonic,
                 wall_clock: Callable[[], float] = time.time):
        self.bus = event_bus
        cfg = (lambda key, default: config.get(key, default)) if config else (lambda key, default: default)
        self.db_path = cfg("tracking.db_path", "data/gps_tracks.db")
        self.interval_sec = float(cfg("tracking.interval_sec", 30))
        self.trip_start_kmh = float(cfg("tracking.trip_start_kmh", 5))
        self.trip_end_kmh = float(cfg("tracking.trip_end_kmh", 2))
        self.trip_end_idle_sec = float(cfg("tracking.trip_end_idle_sec", 60))
        self.no_fix_close_sec = float(cfg("tracking.no_fix_close_sec", 300))
        self._clock = clock
        self._wall = wall_clock

        self._running = False
        self._lock = threading.Lock()
        self._in_trip = False
        self._trip_id = 0
        self._last_log_ts: Optional[float] = None   # monotonic
        self._idle_since: Optional[float] = None    # monotonic
        self._last_pos_at: Optional[float] = None   # monotonic, any valid position
        self._last_point = None  # (lat, lon)
        self._db_error_logged_at: Optional[float] = None
        self._stop_evt = threading.Event()
        self._tick_thread: Optional[threading.Thread] = None
        self._db = None
        self._init_db()

        self.bus.subscribe("gps.position", self._on_position)

    def _init_db(self):
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        self._db = sqlite3.connect(self.db_path, check_same_thread=False,
                                   timeout=BUSY_TIMEOUT_MS / 1000.0)
        # WAL + synchronous=NORMAL: a hard power cut may drop the newest
        # transactions but leaves a consistent database (the rollback-journal
        # default fsyncs every commit — slow on the car's SSD and no safer
        # against losing the last points).
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        self._db.execute("""CREATE TABLE IF NOT EXISTS tracks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trip_id INTEGER, ts REAL,
            lat REAL, lon REAL, speed REAL, heading REAL, altitude REAL
        )""")
        self._db.execute("""CREATE TABLE IF NOT EXISTS trips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            start_ts REAL, end_ts REAL,
            distance_km REAL, avg_speed REAL, max_speed REAL
        )""")
        self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_tracks_trip ON tracks(trip_id)")
        self._db.commit()
        row = self._db.execute("SELECT MAX(id) FROM trips").fetchone()
        self._trip_id = (row[0] or 0) + 1
        self._close_orphans()

    def _close_orphans(self):
        """Close trips a crash/power cut left open — statistics included.

        Also repairs trips that were closed without statistics (the old
        retro-close only set end_ts and left distance/avg/max NULL).
        """
        rows = self._db.execute(
            "SELECT id, start_ts, end_ts FROM trips"
            " WHERE end_ts IS NULL OR distance_km IS NULL").fetchall()
        for trip_id, start_ts, end_ts in rows:
            stats = self._compute_stats(trip_id)
            if end_ts is None:
                last = self._db.execute(
                    "SELECT MAX(ts) FROM tracks WHERE trip_id=?", (trip_id,)).fetchone()[0]
                end_ts = last if last is not None else start_ts
            self._db.execute(
                "UPDATE trips SET end_ts=?, distance_km=?, avg_speed=?, max_speed=?"
                " WHERE id=?",
                (end_ts, stats.get("distance_km", 0), stats.get("avg_speed", 0),
                 stats.get("max_speed", 0), trip_id))
        if rows:
            self._db.commit()
            log.info("Closed %d trip(s) left open by a power cut / crash", len(rows))

    def _on_position(self, topic, pos, ts=None):
        if not self._running or not isinstance(pos, dict) or pos.get("fix") is False:
            return
        lat, lon = _finite(pos.get("lat")), _finite(pos.get("lon"))
        if lat is None or lon is None or abs(lat) > 90 or abs(lon) > 180:
            return
        with self._lock:
            if self._db is None:
                return
            try:
                self._handle_position(pos, lat, lon)
            except sqlite3.Error as e:
                # One line a minute, not a traceback per point (disk full,
                # locked DB …); the bus would log every single failure.
                now = self._clock()
                if self._db_error_logged_at is None or now - self._db_error_logged_at >= 60:
                    self._db_error_logged_at = now
                    log.warning("GPS tracker: database error: %s", e)

    def _handle_position(self, pos, lat, lon):
        now = self._clock()
        wall = self._wall()
        self._last_pos_at = now
        speed = _finite(pos.get("speed")) or 0.0

        if not self._in_trip and speed > self.trip_start_kmh:
            self._in_trip = True
            self._idle_since = None
            self._last_point = None
            self._last_log_ts = None
            self._db.execute(
                "INSERT INTO trips (id, start_ts) VALUES (?, ?)",
                (self._trip_id, wall))
            self._db.commit()
            log.info("Trip %d started", self._trip_id)

        if not self._in_trip:
            return

        # Log a point at most every interval_sec (always log slow points
        # so the trip-end idle window has fresh data).
        if self._last_log_ts is None or now - self._last_log_ts >= self.interval_sec \
                or speed <= self.trip_end_kmh:
            self._last_log_ts = now
            self._db.execute(
                "INSERT INTO tracks (trip_id, ts, lat, lon, speed, heading, altitude)"
                " VALUES (?,?,?,?,?,?,?)",
                (self._trip_id, wall, lat, lon, speed,
                 _finite(pos.get("heading")), _finite(pos.get("altitude", pos.get("alt")))))
            self._db.commit()
            self._last_point = (lat, lon)

        # Trip end: parked below trip_end_kmh for trip_end_idle_sec
        if speed <= self.trip_end_kmh:
            if self._idle_since is None:
                self._idle_since = now
            elif now - self._idle_since >= self.trip_end_idle_sec:
                self._close_trip(wall)
        else:
            self._idle_since = None

    def _close_trip(self, end_ts):
        stats = self._compute_stats(self._trip_id)
        self._db.execute(
            "UPDATE trips SET end_ts=?, distance_km=?, avg_speed=?, max_speed=?"
            " WHERE id=?",
            (end_ts, stats.get("distance_km", 0), stats.get("avg_speed", 0),
             stats.get("max_speed", 0), self._trip_id))
        self._db.commit()
        log.info("Trip %d ended: %.1f km, avg %.0f km/h, max %.0f km/h",
                 self._trip_id, stats.get("distance_km", 0),
                 stats.get("avg_speed", 0), stats.get("max_speed", 0))
        self.bus.publish("tracking.trip_ended", {"trip_id": self._trip_id, **stats})
        self._in_trip = False
        self._idle_since = None
        self._trip_id += 1

    def tick(self):
        """Close the open trip after ``no_fix_close_sec`` without a position.

        Without this a trip whose GPS went away (phone left in the car with
        the app killed, or taken out while the engine still ran) stayed
        open until the next power cut.
        """
        with self._lock:
            if not self._running or not self._in_trip or self._db is None:
                return
            if self._last_pos_at is None:
                return
            silent = self._clock() - self._last_pos_at
            if silent < self.no_fix_close_sec:
                return
            try:
                last = self._db.execute(
                    "SELECT MAX(ts) FROM tracks WHERE trip_id=?",
                    (self._trip_id,)).fetchone()[0]
                log.info("Trip %d: no GPS position for %.0f s — closing it",
                         self._trip_id, silent)
                # The trip ended when the positions stopped, not now.
                self._close_trip(last if last is not None else self._wall())
            except sqlite3.Error as e:
                log.warning("GPS tracker: closing trip %d failed: %s", self._trip_id, e)

    def _tick_loop(self):
        while not self._stop_evt.wait(TICK_SEC):
            try:
                self.tick()
            except Exception:
                log.exception("GPS tracker tick failed")

    def _compute_stats(self, trip_id):
        rows = self._db.execute(
            "SELECT lat, lon, speed, ts FROM tracks WHERE trip_id=? ORDER BY ts",
            (trip_id,)).fetchall()
        if not rows:
            return {}
        distance = 0.0
        for (lat1, lon1, _, _), (lat2, lon2, _, _) in zip(rows, rows[1:]):
            if None in (lat1, lon1, lat2, lon2):
                continue
            distance += _haversine_km(lat1, lon1, lat2, lon2)
        speeds = [r[2] for r in rows if r[2] is not None]
        return {
            "trip_id": trip_id,
            "points": len(rows),
            "distance_km": round(distance, 3),
            "avg_speed": sum(speeds) / len(speeds) if speeds else 0,
            "max_speed": max(speeds) if speeds else 0,
            "duration_s": rows[-1][3] - rows[0][3] if len(rows) > 1 else 0,
        }

    def get_trip_stats(self, trip_id=None):
        """Get statistics for a trip (or the current one)."""
        with self._lock:
            if self._db is None:
                return {}
            return self._compute_stats(trip_id or self._trip_id)

    @staticmethod
    def _trip_row(r):
        return {"trip_id": r[0], "start_ts": r[1], "end_ts": r[2],
                "distance_km": r[3], "avg_speed": r[4], "max_speed": r[5],
                "points": r[6]}

    _TRIP_SELECT = (
        "SELECT id, start_ts, end_ts, distance_km, avg_speed, max_speed,"
        " (SELECT COUNT(*) FROM tracks WHERE tracks.trip_id = trips.id)"
        " FROM trips")

    def list_trips(self, limit=50):
        """Newest trips first; ``limit`` is clamped to 1..500."""
        try:
            limit = int(limit)
        except (TypeError, ValueError, OverflowError):
            limit = 50
        limit = min(max(limit, 1), MAX_LIST_LIMIT)
        with self._lock:
            if self._db is None:
                return []
            rows = self._db.execute(
                self._TRIP_SELECT + " ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [self._trip_row(r) for r in rows]

    def get_trip(self, trip_id):
        """One trip (same keys as list_trips) or None."""
        with self._lock:
            if self._db is None:
                return None
            row = self._db.execute(self._TRIP_SELECT + " WHERE id=?",
                                   (int(trip_id),)).fetchone()
        return self._trip_row(row) if row else None

    def export_gpx(self, trip_id):
        """Export a trip as a GPX 1.1 document (string).

        Valid against the GPX 1.1 schema: namespace, creator, ``<time>`` in
        ISO-8601 UTC per point. ``<speed>`` is not a GPX 1.1 element (it was
        1.0) and is no longer written; map apps derive it from the times.
        """
        with self._lock:
            if self._db is None:
                rows = []
            else:
                rows = self._db.execute(
                    "SELECT lat, lon, altitude, ts"
                    " FROM tracks WHERE trip_id=? ORDER BY ts",
                    (trip_id,)).fetchall()
        first_ts = next((r[3] for r in rows if _finite(r[3]) is not None), None)
        started = _iso_utc(first_ts)
        label = f"BCM trasa {trip_id}"
        if first_ts is not None:
            try:
                label += time.strftime(" %Y-%m-%d %H:%M", time.localtime(first_ts))
            except (OverflowError, OSError, ValueError):
                pass
        name = escape(label)
        out = ['<?xml version="1.0" encoding="UTF-8"?>',
               f'<gpx version="1.1" creator="BCM" xmlns="{GPX_NS}">',
               "  <metadata>",
               f"    <name>{name}</name>"]
        # metadata/time: when the trip started (what map apps show as the
        # track's date); "now" when the trip has no points.
        out.append(f"    <time>{started or _iso_utc(self._wall())}</time>")
        out += ["  </metadata>", "  <trk>", f"    <name>{name}</name>", "    <trkseg>"]
        for lat, lon, alt, ts in rows:
            lat, lon = _finite(lat), _finite(lon)
            if lat is None or lon is None:
                continue
            point = f'      <trkpt lat="{_dec(lat)}" lon="{_dec(lon)}">'
            alt = _finite(alt)
            if alt is not None:
                point += f"<ele>{alt:.1f}</ele>"
            stamp = _iso_utc(ts)
            if stamp:
                point += f"<time>{stamp}</time>"
            out.append(point + "</trkpt>")
        out += ["    </trkseg>", "  </trk>", "</gpx>", ""]
        return "\n".join(out)

    def start(self):
        self._running = True
        if self._tick_thread is None or not self._tick_thread.is_alive():
            self._stop_evt.clear()
            self._tick_thread = threading.Thread(target=self._tick_loop, daemon=True,
                                                 name="gps-tracker-tick")
            self._tick_thread.start()
        log.info("GPS tracker started (DB: %s, interval %ds, no-fix close %ds)",
                 self.db_path, int(self.interval_sec), int(self.no_fix_close_sec))

    def stop(self):
        self._running = False
        self._stop_evt.set()
        if self._tick_thread is not None:
            self._tick_thread.join(timeout=2)
            self._tick_thread = None
        with self._lock:
            if self._in_trip and self._db is not None:
                self._close_trip(self._wall())
            if self._db:
                self._db.close()
                self._db = None


def start_tracker(config=None, event_bus=None, hal=None, **kwargs):
    tracker = GPSTracker(event_bus, config=config)
    tracker.start()
    # Same pattern as multimedia._internals: the web viewer looks the
    # tracker up here for /trips and the GPX download.
    event_bus.publish("tracking._internals", {"tracker": tracker})
    return tracker
