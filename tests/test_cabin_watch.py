"""BCM's side of the cabin watch (plan I): src/safety/cabin_watch.py, the
cabin watch part of src/network/car_phone_agent.py (config push, view
parser, API) and the Settings payload sanitiser.

Fakes only: a fake agent API, a synchronous EventBus, a fake clock; the
end-to-end class runs the REAL Termux agent on 127.0.0.1:0 (no Pillow, a
runner that refuses unexpected commands, no camera thread). Nothing reaches
a phone, adb, a camera or the network.

Covers: the poll on the module's worker, park.cabin_state on change, the
park.cabin_event history (once per event and outcome, also events from
while BCM was off), never alarm.sensor.* and no notification, the error
mapping (no agent, agent older than 1.3.0, no answer, garbage), the view
parser, the cabin_* config push in the agent's canonical form and its hash
compatibility with older agents, the door-signal API, the summary
sanitiser and the dashboard payload.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core.event_bus import EventBus
from src.dashboard import web_viewer as wv
from src.network import car_phone_agent as cpa
from src.safety import cabin_watch as cw

REPO = Path(__file__).resolve().parent.parent
AGENT_PATH = REPO / "tools" / "car_phone" / "termux" / "bcm_agent.py"
NUM1 = "+48601234567"
T0 = 1_763_000_000


def _load_agent():
    old = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location("bcm_agent_cabin_host", AGENT_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = old
    return mod


A = _load_agent()

EVENT = {"id": "0123456789abcdef", "ts": T0, "reasons": ["light", "shake"], "weak": False,
         "photos": 3, "outcome": "pending", "verdict": "change", "changed_pct": 12.3,
         "ref": "ref", "camera": "ok"}
VIEW = {"state": "pending", "camera": "ok", "light_sensor": "ok", "lux": 40.0, "pillow": True,
        "log_only": False, "entry_until": T0 + 60, "photos_n": 3, "photos_mb": 2.1,
        "events_today": 1, "last_event": dict(EVENT), "events": [dict(EVENT)]}


class Clock:
    def __init__(self):
        self.t = 100.0

    def advance(self, s):
        self.t += s


class FakeAgent:
    def __init__(self):
        self.calls = []
        self.view = json.loads(json.dumps(VIEW))
        self.result = None
        self.thread_ids = set()

    def cabin_status(self):
        self.calls.append("status")
        self.thread_ids.add(threading.get_ident())
        if self.result is not None:
            return dict(self.result)
        return {"ok": True, "status": 200, "data": json.loads(json.dumps(self.view)),
                "error": "", "detail": ""}


class Env:
    def __init__(self):
        self.bus = EventBus()
        self.clock = Clock()
        self.agent = FakeAgent()
        self.holder = {"agent": self.agent}
        self.published = []
        orig = self.bus.publish

        def spy(topic, value, *a, **kw):
            self.published.append((topic, value))
            return orig(topic, value, *a, **kw)
        self.bus.publish = spy
        self.m = cw.CabinWatch({}, self.bus, agent_getter=lambda: self.holder["agent"],
                               clock=lambda: self.clock.t)

    def run(self):
        return self.m.step()

    def state(self):
        return self.bus.get_last(cw.TOPIC_STATE)[0]

    def events(self):
        return [v for t, v in self.published if t == cw.TOPIC_EVENT]


@pytest.fixture
def env():
    return Env()


# ── the module ───────────────────────────────────────────────────────────

class TestModule:
    def test_poll_publishes_state_and_history(self, env):
        env.run()
        st = env.state()
        assert st["state"] == "pending" and st["photos_n"] == 3 and st["error"] == ""
        assert st["last_event"]["reasons"] == ["light", "shake"]
        assert env.events() == [EVENT]
        # the same event and outcome again: no second history entry
        env.clock.advance(cw.POLL_S)
        env.run()
        assert len(env.events()) == 1
        # the outcome changes: one more entry; a new event: one more
        env.agent.view["events"][0]["outcome"] = "alarm"
        new = dict(EVENT, id="fedcba9876543210", outcome="owner", photos=0)
        env.agent.view["events"].append(new)
        env.clock.advance(cw.POLL_S)
        env.run()
        assert [e["outcome"] for e in env.events()] == ["pending", "alarm", "owner"]

    def test_polls_every_30_s_only(self, env):
        assert env.run() == pytest.approx(cw.POLL_S)
        env.clock.advance(10)
        env.run()
        assert env.agent.calls == ["status"]
        env.clock.advance(20)
        env.run()
        assert env.agent.calls == ["status", "status"]

    def test_never_the_siren_topic_and_no_notification(self, env):
        env.run()
        topics = {t for t, _v in env.published}
        assert topics == {cw.TOPIC_STATE, cw.TOPIC_EVENT}
        assert not any(t.startswith("alarm.") or t.startswith("notification") for t in topics)

    def test_publishes_only_on_change(self, env):
        env.run()
        n = len(env.published)
        env.clock.advance(cw.POLL_S)
        env.run()
        assert len(env.published) == n

    @pytest.mark.parametrize("result,error", [
        ({"ok": False, "error": "not_found"}, "agent_outdated"),
        ({"ok": False, "error": "timeout"}, "no_answer"),
        ({"ok": False, "error": "no_forward"}, "no_answer"),
        ({"ok": False, "error": "bad_signature"}, "agent_error"),
        ({"ok": True, "data": {"state": "<img>"}}, "agent_error"),
        ({"ok": True, "data": "x"}, "agent_error"),
    ])
    def test_errors(self, env, result, error):
        env.agent.result = result
        env.run()
        st = env.state()
        assert st["error"] == error and st["state"] == "unknown"
        assert env.events() == []

    def test_no_agent_and_backoff(self, env):
        asked = []
        env.m._agent_getter = lambda: asked.append(env.clock.t) or env.holder["agent"]
        env.holder["agent"] = None
        for _ in range(12):
            env.clock.advance(env.run())
        assert env.state()["error"] == "no_agent"
        gaps = [round(b - a) for a, b in zip(asked, asked[1:])]
        assert gaps[:5] == [10, 20, 40, 80, 120]           # 10 s doubling to 2 min
        assert env.m._poll_delay == cw.POLL_FAIL_MAX_S
        env.holder["agent"] = env.agent
        env.clock.advance(cw.POLL_FAIL_MAX_S)
        env.run()
        assert env.state()["error"] == "" and env.state()["state"] == "pending"

    def test_the_last_known_state_survives_a_failed_poll(self, env):
        env.run()
        env.agent.result = {"ok": False, "error": "timeout"}
        env.clock.advance(cw.POLL_S)
        env.run()
        st = env.state()
        assert st["state"] == "pending" and st["error"] == "no_answer"

    def test_worker_thread_only_and_start_does_no_io(self, env):
        env.m.start()
        try:
            deadline = time.monotonic() + 5
            while not env.agent.calls and time.monotonic() < deadline:
                time.sleep(0.01)
            assert env.agent.calls
            assert threading.get_ident() not in env.agent.thread_ids
        finally:
            env.m.stop()
        assert env.m._stop.is_set()

    def test_shutdown_stops(self, env):
        env.m.start()
        env.bus.publish("power.shutting_down", True)
        assert env.m._stop.is_set()
        env.m._thread.join(timeout=5)
        assert not env.m._thread.is_alive()

    def test_entry_point_registers_and_stop_clears(self, monkeypatch):
        bus = EventBus()
        monkeypatch.setattr(cpa, "get_agent", lambda: None)
        mod = cw.start_cabin_watch({}, bus)
        try:
            assert cw.get_cabin_watch() is mod
        finally:
            mod.stop()
        assert cw.get_cabin_watch() is None


# ── the view parser ──────────────────────────────────────────────────────

class TestParseView:
    def test_good(self):
        out = cpa.parse_cabin_view(json.loads(json.dumps(VIEW)))
        assert out["state"] == "pending" and out["last_event"] == EVENT
        assert out["events"] == [EVENT] and out["entry_until"] == T0 + 60

    def test_garbage_is_dropped_field_by_field(self):
        bad = dict(VIEW, camera="<b>", light_sensor=1, lux=float("nan"), pillow="yes",
                   photos_n=-1, photos_mb="2", events_today=True, entry_until=5,
                   last_event=dict(EVENT, id="../../x"),
                   events=[dict(EVENT, outcome="boom"), dict(EVENT, reasons=["evil", "door"],
                                                             photos=99, changed_pct=500,
                                                             verdict="x", ref="y", camera="z"),
                           "x"] + [dict(EVENT)] * 10)
        out = cpa.parse_cabin_view(bad)
        assert out["camera"] == "unknown" and out["light_sensor"] == "unknown"
        assert out["lux"] is None and out["pillow"] is None and out["photos_n"] == 0
        assert out["photos_mb"] is None and out["events_today"] == 0
        assert out["entry_until"] is None and out["last_event"] is None
        assert len(out["events"]) == 5                 # at most the last 5
        assert cpa.parse_cabin_view(dict(VIEW, state="armed")) is None
        assert cpa.parse_cabin_view(None) is None
        ev = cpa.parse_cabin_view(dict(VIEW, events=[dict(
            EVENT, reasons=["evil", "door"], photos=99, changed_pct=500, verdict="x", ref="y",
            camera="z")]))["events"][0]
        assert ev["reasons"] == ["door"] and ev["photos"] == 0 and ev["changed_pct"] is None
        assert ev["verdict"] is None and ev["ref"] is None and ev["camera"] == ""


# ── the config push ──────────────────────────────────────────────────────

def _push_config(on=True, park=True, **cabin):
    return {"modules": {"car_phone": True, "car_phone_agent": True, "parking_guard": park,
                        "cabin_watch": on},
            "crash_detection": {"sms": {"recipients": [NUM1]}},
            "parking_guard": {"numbers": [NUM1]},
            "cabin_watch": cabin,
            "network": {"car_phone": {"agent": {"secret": "3c" * 32}}}}


class TestConfigPush:
    def test_defaults_in_the_agents_canonical_form(self):
        desired = cpa.desired_config(_push_config())
        assert desired["toggles"]["cabin_watch"] is True
        assert desired["cabin_entry_s"] == 60 and desired["cabin_diff_pct"] == 3.0
        assert desired["cabin_mask"] == []
        norm, err = A.normalize_config(desired, strict=True)
        assert err == "" and A.config_hash(norm) == cpa.config_hash(desired)

    def test_values_are_clamped_and_hash_like_the_agent(self):
        warned = []
        desired = cpa.desired_config(_push_config(entry_s=30, diff_pct=2.555,
                                                  mask=[[0, 0, 15, 100], [85, 0, 100, 100]]),
                                     lambda k, m: warned.append(k))
        assert desired["cabin_entry_s"] == 45 and "cabin_entry_s" in warned
        assert desired["cabin_diff_pct"] == 2.56
        assert desired["cabin_mask"] == [[0, 0, 15, 100], [85, 0, 100, 100]]
        norm, err = A.normalize_config(desired, strict=True)
        assert err == "" and A.config_hash(norm) == cpa.config_hash(desired)
        assert cpa.desired_config(_push_config(entry_s=99))["cabin_entry_s"] == 60
        assert cpa.desired_config(_push_config(diff_pct="x"))["cabin_diff_pct"] == 3.0

    def test_light_thresholds_for_the_calibration_week(self):
        desired = cpa.desired_config(_push_config())
        assert desired["cabin_light_ratio"] == 5.0 and desired["cabin_light_lux"] == 5.0
        warned = []
        desired = cpa.desired_config(_push_config(light_ratio=3.25, light_lux=0.2),
                                     lambda k, m: warned.append(k))
        assert desired["cabin_light_ratio"] == 3.25 and desired["cabin_light_lux"] == 1.0
        assert warned == ["cabin_light_lux"]                       # clamped into 1..1000
        norm, err = A.normalize_config(desired, strict=True)
        assert err == "" and A.config_hash(norm) == cpa.config_hash(desired)
        assert norm["cabin_light_ratio"] == 3.25 and norm["cabin_light_lux"] == 1.0
        for bad in (True, "5", float("nan"), None):
            out = cpa.desired_config(_push_config(light_ratio=bad, light_lux=bad))
            assert out["cabin_light_ratio"] == 5.0 and out["cabin_light_lux"] == 5.0
        assert cpa.desired_config(_push_config(light_ratio=99))["cabin_light_ratio"] == 50.0

    @pytest.mark.parametrize("mask", ["left", [[10, 0, 5, 100]], [[0, 0, 101, 100]],
                                      [[0, 0, 10]], [[0, 0, 1, 1]] * 5, [[0, 0, 1.5, 1]],
                                      [[True, 0, 1, 1]]])
    def test_a_bad_mask_is_dropped_with_a_warning(self, mask):
        warned = []
        desired = cpa.desired_config(_push_config(mask=mask), lambda k, m: warned.append(k))
        assert desired["cabin_mask"] == [] and "cabin_mask" in warned
        norm, err = A.normalize_config(desired, strict=True)
        assert err == "" and A.config_hash(norm) == cpa.config_hash(desired)

    def test_toggle_off_keeps_the_old_shape(self):
        desired = cpa.desired_config(_push_config(on=False, entry_s=50))
        assert not any(k.startswith("cabin_") for k in desired)
        norm, _ = A.normalize_config(desired, strict=True)
        assert A.config_hash(norm) == cpa.config_hash(desired)
        # an agent from before plan I (1.2.0, drops cabin_* keys) hashes the same
        assert cpa.config_hash({k: v for k, v in desired.items()
                                if not k.startswith("cabin_")}) == cpa.config_hash(desired)

    def test_door_signal_api_validates_before_sending(self):
        mod = cpa.CarPhoneAgent(_push_config(), EventBus(), state_path="/nonexistent/x.json")
        assert mod.park_event("window")["error"] == "bad_request"
        assert mod.park_event(None)["error"] == "bad_request"


# ── end to end with the real agent on 127.0.0.1:0 ────────────────────────

class _Runner:
    def __init__(self):
        self.calls = []

    def __call__(self, argv, stdin, timeout):
        self.calls.append(list(argv))
        if argv[0] == "termux-battery-status":
            return 0, json.dumps({"percentage": 80, "plugged": "PLUGGED_USB",
                                  "temperature": 25.0}), ""
        if argv[0] == "termux-telephony-deviceinfo":
            return 0, json.dumps({"sim_state": "ready", "network_operator": "26001"}), ""
        raise AssertionError(f"unexpected command {argv}")


@pytest.fixture
def phone(tmp_path):
    runner = _Runner()
    agent = A.Agent(str(tmp_path / "phone"), runner=runner, clock=time.monotonic,
                    wall=time.time, localtime=time.gmtime, spawn=lambda argv: None,
                    pillow=None)
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
    def test_door_signal_and_the_history_from_the_real_agent(self, tmp_path, phone):
        bus = EventBus()
        config = _push_config(entry_s=50)
        mod = _paired_module(tmp_path, bus, phone, config)
        assert phone.agent.config["toggles"]["cabin_watch"] is True
        assert phone.agent.config["cabin_entry_s"] == 50
        assert mod.state["reason"] == ""
        clock = Clock()
        watch = cw.CabinWatch(config, bus, agent_getter=lambda: mod, clock=lambda: clock.t)
        watch.step()
        assert bus.get_last(cw.TOPIC_STATE)[0]["state"] == "idle"     # not armed: no camera
        with phone.agent._lock:
            phone.agent.park._arm_now_locked(time.time())
        res = mod.park_event("door")
        assert res["ok"] and res["data"]["accepted"] is True
        clock.advance(cw.POLL_S)
        watch.step()
        st = bus.get_last(cw.TOPIC_STATE)[0]
        assert st["state"] == "pending" and st["last_event"]["reasons"] == ["door"]
        assert st["pillow"] is False
        hist = bus.get_last(cw.TOPIC_EVENT)[0]
        assert hist["outcome"] == "pending" and hist["reasons"] == ["door"]
        # the door signal never disarmed anything
        assert phone.agent.park.st["state"] == "armed"
        # the summary for the Settings row
        out = wv._cabin_watch_summary(st)
        assert out["state"] == "pending" and out["last_event"]["reasons"] == ["door"]
        assert not any(c[0] in ("termux-camera-photo", "su") for c in phone.runner.calls)

    def test_an_agent_before_1_3_0_is_agent_outdated(self, tmp_path, phone, monkeypatch):
        monkeypatch.setattr(A, "VERSION", "1.2.0")
        orig = phone.agent.put_config

        def put_120(obj):
            status, out = orig({k: v for k, v in obj.items() if not k.startswith("cabin_")})
            if status == 200:
                cfg = phone.agent.config
                out = dict(out, config_hash=cpa.config_hash(
                    {k: v for k, v in cfg.items() if not k.startswith("cabin_")}))
            return status, out
        monkeypatch.setattr(phone.agent, "put_config", put_120)
        bus = EventBus()
        _paired_module(tmp_path, bus, phone, _push_config(entry_s=50))
        assert bus.get_last(cpa.TOPIC)[0]["reason"] == "agent_outdated"
        assert phone.agent.config["cabin_entry_s"] == 60          # it never got it


# ── the dashboard summary ────────────────────────────────────────────────

class TestSummary:
    def test_none_without_the_module(self):
        assert wv._cabin_watch_summary(None) is None
        assert wv._cabin_watch_summary("x") is None

    def test_whitelists(self, env):
        env.run()
        out = wv._cabin_watch_summary(env.state())
        assert out["state"] == "pending" and out["photos_n"] == 3
        assert out["last_event"]["verdict"] == "change"
        assert "id" not in out["last_event"]                 # nothing the row does not need
        bad = dict(env.state(), state="<img>", camera="x", light_sensor="y", error="z",
                   lux=-1, pillow="yes", log_only=1, photos_n=-1, photos_mb=float("inf"),
                   events_today="3", entry_until=float("nan"),
                   last_event=dict(env.state()["last_event"], outcome="rm -rf"))
        out = wv._cabin_watch_summary(bad)
        assert out["state"] == "unknown" and out["camera"] == "unknown"
        assert out["light_sensor"] == "unknown" and out["error"] == ""
        assert out["lux"] is None and out["pillow"] is None and out["log_only"] is None
        assert out["photos_n"] == 0 and out["photos_mb"] is None and out["events_today"] == 0
        assert out["entry_until"] is None and out["last_event"] is None
        ev = wv._cabin_watch_summary(dict(env.state(), last_event=dict(
            env.state()["last_event"], reasons=["<x>", "light"], photos="3",
            changed_pct=float("nan"), verdict="v", ref="r", camera="c")))["last_event"]
        assert ev["reasons"] == ["light"] and ev["photos"] == 0 and ev["changed_pct"] is None
        assert ev["verdict"] is None and ev["ref"] is None and ev["camera"] == ""

    def test_in_the_dashboard_payload(self, env, tmp_path):
        from src.core.config import BCMConfig
        from src.dashboard.web_viewer import WebViewer
        cfg = BCMConfig(config_path=str(REPO / "config" / "bcm_config_test.yaml"),
                        platform_override="x86", local_path=None, env={})
        viewer = WebViewer(host="127.0.0.1", port=5099, event_bus=env.bus, config=cfg)
        client = viewer._build_app().test_client()
        assert client.get("/api/data").get_json()["cabin_watch"] is None
        env.run()
        data = client.get("/api/data").get_json()
        assert data["cabin_watch"]["state"] == "pending"
        assert data["parking_guard"] is None
