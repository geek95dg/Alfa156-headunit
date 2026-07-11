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
"""

import math
import os
import sqlite3
import threading
import time

from src.core.logger import get_logger

log = get_logger("gps_tracker")


def _haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class GPSTracker:
    """Continuous GPS logging with trip detection."""

    def __init__(self, event_bus, config=None):
        self.bus = event_bus
        cfg = (lambda key, default: config.get(key, default)) if config else (lambda key, default: default)
        self.db_path = cfg("tracking.db_path", "data/gps_tracks.db")
        self.interval_sec = float(cfg("tracking.interval_sec", 30))
        self.trip_start_kmh = float(cfg("tracking.trip_start_kmh", 5))
        self.trip_end_kmh = float(cfg("tracking.trip_end_kmh", 2))
        self.trip_end_idle_sec = float(cfg("tracking.trip_end_idle_sec", 60))

        self._running = False
        self._lock = threading.Lock()
        self._in_trip = False
        self._trip_id = 0
        self._last_log_ts = 0.0
        self._idle_since = None
        self._last_point = None  # (lat, lon)
        self._db = None
        self._init_db()

        self.bus.subscribe("gps.position", self._on_position)

    def _init_db(self):
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        self._db = sqlite3.connect(self.db_path, check_same_thread=False)
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
        # A trip left open by a crash/power cut is closed retroactively.
        self._db.execute(
            "UPDATE trips SET end_ts = "
            " (SELECT MAX(ts) FROM tracks WHERE tracks.trip_id = trips.id)"
            " WHERE end_ts IS NULL")
        self._db.commit()

    def _on_position(self, topic, pos, ts=None):
        if not self._running or not isinstance(pos, dict):
            return
        with self._lock:
            self._handle_position(pos)

    def _handle_position(self, pos):
        now = time.time()
        speed = float(pos.get("speed", 0) or 0)

        if not self._in_trip and speed > self.trip_start_kmh:
            self._in_trip = True
            self._idle_since = None
            self._last_point = None
            self._last_log_ts = 0.0
            self._db.execute(
                "INSERT INTO trips (id, start_ts) VALUES (?, ?)",
                (self._trip_id, now))
            self._db.commit()
            log.info("Trip %d started", self._trip_id)

        if not self._in_trip:
            return

        # Log a point at most every interval_sec (always log slow points
        # so the trip-end idle window has fresh data).
        if now - self._last_log_ts >= self.interval_sec or speed <= self.trip_end_kmh:
            self._last_log_ts = now
            self._db.execute(
                "INSERT INTO tracks (trip_id, ts, lat, lon, speed, heading, altitude)"
                " VALUES (?,?,?,?,?,?,?)",
                (self._trip_id, now,
                 pos.get("lat", 0), pos.get("lon", 0),
                 speed, pos.get("heading", 0), pos.get("altitude", 0)))
            self._db.commit()

        # Trip end: parked below trip_end_kmh for trip_end_idle_sec
        if speed <= self.trip_end_kmh:
            if self._idle_since is None:
                self._idle_since = now
            elif now - self._idle_since >= self.trip_end_idle_sec:
                self._close_trip(now)
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

    def _compute_stats(self, trip_id):
        rows = self._db.execute(
            "SELECT lat, lon, speed, ts FROM tracks WHERE trip_id=? ORDER BY ts",
            (trip_id,)).fetchall()
        if not rows:
            return {}
        distance = 0.0
        for (lat1, lon1, _, _), (lat2, lon2, _, _) in zip(rows, rows[1:]):
            distance += _haversine_km(lat1, lon1, lat2, lon2)
        speeds = [r[2] for r in rows]
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
            return self._compute_stats(trip_id or self._trip_id)

    def list_trips(self, limit=50):
        with self._lock:
            rows = self._db.execute(
                "SELECT id, start_ts, end_ts, distance_km, avg_speed, max_speed"
                " FROM trips ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [
            {"trip_id": r[0], "start_ts": r[1], "end_ts": r[2],
             "distance_km": r[3], "avg_speed": r[4], "max_speed": r[5]}
            for r in rows
        ]

    def export_gpx(self, trip_id):
        """Export trip as GPX XML string."""
        with self._lock:
            rows = self._db.execute(
                "SELECT lat, lon, speed, heading, altitude, ts"
                " FROM tracks WHERE trip_id=? ORDER BY ts",
                (trip_id,)).fetchall()
        points = "\n".join(
            f'    <trkpt lat="{r[0]}" lon="{r[1]}"><ele>{r[4]}</ele>'
            f'<speed>{r[2]}</speed></trkpt>'
            for r in rows)
        return f"""<?xml version="1.0"?>
<gpx version="1.1"><trk><name>Trip {trip_id}</name><trkseg>
{points}
</trkseg></trk></gpx>"""

    def start(self):
        self._running = True
        log.info("GPS tracker started (DB: %s, interval %ds)",
                 self.db_path, int(self.interval_sec))

    def stop(self):
        self._running = False
        with self._lock:
            if self._in_trip:
                self._close_trip(time.time())
            if self._db:
                self._db.close()
                self._db = None


def start_tracker(config=None, event_bus=None, hal=None, **kwargs):
    tracker = GPSTracker(event_bus, config=config)
    tracker.start()
    return tracker
