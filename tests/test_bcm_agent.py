"""The Termux agent on the car phone (tools/car_phone/termux/bcm_agent.py).

Imported by path (it is not a package and runs in Termux, not here); no
Termux: every phone command goes through a fake runner that refuses
anything unexpected, clocks are injected, state lives in tmp_path.

Covers: HMAC on requests (bad signature, old timestamp, replayed / lower
nonce — also after a restart), signed answers (and none for strangers),
body limit, bind address and connection cap, pairing only with the PAIRING
file (deleted after, secret 0600, never logged), the config, idempotent
crash events with the deadline held by the agent (fake clock), cancel
before / after sending with exactly one follow-up SMS, the 10 min / 3 per
day limits persisted, resume after a restart, retries and verification,
GSM-7 only texts within 2 segments, the number as the only free word in
argv, dry_run never calling termux-sms-send, the test SMS.
"""

from __future__ import annotations

import ast
import calendar
import importlib.util
import json
import logging
import os
import py_compile
import socket
import stat
import sys
import threading
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
AGENT_PATH = REPO / "tools" / "car_phone" / "termux" / "bcm_agent.py"
BOOT_PATH = REPO / "tools" / "car_phone" / "termux" / "boot_bcm_agent.sh"


def load_agent_module(name: str = "bcm_agent_under_test"):
    """Import bcm_agent.py by path without leaving a __pycache__ in tools/."""
    old = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location(name, AGENT_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = old
    return mod


A = load_agent_module()

SECRET = "5e" * 32                       # 64 hex characters — a test value
KEY = bytes.fromhex(SECRET)
OTHER = "a7" * 32
T0 = 1_763_000_000
NUM1, NUM2 = "+48601234567", "+48601234568"

#: GSM 03.38 basic character set, written out independently of the agent's.
GSM7 = set("@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
           "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà")


class FakeRunner:
    """Termux:API stand-in. What termux-sms-send got lands in the SMS
    provider ``land_after`` seconds later (fake BOOTTIME clock) as ``sent``
    — or as ``failed`` while ``land_as`` says so; ``record_sent`` False =
    it never shows up in any box (still "in flight")."""

    def __init__(self, clock=None):
        self.clock = clock
        self.calls = []
        self.sent = []                 # (number, text, type) in the provider
        self.pending = []              # (number, text, type, lands at boot s)
        self.send_rc = 0
        self.send_err = ""
        self.record_sent = True
        self.land_after = 0.0
        self.land_as = "sent"
        self.list_ok = True
        self.typed = True              # False: an old termux-api without "type"
        self.record_on_error = False   # a failed / timed-out send may still land
        self.sim = "ready"
        self.operator = "26001"
        self.hook = None               # hook(argv) runs before a command answers

    def _now(self):
        return self.clock.boot if self.clock is not None else 0.0

    def __call__(self, argv, stdin, timeout):
        assert isinstance(argv, list) and all(isinstance(a, str) for a in argv), argv
        assert timeout > 0
        self.calls.append((list(argv), stdin))
        if self.hook is not None:
            self.hook(argv)
        prog = argv[0]
        if prog == "termux-sms-send":
            assert argv[1] == "-n" and A.E164_RE.fullmatch(argv[2]), argv
            if (self.send_rc == 0 or self.record_on_error) and self.record_sent:
                self.pending.append((argv[2], stdin, self.land_as,
                                     self._now() + self.land_after))
            return self.send_rc, "", self.send_err
        if prog == "termux-sms-list":
            assert argv[1:3] == ["-t", "all"], argv
            if not self.list_ok:
                return 1, "", "Error: READ_SMS permission"
            now = self._now()
            self.sent += [(n, b, t) for n, b, t, at in self.pending if at <= now]
            self.pending = [p for p in self.pending if p[3] > now]
            items = [{"type": t, "number": n, "body": b} for n, b, t in self.sent]
            items.append({"type": "inbox", "number": "+48500000000", "body": "operator"})
            if not self.typed:
                for item in items:
                    del item["type"]
            return 0, json.dumps(items), ""
        if prog == "termux-telephony-deviceinfo":
            return 0, json.dumps({"sim_state": self.sim, "network_operator": self.operator}), ""
        if prog == "termux-battery-status":
            return 0, json.dumps({"percentage": 81, "temperature": 30.4, "plugged": "PLUGGED_USB",
                                  "status": "CHARGING", "health": "GOOD"}), ""
        raise AssertionError(f"unexpected command {argv}")

    def sms_calls(self):
        return [(argv, stdin) for argv, stdin in self.calls if argv[0] == "termux-sms-send"]


class Clock:
    def __init__(self):
        self.boot = 1000.0
        self.wall = float(T0)

    def advance(self, s):
        self.boot += s
        self.wall += s


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def runner(clock):
    return FakeRunner(clock)


@pytest.fixture
def state_dir(tmp_path):
    return str(tmp_path / "bcm_agent")


def make_agent(state_dir, runner, clock):
    return A.Agent(state_dir, runner=runner, clock=lambda: clock.boot,
                   wall=lambda: clock.wall, localtime=time.gmtime)


class Peer:
    """BCM's side in miniature: signs, keeps a nonce, verifies answers."""

    def __init__(self, agent, clock, key=KEY, nonce=100):
        self.agent = agent
        self.clock = clock
        self.key = key
        self.nonce = nonce

    def raw(self, method, path, body=b"", nonce=None, ts=None, key=None, sig=None):
        if nonce is None:
            self.nonce += 1
            nonce = self.nonce
        ts = int(self.clock.wall) if ts is None else ts
        key = self.key if key is None else key
        if sig is None:
            sig = A.sign(key, A.request_message(method, path, ts, nonce, body))
        headers = {"X-BCM-Ts": str(ts), "X-BCM-Nonce": str(nonce), "X-BCM-Sig": sig}
        status, data, hdrs = self.agent.handle(method, path, headers, body)
        return status, json.loads(data), hdrs, nonce, data

    def req(self, method, path, obj=None, **kw):
        body = b"" if obj is None else json.dumps(obj).encode()
        status, out, hdrs, nonce, data = self.raw(method, path, body, **kw)
        # every authenticated answer is signed over OUR nonce
        assert hdrs.get("X-BCM-Sig") == A.sign(self.key, A.response_message(status, nonce, data))
        return status, out


CODE = "0123456789"                      # a pairing code as --pair writes it


def pair_request(agent, secret=SECRET, nonce=50, code=CODE, ts=None, body=None):
    """POST /v1/pair signed with the pairing ``code`` (no PAIRING file is
    created here)."""
    body = json.dumps({"secret": secret}).encode() if body is None else body
    ts = int(agent._wall()) if ts is None else ts
    sig = A.sign(code.encode(), A.request_message("POST", "/v1/pair", ts, nonce, body))
    status, data, hdrs = agent.handle("POST", "/v1/pair", {
        "X-BCM-Ts": str(ts), "X-BCM-Nonce": str(nonce), "X-BCM-Sig": sig}, body)
    return status, json.loads(data), hdrs, data


def pair(agent, state_dir, secret=SECRET, nonce=50, code=CODE):
    Path(state_dir, "PAIRING").write_text(code + "\n")
    return pair_request(agent, secret, nonce, code)


CONFIG = {"recipients": [NUM1, NUM2], "sim_slot": 0, "vehicle_label": "ALFA 156",
          "toggles": {"crash_sms": True, "parking_guard": False, "cabin_watch": False,
                      "call112": False},
          "dry_run": False, "follow_up_cancel": True}

CRASH = {"event_id": "c0ffee01", "countdown_s": 45, "lat": 52.22968, "lon": 21.01223,
         "fix_age_s": 4, "speed_kmh": 72, "dv_kmh": 45, "event_ts": T0}


@pytest.fixture
def ready(state_dir, runner, clock):
    """A paired agent with two recipients, real (non-dry) sending."""
    agent = make_agent(state_dir, runner, clock)
    assert pair(agent, state_dir)[0] == 200
    peer = Peer(agent, clock)
    assert peer.req("PUT", "/v1/config", CONFIG)[0] == 200
    return agent, peer


def run_steps(agent, n=20):
    for _ in range(n):
        if agent.step() > 0:
            break


# ── the file itself ──────────────────────────────────────────────────────

class TestFile:
    def test_py_compile(self, tmp_path):
        py_compile.compile(str(AGENT_PATH), cfile=str(tmp_path / "agent.pyc"), doraise=True)

    def test_stdlib_only(self):
        tree = ast.parse(AGENT_PATH.read_text(encoding="utf-8"))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names.add(node.module.split(".")[0])
        assert names <= set(sys.stdlib_module_names) | {"__future__"}, names

    def test_no_shell_anywhere(self):
        text = AGENT_PATH.read_text(encoding="utf-8")
        assert "shell=True" not in text and "os.system" not in text and "os.popen" not in text

    def test_docs_in_polish_at_the_top(self):
        doc = ast.get_docstring(ast.parse(AGENT_PATH.read_text(encoding="utf-8")))
        for needle in ("pkg install python termux-api", "Termux:Boot", "termux-wake-lock",
                       "boot_bcm_agent.sh", "PAIRING", "Optymalizacja baterii"):
            assert needle in doc, needle

    def test_boot_script_syntax(self):
        import shutil
        import subprocess
        for sh in ("bash", "dash"):
            if shutil.which(sh):
                res = subprocess.run([sh, "-n", str(BOOT_PATH)], capture_output=True, text=True,
                                     timeout=30)
                assert res.returncode == 0, res.stderr
        text = BOOT_PATH.read_text(encoding="utf-8")
        assert "termux-wake-lock" in text and "bcm_agent.py" in text


# ── pairing ──────────────────────────────────────────────────────────────

class TestPairing:
    def test_unpaired_agent_answers_nothing_but_pairing(self, state_dir, runner, clock):
        agent = make_agent(state_dir, runner, clock)
        status, data, hdrs = agent.handle("GET", "/v1/health", {}, b"")
        assert status == 403 and json.loads(data)["error"] == "unpaired"
        assert "X-BCM-Sig" not in hdrs
        assert runner.calls == []

    def test_refused_without_the_pairing_file(self, state_dir, runner, clock):
        agent = make_agent(state_dir, runner, clock)
        status, out, hdrs, _d = pair_request(agent)
        assert status == 403 and out["error"] == "pairing_closed"
        assert not Path(state_dir, "secret").exists() and not agent.paired

    def test_pairing_stores_the_secret_privately_and_removes_the_file(self, state_dir, runner,
                                                                      clock):
        agent = make_agent(state_dir, runner, clock)
        status, out, hdrs, data = pair(agent, state_dir, nonce=77)
        assert status == 200 and out["paired"] is True
        # the answer proves the agent holds exactly this secret
        assert hdrs["X-BCM-Sig"] == A.sign(KEY, A.response_message(200, 77, data))
        assert not Path(state_dir, "PAIRING").exists()
        assert stat.S_IMODE(os.stat(state_dir).st_mode) == 0o700
        assert stat.S_IMODE(os.stat(Path(state_dir, "secret")).st_mode) == 0o600
        assert Path(state_dir, "secret").read_text() == SECRET
        # a second attempt (even with the old code) without a new PAIRING file
        clock.advance(10)
        status, _out, _h, _d = pair_request(agent, OTHER, 78)
        assert status == 403 and Path(state_dir, "secret").read_text() == SECRET

    def test_pairing_again_with_a_new_pairing_file(self, state_dir, runner, clock):
        agent = make_agent(state_dir, runner, clock)
        pair(agent, state_dir)
        clock.advance(10)
        status, _out, _h, _d = pair(agent, state_dir, secret=OTHER, nonce=5, code="9876543210")
        assert status == 200 and Path(state_dir, "secret").read_text() == OTHER
        assert Peer(agent, clock, key=bytes.fromhex(OTHER)).req("GET", "/v1/health")[0] == 200
        status, out, hdrs, _n, _d = Peer(agent, clock).raw("GET", "/v1/health")
        assert status == 401 and "X-BCM-Sig" not in hdrs

    @pytest.mark.parametrize("secret", ["ab" * 31, "zz" * 32, "ab" * 32 + "a", 123, None])
    def test_bad_secret_is_refused(self, state_dir, runner, clock, secret):
        agent = make_agent(state_dir, runner, clock)
        Path(state_dir, "PAIRING").write_text(CODE)
        status, out, _h, _d = pair_request(agent, secret)
        assert status == 400 and out["error"] == "bad_secret" and not agent.paired
        assert Path(state_dir, "PAIRING").exists()

    def test_a_third_party_without_the_code_cannot_pair(self, state_dir, runner, clock):
        """The race the code exists for: any local process (an Android app,
        the kiosk user on the head unit) polls and fires first."""
        agent = make_agent(state_dir, runner, clock)
        Path(state_dir, "PAIRING").write_text(CODE)
        status, out, hdrs, _d = pair_request(agent, OTHER, code="1111111111")
        assert status == 401 and out["error"] == "bad_code" and "X-BCM-Sig" not in hdrs
        assert not agent.paired and not Path(state_dir, "secret").exists()
        assert Path(state_dir, "PAIRING").exists()          # BCM can still pair
        clock.advance(A.PAIR_MIN_INTERVAL_S)
        assert pair_request(agent)[0] == 200
        assert Path(state_dir, "secret").read_text() == SECRET

    def test_five_wrong_codes_close_pairing(self, state_dir, runner, clock, caplog):
        agent = make_agent(state_dir, runner, clock)
        Path(state_dir, "PAIRING").write_text(CODE)
        with caplog.at_level(logging.WARNING, logger="bcm_agent"):
            for i in range(A.PAIR_MAX_FAILS):
                status, out, _h, _d = pair_request(agent, code=f"{i:010d}" if i else "5555555555")
                clock.advance(A.PAIR_MIN_INTERVAL_S)
        assert status == 403 and out["error"] == "pairing_closed"
        assert not Path(state_dir, "PAIRING").exists()
        assert pair_request(agent)[0] == 403               # the right code is too late
        assert any("wrong codes" in r.getMessage() for r in caplog.records)
        assert not any(CODE in r.getMessage() for r in caplog.records)

    def test_stale_timestamp_and_junk_do_not_use_the_limit(self, state_dir, runner, clock):
        agent = make_agent(state_dir, runner, clock)
        Path(state_dir, "PAIRING").write_text(CODE)
        body = json.dumps({"secret": SECRET}).encode()
        # junk (no headers, bad body) is refused before the limiter
        for _ in range(5):
            assert agent.handle("POST", "/v1/pair", {}, body)[0] == 400
            assert pair_request(agent, body=b"x")[0] == 400
        status, out, _h, _d = pair_request(agent, ts=int(clock.wall) - A.TS_WINDOW_S - 5)
        assert status == 401 and out["error"] == "stale_ts"
        assert pair_request(agent)[0] == 429                # well-formed attempts are limited
        clock.advance(A.PAIR_MIN_INTERVAL_S)
        assert pair_request(agent)[0] == 200

    def test_unauthenticated_answers_say_nothing_about_pairing(self, state_dir, runner, clock):
        agent = make_agent(state_dir, runner, clock)
        Path(state_dir, "PAIRING").write_text(CODE)
        for method, path, body in (("GET", "/v1/health", b""), ("POST", "/v1/pair", b"{}")):
            _s, data, _h = agent.handle(method, path, {}, body)
            out = json.loads(data)
            assert "pairing" not in out and "paired" not in out, out
        pair(agent, state_dir)
        _s, out, _h, _n, _d = Peer(agent, clock, key=bytes.fromhex(OTHER)).raw("GET", "/v1/health")
        assert set(out) == {"error", "version", "time"}

    def test_an_empty_pairing_file_gets_a_code(self, state_dir, runner, clock):
        agent = make_agent(state_dir, runner, clock)
        Path(state_dir, "PAIRING").touch()                  # the old "touch" way
        code = agent.pairing_code()
        assert A.PAIR_CODE_RE.fullmatch(code)
        assert Path(state_dir, "PAIRING").read_text().strip() == code
        assert stat.S_IMODE(os.stat(Path(state_dir, "PAIRING")).st_mode) == 0o600
        assert agent.pairing_code() == code                 # stable until used
        assert pair(agent, state_dir, code=code)[0] == 200

    def test_pair_command_line(self, state_dir, capsys):
        assert A.main(["--state-dir", state_dir, "--pair"]) == 0
        code = Path(state_dir, "PAIRING").read_text().strip()
        assert A.PAIR_CODE_RE.fullmatch(code)
        assert stat.S_IMODE(os.stat(Path(state_dir, "PAIRING")).st_mode) == 0o600
        out = capsys.readouterr().out
        assert code in out and all(ord(ch) < 128 for ch in out)
        assert not Path(state_dir, A.LOG_FILE).exists()     # no server, no log
        assert A.main(["--state-dir", state_dir, "--pair"]) == 0     # a fresh one
        assert A.PAIR_CODE_RE.fullmatch(Path(state_dir, "PAIRING").read_text().strip())

    def test_repairing_never_lowers_the_replay_floor(self, state_dir, runner, clock):
        agent = make_agent(state_dir, runner, clock)
        pair(agent, state_dir, nonce=10)
        peer = Peer(agent, clock, nonce=5999)
        assert peer.req("GET", "/v1/health")[0] == 200       # nonce 6000
        recorded = peer.raw("GET", "/v1/health", nonce=10000)   # accepted, recorded
        assert recorded[0] == 200
        clock.advance(10)
        assert pair(agent, state_dir, nonce=5500, code="2222222222")[0] == 200   # same secret
        replay = peer.raw("GET", "/v1/health", nonce=6000)
        assert replay[0] == 409 and replay[1]["min_nonce"] == 10001
        assert Path(state_dir, "nonce").read_text() == "10000"

    def test_the_secret_and_code_are_never_logged(self, state_dir, runner, clock, caplog):
        with caplog.at_level(logging.DEBUG, logger="bcm_agent"):
            agent = make_agent(state_dir, runner, clock)
            Path(state_dir, "PAIRING").touch()
            code = agent.pairing_code()
            pair(agent, state_dir, code=code)
            Peer(agent, clock).req("GET", "/v1/health")
            Peer(agent, clock, key=bytes.fromhex(OTHER)).raw("GET", "/v1/health")
        assert caplog.records
        assert not any(SECRET in r.getMessage() or OTHER in r.getMessage()
                       or code in r.getMessage() for r in caplog.records)

    def test_stored_secret_survives_a_restart(self, state_dir, runner, clock):
        pair(make_agent(state_dir, runner, clock), state_dir)
        agent = make_agent(state_dir, runner, clock)
        assert agent.paired and Peer(agent, clock).req("GET", "/v1/health")[0] == 200


# ── HMAC ─────────────────────────────────────────────────────────────────

class TestAuth:
    def test_valid_request_and_signed_answer(self, ready):
        agent, peer = ready
        status, out = peer.req("GET", "/v1/health")
        assert status == 200 and out["paired"] is True and out["version"] == A.VERSION
        assert out["config_hash"] == A.config_hash(A.normalize_config(CONFIG)[0])

    def test_bad_signature(self, ready):
        agent, peer = ready
        status, out, hdrs, _n, _d = peer.raw("GET", "/v1/health", sig="0" * 64)
        assert status == 401 and out["error"] == "bad_auth" and "X-BCM-Sig" not in hdrs

    def test_wrong_key(self, ready, clock):
        agent, _peer = ready
        status, out, hdrs, _n, _d = Peer(agent, clock, key=bytes.fromhex(OTHER)).raw(
            "GET", "/v1/health")
        assert status == 401 and "X-BCM-Sig" not in hdrs

    @pytest.mark.parametrize("skew", [-61, 61, -3600])
    def test_old_or_future_timestamp(self, ready, clock, skew):
        agent, peer = ready
        status, out, hdrs, _n, _d = peer.raw("GET", "/v1/health", ts=int(clock.wall) + skew)
        assert status == 401 and out["error"] == "stale_ts" and "X-BCM-Sig" not in hdrs
        assert out["time"] == int(clock.wall)

    def test_timestamp_inside_the_window(self, ready, clock):
        _agent, peer = ready
        assert peer.raw("GET", "/v1/health", ts=int(clock.wall) - 60)[0] == 200

    def test_tampered_body_or_path(self, ready, clock):
        agent, peer = ready
        body = json.dumps(dict(CONFIG, recipients=[NUM1])).encode()
        good_for_other_body = A.sign(KEY, A.request_message("PUT", "/v1/config", int(clock.wall),
                                                            500, b'{"x":1}'))
        status, *_ = peer.raw("PUT", "/v1/config", body, nonce=500, sig=good_for_other_body)
        assert status == 401
        sig = A.sign(KEY, A.request_message("POST", "/v1/test", int(clock.wall), 501, b"{}"))
        status, *_ = peer.raw("POST", "/v1/crash", b"{}", nonce=501, sig=sig)
        assert status == 401

    def test_replayed_and_lower_nonce(self, ready):
        agent, peer = ready
        status, _out = peer.req("GET", "/v1/health", nonce=1000)
        assert status == 200
        for nonce in (1000, 999, 1):
            status, out = peer.req("GET", "/v1/health", nonce=nonce)
            # signed (the request itself was genuine) so BCM can resync
            assert status == 409 and out == {"error": "replay", "min_nonce": 1001}
        assert peer.req("GET", "/v1/health", nonce=1001)[0] == 200

    def test_nonce_is_persisted_before_the_request_runs(self, ready, state_dir):
        agent, peer = ready
        peer.req("GET", "/v1/health", nonce=4242)
        assert Path(state_dir, "nonce").read_text() == "4242"

    def test_replay_fails_after_an_agent_restart(self, ready, state_dir, runner, clock):
        agent, peer = ready
        body = b""
        ts = int(clock.wall)
        sig = A.sign(KEY, A.request_message("GET", "/v1/health", ts, 7000, body))
        hdrs = {"X-BCM-Ts": str(ts), "X-BCM-Nonce": "7000", "X-BCM-Sig": sig}
        assert agent.handle("GET", "/v1/health", hdrs, body)[0] == 200
        restarted = make_agent(state_dir, runner, clock)
        status, data, _h = restarted.handle("GET", "/v1/health", hdrs, body)
        assert status == 409 and json.loads(data)["error"] == "replay"

    @pytest.mark.parametrize("headers", [
        {}, {"X-BCM-Ts": "abc", "X-BCM-Nonce": "1", "X-BCM-Sig": "0" * 64},
        {"X-BCM-Ts": str(T0), "X-BCM-Nonce": "-1", "X-BCM-Sig": "0" * 64},
        {"X-BCM-Ts": str(T0), "X-BCM-Nonce": "1", "X-BCM-Sig": "0" * 63},
        {"X-BCM-Ts": str(T0), "X-BCM-Nonce": "1" * 20, "X-BCM-Sig": "0" * 64}])
    def test_malformed_headers(self, ready, headers):
        agent, _peer = ready
        status, data, hdrs = agent.handle("GET", "/v1/health", headers, b"")
        assert status == 401 and "X-BCM-Sig" not in hdrs

    def test_failed_auth_is_logged_rate_limited(self, ready, clock, caplog):
        _agent, peer = ready
        with caplog.at_level(logging.WARNING, logger="bcm_agent"):
            for _ in range(5):
                peer.raw("GET", "/v1/health", sig="0" * 64)
        assert len([r for r in caplog.records if "Unauthenticated" in r.getMessage()]) == 1

    def test_unknown_paths_and_methods(self, ready):
        agent, peer = ready
        assert agent.handle("GET", "/v1/nope", {}, b"")[0] == 404
        assert agent.handle("GET", "/v1/crash/XYZ", {}, b"")[0] == 404
        assert agent.handle("DELETE", "/v1/health", {}, b"")[0] == 405
        assert agent.handle("GET", "/v1/health?x=1", {}, b"")[0] == 404

    def test_get_with_a_body_and_bad_json(self, ready):
        _agent, peer = ready
        assert peer.raw("GET", "/v1/health", b"{}")[0] == 400
        status, out, *_ = peer.raw("PUT", "/v1/config", b"{not json")
        assert status == 400 and out["error"] == "bad_json"
        assert peer.raw("PUT", "/v1/config", b"[1,2]")[0] == 400
        assert peer.raw("PUT", "/v1/config", b'{"a":NaN}')[0] == 400
        assert peer.raw("PUT", "/v1/config", b'{"a":1,"a":2}')[0] == 400
        assert peer.raw("PUT", "/v1/config", b"[" * 4000 + b"]" * 4000)[0] == 400

    def test_body_limit(self, ready):
        agent, peer = ready
        big = json.dumps({"x": "a" * A.MAX_BODY}).encode()
        status, data, hdrs = agent.handle("PUT", "/v1/config", {}, big)
        assert status == 413 and "X-BCM-Sig" not in hdrs


# ── the HTTP server ──────────────────────────────────────────────────────

@pytest.fixture
def served(ready):
    agent, peer = ready
    server = A.make_server(agent, 0)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                              daemon=True)
    thread.start()
    yield agent, peer, server
    server.shutdown()
    server.server_close()


def _http(port, raw: bytes, timeout=5.0) -> bytes:
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as s:
        s.sendall(raw)
        chunks = []
        while True:
            try:
                chunk = s.recv(65536)
            except ConnectionResetError:
                break
            if not chunk:
                break
            chunks.append(chunk)
    return b"".join(chunks)


class TestServer:
    def test_binds_loopback_only(self, served):
        _agent, _peer, server = served
        assert server.server_address[0] == "127.0.0.1"
        import inspect
        assert list(inspect.signature(A.make_server).parameters) == ["agent", "port"]

    def test_oversized_body_is_refused_unread(self, served):
        _agent, _peer, server = served
        port = server.server_address[1]
        head = (f"PUT /v1/config HTTP/1.1\r\nHost: x\r\nContent-Length: {A.MAX_BODY + 1}\r\n"
                f"\r\n").encode()
        resp = _http(port, head)
        assert resp.startswith(b"HTTP/1.0 413")

    def test_chunked_and_bad_length_are_refused(self, served):
        _agent, _peer, server = served
        port = server.server_address[1]
        resp = _http(port, b"PUT /v1/config HTTP/1.1\r\nHost: x\r\nTransfer-Encoding: chunked"
                           b"\r\n\r\n0\r\n\r\n")
        assert resp.startswith(b"HTTP/1.0 411")
        resp = _http(port, b"PUT /v1/config HTTP/1.1\r\nHost: x\r\nContent-Length: -5\r\n\r\n")
        assert resp.startswith(b"HTTP/1.0 400")

    def test_signed_round_trip_over_http(self, served, clock):
        _agent, peer, server = served
        port = server.server_address[1]
        peer.nonce += 1
        ts = int(clock.wall)
        sig = A.sign(KEY, A.request_message("GET", "/v1/health", ts, peer.nonce, b""))
        resp = _http(port, (f"GET /v1/health HTTP/1.1\r\nHost: x\r\nX-BCM-Ts: {ts}\r\n"
                            f"X-BCM-Nonce: {peer.nonce}\r\nX-BCM-Sig: {sig}\r\n\r\n").encode())
        head, body = resp.split(b"\r\n\r\n", 1)
        assert head.startswith(b"HTTP/1.0 200")
        got = [line.split(b": ", 1)[1].decode() for line in head.split(b"\r\n")
               if line.lower().startswith(b"x-bcm-sig:")]
        assert got == [A.sign(KEY, A.response_message(200, peer.nonce, body))]

    def test_connection_cap(self, ready, monkeypatch):
        agent, _peer = ready
        monkeypatch.setattr(A.AgentHandler, "timeout", 3.0)
        server = A.AgentServer(("127.0.0.1", 0), agent, max_conn=1)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                                  daemon=True)
        thread.start()
        port = server.server_address[1]
        try:
            idle = socket.create_connection(("127.0.0.1", port), timeout=5)
            time.sleep(0.3)             # the idle connection holds the only slot
            t = time.monotonic()
            resp = _http(port, b"GET /v1/health HTTP/1.1\r\nHost: x\r\n\r\n")
            assert resp == b"" and time.monotonic() - t < 2.0
            idle.close()
            time.sleep(0.3)
            deadline = time.monotonic() + 5
            while True:
                resp = _http(port, b"GET /v1/health HTTP/1.1\r\nHost: x\r\n\r\n")
                if resp or time.monotonic() > deadline:
                    break
                time.sleep(0.1)
            assert resp.startswith(b"HTTP/1.0 401")          # served again
        finally:
            server.shutdown()
            server.server_close()


# ── config ───────────────────────────────────────────────────────────────

class TestConfig:
    def test_defaults_before_the_first_push(self, state_dir, runner, clock):
        agent = make_agent(state_dir, runner, clock)
        assert agent.config == {"recipients": [], "sim_slot": 0, "vehicle_label": "ALFA 156",
                                "toggles": dict.fromkeys(A.TOGGLES, False), "dry_run": True,
                                "follow_up_cancel": True}

    def test_put_is_persisted(self, ready, state_dir, runner, clock):
        agent, peer = ready
        restarted = make_agent(state_dir, runner, clock)
        assert restarted.config == A.normalize_config(CONFIG)[0]
        assert stat.S_IMODE(os.stat(Path(state_dir, "config.json")).st_mode) == 0o600

    @pytest.mark.parametrize("change", [
        {"recipients": ["601234567"]}, {"recipients": ["+48 601 234 567"]},
        {"recipients": [NUM1, NUM2, "+48601234569", "+48601234560"]},
        {"recipients": "+48601234567"}, {"recipients": ["+0601234567"]},
        {"sim_slot": 2}, {"sim_slot": True}, {"vehicle_label": "ŁÓDŹ 156"},
        {"vehicle_label": "A" * 21}, {"vehicle_label": "X;rm -rf"}, {"vehicle_label": ""},
        {"toggles": {"crash_sms": "yes"}}, {"dry_run": 1}, {"follow_up_cancel": None},
    ])
    def test_invalid_config_is_refused(self, ready, change):
        agent, peer = ready
        before = dict(agent.config)
        status, out = peer.req("PUT", "/v1/config", dict(CONFIG, **change))
        assert status == 400 and out["error"] == "bad_config"
        assert agent.config == before

    def test_missing_field_is_refused_unknown_ignored(self, ready):
        agent, peer = ready
        cfg = dict(CONFIG)
        del cfg["sim_slot"]
        assert peer.req("PUT", "/v1/config", cfg)[0] == 400
        status, out = peer.req("PUT", "/v1/config", dict(CONFIG, future_key=1,
                                                         toggles={"crash_sms": True, "x": 1}))
        assert status == 200
        assert agent.config["toggles"] == {"crash_sms": True, "parking_guard": False,
                                           "cabin_watch": False, "call112": False}


# ── crash events ─────────────────────────────────────────────────────────

def _texts_in_argv(runner):
    """Any argv word that carries SMS text (the texts all contain ': ')."""
    return [a for argv, _ in runner.calls for a in argv if ": " in a or "MOZLIWY" in a]


class TestCrash:
    def test_refused_while_crash_sms_is_off_or_without_recipients(self, ready):
        agent, peer = ready
        peer.req("PUT", "/v1/config", dict(CONFIG, toggles={"crash_sms": False}))
        assert peer.req("POST", "/v1/crash", CRASH) == (409, {"error": "crash_sms_off"})
        peer.req("PUT", "/v1/config", dict(CONFIG, recipients=[]))
        assert peer.req("POST", "/v1/crash", CRASH) == (409, {"error": "no_recipients"})

    @pytest.mark.parametrize("change", [
        {"event_id": "C0FFEE"}, {"event_id": "a" * 33}, {"event_id": "../x"},
        {"countdown_s": 14}, {"countdown_s": 121}, {"countdown_s": 45.0},
        {"lat": 91}, {"lat": None}, {"lon": "21.0"}, {"fix_age_s": -1},
        {"speed_kmh": 401}, {"dv_kmh": True}, {"event_ts": "now"}, {"dry_run": "no"},
    ])
    def test_invalid_crash_is_refused(self, ready, change, runner):
        _agent, peer = ready
        status, out = peer.req("POST", "/v1/crash", dict(CRASH, **change))
        assert status == 400 and out["error"] == "bad_request"
        assert runner.sms_calls() == []

    def test_armed_and_persisted_before_the_answer(self, ready, state_dir):
        agent, peer = ready
        status, out = peer.req("POST", "/v1/crash", CRASH)
        assert status == 200 and out["created"] is True and out["state"] == "armed"
        assert out["deadline_in_s"] == 45
        saved = json.loads(Path(state_dir, "events.json").read_text())
        assert [e["id"] for e in saved["events"]] == ["c0ffee01"]
        assert saved["events"][0]["state"] == "armed"

    def test_idempotent_by_event_id(self, ready, clock):
        agent, peer = ready
        peer.req("POST", "/v1/crash", CRASH)
        clock.advance(10)
        status, out = peer.req("POST", "/v1/crash", dict(CRASH, countdown_s=15))
        assert status == 200 and out["created"] is False
        assert out["deadline_in_s"] == 35 and out["countdown_s"] == 45
        assert len(agent.events) == 1

    def test_the_agent_holds_the_deadline(self, ready, runner, clock):
        agent, peer = ready
        peer.req("POST", "/v1/crash", CRASH)
        clock.advance(44)
        run_steps(agent)
        assert runner.sms_calls() == []
        assert peer.req("GET", "/v1/crash/c0ffee01")[1]["deadline_in_s"] == 1
        clock.advance(1)
        run_steps(agent)
        calls = runner.sms_calls()
        assert [argv for argv, _ in calls] == [["termux-sms-send", "-n", NUM1, "-s", "0"],
                                              ["termux-sms-send", "-n", NUM2, "-s", "0"]]
        text = calls[0][1]
        assert text.startswith("ALFA 156: MOZLIWY WYPADEK") and "52.22968,21.01223" in text
        out = peer.req("GET", "/v1/crash/c0ffee01")[1]
        assert out["state"] == "sending"
        assert [r["state"] for r in out["results"]] == ["submitted", "submitted"]
        clock.advance(A.VERIFY_AFTER_S)
        run_steps(agent)
        out = peer.req("GET", "/v1/crash/c0ffee01")[1]
        assert out["state"] == "sent"
        assert [(r["to"], r["state"], r["verified"]) for r in out["results"]] == [
            ("+48...567", "sent", True), ("+48...568", "sent", True)]
        assert peer.req("GET", "/v1/health")[1]["last_sent_ts"] == int(clock.wall)

    def test_text_and_recipients_never_in_argv(self, ready, runner, clock):
        agent, peer = ready
        peer.req("POST", "/v1/crash", CRASH)
        clock.advance(45)
        run_steps(agent)
        assert runner.sms_calls()
        assert _texts_in_argv(runner) == []
        for argv, _stdin in runner.calls:
            free = [a for a in argv if a not in ("termux-sms-send", "-n", "-s", "0", "1", "-t",
                                                 "all", "-l", str(A.SMS_LIST_LIMIT),
                                                 "termux-sms-list",
                                                 "termux-telephony-deviceinfo")]
            assert all(A.E164_RE.fullmatch(a) for a in free), argv

    def test_send_now(self, ready, runner, clock):
        agent, peer = ready
        peer.req("POST", "/v1/crash", CRASH)
        assert peer.req("POST", "/v1/crash/c0ffee01/send_now", {})[0] == 200
        run_steps(agent)
        assert len(runner.sms_calls()) == 2

    def test_unknown_event(self, ready):
        _agent, peer = ready
        assert peer.req("GET", "/v1/crash/abcd")[0] == 404
        assert peer.req("POST", "/v1/crash/abcd/cancel", {})[0] == 404

    def test_cancel_before_sending_sends_nothing(self, ready, runner, clock):
        agent, peer = ready
        peer.req("POST", "/v1/crash", CRASH)
        clock.advance(20)
        status, out = peer.req("POST", "/v1/crash/c0ffee01/cancel", {})
        assert status == 200 and out["state"] == "cancelled" and out["cancel_sms"] is None
        clock.advance(600)
        run_steps(agent)
        assert runner.sms_calls() == []

    def test_cancel_after_sending_sends_one_cancel_sms(self, ready, runner, clock):
        agent, peer = ready
        peer.req("POST", "/v1/crash", CRASH)
        clock.advance(45)
        run_steps(agent)
        clock.advance(A.VERIFY_AFTER_S)
        run_steps(agent)
        status, out = peer.req("POST", "/v1/crash/c0ffee01/cancel", {})
        assert status == 200 and out["cancel_sms"]["state"] == "sending"
        run_steps(agent)
        cancel_calls = runner.sms_calls()[2:]
        assert [argv[2] for argv, _ in cancel_calls] == [NUM1, NUM2]
        assert cancel_calls[0][1] == ("ALFA 156: ODWOLANE - kierowca potwierdzil, ze nic sie "
                                      "nie stalo (alarm z 02:13).")
        clock.advance(A.VERIFY_AFTER_S)
        run_steps(agent)
        assert peer.req("GET", "/v1/crash/c0ffee01")[1]["cancel_sms"]["state"] == "sent"
        # never a second one
        assert peer.req("POST", "/v1/crash/c0ffee01/cancel", {})[0] == 200
        clock.advance(600)
        run_steps(agent)
        assert len(runner.sms_calls()) == 4

    def test_no_cancel_sms_after_15_min_or_when_disabled(self, ready, runner, clock):
        agent, peer = ready
        peer.req("POST", "/v1/crash", CRASH)
        clock.advance(45)
        run_steps(agent)
        clock.advance(A.CANCEL_WINDOW_S + 1)
        run_steps(agent)
        peer.req("POST", "/v1/crash/c0ffee01/cancel", {})
        run_steps(agent)
        assert len(runner.sms_calls()) == 2
        # follow_up_cancel off: also nothing
        clock.advance(A.CRASH_COOLDOWN_S)
        peer.req("PUT", "/v1/config", dict(CONFIG, follow_up_cancel=False))
        peer.req("POST", "/v1/crash", dict(CRASH, event_id="beef"))
        clock.advance(45)
        run_steps(agent)
        peer.req("POST", "/v1/crash/beef/cancel", {})
        run_steps(agent)
        assert len(runner.sms_calls()) == 4

    def test_cancel_while_waiting_for_service_sends_nothing(self, ready, runner, clock):
        agent, peer = ready
        runner.sim = "absent"
        peer.req("POST", "/v1/crash", CRASH)
        clock.advance(45)
        run_steps(agent)
        assert runner.sms_calls() == []
        peer.req("POST", "/v1/crash/c0ffee01/cancel", {})
        clock.advance(A.SERVICE_WAIT_S + 10)
        run_steps(agent)
        assert runner.sms_calls() == []

    @pytest.mark.parametrize("during", ["termux-telephony-deviceinfo", "termux-sms-list"])
    def test_cancel_during_the_pre_send_checks_sends_nothing(self, ready, runner, clock, during):
        """The driver cancels while the agent is still checking the signal or
        the SMS boxes (each up to API_TIMEOUT_S): nothing may go out."""
        agent, peer = ready
        peer.req("POST", "/v1/crash", CRASH)
        clock.advance(45)
        fired = []

        def hook(argv):
            if argv[0] == during and not fired:
                fired.append(peer.req("POST", "/v1/crash/c0ffee01/cancel", {}))
        runner.hook = hook
        run_steps(agent)
        clock.advance(A.CANCEL_WINDOW_S)
        run_steps(agent)
        assert fired and fired[0][0] == 200
        assert runner.sms_calls() == []
        out = peer.req("GET", "/v1/crash/c0ffee01")[1]
        assert out["state"] == "cancelled" and out["cancel_sms"] is None
        assert [r["state"] for r in out["results"]] == ["skipped", "skipped"]

    def test_cancel_during_the_send_itself_gets_a_cancel_sms(self, ready, runner, clock):
        """termux-sms-send itself cannot be interrupted: that recipient gets
        exactly one cancel SMS, the others nothing."""
        agent, peer = ready
        peer.req("POST", "/v1/crash", CRASH)
        clock.advance(45)
        fired = []

        def hook(argv):
            if argv[0] == "termux-sms-send" and not fired:
                fired.append(peer.req("POST", "/v1/crash/c0ffee01/cancel", {}))
        runner.hook = hook
        run_steps(agent)
        texts = [(argv[2], stdin[:20]) for argv, stdin in runner.sms_calls()]
        assert texts == [(NUM1, "ALFA 156: MOZLIWY WY"), (NUM1, "ALFA 156: ODWOLANE -")]

    @pytest.mark.parametrize("during", ["termux-telephony-deviceinfo", "termux-sms-list"])
    def test_cancel_then_restart_never_sends_the_crash_sms(self, ready, runner, clock,
                                                           state_dir, during):
        """Cancel lands while recipient 1 is "sending", then Android kills
        Termux before termux-sms-send: the restarted agent must not send the
        alarm. Whether it went out is unknown, so that one recipient gets the
        cancel SMS (better a needless "ODWOLANE" than an alarm without it)."""
        agent, peer = ready
        peer.req("POST", "/v1/crash", CRASH)
        clock.advance(45)

        class Killed(BaseException):
            pass

        def hook(argv):
            if argv[0] == during:
                runner.hook = None
                peer.req("POST", "/v1/crash/c0ffee01/cancel", {})
                raise Killed()
        runner.hook = hook
        with pytest.raises(Killed):
            agent.step()
        saved = json.loads(Path(state_dir, "events.json").read_text())["events"][0]
        assert saved["crash"]["rcpt"][0]["st"] == "sending" and saved["crash"]["no_retry"]
        restarted = make_agent(state_dir, runner, clock)
        run_steps(restarted)
        clock.advance(A.VERIFY_AFTER_S)
        run_steps(restarted)
        texts = [(argv[2], stdin[:20]) for argv, stdin in runner.sms_calls()]
        assert texts == [(NUM1, "ALFA 156: ODWOLANE -")]
        out = Peer(restarted, clock, nonce=peer.nonce).req("GET", "/v1/crash/c0ffee01")[1]
        assert out["state"] == "cancelled"
        assert [r["state"] for r in out["results"]] == ["failed", "skipped"]
        assert out["cancel_sms"]["state"] == "sent"
        again = make_agent(state_dir, runner, clock)          # and never twice
        run_steps(again)
        assert len(runner.sms_calls()) == 1

    def test_cancel_then_restart_without_follow_up(self, ready, runner, clock, state_dir):
        agent, peer = ready
        peer.req("PUT", "/v1/config", dict(CONFIG, follow_up_cancel=False))
        peer.req("POST", "/v1/crash", CRASH)
        clock.advance(45)

        class Killed(BaseException):
            pass

        def hook(argv):
            if argv[0] == "termux-sms-list":
                runner.hook = None
                peer.req("POST", "/v1/crash/c0ffee01/cancel", {})
                raise Killed()
        runner.hook = hook
        with pytest.raises(Killed):
            agent.step()
        run_steps(make_agent(state_dir, runner, clock))
        assert runner.sms_calls() == []

    def test_waits_for_service_then_sends_anyway(self, ready, runner, clock):
        agent, peer = ready
        runner.operator = ""
        peer.req("POST", "/v1/crash", CRASH)
        clock.advance(45)
        for _ in range(int(A.SERVICE_WAIT_S // A.SERVICE_POLL_S) - 1):
            run_steps(agent)
            clock.advance(A.SERVICE_POLL_S)
        assert runner.sms_calls() == []
        clock.advance(A.SERVICE_POLL_S)
        run_steps(agent)
        assert len(runner.sms_calls()) == 2

    def test_retries_then_partial(self, ready, runner, clock):
        agent, peer = ready
        peer.req("POST", "/v1/crash", CRASH)
        runner.send_rc, runner.send_err = 1, "Error: generic failure"
        clock.advance(45)
        run_steps(agent)
        for delay in A.RETRY_DELAYS_S:
            out = peer.req("GET", "/v1/crash/c0ffee01")[1]
            assert {r["state"] for r in out["results"]} == {"retry"}
            clock.advance(delay)
            run_steps(agent)
        out = peer.req("GET", "/v1/crash/c0ffee01")[1]
        assert out["state"] == "failed"
        assert [r["tries"] for r in out["results"]] == [4, 4]
        assert len(runner.sms_calls()) == 8

    def _states(self, peer):
        out = peer.req("GET", "/v1/crash/c0ffee01")[1]
        return out["state"], [(r["state"], r["tries"], r["verified"]) for r in out["results"]]

    def test_never_in_any_box_is_not_resent(self, ready, runner, clock):
        """Neither "sent" nor "failed": still in flight — no blind resend,
        "sent, unverified" after the window."""
        agent, peer = ready
        runner.record_sent = False
        peer.req("POST", "/v1/crash", CRASH)
        clock.advance(45)
        run_steps(agent)
        t = 0.0
        while t < A.VERIFY_WINDOW_S - A.VERIFY_AFTER_S:
            clock.advance(A.VERIFY_AFTER_S)
            t += A.VERIFY_AFTER_S
            run_steps(agent)
            assert self._states(peer)[1] == [("submitted", 1, None)] * 2, t
        clock.advance(A.VERIFY_AFTER_S)
        run_steps(agent)
        assert self._states(peer) == ("sent", [("sent", 1, None)] * 2)
        assert len(runner.sms_calls()) == 2

    @pytest.mark.parametrize("delay", [29, 31, 45, 65, 200])
    def test_late_landing_is_not_a_duplicate(self, ready, runner, clock, delay):
        """Weak signal, a 2-part SMS: Android writes it to the provider late."""
        agent, peer = ready
        runner.land_after = delay
        peer.req("POST", "/v1/crash", CRASH)
        clock.advance(45)
        run_steps(agent)
        for _ in range(12):
            clock.advance(A.VERIFY_AFTER_S)
            run_steps(agent)
        assert self._states(peer) == ("sent", [("sent", 1, True)] * 2)
        assert len(runner.sms_calls()) == 2

    def test_failed_box_is_retried(self, ready, runner, clock):
        agent, peer = ready
        runner.land_as = "failed"
        peer.req("POST", "/v1/crash", CRASH)
        clock.advance(45)
        run_steps(agent)
        clock.advance(A.VERIFY_AFTER_S)
        run_steps(agent)
        assert self._states(peer)[1] == [("retry", 1, None)] * 2
        runner.land_as = "sent"
        clock.advance(A.RETRY_DELAYS_S[0])
        run_steps(agent)
        clock.advance(A.VERIFY_AFTER_S)
        run_steps(agent)
        assert self._states(peer) == ("sent", [("sent", 2, True)] * 2)
        assert len(runner.sms_calls()) == 4

    def test_an_earlier_copy_landing_before_the_retry_is_not_resent(self, ready, runner,
                                                                    clock):
        agent, peer = ready
        peer.req("POST", "/v1/crash", CRASH)
        runner.send_rc, runner.send_err = A.RC_TIMEOUT, "termux-sms-send timed out"
        runner.record_on_error, runner.land_after = True, 20
        clock.advance(45)
        run_steps(agent)
        assert self._states(peer)[1] == [("retry", 1, None)] * 2
        runner.send_rc = 0
        clock.advance(A.RETRY_DELAYS_S[0])
        run_steps(agent)
        assert self._states(peer) == ("sent", [("sent", 1, True)] * 2)
        assert len(runner.sms_calls()) == 2

    def test_old_termux_api_without_type_is_unverified(self, ready, runner, clock):
        agent, peer = ready
        runner.typed = False
        peer.req("POST", "/v1/crash", CRASH)
        clock.advance(45)
        run_steps(agent)
        clock.advance(A.VERIFY_AFTER_S)
        run_steps(agent)
        assert self._states(peer) == ("sent", [("sent", 1, None)] * 2)
        assert len(runner.sms_calls()) == 2

    def test_cancel_reaches_everyone_the_alarm_may_have_reached(self, ready, runner, clock):
        """Handed to Android, then reported failed and waiting for a retry:
        it may still have gone out, so the cancel SMS goes there too."""
        agent, peer = ready
        runner.land_as = "failed"
        peer.req("POST", "/v1/crash", CRASH)
        clock.advance(45)
        run_steps(agent)
        clock.advance(A.VERIFY_AFTER_S)
        run_steps(agent)
        assert self._states(peer)[1] == [("retry", 1, None)] * 2
        runner.land_as = "sent"
        out = peer.req("POST", "/v1/crash/c0ffee01/cancel", {})[1]
        assert out["cancel_sms"] is not None
        clock.advance(A.RETRY_DELAYS_S[-1])
        run_steps(agent)
        texts = [(argv[2], stdin[:20]) for argv, stdin in runner.sms_calls()]
        assert texts.count((NUM1, "ALFA 156: MOZLIWY WY")) == 1     # never resent
        assert (NUM1, "ALFA 156: ODWOLANE -") in texts and (NUM2, "ALFA 156: ODWOLANE -") in texts

    def test_unreadable_sent_box_counts_as_sent_unverified(self, ready, runner, clock):
        agent, peer = ready
        runner.list_ok = False
        peer.req("POST", "/v1/crash", CRASH)
        clock.advance(45)
        run_steps(agent)
        clock.advance(A.VERIFY_AFTER_S)
        run_steps(agent)
        out = peer.req("GET", "/v1/crash/c0ffee01")[1]
        assert out["state"] == "sent" and {r["verified"] for r in out["results"]} == {None}

    def test_one_recipient_failing_is_partial(self, ready, runner, clock):
        agent, peer = ready
        peer.req("POST", "/v1/crash", CRASH)
        clock.advance(45)
        orig = runner.__call__

        def flaky(argv, stdin, timeout):
            if argv[0] == "termux-sms-send" and argv[2] == NUM2:
                runner.calls.append((list(argv), stdin))
                return 1, "", "Error: no service"
            return orig(argv, stdin, timeout)
        agent.phone._run = flaky
        for _ in range(12):
            run_steps(agent)
            clock.advance(130)
        assert peer.req("GET", "/v1/crash/c0ffee01")[1]["state"] == "partial"


class TestDryRun:
    def test_config_dry_run_never_calls_sms_send(self, ready, runner, clock, caplog):
        agent, peer = ready
        peer.req("PUT", "/v1/config", dict(CONFIG, dry_run=True))
        peer.req("POST", "/v1/crash", CRASH)
        clock.advance(45)
        with caplog.at_level(logging.WARNING, logger="bcm_agent"):
            run_steps(agent)
        out = peer.req("GET", "/v1/crash/c0ffee01")[1]
        assert out["state"] == "sent" and out["dry_run"] is True
        assert {r["state"] for r in out["results"]} == {"sent_dry"}
        assert runner.sms_calls() == []
        assert any("DRY RUN" in r.getMessage() and "MOZLIWY WYPADEK" in r.getMessage()
                   for r in caplog.records)
        assert peer.req("GET", "/v1/health")[1]["last_sent_ts"] is None

    def test_request_dry_run(self, ready, runner, clock):
        agent, peer = ready
        peer.req("POST", "/v1/crash", dict(CRASH, dry_run=True))
        clock.advance(45)
        run_steps(agent)
        assert runner.sms_calls() == []

    def test_dry_run_switched_on_during_the_countdown_wins(self, ready, runner, clock):
        agent, peer = ready
        peer.req("POST", "/v1/crash", CRASH)
        clock.advance(20)
        peer.req("PUT", "/v1/config", dict(CONFIG, dry_run=True))
        clock.advance(25)
        run_steps(agent)
        assert runner.sms_calls() == []

    def test_dry_cancel_sms_is_dry_too(self, ready, runner, clock):
        agent, peer = ready
        peer.req("PUT", "/v1/config", dict(CONFIG, dry_run=True))
        peer.req("POST", "/v1/crash", CRASH)
        clock.advance(45)
        run_steps(agent)
        out = peer.req("POST", "/v1/crash/c0ffee01/cancel", {})[1]
        run_steps(agent)
        out = peer.req("GET", "/v1/crash/c0ffee01")[1]
        assert out["cancel_sms"]["state"] == "sent"
        assert runner.sms_calls() == []


class TestLimits:
    def _fire(self, agent, peer, clock, eid):
        status, out = peer.req("POST", "/v1/crash", dict(CRASH, event_id=eid, countdown_s=15))
        if status == 200:
            clock.advance(15)
            run_steps(agent)
            clock.advance(A.VERIFY_AFTER_S)
            run_steps(agent)
        return status, out

    def test_one_per_ten_minutes_and_three_per_day(self, ready, clock, state_dir, runner):
        agent, peer = ready
        assert self._fire(agent, peer, clock, "a1")[0] == 200
        status, out = self._fire(agent, peer, clock, "a2")
        assert status == 429 and out["error"] == "rate_limited"
        assert 0 < out["retry_after"] <= A.CRASH_COOLDOWN_S
        clock.advance(A.CRASH_COOLDOWN_S)
        assert self._fire(agent, peer, clock, "a3")[0] == 200
        clock.advance(A.CRASH_COOLDOWN_S)
        assert self._fire(agent, peer, clock, "a4")[0] == 200
        clock.advance(A.CRASH_COOLDOWN_S)
        status, out = self._fire(agent, peer, clock, "a5")
        assert status == 429 and out["retry_after"] > A.CRASH_COOLDOWN_S
        # persisted: a restarted agent still refuses
        restarted = make_agent(state_dir, runner, clock)
        status, out = Peer(restarted, clock, nonce=peer.nonce).req(
            "POST", "/v1/crash", dict(CRASH, event_id="a6"))
        assert status == 429
        clock.advance(A.DAY_S)
        assert Peer(restarted, clock, nonce=peer.nonce + 10).req(
            "POST", "/v1/crash", dict(CRASH, event_id="a7"))[0] == 200

    def test_cancelled_before_sending_does_not_count(self, ready, clock):
        agent, peer = ready
        peer.req("POST", "/v1/crash", dict(CRASH, event_id="b1"))
        clock.advance(5)
        peer.req("POST", "/v1/crash/b1/cancel", {})
        assert peer.req("POST", "/v1/crash", dict(CRASH, event_id="b2"))[0] == 200

    def test_an_active_event_blocks_a_second_one(self, ready, clock):
        _agent, peer = ready
        peer.req("POST", "/v1/crash", dict(CRASH, event_id="d1"))
        assert peer.req("POST", "/v1/crash", dict(CRASH, event_id="d2"))[0] == 429


class TestDryLimits:
    """A dry-run event sends nothing, so it never limits a real one."""

    def _fire(self, peer, clock, agent, eid, **extra):
        status, out = peer.req("POST", "/v1/crash",
                               dict(CRASH, event_id=eid, countdown_s=15, **extra))
        if status == 200:
            clock.advance(15)
            run_steps(agent)
            clock.advance(A.VERIFY_AFTER_S)
            run_steps(agent)
        return status, out

    def test_three_dry_events_do_not_block_a_real_one(self, ready, runner, clock):
        agent, peer = ready
        peer.req("PUT", "/v1/config", dict(CONFIG, dry_run=True))
        for eid in ("d1", "d2", "d3"):
            assert self._fire(peer, clock, agent, eid)[0] == 200
            clock.advance(A.CRASH_COOLDOWN_S)
        assert runner.sms_calls() == []
        peer.req("PUT", "/v1/config", CONFIG)
        assert self._fire(peer, clock, agent, "e1")[0] == 200
        assert len(runner.sms_calls()) == 2

    def test_request_dry_event_then_a_real_one_at_once(self, ready, runner, clock):
        agent, peer = ready
        assert self._fire(peer, clock, agent, "d1", dry_run=True)[0] == 200
        assert self._fire(peer, clock, agent, "e1")[0] == 200

    def test_dry_events_still_limit_dry_events(self, ready, clock):
        agent, peer = ready
        peer.req("PUT", "/v1/config", dict(CONFIG, dry_run=True))
        assert self._fire(peer, clock, agent, "d1")[0] == 200
        status, out = self._fire(peer, clock, agent, "d2")
        assert status == 429 and out["error"] == "rate_limited"

    def test_an_armed_dry_event_blocks_a_second_one(self, ready, clock):
        _agent, peer = ready
        assert peer.req("POST", "/v1/crash", dict(CRASH, event_id="d1", dry_run=True))[0] == 200
        assert peer.req("POST", "/v1/crash", dict(CRASH, event_id="e1"))[0] == 429

    def test_a_real_event_still_limits_a_dry_one(self, ready, clock):
        agent, peer = ready
        assert self._fire(peer, clock, agent, "e1")[0] == 200
        assert self._fire(peer, clock, agent, "d1", dry_run=True)[0] == 429

    def test_many_cancelled_false_alarms_never_fill_the_store(self, ready, clock):
        agent, peer = ready
        for i in range(A.MAX_EVENTS):
            assert peer.req("POST", "/v1/crash", dict(CRASH, event_id=f"f{i:02x}"))[0] == 200
            peer.req("POST", f"/v1/crash/f{i:02x}/cancel", {})
            clock.advance(1)
        assert len(agent.events) == A.MAX_EVENTS
        status, out = peer.req("POST", "/v1/crash", dict(CRASH, event_id="beef"))
        assert status == 200, out
        assert len(agent.events) == A.MAX_EVENTS


class TestResume:
    def test_countdown_continues_after_a_restart(self, ready, state_dir, runner, clock):
        agent, peer = ready
        peer.req("POST", "/v1/crash", CRASH)
        clock.advance(30)
        clock.boot = 5.0                      # the phone rebooted: BOOTTIME restarted
        restarted = make_agent(state_dir, runner, clock)
        rp = Peer(restarted, clock, nonce=peer.nonce)
        assert rp.req("GET", "/v1/crash/c0ffee01")[1]["deadline_in_s"] == 15
        clock.advance(14)
        run_steps(restarted)
        assert runner.sms_calls() == []
        clock.advance(1)
        run_steps(restarted)
        assert len(runner.sms_calls()) == 2

    def test_missed_deadline_is_sent_at_once_if_recent(self, ready, state_dir, runner, clock):
        agent, peer = ready
        peer.req("POST", "/v1/crash", CRASH)
        clock.advance(45 + 600)               # agent was down across the deadline
        restarted = make_agent(state_dir, runner, clock)
        run_steps(restarted)
        assert len(runner.sms_calls()) == 2

    def test_old_missed_deadline_expires(self, ready, state_dir, runner, clock):
        agent, peer = ready
        peer.req("POST", "/v1/crash", CRASH)
        clock.advance(45 + A.RESUME_MAX_LATE_S + 1)
        restarted = make_agent(state_dir, runner, clock)
        run_steps(restarted)
        assert runner.sms_calls() == []
        out = Peer(restarted, clock, nonce=peer.nonce).req("GET", "/v1/crash/c0ffee01")[1]
        assert out["state"] == "failed" and out["error"] == "expired"

    def test_interrupted_sending_resumes(self, ready, state_dir, runner, clock):
        agent, peer = ready
        peer.req("POST", "/v1/crash", CRASH)
        clock.advance(45)
        agent.step()                          # first recipient handed over
        assert len(runner.sms_calls()) == 1
        restarted = make_agent(state_dir, runner, clock)
        run_steps(restarted)
        assert [argv[2] for argv, _ in runner.sms_calls()] == [NUM1, NUM2]
        clock.advance(A.VERIFY_AFTER_S)
        run_steps(restarted)
        out = Peer(restarted, clock, nonce=peer.nonce).req("GET", "/v1/crash/c0ffee01")[1]
        assert out["state"] == "sent"

    def test_damaged_records_are_skipped(self, state_dir, runner, clock):
        os.makedirs(state_dir, mode=0o700)
        good = {"id": "aa", "state": "sent", "dry": False, "countdown_s": 45,
                "created_wall": T0, "deadline_wall": T0 + 45, "event_ts": T0,
                "crash": {"kind": "crash", "text": "x", "dry": False, "slot": 0,
                          "created_wall": T0, "out_wall": T0,
                          "rcpt": [{"num": NUM1, "st": "sent", "tries": 1, "err": ""}]}}
        bad = [dict(good, id="BB"), dict(good, id="cc", crash={"rcpt": "x"}),
               dict(good, id="dd", crash=dict(good["crash"], rcpt=[{"num": "x; reboot",
                                                                    "st": "queued",
                                                                    "tries": 0}])), 5]
        Path(state_dir, "events.json").write_text(json.dumps({"events": [good, *bad]}))
        agent = make_agent(state_dir, runner, clock)
        assert [e["id"] for e in agent.events] == ["aa"]
        assert agent.step() > 0               # no crash in the scheduler


class TestTestSms:
    def test_test_sms(self, ready, runner, clock, state_dir):
        agent, peer = ready
        status, out = peer.req("POST", "/v1/test", {})
        assert status == 200 and out["dry_run"] is False
        run_steps(agent)
        assert [stdin for _argv, stdin in runner.sms_calls()] == [
            "ALFA 156: TEST powiadomien o wypadku. Nic sie nie stalo, nie reaguj."] * 2
        status, out = peer.req("POST", "/v1/test", {})
        assert status == 429 and 0 < out["retry_after"] <= A.TEST_COOLDOWN_S
        restarted = make_agent(state_dir, runner, clock)
        assert Peer(restarted, clock, nonce=peer.nonce).req("POST", "/v1/test", {})[0] == 429
        clock.advance(A.VERIFY_AFTER_S)
        run_steps(agent)
        assert peer.req("GET", "/v1/health")[1]["last_test"]["state"] == "sent"

    def test_dry_by_config_unless_the_request_says_otherwise(self, ready, runner, clock):
        agent, peer = ready
        peer.req("PUT", "/v1/config", dict(CONFIG, dry_run=True))
        assert peer.req("POST", "/v1/test", {})[1]["dry_run"] is True
        run_steps(agent)
        assert runner.sms_calls() == []
        clock.advance(A.TEST_COOLDOWN_S)
        # dry_run:false never bypasses the config — only an explicit real_test
        assert peer.req("POST", "/v1/test", {"dry_run": False})[0] == 400
        assert peer.req("POST", "/v1/test", {"dry_run": True, "real_test": True})[0] == 400
        assert peer.req("POST", "/v1/test", {"real_test": "yes"})[0] == 400
        assert runner.sms_calls() == []
        assert peer.req("POST", "/v1/test", {"real_test": True})[1]["dry_run"] is False
        run_steps(agent)
        assert len(runner.sms_calls()) == 2
        clock.advance(A.TEST_COOLDOWN_S)
        assert peer.req("POST", "/v1/test", {"dry_run": True})[1]["dry_run"] is True

    def test_verified_test_is_reported(self, ready, runner, clock):
        agent, peer = ready
        assert peer.req("GET", "/v1/health")[1]["last_verified_test_ts"] is None
        peer.req("POST", "/v1/test", {})
        run_steps(agent)
        clock.advance(A.VERIFY_AFTER_S)
        run_steps(agent)
        out = peer.req("GET", "/v1/health")[1]
        assert out["last_test"]["state"] == "sent" and out["last_test"]["verified"] is True
        assert out["last_verified_test_ts"] == int(clock.wall)

    def test_unverified_or_dry_test_is_not_verified(self, ready, runner, clock):
        agent, peer = ready
        runner.list_ok = False
        peer.req("POST", "/v1/test", {})
        run_steps(agent)
        clock.advance(A.VERIFY_AFTER_S)
        run_steps(agent)
        out = peer.req("GET", "/v1/health")[1]
        assert out["last_test"]["state"] == "sent" and out["last_test"]["verified"] is False
        assert out["last_verified_test_ts"] is None
        clock.advance(A.TEST_COOLDOWN_S)
        peer.req("POST", "/v1/test", {"dry_run": True})
        run_steps(agent)
        out = peer.req("GET", "/v1/health")[1]
        assert out["last_test"]["verified"] is False and out["last_verified_test_ts"] is None

    def test_needs_recipients(self, ready):
        _agent, peer = ready
        peer.req("PUT", "/v1/config", dict(CONFIG, recipients=[]))
        assert peer.req("POST", "/v1/test", {}) == (409, {"error": "no_recipients"})


# ── texts ────────────────────────────────────────────────────────────────

PLAN_TEXT = ("ALFA 156: MOZLIWY WYPADEK 12.11.2026 14:03. Pozycja: "
             "https://maps.google.com/?q=52.22968,21.01223 (GPS sprzed 4 s). Predkosc przed: "
             "72 km/h, zmiana ok. 45 km/h. Wiadomosc automatyczna, NIE jest to zgloszenie na "
             "112. Zadzwon do kierowcy; jesli nie odbiera, dzwon 112 i podaj pozycje.")
EVENT_1403 = calendar.timegm((2026, 11, 12, 14, 3, 0))


def _gsm7_segments(text):
    return 1 if len(text) <= 160 else -(-len(text) // 153)


class TestTexts:
    def test_crash_text_is_the_plans_template(self):
        assert A.crash_text("ALFA 156", EVENT_1403, 52.22968, 21.01223, 4, 72, 45,
                            time.gmtime) == PLAN_TEXT

    def test_cancel_and_test_texts(self):
        assert A.cancel_text("ALFA 156", EVENT_1403, time.gmtime) == (
            "ALFA 156: ODWOLANE - kierowca potwierdzil, ze nic sie nie stalo (alarm z 14:03).")
        assert A.test_text("ALFA 156") == (
            "ALFA 156: TEST powiadomien o wypadku. Nic sie nie stalo, nie reaguj.")

    @pytest.mark.parametrize("label", ["ALFA 156", "A" * 20, "Alfa 156 GTA-2.5 v6."[:20]])
    @pytest.mark.parametrize("args", [
        (52.22968, 21.01223, 4, 72, 45),
        (-89.999999, -179.999999, 7199, 400, 400),   # the longest numbers allowed
        (-89.99999, -179.99999, 86400, 399.6, 399.6),
        (None, None, None, None, None),
        (0.0, 0.0, None, 0, None),
    ])
    def test_every_text_is_gsm7_and_at_most_two_segments(self, label, args):
        texts = [A.crash_text(label, EVENT_1403, *args, localtime=time.gmtime),
                 A.cancel_text(label, EVENT_1403, time.gmtime), A.test_text(label)]
        for text in texts:
            bad = sorted({ch for ch in text if ch not in GSM7})
            assert not bad, (bad, text)
            assert A.is_gsm7(text)
            assert _gsm7_segments(text) <= 2, (len(text), text)
            assert A.sms_segments(text) == _gsm7_segments(text)

    def test_no_polish_letters_or_en_dash_in_the_templates(self):
        src = AGENT_PATH.read_text(encoding="utf-8")
        body = src[src.index("def crash_text"):src.index("# ── polecenia w telefonie")]
        literals = [n.value for n in ast.walk(ast.parse(body)) if isinstance(n, ast.Constant)
                    and isinstance(n.value, str) and ":" in n.value]
        for lit in literals:
            if "WYPADEK" in lit or "ODWOLANE" in lit or "TEST" in lit or "Predkosc" in lit:
                assert all(ch in GSM7 or ch in "{}" for ch in lit), lit


# ── status ───────────────────────────────────────────────────────────────

class TestStatus:
    def test_health_reports_cached_battery_and_sim(self, ready, runner):
        agent, peer = ready
        out = peer.req("GET", "/v1/health")[1]
        assert out["battery"] is None and out["sim_ready"] is None
        agent.refresh_status()
        out = peer.req("GET", "/v1/health")[1]
        assert out["battery"] == {"pct": 81, "temp_c": 30.4, "plugged": "PLUGGED_USB",
                                  "status": "CHARGING"}
        assert out["sim_ready"] is True
        n = len(runner.calls)
        peer.req("GET", "/v1/health")
        assert len(runner.calls) == n         # health never waits for Termux:API

    def test_missing_termux_api_is_unknown_not_an_error(self, ready, runner):
        agent, peer = ready

        def missing(argv, stdin, timeout):
            return 127, "", "not installed"
        agent.phone._run = missing
        agent.refresh_status()
        out = peer.req("GET", "/v1/health")[1]
        assert out["battery"] is None and out["sim_ready"] is None
        assert agent.phone.service_ok() is None

    @pytest.mark.parametrize("info, sim, service", [
        ({"error": "READ_PHONE_STATE permission"}, None, None),   # an error object
        ({"sim_state": 5}, None, None),
        ({"sim_state": "READY"}, True, None),                      # no operator field
        ({"sim_state": "ready", "network_operator": ""}, True, False),
        ({"sim_state": "absent", "network_operator": "26001"}, False, False),
        ({"sim_state": "ready", "network_operator": "26001"}, True, True),
    ])
    def test_missing_fields_are_unknown_not_no_sim(self, ready, info, sim, service):
        agent, _peer = ready

        def device(argv, stdin, timeout):
            return 0, json.dumps(info), ""
        agent.phone._run = device
        assert agent.phone.sim_ready() is sim
        assert agent.phone.service_ok() is service

    def test_unknown_service_does_not_delay_the_alarm(self, ready, runner, clock):
        agent, peer = ready
        runner.sim = None                    # sim_state: null — e.g. no permission
        peer.req("POST", "/v1/crash", CRASH)
        clock.advance(45)
        run_steps(agent)
        assert len(runner.sms_calls()) == 2

    def test_status_is_refreshed_only_while_someone_reads_health(self, ready, runner, clock):
        agent, peer = ready
        stop = threading.Event()
        before = len(runner.calls)
        thread = threading.Thread(target=agent.run_status, args=(stop,), daemon=True)
        thread.start()
        try:
            time.sleep(0.2)
            assert len(runner.calls) == before          # nobody asked: no Termux:API
            assert not agent.status_wanted()
            out = peer.req("GET", "/v1/health")[1]       # kicks the thread …
            assert out["battery"] is None                # … but never waits for it
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and agent._status_ts is None:
                time.sleep(0.02)
            assert peer.req("GET", "/v1/health")[1]["battery"]["pct"] == 81
            clock.advance(A.STATUS_IDLE_S + 1)
            assert not agent.status_wanted()             # idle again: refreshing stops
        finally:
            stop.set()
            agent.status_kick.set()
            thread.join(5)
        assert not thread.is_alive()
