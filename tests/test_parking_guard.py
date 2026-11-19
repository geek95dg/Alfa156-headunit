"""BCM's side of the alarm on the parked car (plan D4):
src/safety/parking_guard.py, the parking guard part of
src/network/car_phone_agent.py and the web routes / Settings payload.

Fakes only: a fake agent API (records every call), a synchronous EventBus,
a fake clock; the end-to-end class runs the REAL Termux agent on
127.0.0.1:0 with a runner that refuses unexpected commands. Nothing reaches
a phone, adb or the network.

Covers: one disarm per owner connection edge (repeats of the same
connection, strangers, retries until confirmed, TTL), owner phones from
owner_macs or the last_bt_device snapshot, Uzbrój / Rozbrój from Settings
(owner proof or a TOTP code), the polled state on park.state, one alarm
notification, never alarm.sensor.*, the toggle / park_* config push and the
version skew with an agent before 1.2.0, the summary sanitiser and the
loopback-only routes.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core.config import BCMConfig
from src.core.event_bus import EventBus
from src.dashboard import web_viewer as wv
from src.dashboard.web_viewer import WebViewer
from src.network import car_phone_agent as cpa
from src.safety import parking_guard as pg

REPO = Path(__file__).resolve().parent.parent
AGENT_PATH = REPO / "tools" / "car_phone" / "termux" / "bcm_agent.py"

OWNER_MAC = "AA:BB:CC:DD:EE:01"
OTHER_MAC = "AA:BB:CC:DD:EE:02"
NUM1, NUM2 = "+48601234567", "+48601234568"
T0 = 1_763_000_000.0

VIEW = {"state": "armed", "since": T0 - 600, "by": "power", "arm_at": None,
        "last_event": None, "battery": {"pct": 64, "power": "unplugged"}, "log_only": False,
        "light": False, "sensor": "ok", "totp_ready": True, "numbers_n": 2, "home_set": False,
        "alarms_today": 0}


class Clock:
    def __init__(self):
        self.t = 100.0
        self.wall = T0

    def advance(self, s):
        self.t += s
        self.wall += s


class FakeAgent:
    """The CarPhoneAgent API as parking_guard uses it."""

    def __init__(self):
        self.calls = []
        self.disarm_results = []
        self.view = dict(VIEW)
        self.status_result = None
        self.arm_result = None
        self.thread_ids = set()

    def _ok(self, view=None):
        return {"ok": True, "status": 200, "data": dict(view or self.view), "error": "",
                "detail": ""}

    def park_status(self):
        self.calls.append(("status",))
        self.thread_ids.add(threading.get_ident())
        return self.status_result or self._ok()

    def park_arm(self, delay_min=None):
        self.calls.append(("arm", delay_min))
        return self.arm_result or self._ok(dict(self.view, state="arming"))

    def park_disarm(self, code=None):
        self.calls.append(("disarm", code))
        self.thread_ids.add(threading.get_ident())
        if self.disarm_results:
            return self.disarm_results.pop(0)
        return self._ok(dict(self.view, state="disarmed", by="owner_bt"))

    def disarms(self):
        return [c for c in self.calls if c[0] == "disarm"]


def _config(**park):
    return {"modules": {"car_phone": True, "car_phone_agent": True, "parking_guard": True},
            "multimedia": {"last_bt_device": OWNER_MAC.lower()},
            "parking_guard": park}


class Env:
    def __init__(self, config=None, agent="fake"):
        self.bus = EventBus()
        self.clock = Clock()
        self.agent = FakeAgent() if agent == "fake" else agent
        self.notes = []
        self.config = _config() if config is None else config
        self.m = pg.ParkingGuard(self.config, self.bus, agent_getter=lambda: self.agent,
                                 clock=lambda: self.clock.t, wall_clock=lambda: self.clock.wall,
                                 notify=lambda bus, title, desc, **kw: self.notes.append(
                                     (title, desc, kw)))
        self.topics = []
        self.bus.subscribe("*", lambda topic, value, ts: self.topics.append(topic))
        self.m.subscribe()

    def run(self):
        return self.m.run_once()

    def state(self):
        last = self.bus.get_last(pg.TOPIC_STATE)
        return last[0] if last else None


@pytest.fixture
def env():
    return Env()


# ── owner proof: the Bluetooth connection edge ───────────────────────────

class TestOwnerEdge:
    def test_one_disarm_per_owner_connection(self, env):
        env.run()
        env.bus.publish("bt.connected", {"address": OWNER_MAC, "name": "Pixel"})
        env.run()
        assert env.agent.disarms() == [("disarm", None)]
        # bluetooth publishes the same connection again (state re-sync)
        for _ in range(3):
            env.bus.publish("bt.connected", {"address": OWNER_MAC.lower(), "name": "Pixel"})
            env.clock.advance(60)
            env.run()
        assert len(env.agent.disarms()) == 1
        # a new connection after a disconnect is a new edge
        env.bus.publish("bt.disconnected", {"address": OWNER_MAC})
        env.run()
        env.bus.publish("bt.connected", {"address": OWNER_MAC, "name": "Pixel"})
        env.run()
        assert len(env.agent.disarms()) == 2

    def test_a_stranger_never_disarms(self, env):
        env.bus.publish("bt.connected", {"address": OTHER_MAC, "name": "?"})
        env.run()
        assert env.agent.disarms() == [] and env.state()["owner_connected"] is False
        assert env.m.request_disarm()["error"] == "owner_required"

    def test_retried_until_the_phone_confirms(self, env):
        env.agent.disarm_results = [{"ok": False, "error": "no_forward"},
                                    {"ok": False, "error": "timeout"}]
        env.bus.publish("bt.connected", {"address": OWNER_MAC})
        env.run()
        assert len(env.agent.disarms()) == 1 and env.state()["disarm_pending"] is True
        env.clock.advance(1)
        env.run()
        assert len(env.agent.disarms()) == 1                      # backoff
        env.clock.advance(pg.DISARM_RETRY_MIN_S)
        env.run()
        env.clock.advance(2 * pg.DISARM_RETRY_MIN_S)
        env.run()
        assert len(env.agent.disarms()) == 3 and env.state()["disarm_pending"] is False
        env.clock.advance(600)
        env.run()
        assert len(env.agent.disarms()) == 3

    def test_agent_back_retries_at_once(self, env):
        env.agent.disarm_results = [{"ok": False, "error": "no_forward"}]
        env.bus.publish("bt.connected", {"address": OWNER_MAC})
        env.run()
        env.bus.publish(cpa.TOPIC, {"state": "ok"})
        env.run()
        assert len(env.agent.disarms()) == 2

    def test_given_up_after_the_ttl(self, env):
        env.agent.disarm_results = [{"ok": False, "error": "no_forward"}] * 100
        env.bus.publish("bt.connected", {"address": OWNER_MAC})
        for _ in range(40):
            env.run()
            env.clock.advance(60)
        n = len(env.agent.disarms())
        assert n <= pg.DISARM_TTL_S / pg.DISARM_RETRY_MAX_S + 3
        assert env.state()["disarm_pending"] is False

    def test_phone_toggle_off_ends_it(self, env):
        env.agent.disarm_results = [{"ok": False, "status": 409,
                                     "error": "parking_guard_off"}]
        env.bus.publish("bt.connected", {"address": OWNER_MAC})
        env.run()
        env.clock.advance(120)
        env.run()
        assert len(env.agent.disarms()) == 1

    def test_connected_before_the_module_started(self):
        bus = EventBus()
        bus.publish("bt.connected", {"address": OWNER_MAC})
        agent = FakeAgent()
        m = pg.ParkingGuard(_config(), bus, agent_getter=lambda: agent, notify=lambda *a, **k: 0)
        m.subscribe()
        m.run_once()
        assert agent.disarms() == [("disarm", None)]
        bus2 = EventBus()
        bus2.publish("bt.connected", {"address": OWNER_MAC})
        bus2.publish("bt.disconnected", {"address": OWNER_MAC})
        agent2 = FakeAgent()
        m2 = pg.ParkingGuard(_config(), bus2, agent_getter=lambda: agent2,
                             notify=lambda *a, **k: 0)
        m2.subscribe()
        m2.run_once()
        assert agent2.disarms() == []

    def test_no_io_on_the_bus_thread(self, env):
        env.bus.publish("bt.connected", {"address": OWNER_MAC})
        assert env.agent.calls == []                               # only queued
        worker = threading.Thread(target=env.run)
        worker.start()
        worker.join(5)
        assert env.agent.thread_ids == {worker.ident}


class TestOwners:
    def test_last_device_is_read_once_at_start(self):
        cfg = _config()
        owners, source = pg.owner_macs(cfg)
        assert owners == {OWNER_MAC} and source == "last_bt_device"
        env = Env(cfg)
        # bluetooth persists the newly connected phone as last_bt_device
        cfg["multimedia"]["last_bt_device"] = OTHER_MAC
        env.bus.publish("bt.connected", {"address": OTHER_MAC})
        env.run()
        assert env.agent.disarms() == []

    def test_owner_macs_replace_the_last_device(self):
        cfg = _config(owner_macs=[OTHER_MAC.lower(), "nonsense", 7])
        assert pg.owner_macs(cfg) == ({OTHER_MAC}, "owner_macs")
        env = Env(cfg)
        env.bus.publish("bt.connected", {"address": OWNER_MAC})
        env.run()
        assert env.agent.disarms() == []
        env.bus.publish("bt.connected", {"address": OTHER_MAC})
        env.run()
        assert len(env.agent.disarms()) == 1

    def test_no_owner_known(self):
        cfg = _config()
        cfg["multimedia"]["last_bt_device"] = ""
        env = Env(cfg)
        env.run()
        assert env.state()["owner_known"] is False


# ── Settings: Uzbrój / Rozbrój, state, notification ──────────────────────

class TestCommandsAndState:
    def test_poll_publishes_the_phone_state(self, env):
        env.run()
        st = env.state()
        assert st["state"] == "armed" and st["battery_pct"] == 64 and st["error"] == ""
        assert st["power"] == "unplugged" and st["numbers_n"] == 2
        n = len(env.agent.calls)
        env.clock.advance(10)
        env.run()
        assert len(env.agent.calls) == n                           # every 30 s
        env.clock.advance(pg.POLL_S)
        env.run()
        assert len(env.agent.calls) == n + 1

    def test_no_agent_and_outdated_agent(self):
        env = Env(agent=None)
        env.run()
        assert env.state()["state"] == "unknown" and env.state()["error"] == "no_agent"
        env2 = Env()
        env2.agent.status_result = {"ok": False, "status": 404, "error": "not_found",
                                    "data": {"error": "not_found"}}
        env2.run()
        assert env2.state()["error"] == "agent_outdated"

    def test_garbage_from_the_phone_is_not_trusted(self, env):
        env.agent.view = {"state": "pwned", "battery": "x"}
        env.run()
        assert env.state()["state"] == "unknown" and env.state()["error"] == "agent_error"
        env.agent.view = dict(VIEW, by="<script>", sensor="evil", numbers_n=99,
                              last_event={"kind": "x", "ts": T0})
        env.clock.advance(pg.POLL_S + 1)
        env.run()
        st = env.state()
        assert st["by"] == "" and st["sensor"] == "off" and st["numbers_n"] == 0
        assert st["last_event"] is None

    def test_arm(self, env):
        assert env.m.request_arm() == {"ok": True}
        env.run()
        assert ("arm", None) in env.agent.calls
        assert env.state()["cmd"]["action"] == "arm" and env.state()["cmd"]["ok"] is True

    def test_arm_is_refused_while_the_car_drives(self, env):
        # A moving car armed from the screen would only alarm the driver.
        env.bus.publish("gps.speed", 42.0)
        assert env.m.moving is True
        assert env.m.request_arm() == {"ok": False, "error": "moving"}
        env.run()
        assert not any(c[0] == "arm" for c in env.agent.calls)
        # a stale speed (no fix for a while) does not block arming
        env.clock.advance(pg.SPEED_FRESH_S + 1)
        assert env.m.moving is False and env.m.request_arm() == {"ok": True}
        # walking pace / GPS jitter on a parked car does not count
        env.bus.publish("gps.speed", pg.ARM_MAX_SPEED_KMH - 1)
        assert env.m.moving is False

    @pytest.mark.parametrize("bad", [True, float("nan"), float("inf"), -1.0, 1000.0, "50",
                                     None, {"speed": 50}])
    def test_garbage_speed_is_ignored(self, env, bad):
        env.bus.publish("gps.speed", bad)
        assert env.m.moving is False and env.m.request_arm() == {"ok": True}

    def test_disarm_needs_the_owner_or_a_code(self, env):
        assert env.m.request_disarm() == {"ok": False, "error": "owner_required"}
        for bad in ("12345", "abcdef", 123456, "1234567"):
            assert env.m.request_disarm(bad)["error"] == "bad_request"
        assert env.m.request_disarm("123456") == {"ok": True}
        env.agent.disarm_results = [{"ok": False, "status": 403, "error": "bad_code",
                                     "data": {"error": "bad_code"}}]
        env.run()
        assert ("disarm", "123456") in env.agent.calls
        cmd = env.state()["cmd"]
        assert cmd == {"action": "disarm", "ok": False, "error": "bad_code", "ts": T0}
        # with the owner's phone connected no code is needed
        env.bus.publish("bt.connected", {"address": OWNER_MAC})
        env.run()
        assert env.m.request_disarm() == {"ok": True}

    def test_code_never_reaches_the_bus_or_the_log(self, env, caplog):
        env.m.request_disarm("987654")
        env.run()
        assert "987654" not in json.dumps([env.bus.get_last(t) for t in env.bus.topics()],
                                          default=str)
        assert "987654" not in caplog.text

    def test_one_notification_per_alarm(self, env):
        env.agent.view = dict(VIEW, state="alarm",
                              last_event={"kind": "tilt", "ts": T0 - 60, "value": 1.2,
                                          "logged_only": False})
        env.run()
        for _ in range(3):
            env.clock.advance(pg.POLL_S + 1)
            env.run()
        assert len(env.notes) == 1 and env.notes[0][0] == "Alarm na postoju"
        assert env.notes[0][2]["severity"] == "danger"
        env.agent.view = dict(env.agent.view, last_event={"kind": "power", "ts": T0 + 100,
                                                          "value": None, "logged_only": False})
        env.clock.advance(pg.POLL_S + 1)
        env.run()
        assert len(env.notes) == 2

    def test_never_publishes_alarm_sensor_topics(self, env):
        env.agent.view = dict(VIEW, state="alarm",
                              last_event={"kind": "shake", "ts": T0, "value": 9.0,
                                          "logged_only": False})
        env.bus.publish("bt.connected", {"address": OWNER_MAC})
        env.run()
        env.m.request_arm()
        env.run()
        assert not any(t.startswith("alarm.") for t in env.topics), env.topics

    def test_stop(self, env):
        env.m.start()
        env.m.stop()
        assert env.m.request_arm()["error"] == "stopped"
        assert pg.get_parking_guard() is None


# ── config push: the toggle and the park_* keys ──────────────────────────

def _load_agent():
    old = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location("bcm_agent_for_park_host", AGENT_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = old
    return mod


A = _load_agent()


def _push_config(on=True, **park):
    return {"modules": {"car_phone": True, "car_phone_agent": True, "parking_guard": on},
            "crash_detection": {"sms": {"recipients": [NUM1]}},
            "parking_guard": park,
            "network": {"car_phone": {"agent": {"secret": "3c" * 32}}}}


class TestConfigPush:
    def test_toggle_on_sends_the_park_keys_in_the_agents_canonical_form(self):
        cfg = _push_config(numbers=[NUM1, f" {NUM2} ", NUM1, "601234567"], log_only=False,
                           arm_after_min=4.0, arm_delay_min=99, grace_min="x", tilt_deg=0.75,
                           shake_k=6, home={"lat": 52.123456789, "lon": 21, "radius_m": 20})
        warned = []
        desired = cpa.desired_config(cfg, lambda k, m: warned.append(k))
        assert desired["toggles"]["parking_guard"] is True
        assert desired["park_numbers"] == [NUM1, NUM2]
        assert desired["park_log_only"] is False
        assert desired["park_arm_after_min"] == 4 and desired["park_arm_delay_min"] == 30
        assert desired["park_grace_min"] == 3
        assert desired["park_tilt_deg"] == 0.75 and desired["park_shake_k"] == 6.0
        assert desired["park_home"] == {"lat": 52.123457, "lon": 21.0, "radius_m": 50}
        assert {"park_number:2", "park_arm_delay_min", "park_grace_min",
                "park_home_radius"} <= set(warned)
        norm, err = A.normalize_config(desired, strict=True)
        assert err == "" and A.config_hash(norm) == cpa.config_hash(desired)

    def test_entry_window_is_clamped_and_hashes_like_the_agent(self):
        assert cpa.desired_config(_push_config())["park_entry_s"] == 90
        assert cpa.desired_config(_push_config(entry_s=0))["park_entry_s"] == 0
        warned = []
        desired = cpa.desired_config(_push_config(entry_s=900), lambda k, m: warned.append(k))
        assert desired["park_entry_s"] == 300 and "park_entry_s" in warned
        assert cpa.desired_config(_push_config(entry_s="x"))["park_entry_s"] == 90
        norm, err = A.normalize_config(desired, strict=True)
        assert err == "" and A.config_hash(norm) == cpa.config_hash(desired)

    def test_defaults_are_log_only(self):
        desired = cpa.desired_config(_push_config())
        assert desired["park_log_only"] is True and desired["park_home"] is None
        assert desired["park_numbers"] == []
        assert cpa.desired_config(_push_config(log_only="no"))["park_log_only"] is True

    def test_toggle_off_keeps_the_old_shape(self):
        desired = cpa.desired_config(_push_config(on=False, numbers=[NUM1]))
        assert not any(k.startswith("park_") for k in desired)
        norm, _ = A.normalize_config(desired, strict=True)
        assert A.config_hash(norm) == cpa.config_hash(desired)
        # an agent from before D4 (drops park_* keys) hashes the same
        assert cpa.config_hash({k: v for k, v in desired.items()
                                if not k.startswith("park_")}) == cpa.config_hash(desired)

    def test_bad_home_is_dropped(self):
        for home in ({"lat": 52}, {"lat": 95, "lon": 1, "radius_m": 100}, "home",
                     {"lat": 52, "lon": 21, "radius_m": True}):
            assert cpa.desired_config(_push_config(home=home))["park_home"] is None

    def test_agent_api_validates_before_sending(self):
        mod = cpa.CarPhoneAgent(_push_config(), EventBus(), state_path="/nonexistent/x.json")
        assert mod.park_arm(31)["error"] == "bad_request"
        assert mod.park_arm(True)["error"] == "bad_request"
        assert mod.park_disarm("12345")["error"] == "bad_request"
        assert mod.park_disarm(123456)["error"] == "bad_request"


# ── end to end with the real agent on 127.0.0.1:0 ────────────────────────

class _Runner:
    def __init__(self):
        self.calls = []

    def __call__(self, argv, stdin, timeout):
        self.calls.append(list(argv))
        if argv[0] == "termux-battery-status":
            return 0, json.dumps({"percentage": 80, "plugged": "PLUGGED_USB"}), ""
        if argv[0] == "termux-telephony-deviceinfo":
            return 0, json.dumps({"sim_state": "ready", "network_operator": "26001"}), ""
        raise AssertionError(f"unexpected command {argv}")


@pytest.fixture
def phone(tmp_path):
    runner = _Runner()
    agent = A.Agent(str(tmp_path / "phone"), runner=runner, clock=time.monotonic,
                    wall=time.time, localtime=time.gmtime, spawn=lambda argv: None)
    server = A.make_server(agent, 0)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                              daemon=True)
    thread.start()
    yield SimpleNamespace(agent=agent, port=server.server_address[1], runner=runner,
                          dir=tmp_path / "phone")
    server.shutdown()
    server.server_close()


def _paired_module(tmp_path, bus, phone, config):
    mod = cpa.CarPhoneAgent(config, bus, state_path=str(tmp_path / "bcm" / "cpa.json"))
    bus.publish("net.car_phone", {"state": "connected", "forwards": {
        "agent": {"local": phone.port, "remote": 8765, "ok": True, "error": ""}}})
    (phone.dir / "PAIRING").write_text("4815162342\n")
    assert mod.request_pair("4815162342", False)["ok"]
    mod.cycle()
    mod._next_poll = 0.0
    mod.cycle()
    return mod


class TestEndToEnd:
    def test_owner_connection_disarms_the_real_agent(self, tmp_path, phone):
        bus = EventBus()
        config = _push_config(numbers=[NUM1], log_only=False)
        config["multimedia"] = {"last_bt_device": OWNER_MAC}
        mod = _paired_module(tmp_path, bus, phone, config)
        assert phone.agent.config["toggles"]["parking_guard"] is True
        assert phone.agent.config["park_numbers"] == [NUM1]
        assert mod.state["reason"] == ""
        # the phone armed itself while BCM was off
        with phone.agent._lock:
            phone.agent.park._arm_locked("power", 0, False, time.time())
            phone.agent.park._arm_now_locked(time.time())
        guard = pg.ParkingGuard(config, bus, agent_getter=lambda: mod,
                                notify=lambda *a, **k: None)
        guard.subscribe()
        guard.run_once()
        assert bus.get_last(pg.TOPIC_STATE)[0]["state"] == "armed"
        # an unsigned disarm (anyone on the forward port) is refused
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", phone.port, timeout=3)
        conn.request("POST", "/v1/park/disarm", body=b"{}",
                     headers={"Content-Type": "application/json"})
        assert conn.getresponse().status == 401
        conn.close()
        assert phone.agent.park.view()["state"] == "armed"
        bus.publish("bt.connected", {"address": OWNER_MAC})
        guard.run_once()
        v = phone.agent.park.view()
        assert v["state"] == "disarmed" and v["by"] == "owner_bt"
        assert bus.get_last(pg.TOPIC_STATE)[0]["state"] == "disarmed"
        assert not any(c[0] == "termux-sms-send" for c in phone.runner.calls)

    def test_an_agent_before_1_2_0_is_agent_outdated(self, tmp_path, phone, monkeypatch):
        monkeypatch.setattr(A, "VERSION", "1.1.0")
        orig = phone.agent.put_config

        def put_110(obj):
            status, out = orig({k: v for k, v in obj.items() if not k.startswith("park_")})
            if status == 200:
                cfg = phone.agent.config
                out = dict(out, config_hash=cpa.config_hash(
                    {k: v for k, v in cfg.items() if not k.startswith("park_")}))
            return status, out
        monkeypatch.setattr(phone.agent, "put_config", put_110)
        bus = EventBus()
        config = _push_config(numbers=[NUM1])
        mod = _paired_module(tmp_path, bus, phone, config)
        assert bus.get_last(cpa.TOPIC)[0]["reason"] == "agent_outdated"
        assert mod.health_facts()["config_hash"] != cpa.config_hash(
            cpa.desired_config(config))
        assert phone.agent.config["park_numbers"] == []          # it never got them


# ── the dashboard summary and the routes ─────────────────────────────────

class TestSummary:
    def test_none_without_the_module(self):
        assert wv._parking_guard_summary(None) is None
        assert wv._parking_guard_summary("x") is None

    def test_whitelists(self, env):
        env.run()
        out = wv._parking_guard_summary(env.state())
        assert out["state"] == "armed" and out["battery_pct"] == 64
        bad = dict(env.state(), state="<img>", by="x", sensor="y", error="z",
                   battery_pct=101, numbers_n=-1, alarms_today="3",
                   last_event={"kind": "tilt", "ts": float("nan")},
                   cmd={"action": "rm", "ok": True})
        out = wv._parking_guard_summary(bad)
        assert out["state"] == "unknown" and out["by"] == "" and out["sensor"] == "off"
        assert out["error"] == "" and out["battery_pct"] is None and out["numbers_n"] == 0
        assert out["alarms_today"] == 0 and out["last_event"] is None and out["cmd"] is None


@pytest.fixture
def web(monkeypatch, tmp_path, env):
    def refuse(*a, **kw):
        raise AssertionError("no subprocess from web_viewer here")
    monkeypatch.setattr(wv, "subprocess", SimpleNamespace(run=refuse, Popen=refuse))
    base = tmp_path / "bcm_config_test.yaml"
    shutil.copy(REPO / "config" / "bcm_config_test.yaml", base)
    cfg = BCMConfig(config_path=str(base), platform_override="x86",
                    local_path=str(tmp_path / "local.yaml"), env={})
    viewer = WebViewer(host="127.0.0.1", port=5099, event_bus=env.bus, config=cfg)
    holder = {"module": env.m}
    monkeypatch.setattr(pg, "get_parking_guard", lambda: holder["module"])
    return SimpleNamespace(env=env, cfg=cfg, viewer=viewer, holder=holder,
                           client=viewer._build_app().test_client())


def _as(addr):
    return {"environ_base": {"REMOTE_ADDR": addr}}


class TestRoutes:
    def test_arm(self, web):
        res = web.client.post("/api/parking_guard/arm", json={})
        assert res.status_code == 200 and res.get_json() == {"ok": True}
        web.env.run()
        assert ("arm", None) in web.env.agent.calls

    def test_arm_while_driving_is_refused(self, web):
        web.env.bus.publish("gps.speed", 60.0)
        res = web.client.post("/api/parking_guard/arm", json={})
        assert res.status_code == 409 and res.get_json()["error"] == "moving"
        web.env.run()
        assert not any(c[0] == "arm" for c in web.env.agent.calls)

    def test_disarm_with_a_code(self, web):
        res = web.client.post("/api/parking_guard/disarm", json={"code": "246810"})
        assert res.status_code == 200
        web.env.run()
        assert ("disarm", "246810") in web.env.agent.calls

    def test_disarm_without_owner_or_code(self, web):
        res = web.client.post("/api/parking_guard/disarm", json={})
        assert res.status_code == 409 and res.get_json()["error"] == "owner_required"
        for body in ({"code": "12345"}, {"code": 246810}, {"code": "246810", "x": 1}):
            web.viewer._crash_last.clear()
            res = web.client.post("/api/parking_guard/disarm", json=body)
            assert res.status_code == 400

    @pytest.mark.parametrize("addr", ["192.168.1.50", "10.0.0.5", "::ffff:192.168.1.5"])
    @pytest.mark.parametrize("route", ["/api/parking_guard/arm", "/api/parking_guard/disarm"])
    def test_loopback_only_even_with_full_remote_access(self, web, route, addr):
        web.cfg.set("dashboard.remote_access", "full")
        client = web.viewer._build_app().test_client()
        res = client.post(route, json={"code": "246810"}, **_as(addr))
        assert res.status_code == 403 and res.get_json()["error"] == "forbidden"
        web.env.run()
        assert not any(c[0] in ("arm", "disarm") for c in web.env.agent.calls)

    def test_json_body_required_and_rate_limit(self, web):
        res = web.client.post("/api/parking_guard/arm", data="x", content_type="text/plain")
        assert res.status_code == 400
        assert web.client.post("/api/parking_guard/arm", json={}).status_code == 200
        res = web.client.post("/api/parking_guard/arm", json={})
        assert res.status_code == 429 and int(res.headers["Retry-After"]) >= 1

    def test_not_running(self, web):
        web.holder["module"] = None
        res = web.client.post("/api/parking_guard/arm", json={})
        assert res.status_code == 409 and res.get_json()["error"] == "not_running"

    def test_payload(self, web):
        web.env.run()
        data = web.client.get("/api/data").get_json()
        assert data["parking_guard"]["state"] == "armed"
