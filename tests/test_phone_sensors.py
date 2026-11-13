"""Car phone sensors: SensorServer client and processing (src/sensors/phone_sensors.py).

The processing is driven sample by sample (pure classes, FakeClock); the
worker's connect/stream/backoff logic runs against an injected connection
factory that advances the same clock; the small WebSocket client itself is
exercised against a real wsproto server on 127.0.0.1:0 in a thread. Files
(the gravity reference) live in ``tmp_path`` only.
"""

import json
import logging
import math
import os
import socket
import threading
import time
from pathlib import Path

import pytest
from wsproto import ConnectionType, WSConnection
from wsproto.events import (AcceptConnection, BytesMessage, CloseConnection, Ping, Pong,
                            RejectConnection, Request, TextMessage)

import main
from src.core import modules_catalog
from src.core.config import BCMConfig
from src.core.event_bus import EventBus
from src.safety.crash_detect import CrashConfig
from src.sensors import phone_sensors as ps
from src.sensors.phone_sensors import (AccelProcessor, ConnectionClosed, GravityCalibrator,
                                       LightSmoother, PhoneSensors, WsClient, load_reference,
                                       parse_frame)
from tests.sensor_sim import G0, MOUNT, Drive, FakeClock, _apply, _mul, _rot_x, accel_frame, \
    gyro_frame, light_frame

REPO = Path(__file__).resolve().parent.parent
ACC = "android.sensor.accelerometer"
GYRO = "android.sensor.gyroscope"
G_KEYS = {"ts", "mono", "rate_hz", "sat", "peak_h_g", "peak_v_g", "dv_h_kmh_150ms",
          "dv_window_ms", "n_over_g", "freefall_ms", "calib_ok", "lag_ms", "overrun"}
HUGE = "1" + "0" * 400                   # a JSON integer float() cannot hold


def car_phone_payload(local=951, ok=True, state="connected"):
    return {"state": state, "forwards": {"sensors": {"local": local, "remote": 8080, "ok": ok,
                                                     "error": ""}}}


@pytest.fixture
def env(tmp_path):
    def make(config=None, connect=None, rate_hz=100.0, **drive_kw):
        clock = FakeClock()
        bus = EventBus()
        seen = []
        bus.subscribe("*", lambda t, v, ts: seen.append((t, v)))
        sensors = PhoneSensors(config or {}, bus, connect=connect or (lambda *a: None),
                               clock=clock.mono, wall_clock=clock.wall,
                               state_path=str(tmp_path / "phone_sensors.json"))
        drive = Drive(sensors, bus, clock, rate_hz=rate_hz, **drive_kw)
        e = type("Env", (), {})()
        e.clock, e.bus, e.sensors, e.drive, e.seen = clock, bus, sensors, drive, seen
        e.topic = lambda name: [v for t, v in seen if t == name]
        e.state_path = tmp_path / "phone_sensors.json"
        return e

    return make


def no_alarm_topics(e):
    assert not any(t.startswith("alarm.") for t, _ in e.seen)


# ── frames ────────────────────────────────────────────────────────────────

class TestParseFrame:
    def test_accelerometer_and_light(self):
        assert parse_frame(accel_frame([0.1, -0.2, 9.8], 123)) == ((ACC, (0.1, -0.2, 9.8), 123),
                                                                   "")
        assert parse_frame(light_frame(250.5, 7)) == (("android.sensor.light", (250.5,), 7), "")

    def test_light_with_padding_values_keeps_the_first(self):
        raw = json.dumps({"type": "android.sensor.light", "values": [12.0, 0, 0]})
        assert parse_frame(raw) == (("android.sensor.light", (12.0,), None), "")

    @pytest.mark.parametrize("raw, why", [
        (b'{"type": "android.sensor.light"}', "garbage"),
        (None, "garbage"),
        ("not json", "garbage"),
        ("[1, 2, 3]", "garbage"),
        ('"string"', "garbage"),
        ("[" * 1500 + "]" * 1500, "oversize"),
        ("[" * 1000 + "]" * 1000, "garbage"),            # nesting bomb under the size cap
        ('{"type": "android.sensor.accelerometer", "values": [NaN, 0, 9.8]}', "garbage"),
        ('{"type": "android.sensor.accelerometer", "values": [Infinity, 0, 9.8]}', "garbage"),
        ('{"type": "android.sensor.magnetic_field", "values": [0, 0, 0]}', "unknown_type"),
        ('{"type": "android.sensor.gyroscope", "values": [0, 0]}', "invalid"),
        ('{"type": "android.sensor.gyroscope", "values": [0, 0, 40]}', "invalid"),
        ('{"type": "android.sensor.accelerometer", "values": [' + HUGE + ', 0, 0]}', "invalid"),
        ('{"type": "android.sensor.accelerometer", "values": [0, -' + HUGE + ', 0]}', "invalid"),
        ('{"type": "android.sensor.gyroscope", "values": [0, 0, ' + HUGE + ']}', "invalid"),
        ('{"type": "android.sensor.light", "values": [' + HUGE + ']}', "invalid"),
        ('{"values": [0, 0, 9.8]}', "unknown_type"),
        ('{"type": ["android.sensor.accelerometer"], "values": [0, 0, 9.8]}', "unknown_type"),
        ('{"type": "android.sensor.accelerometer", "values": [0, 9.8]}', "invalid"),
        ('{"type": "android.sensor.accelerometer", "values": [0, 0, 9.8, 1]}', "invalid"),
        ('{"type": "android.sensor.accelerometer", "values": [0, 0, "9.8"]}', "invalid"),
        ('{"type": "android.sensor.accelerometer", "values": [0, 0, true]}', "invalid"),
        ('{"type": "android.sensor.accelerometer", "values": [0, 0, 1e400]}', "invalid"),
        ('{"type": "android.sensor.accelerometer", "values": [0, 0, 700]}', "invalid"),
        ('{"type": "android.sensor.accelerometer", "values": "0,0,9.8"}', "invalid"),
        ('{"type": "android.sensor.accelerometer", "values": []}', "invalid"),
        ('{"type": "android.sensor.light", "values": [-1]}', "invalid"),
        ('{"type": "android.sensor.light", "values": [250000]}', "invalid"),
    ])
    def test_hostile_or_broken_frames(self, raw, why):
        assert parse_frame(raw) == (None, why)

    @pytest.mark.parametrize("ts", [-1, 1.5, "123", True, 2**63, None])
    def test_bad_timestamp_falls_back_to_arrival(self, ts):
        raw = json.dumps({"type": ACC, "values": [0, 0, 9.8], "timestamp": ts})
        assert parse_frame(raw) == ((ACC, (0.0, 0.0, 9.8), None), "")

    def test_gyroscope(self):
        assert parse_frame(json.dumps({"type": GYRO, "values": [0.5, -1, 2], "timestamp": 9})) \
            == ((GYRO, (0.5, -1.0, 2.0), 9), "")

    def test_huge_integer_is_counted_and_the_stream_goes_on(self, env):
        e = env()
        raw = '{"type": "android.sensor.accelerometer", "values": [' + HUGE + ', 0, 0]}'
        assert len(raw) < ps.MAX_FRAME_BYTES
        e.sensors.handle_message(raw, e.clock.t)               # must not raise
        assert e.sensors.stats["invalid"] == 1
        frames = [raw] + [accel_frame([0, 0, G0], 10**9 + i * 10**7) for i in range(5)]
        fake = type("Conn", (), {})()
        fake.closed = False

        def receive(timeout):
            if frames:
                e.clock.advance(0.01)
                return frames.pop(0)
            raise ConnectionClosed("closed by the phone (code 1000)")
        fake.receive = receive
        fake.close = lambda: setattr(fake, "closed", True)
        e.sensors.stream(fake, 951)
        assert e.sensors.stats["invalid"] == 2 and e.sensors.stats["accel"] == 5
        assert "closed by the phone" in e.sensors.state["error"]

    def test_unknown_types_and_garbage_are_counted_not_processed(self, env):
        e = env()
        for raw in ("x", '{"type": "android.sensor.magnetic_field", "values": [1, 2, 3]}',
                    "y" * 3000):
            e.sensors.handle_message(raw, e.clock.t)
        assert e.sensors.stats["garbage"] == 1 and e.sensors.stats["unknown_type"] == 1
        assert e.sensors.stats["oversize"] == 1 and e.sensors.accel.samples == 0

    def test_frames_beyond_the_per_second_cap_are_dropped(self, env):
        e = env()
        for i in range(ps.MAX_FRAMES_PER_S + 50):
            e.sensors.handle_message(accel_frame([0, 0, 9.8], 10**9 + i * 10**6), e.clock.t)
        assert e.sensors.accel.samples == ps.MAX_FRAMES_PER_S
        assert e.sensors.stats["dropped_rate"] == 50
        # the truncated second is flagged: its rate still looks fine
        assert e.sensors.accel.snapshot(0, 0)["overrun"] is True
        e.clock.advance(1.0)
        e.sensors.handle_message(accel_frame([0, 0, 9.8], 2 * 10**9), e.clock.t)
        assert e.sensors.accel.samples == ps.MAX_FRAMES_PER_S + 1
        assert e.sensors.accel.snapshot(0, 0)["overrun"] is False

    def test_bad_frames_are_reported_once_a_minute(self, env, caplog):
        e = env()
        with caplog.at_level(logging.WARNING, logger="bcm.sensors.phone"):
            for i in range(30):
                e.sensors.handle_message("garbage", e.clock.t)
                e.sensors.periodic(e.clock.t)
                e.clock.advance(1.0)
        msgs = [r.getMessage() for r in caplog.records if "frames ignored" in r.getMessage()]
        assert len(msgs) == 1 and "garbage=1" in msgs[0]


# ── accelerometer pipeline ────────────────────────────────────────────────

def feed(proc, seconds, f_phone=(0.0, 0.0, G0), rate=100.0, t0=0.0):
    dt = 1.0 / rate
    n = int(round(seconds * rate))
    for i in range(n):
        proc.add(t0 + (i + 1) * dt, *f_phone)
    return t0 + n * dt


class TestAccelProcessor:
    def make(self, **crash):
        return AccelProcessor(CrashConfig(**crash), 8.0)

    def test_rate_from_sensor_timestamps(self):
        p = self.make()
        feed(p, 2.0)
        assert p.rate_hz == pytest.approx(100.0, rel=0.01)
        p2 = self.make()
        feed(p2, 2.0, rate=50.0)
        assert p2.rate_hz == pytest.approx(50.0, rel=0.01)

    def test_batched_arrival_does_not_distort_the_rate(self, env):
        e = env()
        ts = 5 * 10**9
        for batch in range(10):                 # 10 batches of 20 frames, 200 ms apart
            for i in range(20):
                ts += 10**7
                e.sensors.handle_message(accel_frame([0, 0, 9.8], ts), e.clock.t)
            e.clock.advance(0.2)
        assert e.sensors.accel.rate_hz == pytest.approx(100.0, rel=0.01)

    def test_no_timestamps_use_the_arrival_time(self, env):
        e = env(timestamps=False)
        e.drive.rest(2.0)
        assert e.sensors.accel.rate_hz == pytest.approx(100.0, rel=0.02)

    def test_duplicate_dropped_step_back_and_gap_restart(self):
        p = self.make()
        assert p.add(1.0, 0, 0, G0) and p.add(1.01, 0, 0, G0)
        assert p.add(1.01, 0, 0, G0) is False                  # same timestamp again
        assert p.add(0.5, 0, 0, G0) and p.resets == 1          # phone rebooted / app restart
        assert p.add(10.0, 0, 0, G0) and p.resets == 2         # 9.5 s gap

    def test_saturation_against_the_configured_range(self):
        p = self.make()
        feed(p, 0.2)
        p.add(10.0, 0.0, 0.98 * 8 * G0, G0)
        assert p.snapshot(0, 0)["sat"] is True
        assert p.snapshot(0, 0)["sat"] is False                # reset per period
        p16 = AccelProcessor(CrashConfig(), 16.0)
        feed(p16, 0.2)
        p16.add(10.0, 0.0, 0.98 * 8 * G0, G0)
        assert p16.snapshot(0, 0)["sat"] is False

    def test_horizontal_vertical_split_on_a_tilted_mount(self):
        calib = GravityCalibrator()
        p = AccelProcessor(CrashConfig(), 8.0, calib)
        rest = _apply(MOUNT, (0.0, 0.0, G0))
        t = feed(p, 12.0, rest)
        assert calib.calib_ok
        p.snapshot(0, 0)
        # 3 g forward (car frame) → horizontal
        t = feed(p, 0.05, _apply(MOUNT, (3 * G0, 0.0, G0)), t0=t)
        snap = p.snapshot(0, 0)
        assert snap["peak_h_g"] == pytest.approx(3.0, abs=0.05)
        assert snap["peak_v_g"] == pytest.approx(0.0, abs=0.05)
        # 3 g up (a pothole) → vertical
        feed(p, 0.05, _apply(MOUNT, (0.0, 0.0, 4 * G0)), t0=t)
        snap = p.snapshot(0, 0)
        assert snap["peak_v_g"] == pytest.approx(3.0, abs=0.05)
        assert snap["peak_h_g"] == pytest.approx(0.0, abs=0.05)

    def test_dv_over_the_window_and_over_threshold_run(self):
        calib = GravityCalibrator()
        p = AccelProcessor(CrashConfig(), 8.0, calib)
        t = feed(p, 12.0)
        p.snapshot(0, 0)
        t = feed(p, 0.3, (2 * G0, 0.0, G0), t0=t)              # 2 g for 300 ms
        snap = p.snapshot(0, 0)
        assert snap["dv_h_kmh_150ms"] == pytest.approx(2 * G0 * 0.15 * 3.6, rel=0.08)
        assert snap["n_over_g"] == 0 and snap["dv_window_ms"] == 150
        t = feed(p, 0.03, (5 * G0, 0.0, G0), t0=t)             # 3 samples over 4 g
        assert p.snapshot(0, 0)["n_over_g"] == 3
        t = feed(p, 0.02, (5 * G0, 0.0, G0), t0=t)             # the run continues
        assert p.snapshot(0, 0)["n_over_g"] == 5
        feed(p, 0.01, (0.0, 0.0, G0), t0=t)
        assert p.snapshot(0, 0)["n_over_g"] == 0

    def test_configured_window_and_threshold(self):
        p = AccelProcessor(CrashConfig(dv_window_ms=100.0, g_h_threshold=2.0), 8.0)
        t = feed(p, 12.0)
        p.snapshot(0, 0)
        feed(p, 0.3, (3 * G0, 0.0, G0), t0=t)
        snap = p.snapshot(0, 0)
        assert snap["dv_h_kmh_150ms"] == pytest.approx(3 * G0 * 0.1 * 3.6, rel=0.1)
        assert snap["dv_window_ms"] == 100 and snap["n_over_g"] == 30

    def test_vibration_cancels_out_of_dv(self):
        p = AccelProcessor(CrashConfig(), 8.0)
        t = feed(p, 12.0)
        p.snapshot(0, 0)
        for i in range(100):                    # ±3 g at 50 Hz: a rough road / holder rattle
            sign = 1 if (i // 1) % 2 == 0 else -1
            t += 0.01
            p.add(t, sign * 3 * G0, 0.0, G0)
        snap = p.snapshot(0, 0)
        assert snap["peak_h_g"] == pytest.approx(3.0, abs=0.1)
        assert snap["dv_h_kmh_150ms"] < 2.0

    def test_free_fall_duration_just_before(self):
        p = AccelProcessor(CrashConfig(), 8.0)
        t = feed(p, 2.0)
        p.snapshot(0, 0)
        t = feed(p, 0.12, (0.0, 0.0, 0.5), t0=t)               # |a| < 0.3 g for 120 ms
        t = feed(p, 0.05, (0.0, 0.0, G0), t0=t)
        assert p.snapshot(0, 0)["freefall_ms"] == pytest.approx(120, abs=10)
        t = feed(p, 0.5, t0=t)
        assert p.snapshot(0, 0)["freefall_ms"] == pytest.approx(120, abs=10)   # within 1 s
        t = feed(p, 0.5, t0=t)
        p.snapshot(0, 0)
        feed(p, 0.5, t0=t)                      # > 1 s after the fall ended
        assert p.snapshot(0, 0)["freefall_ms"] == 0

    def test_windows_are_bounded_when_timestamps_barely_advance(self):
        # A broken app (or one not sending ns) whose timestamps advance 1 ns
        # per sample: time trimming never evicts, the count caps must.
        p = self.make()
        t = 1.0
        for i in range(50_000):
            t += 1e-9
            p.add(t, 0.1 * (i % 7), 0.2, G0)
        assert len(p._buf) <= p._buf_max and len(p._rate) <= p._rate_max
        assert len(p._dv) <= p._dv_max
        for i in range(3):
            assert p._sum[i] == pytest.approx(sum(s[i + 1] for s in p._buf), abs=1e-6)
            assert p._dv_sum[i] == pytest.approx(sum(s[i + 1] for s in p._dv), abs=1e-6)
        assert p.rate_hz == 0.0                 # fails safe for crash_detect

    def test_dense_real_data_is_not_truncated_by_the_caps(self):
        # 500 Hz (a phone on "fastest"): the 150 ms window keeps every sample.
        p = self.make()
        feed(p, 2.0, rate=500.0)
        assert 75 <= len(p._dv) <= 76 and len(p._buf) == 1000

    def test_lag_of_a_late_backlog(self):
        p = self.make()
        t = 0.0
        for _ in range(300):                    # live: arrives 30 ms after the event
            t += 0.01
            p.add(t, 0.0, 0.0, G0, arrival=t + 0.03)
        assert p.snapshot(0, 0)["lag_ms"] == 0
        stall_end = t + 3.0                     # 3 s stall, then the backlog at once
        for _ in range(300):
            t += 0.01
            p.add(t, 0.0, 0.0, G0, arrival=stall_end)
        snap = p.snapshot(0, 0)
        # the first backlog sample: 2.99 s after its event, 30 ms is normal
        assert snap["lag_ms"] == pytest.approx(2960, abs=5) and p.late > 0
        for _ in range(100):                    # live again
            t += 0.01
            p.add(t, 0.0, 0.0, G0, arrival=t + 0.03)
        assert p.snapshot(0, 0)["lag_ms"] <= 50

    def test_constant_offset_and_clock_drift_are_not_lag(self):
        p = self.make()
        t = 0.0
        for i in range(6000):                   # 60 s, phone clock 100 ppm slow
            t += 0.01
            p.add(t, 0.0, 0.0, G0, arrival=500.0 + t * 1.0001)
        assert p.snapshot(0, 0)["lag_ms"] <= 3

    def test_timestamps_not_in_ns_switch_to_the_arrival_time(self, env, caplog):
        e = env()
        with caplog.at_level(logging.WARNING, logger="bcm.sensors.phone"):
            for _ in range(1000):               # 10 s at 100 Hz, timestamps in ms
                e.clock.advance(0.01)
                e.sensors.handle_message(accel_frame([0, 0, G0], int(e.clock.t * 1000)),
                                         e.clock.t)
        assert e.sensors._clock_bad
        assert e.sensors.accel.rate_hz == pytest.approx(100.0, rel=0.02)
        assert len([r for r in caplog.records if "not nanoseconds" in r.getMessage()]) == 1

    def test_ns_timestamps_with_batched_arrival_stay_in_use(self, env):
        e = env()
        ts = 10**9
        for _ in range(40):                     # 8 s: batches of 20 frames, 200 ms apart
            for _ in range(20):
                ts += 10**7
                e.sensors.handle_message(accel_frame([0, 0, G0], ts), e.clock.t)
            e.clock.advance(0.2)
        assert not e.sensors._clock_bad and e.sensors.accel.resets == 0

    @pytest.mark.parametrize("omega, falling", [(10.0, True), (2.0, False), (None, False)])
    def test_tumbling_fall_is_free_fall_with_the_gyroscope(self, env, omega, falling):
        # 0.5 g read in the phone's own axes: the centripetal part of a spin.
        e = env(gyro=omega is not None)
        e.drive.rest(2.0)
        e.sensors.accel.snapshot(0, 0)
        e.drive.tumbling_fall(0.3, reading_g=0.5, omega=omega or 0.0)
        e.drive.rest(0.1)
        ff = e.sensors.accel.snapshot(0, 0)["freefall_ms"]
        assert (ff >= 250) is falling
        assert e.sensors.stats["gyro"] == (0 if omega is None else 240)

    def test_payload_keys(self, env):
        e = env()
        e.drive.rest(1.0)
        msg = e.topic("phone.g_force")[-1]
        assert set(msg) == G_KEYS
        assert msg["mono"] == pytest.approx(e.clock.t, abs=0.11)
        assert msg["rate_hz"] == pytest.approx(100.0, rel=0.02)
        assert msg["calib_ok"] is False                        # not calibrated yet
        no_alarm_topics(e)

    def test_published_at_most_10_hz(self, env):
        e = env()
        e.drive.rest(3.0)
        monos = [m["mono"] for m in e.topic("phone.g_force")]
        assert 28 <= len(monos) <= 31
        assert all(b - a >= ps.G_PUBLISH_S - 1e-6 for a, b in zip(monos, monos[1:]))


# ── gravity calibration ───────────────────────────────────────────────────

class TestCalibration:
    def test_first_calibration_after_10_s_of_quiet_is_saved(self, env):
        e = env()
        e.drive.rest(9.0)
        assert not e.sensors.calib.calib_ok and not e.state_path.exists()
        e.drive.rest(1.6)
        assert e.sensors.calib.calib_ok
        data = json.loads(e.state_path.read_text())
        want = _apply(MOUNT, (0.0, 0.0, 1.0))
        assert all(abs(a - b) < 0.02 for a, b in zip(data["gravity"], want))
        assert [n for n in os.listdir(e.state_path.parent) if n.endswith(".tmp")] == []
        assert e.topic("phone.g_force")[-1]["calib_ok"] is True

    def test_road_vibration_never_calibrates(self, env):
        e = env()
        e.drive.cruise(60.0, 20.0)
        assert e.sensors.calib.ref is None and not e.sensors.calib.calib_ok

    def test_restart_keeps_it_but_verifies_first(self, env, tmp_path):
        e = env()
        e.drive.rest(11.0)
        assert e.state_path.exists()
        e2 = env()                                             # "BCM restarted"
        assert e2.sensors.calib.ref is not None
        assert not e2.sensors.calib.calib_ok
        e2.drive.rest(3.6)
        assert e2.sensors.calib.calib_ok

    def test_skewed_first_blocks_do_not_become_the_reference(self, env):
        # The first quiet seconds are a slow roll down a ramp before the stop
        # (8° off), then the car stands level: the reference is level, not
        # a mix of both.
        e = env()
        e.drive.mount = _mul(_rot_x(8.0), MOUNT)
        e.drive.rest(3.1)
        e.drive.mount = MOUNT
        e.drive.rest(11.5)
        ref = e.sensors.calib.ref
        assert ref is not None
        level = _apply(MOUNT, (0.0, 0.0, 1.0))
        assert ps.angle_deg(ref, level) < 1.0
        assert e.sensors.calib.calib_ok

    def test_restart_on_a_ramp_is_not_a_moved_phone(self, env):
        e = env()
        e.drive.rest(11.0)                      # calibrated level, saved
        e2 = env()                              # "BCM restarted" on an 11° ramp
        e2.drive.mount = _mul(_rot_x(11.0), MOUNT)
        e2.drive.rest(3.6)
        assert e2.sensors.calib.calib_ok
        e2.drive.rest(30.0)                     # a long red light on the ramp
        assert e2.sensors.calib.calib_ok

    def test_restart_after_a_remount_is_flagged_within_seconds(self, env):
        e = env()
        e.drive.rest(11.0)
        e2 = env()
        e2.drive.mount = _mul(_rot_x(30.0), MOUNT)             # re-mounted while off
        e2.drive.rest(4.0)
        assert e2.sensors.calib.drifted and not e2.sensors.calib.calib_ok
        assert e2.sensors.calib.drift_deg() == pytest.approx(30.0, abs=2.0)

    def test_phone_moved_in_the_holder_turns_calib_off_and_back(self, env):
        e = env(rate_hz=50.0)
        e.drive.rest(12.0)
        assert e.sensors.calib.calib_ok
        e.drive.mount = _mul(_rot_x(15.0), MOUNT)              # slipped by 15°
        e.drive.rest(100.0)
        assert e.sensors.calib.drifted and not e.sensors.calib.calib_ok
        assert e.topic("phone.g_force")[-1]["calib_ok"] is False
        e.drive.mount = MOUNT
        e.drive.rest(150.0)
        assert e.sensors.calib.calib_ok

    def test_recalibrate_command(self, env):
        e = env(rate_hz=50.0)
        e.drive.rest(12.0)
        old = json.loads(e.state_path.read_text())["gravity"]
        e.bus.subscribe(ps.RECALIBRATE_TOPIC, e.sensors._on_recalibrate)
        e.drive.mount = _mul(_rot_x(30.0), MOUNT)              # re-mounted
        e.bus.publish(ps.RECALIBRATE_TOPIC, "ignored argument")
        e.drive.rest(1.0)
        assert e.sensors.calib.ref is None and not e.sensors.calib.calib_ok
        e.drive.rest(11.0)
        assert e.sensors.calib.calib_ok
        new = json.loads(e.state_path.read_text())["gravity"]
        dot = sum(a * b for a, b in zip(old, new))
        assert math.degrees(math.acos(min(1.0, dot))) == pytest.approx(30.0, abs=1.0)

    @pytest.mark.parametrize("content", [
        "garbage", "[]", '{"gravity": [0, 0]}', '{"gravity": [0, 0, NaN]}',
        '{"gravity": [0, 0, 5]}', '{"gravity": [0, "0", 1]}', '{"gravity": [0, 0, true]}',
        '{"gravity": [0, 0, 1], "pad": "' + "x" * 5000 + '"}'])
    def test_invalid_state_file_is_ignored(self, tmp_path, content):
        path = tmp_path / "state.json"
        path.write_text(content)
        assert load_reference(str(path)) is None

    def test_huge_integer_in_the_state_file(self, tmp_path):
        path = tmp_path / "state.json"
        path.write_text('{"gravity": [' + HUGE + ', 0, 0]}')
        assert load_reference(str(path)) is None
        sensors = PhoneSensors({}, EventBus(), state_path=str(path))     # must not raise
        assert sensors.calib.ref is None

    def test_valid_state_file(self, tmp_path):
        path = tmp_path / "state.json"
        path.write_text('{"version": 1, "gravity": [0, 0.6, 0.8]}')
        assert load_reference(str(path)) == pytest.approx((0.0, 0.6, 0.8))
        assert load_reference(str(tmp_path / "missing.json")) is None

    def test_unwritable_state_file_keeps_working(self, env, tmp_path, caplog):
        e = env()
        e.sensors._state_path = str(tmp_path / "file" / "state.json")
        (tmp_path / "file").write_text("not a directory")
        with caplog.at_level(logging.WARNING, logger="bcm.sensors.phone"):
            e.drive.rest(11.0)
        assert e.sensors.calib.calib_ok
        assert any("saving the gravity reference failed" in r.getMessage()
                   for r in caplog.records)


# ── light ─────────────────────────────────────────────────────────────────

class TestLight:
    def test_smoother(self):
        s = LightSmoother()
        assert s.due(0.0) is None
        s.add(100.0)
        assert s.due(0.0) == 100.0                             # first one at once
        s.add(104.0)
        assert s.due(0.6) is None                              # 4 %: no news
        for v in (5000.0, 101.0, 103.0):                       # one spike: median wins
            s.add(v)
        assert s.due(1.0) is None
        assert s.due(2.1) == 103.0                             # heartbeat
        for v in (300.0, 310.0, 305.0):
            s.add(v)
        assert s.due(2.3) is None                              # <= 2 Hz
        assert s.due(2.7) == 300.0

    def test_low_light_small_steps(self):
        s = LightSmoother()
        s.add(0.0)
        assert s.due(0.0) == 0.0
        s.add(0.2)
        s.add(0.2)
        assert s.due(1.0) is None                              # below 0.5 lux
        s.add(2.0)
        s.add(2.0)
        assert s.due(1.6) == 0.2 or s.due(1.6) is None
        s.add(2.0)
        assert s.due(2.5) == 2.0

    def test_published_only_while_streaming(self, env):
        e = env()
        e.sensors.handle_message(light_frame(120.0, 10**9), e.clock.t)
        e.sensors.periodic(e.clock.t)
        assert e.topic("phone.light_lux") == []                # no accelerometer yet
        e.drive.rest(0.2)
        e.sensors.handle_message(light_frame(120.0, None), e.clock.t)
        e.drive.rest(0.2)
        lux = e.topic("phone.light_lux")
        assert lux and set(lux[0]) == {"lux", "ts"} and lux[0]["lux"] == 120.0
        e.drive.rest(5.0)
        assert 2 <= len(e.topic("phone.light_lux")) <= 4       # 2 s heartbeat


# ── the worker: forward, connect, backoff, stale ──────────────────────────

class FakeConn:
    """A SensorServer connection on the fake clock: ``frames`` accelerometer
    frames at 100 Hz (sensor time = clock time), then silence; ``fail_after``
    raises ConnectionClosed instead of the silence."""

    def __init__(self, clock, frames=0, fail_after=False, on_receive=None):
        self.clock = clock
        self.left = frames
        self.fail_after = fail_after
        self.on_receive = on_receive
        self.closed = False
        self.calls = 0

    def receive(self, timeout):
        self.calls += 1
        if self.on_receive:
            self.on_receive(self)
        if self.left > 0:
            self.left -= 1
            self.clock.advance(0.01)
            return accel_frame([0.0, 0.0, G0], int(round(self.clock.t * 1e9)))
        if self.fail_after:
            raise ConnectionClosed("closed by the phone (code 1000)")
        self.clock.advance(timeout)
        return None

    def close(self):
        self.closed = True


class Connector:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def __call__(self, host, port, target, timeout):
        self.calls.append((host, port, target, timeout))
        res = self.results.pop(0)
        if isinstance(res, Exception):
            raise res
        return res


class TestWorker:
    def test_waits_for_the_forward(self, env):
        conn = Connector([])
        e = env(connect=conn)
        assert e.sensors.cycle() == ps.WAIT_FORWARD_S
        assert e.topic("phone_sensors.state")[-1]["state"] == "waiting_forward"
        for payload in (car_phone_payload(ok=False), car_phone_payload(state="disabled"),
                        car_phone_payload(local=0), car_phone_payload(local="951"),
                        car_phone_payload(local=True), {"state": "connected"}, "x",
                        {"state": "connected", "forwards": {"agent": {"local": 952,
                                                                      "ok": True}}}):
            e.bus.publish("net.car_phone", payload)
            assert e.sensors.forward_port() is None, payload
            assert e.sensors.cycle() == ps.WAIT_FORWARD_S
        assert conn.calls == []

    def test_connects_to_the_forward_port_only(self, env):
        e = env()
        conn = Connector([FakeConn(e.clock, frames=0, fail_after=True)])
        e.sensors._connect = conn
        e.bus.publish("net.car_phone", car_phone_payload(local=961))
        e.sensors.cycle()
        assert conn.calls == [("127.0.0.1", 961, ps.CONNECT_TARGET, ps.CONNECT_TIMEOUT_S)]
        assert ps.CONNECT_TARGET == ('/sensors/connect?types=["android.sensor.accelerometer",'
                                     '"android.sensor.gyroscope","android.sensor.light"]')
        assert ps.CONNECT_TARGET_NO_GYRO == ('/sensors/connect?types=['
                                             '"android.sensor.accelerometer",'
                                             '"android.sensor.light"]')

    def test_backoff_doubles_to_the_cap(self, env, caplog):
        # Handshake failures reach the phone (SensorServer not running,
        # rejected, timeout): full backoff.
        e = env()
        conn = Connector([ConnectionClosed("connection closed during the handshake")] * 12)
        e.sensors._connect = conn
        e.bus.publish("net.car_phone", car_phone_payload())
        delays = []
        with caplog.at_level(logging.WARNING, logger="bcm.sensors.phone"):
            for _ in range(10):
                assert e.sensors.cycle() == 0.0
                state = e.sensors.state
                assert state["state"] == "error" and "cannot connect" in state["error"]
                delays.append(round(e.sensors._retry_at - e.clock.t, 3))
                assert 0 < e.sensors.cycle() <= ps.WAIT_FORWARD_S   # no connect meanwhile
                e.clock.t = e.sensors._retry_at
        assert delays == [1, 2, 4, 8, 16, 32, 60, 60, 60, 60]
        assert len(conn.calls) == 10
        # the same error is logged once, not every minute
        assert len([r for r in caplog.records if "cannot connect" in r.getMessage()]) == 1

    def test_missing_local_forward_is_retried_soon(self, env):
        # Connection refused on 127.0.0.1 = adb's forward is missing (being
        # re-created after the phone re-enumerated): cheap, short cap.
        e = env()
        fake = FakeConn(e.clock, frames=5, fail_after=True)
        conn = Connector([ConnectionRefusedError("refused")] * 6 + [fake])
        e.sensors._connect = conn
        e.bus.publish("net.car_phone", car_phone_payload())
        delays = []
        for _ in range(6):
            e.sensors.cycle()
            delays.append(round(e.sensors._retry_at - e.clock.t, 3))
            e.clock.t = e.sensors._retry_at
        assert delays == [1, 2, 3, 3, 3, 3]
        assert all(d <= ps.FORWARD_MISSING_RETRY_S for d in delays)
        e.sensors.cycle()
        assert fake.calls and len(conn.calls) == 7

    def test_forward_back_resets_the_backoff(self, env):
        e = env()
        conn = Connector([ConnectionClosed("handshake")] * 5 + [FakeConn(e.clock, frames=3)])
        e.sensors._connect = conn
        e.bus.publish("net.car_phone", car_phone_payload())
        for i in range(5):
            e.sensors.cycle()
            if i < 4:
                e.clock.t = e.sensors._retry_at
        assert e.sensors.cycle() > 0            # the 6th attempt is still 16 s away
        assert len(conn.calls) == 5 and e.sensors._retry_at - e.clock.t == pytest.approx(16.0)
        e.bus.publish("net.car_phone", car_phone_payload(ok=False))   # phone re-enumerated
        assert e.sensors.cycle() == ps.WAIT_FORWARD_S
        e.bus.publish("net.car_phone", car_phone_payload(ok=True))    # forward re-created
        e.sensors.cycle()
        assert len(conn.calls) == 6                             # at once, not after 32 s
        assert e.sensors._delay <= 2.0

    def test_streaming_stale_then_reconnect(self, env):
        e = env()
        fake = FakeConn(e.clock, frames=200)
        e.sensors._connect = Connector([fake])
        e.bus.publish("net.car_phone", car_phone_payload())
        e.sensors.cycle()
        states = [s["state"] for s in e.topic("phone_sensors.state")]
        changes = [s for i, s in enumerate(states) if i == 0 or states[i - 1] != s]
        assert changes == ["connecting", "streaming", "stale", "error"]
        assert states[-1] == "error" and "no accelerometer data" in e.sensors.state["error"]
        assert fake.closed
        assert any(s["rate_hz"] >= 90 for s in e.topic("phone_sensors.state")
                   if s["state"] == "streaming")
        assert e.topic("phone.g_force")

    def test_closed_by_the_phone_is_an_error_with_backoff(self, env):
        e = env()
        e.sensors._connect = Connector([FakeConn(e.clock, frames=10, fail_after=True)])
        e.bus.publish("net.car_phone", car_phone_payload())
        e.sensors.cycle()
        assert e.sensors.state["state"] == "error"
        assert "closed by the phone" in e.sensors.state["error"]
        assert e.sensors._retry_at > e.clock.t

    def test_backoff_resets_after_a_long_session(self, env):
        e = env()
        e.sensors._delay = 32.0
        e.sensors._connect = Connector([FakeConn(e.clock, frames=3200, fail_after=True)])
        e.bus.publish("net.car_phone", car_phone_payload())
        e.sensors.cycle()
        assert e.sensors._retry_at - e.clock.t == pytest.approx(1.0)
        e2 = env()
        e2.sensors._delay = 32.0
        e2.sensors._fwd_seen = (951, True)      # the same forward as before
        e2.sensors._connect = Connector([FakeConn(e2.clock, frames=500, fail_after=True)])
        e2.bus.publish("net.car_phone", car_phone_payload())
        e2.sensors.cycle()
        assert e2.sensors._retry_at - e2.clock.t == pytest.approx(32.0)

    @pytest.mark.parametrize("gone", [car_phone_payload(state="disabled"),
                                      car_phone_payload(local=961),
                                      {"state": "connected", "forwards": {}}])
    def test_forward_gone_closes_without_backoff(self, env, gone):
        e = env()

        def drop_forward(conn):
            if conn.calls == 150:
                e.bus.publish("net.car_phone", gone)

        fake = FakeConn(e.clock, frames=10_000, on_receive=drop_forward)
        e.sensors._connect = Connector([fake])
        e.bus.publish("net.car_phone", car_phone_payload())
        e.sensors.cycle()
        assert fake.closed and e.sensors.state["state"] == "waiting_forward"
        assert e.sensors._retry_at == 0.0

    def test_forward_briefly_not_ok_keeps_a_working_stream(self, env):
        # One failed `adb devices` in car_phone (and its backoff) reports the
        # forward as not ok; a stream that keeps delivering is not dropped.
        e = env()

        def flap(conn):
            if conn.calls == 150:
                e.bus.publish("net.car_phone", car_phone_payload(ok=False, state="adb_error"))

        fake = FakeConn(e.clock, frames=1200, fail_after=True, on_receive=flap)
        e.sensors._connect = Connector([fake])
        e.bus.publish("net.car_phone", car_phone_payload())
        e.sensors.cycle()
        assert fake.left == 0                    # every frame was read
        assert e.sensors.stats["accel"] == 1200
        assert "closed by the phone" in e.sensors.state["error"]

    def test_waiting_forward_says_why(self, env):
        e = env()
        e.sensors.cycle()
        assert e.sensors.state["error"] == "car_phone is not running"
        e.bus.publish("net.car_phone", {"state": "connected", "forwards": {}})
        e.sensors.cycle()
        assert "modules.phone_sensors must be on in the config" in e.sensors.state["error"]
        clash = car_phone_payload(ok=False)
        clash["forwards"]["sensors"]["error"] = "sensors_local_port=5002 is already taken"
        e.bus.publish("net.car_phone", clash)
        e.sensors.cycle()
        assert e.sensors.state["state"] == "waiting_forward"
        assert "already taken" in e.sensors.state["error"]

    def test_light_alone_does_not_keep_the_session(self, env):
        # The accelerometer listener stopped but light frames still come:
        # reconnect after 10 s instead of staying "stale" for ever.
        e = env()
        n = {"i": 0}

        class LightOnly(FakeConn):
            def receive(self, timeout):
                n["i"] += 1
                self.clock.advance(0.1)
                if n["i"] > 400:
                    raise AssertionError("never reconnected")
                return light_frame(50.0)

        fake = LightOnly(e.clock)
        e.sensors._connect = Connector([fake])
        e.bus.publish("net.car_phone", car_phone_payload())
        e.sensors.cycle()
        assert fake.closed and "no accelerometer data" in e.sensors.state["error"]
        assert n["i"] <= 105

    def test_gyroscope_refused_is_dropped_from_the_request(self, env, caplog):
        e = env()
        refused = FakeConn(e.clock)
        refused.receive = lambda timeout: (_ for _ in ()).throw(ConnectionClosed(
            "closed by the phone (code 4002: Sensor of type android.sensor.gyroscope not "
            "supported)", code=4002))
        conn = Connector([refused, FakeConn(e.clock, frames=3, fail_after=True)])
        e.sensors._connect = conn
        e.bus.publish("net.car_phone", car_phone_payload())
        with caplog.at_level(logging.WARNING, logger="bcm.sensors.phone"):
            e.sensors.cycle()
            e.clock.t = e.sensors._retry_at
            e.sensors.cycle()
        assert [c[2] for c in conn.calls] == [ps.CONNECT_TARGET, ps.CONNECT_TARGET_NO_GYRO]
        assert any("without the gyroscope" in r.getMessage() for r in caplog.records)

    def test_normal_close_keeps_the_gyroscope(self, env):
        e = env()
        conn = Connector([FakeConn(e.clock, frames=0, fail_after=True),
                          FakeConn(e.clock, frames=0, fail_after=True)])
        e.sensors._connect = conn
        e.bus.publish("net.car_phone", car_phone_payload())
        e.sensors.cycle()
        e.clock.t = e.sensors._retry_at
        e.sensors.cycle()
        assert [c[2] for c in conn.calls] == [ps.CONNECT_TARGET, ps.CONNECT_TARGET]

    def test_state_payload(self, env):
        e = env()
        e.sensors.cycle()
        state = e.topic("phone_sensors.state")[-1]
        assert set(state) == {"state", "rate_hz", "calib_ok", "error", "since"}
        assert state["state"] in ps.STATES


# ── the WebSocket client against a real local server ──────────────────────

class WsServer:
    """One-connection wsproto server on 127.0.0.1:0 in a thread."""

    def __init__(self, mode="stream", messages=(), hold_s=0.5):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.mode = mode
        self.messages = list(messages)
        self.hold_s = hold_s
        self.target = None
        self.got_pong = threading.Event()
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        c, _ = self.sock.accept()
        c.settimeout(5)
        try:
            if self.mode == "eof":
                c.recv(4096)                    # read the request, then a clean EOF
                return
            if self.mode == "silent":
                time.sleep(self.hold_s)
                return
            ws = WSConnection(ConnectionType.SERVER)
            while self.target is None:
                ws.receive_data(c.recv(4096))
                for ev in ws.events():
                    if isinstance(ev, Request):
                        self.target = ev.target
            if self.mode == "reject":
                c.sendall(ws.send(RejectConnection(status_code=404)))
                return
            out = ws.send(AcceptConnection())
            for m in self.messages:
                out += ws.send(m)
            c.sendall(out)
            if self.mode == "ping":
                c.sendall(ws.send(Ping(b"hi")))
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline and not self.got_pong.is_set():
                    data = c.recv(4096)
                    if not data:
                        break
                    ws.receive_data(data)
                    if any(isinstance(ev, Pong) for ev in ws.events()):
                        self.got_pong.set()
            time.sleep(self.hold_s)
            c.sendall(ws.send(CloseConnection(code=1000)))
            time.sleep(0.1)
        except OSError:
            pass
        finally:
            c.close()
            self.sock.close()


def recv_all(client, n=20, timeout=0.5):
    out = []
    try:
        for _ in range(n):
            out.append(client.receive(timeout))
    except ConnectionClosed as e:
        out.append(e)
    return out


class TestWsClient:
    def test_messages_oversize_and_binary(self):
        good = accel_frame([0, 0, 9.8], 1)
        srv = WsServer(messages=[TextMessage(good), TextMessage("x" * 5000),
                                 BytesMessage(b"\x00\x01"), TextMessage(good)], hold_s=0.2)
        client = WsClient.open("127.0.0.1", srv.port, ps.CONNECT_TARGET, 2.0)
        got = recv_all(client)
        assert srv.target == ps.CONNECT_TARGET
        assert got[:2] == [good, good]
        assert client.oversize == 1 and client.binary == 1
        assert isinstance(got[-1], ConnectionClosed) and "1000" in str(got[-1])
        client.close()

    def test_fragmented_message_is_joined(self):
        srv = WsServer(messages=[TextMessage('{"type": "android.sensor.light", ',
                                             message_finished=False),
                                 TextMessage('"values": [5]}')], hold_s=0.1)
        client = WsClient.open("127.0.0.1", srv.port, ps.CONNECT_TARGET, 2.0)
        assert parse_frame(client.receive(1.0))[0] == ("android.sensor.light", (5.0,), None)
        client.close()

    def test_ping_is_answered(self):
        srv = WsServer(mode="ping", hold_s=0.1)
        client = WsClient.open("127.0.0.1", srv.port, ps.CONNECT_TARGET, 2.0)
        deadline = time.monotonic() + 3
        while not srv.got_pong.is_set() and time.monotonic() < deadline:
            try:
                client.receive(0.1)
            except ConnectionClosed:
                break
        assert srv.got_pong.is_set()
        client.close()

    def test_handshake_timeout(self):
        srv = WsServer(mode="silent", hold_s=2.0)
        t0 = time.monotonic()
        with pytest.raises((TimeoutError, socket.timeout)):
            WsClient.open("127.0.0.1", srv.port, ps.CONNECT_TARGET, 0.3)
        assert time.monotonic() - t0 < 1.5

    def test_eof_during_handshake(self):
        srv = WsServer(mode="eof")
        with pytest.raises(ConnectionClosed, match="handshake"):
            WsClient.open("127.0.0.1", srv.port, ps.CONNECT_TARGET, 2.0)

    def test_rejected(self):
        srv = WsServer(mode="reject")
        with pytest.raises(ConnectionClosed, match="404"):
            WsClient.open("127.0.0.1", srv.port, ps.CONNECT_TARGET, 2.0)

    def test_nothing_listening(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        with pytest.raises(OSError):
            WsClient.open("127.0.0.1", port, ps.CONNECT_TARGET, 1.0)


# ── lifecycle and registration ────────────────────────────────────────────

class TestLifecycle:
    def test_thread_end_to_end_with_a_real_socket(self, tmp_path):
        frames = [TextMessage(accel_frame([0.0, 0.0, G0], 10**9 + i * 10**7))
                  for i in range(150)]
        srv = WsServer(messages=frames, hold_s=1.5)
        bus = EventBus()
        seen = []
        bus.subscribe("*", lambda t, v, ts: seen.append((t, v)))
        bus.publish("net.car_phone", car_phone_payload(local=srv.port))
        sensors = PhoneSensors({}, bus, state_path=str(tmp_path / "s.json"))
        t0 = time.monotonic()
        sensors.start()
        assert time.monotonic() - t0 < 0.5                     # no I/O in start()
        deadline = time.monotonic() + 5
        while not any(t == "phone.g_force" for t, _ in seen) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert any(t == "phone.g_force" for t, _ in seen)
        assert any(t == "phone_sensors.state" and v["state"] == "streaming" for t, v in seen)
        bus.publish("power.shutting_down", True)
        sensors._thread.join(timeout=5)
        assert not sensors._thread.is_alive()
        last = [i for i, (t, _) in enumerate(seen) if t == "phone_sensors.state"][-1]
        assert seen[last][1]["state"] == "disabled"
        assert not any(t.startswith("phone.") for t, _ in seen[last:])   # nothing after it
        assert not any(t.startswith("alarm.") for t, _ in seen)

    def test_stop_publishes_disabled_and_no_more(self, env):
        e = env()
        e.sensors.stop()
        assert e.topic("phone_sensors.state")[-1]["state"] == "disabled"
        n = len(e.seen)
        e.sensors.cycle()
        assert len(e.seen) == n


class TestRegistration:
    def test_catalog_entry(self):
        info = modules_catalog.MODULES["phone_sensors"]
        assert info["entry"] == ("src.sensors.phone_sensors", "start_phone_sensors")
        assert info["requires"] == ("car_phone",) and info["default"] is False
        assert not info.get("planned")

    @pytest.mark.parametrize("cfg_name", ["bcm_config.yaml", "bcm_config_test.yaml"])
    def test_off_in_both_configs_and_never_started(self, cfg_name, monkeypatch):
        # Every entry point is a recorder: nothing real is started.
        called = []
        registry = {name: dict(info, start=lambda _n=name, **kw: called.append(_n))
                    for name, info in main.MODULE_REGISTRY.items()}
        monkeypatch.setattr(main, "MODULE_REGISTRY", registry)
        cfg = BCMConfig(config_path=str(REPO / "config" / cfg_name), platform_override="x86",
                        local_path=None, env={})
        assert modules_catalog.is_enabled(cfg, "phone_sensors") is False
        main.start_modules(main.registry_to_start(main.plan_modules(cfg)), cfg, EventBus(), None)
        assert called and "phone_sensors" not in called

    def test_needs_car_phone(self):
        cfg = BCMConfig(config_path=str(REPO / "config" / "bcm_config.yaml"),
                        platform_override="x86", local_path=None, env={})
        cfg.set("modules.phone_sensors", True)
        assert main.plan_modules(cfg)["phone_sensors"].runs is False
        cfg.set("modules.car_phone", True)
        assert main.plan_modules(cfg)["phone_sensors"].runs is True

    def test_test_config_blocks_are_read(self):
        cfg = BCMConfig(config_path=str(REPO / "config" / "bcm_config_test.yaml"),
                        platform_override="x86", local_path=None, env={})
        sensors = PhoneSensors(cfg, EventBus(), state_path="/nonexistent/state.json")
        assert sensors.accel_range_g == 8.0
        assert sensors.crash_cfg == CrashConfig()

    @pytest.mark.parametrize("config, warns", [
        ({}, False),
        ({"sensors": {"phone": {"accel_range_g": 4}}}, True),
        ({"crash_detection": {"dv_window_ms": 50}}, True),
        ({"crash_detection": {"dv_window_ms": 50}, "sensors": {"phone": {"accel_range_g": 16}}},
         False),
    ])
    def test_unreachable_thresholds_are_named(self, config, warns, caplog):
        with caplog.at_level(logging.WARNING, logger="bcm.sensors.phone"):
            PhoneSensors(config, EventBus(), state_path="/nonexistent/state.json")
        assert any("can never trigger" in r.getMessage() for r in caplog.records) is warns

    @pytest.mark.parametrize("value, want", [(16, 16.0), (100, 32.0), (1, 2.0), ("8", 8.0),
                                             (True, 8.0)])
    def test_accel_range_validated(self, value, want):
        sensors = PhoneSensors({"sensors": {"phone": {"accel_range_g": value}}}, EventBus(),
                               state_path="/nonexistent/state.json")
        assert sensors.accel_range_g == want
