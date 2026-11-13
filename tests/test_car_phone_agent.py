"""BCM's client of the Termux agent (src/network/car_phone_agent.py).

The agent side is the REAL tools/car_phone/termux/bcm_agent.py (imported by
path, fake Termux runner) served by its own ThreadingHTTPServer on
127.0.0.1:0, so signing and verification are checked end to end. Also: the
pair route of web_viewer (loopback only, 409 / 429), the dashboard summary,
and the secret's place in SECRET_ENV_MAP (never written to local.yaml).
"""

from __future__ import annotations

import http.server
import importlib.util
import json
import logging
import os
import stat
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core import modules_catalog as mc
from src.core.config import SECRET_ENV_MAP, BCMConfig
from src.core.event_bus import EventBus
from src.dashboard import web_viewer as wv
from src.dashboard.web_viewer import WebViewer
from src.network import car_phone_agent as cpa

REPO = Path(__file__).resolve().parent.parent
AGENT_PATH = REPO / "tools" / "car_phone" / "termux" / "bcm_agent.py"


def _load_agent():
    old = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location("bcm_agent_for_client_tests", AGENT_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = old
    return mod


A = _load_agent()

SECRET = "3c" * 32                       # 64 hex characters — a test value
OTHER = "d4" * 32
CODE = "4815162342"                      # a pairing code as bcm_agent.py --pair prints
NUM1, NUM2 = "+48601234567", "+48601234568"


class Runner:
    """Termux:API stand-in; refuses anything unexpected."""

    def __init__(self):
        self.calls = []

    def __call__(self, argv, stdin, timeout):
        assert isinstance(argv, list) and all(isinstance(a, str) for a in argv)
        self.calls.append(list(argv))
        if argv[0] == "termux-sms-send":
            return 0, "", ""
        if argv[0] == "termux-sms-list":
            return 0, "[]", ""
        if argv[0] == "termux-telephony-deviceinfo":
            return 0, json.dumps({"sim_state": "ready", "network_operator": "26001"}), ""
        if argv[0] == "termux-battery-status":
            return 0, json.dumps({"percentage": 80}), ""
        raise AssertionError(f"unexpected command {argv}")


@pytest.fixture
def phone(tmp_path):
    """The real agent on 127.0.0.1:<free port>, with a request log."""
    runner = Runner()
    boot = [1000.0]
    agent = A.Agent(str(tmp_path / "phone"), runner=runner, clock=lambda: boot[0],
                    wall=time.time, localtime=time.gmtime)
    seen = []
    orig = agent.handle

    def handle(method, path, headers, body):
        seen.append((method, path))
        return orig(method, path, headers, body)
    agent.handle = handle
    server = A.make_server(agent, 0)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                              daemon=True)
    thread.start()
    yield SimpleNamespace(agent=agent, server=server, port=server.server_address[1],
                          runner=runner, dir=Path(tmp_path / "phone"), seen=seen, boot=boot)
    server.shutdown()
    server.server_close()


def _config(secret=SECRET, **sms):
    cfg = {"network": {"car_phone": {"agent": {}}}, "modules": {"car_phone": True,
                                                                "car_phone_agent": True},
           "crash_detection": {"sms": dict({"recipients": [NUM1]}, **sms)}}
    if secret is not None:
        cfg["network"]["car_phone"]["agent"]["secret"] = secret
    return cfg


def _forward(bus, port, ok=True, error=""):
    bus.publish("net.car_phone", {"state": "connected", "forwards": {
        "agent": {"local": port, "remote": 8765, "ok": ok, "error": error}}})


def _module(tmp_path, bus, config=None, **kw):
    return cpa.CarPhoneAgent(_config() if config is None else config, bus,
                             state_path=str(tmp_path / "bcm" / "car_phone_agent.json"), **kw)


def _state(bus):
    last = bus.get_last(cpa.TOPIC)
    return last[0] if last else None


def _poll(mod):
    mod._next_poll = 0.0
    return mod.cycle()


def _pair(mod, phone, code=CODE, confirm=False):
    """The driver: --pair on the phone, the code typed into Settings."""
    (phone.dir / "PAIRING").write_text(code + "\n")
    res = mod.request_pair(code, confirm)
    assert res["ok"], res
    return mod.cycle()


@pytest.fixture
def bus():
    return EventBus()


# ── protocol: identical on both sides ────────────────────────────────────

class TestProtocol:
    def test_signing_matches_the_agent(self):
        body = b'{"a":1}'
        assert cpa.request_message("PUT", "/v1/config", 5, 7, body) == \
            A.request_message("PUT", "/v1/config", 5, 7, body)
        assert cpa.response_message(200, 7, body) == A.response_message(200, 7, body)
        assert cpa.sign(b"k" * 32, b"m") == A.sign(b"k" * 32, b"m")

    def test_desired_config_hash_matches_the_agents_normal_form(self):
        desired = cpa.desired_config(_config(recipients=[NUM1, NUM2], dry_run=False))
        norm, err = A.normalize_config(desired, strict=True)
        assert err == "" and norm == desired
        assert cpa.config_hash(desired) == A.config_hash(norm)

    @pytest.mark.parametrize("value", [None, "", "ab" * 31, "zz" * 32, "ab" * 32 + "a", 5])
    def test_parse_secret_refuses_short_or_odd(self, value):
        assert cpa.parse_secret(value) is None

    def test_parse_secret(self):
        assert cpa.parse_secret(" " + SECRET.upper() + "\n") == bytes.fromhex(SECRET)


# ── health, pairing, config ──────────────────────────────────────────────

class TestRoundTrip:
    def test_unpaired_then_pair_then_ok(self, tmp_path, bus, phone):
        mod = _module(tmp_path, bus)
        _forward(bus, phone.port)
        mod.cycle()
        st = _state(bus)
        assert st["state"] == "unpaired" and st["paired"] is False and st["pairing"] is None
        assert st["needs_confirm"] is False
        _pair(mod, phone)
        st = _state(bus)
        assert st["state"] == "ok" and st["paired"] is True and st["version"] == A.VERSION
        assert st["reason"] == "" and st["error"] == "" and st["pairing"] is False
        assert not (phone.dir / "PAIRING").exists()
        assert (phone.dir / "secret").read_text() == SECRET
        # the config went to the phone right after the first good health
        assert ("PUT", "/v1/config") in phone.seen
        assert phone.agent.config["recipients"] == [NUM1]
        assert phone.agent.config["dry_run"] is True

    def test_the_pairing_window_is_not_advertised(self, tmp_path, bus, phone):
        """An open PAIRING file is not visible to an unauthenticated poller."""
        (phone.dir / "PAIRING").write_text(CODE)
        mod = _module(tmp_path, bus)
        _forward(bus, phone.port)
        mod.cycle()
        assert _state(bus)["state"] == "unpaired" and _state(bus)["pairing"] is None

    def test_pairing_without_the_file_is_explained(self, tmp_path, bus, phone):
        mod = _module(tmp_path, bus)
        _forward(bus, phone.port)
        mod.cycle()
        res = mod.pair(CODE)
        assert res["ok"] is False and res["error"] == "pairing_closed"
        st = _state(bus)
        assert st["state"] == "unpaired" and st["reason"] == "pairing_closed"
        assert not phone.agent.paired

    def test_a_wrong_code_is_explained_and_sends_nothing_usable(self, tmp_path, bus, phone):
        (phone.dir / "PAIRING").write_text(CODE)
        mod = _module(tmp_path, bus)
        _forward(bus, phone.port)
        mod.cycle()
        res = mod.pair("1111111111")
        assert res["ok"] is False and res["error"] == "bad_code"
        st = _state(bus)
        assert st["state"] == "unpaired" and st["reason"] == "bad_code"
        assert not phone.agent.paired and (phone.dir / "PAIRING").exists()

    def test_pair_is_skipped_when_already_paired(self, tmp_path, bus, phone):
        mod = _module(tmp_path, bus)
        _forward(bus, phone.port)
        _pair(mod, phone)
        n = len(phone.seen)
        assert mod.pair(CODE)["error"] == "already_paired" and len(phone.seen) == n
        assert mod.request_pair(CODE)["error"] == "already_paired"

    @pytest.mark.parametrize("code, confirm", [("123456789", False), ("12345678901", False),
                                               ("12345abcde", False), (1234567890, False),
                                               (CODE, "yes")])
    def test_request_pair_validates(self, tmp_path, bus, phone, code, confirm):
        mod = _module(tmp_path, bus)
        _forward(bus, phone.port)
        assert mod.request_pair(code, confirm)["error"] == "bad_request"
        assert mod._pair_pending is None

    def test_config_is_pushed_only_on_change(self, tmp_path, bus, phone):
        config = _config()
        mod = _module(tmp_path, bus, config)
        _forward(bus, phone.port)
        _pair(mod, phone)
        puts = lambda: phone.seen.count(("PUT", "/v1/config"))   # noqa: E731
        assert puts() == 1
        _poll(mod)
        _poll(mod)
        assert puts() == 1
        config["crash_detection"]["sms"]["recipients"] = [NUM1, NUM2]
        _poll(mod)
        assert puts() == 2 and phone.agent.config["recipients"] == [NUM1, NUM2]
        _poll(mod)
        assert puts() == 2
        # an agent that lost its config gets it again (its hash differs)
        phone.agent.config = A.default_config()
        _poll(mod)
        assert puts() == 3

    def test_a_refused_config_is_not_hammered(self, tmp_path, bus, phone, monkeypatch, caplog):
        config = _config()
        mod = _module(tmp_path, bus, config)
        _forward(bus, phone.port)
        _pair(mod, phone)
        monkeypatch.setattr(phone.agent, "put_config",
                            lambda obj: (400, {"error": "bad_config", "detail": "nope"}))
        config["crash_detection"]["sms"]["sim_slot"] = 1
        with caplog.at_level(logging.WARNING, logger="bcm.network.car_phone_agent"):
            _poll(mod)
            _poll(mod)
            _poll(mod)
        assert phone.seen.count(("PUT", "/v1/config")) == 2      # 1 initial + 1 refused
        assert _state(bus)["state"] == "ok"
        config["crash_detection"]["sms"]["sim_slot"] = 0
        _poll(mod)                                               # back to what it holds
        assert phone.seen.count(("PUT", "/v1/config")) == 2

    def test_secret_mismatch_then_repair(self, tmp_path, bus, phone):
        phone.agent._key = bytes.fromhex(OTHER)
        (phone.dir / "secret").write_text(OTHER)
        mod = _module(tmp_path, bus)
        _forward(bus, phone.port)
        assert mod.cycle() == pytest.approx(cpa.POLL_OK_S, abs=0.5)  # a live agent: 30 s
        st = _state(bus)
        assert st["state"] == "error" and st["reason"] == "secret_mismatch"
        assert st["paired"] is False and st["needs_confirm"] is False
        _pair(mod, phone)                                        # Sparuj can fix it
        assert _state(bus)["state"] == "ok"
        assert (phone.dir / "secret").read_text() == SECRET

    def test_clock_skew(self, tmp_path, bus, phone):
        phone.agent._key = bytes.fromhex(SECRET)
        mod = _module(tmp_path, bus, wall_clock=lambda: time.time() + 120)
        _forward(bus, phone.port)
        mod.cycle()
        st = _state(bus)
        assert st["state"] == "error" and st["reason"] == "clock_skew"
        assert "differs" in st["error"]

    def test_backoff_while_failing(self, tmp_path, bus):
        def refused(port, timeout):
            raise ConnectionRefusedError(111, "Connection refused")
        mod = _module(tmp_path, bus, connect=refused)
        _forward(bus, 952)                                       # nothing listens there
        waits = [round(_poll(mod)) for _ in range(7)]
        assert _state(bus)["reason"] == "no_answer"
        assert waits[0] == pytest.approx(cpa.BACKOFF_MIN_S, abs=0.5)
        assert waits == [10, 20, 40, 80, 160, 300, 300]

    def test_worker_thread_end_to_end(self, tmp_path, bus, phone):
        phone.agent._key = bytes.fromhex(SECRET)
        mod = _module(tmp_path, bus)
        _forward(bus, phone.port)
        mod.start()
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and (_state(bus) or {}).get("state") != "ok":
                time.sleep(0.05)
            assert _state(bus)["state"] == "ok"
        finally:
            mod.stop()
        assert _state(bus)["state"] == "disabled" and _state(bus)["paired"] is None
        assert mod.arm_crash("ab", 45, None, None, None, None, None, int(time.time()))[
            "error"] == "stopped"


# ── untrusted answers ────────────────────────────────────────────────────

class _Fake(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    status = 200
    body = b'{"version":"9.9","paired":true}'
    sig = "0" * 64

    def do_GET(self):
        self._answer()

    def do_PUT(self):
        self._answer()

    def do_POST(self):
        self._answer()

    def _answer(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n:
            self.rfile.read(n)
        self.send_response(self.status)
        if self.sig is not None:
            self.send_header("X-BCM-Sig", self.sig)
        self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *a):
        pass


@pytest.fixture
def squatter():
    """Something else answering on the agent's forward."""
    servers = []

    def start(**attrs):
        handler = type("H", (_Fake,), attrs)
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                         daemon=True).start()
        servers.append(server)
        return server.server_address[1]
    yield start
    for s in servers:
        s.shutdown()
        s.server_close()


class TestUntrusted:
    @pytest.mark.parametrize("sig", ["0" * 64, None, "zz"])
    def test_bad_or_missing_response_signature(self, tmp_path, bus, squatter, sig, caplog):
        port = squatter(sig=sig)
        mod = _module(tmp_path, bus)
        _forward(bus, port)
        with caplog.at_level(logging.ERROR, logger="bcm.network.car_phone_agent"):
            mod.cycle()
        st = _state(bus)
        assert st["state"] == "bad_signature" and st["version"] is None
        assert st["paired"] is None
        assert any("not signed with our secret" in r.getMessage() for r in caplog.records)

    def test_signature_with_another_key(self, tmp_path, bus, squatter):
        body = b'{"version":"1.0.0"}'
        port = squatter(body=body, sig=A.sign(bytes.fromhex(OTHER),
                                               A.response_message(200, 1, body)))
        mod = _module(tmp_path, bus)
        _forward(bus, port)
        mod.cycle()
        assert _state(bus)["state"] == "bad_signature"

    def test_a_fake_sent_is_not_believed(self, tmp_path, bus, squatter):
        port = squatter(body=b'{"id":"ab","state":"sent"}', sig=None)
        mod = _module(tmp_path, bus)
        _forward(bus, port)
        res = mod.get("ab")
        assert res["ok"] is False and res["error"] == "bad_signature" and res["data"] is None
        assert _state(bus)["state"] == "bad_signature"

    def test_unsigned_refusal_is_only_informational(self, tmp_path, bus, squatter):
        port = squatter(status=403, sig=None,
                        body=b'{"error":"unpaired","pairing":true,"paired":false}')
        mod = _module(tmp_path, bus)
        _forward(bus, port)
        mod.cycle()
        assert _state(bus)["state"] == "unpaired"
        # ... but an unsigned 403 with an unknown code is not trusted
        port = squatter(status=403, sig=None, body=b'{"error":"sent"}')
        _forward(bus, port)
        _poll(mod)
        assert _state(bus)["state"] == "bad_signature"

    def test_no_pairing_while_something_else_answers(self, tmp_path, bus, squatter):
        seen = []
        port = squatter(sig=None, body=b'{"ok":true}')
        mod = _module(tmp_path, bus)
        _forward(bus, port)
        mod.cycle()
        assert _state(bus)["state"] == "bad_signature"
        orig = mod._client._exchange
        mod._client._exchange = lambda *a, **kw: seen.append(a) or orig(*a, **kw)
        assert mod.pair(CODE)["error"] == "untrusted"
        assert mod.request_pair(CODE)["error"] == "untrusted"
        assert seen == []                                    # the secret never left

    def test_deeply_nested_answer_is_a_clean_error(self, tmp_path, bus, squatter):
        port = squatter(sig=None, body=b"[" * 5000 + b"]" * 5000)
        mod = _module(tmp_path, bus)
        _forward(bus, port)
        assert mod.get("ab")["error"] == "bad_signature"       # never raises

    def test_oversized_answer(self, tmp_path, bus, squatter):
        port = squatter(body=b"x" * (cpa.MAX_RESPONSE_BYTES + 10))
        mod = _module(tmp_path, bus)
        _forward(bus, port)
        mod.cycle()
        st = _state(bus)
        assert st["state"] == "error" and st["reason"] == "http"


# ── a proven pairing is remembered (port squatter after the agent died) ──

class TestProvenPairing:
    def _paired(self, tmp_path, bus, phone):
        mod = _module(tmp_path, bus)
        _forward(bus, phone.port)
        _pair(mod, phone)
        assert _state(bus)["state"] == "ok"
        saved = json.loads((tmp_path / "bcm" / "car_phone_agent.json").read_text())
        assert saved["proven"] == cpa.key_fingerprint(bytes.fromhex(SECRET))
        assert SECRET not in json.dumps(saved)
        return mod

    def test_squatter_after_a_proven_pairing_gets_no_secret(self, tmp_path, bus, phone,
                                                           squatter):
        mod = self._paired(tmp_path, bus, phone)
        # The agent dies; another app binds the port and plays "unpaired".
        port = squatter(status=403, sig=None,
                        body=b'{"error":"unpaired","pairing":true,"paired":false}')
        _forward(bus, port)
        mod.cycle()
        st = _state(bus)
        assert st["state"] == "error" and st["reason"] == "agent_reset"
        assert st["needs_confirm"] is True and st["state"] != "unpaired"
        seen = []
        orig = mod._client._exchange
        mod._client._exchange = lambda *a, **kw: seen.append(a) or orig(*a, **kw)
        assert mod.request_pair(CODE)["error"] == "confirm_needed"
        assert mod.pair(CODE)["error"] == "confirm_needed"
        assert seen == [] and mod._pair_pending is None          # the secret never left
        # bad_auth after a proven pairing is the same warning
        port = squatter(status=401, sig=None, body=b'{"error":"bad_auth"}')
        _forward(bus, port)
        mod.cycle()
        assert _state(bus)["reason"] == "agent_reset"

    def test_the_proof_survives_a_bcm_restart(self, tmp_path, bus, phone, squatter):
        self._paired(tmp_path, bus, phone)
        port = squatter(status=403, sig=None, body=b'{"error":"unpaired"}')
        again = _module(tmp_path, bus)
        _forward(bus, port)
        again.cycle()
        assert _state(bus)["reason"] == "agent_reset"

    def test_a_reinstalled_agent_can_be_paired_with_confirmation(self, tmp_path, bus, phone):
        mod = self._paired(tmp_path, bus, phone)
        phone.agent._key = None                                  # Termux reinstalled
        (phone.dir / "secret").unlink()
        _poll(mod)
        assert _state(bus)["reason"] == "agent_reset"
        (phone.dir / "PAIRING").write_text(CODE)
        phone.boot[0] += A.PAIR_MIN_INTERVAL_S                   # the agent's pair limit
        assert mod.request_pair(CODE)["error"] == "confirm_needed"
        assert mod.request_pair(CODE, confirm=True)["ok"]
        mod.cycle()
        st = _state(bus)
        assert st["state"] == "ok" and st["needs_confirm"] is False

    def test_a_new_secret_is_a_normal_first_pairing(self, tmp_path, bus, phone):
        self._paired(tmp_path, bus, phone)
        mod = _module(tmp_path, bus, _config(secret=OTHER))      # bcm.env changed
        _forward(bus, phone.port)
        phone.boot[0] += A.PAIR_MIN_INTERVAL_S
        mod.cycle()
        st = _state(bus)
        assert st["state"] == "error" and st["reason"] == "secret_mismatch"
        assert st["needs_confirm"] is False
        _pair(mod, phone)
        assert _state(bus)["state"] == "ok"
        assert (phone.dir / "secret").read_text() == OTHER


# ── pair requests from the route ─────────────────────────────────────────

class TestPairRequests:
    def test_dropped_when_the_forward_goes_down(self, tmp_path, bus, phone, caplog):
        mod = _module(tmp_path, bus)
        _forward(bus, phone.port)
        mod.cycle()
        (phone.dir / "PAIRING").write_text(CODE)
        assert mod.request_pair(CODE)["ok"]
        _forward(bus, phone.port, ok=False, error="device offline")
        with caplog.at_level(logging.WARNING, logger="bcm.network.car_phone_agent"):
            mod.cycle()
        assert any("pair request dropped" in r.getMessage() for r in caplog.records)
        _forward(bus, phone.port)                     # hours later the phone is back
        mod.cycle()
        assert ("POST", "/v1/pair") not in phone.seen and not phone.agent.paired

    def test_dropped_when_too_old(self, tmp_path, bus, phone):
        now = [100.0]
        mod = _module(tmp_path, bus, clock=lambda: now[0])
        _forward(bus, phone.port)
        mod.cycle()
        (phone.dir / "PAIRING").write_text(CODE)
        assert mod.request_pair(CODE)["ok"]
        now[0] += cpa.PAIR_REQUEST_TTL_S + 1
        mod.cycle()
        assert ("POST", "/v1/pair") not in phone.seen

    def test_one_attempt_per_request(self, tmp_path, bus, phone):
        mod = _module(tmp_path, bus)
        _forward(bus, phone.port)
        mod.cycle()
        (phone.dir / "PAIRING").write_text(CODE)
        assert mod.request_pair("0000000000")["ok"]
        mod.cycle()
        mod.cycle()
        assert phone.seen.count(("POST", "/v1/pair")) == 1
        assert _state(bus)["reason"] == "bad_code"


# ── config sync ──────────────────────────────────────────────────────────

class TestConfigSync:
    def _ready(self, tmp_path, bus, phone, config):
        mod = _module(tmp_path, bus, config)
        _forward(bus, phone.port)
        _pair(mod, phone)
        assert _state(bus)["state"] == "ok" and _state(bus)["reason"] == ""
        return mod

    def test_a_transient_storage_failure_is_retried(self, tmp_path, bus, phone, monkeypatch):
        config = _config()
        mod = self._ready(tmp_path, bus, phone, config)
        orig = phone.agent._save_json
        failed = []

        def flaky(name, obj):
            if name == "config.json" and not failed:
                failed.append(name)
                raise OSError(28, "No space left on device")
            return orig(name, obj)
        monkeypatch.setattr(phone.agent, "_save_json", flaky)
        config["crash_detection"]["sms"]["recipients"] = [NUM1, NUM2]
        _poll(mod)
        st = _state(bus)
        assert failed and st["state"] == "ok" and st["reason"] == "config_pending"
        assert phone.agent.config["recipients"] == [NUM1]
        _poll(mod)                                               # the next poll re-PUTs
        assert phone.agent.config["recipients"] == [NUM1, NUM2]
        assert _state(bus)["reason"] == ""

    def test_a_refused_config_is_latched_and_shown(self, tmp_path, bus, phone, monkeypatch):
        config = _config()
        mod = self._ready(tmp_path, bus, phone, config)
        monkeypatch.setattr(phone.agent, "put_config",
                            lambda obj: (400, {"error": "bad_config", "detail": "nope"}))
        config["crash_detection"]["sms"]["sim_slot"] = 1
        _poll(mod)
        _poll(mod)
        assert phone.seen.count(("PUT", "/v1/config")) == 2      # 1 initial + 1 refused
        assert _state(bus)["reason"] == "config_refused"

    def test_a_hash_mismatch_after_200_is_latched(self, tmp_path, bus, phone, monkeypatch):
        config = _config()
        mod = self._ready(tmp_path, bus, phone, config)
        monkeypatch.setattr(phone.agent, "put_config",
                            lambda obj: (200, {"ok": True, "config_hash": "0" * 16}))
        config["crash_detection"]["sms"]["sim_slot"] = 1
        for _ in range(3):
            _poll(mod)
        assert phone.seen.count(("PUT", "/v1/config")) == 2
        assert _state(bus)["reason"] == "config_refused"

    def test_a_server_error_is_pending_and_logged_once(self, tmp_path, bus, phone, monkeypatch,
                                                       caplog):
        config = _config()
        mod = self._ready(tmp_path, bus, phone, config)
        monkeypatch.setattr(phone.agent, "put_config", lambda obj: (500, {"error": "storage"}))
        config["crash_detection"]["sms"]["sim_slot"] = 1
        with caplog.at_level(logging.WARNING, logger="bcm.network.car_phone_agent"):
            for _ in range(3):
                _poll(mod)
        assert phone.seen.count(("PUT", "/v1/config")) == 4      # retried every poll
        assert _state(bus)["reason"] == "config_pending"
        assert len([r for r in caplog.records if "config push failed" in r.getMessage()]) == 1


# ── transport: deadlines and closed connections ─────────────────────────

def _raw_server(handler):
    """A bare TCP server on 127.0.0.1:0 running ``handler(conn)`` per client."""
    import socket as _socket
    srv = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(4)
    stop = threading.Event()

    def loop():
        srv.settimeout(0.1)
        while not stop.is_set():
            try:
                conn, _a = srv.accept()
            except OSError:
                continue
            threading.Thread(target=handler, args=(conn, stop), daemon=True).start()
    threading.Thread(target=loop, daemon=True).start()
    return srv.getsockname()[1], lambda: (stop.set(), srv.close())


class TestTransport:
    def test_a_dripping_peer_cannot_hold_the_lock(self, tmp_path, bus, monkeypatch):
        """One byte every 0.4 s keeps each recv under the per-read timeout,
        but the whole exchange still ends at RESPONSE_DEADLINE_S."""
        monkeypatch.setattr(cpa, "RESPONSE_DEADLINE_S", 1.0)

        def drip(conn, stop):
            try:
                conn.recv(4096)
                for ch in b"HTTP/1.0 200 OK\r\nX-Pad: " + b"a" * 1000:
                    if stop.is_set():
                        break
                    conn.sendall(bytes([ch]))
                    time.sleep(0.4)
            except OSError:
                pass
            finally:
                conn.close()
        port, close = _raw_server(drip)
        try:
            mod = _module(tmp_path, bus)
            _forward(bus, port)
            t0 = time.monotonic()
            mod.cycle()
            took = time.monotonic() - t0
        finally:
            close()
        st = _state(bus)
        assert st["state"] == "error" and st["reason"] == "no_answer", st
        assert took < 4.0

    def test_closed_without_an_answer_is_no_answer(self, tmp_path, bus):
        """adb accepts on 952 and closes when nothing listens on the phone."""
        def close_after_request(conn, stop):
            try:
                conn.recv(4096)
            except OSError:
                pass
            conn.close()
        port, close = _raw_server(close_after_request)
        try:
            mod = _module(tmp_path, bus)
            _forward(bus, port)
            mod.cycle()
        finally:
            close()
        st = _state(bus)
        assert st["state"] == "error" and st["reason"] == "no_answer", st

    @pytest.mark.parametrize("rst", [False, True], ids=["fin", "rst"])
    def test_a_break_after_the_whole_request_is_dropped_not_connect(self, tmp_path, bus, rst):
        """The agent read the whole POST /v1/crash (and may have armed and
        saved it) — then the link broke before the answer: "dropped", so
        crash_sms treats the arm as maybe delivered (a cancel is sent, the
        event is looked up), never as "certainly not delivered"."""
        import re as _re
        import socket as _socket
        import struct
        bodies = []

        def read_all_then_close(conn, stop):
            try:
                conn.settimeout(3)
                buf = b""
                while b"\r\n\r\n" not in buf:
                    chunk = conn.recv(4096)
                    if not chunk:
                        return
                    buf += chunk
                head, _, body = buf.partition(b"\r\n\r\n")
                m = _re.search(rb"content-length:\s*(\d+)", head, _re.I)
                while m and len(body) < int(m.group(1)):
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    body += chunk
                bodies.append(body)
                if rst:
                    conn.setsockopt(_socket.SOL_SOCKET, _socket.SO_LINGER,
                                    struct.pack("ii", 1, 0))
            except OSError:
                pass
            finally:
                conn.close()
        port, close = _raw_server(read_all_then_close)
        try:
            mod = _module(tmp_path, bus)
            _forward(bus, port)
            res = mod.arm_crash("ab" * 16, 45, None, None, None, None, None, int(time.time()))
        finally:
            close()
        assert bodies and json.loads(bodies[0])["event_id"] == "ab" * 16   # it arrived whole
        assert res["ok"] is False and res["error"] == "dropped", res

    def test_refused_is_connect(self, tmp_path, bus):
        """Nothing listens: the request certainly did not arrive."""
        import socket as _socket
        s = _socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()                                        # nothing listens there now
        mod = _module(tmp_path, bus)
        _forward(bus, port)
        res = mod.get("ab" * 16)
        assert res["ok"] is False and res["error"] == "connect", res
        mod.cycle()
        assert _state(bus)["reason"] == "no_answer"


# ── threads: one writer, ordered publications, the accessor ─────────────

class TestThreads:
    def test_get_agent_follows_start_and_stop(self, tmp_path, bus, monkeypatch):
        monkeypatch.setattr(cpa, "STATE_FILE", str(tmp_path / "bcm" / "car_phone_agent.json"))
        assert cpa.get_agent() is None
        mod = cpa.start_car_phone_agent(_config(), bus)
        try:
            assert cpa.get_agent() is mod
        finally:
            mod.stop()
        assert cpa.get_agent() is None
        assert _state(bus)["state"] == "disabled"

    def test_nothing_is_published_after_stop(self, tmp_path, bus):
        mod = _module(tmp_path, bus)
        mod.stop()
        assert _state(bus)["state"] == "disabled"
        assert mod._set_state("ok") is False
        assert _state(bus)["state"] == "disabled"

    def test_api_threads_hand_untrusted_answers_to_the_worker(self, tmp_path, bus, squatter):
        port = squatter(body=b'{"id":"ab","state":"sent"}', sig=None)
        mod = _module(tmp_path, bus)
        _forward(bus, port)
        mod._thread = threading.Thread(target=lambda: None)      # a worker that is not us
        out = []
        t = threading.Thread(target=lambda: out.append(mod.get("ab")))
        t.start()
        t.join(10)
        assert out[0]["error"] == "bad_signature"
        assert mod._untrusted_pending is not None
        assert mod.request_pair(CODE)["error"] == "untrusted"   # before the worker ran
        mod._thread = None
        mod.cycle()
        assert _state(bus)["state"] == "bad_signature"


# ── no secret / no forward ───────────────────────────────────────────────

class _NoConnect:
    def __init__(self):
        self.calls = 0

    def __call__(self, port, timeout):
        self.calls += 1
        raise AssertionError("no connection expected")


class TestIdle:
    @pytest.mark.parametrize("secret", [None, "", "abc123", "ab" * 31])
    def test_no_secret(self, tmp_path, bus, secret, caplog):
        connect = _NoConnect()
        with caplog.at_level(logging.WARNING, logger="bcm.network.car_phone_agent"):
            mod = _module(tmp_path, bus, _config(secret=secret), connect=connect)
            _forward(bus, 952)
            assert mod.cycle() == cpa.NO_SECRET_WAIT_S
            mod.cycle()
        assert _state(bus)["state"] == "no_secret"
        assert connect.calls == 0
        warnings = [r.getMessage() for r in caplog.records]
        assert len(warnings) == 1 and "BCM_CAR_PHONE_AGENT_SECRET" in warnings[0]
        if secret:
            assert secret not in warnings[0]
        for api in (lambda: mod.get("ab"), mod.test_sms, lambda: mod.pair(CODE),
                    lambda: mod.request_pair(CODE)):
            assert api()["error"] == "no_secret"
        assert not (tmp_path / "bcm").exists()

    def test_the_secret_is_never_logged(self, tmp_path, bus, phone, caplog):
        with caplog.at_level(logging.DEBUG):
            mod = _module(tmp_path, bus)
            _forward(bus, phone.port)
            mod.cycle()
            _pair(mod, phone)
            _poll(mod)
        assert caplog.records
        assert not any(SECRET in r.getMessage() for r in caplog.records)
        assert SECRET not in json.dumps(_state(bus))

    @pytest.mark.parametrize("car_phone", [
        None,
        {"state": "disabled", "forwards": {}},
        {"state": "connected", "forwards": {}},
        {"state": "no_device", "forwards": {"agent": {"local": 952, "remote": 8765,
                                                      "ok": False, "error": ""}}},
        {"state": "connected", "forwards": {"agent": {"local": "952", "ok": True}}},
        {"state": "connected", "forwards": {"agent": {"local": 70000, "ok": True}}},
    ])
    def test_forward_not_ready(self, tmp_path, bus, car_phone):
        connect = _NoConnect()
        mod = _module(tmp_path, bus, connect=connect)
        if car_phone is not None:
            bus.publish("net.car_phone", car_phone)
        assert mod.cycle() == cpa.WAIT_FORWARD_S
        st = _state(bus)
        assert st["state"] == "waiting_forward" and st["error"]
        assert connect.calls == 0
        for api in (lambda: mod.get("ab"), lambda: mod.cancel("ab"), mod.test_sms):
            assert api()["error"] == "no_forward"

    def test_missing_forward_names_the_toggle(self, tmp_path, bus):
        mod = _module(tmp_path, bus, connect=_NoConnect())
        bus.publish("net.car_phone", {"state": "connected", "forwards": {}})
        mod.cycle()
        assert "modules.car_phone_agent" in _state(bus)["error"]


# ── nonce ────────────────────────────────────────────────────────────────

class TestNonce:
    def test_reserved_on_disk_before_use_and_strictly_increasing(self, tmp_path, bus, phone):
        frozen = [time.time()]
        mod = _module(tmp_path, bus, wall_clock=lambda: frozen[0])
        phone.agent._key = bytes.fromhex(SECRET)
        _forward(bus, phone.port)
        client = mod._client
        nonces = []
        for _ in range(5):
            mod.get("ab")
            nonces.append(client.last_nonce)
        assert nonces == sorted(set(nonces)) and nonces[-1] - nonces[0] == 4
        path = tmp_path / "bcm" / "car_phone_agent.json"
        saved = json.loads(path.read_text())
        assert saved["reserved"] >= nonces[-1]
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
        # a restart continues ABOVE everything ever sent
        again = _module(tmp_path, bus, wall_clock=lambda: frozen[0])
        again.get("ab")
        assert again._client.last_nonce > saved["reserved"] >= nonces[-1]
        assert again.get("ab")["status"] == 404                  # accepted, signed

    def test_one_write_per_reserved_block(self, tmp_path, monkeypatch):
        writes = []
        monkeypatch.setattr(cpa, "atomic_write_json",
                            lambda path, obj, mode=0o644: writes.append(obj["reserved"]))
        wall = [1_763_000_000.0]
        client = cpa.AgentClient(b"k" * 32, str(tmp_path / "n.json"), lambda: wall[0])
        for _ in range(100):
            client._next_nonce()
            wall[0] += 1
        assert len(writes) == 1                                  # 100 s < 10 min block
        wall[0] += cpa.NONCE_RESERVE / 1000
        client._next_nonce()
        assert len(writes) == 2

    def test_storage_failure_sends_nothing(self, tmp_path, bus, phone, monkeypatch):
        def boom(*a, **kw):
            raise OSError("read-only file system")
        monkeypatch.setattr(cpa, "atomic_write_json", boom)
        mod = _module(tmp_path, bus)
        _forward(bus, phone.port)
        mod.cycle()
        assert phone.seen == []
        assert _state(bus)["reason"] == "storage"

    def test_resync_after_a_lost_state_file(self, tmp_path, bus, phone):
        phone.agent._key = bytes.fromhex(SECRET)
        first = _module(tmp_path, bus)
        _forward(bus, phone.port)
        first._client._last = first._client._reserved = int(time.time() * 1000) + 10**9
        assert first.get("ab")["status"] == 404
        (tmp_path / "bcm" / "car_phone_agent.json").unlink()
        second = _module(tmp_path, bus)
        res = second.get("ab")
        assert res["status"] == 404, res                       # signed 409 → jump → retry
        assert second._client.last_nonce > first._client.last_nonce

    def test_damaged_state_file(self, tmp_path, bus, phone, caplog):
        path = tmp_path / "bcm" / "car_phone_agent.json"
        path.parent.mkdir(parents=True)
        path.write_text('{"reserved": "lots"}')
        phone.agent._key = bytes.fromhex(SECRET)
        with caplog.at_level(logging.WARNING, logger="bcm.network.car_phone_agent"):
            mod = _module(tmp_path, bus)
        assert any("damaged" in r.getMessage() for r in caplog.records)
        _forward(bus, phone.port)
        assert mod.get("ab")["status"] == 404


# ── the API for later modules ────────────────────────────────────────────

@pytest.fixture
def crash_sms_has_code(monkeypatch):
    """crash_sms has code now (src/safety/crash_sms.py); kept so these tests
    do not depend on the catalog entry staying that way."""
    info = {k: v for k, v in mc.MODULES["crash_sms"].items() if k != "planned"}
    monkeypatch.setitem(mc.MODULES, "crash_sms", info)


class TestApi:
    def _ready(self, tmp_path, bus, phone, **sms):
        config = _config(**sms)
        config["modules"]["crash_sms"] = True
        mod = _module(tmp_path, bus, config)
        _forward(bus, phone.port)
        _pair(mod, phone)
        assert _state(bus)["state"] == "ok"
        return mod

    def test_crash_flow(self, tmp_path, bus, phone, crash_sms_has_code):
        mod = self._ready(tmp_path, bus, phone)
        assert phone.agent.config["toggles"]["crash_sms"] is True
        ts = int(time.time())
        res = mod.arm_crash("c0ffee", 45, 52.229681, 21.012231, 4, 72.4, 45.6, ts)
        assert res["ok"] and res["data"]["state"] == "armed" and res["data"]["created"] is True
        again = mod.arm_crash("c0ffee", 45, 52.229681, 21.012231, 4, 72.4, 45.6, ts)
        assert again["ok"] and again["data"]["created"] is False
        assert mod.get("c0ffee")["data"]["deadline_in_s"] == 45
        assert mod.cancel("c0ffee")["data"]["state"] == "cancelled"
        assert mod.get("dead")["status"] == 404 and mod.get("dead")["error"] == "unknown_event"
        assert mod.send_now("c0ffee")["ok"]

    def test_send_now_and_test_sms(self, tmp_path, bus, phone, crash_sms_has_code):
        mod = self._ready(tmp_path, bus, phone)
        mod.arm_crash("ab12", 15, None, None, None, None, None, int(time.time()))
        assert mod.send_now("ab12")["ok"]
        phone.agent.step()
        assert mod.get("ab12")["data"]["state"] in ("sent", "sending")
        res = mod.test_sms()
        assert res["ok"] and res["data"]["dry_run"] is True
        assert mod.test_sms()["status"] == 429

    def test_agent_refusals_come_back_as_errors(self, tmp_path, bus, phone):
        config = _config()
        config["modules"]["crash_sms"] = False               # the phone's toggle: off
        mod = _module(tmp_path, bus, config)
        _forward(bus, phone.port)
        _pair(mod, phone)
        res = mod.arm_crash("ab", 45, None, None, None, None, None, int(time.time()))
        assert res == {"ok": False, "status": 409, "data": {"error": "crash_sms_off"},
                       "error": "crash_sms_off", "detail": ""}

    @pytest.mark.parametrize("args", [
        ("AB", 45, None, None, None, None, None, 1_763_000_000),
        ("ab", 14, None, None, None, None, None, 1_763_000_000),
        ("ab", True, None, None, None, None, None, 1_763_000_000),
        ("ab", 45, None, None, None, None, None, 0),
        ("ab", 45, None, None, None, None, None, float("nan")),
        ("ab", 45, None, None, None, None, None, "1763000000"),
        ("ab", 45, None, None, None, None, None, True),
    ])
    def test_invalid_arguments_never_reach_the_phone(self, tmp_path, bus, phone, args):
        mod = self._ready(tmp_path, bus, phone)
        n = len(phone.seen)
        res = mod.arm_crash(*args)
        assert res["ok"] is False and res["error"] == "bad_request"
        assert len(phone.seen) == n
        for bad in ("../x", "AB", "", 5):
            assert mod.cancel(bad)["error"] == "bad_request"
            assert mod.get(bad)["error"] == "bad_request"
        assert len(phone.seen) == n


class TestApiFields:
    def _ready(self, tmp_path, bus, phone):
        config = _config()
        config["modules"]["crash_sms"] = True
        mod = _module(tmp_path, bus, config)
        _forward(bus, phone.port)
        _pair(mod, phone)
        return mod

    @pytest.mark.parametrize("lat, lon, age, speed, dv", [
        (95.0, 21.0, 4, 72, 45), (52.0, None, 4, 72, 45), (float("nan"), 21.0, 4, 72, 45),
        (52.2, 21.0, -1, 72, 45), (52.2, 21.0, 4, 500, 45), (52.2, 21.0, 4, 72, float("inf")),
    ])
    def test_bad_optional_numbers_go_as_unknown(self, tmp_path, bus, phone, crash_sms_has_code,
                                                 caplog, lat, lon, age, speed, dv):
        """A GPS glitch must not cost the alarm: the field goes as null."""
        mod = self._ready(tmp_path, bus, phone)
        sent = []
        orig = mod._client.request
        mod._client.request = lambda *a, **kw: sent.append(a) or orig(*a, **kw)
        with caplog.at_level(logging.WARNING, logger="bcm.network.car_phone_agent"):
            res = mod.arm_crash("c0ffee", 45, lat, lon, age, speed, dv, int(time.time()))
        assert res["ok"] and res["data"]["state"] == "armed", res
        body = sent[-1][3]
        bad_pos = lat is None or lon is None or lat != lat or abs(lat) > 90
        assert (body["lat"] is None and body["lon"] is None) == bad_pos
        assert body["speed_kmh"] == (72 if speed == 72 else None)
        assert any("sent as unknown" in r.getMessage() for r in caplog.records)

    def test_test_sms_modes(self, tmp_path, bus, phone):
        mod = self._ready(tmp_path, bus, phone)
        sent = []
        orig = mod._client.request
        mod._client.request = lambda *a, **kw: sent.append(a) or orig(*a, **kw)
        assert mod.test_sms(force_dry=True, real=True)["error"] == "bad_request"
        assert sent == []
        res = mod.test_sms(real=True)                 # the config is dry_run: true
        assert res["ok"] and res["data"]["dry_run"] is False
        assert sent[-1][3] == {"real_test": True}
        phone.agent.meta["last_test_wall"] = None
        assert mod.test_sms(force_dry=True)["data"]["dry_run"] is True
        assert sent[-1][3] == {"dry_run": True}


# ── desired config ───────────────────────────────────────────────────────

class TestDesiredConfig:
    def test_defaults(self):
        assert cpa.desired_config({}) == {
            "recipients": [], "sim_slot": 0, "vehicle_label": "ALFA 156",
            "toggles": dict.fromkeys(cpa.AGENT_TOGGLES, False), "dry_run": True,
            "follow_up_cancel": True}

    def test_recipients_validated_and_never_logged(self):
        warned = []
        cfg = _config(recipients=["601234567", NUM1, NUM1, " " + NUM2, 48601234569,
                                  "+48601234560", "+48601234561"])
        out = cpa.desired_config(cfg, lambda k, m: warned.append(m))
        assert out["recipients"] == [NUM1, NUM2, "+48601234560"]
        assert warned and not any("601234567" in m for m in warned)

    @pytest.mark.parametrize("value", ["+48601234567", {"a": 1}, 5])
    def test_recipients_not_a_list(self, value):
        assert cpa.desired_config(_config(recipients=value))["recipients"] == []

    @pytest.mark.parametrize("sms, key, expected", [
        ({"sim_slot": 1}, "sim_slot", 1), ({"sim_slot": 2}, "sim_slot", 0),
        ({"sim_slot": True}, "sim_slot", 0),
        ({"vehicle_label": "GTA 3.2"}, "vehicle_label", "GTA 3.2"),
        ({"vehicle_label": "Łódź"}, "vehicle_label", "ALFA 156"),
        ({"vehicle_label": "A" * 21}, "vehicle_label", "ALFA 156"),
        ({"dry_run": False}, "dry_run", False), ({"dry_run": "false"}, "dry_run", True),
        ({"dry_run": 0}, "dry_run", True), ({"dry_run": None}, "dry_run", True),
        ({"follow_up_cancel": False}, "follow_up_cancel", False),
    ])
    def test_fields(self, sms, key, expected):
        assert cpa.desired_config(_config(**sms))[key] == expected

    def test_toggles_mirror_only_modules_with_code(self, crash_sms_has_code):
        cfg = _config()
        cfg["modules"].update(crash_sms=True, parking_guard=True, cabin_watch="yes")
        toggles = cpa.desired_config(cfg)["toggles"]
        # crash_sms has code (fixture); parking_guard is planned; "yes" is not True
        assert toggles == {"crash_sms": True, "parking_guard": False, "cabin_watch": False,
                           "call112": False}


# ── the secret's place in the config ─────────────────────────────────────

class TestSecretConfig:
    def test_registered_in_secret_env_map(self):
        assert SECRET_ENV_MAP["network.car_phone.agent.secret"] == "BCM_CAR_PHONE_AGENT_SECRET"
        assert cpa.SECRET_PATH in SECRET_ENV_MAP and cpa.SECRET_ENV in SECRET_ENV_MAP.values()

    def test_from_env_and_never_saved_to_local_yaml(self, tmp_path):
        local = tmp_path / "local.yaml"
        cfg = BCMConfig(config_path=str(REPO / "config" / "bcm_config_test.yaml"),
                        platform_override="x86", local_path=str(local),
                        env={"BCM_CAR_PHONE_AGENT_SECRET": SECRET})
        assert cfg.get("network.car_phone.agent.secret") == SECRET
        assert cpa.parse_secret(cfg.get(cpa.SECRET_PATH)) == bytes.fromhex(SECRET)
        cfg.set("modules.car_phone_agent", True)
        assert cfg.save() is not False
        text = local.read_text()
        assert "car_phone_agent: true" in text and SECRET not in text
        assert "secret" not in json.dumps(cfg.overlay())

    def test_example_env_documents_it(self):
        text = (REPO / "config" / "bcm.env.example").read_text(encoding="utf-8")
        assert "#BCM_CAR_PHONE_AGENT_SECRET=" in text
        assert "secrets.token_hex(32)" in text

    def test_production_config_does_not_start_it(self):
        cfg = BCMConfig(config_path=str(REPO / "config" / "bcm_config.yaml"),
                        platform_override="x86", local_path=None, env={})
        assert mc.is_enabled(cfg, "car_phone_agent") is False
        assert mc.module_states(cfg)["car_phone_agent"].runs is False


# ── web_viewer: summary and the pair route ───────────────────────────────

class _FakeModule:
    """Stands in for the running CarPhoneAgent behind get_agent()."""

    def __init__(self, answer=None):
        self.calls = []
        self.answer = answer or {"ok": True}

    def request_pair(self, code, confirm=False):
        self.calls.append((code, confirm))
        return dict(self.answer)


@pytest.fixture(autouse=False)
def web(monkeypatch):
    def refuse(*a, **kw):
        raise AssertionError("no subprocess from web_viewer here")
    monkeypatch.setattr(wv, "subprocess", SimpleNamespace(run=refuse, Popen=refuse))
    bus = EventBus()
    seen = []
    bus.subscribe("*", lambda t, v, ts: seen.append((t, v)))
    cfg = BCMConfig(platform_override="x86")
    cfg.save = lambda path=None: None
    viewer = WebViewer(host="127.0.0.1", port=5099, event_bus=bus, config=cfg)
    module = _FakeModule()
    holder = {"agent": module}
    monkeypatch.setattr(cpa, "get_agent", lambda: holder["agent"])
    return SimpleNamespace(bus=bus, viewer=viewer, client=viewer._build_app().test_client(),
                           module=module, holder=holder, seen=seen)


AGENT_OK = {"state": "ok", "paired": True, "pairing": False, "version": "1.0.0",
            "sim_ready": True, "last_ok_ts": 1_763_000_000.5, "last_sent_ts": None,
            "reason": "", "error": "", "needs_confirm": False, "since": 1.0}


def _as(addr):
    return {"environ_base": {"REMOTE_ADDR": addr}}


class TestPairRoute:
    def test_not_running(self, web):
        web.holder["agent"] = None
        res = web.client.post("/api/car_phone_agent/pair", json={"code": CODE})
        assert res.status_code == 409 and res.get_json()["error"] == "not_running"

    @pytest.mark.parametrize("error", ["no_secret", "no_forward", "untrusted", "already_paired",
                                       "confirm_needed", "stopped"])
    def test_module_refusals_are_409(self, web, error):
        web.module.answer = {"ok": False, "error": error}
        res = web.client.post("/api/car_phone_agent/pair", json={"code": CODE})
        assert res.status_code == 409 and res.get_json()["error"] == error
        # a refusal does not use the rate limit ("Sparuj mimo to" right after)
        web.module.answer = {"ok": True}
        assert web.client.post("/api/car_phone_agent/pair",
                               json={"code": CODE, "confirm": True}).status_code == 200

    @pytest.mark.parametrize("body", [None, {}, {"code": "123"}, {"code": 4815162342},
                                      {"code": CODE + "0"}, {"code": "48151623a2"},
                                      {"code": CODE, "confirm": "yes"}, ["x"]])
    def test_malformed_bodies(self, web, body):
        res = web.client.post("/api/car_phone_agent/pair", json=body)
        assert res.status_code == 400
        assert web.module.calls == []

    def test_oversized_body(self, web):
        res = web.client.post("/api/car_phone_agent/pair",
                              data=json.dumps({"code": CODE, "x": "y" * 1000}),
                              content_type="application/json")
        assert res.status_code == 413 and web.module.calls == []

    def test_hands_the_code_to_the_module_and_is_rate_limited(self, web):
        res = web.client.post("/api/car_phone_agent/pair", json={"code": CODE, "confirm": True,
                                                                 "secret": "x" * 64})
        assert res.status_code == 200 and res.get_json() == {"ok": True}
        assert web.module.calls == [(CODE, True)]
        res = web.client.post("/api/car_phone_agent/pair", json={"code": CODE})
        assert res.status_code == 429
        assert 1 <= int(res.headers["Retry-After"]) <= wv._AGENT_PAIR_MIN_INTERVAL_S
        assert web.module.calls == [(CODE, True)]
        web.viewer._agent_pair_last -= wv._AGENT_PAIR_MIN_INTERVAL_S
        assert web.client.post("/api/car_phone_agent/pair",
                               json={"code": CODE}).status_code == 200
        assert web.module.calls == [(CODE, True), (CODE, False)]

    def test_the_code_never_reaches_the_bus_or_the_log(self, web, caplog):
        with caplog.at_level(logging.DEBUG):
            web.client.post("/api/car_phone_agent/pair", json={"code": CODE})
            web.client.post("/api/car_phone_agent/pair", json={"code": CODE},
                            **_as("192.168.1.50"))
        assert CODE not in json.dumps(web.seen, default=str)
        assert not any(CODE in r.getMessage() for r in caplog.records)

    @pytest.mark.parametrize("addr", ["192.168.1.50", "10.0.0.5", "8.8.8.8", "::2"])
    def test_loopback_only_even_with_full_remote_access(self, web, addr):
        assert web.viewer._config.get("dashboard.remote_access") is None     # = full
        res = web.client.post("/api/car_phone_agent/pair", json={"code": CODE}, **_as(addr))
        assert res.status_code == 403
        assert web.module.calls == []

    @pytest.mark.parametrize("addr", ["127.0.0.1", "::1", "::ffff:127.0.0.1"])
    def test_kiosk_addresses(self, web, addr):
        assert web.client.post("/api/car_phone_agent/pair", json={"code": CODE},
                               **_as(addr)).status_code == 200

    def test_get_is_not_allowed(self, web):
        assert web.client.get("/api/car_phone_agent/pair").status_code == 405


class TestSummary:
    def test_none_while_the_module_never_published(self, web):
        assert web.viewer._get_dashboard_data()["car_phone_agent"] is None

    def test_summary(self, web):
        web.bus.publish(cpa.TOPIC, AGENT_OK)
        assert web.viewer._get_dashboard_data()["car_phone_agent"] == {
            "state": "ok", "paired": True, "pairing": False, "version": "1.0.0",
            "sim_ready": True, "last_ok_ts": 1_763_000_000.5, "last_sent_ts": None,
            "reason": "", "error": "", "needs_confirm": False}

    def test_garbage_is_neutralised(self, web):
        web.bus.publish(cpa.TOPIC, {
            "state": "<script>", "paired": "yes", "pairing": 1, "version": "1<img>",
            "sim_ready": "true", "last_ok_ts": float("inf"), "last_sent_ts": True,
            "reason": "<b>", "error": 5, "needs_confirm": "yes"})
        assert web.viewer._get_dashboard_data()["car_phone_agent"] == {
            "state": "unknown", "paired": None, "pairing": None, "version": None,
            "sim_ready": None, "last_ok_ts": None, "last_sent_ts": None, "reason": "",
            "error": "", "needs_confirm": False}

    def test_every_state_and_reason_passes(self, web):
        for state in cpa.STATES:
            for reason in cpa.REASONS:
                web.bus.publish(cpa.TOPIC, dict(AGENT_OK, state=state, reason=reason))
                out = web.viewer._get_dashboard_data()["car_phone_agent"]
                assert out["state"] == state and out["reason"] == reason
