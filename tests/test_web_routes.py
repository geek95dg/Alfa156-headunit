"""Real web_viewer routes through ``WebViewer._build_app().test_client()``.

Only harmless endpoints are exercised. web_viewer's ``subprocess`` is
replaced by a recorder for every test here, and the AA touch injector is a
fake-runner instance, so nothing spawns xdotool/ffmpeg/systemctl.
"""

import fcntl
import json
import os
import resource
import subprocess
import threading
import time
from types import SimpleNamespace

import pytest

from src.core.config import BCMConfig
from src.core.event_bus import EventBus
from src.dashboard import web_viewer as wv
from src.dashboard.web_viewer import WebViewer
from src.multimedia.aa_input import AATouchInjector


class _Recorder:
    """Fake injector runner."""

    def __init__(self, exc=None):
        self.calls = []
        self.exc = exc

    def __call__(self, argv, **kw):
        assert not kw.get("shell")
        self.calls.append(list(argv))
        if self.exc is not None:
            raise self.exc
        return subprocess.CompletedProcess(argv, 0)


@pytest.fixture(autouse=True)
def no_web_subprocess(monkeypatch):
    """Record (and refuse) any subprocess call made by web_viewer itself."""
    calls = []

    def refuse(argv, *a, **kw):
        calls.append(list(argv))
        raise FileNotFoundError(argv[0])

    fake = SimpleNamespace(
        run=refuse, Popen=refuse, PIPE=subprocess.PIPE, DEVNULL=subprocess.DEVNULL,
        STDOUT=subprocess.STDOUT, TimeoutExpired=subprocess.TimeoutExpired,
    )
    monkeypatch.setattr(wv, "subprocess", fake)
    return calls


@pytest.fixture
def env():
    bus = EventBus()
    cfg = BCMConfig(platform_override="x86")
    cfg.save = lambda path=None: None
    viewer = WebViewer(host="127.0.0.1", port=5099, event_bus=bus, config=cfg)
    runner = _Recorder()
    viewer._aa_injector = AATouchInjector(viewer._aa_canvas_size, runner=runner,
                                          autostart=False)
    client = viewer._build_app().test_client()
    return SimpleNamespace(bus=bus, cfg=cfg, viewer=viewer, runner=runner,
                           client=client, injector=viewer._aa_injector,
                           size=viewer._aa_canvas_size())


def _px(env, rx, ry):
    w, h = env.size
    return str(min(w - 1, int(rx * w))), str(min(h - 1, int(ry * h)))


# ── POST /aa/touch ───────────────────────────────────────────────────────

class TestAATouchRoute:
    def test_without_action_is_a_tap(self, env, no_web_subprocess):
        res = env.client.post("/aa/touch", json={"x": 0.25, "y": 0.5})
        assert res.status_code == 200
        body = res.get_json()
        assert body["ok"] is True and body["action"] == "tap"
        env.injector.process_pending()
        x, y = _px(env, 0.25, 0.5)
        assert env.runner.calls == [["xdotool", "mousemove", "--screen", "0", x, y, "click", "1"]]
        assert no_web_subprocess == []

    def test_empty_body_taps_centre_as_before(self, env):
        assert env.client.post("/aa/touch").status_code == 200
        assert env.client.post("/aa/touch", json={}).status_code == 200
        env.injector.process_pending()
        x, y = _px(env, 0.5, 0.5)
        assert env.runner.calls[0][4:6] == [x, y]

    def test_down_then_up(self, env):
        assert env.client.post("/aa/touch", json={"action": "down", "x": 0.1, "y": 0.1}).status_code == 200
        assert env.client.post("/aa/touch", json={"action": "up", "x": 0.2, "y": 0.1}).status_code == 200
        env.injector.process_pending()
        assert env.runner.calls[0][-2:] == ["mousedown", "1"]
        assert env.runner.calls[1][-2:] == ["mouseup", "1"]

    @pytest.mark.parametrize("body", [
        {"action": "drag", "x": 0.5, "y": 0.5},
        {"action": "move", "x": 0.5, "y": 0.5},     # never over HTTP
        {"action": None},
        {"x": "abc", "y": 0.5},
        {"x": 0.5, "y": [1]},
        {"x": True, "y": 0.5},
    ])
    def test_invalid_is_400(self, env, body):
        res = env.client.post("/aa/touch", json=body)
        assert res.status_code == 400
        assert res.get_json()["ok"] is False
        env.injector.process_pending()
        assert env.runner.calls == []

    def test_nan_is_400(self, env):
        res = env.client.post("/aa/touch", data='{"x": NaN, "y": 0.5}',
                              content_type="application/json")
        assert res.status_code == 400

    def test_huge_integer_is_400_not_500(self, env):
        # json parses it as int; float() of it overflows. Used to be a 500
        # with a full traceback in the log on every request.
        res = env.client.post("/aa/touch", data='{"x": 1' + "0" * 400 + ', "y": 0.5}',
                              content_type="application/json")
        assert res.status_code == 400
        env.injector.process_pending()
        assert env.runner.calls == []

    def test_non_object_body_is_400(self, env):
        assert env.client.post("/aa/touch", json=[0.5, 0.5]).status_code == 400

    def test_missing_xdotool_is_503_not_500(self, env):
        env.viewer._aa_injector = AATouchInjector(
            env.viewer._aa_canvas_size, runner=_Recorder(exc=FileNotFoundError("xdotool")),
            autostart=False)
        assert env.client.post("/aa/touch", json={}).status_code == 200
        env.viewer._aa_injector.process_pending()   # discovers xdotool is missing
        assert env.client.post("/aa/touch", json={}).status_code == 503


# ── /ws/input message handling ───────────────────────────────────────────

class TestInputMessages:
    GARBAGE = [
        None, 42, 3.5, [], {}, b"\xff\xfe", "not json", "[]", "null", '"str"',
        '{"type": 5}', '{"type": "keydown"}', '{"type": "keydown", "key": {}}',
        '{"type": "keydown", "key": ""}', '{"type": "keydown", "key": "' + "k" * 100 + '"}',
        '{"type": "aa_touch"}', '{"type": "aa_touch", "action": "rm -rf /"}',
        '{"type": "aa_touch", "action": "tap", "x": "NaN", "y": 0}',
        '{"type": "aa_touch", "action": "tap", "x": NaN, "y": 0}',
        '{"type": "aa_touch", "action": "tap", "x": 1e999, "y": 0}',
        "x" * 100000, b"y" * 100000,
    ]

    def test_garbage_never_raises(self, env):
        for msg in self.GARBAGE:
            assert env.viewer._handle_input_message(msg, "c") is False, msg
        env.injector.process_pending()
        assert env.runner.calls == []

    def test_keydown_still_works(self, env):
        seen = []
        env.bus.subscribe("input.raw_keyname", lambda t, v, ts: seen.append(v))
        assert env.viewer._handle_input_message('{"type": "keydown", "key": "ArrowUp"}', "c")
        assert env.viewer._handle_input_message({"type": "keydown", "key": "MediaTrackNext"}, "c")
        assert seen == ["up", "n"]

    def test_aa_touch_reaches_injector(self, env):
        msg = json.dumps({"type": "aa_touch", "action": "down", "x": 0.5, "y": 0.5})
        assert env.viewer._handle_input_message(msg, "ws1") is True
        env.injector.process_pending()
        assert env.injector.button_down is True

    def test_ws_loop_survives_garbage_and_releases_on_close(self, env):
        class FakeWS:
            def __init__(self, msgs):
                self.msgs = list(msgs)

            def receive(self, timeout=None):
                if not self.msgs:
                    raise ConnectionError("closed")
                return self.msgs.pop(0)

        seen = []
        env.bus.subscribe("input.raw_keyname", lambda t, v, ts: seen.append(v))
        env.viewer._running = True
        ws = FakeWS([None, "garbage", "[1]",
                     json.dumps({"type": "aa_touch", "action": "down", "x": 0.5, "y": 0.5}),
                     '{"type": "keydown", "key": {}}',
                     json.dumps({"type": "keydown", "key": "Enter"})])
        env.viewer._serve_input_ws(ws)
        env.viewer._running = False
        assert seen == ["enter"]          # the loop outlived the garbage
        env.injector.process_pending()
        # down from this socket, then the release queued when it closed
        assert env.runner.calls[0][-2:] == ["mousedown", "1"]
        assert env.runner.calls[-1] == ["xdotool", "mouseup", "1"]
        assert env.injector.button_down is False

    def test_aa_restart_status_resets_injector(self, env):
        env.injector.submit("down", 0.5, 0.5, client="ws1")
        env.injector.process_pending()
        assert env.injector.button_down is True
        env.bus.publish("multimedia.openauto_status", "restarting")
        assert env.injector.button_down is False
        env.injector.submit("down", 0.5, 0.5, client="ws1")
        env.injector.process_pending()
        env.bus.publish("multimedia.openauto_status", "connected")   # not a reset
        assert env.injector.button_down is True

    def test_voice_trigger_taps_through_injector(self, env, no_web_subprocess):
        env.bus.publish("aa.voice_trigger", True)
        env.bus.publish("aa.voice_trigger", False)   # release: no second tap
        env.injector.process_pending()
        x, y = _px(env, 0.05, 0.08)
        assert env.runner.calls == [["xdotool", "mousemove", "--screen", "0", x, y, "click", "1"]]
        assert no_web_subprocess == []

    def test_voice_key_method_sends_m(self, env, no_web_subprocess):
        env.cfg.set("multimedia.aa_voice_method", "key")
        env.bus.publish("aa.voice_trigger", True)
        env.injector.process_pending()
        assert env.runner.calls == [["xdotool", "key", "--clearmodifiers", "m"]]
        assert no_web_subprocess == []

    def test_voice_key_falls_back_to_tap_without_voice_button(self, env):
        # autoapp started without a mic -> VoiceCommandButton=false -> M is ignored
        env.cfg.set("multimedia.aa_voice_method", "key")
        env.bus.publish("multimedia._internals",
                        {"openauto": SimpleNamespace(voice_button_enabled=False)})
        env.bus.publish("aa.voice_trigger", True)
        env.injector.process_pending()
        assert env.runner.calls[0][-2:] == ["click", "1"]

    def test_notifications_in_payload_expire(self, env):
        from src.core.notifications import publish_notification
        publish_notification(env.bus, "Brak mikrofonu", ttl=5, now=time.time())
        assert [n["title"] for n in env.viewer._get_dashboard_data()["notifications"]] == [
            "Brak mikrofonu"]
        publish_notification(env.bus, "old", ttl=1, now=time.time() - 100, key="x")
        titles = [n["title"] for n in env.viewer._get_dashboard_data()["notifications"]]
        assert "old" not in titles

    def test_lazy_injector_is_created_once(self):
        viewer = WebViewer(event_bus=EventBus(), config=BCMConfig(platform_override="x86"))
        try:
            first = viewer._get_aa_injector()
            assert isinstance(first, AATouchInjector)
            assert viewer._get_aa_injector() is first
        finally:
            viewer.stop()


# ── /ws/input Origin check ───────────────────────────────────────────────

class _FakeWSServer:
    """Stands in for simple_websocket.Server inside flask_sock's route."""

    instances = []
    mode = "werkzeug"

    def __init__(self, environ, **kw):
        self.msgs = [json.dumps({"type": "aa_touch", "action": "down", "x": 0.5, "y": 0.5})]
        self.received = 0
        self.closed = False
        _FakeWSServer.instances.append(self)

    def receive(self, timeout=None):
        if not self.msgs:
            raise ConnectionError("closed")
        self.received += 1
        return self.msgs.pop(0)

    def close(self, *a, **kw):
        self.closed = True


class TestInputWebSocketOrigin:
    @pytest.fixture
    def ws_env(self, env, monkeypatch):
        import flask_sock
        _FakeWSServer.instances = []
        monkeypatch.setattr(flask_sock, "Server", _FakeWSServer)
        env.viewer._running = True
        yield env
        env.viewer._running = False

    def _open(self, env, origin=None, host="localhost:5002"):
        headers = {"Upgrade": "websocket", "Connection": "Upgrade",
                   "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ==",
                   "Sec-WebSocket-Version": "13", "Host": host}
        if origin is not None:
            headers["Origin"] = origin
        env.client.get("/ws/input", headers=headers)
        assert len(_FakeWSServer.instances) == 1, "route did not reach flask_sock"
        return _FakeWSServer.instances[0]

    @pytest.mark.parametrize("origin", [
        "http://evil.example", "http://evil.example:5002", "http://localhost:5003",
        "null", "", "file://", "ws://localhost:5002", "http://localhost:5002.evil",
    ])
    def test_foreign_origin_gets_no_touch_through(self, ws_env, origin):
        ws = self._open(ws_env, origin=origin)
        assert ws.received == 0 and ws.closed
        ws_env.injector.process_pending()
        assert ws_env.runner.calls == []
        assert ws_env.injector.button_down is False

    @pytest.mark.parametrize("origin", [None, "http://localhost:5002", "HTTP://LocalHost:5002"])
    def test_own_page_and_non_browser_clients_are_served(self, ws_env, origin):
        ws = self._open(ws_env, origin=origin)
        assert ws.received == 1
        ws_env.injector.process_pending()
        # the down, then the release queued when the socket closed
        assert ws_env.runner.calls[0][-2:] == ["mousedown", "1"]
        assert ws_env.runner.calls[-1] == ["xdotool", "mouseup", "1"]

    @pytest.mark.parametrize("origin, host, ok", [
        (None, "10.0.0.1:5002", True),
        ("http://10.0.0.1:5002", "10.0.0.1:5002", True),
        ("http://10.0.0.1", "10.0.0.1:80", True),          # default port
        ("https://bcm.local", "bcm.local:443", True),
        ("http://10.0.0.1:5002", "localhost:5002", False),
        ("https://10.0.0.1:80", "10.0.0.1", False),
        ("http://[::1]:5002", "[::1]:5002", True),
        ("http://x", None, False),
        ("http://x", "", False),
        ("http://[bad", "x", False),
    ])
    def test_origin_helper(self, origin, host, ok):
        assert wv._ws_origin_allowed(origin, host) is ok


# ── AA restart endpoint ──────────────────────────────────────────────────

class _FakeOpenAuto:
    def __init__(self, busy):
        self.restart_in_progress = busy
        self.calls = 0
        self.done = threading.Event()
        self.auto_restart_enabled = True

    def restart(self):
        self.calls += 1
        self.done.set()
        return True


class TestRestartEndpoint:
    @pytest.mark.parametrize("path", ["/aa/restart", "/api/aa/restart"])
    def test_already_restarting_spawns_nothing(self, env, path):
        fake = _FakeOpenAuto(busy=True)
        env.bus.publish("multimedia._internals", {"openauto": fake})
        before = {t.ident for t in threading.enumerate()}
        res = env.client.post(path)
        assert res.status_code == 200
        assert res.get_json() == {"ok": True, "status": "already_restarting"}
        assert fake.calls == 0
        new = [t for t in threading.enumerate()
               if t.ident not in before and t.name == "aa-http-restart"]
        assert new == []

    def test_idle_controller_is_restarted_in_background(self, env):
        fake = _FakeOpenAuto(busy=False)
        env.bus.publish("multimedia._internals", {"openauto": fake})
        res = env.client.post("/api/aa/restart")
        assert res.get_json() == {"ok": True, "status": "restarting"}
        assert fake.done.wait(5)
        assert fake.calls == 1

    def test_dashboard_data_carries_stream_epoch(self, env):
        assert env.viewer._get_dashboard_data()["aa_stream_epoch"] == 0
        env.bus.publish("multimedia.aa_stream_epoch", 1234.5)
        assert env.viewer._get_dashboard_data()["aa_stream_epoch"] == 1234.5


# ── /aa/stream MJPEG generator ───────────────────────────────────────────

JPEG_A = b"\xff\xd8" + b"frame-a" + b"\xff\xd9"
JPEG_B = b"\xff\xd8" + b"frame-b" + b"\xff\xd9"


class _FakeFfmpeg:
    """A Popen stand-in whose stdout is a real pipe (poll() works).

    ``min_fd`` moves the read end to a descriptor >= that number, to prove
    the generator is not bound by select()'s FD_SETSIZE (1024).
    """

    def __init__(self, min_fd=None):
        r, w = os.pipe()
        if min_fd is not None:
            high = fcntl.fcntl(r, fcntl.F_DUPFD, min_fd)
            os.close(r)
            r = high
        self.stdout = os.fdopen(r, "rb", buffering=0)
        self._w = w
        self.terminated = False

    def write(self, data):
        os.write(self._w, data)

    def close_writer(self):
        if self._w is not None:
            os.close(self._w)
            self._w = None

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.terminated = True


@pytest.fixture
def fast_stream(monkeypatch):
    monkeypatch.setattr(wv, "_AA_STREAM_READ_TIMEOUT_S", 0.05)
    monkeypatch.setattr(wv, "_AA_STREAM_STALL_S", 0.3)
    procs = []
    yield procs
    for p in procs:
        p.close_writer()


class TestMJPEGStream:
    def _start(self, viewer, procs, argv_seen=None, min_fd=None):
        fake = _FakeFfmpeg(min_fd=min_fd)
        procs.append(fake)

        def popen(argv, **kw):
            if argv_seen is not None:
                argv_seen.append((argv, kw))
            return fake
        return fake, viewer._aa_mjpeg_frames(popen=popen)

    def test_frames_then_stall_ends_stream(self, env, fast_stream):
        seen = []
        fake, gen = self._start(env.viewer, fast_stream, seen)
        fake.write(JPEG_A + JPEG_B[:5])
        assert JPEG_A in next(gen)
        fake.write(JPEG_B[5:])
        assert JPEG_B in next(gen)
        t0 = time.monotonic()
        with pytest.raises(StopIteration):
            next(gen)
        assert 0.2 <= time.monotonic() - t0 < 5
        assert fake.terminated
        assert env.viewer._aa_stream_active == []
        argv, kw = seen[0]
        w, h = env.size
        assert argv[:3] == ["ffmpeg", "-f", "x11grab"]
        assert f"{w}x{h}" in argv and ":99" in argv
        assert kw.get("bufsize") == 0 and not kw.get("shell")

    def test_eof_ends_stream(self, env, fast_stream):
        fake, gen = self._start(env.viewer, fast_stream)
        fake.write(JPEG_A)
        next(gen)
        fake.close_writer()
        with pytest.raises(StopIteration):
            next(gen)
        assert fake.terminated

    @pytest.mark.skipif(resource.getrlimit(resource.RLIMIT_NOFILE)[0] < 1100,
                        reason="RLIMIT_NOFILE too low for an fd above 1024")
    def test_fd_above_fd_setsize_still_streams(self, env, fast_stream):
        # select() raises ValueError for fd >= 1024 and used to end the stream
        fake, gen = self._start(env.viewer, fast_stream, min_fd=1024)
        assert fake.stdout.fileno() >= 1024
        fake.write(JPEG_A)
        assert JPEG_A in next(gen)
        fake.write(JPEG_B)
        assert JPEG_B in next(gen)
        gen.close()
        assert fake.terminated

    def test_at_most_two_streams_newest_win(self, env, fast_stream):
        streams = [self._start(env.viewer, fast_stream) for _ in range(3)]
        for fake, gen in streams:
            fake.write(JPEG_A)
        for fake, gen in streams:
            next(gen)
        (f1, g1), (f2, g2), (f3, g3) = streams
        # The retired stream's ffmpeg is stopped by the newer request while
        # g1 is still suspended in ``yield`` (= its thread blocked writing to
        # a client that stopped reading) — not only once g1 resumes.
        assert f1.terminated
        assert set(env.viewer._aa_stream_procs) == {2, 3}
        with pytest.raises(StopIteration):
            next(g1)                       # retired by the third stream
        assert f1.terminated
        assert len(env.viewer._aa_stream_active) == 2
        assert not f2.terminated and not f3.terminated
        g2.close()
        g3.close()
        assert f2.terminated and f3.terminated
        assert env.viewer._aa_stream_active == []
        assert env.viewer._aa_stream_procs == {}

    def test_route_without_ffmpeg_returns_empty_stream(self, env, no_web_subprocess):
        res = env.client.get("/aa/stream")
        assert res.status_code == 200
        assert res.mimetype == "multipart/x-mixed-replace"
        assert res.data == b""
        assert no_web_subprocess and no_web_subprocess[0][0] == "ffmpeg"
        assert env.viewer._aa_stream_active == []


# ── POST /api/phone/dial (browser input -> log, bus, oFono) ─────────────

class TestPhoneDialRoute:
    def _dials(self, env):
        seen = []
        env.bus.subscribe("bt.cmd.dial", lambda t, v, ts: seen.append(v))
        return seen

    def test_phonebook_number_is_normalised(self, env):
        seen = self._dials(env)
        res = env.client.post("/api/phone/dial", json={"number": "+48 600-123-456"})
        assert res.status_code == 200
        assert res.get_json() == {"ok": True, "number": "+48600123456"}
        assert seen == ["+48600123456"]

    @pytest.mark.parametrize("body", [
        {"number": "600\nINFO forged"}, {"number": "abc"}, {"number": "1" * 40},
        {"number": ""}, {"number": None}, {"number": ["112"]}, {}, None, "112",
    ])
    def test_invalid_is_400_and_never_published(self, env, body):
        seen = self._dials(env)
        res = env.client.post("/api/phone/dial", json=body)
        assert res.status_code == 400
        assert res.get_json()["ok"] is False
        assert seen == []


# ── Phone internet / LTE in the dashboard payload ────────────────────────

class TestConnectivityPayload:
    def test_phone_tether_is_none_while_the_module_never_published(self, env):
        # Production config: module off -> no row in Settings (unchanged UI).
        assert env.viewer._get_dashboard_data()["phone_tether"] is None

    def test_phone_tether_summary(self, env):
        env.bus.publish("net.phone_tether", {
            "state": "connected", "iface": "bnep0", "ip": "192.168.44.23", "prefix": 24,
            "gateway": "192.168.44.1", "mac": "AA:BB:CC:DD:EE:01", "error": "", "hint": "",
            "since": 1.0})
        assert env.viewer._get_dashboard_data()["phone_tether"] == {
            "state": "connected", "ip": "192.168.44.23", "iface": "bnep0", "hint": ""}

    def test_phone_tether_failed_hint_is_passed_on(self, env):
        env.bus.publish("net.phone_tether", {"state": "failed", "hint": "check_tethering",
                                             "error": "Error: <raw nmcli text>"})
        summary = env.viewer._get_dashboard_data()["phone_tether"]
        assert summary == {"state": "failed", "ip": "", "iface": "", "hint": "check_tethering"}
        assert "error" not in summary          # raw error text never reaches the UI

    @pytest.mark.parametrize("value, expected", [
        ({"state": "<script>"}, {"state": "unknown", "ip": "", "iface": "", "hint": ""}),
        ({"state": "connected", "ip": "x" * 100, "iface": ["bnep0"], "hint": "<b>"},
         {"state": "connected", "ip": "", "iface": "", "hint": ""}),
        ("connected", None),
    ])
    def test_phone_tether_garbage_is_neutralised(self, env, value, expected):
        env.bus.publish("net.phone_tether", value)
        assert env.viewer._get_dashboard_data()["phone_tether"] == expected

    def test_lte_signal_reads_the_published_key(self, env):
        env.bus.publish("lte.signal", 3)
        assert env.viewer._get_dashboard_data()["lte_signal"] == 3


# ── POST /api/phone_tether/retry ─────────────────────────────────────────

class TestPhoneTetherRetryRoute:
    def _seen(self, env):
        seen = []
        env.bus.subscribe("net.phone_tether.cmd.retry", lambda t, v, ts: seen.append(v))
        return seen

    def test_publishes_an_argument_free_retry(self, env):
        seen = self._seen(env)
        res = env.client.post("/api/phone_tether/retry",
                              json={"mac": "AA:BB:CC:DD:EE:01; reboot", "con": "--x"})
        assert res.status_code == 200 and res.get_json() == {"ok": True}
        assert seen == [True]                  # the body never travels on

    def test_rate_limited(self, env):
        seen = self._seen(env)
        assert env.client.post("/api/phone_tether/retry").status_code == 200
        res = env.client.post("/api/phone_tether/retry")
        assert res.status_code == 429
        assert 1 <= int(res.headers["Retry-After"]) <= 11
        assert seen == [True]
        env.viewer._tether_retry_last -= wv._TETHER_RETRY_MIN_INTERVAL_S   # time passes
        assert env.client.post("/api/phone_tether/retry").status_code == 200
        assert seen == [True, True]

    def test_get_is_not_allowed(self, env):
        assert env.client.get("/api/phone_tether/retry").status_code == 405


# ── POST /api/weather/location ───────────────────────────────────────────

class TestWeatherLocationRoute:
    def _seen(self, env):
        seen = []
        env.bus.subscribe("weather.search_location", lambda t, v, ts: seen.append(v))
        return seen

    def test_valid_location_is_published_as_floats(self, env):
        seen = self._seen(env)
        res = env.client.post("/api/weather/location",
                              json={"lat": "52.23", "lon": 21.01, "city": "Warszawa"})
        assert res.status_code == 200
        assert seen == [{"lat": 52.23, "lon": 21.01, "city": "Warszawa"}]

    @pytest.mark.parametrize("body", [
        {"lat": "1&appid=evil", "lon": 2}, {"lat": 91, "lon": 0}, {"lat": 0, "lon": 181},
        {"lat": True, "lon": 1}, {"lat": [1], "lon": 1}, {"lat": 1}, {}, None, "52,21",
        {"lat": 10 ** 400, "lon": 1}, {"lat": "nan", "lon": 1},
    ])
    def test_invalid_is_400_and_never_published(self, env, body):
        seen = self._seen(env)
        res = env.client.post("/api/weather/location", json=body)
        assert res.status_code == 400
        assert seen == []


# ── Trips + GPX (src/location/tracker.py) ────────────────────────────────

class _TrackerCfg:
    def __init__(self, db):
        self._data = {"tracking.db_path": db, "tracking.interval_sec": 0,
                      "tracking.trip_end_idle_sec": 0}

    def get(self, key, default=None):
        return self._data.get(key, default)


@pytest.fixture
def tracker(env, tmp_path):
    from src.location.tracker import start_tracker
    trk = start_tracker(config=_TrackerCfg(str(tmp_path / "trips.db")), event_bus=env.bus)
    yield trk
    trk.stop()


def _drive(bus):
    for lat, speed in ((52.2297, 50.0), (52.2397, 60.0), (52.2497, 0.0), (52.2497, 0.0)):
        bus.publish("gps.position", {"lat": lat, "lon": 21.0122, "speed": speed,
                                     "heading": 0.0, "alt": 100.0, "altitude": 100.0,
                                     "fix": True})


class _FakeTracker:
    """list_trips/get_trip/export_gpx recorder for the edge cases."""

    def __init__(self, trips=(), points=0):
        self.trips = list(trips)
        self.points = points
        self.limits = []

    def list_trips(self, limit=50):
        self.limits.append(limit)
        return self.trips

    def get_trip(self, trip_id):
        return {"trip_id": trip_id, "start_ts": 0, "points": self.points}

    def export_gpx(self, trip_id):
        raise AssertionError("must not export a trip without points")


class TestTripsRoutes:
    def test_503_when_tracking_module_is_off(self, env):
        assert env.client.get("/api/tracking/trips").status_code == 503
        assert env.client.get("/api/tracking/trips").get_json()["trips"] == []
        assert env.client.get("/api/tracking/trips/1.gpx").status_code == 503
        res = env.client.get("/trips")
        assert res.status_code == 503 and "modules.tracking" in res.get_data(as_text=True)

    def test_trip_list_json(self, env, tracker):
        _drive(env.bus)
        res = env.client.get("/api/tracking/trips")
        assert res.status_code == 200
        trips = res.get_json()["trips"]
        assert len(trips) == 1
        trip = trips[0]
        assert trip["trip_id"] == 1 and trip["points"] >= 3 and trip["distance_km"] > 0
        assert trip["end_ts"] is not None
        assert trip["gpx_url"] == "/api/tracking/trips/1.gpx"

    @pytest.mark.parametrize("raw, expected", [
        (None, 50), ("0", 1), ("-5", 1), ("7", 7), ("500", 500), ("100000", 500),
        ("abc", 50), ("1e3", 50), ("", 50), ("9" * 40, 50), ("٣", 50),
        ("--5", 50), ("+5", 50), ("5-", 50), ("-", 50), ("0x10", 50),
    ])
    def test_limit_is_clamped(self, env, raw, expected):
        fake = _FakeTracker()
        env.bus.publish("tracking._internals", {"tracker": fake})
        from urllib.parse import quote
        url = "/api/tracking/trips" + ("" if raw is None else "?limit=" + quote(raw))
        assert env.client.get(url).status_code == 200
        assert fake.limits == [expected]

    def test_gpx_download(self, env, tracker):
        import xml.etree.ElementTree as ET
        _drive(env.bus)
        start_ts = tracker.get_trip(1)["start_ts"]
        res = env.client.get("/api/tracking/trips/1.gpx")
        assert res.status_code == 200
        assert res.mimetype == "application/gpx+xml"
        day = time.strftime("%Y%m%d", time.localtime(start_ts))
        assert res.headers["Content-Disposition"] == f'attachment; filename="bcm-trip-1-{day}.gpx"'
        assert res.headers["X-Content-Type-Options"] == "nosniff"
        root = ET.fromstring(res.data)
        assert root.tag == "{http://www.topografix.com/GPX/1/1}gpx"
        assert len(root.findall(".//{http://www.topografix.com/GPX/1/1}trkpt")) >= 3

    def test_gpx_404s(self, env, tracker):
        assert env.client.get("/api/tracking/trips/999.gpx").status_code == 404
        assert env.client.get("/api/tracking/trips/" + "9" * 30 + ".gpx").status_code == 404
        assert env.client.get("/api/tracking/trips/-1.gpx").status_code == 404
        assert env.client.get("/api/tracking/trips/abc.gpx").status_code == 404

    def test_gpx_404_for_a_trip_without_points(self, env):
        env.bus.publish("tracking._internals", {"tracker": _FakeTracker(points=0)})
        assert env.client.get("/api/tracking/trips/3.gpx").status_code == 404

    def test_trips_page_lists_and_links(self, env, tracker):
        _drive(env.bus)
        res = env.client.get("/trips")
        assert res.status_code == 200 and res.mimetype == "text/html"
        body = res.get_data(as_text=True)
        assert "Zapisane trasy" in body and "Trasa 1" in body
        assert 'href="/api/tracking/trips/1.gpx"' in body
        assert "default-src 'none'" in res.headers["Content-Security-Policy"]
        assert "<script" not in body and 'class="' not in body   # inline styles only

    def test_trips_page_escapes_everything(self, env):
        env.bus.publish("tracking._internals", {"tracker": _FakeTracker(trips=[
            {"trip_id": 5, "start_ts": "<b>x</b>", "end_ts": None, "distance_km": "<i>",
             "avg_speed": None, "max_speed": float("nan"), "points": 0},
            {"trip_id": "<script>alert(1)</script>"},
            "garbage",
        ])})
        env.bus.publish("gps.fix", True)
        env.bus.publish("gps.source_state", {"source": "udp",
                                             "peer": "<script>alert(1)</script>"})
        res = env.client.get("/trips")
        body = res.get_data(as_text=True)
        assert res.status_code == 200
        assert "<script" not in body and "<b>" not in body and "<i>" not in body
        assert "&lt;script&gt;" in body                   # the peer, escaped
        assert "Trasa 5" in body and "w trakcie" in body and "brak punktów" in body


# ── Network access policy ────────────────────────────────────────────────

def _policy_client(env, mode, networks=None):
    env.cfg.set("dashboard.remote_access", mode)
    if networks is not None:
        env.cfg.set("dashboard.allowed_networks", networks)
    return env.viewer._build_app().test_client()


def _as(addr, host="10.0.0.1:5002"):
    """Request from ``addr`` with this ``Host`` header (an IP by default,
    as a phone browser opening http://10.0.0.1:5002/trips sends)."""
    return {"environ_base": {"REMOTE_ADDR": addr},
            "environ_overrides": {"HTTP_HOST": host}}


class TestAccessPolicy:
    def test_production_default_is_full_from_anywhere(self, env):
        assert env.cfg.get("dashboard.remote_access") is None
        assert env.client.get("/api/data", **_as("8.8.8.8")).status_code == 200

    def test_outside_allowed_networks_is_403(self, env, tracker):
        client = _policy_client(env, "tracking")
        res = client.get("/trips", **_as("8.8.8.8"))
        assert res.status_code == 403
        assert res.get_json()["config_key"] == "dashboard.allowed_networks"

    def test_tracking_mode_allows_trips_only(self, env, tracker):
        client = _policy_client(env, "tracking")
        seen = []
        env.bus.subscribe("net.phone_tether.cmd.retry", lambda t, v, ts: seen.append(v))
        phone = _as("10.0.0.23")
        assert client.get("/trips", **phone).status_code == 200
        assert client.get("/api/tracking/trips", **phone).status_code == 200
        assert client.get("/api/data", **phone).status_code == 403
        assert client.get("/", **phone).status_code == 403
        assert client.get("/no/such/page", **phone).status_code == 403
        res = client.post("/api/phone_tether/retry", **phone)
        assert res.status_code == 403
        body = res.get_json()
        assert body["config_key"] == "dashboard.remote_access" and "/trips" in body["hint"]
        assert seen == []

    @pytest.mark.parametrize("addr", ["127.0.0.1", "127.0.0.2", "::1", "::ffff:127.0.0.1"])
    def test_loopback_kiosk_always_has_full_access(self, env, addr):
        for mode in ("tracking", "none", "readonly"):
            client = _policy_client(env, mode)
            assert client.get("/api/data", **_as(addr)).status_code == 200
            assert client.post("/api/phone_tether/retry", **_as(addr)).status_code in (200, 429)

    def test_readonly_mode(self, env):
        client = _policy_client(env, "readonly")
        lan = _as("192.168.1.50")
        assert client.get("/api/data", **lan).status_code == 200
        assert client.head("/api/config", **lan).status_code == 200
        assert client.post("/api/phone_tether/retry", **lan).status_code == 403
        assert client.post("/api/weather/location", json={"lat": 1, "lon": 2},
                           **lan).status_code == 403
        assert client.get("/api/wifi/config", **lan).status_code == 403    # passwords

    def test_readonly_refuses_gets_with_side_effects(self, env):
        client = _policy_client(env, "readonly")
        lan = _as("192.168.1.50")
        requests_seen = []
        env.bus.subscribe("obd.dtc.read_request", lambda t, v, ts: requests_seen.append(v))
        assert client.get("/api/dtc/read", **lan).status_code == 403     # K-Line to the ECU
        assert requests_seen == []
        assert client.get("/api/weather/search?q=Milano", **lan).status_code == 403
        assert client.get("/api/trip/search?q=Milano", **lan).status_code == 403

    def test_every_get_view_is_classified_for_readonly(self, env):
        # A new GET route must be put on the allow-list or the deny-list
        # deliberately — an unclassified one is refused from the network.
        app = env.viewer._build_app()
        gets = {rule.endpoint for rule in app.url_map.iter_rules()
                if "GET" in (rule.methods or ())}
        assert not wv._READONLY_ENDPOINTS & wv._READONLY_DENIED_ENDPOINTS
        assert gets == wv._READONLY_ENDPOINTS | wv._READONLY_DENIED_ENDPOINTS

    @pytest.mark.parametrize("mode", ["tracking", "readonly"])
    def test_dns_rebinding_host_is_refused(self, env, tracker, mode):
        client = _policy_client(env, mode)
        res = client.get("/trips", **_as("10.0.0.23", host="evil.example:5002"))
        assert res.status_code == 403
        body = res.get_json()
        assert body["config_key"] == "dashboard.allowed_hosts" and "10.0.0.1" in body["hint"]
        assert client.get("/api/tracking/trips/1.gpx",
                          **_as("10.0.0.23", host="evil.example")).status_code == 403
        assert client.get("/trips", **_as("10.0.0.23")).status_code == 200
        assert client.get("/trips", **_as("10.0.0.23", host="[fe80::1]:5002")).status_code == 200
        # The kiosk is not affected (a rebinding page cannot come from here).
        assert client.get("/trips", **_as("127.0.0.1", host="localhost:5002")).status_code == 200

    def test_allowed_hosts_lets_a_name_through(self, env, tracker):
        env.cfg.set("dashboard.allowed_hosts", ["BCM.local.", "bad name", 5])
        client = _policy_client(env, "tracking")
        assert client.get("/trips", **_as("10.0.0.23", host="bcm.local:5002")).status_code == 200
        assert client.get("/trips", **_as("10.0.0.23", host="evil.example")).status_code == 403

    def test_full_mode_does_not_check_host(self, env):
        # Production default: the legacy behaviour, whatever the Host.
        assert env.client.get("/api/data", **_as("8.8.8.8", host="car.example")).status_code == 200

    def test_none_mode_and_typos_fail_closed(self, env, tracker):
        for mode in ("none", "readonyl", 5):
            client = _policy_client(env, mode)
            assert client.get("/trips", **_as("10.0.0.23")).status_code == 403
            assert client.get("/trips").status_code == 200        # loopback

    def test_custom_networks_and_bad_entries(self, env, tracker):
        client = _policy_client(env, "tracking", ["10.0.0.0/24", "not-a-cidr"])
        assert client.get("/trips", **_as("10.0.0.23")).status_code == 200
        assert client.get("/trips", **_as("10.0.1.23")).status_code == 403
        assert client.get("/trips", **_as("192.168.1.2")).status_code == 403

    def test_policy_endpoints_exist(self, env):
        app = env.viewer._build_app()
        names = set(app.view_functions)
        assert wv._TRACKING_ENDPOINTS <= names
        assert wv._READONLY_ENDPOINTS <= names
        assert wv._READONLY_DENIED_ENDPOINTS <= names
        assert {"ws_data_handler", "ws_input_handler"} <= names

    def test_refusals_are_logged_once_per_minute(self, env, monkeypatch):
        lines = []
        monkeypatch.setattr(wv.log, "info", lambda msg, *a: lines.append(msg % a))
        client = _policy_client(env, "none")
        for _ in range(5):
            client.get("/api/data", **_as("10.0.0.23"))
        client.get("/api/data", **_as("10.0.0.24"))
        refused = [line for line in lines if line.startswith("Refused")]
        assert len(refused) == 2
        assert "dashboard.remote_access" in refused[0]

    @pytest.mark.parametrize("addr, method, endpoint, mode, allowed", [
        ("10.0.0.5", "GET", "trips_page", "tracking", True),
        ("10.0.0.5", "HEAD", "api_tracking_trip_gpx", "tracking", True),
        ("10.0.0.5", "POST", "trips_page", "tracking", False),
        ("10.0.0.5", "GET", None, "tracking", False),
        ("10.0.0.5", "GET", "ws_data_handler", "readonly", True),
        ("10.0.0.5", "GET", "ws_input_handler", "readonly", False),
        ("10.0.0.5", "DELETE", "api_dvr_delete", "readonly", False),
        ("10.0.0.5", "GET", "api_dtc_read", "readonly", False),
        ("10.0.0.5", "GET", "api_weather_search", "readonly", False),
        ("10.0.0.5", "GET", "api_trip_search", "readonly", False),
        ("10.0.0.5", "GET", "some_future_view", "readonly", False),
        ("10.0.0.5", "GET", None, "readonly", False),
        ("10.0.0.5", "GET", "api_data", "readonly", True),
        ("8.8.8.8", "POST", "api_system_reboot", "full", True),
        ("8.8.8.8", "GET", "trips_page", "readonly", False),
        ("", "GET", "trips_page", "tracking", False),
        (None, "GET", "trips_page", "tracking", False),
        ("fe80::1%wlan0", "GET", "trips_page", "tracking", False),
        ("::1", "POST", "api_system_reboot", "none", True),
    ])
    def test_decision_table(self, addr, method, endpoint, mode, allowed):
        nets = tuple(wv.ipaddress.ip_network(n) for n in wv._DEFAULT_ALLOWED_NETWORKS)
        decision = wv._access_decision(addr, method, endpoint, mode, nets, "10.0.0.1:5002")
        assert (decision is None) is allowed

    @pytest.mark.parametrize("host, allowed", [
        ("10.0.0.1:5002", True),
        ("10.0.0.1", True),
        ("192.168.44.23:5002", True),
        ("[fe80::1]:5002", True),
        ("[::1]", True),
        ("bcm.local:5002", True),          # in allowed_hosts
        ("BCM.LOCAL.", True),
        ("evil.example:5002", False),
        ("10.0.0.1.nip.io:5002", False),
        ("0x0a000001:5002", False),        # numeric forms only browsers decode
        ("localhost:5002", False),         # from a remote address: not a browser
        ("[fe80::1", False),
        ("", False),
        (None, False),
    ])
    def test_host_header_table(self, host, allowed):
        nets = tuple(wv.ipaddress.ip_network(n) for n in wv._DEFAULT_ALLOWED_NETWORKS)
        decision = wv._access_decision("10.0.0.23", "GET", "trips_page", "tracking", nets,
                                       host, ("bcm.local",))
        assert (decision is None) is allowed
        if not allowed:
            assert decision[0] == "dashboard.allowed_hosts"


class _FakeDataWS(_FakeWSServer):
    def __init__(self, environ, **kw):
        super().__init__(environ, **kw)
        self.sent = []

    def send(self, data):
        self.sent.append(data)


class TestWebSocketPolicy:
    @pytest.fixture
    def ws_env(self, env, monkeypatch):
        import flask_sock
        _FakeWSServer.instances = []
        monkeypatch.setattr(flask_sock, "Server", _FakeDataWS)
        env.viewer._running = True
        yield env
        env.viewer._running = False

    def _open(self, client, path, addr="127.0.0.1", origin=None, host="localhost:5002"):
        headers = {"Upgrade": "websocket", "Connection": "Upgrade",
                   "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ==",
                   "Sec-WebSocket-Version": "13", "Host": host}
        if origin is not None:
            headers["Origin"] = origin
        return client.get(path, headers=headers, **_as(addr, host))

    def test_data_socket_checks_origin(self, ws_env):
        self._open(ws_env.client, "/ws", origin="http://evil.example")
        ws = _FakeWSServer.instances[-1]
        assert ws.sent == [] and ws.received == 0
        self._open(ws_env.client, "/ws", origin="http://localhost:5002")
        ws = _FakeWSServer.instances[-1]
        assert len(ws.sent) == 1 and json.loads(ws.sent[0])["gps_fix"] is False

    def test_policy_runs_before_the_websocket_handshake(self, ws_env):
        client = _policy_client(ws_env, "readonly")
        res = self._open(client, "/ws/input", addr="10.0.0.23", host="10.0.0.1:5002",
                         origin="http://10.0.0.1:5002")
        assert res.status_code == 403
        assert _FakeWSServer.instances == []          # never reached flask_sock
        self._open(client, "/ws", addr="10.0.0.23", host="10.0.0.1:5002",
                   origin="http://10.0.0.1:5002")
        assert len(_FakeWSServer.instances) == 1      # the data socket is a view
        client = _policy_client(ws_env, "tracking")
        res = self._open(client, "/ws", addr="10.0.0.23", host="10.0.0.1:5002")
        assert res.status_code == 403 and len(_FakeWSServer.instances) == 1
