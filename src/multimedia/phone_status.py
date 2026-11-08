"""Phone status for the top bar: battery, signal and operator of the phone.

Why this exists
---------------
The phone is connected over Bluetooth practically all the time, and oFono
(the HFP backend, see ``config/wireplumber/.../51-bcm-hfp-ofono.conf``)
already receives the phone's indicators over HFP: battery charge, signal
strength, service/roaming and the operator name. Nothing showed them. This
module reads them and publishes one small ``bt.phone_status`` record that
web_viewer puts into the dashboard payload, and ``components/appbar.js``
draws as a signal / operator / battery cluster after the date.

Enabled by ``modules.phone_status`` (subsystem, default off — production
unchanged; the test config turns it on). main.py starts it next to the
phonebook, only when Bluetooth is enabled. Settings: ``bluetooth.phone_status``
(:data:`DEFAULTS`).

Data sources. The oFono names, types and value ranges below were checked
against the oFono sources (GitHub mirror of git.kernel.org/pub/scm/network/
ofono/ofono.git): ``doc/handsfree-api.txt``, ``doc/network-api.txt``,
``doc/modem-api.txt``, ``plugins/hfp_hf_bluez5.c`` (modem path) and
``drivers/hfpmodem/network-registration.c`` (Strength = indicator * 20); the
battery fallback is BlueZ ``org.bluez.Battery1.Percentage`` (byte 0-100). To
look at the real values on the car, read-only::

    dbus-send --system --print-reply --dest=org.ofono / org.ofono.Manager.GetModems

and ``.../org.ofono.Handsfree.GetProperties`` /
``org.ofono.NetworkRegistration.GetProperties`` on the modem path it prints):

* ``org.ofono.Manager.GetModems`` -> the HFP modem of OUR phone: the one whose
  object path contains ``dev_<MAC with underscores>`` (oFono names its HFP
  modems after the BlueZ device, e.g. ``/hfp/org/bluez/hci0/dev_AA_BB_…``).
  Its ``Interfaces`` property tells which of the two interfaces below exist
  (an unpowered modem — phone not connected over HFP — lists none).
* ``org.ofono.Handsfree.GetProperties`` -> ``BatteryChargeLevel`` (byte 0-5,
  the HFP ``battchg`` indicator) -> ``battery_pct = level * 20``.
* ``org.ofono.NetworkRegistration.GetProperties`` -> ``Strength`` (0-100 %,
  oFono scales the HFP ``signal`` indicator 0-5 by 20), ``Name`` (operator,
  from ``AT+COPS?``) and ``Status`` (registered / roaming / searching /
  denied / unknown / unregistered). ``Strength`` is optional in the API and
  an Audio Gateway may report no operator at all -> those fields stay None
  and the bar shows what it has (often just the battery).
* Fallback for the battery only: BlueZ ``org.bluez.Battery1.Percentage`` on
  ``/org/bluez/hciX/dev_<MAC>`` (found via ObjectManager.GetManagedObjects)
  — used when oFono has no modem / no battery level for the phone.

Radio traffic: ``NetworkRegistration.GetProperties`` and BlueZ ``Battery1``
are cache reads (the phone pushes indicator changes on its own). The FIRST
``Handsfree.GetProperties`` after each HFP connection is not: oFono
(``src/handsfree.c``) fills its cache then and sends ONE ``AT+CNUM`` to the
phone over the already open HFP link; later calls are cache reads too. That
single AT command is tiny next to the HFP connection setup itself, so the
first read still happens right after ``bt.connected`` (the AA wireless
bootstrap runs on its own RFCOMM channel). While that query is pending
another caller gets ``org.ofono.Error.InProgress``, and a phone slow to
answer only costs that one read: it times out after ``DBUS_TIMEOUT_S``
(2 s), the battery falls back to BlueZ, and the next poll normally reads
the cache.

Polling: right after every ``bt.connected`` and then every ``poll_sec`` (20 s)
while the phone is connected; ``bt.disconnected`` stops it and publishes
``available: False``. When neither oFono nor BlueZ (nor dbus-python) is
there at all, the next try waits ``retry_sec`` (120 s) and ONE warning is
logged per reason — a missing service is a state, not a crash.

D-Bus: a PRIVATE system-bus connection (``dbus.SystemBus(private=True)``,
blocking calls, no main loop integration), never the shared connection that
bluetooth.py's GLib monitors run on — a slow or failing read here must not
touch their signal handling. Calls go to a service only when it already
owns its bus name, so a read never D-Bus-activates oFono/BlueZ.

Published on ``bt.phone_status`` (only when a field changed; ``ts`` = wall
time of that change)::

    {available, battery_pct, signal_pct, operator, registration, roaming,
     source, ts}

    battery_pct / signal_pct: int 0-100 or None
    operator:     str (no control/bidi characters, single-spaced, <= 24
                  characters) or None
    registration: one of REGISTRATION_STATES or None; roaming: bool or None
    source:       'ofono' | 'bluez' | None (None <=> available False)

Security: everything read from D-Bus comes from the phone (or whoever named
a nearby network) — numbers are type-checked and clamped, the operator
cleaned and cut, the MAC validated before it is used to pick a modem.
web_viewer re-sanitises the record (:func:`sanitize_status`) and the UI
writes the operator with textContent only.
"""

from __future__ import annotations

import math
import re
import threading
import time
from typing import Any, Callable, Optional

from src.core.logger import get_logger
from src.core.notifications import clean_text
from src.network.phone_tether import normalize_mac

log = get_logger("multimedia.phone_status")

try:
    import dbus
    HAS_DBUS = True
except ImportError:      # dev machines / CI: the module degrades to "unavailable"
    dbus = None
    HAS_DBUS = False

TOPIC = "bt.phone_status"

OFONO_SERVICE = "org.ofono"
OFONO_MANAGER_IFACE = "org.ofono.Manager"
OFONO_HANDSFREE_IFACE = "org.ofono.Handsfree"
OFONO_NETREG_IFACE = "org.ofono.NetworkRegistration"
BLUEZ_SERVICE = "org.bluez"
BLUEZ_BATTERY_IFACE = "org.bluez.Battery1"
OBJECT_MANAGER_IFACE = "org.freedesktop.DBus.ObjectManager"

#: oFono NetworkRegistration.Status values (doc/network-api.txt).
REGISTRATION_STATES = ("registered", "roaming", "searching", "denied",
                       "unknown", "unregistered")
SOURCES = ("ofono", "bluez")

OPERATOR_MAX = 24
#: HFP battchg indicator range (Handsfree.BatteryChargeLevel).
BATTERY_LEVEL_MAX = 5
#: Bounded work per pass: modems looked at, characters of a raw string.
MAX_MODEMS = 16
MAX_RAW_TEXT = 256
MAX_MANAGED_OBJECTS = 4096
DBUS_TIMEOUT_S = 2.0

#: Code defaults for ``bluetooth.phone_status``.
DEFAULTS: dict[str, Any] = {
    # Read interval while the phone is connected. The phone pushes indicator
    # changes to oFono itself; this only decides how stale the bar may get.
    "poll_sec": 20,
    # Next try when NOTHING is reachable (no dbus-python, no oFono, no BlueZ).
    "retry_sec": 120,
}

#: The record published while no phone data is available.
UNAVAILABLE: dict[str, Any] = {
    "available": False, "battery_pct": None, "signal_pct": None, "operator": None,
    "registration": None, "roaming": None, "source": None,
}

# D-Bus error names meaning "the service is not there" (not running, not
# activatable) or "the bus connection is gone".
_SERVICE_GONE = (
    "org.freedesktop.DBus.Error.ServiceUnknown",
    "org.freedesktop.DBus.Error.NameHasNoOwner",
)
_CONNECTION_GONE = (
    "org.freedesktop.DBus.Error.Disconnected",
    "org.freedesktop.DBus.Error.NoServer",
    "org.freedesktop.DBus.Error.FileNotFound",
)


class ServiceUnavailable(Exception):
    """D-Bus, dbus-python or the asked service (org.ofono / org.bluez) is
    not there. Raised by readers; any OTHER exception from a reader call is a
    failed read of that one value (object vanished, timeout, …)."""


# ── pure helpers (tested directly) ─────────────────────────────────────────

def _is_number(value: Any) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def mac_path_token(mac: str) -> str:
    """``AA:BB:CC:DD:EE:FF`` -> ``dev_AA_BB_CC_DD_EE_FF`` (BlueZ/oFono path part)."""
    return "dev_" + mac.replace(":", "_")


def _path_has_device(path: Any, mac: str) -> bool:
    """True if ``path`` has the path component ``dev_<MAC>`` (whole component,
    hex case-insensitive). ``…/dev_AA_…_FF0`` is a different device."""
    if not isinstance(path, str) or len(path) > MAX_RAW_TEXT:
        return False
    token = mac_path_token(mac).lower()
    return token in path.lower().split("/")


def interfaces_of(props: Any) -> list[str]:
    """oFono modem ``Interfaces`` property as a list of strings (else [])."""
    if not isinstance(props, dict):
        return []
    ifaces = props.get("Interfaces")
    if not isinstance(ifaces, (list, tuple)):
        return []
    return [i for i in ifaces[:64] if isinstance(i, str)]


def modem_for_mac(modems: Any, mac: str) -> Optional[tuple[str, dict]]:
    """The oFono modem of the phone ``mac`` among ``[(path, props), …]``.

    Matched on the object path (``…/dev_AA_BB_…``), never on a name the phone
    chose. If several match (should not happen), the one that actually
    offers Handsfree/NetworkRegistration wins, then the first in path order.
    """
    if not isinstance(modems, (list, tuple)):
        return None
    found: list[tuple[str, dict]] = []
    for entry in list(modems)[:MAX_MODEMS]:
        if not isinstance(entry, (list, tuple)) or len(entry) != 2:
            continue
        path, props = entry
        if _path_has_device(path, mac):
            found.append((path, props if isinstance(props, dict) else {}))
    if not found:
        return None

    def useful(item: tuple[str, dict]) -> int:
        ifaces = interfaces_of(item[1])
        return int(OFONO_HANDSFREE_IFACE in ifaces) + int(OFONO_NETREG_IFACE in ifaces)

    found.sort(key=lambda item: (-useful(item), item[0]))
    return found[0]


def battery_pct_from_level(value: Any) -> Optional[int]:
    """Handsfree ``BatteryChargeLevel`` (0-5) -> percent (0, 20 … 100)."""
    if not _is_number(value):
        return None
    level = min(max(int(round(value)), 0), BATTERY_LEVEL_MAX)
    return level * 100 // BATTERY_LEVEL_MAX


def percent(value: Any) -> Optional[int]:
    """A 0-100 value (``Strength``, ``Battery1.Percentage``), clamped."""
    if not _is_number(value):
        return None
    return min(max(int(round(value)), 0), 100)


def clean_operator(value: Any) -> Optional[str]:
    """Operator name for the bar: printable, single-spaced, <= 24 chars.

    The name comes from the phone network (or a fake base station) —
    control and bidi-override characters are removed so it cannot break or
    reorder the bar; the UI writes it with textContent anyway. Empty -> None.
    """
    if not isinstance(value, str):
        return None
    text = clean_text(value[:MAX_RAW_TEXT], OPERATOR_MAX).strip()
    return text or None


def registration_of(value: Any) -> Optional[str]:
    """``NetworkRegistration.Status`` -> a known state; unknown text ->
    ``'unknown'``; missing / not a string -> None."""
    if not isinstance(value, str):
        return None
    state = value.strip().lower()
    return state if state in REGISTRATION_STATES else "unknown"


def _status_record(battery: Optional[int], signal: Optional[int], operator: Optional[str],
                   registration: Optional[str], source: Optional[str]) -> dict[str, Any]:
    if source not in SOURCES:
        return dict(UNAVAILABLE)
    return {
        "available": True,
        "battery_pct": battery,
        "signal_pct": signal,
        "operator": operator,
        "registration": registration,
        "roaming": None if registration is None else registration == "roaming",
        "source": source,
    }


def read_phone_status(reader: Any, mac: str) -> tuple[dict[str, Any], set[str]]:
    """One snapshot of the phone ``mac`` through ``reader``.

    Returns ``(record, down)``: the record as published (without ``ts``) and
    the set of services that were not reachable (``'ofono'``, ``'bluez'``).
    Never raises — every failed call just leaves its fields None.
    """
    down: set[str] = set()
    battery = signal = None
    operator = registration = None
    from_ofono = from_bluez = False

    try:
        modems = reader.ofono_modems()
    except ServiceUnavailable:
        down.add("ofono")
        modems = []
    except Exception as e:
        log.debug("Phone status: GetModems failed: %s", e)
        modems = []

    modem = modem_for_mac(modems, mac) if modems else None
    if modem is not None:
        path, props = modem
        ifaces = interfaces_of(props)
        if OFONO_HANDSFREE_IFACE in ifaces:
            hf = _ofono_props(reader, path, OFONO_HANDSFREE_IFACE, down)
            battery = battery_pct_from_level(hf.get("BatteryChargeLevel"))
            from_ofono = from_ofono or battery is not None
        if OFONO_NETREG_IFACE in ifaces and "ofono" not in down:
            nr = _ofono_props(reader, path, OFONO_NETREG_IFACE, down)
            signal = percent(nr.get("Strength"))
            operator = clean_operator(nr.get("Name"))
            registration = registration_of(nr.get("Status"))
            from_ofono = from_ofono or any(
                v is not None for v in (signal, operator, registration))

    if battery is None:
        try:
            battery = percent(reader.bluez_battery(mac))
        except ServiceUnavailable:
            down.add("bluez")
        except Exception as e:
            log.debug("Phone status: BlueZ Battery1 read failed: %s", e)
        from_bluez = battery is not None

    source = "ofono" if from_ofono else ("bluez" if from_bluez else None)
    return _status_record(battery, signal, operator, registration, source), down


def _ofono_props(reader: Any, path: str, interface: str, down: set[str]) -> dict:
    try:
        props = reader.ofono_properties(path, interface)
    except ServiceUnavailable:
        down.add("ofono")
        return {}
    except Exception as e:
        # e.g. the modem went away between GetModems and this call.
        log.debug("Phone status: %s.GetProperties(%s) failed: %s", interface, path, e)
        return {}
    return props if isinstance(props, dict) else {}


def sanitize_status(value: Any) -> Optional[dict[str, Any]]:
    """``bt.phone_status`` -> the dashboard payload's ``phone_status``.

    Defence in depth for web_viewer: whatever is on the bus (another module,
    an IPC client) passes only in the documented shape. Never published (the
    module is off — production) -> None, and the bar draws no cluster.
    """
    if not isinstance(value, dict):
        return None
    if value.get("available") is not True:
        return dict(UNAVAILABLE)
    registration = value.get("registration")
    registration = registration if registration in REGISTRATION_STATES else None
    source = value.get("source")
    record = _status_record(percent(value.get("battery_pct")),
                            percent(value.get("signal_pct")),
                            clean_operator(value.get("operator")),
                            registration,
                            source if isinstance(source, str) else None)
    return record


def _cfg_get(config: Any, dotpath: str, default: Any = None) -> Any:
    """Read ``a.b.c`` from a BCMConfig (dotted ``get``) or nested dicts."""
    if config is None:
        return default
    getter = getattr(config, "get", None)
    if callable(getter):
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


def _number_opt(value: Any, default: float, lo: float, hi: float, name: str) -> float:
    if not _is_number(value):
        if value is not None:
            log.warning("bluetooth.phone_status.%s=%r is not a number — using %s",
                        name, value, default)
        return float(default)
    return float(min(max(value, lo), hi))


# ── the default reader: blocking calls on a private system-bus connection ──

def _plain(value: Any, depth: int = 0) -> Any:
    """dbus-python values -> plain Python, bounded (depth, items, length)."""
    if depth > 4:
        return None
    if HAS_DBUS and isinstance(value, dbus.Boolean):     # an int subclass
        return bool(value)
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value)
    if isinstance(value, str):
        return str(value)[:MAX_RAW_TEXT]
    if isinstance(value, dict):
        out = {}
        for i, (k, v) in enumerate(value.items()):
            if i >= 64:
                break
            out[str(k)[:128]] = _plain(v, depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [_plain(v, depth + 1) for v in list(value)[:64]]
    return None


class DBusPhoneReader:
    """Reads oFono/BlueZ over a PRIVATE system-bus connection.

    Private (``SystemBus(private=True)``) and without main-loop integration:
    bluetooth.py runs its oFono/AVRCP signal monitors on the shared
    connection with the GLib loop; these blocking calls must not run on (or
    stall) that one. Only the PhoneStatusMonitor worker thread uses it.
    """

    def __init__(self, timeout: float = DBUS_TIMEOUT_S) -> None:
        self._timeout = timeout
        self._bus: Any = None

    def _connection(self) -> Any:
        if not HAS_DBUS:
            raise ServiceUnavailable("dbus-python not installed")
        if self._bus is None:
            kwargs: dict[str, Any] = {"private": True}
            # NULL_MAIN_LOOP = "do not integrate with any loop": blocking calls
            # only, even though bluetooth.py set GLib as the default loop.
            null_loop = getattr(getattr(dbus, "mainloop", None), "NULL_MAIN_LOOP", None)
            if null_loop is not None:
                kwargs["mainloop"] = null_loop
            try:
                self._bus = dbus.SystemBus(**kwargs)
            except Exception as e:
                raise ServiceUnavailable(f"system bus: {_dbus_error_name(e)}") from None
        return self._bus

    def _call(self, service: str, path: str, interface: str, method: str) -> Any:
        bus = self._connection()
        try:
            # Only talk to a service that is already running: a call to a
            # well-known name without an owner would D-Bus-activate it.
            if not bus.name_has_owner(service):
                raise ServiceUnavailable(f"{service} not running")
            return bus.call_blocking(service, path, interface, method, "", (),
                                     timeout=self._timeout)
        except ServiceUnavailable:
            raise
        except Exception as e:
            name = _dbus_error_name(e)
            if name in _SERVICE_GONE:
                raise ServiceUnavailable(f"{service}: {name}") from None
            if name in _CONNECTION_GONE:
                self.close()
                raise ServiceUnavailable(f"system bus: {name}") from None
            raise

    def ofono_modems(self) -> list[tuple[str, dict]]:
        raw = self._call(OFONO_SERVICE, "/", OFONO_MANAGER_IFACE, "GetModems")
        out: list[tuple[str, dict]] = []
        for entry in list(raw or [])[:MAX_MODEMS]:
            try:
                path, props = entry
            except (TypeError, ValueError):
                continue
            plain = _plain(props)
            out.append((str(path)[:MAX_RAW_TEXT], plain if isinstance(plain, dict) else {}))
        return out

    def ofono_properties(self, path: str, interface: str) -> dict:
        raw = self._call(OFONO_SERVICE, path, interface, "GetProperties")
        plain = _plain(raw)
        return plain if isinstance(plain, dict) else {}

    def bluez_battery(self, mac: str) -> Any:
        """``Battery1.Percentage`` of ``/org/bluez/hci*/dev_<MAC>`` or None."""
        objects = self._call(BLUEZ_SERVICE, "/", OBJECT_MANAGER_IFACE, "GetManagedObjects")
        want = re.compile(r"^/org/bluez/hci\d{1,3}/" + re.escape(mac_path_token(mac)) + "$",
                          re.IGNORECASE)
        for i, (path, ifaces) in enumerate((objects or {}).items()):
            if i >= MAX_MANAGED_OBJECTS:
                break
            if not want.match(str(path)):
                continue
            battery = ifaces.get(BLUEZ_BATTERY_IFACE) if hasattr(ifaces, "get") else None
            if battery is not None and hasattr(battery, "get"):
                return _plain(battery.get("Percentage"))
        return None

    def close(self) -> None:
        bus, self._bus = self._bus, None
        if bus is not None:
            try:
                bus.close()
            except Exception:
                pass


def _dbus_error_name(exc: BaseException) -> str:
    getter = getattr(exc, "get_dbus_name", None)
    if callable(getter):
        try:
            return getter() or type(exc).__name__
        except Exception:
            pass
    return type(exc).__name__


# ── the monitor ────────────────────────────────────────────────────────────

class PhoneStatusMonitor:
    """Polls the connected phone's status and publishes ``bt.phone_status``.

    Args:
        config: BCMConfig (dotted ``get``) or a plain nested dict.
        event_bus: EventBus (``subscribe``/``publish``/``get_last``).
        reader: object with ``ofono_modems()``, ``ofono_properties(path,
            iface)``, ``bluez_battery(mac)`` and ``close()`` (raising
            :class:`ServiceUnavailable` for a missing service) — the test
            seam; default :class:`DBusPhoneReader`.
        clock: monotonic seconds (kept for symmetry with the other monitors;
            scheduling is relative waits only).
        wall_clock: epoch seconds for the published ``ts``.
    """

    def __init__(self, config: Any, event_bus: Any, reader: Any = None,
                 clock: Callable[[], float] = time.monotonic,
                 wall_clock: Callable[[], float] = time.time) -> None:
        self._config = config
        self._bus = event_bus
        self._reader = reader if reader is not None else DBusPhoneReader()
        self._clock = clock
        self._wall = wall_clock

        section = _cfg_get(config, "bluetooth.phone_status", {})
        if not isinstance(section, dict):
            section = {}
        self._poll_sec = _number_opt(section.get("poll_sec"), DEFAULTS["poll_sec"],
                                     5, 600, "poll_sec")
        self._retry_sec = _number_opt(section.get("retry_sec"), DEFAULTS["retry_sec"],
                                      self._poll_sec, 3600, "retry_sec")

        # tick() runs one pass at a time (worker thread, or a test).
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # Phone presence from the bus callbacks (no I/O there). _gen bumps on
        # every connect/disconnect so a read that straddles one is dropped.
        self._ev_lock = threading.Lock()
        self._connected = False
        self._addr: Optional[str] = None
        self._gen = 0
        self._bt_events = 0

        self._wait: Optional[float] = None      # None = idle until woken
        # Guards the stop check + publish: stop() must not wait for a pass
        # stuck in a D-Bus call (self._lock), yet its "available: False" has
        # to be the LAST record — a pass finishing later stays quiet.
        self._pub_lock = threading.Lock()
        self._record: Optional[dict[str, Any]] = None
        self._ts = 0.0
        self._warned: set[str] = set()

    # ── read-only views (UI / tests) ──────────────────────────────────────

    @property
    def state(self) -> Optional[dict[str, Any]]:
        """Last published record (copy, with ``ts``) or None."""
        if self._record is None:
            return None
        return dict(self._record, ts=self._ts)

    @property
    def poll_sec(self) -> float:
        return self._poll_sec

    @property
    def retry_sec(self) -> float:
        return self._retry_sec

    def next_wait(self) -> Optional[float]:
        """Seconds until the next pass, or None (no phone: wait for an event)."""
        return self._wait

    def _subscriptions(self) -> tuple:
        return (("bt.connected", self._on_bt_connected),
                ("bt.disconnected", self._on_bt_disconnected),
                ("power.shutting_down", self._on_shutdown))

    # ── lifecycle ─────────────────────────────────────────────────────────

    def start(self) -> None:
        """Subscribe, seed the phone state and start the worker thread."""
        if self._thread is not None:
            return
        for topic, cb in self._subscriptions():
            self._bus.subscribe(topic, cb)
        self.seed_from_bus()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="phone-status")
        self._thread.start()
        log.info("Phone status monitor started (poll=%ds, retry=%ds, D-Bus=%s)",
                 self._poll_sec, self._retry_sec,
                 "yes" if HAS_DBUS else "no — dbus-python missing")

    def seed_from_bus(self) -> None:
        """The phone may have connected before we subscribed (Bluetooth
        starts first): take the newer of the last bt.connected /
        bt.disconnected, unless a callback already told us more."""
        try:
            last_c = self._bus.get_last("bt.connected")
            last_d = self._bus.get_last("bt.disconnected")
        except Exception:
            return
        with self._ev_lock:
            if self._bt_events:
                return
            if last_c is not None and last_c[0] and (last_d is None or last_c[1] > last_d[1]):
                self._connected = True
                self._addr = self._address_of(last_c[0])
                self._gen += 1

    def stop(self) -> None:
        """Stop polling and hide the cluster (``available: False``)."""
        if self._stop.is_set():
            return
        self._stop.set()
        self._wake.set()
        for topic, cb in self._subscriptions():
            try:
                self._bus.unsubscribe(topic, cb)
            except Exception:
                pass
        self._publish(dict(UNAVAILABLE), force=True)
        if self._thread is None:
            self._close_reader()        # no worker: nobody else uses it
        log.info("Phone status monitor stopped")

    def _on_shutdown(self, topic: str, value: Any, timestamp: float) -> None:
        if value:
            self.stop()

    def _run(self) -> None:
        while not self._stop.is_set():
            # Clear BEFORE the pass: an event during tick() then makes the
            # wait below return at once instead of being lost.
            self._wake.clear()
            try:
                self.tick()
            except Exception:
                log.exception("Phone status pass failed")
                self._wait = self._retry_sec
            self._wake.wait(self._wait)
        self._close_reader()

    def _close_reader(self) -> None:
        close = getattr(self._reader, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass

    # ── bus callbacks: record and wake, no I/O (async dispatcher thread) ──

    @staticmethod
    def _address_of(value: Any) -> Optional[str]:
        if isinstance(value, dict):
            addr = value.get("address")
            return addr if isinstance(addr, str) else None
        return None

    def _on_bt_connected(self, topic: str, value: Any, timestamp: float) -> None:
        with self._ev_lock:
            self._bt_events += 1
            self._gen += 1
            if value:
                self._connected = True
                self._addr = self._address_of(value)
            else:
                self._connected = False
        self._wake.set()

    def _on_bt_disconnected(self, topic: str, value: Any, timestamp: float) -> None:
        addr = normalize_mac(self._address_of(value))
        with self._ev_lock:
            self._bt_events += 1
            current = normalize_mac(self._addr)
            # BCM tracks one phone; a disconnect naming another device
            # (stale event, a second device) must not hide our phone's status.
            if addr and current and addr != current:
                return
            self._connected = False
            self._gen += 1
        self._wake.set()

    # ── one pass ──────────────────────────────────────────────────────────

    def tick(self) -> dict[str, Any]:
        """Read once (if a phone is connected) and publish on change.
        Returns the current record (without ``ts``)."""
        with self._lock:
            if self._stop.is_set():
                return dict(self._record or UNAVAILABLE)
            with self._ev_lock:
                connected, addr, gen = self._connected, self._addr, self._gen
            if not connected:
                self._wait = None
                self._publish(dict(UNAVAILABLE))
                return dict(UNAVAILABLE)

            mac, why = self._resolve_mac(addr)
            if mac is None:
                self._warn_once(f"mac:{why}", f"Phone status: {why} — nothing read")
                self._wait = None       # a new bt.connected wakes us
                self._publish(dict(UNAVAILABLE))
                return dict(UNAVAILABLE)

            record, down = read_phone_status(self._reader, mac)

            with self._ev_lock:
                stale = gen != self._gen or not self._connected
            if stale or self._stop.is_set():
                # The phone went away / changed during the read: this result
                # belongs to the old connection. The wake flag is already set.
                return dict(self._record or UNAVAILABLE)

            if {"ofono", "bluez"} <= down:
                self._warn_once("nothing", "Phone status unavailable: neither oFono nor "
                                "BlueZ answer on the system bus"
                                + ("" if HAS_DBUS else " (dbus-python not installed)")
                                + f" — next try every {int(self._retry_sec)} s")
                self._wait = self._retry_sec
            else:
                if "ofono" in down:
                    self._warn_once("ofono", "Phone status: oFono not reachable — no "
                                    "signal/operator in the top bar (battery from BlueZ "
                                    "if the phone reports it)")
                self._wait = self._poll_sec
            self._publish(record)
            return record

    def _resolve_mac(self, addr: Optional[str]) -> tuple[Optional[str], str]:
        """The phone's address: from bt.connected, else the last one used.
        An INVALID value never falls through to another source."""
        if addr:
            mac = normalize_mac(addr)
            if mac is None:
                return None, "invalid phone address in bt.connected"
            return mac, ""
        last = _cfg_get(self._config, "multimedia.last_bt_device", "")
        if last:
            mac = normalize_mac(last)
            if mac is None:
                return None, "invalid multimedia.last_bt_device"
            return mac, ""
        return None, "phone address unknown (no address in bt.connected, no last_bt_device)"

    # ── publishing ────────────────────────────────────────────────────────

    def _publish(self, record: dict[str, Any], force: bool = False) -> bool:
        """Publish ``bt.phone_status`` if a field changed. True if published."""
        with self._pub_lock:
            return self._publish_locked(record, force)

    def _publish_locked(self, record: dict[str, Any], force: bool) -> bool:
        if self._stop.is_set() and not force:
            return False
        if record == self._record:
            return False
        was = self._record
        self._record = dict(record)
        self._ts = self._wall()
        if was is None or was.get("available") != record["available"] \
                or was.get("source") != record["source"]:
            if record["available"]:
                log.info("Phone status: available via %s (battery=%s%%, signal=%s%%, "
                         "operator=%r, %s)", record["source"], record["battery_pct"],
                         record["signal_pct"], record["operator"], record["registration"])
            elif was is not None and was.get("available"):
                log.info("Phone status: unavailable")
        else:
            log.debug("Phone status: %s", record)
        try:
            self._bus.publish(TOPIC, dict(record, ts=self._ts))
        except Exception:
            log.exception("Publishing %s failed", TOPIC)
        return True

    def _warn_once(self, key: str, message: str) -> None:
        if key not in self._warned:
            self._warned.add(key)
            log.warning(message)


def start_phone_status(config: Any, event_bus: Any, reader: Any = None) -> PhoneStatusMonitor:
    """Entry point — called once from main.py (Bluetooth on, modules.phone_status)."""
    monitor = PhoneStatusMonitor(config, event_bus, reader=reader)
    monitor.start()
    return monitor
