"""Weather poller (src/weather/weather.py): backoff, phone internet, location.

``_poll_once()`` is driven directly with a fake monotonic clock and a
patched ``_fetch_weather``; no thread is started and nothing touches the
network or ~/.cache (the cache file points into tmp_path).
"""

import json
from urllib.parse import parse_qs, urlsplit

import pytest

from src.core.event_bus import EventBus
from src.weather import weather as wmod
from src.weather.weather import (
    FORCE_MIN_AGE_S,
    WeatherManager,
    _plausible_fix,
    valid_coords,
)

GOOD = {"current": {"temp": 11.0, "condition": "Clear"}, "city": "Kraków, PL",
        "forecast": []}


class FakeClock:
    def __init__(self, t=5000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


@pytest.fixture(autouse=True)
def cache_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(wmod, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(wmod, "CACHE_FILE", tmp_path / "weather.json")


def make(platform="x86", api_key="k", poll_min=15, results=None, **weather_cfg):
    """Manager wired like start() does, minus the thread.

    ``wm.used`` lists the coordinates each fetch was made for (the explicit
    ones of a search fetch, else the current location).
    """
    bus = EventBus()
    clock = FakeClock()
    wm = WeatherManager(bus, {"weather": {"api_key": api_key, "poll_interval_min": poll_min,
                                          "default_lat": 50.06, "default_lon": 19.94,
                                          **weather_cfg}},
                        platform, clock=clock)
    attempts = []
    wm.used = []
    results = list(results or [])

    def fetch(coords=None):
        attempts.append(clock.t)
        wm.used.append(coords if coords is not None else (wm._lat, wm._lon))
        return results.pop(0) if results else None

    wm._fetch_weather = fetch
    bus.subscribe("gps.position", wm._on_gps_position)
    bus.subscribe("lte.connected", wm._on_lte_status)
    bus.subscribe("net.phone_tether", wm._on_phone_tether)
    bus.subscribe("net.car_phone", wm._on_car_phone)
    bus.subscribe("weather.search_location", wm._on_search_location)
    return wm, bus, clock, attempts


def run_for(wm, clock, seconds, step=5):
    for _ in range(int(seconds // step)):
        wm._poll_once()
        clock.advance(step)


def gaps(times):
    return [b - a for a, b in zip(times, times[1:])]


class TestBackoff:
    def test_failures_back_off_from_60s_to_the_poll_interval(self):
        wm, bus, clock, attempts = make(poll_min=15)
        run_for(wm, clock, 2 * 3600)
        # It used to retry every ~5 s: 1440 attempts in these two hours.
        assert gaps(attempts)[:6] == [60, 120, 240, 480, 900, 900]
        assert set(gaps(attempts)[4:]) == {900}
        assert len(attempts) < 15

    def test_short_poll_interval_still_waits_at_least_60s(self):
        wm, bus, clock, attempts = make(poll_min=0.5)
        run_for(wm, clock, 600)
        assert set(gaps(attempts)) == {60}

    def test_success_polls_at_interval_and_resets_backoff(self):
        wm, bus, clock, attempts = make(poll_min=15, results=[None, None, GOOD, None])
        run_for(wm, clock, 3600)
        # fail (60) -> fail (120) -> success (900) -> fail: back to 60
        assert gaps(attempts)[:4] == [60, 120, 900, 60]
        assert wm._last_success == attempts[2]

    def test_exception_in_fetch_counts_as_failure(self):
        wm, bus, clock, attempts = make()

        def boom(coords=None):
            attempts.append(clock.t)
            raise RuntimeError("network down")

        wm._fetch_weather = boom
        run_for(wm, clock, 300)
        assert gaps(attempts)[:2] == [60, 120]

    def test_no_key_no_attempts(self):
        wm, bus, clock, attempts = make(api_key="")
        run_for(wm, clock, 600)
        assert attempts == []

    def test_offline_non_x86_waits_for_an_uplink(self):
        wm, bus, clock, attempts = make(platform="opi")
        run_for(wm, clock, 600)
        assert attempts == []
        bus.publish("lte.connected", True)
        wm._poll_once()
        assert len(attempts) == 1


class TestPhoneTether:
    def test_tether_connected_forces_a_fetch(self):
        wm, bus, clock, attempts = make(results=[GOOD])
        wm._poll_once()                             # success: next poll in 15 min
        clock.advance(120)
        wm._poll_once()
        assert len(attempts) == 1
        bus.publish("net.phone_tether", {"state": "connected", "ip": "192.168.44.2"})
        wm._poll_once()
        assert len(attempts) == 2

    def test_forced_fetch_skips_the_backoff(self):
        wm, bus, clock, attempts = make()
        run_for(wm, clock, 1000)                    # failing: backoff at 900 s now
        n = len(attempts)
        bus.publish("net.phone_tether", {"state": "connecting"})
        bus.publish("net.phone_tether", {"state": "connected"})
        wm._poll_once()
        assert len(attempts) == n + 1
        # ... and the backoff starts over at 60 s
        run_for(wm, clock, 65)
        assert gaps(attempts)[-1] == 60

    def test_force_during_an_in_flight_fetch_is_not_lost(self):
        # The PAN link comes up while an (offline) fetch is running: that
        # fetch fails, but the forced retry must stay "now", not +60 s.
        wm, bus, clock, attempts = make(platform="opi")
        bus.publish("lte.connected", True)
        state = {"n": 0}

        def fetch(coords=None):
            attempts.append(clock.t)
            state["n"] += 1
            if state["n"] == 1:
                bus.publish("net.phone_tether", {"state": "connected"})
                return None                         # this one was still offline
            return GOOD

        wm._fetch_weather = fetch
        wm._poll_once()
        assert wm._next_fetch == 0.0
        assert wm._retry_delay == wmod.RETRY_MIN_S  # backoff not grown
        assert wm._wake.is_set()
        clock.advance(1)
        wm._poll_once()
        assert len(attempts) == 2 and wm._last_success == clock.t

    def test_failure_without_a_force_still_backs_off(self):
        wm, bus, clock, attempts = make()
        wm._poll_once()
        assert wm._next_fetch == clock.t + 60

    def test_only_the_transition_forces(self):
        wm, bus, clock, attempts = make(results=[GOOD, GOOD])
        bus.publish("net.phone_tether", {"state": "connected"})
        wm._poll_once()
        clock.advance(FORCE_MIN_AGE_S + 1)
        bus.publish("net.phone_tether", {"state": "connected", "ip": "x"})  # no edge
        wm._poll_once()
        assert len(attempts) == 1

    def test_flapping_link_does_not_storm(self):
        wm, bus, clock, attempts = make(results=[GOOD] * 5)
        wm._poll_once()
        for _ in range(3):
            clock.advance(10)
            bus.publish("net.phone_tether", {"state": "waiting_phone"})
            bus.publish("net.phone_tether", {"state": "connected"})
            wm._poll_once()
        assert len(attempts) == 1                   # data younger than 60 s

    def test_tether_counts_as_uplink_off_x86(self):
        wm, bus, clock, attempts = make(platform="opi")
        wm._poll_once()
        assert attempts == []
        bus.publish("net.phone_tether", {"state": "connected"})
        wm._poll_once()
        assert len(attempts) == 1

    def test_start_seeds_tether_state_and_subscribes(self):
        bus = EventBus()
        bus.publish("net.phone_tether", {"state": "connected"})
        wm = WeatherManager(bus, {"weather": {"api_key": ""}}, "opi", clock=FakeClock())
        wm._run = lambda: None
        wm.start()
        try:
            assert wm._tether_connected is True
            bus.publish("net.phone_tether", {"state": "waiting_phone"})
            assert wm._tether_connected is False
        finally:
            wm.stop()


class TestCarPhone:
    """net.car_phone (src/network/car_phone.py, USB tethering) counts as an
    uplink and forces a fetch on its edge into connected — like PAN."""

    def test_connected_forces_a_fetch_once_per_edge(self):
        wm, bus, clock, attempts = make(results=[GOOD, GOOD, GOOD])
        wm._poll_once()
        clock.advance(120)
        bus.publish("net.car_phone", {"state": "connected", "ip": "192.168.42.100"})
        wm._poll_once()
        assert len(attempts) == 2
        clock.advance(120)
        bus.publish("net.car_phone", {"state": "connected", "battery_pct": 77})
        wm._poll_once()
        assert len(attempts) == 2                  # not an edge: no new force

    def test_it_is_an_uplink_off_x86(self):
        wm, bus, clock, attempts = make(platform="opi")
        wm._poll_once()
        assert attempts == []
        bus.publish("net.car_phone", {"state": "tethering"})
        wm._poll_once()
        assert attempts == []
        bus.publish("net.car_phone", {"state": "connected"})
        wm._poll_once()
        assert len(attempts) == 1
        bus.publish("net.car_phone", {"state": "no_device"})
        assert wm._car_phone_connected is False

    def test_start_seeds_and_subscribes(self):
        bus = EventBus()
        bus.publish("net.car_phone", {"state": "connected"})
        wm = WeatherManager(bus, {"weather": {"api_key": ""}}, "opi", clock=FakeClock())
        wm._run = lambda: None
        wm.start()
        try:
            assert wm._car_phone_connected is True
            bus.publish("net.car_phone", "garbage")
            assert wm._car_phone_connected is False
        finally:
            wm.stop()


class TestLocation:
    @pytest.mark.parametrize("payload", [
        {"lat": 0, "lon": 0},
        {"lat": 0.0, "lon": 0.0, "fix": True},
        {"lat": 45.46, "lon": 9.19, "fix": False},
        {"lat": float("nan"), "lon": 9.19},
        {"lat": 91, "lon": 9.19},
        {"lat": "45.46&appid=x", "lon": 9.19},
        {"lat": True, "lon": 9.19},
        {"lon": 9.19},
        "45,9",
        None,
    ])
    def test_implausible_gps_is_ignored(self, payload):
        wm, bus, clock, attempts = make()
        bus.publish("gps.position", payload)
        assert wm._has_gps is False
        wm._poll_once()
        assert wm.used == [(50.06, 19.94)]                # default location used

    def test_valid_fix_is_used(self):
        wm, bus, clock, attempts = make()
        bus.publish("gps.position", {"lat": 45.46, "lon": 9.19, "alt": 120})
        assert wm._has_gps is True
        bus.publish("gps.position", {"lat": 0, "lon": 0})   # lost fix: keep last good
        wm._poll_once()
        assert (wm._lat, wm._lon) == (45.46, 9.19)

    def test_helpers(self):
        assert valid_coords(50, "19.5") == (50.0, 19.5)
        assert valid_coords(-90, 180) == (-90.0, 180.0)
        assert valid_coords(90.1, 0) is None
        assert valid_coords(float("inf"), 0) is None
        assert valid_coords(None, 0) is None
        assert _plausible_fix({"lat": 0.0, "lon": 1e-9}) == (0.0, 1e-9)

    def test_invalid_search_location_is_rejected(self):
        wm, bus, clock, attempts = make()
        done = []
        bus.subscribe("weather.search_done", lambda t, v, ts: done.append(v))
        started = []
        wm._immediate_fetch = lambda: started.append(True)
        bus.publish("weather.search_location", {"lat": "1&appid=evil", "lon": 2, "city": "x"})
        assert started == [] and len(done) == 1
        assert wm._has_gps is False
        bus.publish("weather.search_location", {"lat": 52.23, "lon": 21.01, "city": "Warszawa"})
        assert (wm._lat, wm._lon) == (52.23, 21.01)


KRAKOW = (50.06, 19.94)          # the default location in make()
WARSAW = {"lat": 52.2297, "lon": 21.0122, "fix": True}


def fix(lat, lon):
    return {"lat": lat, "lon": lon, "fix": True}


class TestFirstGpsFix:
    """The boot fetch is for the default city; the first real fix must not
    wait for the next 15-minute poll (zgłoszenie A)."""

    def test_fix_40s_after_the_boot_fetch_refetches_at_once(self):
        wm, bus, clock, attempts = make(results=[GOOD, GOOD, GOOD])
        lats = []
        bus.subscribe("weather.lat", lambda t, v, ts: lats.append(v))
        wm._poll_once()                                    # boot: default city
        assert wm.used == [KRAKOW] and wm._fetch_source == "default"
        clock.advance(40)
        wm._wake.clear()
        bus.publish("gps.position", WARSAW)
        assert wm._wake.is_set()                           # the poller is woken
        assert wm._poll_once() is True                     # ... and fetches now
        assert wm.used[-1] == (52.2297, 21.0122)
        assert attempts[-1] == attempts[0] + 40
        assert wm._fetch_source == "gps" and lats[-1] == 52.2297
        # Later fixes never force again: the next fetch is the regular poll.
        for _ in range(20):
            clock.advance(5)
            bus.publish("gps.position", fix(52.2298, 21.0123))
            wm._poll_once()
        assert len(attempts) == 2

    def test_a_fix_after_an_outage_does_not_force_again(self):
        wm, bus, clock, attempts = make(results=[GOOD, None, GOOD])
        wm._poll_once()
        clock.advance(10)
        bus.publish("gps.position", WARSAW)
        wm._poll_once()                                    # the forced one fails
        assert len(attempts) == 2 and wm._fetch_source == "default"
        clock.advance(5)
        bus.publish("gps.position", fix(52.23, 21.01))     # fix back: no new force
        wm._poll_once()
        assert len(attempts) == 2                          # backoff (60 s) holds
        run_for(wm, clock, 60)
        assert len(attempts) == 3 and wm.used[-1] == (52.23, 21.01)

    def test_fix_arriving_during_the_default_fetch_still_forces(self):
        wm, bus, clock, attempts = make()

        def fetch(coords=None):
            attempts.append(clock.t)
            wm.used.append((wm._lat, wm._lon) if coords is None else coords)
            if len(attempts) == 1:
                bus.publish("gps.position", WARSAW)        # mid-request
            return GOOD

        wm._fetch_weather = fetch
        wm._poll_once()
        assert wm._fetch_source == "default" and wm._next_fetch == 0.0
        clock.advance(1)
        wm._poll_once()
        assert len(attempts) == 2 and wm._fetch_source == "gps"

    def test_fix_during_a_later_default_fetch_still_forces(self):
        # Boot fetch for the default city (x86: online). > 60 s later the
        # phone's PAN comes up (forced fetch, still no GPS) and the GPS NMEA,
        # arriving over the same PAN, lands while that request is in flight.
        wm, bus, clock, attempts = make()

        def fetch(coords=None):
            attempts.append(clock.t)
            wm.used.append(coords)
            if len(attempts) == 2:
                bus.publish("gps.position", WARSAW)        # mid-request
            return GOOD

        wm._fetch_weather = fetch
        wm._poll_once()                                    # boot: default
        clock.advance(90)
        bus.publish("net.phone_tether", {"state": "connected"})
        assert wm._poll_once() is True                     # forced: still default
        assert wm.used == [KRAKOW, KRAKOW]
        assert wm._gps_upgrade_done is True
        assert wm._next_fetch == 0.0                       # the force survived
        clock.advance(1)
        assert wm._poll_once() is True
        assert wm.used[-1] == (52.2297, 21.0122) and wm._fetch_source == "gps"
        run_for(wm, clock, 600)                            # and then the regular poll
        assert len(attempts) == 3

    def test_a_fix_landing_right_after_the_location_snapshot(self):
        # The bus thread stores a fix between the poller's location snapshot
        # and the request: the fetch is still for (and recorded as) the
        # default point, and the first-fix force follows.
        wm, bus, clock, attempts = make(results=[GOOD, GOOD])
        real = wm._location

        def location():
            snapshot = real()
            if not attempts:
                bus.publish("gps.position", WARSAW)
            return snapshot

        wm._location = location
        wm._poll_once()
        assert wm.used == [KRAKOW] and wm._fetch_source == "default"
        assert (wm._lat, wm._lon) == (52.2297, 21.0122)    # the fix is not overwritten
        clock.advance(1)
        wm._poll_once()
        assert wm.used[-1] == (52.2297, 21.0122) and wm._fetch_source == "gps"

    def test_an_ordinary_force_during_a_fetch_does_not_refetch(self):
        wm, bus, clock, attempts = make()

        def fetch(coords=None):
            attempts.append(clock.t)
            wm.used.append(coords)
            if len(attempts) == 2:
                bus.publish("net.phone_tether", {"state": "connected"})
            return GOOD

        wm._fetch_weather = fetch
        wm._poll_once()
        clock.advance(FORCE_MIN_AGE_S + 1)
        wm.force_fetch("test")
        wm._poll_once()
        assert len(attempts) == 2 and wm._next_fetch > clock.t

    def test_fix_before_any_fetch_needs_no_force(self):
        wm, bus, clock, attempts = make(results=[GOOD])
        bus.publish("gps.position", WARSAW)
        assert wm._gps_upgrade_done is False and not wm._wake.is_set()
        wm._poll_once()
        assert wm.used == [(52.2297, 21.0122)]

    def test_searched_city_wins_over_the_first_fix(self):
        wm, bus, clock, attempts = make(results=[GOOD, GOOD, GOOD])
        wm._poll_once()                                    # default
        wm._immediate_fetch = lambda: None                 # no thread here
        bus.publish("weather.search_location", {"lat": 41.9, "lon": 12.5, "city": "Roma"})
        WeatherManager._immediate_fetch(wm)                # what the thread runs
        assert wm.used[-1] == (41.9, 12.5) and wm._fetch_source == "search"
        clock.advance(30)
        wm._wake.clear()
        bus.publish("gps.position", WARSAW)                # moved > 15 km, first fix
        assert not wm._wake.is_set()
        run_for(wm, clock, 600)
        assert len(attempts) == 2                          # Rome stays until the poll
        run_for(wm, clock, 400)
        assert len(attempts) == 3 and wm.used[-1] == (52.2297, 21.0122)

    def test_search_fetch_uses_the_searched_coordinates_even_if_gps_moves(self):
        wm, bus, clock, attempts = make(results=[GOOD])
        wm._immediate_fetch = lambda: None
        bus.publish("weather.search_location", {"lat": 41.9, "lon": 12.5, "city": "Roma"})
        bus.publish("gps.position", WARSAW)                # before the thread fetches
        lats = []
        bus.subscribe("weather.lat", lambda t, v, ts: lats.append(v))
        WeatherManager._immediate_fetch(wm)
        assert wm.used == [(41.9, 12.5)] and lats == [41.9]

    def test_force_fetch_min_age_and_its_override(self):
        wm, bus, clock, attempts = make(results=[GOOD])
        wm._poll_once()
        clock.advance(10)
        assert wm.force_fetch("again") is False
        assert wm.force_fetch("first GPS fix", ignore_min_age=True) is True
        assert wm._next_fetch == 0.0


class TestDistanceRefetch:
    def _driving(self, **cfg):
        wm, bus, clock, attempts = make(results=[GOOD] * 5, **cfg)
        bus.publish("gps.position", fix(*KRAKOW))
        wm._poll_once()                                    # GPS-based fetch
        assert wm._fetch_source == "gps"
        clock.advance(FORCE_MIN_AGE_S + 60)
        return wm, bus, clock, attempts

    def test_moving_more_than_15_km_refetches_once(self):
        wm, bus, clock, attempts = self._driving()
        bus.publish("gps.position", fix(50.15, 19.94))     # ~10 km
        wm._poll_once()
        assert len(attempts) == 1
        bus.publish("gps.position", fix(50.24, 19.94))     # ~20 km
        bus.publish("gps.position", fix(50.25, 19.94))     # no second force
        wm._poll_once()
        assert len(attempts) == 2 and wm.used[-1] == (50.25, 19.94)
        # measured from the new place now
        clock.advance(FORCE_MIN_AGE_S + 1)
        bus.publish("gps.position", fix(50.30, 19.94))
        wm._poll_once()
        assert len(attempts) == 2

    def test_a_failing_refetch_does_not_force_on_every_fix(self):
        wm, bus, clock, attempts = make(results=[GOOD])
        bus.publish("gps.position", fix(*KRAKOW))
        wm._poll_once()
        clock.advance(FORCE_MIN_AGE_S + 60)
        bus.publish("gps.position", fix(50.30, 19.94))     # ~27 km: force
        wm._poll_once()                                    # fails -> backoff 60 s
        assert len(attempts) == 2
        for _ in range(10):                                # 1 Hz fixes while offline
            clock.advance(1)
            bus.publish("gps.position", fix(50.31, 19.94))
            wm._poll_once()
        assert len(attempts) == 2 and wm._retry_delay == 120

    @pytest.mark.parametrize("value", [0, 0.0])
    def test_zero_turns_it_off(self, value):
        wm, bus, clock, attempts = self._driving(refetch_distance_km=value)
        bus.publish("gps.position", fix(51.0, 19.94))      # ~100 km
        wm._poll_once()
        assert len(attempts) == 1

    @pytest.mark.parametrize("value, expected", [
        (None, 15.0), (5, 5.0), (2.5, 2.5), (-1, 15.0), ("10", 15.0),
        (True, 15.0), (float("nan"), 15.0), (float("inf"), 15.0),
    ])
    def test_config_value(self, value, expected):
        cfg = {} if value is None else {"refetch_distance_km": value}
        wm, *_ = make(**cfg)
        assert wm._refetch_km == expected

    def test_distance_helper(self):
        assert wmod._distance_km(KRAKOW, KRAKOW) == 0.0
        assert wmod._distance_km((50.0, 20.0), (51.0, 20.0)) == pytest.approx(111.2, abs=0.2)


class _Resp:
    def __init__(self, body):
        self._body = json.dumps(body).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_request_parameters_are_url_encoded(monkeypatch):
    urls = []

    def fake_urlopen(req, timeout=None):
        urls.append(req.full_url)
        if "forecast" in req.full_url:
            return _Resp({"list": []})
        return _Resp({"weather": [{"description": "clear", "icon": "01d"}],
                      "main": {"temp": 10}, "wind": {}, "name": "X", "sys": {}})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    wm = WeatherManager(EventBus(), {"weather": {"api_key": "a&units=imperial"}}, "x86")
    wm._lat, wm._lon = 50.06, 19.94
    assert wm._fetch_weather()["city"] == "X"
    for url in urls:
        q = parse_qs(urlsplit(url).query)
        assert q["appid"] == ["a&units=imperial"]
        assert q["units"] == ["metric"]
        assert q["lat"] == ["50.06"] and q["lon"] == ["19.94"]
    assert parse_qs(urlsplit(urls[1]).query)["cnt"] == ["24"]
