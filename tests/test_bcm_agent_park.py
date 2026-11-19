"""Alarm na postoju (plan D4) in the Termux agent
(tools/car_phone/termux/bcm_agent.py, :class:`ParkGuard`).

No Termux here: every phone command goes through a fake runner that refuses
anything unexpected, the accelerometer stream is a fake process whose lines
advance a fake clock, state lives in tmp_path. Nothing can send a real SMS.

Covers: arming after USB power loss + no BCM contact (and not while BCM
talks), the exit window, the home geofence, power restored alone never
disarming (alarm after the grace), the signed BCM disarm (an unsigned one is
refused), TOTP (RFC 6238 vectors, expired, replayed — also after a restart),
SMS commands from whitelisted vs unknown numbers, dedupe, old messages,
reply limits, the termux-sensor stream parser with garbage and restarts,
tilt / shaking vs noise, log_only never sending, alarm SMS GSM-7 + limits +
priority behind the crash SMS, the light mode and the low-battery disarm,
the location fallback (and skipping GPS for a while after it failed),
persistence, the config hash compatibility and the CLI (--park-setup,
--park-numbers), the entry window, TOTP codes checked against the SMS's
receipt time, stopping the sensor stream (process group, reader generation,
termux-sensor -c after every stop) and no arming while the car moves. Real
processes are never started: Popen and os.killpg are replaced where the
process-group handling is checked.
"""

from __future__ import annotations

import calendar
import importlib.util
import io
import json
import logging
import math
import os
import queue
import random
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
AGENT_PATH = REPO / "tools" / "car_phone" / "termux" / "bcm_agent.py"


def _load():
    old = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location("bcm_agent_park_under_test", AGENT_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = old
    return mod


A = _load()

SECRET = "5e" * 32
KEY = bytes.fromhex(SECRET)
CODE = "0123456789"
T0 = 1_763_000_000.0
OWNER, OWNER2, STRANGER = "+48601234567", "+48601234568", "+48700000001"
ACCEL = "lsm6dso Accelerometer"
#: The test TOTP secret (RFC 6238 Appendix B: ASCII "12345678901234567890").
RFC_KEY = b"12345678901234567890"
B32 = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
HOME = {"lat": 52.2297, "lon": 21.0122, "radius_m": 150}
FIX_HOME = {"latitude": 52.22975, "longitude": 21.01225, "accuracy": 12.0,
            "elapsedMs": 4000, "provider": "gps"}
FIX_AWAY = {"latitude": 50.06143, "longitude": 19.93658, "accuracy": 8.0,
            "elapsedMs": 2000, "provider": "gps"}

#: GSM 03.38 basic character set, written out independently of the agent's.
GSM7 = set("@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
           "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà")


class Clock:
    def __init__(self):
        self.boot = 1000.0
        self.wall = T0

    def advance(self, s):
        self.boot += s
        self.wall += s


def localtime_str(wall):
    """termux-sms-list "received" for a wall time (the tests' localtime is
    UTC: the agent gets time.gmtime / calendar.timegm)."""
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(wall))


class Runner:
    """Termux:API stand-in for the parking guard; refuses anything unexpected."""

    def __init__(self, clock):
        self.clock = clock
        self.calls = []
        self.battery = {"percentage": 80, "temperature": 30.0, "plugged": "PLUGGED_USB",
                        "status": "CHARGING"}
        self.inbox = []
        self.fixes = {("gps", "once"): FIX_AWAY}
        self.sensors = ["Light", f"{ACCEL} Uncalibrated", ACCEL, "Linear Acceleration"]
        self.burst = ""
        self.sms = []                    # (number, text) handed to termux-sms-send
        self.inbox_ok = True
        self.operator = "26001"          # "" = no network (the SMS waits for signal)
        self.on_location = None          # called on every termux-location (time passes)

    def __call__(self, argv, stdin, timeout):
        assert isinstance(argv, list) and all(isinstance(a, str) for a in argv), argv
        assert 0 < timeout <= 120
        self.calls.append(list(argv))
        prog = argv[0]
        if prog == "termux-battery-status":
            return 0, json.dumps(self.battery), ""
        if prog == "termux-sms-list" and argv[1:3] == ["-t", "inbox"]:
            assert argv[3:] == ["-l", "10"], argv
            if not self.inbox_ok:
                return 1, "", "Error: READ_SMS"
            return 0, json.dumps(self.inbox), ""
        if prog == "termux-sms-list" and argv[1:3] == ["-t", "all"]:
            return 0, json.dumps([{"type": "sent", "number": n, "body": b}
                                  for n, b in self.sms]), ""
        if prog == "termux-sms-send":
            assert argv[1] == "-n" and A.E164_RE.fullmatch(argv[2]), argv
            assert argv[2] in (OWNER, OWNER2, "+48601234569"), argv     # only listed numbers
            self.sms.append((argv[2], stdin))
            return 0, "", ""
        if prog == "termux-telephony-deviceinfo":
            return 0, json.dumps({"sim_state": "ready", "network_operator": self.operator}), ""
        if prog == "termux-location":
            assert argv[1] == "-p" and argv[3] == "-r", argv
            if self.on_location is not None:
                self.on_location(argv)
            fix = self.fixes.get((argv[2], argv[4]))
            if fix == "timeout":
                return A.RC_TIMEOUT, "", "timed out"
            return 0, json.dumps(fix) if fix else "", ""
        if prog == "termux-sensor":
            if argv[1:] == ["-l"]:
                return 0, json.dumps({"sensors": self.sensors}), ""
            if argv[1:] == ["-c"]:
                return 0, "", ""
            assert argv[1] == "-s" and argv[2] == ACCEL and argv[3:5] == ["-d", "100"], argv
            assert argv[5:] == ["-n", "10"], argv
            if self.burst == "timeout":
                return A.RC_TIMEOUT, "", "termux-sensor timed out"
            return 0, self.burst, ""
        raise AssertionError(f"unexpected command {argv}")

    def progs(self, name):
        return [c for c in self.calls if c[0] == name]

    def sms_texts(self):
        return [t for _n, t in self.sms]


class FakeProc:
    """A termux-sensor stream: each line advances the fake clock (``dt``
    per JSON object), then EOF (the process ends)."""

    def __init__(self, argv, lines, clock, dt=0.1):
        self.argv = argv
        self._lines = lines
        self._clock = clock
        self._dt = dt
        self.terminated = False
        self.finished = False

    @property
    def stdout(self):
        def gen():
            for line in self._lines:
                if self.terminated:
                    break
                if line.startswith("}") or (line.startswith("{") and line.rstrip().endswith("}")):
                    self._clock.advance(self._dt)
                yield line
            self.finished = True
        return gen()

    def poll(self):
        return 0 if (self.finished or self.terminated) else None

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0


class Spawner:
    def __init__(self, clock):
        self.clock = clock
        self.procs = []
        self.next_lines = []
        self.fail = False

    def __call__(self, argv):
        assert argv == ["termux-sensor", "-s", ACCEL, "-d", "100"], argv
        if self.fail:
            raise OSError("no termux-sensor")
        proc = FakeProc(argv, list(self.next_lines), self.clock)
        self.next_lines = []
        self.procs.append(proc)
        return proc


def obj_lines(vec, name=ACCEL, indent=True):
    text = json.dumps({name: {"values": list(vec)}}, indent=2 if indent else None)
    return [line + "\n" for line in text.splitlines()]


def quiet(n, noise=0.01, g=(0.0, 0.0, 9.81), seed=1):
    rnd = random.Random(seed)
    return [(g[0] + rnd.gauss(0, noise), g[1] + rnd.gauss(0, noise), g[2] + rnd.gauss(0, noise))
            for _ in range(n)]


def tilted(n, deg, noise=0.01, seed=2):
    r = math.radians(deg)
    return quiet(n, noise, (9.81 * math.sin(r), 0.0, 9.81 * math.cos(r)), seed)


def stream(vectors):
    out = []
    for v in vectors:
        out += obj_lines(v)
    return out


# ── fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def runner(clock):
    return Runner(clock)


@pytest.fixture
def spawn(clock):
    return Spawner(clock)


def make_agent(state_dir, runner, clock, spawn):
    return A.Agent(state_dir, runner=runner, clock=lambda: clock.boot,
                   wall=lambda: clock.wall, localtime=time.gmtime, spawn=spawn,
                   mktime=calendar.timegm)


class Peer:
    """BCM in miniature: signs, keeps a nonce."""

    def __init__(self, agent, clock, nonce=100):
        self.agent, self.clock, self.nonce = agent, clock, nonce

    def req(self, method, path, obj=None, sign=True):
        body = b"" if obj is None else json.dumps(obj).encode()
        self.nonce += 1
        ts = int(self.clock.wall)
        sig = A.sign(KEY, A.request_message(method, path, ts, self.nonce, body)) if sign \
            else "0" * 64
        status, data, _h = self.agent.handle(method, path, {
            "X-BCM-Ts": str(ts), "X-BCM-Nonce": str(self.nonce), "X-BCM-Sig": sig}, body)
        return status, json.loads(data)


def park_config(**park):
    cfg = {"recipients": [OWNER], "sim_slot": 0, "vehicle_label": "ALFA 156",
           "toggles": {"crash_sms": True, "parking_guard": True, "cabin_watch": False,
                       "call112": False},
           "dry_run": False, "follow_up_cancel": True,
           "park_numbers": [OWNER, OWNER2], "park_log_only": False,
           "park_arm_after_min": 3, "park_arm_delay_min": 2, "park_grace_min": 3,
           "park_home": None, "park_tilt_deg": 0.5, "park_shake_k": 6.0}
    cfg.update(park)
    return cfg


class Env:
    def __init__(self, tmp_path, clock, runner, spawn, totp=True, **park):
        self.dir = str(tmp_path / "bcm_agent")
        self.clock, self.runner, self.spawn = clock, runner, spawn
        self.agent = make_agent(self.dir, runner, clock, spawn)
        Path(self.dir, "PAIRING").write_text(CODE + "\n")
        body = json.dumps({"secret": SECRET}).encode()
        ts = int(clock.wall)
        sig = A.sign(CODE.encode(), A.request_message("POST", "/v1/pair", ts, 50, body))
        status, _d, _h = self.agent.handle("POST", "/v1/pair", {
            "X-BCM-Ts": str(ts), "X-BCM-Nonce": "50", "X-BCM-Sig": sig}, body)
        assert status == 200
        self.peer = Peer(self.agent, clock)
        status, out = self.peer.req("PUT", "/v1/config", park_config(**park))
        assert status == 200, out
        if totp:
            Path(self.dir, A.TOTP_FILE).write_text(B32 + "\n")
        self.guard = self.agent.park
        # SMS commands must be newer than the agent's start.
        clock.advance(60)

    def step(self, n=1):
        for _ in range(n):
            self.guard.step()
            if self.guard._reader is not None:
                self.guard._reader.join(timeout=5)

    def send(self, n=30):
        for _ in range(n):
            if self.agent.step() > 0:
                break

    def view(self):
        return self.guard.view()

    def unplug(self):
        self.runner.battery = dict(self.runner.battery, plugged="UNPLUGGED", status="DISCHARGING")
        self.guard._kick = True

    def plug(self):
        self.runner.battery = dict(self.runner.battery, plugged="PLUGGED_USB", status="CHARGING")
        self.guard._kick = True

    def arm_by_power(self):
        """Engine off: power cut, BCM gone; 3 min no contact + 2 min exit
        window."""
        self.step()
        self.unplug()
        self.step()
        self.clock.advance(181)
        self.step()
        assert self.view()["state"] == "arming", self.view()
        self.clock.advance(121)
        self.step()

    def code(self, offset=0):
        return A.totp_code(RFC_KEY, int(self.clock.wall // 30) + offset)

    def sms_in(self, body, number=OWNER, age=5, mid=None):
        mid = len(self.runner.inbox) + 1 if mid is None else mid
        self.runner.inbox.insert(0, {"threadid": 1, "type": "inbox", "read": False,
                                     "number": number, "received":
                                     localtime_str(self.clock.wall - age),
                                     "body": body, "_id": mid})
        self.guard._inbox_at = None


@pytest.fixture
def env(tmp_path, clock, runner, spawn):
    return Env(tmp_path, clock, runner, spawn)


# ── TOTP (RFC 6238) ──────────────────────────────────────────────────────

class TestTotp:
    @pytest.mark.parametrize("when,code8", [(59, "94287082"), (1111111109, "07081804"),
                                            (1234567890, "89005924"),
                                            (2000000000, "69279037")])
    def test_rfc_6238_vectors(self, when, code8):
        assert A.totp_code(RFC_KEY, when // 30, digits=8) == code8
        assert A.totp_code(RFC_KEY, when // 30) == code8[-6:]

    def test_secret_round_trip(self):
        assert A.parse_totp_secret(B32) == RFC_KEY
        assert A.parse_totp_secret(B32.lower()) == RFC_KEY
        new = A.new_totp_secret()
        assert len(A.parse_totp_secret(new)) == A.TOTP_SECRET_BYTES
        for bad in ("", "not base32!", "A" * 8, None, 123):
            assert A.parse_totp_secret(bad) is None

    def test_window_expired_and_replay(self):
        now = 1_763_000_000
        step = now // 30
        for off in (-1, 0, 1):
            assert A.totp_verify(RFC_KEY, A.totp_code(RFC_KEY, step + off), now, None) == \
                ("ok", step + off)
        assert A.totp_verify(RFC_KEY, A.totp_code(RFC_KEY, step - 2), now, None) == ("bad", None)
        assert A.totp_verify(RFC_KEY, A.totp_code(RFC_KEY, step + 2), now, None) == ("bad", None)
        code = A.totp_code(RFC_KEY, step)
        assert A.totp_verify(RFC_KEY, code, now, step) == ("replay", step)
        # a newer step used => an older code is refused too
        assert A.totp_verify(RFC_KEY, A.totp_code(RFC_KEY, step - 1), now, step)[0] == "replay"
        for bad in ("12345", "1234567", "abcdef", None, 123456):
            assert A.totp_verify(RFC_KEY, bad, now, None) == ("bad", None)

    def test_otpauth_uri(self):
        uri = A.otpauth_uri(B32)
        assert uri.startswith("otpauth://totp/") and f"secret={B32}" in uri
        assert "algorithm=SHA1" in uri and "digits=6" in uri and "period=30" in uri


# ── pure helpers ─────────────────────────────────────────────────────────

class TestHelpers:
    def test_power_of(self):
        assert A.power_of({"plugged": "UNPLUGGED"}) == "unplugged"
        assert A.power_of({"plugged": "PLUGGED_USB"}) == "plugged"
        assert A.power_of({"plugged": "PLUGGED_AC"}) == "plugged"
        # status alone never decides (a charge limiter reports DISCHARGING on the cable)
        assert A.power_of({"plugged": None, "status": "DISCHARGING"}) is None
        assert A.power_of(None) is None

    @pytest.mark.parametrize("body,want", [
        ("POZYCJA 123456", ("position", "123456")), ("gdzie 123 456", ("position", "123456")),
        (" park on 000001 ", ("on", "000001")), ("Park Off\n654321", ("off", "654321")),
        ("PARK STATUS 111111", ("status", "111111")),
        ("PARK OFF", None), ("PARK OFF 12345", None), ("PARK OFF 1234567", None),
        ("POZYCJA 123456; rm -rf /", None), ("hej", None), ("x" * 100, None), (None, None)])
    def test_commands(self, body, want):
        assert A.parse_park_command(body) == want

    def test_sender_match(self):
        nums = [OWNER, "+447700900123"]
        assert A.match_sender(OWNER, nums) == OWNER
        assert A.match_sender("0048601234567", nums) == OWNER
        assert A.match_sender("601 234 567", nums) == OWNER          # national form
        assert A.match_sender("+48601234560", nums) is None
        assert A.match_sender("+4860123456", nums) is None
        assert A.match_sender("Orange", nums) is None
        assert A.match_sender(None, nums) is None
        # a national number that fits two listed numbers is ambiguous
        assert A.match_sender("601234567", [OWNER, "+44601234567"]) is None

    def test_location_parsing(self):
        fix = A.parse_location(json.dumps(FIX_AWAY))
        assert fix == {"lat": 50.06143, "lon": 19.93658, "acc": 8, "age_s": 2,
                       "provider": "gps"}
        for bad in ("", "{}", "[]", "nope", json.dumps({"latitude": 91, "longitude": 0}),
                    json.dumps({"latitude": 0, "longitude": 0}),
                    json.dumps({"API_ERROR": "denied"})):
            assert A.parse_location(bad) is None

    def test_home(self):
        home_fix = A.parse_location(json.dumps(FIX_HOME))
        assert A.at_home(home_fix, HOME)
        assert not A.at_home(A.parse_location(json.dumps(FIX_AWAY)), HOME)
        assert not A.at_home(dict(home_fix, acc=900), HOME)       # too vague: arm
        assert not A.at_home(None, HOME)

    def test_pick_accelerometer(self):
        assert A.pick_accelerometer(["Light", f"{ACCEL} Uncalibrated", ACCEL]) == ACCEL
        assert A.pick_accelerometer(["BMI160 accel"]) == "BMI160 accel"
        assert A.pick_accelerometer(["Light", "Linear Acceleration"]) is None
        assert A.pick_accelerometer(["Bad,Accelerometer", "x;Accelerometer"]) is None
        assert A.pick_accelerometer(None) is None

    def test_texts_are_gsm7_and_short(self):
        fix = A.parse_location(json.dumps(FIX_AWAY))
        net = dict(fix, provider="network", age_s=600, acc=1500)
        label = "ALFA 156"
        texts = [A.park_alarm_text(label, r, T0, f, time.gmtime)
                 for r in ("tilt", "shake", "power") for f in (fix, net, None)]
        texts += [A.park_position_text(label, f) for f in (fix, net, None)]
        texts += [A.park_low_battery_text(label, 14)]
        texts += [A.park_ack_text(label, w, 2) for w in ("arming", "already", "off",
                                                         "low_battery", "bad")]
        view = {"state": "alarm", "since": T0, "battery": {"pct": 55},
                "last_event": {"kind": "power", "ts": T0}}
        texts.append(A.park_status_text(label, view, time.gmtime))
        for text in texts:
            assert set(text) <= GSM7, text
            assert A.sms_segments(text) <= 2, text
        power = A.park_alarm_text(label, "power", T0, fix, time.gmtime)
        assert "zasilanie wrocilo bez telefonu wlasciciela" in power
        assert power.startswith("ALFA 156: ALARM ") and "Pozycja: https://maps.google.com/" in power
        pos = A.park_position_text(label, fix)
        assert pos == ("ALFA 156: POZYCJA https://maps.google.com/?q=50.06143,19.93658 "
                       "(GPS sprzed 2 s, dokladnosc 8 m)")


# ── the accelerometer: parser and detector ───────────────────────────────

class TestSensorParser:
    def test_pretty_and_single_line_objects_with_garbage(self):
        p = A.SensorParser(ACCEL)
        lines = (["garbage\n", "}\n"] + obj_lines((0.1, 0.2, 9.8))
                 + ['{"' + ACCEL + '": {"values": [1, 2, 9]}}\n']
                 + ["{\n", '  "x": {\n'] + obj_lines((0.3, 0.1, 9.7))      # unfinished, then new
                 + obj_lines((float("nan"), 0, 9.8), indent=True)[:0]
                 + ["{\n", '  "' + ACCEL + '": {"values": ["a", 1, 2]}\n', "}\n"]
                 + ["x" * 5000 + "\n"]
                 + obj_lines((0.0, 0.0, 9.81)))
        out = []
        for line in lines:
            out += p.feed_line(line)
        assert out == [(0.1, 0.2, 9.8), (1.0, 2.0, 9.0), (0.3, 0.1, 9.7), (0.0, 0.0, 9.81)]
        assert p.garbage >= 4

    def test_exact_name_wins_over_partial_matches(self):
        obj = {f"{ACCEL} Uncalibrated": {"values": [5, 5, 5]}, ACCEL: {"values": [0, 0, 9.8]}}
        assert A.sensor_vectors(obj, ACCEL) == [(0.0, 0.0, 9.8)]
        assert A.sensor_vectors({}, ACCEL) == []
        assert A.sensor_vectors({"a": {"values": [1, 2]}}, ACCEL) == []

    def test_bounded(self):
        p = A.SensorParser(ACCEL)
        p.feed_line("{\n")
        for _ in range(500):
            assert p.feed_line('  "k": 1,\n') == []
        assert p._buf is None or len(p._buf) <= A.SENSOR_OBJ_MAX_LINES + 1


class TestDetector:
    def feed(self, det, vectors, t0=0.0, dt=0.1):
        events = []
        t = t0
        for v in vectors:
            ev = det.feed(t, *v)
            if ev:
                events.append((round(t, 1), ev[0]))
            t += dt
        return events, t

    def test_noise_alone_never_triggers(self):
        det = A.MotionDetector(0.5, 6.0)
        events, _t = self.feed(det, quiet(6000, noise=0.02))         # 10 min
        assert events == [] and det.calibrated

    def test_tilt_needs_3_s(self):
        det = A.MotionDetector(0.5, 6.0)
        events, t = self.feed(det, quiet(100))
        events, t = self.feed(det, tilted(20, 1.0), t)                # 2 s: no
        assert events == []
        events, t = self.feed(det, quiet(100), t)
        assert events == []
        events, t = self.feed(det, tilted(60, 1.0, seed=3), t)        # 6 s: yes
        assert [k for _t, k in events] == ["tilt"]

    def test_small_tilt_is_ignored(self):
        det = A.MotionDetector(0.5, 6.0)
        _e, t = self.feed(det, quiet(100))
        events, _t = self.feed(det, tilted(200, 0.2), t)
        assert events == []

    def test_slow_drift_follows_the_reference(self):
        det = A.MotionDetector(0.5, 6.0)
        _e, t = self.feed(det, quiet(100))
        # 1 degree over 4 hours (temperature, a tyre losing air): no alarm
        events = []
        for i in range(1, 241):
            ev, t = self.feed(det, tilted(10, i / 240.0, seed=i), t, dt=6.0)
            events += ev
        assert events == []

    def test_shaking_needs_half_a_second(self):
        det = A.MotionDetector(0.5, 6.0)
        _e, t = self.feed(det, quiet(100))
        spike = [(0.0, 0.0, 9.81)] * 3 + [(0.6, 0.6, 10.4)] + [(0.0, 0.0, 9.81)] * 30
        events, t = self.feed(det, spike, t)                             # one spike: no
        assert events == []
        rock = [(0.5 * math.sin(2 * math.pi * 2 * i / 10.0), 0.0, 9.81) for i in range(20)]
        events, t = self.feed(det, rock, t)                              # 2 s rocking: yes
        assert [k for _t, k in events] == ["shake"]

    def test_cooldown_and_garbage(self):
        det = A.MotionDetector(0.5, 6.0)
        _e, t = self.feed(det, quiet(100))
        rock = [(0.5 * math.sin(2 * math.pi * 2 * i / 10.0), 0.0, 9.81) for i in range(100)]
        events, t = self.feed(det, rock, t)                              # 10 s rocking
        assert [k for _t, k in events] == ["shake"]                      # once (30 s cooldown)
        assert det.feed(t, float("nan"), 0, 9.8) is None
        assert det.feed(t, 0, 0, 0.1) is None                            # free fall / garbage
        assert det.feed(t, 100, 0, 0) is None

    def test_burst_mode(self):
        det = A.MotionDetector(0.5, 6.0)
        assert det.feed_burst(0.0, quiet(10)) is None                    # reference
        assert det.feed_burst(20.0, quiet(10, seed=5)) is None
        assert det.feed_burst(40.0, tilted(10, 1.5)) is None             # first tilted burst
        assert det.feed_burst(60.0, tilted(10, 1.5, seed=7)) == ("tilt", pytest.approx(1.5, 0.1))
        # back to level is a change of position too (two bursts again)
        assert det.feed_burst(80.0, quiet(10, seed=8)) is None
        assert det.feed_burst(100.0, quiet(10, seed=9))[0] == "tilt"
        det = A.MotionDetector(0.5, 6.0)
        det.feed_burst(0.0, quiet(10))
        rock = [(0.6 * (1 if i % 2 else -1), 0.0, 9.81) for i in range(10)]
        ev = det.feed_burst(20.0, rock)
        assert ev is not None and ev[0] == "shake"
        spike = quiet(10, seed=10)
        spike[4] = (0.8, 0.0, 9.81)
        assert det.feed_burst(40.0, spike) is None                       # one sample: no


# ── arming and disarming ─────────────────────────────────────────────────

class TestArming:
    def test_power_loss_and_no_bcm_contact_arm_after_the_exit_window(self, env):
        env.step()
        assert env.view()["state"] == "disarmed"
        env.unplug()
        assert env.peer.req("GET", "/v1/health")[0] == 200       # BCM's last word
        env.step()
        env.clock.advance(120)
        env.step()
        assert env.view()["state"] == "disarmed"                 # only 2 min without BCM
        env.clock.advance(61)
        env.step()
        v = env.view()
        assert v["state"] == "arming" and v["by"] == "power"
        assert v["arm_at"] == int(env.clock.wall) + 120
        assert env.spawn.procs == []                              # no sensor while arming
        env.clock.advance(121)
        env.step()
        v = env.view()
        assert v["state"] == "armed" and v["by"] == "power"
        assert len(env.spawn.procs) == 1                          # the stream started

    def test_bcm_talking_keeps_it_disarmed(self, env):
        env.unplug()
        env.step()
        for _ in range(20):                                       # 10 min of BCM polls
            env.clock.advance(30)
            assert env.peer.req("GET", "/v1/health")[0] == 200
            env.step()
        assert env.view()["state"] == "disarmed"

    def test_power_back_in_the_exit_window_cancels_arming(self, env):
        env.step()
        env.unplug()
        env.step()
        env.clock.advance(181)
        env.step()
        assert env.view()["state"] == "arming"
        env.plug()
        env.step()
        v = env.view()
        assert v["state"] == "disarmed" and v["by"] == "power_back"

    def test_not_at_home(self, tmp_path, clock, runner, spawn):
        runner.fixes = {("gps", "once"): FIX_HOME}
        env = Env(tmp_path, clock, runner, spawn, park_home=HOME)
        env.step()
        env.unplug()
        env.step()
        env.clock.advance(181)
        env.step()
        env.clock.advance(121)
        env.step()
        v = env.view()
        assert v["state"] == "disarmed" and v["by"] == "home"
        assert v["last_event"]["kind"] == "home"
        assert len(runner.progs("termux-location")) == 1
        # no new attempt (and no GPS) until the car was driven again
        env.clock.advance(3600)
        env.step(3)
        assert env.view()["state"] == "disarmed" and len(runner.progs("termux-location")) == 1
        env.plug()
        env.step()
        env.unplug()
        env.step()                                    # BCM silent for an hour already
        assert env.view()["state"] == "arming"

    def test_away_from_home_or_no_fix_arms(self, tmp_path, clock, runner, spawn):
        runner.fixes = {("gps", "once"): None}
        env = Env(tmp_path, clock, runner, spawn, park_home=HOME)
        env.arm_by_power()
        assert env.view()["state"] == "armed"                    # no position: arm anyway

    def test_bcm_arm_and_validation(self, env):
        assert env.peer.req("POST", "/v1/park/arm", {"delay_min": 0})[1]["state"] == "arming"
        env.step()
        assert env.view()["state"] == "armed" and env.view()["by"] == "bcm"
        for bad in ({"delay_min": 31}, {"delay_min": -1}, {"delay_min": "1"},
                    {"delay_min": True}, {"x": 1}):
            assert env.peer.req("POST", "/v1/park/arm", bad)[0] == 400

    def test_off_toggle(self, env):
        env.peer.req("POST", "/v1/park/arm", {"delay_min": 0})
        env.step()
        cfg = park_config()
        cfg["toggles"]["parking_guard"] = False
        assert env.peer.req("PUT", "/v1/config", cfg)[0] == 200
        env.runner.calls.clear()
        env.step()
        v = env.view()
        assert v["state"] == "off" and env.guard.st["by"] == "off"
        assert [c[0] for c in env.runner.calls] == ["termux-sensor"]   # only the cleanup
        assert env.peer.req("POST", "/v1/park/arm", {})[0] == 409
        assert env.peer.req("POST", "/v1/park/disarm", {})[0] == 409
        env.runner.calls.clear()
        env.clock.advance(3600)
        env.step(5)
        assert env.runner.calls == []                             # off = zero Termux:API

    def test_toggle_off_from_the_start_never_calls_the_phone(self, tmp_path, clock, runner,
                                                             spawn):
        cfg_env = Env(tmp_path, clock, runner, spawn)
        cfg = park_config()
        cfg["toggles"]["parking_guard"] = False
        cfg_env.peer.req("PUT", "/v1/config", cfg)
        runner.calls.clear()
        cfg_env.sms_in("PARK OFF 123456")
        cfg_env.step(3)
        assert runner.calls == [] and spawn.procs == []


class TestDisarm:
    def test_power_restored_alone_does_not_disarm(self, env):
        env.arm_by_power()
        env.plug()
        env.step()
        v = env.view()
        assert v["state"] == "armed"
        env.clock.advance(179)
        env.step()
        assert env.view()["state"] == "armed" and env.runner.sms == []
        env.clock.advance(2)
        env.step()
        v = env.view()
        assert v["state"] == "alarm" and v["last_event"]["kind"] == "power"
        env.send()
        texts = env.runner.sms_texts()
        assert len(texts) == 2 and all("zasilanie wrocilo bez telefonu wlasciciela" in t
                                       for t in texts)
        assert {n for n, _t in env.runner.sms} == {OWNER, OWNER2}

    def test_bcm_talking_again_checks_the_power_at_once(self, env):
        env.arm_by_power()
        polls = len(env.runner.progs("termux-battery-status"))
        env.clock.advance(5)
        env.step()
        assert len(env.runner.progs("termux-battery-status")) == polls     # every 3 min
        env.plug()
        env.guard._kick = False
        assert env.peer.req("GET", "/v1/health")[0] == 200                  # BCM is back
        env.step()
        assert len(env.runner.progs("termux-battery-status")) == polls + 1
        assert env.guard.st["restored_wall"] is not None                    # grace runs
        assert env.view()["state"] == "armed"                               # not disarmed
        for method, path in (("POST", "/v1/park"), ("GET", "/v1/park/arm"),
                             ("GET", "/v1/park/disarm")):
            assert env.peer.req(method, path)[0] == 405

    def test_bcm_disarm_in_the_grace_and_unsigned_refused(self, env):
        env.arm_by_power()
        env.plug()
        env.step()
        status, out = env.peer.req("POST", "/v1/park/disarm", {}, sign=False)
        assert status == 401 and env.view()["state"] == "armed"
        status, out = env.peer.req("POST", "/v1/park/disarm", {})
        assert status == 200 and out["state"] == "disarmed" and out["by"] == "owner_bt"
        env.clock.advance(600)
        env.step()
        env.send()
        assert env.runner.sms == []
        assert env.spawn.procs[-1].terminated and ["termux-sensor", "-c"] in env.runner.calls

    def test_disarm_with_a_code_from_the_car_screen(self, env):
        env.arm_by_power()
        status, out = env.peer.req("POST", "/v1/park/disarm", {"code": "000000"})
        assert status == 403 and out["error"] == "bad_code" and env.view()["state"] == "armed"
        code = env.code()
        status, out = env.peer.req("POST", "/v1/park/disarm", {"code": code})
        assert status == 200 and out["by"] == "owner_code"
        env.peer.req("POST", "/v1/park/arm", {"delay_min": 0})
        env.step()
        status, out = env.peer.req("POST", "/v1/park/disarm", {"code": code})   # replay
        assert status == 403 and out["error"] == "code_used" and env.view()["state"] == "armed"
        for bad in ({"code": "12345"}, {"code": 123456}, {"pin": "123456"}):
            assert env.peer.req("POST", "/v1/park/disarm", bad)[0] == 400

    def test_disarm_from_far_away_does_not_re_arm_until_the_next_drive(self, env):
        env.arm_by_power()
        env.sms_in(f"PARK OFF {env.code()}")
        env.step()
        assert env.view()["state"] == "disarmed" and env.view()["by"] == "owner_sms"
        env.clock.advance(3600)
        env.step(3)
        assert env.view()["state"] == "disarmed"


# ── SMS commands ─────────────────────────────────────────────────────────

class TestSmsCommands:
    def test_position_from_a_listed_number(self, env):
        env.sms_in(f"pozycja {env.code()}")
        env.step()
        env.send()
        assert env.runner.sms == [(OWNER, "ALFA 156: POZYCJA https://maps.google.com/?q="
                                          "50.06143,19.93658 (GPS sprzed 2 s, dokladnosc 8 m)")]

    def test_unknown_sender_is_ignored_silently(self, env):
        env.sms_in(f"POZYCJA {env.code()}", number=STRANGER)
        env.sms_in(f"PARK OFF {env.code()}", number="ORANGE")
        env.step()
        env.send()
        assert env.runner.sms == [] and env.runner.progs("termux-location") == []
        assert env.guard.st["totp_last"] is None                 # the code was not used up

    def test_dedupe_and_old_messages(self, env):
        env.sms_in(f"PARK STATUS {env.code()}", mid=7)
        env.step()
        env.guard._inbox_at = None
        env.step()                                                # same _id again
        env.sms_in(f"PARK STATUS {env.code(1)}", age=700)        # older than 10 min
        env.step()
        env.send()
        assert len(env.runner.sms) == 1 and "POSTOJ rozbrojony" in env.runner.sms[0][1]

    def test_messages_from_before_the_agent_started_are_ignored(self, env):
        env.sms_in(f"PARK ON {env.code()}", age=-1)
        env.runner.inbox[0]["received"] = localtime_str(env.guard._start_wall - 30)
        env.step()
        assert env.view()["state"] == "disarmed"

    def test_wrong_and_replayed_codes(self, env):
        code = env.code()
        env.sms_in(f"PARK ON {code}")
        env.step()
        assert env.view()["state"] == "arming"
        env.clock.advance(150)
        env.sms_in(f"PARK OFF {code}")                           # same code again
        env.step()
        assert env.view()["state"] == "armed"
        env.send()
        assert env.runner.sms_texts()[-1] == "ALFA 156: POSTOJ zly albo zuzyty kod."

    def test_lockout_after_wrong_codes(self, env):
        for i in range(A.PARK_BAD_CODE_MAX):
            env.clock.advance(1)
            env.sms_in(f"PARK STATUS {i:06d}")
            env.step()
        env.clock.advance(1)
        env.sms_in(f"PARK STATUS {env.code()}")
        env.step()
        assert env.guard.st["totp_last"] is None                 # not even checked

    def test_reply_limits(self, env):
        env.sms_in(f"PARK STATUS {env.code(-1)}")
        env.step()
        env.clock.advance(31)
        env.sms_in(f"PARK STATUS {env.code()}")
        env.step()
        env.send()
        assert len(env.runner.sms) == 1                          # 1 per 2 min
        sent = 1
        for _ in range(15):
            env.clock.advance(121)
            env.sms_in(f"PARK STATUS {env.code()}")
            env.step()
        env.send(100)
        assert len(env.runner.sms) == A.PARK_REPLY_MAX_PER_DAY >= sent

    def test_park_on_then_off(self, env):
        env.sms_in(f"PARK ON {env.code()}")
        env.step()
        assert env.view()["state"] == "arming" and env.view()["by"] == "sms"
        env.clock.advance(121)
        env.step()
        assert env.view()["state"] == "armed"
        env.clock.advance(60)
        env.sms_in(f"PARK OFF {env.code()}")
        env.step()
        env.send()
        assert env.view()["state"] == "disarmed"
        assert env.runner.sms_texts() == ["ALFA 156: POSTOJ uzbrajanie za 2 min.",
                                          "ALFA 156: POSTOJ rozbrojony."]

    def test_no_totp_secret_means_no_inbox_polling(self, tmp_path, clock, runner, spawn,
                                                   caplog):
        env = Env(tmp_path, clock, runner, spawn, totp=False)
        env.sms_in("PARK OFF 123456")
        with caplog.at_level(logging.WARNING, logger="bcm_agent"):
            env.step(2)
        assert runner.progs("termux-sms-list") == []
        assert any("--park-setup" in r.getMessage() for r in caplog.records)

    def test_numbers_set_on_the_phone(self, tmp_path, clock, runner, spawn):
        env = Env(tmp_path, clock, runner, spawn, park_numbers=[])
        assert env.view()["numbers_n"] == 0
        assert A.write_park_numbers(env.dir, f"{OWNER2}", out=io.StringIO()) == 0
        assert env.view()["numbers_n"] == 1
        env.sms_in(f"PARK STATUS {env.code()}", number=OWNER2)
        env.sms_in(f"PARK STATUS {env.code()}", number=OWNER)     # not on the phone's list
        env.step()
        env.send()
        assert [n for n, _t in runner.sms] == [OWNER2]


# ── TOTP against the time the SMS was received ───────────────────────────

def _to_phase(env, phase):
    """Advance the clock to ``phase`` seconds into the current 30 s step."""
    env.clock.advance((phase - env.clock.wall % 30) % 30)


def _inbox_add(env, body, number=OWNER, mid=None, received=None):
    """An SMS lands in the inbox WITHOUT forcing a poll (sms_in() does) —
    the scheduled 30 s poll picks it up."""
    mid = 1000 + len(env.runner.inbox) if mid is None else mid
    env.runner.inbox.insert(0, {"type": "inbox", "number": number, "body": body, "_id": mid,
                                "received": localtime_str(env.clock.wall if received is None
                                                          else received)})


class TestCodeTime:
    def test_code_late_in_its_step_delivered_and_read_at_the_next_poll(self, env):
        _to_phase(env, 28)
        step = int(env.clock.wall // 30)
        code = env.code()                         # read 2 s before its step ends
        env.clock.advance(2)
        env.guard._inbox_at = None
        env.step()                                # a scheduled poll: inbox empty
        env.clock.advance(8)
        _inbox_add(env, f"PARK STATUS {code}")    # received 10 s after reading
        env.step()                                # not polled (30 s cadence)
        env.clock.advance(22)                     # polled 30 s after the last poll
        env.step()
        assert int(env.clock.wall // 30) - step == 2         # 2 steps by now
        assert env.guard.st["totp_last"] == step and env.guard.st["bad_codes"] == {}
        env.send()
        assert len(env.runner.sms) == 1 and "POSTOJ rozbrojony" in env.runner.sms[0][1]

    def test_park_off_received_while_a_gps_job_runs(self, env):
        env.arm_by_power()
        env.clock.advance(200)
        sent = {}

        def slow_gps(argv):
            if argv[2:5] == ["gps", "-r", "once"] and "off" not in sent:
                env.clock.advance(20)
                _to_phase(env, 28)
                sent["off"] = env.code()
                _inbox_add(env, f"PARK OFF {sent['off']}")
                env.clock.advance(50)             # GPS takes its time

        env.runner.on_location = slow_gps
        env.sms_in(f"POZYCJA {env.code()}")
        env.step()                                # POZYCJA: poll + GPS job (70 s)
        env.step()                                # the next poll: PARK OFF
        v = env.view()
        assert v["state"] == "disarmed" and v["by"] == "owner_sms"
        assert env.guard.st["bad_codes"] == {}
        env.send()
        texts = env.runner.sms_texts()
        # (the PARK OFF reply itself falls under the 1-per-2-min reply limit)
        assert len(texts) == 1 and "POZYCJA https://" in texts[0]
        # the same code again (another SMS) is a replay
        _inbox_add(env, f"PARK ON {sent['off']}")
        env.clock.advance(31)
        env.step()
        assert env.view()["state"] == "disarmed"
        assert len(env.guard.st["bad_codes"].get(OWNER, [])) == 1

    def test_a_code_two_steps_from_its_own_receipt_is_refused(self, env):
        _to_phase(env, 5)
        old = env.code(-2)
        _inbox_add(env, f"PARK STATUS {old}")
        env.guard._inbox_at = None
        env.step()
        assert env.guard.st["totp_last"] is None
        assert len(env.guard.st["bad_codes"][OWNER]) == 1

    def test_a_receipt_time_in_the_future_counts_as_now(self, env):
        _to_phase(env, 5)
        future = env.code(3)                      # valid 90 s from now
        _inbox_add(env, f"PARK STATUS {future}", received=env.clock.wall + 90)
        env.guard._inbox_at = None
        env.step()
        assert env.guard.st["totp_last"] is None             # checked against "now"

    def test_car_screen_code_while_disarmed_stays_used_after_a_restart(
            self, env, runner, clock, spawn):
        assert env.view()["state"] == "disarmed"
        code = env.code()
        status, out = env.peer.req("POST", "/v1/park/disarm", {"code": code})
        assert status == 200 and out["state"] == "disarmed"
        again = make_agent(env.dir, runner, clock, spawn)
        assert again.park.st["totp_last"] == int(clock.wall // 30)
        peer = Peer(again, clock, nonce=env.peer.nonce)
        assert peer.req("POST", "/v1/park/disarm", {"code": code})[1]["error"] == "code_used"


# ── alarms ───────────────────────────────────────────────────────────────

def _tilt_stream(env, seconds_quiet=8, seconds_tilt=6):
    """A jack: level, then 0 -> 1.5 degrees over 6 s, then held."""
    ramp = []
    for i in range(60):
        ramp += tilted(1, 1.5 * i / 60.0, seed=100 + i)
    env.spawn.next_lines = stream(quiet(seconds_quiet * 10) + ramp
                                  + tilted(seconds_tilt * 10, 1.5))


class TestAlarms:
    def test_tilt_sends_one_gsm7_alarm_with_the_position(self, env):
        env.arm_by_power()
        env.clock.advance(10)
        _tilt_stream(env)
        env.guard._sensor_next = 0
        env.guard._proc = None
        env.step()                                    # stream starts, is read to EOF
        env.step()                                    # the detection -> entry window
        env.send()
        v = env.view()
        assert v["state"] == "armed" and v["last_event"]["kind"] == "tilt"
        tilt_wall = v["last_event"]["ts"]
        assert v["entry_until"] == tilt_wall + 90 and env.runner.sms == []
        env.clock.advance(91)                         # a jack never brings the power back
        env.step(3)                                   # fresh battery read, alarm, GPS
        env.send()
        v = env.view()
        assert v["state"] == "alarm" and v["entry_until"] is None
        texts = env.runner.sms_texts()
        assert len(texts) == 2 and texts[0].startswith("ALFA 156: ALARM przechyl")
        # the time of the tilt, not of the end of the entry window
        assert time.strftime("%d.%m %H:%M", time.gmtime(tilt_wall)) in texts[0]
        assert "Pozycja: https://maps.google.com/?q=50.06143,19.93658" in texts[0]
        assert set(texts[0]) <= GSM7

    def test_log_only_never_sends(self, tmp_path, clock, runner, spawn):
        env = Env(tmp_path, clock, runner, spawn, park_log_only=True)
        env.arm_by_power()
        assert env.view()["state"] == "log_only"
        _tilt_stream(env)
        env.guard._proc = None
        env.step(2)
        env.plug()
        env.step()
        env.clock.advance(200)
        env.step()
        runner.battery = dict(runner.battery, percentage=10)
        env.guard._kick = True
        env.step()
        env.send(50)
        assert runner.sms == [] and runner.progs("termux-sms-send") == []
        ev = env.view()["last_event"]
        assert ev["logged_only"] is True

    def test_alarm_limits(self, tmp_path, clock, runner, spawn):
        env = Env(tmp_path, clock, runner, spawn, park_entry_s=0)     # alarm at once
        env.arm_by_power()
        g = env.guard
        with env.agent._lock:
            for i in range(8):
                g._trigger_locked("shake", 9.0, env.clock.wall + i)
        env.step()
        env.send()
        assert len(env.runner.sms) == 2                  # one alarm (2 numbers)
        for _ in range(10):
            env.clock.advance(601)
            with env.agent._lock:
                g._trigger_locked("shake", 9.0, env.clock.wall)
            env.step()
            env.send()
        assert len(env.runner.sms) == 2 * A.PARK_ALARM_MAX_PER_DAY
        assert env.view()["alarms_today"] == A.PARK_ALARM_MAX_PER_DAY

    def test_crash_sms_goes_first(self, tmp_path, clock, runner, spawn):
        env = Env(tmp_path, clock, runner, spawn, park_entry_s=0)
        env.arm_by_power()
        with env.agent._lock:
            env.guard._trigger_locked("tilt", 1.2, env.clock.wall)
        env.step()                                        # alarm SMS queued
        crash = {"event_id": "c0ffee01", "countdown_s": 15, "lat": 52.1, "lon": 21.0,
                 "fix_age_s": 3, "speed_kmh": 60, "dv_kmh": 40, "event_ts": int(T0)}
        assert env.peer.req("POST", "/v1/crash", crash)[0] == 200
        assert env.peer.req("POST", "/v1/crash/c0ffee01/send_now", {})[0] == 200
        env.send(60)
        texts = env.runner.sms_texts()
        assert len(texts) == 3
        assert "MOZLIWY WYPADEK" in texts[0] and "ALARM" in texts[1] and "ALARM" in texts[2]


# ── the entry window (park_entry_s) ──────────────────────────────────────

def _entry_stream(env, seconds_quiet=8):
    """The owner (or a thief) opens the door and sits down: a damped body
    bounce of 0.5 m/s2 for 3 s, then quiet."""
    bounce = []
    for i in range(30):
        t = i / 10.0
        amp = 0.5 * math.exp(-t / 1.5) * math.sin(2 * math.pi * 1.5 * t)
        bounce += quiet(1, g=(0.0, 0.0, 9.81 + amp), seed=300 + i)
    env.spawn.next_lines = stream(quiet(seconds_quiet * 10) + bounce + quiet(20, seed=7))


def _jolt(env):
    """Armed by power loss, then the entry bounce read from the stream."""
    env.arm_by_power()
    env.clock.advance(10)
    _entry_stream(env)
    env.guard._sensor_next = 0
    env.guard._proc = None
    env.step()                                    # the stream, read to EOF
    env.step()                                    # the detection
    v = env.view()
    assert v["state"] == "armed" and v["last_event"]["kind"] in ("shake", "tilt"), v
    assert v["entry_until"] is not None
    return v


class TestEntryWindow:
    def test_owner_returns_starts_the_engine_and_bcm_disarms_no_sms(self, env):
        v = _jolt(env)
        assert int(env.guard.st["pending"]["deadline"]) == v["entry_until"]
        env.clock.advance(15)
        env.plug()                                # ignition: USB power back
        env.step()
        assert env.guard.st["restored_wall"] is not None
        # the deadline moved to the end of the power grace (BCM boots, adb, BT)
        assert env.view()["entry_until"] == int(env.guard.st["restored_wall"] + 180)
        env.clock.advance(75)                     # +90 s: past the plain entry window
        env.step()
        env.send()
        assert env.runner.sms == [] and env.view()["state"] == "armed"
        status, out = env.peer.req("POST", "/v1/park/disarm", {})   # owner's phone on BT
        assert status == 200 and out["state"] == "disarmed" and out["entry_until"] is None
        env.clock.advance(600)
        env.step(3)
        env.send()
        assert env.runner.sms == [] and env.view()["state"] == "disarmed"

    def test_motion_without_the_power_coming_back_alarms_after_the_window(self, env):
        v = _jolt(env)
        kind = v["last_event"]["kind"]
        env.clock.advance(70)
        env.step()
        env.send()
        assert env.runner.sms == [] and env.view()["state"] == "armed"
        env.clock.advance(21)                     # past entry_until (90 s)
        env.step(3)
        env.send()
        texts = env.runner.sms_texts()
        assert len(texts) == 2 and {n for n, _t in env.runner.sms} == {OWNER, OWNER2}
        assert texts[0].startswith("ALFA 156: ALARM " + A.PARK_REASON_TEXT[kind])
        assert env.view()["state"] == "alarm" and env.view()["entry_until"] is None

    def test_later_jolts_do_not_extend_the_deadline(self, env):
        v = _jolt(env)
        first = v["entry_until"]
        for _ in range(5):
            env.clock.advance(15)
            with env.agent._lock:
                env.guard._trigger_locked("shake", 9.0, env.clock.wall)
            env.step()
        assert env.view()["entry_until"] == first
        env.clock.advance(30)
        env.step(3)
        env.send()
        assert len(env.runner.sms) == 2                     # one alarm, two numbers

    def test_power_back_without_the_owner_gives_one_alarm_after_the_grace(self, env):
        _jolt(env)
        env.clock.advance(15)
        env.plug()
        env.step()
        restored = env.guard.st["restored_wall"]
        env.clock.advance(restored + 170 - env.clock.wall)
        env.step()
        env.send()
        assert env.runner.sms == []
        env.clock.advance(11)                     # restored + 181 s
        env.step(3)
        env.send()
        texts = env.runner.sms_texts()
        assert len(texts) == 2
        assert "ALARM wstrzas" in texts[0] or "ALARM przechyl" in texts[0]
        env.clock.advance(900)                    # no second alarm for the power
        env.step(3)
        env.send()
        assert len(env.runner.sms) == 2 and env.guard.st["restored_wall"] is None

    def test_power_back_just_before_the_deadline_is_read_before_alarming(self, env):
        _jolt(env)
        env.clock.advance(80)
        env.step()                                # a regular battery read (every 15 s)
        polls = len(env.runner.progs("termux-battery-status"))
        env.clock.advance(2)
        # ignition at +82 s; the next regular read would come only at +95 s
        env.runner.battery = dict(env.runner.battery, plugged="PLUGGED_USB", status="CHARGING")
        env.clock.advance(9)                      # +91 s: past the deadline
        env.step(3)
        assert len(env.runner.progs("termux-battery-status")) == polls + 1   # forced read
        env.send()
        assert env.runner.sms == [] and env.guard.st["restored_wall"] is not None
        assert env.view()["entry_until"] > env.clock.wall

    def test_disarm_cancels_a_queued_alarm_sms_still_waiting_for_signal(
            self, tmp_path, clock, runner, spawn):
        env = Env(tmp_path, clock, runner, spawn, park_entry_s=0)
        env.arm_by_power()
        runner.operator = ""                      # no network: the SMS waits
        with env.agent._lock:
            env.guard._trigger_locked("shake", 9.0, clock.wall)
        assert env.view()["state"] == "alarm"
        env.step()                                # GPS, alarm SMS queued
        env.send()
        d = env.agent.meta["park_sms"][-1]
        assert d["kind"] == "park_alarm" and {r["st"] for r in d["rcpt"]} <= {"queued", "wait"}
        status, out = env.peer.req("POST", "/v1/park/disarm", {"code": env.code()})
        assert status == 200 and out["by"] == "owner_code"
        assert {(r["st"], r["err"]) for r in d["rcpt"]} == {("skipped", "disarmed")}
        assert d["no_retry"] is True
        runner.operator = "26001"
        clock.advance(600)
        env.send(50)
        assert runner.sms == [] and runner.progs("termux-sms-send") == []

    def test_low_battery_disarm_keeps_the_alarm(self, env):
        _jolt(env)
        env.runner.battery = dict(env.runner.battery, percentage=12)
        env.guard._kick = True
        env.step(2)
        env.send()
        v = env.view()
        assert v["state"] == "disarmed" and v["by"] == "low_battery"
        texts = env.runner.sms_texts()
        # the pending alarm went out at once (it may be a thief), then the battery note
        assert sum("ALARM" in t for t in texts) == 2
        assert sum("bateria telefonu 12%" in t for t in texts) == 2

    def test_zero_alarms_at_once(self, tmp_path, clock, runner, spawn):
        env = Env(tmp_path, clock, runner, spawn, park_entry_s=0)
        env.arm_by_power()
        with env.agent._lock:
            env.guard._trigger_locked("tilt", 1.2, clock.wall)
        assert env.view()["state"] == "alarm" and env.view()["entry_until"] is None
        env.step()
        env.send()
        assert len(runner.sms) == 2

    def test_the_pending_alarm_survives_a_restart(self, env, runner, clock, spawn):
        v = _jolt(env)
        again = make_agent(env.dir, runner, clock, spawn)
        assert again.park.view()["entry_until"] == v["entry_until"]
        assert again.park.st["pending"] == env.guard.st["pending"]
        clock.advance(v["entry_until"] + 1 - clock.wall)
        for _ in range(3):
            again.park.step()
        for _ in range(30):
            if again.step() > 0:
                break
        assert len(runner.sms) == 2 and again.park.view()["state"] == "alarm"
        again.park.shutdown()

    def test_log_only_has_no_entry_window_and_never_sends(self, tmp_path, clock, runner,
                                                          spawn):
        env = Env(tmp_path, clock, runner, spawn, park_log_only=True)
        env.arm_by_power()
        with env.agent._lock:
            env.guard._trigger_locked("shake", 9.0, clock.wall)
        assert env.guard.st["pending"] is None and env.view()["state"] == "log_only"
        clock.advance(600)
        env.step(3)
        env.send()
        assert runner.sms == []

    def test_status_reply_mentions_the_pending_alarm(self, env):
        _jolt(env)
        env.sms_in(f"PARK STATUS {env.code()}")
        env.step()
        env.send()
        text = env.runner.sms_texts()[0]
        assert "uzbrojony" in text and "ruch - alarm o" in text and set(text) <= GSM7

    def test_bad_entry_config_is_refused(self):
        for bad in (-1, 301, 1.5, "90", True):
            norm, err = A.normalize_config(park_config(park_entry_s=bad), strict=True)
            assert norm is None and "park_entry_s" in err


# ── battery ──────────────────────────────────────────────────────────────

class TestBattery:
    def test_light_mode_below_30_percent(self, env):
        env.arm_by_power()
        env.runner.calls.clear()                      # (the motion check before arming)
        env.runner.battery = dict(env.runner.battery, percentage=25)
        env.guard._kick = True
        env.runner.burst = "".join(stream(quiet(10)))
        env.step()
        assert env.view()["light"] is True
        assert env.spawn.procs[-1].terminated                 # the stream stopped
        sensor = [c for c in env.runner.calls if c[:1] == ["termux-sensor"]]
        # the stream's listener released BEFORE the first burst (otherwise
        # Termux:API keeps sampling at 10 Hz and the bursts get nothing)
        assert sensor[0] == ["termux-sensor", "-c"] and "-n" in sensor[1], sensor
        bursts = [c for c in sensor if "-n" in c]
        assert len(bursts) == 1
        env.clock.advance(5)
        env.step()
        assert len([c for c in env.runner.calls if "-n" in c]) == 1     # every 20 s only
        env.clock.advance(20)
        env.step()
        assert len([c for c in env.runner.calls if "-n" in c]) == 2
        assert env.view()["sensor"] == "light"
        # good bursts end on their own: no -c after each of them
        assert env.runner.calls.count(["termux-sensor", "-c"]) == 1

    def test_light_mode_after_24_h(self, env):
        env.arm_by_power()
        procs = len(env.spawn.procs)
        env.clock.advance(A.PARK_LIGHT_AFTER_S + 1)
        env.runner.burst = "".join(stream(quiet(10)))
        env.step()
        assert env.view()["light"] is True and len(env.spawn.procs) == procs

    def test_low_battery_disarms_with_one_sms(self, env):
        env.arm_by_power()
        env.runner.battery = dict(env.runner.battery, percentage=14)
        env.guard._kick = True
        env.step()
        v = env.view()
        assert v["state"] == "disarmed" and v["by"] == "low_battery"
        env.clock.advance(400)
        env.step(3)
        env.send()
        texts = env.runner.sms_texts()
        assert texts == ["ALFA 156: POSTOJ rozbrojony - bateria telefonu 14%. Alarm wroci po "
                         "podlaczeniu zasilania."] * 2
        assert env.view()["state"] == "disarmed"                # stays (await power)


# ── location fallback, persistence ───────────────────────────────────────

class TestLocationAndPersistence:
    def test_location_fallback_order(self, env):
        env.runner.fixes = {("gps", "once"): "timeout", ("network", "once"): None,
                            ("gps", "last"): dict(FIX_AWAY, elapsedMs=900_000,
                                                  provider="gps")}
        env.sms_in(f"GDZIE {env.code()}")
        env.step()
        env.send()
        locs = env.runner.progs("termux-location")
        assert [c[2:5] for c in locs] == [["gps", "-r", "once"], ["network", "-r", "once"],
                                          ["gps", "-r", "last"]]
        assert "(GPS sprzed 15 min, dokladnosc 8 m)" in env.runner.sms_texts()[0]

    def test_no_position_at_all(self, env):
        env.runner.fixes = {}
        env.sms_in(f"POZYCJA {env.code()}")
        env.step()
        env.send()
        assert env.runner.sms_texts() == ["ALFA 156: POZYCJA nieznana (brak GPS i sieci)"]
        assert len(env.runner.progs("termux-location")) == 4

    def test_state_survives_a_restart(self, env, runner, clock, spawn):
        env.arm_by_power()
        code = env.code()
        env.sms_in(f"PARK STATUS {code}")
        env.step()
        since = env.view()["since"]
        assert stat.S_IMODE(os.stat(Path(env.dir, "park.json")).st_mode) == 0o600
        again = make_agent(env.dir, runner, clock, spawn)
        v = again.park.view()
        assert v["state"] == "armed" and v["since"] == since and v["by"] == "power"
        assert again.park.st["totp_last"] == env.guard.st["totp_last"]
        # the used code stays used after the restart
        peer = Peer(again, clock, nonce=env.peer.nonce)
        assert peer.req("POST", "/v1/park/disarm", {"code": code})[1]["error"] == "code_used"

    def test_damaged_state_file_starts_disarmed(self, env, runner, clock, spawn):
        Path(env.dir, "park.json").write_text('{"state": "armed", "since": "x"}')
        again = make_agent(env.dir, runner, clock, spawn)
        assert again.park.st["state"] == "disarmed"
        Path(env.dir, "park.json").write_text("not json")
        assert make_agent(env.dir, runner, clock, spawn).park.st["state"] == "disarmed"


# ── the stream process ───────────────────────────────────────────────────

class TestStream:
    def test_restart_with_backoff(self, env):
        env.arm_by_power()
        assert len(env.spawn.procs) == 1                        # ended at once (no lines)
        env.step()                                               # notices the end
        assert env.view()["sensor"] == "error"
        env.step()
        assert len(env.spawn.procs) == 1                         # not before the backoff
        env.clock.advance(A.SENSOR_BACKOFF_MIN_S + 0.1)
        env.step()
        assert len(env.spawn.procs) == 2
        env.step()
        env.clock.advance(A.SENSOR_BACKOFF_MIN_S + 0.1)
        env.step()
        assert len(env.spawn.procs) == 2                         # backoff doubled

    def test_no_accelerometer(self, tmp_path, clock, runner, spawn):
        runner.sensors = ["Light", "Proximity"]
        env = Env(tmp_path, clock, runner, spawn)
        env.arm_by_power()
        assert spawn.procs == [] and env.view()["sensor"] == "no_sensor"
        env.step(3)
        assert len(runner.progs("termux-sensor")) == 1           # -l once (retry in 10 min)

    def test_spawn_failure_backs_off(self, tmp_path, clock, runner, spawn):
        spawn.fail = True
        env = Env(tmp_path, clock, runner, spawn)
        env.arm_by_power()
        assert env.view()["sensor"] == "error"


class _QueuePipe:
    """stdout of a stream that never ends by itself: lines from a queue,
    ``None`` = EOF."""

    def __init__(self):
        self.q = queue.Queue()
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        line = self.q.get()
        if line is None:
            raise StopIteration
        return line

    def close(self):
        self.closed = True


class StuckProc:
    """The old failure: termux-sensor (a bash script with a SIGTERM trap)
    defers the signal while its termux-api helper runs, so terminate() and
    kill() change nothing and the pipe stays open."""

    def __init__(self, argv):
        self.argv = argv
        self.stdout = _QueuePipe()
        self.terminate_calls = 0
        self.kill_calls = 0

    def poll(self):
        return None

    def terminate(self):
        self.terminate_calls += 1

    def kill(self):
        self.kill_calls += 1

    def wait(self, timeout=None):
        raise subprocess.TimeoutExpired(self.argv, timeout)

    def feed(self, vec):
        for line in obj_lines(vec):
            self.stdout.q.put(line)


class TestStreamStop:
    def test_a_stream_that_ignores_the_signals_is_abandoned(self, tmp_path, clock, runner,
                                                             monkeypatch):
        monkeypatch.setattr(A, "SENSOR_JOIN_S", 0.2)
        procs = []

        def spawn(argv):
            procs.append(StuckProc(argv))
            return procs[-1]

        env = Env(tmp_path, clock, runner, spawn)
        g = env.guard
        with env.agent._lock:
            g._arm_now_locked(clock.wall)
        g._manage_sensor()
        proc = procs[0]
        proc.feed(quiet(1)[0])
        deadline = time.monotonic() + 5
        while g._last_sample is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert g._last_sample is not None
        reader = g._reader
        runner.calls.clear()
        g._sensor_off()
        assert proc.terminate_calls == 1 and proc.kill_calls == 1
        assert runner.calls == [["termux-sensor", "-c"]]        # released all the same
        assert reader.is_alive()                                # still blocked on the pipe
        assert not proc.stdout.closed      # closing it could block the park thread
        with g._det_lock:
            g._last_sample = None
            det = g._det
        # the old process keeps writing: nothing reaches the detector
        proc.feed(tilted(1, 5.0)[0])
        reader.join(timeout=5)
        assert not reader.is_alive()                            # ended at the first sample
        assert g._last_sample is None and g._det is det and g._det_q.empty()
        proc.stdout.q.put(None)

    def test_a_restart_releases_the_sensor_before_the_next_stream(self, env):
        env.arm_by_power()
        env.runner.calls.clear()
        env.step()                                              # the stream ended
        assert env.runner.calls.count(["termux-sensor", "-c"]) == 1
        assert len(env.spawn.procs) == 1 and env.spawn.procs[0].terminated
        env.clock.advance(A.SENSOR_BACKOFF_MIN_S + 0.1)
        env.step()
        assert len(env.spawn.procs) == 2

    def test_a_failed_burst_releases_the_sensor(self, env):
        env.arm_by_power()
        env.runner.battery = dict(env.runner.battery, percentage=25)
        env.guard._kick = True
        env.runner.burst = "timeout"
        env.runner.calls.clear()
        env.step()
        sensor = [c for c in env.runner.calls if c[:1] == ["termux-sensor"]]
        assert sensor[0] == ["termux-sensor", "-c"] and "-n" in sensor[1], sensor
        assert sensor[2:] == [["termux-sensor", "-c"]], sensor
        assert env.view()["light"] is True and env.view()["sensor"] == "error"


class _GroupProc:
    def __init__(self, pid=4242, exits=True):
        self.pid = pid
        self.exits = exits
        self.calls = []

    def wait(self, timeout=None):
        self.calls.append("wait")
        if not self.exits:
            raise subprocess.TimeoutExpired("termux-sensor", timeout)
        return -15

    def terminate(self):
        self.calls.append("terminate")

    def kill(self):
        self.calls.append("kill")


class TestProcessGroups:
    @pytest.fixture
    def killpg(self, monkeypatch):
        sent = []
        mode = {"raise": None}

        def fake(pid, sig):
            sent.append((pid, sig))
            if mode["raise"] is not None:
                raise mode["raise"]()

        monkeypatch.setattr(A.os, "killpg", fake)
        return sent, mode

    def test_sigterm_goes_to_the_whole_group(self, killpg):
        sent, _mode = killpg
        p = _GroupProc()
        A.stop_process(p)
        assert sent == [(4242, signal.SIGTERM)] and p.calls == ["wait"]

    def test_sigkill_to_the_group_when_sigterm_is_ignored(self, killpg):
        sent, _mode = killpg
        p = _GroupProc(exits=False)
        A.stop_process(p, term_s=0.01, kill_s=0.01)
        assert sent == [(4242, signal.SIGTERM), (4242, signal.SIGKILL)]
        assert "terminate" not in p.calls and "kill" not in p.calls

    def test_a_group_already_gone_is_not_an_error(self, killpg):
        sent, mode = killpg
        mode["raise"] = ProcessLookupError
        p = _GroupProc(exits=False)
        A.stop_process(p, term_s=0.01, kill_s=0.01)
        assert "terminate" not in p.calls and "kill" not in p.calls

    def test_no_permission_falls_back_to_the_process_itself(self, killpg):
        _sent, mode = killpg
        mode["raise"] = PermissionError
        p = _GroupProc(exits=False)
        A.stop_process(p, term_s=0.01, kill_s=0.01)
        assert "terminate" in p.calls and "kill" in p.calls

    def test_odd_pids_never_reach_killpg(self, killpg):
        sent, _mode = killpg
        for pid in (None, True, 0, 1, -5, "42"):
            p = _GroupProc(pid=pid, exits=False)
            A.stop_process(p, term_s=0.01, kill_s=0.01)
            assert "terminate" in p.calls and "kill" in p.calls
        assert sent == []

    def test_spawn_and_runner_start_their_own_session(self, killpg, monkeypatch):
        sent, _mode = killpg
        seen = []

        class FakePopen:
            def __init__(self, argv, **kw):
                seen.append((list(argv), kw))
                self.pid = 777
                self.returncode = None
                self.n = 0

            def communicate(self, input=None, timeout=None):
                self.n += 1
                if self.n == 1:
                    raise subprocess.TimeoutExpired("termux-sensor", timeout)
                return "", ""

            def wait(self, timeout=None):
                self.returncode = -15
                return -15

        monkeypatch.setattr(A.subprocess, "Popen", FakePopen)
        rc, _out, err = A.default_runner(["termux-sensor", "-s", ACCEL, "-n", "10"], None, 0.5)
        assert rc == A.RC_TIMEOUT and "timed out" in err
        # the timeout kills the script WITH its termux-api helper
        assert sent == [(777, signal.SIGTERM)]
        assert seen[0][1]["start_new_session"] is True and seen[0][1]["shell"] is False
        A.default_spawn(["termux-sensor", "-s", ACCEL, "-d", "100"])
        assert seen[1][1]["start_new_session"] is True and seen[1][1]["shell"] is False
        with pytest.raises(ValueError):
            A.default_spawn("termux-sensor -s x")


# ── GPS in a garage ──────────────────────────────────────────────────────

class TestGpsSkip:
    def _locs(self, env):
        return [c[2:5] for c in env.runner.progs("termux-location")]

    def test_after_a_gps_failure_commands_ask_the_network_first(self, env):
        env.runner.fixes = {("gps", "once"): "timeout", ("network", "once"): FIX_AWAY}
        env.sms_in(f"POZYCJA {env.code()}")
        env.step()
        assert self._locs(env) == [["gps", "-r", "once"], ["network", "-r", "once"]]
        env.clock.advance(150)            # past the reply limit and the reuse of the fix
        env.sms_in(f"POZYCJA {env.code()}")
        env.step()
        assert self._locs(env)[2:] == [["network", "-r", "once"]]     # no 60 s of GPS
        env.clock.advance(A.PARK_GPS_SKIP_S)
        env.sms_in(f"POZYCJA {env.code()}")
        env.step()
        assert self._locs(env)[3] == ["gps", "-r", "once"]          # tried again later
        env.send()
        assert len(env.runner.sms) == 3
        assert all("POZYCJA https://" in t for t in env.runner.sms_texts())

    def test_a_good_gps_fix_clears_the_memory(self, env):
        env.runner.fixes = {("gps", "once"): "timeout", ("network", "once"): FIX_AWAY}
        env.sms_in(f"POZYCJA {env.code()}")
        env.step()
        assert env.agent.phone.gps_failed_at is not None
        env.clock.advance(A.PARK_GPS_SKIP_S + 1)
        env.runner.fixes = {("gps", "once"): FIX_AWAY}
        env.sms_in(f"POZYCJA {env.code()}")
        env.step()
        assert env.agent.phone.gps_failed_at is None

    def test_an_alarm_always_tries_gps(self, tmp_path, clock, runner, spawn):
        env = Env(tmp_path, clock, runner, spawn, park_entry_s=0)
        runner.fixes = {("gps", "once"): "timeout", ("network", "once"): FIX_AWAY}
        env.sms_in(f"POZYCJA {env.code()}")
        env.step()
        env.arm_by_power()
        n = len(self._locs(env))
        with env.agent._lock:
            env.guard._trigger_locked("tilt", 1.2, clock.wall)
        env.step()
        # the car may have just been taken out from under the roof
        assert self._locs(env)[n] == ["gps", "-r", "once"]


# ── no arming while the car moves ────────────────────────────────────────

def _moving_burst():
    return "".join(stream(quiet(10, noise=0.6, seed=7)))


class TestArmWhileMoving:
    def _until_arm_time(self, env):
        env.step()
        env.unplug()
        env.step()
        env.clock.advance(181)
        env.step()
        assert env.view()["state"] == "arming"
        env.clock.advance(121)

    def test_a_cable_lost_while_driving_does_not_arm_a_moving_phone(self, env):
        env.runner.burst = _moving_burst()
        self._until_arm_time(env)
        env.step()
        v = env.view()
        assert v["state"] == "arming" and v["arm_at"] == int(env.clock.wall + 60)
        assert env.spawn.procs == []                            # no stream yet
        env.runner.burst = "".join(stream(quiet(10)))           # parked now
        env.clock.advance(61)
        env.step()
        assert env.view()["state"] == "armed" and env.view()["by"] == "power"

    def test_a_sensor_that_always_moves_arms_after_the_limit(self, env):
        env.runner.burst = _moving_burst()
        self._until_arm_time(env)
        for _ in range(A.PARK_MOVING_MAX):
            env.step()
            assert env.view()["state"] == "arming"
            env.clock.advance(A.PARK_MOVING_RETRY_S + 1)
        env.step()
        assert env.view()["state"] == "armed"

    def test_bcm_arm_waits_for_the_car_to_stop_too(self, env):
        env.runner.burst = _moving_burst()
        assert env.peer.req("POST", "/v1/park/arm", {"delay_min": 0})[0] == 200
        env.step()
        assert env.view()["state"] == "arming"
        env.runner.burst = "".join(stream(quiet(10)))
        env.clock.advance(61)
        env.step()
        assert env.view()["state"] == "armed" and env.view()["by"] == "bcm"

    def test_burst_spread(self):
        assert A.burst_spread([]) is None and A.burst_spread([(0, 0, 9.81)] * 4) is None
        still = A.burst_spread(quiet(10))
        assert still is not None and still < A.PARK_MOVING_MS2
        assert A.burst_spread(quiet(10, noise=0.6, seed=7)) > A.PARK_MOVING_MS2
        assert A.burst_spread([(float("nan"), 0, 0)] * 10) is None


# ── configuration, endpoints, CLI ────────────────────────────────────────

class TestConfigAndApi:
    def test_park_keys_do_not_count_while_the_toggle_is_off(self):
        base, _ = A.normalize_config(dict(park_config(), toggles={
            "crash_sms": True, "parking_guard": False, "cabin_watch": False, "call112": False}),
            strict=True)
        six = {k: base[k] for k in ("recipients", "sim_slot", "vehicle_label", "toggles",
                                    "dry_run", "follow_up_cancel")}
        # A false remote_session (1.4.0) is not part of the hash either: the
        # #128 form had four toggles.
        assert base["toggles"]["remote_session"] is False
        six["toggles"] = {k: v for k, v in six["toggles"].items() if k != "remote_session"}
        assert A.config_hash(base) == A.sha256_hex(A.canonical_json(six).encode())[:16]
        on, _ = A.normalize_config(park_config(), strict=True)
        changed, _ = A.normalize_config(park_config(park_tilt_deg=0.8), strict=True)
        assert A.config_hash(on) != A.config_hash(changed)

    @pytest.mark.parametrize("bad", [
        {"park_numbers": ["601234567"]}, {"park_numbers": [OWNER] * 2 + [OWNER2, "+48601234569",
                                                                         "+48601234560"]},
        {"park_log_only": "yes"}, {"park_arm_after_min": 0}, {"park_arm_after_min": 3.5},
        {"park_arm_delay_min": 31}, {"park_grace_min": 16}, {"park_tilt_deg": 0.1},
        {"park_shake_k": 60}, {"park_home": {"lat": 52, "lon": 21}},
        {"park_home": {"lat": 52, "lon": 21, "radius_m": 49}},
        {"park_home": {"lat": 95, "lon": 21, "radius_m": 100}}, {"park_home": "home"}])
    def test_bad_park_config_is_refused(self, bad):
        norm, err = A.normalize_config(park_config(**bad), strict=True)
        assert norm is None and err

    def test_canonical_numbers(self):
        norm, _ = A.normalize_config(park_config(park_shake_k=6, park_home={
            "lat": 52.12345678, "lon": 21.1, "radius_m": 100}), strict=True)
        assert norm["park_shake_k"] == 6.0 and isinstance(norm["park_shake_k"], float)
        assert norm["park_home"] == {"lat": 52.123457, "lon": 21.1, "radius_m": 100}

    def test_get_park_view(self, env):
        status, v = env.peer.req("GET", "/v1/park")
        assert status == 200
        assert set(v) == {"state", "since", "by", "arm_at", "last_event", "battery", "log_only",
                          "light", "sensor", "totp_ready", "numbers_n", "home_set",
                          "alarms_today", "entry_until"}
        assert v["state"] == "disarmed" and v["totp_ready"] is True and v["numbers_n"] == 2
        status, out, = env.peer.req("GET", "/v1/park", sign=False)
        assert status == 401

    def test_park_setup_cli(self, tmp_path):
        d = str(tmp_path / "st")
        os.makedirs(d)
        out = io.StringIO()
        assert A.write_park_setup(d, out=out) == 0
        path = Path(d, A.TOTP_FILE)
        secret = path.read_text().strip()
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
        assert A.parse_totp_secret(secret) is not None
        assert f"secret={secret}" in out.getvalue()
        out2 = io.StringIO()
        assert A.write_park_setup(d, out=out2) == 0             # shown again, not replaced
        assert path.read_text().strip() == secret and "juz jest" in out2.getvalue()
        assert A.write_park_setup(d, new=True, out=io.StringIO()) == 0
        assert path.read_text().strip() != secret

    def test_park_numbers_cli(self, tmp_path):
        d = str(tmp_path / "st")
        os.makedirs(d)
        assert A.write_park_numbers(d, f"{OWNER}, {OWNER2}", out=io.StringIO()) == 0
        assert json.loads(Path(d, A.PARK_LOCAL_FILE).read_text()) == {"numbers": [OWNER, OWNER2]}
        assert A.write_park_numbers(d, "601234567", out=io.StringIO()) == 2
        assert A.write_park_numbers(d, "", out=io.StringIO()) == 0
        assert json.loads(Path(d, A.PARK_LOCAL_FILE).read_text()) == {"numbers": []}

    def test_secret_and_codes_never_logged(self, env, caplog):
        with caplog.at_level(logging.DEBUG, logger="bcm_agent"):
            code = env.code()
            env.sms_in(f"PARK ON {code}")
            env.step()
            env.peer.req("POST", "/v1/park/disarm", {"code": "000000"})
        text = "\n".join(r.getMessage() for r in caplog.records)
        assert B32 not in text and code not in text and "000000" not in text
        assert OWNER not in text                                   # masked
