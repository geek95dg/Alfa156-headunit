"""Session after a remote wake (plan E, the buffered build) — BCM's side.

Why it is built this way
------------------------
In the buffered build the M910q sleeps in S3 (or is off) while the car is
parked, and only Nano #2 (sensor_hub, ``FEATURE_WAKE_*``) can wake it: a
door opening at the driver's door, an IR frame from the car phone (the Termux
agent, ``WAKE <code>`` SMS or the ``wake.sh`` shortcut) or a pulse on its
EXT input. The Nano presses the power button and gives the computer a
**lease** (door 5 min, IR/EXT 10 min); when the lease ends with the ignition
still off it presses SHORT and the computer goes back to S3. The firmware
owns the rules (ignition off, rate limits, the door hold-off, the bank
voltage) — sensor_hub/wake_logic.h. Nothing here can wake the computer.

BCM starts AFTER the wake (bcm-sleep-hook.sh), so it never sees the moment
itself: the Nano repeats ``WAKE:<reason>`` and ``LEASE:<s>`` with its full
state every 2 s while the lease lasts (src/input/arduino_serial.py →
``vehicle.wake_reason`` / ``vehicle.wake_lease_s``). This module turns that
into a SESSION the driver can see and steer:

* a global, non-modal banner (app.js, components/wake_banner.js):
  "Wybudzono: telefon/drzwi — uśpienie za mm:ss [Nie usypiaj 30 min]
  [Uśpij teraz]";
* ``hold`` → ``HOLD:<hold_step_min>`` to the Nano (at least that long from
  now; ``hold_max_min`` minutes of holds per session in total), ``sleep`` →
  ``RELEASE`` (the Nano presses SHORT). Commands come from the loopback-only
  routes ``/api/remote_session/{hold,sleep}`` or the bus topics
  :data:`CMD_HOLD` / :data:`CMD_SLEEP`;
* after ``idle_suspend_min`` without use → ``RELEASE`` early. Use is: a
  SWC/button press (``input.raw_keycode``), the kiosk being used —
  ``ui.activity`` from web_viewer: a key, an Android Auto touch or a tap on
  any BCM screen, loopback (the kiosk) only, throttled to one per 5 s —
  Android Auto connecting or disconnecting (``multimedia.openauto_status``
  changes), music stopping, a banner tap, a further wake request at the car
  (the lease jumps up), and the end of a call. A call or music playing
  (``bt.call_state`` not idle, ``bt.media_playing``) holds idle off for as
  long as it lasts — NOT ``bt.a2dp_active``: that only says the main phone
  is connected, which it usually is. The Nano's lease is the hard limit
  anyway; idle only shortens a session that a "Nie usypiaj" extended and
  nobody uses. While idle would end the session before the lease does, its
  deadline is published (``idle_at``) and the banner counts down to it —
  the driver sees when the computer really goes to sleep;
* a call in progress (``bt.call_state``) is never cut by the end of the
  lease: :data:`AUTO_HOLD_BEFORE_S` before it ends the module sends the
  same ``HOLD`` as the button — from the same ``hold_max_min`` budget (the
  firmware caps the whole session at 90 min anyway).

The host NEVER suspends itself here: ``RELEASE`` makes the Nano press SHORT,
which goes the usual way (acpid → bcm-power-toggle.sh: stop BCM, suspend) —
one path to S3, the same as the ignition. ``ignition_watcher.load_config``
is deliberately left alone: fixing it would enable a second, competing
suspend path (``suspend_on_stop: true`` in the config).

Threads: bus callbacks only update state under a lock and wake the worker;
every serial write (``ArduinoSerialListener.send_line``, which may block up
to ~3 s) and every publication happens on the module's own worker thread —
never on the event-bus dispatcher and never in module start.

The only switch is ``modules.remote_session`` (off in code and in both
configs; requires ``input``, which runs arduino_serial). Settings
``power.remote_session.{idle_suspend_min 10, hold_step_min 30,
hold_max_min 60}`` (clamped 1..60) and the IR code the phone sends
(``ir_address`` 0x7A15, ``ir_command`` 0x56 — the same as WAKE_IR_ADDRESS /
WAKE_IR_COMMAND in wake_logic.h; car_phone_agent pushes them to the phone
while the toggle is on).

Published ``power.remote_session`` (on change)::

    {state: idle | session | ending, reason: ir | door | ext | "",
     since (epoch s) | None, lease_until (epoch s) | None,
     idle_at (epoch s; only while idle would end the session first) | None,
     sleep_pending, holds_used_min, hold_step_min, hold_max_min, can_hold,
     idle_suspend_min, link (sensor_hub port open), ended: "" | lease_end |
     released | idle | ignition | lost,
     last_wake: {reason, ts} | None, denied_seen, denied_total | None,
     last_denied: {reason, ts} | None, last_denied_nano: reason | "",
     cmd: {action: hold | sleep | idle, ok, error, ts} | None}
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Optional

from src.core.logger import get_logger

log = get_logger("power.remote_session")

TOPIC_STATE = "power.remote_session"
CMD_HOLD = "power.remote_session.cmd.hold"
CMD_SLEEP = "power.remote_session.cmd.sleep"

STATES = ("idle", "session", "ending")
REASONS = ("ir", "door", "ext")
DENIALS = ("rate", "lowbatt", "holdoff", "state")
ENDED = ("", "lease_end", "released", "idle", "ignition", "lost")
CMD_ACTIONS = ("hold", "sleep", "idle")
CMD_ERRORS = ("", "not_sent", "not_confirmed", "no_session", "hold_limit")

#: Defaults of power.remote_session (clamped to 1..60 min).
DEFAULT_IDLE_SUSPEND_MIN = 10
DEFAULT_HOLD_STEP_MIN = 30
DEFAULT_HOLD_MAX_MIN = 60
MINUTES_RANGE = (1, 60)
#: The private NEC code the car phone sends (wake_logic.h WAKE_IR_ADDRESS /
#: WAKE_IR_COMMAND): a 16-bit address sent low byte first, an 8-bit command
#: sent with its inverse. Changed together on the Nano and in local.yaml.
DEFAULT_IR_ADDRESS = 0x7A15
DEFAULT_IR_COMMAND = 0x56

#: The firmware caps a session at 90 min; a LEASE above that is noise.
LEASE_MAX_S = 5400
#: A LEASE that jumps more than this above the running countdown = the lease
#: was extended (a new wake request at the car, or our HOLD) — activity.
EXTEND_SLACK_S = 5.0
#: RELEASE written but the Nano still reports a lease after this = it did not
#: take (lost byte, old firmware) — the session goes on, the button works again.
RELEASE_CONFIRM_S = 6.0
#: After a RELEASE that did not take, idle does not retry for this long.
IDLE_RETRY_S = 60.0
#: Failed RELEASE writes (port closed) are retried this many times, 5 s apart.
RELEASE_TRIES = 3
RELEASE_RETRY_S = 5.0
#: "ending" (RELEASE confirmed / lease over — the Nano is suspending us) is
#: shown this long, then back to idle (we are still running = it did not).
ENDING_SHOW_S = 120.0
#: No LEASE line for this long after the local countdown reached 0 (the Nano
#: was unplugged), or none at all this long after WAKE: — the session is over.
LOST_GRACE_S = 30.0
NO_LEASE_S = 60.0
#: A call in progress and the lease ends within this: HOLD automatically
#: (retried at most every AUTO_HOLD_RETRY_S while the Nano does not extend).
AUTO_HOLD_BEFORE_S = 90.0
AUTO_HOLD_RETRY_S = 30.0
TICK_S = 1.0
IDLE_WAIT_S = 30.0
#: bt.call_state values that are NOT a call in progress.
_NO_CALL = ("idle", "", None)
#: multimedia.openauto_status values; a CHANGE between them is activity
#: (Android Auto connected / gone), never a permanent "busy" — wireless AA
#: connects by itself whenever the main phone is near.
_AA_STATUSES = ("running", "connected", "stopped", "restarting", "error", "failed",
                "unavailable")


def _cfg_get(config: Any, dotpath: str, default: Any = None) -> Any:
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


def _minutes(block: dict, key: str, default: int) -> int:
    raw = block.get(key)
    lo, hi = MINUTES_RANGE
    if raw is None:
        return default
    if isinstance(raw, bool) or not isinstance(raw, int):
        log.warning("power.remote_session.%s=%r is not a whole number of minutes — using %d",
                    key, raw, default)
        return default
    value = min(max(raw, lo), hi)
    if value != raw:
        log.warning("power.remote_session.%s=%d clamped to %d (%d..%d)", key, raw, value, lo, hi)
    return value


def session_settings(config: Any) -> dict[str, int]:
    """``power.remote_session.{idle_suspend_min, hold_step_min, hold_max_min}``
    → whole minutes 1..60; the step is never above the budget."""
    block = _cfg_get(config, "power.remote_session", {})
    if not isinstance(block, dict):
        block = {}
    out = {"idle_suspend_min": _minutes(block, "idle_suspend_min", DEFAULT_IDLE_SUSPEND_MIN),
           "hold_step_min": _minutes(block, "hold_step_min", DEFAULT_HOLD_STEP_MIN),
           "hold_max_min": _minutes(block, "hold_max_min", DEFAULT_HOLD_MAX_MIN)}
    out["hold_step_min"] = min(out["hold_step_min"], out["hold_max_min"])
    return out


def ir_settings(config: Any, warn: Optional[Callable[[str, str], None]] = None) -> tuple[int, int]:
    """``(address 0..65535, command 0..255)`` of the IR wake code — the ONLY
    values the phone builds its IR frame from (whole numbers, checked again
    on the phone). Anything else → the default, with ``warn(key, message)``."""
    block = _cfg_get(config, "power.remote_session", {})
    if not isinstance(block, dict):
        block = {}
    out = []
    for key, default, hi in (("ir_address", DEFAULT_IR_ADDRESS, 0xFFFF),
                             ("ir_command", DEFAULT_IR_COMMAND, 0xFF)):
        raw = block.get(key, default)
        if isinstance(raw, bool) or not isinstance(raw, int) or not 0 <= raw <= hi:
            if warn is not None:
                warn(f"wake_{key}", f"power.remote_session.{key}={raw!r} is not a whole number "
                                    f"0..{hi} — using {default:#x}")
            raw = default
        out.append(int(raw))
    return out[0], out[1]


class RemoteSession:
    """See the module docstring.

    Args:
        config: BCMConfig or nested dict (``power.remote_session``).
        event_bus: EventBus.
        sender: ``sender(line) -> bool`` writing ``HOLD:<n>`` / ``RELEASE`` to
            the sensor_hub; default: arduino_serial's ``send_line`` found on
            ``input._internals`` (looked up at use, the input module may
            start later).
        clock: monotonic seconds; wall: epoch seconds (tests pass fakes).
    """

    def __init__(self, config: Any, event_bus: Any,
                 sender: Optional[Callable[[str], bool]] = None,
                 clock: Callable[[], float] = time.monotonic,
                 wall: Callable[[], float] = time.time) -> None:
        self._config = config
        self._bus = event_bus
        self._sender = sender
        self._clock = clock
        self._wall = wall
        self._settings = session_settings(config)
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._subscribed = False
        self._published: Optional[dict[str, Any]] = None
        self._warned: set[str] = set()
        # State (under _lock).
        self._state = "idle"
        self._reason = ""
        self._since: Optional[float] = None          # wall
        self._started: Optional[float] = None        # monotonic
        self._lease_until: Optional[float] = None    # monotonic
        self._lease_seen: Optional[float] = None     # monotonic of the last LEASE line
        self._holds_used = 0
        self._last_activity = 0.0
        self._ended = ""
        self._ending_at: Optional[float] = None
        self._ignition: Optional[bool] = None
        self._call_busy = False
        self._media_playing = False
        self._aa_status: Optional[str] = None
        self._link: Optional[bool] = None
        self._last_wake: Optional[dict[str, Any]] = None
        self._denied_seen = 0
        self._denied_total: Optional[int] = None
        self._last_denied: Optional[dict[str, Any]] = None
        self._last_denied_nano = ""
        self._cmd: Optional[dict[str, Any]] = None
        # Commands for the worker: "hold" | "sleep" | "idle" (latest wins).
        self._pending: Optional[str] = None
        self._release_sent_at: Optional[float] = None
        self._release_why = ""
        self._release_tries = 0
        self._release_next = 0.0
        self._idle_block_until = 0.0
        self._auto_hold_next = 0.0

    # ── lifecycle ─────────────────────────────────────────────────────────

    def _subscriptions(self) -> tuple:
        return (("vehicle.wake_reason", self._on_wake),
                ("vehicle.wake_lease_s", self._on_lease),
                ("vehicle.wake_denied", self._on_denied),
                ("vehicle.wake_stats", self._on_stats),
                ("vehicle.ignition_raw", self._on_ignition),
                ("arduino.sensor_hub_connected", self._on_link),
                ("bt.call_state", self._on_call),
                ("bt.media_playing", self._on_media),
                ("bt.a2dp_active", self._on_a2dp),
                ("multimedia.openauto_status", self._on_aa_status),
                ("input.raw_keycode", self._on_input),
                ("ui.activity", self._on_input),
                (CMD_HOLD, self._on_cmd_hold),
                (CMD_SLEEP, self._on_cmd_sleep),
                ("power.shutting_down", self._on_shutdown))

    def start(self) -> None:
        """Subscribe and start the worker; no I/O here."""
        if not self._subscribed:
            self._subscribed = True
            for topic, cb in self._subscriptions():
                self._bus.subscribe(topic, cb)
            self._seed_from_bus()
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, daemon=True,
                                            name="remote-session")
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
        self._wake.set()

    def _seed_from_bus(self) -> None:
        """A call or music that started before this module subscribed (the
        bluetooth module may start first) still holds idle off. Memory only
        (the bus's last values), never I/O."""
        def last(topic: str) -> Any:
            try:
                got = self._bus.get_last(topic)
            except Exception:
                return None
            return got[0] if isinstance(got, tuple) and got else None

        call, media, a2dp = last("bt.call_state"), last("bt.media_playing"), last("bt.a2dp_active")
        aa = last("multimedia.openauto_status")
        with self._lock:
            self._call_busy = isinstance(call, str) and call not in _NO_CALL
            self._media_playing = media is True and a2dp is not False
            self._aa_status = aa if aa in _AA_STATUSES else None

    def _on_shutdown(self, topic: str, value: Any, timestamp: float) -> None:
        if value:
            self.stop()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                wait = self.step()
            except Exception:
                log.exception("Remote session: worker pass failed")
                wait = TICK_S
            self._wake.wait(timeout=max(0.05, wait))
            self._wake.clear()

    # ── bus callbacks (dispatcher thread: state only, never I/O) ──────────

    def _on_wake(self, topic: str, value: Any, timestamp: float) -> None:
        if value not in REASONS:
            return
        now = self._clock()
        with self._lock:
            if self._state == "session":
                self._reason = value
            elif self._state == "idle" and self._ignition is not True:
                # The Nano reports WAKE: only while its lease lasts, and only
                # with the ignition off. "ending" ignores it: we asked the
                # Nano to end the lease, a stale full-state line must not
                # open a new session.
                self._start_session_locked(value, now)
            else:
                return
        self._wake.set()

    def _start_session_locked(self, reason: str, now: float) -> None:
        self._state = "session"
        self._reason = reason
        self._since = self._wall()
        self._started = now
        self._lease_until = None
        self._lease_seen = None
        self._holds_used = 0
        self._last_activity = now
        self._ended = ""
        self._ending_at = None
        self._pending = None
        self._release_sent_at = None
        self._release_why = ""
        self._release_tries = 0
        self._idle_block_until = 0.0
        self._auto_hold_next = 0.0
        self._cmd = None
        self._last_wake = {"reason": reason, "ts": self._since}
        log.info("Remote wake: session started (%s)", reason)

    def _on_lease(self, topic: str, value: Any, timestamp: float) -> None:
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= LEASE_MAX_S:
            return
        now = self._clock()
        with self._lock:
            if self._state != "session":
                return
            self._lease_seen = now
            if value == 0:
                self._end_locked(self._release_why or "lease_end", now)
            else:
                until = now + value
                if self._lease_until is not None and until - self._lease_until > EXTEND_SLACK_S:
                    self._last_activity = now           # extended at the car or by HOLD
                self._lease_until = until
                if self._release_sent_at is not None \
                        and now - self._release_sent_at > RELEASE_CONFIRM_S:
                    # RELEASE was written, yet the lease goes on: it did not take.
                    self._release_sent_at = None
                    self._release_why = ""
                    self._idle_block_until = now + IDLE_RETRY_S
                    self._set_cmd_locked("sleep", False, "not_confirmed")
                    log.warning("Remote wake: RELEASE not confirmed by the sensor_hub — "
                                "session goes on")
        self._wake.set()

    def _on_denied(self, topic: str, value: Any, timestamp: float) -> None:
        if value not in DENIALS:
            return
        with self._lock:
            self._denied_seen = min(self._denied_seen + 1, 1_000_000)
            self._last_denied = {"reason": value, "ts": self._wall()}
        self._wake.set()

    def _on_stats(self, topic: str, value: Any, timestamp: float) -> None:
        if not isinstance(value, dict):
            return
        count, last = value.get("denied"), value.get("last")
        if isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= 0xFFFF:
            return
        with self._lock:
            self._denied_total = count
            self._last_denied_nano = last if last in DENIALS else ""
        self._wake.set()

    def _on_ignition(self, topic: str, value: Any, timestamp: float) -> None:
        if not isinstance(value, bool):
            return
        now = self._clock()
        with self._lock:
            self._ignition = value
            if value and self._state != "idle":
                # The Nano drops the lease itself on ignition; we just stop
                # showing a countdown — the driver is driving now.
                self._end_locked("ignition", now)
                self._state = "idle"
                self._ending_at = None
        self._wake.set()

    def _on_link(self, topic: str, value: Any, timestamp: float) -> None:
        if isinstance(value, bool):
            with self._lock:
                self._link = value
            self._wake.set()

    def _on_call(self, topic: str, value: Any, timestamp: float) -> None:
        busy = value not in _NO_CALL
        with self._lock:
            self._call_busy = busy
            self._last_activity = self._clock()
        self._wake.set()

    def _on_media(self, topic: str, value: Any, timestamp: float) -> None:
        # Music playing = in use (like a call); stopping = activity, so the
        # idle countdown starts from the end of the music.
        if not isinstance(value, bool):
            return
        with self._lock:
            if self._media_playing and not value:
                self._last_activity = self._clock()
            self._media_playing = value
        self._wake.set()

    def _on_a2dp(self, topic: str, value: Any, timestamp: float) -> None:
        # The phone's A2DP went away: bluetooth.py does not reset
        # bt.media_playing then, and a stale True would hold idle off for
        # good. Connecting is NOT activity (the main phone does it alone).
        if value is False:
            with self._lock:
                if self._media_playing:
                    self._media_playing = False
                    self._last_activity = self._clock()
            self._wake.set()

    def _on_aa_status(self, topic: str, value: Any, timestamp: float) -> None:
        if value not in _AA_STATUSES:
            return
        with self._lock:
            if self._aa_status is not None and value != self._aa_status:
                self._last_activity = self._clock()
            self._aa_status = value

    def _on_input(self, topic: str, value: Any, timestamp: float) -> None:
        # input.raw_keycode (SWC/HID) and ui.activity (web_viewer: the kiosk
        # on loopback was used — key, AA touch, tap; throttled there).
        with self._lock:
            self._last_activity = self._clock()

    def _on_cmd_hold(self, topic: str, value: Any, timestamp: float) -> None:
        self.request_hold()

    def _on_cmd_sleep(self, topic: str, value: Any, timestamp: float) -> None:
        self.request_sleep()

    # ── commands (routes, bus) — never block ──────────────────────────────

    def request_hold(self) -> dict[str, Any]:
        """"Nie usypiaj": HOLD:<hold_step_min> on the worker. ``{"ok": True}``
        when queued; ``no_session`` / ``hold_limit`` otherwise."""
        with self._lock:
            if self._state != "session" or self._release_sent_at is not None:
                return {"ok": False, "error": "no_session"}
            if self._holds_used >= self._settings["hold_max_min"]:
                return {"ok": False, "error": "hold_limit"}
            if self._pending != "sleep":
                self._pending = "hold"
            self._last_activity = self._clock()
        self._wake.set()
        return {"ok": True}

    def request_sleep(self) -> dict[str, Any]:
        """"Uśpij teraz": RELEASE on the worker (the Nano presses SHORT)."""
        with self._lock:
            if self._state != "session":
                return {"ok": False, "error": "no_session"}
            self._pending = "sleep"
            self._release_tries = 0
            self._release_next = 0.0
        self._wake.set()
        return {"ok": True}

    # ── worker ────────────────────────────────────────────────────────────

    def _send(self, line: str) -> bool:
        sender = self._sender
        if sender is None:
            internals = None
            try:
                last = self._bus.get_last("input._internals")
                internals = last[0] if last else None
            except Exception:
                internals = None
            listener = internals.get("arduino_serial") if isinstance(internals, dict) else None
            sender = getattr(listener, "send_line", None)
        if not callable(sender):
            if "no_sender" not in self._warned:
                self._warned.add("no_sender")
                log.warning("Remote wake: no Arduino serial listener (module input) — "
                            "%s not sent", line)
            return False
        try:
            return sender(line) is True
        except Exception:
            log.exception("Remote wake: sending %s failed", line)
            return False

    def _set_cmd_locked(self, action: str, ok: bool, error: str = "") -> None:
        self._cmd = {"action": action, "ok": ok, "error": error, "ts": self._wall()}

    def _end_locked(self, why: str, now: float) -> None:
        if self._state != "session":
            return
        self._state = "ending"
        self._ended = why if why in ENDED else "lease_end"
        self._ending_at = now
        self._pending = None
        self._release_sent_at = None
        self._release_why = ""
        log.info("Remote wake: session ended (%s)", self._ended)

    def _busy_locked(self) -> bool:
        """In use for as long as it lasts: a call or music playing."""
        return self._call_busy or self._media_playing

    def _idle_deadline_locked(self) -> Optional[float]:
        """Monotonic moment idle would send RELEASE; None while it cannot
        (in use, a command pending, RELEASE already sent)."""
        if self._state != "session" or self._busy_locked() or self._pending is not None \
                or self._release_sent_at is not None:
            return None
        idle_s = 60.0 * self._settings["idle_suspend_min"]
        return max(self._last_activity + idle_s, self._idle_block_until)

    def step(self) -> float:
        """One pass: expiry, idle, one pending command; returns the sleep."""
        now = self._clock()
        line: Optional[str] = None
        action = ""
        with self._lock:
            if self._state == "ending" and self._ending_at is not None \
                    and now - self._ending_at >= ENDING_SHOW_S:
                # Still running two minutes after the session ended: the
                # Nano did not suspend us (or the ignition…) — back to idle.
                self._state = "idle"
                self._ending_at = None
            if self._state == "session":
                if self._lease_until is not None and now - self._lease_until >= LOST_GRACE_S:
                    self._end_locked("lost", now)       # the Nano went quiet
                elif self._lease_seen is None and self._started is not None \
                        and now - self._started >= NO_LEASE_S:
                    self._end_locked("lost", now)       # WAKE: but never a LEASE:
            if self._state == "session":
                if self._busy_locked():
                    self._last_activity = now
                if self._call_busy:
                    # A call must not be cut by the end of the lease: the
                    # same HOLD as the button, from the same budget. (Music
                    # only holds idle off — the lease ends it as planned.)
                    if self._pending is None and self._release_sent_at is None \
                            and self._lease_until is not None \
                            and self._lease_until - now <= AUTO_HOLD_BEFORE_S \
                            and self._holds_used < self._settings["hold_max_min"] \
                            and now >= self._auto_hold_next:
                        self._pending = "hold"
                        self._auto_hold_next = now + AUTO_HOLD_RETRY_S
                        log.info("Remote wake: call in progress — extending the lease")
                idle_s = 60.0 * self._settings["idle_suspend_min"]
                if self._pending is None and self._release_sent_at is None \
                        and now >= self._idle_block_until \
                        and now - self._last_activity >= idle_s:
                    self._pending = "idle"
                    self._release_tries = 0
                    self._release_next = 0.0
                if self._pending == "hold":
                    step_min = min(self._settings["hold_step_min"],
                                   self._settings["hold_max_min"] - self._holds_used)
                    if step_min >= 1:
                        line, action = f"HOLD:{int(step_min)}", "hold"
                    else:
                        self._pending = None
                        self._set_cmd_locked("hold", False, "hold_limit")
                elif self._pending in ("sleep", "idle") and now >= self._release_next:
                    line, action = "RELEASE", self._pending
                    # Set BEFORE the write: the Nano answers LEASE:0 at once,
                    # possibly before send_line() returns here.
                    self._release_why = "released" if action == "sleep" else "idle"
        ok = self._send(line) if line is not None else False
        with self._lock:
            if line is None:
                pass
            elif action == "hold":
                self._pending = None if self._pending == "hold" else self._pending
                if ok:
                    self._holds_used += int(line.split(":", 1)[1])
                    self._last_activity = self._clock()
                    log.info("Remote wake: lease extended (%s, %d of %d min used)", line,
                             self._holds_used, self._settings["hold_max_min"])
                self._set_cmd_locked("hold", ok, "" if ok else "not_sent")
            elif ok:
                if self._pending == action:
                    self._pending = None
                if self._state == "session":
                    self._release_sent_at = self._clock()
                self._set_cmd_locked(action, True)
                log.info("Remote wake: RELEASE sent (%s)", action)
            elif self._state == "session":
                self._release_why = ""
                self._release_tries += 1
                if self._release_tries >= RELEASE_TRIES:
                    self._pending = None
                    if action == "idle":
                        self._idle_block_until = self._clock() + IDLE_RETRY_S
                    self._set_cmd_locked(action, False, "not_sent")
                    log.warning("Remote wake: RELEASE could not be sent (sensor_hub port) "
                                "— the Nano's lease ends the session")
                else:
                    self._release_next = self._clock() + RELEASE_RETRY_S
            active = self._state != "idle"
        self._publish()
        return TICK_S if active or line is not None else IDLE_WAIT_S

    # ── publication ───────────────────────────────────────────────────────

    def payload(self) -> dict[str, Any]:
        now, wall = self._clock(), self._wall()
        with self._lock:
            until = None
            idle_at = None
            if self._lease_until is not None and self._state == "session":
                # Whole seconds: two clocks, and a quiet session must not be
                # republished every second for float jitter alone.
                until = int(round(wall + (self._lease_until - now)))
                deadline = self._idle_deadline_locked()
                if deadline is not None and deadline < self._lease_until:
                    # Idle ends the session before the lease: the banner
                    # counts down to THIS (changes at most every 5 s — the
                    # ui.activity throttle — so the publication stays rare).
                    idle_at = int(round(wall + (deadline - now)))
            hold_left = self._settings["hold_max_min"] - self._holds_used
            return {
                "state": self._state,
                "reason": self._reason if self._state != "idle" else "",
                "since": self._since if self._state != "idle" else None,
                "lease_until": until,
                "idle_at": idle_at,
                "sleep_pending": self._state == "session" and (
                    self._release_sent_at is not None or self._pending in ("sleep", "idle")),
                "holds_used_min": self._holds_used,
                "hold_step_min": min(self._settings["hold_step_min"], max(hold_left, 0)),
                "hold_max_min": self._settings["hold_max_min"],
                "can_hold": self._state == "session" and hold_left > 0
                and self._release_sent_at is None,
                "idle_suspend_min": self._settings["idle_suspend_min"],
                "link": self._link,
                "ended": self._ended,
                "last_wake": dict(self._last_wake) if self._last_wake else None,
                "denied_seen": self._denied_seen,
                "denied_total": self._denied_total,
                "last_denied": dict(self._last_denied) if self._last_denied else None,
                "last_denied_nano": self._last_denied_nano,
                "cmd": dict(self._cmd) if self._cmd else None,
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

_INSTANCE: Optional[RemoteSession] = None
_INSTANCE_LOCK = threading.Lock()


def get_remote_session() -> Optional[RemoteSession]:
    """The running module, or None (not enabled, not started, stopped)."""
    with _INSTANCE_LOCK:
        return _INSTANCE


def start_remote_session(config, event_bus, hal=None, **kwargs) -> RemoteSession:
    """Module entry point (``modules.remote_session``): builds the object,
    subscribes and starts its one daemon thread; every serial write happens
    there."""
    global _INSTANCE
    module = RemoteSession(config, event_bus)
    with _INSTANCE_LOCK:
        _INSTANCE = module
    module.start()
    return module
