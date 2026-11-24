"""Traccar (OsmAnd) reporting in the Termux agent
(tools/car_phone/termux/bcm_agent.py, :class:`TraccarReporter`, 1.6.0).

No network and no Termux here: HTTP goes through a fake ``traccar_get``
that records the URLs it was handed, phone commands through the parking
guard's fake runner (it refuses anything unexpected), clocks are fake and
state lives in tmp_path.

Covers: the OsmAnd URL (encoding, knots, seconds, alarm, valid=false), the
https-only rule (http only for 127.0.0.1, no credentials / query, length),
the config (validation, defaults, hash compatibility with the toggle off and
with BCM's desired_config), the offline queue (bound, drop oldest,
persistence across a restart, order, backoff, 4xx = longest backoff),
intervals per mode with a fake clock (driving every N s, one point at park
time, then every N min, ×4 below 20 %, none below 10 % — alarms still),
an alarm from the parking guard sent at once with ``alarm=tow`` and the SMS
fix, ``POST /v1/traccar/send`` (BCM's fix, validation, rate limit, off /
not configured), the health view, and the device id never in any log line
(only its 8-character fingerprint).
"""

from __future__ import annotations

import json
import logging
import os
import stat
import urllib.parse

import pytest

from tests import test_bcm_agent_park as park

A = park.A
DEV = "a1b2c3d4" * 4
URL = "https://example.org/traccar-gps/"
FIX_GPS = {"latitude": 50.06143, "longitude": 19.93658, "accuracy": 8.0, "altitude": 220.5,
           "bearing": 91.0, "speed": 13.9, "elapsedMs": 2000, "provider": "gps"}
FIX_NET = {"latitude": 50.0615, "longitude": 19.9366, "accuracy": 40.0, "elapsedMs": 5000,
           "provider": "network"}


class Http:
    """Fake ``traccar_get``: records URLs, answers from a script."""

    def __init__(self):
        self.urls = []
        self.answers = []        # [(status, err)] consumed first; then default
        self.default = (200, "")

    def __call__(self, url, timeout):
        assert timeout == A.TRACCAR_TIMEOUT_S
        self.urls.append(url)
        return self.answers.pop(0) if self.answers else self.default

    def params(self, i=-1):
        return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.urls[i]).query))


def traccar_config(**over):
    cfg = park.park_config(toggles={"crash_sms": True, "parking_guard": True,
                                    "cabin_watch": False, "call112": False, "traccar": True},
                           traccar_url=URL, traccar_device_id=DEV,
                           traccar_drive_interval_s=30, traccar_park_interval_min=15)
    cfg.update(over)
    return cfg


def traccar_cfg(env):
    return env.rep._cfg()


class Env:
    def __init__(self, tmp_path, clock, runner, spawn, http, **over):
        self.dir = str(tmp_path / "bcm_agent")
        self.clock, self.runner, self.http = clock, runner, http
        self.sleeps = []
        self.agent = self._agent(spawn)
        os.makedirs(self.dir, exist_ok=True)
        with open(os.path.join(self.dir, "PAIRING"), "w") as f:
            f.write(park.CODE + "\n")
        body = json.dumps({"secret": park.SECRET}).encode()
        ts = int(clock.wall)
        sig = A.sign(park.CODE.encode(), A.request_message("POST", "/v1/pair", ts, 50, body))
        status, _d, _h = self.agent.handle("POST", "/v1/pair", {
            "X-BCM-Ts": str(ts), "X-BCM-Nonce": "50", "X-BCM-Sig": sig}, body)
        assert status == 200
        self.peer = park.Peer(self.agent, clock)
        status, out = self.peer.req("PUT", "/v1/config", traccar_config(**over))
        assert status == 200, out
        self.rep = self.agent.traccar
        self.spawn = spawn

    def _agent(self, spawn):
        return A.Agent(self.dir, runner=self.runner, clock=lambda: self.clock.boot,
                       wall=lambda: self.clock.wall, localtime=park.time.gmtime, spawn=spawn,
                       mktime=park.calendar.timegm, pillow=None, traccar_get=self.http,
                       sleep=self.sleeps.append)

    def restart(self):
        self.agent = self._agent(self.spawn)
        self.rep = self.agent.traccar

    def parked(self):
        """BCM's last signed request (the config push) is older than the
        contact window: the car is parked."""
        self.clock.advance(A.TRACCAR_CONTACT_S + 1)

    def contact(self):
        """A signed BCM request (health) = BCM is on = driving."""
        assert self.peer.req("GET", "/v1/health")[0] == 200

    def locations(self):
        return [c for c in self.runner.calls if c[0] == "termux-location"]


@pytest.fixture
def http():
    return Http()


@pytest.fixture
def env(tmp_path, park_clock, park_runner, park_spawn, http):
    park_runner.fixes = {("gps", "last"): FIX_GPS, ("network", "once"): FIX_NET}
    return Env(tmp_path, park_clock, park_runner, park_spawn, http)


@pytest.fixture
def park_clock():
    return park.Clock()


@pytest.fixture
def park_runner(park_clock):
    return park.Runner(park_clock)


@pytest.fixture
def park_spawn(park_clock):
    return park.Spawner(park_clock)


# ── pure helpers ─────────────────────────────────────────────────────────

class TestUrl:
    @pytest.mark.parametrize("url", [
        "https://example.org/traccar-gps/", "https://example.org", "https://example.org:8443/x",
        "https://traccar.example.org/", "http://127.0.0.1:5055/"])
    def test_good(self, url):
        assert A.traccar_url_error(url) == ""

    @pytest.mark.parametrize("url", [
        "", "http://example.org/traccar-gps/", "ftp://example.org/", "https://",
        "https://user:pw@example.org/", "https://example.org/?id=1", "https://example.org/#x",
        "https://example.org/a b", " https://example.org/", "https://example.org/" + "a" * 200,
        "https://exa mple.org/", "https://example.org/%2e%2e/", "https://example.org:0/",
        "https://example.org:99999/", "http://localhost/", "https://example.org/ś",
        "javascript:alert(1)", "https://example.org\n/", None, 5])
    def test_bad(self, url):
        assert A.traccar_url_error(url) != ""

    def test_query_is_encoded_and_osmand_shaped(self):
        point = A._point_from_fix(A.parse_location(json.dumps(FIX_GPS)), park.T0, (55, "plugged"),
                                  "tow")
        q = A.traccar_query("dev.id_-1", point)
        params = dict(urllib.parse.parse_qsl(q))
        assert params == {"id": "dev.id_-1", "lat": "50.061430", "lon": "19.936580",
                          "timestamp": str(int(park.T0) - 2), "speed": "27.0",
                          "bearing": "91.0", "altitude": "220.5", "accuracy": "8",
                          "batt": "55", "charge": "true", "alarm": "tow"}
        # Only urlencode output: nothing that could break out of the query.
        assert all(ch.isalnum() or ch in "=&.-_%" for ch in q)

    def test_fix_older_than_a_day_keeps_its_time_and_is_invalid(self):
        day = A.MAX_FIX_AGE_S
        old = A._point_from_fix({"lat": 1.0, "lon": 2.0, "acc": None, "age_s": day + 3600},
                                park.T0, (None, None))
        assert old["t"] == int(park.T0) - day - 3600 and old["valid"] is False
        recent = A._point_from_fix({"lat": 1.0, "lon": 2.0, "acc": None, "age_s": 600},
                                   park.T0, (None, None))
        assert recent["t"] == int(park.T0) - 600 and "valid" not in recent
        ancient = A._point_from_fix({"lat": 1.0, "lon": 2.0, "acc": None, "age_s": 10 ** 10},
                                    park.T0, (None, None))
        assert ancient["t"] == A.EVENT_TS_MIN and A.valid_traccar_point(ancient)

    def test_invalid_point_flag_and_negative_coordinates(self):
        point = A._point_from_fix({"lat": -33.9, "lon": -70.1, "acc": None, "age_s": 0},
                                  park.T0, (None, None), None, valid=False)
        params = dict(urllib.parse.parse_qsl(A.traccar_query(DEV, point)))
        assert params["lat"] == "-33.900000" and params["lon"] == "-70.100000"
        assert params["valid"] == "false" and "batt" not in params and "speed" not in params

    def test_fingerprint(self):
        fp = A.traccar_fingerprint(DEV)
        assert len(fp) == 8 and fp != DEV[:8] and A.traccar_fingerprint("") == ""

    def test_parse_location_keeps_speed_only_when_given(self):
        fix = A.parse_location(json.dumps(FIX_GPS))
        assert fix["speed_ms"] == 13.9 and fix["bearing"] == 91.0 and fix["alt"] == 220.5
        assert "speed_ms" not in A.parse_location(json.dumps(FIX_NET))
        bad = dict(FIX_GPS, speed=-3, bearing=999, altitude="x")
        out = A.parse_location(json.dumps(bad))
        assert not {"speed_ms", "bearing", "alt"} & set(out)


class TestHttpGet:
    def test_refuses_plain_http_to_a_remote_host_without_any_connection(self, monkeypatch):
        def boom(*a, **k):
            raise AssertionError("no connection may be attempted")
        monkeypatch.setattr(A.urllib.request.OpenerDirector, "open", boom)
        assert A.traccar_http_get("http://example.org/?id=x", 1.0) == (None, "network")

    def test_error_classes(self):
        import socket
        import ssl
        assert A._net_error_class(ssl.SSLCertVerificationError("bad")) == "tls"
        assert A._net_error_class(socket.gaierror("x")) == "dns"
        assert A._net_error_class(socket.timeout("x")) == "timeout"
        assert A._net_error_class(ConnectionRefusedError()) == "connect"
        assert A._net_error_class(ValueError()) == "network"

    def test_redirect_is_not_followed(self):
        h = A._NoRedirect()
        assert h.redirect_request(None, None, 302, "Found", {}, "http://evil.example/") is None

    def test_local_server_round_trip(self):
        """A real HTTP exchange with a local server on 127.0.0.1 (the only
        plain-http host allowed): status passes through, 302 is not followed."""
        import http.server
        import threading
        seen = []

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append(self.path)
                if "redirect" in self.path:
                    self.send_response(302)
                    self.send_header("Location", "http://127.0.0.1:1/x")
                else:
                    self.send_response(200)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *a):
                pass

        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            base = f"http://127.0.0.1:{srv.server_address[1]}/gps/"
            assert A.traccar_http_get(base + "?id=abc&lat=1", 5.0) == (200, "")
            assert A.traccar_http_get(base.replace("/gps/", "/redirect/") + "?id=x", 5.0) \
                == (302, "")
            assert seen == ["/gps/?id=abc&lat=1", "/redirect/?id=x"]
        finally:
            srv.shutdown()
            srv.server_close()


# ── config ───────────────────────────────────────────────────────────────

class TestConfig:
    def test_defaults_and_validation(self):
        cfg = A.default_config()
        assert cfg["traccar_url"] == "" and cfg["traccar_device_id"] == ""
        assert (cfg["traccar_drive_interval_s"], cfg["traccar_park_interval_min"]) == (30, 15)
        for bad in ({"traccar_url": "http://example.org/"}, {"traccar_device_id": "short"},
                    {"traccar_device_id": "a/b" * 4}, {"traccar_drive_interval_s": 5},
                    {"traccar_park_interval_min": 4}, {"traccar_park_interval_min": True},
                    {"traccar_url": 7}):
            norm, err = A.normalize_config(dict(traccar_config(), **bad), strict=True)
            assert norm is None and err.startswith("traccar_"), bad
            assert DEV not in err

    def test_hash_ignores_traccar_while_off(self):
        on, _ = A.normalize_config(traccar_config(), strict=True)
        off_cfg = traccar_config(toggles={"crash_sms": True, "parking_guard": True,
                                          "cabin_watch": False, "call112": False})
        off, _ = A.normalize_config(off_cfg, strict=True)
        plain, _ = A.normalize_config(park.park_config(), strict=True)
        assert A.config_hash(off) == A.config_hash(plain)       # pre-1.6.0 agent agrees
        assert A.config_hash(on) != A.config_hash(plain)
        other, _ = A.normalize_config(traccar_config(traccar_park_interval_min=20), strict=True)
        assert A.config_hash(other) != A.config_hash(on)

    def test_host_and_agent_agree(self):
        from src.network import car_phone_agent as cpa
        for on in (False, True):
            cfg = {"modules": {"car_phone": True, "car_phone_agent": True, "traccar": on},
                   "traccar": {"url": URL, "device_id": DEV, "drive_interval_s": 45,
                               "park_interval_min": 20}}
            desired = cpa.desired_config(cfg)
            assert ("traccar" in desired["toggles"]) is on
            assert ("traccar_url" in desired) is on
            norm, err = A.normalize_config(desired, strict=True)
            assert err == "" and cpa.config_hash(desired) == A.config_hash(norm)
        assert desired["traccar_drive_interval_s"] == 45 and desired["traccar_device_id"] == DEV

    def test_device_id_never_logged_on_config(self, env, caplog):
        caplog.set_level(logging.DEBUG, logger="bcm_agent")
        status, _ = env.peer.req("PUT", "/v1/config", traccar_config(traccar_park_interval_min=30))
        assert status == 200
        text = caplog.text
        assert "Traccar config" in text and A.traccar_fingerprint(DEV) in text
        assert DEV not in text

    def test_config_file_is_private(self, env):
        st = os.stat(os.path.join(env.dir, "config.json"))
        assert stat.S_IMODE(st.st_mode) == 0o600


# ── modes and intervals ──────────────────────────────────────────────────

class TestModes:
    def test_driving_reports_every_drive_interval_from_the_gps(self, env):
        env.contact()
        env.rep.step()
        assert len(env.http.urls) == 1 and env.rep.view()["mode"] == "drive"
        p = env.http.params()
        assert p["id"] == DEV and p["speed"] == "27.0" and p["lat"] == "50.061430"
        assert env.locations()[-1] == ["termux-location", "-p", "gps", "-r", "last"]
        env.clock.advance(20)
        env.contact()
        env.rep.step()
        assert len(env.http.urls) == 1                      # not yet
        env.clock.advance(11)
        env.contact()
        env.rep.step()
        assert len(env.http.urls) == 2

    def test_stale_last_fix_while_driving_measures(self, env):
        env.runner.fixes[("gps", "last")] = dict(FIX_GPS, elapsedMs=300_000)
        env.runner.fixes[("gps", "once")] = FIX_GPS
        env.contact()
        env.rep.step()
        assert [c[2:] for c in env.locations()][-2:] == [["gps", "-r", "last"],
                                                       ["gps", "-r", "once"]]
        assert len(env.http.urls) == 1

    def test_park_time_point_then_every_park_interval(self, env):
        env.contact()
        env.rep.step()
        env.clock.advance(A.TRACCAR_CONTACT_S + 1)          # BCM went quiet = parked
        env.rep.step()
        assert env.rep.view()["mode"] == "park" and len(env.http.urls) == 2
        env.clock.advance(14 * 60)
        env.rep.step()
        assert len(env.http.urls) == 2
        env.clock.advance(61)
        n_loc = len(env.locations())
        env.rep.step()
        assert len(env.http.urls) == 3
        # Parked: no GPS "-r once" (the car stands still).
        assert all(c[2:5] != ["gps", "-r", "once"] for c in env.locations()[n_loc:])

    def test_low_battery_stretches_then_stops_periodic(self, env):
        env.runner.battery = dict(env.runner.battery, percentage=15, plugged="UNPLUGGED")
        env.parked()
        env.rep.step()                                      # start parked: first point
        assert len(env.http.urls) == 1
        env.clock.advance(16 * 60)
        env.rep.step()
        assert len(env.http.urls) == 1                      # ×4 = 60 min
        env.clock.advance(45 * 60)
        env.rep.step()
        assert len(env.http.urls) == 2
        env.runner.battery = dict(env.runner.battery, percentage=8)
        env.clock.advance(61 * 60)
        env.rep.step()
        assert len(env.http.urls) == 2 and env.rep.view()["paused_low_battery"] is True
        # ... but an alarm still goes, at once.
        env.rep.note_alarm("tilt", A.parse_location(json.dumps(FIX_NET)))
        env.rep.step()
        assert len(env.http.urls) == 3 and env.http.params()["alarm"] == "tow"

    def test_plugged_phone_keeps_the_normal_interval(self, env):
        env.runner.battery = dict(env.runner.battery, percentage=5, plugged="PLUGGED_USB")
        env.parked()
        env.rep.step()
        env.clock.advance(15 * 60 + 1)
        env.rep.step()
        assert len(env.http.urls) == 2

    def test_off_or_unconfigured_sends_nothing(self, tmp_path, park_clock, park_runner,
                                               park_spawn, http):
        for over in ({"traccar_url": ""}, {"traccar_device_id": ""},
                     {"toggles": {"crash_sms": True, "parking_guard": True,
                                  "cabin_watch": False, "call112": False}}):
            e = Env(tmp_path / str(len(http.urls)) / str(id(over)), park_clock, park_runner,
                    park_spawn, http, **over)
            assert e.rep.step() == A.TRACCAR_IDLE_S
            e.rep.note_alarm("tilt", {"lat": 1.0, "lon": 2.0, "acc": 5, "age_s": 0})
            e.rep.step()
        assert http.urls == []
        assert not [c for c in park_runner.calls if c[0] == "termux-location"]


# ── queue ────────────────────────────────────────────────────────────────

class TestQueue:
    def test_offline_queue_order_backoff_and_resend(self, env):
        env.http.default = (None, "connect")
        env.contact()
        env.rep.step()
        for _ in range(3):
            env.clock.advance(31)
            env.contact()
            env.rep.step()
        v = env.rep.view()
        assert v["last_error"] == "connect" and v["queue_n"] >= 2
        queued = [p["t"] for p in env.rep._queue]
        assert queued == sorted(queued)
        env.http.default = (200, "")
        env.http.urls.clear()
        env.clock.advance(A.TRACCAR_BACKOFF_MAX_S)
        env.contact()
        env.rep.step()
        sent = [int(dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(u).query))["timestamp"])
                for u in env.http.urls]
        assert sent == sorted(sent) and len(sent) == len(queued) + 1
        assert env.rep.view()["queue_n"] == 0 and env.rep.view()["last_error"] == ""
        # nginx limit: a gap between points of one batch
        assert env.sleeps and set(env.sleeps) == {A.TRACCAR_GAP_S}

    def test_backoff_grows_and_unknown_device_waits_longest(self, env):
        env.http.answers = [(None, "timeout")]
        env.rep.step()
        first = env.rep._next_try - env.clock.boot
        assert first == pytest.approx(A.TRACCAR_BACKOFF_MIN_S)
        env.http.answers = [(400, "")]
        env.clock.advance(first + 1)
        env.rep.step()
        assert env.rep.view()["last_error"] == "unknown_device"
        assert env.rep._next_try - env.clock.boot == pytest.approx(A.TRACCAR_BACKOFF_MAX_S)
        env.http.answers = [(302, "")]
        env.clock.advance(A.TRACCAR_BACKOFF_MAX_S + 1)
        env.rep.step()
        # Nothing was delivered: every point (also the parked ones made in
        # the meantime) is still queued.
        assert env.rep.view()["last_error"] == "redirect" and env.rep.view()["queue_n"] >= 1
        assert env.rep.view()["last_sent_ts"] is None

    def test_queue_is_bounded_drops_oldest_and_survives_restart(self, env):
        env.http.default = (None, "dns")
        with env.rep._lock:
            for i in range(A.TRACCAR_QUEUE_MAX + 7):
                env.rep._push_locked({"t": int(park.T0) + i, "lat": 1.0, "lon": 2.0})
        env.rep._persist()                                  # the write is outside the lock
        assert len(env.rep._queue) == A.TRACCAR_QUEUE_MAX
        assert env.rep._queue[0]["t"] == int(park.T0) + 7 and env.rep.view()["dropped"] == 7
        path = os.path.join(env.dir, A.TRACCAR_QUEUE_FILE)
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
        raw = open(path).read()
        assert DEV not in raw                               # the id is added at send time
        env.restart()
        assert len(env.rep._queue) == A.TRACCAR_QUEUE_MAX
        assert env.rep._queue[0]["t"] == int(park.T0) + 7

    def test_queue_file_is_written_without_holding_the_lock(self, env, monkeypatch):
        held = []
        real = A.atomic_write
        monkeypatch.setattr(A, "atomic_write", lambda *a, **k: (
            held.append(env.rep._lock.locked()), real(*a, **k))[1])
        env.http.default = (None, "dns")
        env.rep.step()
        assert held and not any(held)
        assert env.rep.view()["queue_n"] == 1

    def test_driving_saves_are_debounced(self, env, monkeypatch):
        writes = []
        real = A.atomic_write
        monkeypatch.setattr(A, "atomic_write", lambda *a, **k: (
            a[0].endswith(A.TRACCAR_QUEUE_FILE) and writes.append(a[0]), real(*a, **k))[1])
        env.http.default = (None, "connect")
        env.contact()
        env.rep.step()                                      # mode change: saved at once
        assert len(writes) == 1
        for _ in range(3):                                  # 3 more points within 60 s
            env.clock.advance(15)
            env.contact()
            env.rep._next_report = env.clock.boot
            env.rep.step()
        assert len(writes) == 1
        env.clock.advance(A.TRACCAR_SAVE_DRIVE_S)
        env.contact()
        env.rep._next_report = env.clock.boot
        env.rep.step()
        assert len(writes) == 2

    def test_rejected_point_is_dropped_after_the_id_was_accepted(self, env):
        env.contact()
        env.rep.step()                                      # 200: the id is known
        bad = {"t": int(park.T0), "lat": 1.0, "lon": 2.0}
        good = {"t": int(park.T0) + 1, "lat": 1.5, "lon": 2.5}
        with env.rep._lock:
            env.rep._push_locked(bad)
            env.rep._push_locked(good)
        env.http.answers = [(400, "")]
        env.rep._flush(traccar_cfg(env))
        v = env.rep.view()
        assert v["last_error"] == "http_4xx" and v["queue_n"] == 2
        assert env.rep._next_try - env.clock.boot < A.TRACCAR_BACKOFF_MAX_S
        for _ in range(2):
            env.clock.advance(A.TRACCAR_BACKOFF_MAX_S)
            env.http.answers = [(400, "")]
            env.rep._flush(traccar_cfg(env))
        # Third rejection of the same head point: dropped, the next one goes.
        assert env.rep.view()["queue_n"] == 0 and env.rep.view()["dropped"] == 1
        assert env.http.params()["lat"] == "1.500000"

    def test_400_before_any_success_is_unknown_device(self, env):
        env.http.default = (400, "")
        env.rep.step()
        for _ in range(5):
            env.clock.advance(A.TRACCAR_BACKOFF_MAX_S + 1)
            env.rep.step()
        v = env.rep.view()
        assert v["last_error"] == "unknown_device" and v["dropped"] == 0 and v["queue_n"] >= 1

    def test_damaged_queue_file_starts_empty_or_skips_bad_points(self, env):
        path = os.path.join(env.dir, A.TRACCAR_QUEUE_FILE)
        with open(path, "w") as f:
            f.write("{not json")
        env.restart()
        assert env.rep._queue == []
        good = {"t": int(park.T0), "lat": 1.0, "lon": 2.0}
        with open(path, "w") as f:
            json.dump({"points": [good, {"t": "x"}, {"t": int(park.T0), "lat": 99, "lon": 0},
                                  dict(good, alarm="evil&id=1"), "junk"]}, f)
        env.restart()
        assert env.rep._queue == [good]


# ── alarms and "send now" ────────────────────────────────────────────────

class TestAlarmAndSend:
    def test_park_alarm_job_reaches_traccar_with_the_sms_fix(self, env):
        guard = env.agent.park
        with env.agent._lock:
            guard.st["state"] = "alarm"
            guard._jobs.append({"kind": "alarm", "reason": "shake", "wall": env.clock.wall})
        env.runner.fixes[("gps", "once")] = FIX_GPS
        guard._run_jobs()
        assert len(env.rep._alarms) == 1 and env.http.urls == []
        env.rep.step()
        params = env.http.params(0)
        assert params["alarm"] == "vibration" and params["lat"] == "50.061430"

    def test_alarm_without_any_position_uses_the_last_point_marked_invalid(self, env):
        env.rep.step()                                      # one normal point
        env.runner.fixes = {}
        env.rep.note_alarm("power", None)
        env.rep.step()
        p = env.http.params()
        assert p["alarm"] == "powerCut" and p["valid"] == "false"

    def test_send_now_uses_bcms_fix_and_is_rate_limited(self, env):
        status, out = env.peer.req("POST", "/v1/traccar/send",
                                   {"lat": 52.2297, "lon": 21.0122, "speed_kmh": 36.0,
                                    "heading": 180})
        assert status == 202 and out["queued"] is True
        status, out = env.peer.req("POST", "/v1/traccar/send", {})
        assert status == 429 and out["retry_after"] >= 1
        env.rep.step()
        sent = [dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(u).query))
                for u in env.http.urls]
        assert any(p["lat"] == "52.229700" and p["speed"] == "19.4" and p["bearing"] == "180.0"
                   for p in sent)

    @pytest.mark.parametrize("body", [{"lat": 91, "lon": 0}, {"lat": "1", "lon": 2},
                                      {"lat": 1, "lon": 2, "x": 1}, {"lat": 1},
                                      {"lat": 1, "lon": 2, "speed_kmh": 999}])
    def test_send_now_validates(self, env, body):
        assert env.peer.req("POST", "/v1/traccar/send", body)[0] == 400

    def test_send_now_when_off(self, tmp_path, park_clock, park_runner, park_spawn, http):
        e = Env(tmp_path, park_clock, park_runner, park_spawn, http, traccar_device_id="")
        status, out = e.peer.req("POST", "/v1/traccar/send", {})
        assert status == 409 and out["error"] == "not_configured"

    def test_send_now_needs_a_signature(self, env):
        status, _d, _h = env.agent.handle("POST", "/v1/traccar/send", {}, b"{}")
        assert status == 401


class TestHealthAndLogs:
    def test_health_view_has_no_url_or_id(self, env):
        env.rep.step()
        status, out = env.peer.req("GET", "/v1/health")
        assert status == 200
        tr = out["traccar"]
        assert tr["enabled"] is True and tr["configured"] is True
        assert tr["id_fp"] == A.traccar_fingerprint(DEV) and tr["queue_n"] == 0
        assert tr["last_sent_ts"] is not None
        blob = json.dumps(out)
        assert DEV not in blob and "example.org" not in blob
        from src.network import traccar as host
        parsed = host.parse_agent_view(tr)
        assert parsed["mode"] in ("drive", "park") and parsed["last_error"] == ""

    def test_no_log_line_contains_the_device_id(self, env, caplog):
        caplog.set_level(logging.DEBUG, logger="bcm_agent")
        env.http.answers = [(None, "tls"), (404, "")]
        env.rep.step()
        env.clock.advance(A.TRACCAR_BACKOFF_MAX_S + 1)
        env.rep.step()
        env.rep.note_alarm("cabin", None)
        env.rep.step()
        assert "send failed" in caplog.text
        assert DEV not in caplog.text and "example.org" not in caplog.text
