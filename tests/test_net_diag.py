"""Internet and API key diagnostics (Partia 12, stage 1).

* src/network/net_probe.py — default route / DNS / HTTPS probe with a fake
  runner, resolver and HTTPS seam; the rate limit;
* car_phone / phone_tether — "connected" plus ``internet`` and the hint;
* src/network/net_services.py — key presence, per-service results, the
  "Test" run (fake HTTP; keys never in a result);
* weather.status transitions (demo → live, 401, network error);
* RoutePlanner service errors and their way into the trip plan;
* secret stripping in BCMConfig and the start-up warning list;
* POST /api/net/test (loopback only, rate limit, no key in any answer),
  /api/debug/weather and the payload summary.

Nothing touches the network, adb, nmcli or the real config files.
"""

import io
import json
import subprocess
import threading
import urllib.error
from types import SimpleNamespace

import pytest

from src.core.config import BCMConfig, missing_secrets
from src.core.event_bus import EventBus
from src.dashboard import web_viewer as wv
from src.dashboard.trip_computer import _service_errors
from src.dashboard.web_viewer import WebViewer
from src.network import net_probe as npr
from src.network import net_services as ns
from src.trip import route_planner as rp
from src.weather import weather as wmod

SECRET = "SeCrEt-KeY-0123456789abcdef"


@pytest.fixture(autouse=True)
def clean_services(monkeypatch):
    ns.reset()
    # A fresh shared probe per test (the payload reads its last result).
    monkeypatch.setattr(npr, "_shared", None)
    yield
    ns.reset()


# ── net_probe ─────────────────────────────────────────────────────────────

class FakeRun:
    def __init__(self, rc=0, out="1.1.1.1 via 192.168.42.129 dev usb0 src 192.168.42.10 uid 0\n"
                                    "    cache \n", err=""):
        self.rc, self.out, self.err = rc, out, err
        self.calls = []

    def __call__(self, argv, **kw):
        self.calls.append((argv, kw))
        return subprocess.CompletedProcess(argv, self.rc, self.out, self.err)


def _probe(run=None, dns=(True, ""), https=(True, 204, "")):
    return npr.probe_internet(runner=run or FakeRun(), resolver=lambda h, t: dns,
                              https=lambda u, t: https, wall_clock=lambda: 1.7e9)


class TestProbe:
    def test_all_good(self):
        run = FakeRun()
        res = _probe(run)
        assert res == {"ok": True, "iface": "usb0", "dns_ok": True, "https_ok": True,
                       "error": "", "detail": "", "checked_at": 1.7e9}
        argv, kw = run.calls[0]
        assert argv == ["ip", "-4", "route", "get", "1.1.1.1"]      # argv list, no shell
        assert "shell" not in kw and kw["timeout"] <= npr.STEP_TIMEOUT_S

    def test_no_default_route(self):
        res = _probe(FakeRun(rc=2, out="", err="RTNETLINK answers: Network is unreachable"))
        assert res["ok"] is False and res["error"] == "no_route" and res["iface"] == ""
        assert "unreachable" in res["detail"]

    def test_other_interface_holds_the_route(self):
        res = _probe(FakeRun(out="1.1.1.1 via 192.168.1.1 dev wlan0 src 192.168.1.5\n"),
                     https=(False, None, "timed out"))
        assert res["iface"] == "wlan0" and res["error"] == "https"

    def test_dns_failure(self):
        res = _probe(dns=(False, "[Errno -3] Temporary failure in name resolution"))
        assert res["ok"] is False and res["error"] == "dns" and res["dns_ok"] is False
        assert res["iface"] == "usb0" and res["https_ok"] is False

    def test_https_failure(self):
        res = _probe(https=(False, None, "certificate verify failed"))
        assert res["error"] == "https" and res["dns_ok"] is True and res["ok"] is False

    def test_any_http_status_counts_as_reached(self):
        assert _probe(https=(True, 404, ""))["ok"] is True

    @pytest.mark.parametrize("text", ["", "garbage", "1.1.1.1 dev ;rm -rf /\n",
                                      "1.1.1.1 dev " + "x" * 40])
    def test_bad_route_output_is_no_route(self, text):
        assert npr.parse_route_get(text) is None

    def test_missing_ip_binary(self):
        def run(argv, **kw):
            raise FileNotFoundError(argv[0])
        assert _probe(run)["error"] == "no_route"

    def test_resolver_times_out(self):
        gate = threading.Event()
        orig = npr.socket.getaddrinfo
        npr.socket.getaddrinfo = lambda *a, **k: gate.wait(5) or []
        try:
            ok, err = npr.default_resolver("example.org", 0.05)
        finally:
            gate.set()
            npr.socket.getaddrinfo = orig
        assert ok is False and "timeout" in err


class TestProbeRateLimit:
    def test_cached_for_60_s_force_floor_5_s(self):
        clock = SimpleNamespace(t=100.0)
        n = []
        probe = npr.InternetProbe(probe=lambda: n.append(1) or {"ok": True, "iface": "usb0",
                                                                "error": ""},
                                  clock=lambda: clock.t)
        probe.check()
        clock.t += 30
        probe.check()
        assert len(n) == 1                       # cached
        probe.check(force=True)
        assert len(n) == 2                       # forced (30 s > 5 s floor)
        clock.t += 2
        probe.check(force=True)
        assert len(n) == 2                       # floor
        clock.t += 61
        probe.check()
        assert len(n) == 2                       # OK → re-checked only every 10 min
        clock.t += npr.OK_INTERVAL_S
        probe.check()
        assert len(n) == 3

    def test_failed_result_is_rechecked_after_60_s(self):
        clock = SimpleNamespace(t=100.0)
        n = []
        probe = npr.InternetProbe(probe=lambda: n.append(1) or {"ok": False, "iface": "usb0",
                                                                "error": "dns"},
                                  clock=lambda: clock.t)
        probe.check()
        clock.t += 59
        probe.check()
        assert len(n) == 1
        clock.t += 2
        probe.check()
        assert len(n) == 2

    def test_broken_seam_is_a_result_not_a_crash(self):
        def boom():
            raise RuntimeError("x")
        res = npr.InternetProbe(probe=boom).check()
        assert res["ok"] is False and res["error"] == "no_route"


class TestProbeNeverBlocksReaders:
    """A probe on a phone without internet takes up to 2×5 s; the dashboard
    broadcast loop reads ``last`` ~15×/s and must never wait for it."""

    def _slow(self, first=None):
        gate = threading.Event()
        started = threading.Event()
        calls = []

        def probe():
            calls.append(1)
            if len(calls) == 1 and first is not None:
                return dict(first)
            started.set()
            gate.wait(5)
            return {"ok": True, "iface": "usb0", "dns_ok": True, "https_ok": True,
                    "error": "", "detail": "", "checked_at": 1.7e9}
        return probe, gate, started, calls

    def test_last_and_check_return_at_once_while_probing(self):
        import time as _t
        first = {"ok": False, "iface": "usb0", "dns_ok": False, "https_ok": False,
                 "error": "dns", "detail": "", "checked_at": 1.7e9}
        probe_fn, gate, started, calls = self._slow(first)
        clock = SimpleNamespace(t=100.0)
        p = npr.InternetProbe(probe=probe_fn, clock=lambda: clock.t)
        assert p.check()["error"] == "dns"            # cached first result
        clock.t += 120
        th = threading.Thread(target=p.check, daemon=True)
        th.start()
        assert started.wait(2)
        for call in (lambda: p.last, p.check, lambda: p.check(force=True)):
            t0 = _t.monotonic()
            res = call()
            assert _t.monotonic() - t0 < 0.05
            assert res["error"] == "dns"              # the cached answer
        gate.set()
        th.join(2)
        assert p.last["ok"] is True and len(calls) == 2
        clock.t += 1
        assert p.check()["ok"] is True                # stored and returned

    def test_first_probe_in_progress_is_unknown(self):
        import time as _t
        probe_fn, gate, started, _calls = self._slow()
        p = npr.InternetProbe(probe=probe_fn)
        th = threading.Thread(target=p.check, daemon=True)
        th.start()
        assert started.wait(2)
        t0 = _t.monotonic()
        assert p.last is None
        res = p.check(force=True)
        assert _t.monotonic() - t0 < 0.05
        assert res.get("pending") is True
        assert npr.internet_fields(p, "usb0")["internet"] is None
        gate.set()
        th.join(2)
        assert p.last["ok"] is True and "pending" not in p.last


class FixedProbe:
    def __init__(self, ok, iface="usb0", error=""):
        self.res = {"ok": ok, "iface": iface, "dns_ok": ok, "https_ok": ok,
                    "error": error, "detail": "", "checked_at": 1.7e9}
        self.forced = []

    def check(self, force=False):
        self.forced.append(force)
        return dict(self.res)

    @property
    def last(self):
        return dict(self.res)


class TestInternetFields:
    def test_no_probe_is_unknown(self):
        assert npr.internet_fields(None, "usb0") == {"internet": None, "route_iface": "",
                                                     "internet_error": "", "hint": ""}

    def test_ok(self):
        assert npr.internet_fields(FixedProbe(True), "usb0")["hint"] == ""

    def test_this_link_without_internet(self):
        f = npr.internet_fields(FixedProbe(False, "usb0", "dns"), "usb0")
        assert f == {"internet": False, "route_iface": "usb0", "internet_error": "dns",
                     "hint": "no_internet"}

    def test_other_link_wins_the_route(self):
        f = npr.internet_fields(FixedProbe(False, "wlan0", "https"), "usb0")
        assert f["hint"] == "route_other" and f["route_iface"] == "wlan0"


# ── car_phone / phone_tether ──────────────────────────────────────────────

class TestCarPhoneInternet:
    @pytest.fixture
    def connected(self, tmp_path):
        from tests.test_car_phone import GOOD_PROFILE, FakeClock, FakePhone
        from src.network import car_phone as cp
        fake = FakePhone()
        fake.profile = dict(GOOD_PROFILE)
        fake.link = "activated"
        adb_dir = tmp_path / "adb"
        fake.adb_socket = str(adb_dir / cp.ADB_SOCKET_NAME)
        sysctl = tmp_path / "sysctl"
        sysctl.write_text("1024\n")
        (tmp_path / "usb").mkdir()
        clock = FakeClock()
        bus = EventBus()
        published = []
        bus.subscribe(cp.TOPIC, lambda t, v, ts: published.append(v))

        def make(probe):
            phone = cp.CarPhone({"network": {"car_phone": {"time_sync": False}},
                                 "hardware": {"gps": {"tcp": {"port": 50000}}}}, bus,
                                runner=fake, clock=clock.mono, wall_clock=clock.wall,
                                boot_clock=clock.boot, usb_root=str(tmp_path / "usb"),
                                marker_path=str(tmp_path / "m"), adb_socket_dir=str(adb_dir),
                                port_sysctl=str(sysctl), notify=lambda *a, **k: None,
                                net_probe=probe)
            return phone
        return make, published

    def test_connected_without_internet_says_so(self, connected):
        make, published = connected
        probe = FixedProbe(False, "usb0", "dns")
        phone = make(probe)
        assert phone.tick() == "connected"
        last = published[-1]
        assert last["state"] == "connected"                   # state stays connected
        assert last["internet"] is False and last["hint"] == "no_internet"
        assert last["route_iface"] == "usb0" and last["internet_error"] == "dns"
        assert probe.forced == [True]                         # fresh edge forces a probe
        phone.tick()
        assert probe.forced == [True, False]                  # later passes use the cache

    def test_connected_with_internet(self, connected):
        make, published = connected
        phone = make(FixedProbe(True, "usb0"))
        phone.tick()
        assert published[-1]["internet"] is True and published[-1]["hint"] == ""

    def test_without_probe_internet_is_none(self, connected):
        make, published = connected
        make(None).tick()
        assert published[-1]["internet"] is None

    def test_entry_point_uses_the_probe_only_with_net_diag(self, monkeypatch):
        from src.network import car_phone as cp
        seen = []
        monkeypatch.setattr(cp.CarPhone, "start", lambda self: seen.append(self._probe))
        cp.start_car_phone({"modules": {"net_diag": True}}, EventBus())
        cp.start_car_phone({"modules": {"net_diag": "yes"}}, EventBus())
        assert isinstance(seen[0], npr.InternetProbe) and seen[1] is None


class TestPhoneTetherInternet:
    def _connected(self, probe):
        from tests.test_phone_tether import PHONE, make, phone_connected
        tether, bus, nm, clock, published = make()
        tether._probe = probe
        nm.bt_devices[PHONE] = "disconnected"
        phone_connected(bus)
        assert tether.tick() == "connected"
        return published

    def test_no_internet_hint(self):
        last = self._connected(FixedProbe(False, "bnep0", "https"))[-1]
        assert last["state"] == "connected" and last["internet"] is False
        assert last["hint"] == "no_internet" and last["internet_error"] == "https"

    def test_route_other(self):
        last = self._connected(FixedProbe(False, "usb0", "dns"))[-1]
        assert last["hint"] == "route_other" and last["route_iface"] == "usb0"

    def test_internet_ok_through_another_uplink(self):
        last = self._connected(FixedProbe(True, "usb0"))[-1]
        assert last["internet"] is True and last["hint"] == "" and last["route_iface"] == "usb0"


# ── net_services ──────────────────────────────────────────────────────────

class FakeHTTP:
    def __init__(self, answers):
        self.answers = answers          # host substring -> (status, body) | Exception
        self.calls = []

    def __call__(self, method, url, headers, timeout):
        self.calls.append((method, url, dict(headers)))
        for key, ans in self.answers.items():
            if key in url:
                if isinstance(ans, BaseException):
                    raise ans
                return ans
        raise AssertionError(url)


def _cfg(**keys):
    return {"weather": {"api_key": keys.get("owm", ""), "default_lat": 50.0, "default_lon": 20.0},
            "travel": {"openrouteservice_key": keys.get("ors", ""),
                       "tomtom_key": keys.get("tomtom", "")}}


class TestServices:
    def test_key_presence_only_booleans(self):
        pres = ns.key_presence(_cfg(owm=SECRET, ors="  "))
        assert pres == {"owm": True, "ors": False, "tomtom": False}

    def test_run_test_records_and_never_returns_a_key(self):
        http = FakeHTTP({
            "openweathermap": (200, json.dumps({"main": {"temp": 3}}).encode()),
            "api.heigit.org": (401, b""),
            "tomtom": urllib.error.URLError("timed out"),
        })
        bus = EventBus()
        seen = []
        bus.subscribe("net.test_result", lambda t, v, ts: seen.append(v))
        out = ns.run_test(_cfg(owm=SECRET, ors=SECRET, tomtom=SECRET),
                          probe=FixedProbe(True), bus=bus, http=http)
        assert out["services"] == {"owm": {"result": "ok", "http_code": None},
                                   "ors": {"result": "http", "http_code": 401},
                                   "tomtom": {"result": "network", "http_code": None}}
        assert SECRET not in json.dumps(out) and SECRET not in json.dumps(ns.snapshot())
        assert seen and SECRET not in json.dumps(seen)
        snap = ns.snapshot()
        assert snap["ors"]["result"] == "http" and snap["ors"]["source"] == "test"
        # ORS key in the header, never in the URL.
        ors_call = [c for c in http.calls if "api.heigit.org/pelias" in c[1]][0]
        assert SECRET not in ors_call[1] and ors_call[2]["Authorization"] == SECRET

    def test_no_key_no_request(self):
        http = FakeHTTP({})
        out = ns.run_test(_cfg(), probe=None, http=http)
        assert http.calls == []
        assert {v["result"] for v in out["services"].values()} == {"no_key"}
        assert ns.snapshot()["owm"]["result"] == "untested"

    def test_bad_json_is_bad_response(self):
        http = FakeHTTP({"openweathermap": (200, b"<html>")})
        assert ns.check_owm(SECRET, 50, 20, http)["result"] == "bad_response"

    def test_record_folds_unknown_values(self):
        ns.record("owm", "weird", 999)
        assert ns.snapshot()["owm"]["result"] == "network"
        ns.record("nope", "ok")
        assert "nope" not in ns.snapshot()


# ── weather.status ────────────────────────────────────────────────────────

@pytest.fixture
def weather(tmp_path, monkeypatch):
    monkeypatch.setattr(wmod, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(wmod, "CACHE_FILE", tmp_path / "weather.json")
    bus = EventBus()
    statuses = []
    bus.subscribe("weather.status", lambda t, v, ts: statuses.append(dict(v)))

    def make(key=" " + SECRET + "\n"):
        wm = wmod.WeatherManager(bus, {"weather": {"api_key": key}}, "x86")
        return wm
    return make, statuses, monkeypatch


def _resp(payload):
    class R(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    return R(json.dumps(payload).encode())


class TestWeatherStatus:
    def test_key_is_stripped(self, weather):
        make, statuses, mp = weather
        assert make()._api_key == SECRET

    def test_demo_then_live(self, weather):
        make, statuses, mp = weather
        wm = make()
        wm._publish_data(wmod.DEMO_WEATHER)
        wm._publish_status(source="demo")
        assert statuses[-1]["source"] == "demo" and statuses[-1]["key_set"] is True
        mp.setattr("urllib.request.urlopen", lambda req, timeout=None: _resp(
            {"main": {"temp": 5}, "weather": [{}], "name": "X", "list": []}))
        assert wm._poll_once() is True
        st = statuses[-1]
        assert st["source"] == "live" and st["last_error"] == "" and st["last_ok_ts"]
        assert ns.snapshot()["owm"]["result"] == "ok"

    def test_401_keeps_demo_and_names_the_code(self, weather):
        make, statuses, mp = weather
        wm = make()

        def deny(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, None)
        mp.setattr("urllib.request.urlopen", deny)
        wm._poll_once()
        st = statuses[-1]
        assert st["source"] == "demo" and st["last_error"] == "http" and st["http_code"] == 401
        assert ns.snapshot()["owm"] == dict(ns.snapshot()["owm"], result="http", http_code=401)
        assert SECRET not in json.dumps(statuses)

    def test_network_error(self, weather):
        make, statuses, mp = weather
        wm = make()

        def down(req, timeout=None):
            raise urllib.error.URLError("Temporary failure in name resolution")
        mp.setattr("urllib.request.urlopen", down)
        wm._poll_once()
        assert statuses[-1]["last_error"] == "network" and statuses[-1]["http_code"] is None

    def test_unexpected_field_types_are_bad_response(self, weather):
        make, statuses, mp = weather
        wm = make()
        mp.setattr("urllib.request.urlopen", lambda req, timeout=None: _resp(
            {"main": {"temp": "warm"}, "weather": [{}], "name": "X", "list": []}))
        wm._poll_once()
        assert statuses[-1]["last_error"] == "bad_response"
        assert ns.snapshot()["owm"]["result"] == "bad_response"

    def test_no_key_status(self, weather):
        make, statuses, mp = weather
        wm = make(key="   ")
        assert wm.status["last_error"] == "no_key" and wm.status["key_set"] is False


# ── route planner ─────────────────────────────────────────────────────────

class FakeResp:
    def __init__(self, status, payload=None, text=""):
        self.status_code = status
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class TestRoutePlannerErrors:
    def _planner(self, monkeypatch, post=None, get=None):
        import requests
        if post is not None:
            monkeypatch.setattr(requests, "post", post)
        if get is not None:
            monkeypatch.setattr(requests, "get", get)
        cfg = BCMConfig(platform_override="x86")
        cfg.set("travel.openrouteservice_key", SECRET + " ")
        cfg.set("travel.tomtom_key", SECRET)
        return rp.RoutePlanner(cfg)

    def test_ors_401_reaches_the_plan(self, monkeypatch, caplog):
        planner = self._planner(monkeypatch,
                                post=lambda *a, **k: FakeResp(401, text="Unauthorized"))
        assert planner._ors_key == SECRET                     # stripped
        plan = planner.plan((50.0, 20.0), (50.1, 20.1))
        assert plan["error"] == "route_unavailable"
        assert plan["service_errors"] == [{"service": "ors", "result": "http",
                                           "http_code": 401}]
        assert ns.snapshot()["ors"]["result"] == "http"
        assert SECRET not in caplog.text

    def test_tomtom_network_error_is_reported_and_url_not_logged(self, monkeypatch, caplog):
        route = {"features": [{"properties": {"summary": {"distance": 10, "duration": 600}},
                               "geometry": {"coordinates": [[20.0, 50.0], [20.1, 50.1]]}}]}

        def get(url, params=None, **kw):
            raise ConnectionError(f"failed {url}?key={params.get('key')}")
        planner = self._planner(monkeypatch, post=lambda *a, **k: FakeResp(200, route), get=get)
        plan = planner.plan((50.0, 20.0), (50.1, 20.1))
        assert "error" not in plan and plan["distance_km"] == 10
        assert plan["service_errors"] == [{"service": "tomtom", "result": "network",
                                           "http_code": None}]
        assert SECRET not in caplog.text

    def test_overlapping_plans_keep_their_own_errors(self, monkeypatch):
        # Two trip-computer workers can plan at once: plan B (TomTom
        # down) must not show plan A's ORS 401, nor wipe it.
        route = {"features": [{"properties": {"summary": {"distance": 10, "duration": 600}},
                               "geometry": {"coordinates": [[20.0, 50.0], [20.1, 50.1]]}}]}
        a_in_ors = threading.Event()
        b_done = threading.Event()

        def post(url, json=None, **kw):
            if json["coordinates"][1][1] == 50.1:      # plan A
                a_in_ors.set()
                b_done.wait(2)
                return FakeResp(401, text="Unauthorized")
            return FakeResp(200, route)

        def get(url, params=None, **kw):
            raise ConnectionError("down")
        planner = self._planner(monkeypatch, post=post, get=get)
        out = {}
        th = threading.Thread(target=lambda: out.setdefault(
            "a", planner.plan((50.0, 20.0), (50.1, 20.1))), daemon=True)
        th.start()
        assert a_in_ors.wait(2)
        out["b"] = planner.plan((50.0, 20.0), (50.2, 20.2))
        b_done.set()
        th.join(2)
        assert [e["service"] for e in out["a"]["service_errors"]] == ["ors"]
        assert [e["service"] for e in out["b"]["service_errors"]] == ["tomtom"]

    def test_trip_computer_sanitises_service_errors(self):
        raw = [{"service": "ors", "result": "http", "http_code": 401, "x": "<b>"},
               {"service": "<script>", "result": "http"},
               {"service": "tomtom", "result": "network", "http_code": True},
               "junk"]
        assert _service_errors(raw) == [
            {"service": "ors", "result": "http", "http_code": 401},
            {"service": "tomtom", "result": "network", "http_code": None}]
        assert _service_errors(None) == []


# ── config secrets ────────────────────────────────────────────────────────

class TestSecrets:
    def test_values_are_stripped_and_blank_ignored(self, tmp_path):
        env = tmp_path / "bcm.env"
        env.write_text("BCM_ORS_API_KEY=  abc123 \r\nBCM_TOMTOM_API_KEY=   \n")
        env.chmod(0o600)
        cfg = BCMConfig(platform_override="x86", local_path=None,
                        env={"BCM_OWM_API_KEY": "\tkey-owm \n"}, dotenv_path=str(env))
        assert cfg.get("weather.api_key") == "key-owm"
        assert cfg.get("travel.openrouteservice_key") == "abc123"
        assert "travel.tomtom_key" not in cfg.secret_sources

    def test_missing_secrets_names_only(self):
        cfg = BCMConfig(platform_override="x86", local_path=None,
                        env={"BCM_OWM_API_KEY": SECRET})
        cfg.set("travel.openrouteservice_key", "")
        missing = {var for var, _path, _why in missing_secrets(cfg)}
        assert "BCM_OWM_API_KEY" not in missing and "BCM_ORS_API_KEY" in missing
        assert SECRET not in repr(missing_secrets(cfg))

    def test_missing_secrets_only_enabled_modules(self):
        # A key of a module that is off is not warned about (journal noise).
        cfg = BCMConfig(platform_override="x86", local_path=None, env={})
        for path in ("weather.api_key", "travel.openrouteservice_key",
                     "travel.tomtom_key", "network.car_phone.agent.secret"):
            cfg.set(path, "")
        cfg.set("modules.weather", False)
        cfg.set("modules.route_planner", True)
        cfg.set("modules.car_phone_agent", False)
        cfg.set("modules.traccar", False)
        cfg.set("modules.voice_announce", False)
        missing = {var for var, _p, _w in missing_secrets(cfg, only_enabled=True)}
        assert missing == {"BCM_ORS_API_KEY", "BCM_TOMTOM_API_KEY"}
        cfg.set("modules.car_phone_agent", True)
        missing = {var for var, _p, _w in missing_secrets(cfg, only_enabled=True)}
        assert "BCM_CAR_PHONE_AGENT_SECRET" in missing
        # Without the filter every missing key is listed (traccar.device_id
        # and the Azure voice key are not set at all here).
        assert len(missing_secrets(cfg)) == 6
        cfg.set("modules.traccar", True)
        missing = {var for var, _p, _w in missing_secrets(cfg, only_enabled=True)}
        assert "BCM_TRACCAR_DEVICE_ID" in missing
        cfg.set("modules.voice_announce", True)
        missing = {var for var, _p, _w in missing_secrets(cfg, only_enabled=True)}
        assert "BCM_AZURE_TTS_KEY" in missing


# ── web: payload, /api/net/test, /api/debug/weather ───────────────────────

@pytest.fixture
def web(monkeypatch):
    bus = EventBus()
    cfg = BCMConfig(platform_override="x86", local_path=None, env={})
    cfg.save = lambda path=None: None
    cfg.set("modules.net_diag", True)
    cfg.set("weather.api_key", SECRET)
    cfg.set("travel.openrouteservice_key", SECRET)
    cfg.set("travel.tomtom_key", "")
    viewer = WebViewer(host="127.0.0.1", port=5099, event_bus=bus, config=cfg)
    ran = []
    done = threading.Event()

    def runner(config, probe, event_bus):
        ran.append(config)
        ns.record("owm", "http", 401, source="test")
        done.set()
        return {"keys": ns.key_presence(config)}
    viewer._net_test_runner = runner
    monkeypatch.setattr(npr, "_shared", npr.InternetProbe(probe=lambda: {
        "ok": False, "iface": "wlan0", "dns_ok": False, "https_ok": False,
        "error": "dns", "detail": "x", "checked_at": 1.7e9}))
    client = viewer._build_app().test_client()
    return SimpleNamespace(bus=bus, cfg=cfg, viewer=viewer, client=client, ran=ran, done=done)


class TestNetDiagStaleProbe:
    def _cfg(self):
        cfg = BCMConfig(platform_override="x86", local_path=None, env={})
        cfg.set("modules.net_diag", True)
        return cfg

    def _probe(self, monkeypatch, ok, iface, checked_at):
        p = npr.InternetProbe(probe=lambda: {
            "ok": ok, "iface": iface, "dns_ok": ok, "https_ok": ok,
            "error": "" if ok else "dns", "detail": "", "checked_at": checked_at})
        p.check()
        monkeypatch.setattr(npr, "_shared", p)

    def test_unplugged_phone_no_longer_claims_internet(self, monkeypatch):
        import time as _t
        self._probe(monkeypatch, True, "rndis0", _t.time() - 600)
        out = wv._net_diag_summary(self._cfg(), None,
                                   {"state": "disconnected", "iface": "rndis0"}, False, None)
        assert out["uplink"]["internet"] is None
        assert out["uplink"]["kind"] != "other" and out["probe"] is None

    def test_connected_uplink_keeps_an_old_probe(self, monkeypatch):
        # A long check_sec must not make the row flicker to "unknown".
        import time as _t
        self._probe(monkeypatch, True, "rndis0", _t.time() - 600)
        out = wv._net_diag_summary(self._cfg(), None,
                                   {"state": "connected", "iface": "rndis0"}, False, None)
        assert out["uplink"] == {"kind": "usb", "iface": "rndis0", "internet": True}

    def test_fresh_probe_of_other_uplink_is_shown(self, monkeypatch):
        import time as _t
        self._probe(monkeypatch, False, "wlan0", _t.time() - 5)
        out = wv._net_diag_summary(self._cfg(), None, None, False, None)
        assert out["uplink"]["kind"] == "other" and out["uplink"]["internet"] is False


class TestNetTestRoute:
    def test_starts_a_worker_and_returns_202(self, web):
        res = web.client.post("/api/net/test")
        assert res.status_code == 202 and res.get_json() == {"ok": True, "started": True}
        assert web.done.wait(2)
        assert SECRET not in res.get_data(as_text=True)

    def test_rate_limited(self, web):
        assert web.client.post("/api/net/test").status_code == 202
        web.done.wait(2)
        res = web.client.post("/api/net/test")
        assert res.status_code == 429 and int(res.headers["Retry-After"]) >= 1

    def test_busy(self, web):
        web.viewer._net_test_running = True
        res = web.client.post("/api/net/test")
        assert res.status_code == 409 and res.get_json()["error"] == "busy"

    @pytest.mark.parametrize("addr, base", [
        ("10.0.0.5", "http://localhost"),
        ("127.0.0.1", "http://evil.example:5002"),      # DNS rebinding
    ])
    def test_loopback_kiosk_only(self, web, addr, base):
        res = web.client.post("/api/net/test", environ_base={"REMOTE_ADDR": addr},
                              base_url=base)
        assert res.status_code == 403 and web.ran == []

    def test_foreign_origin_refused(self, web):
        res = web.client.post("/api/net/test", headers={"Origin": "http://evil.example"})
        assert res.status_code == 403

    def test_disabled_module(self, web):
        web.cfg.set("modules.net_diag", False)
        assert web.client.post("/api/net/test").status_code == 409

    def test_payload_has_flags_only(self, web):
        web.client.post("/api/net/test")
        web.done.wait(2)
        npr.shared_probe().check()
        web.bus.publish("net.car_phone", {"state": "connected", "iface": "usb0",
                                          "internet": False, "route_iface": "wlan0",
                                          "internet_error": "dns", "hint": "route_other"})
        data = web.viewer._get_dashboard_data()
        nd = data["net_diag"]
        assert nd["services"]["owm"] == dict(nd["services"]["owm"], key_set=True,
                                             result="http", http_code=401)
        assert nd["services"]["tomtom"]["key_set"] is False
        assert nd["uplink"] == {"kind": "other", "iface": "wlan0", "internet": False}
        assert nd["probe"]["error"] == "dns"
        assert data["car_phone"]["internet"] is False
        assert data["car_phone"]["hint"] == "route_other"
        assert SECRET not in json.dumps(data, default=str)

    def test_net_diag_none_when_off(self, web):
        web.cfg.set("modules.net_diag", False)
        assert web.viewer._get_dashboard_data()["net_diag"] is None

    def test_debug_weather_presence_only(self, web):
        web.bus.publish("weather.status", {"source": "demo", "last_error": "http",
                                           "http_code": 401, "key_set": True})
        body = web.client.get("/api/debug/weather").get_json()
        assert body["keys_set"] == {"owm": True, "ors": True, "tomtom": False}
        assert body["weather_status"]["http_code"] == 401
        assert "car_phone" in body and "phone_tether" in body
        assert SECRET not in json.dumps(body)

    def test_search_no_key_is_a_code(self, web):
        web.cfg.set("weather.api_key", "")
        res = web.client.get("/api/trip/search?q=Krak")
        assert res.status_code == 400 and res.get_json()["error"] == "no_key"

    def test_search_401_is_a_code_without_url(self, web, monkeypatch):
        def deny(method, url, headers, timeout):
            raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, None)
        monkeypatch.setattr(ns, "default_http", deny)
        res = web.client.get("/api/weather/search?q=Krak")
        body = res.get_json()
        assert res.status_code == 502 and body == {"results": [], "error": "http",
                                                   "http_code": 401}
        assert ns.snapshot()["owm"]["source"] == "search"

    def test_search_results_are_validated(self, web, monkeypatch):
        raw = [{"name": "Kraków", "country": "PL", "lat": 50.06, "lon": 19.94},
               {"name": "bad", "lat": "x", "lon": 1}, "junk"]
        monkeypatch.setattr(ns, "default_http",
                            lambda m, u, h, t: (200, json.dumps(raw).encode()))
        body = web.client.get("/api/trip/search?q=Krak").get_json()
        assert body["results"] == [{"name": "Kraków", "country": "PL", "state": "",
                                    "lat": 50.06, "lon": 19.94}]

    def test_weather_status_summary_sanitises(self):
        out = wv._weather_status_summary({"source": "<x>", "last_error": "boom",
                                          "http_code": 9999, "last_ok_ts": float("nan"),
                                          "key_set": "yes"})
        assert out == {"source": "demo", "last_ok_ts": None, "last_attempt_ts": None,
                       "last_error": "", "http_code": None, "key_set": False}
        assert wv._weather_status_summary(None) is None


def test_net_test_route_is_post_only_and_not_readonly():
    assert "api_net_test" not in wv._READONLY_ENDPOINTS


def test_ors_uses_heigit_host():
    """OpenRouteService moved to HeiGIT (2026): the old host answers 410."""
    from src.network import net_services as ns_mod
    from src.trip import route_planner as rp
    assert ns_mod.ORS_GEOCODE == rp.ORS_GEOCODE == "https://api.heigit.org/pelias/v1/search"
    assert rp.ORS_DIRECTIONS == "https://api.heigit.org/openrouteservice/v2/directions/driving-car"
