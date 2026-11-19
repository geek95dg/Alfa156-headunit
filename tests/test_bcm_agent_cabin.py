"""Czuwanie kabiny (plan I) in the Termux agent
(tools/car_phone/termux/bcm_agent.py, :class:`CabinWatch` on top of
:class:`ParkGuard`).

No Termux, no camera, no root: every phone command goes through a fake
runner that refuses anything unexpected (``su`` only with the three fixed
cabin strings, ``termux-camera-photo`` only with the front id and a path in
the agent's own directory), the sensor stream is a fake process whose lines
advance a fake clock, photos are JPEGs generated with Pillow HERE (the agent
gets Pillow injected, or None for the "no Pillow" path), state lives in
tmp_path. Nothing can send a real SMS or take a real photo.

Covers: the light detector (lamp vs cloud vs passing headlights, mute while
the screen is on), the combiner (light + motion, tilt, door, 3 weak
signals), the full flow (lamp + seat motion => 3 photos at 0/3/6 s with the
fixed su strings => one alarm SMS after the entry window that also covers
the parking guard's waiting alarm), wind / truck / cloud => nothing, owner
proof in the entry window (BCM disarm, TOTP code, mid-series) deleting the
photos, the door signal never disarming, the limits (series and the shared
alarm SMS budget), the temperature / battery / charging guards, front camera
id parsing, EXIF removal (Pillow re-encode and the stdlib segment strip),
retention (72 h, 200 MB, foreign files and symlinks untouched), the
analysis (reference vs burst, window mask, dark frames) and running without
Pillow, GET /v1/cabin (never the photos), the config keys and the hash,
the sensor argv and persistence across a restart.
"""

from __future__ import annotations

import calendar
import importlib
import io
import json
import math
import os
import random
import stat
import time
from pathlib import Path

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image, ImageDraw  # noqa: E402

P = importlib.import_module("tests.test_bcm_agent_park")
A = P.A

ACCEL = P.ACCEL
LIGHT = "TCS3701 Light"
OWNER, OWNER2 = P.OWNER, P.OWNER2
GSM7 = P.GSM7


# ── generated photos (Pillow in the tests only) ──────────────────────────

def cabin_image(person=False, window_change=False, brightness=1.0, size=(640, 480)):
    """A synthetic cabin seen from the headliner: gradient, two seats, a
    console; ``person`` = a big dark shape on the driver's seat;
    ``window_change`` = something bright moves in the left window strip."""
    w, h = size
    small = Image.new("RGB", (64, 48))
    px = small.load()
    for y in range(48):
        for x in range(64):
            v = int((90 + 60 * x / 64 + 40 * y / 48) * brightness)
            px[x, y] = (v, v, v)
    img = small.resize(size, Image.BILINEAR)
    d = ImageDraw.Draw(img)
    shade = lambda v: tuple(int(c * brightness) for c in v)       # noqa: E731
    d.rectangle([w * 0.2, h * 0.35, w * 0.45, h * 0.9], fill=shade((60, 60, 70)))
    d.rectangle([w * 0.55, h * 0.35, w * 0.8, h * 0.9], fill=shade((60, 60, 70)))
    d.rectangle([w * 0.46, h * 0.5, w * 0.54, h * 0.95], fill=shade((40, 40, 40)))
    if person:
        d.ellipse([w * 0.18, h * 0.15, w * 0.5, h * 0.95], fill=shade((20, 15, 10)))
    if window_change:
        d.rectangle([0, 0, w * 0.12, h], fill=shade((250, 250, 250)))
    return img


def jpeg(img, exif=True):
    buf = io.BytesIO()
    if exif:
        ex = Image.Exif()
        ex[0x010F] = "Xiaomi"                 # Make
        ex[0x0110] = "Redmi Note 8 Pro"       # Model
        ex[0x0132] = "2026:11:19 03:12:00"    # DateTime
        img.save(buf, "JPEG", quality=90, exif=ex.tobytes())
    else:
        img.save(buf, "JPEG", quality=90)
    return buf.getvalue()


EMPTY = jpeg(cabin_image())
PERSON = jpeg(cabin_image(person=True))


# ── fakes ────────────────────────────────────────────────────────────────

class CabinRunner(P.Runner):
    """The parking guard's fake Termux:API plus the camera and su."""

    def __init__(self, clock):
        super().__init__(clock)
        self.sensors = [LIGHT, f"{ACCEL} Uncalibrated", ACCEL, "Linear Acceleration"]
        self.battery = dict(self.battery, temperature=25.0)
        self.cameras = [{"id": "0", "facing": "back"}, {"id": "1", "facing": "front"}]
        self.photo_data = [EMPTY]            # cycled for every photo
        self.photo_fail = False
        self.photo_paths = []
        self.su_calls = []
        self.cabin_dir = None
        self.on_photo = None

    def __call__(self, argv, stdin, timeout):
        prog = argv[0] if argv else ""
        if prog == "termux-camera-info":
            assert argv == ["termux-camera-info"]
            self.calls.append(list(argv))
            return 0, json.dumps(self.cameras), ""
        if prog == "termux-camera-photo":
            assert len(argv) == 4 and argv[1] == "-c" and argv[2] == "1", argv
            path = argv[3]
            assert A.valid_photo_path(path) and os.path.dirname(path) == self.cabin_dir, path
            assert 0 < timeout <= 30
            self.calls.append(list(argv))
            self.photo_paths.append(path)
            if self.on_photo is not None:
                self.on_photo(path)
            if self.photo_fail:
                Path(path).write_bytes(b"")          # the script's "touch"
                return 1, "", "Error: camera is used by another app"
            data = self.photo_data[(len(self.photo_paths) - 1) % len(self.photo_data)]
            Path(path).write_bytes(data)
            return 0, "", ""
        if prog == "su":
            assert len(argv) == 3 and argv[1] == "-c" and argv[2] in A.CABIN_SU_COMMANDS, argv
            self.calls.append(list(argv))
            self.su_calls.append(argv[2])
            return 0, "", ""
        return super().__call__(argv, stdin, timeout)

    def photos(self):
        return [c for c in self.calls if c[0] == "termux-camera-photo"]


class CabinSpawner:
    def __init__(self, clock):
        self.clock = clock
        self.procs = []
        self.argvs = []
        self.next_lines = []

    def __call__(self, argv):
        assert argv in (["termux-sensor", "-s", ACCEL, "-d", "100"],
                        ["termux-sensor", "-s", f"{ACCEL},{LIGHT}", "-d", "100"]), argv
        self.argvs.append(list(argv))
        proc = P.FakeProc(argv, list(self.next_lines), self.clock)
        self.next_lines = []
        self.procs.append(proc)
        return proc


def obj2(vec, lux):
    obj = {ACCEL: {"values": list(vec)}}
    if lux is not None:
        obj[LIGHT] = {"values": [lux]}
    return [line + "\n" for line in json.dumps(obj, indent=2).splitlines()]


def lines(samples):
    out = []
    for vec, lux in samples:
        out += obj2(vec, lux)
    return out


def quiet(n, lux, seed=1):
    return [(v, lux) for v in P.quiet(n, seed=seed)]


def shake(n, lux, amp=0.4):
    return [((0.0, 0.0, 9.81 + (amp if i % 2 else -amp)), lux) for i in range(n)]


def lamp_and_seat():
    """Night: 7 s dark and still (calibration), the interior lamp comes on,
    1 s later someone sits down (1.5 s of rocking), then still, lamp on."""
    return quiet(70, 0.5) + quiet(10, 40.0, seed=2) + shake(15, 40.0) + quiet(30, 40.0, seed=3)


# ── fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def clock():
    return P.Clock()


@pytest.fixture
def runner(clock):
    return CabinRunner(clock)


@pytest.fixture
def spawn(clock):
    return CabinSpawner(clock)


def toggles(**over):
    t = {"crash_sms": True, "parking_guard": True, "cabin_watch": True, "call112": False}
    t.update(over)
    return t


class CabinEnv:
    def __init__(self, tmp_path, clock, runner, spawn, pillow="real", **cfg):
        self.dir = str(tmp_path / "bcm_agent")
        self.clock, self.runner, self.spawn = clock, runner, spawn
        self.pil = A.load_pillow() if pillow == "real" else pillow
        self.agent = A.Agent(self.dir, runner=runner, clock=lambda: clock.boot,
                             wall=lambda: clock.wall, localtime=time.gmtime, spawn=spawn,
                             mktime=calendar.timegm, pillow=self.pil)
        Path(self.dir, "PAIRING").write_text(P.CODE + "\n")
        body = json.dumps({"secret": P.SECRET}).encode()
        ts = int(clock.wall)
        sig = A.sign(P.CODE.encode(), A.request_message("POST", "/v1/pair", ts, 50, body))
        status, _d, _h = self.agent.handle("POST", "/v1/pair", {
            "X-BCM-Ts": str(ts), "X-BCM-Nonce": "50", "X-BCM-Sig": sig}, body)
        assert status == 200
        self.peer = P.Peer(self.agent, clock)
        cfg.setdefault("toggles", toggles())
        status, out = self.peer.req("PUT", "/v1/config", P.park_config(**cfg))
        assert status == 200, out
        Path(self.dir, A.TOTP_FILE).write_text(P.B32 + "\n")
        self.guard = self.agent.park
        self.cabin = self.guard.cabin
        runner.cabin_dir = os.path.join(self.dir, "cabin")
        clock.advance(60)

    # park side
    def arm(self, ref=False):
        with self.agent._lock:
            self.guard._arm_now_locked(self.clock.wall)
            if not ref:
                self.cabin._todo = [t for t in self.cabin._todo if t["kind"] != "ref"]

    def step(self, n=1):
        for _ in range(n):
            self.guard.step()
            if self.guard._reader is not None:
                self.guard._reader.join(timeout=5)

    def stream(self, samples):
        """The sensor stream: spawned and read by one park step, the
        detections handled by the next."""
        self.spawn.next_lines = lines(samples)
        self.guard._sensor_next = 0.0
        self.step(2)

    def send(self, n=40):
        for _ in range(n):
            if self.agent.step() > 0:
                break

    # cabin side
    def cabin_run(self, seconds, max_iter=500):
        end = self.clock.boot + seconds
        for _ in range(max_iter):
            w = self.cabin.step()
            if self.clock.boot >= end:
                return
            if w > 0:
                self.clock.advance(min(w, end - self.clock.boot))
        raise AssertionError("cabin loop did not settle")

    def until_alarm(self, seconds):
        """Let the entry window run out: park steps (battery kick, timers,
        the alarm job with the position), then the SMS scheduler."""
        self.clock.advance(seconds)
        self.step(3)
        self.send()

    def event(self):
        return self.cabin.st["events"][-1] if self.cabin.st["events"] else None

    def files(self):
        d = Path(self.dir, "cabin")
        return sorted(p.name for p in d.iterdir()) if d.exists() else []

    def view(self):
        status, out = self.peer.req("GET", "/v1/cabin")
        assert status == 200
        return out


@pytest.fixture
def env(tmp_path, clock, runner, spawn):
    return CabinEnv(tmp_path, clock, runner, spawn)


# ── the light detector and the combiner ─────────────────────────────────

class TestLightDetector:
    def feed(self, det, values, t0=0.0, dt=0.1):
        out = []
        for i, v in enumerate(values):
            ev = det.feed(t0 + i * dt, v)
            if ev:
                out.append((round(t0 + i * dt, 1), ev))
        return out

    def test_interior_lamp_is_one_signal(self):
        det = A.LightDetector()
        out = self.feed(det, [0.5] * 30 + [40.0] * 200)
        assert out == [(3.0, ("light", 40.0))]          # one signal, then the cooldown

    def test_cloud_dusk_and_passing_headlights_are_not(self):
        det = A.LightDetector()
        # a cloud: 100 -> 600 lux over 30 s (x6, but slowly)
        assert self.feed(det, [100 + 500 * i / 300 for i in range(300)]) == []
        # dusk in the car park and headlights far away: x4, +3 lux
        assert self.feed(A.LightDetector(), [1.0] * 30 + [4.0] * 30) == []
        # x10 but only +4.5 lux (moonlight)
        assert self.feed(A.LightDetector(), [0.5] * 30 + [5.0] * 30) == []
        # the lamp going OFF is not a signal
        assert self.feed(A.LightDetector(), [40.0] * 30 + [0.5] * 30) == []

    def test_mute_while_the_screen_is_on(self):
        det = A.LightDetector()
        det.mute(10.0)
        assert self.feed(det, [0.5] * 30 + [300.0] * 30 + [0.5] * 50) == []   # t < 10 s
        assert self.feed(det, [0.5] * 30 + [40.0] * 5, t0=20.0)                # back on

    def test_garbage_is_ignored(self):
        det = A.LightDetector()
        for bad in (float("nan"), float("inf"), -1, "40", None, True, 1e9):
            assert det.feed(1.0, bad) is None
        assert det.feed(float("nan"), 3.0) is None


class TestCombiner:
    def test_light_and_motion_within_10_s(self):
        c = A.CabinCombiner()
        assert c.feed("light", 100.0) is None
        assert c.feed("shake", 108.0) == (["light", "shake"], False)

    def test_light_and_motion_too_far_apart(self):
        c = A.CabinCombiner()
        assert c.feed("light", 100.0) is None
        assert c.feed("shake", 111.0) is None           # 2 weak — not yet

    def test_tilt_and_door_alone(self):
        assert A.CabinCombiner().feed("tilt", 1.0) == (["tilt"], False)
        c = A.CabinCombiner()
        c.feed("light", 0.0)
        assert c.feed("door", 30.0) == (["door", "light"], False)

    def test_three_weak_signals_in_60_s(self):
        c = A.CabinCombiner()
        assert c.feed("shake", 0.0) is None
        assert c.feed("shake", 20.0) is None
        assert c.feed("shake", 40.0) == (["shake"], True)          # ~20 s of rocking
        # one light + two shakes, each more than 10 s from the light
        c = A.CabinCombiner()
        assert c.feed("light", 0.0) is None
        assert c.feed("shake", 15.0) is None
        assert c.feed("shake", 30.0) == (["light", "shake"], True)
        c = A.CabinCombiner()
        for t in (0.0, 40.0):
            assert c.feed("shake", t) is None
        assert c.feed("shake", 101.0) is None           # the first fell out of the window

    def test_lights_alone_never_make_an_event(self):
        """Hazard lights of a car alongside, a tow truck's beacon, lightning,
        a row of passing cars: the same source again and again — every light
        jump in the window counts as ONE weak signal."""
        c = A.CabinCombiner()
        for t in (0.0, 15.0, 30.0, 45.0, 60.0, 75.0, 90.0):
            assert c.feed("light", t) is None
        # ... but they stay in the window: a later pair names the light
        assert c.feed("shake", 95.0) == (["light", "shake"], False)
        c = A.CabinCombiner()
        for t in (0.0, 15.0, 30.0):
            assert c.feed("light", t) is None
        assert c.feed("shake", 45.0) is None             # light (once) + 1 shake = 2
        assert c.feed("shake", 58.0) == (["light", "shake"], True)

    def test_power_is_never_a_trigger(self):
        assert A.CabinCombiner().feed("power", 0.0) is None
        assert A.CabinCombiner().feed("bogus", 0.0) is None


class TestTexts:
    def test_alarm_sms_is_gsm7(self):
        fix = {"lat": 52.22968, "lon": 21.01223, "acc": 12, "age_s": 4, "provider": "gps"}
        text = A.cabin_alarm_text("ALFA 156", ["light", "shake"], False, P.T0, 3, fix,
                                  time.gmtime)
        assert text.startswith("ALFA 156: RUCH W KABINIE ")
        assert "(swiatlo+ruch). Zdjecia: 3. Pozycja: https://maps.google.com/?q=52.22968," \
               "21.01223" in text
        assert set(text) <= GSM7 and A.sms_segments(text) <= 2
        weak = A.cabin_alarm_text("ALFA 156", ["door", "light", "shake", "tilt", "power"], True,
                                  P.T0, 0, None, time.gmtime)
        assert "(drzwi+swiatlo+ruch+przechyl+zasilanie, 3 slabe sygnaly)" in weak
        assert "nieznana (brak GPS)" in weak and set(weak) <= GSM7


# ── camera id, paths, su strings ─────────────────────────────────────────

class TestCameraAndPaths:
    @pytest.mark.parametrize("info,want", [
        ([{"id": "0", "facing": "back"}, {"id": "1", "facing": "front"}], "1"),
        ([{"id": 2, "facing": "FRONT"}], "2"),
        ([{"id": "0", "facing": "back"}], None),
        ([{"id": "1; rm -rf /", "facing": "front"}], None),
        ([{"id": "../x", "facing": "front"}], None),
        ([{"id": "123", "facing": "front"}], None),
        ([{"id": True, "facing": "front"}], None),
        ({"id": "1", "facing": "front"}, None),
    ])
    def test_front_id(self, info, want):
        assert A.parse_camera_info(json.dumps(info)) == want

    def test_front_id_garbage(self):
        for text in (None, "", "not json", "[" * 5000, "NaN", "x" * 300000):
            assert A.parse_camera_info(text) is None

    def test_paths(self, tmp_path):
        assert A.valid_photo_path("/data/data/com.termux/files/home/.config/bcm_agent/cabin/"
                                  "cab_0123456789abcdef_0.jpg")
        for bad in ("relative/x.jpg", "/a b/x.jpg", "/a/../x.jpg", "/a//x.jpg", "/a/x;rm",
                    "/a/$(id)", "/a/`id`", "/a/x\n", None, "/" + "a" * 300):
            assert not A.valid_photo_path(bad), bad

    def test_su_strings_are_fixed_and_safe(self):
        for cmd in A.CABIN_SU_COMMANDS:
            assert A.SU_SAFE_RE.fullmatch(cmd)
            assert A.su_argv(cmd) == ["su", "-c", cmd]
        # -W: am start waits until Termux is shown (the camera needs the
        # app in the foreground before the first photo)
        assert A.CABIN_SU_COMMANDS == ("input keyevent KEYCODE_WAKEUP",
                                       "am start -W -a android.intent.action.MAIN -c "
                                       "android.intent.category.LAUNCHER com.termux",
                                       "input keyevent KEYCODE_SLEEP")

    def test_camera_photo_refuses_bad_arguments_without_running(self, clock):
        calls = []
        phone = A.Phone(lambda argv, stdin, timeout: calls.append(argv) or (0, "", ""),
                        lambda: clock.boot)
        assert phone.camera_photo("1;id", "/tmp/x.jpg")[0] is False
        assert phone.camera_photo("1", "/tmp/a b.jpg")[0] is False
        assert phone.camera_photo("1", "rel.jpg")[0] is False
        assert calls == []
        assert phone.camera_photo("1", "/tmp/x.jpg") == (True, "")
        assert calls == [["termux-camera-photo", "-c", "1", "/tmp/x.jpg"]]


# ── the full flow ────────────────────────────────────────────────────────

class TestFlow:
    def test_lamp_and_seat_motion_three_photos_then_one_alarm_sms(self, env, runner):
        env.arm()
        env.stream(lamp_and_seat())
        assert runner.photos() == []                   # nothing on the park thread
        ev = env.event()
        assert ev is not None and ev["outcome"] == "pending", env.cabin.st
        assert ev["reasons"] == ["light", "shake"] and ev["weak"] is False
        assert env.guard.st["pending"]["kind"] == "shake"      # the park alarm waits too
        assert env.view()["state"] == "pending"
        t0 = env.clock.boot
        taken = []
        runner.on_photo = lambda path: taken.append(round(env.clock.boot - t0, 1))
        env.cabin_run(12)
        assert taken == [0.0, 3.0, 6.0]                 # 0/3/6 s
        assert runner.su_calls == [A.WAKE_COMMAND, A.FOREGROUND_COMMAND, A.SLEEP_COMMAND]
        assert [c[2] for c in runner.photos()] == ["1", "1", "1"]
        names = [f"cab_{ev['id']}_{i}.jpg" for i in range(3)]
        assert env.files() == names
        cdir = Path(env.dir, "cabin")
        assert stat.S_IMODE(cdir.stat().st_mode) == 0o700
        for n in names:
            assert stat.S_IMODE((cdir / n).stat().st_mode) == 0o600
        ev = env.event()
        assert ev["photos"] == names and ev["clean"] is True
        assert ev["analysis"]["verdict"] in ("no_change", "change")
        # the entry window runs out (60 s) without the owner's proof
        env.until_alarm(55)
        assert ev["outcome"] == "alarm"
        texts = runner.sms_texts()
        assert len(texts) == 2 and texts[0] == texts[1]          # both listed numbers
        assert {n for n, _t in runner.sms} == {OWNER, OWNER2}
        text = texts[0]
        assert text.startswith("ALFA 156: RUCH W KABINIE ") and "(swiatlo+ruch)" in text
        assert "Zdjecia: 3. Pozycja: https://maps.google.com/?q=" in text and set(text) <= GSM7
        g = env.guard.st
        assert g["state"] == "alarm" and g["last_event"]["kind"] == "cabin"
        assert g["pending"] is None                      # covered: one SMS per entry
        # the parking guard's own entry window (90 s) passes — no second SMS
        env.until_alarm(60)
        assert len(runner.sms_texts()) == 2
        v = env.view()
        assert v["last_event"]["outcome"] == "alarm" and v["last_event"]["photos"] == 3

    def test_wind_truck_and_clouds_do_nothing(self, env, runner):
        env.arm()
        rnd = random.Random(5)
        wind = [((0.0, 0.02 * math.sin(i / 3.0), 9.81 + rnd.gauss(0, 0.01)),
                 300.0 + rnd.uniform(-10, 10)) for i in range(200)]
        truck = shake(2, 300.0, amp=1.0)               # 0.2 s jolt
        cloud = [(v, 300.0 + 300.0 * i / 300) for i, v in enumerate(P.quiet(300, seed=9))]
        headlights = quiet(40, 1.0) + quiet(20, 4.0, seed=4) + quiet(40, 1.0, seed=6)
        env.stream(quiet(70, 300.0) + wind + truck + quiet(20, 300.0) + cloud + headlights)
        env.cabin_run(5)
        assert env.cabin.st["events"] == [] and runner.photos() == []
        assert runner.su_calls == []
        env.until_alarm(120)
        assert runner.sms == []
        assert env.view()["state"] == "watching"

    def test_one_shake_alone_takes_no_photos(self, env, runner):
        env.arm()
        env.stream(quiet(70, 300.0) + shake(15, 300.0) + quiet(30, 300.0))
        assert env.guard.st["pending"]["kind"] == "shake"     # D4 still waits
        assert env.cabin.st["events"] == []                    # one weak signal
        env.cabin_run(5)
        assert runner.photos() == []

    def test_cabin_off_means_no_light_no_camera(self, tmp_path, clock, runner, spawn):
        env = CabinEnv(tmp_path, clock, runner, spawn, toggles=toggles(cabin_watch=False))
        env.arm()
        env.stream(lamp_and_seat())
        env.cabin_run(20)
        assert spawn.argvs[0] == ["termux-sensor", "-s", ACCEL, "-d", "100"]
        assert env.cabin.st["events"] == [] and runner.photos() == [] and runner.su_calls == []
        assert not any(c[0] == "termux-camera-info" for c in runner.calls)
        assert env.view()["state"] == "off"

    def test_never_while_disarmed(self, env, runner):
        with env.agent._lock:
            env.cabin.signal_locked("tilt", 1.0, env.clock.boot, env.clock.wall)
        env.cabin_run(20)
        assert env.cabin.st["events"] == [] and runner.photos() == []
        assert env.view()["state"] == "idle"
        status, out = env.peer.req("POST", "/v1/park/event", {"kind": "door"})
        assert status == 200 and out["accepted"] is False
        assert env.cabin.st["events"] == []


def blinker(seconds, low=0.5, high=6.0, still=True):
    """Hazard lights / a tow truck's beacon next to the car: the light flips
    every 0.4 s, the car itself does not move."""
    vecs = P.quiet(int(seconds * 10), seed=11)
    return [(v, high if (i // 4) % 2 else low) for i, v in enumerate(vecs)]


def sweeps(n, gap_s=15.0, low=0.5, high=8.0):
    """``n`` headlight sweeps (1 s bright) ``gap_s`` apart, the car still."""
    out = []
    for k in range(n):
        out += quiet(int(gap_s * 10) - 10, low, seed=20 + k) + quiet(10, high, seed=40 + k)
    return out


class TestFalseAlarmsAndDaylight:
    """Review fixes: light jumps alone never make an event (blinkers,
    beacons, lightning, passing headlights); motion alone does, after about
    20 s of rocking (the cabin's own 10 s motion rhythm), even in a bright
    cabin where the lamp gives no x5 jump."""

    def test_headlight_sweeps_without_motion_do_nothing(self, env, runner):
        env.arm()
        env.stream(quiet(70, 0.5) + sweeps(4))
        lights = [t for t, k in env.cabin._comb._sig if k == "light"]
        assert len(lights) == 4                       # every sweep WAS a light jump
        env.cabin_run(5)
        assert env.cabin.st["events"] == [] and runner.su_calls == []
        assert runner.photos() == []
        env.until_alarm(120)
        assert runner.sms == [] and env.guard.st["pending"] is None

    def test_hazard_lights_alongside_do_nothing(self, env, runner):
        env.arm()
        env.stream(quiet(70, 0.5) + blinker(40))
        assert len([k for _t, k in env.cabin._comb._sig if k == "light"]) == 4   # 1 per 10 s
        env.cabin_run(5)
        assert env.cabin.st["events"] == [] and runner.su_calls == []
        assert runner.photos() == []
        env.until_alarm(120)
        assert runner.sms == []

    def test_daylight_rocking_takes_photos(self, env, runner):
        env.arm()
        env.stream(quiet(70, 300.0) + shake(400, 300.0) + quiet(30, 300.0))
        assert len(env.cabin.st["events"]) == 1, env.cabin.st
        ev = env.event()
        assert ev["reasons"] == ["shake"] and ev["weak"] is True
        pend = env.guard.st["pending"]
        assert pend["kind"] == "shake"                    # the parking guard waits as before
        assert pend["deadline"] == pytest.approx(pend["wall"] + 90)
        t0 = env.clock.boot
        taken = []
        runner.on_photo = lambda path: taken.append(round(env.clock.boot - t0, 1))
        env.cabin_run(12)
        assert taken == [0.0, 3.0, 6.0]
        env.until_alarm(55)
        texts = runner.sms_texts()
        assert len(texts) == 2 and texts[0] == texts[1]            # one SMS per number
        # motion only: the parking guard's wording, with the photos
        assert texts[0].startswith("ALFA 156: ALARM wstrzas albo kolysanie ")
        assert "Zdjecia: 3. Pozycja: " in texts[0] and set(texts[0]) <= GSM7
        assert "RUCH W KABINIE" not in texts[0]
        assert env.guard.st["pending"] is None                     # covered
        env.until_alarm(60)
        assert len(runner.sms_texts()) == 2

    def test_two_short_shakes_15_s_apart_are_not_enough(self, env, runner):
        env.arm()
        env.stream(quiet(70, 300.0) + shake(15, 300.0) + quiet(135, 300.0)
                   + shake(15, 300.0) + quiet(30, 300.0))
        assert env.cabin.st["events"] == []
        env.cabin_run(5)
        assert runner.photos() == []

    def test_park_rhythm_is_unchanged_and_the_cabin_has_its_own(self):
        det = A.MotionDetector(0.5, 6.0)
        t = 0.0
        for v in P.quiet(100):
            det.feed(t, *v)
            t += 0.1
        park, cabin = [], []
        for i in range(1000):                                      # 100 s of rocking
            ev = det.feed(t, 0.5 * math.sin(2 * math.pi * 2 * i / 10.0), 0.0, 9.81)
            if ev:
                park.append(t)
            if det.cabin_shake is not None:
                cabin.append(t)
            t += 0.1
        assert len(park) == 4                                      # at most 1 per 30 s
        assert all(b - a >= det.COOLDOWN_S for a, b in zip(park, park[1:]))
        assert len(cabin) >= 9                                     # 1 per 10 s
        assert all(b - a >= A.CABIN_SHAKE_COOLDOWN_S for a, b in zip(cabin, cabin[1:]))
        assert det.feed(t, 0.0, 0.0, 9.81) is None and det.cabin_shake is None


class TestHeadline:
    """Review fix: "RUCH W KABINIE" only with a cabin-only signal (light,
    door); a tilt or motion alone keeps the parking guard's wording."""

    def test_texts(self):
        tilt = A.cabin_alarm_text("ALFA 156", ["shake", "tilt"], False, P.T0, 3, None,
                                  time.gmtime)
        assert tilt.startswith("ALFA 156: ALARM przechyl (podnosnik albo holowanie) ")
        assert tilt.endswith(". Zdjecia: 3. Pozycja: nieznana (brak GPS)")
        shake = A.cabin_alarm_text("ALFA 156", ["shake", "power"], True, P.T0, 0, None,
                                   time.gmtime)
        assert shake.startswith("ALFA 156: ALARM wstrzas albo kolysanie ")
        door = A.cabin_alarm_text("ALFA 156", ["door", "tilt"], False, P.T0, 2, None,
                                  time.gmtime)
        assert door.startswith("ALFA 156: RUCH W KABINIE ") and "(drzwi+przechyl)" in door
        for text in (tilt, shake, door):
            assert set(text) <= GSM7 and A.sms_segments(text) <= 2

    def test_a_jack_from_the_stream_is_not_someone_inside(self, env, runner):
        env.arm()
        tilt = [(v, 300.0) for v in P.tilted(60, 2.0, seed=3)]
        env.stream(quiet(70, 300.0) + tilt + quiet(20, 300.0))
        ev = env.event()
        assert ev is not None and "tilt" in ev["reasons"] and ev["outcome"] == "pending"
        env.cabin_run(12)
        env.until_alarm(55)
        texts = runner.sms_texts()
        assert len(texts) == 2 and texts[0] == texts[1]
        assert texts[0].startswith("ALFA 156: ALARM przechyl (podnosnik albo holowanie) ")
        assert "Zdjecia: 3." in texts[0] and "RUCH W KABINIE" not in texts[0]
        # the parking guard's own record stays (not "ruch w kabinie")
        assert env.guard.st["last_event"]["kind"] in ("tilt", "shake")

    def test_light_mode_leaves_tilt_to_the_parking_guard(self, env, runner):
        env.arm()
        env.guard._light = True
        env.guard._det_q.put(("tilt", 1.5, env.clock.boot, True, True))
        env.guard._handle_detections()
        assert env.cabin.st["events"] == []                 # no event, no series budget
        assert env.guard.st["pending"]["kind"] == "tilt"
        env.until_alarm(95)
        texts = runner.sms_texts()
        assert len(texts) == 2
        assert texts[0].startswith("ALFA 156: ALARM przechyl (podnosnik albo holowanie) ")
        assert "Zdjecia" not in texts[0]                    # the plain parking guard alarm

    def test_light_mode_still_takes_the_door_signal(self, env, runner):
        env.arm()
        env.guard._light = True
        status, out = env.peer.req("POST", "/v1/park/event", {"kind": "door"})
        assert status == 200 and out["accepted"] is True
        env.cabin_run(12)
        assert runner.photos() == [] and env.event()["camera"] == "light_mode"
        env.until_alarm(55)
        texts = runner.sms_texts()
        assert len(texts) == 2 and "RUCH W KABINIE" in texts[0]
        assert "(drzwi). Zdjecia: 0." in texts[0]


class TestShorterParkWindow:
    """Review fix: parking_guard.entry_s shorter than the cabin's window —
    the cabin adopts the earlier deadline, still one SMS (with photos)."""

    def test_one_sms_with_photos_at_the_park_deadline(self, tmp_path, clock, runner, spawn):
        env = CabinEnv(tmp_path, clock, runner, spawn, park_entry_s=30)
        env.arm()
        env.stream(lamp_and_seat())
        ev = env.event()
        pend = env.guard.st["pending"]
        assert ev["outcome"] == "pending" and pend["kind"] == "shake"
        assert env.view()["entry_until"] == int(pend["deadline"])          # 30 s, not 60
        status, park = env.peer.req("GET", "/v1/park")
        assert status == 200 and park["entry_until"] == int(pend["deadline"])
        env.cabin_run(12)
        assert len(runner.photos()) == 3
        env.until_alarm(20)                                  # past the 30 s deadline
        texts = runner.sms_texts()
        assert len(texts) == 2 and "RUCH W KABINIE" in texts[0] and "Zdjecia: 3." in texts[0]
        assert env.event()["outcome"] == "alarm" and env.guard.st["pending"] is None
        env.until_alarm(120)
        assert len(runner.sms_texts()) == 2

    def test_a_door_event_shows_in_the_park_row(self, env):
        env.arm()
        env.peer.req("POST", "/v1/park/event", {"kind": "door"})
        assert env.guard.st["pending"] is None
        status, park = env.peer.req("GET", "/v1/park")
        assert status == 200 and park["entry_until"] == int(env.event()["deadline"])


class TestLightThresholds:
    """Plan gap: the light jump thresholds are config keys (calibration in
    the log_only week), applied at once."""

    def test_detector_uses_its_thresholds(self):
        values = [1.0] * 30 + [4.5] * 30                      # x4.5, +3.5 lux
        assert TestLightDetector().feed(A.LightDetector(), values) == []
        det = A.LightDetector(ratio=3.0, delta=2.0)
        assert TestLightDetector().feed(det, values) == [(3.0, ("light", 4.5))]

    def test_config_keys_are_pushed_and_applied(self, env):
        assert (env.cabin.light.ratio, env.cabin.light.delta) == (5.0, 5.0)
        status, _out = env.peer.req("PUT", "/v1/config", P.park_config(
            toggles=toggles(), cabin_light_ratio=3.0, cabin_light_lux=2.555))
        assert status == 200
        assert (env.cabin.light.ratio, env.cabin.light.delta) == (3.0, 2.56)
        env.arm()
        assert (env.cabin.light.ratio, env.cabin.light.delta) == (3.0, 2.56)

    def test_bad_values_are_refused(self):
        for bad in ({"cabin_light_ratio": 1.5}, {"cabin_light_ratio": 51},
                    {"cabin_light_ratio": "5"}, {"cabin_light_lux": 0.5},
                    {"cabin_light_lux": float("inf")}, {"cabin_light_lux": True}):
            assert A.normalize_config(dict(P.park_config(), **bad), strict=True)[0] is None, bad


class TestOwnerProof:
    def start(self, env):
        env.arm()
        env.stream(lamp_and_seat())
        env.cabin_run(12)
        assert len(env.files()) == 3

    def test_bcm_disarm_in_the_window_deletes_the_photos(self, env, runner):
        self.start(env)
        status, out = env.peer.req("POST", "/v1/park/disarm", {})
        assert status == 200 and out["state"] == "disarmed"
        env.cabin_run(2)
        assert env.files() == []
        ev = env.event()
        assert ev["outcome"] == "owner" and ev["photos"] == []
        env.until_alarm(120)
        assert runner.sms == []
        assert env.guard.st["pending"] is None and env.view()["state"] == "idle"

    def test_totp_code_in_the_window_deletes_the_photos(self, env, runner):
        self.start(env)
        code = A.totp_code(P.RFC_KEY, int(env.clock.wall // 30))
        status, out = env.peer.req("POST", "/v1/park/disarm", {"code": code})
        assert status == 200, out
        env.cabin_run(2)
        assert env.files() == [] and env.event()["outcome"] == "owner"
        env.until_alarm(120)
        assert runner.sms == []

    def test_proof_in_the_middle_of_the_series(self, env, runner):
        env.arm()
        env.stream(lamp_and_seat())

        def disarm(_path):
            if len(runner.photo_paths) == 1:
                env.peer.req("POST", "/v1/park/disarm", {})

        runner.on_photo = disarm
        env.cabin_run(15)
        assert len(runner.photos()) == 1                 # the series stopped
        assert runner.su_calls[-1] == A.SLEEP_COMMAND     # the screen goes off again
        assert env.files() == [] and env.event()["outcome"] == "owner"

    def test_door_signal_never_disarms(self, env, runner):
        env.arm()
        status, out = env.peer.req("POST", "/v1/park/event", {"kind": "door"})
        assert status == 200 and out["accepted"] is True and out["state"] == "pending"
        assert env.event()["reasons"] == ["door"]
        for _ in range(5):                                  # BCM keeps polling
            assert env.peer.req("GET", "/v1/health")[0] == 200
        env.cabin_run(12)
        assert len(runner.photos()) == 3
        assert env.guard.st["state"] == "armed"
        env.until_alarm(55)
        texts = runner.sms_texts()
        assert len(texts) == 2 and "(drzwi)" in texts[0] and "Zdjecia: 3." in texts[0]
        assert len(env.files()) == 3                      # an alarm keeps its photos

    def test_event_endpoint_validation(self, env):
        env.arm()
        assert env.peer.req("POST", "/v1/park/event", {"kind": "window"})[0] == 400
        assert env.peer.req("POST", "/v1/park/event", {"kind": "door", "x": 1})[0] == 400
        assert env.peer.req("POST", "/v1/park/event", {"kind": "door"}, sign=False)[0] == 401
        assert env.cabin.st["events"] == []
        env.peer.req("PUT", "/v1/config", P.park_config(toggles=toggles(cabin_watch=False)))
        assert env.peer.req("POST", "/v1/park/event", {"kind": "door"}) == \
            (409, {"error": "cabin_watch_off"})

    def test_low_battery_disarm_sends_the_cabin_alarm_at_once(self, env, runner):
        self.start(env)
        env.runner.battery = dict(env.runner.battery, percentage=12)
        env.guard._kick = True
        env.step(2)
        env.send()
        texts = runner.sms_texts()
        assert any("RUCH W KABINIE" in t for t in texts), texts
        assert not any("ALARM wstrzas" in t for t in texts)        # one alarm, not two
        assert env.event()["outcome"] == "alarm" and len(env.files()) == 3

    def test_power_back_extends_the_window_and_is_named(self, env, runner):
        env.arm()
        env.runner.battery = dict(env.runner.battery, plugged="UNPLUGGED")
        env.guard._kick = True
        env.step()
        env.stream(lamp_and_seat())
        env.cabin_run(12)
        env.runner.battery = dict(env.runner.battery, plugged="PLUGGED_USB")   # ignition
        env.guard._kick = True
        env.step()
        assert env.guard.st["restored_wall"] is not None
        env.until_alarm(70)                     # past 60 s: still waiting (grace 3 min)
        assert runner.sms == [] and env.event()["outcome"] == "pending"
        env.until_alarm(150)
        texts = runner.sms_texts()
        assert len(texts) == 2 and "(swiatlo+ruch+zasilanie)" in texts[0]
        assert not any("zasilanie wrocilo" in t for t in texts)   # covered by this SMS


class TestLimits:
    def signal(self, env, kind="tilt"):
        with env.agent._lock:
            env.cabin.signal_locked(kind, 1.0, env.clock.boot, env.clock.wall)

    def test_one_series_per_10_min_and_6_per_day(self, env, runner, monkeypatch):
        env.arm()
        self.signal(env)
        env.cabin_run(12)
        assert len(runner.photos()) == 3
        env.until_alarm(55)
        env.clock.advance(120)
        self.signal(env)                                    # 3 min later
        env.cabin_run(12)
        assert len(env.cabin.st["events"]) == 1 and len(runner.photos()) == 3
        for _ in range(8):
            env.clock.advance(601)
            env.cabin_run(1)
            self.signal(env)
            env.cabin_run(12)
            env.until_alarm(55)
        assert len(env.cabin.st["events"]) == 6              # the 7th and later: limit
        assert len(runner.photos()) == 18                   # 3 photos per series
        # a tilt alone keeps the parking guard's wording (with the photos)
        assert len([t for t in runner.sms_texts()
                    if "ALARM przechyl (podnosnik albo holowanie)" in t
                    and "Zdjecia: 3." in t]) == 6 * 2
        assert not any("RUCH W KABINIE" in t for t in runner.sms_texts())

    def test_owner_cancelled_series_do_not_count(self, env, runner):
        env.arm()
        for _ in range(3):
            self.signal(env)
            env.cabin_run(12)
            env.peer.req("POST", "/v1/park/disarm", {})
            env.arm()
            env.clock.advance(5)
        assert [e["outcome"] for e in env.cabin.st["events"]] == ["owner"] * 3
        self.signal(env)
        assert env.event()["outcome"] == "pending"

    def test_shared_alarm_budget_with_the_parking_guard(self, env, runner):
        env.arm()
        with env.agent._lock:
            env.guard._alarm_locked("tilt", 1.0, env.clock.wall, env.clock.wall)
        env.step(2)
        env.send()
        assert len(runner.sms_texts()) == 2                 # the parking guard's alarm
        env.clock.advance(60)
        self.signal(env, "door")
        env.cabin_run(12)
        env.until_alarm(55)
        assert env.event()["outcome"] == "limited"          # same car, same 10 min
        assert len(runner.sms_texts()) == 2

    def test_cabin_sms_queues_behind_the_crash_sms(self, env, runner):
        env.arm()
        self.signal(env, "door")
        env.clock.advance(65)
        env.step(3)                                 # the alarm job queues the cabin SMS
        assert [d["kind"] for d in env.agent.meta["park_sms"]] == ["park_alarm"]
        status, out = env.peer.req("POST", "/v1/crash", {
            "event_id": "abc", "countdown_s": 15, "event_ts": int(env.clock.wall),
            "lat": None, "lon": None})
        assert status == 200, out
        env.clock.advance(16)
        assert [d["kind"] for d, _ev in env.agent._deliveries()][0] == "park_alarm"
        env.send()
        texts = runner.sms_texts()
        # the crash SMS goes first even though the cabin SMS was queued earlier
        assert texts[0].startswith("ALFA 156: MOZLIWY WYPADEK"), texts
        assert sum("RUCH W KABINIE" in t for t in texts) == 2

    def test_log_only_photos_but_no_sms(self, tmp_path, clock, runner, spawn):
        env = CabinEnv(tmp_path, clock, runner, spawn, park_log_only=True)
        env.arm()
        env.stream(lamp_and_seat())
        env.cabin_run(12)
        assert len(runner.photos()) == 3
        env.until_alarm(150)
        assert runner.sms == [] and env.event()["outcome"] == "logged"
        assert env.guard.st["last_event"] == {"kind": "cabin", "ts": int(env.event()["wall"]),
                                              "value": 3.0, "logged_only": True}


class TestGuards:
    @pytest.mark.parametrize("battery,block", [
        ({"temperature": -5.0}, "cold"),
        ({"temperature": 46.0}, "hot"),
        ({"temperature": 41.0, "plugged": "PLUGGED_USB"}, "charging_hot"),
        ({"temperature": 25.0, "percentage": 25}, "low_battery"),
        ({"temperature": None}, "no_temp"),
    ])
    def test_no_camera_but_the_alarm_still_goes(self, env, runner, battery, block):
        env.runner.battery = dict(env.runner.battery, **dict({"plugged": "UNPLUGGED"},
                                                             **battery))
        env.guard._battery_at = None
        env.arm()
        with env.agent._lock:
            env.cabin.signal_locked("door", None, env.clock.boot, env.clock.wall)
        env.cabin_run(12)
        assert runner.photos() == [] and runner.su_calls == []
        assert env.event()["camera"] == block and env.view()["camera"] == block
        env.until_alarm(55)
        texts = runner.sms_texts()
        assert len(texts) == 2 and "Zdjecia: 0." in texts[0]

    def test_light_mode_has_no_camera(self, env, runner):
        env.arm()
        env.guard._light = True
        with env.agent._lock:
            env.cabin.signal_locked("door", None, env.clock.boot, env.clock.wall)
        env.cabin_run(12)
        assert runner.photos() == [] and env.event()["camera"] == "light_mode"

    def test_no_front_camera(self, env, runner):
        runner.cameras = [{"id": "0", "facing": "back"}]
        env.arm()
        with env.agent._lock:
            env.cabin.signal_locked("door", None, env.clock.boot, env.clock.wall)
        env.cabin_run(12)
        assert runner.photos() == [] and env.event()["camera"] == "no_front_camera"
        info = [c for c in runner.calls if c[0] == "termux-camera-info"]
        assert len(info) == 1

    def test_front_id_asked_once(self, env, runner):
        env.arm()
        for _ in range(2):
            with env.agent._lock:
                env.cabin.signal_locked("door", None, env.clock.boot, env.clock.wall)
            env.cabin_run(12)
            env.peer.req("POST", "/v1/park/disarm", {})
            env.arm()
        assert len([c for c in runner.calls if c[0] == "termux-camera-info"]) == 1
        assert len(runner.photos()) == 6

    def test_a_symlinked_photo_dir_is_refused(self, env, runner, tmp_path):
        target = tmp_path / "elsewhere"
        target.mkdir()
        os.symlink(target, Path(env.dir, "cabin"))
        env.arm()
        with env.agent._lock:
            env.cabin.signal_locked("door", None, env.clock.boot, env.clock.wall)
        env.cabin_run(12)
        assert runner.photos() == [] and env.event()["camera"] == "bad_path"
        assert list(target.iterdir()) == []

    def test_failed_photos_leave_nothing(self, env, runner):
        runner.photo_fail = True
        env.arm()
        with env.agent._lock:
            env.cabin.signal_locked("door", None, env.clock.boot, env.clock.wall)
        env.cabin_run(12)
        assert len(runner.photos()) == 3 and env.files() == []
        assert env.event()["photos"] == []


# ── EXIF ─────────────────────────────────────────────────────────────────

class TestExif:
    def test_pillow_reencode_has_no_exif(self, env, runner):
        big = cabin_image(size=(2000, 1500))
        runner.photo_data = [jpeg(big)]
        assert Image.open(io.BytesIO(runner.photo_data[0])).getexif()   # the camera's EXIF
        env.arm()
        with env.agent._lock:
            env.cabin.signal_locked("door", None, env.clock.boot, env.clock.wall)
        env.cabin_run(12)
        for name in env.files():
            with Image.open(Path(env.dir, "cabin", name)) as im:
                assert not im.getexif() and "exif" not in im.info
                assert max(im.size) <= A.CABIN_REENCODE_SIDE

    def test_stdlib_strip_without_pillow(self, tmp_path, clock, runner, spawn):
        env = CabinEnv(tmp_path, clock, runner, spawn, pillow=None)
        env.arm()
        with env.agent._lock:
            env.cabin.signal_locked("door", None, env.clock.boot, env.clock.wall)
        env.cabin_run(12)
        names = env.files()
        assert len(names) == 3
        for name in names:
            data = Path(env.dir, "cabin", name).read_bytes()
            assert b"Exif" not in data and b"Redmi" not in data
            with Image.open(io.BytesIO(data)) as im, Image.open(io.BytesIO(EMPTY)) as orig:
                assert not im.getexif()
                assert im.tobytes() == orig.tobytes()         # the same pixels, bit for bit
        assert env.event()["analysis"]["verdict"] == "skipped"

    def test_strip_segments(self):
        out = A.strip_jpeg_metadata(EMPTY)
        assert out is not None and out.startswith(b"\xff\xd8") and b"Exif" not in out
        assert A.strip_jpeg_metadata(out) == out
        for bad in (b"", b"\xff\xd8", b"GIF89a....", EMPTY[:20], b"\xff\xd8\xff\xe1\xff\xff",
                    None, "text"):
            assert A.strip_jpeg_metadata(bad) is None

    def test_a_broken_file_is_kept_untouched(self, tmp_path, clock, runner, spawn):
        env = CabinEnv(tmp_path, clock, runner, spawn, pillow=None)
        runner.photo_data = [b"\xff\xd8\xff\xe1\x00\x10not a real jpeg"]
        env.arm()
        with env.agent._lock:
            env.cabin.signal_locked("door", None, env.clock.boot, env.clock.wall)
        env.cabin_run(12)
        names = env.files()
        assert len(names) == 3
        assert Path(env.dir, "cabin", names[0]).read_bytes() == runner.photo_data[0]


# ── retention ────────────────────────────────────────────────────────────

class TestRetention:
    def make(self, env, name, age_h, size=1000):
        d = Path(env.dir, "cabin")
        d.mkdir(mode=0o700, exist_ok=True)
        p = d / name
        p.write_bytes(b"x" * size)
        t = env.clock.wall - age_h * 3600
        os.utime(p, (t, t))
        return p

    def test_72_hours(self, env):
        old = self.make(env, "cab_" + "a" * 16 + "_0.jpg", 73)
        new = self.make(env, "cab_" + "b" * 16 + "_0.jpg", 71)
        ref = self.make(env, "ref_dark.png", 80)
        tmp = self.make(env, ".cab_" + "c" * 16 + "_0.jpg.tmp", 2)
        foreign = self.make(env, "notes.txt", 500)
        env.cabin.cleanup()
        assert not old.exists() and not ref.exists() and not tmp.exists()
        assert new.exists() and foreign.exists()
        assert env.cabin._disk[0] == 1

    def test_200_mb_oldest_first(self, env, monkeypatch):
        monkeypatch.setattr(A, "CABIN_MAX_BYTES", 2500)
        a = self.make(env, "cab_" + "a" * 16 + "_0.jpg", 30)
        b = self.make(env, "cab_" + "b" * 16 + "_0.jpg", 20)
        c = self.make(env, "cab_" + "c" * 16 + "_0.jpg", 10)
        env.cabin.cleanup()
        assert not a.exists() and b.exists() and c.exists()

    def test_symlinks_are_never_followed(self, env, tmp_path):
        outside = tmp_path / "precious.jpg"
        outside.write_bytes(b"keep")
        t = env.clock.wall - 100 * 3600
        os.utime(outside, (t, t))
        d = Path(env.dir, "cabin")
        d.mkdir(mode=0o700)
        link = d / ("cab_" + "d" * 16 + "_0.jpg")
        os.symlink(outside, link)
        env.cabin.cleanup()
        with env.agent._lock:
            env.cabin.st["events"].append({
                "id": "d" * 16, "wall": env.clock.wall, "deadline": env.clock.wall,
                "reasons": ["door"], "weak": False, "lux": None, "photos": [link.name],
                "clean": True, "outcome": "owner", "log_only": False, "analysis": None,
                "camera": ""})
        env.cabin._purge_event("d" * 16)
        assert outside.read_bytes() == b"keep" and link.is_symlink()

    def test_event_photo_lists_follow_the_disk(self, env, runner):
        env.arm()
        with env.agent._lock:
            env.cabin.signal_locked("door", None, env.clock.boot, env.clock.wall)
        env.cabin_run(12)
        env.until_alarm(55)
        assert len(env.event()["photos"]) == 3
        env.clock.advance(73 * 3600)
        for name in env.files():
            p = Path(env.dir, "cabin", name)
            os.utime(p, (env.clock.wall - 73 * 3600, env.clock.wall - 73 * 3600))
        env.cabin_run(1)
        assert env.files() == [] and env.event()["photos"] == []
        assert env.view()["photos_n"] == 0


# ── analysis ─────────────────────────────────────────────────────────────

class TestAnalysis:
    def frames(self, pil, *images, tmp_path, tag="f"):
        out = []
        for i, img in enumerate(images):
            p = tmp_path / f"{tag}{i}.jpg"
            p.write_bytes(jpeg(img))
            out.append(A.pil_prepare(pil, str(p)))
        return out

    def test_person_vs_empty_cabin(self, tmp_path):
        pil = A.load_pillow()
        rnd = random.Random(1)
        empty, person = self.frames(pil, cabin_image(), cabin_image(person=True),
                                    tmp_path=tmp_path)
        noisy = cabin_image()
        px = noisy.load()
        for _ in range(20000):
            x, y = rnd.randrange(640), rnd.randrange(480)
            v = px[x, y][0] + rnd.randint(-8, 8)
            px[x, y] = (v, v, v)
        (noisy_f,) = self.frames(pil, noisy, tmp_path=tmp_path, tag="noisy")
        assert A.pil_change_pct(pil, empty, person, []) > 10.0
        assert A.pil_change_pct(pil, empty, noisy_f, []) < 1.0
        # auto exposure: the same cabin 30% darker is not a change
        (darker,) = self.frames(pil, cabin_image(brightness=0.7), tmp_path=tmp_path,
                                tag="dark")
        assert A.pil_change_pct(pil, empty, darker, []) < 3.0

    def test_window_mask(self, tmp_path):
        pil = A.load_pillow()
        empty, window = self.frames(pil, cabin_image(), cabin_image(window_change=True),
                                    tmp_path=tmp_path)
        assert A.pil_change_pct(pil, empty, window, []) > 3.0
        assert A.pil_change_pct(pil, empty, window, [[0, 0, 15, 100]]) < 0.5

    def test_reference_burst_dark_and_mask_in_the_flow(self, env, runner):
        cdir = Path(env.dir, "cabin")
        # a reference of the "dim" class, taken at arming (lamp on: 40 lux)
        runner.photo_data = [EMPTY]
        env.arm(ref=True)
        env.stream(quiet(70, 40.0))
        env.cabin_run(40)
        assert (cdir / "ref_dim.png").exists() and not (cdir / "ref_raw.jpg").exists()
        assert stat.S_IMODE((cdir / "ref_dim.png").stat().st_mode) == 0o600
        with Image.open(cdir / "ref_dim.png") as im:
            assert im.size == A.CABIN_FRAME and im.mode == "L"
        assert len(runner.photos()) == 1
        # an intruder: same class, compared with the reference
        runner.photo_data = [PERSON]
        with env.agent._lock:
            env.cabin.signal_locked("door", None, env.clock.boot, env.clock.wall)
        env.cabin_run(12)
        a = env.event()["analysis"]
        assert a["verdict"] == "change" and a["ref"] == "ref" and a["changed_pct"] > 10
        v = env.view()["last_event"]
        assert v["verdict"] == "change" and v["ref"] == "ref"

    def test_burst_without_a_reference(self, env, runner):
        runner.photo_data = [EMPTY, PERSON, PERSON]
        env.arm()
        with env.agent._lock:
            env.cabin.signal_locked("door", None, env.clock.boot, env.clock.wall)
        env.cabin_run(12)
        a = env.event()["analysis"]
        assert a["ref"] == "burst" and a["verdict"] == "change"

    def test_dark_frames(self, env, runner):
        runner.photo_data = [jpeg(Image.new("RGB", (640, 480), (3, 3, 3)))]
        env.arm()
        with env.agent._lock:
            env.cabin.signal_locked("door", None, env.clock.boot, env.clock.wall)
        env.cabin_run(12)
        assert env.event()["analysis"] == {"verdict": "dark", "changed_pct": None, "ref": None}

    def test_no_reference_photo_in_a_dark_cabin(self, env, runner):
        """Night: the frame would be black anyway — no screen wake, no
        Termux in front, no camera in an empty parked car."""
        env.arm(ref=True)
        env.stream(quiet(70, 0.5))
        env.cabin_run(40)
        assert runner.su_calls == [] and runner.photos() == []
        assert not any(c[0] == "termux-camera-info" for c in runner.calls)
        assert env.files() == []

    def test_no_pillow_no_reference_photo(self, tmp_path, clock, runner, spawn):
        env = CabinEnv(tmp_path, clock, runner, spawn, pillow=None)
        env.arm(ref=True)
        env.stream(quiet(70, 40.0))
        env.cabin_run(40)
        assert runner.photos() == [] and env.view()["pillow"] is False


# ── API, config, sensors, persistence ────────────────────────────────────

class TestApi:
    def test_view_never_carries_photos(self, env, runner):
        env.arm()
        with env.agent._lock:
            env.cabin.signal_locked("door", None, env.clock.boot, env.clock.wall)
        env.cabin_run(12)
        status, data, _h = env.agent.handle("GET", "/v1/cabin", *self._signed(env, "GET",
                                                                             "/v1/cabin"))
        assert status == 200 and len(data) < 4096
        out = json.loads(data)
        assert set(out) == {"state", "camera", "light_sensor", "lux", "pillow", "log_only",
                            "entry_until", "photos_n", "photos_mb", "events_today",
                            "last_event", "events"}
        assert out["photos_n"] == 3 and out["state"] == "pending" and out["camera"] == "ok"
        assert out["entry_until"] == int(env.event()["deadline"])
        assert b".jpg" not in data and b"\xff\xd8" not in data and b"/data" not in data
        assert out["last_event"]["reasons"] == ["door"] and out["last_event"]["photos"] == 3

    @staticmethod
    def _signed(env, method, path):
        env.peer.nonce += 1
        ts = int(env.clock.wall)
        sig = A.sign(P.KEY, A.request_message(method, path, ts, env.peer.nonce, b""))
        return ({"X-BCM-Ts": str(ts), "X-BCM-Nonce": str(env.peer.nonce), "X-BCM-Sig": sig},
                b"")

    def test_unsigned_get_is_refused(self, env):
        status, data, hdrs = env.agent.handle("GET", "/v1/cabin", {}, b"")
        assert status == 401 and "X-BCM-Sig" not in hdrs


class TestConfig:
    def test_cabin_keys(self):
        norm, err = A.normalize_config(dict(P.park_config(), cabin_entry_s=45,
                                            cabin_diff_pct=2.555,
                                            cabin_mask=[[0, 0, 15, 100], [85, 0, 100, 100]]),
                                       strict=True)
        assert err == "" and norm["cabin_entry_s"] == 45 and norm["cabin_diff_pct"] == 2.56
        assert norm["cabin_mask"] == [[0, 0, 15, 100], [85, 0, 100, 100]]
        for bad in ({"cabin_entry_s": 30}, {"cabin_entry_s": 61}, {"cabin_entry_s": 50.5},
                    {"cabin_diff_pct": 0.1}, {"cabin_diff_pct": float("nan")},
                    {"cabin_mask": [[10, 0, 5, 100]]}, {"cabin_mask": [[0, 0, 101, 100]]},
                    {"cabin_mask": [[0, 0, 10]]}, {"cabin_mask": [[0, 0, 1, 1]] * 5},
                    {"cabin_mask": "left"}, {"cabin_mask": [[True, 0, 1, 1]]}):
            assert A.normalize_config(dict(P.park_config(), **bad), strict=True)[0] is None, bad

    def test_hash_ignores_cabin_keys_while_the_toggle_is_off(self):
        base = A.normalize_config(P.park_config(), strict=True)[0]
        old = {k: v for k, v in base.items() if not k.startswith("cabin_")}
        assert A.config_hash(base) == A.config_hash(old)            # agent 1.2.0 hashes so
        on = dict(base, toggles=dict(base["toggles"], cabin_watch=True))
        assert A.config_hash(on) != A.config_hash(
            {k: v for k, v in on.items() if not k.startswith("cabin_")})


class TestSensors:
    def test_light_sensor_joins_the_stream(self, env, spawn):
        env.arm()
        env.stream(quiet(20, 12.0))
        assert spawn.argvs[0] == ["termux-sensor", "-s", f"{ACCEL},{LIGHT}", "-d", "100"]
        assert env.view()["light_sensor"] == "ok" and env.view()["lux"] == 12.0

    def test_no_light_sensor(self, env, runner, spawn):
        runner.sensors = [ACCEL]
        env.arm()
        env.stream(quiet(20, None))
        assert spawn.argvs[0] == ["termux-sensor", "-s", ACCEL, "-d", "100"]
        assert env.view()["light_sensor"] == "none"

    def test_pick_light(self):
        assert A.pick_light(["Light Uncalibrated", "stk3x3x Light/Proximity", "TCS Light"]) \
            == "TCS Light"
        assert A.pick_light(["stk3x3x Light/Proximity"]) == "stk3x3x Light/Proximity"
        assert A.pick_light(["Light flicker", "a,Light", ACCEL]) is None
        assert A.pick_light(None) is None

    def test_light_values_never_become_acceleration(self):
        p = A.SensorParser(ACCEL, LIGHT)
        only_light = json.dumps({LIGHT: {"values": [9.0, 0.0, 0.0]}})
        assert p.feed_items(only_light) == [("l", 9.0)]
        both = json.dumps({ACCEL: {"values": [0, 0, 9.8]}, LIGHT: {"values": [3]}})
        assert p.feed_items(both) == [("a", (0.0, 0.0, 9.8)), ("l", 3.0)]
        assert p.feed_line(both) == [(0.0, 0.0, 9.8)]
        bad = json.dumps({ACCEL: {"values": [0, 0, 9.8]}, LIGHT: {"values": [-4]}})
        assert p.feed_items(bad) == [("a", (0.0, 0.0, 9.8))]

    def test_toggling_the_cabin_restarts_the_stream(self, env, spawn, monkeypatch):
        monkeypatch.setattr(A, "SENSOR_JOIN_S", 0.2)
        env.arm()
        stuck = P.StuckProc(["termux-sensor"])
        stuck.wait = lambda timeout=None: 0          # ends on SIGTERM
        env.guard._spawn = lambda argv: (spawn.argvs.append(argv), stuck)[1]
        env.guard._manage_sensor()
        assert spawn.argvs[-1][2] == f"{ACCEL},{LIGHT}"
        env.peer.req("PUT", "/v1/config", P.park_config(toggles=toggles(cabin_watch=False)))
        fresh = P.StuckProc(["termux-sensor"])
        env.guard._spawn = lambda argv: (spawn.argvs.append(argv), fresh)[1]
        stuck.stdout.q.put(None)                      # its reader ends (EOF)
        env.guard._manage_sensor()
        assert spawn.argvs[-1] == ["termux-sensor", "-s", ACCEL, "-d", "100"]
        assert stuck.terminate_calls == 1             # no backoff: restarted at once
        fresh.stdout.q.put(None)
        env.guard._reader.join(timeout=5)


class TestPersistence:
    def test_a_pending_event_survives_a_restart(self, tmp_path, clock, runner, spawn):
        env = CabinEnv(tmp_path, clock, runner, spawn)
        env.arm()
        with env.agent._lock:
            env.cabin.signal_locked("door", None, env.clock.boot, env.clock.wall)
        env.cabin_run(12)
        eid = env.event()["id"]
        again = A.Agent(env.dir, runner=runner, clock=lambda: clock.boot,
                        wall=lambda: clock.wall, localtime=time.gmtime, spawn=spawn,
                        mktime=calendar.timegm, pillow=None)
        cabin = again.park.cabin
        assert cabin.st["events"][-1]["id"] == eid
        assert cabin.st["events"][-1]["outcome"] == "pending"
        assert len(cabin.st["events"][-1]["photos"]) == 3
        clock.advance(55)
        for _ in range(3):
            again.park.step()
        for _ in range(40):
            if again.step() > 0:
                break
        assert cabin.st["events"][-1]["outcome"] == "alarm"
        assert any("RUCH W KABINIE" in t for t in runner.sms_texts())

    def test_damaged_state_is_ignored(self, tmp_path, clock, runner, spawn):
        d = tmp_path / "bcm_agent"
        d.mkdir(mode=0o700)
        (d / A.CABIN_FILE).write_text(json.dumps({"events": [
            {"id": "../../etc", "wall": 1, "deadline": 1, "outcome": "pending"},
            {"id": "a" * 16, "wall": P.T0, "deadline": P.T0, "outcome": "alarm",
             "photos": ["../../secret", "cab_" + "b" * 16 + "_0.jpg",
                        "cab_" + "a" * 16 + "_1.jpg"], "reasons": ["door", "evil"]},
        ]}))
        env = CabinEnv(tmp_path, clock, runner, spawn)
        events = env.cabin.st["events"]
        assert len(events) == 1 and events[0]["photos"] == ["cab_" + "a" * 16 + "_1.jpg"]
        assert events[0]["reasons"] == ["door"]
