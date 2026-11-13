"""SMS after a crash (src/safety/crash_sms.py, plan F "Przebieg") — the state
machine with a fake agent and a fake clock, the web routes, the dashboard
payload, the SWC action ``crash_cancel`` and the config.

Nothing real is touched: the agent is a fake object (no sockets, no adb),
the clock is injected, files only go to tmp_path, the web routes run through
Flask's test client.
"""

import json
import logging
import math
import os
import shutil
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core import modules_catalog as mc
from src.core.config import BCMConfig
from src.core.event_bus import EventBus
from src.dashboard import web_viewer as wv
from src.dashboard.web_viewer import WebViewer
from src.network import car_phone_agent as cpa
from src.safety import crash_sms as cs

REPO = Path(__file__).resolve().parent.parent
EID = "0123456789abcdef" * 2     # built: no 32-hex literal in the repo
EID2 = "fedcba9876543210" * 2
NUM1 = "+48601234567"
NUM2 = "+48602345678"
WALL0 = 1_763_000_000.0


# ── fakes ──────────────────────────────────────────────────────────────────

class Clocks:
    """Monotonic and wall clock moving together."""

    def __init__(self, mono=1000.0, wall=WALL0):
        self.t = mono
        self.w = wall

    def mono(self):
        return self.t

    def wall(self):
        return self.w

    def advance(self, s):
        self.t += s
        self.w += s


class FakeAgent:
    """The CarPhoneAgent API crash_sms uses, with the phone's behaviour
    (bcm_agent.py) reduced to what matters: arm is idempotent by id, the
    phone holds the deadline, cancel stops what has not gone out."""

    def __init__(self, clocks):
        self.c = clocks
        self.events = {}
        self.calls = []
        self.fail = None          # transport error code for every call
        self.refuse = None        # (status, error) for arm
        self.outcome = "sent"     # per recipient when "sent"
        self.threads = set()
        self.kicks = 0
        self.state = {"state": "ok", "paired": True, "reason": "",
                      "last_ok_ts": clocks.wall()}
        self.facts = dict(cpa._EMPTY_FACTS, dry_run=True, recipients_n=1)
        self.test_answer = {"ok": True, "status": 200, "data": {"ok": True}, "error": "",
                            "detail": ""}

    def health_facts(self):
        return dict(self.facts)

    def kick(self):
        self.kicks += 1

    @staticmethod
    def _err(code, status=None):
        return {"ok": False, "status": status, "data": None, "error": code, "detail": ""}

    @staticmethod
    def _ok(data):
        return {"ok": True, "status": 200, "data": data, "error": "", "detail": ""}

    def _view(self, ev):
        left = 0
        if ev["state"] == "armed":
            left = max(0, int(math.ceil(ev["deadline"] - self.c.mono())))
        return {"id": ev["id"], "state": ev["state"], "dry_run": ev["dry"],
                "countdown_s": ev["countdown_s"], "deadline_in_s": left, "armed_ts": 0,
                "error": "", "results": [dict(r) for r in ev["results"]],
                "cancel_sms": ev.get("cancel_sms")}

    def _record(self, *call):
        self.calls.append(call)
        self.threads.add(threading.current_thread().name)

    def arm_crash(self, eid, countdown_s, lat, lon, fix_age_s, speed_kmh, dv_kmh, event_ts,
                  dry_run=False):
        self._record("arm", eid, countdown_s, dry_run, lat, lon, fix_age_s, speed_kmh, dv_kmh,
                     event_ts)
        if self.fail:
            return self._err(self.fail)
        if self.refuse:
            return {"ok": False, "status": self.refuse[0], "data": {"error": self.refuse[1]},
                    "error": self.refuse[1], "detail": ""}
        ev = self.events.get(eid)
        if ev is None:
            ev = self.events[eid] = {
                "id": eid, "state": "armed", "dry": bool(dry_run), "countdown_s": countdown_s,
                "deadline": self.c.mono() + countdown_s,
                "results": [{"to": "+48...567", "state": "queued", "tries": 0,
                             "verified": None, "error": ""}]}
        return self._ok(dict(self._view(ev), created=True))

    def get(self, eid):
        self._record("get", eid)
        if self.fail:
            return self._err(self.fail)
        ev = self.events.get(eid)
        if ev is None:
            return {"ok": False, "status": 404, "data": {"error": "unknown_event"},
                    "error": "unknown_event", "detail": ""}
        return self._ok(self._view(ev))

    def cancel(self, eid):
        self._record("cancel", eid)
        if self.fail:
            return self._err(self.fail)
        ev = self.events.get(eid)
        if ev is None:
            return {"ok": False, "status": 404, "data": {"error": "unknown_event"},
                    "error": "unknown_event", "detail": ""}
        went = any(r["state"] in ("sent", "sent_dry") for r in ev["results"])
        for r in ev["results"]:
            if r["state"] in ("queued", "wait", "retry"):
                r["state"] = "skipped"
        ev["state"] = "cancelled"
        if went:
            ev["cancel_sms"] = {"state": "sending", "results": []}
        return self._ok(self._view(ev))

    def send_now(self, eid):
        self._record("send_now", eid)
        if self.fail:
            return self._err(self.fail)
        ev = self.events.get(eid)
        if ev is None:
            return {"ok": False, "status": 404, "data": {"error": "unknown_event"},
                    "error": "unknown_event", "detail": ""}
        if ev["state"] == "armed":
            ev["deadline"] = self.c.mono()
        return self._ok(self._view(ev))

    def test_sms(self, force_dry=False, real=False):
        self._record("test", force_dry, real)
        return dict(self.test_answer)

    def step(self):
        """The phone's scheduler: deadline → sending → outcome."""
        for ev in self.events.values():
            if ev["state"] == "armed" and self.c.mono() >= ev["deadline"]:
                ev["state"] = "sending"
                for r in ev["results"]:
                    r["state"] = "sending"
            elif ev["state"] == "sending":
                for r in ev["results"]:
                    r["state"] = ("sent_dry" if ev["dry"] else "sent") \
                        if self.outcome == "sent" else "failed"
                    r["tries"] = 1
                ok = sum(r["state"] in ("sent", "sent_dry") for r in ev["results"])
                ev["state"] = "sent" if ok == len(ev["results"]) else (
                    "partial" if ok else "failed")


def _config(recipients=(NUM1,), **sms):
    block = {"recipients": list(recipients), "dry_run": True}
    block.update(sms)
    return {"modules": {"crash_sms": True},
            "crash_detection": {"min_rate_hz": 80, "sms": block}}


def _detected(eid=EID, **extra):
    ev = {"event_id": eid, "ts": WALL0, "source": "accel", "sms_eligible": True,
          "lat": 52.22968, "lon": 21.01223, "fix_age_s": 4.0, "sats": 9,
          "speed_before_kmh": 72.0, "dv_kmh": 45.0, "peak_g": 9.5, "heading": 90.0}
    ev.update(extra)
    return ev


@pytest.fixture
def env(tmp_path):
    clocks = Clocks()
    bus = EventBus()
    states = []
    bus.subscribe(cs.TOPIC_STATE, lambda t, v, ts: states.append(v))
    agent = FakeAgent(clocks)
    holder = {"agent": agent}
    config = _config()

    def make(config=config, path=None):
        m = cs.CrashSms(config, bus, agent_getter=lambda: holder["agent"], clock=clocks.mono,
                        wall_clock=clocks.wall,
                        state_path=str(path or tmp_path / "crash_sms.json"))
        m.subscribe()
        return m

    return SimpleNamespace(clocks=clocks, bus=bus, states=states, agent=agent, holder=holder,
                           config=config, make=make, path=tmp_path / "crash_sms.json",
                           tmp=tmp_path)


def _run(m, seconds=0.0, step=0.25):
    """Drive the worker by hand for ``seconds`` of fake time."""
    m.run_once()
    t = 0.0
    while t < seconds - 1e-9:
        d = min(step, seconds - t)
        m._clock.__self__.advance(d)
        t += d
        m.run_once()


def _last(env):
    return env.states[-1]


def _arm(env, **cfg):
    m = env.make(_config(**cfg)) if cfg else env.make()
    m.run_once()
    env.bus.publish(cs.TOPIC_DETECTED, _detected())
    m.run_once()
    return m


# ── the flow ───────────────────────────────────────────────────────────────

class TestFlow:
    def test_idle_then_arm_hands_the_deadline_to_the_phone(self, env):
        m = env.make()
        m.run_once()
        assert _last(env)["state"] == "idle" and _last(env)["modal"] is False
        env.bus.publish(cs.TOPIC_DETECTED, _detected())
        assert env.agent.calls == []                    # the bus callback only enqueues
        m.run_once()
        arm = env.agent.calls[0]
        assert arm[:4] == ("arm", EID, 45, True)        # config dry_run: true
        assert arm[4:6] == (52.22968, 21.01223) and arm[7:9] == (72.0, 45.0)
        st = _last(env)
        assert st["state"] == "pending" and st["modal"] is True and st["phone_ok"] is True
        assert st["countdown_left_s"] == 45 and st["recipients_n"] == 1
        assert st["dry_run"] is True and st["forced_dry_run_reason"] == ""
        assert st["deadline_ts"] == pytest.approx(WALL0 + 44.5)

    def test_countdown_published_once_a_second(self, env):
        m = _arm(env)
        env.states.clear()
        _run(m, 5.0, step=0.1)
        lefts = [s["countdown_left_s"] for s in env.states]
        assert lefts == [44, 43, 42, 41, 40], lefts     # one publication per second

    def test_cancel_before_the_deadline(self, env):
        m = _arm(env)
        _run(m, 3.0)
        res = m.command("cancel", EID)
        assert res == {"ok": True, "error": ""}
        m.run_once()
        assert ("cancel", EID) in env.agent.calls
        st = _last(env)
        assert st["state"] == "cancelled" and st["modal"] is True
        # the result stays up for 60 s, then the window goes
        _run(m, cs.FINAL_SHOW_S + 1, step=5)
        assert _last(env)["modal"] is False
        # nothing more is asked of the phone about it
        n = len(env.agent.calls)
        _run(m, 120, step=10)
        assert len(env.agent.calls) == n

    def test_send_now_then_sent(self, env):
        m = _arm(env)
        assert m.command("send_now", EID)["ok"]
        m.run_once()
        assert ("send_now", EID) in env.agent.calls
        env.agent.step()                                # phone: deadline → sending
        _run(m, 1.0)
        assert _last(env)["state"] == "sending"
        assert _last(env)["countdown_left_s"] is None
        env.agent.step()                                # phone: sent (dry)
        _run(m, 4.0)
        st = _last(env)
        assert st["state"] == "sent" and st["results"] == [{"state": "sent_dry",
                                                            "verified": False}]
        assert m.command("send_now", EID)["error"] == "not_pending"

    def test_deadline_on_the_phone_without_any_command(self, env):
        m = _arm(env)
        _run(m, 46, step=1)
        env.agent.step()
        _run(m, 4, step=1)
        env.agent.step()
        _run(m, 4, step=1)
        assert _last(env)["state"] == "sent"

    def test_partial(self, env):
        m = _arm(env, recipients=(NUM1, NUM2))
        ev = env.agent.events[EID]
        ev["results"].append({"to": "+48...678", "state": "queued", "tries": 0,
                              "verified": None, "error": "<b>x</b>"})
        ev["state"] = "partial"
        ev["results"][0]["state"] = "sent"
        ev["results"][1]["state"] = "failed"
        _run(m, 3.0)
        st = _last(env)
        assert st["state"] == "partial"
        assert st["results"] == [{"state": "sent", "verified": False},
                                 {"state": "failed", "verified": False}]
        assert st["recipients_n"] == 2

    def test_failed_outcome(self, env):
        m = _arm(env)
        env.agent.outcome = "failed"
        _run(m, 46, step=1)
        env.agent.step()
        env.agent.step()
        _run(m, 4, step=1)
        assert _last(env)["state"] == "failed"

    def test_follow_up_cancel_after_a_sent_sms(self, env):
        m = _arm(env)
        assert m.command("send_now", EID)["ok"]
        m.run_once()
        env.agent.step()
        env.agent.step()
        _run(m, 4)
        assert _last(env)["state"] == "sent" and _last(env)["can_follow_up"] is True
        # A plain cancel (a late ANULUJ tap) is never turned into a cancel SMS…
        assert m.command("cancel", EID)["error"] == "not_cancellable"
        # …"Jestem OK" is its own action, from the window, with the id.
        assert m.command("follow_up")["error"] == "bad_request"
        assert m.command("follow_up", EID, source="swc")["error"] == "bad_request"
        assert m.command("follow_up", EID)["ok"]
        m.run_once()
        st = _last(env)
        assert st["state"] == "cancelled" and st["cancel_sms"] == {"state": "sending"}
        assert st["modal"] is True

    def test_command_validation(self, env):
        m = _arm(env)
        assert m.command("cancel", EID2)["error"] == "unknown_event"
        assert m.command("cancel", "XYZ")["error"] == "bad_request"
        assert m.command("explode", EID)["error"] == "bad_request"
        assert m.command("cancel", EID, source="evil")["error"] == "bad_request"
        assert env.make().command("cancel")["error"] == "no_event"


#: Default countdown 45 s: arming is retried until 15 s are left.
ARM_WINDOW = 45 - cpa.COUNTDOWN_MIN_S
ARM_RETRY_EVERY = cs.ARM_RETRY_EVERY_S


class HoldingAgent(FakeAgent):
    """The arm request REACHES the phone (it saves the event, as
    bcm_agent.py does before answering) but the answer is lost with
    ``answer_error`` — and while ``down`` every other call fails too."""

    def __init__(self, clocks, answer_error="dropped"):
        super().__init__(clocks)
        self.answer_error = answer_error
        self.down = True

    def arm_crash(self, *a, **kw):
        res = FakeAgent.arm_crash(self, *a, **kw)
        return self._err(self.answer_error) if self.down and res["ok"] else res

    def get(self, eid):
        return self._err(self.answer_error) if self.down else FakeAgent.get(self, eid)

    def cancel(self, eid):
        if self.down:
            self._record("cancel", eid)
            return self._err(self.answer_error)
        return FakeAgent.cancel(self, eid)


class TestNoPhone:
    def test_unreachable_at_arm_time_is_failed_no_phone(self, env):
        env.agent.fail = "connect"              # refused / not written: never arrived
        m = _arm(env)
        st = _last(env)
        assert st["state"] == "armed" and st["phone_ok"] is False and st["modal"] is True
        assert st["countdown_left_s"] == 45            # the window counts from the event
        # Arming is retried while the shown countdown has more than the
        # phone's 15 s minimum left (car_phone may need a whole check_sec
        # to bring the forward back after a USB re-enumeration).
        _run(m, ARM_WINDOW - 1, step=0.5)
        assert _last(env)["state"] == "armed"
        _run(m, 2, step=0.5)
        st = _last(env)
        assert st["state"] == "failed_no_phone" and st["error"] == "no_phone"
        assert st["modal"] is True and st["may_send"] is False   # "SMS NIE zostanie wysłany"
        arms = [c for c in env.agent.calls if c[0] == "arm"]
        assert 14 <= len(arms) <= 17
        # "connection refused" cannot have armed the phone: no look-ups later
        env.agent.fail = None
        n = len(env.agent.calls)
        _run(m, 300, step=10)
        assert len(env.agent.calls) == n
        assert _last(env)["modal"] is False

    @pytest.mark.parametrize("code", ["no_forward", "connect"])
    @pytest.mark.parametrize("back_at", [15, 25])
    def test_the_link_back_within_the_countdown_arms_with_what_is_left(self, env, code,
                                                                      back_at):
        env.agent.fail = code
        m = _arm(env)
        lefts = []
        t = 0.0
        while t < back_at:
            _run(m, 0.5, step=0.5)
            t += 0.5
            lefts.append(_last(env)["countdown_left_s"])
        env.agent.fail = None
        _run(m, ARM_RETRY_EVERY + 0.5, step=0.5)
        st = _last(env)
        assert st["state"] == "pending" and st["phone_ok"] is True
        arm = [c for c in env.agent.calls if c[0] == "arm"][-1]
        assert abs(arm[2] - (45 - back_at)) <= 2, arm          # what the window still shows
        # the window's countdown does not jump when the phone takes over
        assert abs(st["countdown_left_s"] - lefts[-1]) <= 3, (st, lefts[-1])

    def test_countdown_of_15_still_gets_the_minimum_retry_window(self, env):
        env.agent.fail = "connect"
        m = _arm(env, countdown_sec=15)
        _run(m, cs.ARM_RETRY_WINDOW_S - 1, step=0.5)
        assert _last(env)["state"] == "armed"
        _run(m, 2, step=0.5)
        assert _last(env)["state"] == "failed_no_phone"

    def test_agent_module_not_running(self, env):
        env.holder["agent"] = None
        m = _arm(env)
        _run(m, ARM_WINDOW + 1, step=1)
        assert _last(env)["state"] == "failed_no_phone"

    def test_a_timeout_may_have_armed_the_phone(self, env):
        env.agent.fail = "timeout"
        m = _arm(env)
        _run(m, ARM_WINDOW + 1, step=1)
        st = _last(env)
        assert st["state"] == "failed_no_phone"
        assert st["may_send"] is True                    # NOT "SMS NIE zostanie wysłany"
        now = env.clocks.mono()
        assert m._cancellable(m._ev, "ui", now)          # the window offers ANULUJ
        assert m._cancellable(m._ev, "swc", now)         # before its deadline: nothing out
        # the phone DID get it: the next look-up brings the countdown back
        env.agent.fail = None
        env.agent.events[EID] = {"id": EID, "state": "armed", "dry": True, "countdown_s": 45,
                                 "deadline": env.clocks.mono() + 14, "results": []}
        _run(m, cs.RECONCILE_EVERY_S + 1, step=1)
        st = _last(env)
        assert st["state"] == "pending" and st["modal"] is True and st["may_send"] is False
        assert 1 <= st["countdown_left_s"] <= 4          # the phone's deadline

    def test_a_timeout_then_the_phone_back_without_it_arms_again(self, env):
        env.agent.fail = "timeout"                       # never executed this time
        m = _arm(env)
        _run(m, 10, step=1)
        env.agent.fail = None
        _run(m, ARM_RETRY_EVERY + 1, step=0.5)
        assert _last(env)["state"] == "pending"
        assert env.agent.events[EID]["state"] == "armed"

    def test_dropped_arm_then_anuluj_reaches_the_phone(self, env):
        """The arm arrived, the answer was lost ("dropped": the USB link
        broke, or the agent died after saving it and boot_bcm_agent.sh
        restarts it). ANULUJ must reach the phone — a local "cancelled"
        would let the phone send what the driver cancelled."""
        agent = env.holder["agent"] = HoldingAgent(env.clocks)
        m = _arm(env)
        assert EID in agent.events and _last(env)["state"] == "armed"
        assert m.command("cancel", EID)["ok"]
        m.run_once()
        assert ("cancel", EID) in agent.calls
        st = _last(env)
        assert st["cancel_pending"] is True              # not finished locally
        agent.down = False
        _run(m, cs.RETRY_MAX_S + 1, step=1)
        assert agent.events[EID]["state"] == "cancelled"
        assert _last(env)["state"] == "cancelled" and _last(env)["error"] == ""

    def test_dropped_arm_without_cancel_is_looked_up_and_comes_back(self, env):
        agent = env.holder["agent"] = HoldingAgent(env.clocks)
        m = _arm(env)
        _run(m, ARM_WINDOW + 1, step=1)
        st = _last(env)
        assert st["state"] == "failed_no_phone" and st["may_send"] is True
        agent.down = False
        _run(m, cs.RECONCILE_EVERY_S + 1, step=1)
        st = _last(env)
        assert st["state"] == "pending" and st["may_send"] is False
        assert st["countdown_left_s"] > 0

    def test_anuluj_in_the_may_send_window_reaches_the_phone(self, env):
        agent = env.holder["agent"] = HoldingAgent(env.clocks)
        m = _arm(env)
        _run(m, ARM_WINDOW + 1, step=1)
        assert _last(env)["may_send"] is True
        assert m.command("cancel", EID)["ok"]
        _run(m, 1)
        assert _last(env)["cancel_pending"] is True and _last(env)["may_send"] is True
        agent.down = False
        _run(m, cs.RETRY_MAX_S + 1, step=1)
        assert agent.events[EID]["state"] == "cancelled"
        st = _last(env)
        assert st["state"] == "cancelled" and st["cancel_pending"] is False
        # past the deadline a steering-wheel press would no longer count
        agent2 = env.holder["agent"] = HoldingAgent(env.clocks)
        m.stop()
        env.clocks.advance(cs.DAY_S)
        m = env.make()
        m.run_once()
        env.bus.publish(cs.TOPIC_DETECTED, _detected(eid=EID2))
        _run(m, 46, step=1)
        assert _last(env)["state"] == "failed_no_phone" and _last(env)["may_send"] is True
        assert m.command("cancel", source="swc")["error"] == "not_cancellable"
        assert m.command("cancel", EID2)["ok"]                   # the window still may
        assert agent2 is not None

    def test_cancel_while_arming_with_nothing_delivered_is_local(self, env):
        env.agent.fail = "connect"
        m = _arm(env)
        assert m.command("cancel", EID)["ok"]
        m.run_once()
        assert _last(env)["state"] == "cancelled"
        assert not any(c[0] == "cancel" for c in env.agent.calls)

    def test_cancel_reaches_the_phone_when_it_comes_back(self, env):
        m = _arm(env)
        env.agent.fail = "timeout"
        assert m.command("cancel", EID)["ok"]
        _run(m, 6, step=1)
        st = _last(env)
        assert st["state"] == "pending" and st["cancel_pending"] is True
        assert st["phone_ok"] is False
        env.agent.fail = None
        _run(m, cs.RETRY_MAX_S + 1, step=1)
        assert _last(env)["state"] == "cancelled"
        assert env.agent.events[EID]["state"] == "cancelled"

    def test_phone_refusals_are_final(self, env):
        env.agent.refuse = (409, "crash_sms_off")
        m = _arm(env)
        st = _last(env)
        assert st["state"] == "failed" and st["error"] == "crash_sms_off"
        assert len([c for c in env.agent.calls if c[0] == "arm"]) == 1

    def test_no_recipients_never_arms(self, env):
        m = env.make(_config(recipients=()))
        m.run_once()
        env.bus.publish(cs.TOPIC_DETECTED, _detected())
        m.run_once()
        st = _last(env)
        assert st["state"] == "failed" and st["error"] == "no_recipients" and st["modal"]
        assert env.agent.calls == []


class TestEventFilter:
    @pytest.mark.parametrize("change", [
        {"source": "gps", "sms_eligible": False},       # the GPS-only path: never an SMS
        {"source": "gps", "sms_eligible": True},        # even if someone sets the flag
        {"sms_eligible": False},                        # accel without GPS speed
        {"sms_eligible": "true"},
        {"event_id": "not-hex"},
        {"event_id": None},
    ])
    def test_ignored(self, env, change):
        m = env.make()
        m.run_once()
        env.bus.publish(cs.TOPIC_DETECTED, _detected(**change))
        m.run_once()
        assert env.agent.calls == [] and _last(env)["state"] == "idle"

    @pytest.mark.parametrize("value", [None, "x", 5, [], {"event_id": EID}])
    def test_garbage_is_ignored(self, env, value):
        m = env.make()
        env.bus.publish(cs.TOPIC_DETECTED, value)
        m.run_once()
        assert env.agent.calls == []

    def test_implausible_numbers_go_as_unknown(self, env):
        m = env.make()
        env.bus.publish(cs.TOPIC_DETECTED, _detected(lat=float("nan"), lon=500,
                                                     speed_before_kmh=-1, dv_kmh="x"))
        m.run_once()
        arm = env.agent.calls[0]
        assert arm[4:9] == (None, None, 4, None, None)

    def test_a_second_event_while_one_runs_is_covered_by_it(self, env):
        m = _arm(env)
        env.bus.publish(cs.TOPIC_DETECTED, _detected(eid=EID2))
        m.run_once()
        assert _last(env)["event_id"] == EID
        assert len([c for c in env.agent.calls if c[0] == "arm"]) == 1

    def test_auto_cancel_when_the_car_drove_on(self, env):
        m = _arm(env)
        env.bus.publish(cs.TOPIC_OUTCOME, {"event_id": EID, "outcome": "cancelled",
                                           "reason": "no_stop"})
        m.run_once()
        assert _last(env)["state"] == "cancelled"

    def test_auto_cancel_never_once_sending(self, env):
        m = _arm(env)
        m.command("send_now", EID)
        m.run_once()
        env.agent.step()
        _run(m, 4)
        assert _last(env)["state"] == "sending"
        env.bus.publish(cs.TOPIC_OUTCOME, {"event_id": EID, "outcome": "cancelled"})
        m.run_once()
        assert not any(c[0] == "cancel" for c in env.agent.calls)

    def test_swc_cancel_without_an_id(self, env):
        m = _arm(env)
        env.bus.publish(cs.CMD_CANCEL, {"source": "swc"})
        m.run_once()
        assert _last(env)["state"] == "cancelled"

    @pytest.mark.parametrize("source", ["auto", "swc", "bus"])
    def test_cancel_queued_in_pending_is_dropped_once_sending(self, env, source):
        """Accepted while pending, handled after a look-up adopted
        "sending": the worker checks again — nothing reaches the phone."""
        m = _arm(env)
        assert m.command("cancel", None if source == "swc" else EID, source=source)["ok"]
        with m._lock:
            m._ev["state"] = "sending"                       # a look-up adopted it first
        env.agent.events[EID]["state"] = "sending"
        m.run_once()
        assert not any(c[0] == "cancel" for c in env.agent.calls)
        assert _last(env)["cancel_pending"] is False

    def test_bus_command_with_a_bad_id_does_nothing(self, env):
        m = _arm(env)
        env.bus.publish(cs.CMD_CANCEL, {"event_id": "<script>"})
        m.run_once()
        assert _last(env)["state"] == "pending"


def _sent(env, m):
    """Arm, send now, the phone sends: the event is "sent" (a REAL crash
    SMS went out as far as the follow-up is concerned)."""
    assert m.command("send_now", EID)["ok"]
    m.run_once()
    env.agent.step()
    env.agent.step()
    _run(m, 4)
    assert _last(env)["state"] == "sent" and _last(env)["can_follow_up"] is True


class TestDualUseButtons:
    """A steering-wheel button mapped to crash_cancel keeps its fixed
    action (hang-up, volume …): it is pressed for other reasons too, above
    all right after a crash. Only the running countdown may be cancelled
    by it — never the "Jestem OK" follow-up (a false "ODWOLANE" SMS to the
    family) and never while the SMS is being sent."""

    def _wheel(self, env):
        from src.input.action_dispatch import ActionDispatcher
        from src.input.input_bridge import InputBridge
        mapping = {"phone_hangup": ["SWC_HANGUP", "SWC2_HANGUP"],
                   "crash_cancel": ["SWC_HANGUP", ""]}

        class Cfg:
            def get(self, key, default=None):
                return mapping if key == "swc.mapping" else default
        ActionDispatcher(env.bus)
        InputBridge(env.bus, Cfg())
        hangups = []
        env.bus.subscribe("bt.cmd.hangup", lambda t, v, ts: hangups.append(v))
        return hangups

    @pytest.mark.parametrize("after", [30.0, 300.0, 14 * 60.0])
    def test_hangup_after_a_sent_sms_sends_no_cancel_sms(self, env, after):
        hangups = self._wheel(env)
        m = _arm(env)
        _sent(env, m)
        _run(m, after, step=10)
        env.bus.publish("input.raw_keycode", 64)          # HANGUP: the family calls back
        _run(m, 1)
        assert hangups, "the button lost its own action"
        assert not any(c[0] == "cancel" for c in env.agent.calls)
        st = _last(env)
        assert st["state"] == "sent" and st["cancel_sms"] is None
        assert st["can_follow_up"] is True                 # the window's button still works
        assert env.agent.events[EID]["state"] == "sent"

    def test_bare_bus_cancel_after_sent_is_refused(self, env):
        m = _arm(env)
        _sent(env, m)
        env.bus.publish(cs.CMD_CANCEL, {"source": "swc"})
        env.bus.publish(cs.CMD_CANCEL, {"source": "bus", "event_id": EID})
        _run(m, 1)
        assert not any(c[0] == "cancel" for c in env.agent.calls)

    def test_swc_during_sending_is_ignored(self, env):
        hangups = self._wheel(env)
        m = _arm(env)
        assert m.command("send_now", EID)["ok"]
        m.run_once()
        env.agent.step()
        _run(m, 4)
        assert _last(env)["state"] == "sending"
        env.bus.publish("input.raw_keycode", 64)
        _run(m, 1)
        assert hangups and not any(c[0] == "cancel" for c in env.agent.calls)
        # the window's ANULUJ still decides while sending
        assert m.command("cancel", EID)["ok"]

    def test_swc_after_the_shown_deadline_is_ignored(self, env):
        m = _arm(env)
        env.agent.fail = "timeout"                         # the phone stops answering
        _run(m, 46, step=1)
        assert _last(env)["state"] == "pending" and _last(env)["countdown_left_s"] == 0
        assert m.command("cancel", source="swc")["error"] == "not_cancellable"

    def test_swc_during_the_countdown_cancels(self, env):
        hangups = self._wheel(env)
        m = _arm(env)
        _run(m, 5)
        env.bus.publish("input.raw_keycode", 64)
        _run(m, 1)
        assert hangups and ("cancel", EID) in env.agent.calls
        assert _last(env)["state"] == "cancelled" and _last(env)["cancel_sms"] is None


class TestFollowUp:
    def test_no_busy_loop_when_the_phone_forgets_the_event(self, env):
        """After "Jestem OK" the phone forgets the event (wiped / reinstalled):
        the look-up must not repeat back to back for an hour."""
        m = _arm(env)
        _sent(env, m)
        assert m.command("follow_up", EID)["ok"]
        m.run_once()
        assert _last(env)["cancel_sms"] == {"state": "sending"}
        env.clocks.advance(4)
        env.agent.events.clear()
        n = len(env.agent.calls)
        waits = [m.run_once() for _ in range(50)]          # the clock stands still
        gets = [c for c in env.agent.calls[n:] if c[0] == "get"]
        assert len(gets) <= 1, len(gets)
        assert all(w > 0 for w in waits[1:]), waits[:5]
        st = _last(env)
        assert st["state"] == "cancelled" and st["cancel_sms"] == {"state": "failed"}

    def test_follow_up_on_a_forgotten_event_keeps_saying_sent(self, env):
        m = _arm(env)
        _sent(env, m)
        env.agent.events.clear()                           # the phone forgot it
        assert m.command("follow_up", EID)["ok"]
        m.run_once()
        st = _last(env)
        assert st["state"] == "sent"                       # the crash SMS DID go out
        assert st["cancel_sms"] == {"state": "failed"} and st["cancel_pending"] is False
        assert st["can_follow_up"] is True                 # it may be tried again

    def test_follow_up_window_closes_after_15_min(self, env):
        m = _arm(env)
        _sent(env, m)
        _run(m, cs.FOLLOW_UP_WINDOW_S + 5, step=30)
        assert _last(env)["can_follow_up"] is False
        assert m.command("follow_up", EID)["error"] == "not_cancellable"

    def test_spin_guard(self, env):
        """Defense in depth: a handler path that does not schedule the next
        try gets at most one immediate repeat."""
        m = _arm(env)
        with m._lock:
            m._ev["next_try"] = env.clocks.mono()
        real = m._lookup
        calls = []
        m._lookup = lambda ev, now, final_try=False: calls.append(now) or "error"
        try:
            waits = [m.run_once() for _ in range(10)]
        finally:
            m._lookup = real
        assert len(calls) <= 2 and waits[-1] > 0, (calls, waits)


class TestUnconfirmed:
    def test_phone_silent_after_the_deadline(self, env):
        m = _arm(env)
        _run(m, 5)
        env.agent.fail = "timeout"                         # the phone drops out
        _run(m, 40 + cs.UNCONFIRMED_AFTER_S - 1, step=1)
        st = _last(env)
        assert st["state"] == "pending" and st["unconfirmed"] is False
        _run(m, 6, step=1)
        st = _last(env)
        assert st["unconfirmed"] is True and st["modal"] is True
        assert st["countdown_left_s"] == 0
        n = len(env.agent.calls)
        _run(m, cs.FINAL_SHOW_S + 1, step=1)
        assert len(env.agent.calls) > n                    # still looked up
        assert _last(env)["modal"] is False                # not 15 min over AA
        # the phone comes back: it did send
        env.agent.fail = None
        env.agent.step()
        env.agent.step()
        _run(m, cs.RETRY_MAX_S + 1, step=1)
        st = _last(env)
        assert st["state"] == "sent" and st["unconfirmed"] is False and st["modal"] is True

    def test_suspend_during_the_countdown(self, env):
        """Plan F "zgaszenie/S3 w trakcie": BCM's monotonic clock stops in
        S3 while the wall clock and the PHONE's deadline go on. The first
        look-up after the resume corrects the window from the phone."""
        m = _arm(env)
        _run(m, 5)
        assert _last(env)["countdown_left_s"] == 40
        env.clocks.w += 30                                 # suspended 30 s
        env.agent.events[EID]["deadline"] -= 30            # the phone's time went on
        _run(m, cs.POLL_PENDING_S + 0.5, step=0.5)
        left = _last(env)["countdown_left_s"]
        assert 7 <= left <= 9, left
        # a longer suspend: the phone sent meanwhile
        env.clocks.w += 60
        env.agent.events[EID]["deadline"] -= 60
        env.agent.step()
        env.agent.step()
        _run(m, cs.POLL_PENDING_S + 0.5, step=0.5)
        assert _last(env)["state"] == "sent"


class TestSmallFixes:
    def test_phone_confirmation_clears_a_stale_no_phone(self, env):
        agent = env.holder["agent"] = HoldingAgent(env.clocks, "timeout")
        m = _arm(env)
        _run(m, ARM_WINDOW + 1, step=1)
        assert _last(env)["error"] == "no_phone"
        agent.down = False
        _run(m, cs.RECONCILE_EVERY_S + 1, step=1)
        assert _last(env)["state"] == "pending"
        assert m.command("cancel", EID)["ok"]
        m.run_once()
        st = _last(env)
        assert st["state"] == "cancelled" and st["error"] == ""

    def test_fix_age_is_not_inflated_by_arm_retries(self, env):
        env.agent.fail = "connect"
        m = _arm(env)
        _run(m, 10, step=1)
        env.agent.fail = None
        _run(m, 3, step=1)
        arms = [c for c in env.agent.calls if c[0] == "arm"]
        assert {c[6] for c in arms} == {4}                 # crash_detect's fix age

    def test_config_typo_is_warned_once(self, caplog):
        bad = {"crash_detection": {"sms": {"dry_run": "nope", "countdown_sec": "x"}}}
        with caplog.at_level(logging.WARNING, logger="bcm.safety.crash_sms"):
            for _ in range(200):
                cs.load_sms_config(bad)
        msgs = [r.getMessage() for r in caplog.records]
        assert len([x for x in msgs if "dry_run" in x]) == 1
        assert len([x for x in msgs if "countdown_sec" in x]) == 1

    def test_new_event_while_the_phone_holds_the_reconciled_one(self, env):
        agent = env.holder["agent"] = HoldingAgent(env.clocks, "timeout")
        m = _arm(env)
        _run(m, ARM_WINDOW + 1, step=1)
        assert _last(env)["may_send"] is True
        agent.down = False                                  # the phone holds EID
        env.bus.publish(cs.TOPIC_DETECTED, _detected(eid=EID2))
        m.run_once()
        st = _last(env)
        assert st["event_id"] == EID and st["state"] == "pending"   # cancellable again
        assert not any(c[0] == "arm" and c[1] == EID2 for c in agent.calls)

    def test_new_event_when_the_phone_never_held_the_reconciled_one(self, env):
        agent = env.holder["agent"] = HoldingAgent(env.clocks, "timeout")
        m = _arm(env)
        _run(m, ARM_WINDOW + 1, step=1)
        agent.down = False
        agent.events.clear()                                # it never got there
        env.bus.publish(cs.TOPIC_DETECTED, _detected(eid=EID2))
        m.run_once()
        st = _last(env)
        assert st["event_id"] == EID2 and st["state"] == "pending"

    def test_new_event_while_the_phone_is_still_silent(self, env):
        agent = env.holder["agent"] = HoldingAgent(env.clocks, "timeout")
        m = _arm(env)
        _run(m, ARM_WINDOW + 1, step=1)
        env.bus.publish(cs.TOPIC_DETECTED, _detected(eid=EID2))
        m.run_once()
        assert _last(env)["event_id"] == EID and _last(env)["may_send"] is True
        assert agent is not None


class TestLimits:
    def _sent(self, env, m, eid):
        env.bus.publish(cs.TOPIC_DETECTED, _detected(eid=eid))
        m.run_once()
        m.command("send_now", eid)
        m.run_once()
        env.agent.step()
        env.agent.step()
        _run(m, 4)
        assert _last(env)["state"] == "sent"

    def test_cooldown(self, env):
        m = env.make()
        self._sent(env, m, EID)
        env.clocks.advance(5 * 60)
        env.bus.publish(cs.TOPIC_DETECTED, _detected(eid=EID2))
        m.run_once()
        st = _last(env)
        assert st["state"] == "limited" and st["error"] == "cooldown" and st["modal"]
        assert not any(c[0] == "arm" and c[1] == EID2 for c in env.agent.calls)

    def test_daily_limit(self, env):
        m = env.make(_config(cooldown_min=1, max_per_day=2))
        ids = ["%032x" % i for i in range(1, 4)]
        self._sent(env, m, ids[0])
        env.clocks.advance(120)
        self._sent(env, m, ids[1])
        env.clocks.advance(120)
        env.bus.publish(cs.TOPIC_DETECTED, _detected(eid=ids[2]))
        m.run_once()
        assert _last(env)["state"] == "limited" and _last(env)["error"] == "daily_limit"

    def test_a_false_alarm_cancelled_in_time_does_not_count(self, env):
        m = _arm(env)
        m.command("cancel", EID)
        m.run_once()
        env.clocks.advance(60)
        env.bus.publish(cs.TOPIC_DETECTED, _detected(eid=EID2))
        m.run_once()
        assert _last(env)["state"] == "pending" and _last(env)["event_id"] == EID2

    def test_test_mode_events_do_not_block_a_real_one(self, env):
        m = env.make()
        self._sent(env, m, EID)                          # dry_run: true
        _gate_ok(env)
        m2 = env.make(_config(dry_run=False))
        env.clocks.advance(60)
        env.bus.publish(cs.TOPIC_DETECTED, _detected(eid=EID2))
        m.stop()
        m2.run_once()
        st = _last(env)
        assert st["state"] == "pending" and st["dry_run"] is False


# ── safety gate ────────────────────────────────────────────────────────────

def _gate_ok(env):
    env.agent.facts.update(dry_run=False, last_verified_test_ts=env.clocks.wall() - 86400)
    env.agent.state.update(state="ok", paired=True, reason="",
                           last_ok_ts=env.clocks.wall())
    env.bus.publish(cs.SENSORS_TOPIC, {"state": "streaming", "rate_hz": 100.0,
                                       "calib_ok": True, "error": "", "since": 1.0})
    _g(env)


def _g(env, **extra):
    """A fresh phone.g_force (what the idle indicator reads)."""
    msg = {"ts": env.clocks.wall(), "mono": env.clocks.mono(), "rate_hz": 100.0,
           "calib_ok": True, "sat": False}
    msg.update(extra)
    env.bus.publish(cs.G_TOPIC, msg)


class TestSafetyGate:
    def test_all_checks_pass_real_sms(self, env):
        _gate_ok(env)
        m = _arm(env, dry_run=False)
        assert env.agent.calls[0][3] is False             # arm(dry_run=False)
        st = _last(env)
        assert st["dry_run"] is False and st["forced_dry_run_reason"] == ""

    @pytest.mark.parametrize("breaks, reason", [
        (lambda e: e.holder.update(agent=None), "agent_not_ready"),
        (lambda e: e.agent.state.update(state="error"), "agent_not_ready"),
        (lambda e: e.agent.state.update(paired=False), "agent_not_ready"),
        (lambda e: e.agent.state.update(reason="config_pending"), "agent_not_ready"),
        (lambda e: e.agent.state.update(last_ok_ts=e.clocks.wall() - 600), "agent_not_ready"),
        (lambda e: e.agent.facts.update(dry_run=True), "agent_not_ready"),
        (lambda e: e.agent.facts.update(last_verified_test_ts=None), "no_verified_test"),
        (lambda e: e.agent.facts.update(last_verified_test_ts=e.clocks.wall() - 31 * 86400),
         "test_too_old"),
    ])
    def test_forced_dry_run(self, env, breaks, reason):
        _gate_ok(env)
        breaks(env)
        m = _arm(env, dry_run=False)
        st = _last(env)
        assert st["dry_run"] is True and st["forced_dry_run_reason"] == reason
        if env.holder["agent"] is not None:
            assert env.agent.calls[0][3] is True          # arm(dry_run=True)
        assert m is not None

    @pytest.mark.parametrize("breaks, reason", [
        (lambda e: e.bus.publish(cs.SENSORS_TOPIC, {"state": "stale", "rate_hz": 100,
                                                    "calib_ok": True}),
         "sensors_not_streaming"),
        (lambda e: e.clocks.advance(cs.G_FRESH_S + 1), "sensors_not_streaming"),
        (lambda e: _g(e, rate_hz=50.0), "sensor_rate_low"),
        (lambda e: _g(e, calib_ok=False), "not_calibrated"),
    ])
    def test_sensors_only_in_the_idle_indicator(self, env, breaks, reason):
        """The sensors are shown in Settings (idle payload) — but an accel
        event already proves them, so they never force a real crash into
        test mode."""
        _gate_ok(env)
        env.agent.state["last_ok_ts"] = env.clocks.wall() + 10
        breaks(env)
        m = env.make(_config(dry_run=False))
        m.run_once()
        st = _last(env)
        assert st["state"] == "idle" and st["forced_dry_run_reason"] == reason
        assert st["dry_run"] is True
        env.bus.publish(cs.TOPIC_DETECTED, _detected())
        m.run_once()
        assert env.agent.calls[0][3] is False             # arm(dry_run=False): REAL
        assert _last(env)["forced_dry_run_reason"] == ""

    def test_lagging_published_rate_never_turns_a_real_crash_into_a_test(self, env):
        """phone_sensors.state republishes rate_hz only on a 10 % move: it
        may still say 78 Hz while the stream (and crash_detect) runs at 85."""
        _gate_ok(env)
        env.bus.publish(cs.SENSORS_TOPIC, {"state": "streaming", "rate_hz": 78.0,
                                           "calib_ok": True, "error": "", "since": 1.0})
        _g(env, rate_hz=85.0)
        m = _arm(env, dry_run=False)
        assert env.agent.calls[0][3] is False
        assert _last(env)["dry_run"] is False and _last(env)["forced_dry_run_reason"] == ""
        assert m is not None

    def test_config_dry_run_is_not_a_forced_reason(self, env):
        _gate_ok(env)
        _arm(env)                                         # dry_run: true in the config
        assert _last(env)["dry_run"] is True and _last(env)["forced_dry_run_reason"] == ""

    @pytest.mark.parametrize("value", ["false", 0, None, "no"])
    def test_only_an_explicit_false_leaves_test_mode(self, value):
        assert cs.load_sms_config({"crash_detection": {"sms": {"dry_run": value}}}).dry_run

    def test_reason_logged_once(self, env, caplog):
        _gate_ok(env)
        env.agent.facts["last_verified_test_ts"] = None
        m = env.make(_config(dry_run=False))
        with caplog.at_level(logging.WARNING, logger="bcm.safety.crash_sms"):
            _run(m, 60, step=1)
        hits = [r for r in caplog.records if "TEST MODE" in r.getMessage()]
        assert len(hits) == 1 and "no_verified_test" in hits[0].getMessage()
        assert _last(env)["forced_dry_run_reason"] == "no_verified_test"   # idle payload


# ── restart / persistence ──────────────────────────────────────────────────

class TestRestart:
    def test_resume_a_pending_event(self, env):
        m = _arm(env)
        _run(m, 5)
        m.stop()
        # BCM restarts 10 s later: a new monotonic clock, the wall moved on
        env.clocks.t = 50.0
        env.clocks.w += 10
        env.agent.c.t = env.clocks.t
        env.agent.events[EID]["deadline"] = env.clocks.mono() + 30
        env.states.clear()
        m2 = env.make()
        m2.run_once()
        st = _last(env)
        assert st["state"] == "pending" and st["event_id"] == EID and st["modal"] is True
        assert 29 <= st["countdown_left_s"] <= 31
        assert ("get", EID) in env.agent.calls

    @pytest.mark.parametrize("down_for", [20.0, 60.0])
    def test_resume_after_a_reboot_waits_for_the_forward(self, env, down_for):
        """Power lost at the impact before the arm got through: BCM reboots
        40 s later and car_phone needs adb + device + USB re-enumeration
        before the agent's forward is back (> 10 s). Arming is retried
        until the event is REARM_MAX_AGE_S old."""
        env.agent.fail = "connect"
        m = _arm(env)
        m.stop()
        env.clocks.advance(40)
        env.agent.fail = "no_forward"
        m2 = env.make()
        _run(m2, down_for, step=1)
        assert _last(env)["state"] == "armed"
        env.agent.fail = None
        _run(m2, 3, step=1)
        assert _last(env)["state"] == "pending"
        assert [c for c in env.agent.calls if c[0] == "arm"][-1][2] == cpa.COUNTDOWN_MIN_S
        env.agent.step()
        _run(m2, 16, step=1)
        env.agent.step()
        env.agent.step()
        _run(m2, 4, step=1)
        assert _last(env)["state"] == "sent"

    def test_resume_gives_up_at_rearm_max_age(self, env):
        env.agent.fail = "connect"
        m = _arm(env)
        m.stop()
        env.clocks.advance(40)
        env.agent.fail = "no_forward"
        m2 = env.make()
        _run(m2, cs.REARM_MAX_AGE_S - 40 + 2, step=1)
        assert _last(env)["state"] == "failed_no_phone"
        env.agent.fail = None
        n = len(env.agent.calls)
        _run(m2, 30, step=1)
        assert not any(c[0] == "arm" for c in env.agent.calls[n:])

    def test_resume_while_arming_arms_again(self, env):
        env.agent.fail = "connect"
        m = _arm(env)
        m.stop()
        env.agent.fail = None
        env.clocks.advance(20)
        m2 = env.make()
        m2.run_once()
        arms = [c for c in env.agent.calls if c[0] == "arm"]
        assert arms[-1][2] == 25                          # 45 s minus the 20 s gone
        assert _last(env)["state"] == "pending"

    def test_an_old_arming_event_is_not_armed_hours_later(self, env):
        env.agent.fail = "connect"
        m = _arm(env)
        m.stop()
        env.agent.fail = None
        env.clocks.advance(3 * 3600)
        n = len([c for c in env.agent.calls if c[0] == "arm"])
        m2 = env.make()
        m2.run_once()
        assert len([c for c in env.agent.calls if c[0] == "arm"]) == n
        st = _last(env)
        assert st["state"] in ("armed", "failed_no_phone") and st["modal"] is False

    def test_saved_file(self, env):
        m = _arm(env)
        data = json.loads(env.path.read_text())
        assert data["event"]["id"] == EID and data["event"]["state"] == "pending"
        assert data["event"]["arm"] is None               # the position is on the phone
        assert os.stat(env.path).st_mode & 0o777 == 0o600
        text = env.path.read_text()
        assert NUM1 not in text and "52.2" not in text    # no numbers, no position
        assert m is not None

    def test_look_ups_do_not_rewrite_an_unchanged_file(self, env):
        m = _arm(env)
        writes = []
        real = cs.atomic_write_json
        cs.atomic_write_json = lambda *a, **kw: (writes.append(a[0]), real(*a, **kw))
        try:
            _run(m, 10, step=1)
            assert len([c for c in env.agent.calls if c[0] == "get"]) >= 4
            assert writes == []
            m.command("cancel", EID)
            m.run_once()
            assert len(writes) >= 1                        # a change is written
        finally:
            cs.atomic_write_json = real
        assert json.loads(env.path.read_text())["event"]["state"] == "cancelled"

    def test_position_kept_until_the_phone_has_it(self, env):
        env.agent.fail = "connect"
        _arm(env)
        assert json.loads(env.path.read_text())["event"]["arm"]["lat"] == 52.22968

    @pytest.mark.parametrize("content", [b"garbage", b"[]", b'{"version":1,"event":{"id":"x"}}',
                                         b'{"version":1,"event":null,"history":"x"}',
                                         b"{" + b" " * (cs.STATE_FILE_MAX + 10) + b"}"])
    def test_a_damaged_file_is_ignored(self, env, content, caplog):
        env.path.write_bytes(content)
        m = env.make()
        with caplog.at_level(logging.WARNING):
            m.run_once()
        assert _last(env)["state"] == "idle"

    def test_history_survives_a_restart(self, env):
        m = env.make()
        TestLimits()._sent(env, m, EID)
        m.stop()
        env.clocks.advance(60)
        m2 = env.make()
        m2.run_once()
        env.bus.publish(cs.TOPIC_DETECTED, _detected(eid=EID2))
        m2.run_once()
        assert _last(env)["state"] == "limited"


# ── test SMS ───────────────────────────────────────────────────────────────

class TestTestSms:
    def test_real_test_sms(self, env):
        m = env.make()
        m.run_once()
        assert m.request_test() == {"ok": True, "error": ""}
        assert m.request_test()["error"] == "busy"
        m.run_once()
        assert ("test", False, True) in env.agent.calls    # real=True
        st = _last(env)
        assert st["test"]["request"] == "accepted" and env.agent.kicks >= 1
        env.agent.facts.update(last_test={"state": "sent", "ts": WALL0, "dry_run": False,
                                          "verified": True},
                               last_verified_test_ts=WALL0)
        _run(m, cs.TEST_KICK_EVERY_S + 1, step=1)
        assert env.agent.kicks >= 2
        assert _last(env)["test"]["verified"] is True
        assert _last(env)["test"]["last_verified_ts"] == WALL0

    def test_refused_by_the_phone(self, env):
        env.agent.test_answer = {"ok": False, "status": 429, "data": {}, "error": "rate_limited",
                                 "detail": ""}
        m = env.make()
        m.request_test()
        m.run_once()
        assert _last(env)["test"] == dict(_last(env)["test"], request="error",
                                          error="rate_limited")

    def test_refused_while_the_phone_has_the_old_recipients(self, env):
        """Recipients saved a moment ago and not pushed yet: a test now
        would go to the phone's OLD list and look verified for the new."""
        m = env.make()
        env.agent.state["reason"] = "config_pending"
        assert m.request_test()["error"] == "config_pending"
        env.agent.state["reason"] = ""
        env.agent.facts["config_hash"] = "0" * 16           # the phone holds another config
        assert m.request_test()["error"] == "config_pending"
        env.agent.facts["config_hash"] = cpa.config_hash(cpa.desired_config(env.config))
        assert m.request_test() == {"ok": True, "error": ""}

    def test_preconditions(self, env):
        assert env.make(_config(recipients=())).request_test()["error"] == "no_recipients"
        env.holder["agent"] = None
        assert env.make().request_test()["error"] == "not_running"


# ── threads ────────────────────────────────────────────────────────────────

class TestThreads:
    def test_agent_calls_only_on_the_worker(self, tmp_path):
        bus = EventBus()
        clocks = Clocks(mono=time.monotonic(), wall=time.time())
        agent = FakeAgent(clocks)
        agent.c = SimpleNamespace(mono=time.monotonic, wall=time.time)
        m = cs.CrashSms(_config(), bus, agent_getter=lambda: agent,
                        state_path=str(tmp_path / "s.json"))
        m.start()
        try:
            bus.publish(cs.TOPIC_DETECTED, _detected(ts=time.time()))
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                st = m.state
                if st and st["state"] == "pending":
                    break
                time.sleep(0.02)
            assert m.state["state"] == "pending"
            assert agent.threads == {"crash-sms"}
        finally:
            m.stop()

    def test_start_and_stop_register_the_instance(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)                      # data/crash_sms.json goes here
        bus = EventBus()
        mod = cs.start_crash_sms(_config(), bus)
        try:
            assert cs.get_crash_sms() is mod
        finally:
            mod.stop()
        assert cs.get_crash_sms() is None
        assert mod.command("cancel")["error"] == "stopped"

    def test_shutdown_stops_it(self, env):
        m = env.make()
        env.bus.publish("power.shutting_down", True)
        assert m.command("cancel")["error"] == "stopped"


# ── the agent client additions (car_phone_agent) ───────────────────────────

class TestAgentClientFacts:
    def test_parse_health_facts(self):
        out = cpa.parse_health_facts({
            "last_verified_test_ts": WALL0, "dry_run": False, "recipients_n": 2,
            "active_event": EID, "last_test": {"state": "sent", "ts": WALL0, "dry_run": False,
                                               "verified": True}})
        assert out == {"last_verified_test_ts": WALL0, "dry_run": False, "recipients_n": 2,
                       "active_event": EID, "last_test": {"state": "sent", "ts": WALL0,
                                                          "dry_run": False, "verified": True},
                       "config_hash": None}
        assert cpa.parse_health_facts({"config_hash": "0123456789abcdef"})["config_hash"] \
            == "0123456789abcdef"
        assert cpa.parse_health_facts({"config_hash": "<b>"})["config_hash"] is None

    @pytest.mark.parametrize("obj", [
        None, [], {"last_verified_test_ts": "1763000000", "dry_run": "no", "recipients_n": 9,
                   "active_event": "<b>", "last_test": {"state": "<b>"}},
        {"last_verified_test_ts": float("inf"), "recipients_n": True, "last_test": "x"},
    ])
    def test_garbage_facts(self, obj):
        assert cpa.parse_health_facts(obj) == cpa._EMPTY_FACTS

    def test_kick_polls_now(self, tmp_path):
        bus = EventBus()
        cfg = {"network": {"car_phone": {"agent": {"secret": "ab" * 32}}}}
        t = [100.0]
        agent = cpa.CarPhoneAgent(cfg, bus, state_path=str(tmp_path / "a.json"),
                                  clock=lambda: t[0])
        bus.publish(cpa.CAR_PHONE_TOPIC, {"state": "connected",
                                          "forwards": {"agent": {"local": 952, "ok": True}}})
        polls = []
        agent.poll = lambda: polls.append(t[0]) or setattr(agent, "_next_poll", t[0] + 30)
        agent.cycle()
        assert polls == [100.0]
        t[0] += 5
        agent.cycle()
        assert polls == [100.0]                           # 30 s cadence
        agent.kick()
        agent.cycle()
        assert polls == [100.0, 105.0]
        agent._healthy({"version": "1.0.0", "last_verified_test_ts": WALL0, "dry_run": False})
        facts = agent.health_facts()
        assert facts["last_verified_test_ts"] == WALL0 and facts["dry_run"] is False


# ── web routes and the dashboard payload ───────────────────────────────────

class _FakeModule:
    def __init__(self):
        self.calls = []
        self.answer = {"ok": True, "error": ""}

    def command(self, action, event_id=None, source="ui"):
        self.calls.append((action, event_id, source))
        return dict(self.answer)

    def request_test(self):
        self.calls.append(("test",))
        return dict(self.answer)


@pytest.fixture
def web(monkeypatch, tmp_path):
    def refuse(*a, **kw):
        raise AssertionError("no subprocess from web_viewer here")
    monkeypatch.setattr(wv, "subprocess", SimpleNamespace(run=refuse, Popen=refuse))
    base = tmp_path / "bcm_config_test.yaml"
    shutil.copy(REPO / "config" / "bcm_config_test.yaml", base)
    local = tmp_path / "local.yaml"
    cfg = BCMConfig(config_path=str(base), platform_override="x86", local_path=str(local),
                    env={})
    bus = EventBus()
    seen = []
    bus.subscribe("*", lambda t, v, ts: seen.append((t, v)))
    viewer = WebViewer(host="127.0.0.1", port=5099, event_bus=bus, config=cfg)
    module = _FakeModule()
    holder = {"module": module, "agent": None}
    monkeypatch.setattr(cs, "get_crash_sms", lambda: holder["module"])
    monkeypatch.setattr(cpa, "get_agent", lambda: holder["agent"])
    return SimpleNamespace(bus=bus, viewer=viewer, client=viewer._build_app().test_client(),
                           module=module, holder=holder, cfg=cfg, base=base, local=local,
                           seen=seen)


def _as(addr):
    return {"environ_base": {"REMOTE_ADDR": addr}}


class TestCommandRoutes:
    @pytest.mark.parametrize("route, action", [("/api/crash/cancel", "cancel"),
                                               ("/api/crash/send_now", "send_now"),
                                               ("/api/crash/follow_up", "follow_up")])
    def test_accepted_and_rate_limited(self, web, route, action):
        res = web.client.post(route, json={"event_id": EID, "extra": "ignored"})
        assert res.status_code == 200 and res.get_json() == {"ok": True}
        assert web.module.calls == [(action, EID, "ui")]
        res = web.client.post(route, json={"event_id": EID})
        assert res.status_code == 429 and int(res.headers["Retry-After"]) >= 1
        assert len(web.module.calls) == 1
        web.viewer._crash_last[action] -= wv._CRASH_CMD_MIN_INTERVAL_S
        assert web.client.post(route, json={"event_id": EID}).status_code == 200

    @pytest.mark.parametrize("addr", ["192.168.1.50", "10.0.0.5", "8.8.8.8", "::2"])
    @pytest.mark.parametrize("route", ["/api/crash/cancel", "/api/crash/send_now",
                                       "/api/crash/follow_up", "/api/crash/test",
                                       "/api/crash/recipients"])
    def test_loopback_only_even_with_full_remote_access(self, web, route, addr):
        web.cfg.set("dashboard.remote_access", "full")     # every route open to the network…
        client = web.viewer._build_app().test_client()
        res = client.post(route, json={"event_id": EID, "confirm": True,
                                       "recipients": [NUM1]}, **_as(addr))
        assert res.status_code == 403 and res.get_json()["error"] == "forbidden"  # …not these
        assert web.module.calls == []
        assert web.cfg.get("crash_detection.sms.recipients") is None
        assert client.get("/api/crash/recipients", **_as(addr)).status_code == 403

    @pytest.mark.parametrize("addr", ["127.0.0.1", "::1", "::ffff:127.0.0.1"])
    def test_kiosk_addresses(self, web, addr):
        assert web.client.post("/api/crash/cancel", json={"event_id": EID},
                               **_as(addr)).status_code == 200

    @pytest.mark.parametrize("body", [None, [], {}, {"event_id": None}, {"event_id": 5},
                                      {"event_id": "ABC"}, {"event_id": "../../etc"},
                                      {"event_id": "0" * 33}, {"event_id": EID + " "}])
    def test_only_a_validated_event_id(self, web, body):
        res = web.client.post("/api/crash/cancel", json=body)
        assert res.status_code == 400 and web.module.calls == []

    def test_oversized_body(self, web):
        res = web.client.post("/api/crash/cancel", data=json.dumps({"event_id": EID,
                                                                    "x": "y" * 2000}),
                              content_type="application/json")
        assert res.status_code == 413 and web.module.calls == []

    def test_not_running_and_refusals(self, web):
        web.module.answer = {"ok": False, "error": "unknown_event"}
        res = web.client.post("/api/crash/cancel", json={"event_id": EID})
        assert res.status_code == 409 and res.get_json()["error"] == "unknown_event"
        # a refusal does not use the rate limit
        web.module.answer = {"ok": True, "error": ""}
        assert web.client.post("/api/crash/cancel", json={"event_id": EID}).status_code == 200
        web.holder["module"] = None
        web.viewer._crash_last.clear()
        res = web.client.post("/api/crash/cancel", json={"event_id": EID})
        assert res.status_code == 409 and res.get_json()["error"] == "not_running"

    def test_a_late_anuluj_after_a_sent_sms_is_a_409(self, env, tmp_path, monkeypatch):
        """With the real module: after a sent SMS /api/crash/cancel is
        refused — only /api/crash/follow_up sends the cancel SMS."""
        m = _arm(env)
        _sent(env, m)
        monkeypatch.setattr(cs, "get_crash_sms", lambda: m)
        cfg = BCMConfig(config_path=str(REPO / "config" / "bcm_config_test.yaml"),
                        platform_override="x86", local_path=str(tmp_path / "l.yaml"), env={})
        client = WebViewer(host="127.0.0.1", port=5098, event_bus=EventBus(),
                           config=cfg)._build_app().test_client()
        res = client.post("/api/crash/cancel", json={"event_id": EID})
        assert res.status_code == 409 and res.get_json()["error"] == "not_cancellable"
        res = client.post("/api/crash/follow_up", json={"event_id": EID})
        assert res.status_code == 200
        m.run_once()
        assert _last(env)["cancel_sms"] == {"state": "sending"}

    def test_get_is_not_allowed(self, web):
        assert web.client.get("/api/crash/cancel").status_code == 405


class TestTestRoute:
    def test_needs_an_explicit_confirmation(self, web):
        for body in ({}, {"confirm": "true"}, {"confirm": 1}, None):
            assert web.client.post("/api/crash/test", json=body).status_code == 400
        assert web.module.calls == []
        res = web.client.post("/api/crash/test", json={"confirm": True})
        assert res.status_code == 200 and web.module.calls == [("test",)]
        res = web.client.post("/api/crash/test", json={"confirm": True})
        assert res.status_code == 429
        assert int(res.headers["Retry-After"]) <= wv._CRASH_TEST_MIN_INTERVAL_S

    def test_module_refusal(self, web):
        web.module.answer = {"ok": False, "error": "no_recipients"}
        res = web.client.post("/api/crash/test", json={"confirm": True})
        assert res.status_code == 409 and res.get_json()["error"] == "no_recipients"


class TestRecipients:
    def test_saved_only_to_the_local_overlay(self, web, caplog):
        before = web.base.read_bytes()
        kicked = []
        web.holder["agent"] = SimpleNamespace(kick=lambda: kicked.append(1))
        with caplog.at_level(logging.DEBUG):
            res = web.client.post("/api/crash/recipients",
                                  json={"recipients": ["+48 601 234 567", "", "+48602-345-678"]})
        assert res.status_code == 200
        assert res.get_json() == {"ok": True, "persisted": True, "recipients_n": 2}
        assert web.cfg.get("crash_detection.sms.recipients") == [NUM1, NUM2]
        assert web.base.read_bytes() == before            # never the base YAML
        text = web.local.read_text()
        assert NUM1 in text and NUM2 in text
        assert os.stat(web.local).st_mode & 0o777 == 0o600
        assert kicked == [1]                               # the phone gets them at once
        # never in the log or on the bus
        assert not any(NUM1 in r.getMessage() for r in caplog.records)
        assert NUM1 not in json.dumps(web.seen, default=str)
        got = web.client.get("/api/crash/recipients").get_json()
        assert got == {"recipients": [NUM1, NUM2], "max": 3}

    def test_clearing_them(self, web):
        web.client.post("/api/crash/recipients", json={"recipients": [NUM1]})
        web.viewer._crash_last.clear()
        res = web.client.post("/api/crash/recipients", json={"recipients": ["", " "]})
        assert res.status_code == 200 and res.get_json()["recipients_n"] == 0
        assert web.cfg.get("crash_detection.sms.recipients") == []

    @pytest.mark.parametrize("body", [
        None, {}, {"recipients": NUM1}, {"recipients": [NUM1, NUM2, NUM1, NUM2]},
        {"recipients": ["0601234567"]}, {"recipients": ["+0601234567"]},
        {"recipients": ["+4860"]}, {"recipients": ["+486012345678901234"]},
        {"recipients": [48601234567]}, {"recipients": ["+48 601<b>"]},
        {"recipients": ["+48601234567;rm -rf"]}, {"recipients": [None]},
        {"recipients": ["601234567"]}, {"recipients": ["+601234567"]},     # no 48: Malaysia
        {"recipients": ["+4860123456"]}, {"recipients": ["+486012345678"]},  # 48 + not 9
    ])
    def test_invalid_is_refused_whole(self, web, body):
        res = web.client.post("/api/crash/recipients", json=body)
        assert res.status_code == 400
        assert web.cfg.get("crash_detection.sms.recipients") is None
        assert not web.local.exists()

    def test_a_number_without_the_country_code_gets_a_hint(self, web):
        res = web.client.post("/api/crash/recipients", json={"recipients": [NUM1, "601234567"]})
        assert res.status_code == 400
        assert res.get_json() == {"ok": False, "error": "bad_number", "index": 1, "hint": "no_cc"}
        # a foreign number of a normal length still goes through
        assert web.client.post("/api/crash/recipients",
                               json={"recipients": ["+4915112345678"]}).status_code == 200

    def test_duplicates_dropped(self, web):
        res = web.client.post("/api/crash/recipients", json={"recipients": [NUM1, NUM1]})
        assert res.get_json()["recipients_n"] == 1

    def test_rate_limited(self, web):
        assert web.client.post("/api/crash/recipients",
                               json={"recipients": [NUM1]}).status_code == 200
        assert web.client.post("/api/crash/recipients",
                               json={"recipients": [NUM2]}).status_code == 429
        assert web.cfg.get("crash_detection.sms.recipients") == [NUM1]

    def test_get_only_returns_valid_numbers(self, web):
        web.cfg.set("crash_detection.sms.recipients", ["garbage", NUM1, "+48 60"])
        assert web.client.get("/api/crash/recipients").get_json()["recipients"] == [NUM1]

    def test_readonly_mode_never_hands_them_out(self, web):
        web.cfg.set("dashboard.remote_access", "readonly")
        client = web.viewer._build_app().test_client()
        res = client.get("/api/crash/recipients", **_as("192.168.1.50"),
                         headers={"Host": "192.168.1.1:5002"})
        assert res.status_code == 403
        assert "api_crash_recipients_get" in wv._READONLY_DENIED_ENDPOINTS


STATE_OK = {"state": "pending", "event_id": EID, "ts": WALL0, "countdown_s": 45,
            "countdown_left_s": 30, "deadline_ts": WALL0 + 45, "recipients_n": 2,
            "phone_ok": True, "dry_run": True, "forced_dry_run_reason": "no_verified_test",
            "results": [{"state": "queued", "verified": False}], "cancel_sms": None,
            "error": "", "modal": True, "cancel_pending": False, "send_now_pending": False,
            "can_follow_up": False, "may_send": False, "unconfirmed": False,
            "test": {"request": "", "error": "", "state": None, "ts": None, "dry_run": None,
                     "verified": False, "last_verified_ts": None}}


class TestPayload:
    def test_none_while_the_module_never_published(self, web):
        assert web.viewer._get_dashboard_data()["crash_sms"] is None

    def test_summary(self, web):
        web.bus.publish(cs.TOPIC_STATE, STATE_OK)
        assert web.viewer._get_dashboard_data()["crash_sms"] == STATE_OK

    def test_garbage_is_neutralised(self, web):
        web.bus.publish(cs.TOPIC_STATE, {
            "state": "<script>", "event_id": "<img>", "ts": float("nan"), "countdown_s": 500,
            "countdown_left_s": -1, "deadline_ts": True, "recipients_n": 7, "phone_ok": "yes",
            "dry_run": "false", "forced_dry_run_reason": "<b>", "results": [
                {"state": "<i>", "verified": True, "to": NUM1}, {"state": "sent", "to": NUM1},
                "x"] * 3,
            "cancel_sms": {"state": "<b>"}, "error": "<b>", "modal": 1, "test": "x",
            "extra": NUM1})
        out = web.viewer._get_dashboard_data()["crash_sms"]
        assert out["state"] == "idle" and out["event_id"] is None and out["ts"] is None
        assert out["countdown_s"] is None and out["countdown_left_s"] is None
        assert out["deadline_ts"] is None and out["recipients_n"] == 0
        assert out["phone_ok"] is False and out["dry_run"] is True and out["modal"] is False
        assert out["forced_dry_run_reason"] == "" and out["error"] == ""
        assert out["results"] == [{"state": "sent", "verified": False}]
        assert out["cancel_sms"] is None and "extra" not in out
        assert NUM1 not in json.dumps(out)
        assert out["test"]["request"] == "" and out["test"]["state"] is None

    def test_every_state_reason_and_error_passes(self, web):
        for state in cs.STATES:
            for reason in cs.FORCED_REASONS:
                web.bus.publish(cs.TOPIC_STATE, dict(STATE_OK, state=state,
                                                     forced_dry_run_reason=reason))
                out = web.viewer._get_dashboard_data()["crash_sms"]
                assert out["state"] == state and out["forced_dry_run_reason"] == reason
        for error in cs.ERRORS:
            web.bus.publish(cs.TOPIC_STATE, dict(STATE_OK, error=error))
            assert web.viewer._get_dashboard_data()["crash_sms"]["error"] == error

    def test_new_flags_only_as_true_booleans(self, web):
        for v in (1, "true", "yes", None):
            web.bus.publish(cs.TOPIC_STATE, dict(STATE_OK, may_send=v, unconfirmed=v))
            out = web.viewer._get_dashboard_data()["crash_sms"]
            assert out["may_send"] is False and out["unconfirmed"] is False
        web.bus.publish(cs.TOPIC_STATE, dict(STATE_OK, may_send=True, unconfirmed=True))
        out = web.viewer._get_dashboard_data()["crash_sms"]
        assert out["may_send"] is True and out["unconfirmed"] is True

    def test_module_payload_passes_the_sanitiser_unchanged(self, env):
        m = _arm(env)
        assert m is not None
        assert wv._crash_sms_summary(_last(env)) == _last(env)


# ── SWC action crash_cancel ────────────────────────────────────────────────

class TestSwc:
    def test_action_is_listed_everywhere(self):
        from src.dashboard import settings_screen
        from src.input import swc_remote
        assert "crash_cancel" in swc_remote.ACTIONS
        assert "crash_cancel" in swc_remote.OPTIONAL_ACTIONS
        assert "crash_cancel" in settings_screen.SWC_AVAILABLE_ACTIONS
        assert "crash_cancel" in settings_screen.ACTION_DISPLAY_NAMES
        assert "crash_cancel" not in swc_remote.DEFAULT_MAPPING   # no default button
        js = (REPO / "src/dashboard/web/js/screens/settings.js").read_text(encoding="utf-8")
        assert 'crash_cancel: App.t("swc_crash_cancel"' in js

    def _bridge(self, mapping):
        from src.input.input_bridge import InputBridge
        bus = EventBus()
        seen = []
        bus.subscribe(cs.CMD_CANCEL, lambda t, v, ts: seen.append(v))
        cfg = {"swc": {"mapping": mapping}}

        class Cfg:
            def get(self, key, default=None):
                return cfg["swc"]["mapping"] if key == "swc.mapping" else default
        InputBridge(bus, Cfg())
        return bus, seen

    def test_mapped_button_cancels(self):
        bus, seen = self._bridge({"phone_hangup": ["SWC_HANGUP", "SWC2_HANGUP"],
                                  "crash_cancel": ["SWC_HANGUP", ""]})
        bus.publish("input.raw_keycode", 64)                       # HANGUP (both pods)
        assert seen == [{"source": "swc"}]

    @pytest.mark.parametrize("code", [115, 63, "64", True, None, 9999])
    def test_other_keys_do_nothing(self, code):
        bus, seen = self._bridge({"crash_cancel": ["SWC_HANGUP", ""]})
        bus.publish("input.raw_keycode", code)
        assert seen == []

    def test_unmapped_by_default(self):
        from src.input.input_bridge import InputBridge
        bus = EventBus()
        seen = []
        bus.subscribe(cs.CMD_CANCEL, lambda t, v, ts: seen.append(v))
        InputBridge(bus)                                            # no config: defaults
        for code in (63, 64, 65, 66, 68, 113, 114, 115, 103, 108, 163, 165):
            bus.publish("input.raw_keycode", code)
        assert seen == []

    def test_swc_route_lists_it_for_an_old_mapping(self, web):
        web.cfg.set("modules.crash_sms", True)
        web.cfg.set("swc.mapping", {"volume_up": ["SWC_VOLUP", "SWC2_VOLUP"]})
        body = web.client.get("/api/config/swc").get_json()
        assert body["mapping"]["crash_cancel"] == ["", ""]
        assert "crash_cancel" in body["actions"]
        assert "crash_cancel" not in web.cfg.get("swc.mapping")   # GET changes nothing

    def test_swc_route_hides_it_while_the_module_is_off(self, web):
        """Production (crash_sms off): no SWC row that would do nothing —
        and saving the table does not erase a binding made earlier."""
        web.cfg.set("swc.mapping", {"volume_up": ["SWC_VOLUP", "SWC2_VOLUP"],
                                    "crash_cancel": ["SWC_MODE", ""]})
        body = web.client.get("/api/config/swc").get_json()
        assert "crash_cancel" not in body["actions"] and "crash_cancel" not in body["mapping"]
        res = web.client.post("/api/config/swc", json={"mapping": body["mapping"]})
        assert res.status_code == 200
        assert web.cfg.get("swc.mapping")["crash_cancel"] == ["SWC_MODE", ""]
        from src.dashboard import settings_screen
        screen = SimpleNamespace(config=web.cfg, selected_index=0)
        seen = set()
        for _ in range(len(settings_screen.SWC_AVAILABLE_ACTIONS) + 1):
            key = settings_screen.SettingsScreen._cycle_swc(screen, 1)
            seen.add(web.cfg.get(key))
        assert "crash_cancel" not in seen
        web.cfg.set("modules.crash_sms", True)
        for _ in range(len(settings_screen.SWC_AVAILABLE_ACTIONS) + 1):
            seen.add(web.cfg.get(settings_screen.SettingsScreen._cycle_swc(screen, 1)))
        assert "crash_cancel" in seen

    @pytest.mark.parametrize("addr", ["192.168.1.50", "10.0.0.5"])
    def test_network_clients_cannot_bind_it(self, web, addr):
        """Binding crash_cancel decides what may cancel a crash SMS: like
        /api/crash/*, kiosk only — also with remote_access full."""
        web.cfg.set("modules.crash_sms", True)
        web.cfg.set("dashboard.remote_access", "full")
        client = web.viewer._build_app().test_client()
        mapping = {"volume_up": ["SWC_VOLUP", "SWC2_VOLUP"], "crash_cancel": ["SWC_VOLUP", ""]}
        res = client.post("/api/config/swc", json={"mapping": mapping}, **_as(addr))
        assert res.status_code == 403
        assert "crash_cancel" not in (web.cfg.get("swc.mapping") or {})
        res = client.post("/api/config/swc/learn", json={"action": "crash_cancel", "pod": 0},
                          **_as(addr))
        assert res.status_code == 403
        # the rest of the table stays theirs to change (full mode) …
        res = client.post("/api/config/swc", json={"mapping": {
            "volume_up": ["SWC_VOLUP", ""], "crash_cancel": ["", ""]}}, **_as(addr))
        assert res.status_code == 200
        res = client.post("/api/config/swc/learn", json={"action": "mute", "pod": 0},
                          **_as(addr))
        assert res.status_code == 200
        # … and the kiosk may bind it
        res = web.client.post("/api/config/swc", json={"mapping": mapping})
        assert res.status_code == 200
        assert web.cfg.get("swc.mapping")["crash_cancel"] == ["SWC_VOLUP", ""]


# ── config ─────────────────────────────────────────────────────────────────

def _yaml_cfg(name):
    return BCMConfig(config_path=str(REPO / "config" / name), platform_override="x86",
                     local_path=None, env={})


class TestConfig:
    def test_production_does_not_start_it(self):
        cfg = _yaml_cfg("bcm_config.yaml")
        assert mc.is_enabled(cfg, "crash_sms") is False
        assert mc.module_states(cfg)["crash_sms"].runs is False
        assert cfg.get("crash_detection.sms") is None              # code defaults only

    def test_test_config_keeps_it_off_in_test_mode(self):
        cfg = _yaml_cfg("bcm_config_test.yaml")
        assert mc.is_enabled(cfg, "crash_sms") is False
        sms = cfg.get("crash_detection.sms")
        assert sms["dry_run"] is True and "enabled" not in sms
        assert "recipients" not in sms                             # only local.yaml / UI
        c = cs.load_sms_config(cfg)
        assert (c.dry_run, c.countdown_sec, c.cooldown_min, c.max_per_day,
                c.follow_up_cancel) == (True, 45, 10, 3, True)

    @pytest.mark.parametrize("name", ["bcm_config.yaml", "bcm_config_test.yaml",
                                      "bcm_config_temp.yaml"])
    def test_dead_sms_number_is_gone(self, name):
        assert "sms_number" not in (REPO / "config" / name).read_text(encoding="utf-8")

    def test_no_code_reads_the_old_key(self):
        for path in (REPO / "src").rglob("*.py"):
            assert "sms_number" not in path.read_text(encoding="utf-8"), path

    def test_defaults_and_clamps(self):
        c = cs.load_sms_config({})
        assert (c.dry_run, c.countdown_sec, c.cooldown_min, c.max_per_day) == (True, 45, 10, 3)
        c = cs.load_sms_config({"crash_detection": {"sms": {
            "countdown_sec": 5, "cooldown_min": 0, "max_per_day": 99, "dry_run": False,
            "follow_up_cancel": "no"}}})
        assert (c.dry_run, c.countdown_sec, c.cooldown_min, c.max_per_day,
                c.follow_up_cancel) == (False, 15, 1, 20, True)
        assert cs.load_sms_config({"crash_detection": {"sms": {"countdown_sec": 500}}}) \
            .countdown_sec == 120
        assert cs.load_sms_config({"crash_detection": {"sms": "x"}}).countdown_sec == 45

    def test_recipients_from_config(self):
        cfg = {"crash_detection": {"sms": {"recipients": [NUM1, "bad", NUM1, NUM2, "+48603456789",
                                                          "+48604567890"]}}}
        assert cs.configured_recipients(cfg) == [NUM1, NUM2, "+48603456789"]
