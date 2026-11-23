"""Car phone light sensor and the SensorServer subscription fallback
(src/sensors/phone_sensors.py), the Settings summary and the test route
(src/dashboard/web_viewer.py).

* ``phone.light_lux`` without the accelerometer (own freshness);
* fallback combined → no_gyro → split (one connection per sensor), so a
  refused/missing light sensor never stops the accelerometer and vice versa;
* per-type statistics in ``phone_sensors.state``, the one-time "no light"
  warning, the 10 s test (``phone_sensors.test_result``);
* a real multi-connection wsproto server for the ``split`` mode (select());
* the web summary sanitiser and POST /api/phone_sensors/test (loopback,
  rate limit).

Fake connections run on a FakeClock; files only in ``tmp_path``.
"""

import json
import logging
import math
import socket
import threading
import time

import pytest
from wsproto import ConnectionType, WSConnection
from wsproto.events import AcceptConnection, CloseConnection, Request, TextMessage

from src.core.config import BCMConfig
from src.core.event_bus import EventBus
from src.dashboard import web_viewer as wv
from src.dashboard.web_viewer import WebViewer
from src.sensors import phone_sensors as ps
from src.sensors.phone_sensors import ConnectionClosed, PhoneSensors, WsClient, parse_frame
from tests.sensor_sim import G0, Drive, FakeClock, accel_frame, light_frame

ACC, GYRO, LIGHT = ps.TYPE_ACCEL, ps.TYPE_GYRO, ps.TYPE_LIGHT
T_ACC, T_GYRO, T_LIGHT = (ps.single_target(k) for k in (ACC, GYRO, LIGHT))
LOGGER = "bcm.sensors.phone"


def car_phone_payload(local=951, ok=True, state="connected", error=""):
    return {"state": state, "forwards": {"sensors": {"local": local, "remote": 8080, "ok": ok,
                                                     "error": error}}}


@pytest.fixture
def env(tmp_path):
    def make(config=None, connect=None):
        clock = FakeClock()
        bus = EventBus()
        seen = []
        bus.subscribe("*", lambda t, v, ts: seen.append((t, v)))
        sensors = PhoneSensors(config or {}, bus, connect=connect or (lambda *a: None),
                               clock=clock.mono, wall_clock=clock.wall,
                               state_path=str(tmp_path / "phone_sensors.json"))
        # The bus callbacks without the worker thread (cycle() is driven here).
        for topic, cb in sensors._subscriptions():
            bus.subscribe(topic, cb)
        e = type("Env", (), {})()
        e.clock, e.bus, e.sensors, e.seen = clock, bus, sensors, seen
        e.topic = lambda name: [v for t, v in seen if t == name]
        e.drive = Drive(sensors, bus, clock)
        return e

    return make


class Runaway(BaseException):
    """Not an Exception: the worker must not swallow it as a closed link."""


class StreamConn:
    """A fake SensorServer connection on the shared FakeClock.

    ``kind``: frames of that type every ``period`` s of clock time from
    ``start`` until ``until`` (then silence), ``typed=False`` = frames
    without the ``type`` field (one-sensor endpoint). ``refuse``: the first
    receive() raises a close with that code; ``close_at``: a normal close
    (1000) once the clock passes it. ``limit``: Runaway past that time."""

    def __init__(self, clock, kind=None, period=0.01, start=None, until=math.inf,
                 refuse=None, reason="", close_at=math.inf, typed=True, lux=100.0, limit=600.0):
        self.clock = clock
        self.kind = kind
        self.period = period
        self.next_t = clock.t if start is None else start
        self.until = until
        self.refuse = refuse
        self.reason = reason
        self.close_at = close_at
        self.typed = typed
        self.lux = lux
        self.limit = clock.t + limit
        self.closed = False
        self.frames = 0

    def _frame(self, t):
        values = [self.lux] if self.kind == LIGHT else [0.0, 0.0, G0]
        obj = {"values": values, "timestamp": int(round(t * 1e9)), "accuracy": 3}
        if self.typed:
            obj["type"] = self.kind
        return json.dumps(obj)

    def receive(self, timeout):
        if self.clock.t > self.limit:
            raise Runaway("the session never ended")
        if self.refuse is not None:
            raise ConnectionClosed(f"closed by the phone (code {self.refuse}: {self.reason})",
                                   code=self.refuse)
        if self.clock.t >= self.close_at:
            raise ConnectionClosed("closed by the phone (code 1000)", code=1000)
        if self.kind and self.next_t < self.until and self.next_t <= self.clock.t + timeout:
            self.clock.t = max(self.clock.t, self.next_t)
            t = self.next_t
            self.next_t += self.period
            self.frames += 1
            return self._frame(t)
        self.clock.advance(timeout)
        return None

    def close(self):
        self.closed = True


class TargetConnector:
    """``connect(host, port, target, timeout)`` → the next result for that
    target (a connection or an exception); a factory for the rest."""

    def __init__(self, results=None, factory=None):
        self.results = {k: list(v) for k, v in (results or {}).items()}
        self.factory = factory
        self.calls = []

    def __call__(self, host, port, target, timeout):
        self.calls.append(target)
        queue = self.results.get(target)
        res = queue.pop(0) if queue else (self.factory(target) if self.factory else None)
        if res is None:
            raise ConnectionRefusedError("nothing scripted")
        if isinstance(res, BaseException):
            raise res
        return res


def lux_values(e):
    return [v["lux"] for v in e.topic("phone.light_lux")]


# ── light independent of the accelerometer ────────────────────────────────

class TestLightWithoutAccelerometer:
    def test_lux_is_published_with_no_accelerometer_at_all(self, env):
        e = env()
        for i in range(30):                                     # 3 s of light only
            e.clock.advance(0.1)
            e.sensors.handle_message(light_frame(42.0 + (i % 2)), e.clock.t)
            e.sensors.periodic(e.clock.t)
        lux = e.topic("phone.light_lux")
        assert lux and set(lux[0]) == {"lux", "ts", "frame_age_s"} and 42.0 <= lux[0]["lux"] <= 43.0
        assert not e.topic("phone.g_force")
        assert e.sensors.state is None                          # never "streaming"
        state = e.sensors._extras("stale")
        assert state["types"]["light"]["active"] is True
        assert state["types"]["accel"]["active"] is False
        assert state["lux"] in (42.0, 43.0) and state["lux_ts"] is not None

    def test_accelerometer_without_light_streams_normally(self, env):
        e = env()
        e.drive.rest(3.0)
        assert e.topic("phone.g_force") and e.sensors.state["state"] == "streaming"
        assert e.topic("phone.light_lux") == []
        assert e.sensors.state["types"]["light"]["active"] is False
        assert e.sensors.state["lux"] is None

    def test_split_light_keeps_working_while_the_accelerometer_is_refused(self, env, caplog):
        e = env()
        e.sensors._split = True
        conn = TargetConnector(factory=lambda target: {
            T_ACC: StreamConn(e.clock, refuse=4002, reason="no accelerometer"),
            T_GYRO: StreamConn(e.clock, refuse=4002, reason="Sensor of type gyroscope"),
            T_LIGHT: StreamConn(e.clock, LIGHT, period=1.0, typed=False, lux=250.0,
                                close_at=e.clock.t + 40.0),
        }[target])
        e.sensors._connect = conn
        e.bus.publish("net.car_phone", car_phone_payload())
        with caplog.at_level(logging.WARNING, logger=LOGGER):
            e.sensors.cycle()
        # Light went on for 40 s although the accelerometer was refused.
        lux = lux_values(e)
        assert lux and set(lux) == {250.0} and len(lux) >= 15
        # The accelerometer was retried with its own backoff, the gyroscope
        # refused once is given up (not retried).
        acc_calls = conn.calls.count(T_ACC)
        assert 4 <= acc_calls <= 7                               # 1+2+4+8+16 s
        assert conn.calls.count(T_GYRO) == 1 and e.sensors._gyro_dead
        assert any("refused the gyroscope" in r.getMessage() for r in caplog.records)
        states = [s["state"] for s in e.topic("phone_sensors.state")]
        assert "streaming" not in states and "stale" in states
        assert e.sensors.state["close"]["channel"] in ("accel", "light")
        # The next plan has no gyroscope connection.
        assert [c.name for c in e.sensors._plan()] == ["accel", "light"]


# ── the fallback order ────────────────────────────────────────────────────

class TestFallback:
    def _run(self, e, conn, cycles):
        e.sensors._connect = conn
        e.bus.publish("net.car_phone", car_phone_payload())
        for _ in range(cycles):
            e.sensors.cycle()
            e.clock.t = max(e.clock.t, e.sensors._retry_at)

    def test_refusal_naming_light_goes_straight_to_split(self, env, caplog):
        e = env()
        conn = TargetConnector(results={ps.CONNECT_TARGET: [StreamConn(
            e.clock, refuse=4002, reason="Sensor of type android.sensor.light not supported")]},
            factory=lambda target: StreamConn(e.clock, ACC if target == T_ACC else None,
                                              close_at=e.clock.t + 3.0))
        with caplog.at_level(logging.WARNING, logger=LOGGER):
            self._run(e, conn, 2)
        assert conn.calls[0] == ps.CONNECT_TARGET
        assert set(conn.calls[1:4]) == {T_ACC, T_GYRO, T_LIGHT}  # gyroscope kept
        assert e.sensors.mode == "split"
        assert any("one SensorServer connection per sensor" in r.getMessage()
                   for r in caplog.records)

    def test_unnamed_refusals_drop_the_gyroscope_then_split(self, env):
        # A refused light sensor whose reason names nothing used to loop
        # for ever on [accelerometer, light].
        e = env()
        conn = TargetConnector(
            results={ps.CONNECT_TARGET: [StreamConn(e.clock, refuse=4000)],
                     ps.CONNECT_TARGET_NO_GYRO: [StreamConn(e.clock, refuse=4000)]},
            factory=lambda target: StreamConn(e.clock, ACC if target == T_ACC else None,
                                              close_at=e.clock.t + 3.0))
        self._run(e, conn, 3)
        assert conn.calls[:2] == [ps.CONNECT_TARGET, ps.CONNECT_TARGET_NO_GYRO]
        assert set(conn.calls[2:5]) == {T_ACC, T_GYRO, T_LIGHT}
        assert e.sensors.mode == "split"

    def test_combined_light_without_accelerometer_switches_to_split(self, env):
        e = env()
        conn = TargetConnector(
            results={ps.CONNECT_TARGET: [StreamConn(e.clock, LIGHT, period=0.5)]},
            factory=lambda target: StreamConn(e.clock, ACC if target == T_ACC else None,
                                              close_at=e.clock.t + 3.0))
        self._run(e, conn, 1)
        assert e.sensors.mode == "split"
        assert e.sensors._retry_at - e.clock.t <= ps.BACKOFF_MIN_S   # quick retry
        assert lux_values(e)                                       # light used meanwhile

    def test_combined_accelerometer_without_light_switches_to_split(self, env):
        e = env()
        combined = StreamConn(e.clock, ACC)
        conn = TargetConnector(results={ps.CONNECT_TARGET: [combined]},
                               factory=lambda target: StreamConn(
                                   e.clock, ACC if target == T_ACC else None,
                                   close_at=e.clock.t + 3.0))
        self._run(e, conn, 1)
        assert combined.closed and e.sensors.mode == "split"
        n = combined.frames
        assert 1400 <= n <= 1600                                    # ~15 s at 100 Hz
        assert e.topic("phone.g_force")

    def test_normal_close_changes_nothing(self, env):
        e = env()
        conn = TargetConnector(results={ps.CONNECT_TARGET: [
            StreamConn(e.clock, ACC, close_at=e.clock.t + 2.0),
            StreamConn(e.clock, ACC, close_at=e.clock.t + 10.0)]})       # < 15 s
        self._run(e, conn, 2)
        assert conn.calls == [ps.CONNECT_TARGET, ps.CONNECT_TARGET]
        assert e.sensors.mode == "combined"

    def test_split_silent_light_is_warned_once_and_retried(self, env, caplog):
        e = env()
        e.sensors._split = True
        lights = []

        def factory(target):
            if target == T_LIGHT:
                lights.append(StreamConn(e.clock))                   # never a frame
                return lights[-1]
            return StreamConn(e.clock, ACC if target == T_ACC else GYRO,
                              close_at=e.clock.t + 100.0 - (e.clock.t - 1000.0))
        conn = TargetConnector(factory=factory)
        with caplog.at_level(logging.WARNING, logger=LOGGER):
            self._run(e, conn, 1)
        warned = [r for r in caplog.records
                  if "SensorServer nie wysyła czujnika światła" in r.getMessage()]
        assert len(warned) == 1
        assert len(lights) >= 2 and lights[0].closed               # closed, retried
        # The accelerometer streamed the whole time.
        # (g_force: one per worker round of the fakes, >= 100 ms apart)
        assert len(e.topic("phone.g_force")) >= 500 and e.sensors.stats["accel"] >= 9000

    @pytest.mark.parametrize("how", ["eof", "idle"])
    def test_empty_combined_sessions_advance_the_fallback(self, env, how, caplog):
        # Accepted, then ended without a frame (no 4xxx): 3 in a row drop
        # the gyroscope, 3 more go to one connection per sensor.
        e = env()

        def empty(target):
            if target in (ps.CONNECT_TARGET, ps.CONNECT_TARGET_NO_GYRO):
                return StreamConn(e.clock, close_at=e.clock.t if how == "eof" else math.inf)
            return StreamConn(e.clock, ACC if target == T_ACC else None,
                              close_at=e.clock.t + 3.0)
        conn = TargetConnector(factory=empty)
        n = ps.EMPTY_SESSIONS_FALLBACK
        with caplog.at_level(logging.WARNING, logger=LOGGER):
            self._run(e, conn, n)
            assert e.sensors.mode == "no_gyro"
            self._run(e, conn, n)
        assert conn.calls[:2 * n] == [ps.CONNECT_TARGET] * n + [ps.CONNECT_TARGET_NO_GYRO] * n
        assert e.sensors.mode == "split"
        assert any("without a single frame" in r.getMessage() for r in caplog.records)

    def test_a_frame_resets_the_empty_session_count(self, env):
        e = env()
        kinds = iter([None, None, ACC, None, None])

        def factory(target):                     # built when connected (clock now)
            kind = next(kinds)
            return StreamConn(e.clock, kind, close_at=e.clock.t + (1.0 if kind else 0.0))
        conn = TargetConnector(factory=factory)
        self._run(e, conn, 5)
        assert conn.calls == [ps.CONNECT_TARGET] * 5
        assert e.sensors.mode == "combined"

    def test_split_light_refused_repeatedly_is_given_up(self, env, caplog):
        e = env()
        e.sensors._split = True
        timeouts = []

        def factory(target):
            if target == T_LIGHT:
                return StreamConn(e.clock, refuse=4002, reason="not available")
            return StreamConn(e.clock, ACC if target == T_ACC else GYRO,
                              close_at=e.clock.t + 120.0 - (e.clock.t - 1000.0))
        conn = TargetConnector(factory=factory)
        orig = conn.__call__

        def connect(host, port, target, timeout):
            timeouts.append((target, timeout))
            return orig(host, port, target, timeout)
        with caplog.at_level(logging.WARNING, logger=LOGGER):
            self._run(e, connect, 1)
        assert conn.calls.count(T_LIGHT) == ps.LIGHT_REFUSALS_MAX
        assert e.sensors._light_dead
        assert any("refused the light sensor" in r.getMessage() for r in caplog.records)
        assert e.sensors.state["types"]["light"]["refused"] is True
        assert [c.name for c in e.sensors._plan()] == ["accel", "gyro"]
        # Reopened while the accelerometer streamed: the short budget.
        reopen = [t for tgt, t in timeouts[3:] if tgt == T_LIGHT]
        assert reopen and set(reopen) == {ps.SPLIT_REOPEN_TIMEOUT_S}
        assert timeouts[0][1] == ps.CONNECT_TIMEOUT_S

    def test_split_frames_without_type_are_attributed(self):
        ch = ps._Channel("light", (LIGHT,), T_LIGHT)
        parsed, why = parse_frame('{"values": [12.5], "timestamp": 5}', ch.default_type)
        assert why == "" and parsed[0] == LIGHT and parsed[1] == (12.5,)
        assert parse_frame('{"values": [12.5]}')[1] == "unknown_type"
        # A frame that names another type is still checked as that type.
        parsed, _ = parse_frame(accel_frame([0, 0, G0]), LIGHT)
        assert parsed[0] == ACC


# ── statistics in phone_sensors.state ─────────────────────────────────────

class TestStateStatistics:
    def test_rates_lux_and_close(self, env):
        e = env()
        conn = TargetConnector(results={ps.CONNECT_TARGET: [StreamConn(
            e.clock, ACC, close_at=e.clock.t + 12.0)]})
        light = StreamConn(e.clock, LIGHT, period=0.5, lux=77.0)
        # Interleave light frames into the combined stream.
        combined = conn.results[ps.CONNECT_TARGET][0]
        orig = combined.receive

        def receive(timeout):
            if light.next_t <= e.clock.t:
                return light.receive(0.0)
            return orig(timeout)
        combined.receive = receive
        e.sensors._connect = conn
        e.bus.publish("net.car_phone", car_phone_payload())
        e.sensors.cycle()
        states = e.topic("phone_sensors.state")
        streaming = [s for s in states if s["state"] == "streaming"]
        # (the very last one may come after the close: not subscribed any more)
        last = [s for s in streaming if s["types"]["accel"]["subscribed"]][-1]
        assert last["mode"] == "combined"
        assert 90 <= last["types"]["accel"]["hz"] <= 110
        assert last["types"]["accel"]["active"] and last["types"]["accel"]["subscribed"]
        assert last["types"]["gyro"]["subscribed"] and not last["types"]["gyro"]["active"]
        assert 1.5 <= last["types"]["light"]["hz"] <= 2.5
        assert last["lux"] == 77.0 and last["test_running"] is False
        # Statistics republished at most every 5 s while nothing else changes.
        assert len(streaming) <= 12
        end = e.sensors.state
        assert end["state"] == "error" and end["close"]["code"] == 1000
        assert end["close"]["channel"] == "all"
        assert set(end) >= {"state", "rate_hz", "calib_ok", "error", "since", "mode",
                            "types", "lux", "lux_ts", "close", "test_running"}

    def test_light_heartbeat_ends_with_its_connection(self, env):
        e = env()
        conn = TargetConnector(results={ps.CONNECT_TARGET: [StreamConn(
            e.clock, LIGHT, period=100.0, close_at=e.clock.t + 6.0)]})
        e.sensors._connect = conn
        e.bus.publish("net.car_phone", car_phone_payload())
        e.sensors.cycle()
        n = len(lux_values(e))
        assert 2 <= n <= 4                                          # one frame + heartbeats
        e.clock.advance(5.0)
        e.sensors.periodic(e.clock.t)
        assert len(lux_values(e)) == n                              # link gone: no more
        assert e.sensors.state["types"]["light"]["active"] is False

    def test_heartbeat_stops_after_the_cap_without_a_light_frame(self, env):
        e = env()
        e.sensors.handle_message(light_frame(80.0), e.clock.t)
        for _ in range(int(ps.LIGHT_HEARTBEAT_MAX_S / 2) + 20):
            e.clock.advance(2.0)
            e.sensors.periodic(e.clock.t)
        out = e.topic("phone.light_lux")
        assert out and all(v["frame_age_s"] < ps.LIGHT_HEARTBEAT_MAX_S for v in out)
        n = len(out)
        assert n >= ps.LIGHT_HEARTBEAT_MAX_S / 2 - 5
        e.clock.advance(10.0)
        e.sensors.periodic(e.clock.t)
        assert len(e.topic("phone.light_lux")) == n                 # stale: brightness falls back
        assert e.sensors._extras("stale")["types"]["light"]["active"] is False
        e.sensors.handle_message(light_frame(3.0), e.clock.t)        # a new frame: back
        e.clock.advance(2.0)
        e.sensors.periodic(e.clock.t)
        assert len(e.topic("phone.light_lux")) > n


# ── the test command ──────────────────────────────────────────────────────

class TestSensorTest:
    def _drive(self, e, seconds, light=True):
        for i in range(int(seconds * 100)):
            e.drive.sample((0.0, 0.0, G0), 0.05)
            if light and i % 50 == 0:
                e.sensors.handle_message(light_frame(100.0 + i % 7), e.clock.t)

    def test_ok_with_frames_and_lux_range(self, env):
        e = env()
        e.bus.publish("net.car_phone", car_phone_payload())
        e.bus.publish(ps.TEST_TOPIC, True)
        self._drive(e, 10.5)
        res = e.topic(ps.TOPIC_TEST_RESULT)
        assert len(res) == 1
        r = res[0]
        assert r["verdict"] == "ok" and r["hint"] == ""
        assert 950 <= r["frames"]["accel"] <= 1010 and r["frames"]["light"] >= 19
        assert r["frames"]["gyro"] == 0 and 95 <= r["hz"]["accel"] <= 101
        assert 100.0 <= r["lux_min"] <= r["lux_max"] <= 106.0
        assert any(s["test_running"] for s in e.topic("phone_sensors.state"))
        assert e.sensors.state["test_running"] is False

    def test_no_light_names_what_to_check(self, env):
        e = env()
        e.bus.publish("net.car_phone", car_phone_payload())
        e.bus.publish(ps.TEST_TOPIC, True)
        self._drive(e, 10.5, light=False)
        r = e.topic(ps.TOPIC_TEST_RESULT)[0]
        assert (r["verdict"], r["hint"]) == ("no_light", "light")

    def _steady(self, e, seconds, accel_dt=0.01):
        """One light frame before the test, then accelerometer only: the
        on-change sensor in constant light (phone.light_lux heartbeats)."""
        e.sensors.handle_message(light_frame(321.0), e.clock.t)
        e.sensors.periodic(e.clock.t)
        e.bus.publish(ps.TEST_TOPIC, True)
        if accel_dt is None:
            for _ in range(int(seconds * 10)):
                e.clock.advance(0.1)
                e.sensors.periodic(e.clock.t)
            return
        e.drive.dt = accel_dt
        for _ in range(int(seconds / accel_dt)):
            e.drive.sample((0.0, 0.0, G0), 0.05)

    def test_steady_light_is_ok(self, env):
        e = env()
        e.bus.publish("net.car_phone", car_phone_payload())
        self._steady(e, 10.5)
        r = e.topic(ps.TOPIC_TEST_RESULT)[0]
        assert (r["verdict"], r["hint"]) == ("ok", "")
        assert r["frames"]["light"] == 0 and r["light_steady"] is True
        assert r["lux"] == 321.0 and r["lux_ts"] is not None
        assert r["lux_min"] is None and r["lux_max"] is None
        assert len(lux_values(e)) >= 5                              # heartbeat meanwhile

    def test_steady_light_without_accelerometer_is_no_accel(self, env):
        e = env()
        e.bus.publish("net.car_phone", car_phone_payload())
        self._steady(e, 10.5, accel_dt=None)
        r = e.topic(ps.TOPIC_TEST_RESULT)[0]
        assert (r["verdict"], r["hint"]) == ("no_accel", "accel")

    def test_steady_light_does_not_hide_a_slow_accelerometer(self, env):
        e = env()
        e.bus.publish("net.car_phone", car_phone_payload())
        self._steady(e, 10.5, accel_dt=1 / 50.0)
        r = e.topic(ps.TOPIC_TEST_RESULT)[0]
        assert (r["verdict"], r["hint"]) == ("low_rate", "rate")

    def test_light_older_than_the_heartbeat_cap_is_no_light(self, env):
        e = env()
        e.bus.publish("net.car_phone", car_phone_payload())
        e.sensors.handle_message(light_frame(5.0), e.clock.t)
        e.clock.advance(ps.LIGHT_HEARTBEAT_MAX_S + 1.0)
        e.bus.publish(ps.TEST_TOPIC, True)
        self._drive(e, 10.5, light=False)
        r = e.topic(ps.TOPIC_TEST_RESULT)[0]
        assert (r["verdict"], r["light_steady"]) == ("no_light", False)

    def test_light_only(self, env):
        e = env()
        e.bus.publish("net.car_phone", car_phone_payload())
        e.bus.publish(ps.TEST_TOPIC, True)
        for _ in range(110):
            e.clock.advance(0.1)
            e.sensors.handle_message(light_frame(5.0), e.clock.t)
            e.sensors.periodic(e.clock.t)
        r = e.topic(ps.TOPIC_TEST_RESULT)[0]
        assert (r["verdict"], r["hint"]) == ("no_accel", "accel")

    def test_low_rate(self, env):
        e = env()
        e.bus.publish("net.car_phone", car_phone_payload())
        e.drive.dt = 1 / 50.0
        e.bus.publish(ps.TEST_TOPIC, True)
        for i in range(530):
            e.drive.sample((0.0, 0.0, G0), 0.05)
            if i % 25 == 0:
                e.sensors.handle_message(light_frame(10.0), e.clock.t)
        r = e.topic(ps.TOPIC_TEST_RESULT)[0]
        assert (r["verdict"], r["hint"]) == ("low_rate", "rate")

    @pytest.mark.parametrize("payload, hint", [
        (None, "car_phone"),
        ({"state": "connected", "forwards": {}}, "restart"),
        (car_phone_payload(ok=False), "phone"),
    ])
    def test_no_forward_while_the_worker_waits(self, env, payload, hint):
        e = env()
        if payload is not None:
            e.bus.publish("net.car_phone", payload)
        assert e.sensors.cycle() == ps.WAIT_FORWARD_S
        e.bus.publish(ps.TEST_TOPIC, True)
        assert e.sensors._wake.is_set()
        for _ in range(5):
            wait = e.sensors.cycle()
            assert wait <= ps.TEST_DURATION_S                       # capped by the test
            if e.topic(ps.TOPIC_TEST_RESULT):
                break
            e.clock.advance(wait)
        r = e.topic(ps.TOPIC_TEST_RESULT)[0]
        assert 10.0 <= r["duration_s"] <= 10.5
        assert (r["verdict"], r["hint"]) == ("no_forward", hint)
        assert r["verdict"] in ps.TEST_VERDICTS and r["hint"] in ps.TEST_HINTS

    def test_second_request_while_running_is_ignored(self, env):
        e = env()
        e.bus.publish("net.car_phone", car_phone_payload())
        e.bus.publish(ps.TEST_TOPIC, True)
        self._drive(e, 3.0)
        e.bus.publish(ps.TEST_TOPIC, True)
        self._drive(e, 8.0)
        assert len(e.topic(ps.TOPIC_TEST_RESULT)) == 1


# ── a real multi-connection server (split mode, select()) ─────────────────

class MultiWsServer:
    """wsproto server on 127.0.0.1:0: each connection is answered by the
    request target — accelerometer frames (no ``type``), light frames, or
    a 4002 close (gyroscope)."""

    def __init__(self, hold_s=2.0):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.sock.settimeout(5)
        self.port = self.sock.getsockname()[1]
        self.hold_s = hold_s
        self.targets = []
        self.threads = []
        self.stop = threading.Event()
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while not self.stop.is_set():
            try:
                c, _ = self.sock.accept()
            except OSError:
                return
            th = threading.Thread(target=self._serve, args=(c,), daemon=True)
            th.start()
            self.threads.append(th)

    def _serve(self, c):
        c.settimeout(5)
        ws = WSConnection(ConnectionType.SERVER)
        target = None
        try:
            while target is None:
                ws.receive_data(c.recv(4096))
                for ev in ws.events():
                    if isinstance(ev, Request):
                        target = ev.target
            self.targets.append(target)
            c.sendall(ws.send(AcceptConnection()))
            if target == T_GYRO:
                c.sendall(ws.send(CloseConnection(code=4002, reason="no gyroscope")))
                time.sleep(0.2)
                return
            end = time.monotonic() + self.hold_s
            i = 0
            while time.monotonic() < end and not self.stop.is_set():
                if target == T_ACC:
                    out = b"".join(ws.send(TextMessage(json.dumps(
                        {"values": [0.0, 0.0, G0], "timestamp": 10**9 + (i + k) * 10**7})))
                        for k in range(5))
                    i += 5
                    c.sendall(out)
                    time.sleep(0.05)
                else:
                    c.sendall(ws.send(TextMessage(json.dumps({"values": [321.0],
                                                              "timestamp": 10**9 + i}))))
                    i += 1
                    time.sleep(0.3)
            c.sendall(ws.send(CloseConnection(code=1000)))
            time.sleep(0.1)
        except OSError:
            pass
        finally:
            c.close()

    def close(self):
        self.stop.set()
        self.sock.close()


class TestSplitWithRealSockets:
    def test_client_fileno_pending_and_non_blocking_receive(self):
        srv = MultiWsServer(hold_s=1.0)
        try:
            client = WsClient.open("127.0.0.1", srv.port, T_LIGHT, 2.0)
            assert isinstance(client.fileno(), int)
            t0 = time.monotonic()
            assert client.receive(0.0) is None or True              # never blocks
            assert time.monotonic() - t0 < 0.1
            deadline = time.monotonic() + 2
            msg = None
            while msg is None and time.monotonic() < deadline:
                msg = client.receive(0.2)
            assert msg and json.loads(msg)["values"] == [321.0]
            client.close()
        finally:
            srv.close()

    def test_split_session_end_to_end(self, tmp_path):
        srv = MultiWsServer(hold_s=2.5)
        bus = EventBus()
        seen = []
        bus.subscribe("*", lambda t, v, ts: seen.append((t, v)))
        bus.publish("net.car_phone", car_phone_payload(local=srv.port))
        sensors = PhoneSensors({}, bus, state_path=str(tmp_path / "s.json"))
        sensors._split = True
        try:
            sensors.cycle()                                         # one split session
        finally:
            srv.close()
        assert set(srv.targets) >= {T_ACC, T_GYRO, T_LIGHT}
        assert sensors.stats["accel"] >= 100                        # ~200 frames in 2.5 s
        assert sensors.stats["light"] >= 3
        assert sensors._gyro_dead
        assert any(t == "phone.light_lux" and v["lux"] == 321.0 for t, v in seen)
        assert any(t == "phone.g_force" for t, v in seen)
        assert any(t == "phone_sensors.state" and v["state"] == "streaming" for t, v in seen)


# ── web: summary and route ────────────────────────────────────────────────

STATE = {"state": "streaming", "rate_hz": 99.4, "calib_ok": True, "error": "", "since": 1.7e9,
         "mode": "split",
         "types": {"accel": {"subscribed": True, "active": True, "hz": 99.4, "refused": False},
                   "gyro": {"subscribed": False, "active": False, "hz": 0.0, "refused": True},
                   "light": {"subscribed": True, "active": True, "hz": 0.5, "refused": False}},
         "lux": 88.0, "lux_ts": 1.7e9, "test_running": False,
         "close": {"code": 4002, "reason": "no gyroscope", "ts": 1.7e9, "channel": "gyro"}}
RESULT = {"ts": 1.7e9, "duration_s": 10.0, "mode": "split", "verdict": "no_light",
          "hint": "light", "frames": {"accel": 1000, "gyro": 0, "light": 0},
          "hz": {"accel": 100.0, "gyro": 0.0, "light": 0.0}, "lux_min": None,
          "lux_max": None, "light_steady": False, "lux": 88.0, "lux_ts": 1.7e9 - 20.0,
          "state": "streaming", "error": ""}


class TestSummary:
    def test_full(self):
        out = wv._phone_sensors_summary(STATE, RESULT, car_phone_payload(), now=1.7e9 + 12.34)
        assert out == {
            "state": "streaming", "mode": "split", "error": "", "rate_hz": 99.4,
            "calib_ok": True, "types": STATE["types"], "lux": 88.0, "lux_age_s": 12.3,
            "close": {"code": 4002, "reason": "no gyroscope", "channel": "gyro"},
            "test": {"running": False, "result": {
                "ts": 1.7e9, "verdict": "no_light", "hint": "light",
                "frames": {"accel": 1000, "gyro": 0, "light": 0},
                "hz": {"accel": 100.0, "gyro": 0.0, "light": 0.0},
                "lux_min": None, "lux_max": None, "light_steady": False, "lux": 88.0,
                "lux_age_s": 20.0, "duration_s": 10.0}},
            "forward": {"ok": True, "error": ""}}

    def test_module_off_and_forward_missing(self):
        assert wv._phone_sensors_summary(None, None, None) is None
        assert wv._phone_sensors_summary("streaming", None, None) is None
        out = wv._phone_sensors_summary(STATE, None, {"state": "connected", "forwards": {}})
        assert out["forward"] == {"ok": False, "error": "missing"}
        assert out["test"]["result"] is None
        assert wv._phone_sensors_summary(STATE, None, None)["forward"] is None

    def test_garbage_is_neutralised(self):
        bad = {"state": "<script>", "mode": "x", "error": "a\nb" * 300, "rate_hz": float("nan"),
               "calib_ok": "yes", "types": {"accel": {"hz": 1e12, "active": 1},
                                            "light": "x"},
               "lux": -5, "lux_ts": "now", "test_running": "true",
               "close": {"code": True, "reason": "<b>" * 100, "channel": "<x>"}}
        res = {"verdict": "<img>", "hint": "x"}
        out = wv._phone_sensors_summary(bad, res, {"forwards": {"sensors": {
            "ok": "yes", "error": "line1\nline2", "local": 951}}})
        assert out["state"] == "unknown" and out["mode"] == "" and out["rate_hz"] == 0.0
        assert len(out["error"]) <= 200 and "\n" not in out["error"]
        assert out["calib_ok"] is False and out["lux"] is None and out["lux_age_s"] is None
        assert out["types"]["accel"] == {"subscribed": False, "active": False, "hz": 0.0,
                                         "refused": False}
        assert out["types"]["light"] == {"subscribed": False, "active": False, "hz": 0.0,
                                         "refused": False}
        assert out["close"]["code"] is None and out["close"]["channel"] == ""
        assert len(out["close"]["reason"]) <= ps.CLOSE_REASON_MAX
        assert out["test"] == {"running": False, "result": None}
        assert out["forward"] == {"ok": False, "error": "line1 line2"}
        res2 = dict(RESULT, hint="<x>", frames={"accel": -1, "light": True}, hz={"accel": "9"},
                    lux_min=float("inf"), duration_s=1e9, light_steady="yes", lux=-1,
                    lux_ts=1.7e9 + 50)                     # after the result: no age
        r = wv._phone_sensors_test_summary(res2)
        assert r["hint"] == "" and r["frames"] == {"accel": 0, "gyro": 0, "light": 0}
        assert r["hz"]["accel"] == 0.0 and r["lux_min"] is None and r["duration_s"] is None
        assert r["light_steady"] is False and r["lux"] is None and r["lux_age_s"] is None

    def test_car_phone_summary_keeps_known_forwards_only(self):
        out = wv._car_phone_summary({"state": "connected", "forwards": {
            "sensors": {"local": 951, "remote": 8080, "ok": True, "error": ""},
            "agent": {"local": 952, "remote": 8765, "ok": False, "error": "adb: refused"},
            "<evil>": {"ok": True}}})
        assert out["forwards"] == {"sensors": {"ok": True, "error": ""},
                                   "agent": {"ok": False, "error": "adb: refused"}}
        assert wv._car_phone_summary({"state": "connected"})["forwards"] == {}


@pytest.fixture
def web():
    bus = EventBus()
    cfg = BCMConfig(platform_override="x86", local_path=None, env={})
    cfg.save = lambda path=None: None
    viewer = WebViewer(host="127.0.0.1", port=5099, event_bus=bus, config=cfg)
    client = viewer._build_app().test_client()
    sent = []
    bus.subscribe(ps.TEST_TOPIC, lambda t, v, ts: sent.append(v))
    e = type("Web", (), {})()
    e.bus, e.viewer, e.client, e.sent = bus, viewer, client, sent
    return e


class TestRoute:
    def test_starts_the_test(self, web):
        web.bus.publish(ps.TOPIC_STATE, STATE)
        res = web.client.post("/api/phone_sensors/test", data="ignored")
        assert res.status_code == 202 and res.get_json()["started"] is True
        assert web.sent == [True]

    def test_rate_limited(self, web):
        web.bus.publish(ps.TOPIC_STATE, STATE)
        assert web.client.post("/api/phone_sensors/test").status_code == 202
        res = web.client.post("/api/phone_sensors/test")
        assert res.status_code == 429 and int(res.headers["Retry-After"]) >= 1
        assert len(web.sent) == 1

    def test_busy_and_disabled(self, web):
        assert web.client.post("/api/phone_sensors/test").status_code == 409   # no module
        web.bus.publish(ps.TOPIC_STATE, dict(STATE, state="disabled"))
        assert web.client.post("/api/phone_sensors/test").get_json()["error"] == "disabled"
        web.bus.publish(ps.TOPIC_STATE, dict(STATE, test_running=True))
        res = web.client.post("/api/phone_sensors/test")
        assert res.status_code == 409 and res.get_json()["error"] == "busy"
        assert web.sent == []

    @pytest.mark.parametrize("addr, base", [
        ("10.0.0.5", "http://localhost"),
        ("127.0.0.1", "http://evil.example:5002"),      # DNS rebinding
    ])
    def test_loopback_kiosk_only(self, web, addr, base):
        web.bus.publish(ps.TOPIC_STATE, STATE)
        res = web.client.post("/api/phone_sensors/test", environ_base={"REMOTE_ADDR": addr},
                              base_url=base)
        assert res.status_code == 403 and web.sent == []

    def test_foreign_origin_refused(self, web):
        web.bus.publish(ps.TOPIC_STATE, STATE)
        res = web.client.post("/api/phone_sensors/test", headers={"Origin": "http://evil.example"})
        assert res.status_code == 403 and web.sent == []

    def test_not_reachable_read_only(self):
        assert "api_phone_sensors_test" not in wv._READONLY_ENDPOINTS
        assert "api_phone_sensors_test" not in wv._TRACKING_ENDPOINTS

    def test_payload(self, web):
        web.bus.publish(ps.TOPIC_STATE, STATE)
        web.bus.publish(ps.TOPIC_TEST_RESULT, RESULT)
        web.bus.publish("net.car_phone", car_phone_payload(ok=False, error="adb: no device"))
        data = web.viewer._get_dashboard_data()
        assert data["phone_sensors"]["test"]["result"]["verdict"] == "no_light"
        assert data["phone_sensors"]["forward"] == {"ok": False, "error": "adb: no device"}
        assert data["car_phone"]["forwards"]["sensors"]["ok"] is False

    def test_payload_without_module(self, web):
        assert web.viewer._get_dashboard_data()["phone_sensors"] is None
