"""„Zadzwoń 112” in the crash window (plan H) — ALWAYS manual.

Why it is built this way
------------------------
After an impact the driver may be hurt, confused or trapped, and the
main phone may be out of reach. The crash window (``#crash-modal``,
components/crash_modal.js) therefore offers a red "PRZYTRZYMAJ 2 s –
ZADZWOŃ 112" button and, from the moment it opens, a dispatcher panel
with the position in big letters (no reverse geocoding: AML rarely
works in Poland and the car phone has no Google services, so reading the
coordinates out is what gets help to the right place).

NOTHING here dials by itself: no countdown, no steering-wheel action, no
bus topic. A call starts only from :meth:`Call112.request_call`, which
only the loopback-only route ``POST /api/crash/call112`` calls after the
driver HELD the button (hold.js: 2 s, inactive for 0.7 s after the window
opens). The number is never taken from a request: it is the constant 112,
or — in test mode — the E.164 test number from local.yaml (and then 112
can never be dialled at all). The SMS countdown (crash_sms) is untouched:
112 never cancels the SMS; the phone adds "Z auta wybrano 112 o hh:mm"
(or sends ONE follow-up SMS when the crash SMS already went out).

Paths (chosen when the button is pressed — :func:`choose_path`)
--------------------------------------------------------------
* **A — the main phone over HFP** (``hfp``): Android lets an emergency
  number from HFP through without a confirmation. Offered only when a
  phone is connected over Bluetooth, oFono has a modem with a
  VoiceCallManager, ``bt.phone_status`` says ``registered``/``roaming``
  (needs ``modules.phone_status``), no other call is up and
  ``audio.mic_state`` is ``ok`` — NEVER without a microphone (the uplink
  would be silence). Dialled through the Bluetooth manager's internal entry
  point :meth:`BluetoothManager.dial_call112` (not the bus: the network
  block of ``/api/phone/dial`` stays as it is). When ``bt.dial_result``
  reports an error, or oFono has not accepted the call within
  :data:`HFP_CONFIRM_S`, path B is offered at once (one more hold). The
  same when the call is up but ``audio.call_route`` (pipewire_ctrl, a few
  seconds after "active") shows the SCO uplink unlinked or fed only by the
  mic router's silent source: the dispatcher may hear nothing, so the
  window says so (``uplink: missing``) and offers path B even DURING the
  HFP call — dialling B hangs the HFP call up first (no double 112).
* **B — the car phone on its speaker** (``car_phone``): the Termux agent
  (``POST /v1/call112``, signed, no number) dials through Magisk ``su`` a
  FIXED ``am start ... CALL_PRIVILEGED ... tel:112`` with the speakerphone
  extra. Offered when the agent is paired and healthy, reports
  ``call112_capable`` and is in the same mode (real/test) as BCM. During
  the call BCM mutes its own media (``input.mute``, the toggle the volume
  controller listens to — only when it is not muted already, and back
  afterwards only if it is still the mute we set).
* **C — none**: the window says "Zadzwoń 112 ze swojego telefonu" and shows
  the dispatcher panel.

``safety.call112.paths`` (default ``[hfp, car_phone]``) is the order and
the allowed set.

Window and limits
-----------------
The window opens on ``crash.detected`` (any source — the 112 button is
manual, a GPS-only event may be a real crash too) and stays available for
``window_min`` (30) minutes, until the driver closes it ("Zamknij",
``POST /api/crash/call112/close``), the car drives on or the crash SMS was
cancelled. "Drives on" is judged HERE from ``gps.speed`` with
crash_detect's own rule (above ``crash_detection.min_speed_kmh``, 25 km/h,
for :data:`DRIVE_ON_SUSTAIN_S` with no gap over :data:`DRIVE_ON_GAP_S`),
also after the car had stopped: crash_detect publishes ONE outcome per
event, so after ``stopped`` it never says ``cancelled`` (that outcome is
still honoured). "SMS cancelled": ``crash.sms_state`` of the same event
reaches ``cancelled`` (ANULUJ / steering wheel / auto) and its result view
is gone (``modal`` false, 60 s later — the 112 column stays next to the
result until then) while nothing was dialled for the event — the driver
said "nic się nie stało", so no full-screen panel over Android Auto for 30
minutes. Never during a live call. For the bench test,
``POST /api/crash/call112/test`` opens the window without a crash — only in
test mode with a test number (:meth:`Call112.open_test_window`). The event
is saved atomically
(``data/call112.json``): the test car has no buffered power, the engine
stopping after an impact cuts BCM — when the key is turned again the
window comes back while it is still within ``window_min``.

At most one dial per :data:`ATTEMPT_MIN_INTERVAL_S` (the route answers
429), except the ONE immediate fallback to the other path after a failed
attempt. The agent has its own limit (1 per 60 s) too.

Published ``crash.call112_state`` (on change; once a second while the
window is open — fix age and call duration)::

    {window, event_id, event_ts, window_until_ts, state, path, error,
     started_ts, active_ts, ended_ts, duration_s, unverified, reached,
     reached_ts, uplink, offer, fallback, reasons {hfp, car_phone},
     retry_after_s, test_mode, test_number, hold_ms, arm_delay_ms, incoming,
     hangup_pending,
     dispatcher {lat, lon, fix_age_s, sats, heading, speed_kmh, event_ts,
                 vehicle {label, colour, plate}} | None}

``state``: ``idle`` (nothing dialled for this event) → ``dialing`` →
``ringing`` (the phone accepted the call: oFono's Dial() answered / the
agent's ``am start`` went through) → ``active`` (oFono "active" / the car
phone OFFHOOK — it cannot tell "ringing" from "talking") → ``ended``; or
``failed`` with ``error``. ``reached`` / ``reached_ts``: the call got as
far as ``ringing`` (and when). In real mode the phone then marks the
crash event ``called_112``: a crash SMS that has not gone out yet gets
"Z auta wybrano 112 o hh:mm" appended (the cancel budget stays — "Jestem
OK" is still possible later); one that already went out gets ONE
follow-up SMS from the cancel budget. crash_sms uses ``reached`` only as
a trigger to re-read the phone's ``follow_up_left``. ``uplink`` (path A):
``unknown`` | ``ok`` | ``missing`` from ``audio.call_route``.
``unverified``: the car phone placed the call but its state is not
readable (or it stopped answering) — followed for at most
:data:`UNVERIFIED_FOLLOW_MAX_S` more, then ``ended`` (still unverified),
so a call BCM can no longer see never keeps the window, the media mute
and the ignored steering-wheel hang-up for an hour. ``incoming``: the
main phone rings while the window is open (the dispatcher calling back) —
the window shows "Odbierz". During a live call (dialing/ringing/active)
the steering-wheel "hang up" is ignored (src/input/input_bridge.py reads
this topic).

Threads: bus callbacks only validate and enqueue (or store a position);
every agent request and the HFP dial run on the module's ONE worker thread
— never the bus dispatcher, never module start. The web routes call
:meth:`Call112.request_call` / :meth:`request_hangup` / :meth:`dismiss`
(no I/O, any thread).

Configuration (``safety.call112.*``, code defaults; the only switch is
``modules.call112``): ``paths [hfp, car_phone]``, ``hold_ms`` 2000
(1000..5000), ``arm_delay_ms`` 700 (300..3000), ``window_min`` 30
(5..120), ``test_mode`` false (only an explicit false is real 112),
``test_number`` "" (E.164, ONLY in local.yaml — never commit a number).
``safety.vehicle.{label, colour, plate}`` (local.yaml) describe the car in
the dispatcher panel.

What this does NOT promise: that a call is set up, that the position
reaches the dispatcher automatically, the quality of a phone speaker under
the headliner. This is not eCall.
"""

from __future__ import annotations

import json
import math
import queue
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from src.core.fsutil import atomic_write_json
from src.core.logger import get_logger
from src.network import car_phone_agent as _cpa
from src.network._proc import _cfg_get, _number, clean_error
from src.safety import crash_detect as _cd

log = get_logger("safety.call112")

TOPIC_STATE = "crash.call112_state"
TOPIC_DETECTED = "crash.detected"
TOPIC_OUTCOME = "crash.outcome"
#: src/safety/crash_sms.py TOPIC_STATE (a string: no import cycle — crash_sms
#: reads THIS module's topic).
TOPIC_SMS_STATE = "crash.sms_state"
STATE_FILE = "data/call112.json"
STATE_FILE_MAX = 8 * 1024

#: The emergency number. A constant: no request, no config ever names it.
EMERGENCY_NUMBER = "112"
PATHS = ("hfp", "car_phone")
CALL_STATES = ("idle", "dialing", "ringing", "active", "ended", "failed")
#: A call in these states is "live": no second dial, no window close, the
#: steering-wheel hang-up is ignored.
LIVE = ("dialing", "ringing", "active")
#: ``error`` values (never free text).
ERRORS = ("", "no_path", "no_modem", "dbus", "busy", "netdown", "invalid", "unknown",
          "timeout", "no_call", "no_phone", "not_running", "refused", "rate_limited",
          "mode_mismatch", "call112_off", "no_test_number", "no_root", "su_missing",
          "su_denied", "am_failed")
#: Why a path is not offered (``reasons``).
REASONS = ("", "off", "not_running", "not_connected", "no_modem", "no_network",
           "call_in_progress", "no_mic", "no_number", "not_ready", "not_capable",
           "mode_mismatch")
#: oFono must have accepted path A's Dial() (or the call be active) this long
#: after the press, else path B is offered.
HFP_CONFIRM_S = 10.0
#: Path B: an answer lost on the way (timeout, dropped connection) may mean
#: the phone IS dialling — look the call up for this long before "failed".
AGENT_VERIFY_S = 20.0
POLL_LIVE_S = 2.0
#: ... and this often after several look-ups in a row failed.
POLL_SLOW_S = 5.0
POLL_FAILS_UNVERIFIED = 5
#: A call is followed at most this long.
CALL_FOLLOW_MAX_S = 3600.0
#: ... and an UNVERIFIED one (state not readable / the car phone no longer
#: answers / the agent forgot it) this long after it became unverified:
#: then it is "ended" (still unverified) — the window can be closed, BCM's
#: media come back and the steering-wheel hang-up works again.
UNVERIFIED_FOLLOW_MAX_S = 300.0
#: "Rozłącz" was taken (agent 200 / HFP HangupAll sent) but the call is
#: still live this long after: the button works again (KEYCODE_ENDCALL is
#: unverified on crDroid — a dead "Rozłączanie…" must not be the end).
HANGUP_CONFIRM_S = 10.0
#: HFP: our hang-up ended the call (optimistic ``idle``) but oFono reports
#: it active again this soon (bluetooth's reconcile, ~3 s): the hang-up did
#: not take — the call is live again. Later "active" is not revived (it may
#: be the dispatcher calling back, which comes as "incoming" first anyway).
HFP_HANGUP_REVIVE_S = 6.0
#: Path B looked up without the agent's call seq (the answer to POST was
#: lost): accept a call requested at most this long before our press. The
#: agent's clock may differ from ours by up to the HMAC window (±60 s,
#: car_phone_agent) — a 30 s margin missed such a call. An older call of
#: this BCM run is told apart by its seq (``seq_floor``).
AGENT_TS_MARGIN_S = 65.0
#: Driving on closes the window: crash_detect's own "no stop" rule (speed
#: above crash_detection.min_speed_kmh for this long, no gap over
#: DRIVE_ON_GAP_S between samples), applied here because crash_detect
#: publishes ONE outcome per event — after "stopped" it never says
#: "cancelled" (see the module docstring).
DRIVE_ON_SUSTAIN_S = _cd.CANCEL_SUSTAIN_S
DRIVE_ON_GAP_S = _cd.SPEED_GAP_S
#: The mic router's silent fallback source (src/audio/mic_router.py
#: NULL_MIC_NAME): an SCO uplink fed only by it is silence for the
#: dispatcher. (A string, not an import: the audio stack is not needed here.)
NULL_MIC_NAME = "bcm_null_mic"
#: ``uplink`` of a call (path A): not known yet / a real uplink / none.
UPLINK_STATES = ("unknown", "ok", "missing")
#: ``audio.call_route`` limits (node names, peer list).
ROUTE_NAME_MAX = 128
ROUTE_PEERS_MAX = 16
#: One dial per this long (the route answers 429); the one fallback after
#: a failed attempt is exempt.
ATTEMPT_MIN_INTERVAL_S = 60.0
TICK_S = 1.0
IDLE_WAIT_S = 30.0
QUEUE_MAX = 32
VEHICLE_LIMITS = {"label": 32, "colour": 20, "plate": 12}
DEFAULT_VEHICLE_LABEL = "Alfa Romeo 156"

EVENT_ID_RE = re.compile(r"^[0-9a-f]{8,32}$")
#: crash.detected sources, and "test": a window opened by
#: :meth:`Call112.open_test_window` (test mode only — no crash, no SMS).
SOURCES = ("accel", "gps", "test")
_PLATE_RE = re.compile(r"^[A-Za-z0-9 -]{1,12}$")
#: Agent call states → ours (the car phone cannot tell ringing from talking:
#: OFFHOOK is both; "placed" = ``am start`` went through).
AGENT_TO_STATE = {"queued": "dialing", "placed": "ringing", "offhook": "active",
                  "ended": "ended", "failed": "failed"}
#: The agent's call errors we pass on.
AGENT_ERRORS = ("su_missing", "su_denied", "am_failed", "no_call")
#: Agent refusals of POST /v1/call112 (final — retrying does not help).
AGENT_REFUSALS = ("call112_off", "mode_mismatch", "no_test_number", "no_root", "busy",
                  "rate_limited", "bad_request")
#: Path-B refusals after which the MAIN phone is NOT offered at once (the
#: one fallback): the car phone may well be calling 112 right now —
#: ``busy`` (it is in a call; with a call view in the answer that call is
#: adopted and followed instead), ``rate_limited`` (it placed one < 60 s
#: ago). The same for ``no_phone`` after the look-up (the answer was lost,
#: the call may be up). A second 112 from the main phone would only tie up
#: the dispatcher; after the 60 s limit the normal choice applies again.
#: Definitive refusals (su, am, mode, config, not delivered) still offer
#: the main phone at once.
NO_FALLBACK_REFUSALS = ("busy", "rate_limited")
#: Transport failures after which the request certainly did NOT reach the
#: agent (the same list crash_sms uses — see there).
NOT_DELIVERED = ("no_forward", "connect", "busy", "stopped", "no_secret", "unpaired",
                 "bad_auth", "stale_ts", "not_running")


# ── configuration ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Call112Config:
    """``safety.call112.*`` (validated) and ``safety.vehicle.*``."""
    paths: tuple = ("hfp", "car_phone")
    hold_ms: int = 2000
    arm_delay_ms: int = 700
    window_min: int = 30
    test_mode: bool = False
    test_number: str = ""
    vehicle: dict = field(default_factory=lambda: {"label": DEFAULT_VEHICLE_LABEL,
                                                   "colour": "", "plate": ""})


class _OnceLogger:
    """One warning per distinct text (the config is read on every pass)."""

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


class _Quiet:
    """For ``crash_detect.load_crash_config`` read here only for
    ``min_speed_kmh``: crash_detect itself warns about a bad value."""

    @staticmethod
    def warning(*_args: Any, **_kwargs: Any) -> None:
        return None


_QUIET = _Quiet()


def _clean_vehicle_text(value: Any, limit: int) -> str:
    """Printable, single line, at most ``limit`` characters ("" otherwise).
    The UI escapes it as well."""
    if not isinstance(value, str):
        return ""
    text = "".join(ch if ch.isprintable() else " " for ch in value)
    return " ".join(text.split())[:limit]


def load_config(config: Any, logger: Any = None) -> Call112Config:
    """Read and clamp ``safety.call112`` / ``safety.vehicle``. Test mode and
    the test number come from :func:`car_phone_agent.call112_settings` —
    the same reading the config push to the phone uses, so BCM and the
    phone can never disagree on what is dialled."""
    lg = logger or _CFG_LOG
    block = _cfg_get(config, "safety.call112", {})
    if not isinstance(block, dict):
        block = {}
    raw_paths = block.get("paths", list(PATHS))
    if not isinstance(raw_paths, (list, tuple)):
        lg.warning("safety.call112.paths=%r is not a list — using hfp, car_phone", raw_paths)
        raw_paths = list(PATHS)
    paths = []
    for p in raw_paths:
        if p in PATHS and p not in paths:
            paths.append(p)
        elif p not in PATHS:
            lg.warning("safety.call112.paths: unknown path %r ignored (hfp, car_phone)", p)
    if not paths:
        lg.warning("safety.call112.paths is empty — the window shows only the position "
                   "(\"Zadzwoń 112 ze swojego telefonu\")")
    hold = _number("safety.call112", block.get("hold_ms"), 2000, 1000, 5000, "hold_ms",
                   logger=lg)
    arm = _number("safety.call112", block.get("arm_delay_ms"), 700, 300, 3000,
                  "arm_delay_ms", logger=lg)
    window = _number("safety.call112", block.get("window_min"), 30, 5, 120, "window_min",
                     logger=lg)
    raw_mode = block.get("test_mode", False)
    if raw_mode is not True and raw_mode is not False:
        lg.warning("safety.call112.test_mode=%r is not true/false — TEST mode (112 is "
                   "never dialled)", raw_mode)
    test_mode, test_number = _cpa.call112_settings(config)
    raw_num = block.get("test_number", "")
    if raw_num not in ("", None) and not test_number:
        # The value itself is not logged (a personal phone number).
        lg.warning("safety.call112.test_number is not an E.164 number ('+', country code, "
                   "digits) — ignored")
    if test_mode and not test_number:
        lg.warning("safety.call112.test_mode is on without a test_number — the 112 button "
                   "cannot dial anything (set test_number in config/local.yaml)")
    veh = _cfg_get(config, "safety.vehicle", {})
    if not isinstance(veh, dict):
        veh = {}
    vehicle = {k: _clean_vehicle_text(veh.get(k), n) for k, n in VEHICLE_LIMITS.items()}
    if vehicle["plate"] and not _PLATE_RE.fullmatch(vehicle["plate"]):
        lg.warning("safety.vehicle.plate is not 1-12 letters/digits/spaces — not shown")
        vehicle["plate"] = ""
    vehicle["plate"] = vehicle["plate"].upper()
    if not vehicle["label"]:
        vehicle["label"] = DEFAULT_VEHICLE_LABEL
    return Call112Config(paths=tuple(paths), hold_ms=int(round(hold)),
                         arm_delay_ms=int(round(arm)), window_min=int(round(window)),
                         test_mode=test_mode, test_number=test_number, vehicle=vehicle)


def mask_number(num: str) -> str:
    """``+48601234567`` → ``+48...567`` (screen and log; the agent masks
    the same way)."""
    return f"{num[:3]}...{num[-3:]}" if isinstance(num, str) and len(num) > 6 else "..."


# ── path choice (pure) ─────────────────────────────────────────────────────

def hfp_reason(facts: Optional[dict], test_mode: bool, test_number: str) -> str:
    """Why path A (main phone, HFP) cannot be offered now ("" = it can).

    ``facts``: ``running`` (the Bluetooth manager exists), ``connected``,
    ``voice_modem``, ``call_state`` (oFono's real state, None unknown),
    ``bus_call_state`` (``bt.call_state``), ``registration``
    (``bt.phone_status``), ``mic`` (``audio.mic_state.state``)."""
    f = facts or {}
    if not f.get("running"):
        return "off"
    if test_mode and not test_number:
        return "no_number"
    if not f.get("connected"):
        return "not_connected"
    if not f.get("voice_modem"):
        return "no_modem"
    if f.get("registration") not in ("registered", "roaming"):
        return "no_network"
    if f.get("call_state") not in (None, "idle") or f.get("bus_call_state") not in (None, "idle"):
        return "call_in_progress"
    if f.get("mic") != "ok":
        return "no_mic"
    return ""


def car_phone_reason(facts: Optional[dict], test_mode: bool, test_number: str) -> str:
    """Why path B (car phone on speaker) cannot be offered now ("" = it can).

    ``facts``: ``running`` (car_phone_agent module), ``state``/``paired``
    (its published state), ``capable`` / ``mode`` (the last signed health
    answer: ``call112_capable``, ``call112_mode``)."""
    f = facts or {}
    if not f.get("running"):
        return "not_running"
    if test_mode and not test_number:
        return "no_number"
    if f.get("state") != "ok" or f.get("paired") is not True:
        return "not_ready"
    if f.get("capable") is not True:
        return "not_capable"
    if f.get("mode") != ("test" if test_mode else "real"):
        return "mode_mismatch"
    return ""


def choose_path(paths: tuple, test_mode: bool, test_number: str,
                hfp: Optional[dict], car_phone: Optional[dict],
                exclude: tuple = ()) -> tuple[str, dict[str, str]]:
    """``(path, reasons)``: the first allowed path (in ``paths`` order, not
    in ``exclude``) that can be offered now, or ``"none"``; ``reasons``
    says per path why not ("" = available; "off" = not allowed by
    ``safety.call112.paths``). Pure — the matrix is unit-tested."""
    reasons = {
        "hfp": hfp_reason(hfp, test_mode, test_number) if "hfp" in paths else "off",
        "car_phone": car_phone_reason(car_phone, test_mode, test_number)
        if "car_phone" in paths else "off",
    }
    for p in paths:
        if p in PATHS and p not in exclude and reasons[p] == "":
            return p, reasons
    return "none", reasons


def parse_detected(value: Any) -> Optional[dict[str, Any]]:
    """A ``crash.detected`` payload → the fields the window needs, or None.
    Any source (the button is manual)."""
    if not isinstance(value, dict):
        return None
    eid = value.get("event_id")
    if not isinstance(eid, str) or not EVENT_ID_RE.fullmatch(eid):
        return None

    def num(key: str, lo: float, hi: float) -> Optional[float]:
        v = value.get(key)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return None
        v = float(v)
        return v if math.isfinite(v) and lo <= v <= hi else None

    lat, lon = num("lat", -90.0, 90.0), num("lon", -180.0, 180.0)
    if lat is None or lon is None:
        lat = lon = None
    sats = value.get("sats")
    return {"id": eid, "ts": num("ts", 1e9, 4.1e9), "lat": lat, "lon": lon,
            "fix_age_s": num("fix_age_s", 0.0, 86400.0) if lat is not None else None,
            "sats": sats if isinstance(sats, int) and not isinstance(sats, bool)
            and 0 <= sats <= 255 else None,
            "heading": num("heading", 0.0, 360.0),
            "speed_kmh": num("speed_before_kmh", 0.0, 400.0),
            "source": value.get("source") if value.get("source") in SOURCES else ""}


def parse_position(value: Any) -> Optional[dict[str, Any]]:
    """``gps.position`` → ``{lat, lon, sats, heading}`` (a fix) or None."""
    if not isinstance(value, dict) or value.get("fix") is False:
        return None
    out = parse_detected({"event_id": "0" * 8, "lat": value.get("lat"),
                          "lon": value.get("lon"), "sats": value.get("satellites"),
                          "heading": value.get("heading"), "fix_age_s": 0})
    if out is None or out["lat"] is None:
        return None
    return {"lat": out["lat"], "lon": out["lon"], "sats": out["sats"],
            "heading": out["heading"]}


# ── the module ─────────────────────────────────────────────────────────────

class Call112:
    """The 112 button behind the crash window (see the module docstring).

    Args:
        config: BCMConfig or nested dict (read live).
        event_bus: EventBus.
        bt_manager: the BluetoothManager (path A) or None.
        agent_getter: returns the running ``CarPhoneAgent`` or None.
        clock / wall_clock: monotonic / epoch seconds (tests pass fakes).
        state_path: where the event is saved.
    """

    def __init__(self, config: Any, event_bus: Any, bt_manager: Any = None,
                 agent_getter: Optional[Callable[[], Any]] = None,
                 clock: Callable[[], float] = time.monotonic,
                 wall_clock: Callable[[], float] = time.time,
                 state_path: str = STATE_FILE) -> None:
        self._config = config
        self._bus = event_bus
        self._bt = bt_manager
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
        self._event: Optional[dict[str, Any]] = None
        self._call: Optional[dict[str, Any]] = None
        self._seq = 0
        self._last_attempt: Optional[float] = None
        # After a failed attempt: the ONE other path that may be dialled at
        # once (exempt from the 60 s limit), and whether it was used.
        self._fallback: str = ""
        self._pos: Optional[dict[str, Any]] = None
        self._pos_at: Optional[float] = None
        self._bt_state: str = "idle"
        self._incoming = False
        self._published: Optional[dict[str, Any]] = None
        self._saved: Optional[dict[str, Any]] = None
        self._save_failed = False
        # input.mute toggled by us for path B (undone only if still ours).
        self._muted_by_us = False
        # Driving on (gps.speed, see _on_speed): {eid, above_since, last_at}.
        self._drive: Optional[dict[str, Any]] = None
        self._min_speed = _cd.load_crash_config(config, _QUIET).min_speed_kmh
        # crash.sms_state "cancelled" already queued for this event id.
        self._sms_cancel_seen: Optional[str] = None
        # The highest call seq the agent showed us in this run: a call
        # looked up without its own seq must be newer (AGENT_TS_MARGIN_S).
        self._agent_seq_hi: Optional[int] = None
        cfg = load_config(config)
        log.info("112 button ready (paths %s, hold %d ms, window %d min%s)",
                 ",".join(cfg.paths) or "-", cfg.hold_ms, cfg.window_min,
                 f", TEST -> {mask_number(cfg.test_number)}" if cfg.test_mode
                 and cfg.test_number else ", TEST without a number" if cfg.test_mode else "")

    # ── lifecycle ─────────────────────────────────────────────────────────

    def _subscriptions(self) -> tuple:
        return ((TOPIC_DETECTED, self._on_detected),
                (TOPIC_OUTCOME, self._on_outcome),
                ("gps.position", self._on_position),
                ("gps.speed", self._on_speed),
                (TOPIC_SMS_STATE, self._on_sms_state),
                ("bt.dial_result", self._on_dial_result),
                ("bt.call_state", self._on_bt_call_state),
                ("audio.call_route", self._on_call_route),
                ("power.shutting_down", self._on_shutdown))

    def subscribe(self) -> None:
        if self._subscribed:
            return
        self._subscribed = True
        for topic, cb in self._subscriptions():
            self._bus.subscribe(topic, cb)

    def start(self) -> None:
        """Subscribe and start the worker; no I/O here."""
        self.subscribe()
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, daemon=True, name="call112")
            self._thread.start()

    def stop(self) -> None:
        """Never waits for a request in progress."""
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
                log.exception("112: worker pass failed")
                wait = TICK_S
            try:
                cmd = self._q.get(timeout=max(0.05, min(wait, IDLE_WAIT_S)))
            except queue.Empty:
                continue
            self._handle_safe(cmd)

    def run_once(self) -> float:
        """Everything queued, then one :meth:`step`. Returns the sleep."""
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
            log.exception("112: command %r failed", cmd[0] if cmd else cmd)

    def _enqueue(self, item: Any) -> bool:
        try:
            self._q.put_nowait(item)
            return True
        except queue.Full:
            log.warning("112: command queue full — %r dropped",
                        item[0] if isinstance(item, tuple) else item)
            return False

    # ── bus callbacks (dispatcher thread: validate + enqueue only) ─────────

    def _on_detected(self, topic: str, value: Any, timestamp: float) -> None:
        parsed = parse_detected(value)
        if parsed is None:
            log.warning("112: malformed crash.detected ignored")
            return
        self._enqueue(("detected", parsed, self._clock()))

    def _on_outcome(self, topic: str, value: Any, timestamp: float) -> None:
        """``cancelled`` = the car drove on before it ever stopped (crash_detect
        says it only then — after ``stopped`` see :meth:`_on_speed`)."""
        if not isinstance(value, dict) or value.get("outcome") != "cancelled":
            return
        eid = value.get("event_id")
        if isinstance(eid, str) and EVENT_ID_RE.fullmatch(eid):
            self._enqueue(("outcome", eid))

    def _on_position(self, topic: str, value: Any, timestamp: float) -> None:
        pos = parse_position(value)
        if pos is None:
            return
        with self._lock:
            self._pos = pos
            self._pos_at = self._clock()

    def _on_speed(self, topic: str, value: Any, timestamp: float) -> None:
        """``gps.speed`` (km/h, only published when known): the "drove on"
        tracker of the open window — crash_detect's rule (above
        ``min_speed_kmh``, no gap over :data:`DRIVE_ON_GAP_S`); :meth:`step`
        closes the window once it held for :data:`DRIVE_ON_SUSTAIN_S`.
        Validates and records only (dispatcher thread)."""
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return
        speed = float(value)
        if not math.isfinite(speed) or not 0.0 <= speed <= _cd.MAX_SPEED_KMH:
            return
        now = self._clock()
        with self._lock:
            ev = self._event
            if ev is None or ev["dismissed"]:
                return
            d = self._drive
            if d is None or d["eid"] != ev["id"]:
                d = self._drive = {"eid": ev["id"], "above_since": None, "last_at": None}
            last = d["last_at"]
            gap_ok = last is not None and 0.0 <= now - last <= DRIVE_ON_GAP_S
            if speed > self._min_speed:
                if d["above_since"] is None or not gap_ok:
                    d["above_since"] = now
            else:
                d["above_since"] = None
            d["last_at"] = now

    def _on_sms_state(self, topic: str, value: Any, timestamp: float) -> None:
        """``crash.sms_state``: the crash SMS of an event was cancelled and its
        result view is gone (``modal`` false) — queued once per event; the
        worker closes the window only if nothing was dialled for it."""
        if not isinstance(value, dict) or value.get("state") != "cancelled" \
                or value.get("modal") is not False:
            return
        eid = value.get("event_id")
        if not isinstance(eid, str) or not EVENT_ID_RE.fullmatch(eid):
            return
        with self._lock:
            if self._sms_cancel_seen == eid:
                return
            self._sms_cancel_seen = eid
        self._enqueue(("sms_cancelled", eid))

    def _on_call_route(self, topic: str, value: Any, timestamp: float) -> None:
        """``audio.call_route`` (pipewire_ctrl, once per HFP call a few
        seconds after "active"): is there a real uplink to the dispatcher?
        Missing = no uplink node, no peers, or only the mic router's silent
        source. Validates (sizes, types) and enqueues only."""
        if not isinstance(value, dict):
            return
        uplink = value.get("uplink", "")
        peers = value.get("uplink_peers", [])
        if not isinstance(uplink, str) or len(uplink) > ROUTE_NAME_MAX \
                or not isinstance(peers, list) or len(peers) > ROUTE_PEERS_MAX \
                or not all(isinstance(p, str) and len(p) <= ROUTE_NAME_MAX for p in peers):
            log.debug("112: malformed audio.call_route ignored")
            return
        missing = not uplink or not peers or all(p == NULL_MIC_NAME for p in peers)
        self._enqueue(("route", missing))

    def _on_dial_result(self, topic: str, value: Any, timestamp: float) -> None:
        if isinstance(value, dict) and value.get("origin") == "call112":
            self._enqueue(("dial_result", dict(value)))

    def _on_bt_call_state(self, topic: str, value: Any, timestamp: float) -> None:
        if value in ("idle", "incoming", "ringing", "active"):
            self._enqueue(("bt_state", value))

    # ── API for the web routes (any thread; no I/O) ────────────────────────

    def _window_open_locked(self, now: float, cfg: Call112Config) -> bool:
        ev = self._event
        if ev is None or ev["dismissed"]:
            return False
        if self._call is not None and self._call["state"] in LIVE:
            return True
        return now - ev["at_mono"] <= cfg.window_min * 60.0

    def request_call(self, source: str = "ui") -> dict:
        """The driver held the 112 button (loopback-only route). Chooses the
        path now (no I/O), queues the dial for the worker. Never takes a
        number. Returns ``{ok, error, path, retry_after}``; errors:
        stopped, no_window, busy, rate_limited, no_path."""
        if self._stop.is_set():
            return {"ok": False, "error": "stopped", "path": "", "retry_after": 0}
        cfg = load_config(self._config)
        hfp, car = self._facts()
        now, wall = self._clock(), self._wall()
        with self._lock:
            if not self._window_open_locked(now, cfg):
                return {"ok": False, "error": "no_window", "path": "", "retry_after": 0}
            call = self._call
            if call is not None and call["state"] in LIVE and not (
                    self._uplink_lost_locked(call) and self._fallback):
                return {"ok": False, "error": "busy", "path": call["path"], "retry_after": 0}
            path, _reasons, fallback, wait = self._offer_locked(now, cfg, hfp, car)
            if wait:
                return {"ok": False, "error": "rate_limited", "path": path,
                        "retry_after": wait}
            if path == "none":
                return {"ok": False, "error": "no_path", "path": "none", "retry_after": 0}
            if call is not None and call["state"] in LIVE and not fallback:
                # Only the car phone may join a live HFP call without uplink.
                return {"ok": False, "error": "busy", "path": call["path"], "retry_after": 0}
            prev = call if fallback else None
            self._seq += 1
            number = cfg.test_number if cfg.test_mode else EMERGENCY_NUMBER
            self._call = {
                "seq": self._seq, "path": path, "state": "dialing", "error": "",
                "test": cfg.test_mode, "number": number,
                "started_ts": wall, "started_mono": now, "active_ts": None,
                "active_mono": None, "ended_ts": None, "ended_mono": None,
                "unverified": False, "unverified_mono": None,
                "hangup_pending": False, "hangup_mono": None, "hangup_end_mono": None,
                "agent_seq": None, "seq_floor": self._agent_seq_hi,
                "verify_until": None, "next_poll": now, "poll_fails": 0, "forgotten": 0,
                "dial_answered": False, "marked": False, "reached": False,
                "reached_ts": None, "uplink": "unknown", "uplink_logged": False,
                "event_id": self._event["id"] if self._event is not None else "",
                # A fallback attempt gets no fallback of its own (one only).
                "after": prev["path"] if prev is not None else "",
                # An HFP call that may still be up (oFono never confirmed it,
                # or it is up without an uplink): ended before B dials.
                "prev_unconfirmed": bool(
                    prev is not None and prev["path"] == "hfp"
                    and (prev["error"] in ("timeout", "unknown")
                         or (prev["uplink"] == "missing" and prev["state"] in LIVE))),
            }
            self._last_attempt = now
            self._fallback = ""
            seq = self._seq
        log.critical("112 button HELD (%s) — dialling %s via %s", source,
                     f"TEST {mask_number(number)}" if cfg.test_mode else "112",
                     "the main phone (HFP)" if path == "hfp" else "the car phone (speaker)")
        if not self._enqueue(("dial", seq)):
            with self._lock:
                if self._call is not None and self._call["seq"] == seq:
                    self._fail_locked(self._call, "busy", self._clock(), self._wall(),
                                      offer=False)
            return {"ok": False, "error": "busy", "path": path, "retry_after": 0}
        self._publish()
        return {"ok": True, "error": "", "path": path, "retry_after": 0}

    def _offer_locked(self, now: float, cfg: Call112Config, hfp: dict,
                      car: dict) -> tuple[str, dict, bool, int]:
        """``(path, reasons, fallback, retry_after)`` — what the button does
        if pressed now. Within :data:`ATTEMPT_MIN_INTERVAL_S` of the last
        attempt only the ONE fallback after a failed attempt (the other
        path) may be dialled; otherwise ``retry_after`` > 0."""
        call = self._call
        limited = self._last_attempt is not None \
            and 0 <= now - self._last_attempt < ATTEMPT_MIN_INTERVAL_S
        # An HFP call without uplink: the car phone stays THE offer (also
        # after the 60 s and after that call ended) — never path A again
        # with the same broken audio.
        uplink_lost = self._uplink_lost_locked(call)
        if self._fallback and call is not None and (limited or uplink_lost):
            path, reasons = choose_path(cfg.paths, cfg.test_mode, cfg.test_number, hfp, car,
                                        exclude=(call["path"],))
            if path == self._fallback:
                return path, reasons, True, 0
            if uplink_lost and not limited:
                return path, reasons, False, 0
        else:
            path, reasons = choose_path(cfg.paths, cfg.test_mode, cfg.test_number, hfp, car)
        wait = max(1, int(math.ceil(ATTEMPT_MIN_INTERVAL_S - (now - self._last_attempt)))) \
            if limited else 0
        return path, reasons, False, wait

    @staticmethod
    def _uplink_lost_locked(call: Optional[dict]) -> bool:
        """An HFP 112 call (live or over) whose SCO uplink was missing."""
        return call is not None and call["path"] == "hfp" and call["uplink"] == "missing"

    def request_hangup(self) -> dict:
        """"Rozłącz" (held 1 s in the window). ``{ok, error}``; errors:
        stopped, no_call, busy. While a hang-up is pending a second hold is
        a no-op — until :data:`HANGUP_CONFIRM_S` showed it did not take
        (:meth:`step` clears ``hangup_pending``), then it is sent again."""
        if self._stop.is_set():
            return {"ok": False, "error": "stopped"}
        with self._lock:
            call = self._call
            if call is None or call["state"] not in LIVE:
                return {"ok": False, "error": "no_call"}
            if call["hangup_pending"]:
                return {"ok": True, "error": ""}
            call["hangup_pending"] = True
            call["hangup_mono"] = None
            seq = call["seq"]
        if not self._enqueue(("hangup", seq)):
            with self._lock:
                call["hangup_pending"] = False
            return {"ok": False, "error": "busy"}
        self._publish()
        return {"ok": True, "error": ""}

    def dismiss(self, event_id: str) -> dict:
        """"Zamknij" — close the window of ``event_id`` (not during a live
        call). Saved: the window does not come back after a restart."""
        if not isinstance(event_id, str) or not EVENT_ID_RE.fullmatch(event_id):
            return {"ok": False, "error": "bad_request"}
        with self._lock:
            ev = self._event
            if ev is None or ev["id"] != event_id:
                return {"ok": False, "error": "unknown_event"}
            if self._call is not None and self._call["state"] in LIVE:
                return {"ok": False, "error": "busy"}
            ev["dismissed"] = True
        self._enqueue(("save",))
        self._publish()
        return {"ok": True, "error": ""}

    def open_test_window(self) -> dict:
        """Bench test (``POST /api/crash/call112/test``, loopback only): open
        the window without a crash — ONLY in test mode with a test number,
        so the only thing it can ever dial is that number. Nothing is
        published on ``crash.detected`` (no SMS, no DVR, no record).
        Errors: stopped, not_test_mode, no_test_number, busy."""
        if self._stop.is_set():
            return {"ok": False, "error": "stopped"}
        cfg = load_config(self._config)
        if not cfg.test_mode:
            return {"ok": False, "error": "not_test_mode"}
        if not cfg.test_number:
            return {"ok": False, "error": "no_test_number"}
        with self._lock:
            if self._call is not None and self._call["state"] in LIVE:
                return {"ok": False, "error": "busy"}
            pos = dict(self._pos) if self._pos is not None else None
            age = None if self._pos_at is None else max(0.0, self._clock() - self._pos_at)
        det = {"id": uuid.uuid4().hex, "ts": self._wall(), "source": "test",
               "lat": pos["lat"] if pos else None, "lon": pos["lon"] if pos else None,
               "fix_age_s": age if pos else None, "sats": pos["sats"] if pos else None,
               "heading": pos["heading"] if pos else None, "speed_kmh": None}
        log.warning("112: TEST window opened (calls go only to %s)", mask_number(cfg.test_number))
        if not self._enqueue(("detected", det, self._clock())):
            return {"ok": False, "error": "busy"}
        return {"ok": True, "error": "", "event_id": det["id"]}

    @property
    def state(self) -> Optional[dict[str, Any]]:
        """The last published ``crash.call112_state`` (a copy), or None."""
        with self._lock:
            return None if self._published is None else json.loads(json.dumps(self._published))

    # ── facts for the path choice (no I/O) ────────────────────────────────

    def _last(self, topic: str) -> Any:
        try:
            got = self._bus.get_last(topic)
        except Exception:
            return None
        return got[0] if isinstance(got, tuple) and got else None

    def _facts(self) -> tuple[dict, dict]:
        hfp: dict[str, Any] = {"running": self._bt is not None}
        if self._bt is not None:
            try:
                hfp.update(self._bt.call112_facts())
            except Exception:
                log.debug("call112_facts() failed", exc_info=True)
                hfp["running"] = False
            status = self._last("bt.phone_status")
            hfp["registration"] = status.get("registration") if isinstance(status, dict) \
                else None
            mic = self._last("audio.mic_state")
            hfp["mic"] = mic.get("state") if isinstance(mic, dict) else None
            hfp["bus_call_state"] = self._last("bt.call_state")
        car: dict[str, Any] = {"running": False}
        agent = self._agent()
        if agent is not None:
            try:
                st = agent.state or {}
                facts = agent.health_facts() or {}
            except Exception:
                st, facts = {}, {}
            car = {"running": True, "state": st.get("state"), "paired": st.get("paired"),
                   "capable": facts.get("call112_capable"),
                   "mode": facts.get("call112_mode")}
        return hfp, car

    def _agent(self) -> Any:
        try:
            return self._agent_getter()
        except Exception:
            return None

    # ── commands (worker thread) ───────────────────────────────────────────

    def handle(self, cmd: tuple) -> None:
        kind = cmd[0]
        if kind == "detected":
            self._new_event(cmd[1], cmd[2])
        elif kind == "outcome":
            self._outcome(cmd[1])
        elif kind == "dial":
            self._dial(cmd[1])
        elif kind == "hangup":
            self._hangup(cmd[1])
        elif kind == "dial_result":
            self._dial_result(cmd[1])
        elif kind == "bt_state":
            self._bt_call_state(cmd[1])
        elif kind == "route":
            self._call_route(cmd[1])
        elif kind == "sms_cancelled":
            self._sms_cancelled(cmd[1])
        elif kind == "save":
            self._save()
        self._publish()

    def _new_event(self, det: dict, detected_at: float) -> None:
        now, wall = self._clock(), self._wall()
        with self._lock:
            cur = self._event
            if cur is not None and cur["id"] == det["id"]:
                return
            if self._call is not None and self._call["state"] in LIVE:
                # A new event during a 112 call: the call stays on screen;
                # the window simply follows the newest event afterwards.
                log.warning("112: event %s during a live 112 call", det["id"])
            fix_at = None
            if det["fix_age_s"] is not None:
                fix_at = min(detected_at, now) - det["fix_age_s"]
            self._event = dict(det, at_mono=min(detected_at, now), fix_mono=fix_at,
                               ts=det["ts"] if det["ts"] is not None else wall,
                               dismissed=False)
            self._drive = None
            if self._call is not None and self._call["state"] not in LIVE:
                self._call = None
                self._fallback = ""
        log.warning("112: crash window for event %s (%s) — the 112 button is available for "
                    "%d min", det["id"], det["source"] or "?", load_config(self._config).window_min)
        self._save()

    def _outcome(self, eid: str) -> None:
        self._close_window(eid, "the car drove on")

    def _sms_cancelled(self, eid: str) -> None:
        """The crash SMS of ``eid`` was cancelled ("nic się nie stało") and
        its result view is gone: close the window too — only if nothing was
        dialled for this event (after a call the panel and "Odbierz" stay)."""
        with self._lock:
            if self._call is not None:
                return
        self._close_window(eid, "the crash SMS was cancelled")

    def _close_window(self, eid: str, why: str) -> bool:
        """Dismiss the window of ``eid`` (not during a live call) and save."""
        with self._lock:
            ev = self._event
            if ev is None or ev["id"] != eid or ev["dismissed"]:
                return False
            if self._call is not None and self._call["state"] in LIVE:
                return False
            ev["dismissed"] = True
        log.info("112: %s — window of %s closed", why, eid)
        self._save()
        return True

    def _current(self, seq: int) -> Optional[dict]:
        call = self._call
        return call if call is not None and call["seq"] == seq else None

    def _dial(self, seq: int) -> None:
        with self._lock:
            call = self._current(seq)
            if call is None or call["state"] != "dialing":
                return
            path, number, test = call["path"], call["number"], call["test"]
            hang_first = call["prev_unconfirmed"]
            event_id = call["event_id"]
        if path == "hfp":
            ok = False
            try:
                ok = bool(self._bt is not None and self._bt.dial_call112(number))
            except Exception:
                log.exception("112: HFP dial failed")
            if not ok:
                with self._lock:
                    call = self._current(seq)
                    if call is not None and call["state"] == "dialing" \
                            and not call["dial_answered"]:
                        self._fail_locked(call, "dbus", self._clock(), self._wall())
            return
        # Path B. A path-A call that oFono never confirmed may still be
        # going out: end it first, so 112 is not called twice.
        if hang_first and self._bt is not None:
            try:
                self._bt.hangup_call112()
            except Exception:
                log.exception("112: hanging up the unconfirmed HFP call failed")
        agent = self._agent()
        if agent is None:
            with self._lock:
                call = self._current(seq)
                if call is not None:
                    self._fail_locked(call, "not_running", self._clock(), self._wall())
            return
        res = agent.call112("test" if test else "real", event_id)
        now, wall = self._clock(), self._wall()
        err = res.get("error") or ""
        with self._lock:
            call = self._current(seq)
            if call is None:
                return
            busy_view = _cpa.parse_call112_view(res.get("data")) \
                if res.get("status") == 409 and err == "busy" else None
            if res.get("ok") or (busy_view is not None and busy_view["state"] in
                                 ("queued", "placed", "offhook")):
                # 200, or 409 "busy" with the call the phone IS in (e.g. one
                # requested before a BCM restart): follow that call.
                view = busy_view or _cpa.parse_call112_view(res.get("data"))
                if view is not None:
                    self._own_seq_locked(call, view["seq"])
                    self._adopt_locked(call, view, now, wall)
                if busy_view is not None:
                    log.warning("112: the car phone is already in a 112 call — following it")
                call["next_poll"] = now + POLL_LIVE_S
                mute = True
            elif res.get("status") in (400, 409, 429) and err in AGENT_REFUSALS:
                # The agent answered and refused (signed): nothing dialled by
                # this request. busy / rate_limited: the phone may still be in
                # (or just made) a call — no immediate main-phone fallback.
                self._fail_locked(call, err if err in ERRORS else "refused", now, wall,
                                  offer=err not in NO_FALLBACK_REFUSALS)
                mute = False
            elif err in NOT_DELIVERED:
                self._fail_locked(call, "no_phone", now, wall)
                mute = False
            elif err == "bad_request" and res.get("status") is None:
                # Refused by the client before sending (never reached the phone).
                self._fail_locked(call, "refused", now, wall)
                mute = False
            else:
                # Timeout / dropped / a broken answer: the phone may be
                # dialling — look it up before saying anything.
                call["verify_until"] = now + AGENT_VERIFY_S
                call["next_poll"] = now + POLL_LIVE_S
                mute = True
                log.warning("112: no clear answer from the car phone (%s) — looking the call "
                            "up", err or "?")
        if mute:
            self._mute(True)

    def _hangup(self, seq: int) -> None:
        with self._lock:
            call = self._current(seq)
            if call is None or call["state"] not in LIVE:
                return
            path = call["path"]
        log.warning("112: hang-up held in the window (%s)", path)
        if path == "hfp":
            try:
                if self._bt is not None:
                    self._bt.hangup_call112()
            except Exception:
                log.exception("112: HFP hang-up failed")
            with self._lock:
                call = self._current(seq)
                if call is not None and call["hangup_pending"]:
                    call["hangup_mono"] = self._clock()
            return
        agent = self._agent()
        res = agent.call112_hangup() if agent is not None else {"ok": False}
        now, wall = self._clock(), self._wall()
        with self._lock:
            call = self._current(seq)
            if call is None:
                return
            if res.get("ok"):
                if call["hangup_pending"]:
                    call["hangup_mono"] = now
            elif res.get("status") == 409 and res.get("error") == "no_call":
                # A signed "no call": the phone follows no 112 call (it
                # restarted, or the call is over) — BCM can neither see nor
                # end it from here. Ours ends (unverified), so nothing stays
                # blocked for an hour.
                self._unverified_locked(call, now)
                if call["state"] in LIVE:
                    self._end_locked(call, now, wall)
                log.warning("112: the car phone follows no call — ended here (unverified)")
            else:
                log.warning("112: the car phone did not take the hang-up (%s)",
                            res.get("error") or "no agent")
                call["hangup_pending"] = False
                call["hangup_mono"] = None
            call["next_poll"] = now

    def _dial_result(self, value: dict) -> None:
        ok = value.get("ok")
        error = value.get("error")
        now, wall = self._clock(), self._wall()
        mark = False
        eid = ""
        with self._lock:
            call = self._call
            if call is None or call["path"] != "hfp":
                return
            if ok is True:
                call["dial_answered"] = True
                if call["hangup_pending"] or call["state"] == "ended":
                    # "Rozłącz" was held before oFono answered: the hang-up
                    # queued behind the dial ends it — nothing to revive.
                    pass
                elif call["state"] == "dialing" or (call["state"] == "failed"
                                                    and call["error"] in ("timeout", "unknown")):
                    # Also late: the call went out after all — withdraw the
                    # fallback offer.
                    self._revive_locked(call, "ringing", now, wall)
                    log.warning("112: the main phone is dialling 112 (oFono accepted it)")
                    mark = not call["test"] and not call["marked"]
                    call["marked"] = call["marked"] or mark
                    eid = call["event_id"]
            elif ok is None:
                call["dial_answered"] = True     # "unknown": the timer decides
            elif call["state"] == "dialing":
                self._fail_locked(call, error if error in ERRORS and error else "dbus",
                                  now, wall)
            elif call["state"] == "failed" and call["error"] == "dbus" \
                    and not call["dial_answered"] and error in ERRORS and error:
                # dial_call112() said False (busy / invalid / not queued) and
                # _dial() already failed it: the real reason, for the screen.
                call["error"] = error
        if mark:
            self._mark_agent(eid)

    def _bt_call_state(self, state: str) -> None:
        now, wall = self._clock(), self._wall()
        mark = False
        with self._lock:
            prev = self._bt_state
            self._bt_state = state
            self._incoming = state == "incoming"
            call = self._call
            if call is None or call["path"] != "hfp":
                return
            if state == "active":
                if call["state"] in ("dialing", "ringing") or (
                        call["state"] == "failed" and call["error"] in ("timeout", "unknown")):
                    self._revive_locked(call, "active", now, wall)
                    call["active_ts"], call["active_mono"] = wall, now
                    log.warning("112: call active (main phone)")
                    mark = not call["test"] and not call["marked"]
                    call["marked"] = call["marked"] or mark
                elif call["state"] == "ended" and call["hangup_end_mono"] is not None \
                        and prev != "incoming" \
                        and 0 <= now - call["hangup_end_mono"] <= HFP_HANGUP_REVIVE_S:
                    # Our hang-up ended it only optimistically: HangupAll did
                    # not take and oFono still has the call — live again, and
                    # "Rozłącz" works again (duration kept).
                    call["state"] = "active"
                    call["ended_ts"] = call["ended_mono"] = None
                    call["hangup_end_mono"] = None
                    if call["active_mono"] is None:
                        call["active_ts"], call["active_mono"] = wall, now
                    log.warning("112: the main phone is still in the call after the hang-up — "
                                "Rozłącz can be held again")
            elif state == "idle" and (prev != "idle" or call["hangup_pending"]):
                by_hangup = call["hangup_pending"]
                if call["state"] in ("ringing", "active") or (
                        call["state"] == "dialing" and call["hangup_pending"]):
                    self._end_locked(call, now, wall)
                    if by_hangup:
                        call["hangup_end_mono"] = now
                elif call["state"] == "dialing" and call["dial_answered"]:
                    # oFono gave no answer in time and now says: no call.
                    self._fail_locked(call, "no_call", now, wall)
            eid = call["event_id"]
        if mark:
            self._mark_agent(eid)

    def _call_route(self, missing: bool) -> None:
        """``audio.call_route`` of a live HFP 112 call (pipewire_ctrl publishes
        it only after "active", once per call): no uplink = the dispatcher
        may hear nothing — the window says so and offers the car phone at
        once (exempt from the 60 s limit; B hangs this call up first)."""
        cfg = load_config(self._config)
        with self._lock:
            call = self._call
            if call is None or call["path"] != "hfp" or call["state"] not in ("ringing",
                                                                                 "active"):
                return
            call["uplink"] = "missing" if missing else "ok"
            if not missing:
                return
            if "car_phone" in cfg.paths and not call["after"]:
                self._fallback = "car_phone"
            if not call["uplink_logged"]:
                call["uplink_logged"] = True
                log.error("112: the main phone's call has NO microphone uplink (SCO) — the "
                          "dispatcher may hear nothing%s",
                          "; the car phone is offered" if self._fallback else "")

    def _mark_agent(self, event_id: str) -> None:
        """Real 112 went out over HFP: the car phone's crash SMS of THIS event
        says so (the phone flags nothing if it does not hold the event)."""
        agent = self._agent()
        if agent is None or not EVENT_ID_RE.fullmatch(event_id or ""):
            return
        try:
            res = agent.call112_mark(event_id)
        except Exception:
            log.debug("call112_mark failed", exc_info=True)
            return
        if not res.get("ok"):
            log.info("112: the car phone did not take the 'called 112' note (%s)",
                     res.get("error") or "?")

    # ── state transitions (under the lock) ────────────────────────────────

    def _revive_locked(self, call: dict, state: str, now: float, wall: float) -> None:
        call["state"] = state
        self._reached_locked(call, wall)
        call["error"] = ""
        call["ended_ts"] = call["ended_mono"] = None
        if self._fallback and not self._uplink_lost_locked(call):
            self._fallback = ""

    @staticmethod
    def _reached_locked(call: dict, wall: float) -> None:
        if not call["reached"]:
            call["reached"] = True
            call["reached_ts"] = wall

    def _own_seq_locked(self, call: dict, seq: int) -> None:
        """The agent's call seq of ``call`` (and the run's highest seen)."""
        call["agent_seq"] = seq
        if self._agent_seq_hi is None or seq > self._agent_seq_hi:
            self._agent_seq_hi = seq

    def _fail_locked(self, call: dict, error: str, now: float, wall: float,
                     offer: bool = True) -> None:
        call["state"] = "failed"
        call["error"] = error if error in ERRORS else "refused"
        call["ended_ts"], call["ended_mono"] = wall, now
        call["hangup_pending"] = False
        call["hangup_mono"] = None
        other = "car_phone" if call["path"] == "hfp" else "hfp"
        cfg = load_config(self._config)
        self._fallback = other if offer and other in cfg.paths and not call["after"] else ""
        log.error("112: call via %s FAILED (%s)%s", call["path"], call["error"],
                  f" — {other} offered" if self._fallback else "")

    def _end_locked(self, call: dict, now: float, wall: float) -> None:
        call["state"] = "ended"
        call["ended_ts"], call["ended_mono"] = wall, now
        call["hangup_pending"] = False
        call["hangup_mono"] = None
        log.warning("112: call ended (%s%s)", call["path"],
                    ", unverified" if call["unverified"] else "")

    @staticmethod
    def _unverified_locked(call: dict, now: float) -> None:
        """The call's state can no longer be seen: from now on it is
        followed for at most :data:`UNVERIFIED_FOLLOW_MAX_S`."""
        if not call["unverified"]:
            call["unverified"] = True
            call["unverified_mono"] = now

    def _adopt_locked(self, call: dict, view: dict, now: float, wall: float) -> None:
        """The agent's call view → our call (path B)."""
        state = AGENT_TO_STATE.get(view["state"], "dialing")
        call["verify_until"] = None
        call["poll_fails"] = 0
        call["forgotten"] = 0
        if view["state"] == "placed" and view["final"]:
            # Placed, but its state is not readable on this ROM (the agent
            # gave up after 2 min). "Rozłącz" still works (KEYCODE_ENDCALL).
            state = "active"
            self._unverified_locked(call, now)
        if state == "failed":
            if call["state"] != "failed":
                err = view["error"] if view["error"] in AGENT_ERRORS else "refused"
                self._fail_locked(call, err, now, wall)
            return
        if state == "ended":
            if call["state"] != "ended":
                self._end_locked(call, now, wall)
            return
        if state in ("ringing", "active"):
            self._reached_locked(call, wall)
        if state == "active" and call["state"] != "active":
            ts = view.get("offhook_ts") or view.get("placed_ts")
            call["active_ts"] = float(ts) if ts else wall
            call["active_mono"] = now - max(0.0, wall - call["active_ts"])
        call["state"] = state

    # ── the periodic step (worker) ─────────────────────────────────────────

    def step(self) -> float:
        now, wall = self._clock(), self._wall()
        cfg = load_config(self._config)
        min_speed = _cd.load_crash_config(self._config, _QUIET).min_speed_kmh
        poll = False
        with self._lock:
            self._min_speed = min_speed
            call = self._call
            if call is not None and call["state"] in LIVE:
                if call["path"] == "hfp" and call["state"] == "dialing" \
                        and now - call["started_mono"] >= HFP_CONFIRM_S:
                    self._fail_locked(call, "timeout" if not call["dial_answered"]
                                      else "unknown", now, wall)
                elif call["path"] == "car_phone":
                    if call["verify_until"] is not None and now >= call["verify_until"]:
                        # The answer was lost and the call is nowhere to be
                        # seen — it may still be up: no main-phone fallback
                        # at once (NO_FALLBACK_REFUSALS).
                        self._fail_locked(call, "no_phone", now, wall, offer=False)
                    elif now >= call["next_poll"]:
                        poll = True
                if call["state"] in LIVE and call["hangup_pending"] \
                        and call["hangup_mono"] is not None \
                        and now - call["hangup_mono"] >= HANGUP_CONFIRM_S:
                    call["hangup_pending"] = False
                    call["hangup_mono"] = None
                    log.warning("112: the %s is still in the call %d s after the hang-up — "
                                "Rozłącz can be held again", "car phone" if call["path"]
                                == "car_phone" else "main phone", int(HANGUP_CONFIRM_S))
                if call["state"] in LIVE and call["unverified"] \
                        and call["unverified_mono"] is not None \
                        and now - call["unverified_mono"] >= UNVERIFIED_FOLLOW_MAX_S:
                    log.warning("112: the call's state has not been visible for %d min — no "
                                "longer followed (the window can be closed)",
                                int(UNVERIFIED_FOLLOW_MAX_S // 60))
                    self._end_locked(call, now, wall)
                if call["state"] in LIVE and now - call["started_mono"] >= CALL_FOLLOW_MAX_S:
                    self._end_locked(call, now, wall)
            seq = call["seq"] if call is not None else None
            live = call is not None and call["state"] in LIVE
            drove_on = self._drove_on_locked(now) and not live
            eid = self._event["id"] if self._event is not None else ""
            open_ = self._window_open_locked(now, cfg)
            unmute = self._muted_by_us and not live
        if poll and seq is not None:
            self._poll_agent(seq)
        if unmute:
            self._mute(False)
        if drove_on and self._close_window(eid, "the car drove on"):
            open_ = False
        self._publish()
        if open_:
            return TICK_S
        return IDLE_WAIT_S

    def _drove_on_locked(self, now: float) -> bool:
        """The open window's car drove on: above ``min_speed_kmh`` for
        :data:`DRIVE_ON_SUSTAIN_S`, the last sample still fresh."""
        ev, d = self._event, self._drive
        return (ev is not None and not ev["dismissed"] and d is not None
                and d["eid"] == ev["id"] and d["above_since"] is not None
                and d["last_at"] is not None
                and d["last_at"] - d["above_since"] >= DRIVE_ON_SUSTAIN_S
                and 0.0 <= now - d["last_at"] <= DRIVE_ON_GAP_S)

    def _poll_agent(self, seq: int) -> None:
        agent = self._agent()
        res = agent.call112_status() if agent is not None else {"ok": False}
        now, wall = self._clock(), self._wall()
        with self._lock:
            call = self._current(seq)
            if call is None or call["state"] not in LIVE:
                return
            data = res.get("data") if res.get("ok") else None
            raw = data.get("call") if isinstance(data, dict) else None
            view = _cpa.parse_call112_view(raw)
            if call["agent_seq"] is not None:
                mine = view is not None and view["seq"] == call["agent_seq"]
            else:
                # The answer to our POST was lost: a call requested around
                # our press (the agent's clock may be off by the HMAC window)
                # and newer than any call of this run is ours.
                floor = call["seq_floor"]
                mine = view is not None and (floor is None or view["seq"] > floor) \
                    and (view["requested_ts"] or 0) >= call["started_ts"] - AGENT_TS_MARGIN_S
            if mine:
                if call["agent_seq"] is None:
                    self._own_seq_locked(call, view["seq"])
                self._adopt_locked(call, view, now, wall)
                call["next_poll"] = now + POLL_LIVE_S
                return
            if isinstance(data, dict) and call["agent_seq"] is not None:
                # A signed answer without our call: the agent restarted (its
                # call lives only in memory) — it can neither show nor end
                # ours any more. After a few such answers ours ends here
                # (unverified) instead of blocking the window for an hour.
                call["forgotten"] += 1
                if call["forgotten"] >= POLL_FAILS_UNVERIFIED:
                    self._unverified_locked(call, now)
                    log.warning("112: the car phone no longer knows the call — ended here "
                                "(unverified)")
                    self._end_locked(call, now, wall)
                    return
            call["poll_fails"] += 1
            if call["poll_fails"] >= POLL_FAILS_UNVERIFIED and call["state"] != "dialing":
                self._unverified_locked(call, now)
            call["next_poll"] = now + (POLL_SLOW_S if call["poll_fails"]
                                       >= POLL_FAILS_UNVERIFIED else POLL_LIVE_S)

    def _mute(self, on: bool) -> None:
        """Path B: BCM's own media must not drown the speaker of the car
        phone. ``input.mute`` is a toggle (VolumeController): it is sent
        only when the state is the opposite (``audio.mute_changed``), and
        undone only if the mute is still ours."""
        muted = self._last("audio.mute_changed") is True
        if on and not muted and not self._muted_by_us:
            self._muted_by_us = True
            self._bus.publish("input.mute", True)
            log.info("112: BCM media muted for the car phone's call")
        elif not on and self._muted_by_us:
            self._muted_by_us = False
            if muted:
                self._bus.publish("input.mute", True)
                log.info("112: BCM media unmuted")

    # ── publication ────────────────────────────────────────────────────────

    def _dispatcher_locked(self, now: float, cfg: Call112Config) -> Optional[dict]:
        ev = self._event
        cands = []
        if self._pos is not None and self._pos_at is not None:
            cands.append((max(0.0, now - self._pos_at), self._pos))
        if ev is not None and ev["lat"] is not None and ev["fix_mono"] is not None:
            cands.append((max(0.0, now - ev["fix_mono"]), ev))
        if not cands and ev is None:
            return None
        # The freshest of the live fix and the event's last known one (GPS
        # is often lost right after an impact; the UI says how old it is).
        best = min(cands, key=lambda c: c[0]) if cands else None
        return {
            "lat": round(best[1]["lat"], 5) if best else None,
            "lon": round(best[1]["lon"], 5) if best else None,
            "fix_age_s": int(best[0]) if best else None,
            "sats": best[1].get("sats") if best else None,
            "heading": None if ev is None or ev["heading"] is None else int(round(ev["heading"]))
            % 360,
            "speed_kmh": None if ev is None or ev["speed_kmh"] is None
            else int(round(ev["speed_kmh"])),
            "event_ts": ev["ts"] if ev is not None else None,
            "vehicle": dict(cfg.vehicle),
        }

    def payload(self) -> dict[str, Any]:
        """``crash.call112_state`` as it would be published now."""
        now = self._clock()
        cfg = load_config(self._config)
        hfp, car = self._facts()
        with self._lock:
            ev = self._event
            call = self._call
            open_ = self._window_open_locked(now, cfg)
            offer, reasons, fallback, retry = self._offer_locked(now, cfg, hfp, car)
            duration = None
            if call is not None and call["active_mono"] is not None:
                end = call["ended_mono"] if call["ended_mono"] is not None else now
                duration = max(0, int(end - call["active_mono"]))
            return {
                "window": open_,
                "event_id": ev["id"] if ev is not None else None,
                "event_ts": ev["ts"] if ev is not None else None,
                "window_until_ts": ev["ts"] + cfg.window_min * 60.0 if ev is not None else None,
                "state": call["state"] if call is not None else "idle",
                "path": call["path"] if call is not None else "",
                "error": call["error"] if call is not None else "",
                "started_ts": call["started_ts"] if call is not None else None,
                "active_ts": call["active_ts"] if call is not None else None,
                "ended_ts": call["ended_ts"] if call is not None else None,
                "duration_s": duration,
                "unverified": bool(call and call["unverified"]),
                # The call got through to the phone network (oFono accepted
                # it / the car phone placed it) — crash_sms reads this.
                "reached": bool(call and call["reached"]),
                "reached_ts": call["reached_ts"] if call is not None else None,
                # Path A: is there a microphone uplink to the dispatcher?
                "uplink": call["uplink"] if call is not None else "unknown",
                "hangup_pending": bool(call and call["hangup_pending"]),
                "offer": offer,
                "fallback": fallback,
                "reasons": reasons,
                "retry_after_s": retry,
                "test_mode": cfg.test_mode,
                "test_number": mask_number(cfg.test_number) if cfg.test_number else "",
                "hold_ms": cfg.hold_ms, "arm_delay_ms": cfg.arm_delay_ms,
                "incoming": self._incoming and open_,
                "dispatcher": self._dispatcher_locked(now, cfg) if open_ else None,
            }

    def _publish(self) -> None:
        out = self.payload()
        with self._lock:
            if out == self._published:
                return
            self._published = out
        try:
            self._bus.publish(TOPIC_STATE, dict(out))
        except Exception:
            log.exception("Publishing %s failed", TOPIC_STATE)

    # ── persistence ────────────────────────────────────────────────────────

    _SAVED_KEYS = ("id", "ts", "lat", "lon", "fix_age_s", "sats", "heading", "speed_kmh",
                   "source", "dismissed")

    def _save(self) -> None:
        with self._lock:
            ev = self._event
            data = {"version": 1,
                    "event": None if ev is None else {k: ev[k] for k in self._SAVED_KEYS}}
        if data == self._saved:
            return
        try:
            atomic_write_json(self._path, data, mode=0o600, sort_keys=True)
            self._saved = data
            self._save_failed = False
        except (OSError, TypeError, ValueError) as e:
            if not self._save_failed:
                log.error("112: cannot save %s (%s) — after a restart the window would not "
                          "come back", self._path, clean_error(e))
            self._save_failed = True

    def load(self) -> None:
        """The saved event (worker, at start): the window comes back while
        it is within ``window_min`` of the event and was not closed."""
        try:
            with open(self._path, "rb") as f:
                raw = f.read(STATE_FILE_MAX + 1)
        except FileNotFoundError:
            return
        except OSError as e:
            log.warning("112: cannot read %s (%s)", self._path, clean_error(e))
            return
        data = None
        if len(raw) <= STATE_FILE_MAX:
            try:
                data = json.loads(raw.decode("utf-8"), parse_constant=_cpa._reject_constant)
            except (ValueError, UnicodeDecodeError, RecursionError):
                data = None
        saved = data.get("event") if isinstance(data, dict) else None
        if saved is None:
            if not isinstance(data, dict):
                log.warning("112: %s is damaged — ignored", self._path)
            return
        det = parse_detected(dict(saved, event_id=saved.get("id"),
                                  speed_before_kmh=saved.get("speed_kmh")) if isinstance(
            saved, dict) else None)
        if det is None or det["ts"] is None or not isinstance(saved.get("dismissed"), bool):
            log.warning("112: %s is damaged — ignored", self._path)
            return
        now, wall = self._clock(), self._wall()
        age = wall - det["ts"]
        cfg = load_config(self._config)
        if not 0 <= age <= cfg.window_min * 60.0:
            return
        with self._lock:
            self._event = dict(det, at_mono=now - age,
                               fix_mono=None if det["fix_age_s"] is None
                               else now - age - det["fix_age_s"],
                               dismissed=saved["dismissed"])
            self._drive = None
        self._saved = {"version": 1, "event": dict(saved)}
        if not saved["dismissed"]:
            log.warning("112: crash window of %s restored (%d min ago)", det["id"],
                        int(age // 60))


# ── the running instance (for the web routes) ─────────────────────────────

_INSTANCE: Optional[Call112] = None
_INSTANCE_LOCK = threading.Lock()


def get_call112() -> Optional[Call112]:
    """The running module, or None (not enabled, not started, stopped)."""
    with _INSTANCE_LOCK:
        return _INSTANCE


def start_call112(config, event_bus, hal=None, bt_manager=None, **kwargs) -> Call112:
    """Module entry point (``modules.call112``): builds the object, registers
    it for :func:`get_call112`, subscribes and starts its one daemon
    thread. ``bt_manager`` (main.py passes the shared BluetoothManager)
    enables path A; every dial happens on the worker."""
    global _INSTANCE
    module = Call112(config, event_bus, bt_manager=bt_manager)
    with _INSTANCE_LOCK:
        _INSTANCE = module
    module.start()
    return module
