"""GPS route tracker — continuous logging to SQLite.

Logs GPS positions, auto-detects trip start/stop, exports GPX.
"""

import os
import sqlite3
import threading
import time
from src.core.logger import get_logger

log = get_logger("gps_tracker")


class GPSTracker:
    """Continuous GPS logging with trip detection."""

    DB_PATH = "data/gps_tracks.db"

    def __init__(self, event_bus):
        self.bus = event_bus
        self._running = False
        self._thread = None
        self._in_trip = False
        self._trip_id = 0
        self._db = None
        self._init_db()

        bus.subscribe("gps.position", self._on_position)

    def _init_db(self):
        os.makedirs(os.path.dirname(self.DB_PATH), exist_ok=True)
        self._db = sqlite3.connect(self.DB_PATH, check_same_thread=False)
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
        self._db.commit()
        # Get next trip ID
        row = self._db.execute("SELECT MAX(id) FROM trips").fetchone()
        self._trip_id = (row[0] or 0) + 1

    def _on_position(self, topic, pos, ts):
        if not isinstance(pos, dict):
            return
        speed = pos.get("speed", 0)

        # Trip detection: start when speed > 5, stop when parked for 60s
        if not self._in_trip and speed > 5:
            self._in_trip = True
            self._db.execute("INSERT INTO trips (id, start_ts) VALUES (?, ?)",
                             (self._trip_id, time.time()))
            self._db.commit()
            log.info("Trip %d started", self._trip_id)

        if self._in_trip:
            self._db.execute(
                "INSERT INTO tracks (trip_id, ts, lat, lon, speed, heading, altitude) VALUES (?,?,?,?,?,?,?)",
                (self._trip_id, time.time(),
                 pos.get("lat", 0), pos.get("lon", 0),
                 speed, pos.get("heading", 0), pos.get("altitude", 0)))
            self._db.commit()

    def get_trip_stats(self, trip_id=None):
        """Get statistics for a trip (or current)."""
        tid = trip_id or self._trip_id
        rows = self._db.execute(
            "SELECT lat, lon, speed, ts FROM tracks WHERE trip_id=? ORDER BY ts",
            (tid,)).fetchall()
        if not rows:
            return {}
        speeds = [r[2] for r in rows]
        return {
            "trip_id": tid,
            "points": len(rows),
            "avg_speed": sum(speeds) / len(speeds) if speeds else 0,
            "max_speed": max(speeds) if speeds else 0,
            "duration_s": rows[-1][3] - rows[0][3] if len(rows) > 1 else 0,
        }

    def export_gpx(self, trip_id):
        """Export trip as GPX XML string."""
        rows = self._db.execute(
            "SELECT lat, lon, speed, heading, altitude, ts FROM tracks WHERE trip_id=? ORDER BY ts",
            (trip_id,)).fetchall()
        points = "\n".join(
            f'    <trkpt lat="{r[0]}" lon="{r[1]}"><ele>{r[4]}</ele><speed>{r[2]}</speed></trkpt>'
            for r in rows)
        return f"""<?xml version="1.0"?>
<gpx version="1.1"><trk><name>Trip {trip_id}</name><trkseg>
{points}
</trkseg></trk></gpx>"""

    def start(self):
        self._running = True
        log.info("GPS tracker started (DB: %s)", self.DB_PATH)

    def stop(self):
        self._running = False
        if self._db:
            self._db.close()


def start_tracker(config, event_bus, hal=None, **kwargs):
    tracker = GPSTracker(event_bus)
    tracker.start()
    return tracker
