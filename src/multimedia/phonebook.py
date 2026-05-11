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
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Any, Optional

from src.core.event_bus import EventBus
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


class PhonebookSync:
    """Drives obexd PBAP sessions per connected BT device."""

    def __init__(self, event_bus: EventBus):
        self._bus = event_bus
        self._lock = threading.Lock()
        self._active_addr: Optional[str] = None
        self._stop_flag = False
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
            self._bus.publish("bt.contacts", data.get("contacts", []))
            self._bus.publish("bt.call_history", data.get("history", []))
            log.info("PBAP: served cached phonebook for %s (%d contacts)",
                     addr, len(data.get("contacts", [])))
        except Exception:
            log.debug("PBAP: cache read failed for %s", addr)

    def _sync_safe(self, addr: str) -> None:
        try:
            self._sync(addr)
        except Exception:
            log.exception("PBAP sync raised for %s", addr)

    def _sync(self, addr: str) -> None:
        with self._lock:
            if self._active_addr == addr:
                return
            self._active_addr = addr
            self._stop_flag = False

        # Give the phone a moment to authorise the PBAP service after
        # the A2DP link comes up — Android delays the PBAP authorise
        # popup until after audio is rolling.
        time.sleep(3)

        bus = dbus.SessionBus()
        try:
            client = dbus.Interface(
                bus.get_object(OBEX_BUS, OBEX_ROOT), OBEX_CLIENT_IFACE,
            )
        except dbus.exceptions.DBusException:
            log.warning("obexd not running on session bus — install "
                        "bluez-obexd and ensure the user session is up")
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

        contacts = self._pull_book(pbap, "internal", "pb")
        history = self._pull_book(pbap, "internal", "cch")

        # Persist cache
        try:
            with open(_cache_path(addr), "w") as f:
                json.dump({
                    "addr": addr,
                    "contacts": contacts,
                    "history": history,
                    "pulled_at": int(time.time()),
                }, f)
        except OSError as e:
            log.debug("PBAP cache write failed: %s", e)

        self._bus.publish("bt.contacts", contacts)
        self._bus.publish("bt.call_history", history)
        log.info("PBAP %s: %d contacts, %d history entries",
                 addr, len(contacts), len(history))

        try:
            client.RemoveSession(session_path)
        except dbus.exceptions.DBusException:
            pass

    def _pull_book(self, pbap, location: str, book: str) -> list[dict[str, Any]]:
        try:
            pbap.Select(location, book)
        except dbus.exceptions.DBusException as e:
            log.debug("PBAP Select(%s,%s) failed: %s", location, book, e)
            return []
        try:
            blob, _ = pbap.PullAll(
                "",
                dbus.Dictionary({"Format": "vcard30"}, signature="sv"),
            )
        except dbus.exceptions.DBusException as e:
            log.warning("PBAP PullAll(%s) failed: %s — phone may have "
                        "denied phonebook share", book, e)
            return []
        # PullAll returns the path of a transient file or a string blob
        # depending on obexd version. Newer obexd returns a path; older
        # returns the bytes inline.
        if isinstance(blob, str) and blob.startswith("/"):
            try:
                with open(blob) as f:
                    blob = f.read()
            except OSError:
                return []
        if isinstance(blob, (bytes, bytearray)):
            blob = bytes(blob).decode("utf-8", errors="replace")
        return _parse_vcards(blob or "")


def start_phonebook_sync(event_bus: EventBus) -> PhonebookSync:
    """Entry point — call once from main.py after BluetoothManager init."""
    sync = PhonebookSync(event_bus)
    log.info("PBAP phonebook sync ready (subscribed to bt.connected)")
    return sync
