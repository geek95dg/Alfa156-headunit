"""Crash detection (src/safety/crash_detect.py, plan F "Detekcja").

Two kinds of tests:

* physics, end to end: :mod:`tests.sensor_sim` plays a car and the phone
  under its headliner — SensorServer frames → PhoneSensors → phone.g_force
  → CrashDetector on the in-process bus, GPS at 1 Hz — on one FakeClock;
* rules, with hand-made ``phone.g_force`` messages, so each rejection
  reason is pinned on its own.

Records go to ``tmp_path``; the record writer is driven with
``run_pending_io()`` except in the one lifecycle test that starts the worker.
"""

import json
import logging
import math
import os
import stat
import time
from pathlib import Path

import pytest

import main
from src.core import modules_catalog
from src.core.config import BCMConfig
from src.core.event_bus import EventBus
from src.safety import crash_detect as cd
from src.safety.crash_detect import CrashDetector, load_crash_config, parse_g_force
from src.sensors.phone_sensors import PhoneSensors
from tests.sensor_sim import G0, MOUNT, ON_FLOOR, WALL_OFFSET, Drive, FakeClock, _mul, _rot_x

REPO = Path(__file__).resolve().parent.parent

EVENT_KEYS = {"event_id", "ts", "source", "sms_eligible", "lat", "lon", "fix_age_s", "sats",
              "speed_before_kmh", "dv_kmh", "peak_g", "heading"}


class Ids:
    def __init__(self):
        self.n = 0

    def __call__(self):
        self.n += 1
        return f"{self.n:032x}"


@pytest.fixture
def world(tmp_path):
    """Bus + clock + detector (+ the sensor module for the physics tests)."""
    def make(config=None, rate_hz=100.0, with_sensors=True, **drive_kw):
        clock = FakeClock()
        bus = EventBus()
        seen = []
        bus.subscribe("*", lambda t, v, ts: seen.append((t, v)))
        det = CrashDetector(config or {}, bus, clock=clock.mono, wall_clock=clock.wall,
                            events_dir=str(tmp_path / "crash_events"), id_factory=Ids())
        det.subscribe()
        sensors = drive = None
        if with_sensors:
            sensors = PhoneSensors(config or {}, bus, clock=clock.mono, wall_clock=clock.wall,
                                   state_path=str(tmp_path / "phone_sensors.json"))
            drive = Drive(sensors, bus, clock, rate_hz=rate_hz, **drive_kw)
        w = type("World", (), {})()
        w.clock, w.bus, w.det, w.sensors, w.drive, w.seen = clock, bus, det, sensors, drive, seen
        w.events = lambda: [v for t, v in seen if t == cd.TOPIC_DETECTED]
        w.outcomes = lambda: [v for t, v in seen if t == cd.TOPIC_OUTCOME]
        w.dir = tmp_path / "crash_events"
        return w

    yield make


def no_alarm_topics(w):
    """The car alarm reads ANY alarm.sensor.* value as a break-in."""
    topics = {t for t, _ in w.seen}
    assert not any(t.startswith("alarm.") for t in topics), topics


def calibrated_cruise(w, kmh=50.0, cruise_s=5.0):
    w.drive.rest(12.0)
    assert w.sensors.calib.calib_ok
    w.drive.cruise(kmh, cruise_s)


# ── physics, end to end ───────────────────────────────────────────────────

class TestPhysics:
    def test_50_kmh_barrier_impact_is_an_sms_eligible_event(self, world):
        w = world()
        calibrated_cruise(w)
        w.drive.barrier(50.0)
        w.drive.speed = 0.0
        w.drive.hold(3.0, noise=0.05)
        events = w.events()
        assert len(events) == 1
        ev = events[0]
        assert set(ev) == EVENT_KEYS
        assert ev["source"] == "accel" and ev["sms_eligible"] is True
        assert ev["dv_kmh"] >= 15 and ev["peak_g"] >= 4
        assert ev["speed_before_kmh"] == 50.0
        assert (ev["lat"], ev["lon"], ev["sats"], ev["heading"]) == (52.22968, 21.01223, 9, 90.0)
        assert 0 <= ev["fix_age_s"] <= 1.0
        assert ("dvr.protect_segment", True) in w.seen
        assert w.outcomes()[0]["outcome"] == "stopped"
        no_alarm_topics(w)

    @pytest.mark.parametrize("kmh, vertical", [(50, -0.45), (70, -0.45), (90, -0.45),
                                               (70, -0.60), (70, 0.45)])
    def test_severe_impact_with_a_vertical_part_still_fires(self, world, kmh, vertical):
        # 8 g range: the impact saturates both axes; with a downward vertical
        # part the clipped vertical peak (gravity's offset on that axis)
        # exceeds the clipped horizontal one. Still a crash.
        w = world()
        calibrated_cruise(w, kmh=float(kmh))
        a = (kmh / 3.6) * math.pi / (2 * 0.1)
        w.drive.pulse((-a, 0.0, vertical * a), 0.1)
        w.drive.speed = 0.0
        w.drive.hold(3.0, noise=0.05)
        events = w.events()
        assert [(e["source"], e["sms_eligible"]) for e in events] == [("accel", True)]
        assert not w.det.stats.get("rejected_vertical")

    def test_barrier_after_a_spin_out_with_the_gyroscope(self, world):
        # Yaw of 1.5 rad/s before the impact is no "tumbling phone".
        w = world(gyro=True)
        calibrated_cruise(w, kmh=60.0)
        w.drive.omega = (0.0, 0.0, 1.5)
        w.drive.hold(1.0, noise=0.6)
        w.drive.barrier(60.0)
        w.drive.omega = (0.0, 0.0, 0.0)
        w.drive.speed = 0.0
        w.drive.hold(3.0, noise=0.05)
        assert [e["source"] for e in w.events()] == ["accel"]

    def test_barrier_with_the_gyroscope(self, world):
        w = world(gyro=True)
        calibrated_cruise(w)
        w.drive.barrier(50.0)
        w.drive.speed = 0.0
        w.drive.hold(3.0, noise=0.05)
        assert [e["sms_eligible"] for e in w.events()] == [True]

    def test_tumbling_dropped_phone_is_not_a_crash(self, world):
        # Falls 0.45 s out of the holder spinning (reads a constant 0.5 g of
        # its own spin, never ~0 g), lands on its edge turned by 90° and is
        # stopped over 80 ms (3.7 m/s, ~0.7 m from the headliner). Without
        # the gyroscope this looked like a horizontal impact.
        w = world(gyro=True)
        calibrated_cruise(w)
        w.drive.tumbling_fall(0.45, reading_g=0.5, omega=10.0)
        w.drive.mount = _mul(_rot_x(90.0), MOUNT)
        a = 3.7 * math.pi / (2 * 0.08)
        w.drive.pulse((0.0, 0.0, a), 0.08)
        w.drive.cruise(50.0, 3.0)
        assert [e for e in w.events() if e["source"] == "accel"] == []
        g = [v for t, v in w.seen if t == "phone.g_force"]
        assert max(m["freefall_ms"] for m in g) >= 400

    def test_event_is_announced_on_the_dashboard(self, world):
        w = world()
        calibrated_cruise(w)
        w.drive.barrier(50.0)
        w.drive.speed = 0.0
        w.drive.hold(1.0, noise=0.05)
        notes = [v for t, v in w.seen if t == "system.notifications"]
        assert notes and notes[-1][-1]["key"] == "crash_detected"
        assert notes[-1][-1]["severity"] == "danger" and notes[-1][-1]["icon"] == "car_crash"
        assert "stłuczk" in notes[-1][-1]["title"]

    def test_one_g_braking_is_not_a_crash(self, world):
        w = world()
        calibrated_cruise(w, kmh=90.0)
        w.drive.brake(90.0, g=1.0)
        w.drive.hold(5.0, noise=0.05)
        assert w.events() == []                 # phone data valid: GPS path stays quiet
        no_alarm_topics(w)

    def test_pothole_is_not_a_crash(self, world):
        w = world()
        calibrated_cruise(w)
        w.drive.pulse((0.0, 0.0, 10 * G0), 0.04)
        w.drive.pulse((4 * G0, 0.0, -3 * G0), 0.03)
        w.drive.cruise(50.0, 3.0)
        assert w.events() == []

    def test_dropped_phone_is_not_a_crash(self, world):
        w = world()
        calibrated_cruise(w)
        w.drive.free_fall(0.35)
        w.drive.mount = ON_FLOOR
        w.drive.pulse((6 * G0, 0.0, 25 * G0), 0.03)
        w.drive.cruise(50.0, 3.0)
        assert w.events() == []
        g = [v for t, v in w.seen if t == "phone.g_force"]
        assert max(m["freefall_ms"] for m in g) >= 300

    def test_low_rate_stream_never_gives_an_accel_event(self, world):
        w = world(rate_hz=50.0)
        calibrated_cruise(w)
        w.drive.barrier(50.0)
        w.drive.speed = 0.0
        w.drive.hold(4.0, noise=0.05)
        assert w.det.stats.get("rejected_low_rate")
        sources = [e["source"] for e in w.events()]
        assert "accel" not in sources
        # ... the phone data is not valid, so the GPS-only path may log it
        assert all(e["sms_eligible"] is False for e in w.events())

    def test_uncalibrated_phone_never_gives_an_accel_event(self, world):
        w = world()
        w.drive.cruise(50.0, 8.0)               # straight onto the road: no quiet second
        assert not w.sensors.calib.calib_ok
        w.drive.barrier(50.0)
        w.drive.speed = 0.0
        w.drive.hold(4.0, noise=0.05)
        assert w.det.stats.get("rejected_uncalibrated")
        assert all(e["source"] == "gps" and not e["sms_eligible"] for e in w.events())

    def test_below_25_kmh_nothing(self, world):
        # E.g. rear-ended while creeping in a jam: the phone sees a real
        # impact, but the plan promises nothing below 25 km/h.
        w = world()
        calibrated_cruise(w, kmh=20.0)
        w.drive.barrier(50.0)
        w.drive.speed = 0.0
        w.drive.hold(3.0, noise=0.05)
        assert w.events() == []
        assert w.det.stats.get("rejected_slow")


# ── the rules, with hand-made messages ────────────────────────────────────

def g_msg(clock, **kw):
    msg = {"ts": clock.wall(), "mono": clock.mono(), "rate_hz": 100.0, "sat": False,
           "peak_h_g": 6.0, "peak_v_g": 2.0, "dv_h_kmh_150ms": 20.0, "dv_window_ms": 150,
           "n_over_g": 4, "freefall_ms": 0, "calib_ok": True}
    msg.update(kw)
    return msg


def drive_at(w, kmh, seconds=3, hz=1.0):
    for _ in range(int(seconds * hz)):
        w.clock.advance(1.0 / hz)
        w.bus.publish("gps.position", {"lat": 50.06, "lon": 19.94, "speed": kmh,
                                       "heading": 180.0, "satellites": 7, "fix": True})
        w.bus.publish("gps.speed", kmh)


def quiet_phone(w):
    """A valid, calm phone.g_force (keeps the GPS-only path off)."""
    w.bus.publish("phone.g_force", g_msg(w.clock, peak_h_g=0.1, peak_v_g=0.05,
                                         dv_h_kmh_150ms=0.2, n_over_g=0))


class TestRules:
    def test_impact_signature_fires(self, world):
        w = world(with_sensors=False)
        drive_at(w, 60.0)
        w.bus.publish("phone.g_force", g_msg(w.clock))
        assert [e["source"] for e in w.events()] == ["accel"]

    @pytest.mark.parametrize("override, reason", [
        ({"peak_v_g": 7.0}, "vertical"),
        ({"freefall_ms": 120}, "free_fall"),
        ({"calib_ok": False}, "uncalibrated"),
        ({"rate_hz": 60.0}, "low_rate"),
        ({"overrun": True}, "overrun"),
        ({"lag_ms": 1500}, "stale"),
    ])
    def test_rejections(self, world, override, reason):
        w = world(with_sensors=False)
        drive_at(w, 60.0)
        w.bus.publish("phone.g_force", g_msg(w.clock, **override))
        assert w.events() == []
        assert w.det.stats.get(f"rejected_{reason}") == 1

    def test_saturated_vertical_peak_does_not_reject(self, world):
        # 8 g range: the horizontal axis clips near 7.4 g, the vertical one
        # (with gravity's offset) reads up to ~9 g — clipped peaks say
        # nothing about which axis dominates.
        w = world(with_sensors=False)
        drive_at(w, 70.0)
        w.bus.publish("phone.g_force", g_msg(w.clock, peak_h_g=7.4, peak_v_g=8.8, sat=True))
        assert [e["source"] for e in w.events()] == ["accel"]
        w2 = world(with_sensors=False)
        drive_at(w2, 70.0)
        w2.bus.publish("phone.g_force", g_msg(w2.clock, peak_h_g=7.4, peak_v_g=8.8, sat=False))
        assert w2.events() == [] and w2.det.stats.get("rejected_vertical") == 1

    def test_a_vertical_rejection_consumes_its_messages(self, world):
        # The same pothole must not "fire" 0.4 s later from what is left in
        # the 0.35 s combine window once the vertical message has aged out.
        w = world(with_sensors=False)
        drive_at(w, 60.0)
        w.bus.publish("phone.g_force", g_msg(w.clock, peak_v_g=7.0, peak_h_g=3.0,
                                             n_over_g=0, dv_h_kmh_150ms=5.0))
        w.clock.advance(0.1)
        w.bus.publish("phone.g_force", g_msg(w.clock, peak_h_g=6.0, peak_v_g=2.0))
        assert w.det.stats.get("rejected_vertical") == 1
        for _ in range(3):
            w.clock.advance(0.1)
            quiet_phone(w)
        assert w.events() == []

    def test_late_samples_switch_the_gps_path_on(self, world):
        w = world(with_sensors=False)
        drive_at(w, 60.0)
        w.bus.publish("phone.g_force", g_msg(w.clock, peak_h_g=0.1, peak_v_g=0.05,
                                             dv_h_kmh_150ms=0.2, n_over_g=0, lag_ms=2500))
        assert not w.det.phone_data_ok()
        quiet_phone(w)
        assert w.det.phone_data_ok()

    def test_stale_data_is_rejected(self, world):
        w = world(with_sensors=False)
        drive_at(w, 60.0)
        w.bus.publish("phone.g_force", g_msg(w.clock, mono=w.clock.mono() - 1.5))
        assert w.events() == [] and w.det.stats.get("rejected_stale") == 1

    def test_stale_by_wall_clock_without_mono(self, world):
        w = world(with_sensors=False)
        drive_at(w, 60.0)
        msg = g_msg(w.clock, ts=w.clock.wall() - 5)
        del msg["mono"]
        w.bus.publish("phone.g_force", msg)
        assert w.events() == [] and w.det.stats.get("rejected_stale") == 1

    def test_below_min_speed(self, world):
        w = world(with_sensors=False)
        drive_at(w, 22.0)
        w.bus.publish("phone.g_force", g_msg(w.clock))
        assert w.events() == [] and w.det.stats.get("rejected_slow") == 1

    def test_no_gps_speed_at_all_is_recorded_but_never_sms(self, world):
        # Tunnel / underground car park: the impact is real, the speed gate
        # cannot be checked — log, record, DVR, never an SMS.
        w = world(with_sensors=False)
        w.bus.publish("phone.g_force", g_msg(w.clock))
        events = w.events()
        assert len(events) == 1
        ev = events[0]
        assert ev["source"] == "accel" and ev["sms_eligible"] is False
        assert ev["speed_before_kmh"] is None
        assert ("dvr.protect_segment", True) in w.seen
        w.det.run_pending_io()
        rec = json.loads(next(w.dir.iterdir()).read_text())
        assert rec["details"]["reason"] == "no_gps_speed"
        assert w.det.stats.get("event_accel_no_speed") == 1

    def test_highest_speed_of_the_last_10_s_counts(self, world):
        w = world(with_sensors=False)
        drive_at(w, 40.0, seconds=2)
        drive_at(w, 18.0, seconds=5)            # braked hard before the impact
        w.bus.publish("phone.g_force", g_msg(w.clock))
        assert len(w.events()) == 1
        assert w.events()[0]["speed_before_kmh"] == 18.0       # the newest sample
        w2 = world(with_sensors=False)
        drive_at(w2, 40.0, seconds=2)
        drive_at(w2, 18.0, seconds=11)          # the 40 km/h is 11 s old now
        w2.bus.publish("phone.g_force", g_msg(w2.clock))
        assert w2.events() == []

    @pytest.mark.parametrize("override", [
        {"dv_h_kmh_150ms": 12.0}, {"peak_h_g": 3.5}, {"n_over_g": 2}])
    def test_each_threshold_is_needed(self, world, override):
        w = world(with_sensors=False)
        drive_at(w, 60.0)
        w.bus.publish("phone.g_force", g_msg(w.clock, **override))
        assert w.events() == [] and not any(k.startswith("rejected") for k in w.det.stats)

    def test_signature_straddling_two_messages(self, world):
        w = world(with_sensors=False)
        drive_at(w, 60.0)
        w.bus.publish("phone.g_force", g_msg(w.clock, n_over_g=2, dv_h_kmh_150ms=11.0))
        w.clock.advance(0.1)
        w.bus.publish("phone.g_force", g_msg(w.clock, n_over_g=3, peak_h_g=4.5,
                                             dv_h_kmh_150ms=16.0))
        assert len(w.events()) == 1

    @pytest.mark.parametrize("bad", [
        None, [], "x", {"rate_hz": float("nan")},
        {"rate_hz": 100, "peak_h_g": 5, "peak_v_g": 1, "dv_h_kmh_150ms": 20,
         "n_over_g": True, "freefall_ms": 0},
        {"rate_hz": 100, "peak_h_g": float("inf"), "peak_v_g": 1, "dv_h_kmh_150ms": 20,
         "n_over_g": 4, "freefall_ms": 0},
        {"rate_hz": "100", "peak_h_g": 5, "peak_v_g": 1, "dv_h_kmh_150ms": 20,
         "n_over_g": 4, "freefall_ms": 0},
    ])
    def test_invalid_messages_are_counted_not_used(self, world, bad):
        w = world(with_sensors=False)
        drive_at(w, 60.0)
        assert parse_g_force(bad) is None
        w.bus.publish("phone.g_force", bad)
        assert w.events() == [] and w.det.stats.get("invalid_g_force") == 1

    def test_garbage_gps_input_is_ignored(self, world):
        w = world(with_sensors=False)
        for bad in (None, "60", True, float("nan"), -5, 1e9):
            w.bus.publish("gps.speed", bad)
        w.bus.publish("gps.position", {"lat": 95.0, "lon": 10.0})
        w.bus.publish("gps.position", "x")
        assert w.det.stats.get("invalid_speed") == 6
        w.bus.publish("phone.g_force", g_msg(w.clock))
        assert [e["sms_eligible"] for e in w.events()] == [False]      # no valid speed

    def test_speed_before_is_from_before_the_impact(self, world):
        # A GPS sample that already shows the impact (0 km/h) arrives just
        # before the g_force message: it is not "the speed before".
        w = world(with_sensors=False)
        drive_at(w, 60.0)
        w.clock.advance(0.1)
        w.bus.publish("gps.speed", 0.0)
        w.bus.publish("phone.g_force", g_msg(w.clock))
        assert w.events()[0]["speed_before_kmh"] == 60.0

    def test_position_is_the_last_known_with_its_age(self, world):
        w = world(with_sensors=False)
        drive_at(w, 60.0)
        w.clock.advance(25.0)                   # GPS lost before the impact
        w.bus.publish("gps.speed", 60.0)        # (speed from another source)
        w.bus.publish("phone.g_force", g_msg(w.clock))
        ev = w.events()[0]
        assert (ev["lat"], ev["lon"]) == (50.06, 19.94)
        assert ev["fix_age_s"] == 25.0 and ev["heading"] is None     # course too old

    def test_no_position_ever(self, world):
        w = world(with_sensors=False)
        for _ in range(3):
            w.clock.advance(1.0)
            w.bus.publish("gps.speed", 60.0)
        w.bus.publish("phone.g_force", g_msg(w.clock))
        ev = w.events()[0]
        assert ev["lat"] is None and ev["lon"] is None and ev["fix_age_s"] is None


class TestGpsOnly:
    def test_drop_over_two_seconds_is_a_gps_event_never_sms(self, world):
        w = world(with_sensors=False)
        drive_at(w, 60.0, seconds=4)
        for v in (55.0, 10.0, 0.0, 0.0):        # impact between the 2nd and 3rd sample
            drive_at(w, v, seconds=1)
        events = w.events()
        assert len(events) == 1
        ev = events[0]
        assert ev["source"] == "gps" and ev["sms_eligible"] is False and ev["peak_g"] is None
        assert ev["dv_kmh"] >= 45 and ev["speed_before_kmh"] >= 55
        assert ("dvr.protect_segment", True) in w.seen
        no_alarm_topics(w)

    def test_one_sample_glitch_is_not_an_event(self, world):
        w = world(with_sensors=False)
        drive_at(w, 60.0, seconds=4)
        for v in (60.0, 0.0, 60.0, 60.0, 60.0):
            drive_at(w, v, seconds=1)
        assert w.events() == []

    def test_gentle_stop_is_not_an_event(self, world):
        w = world(with_sensors=False)
        drive_at(w, 50.0, seconds=4)
        for v in (42.0, 34.0, 26.0, 18.0, 10.0, 2.0, 0.0, 0.0):     # ~0.23 g
            drive_at(w, v, seconds=1)
        assert w.events() == []

    def test_valid_phone_data_switches_the_gps_path_off(self, world):
        w = world(with_sensors=False)
        drive_at(w, 60.0, seconds=4)
        for v in (55.0, 10.0, 0.0, 0.0):
            quiet_phone(w)
            drive_at(w, v, seconds=1)
            quiet_phone(w)
        assert w.events() == []
        assert w.det.phone_data_ok()

    def test_stalled_dispatcher_does_not_compress_a_drop(self, world):
        # Normal hard braking, 50 -> 0 km/h over 4 s (0.35 g), but the bus
        # dispatcher delivered the samples late and bunched (0.5 s apart).
        # Dated by their publish time it is still 4 s — no event.
        w = world(with_sensors=False)
        drive_at(w, 50.0, seconds=4)
        t0 = w.clock.t
        for i, v in enumerate((50.0, 37.5, 25.0, 12.5, 0.0, 0.0)):
            published = t0 + 1 + i
            w.clock.t = max(t0 + 3.0 + 0.5 * i, published)
            w.det._on_speed("gps.speed", v, published + WALL_OFFSET)
        assert w.events() == []

    def test_slow_car_no_gps_event(self, world):
        w = world(with_sensors=False)
        drive_at(w, 20.0, seconds=4)
        for v in (0.0, 0.0, 0.0):
            drive_at(w, v, seconds=1)
        assert w.events() == []


class TestCooldownAndOutcome:
    def test_at_most_one_event_per_60_s(self, world):
        w = world(with_sensors=False)
        drive_at(w, 60.0)
        w.bus.publish("phone.g_force", g_msg(w.clock))
        w.clock.advance(30)
        drive_at(w, 60.0)
        w.bus.publish("phone.g_force", g_msg(w.clock))
        assert len(w.events()) == 1 and w.det.stats.get("cooldown") == 1
        w.clock.advance(30)
        drive_at(w, 60.0)
        w.bus.publish("phone.g_force", g_msg(w.clock))
        assert len(w.events()) == 2
        # the first one's outcome was still open (GPS samples 30 s apart do
        # not make "10 s sustained"): it is closed first, each event gets one
        assert w.outcomes() == [{"event_id": w.events()[0]["event_id"],
                                 "outcome": "unconfirmed", "reason": "superseded",
                                 "ts": w.outcomes()[0]["ts"]}]

    def test_sms_eligible_event_supersedes_a_gps_only_one(self, world):
        w = world(with_sensors=False)
        drive_at(w, 60.0, seconds=4)
        for v in (55.0, 10.0, 8.0, 8.0):        # GPS-only event (no phone data yet),
            drive_at(w, v, seconds=1)           # still rolling: its outcome is open
        assert [e["source"] for e in w.events()] == ["gps"] and w.outcomes() == []
        drive_at(w, 40.0, seconds=5)            # the phone stream is back, 20 s later:
        w.bus.publish("phone.g_force", g_msg(w.clock))         # the real impact
        events = w.events()
        assert [(e["source"], e["sms_eligible"]) for e in events] == [("gps", False),
                                                                     ("accel", True)]
        assert [(o["event_id"], o["outcome"], o["reason"]) for o in w.outcomes()] == [
            (events[0]["event_id"], "unconfirmed", "superseded")]
        w.clock.advance(5)
        drive_at(w, 60.0)
        w.bus.publish("phone.g_force", g_msg(w.clock))         # after an SMS one: cooldown
        assert len(w.events()) == 2 and w.det.stats.get("cooldown") == 1

    def test_stopped(self, world):
        w = world(with_sensors=False)
        drive_at(w, 60.0)
        w.bus.publish("phone.g_force", g_msg(w.clock))
        drive_at(w, 30.0, seconds=1)
        drive_at(w, 4.0, seconds=1)
        out = w.outcomes()
        assert [o["outcome"] for o in out] == ["stopped"]
        assert out[0]["event_id"] == w.events()[0]["event_id"]

    def test_driving_on_for_10_s_cancels(self, world):
        w = world(with_sensors=False)
        drive_at(w, 60.0)
        w.bus.publish("phone.g_force", g_msg(w.clock))
        drive_at(w, 55.0, seconds=9)
        assert w.outcomes() == []
        drive_at(w, 55.0, seconds=2)
        assert [(o["outcome"], o["reason"]) for o in w.outcomes()] == [("cancelled", "no_stop")]

    def test_gps_gap_never_cancels_and_times_out_unconfirmed(self, world):
        w = world(with_sensors=False)
        drive_at(w, 60.0)
        w.bus.publish("phone.g_force", g_msg(w.clock))
        drive_at(w, 55.0, seconds=5)
        w.clock.advance(4.0)                    # GPS lost for 4 s
        drive_at(w, 55.0, seconds=6)
        assert w.outcomes() == []               # the 10 s started again after the gap
        w.clock.advance(cd.OUTCOME_WATCH_S)
        w.det.tick()
        assert [(o["outcome"], o["reason"]) for o in w.outcomes()] == [
            ("unconfirmed", "timeout")]

    def test_slow_rolling_neither_cancels_nor_confirms(self, world):
        w = world(with_sensors=False)
        drive_at(w, 60.0)
        w.bus.publish("phone.g_force", g_msg(w.clock))
        drive_at(w, 15.0, seconds=30)
        assert w.outcomes() == []


class TestRecords:
    def test_written_atomically_and_updated_with_the_outcome(self, world):
        w = world(with_sensors=False)
        drive_at(w, 60.0)
        w.bus.publish("phone.g_force", g_msg(w.clock))
        assert not w.dir.exists()               # nothing written on the bus thread
        assert w.det.run_pending_io() == 1
        files = sorted(os.listdir(w.dir))
        assert len(files) == 1 and cd._RECORD_RE.fullmatch(files[0])
        path = w.dir / files[0]
        assert stat.S_IMODE(path.stat().st_mode) == 0o600      # a position inside
        rec = json.loads(path.read_text())
        assert rec["version"] == 1 and rec["outcome"] == "pending"
        assert rec["event"] == w.events()[0]
        assert rec["details"]["calib_ok"] is True
        drive_at(w, 0.0, seconds=1)
        w.det.run_pending_io()
        assert sorted(os.listdir(w.dir)) == files               # same file, rewritten
        assert json.loads(path.read_text())["outcome"] == "stopped"

    def test_retention_keeps_the_newest_50(self, world):
        w = world(with_sensors=False)
        w.dir.mkdir()
        for i in range(55):
            (w.dir / f"crash_20250101_0000{i:02d}_{i:08x}.json").write_text("{}")
        (w.dir / "notes.txt").write_text("mine")
        drive_at(w, 60.0)
        w.bus.publish("phone.g_force", g_msg(w.clock))
        w.det.run_pending_io()
        names = sorted(os.listdir(w.dir))
        records = [n for n in names if n.startswith("crash_")]
        assert len(records) == cd.MAX_RECORDS and "notes.txt" in names
        assert "crash_20250101_000000_00000000.json" not in names    # the oldest went
        assert any(n.startswith("crash_2026") for n in records)      # the new one stays

    def test_retention_never_removes_the_new_record(self, world):
        # Wrong system clock (RTC reset before bcm-timesync): the new record
        # gets an older name than the 55 already there.
        w = world(with_sensors=False)
        w.dir.mkdir()
        for i in range(55):
            (w.dir / f"crash_20270101_0000{i:02d}_{i:08x}.json").write_text("{}")
        drive_at(w, 60.0)
        w.bus.publish("phone.g_force", g_msg(w.clock))
        w.det.run_pending_io()
        new = [n for n in os.listdir(w.dir) if n.startswith("crash_2026")]
        assert len(new) == 1
        drive_at(w, 0.0, seconds=1)                            # outcome: rewritten, kept
        w.det.run_pending_io()
        assert (w.dir / new[0]).exists()
        assert json.loads((w.dir / new[0]).read_text())["outcome"] == "stopped"

    def test_unwritable_directory_is_logged_not_raised(self, world, tmp_path, caplog):
        w = world(with_sensors=False)
        w.det._dir = tmp_path / "file"
        (tmp_path / "file").write_text("not a directory")
        drive_at(w, 60.0)
        w.bus.publish("phone.g_force", g_msg(w.clock))
        with caplog.at_level(logging.ERROR, logger="bcm.safety.crash_detect"):
            w.det.run_pending_io()
        assert any("not written" in r.getMessage() for r in caplog.records)


# ── configuration ─────────────────────────────────────────────────────────

class TestConfig:
    def test_code_defaults(self):
        c = load_crash_config({})
        assert (c.min_speed_kmh, c.dv_threshold_kmh, c.dv_window_ms, c.g_h_threshold,
                c.min_rate_hz, c.confirm_stop_kmh) == (25, 15, 150, 4.0, 80, 5)

    def test_clamped_and_invalid(self, caplog):
        with caplog.at_level(logging.WARNING):
            c = load_crash_config({"crash_detection": {
                "min_speed_kmh": 1, "dv_threshold_kmh": "15", "dv_window_ms": 5000,
                "g_h_threshold": True, "min_rate_hz": float("nan"), "confirm_stop_kmh": 3}})
        assert c.min_speed_kmh == 10 and c.dv_threshold_kmh == 15 and c.dv_window_ms == 300
        assert c.g_h_threshold == 4.0 and c.min_rate_hz == 80 and c.confirm_stop_kmh == 3
        assert len([r for r in caplog.records if "crash_detection." in r.getMessage()]) == 5

    def test_legacy_keys_are_named_once(self, caplog):
        with caplog.at_level(logging.INFO, logger="bcm.safety.crash_detect"):
            CrashDetector({"crash_detection": {"speed_drop_threshold": 30,
                                               "g_force_threshold": 3.0}}, EventBus())
        msgs = [r.getMessage() for r in caplog.records if "no longer read" in r.getMessage()]
        assert len(msgs) == 1 and "speed_drop_threshold/g_force_threshold" in msgs[0]

    @pytest.mark.parametrize("cfg_name", ["bcm_config.yaml", "bcm_config_test.yaml"])
    def test_shipped_configs_use_the_new_keys(self, cfg_name):
        cfg = BCMConfig(config_path=str(REPO / "config" / cfg_name), platform_override="x86",
                        local_path=None, env={})
        assert cd.legacy_keys_present(cfg) == []
        assert load_crash_config(cfg) == cd.CrashConfig()


# ── lifecycle and registration ────────────────────────────────────────────

class TestLifecycle:
    def test_worker_writes_records_and_stops(self, tmp_path):
        bus = EventBus()
        det = CrashDetector({}, bus, events_dir=str(tmp_path / "ev"))
        det.start()
        try:
            for _ in range(3):
                bus.publish("gps.speed", 60.0)
            bus.publish("phone.g_force", {"mono": time.monotonic(),
                                          "rate_hz": 100.0, "peak_h_g": 6.0, "peak_v_g": 1.0,
                                          "dv_h_kmh_150ms": 20.0, "n_over_g": 4,
                                          "freefall_ms": 0, "calib_ok": True})
            deadline = time.monotonic() + 5
            while not (tmp_path / "ev").exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            assert len(os.listdir(tmp_path / "ev")) == 1
        finally:
            bus.publish("power.shutting_down", True)
        det._thread.join(timeout=5)
        assert not det._thread.is_alive()

    def test_camera_wrapper_is_the_same_code(self):
        from src.camera import crash_detect as old
        assert old.start_crash_detect is cd.start_crash_detect
        assert old.CrashDetector is cd.CrashDetector

    def test_old_alarm_topics_are_not_listened_to(self, world):
        w = world(with_sensors=False)
        drive_at(w, 60.0)
        w.bus.publish("alarm.sensor.tilt", 9.0)
        assert w.events() == []


class TestRegistration:
    def test_catalog_entry(self):
        info = modules_catalog.MODULES["crash_detect"]
        assert info["entry"] == ("src.safety.crash_detect", "start_crash_detect")
        assert info["requires"] == ("location",) and info["default"] is False

    def test_production_off_test_config_on(self):
        prod = BCMConfig(config_path=str(REPO / "config" / "bcm_config.yaml"),
                         platform_override="x86", local_path=None, env={})
        test = BCMConfig(config_path=str(REPO / "config" / "bcm_config_test.yaml"),
                         platform_override="x86", local_path=None, env={})
        assert modules_catalog.is_enabled(prod, "crash_detect") is False
        assert main.plan_modules(prod)["crash_detect"].runs is False
        # GPS-only path works without new hardware (plan F: on in the test config)
        assert main.plan_modules(test)["crash_detect"].runs is True

    @pytest.mark.parametrize("cfg_name, started", [("bcm_config.yaml", False),
                                                   ("bcm_config_test.yaml", True)])
    def test_entry_point_called_only_when_on(self, monkeypatch, cfg_name, started):
        # Every entry point is a recorder: nothing real is started.
        called = []
        registry = {name: dict(info, start=lambda _n=name, **kw: called.append(_n))
                    for name, info in main.MODULE_REGISTRY.items()}
        monkeypatch.setattr(main, "MODULE_REGISTRY", registry)
        cfg = BCMConfig(config_path=str(REPO / "config" / cfg_name),
                        platform_override="x86", local_path=None, env={})
        main.start_modules(main.registry_to_start(main.plan_modules(cfg)), cfg, EventBus(), None)
        assert called and ("crash_detect" in called) is started
        assert "phone_sensors" not in called

    def test_without_location_it_is_not_started(self):
        cfg = BCMConfig(config_path=str(REPO / "config" / "bcm_config_test.yaml"),
                        platform_override="x86", local_path=None, env={})
        cfg.set("modules.location", False)
        st = main.plan_modules(cfg)["crash_detect"]
        assert st.runs is False and st.blocked_by == (("location",),)
