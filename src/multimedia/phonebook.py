"""PBAP phonebook + call-history puller via BlueZ obexd.

When a paired phone authorises PBAP sharing during pairing, obexd
exposes an org.bluez.obex session that we can drive over D-Bus to
download:

  * ``telecom/pb.vcf``  — full phonebook (vCard 3.0 stream)
  * ``telecom/cch.vcf`` — combined call history (in + out + missed)

Both are parsed into JSON-friendly dicts and published on the event
bus as ``bt.contacts`` and ``bt.call_history`` so the A3 phone screen
can render them via /api/phone/contacts and /api/phone/history.

Results are cached to ~/.bcm/phonebook-<addr>.json so a slow PBAP
pull doesn't blank the A3 screen between sessions.

The pull waits ``bluetooth.phonebook_settle_sec`` (code default 3 s, the old
fixed delay) after ``bt.connected``: PBAP is an OBEX session over RFCOMM, and
in the first seconds after the phone connects Android Auto bootstraps its
Wi-Fi credentials over RFCOMM too. The test config uses the same 15 s as
``network.phone_tether.settle_sec``. A disconnect during the wait cancels it.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from typing import Any, Optional

from src.core.event_bus import EventBus
from src.core.fsutil import atomic_write_json
from src.core.logger import get_logger

log = get_logger("multimedia.phonebook")

try:
    import dbus
    HAS_DBUS = True
except ImportError:
    HAS_DBUS = False

OBEX_BUS = "org.bluez.obex"
OBEX_ROOT = "/org/bluez/obex"
OBEX_CLIENT_IFACE = "org.bluez.obex.Client1"
OBEX_SESSION_IFACE = "org.bluez.obex.Session1"
OBEX_PBAP_IFACE = "org.bluez.obex.PhonebookAccess1"

CACHE_DIR = os.path.expanduser("~/.bcm")
PULL_TIMEOUT_S = 30.0
#: Default wait between bt.connected and the pull (the historical value:
#: Android shows the PBAP authorise popup only once audio is rolling).
DEFAULT_SETTLE_S = 3.0
MAX_SETTLE_S = 120.0
_SETTLE_STEP_S = 0.5

# obexd ships in slightly different libexec locations across distros.
_OBEXD_BIN_CANDIDATES = (
    "/usr/libexec/bluetooth/obexd",
    "/usr/lib/bluetooth/obexd",
    "/usr/lib/bluez/obexd",
)


def _cache_path(addr: str) -> str:
    safe = addr.replace(":", "").lower()
    return os.path.join(CACHE_DIR, f"phonebook-{safe}.json")


def _parse_vcards(blob: str) -> list[dict[str, Any]]:
    """Split a vCard 3.0 stream into structured records.

    Handles the subset Android exposes via PBAP:
      FN, N, TEL (with TYPE=CELL/HOME/WORK/VOICE), X-IRMC-CALL-DATETIME.
    Everything else is ignored — we only need name + numbers + optional
    timestamp for the call-history view.
    """
    records: list[dict[str, Any]] = []
    current: Optional[dict[str, Any]] = None
    line_iter = iter(blob.splitlines())
    for raw in line_iter:
        line = raw.rstrip("\r")
        if not line:
            continue
        # vCard line-folding: a line continuation starts with space/tab
        while line.endswith("="):
            try:
                line = line[:-1] + next(line_iter).rstrip("\r")
            except StopIteration:
                break
        if line.upper() == "BEGIN:VCARD":
            current = {"name": "", "numbers": [], "timestamp": ""}
            continue
        if line.upper() == "END:VCARD":
            if current and (current["name"] or current["numbers"]):
                records.append(current)
            current = None
            continue
        if current is None:
            continue
        if ":" not in line:
            continue
        head, value = line.split(":", 1)
        params = head.split(";")
        prop = params[0].upper()
        if prop == "FN":
            current["name"] = value.strip()
        elif prop == "N" and not current["name"]:
            # N is "Last;First;Middle;Prefix;Suffix" — take first+last.
            parts = value.split(";")
            current["name"] = " ".join(p for p in (
                parts[1] if len(parts) > 1 else "",
                parts[0] if parts else "",
            ) if p).strip()
        elif prop == "TEL":
            typ = ""
            for p in params[1:]:
                if p.upper().startswith("TYPE="):
                    typ = p.split("=", 1)[1].strip().split(",")[0]
                    break
            number = re.sub(r"[\s\-()]", "", value.strip())
            if number:
                current["numbers"].append({"type": typ.lower(), "number": number})
        elif prop == "X-IRMC-CALL-DATETIME":
            current["timestamp"] = value.strip()
            for p in params[1:]:
                if p.upper() in ("RECEIVED", "DIALED", "MISSED"):
                    current.setdefault("direction", p.lower())
    return records


_DIR_TO_TYPE = {"received": "incoming", "dialed": "outgoing", "missed": "missed"}


def _fmt_call_time(ts: str) -> str:
    """Render an X-IRMC-CALL-DATETIME stamp for the A8 history list.

    The field is basic ISO 8601 (``YYYYMMDDThhmmss[+/-hhmm]``). The A8
    list only has room for a short label, so collapse it to ``DD.MM HH:MM``.
    Anything that doesn't match is passed through untouched.
    """
    if not ts:
        return ""
    m = re.match(r"(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})", ts)
    if not m:
        return ts
    _y, mo, d, h, mi = m.groups()
    return f"{d}.{mo} {h}:{mi}"


def _to_ui_contacts(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten parsed vCards into the ``{name, number}`` cards the A8
    contacts list renders.

    The parser groups every TEL under one record as ``numbers: [...]``,
    but the dialer screen reads a flat ``c.number`` and dials it directly.
    Emit one card per number (so a contact with mobile+home shows both,
    each independently dialable) and drop exact duplicates PBAP loves to
    repeat.
    """
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for rec in records:
        name = (rec.get("name") or "").strip()
        for n in rec.get("numbers") or []:
            num = (n.get("number") or "").strip()
            if not num:
                continue
            key = (name, num)
            if key in seen:
                continue
            seen.add(key)
            out.append({"name": name or num, "number": num,
                        "type": n.get("type", "")})
    return out


def _to_ui_history(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map call-history vCards to the ``{type, name, number, time}`` rows
    the A8 history list expects.

    PBAP's cch.vcf marks each entry with X-IRMC-CALL-DATETIME;TYPE and a
    direction (received/dialed/missed). The UI keys off ``h.type`` with
    values incoming/outgoing/missed for its icon + colour, so translate
    the direction and surface the first number flat.
    """
    out: list[dict[str, Any]] = []
    for rec in records:
        numbers = rec.get("numbers") or []
        num = ((numbers[0].get("number") if numbers else "") or "").strip()
        out.append({
            "type": _DIR_TO_TYPE.get(rec.get("direction", ""), "incoming"),
            "name": (rec.get("name") or "").strip(),
            "number": num,
            "time": _fmt_call_time(rec.get("timestamp", "")),
            "duration": "",
        })
    return out


def settle_from_config(config: Any) -> float:
    """``bluetooth.phonebook_settle_sec`` as seconds in ``[0, MAX_SETTLE_S]``;
    the default for a missing or non-numeric value."""
    value = None
    getter = getattr(config, "get", None)
    if callable(getter):
        try:
            value = getter("bluetooth.phonebook_settle_sec")
        except Exception:
            value = None
    if value is None:
        return DEFAULT_SETTLE_S
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or value != value or value in (float("inf"), float("-inf")):
        log.warning("bluetooth.phonebook_settle_sec=%r is not a number — using %ss",
                    value, DEFAULT_SETTLE_S)
        return DEFAULT_SETTLE_S
    return float(min(max(value, 0.0), MAX_SETTLE_S))


class PhonebookSync:
    """Drives obexd PBAP sessions per connected BT device."""

    def __init__(self, event_bus: EventBus, settle_sec: float = DEFAULT_SETTLE_S,
                 sleep=time.sleep, clock=time.monotonic):
        self._bus = event_bus
        self._lock = threading.Lock()
        self._active_addr: Optional[str] = None
        self._stop_flag = False
        # Bumped by every _sync start: a sync still waiting out its settle
        # when the phone reconnects must not pull alongside the new one.
        self._sync_gen = 0
        self._settle_sec = settle_sec
        self._sleep = sleep
        self._clock = clock
        # bcm-headunit runs headless as root with no login session, so
        # there's no D-Bus session bus and obexd (the session-bus service
        # providing PhonebookAccess1) is never started. We bring up a
        # private session bus + obexd for this process — see
        # _ensure_session_bus.
        self._session_bus_proc: Optional[subprocess.Popen] = None
        self._obexd_proc: Optional[subprocess.Popen] = None
        self._session_addr: Optional[str] = None
        os.makedirs(CACHE_DIR, exist_ok=True)
        self._bus.subscribe("bt.connected", self._on_connected)
        self._bus.subscribe("bt.disconnected", self._on_disconnected)

    def _on_connected(self, topic: str, value: Any, ts: float) -> None:
        if not HAS_DBUS:
            log.debug("dbus-python missing — PBAP sync disabled")
            return
        if not isinstance(value, dict):
            return
        addr = value.get("address")
        if not addr:
            return
        self._publish_cached(addr)
        threading.Thread(
            target=self._sync_safe, args=(addr,),
            daemon=True, name=f"pbap-sync-{addr[-5:]}",
        ).start()

    def _on_disconnected(self, topic: str, value: Any, ts: float) -> None:
        with self._lock:
            self._active_addr = None
            self._stop_flag = True

    def _publish_cached(self, addr: str) -> None:
        """Surface the last-known phonebook immediately so A3 isn't blank
        while the PBAP pull is in flight."""
        path = _cache_path(addr)
        if not os.path.isfile(path):
            return
        try:
            with open(path) as f:
                data = json.load(f)
            self._bus.publish("bt.contacts",
                              _to_ui_contacts(data.get("contacts", [])))
            self._bus.publish("bt.call_history",
                              _to_ui_history(data.get("history", [])))
            log.info("PBAP: served cached phonebook for %s (%d contacts)",
                     addr, len(data.get("contacts", [])))
        except Exception:
            log.debug("PBAP: cache read failed for %s", addr)

    def _ensure_session_bus(self) -> "Optional[dbus.Bus]":
        """Return a session bus that has obexd, starting both if needed.

        On a normal desktop ``dbus.SessionBus()`` just works. Under the
        headless bcm-headunit service there's no session bus at all, so
        autolaunch fails with ``Unable to autolaunch a dbus-daemon without
        a $DISPLAY``. Spin up a private session ``dbus-daemon`` for this
        process (once), point obexd at it, and hand back the connection.
        Returns None if the bus or obexd can't be brought up.
        """
        # Reuse an already-working session bus (real user session, or the
        # private one we started on a previous connect).
        addr = os.environ.get("DBUS_SESSION_BUS_ADDRESS")
        if addr:
            try:
                bus = dbus.bus.BusConnection(addr)
                if self._ensure_obexd(bus):
                    return bus
            except Exception:
                pass

        # Start our own private session bus if we don't have a live one.
        if not (self._session_bus_proc and self._session_bus_proc.poll() is None):
            try:
                proc = subprocess.Popen(
                    ["dbus-daemon", "--session", "--nofork",
                     "--nopidfile", "--print-address"],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    text=True,
                )
            except FileNotFoundError:
                log.warning("dbus-daemon missing — cannot start a PBAP "
                            "session bus; phonebook unavailable")
                return None
            line = proc.stdout.readline().strip() if proc.stdout else ""
            if not line:
                log.warning("PBAP session dbus-daemon produced no address")
                proc.terminate()
                return None
            self._session_bus_proc = proc
            self._session_addr = line
            log.info("PBAP: started private session bus %s", line)

        os.environ["DBUS_SESSION_BUS_ADDRESS"] = self._session_addr or ""
        try:
            bus = dbus.bus.BusConnection(self._session_addr)
        except Exception as e:
            log.warning("PBAP: failed to connect private session bus: %s", e)
            return None
        if not self._ensure_obexd(bus):
            return None
        return bus

    def _ensure_obexd(self, bus: "dbus.Bus") -> bool:
        """Make sure obexd owns org.bluez.obex on ``bus``; launch it if not."""
        try:
            if bus.name_has_owner(OBEX_BUS):
                return True
        except Exception:
            pass
        if not (self._obexd_proc and self._obexd_proc.poll() is None):
            binp = next((p for p in _OBEXD_BIN_CANDIDATES if os.path.exists(p)),
                        None)
            if not binp:
                log.warning("obexd binary not found in %s — install bluez "
                            "OBEX support; phonebook unavailable",
                            _OBEXD_BIN_CANDIDATES)
                return False
            self._obexd_proc = subprocess.Popen(
                [binp], env=dict(os.environ),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            log.info("PBAP: launched obexd (%s)", binp)
        # obexd needs a moment to claim its bus name.
        for _ in range(24):
            try:
                if bus.name_has_owner(OBEX_BUS):
                    return True
            except Exception:
                pass
            time.sleep(0.25)
        log.warning("obexd started but org.bluez.obex never appeared on the bus")
        return False

    def _sync_safe(self, addr: str) -> None:
        try:
            self._sync(addr)
        except Exception:
            log.exception("PBAP sync raised for %s", addr)

    def _still_current(self, addr: str, gen: int) -> bool:
        with self._lock:
            return (not self._stop_flag and self._active_addr == addr
                    and self._sync_gen == gen)

    def _wait_settle(self, addr: str, gen: int) -> bool:
        """Wait ``settle_sec`` in short steps; False if the phone went away
        (or a newer sync took over) meanwhile."""
        deadline = self._clock() + self._settle_sec
        while True:
            if not self._still_current(addr, gen):
                return False
            remaining = deadline - self._clock()
            if remaining <= 0:
                return True
            self._sleep(min(_SETTLE_STEP_S, remaining))

    def _sync(self, addr: str) -> None:
        with self._lock:
            if self._active_addr == addr:
                return
            self._active_addr = addr
            self._stop_flag = False
            self._sync_gen += 1
            gen = self._sync_gen

        # Give the phone a moment to authorise the PBAP service after
        # the A2DP link comes up — Android delays the PBAP authorise
        # popup until after audio is rolling — and let the AA wireless
        # bootstrap have RFCOMM to itself (module docstring).
        if not self._wait_settle(addr, gen):
            log.info("PBAP: %s went away during the settle wait — pull skipped", addr)
            return

        bus = self._ensure_session_bus()
        if bus is None:
            log.warning("PBAP: no session bus / obexd available — "
                        "phonebook & call history unavailable")
            return
        try:
            client = dbus.Interface(
                bus.get_object(OBEX_BUS, OBEX_ROOT), OBEX_CLIENT_IFACE,
            )
        except dbus.exceptions.DBusException:
            log.warning("obexd not reachable on session bus after bootstrap")
            return

        try:
            session_path = client.CreateSession(
                addr, dbus.Dictionary({"Target": "PBAP"}, signature="sv"),
                timeout=PULL_TIMEOUT_S,
            )
        except dbus.exceptions.DBusException as e:
            log.warning("PBAP CreateSession(%s) failed: %s", addr, e)
            return
        log.info("PBAP session for %s → %s", addr, session_path)

        pbap = dbus.Interface(
            bus.get_object(OBEX_BUS, session_path), OBEX_PBAP_IFACE,
        )

        contacts = self._pull_book(bus, pbap, "internal", "pb")
        history = self._pull_book(bus, pbap, "internal", "cch")

        # Persist cache — atomically (a power cut mid-write must not leave
        # a truncated file) and 0600: contacts and call history are personal
        # data of the phone owner.
        try:
            atomic_write_json(_cache_path(addr), {
                "addr": addr,
                "contacts": contacts,
                "history": history,
                "pulled_at": int(time.time()),
            }, mode=0o600)
        except (OSError, TypeError, ValueError) as e:
            log.debug("PBAP cache write failed: %s", e)

        # Cache keeps the raw vCard-parsed records (full numbers list);
        # the bus carries the flattened shape the A8 dialer renders.
        self._bus.publish("bt.contacts", _to_ui_contacts(contacts))
        self._bus.publish("bt.call_history", _to_ui_history(history))
        log.info("PBAP %s: %d contacts, %d history entries",
                 addr, len(contacts), len(history))

        try:
            client.RemoveSession(session_path)
        except dbus.exceptions.DBusException:
            pass

    def _pull_book(self, bus, pbap, location: str,
                   book: str) -> list[dict[str, Any]]:
        try:
            pbap.Select(location, book)
        except dbus.exceptions.DBusException as e:
            log.debug("PBAP Select(%s,%s) failed: %s", location, book, e)
            return []
        try:
            ret = pbap.PullAll(
                "",
                dbus.Dictionary({"Format": "vcard30"}, signature="sv"),
            )
        except dbus.exceptions.DBusException as e:
            log.warning("PBAP PullAll(%s) failed: %s — phone may have "
                        "denied phonebook share", book, e)
            return []

        # obexd >= 5 returns (transfer_object_path, properties): the
        # PullAll is ASYNCHRONOUS. The vCards land in the file named by
        # properties["Filename"] only once the Transfer1 reaches
        # "complete" — obexd then removes the transfer object. Treating
        # the returned object path as a filename (it starts with "/")
        # and open()ing it is the classic bug that yields zero contacts.
        # Very old obexd returned the bytes/file path inline; handle both.
        if isinstance(ret, (tuple, list)) and len(ret) == 2 \
                and str(ret[0]).startswith("/org/bluez/obex/"):
            transfer_path, props = ret
            filename = str(props.get("Filename", "")) if props else ""
            if not self._await_transfer(bus, transfer_path):
                log.warning("PBAP %s transfer did not complete", book)
                return []
            if not filename or not os.path.exists(filename):
                log.warning("PBAP %s: transfer file %r missing", book, filename)
                return []
            try:
                with open(filename, errors="replace") as f:
                    blob = f.read()
            except OSError as e:
                log.warning("PBAP %s read failed: %s", book, e)
                return []
            finally:
                try:
                    os.unlink(filename)  # obexd leaves the temp file behind
                except OSError:
                    pass
        else:
            blob = ret[0] if isinstance(ret, (tuple, list)) else ret
            if isinstance(blob, str) and blob.startswith("/") \
                    and os.path.exists(blob):
                try:
                    with open(blob) as f:
                        blob = f.read()
                except OSError:
                    return []
            if isinstance(blob, (bytes, bytearray)):
                blob = bytes(blob).decode("utf-8", errors="replace")
        return _parse_vcards(blob or "")

    def _await_transfer(self, bus, path: str,
                        timeout: float = PULL_TIMEOUT_S) -> bool:
        """Block until an obexd Transfer1 finishes.

        Polls the transfer's ``Status`` until ``complete``. obexd removes
        the object the instant it completes, so a vanished object (the
        Properties.Get raises UnknownObject) counts as success — the
        caller still verifies the file exists before reading.
        """
        props = dbus.Interface(
            bus.get_object(OBEX_BUS, path),
            "org.freedesktop.DBus.Properties",
        )
        # Monotonic: the pull runs right when the phone's PAN comes up and
        # bcm-timesync may move the wall clock by hours (also backwards).
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                status = str(props.Get("org.bluez.obex.Transfer1", "Status"))
            except dbus.exceptions.DBusException:
                # Object gone — obexd drops completed transfers immediately.
                return True
            if status == "complete":
                return True
            if status == "error":
                return False
            time.sleep(0.15)
        return False


def start_phonebook_sync(event_bus: EventBus, config: Any = None) -> PhonebookSync:
    """Entry point — call once from main.py after BluetoothManager init."""
    settle = settle_from_config(config)
    sync = PhonebookSync(event_bus, settle_sec=settle)
    log.info("PBAP phonebook sync ready (subscribed to bt.connected, settle %.0fs)", settle)
    return sync
