"""Tests for the GPS route tracker (src/location/tracker.py)."""

import xml.etree.ElementTree as ET

import pytest

from src.core.event_bus import EventBus
from src.location.tracker import GPSTracker, _haversine_km, start_tracker


class _TrackerConfig:
    """Minimal config stub feeding tracking.* keys."""

    def __init__(self, **overrides):
        self._data = overrides

    def get(self, key, default=None):
        return self._data.get(key, default)


@pytest.fixture()
def tracker(tmp_path):
    bus = EventBus()
    cfg = _TrackerConfig(**{
        "tracking.db_path": str(tmp_path / "gps_tracks.db"),
        "tracking.interval_sec": 0,       # log every point
        "tracking.trip_start_kmh": 5,
        "tracking.trip_end_kmh": 2,
        "tracking.trip_end_idle_sec": 0,  # close on second parked point
    })
    trk = GPSTracker(bus, config=cfg)
    trk.start()
    yield trk
    trk.stop()


def _pos(bus, lat, lon, speed, altitude=120.0):
    bus.publish("gps.position", {
        "lat": lat, "lon": lon, "speed": speed,
        "heading": 0.0, "altitude": altitude,
    })


def _drive_full_trip(tracker):
    """Simulate a short drive followed by parking; returns the trip id."""
    trip_id = tracker._trip_id
    bus = tracker.bus
    _pos(bus, 52.2297, 21.0122, 50.0)
    _pos(bus, 52.2397, 21.0122, 60.0)
    _pos(bus, 52.2497, 21.0122, 40.0)
    # Parked: first slow point arms the idle timer, second closes the trip
    _pos(bus, 52.2497, 21.0122, 0.0)
    _pos(bus, 52.2497, 21.0122, 0.0)
    return trip_id


class TestTripLifecycle:
    def test_not_in_trip_initially(self, tracker):
        assert tracker._in_trip is False

    def test_slow_speed_does_not_open_trip(self, tracker):
        _pos(tracker.bus, 52.0, 21.0, 3.0)
        assert tracker._in_trip is False

    def test_trip_opens_above_start_speed(self, tracker):
        _pos(tracker.bus, 52.0, 21.0, 10.0)
        assert tracker._in_trip is True

    def test_trip_closes_after_idle(self, tracker):
        _drive_full_trip(tracker)
        assert tracker._in_trip is False

    def test_trip_end_event_published(self, tracker):
        ended = []
        tracker.bus.subscribe("tracking.trip_ended", lambda t, v, ts: ended.append(v))
        trip_id = _drive_full_trip(tracker)
        assert len(ended) == 1
        assert ended[0]["trip_id"] == trip_id
        assert ended[0]["distance_km"] > 0

    def test_ignores_positions_before_start(self, tmp_path):
        bus = EventBus()
        cfg = _TrackerConfig(**{"tracking.db_path": str(tmp_path / "t.db")})
        trk = GPSTracker(bus, config=cfg)
        # start() NOT called — positions must be ignored
        _pos(bus, 52.0, 21.0, 50.0)
        assert trk._in_trip is False
        trk._running = False
        trk.stop()


class TestTripStats:
    def test_distance_positive(self, tracker):
        trip_id = _drive_full_trip(tracker)
        stats = tracker.get_trip_stats(trip_id)
        assert stats["distance_km"] > 0
        assert stats["points"] >= 3
        assert stats["max_speed"] == 60.0

    def test_list_trips_returns_closed_trip(self, tracker):
        trip_id = _drive_full_trip(tracker)
        trips = tracker.list_trips()
        assert len(trips) == 1
        trip = trips[0]
        assert trip["trip_id"] == trip_id
        assert trip["end_ts"] is not None
        assert trip["distance_km"] > 0

    def test_second_trip_gets_new_id(self, tracker):
        first = _drive_full_trip(tracker)
        second = _drive_full_trip(tracker)
        assert second == first + 1
        assert len(tracker.list_trips()) == 2


class TestExportGPX:
    def test_export_contains_trkpt(self, tracker):
        trip_id = _drive_full_trip(tracker)
        gpx = tracker.export_gpx(trip_id)
        assert "<gpx" in gpx
        assert "<trkpt" in gpx
        assert 'lat="52.2297"' in gpx
        assert "<ele>" in gpx

    def test_export_empty_trip(self, tracker):
        gpx = tracker.export_gpx(99999)
        assert "<gpx" in gpx
        assert "<trkpt" not in gpx


class TestHaversine:
    def test_zero_distance(self):
        assert _haversine_km(52.0, 21.0, 52.0, 21.0) == 0.0

    def test_known_distance(self):
        # ~1.11 km per 0.01 deg of latitude
        d = _haversine_km(52.00, 21.0, 52.01, 21.0)
        assert 1.0 < d < 1.2


class TestPersistence:
    def test_crashed_trip_closed_on_reopen(self, tmp_path):
        db = str(tmp_path / "gps.db")
        cfg = _TrackerConfig(**{
            "tracking.db_path": db,
            "tracking.interval_sec": 0,
        })
        bus = EventBus()
        trk = GPSTracker(bus, config=cfg)
        trk.start()
        _pos(bus, 52.0, 21.0, 50.0)  # trip open
        assert trk._in_trip is True
        trk._running = False  # simulate crash: no clean stop
        trk._db.close()

        bus2 = EventBus()
        trk2 = GPSTracker(bus2, config=cfg)
        trips = trk2.list_trips()
        assert len(trips) == 1
        assert trips[0]["end_ts"] is not None  # retroactively closed
        trk2.stop()


# ── Etap 4: power cuts, no-fix close, GPX 1.1, web access ────────────────

GPX_NS = "{http://www.topografix.com/GPX/1/1}"


class _Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


class TestPowerCutSafety:
    def test_wal_and_busy_timeout(self, tracker):
        db = tracker._db
        assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert db.execute("PRAGMA synchronous").fetchone()[0] == 1      # NORMAL
        assert db.execute("PRAGMA busy_timeout").fetchone()[0] == 2000

    def test_trip_cut_by_power_loss_gets_stats_on_restart(self, tmp_path):
        cfg = _TrackerConfig(**{"tracking.db_path": str(tmp_path / "g.db"),
                                "tracking.interval_sec": 0})
        bus = EventBus()
        trk = GPSTracker(bus, config=cfg)
        trk.start()
        _pos(bus, 52.2297, 21.0122, 50.0)
        _pos(bus, 52.2397, 21.0122, 60.0)
        _pos(bus, 52.2497, 21.0122, 40.0)
        last_ts = trk._db.execute("SELECT MAX(ts) FROM tracks").fetchone()[0]
        trk._running = False        # power cut: no stop(), no _close_trip()
        trk._stop_evt.set()
        trk._db.close()

        trk2 = GPSTracker(EventBus(), config=cfg)
        try:
            trip = trk2.list_trips()[0]
            assert trip["end_ts"] == last_ts
            assert trip["distance_km"] == pytest.approx(2.22, abs=0.05)
            assert trip["max_speed"] == 60.0
            assert trip["avg_speed"] == pytest.approx(50.0)
            assert trip["points"] == 3
            assert trk2._trip_id == trip["trip_id"] + 1
        finally:
            trk2.stop()

    def test_old_retro_closed_trip_without_stats_is_repaired(self, tmp_path):
        import sqlite3
        db = str(tmp_path / "old.db")
        cfg = _TrackerConfig(**{"tracking.db_path": db})
        GPSTracker(EventBus(), config=cfg).stop()           # creates the schema
        con = sqlite3.connect(db)
        con.execute("INSERT INTO trips (id, start_ts, end_ts) VALUES (1, 100, 300)")
        con.executemany("INSERT INTO tracks (trip_id, ts, lat, lon, speed) VALUES (1,?,?,?,?)",
                        [(100, 52.0, 21.0, 30.0), (300, 52.01, 21.0, 50.0)])
        con.commit()
        con.close()
        trk = GPSTracker(EventBus(), config=cfg)
        try:
            trip = trk.get_trip(1)
            assert trip["end_ts"] == 300                       # kept
            assert trip["distance_km"] == pytest.approx(1.11, abs=0.02)
            assert trip["max_speed"] == 50.0
        finally:
            trk.stop()

    def test_trip_without_points_is_closed_at_its_start(self, tmp_path):
        import sqlite3
        db = str(tmp_path / "empty.db")
        cfg = _TrackerConfig(**{"tracking.db_path": db})
        GPSTracker(EventBus(), config=cfg).stop()
        con = sqlite3.connect(db)
        con.execute("INSERT INTO trips (id, start_ts) VALUES (1, 123)")
        con.commit()
        con.close()
        trk = GPSTracker(EventBus(), config=cfg)
        try:
            trip = trk.get_trip(1)
            assert trip["end_ts"] == 123 and trip["distance_km"] == 0 and trip["points"] == 0
        finally:
            trk.stop()


class TestNoFixClose:
    def _tracker(self, tmp_path, clock):
        cfg = _TrackerConfig(**{"tracking.db_path": str(tmp_path / "nf.db"),
                                "tracking.interval_sec": 0,
                                "tracking.no_fix_close_sec": 300})
        trk = GPSTracker(EventBus(), config=cfg, clock=clock)
        trk.start()
        return trk

    def test_closes_after_no_fix_close_sec(self, tmp_path):
        clock = _Clock()
        trk = self._tracker(tmp_path, clock)
        ended = []
        trk.bus.subscribe("tracking.trip_ended", lambda t, v, ts: ended.append(v))
        try:
            _pos(trk.bus, 52.2297, 21.0122, 50.0)
            _pos(trk.bus, 52.2397, 21.0122, 60.0)
            last_ts = trk._db.execute("SELECT MAX(ts) FROM tracks").fetchone()[0]
            clock.t += 299
            trk.tick()
            assert trk._in_trip is True and ended == []
            clock.t += 2
            trk.tick()
            assert trk._in_trip is False
            assert len(ended) == 1 and ended[0]["distance_km"] > 0
            assert trk.list_trips()[0]["end_ts"] == last_ts    # when GPS stopped
            trk.tick()
            assert len(ended) == 1
        finally:
            trk.stop()

    def test_positions_keep_the_trip_open(self, tmp_path):
        clock = _Clock()
        trk = self._tracker(tmp_path, clock)
        try:
            for _ in range(5):
                _pos(trk.bus, 52.2297, 21.0122, 50.0)
                clock.t += 200
                trk.tick()
            assert trk._in_trip is True
        finally:
            trk.stop()

    def test_invalid_positions_are_ignored(self, tracker):
        bus = tracker.bus
        bus.publish("gps.position", {"lat": 52.0, "lon": 21.0, "speed": 50.0, "fix": False})
        bus.publish("gps.position", {"lat": float("nan"), "lon": 21.0, "speed": 50.0})
        bus.publish("gps.position", {"lat": 95.0, "lon": 21.0, "speed": 50.0})
        bus.publish("gps.position", {"lat": "52", "lon": 21.0, "speed": 50.0})
        assert tracker._in_trip is False
        bus.publish("gps.position", {"lat": 52.0, "lon": 21.0, "speed": None,
                                     "heading": None, "alt": None, "altitude": None})
        assert tracker._in_trip is False


class TestGPX11:
    def test_parses_with_namespace_times_and_elevation(self, tracker):
        trip_id = _drive_full_trip(tracker)
        root = ET.fromstring(tracker.export_gpx(trip_id).encode("utf-8"))
        assert root.tag == GPX_NS + "gpx"
        assert root.get("version") == "1.1" and root.get("creator") == "BCM"
        meta_time = root.find(f"{GPX_NS}metadata/{GPX_NS}time")
        assert meta_time is not None and meta_time.text.endswith("Z")
        points = root.findall(f".//{GPX_NS}trkpt")
        assert len(points) >= 3
        for pt in points:
            t = pt.find(f"{GPX_NS}time").text
            assert len(t) == 20 and t[10] == "T" and t.endswith("Z")
            assert float(pt.find(f"{GPX_NS}ele").text) == 120.0
            float(pt.get("lat")), float(pt.get("lon"))
        # GPX 1.1 has no <speed> in trkpt (that was GPX 1.0)
        assert root.find(f".//{GPX_NS}speed") is None
        assert root.find(f"{GPX_NS}trk/{GPX_NS}name").text.startswith(f"BCM trasa {trip_id}")

    def test_small_coordinates_are_plain_decimals(self, tracker):
        _pos(tracker.bus, 0.00001, -0.00002, 50.0, altitude=None)
        trip_id = tracker._trip_id
        gpx = tracker.export_gpx(trip_id)
        assert 'lat="0.00001"' in gpx and 'lon="-0.00002"' in gpx
        assert "e-0" not in gpx
        ET.fromstring(gpx.encode("utf-8"))


class TestWebAccessHelpers:
    def test_start_tracker_publishes_internals(self, tmp_path):
        bus = EventBus()
        cfg = _TrackerConfig(**{"tracking.db_path": str(tmp_path / "s.db")})
        trk = start_tracker(config=cfg, event_bus=bus)
        try:
            assert bus.get_last("tracking._internals")[0] == {"tracker": trk}
        finally:
            trk.stop()

    def test_list_trips_clamps_and_counts_points(self, tracker):
        _drive_full_trip(tracker)
        _drive_full_trip(tracker)
        assert len(tracker.list_trips(0)) == 1
        assert len(tracker.list_trips("x")) == 2
        assert len(tracker.list_trips(10**9)) == 2
        assert all(t["points"] >= 3 for t in tracker.list_trips())
        assert tracker.get_trip(999) is None

    def test_stopped_tracker_answers_empty(self, tmp_path):
        trk = GPSTracker(EventBus(), config=_TrackerConfig(**{
            "tracking.db_path": str(tmp_path / "x.db")}))
        trk.stop()
        assert trk.list_trips() == [] and trk.get_trip(1) is None
        assert "<trkpt" not in trk.export_gpx(1)
