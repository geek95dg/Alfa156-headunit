"""The phone that lives in the car: USB tethering, GPS, battery and clock via adb.

Why this exists
---------------
The test car gets a second, permanently mounted phone (a rooted Redmi Note 8
Pro on a USB cable, plan section C). It gives the head unit an uplink over
USB tethering (``rndis``/``ncm`` interface, managed by NetworkManager), its
GNSS position (an NMEA TCP server app on the phone, reached through
``adb forward``) and a trusted clock; BCM in turn keeps an eye on its
battery and temperature, because a phone under the headliner in summer is a
fire risk. The driver's own phone keeps Android Auto and calls; its
Bluetooth PAN (``phone_tether``, route metric 750) stays as the fallback
uplink — this link uses 650, so the kernel prefers it while it is up and
falls back by itself when the cable or the tethering goes.

Enabled by ``modules.car_phone`` only (registry module, default off; the
production config does not name it). Settings live in ``network.car_phone``
(see :data:`DEFAULTS`). ``modules.car_phone_hotspot`` (requires car_phone)
adds the read-only Wi-Fi hotspot status (plan D2) — it is the ONLY switch of
that feature, there is no ``hotspot`` sub-key.

One reconciliation step (:meth:`CarPhone.tick`)
-----------------------------------------------
1. ``adb devices -l`` (20 s timeout on the first call — it may start the adb
   server — then 8 s). Parsed strictly: the "List of devices" header and
   ``* daemon …`` lines are skipped, the second token is the state. Exit 127
   => ``no_adb`` (hint ``install_adb``), 124 => ``adb_error``. Only USB
   transports (``usb:`` in the ``-l`` line) are picked automatically —
   never a device adb reaches over the network. With ``serial`` empty the
   module acts only when exactly ONE phone is in the ``device`` state;
   two => hint ``pin_serial``.
2. AOAP check: ``/sys/bus/usb/devices/*/idVendor,idProduct`` = 18d1:2d00…2d05
   means something switched a phone into Android Open Accessory mode — with
   the stock openDsh autoapp that is autoapp itself (it sends the AA
   handshake to EVERY USB device). Without a link => ``failed`` + hint
   ``aa_usb_probe`` and no ``setFunctions`` (fighting autoapp would loop);
   ``config/scripts/install-openauto.sh`` with ``BCM_AA_USB=0`` builds
   autoapp wireless-only.
3. ``nmcli -t -f NAME,DEVICE,STATE connection show --active``: our profile
   (``con_name``) active => ``nmcli -g GENERAL.IP-IFACE,IP4.ADDRESS,
   IP4.GATEWAY device show <dev>`` => ``connected``. An active link is
   ``connected`` whatever adb says (the cable carries the data; adb may be
   unauthorised or restarting).
4. No link: the profile is created when missing (nmcli exit 10) or corrected
   when it drifted — ``type ethernet``, ``ifname *``, ``match.driver
   rndis_host cdc_ncm`` (NOT ``cdc_ether``: the Huawei E3372 LTE stick of
   the future modem uses it), ``ipv4.method auto``, ``ipv4.route-metric
   650``, ``ipv6.method disabled``, ``connection.autoconnect yes``. Then
   ``adb -s S shell svc usb getFunctions`` (Android prints the answer on
   STDERR — both streams are parsed); the function missing =>
   ``svc usb setFunctions rndis`` (exits 0 even when it fails, so the result
   is only ever judged by a later ``getFunctions``) => ``tethering``, looked
   at again after ``settle_sec``. Three attempts without the function
   appearing => ``failed`` + hint ``tether_blocked``, with backoff. Function
   present but NetworkManager has no link after ``settle_sec`` => ONE
   ``nmcli --wait 30 connection up id <con>`` per backoff period.
5. GPS forward, every pass (a BCM restart kills the adb server and every
   forward with it): ``adb -s S forward --list``; the exact line
   ``S tcp:L tcp:R`` missing => ``adb -s S forward tcp:L tcp:R``. Never
   ``--remove-all`` (other forwards may belong to the agent of later plan
   items) and never ``wait-for-usb-device`` (blocks forever).
6. Every ``battery_sec``: ``adb -s S shell dumpsys battery`` — anchored
   ``key: value`` regexes; level 0-100, temperature in tenths of °C, status
   2/5 charging/full, health 3 overheat. ``UPDATES STOPPED`` (someone ran
   ``dumpsys battery set …``) only sets ``overridden``; BCM never runs
   ``dumpsys battery reset`` or anything else that changes the phone.
   Heat: ``warn_temp_c``/``critical_temp_c`` => notification
   ``car_phone_heat`` (warning/danger, re-announced at most every 60 s while
   hot), cleared below ``warn_temp_c - 3``.
7. Clock (plan D1), at most every 10 min and at once with a new phone: only
   with ``time_sync`` and when bcm-timesync has NOT succeeded within its
   last timer period (1 h + 15 min slack — the marker
   ``/run/bcm-timesync.ok`` is written on every success, boot-time based so
   a clock jump cannot fake it; the slack covers the timer's accuracy and
   curl's run time, or a healthy internet sync would be overridden just
   before every refresh). ``adb shell date +%s`` — the cable is trusted,
   unlike NMEA over UDP, which is NEVER used for the clock — validated as
   an integer >= 2025-01-01. A phone that lost its clock (battery run flat
   on a long stop, then switched on by hand) does NOT know the time:
   Android starts it at the ROM's build time (``ro.build.date.utc``) and
   counts from there until NITZ/NTP answer. Setting the head unit from that
   would step it back by months, and ``set-time`` writes the RTC too — then
   HTTPS ("certificate not yet valid") blocks bcm-timesync from repairing
   it, even after a power cut. So a reading is used only when:

   * it is more than 48 h after the build time (``adb shell getprop
     ro.build.date.utc``, read once per phone appearance; unreadable =>
     not used);
   * a step BACK by more than 1 h is confirmed by a second reading one
     check (10 min) later with the same drift (±5 s) — a clock that was
     just synced does not move against ours, one that is about to be
     corrected does;
   * the drift is >= ``time_sync_drift_s``.

   Then ``timedatectl set-time @<epoch>``.
8. Hotspot status (plan D2, ``modules.car_phone_hotspot``), every
   ``battery_sec``: read-only ``adb shell dumpsys tethering`` (Android 11+;
   ``dumpsys connectivity tethering`` on older releases). Unknown output =>
   ``None`` (the UI shows nothing). Switching the hotspot from BCM
   (``cmd wifi start-softap``) is future work, unverified on this ROM.

The only commands that change anything on the phone are ``svc usb
setFunctions`` and the ``adb forward`` listener on 127.0.0.1; on the head
unit it is the NM profile, ``connection up``, ``timedatectl set-time`` and
``systemctl start --no-block bcm-timesync.service`` (once per edge into
``connected``). The module never runs ``su``.

Published on ``net.car_phone`` (only when something changed)::

    {state, adb, serial, iface, ip, prefix, gateway, gps_forward, gps_port,
     battery_pct, temp_c, charging, full, plugged, health, overridden,
     hotspot_active, hotspot_clients, heat, time_synced_at, error, hint, since}

    state: disabled | no_adb | adb_error | no_device | unauthorized
           | tethering | connected | failed
    adb:   '' | device | unauthorized | offline | no_permissions | other
           | missing | error   (the picked phone's adb state / the tool)
    hint:  '' | authorize | pin_serial | tether_blocked | aa_usb_probe
           | install_adb
    serial: masked (first and last two characters)
    heat:  None | warning | danger (the battery temperature alarm)
    gps_port: local port of the GPS forward while it works (else None)
    since: wall-clock time (epoch s) the current state was entered

``net.car_phone.cmd.retry`` (Settings "Ponów", rate-limited by web_viewer)
drops a running backoff and the tethering attempt counter.

Security
--------
* Every command is an argv list with a timeout (``src.network._proc._run``,
  never a shell). ``adb shell`` JOINS its arguments into one command line
  for the phone's shell WITHOUT escaping — so every word sent to the phone
  is a fixed string from this file or a validated integer (ports); the
  serial is validated (:data:`SERIAL_RE`) and only ever passed to the LOCAL
  adb client after ``-s``.
* Everything parsed from adb/nmcli is validated before it is published;
  error text is cleaned and cut to 200 characters.
* adb runs with ``LC_ALL=C`` and ``HOME=/root`` (BCM runs as root; the key
  pair adb generates is ``/root/.android/adbkey`` — never in the repo).
  adb is used over USB only, never ``adb tcpip``.
* The adb SERVER (started by the first adb call, running as root) would
  listen on 127.0.0.1:5037 by default — reachable by every local user, the
  kiosk user too, and whoever talks to it gets a full ``adb shell`` on the
  phone and root-owned host listeners (``forward local:<path>`` unlinks
  that path before binding it). So every adb call carries
  ``ADB_SERVER_SOCKET=localfilesystem:/run/bcm-adb/adb.sock``: the server
  listens on a Unix socket in a directory only root can enter. The module
  creates that directory (0700, owned by BCM's user, not a symlink) before
  the first call of every pass and refuses to run adb when it cannot. By
  hand: ``sudo env ADB_SERVER_SOCKET=localfilesystem:/run/bcm-adb/adb.sock
  adb devices -l`` — a plain ``sudo adb …`` starts a SECOND server on
  :5037 that fights this one for the USB device (``sudo adb kill-server``
  ends it). ``adb forward`` listens on 127.0.0.1 only.
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

from src.core.logger import get_logger
from src.network._proc import IFACE_RE, PROBE_TIMEOUT_S, RC_MISSING, RC_TIMEOUT
from src.network._proc import _cfg_get
from src.network._proc import _number as _proc_number
from src.network._proc import _run as _run_cmd
from src.network._proc import clean_error, parse_ip_status, split_terse
from src.network.phone_tether import CON_NAME_RE, NMCLI_NOT_FOUND, TIMESYNC_ARGV
from src.network.phone_tether import _get_values

log = get_logger("network.car_phone")

TOPIC = "net.car_phone"
#: Argument-free "try again now" (web_viewer's rate-limited POST route).
RETRY_TOPIC = "net.car_phone.cmd.retry"

#: Every state the module publishes (web_viewer accepts only these).
STATES = ("disabled", "no_adb", "adb_error", "no_device", "unauthorized",
          "tethering", "connected", "failed")

HINT_AUTHORIZE = "authorize"
HINT_PIN_SERIAL = "pin_serial"
HINT_TETHER_BLOCKED = "tether_blocked"
HINT_AA_USB_PROBE = "aa_usb_probe"
HINT_INSTALL_ADB = "install_adb"
#: ``hint`` values (web_viewer passes only these on).
HINTS = ("", HINT_AUTHORIZE, HINT_PIN_SERIAL, HINT_TETHER_BLOCKED,
         HINT_AA_USB_PROBE, HINT_INSTALL_ADB)

#: adb states of a device as ``adb devices`` prints them, folded to these
#: (plus "missing"/"error" for the tool itself) — the ``adb`` field.
ADB_STATES = ("", "device", "unauthorized", "offline", "no_permissions", "other",
              "missing", "error")

#: Code defaults for ``network.car_phone``.
DEFAULTS: dict[str, Any] = {
    # '' = the only phone on USB in the "device" state. Pin it (adb serial,
    # `adb devices -l`) when a second Android device may be plugged in.
    "serial": "",
    "con_name": "bcm-car-phone",
    # Below Bluetooth PAN (750) and a future LTE modem (NM default 700):
    # the cable wins while it is up, the kernel falls back by itself.
    "route_metric": 650,
    # svc_usb = switch USB tethering on over adb; none = leave it to the
    # phone ("Default USB configuration: USB tethering" in developer options).
    "tether_method": "svc_usb",
    # rndis (every Android) or ncm (Android 11+ on some kernels).
    "usb_function": "rndis",
    "check_sec": 30,
    "retry_sec": 15,
    "max_retry_sec": 300,
    # After setFunctions the USB re-enumerates and NM needs a few seconds.
    "settle_sec": 10,
    "gps_forward": True,
    # Port of the NMEA TCP server app on the phone (gpsdRelay, plan C).
    "gps_remote_port": 50000,
    # 0 = hardware.gps.tcp.port, so `hardware.gps.tcp.host: auto` reaches it.
    "gps_local_port": 0,
    "battery_sec": 60,
    "warn_temp_c": 45,
    "critical_temp_c": 50,
    "trigger_timesync": True,
    # Plan D1: clock from the phone when the internet one did not work.
    "time_sync": True,
    "time_sync_drift_s": 30,
}

#: adb serials we accept (USB serials are alphanumeric; ``.:_-`` for the
#: rest). Starts with an alphanumeric so it can never read as an option.
SERIAL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
TETHER_METHODS = ("svc_usb", "none")
USB_FUNCTIONS = ("rndis", "ncm")
#: Kernel drivers of the phone's tethering interface (``match.driver``).
#: cdc_ether is deliberately absent — the Huawei E3372 LTE stick uses it.
TETHER_DRIVERS = ("rndis_host", "cdc_ncm")
#: Google's vendor id in Android Open Accessory mode: 2d00 accessory,
#: 2d01 accessory+adb (what autoapp's AA handshake produces), 2d02-2d05
#: the audio variants. No phone uses these ids in normal operation.
AOAP_VENDOR = "18d1"
AOAP_PRODUCTS = frozenset({"2d00", "2d01", "2d02", "2d03", "2d04", "2d05"})
USB_SYSFS_ROOT = "/sys/bus/usb/devices"
#: Upper bound of sysfs entries read per pass (a hub tree has a few dozen).
USB_SYSFS_MAX = 256
#: Root-only directory of the adb server's Unix socket (see "Security").
ADB_SOCKET_DIR = "/run/bcm-adb"
ADB_SOCKET_NAME = "adb.sock"


def adb_env(socket_dir: str = ADB_SOCKET_DIR) -> dict[str, str]:
    """``adb``'s environment (on top of ``LC_ALL=C``): root's key pair and
    the private server socket instead of TCP 127.0.0.1:5037."""
    return {"HOME": "/root",
            "ADB_SERVER_SOCKET": f"localfilesystem:{socket_dir}/{ADB_SOCKET_NAME}"}


#: The production environment of every adb call.
ADB_ENV = adb_env()

FIRST_ADB_TIMEOUT_S = 20.0
EDIT_TIMEOUT_S = 15.0
UP_WAIT_S = 30
UP_TIMEOUT_S = UP_WAIT_S + 15.0
TIMESYNC_TIMEOUT_S = 10.0
SET_TIME_TIMEOUT_S = 10.0
#: setFunctions attempts without the function appearing => tether_blocked.
MAX_TETHER_ATTEMPTS = 3
#: Heat hysteresis: the alarm clears below warn_temp_c minus this.
HEAT_CLEAR_MARGIN_C = 3.0
HEAT_REANNOUNCE_S = 60.0
HEAT_NOTIFY_TTL_S = 60.0
#: Clock check cadence while it is allowed (the drift does not change fast).
TIME_CHECK_S = 600.0
#: bcm-timesync success within this long => the phone is not asked: the
#: timer period (OnUnitActiveSec=1h) plus slack for the timer's accuracy
#: (AccuracySec, 1 min by default) and curl's run time — exactly 1 h would
#: let the phone override a healthy internet sync just before each refresh.
TIMESYNC_FRESH_S = 3600.0 + 15 * 60
TIMESYNC_MARKER = "/run/bcm-timesync.ok"
#: Sanity range of the phone's clock: 2025-01-01 .. 2100-01-01 (UTC).
MIN_EPOCH = 1735689600
MAX_EPOCH = 4102444800
#: Android's fallback for a lost clock is the ROM's build time; a reading
#: less than this long after it is that fallback, not a synced clock.
BUILD_TIME_GUARD_S = 48 * 3600
#: Plausible ``ro.build.date.utc`` (2001-09-09 .. MAX_EPOCH).
MIN_BUILD_EPOCH = 1_000_000_000
#: A step back by more than this needs two readings that agree (±TOL).
BACKWARD_CONFIRM_S = 3600.0
BACKWARD_CONFIRM_TOL_S = 5.0
#: Plausible battery temperature (°C); outside = not reported.
MIN_TEMP_C, MAX_TEMP_C = -40.0, 100.0

HEALTH_NAMES = {1: "unknown", 2: "good", 3: "overheat", 4: "dead",
                5: "over_voltage", 6: "failure", 7: "cold"}

_FUNCS_RE = re.compile(r"^[a-z_]{2,16}(?:,[a-z_]{2,16})*$")
_EPOCH_RE = re.compile(r"^\d{10}$")
_BUILD_EPOCH_RE = re.compile(r"^\d{9,10}$")
#: Connection states adb prints in ``adb devices`` (adb's
#: connection_state_name); a line with any other second word is not a
#: device line ("adb server version (41) doesn't match …").
KNOWN_ADB_STATES = frozenset({"device", "unauthorized", "offline", "bootloader", "recovery",
                              "rescue", "sideload", "host", "authorizing", "connecting",
                              "detached", "unknown", "no_permissions"})


# ── pure helpers (tested directly) ─────────────────────────────────────────

def mask_serial(serial: Any) -> str:
    """``1a2b3c4d`` → ``1a…4d`` — enough to tell two phones apart in the
    UI, not enough to address one (the payload is visible from the LAN in
    ``readonly`` mode)."""
    if not isinstance(serial, str) or not serial:
        return ""
    if len(serial) <= 4:
        return "…"
    return f"{serial[:2]}…{serial[-2:]}"


def parse_devices(text: str) -> list[dict[str, Any]]:
    """``adb devices -l`` → ``[{serial, state, usb}]``.

    Strict on purpose — the serial ends up in argv: lines that are not
    ``<serial> <state> …`` with a valid serial are dropped (the header,
    ``* daemon not running; starting now …``, ``adb server version … doesn't
    match``). ``no permissions (…)`` folds to ``no_permissions``; ``usb`` is
    True when the ``-l`` details name a USB port (network transports never
    do).
    """
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("*") or stripped.lower().startswith("list of"):
            continue
        tokens = stripped.split()
        if len(tokens) < 2 or not SERIAL_RE.fullmatch(tokens[0]):
            continue
        serial, state = tokens[0], tokens[1]
        if state == "no" and len(tokens) > 2 and tokens[2].startswith("permissions"):
            state = "no_permissions"
        if state not in KNOWN_ADB_STATES:
            continue        # not a device line (an adb message with a serial-like word)
        if serial in seen:
            continue
        seen.add(serial)
        usb = any(t.startswith("usb:") for t in tokens[2:])
        out.append({"serial": serial, "state": state, "usb": usb})
    return out


def adb_state_field(state: Optional[str]) -> str:
    """A device state from :func:`parse_devices` → one of :data:`ADB_STATES`."""
    if not state:
        return ""
    return state if state in ("device", "unauthorized", "offline", "no_permissions") else "other"


def parse_functions(*streams: str) -> Optional[set[str]]:
    """``svc usb getFunctions`` → set of functions, None if unrecognised.

    Android prints the answer (``rndis,adb``, ``mtp,adb`` …) on STDERR; both
    streams are looked at, but only a line that is nothing else than a
    comma-separated list of lowercase names counts — an error message that
    happens to contain "rndis" must not read as "rndis is on".
    """
    for stream in streams:
        for line in (stream or "").splitlines():
            line = line.strip()
            if _FUNCS_RE.fullmatch(line):
                return set(line.split(","))
    return None


def parse_active(text: str, con_name: str) -> tuple[Optional[str], str]:
    """``NAME,DEVICE,STATE`` of active connections → (device, state) of ours.

    ``(None, '')`` when our profile is not active; the device only when it
    is a plausible interface name (it goes into the next nmcli argv).
    """
    for line in (text or "").splitlines():
        fields = split_terse(line)
        if len(fields) < 3 or fields[0] != con_name:
            continue
        dev = fields[1].strip()
        state = fields[2].strip().lower()
        return (dev if IFACE_RE.fullmatch(dev) else None), state
    return None, ""


def _int_field(text: str, key: str) -> Optional[int]:
    m = re.search(rf"(?m)^[ \t]*{re.escape(key)}:[ \t]*(-?\d{{1,9}})[ \t]*$", text)
    return int(m.group(1)) if m else None


def _bool_field(text: str, key: str) -> Optional[bool]:
    m = re.search(rf"(?m)^[ \t]*{re.escape(key)}:[ \t]*(true|false)[ \t]*$", text)
    return None if m is None else m.group(1) == "true"


def parse_battery(text: str) -> dict[str, Any]:
    """``dumpsys battery`` → ``{battery_pct, temp_c, charging, full, plugged,
    health, overheat, overridden}``; a missing or implausible field is None.

    Every regex is anchored to a whole ``key: value`` line, so junk around
    (a ROM's extra lines, a truncated dump) cannot be misread.
    """
    text = text or ""
    level = _int_field(text, "level")
    scale = _int_field(text, "scale")
    if level is not None and scale not in (None, 100) and scale > 0:
        level = round(level * 100 / scale)
    pct = level if level is not None and 0 <= level <= 100 else None
    raw_temp = _int_field(text, "temperature")
    temp = None
    if raw_temp is not None:
        temp = raw_temp / 10.0
        if not MIN_TEMP_C <= temp <= MAX_TEMP_C:
            temp = None
    status = _int_field(text, "status")
    charging = None
    full = None
    if status in (2, 3, 4, 5):
        charging = status == 2
        full = status == 5
    plugged: Optional[str] = None
    sources = {"AC powered": "ac", "USB powered": "usb", "Wireless powered": "wireless",
               "Dock powered": "dock"}
    seen_any = False
    for key, name in sources.items():
        value = _bool_field(text, key)
        if value is None:
            continue
        seen_any = True
        if value and plugged is None:
            plugged = name
    if seen_any and plugged is None:
        plugged = ""
    health_code = _int_field(text, "health")
    health = HEALTH_NAMES.get(health_code) if health_code is not None else None
    return {
        "battery_pct": pct,
        "temp_c": temp,
        "charging": charging,
        "full": full,
        "plugged": plugged,
        "health": health,
        "overheat": health_code == 3,
        "overridden": "UPDATES STOPPED" in text,
    }


#: Wi-Fi hotspot interface names of Android tethering (wlan1 on most
#: Qualcomm/MediaTek phones, ap0/swlan0/softap0 on others).
_HOTSPOT_IFACE_RE = re.compile(r"^(?:wlan\d+|ap\d+|swlan\d+|softap\d+|wigig\d+)$")
_TETHER_STATE_RE = re.compile(
    r"^\s*([A-Za-z0-9_.-]{1,15})\s+-\s+([A-Za-z]+State)\s+-\s+lastError\s*=\s*-?\d+\s*$")
_CLIENTS_RE = re.compile(
    r"(?im)^\s*(?:mNumAssociatedStations|connected\s+clients|number\s+of\s+clients)"
    r"\s*[:=]\s*(\d{1,3})\s*$")


def parse_hotspot(text: str) -> tuple[Optional[bool], Optional[int]]:
    """``dumpsys tethering`` → (hotspot active, client count).

    The "Tether state:" lines (``wlan1 - TetheredState - lastError = 0``) are
    the stable part of the dump across Android 9-14: a Wi-Fi interface in
    ``TetheredState`` = the hotspot is up. ``(None, None)`` when no such
    line exists at all (unknown format, service missing) — the UI then
    shows nothing rather than "off". The client count is read only from an
    explicit count line, which not every release prints (else None).
    Unverified on the Redmi's ROM.
    """
    text = text or ""
    seen = False
    active = False
    for line in text.splitlines():
        m = _TETHER_STATE_RE.match(line)
        if not m:
            continue
        seen = True
        if _HOTSPOT_IFACE_RE.match(m.group(1)) and m.group(2) == "TetheredState":
            active = True
    if not seen:
        return None, None
    clients = None
    m = _CLIENTS_RE.search(text)
    if m:
        clients = int(m.group(1))
    return active, (clients if active else None)


def parse_epoch(text: str) -> Optional[int]:
    """``date +%s`` output → epoch seconds in the sane range, else None."""
    value = (text or "").strip()
    if not _EPOCH_RE.fullmatch(value):
        return None
    epoch = int(value)
    return epoch if MIN_EPOCH <= epoch <= MAX_EPOCH else None


def parse_build_epoch(text: str) -> Optional[int]:
    """``getprop ro.build.date.utc`` → the ROM's build time (epoch s), else
    None (empty: property missing; anything but digits: not trusted)."""
    value = (text or "").strip()
    if not _BUILD_EPOCH_RE.fullmatch(value):
        return None
    epoch = int(value)
    return epoch if MIN_BUILD_EPOCH <= epoch <= MAX_EPOCH else None


def prepare_private_dir(path: str) -> str:
    """Make ``path`` a directory only its owner can enter. ``''`` when it
    is one, else the reason it is not (then adb must not run).

    Created 0700 when missing; an existing one must be a real directory
    (not a symlink) owned by this process's user — its mode is then
    tightened to 0700. /run is writable by root only, so nobody else can
    have planted it; the checks are for a mistake, not a race."""
    try:
        os.makedirs(path, mode=0o700, exist_ok=True)
        st = os.lstat(path)
        if not stat.S_ISDIR(st.st_mode):
            return f"{path} is not a directory"
        if st.st_uid != os.geteuid():
            return f"{path} belongs to uid {st.st_uid}, not to BCM (uid {os.geteuid()})"
        if stat.S_IMODE(st.st_mode) != 0o700:
            os.chmod(path, 0o700)
    except OSError as e:
        return clean_error(f"cannot prepare {path}: {e}")
    return ""


def parse_forwards(text: str) -> set[str]:
    """``adb forward --list`` → the set of its lines (normalised spaces)."""
    return {" ".join(line.split()) for line in (text or "").splitlines() if line.strip()}


def aoap_present(root: str = USB_SYSFS_ROOT) -> bool:
    """True if a USB device is in Android Open Accessory mode (18d1:2d0x).

    Reads only the two small id files per device, at most
    :data:`USB_SYSFS_MAX` entries; any read error counts as "not AOAP"."""
    try:
        entries = sorted(os.listdir(root))[:USB_SYSFS_MAX]
    except OSError:
        return False
    for name in entries:
        base = os.path.join(root, name)
        try:
            vendor = Path(base, "idVendor").read_text(encoding="ascii", errors="replace")[:16]
            product = Path(base, "idProduct").read_text(encoding="ascii", errors="replace")[:16]
        except OSError:
            continue
        if vendor.strip().lower() == AOAP_VENDOR and product.strip().lower() in AOAP_PRODUCTS:
            return True
    return False


def read_timesync_marker(path: str = TIMESYNC_MARKER) -> Optional[float]:
    """CLOCK_BOOTTIME seconds of bcm-timesync's last success, or None."""
    try:
        text = Path(path).read_text(encoding="ascii", errors="replace")[:64]
    except OSError:
        return None
    first = text.split()[0] if text.split() else ""
    if not re.fullmatch(r"\d{1,10}", first):
        return None
    return float(first)


def _boottime() -> float:
    """CLOCK_BOOTTIME (counts S3), fallback monotonic — matches /proc/uptime."""
    try:
        return time.clock_gettime(time.CLOCK_BOOTTIME)
    except (AttributeError, OSError):
        return time.monotonic()


def _number(value: Any, default: float, lo: float, hi: float, name: str) -> float:
    """:func:`src.network._proc._number` for ``network.car_phone.*``."""
    return _proc_number("network.car_phone", value, default, lo, hi, name, logger=log)


def _port(value: Any, default: int, name: str, allow_zero: bool = False) -> int:
    """A TCP port (int 1..65535, 0 too with ``allow_zero``), else the default.
    Integers only: the value becomes a word on adb's command line."""
    lo = 0 if allow_zero else 1
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= 65535:
        if value is not None and value != default:
            log.warning("network.car_phone.%s=%r is not a port number — using %s",
                        name, value, default)
        return default
    return value


# ── the manager ────────────────────────────────────────────────────────────

class CarPhone:
    """Keeps the car phone's USB uplink, GPS forward and health in view.

    Args:
        config: BCMConfig (dotted ``get``) or a plain nested dict.
        event_bus: EventBus (``subscribe``/``publish``/``get_last``).
        runner: ``subprocess.run`` compatible — the test seam; every call is
            an argv list.
        clock: monotonic seconds (backoff, settle, battery cadence).
        wall_clock: epoch seconds (``since``, the clock comparison).
        boot_clock: CLOCK_BOOTTIME seconds (bcm-timesync marker age).
        usb_root: sysfs directory scanned for AOAP devices.
        marker_path: bcm-timesync's success marker.
        notify: ``publish_notification`` compatible (tests).
        adb_socket_dir: root-only directory of the adb server's socket
            (tests: a temporary directory).
    """

    def __init__(self, config: Any, event_bus: Any,
                 runner: Callable[..., Any] = subprocess.run,
                 clock: Callable[[], float] = time.monotonic,
                 wall_clock: Callable[[], float] = time.time,
                 boot_clock: Callable[[], float] = _boottime,
                 usb_root: str = USB_SYSFS_ROOT,
                 marker_path: str = TIMESYNC_MARKER,
                 notify: Optional[Callable[..., Any]] = None,
                 adb_socket_dir: str = ADB_SOCKET_DIR) -> None:
        self._config = config
        self._bus = event_bus
        self._runner = runner
        self._clock = clock
        self._wall = wall_clock
        self._boot = boot_clock
        self._usb_root = usb_root
        self._marker = marker_path
        self._adb_dir = adb_socket_dir
        self._adb_env = adb_env(adb_socket_dir)
        if notify is None:
            from src.core.notifications import publish_notification as notify
        self._notify = notify

        section = _cfg_get(config, "network.car_phone", {})
        if not isinstance(section, dict):
            section = {}

        def opt(key: str) -> Any:
            return section.get(key, DEFAULTS[key])

        # Kept raw: an invalid pinned serial must stay invalid (state
        # failed), not silently fall back to "the only phone on USB".
        # Not a string (YAML turns an unquoted 0123456789 into a number and
        # may drop the leading zero) = invalid, never "the number as text".
        serial = opt("serial")
        if isinstance(serial, str):
            self._serial_raw = serial.strip()
            self._serial_ok = (not self._serial_raw) or bool(SERIAL_RE.fullmatch(self._serial_raw))
        elif serial is None:
            self._serial_raw, self._serial_ok = "", True
        else:
            self._serial_raw, self._serial_ok = repr(serial)[:64], False
        con = opt("con_name")
        if isinstance(con, str) and CON_NAME_RE.fullmatch(con):
            self._con_name = con
        else:
            log.warning("network.car_phone.con_name=%r is not a safe profile name "
                        "(letters, digits, _ . -) — using %r", con, DEFAULTS["con_name"])
            self._con_name = DEFAULTS["con_name"]
        self._metric = int(_number(opt("route_metric"), DEFAULTS["route_metric"],
                                   0, 2**31 - 1, "route_metric"))
        method = opt("tether_method")
        if method not in TETHER_METHODS:
            log.warning("network.car_phone.tether_method=%r unknown — using %s (%s)",
                        method, DEFAULTS["tether_method"], "/".join(TETHER_METHODS))
            method = DEFAULTS["tether_method"]
        self._tether_method = method
        func = opt("usb_function")
        if func not in USB_FUNCTIONS:
            log.warning("network.car_phone.usb_function=%r unknown — using %s (%s)",
                        func, DEFAULTS["usb_function"], "/".join(USB_FUNCTIONS))
            func = DEFAULTS["usb_function"]
        self._usb_function = func
        self._check_sec = float(_number(opt("check_sec"), DEFAULTS["check_sec"],
                                        5, 3600, "check_sec"))
        self._retry_sec = float(_number(opt("retry_sec"), DEFAULTS["retry_sec"],
                                        5, 3600, "retry_sec"))
        self._max_retry_sec = float(_number(opt("max_retry_sec"), DEFAULTS["max_retry_sec"],
                                            self._retry_sec, 86400, "max_retry_sec"))
        self._settle_sec = float(_number(opt("settle_sec"), DEFAULTS["settle_sec"],
                                         0, 300, "settle_sec"))
        fwd = opt("gps_forward")
        self._gps_forward = fwd if isinstance(fwd, bool) else True
        self._gps_remote = _port(opt("gps_remote_port"), DEFAULTS["gps_remote_port"],
                                 "gps_remote_port")
        local = _port(opt("gps_local_port"), DEFAULTS["gps_local_port"], "gps_local_port",
                      allow_zero=True)
        if local == 0:
            tcp_port = _cfg_get(config, "hardware.gps.tcp.port", 50000)
            local = tcp_port if isinstance(tcp_port, int) and not isinstance(tcp_port, bool) \
                and 1 <= tcp_port <= 65535 else 50000
        self._gps_local = local
        self._battery_sec = float(_number(opt("battery_sec"), DEFAULTS["battery_sec"],
                                          15, 3600, "battery_sec"))
        self._warn_c = float(_number(opt("warn_temp_c"), DEFAULTS["warn_temp_c"],
                                     20, 80, "warn_temp_c"))
        self._crit_c = float(_number(opt("critical_temp_c"), DEFAULTS["critical_temp_c"],
                                     self._warn_c, 90, "critical_temp_c"))
        timesync = opt("trigger_timesync")
        self._trigger_timesync = timesync if isinstance(timesync, bool) else True
        tsync = opt("time_sync")
        self._time_sync = tsync if isinstance(tsync, bool) else True
        self._drift_s = float(_number(opt("time_sync_drift_s"), DEFAULTS["time_sync_drift_s"],
                                      5, 86400, "time_sync_drift_s"))
        # Plan D2 has its own module toggle (requires car_phone — which runs,
        # or this object would not exist). Strictly True: a typo stays off.
        self._hotspot = _cfg_get(config, "modules.car_phone_hotspot", False) is True

        # tick() runs one pass at a time; stop() never takes this lock (a
        # pass can sit in `connection up --wait 30`).
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._ev_lock = threading.Lock()
        self._retry_req = 0
        self._seen_retry = 0

        # adb. Its own backoff: a hung adb server must not gate the
        # tethering backoff below (and vice versa).
        self._adb_calls = 0
        self._adb_failed = False
        self._adb_err = ""
        self._adb_delay = self._retry_sec
        self._adb_retry_at = 0.0
        # The phone being worked with (full serial — never published).
        self._serial: Optional[str] = None
        # Tethering (monotonic times). The attempt counter belongs to a
        # serial and survives the phone dropping off USB for a moment —
        # setFunctions re-enumerates the USB device, and a reset there
        # would turn "3 attempts, then tether_blocked" into an endless loop.
        self._attempts_serial: Optional[str] = None
        self._tether_attempts = 0
        self._tether_at: Optional[float] = None
        self._func_seen_at: Optional[float] = None
        # Backoff (monotonic). _retry_kind: None | "backoff".
        self._delay = self._retry_sec
        self._retry_at = 0.0
        self._retry_kind: Optional[str] = None
        self._last_error = ""
        self._last_hint = ""
        # Device data kept between passes (published with every state).
        self._device: dict[str, Any] = self._empty_device()
        self._battery_due = 0.0
        self._time_due = 0.0
        self._fwd_error = ""
        self._time_warned = False
        self._time_synced_at: Optional[float] = None
        # Clock validation (plan D1): the phone's ROM build time (read once
        # per appearance) and a not yet confirmed backwards drift.
        self._build_epoch: Optional[int] = None
        self._back_pending: Optional[float] = None
        self._build_logged = False
        self._hotspot_cmd: Optional[list[str]] = None
        # Heat alarm: None | "warning" | "danger"; last announcement (monotonic).
        self._heat: Optional[str] = None
        self._heat_announced_at: Optional[float] = None

        # Published state.
        self._payload: Optional[dict[str, Any]] = None
        self._state_name = "disabled"
        self._since = 0.0
        self._warned: set[str] = set()

    @staticmethod
    def _empty_device() -> dict[str, Any]:
        return {"gps_forward": False, "battery_pct": None, "temp_c": None,
                "charging": None, "full": None, "plugged": None, "health": None,
                "overridden": False, "hotspot_active": None, "hotspot_clients": None}

    # ── read-only views (UI / tests) ──────────────────────────────────────

    @property
    def state(self) -> Optional[dict[str, Any]]:
        """Last published payload (copy) or None."""
        if self._payload is None:
            return None
        return dict(self._payload, since=self._since)

    @property
    def retry_delay(self) -> float:
        return self._delay

    @property
    def retry_at(self) -> float:
        return self._retry_at

    @property
    def con_name(self) -> str:
        return self._con_name

    @property
    def gps_local_port(self) -> int:
        return self._gps_local

    def _subscriptions(self) -> tuple:
        return ((RETRY_TOPIC, self._on_retry_cmd),
                ("power.shutting_down", self._on_shutdown))

    # ── lifecycle ─────────────────────────────────────────────────────────

    def start(self) -> None:
        """Subscribe and start the worker thread (no I/O here: a slow adb
        server start must not delay the other modules)."""
        if self._thread is not None:
            return
        for topic, cb in self._subscriptions():
            self._bus.subscribe(topic, cb)
        self._thread = threading.Thread(target=self._run, daemon=True, name="car-phone")
        self._thread.start()
        if self._serial_raw:
            serial_desc = mask_serial(self._serial_raw) if self._serial_ok \
                else "<invalid network.car_phone.serial>"
        else:
            serial_desc = "<the only phone on USB>"
        log.info("Car phone started (serial=%s, profile=%s, metric=%d, tether=%s/%s, "
                 "gps forward=%s tcp:%d->tcp:%d, check=%ds, battery=%ds, heat=%d/%d C, "
                 "time sync=%s, hotspot status=%s)", serial_desc, self._con_name,
                 self._metric, self._tether_method, self._usb_function, self._gps_forward,
                 self._gps_local, self._gps_remote, self._check_sec, self._battery_sec,
                 self._warn_c, self._crit_c, self._time_sync, self._hotspot)

    def stop(self) -> None:
        """Stop the worker. Never waits for a pass in progress; the link and
        the forward are left as they are (NetworkManager keeps the link)."""
        if self._stop.is_set():
            return
        self._stop.set()
        self._wake.set()
        for topic, cb in self._subscriptions():
            try:
                self._bus.unsubscribe(topic, cb)
            except Exception:
                pass
        self._publish("disabled")
        log.info("Car phone stopped")

    def _on_shutdown(self, topic: str, value: Any, timestamp: float) -> None:
        if value:
            self.stop()

    def _on_retry_cmd(self, topic: str, value: Any, timestamp: float) -> None:
        """"Ponów" from Settings. The value is ignored (nothing from the
        browser reaches adb or nmcli); runs on the bus dispatcher — only a
        counter and a wake-up, no I/O."""
        with self._ev_lock:
            self._retry_req += 1
        self._wake.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            # Clear BEFORE the pass: a retry during tick() is not lost.
            self._wake.clear()
            try:
                self.tick()
            except Exception:
                log.exception("Car phone pass failed")
            self._wake.wait(self.next_wait())

    def next_wait(self) -> float:
        """Seconds until the next pass: ``check_sec``, or sooner for a
        settle / backoff / battery deadline inside that window."""
        now = self._clock()
        wait = self._check_sec
        deadlines = []
        if self._retry_kind is not None:
            deadlines.append(self._retry_at)
        if self._adb_retry_at:
            deadlines.append(self._adb_retry_at)
        if self._tether_at is not None:
            deadlines.append(self._tether_at + self._settle_sec)
        if self._func_seen_at is not None:
            deadlines.append(self._func_seen_at + self._settle_sec)
        if self._serial is not None:
            deadlines.append(self._battery_due)
        for at in deadlines:
            remaining = at - now
            if 0 < remaining < wait:
                wait = remaining
        return max(1.0, wait)

    # ── one pass ──────────────────────────────────────────────────────────

    def tick(self) -> str:
        """One reconciliation step. Returns the resulting state name."""
        with self._lock:
            if self._stop.is_set():
                return self._state_name
            now = self._clock()
            with self._ev_lock:
                retry_req = self._retry_req
            if retry_req != self._seen_retry:
                self._seen_retry = retry_req
                log.info("Car phone: retry requested — backoff and attempts dropped")
                self._reset_backoff()
                self._adb_delay = self._retry_sec
                self._adb_retry_at = 0.0
                self._tether_attempts = 0
                self._tether_at = None

            # 1. adb (skipped while an adb error backs off; NM is still read).
            adb_status, devices = "skipped", []
            if not now < self._adb_retry_at:
                adb_status, devices = self._adb_devices(now)
            # 2. AOAP (cheap sysfs read).
            aoap = aoap_present(self._usb_root)
            # 3. NetworkManager.
            link, link_state, nm_err = self._nm_link()

            serial, dev_state, why, hint = self._pick(adb_status, devices)
            if serial != self._serial:
                self._new_phone(serial, now)
            if serial is not None and dev_state == "device":
                self._device_work(serial, now)
            elif serial is None:
                self._device = self._empty_device()
                self._clear_heat()
            adb_field = {"missing": "missing", "error": "error"}.get(
                adb_status, adb_state_field(dev_state))

            if link is not None:
                self._connected(link, adb_field)
                return self._state_name
            if adb_status == "missing":
                self._publish("no_adb", adb=adb_field, hint=HINT_INSTALL_ADB,
                              error="adb is not installed (apt install adb)")
                return self._state_name
            if adb_status in ("error", "skipped"):
                self._publish("adb_error", adb="error", error=self._adb_err)
                return self._state_name
            if aoap:
                self._publish("failed", adb=adb_field, hint=HINT_AA_USB_PROBE,
                              error="a USB device is in Android Auto accessory mode (AOAP) — "
                                    "autoapp probes USB; rebuild it with BCM_AA_USB=0")
                return self._state_name
            if serial is None or dev_state != "device":
                state = {"unauthorized": "unauthorized",
                         "pin_serial": "failed", "bad_serial": "failed"}.get(why, "no_device")
                self._publish(state, adb=adb_field, hint=hint, error=self._why_text(why, dev_state))
                return self._state_name
            if link_state == "activating":
                self._publish("tethering", adb=adb_field, error="NetworkManager is bringing "
                              "the USB link up")
                return self._state_name
            self._tether(now, serial, adb_field, nm_err)
            return self._state_name

    # ── step 1: adb devices / picking the phone ───────────────────────────

    def _adb(self, argv: list[str], timeout: float = PROBE_TIMEOUT_S, *,
             raw_stderr: bool = False) -> tuple[int, str, str]:
        """Every adb call: root's key, the private server socket, a timeout."""
        return _run_cmd(self._runner, argv, timeout, env_extra=self._adb_env,
                        on_missing=self._warn_missing, raw_stderr=raw_stderr)

    def _adb_devices(self, now: float) -> tuple[str, list[dict[str, Any]]]:
        """``("ok"|"missing"|"error", devices)``. The first call (and the
        first after an error) may start the adb server — longer timeout. An
        error (timeout, crash) backs off ``retry_sec`` doubling up to
        ``max_retry_sec``: every hung call costs up to 20 s of this thread.
        A missing binary is re-checked every pass — that is one cheap
        failed exec, and ``apt install adb`` should show up without a
        restart. The private socket directory is checked first: without it
        the adb server would be reachable by other local users, so adb is
        not run at all (state ``adb_error``)."""
        dir_err = prepare_private_dir(self._adb_dir)
        if dir_err:
            return self._adb_error(now, f"adb not started: {dir_err}"), []
        timeout = FIRST_ADB_TIMEOUT_S if (self._adb_calls == 0 or self._adb_failed) \
            else PROBE_TIMEOUT_S
        self._adb_calls += 1
        rc, out, err = self._adb(["adb", "devices", "-l"], timeout)
        if rc == RC_MISSING:
            self._adb_failed = True
            self._adb_err = ""
            return "missing", []
        if rc != 0:
            text = err or out.strip() or f"adb devices: exit {rc}"
            if rc == RC_TIMEOUT:
                text = err or "adb devices timed out"
            return self._adb_error(now, text), []
        self._adb_failed = False
        self._adb_err = ""
        self._adb_delay = self._retry_sec
        self._adb_retry_at = 0.0
        return "ok", parse_devices(out)

    def _adb_error(self, now: float, text: str) -> str:
        """adb (or its socket directory) failed: back off ``retry_sec``
        doubling up to ``max_retry_sec``. Returns the status ``"error"``."""
        self._adb_failed = True
        self._adb_err = clean_error(text)
        delay = min(self._adb_delay, self._max_retry_sec)
        self._adb_retry_at = now + delay
        self._adb_delay = min(delay * 2, self._max_retry_sec)
        if self._state_name != "adb_error":
            log.warning("Car phone: adb error (%s) — next attempt in %ds",
                        self._adb_err, delay)
        return "error"

    def _pick(self, adb_status: str, devices: list[dict[str, Any]]) \
            -> tuple[Optional[str], Optional[str], str, str]:
        """``(serial, adb state, why, hint)`` of the phone to work with.

        ``serial`` is None when there is none; ``why`` names the reason
        (:meth:`_why_text`). Pinned serial: that device whatever its
        transport. Not pinned: USB transports only, and only when exactly
        one is in the ``device`` state."""
        if not self._serial_ok:
            return None, None, "bad_serial", ""
        if adb_status != "ok":
            return None, None, adb_status, ""
        if self._serial_raw:
            for d in devices:
                if d["serial"] == self._serial_raw:
                    if d["state"] == "device":
                        return d["serial"], "device", "", ""
                    if d["state"] == "unauthorized":
                        return None, "unauthorized", "unauthorized", HINT_AUTHORIZE
                    return None, d["state"], "state", ""
            return None, None, "pinned_absent", ""
        usb = [d for d in devices if d["usb"]]
        ready = [d for d in usb if d["state"] == "device"]
        if len(ready) == 1:
            return ready[0]["serial"], "device", "", ""
        if len(ready) > 1:
            return None, None, "pin_serial", HINT_PIN_SERIAL
        if any(d["state"] == "unauthorized" for d in usb):
            return None, "unauthorized", "unauthorized", HINT_AUTHORIZE
        if usb:
            return None, usb[0]["state"], "state", ""
        if devices:
            return None, None, "network_only", ""
        return None, None, "none", ""

    def _why_text(self, why: str, dev_state: Optional[str]) -> str:
        return {
            "bad_serial": "invalid network.car_phone.serial (letters, digits, . _ : -; "
                          "quote it in YAML)",
            "unauthorized": "allow USB debugging on the phone (\"Always allow from this "
                            "computer\")",
            "pin_serial": "more than one Android phone on USB — set network.car_phone.serial",
            "pinned_absent": f"phone {mask_serial(self._serial_raw)} is not connected",
            "network_only": "adb lists only network devices — ignored (USB only)",
            "state": f"phone reported by adb as {dev_state or 'unknown'}",
        }.get(why, "no phone on USB (adb devices)")

    def _new_phone(self, serial: Optional[str], now: float) -> None:
        """The phone appeared, changed or went: forget its data; a phone
        (re)appearing gets its battery and clock read at once. Tethering
        attempts and backoff start over only for a DIFFERENT phone — the
        same one dropping off USB for a moment (setFunctions re-enumerates
        it) keeps them."""
        self._serial = serial
        self._device = self._empty_device()
        self._fwd_error = ""
        self._clear_heat()
        # A phone that went and came back may have rebooted (and lost its
        # clock): its build time is read again, a pending backwards drift
        # needs a new confirmation.
        self._build_epoch = None
        self._back_pending = None
        self._build_logged = False
        if serial is None:
            return
        self._battery_due = now
        self._time_due = now
        if serial != self._attempts_serial:
            log.info("Car phone: working with %s", mask_serial(serial))
            self._attempts_serial = serial
            self._tether_attempts = 0
            self._tether_at = None
            self._func_seen_at = None
            self._reset_backoff()

    # ── step 3: NetworkManager ────────────────────────────────────────────

    def _nm(self, argv: list[str], timeout: float = PROBE_TIMEOUT_S) -> tuple[int, str, str]:
        return _run_cmd(self._runner, argv, timeout, on_missing=self._warn_missing)

    def _nm_link(self) -> tuple[Optional[dict[str, Any]], str, str]:
        """``(ip status | None, our connection's NM state, error)``."""
        rc, out, err = self._nm(["nmcli", "-t", "-f", "NAME,DEVICE,STATE",
                                 "connection", "show", "--active"])
        if rc != 0:
            if rc == RC_MISSING:
                return None, "", "nmcli is not installed — USB tethering needs NetworkManager"
            return None, "", err or f"nmcli connection show: exit {rc}"
        dev, state = parse_active(out, self._con_name)
        if dev is None or state != "activated":
            return None, state, ""
        rc, out, _err = self._nm(["nmcli", "-g", "GENERAL.IP-IFACE,IP4.ADDRESS,IP4.GATEWAY",
                                  "device", "show", dev])
        status = parse_ip_status(out) if rc == 0 else {}
        if not status.get("iface"):
            status["iface"] = dev
        return status, state, ""

    def _connected(self, link: dict[str, Any], adb_field: str) -> None:
        was = self._state_name
        self._reset_backoff()
        self._tether_attempts = 0
        self._tether_at = None
        self._func_seen_at = None
        self._publish("connected", adb=adb_field, iface=link.get("iface", ""),
                      ip=link.get("ip", ""), prefix=link.get("prefix"),
                      gateway=link.get("gateway", ""))
        if was != "connected" and self._trigger_timesync:
            self._timesync()

    def _timesync(self) -> None:
        """Start bcm-timesync.service without waiting; errors are ignored
        (the unit may not be installed — the timer retries anyway)."""
        try:
            self._runner(list(TIMESYNC_ARGV), capture_output=True, text=True,
                         errors="replace", timeout=TIMESYNC_TIMEOUT_S)
        except Exception as e:
            log.debug("bcm-timesync start failed (ignored): %s", e)

    # ── step 4: tethering ─────────────────────────────────────────────────

    def _tether(self, now: float, serial: str, adb_field: str, nm_err: str) -> None:
        if self._retry_kind == "backoff" and now < self._retry_at:
            self._publish("failed", adb=adb_field, error=self._last_error, hint=self._last_hint)
            return
        if self._retry_kind == "backoff":
            # Backoff over: a fresh round of attempts.
            self._retry_kind = None
            self._tether_attempts = 0
        if nm_err:
            self._fail(now, "failed", nm_err, adb_field)
            return
        if not self._ensure_profile(now, adb_field):
            return
        if self._tether_method == "none":
            self._publish("tethering", adb=adb_field,
                          error="waiting for USB tethering on the phone (tether_method: none)")
            return
        if self._tether_at is not None and now < self._tether_at + self._settle_sec:
            self._publish("tethering", adb=adb_field)
            return
        # Raw stderr: the answer is a line of its own there, possibly after
        # a ROM's linker warnings — cleaned (joined, cut to 200 characters)
        # it would be unreadable, and "missing" means a needless
        # setFunctions and finally a false tether_blocked.
        rc, out, err = self._adb(["adb", "-s", serial, "shell", "svc", "usb", "getFunctions"],
                                 raw_stderr=True)
        functions = parse_functions(out, err) if rc == 0 else None
        if functions is not None and self._usb_function in functions:
            self._tether_attempts = 0
            self._tether_at = None
            if self._func_seen_at is None:
                self._func_seen_at = now
            if now < self._func_seen_at + self._settle_sec:
                self._publish("tethering", adb=adb_field)     # NM autoconnects by itself
                return
            self._publish("tethering", adb=adb_field)
            rc, out, err = self._nm(["nmcli", "--wait", str(UP_WAIT_S), "connection", "up",
                                     "id", self._con_name], timeout=UP_TIMEOUT_S)
            if self._stop.is_set():
                return
            if rc == 0:
                link, _state, _err = self._nm_link()
                if link is not None:
                    self._connected(link, adb_field)
                    return
            self._fail(now, "failed", err or out.strip() or f"connection up: exit {rc}",
                       adb_field)
            return
        self._func_seen_at = None
        if self._tether_attempts >= MAX_TETHER_ATTEMPTS:
            self._fail(now, "failed", f"USB tethering did not start after "
                       f"{MAX_TETHER_ATTEMPTS} attempts (svc usb setFunctions "
                       f"{self._usb_function})", adb_field, hint=HINT_TETHER_BLOCKED)
            return
        self._tether_attempts += 1
        self._tether_at = now
        # setFunctions exits 0 even when the phone refuses — the next
        # getFunctions (after settle_sec) is the only judge.
        self._adb(["adb", "-s", serial, "shell", "svc", "usb", "setFunctions",
                   self._usb_function])
        log.info("Car phone: USB tethering requested (%s, attempt %d/%d)",
                 self._usb_function, self._tether_attempts, MAX_TETHER_ATTEMPTS)
        self._publish("tethering", adb=adb_field)

    #: Profile properties read back (and corrected) by _ensure_profile, in order.
    PROFILE_FIELDS = ("connection.type,match.driver,ipv4.method,ipv4.route-metric,"
                      "ipv6.method,connection.autoconnect")

    def _ensure_profile(self, now: float, adb_field: str) -> bool:
        """Create or correct our NM profile. False (state published) on error.

        ``match.driver`` is a list property. nmcli splits it on whitespace
        (and, depending on the version, also on commas); a SPACE-separated
        value is accepted by every version, and the read-back is compared
        as a set split on both — so either output style matches.
        Assumptions (nmcli >= 1.20, from the nmcli / nm-settings
        documentation, not verified on the car): ``ifname *`` = no
        interface binding, ``-g`` prints one value per line, exit 10 =
        profile does not exist.
        """
        con = self._con_name
        drivers = " ".join(TETHER_DRIVERS)
        rc, out, err = self._nm(["nmcli", "-g", self.PROFILE_FIELDS,
                                 "connection", "show", "id", con])
        if rc == NMCLI_NOT_FOUND:
            rc, out, err = self._nm(
                ["nmcli", "connection", "add", "type", "ethernet", "con-name", con,
                 "ifname", "*", "match.driver", drivers,
                 "ipv4.method", "auto", "ipv4.route-metric", str(self._metric),
                 "ipv6.method", "disabled", "connection.autoconnect", "yes"],
                timeout=EDIT_TIMEOUT_S)
            if rc != 0:
                self._fail(now, "failed", f"creating profile {con} failed: "
                           f"{err or out.strip() or f'exit {rc}'}", adb_field)
                return False
            log.info("Car phone: created NetworkManager profile %s (%s, metric %d)",
                     con, drivers, self._metric)
            return True
        if rc != 0:
            self._fail(now, "failed", f"reading profile {con} failed: "
                       f"{err or out.strip() or f'exit {rc}'}", adb_field)
            return False
        ctype, match, v4, metric, v6, auto = _get_values(out, 6)
        if ctype and ctype.lower() not in ("802-3-ethernet", "ethernet"):
            # Somebody else's profile under our name: never touch it.
            self._fail(now, "failed", f"profile {con} exists with type {ctype} — set another "
                       "network.car_phone.con_name", adb_field)
            return False
        changes: list[str] = []
        if set(re.split(r"[,\s]+", match.strip())) - {""} != set(TETHER_DRIVERS):
            changes += ["match.driver", drivers]
        if v4.lower() != "auto":
            changes += ["ipv4.method", "auto"]
        # Compare only a value we could read — an unparsable one must not
        # turn every attempt into a modify.
        if re.fullmatch(r"-?\d+", metric) and int(metric) != self._metric:
            changes += ["ipv4.route-metric", str(self._metric)]
        if v6 and v6.lower() != "disabled":
            changes += ["ipv6.method", "disabled"]
        if auto.lower() in ("yes", "no") and auto.lower() != "yes":
            changes += ["connection.autoconnect", "yes"]
        if changes:
            rc, out, err = self._nm(["nmcli", "connection", "modify", "id", con] + changes,
                                    timeout=EDIT_TIMEOUT_S)
            if rc != 0:
                self._fail(now, "failed", f"updating profile {con} failed: "
                           f"{err or out.strip() or f'exit {rc}'}", adb_field)
                return False
            log.info("Car phone: profile %s updated (%s)", con, ", ".join(changes[0::2]))
        return True

    # ── steps 5-8: work with a ready phone ────────────────────────────────

    def _device_work(self, serial: str, now: float) -> None:
        """GPS forward (every pass), battery + hotspot (every battery_sec),
        clock (TIME_CHECK_S). Each step is independent: one failing (or the
        phone vanishing in between) never stops the others' next pass."""
        self._ensure_forward(serial)
        if now >= self._battery_due:
            self._battery_due = now + self._battery_sec
            self._read_battery(serial, now)
            if self._hotspot:
                self._read_hotspot(serial)
        if self._time_sync and now >= self._time_due:
            self._time_due = now + TIME_CHECK_S
            self._check_clock(serial)

    def _ensure_forward(self, serial: str) -> None:
        if not self._gps_forward:
            self._device["gps_forward"] = False
            return
        want = f"{serial} tcp:{self._gps_local} tcp:{self._gps_remote}"
        rc, out, err = self._adb(["adb", "-s", serial, "forward", "--list"])
        if rc == 0 and want in parse_forwards(out):
            self._device["gps_forward"] = True
            self._fwd_error = ""
            return
        rc, out, err = self._adb(["adb", "-s", serial, "forward",
                                  f"tcp:{self._gps_local}", f"tcp:{self._gps_remote}"])
        if rc == 0:
            if not self._device["gps_forward"]:
                log.info("Car phone: GPS forward 127.0.0.1:%d -> phone:%d", self._gps_local,
                         self._gps_remote)
            self._device["gps_forward"] = True
            self._fwd_error = ""
            return
        text = clean_error(err or out.strip() or f"adb forward: exit {rc}")
        if "cannot bind" in text.lower():
            text = clean_error(f"GPS forward: local port {self._gps_local} is in use "
                               f"by another program ({text})")
        if text != self._fwd_error:
            log.warning("Car phone: %s", text)
        self._fwd_error = text
        self._device["gps_forward"] = False

    def _read_battery(self, serial: str, now: float) -> None:
        rc, out, _err = self._adb(["adb", "-s", serial, "shell", "dumpsys", "battery"])
        if rc != 0:
            return      # keep the last values; the next read may work
        data = parse_battery(out)
        for key in ("battery_pct", "temp_c", "charging", "full", "plugged", "health",
                    "overridden"):
            self._device[key] = data[key]
        self._heat_check(data.get("temp_c"), bool(data.get("overheat")), now)

    def _read_hotspot(self, serial: str) -> None:
        """Hotspot status (D2). ``dumpsys tethering`` exists from Android 11;
        older releases have the same section in ``dumpsys connectivity
        tethering``. Whichever answered is remembered."""
        cmds = [self._hotspot_cmd] if self._hotspot_cmd else [
            ["dumpsys", "tethering"], ["dumpsys", "connectivity", "tethering"]]
        for cmd in cmds:
            rc, out, _err = self._adb(["adb", "-s", serial, "shell"] + cmd)
            if rc != 0:
                continue
            active, clients = parse_hotspot(out)
            if active is None:
                continue
            self._hotspot_cmd = cmd
            self._device["hotspot_active"] = active
            self._device["hotspot_clients"] = clients
            return
        self._device["hotspot_active"] = None
        self._device["hotspot_clients"] = None

    def _check_clock(self, serial: str) -> None:
        """Plan D1: the phone's clock when the internet one did not work.

        Every reading is validated before it may touch the system clock
        (module docstring, step 7): sane range, not Android's build-time
        fallback, a large step back confirmed by a second reading."""
        marker = read_timesync_marker(self._marker)
        if marker is not None:
            age = self._boot() - marker
            if 0 <= age < TIMESYNC_FRESH_S:
                self._back_pending = None
                return      # bcm-timesync worked in its last period: it wins
        rc, out, _err = self._adb(["adb", "-s", serial, "shell", "date", "+%s"])
        if rc != 0:
            return
        epoch = parse_epoch(out)
        if epoch is None:
            self._warn_once("time:insane", f"Car phone: the phone's clock reads "
                            f"{clean_error(out)[:40]!r} — not used")
            return
        local = self._wall()
        drift = epoch - local
        if abs(drift) < self._drift_s:
            self._back_pending = None
            return
        build = self._read_build_epoch(serial)
        if build is None:
            self._warn_once("time:build", "Car phone: the phone's ROM build time "
                            "(getprop ro.build.date.utc) is unreadable — its clock is not "
                            "used (it could be Android's fallback after losing the time)")
            return
        if epoch < build + BUILD_TIME_GUARD_S:
            # Android's fallback after the phone lost its clock: the ROM's
            # build time and counting. Not the time — wait for NITZ/NTP.
            self._back_pending = None
            if not self._build_logged:
                self._build_logged = True
                log.warning("Car phone: the phone's clock (%d) is within %d h of its ROM "
                            "build time (%d) — it has not synced since it lost the time; "
                            "not used", epoch, BUILD_TIME_GUARD_S // 3600, build)
            return
        if drift <= -BACKWARD_CONFIRM_S:
            pending = self._back_pending
            if pending is None or abs(drift - pending) > BACKWARD_CONFIRM_TOL_S:
                self._back_pending = drift
                log.info("Car phone: the phone's clock is %.0f s behind this one — "
                         "confirming at the next check before stepping the clock back", -drift)
                return
            log.info("Car phone: the phone's clock is still %.0f s behind (confirmed)", -drift)
        self._back_pending = None
        rc, out, err = _run_cmd(self._runner, ["timedatectl", "set-time", f"@{epoch}"],
                                SET_TIME_TIMEOUT_S, on_missing=self._warn_missing)
        if rc != 0:
            if not self._time_warned:
                self._time_warned = True
                log.warning("Car phone: setting the clock from the phone failed: %s",
                            err or out.strip() or f"exit {rc}")
            return
        self._time_synced_at = self._wall()
        log.info("Car phone: clock set from the phone (drift %+.0f s)", drift)

    def _read_build_epoch(self, serial: str) -> Optional[int]:
        """The phone's ROM build time — read once per appearance (an OTA
        changes it only with a reboot, which is a new appearance)."""
        if self._build_epoch is None:
            rc, out, _err = self._adb(["adb", "-s", serial, "shell", "getprop",
                                       "ro.build.date.utc"])
            if rc == 0:
                self._build_epoch = parse_build_epoch(out)
        return self._build_epoch

    # ── heat ──────────────────────────────────────────────────────────────

    def _heat_check(self, temp: Optional[float], overheat: bool, now: float) -> None:
        """Hysteresis: warning from ``warn_temp_c``, danger from
        ``critical_temp_c`` (or Android's own "overheat" health); clears only
        below ``warn_temp_c - 3``. Announced on every escalation and at most
        every 60 s while it lasts (the notification's TTL is 60 s)."""
        level = self._heat
        if temp is None and not overheat:
            return          # no reading: keep the level, announce nothing
        if overheat or (temp is not None and temp >= self._crit_c):
            new = "danger"
        elif temp is not None and temp >= self._warn_c:
            new = "warning"
        elif temp is not None and level is not None and temp >= self._warn_c - HEAT_CLEAR_MARGIN_C:
            new = "warning"
        else:
            new = None
        if new is None:
            if level is not None:
                log.info("Car phone: battery temperature back to %.1f C", temp)
            self._clear_heat()
            return
        escalated = level != new and (level is None or new == "danger")
        due = self._heat_announced_at is None or now - self._heat_announced_at >= HEAT_REANNOUNCE_S
        self._heat = new
        if not (escalated or due):
            return
        self._heat_announced_at = now
        temp_txt = f"{temp:.0f} °C" if temp is not None else "przegrzanie"
        if new == "danger":
            title = "Telefon w aucie: krytyczna temperatura"
            desc = f"Bateria {temp_txt} — odłącz zasilanie, osłoń przed słońcem"
        else:
            title = "Telefon w aucie się grzeje"
            desc = f"Bateria {temp_txt}"
        if escalated:
            log.warning("Car phone: battery %s (%s)", new, temp_txt)
        try:
            self._notify(self._bus, title, desc, severity=new, icon="device_thermostat",
                         ttl=HEAT_NOTIFY_TTL_S, key="car_phone_heat")
        except Exception:
            log.debug("heat notification failed", exc_info=True)

    def _clear_heat(self) -> None:
        self._heat = None
        self._heat_announced_at = None

    # ── state / scheduling ────────────────────────────────────────────────

    def _reset_backoff(self) -> None:
        self._delay = self._retry_sec
        self._retry_at = 0.0
        self._retry_kind = None
        self._last_error = ""
        self._last_hint = ""

    def _fail(self, now: float, state: str, error: str, adb_field: str,
              hint: str = "") -> None:
        """A real attempt failed: wait ``delay``, then double it (capped)."""
        error = clean_error(error)
        delay = min(self._delay, self._max_retry_sec)
        self._retry_at = now + delay
        self._retry_kind = "backoff"
        self._delay = min(delay * 2, self._max_retry_sec)
        self._last_error = error
        self._last_hint = hint
        if self._publish(state, adb=adb_field, error=error, hint=hint):
            log.warning("Car phone: %s (%s) — next attempt in %ds", state, error, delay)
        else:
            log.debug("Car phone: still %s (%s) — next attempt in %ds", state, error, delay)

    def _publish(self, state: str, adb: str = "", iface: str = "", ip: str = "",
                 prefix: Optional[int] = None, gateway: str = "", error: str = "",
                 hint: str = "") -> bool:
        """Publish ``net.car_phone`` if anything changed. True if published."""
        if self._stop.is_set() and state != "disabled":
            return False    # a pass still finishing after stop() stays quiet
        if state == "disabled":
            dev = self._empty_device()
            serial = ""
        else:
            dev = self._device
            serial = mask_serial(self._serial)
        if not error and state != "disabled" and self._fwd_error:
            error = self._fwd_error
        payload = {
            "state": state,
            "adb": adb if adb in ADB_STATES else "",
            "serial": serial,
            "iface": iface if isinstance(iface, str) and IFACE_RE.fullmatch(iface) else "",
            "ip": ip,
            "prefix": prefix,
            "gateway": gateway,
            "gps_forward": bool(dev["gps_forward"]),
            "gps_port": self._gps_local if dev["gps_forward"] else None,
            "battery_pct": dev["battery_pct"],
            "temp_c": dev["temp_c"],
            "charging": dev["charging"],
            "full": dev["full"],
            "plugged": dev["plugged"],
            "health": dev["health"],
            "overridden": bool(dev["overridden"]),
            "hotspot_active": dev["hotspot_active"],
            "hotspot_clients": dev["hotspot_clients"],
            "heat": self._heat if state != "disabled" else None,
            "time_synced_at": self._time_synced_at,
            "error": clean_error(error),
            "hint": hint if hint in HINTS else "",
        }
        if payload == self._payload:
            return False
        if state != self._state_name or self._payload is None:
            self._since = self._wall()
            if state != self._state_name and state not in ("failed", "adb_error"):
                detail = ""
                if state == "connected":
                    detail = f" ({ip or '-'}/{prefix} via {gateway or '-'} on {iface or '-'})"
                elif payload["error"]:
                    detail = f" — {payload['error']}"
                log.info("Car phone: %s -> %s%s", self._state_name, state, detail)
        self._payload = payload
        self._state_name = state
        try:
            self._bus.publish(TOPIC, dict(payload, since=self._since))
        except Exception:
            log.exception("Publishing %s failed", TOPIC)
        return True

    def _warn_once(self, key: str, message: str) -> None:
        if key not in self._warned:
            self._warned.add(key)
            log.warning(message)

    def _warn_missing(self, prog: str) -> None:
        hints = {"adb": "apt install adb (config/scripts/apply-fixes.sh)",
                 "nmcli": "USB tethering needs NetworkManager",
                 "timedatectl": "the clock cannot be set from the phone"}
        self._warn_once(f"missing:{prog}", f"Car phone: {prog} not installed — "
                        f"{hints.get(prog, 'the step that needs it is skipped')}")


def start_car_phone(config, event_bus, hal=None, **kwargs) -> CarPhone:
    """Module entry point — called by main.py's module registry. Only builds
    the object and starts its daemon thread; every adb/nmcli call happens
    there, so a hung adb server never delays the other modules."""
    phone = CarPhone(config, event_bus)
    phone.start()
    return phone
