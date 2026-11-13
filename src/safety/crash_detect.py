"""Crash detection: the car phone's accelerometer first, GPS as a fallback.

Why it was rewritten (plan section F, "Detekcja")
-------------------------------------------------
The old ``src/camera/crash_detect.py`` fired on ONE pair of GPS speed
samples (any drop of more than 30 km/h between two readings) or on one value
of ``alarm.sensor.tilt`` above 3 — a topic nobody publishes — and published
``alarm.sensor.shock``, which the car alarm treats as a break-in. It never
needed a camera (the config comment said it did). This module keeps the
idea (protect the DVR, keep a record) but decides with physics, and it is
written so that a later module (``crash_sms``, plan F) can act on an event
without ever being woken by an emergency stop, a pothole or a phone that
fell out of its holder.

Inputs (event bus)
------------------
* ``phone.g_force`` — from ``src/sensors/phone_sensors.py`` (≤ 10 Hz;
  ``{ts, mono, rate_hz, sat, peak_h_g, peak_v_g, dv_h_kmh_150ms, n_over_g,
  freefall_ms, calib_ok, lag_ms, overrun}``; peaks are since the previous
  message, see that module). The preferred source.
* ``gps.speed`` (km/h) — speed samples; ``gps.position`` — position,
  satellites and heading for the event, and its age.

Bus values are dated by their PUBLISH time (arrival minus the dispatcher's
delay from the bus timestamp, at most 2 s), and ``phone.g_force`` messages
by their ``mono``: a stalled dispatcher must neither compress a slow GPS
drop into a steep one nor merge messages that were far apart.

Speed-based decisions (the 25 km/h gate, the GPS-only path, the
``cancelled`` outcome) are only as trustworthy as the GPS inputs: keep UDP
NMEA from 127.0.0.0/8 out of ``hardware.gps.udp.allowed_sources`` and the
GPS forward on a privileged local port (see ``car_phone``).

Accelerometer path (``source: accel``, the only one that may lead to an SMS)
---------------------------------------------------------------------------
An event needs ALL of:

* the highest GPS speed of the last 10 s >= ``min_speed_kmh`` (25) — below
  that a phone cannot tell a parking knock from a door slam, and the plan
  does not promise detection there. With NO speed sample at all (tunnel,
  underground car park, GPS lost) the impact is still an event — logged,
  recorded, DVR protected — but ``sms_eligible`` is False (details
  ``reason: no_gps_speed``);
* horizontal Δv >= ``dv_threshold_kmh`` (15) within ``dv_window_ms`` (150):
  braking at 1 g changes speed by only 5.3 km/h in 150 ms; a 50 km/h impact
  into a barrier sheds ~50 km/h in ~100 ms;
* horizontal peak >= ``g_h_threshold`` (4 g) for >= 3 consecutive samples
  (one spike from a stone hitting the holder is not an impact);

and it is REJECTED when:

* the vertical peak is at least the horizontal one (a pothole or a kerb) —
  only when no sample was clipped: with ``sat`` both peaks are capped by
  the range and the vertical axis also carries gravity's offset, so in a
  severe crash "vertical wins" would depend on the sign of the vertical
  component; the Δv gate already excludes potholes and kerbs;
* the phone was in free fall for >= 80 ms just before (it fell out of the
  holder — the landing is a big spike with no Δv of the car behind it;
  ``phone_sensors`` also counts a tumbling fall, with the gyroscope);
* ``calib_ok`` is False (no gravity reference, or the phone moved in the
  holder by more than 10° — plan G), or the stream runs below
  ``min_rate_hz`` (80 Hz: Δv over 150 ms needs >= 12 samples), or frames
  were dropped in the period (``overrun``), or the data is older than 1 s
  (publish age plus ``lag_ms``, the lag of the samples in it).

Messages of the last 0.35 s (by their ``mono``) are combined before the
check: an impact can straddle two 10 Hz messages (the Δv window ends in
one, the third sample over the threshold falls into the next). A
``vertical`` or ``free_fall`` rejection consumes the messages it judged, so
the same bump cannot fire a moment later from what is left of them.

GPS-only path (``source: gps``; NEVER an SMS)
---------------------------------------------
Used only while there is no valid phone data (module off, no stream, low
rate, not calibrated). GPS speed comes once a second and is filtered by the
phone, so a single pair of samples says nothing; the drop is measured over
at least 2 s (start = the sample 2–4 s before the end that gives the
steepest drop) and normalised by the time it took: an average deceleration
of >= 0.6 g with a drop of >= ``dv_threshold_kmh``, confirmed by the next
sample (no rebound, which a one-sample GPS glitch would show). Because of
the 2 s floor it sees impacts from roughly 45 km/h up (45 km/h in 2 s is
0.64 g). Emergency braking to a standstill looks the same to GPS — that is
why this path only logs, keeps a record and protects the DVR recording.

After an event (both paths)
---------------------------
* ``crash.detected`` ``{event_id (uuid4 hex), ts, source: accel|gps,
  sms_eligible, lat, lon, fix_age_s, sats, speed_before_kmh, dv_kmh,
  peak_g, heading}`` — ``sms_eligible`` is True only for ``accel``;
  ``lat``/``lon`` are the LAST KNOWN position (``fix_age_s`` says how old;
  GPS is often lost right after an impact), None when there never was one;
  ``speed_before_kmh`` is the newest speed sample published before the
  first message of the signature (minus 0.3 s) if at most 3 s older, else
  the highest of the 10 s before it — a GPS sample that already shows the
  impact is never "the speed before"; ``peak_g`` is None for ``gps``.
* ``dvr.protect_segment`` (True), as before, and a dashboard notification
  (``system.notifications``, key ``crash_detected``; plan D3: visible
  without cameras too).
* At most one event per 60 s — except that an SMS-eligible event is never
  swallowed by the cooldown of a non-eligible one (it supersedes it).
* Outcome, ``crash.outcome`` ``{event_id, outcome, reason, ts}``:
  ``stopped`` as soon as a speed sample <= ``confirm_stop_kmh`` (5) comes;
  ``cancelled`` (reason ``no_stop``) when the speed stays above
  ``min_speed_kmh`` for 10 s with no gap over 2.5 s between samples — the
  car simply drove on, it was not a crash; ``unconfirmed`` when neither
  happened within 120 s (e.g. GPS lost). Missing data never cancels.
* A JSON record per event in ``data/crash_events`` (atomic write through
  ``src.core.fsutil``; rewritten with the outcome; the newest 50 are kept,
  never the one just written or the one of the event still watched — with
  a wrong clock a new record can get an old name), written by this
  module's own worker thread — never on the event-bus dispatcher, which
  only computes.

``alarm.sensor.*`` is never published (the alarm reads any value there as a
break-in) and no longer listened to.

Configuration (``crash_detection.*``, code defaults, validated and clamped)
--------------------------------------------------------------------------
``min_speed_kmh`` 25, ``dv_threshold_kmh`` 15, ``dv_window_ms`` 150,
``g_h_threshold`` 4.0, ``min_rate_hz`` 80, ``confirm_stop_kmh`` 5.
``dv_window_ms`` and ``g_h_threshold`` are read by ``phone_sensors`` too
(:func:`load_crash_config`): the Δv window and the over-threshold run are
computed there, on the raw samples.

Compatibility: ``speed_drop_threshold``, ``g_force_threshold`` and
``post_crash_record_sec`` of the old detector are no longer read (one log
line names them); ``src/camera/crash_detect.start_crash_detect`` stays as a
wrapper for one release.
"""

from __future__ import annotations

import collections
import math
import os
import queue
import re
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from src.core.fsutil import atomic_write_json, cleanup_stale_tmp
from src.core.logger import get_logger
from src.network._proc import _cfg_get, _number

log = get_logger("safety.crash_detect")

TOPIC_DETECTED = "crash.detected"
TOPIC_OUTCOME = "crash.outcome"
TOPIC_DVR = "dvr.protect_segment"
G_FORCE_TOPIC = "phone.g_force"

#: Standard gravity (m/s²) — km/h per second per g = 3.6 * 9.80665.
G0 = 9.80665
KMH_PER_S_PER_G = 3.6 * G0

#: Code defaults of ``crash_detection.*`` and their (lo, hi) clamps.
DEFAULTS: dict[str, float] = {
    "min_speed_kmh": 25.0,
    "dv_threshold_kmh": 15.0,
    "dv_window_ms": 150.0,
    "g_h_threshold": 4.0,
    "min_rate_hz": 80.0,
    "confirm_stop_kmh": 5.0,
}
LIMITS: dict[str, tuple[float, float]] = {
    "min_speed_kmh": (10.0, 80.0),
    # Below ~8 km/h in 150 ms hard braking plus a bump would qualify.
    "dv_threshold_kmh": (8.0, 60.0),
    # >= 5 samples at 100 Hz; longer than 300 ms lets braking add up.
    "dv_window_ms": (50.0, 300.0),
    "g_h_threshold": (2.0, 15.0),
    # Δv over 150 ms is meaningless with fewer than ~8 samples.
    "min_rate_hz": (50.0, 400.0),
    "confirm_stop_kmh": (1.0, 15.0),
}
#: Keys of the old detector that are no longer read (compatibility note).
LEGACY_KEYS = ("speed_drop_threshold", "g_force_threshold", "post_crash_record_sec")

#: Window of the "highest fresh speed" condition, and of the speed history.
SPEED_WINDOW_S = 10.0
#: The newest speed sample is "the speed before" only if at most this old.
SPEED_BEFORE_MAX_AGE_S = 3.0
#: "Before" = before the first message of the signature minus this: a
#: message covers the 100 ms before its stamp, plus a margin, so a GPS
#: sample that already shows the impact is never "the speed before".
SPEED_BEFORE_MARGIN_S = 0.3
#: Accelerometer data older than this is not used (plan F) — the message's
#: publish age plus the lag of its samples (``lag_ms``).
GFORCE_MAX_AGE_S = 1.0
#: Bus values are dated by their publish time: arrival minus the
#: dispatcher's delay (wall-clock delta of the bus timestamp), at most this
#: much — a stalled dispatcher must not compress a 4 s drop into 2 s.
BUS_DELAY_MAX_S = 2.0
#: Messages combined for one check (an impact straddles two 10 Hz messages).
GFORCE_COMBINE_S = 0.35
#: Consecutive samples over g_h_threshold an impact needs.
MIN_OVER_SAMPLES = 3
#: Free fall at least this long right before the peak = a dropped phone.
FREEFALL_REJECT_MS = 80.0
#: One event per this many seconds.
COOLDOWN_S = 60.0
#: Speed above min_speed_kmh this long after an event = no crash.
CANCEL_SUSTAIN_S = 10.0
#: Largest gap between speed samples that still counts as "sustained".
SPEED_GAP_S = 2.5
#: An event without stop or cancel within this long is "unconfirmed".
OUTCOME_WATCH_S = 120.0
#: GPS-only path: the drop is measured over at least / at most this long.
GPS_DROP_MIN_S = 2.0
GPS_DROP_MAX_S = 4.0
#: GPS-only path: average deceleration over the drop (in g).
GPS_DECEL_G = 0.6
#: GPS-only path: the confirming sample may be at most this much higher.
GPS_CONFIRM_TOL_KMH = 2.0
#: The confirming sample must follow the candidate within this long.
GPS_CONFIRM_MAX_GAP_S = 2.5
#: Plausible GPS speed (km/h).
MAX_SPEED_KMH = 400.0
#: Records kept in the events directory.
MAX_RECORDS = 50
DEFAULT_EVENTS_DIR = "data/crash_events"
#: Bounded queue of the record writer.
IO_QUEUE_MAX = 32
#: Rejection log lines at most this often (they help tuning thresholds).
REJECT_LOG_EVERY_S = 5.0
#: Rejections that judged the impact itself (not the data quality): the
#: messages used are consumed, so the same impact cannot fire a moment
#: later from what is left of them.
CONSUMING_REJECTIONS = ("vertical", "free_fall")
#: UI notification of an event (system.notifications; the crash modal of
#: the later crash_sms item is separate).
NOTIFY_TTL_S = 60.0

OUTCOMES = ("stopped", "cancelled", "unconfirmed")
SOURCES = ("accel", "gps")
_RECORD_RE = re.compile(r"^crash_\d{8}_\d{6}_[0-9a-f]{8}\.json$")


# ── configuration ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CrashConfig:
    """Validated ``crash_detection.*`` (see the module docstring)."""
    min_speed_kmh: float = DEFAULTS["min_speed_kmh"]
    dv_threshold_kmh: float = DEFAULTS["dv_threshold_kmh"]
    dv_window_ms: float = DEFAULTS["dv_window_ms"]
    g_h_threshold: float = DEFAULTS["g_h_threshold"]
    min_rate_hz: float = DEFAULTS["min_rate_hz"]
    confirm_stop_kmh: float = DEFAULTS["confirm_stop_kmh"]


def load_crash_config(config: Any, logger: Any = None) -> CrashConfig:
    """``crash_detection.*`` → :class:`CrashConfig`. Numbers only (a bool or
    a string falls back to the default with a warning), clamped to
    :data:`LIMITS` — a typo must not turn the detector into a siren or
    switch it off silently. Shared by this module and ``phone_sensors``."""
    lg = logger or log
    section = _cfg_get(config, "crash_detection", {})
    if not isinstance(section, dict):
        section = {}
    values = {}
    for key, default in DEFAULTS.items():
        lo, hi = LIMITS[key]
        raw = section.get(key)
        value = float(_number("crash_detection", raw, default, lo, hi, key, logger=lg))
        if raw is not None and not isinstance(raw, bool) and isinstance(raw, (int, float)) \
                and math.isfinite(raw) and value != raw:
            lg.warning("crash_detection.%s=%r is outside %g..%g — using %g", key, raw, lo, hi,
                       value)
        values[key] = value
    return CrashConfig(**values)


def legacy_keys_present(config: Any) -> list[str]:
    """Keys of the old detector still in the config (they are ignored)."""
    section = _cfg_get(config, "crash_detection", {})
    if not isinstance(section, dict):
        return []
    return [k for k in LEGACY_KEYS if k in section]


# ── input validation (pure) ────────────────────────────────────────────────

def _finite(value: Any, lo: float, hi: float) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    if not math.isfinite(value) or not lo <= value <= hi:
        return None
    return value


def parse_g_force(value: Any) -> Optional[dict[str, Any]]:
    """A ``phone.g_force`` payload, validated; None if unusable.

    Every number must be finite and in a plausible range — the bus is
    in-process, but the values started as WebSocket frames from a phone.
    ``mono`` (monotonic seconds of the publisher) and ``ts`` (epoch) are
    optional: whichever exists dates the message."""
    if not isinstance(value, dict):
        return None
    rate = _finite(value.get("rate_hz"), 0.0, 5000.0)
    peak_h = _finite(value.get("peak_h_g"), 0.0, 200.0)
    peak_v = _finite(value.get("peak_v_g"), 0.0, 200.0)
    dv = _finite(value.get("dv_h_kmh_150ms"), 0.0, 1000.0)
    freefall = _finite(value.get("freefall_ms"), 0.0, 600_000.0)
    n_over = value.get("n_over_g")
    if isinstance(n_over, bool) or not isinstance(n_over, int) or not 0 <= n_over <= 10**6:
        return None
    if None in (rate, peak_h, peak_v, dv, freefall):
        return None
    return {
        "rate_hz": rate, "peak_h_g": peak_h, "peak_v_g": peak_v, "dv_kmh": dv,
        "n_over_g": n_over, "freefall_ms": freefall,
        "calib_ok": value.get("calib_ok") is True,
        "sat": value.get("sat") is True,
        # Frames were dropped in the period (phone_sensors' per-second cap):
        # the statistics are incomplete.
        "overrun": value.get("overrun") is True,
        "mono": _finite(value.get("mono"), 0.0, 1e12),
        "ts": _finite(value.get("ts"), 0.0, 4102444800.0),
        # How late the period's samples arrived (backlog); optional.
        "lag_ms": _finite(value.get("lag_ms"), 0.0, 1e9),
    }


def parse_position(value: Any) -> Optional[dict[str, Any]]:
    """``gps.position`` → ``{lat, lon, sats, heading}`` or None."""
    if not isinstance(value, dict) or value.get("fix") is False:
        return None
    lat = _finite(value.get("lat"), -90.0, 90.0)
    lon = _finite(value.get("lon"), -180.0, 180.0)
    if lat is None or lon is None:
        return None
    sats = value.get("satellites")
    if isinstance(sats, bool) or not isinstance(sats, int) or not 0 <= sats <= 255:
        sats = None
    return {"lat": lat, "lon": lon, "sats": sats,
            "heading": _finite(value.get("heading"), 0.0, 360.0)}


# ── the detector ───────────────────────────────────────────────────────────

class CrashDetector:
    """Decides on crash events from ``phone.g_force`` and GPS speed.

    Args:
        config: BCMConfig or nested dict (``crash_detection.*``).
        event_bus: EventBus (``subscribe``/``unsubscribe``/``publish``).
        clock: monotonic seconds (ages, windows, cooldown) — tests inject.
        wall_clock: epoch seconds (``ts`` of events, record names).
        events_dir: where the JSON records go.
        id_factory: event id generator (tests).

    Bus callbacks only compute under ``self._lock`` and queue the record
    writes; :meth:`tick` (outcome timeouts) and the writes run on the
    module's worker thread (:meth:`start`) or are driven by tests.
    """

    def __init__(self, config: Any, event_bus: Any,
                 clock: Callable[[], float] = time.monotonic,
                 wall_clock: Callable[[], float] = time.time,
                 events_dir: str = DEFAULT_EVENTS_DIR,
                 id_factory: Callable[[], str] = lambda: uuid.uuid4().hex,
                 notify: Optional[Callable[..., Any]] = None) -> None:
        self._bus = event_bus
        self._clock = clock
        self._wall = wall_clock
        self._dir = Path(events_dir)
        self._new_id = id_factory
        if notify is None:
            from src.core.notifications import publish_notification as notify
        self._notify = notify
        self.cfg = load_crash_config(config)
        legacy = legacy_keys_present(config)
        if legacy:
            log.info("crash_detection.%s: no longer read — the detector now uses "
                     "min_speed_kmh/dv_threshold_kmh/dv_window_ms/g_h_threshold/min_rate_hz/"
                     "confirm_stop_kmh (src/safety/crash_detect.py)", "/".join(legacy))

        self._lock = threading.Lock()
        # (mono arrival, km/h) of the last SPEED_WINDOW_S (+ the drop window).
        self._speeds: collections.deque[tuple[float, float]] = collections.deque(maxlen=256)
        # Last valid position and its arrival (mono).
        self._pos: Optional[dict[str, Any]] = None
        self._pos_at: Optional[float] = None
        # Recent valid g_force messages: (stamp, parsed) — the publisher's
        # monotonic time, else the estimated publish time.
        self._g_msgs: collections.deque[tuple[float, dict]] = collections.deque(maxlen=16)
        self._g_last_ok_at: Optional[float] = None
        # GPS-only candidate waiting for its confirming sample:
        # (end mono, end speed, start speed, drop, decel_g).
        self._gps_candidate: Optional[tuple[float, float, float, float, float]] = None
        self._last_event_at: Optional[float] = None
        self._last_event_sms = False
        # The event whose outcome is being watched.
        self._watch: Optional[dict[str, Any]] = None
        self._reject_logged_at: dict[str, float] = {}
        self._stats = collections.Counter()

        self._io: queue.Queue = queue.Queue(maxsize=IO_QUEUE_MAX)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._subscribed = False

    # ── lifecycle ─────────────────────────────────────────────────────────

    def _subscriptions(self) -> tuple:
        return ((G_FORCE_TOPIC, self._on_g_force),
                ("gps.speed", self._on_speed),
                ("gps.position", self._on_position),
                ("power.shutting_down", self._on_shutdown))

    def subscribe(self) -> None:
        if self._subscribed:
            return
        self._subscribed = True
        for topic, cb in self._subscriptions():
            self._bus.subscribe(topic, cb)

    def start(self) -> None:
        """Subscribe and start the worker (records + outcome timeouts)."""
        self.subscribe()
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, daemon=True, name="crash-detect")
            self._thread.start()
        c = self.cfg
        log.info("Crash detector started (accel: >= %.0f km/h, dv >= %.0f km/h in %.0f ms, "
                 ">= %.1f g x%d, >= %.0f Hz; GPS-only fallback: >= %.1f g over >= %.0f s, "
                 "no SMS; records: %s)", c.min_speed_kmh, c.dv_threshold_kmh, c.dv_window_ms,
                 c.g_h_threshold, MIN_OVER_SAMPLES, c.min_rate_hz, GPS_DECEL_G, GPS_DROP_MIN_S,
                 self._dir)

    def stop(self) -> None:
        if self._stop.is_set():
            return
        self._stop.set()
        for topic, cb in self._subscriptions():
            try:
                self._bus.unsubscribe(topic, cb)
            except Exception:
                pass
        try:
            self._io.put_nowait(None)       # wake the worker
        except queue.Full:
            pass

    def _on_shutdown(self, topic: str, value: Any, timestamp: float) -> None:
        if value:
            self.stop()

    def _run(self) -> None:
        try:
            cleanup_stale_tmp(self._dir, ".crash_")
        except (OSError, ValueError):
            log.debug("crash records: stale temporary cleanup failed", exc_info=True)
        while not self._stop.is_set():
            try:
                job = self._io.get(timeout=1.0)
            except queue.Empty:
                job = None
            if job is not None:
                self._write(job)
            try:
                self.tick()
            except Exception:
                log.exception("Crash detector tick failed")
        self.run_pending_io()

    def run_pending_io(self) -> int:
        """Write every queued record now (worker loop, tests). Returns the count."""
        done = 0
        while True:
            try:
                job = self._io.get_nowait()
            except queue.Empty:
                return done
            if job is not None:
                self._write(job)
                done += 1

    # ── read-only views ───────────────────────────────────────────────────

    @property
    def stats(self) -> dict[str, int]:
        """Counters: events by source, rejections by reason, invalid input."""
        with self._lock:
            return dict(self._stats)

    def phone_data_ok(self) -> bool:
        """True while the accelerometer path is usable (then GPS stays quiet)."""
        with self._lock:
            return self._phone_ok_locked(self._clock())

    # ── inputs (bus dispatcher: compute only) ─────────────────────────────

    def _on_speed(self, topic: str, value: Any, timestamp: float) -> None:
        speed = _finite(value, 0.0, MAX_SPEED_KMH)
        if speed is None:
            with self._lock:
                self._stats["invalid_speed"] += 1
            return
        events = []
        with self._lock:
            now = self._clock()
            at = self._published_at(now, timestamp)
            if self._speeds and at < self._speeds[-1][0]:
                at = self._speeds[-1][0]            # keep the history ordered
            self._speeds.append((at, speed))
            self._trim_speeds_locked(at)
            events += self._watch_outcome_locked(at, speed)
            if not self._phone_ok_locked(now):
                events += self._gps_check_locked(at, speed)
            else:
                self._gps_candidate = None
        self._emit(events)

    def _on_position(self, topic: str, value: Any, timestamp: float) -> None:
        pos = parse_position(value)
        if pos is None:
            return
        with self._lock:
            self._pos = pos
            self._pos_at = self._published_at(self._clock(), timestamp)

    def _published_at(self, now: float, bus_ts: Any) -> float:
        """Our monotonic time when a bus value was PUBLISHED: the arrival
        minus the dispatcher's delay (the bus timestamp is wall time),
        clamped to 0..BUS_DELAY_MAX_S so a wall-clock step cannot move it
        far. On the async bus one slow subscriber delays everything after
        it; the GPS drop rate and the windows must not shrink with that."""
        if isinstance(bus_ts, bool) or not isinstance(bus_ts, (int, float)):
            return now
        delay = self._wall() - float(bus_ts)
        if not math.isfinite(delay) or delay <= 0:
            return now
        return now - min(delay, BUS_DELAY_MAX_S)

    def _on_g_force(self, topic: str, value: Any, timestamp: float) -> None:
        msg = parse_g_force(value)
        events = []
        with self._lock:
            if msg is None:
                self._stats["invalid_g_force"] += 1
                return
            now = self._clock()
            age = self._msg_age(msg, now, timestamp)
            if age is not None and msg["lag_ms"] is not None:
                age += msg["lag_ms"] / 1000.0       # samples that came late
            fresh = age is not None and -GFORCE_MAX_AGE_S <= age <= GFORCE_MAX_AGE_S
            if fresh and msg["calib_ok"] and msg["rate_hz"] >= self.cfg.min_rate_hz \
                    and not msg["overrun"]:
                self._g_last_ok_at = now
                self._gps_candidate = None
            stamp = msg["mono"] if msg["mono"] is not None else \
                self._published_at(now, timestamp)
            self._g_msgs.append((stamp, dict(msg, fresh=fresh, stamp=stamp)))
            events += self._accel_check_locked(now)
        self._emit(events)

    def _msg_age(self, msg: dict, now: float, bus_ts: float) -> Optional[float]:
        """Seconds since the message's data was current: its ``mono`` against
        our monotonic clock (immune to wall-clock steps), else ``ts`` /
        the bus timestamp against the wall clock."""
        if msg["mono"] is not None:
            return now - msg["mono"]
        stamp = msg["ts"] if msg["ts"] is not None else bus_ts
        if isinstance(stamp, bool) or not isinstance(stamp, (int, float)):
            return None
        return self._wall() - float(stamp)

    # ── the accelerometer path ────────────────────────────────────────────

    def _phone_ok_locked(self, now: float) -> bool:
        at = self._g_last_ok_at
        return at is not None and 0 <= now - at <= GFORCE_MAX_AGE_S

    def _accel_check_locked(self, now: float) -> list[dict]:
        if not self._g_msgs:
            return []
        # Combined by their own stamps (data time), not by arrival: a late
        # dispatcher must not merge messages that were far apart.
        newest = max(st for st, _m in self._g_msgs)
        recent = [m for st, m in self._g_msgs if 0 <= newest - st <= GFORCE_COMBINE_S]
        if not recent:
            return []
        c = self.cfg
        dv = max(m["dv_kmh"] for m in recent)
        peak_h = max(m["peak_h_g"] for m in recent)
        peak_v = max(m["peak_v_g"] for m in recent)
        n_over = max(m["n_over_g"] for m in recent)
        freefall = max(m["freefall_ms"] for m in recent)
        if not (dv >= c.dv_threshold_kmh and peak_h >= c.g_h_threshold
                and n_over >= MIN_OVER_SAMPLES):
            return []
        # An impact-like signature. Every message it is built from must be
        # trustworthy, else it is not used (the GPS path may still act).
        sat = any(m["sat"] for m in recent)
        reason = ""
        vmax: Optional[float] = None
        if not all(m["fresh"] for m in recent):
            reason = "stale"
        elif not all(m["calib_ok"] for m in recent):
            reason = "uncalibrated"
        elif min(m["rate_hz"] for m in recent) < c.min_rate_hz:
            reason = "low_rate"
        elif any(m["overrun"] for m in recent):
            reason = "overrun"
        elif peak_v >= peak_h and not sat:
            # Only on unclipped data: with a saturated axis both peaks are
            # capped by the range, and the vertical one also carries
            # gravity's offset — in a severe crash the "vertical wins" would
            # depend on the sign of the vertical component, not on physics.
            # The Δv gate already excludes potholes and kerbs.
            reason = "vertical"
        elif freefall >= FREEFALL_REJECT_MS:
            reason = "free_fall"
        else:
            vmax = self._max_speed_locked(now)
            if vmax is not None and vmax < c.min_speed_kmh:
                reason = "slow"
        details = {"dv_kmh": round(dv, 1), "peak_h_g": round(peak_h, 2),
                   "peak_v_g": round(peak_v, 2), "n_over_g": n_over,
                   "freefall_ms": round(freefall), "rate_hz": round(min(
                       m["rate_hz"] for m in recent), 1),
                   "sat": sat, "calib_ok": all(m["calib_ok"] for m in recent)}
        if reason:
            self._reject_locked(now, reason, details)
            if reason in CONSUMING_REJECTIONS:
                self._g_msgs.clear()
            return []
        # No GPS speed at all (tunnel, underground car park, GPS lost): the
        # impact is real, but without a speed it may not lead to an SMS —
        # it is still logged, recorded and the DVR protected.
        sms_eligible = vmax is not None
        if not sms_eligible:
            details["reason"] = "no_gps_speed"
        if self._cooling_down_locked(now, sms_eligible):
            return []
        # One impact = one event: the same messages must not fire again.
        self._g_msgs.clear()
        first = min(m["stamp"] for m in recent)
        speed_before = self._speed_before_locked(first - SPEED_BEFORE_MARGIN_S, now)
        return self._event_locked(now, "accel", dv_kmh=dv, peak_g=peak_h, details=details,
                                  speed_before=speed_before, sms_eligible=sms_eligible)

    def _reject_locked(self, now: float, reason: str, details: dict) -> None:
        self._stats[f"rejected_{reason}"] += 1
        last = self._reject_logged_at.get(reason)
        if last is None or now - last >= REJECT_LOG_EVERY_S:
            self._reject_logged_at[reason] = now
            log.info("Crash detector: impact-like signal rejected (%s): %s", reason, details)

    # ── the GPS-only path ─────────────────────────────────────────────────

    def _gps_check_locked(self, now: float, speed: float) -> list[dict]:
        """GPS-only (no valid phone data). A candidate end sample becomes an
        event when the NEXT sample confirms it (no rebound above it)."""
        cand = self._gps_candidate
        self._gps_candidate = None
        if cand is not None:
            end_at, end_speed, start_speed, drop, decel_g = cand
            if now - end_at <= GPS_CONFIRM_MAX_GAP_S and \
                    speed <= end_speed + GPS_CONFIRM_TOL_KMH:
                if self._cooling_down_locked(now, False):
                    return []
                details = {"start_kmh": round(start_speed, 1), "end_kmh": round(end_speed, 1),
                           "decel_g": round(decel_g, 2)}
                return self._event_locked(now, "gps", dv_kmh=drop, peak_g=None,
                                          details=details, speed_before=start_speed,
                                          sms_eligible=False)
        # Is THIS sample the end of a qualifying drop? The start is the
        # sample 2-4 s back that gives the steepest average deceleration.
        c = self.cfg
        vmax = self._max_speed_locked(now)
        if vmax is None or vmax < c.min_speed_kmh:
            return []
        best: Optional[tuple[float, float, float]] = None      # (decel_g, start, drop)
        for at, v in self._speeds:
            dt = now - at
            drop = v - speed
            if not GPS_DROP_MIN_S <= dt <= GPS_DROP_MAX_S or drop < c.dv_threshold_kmh:
                continue
            decel_g = drop / dt / KMH_PER_S_PER_G
            if best is None or decel_g > best[0]:
                best = (decel_g, v, drop)
        if best is not None and best[0] >= GPS_DECEL_G:
            self._gps_candidate = (now, speed, best[1], best[2], best[0])
        return []

    # ── events and outcome ────────────────────────────────────────────────

    def _cooling_down_locked(self, now: float, sms_eligible: bool) -> bool:
        """One event per COOLDOWN_S — except that an SMS-eligible event is
        never swallowed by a cooldown a non-eligible one started (a GPS-only
        event on hard braking while the phone stream was still reconnecting,
        then the real impact): it supersedes it."""
        at = self._last_event_at
        if at is not None and 0 <= now - at < COOLDOWN_S:
            if sms_eligible and not self._last_event_sms:
                return False
            self._stats["cooldown"] += 1
            return True
        return False

    def _trim_speeds_locked(self, now: float) -> None:
        keep = max(SPEED_WINDOW_S, GPS_DROP_MAX_S) + 1.0
        while self._speeds and now - self._speeds[0][0] > keep:
            self._speeds.popleft()

    def _max_speed_locked(self, now: float) -> Optional[float]:
        values = [v for at, v in self._speeds if 0 <= now - at <= SPEED_WINDOW_S]
        return max(values) if values else None

    def _speed_before_locked(self, before: float, now: float) -> Optional[float]:
        """The speed before the impact: the newest sample published before
        ``before`` if at most 3 s older, else the highest of the 10 s before
        it, else the highest of the last 10 s (None without any)."""
        prior = [(at, v) for at, v in self._speeds if at <= before]
        if prior and before - prior[-1][0] <= SPEED_BEFORE_MAX_AGE_S:
            return prior[-1][1]
        values = [v for at, v in prior if before - at <= SPEED_WINDOW_S]
        if values:
            return max(values)
        return self._max_speed_locked(now)

    def _event_locked(self, now: float, source: str, *, dv_kmh: float,
                      peak_g: Optional[float], details: dict,
                      speed_before: Optional[float], sms_eligible: bool) -> list[dict]:
        """The ``detected`` item — after the ``unconfirmed`` outcome of a
        previous event still being watched (each event gets one outcome)."""
        out = []
        if self._watch is not None:
            out.append(self._outcome_locked("unconfirmed", "superseded", now))
        self._last_event_at = now
        self._last_event_sms = sms_eligible
        self._stats[f"event_{source}"] += 1
        if not sms_eligible and source == "accel":
            self._stats["event_accel_no_speed"] += 1
        pos = self._pos
        fix_age = None if self._pos_at is None else round(max(0.0, now - self._pos_at), 1)
        heading = None
        if pos is not None and fix_age is not None and fix_age <= SPEED_WINDOW_S:
            heading = pos["heading"]
        event = {
            "event_id": self._new_id(),
            "ts": self._wall(),
            "source": source,
            "sms_eligible": bool(sms_eligible and source == "accel"),
            "lat": pos["lat"] if pos else None,
            "lon": pos["lon"] if pos else None,
            "fix_age_s": fix_age,
            "sats": pos["sats"] if pos else None,
            "speed_before_kmh": None if speed_before is None else round(speed_before, 1),
            "dv_kmh": round(dv_kmh, 1),
            "peak_g": None if peak_g is None else round(peak_g, 2),
            "heading": heading,
        }
        self._watch = {"event": event, "at": now, "above_since": None, "last_speed_at": None,
                       "details": details}
        out.append({"kind": "detected", "event": event, "details": details})
        return out

    def _watch_outcome_locked(self, now: float, speed: Optional[float]) -> list[dict]:
        """Stop / cancel / timeout of the watched event (speed None = tick)."""
        w = self._watch
        if w is None:
            return []
        if speed is not None:
            if speed <= self.cfg.confirm_stop_kmh:
                return [self._outcome_locked("stopped", "speed_low", now)]
            last = w["last_speed_at"]
            gap_ok = last is not None and now - last <= SPEED_GAP_S
            if speed > self.cfg.min_speed_kmh:
                if w["above_since"] is None or not gap_ok:
                    w["above_since"] = now
            else:
                w["above_since"] = None
            w["last_speed_at"] = now
            if w["above_since"] is not None and now - w["above_since"] >= CANCEL_SUSTAIN_S:
                return [self._outcome_locked("cancelled", "no_stop", now)]
        if now - w["at"] >= OUTCOME_WATCH_S:
            return [self._outcome_locked("unconfirmed", "timeout", now)]
        return []

    def _outcome_locked(self, outcome: str, reason: str, now: float) -> dict:
        event = self._watch["event"]
        details = self._watch["details"]
        self._watch = None
        return {"kind": "outcome", "event": event, "details": details,
                "outcome": {"event_id": event["event_id"], "outcome": outcome,
                            "reason": reason, "ts": self._wall()}}

    def tick(self) -> None:
        """Outcome timeout without speed samples (GPS lost after an impact)."""
        with self._lock:
            events = self._watch_outcome_locked(self._clock(), None)
        self._emit(events)

    def _emit(self, events: list[dict]) -> None:
        """Publish (outside the lock) and queue the record write."""
        for item in events:
            event = item["event"]
            if item["kind"] == "detected":
                if event["source"] == "accel":
                    log.critical("CRASH DETECTED (accelerometer): %s %s", event, item["details"])
                else:
                    log.warning("Possible crash from GPS speed only (logged, DVR protected, "
                                "never an SMS): %s %s", event, item["details"])
                self._publish(TOPIC_DVR, True)
                self._publish(TOPIC_DETECTED, dict(event))
                self._announce(event)
                self._queue_write(event, item["details"], "pending")
            else:
                outcome = item["outcome"]
                log.info("Crash event %s: %s (%s)", outcome["event_id"], outcome["outcome"],
                         outcome["reason"])
                self._publish(TOPIC_OUTCOME, dict(outcome))
                self._queue_write(event, item["details"], outcome["outcome"])

    def _publish(self, topic: str, value: Any) -> None:
        try:
            self._bus.publish(topic, value)
        except Exception:
            log.exception("Publishing %s failed", topic)

    def _announce(self, event: dict) -> None:
        """A dashboard notification (plan D3: the event must be visible
        without cameras too). Fixed Polish texts with numbers only — nothing
        from outside reaches them."""
        dv = event.get("dv_kmh")
        dv_txt = f" (zmiana prędkości ok. {dv:.0f} km/h)" if isinstance(dv, (int, float)) \
            else ""
        if event["source"] == "gps":
            title, severity = "Gwałtowne zatrzymanie (GPS)", "warning"
            desc = f"Możliwa stłuczka{dv_txt} — nagranie zabezpieczone, zdarzenie zapisane"
        elif event["sms_eligible"]:
            title, severity = "Wykryto możliwą stłuczkę", "danger"
            desc = f"Nagranie zabezpieczone, pozycja zapisana{dv_txt}"
        else:
            title, severity = "Wykryto silne uderzenie", "danger"
            desc = f"Brak prędkości z GPS{dv_txt} — nagranie zabezpieczone, zdarzenie zapisane"
        try:
            self._notify(self._bus, title, desc, severity=severity, icon="car_crash",
                         ttl=NOTIFY_TTL_S, key="crash_detected")
        except Exception:
            log.debug("crash notification failed", exc_info=True)

    # ── records (worker thread) ───────────────────────────────────────────

    def _queue_write(self, event: dict, details: dict, outcome: str) -> None:
        try:
            self._io.put_nowait({"event": dict(event), "details": dict(details),
                                 "outcome": outcome, "saved_at": self._wall()})
        except queue.Full:
            log.warning("Crash record queue full — record of %s not written", event["event_id"])

    def record_name(self, event: dict) -> str:
        # UTC: names sort by time across DST changes (pruning relies on it).
        stamp = time.strftime("%Y%m%d_%H%M%S", time.gmtime(event["ts"]))
        return f"crash_{stamp}_{event['event_id'][:8]}.json"

    def _write(self, job: dict) -> None:
        event = job["event"]
        if not re.fullmatch(r"[0-9a-f]{8,64}", str(event.get("event_id", ""))):
            log.error("Crash record with an invalid id not written")
            return
        path = self._dir / self.record_name(event)
        record = {"version": 1, "event": event, "outcome": job["outcome"],
                  "details": job["details"], "saved_at": job["saved_at"]}
        try:
            atomic_write_json(path, record, mode=0o600, indent=2, sort_keys=True)
        except (OSError, TypeError, ValueError):
            log.exception("Crash record %s not written", path)
            return
        log.info("Crash record saved: %s (%s)", path, job["outcome"])
        with self._lock:
            watched = self._watch["event"] if self._watch is not None else None
        keep = {path.name}
        if watched is not None:
            keep.add(self.record_name(watched))
        self._prune(keep)

    def _prune(self, keep: frozenset | set = frozenset()) -> None:
        """Keep the newest :data:`MAX_RECORDS` records (names sort by time).

        ``keep`` (the record just written, the one of the event still being
        watched) is never removed: with a wrong system clock (RTC reset
        before bcm-timesync) a new record gets an OLD name and would be the
        first to go."""
        try:
            names = sorted(n for n in os.listdir(self._dir) if _RECORD_RE.fullmatch(n))
        except OSError:
            return
        for name in names[:-MAX_RECORDS] if len(names) > MAX_RECORDS else []:
            if name in keep:
                continue
            try:
                os.unlink(self._dir / name)
            except OSError:
                log.debug("cannot remove old crash record %s", name, exc_info=True)


def start_crash_detect(config, event_bus, hal=None, **kwargs) -> CrashDetector:
    """Module entry point (``modules.crash_detect``). Builds the detector,
    subscribes and starts its worker thread; no I/O here."""
    detector = CrashDetector(config, event_bus)
    detector.start()
    return detector
