"""Tests for the GPS route tracker (src/location/tracker.py)."""

import pytest

from src.core.event_bus import EventBus
from src.location.tracker import GPSTracker, _haversine_km


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
