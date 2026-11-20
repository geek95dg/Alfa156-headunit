"""Alarm on the parked car (plan D4) — BCM's side.

Why it is built this way
------------------------
When the car is parked BCM is off (the test car has no buffered power:
every engine stop cuts the M910q and the phone's USB power), so the alarm
itself — arming on power loss, the accelerometer, the SMS commands with a
TOTP code, the alarm SMS — runs ON THE CAR PHONE, in the Termux agent
(tools/car_phone/termux/bcm_agent.py, ``ParkGuard``). This module is what
BCM adds while it runs:

* **Owner proof → disarm.** The phone disarms ONLY on proof of the owner,
  never on power or ignition alone (a thief turns the key too). BCM's proof
  is the owner's phone holding an AUTHENTICATED Bluetooth link: its
  address in ``BluetoothManager.authenticated_peers()`` — oFono's HFP voice
  modem for that address, which exists only after the RFCOMM channel came
  up, i.e. after link-key authentication and encryption. ``bt.connected``
  alone is NOT proof: BlueZ reports a device Connected at ACL level,
  before authentication, so anyone presenting the owner's BD_ADDR (MAC
  spoofing; the address is easy to learn) would pass. The owner address on
  ``bt.connected`` (a new address = a connection EDGE) only starts the
  check: the worker waits up to :data:`PROOF_WAIT_S` for the HFP link,
  then sends ONE signed ``POST /v1/park/disarm {}`` — re-checking the proof
  before every retry, retried with backoff until the phone confirms it
  (BCM boots faster than the agent forward comes up) or
  :data:`DISARM_TTL_S` passes, never a second one for the same connection;
  ``bt.disconnected`` of that address cancels it. Without a live oFono
  monitor there is no Bluetooth proof — the TOTP code (Rozbrój) and the SMS
  ``PARK OFF <kod>`` still work. Residual risk: BIAS/KNOB-class attacks on
  an unpatched Bluetooth controller. Owner phones: ``parking_guard.owner_macs`` (up to
  :data:`MAX_OWNER_MACS`, local.yaml) when set — ONLY those; otherwise the
  ``multimedia.last_bt_device`` read once at module start, i.e. the phone
  that was connected last BEFORE this boot (a phone paired today becomes
  "the owner's" from the next drive on — after the alarm has already gone
  out if it was not the owner's).
* **The phone's state** (``GET /v1/park``) every :data:`POLL_S` on the
  module's own worker, published on ``park.state`` for the Settings row
  "Postój" (state, last event, battery). Never ``alarm.sensor.*`` — that is
  the siren alarm module (src/vehicle/alarm.py), which treats every value
  as a break-in. An alarm the phone raised while BCM was off shows ONE
  notification after the next start.
* **Uzbrój / Rozbrój** from the head unit's own screen (web_viewer's
  loopback-only routes): :meth:`ParkingGuard.request_arm` (no proof
  needed; refused with ``moving`` while ``gps.speed`` is fresh and above
  :data:`ARM_MAX_SPEED_KMH` — arming a moving car would only alarm the
  driver; the phone also postpones arming while its accelerometer says
  "driving") and :meth:`ParkingGuard.request_disarm` — without a code only
  while an owner phone is connected (the same proof as above); otherwise
  with the 6-digit TOTP code from the owner's authenticator app, which the
  PHONE checks (BCM never knows the TOTP secret). A thief at the car's
  screen has neither (a spoofed address gives no HFP link).

The settings themselves (numbers, log_only, home zone, thresholds) reach
the phone through car_phone_agent's config push (``park_*`` keys, only
while ``modules.parking_guard`` is on — see
src/network/car_phone_agent.py). The toggle on the phone mirrors
``modules.parking_guard`` — but switching it off is NOT an owner proof
(anyone at the car's screen can open Settings → Moduły): an armed phone
(agent >= 1.5.0) keeps guarding with its last settings until the owner's
proof (``off_pending`` in the state), and web_viewer refuses the toggle
with ``disarm_first`` while the last state is armed without the owner's
phone (:func:`disarm_first`).

Published ``park.state`` (on change)::

    {state, since, by, arm_at, last_event {kind, ts, value, logged_only} | None,
     battery_pct, power, log_only, light, sensor, totp_ready, numbers_n,
     home_set, alarms_today, entry_until, off_pending, owner_connected,
     owner_unproven, owner_known, bt_proof, disarm_pending, error,
     cmd {action, ok, error, ts} | None}

    state: unknown (no answer yet) | off | disarmed | arming | armed | alarm
           | log_only
    error: '' | no_agent | agent_outdated | no_answer | agent_error
    cmd:   the outcome of the last Uzbrój / Rozbrój from Settings

Threads: bus callbacks only validate and enqueue; every agent request runs
on the module's ONE worker thread — never the bus dispatcher, never module
start. The web routes call :meth:`request_arm` / :meth:`request_disarm`
(no I/O, any thread).

The only switch is ``modules.parking_guard`` (requires
``car_phone_agent``); there is no ``enabled`` sub-key.
"""

from __future__ import annotations

import math
import queue
import re
import threading
import time
from typing import Any, Callable, Optional

from src.core.logger import get_logger
from src.network import car_phone_agent as _cpa
from src.network._proc import _cfg_get

log = get_logger("safety.parking_guard")

TOPIC_STATE = "park.state"
STATES = ("unknown",) + _cpa.PARK_STATES
ERRORS = ("", "no_agent", "agent_outdated", "no_answer", "agent_error")
CMD_ACTIONS = ("arm", "disarm")
CMD_ERRORS = ("", "no_agent", "agent_outdated", "no_answer", "parking_guard_off", "bad_code",
              "code_used", "no_totp", "rate_limited", "low_battery", "owner_required",
              "agent_error", "crash_holdoff")
#: GET /v1/park every 30 s while the phone answers; backoff while not.
POLL_S = 30.0
POLL_FAIL_MIN_S = 10.0
POLL_FAIL_MAX_S = 120.0
#: How long a connection edge of an owner address waits for the
#: authenticated HFP link (oFono's modem comes a few seconds after connect).
PROOF_WAIT_S = 60.0
PROOF_POLL_S = 2.0
#: The disarm of one connection edge: retried 5 s → 60 s, given up after 15 min.
DISARM_RETRY_MIN_S = 5.0
DISARM_RETRY_MAX_S = 60.0
DISARM_TTL_S = 900.0
MAX_OWNER_MACS = 4
QUEUE_MAX = 32
IDLE_WAIT_S = 30.0
MAC_RE = re.compile(r"^[0-9A-F]{2}(:[0-9A-F]{2}){5}$")
#: "Uzbrój" is refused above this speed (km/h) while the last ``gps.speed``
#: is at most :data:`SPEED_FRESH_S` old (no fix = no speed = allowed).
ARM_MAX_SPEED_KMH = 5.0
SPEED_FRESH_S = 10.0
MAX_SPEED_KMH = 400.0
CODE_RE = _cpa.PARK_CODE_RE
#: Agent errors that mean "nothing answered" (vs. an agent that refused).
_NO_ANSWER = ("no_forward", "connect", "dropped", "timeout", "busy", "stopped", "no_secret")


def normalize_mac(value: Any) -> Optional[str]:
    """``aa:bb:cc:dd:ee:ff`` → ``AA:BB:CC:DD:EE:FF``; None if not a MAC."""
    if not isinstance(value, str):
        return None
    mac = value.strip().upper()
    return mac if MAC_RE.fullmatch(mac) else None


def owner_macs(config: Any) -> tuple[frozenset, str]:
    """``(owner MACs, source)``: ``parking_guard.owner_macs`` when it lists
    any valid MAC (ONLY those), else ``multimedia.last_bt_device`` as it is
    NOW (the caller reads it once, at module start). Invalid entries are
    logged (never the MACs themselves) and skipped."""
    raw = _cfg_get(config, "parking_guard.owner_macs", [])
    listed: set[str] = set()
    if isinstance(raw, list):
        for item in raw[:MAX_OWNER_MACS * 2]:
            mac = normalize_mac(item)
            if mac is None:
                log.warning("Parking guard: an entry of parking_guard.owner_macs is not a MAC "
                            "(AA:BB:CC:DD:EE:FF) — ignored")
            elif len(listed) < MAX_OWNER_MACS:
                listed.add(mac)
    elif raw not in (None, ""):
        log.warning("Parking guard: parking_guard.owner_macs is not a list — ignored")
    if listed:
        return frozenset(listed), "owner_macs"
    last = normalize_mac(_cfg_get(config, "multimedia.last_bt_device", ""))
    return (frozenset({last}), "last_bt_device") if last else (frozenset(), "")


def _event_mac(value: Any) -> Optional[str]:
    return normalize_mac(value.get("address")) if isinstance(value, dict) else None


def _error_of(res: dict) -> str:
    """An agent API result → this module's error code."""
    err = res.get("error") or ""
    if err == "no_agent":
        return "no_agent"
    if err == "not_found":
        return "agent_outdated"         # an agent before 1.2.0 has no /v1/park
    if err in _NO_ANSWER:
        return "no_answer"
    return "agent_error"


class ParkingGuard:
    """See the module docstring.

    Args:
        config: BCMConfig or nested dict.
        event_bus: EventBus.
        agent_getter: returns the running CarPhoneAgent or None.
        clock / wall_clock: monotonic / epoch seconds (tests pass fakes).
        notify: ``publish_notification``-compatible (tests).
        bt_manager: the shared BluetoothManager (main.py) — its
            ``authenticated_peers()`` is the Bluetooth owner proof; None =
            no Bluetooth proof (code / SMS only).
    """

    def __init__(self, config: Any, event_bus: Any,
                 agent_getter: Optional[Callable[[], Any]] = None,
                 clock: Callable[[], float] = time.monotonic,
                 wall_clock: Callable[[], float] = time.time,
                 notify: Optional[Callable[..., Any]] = None,
                 bt_manager: Any = None) -> None:
        self._config = config
        self._bus = event_bus
        self._bt = bt_manager
        self._agent_getter = agent_getter or _cpa.get_agent
        self._clock = clock
        self._wall = wall_clock
        if notify is None:
            from src.core.notifications import publish_notification as notify
        self._notify = notify
        self._owners, self._owner_source = owner_macs(config)
        self._q: queue.Queue = queue.Queue(maxsize=QUEUE_MAX)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._subscribed = False
        # Worker state (``_connected`` also read by request_disarm, under _lock).
        self._connected: Optional[str] = None
        self._disarm: Optional[dict[str, Any]] = None
        self._view: Optional[dict[str, Any]] = None
        self._error = ""
        self._next_poll = 0.0
        self._poll_delay = POLL_FAIL_MIN_S
        self._cmd: Optional[dict[str, Any]] = None
        self._published: Optional[dict[str, Any]] = None
        self._alarm_seen: Optional[int] = None
        self._logged_error = ""
        # The last gps.speed (km/h, module clock), under _lock.
        self._speed: Optional[tuple[float, float]] = None
        log.info("Parking guard ready (owner phones: %d from %s)", len(self._owners),
                 self._owner_source or "nowhere — set parking_guard.owner_macs")
        if bt_manager is None:
            log.warning("Parking guard: no Bluetooth (modules.bluetooth off or no adapter) — "
                        "the owner's phone cannot disarm; only the TOTP code (Rozbrój) and "
                        "SMS PARK OFF <kod> do, otherwise every engine start alarms after "
                        "parking_guard grace_min")

    # ── lifecycle ─────────────────────────────────────────────────────────

    def _subscriptions(self) -> tuple:
        return (("bt.connected", self._on_bt_connected),
                ("bt.disconnected", self._on_bt_disconnected),
                (_cpa.TOPIC, self._on_agent),
                ("gps.speed", self._on_speed),
                ("power.shutting_down", self._on_shutdown))

    def subscribe(self) -> None:
        if self._subscribed:
            return
        self._subscribed = True
        for topic, cb in self._subscriptions():
            self._bus.subscribe(topic, cb)
        # A phone that connected before this module subscribed is an edge too.
        try:
            on = self._bus.get_last("bt.connected")
            off = self._bus.get_last("bt.disconnected")
        except Exception:
            on = off = None
        if on is not None and (off is None or on[1] >= off[1]):
            self._on_bt_connected("bt.connected", on[0], on[1])

    def start(self) -> None:
        """Subscribe and start the worker; no I/O here."""
        self.subscribe()
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, daemon=True,
                                            name="parking-guard")
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
        self._enqueue(None)

    def _on_shutdown(self, topic: str, value: Any, timestamp: float) -> None:
        if value:
            self.stop()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                wait = self.run_once()
            except Exception:
                log.exception("Parking guard: worker pass failed")
                wait = POLL_FAIL_MIN_S
            try:
                cmd = self._q.get(timeout=max(0.05, min(wait, IDLE_WAIT_S)))
            except queue.Empty:
                continue
            self._handle_safe(cmd)

    def run_once(self) -> float:
        """Everything queued, then one :meth:`step`. Returns the sleep."""
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
            log.exception("Parking guard: command %r failed", cmd[0] if cmd else cmd)

    def _enqueue(self, item: Any) -> bool:
        try:
            self._q.put_nowait(item)
            return True
        except queue.Full:
            log.warning("Parking guard: command queue full — %r dropped",
                        item[0] if isinstance(item, tuple) else item)
            return False

    # ── bus callbacks (dispatcher thread: validate + enqueue only) ─────────

    def _on_bt_connected(self, topic: str, value: Any, timestamp: float) -> None:
        mac = _event_mac(value)
        if mac is not None:
            self._enqueue(("bt_on", mac))

    def _on_bt_disconnected(self, topic: str, value: Any, timestamp: float) -> None:
        self._enqueue(("bt_off", _event_mac(value)))

    def _on_agent(self, topic: str, value: Any, timestamp: float) -> None:
        if isinstance(value, dict) and value.get("state") == "ok":
            self._enqueue(("agent_ok",))

    def _on_speed(self, topic: str, value: Any, timestamp: float) -> None:
        """``gps.speed`` (km/h, published only with a fix): validated and
        recorded for :attr:`moving` — nothing else on the dispatcher."""
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return
        speed = float(value)
        if not math.isfinite(speed) or not 0.0 <= speed <= MAX_SPEED_KMH:
            return
        with self._lock:
            self._speed = (speed, self._clock())

    # ── API for the web routes (any thread, no I/O) ───────────────────────

    def _proven(self, mac: Optional[str]) -> bool:
        """``mac`` holds an authenticated HFP link now (no I/O)."""
        if mac is None or self._bt is None:
            return False
        try:
            peers = self._bt.authenticated_peers()
        except Exception:
            return False
        return isinstance(peers, (set, frozenset)) and mac in peers

    def _owner_link(self) -> tuple[bool, bool]:
        """``(owner address connected, and proven)``."""
        with self._lock:
            mac = self._connected if self._connected in self._owners else None
        return mac is not None, self._proven(mac)

    @property
    def owner_connected(self) -> bool:
        """An owner phone is connected WITH an authenticated HFP link (the
        proof for "Rozbrój" without a code) — never the address alone."""
        return self._owner_link()[1]

    @property
    def moving(self) -> bool:
        """The car drives: a fresh ``gps.speed`` above :data:`ARM_MAX_SPEED_KMH`."""
        with self._lock:
            sp = self._speed
        return sp is not None and 0.0 <= self._clock() - sp[1] <= SPEED_FRESH_S \
            and sp[0] > ARM_MAX_SPEED_KMH

    def request_arm(self) -> dict:
        """"Uzbrój" (Settings): the phone arms after its own exit window.
        Refused (``moving``) while the car drives."""
        if self._stop.is_set():
            return {"ok": False, "error": "stopped"}
        if self.moving:
            return {"ok": False, "error": "moving"}
        if not self._enqueue(("arm",)):
            return {"ok": False, "error": "busy"}
        return {"ok": True}

    def request_disarm(self, code: Any = None) -> dict:
        """"Rozbrój" (Settings): with an owner phone connected no code is
        needed (``owner_required`` otherwise); ``code`` = the 6-digit TOTP
        code, checked by the phone. The code goes to the worker's queue and
        from there into ONE signed request — never the bus or the log."""
        if self._stop.is_set():
            return {"ok": False, "error": "stopped"}
        if code is not None and (not isinstance(code, str) or not CODE_RE.fullmatch(code)):
            return {"ok": False, "error": "bad_request"}
        if code is None and not self.owner_connected:
            return {"ok": False, "error": "owner_required"}
        if not self._enqueue(("disarm", code)):
            return {"ok": False, "error": "busy"}
        return {"ok": True}

    @property
    def state(self) -> Optional[dict[str, Any]]:
        with self._lock:
            return dict(self._published) if self._published is not None else None

    # ── worker ────────────────────────────────────────────────────────────

    def handle(self, cmd: tuple) -> None:
        kind = cmd[0]
        if kind == "bt_on":
            self._bt_on(cmd[1])
        elif kind == "bt_off":
            with self._lock:
                gone = cmd[1] is None or cmd[1] == self._connected
                if gone:
                    self._connected = None
            if gone and self._disarm is not None:
                # The proof is the LIVE link: a disarm not confirmed yet is
                # not retried after it went away (a spoofed address may get
                # a short connection; the real owner's next connection is a
                # new edge anyway).
                log.info("Parking guard: the owner's phone disconnected before the phone "
                         "confirmed the disarm — not retried")
                self._disarm = None
        elif kind == "agent_ok":
            # The agent (re)appeared: a pending disarm and a poll go now.
            if self._disarm is not None:
                self._disarm["next"] = 0.0
            self._next_poll = 0.0
        elif kind == "arm":
            self._command("arm", None)
        elif kind == "disarm":
            self._command("disarm", cmd[1])
        self._publish()

    def _bt_on(self, mac: str) -> None:
        """A connection EDGE is a new address — the same connection published
        again (bluetooth re-syncs its state) is not."""
        with self._lock:
            if mac == self._connected:
                return
            self._connected = mac
            owner = mac in self._owners
        if not owner:
            log.info("Parking guard: a phone that is not the owner's connected — no disarm")
            return
        now = self._clock()
        self._disarm = {"since": now, "next": 0.0, "delay": DISARM_RETRY_MIN_S, "tries": 0,
                        "mac": mac, "proof_until": now + PROOF_WAIT_S, "sent": False}
        log.info("Parking guard: the owner's phone connected — waiting for its HFP link "
                 "before disarming")

    def _agent(self) -> Any:
        try:
            return self._agent_getter()
        except Exception:
            return None

    def step(self) -> float:
        """The pending disarm (retries) and the poll; returns the sleep."""
        now = self._clock()
        waits = [IDLE_WAIT_S]
        if self._disarm is not None:
            d = self._disarm
            if now - d["since"] > DISARM_TTL_S:
                log.warning("Parking guard: the phone did not confirm the disarm within %d min "
                            "— given up (PARK OFF <kod> by SMS still works)",
                            DISARM_TTL_S // 60)
                self._disarm = None
            elif now >= d["next"]:
                if self._proven(d["mac"]):
                    self._send_disarm(now)
                elif not d["sent"] and now >= d["proof_until"]:
                    log.warning("Parking guard: the owner's address connected, but no HFP "
                                "link within %d s — NOT disarmed (a bare connection is no "
                                "proof; Rozbrój with the code or PARK OFF <kod>)",
                                PROOF_WAIT_S)
                    self._disarm = None
                else:
                    # No proof (yet / any more): checked again shortly,
                    # never sent without it.
                    d["next"] = now + PROOF_POLL_S
            if self._disarm is not None:
                waits.append(self._disarm["next"] - now)
        if now >= self._next_poll:
            self._poll(now)
        waits.append(self._next_poll - now)
        self._publish()
        return max(0.05, min(waits))

    def _send_disarm(self, now: float) -> None:
        d = self._disarm
        assert d is not None
        agent = self._agent()
        d["tries"] += 1
        d["sent"] = True
        res = agent.park_disarm() if agent is not None else {"ok": False, "error": "no_agent"}
        if res.get("ok") or res.get("error") == "parking_guard_off":
            # Done for this connection (with the phone's toggle off there is
            # nothing armed to disarm).
            self._disarm = None
            view = _cpa.parse_park_view(res.get("data")) if res.get("ok") else None
            if view is not None:
                self._view, self._error = view, ""
            log.info("Parking guard: disarmed by the owner's phone (try %d)", d["tries"])
            return
        d["next"] = now + d["delay"]
        d["delay"] = min(d["delay"] * 2, DISARM_RETRY_MAX_S)
        if d["tries"] == 1:
            log.warning("Parking guard: disarm not confirmed yet (%s) — retrying",
                        res.get("error") or "?")

    def _poll(self, now: float) -> None:
        agent = self._agent()
        if agent is None:
            self._failed(now, "no_agent")
            return
        res = agent.park_status()
        view = _cpa.parse_park_view(res.get("data")) if res.get("ok") else None
        if view is None:
            self._failed(now, _error_of(res) if not res.get("ok") else "agent_error")
            return
        self._view, self._error = view, ""
        self._logged_error = ""
        self._poll_delay = POLL_FAIL_MIN_S
        self._next_poll = now + POLL_S
        self._maybe_notify(view)

    def _failed(self, now: float, error: str) -> None:
        self._error = error
        self._next_poll = now + self._poll_delay
        self._poll_delay = min(self._poll_delay * 2, POLL_FAIL_MAX_S)
        if error != self._logged_error:
            self._logged_error = error
            if error == "agent_outdated":
                log.warning("Parking guard: the agent on the phone has no parking guard (older "
                            "than 1.2.0) — copy the new tools/car_phone/termux/bcm_agent.py "
                            "(docs §5.12)")
            else:
                log.info("Parking guard: no state from the phone (%s)", error)

    def _command(self, action: str, code: Optional[str]) -> None:
        """Uzbrój / Rozbrój from Settings (worker thread)."""
        agent = self._agent()
        if agent is None:
            res: dict = {"ok": False, "error": "no_agent"}
        elif action == "arm":
            res = agent.park_arm()
        else:
            if code is None and not self.owner_connected:
                res = {"ok": False, "error": "owner_required"}
            else:
                res = agent.park_disarm(code)
        ok = bool(res.get("ok"))
        err = res.get("error") or ""
        if not ok and err not in CMD_ERRORS:
            err = _error_of(res)
        view = _cpa.parse_park_view(res.get("data"))
        if view is not None:
            self._view, self._error = view, ""
        self._cmd = {"action": action, "ok": ok, "error": "" if ok else err,
                     "ts": self._wall()}
        log.info("Parking guard: %s from the car's screen %s%s", action,
                 "accepted" if ok else "refused: ", "" if ok else err)

    def _maybe_notify(self, view: dict) -> None:
        """ONE notification for an alarm the phone raised (seen at the first
        poll after BCM starts, or live)."""
        ev = view.get("last_event")
        if view.get("state") != "alarm" or not isinstance(ev, dict):
            return
        ts = ev.get("ts")
        if ts == self._alarm_seen:
            return
        self._alarm_seen = ts
        what = {"tilt": "przechył (podnośnik / holowanie)", "shake": "wstrząs / kołysanie",
                "power": "zasilanie bez telefonu właściciela",
                "cabin": "ruch w kabinie (czuwanie kabiny, zdjęcia w telefonie)"}.get(
            ev.get("kind"), "czujnik")
        when = time.strftime("%d.%m %H:%M", time.localtime(ts)) if ts else ""
        try:
            self._notify(self._bus, "Alarm na postoju", f"{what} {when}".strip(),
                         severity="danger", icon="car_crash", ttl=60, key="parking_guard_alarm")
        except Exception:
            log.exception("Parking guard: notification failed")

    # ── publication ───────────────────────────────────────────────────────

    def payload(self) -> dict[str, Any]:
        view = self._view or {}
        owner_present, owner_connected = self._owner_link()
        out: dict[str, Any] = {
            "state": view.get("state", "unknown") if view else "unknown",
            "since": view.get("since"), "by": view.get("by", ""),
            "arm_at": view.get("arm_at"),
            "last_event": dict(view["last_event"]) if view.get("last_event") else None,
            "battery_pct": view.get("battery_pct"), "power": view.get("power"),
            "log_only": view.get("log_only", True) if view else None,
            "light": bool(view.get("light")), "sensor": view.get("sensor", "off"),
            "totp_ready": bool(view.get("totp_ready")),
            "numbers_n": int(view.get("numbers_n") or 0),
            "home_set": bool(view.get("home_set")),
            "alarms_today": int(view.get("alarms_today") or 0),
            "entry_until": view.get("entry_until"),
            "off_pending": bool(view.get("off_pending")),
            "owner_connected": owner_connected,
            # The owner's address is connected, but without the HFP link
            # that proves it (no oFono, HFP off on the phone — or spoofed).
            "owner_unproven": owner_present and not owner_connected,
            "owner_known": bool(self._owners),
            # Without the BluetoothManager there is no Bluetooth proof.
            "bt_proof": self._bt is not None,
            "disarm_pending": self._disarm is not None,
            "error": self._error if self._error in ERRORS else "agent_error",
            "cmd": dict(self._cmd) if self._cmd else None,
        }
        return out

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


# ── the running instance (for the web routes) ─────────────────────────────

_INSTANCE: Optional[ParkingGuard] = None
_INSTANCE_LOCK = threading.Lock()


def disarm_first(state: Any) -> bool:
    """For Settings → Moduły: True when switching ``parking_guard`` /
    ``cabin_watch`` off must wait for the owner's disarm — the last
    ``park.state`` is armed (or alarming, or an entry window runs) and no
    owner phone is connected. Only the screen's answer: the phone itself
    (agent >= 1.5.0) keeps guarding regardless; an unknown state allows it."""
    if not isinstance(state, dict):
        return False
    armed = state.get("state") in ("armed", "alarm", "log_only") \
        or state.get("entry_until") is not None or state.get("off_pending") is True
    return armed and state.get("owner_connected") is not True


def get_parking_guard() -> Optional[ParkingGuard]:
    """The running module, or None (not enabled, not started, stopped)."""
    with _INSTANCE_LOCK:
        return _INSTANCE


def start_parking_guard(config, event_bus, hal=None, bt_manager=None,
                        **kwargs) -> ParkingGuard:
    """Module entry point (``modules.parking_guard``): builds the object,
    registers it for :func:`get_parking_guard`, subscribes and starts its one
    daemon thread; every agent request happens there. ``bt_manager`` (main.py
    passes the shared BluetoothManager) gives the Bluetooth owner proof."""
    global _INSTANCE
    module = ParkingGuard(config, event_bus, bt_manager=bt_manager)
    with _INSTANCE_LOCK:
        _INSTANCE = module
    module.start()
    return module
