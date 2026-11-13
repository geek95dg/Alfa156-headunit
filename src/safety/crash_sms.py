"""SMS to the driver's contacts after a crash: the countdown window and the
state machine behind it (plan F, "Przebieg").

Why it is built this way
------------------------
After an impact the head unit may lose power within a second (the test car
has no buffered supply: the engine stalls, the ignition drops, BCM is gone).
So BCM never sends anything itself and never owns the deadline: the moment
``crash_detect`` reports an SMS-eligible event, this module ARMS the Termux
agent on the car phone (``car_phone_agent`` → ``POST /v1/crash`` with the
countdown) and from that answer on the PHONE holds the deadline — without a
cancel it sends the SMS on time even if BCM died. BCM only shows the window
("ANULUJ – nic się nie stało", "Wyślij teraz"), forwards the driver's
decision and reports what the phone did. The SMS text is built on the phone
from fixed GSM-7 templates; BCM sends validated numbers only.

Enabled by ``modules.crash_sms`` only (requires ``crash_detect``,
``phone_sensors`` and ``car_phone_agent``; off in code and in both shipped
configs). There is no ``enabled`` key in ``crash_detection.sms``.

States (``crash.sms_state`` → ``state``)
---------------------------------------
* ``idle`` — nothing happened since the module started (no saved event).
* ``armed`` — an event was detected, the phone has not confirmed it yet.
  Arm requests are retried every :data:`ARM_RETRY_EVERY_S` until the
  phone's countdown would have to be stretched (``countdown_s`` minus the
  phone's 15 s minimum, at least :data:`ARM_RETRY_WINDOW_S`): an impact
  that makes the USB link re-enumerate takes car_phone up to one
  ``check_sec`` (30 s) to bring the forward back, and losing the alarm
  then would defeat the module. A late arm gives the phone what is left
  of the shown countdown, so the deadline on screen never moves.
* ``pending`` — the phone holds the event and counts down.
* ``sending`` — the deadline passed (or "Wyślij teraz"), the phone sends.
* ``sent`` / ``partial`` / ``failed`` — the phone's outcome (``failed`` is
  also used when the phone refused the event: no recipients, crash_sms off
  on the phone, the phone's own limit — ``error`` says which).
* ``cancelled`` — the driver cancelled (confirmed by the phone, or locally
  when no arm request can have reached it).
* ``failed_no_phone`` — the phone could not be reached while arming. Only
  when no arm request can have reached it (``connect`` = refused / not
  written, ``no_forward`` …) does the window say "SMS NIE zostanie
  wysłany" (``may_send`` false). When one may have (a timeout, a
  connection ``dropped`` after the request was written — the agent saves
  the event BEFORE it answers), ``may_send`` is true: the window says the
  SMS MAY still go out and keeps ANULUJ; the event keeps being looked up
  (``GET /v1/crash/<id>``) for a while, and if the phone does hold it the
  countdown comes back (the phone WILL send).
* ``limited`` — BCM's own limit (``cooldown_min``, ``max_per_day``):
  nothing is armed.

The event bus callbacks only validate and enqueue; every agent call runs on
the module's ONE worker thread (never the bus dispatcher, never module
start). The event is saved atomically (``data/crash_sms.json``, 0600) on
every state change; after a restart the worker looks it up on the phone and
the window comes back while it is still pending.

Published ``crash.sms_state`` (on change, and once a second while a
countdown runs — the window's clock)::

    {state, event_id, ts, countdown_s, countdown_left_s, deadline_ts,
     recipients_n, phone_ok, dry_run, forced_dry_run_reason, results,
     cancel_sms, error, modal, cancel_pending, send_now_pending,
     can_follow_up, may_send, unconfirmed, test}

``modal``: the window should be on screen (active states, and a final state
for :data:`FINAL_SHOW_S` after it was reached). ``results``: per recipient
``{state, verified}`` — never a number. ``may_send``: see
``failed_no_phone``. ``unconfirmed``: the phone stopped answering and
BCM's deadline passed :data:`UNCONFIRMED_AFTER_S` ago — the phone may
already have sent; the window turns into a closable "no confirmation"
view (no more beeping) while the event keeps being looked up.

Commands: ``crash.cmd.cancel`` / ``crash.cmd.send_now`` (bus, e.g. the SWC
action ``crash_cancel``; value ``{"event_id"?, "source"?}``) and the
loopback-only routes in web_viewer through :meth:`CrashSms.command` /
:meth:`CrashSms.request_test` (instance from :func:`get_crash_sms`).
``crash.outcome`` ``cancelled`` (the car drove on above 25 km/h for 10 s)
cancels the pending event too: a driver who drives on is not hurt, and must
not be made to tap the screen while driving.

Who may cancel what (:meth:`CrashSms._cancellable`): a cancel that does not
come from the window itself — a steering-wheel button (it keeps its normal
action, e.g. volume, so it is pressed for other reasons too), a bus
command, ``auto`` — counts ONLY while the countdown runs (``armed`` /
``pending`` with time left, or a ``failed_no_phone`` the phone may hold,
before its deadline): nothing can have left the phone yet. Never during
``sending`` and never after a sent SMS — there the phone would send
"ODWOLANE - kierowca potwierdzil..." to everybody. The window's ANULUJ
(``ui``, always with the event id it shows) may also cancel while
``sending``. "Jestem OK" after a sent SMS is its own action
(``follow_up``, UI only, with the event id), so a late ANULUJ tap is never
turned into a cancel SMS. Both are checked again on the worker, because
the state may move (pending → sending) between the request and its turn.

Safety gate (``crash_detection.sms.dry_run: false``)
---------------------------------------------------
Honoured only when ALL hold; otherwise the event is armed with
``dry_run: true`` (the phone only logs it) and ``forced_dry_run_reason``
says why (shown in the window and in Settings, logged once per reason):

* the agent is paired and healthy: state ``ok``, ``paired``, config in sync
  (no ``config_pending``/``config_refused``), a signed answer within
  :data:`AGENT_FRESH_S`, and the phone's own config is not ``dry_run``;
* a REAL test SMS was confirmed in "wysłane" for every CURRENT recipient
  within :data:`TEST_MAX_AGE_S` (the agent's ``last_verified_test_ts``; the
  agent clears it when the recipients or the SIM slot change).

The phone's sensors (streaming, ``rate_hz >= crash_detection.min_rate_hz``,
``calib_ok``) are NOT checked for an event: an ``accel`` event with
``sms_eligible`` already proves them on the very samples that triggered it
(crash_detect checks them), and a second look after the impact could only
turn a real crash into test mode (the published ``rate_hz`` lags by up to
10 %, and the impact itself may stall the stream). They are part of the
idle indicator in Settings only (from the latest ``phone.g_force``).

Configuration (``crash_detection.sms.*``, code defaults)
-------------------------------------------------------
``dry_run`` true (only an explicit ``false`` leaves test mode),
``countdown_sec`` 45 (15..120), ``recipients`` [] (≤ 3, E.164, only in
local.yaml / Settings), ``sim_slot`` 0, ``vehicle_label`` "ALFA 156",
``cooldown_min`` 10 (1..1440), ``max_per_day`` 3 (1..20),
``follow_up_cancel`` true. ``recipients``/``sim_slot``/``vehicle_label``/
``follow_up_cancel`` go to the phone through ``car_phone_agent``'s config
push; the phone enforces its own fixed limits (1 per 10 min, 3 a day) too.

What this does NOT promise: delivery (no delivery reports), an SMS when the
phone is dead or out of coverage, a call to 112 (manual, later batch).
"""

from __future__ import annotations

import json
import math
import queue
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from src.core.fsutil import atomic_write_json
from src.core.logger import get_logger
from src.network import car_phone_agent as _cpa
from src.network._proc import _cfg_get, _number, clean_error

log = get_logger("safety.crash_sms")

TOPIC_STATE = "crash.sms_state"
TOPIC_DETECTED = "crash.detected"
TOPIC_OUTCOME = "crash.outcome"
CMD_CANCEL = "crash.cmd.cancel"
CMD_SEND_NOW = "crash.cmd.send_now"
SENSORS_TOPIC = "phone_sensors.state"
G_TOPIC = "phone.g_force"
STATE_FILE = "data/crash_sms.json"
STATE_FILE_MAX = 32 * 1024

STATES = ("idle", "armed", "pending", "sending", "sent", "partial", "failed", "cancelled",
          "failed_no_phone", "limited")
ACTIVE = ("armed", "pending", "sending")
FINAL = ("sent", "partial", "failed", "cancelled", "failed_no_phone", "limited")
#: Why dry_run: false was not honoured (``forced_dry_run_reason``).
FORCED_REASONS = ("", "agent_not_ready", "no_verified_test", "test_too_old",
                  "sensors_not_streaming", "sensor_rate_low", "not_calibrated")
#: ``error`` of the event (what the window explains; never free text).
ERRORS = ("", "no_recipients", "crash_sms_off", "rate_limited", "cooldown", "daily_limit",
          "bad_request", "unknown_event", "no_phone", "expired", "refused")
#: Per-recipient states the agent reports (``results[].state``).
RCPT_STATES = ("queued", "wait", "retry", "sending", "submitted", "verifying", "sent",
               "sent_dry", "failed", "skipped")
#: Recipient states that mean "the crash SMS may have left the phone".
RCPT_OUT = ("sending", "submitted", "verifying", "sent", "sent_dry")
#: The agent's event states → ours.
AGENT_TO_STATE = {"armed": "pending", "pending": "sending", "sending": "sending",
                  "sent": "sent", "partial": "partial", "failed": "failed",
                  "cancelled": "cancelled"}
#: Refusals of POST /v1/crash: final, retrying does not help.
ARM_REFUSALS = {"no_recipients": "no_recipients", "crash_sms_off": "crash_sms_off",
                "rate_limited": "rate_limited", "too_many_events": "rate_limited",
                "bad_request": "bad_request"}
#: Transport failures after which the request certainly did NOT reach the
#: agent: no forward, ``connect`` (refused, or broken before the request
#: was fully written — car_phone_agent reports a break AFTER that as
#: ``dropped``), the agent refused our signature, our own side. Anything
#: else (a timeout, ``dropped``, a broken answer) may have been executed:
#: the agent saves an armed event BEFORE it answers.
NOT_DELIVERED = ("no_forward", "connect", "busy", "stopped", "no_secret", "unpaired",
                 "bad_auth", "stale_ts", "not_running")
TEST_REQUESTS = ("", "queued", "sending", "accepted", "error")
TEST_ERRORS = ("", "no_recipients", "rate_limited", "no_phone", "refused", "config_pending")
SOURCES = ("ui", "swc", "auto", "bus")
ACTIONS = ("cancel", "send_now", "follow_up")

EVENT_ID_RE = re.compile(r"^[0-9a-f]{8,32}$")

#: Arm requests are retried at least this long after the event — and
#: normally until the shown countdown has only the phone's minimum
#: (15 s) left (see :meth:`CrashSms._arm_window`); then ``failed_no_phone``.
ARM_RETRY_WINDOW_S = 10.0
ARM_RETRY_EVERY_S = 2.0
#: A saved event still being armed is armed again after a restart only if
#: it is younger than this (a process restart or a reboot after the power
#: dropped at the impact, not hours later) — and arming is retried until
#: it is this old: after a reboot car_phone needs adb, the device and a
#: USB re-enumeration (tethering) before the agent's forward is back,
#: easily more than 10 s.
REARM_MAX_AGE_S = 120.0
#: Look-ups while the phone counts down / sends.
POLL_PENDING_S = 2.0
POLL_SENDING_S = 3.0
#: Backoff while the phone does not answer during an event.
RETRY_MIN_S = 2.0
RETRY_MAX_S = 10.0
#: An event is followed (polls, cancel retries) at most this long.
ACTIVE_MAX_S = 3600.0
#: A saved active event is resumed after a restart only if younger.
RESUME_MAX_AGE_S = 3600.0
#: ``failed_no_phone`` after a request that may have arrived: keep looking
#: the event up this long after its deadline (the phone may send it).
RECONCILE_AFTER_DEADLINE_S = 600.0
RECONCILE_EVERY_S = 10.0
#: The window stays up this long after a final state (then ``modal`` off).
FINAL_SHOW_S = 60.0
#: ... and at most this long after the deadline of an event that is still
#: "active" because the phone does not answer (it is followed further).
MODAL_ACTIVE_MAX_S = 900.0
#: The phone has not answered and BCM's deadline passed this long ago: the
#: window stops counting/beeping and says the phone may already have sent
#: (``unconfirmed``) — closable, and gone after :data:`FINAL_SHOW_S` more.
UNCONFIRMED_AFTER_S = 10.0
#: Idle indicator: the latest ``phone.g_force`` must be at most this old.
G_FRESH_S = 2.0
#: "Jestem OK" after a sent SMS: the agent sends one cancel SMS within 15 min.
FOLLOW_UP_WINDOW_S = 900.0
#: Safety gate: a signed health answer at most this old ...
AGENT_FRESH_S = 120.0
#: ... and a verified real test SMS at most this old.
TEST_MAX_AGE_S = 30 * 86400.0
#: Idle: re-evaluate the gate (no I/O) this often, publish on change.
GATE_REFRESH_S = 10.0
#: After a test SMS was accepted, ask the agent for fresh health this often
#: for this long (its delivery check takes 30 s and more).
TEST_WATCH_S = 300.0
TEST_KICK_EVERY_S = 20.0
HISTORY_MAX = 20
DAY_S = 86400.0
QUEUE_MAX = 64
MAX_WAIT_S = 30.0

DEFAULTS: dict[str, Any] = {"dry_run": True, "countdown_sec": 45, "cooldown_min": 10,
                            "max_per_day": 3, "follow_up_cancel": True}


# ── configuration ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SmsConfig:
    """``crash_detection.sms.*`` that this module reads (validated)."""
    dry_run: bool = True
    countdown_sec: int = 45
    cooldown_min: int = 10
    max_per_day: int = 3
    follow_up_cancel: bool = True


class _OnceLogger:
    """Logs each distinct warning once. The config is read live (every
    publication, the gate refresh every 10 s, once a second during a
    countdown): a typo in ``crash_detection.sms`` must give one line, not
    tens of thousands a day on a unit that runs 24/7. Bounded."""

    MAX = 32

    def __init__(self, logger: Any) -> None:
        self._log = logger
        self._seen: list[str] = []
        self._lock = threading.Lock()

    def warning(self, fmt: str, *args: Any) -> None:
        try:
            text = fmt % args if args else fmt
        except (TypeError, ValueError):
            text = fmt
        with self._lock:
            if text in self._seen:
                return
            self._seen.append(text)
            del self._seen[:-self.MAX]
        self._log.warning("%s", text)


_CFG_LOG = _OnceLogger(log)


def load_sms_config(config: Any, logger: Any = None) -> SmsConfig:
    """Read and clamp the block. Only an explicit ``dry_run: false`` leaves
    test mode (a typo such as ``"false"`` or ``0`` stays in it) — the same
    rule as the config pushed to the phone (car_phone_agent). Each invalid
    value is warned about once (see :class:`_OnceLogger`)."""
    lg = logger or _CFG_LOG
    sms = _cfg_get(config, "crash_detection.sms", {})
    if not isinstance(sms, dict):
        sms = {}
    raw_dry = sms.get("dry_run", True)
    if raw_dry is not True and raw_dry is not False:
        lg.warning("crash_detection.sms.dry_run=%r is not true/false — test mode", raw_dry)
    countdown = _number("crash_detection.sms", sms.get("countdown_sec"), 45,
                        _cpa.COUNTDOWN_MIN_S, _cpa.COUNTDOWN_MAX_S, "countdown_sec", logger=lg)
    cooldown = _number("crash_detection.sms", sms.get("cooldown_min"), 10, 1, 1440,
                       "cooldown_min", logger=lg)
    per_day = _number("crash_detection.sms", sms.get("max_per_day"), 3, 1, 20,
                      "max_per_day", logger=lg)
    return SmsConfig(dry_run=raw_dry is not False,
                     countdown_sec=int(round(countdown)),
                     cooldown_min=int(round(cooldown)),
                     max_per_day=int(round(per_day)),
                     follow_up_cancel=sms.get("follow_up_cancel", True) is not False)


def configured_recipients(config: Any) -> list[str]:
    """The valid recipients (E.164, at most 3, no duplicates) — exactly what
    ``car_phone_agent`` pushes to the phone."""
    return list(_cpa.desired_config(config)["recipients"])


def _finite(value: Any, lo: float, hi: float) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) and lo <= value <= hi else None


def parse_detected(value: Any) -> Optional[dict[str, Any]]:
    """A ``crash.detected`` payload that may lead to an SMS, else None.

    Only ``source: accel`` with ``sms_eligible: true`` (the GPS-only path
    never sends an SMS — plan F). The informational numbers are passed on
    as None when missing or implausible (``arm_crash`` validates again)."""
    if not isinstance(value, dict):
        return None
    if value.get("sms_eligible") is not True or value.get("source") != "accel":
        return None
    eid = value.get("event_id")
    if not isinstance(eid, str) or not EVENT_ID_RE.fullmatch(eid):
        return None
    ts = _finite(value.get("ts"), _cpa.EVENT_TS_MIN, _cpa.EVENT_TS_MAX)
    lat = _finite(value.get("lat"), -90.0, 90.0)
    lon = _finite(value.get("lon"), -180.0, 180.0)
    if lat is None or lon is None:
        lat = lon = None
    return {"event_id": eid, "ts": ts, "lat": lat, "lon": lon,
            "fix_age_s": _finite(value.get("fix_age_s"), 0.0, 86400.0),
            "speed_kmh": _finite(value.get("speed_before_kmh"), 0.0, 400.0),
            "dv_kmh": _finite(value.get("dv_kmh"), 0.0, 400.0)}


def parse_agent_view(view: Any, event_id: str) -> Optional[dict[str, Any]]:
    """The agent's ``_event_view`` of OUR event, validated, or None.

    The answer is signed (car_phone_agent checked it), but a newer agent
    or a bug must not put anything but known states and small numbers into
    the window."""
    if not isinstance(view, dict) or view.get("id") != event_id:
        return None
    state = view.get("state")
    if state not in AGENT_TO_STATE:
        return None
    deadline = view.get("deadline_in_s")
    if isinstance(deadline, bool) or not isinstance(deadline, int) \
            or not 0 <= deadline <= _cpa.COUNTDOWN_MAX_S:
        deadline = 0
    raw = view.get("results")
    results = []
    if isinstance(raw, list):
        for r in raw[:_cpa.MAX_RECIPIENTS]:
            if isinstance(r, dict) and r.get("state") in RCPT_STATES:
                results.append({"state": r["state"], "verified": r.get("verified") is True,
                                "tries": r["tries"] if isinstance(r.get("tries"), int)
                                and not isinstance(r.get("tries"), bool) else 0})
    cancel = view.get("cancel_sms")
    cancel_sms = None
    if isinstance(cancel, dict) and cancel.get("state") in ("sending", "sent", "partial",
                                                             "failed"):
        cancel_sms = {"state": cancel["state"]}
    error = view.get("error")
    return {"state": state, "deadline_in_s": deadline,
            "dry_run": view.get("dry_run") is not False,
            "results": results, "cancel_sms": cancel_sms,
            "error": "expired" if error == "expired" else ""}


# ── the module ─────────────────────────────────────────────────────────────

class CrashSms:
    """The crash SMS flow (see the module docstring).

    Args:
        config: BCMConfig or nested dict (read live: recipients changed in
            Settings count at once).
        event_bus: EventBus.
        agent_getter: returns the running ``CarPhoneAgent`` or None
            (default :func:`car_phone_agent.get_agent`; tests pass a fake).
        clock: monotonic seconds (deadlines, retries, the window).
        wall_clock: epoch seconds (saved timestamps, limits, the gate).
        state_path: where the event is saved.

    Threads: the worker (:meth:`_run` → :meth:`run_once`) is the only one
    that changes the event and the only one that talks to the agent; bus
    callbacks and the web routes only validate and enqueue. ``_lock``
    guards what other threads read (:attr:`state`, :meth:`command`).
    Tests drive :meth:`run_once` by hand with a fake clock.
    """

    def __init__(self, config: Any, event_bus: Any,
                 agent_getter: Optional[Callable[[], Any]] = None,
                 clock: Callable[[], float] = time.monotonic,
                 wall_clock: Callable[[], float] = time.time,
                 state_path: str = STATE_FILE) -> None:
        self._config = config
        self._bus = event_bus
        self._agent_getter = agent_getter or _cpa.get_agent
        self._clock = clock
        self._wall = wall_clock
        self._path = state_path
        self._q: queue.Queue = queue.Queue(maxsize=QUEUE_MAX)
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._subscribed = False
        self._loaded = False
        # The current (or last) event — worker writes, others read under _lock.
        self._ev: Optional[dict[str, Any]] = None
        self._history: list[dict[str, Any]] = []
        self._test: dict[str, Any] = {"request": "", "error": "", "watch_until": None,
                                      "kick_at": 0.0}
        self._gate_reason = ""
        self._gate_at: Optional[float] = None
        self._forced_logged = ""
        self._published: Optional[dict[str, Any]] = None
        self._save_failed = False
        # Consecutive worker passes whose handler did not move next_try.
        self._spins = 0
        # What is on disk: a look-up every 2-3 s must not rewrite the same
        # JSON (SSD wear) — only a change is written.
        self._saved: Optional[dict[str, Any]] = None
        self._min_rate = self._load_min_rate()
        cfg = load_sms_config(config)
        log.info("Crash SMS ready (countdown %d s, %d recipient(s), dry_run=%s, limit 1 per "
                 "%d min / %d a day)", cfg.countdown_sec, len(configured_recipients(config)),
                 cfg.dry_run, cfg.cooldown_min, cfg.max_per_day)

    def _load_min_rate(self) -> float:
        try:
            from src.safety.crash_detect import load_crash_config
            return float(load_crash_config(self._config).min_rate_hz)
        except Exception:
            log.debug("crash_detection.min_rate_hz unreadable — 80 Hz", exc_info=True)
            return 80.0

    # ── lifecycle ─────────────────────────────────────────────────────────

    def _subscriptions(self) -> tuple:
        return ((TOPIC_DETECTED, self._on_detected),
                (TOPIC_OUTCOME, self._on_outcome),
                (CMD_CANCEL, self._on_cmd_cancel),
                (CMD_SEND_NOW, self._on_cmd_send_now),
                ("power.shutting_down", self._on_shutdown))

    def subscribe(self) -> None:
        if self._subscribed:
            return
        self._subscribed = True
        for topic, cb in self._subscriptions():
            self._bus.subscribe(topic, cb)

    def start(self) -> None:
        """Subscribe and start the worker; no I/O here (the saved event is
        read by the worker)."""
        self.subscribe()
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, daemon=True, name="crash-sms")
            self._thread.start()

    def stop(self) -> None:
        """Never waits for a request in progress. The saved event stays: the
        phone holds the deadline anyway, and a restart resumes it."""
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
        self._enqueue(None)

    def _on_shutdown(self, topic: str, value: Any, timestamp: float) -> None:
        if value:
            self.stop()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                wait = self.run_once()
            except Exception:
                log.exception("Crash SMS: worker pass failed")
                wait = RETRY_MIN_S
            try:
                cmd = self._q.get(timeout=max(0.0, min(wait, MAX_WAIT_S)))
            except queue.Empty:
                continue
            self._handle_safe(cmd)

    def run_once(self) -> float:
        """Handle everything queued, then one :meth:`step`. Returns how long
        the worker may sleep (a new command cuts it short)."""
        if not self._loaded:
            self._loaded = True
            self.load()
        while True:
            try:
                cmd = self._q.get_nowait()
            except queue.Empty:
                break
            self._handle_safe(cmd)
        return self.step()

    def _handle_safe(self, cmd: Any) -> None:
        if cmd is None:
            return
        try:
            self.handle(cmd)
        except Exception:
            log.exception("Crash SMS: command %r failed", cmd[0] if cmd else cmd)

    def _enqueue(self, item: Any) -> bool:
        try:
            self._q.put_nowait(item)
            return True
        except queue.Full:
            log.warning("Crash SMS: command queue full — %r dropped",
                        item[0] if isinstance(item, tuple) else item)
            return False

    # ── bus callbacks (dispatcher thread: validate + enqueue only) ─────────

    def _on_detected(self, topic: str, value: Any, timestamp: float) -> None:
        parsed = parse_detected(value)
        if parsed is None:
            if isinstance(value, dict) and value.get("source") == "gps":
                log.info("Crash SMS: GPS-only event %s — logged by crash_detect, never an SMS",
                         str(value.get("event_id", ""))[:32])
            elif isinstance(value, dict) and value.get("sms_eligible") is not True:
                log.info("Crash SMS: event without the right to an SMS (no GPS speed) — ignored")
            else:
                log.warning("Crash SMS: malformed crash.detected ignored")
            return
        self._enqueue(("detected", parsed, self._clock()))

    def _on_outcome(self, topic: str, value: Any, timestamp: float) -> None:
        """``cancelled`` = the car drove on above min_speed_kmh for 10 s."""
        if not isinstance(value, dict) or value.get("outcome") != "cancelled":
            return
        eid = value.get("event_id")
        if isinstance(eid, str) and EVENT_ID_RE.fullmatch(eid):
            self.command("cancel", eid, source="auto")

    def _cmd_args(self, value: Any) -> tuple[Optional[str], str]:
        eid, source = None, "bus"
        if isinstance(value, dict):
            raw = value.get("event_id")
            if isinstance(raw, str) and EVENT_ID_RE.fullmatch(raw):
                eid = raw
            elif raw is not None:
                return "", "bus"            # an invalid id never means "the current one"
            if value.get("source") in SOURCES:
                source = value["source"]
        return eid, source

    def _on_cmd_cancel(self, topic: str, value: Any, timestamp: float) -> None:
        eid, source = self._cmd_args(value)
        if eid == "":
            log.warning("Crash SMS: %s with an invalid event_id ignored", topic)
            return
        res = self.command("cancel", eid, source=source)
        if not res["ok"]:
            log.info("Crash SMS: cancel (%s) ignored — %s", source, res["error"])

    def _on_cmd_send_now(self, topic: str, value: Any, timestamp: float) -> None:
        eid, source = self._cmd_args(value)
        if eid == "":
            log.warning("Crash SMS: %s with an invalid event_id ignored", topic)
            return
        res = self.command("send_now", eid, source=source)
        if not res["ok"]:
            log.info("Crash SMS: send_now (%s) ignored — %s", source, res["error"])

    # ── API for the web routes (any thread; no I/O) ────────────────────────

    def command(self, action: str, event_id: Optional[str] = None, source: str = "ui") -> dict:
        """Queue "cancel" / "send_now" / "follow_up" for the worker.
        ``event_id`` None = the current event (SWC). Returns ``{"ok",
        "error"}``; errors: stopped, bad_request, no_event, unknown_event,
        not_cancellable, not_pending, busy.

        ``follow_up`` ("Jestem OK – wyślij SMS odwołujący" after a sent
        SMS) only from the window (``ui``) with its event id. Who may
        cancel when: :meth:`_cancellable` (checked here for the answer and
        again on the worker)."""
        if self._stop.is_set():
            return {"ok": False, "error": "stopped"}
        if action not in ACTIONS or source not in SOURCES \
                or (event_id is not None and (not isinstance(event_id, str)
                                              or not EVENT_ID_RE.fullmatch(event_id))):
            return {"ok": False, "error": "bad_request"}
        if action == "follow_up" and (source != "ui" or event_id is None):
            return {"ok": False, "error": "bad_request"}
        with self._lock:
            ev = self._ev
            if ev is None:
                return {"ok": False, "error": "no_event"}
            if event_id is not None and event_id != ev["id"]:
                return {"ok": False, "error": "unknown_event"}
            eid = ev["id"]
            if action == "cancel" and not self._cancellable(ev, source, self._clock()):
                return {"ok": False, "error": "not_cancellable"}
            if action == "follow_up" and not self._follow_up_ok(ev):
                return {"ok": False, "error": "not_cancellable"}
            if action == "send_now" and (ev["state"] not in ("armed", "pending")
                                         or ev["cancel_pending"]):
                return {"ok": False, "error": "not_pending"}
        if not self._enqueue((action, eid, source)):
            return {"ok": False, "error": "busy"}
        return {"ok": True, "error": ""}

    def request_test(self) -> dict:
        """Queue a REAL test SMS ("Wyślij testowy SMS" in Settings, after
        the driver confirmed it on screen — the route is loopback only).
        Errors: stopped, no_recipients, not_running (the agent module),
        config_pending (the phone does not hold the recipients saved here
        yet — a test now would go to its OLD list), busy (a test is
        already on its way)."""
        if self._stop.is_set():
            return {"ok": False, "error": "stopped"}
        if not configured_recipients(self._config):
            return {"ok": False, "error": "no_recipients"}
        agent = self._agent()
        if agent is None:
            return {"ok": False, "error": "not_running"}
        if self._config_pending(agent):
            return {"ok": False, "error": "config_pending"}
        with self._lock:
            if self._test["request"] in ("queued", "sending"):
                return {"ok": False, "error": "busy"}
            self._test.update(request="queued", error="")
        if not self._enqueue(("test",)):
            with self._lock:
                self._test.update(request="", error="")
            return {"ok": False, "error": "busy"}
        return {"ok": True, "error": ""}

    def _config_pending(self, agent: Any) -> bool:
        """Does the phone NOT hold the config BCM wants (recipients just
        saved in Settings, the push not through yet)? From the client's
        state (``config_pending`` / ``config_refused``) and the hash of the
        phone's config in its last signed answer. No I/O."""
        try:
            st = agent.state or {}
            facts = agent.health_facts() or {}
        except Exception:
            return False
        if st.get("reason") in ("config_pending", "config_refused"):
            return True
        have = facts.get("config_hash")
        if not isinstance(have, str):
            return False                     # no signed answer yet: the request will tell
        return have != _cpa.config_hash(_cpa.desired_config(self._config))

    @property
    def state(self) -> Optional[dict[str, Any]]:
        """The last published ``crash.sms_state`` (a copy), or None."""
        with self._lock:
            return None if self._published is None else json.loads(json.dumps(self._published))

    # ── commands (worker thread) ───────────────────────────────────────────

    def handle(self, cmd: tuple) -> None:
        kind = cmd[0]
        if kind == "detected":
            self._new_event(cmd[1], cmd[2])
        elif kind in ACTIONS:
            self._apply(kind, cmd[1], cmd[2])
        elif kind == "test":
            self._do_test()

    def _new_event(self, det: dict, detected_at: float) -> None:
        now, wall = self._clock(), self._wall()
        with self._lock:
            cur = self._ev
            if cur is not None and cur["id"] == det["event_id"]:
                return                                      # duplicate
            if cur is not None and (_live(cur) or cur["cancel_pending"]):
                # One event at a time (the phone holds one too). An event whose
                # cancel has not reached the phone yet is never dropped: the
                # phone would send what the driver cancelled.
                log.warning("Crash SMS: event %s while %s is still %s — the running one "
                            "covers it", det["event_id"], cur["id"],
                            "being cancelled" if cur["cancel_pending"] else cur["state"])
                return
            reconciling = cur if cur is not None and cur["state"] == "failed_no_phone" \
                and cur["reconcile_until"] is not None else None
        if reconciling is not None and not self._settle_reconciling(reconciling, det):
            return
        now, wall = self._clock(), self._wall()
        cfg = load_sms_config(self._config)
        recipients = configured_recipients(self._config)
        # No sensor check here: this accel event already proves them (see
        # the module docstring, "Safety gate").
        dry, reason = self._gate(cfg, indicator=False)
        event_ts = det["ts"] if det["ts"] is not None else wall
        created = min(detected_at, now)
        ev = {
            "id": det["event_id"], "state": "armed", "created_ts": wall,
            "created_mono": created, "event_ts": int(event_ts),
            "countdown_s": cfg.countdown_sec, "deadline_ts": None, "deadline_mono": None,
            "dry_run": dry, "forced_reason": reason, "recipients_n": len(recipients),
            "results": [], "cancel_sms": None, "error": "", "cancel_pending": False,
            "cancel_source": "", "cancel_mono": None, "send_now_pending": False,
            "final_ts": None, "final_mono": None, "phone_ok": False, "maybe_delivered": False,
            "confirmed": False, "went_out": False, "follow_up": cfg.follow_up_cancel,
            "arm": {k: det[k] for k in ("lat", "lon", "fix_age_s", "speed_kmh", "dv_kmh")},
            "arm_until": created + self._arm_window(cfg.countdown_sec), "next_try": now,
            "retry": RETRY_MIN_S, "reconcile_until": None, "followed_until": now + ACTIVE_MAX_S,
        }
        log.critical("Crash SMS: event %s — %d recipient(s), countdown %d s%s",
                     ev["id"], len(recipients), cfg.countdown_sec,
                     f" (DRY RUN{', forced: ' + reason if reason else ''})" if dry else "")
        limit = self._limit(dry, wall, cfg)
        if not recipients:
            self._finish(ev, "failed", "no_recipients", now, set_current=True)
            log.error("Crash SMS: no recipients configured (crash_detection.sms.recipients "
                      "in local.yaml / Settings) — NO SMS for %s", ev["id"])
        elif limit:
            self._finish(ev, "limited", limit, now, set_current=True)
            log.warning("Crash SMS: %s — limit (%s), nothing armed", ev["id"], limit)
        else:
            with self._lock:
                self._ev = ev
            self._remember(ev)
            self._save()
        self._publish()

    @staticmethod
    def _arm_window(countdown_s: int) -> float:
        """How long after the event arm requests are retried: until the
        shown countdown has only the phone's minimum left (a later arm
        would stretch the deadline on screen), at least
        :data:`ARM_RETRY_WINDOW_S` (``countdown_sec`` set to 15)."""
        return max(ARM_RETRY_WINDOW_S, float(countdown_s - _cpa.COUNTDOWN_MIN_S))

    def _settle_reconciling(self, cur: dict, det: dict) -> bool:
        """A new event while the last one is ``failed_no_phone`` and the
        phone may still hold it (its arm request may have arrived). The
        phone holds ONE event: arming the new one would be refused (429)
        while the old one — no longer followed nor cancellable — is sent.
        So ask the phone first (worker thread). Returns True when the new
        event may go ahead (the phone does not know the old one, or holds
        it finished); False when the old one covers it (it is live on the
        phone — the window shows its countdown again — or the phone does
        not answer: the old one keeps being looked up)."""
        found = self._lookup(cur, self._clock(), final_try=True)
        if found == "unknown":
            with self._lock:
                cur["reconcile_until"] = None
                cur["phone_ok"] = True
            self._save()
        with self._lock:
            covered = found == "error" or _live(cur) or cur["cancel_pending"]
        if covered:
            log.warning("Crash SMS: event %s while %s may still be held by the phone (%s) — "
                        "the earlier one covers it", det["event_id"], cur["id"],
                        "no answer" if found == "error" else cur["state"])
            self._publish()
        return not covered

    def _apply(self, kind: str, eid: str, source: str) -> None:
        now = self._clock()
        with self._lock:
            ev = self._ev
            if ev is None or ev["id"] != eid:
                return
            if kind in ("cancel", "follow_up"):
                # Checked again here: the state may have moved since the
                # request was queued (a look-up adopted "sending"/"sent").
                allowed = self._cancellable(ev, source, now) if kind == "cancel" \
                    else self._follow_up_ok(ev)
                if not allowed:
                    log.info("Crash SMS: %s — %s (%s) no longer possible in state %s — "
                             "ignored", eid, kind, source, ev["state"])
                    return
                log.warning("Crash SMS: %s — %s requested (%s)", eid,
                            "CANCEL" if kind == "cancel" else "FOLLOW-UP CANCEL SMS", source)
                ev["cancel_pending"] = True
                ev["cancel_source"] = source
                ev["cancel_mono"] = now
                ev["send_now_pending"] = False
                ev["next_try"] = now
                ev["retry"] = RETRY_MIN_S
                if kind == "cancel" and ev["state"] == "armed" and not ev["maybe_delivered"]:
                    # No arm request can have reached the phone: nothing to
                    # tell it, nothing will be sent.
                    self._finish(ev, "cancelled", "", now)
                    log.warning("Crash SMS: %s cancelled before the phone held it", eid)
            elif ev["state"] in ("armed", "pending") and not ev["cancel_pending"]:
                log.warning("Crash SMS: %s — SEND NOW requested (%s)", eid, source)
                ev["send_now_pending"] = True
                ev["next_try"] = now
        self._save()
        self._publish()

    def _cancellable(self, ev: dict, source: str, now: float) -> bool:
        """May ``source`` cancel the event now (see the module docstring)?

        Not the window (a steering-wheel button that keeps its normal
        action, a bus command, ``auto``): only while the countdown runs,
        when nothing can have left the phone — a cancel then only stops
        the countdown. Later the phone would send the cancel SMS
        ("kierowca potwierdzil, ze nic sie nie stalo") to everybody who got
        the crash SMS: after a REAL crash a routine button press (hanging
        up on the family calling back) must never do that.

        The window's ANULUJ (``ui``): any live active state (also
        ``sending``: the driver sees "WYSYŁANIE" and decides), and a
        ``failed_no_phone`` the phone may hold (``may_send``)."""
        if ev["cancel_pending"]:
            return False
        state = ev["state"]
        if source != "ui":
            if state in ("armed", "pending"):
                left = self._left(ev, now)
                return _live(ev) and left is not None and left > 0
            if state == "failed_no_phone":
                return ev["reconcile_until"] is not None and now < self._deadline_mono(ev)
            return False
        if state in ACTIVE:
            return _live(ev)
        if state == "failed_no_phone":
            return ev["reconcile_until"] is not None
        return False

    def _follow_up_ok(self, ev: dict) -> bool:
        """"Jestem OK" after a sent SMS: the phone sends ONE cancel SMS to
        every recipient who got the crash SMS, within its 15 min."""
        if ev["cancel_pending"] or ev["state"] not in ("sent", "partial") \
                or not ev["follow_up"] or not ev["went_out"]:
            return False
        final = ev["final_ts"]
        return final is not None and abs(self._wall() - final) < FOLLOW_UP_WINDOW_S

    def _do_test(self) -> None:
        with self._lock:
            self._test.update(request="sending", error="")
        self._publish()
        agent = self._agent_getter()
        res = agent.test_sms(real=True) if agent is not None else {"ok": False,
                                                                     "error": "not_running"}
        now = self._clock()
        with self._lock:
            if res.get("ok"):
                self._test.update(request="accepted", error="", watch_until=now + TEST_WATCH_S,
                                  kick_at=now)
                log.warning("Crash SMS: REAL test SMS accepted by the phone")
            else:
                err = res.get("error") or ""
                code = err if err in ("no_recipients", "rate_limited") else (
                    "no_phone" if err in NOT_DELIVERED
                    or err in ("timeout", "dropped", "not_running")
                    else "refused")
                self._test.update(request="error", error=code, watch_until=None)
                log.warning("Crash SMS: test SMS not accepted (%s%s)", err or "?",
                            f": {res.get('detail')}" if res.get("detail") else "")
        if agent is not None and res.get("ok"):
            try:
                agent.kick()
            except Exception:
                pass
        self._publish()

    # ── the scheduler (worker thread) ──────────────────────────────────────

    def step(self) -> float:
        """Due work: arm, cancel, send now, look-ups, the window's clock.
        Returns seconds until the next due item."""
        now = self._clock()
        waits = [MAX_WAIT_S]
        self._test_watch(now, waits)
        with self._lock:
            ev = self._ev
        if ev is not None:
            self._event_step(ev, now, waits)
        if self._gate_at is None or now - self._gate_at >= GATE_REFRESH_S:
            self._gate_at = now
            self._gate(load_sms_config(self._config))
        waits.append(max(0.0, self._gate_at + GATE_REFRESH_S - now))
        self._publish()
        with self._lock:
            ev = self._ev
            if ev is not None and ev["state"] in ("armed", "pending"):
                left = self._left(ev, self._clock())
                if left is not None and left > 0:
                    # Wake when the shown second changes.
                    frac = (self._deadline_mono(ev) - self._clock()) % 1.0
                    waits.append(frac if frac > 0.01 else 1.0)
            if ev is not None and ev["state"] in FINAL and ev["final_mono"] is not None:
                show_left = ev["final_mono"] + FINAL_SHOW_S - self._clock()
                if show_left > 0:
                    waits.append(show_left)
            if ev is not None and ev["state"] in ("pending", "sending") and not ev["phone_ok"]:
                # "unconfirmed" starts, and its window ends, at fixed times.
                past = self._clock() - self._deadline_mono(ev)
                for at in (UNCONFIRMED_AFTER_S, UNCONFIRMED_AFTER_S + FINAL_SHOW_S):
                    if past < at:
                        waits.append(at - past + 0.01)
                        break
        return max(0.0, min(waits))

    def _event_step(self, ev: dict, now: float, waits: list) -> None:
        if now > ev["followed_until"] and (ev["state"] in ACTIVE or ev["cancel_pending"]
                                           or ev["reconcile_until"] is not None):
            log.warning("Crash SMS: %s still %s after %d min — no longer followed",
                        ev["id"], ev["state"], int(ACTIVE_MAX_S // 60))
            with self._lock:
                ev["cancel_pending"] = False
                ev["send_now_pending"] = False
                ev["reconcile_until"] = None
                ev["followed_until"] = float("inf")
                ev["next_try"] = float("inf")
                if ev["state"] in ACTIVE:
                    ev["final_mono"] = now - FINAL_SHOW_S    # window down
            self._save()
            return
        due = ev["next_try"]
        if now < due:
            waits.append(due - now)
            return
        state = ev["state"]
        if ev["cancel_pending"]:
            self._send_cancel(ev, now)
        elif state == "armed":
            self._arm(ev, now)
        elif state == "pending" and ev["send_now_pending"]:
            self._send_now(ev, now)
        elif self._needs_lookup(ev, now):
            self._lookup(ev, now)
        else:
            return
        with self._lock:
            # A handler that did not move next_try may be followed by one
            # immediate pass (send-now → look up at once), never by a
            # second: an exit path that forgets to schedule must not turn
            # the worker into a busy loop of signed requests to the phone.
            if ev["next_try"] <= due:
                self._spins += 1
                if self._spins > 1:
                    ev["next_try"] = self._clock() + RETRY_MIN_S
                    self._spins = 0
            else:
                self._spins = 0
        waits.append(max(0.0, ev["next_try"] - self._clock()))

    def _needs_lookup(self, ev: dict, now: float) -> bool:
        if now > ev["followed_until"]:
            return False
        if ev["state"] in ("pending", "sending"):
            return True
        if ev["state"] == "cancelled" and isinstance(ev["cancel_sms"], dict) \
                and ev["cancel_sms"]["state"] == "sending":
            return True
        if ev["reconcile_until"] is not None:
            if now <= ev["reconcile_until"]:
                return True
            with self._lock:
                ev["reconcile_until"] = None
            log.info("Crash SMS: %s — the phone never reported it; no longer looked up",
                     ev["id"])
            self._save()
        return False

    def _agent(self) -> Any:
        try:
            return self._agent_getter()
        except Exception:
            return None

    def _arm(self, ev: dict, now: float) -> None:
        agent = self._agent()
        elapsed = max(0.0, now - ev["created_mono"])
        countdown = int(max(_cpa.COUNTDOWN_MIN_S, round(ev["countdown_s"] - elapsed)))
        a = ev["arm"] or {}
        fix_age = a.get("fix_age_s")
        if agent is None:
            res = {"ok": False, "error": "not_running", "status": None, "data": None}
        else:
            # fix_age_s as crash_detect measured it — relative to the
            # accident, whose time the SMS carries; the time spent arming
            # must not make a good position look stale ("GPS sprzed 2 min").
            res = agent.arm_crash(
                ev["id"], countdown, a.get("lat"), a.get("lon"),
                None if fix_age is None else int(round(fix_age)),
                a.get("speed_kmh"), a.get("dv_kmh"), ev["event_ts"], dry_run=ev["dry_run"])
        now = self._clock()
        err = res.get("error") or ""
        if res.get("ok"):
            view = parse_agent_view(res.get("data"), ev["id"])
            if view is not None:
                self._adopt(ev, view, now)
                log.warning("Crash SMS: %s armed on the phone — it sends in %d s unless "
                            "cancelled%s", ev["id"], view["deadline_in_s"],
                            " (DRY RUN)" if view["dry_run"] else "")
                return
            err = "protocol"
        status = res.get("status")
        if (status in (400, 409, 429) or (status is None and err == "bad_request")) \
                and err in ARM_REFUSALS:
            self._finish(ev, "failed", ARM_REFUSALS[err], now)
            log.error("Crash SMS: the phone refused %s (%s) — NO SMS", ev["id"], err)
            return
        with self._lock:
            ev["phone_ok"] = False
            if err not in NOT_DELIVERED:
                ev["maybe_delivered"] = True
        if now < ev["arm_until"]:
            with self._lock:
                ev["next_try"] = now + ARM_RETRY_EVERY_S
            log.warning("Crash SMS: arming %s failed (%s) — retrying", ev["id"], err or "?")
            return
        if ev["maybe_delivered"]:
            # The phone may hold it: one look-up decides, and if it cannot be
            # reached the event keeps being looked up (it may still send).
            found = self._lookup(ev, now, final_try=True)
            if found == "found":
                return
            if found == "unknown":
                with self._lock:
                    ev["maybe_delivered"] = False
            else:
                deadline = ev["created_mono"] + ev["countdown_s"]
                with self._lock:
                    ev["reconcile_until"] = max(deadline, now) + RECONCILE_AFTER_DEADLINE_S
                    ev["next_try"] = now + RECONCILE_EVERY_S
        self._finish(ev, "failed_no_phone", "no_phone", now)
        if ev["reconcile_until"] is not None:
            log.error("Crash SMS: the phone is not reachable (%s) — an arm request may have "
                      "reached it: it MAY still send %s; looking it up", err or "?", ev["id"])
        else:
            log.error("Crash SMS: the phone is not reachable (%s) — NO SMS for %s",
                      err or "?", ev["id"])

    def _send_cancel(self, ev: dict, now: float) -> None:
        agent = self._agent()
        res = agent.cancel(ev["id"]) if agent is not None else {"ok": False,
                                                                   "error": "not_running"}
        now = self._clock()
        if res.get("ok"):
            view = parse_agent_view(res.get("data"), ev["id"])
            with self._lock:
                ev["cancel_pending"] = False
            if view is not None:
                self._adopt(ev, view, now)
            else:
                self._finish(ev, "cancelled", "", now)
            log.warning("Crash SMS: %s cancelled on the phone%s", ev["id"],
                        " — cancel SMS queued" if ev.get("cancel_sms") else "")
            return
        if res.get("status") == 404 and res.get("error") == "unknown_event":
            if ev["state"] in ("sent", "partial"):
                # "Jestem OK" after a sent SMS, and the phone no longer knows
                # the event: the crash SMS DID go out — keep saying so; only
                # the cancel SMS did not happen.
                with self._lock:
                    ev["cancel_pending"] = False
                    ev["cancel_sms"] = {"state": "failed"}
                    ev["next_try"] = now + POLL_SENDING_S
                self._save()
                log.error("Crash SMS: %s unknown on the phone — NO cancel SMS went out",
                          ev["id"])
                return
            # The phone does not know it: it was never armed there (or the
            # agent lost it) — nothing will be sent.
            with self._lock:
                ev["cancel_pending"] = False
            self._finish(ev, "cancelled", "unknown_event" if ev["confirmed"] else "", now)
            log.warning("Crash SMS: %s unknown on the phone — cancelled", ev["id"])
            return
        since = ev["cancel_mono"] if ev["cancel_mono"] is not None else ev["arm_until"]
        if ev["state"] == "armed" and now >= since + ARM_RETRY_WINDOW_S:
            # Never reached the phone, and maybe it holds the event: the
            # window says "cancelled, the phone did not confirm" and the
            # cancel keeps being retried in the background.
            self._finish(ev, "cancelled", "no_phone", now, keep_cancel=True)
        self._backoff(ev, now, "cancel", res)

    def _send_now(self, ev: dict, now: float) -> None:
        agent = self._agent()
        res = agent.send_now(ev["id"]) if agent is not None else {"ok": False,
                                                                     "error": "not_running"}
        now = self._clock()
        if res.get("ok"):
            with self._lock:
                ev["send_now_pending"] = False
            view = parse_agent_view(res.get("data"), ev["id"])
            if view is not None:
                self._adopt(ev, view, now)
            with self._lock:
                ev["next_try"] = now          # look up at once: "sending"
            return
        if res.get("status") == 404:
            with self._lock:
                ev["send_now_pending"] = False
        self._backoff(ev, now, "send_now", res)

    def _lookup(self, ev: dict, now: float, final_try: bool = False) -> str:
        """``GET /v1/crash/<id>`` → "found" (adopted), "unknown" (the phone
        does not know it) or "error" (no usable answer)."""
        agent = self._agent()
        res = agent.get(ev["id"]) if agent is not None else {"ok": False,
                                                             "error": "not_running"}
        now = self._clock()
        if res.get("ok"):
            view = parse_agent_view(res.get("data"), ev["id"])
            if view is not None:
                if ev["state"] == "failed_no_phone":
                    log.warning("Crash SMS: %s — the phone DOES hold the event after all "
                                "(%s)", ev["id"], view["state"])
                with self._lock:
                    ev["reconcile_until"] = None
                self._adopt(ev, view, now)
                return "found"
        unknown = res.get("status") == 404 and res.get("error") == "unknown_event"
        if final_try:
            return "unknown" if unknown else "error"
        if unknown:
            with self._lock:
                ev["phone_ok"] = True
                reconciling = ev["reconcile_until"] is not None
                ev["reconcile_until"] = None
            if ev["state"] in ("pending", "sending") and not reconciling:
                # It held it and forgot it (agent reinstalled?): the outcome
                # is unknown — say so, stop following.
                self._finish(ev, "failed", "unknown_event", now)
                log.error("Crash SMS: the phone no longer knows %s — outcome unknown",
                          ev["id"])
            else:
                forgot = False
                with self._lock:
                    if isinstance(ev["cancel_sms"], dict) \
                            and ev["cancel_sms"]["state"] == "sending":
                        # It forgot the event while the cancel SMS was on its
                        # way: that outcome is unknown — stop following it
                        # (else this look-up would repeat back to back).
                        ev["cancel_sms"] = {"state": "failed"}
                        if ev["confirmed"]:
                            ev["error"] = "unknown_event"
                        forgot = True
                    ev["next_try"] = now + POLL_SENDING_S
                if forgot:
                    log.error("Crash SMS: the phone no longer knows %s — the cancel SMS "
                              "outcome is unknown", ev["id"])
                self._save()
            return "unknown"
        if ev["reconcile_until"] is not None and ev["state"] == "failed_no_phone":
            with self._lock:
                ev["next_try"] = now + RECONCILE_EVERY_S
            return "error"
        self._backoff(ev, now, "look-up", res)
        return "error"

    def _backoff(self, ev: dict, now: float, what: str, res: dict) -> None:
        with self._lock:
            was_ok = ev["phone_ok"]
            ev["phone_ok"] = False
            ev["next_try"] = now + ev["retry"]
            ev["retry"] = min(ev["retry"] * 2, RETRY_MAX_S)
        if was_ok:
            log.warning("Crash SMS: %s — %s failed (%s); the phone keeps its own deadline",
                        ev["id"], what, res.get("error") or "?")

    def _adopt(self, ev: dict, view: dict, now: float) -> None:
        """The phone's view of the event → ours (its word is the truth)."""
        state = AGENT_TO_STATE[view["state"]]
        wall = self._wall()
        with self._lock:
            old = ev["state"]
            ev["confirmed"] = True
            ev["phone_ok"] = True
            ev["retry"] = RETRY_MIN_S
            ev["arm"] = None                     # the position is on the phone now
            ev["dry_run"] = view["dry_run"]
            ev["results"] = [{"state": r["state"], "verified": r["verified"]}
                             for r in view["results"]]
            ev["went_out"] = ev["went_out"] or any(
                r["state"] in RCPT_OUT or r["tries"] > 0 for r in view["results"])
            ev["cancel_sms"] = view["cancel_sms"]
            # The phone's word replaces a BCM-side guess ("no_phone" while it
            # did not answer): it answered, so that is no longer true.
            ev["error"] = view["error"]
            if view["state"] == "armed":
                # The phone's whole seconds are a ceiling (true remaining in
                # (d-1, d]): take the middle, and only move our clock when it
                # is off by more than that — the window must not jitter, nor
                # show more time than the phone gives.
                left = max(0.0, view["deadline_in_s"] - 0.5)
                cur = ev["deadline_mono"]
                if cur is None or abs((now + left) - cur) > 1.5:
                    ev["deadline_mono"] = now + left
                    ev["deadline_ts"] = wall + left
            ev["state"] = state
            if state == "cancelled":
                ev["cancel_pending"] = False
                ev["send_now_pending"] = False
            if state in FINAL and (old != state or ev["final_mono"] is None):
                ev["final_ts"] = wall
                ev["final_mono"] = now
            poll = POLL_PENDING_S if state == "pending" else POLL_SENDING_S
            # A cancel / send-now waiting for the confirmation goes out at once.
            ev["next_try"] = now if (ev["cancel_pending"] or ev["send_now_pending"]) \
                else now + poll
        if old != state:
            log.warning("Crash SMS: %s %s -> %s", ev["id"], old, state)
        self._remember(ev)
        self._save()

    def _finish(self, ev: dict, state: str, error: str, now: float,
                set_current: bool = False, keep_cancel: bool = False) -> None:
        with self._lock:
            if set_current:
                self._ev = ev
            old = ev["state"]
            ev["state"] = state
            ev["error"] = error if error in ERRORS else "refused"
            ev["final_ts"] = self._wall()
            ev["final_mono"] = now
            ev["send_now_pending"] = False
            if state != "failed_no_phone":
                ev["reconcile_until"] = None
            if state == "cancelled" and not keep_cancel:
                ev["cancel_pending"] = False
        if old != state:
            log.warning("Crash SMS: %s %s -> %s%s", ev["id"], old, state,
                        f" ({error})" if error else "")
        self._remember(ev)
        self._save()

    # ── limits (BCM's own; the phone has fixed ones too) ───────────────────

    @staticmethod
    def _counted(ev: dict) -> bool:
        """Does the event count towards the limits? Only what the phone
        held and did not drop before anything went out: a false alarm
        cancelled in time must not block a real one."""
        if not ev["confirmed"]:
            return False
        if ev["state"] == "cancelled":
            return ev["went_out"]
        return not (ev["state"] == "failed" and ev["error"] in ARM_REFUSALS.values())

    def _remember(self, ev: dict) -> None:
        entry = {"id": ev["id"], "ts": ev["created_ts"], "dry": bool(ev["dry_run"]),
                 "counted": self._counted(ev)}
        with self._lock:
            self._history = [h for h in self._history if h["id"] != ev["id"]]
            self._history.append(entry)
            wall = self._wall()
            self._history = [h for h in self._history
                             if abs(wall - h["ts"]) < DAY_S][-HISTORY_MAX:]

    def _limit(self, dry: bool, wall: float, cfg: SmsConfig) -> str:
        """'' = may arm; else ``cooldown`` / ``daily_limit``. Like the phone:
        test-mode events do not count against a real one (they protected
        nobody), real ones count against everything."""
        with self._lock:
            counted = [h for h in self._history if h["counted"] and (dry or not h["dry"])]
        ages = [abs(wall - h["ts"]) for h in counted]
        if any(a < cfg.cooldown_min * 60 for a in ages):
            return "cooldown"
        if sum(1 for a in ages if a < DAY_S) >= cfg.max_per_day:
            return "daily_limit"
        return ""

    # ── safety gate (no I/O) ───────────────────────────────────────────────

    def _gate(self, cfg: SmsConfig, indicator: bool = True) -> tuple[bool, str]:
        """``(dry_run, forced_dry_run_reason)``.

        ``indicator`` True: the idle / Settings indicator (also the
        phone's sensors; remembered for the idle payload, a change is
        logged once). False: for an event armed now — agent and test only
        (the event itself proves the sensors)."""
        reason = "" if cfg.dry_run else self._gate_failure(sensors=indicator)
        if indicator:
            with self._lock:
                self._gate_reason = reason
            if reason and reason != self._forced_logged:
                log.warning("Crash SMS: crash_detection.sms.dry_run is false, but SMS stay in "
                            "TEST MODE — %s", reason)
            elif not reason and self._forced_logged and not cfg.dry_run:
                log.warning("Crash SMS: safety checks pass — crash SMS are REAL now")
            self._forced_logged = reason
        return (cfg.dry_run or bool(reason)), reason

    def _gate_failure(self, sensors: bool = True) -> str:
        wall = self._wall()
        agent = self._agent()
        if agent is None:
            return "agent_not_ready"
        try:
            st = agent.state or {}
            facts = agent.health_facts() or {}
        except Exception:
            return "agent_not_ready"
        ok_ts = _finite(st.get("last_ok_ts"), 0.0, 4e9)
        if st.get("state") != "ok" or st.get("paired") is not True or st.get("reason") \
                or ok_ts is None or abs(wall - ok_ts) > AGENT_FRESH_S \
                or facts.get("dry_run") is not False:
            return "agent_not_ready"
        tested = _finite(facts.get("last_verified_test_ts"), 0.0, 4e9)
        if tested is None:
            return "no_verified_test"
        if wall - tested > TEST_MAX_AGE_S or tested - wall > AGENT_FRESH_S:
            return "test_too_old"
        return self._sensor_failure() if sensors else ""

    def _sensor_failure(self) -> str:
        """The phone's sensors for the idle indicator, from the latest
        ``phone.g_force`` (its ``rate_hz`` / ``calib_ok`` are current, and
        its ``mono`` tells whether the stream still runs) — not from
        ``phone_sensors.state``, whose ``rate_hz`` is republished only on a
        10 % move and so may lag behind the real rate."""
        try:
            st = self._bus.get_last(SENSORS_TOPIC)
            g = self._bus.get_last(G_TOPIC)
        except Exception:
            st = g = None
        state = st[0] if st else None
        if not isinstance(state, dict) or state.get("state") != "streaming":
            return "sensors_not_streaming"
        msg = g[0] if g else None
        if not isinstance(msg, dict):
            return "sensors_not_streaming"
        mono = _finite(msg.get("mono"), 0.0, 1e12)
        if mono is None or abs(self._clock() - mono) > G_FRESH_S:
            return "sensors_not_streaming"
        rate = _finite(msg.get("rate_hz"), 0.0, 5000.0)
        if rate is None or rate < self._min_rate:
            return "sensor_rate_low"
        if msg.get("calib_ok") is not True:
            return "not_calibrated"
        return ""

    # ── test SMS follow-up ─────────────────────────────────────────────────

    def _test_watch(self, now: float, waits: list) -> None:
        """While a test SMS is being checked by the phone, ask the agent
        for fresh health now and then (Settings shows the outcome)."""
        with self._lock:
            until = self._test["watch_until"]
            kick_at = self._test["kick_at"]
        if until is None:
            return
        if now >= until:
            with self._lock:
                self._test["watch_until"] = None
            return
        if now - kick_at >= TEST_KICK_EVERY_S:
            agent = self._agent()
            if agent is not None:
                try:
                    agent.kick()
                except Exception:
                    pass
            with self._lock:
                self._test["kick_at"] = now
            kick_at = now
        waits.append(max(0.0, kick_at + TEST_KICK_EVERY_S - now))

    # ── publication ────────────────────────────────────────────────────────

    def _deadline_mono(self, ev: dict) -> float:
        if ev["deadline_mono"] is not None:
            return ev["deadline_mono"]
        return ev["created_mono"] + ev["countdown_s"]

    def _left(self, ev: dict, now: float) -> Optional[int]:
        if ev["state"] not in ("armed", "pending"):
            return None
        return max(0, int(math.ceil(self._deadline_mono(ev) - now - 1e-9)))

    def payload(self) -> dict[str, Any]:
        """``crash.sms_state`` as it would be published now."""
        now, wall = self._clock(), self._wall()
        facts = {}
        agent = self._agent()
        if agent is not None:
            try:
                facts = agent.health_facts() or {}
            except Exception:
                facts = {}
        last_test = facts.get("last_test") if isinstance(facts.get("last_test"), dict) else None
        cfg_dry = load_sms_config(self._config).dry_run
        with self._lock:
            ev = self._ev
            test = {"request": self._test["request"], "error": self._test["error"],
                    "state": last_test["state"] if last_test else None,
                    "ts": last_test["ts"] if last_test else None,
                    "dry_run": last_test["dry_run"] if last_test else None,
                    "verified": bool(last_test and last_test["verified"]),
                    "last_verified_ts": _finite(facts.get("last_verified_test_ts"), 0.0, 4e9)}
            if ev is None:
                st = agent.state if agent is not None else None
                phone_ok = isinstance(st, dict) and st.get("state") == "ok" \
                    and st.get("paired") is True
                return {"state": "idle", "event_id": None, "ts": None, "countdown_s": None,
                        "countdown_left_s": None, "deadline_ts": None,
                        "recipients_n": len(configured_recipients(self._config)),
                        "phone_ok": phone_ok, "dry_run": cfg_dry or bool(self._gate_reason),
                        "forced_dry_run_reason": self._gate_reason, "results": [],
                        "cancel_sms": None, "error": "", "modal": False,
                        "cancel_pending": False, "send_now_pending": False,
                        "can_follow_up": False, "may_send": False, "unconfirmed": False,
                        "test": test}
            state = ev["state"]
            past = now - self._deadline_mono(ev)
            # The phone stopped answering and BCM's deadline is gone: it may
            # have sent — say so in a closable view instead of a countdown
            # stuck at 0 that beeps for 15 min over Android Auto.
            unconfirmed = state in ("pending", "sending") and not ev["phone_ok"] \
                and past > UNCONFIRMED_AFTER_S
            modal = state in ACTIVE or (state in FINAL and ev["final_mono"] is not None
                                        and now - ev["final_mono"] < FINAL_SHOW_S)
            if state in ACTIVE and (ev["followed_until"] == float("inf") or
                                    past > MODAL_ACTIVE_MAX_S or (
                                        unconfirmed
                                        and past > UNCONFIRMED_AFTER_S + FINAL_SHOW_S)):
                modal = False
            left = self._left(ev, now)
            deadline_ts = ev["deadline_ts"]
            if deadline_ts is None and state == "armed":
                deadline_ts = ev["created_ts"] + ev["countdown_s"]
            return {
                "state": state, "event_id": ev["id"], "ts": ev["created_ts"],
                "countdown_s": ev["countdown_s"], "countdown_left_s": left,
                "deadline_ts": deadline_ts if state in ("armed", "pending") else None,
                "recipients_n": ev["recipients_n"], "phone_ok": bool(ev["phone_ok"]),
                "dry_run": bool(ev["dry_run"]), "forced_dry_run_reason": ev["forced_reason"],
                "results": [dict(r) for r in ev["results"]],
                "cancel_sms": dict(ev["cancel_sms"]) if ev["cancel_sms"] else None,
                "error": ev["error"], "modal": bool(modal),
                "cancel_pending": bool(ev["cancel_pending"]),
                "send_now_pending": bool(ev["send_now_pending"]),
                "can_follow_up": self._follow_up_ok(ev),
                # The phone may hold the event although arming "failed":
                # the window must not say "SMS NIE zostanie wysłany".
                "may_send": state == "failed_no_phone" and ev["reconcile_until"] is not None,
                "unconfirmed": unconfirmed,
                "test": test,
                "_wall": wall,
            }

    def _publish(self) -> None:
        out = self.payload()
        out.pop("_wall", None)
        with self._lock:
            if out == self._published:
                return
            self._published = out
        try:
            self._bus.publish(TOPIC_STATE, dict(out))
        except Exception:
            log.exception("Publishing %s failed", TOPIC_STATE)

    # ── persistence ────────────────────────────────────────────────────────

    _SAVED_KEYS = ("id", "state", "created_ts", "event_ts", "countdown_s", "deadline_ts",
                   "dry_run", "forced_reason", "recipients_n", "results", "cancel_sms",
                   "error", "cancel_pending", "cancel_source", "send_now_pending", "final_ts",
                   "maybe_delivered", "confirmed", "went_out", "follow_up", "arm")

    def _save(self) -> None:
        with self._lock:
            ev = self._ev
            data = {"version": 1,
                    "event": None if ev is None else {k: ev[k] for k in self._SAVED_KEYS},
                    "history": [dict(h) for h in self._history]}
        if data == self._saved:
            return
        try:
            atomic_write_json(self._path, data, mode=0o600, sort_keys=True)
            self._save_failed = False
            self._saved = data
        except (OSError, TypeError, ValueError) as e:
            if not self._save_failed:
                log.error("Crash SMS: cannot save %s (%s) — a restart would forget the "
                          "event (the phone still holds its deadline)", self._path,
                          clean_error(e))
            self._save_failed = True

    def load(self) -> None:
        """Read the saved event (worker, at start) and decide how to go on."""
        try:
            with open(self._path, "rb") as f:
                raw = f.read(STATE_FILE_MAX + 1)
        except FileNotFoundError:
            self._publish()
            return
        except OSError as e:
            log.warning("Crash SMS: cannot read %s (%s)", self._path, clean_error(e))
            self._publish()
            return
        data = None
        if len(raw) <= STATE_FILE_MAX:
            try:
                data = json.loads(raw.decode("utf-8"),
                                  parse_constant=_cpa._reject_constant)
            except (ValueError, UnicodeDecodeError, RecursionError):
                data = None
        history = _valid_history(data.get("history") if isinstance(data, dict) else None)
        ev = _valid_saved_event(data.get("event") if isinstance(data, dict) else None)
        if not isinstance(data, dict) or history is None or (
                data.get("event") is not None and ev is None):
            log.warning("Crash SMS: %s is damaged — ignored", self._path)
            history, ev = history or [], None
        now, wall = self._clock(), self._wall()
        with self._lock:
            self._history = [h for h in history if abs(wall - h["ts"]) < DAY_S][-HISTORY_MAX:]
        if ev is not None:
            self._resume(ev, now, wall)
        self._publish()

    def _resume(self, saved: dict, now: float, wall: float) -> None:
        age = max(0.0, wall - saved["created_ts"])
        ev = dict(saved)
        ev.update(created_mono=now - age, deadline_mono=None, final_mono=None,
                  phone_ok=False, next_try=now, retry=RETRY_MIN_S, reconcile_until=None,
                  arm_until=now, followed_until=now + max(0.0, ACTIVE_MAX_S - age),
                  cancel_mono=now if saved["cancel_pending"] else None)
        if ev["deadline_ts"] is not None:
            ev["deadline_mono"] = now + (ev["deadline_ts"] - wall)
        if ev["final_ts"] is not None:
            ev["final_mono"] = now - max(0.0, wall - ev["final_ts"])
        state = ev["state"]
        if state in ACTIVE and age > RESUME_MAX_AGE_S:
            log.warning("Crash SMS: saved event %s (%s) is %d min old — not resumed",
                        ev["id"], state, int(age // 60))
            # Inert: no request about it ever again, no window, and it does
            # not block a new event (see _live).
            ev["final_mono"] = now - FINAL_SHOW_S
            ev["followed_until"] = float("inf")
            ev["next_try"] = float("inf")
            ev["cancel_pending"] = False
            ev["send_now_pending"] = False
        elif state == "armed":
            if age < REARM_MAX_AGE_S and ev["arm"] is not None and not ev["cancel_pending"]:
                # A restart while arming (e.g. the power dropped at the
                # impact): arm again (idempotent by id), and keep trying
                # until the event is REARM_MAX_AGE_S old — after a reboot
                # the agent's forward needs adb, the device and a USB
                # re-enumeration first. The phone then gets at least its
                # 15 s minimum (the window shows "Łączenie z telefonem…").
                ev["arm_until"] = max(now + ARM_RETRY_WINDOW_S,
                                      ev["created_mono"] + REARM_MAX_AGE_S)
                ev["maybe_delivered"] = True
                log.warning("Crash SMS: resuming %s — arming the phone again", ev["id"])
            else:
                # Too late to start a countdown now; the phone may hold it.
                ev["state"] = "failed_no_phone"
                ev["error"] = "no_phone"
                ev["final_ts"] = wall
                ev["final_mono"] = now - (FINAL_SHOW_S if age > FINAL_SHOW_S else 0.0)
                ev["reconcile_until"] = now + RECONCILE_AFTER_DEADLINE_S
        elif state in ("pending", "sending"):
            log.warning("Crash SMS: resuming %s (%s) — looking it up on the phone",
                        ev["id"], state)
        elif state == "failed_no_phone" and ev["maybe_delivered"] and age < RESUME_MAX_AGE_S:
            ev["reconcile_until"] = now + max(0.0, ev["countdown_s"] - age) \
                + RECONCILE_AFTER_DEADLINE_S
        with self._lock:
            self._ev = ev


def _live(ev: dict) -> bool:
    """Active and still followed (an event given up on — too old after a
    restart, or followed for :data:`ACTIVE_MAX_S` — is inert)."""
    return ev["state"] in ACTIVE and ev["followed_until"] != float("inf")


# ── saved-state validation (the file may be damaged or replaced) ──────────

def _valid_history(raw: Any) -> Optional[list[dict]]:
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > HISTORY_MAX * 2:
        return None
    out = []
    for h in raw:
        if not isinstance(h, dict) or not isinstance(h.get("id"), str) \
                or not EVENT_ID_RE.fullmatch(h["id"]) \
                or _finite(h.get("ts"), 0.0, 4e9) is None \
                or not isinstance(h.get("dry"), bool) or not isinstance(h.get("counted"), bool):
            return None
        out.append({"id": h["id"], "ts": float(h["ts"]), "dry": h["dry"],
                    "counted": h["counted"]})
    return out


def _valid_saved_event(raw: Any) -> Optional[dict]:
    if not isinstance(raw, dict):
        return None
    ev = {k: raw.get(k) for k in CrashSms._SAVED_KEYS}
    if not isinstance(ev["id"], str) or not EVENT_ID_RE.fullmatch(ev["id"]) \
            or ev["state"] not in STATES or ev["state"] == "idle":
        return None
    if _finite(ev["created_ts"], 0.0, 4e9) is None \
            or _finite(ev["event_ts"], 0.0, 4e9) is None \
            or not isinstance(ev["countdown_s"], int) or isinstance(ev["countdown_s"], bool) \
            or not _cpa.COUNTDOWN_MIN_S <= ev["countdown_s"] <= _cpa.COUNTDOWN_MAX_S:
        return None
    for key in ("deadline_ts", "final_ts"):
        if ev[key] is not None and _finite(ev[key], 0.0, 4e9) is None:
            return None
    for key in ("dry_run", "cancel_pending", "send_now_pending", "maybe_delivered",
                "confirmed", "went_out", "follow_up"):
        if not isinstance(ev[key], bool):
            return None
    if ev["forced_reason"] not in FORCED_REASONS or ev["error"] not in ERRORS \
            or ev["cancel_source"] not in ("",) + SOURCES:
        return None
    n = ev["recipients_n"]
    if not isinstance(n, int) or isinstance(n, bool) or not 0 <= n <= _cpa.MAX_RECIPIENTS:
        return None
    results = ev["results"]
    if not isinstance(results, list) or len(results) > _cpa.MAX_RECIPIENTS or not all(
            isinstance(r, dict) and r.get("state") in RCPT_STATES
            and isinstance(r.get("verified"), bool) for r in results):
        return None
    ev["results"] = [{"state": r["state"], "verified": r["verified"]} for r in results]
    cancel = ev["cancel_sms"]
    if cancel is not None and not (isinstance(cancel, dict) and cancel.get("state") in (
            "sending", "sent", "partial", "failed")):
        return None
    ev["cancel_sms"] = None if cancel is None else {"state": cancel["state"]}
    arm = ev["arm"]
    if arm is not None:
        if not isinstance(arm, dict):
            return None
        lims = {"lat": (-90.0, 90.0), "lon": (-180.0, 180.0), "fix_age_s": (0.0, 86400.0),
                "speed_kmh": (0.0, 400.0), "dv_kmh": (0.0, 400.0)}
        clean = {}
        for key, (lo, hi) in lims.items():
            v = arm.get(key)
            if v is not None and _finite(v, lo, hi) is None:
                return None
            clean[key] = v
        ev["arm"] = clean
    ev["created_ts"] = float(ev["created_ts"])
    ev["event_ts"] = int(ev["event_ts"])
    return ev


# ── the running instance (for the web routes) ─────────────────────────────

_INSTANCE: Optional[CrashSms] = None
_INSTANCE_LOCK = threading.Lock()


def get_crash_sms() -> Optional[CrashSms]:
    """The running module, or None (not enabled, not started, stopped)."""
    with _INSTANCE_LOCK:
        return _INSTANCE


def start_crash_sms(config, event_bus, hal=None, **kwargs) -> CrashSms:
    """Module entry point (``modules.crash_sms``): builds the object,
    registers it for :func:`get_crash_sms`, subscribes and starts its one
    daemon thread; every agent request happens there."""
    global _INSTANCE
    module = CrashSms(config, event_bus)
    with _INSTANCE_LOCK:
        _INSTANCE = module
    module.start()
    return module
