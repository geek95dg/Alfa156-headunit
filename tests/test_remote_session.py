"""Session after a remote wake (plan E) — src/power/remote_session.py, its
web routes and payload summary (src/dashboard/web_viewer.py).

Fake clocks, a fake sender in place of arduino_serial.send_line (it records
what would be written to the Nano), a synchronous EventBus; ``step()`` is
called by hand — no thread is started except in the lifecycle test.

Covers: the session starting on WAKE: only with the ignition off (and not
while "ending"), the lease countdown from LEASE:, HOLD steps and the budget,
RELEASE from the banner and after idle_suspend_min, a call or SWC input
holding idle off, the Nano's LEASE:0 ending the session (labelled released /
idle / lease_end), a RELEASE the Nano did not confirm, retries when the port
is closed, the ignition ending it, the Nano going quiet, denial statistics,
config clamping, that nothing is ever written except HOLD:<n> / RELEASE,
kiosk use (ui.activity from loopback only), music and Android Auto as
use, the published idle deadline,
that bus callbacks never write (dispatcher), the routes (loopback only,
rate-limited, JSON body, not_running) and the summary's whitelists.
"""

from __future__ import annotations

import json
import re
import shutil
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core.config import BCMConfig
from src.core.event_bus import EventBus
from src.dashboard import web_viewer as wv
from src.dashboard.web_viewer import WebViewer
from src.power import remote_session as rs

REPO = Path(__file__).resolve().parent.parent
T0 = 1_763_000_000.0


class Clock:
    def __init__(self):
        self.mono = 5000.0
        self.wall = T0

    def advance(self, s):
        self.mono += s
        self.wall += s


class Sender:
    """send_line() stand-in; with ``nano`` it also plays the firmware's
    lease (HOLD:n = at least n min from now, RELEASE = over)."""

    def __init__(self):
        self.lines: list[str] = []
        self.ok = True
        self.threads: set[str] = set()
        self.nano = None

    def __call__(self, line):
        self.threads.add(threading.current_thread().name)
        assert re.fullmatch(r"HOLD:([1-9]|[1-5][0-9]|60)|RELEASE", line), line
        self.lines.append(line)
        if self.ok and self.nano is not None:
            if line == "RELEASE":
                self.nano["lease"] = 0
            else:
                self.nano["lease"] = max(self.nano["lease"], 60 * int(line.split(":")[1]))
        return self.ok


class Env:
    def __init__(self, config=None):
        self.clock = Clock()
        self.bus = EventBus()
        self.sender = Sender()
        self.published: list[dict] = []
        self.bus.subscribe(rs.TOPIC_STATE, lambda t, v, ts: self.published.append(v))
        self.m = rs.RemoteSession(config or {}, self.bus, sender=self.sender,
                                  clock=lambda: self.clock.mono, wall=lambda: self.clock.wall)
        # Subscribe without the worker thread (tests drive step()).
        self.m._subscribed = True
        for topic, cb in self.m._subscriptions():
            self.bus.subscribe(topic, cb)

    def pub(self, topic, value):
        self.bus.publish(topic, value)

    def wake(self, reason="ir", lease=600):
        self.pub("vehicle.ignition_raw", False)
        self.pub("vehicle.wake_reason", reason)
        self.pub("vehicle.wake_lease_s", lease)
        self.step()

    def step(self, n=1):
        for _ in range(n):
            self.m.step()

    def run(self, seconds, lease_from=None, every=2.0):
        """Time passes; the Nano repeats LEASE: every 2 s (counting down
        from ``lease_from`` when given, or the fake Nano's own lease)."""
        t = 0.0
        while t < seconds:
            self.clock.advance(every)
            t += every
            if self.sender.nano is not None:
                n = self.sender.nano
                n["lease"] = max(0, n["lease"] - every)
                self.pub("vehicle.wake_lease_s", int(n["lease"]))
            elif lease_from is not None:
                self.pub("vehicle.wake_lease_s", max(0, int(lease_from - t)))
            self.step()

    def nano(self, lease):
        """From now on the fake Nano holds the lease (HOLD/RELEASE act)."""
        self.sender.nano = {"lease": float(lease)}

    @property
    def state(self):
        return self.m.state


@pytest.fixture
def env():
    return Env()


class TestSession:
    def test_starts_on_wake_with_ignition_off(self, env):
        env.wake("door", 300)
        st = env.state
        assert st["state"] == "session" and st["reason"] == "door"
        assert st["since"] == T0 and st["last_wake"] == {"reason": "door", "ts": T0}
        assert st["lease_until"] == int(T0 + 300) and st["can_hold"] is True
        assert env.sender.lines == []

    def test_wake_line_with_ignition_on_is_ignored(self, env):
        env.pub("vehicle.ignition_raw", True)
        env.pub("vehicle.wake_reason", "ir")
        env.step()
        assert env.state["state"] == "idle"

    @pytest.mark.parametrize("bad", ["IR", "phone", "", None, 1, {"r": "ir"}])
    def test_only_known_reasons(self, env, bad):
        env.pub("vehicle.wake_reason", bad)
        env.step()
        assert env.state["state"] == "idle"

    @pytest.mark.parametrize("bad", [-1, 5401, 12.5, True, "600", None])
    def test_lease_values_are_checked(self, env, bad):
        env.wake("ir", 600)
        env.pub("vehicle.wake_lease_s", bad)
        env.step()
        assert env.state["state"] == "session" and env.state["lease_until"] == int(T0 + 600)

    def test_repeated_wake_lines_are_one_session(self, env):
        env.wake("ir", 600)
        since = env.state["since"]
        env.clock.advance(2)
        env.pub("vehicle.wake_reason", "ir")
        env.pub("vehicle.wake_lease_s", 598)
        env.step()
        assert env.state["since"] == since and env.state["holds_used_min"] == 0

    def test_lease_zero_ends_the_session(self, env):
        env.wake("ir", 10)
        env.run(12, lease_from=10)
        st = env.state
        assert st["state"] == "ending" and st["ended"] == "lease_end"
        assert env.sender.lines == []
        # ... and back to idle after ENDING_SHOW_S (we were not suspended)
        env.clock.advance(rs.ENDING_SHOW_S)
        env.step()
        assert env.state["state"] == "idle" and env.state["reason"] == ""

    def test_ignition_ends_the_session(self, env):
        env.wake("door", 300)
        env.pub("vehicle.ignition_raw", True)
        env.step()
        assert env.state["state"] == "idle" and env.state["ended"] == "ignition"
        assert env.sender.lines == []

    def test_quiet_nano_ends_the_session(self, env):
        env.wake("ir", 20)
        env.clock.advance(20 + rs.LOST_GRACE_S)
        env.step()
        assert env.state["state"] == "ending" and env.state["ended"] == "lost"

    def test_wake_without_any_lease_line_ends(self, env):
        env.pub("vehicle.ignition_raw", False)
        env.pub("vehicle.wake_reason", "ext")
        env.step()
        env.clock.advance(rs.NO_LEASE_S)
        env.step()
        assert env.state["ended"] == "lost"

    def test_extension_at_the_car_counts_as_activity(self, env):
        env.wake("ir", 600)
        env.clock.advance(300)
        env.pub("vehicle.wake_lease_s", 300)
        env.step()
        before = env.m._last_activity
        env.clock.advance(2)
        env.pub("vehicle.wake_lease_s", 298)             # ordinary countdown
        env.step()
        assert env.m._last_activity == before
        env.pub("vehicle.wake_lease_s", 300)             # +2 s only: not a request
        env.step()
        assert env.m._last_activity == before
        env.pub("vehicle.wake_lease_s", 600)             # IR again: +10 min
        env.step()
        assert env.m._last_activity == env.clock.mono


class TestCommands:
    def test_hold_steps_and_budget(self, env):
        env.wake("ir", 600)
        assert env.m.request_hold() == {"ok": True}
        env.step()
        assert env.sender.lines == ["HOLD:30"]
        st = env.state
        assert st["holds_used_min"] == 30 and st["cmd"]["ok"] is True
        assert env.m.request_hold() == {"ok": True}
        env.step()
        assert env.sender.lines == ["HOLD:30", "HOLD:30"]
        assert env.state["can_hold"] is False
        assert env.m.request_hold() == {"ok": False, "error": "hold_limit"}

    def test_last_hold_is_capped_by_the_budget(self):
        e = Env({"power": {"remote_session": {"hold_step_min": 25, "hold_max_min": 60}}})
        e.wake("ir", 600)
        for _ in range(3):
            e.m.request_hold()
            e.step()
        assert e.sender.lines == ["HOLD:25", "HOLD:25", "HOLD:10"]
        assert e.state["holds_used_min"] == 60

    def test_failed_hold_is_not_counted(self, env):
        env.wake("ir", 600)
        env.sender.ok = False
        env.m.request_hold()
        env.step()
        st = env.state
        assert st["holds_used_min"] == 0 and st["cmd"] == {
            "action": "hold", "ok": False, "error": "not_sent", "ts": T0}

    def test_sleep_now_and_confirmation(self, env):
        env.wake("door", 300)
        assert env.m.request_sleep() == {"ok": True}
        env.step()
        assert env.sender.lines == ["RELEASE"] and env.state["sleep_pending"] is True
        assert env.m.request_hold() == {"ok": False, "error": "no_session"}
        env.pub("vehicle.wake_lease_s", 0)               # the Nano's answer
        env.step()
        assert env.state["state"] == "ending" and env.state["ended"] == "released"

    def test_stale_wake_line_after_release_does_not_reopen(self, env):
        env.wake("door", 300)
        env.m.request_sleep()
        env.step()
        env.pub("vehicle.wake_lease_s", 0)
        env.pub("vehicle.wake_reason", "door")           # a full-state line in flight
        env.step()
        assert env.state["state"] == "ending"

    def test_release_not_confirmed(self, env):
        env.wake("ir", 600)
        env.m.request_sleep()
        env.step()
        env.clock.advance(rs.RELEASE_CONFIRM_S + 1)
        env.pub("vehicle.wake_lease_s", 590)             # the lease goes on
        env.step()
        st = env.state
        assert st["state"] == "session" and st["sleep_pending"] is False
        assert st["cmd"]["error"] == "not_confirmed" and st["can_hold"] is True

    def test_release_retried_when_the_port_is_closed(self, env):
        env.wake("ir", 600)
        env.sender.ok = False
        env.m.request_sleep()
        env.step()
        env.step()                                       # not before RELEASE_RETRY_S
        assert env.sender.lines == ["RELEASE"]
        for _ in range(rs.RELEASE_TRIES):
            env.clock.advance(rs.RELEASE_RETRY_S)
            env.step()
        assert env.sender.lines == ["RELEASE"] * rs.RELEASE_TRIES
        assert env.state["cmd"]["error"] == "not_sent" and env.state["state"] == "session"

    def test_commands_without_a_session(self, env):
        assert env.m.request_hold() == {"ok": False, "error": "no_session"}
        assert env.m.request_sleep() == {"ok": False, "error": "no_session"}
        env.step()
        assert env.sender.lines == []

    def test_bus_commands(self, env):
        env.wake("ir", 600)
        env.pub(rs.CMD_HOLD, None)
        env.step()
        env.pub(rs.CMD_SLEEP, None)
        env.step()
        assert env.sender.lines == ["HOLD:30", "RELEASE"]

    def test_callbacks_never_write(self, env):
        """Bus callbacks (the dispatcher) only change state: every write is
        on the worker (here: the test thread calling step())."""
        env.pub("vehicle.ignition_raw", False)
        env.pub("vehicle.wake_reason", "ir")
        env.pub("vehicle.wake_lease_s", 600)
        env.pub(rs.CMD_HOLD, None)
        env.pub(rs.CMD_SLEEP, None)
        assert env.sender.lines == []


class TestIdle:
    def test_idle_releases_after_the_configured_minutes(self, env):
        env.wake("ir", 600)
        env.m.request_hold()
        env.step()                                       # lease now 30 min
        env.run(10 * 60 - 4, lease_from=1800)
        assert env.sender.lines == ["HOLD:30"]
        env.run(6, lease_from=1800 - 596)
        assert env.sender.lines == ["HOLD:30", "RELEASE"]
        env.pub("vehicle.wake_lease_s", 0)
        env.step()
        assert env.state["ended"] == "idle"

    def test_input_and_calls_keep_it_awake(self, env):
        env.wake("ir", 600)
        env.nano(600)
        env.m.request_hold()
        env.step()                                       # lease 30 min
        env.run(9 * 60)
        env.pub("input.raw_keycode", 115)                # SWC press
        env.run(9 * 60)
        assert env.sender.lines == ["HOLD:30"]
        env.pub("bt.call_state", "active")               # a call: never idle...
        env.run(15 * 60)
        # ...and never cut by the lease end (12 min were left): auto HOLD
        # from the same budget, shortly before the end.
        assert env.sender.lines == ["HOLD:30", "HOLD:30"]
        assert env.state["state"] == "session" and env.state["holds_used_min"] == 60
        env.pub("bt.call_state", "idle")                 # idle counts from the call's end
        env.run(9 * 60)
        assert env.sender.lines == ["HOLD:30", "HOLD:30"]
        env.run(62)
        assert env.sender.lines == ["HOLD:30", "HOLD:30", "RELEASE"]

    def test_call_with_the_budget_used_up_ends_with_the_lease(self, env):
        env.wake("ir", 600)
        env.nano(600)
        for _ in range(2):
            env.m.request_hold()
            env.step()
        env.pub("bt.call_state", "active")
        env.run(31 * 60)
        assert env.sender.lines == ["HOLD:30", "HOLD:30"]       # nothing left to extend
        assert env.state["state"] == "ending" and env.state["ended"] == "lease_end"

    def test_kiosk_use_after_hold_keeps_it_awake(self, env):
        """The driver asked for 30 more minutes and uses the touchscreen /
        Android Auto (web_viewer's ui.activity), never a SWC button: idle
        must not cut the session short — the lease ends it."""
        env.wake("ir", 600)
        env.nano(600)
        env.m.request_hold()
        env.step()                                       # lease 30 min
        for _ in range(50):                              # 25 min of touches
            env.run(30)
            env.pub("ui.activity", "touch")
        assert env.sender.lines == ["HOLD:30"]
        assert env.state["state"] == "session"
        env.run(6 * 60)                                  # hands off: the lease ends it
        assert env.sender.lines == ["HOLD:30"]
        assert env.state["state"] == "ending" and env.state["ended"] == "lease_end"

    def test_music_holds_idle_off_and_counts_from_its_end(self, env):
        env.wake("ir", 600)
        env.nano(600)
        env.m.request_hold()
        env.step()
        env.pub("bt.media_playing", True)
        env.run(15 * 60)
        assert env.sender.lines == ["HOLD:30"]
        assert env.state["idle_at"] is None              # nothing to count down to
        env.pub("bt.media_playing", False)               # music stopped: idle from here
        env.run(9 * 60)
        assert env.sender.lines == ["HOLD:30"]
        env.run(62)
        assert env.sender.lines == ["HOLD:30", "RELEASE"]

    def test_music_never_extends_the_lease(self, env):
        """Only a call gets the automatic HOLD; music just holds idle off."""
        env.wake("ir", 600)
        env.nano(600)
        env.pub("bt.media_playing", True)
        env.run(11 * 60)
        assert env.sender.lines == []
        assert env.state["state"] == "ending" and env.state["ended"] == "lease_end"

    def test_a2dp_connection_alone_is_not_use_and_its_loss_clears_music(self, env):
        env.wake("ir", 600)
        env.nano(600)
        env.m.request_hold()
        env.step()
        env.pub("bt.media_playing", True)
        env.pub("bt.a2dp_active", True)                  # the main phone, as usual
        env.run(60)
        env.pub("bt.a2dp_active", False)                 # phone gone, media_playing stale
        env.run(9 * 60)
        assert env.sender.lines == ["HOLD:30"]
        env.run(62)
        assert env.sender.lines == ["HOLD:30", "RELEASE"]
        env2 = Env()
        env2.wake("ir", 600)
        env2.nano(600)
        env2.m.request_hold()
        env2.step()
        for _ in range(10):
            env2.pub("bt.a2dp_active", True)             # connected all along: not use
            env2.run(62)
        assert env2.sender.lines == ["HOLD:30", "RELEASE"]

    def test_android_auto_change_counts_once(self, env):
        env.wake("ir", 600)
        env.nano(600)
        env.pub("multimedia.openauto_status", "running")
        env.m.request_hold()
        env.step()
        env.run(5 * 60)
        env.pub("multimedia.openauto_status", "connected")   # AA came up: activity
        env.run(5 * 60)
        env.pub("multimedia.openauto_status", "connected")   # same value: not activity
        env.pub("multimedia.openauto_status", "<bogus>")
        env.run(4 * 60)
        assert env.sender.lines == ["HOLD:30"]
        env.run(62)
        assert env.sender.lines == ["HOLD:30", "RELEASE"]

    def test_idle_deadline_is_published_only_when_it_comes_first(self, env):
        env.wake("ir", 600)
        env.nano(600)
        assert env.state["idle_at"] is None              # lease 10 min, idle 10 min
        env.m.request_hold()
        env.step()
        env.run(2)                                       # LEASE jumps to 30 min
        assert env.state["idle_at"] == int(T0 + 2 + 600)
        assert env.state["lease_until"] == int(T0 + 2 + 1798)
        env.run(60)
        env.pub("ui.activity", "touch")
        env.step()
        assert env.state["idle_at"] == int(T0 + 62 + 600)
        env.pub("bt.call_state", "active")
        env.step()
        assert env.state["idle_at"] is None              # a call: no idle deadline

    def test_a_call_or_music_before_the_module_started_counts(self):
        bus = EventBus()
        bus.publish("bt.media_playing", True)
        bus.publish("bt.a2dp_active", True)
        bus.publish("bt.call_state", "idle")
        m = rs.RemoteSession({}, bus, sender=Sender())
        m._seed_from_bus()
        assert m._media_playing is True and m._call_busy is False
        bus.publish("bt.a2dp_active", False)
        m2 = rs.RemoteSession({}, bus, sender=Sender())
        m2._seed_from_bus()
        assert m2._media_playing is False                # stale: the phone is gone
        bus.publish("bt.call_state", "active")
        m2._seed_from_bus()
        assert m2._call_busy is True

    def test_config_is_clamped(self):
        e = Env({"power": {"remote_session": {"idle_suspend_min": 0, "hold_step_min": 99,
                                              "hold_max_min": "60"}}})
        assert e.m._settings == {"idle_suspend_min": 1, "hold_step_min": 60,
                                 "hold_max_min": 60}
        assert rs.session_settings({}) == {"idle_suspend_min": 10, "hold_step_min": 30,
                                           "hold_max_min": 60}
        assert rs.session_settings({"power": {"remote_session": {
            "hold_step_min": 45, "hold_max_min": 20}}})["hold_step_min"] == 20


class TestStats:
    def test_denials_and_nano_counter(self, env):
        env.pub("vehicle.wake_denied", "rate")
        env.pub("vehicle.wake_denied", "bogus")
        env.pub("vehicle.wake_stats", {"denied": 7, "last": "lowbatt"})
        env.pub("vehicle.wake_stats", {"denied": 70000, "last": "rate"})   # ignored
        env.pub("arduino.sensor_hub_connected", False)
        env.step()
        st = env.state
        assert st["denied_seen"] == 1 and st["last_denied"] == {"reason": "rate", "ts": T0}
        assert st["denied_total"] == 7 and st["last_denied_nano"] == "lowbatt"
        assert st["link"] is False and st["state"] == "idle"

    def test_ir_settings(self):
        assert rs.ir_settings({}) == (0x7A15, 0x56)
        warned = []
        assert rs.ir_settings({"power": {"remote_session": {"ir_address": 70000,
                                                            "ir_command": "x"}}},
                              lambda k, m: warned.append(k)) == (0x7A15, 0x56)
        assert warned == ["wake_ir_address", "wake_ir_command"]
        assert rs.ir_settings({"power": {"remote_session": {"ir_address": 0x1234,
                                                            "ir_command": 0}}}) == (0x1234, 0)

    def test_the_public_repo_ir_code_is_warned_about(self, caplog):
        """The repo's IR code is public: warned at start and shown in the
        Settings row until a private code is set."""
        with caplog.at_level("WARNING", logger=rs.log.name):
            e = Env()
        e.step()
        assert e.state["ir_default"] is True
        assert "repo default" in caplog.text
        assert wv._remote_session_summary(e.state)["ir_default"] is True
        caplog.clear()
        with caplog.at_level("WARNING", logger=rs.log.name):
            e = Env({"power": {"remote_session": {"ir_address": 0x1B2C, "ir_command": 0x3D}}})
        e.step()
        assert e.state["ir_default"] is False and "repo default" not in caplog.text
        assert wv._remote_session_summary(e.state)["ir_default"] is False


class TestSender:
    def test_default_sender_is_the_arduino_listener(self):
        bus = EventBus()
        lines = []
        listener = SimpleNamespace(send_line=lambda line: lines.append(line) or True)
        bus.publish("input._internals", {"arduino_serial": listener})
        m = rs.RemoteSession({}, bus)
        assert m._send("RELEASE") is True and lines == ["RELEASE"]

    def test_no_listener_is_a_failure_not_a_crash(self):
        m = rs.RemoteSession({}, EventBus())
        assert m._send("RELEASE") is False

    def test_lifecycle_thread(self):
        """The real entry point: one worker thread does the writes, the
        module is reachable for the routes and gone after shutdown."""
        bus = EventBus()
        sender = Sender()
        bus.publish("input._internals", {"arduino_serial": SimpleNamespace(send_line=sender)})
        mod = rs.start_remote_session({}, bus)
        try:
            assert rs.get_remote_session() is mod
            bus.publish("vehicle.ignition_raw", False)
            bus.publish("vehicle.wake_reason", "door")
            bus.publish("vehicle.wake_lease_s", 300)
            deadline = time.monotonic() + 5
            while (mod.state or {}).get("state") != "session" and time.monotonic() < deadline:
                time.sleep(0.02)
            assert mod.state["state"] == "session"
            mod.request_sleep()
            deadline = time.monotonic() + 5
            while not sender.lines and time.monotonic() < deadline:
                time.sleep(0.02)
            assert sender.lines == ["RELEASE"] and sender.threads == {"remote-session"}
        finally:
            bus.publish("power.shutting_down", True)
        assert rs.get_remote_session() is None
        mod._thread.join(timeout=5)
        assert not mod._thread.is_alive()


# ── web: summary and routes ──────────────────────────────────────────────

class TestSummary:
    def test_none_without_the_module(self):
        assert wv._remote_session_summary(None) is None
        assert wv._remote_session_summary("x") is None

    def test_left_is_computed_at_payload_time(self, env, monkeypatch):
        env.wake("ir", 600)
        monkeypatch.setattr(wv.time, "time", lambda: T0 + 100)
        out = wv._remote_session_summary(env.state)
        assert out["state"] == "session" and out["lease_left_s"] == 500
        assert out["reason"] == "ir" and out["can_hold"] is True and out["hold_step_min"] == 30

    def test_idle_left_only_before_the_lease(self, env, monkeypatch):
        env.wake("ir", 600)
        env.nano(600)
        env.m.request_hold()
        env.step()
        env.run(2)
        monkeypatch.setattr(wv.time, "time", lambda: T0 + 100)
        out = wv._remote_session_summary(env.state)
        assert out["idle_left_s"] == 502 and out["lease_left_s"] == 1700
        # A bogus or later idle_at never shows, and never above the lease.
        assert wv._remote_session_summary(dict(env.state, idle_at="x"))["idle_left_s"] is None
        late = wv._remote_session_summary(dict(env.state, idle_at=T0 + 99999))
        assert late["idle_left_s"] == late["lease_left_s"] == 1700
        assert wv._remote_session_summary(dict(env.state, state="ending"))["idle_left_s"] is None

    def test_whitelists(self, env):
        env.wake("ir", 600)
        bad = dict(env.state, state="<img>", reason="x", ended="rm", holds_used_min=-1,
                   hold_step_min="30", denied_total=70000, link="yes",
                   last_wake={"reason": "<b>", "ts": T0},
                   last_denied={"reason": "rate", "ts": float("nan")},
                   last_denied_nano="evil", cmd={"action": "rm", "ok": True})
        out = wv._remote_session_summary(bad)
        assert out["state"] == "idle" and out["reason"] == "" and out["ended"] == ""
        assert out["holds_used_min"] == 0 and out["hold_step_min"] == 0
        assert out["denied_total"] is None and out["link"] is None
        assert out["last_wake"] is None and out["last_denied"] is None
        assert out["last_denied_nano"] == "" and out["cmd"] is None
        assert out["lease_left_s"] is None


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
    monkeypatch.setattr(rs, "get_remote_session", lambda: holder["module"])
    return SimpleNamespace(env=env, cfg=cfg, viewer=viewer, holder=holder,
                           client=viewer._build_app().test_client())


def _as(addr):
    return {"environ_base": {"REMOTE_ADDR": addr}}


class TestRoutes:
    def test_hold_and_sleep(self, web):
        web.env.wake("ir", 600)
        res = web.client.post("/api/remote_session/hold", json={})
        assert res.status_code == 200 and res.get_json() == {"ok": True}
        web.env.step()
        res = web.client.post("/api/remote_session/sleep", json={"minutes": 60})
        assert res.status_code == 200
        web.env.step()
        assert web.env.sender.lines == ["HOLD:30", "RELEASE"]   # the body is ignored

    def test_no_session(self, web):
        res = web.client.post("/api/remote_session/hold", json={})
        assert res.status_code == 409 and res.get_json()["error"] == "no_session"

    @pytest.mark.parametrize("addr", ["192.168.1.50", "10.0.0.5", "::ffff:192.168.1.5"])
    @pytest.mark.parametrize("route", ["/api/remote_session/hold", "/api/remote_session/sleep"])
    def test_loopback_only_even_with_full_remote_access(self, web, route, addr):
        web.env.wake("ir", 600)
        web.cfg.set("dashboard.remote_access", "full")
        client = web.viewer._build_app().test_client()
        res = client.post(route, json={}, **_as(addr))
        assert res.status_code == 403 and res.get_json()["error"] == "forbidden"
        web.env.step()
        assert web.env.sender.lines == []

    def test_json_body_required_and_rate_limit(self, web):
        web.env.wake("ir", 600)
        res = web.client.post("/api/remote_session/hold", data="x", content_type="text/plain")
        assert res.status_code == 400
        assert web.client.post("/api/remote_session/hold", json={}).status_code == 200
        res = web.client.post("/api/remote_session/hold", json={})
        assert res.status_code == 429 and int(res.headers["Retry-After"]) >= 1

    def test_not_running(self, web):
        web.holder["module"] = None
        res = web.client.post("/api/remote_session/sleep", json={})
        assert res.status_code == 409 and res.get_json()["error"] == "not_running"

    def test_payload(self, web, monkeypatch):
        monkeypatch.setattr(wv.time, "time", lambda: T0)
        data = web.client.get("/api/data").get_json()
        assert data["remote_session"] is None           # never published yet
        web.env.wake("door", 300)
        data = web.client.get("/api/data").get_json()
        assert data["remote_session"]["state"] == "session"
        assert data["remote_session"]["reason"] == "door"
        assert 0 < data["remote_session"]["lease_left_s"] <= 300


class TestKioskActivity:
    """web_viewer → ui.activity: only the kiosk (loopback), throttled."""

    def _collect(self, web):
        got = []
        web.env.bus.subscribe("ui.activity", lambda t, v, ts: got.append(v))
        web.viewer._aa_injector = SimpleNamespace(
            submit=lambda *a, **kw: True, to_pixels=lambda x, y: (10, 20),
            release=lambda *a, **kw: None)
        return got

    def test_loopback_only_and_throttled(self, web):
        got = self._collect(web)
        v = web.viewer
        touch = json.dumps({"type": "aa_touch", "action": "down", "x": 0.5, "y": 0.5})
        assert v._handle_input_message('{"type": "activity"}', "n", local=False) is False
        assert v._handle_input_message(touch, "n", local=False) is True
        assert v._handle_input_message('{"type": "keydown", "key": "Enter"}', "n") is True
        assert got == []                                 # a network client: never
        assert v._handle_input_message('{"type": "activity"}', "k", local=True) is True
        assert v._handle_input_message(touch, "k", local=True) is True
        assert got == ["touch"]                          # one per 5 s
        v._ui_activity_at -= wv._UI_ACTIVITY_MIN_INTERVAL_S
        assert v._handle_input_message('{"type": "keydown", "key": "Enter"}', "k", local=True)
        assert got == ["touch", "key"]
        assert v._handle_input_message('{"type": "activity", "x": "' + "a" * 5000 + '"}',
                                       "k", local=True) is False

    def test_ws_loop_passes_the_flag(self, web):
        got = self._collect(web)

        class FakeWS:
            def __init__(self, msgs):
                self.msgs = list(msgs)

            def receive(self, timeout=None):
                if not self.msgs:
                    raise ConnectionError("closed")
                return self.msgs.pop(0)

        web.viewer._running = True
        try:
            web.viewer._serve_input_ws(FakeWS(['{"type": "activity"}']))
            assert got == []
            web.viewer._serve_input_ws(FakeWS(['{"type": "activity"}']), local=True)
            assert got == ["touch"]
        finally:
            web.viewer._running = False

    def test_http_touch_fallback(self, web):
        got = self._collect(web)
        web.cfg.set("dashboard.remote_access", "full")
        client = web.viewer._build_app().test_client()
        res = client.post("/aa/touch", json={"action": "tap", "x": 0.5, "y": 0.5},
                          **_as("192.168.1.50"))
        assert res.status_code == 200 and got == []
        res = client.post("/aa/touch", json={"action": "tap", "x": 0.5, "y": 0.5})
        assert res.status_code == 200 and got == ["touch"]

    def test_it_reaches_the_session(self, web):
        """End to end: a kiosk touch moves the idle deadline."""
        self._collect(web)
        env = web.env
        env.wake("ir", 600)
        env.nano(600)
        env.m.request_hold()
        env.step()
        env.run(2)
        before = env.state["idle_at"]
        env.run(30)
        web.viewer._handle_input_message('{"type": "activity"}', "k", local=True)
        env.step()
        assert env.state["idle_at"] == before + 30


def test_production_and_test_configs_keep_it_off():
    from src.core import modules_catalog as mc
    for name in ("bcm_config.yaml", "bcm_config_test.yaml"):
        cfg = BCMConfig(config_path=str(REPO / "config" / name), platform_override="x86",
                        local_path=None, env={})
        assert mc.is_enabled(cfg, "remote_session") is False
        assert mc.module_states(cfg)["remote_session"].runs is False


def test_ignition_watcher_is_left_alone():
    """Fixing ignition_watcher.load_config would enable a second, competing
    suspend path — this module never imports or touches it."""
    text = (REPO / "src" / "power" / "remote_session.py").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
    assert "import ignition_watcher" not in code and "from src.power.ignition_watcher" not in code
    assert "systemctl" not in code and "subprocess" not in code
