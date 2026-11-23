"""Refuel log, GPS trip feed, route fuel/weather (Partia 12, etap 3).

* src/trip/fuel_log.py: validation, full-to-full interval maths (partial
  fills, missing odometer → GPS, calibration clamp, first fill), storage
  (restart, time order, delete-last-only, newer schema → read only),
  fuel.stats publication, the tracker's distance_between;
* src/trip/gps_trip_feed.py: trip.* from a GPS stream on a fake clock;
* RoutePlanner: the log's average in the fuel estimate, the weather manager
  from weather._internals; WeatherManager.forecast_at and its 3-hour slots;
* web: /api/fuel/* (loopback only, 400/404/409/429), the A3 payload, the
  /trips "Tankowania" table, remote-access classification.

Nothing touches the network or system paths: databases live in tmp_path,
OpenWeatherMap is a fake urlopen.
"""

import json
import time
from types import SimpleNamespace

import pytest

from src.core.config import BCMConfig
from src.core.event_bus import EventBus
from src.dashboard import web_viewer as wv
from src.dashboard.web_viewer import WebViewer
from src.location.tracker import GPSTracker
from src.trip import fuel_log as fl
from src.trip.gps_trip_feed import GpsTripFeed, NEW_TRIP_AFTER_S
from src.trip.route_planner import RoutePlanner
from src.weather import weather as wmod


class _Cfg:
    def __init__(self, **data):
        self._data = data

    def get(self, key, default=None):
        return self._data.get(key, default)


class _Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


def _row(rid, ts, litres, full=True, price=None, odo=None):
    return {"id": rid, "ts": float(ts), "litres": litres, "full": full,
            "price_per_l": price, "odometer_km": odo}


# ── validation ───────────────────────────────────────────────────────────

class TestValidate:
    def test_comma_and_dot_strings(self):
        clean, err, warn = fl.validate_refuel(
            {"litres": "45,5", "price_per_l": "6.49", "odometer_km": "123456"})
        assert err == "" and warn == []
        assert clean == {"litres": 45.5, "price_per_l": 6.49, "odometer_km": 123456.0,
                         "full": True, "note": None}

    @pytest.mark.parametrize("body,code", [
        ({}, "litres_required"),
        ({"litres": "  "}, "litres_required"),
        ({"litres": 0.5}, "litres_range"),
        ({"litres": 121}, "litres_range"),
        ({"litres": "1e2"}, "litres_range"),
        ({"litres": "-5"}, "litres_range"),
        ({"litres": True}, "litres_range"),
        ({"litres": float("nan")}, "litres_range"),
        ({"litres": 40, "price_per_l": 0}, "price_range"),
        ({"litres": 40, "price_per_l": 31}, "price_range"),
        ({"litres": 40, "price_per_l": "abc"}, "price_range"),
        ({"litres": 40, "odometer_km": 2_000_001}, "odometer_range"),
        ({"litres": 40, "full": "yes"}, "bad_full"),
        ({"litres": 40, "note": "x" * 81}, "note_too_long"),
        ({"litres": 40, "note": 5}, "bad_request"),
        ([], "bad_request"),
    ])
    def test_rejected(self, body, code):
        clean, err, _ = fl.validate_refuel(body)
        assert clean is None and err == code

    def test_bounds_are_inclusive(self):
        for litres in (1, 120):
            assert fl.validate_refuel({"litres": litres})[1] == ""
        assert fl.validate_refuel({"litres": 40, "price_per_l": 30})[1] == ""
        assert fl.validate_refuel({"litres": 40, "odometer_km": 0})[1] == ""
        assert fl.validate_refuel({"litres": 40, "odometer_km": 2_000_000})[1] == ""

    def test_over_tank_is_a_warning(self):
        clean, err, warn = fl.validate_refuel({"litres": 70}, tank_l=58)
        assert err == "" and warn == ["litres_over_tank"]

    def test_odometer_backwards_needs_confirmation(self):
        prev = {"odometer_km": 100_000}
        assert fl.validate_refuel({"litres": 40, "odometer_km": 99_000}, prev)[1] \
            == "odometer_backwards"
        clean, err, warn = fl.validate_refuel(
            {"litres": 40, "odometer_km": 99_000, "confirm_odometer": True}, prev)
        assert err == "" and warn == ["odometer_backwards"]
        assert fl.validate_refuel({"litres": 40, "odometer_km": 100_000}, prev)[1] == ""

    def test_note_control_chars_stripped(self):
        clean, err, _ = fl.validate_refuel({"litres": 40, "note": "Orlen\n<b>x</b>"})
        assert err == "" and clean["note"] == "Orlen <b>x</b>"

    def test_tank_capacity_from_config(self):
        assert fl.tank_capacity(_Cfg(**{"fuel_sender.tank_capacity_litres": 60})) == 60
        assert fl.tank_capacity(_Cfg(**{"fuel_sender.tank_capacity_litres": 5})) == 58
        assert fl.tank_capacity(_Cfg(**{"fuel_sender.tank_capacity_litres": "x"})) == 58
        assert fl.tank_capacity(_Cfg()) == 58
        assert fl.tank_capacity(None) == 58


# ── interval maths ───────────────────────────────────────────────────────

class TestComputeStats:
    def test_empty(self):
        s = fl.compute_stats([], None)
        assert s["status"] == "empty" and s["avg_l100_overall"] is None and s["recent"] == []

    def test_first_full_only_starts_the_log(self):
        s = fl.compute_stats([_row(1, 1000, 50, odo=1000)], lambda a, b: 120.0)
        assert s["status"] == "need_second_full"
        assert s["avg_l100_last"] is None and s["avg_l100_overall"] is None
        # Range needs an average — none yet.
        assert s["km_since_full"] == 120.0 and s["est_range_km"] is None

    def test_partial_before_first_full_is_ignored(self):
        rows = [_row(1, 0, 20, full=False, odo=500), _row(2, 10, 50, odo=900),
                _row(3, 20, 40, odo=1400)]
        s = fl.compute_stats(rows, None)
        assert s["avg_l100_overall"] == 8.0          # 40 l / 500 km

    def test_odometer_interval_with_partial_fills(self):
        rows = [_row(1, 0, 50, odo=10_000, price=6.0),
                _row(2, 10, 10, full=False, price=6.5),
                _row(3, 20, 25, odo=10_500, price=6.2)]
        s = fl.compute_stats(rows, None)
        # (10 + 25) l / 500 km = 7.0 l/100 km
        assert s["status"] == "ok"
        assert s["avg_l100_last"] == 7.0 and s["avg_l100_overall"] == 7.0
        iv = s["intervals"][3]
        assert iv["source"] == "odometer" and iv["km"] == 500 and iv["usable"] is True
        assert iv["cost"] == round(10 * 6.5 + 25 * 6.2, 2)
        assert s["cost_per_100km"] == round((65 + 155) / 500 * 100, 2)
        # The partial fill itself closes no interval.
        assert s["intervals"].get(2) is None
        assert [r["id"] for r in s["recent"]] == [3, 2, 1]
        assert s["recent"][0]["interval"]["l100"] == 7.0

    def test_missing_price_means_no_cost(self):
        rows = [_row(1, 0, 50, odo=0, price=6.0), _row(2, 10, 30, odo=400)]
        s = fl.compute_stats(rows, None)
        assert s["intervals"][2]["cost"] is None and s["cost_per_100km"] is None

    def test_missing_odometer_uses_gps(self):
        rows = [_row(1, 0, 50), _row(2, 100, 30)]
        calls = []

        def gps(a, b):
            calls.append((a, b))
            return 400.0 if b is not None else 50.0
        s = fl.compute_stats(rows, gps)
        assert (0.0, 100.0) in calls and (100.0, None) in calls
        iv = s["intervals"][2]
        assert iv["source"] == "gps" and iv["km"] == 400 and iv["l100"] == 7.5
        assert s["calibration"] == {"factor": 1.0, "samples": 0}
        assert s["km_since_full"] == 50.0

    def test_calibration_corrects_gps_and_is_clamped(self):
        # Interval 1: odometer 1000 km, GPS 960 km → factor 1.0417.
        # Interval 2: GPS only, 480 km → 500 km after calibration.
        gps_km = {(0.0, 10.0): 960.0, (10.0, 20.0): 480.0}
        rows = [_row(1, 0, 50, odo=10_000), _row(2, 10, 70, odo=11_000), _row(3, 20, 35)]
        s = fl.compute_stats(rows, lambda a, b: gps_km.get((a, b), 0.0))
        assert s["calibration"]["samples"] == 1
        assert s["calibration"]["factor"] == pytest.approx(1000 / 960, abs=1e-4)
        assert s["intervals"][3]["km"] == pytest.approx(500.0, abs=0.1)
        assert s["intervals"][3]["l100"] == pytest.approx(7.0, abs=0.01)
        # A 30 % gap is clamped to +10 %.
        gps_km[(0.0, 10.0)] = 1000 / 1.3
        s = fl.compute_stats(rows, lambda a, b: gps_km.get((a, b), 0.0))
        assert s["calibration"]["factor"] == 1.1
        # GPS covered a third (module off for days): not a calibration sample.
        gps_km[(0.0, 10.0)] = 330.0
        s = fl.compute_stats(rows, lambda a, b: gps_km.get((a, b), 0.0))
        assert s["calibration"] == {"factor": 1.0, "samples": 0}

    def test_short_or_implausible_interval_is_skipped(self):
        rows = [_row(1, 0, 50, odo=0), _row(2, 10, 5, odo=10),         # 10 km: too short
                _row(3, 20, 40, odo=110),                              # 40 l/100 km
                _row(4, 30, 35, odo=610)]                              # 7.0
        s = fl.compute_stats(rows, None)
        assert s["intervals"][2]["usable"] is False
        assert s["intervals"][3]["usable"] is False and s["intervals"][3]["l100"] == 40.0
        assert s["avg_l100_overall"] == 7.0 and s["avg_l100_last"] == 7.0

    def test_overall_is_weighted_by_distance(self):
        rows = [_row(1, 0, 50, odo=0), _row(2, 10, 10, odo=100),       # 10 l/100 over 100
                _row(3, 20, 54, odo=1000)]                             # 6 l/100 over 900
        s = fl.compute_stats(rows, None)
        assert s["avg_l100_overall"] == pytest.approx(64 / 1000 * 100, abs=0.01)
        assert s["avg_l100_last"] == 6.0

    def test_range_uses_tank_and_partial_fills(self):
        rows = [_row(1, 0, 50, odo=0), _row(2, 10, 35, odo=500),     # 7.0 l/100
                _row(3, 20, 10, full=False)]
        s = fl.compute_stats(rows, lambda a, b: 300.0 if b is None else 0.0, tank_l=60)
        # 300 km since the full fill: 21 l used, + 10 l partial → 49 l left.
        assert s["km_since_full"] == 300.0 and s["litres_used_est"] == 21.0
        assert s["fuel_left_est_l"] == 49.0 and s["est_range_km"] == 700
        # Never above the tank, never below empty.
        s = fl.compute_stats(rows, lambda a, b: 5000.0 if b is None else 0.0, tank_l=60)
        assert s["fuel_left_est_l"] == 0.0 and s["est_range_km"] == 0


# ── the module (storage) ─────────────────────────────────────────────────

@pytest.fixture
def log_env(tmp_path):
    bus = EventBus()
    wall = _Clock()
    cfg = _Cfg(**{"fuel_log.db_path": str(tmp_path / "fuel.db"),
                  "fuel_sender.tank_capacity_litres": 58})
    flog = fl.FuelLog(bus, cfg, wall_clock=wall)
    seen = []
    bus.subscribe(fl.STATS_TOPIC, lambda t, v, ts: seen.append(v))
    yield SimpleNamespace(bus=bus, wall=wall, cfg=cfg, log=flog, seen=seen, path=tmp_path)
    flog.stop()


class TestFuelLogStorage:
    def test_add_and_persist_across_restart(self, log_env):
        assert log_env.log.add({"litres": "50", "odometer_km": 1000})["ok"]
        log_env.wall.advance(3600)
        r = log_env.log.add({"litres": 35, "odometer_km": 1500, "price_per_l": 6})
        assert r["ok"] and r["refuel"]["litres"] == 35
        assert log_env.seen[-1]["avg_l100_overall"] == 7.0
        assert "intervals" not in log_env.seen[-1]          # bus payload stays small
        log_env.log.stop()
        again = fl.FuelLog(log_env.bus, log_env.cfg, wall_clock=log_env.wall)
        try:
            rows = again.list_refuels()
            assert [r["litres"] for r in rows] == [35, 50]
            assert again.stats()["avg_l100_overall"] == 7.0
        finally:
            again.stop()

    def test_schema_version_table(self, log_env):
        import sqlite3
        db = sqlite3.connect(str(log_env.path / "fuel.db"))
        assert db.execute("SELECT version FROM schema_version").fetchall() == [(1,)]
        db.close()

    def test_newer_schema_is_read_only(self, log_env):
        import sqlite3
        log_env.log.add({"litres": 40})
        log_env.log.stop()
        db = sqlite3.connect(str(log_env.path / "fuel.db"))
        db.execute("UPDATE schema_version SET version = 99")
        db.commit()
        db.close()
        newer = fl.FuelLog(log_env.bus, log_env.cfg, wall_clock=log_env.wall)
        try:
            assert newer.add({"litres": 40}) == {"ok": False, "error": "read_only"}
            assert len(newer.list_refuels()) == 1 and newer.stats()["read_only"] is True
        finally:
            newer.stop()

    def test_timestamps_stay_in_order(self, log_env):
        log_env.log.add({"litres": 40})
        log_env.wall.advance(-86400)            # clock went back a day
        r = log_env.log.add({"litres": 30})
        assert r["ok"] and "clock_behind" in r["warnings"]
        rows = log_env.log.list_refuels()
        assert rows[0]["ts"] == rows[1]["ts"] + 1.0

    def test_validation_error_stores_nothing(self, log_env):
        assert log_env.log.add({"litres": 500}) == {"ok": False, "error": "litres_range"}
        assert log_env.log.list_refuels() == []

    def test_odometer_backwards_against_last_known(self, log_env):
        log_env.log.add({"litres": 40, "odometer_km": 5000})
        log_env.wall.advance(10)
        log_env.log.add({"litres": 10, "full": False})              # no odometer
        log_env.wall.advance(10)
        assert log_env.log.add({"litres": 30, "odometer_km": 4000})["error"] \
            == "odometer_backwards"
        log_env.wall.advance(10)
        r = log_env.log.add({"litres": 30, "odometer_km": 4000, "confirm_odometer": True})
        assert r["ok"] and r["warnings"] == ["odometer_backwards"]

    def test_delete_only_the_newest(self, log_env):
        a = log_env.log.add({"litres": 40})["refuel"]["id"]
        log_env.wall.advance(10)
        b = log_env.log.add({"litres": 30})["refuel"]["id"]
        assert log_env.log.delete(a) == {"ok": False, "error": "not_last"}
        assert log_env.log.delete(999) == {"ok": False, "error": "not_found"}
        assert log_env.log.delete("1") == {"ok": False, "error": "bad_request"}
        assert log_env.log.delete(b) == {"ok": True}
        assert [r["id"] for r in log_env.log.list_refuels()] == [a]
        assert log_env.seen[-1]["count"] == 1

    def test_position_only_when_fresh(self, log_env):
        log_env.bus.publish("gps.position", {"lat": 50.1, "lon": 19.9, "fix": True})
        log_env.wall.t = time.time()
        log_env.log.add({"litres": 40})
        log_env.wall.t = time.time() + 3600         # an hour-old fix is not "here"
        log_env.log.add({"litres": 30})
        rows = log_env.log.list_refuels()
        assert (rows[1]["lat"], rows[1]["lon"]) == (50.1, 19.9)
        assert rows[0]["lat"] is None

    def test_notification_after_second_full(self, log_env):
        log_env.log.add({"litres": 50, "odometer_km": 0})
        note = log_env.bus.get_last("system.notifications")
        assert note and "zatankuj do pełna jeszcze raz" in note[0][-1]["desc"]
        log_env.wall.advance(10)
        log_env.log.add({"litres": 35, "odometer_km": 500})
        note = log_env.bus.get_last("system.notifications")
        assert "7,0 l/100 km" in note[0][-1]["desc"]

    def test_without_tracker_warns_once(self, log_env, caplog):
        for _ in range(3):
            log_env.log.stats()
        assert sum("modules.tracking" in r.getMessage() for r in caplog.records) <= 1
        assert log_env.log.stats()["gps_available"] is False

    def test_start_publishes_internals_and_stats(self, tmp_path):
        bus = EventBus()
        cfg = _Cfg(**{"fuel_log.db_path": str(tmp_path / "f.db")})
        obj = fl.start_fuel_log(cfg, bus)
        try:
            assert fl.get_fuel_log(bus) is obj
            assert bus.get_last(fl.STATS_TOPIC)[0]["status"] == "empty"
        finally:
            obj.stop()


class TestWithTracker:
    def test_gps_distance_from_tracker(self, tmp_path):
        bus = EventBus()
        wall = _Clock(1_800_000_000.0)
        trk = GPSTracker(bus, config=_Cfg(**{
            "tracking.db_path": str(tmp_path / "gps.db"), "tracking.interval_sec": 0,
            "tracking.trip_end_idle_sec": 0}), wall_clock=wall)
        trk.start()
        bus.publish("tracking._internals", {"tracker": trk})
        flog = fl.FuelLog(bus, _Cfg(**{"fuel_log.db_path": str(tmp_path / "f.db")}),
                          wall_clock=wall)
        try:
            flog.add({"litres": 50})
            wall.advance(60)
            # ~11.1 km north at 60 km/h, then parked (trip closes).
            for lat, v in ((50.0, 60.0), (50.05, 60.0), (50.1, 60.0), (50.1, 0.0), (50.1, 0.0)):
                bus.publish("gps.position", {"lat": lat, "lon": 20.0, "speed": v})
                wall.advance(30)
            assert trk.distance_between(1_800_000_000.0) == pytest.approx(11.12, abs=0.05)
            assert trk.distance_between(wall() + 10) == 0.0
            assert trk.distance_between("x") is None
            s = flog.stats()
            assert s["gps_available"] is True and s["km_since_full"] == pytest.approx(11.1, abs=0.1)
            # An open trip counts live.
            bus.publish("gps.position", {"lat": 50.1, "lon": 20.0, "speed": 50.0})
            wall.advance(30)
            bus.publish("gps.position", {"lat": 50.2, "lon": 20.0, "speed": 50.0})
            assert trk.distance_between(1_800_000_000.0) == pytest.approx(22.24, abs=0.1)
        finally:
            flog.stop()
            trk.stop()


# ── GPS trip feed ────────────────────────────────────────────────────────

class TestGpsTripFeed:
    def _feed(self):
        bus = EventBus()
        clock = _Clock(1000.0)
        feed = GpsTripFeed(bus, None, clock=clock)
        feed.start()
        return bus, clock, feed

    def _drive(self, bus, clock, points, step=1.0):
        for lat, speed in points:
            clock.advance(step)
            bus.publish("gps.position", {"lat": lat, "lon": 20.0, "speed": speed, "fix": True})

    def test_no_obd_values_are_none(self):
        bus, clock, feed = self._feed()
        assert bus.get_last("trip.instant_consumption")[0] is None
        assert bus.get_last("trip.avg_consumption")[0] is None
        assert bus.get_last("trip.estimated_range")[0] is None
        assert bus.get_last("trip.distance")[0] == 0.0
        assert bus.get_last("trip.time_str")[0] == "00:00:00"

    def test_distance_time_and_average(self):
        bus, clock, feed = self._feed()
        # 0.001° of latitude ≈ 0.111 km every 10 s ≈ 40 km/h.
        lat = 50.0
        pts = []
        for _ in range(91):
            pts.append((lat, 40.0))
            lat += 0.001
        self._drive(bus, clock, pts, step=10.0)
        snap = feed.snapshot()
        assert snap["distance"] == pytest.approx(10.0, abs=0.05)   # 90 × 0.1112 km
        assert snap["time_str"] == "00:15:00"
        assert snap["avg_speed"] == pytest.approx(40.0, abs=0.5)
        assert bus.get_last("trip.distance")[0] == snap["distance"]

    def test_jumps_gaps_and_parked_drift_are_ignored(self):
        bus, clock, feed = self._feed()
        self._drive(bus, clock, [(50.0, 50.0), (50.0005, 50.0)], step=5.0)
        base = feed.distance_km
        self._drive(bus, clock, [(51.0, 50.0)], step=5.0)       # 110 km in 5 s
        assert feed.distance_km == base
        self._drive(bus, clock, [(51.001, 50.0)], step=300.0)  # after a 5-min gap
        assert feed.distance_km == base
        self._drive(bus, clock, [(51.0011, 0.0), (51.00105, 0.0)], step=5.0)  # drift
        assert feed.distance_km == base

    def test_short_stop_continues_long_stop_starts_new_trip(self):
        bus, clock, feed = self._feed()
        self._drive(bus, clock, [(50.0, 50.0), (50.001, 50.0)], step=8.0)
        d1 = feed.distance_km
        assert d1 > 0.1
        self._drive(bus, clock, [(50.001, 0.0)], step=8.0)        # parked
        clock.advance(60)                                          # a minute at the pump
        self._drive(bus, clock, [(50.002, 50.0)], step=8.0)
        assert feed.distance_km > d1                               # same trip
        self._drive(bus, clock, [(50.002, 0.0)], step=8.0)
        clock.advance(NEW_TRIP_AFTER_S + 1)
        frozen = feed.snapshot()["time_str"]
        clock.advance(600)
        assert feed.snapshot()["time_str"] == frozen               # parked: time stopped
        self._drive(bus, clock, [(50.003, 50.0)], step=8.0)        # new trip
        assert feed.distance_km == 0.0
        assert feed.snapshot()["time_str"] == "00:00:00"

    def test_fuel_stats_feed_consumption_and_range(self):
        bus, clock, feed = self._feed()
        bus.publish("fuel.stats", {"avg_l100_overall": 6.84, "est_range_km": 512.4})
        assert bus.get_last("trip.avg_consumption")[0] == 6.8
        assert bus.get_last("trip.estimated_range")[0] == 512
        bus.publish("fuel.stats", {"avg_l100_overall": None, "avg_l100_last": "x",
                                   "est_range_km": float("inf")})
        assert bus.get_last("trip.avg_consumption")[0] is None
        assert bus.get_last("trip.estimated_range")[0] is None

    def test_invalid_positions_are_ignored(self):
        bus, clock, feed = self._feed()
        for pos in ({"lat": 0.0, "lon": 0.0, "speed": 50}, {"lat": "x", "lon": 1},
                    {"lat": 50, "lon": 20, "fix": False, "speed": 50}, None, [1]):
            clock.advance(1)
            bus.publish("gps.position", pos)
        assert feed.snapshot()["distance"] == 0.0 and feed._started is None

    def test_publishes_at_most_once_a_second(self):
        bus, clock, feed = self._feed()
        got = []
        bus.subscribe("trip.distance", lambda t, v, ts: got.append(v))
        for i in range(10):
            clock.advance(0.1)
            bus.publish("gps.position", {"lat": 50 + i * 1e-5, "lon": 20, "speed": 30})
        assert len(got) == 1


# ── route planner: fuel from the log, weather from _internals ─────────────

class TestRoutePlanner:
    def _planner(self, bus):
        return RoutePlanner(_Cfg(), bus)

    def test_estimate_uses_log_average(self):
        bus = EventBus()
        bus.publish("fuel.stats", {"avg_l100_overall": 6.0})
        res = self._planner(bus).plan((50.0, 20.0), (50.9, 20.0))
        assert res["fuel_l100_source"] == "log" and res["fuel_l100"] == 6.0
        # distance_km is rounded to 0.1 km in the result, the estimate is not.
        assert res["predicted_fuel_l"] == pytest.approx(res["distance_km"] * 0.06, abs=0.01)

    def test_trip_average_wins_then_default(self):
        bus = EventBus()
        bus.publish("fuel.stats", {"avg_l100_overall": 6.0})
        p = self._planner(bus)
        assert p._consumption(5.5) == (5.5, "trip")
        bus.publish("fuel.stats", {"avg_l100_overall": 99.0})      # implausible
        assert p._consumption(0) == (7.0, "default")
        assert self._planner(None)._consumption(None) == (7.0, "default")

    def test_weather_manager_from_internals(self):
        bus = EventBus()
        calls = []

        class Mgr:
            def forecast_at(self, lat, lon, eta):
                calls.append((lat, lon, eta))
                return {"condition": "Light Rain", "temp": 3.5, "rain_mm": 1.2, "icon": "10d"}
        p = self._planner(bus)
        bus.publish("weather._internals", {"manager": Mgr()})      # started after the planner
        res = p.plan((50.0, 20.0), (50.9, 20.0))
        assert calls and res["weather_points"][0]["condition"] == "Light Rain"
        assert res["weather_points"][-1]["temp"] == 3.5


# ── WeatherManager.forecast_at ───────────────────────────────────────────

def _forecast_raw(start_ts, n=8, temp=5.0):
    return {"list": [{"dt": start_ts + i * 10800,
                      "main": {"temp": temp + i, "humidity": 80, "feels_like": temp - 2},
                      "weather": [{"id": 500, "main": "Rain", "description": "light rain",
                                   "icon": "10d"}],
                      "rain": {"3h": 0.6}, "wind": {"speed": 5, "gust": 12},
                      "pop": 0.7, "visibility": 8000} for i in range(n)]}


class _Resp:
    def __init__(self, body):
        self._body = json.dumps(body).encode()

    def read(self, n=-1):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestForecastAt:
    def _mgr(self, key="k"):
        clock = _Clock(500.0)
        m = wmod.WeatherManager(EventBus(), {"weather": {"api_key": key}}, clock=clock)
        return m, clock

    def test_parse_slots_validates(self):
        now = int(time.time())
        raw = _forecast_raw(now, 3)
        raw["list"].append({"dt": "x", "main": {"temp": 1}})
        raw["list"].append({"dt": now, "main": {"temp": 1000}})
        raw["list"][0]["weather"][0]["icon"] = "<script>"
        slots = wmod.WeatherManager._parse_slots(raw)
        assert len(slots) == 3
        assert slots[0]["icon"] is None and slots[1]["icon"] == "10d"
        assert slots[0]["wind_kmh"] == 18.0 and slots[0]["gust_kmh"] == 43.2
        assert slots[0]["rain_mm"] == 0.6 and slots[0]["condition"] == "Light Rain"
        assert wmod.WeatherManager._parse_slots({"list": "x"}) == []
        assert wmod.WeatherManager._parse_slots(None) == []

    def test_near_point_uses_regular_slots(self, monkeypatch):
        m, _ = self._mgr()
        now = int(time.time())
        m._publish_data({"current": {}, "forecast": [], "city": "",
                         "slots": wmod.WeatherManager._parse_slots(_forecast_raw(now)),
                         "coords": [50.0, 20.0]}, (50.0, 20.0))
        monkeypatch.setattr("urllib.request.urlopen",
                            lambda *a, **k: pytest.fail("no request for a near point"))
        out = m.forecast_at(50.05, 20.05, 180)
        assert out["temp"] == 6.0 and out["slot_ts"] == now + 10800
        assert m.forecast_at(50.0, 20.0, 0)["temp"] == 5.0

    def test_far_point_fetches_once_and_caches(self, monkeypatch):
        m, clock = self._mgr()
        now = int(time.time())
        urls = []

        def fake(req, timeout=0):
            urls.append(req.full_url)
            return _Resp(_forecast_raw(now, temp=-3.0))
        monkeypatch.setattr("urllib.request.urlopen", fake)
        a = m.forecast_at(52.231, 21.011, 0)
        b = m.forecast_at(52.229, 21.009, 60)       # same 0.1° cell
        assert a["temp"] == -3.0 and b is not None and len(urls) == 1
        assert "lat=52.2" in urls[0] and "lon=21.0" in urls[0]
        clock.advance(wmod.ROUTE_CACHE_S + 1)
        m.forecast_at(52.231, 21.011, 0)
        assert len(urls) == 2

    def test_rate_limited(self, monkeypatch):
        m, _ = self._mgr()
        now = int(time.time())
        count = [0]

        def fake(req, timeout=0):
            count[0] += 1
            return _Resp(_forecast_raw(now))
        monkeypatch.setattr("urllib.request.urlopen", fake)
        for i in range(wmod.ROUTE_FETCH_MAX + 5):
            m.forecast_at(40.0 + i, 10.0, 0)
        assert count[0] == wmod.ROUTE_FETCH_MAX

    def test_no_key_bad_input_and_far_future(self, monkeypatch):
        m, _ = self._mgr(key="")
        monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: pytest.fail("no key"))
        assert m.forecast_at(50, 20, 0) is None
        m, _ = self._mgr()
        assert m.forecast_at(91, 20, 0) is None
        assert m.forecast_at(50, 20, -5) is None
        assert m.forecast_at(50, 20, wmod.MAX_ETA_MIN + 1) is None
        assert m.forecast_at(50, 20, True) is None

    def test_http_error_returns_none(self, monkeypatch):
        import urllib.error
        m, _ = self._mgr()

        def boom(req, timeout=0):
            raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, None)
        monkeypatch.setattr("urllib.request.urlopen", boom)
        assert m.forecast_at(45.0, 10.0, 0) is None

    def test_demo_data_clears_slots(self):
        m, _ = self._mgr()
        m._publish_data(wmod.DEMO_WEATHER)
        assert m.slots == ([], None)

    def test_start_publishes_internals(self, monkeypatch):
        bus = EventBus()
        monkeypatch.setattr(wmod.WeatherManager, "start", lambda self: None)
        mgr = wmod.start_weather({"weather": {}}, bus, None)
        assert bus.get_last("weather._internals")[0]["manager"] is mgr


# ── web ──────────────────────────────────────────────────────────────────

@pytest.fixture
def web(tmp_path):
    bus = EventBus()
    cfg = BCMConfig(platform_override="x86", local_path=None, env={})
    cfg.save = lambda path=None: None
    cfg.set("modules.fuel_log", True)
    flog = fl.FuelLog(bus, _Cfg(**{"fuel_log.db_path": str(tmp_path / "f.db")}))
    flog.start()
    bus.publish(fl.INTERNALS_TOPIC, {"fuel_log": flog})
    viewer = WebViewer(host="127.0.0.1", port=5099, event_bus=bus, config=cfg)
    client = viewer._build_app().test_client()
    yield SimpleNamespace(bus=bus, cfg=cfg, viewer=viewer, client=client, log=flog)
    flog.stop()


def _lan(addr="10.0.0.23"):
    return {"environ_base": {"REMOTE_ADDR": addr},
            "environ_overrides": {"HTTP_HOST": "10.0.0.1:5002"}}


class TestFuelRoutes:
    def test_post_201_then_rate_limited(self, web):
        res = web.client.post("/api/fuel/refuel", json={"litres": "45,5", "price_per_l": 6.49})
        assert res.status_code == 201
        body = res.get_json()
        assert body["ok"] and body["refuel"]["litres"] == 45.5 and body["warnings"] == []
        assert "lat" not in body["refuel"]
        res = web.client.post("/api/fuel/refuel", json={"litres": 30})
        assert res.status_code == 429 and res.headers["Retry-After"]
        assert len(web.log.list_refuels()) == 1

    @pytest.mark.parametrize("body,code", [
        ({"litres": 500}, "litres_range"), ({}, "litres_required"),
        ({"litres": 40, "price_per_l": 99}, "price_range"),
    ])
    def test_bad_input_is_400(self, web, body, code):
        res = web.client.post("/api/fuel/refuel", json=body)
        assert res.status_code == 400 and res.get_json()["error"] == code

    def test_not_json_and_too_large(self, web):
        assert web.client.post("/api/fuel/refuel", data="x",
                               content_type="application/json").status_code == 400
        assert web.client.post("/api/fuel/refuel", json=[1]).status_code == 400
        big = {"litres": 40, "note": "x" * 5000}
        assert web.client.post("/api/fuel/refuel", json=big).status_code == 413

    def test_kiosk_only(self, web):
        res = web.client.post("/api/fuel/refuel", json={"litres": 40}, **_lan())
        assert res.status_code == 403
        res = web.client.post("/api/fuel/refuel", json={"litres": 40},
                              headers={"Origin": "http://evil.example"})
        assert res.status_code == 403
        assert web.client.delete("/api/fuel/refuel/1", **_lan()).status_code == 403
        assert web.log.list_refuels() == []

    def test_delete(self, web, monkeypatch):
        monkeypatch.setattr(wv, "_FUEL_MIN_INTERVAL_S", 0.0)
        a = web.client.post("/api/fuel/refuel", json={"litres": 40}).get_json()["refuel"]["id"]
        time.sleep(0.01)
        b = web.client.post("/api/fuel/refuel", json={"litres": 30}).get_json()["refuel"]["id"]
        assert web.client.delete(f"/api/fuel/refuel/{a}").status_code == 409
        assert web.client.delete("/api/fuel/refuel/777").status_code == 404
        assert web.client.delete(f"/api/fuel/refuel/{b}").status_code == 200
        assert [r["id"] for r in web.log.list_refuels()] == [a]

    def test_not_running_is_409(self, web):
        web.bus.publish(fl.INTERNALS_TOPIC, {})
        assert web.client.post("/api/fuel/refuel", json={"litres": 40}).status_code == 409
        assert web.client.get("/api/fuel/log").status_code == 503

    def test_log_and_payload(self, web, monkeypatch):
        monkeypatch.setattr(wv, "_FUEL_MIN_INTERVAL_S", 0.0)
        web.client.post("/api/fuel/refuel", json={"litres": 50, "odometer_km": 1000,
                                                  "note": "<b>Orlen</b>"})
        time.sleep(0.01)
        web.client.post("/api/fuel/refuel", json={"litres": 35, "odometer_km": 1500,
                                                  "price_per_l": 6})
        body = web.client.get("/api/fuel/log").get_json()
        assert [r["litres"] for r in body["refuels"]] == [35, 50]
        assert body["refuels"][0]["interval"]["l100"] == 7.0
        assert body["stats"]["avg_l100_overall"] == 7.0
        assert "Orlen" not in json.dumps(body)               # no notes over the API
        data = web.viewer._get_dashboard_data()["fuel_log"]
        assert data["enabled"] and data["running"] and data["status"] == "ok"
        assert data["recent"][0]["interval"]["cost"] == 210.0
        assert data["cost_per_100km"] == 42.0

    def test_payload_without_module(self):
        assert wv._fuel_log_summary(None, None) == {"enabled": False, "running": False}
        out = wv._fuel_log_summary(None, {"status": "<x>", "avg_l100_last": "7",
                                          "recent": "nope", "count": True})
        assert out["status"] == "empty" and out["avg_l100_last"] is None
        assert out["recent"] == [] and out["count"] == 0

    def test_trips_page_has_refuels_table(self, web):
        web.client.post("/api/fuel/refuel", json={"litres": 42.5, "price_per_l": 6.5})
        res = web.client.get("/trips")
        page = res.get_data(as_text=True)
        assert "Tankowania" in page and "42,50 l" in page and "6,50 zł" in page
        assert res.headers["Content-Security-Policy"].startswith("default-src 'none'")

    def test_refuels_html_escapes_and_empty(self):
        assert wv._render_refuels_html(None) == ""
        assert "Brak zapisanych tankowań" in wv._render_refuels_html([])
        html = wv._render_refuels_html([{"ts": 1.8e9, "litres": 40.0, "full": True,
                                         "interval": {"l100": 45.0, "km": 50, "usable": False,
                                                      "source": "gps", "cost": None}}])
        assert "(pominięte)" in html and "(GPS)" in html

    def test_remote_access_classification(self, web):
        assert "api_fuel_log" in wv._TRACKING_ENDPOINTS
        assert "api_fuel_log" in wv._READONLY_ENDPOINTS
        web.cfg.set("dashboard.remote_access", "tracking")
        client = web.viewer._build_app().test_client()
        assert client.get("/api/fuel/log", **_lan()).status_code == 200
        assert client.post("/api/fuel/refuel", json={"litres": 40}, **_lan()).status_code == 403
        # No tracker in this fixture: 503, but not refused by the policy.
        assert client.get("/trips", **_lan()).status_code != 403


# ── review fixes ─────────────────────────────────────────────────────────

class TestReviewFixes:
    def test_trip_end_on_sync_bus_does_not_deadlock(self, tmp_path):
        """tracking.trip_ended on a synchronous bus: the fuel log must not
        call back into the tracker (its plain Lock) from the callback."""
        import threading
        bus = EventBus()
        wall = _Clock(1_800_000_000.0)
        trk = GPSTracker(bus, config=_Cfg(**{
            "tracking.db_path": str(tmp_path / "gps.db"), "tracking.interval_sec": 0,
            "tracking.trip_end_idle_sec": 0}), wall_clock=wall)
        trk.start()
        bus.publish("tracking._internals", {"tracker": trk})
        flog = fl.FuelLog(bus, _Cfg(**{"fuel_log.db_path": str(tmp_path / "f.db")}),
                          wall_clock=wall)
        ended, seen = [], []
        bus.subscribe("tracking.trip_ended", lambda t, v, ts: ended.append(v))
        bus.subscribe(fl.STATS_TOPIC, lambda t, v, ts: seen.append(v))
        try:
            flog.start()
            assert flog.add({"litres": 50, "full": True})["ok"]
            wall.advance(60)

            def drive():
                for lat, v in ((50.0, 50.0), (50.05, 50.0), (50.05, 0.0), (50.05, 0.0)):
                    bus.publish("gps.position", {"lat": lat, "lon": 20.0, "speed": v})
                    wall.advance(30)
            t = threading.Thread(target=drive, daemon=True)
            t.start()
            t.join(timeout=5)
            assert not t.is_alive(), "trip end deadlocked on the tracker lock"
            assert len(ended) == 1
            # The tick thread recomputes right away (dirty flag), not after TICK_S.
            before = len(seen)
            deadline = time.monotonic() + 3
            while len(seen) == before and time.monotonic() < deadline:
                time.sleep(0.02)
            assert len(seen) > before
            assert seen[-1]["km_since_full"] == pytest.approx(5.6, abs=0.1)
        finally:
            flog.stop()
            trk.stop()

    def test_stop_wakes_tick_thread(self, log_env):
        log_env.log.start()
        t0 = time.monotonic()
        log_env.log.stop()
        assert time.monotonic() - t0 < 1.5

    def test_huge_integer_is_out_of_range_not_overflow(self):
        big = 10 ** 400
        assert fl.parse_number(big) is None
        assert fl.validate_refuel({"litres": big})[1] == "litres_range"
        assert fl.validate_refuel({"litres": 40, "price_per_l": big})[1] == "price_range"
        assert fl.validate_refuel({"litres": 40, "odometer_km": big})[1] == "odometer_range"

    def test_huge_integer_in_forecast_drops_field_only(self):
        now = int(time.time())
        raw = _forecast_raw(now, n=3)
        raw["list"][1]["main"]["temp"] = 10 ** 400
        slots = wmod.WeatherManager._parse_slots(raw)
        # The slot without a usable temperature is dropped, not the whole fetch.
        assert len(slots) == 2

    def test_gps_feed_finite_survives_huge_int(self):
        from src.trip import gps_trip_feed as gtf
        assert gtf._finite(10 ** 400) is None

    @pytest.mark.parametrize("rows,status", [
        ([_row(1, 0, 20, full=False)], "need_first_full"),
        ([_row(1, 0, 50)], "need_second_full"),
        ([_row(1, 0, 50), _row(2, 10, 40), _row(3, 20, 45)], "no_distance"),
        ([_row(1, 0, 50, odo=1000), _row(2, 10, 40, odo=1005)], "intervals_skipped"),
    ])
    def test_status_says_why_there_is_no_average(self, rows, status):
        assert fl.compute_stats(rows, None)["status"] == status

    def test_no_distance_notification(self, log_env):
        for _ in range(2):
            assert log_env.log.add({"litres": 40})["ok"]
            log_env.wall.advance(3600)
        note = log_env.bus.get_last("system.notifications")
        assert "brak dystansu" in note[0][-1]["desc"]

    def test_db_files_are_owner_only(self, log_env):
        import os
        import stat
        log_env.log.add({"litres": 40})
        for suffix in ("", "-wal", "-shm"):
            p = str(log_env.path / "fuel.db") + suffix
            if os.path.exists(p):
                assert stat.S_IMODE(os.stat(p).st_mode) == 0o600, p

    def test_route_weather_failure_holdoff(self, monkeypatch):
        clock = _Clock(500.0)
        m = wmod.WeatherManager(EventBus(), {"weather": {"api_key": "k"}}, clock=clock)
        calls = [0]

        def down(req, timeout=0):
            calls[0] += 1
            raise OSError("timed out")
        monkeypatch.setattr("urllib.request.urlopen", down)
        assert m.forecast_at(45.0, 10.0, 0) is None
        assert m.forecast_at(46.0, 10.0, 0) is None
        assert m.forecast_at(47.0, 10.0, 0) is None
        assert calls[0] == 1
        now = int(time.time())
        monkeypatch.setattr("urllib.request.urlopen",
                            lambda req, timeout=0: _Resp(_forecast_raw(now)))
        clock.advance(wmod.ROUTE_FAIL_HOLDOFF_S + 1)
        assert m.forecast_at(48.0, 10.0, 0) is not None

    def test_trip_gps_catalog_entry(self):
        from src.core.modules_catalog import MODULES
        e = MODULES["trip_gps"]
        assert e["default"] is False and e["requires"] == ("location",)
        assert "entry" not in e
        import pathlib
        import yaml
        root = pathlib.Path(__file__).resolve().parent.parent
        with open(root / "config" / "bcm_config_test.yaml", encoding="utf-8") as f:
            assert yaml.safe_load(f)["modules"]["trip_gps"] is True


class TestFuelRouteReviewFixes:
    def test_huge_integer_body_is_400(self, web):
        body = '{"litres": ' + "9" * 400 + "}"
        res = web.client.post("/api/fuel/refuel", data=body, content_type="application/json")
        assert res.status_code == 400 and res.get_json()["error"] == "litres_range"

    def test_refused_entry_does_not_throttle_corrected_retry(self, web):
        assert web.client.post("/api/fuel/refuel", json={"litres": 500}).status_code == 400
        assert web.client.post("/api/fuel/refuel", json={"litres": 40}).status_code == 201

    def test_overlapping_posts_store_one_refuel(self, web, monkeypatch):
        import threading
        real_add = web.log.add
        gate = threading.Event()

        def slow_add(data):
            gate.wait(1.0)
            return real_add(data)
        monkeypatch.setattr(web.log, "add", slow_add)
        codes = []

        def post():
            codes.append(web.client.post("/api/fuel/refuel", json={"litres": 40}).status_code)
        threads = [threading.Thread(target=post) for _ in range(2)]
        for t in threads:
            t.start()
        time.sleep(0.2)
        gate.set()
        for t in threads:
            t.join(timeout=5)
        assert sorted(codes) == [201, 429]
        assert len(web.log.list_refuels()) == 1
