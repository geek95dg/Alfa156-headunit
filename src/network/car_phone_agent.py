"""BCM's side of the Termux agent on the car phone: health, config sync,
pairing and a small signed API for the modules built on it.

Why this exists (plan F; shared later by D4 parking_guard, H call112, I cabin_watch)
-----------------------------------------------------------------------------------
The phone mounted in the car runs ``tools/car_phone/termux/bcm_agent.py``
(Python in Termux, listening on the phone's 127.0.0.1:8765 only). It owns
everything that must keep working when BCM does not: the deadline of a
crash SMS, the SMS texts (fixed GSM-7 templates on the phone), the rate
limits. BCM reaches it through car_phone's ``agent`` adb forward
(``net.car_phone`` → ``forwards.agent.local``, a privileged port so the kiosk
user cannot squat it) — this module never runs adb.

Enabled by ``modules.car_phone_agent`` only (requires ``car_phone``; off in
code and in the production config). There is no ``enabled`` sub-key.

The shared secret
-----------------
``network.car_phone.agent.secret`` ← ``BCM_CAR_PHONE_AGENT_SECRET`` from
``/etc/bcm/bcm.env`` (``SECRET_ENV_MAP``: never written to local.yaml).
At least 64 hex characters (32 bytes); generate with
``python3 -c 'import secrets;print(secrets.token_hex(32))'``. Missing or
malformed => state ``no_secret`` and ONE warning; the value is never
logged, published or shown.

Protocol (must match bcm_agent.py byte for byte)
------------------------------------------------
Request: ``X-BCM-Ts`` (epoch s), ``X-BCM-Nonce`` and ``X-BCM-Sig`` =
HMAC-SHA256(key, ``METHOD\\nPATH\\nTS\\nNONCE\\nSHA256HEX(body)``), hex —
the key is the shared secret, except for ``POST /v1/pair`` (below).
Response: ``X-BCM-Sig`` = HMAC-SHA256(secret,
``RESP\\nSTATUS\\nNONCE\\nSHA256HEX(body)``) over the nonce of OUR request —
an answer without a valid signature is never trusted: a 2xx without one
puts the module into ``bad_signature`` (something else answers on the
forward). Unsigned 401/403 answers are only informational (``unpaired``,
signature rejected, clock skew) and never carry pairing details.

Who can reach the agent (the threat model the pairing is built for): ANY
local process — every Android app through the phone's 127.0.0.1:8765, and
every user of the head unit, the unprivileged kiosk user included, through
the forward's local port (privileged, so they cannot BIND it, but anyone may
CONNECT). So:

* **Pairing needs a one-time code that starts on the phone.** ``python
  bcm_agent.py --pair`` (Termux) writes a 10-digit code into the agent's
  private ``PAIRING`` file and prints it; the driver types it into Settings
  → "Agent w telefonie". BCM signs ``POST /v1/pair {secret}`` with the CODE
  (same scheme as above); the agent stores the secret only when that
  signature checks out, deletes PAIRING afterwards and after 5 wrong codes.
  A process that merely polls cannot pair first. The code goes from the
  browser (loopback only) straight to the worker's memory for ONE attempt —
  never onto the bus, into a file or the log.
* **Proven pairing is remembered.** After the first answer signed with our
  secret, a fingerprint of the key is stored next to the nonce
  (``proven``). If the agent later says "unpaired" / "wrong signature"
  while that fingerprint still matches, it is either a reinstalled agent or
  another app squatting port 8765 after the agent died — which would
  receive the secret on a re-pair (it travels in the body). State
  ``error`` / reason ``agent_reset`` and a re-pair only with an explicit
  confirmation ("Sparuj mimo to", ``needs_confirm`` in the payload). A new
  secret in bcm.env = a new fingerprint = the normal first pairing.

Nonce: ``max(last + 1, now in ms)``, strictly increasing across restarts.
To spare the SSD, a block of :data:`NONCE_RESERVE` values is reserved by
writing its upper end atomically (``data/car_phone_agent.json``) BEFORE any
nonce of it is sent; after a restart counting resumes above it. When that
file is lost and the clock is behind, the agent answers a correctly signed
request with a SIGNED ``409 replay {min_nonce}`` and the client jumps there
once.

All HTTP happens on worker threads, one request at a time (the agent wants
strictly increasing nonces, so requests are serialised under one lock),
with :data:`REQUEST_TIMEOUT_S` per socket operation and ONE deadline
(:data:`RESPONSE_DEADLINE_S`) over the whole exchange — status line and
headers included, so a peer dripping one byte at a time cannot hold the
lock; never on the event bus dispatch thread. The module's own worker polls
``GET /v1/health`` every 30 s (a live agent that refuses us — wrong secret,
clock skew — is also asked every 30 s, so a fix shows at once; backoff 10 s
doubling to 5 min only while nothing answers; at once when the forward
(re)appears) and pushes ``PUT /v1/config`` when the agent's ``config_hash``
differs from the desired configuration:

* ``recipients`` ← ``crash_detection.sms.recipients`` (local.yaml; E.164
  ``^\\+[1-9][0-9]{7,14}$``, at most 3 — invalid ones are dropped with a
  warning),
* ``sim_slot`` (0|1), ``vehicle_label`` (``[A-Za-z0-9 .-]{1,20}``),
  ``dry_run`` (default True; only an explicit ``false`` sends real SMS),
  ``follow_up_cancel`` (default True) — all from ``crash_detection.sms``,
* ``toggles`` mirrored from ``modules.{crash_sms, parking_guard,
  cabin_watch, call112}`` — True only for a module that has code in this
  version (a planned module is never "on" on the phone).

A config the agent refused (400 ``bad_config``, or a hash that does not
match after a 200) is not re-sent until it changes (reason
``config_refused``); any other failure (the phone's storage, a timeout) is
retried with the next poll (reason ``config_pending``) — so the row never
says "działa" while the phone holds old recipients without saying so.

Published on ``net.car_phone_agent`` (on change; ``last_ok_ts`` alone at
most every 60 s)::

    {state, paired, pairing, version, sim_ready, last_ok_ts, last_sent_ts,
     reason, error, needs_confirm, since}

    state:  disabled | no_secret | waiting_forward | unpaired | ok | error
            | bad_signature
    paired: True = the last answer was signed with our secret; False = the
            agent is unpaired or rejects our signature; None = unknown
    pairing: the PAIRING file exists on the phone (signed health only)
    reason: '' | pairing_closed | bad_code | secret_mismatch | agent_reset
            | clock_skew | no_answer | storage | http | config_pending
            | config_refused   (what the Settings row explains)
    needs_confirm: a re-pair needs "Sparuj mimo to" (proven pairing)

Pairing is started by web_viewer's loopback-only, rate-limited
``POST /api/car_phone_agent/pair {code, confirm}`` through
:meth:`CarPhoneAgent.request_pair` (the instance comes from
:func:`get_agent`); the worker sends ``POST /v1/pair``. Never while the
state is ``bad_signature`` — whatever answers there is not the agent. A
request the worker cannot serve within :data:`PAIR_REQUEST_TTL_S` (no
forward, phone unplugged) is dropped, never sent hours later.

API for later modules (crash_sms, parking_guard, call112): get the running
instance with :func:`get_agent` (None while the module is not running) and
call it from YOUR OWN worker thread — each call may take a few seconds;
thread-safe, each returns ``{"ok", "status", "data", "error", "detail"}``
and never raises: :meth:`~CarPhoneAgent.arm_crash`,
:meth:`~CarPhoneAgent.cancel`, :meth:`~CarPhoneAgent.send_now`,
:meth:`~CarPhoneAgent.get`, :meth:`~CarPhoneAgent.test_sms`.
``test_sms(real=True)`` sends a REAL test SMS even while ``dry_run`` is on:
only from a loopback-only, rate-limited route after the driver confirmed it
on the head unit's screen.
"""

from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import math
import re
import socket
import threading
import time
from typing import Any, Callable, Optional

from src.core import modules_catalog
from src.core.fsutil import atomic_write_json
from src.core.logger import get_logger
from src.network._proc import _cfg_get, clean_error

log = get_logger("network.car_phone_agent")

TOPIC = "net.car_phone_agent"
CAR_PHONE_TOPIC = "net.car_phone"
FORWARD_NAME = "agent"
STATES = ("disabled", "no_secret", "waiting_forward", "unpaired", "ok", "error",
          "bad_signature")
REASONS = ("", "pairing_closed", "bad_code", "secret_mismatch", "agent_reset", "clock_skew",
           "no_answer", "storage", "http", "config_pending", "config_refused")
#: Reasons that may accompany state "ok" (the agent works, its config lags).
OK_REASONS = ("config_pending", "config_refused")
SECRET_PATH = "network.car_phone.agent.secret"
SECRET_ENV = "BCM_CAR_PHONE_AGENT_SECRET"
STATE_FILE = "data/car_phone_agent.json"
STATE_FILE_MAX = 4096
HOST = "127.0.0.1"

#: Per socket operation (connect, send, each read) — the plan's 3 s.
REQUEST_TIMEOUT_S = 3.0
#: The whole response must be read within this (a drip-feeding peer).
RESPONSE_DEADLINE_S = 6.0
#: Waiting for another thread's request (requests are serialised).
LOCK_TIMEOUT_S = 8.0
#: A "Sparuj" the worker could not serve within this is dropped (the phone
#: was unplugged): the secret never goes out long after the driver asked.
PAIR_REQUEST_TTL_S = 30.0
MAX_RESPONSE_BYTES = 16384
POLL_OK_S = 30.0
BACKOFF_MIN_S = 10.0
BACKOFF_MAX_S = 300.0
WAIT_FORWARD_S = 30.0
NO_SECRET_WAIT_S = 3600.0
#: Nonce values reserved per write of the state file (10 min of ms).
NONCE_RESERVE = 600_000
NONCE_MAX = 10**18
LAST_OK_REPUBLISH_S = 60.0

AGENT_TOGGLES = ("crash_sms", "parking_guard", "cabin_watch", "call112")
DEFAULT_LABEL = "ALFA 156"
MAX_RECIPIENTS = 3
COUNTDOWN_MIN_S = 15
COUNTDOWN_MAX_S = 120
#: The agent's accepted range of a crash event's epoch timestamp.
EVENT_TS_MIN = 1_600_000_000
EVENT_TS_MAX = 4_000_000_000

SECRET_RE = re.compile(r"^[0-9a-fA-F]{64,128}$")
#: The one-time pairing code bcm_agent.py --pair prints (10 digits).
PAIR_CODE_RE = re.compile(r"^[0-9]{10}$")
E164_RE = re.compile(r"^\+[1-9][0-9]{7,14}$")
LABEL_RE = re.compile(r"^[A-Za-z0-9 .-]{1,20}$")
EVENT_ID_RE = re.compile(r"^[0-9a-f]{1,32}$")
SIG_RE = re.compile(r"^[0-9a-f]{64}$")
VERSION_RE = re.compile(r"^[0-9A-Za-z.+-]{1,16}$")
HASH_RE = re.compile(r"^[0-9a-f]{16}$")

#: Error codes the agent sends WITHOUT a signature (it cannot sign for a
#: client it did not authenticate) — informational only.
UNSIGNED_CODES = ("unpaired", "bad_auth", "stale_ts", "pairing_closed", "rate_limited",
                  "bad_code", "bad_request", "bad_json", "bad_secret", "storage", "too_large",
                  "not_found", "method_not_allowed", "internal")
#: Failures that came from an agent that ANSWERED (it refuses us): asked again
#: at the normal pace, so fixing it on the phone shows within 30 s. Anything
#: else (nothing answers, our storage) backs off.
LIVE_CODES = ("unpaired", "bad_auth", "stale_ts", "pairing_closed", "rate_limited",
              "bad_code", "http")


# ── protocol (pure; mirrors tools/car_phone/termux/bcm_agent.py) ──────────

def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def request_message(method: str, path: str, ts: int, nonce: int, body: bytes) -> bytes:
    return f"{method}\n{path}\n{ts}\n{nonce}\n{sha256_hex(body)}".encode("ascii")


def response_message(status: int, nonce: int, body: bytes) -> bytes:
    return f"RESP\n{status}\n{nonce}\n{sha256_hex(body)}".encode("ascii")


def sign(key: bytes, message: bytes) -> str:
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def config_hash(cfg: dict) -> str:
    return sha256_hex(canonical_json(cfg).encode("ascii"))[:16]


def key_fingerprint(key: bytes) -> str:
    """What is stored as "pairing with this key was proven" (not the key)."""
    return sha256_hex(b"bcm-car-phone-agent proven\n" + key)[:16]


def parse_secret(value: Any) -> Optional[bytes]:
    """The configured secret as key bytes, or None (missing / malformed)."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not SECRET_RE.fullmatch(text) or len(text) % 2:
        return None
    return bytes.fromhex(text)


def _reject_constant(name: str) -> Any:
    raise ValueError(f"{name} is not valid JSON")


def _json_object(raw: bytes) -> Optional[dict]:
    try:
        obj = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant)
    except (ValueError, UnicodeDecodeError, RecursionError):
        return None
    return obj if isinstance(obj, dict) else None


def _module_on(config: Any, name: str) -> bool:
    """``modules.<name>`` strictly True AND the module has code in this
    version — the phone never treats a planned feature as on."""
    info = modules_catalog.MODULES.get(name)
    if info is None or not modules_catalog.is_available(info):
        return False
    return _cfg_get(config, f"modules.{name}", False) is True


def desired_config(config: Any, warn: Optional[Callable[[str, str], None]] = None) -> dict:
    """What the agent should hold (``PUT /v1/config``), in the agent's
    canonical form — the hash must match the agent's ``config_hash``.
    ``warn(key, message)`` is called for every value that was dropped."""
    def _warn(key: str, msg: str) -> None:
        if warn is not None:
            warn(key, msg)

    sms = _cfg_get(config, "crash_detection.sms", {})
    if not isinstance(sms, dict):
        sms = {}
    raw = sms.get("recipients", [])
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        _warn("recipients", "crash_detection.sms.recipients is not a list — no recipients")
        raw = []
    recipients: list[str] = []
    for n in raw:
        if not isinstance(n, str) or not E164_RE.fullmatch(n.strip()):
            # The number itself is not logged (personal data) — its position is.
            _warn(f"recipient:{len(recipients)}",
                  "crash_detection.sms.recipients: an entry is not an E.164 number "
                  "('+', country code, digits, no spaces) — ignored")
            continue
        n = n.strip()
        if n in recipients:
            continue
        if len(recipients) >= MAX_RECIPIENTS:
            _warn("recipients_max", f"crash_detection.sms.recipients: more than "
                                    f"{MAX_RECIPIENTS} — only the first {MAX_RECIPIENTS} used")
            break
        recipients.append(n)
    slot = sms.get("sim_slot", 0)
    if isinstance(slot, bool) or slot not in (0, 1):
        _warn("sim_slot", f"crash_detection.sms.sim_slot={slot!r} — using 0")
        slot = 0
    label = sms.get("vehicle_label", DEFAULT_LABEL)
    if not isinstance(label, str) or not LABEL_RE.fullmatch(label) or label != label.strip():
        _warn("vehicle_label", f"crash_detection.sms.vehicle_label is not 1-20 characters "
                               f"A-Z a-z 0-9 space . - — using {DEFAULT_LABEL!r}")
        label = DEFAULT_LABEL
    return {
        "recipients": recipients,
        "sim_slot": int(slot),
        "vehicle_label": label,
        "toggles": {name: _module_on(config, name) for name in AGENT_TOGGLES},
        # Only an explicit false sends real SMS (a typo stays in test mode).
        "dry_run": sms.get("dry_run", True) is not False,
        "follow_up_cancel": sms.get("follow_up_cancel", True) is not False,
    }


# ── transport ─────────────────────────────────────────────────────────────

class AgentError(Exception):
    """A request that did not produce a signed answer.

    ``code``: no_secret | no_forward | busy | storage | connect | timeout |
    protocol | bad_signature | one of :data:`UNSIGNED_CODES` (the agent's
    unsigned refusal; ``body`` carries its informational fields)."""

    def __init__(self, code: str, detail: str = "", status: Optional[int] = None,
                 body: Optional[dict] = None) -> None:
        super().__init__(code)
        self.code = code
        self.detail = clean_error(detail) if detail else ""
        self.status = status
        self.body = body or {}


def default_connect(port: int, timeout: float) -> http.client.HTTPConnection:
    return http.client.HTTPConnection(HOST, port, timeout=timeout)


class AgentClient:
    """Signs requests, verifies answers, keeps the nonce and the "pairing
    proven" fingerprint. Thread-safe: one request at a time (the agent wants
    strictly increasing nonces)."""

    def __init__(self, key: bytes, nonce_path: str,
                 wall_clock: Callable[[], float] = time.time,
                 connect: Callable[[int, float], Any] = default_connect,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._key = key
        self._fp = key_fingerprint(key)
        self._path = nonce_path
        self._wall = wall_clock
        self._connect = connect
        self._clock = clock
        self._io = threading.Lock()
        self._reserved, self._proven = self._load_state()
        self._last = self._reserved

    def _load_state(self) -> tuple[int, Optional[str]]:
        try:
            with open(self._path, "rb") as f:
                raw = f.read(STATE_FILE_MAX + 1)
        except FileNotFoundError:
            return 0, None
        except OSError as e:
            log.warning("Car phone agent: cannot read %s (%s) — nonce starts from the clock",
                        self._path, clean_error(e))
            return 0, None
        obj = _json_object(raw) if len(raw) <= STATE_FILE_MAX else None
        value = obj.get("reserved") if obj else None
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < NONCE_MAX:
            log.warning("Car phone agent: %s is damaged — nonce starts from the clock",
                        self._path)
            return 0, None
        proven = obj.get("proven")
        return value, proven if isinstance(proven, str) and HASH_RE.fullmatch(proven) else None

    @property
    def last_nonce(self) -> int:
        return self._last

    @property
    def proven(self) -> bool:
        """An answer signed with THIS key was seen (now or before a restart)."""
        return self._proven == self._fp

    def _save_state(self, reserved: int) -> None:
        atomic_write_json(self._path, {"version": 1, "reserved": reserved,
                                       "proven": self._proven}, mode=0o600)

    def _mark_proven(self) -> None:
        """First answer signed with our key: remember it (on disk at once —
        a restart must not forget it, see the module docstring)."""
        if self._proven == self._fp:
            return
        self._proven = self._fp
        try:
            self._save_state(self._reserved)
        except (OSError, TypeError, ValueError) as e:
            log.warning("Car phone agent: cannot save the pairing proof (%s) — kept in "
                        "memory only", clean_error(e))

    def _next_nonce(self) -> int:
        """Strictly increasing; the reservation is on disk BEFORE the value
        is used (``storage`` error otherwise — nothing is sent)."""
        n = max(self._last + 1, int(self._wall() * 1000))
        if n >= NONCE_MAX:
            raise AgentError("storage", "nonce out of range")
        if n > self._reserved:
            reserved = min(n + NONCE_RESERVE, NONCE_MAX - 1)
            try:
                self._save_state(reserved)
            except (OSError, TypeError, ValueError) as e:
                raise AgentError("storage", f"cannot save the nonce: {e}") from e
            self._reserved = reserved
        self._last = n
        return n

    def _bump(self, floor: Any) -> bool:
        if isinstance(floor, bool) or not isinstance(floor, int) or not 0 < floor < NONCE_MAX:
            return False
        if floor - 1 > self._last:
            log.warning("Car phone agent: the agent saw higher nonces than ours (our state "
                        "file was lost?) — continuing from %d", floor)
            self._last = floor - 1
        return True

    def request(self, port: int, method: str, path: str, body: Optional[dict] = None,
                sign_key: Optional[bytes] = None) -> tuple[int, dict]:
        """One request → ``(status, json)`` of a SIGNED answer; anything else
        raises :class:`AgentError`. ``sign_key`` signs the request instead of
        the secret (``/v1/pair``: the pairing code); the answer is always
        verified with the secret."""
        if not self._io.acquire(timeout=LOCK_TIMEOUT_S):
            raise AgentError("busy", "another request to the agent is still running")
        try:
            key = self._key if sign_key is None else sign_key
            for attempt in (0, 1):
                nonce = self._next_nonce()
                status, obj = self._exchange(port, method, path, body, nonce, key)
                if status == 409 and obj.get("error") == "replay" and attempt == 0 \
                        and self._bump(obj.get("min_nonce")):
                    continue
                return status, obj
            return status, obj
        finally:
            self._io.release()

    def _exchange(self, port: int, method: str, path: str, body: Optional[dict], nonce: int,
                  key: bytes) -> tuple[int, dict]:
        data = canonical_json(body).encode("ascii") if body is not None else b""
        ts = int(self._wall())
        headers = {"Content-Type": "application/json", "Connection": "close",
                   "X-BCM-Ts": str(ts), "X-BCM-Nonce": str(nonce),
                   "X-BCM-Sig": sign(key, request_message(method, path, ts, nonce, data))}
        conn = None
        cut = threading.Event()

        def _deadline() -> None:
            # One deadline over the whole exchange: http.client reads the
            # status line and headers with only the per-recv timeout, so a
            # peer sending a byte every 2.9 s would hold the lock (and every
            # API caller, e.g. a crash cancel) for minutes.
            cut.set()
            sock = getattr(conn, "sock", None)
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

        timer = threading.Timer(RESPONSE_DEADLINE_S, _deadline)
        timer.daemon = True
        try:
            conn = self._connect(port, REQUEST_TIMEOUT_S)
            timer.start()
            conn.request(method, path, body=data if data else None, headers=headers)
            resp = conn.getresponse()
            status = int(resp.status)
            sig = (resp.getheader("X-BCM-Sig") or "").strip().lower()
            raw = self._read(resp)
        except http.client.RemoteDisconnected as e:
            # adb's server accepts on the local port and closes the socket
            # when nothing listens on the phone: "Termux / agent not running".
            if cut.is_set():
                raise AgentError("timeout", f"no answer within {RESPONSE_DEADLINE_S:.0f} s") \
                    from e
            raise AgentError("connect", "the connection was closed without an answer "
                                        "(is the agent running on the phone?)") from e
        except ConnectionRefusedError as e:
            raise AgentError("connect", f"nothing listens on 127.0.0.1:{port} ({e})") from e
        except (socket.timeout, TimeoutError) as e:
            raise AgentError("timeout", f"no answer within {REQUEST_TIMEOUT_S:.0f} s") from e
        except http.client.HTTPException as e:
            if cut.is_set():
                raise AgentError("timeout", f"no answer within {RESPONSE_DEADLINE_S:.0f} s") \
                    from e
            raise AgentError("protocol", f"bad HTTP answer: {type(e).__name__}") from e
        except OSError as e:
            if cut.is_set():
                raise AgentError("timeout", f"no answer within {RESPONSE_DEADLINE_S:.0f} s") \
                    from e
            raise AgentError("connect", str(e) or type(e).__name__) from e
        finally:
            timer.cancel()
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
        expected = sign(self._key, response_message(status, nonce, raw))
        if SIG_RE.fullmatch(sig) and hmac.compare_digest(expected, sig):
            obj = _json_object(raw)
            if obj is None:
                raise AgentError("protocol", "the signed answer is not a JSON object", status)
            self._mark_proven()
            return status, obj
        # Not signed by our secret: never trusted. A refusal the agent could
        # not sign is informational; anything else — above all a "success" —
        # means something else answers in the agent's place.
        obj = _json_object(raw) or {}
        code = obj.get("error")
        if 400 <= status < 600 and not sig and isinstance(code, str) and code in UNSIGNED_CODES:
            info = {k: obj.get(k) for k in ("time", "version")}
            raise AgentError(code, f"agent: {code} (HTTP {status})", status, info)
        raise AgentError("bad_signature", f"answer to {method} {path} (HTTP {status}) is not "
                                          f"signed with our secret", status)

    def _read(self, resp: Any) -> bytes:
        deadline = self._clock() + RESPONSE_DEADLINE_S
        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = resp.read1(4096) if hasattr(resp, "read1") else resp.read(4096)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_RESPONSE_BYTES:
                raise http.client.HTTPException("answer too large")
            chunks.append(chunk)
            if self._clock() > deadline:
                raise socket.timeout("answer too slow")
        return b"".join(chunks)


# ── the module ────────────────────────────────────────────────────────────

def _num(value: Any, lo: float, hi: float) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value if lo <= value <= hi else None


def _result(ok: bool, status: Optional[int] = None, data: Optional[dict] = None,
            error: str = "", detail: str = "") -> dict:
    return {"ok": ok, "status": status, "data": data, "error": error, "detail": detail}


class CarPhoneAgent:
    """Health, config sync and pairing of the Termux agent, plus the API.

    Args:
        config: BCMConfig or nested dict.
        event_bus: EventBus.
        state_path: the nonce reservation / pairing proof file.
        clock: monotonic seconds (poll cadence, backoff).
        wall_clock: epoch seconds (request ``ts``, nonce, ``since``).
        connect: ``(port, timeout) -> HTTPConnection``-like (tests).

    Threads: the worker (:meth:`_run` → :meth:`cycle`) is the only writer of
    the poll schedule (``_delay``, ``_next_poll``) and the only sender of
    ``POST /v1/pair``; other threads (the API, the pair route, stop()) only
    hand it work (``_pair_pending``, ``_untrusted_pending``) or publish under
    ``_pub_lock``, so publications never arrive out of order.
    """

    def __init__(self, config: Any, event_bus: Any, state_path: str = STATE_FILE,
                 clock: Callable[[], float] = time.monotonic,
                 wall_clock: Callable[[], float] = time.time,
                 connect: Callable[[int, float], Any] = default_connect) -> None:
        self._config = config
        self._bus = event_bus
        self._clock = clock
        self._wall = wall_clock
        key = parse_secret(_cfg_get(config, SECRET_PATH))
        self._client: Optional[AgentClient] = None
        if key is None:
            # The value itself is never logged — not even its length.
            log.warning("Car phone agent: %s is missing or not >= 64 hex characters — the "
                        "agent stays idle. Generate one: python3 -c 'import secrets;"
                        "print(secrets.token_hex(32))' and put it into /etc/bcm/bcm.env",
                        SECRET_ENV)
        else:
            self._client = AgentClient(key, state_path, wall_clock, connect, clock)
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: Optional[threading.Thread] = None
        # Work handed to the worker by other threads.
        self._ev_lock = threading.Lock()
        self._pair_pending: Optional[tuple[str, bool, float]] = None
        self._untrusted_pending: Optional[AgentError] = None
        self._state_lock = threading.Lock()
        self._pub_lock = threading.Lock()
        self._fwd_seen: Optional[tuple[int, bool]] = None
        self._delay = BACKOFF_MIN_S
        self._next_poll = 0.0
        self._push_failed: Optional[str] = None
        self._push_logged = ""
        self._warned: set[str] = set()
        self._logged_error = ""
        # Last known agent facts (published with every state).
        self._info: dict[str, Any] = {"paired": None, "pairing": None, "version": None,
                                      "sim_ready": None, "last_ok_ts": None,
                                      "last_sent_ts": None}
        self._state = "disabled"
        self._payload: Optional[dict[str, Any]] = None
        self._published_ok_ts: Optional[float] = None
        self._since = 0.0

    # ── lifecycle ─────────────────────────────────────────────────────────

    def _subscriptions(self) -> tuple:
        return ((CAR_PHONE_TOPIC, self._on_car_phone),
                ("power.shutting_down", self._on_shutdown))

    def start(self) -> None:
        """Subscribe and start the worker; no I/O here."""
        if self._thread is not None:
            return
        for topic, cb in self._subscriptions():
            self._bus.subscribe(topic, cb)
        self._thread = threading.Thread(target=self._run, daemon=True, name="car-phone-agent")
        self._thread.start()
        log.info("Car phone agent started (via the car phone's '%s' forward, secret: %s)",
                 FORWARD_NAME, "set" if self._client is not None else "MISSING")

    def stop(self) -> None:
        """Never waits for a request in progress (at most a few seconds)."""
        global _INSTANCE
        if self._stop.is_set():
            return
        self._stop.set()
        self._wake.set()
        with _INSTANCE_LOCK:
            if _INSTANCE is self:
                _INSTANCE = None
        with self._ev_lock:
            self._pair_pending = None
        for topic, cb in self._subscriptions():
            try:
                self._bus.unsubscribe(topic, cb)
            except Exception:
                pass
        self._set_state("disabled", force=True)
        log.info("Car phone agent stopped")

    def _on_shutdown(self, topic: str, value: Any, timestamp: float) -> None:
        if value:
            self.stop()

    def _on_car_phone(self, topic: str, value: Any, timestamp: float) -> None:
        """Forward state changed: only a wake-up (bus dispatcher, no I/O)."""
        self._wake.set()

    @property
    def state(self) -> Optional[dict[str, Any]]:
        with self._state_lock:
            if self._payload is None:
                return None
            return dict(self._payload, since=self._since)

    def _on_worker(self) -> bool:
        """The caller is the worker — or no worker runs (tests drive
        :meth:`cycle` by hand, then the caller is the only writer)."""
        return self._thread is None or threading.current_thread() is self._thread

    # ── pairing request (web_viewer's route; any thread) ──────────────────

    def request_pair(self, code: Any, confirm: Any = False) -> dict:
        """"Sparuj" with the one-time code from the phone. Validates, then
        hands the code to the worker for ONE attempt (memory only — never
        the bus, a file or the log) and returns at once; the outcome shows
        on ``net.car_phone_agent``. Errors: stopped, bad_request, no_secret,
        no_forward, untrusted, already_paired, confirm_needed."""
        if self._stop.is_set():
            return _result(False, error="stopped")
        if not isinstance(code, str) or not PAIR_CODE_RE.fullmatch(code) \
                or not isinstance(confirm, bool):
            return _result(False, error="bad_request", detail="code: 10 digits from the phone")
        if self._client is None:
            return _result(False, error="no_secret")
        if self.forward_port() is None:
            return _result(False, error="no_forward")
        with self._ev_lock:
            untrusted = self._untrusted_pending is not None
        with self._state_lock:
            state, paired = self._state, self._info.get("paired")
        if untrusted or state == "bad_signature":
            # Something else answers on the forward: it would get the secret.
            return _result(False, error="untrusted")
        if state == "ok" and paired is True:
            return _result(False, error="already_paired")
        if self._client.proven and not confirm:
            return _result(False, error="confirm_needed")
        with self._ev_lock:
            self._pair_pending = (code, confirm, self._clock())
        self._wake.set()
        return _result(True)

    def _take_pair(self) -> Optional[tuple[str, bool]]:
        with self._ev_lock:
            pending, self._pair_pending = self._pair_pending, None
        if pending is None:
            return None
        code, confirm, at = pending
        if self._clock() - at > PAIR_REQUEST_TTL_S:
            log.warning("Car phone agent: pair request dropped — too old (the forward was "
                        "down); press Sparuj again")
            return None
        return code, confirm

    def _drop_pair(self, why: str) -> None:
        with self._ev_lock:
            pending, self._pair_pending = self._pair_pending, None
        if pending is not None:
            log.warning("Car phone agent: pair request dropped — %s", why)

    # ── worker ────────────────────────────────────────────────────────────

    def _run(self) -> None:
        while not self._stop.is_set():
            self._wake.clear()
            try:
                wait = self.cycle()
            except Exception:
                log.exception("Car phone agent: worker pass failed")
                self._set_state("error", reason="http", error="internal error (see the log)")
                wait = BACKOFF_MIN_S
            if wait > 0:
                self._wake.wait(wait)

    def forward_spec(self) -> tuple[Optional[tuple[int, bool]], str]:
        """car_phone's ``agent`` forward from ``net.car_phone``:
        ``((local port, ok), why)`` or ``(None, why)``."""
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
            return None, ("car_phone has no agent forward — modules.car_phone_agent must be "
                          "on in the config when car_phone starts")
        port = spec.get("local")
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            return None, "car_phone reports an invalid agent forward port"
        ok = spec.get("ok") is True
        why = ""
        if not ok:
            err = spec.get("error")
            why = clean_error(err) if isinstance(err, str) and err else \
                "the agent forward is not up (phone not connected?)"
        return (port, ok), why

    def forward_port(self) -> Optional[int]:
        spec, _why = self.forward_spec()
        return spec[0] if spec is not None and spec[1] else None

    def cycle(self) -> float:
        """One worker step; returns how long to wait (a ``net.car_phone``
        change, a pair request or stop() cut it short)."""
        with self._ev_lock:
            untrusted, self._untrusted_pending = self._untrusted_pending, None
        if untrusted is not None:
            self._failed(untrusted)
        if self._client is None:
            self._drop_pair("no secret")
            self._set_state("no_secret", error=f"{SECRET_ENV} missing or invalid")
            return NO_SECRET_WAIT_S
        spec, why = self.forward_spec()
        if spec is None or not spec[1]:
            self._drop_pair("the agent forward is down")
            self._fwd_seen = spec
            self._set_state("waiting_forward", error=why)
            return WAIT_FORWARD_S
        port = spec[0]
        if self._fwd_seen != (port, True):
            # The forward (re)appeared or moved: ask the agent now.
            self._fwd_seen = (port, True)
            self._delay = BACKOFF_MIN_S
            self._next_poll = 0.0
        pending = self._take_pair()
        if pending is not None and self.pair(*pending)["ok"]:
            # Paired: health and the config push right away. A failure keeps
            # the schedule, so its hint (wrong code…) stays up until the
            # next regular poll instead of being overwritten at once.
            self._next_poll = 0.0
        now = self._clock()
        if now < self._next_poll:
            return min(self._next_poll - now, POLL_OK_S)
        self.poll()
        return max(0.0, min(self._next_poll - self._clock(), BACKOFF_MAX_S))

    def poll(self) -> None:
        """``GET /v1/health`` → state; push the config when it differs."""
        port = self.forward_port()
        if port is None or self._client is None:
            return
        try:
            status, obj = self._client.request(port, "GET", "/v1/health")
        except AgentError as e:
            self._failed(e)
            return
        if status != 200:
            self._failed(AgentError("http", f"health: HTTP {status} {obj.get('error', '')}",
                                    status))
            return
        self._healthy(obj)
        reason = self._push_config(port, obj.get("config_hash"))
        if reason is not None:
            self._set_state("ok", reason=reason)

    def _healthy(self, obj: dict) -> None:
        """Facts from a signed health answer (published by the caller)."""
        version = obj.get("version")
        sim = obj.get("sim_ready")
        sent = _num(obj.get("last_sent_ts"), 0, 4e9)
        pairing = obj.get("pairing")
        with self._state_lock:
            self._info.update(
                paired=True,
                pairing=pairing if isinstance(pairing, bool) else None,
                version=version if isinstance(version, str) and VERSION_RE.fullmatch(version)
                else None,
                sim_ready=sim if isinstance(sim, bool) else None,
                last_ok_ts=self._wall(),
                last_sent_ts=sent)
        self._delay = BACKOFF_MIN_S
        self._next_poll = self._clock() + POLL_OK_S
        self._logged_error = ""

    def _failed(self, e: AgentError) -> None:
        """Map a failed request to the published state and the next poll
        (worker only — see the class docstring)."""
        now = self._clock()
        proven = self._client is not None and self._client.proven
        if e.code == "bad_signature":
            state, reason = "bad_signature", ""
            with self._state_lock:
                self._info["paired"] = None
        elif e.code in ("unpaired", "bad_auth") and proven:
            # We HAVE seen this agent sign with our secret. Now it does not
            # know it: reinstalled — or another app answers on port 8765
            # after the agent died, and would get the secret from a re-pair.
            state, reason = "error", "agent_reset"
            with self._state_lock:
                self._info.update(paired=False, pairing=None)
        elif e.code == "unpaired":
            state, reason = "unpaired", ""
            with self._state_lock:
                self._info.update(paired=False, pairing=None)
        elif e.code == "bad_auth":
            state, reason = "error", "secret_mismatch"
            with self._state_lock:
                self._info.update(paired=False, pairing=None)
        elif e.code == "stale_ts":
            state, reason = "error", "clock_skew"
            t = _num(e.body.get("time"), 0, 4e9)
            if t is not None:
                e.detail = clean_error(f"the phone's clock differs from BCM's by "
                                       f"{int(t - self._wall())} s")
        elif e.code in ("connect", "timeout"):
            state, reason = "error", "no_answer"
        elif e.code == "storage":
            state, reason = "error", "storage"
        else:
            state, reason = "error", "http"
        if e.code in LIVE_CODES:
            # The agent answers — it just refuses us: ask at the normal pace,
            # so a fix on the phone (or Sparuj) shows within 30 s.
            next_wait = POLL_OK_S
            self._delay = BACKOFF_MIN_S
        else:
            next_wait = self._delay
            self._delay = min(self._delay * 2, BACKOFF_MAX_S)
        self._next_poll = now + next_wait
        detail = e.detail or e.code
        self._set_state(state, reason=reason, error=detail)
        if detail != self._logged_error:
            self._logged_error = detail
            (log.error if state == "bad_signature" or reason == "agent_reset" else log.warning)(
                "Car phone agent: %s%s — next attempt in %.0f s", detail,
                " (pairing with this secret was proven before: reinstalled agent, or "
                "another app on the agent's port?)" if reason == "agent_reset" else "",
                next_wait)

    def _note_untrusted(self, e: AgentError) -> None:
        """An unsigned answer seen by an API caller: the worker maps it."""
        if self._on_worker():
            self._failed(e)
            return
        with self._ev_lock:
            self._untrusted_pending = e
        self._wake.set()

    def _push_config(self, port: int, agent_hash: Any) -> Optional[str]:
        """Bring the agent's config in line; returns the reason to publish
        with state ok ('' in sync, ``config_pending``, ``config_refused``) or
        None when the state was already set (``bad_signature``).

        Only a DETERMINISTIC refusal is latched (not re-sent until the
        desired config changes): a signed 400 ``bad_config`` or a 200 whose
        hash does not match. A transient failure (the phone's storage, a
        timeout, a 5xx) is retried with the next poll — at most one PUT per
        :data:`POLL_OK_S`."""
        if self._client is None:
            return ""
        desired = desired_config(self._config, self._warn_once)
        want = config_hash(desired)
        if isinstance(agent_hash, str) and agent_hash == want:
            self._push_failed = None
            self._push_logged = ""
            return ""
        if want == self._push_failed:
            return "config_refused"     # the agent refused exactly this — wait for a change
        try:
            status, obj = self._client.request(port, "PUT", "/v1/config", desired)
        except AgentError as e:
            if e.code == "bad_signature":
                self._failed(e)
                return None
            self._log_push(f"config push failed ({e.detail or e.code}) — the next poll "
                           "retries")
            return "config_pending"
        if status == 200 and obj.get("config_hash") == want:
            self._push_failed = None
            self._push_logged = ""
            log.info("Car phone agent: config pushed (%d recipient(s), slot %d, dry_run=%s, "
                     "toggles: %s)", len(desired["recipients"]), desired["sim_slot"],
                     desired["dry_run"],
                     ",".join(k for k, v in desired["toggles"].items() if v) or "-")
            return ""
        detail = clean_error(obj.get("detail") or obj.get("error") or "")
        if status == 200 or (status == 400 and obj.get("error") == "bad_config"):
            self._push_failed = want
            log.warning("Car phone agent: the agent refused the config (HTTP %d: %s) — not "
                        "retried until it changes", status, detail or "hash mismatch")
            return "config_refused"
        self._log_push(f"config push failed (HTTP {status}: {detail}) — the next poll retries")
        return "config_pending"

    def _log_push(self, message: str) -> None:
        """One warning per distinct failure, not one every 30 s."""
        if message != self._push_logged:
            self._push_logged = message
            log.warning("Car phone agent: %s", message)

    def _warn_once(self, key: str, message: str) -> None:
        if key not in self._warned:
            self._warned.add(key)
            log.warning("Car phone agent: %s", message)

    # ── API for other modules (their worker threads) ──────────────────────

    def _call(self, method: str, path: str, body: Optional[dict] = None,
              sign_key: Optional[bytes] = None) -> dict:
        if self._stop.is_set():
            return _result(False, error="stopped")
        if self._client is None:
            return _result(False, error="no_secret")
        port = self.forward_port()
        if port is None:
            return _result(False, error="no_forward")
        try:
            status, obj = self._client.request(port, method, path, body, sign_key=sign_key)
        except AgentError as e:
            if e.code == "bad_signature":
                self._note_untrusted(e)
            return _result(False, e.status, e.body or None, e.code, e.detail)
        ok = 200 <= status < 300
        err = obj.get("error") if not ok else ""
        return _result(ok, status, obj, err if isinstance(err, str) else "http")

    def arm_crash(self, event_id: str, countdown_s: int, lat: Optional[float],
                  lon: Optional[float], fix_age_s: Optional[int], speed_kmh: Optional[float],
                  dv_kmh: Optional[float], event_ts: int, dry_run: bool = False) -> dict:
        """``POST /v1/crash`` — from this answer on, the PHONE holds the
        deadline. Idempotent by ``event_id`` (retry with the same id).

        Only ``event_id``, ``countdown_s`` and ``event_ts`` are strict (a bad
        one = ``bad_request``, nothing reaches the phone). The informational
        numbers (position, fix age, speeds) are sent as "unknown" (null)
        when out of range — a GPS speed glitch must not cost the alarm; the
        SMS template has words for missing values."""
        if not isinstance(event_id, str) or not EVENT_ID_RE.fullmatch(event_id):
            return _result(False, error="bad_request", detail="event_id: 1-32 lowercase hex")
        if isinstance(countdown_s, bool) or not isinstance(countdown_s, int) \
                or not COUNTDOWN_MIN_S <= countdown_s <= COUNTDOWN_MAX_S:
            return _result(False, error="bad_request", detail="countdown_s: 15..120")
        ts = _num(event_ts, EVENT_TS_MIN, EVENT_TS_MAX)
        if ts is None:
            return _result(False, error="bad_request", detail="event_ts: epoch seconds")
        dropped = []
        if lat is None and lon is None:
            pos = None
        elif _num(lat, -90, 90) is None or _num(lon, -180, 180) is None:
            pos = None
            dropped.append("lat/lon")
        else:
            pos = (round(float(lat), 6), round(float(lon), 6))
        age = None if fix_age_s is None else _num(fix_age_s, 0, 86400)
        if fix_age_s is not None and age is None:
            dropped.append("fix_age_s")
        body: dict[str, Any] = {
            "event_id": event_id, "countdown_s": countdown_s,
            "lat": None if pos is None else pos[0],
            "lon": None if pos is None else pos[1],
            "fix_age_s": None if age is None or pos is None else int(age),
            "event_ts": int(ts),
            "dry_run": bool(dry_run),
        }
        for key, value in (("speed_kmh", speed_kmh), ("dv_kmh", dv_kmh)):
            v = None if value is None else _num(value, 0, 400)
            if value is not None and v is None:
                dropped.append(key)
            body[key] = None if v is None else int(round(v))
        if dropped:
            self._warn_once("arm:" + ",".join(dropped),
                            f"crash event {event_id}: {', '.join(dropped)} out of range — "
                            f"sent as unknown")
        return self._call("POST", "/v1/crash", body)

    def cancel(self, event_id: str) -> dict:
        if not isinstance(event_id, str) or not EVENT_ID_RE.fullmatch(event_id):
            return _result(False, error="bad_request", detail="event_id")
        return self._call("POST", f"/v1/crash/{event_id}/cancel", {})

    def send_now(self, event_id: str) -> dict:
        if not isinstance(event_id, str) or not EVENT_ID_RE.fullmatch(event_id):
            return _result(False, error="bad_request", detail="event_id")
        return self._call("POST", f"/v1/crash/{event_id}/send_now", {})

    def get(self, event_id: str) -> dict:
        if not isinstance(event_id, str) or not EVENT_ID_RE.fullmatch(event_id):
            return _result(False, error="bad_request", detail="event_id")
        return self._call("GET", f"/v1/crash/{event_id}")

    def test_sms(self, force_dry: bool = False, real: bool = False) -> dict:
        """``POST /v1/test``. Default: as the agent's config (``dry_run``).
        ``force_dry``: only logged on the phone. ``real``: a REAL test SMS
        even while ``dry_run`` is on (the only way to prove sending before
        the crash path leaves test mode) — call it only from a loopback-only,
        rate-limited route after the driver confirmed it on screen."""
        if not isinstance(force_dry, bool) or not isinstance(real, bool) \
                or (force_dry and real):
            return _result(False, error="bad_request", detail="force_dry or real, not both")
        body: dict[str, Any] = {}
        if force_dry:
            body["dry_run"] = True
        elif real:
            body["real_test"] = True
        return self._call("POST", "/v1/test", body)

    def pair(self, code: str, confirm: bool = False) -> dict:
        """``POST /v1/pair {secret}`` signed with the one-time ``code``; the
        answer must be signed with OUR secret. Worker thread only (through
        :meth:`request_pair`): never while the state is ``bad_signature``,
        never when already paired, and after a proven pairing only with
        ``confirm``."""
        if not isinstance(code, str) or not PAIR_CODE_RE.fullmatch(code):
            return _result(False, error="bad_request", detail="code")
        with self._state_lock:
            state, paired = self._state, self._info.get("paired")
        if state == "ok" and paired is True:
            return _result(False, error="already_paired")
        if state == "bad_signature":
            # Something else answers on the forward: it would get the secret.
            log.warning("Car phone agent: pairing refused — the last answer on the "
                        "agent forward was not from the agent")
            return _result(False, error="untrusted")
        if self._client is None:
            return _result(False, error="no_secret")
        if self._client.proven and not confirm:
            return _result(False, error="confirm_needed")
        secret = _cfg_get(self._config, SECRET_PATH)
        secret = secret.strip().lower() if isinstance(secret, str) else ""
        res = self._call("POST", "/v1/pair", {"secret": secret},
                         sign_key=code.encode("ascii"))
        if res["ok"]:
            log.info("Car phone agent: paired")
            with self._state_lock:
                self._info.update(paired=True, pairing=False, last_ok_ts=self._wall())
            self._delay = BACKOFF_MIN_S
            self._logged_error = ""
            self._set_state("ok")
            return res
        if res["error"] == "bad_signature":
            return res                  # _note_untrusted already set the state
        reason, why = {
            "pairing_closed": ("pairing_closed", "no PAIRING file on the phone (python "
                                                 "bcm_agent.py --pair in Termux)"),
            "bad_code": ("bad_code", "wrong pairing code"),
            "stale_ts": ("clock_skew", "the phone's clock differs from BCM's"),
            "connect": ("no_answer", res["detail"] or "no answer"),
            "timeout": ("no_answer", res["detail"] or "no answer"),
        }.get(res["error"], ("http", res["detail"] or res["error"]))
        log.warning("Car phone agent: pairing failed — %s", why)
        if reason == "pairing_closed":
            with self._state_lock:
                self._info["pairing"] = False
        with self._state_lock:
            current = self._state
        self._set_state(current if current in ("unpaired", "error") else "error",
                        reason=reason, error=why)
        return res

    # ── publication ───────────────────────────────────────────────────────

    def _set_state(self, state: str, reason: str = "", error: str = "",
                   force: bool = False) -> bool:
        """Publish ``net.car_phone_agent`` on change. True if published.

        Built AND published under ``_pub_lock``: two threads (the worker,
        stop()) can never publish in reverse order, and after stop() only
        its forced ``disabled`` goes out."""
        with self._pub_lock:
            with self._state_lock:
                if self._stop.is_set() and not force:
                    return False
                info = dict(self._info)
                if state == "disabled":
                    info = {k: None for k in info}
                ok_reason = state != "ok" or reason in OK_REASONS
                payload = {"state": state, **{k: info[k] for k in (
                    "paired", "pairing", "version", "sim_ready", "last_ok_ts",
                    "last_sent_ts")},
                    "reason": reason if reason in REASONS and ok_reason else "",
                    "error": clean_error(error) if state not in ("ok", "disabled") else "",
                    "needs_confirm": bool(state not in ("ok", "disabled", "no_secret")
                                          and self._client is not None
                                          and self._client.proven)}
                old = self._payload
                if old is not None:
                    same = {k: v for k, v in old.items() if k != "last_ok_ts"} == \
                        {k: v for k, v in payload.items() if k != "last_ok_ts"}
                    ok_ts = payload["last_ok_ts"]
                    if same and (ok_ts == old["last_ok_ts"] or (
                            ok_ts is not None and self._published_ok_ts is not None
                            and ok_ts - self._published_ok_ts < LAST_OK_REPUBLISH_S)):
                        return False
                if old is None or old["state"] != state:
                    self._since = self._wall()
                    if state not in ("error", "bad_signature"):
                        log.info("Car phone agent: %s -> %s", self._state, state)
                self._state = state
                self._payload = payload
                self._published_ok_ts = payload["last_ok_ts"]
                out = dict(payload, since=self._since)
            try:
                self._bus.publish(TOPIC, out)
            except Exception:
                log.exception("Publishing %s failed", TOPIC)
            return True


# ── the running instance (for the pair route and later modules) ──────────

_INSTANCE: Optional[CarPhoneAgent] = None
_INSTANCE_LOCK = threading.Lock()


def get_agent() -> Optional[CarPhoneAgent]:
    """The running module, or None (not enabled, not started, stopped).
    Call its API from your own worker thread — never the bus dispatcher."""
    with _INSTANCE_LOCK:
        return _INSTANCE


def start_car_phone_agent(config, event_bus, hal=None, **kwargs) -> CarPhoneAgent:
    """Module entry point (``modules.car_phone_agent``): builds the object,
    registers it for :func:`get_agent` and starts its one daemon thread;
    every request happens there (or on the caller's worker thread for the
    API)."""
    global _INSTANCE
    agent = CarPhoneAgent(config, event_bus, state_path=STATE_FILE)
    with _INSTANCE_LOCK:
        _INSTANCE = agent
    agent.start()
    return agent
