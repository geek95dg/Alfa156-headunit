"""Ostatni postój — where the car last stood, from BCM's own GPS.

Why it is built this way
------------------------
The test car has no clean ignition-off: the engine stops and the power is
simply cut, so "save on shutdown" alone would almost never run. The module
therefore keeps the latest plausible fix in memory and saves it
(atomically, ``data/last_park.json``) when:

* the car has stood still for :data:`STILL_SAVE_S` seconds — speed ≤
  :data:`STILL_KMH`, or, when the GPS publishes no speed (``speed: None``
  when RMC/VTG is stale), fixes staying within :data:`STILL_RADIUS_M` of one
  anchor point. A missing speed is "unknown", never "still": otherwise every
  fix while driving would count as a stop;
* the car is moving and the last write is :data:`MOVING_SAVE_S` old — so the
  last plausible fix before a power cut is on disk even when the engine is
  stopped within a few seconds of parking (a later stop overwrites it, and a
  red-light stop is overwritten by the next save too);
* ``tracking.trip_ended`` (the route logger closed a trip),
* ``vehicle.ignition_raw`` goes True → False (the Arduino sensor hub's
  ``IGN:`` line; only with ``sensor_hub_port`` — without it this trigger
  does not exist and the "still" / "moving" saves are the main ones), or
  ``power.shutting_down`` (the buffered build shuts down cleanly).

"still" and "moving" are written only when the fix is more than
:data:`MOVE_M` metres from the saved one and at most once per
:data:`WRITE_FLOOR_S` seconds (fsync on the bus dispatcher thread must stay
rare); trip end, ignition off and shutdown bypass both limits. On the test
car the saved spot is thus the last fix about 10–30 s before the power cut.

Published ``park.last_position`` (at start from the file, then on every
save)::

    {lat, lon, ts, reason: still|moving|trip_end|ignition_off|shutdown, source}

Shown in Settings ("Ostatni postój") and on ``/trips`` as escaped links to
OpenStreetMap and ``geo:`` — built by the page from the two numbers only.
The file holds only those numbers; anything else in it is ignored, and a
damaged file is treated as "nothing saved yet". Positions never leave the
car from here (the Traccar module is the phone's job).

Switch: ``modules.last_park`` (requires ``location``); config
``last_park.path`` (default ``data/last_park.json``).
"""

from __future__ import annotations

import json
import math
import os
import threading
import time
from typing import Any, Callable, Optional

from src.core.fsutil import atomic_write_json
from src.core.logger import get_logger
from src.network._proc import _cfg_get

log = get_logger("location.last_park")

TOPIC = "park.last_position"
DEFAULT_PATH = "data/last_park.json"
REASONS = ("still", "moving", "trip_end", "ignition_off", "shutdown")
#: Reasons that only follow the GPS stream (rate-limited, deduplicated).
PERIODIC_REASONS = ("still", "moving")
#: Speed (km/h) that still counts as standing (GPS noise at a standstill).
STILL_KMH = 3.0
#: Standing this long = a stop worth saving (the power may be cut soon).
STILL_SAVE_S = 10.0
#: Without a speed: fixes within this radius of the anchor count as standing.
STILL_RADIUS_M = 10.0
#: While moving, the fix is written at most this often (last fix before a cut).
MOVING_SAVE_S = 30.0
#: No "still"/"moving" write sooner than this after the previous write.
WRITE_FLOOR_S = 10.0
#: A new "still"/"moving" point is written only this far from the saved one.
MOVE_M = 25.0
#: A fix older than this is not "the current position" any more.
FIX_MAX_AGE_S = 120.0
FILE_MAX = 4096
TS_MIN = 1_600_000_000
TS_MAX = 4_000_000_000


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in metres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371000.0 * math.asin(min(1.0, math.sqrt(h)))


def _finite(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def valid_record(obj: Any) -> Optional[dict]:
    """The saved / published record in canonical form, or None."""
    if not isinstance(obj, dict):
        return None
    lat, lon, ts = obj.get("lat"), obj.get("lon"), obj.get("ts")
    if not (_finite(lat) and _finite(lon) and _finite(ts)):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0) \
            or not TS_MIN <= ts <= TS_MAX:
        return None
    reason = obj.get("reason")
    source = obj.get("source")
    return {"lat": round(float(lat), 6), "lon": round(float(lon), 6), "ts": int(ts),
            "reason": reason if reason in REASONS else "still",
            "source": source if isinstance(source, str) and source.isalnum()
            and len(source) <= 16 else ""}


class LastPark:
    """See the module docstring.

    Args:
        event_bus: EventBus.
        config: BCMConfig or nested dict.
        clock / wall: monotonic and wall seconds (tests pass fakes).
    """

    def __init__(self, event_bus: Any, config: Any = None,
                 clock: Callable[[], float] = time.monotonic,
                 wall: Callable[[], float] = time.time) -> None:
        self.bus = event_bus
        path = _cfg_get(config, "last_park.path", DEFAULT_PATH)
        self.path = path if isinstance(path, str) and path else DEFAULT_PATH
        self._clock = clock
        self._wall = wall
        self._lock = threading.Lock()
        self._fix: Optional[dict] = None          # {lat, lon, at, source}
        self._still_since: Optional[float] = None
        self._anchor: Optional[tuple] = None      # (lat, lon) for speed-less fixes
        self._last_write_at: Optional[float] = None
        self._ign_last: Optional[bool] = None
        self._saved: Optional[dict] = self._load()
        self._started = False

    # ── file ──────────────────────────────────────────────────────────────

    def _load(self) -> Optional[dict]:
        try:
            with open(self.path, "rb") as f:
                raw = f.read(FILE_MAX + 1)
        except FileNotFoundError:
            return None
        except OSError as e:
            log.warning("Ostatni postój: nie mogę odczytać %s (%s)", self.path, e)
            return None
        if len(raw) > FILE_MAX:
            return None
        try:
            return valid_record(json.loads(raw.decode("utf-8")))
        except (ValueError, UnicodeDecodeError, RecursionError):
            log.warning("Ostatni postój: uszkodzony plik %s — pomijam", self.path)
            return None

    def _save_locked(self, reason: str) -> Optional[dict]:
        """Write the current fix (under the lock); returns the record to
        publish (outside the lock) or None."""
        fix = self._fix
        if fix is None or self._clock() - fix["at"] > FIX_MAX_AGE_S:
            return None
        saved = self._saved
        if reason in PERIODIC_REASONS and saved is not None \
                and distance_m(saved["lat"], saved["lon"], fix["lat"], fix["lon"]) <= MOVE_M:
            return None
        record = valid_record({"lat": fix["lat"], "lon": fix["lon"], "ts": self._wall(),
                               "reason": reason, "source": fix["source"]})
        if record is None:
            return None
        try:
            directory = os.path.dirname(self.path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            atomic_write_json(self.path, record, mode=0o600)
        except (OSError, TypeError, ValueError) as e:
            log.error("Ostatni postój: zapis %s nie powiódł się (%s)", self.path, e)
            return None
        self._saved = record
        self._last_write_at = self._clock()
        return record

    def _publish(self, record: Optional[dict]) -> None:
        if record is None:
            return
        try:
            self.bus.publish(TOPIC, dict(record))
        except Exception:
            log.exception("Publishing %s failed", TOPIC)

    # ── bus (dispatcher thread: only a small file write) ──────────────────

    def _on_position(self, topic: str, value: Any, ts: Any = None) -> None:
        if not isinstance(value, dict) or value.get("fix") is False:
            return
        lat, lon = value.get("lat"), value.get("lon")
        if not (_finite(lat) and _finite(lon)) or not (-90 <= lat <= 90 and -180 <= lon <= 180) \
                or (lat == 0 and lon == 0):
            return
        speed = value.get("speed")
        source = value.get("source")
        now = self._clock()
        with self._lock:
            self._fix = {"lat": float(lat), "lon": float(lon), "at": now,
                         "source": source if isinstance(source, str) else ""}
            anchor = self._anchor
            left_anchor = anchor is None or \
                distance_m(anchor[0], anchor[1], float(lat), float(lon)) > STILL_RADIUS_M
            if left_anchor:
                self._anchor = (float(lat), float(lon))
            if _finite(speed):
                moving = speed > STILL_KMH
            else:
                # No speed from the GPS = unknown: decide by displacement.
                moving = left_anchor
            if moving:
                self._still_since = None
                reason = "moving"
                due = self._last_write_at is None or now - self._last_write_at >= MOVING_SAVE_S
            else:
                if self._still_since is None:
                    self._still_since = now
                reason = "still"
                due = now - self._still_since >= STILL_SAVE_S
            if not due or (self._last_write_at is not None
                           and now - self._last_write_at < WRITE_FLOOR_S):
                return
            record = self._save_locked(reason)
        self._publish(record)

    def _on_event(self, reason: str) -> None:
        with self._lock:
            record = self._save_locked(reason)
        if record is not None:
            log.info("Ostatni postój zapisany (%s)", reason)
        self._publish(record)

    def _on_trip_ended(self, topic: str, value: Any, ts: Any = None) -> None:
        self._on_event("trip_end")

    def _on_ignition_raw(self, topic: str, value: Any, ts: Any = None) -> None:
        # The sensor hub repeats ``IGN:`` every 2 s (STATE_REFRESH_MS), so only
        # a True → False edge saves; a first False after start/reconnect does not.
        if not isinstance(value, bool):
            return
        with self._lock:
            edge = self._ign_last is True and value is False
            self._ign_last = value
        if edge:
            self._on_event("ignition_off")

    def _on_shutdown(self, topic: str, value: Any, ts: Any = None) -> None:
        if value:
            self._on_event("shutdown")

    def _subscriptions(self) -> tuple:
        return (("gps.position", self._on_position),
                ("tracking.trip_ended", self._on_trip_ended),
                ("vehicle.ignition_raw", self._on_ignition_raw),
                ("power.shutting_down", self._on_shutdown))

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        for topic, cb in self._subscriptions():
            self.bus.subscribe(topic, cb)
        with self._lock:
            saved = dict(self._saved) if self._saved is not None else None
        self._publish(saved)

    def stop(self) -> None:
        if not self._started:
            return
        self._started = False
        for topic, cb in self._subscriptions():
            try:
                self.bus.unsubscribe(topic, cb)
            except Exception:
                pass

    def last(self) -> Optional[dict]:
        with self._lock:
            return dict(self._saved) if self._saved is not None else None


def start_last_park(config=None, event_bus=None, hal=None, **kwargs) -> LastPark:
    module = LastPark(event_bus, config=config)
    module.start()
    return module
