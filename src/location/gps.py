"""GPS/GNSS — NMEA from a serial receiver, from the phone (UDP/TCP) or a demo.

Why it looks like this
----------------------
The test car has no GPS receiver, but the phone is always there: an app
such as *GPSd Forwarder* (F-Droid) sends the phone's NMEA sentences as UDP
datagrams to the head unit (``10.0.0.1:10110`` over the Android Auto Wi-Fi
Direct link), and an "NMEA TCP server" app can serve them over Bluetooth
PAN as a fallback. A real UART receiver (NEO-6M/M8N, also a Bluetooth GPS
mouse on ``/dev/rfcomm0``) remains supported.

Sources — ``hardware.gps.source``
---------------------------------
``auto`` (default — also what production ``bcm_config.yaml`` gets, it has no
``source`` key) keeps the legacy behaviour: x86 → demo route through Milan;
anything else → serial, and when the port cannot be opened at start-up the
legacy fallback to the demo route (now logged at WARNING). ``demo``,
``serial``, ``udp``, ``tcp`` select one input; a list (``[udp, tcp]``) runs
every listed input concurrently, all feeding ONE parser under one lock.
An explicit ``serial`` never falls back to demo — it reconnects with backoff
instead (a fake position is worse than none).

Other keys (code defaults in :data:`DEFAULTS`): ``port`` / ``baudrate``
(serial), ``stale_sec`` (no valid fix for that long ⇒ ``gps.fix`` False),
``require_checksum``, ``udp.{bind, port, allowed_sources, max_datagram}``,
``tcp.{host, port, connect_timeout, backoff_max_sec}``.

Published (only VALID fixes — a receiver without a fix used to publish 0,0,
which put the car in the Gulf of Guinea for weather/trip/tracker)::

    gps.position   {lat, lon, alt, altitude, speed (km/h), heading,
                    satellites, fix: True, time_utc, source}
    gps.lat / gps.lon / gps.speed / gps.heading / gps.satellites / gps.time_utc
    gps.fix        True when a fix is acquired; False exactly once after
                   ``stale_sec`` without a valid fix (never republished
                   while it stays lost)
    gps.source_state  {source, state, peer, last_ts, inputs: [...]} every 10 s

``speed``/``heading``/``alt``/``time_utc`` are ``None`` when the sentence
carrying them (RMC/VTG resp. GGA resp. RMC) is missing or older than
``stale_sec``; ``gps.speed``/``gps.heading``/``gps.time_utc`` are then NOT
published. Losing the fix publishes no speed at all — publishing 0 would
look like an 80 → 0 km/h drop to camera/crash_detect.py. One nuance for
``heading``: an RMC/VTG with an EMPTY course field (stationary receivers
often omit it) keeps the last course current — the car still points the
same way — but only while the fix lasts. Losing the fix forgets the
course, so one from before an outage is never republished as current.

The system clock is NEVER set from NMEA: the UDP input accepts datagrams
from a whole subnet and UDP source addresses can be spoofed, so anyone
there could move the clock (TLS, logs, trip timestamps). ``time_utc`` is
informational only; the clock comes from bcm-timesync over the internet.

Security of the network inputs: sentences are ASCII-only, at most 128
characters, checksummed (``require_checksum``), with strictly validated
numeric fields; UDP datagrams are accepted only from ``allowed_sources``
(CIDRs and ``pan`` = the subnets of the ``bnep*`` interfaces) and oversize
datagrams are dropped. Only GGA/RMC/VTG lines reach the parser (a cheap
type check comes first, so the 20-40 GSV/GSA lines a multi-GNSS phone
sends per epoch never compete with the lines that carry the fix); those
are capped per source by a token bucket (:data:`RATE_PER_SOURCE`), raw
UDP lines of any kind by a much larger one (:data:`RAW_LINES_PER_SOURCE`,
a CPU bound). The publish rate is bounded too
(:data:`MIN_PUBLISH_INTERVAL_S`), so a flood cannot flood the event bus.
"""

from __future__ import annotations

import ipaddress
import math
import re
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from src.core.logger import get_logger

log = get_logger("location.gps")

#: Input names accepted in ``hardware.gps.source``.
SOURCES = ("demo", "serial", "udp", "tcp")

#: Code defaults for ``hardware.gps`` (the production YAML sets only
#: enabled/port/baudrate, so everything else comes from here).
DEFAULTS: dict[str, Any] = {
    "source": "auto",
    "port": "/dev/ttyUSB0",
    "baudrate": 9600,
    "stale_sec": 5,
    "require_checksum": True,
    "udp": {
        "bind": "0.0.0.0",
        "port": 10110,
        # 10.0.0.0/24 = the Android Auto Wi-Fi Direct group (we are 10.0.0.1),
        # 127/8 = local tests (nc -u, gpsfake), pan = the phone over BT PAN.
        "allowed_sources": ["10.0.0.0/24", "127.0.0.0/8", "pan"],
        # Apps that batch a whole epoch into one datagram send 30+ GSV
        # lines of ~70 bytes (> 2 KiB) with a multi-GNSS phone; anything
        # this size is still bounded by RAW_LINES_PER_SOURCE.
        "max_datagram": 8192,
    },
    "tcp": {
        # pan-gateway = the default gateway of a bnep* interface, i.e. the
        # phone itself when it shares its internet over Bluetooth.
        "host": "pan-gateway",
        "port": 50000,
        "connect_timeout": 5,
        "backoff_max_sec": 60,
        # Optional: first retry delay (tests use a small one).
        "backoff_min_sec": 1,
        # Reconnect when a connected server sends nothing for this long.
        "idle_timeout_sec": 30,
    },
}

#: NMEA 0183 says 82 characters; NMEA 4.x receivers and phones exceed it a
#: little. Anything longer is not a sentence we want.
MAX_LINE = 128
#: GPS, multi-GNSS, GLONASS, Galileo, BeiDou (both spellings), QZSS.
TALKERS = frozenset({"GP", "GN", "GL", "GA", "BD", "GB", "GQ"})
KNOT_KMH = 1.852
#: RMC dates outside this range are a receiver bug (GPS week rollover puts
#: old receivers in 1999/2006) — the position stays, time_utc is dropped.
MIN_YEAR = 2020
MAX_YEAR = 2099
#: GGA fix quality accepted: 1 GPS, 2 DGPS, 3 PPS, 4 RTK, 5 float RTK,
#: 6 dead reckoning (tunnels). 0 = no fix, 7 = manual input, 8 = simulator.
GGA_VALID_QUALITY = frozenset({1, 2, 3, 4, 5, 6})
#: RMC/VTG mode indicator (NMEA 2.3+): N no fix, M manual, S simulator.
INVALID_MODES = frozenset({"N", "M", "S"})
#: Sanity limits — a value outside is treated as "not reported".
MAX_SPEED_KMH = 1000.0
MIN_ALT_M, MAX_ALT_M = -1000.0, 20000.0

#: At most one gps.position publication per this many seconds (a fix is
#: still recorded for staleness). RMC and GGA of one epoch arrive ms apart;
#: this merges them into one publication and bounds the bus load whatever
#: the input rate (10 Hz receivers, two sources at once, a flood).
MIN_PUBLISH_INTERVAL_S = 0.5
#: Manager tick (stale check) and gps.source_state period.
TICK_S = 0.5
SOURCE_STATE_EVERY_S = 10.0
#: Sentence types the parser uses (``$ttXXX`` → ``XXX``). Every other
#: line (GSV, GSA, GLL, ZDA, proprietary ``$P…``) is dropped by a slice
#: compare BEFORE any rate accounting: phones reporting several
#: constellations send 20-40 GSV/GSA lines per epoch, RMC/GGA often last,
#: and counting those used to starve every other fix.
WANTED_TYPES = (b"GGA", b"RMC", b"VTG")
#: Per-source token bucket for WANTED_TYPES lines: refill per second and
#: burst. A 10 Hz receiver sending RMC+GGA+VTG needs 30/s.
RATE_PER_SOURCE = 50
#: Per-source token bucket for raw UDP lines of any type — only a CPU
#: bound against a flood from an allowed address (a whole datagram is
#: dropped unsplit once it is exceeded). A multi-GNSS phone at 5 Hz sends
#: ~200 lines/s; a 2048-byte datagram holds fewer than 300 sentences.
RAW_LINES_PER_SOURCE = 500
#: While the TCP input waits for a Bluetooth PAN gateway it re-reads
#: /proc/net/route this often (at most) — PAN down is not a failure, so
#: the exponential backoff must not grow meanwhile.
PAN_POLL_S = 5.0
#: ``pan`` subnets are re-read from ``ip`` at most this often (and an
#: empty answer after :data:`PAN_CACHE_EMPTY_S`, so a fresh PAN link is
#: picked up quickly).
PAN_CACHE_S = 30.0
PAN_CACHE_EMPTY_S = 5.0
#: Narrower than this is not a phone's PAN subnet (Android /24, iOS /28) —
#: never let a mis-configured bnep turn "pan" into "the whole internet".
PAN_MIN_PREFIX = 16
#: Log lines about rejected sources: at most one per source per this long.
LOG_EVERY_S = 60.0

IP_ADDR_ARGV = ["ip", "-o", "-4", "addr", "show"]
PROC_NET_ROUTE = "/proc/net/route"
RTF_UP = 0x0001
RTF_GATEWAY = 0x0002

_NUM_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$")
_INT_RE = re.compile(r"^\d{1,3}$")
# Degrees then two-digit minutes with a mandatory fractional part: a
# coordinate without a dot is ambiguous (truncated / not NMEA) and rejected.
_LAT_RE = re.compile(r"^(\d{1,2})(\d{2}\.\d{1,10})$")
_LON_RE = re.compile(r"^(\d{1,3})(\d{2}\.\d{1,10})$")
_TIME_RE = re.compile(r"^(\d{2})(\d{2})(\d{2})(?:\.(\d{1,6}))?$")
_DATE_RE = re.compile(r"^(\d{2})(\d{2})(\d{2})$")
_HEX = frozenset("0123456789ABCDEFabcdef")
_HOST_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,252})$")
# Any printable ASCII without spaces under /dev/: the stable names udev
# makes are long and contain ':' (/dev/serial/by-id/usb-u-blox_AG_-_www.
# u-blox.com_u-blox_7_-_GPS_GNSS_Receiver-if00 is 82 characters,
# /dev/serial/by-path/pci-0000:00:14.0-usb-0:2:1.0-port0). The port comes
# from the local config (trusted); this only catches typos and a path
# that would leave /dev ("..", checked by component in _valid_serial_port).
_SERIAL_PORT_RE = re.compile(r"^/dev/[!-~]{1,235}$")


# ── pure helpers (tested directly) ─────────────────────────────────────────

def _num(text: str) -> Optional[float]:
    """Strict decimal → float. Empty → None; anything else raises ValueError.

    ``float()`` alone would accept "nan", "inf", "1e9" and "١٢" — none of
    which is NMEA.
    """
    if text == "":
        return None
    if not _NUM_RE.match(text):
        raise ValueError(f"not a number: {text!r}")
    return float(text)


def _int(text: str) -> Optional[int]:
    if text == "":
        return None
    if not _INT_RE.match(text):
        raise ValueError(f"not a small integer: {text!r}")
    return int(text)


def _coord(text: str, pattern: re.Pattern, limit: float) -> Optional[float]:
    """``DDMM.mmmm`` / ``DDDMM.mmmm`` → decimal degrees (unsigned), or None."""
    m = pattern.match(text)
    if not m:
        return None
    degrees = int(m.group(1))
    minutes = float(m.group(2))
    if minutes >= 60.0:
        return None
    value = degrees + minutes / 60.0
    return value if value <= limit else None


def _position(lat_s: str, ns: str, lon_s: str, ew: str) -> Optional[tuple[float, float]]:
    """Validated signed (lat, lon); S and W are negative. None if invalid."""
    if ns not in ("N", "S") or ew not in ("E", "W"):
        return None
    lat = _coord(lat_s, _LAT_RE, 90.0)
    lon = _coord(lon_s, _LON_RE, 180.0)
    if lat is None or lon is None:
        return None
    if ns == "S":
        lat = -lat
    if ew == "W":
        lon = -lon
    if lat == 0.0 and lon == 0.0:
        # "Null island" is a receiver's placeholder, not a place we drive to.
        return None
    return lat, lon


def _rmc_epoch(time_s: str, date_s: str) -> Optional[float]:
    """RMC ``hhmmss.ss`` + ``ddmmyy`` → UTC epoch seconds, or None."""
    t = _TIME_RE.match(time_s)
    d = _DATE_RE.match(date_s)
    if not t or not d:
        return None
    yy = int(d.group(3))
    # The usual NMEA pivot: 80-99 = 1980-1999 (only a rollover bug or an
    # ancient receiver says so, and the range check below drops it).
    year = 1900 + yy if yy >= 80 else 2000 + yy
    if not MIN_YEAR <= year <= MAX_YEAR:
        return None
    frac = t.group(4) or ""
    micros = int((frac + "000000")[:6]) if frac else 0
    try:
        stamp = datetime(year, int(d.group(2)), int(d.group(1)),
                         int(t.group(1)), int(t.group(2)), int(t.group(3)),
                         micros, tzinfo=timezone.utc)
    except ValueError:      # 31 Feb, hour 25, leap second 60 …
        return None
    return stamp.timestamp()


def _valid_serial_port(port: Any) -> bool:
    """Is ``port`` an absolute path under /dev/ (by-id/by-path names too)?"""
    # fullmatch: re's "$" also matches before a trailing newline.
    return (isinstance(port, str) and bool(_SERIAL_PORT_RE.fullmatch(port))
            and ".." not in port.split("/"))


def _wanted(line: bytes) -> bool:
    """Cheap pre-filter: a ``$ttGGA`` / ``$ttRMC`` / ``$ttVTG`` line?

    Only a slice compare — the parser still validates everything else.
    """
    return len(line) >= 7 and line[3:6] in WANTED_TYPES


def _parse_ip_addr(text: str, prefix: str = "bnep") -> list:
    """IPv4 subnets of ``prefix*`` interfaces from ``ip -o -4 addr show``.

    ``3: bnep0    inet 192.168.44.23/24 brd … scope global dynamic bnep0\\ …``
    """
    nets = []
    for line in (text or "").splitlines():
        fields = line.split()
        if len(fields) < 4:
            continue
        iface = fields[1].split("@", 1)[0]
        if not iface.startswith(prefix):
            continue
        try:
            idx = fields.index("inet")
            net = ipaddress.IPv4Interface(fields[idx + 1]).network
        except (ValueError, IndexError):
            continue
        if net.prefixlen < PAN_MIN_PREFIX:
            log.debug("GPS: ignoring %s subnet %s (wider than /%d)", iface, net, PAN_MIN_PREFIX)
            continue
        if net not in nets:
            nets.append(net)
    return nets


def _parse_proc_net_route(text: str, prefix: str = "bnep") -> Optional[str]:
    """Default gateway of a ``prefix*`` interface from ``/proc/net/route``.

    The kernel prints addresses as the raw 32-bit value in host byte order
    (``012CA8C0`` on x86 = 192.168.44.1). With several bnep default routes
    the lowest metric wins. None when there is none (PAN down).
    """
    best: Optional[tuple[int, str]] = None
    for line in (text or "").splitlines():
        f = line.split()
        if len(f) < 8 or f[0] == "Iface" or not f[0].startswith(prefix):
            continue
        try:
            dest, gateway, flags = int(f[1], 16), int(f[2], 16), int(f[3], 16)
            metric, mask = int(f[6]), int(f[7], 16)
        except ValueError:
            continue
        if dest != 0 or mask != 0 or gateway == 0:
            continue
        if not (flags & RTF_UP and flags & RTF_GATEWAY):
            continue
        if not 0 <= gateway <= 0xFFFFFFFF:
            continue
        addr = str(ipaddress.IPv4Address(gateway.to_bytes(4, sys.byteorder)))
        if best is None or metric < best[0]:
            best = (metric, addr)
    return best[1] if best else None


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


def _number(value: Any, default: float, lo: float, hi: float, name: str) -> float:
    """A finite number within ``[lo, hi]`` (clamped), else ``default``."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or not math.isfinite(value):
        if value is not None:
            log.warning("hardware.gps.%s=%r is not a number — using %s", name, value, default)
        return default
    return min(max(value, lo), hi)


def _resolve_sources(value: Any, platform: str) -> tuple[list[str], bool]:
    """``hardware.gps.source`` → (input names, auto?).

    Accepts a name, a comma-separated string or a list. Unknown names are
    logged and skipped — never replaced by the demo route.
    """
    if value is None or (isinstance(value, str) and value.strip().lower() in ("", "auto")):
        items = ["auto"]
    elif isinstance(value, str):
        items = [v.strip().lower() for v in value.split(",") if v.strip()]
    elif isinstance(value, (list, tuple)):
        items = [v.strip().lower() if isinstance(v, str) else repr(v) for v in value]
    else:
        log.error("hardware.gps.source=%r is neither a name nor a list — no GPS input", value)
        return [], False
    if items == ["auto"]:
        return (["demo"] if platform == "x86" else ["serial"]), True
    out: list[str] = []
    for item in items:
        if item in SOURCES:
            if item not in out:
                out.append(item)
        else:
            log.warning("hardware.gps.source: unknown input %r ignored (use %s, or auto alone)",
                        item, "/".join(SOURCES))
    if not out:
        log.error("hardware.gps.source=%r names no valid input — GPS has no source", value)
    elif "demo" in out and len(out) > 1:
        log.warning("hardware.gps.source mixes the demo route with real inputs %s — "
                    "positions will jump", out)
    return out, False


def _open_serial(port: str, baudrate: int) -> Any:
    """Default serial factory (pyserial). A short timeout keeps stop() quick."""
    import serial  # imported lazily: pyserial is only needed for this input
    return serial.Serial(port, baudrate, timeout=1)


def _read_proc_net_route() -> str:
    with open(PROC_NET_ROUTE, encoding="ascii", errors="replace") as fh:
        return fh.read(65536)


class _Backoff:
    """Exponential retry delay: first, 2×first, … capped."""

    def __init__(self, first: float, cap: float) -> None:
        self.first = first
        self.cap = max(cap, first)
        self.delay = first
        self.failures = 0

    def failure(self) -> float:
        delay = self.delay
        self.delay = min(self.delay * 2, self.cap)
        self.failures += 1
        return delay

    def reset(self) -> None:
        self.delay = self.first
        self.failures = 0


class _TokenBucket:
    """Per-key token bucket: ``rate`` tokens per second, ``burst`` at most.

    A token bucket rather than a fixed one-second window: with a window,
    UDP jitter regularly puts two 1 Hz epochs into the same second and the
    second one finds the allowance spent. Tokens refill continuously, so
    a steady sender below ``rate`` is never cut, whatever the jitter.

    The key table is bounded: when full it is simply cleared (only allowed
    sources ever get here, so that is a handful of phones, not an attacker
    spraying addresses). Not thread-safe — each input owns its buckets and
    uses them from its own thread only.
    """

    def __init__(self, rate: float, burst: float, clock: Callable[[], float],
                 max_keys: int = 64) -> None:
        self._rate = float(rate)
        self._burst = float(burst)
        self._clock = clock
        self._max_keys = max_keys
        self._state: dict[Any, list] = {}      # key → [tokens, last refill]

    def take(self, key: Any, n: int = 1) -> bool:
        """Spend ``n`` tokens for ``key``; False (nothing spent) if short."""
        now = self._clock()
        st = self._state.get(key)
        if st is None:
            if len(self._state) >= self._max_keys:
                self._state.clear()
            st = self._state[key] = [self._burst, now]
        else:
            # max(0, …): a clock that steps back must not drain the bucket.
            st[0] = min(self._burst, st[0] + max(0.0, now - st[1]) * self._rate)
            st[1] = now
        if st[0] < n:
            return False
        st[0] -= n
        return True


class _LogLimiter:
    """One log line per key per :data:`LOG_EVERY_S` (bounded table)."""

    def __init__(self, clock: Callable[[], float], every: float = LOG_EVERY_S) -> None:
        self._clock = clock
        self._every = every
        self._last: dict[Any, float] = {}

    def ready(self, key: Any) -> bool:
        now = self._clock()
        last = self._last.get(key)
        if last is not None and 0 <= now - last < self._every:
            return False
        if len(self._last) >= 256:
            self._last.clear()
        self._last[key] = now
        return True


# ── parser ─────────────────────────────────────────────────────────────────

class NMEAParser:
    """Talker-agnostic parser for GGA, RMC and VTG.

    ``parse()`` returns True for a well-formed sentence it understands (a
    "no fix" RMC/GGA included — it is valid, just carries no position) and
    False for anything else (bad checksum, unknown type, GSV/GSA, junk).
    Every VALID position (RMC status A / GGA quality 1-6) bumps
    :attr:`fix_count`; the manager publishes on that.

    Satellites come from GGA only (the old GSV handler overwrote them with
    "satellites in view", which is not "used in the fix"). Speed and course
    come from RMC or VTG, altitude from GGA, ``time_utc`` from RMC
    (date + time, year sanity checked).

    Args:
        require_checksum: reject sentences without ``*hh`` (a present
            checksum is always verified).
        clock: monotonic seconds — when each field was last refreshed.
    """

    def __init__(self, require_checksum: bool = True,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.require_checksum = require_checksum
        self._clock = clock
        self.lat = 0.0
        self.lon = 0.0
        self.alt: Optional[float] = None
        self.speed_knots: Optional[float] = None
        self.heading: Optional[float] = None
        self.fix = False
        self.satellites = 0
        self.time_utc: Optional[float] = None
        self.fix_count = 0
        # monotonic time of the last fix / GGA / speed / course / RMC time
        self.fix_at: Optional[float] = None
        self.gga_at: Optional[float] = None
        self.motion_at: Optional[float] = None
        self.heading_at: Optional[float] = None
        self.time_at: Optional[float] = None
        self.last_type = ""

    def parse(self, sentence: Any) -> bool:
        """Parse one sentence (str or bytes). True if valid and understood."""
        if isinstance(sentence, (bytes, bytearray)):
            if len(sentence) > MAX_LINE + 2:
                return False
            try:
                sentence = bytes(sentence).decode("ascii")
            except UnicodeDecodeError:
                return False
        if not isinstance(sentence, str):
            return False
        sentence = sentence.strip()
        if not sentence or len(sentence) > MAX_LINE or sentence[0] != "$":
            return False
        if not (sentence.isascii() and sentence.isprintable()):
            return False

        star = sentence.find("*")
        if star >= 0:
            body, checksum = sentence[1:star], sentence[star + 1:]
            if len(checksum) != 2 or not set(checksum) <= _HEX:
                return False
            computed = 0
            for ch in body:
                computed ^= ord(ch)
            if computed != int(checksum, 16):
                return False
        elif self.require_checksum:
            return False
        else:
            body = sentence[1:]

        parts = body.split(",")
        head = parts[0]
        if len(head) != 5 or head[:2] not in TALKERS:
            return False
        kind = head[2:]
        try:
            if kind == "GGA":
                ok = self._parse_gga(parts)
            elif kind == "RMC":
                ok = self._parse_rmc(parts)
            elif kind == "VTG":
                ok = self._parse_vtg(parts)
            else:
                return False
        except (ValueError, IndexError, OverflowError):
            return False
        if ok:
            self.last_type = kind
        return ok

    def _fix(self, lat: float, lon: float, now: float) -> None:
        self.lat, self.lon = lat, lon
        self.fix = True
        self.fix_at = now
        self.fix_count += 1

    def _parse_gga(self, parts: list) -> bool:
        """GGA — position, fix quality, satellites used, altitude."""
        if len(parts) < 10:
            return False
        quality = _int(parts[6])
        sats = _int(parts[7])
        alt = _num(parts[9])
        if quality not in GGA_VALID_QUALITY:
            self.fix = False        # well-formed "no fix" — ignored
            return True
        pos = _position(parts[2], parts[3], parts[4], parts[5])
        if pos is None:
            return False
        now = self._clock()
        self.satellites = sats if sats is not None else 0
        self.alt = alt if alt is not None and MIN_ALT_M <= alt <= MAX_ALT_M else None
        self.gga_at = now
        self._fix(pos[0], pos[1], now)
        return True

    def _parse_rmc(self, parts: list) -> bool:
        """RMC — status, position, speed (knots), course, date + time."""
        if len(parts) < 10:
            return False
        status = parts[2]
        mode = parts[12][:1] if len(parts) > 12 else ""
        if status not in ("A", "V"):
            return False
        if status != "A" or mode in INVALID_MODES:
            self.fix = False        # receiver says: no valid fix — ignored
            return True
        pos = _position(parts[3], parts[4], parts[5], parts[6])
        if pos is None:
            return False
        knots = _num(parts[7])
        course = _num(parts[8])
        now = self._clock()
        self._motion(None if knots is None else knots * KNOT_KMH, course, now)
        stamp = _rmc_epoch(parts[1], parts[9])
        if stamp is not None:
            self.time_utc = stamp
            self.time_at = now
        self._fix(pos[0], pos[1], now)
        return True

    def _parse_vtg(self, parts: list) -> bool:
        """VTG — course over ground and speed (km/h field preferred)."""
        if len(parts) < 9:
            return False
        mode = parts[9][:1] if len(parts) > 9 else ""
        course = _num(parts[1])
        knots = _num(parts[5])
        kmh = _num(parts[7])
        if mode in INVALID_MODES:
            return True
        if kmh is None and knots is not None:
            kmh = knots * KNOT_KMH
        self._motion(kmh, course, self._clock())
        return True

    def _motion(self, kmh: Optional[float], course: Optional[float], now: float) -> None:
        """Store speed/course; implausible values count as not reported."""
        if kmh is not None and 0.0 <= kmh <= MAX_SPEED_KMH:
            self.speed_knots = kmh / KNOT_KMH
            self.motion_at = now
        if course is not None and 0.0 <= course <= 360.0:
            self.heading = course % 360.0
            self.heading_at = now
        elif course is None and self.heading is not None:
            # Empty course field: stationary receivers often omit it, and
            # the car still points the same way — keep the last course
            # current. The manager forgets it when the fix is lost
            # (clear_heading), so this never carries one across an outage.
            self.heading_at = now

    def clear_heading(self) -> None:
        """Forget the course (the fix was lost; the car may have turned)."""
        self.heading = None
        self.heading_at = None

    @property
    def speed_kmh(self) -> float:
        """Speed in km/h (converted from knots); 0.0 when never reported."""
        return (self.speed_knots or 0.0) * KNOT_KMH


# ── demo ───────────────────────────────────────────────────────────────────

class DemoGPSGenerator:
    """Simulated GPS generating a driving route through Milan.

    Route: Via Alessandro Volta → Arco della Pace → Central Milan loop.
    """

    # Milan route waypoints (lat, lon)
    ROUTE = [
        (45.4773, 9.1815),  # Via Alessandro Volta
        (45.4755, 9.1750),  # Toward Parco Sempione
        (45.4740, 9.1720),  # Arco della Pace
        (45.4710, 9.1700),  # Via Dante approach
        (45.4660, 9.1870),  # Piazza del Duomo area
        (45.4630, 9.1920),  # Via Torino
        (45.4680, 9.1960),  # Piazza San Babila
        (45.4720, 9.1950),  # Corso Buenos Aires
        (45.4760, 9.2000),  # Viale Monza
        (45.4800, 9.1950),  # North loop
        (45.4790, 9.1880),  # Heading west
        (45.4773, 9.1815),  # Back to start
    ]

    def __init__(self):
        self._idx = 0
        self._frac = 0.0
        self._speed = 45.0  # km/h base speed

    def tick(self) -> dict:
        """Advance simulation, return GPS data dict."""
        n = len(self.ROUTE)
        p1 = self.ROUTE[self._idx % n]
        p2 = self.ROUTE[(self._idx + 1) % n]

        # Interpolate position
        lat = p1[0] + (p2[0] - p1[0]) * self._frac
        lon = p1[1] + (p2[1] - p1[1]) * self._frac

        # Heading from p1 to p2
        dlat = p2[0] - p1[0]
        dlon = p2[1] - p1[1]
        heading = math.degrees(math.atan2(dlon, dlat)) % 360

        # Vary speed slightly
        speed = self._speed + 10 * math.sin(time.time() * 0.3)

        # Advance along segment
        self._frac += 0.02
        if self._frac >= 1.0:
            self._frac = 0.0
            self._idx = (self._idx + 1) % n

        return {
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "alt": 120.0,
            "altitude": 120.0,
            "speed": max(0, round(speed, 1)),
            "heading": round(heading, 1),
            "fix": True,
            "satellites": 8,
        }


# ── inputs ─────────────────────────────────────────────────────────────────

class _Input:
    """One NMEA input running in its own thread.

    ``state``/``peer``/``last_ts`` are read by gps.source_state without a
    lock — plain attribute writes, a slightly stale view is fine.
    """

    name = ""

    def __init__(self, manager: "GPSManager") -> None:
        self._mgr = manager
        self.state = "starting"
        self.peer = ""
        self.last_ts: Optional[float] = None
        self._announced = False

    def snapshot(self) -> dict:
        return {"source": self.name, "state": self.state,
                "peer": self.peer, "last_ts": self.last_ts}

    def run(self) -> None:          # pragma: no cover - abstract
        raise NotImplementedError

    def close(self) -> None:
        """Help run() notice stop() sooner.

        Every blocking call in the inputs has a <= 1 s timeout, so this is
        optional. UDP and serial deliberately do NOT close their descriptor
        from here: closing an fd another thread is blocked on lets the
        number be reused under it. TCP only shuts the socket down.
        """

    def _stopping(self) -> bool:
        return self._mgr._stop.is_set()

    def _wait(self, seconds: float) -> bool:
        """Sleep unless stopping; True = stop requested."""
        return self._mgr._stop.wait(seconds)

    def _accepted(self, peer: str) -> None:
        self.last_ts = self._mgr._wall()
        if not self._announced:
            self._announced = True
            log.info("GPS: receiving NMEA via %s from %s", self.name, peer or "?")


class _DemoInput(_Input):
    name = "demo"

    def run(self) -> None:
        self.state = "running"
        while not self._stopping():
            self._mgr.publish_demo(self._mgr._demo.tick(), self)
            if self._wait(1.0):
                break


class _SerialInput(_Input):
    """UART receiver or Bluetooth GPS (``/dev/rfcomm0``), with reconnect.

    ``fallback_demo`` (source ``auto`` only): when the port cannot be opened
    on the FIRST attempt, run the demo route instead — the legacy behaviour.
    """

    name = "serial"

    def __init__(self, manager: "GPSManager", port: Any, baudrate: int,
                 fallback_demo: bool) -> None:
        super().__init__(manager)
        self._port = port
        self._baudrate = baudrate
        self._fallback_demo = fallback_demo

    def run(self) -> None:
        port = self._port
        if not _valid_serial_port(port):
            log.error("hardware.gps.port=%r is not a /dev/… path", port)
            if self._fallback_demo:
                self._run_fallback("invalid port")
            else:
                self.state = "error"
            return
        self.peer = port
        backoff = _Backoff(1.0, 60.0)
        first = True
        while not self._stopping():
            try:
                ser = self._mgr._serial_factory(port, self._baudrate)
            except Exception as e:          # ImportError, SerialException, OSError
                if first and self._fallback_demo:
                    self._run_fallback(str(e))
                    return
                first = False
                self.state = "error"
                level = log.warning if backoff.failures == 0 else log.debug
                level("GPS serial %s unavailable: %s — retrying", port, e)
                if self._wait(backoff.failure()):
                    break
                continue
            first = False
            self.state = "connected"
            log.info("GPS serial opened: %s @ %d", port, self._baudrate)
            try:
                while not self._stopping():
                    raw = ser.readline(MAX_LINE * 2)
                    if not raw:
                        continue    # read timeout
                    if self._mgr.feed(raw, self.name):
                        backoff.reset()
                        self._accepted(port)
            except Exception as e:
                log.warning("GPS serial %s read error: %s — reopening", port, e)
            finally:
                self._announced = False
                try:
                    ser.close()
                except Exception:
                    pass
            if self._stopping():
                break
            self.state = "error"
            if self._wait(backoff.failure()):
                break

    def _run_fallback(self, reason: str) -> None:
        log.warning("GPS serial %s unavailable (%s) — hardware.gps.source is auto: "
                    "falling back to the DEMO route (set source: serial to wait "
                    "for the receiver instead)", self._port, reason)
        self.state = "demo_fallback"
        while not self._stopping():
            self._mgr.publish_demo(self._mgr._demo.tick(), self)
            if self._wait(1.0):
                break


class _UDPInput(_Input):
    """Datagrams from the phone (GPSd Forwarder and friends).

    Several sentences per datagram are fine (one per line). Only sources in
    ``allowed_sources`` count; oversize datagrams are dropped whole.
    """

    name = "udp"

    def __init__(self, manager: "GPSManager", cfg: dict) -> None:
        super().__init__(manager)
        d = DEFAULTS["udp"]
        bind = cfg.get("bind", d["bind"])
        try:
            self._bind = str(ipaddress.IPv4Address(str(bind)))
        except ValueError:
            log.warning("hardware.gps.udp.bind=%r is not an IPv4 address — using %s",
                        bind, d["bind"])
            self._bind = d["bind"]
        # 0 = any free port (tests read bound_port).
        self._port = int(_number(cfg.get("port", d["port"]), d["port"], 0, 65535, "udp.port"))
        self._max = int(_number(cfg.get("max_datagram", d["max_datagram"]), d["max_datagram"],
                                128, 65507, "udp.max_datagram"))
        self._networks, self._use_pan = self._parse_allowed(
            cfg.get("allowed_sources", d["allowed_sources"]))
        self._rate = _TokenBucket(RATE_PER_SOURCE, RATE_PER_SOURCE, manager._clock)
        self._raw = _TokenBucket(RAW_LINES_PER_SOURCE, RAW_LINES_PER_SOURCE, manager._clock)
        self._log_limit = _LogLimiter(manager._clock)
        self._pan_lock = threading.Lock()
        self._pan_nets: list = []
        self._pan_expiry: Optional[float] = None
        self._pan_warned = False
        self.bound_port: Optional[int] = None
        #: Set once the socket is bound (tests wait on it).
        self.bound = threading.Event()

    @staticmethod
    def _parse_allowed(value: Any) -> tuple[list, bool]:
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, (list, tuple)):
            log.warning("hardware.gps.udp.allowed_sources=%r is not a list — "
                        "only loopback is allowed", value)
            return [ipaddress.ip_network("127.0.0.0/8")], False
        nets, use_pan = [], False
        for entry in value:
            if entry == "pan":
                use_pan = True
                continue
            try:
                nets.append(ipaddress.ip_network(str(entry), strict=False))
            except ValueError:
                log.warning("hardware.gps.udp.allowed_sources: %r is not a CIDR or 'pan' — "
                            "ignored", entry)
        return nets, use_pan

    def pan_networks(self) -> list:
        """Subnets of bnep* (cached; ``ip`` missing = none)."""
        with self._pan_lock:
            now = self._mgr._clock()
            if self._pan_expiry is not None and now < self._pan_expiry:
                return self._pan_nets
            nets: list = []
            try:
                res = self._mgr._ip_runner(list(IP_ADDR_ARGV), capture_output=True,
                                           text=True, timeout=3)
                if getattr(res, "returncode", 1) == 0:
                    nets = _parse_ip_addr(getattr(res, "stdout", "") or "")
            except (OSError, subprocess.SubprocessError, ValueError) as e:
                if not self._pan_warned:
                    self._pan_warned = True
                    log.warning("GPS UDP: cannot list interfaces (%s) — 'pan' "
                                "allows nothing", e)
            self._pan_nets = nets
            self._pan_expiry = now + (PAN_CACHE_S if nets else PAN_CACHE_EMPTY_S)
            return nets

    def source_allowed(self, host: str) -> bool:
        try:
            ip = ipaddress.ip_address(str(host).split("%", 1)[0])
        except ValueError:
            return False
        if ip.version == 6 and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        if any(ip in net for net in self._networks):
            return True
        return self._use_pan and any(ip in net for net in self.pan_networks())

    def handle_datagram(self, data: bytes, addr: tuple) -> int:
        """Feed one datagram; returns the number of sentences accepted."""
        host = str(addr[0]) if addr else ""
        if not self.source_allowed(host):
            if self._log_limit.ready(("deny", host)):
                log.info("GPS UDP: ignoring datagrams from %s (not in "
                         "hardware.gps.udp.allowed_sources)", host)
            return 0
        if len(data) > self._max:
            if self._log_limit.ready(("size", host)):
                log.info("GPS UDP: dropped a %d-byte datagram from %s (max_datagram %d)",
                         len(data), host, self._max)
            return 0
        lines = data.split(b"\n")
        # CPU bound first: a flood from an allowed address is dropped a
        # whole datagram at a time, before any per-line Python work.
        if not self._raw.take(host, len(lines)):
            if self._log_limit.ready(("raw", host)):
                log.info("GPS UDP: %s exceeds %d lines/s — dropping datagrams",
                         host, RAW_LINES_PER_SOURCE)
            return 0
        accepted = 0
        for raw in lines:
            line = raw.strip()
            # GSV/GSA/… are dropped here, before the sentence bucket, so
            # they cannot use up the allowance of the lines with the fix.
            if not _wanted(line):
                continue
            if not self._rate.take(host):
                if self._log_limit.ready(("rate", host)):
                    log.info("GPS UDP: %s exceeds %d GGA/RMC/VTG sentences/s — "
                             "dropping the excess", host, RATE_PER_SOURCE)
                break
            if self._mgr.feed(line, self.name):
                accepted += 1
        if accepted:
            port = addr[1] if len(addr) > 1 else 0
            self.peer = f"{host}:{port}"
            self.state = "receiving"
            self._accepted(self.peer)
        return accepted

    def run(self) -> None:
        backoff = _Backoff(1.0, 60.0)
        while not self._stopping():
            sock = None
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                # Deliberately NO SO_REUSEADDR: UDP needs none to re-bind,
                # and on Linux it would let a second BCM (run_x86.sh by hand
                # next to the service) bind the same port too — unicast
                # datagrams then reach only one of them and the service
                # silently loses the phone. Without it the second instance
                # gets EADDRINUSE, logged below.
                sock.bind((self._bind, self._port))
                sock.settimeout(1.0)
            except OSError as e:
                if sock is not None:
                    sock.close()
                self.state = "error"
                level = log.warning if backoff.failures == 0 else log.debug
                level("GPS UDP: cannot bind %s:%d: %s — retrying", self._bind, self._port, e)
                if self._wait(backoff.failure()):
                    break
                continue
            self.bound_port = sock.getsockname()[1]
            self.state = "listening"
            backoff.reset()
            log.info("GPS UDP listening on %s:%d (allowed: %s%s)", self._bind,
                     self.bound_port, ", ".join(str(n) for n in self._networks) or "-",
                     ", pan" if self._use_pan else "")
            self.bound.set()
            try:
                while not self._stopping():
                    try:
                        # +1: a datagram larger than max arrives truncated to
                        # max+1 bytes, which is how oversize is detected.
                        data, addr = sock.recvfrom(self._max + 1)
                    except socket.timeout:
                        continue
                    self.handle_datagram(data, addr)
            except OSError as e:
                if not self._stopping():
                    log.warning("GPS UDP socket error: %s — re-binding", e)
            finally:
                self.bound.clear()
                sock.close()
            if self._wait(backoff.failure()):
                break


class _TCPInput(_Input):
    """Client of an NMEA TCP server app on the phone (over BT PAN)."""

    name = "tcp"

    def __init__(self, manager: "GPSManager", cfg: dict) -> None:
        super().__init__(manager)
        d = DEFAULTS["tcp"]
        host = cfg.get("host", d["host"])
        if isinstance(host, str) and (host == "pan-gateway" or _HOST_RE.fullmatch(host)):
            self._host = host
        else:
            log.warning("hardware.gps.tcp.host=%r is not a host name/address — using %s",
                        host, d["host"])
            self._host = d["host"]
        self._port = int(_number(cfg.get("port", d["port"]), d["port"], 1, 65535, "tcp.port"))
        self._connect_timeout = float(_number(cfg.get("connect_timeout", d["connect_timeout"]),
                                              d["connect_timeout"], 0.5, 60, "tcp.connect_timeout"))
        backoff_max = float(_number(cfg.get("backoff_max_sec", d["backoff_max_sec"]),
                                    d["backoff_max_sec"], 1, 3600, "tcp.backoff_max_sec"))
        backoff_min = float(_number(cfg.get("backoff_min_sec", d["backoff_min_sec"]),
                                    d["backoff_min_sec"], 0.05, 60, "tcp.backoff_min_sec"))
        self._idle = float(_number(cfg.get("idle_timeout_sec", d["idle_timeout_sec"]),
                                   d["idle_timeout_sec"], 2, 3600, "tcp.idle_timeout_sec"))
        self._backoff = _Backoff(backoff_min, backoff_max)
        # No raw-line bucket here: TCP is one connection WE open to the
        # phone, read 4 KiB at a time, and every line costs a slice compare
        # (_wanted) before anything heavier.
        self._rate = _TokenBucket(RATE_PER_SOURCE, RATE_PER_SOURCE, manager._clock)
        self._log_limit = _LogLimiter(manager._clock)
        self._sock: Optional[socket.socket] = None
        #: Successful connections so far (tests).
        self.connections = 0

    def _resolve(self) -> Optional[str]:
        if self._host != "pan-gateway":
            return self._host
        try:
            return _parse_proc_net_route(self._mgr._route_reader())
        except OSError as e:
            log.debug("GPS TCP: cannot read %s: %s", PROC_NET_ROUTE, e)
            return None

    def run(self) -> None:
        backoff = self._backoff
        while not self._stopping():
            host = self._resolve()
            if not host:
                self.state = "waiting"
                self.peer = ""
                if self._log_limit.ready("no-gateway"):
                    log.info("GPS TCP: no Bluetooth PAN gateway yet (bnep*) — waiting")
                # PAN down is not a failure of ours: poll the routing table
                # at a fixed short interval (growing the backoff here would
                # start the fallback up to backoff_max_sec late after every
                # PAN drop), and forget earlier connect failures — a new
                # link is a new situation. The exponential backoff stays
                # for connect and read failures only.
                backoff.reset()
                if self._wait(min(PAN_POLL_S, backoff.cap)):
                    break
                continue
            self.peer = f"{host}:{self._port}"
            self.state = "connecting"
            try:
                sock = socket.create_connection((host, self._port),
                                                timeout=self._connect_timeout)
            except OSError as e:
                self.state = "error"
                level = log.warning if backoff.failures == 0 else log.debug
                level("GPS TCP: cannot connect to %s: %s — retrying", self.peer, e)
                if self._wait(backoff.failure()):
                    break
                continue
            self._sock = sock
            self.connections += 1
            self.state = "connected"
            log.info("GPS TCP connected to %s", self.peer)
            try:
                self._read_loop(sock)
            except OSError as e:
                if not self._stopping():
                    log.info("GPS TCP: connection to %s lost: %s", self.peer, e)
            finally:
                self._sock = None
                self._announced = False
                try:
                    sock.close()
                except OSError:
                    pass
            if self._stopping():
                break
            self.state = "disconnected"
            # The backoff is reset only by accepted data, so a server that
            # accepts and hangs up at once is not hammered every second.
            if self._wait(backoff.failure()):
                break

    def _read_loop(self, sock: socket.socket) -> None:
        sock.settimeout(1.0)
        buf = b""
        last_data = self._mgr._clock()
        while not self._stopping():
            try:
                chunk = sock.recv(4096)
            except socket.timeout:
                if self._mgr._clock() - last_data > self._idle:
                    log.info("GPS TCP: nothing from %s for %.0f s — reconnecting",
                             self.peer, self._idle)
                    return
                continue
            if not chunk:
                if not self._stopping():        # stop() shuts the socket down
                    log.info("GPS TCP: %s closed the connection", self.peer)
                return
            last_data = self._mgr._clock()
            buf += chunk
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                self._line(raw.strip())
            if len(buf) > MAX_LINE * 2:
                buf = b""       # no newline in sight: not NMEA, drop it

    def _line(self, line: bytes) -> None:
        # Same order as UDP: unused sentence types never reach the bucket.
        if not _wanted(line):
            return
        if not self._rate.take("tcp"):
            if self._log_limit.ready("rate"):
                log.info("GPS TCP: %s exceeds %d GGA/RMC/VTG sentences/s — "
                         "dropping the excess", self.peer, RATE_PER_SOURCE)
            return
        if self._mgr.feed(line, self.name):
            self._backoff.reset()
            self._accepted(self.peer)

    def close(self) -> None:
        sock = self._sock
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


# ── manager ────────────────────────────────────────────────────────────────

class GPSManager:
    """Runs the configured NMEA inputs and publishes valid fixes.

    Args:
        event_bus: EventBus instance for publishing position data.
        config: BCMConfig or a plain dict with ``hardware.gps`` settings.
        platform: "x86" → ``auto`` means demo; anything else → serial.
        clock: monotonic seconds (staleness, backoff, rate limits).
        wall_clock: epoch seconds (``last_ts`` / demo ``time_utc``).
        ip_runner: ``subprocess.run`` compatible, for ``ip -o -4 addr show``.
        route_reader: returns the text of ``/proc/net/route``.
        serial_factory: ``(port, baudrate) -> serial object`` (pyserial).
    """

    def __init__(self, event_bus, config: Any, platform: str = "x86", *,
                 clock: Callable[[], float] = time.monotonic,
                 wall_clock: Callable[[], float] = time.time,
                 ip_runner: Callable[..., Any] = subprocess.run,
                 route_reader: Callable[[], str] = _read_proc_net_route,
                 serial_factory: Callable[[str, int], Any] = _open_serial):
        self._bus = event_bus
        self._config = config
        self._platform = platform
        self._clock = clock
        self._wall = wall_clock
        self._ip_runner = ip_runner
        self._route_reader = route_reader
        self._serial_factory = serial_factory

        section = _cfg_get(config, "hardware.gps", {})
        if not isinstance(section, dict):
            section = {}
        self._section = section
        self.sources, self.auto = _resolve_sources(section.get("source", DEFAULTS["source"]),
                                                   platform)
        self._stale_sec = float(_number(section.get("stale_sec", DEFAULTS["stale_sec"]),
                                        DEFAULTS["stale_sec"], 1, 600, "stale_sec"))
        require = section.get("require_checksum", DEFAULTS["require_checksum"])
        if not isinstance(require, bool):
            log.warning("hardware.gps.require_checksum=%r is not true/false — using true",
                        require)
            require = True
        self._parser = NMEAParser(require_checksum=require, clock=clock)
        self._demo = DemoGPSGenerator()

        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._running = False
        self._threads: list[threading.Thread] = []
        self._thread: Optional[threading.Thread] = None     # ticker (legacy name)
        self._inputs: dict[str, _Input] = {}
        self._build_inputs()

        # Fix state (under _lock).
        self._fix_published = False
        self._last_fix_at: Optional[float] = None
        self._last_fix_wall: Optional[float] = None
        self._last_fix_source = ""
        self._last_publish_at: Optional[float] = None
        self._next_state_at: Optional[float] = None

    # ── setup ─────────────────────────────────────────────────────────────

    def _build_inputs(self) -> None:
        section = self._section
        for name in self.sources:
            if name == "demo":
                inp: _Input = _DemoInput(self)
            elif name == "serial":
                baud = int(_number(section.get("baudrate", DEFAULTS["baudrate"]),
                                   DEFAULTS["baudrate"], 300, 921600, "baudrate"))
                inp = _SerialInput(self, section.get("port", DEFAULTS["port"]), baud,
                                   fallback_demo=self.auto)
            elif name == "udp":
                cfg = section.get("udp") or {}
                inp = _UDPInput(self, cfg if isinstance(cfg, dict) else {})
            else:
                cfg = section.get("tcp") or {}
                inp = _TCPInput(self, cfg if isinstance(cfg, dict) else {})
            self._inputs[name] = inp

    @property
    def inputs(self) -> dict:
        """Input objects by name (read-only view for tests / diagnostics)."""
        return dict(self._inputs)

    def start(self):
        """Start every input and the ticker in background threads."""
        if self._running:
            return
        self._running = True
        self._stop.clear()
        for name, inp in self._inputs.items():
            t = threading.Thread(target=self._guard, args=(inp,), daemon=True,
                                 name=f"gps-{name}")
            t.start()
            self._threads.append(t)
        self._thread = threading.Thread(target=self._tick_loop, daemon=True, name="gps-tick")
        self._thread.start()
        log.info("GPSManager started (platform=%s, source=%s%s, stale %.0f s)",
                 self._platform, ",".join(self.sources) or "none",
                 " [auto]" if self.auto else "", self._stale_sec)

    def stop(self):
        """Stop every input; returns within a few seconds."""
        self._running = False
        self._stop.set()
        for inp in self._inputs.values():
            inp.close()
        for t in self._threads + ([self._thread] if self._thread else []):
            t.join(timeout=3)
        self._threads = []
        self._thread = None
        log.info("GPSManager stopped")

    def _guard(self, inp: _Input) -> None:
        """Run one input; an unexpected bug restarts it instead of killing GPS."""
        while not self._stop.is_set():
            try:
                inp.run()
                return
            except Exception:
                log.exception("GPS input %s crashed — restarting in 5 s", inp.name)
                inp.state = "error"
                if self._stop.wait(5.0):
                    return

    def _tick_loop(self) -> None:
        while not self._stop.wait(TICK_S):
            try:
                self.tick()
            except Exception:
                log.exception("GPS tick failed")

    # ── data path ─────────────────────────────────────────────────────────

    def feed(self, line: Any, source: str = "test") -> bool:
        """Parse one sentence from ``source``; publish if it is a valid fix.

        Returns True when the sentence was accepted by the parser.
        """
        with self._lock:
            before = self._parser.fix_count
            if not self._parser.parse(line):
                return False
            if self._parser.fix_count != before:
                self._on_fix_locked(source)
            return True

    def _on_fix_locked(self, source: str) -> None:
        now = self._clock()
        self._last_fix_at = now
        self._last_fix_wall = self._wall()
        self._last_fix_source = source
        acquired = not self._fix_published
        if not acquired and self._last_publish_at is not None \
                and 0 <= now - self._last_publish_at < MIN_PUBLISH_INTERVAL_S:
            return
        self._last_publish_at = now
        self._publish_fix_locked(self._payload_locked(source, now), acquired)

    def _payload_locked(self, source: str, now: float) -> dict:
        p = self._parser

        def fresh(at: Optional[float]) -> bool:
            return at is not None and 0 <= now - at <= self._stale_sec

        speed = round(p.speed_knots * KNOT_KMH, 1) \
            if p.speed_knots is not None and fresh(p.motion_at) else None
        heading = round(p.heading, 1) \
            if p.heading is not None and fresh(p.heading_at) else None
        gga = fresh(p.gga_at)
        alt = round(p.alt, 1) if gga and p.alt is not None else None
        return {
            "lat": round(p.lat, 6),
            "lon": round(p.lon, 6),
            "alt": alt,
            "altitude": alt,
            "speed": speed,
            "heading": heading,
            "satellites": p.satellites if gga else 0,
            "fix": True,
            # Informational only — see the module docstring: never used to
            # set the system clock (UDP sources can be spoofed).
            "time_utc": p.time_utc if fresh(p.time_at) else None,
            "source": source,
        }

    def publish_demo(self, data: dict, inp: Optional[_Input] = None) -> None:
        """Publish one demo-route point with the same payload shape."""
        with self._lock:
            now = self._clock()
            wall = self._wall()
            source = "demo"
            self._last_fix_at = now
            self._last_fix_wall = wall
            self._last_fix_source = source
            self._last_publish_at = now
            if inp is not None:
                inp.last_ts = wall
            alt = data.get("alt", data.get("altitude"))
            payload = {
                "lat": data["lat"], "lon": data["lon"],
                "alt": alt, "altitude": alt,
                "speed": data.get("speed"), "heading": data.get("heading"),
                "satellites": data.get("satellites", 0), "fix": True,
                "time_utc": wall, "source": source,
            }
            self._publish_fix_locked(payload, not self._fix_published)

    def _publish_fix_locked(self, payload: dict, acquired: bool) -> None:
        bus = self._bus
        if acquired:
            self._fix_published = True
            bus.publish("gps.fix", True)
            log.info("GPS fix acquired (source %s)", payload.get("source"))
        bus.publish("gps.position", payload)
        bus.publish("gps.lat", payload["lat"])
        bus.publish("gps.lon", payload["lon"])
        if payload.get("speed") is not None:
            bus.publish("gps.speed", payload["speed"])
        if payload.get("heading") is not None:
            bus.publish("gps.heading", payload["heading"])
        bus.publish("gps.satellites", payload.get("satellites", 0))
        if payload.get("time_utc") is not None:
            bus.publish("gps.time_utc", payload["time_utc"])

    def tick(self) -> None:
        """Stale check (gps.fix False once) and periodic gps.source_state."""
        with self._lock:
            now = self._clock()
            if self._fix_published and (self._last_fix_at is None
                                        or not 0 <= now - self._last_fix_at < self._stale_sec):
                self._fix_published = False
                # A course from before the outage is not current: the car
                # may have turned meanwhile (see the module docstring).
                self._parser.clear_heading()
                self._bus.publish("gps.fix", False)
                log.info("GPS fix lost — no valid fix for %.0f s (last from %s)",
                         self._stale_sec, self._last_fix_source or "?")
            if self._next_state_at is None or now >= self._next_state_at \
                    or self._next_state_at - now > SOURCE_STATE_EVERY_S:
                self._next_state_at = now + SOURCE_STATE_EVERY_S
                self._bus.publish("gps.source_state", self._source_state_locked())

    def _source_state_locked(self) -> dict:
        last = self._inputs.get(self._last_fix_source)
        return {
            "source": self._last_fix_source or ",".join(self.sources),
            "state": "fix" if self._fix_published else "no_fix",
            "peer": last.peer if last is not None else "",
            "last_ts": self._last_fix_wall,
            "inputs": [inp.snapshot() for inp in self._inputs.values()],
        }

    @property
    def has_fix(self) -> bool:
        return self._fix_published


def start_location(config, event_bus, hal, **kwargs):
    """Module entry point — called by main.py module registry."""
    platform = _cfg_get(config, "system.platform", "x86")
    gps = GPSManager(event_bus, config, platform if isinstance(platform, str) else "x86")
    gps.start()
    return gps
