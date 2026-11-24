"""Traccar: the car's position on the owner's own Traccar server — BCM's side.

Why it is built this way
------------------------
BCM is off while the car is parked (the test car has no buffered power), so
the positions are sent by the PHONE: the Termux agent
(tools/car_phone/termux/bcm_agent.py, ``TraccarReporter``, agent >= 1.6.0)
reports over HTTPS with the OsmAnd protocol to ``traccar.url``
(docs/TRACCAR_SERWER.md): every ``drive_interval_s`` while BCM talks to it,
once at park time and every ``park_interval_min`` on a parked car, at once
on a parking guard / cabin alarm, with an offline queue on the phone.

What BCM does here — it never talks to the Traccar server itself:

* **Settings for the phone** (:func:`traccar_settings`): ``traccar.url``
  (https only, at most :data:`URL_MAX` characters, no user name/password,
  no query — :func:`url_error`, the same rules as the agent's
  ``traccar_url_error``), the device id from ``/etc/bcm/bcm.env``
  (``BCM_TRACCAR_DEVICE_ID`` → ``traccar.device_id`` through
  ``SECRET_ENV_MAP``; :data:`DEVICE_ID_RE`), ``drive_interval_s``
  (10–600, default 30) and ``park_interval_min`` (5–240, default 15).
  car_phone_agent pushes them as ``traccar_*`` with the toggle
  ``traccar`` — ONLY while ``modules.traccar`` is on (an agent before 1.6.0
  does not know them; with the module off the config and its hash are
  exactly what they were). A bad URL or id is dropped with one warning
  (the phone then sends nothing — "nie skonfigurowany" in the row).
* **The Settings row "Traccar"** (``traccar.state``, on change): what the
  phone's last signed health answer said (mode, last sent point, queue
  length, last error CLASS, the device id's 8-character fingerprint) and
  whether BCM's own settings are complete. The device id itself is never
  logged, published or sent to the browser — only ``id_set`` and the
  fingerprint (so "the phone holds a different id" is visible).
* **"Wyślij pozycję teraz"** (:meth:`Traccar.request_send`, from
  web_viewer's loopback-only, rate-limited route): queued for this module's
  worker, which sends a signed ``POST /v1/traccar/send`` with BCM's own
  fresh GPS fix (``gps.position``, at most :data:`FIX_MAX_AGE_S` old) or
  ``{}`` (the phone measures itself). The outcome shows in the row.

Why the URL is not editable on the Settings screen: ``POST /api/config`` is
reachable from the network in ``remote_access: full``, and a changed URL
would send the device id and every position to a foreign server — so it
lives in ``config/local.yaml`` (root-owned on the car) only.

The module requires ``car_phone_agent``; without a running agent it still
starts, shows "brak agenta" and warns once.

Published ``traccar.state``::

    {url_ok, url_host, id_set, id_fp, agent: {...} | None, cmd | None, error}

    agent: the phone's view (enabled, configured, id_fp, mode drive|park,
           queue_n, last_sent_ts, last_ok_ts, last_error, last_http,
           dropped, paused_low_battery) — None before a signed answer
    cmd:   {state: pending|sent|failed, error, ts} of "Wyślij teraz"
    error: '' | no_agent | agent_outdated
"""

from __future__ import annotations

import hashlib
import math
import queue
import re
import threading
import time
from typing import Any, Callable, Optional
from urllib.parse import urlsplit

from src.core.logger import get_logger
from src.network._proc import _cfg_get

log = get_logger("network.traccar")

TOPIC_STATE = "traccar.state"
DEVICE_ID_PATH = "traccar.device_id"
DEVICE_ID_ENV = "BCM_TRACCAR_DEVICE_ID"
URL_MAX = 200
#: The agent's ranges (bcm_agent.py TRACCAR_DRIVE_RANGE / TRACCAR_PARK_RANGE).
DRIVE_S = (30, 10, 600)
PARK_MIN = (15, 5, 240)
#: Letters, digits and ``. _ -`` (no URL encoding needed), at least 8 — the
#: id is the only protection of the OsmAnd protocol (docs/TRACCAR_SERWER §5).
DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
_PATH_RE = re.compile(r"^[A-Za-z0-9._~/-]{0,150}$")
_HOST_RE = re.compile(r"^[A-Za-z0-9.-]{1,253}$")
#: The phone's view: mode and error classes (bcm_agent.py TRACCAR_ERRORS).
MODES = ("drive", "park")
AGENT_ERRORS = ("", "tls", "dns", "connect", "timeout", "redirect", "http_4xx", "http_5xx",
                "unknown_device", "no_position", "storage", "network")
ERRORS = ("", "no_agent", "agent_outdated")
CMD_STATES = ("pending", "sent", "failed")
#: BCM's GPS fix sent with "Wyślij teraz" only when at most this old.
FIX_MAX_AGE_S = 30.0
POLL_S = 10.0
QUEUE_MAX = 4
TS_MIN = 1_600_000_000
TS_MAX = 4_000_000_000


# ── pure helpers (also used by car_phone_agent's config push) ─────────────

def url_error(url: Any) -> str:
    """"" for a valid server URL, else why — the agent's
    ``traccar_url_error`` rules: ``https://host[:port]/path`` without a
    query, fragment or credentials, printable ASCII, at most
    :data:`URL_MAX` characters; ``http://`` only for 127.0.0.1 (tests)."""
    if not isinstance(url, str) or not url or len(url) > URL_MAX:
        return f"1-{URL_MAX} characters"
    if url != url.strip() or any(ord(ch) < 33 or ord(ch) > 126 for ch in url):
        return "printable ASCII without spaces"
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return "not a valid URL"
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        return "no user name or password in the URL"
    if parts.query or parts.fragment or "?" in url or "#" in url:
        return "no query or fragment"
    host = parts.hostname or ""
    if not _HOST_RE.fullmatch(host) or host.startswith(".") or ".." in host:
        return "a host name is required"
    if parts.scheme == "http":
        if host != "127.0.0.1":
            return "https only (http:// only for 127.0.0.1)"
    elif parts.scheme != "https":
        return "https only"
    if port is not None and not 1 <= port <= 65535:
        return "bad port"
    if not _PATH_RE.fullmatch(parts.path):
        return "path: letters, digits and . _ ~ / - only"
    return ""


def fingerprint(device_id: Any) -> str:
    """8 hex characters of SHA-256 — the same as the agent's
    ``traccar_fingerprint``; the id itself is never shown or logged."""
    if not isinstance(device_id, str) or not device_id:
        return ""
    return hashlib.sha256(device_id.encode("utf-8")).hexdigest()[:8]


def _url_and_id(config: Any) -> tuple[str, str, str, str]:
    """``(url, url_problem, device_id, id_problem)`` — "" where valid."""
    raw = _cfg_get(config, "traccar.url", "")
    url = raw.strip() if isinstance(raw, str) else ""
    url_problem = "missing" if not url else url_error(url)
    raw_id = _cfg_get(config, DEVICE_ID_PATH, "")
    dev = raw_id.strip() if isinstance(raw_id, str) else ""
    id_problem = "missing" if not dev else ("" if DEVICE_ID_RE.fullmatch(dev) else "format")
    return url, url_problem, dev, id_problem


def _clamp(raw: Any, limits: tuple) -> tuple[int, bool]:
    default, lo, hi = limits
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) \
            or (isinstance(raw, float) and not math.isfinite(raw)):
        return default, raw is None
    value = int(round(min(max(raw, lo), hi)))
    return value, value == raw


def traccar_settings(config: Any, warn: Optional[Callable[[str, str], None]] = None) -> dict:
    """``traccar.*`` + the device id → the agent's ``traccar_*`` keys in its
    canonical form (the config hashes on both sides must match). An invalid
    URL or id becomes "" (the phone then sends nothing) with ``warn(key,
    message)`` — the message never contains the id or the URL (the URL may
    carry a typo'd secret)."""
    def _warn(key: str, msg: str) -> None:
        if warn is not None:
            warn(key, msg)

    url, url_problem, dev, id_problem = _url_and_id(config)
    if url_problem:
        _warn("traccar_url", "traccar.url " + ("is not set" if url_problem == "missing"
                                               else f"is invalid ({url_problem})")
              + " — the phone sends no positions")
        url = ""
    if id_problem:
        _warn("traccar_device_id",
              f"{DEVICE_ID_ENV} " + ("is not set in /etc/bcm/bcm.env" if id_problem == "missing"
                                     else "is not 8-64 characters A-Z a-z 0-9 . _ -")
              + " — the phone sends no positions")
        dev = ""
    drive, ok = _clamp(_cfg_get(config, "traccar.drive_interval_s", None), DRIVE_S)
    if not ok:
        _warn("traccar_drive", f"traccar.drive_interval_s: {DRIVE_S[1]}..{DRIVE_S[2]} — "
                               f"using {drive}")
    park, ok = _clamp(_cfg_get(config, "traccar.park_interval_min", None), PARK_MIN)
    if not ok:
        _warn("traccar_park", f"traccar.park_interval_min: {PARK_MIN[1]}..{PARK_MIN[2]} — "
                              f"using {park}")
    return {"traccar_url": url, "traccar_device_id": dev,
            "traccar_drive_interval_s": drive, "traccar_park_interval_min": park}


def _ts(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or not TS_MIN <= value <= TS_MAX:
        return None
    return int(value)


def _small(value: Any, hi: int) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= hi:
        return None
    return value


def parse_agent_view(obj: Any) -> Optional[dict[str, Any]]:
    """The ``traccar`` object of a signed ``/v1/health`` answer, checked
    field by field (authentic, but a newer or broken agent must not hand
    the browser a surprise). None when it is not one (an older agent)."""
    if not isinstance(obj, dict) or not isinstance(obj.get("enabled"), bool):
        return None
    fp = obj.get("id_fp")
    err = obj.get("last_error")
    return {
        "enabled": obj["enabled"],
        "configured": obj.get("configured") is True,
        "id_fp": fp if isinstance(fp, str) and re.fullmatch(r"[0-9a-f]{8}", fp) else "",
        "mode": obj.get("mode") if obj.get("mode") in MODES else None,
        "queue_n": _small(obj.get("queue_n"), 100000),
        "last_sent_ts": _ts(obj.get("last_sent_ts")),
        "last_ok_ts": _ts(obj.get("last_ok_ts")),
        "last_error": err if err in AGENT_ERRORS else "",
        "last_http": _small(obj.get("last_http"), 599),
        "dropped": _small(obj.get("dropped"), 10**9),
        "paused_low_battery": obj.get("paused_low_battery") is True,
    }


def _fix_body(fix: Any, now_wall: float) -> dict:
    """BCM's ``gps.position`` → the ``/v1/traccar/send`` body ({} when not
    fresh or not plausible — the phone measures itself then)."""
    if not isinstance(fix, dict) or fix.get("fix") is False:
        return {}
    lat, lon = fix.get("lat"), fix.get("lon")
    ts = fix.get("_wall")
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
               for v in (lat, lon, ts)):
        return {}
    if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0) \
            or not 0 <= now_wall - ts <= FIX_MAX_AGE_S:
        return {}
    body: dict[str, Any] = {"lat": round(float(lat), 6), "lon": round(float(lon), 6)}
    for src, dst, hi in (("speed", "speed_kmh", 400), ("heading", "heading", 360)):
        v = fix.get(src)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) \
                and 0 <= v <= hi:
            body[dst] = round(float(v), 1)
    return body


# ── the module ────────────────────────────────────────────────────────────

def _default_agent() -> Any:
    # Lazy: car_phone_agent imports this module for the config push.
    from src.network import car_phone_agent
    return car_phone_agent.get_agent()


class Traccar:
    """See the module docstring.

    Args:
        config: BCMConfig or nested dict.
        event_bus: EventBus.
        agent_getter: returns the running CarPhoneAgent or None.
        clock / wall: monotonic and wall seconds (tests pass fakes).
    """

    def __init__(self, config: Any, event_bus: Any,
                 agent_getter: Optional[Callable[[], Any]] = None,
                 clock: Callable[[], float] = time.monotonic,
                 wall: Callable[[], float] = time.time) -> None:
        self._config = config
        self._bus = event_bus
        self._agent_getter = agent_getter or _default_agent
        self._clock = clock
        self._wall = wall
        self._q: queue.Queue = queue.Queue(maxsize=QUEUE_MAX)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._subscribed = False
        self._fix: Optional[dict] = None
        self._send_pending = False
        self._cmd: Optional[dict[str, Any]] = None
        self._published: Optional[dict[str, Any]] = None
        url, url_problem, dev, id_problem = _url_and_id(config)
        self._url_ok = not url_problem
        self._url_host = (urlsplit(url).hostname or "") if self._url_ok else ""
        self._id_set = not id_problem
        self._id_fp = fingerprint(dev) if self._id_set else ""

    # ── lifecycle ─────────────────────────────────────────────────────────

    def _subscriptions(self) -> tuple:
        return (("gps.position", self._on_position),
                ("power.shutting_down", self._on_shutdown))

    def start(self) -> None:
        """Subscribe and start the worker; no I/O here."""
        if not self._url_ok or not self._id_set:
            # One line at start (names only) — the row says the same.
            log.warning("Traccar: %s%s%s — the phone sends no positions until fixed "
                        "(docs/TRACCAR_SERWER.md §8)",
                        "" if self._url_ok else "traccar.url missing or invalid",
                        "" if self._url_ok or self._id_set else ", ",
                        "" if self._id_set else f"{DEVICE_ID_ENV} missing or invalid")
        if not self._subscribed:
            self._subscribed = True
            for topic, cb in self._subscriptions():
                self._bus.subscribe(topic, cb)
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, daemon=True, name="traccar")
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

    def _on_position(self, topic: str, value: Any, timestamp: float) -> None:
        """Dispatcher: remember the fix (no I/O)."""
        if isinstance(value, dict):
            with self._lock:
                self._fix = dict(value, _wall=self._wall())

    def _kick(self) -> None:
        try:
            self._q.put_nowait(True)
        except queue.Full:
            pass

    # ── "Wyślij pozycję teraz" (web route; any thread) ────────────────────

    def request_send(self) -> dict:
        """Queue one "send now" for the worker. ``{"ok": False, "error":
        "busy"}`` while one is still pending, ``not_configured`` when BCM's
        own settings are incomplete."""
        if not self._url_ok or not self._id_set:
            return {"ok": False, "error": "not_configured"}
        with self._lock:
            if self._send_pending:
                return {"ok": False, "error": "busy"}
            self._send_pending = True
            self._cmd = {"state": "pending", "error": "", "ts": int(self._wall())}
        self._kick()
        return {"ok": True}

    # ── worker ────────────────────────────────────────────────────────────

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.step()
            except Exception:
                log.exception("Traccar: worker pass failed")
            try:
                self._q.get(timeout=POLL_S)
            except queue.Empty:
                pass

    def _agent(self) -> Any:
        try:
            return self._agent_getter()
        except Exception:
            return None

    def step(self) -> None:
        """A pending "send now", then the row from the agent's facts."""
        with self._lock:
            pending = self._send_pending
            fix = dict(self._fix) if self._fix is not None else None
        if pending:
            self._send(fix)
        self._publish()

    def _send(self, fix: Optional[dict]) -> None:
        agent = self._agent()
        if agent is None:
            res: dict = {"ok": False, "error": "no_agent"}
        else:
            try:
                res = agent.traccar_send(_fix_body(fix, self._wall()))
            except Exception:
                log.exception("Traccar: send request failed")
                res = {"ok": False, "error": "internal"}
        err = res.get("error") if isinstance(res.get("error"), str) else ""
        if res.get("ok"):
            state, err = "sent", ""
            log.info("Traccar: 'send now' accepted by the phone")
        else:
            state = "failed"
            if err == "not_found":
                err = "agent_outdated"
            log.warning("Traccar: 'send now' refused (%s)", err or "error")
        with self._lock:
            self._send_pending = False
            self._cmd = {"state": state, "error": re.sub(r"[^a-z0-9_]", "", err)[:32],
                         "ts": int(self._wall())}

    def payload(self) -> dict[str, Any]:
        agent = self._agent()
        view = None
        error = ""
        if agent is None:
            error = "no_agent"
        else:
            try:
                facts = agent.health_facts()
            except Exception:
                facts = {}
            view = facts.get("traccar") if isinstance(facts, dict) else None
            version = None
            try:
                state = agent.state
                version = state.get("version") if isinstance(state, dict) else None
            except Exception:
                pass
            if view is None and isinstance(version, str):
                error = "agent_outdated"
        with self._lock:
            cmd = dict(self._cmd) if self._cmd is not None else None
        return {"url_ok": self._url_ok, "url_host": self._url_host, "id_set": self._id_set,
                "id_fp": self._id_fp, "agent": dict(view) if isinstance(view, dict) else None,
                "cmd": cmd, "error": error}

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


_INSTANCE: Optional[Traccar] = None
_INSTANCE_LOCK = threading.Lock()


def get_traccar() -> Optional[Traccar]:
    """The running module, or None (not enabled, not started, stopped)."""
    with _INSTANCE_LOCK:
        return _INSTANCE


def start_traccar(config, event_bus, hal=None, **kwargs) -> Traccar:
    """Module entry point (``modules.traccar``): builds the object,
    subscribes and starts its one daemon thread."""
    global _INSTANCE
    module = Traccar(config, event_bus)
    with _INSTANCE_LOCK:
        _INSTANCE = module
    module.start()
    return module
