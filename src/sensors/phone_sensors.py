"""Accelerometer and light sensor of the car phone, streamed by SensorServer.

Why this exists (plan D3, crash detection of plan F)
----------------------------------------------------
The phone mounted under the headliner (``car_phone``, plan C) has an
accelerometer, a gyroscope and a light sensor the head unit lacks. The open-source
Android app **SensorServer** (umer0586/SensorServer, F-Droid) streams them
as JSON over a WebSocket. This module reads that stream through the adb
forward ``car_phone`` keeps up and turns it into two bus topics:

* ``phone.g_force`` (<= 10 Hz) — what ``src/safety/crash_detect.py`` needs
  to tell an impact from braking, a pothole or a phone that fell;
* ``phone.light_lux`` (<= 2 Hz) — for the later ``auto_brightness``.

It NEVER publishes ``alarm.sensor.*``: the car alarm treats any value there
as a break-in.

Enabled by ``modules.phone_sensors`` only (requires ``car_phone``; off in
code and in the production config).

SensorServer (as documented in its README; checked 2026-11)
-----------------------------------------------------------
* ``ws://<host>:<port>/sensors/connect?types=["android.sensor.accelerometer",
  "android.sensor.gyroscope","android.sensor.light"]`` — one connection,
  several sensors; each text frame is ``{"type": …, "values": […],
  "timestamp": <ns>, "accuracy": n}`` (the README names the ``type`` field
  only in prose — unverified on the phone; a frame without a known ``type``
  is ignored). The gyroscope only serves to recognise a phone that tumbles
  as it falls; when SensorServer closes the connection with an application
  code (4xxx) before the first frame — what it does for a sensor it cannot
  serve (from memory, unverified) — the next attempts ask without it.
* ``timestamp`` is the sensor event time in nanoseconds (Android's
  ``SensorEvent.timestamp``: monotonic, from the phone's boot).
* In the app: **"Local Host"** ON (it then listens on the phone's
  127.0.0.1 only — reachable through ``adb forward``, not over Wi-Fi), port
  8080 (= ``network.car_phone.sensors_remote_port``), and the **sampling
  rate set to 10000 µs (100 Hz)** — the app's default is much slower, and
  below ``crash_detection.min_rate_hz`` (80) the crash path refuses the
  data. Battery optimisation off for the app, start on boot.

The connection
--------------
* Address: 127.0.0.1:<``net.car_phone`` → ``forwards.sensors.local``>,
  used only while that forward is ``ok`` — this module never runs adb (the
  local port is privileged on purpose, see ``car_phone``).
* A small WebSocket client on ``wsproto`` (already a dependency of
  flask-sock) instead of ``simple_websocket.Client``: that one has no
  connect/handshake timeout (a server that accepts and never answers blocks
  the caller forever) and needs a reader thread per connection. Here
  everything runs on the module's ONE worker thread with socket timeouts,
  no compression is offered (no deflate bombs), a message is limited to
  :data:`MAX_FRAME_BYTES` (2 KB; a real frame is ~150 B — bigger ones are
  dropped without being kept in memory) and the handshake to 16 KB.
* Reconnect with backoff 1 s doubling to 60 s; the backoff resets after a
  session that streamed for 30 s, and whenever the forward reappears or
  moves (car_phone re-created it after the phone re-enumerated on USB).
  "Connection refused" on 127.0.0.1 means the forward itself is missing:
  that local retry is capped at :data:`FORWARD_MISSING_RETRY_S` (3 s). No
  accelerometer sample for 1 s → state ``stale``; for 10 s → reconnect
  (light or gyroscope frames alone do not keep a session). A forward that
  car_phone briefly reports as not ``ok`` (one failed ``adb devices``) does
  not end a session that keeps delivering; a changed port or car_phone
  stopping does.

Validation of every frame
-------------------------
JSON object only (``NaN``/``Infinity`` refused), known ``type`` (others
ignored), ``values`` finite numbers (a JSON integer too big for a float is
invalid, never an exception): accelerometer exactly 3, each
``|v| <= 4 × 16 g`` in m/s²; gyroscope exactly 3, each ``|v| <= 35`` rad/s;
light ``values[0]`` in 0..200000 lux. ``timestamp`` an integer >= 0 (else
the arrival time is used). At most :data:`MAX_FRAMES_PER_S` frames (all
types) per second are processed; the rest are dropped, counted, and the
period is flagged ``overrun`` (crash_detect then refuses it — a truncated
second still shows a good rate).

Processing (pure classes, injected clocks — tested without a socket)
--------------------------------------------------------------------
* Time base: the phone's sensor timestamps (batched delivery does not
  distort Δt or the rate), the arrival time when a frame has none — or when
  they turn out implausible on this connection (after 5 s of arrival time
  they advanced by less than half of it: not nanoseconds, or a broken
  app; logged once). A step back or a gap over 2 s restarts the pipeline
  (not the calibration).
* 10 s ring buffer of accelerometer samples; ``rate_hz`` over the last 1 s.
  The windows are trimmed by sensor time AND capped by count
  (:data:`MAX_SENSOR_HZ`), so timestamps that barely advance cannot grow
  them without bound.
* Lag: how much later than the best delivery of the last 10-20 s a sample
  arrived (a backlog after a stall of the phone, adb or TCP) — the
  period's largest is ``lag_ms``; crash_detect adds it to the message age.
* Gravity (:class:`GravityCalibrator`): 0.5 s blocks; a block is "quiet"
  when every axis varies by < 0.35 m/s² (std) and |mean| is within
  0.5 m/s² of 1 g. The reference is the span-weighted mean of 10 s of
  quiet blocks that agree with each other (a block more than 2.5° off
  their running mean restarts the collection), saved atomically to
  ``data/phone_sensors.json`` — a restart keeps it. Quiet blocks feed a
  fast (τ 10 s, live data: the gravity the split subtracts) and a slow
  (τ 60 s; starts AT a loaded reference) low-pass. ``calib_ok`` is True
  once there is a reference and at least 3 s of quiet data this session;
  False while the slow estimate is more than 10° away from the reference
  (the phone moved in its holder — plan G; or the car stood on a very
  steep ramp for minutes), True again below 7°; also False while the fast
  estimate is more than 20° away (re-mounted while BCM was off — flagged
  within seconds; back below 15°). ``phone_sensors.cmd.recalibrate`` (no
  argument) drops the reference and calibrates anew.
* Each sample: linear acceleration = a − gravity (fast estimate; the
  buffer mean until there is one), split into the vertical component
  (along gravity) and the horizontal vector.
* ``phone.g_force`` every 100 ms with samples, covering the samples since
  the previous message::

      {ts, mono, rate_hz, sat, peak_h_g, peak_v_g, dv_h_kmh_150ms,
       dv_window_ms, n_over_g, freefall_ms, calib_ok, lag_ms, overrun}

  ``sat``: any axis >= 0.98 × ``sensors.phone.accel_range_g`` (8 g by
  default; the real range of the phone: ``dumpsys sensorservice``).
  ``dv_h_kmh_150ms``: the largest |Σ a_h·Δt| (vector sum, so vibration
  cancels out) over any ``crash_detection.dv_window_ms`` (150 ms) window
  ending in this period, km/h. ``n_over_g``: the longest run of
  consecutive samples with |a_h| >= ``crash_detection.g_h_threshold``
  reached in this period (runs continue across periods). ``freefall_ms``:
  the longest free fall going on or ended within the last 1 s: |a| < 0.3 g,
  or — with the gyroscope — |a| < 0.8 g while |ω| >= 6 rad/s (a phone
  that tumbles reads the centripetal part of its own spin, not ~0 g).
  ``lag_ms`` see above; ``overrun`` frames were dropped by the cap.
  ``mono`` is this process's monotonic time (the consumer's age check is
  immune to clock steps); ``ts`` epoch seconds.
* ``phone.light_lux`` ``{lux, ts}``: median of the last 5 readings,
  published at most every 0.5 s, when it moved by >= 5 % (at least
  0.5 lux) or as a 2 s heartbeat while streaming.

State: ``phone_sensors.state`` ``{state, rate_hz, calib_ok, error, since}``
on change (``rate_hz`` only when it moved by >= 10 %); state is one of
``disabled|waiting_forward|connecting|streaming|stale|error``; ``error`` is
also set for ``waiting_forward`` (car_phone off, no ``sensors`` forward —
e.g. the toggle was only given with ``--modules`` — or the forward's own
error such as a port clash).

At start one warning names thresholds the accelerometer range cannot reach
(``g_h_threshold`` >= 0.9 × range, or ``dv_threshold_kmh`` above 0.9 × the
most a clipped sensor can show in ``dv_window_ms``) — the accelerometer
crash path would never fire.
"""

from __future__ import annotations

import collections
import json
import math
import socket
import statistics
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

from src.core.fsutil import atomic_write_json
from src.core.logger import get_logger
from src.network._proc import _cfg_get, _number, clean_error
from src.safety.crash_detect import CrashConfig, load_crash_config

log = get_logger("sensors.phone")

TOPIC_G = "phone.g_force"
TOPIC_LUX = "phone.light_lux"
TOPIC_STATE = "phone_sensors.state"
RECALIBRATE_TOPIC = "phone_sensors.cmd.recalibrate"
CAR_PHONE_TOPIC = "net.car_phone"
FORWARD_NAME = "sensors"

STATES = ("disabled", "waiting_forward", "connecting", "streaming", "stale", "error")

TYPE_ACCEL = "android.sensor.accelerometer"
TYPE_GYRO = "android.sensor.gyroscope"
TYPE_LIGHT = "android.sensor.light"
SENSOR_TYPES = (TYPE_ACCEL, TYPE_GYRO, TYPE_LIGHT)
HOST = "127.0.0.1"


def connect_target(gyro: bool = True) -> str:
    """The request path. The JSON array is sent raw, as in SensorServer's
    own examples. ``gyro=False`` after the phone refused the gyroscope."""
    types = (TYPE_ACCEL, TYPE_GYRO, TYPE_LIGHT) if gyro else (TYPE_ACCEL, TYPE_LIGHT)
    return "/sensors/connect?types=[" + ",".join(f'"{t}"' for t in types) + "]"


CONNECT_TARGET = connect_target(True)
CONNECT_TARGET_NO_GYRO = connect_target(False)

G0 = 9.80665
#: Physical sanity of an accelerometer value: 4 × the largest phone range.
MAX_ACCEL_MS2 = 4 * 16 * G0
#: Physical sanity of a gyroscope value (rad/s): phone gyros end at
#: 2000 °/s ≈ 35 rad/s.
MAX_GYRO_RAD_S = 35.0
MAX_LUX = 200_000.0
MAX_FRAME_BYTES = 2048
MAX_HANDSHAKE_BYTES = 16384
#: All frame types together, per second of arrival time: accelerometer and
#: gyroscope at up to ~400 Hz each ("fastest" on many phones) plus light.
#: Frames over it are dropped AND the period is flagged ``overrun`` — a
#: silently truncated second would still show a good ``rate_hz``.
MAX_FRAMES_PER_S = 1000
#: Upper bound of the accelerometer's sample density (Hz) — sizes the count
#: caps of the time windows below, so a phone whose timestamps barely
#: advance (wrong unit, buggy app) cannot grow them without bound.
MAX_SENSOR_HZ = 1000
#: Complete messages buffered by the client between two receive() calls.
MAX_READY_MESSAGES = 512
RECV_BYTES = 4096

BUFFER_S = 10.0
RATE_WINDOW_S = 1.0
#: The rate needs this much time span to mean anything.
RATE_MIN_SPAN_S = 0.25
#: Integration step cap: a gap in the stream must not turn one sample into
#: a big Δv.
MAX_DT_S = 0.05
#: A gap this long (or any step back) restarts the pipeline.
GAP_RESET_S = 2.0
FREEFALL_G = 0.3
FREEFALL_LOOKBACK_S = 1.0
#: A phone that tumbles while it falls reads the centripetal ω²·r of its
#: own spin (0.5-0.8 g at 1.5-2 rev/s with the sensor 4-5 cm off the centre
#: of mass), not ~0 g — so with the gyroscope a sample also counts as
#: "falling" when |a| < TUMBLE_G AND |ω| >= TUMBLE_RAD_S. 6 rad/s is above
#: any yaw/pitch rate of a car before an impact (a spin-out is 1-3 rad/s)
#: and below what a tumble needs to read more than 0.3 g; a car on the road
#: never reads < 0.8 g with ground contact.
TUMBLE_G = 0.8
TUMBLE_RAD_S = 6.0
#: A gyroscope reading applies to accelerometer samples this close in time.
GYRO_MAX_AGE_S = 0.05
SAT_FRACTION = 0.98
#: Sample lag (arrival vs the phone's sensor clock) is measured against the
#: smallest offset of the last 10-20 s (two buckets), so a constant offset
#: and slow clock drift cancel out and only a backlog shows.
LAG_BUCKET_S = 10.0
#: A sample later than this counts as "late" (reported once a minute);
#: crash_detect rejects a message whose ``lag_ms`` exceeds 1 s (plan F).
LATE_S = 1.0
#: Sensor clock plausibility: after this much arrival time, the phone's
#: timestamps must have advanced by at least CLOCK_MIN_RATIO of it (else
#: they are not nanoseconds, or the app is broken) — the connection then
#: uses the arrival time.
CLOCK_CHECK_S = 5.0
CLOCK_MIN_RATIO = 0.5

# Gravity calibration.
BLOCK_S = 0.5
MIN_BLOCK_SAMPLES = 10
REST_STD_MS2 = 0.35
REST_MAG_TOL_MS2 = 0.5
FAST_TAU_S = 10.0
SLOW_TAU_S = 60.0
CALIB_MIN_QUIET_S = 10.0
#: The quiet blocks that make the first reference must agree: one further
#: than this from their running mean (gentle braking or a curve just before
#: the stop) restarts the collection from that block.
REF_AGREE_DEG = 2.5
VERIFY_QUIET_S = 3.0
DRIFT_LIMIT_DEG = 10.0
DRIFT_CLEAR_DEG = 7.0
#: The FAST estimate this far from the reference = the phone was moved
#: (re-mounted while BCM was off) — steeper than any road or parking ramp,
#: so it is flagged within seconds instead of after ~τ 60 s.
MOVED_LIMIT_DEG = 20.0
MOVED_CLEAR_DEG = 15.0
STATE_FILE = "data/phone_sensors.json"
STATE_FILE_MAX = 4096

# Publication.
G_PUBLISH_S = 0.1
LUX_MEDIAN_N = 5
LUX_MIN_INTERVAL_S = 0.5
LUX_HEARTBEAT_S = 2.0
LUX_CHANGE = 0.05
LUX_MIN_STEP = 0.5
RATE_REPUBLISH = 0.10

# Connection.
STALE_S = 1.0
IDLE_RECONNECT_S = 10.0
CONNECT_TIMEOUT_S = 5.0
RECV_TIMEOUT_S = 0.2
BACKOFF_MIN_S = 1.0
BACKOFF_MAX_S = 60.0
BACKOFF_RESET_AFTER_S = 30.0
#: Nothing listens on 127.0.0.1:<local> (connection refused) = the adb
#: forward is missing or being re-created (the phone re-enumerated on USB);
#: such a retry is local and cheap, so it never waits longer than this.
FORWARD_MISSING_RETRY_S = 3.0
WAIT_FORWARD_S = 5.0
#: Dropped/invalid frame counters are logged at most this often.
STATS_LOG_EVERY_S = 60.0
#: Counters that mean "the phone sent something wrong".
BAD_COUNTERS = ("garbage", "oversize", "invalid", "unknown_type", "dropped_rate", "late")

DEFAULTS = {"accel_range_g": 8.0}


# ── frames (pure) ─────────────────────────────────────────────────────────

def _reject_constant(name: str) -> Any:
    raise ValueError(f"{name} is not a number")


def parse_frame(raw: Any) -> tuple[Optional[tuple[str, tuple[float, ...], Optional[int]]], str]:
    """One SensorServer text frame → ``((type, values, timestamp_ns), "")``
    or ``(None, reason)`` with reason ``garbage|oversize|unknown_type|invalid``.

    Nothing from the phone is trusted: size first, then strict JSON (no
    NaN/Infinity), then type and ranges. ``timestamp`` is None when missing
    or not a plain non-negative integer (the caller uses the arrival time).
    """
    if not isinstance(raw, str):
        return None, "garbage"
    if len(raw) > MAX_FRAME_BYTES:
        return None, "oversize"
    try:
        obj = json.loads(raw, parse_constant=_reject_constant)
    except (ValueError, RecursionError):
        return None, "garbage"
    if not isinstance(obj, dict):
        return None, "garbage"
    kind = obj.get("type")
    if kind not in SENSOR_TYPES:
        return None, "unknown_type"
    values = obj.get("values")
    if not isinstance(values, list) or not values or len(values) > 16:
        return None, "invalid"
    out: list[float] = []
    for v in values:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return None, "invalid"
        try:
            # A JSON integer of a few hundred digits fits in one frame and
            # float() of it raises OverflowError — counted, never raised.
            v = float(v)
        except OverflowError:
            return None, "invalid"
        if not math.isfinite(v):
            return None, "invalid"
        out.append(v)
    if kind == TYPE_ACCEL:
        if len(out) != 3 or any(abs(v) > MAX_ACCEL_MS2 for v in out):
            return None, "invalid"
    elif kind == TYPE_GYRO:
        if len(out) != 3 or any(abs(v) > MAX_GYRO_RAD_S for v in out):
            return None, "invalid"
    elif not 0.0 <= out[0] <= MAX_LUX:
        return None, "invalid"
    else:
        out = out[:1]
    ts = obj.get("timestamp")
    if isinstance(ts, bool) or not isinstance(ts, int) or not 0 <= ts < 2**63:
        ts = None
    return (kind, tuple(out), ts), ""


# ── vectors ────────────────────────────────────────────────────────────────

Vec = tuple[float, float, float]


def _norm(v: Vec) -> float:
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


def _unit(v: Vec) -> Optional[Vec]:
    n = _norm(v)
    if not n or not math.isfinite(n):
        return None
    return (v[0] / n, v[1] / n, v[2] / n)


def _blend(old: Vec, new: Vec, alpha: float) -> Vec:
    """One low-pass step: ``old + alpha * (new - old)``."""
    return (old[0] + alpha * (new[0] - old[0]), old[1] + alpha * (new[1] - old[1]),
            old[2] + alpha * (new[2] - old[2]))


def angle_deg(a: Vec, b: Vec) -> float:
    """Angle between two vectors (degrees); 180 if either is zero."""
    ua, ub = _unit(a), _unit(b)
    if ua is None or ub is None:
        return 180.0
    dot = max(-1.0, min(1.0, ua[0] * ub[0] + ua[1] * ub[1] + ua[2] * ub[2]))
    return math.degrees(math.acos(dot))


# ── gravity calibration ────────────────────────────────────────────────────

def load_reference(path: str) -> Optional[Vec]:
    """The saved gravity direction, or None (missing, unreadable, invalid)."""
    try:
        p = Path(path)
        if p.stat().st_size > STATE_FILE_MAX:
            log.warning("Phone sensors: %s is too big — ignored, calibrating anew", path)
            return None
        data = json.loads(p.read_text(encoding="utf-8"), parse_constant=_reject_constant)
    except FileNotFoundError:
        return None
    except (OSError, ValueError, RecursionError) as e:
        log.warning("Phone sensors: %s unreadable (%s) — calibrating anew", path,
                    clean_error(e))
        return None
    vec = data.get("gravity") if isinstance(data, dict) else None
    fvec: Optional[Vec] = None
    if isinstance(vec, list) and len(vec) == 3 and not any(
            isinstance(v, bool) or not isinstance(v, (int, float)) for v in vec):
        try:
            # float() of a huge JSON integer raises OverflowError: an
            # invalid file must never stop the module from starting.
            fvec = (float(vec[0]), float(vec[1]), float(vec[2]))
        except OverflowError:
            fvec = None
    if fvec is None or not all(math.isfinite(c) for c in fvec):
        log.warning("Phone sensors: %s has no valid gravity vector — calibrating anew", path)
        return None
    n = _norm(fvec)
    if not 0.9 <= n <= 1.1:
        log.warning("Phone sensors: %s gravity vector is not a unit vector — ignored", path)
        return None
    return (fvec[0] / n, fvec[1] / n, fvec[2] / n)


def save_reference(path: str, ref: Vec, wall: float) -> None:
    """Atomic write (fsutil) — a power cut leaves the old file or the new one."""
    atomic_write_json(path, {"version": 1, "gravity": [round(c, 6) for c in ref],
                             "saved_at": round(wall, 1)}, mode=0o644)


class GravityCalibrator:
    """Gravity direction of the mounted phone (module docstring, Processing).

    ``add`` takes samples in time order (seconds, m/s²). ``new_reference``
    turns True when a reference was just taken (the owner saves it and
    clears the flag).

    Three estimates, each for one job:

    * ``est`` — fast low-pass (τ 10 s) of the quiet blocks, from live data
      only: what the h/v split subtracts as gravity;
    * ``slow`` — long-term low-pass (τ 60 s): the drift check against the
      reference. With a loaded reference it STARTS at the reference, so a
      restart on a ramp is not mistaken for a moved phone — only a
      deviation held for about τ counts (plan G: the LONG-TERM direction);
    * ``ref`` — the reference, saved to disk: the span-weighted mean of
      10 s of quiet blocks that agree with each other (one block more than
      2.5° off their running mean restarts the collection — a lone block of
      gentle braking or a curve must not become "level").

    A phone re-mounted while BCM was off would take ~τ to show in ``slow``;
    ``est`` more than 20° from the reference (steeper than any ramp) flags
    it after the 3 s of quiet data that confirm a loaded reference."""

    def __init__(self, ref: Optional[Vec] = None) -> None:
        self.ref: Optional[Vec] = ref
        self.est: Optional[Vec] = None
        self.slow: Optional[Vec] = None if ref is None else (ref[0] * G0, ref[1] * G0,
                                                              ref[2] * G0)
        self.quiet_s = 0.0
        self.drifted = False
        self._slow_drifted = False
        self._moved = False
        self.new_reference = False
        self._block: Optional[list[float]] = None
        # First-reference collection: span-weighted sum of agreeing blocks.
        self._col_sum = (0.0, 0.0, 0.0)
        self._col_span = 0.0

    def reset(self) -> None:
        """Forget everything, the reference too (recalibrate command)."""
        self.__init__(None)

    def restart_block(self) -> None:
        self._block = None

    @property
    def calib_ok(self) -> bool:
        return (self.ref is not None and self.est is not None
                and self.quiet_s >= VERIFY_QUIET_S and not self.drifted)

    def drift_deg(self) -> Optional[float]:
        """How far gravity is from the reference (the larger of the
        long-term and, when that flagged it, the fast estimate)."""
        if self.ref is None or self.slow is None:
            return None
        drift = angle_deg(self.slow, self.ref)
        if self._moved and self.est is not None:
            drift = max(drift, angle_deg(self.est, self.ref))
        return drift

    def add(self, t: float, x: float, y: float, z: float) -> None:
        b = self._block
        if b is None:
            # [t0, t_last, n, sx, sy, sz, sxx, syy, szz]
            self._block = [t, t, 1, x, y, z, x * x, y * y, z * z]
            return
        if t - b[0] >= BLOCK_S:
            self._finish(b)
            self._block = [t, t, 1, x, y, z, x * x, y * y, z * z]
            return
        b[1] = t
        b[2] += 1
        b[3] += x
        b[4] += y
        b[5] += z
        b[6] += x * x
        b[7] += y * y
        b[8] += z * z

    def _finish(self, b: list[float]) -> None:
        n = int(b[2])
        span = b[1] - b[0]
        if n < MIN_BLOCK_SAMPLES or span <= 0:
            return
        mean = (b[3] / n, b[4] / n, b[5] / n)
        stds = [math.sqrt(max(0.0, b[6 + i] / n - mean[i] * mean[i])) for i in range(3)]
        if max(stds) > REST_STD_MS2 or abs(_norm(mean) - G0) > REST_MAG_TOL_MS2:
            return
        self.quiet_s += span
        if self.est is None:
            self.est = mean
        else:
            self.est = _blend(self.est, mean, min(1.0, span / FAST_TAU_S))
        if self.ref is None:
            self._collect(mean, span)
            return
        if self.slow is None:
            self.slow = mean
        else:
            self.slow = _blend(self.slow, mean, min(1.0, span / SLOW_TAU_S))
        if self.quiet_s >= VERIFY_QUIET_S:
            drift = angle_deg(self.slow, self.ref)
            if drift > DRIFT_LIMIT_DEG:
                self._slow_drifted = True
            elif drift < DRIFT_CLEAR_DEG:
                self._slow_drifted = False
            moved = angle_deg(self.est, self.ref)
            if moved > MOVED_LIMIT_DEG:
                self._moved = True
            elif moved < MOVED_CLEAR_DEG:
                self._moved = False
            self.drifted = self._slow_drifted or self._moved

    def _collect(self, mean: Vec, span: float) -> None:
        """First reference: span-weighted mean of agreeing quiet blocks."""
        if self._col_span > 0:
            run = (self._col_sum[0] / self._col_span, self._col_sum[1] / self._col_span,
                   self._col_sum[2] / self._col_span)
            if angle_deg(mean, run) > REF_AGREE_DEG:
                self._col_sum = (0.0, 0.0, 0.0)
                self._col_span = 0.0
        self._col_sum = (self._col_sum[0] + mean[0] * span, self._col_sum[1] + mean[1] * span,
                         self._col_sum[2] + mean[2] * span)
        self._col_span += span
        if self._col_span < CALIB_MIN_QUIET_S:
            return
        ref = _unit(self._col_sum)
        if ref is None:
            self._col_sum = (0.0, 0.0, 0.0)
            self._col_span = 0.0
            return
        n = self._col_span
        self.ref = ref
        # Both estimates restart from the agreed data: an early odd block
        # must not linger in the split or in the drift check.
        self.est = (self._col_sum[0] / n, self._col_sum[1] / n, self._col_sum[2] / n)
        self.slow = (ref[0] * G0, ref[1] * G0, ref[2] * G0)
        self._slow_drifted = self._moved = self.drifted = False
        self.new_reference = True


# ── accelerometer pipeline ─────────────────────────────────────────────────

class AccelProcessor:
    """Ring buffer, rate, gravity split, and the per-period ``phone.g_force``
    statistics. Pure: samples in, :meth:`snapshot` out."""

    def __init__(self, crash: CrashConfig, accel_range_g: float,
                 calibrator: Optional[GravityCalibrator] = None) -> None:
        self.calib = calibrator or GravityCalibrator()
        self._window_s = crash.dv_window_ms / 1000.0
        self._window_ms = crash.dv_window_ms
        self._thr = crash.g_h_threshold * G0
        self._sat = SAT_FRACTION * accel_range_g * G0
        # The windows are trimmed by the phone's timestamps; the count caps
        # (with headroom over any real sample density) bound them even when
        # those timestamps barely advance. _rate has no running sum, so a
        # maxlen is enough; _buf/_dv keep sums and are trimmed by hand.
        self._buf_max = int(BUFFER_S * MAX_SENSOR_HZ)
        self._rate_max = int(RATE_WINDOW_S * MAX_SENSOR_HZ) + 1
        self._dv_max = int(self._window_s * MAX_SENSOR_HZ) + 2
        self._buf: collections.deque[tuple[float, float, float, float]] = collections.deque()
        self._sum = [0.0, 0.0, 0.0]
        self._rate: collections.deque[float] = collections.deque(maxlen=self._rate_max)
        self._dv: collections.deque[tuple[float, float, float, float]] = collections.deque()
        self._dv_sum = [0.0, 0.0, 0.0]
        self._last_t: Optional[float] = None
        self._run = 0
        self._ff_start: Optional[float] = None
        self._ff_last_end: Optional[float] = None
        self._ff_last_dur = 0.0
        # Latest gyroscope reading: (time, |ω| rad/s).
        self._gyro: Optional[tuple[float, float]] = None
        self.samples = 0
        self.resets = 0
        self.late = 0
        self.reset_lag()
        self._new_period()

    def _new_period(self) -> None:
        self._p_n = 0
        self._p_sat = False
        self._p_h = 0.0
        self._p_v = 0.0
        self._p_dv = 0.0
        self._p_over = 0
        self._p_ff = 0.0
        self._p_lag = 0.0
        self._p_overrun = False

    def reset_lag(self) -> None:
        """Forget the lag baseline (new connection, new time base)."""
        self._lag_cur: Optional[float] = None
        self._lag_prev: Optional[float] = None
        self._lag_since: Optional[float] = None

    def _lag(self, offset: float, arrival: float) -> float:
        """Seconds this sample arrived later than the best delivery of the
        last 10-20 s (offset = arrival − sensor time)."""
        since = self._lag_since
        if since is None or not 0 <= arrival - since < LAG_BUCKET_S:
            self._lag_prev = self._lag_cur
            self._lag_cur = offset
            self._lag_since = arrival
        else:
            self._lag_cur = min(self._lag_cur, offset)
        base = self._lag_cur if self._lag_prev is None else min(self._lag_cur, self._lag_prev)
        return max(0.0, offset - base)

    def _restart(self) -> None:
        """Gap or step back: the windows restart; calibration stays."""
        self.resets += 1
        self._buf.clear()
        self._sum = [0.0, 0.0, 0.0]
        self._rate.clear()
        self._dv.clear()
        self._dv_sum = [0.0, 0.0, 0.0]
        self._last_t = None
        self._run = 0
        self._ff_start = None
        self._ff_last_end = None
        self._ff_last_dur = 0.0
        self._gyro = None
        self.reset_lag()
        self.calib.restart_block()

    def restart(self) -> None:
        """Public restart (the owner switched the time base)."""
        self._restart()

    def mark_overrun(self) -> None:
        """Frames were dropped by the per-second cap in this period: its
        statistics are incomplete (``overrun`` in the snapshot)."""
        self._p_overrun = True

    def add_gyro(self, t: float, wx: float, wy: float, wz: float) -> None:
        """One gyroscope sample (seconds, rad/s) — only its magnitude is
        used, to recognise a phone tumbling as it falls."""
        self._gyro = (t, math.sqrt(wx * wx + wy * wy + wz * wz))

    def add(self, t: float, x: float, y: float, z: float,
            arrival: Optional[float] = None) -> bool:
        """One sample (seconds, m/s²). False = dropped (duplicate time).
        ``arrival`` (our monotonic time) measures how late the sample came."""
        if self._last_t is not None:
            dt = t - self._last_t
            if dt <= 0:
                if dt > -0.001:
                    return False            # same timestamp again: a duplicate
                self._restart()
                dt = None
            elif dt > GAP_RESET_S:
                self._restart()
                dt = None
        else:
            dt = None
        self._last_t = t
        self.samples += 1
        step = min(dt, MAX_DT_S) if dt else 0.0
        if arrival is not None:
            lag = self._lag(arrival - t, arrival)
            self._p_lag = max(self._p_lag, lag)
            if lag > LATE_S:
                self.late += 1

        self._buf.append((t, x, y, z))
        self._sum[0] += x
        self._sum[1] += y
        self._sum[2] += z
        while self._buf and (t - self._buf[0][0] > BUFFER_S or len(self._buf) > self._buf_max):
            _, ox, oy, oz = self._buf.popleft()
            self._sum[0] -= ox
            self._sum[1] -= oy
            self._sum[2] -= oz
        self._rate.append(t)
        while self._rate and t - self._rate[0] > RATE_WINDOW_S:
            self._rate.popleft()

        self.calib.add(t, x, y, z)
        mag = math.sqrt(x * x + y * y + z * z)
        self._p_n += 1
        if max(abs(x), abs(y), abs(z)) >= self._sat:
            self._p_sat = True

        gravity = self.calib.est
        if gravity is None and len(self._buf) >= MIN_BLOCK_SAMPLES:
            n = len(self._buf)
            gravity = (self._sum[0] / n, self._sum[1] / n, self._sum[2] / n)
        g_hat = _unit(gravity) if gravity is not None else None
        if g_hat is not None:
            lx, ly, lz = x - gravity[0], y - gravity[1], z - gravity[2]
            v = lx * g_hat[0] + ly * g_hat[1] + lz * g_hat[2]
            hx, hy, hz = lx - v * g_hat[0], ly - v * g_hat[1], lz - v * g_hat[2]
            h = math.sqrt(hx * hx + hy * hy + hz * hz)
        else:
            v, h = 0.0, abs(mag - G0)
            hx = hy = hz = 0.0
        self._p_h = max(self._p_h, h / G0)
        self._p_v = max(self._p_v, abs(v) / G0)

        # Δv: vector sum of a_h·Δt over the window (vibration cancels out).
        self._dv.append((t, hx * step, hy * step, hz * step))
        self._dv_sum[0] += hx * step
        self._dv_sum[1] += hy * step
        self._dv_sum[2] += hz * step
        while self._dv and (t - self._dv[0][0] >= self._window_s
                            or len(self._dv) > self._dv_max):
            _, ox, oy, oz = self._dv.popleft()
            self._dv_sum[0] -= ox
            self._dv_sum[1] -= oy
            self._dv_sum[2] -= oz
        dv = math.sqrt(sum(c * c for c in self._dv_sum)) * 3.6
        self._p_dv = max(self._p_dv, dv)

        self._run = self._run + 1 if h >= self._thr else 0
        self._p_over = max(self._p_over, self._run)

        omega = None
        if self._gyro is not None and abs(t - self._gyro[0]) <= GYRO_MAX_AGE_S:
            omega = self._gyro[1]
        falling = mag < FREEFALL_G * G0 or (
            omega is not None and omega >= TUMBLE_RAD_S and mag < TUMBLE_G * G0)
        if falling:
            if self._ff_start is None:
                self._ff_start = t
        elif self._ff_start is not None:
            self._ff_last_end = t
            self._ff_last_dur = t - self._ff_start
            self._ff_start = None
        ff = 0.0
        if self._ff_start is not None:
            ff = t - self._ff_start
        if self._ff_last_end is not None and t - self._ff_last_end <= FREEFALL_LOOKBACK_S:
            ff = max(ff, self._ff_last_dur)
        self._p_ff = max(self._p_ff, ff)
        return True

    @property
    def rate_hz(self) -> float:
        if len(self._rate) < 2:
            return 0.0
        span = self._rate[-1] - self._rate[0]
        if span < RATE_MIN_SPAN_S:
            return 0.0
        return (len(self._rate) - 1) / span

    @property
    def pending(self) -> int:
        """Samples since the last snapshot."""
        return self._p_n

    def snapshot(self, wall: float, mono: float) -> dict[str, Any]:
        """The ``phone.g_force`` payload of the samples since the last call."""
        out = {
            "ts": round(wall, 3),
            "mono": round(mono, 4),
            "rate_hz": round(self.rate_hz, 1),
            "sat": self._p_sat,
            "peak_h_g": round(self._p_h, 3),
            "peak_v_g": round(self._p_v, 3),
            "dv_h_kmh_150ms": round(self._p_dv, 2),
            "dv_window_ms": int(round(self._window_ms)),
            "n_over_g": self._p_over,
            "freefall_ms": int(round(self._p_ff * 1000)),
            "calib_ok": self.calib.calib_ok,
            "lag_ms": int(round(self._p_lag * 1000)),
            "overrun": self._p_overrun,
        }
        self._new_period()
        return out


class LightSmoother:
    """Median of the last readings; publish on a 5 % move or a heartbeat."""

    def __init__(self) -> None:
        self._vals: collections.deque[float] = collections.deque(maxlen=LUX_MEDIAN_N)
        self._last: Optional[float] = None
        self._last_at: Optional[float] = None

    def add(self, lux: float) -> None:
        self._vals.append(lux)

    def due(self, now: float) -> Optional[float]:
        """The value to publish now, or None."""
        if not self._vals:
            return None
        med = round(statistics.median(self._vals), 1)
        if self._last_at is not None:
            elapsed = now - self._last_at
            if 0 <= elapsed < LUX_MIN_INTERVAL_S:
                return None
            moved = abs(med - self._last) >= max(LUX_CHANGE * self._last, LUX_MIN_STEP)
            if not moved and 0 <= elapsed < LUX_HEARTBEAT_S:
                return None
        self._last = med
        self._last_at = now
        return med


# ── WebSocket client (wsproto, one thread, timeouts) ───────────────────────

class ConnectionClosed(Exception):
    """The WebSocket ended (EOF, close frame, protocol error). ``code`` is
    the close code of a close frame (None otherwise)."""

    def __init__(self, message: str = "", code: Optional[int] = None) -> None:
        super().__init__(message)
        self.code = code


class WsClient:
    """Blocking text-message client for ONE thread (module docstring)."""

    def __init__(self, sock: socket.socket, ws: Any, max_bytes: int) -> None:
        self._sock = sock
        self._ws = ws
        self._max = max_bytes
        self._ready: collections.deque[str] = collections.deque()
        self._parts: list[str] = []
        self._size = 0
        self._skip = False
        self.oversize = 0
        self.binary = 0

    @classmethod
    def open(cls, host: str, port: int, target: str, timeout: float,
             max_bytes: int = MAX_FRAME_BYTES) -> "WsClient":
        """Connect and handshake within ``timeout`` seconds in total."""
        from wsproto import ConnectionType, WSConnection
        from wsproto.events import AcceptConnection, RejectConnection, RejectData, Request

        deadline = time.monotonic() + timeout
        sock = socket.create_connection((host, port), timeout=timeout)
        try:
            ws = WSConnection(ConnectionType.CLIENT)
            sock.sendall(ws.send(Request(host=f"{host}:{port}", target=target)))
            client = cls(sock, ws, max_bytes)
            received = 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("WebSocket handshake timed out")
                sock.settimeout(remaining)
                data = sock.recv(RECV_BYTES)
                if not data:
                    raise ConnectionClosed("connection closed during the handshake "
                                           "(is SensorServer running with Local Host on?)")
                received += len(data)
                if received > MAX_HANDSHAKE_BYTES:
                    raise ConnectionClosed("handshake answer too long")
                ws.receive_data(data)
                for event in ws.events():
                    if isinstance(event, AcceptConnection):
                        # Frames that came with the answer stay in wsproto.
                        return client
                    if isinstance(event, (RejectConnection, RejectData)):
                        status = getattr(event, "status_code", "?")
                        raise ConnectionClosed(f"handshake rejected (HTTP {status})")
        except BaseException:
            sock.close()
            raise

    def receive(self, timeout: float) -> Optional[str]:
        """The next complete text message, None after ``timeout`` without one.
        Raises :class:`ConnectionClosed` (or OSError) when the link ends."""
        deadline = time.monotonic() + timeout
        while True:
            if self._ready:
                return self._ready.popleft()
            self._drain_events()
            if self._ready:
                return self._ready.popleft()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            self._sock.settimeout(remaining)
            try:
                data = self._sock.recv(RECV_BYTES)
            except socket.timeout:
                return None
            if not data:
                raise ConnectionClosed("connection closed by the phone")
            try:
                self._ws.receive_data(data)
            except Exception as e:          # LocalProtocolError after a close
                raise ConnectionClosed(clean_error(f"protocol error: {e}")) from e

    def _drain_events(self) -> None:
        from wsproto.events import BytesMessage, CloseConnection, Ping, TextMessage

        try:
            for event in self._ws.events():
                if isinstance(event, TextMessage):
                    self._text(event.data, event.message_finished)
                elif isinstance(event, BytesMessage):
                    # SensorServer sends text only; binary data is not kept.
                    if event.message_finished:
                        self.binary += 1
                elif isinstance(event, Ping):
                    self._send(event.response())
                elif isinstance(event, CloseConnection):
                    try:
                        self._send(event.response())
                    except Exception:
                        pass
                    code = event.code if isinstance(event.code, int) else None
                    raise ConnectionClosed(clean_error(
                        f"closed by the phone (code {event.code}"
                        f"{': ' + event.reason if event.reason else ''})"), code=code)
        except ConnectionClosed:
            raise
        except Exception as e:
            raise ConnectionClosed(clean_error(f"protocol error: {e}")) from e

    def _text(self, data: str, finished: bool) -> None:
        if not self._skip:
            self._size += len(data.encode("utf-8", "replace"))
            if self._size > self._max:
                self._skip = True
                self._parts = []
            else:
                self._parts.append(data)
        if not finished:
            return
        if self._skip:
            self.oversize += 1
        elif len(self._ready) < MAX_READY_MESSAGES:
            self._ready.append("".join(self._parts))
        self._parts = []
        self._size = 0
        self._skip = False

    def _send(self, event: Any) -> None:
        data = self._ws.send(event)
        if data:
            self._sock.settimeout(1.0)
            self._sock.sendall(data)

    def close(self) -> None:
        try:
            from wsproto.connection import ConnectionState
            from wsproto.events import CloseConnection

            if self._ws.state is ConnectionState.OPEN:
                self._send(CloseConnection(code=1000))
        except Exception:
            pass
        try:
            self._sock.close()
        except OSError:
            pass


def default_connect(host: str, port: int, target: str, timeout: float) -> WsClient:
    return WsClient.open(host, port, target, timeout, MAX_FRAME_BYTES)


# ── the module ─────────────────────────────────────────────────────────────

class PhoneSensors:
    """SensorServer stream → ``phone.g_force`` / ``phone.light_lux``.

    Args:
        config: BCMConfig or nested dict.
        event_bus: EventBus.
        connect: ``(host, port, target, timeout) -> client`` with
            ``receive(timeout) -> str | None`` and ``close()`` — the test seam.
        clock: monotonic seconds (arrival times, publish cadence, backoff).
        wall_clock: epoch seconds (``ts`` fields).
        state_path: the gravity reference file.
    """

    def __init__(self, config: Any, event_bus: Any,
                 connect: Callable[..., Any] = default_connect,
                 clock: Callable[[], float] = time.monotonic,
                 wall_clock: Callable[[], float] = time.time,
                 state_path: str = STATE_FILE) -> None:
        self._bus = event_bus
        self._connect = connect
        self._clock = clock
        self._wall = wall_clock
        self._state_path = state_path
        section = _cfg_get(config, "sensors.phone", {})
        if not isinstance(section, dict):
            section = {}
        self.accel_range_g = float(_number("sensors.phone", section.get("accel_range_g"),
                                           DEFAULTS["accel_range_g"], 2.0, 32.0,
                                           "accel_range_g", logger=log))
        self.crash_cfg = load_crash_config(config, logger=log)
        self._warn_unreachable_thresholds()
        self.calib = GravityCalibrator(load_reference(state_path))
        self.accel = AccelProcessor(self.crash_cfg, self.accel_range_g, self.calib)
        self.light = LightSmoother()
        # The gyroscope is requested until the phone refuses it (a close
        # with an application code before the first frame) — then the
        # stream goes on without it (no tumbling-drop recognition).
        self._want_gyro = True
        # Sensor clock plausibility, per connection (handle_message).
        self._clock_bad = False
        self._clock_anchor: Optional[tuple[float, float, int]] = None
        self._clock_bad_logged = False
        self._session_frames = 0
        # (port, ok) of the sensors forward last seen by cycle().
        self._fwd_seen: Optional[tuple[int, bool]] = None

        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._ev_lock = threading.Lock()
        # stop() publishes "disabled" from another thread than the worker.
        self._state_lock = threading.Lock()
        self._recal_req = 0
        self._recal_seen = 0

        self.stats: collections.Counter = collections.Counter()
        self._sec_start: Optional[float] = None
        self._sec_count = 0
        self._last_frame_at: Optional[float] = None
        self._last_accel_at: Optional[float] = None
        self._connected_at: Optional[float] = None
        self._last_g_pub: Optional[float] = None
        self._stats_logged_at: Optional[float] = None
        self._stats_logged: dict[str, int] = {}
        self._delay = BACKOFF_MIN_S
        self._retry_at = 0.0
        self._conn: Any = None
        self._drift_logged = False
        # The last error logged as a warning: a retry that fails the same
        # way every minute is not logged again (debug only).
        self._logged_error = ""

        self._state = "disabled"
        self._state_payload: Optional[dict[str, Any]] = None
        self._since = 0.0

    def _warn_unreachable_thresholds(self) -> None:
        """One warning when the crash thresholds cannot be reached within the
        accelerometer's range — the accel path would then never fire, and
        nothing else would say so."""
        c = self.crash_cfg
        rng = self.accel_range_g
        # The most Δv a clipped sensor can show over the window (km/h).
        dv_max = rng * G0 * c.dv_window_ms / 1000.0 * 3.6
        if c.g_h_threshold >= 0.9 * rng or c.dv_threshold_kmh > 0.9 * dv_max:
            log.warning("Phone sensors: crash_detection.g_h_threshold=%.1f g / "
                        "dv_threshold_kmh=%.0f in %.0f ms cannot be reached with "
                        "sensors.phone.accel_range_g=%.0f (at most ~%.0f km/h in that window) "
                        "— the accelerometer crash path can never trigger", c.g_h_threshold,
                        c.dv_threshold_kmh, c.dv_window_ms, rng, dv_max)

    # ── lifecycle ─────────────────────────────────────────────────────────

    def _subscriptions(self) -> tuple:
        return ((CAR_PHONE_TOPIC, self._on_car_phone),
                (RECALIBRATE_TOPIC, self._on_recalibrate),
                ("power.shutting_down", self._on_shutdown))

    def start(self) -> None:
        """Subscribe and start the worker; no I/O here."""
        if self._thread is not None:
            return
        for topic, cb in self._subscriptions():
            self._bus.subscribe(topic, cb)
        self._thread = threading.Thread(target=self._run, daemon=True, name="phone-sensors")
        self._thread.start()
        log.info("Phone sensors started (SensorServer via the car phone's '%s' forward, "
                 "range %.0f g, gravity reference: %s)", FORWARD_NAME, self.accel_range_g,
                 "loaded" if self.calib.ref is not None else "none yet")

    def stop(self) -> None:
        """Never waits: the worker closes the socket within RECV_TIMEOUT_S."""
        if self._stop.is_set():
            return
        self._stop.set()
        self._wake.set()
        for topic, cb in self._subscriptions():
            try:
                self._bus.unsubscribe(topic, cb)
            except Exception:
                pass
        self._set_state("disabled", force=True)
        log.info("Phone sensors stopped")

    def _on_shutdown(self, topic: str, value: Any, timestamp: float) -> None:
        if value:
            self.stop()

    def _on_car_phone(self, topic: str, value: Any, timestamp: float) -> None:
        """Forward state changed: only a wake-up (bus dispatcher, no I/O)."""
        self._wake.set()

    def _on_recalibrate(self, topic: str, value: Any, timestamp: float) -> None:
        """Argument-free; applied by the worker (it owns the calibration)."""
        with self._ev_lock:
            self._recal_req += 1

    @property
    def state(self) -> Optional[dict[str, Any]]:
        if self._state_payload is None:
            return None
        return dict(self._state_payload, since=self._since)

    # ── worker ────────────────────────────────────────────────────────────

    def _run(self) -> None:
        while not self._stop.is_set():
            # Cleared BEFORE the step: a net.car_phone change during it is
            # not lost (stop() sets the same event).
            self._wake.clear()
            try:
                wait = self.cycle()
            except Exception:
                log.exception("Phone sensors: worker pass failed")
                self._fail("internal error (see the log)")
                wait = BACKOFF_MIN_S
            if wait > 0:
                self._wake.wait(wait)

    def forward_spec(self) -> tuple[Optional[tuple[int, bool]], str]:
        """car_phone's ``sensors`` forward from the bus (``net.car_phone``):
        ``((local port, ok), "")``, or ``(None, why)`` when car_phone does
        not run or has no such forward (``why`` for the state's error)."""
        try:
            last = self._bus.get_last(CAR_PHONE_TOPIC)
        except Exception:
            last = None
        value = last[0] if last else None
        if not isinstance(value, dict) or value.get("state") == "disabled":
            return None, "car_phone is not running"
        forwards = value.get("forwards")
        spec = forwards.get(FORWARD_NAME) if isinstance(forwards, dict) else None
        if not isinstance(spec, dict):
            # car_phone decides its forwards from the config toggle at start:
            # `main.py --modules ...,phone_sensors` alone does not create it.
            return None, ("car_phone has no sensors forward — modules.phone_sensors must be "
                          "on in the config when car_phone starts")
        port = spec.get("local")
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            return None, "car_phone reports an invalid sensors forward port"
        ok = spec.get("ok") is True
        why = ""
        if not ok:
            err = spec.get("error")
            why = clean_error(err) if isinstance(err, str) and err else \
                "the sensors forward is not up (phone not connected?)"
        return (port, ok), why

    def forward_port(self) -> Optional[int]:
        """The local port of car_phone's ``sensors`` forward while it is up;
        None otherwise."""
        spec, _why = self.forward_spec()
        return spec[0] if spec is not None and spec[1] else None

    def cycle(self) -> float:
        """One step of the worker: connect and stream until the link ends,
        unless the forward is down or the backoff runs. Returns how long to
        wait before the next step (a ``net.car_phone`` change or stop()
        cuts the wait short)."""
        spec, why = self.forward_spec()
        if spec is None or not spec[1]:
            self._fwd_seen = spec
            self._set_state("waiting_forward", error=why)
            return WAIT_FORWARD_S
        port = spec[0]
        if self._fwd_seen != (port, True):
            # The forward (re)appeared or moved: whatever failed before was
            # about the old one — connect now, from the shortest backoff.
            self._fwd_seen = (port, True)
            self._delay = BACKOFF_MIN_S
            self._retry_at = 0.0
        now = self._clock()
        if now < self._retry_at:
            return min(self._retry_at - now, WAIT_FORWARD_S)
        self._set_state("connecting")
        target = CONNECT_TARGET if self._want_gyro else CONNECT_TARGET_NO_GYRO
        try:
            conn = self._connect(HOST, port, target, CONNECT_TIMEOUT_S)
        except ConnectionRefusedError as e:
            # Nothing listens locally: the adb forward is missing or being
            # re-created by car_phone. Cheap to retry — short cap.
            self._fail(f"cannot connect to SensorServer (127.0.0.1:{port}): {e}",
                       max_delay=FORWARD_MISSING_RETRY_S)
            return 0.0
        except Exception as e:
            self._fail(f"cannot connect to SensorServer (127.0.0.1:{port}): {e}")
            return 0.0
        self.stream(conn, port)
        return 0.0

    def stream(self, conn: Any, port: int) -> None:
        """Read frames until the link ends, the forward moves or stop().

        A forward that car_phone briefly reports as not ``ok`` (one failed
        ``adb devices`` and its backoff) does not end a session that keeps
        delivering: a phone or adb server that is really gone ends the
        socket anyway, and the idle check catches a dead link. Only a
        changed port or car_phone stopping ends it here."""
        self._conn = conn
        started = self._clock()
        self._connected_at = started
        self._last_frame_at = None
        self._last_accel_at = None
        self._session_frames = 0
        self._clock_bad = False
        self._clock_anchor = None
        self.accel.reset_lag()
        streamed_at: Optional[float] = None
        next_forward_check = started + 1.0
        reason = ""
        close_code: Optional[int] = None
        try:
            while not self._stop.is_set():
                try:
                    msg = conn.receive(RECV_TIMEOUT_S)
                except Exception as e:
                    reason = clean_error(str(e) or type(e).__name__)
                    close_code = getattr(e, "code", None)
                    break
                now = self._clock()
                if msg is not None:
                    self.handle_message(msg, now)
                self.periodic(now)
                if self._state == "streaming" and streamed_at is None:
                    streamed_at = now
                # Only accelerometer samples keep the session alive: light
                # or gyroscope frames alone are useless for crash detection.
                last = self._last_accel_at if self._last_accel_at is not None else started
                if now - last >= IDLE_RECONNECT_S:
                    reason = (f"no accelerometer data from SensorServer for "
                              f"{IDLE_RECONNECT_S:.0f} s (app stopped? sensors allowed?)")
                    break
                if now >= next_forward_check:
                    next_forward_check = now + 1.0
                    spec, why = self.forward_spec()
                    if spec is None or spec[0] != port:
                        # The next cycle treats whatever comes as a new
                        # forward (shortest backoff).
                        self._fwd_seen = None
                        self._set_state("waiting_forward", error=why)
                        return
        finally:
            self._conn = None
            self._connected_at = None
            try:
                conn.close()
            except Exception:
                pass
        if self._stop.is_set():
            return
        if self._want_gyro and self._session_frames == 0 and isinstance(close_code, int) \
                and 4000 <= close_code <= 4999:
            # SensorServer closes with an application code (4xxx) when it
            # cannot serve a requested sensor: go on without the gyroscope.
            self._want_gyro = False
            log.warning("Phone sensors: SensorServer refused the request (%s) — retrying "
                        "without the gyroscope (a tumbling phone that falls is then "
                        "recognised only by |a| < %.1f g)", reason, FREEFALL_G)
        now = self._clock()
        if streamed_at is not None and now - streamed_at >= BACKOFF_RESET_AFTER_S:
            self._delay = BACKOFF_MIN_S
        self._fail(reason or "connection ended")

    def _fail(self, error: str, max_delay: float = BACKOFF_MAX_S) -> None:
        """Error state, next attempt after the backoff (doubling, capped at
        ``max_delay``)."""
        if self._stop.is_set():
            return
        now = self._clock()
        cap = min(max_delay, BACKOFF_MAX_S)
        delay = min(self._delay, cap)
        self._retry_at = now + delay
        self._delay = min(delay * 2, cap)
        error = clean_error(error)
        self._set_state("error", error=error)
        if error != self._logged_error:
            self._logged_error = error
            log.warning("Phone sensors: %s — next attempt in %.0f s", error, delay)
        else:
            log.debug("Phone sensors: %s — next attempt in %.0f s", error, delay)

    # ── frames ────────────────────────────────────────────────────────────

    def handle_message(self, raw: Any, now: float) -> None:
        """One WebSocket message (worker thread)."""
        if self._sec_start is None or not 0 <= now - self._sec_start < 1.0:
            self._sec_start = now
            self._sec_count = 0
        self._sec_count += 1
        if self._sec_count > MAX_FRAMES_PER_S:
            self.stats["dropped_rate"] += 1
            # The second is truncated: its statistics are incomplete even
            # though the measured rate still looks good.
            self.accel.mark_overrun()
            return
        parsed, why = parse_frame(raw)
        if parsed is None:
            self.stats[why] += 1
            return
        kind, values, ts_ns = parsed
        self._last_frame_at = now
        self._session_frames += 1
        if kind == TYPE_LIGHT:
            self.light.add(values[0])
            self.stats["light"] += 1
            return
        t = self._sensor_time(ts_ns, now)
        if kind == TYPE_GYRO:
            self.accel.add_gyro(t, *values)
            self.stats["gyro"] += 1
            if self.stats["gyro"] == 1:
                log.info("Phone sensors: gyroscope frames arriving — a phone tumbling out of "
                         "its holder is recognised as a fall")
            return
        late = self.accel.late
        if self.accel.add(t, *values, arrival=now):
            self.stats["accel"] += 1
            self._last_accel_at = now
            if self.accel.late > late:
                self.stats["late"] += self.accel.late - late

    def _sensor_time(self, ts_ns: Optional[int], now: float) -> float:
        """The sample's time: the phone's sensor clock while it is plausible
        on this connection, else the arrival time.

        Plausible = after CLOCK_CHECK_S of arrival time it has advanced by
        at least CLOCK_MIN_RATIO of it. Timestamps in another unit than ns
        or a broken app would otherwise stall every time window (they are
        trimmed by sensor time) and read as rate 0. Steps back and big jumps
        only re-anchor the check (the pipeline restarts on those anyway)."""
        if ts_ns is None or self._clock_bad:
            return now
        t = ts_ns / 1e9
        anchor = self._clock_anchor
        if anchor is None or t < anchor[0] or anchor[2] != self.accel.resets \
                or not 0 <= now - anchor[1]:
            self._clock_anchor = (t, now, self.accel.resets)
            return t
        elapsed = now - anchor[1]
        if elapsed < CLOCK_CHECK_S:
            return t
        if (t - anchor[0]) - elapsed > GAP_RESET_S:
            self._clock_anchor = (t, now, self.accel.resets)
            return t
        if t - anchor[0] >= CLOCK_MIN_RATIO * elapsed:
            self._clock_anchor = (t, now, self.accel.resets)
            return t
        self._clock_bad = True
        msg = ("Phone sensors: SensorServer timestamps advanced %.6f s in %.1f s — not "
               "nanoseconds? Using the arrival time for this connection")
        if not self._clock_bad_logged:
            self._clock_bad_logged = True
            log.warning(msg, t - anchor[0], elapsed)
        else:
            log.debug(msg, t - anchor[0], elapsed)
        # New time base: the windows and the lag baseline start over.
        self.accel.restart()
        return now

    def periodic(self, now: float) -> None:
        """Publications and state (called after every receive)."""
        self._apply_recalibration()
        if self.calib.new_reference:
            self.calib.new_reference = False
            self._save_reference()
        drifted = self.calib.drifted
        if drifted != self._drift_logged:
            self._drift_logged = drifted
            if drifted:
                log.warning("Phone sensors: gravity is %.1f deg away from the calibrated "
                            "direction — calib_ok off (phone moved in the holder? steep "
                            "ramp?); after re-mounting delete %s and restart BCM (or "
                            "publish phone_sensors.cmd.recalibrate)",
                            self.calib.drift_deg() or 0.0, self._state_path)
            else:
                log.info("Phone sensors: gravity back within %.0f deg of the calibration",
                         DRIFT_CLEAR_DEG)
        self._log_stats(now)
        accel_fresh = self._last_accel_at is not None and \
            0 <= now - self._last_accel_at < STALE_S
        if self.accel.pending and (self._last_g_pub is None
                                   or not 0 <= now - self._last_g_pub < G_PUBLISH_S):
            self._last_g_pub = now
            self._publish(TOPIC_G, self.accel.snapshot(self._wall(), now))
        if accel_fresh:
            self._set_state("streaming")
            self._logged_error = ""
        else:
            # No accelerometer sample for STALE_S — since the last one, or
            # since the connection if none came at all.
            ref = self._last_accel_at if self._last_accel_at is not None \
                else self._connected_at
            if ref is not None and now - ref >= STALE_S:
                self._set_state("stale")
        if self._state == "streaming":
            lux = self.light.due(now)
            if lux is not None:
                self._publish(TOPIC_LUX, {"lux": lux, "ts": round(self._wall(), 3)})

    def _log_stats(self, now: float) -> None:
        """One warning a minute at most when the phone sent bad frames."""
        if self._stats_logged_at is not None and \
                0 <= now - self._stats_logged_at < STATS_LOG_EVERY_S:
            return
        self._stats_logged_at = now
        new = {k: self.stats[k] - self._stats_logged.get(k, 0) for k in BAD_COUNTERS}
        self._stats_logged = {k: self.stats[k] for k in BAD_COUNTERS}
        if any(new.values()):
            log.warning("Phone sensors: frames ignored since the last report: %s",
                        ", ".join(f"{k}={v}" for k, v in new.items() if v))

    def _apply_recalibration(self) -> None:
        with self._ev_lock:
            req = self._recal_req
        if req == self._recal_seen:
            return
        self._recal_seen = req
        self.calib.reset()
        log.info("Phone sensors: recalibration requested — keep the car still for %.0f s",
                 CALIB_MIN_QUIET_S)

    def _save_reference(self) -> None:
        ref = self.calib.ref
        if ref is None:
            return
        try:
            save_reference(self._state_path, ref, self._wall())
            log.info("Phone sensors: gravity reference saved (%.3f, %.3f, %.3f) to %s",
                     ref[0], ref[1], ref[2], self._state_path)
        except (OSError, TypeError, ValueError) as e:
            log.warning("Phone sensors: saving the gravity reference failed (%s) — it "
                        "is used until restart", clean_error(e))

    # ── publication ───────────────────────────────────────────────────────

    def _publish(self, topic: str, value: Any, force: bool = False) -> None:
        # After stop() only the final "disabled" state goes out — a frame
        # still being processed must not publish behind it.
        if self._stop.is_set() and not force:
            return
        try:
            self._bus.publish(topic, value)
        except Exception:
            log.exception("Publishing %s failed", topic)

    def _set_state(self, state: str, error: str = "", force: bool = False) -> bool:
        """Publish ``phone_sensors.state`` on change. True if published."""
        with self._state_lock:
            return self._set_state_locked(state, error, force)

    def _set_state_locked(self, state: str, error: str, force: bool) -> bool:
        if self._stop.is_set() and not force:
            return False
        rate = round(self.accel.rate_hz, 1) if state in ("streaming", "stale") else 0.0
        payload = {"state": state, "rate_hz": rate,
                   "calib_ok": self.calib.calib_ok if state != "disabled" else False,
                   "error": clean_error(error) if state in ("error", "waiting_forward") else ""}
        old = self._state_payload
        if old is not None and old["state"] == state and old["calib_ok"] == payload["calib_ok"] \
                and old["error"] == payload["error"]:
            prev = old["rate_hz"]
            if abs(rate - prev) < max(RATE_REPUBLISH * max(prev, rate), 1.0):
                return False
        if old is None or old["state"] != state:
            self._since = self._wall()
            # "error" is logged by _fail (with the backoff); "connecting"
            # repeats with every retry — debug only.
            if state == "connecting":
                log.debug("Phone sensors: %s -> %s", self._state, state)
            elif state != "error":
                log.info("Phone sensors: %s -> %s", self._state, state)
        self._state = state
        self._state_payload = payload
        self._publish(TOPIC_STATE, dict(payload, since=self._since), force=True)
        return True


def start_phone_sensors(config, event_bus, hal=None, **kwargs) -> PhoneSensors:
    """Module entry point (``modules.phone_sensors``): builds the object and
    starts its one daemon thread; every socket operation happens there."""
    sensors = PhoneSensors(config, event_bus)
    sensors.start()
    return sensors
