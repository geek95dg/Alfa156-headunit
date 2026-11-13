"""Buffer bank monitor — 12 V AGM bank measured by the sensor hub (BATT:).

The M910q runs from a 12 V AGM buffer bank (docs/ZASILANIE_BUFOROWANE.md).
``arduino/sensor_hub`` can measure it (FEATURE_BATT_ADC: voltage through a
divider; FEATURE_BATT_INA226: voltage and current) and sends ``BATT:``;
``src/input/arduino_serial.py`` turns that into ``arduino.battery_voltage``
(V) and ``arduino.battery_current`` (A, + = charging). This module turns
those into a state the UI and other modules can use.

It used to be written for a single 18650 Li-ion cell (4.2 / 3.7 / 3.3 / 3.0 V)
and never received any data (no firmware sent BATT:) — §13.4 of the document
above. Thresholds now follow §13.4 for the AGM bank and live in the
``battery`` config block (:data:`DEFAULTS`).

Enabled by ``modules.battery`` (off in every shipped config): it needs the
sensor hub built with one of the FEATURE_BATT_* switches.

Published (only when the value changes)::

    battery.voltage       float V, median of the last ``smoothing_samples``
    battery.current       float A (+ charging), only with a current sensor
    battery.state         charging | full | ok | low | critical | unknown
    battery.pct           int 0-100, linear resting estimate between
                          critical_v (0 %) and full_v (100 %); None if unknown
    battery.pct_reliable  bool — False while charging, under load, or when
                          there is no current reading to prove the bank rests
                          (a loaded or charging bank does not show its resting
                          voltage, so the estimate is only a hint then)
    battery.low           bool, on the edge only (True entering low/critical,
                          False on recovery)
    battery.critical      bool, on the edge only

States: ``charging`` when V > ``charging_v`` or I > ``charging_current_a``;
otherwise by voltage with hysteresis — once low it stays low until V rises
above ``low_v + hysteresis_v`` (critical likewise, full until it drops below
``full_v - hysteresis_v``), so a bank sitting at the threshold under a
pulsing load does not flap. No sample for ``stale_sec`` ⇒ ``unknown`` (the
sensor hub is gone, or the INA226 stopped answering).

There is NO automatic shutdown here: the hardware low-voltage disconnect
(LVD, 11.0 V) owns that and acts even when BCM hangs. ``critical_v`` sits
above the LVD point so BCM gets to warn first.
"""

import math
import statistics
import threading
import time
from collections import deque
from typing import Any, Callable, Optional

from src.core.logger import get_logger

log = get_logger("battery")

# Defaults for the ``battery`` config block (12 V AGM, §13.4).
DEFAULTS: dict[str, float] = {
    "full_v": 12.85,             # resting, fully charged
    "nominal_v": 12.40,          # resting, roughly half — reference only,
                                 # checked for ordering, not a state boundary
    "low_v": 11.80,
    "critical_v": 11.20,         # above the LVD (11.0 V) so BCM can warn first
    "hysteresis_v": 0.10,
    "charging_v": 13.20,         # above any resting voltage → charger is on
    "charging_current_a": 0.2,   # net current into the bank above this
    "current_sign": 1,           # -1 if the shunt is wired the other way
    "smoothing_samples": 5,      # median window (BATT: arrives every 2 s)
    "stale_sec": 30,             # no BATT: for this long → unknown
}

# Plausibility of the bus values (arduino_serial checks the same range; the
# bus may be fed by something else, e.g. a simulator).
V_MIN = 5.0
V_MAX = 20.0
A_MAX = 100.0
CHECK_INTERVAL_S = 5.0          # how often the background thread looks for staleness

STATES = ("charging", "full", "ok", "low", "critical", "unknown")

# Valid range per numeric key (values outside are clamped, non-numbers
# replaced by the default).
_RANGES: dict[str, tuple[float, float]] = {
    "full_v": (V_MIN, V_MAX),
    "nominal_v": (V_MIN, V_MAX),
    "low_v": (V_MIN, V_MAX),
    "critical_v": (V_MIN, V_MAX),
    "hysteresis_v": (0.0, 1.0),
    "charging_v": (V_MIN, V_MAX),
    "charging_current_a": (0.0, A_MAX),
    "smoothing_samples": (1, 31),
    "stale_sec": (5, 3600),
}


def _cfg_get(config: Any, dotpath: str, default: Any = None) -> Any:
    """Read ``a.b.c`` from a BCMConfig (dotted ``get``) or nested dicts."""
    if config is None:
        return default
    getter = getattr(config, "get", None)
    if callable(getter) and not isinstance(config, dict):
        try:
            value = getter(dotpath)
        except Exception:
            value = None
        if value is not None:
            return value
    node = config
    for key in dotpath.split("."):
        if isinstance(node, dict) and key in node:
            node = node[key]
        else:
            return default
    return node


def _is_number(value: Any) -> bool:
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value))


def load_settings(config: Any) -> dict[str, float]:
    """``battery`` block merged over :data:`DEFAULTS`, validated.

    A typo must not turn the monitor into a false alarm: non-numbers fall
    back to the default, numbers are clamped to a sane range, and thresholds
    that are out of order (critical < low < nominal < full < charging) are
    replaced by the defaults as a set.
    """
    block = _cfg_get(config, "battery", {})
    if not isinstance(block, dict):
        block = {}
    out: dict[str, float] = dict(DEFAULTS)
    for key, (lo, hi) in _RANGES.items():
        value = block.get(key)
        if value is None:
            continue
        if not _is_number(value):
            log.warning("battery.%s=%r is not a number — using %s", key, value, DEFAULTS[key])
            continue
        out[key] = min(max(value, lo), hi)
    out["smoothing_samples"] = int(out["smoothing_samples"])
    sign = block.get("current_sign", DEFAULTS["current_sign"])
    if _is_number(sign) and sign in (1, -1):
        out["current_sign"] = int(sign)
    else:
        log.warning("battery.current_sign=%r must be 1 or -1 — using 1", sign)
        out["current_sign"] = 1
    order = ("critical_v", "low_v", "nominal_v", "full_v", "charging_v")
    if any(out[a] >= out[b] for a, b in zip(order, order[1:])):
        log.warning("battery thresholds out of order (%s) — using the defaults",
                    ", ".join(f"{k}={out[k]}" for k in order))
        for k in order:
            out[k] = DEFAULTS[k]
    return out


class BatteryMonitor:
    """Turns ``arduino.battery_voltage/_current`` into ``battery.*`` (see module doc)."""

    def __init__(self, event_bus: Any, config: Any = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.bus = event_bus
        self._cfg = load_settings(config)
        self._clock = clock
        self._lock = threading.Lock()           # sample deques
        # tick() runs on the serial thread (each sample) AND on the stale
        # checker; computing under _lock but publishing after releasing it
        # let the two interleave, so an older result could be published
        # after a newer one (e.g. "unknown" after a fresh "ok"). One
        # evaluation-and-publish at a time. Re-entrant: with a synchronous
        # bus a subscriber may end up calling tick() again on this thread.
        # Holding it while publishing is fine — publish only queues (the
        # production bus dispatches on its own thread).
        self._tick_lock = threading.RLock()
        n = int(self._cfg["smoothing_samples"])
        self._volts: deque[tuple[float, float]] = deque(maxlen=n)
        self._amps: deque[tuple[float, float]] = deque(maxlen=n)
        self._level: Optional[str] = None       # voltage band, kept for hysteresis
        self._published: dict[str, Any] = {}
        self._low = False
        self._critical = False
        self._running = False
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self.bus.subscribe("arduino.battery_voltage", self._on_voltage)
        self.bus.subscribe("arduino.battery_current", self._on_current)

    # ── inputs ─────────────────────────────────────────────────────────────

    def _on_voltage(self, topic: str, value: Any, ts: float) -> None:
        if not _is_number(value) or not V_MIN <= value <= V_MAX:
            log.debug("battery: ignoring implausible voltage %r", value)
            return
        with self._lock:
            self._volts.append((self._clock(), float(value)))
        self.tick()

    def _on_current(self, topic: str, value: Any, ts: float) -> None:
        if not _is_number(value) or abs(value) > A_MAX:
            log.debug("battery: ignoring implausible current %r", value)
            return
        with self._lock:
            self._amps.append((self._clock(), float(value) * self._cfg["current_sign"]))
        # No tick here: current and voltage come from the same BATT: line and
        # arduino_serial publishes the current first, so the voltage event
        # that follows evaluates both. Ticking here too would evaluate a
        # half-updated pair and could flap the state for a moment.

    # ── evaluation ─────────────────────────────────────────────────────────

    def _fresh_median(self, samples: deque, now: float) -> Optional[float]:
        stale = self._cfg["stale_sec"]
        values = [v for t, v in samples if now - t <= stale]
        if not values:
            return None
        return round(statistics.median(values), 4)

    def _classify(self, volts: float) -> str:
        c = self._cfg
        h = c["hysteresis_v"]
        prev = self._level
        if volts < c["critical_v"] or (
                prev == "critical" and volts <= round(c["critical_v"] + h, 4)):
            return "critical"
        if volts < c["low_v"] or (
                prev in ("low", "critical") and volts <= round(c["low_v"] + h, 4)):
            return "low"
        if volts >= c["full_v"] or (
                prev == "full" and volts >= round(c["full_v"] - h, 4)):
            return "full"
        return "ok"

    def _pct(self, volts: float) -> int:
        c = self._cfg
        span = c["full_v"] - c["critical_v"]
        pct = (volts - c["critical_v"]) / span * 100.0
        return int(round(min(max(pct, 0.0), 100.0)))

    def tick(self) -> None:
        """Re-evaluate and publish what changed (called per sample and by
        the background thread, which is what notices a stale bank).

        Evaluation and publishing form one critical section
        (``_tick_lock``), so results reach the bus in the order they were
        computed.
        """
        with self._tick_lock:
            updates: list[tuple[str, Any]] = []
            with self._lock:
                now = self._clock()
                volts = self._fresh_median(self._volts, now)
                amps = self._fresh_median(self._amps, now)
            c = self._cfg
            if volts is None:
                state, pct, reliable = "unknown", None, False
            else:
                charging = volts > c["charging_v"] or (
                    amps is not None and amps > c["charging_current_a"])
                self._level = self._classify(volts)
                state = "charging" if charging else self._level
                pct = self._pct(volts)
                reliable = (not charging and amps is not None
                            and abs(amps) <= c["charging_current_a"])
                updates.append(("battery.voltage", round(volts, 2)))
                if amps is not None:
                    updates.append(("battery.current", round(amps, 2)))
            updates += [("battery.state", state), ("battery.pct", pct),
                        ("battery.pct_reliable", reliable)]
            changed = [(t, v) for t, v in updates if self._published.get(t, object()) != v]
            for t, v in changed:
                self._published[t] = v
            edges = self._edges(state, volts)
            for topic, value in changed + edges:
                self.bus.publish(topic, value)

    def _edges(self, state: str, volts: Optional[float]) -> list[tuple[str, bool]]:
        """battery.low / battery.critical on transitions only (under ``_tick_lock``).

        ``unknown`` leaves both flags as they were: a lost sensor says nothing
        about the bank, and flipping "low" off then on again would be noise.
        """
        if state == "unknown" or volts is None:
            return []
        level = self._level
        low = level in ("low", "critical")
        critical = level == "critical"
        out: list[tuple[str, bool]] = []
        if low != self._low:
            self._low = low
            out.append(("battery.low", low))
            if low:
                log.warning("Buffer bank LOW: %.2f V (low_v %.2f V)", volts, self._cfg["low_v"])
            else:
                log.info("Buffer bank back above low: %.2f V", volts)
        if critical != self._critical:
            self._critical = critical
            out.append(("battery.critical", critical))
            if critical:
                log.error("Buffer bank CRITICAL: %.2f V (critical_v %.2f V) — the "
                          "hardware LVD cuts power at ~11.0 V; BCM does not shut "
                          "down by itself", volts, self._cfg["critical_v"])
            else:
                log.info("Buffer bank back above critical: %.2f V", volts)
        return out

    # ── lifecycle ──────────────────────────────────────────────────────────

    @property
    def state(self) -> str:
        return self._published.get("battery.state", "unknown")

    @property
    def settings(self) -> dict[str, float]:
        return dict(self._cfg)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._stop.clear()
        self.tick()                     # announce "unknown" until data arrives
        interval = min(CHECK_INTERVAL_S, self._cfg["stale_sec"] / 3.0)
        self._thread = threading.Thread(target=self._loop, args=(interval,),
                                        name="battery-monitor", daemon=True)
        self._thread.start()
        c = self._cfg
        log.info("Buffer bank monitor started (AGM: full %.2f / low %.2f / critical "
                 "%.2f V, charging > %.2f V or > %.2f A, stale after %d s)",
                 c["full_v"], c["low_v"], c["critical_v"], c["charging_v"],
                 c["charging_current_a"], c["stale_sec"])

    def _loop(self, interval: float) -> None:
        while not self._stop.wait(interval):
            try:
                self.tick()
            except Exception:
                log.exception("battery monitor tick failed")

    def stop(self) -> None:
        self._running = False
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        for topic, cb in (("arduino.battery_voltage", self._on_voltage),
                          ("arduino.battery_current", self._on_current)):
            try:
                self.bus.unsubscribe(topic, cb)
            except Exception:
                pass


# Old name (the Li-ion "backup battery" monitor) — kept for imports.
BatteryBackup = BatteryMonitor


def start_battery(config=None, event_bus=None, **kwargs):
    mon = BatteryMonitor(event_bus, config)
    mon.start()
    return mon
