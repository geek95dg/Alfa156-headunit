"""Does the head unit actually have internet? One small, shared probe.

Why this exists
---------------
``car_phone`` (USB tethering) and ``phone_tether`` (Bluetooth PAN) used to
say "connected" as soon as NetworkManager had the profile active with an
address. That only proves the cable/radio link to the PHONE — not that the
phone passes traffic on: mobile data switched off, an operator that blocks
tethering, or another interface with a lower route metric (a Wi-Fi network
without internet, an Ethernet cable) holding the default route all look
exactly the same from there. The driver then saw "connected" while weather,
route planning and the clock silently failed.

What one probe does (:func:`probe_internet`), each step with a short timeout
and never through a shell:

1. ``ip -4 route get 1.1.1.1`` (argv list) — which interface holds the
   default route right now (``iface``); no route = ``no_route``. The address
   is only used for the kernel's route lookup, nothing is sent to it.
2. DNS: ``getaddrinfo("api.openweathermap.org")`` in a helper thread with a
   timeout (``getaddrinfo`` itself has none) — ``dns``.
3. HTTPS: one ``HEAD`` to a neutral connectivity endpoint (no key, no
   personal data). ANY HTTP answer counts — a 404 still proves DNS, TCP and
   TLS work; only no answer / a TLS failure is ``https``.

Result: ``{ok, iface, dns_ok, https_ok, error, detail, checked_at}`` —
``error`` is one of :data:`ERRORS` (the UI translates it), ``detail`` is a
cleaned one-line text for the log/diagnostics, never anything secret.

:class:`InternetProbe` adds the rate limit: at most one probe per
:data:`MIN_INTERVAL_S` (60 s); ``force`` (a fresh "connected" edge, the
Settings "Test" button) still waits :data:`FORCE_FLOOR_S` since the last
one. It is shared (:func:`shared_probe`) — car_phone and phone_tether ask
the same question, and the answer does not depend on who asks. It blocks for
up to a few seconds, so it is only ever called from a worker thread (the
modules' own loops, the web route's worker), never on the event bus.
"""

from __future__ import annotations

import re
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Optional

from src.core.logger import get_logger
from src.network._proc import IFACE_RE, _run, clean_error

log = get_logger("network.net_probe")

#: Address used only for the kernel's route lookup (``ip route get``).
ROUTE_TARGET = "1.1.1.1"
#: Host whose name must resolve — the service BCM needs most often.
DNS_HOST = "api.openweathermap.org"
#: Neutral HTTPS endpoint (answers 204 with an empty body, no cookies).
HTTPS_URL = "https://www.gstatic.com/generate_204"
#: Timeout of each step (seconds).
STEP_TIMEOUT_S = 5.0
#: At most one probe per this many seconds (cached result in between).
MIN_INTERVAL_S = 60.0
#: Even a forced probe waits this long since the previous one.
FORCE_FLOOR_S = 5.0
#: ``error`` values ('' = internet works).
ERRORS = ("", "no_route", "dns", "https")

_DEV_RE = re.compile(r"\bdev\s+(\S+)")
_VIA_RE = re.compile(r"\bvia\s+(\d{1,3}(?:\.\d{1,3}){3})\b")


def parse_route_get(text: str) -> Optional[dict[str, str]]:
    """``ip -4 route get`` output → ``{iface, gateway}`` or None.

    ``1.1.1.1 via 192.168.42.129 dev rndis0 src 192.168.42.10 uid 0``.
    The interface name is validated (it reaches the UI); a missing or
    malformed ``dev`` means no usable route.
    """
    first = (text or "").strip().splitlines()
    if not first:
        return None
    line = first[0]
    m = _DEV_RE.search(line)
    if not m or not IFACE_RE.fullmatch(m.group(1)):
        return None
    via = _VIA_RE.search(line)
    return {"iface": m.group(1), "gateway": via.group(1) if via else ""}


def default_resolver(host: str, timeout: float) -> tuple[bool, str]:
    """Resolve ``host`` within ``timeout`` s. ``(ok, error text)``.

    ``getaddrinfo`` has no timeout of its own (glibc retries for up to
    ~30 s with a dead resolver), so it runs in a daemon thread and we stop
    waiting after ``timeout``; the thread finishes on its own later.
    """
    box: dict[str, Any] = {}

    def work() -> None:
        try:
            box["ok"] = bool(socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP))
        except Exception as e:      # gaierror, UnicodeError …
            box["err"] = str(e)

    t = threading.Thread(target=work, daemon=True, name="net-probe-dns")
    t.start()
    t.join(timeout)
    if t.is_alive():
        return False, f"DNS timeout after {int(timeout)} s"
    if box.get("ok"):
        return True, ""
    return False, box.get("err", "no address")


def default_https(url: str, timeout: float) -> tuple[bool, Optional[int], str]:
    """One ``HEAD`` request. ``(reached, http status or None, error text)``.

    Any HTTP status counts as reached (TLS and TCP worked)."""
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "BCM/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return True, int(getattr(resp, "status", 200) or 200), ""
    except urllib.error.HTTPError as e:
        return True, int(e.code), ""
    except Exception as e:          # URLError, timeout, ssl.SSLError …
        reason = getattr(e, "reason", None)
        return False, None, str(reason if reason is not None else e)


def probe_internet(runner: Callable[..., Any] = subprocess.run,
                   resolver: Callable[[str, float], tuple[bool, str]] = default_resolver,
                   https: Callable[[str, float], tuple[bool, Optional[int], str]] = default_https,
                   wall_clock: Callable[[], float] = time.time,
                   timeout: float = STEP_TIMEOUT_S) -> dict[str, Any]:
    """Run the three steps (module docstring). Never raises."""
    result: dict[str, Any] = {"ok": False, "iface": "", "dns_ok": False,
                              "https_ok": False, "error": "", "detail": "",
                              "checked_at": wall_clock()}
    rc, out, err = _run(runner, ["ip", "-4", "route", "get", ROUTE_TARGET], timeout)
    route = parse_route_get(out) if rc == 0 else None
    if route is None:
        result["error"] = "no_route"
        result["detail"] = clean_error(err or "no default route")
        return result
    result["iface"] = route["iface"]
    try:
        dns_ok, dns_err = resolver(DNS_HOST, timeout)
    except Exception as e:
        dns_ok, dns_err = False, str(e)
    result["dns_ok"] = bool(dns_ok)
    if not dns_ok:
        result["error"] = "dns"
        result["detail"] = clean_error(dns_err or "DNS failed")
        return result
    try:
        reached, _code, https_err = https(HTTPS_URL, timeout)
    except Exception as e:
        reached, https_err = False, str(e)
    result["https_ok"] = bool(reached)
    if not reached:
        result["error"] = "https"
        result["detail"] = clean_error(https_err or "HTTPS failed")
        return result
    result["ok"] = True
    return result


class InternetProbe:
    """Rate-limited, thread-safe wrapper around :func:`probe_internet`.

    ``check()`` returns the cached result when the last probe is younger
    than ``min_interval`` (``force``: younger than ``force_floor``). One
    probe runs at a time, but nobody waits for it: a second caller gets
    the cached result (or a ``pending`` "unknown" one) at once.

    Two locks on purpose: ``last`` is read by the dashboard broadcast loop
    ~15×/s, and a probe on a phone WITHOUT internet takes up to 2×5 s
    (DNS + HTTPS timeouts) — one lock for both froze the whole dashboard
    stream for that long. ``_state_lock`` guards only the cached fields and
    is held for microseconds; ``_probe_lock`` serialises the slow probe.
    """

    def __init__(self, probe: Optional[Callable[[], dict[str, Any]]] = None,
                 clock: Callable[[], float] = time.monotonic,
                 min_interval: float = MIN_INTERVAL_S,
                 force_floor: float = FORCE_FLOOR_S) -> None:
        self._probe = probe or probe_internet
        self._clock = clock
        self._min = float(min_interval)
        self._floor = float(force_floor)
        self._state_lock = threading.Lock()
        self._probe_lock = threading.Lock()
        self._last: Optional[dict[str, Any]] = None
        self._last_at: Optional[float] = None
        self._logged: Optional[tuple] = None

    @property
    def last(self) -> Optional[dict[str, Any]]:
        """The last result (copy) or None — never probes, never waits."""
        with self._state_lock:
            return dict(self._last) if self._last is not None else None

    def _cached(self, age_limit: float) -> Optional[dict[str, Any]]:
        with self._state_lock:
            if self._last is not None and self._last_at is not None \
                    and self._clock() - self._last_at < age_limit:
                return dict(self._last)
        return None

    def check(self, force: bool = False) -> dict[str, Any]:
        """The current answer, probing when the cached one is too old."""
        age_limit = self._floor if force else self._min
        cached = self._cached(age_limit)
        if cached is not None:
            return cached
        if not self._probe_lock.acquire(blocking=False):
            # Another thread is probing right now — do not wait for it.
            last = self.last
            if last is not None:
                return last
            return {"ok": False, "iface": "", "dns_ok": False, "https_ok": False,
                    "error": "", "detail": "probe in progress", "pending": True,
                    "checked_at": time.time()}
        try:
            # Another probe may have finished between the check and acquire.
            cached = self._cached(age_limit)
            if cached is not None:
                return cached
            try:
                res = self._probe()
            except Exception as e:      # a broken seam must not kill a worker
                res = {"ok": False, "iface": "", "dns_ok": False, "https_ok": False,
                       "error": "no_route", "detail": clean_error(e),
                       "checked_at": time.time()}
            res = dict(res)
            res.pop("pending", None)
            if res.get("error") not in ERRORS:
                res["error"] = "no_route" if not res.get("ok") else ""
            with self._state_lock:
                self._last = dict(res)
                self._last_at = self._clock()
                key = (res.get("ok"), res.get("iface"), res.get("error"))
                changed = key != self._logged
                if changed:
                    self._logged = key
            if changed:
                if res.get("ok"):
                    log.info("Internet probe: OK (default route via %s)", res.get("iface") or "-")
                else:
                    log.warning("Internet probe: NO internet — %s (%s; default route via %s)",
                                res.get("error"), res.get("detail") or "-",
                                res.get("iface") or "none")
            return dict(res)
        finally:
            self._probe_lock.release()


_shared_lock = threading.Lock()
_shared: Optional[InternetProbe] = None


def shared_probe() -> InternetProbe:
    """The process-wide probe (car_phone, phone_tether and /api/net/test)."""
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = InternetProbe()
        return _shared


def internet_fields(probe: Optional[InternetProbe], link_iface: str,
                    force: bool = False) -> dict[str, Any]:
    """What a "connected" uplink module adds to its state.

    ``{internet, route_iface, internet_error, hint}`` — ``internet`` None
    when no probe is configured (unknown, the UI shows nothing).
    ``hint``: ``no_internet`` (the default route IS this link, or there is
    none — the phone does not pass traffic on) or ``route_other`` (another
    interface holds the default route and that one has no internet).
    """
    if probe is None:
        return {"internet": None, "route_iface": "", "internet_error": "", "hint": ""}
    res = probe.check(force=force)
    if res.get("pending"):
        # First probe still running in another thread — unknown, not "no".
        return {"internet": None, "route_iface": "", "internet_error": "", "hint": ""}
    route_iface = res.get("iface") or ""
    if not isinstance(route_iface, str) or not IFACE_RE.fullmatch(route_iface):
        route_iface = ""
    ok = bool(res.get("ok"))
    hint = ""
    if not ok:
        hint = "route_other" if route_iface and link_iface and route_iface != link_iface \
            else "no_internet"
    err = res.get("error")
    return {"internet": ok, "route_iface": route_iface,
            "internet_error": err if err in ERRORS else "", "hint": hint}
