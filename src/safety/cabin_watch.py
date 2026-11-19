"""Cabin watch on the parked car (plan I) — BCM's side.

Why it is built this way
------------------------
When the car is parked BCM is off (the test car has no buffered power), so
the cabin watch itself runs ON THE CAR PHONE, in the Termux agent
(tools/car_phone/termux/bcm_agent.py, ``CabinWatch``), as a layer on top of
the parking guard: the same sensor stream plus the light sensor (the
interior lamp), 3 photos with the front camera when the lamp and motion
(or a tilt, a door signal, 3 weak signals with at least two of them
motion — light flashes alone never count) say someone is in the car, a
frame-difference analysis on the phone, and the alarm SMS after the entry
window unless the owner proves themselves (which also deletes the photos).
The photos never leave the phone in this version.

What BCM adds while it runs — read-only, nothing here can arm, disarm or
take a photo:

* ``GET /v1/cabin`` every :data:`POLL_S` on the module's own worker (never
  the bus dispatcher, never module start), published on
  ``park.cabin_state`` (on change) for the Settings row "Czuwanie kabiny":
  state, camera layer (or why it is off), light sensor, Pillow, the entry
  window, photo count and size, the last event.
* ``park.cabin_event`` — the HISTORY: every cabin event once when first
  seen (also the ones from while BCM was off, after the next start) and
  again when its outcome changes (pending → alarm / owner / logged …).
  A bus topic only — never ``alarm.sensor.*`` (that is the siren alarm
  module, which treats every value as a break-in) and no notification
  (the parking guard already shows ONE for the car's alarm).

The owner proof is the parking guard's job (src/safety/parking_guard.py
disarms the phone on the owner's Bluetooth connection edge); the phone
then cancels a waiting cabin alarm and deletes its photos itself.

The settings (``cabin_watch.entry_s``, ``diff_pct``, ``mask``) reach the
phone through car_phone_agent's config push (``cabin_*``, only while
``modules.cabin_watch`` is on); the toggle on the phone mirrors
``modules.cabin_watch``. The only switch is ``modules.cabin_watch``
(requires ``car_phone_agent`` and ``parking_guard``); there is no
``enabled`` sub-key.

Published ``park.cabin_state`` (on change)::

    {state, camera, light_sensor, lux, pillow, log_only, entry_until,
     photos_n, photos_mb, events_today, last_event | None, error}

    state: unknown (no answer yet) | off | idle | watching | pending
    error: '' | no_agent | agent_outdated | no_answer | agent_error

``park.cabin_event``::

    {id, ts, reasons [door|light|shake|tilt|power], weak, photos, outcome,
     verdict, changed_pct, ref, camera}
"""

from __future__ import annotations

import queue
import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Optional

from src.core.logger import get_logger
from src.network import car_phone_agent as _cpa

log = get_logger("safety.cabin_watch")

TOPIC_STATE = "park.cabin_state"
TOPIC_EVENT = "park.cabin_event"
STATES = ("unknown",) + _cpa.CABIN_STATES
ERRORS = ("", "no_agent", "agent_outdated", "no_answer", "agent_error")
#: GET /v1/cabin every 30 s while the phone answers; backoff while not.
POLL_S = 30.0
POLL_FAIL_MIN_S = 10.0
POLL_FAIL_MAX_S = 120.0
IDLE_WAIT_S = 30.0
#: Event ids remembered for the history (the phone keeps the last 32).
SEEN_MAX = 64
QUEUE_MAX = 8
#: Agent errors that mean "nothing answered" (vs. an agent that refused).
_NO_ANSWER = ("no_forward", "connect", "dropped", "timeout", "busy", "stopped", "no_secret")


def _error_of(res: dict) -> str:
    """An agent API result → this module's error code."""
    err = res.get("error") or ""
    if err == "no_agent":
        return "no_agent"
    if err == "not_found":
        return "agent_outdated"         # an agent before 1.3.0 has no /v1/cabin
    if err in _NO_ANSWER:
        return "no_answer"
    return "agent_error"


class CabinWatch:
    """See the module docstring.

    Args:
        config: BCMConfig or nested dict (unused today; kept for the
            module entry signature and future settings).
        event_bus: EventBus.
        agent_getter: returns the running CarPhoneAgent or None.
        clock: monotonic seconds (tests pass a fake).
    """

    def __init__(self, config: Any, event_bus: Any,
                 agent_getter: Optional[Callable[[], Any]] = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._config = config
        self._bus = event_bus
        self._agent_getter = agent_getter or _cpa.get_agent
        self._clock = clock
        self._q: queue.Queue = queue.Queue(maxsize=QUEUE_MAX)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._subscribed = False
        # Worker state.
        self._view: Optional[dict[str, Any]] = None
        self._error = ""
        self._next_poll = 0.0
        self._poll_delay = POLL_FAIL_MIN_S
        self._logged_error = ""
        self._seen: "OrderedDict[str, str]" = OrderedDict()
        self._published: Optional[dict[str, Any]] = None

    # ── lifecycle ─────────────────────────────────────────────────────────

    def _subscriptions(self) -> tuple:
        return ((_cpa.TOPIC, self._on_agent),
                ("power.shutting_down", self._on_shutdown))

    def start(self) -> None:
        """Subscribe and start the worker; no I/O here."""
        if not self._subscribed:
            self._subscribed = True
            for topic, cb in self._subscriptions():
                self._bus.subscribe(topic, cb)
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, daemon=True, name="cabin-watch")
            self._thread.start()

    def stop(self) -> None:
        global _INSTANCE
        if self._stop.is_set():
            return
        self._stop.set()
        with _INSTANCE_LOCK:
            if _INSTANCE is self:
                _INSTANCE = None
        for topic, cb in self._subscriptions():
            try:
                self._bus.unsubscribe(topic, cb)
            except Exception:
                pass
        self._kick()

    def _on_shutdown(self, topic: str, value: Any, timestamp: float) -> None:
        if value:
            self.stop()

    def _on_agent(self, topic: str, value: Any, timestamp: float) -> None:
        """The agent (re)appeared: poll at once (dispatcher: enqueue only)."""
        if isinstance(value, dict) and value.get("state") == "ok":
            self._kick()

    def _kick(self) -> None:
        try:
            self._q.put_nowait(True)
        except queue.Full:
            pass

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                wait = self.step()
            except Exception:
                log.exception("Cabin watch: worker pass failed")
                wait = POLL_FAIL_MIN_S
            try:
                self._q.get(timeout=max(0.05, min(wait, IDLE_WAIT_S)))
            except queue.Empty:
                continue
            if self._error or self._view is None:
                # The agent (re)appeared after a failure: ask now, not in
                # up to 2 min. A healthy module keeps its 30 s rhythm (the
                # agent republishes "ok" every 60 s).
                self._next_poll = 0.0

    # ── worker ────────────────────────────────────────────────────────────

    def _agent(self) -> Any:
        try:
            return self._agent_getter()
        except Exception:
            return None

    def step(self) -> float:
        """One poll when due; returns the sleep."""
        now = self._clock()
        if now >= self._next_poll:
            self._poll(now)
        self._publish()
        return max(0.05, min(IDLE_WAIT_S, self._next_poll - now))

    def _poll(self, now: float) -> None:
        agent = self._agent()
        if agent is None:
            self._failed(now, "no_agent")
            return
        res = agent.cabin_status()
        view = _cpa.parse_cabin_view(res.get("data")) if res.get("ok") else None
        if view is None:
            self._failed(now, _error_of(res) if not res.get("ok") else "agent_error")
            return
        self._view, self._error = view, ""
        self._logged_error = ""
        self._poll_delay = POLL_FAIL_MIN_S
        self._next_poll = now + POLL_S
        self._history(view)

    def _failed(self, now: float, error: str) -> None:
        self._error = error
        self._next_poll = now + self._poll_delay
        self._poll_delay = min(self._poll_delay * 2, POLL_FAIL_MAX_S)
        if error != self._logged_error:
            self._logged_error = error
            if error == "agent_outdated":
                log.warning("Cabin watch: the agent on the phone has no cabin watch (older than "
                            "1.3.0) — copy the new tools/car_phone/termux/bcm_agent.py "
                            "(docs §5.13)")
            else:
                log.info("Cabin watch: no state from the phone (%s)", error)

    def _history(self, view: dict) -> None:
        """``park.cabin_event`` for every event first seen or whose outcome
        changed (oldest first) — the history, also of events from while
        BCM was off."""
        for ev in view.get("events") or []:
            if self._seen.get(ev["id"]) == ev["outcome"]:
                continue
            self._seen[ev["id"]] = ev["outcome"]
            self._seen.move_to_end(ev["id"])
            while len(self._seen) > SEEN_MAX:
                self._seen.popitem(last=False)
            log.info("Cabin watch: event %s at %s — %s (%s, %d photo(s))", ev["id"],
                     time.strftime("%d.%m %H:%M", time.localtime(ev["ts"])), ev["outcome"],
                     "+".join(ev["reasons"]) or "-", ev["photos"])
            try:
                self._bus.publish(TOPIC_EVENT, dict(ev, reasons=list(ev["reasons"])))
            except Exception:
                log.exception("Publishing %s failed", TOPIC_EVENT)

    # ── publication ───────────────────────────────────────────────────────

    def payload(self) -> dict[str, Any]:
        view = self._view or {}
        last = view.get("last_event")
        return {
            "state": view.get("state", "unknown") if view else "unknown",
            "camera": view.get("camera", "unknown"),
            "light_sensor": view.get("light_sensor", "unknown"),
            "lux": view.get("lux"),
            "pillow": view.get("pillow"),
            "log_only": view.get("log_only") if view else None,
            "entry_until": view.get("entry_until"),
            "photos_n": int(view.get("photos_n") or 0),
            "photos_mb": view.get("photos_mb"),
            "events_today": int(view.get("events_today") or 0),
            "last_event": dict(last, reasons=list(last["reasons"])) if last else None,
            "error": self._error if self._error in ERRORS else "agent_error",
        }

    @property
    def state(self) -> Optional[dict[str, Any]]:
        with self._lock:
            return dict(self._published) if self._published is not None else None

    def _publish(self) -> None:
        payload = self.payload()
        with self._lock:
            if payload == self._published:
                return
            self._published = payload
        try:
            self._bus.publish(TOPIC_STATE, dict(payload))
        except Exception:
            log.exception("Publishing %s failed", TOPIC_STATE)


# ── the running instance ──────────────────────────────────────────────────

_INSTANCE: Optional[CabinWatch] = None
_INSTANCE_LOCK = threading.Lock()


def get_cabin_watch() -> Optional[CabinWatch]:
    """The running module, or None (not enabled, not started, stopped)."""
    with _INSTANCE_LOCK:
        return _INSTANCE


def start_cabin_watch(config, event_bus, hal=None, **kwargs) -> CabinWatch:
    """Module entry point (``modules.cabin_watch``): builds the object,
    subscribes and starts its one daemon thread; every agent request
    happens there."""
    global _INSTANCE
    module = CabinWatch(config, event_bus)
    with _INSTANCE_LOCK:
        _INSTANCE = module
    module.start()
    return module
