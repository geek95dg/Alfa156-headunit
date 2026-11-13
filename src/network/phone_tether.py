"""Internet from the phone over Bluetooth PAN, driven through NetworkManager.

Why this exists
---------------
The test car has no LTE modem, but the phone is connected over Bluetooth
practically all the time. Android's "Bluetooth tethering" offers a NAP
(Network Access Point); the head unit joins it as a PANU client and gets a
``bnep*`` interface with a DHCP address from the phone. NetworkManager can
do all of that (bluetooth device plugin + the ``bnep`` kernel module) — what
was missing is something that creates the profile for the *right* phone and
brings it up whenever that phone is around. Weather, the route planner and
the clock (bcm-timesync) then simply have an uplink.

Enabled by ``modules.phone_tether`` only (registry module, default off), so
the production config keeps its behaviour. Settings live in
``network.phone_tether`` (see :data:`DEFAULTS`).

One reconciliation step (:meth:`PhoneTether.tick`)
--------------------------------------------------
1. ``nmcli -t -f RUNNING general`` — NetworkManager running? If not:
   ``unavailable``, re-checked with backoff (a missing NM does not come back
   by itself every 30 s, and the log should not say so every 30 s either).
2. ``nmcli -t -f DEVICE,TYPE,STATE device`` — NM lists a ``bt`` device named
   after the phone's address when BlueZ reports the NAP service for it.
   Missing => ``no_nap``. Nothing is attempted, it is just looked at again
   on the next check.
3. Our profile (``con_name``): created when missing (``nmcli`` exit 10),
   corrected when it points at another phone / type / route metric /
   autoconnect setting (``autoconnect``, default off — see :data:`DEFAULTS`).
4. ``nmcli --wait 30 connection up id <con>`` — on failure ``failed`` with
   ``hint: check_tethering`` and an exponential backoff (``retry_sec``
   doubling up to ``max_retry_connected_sec``), reset by every new
   ``bt.connected`` and by ``net.phone_tether.cmd.retry`` (the "Ponów"
   button in Settings).
5. ``nmcli -g GENERAL.IP-IFACE,IP4.ADDRESS,IP4.GATEWAY device show <MAC>`` —
   iface / ip / prefix / gateway for the UI.

Tethering switched off on the phone — expected, NOT verified on the car:
BlueZ caches the phone's service UUIDs from pairing and Android keeps its
NAP SDP record registered while tethering is off; it refuses the BNEP
connect instead. NetworkManager then still lists the ``bt`` device and the
usual picture is step 4 failing, not step 2 — that is why a failed
``connection up`` carries the "turn on tethering" hint and is retried at
most every ``max_retry_connected_sec`` (120 s) rather than ``max_retry_sec``:
a refused BNEP connect is a single cheap L2CAP exchange, and the driver who
has just switched tethering on should not wait ten minutes. ``no_nap``
remains for phones (or NM versions) that really drop the device.
To check on the car: ``nmcli -t -f DEVICE,TYPE,STATE device`` and
``nmcli connection up id bcm-phone-pan`` with tethering off.

Steps 3-4 are the only ones that make BlueZ do anything (``Network1.Connect``
opens a BNEP channel); 1, 2 and 5 only ask NetworkManager over D-Bus. They
are gated by the backoff and, after a fresh ``bt.connected``, by
``settle_sec`` — Android Auto bootstraps its Wi-Fi credentials over RFCOMM
in the first seconds after the phone connects and should have the radio to
itself while doing so. The same reason keeps the check interval at
``check_sec`` (30 s) instead of polling.

Published on ``net.phone_tether`` (only when something changed)::

    {state, iface, ip, prefix, gateway, mac, error, hint, since}

    state: disabled | unavailable | waiting_phone | no_nap | connecting
           | connected | failed
    hint:  '' | check_tethering (``connection up`` failed — the Settings row
           tells the driver to check "Tethering przez Bluetooth")
    since: wall-clock time (epoch s) the current state was entered

On every transition into ``connected`` (with ``trigger_timesync``) it starts
``bcm-timesync.service`` once, without waiting for it — the clock is often
hours off after a power cut and this is the first moment it can be fixed.
``bt.disconnected`` => ``waiting_phone``; NetworkManager tears the bnep link
down by itself when the phone goes.

Security: the phone's address is validated (``AA:BB:CC:DD:EE:FF`` after
upper-casing) before it is used anywhere, the profile name against a safe
charset; nothing else from the bus or the config reaches nmcli. Every command
is an argv list with a timeout (never a shell); stderr shown in the status is
cleaned and cut to 200 characters. A missing nmcli is a state, not a crash.
"""

from __future__ import annotations

import re
import subprocess
import threading
import time
from typing import Any, Callable, Optional

from src.core.logger import get_logger
# Shared with car_phone (adb + nmcli): argv-only runner that never raises,
# LC_ALL=C, error cleaning, config readers. Re-exported here so existing
# imports (web_viewer, tests) keep working.
from src.network._proc import ERROR_MAX as ERROR_MAX
from src.network._proc import IFACE_RE as IFACE_RE
from src.network._proc import PROBE_TIMEOUT_S as PROBE_TIMEOUT_S
from src.network._proc import _cfg_get as _cfg_get
from src.network._proc import _number as _proc_number
# Named _run_cmd here: PhoneTether._run is the worker thread's loop.
from src.network._proc import _run as _run_cmd
from src.network._proc import clean_error as clean_error
from src.network._proc import parse_ip_status as parse_ip_status
from src.network._proc import proc_env as proc_env
from src.network._proc import split_terse as split_terse

log = get_logger("network.phone_tether")

TOPIC = "net.phone_tether"
#: Argument-free "try again now" (web_viewer's rate-limited POST route).
RETRY_TOPIC = "net.phone_tether.cmd.retry"

#: Every state the module publishes (web_viewer accepts only these).
STATES = ("disabled", "unavailable", "waiting_phone", "no_nap",
          "connecting", "connected", "failed")

#: ``hint`` values (web_viewer passes only these on).
HINT_CHECK_TETHERING = "check_tethering"
HINTS = ("", HINT_CHECK_TETHERING)

#: Code defaults for ``network.phone_tether``.
DEFAULTS: dict[str, Any] = {
    # '' = follow the phone from bt.connected, then multimedia.last_bt_device.
    # Set it to pin one phone (a passenger's phone then never gets a profile).
    "mac": "",
    "con_name": "bcm-phone-pan",
    # NetworkManager's own default metric for Bluetooth; a future LTE modem
    # (NM default 700) wins the default route automatically.
    "route_metric": 750,
    "retry_sec": 60,
    # Cap for NetworkManager being down / the profile not being writable —
    # things that do not fix themselves in a minute.
    "max_retry_sec": 600,
    # Cap for a failed `connection up`. It is only ever attempted while the
    # phone is connected over BT, and the usual cause is tethering switched
    # off on the phone (see the module docstring); clamped to
    # [retry_sec, max_retry_sec].
    "max_retry_connected_sec": 120,
    "check_sec": 30,
    # Quiet time after a fresh bt.connected before BlueZ is asked for PAN,
    # so the AA wireless bootstrap over RFCOMM is not disturbed.
    "settle_sec": 15,
    "trigger_timesync": True,
    # connection.autoconnect of our profile. Off on purpose: NetworkManager
    # treats a paired phone's NAP as available even when the phone is out of
    # range, so with autoconnect it would page the phone on its own schedule
    # and bring PAN up in the middle of the AA bootstrap — bypassing
    # bt.connected, settle_sec and the backoff above. (nm-applet creates its
    # Bluetooth profiles with autoconnect off for the same reason.) This
    # module re-checks every check_sec, so a dropped link comes back anyway.
    "autoconnect": False,
}

#: Validated before ANY use; nothing else is ever passed to nmcli as a MAC.
MAC_RE = re.compile(r"^[0-9A-F]{2}(:[0-9A-F]{2}){5}$")
#: Profile names we accept. Starts with an alphanumeric so it can never be
#: read as an nmcli option.
CON_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")

#: nmcli exit status "connection, device or access point does not exist".
NMCLI_NOT_FOUND = 10
EDIT_TIMEOUT_S = 15.0
UP_WAIT_S = 30
UP_TIMEOUT_S = UP_WAIT_S + 15.0
TIMESYNC_TIMEOUT_S = 10.0
TIMESYNC_ARGV = ["systemctl", "start", "--no-block", "bcm-timesync.service"]


# ── pure helpers (tested directly) ─────────────────────────────────────────

def normalize_mac(value: Any) -> Optional[str]:
    """``aa:bb:cc:dd:ee:ff`` → ``AA:BB:CC:DD:EE:FF``; None if not a MAC."""
    if not isinstance(value, str):
        return None
    mac = value.strip().upper()
    return mac if MAC_RE.fullmatch(mac) else None


def parse_bt_devices(text: str) -> dict[str, str]:
    """``DEVICE,TYPE,STATE`` rows → ``{MAC: state}`` for ``bt`` devices only."""
    out: dict[str, str] = {}
    for line in (text or "").splitlines():
        fields = split_terse(line)
        if len(fields) < 3 or fields[1].strip() != "bt":
            continue
        mac = normalize_mac(fields[0])
        if mac:
            out[mac] = fields[2].strip().lower()
    return out


def _get_values(text: str, count: int) -> list[str]:
    """Values of ``nmcli -g f1,f2,…``: one per line (detail views), or one
    terse line split on unescaped ``:``. Always ``count`` items."""
    lines = (text or "").splitlines()
    if len(lines) == 1 and count > 1:
        values = split_terse(lines[0])
    else:
        values = ["".join(split_terse(line)) if "\\" in line else line for line in lines]
    values = [v.strip() for v in values]
    return (values + [""] * count)[:count]


#: Profile properties read back (and corrected) by _ensure_profile, in order.
PROFILE_FIELDS = "bluetooth.bdaddr,bluetooth.type,ipv4.route-metric,connection.autoconnect"


def parse_profile(text: str) -> tuple[str, str, str, str]:
    """Values of :data:`PROFILE_FIELDS`: bdaddr, type, metric, autoconnect."""
    bdaddr, bt_type, metric, autoconnect = _get_values(text, 4)
    return bdaddr, bt_type.lower(), metric, autoconnect.lower()


def _number(value: Any, default: float, lo: float, hi: float, name: str) -> float:
    """:func:`src.network._proc._number` for ``network.phone_tether.*``."""
    return _proc_number("network.phone_tether", value, default, lo, hi, name, logger=log)


# ── the manager ────────────────────────────────────────────────────────────

class PhoneTether:
    """Keeps a Bluetooth PAN link to the phone up through NetworkManager.

    Args:
        config: BCMConfig (dotted ``get``) or a plain nested dict.
        event_bus: EventBus (``subscribe``/``publish``/``get_last``).
        runner: ``subprocess.run`` compatible — the test seam; every call is
            an argv list.
        clock: monotonic seconds; schedules backoff and settle (a wall-clock
            jump from bcm-timesync must not stretch or skip a retry).
        wall_clock: epoch seconds for the published ``since``.
    """

    def __init__(self, config: Any, event_bus: Any,
                 runner: Callable[..., Any] = subprocess.run,
                 clock: Callable[[], float] = time.monotonic,
                 wall_clock: Callable[[], float] = time.time) -> None:
        self._config = config
        self._bus = event_bus
        self._runner = runner
        self._clock = clock
        self._wall = wall_clock

        section = _cfg_get(config, "network.phone_tether", {})
        if not isinstance(section, dict):
            section = {}

        def opt(key: str) -> Any:
            return section.get(key, DEFAULTS[key])

        # Kept raw: an invalid pinned MAC must stay invalid (state failed),
        # not silently fall back to "any connected phone".
        pinned = opt("mac")
        if isinstance(pinned, str):
            self._pinned_raw = pinned.strip()
        else:
            self._pinned_raw = "" if pinned is None else repr(pinned)
        con = opt("con_name")
        if isinstance(con, str) and CON_NAME_RE.fullmatch(con):
            self._con_name = con
        else:
            log.warning("network.phone_tether.con_name=%r is not a safe profile name "
                        "(letters, digits, _ . -) — using %r", con, DEFAULTS["con_name"])
            self._con_name = DEFAULTS["con_name"]
        self._metric = int(_number(opt("route_metric"), DEFAULTS["route_metric"],
                                   0, 2**31 - 1, "route_metric"))
        self._retry_sec = float(_number(opt("retry_sec"), DEFAULTS["retry_sec"],
                                        5, 3600, "retry_sec"))
        self._max_retry_sec = float(_number(opt("max_retry_sec"), DEFAULTS["max_retry_sec"],
                                            self._retry_sec, 86400, "max_retry_sec"))
        self._max_retry_up_sec = float(_number(
            opt("max_retry_connected_sec"), DEFAULTS["max_retry_connected_sec"],
            self._retry_sec, self._max_retry_sec, "max_retry_connected_sec"))
        self._check_sec = float(_number(opt("check_sec"), DEFAULTS["check_sec"],
                                        5, 3600, "check_sec"))
        self._settle_sec = float(_number(opt("settle_sec"), DEFAULTS["settle_sec"],
                                         0, 300, "settle_sec"))
        timesync = opt("trigger_timesync")
        self._trigger_timesync = timesync if isinstance(timesync, bool) else True
        autoconnect = opt("autoconnect")
        self._autoconnect = autoconnect if isinstance(autoconnect, bool) else False

        # tick() runs one pass at a time; stop() never takes this lock
        # (a pass can sit in `connection up --wait 30`).
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # Phone presence, written by the bus callbacks (cheap, no I/O) and
        # read by tick(). _connect_gen bumps on every bt.connected so tick()
        # can tell a NEW connection (reset backoff, settle) from an old one.
        self._ev_lock = threading.Lock()
        self._phone_connected = False
        self._phone_addr: Optional[str] = None
        self._connect_gen = 0
        self._bt_events = 0
        self._seen_gen = 0
        # Bumped by net.phone_tether.cmd.retry; tick() drops the backoff.
        self._retry_req = 0
        self._seen_retry = 0

        # Retry scheduling (monotonic). _retry_kind: None | "settle" | "backoff".
        self._delay = self._retry_sec
        self._retry_at = 0.0
        self._retry_kind: Optional[str] = None
        self._last_error = ""
        self._last_hint = ""

        # Published state.
        self._payload: Optional[dict[str, Any]] = None
        self._state_name = "disabled"
        self._since = 0.0
        self._warned: set[str] = set()

    # ── read-only views (UI / tests) ──────────────────────────────────────

    @property
    def state(self) -> Optional[dict[str, Any]]:
        """Last published payload (copy) or None."""
        if self._payload is None:
            return None
        return dict(self._payload, since=self._since)

    @property
    def retry_delay(self) -> float:
        """Backoff the NEXT failure will wait for."""
        return self._delay

    @property
    def retry_at(self) -> float:
        """Monotonic time before which gated steps are skipped (0 = none)."""
        return self._retry_at

    @property
    def con_name(self) -> str:
        return self._con_name

    def _subscriptions(self) -> tuple:
        return (("bt.connected", self._on_bt_connected),
                ("bt.disconnected", self._on_bt_disconnected),
                (RETRY_TOPIC, self._on_retry_cmd),
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
                                        name="phone-tether")
        self._thread.start()
        if self._pinned_raw:
            mac_desc = normalize_mac(self._pinned_raw) or "<invalid network.phone_tether.mac>"
        else:
            mac_desc = "<from bt.connected>"
        log.info("Phone tether started (profile=%s, mac=%s, metric=%d, check=%ds, "
                 "retry=%d..%ds (up: ..%ds), settle=%ds, autoconnect=%s)", self._con_name,
                 mac_desc, self._metric, self._check_sec, self._retry_sec,
                 self._max_retry_sec, self._max_retry_up_sec, self._settle_sec,
                 self._autoconnect)

    def seed_from_bus(self) -> None:
        """The phone may have connected before we subscribed (BT starts
        first). Take the newer of the last bt.connected / bt.disconnected —
        unless a callback already told us something fresher."""
        try:
            last_c = self._bus.get_last("bt.connected")
            last_d = self._bus.get_last("bt.disconnected")
        except Exception:
            return
        with self._ev_lock:
            if self._bt_events:
                return
            if last_c is not None and last_c[0] and (last_d is None or last_c[1] > last_d[1]):
                self._phone_connected = True
                self._phone_addr = self._address_of(last_c[0])
                self._connect_gen += 1

    def stop(self) -> None:
        """Stop the worker. Never waits for a pass in progress; the link
        itself is left to NetworkManager (it outlives BCM restarts)."""
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
        log.info("Phone tether stopped")

    def _on_shutdown(self, topic: str, value: Any, timestamp: float) -> None:
        if value:
            self.stop()

    def _run(self) -> None:
        while not self._stop.is_set():
            # Clear BEFORE the pass: a bus event during tick() then makes the
            # wait below return at once instead of being lost.
            self._wake.clear()
            try:
                self.tick()
            except Exception:
                log.exception("Phone tether pass failed")
            self._wake.wait(self.next_wait())

    def next_wait(self) -> float:
        """Seconds until the next pass: ``check_sec``, or sooner when a
        settle/backoff deadline falls inside that window."""
        wait = self._check_sec
        if self._retry_kind is not None:
            remaining = self._retry_at - self._clock()
            if 0 < remaining < wait:
                wait = remaining
        return max(1.0, wait)

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
            if value:
                self._phone_connected = True
                self._phone_addr = self._address_of(value)
                self._connect_gen += 1
            else:
                self._phone_connected = False
        self._wake.set()

    def _on_bt_disconnected(self, topic: str, value: Any, timestamp: float) -> None:
        addr = normalize_mac(self._address_of(value))
        with self._ev_lock:
            self._bt_events += 1
            current = normalize_mac(self._phone_addr)
            # BCM tracks one phone; a disconnect naming a different device
            # (stale event, second device) must not take our link's state down.
            if addr and current and addr != current:
                return
            self._phone_connected = False
        self._wake.set()

    def _on_retry_cmd(self, topic: str, value: Any, timestamp: float) -> None:
        """"Try again now" from Settings. The value is ignored (nothing from
        the browser reaches nmcli); tick() only drops a running backoff — the
        settle gate after bt.connected stays, it protects the AA bootstrap.
        web_viewer rate-limits the route; a burst here still costs at most
        one extra pass."""
        with self._ev_lock:
            self._retry_req += 1
        self._wake.set()

    # ── one pass ──────────────────────────────────────────────────────────

    def tick(self) -> str:
        """One reconciliation step. Returns the resulting state name."""
        with self._lock:
            if self._stop.is_set():
                return self._state_name
            now = self._clock()
            with self._ev_lock:
                connected = self._phone_connected
                addr = self._phone_addr
                gen = self._connect_gen
                retry_req = self._retry_req

            if gen != self._seen_gen:
                # A new phone connection: forget earlier failures and give
                # the AA bootstrap its quiet seconds before touching BlueZ.
                self._seen_gen = gen
                self._delay = self._retry_sec
                self._last_error = ""
                self._last_hint = ""
                self._schedule(now, self._settle_sec, "settle")
            if retry_req != self._seen_retry:
                self._seen_retry = retry_req
                if self._retry_kind == "backoff":
                    log.info("Phone tether: retry requested — backoff dropped")
                    self._delay = self._retry_sec
                    self._retry_at = 0.0
                    self._retry_kind = None

            pinned = normalize_mac(self._pinned_raw) if self._pinned_raw else None
            if not connected:
                self._publish("waiting_phone", mac=pinned or normalize_mac(addr) or "")
                return self._state_name

            mac, why = self._resolve_mac(addr)
            if mac is None:
                self._warn_once(f"mac:{why}", f"Phone tether: {why} — not touching nmcli")
                self._publish("failed", error=why)
                return self._state_name
            connected_mac = normalize_mac(addr)
            if pinned and connected_mac and connected_mac != pinned:
                self._publish("waiting_phone", mac=pinned,
                              error="connected phone is not network.phone_tether.mac")
                return self._state_name

            # NetworkManager down: re-check slowly (backoff), not every pass.
            if self._state_name == "unavailable" and self._retry_kind == "backoff" \
                    and now < self._retry_at:
                return self._state_name

            rc, out, err = self._nm(["nmcli", "-t", "-f", "RUNNING", "general"])
            if rc != 0 or out.strip().lower() != "running":
                self._fail(now, "unavailable",
                           err or out.strip() or "NetworkManager is not running", mac)
                return self._state_name

            rc, out, err = self._nm(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "device"])
            if rc != 0:
                self._fail(now, "unavailable", err or f"nmcli device: exit {rc}", mac)
                return self._state_name
            dev_state = parse_bt_devices(out).get(mac)

            if dev_state is None:
                # Same picture when NM's bluetooth plugin is missing — the
                # hint names both (bcm-harden.sh step 8 checks the plugin).
                self._publish("no_nap", mac=mac,
                              error="NetworkManager lists no Bluetooth network (NAP) for "
                                    "the phone — turn on Bluetooth tethering on the phone "
                                    "(or the NM bluetooth plugin is missing)")
                return self._state_name
            if dev_state.startswith("connected"):
                self._connected(mac)
                return self._state_name
            if dev_state.startswith("connecting"):
                # NM (autoconnect) or an earlier `up` is already on it.
                self._publish("connecting", mac=mac)
                return self._state_name
            if dev_state == "deactivating":
                return self._state_name     # transient; look again next pass
            if dev_state in ("unavailable", "unmanaged", "unknown"):
                self._publish("no_nap", mac=mac,
                              error=f"NetworkManager reports the phone's device as {dev_state}")
                return self._state_name

            # disconnected (or failed): bring it up — gated by settle/backoff.
            if self._retry_kind is not None and now < self._retry_at:
                if self._retry_kind == "settle":
                    self._publish("connecting", mac=mac)
                else:
                    self._publish("failed", mac=mac, error=self._last_error,
                                  hint=self._last_hint)
                return self._state_name

            if not self._ensure_profile(now, mac):
                return self._state_name
            self._publish("connecting", mac=mac)
            rc, out, err = self._nm(["nmcli", "--wait", str(UP_WAIT_S), "connection",
                                     "up", "id", self._con_name], timeout=UP_TIMEOUT_S)
            if self._stop.is_set():
                return self._state_name
            if rc != 0:
                # NM lists the phone but the link will not come up — with
                # Android that mostly means tethering is off (module
                # docstring): say so in the UI and retry on the short cap.
                self._fail(now, "failed", err or out.strip() or f"connection up: exit {rc}",
                           mac, hint=HINT_CHECK_TETHERING, cap=self._max_retry_up_sec)
                return self._state_name
            self._connected(mac)
            return self._state_name

    # ── steps ─────────────────────────────────────────────────────────────

    def _resolve_mac(self, addr: Optional[str]) -> tuple[Optional[str], str]:
        """The phone to tether to: pinned MAC, else the connected phone, else
        the last one used. Never falls through past an INVALID value — that
        could pick a different device than the one meant."""
        if self._pinned_raw:
            mac = normalize_mac(self._pinned_raw)
            if mac is None:
                return None, "invalid network.phone_tether.mac (expected AA:BB:CC:DD:EE:FF)"
            return mac, ""
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

    def _ensure_profile(self, now: float, mac: str) -> bool:
        """Create or correct our NM profile. False (state published) on error.

        Assumptions (nmcli ≥ 1.20, verified against the nmcli/nm-settings
        documentation, not on the car): ``ifname '*'`` = no interface binding,
        ``bluetooth.type panu`` = PAN client, ``ipv6.method disabled``,
        ``-g`` prints one value per line for a connection's details, exit 10
        = profile does not exist.
        """
        con = self._con_name
        rc, out, err = self._nm(["nmcli", "-g", PROFILE_FIELDS,
                                 "connection", "show", "id", con])
        if rc == NMCLI_NOT_FOUND:
            rc, out, err = self._nm(
                ["nmcli", "connection", "add", "type", "bluetooth",
                 "con-name", con, "ifname", "*",
                 "bluetooth.bdaddr", mac, "bluetooth.type", "panu",
                 "ipv4.method", "auto", "ipv4.route-metric", str(self._metric),
                 "ipv6.method", "disabled",
                 "connection.autoconnect", "yes" if self._autoconnect else "no"],
                timeout=EDIT_TIMEOUT_S)
            if rc != 0:
                self._fail(now, "failed", f"creating profile {con} failed: "
                           f"{err or out.strip() or f'exit {rc}'}", mac)
                return False
            log.info("Phone tether: created NetworkManager profile %s for %s", con, mac)
            return True
        if rc != 0:
            self._fail(now, "failed", f"reading profile {con} failed: "
                       f"{err or out.strip() or f'exit {rc}'}", mac)
            return False

        bdaddr, bt_type, metric, autoconnect = parse_profile(out)
        changes: list[str] = []
        if normalize_mac(bdaddr) != mac:
            changes += ["bluetooth.bdaddr", mac]
        if bt_type != "panu":
            changes += ["bluetooth.type", "panu"]
        # Compare only a value we could read — an unparsable one must not
        # turn every attempt into a modify.
        if re.fullmatch(r"-?\d+", metric) and int(metric) != self._metric:
            changes += ["ipv4.route-metric", str(self._metric)]
        want_auto = "yes" if self._autoconnect else "no"
        if autoconnect in ("yes", "no") and autoconnect != want_auto:
            changes += ["connection.autoconnect", want_auto]
        if changes:
            rc, out, err = self._nm(["nmcli", "connection", "modify", "id", con] + changes,
                                    timeout=EDIT_TIMEOUT_S)
            if rc != 0:
                self._fail(now, "failed", f"updating profile {con} failed: "
                           f"{err or out.strip() or f'exit {rc}'}", mac)
                return False
            log.info("Phone tether: profile %s updated (%s)", con,
                     ", ".join(changes[0::2]))
        return True

    def _connected(self, mac: str) -> None:
        """Link is up: read the addresses, publish, kick the clock sync."""
        rc, out, _err = self._nm(["nmcli", "-g", "GENERAL.IP-IFACE,IP4.ADDRESS,IP4.GATEWAY",
                                  "device", "show", mac])
        status = parse_ip_status(out) if rc == 0 else {}
        was = self._state_name
        self._delay = self._retry_sec
        self._retry_at = 0.0
        self._retry_kind = None
        self._last_error = ""
        self._last_hint = ""
        self._publish("connected", mac=mac, **status)
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

    # ── state / scheduling ────────────────────────────────────────────────

    def _schedule(self, now: float, delay: float, kind: str) -> None:
        self._retry_at = now + delay
        self._retry_kind = kind

    def _fail(self, now: float, state: str, error: str, mac: str,
              hint: str = "", cap: Optional[float] = None) -> None:
        """A real attempt failed: wait ``delay``, then double it, both capped
        at ``cap`` (default ``max_retry_sec``)."""
        cap = self._max_retry_sec if cap is None else cap
        error = clean_error(error)
        delay = min(self._delay, cap)
        self._schedule(now, delay, "backoff")
        self._delay = min(delay * 2, cap)
        self._last_error = error
        self._last_hint = hint
        if self._publish(state, mac=mac, error=error, hint=hint):
            log.warning("Phone tether: %s (%s) — next attempt in %ds", state, error, delay)
        else:
            log.debug("Phone tether: still %s (%s) — next attempt in %ds", state, error, delay)

    def _publish(self, state: str, mac: str = "", iface: str = "", ip: str = "",
                 prefix: Optional[int] = None, gateway: str = "", error: str = "",
                 hint: str = "") -> bool:
        """Publish ``net.phone_tether`` if anything changed. True if published."""
        if self._stop.is_set() and state != "disabled":
            return False    # a pass still finishing after stop() stays quiet
        payload = {"state": state, "iface": iface, "ip": ip, "prefix": prefix,
                   "gateway": gateway, "mac": mac, "error": clean_error(error),
                   "hint": hint if hint in HINTS else ""}
        if payload == self._payload:
            return False
        if state != self._state_name or self._payload is None:
            self._since = self._wall()
            # failed/unavailable are logged as warnings by _fail() (with the
            # retry delay); everything else is a normal transition.
            if state != self._state_name and state not in ("failed", "unavailable"):
                detail = ""
                if state == "connected":
                    detail = f" ({ip or '-'}/{prefix} via {gateway or '-'} on {iface or '-'})"
                elif payload["error"]:
                    detail = f" — {payload['error']}"
                log.info("Phone tether: %s -> %s%s", self._state_name, state, detail)
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

    def _nm(self, argv: list[str], timeout: float = PROBE_TIMEOUT_S) -> tuple[int, str, str]:
        """Run one command (:func:`src.network._proc._run`). Never raises;
        ``(rc, stdout, cleaned stderr)`` — 127 missing binary (one warning per
        program), 124 timeout."""
        return _run_cmd(self._runner, argv, timeout, on_missing=self._warn_missing)

    def _warn_missing(self, prog: str) -> None:
        self._warn_once(f"missing:{prog}",
                        f"Phone tether: {prog} not installed — internet from the "
                        "phone needs NetworkManager")


def start_phone_tether(config, event_bus, hal=None, **kwargs) -> PhoneTether:
    """Module entry point — called by main.py's module registry."""
    tether = PhoneTether(config, event_bus)
    tether.start()
    return tether
