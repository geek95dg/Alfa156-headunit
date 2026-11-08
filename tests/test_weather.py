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


def make(platform="x86", api_key="k", poll_min=15, results=None):
    """Manager wired like start() does, minus the thread."""
    bus = EventBus()
    clock = FakeClock()
    wm = WeatherManager(bus, {"weather": {"api_key": api_key, "poll_interval_min": poll_min,
                                          "default_lat": 50.06, "default_lon": 19.94}},
                        platform, clock=clock)
    attempts = []
    results = list(results or [])

    def fetch():
        attempts.append(clock.t)
        return results.pop(0) if results else None

    wm._fetch_weather = fetch
    bus.subscribe("gps.position", wm._on_gps_position)
    bus.subscribe("lte.connected", wm._on_lte_status)
    bus.subscribe("net.phone_tether", wm._on_phone_tether)
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

        def boom():
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

        def fetch():
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
        assert (wm._lat, wm._lon) == (50.06, 19.94)      # default location used

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
