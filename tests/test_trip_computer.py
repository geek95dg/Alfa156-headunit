"""Travel plan route origin (src/dashboard/trip_computer.py, zgłoszenie A).

Without a fresh GPS fix the planner silently started the route in Kraków.
The plan now says where it starts (``origin_source``/``origin_lat``/
``origin_lon``), and when ``gps.fix`` turns True after a plan from the
fallback, the same destination is planned once more from the GPS position.

No threads: the worker and the delayed re-plan run through the seams
``_start_worker`` / ``_schedule``; the planner is a recorder.
"""

import logging

import pytest

from src.core.event_bus import EventBus
from src.dashboard import trip_computer as tc_mod
from src.dashboard.trip_computer import FALLBACK_ORIGIN, REPLAN_DELAY_S, TripComputer

GDYNIA = (54.5189, 18.5305)
WARSAW = (52.2297, 21.0122)


class Planner:
    def __init__(self):
        self.calls = []

    def plan(self, start, dest, avg_consumption):
        self.calls.append((tuple(start), tuple(dest)))
        return {"distance_km": 500.0, "duration_min": 330.0, "computed_at": 1.0}


def make():
    bus = EventBus()
    planner = Planner()
    tc = TripComputer(event_bus=bus, route_planner=planner)
    tc._start_worker = lambda fn, name: fn()            # run the worker inline
    timers = []
    tc._schedule = lambda delay, fn: timers.append((delay, fn))
    return tc, bus, planner, timers


def gps_fix(bus, coords=WARSAW):
    """What GPSManager publishes for a new fix (gps.fix first, then the position)."""
    bus.publish("gps.fix", True)
    bus.publish("gps.lat", coords[0])
    bus.publish("gps.lon", coords[1])


class TestOrigin:
    def test_without_gps_the_plan_says_fallback(self, caplog):
        tc, bus, planner, timers = make()
        with caplog.at_level(logging.INFO, logger="bcm.trip_computer"):
            tc.set_destination(*GDYNIA, "Gdynia")
        assert planner.calls == [(FALLBACK_ORIGIN, GDYNIA)]
        plan = tc.get_plan_dict()
        assert plan["origin_source"] == "fallback"
        assert (plan["origin_lat"], plan["origin_lon"]) == FALLBACK_ORIGIN
        assert any("Route origin: fallback (50.0647, 19.9450)" in r.getMessage()
                   for r in caplog.records)

    def test_with_a_fresh_fix_the_plan_says_gps(self):
        tc, bus, planner, timers = make()
        gps_fix(bus)
        tc.set_destination(*GDYNIA, "Gdynia")
        assert planner.calls == [(WARSAW, GDYNIA)]
        plan = tc.get_plan_dict()
        assert plan["origin_source"] == "gps"
        assert (plan["origin_lat"], plan["origin_lon"]) == WARSAW
        assert timers == []                              # nothing to re-plan

    def test_an_explicit_origin_is_given(self):
        tc, bus, planner, timers = make()
        tc.set_destination(*GDYNIA, "Gdynia", origin=(51.1, 17.03))
        assert tc.get_plan_dict()["origin_source"] == "given"

    def test_route_payload_carries_the_origin(self):
        tc, bus, planner, timers = make()
        routes = []
        bus.subscribe("trip.route", lambda t, v, ts: routes.append(v))
        tc.set_destination(*GDYNIA, "Gdynia")
        assert routes[-1]["origin_source"] == "fallback"

    def test_clear_forgets_the_origin(self):
        tc, bus, planner, timers = make()
        tc.set_destination(*GDYNIA, "Gdynia")
        tc.clear_destination()
        plan = tc.get_plan_dict()
        assert plan["origin_source"] is None and plan["origin_lat"] is None


class TestReplanWhenTheFixArrives:
    def test_fix_after_a_fallback_plan_replans_once(self):
        tc, bus, planner, timers = make()
        tc.set_destination(*GDYNIA, "Gdynia")
        gps_fix(bus)
        assert len(timers) == 1 and timers[0][0] == REPLAN_DELAY_S
        bus.publish("gps.fix", False)
        gps_fix(bus)                                     # flapping fix: still one
        assert len(timers) == 1
        timers.pop()[1]()                                # the delay elapses
        assert planner.calls == [(FALLBACK_ORIGIN, GDYNIA), (WARSAW, GDYNIA)]
        plan = tc.get_plan_dict()
        assert plan["origin_source"] == "gps" and plan["destination_name"] == "Gdynia"
        # A plan from the GPS is never re-planned again.
        bus.publish("gps.fix", False)
        gps_fix(bus)
        assert timers == []
        assert len(planner.calls) == 2

    def test_no_destination_no_replan(self):
        tc, bus, planner, timers = make()
        gps_fix(bus)
        assert timers == [] and planner.calls == []

    def test_a_new_destination_cancels_the_pending_replan(self):
        tc, bus, planner, timers = make()
        tc.set_destination(*GDYNIA, "Gdynia")
        gps_fix(bus)
        tc.set_destination(51.1, 17.03, "Wrocław")      # from GPS now
        timers.pop()[1]()
        assert [c[1] for c in planner.calls] == [GDYNIA, (51.1, 17.03)]

    def test_clear_cancels_the_pending_replan(self):
        tc, bus, planner, timers = make()
        tc.set_destination(*GDYNIA, "Gdynia")
        gps_fix(bus)
        tc.clear_destination()
        timers.pop()[1]()
        assert len(planner.calls) == 1

    def test_stale_position_skips_and_the_next_fix_tries_again(self, monkeypatch):
        tc, bus, planner, timers = make()
        tc.set_destination(*GDYNIA, "Gdynia")
        gps_fix(bus)
        real = tc_mod.time.time
        monkeypatch.setattr(tc_mod.time, "time", lambda: real() + 60)   # position 60 s old
        timers.pop()[1]()
        assert len(planner.calls) == 1                   # not re-planned from fallback
        monkeypatch.setattr(tc_mod.time, "time", real)
        gps_fix(bus)
        assert len(timers) == 1                          # not stuck "scheduled"
        timers.pop()[1]()
        assert planner.calls[-1] == (WARSAW, GDYNIA)

    def test_fix_while_the_fallback_plan_is_still_computing(self):
        tc, bus, planner, timers = make()
        workers = []
        tc._start_worker = lambda fn, name: workers.append(fn)
        tc.set_destination(*GDYNIA, "Gdynia")
        workers.pop()()                                  # origin chosen: fallback
        assert tc.get_plan_dict()["origin_source"] == "fallback"
        gps_fix(bus)
        assert len(timers) == 1


class TestSupersededWorkers:
    def test_an_old_result_never_overwrites_a_newer_plan(self):
        tc, bus, planner, timers = make()
        workers = []
        tc._start_worker = lambda fn, name: workers.append(fn)
        tc.set_destination(*GDYNIA, "Gdynia")
        tc.set_destination(51.1, 17.03, "Wrocław")
        second, first = workers.pop(), workers.pop()
        second()
        first()                                          # finishes last
        plan = tc.get_plan_dict()
        assert plan["destination_name"] == "Wrocław"
        assert [c[1] for c in planner.calls] == [(51.1, 17.03)]   # first never planned

    def test_a_worker_finishing_after_clear_ends_planning(self):
        tc, bus, planner, timers = make()
        workers, planning = [], []
        bus.subscribe("trip.planning", lambda t, v, ts: planning.append(v))
        tc._start_worker = lambda fn, name: workers.append(fn)
        tc.set_destination(*GDYNIA, "Gdynia")
        tc.reset()                                       # trip reset, no clear()
        workers.pop()()
        assert planning[-1] is False
        assert tc.get_plan_dict()["destination_name"] is None


@pytest.mark.parametrize("body", [
    {"lat": float("nan"), "lon": 18.5}, {"lat": [1], "lon": 2}, {"lat": "x", "lon": 2},
    {"lat": 91, "lon": 2}, {"lon": 2}, None,
])
def test_destination_route_validates_coordinates(body):
    from src.core.config import BCMConfig
    from src.dashboard.web_viewer import WebViewer

    tc, bus, planner, timers = make()
    viewer = WebViewer(host="127.0.0.1", port=5099, event_bus=bus,
                       config=BCMConfig(platform_override="x86"), trip_computer=tc)
    client = viewer._build_app().test_client()
    res = client.post("/api/trip/destination", json=body)
    assert res.status_code == 400
    assert planner.calls == []


def test_destination_route_cleans_the_name():
    from src.core.config import BCMConfig
    from src.dashboard.web_viewer import WebViewer

    tc, bus, planner, timers = make()
    viewer = WebViewer(host="127.0.0.1", port=5099, event_bus=bus,
                       config=BCMConfig(platform_override="x86"), trip_computer=tc)
    client = viewer._build_app().test_client()
    res = client.post("/api/trip/destination",
                      json={"lat": GDYNIA[0], "lon": GDYNIA[1], "name": "Gdy\nnia\x1b[2J"})
    assert res.status_code == 200
    assert tc.get_plan_dict()["destination_name"] == "Gdy nia [2J"
