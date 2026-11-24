"""Traccar (BCM's side, src/network/traccar.py) and the last parked position
(src/location/last_park.py), plus their dashboard summaries, the
"Wyślij pozycję teraz" route and the /trips section.

Nothing here talks to a network or a phone: the agent is a fake object,
files live in tmp_path, Flask runs in its test client.

Covers: the URL rules (the same verdict as the agent's), the settings for
the config push (invalid URL / id → "" with a warning that never contains
them, clamped intervals), the secret's place in SECRET_ENV_MAP, the agent
view parser, the module (not configured, BCM's fresh fix sent with "send
now", a stale one not, busy, agent errors, payload without URL or id), the
agent_outdated reason, the last-park persistence (a minute standing still,
not again within 25 m, trip end / ignition / shutdown, stale fixes, a
damaged file, 0600, reload at start), the summaries (whitelists, map links
built from numbers only), the route (kiosk only even in "full", JSON {}
only, rate limit, not running) and /trips (escaped links, tracking mode).
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core.config import SECRET_ENV_MAP, BCMConfig
from src.core.event_bus import EventBus
from src.dashboard import web_viewer as wv
from src.dashboard.web_viewer import WebViewer
from src.location import last_park as lp
from src.network import car_phone_agent as cpa
from src.network import traccar as tr

REPO = Path(__file__).resolve().parent.parent
DEV = "a1b2c3d4" * 4
URL = "https://example.org/traccar-gps/"
WALL0 = 1_763_000_000.0


def _agent_module():
    old = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location(
            "bcm_agent_traccar_host_test", REPO / "tools" / "car_phone" / "termux" / "bcm_agent.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = old
    return mod


A = _agent_module()


class Clock:
    def __init__(self):
        self.mono = 100.0
        self.wall = WALL0

    def advance(self, s):
        self.mono += s
        self.wall += s


def _cfg(**traccar):
    block = {"url": URL, "device_id": DEV}
    block.update(traccar)
    return {"modules": {"car_phone": True, "car_phone_agent": True, "traccar": True},
            "traccar": block}


# ── pure parts ───────────────────────────────────────────────────────────

class TestUrlAndSettings:
    URLS = ["https://example.org/traccar-gps/", "https://example.org", "http://127.0.0.1:5055/",
            "http://example.org/", "https://u:p@example.org/", "https://example.org/?a=1",
            "https://example.org/#f", "https://example.org/a b", "https://" + "a" * 200 + ".org",
            "ftp://example.org/", "https://example.org:70000/", "https://example.org/ą", "",
            "https://example.org\t/", "https://.example.org/", "https://example..org/"]

    @pytest.mark.parametrize("url", URLS)
    def test_same_verdict_as_the_agent(self, url):
        assert (tr.url_error(url) == "") == (A.traccar_url_error(url) == "")

    def test_fingerprint_matches_the_agent(self):
        assert tr.fingerprint(DEV) == A.traccar_fingerprint(DEV) and tr.fingerprint(None) == ""

    def test_settings(self):
        out = tr.traccar_settings(_cfg(drive_interval_s=45, park_interval_min=20))
        assert out == {"traccar_url": URL, "traccar_device_id": DEV,
                       "traccar_drive_interval_s": 45, "traccar_park_interval_min": 20}

    @pytest.mark.parametrize("bad", [
        {"url": "http://example.org/"}, {"url": "https://user:" + DEV + "@example.org/"},
        {"device_id": "short"}, {"device_id": DEV + "/x"}, {"device_id": None}, {"url": 5}])
    def test_invalid_values_become_empty_with_a_warning_without_them(self, bad):
        warned = []
        out = tr.traccar_settings(_cfg(**bad), lambda k, m: warned.append(m))
        assert warned
        for msg in warned:
            assert DEV not in msg and "example.org" not in msg
        assert out["traccar_url"] == "" or out["traccar_device_id"] == ""

    def test_intervals_are_clamped(self):
        warned = []
        out = tr.traccar_settings(_cfg(drive_interval_s=1, park_interval_min=10_000),
                                  lambda k, m: warned.append(k))
        assert (out["traccar_drive_interval_s"], out["traccar_park_interval_min"]) == (10, 240)
        assert set(warned) == {"traccar_drive", "traccar_park"}
        assert tr.traccar_settings(_cfg(drive_interval_s=True))["traccar_drive_interval_s"] == 30

    def test_device_id_is_an_env_secret(self):
        assert SECRET_ENV_MAP[tr.DEVICE_ID_PATH] == tr.DEVICE_ID_ENV == "BCM_TRACCAR_DEVICE_ID"
        cfg = BCMConfig(config_path=str(REPO / "config" / "bcm_config_test.yaml"),
                        platform_override="x86", local_path=None,
                        env={"BCM_TRACCAR_DEVICE_ID": f"  {DEV}\n"})
        assert tr.traccar_settings(cfg)["traccar_device_id"] in ("", DEV)
        assert cfg.get("traccar.device_id").strip() == DEV

    def test_config_push_keys_only_with_the_module_on(self):
        on = cpa.desired_config(_cfg())
        assert on["toggles"]["traccar"] is True and on["traccar_device_id"] == DEV
        off_cfg = _cfg()
        off_cfg["modules"]["traccar"] = False
        off = cpa.desired_config(off_cfg)
        assert "traccar" not in off["toggles"] and not any(k.startswith("traccar_") for k in off)
        norm, err = A.normalize_config(on, strict=True)
        assert err == "" and A.config_hash(norm) == cpa.config_hash(on)

    def test_parse_agent_view(self):
        good = {"enabled": True, "configured": True, "id_fp": "a1b2c3d4", "mode": "drive",
                "queue_n": 3, "last_sent_ts": WALL0, "last_ok_ts": WALL0, "last_error": "tls",
                "last_http": 200, "dropped": 0, "paused_low_battery": False}
        assert tr.parse_agent_view(good)["queue_n"] == 3
        bad = dict(good, id_fp=DEV, mode="<x>", queue_n=-1, last_sent_ts="x",
                   last_error="<script>", last_http=True, paused_low_battery="yes")
        out = tr.parse_agent_view(bad)
        assert out["id_fp"] == "" and out["mode"] is None and out["queue_n"] is None
        assert out["last_sent_ts"] is None and out["last_error"] == ""
        assert out["last_http"] is None and out["paused_low_battery"] is False
        assert tr.parse_agent_view({"configured": True}) is None
        assert cpa.parse_health_facts({"traccar": good})["traccar"]["mode"] == "drive"
        assert cpa.parse_health_facts({})["traccar"] is None


class TestAgentOutdated:
    def test_old_agent_with_the_module_on(self, tmp_path):
        agent = cpa.CarPhoneAgent(_cfg(), EventBus(), state_path=str(tmp_path / "s.json"))
        desired = cpa.desired_config(_cfg())
        agent._info["version"] = "1.5.0"
        assert agent._refused_reason(desired) == "agent_outdated"
        agent._info["version"] = "1.6.0"
        assert agent._refused_reason(desired) == "config_refused"


# ── the module ───────────────────────────────────────────────────────────

class FakeAgent:
    def __init__(self):
        self.sent = []
        self.result = {"ok": True, "status": 202}
        self.facts = {"traccar": None}
        self.state = {"state": "ok", "version": "1.6.0"}

    def traccar_send(self, body):
        self.sent.append(body)
        return self.result

    def health_facts(self):
        return dict(self.facts)


@pytest.fixture
def mod():
    bus, clock, agent = EventBus(), Clock(), FakeAgent()
    m = tr.Traccar(_cfg(), bus, agent_getter=lambda: agent, clock=lambda: clock.mono,
                   wall=lambda: clock.wall)
    return SimpleNamespace(m=m, bus=bus, clock=clock, agent=agent)


class TestModule:
    def test_send_now_with_bcms_fresh_fix(self, mod):
        mod.m._on_position("gps.position", {"lat": 50.06143, "lon": 19.93658, "speed": 42.0,
                                            "heading": 180.0, "fix": True}, 0)
        assert mod.m.request_send() == {"ok": True}
        assert mod.m.request_send() == {"ok": False, "error": "busy"}
        mod.m.step()
        assert mod.agent.sent == [{"lat": 50.06143, "lon": 19.93658, "speed_kmh": 42.0,
                                   "heading": 180.0}]
        st = mod.bus.get_last(tr.TOPIC_STATE)[0]
        assert st["cmd"]["state"] == "sent" and st["url_host"] == "example.org"
        blob = json.dumps(st)
        assert DEV not in blob and URL not in blob

    def test_stale_or_bad_fix_lets_the_phone_measure(self, mod):
        mod.m._on_position("gps.position", {"lat": 50.0, "lon": 19.0}, 0)
        mod.clock.advance(tr.FIX_MAX_AGE_S + 1)
        mod.m.request_send()
        mod.m.step()
        mod.m._on_position("gps.position", {"lat": float("nan"), "lon": 19.0}, 0)
        mod.m.request_send()
        mod.m.step()
        assert mod.agent.sent == [{}, {}]

    def test_refusals(self, mod):
        mod.agent.result = {"ok": False, "error": "not_found"}
        mod.m.request_send()
        mod.m.step()
        assert mod.m.state()["cmd"] == {"state": "failed", "error": "agent_outdated",
                                        "ts": int(WALL0)}
        mod.agent.result = {"ok": False, "error": "<b>"}
        mod.m.request_send()
        mod.m.step()
        assert mod.m.state()["cmd"]["error"] == "b"

    def test_not_configured(self):
        m = tr.Traccar(_cfg(url=""), EventBus(), agent_getter=lambda: None)
        assert m.request_send() == {"ok": False, "error": "not_configured"}
        p = m.payload()
        assert p["url_ok"] is False and p["error"] == "no_agent" and p["id_set"] is True

    def test_payload_agent_view_and_outdated(self, mod):
        assert mod.m.payload()["error"] == "agent_outdated"     # version known, no view
        view = {"enabled": True, "configured": True, "id_fp": tr.fingerprint(DEV),
                "mode": "park", "queue_n": 0}
        mod.agent.facts = {"traccar": view}
        p = mod.m.payload()
        assert p["error"] == "" and p["agent"]["mode"] == "park" and p["id_fp"] == view["id_fp"]

    def test_lifecycle(self, monkeypatch):
        bus = EventBus()
        m = tr.start_traccar(_cfg(), bus)
        try:
            assert tr.get_traccar() is m
        finally:
            m.stop()
        assert tr.get_traccar() is None


# ── last parked position ─────────────────────────────────────────────────

@pytest.fixture
def park(tmp_path):
    bus, clock = EventBus(), Clock()
    path = tmp_path / "data" / "last_park.json"
    m = lp.LastPark(bus, {"last_park": {"path": str(path)}}, clock=lambda: clock.mono,
                    wall=lambda: clock.wall)
    m.start()
    return SimpleNamespace(m=m, bus=bus, clock=clock, path=path)


def _pos(p, lat=50.06143, lon=19.93658, speed=0.0):
    p.bus.publish("gps.position", {"lat": lat, "lon": lon, "speed": speed, "fix": True,
                                   "source": "phone"})


class TestLastPark:
    def test_ten_seconds_standing_still_is_saved_once(self, park):
        _pos(park, lat=50.07, speed=50)           # first moving fix: saved
        assert json.loads(park.path.read_text())["reason"] == "moving"
        park.clock.advance(20)
        _pos(park)
        park.clock.advance(5)
        _pos(park)
        assert json.loads(park.path.read_text())["reason"] == "moving"
        park.clock.advance(6)
        _pos(park)
        rec = json.loads(park.path.read_text())
        assert rec == {"lat": 50.06143, "lon": 19.93658, "ts": int(park.clock.wall),
                       "reason": "still", "source": "phone"}
        assert stat.S_IMODE(os.stat(park.path).st_mode) == 0o600
        assert park.bus.get_last(lp.TOPIC)[0]["reason"] == "still"
        mtime = park.path.stat().st_mtime_ns
        park.clock.advance(120)
        _pos(park, lat=50.06150)                  # ~8 m: the same stop
        assert park.path.stat().st_mtime_ns == mtime

    def test_trip_end_ignition_and_shutdown(self, park):
        _pos(park, lat=52.2297, lon=21.0122, speed=30)
        park.bus.publish("tracking.trip_ended", {"trip_id": 1})
        assert json.loads(park.path.read_text())["reason"] == "trip_end"
        park.bus.publish("vehicle.ignition_raw", True)
        park.bus.publish("vehicle.ignition_raw", False)
        assert json.loads(park.path.read_text())["reason"] == "ignition_off"
        park.bus.publish("power.shutting_down", True)
        assert json.loads(park.path.read_text())["reason"] == "shutdown"
        park.bus.publish("vehicle.ignition_raw", True)    # ignition on: nothing
        assert json.loads(park.path.read_text())["reason"] == "shutdown"

    def test_ignition_off_only_on_edge(self, park, monkeypatch):
        writes = []
        real = lp.atomic_write_json
        monkeypatch.setattr(lp, "atomic_write_json",
                            lambda *a, **k: (writes.append(a[1]["reason"]), real(*a, **k)))
        _pos(park, speed=30)
        writes.clear()
        for _ in range(3):                        # IGN:0 repeated every 2 s, no True first
            park.bus.publish("vehicle.ignition_raw", False)
        park.bus.publish("vehicle.ignition_raw", "0")     # not a bool: ignored
        assert writes == []
        park.bus.publish("vehicle.ignition_raw", True)
        for _ in range(3):
            park.bus.publish("vehicle.ignition_raw", False)
        assert writes == ["ignition_off"]
        assert json.loads(park.path.read_text())["reason"] == "ignition_off"

    def test_missing_speed_while_driving_does_not_storm(self, park, monkeypatch):
        writes = []
        real = lp.atomic_write_json
        monkeypatch.setattr(lp, "atomic_write_json",
                            lambda *a, **k: (writes.append(a[1]["reason"]), real(*a, **k)))
        lat = 50.0
        step = 50 / 3.6 * 0.5 / 111_195           # 50 km/h at 2 Hz, in degrees
        for _ in range(1200):                     # 10 minutes, speed: None
            park.clock.advance(0.5)
            lat += step
            _pos(park, lat=lat, speed=None)
        assert 15 <= len(writes) <= 21
        assert set(writes) == {"moving"}

    def test_missing_speed_standing_still_is_saved(self, park):
        _pos(park, lat=50.07, speed=None)         # first fix: written as "moving"
        park.clock.advance(5)
        for i in range(31):                       # 15 s within ~5 m
            _pos(park, lat=50.06143 + (i % 3) * 0.00002, speed=None)
            park.clock.advance(0.5)
        rec = json.loads(park.path.read_text())
        assert rec["reason"] == "still" and abs(rec["lat"] - 50.06143) < 0.0001

    def _drive(self, park, lat0, seconds, speed=50):
        lat = lat0
        for _ in range(int(seconds * 2)):
            park.clock.advance(0.5)
            lat += speed / 3.6 * 0.5 / 111_195
            _pos(park, lat=lat, speed=speed)
        return lat

    def _stand(self, park, lat, seconds):
        for _ in range(int(seconds * 2)):
            park.clock.advance(0.5)
            _pos(park, lat=lat, speed=0.0)

    def test_short_stop_before_power_cut_is_saved(self, park):
        lat = self._drive(park, 50.0, 120)
        self._stand(park, lat, 15)                # then the power is cut
        assert park.m.last()["reason"] == "still"
        assert abs(park.m.last()["lat"] - round(lat, 6)) < 1e-6

    def test_red_light_is_overwritten_by_the_final_stop(self, park):
        lat = self._drive(park, 50.0, 60)
        red = lat
        self._stand(park, red, 60)                # red light / jam
        lat = self._drive(park, red, 90)
        self._stand(park, lat, 15)
        last = park.m.last()
        assert last["reason"] == "still" and abs(last["lat"] - round(lat, 6)) < 1e-6
        assert lp.distance_m(red, 19.93658, last["lat"], last["lon"]) > 1000

    def test_stale_or_bogus_fixes_are_not_saved(self, park):
        _pos(park)
        park.clock.advance(lp.FIX_MAX_AGE_S + 1)
        park.bus.publish("tracking.trip_ended", {})
        assert not park.path.exists()
        for bad in ({"lat": 0, "lon": 0}, {"lat": 91, "lon": 0}, {"lat": "1", "lon": 2},
                    {"lat": float("inf"), "lon": 2}, {"lat": 1, "lon": 2, "fix": False}, "x"):
            park.bus.publish("gps.position", bad)
            park.bus.publish("tracking.trip_ended", {})
        assert not park.path.exists()

    def test_reload_publishes_and_damaged_file_is_ignored(self, park, tmp_path):
        _pos(park)
        park.bus.publish("tracking.trip_ended", {})
        bus2 = EventBus()
        m2 = lp.LastPark(bus2, {"last_park": {"path": str(park.path)}})
        m2.start()
        assert bus2.get_last(lp.TOPIC)[0]["lat"] == 50.06143 and m2.last()["reason"] == "trip_end"
        park.path.write_text('{"lat": "<script>", "lon": 1, "ts": 5}')
        m3 = lp.LastPark(EventBus(), {"last_park": {"path": str(park.path)}})
        assert m3.last() is None
        park.path.write_text("x" * (lp.FILE_MAX + 10))
        assert lp.LastPark(EventBus(), {"last_park": {"path": str(park.path)}}).last() is None

    def test_valid_record(self):
        assert lp.valid_record({"lat": 1.5, "lon": 2.5, "ts": WALL0, "reason": "evil",
                                "source": "<x>"}) == {"lat": 1.5, "lon": 2.5, "ts": int(WALL0),
                                                      "reason": "still", "source": ""}
        assert lp.valid_record({"lat": 1.5, "lon": 2.5, "ts": 5}) is None


# ── dashboard: summaries, route, /trips ──────────────────────────────────

class TestSummaries:
    def test_traccar_summary(self):
        assert wv._traccar_summary(None) is None
        out = wv._traccar_summary({"url_ok": True, "url_host": "<img>", "id_set": "yes",
                                   "id_fp": DEV, "agent": {"enabled": "x"},
                                   "cmd": {"state": "sent", "error": "<b>", "ts": "x"},
                                   "error": "boom", "url": URL, "device_id": DEV})
        assert out == {"url_ok": True, "url_host": "", "id_set": False, "id_fp": "",
                       "agent": None, "cmd": {"state": "sent", "error": "", "ts": None},
                       "error": ""}
        assert DEV not in json.dumps(out)

    def test_last_park_summary_links_from_numbers(self):
        out = wv._last_park_summary({"lat": 50.06143, "lon": 19.93658, "ts": WALL0,
                                     "reason": "still"})
        assert out["osm_url"] == ("https://www.openstreetmap.org/?mlat=50.061430&mlon=19.936580"
                                  "#map=17/50.061430/19.936580")
        assert out["geo_url"] == "geo:50.061430,19.936580"
        assert wv._last_park_summary({"lat": "1", "lon": 2, "ts": WALL0}) is None


@pytest.fixture
def web(monkeypatch, tmp_path, mod):
    def refuse(*a, **kw):
        raise AssertionError("no subprocess from web_viewer here")
    monkeypatch.setattr(wv, "subprocess", SimpleNamespace(run=refuse, Popen=refuse))
    base = tmp_path / "bcm_config_test.yaml"
    shutil.copy(REPO / "config" / "bcm_config_test.yaml", base)
    cfg = BCMConfig(config_path=str(base), platform_override="x86",
                    local_path=str(tmp_path / "local.yaml"), env={})
    viewer = WebViewer(host="127.0.0.1", port=5099, event_bus=mod.bus, config=cfg)
    holder = {"module": mod.m}
    monkeypatch.setattr(tr, "get_traccar", lambda: holder["module"])
    return SimpleNamespace(mod=mod, cfg=cfg, viewer=viewer, holder=holder,
                           client=viewer._build_app().test_client())


class TestRoutes:
    def test_send(self, web):
        res = web.client.post("/api/traccar/send", json={})
        assert res.status_code == 200 and res.get_json() == {"ok": True}
        web.mod.m.step()
        assert web.mod.agent.sent == [{}]
        res = web.client.post("/api/traccar/send", json={})
        assert res.status_code == 429 and int(res.headers["Retry-After"]) >= 1

    @pytest.mark.parametrize("addr", ["192.168.1.50", "10.0.0.5", "::ffff:192.168.1.5"])
    def test_loopback_only_even_with_full_remote_access(self, web, addr):
        web.cfg.set("dashboard.remote_access", "full")
        client = web.viewer._build_app().test_client()
        res = client.post("/api/traccar/send", json={}, environ_base={"REMOTE_ADDR": addr})
        assert res.status_code == 403
        assert web.mod.agent.sent == [] and web.mod.m.state() is None

    def test_rebinding_host_is_refused(self, web):
        res = web.client.post("/api/traccar/send", json={},
                              headers={"Host": "evil.example:5002"})
        assert res.status_code in (403, 400)

    @pytest.mark.parametrize("body", [{"lat": 1, "lon": 2}, {"url": "https://evil.example/"}])
    def test_only_an_empty_object(self, web, body):
        assert web.client.post("/api/traccar/send", json=body).status_code == 400
        res = web.client.post("/api/traccar/send", data="x", content_type="text/plain")
        assert res.status_code == 400

    def test_not_running_and_not_configured(self, web):
        web.holder["module"] = None
        res = web.client.post("/api/traccar/send", json={})
        assert res.status_code == 409 and res.get_json()["error"] == "not_running"
        web.holder["module"] = tr.Traccar(_cfg(device_id=""), EventBus(),
                                          agent_getter=lambda: None)
        web.viewer._crash_last.clear()
        res = web.client.post("/api/traccar/send", json={})
        assert res.status_code == 409 and res.get_json()["error"] == "not_configured"

    def test_get_is_not_a_route(self, web):
        assert web.client.get("/api/traccar/send").status_code == 405

    def test_payload_and_trips_page(self, web):
        web.mod.m.step()
        web.mod.bus.publish(lp.TOPIC, {"lat": 50.06143, "lon": 19.93658, "ts": WALL0,
                                       "reason": "still", "source": "phone"})
        data = web.client.get("/api/data").get_json()
        assert data["traccar"]["url_host"] == "example.org"
        assert data["last_park"]["geo_url"] == "geo:50.061430,19.936580"
        assert DEV not in json.dumps(data)
        page = web.client.get("/trips").get_data(as_text=True)
        assert "Ostatni postój" in page
        assert ('href="https://www.openstreetmap.org/?mlat=50.061430&amp;mlon=19.936580'
                '#map=17/50.061430/19.936580"') in page
        assert 'href="geo:50.061430,19.936580"' in page and "<script" not in page

    def test_trips_without_a_saved_stop(self, web):
        page = web.client.get("/trips").get_data(as_text=True)
        assert "Ostatni postój" not in page


def test_catalog_entries():
    from src.core.modules_catalog import MODULES
    assert MODULES["traccar"]["requires"] == ("car_phone_agent",)
    assert MODULES["traccar"]["default"] is False
    assert MODULES["last_park"]["requires"] == ("location",)
    assert MODULES["last_park"]["default"] is False
