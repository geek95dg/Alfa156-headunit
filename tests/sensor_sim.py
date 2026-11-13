"""A deterministic car + phone simulator for the sensor and crash tests.

Not a test module (pytest collects ``test_*.py`` only). It produces what the
phone would send — SensorServer JSON frames with sensor timestamps — from a
specific force given in the CAR frame (x forward, y left, z up; at rest the
accelerometer reads +1 g on z), rotated into the phone's axes the way the
plan G mount holds it (under the headliner, screen down, top edge towards
the windshield, tilted with the roof line), with seeded noise and the
phone's ±range clipping. Every sample advances one :class:`FakeClock`
shared by the sensor module and the crash detector, so the whole chain
(frame → PhoneSensors → phone.g_force → CrashDetector) runs synchronously
and deterministically on the in-process bus.
"""

from __future__ import annotations

import json
import math
import random

G0 = 9.80665
WALL_OFFSET = 1767225600.0 - 1000.0     # wall = 2026-01-01 at mono 1000


class FakeClock:
    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def mono(self) -> float:
        return self.t

    def wall(self) -> float:
        return self.t + WALL_OFFSET

    def advance(self, seconds: float) -> None:
        self.t += seconds


def _rot_x(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return ((1, 0, 0), (0, c, -s), (0, s, c))


def _rot_z(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return ((c, -s, 0), (s, c, 0), (0, 0, 1))


def _mul(a, b):
    return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3))
                 for i in range(3))


def _apply(m, v):
    return tuple(m[i][0] * v[0] + m[i][1] * v[1] + m[i][2] * v[2] for i in range(3))


#: Car → phone axes of the plan G mount: phone y = car forward, phone x =
#: car right, phone z = car down (screen down), then 12° of roof-line pitch
#: and 3° of yaw so no axis is exactly aligned.
MOUNT = _mul(_rot_x(12.0), _mul(_rot_z(3.0), ((0, -1, 0), (1, 0, 0), (0, 0, -1))))
#: The phone after it fell onto the floor mat (screen up, turned).
ON_FLOOR = _mul(_rot_z(40.0), ((1, 0, 0), (0, 1, 0), (0, 0, 1)))


def accel_frame(values, ts_ns=None, kind="android.sensor.accelerometer") -> str:
    obj = {"type": kind, "values": list(values), "accuracy": 3}
    if ts_ns is not None:
        obj["timestamp"] = ts_ns
    return json.dumps(obj)


def light_frame(lux, ts_ns=None) -> str:
    return accel_frame([lux], ts_ns, kind="android.sensor.light")


def gyro_frame(values, ts_ns=None) -> str:
    return accel_frame(values, ts_ns, kind="android.sensor.gyroscope")


class Drive:
    """Feeds a PhoneSensors object sample by sample and plays GPS on the bus.

    ``speed`` is what GPS reports (km/h; None = no GPS), published at
    ``gps_hz`` as ``gps.position`` + ``gps.speed`` like src/location/gps.py.
    With ``gyro`` every accelerometer sample is preceded by a gyroscope
    frame of ``omega`` (rad/s, car frame) with the same timestamp.
    """

    def __init__(self, sensors, bus, clock: FakeClock, rate_hz: float = 100.0,
                 mount=MOUNT, noise: float = 0.03, range_g: float = 8.0, seed: int = 7,
                 gps_hz: float = 1.0, timestamps: bool = True, gyro: bool = False) -> None:
        self.sensors = sensors
        self.bus = bus
        self.clock = clock
        self.dt = 1.0 / rate_hz
        self.mount = mount
        self.noise = noise
        self.clip = range_g * G0
        self.rng = random.Random(seed)
        self.gps_period = 1.0 / gps_hz
        self.next_gps = clock.t
        self.timestamps = timestamps
        self.gyro = gyro
        self.omega = (0.0, 0.0, 0.0)
        self.speed = None
        self.position = (52.22968, 21.01223)
        self.heading = 90.0

    def sample(self, f_car, noise=None) -> None:
        """One accelerometer sample of specific force ``f_car`` (car frame)."""
        self.sample_phone(_apply(self.mount, f_car), noise, _apply(self.mount, self.omega))

    def sample_phone(self, phone, noise=None, omega_phone=(0.0, 0.0, 0.0)) -> None:
        """One sample given in the PHONE's axes (a phone that is no longer
        in its holder), plus the gyroscope frame when enabled."""
        self.clock.advance(self.dt)
        t = self.clock.t
        sigma = self.noise if noise is None else noise
        vals = [max(-self.clip, min(self.clip, c + self.rng.gauss(0.0, sigma))) for c in phone]
        ts = int(round(t * 1e9)) if self.timestamps else None
        if self.gyro:
            self.sensors.handle_message(gyro_frame(list(omega_phone), ts), t)
        self.sensors.handle_message(accel_frame(vals, ts), t)
        self.sensors.periodic(t)
        if self.speed is not None and t >= self.next_gps:
            self.next_gps = t + self.gps_period
            self.bus.publish("gps.position", {
                "lat": self.position[0], "lon": self.position[1], "speed": self.speed,
                "heading": self.heading, "satellites": 9, "fix": True, "source": "tcp"})
            self.bus.publish("gps.speed", self.speed)

    def hold(self, seconds: float, f_car=(0.0, 0.0, G0), noise=None, speed="keep") -> None:
        if speed != "keep":
            self.speed = speed
        for _ in range(int(round(seconds / self.dt))):
            self.sample(f_car, noise)

    def rest(self, seconds: float) -> None:
        """Parked or waiting at lights: engine idle, tiny vibration."""
        self.hold(seconds, noise=0.05, speed=0.0)

    def cruise(self, kmh: float, seconds: float) -> None:
        """Steady speed on a normal road: vibration too strong for calibration."""
        self.hold(seconds, noise=0.6, speed=float(kmh))

    def brake(self, kmh: float, g: float = 1.0) -> None:
        """Constant deceleration to a standstill; GPS follows (1 s late)."""
        decel = g * G0
        v = kmh / 3.6
        while v > 0:
            v = max(0.0, v - decel * self.dt)
            # GPS reports the speed of its last epoch.
            if self.clock.t + self.dt >= self.next_gps:
                self.speed = round(v * 3.6, 1)
            self.sample((-decel, 0.0, G0), noise=0.4)
        self.speed = 0.0

    def pulse(self, peak_car, duration_s: float, noise: float = 0.4, after_speed=None) -> None:
        """Half-sine pulse of ``peak_car`` (m/s², car frame) on top of 1 g."""
        n = max(1, int(round(duration_s / self.dt)))
        for i in range(n):
            s = math.sin(math.pi * (i + 0.5) / n)
            self.sample((peak_car[0] * s, peak_car[1] * s, G0 + peak_car[2] * s), noise)
        if after_speed is not None:
            self.speed = after_speed

    def barrier(self, kmh: float = 50.0, duration_s: float = 0.1) -> None:
        """Frontal impact: the car sheds ``kmh`` in ``duration_s`` (half
        sine: peak = Δv·π/(2T), ~22 g for 50 km/h in 100 ms — the phone
        clips at its range), with a vertical part of 25 %."""
        a = (kmh / 3.6) * math.pi / (2 * duration_s)
        self.pulse((-a, 0.0, 0.25 * a), duration_s)

    def free_fall(self, seconds: float) -> None:
        self.hold(seconds, f_car=(0.0, 0.0, 0.0), noise=0.05)

    def tumbling_fall(self, seconds: float, reading_g: float = 0.5,
                      omega: float = 10.0) -> None:
        """The phone falls out of the holder spinning: it reads the constant
        centripetal acceleration of its own spin (ω²·r, ``reading_g``) in
        its own axes, not ~0 g, and the gyroscope reads ``omega``."""
        for _ in range(int(round(seconds / self.dt))):
            self.sample_phone((reading_g * G0, 0.0, 0.0), 0.05, (0.0, 0.0, omega))
