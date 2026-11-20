"""„Zadzwoń 112” in the crash window (src/safety/call112.py, plan H).

No real call anywhere: the Bluetooth manager and the car phone's agent are
fakes that only record; the worker is driven by hand (run_once) with fake
clocks; the event is saved under tmp_path.

Covers: the pure path choice (no mic / no modem / no network / a call in
progress / an unhealthy agent / test mode), the window (opened by
crash.detected, closed after window_min, by the driver or when the car
drives on, restored after a restart), nothing ever dials by itself, path A
through the Bluetooth manager's internal entry point (bt.dial_result error
or no confirmation in 10 s ⇒ path B offered at once, a late confirmation,
the hang-up), path B through the agent (refusals, a lost answer looked up,
mute of BCM's media), the 60 s limit with its one fallback exemption, test
mode never dialling 112, the routes (loopback only also with remote_access
full, the body's number ignored, 429, the window, module off ⇒ 409), the
dashboard summary, the steering-wheel hang-up ignored during a 112 call,
the Bluetooth manager's entry point and the catalog / config wiring.
"""

from __future__ import annotations

import json
import logging
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core import modules_catalog as mc
from src.core.config import BCMConfig
from src.core.event_bus import EventBus
from src.dashboard import web_viewer as wv
from src.dashboard.web_viewer import WebViewer
from src.input.input_bridge import InputBridge
from src.multimedia import bluetooth as bt
from src.network import car_phone_agent as cpa
from src.safety import call112 as c112

REPO = Path(__file__).resolve().parent.parent
EID = "0123456789abcdef" * 2
EID2 = "fedcba9876543210" * 2
WALL0 = 1_763_000_000.0
TEST_NUM = "+48601234599"


# ── fakes ──────────────────────────────────────────────────────────────────

class Clock:
    def __init__(self):
        self.mono = 1000.0
        self.wall = WALL0

    def advance(self, s):
        self.mono += s
        self.wall += s


class FakeBT:
    """BluetoothManager stand-in: records, never dials anything."""

    def __init__(self, bus):
        self.bus = bus
        self.facts = {"connected": True, "voice_modem": True, "call_state": "idle"}
        self.dialled = []
        self.hangups = 0
        self.accept = True

    def call112_facts(self):
        return dict(self.facts)

    def dial_call112(self, number):
        self.dialled.append(number)
        return self.accept

    def hangup_call112(self):
        self.hangups += 1
        return True


class FakeAgent:
    """CarPhoneAgent stand-in (its API and its no-I/O accessors)."""

    def __init__(self):
        self.state = {"state": "ok", "paired": True}
        self.facts = {"call112_capable": True, "call112_mode": "real"}
        self.calls = []
        self.event_ids = []          # the event id each call112 / mark carried
        self.call_answer = None
        self.status_answer = {"ok": False, "status": None, "data": None, "error": "connect"}
        self.hangup_answer = {"ok": True, "status": 200, "data": {}, "error": ""}

    def health_facts(self):
        return dict(self.facts)

    def call112(self, mode, event_id):
        self.calls.append(("call112", mode))
        self.event_ids.append(event_id)
        if self.call_answer is not None:
            return self.call_answer
        return {"ok": True, "status": 200, "error": "",
                "data": {"seq": 1, "state": "queued", "mode": mode, "error": "", "final": False,
                         "number": "112", "requested_ts": int(WALL0)}}

    def call112_status(self):
        self.calls.append(("status",))
        return self.status_answer

    def call112_hangup(self):
        self.calls.append(("hangup",))
        return self.hangup_answer

    def call112_mark(self, event_id):
        self.calls.append(("mark",))
        self.event_ids.append(event_id)
        return {"ok": True, "status": 200, "data": {"ok": True}, "error": ""}


def _view(state, seq=1, **kw):
    v = {"seq": seq, "state": state, "mode": "real", "error": "", "final": False,
         "number": "112", "requested_ts": int(WALL0), "placed_ts": None, "offhook_ts": None,
         "ended_ts": None}
    v.update(kw)
    return {"ok": True, "status": 200, "error": "", "data": {"call": v, "call_state": None}}


def _cfg(**call112):
    block = {"test_mode": False}
    block.update(call112)
    return {"crash_detection": {},
            "safety": {"call112": block,
                       "vehicle": {"label": "Alfa Romeo 156", "colour": "czerwona",
                                   "plate": "wx 12345"}}}


@pytest.fixture
def env(tmp_path):
    bus = EventBus()
    clock = Clock()
    fbt = FakeBT(bus)
    agent = FakeAgent()
    holder = {"agent": agent}
    cfg = _cfg()
    # path A prerequisites on the bus
    bus.publish("bt.phone_status", {"registration": "registered"})
    bus.publish("audio.mic_state", {"state": "ok", "source": "usb", "aec": False})
    bus.publish("bt.call_state", "idle")
    m = c112.Call112(cfg, bus, bt_manager=fbt, agent_getter=lambda: holder["agent"],
                     clock=lambda: clock.mono, wall_clock=lambda: clock.wall,
                     state_path=str(tmp_path / "call112.json"))
    m.subscribe()
    published = []
    bus.subscribe(c112.TOPIC_STATE, lambda t, v, ts: published.append(v))
    mutes = []
    bus.subscribe("input.mute", lambda t, v, ts: mutes.append(v))
    return SimpleNamespace(bus=bus, clock=clock, bt=fbt, agent=agent, holder=holder, cfg=cfg,
                           m=m, published=published, mutes=mutes, path=tmp_path / "call112.json")


def _crash(env, eid=EID, **kw):
    ev = {"event_id": eid, "ts": env.clock.wall, "source": "accel", "sms_eligible": True,
          "lat": 52.229676, "lon": 21.012229, "fix_age_s": 2.0, "sats": 9,
          "speed_before_kmh": 72.4, "dv_kmh": 45.0, "peak_g": 6.1, "heading": 270.0}
    ev.update(kw)
    env.bus.publish("crash.detected", ev)
    env.m.run_once()


def _last(env):
    return env.m.payload()


def _origin(ok, error=None):
    return {"ok": ok, "path": "hfp", "error": error, "ts": WALL0, "origin": "call112"}


# ── the pure path choice ───────────────────────────────────────────────────

HFP_OK = {"running": True, "connected": True, "voice_modem": True, "call_state": "idle",
          "bus_call_state": "idle", "registration": "registered", "mic": "ok"}
CAR_OK = {"running": True, "state": "ok", "paired": True, "capable": True, "mode": "real"}


@pytest.mark.parametrize("hfp, car, expected, reasons", [
    ({}, {}, "hfp", ("", "")),
    ({"mic": "none"}, {}, "car_phone", ("no_mic", "")),        # never without a microphone
    ({"mic": "error"}, {}, "car_phone", ("no_mic", "")),
    ({"mic": None}, {}, "car_phone", ("no_mic", "")),
    ({"voice_modem": False}, {}, "car_phone", ("no_modem", "")),
    ({"connected": False}, {}, "car_phone", ("not_connected", "")),
    ({"registration": "searching"}, {}, "car_phone", ("no_network", "")),
    ({"registration": "denied"}, {}, "car_phone", ("no_network", "")),
    ({"registration": None}, {}, "car_phone", ("no_network", "")),       # no phone_status
    ({"registration": "roaming"}, {}, "hfp", ("", "")),
    ({"call_state": "active"}, {}, "car_phone", ("call_in_progress", "")),
    ({"bus_call_state": "incoming"}, {}, "car_phone", ("call_in_progress", "")),
    ({"running": False}, {}, "car_phone", ("off", "")),
    ({"mic": "none"}, {"state": "error"}, "none", ("no_mic", "not_ready")),
    ({"mic": "none"}, {"paired": False}, "none", ("no_mic", "not_ready")),
    ({"mic": "none"}, {"capable": False}, "none", ("no_mic", "not_capable")),
    ({"mic": "none"}, {"capable": None}, "none", ("no_mic", "not_capable")),
    ({"mic": "none"}, {"mode": "test"}, "none", ("no_mic", "mode_mismatch")),
    ({"mic": "none"}, {"running": False}, "none", ("no_mic", "not_running")),
])
def test_path_matrix(hfp, car, expected, reasons):
    path, why = c112.choose_path(c112.PATHS, False, "", dict(HFP_OK, **hfp), dict(CAR_OK, **car))
    assert path == expected
    assert (why["hfp"], why["car_phone"]) == reasons


def test_path_order_exclusion_and_test_mode():
    assert c112.choose_path(("car_phone", "hfp"), False, "", HFP_OK, CAR_OK)[0] == "car_phone"
    path, why = c112.choose_path(("car_phone",), False, "", HFP_OK, CAR_OK)
    assert path == "car_phone" and why["hfp"] == "off"
    assert c112.choose_path((), False, "", HFP_OK, CAR_OK)[0] == "none"
    assert c112.choose_path(c112.PATHS, False, "", HFP_OK, CAR_OK, exclude=("hfp",))[0] \
        == "car_phone"
    # test mode without a number: nothing can be dialled at all
    path, why = c112.choose_path(c112.PATHS, True, "", HFP_OK, dict(CAR_OK, mode="test"))
    assert path == "none" and why == {"hfp": "no_number", "car_phone": "no_number"}
    # test mode with a number: the agent must be in test mode too
    assert c112.choose_path(c112.PATHS, True, TEST_NUM, dict(HFP_OK, mic="none"),
                            CAR_OK)[0] == "none"
    assert c112.choose_path(c112.PATHS, True, TEST_NUM, dict(HFP_OK, mic="none"),
                            dict(CAR_OK, mode="test"))[0] == "car_phone"
    assert c112.choose_path(c112.PATHS, False, "", None, None)[0] == "none"


# ── configuration ──────────────────────────────────────────────────────────

class TestConfig:
    def test_defaults_and_clamps(self):
        c = c112.load_config({})
        assert (c.paths, c.hold_ms, c.arm_delay_ms, c.window_min, c.test_mode,
                c.test_number) == (("hfp", "car_phone"), 2000, 700, 30, False, "")
        c = c112.load_config({"safety": {"call112": {
            "paths": ["car_phone", "x", "car_phone"], "hold_ms": 50, "arm_delay_ms": 9999,
            "window_min": 1000}}})
        assert (c.paths, c.hold_ms, c.arm_delay_ms, c.window_min) == (("car_phone",), 1000,
                                                                      3000, 120)
        assert c112.load_config({"safety": {"call112": {"paths": "hfp"}}}).paths == c112.PATHS
        assert c112.load_config({"safety": "x"}).hold_ms == 2000

    @pytest.mark.parametrize("raw", ["yes", "false", 0, 1, None, "true"])
    def test_an_unclear_test_mode_is_test(self, raw):
        expected = raw is not None              # None = "not set" → the code default
        assert c112.load_config({"safety": {"call112": {"test_mode": raw}}}).test_mode \
            is expected

    @pytest.mark.parametrize("num, ok", [(TEST_NUM, True), ("601234599", False),
                                         ("+48 601 234 599", False), ("+0601234599", False),
                                         ("112", False), ("+48601234599;rm", False), (5, False)])
    def test_test_number_is_e164_only(self, num, ok):
        c = c112.load_config({"safety": {"call112": {"test_mode": True, "test_number": num}}})
        assert c.test_number == (num if ok else "")

    def test_vehicle_is_cleaned(self):
        c = c112.load_config({"safety": {"vehicle": {
            "label": "Alfa\x00 Romeo\n156" + "x" * 50, "colour": 5, "plate": "wx 1234;5"}}})
        assert c.vehicle["label"] == ("Alfa Romeo 156" + "x" * 50)[:32]     # \x00, \n → space
        assert c.vehicle["colour"] == "" and c.vehicle["plate"] == ""
        c = c112.load_config({"safety": {"vehicle": {"plate": "wx 12345"}}})
        assert c.vehicle == {"label": "Alfa Romeo 156", "colour": "", "plate": "WX 12345"}

    def test_shipped_configs(self):
        for name in ("bcm_config.yaml", "bcm_config_test.yaml"):
            cfg = BCMConfig(config_path=str(REPO / "config" / name), platform_override="x86",
                            local_path=None, env={})
            assert mc.is_enabled(cfg, "call112") is False
            assert mc.module_states(cfg)["call112"].runs is False
            c = c112.load_config(cfg)
            # the shipped files never name a number and never dial the real 112
            assert c.test_mode is True and c.test_number == ""
            assert "enabled" not in cfg.get("safety.call112")
            assert cfg.get("safety.vehicle") is None              # local.yaml only

    def test_catalog_entry(self):
        info = mc.MODULES["call112"]
        assert info["entry"] == ("src.safety.call112", "start_call112")
        assert not info.get("planned") and info["default"] is False
        assert info["requires"] == ("crash_detect",)
        assert info["requires_any"] == (("car_phone_agent", "bluetooth"),)

    def test_main_passes_the_bluetooth_manager(self):
        import main
        assert "call112" in main._NEEDS_BT_MANAGER
        got = {}
        main.start_modules([("call112", {"start": lambda **kw: got.update(kw)})],
                           {}, None, None, bt_manager="BT")
        assert got["bt_manager"] == "BT"


# ── the window ─────────────────────────────────────────────────────────────

class TestWindow:
    def test_no_event_no_window_no_dial(self, env):
        assert env.m.request_call()["error"] == "no_window"
        assert _last(env)["window"] is False and _last(env)["dispatcher"] is None
        assert env.bt.dialled == [] and env.agent.calls == []

    def test_nothing_dials_by_itself(self, env):
        _crash(env)
        for _ in range(200):
            env.clock.advance(5)
            env.m.run_once()
        assert env.bt.dialled == [] and env.agent.calls == [] and env.mutes == []
        assert _last(env)["state"] == "idle"

    def test_opened_by_a_crash_with_the_dispatcher_panel(self, env):
        _crash(env)
        p = _last(env)
        assert p["window"] is True and p["event_id"] == EID and p["offer"] == "hfp"
        assert p["window_until_ts"] == WALL0 + 1800
        d = p["dispatcher"]
        assert (d["lat"], d["lon"], d["sats"], d["heading"], d["speed_kmh"]) == (
            52.22968, 21.01223, 9, 270, 72)
        assert d["fix_age_s"] == 2 and d["event_ts"] == WALL0
        assert d["vehicle"] == {"label": "Alfa Romeo 156", "colour": "czerwona",
                                "plate": "WX 12345"}
        env.clock.advance(60)
        assert _last(env)["dispatcher"]["fix_age_s"] == 62          # it ages
        # a newer live fix wins
        env.bus.publish("gps.position", {"fix": True, "lat": 52.23, "lon": 21.01,
                                         "satellites": 11, "heading": 10.0})
        d = _last(env)["dispatcher"]
        assert (d["lat"], d["sats"], d["fix_age_s"], d["heading"]) == (52.23, 11, 0, 270)

    def test_gps_only_and_no_position(self, env):
        _crash(env, source="gps", sms_eligible=False, lat=None, lon=None, fix_age_s=None)
        d = _last(env)["dispatcher"]
        assert _last(env)["window"] is True
        assert d["lat"] is None and d["fix_age_s"] is None and d["speed_kmh"] == 72

    def test_closes_after_window_min(self, env):
        _crash(env)
        env.clock.advance(30 * 60 - 1)
        assert _last(env)["window"] is True
        env.clock.advance(2)
        assert _last(env)["window"] is False
        assert env.m.request_call()["error"] == "no_window"

    def test_cancelled_outcome_closes_it(self, env):
        # crash_detect says "cancelled" only when the car never stopped.
        _crash(env)
        env.bus.publish("crash.outcome", {"event_id": EID, "outcome": "cancelled"})
        env.m.run_once()
        assert _last(env)["window"] is False

    def _speeds(self, env, kmh, seconds, every=1.0):
        for _ in range(int(seconds / every)):
            env.clock.advance(every)
            env.bus.publish("gps.speed", kmh)
            env.m.run_once()

    def test_driving_on_after_a_stop_closes_it(self, env):
        # After "stopped" crash_detect publishes nothing more for the event:
        # the window judges "drove on" itself from gps.speed.
        _crash(env)
        env.bus.publish("crash.outcome", {"event_id": EID, "outcome": "stopped"})
        self._speeds(env, 0.0, 30)
        assert _last(env)["window"] is True
        self._speeds(env, 60.0, 9)
        assert _last(env)["window"] is True                  # not 10 s yet
        self._speeds(env, 60.0, 2)
        assert _last(env)["window"] is False
        assert json.loads(env.path.read_text())["event"]["dismissed"] is True

    @pytest.mark.parametrize("kmh, every", [(20.0, 1.0),     # below min_speed_kmh (25)
                                            (60.0, 3.0)])    # gaps over 2.5 s
    def test_slow_or_gappy_speed_keeps_it(self, env, kmh, every):
        _crash(env)
        self._speeds(env, kmh, 60, every=every)
        assert _last(env)["window"] is True

    def test_min_speed_follows_crash_detection(self, env):
        env.cfg["crash_detection"] = {"min_speed_kmh": 40}
        _crash(env)
        self._speeds(env, 35.0, 20)
        assert _last(env)["window"] is True
        self._speeds(env, 45.0, 11)
        assert _last(env)["window"] is False

    @pytest.mark.parametrize("bad", [True, "60", None, float("nan"), float("inf"), -5, 500])
    def test_garbage_speed_is_ignored(self, env, bad):
        _crash(env)
        for _ in range(15):
            env.clock.advance(1)
            env.bus.publish("gps.speed", bad)
            env.m.run_once()
        assert _last(env)["window"] is True

    def test_never_during_a_live_call_but_after_it(self, env):
        _crash(env)
        env.m.request_call()
        env.m.run_once()
        env.bus.publish("bt.dial_result", _origin(True))
        env.bus.publish("bt.call_state", "active")
        env.m.run_once()
        self._speeds(env, 60.0, 20)
        assert _last(env)["window"] is True and _last(env)["state"] == "active"
        env.bus.publish("bt.call_state", "idle")
        self._speeds(env, 60.0, 1)
        assert _last(env)["window"] is False

    def test_a_new_event_starts_its_own_tracker(self, env):
        _crash(env)
        self._speeds(env, 60.0, 8)
        _crash(env, eid=EID2)
        self._speeds(env, 60.0, 5)
        assert _last(env)["window"] is True and _last(env)["event_id"] == EID2
        self._speeds(env, 60.0, 6)
        assert _last(env)["window"] is False

    def test_end_to_end_with_the_real_crash_detector(self, env, tmp_path):
        # GPS-only hard braking 80 -> 0 (one "stopped" outcome), then the
        # car drives on: the window must close (it used to stay 30 min).
        from src.safety.crash_detect import CrashDetector
        from tests.sensor_sim import WALL_OFFSET
        det = CrashDetector({}, env.bus, clock=lambda: env.clock.mono,
                            wall_clock=lambda: env.clock.mono + WALL_OFFSET,
                            events_dir=str(tmp_path / "ev"), notify=lambda *a, **k: None)
        det.subscribe()
        outcomes = []
        env.bus.subscribe("crash.outcome", lambda t, v, ts: outcomes.append(v["outcome"]))

        def drive(kmh, seconds):
            for _ in range(seconds):
                env.clock.advance(1.0)
                env.bus.publish("gps.position", {"lat": 50.06, "lon": 19.94, "speed": kmh,
                                                 "heading": 180.0, "satellites": 7,
                                                 "fix": True})
                env.bus.publish("gps.speed", kmh)
                det.tick()
                env.m.run_once()
        drive(80.0, 5)
        for v in (55.0, 30.0, 5.0, 0.0, 0.0):
            drive(v, 1)
        p = _last(env)
        assert p["window"] is True and p["dispatcher"]["lat"] == 50.06
        assert outcomes == ["stopped"]
        drive(0.0, 20)
        drive(60.0, 12)
        assert outcomes == ["stopped"]                        # crash_detect is silent
        assert _last(env)["window"] is False

    def _sms(self, env, state="cancelled", modal=False, eid=EID):
        env.bus.publish("crash.sms_state", {"state": state, "event_id": eid, "modal": modal})
        env.m.run_once()

    def test_a_cancelled_sms_closes_it_once_its_result_is_gone(self, env):
        _crash(env)
        self._sms(env, "pending", True)
        self._sms(env, "cancelled", True)       # the result view: the 112 column stays
        assert _last(env)["window"] is True
        self._sms(env, "cancelled", True, eid=EID2)
        self._sms(env, "cancelled", False, eid=EID2)            # another event
        assert _last(env)["window"] is True
        self._sms(env, "cancelled", False)
        assert _last(env)["window"] is False

    @pytest.mark.parametrize("state", ["sent", "partial", "failed", "failed_no_phone"])
    def test_other_sms_results_keep_it(self, env, state):
        _crash(env)
        self._sms(env, state, False)
        assert _last(env)["window"] is True

    def test_a_cancelled_sms_after_a_112_call_keeps_it(self, env):
        _crash(env)
        env.m.request_call()
        env.m.run_once()
        env.bus.publish("bt.dial_result", _origin(True))
        env.bus.publish("bt.call_state", "active")
        env.bus.publish("bt.call_state", "idle")
        env.m.run_once()
        self._sms(env, "cancelled", False)
        assert _last(env)["window"] is True     # the panel and "Odbierz" stay

    def test_dismiss(self, env):
        _crash(env)
        assert env.m.dismiss(EID2)["error"] == "unknown_event"
        assert env.m.dismiss("<x>")["error"] == "bad_request"
        assert env.m.dismiss(EID)["ok"] is True
        env.m.run_once()
        assert _last(env)["window"] is False
        assert json.loads(env.path.read_text())["event"]["dismissed"] is True

    def test_restored_after_a_restart_within_the_window(self, env, tmp_path):
        _crash(env)
        assert env.path.stat().st_mode & 0o777 == 0o600
        env.clock.advance(600)
        again = c112.Call112(env.cfg, env.bus, bt_manager=env.bt,
                             agent_getter=lambda: env.agent, clock=lambda: env.clock.mono + 50,
                             wall_clock=lambda: env.clock.wall, state_path=str(env.path))
        again.run_once()
        p = again.payload()
        assert p["window"] is True and p["event_id"] == EID and p["state"] == "idle"
        assert p["dispatcher"]["fix_age_s"] == 602
        env.clock.advance(30 * 60)
        late = c112.Call112(env.cfg, env.bus, agent_getter=lambda: None,
                            clock=lambda: env.clock.mono, wall_clock=lambda: env.clock.wall,
                            state_path=str(env.path))
        late.run_once()
        assert late.payload()["window"] is False

    @pytest.mark.parametrize("content", [b"{", b"[]", b'{"event": {"id": "<x>"}}',
                                         b'{"event": {"id": "0123abcd", "ts": 5}}',
                                         b"x" * 9000])
    def test_damaged_file_is_ignored(self, env, content):
        env.path.write_bytes(content)
        m = c112.Call112(env.cfg, env.bus, agent_getter=lambda: None,
                         clock=lambda: env.clock.mono, wall_clock=lambda: env.clock.wall,
                         state_path=str(env.path))
        m.run_once()
        assert m.payload()["window"] is False


# ── path A: the main phone over HFP ────────────────────────────────────────

class TestHfp:
    def test_dials_112_through_the_internal_entry_point(self, env):
        _crash(env)
        res = env.m.request_call()
        assert res == {"ok": True, "error": "", "path": "hfp", "retry_after": 0}
        assert _last(env)["state"] == "dialing"
        env.m.run_once()
        assert env.bt.dialled == ["112"]
        env.bus.publish("bt.dial_result", _origin(True))
        env.m.run_once()
        assert _last(env)["state"] == "ringing"
        assert env.agent.calls == [("mark",)]          # the SMS says "Z auta wybrano 112"
        env.bus.publish("bt.call_state", "active")
        env.m.run_once()
        env.clock.advance(83)
        p = _last(env)
        assert p["state"] == "active" and p["duration_s"] == 83 and p["path"] == "hfp"
        env.bus.publish("bt.call_state", "idle")
        env.m.run_once()
        p = _last(env)
        assert p["state"] == "ended" and p["duration_s"] == 83
        assert env.agent.calls == [("mark",)] and env.mutes == []   # HFP: no media mute

    def test_other_dial_results_are_not_ours(self, env):
        _crash(env)
        env.m.request_call()
        env.m.run_once()
        env.bus.publish("bt.dial_result", {"ok": False, "path": "hfp", "error": "busy"})
        env.m.run_once()
        assert _last(env)["state"] == "dialing"

    @pytest.mark.parametrize("error", ["no_modem", "dbus", "netdown", "busy"])
    def test_a_dial_error_offers_the_car_phone_at_once(self, env, error):
        _crash(env)
        env.m.request_call()
        env.m.run_once()
        env.bus.publish("bt.dial_result", _origin(False, error))
        env.m.run_once()
        p = _last(env)
        assert p["state"] == "failed" and p["error"] == error
        assert p["offer"] == "car_phone" and p["fallback"] is True and p["retry_after_s"] == 0
        res = env.m.request_call()                     # within 60 s: the one exemption
        assert res["ok"] and res["path"] == "car_phone"
        env.m.run_once()
        assert env.agent.calls == [("call112", "real")]
        assert env.bt.hangups == 0                     # it never went out: nothing to end

    def test_no_confirmation_in_10_s_offers_the_car_phone(self, env):
        _crash(env)
        env.m.request_call()
        env.m.run_once()
        env.clock.advance(9.9)
        env.m.run_once()
        assert _last(env)["state"] == "dialing"
        env.clock.advance(0.2)
        env.m.run_once()
        p = _last(env)
        assert p["state"] == "failed" and p["error"] == "timeout" and p["offer"] == "car_phone"
        assert env.m.request_call()["path"] == "car_phone"
        env.m.run_once()
        # the unconfirmed HFP call may still be going out: ended first
        assert env.bt.hangups == 1 and env.agent.calls == [("call112", "real")]

    def test_a_late_confirmation_withdraws_the_fallback(self, env):
        _crash(env)
        env.m.request_call()
        env.m.run_once()
        env.clock.advance(11)
        env.m.run_once()
        assert _last(env)["fallback"] is True
        env.bus.publish("bt.dial_result", _origin(True))
        env.m.run_once()
        p = _last(env)
        assert p["state"] == "ringing" and p["fallback"] is False and p["retry_after_s"] > 0
        assert env.m.request_call()["error"] == "busy"

    def test_one_fallback_only(self, env):
        _crash(env)
        env.m.request_call()
        env.m.run_once()
        env.bus.publish("bt.dial_result", _origin(False, "dbus"))
        env.m.run_once()
        env.m.request_call()
        env.agent.call_answer = {"ok": False, "status": 409, "data": {"error": "no_root"},
                                 "error": "no_root"}
        env.m.run_once()
        p = _last(env)
        assert p["state"] == "failed" and p["error"] == "no_root" and p["fallback"] is False
        res = env.m.request_call()
        assert res["error"] == "rate_limited" and 0 < res["retry_after"] <= 60
        env.clock.advance(61)
        assert env.m.request_call()["ok"] is True          # after the minute: normal choice

    def test_refused_entry_point_and_its_real_reason(self, env):
        _crash(env)
        env.bt.accept = False
        env.m.request_call()
        env.m.run_once()
        assert _last(env)["state"] == "failed" and _last(env)["error"] == "dbus"
        env.bus.publish("bt.dial_result", _origin(False, "busy"))
        env.m.run_once()
        assert _last(env)["error"] == "busy"

    def test_hangup_ends_it_and_a_late_accept_does_not_revive_it(self, env):
        _crash(env)
        env.m.request_call()
        env.m.run_once()
        env.bus.publish("bt.call_state", "ringing")            # the provisional one
        assert env.m.request_hangup() == {"ok": True, "error": ""}
        env.m.run_once()
        assert env.bt.hangups == 1
        env.bus.publish("bt.call_state", "idle")
        env.m.run_once()
        assert _last(env)["state"] == "ended"
        env.bus.publish("bt.dial_result", _origin(True))
        env.m.run_once()
        assert _last(env)["state"] == "ended" and ("mark",) not in env.agent.calls

    def test_dispatcher_calls_back(self, env):
        _crash(env)
        env.bus.publish("bt.call_state", "incoming")
        env.m.run_once()
        assert _last(env)["incoming"] is True
        env.bus.publish("bt.call_state", "active")
        env.m.run_once()
        assert _last(env)["incoming"] is False


# ── path B: the car phone on its speaker ───────────────────────────────────

class TestCarPhone:
    @pytest.fixture
    def b_env(self, env):
        env.bus.publish("audio.mic_state", {"state": "none"})   # no mic: path A is out
        env.bus.publish("audio.mute_changed", False)
        _crash(env)
        return env

    def test_flow_with_mute_and_unmute(self, b_env):
        env = b_env
        assert env.m.request_call()["path"] == "car_phone"
        env.m.run_once()
        assert env.agent.calls == [("call112", "real")]
        assert env.mutes == [True]                              # BCM media off
        env.bus.publish("audio.mute_changed", True)
        env.agent.status_answer = _view("placed", placed_ts=int(WALL0) + 1)
        env.clock.advance(2)
        env.m.run_once()
        assert _last(env)["state"] == "ringing"
        env.agent.status_answer = _view("offhook", placed_ts=int(WALL0) + 1,
                                        offhook_ts=int(WALL0) + 4)
        env.clock.advance(2)
        env.m.run_once()
        env.clock.advance(10)
        p = _last(env)
        assert p["state"] == "active" and p["duration_s"] == 10 and p["path"] == "car_phone"
        assert env.m.request_hangup()["ok"]
        env.m.run_once()
        assert ("hangup",) in env.agent.calls
        env.agent.status_answer = _view("ended", ended_ts=int(WALL0) + 20)
        env.clock.advance(2)
        env.m.run_once()
        env.m.run_once()
        assert _last(env)["state"] == "ended"
        assert env.mutes == [True, True]                       # the toggle back: unmuted

    def test_no_mute_when_already_muted_and_never_unmuting_the_drivers_mute(self, b_env):
        env = b_env
        env.bus.publish("audio.mute_changed", True)
        env.m.request_call()
        env.m.run_once()
        env.agent.status_answer = _view("ended")
        env.clock.advance(2)
        env.m.run_once()
        env.m.run_once()
        assert env.mutes == []

    @pytest.mark.parametrize("error", ["mode_mismatch", "call112_off", "no_test_number",
                                       "no_root", "rate_limited"])
    def test_agent_refusals(self, b_env, error):
        env = b_env
        env.agent.call_answer = {"ok": False, "status": 429 if error == "rate_limited" else 409,
                                 "data": {"error": error}, "error": error}
        env.m.request_call()
        env.m.run_once()
        p = _last(env)
        assert p["state"] == "failed" and p["error"] == error and env.mutes == []

    def test_not_delivered(self, b_env):
        env = b_env
        env.agent.call_answer = {"ok": False, "status": None, "data": None,
                                 "error": "no_forward"}
        env.m.request_call()
        env.m.run_once()
        assert _last(env)["error"] == "no_phone"
        env.holder["agent"] = None
        env.clock.advance(61)
        # no agent running at all: path B is not even offered
        assert _last(env)["offer"] == "none"
        assert _last(env)["reasons"]["car_phone"] == "not_running"

    def test_a_lost_answer_is_looked_up(self, b_env):
        env = b_env
        env.agent.call_answer = {"ok": False, "status": None, "data": None, "error": "timeout"}
        env.m.request_call()
        env.m.run_once()
        assert _last(env)["state"] == "dialing"
        env.agent.status_answer = _view("placed", seq=7)
        env.clock.advance(2)
        env.m.run_once()
        assert _last(env)["state"] == "ringing"

    def test_a_lost_answer_with_no_call_fails_after_20_s(self, b_env):
        env = b_env
        env.agent.call_answer = {"ok": False, "status": None, "data": None, "error": "dropped"}
        env.m.request_call()
        env.m.run_once()
        # an OLD call on the phone is not ours
        env.agent.status_answer = _view("ended", requested_ts=int(WALL0) - 3600)
        for _ in range(11):
            env.clock.advance(2)
            env.m.run_once()
        assert _last(env)["state"] == "failed" and _last(env)["error"] == "no_phone"

    def test_unreadable_call_state_is_active_unverified(self, b_env):
        env = b_env
        env.m.request_call()
        env.m.run_once()
        env.agent.status_answer = _view("placed", final=True, placed_ts=int(WALL0) + 1)
        env.clock.advance(2)
        env.m.run_once()
        p = _last(env)
        assert p["state"] == "active" and p["unverified"] is True

    def test_agent_failure_reasons(self, b_env):
        env = b_env
        env.m.request_call()
        env.m.run_once()
        env.agent.status_answer = _view("failed", error="su_denied", final=True)
        env.clock.advance(2)
        env.m.run_once()
        p = _last(env)
        assert p["state"] == "failed" and p["error"] == "su_denied"
        assert p["offer"] == "none"              # A has no mic: nothing to fall back to


# ── path A without a microphone uplink (audio.call_route) ─────────────────

def _route(uplink="bluez_input.AA.0", peers=("alsa_input.usb-mic",), linked=True):
    return {"downlink": "bluez_output.AA.1", "uplink": uplink, "linked": linked,
            "downlink_peers": ["bcm_eq_sink"], "uplink_peers": list(peers)}


class TestUplink:
    def _live_hfp(self, env):
        _crash(env)
        env.m.request_call()
        env.m.run_once()
        env.bus.publish("bt.dial_result", _origin(True))
        env.bus.publish("bt.call_state", "active")
        env.m.run_once()
        assert _last(env)["state"] == "active"

    def test_a_linked_route_changes_nothing(self, env):
        self._live_hfp(env)
        env.bus.publish("audio.call_route", _route())
        env.m.run_once()
        p = _last(env)
        assert p["uplink"] == "ok" and p["fallback"] is False
        assert env.m.request_call()["error"] == "busy"

    @pytest.mark.parametrize("route", [_route(uplink=""), _route(peers=()),
                                       _route(peers=("bcm_null_mic",)),
                                       _route(peers=("bcm_null_mic", "bcm_null_mic"))])
    def test_no_uplink_offers_the_car_phone_during_the_call(self, env, route):
        self._live_hfp(env)
        order = []
        env.bt.hangup_call112 = lambda: order.append("hfp_hangup") or True
        real_call = env.agent.call112
        env.agent.call112 = lambda mode, eid: order.append("car_phone") or real_call(mode, eid)
        env.bus.publish("audio.call_route", route)
        env.m.run_once()
        p = _last(env)
        assert p["uplink"] == "missing" and p["offer"] == "car_phone" and p["fallback"] is True
        assert p["retry_after_s"] == 0
        res = env.m.request_call()
        assert res["ok"] and res["path"] == "car_phone"
        env.m.run_once()
        # the HFP call is ended FIRST: 112 is never called twice
        assert order == ["hfp_hangup", "car_phone"]
        p = _last(env)
        assert p["path"] == "car_phone" and p["fallback"] is False
        # the HFP call's later "idle" is not ours any more
        env.bus.publish("bt.call_state", "idle")
        env.m.run_once()
        assert _last(env)["state"] == "dialing"

    @pytest.mark.parametrize("route", [None, "x", {"uplink": 5}, {"uplink_peers": "a"},
                                       {"uplink": "x" * 200, "uplink_peers": []},
                                       {"uplink": "u", "uplink_peers": ["p"] * 17},
                                       {"uplink": "u", "uplink_peers": [5]}])
    def test_malformed_routes_are_ignored(self, env, route):
        self._live_hfp(env)
        env.bus.publish("audio.call_route", route)
        env.m.run_once()
        assert _last(env)["uplink"] == "unknown" and _last(env)["fallback"] is False

    def test_routes_without_our_hfp_call_are_ignored(self, env):
        _crash(env)
        env.bus.publish("audio.call_route", _route(uplink=""))     # an ordinary call
        env.m.run_once()
        assert _last(env)["uplink"] == "unknown" and _last(env)["offer"] == "hfp"
        env.bus.publish("audio.mic_state", {"state": "none"})
        env.bus.publish("audio.mute_changed", False)
        env.m.request_call()
        env.m.run_once()
        env.bus.publish("audio.call_route", _route(uplink=""))
        env.m.run_once()
        assert _last(env)["path"] == "car_phone" and _last(env)["uplink"] == "unknown"

    def test_after_the_call_ended_the_car_phone_stays_the_offer(self, env):
        self._live_hfp(env)
        env.bus.publish("audio.call_route", _route(peers=()))
        env.m.run_once()
        env.bus.publish("bt.call_state", "idle")
        env.m.run_once()
        env.clock.advance(120)
        p = _last(env)
        # never path A again with the same broken audio
        assert p["state"] == "ended" and p["offer"] == "car_phone" and p["retry_after_s"] == 0
        assert env.m.request_call()["path"] == "car_phone"
        env.m.run_once()
        assert env.bt.hangups == 0                   # nothing live to end

    def test_no_offer_when_the_car_phone_is_not_allowed(self, env):
        env.cfg["safety"]["call112"]["paths"] = ["hfp"]
        self._live_hfp(env)
        env.bus.publish("audio.call_route", _route(uplink=""))
        env.m.run_once()
        p = _last(env)
        assert p["uplink"] == "missing" and p["fallback"] is False
        assert env.m.request_call()["error"] == "busy"

    def test_summary_carries_the_uplink(self):
        assert wv._call112_summary({"uplink": "missing"})["uplink"] == "missing"
        assert wv._call112_summary({"uplink": "<b>"})["uplink"] == "unknown"


# ── "Rozłącz" that did not take, calls BCM can no longer see ──────────────

def _live_car_phone_call(env):
    """A path-B call that is up (OFFHOOK), BCM's media muted for it."""
    env.bus.publish("audio.mic_state", {"state": "none"})
    env.bus.publish("audio.mute_changed", False)
    _crash(env)
    env.m.request_call()
    env.m.run_once()
    env.bus.publish("audio.mute_changed", True)
    env.agent.status_answer = _view("offhook", offhook_ts=int(WALL0) + 3)
    env.clock.advance(2)
    env.m.run_once()
    assert _last(env)["state"] == "active"
    return env


class TestHangupRetry:
    @pytest.fixture
    def live_b(self, env):
        return _live_car_phone_call(env)

    def test_a_hangup_that_did_not_take_can_be_held_again(self, live_b):
        env = live_b
        assert env.m.request_hangup()["ok"]
        env.m.run_once()
        assert env.agent.calls.count(("hangup",)) == 1
        assert env.m.request_hangup()["ok"]                   # pending: a no-op
        env.m.run_once()
        assert env.agent.calls.count(("hangup",)) == 1
        for _ in range(4):                                     # the phone stays OFFHOOK
            env.clock.advance(2)
            env.m.run_once()
        assert _last(env)["hangup_pending"] is True
        env.clock.advance(c112.HANGUP_CONFIRM_S - 8 + 0.1)
        env.m.run_once()
        p = _last(env)
        assert p["state"] == "active" and p["hangup_pending"] is False
        assert env.m.request_hangup()["ok"]
        env.m.run_once()
        assert env.agent.calls.count(("hangup",)) == 2         # sent again

    def test_a_failed_agent_hangup_resets_at_once(self, live_b):
        env = live_b
        env.agent.hangup_answer = {"ok": False, "status": None, "data": None, "error": "connect"}
        env.m.request_hangup()
        env.m.run_once()
        assert _last(env)["hangup_pending"] is False

    def test_no_call_on_the_phone_ends_ours(self, live_b):
        env = live_b
        env.agent.hangup_answer = {"ok": False, "status": 409, "data": {"error": "no_call"},
                                   "error": "no_call"}
        env.m.request_hangup()
        env.m.run_once()
        env.m.run_once()
        p = _last(env)
        assert p["state"] == "ended" and p["unverified"] is True
        assert env.m.dismiss(EID)["ok"] is True
        assert env.mutes == [True, True]                       # media back

    def test_hfp_hangup_that_did_not_take_revives_the_call(self, env):
        _crash(env)
        env.m.request_call()
        env.m.run_once()
        env.bus.publish("bt.dial_result", _origin(True))
        env.bus.publish("bt.call_state", "active")
        env.m.run_once()
        env.clock.advance(30)
        env.m.request_hangup()
        env.m.run_once()
        env.bus.publish("bt.call_state", "idle")              # optimistic
        env.m.run_once()
        assert _last(env)["state"] == "ended"
        env.clock.advance(3)
        env.bus.publish("bt.call_state", "active")            # reconcile: still up
        env.m.run_once()
        p = _last(env)
        assert p["state"] == "active" and p["duration_s"] == 33 and p["hangup_pending"] is False
        assert env.m.request_hangup()["ok"]
        env.m.run_once()
        assert env.bt.hangups == 2

    def test_a_late_active_is_not_a_revive(self, env):
        _crash(env)
        env.m.request_call()
        env.m.run_once()
        env.bus.publish("bt.dial_result", _origin(True))
        env.bus.publish("bt.call_state", "active")
        env.m.run_once()
        env.m.request_hangup()
        env.m.run_once()
        env.bus.publish("bt.call_state", "idle")
        env.m.run_once()
        env.clock.advance(c112.HFP_HANGUP_REVIVE_S + 1)
        env.bus.publish("bt.call_state", "active")
        env.m.run_once()
        assert _last(env)["state"] == "ended"

    def test_hfp_hangup_without_any_answer_can_be_held_again(self, env):
        _crash(env)
        env.m.request_call()
        env.m.run_once()
        env.bus.publish("bt.dial_result", _origin(True))
        env.bus.publish("bt.call_state", "active")
        env.m.run_once()
        env.m.request_hangup()
        env.m.run_once()
        env.clock.advance(c112.HANGUP_CONFIRM_S + 0.1)
        env.m.run_once()
        assert _last(env)["hangup_pending"] is False and _last(env)["state"] == "active"


class TestUnverified:
    @pytest.fixture
    def live_b(self, env):
        return _live_car_phone_call(env)

    def _swc_forwarded(self, env):
        bridge_bus = EventBus()
        InputBridge(bridge_bus)
        hangups = []
        bridge_bus.subscribe("bt.cmd.hangup", lambda t, v, ts: hangups.append(v))
        bridge_bus.publish(c112.TOPIC_STATE, _last(env))
        bridge_bus.publish("input.phone_hangup", True)
        return hangups == [True]

    def test_an_agent_restart_mid_call_ends_it_here(self, live_b):
        env = live_b
        env.agent.status_answer = {"ok": True, "status": 200, "error": "",
                                   "data": {"call": None, "call_state": None}}
        for _ in range(c112.POLL_FAILS_UNVERIFIED - 1):
            env.clock.advance(2)
            env.m.run_once()
        assert _last(env)["state"] == "active"
        assert not self._swc_forwarded(env)                    # still blocked
        env.clock.advance(2)
        env.m.run_once()
        env.m.run_once()
        p = _last(env)
        assert p["state"] == "ended" and p["unverified"] is True
        assert env.m.dismiss(EID)["ok"] is True
        assert env.mutes == [True, True]
        assert self._swc_forwarded(env)

    def test_a_phone_that_stopped_answering_is_followed_5_min_at_most(self, live_b):
        env = live_b
        env.agent.status_answer = {"ok": False, "status": None, "data": None, "error": "connect"}
        for _ in range(30):
            env.clock.advance(5)
            env.m.run_once()
        p = _last(env)
        assert p["state"] == "active" and p["unverified"] is True
        assert env.m.dismiss(EID)["error"] == "busy"
        env.clock.advance(c112.UNVERIFIED_FOLLOW_MAX_S)
        env.m.run_once()
        env.m.run_once()
        p = _last(env)
        assert p["state"] == "ended" and p["unverified"] is True
        assert env.m.dismiss(EID)["ok"] is True and env.mutes == [True, True]

    def test_accepted_then_silent_while_dialing_is_followed_5_min_at_most(self, env):
        """200 'queued', then the phone stops answering (cable knocked out,
        forward gone): unverified, ended after UNVERIFIED_FOLLOW_MAX_S — not
        an hour of 'dialing' that blocks the main phone and dismiss."""
        env.bus.publish("audio.mic_state", {"state": "none"})       # path A out
        env.bus.publish("audio.mute_changed", False)
        _crash(env)
        assert env.m.request_call()["path"] == "car_phone"
        env.m.run_once()
        env.bus.publish("audio.mute_changed", True)
        env.agent.status_answer = {"ok": False, "status": None, "data": None,
                                   "error": "no_forward"}
        for _ in range(c112.POLL_FAILS_UNVERIFIED):
            env.clock.advance(2)
            env.m.run_once()
        p = _last(env)
        assert p["state"] == "dialing" and p["unverified"] is True
        assert env.m.dismiss(EID)["error"] == "busy"
        env.clock.advance(c112.UNVERIFIED_FOLLOW_MAX_S)
        env.m.run_once()
        env.m.run_once()
        p = _last(env)
        assert p["state"] == "ended" and p["unverified"] is True
        assert env.mutes == [True, True]
        env.bus.publish("audio.mic_state", {"state": "ok", "source": "usb", "aec": False})
        env.clock.advance(61)
        res = env.m.request_call()
        assert res["ok"] is True and res["path"] == "hfp"               # not 'busy'

    def test_a_lost_answer_still_fails_no_phone_at_20_s(self, env):
        env.bus.publish("audio.mic_state", {"state": "none"})
        _crash(env)
        env.agent.call_answer = {"ok": False, "status": None, "data": None, "error": "timeout"}
        env.m.request_call()
        env.m.run_once()
        env.agent.status_answer = {"ok": False, "status": None, "data": None,
                                   "error": "no_forward"}
        for _ in range(12):
            env.clock.advance(2)
            env.m.run_once()
        p = _last(env)
        assert p["state"] == "failed" and p["error"] == "no_phone"

    def test_an_unreadable_call_state_is_followed_5_min_at_most(self, live_b):
        env = live_b
        env.agent.status_answer = _view("placed", final=True, placed_ts=int(WALL0) + 1)
        env.clock.advance(2)
        env.m.run_once()
        assert _last(env)["unverified"] is True and _last(env)["state"] == "active"
        assert env.m.request_hangup()["ok"]                     # ENDCALL still possible
        env.m.run_once()
        assert ("hangup",) in env.agent.calls
        env.clock.advance(c112.UNVERIFIED_FOLLOW_MAX_S + 1)
        env.m.run_once()
        env.m.run_once()
        assert _last(env)["state"] == "ended"
        assert env.m.dismiss(EID)["ok"] is True and env.mutes == [True, True]


# ── path B outcomes that are not clear ─────────────────────────────────────

class TestCarPhoneAmbiguity:
    @pytest.fixture
    def b_env(self, env):
        env.bus.publish("audio.mute_changed", False)
        _crash(env)
        # path A is available, but B is the first choice here
        env.cfg["safety"]["call112"]["paths"] = ["car_phone", "hfp"]
        return env

    def test_event_id_goes_with_the_call(self, b_env):
        env = b_env
        env.m.request_call()
        env.m.run_once()
        assert env.agent.event_ids == [EID]

    def test_busy_with_the_phones_call_is_followed(self, b_env):
        env = b_env
        busy = {"seq": 4, "state": "offhook", "mode": "real", "error": "busy", "final": False,
                "number": "112", "requested_ts": int(WALL0) - 200, "offhook_ts": int(WALL0) - 190}
        env.agent.call_answer = {"ok": False, "status": 409, "data": busy, "error": "busy"}
        env.m.request_call()
        env.m.run_once()
        p = _last(env)
        assert p["state"] == "active" and p["path"] == "car_phone" and env.mutes == [True]
        env.agent.status_answer = _view("ended", seq=4)
        env.clock.advance(2)
        env.m.run_once()
        assert _last(env)["state"] == "ended"

    @pytest.mark.parametrize("error, status", [("busy", 409), ("rate_limited", 429)])
    def test_busy_or_rate_limited_offer_no_main_phone_at_once(self, b_env, error, status):
        env = b_env
        env.agent.call_answer = {"ok": False, "status": status, "data": {"error": error},
                                 "error": error}
        env.m.request_call()
        env.m.run_once()
        p = _last(env)
        assert p["state"] == "failed" and p["fallback"] is False and p["retry_after_s"] > 0
        assert env.m.request_call()["error"] == "rate_limited"
        assert env.bt.dialled == []

    def test_definitive_refusals_still_offer_the_main_phone(self, b_env):
        env = b_env
        env.agent.call_answer = {"ok": False, "status": 409, "data": {"error": "no_root"},
                                 "error": "no_root"}
        env.m.request_call()
        env.m.run_once()
        assert _last(env)["fallback"] is True and _last(env)["offer"] == "hfp"

    def test_no_phone_after_the_look_up_offers_no_main_phone_at_once(self, b_env):
        env = b_env
        env.agent.call_answer = {"ok": False, "status": None, "data": None, "error": "timeout"}
        env.m.request_call()
        env.m.run_once()
        for _ in range(11):
            env.clock.advance(2)
            env.m.run_once()
        p = _last(env)
        assert p["state"] == "failed" and p["error"] == "no_phone" and p["fallback"] is False

    def test_a_lost_answer_is_found_despite_clock_skew(self, b_env):
        env = b_env
        env.agent.call_answer = {"ok": False, "status": None, "data": None, "error": "timeout"}
        env.m.request_call()
        env.m.run_once()
        # the phone's clock is 50 s behind (HMAC allows ±60 s)
        env.agent.status_answer = _view("placed", seq=2, requested_ts=int(WALL0) - 50)
        env.clock.advance(2)
        env.m.run_once()
        assert _last(env)["state"] == "ringing"

    def test_an_older_call_of_this_run_is_not_taken_for_the_new_one(self, b_env):
        env = b_env
        env.m.request_call()                                   # seq 1 (FakeAgent's answer)
        env.m.run_once()
        env.agent.status_answer = _view("ended", seq=1)
        env.clock.advance(2)
        env.m.run_once()
        assert _last(env)["state"] == "ended"
        env.clock.advance(61)
        env.agent.call_answer = {"ok": False, "status": None, "data": None, "error": "timeout"}
        env.m.request_call()
        env.m.run_once()
        env.agent.status_answer = _view("ended", seq=1, requested_ts=int(env.clock.wall) - 60)
        env.clock.advance(2)
        env.m.run_once()
        assert _last(env)["state"] == "dialing"                # still looking
        env.agent.status_answer = _view("placed", seq=2, requested_ts=int(env.clock.wall))
        env.clock.advance(2)
        env.m.run_once()
        assert _last(env)["state"] == "ringing"

    def test_mark_carries_the_event_id(self, env):
        _crash(env)
        env.m.request_call()
        env.m.run_once()
        env.bus.publish("bt.dial_result", _origin(True))
        env.m.run_once()
        assert env.agent.calls == [("mark",)] and env.agent.event_ids == [EID]


# ── limits and test mode ───────────────────────────────────────────────────

class TestLimits:
    def test_one_dial_per_minute(self, env):
        _crash(env)
        env.m.request_call()
        env.m.run_once()
        env.bus.publish("bt.dial_result", _origin(True))
        env.bus.publish("bt.call_state", "active")
        env.m.run_once()
        assert env.m.request_call()["error"] == "busy"
        env.bus.publish("bt.call_state", "idle")
        env.m.run_once()
        res = env.m.request_call()
        assert res["error"] == "rate_limited" and res["retry_after"] > 0
        assert _last(env)["retry_after_s"] > 0
        env.clock.advance(60)
        assert env.m.request_call()["ok"] is True

    def test_no_path(self, env):
        env.bus.publish("audio.mic_state", {"state": "none"})
        env.agent.facts["call112_capable"] = False
        _crash(env)
        res = env.m.request_call()
        assert res == {"ok": False, "error": "no_path", "path": "none", "retry_after": 0}
        assert env.bt.dialled == [] and env.agent.calls == []

    def test_test_mode_never_dials_112(self, env):
        env.cfg["safety"]["call112"].update(test_mode=True, test_number=TEST_NUM)
        _crash(env)
        p = _last(env)
        assert p["test_mode"] is True and p["test_number"] == "+48...599"
        assert env.m.request_call()["path"] == "hfp"
        env.m.run_once()
        assert env.bt.dialled == [TEST_NUM]
        env.bus.publish("bt.dial_result", _origin(True))
        env.m.run_once()
        assert ("mark",) not in env.agent.calls          # no "Z auta wybrano 112" in a test
        env.bus.publish("bt.call_state", "active")
        env.bus.publish("bt.call_state", "idle")
        env.m.run_once()
        assert _last(env)["state"] == "ended"
        env.clock.advance(61)
        env.bus.publish("audio.mic_state", {"state": "none"})
        env.agent.facts["call112_mode"] = "test"
        assert env.m.request_call()["path"] == "car_phone"
        env.m.run_once()
        assert env.agent.calls[-1] == ("call112", "test")
        assert "112" not in env.bt.dialled

    def test_test_mode_without_a_number_dials_nothing(self, env):
        env.cfg["safety"]["call112"].update(test_mode=True)
        _crash(env)
        assert _last(env)["offer"] == "none"
        assert env.m.request_call()["error"] == "no_path"
        assert env.bt.dialled == [] and env.agent.calls == []

    def test_test_window_only_in_test_mode(self, env):
        assert env.m.open_test_window()["error"] == "not_test_mode"
        env.cfg["safety"]["call112"].update(test_mode=True)
        assert env.m.open_test_window()["error"] == "no_test_number"
        env.cfg["safety"]["call112"].update(test_number=TEST_NUM)
        seen = []
        env.bus.subscribe("crash.detected", lambda t, v, ts: seen.append(v))
        assert env.m.open_test_window()["ok"] is True
        env.m.run_once()
        assert _last(env)["window"] is True and seen == []    # no crash, no SMS

    def _restart(self, env, cfg):
        again = c112.Call112(cfg, env.bus, bt_manager=env.bt,
                             agent_getter=lambda: env.agent, clock=lambda: env.clock.mono,
                             wall_clock=lambda: env.clock.wall, state_path=str(env.path))
        again.run_once()
        return again

    def _bench_test(self, env):
        env.cfg["safety"]["call112"].update(test_mode=True, test_number=TEST_NUM)
        assert env.m.open_test_window()["ok"] is True
        env.m.run_once()
        assert json.loads(env.path.read_text())["event"]["source"] == "test"
        env.clock.advance(300)

    def test_a_test_window_never_comes_back_in_real_mode(self, env):
        """docs §5.11: bench test, then test_mode: false and a BCM restart
        within window_min — no phantom real-112 window, nothing dialled."""
        self._bench_test(env)
        again = self._restart(env, _cfg())
        p = again.payload()
        assert p["window"] is False and p["dispatcher"] is None
        assert again.request_call()["error"] == "no_window"
        again.run_once()
        assert env.bt.dialled == [] and env.agent.calls == []
        assert json.loads(env.path.read_text())["event"] is None   # overwritten

    def test_a_test_window_comes_back_in_test_mode_and_dials_only_the_test_number(self, env):
        self._bench_test(env)
        again = self._restart(env, _cfg(test_mode=True, test_number=TEST_NUM))
        assert again.payload()["window"] is True
        assert again.request_call()["ok"] is True
        again.run_once()
        assert env.bt.dialled == [TEST_NUM]

    def test_a_test_window_needs_the_test_number_after_a_restart(self, env):
        self._bench_test(env)
        again = self._restart(env, _cfg(test_mode=True))
        assert again.payload()["window"] is False
        assert again.request_call()["error"] == "no_window"

    def test_switching_test_mode_off_at_runtime_closes_a_test_window(self, env):
        self._bench_test(env)
        env.cfg["safety"]["call112"].update(test_mode=False)
        assert env.m.payload()["window"] is False
        assert env.m.request_call()["error"] == "no_window"
        env.m.run_once()
        assert env.bt.dialled == []


# ── stop / start ───────────────────────────────────────────────────────────

def test_stop_unsubscribes_and_start_registers(env, tmp_path, monkeypatch):
    # The real entry point uses the default data/call112.json (relative)
    # and the real agent accessor: run it in tmp_path, never the repo.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cpa, "get_agent", lambda: None)
    m = c112.start_call112(_cfg(), env.bus, bt_manager=env.bt)
    try:
        assert c112.get_call112() is m
    finally:
        m.stop()
    assert c112.get_call112() is None
    assert m.request_call()["error"] == "stopped"
    env.m.stop()
    env.bus.publish("crash.detected", {"event_id": EID2})
    assert env.m._q.qsize() <= 1                         # only the stop marker


# ── the routes and the dashboard summary ───────────────────────────────────

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
    monkeypatch.setattr(c112, "get_call112", lambda: holder["module"])
    return SimpleNamespace(env=env, cfg=cfg, viewer=viewer, holder=holder,
                           client=viewer._build_app().test_client())


def _as(addr):
    return {"environ_base": {"REMOTE_ADDR": addr}}


class TestRoutes:
    def test_call_ignores_any_number_in_the_body(self, web):
        _crash(web.env)
        res = web.client.post("/api/crash/call112", json={"number": "997", "path": "x"})
        assert res.status_code == 200 and res.get_json() == {"ok": True, "path": "hfp"}
        web.env.m.run_once()
        assert web.env.bt.dialled == ["112"]

    def test_429_within_a_minute(self, web):
        _crash(web.env)
        assert web.client.post("/api/crash/call112", json={}).status_code == 200
        web.env.m.run_once()
        web.env.bus.publish("bt.dial_result", _origin(True))
        web.env.bus.publish("bt.call_state", "active")
        web.env.bus.publish("bt.call_state", "idle")
        web.env.m.run_once()
        web.viewer._crash_last.clear()
        res = web.client.post("/api/crash/call112", json={})
        assert res.status_code == 429 and int(res.headers["Retry-After"]) >= 1
        assert res.get_json()["retry_after"] >= 1
        assert web.env.bt.dialled == ["112"]

    def test_outside_the_window(self, web):
        res = web.client.post("/api/crash/call112", json={})
        assert res.status_code == 409 and res.get_json()["error"] == "no_window"
        assert web.env.bt.dialled == []

    @pytest.mark.parametrize("addr", ["192.168.1.50", "10.0.0.5", "8.8.8.8", "::2",
                                      "::ffff:192.168.1.5"])
    @pytest.mark.parametrize("route", ["/api/crash/call112", "/api/crash/call112/hangup",
                                       "/api/crash/call112/close", "/api/crash/call112/test"])
    def test_loopback_only_even_with_full_remote_access(self, web, route, addr):
        _crash(web.env)
        web.cfg.set("dashboard.remote_access", "full")
        client = web.viewer._build_app().test_client()
        res = client.post(route, json={"event_id": EID}, **_as(addr))
        assert res.status_code == 403 and res.get_json()["error"] == "forbidden"
        web.env.m.run_once()
        assert web.env.bt.dialled == [] and _last(web.env)["window"] is True

    @pytest.mark.parametrize("addr", ["127.0.0.1", "::1"])
    def test_kiosk(self, web, addr):
        _crash(web.env)
        assert web.client.post("/api/crash/call112", json={}, **_as(addr)).status_code == 200

    @pytest.mark.parametrize("headers", [
        {"Host": "evil.example:5002"},                                 # DNS rebinding
        {"Host": "localhost:5002", "Origin": "http://evil.example"},   # foreign page
        {"Host": "localhost:5002", "Origin": "null"},                  # sandboxed frame
    ])
    def test_loopback_with_a_foreign_host_or_origin_is_refused(self, web, headers):
        """A page in the kiosk browser whose name was re-pointed at
        127.0.0.1 is loopback too — Host / Origin must be the kiosk's."""
        _crash(web.env)
        res = web.client.post("/api/crash/call112", json={}, headers=headers,
                              **_as("127.0.0.1"))
        assert res.status_code == 403 and res.get_json()["error"] == "forbidden"
        web.env.m.run_once()
        assert web.env.bt.dialled == []

    @pytest.mark.parametrize("host,origin", [("localhost:5002", "http://localhost:5002"),
                                             ("127.0.0.1:5002", "http://127.0.0.1:5002"),
                                             ("localhost:5002", None)])
    def test_the_kiosk_page_with_its_own_origin(self, web, host, origin):
        _crash(web.env)
        headers = {"Host": host} if origin is None else {"Host": host, "Origin": origin}
        res = web.client.post("/api/crash/call112", json={}, headers=headers,
                              **_as("127.0.0.1"))
        assert res.status_code == 200

    def test_module_off(self, web):
        web.holder["module"] = None
        for route in ("/api/crash/call112", "/api/crash/call112/hangup",
                      "/api/crash/call112/test"):
            res = web.client.post(route, json={})
            assert res.status_code == 409 and res.get_json()["error"] == "not_running"
        res = web.client.post("/api/crash/call112/close", json={"event_id": EID})
        assert res.status_code == 409

    def test_hangup_and_close(self, web):
        _crash(web.env)
        assert web.client.post("/api/crash/call112/hangup", json={}).status_code == 409   # no call
        web.client.post("/api/crash/call112", json={})
        web.env.m.run_once()
        res = web.client.post("/api/crash/call112/close", json={"event_id": EID})
        assert res.status_code == 409 and res.get_json()["error"] == "busy"
        web.viewer._crash_last.clear()
        assert web.client.post("/api/crash/call112/hangup", json={}).status_code == 200
        web.env.m.run_once()
        assert web.env.bt.hangups == 1
        web.env.bus.publish("bt.call_state", "idle")
        web.env.m.run_once()
        for body in (None, {}, {"event_id": "ABC"}):
            assert web.client.post("/api/crash/call112/close", json=body).status_code == 400
        res = web.client.post("/api/crash/call112/close", json={"event_id": EID})
        assert res.status_code == 200
        web.env.m.run_once()
        assert _last(web.env)["window"] is False

    @pytest.mark.parametrize("route", ["/api/crash/call112", "/api/crash/call112/hangup",
                                       "/api/crash/call112/test"])
    @pytest.mark.parametrize("kw", [{}, {"data": "{}", "content_type": "text/plain"},
                                    {"data": {"x": "1"}},
                                    {"data": "[]", "content_type": "application/json"},
                                    {"data": "{", "content_type": "application/json"}])
    def test_a_cross_origin_simple_post_is_refused(self, web, route, kw):
        # A "simple" request (no body / text/plain / form) needs no CORS
        # preflight — any page in a browser on the head unit could send it.
        web.env.cfg["safety"]["call112"].update(test_mode=True, test_number=TEST_NUM)
        _crash(web.env)
        res = web.client.post(route, **kw)
        assert res.status_code == 400 and res.get_json()["error"] == "bad_request"
        web.env.m.run_once()
        assert web.env.bt.dialled == [] and _last(web.env)["state"] == "idle"

    def test_oversized_body(self, web):
        _crash(web.env)
        res = web.client.post("/api/crash/call112", data="x" * 2000,
                              content_type="application/json")
        assert res.status_code == 413 and web.env.bt.dialled == []

    def test_get_is_not_allowed(self, web):
        assert web.client.get("/api/crash/call112").status_code == 405

    def test_phone_dial_still_refuses_112_from_the_network(self, web):
        dials = []
        web.env.bus.subscribe("bt.cmd.dial", lambda t, v, ts: dials.append(v))
        res = web.client.post("/api/phone/dial", json={"number": "112"}, **_as("192.168.1.50"))
        assert res.status_code == 403 and dials == []
        res = web.client.post("/api/phone/dial", json={"number": "112"}, **_as("127.0.0.1"))
        assert res.status_code == 200 and dials == ["112"]

    def test_dashboard_payload(self, web):
        assert web.viewer._get_dashboard_data()["call112"] is None      # module not running
        _crash(web.env)
        web.env.m._publish()
        out = web.viewer._get_dashboard_data()["call112"]
        assert out["window"] is True and out["event_id"] == EID and out["offer"] == "hfp"
        assert out["dispatcher"]["lat"] == 52.22968
        assert out["dispatcher"]["vehicle"]["plate"] == "WX 12345"

    def test_summary_is_a_whitelist(self, web):
        _crash(web.env)
        raw = dict(_last(web.env))
        raw.update(state="<b>", path="evil", error="rm -rf", offer="x", test_number="+48601234599",
                   reasons={"hfp": "<x>", "car_phone": "no_mic"}, retry_after_s=-5,
                   hold_ms=True, dispatcher=dict(raw["dispatcher"], lat=999, sats=-1,
                                                 vehicle={"label": "x" * 99, "plate": 5}))
        s = wv._call112_summary(raw)
        assert (s["state"], s["path"], s["error"], s["offer"]) == ("idle", "", "", "none")
        assert s["test_number"] == ""                     # an unmasked number never goes out
        assert s["reasons"] == {"hfp": "", "car_phone": "no_mic"}
        assert s["retry_after_s"] == 0 and s["hold_ms"] == 2000
        assert s["dispatcher"]["lat"] is None and s["dispatcher"]["lon"] is None
        assert s["dispatcher"]["vehicle"] == {"label": "x" * 32, "colour": "", "plate": ""}
        assert wv._call112_summary(None) is None
        assert wv._call112_summary({"test_mode": "no"})["test_mode"] is True


# ── the steering wheel during a 112 call ───────────────────────────────────

class TestSteeringWheel:
    def test_hangup_ignored_during_a_112_call_and_logged_once(self, caplog):
        import logging
        bus = EventBus()
        InputBridge(bus)
        hangups = []
        bus.subscribe("bt.cmd.hangup", lambda t, v, ts: hangups.append(v))
        bus.publish("input.phone_hangup", True)
        assert hangups == [True]                              # normal: hangs up
        bus.publish(c112.TOPIC_STATE, {"state": "active", "started_ts": WALL0})
        with caplog.at_level(logging.WARNING, logger="bcm.input.bridge"):
            bus.publish("input.phone_hangup", True)
            bus.publish("input.phone_hangup", True)
        assert hangups == [True]
        assert len([r for r in caplog.records if "IGNORED" in r.getMessage()]) == 1
        for state in ("dialing", "ringing"):
            bus.publish(c112.TOPIC_STATE, {"state": state, "started_ts": WALL0 + 100})
            bus.publish("input.phone_hangup", True)
        assert hangups == [True]
        bus.publish(c112.TOPIC_STATE, {"state": "ended", "started_ts": WALL0 + 100})
        bus.publish("input.phone_hangup", True)
        assert hangups == [True, True]

    def test_no_swc_action_dials_112(self):
        from src.input import swc_remote
        assert not [a for a in swc_remote.ACTIONS if "112" in a or "emergency" in a]
        bridge_src = (REPO / "src/input/input_bridge.py").read_text(encoding="utf-8")
        assert "bt.cmd.dial" not in bridge_src and "dial_call112" not in bridge_src


# ── the Bluetooth manager's entry point ───────────────────────────────────

class _Cfg:
    def get(self, key, default=None):
        return default


class TestBluetoothEntryPoint:
    def _mgr(self, monkeypatch):
        monkeypatch.setattr(bt.BluetoothManager, "_check_availability", lambda self: None)
        bus = EventBus()
        mgr = bt.BluetoothManager(_Cfg(), bus)
        queued = []
        monkeypatch.setattr(mgr, "_submit_call", lambda kind, arg=None: queued.append(
            (kind, arg)) or True)
        results = []
        bus.subscribe("bt.dial_result", lambda t, v, ts: results.append(v))
        return bus, mgr, queued, results

    @pytest.mark.parametrize("number", ["997", "+48 112", "112#", "*31#112", "", None, 112,
                                        "+48601234599;x", "0048112"])
    def test_only_112_or_an_e164_test_number(self, monkeypatch, number):
        bus, mgr, queued, results = self._mgr(monkeypatch)
        assert mgr.dial_call112(number) is False
        assert queued == [] and results == []

    @pytest.mark.parametrize("number", ["112", TEST_NUM])
    def test_queued_on_the_worker_with_its_origin(self, monkeypatch, number):
        bus, mgr, queued, results = self._mgr(monkeypatch)
        assert mgr.dial_call112(number) is True
        assert queued == [("dial", (number, "call112"))]
        assert bus.get_last("bt.call_state")[0] == "ringing"

    def test_the_test_number_is_masked_in_the_log(self, monkeypatch, caplog):
        """The test number is a private person's number (local.yaml only)."""
        bus, mgr, queued, results = self._mgr(monkeypatch)
        monkeypatch.setattr(bt, "HAS_DBUS", True)
        monkeypatch.setattr(mgr, "_hfp_dial_dbus", lambda number: "netdown")
        monkeypatch.setattr(mgr, "_schedule_call_reconcile", lambda *a: None)
        with caplog.at_level(logging.DEBUG):
            assert mgr.dial_call112(TEST_NUM) is True
            mgr._run_dial((TEST_NUM, "call112"))
        assert TEST_NUM not in caplog.text
        assert f"{TEST_NUM[:3]}...{TEST_NUM[-3:]}" in caplog.text

    def test_busy_reports_its_origin(self, monkeypatch):
        bus, mgr, queued, results = self._mgr(monkeypatch)
        mgr._dial_busy = True
        assert mgr.dial_call112("112") is False
        assert results[-1]["origin"] == "call112" and results[-1]["error"] == "busy"

    def test_the_worker_carries_the_origin_into_the_result(self, monkeypatch):
        bus, mgr, queued, results = self._mgr(monkeypatch)
        monkeypatch.setattr(bt, "HAS_DBUS", True)
        monkeypatch.setattr(mgr, "_hfp_dial_dbus", lambda number: None)
        monkeypatch.setattr(mgr, "_schedule_call_reconcile", lambda *a: None)
        mgr._run_dial(("112", "call112"))
        assert results[-1]["ok"] is True and results[-1]["origin"] == "call112"
        mgr._run_dial("600123456")                     # the bus path: no origin
        assert "origin" not in results[-1]

    def test_facts_without_and_with_a_live_monitor(self, monkeypatch):
        bus, mgr, queued, results = self._mgr(monkeypatch)
        assert mgr.call112_facts() == {"connected": False, "voice_modem": False,
                                       "call_state": None}
        tracker = bt.OfonoCallTracker(bus)
        tracker.live = True
        tracker.modem_added("/hfp/x", {"Interfaces": [bt.OFONO_VCM_IFACE]})
        mgr._call_tracker = tracker
        mgr._connected_device = {"address": "AA", "name": "P"}
        assert mgr.call112_facts() == {"connected": True, "voice_modem": True,
                                       "call_state": "idle"}

    def test_authenticated_peers_are_hfp_modems_of_a_live_monitor(self, monkeypatch):
        """parking_guard's Bluetooth owner proof: oFono's HFP voice modem per
        address (exists only after an authenticated RFCOMM link), never a
        bare connection."""
        bus, mgr, queued, results = self._mgr(monkeypatch)
        assert mgr.authenticated_peers() == frozenset()
        tracker = bt.OfonoCallTracker(bus)
        tracker.modem_added("/hfp/org/bluez/hci0/dev_AA_BB_CC_DD_EE_01",
                            {"Interfaces": [bt.OFONO_VCM_IFACE]})
        tracker.modem_added("/hfp/org/bluez/hci0/dev_AA_BB_CC_DD_EE_02",
                            {"Interfaces": []})                # no VoiceCallManager yet
        tracker.modem_added("/ril_0", {"Interfaces": [bt.OFONO_VCM_IFACE]})
        mgr._call_tracker = tracker
        assert mgr.authenticated_peers() == frozenset()          # monitor not live
        tracker.live = True
        mgr._connected_device = {"address": "AA:BB:CC:DD:EE:02", "name": "P"}
        assert mgr.authenticated_peers() == frozenset({"AA:BB:CC:DD:EE:01"})

    def test_hangup_entry_point(self, monkeypatch):
        bus, mgr, queued, results = self._mgr(monkeypatch)
        monkeypatch.setattr(bt, "HAS_DBUS", True)
        assert mgr.hangup_call112() is True
        assert queued == [("hangup", None)]
        assert bus.get_last("bt.call_state")[0] == "idle"


def test_module_docs_say_always_manual():
    doc = c112.__doc__
    assert "ALWAYS manual" in doc and "NOTHING here dials by itself" in doc
    assert sys.modules["src.safety.call112"] is c112


class TestPhoneRoutesDuring112:
    """/api/phone/hangup|answer|dial during a live 112 call: never from the
    network (403, also in remote_access "full"); the kiosk cannot end the
    dispatcher call through the phone screen (409) — only the crash window's
    held "Rozłącz" does."""

    def _live(self, web):
        _crash(web.env)
        assert web.env.m.request_call()["ok"] is True
        web.env.m.run_once()
        assert web.env.m.state["state"] in c112.LIVE
        cmds = []
        web.env.bus.subscribe("*", lambda t, v, ts: cmds.append(t)
                              if t.startswith("bt.cmd.") else None)
        return cmds

    @pytest.mark.parametrize("route,body", [("/api/phone/hangup", None),
                                            ("/api/phone/answer", None),
                                            ("/api/phone/dial", {"number": "601234567"})])
    def test_the_network_cannot_touch_the_call(self, web, route, body):
        cmds = self._live(web)
        web.cfg.set("dashboard.remote_access", "full")
        client = web.viewer._build_app().test_client()
        res = client.post(route, json=body, **_as("10.0.0.23"))
        assert res.status_code == 403 and res.get_json()["error"] == "forbidden"
        res = client.post(route, data="x", content_type="text/plain", **_as("192.168.1.5"))
        assert res.status_code == 403
        assert cmds == []

    def test_the_kiosk_cannot_hang_up_through_the_phone_screen(self, web):
        cmds = self._live(web)
        res = web.client.post("/api/phone/hangup")
        assert res.status_code == 409 and res.get_json()["error"] == "call112_live"
        assert cmds == []
        assert web.client.post("/api/phone/answer").status_code == 200   # "Odbierz"
        assert cmds == ["bt.cmd.answer"]

    def test_after_the_call_or_without_the_module_it_works(self, web):
        cmds = self._live(web)
        web.holder["module"] = None
        assert web.client.post("/api/phone/hangup").status_code == 200
        web.holder["module"] = web.env.m
        web.env.bus.publish("bt.call_state", "active")
        web.env.bus.publish("bt.call_state", "idle")
        web.env.m.run_once()
        assert web.env.m.state["state"] not in c112.LIVE
        assert web.client.post("/api/phone/hangup").status_code == 200
        assert cmds.count("bt.cmd.hangup") == 2
