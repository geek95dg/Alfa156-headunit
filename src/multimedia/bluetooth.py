"""BlueZ Bluetooth configuration — A2DP sink + HFP for phone audio.

Manages Bluetooth pairing, A2DP audio streaming (phone -> PipeWire -> DAC),
and HFP hands-free calling with mic + speaker routing.

Uses bluetoothctl CLI for device management and a D-Bus pairing agent
for handling phone-initiated pairing requests.

On x86, works with built-in or USB Bluetooth adapter.
On OPi, uses onboard or USB BT.
"""

import subprocess
import threading
import time
from typing import Any, Optional

from src.core.event_bus import EventBus
from src.core.logger import get_logger

log = get_logger("multimedia.bluetooth")

# D-Bus pairing agent — optional, only works when dbus is available
try:
    import dbus
    import dbus.service
    import dbus.mainloop.glib
    HAS_DBUS = True
except ImportError:
    HAS_DBUS = False

    # Provide minimal stubs so the _PairingAgent class body can be defined
    # without NameError even when dbus-python is not installed.
    class _DbusServiceStub:
        Object = object

        @staticmethod
        def method(*args, **kwargs):
            def decorator(f):
                return f
            return decorator

    class _DbusExceptionsStub:
        DBusException = Exception

    class _DbusStub:
        service = _DbusServiceStub
        exceptions = _DbusExceptionsStub

        @staticmethod
        def UInt32(v):
            return v

        @staticmethod
        def String(v):
            return v

        @staticmethod
        def Boolean(v):
            return v

        @staticmethod
        def ObjectPath(v):
            return v

        @staticmethod
        def Interface(*args, **kwargs):
            return None

        @staticmethod
        def SystemBus():
            return None

    dbus = _DbusStub()

AGENT_PATH = "/org/bluez/bcm_agent"
_agent_registered = False  # Guard against double registration


def _device_path_to_addr(device_path: str) -> str:
    """Convert D-Bus device path to BT address.

    Example: /org/bluez/hci0/dev_C0_7A_D6_90_E9_CC → C0:7A:D6:90:E9:CC
    """
    node = device_path.split("/")[-1]  # dev_C0_7A_D6_90_E9_CC
    if node.startswith("dev_"):
        node = node[4:]  # C0_7A_D6_90_E9_CC
    return node.replace("_", ":")
AGENT_CAPABILITY = "DisplayYesNo"

# Bluetooth service UUIDs
AA_SERVICE_UUID = "4de17a00-52cb-11e6-bdf4-0800200c9a66"  # Android Auto
A2DP_SINK_UUID = "0000110b-0000-1000-8000-00805f9b34fb"   # A2DP Sink
HFP_HF_UUID = "0000111e-0000-1000-8000-00805f9b34fb"      # HFP Hands-Free

# D-Bus object paths for profiles
AA_PROFILE_PATH = "/org/bluez/bcm_aa_profile"
A2DP_PROFILE_PATH = "/org/bluez/bcm_a2dp_profile"
HFP_PROFILE_PATH = "/org/bluez/bcm_hfp_profile"

# Phone Book Access Profile (PBAP) — Client (PCE) UUID. Phones surface
# the "Share contacts & call history with car" prompt during pairing
# only when the headunit advertises this UUID in its SDP record. The
# Carkit Class-of-Device alone is not enough — Android checks for the
# PCE service before offering the toggle.
PBAP_PCE_UUID = "0000112e-0000-1000-8000-00805f9b34fb"
PBAP_PROFILE_PATH = "/org/bluez/bcm_pbap_pce"
# Message Access Profile — Client (MCE) UUID. Same story for SMS/MMS
# sharing; we advertise it so the phone offers the toggle, but the
# actual message-pull is optional and disabled by default.
MAP_MCE_UUID = "00001134-0000-1000-8000-00805f9b34fb"
MAP_PROFILE_PATH = "/org/bluez/bcm_map_mce"


class _PairingRequest:
    """Holds a pending pairing confirmation request."""

    def __init__(self, device_path: str, passkey: int):
        addr = _device_path_to_addr(device_path)
        self.device_path = device_path
        self.address = addr
        self.passkey = passkey
        self.event = threading.Event()
        self.accepted = False
        self.timestamp = time.time()

    def accept(self):
        self.accepted = True
        self.event.set()

    def reject(self):
        self.accepted = False
        self.event.set()


# Global pending pairing request — only one at a time
_pending_pairing: Optional[_PairingRequest] = None
_pairing_lock = threading.Lock()


def get_pending_pairing() -> Optional[dict]:
    """Get the current pending pairing request, if any."""
    with _pairing_lock:
        if _pending_pairing and not _pending_pairing.event.is_set():
            return {
                "address": _pending_pairing.address,
                "passkey": f"{_pending_pairing.passkey:06d}",
                "timestamp": _pending_pairing.timestamp,
            }
    return None


def confirm_pairing(accept: bool) -> bool:
    """Confirm or reject the pending pairing request."""
    with _pairing_lock:
        req = _pending_pairing
    if req and not req.event.is_set():
        if accept:
            req.accept()
            log.info("Pairing ACCEPTED by user for %s", req.address)
        else:
            req.reject()
            log.info("Pairing REJECTED by user for %s", req.address)
        return True
    return False


class _PairingAgent(dbus.service.Object):
    """BlueZ D-Bus pairing agent with interactive confirmation.

    Implements org.bluez.Agent1 interface. When a phone requests pairing,
    the passkey is exposed via get_pending_pairing() so the web UI can
    show a confirmation popup. The agent blocks until the user responds
    or a 30-second timeout expires.
    """

    AGENT_INTERFACE = "org.bluez.Agent1"
    CONFIRMATION_TIMEOUT = 30  # seconds to wait for user response

    def __init__(self, bus, path):
        super().__init__(bus, path)
        log.info("BT pairing agent registered at %s", path)

    @dbus.service.method(AGENT_INTERFACE, in_signature="", out_signature="")
    def Release(self):
        log.debug("Agent released")

    @dbus.service.method(AGENT_INTERFACE, in_signature="os", out_signature="")
    def AuthorizeService(self, device, uuid):
        log.info("Agent: authorizing service %s for %s", uuid, device)
        addr = _device_path_to_addr(device)
        _run_btctl(["trust", addr])
        return

    @dbus.service.method(AGENT_INTERFACE, in_signature="o", out_signature="s")
    def RequestPinCode(self, device):
        log.info("Agent: PIN requested for %s → 0000", device)
        return "0000"

    @dbus.service.method(AGENT_INTERFACE, in_signature="o", out_signature="u")
    def RequestPasskey(self, device):
        log.info("Agent: passkey requested for %s → 0", device)
        return dbus.UInt32(0)

    @dbus.service.method(AGENT_INTERFACE, in_signature="ouq", out_signature="")
    def DisplayPasskey(self, device, passkey, entered):
        log.info("Agent: display passkey %06d for %s", passkey, device)

    @dbus.service.method(AGENT_INTERFACE, in_signature="os", out_signature="")
    def DisplayPinCode(self, device, pincode):
        log.info("Agent: display PIN %s for %s", pincode, device)

    @dbus.service.method(AGENT_INTERFACE, in_signature="ou", out_signature="")
    def RequestConfirmation(self, device, passkey):
        global _pending_pairing
        addr = _device_path_to_addr(device)
        log.info("Agent: pairing confirmation requested — passkey %06d for %s",
                 passkey, addr)

        # Create pending request and wait for user response via web UI
        req = _PairingRequest(device, passkey)
        with _pairing_lock:
            _pending_pairing = req

        # Block until user responds or timeout
        responded = req.event.wait(timeout=self.CONFIRMATION_TIMEOUT)

        with _pairing_lock:
            _pending_pairing = None

        if not responded:
            log.warning("Agent: pairing timed out for %s (no user response in %ds)",
                        addr, self.CONFIRMATION_TIMEOUT)
            raise dbus.exceptions.DBusException(
                "org.bluez.Error.Rejected",
                "Pairing confirmation timed out")

        if not req.accepted:
            log.info("Agent: pairing rejected by user for %s", addr)
            raise dbus.exceptions.DBusException(
                "org.bluez.Error.Rejected",
                "Pairing rejected by user")

        # Accepted — trust the device
        _run_btctl(["trust", addr])
        log.info("Agent: pairing confirmed for %s", addr)
        return

    @dbus.service.method(AGENT_INTERFACE, in_signature="o", out_signature="")
    def RequestAuthorization(self, device):
        log.info("Agent: auto-authorizing %s", device)
        addr = _device_path_to_addr(device)
        _run_btctl(["trust", addr])
        return

    @dbus.service.method(AGENT_INTERFACE, in_signature="", out_signature="")
    def Cancel(self):
        global _pending_pairing
        log.debug("Agent: pairing cancelled")
        with _pairing_lock:
            if _pending_pairing:
                _pending_pairing.reject()
                _pending_pairing = None


def _register_bt_profile(bus, path: str, uuid: str, name: str,
                         role: str = "server") -> bool:
    """Register a Bluetooth profile with BlueZ ProfileManager1."""
    try:
        profile_mgr = dbus.Interface(
            bus.get_object("org.bluez", "/org/bluez"),
            "org.bluez.ProfileManager1",
        )

        opts = {
            "Name": dbus.String(name),
            "Role": dbus.String(role),
            "RequireAuthentication": dbus.Boolean(False),
            "RequireAuthorization": dbus.Boolean(False),
            "AutoConnect": dbus.Boolean(True),
        }

        profile_mgr.RegisterProfile(
            dbus.ObjectPath(path),
            uuid,
            opts,
        )
        log.info("BT profile registered: %s (UUID=%s)", name, uuid)
        return True
    except dbus.exceptions.DBusException as e:
        if "AlreadyExists" in str(e):
            log.debug("BT profile already registered: %s", name)
            return True
        log.warning("Failed to register BT profile %s: %s", name, e)
        return False
    except Exception:
        log.exception("Failed to register BT profile %s", name)
        return False


def _register_all_profiles(bus) -> None:
    """Register Bluetooth profiles with BlueZ.

    A2DP Sink and HFP profiles are NOT registered here — they are
    managed by PipeWire/WirePlumber via libspa-0.2-bluetooth. Registering
    them here would block PipeWire (BlueZ: NotPermitted) and break audio.

    The Android Auto BT service is NOT registered here — it is handled
    by autoapp's built-in btservice (Qt Bluetooth RFCOMM server) which
    properly implements the AA wireless protocol handshake. Registering
    the AA UUID here would conflict with autoapp's btservice and cause
    "Server start failed" errors.

    PBAP-PCE and MAP-MCE ARE registered here — these are client-side
    "we want to consume your phonebook/messages" advertisements that
    flip on the Android-side "Share contacts & call history with car"
    pairing prompt. They don't conflict with autoapp because autoapp
    doesn't touch PBAP/MAP. The actual data pull happens through obexd
    in src/multimedia/phonebook.py.
    """
    _register_bt_profile(bus, PBAP_PROFILE_PATH, PBAP_PCE_UUID,
                         "BCM Phonebook Client", role="client")
    _register_bt_profile(bus, MAP_PROFILE_PATH, MAP_MCE_UUID,
                         "BCM Message Client", role="client")
    log.info("BT profile registration: PBAP-PCE + MAP-MCE; "
             "A2DP/HFP=PipeWire, AA=autoapp")


def _find_adapter_dbus_path() -> str:
    """Find the D-Bus path of the preferred BT adapter (hci0/hci1/...)."""
    adapter_addr = _get_adapter_addr()
    if not adapter_addr:
        return "/org/bluez/hci0"  # fallback
    try:
        result = subprocess.run(
            ["hciconfig"],
            capture_output=True, text=True, timeout=5.0,
        )
        if result.returncode == 0:
            current_hci = None
            for line in result.stdout.splitlines():
                if line and not line[0].isspace() and line.startswith("hci"):
                    current_hci = line.split(":")[0].strip()
                if adapter_addr in line and current_hci:
                    log.info("Preferred adapter %s mapped to %s",
                             adapter_addr, current_hci)
                    return f"/org/bluez/{current_hci}"
    except Exception:
        pass
    return "/org/bluez/hci0"


def _configure_adapter(bus) -> None:
    """Configure BT adapter name + persistent pairable/discoverable.

    Class-of-Device cannot be set via D-Bus on BlueZ — it must come from
    /etc/bluetooth/main.conf (Class=0x42020c for an automotive carkit).
    bcm-bluetooth-setup.sh writes it; here we only handle runtime props.
    """
    adapter_path = _find_adapter_dbus_path()
    try:
        adapter = dbus.Interface(
            bus.get_object("org.bluez", adapter_path),
            "org.freedesktop.DBus.Properties",
        )
        # Friendly name so phones see "Alfa156 Headunit"
        adapter.Set("org.bluez.Adapter1", "Alias",
                     dbus.String("Alfa156 Headunit"))
        # Persistent pairable + discoverable so the head unit always
        # accepts the phone's first connect attempt after a cold boot.
        # Combined with main.conf AlwaysPairable=true this survives the
        # post-boot DiscoverableTimeout that otherwise drops the radio
        # into "no, you can't see me" mode after 3 minutes.
        try:
            adapter.Set("org.bluez.Adapter1", "Pairable", dbus.Boolean(True))
            adapter.Set("org.bluez.Adapter1", "Discoverable",
                        dbus.Boolean(True))
        except Exception:
            pass
        log.info("BT adapter alias set + pairable/discoverable on %s",
                 adapter_path)
    except Exception:
        log.debug("Could not configure adapter on %s (non-critical)",
                  adapter_path)


def _is_autoapp_available() -> bool:
    """Check if OpenAuto (autoapp) binary is installed."""
    import os
    for path in ["/usr/local/bin/autoapp", "/opt/openauto/bin/autoapp",
                 "/usr/bin/autoapp"]:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return True
    return False


def _start_pairing_agent() -> bool:
    """Register the D-Bus pairing agent and BT profiles with BlueZ.

    Always claims default-agent — the BCM popup is the user-visible PIN
    confirmation, so pairing requests must land here. autoapp's btservice
    handles AA-specific RFCOMM via its own profile registration, which is
    independent of the agent that confirms pairing PINs.

    Safe to call multiple times — only registers once.
    """
    global _agent_registered

    if _agent_registered:
        log.debug("D-Bus pairing agent already registered — skipping")
        return True

    if not HAS_DBUS:
        log.warning("dbus-python not available — pairing agent disabled")
        return False

    try:
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        bus = dbus.SystemBus()

        _PairingAgent(bus, AGENT_PATH)

        manager = dbus.Interface(
            bus.get_object("org.bluez", "/org/bluez"),
            "org.bluez.AgentManager1",
        )
        # Unregister any stale agent at our path before registering anew —
        # avoids "AlreadyExists" after a service restart.
        try:
            manager.UnregisterAgent(AGENT_PATH)
        except dbus.exceptions.DBusException:
            pass
        manager.RegisterAgent(AGENT_PATH, AGENT_CAPABILITY)
        try:
            manager.RequestDefaultAgent(AGENT_PATH)
            log.info("BT pairing agent active as default")
        except dbus.exceptions.DBusException as e:
            # Another agent (e.g. autoapp's) already holds default — log
            # but continue. Pairing requests routed to autoapp will not
            # surface in our UI; user can stop autoapp and retry.
            log.warning("Could not claim default BT agent (%s) — popup may not "
                        "appear until other agents release it", e)

        # Configure adapter name for discovery
        _configure_adapter(bus)

        # Register profiles (AA only if OpenAuto installed)
        _register_all_profiles(bus)

        # Run GLib main loop in background thread for D-Bus signal handling
        from gi.repository import GLib
        loop = GLib.MainLoop()
        t = threading.Thread(target=loop.run, daemon=True)
        t.start()

        _agent_registered = True
        return True
    except Exception:
        log.exception("Failed to start D-Bus pairing agent")
        return False


_PREFER_INTERNAL = False


def set_prefer_internal(flag: bool) -> None:
    """Flip vendor-8087 preference. False (default) prefers the USB dongle
    (working-around the documented M910q tx-timeout); True forces the
    integrated Intel adapter even when a dongle is present."""
    global _PREFER_INTERNAL, _PREFERRED_ADAPTER
    _PREFER_INTERNAL = bool(flag)
    _PREFERRED_ADAPTER = ""   # force re-resolve


def _find_preferred_adapter() -> str:
    """Find the best BT adapter address for headunit use.

    Default policy (M910q workaround): the integrated Intel 8087:0a2b
    (BT 4.2 on paper) is documented-broken — dmesg captures
    ``command 0xNNNN tx timeout`` → ``Resetting usb device.`` after
    ~15 minutes uptime, after which the controller disappears from
    sysfs entirely. So when both the Intel and a USB dongle
    (CSR/Realtek/Broadcom) are present, prefer the dongle even though
    it's BT 4.0 — it survives.

    Override policy (``bluetooth.prefer_internal: true`` in YAML):
    flips the bias so the Intel 8087 is picked even with a dongle
    present. Pairs with the hci watchdog in BluetoothManager which
    auto-bounces the Intel adapter on tx-timeout so the user-facing
    impact of the reset is minimised.

    An explicit ``bluetooth.preferred_adapter`` MAC in config still wins
    over both policies (lets the user pin a specific controller).
    """
    try:
        result = subprocess.run(
            ["bluetoothctl", "list"],
            capture_output=True, text=True, timeout=5.0,
        )
        if result.returncode != 0:
            return ""
        controllers: list[str] = []
        for line in result.stdout.strip().splitlines():
            parts = line.strip().split()
            if len(parts) >= 2 and parts[0] == "Controller":
                controllers.append(parts[1])
        if not controllers:
            return ""
        if len(controllers) == 1:
            return controllers[0]

        # Map controller MAC -> hciX via hciconfig output.
        addr_to_hci: dict[str, str] = {}
        try:
            hc = subprocess.run(
                ["hciconfig"],
                capture_output=True, text=True, timeout=5.0,
            )
            if hc.returncode == 0:
                current_hci = None
                for line in hc.stdout.splitlines():
                    if line and not line[0].isspace() and ":" in line:
                        current_hci = line.split(":")[0].strip()
                    if current_hci and "BD Address" in line:
                        bd = line.split("BD Address:")[1].strip().split()[0]
                        addr_to_hci[bd] = current_hci
        except Exception:
            pass

        # For each hciX, read USB vendor id from sysfs. Intel = 8087 is
        # the documented-broken radio on this hardware; prefer anything
        # else. The walk-up loop is needed because hciX/device on USB
        # combo chips points at the USB *interface*, and idVendor lives
        # one or two parents up at the USB device node.
        import os as _os

        def _hci_index(addr: str) -> int:
            hci = addr_to_hci.get(addr, "hci999")
            try:
                return int(hci[3:])
            except ValueError:
                return 999

        intel: list[str] = []
        non_intel: list[str] = []
        for addr in controllers:
            hci = addr_to_hci.get(addr)
            if not hci:
                continue
            try:
                base = _os.path.realpath(f"/sys/class/bluetooth/{hci}/device")
                vendor = ""
                cur = base
                for _ in range(4):
                    vpath = _os.path.join(cur, "idVendor")
                    if _os.path.isfile(vpath):
                        with open(vpath) as f:
                            vendor = f.read().strip().lower()
                        break
                    parent = _os.path.dirname(cur)
                    if parent == cur:
                        break
                    cur = parent
                if vendor == "8087":
                    intel.append(addr)
                elif vendor:
                    non_intel.append(addr)
            except Exception:
                pass

        if _PREFER_INTERNAL and intel:
            intel.sort(key=_hci_index)
            log.info("BT: preferring INTERNAL Intel 8087 adapter %s "
                     "(prefer_internal=true) — %d controllers seen",
                     intel[0], len(controllers))
            return intel[0]

        if non_intel:
            non_intel.sort(key=_hci_index)
            log.info("BT: preferring non-Intel adapter %s (USB dongle) over "
                     "internal Intel — %d controllers seen",
                     non_intel[0], len(controllers))
            return non_intel[0]
        # Only Intel(s) available — use the lowest-index one.
        controllers.sort(key=_hci_index)
        return controllers[0]
    except Exception:
        pass
    return ""


_PREFERRED_ADAPTER = ""
_ADAPTER_OVERRIDE = ""


def set_adapter_override(addr: str) -> None:
    """Pin a specific BT controller MAC. Empty string clears the override."""
    global _ADAPTER_OVERRIDE, _PREFERRED_ADAPTER
    _ADAPTER_OVERRIDE = (addr or "").strip().upper()
    _PREFERRED_ADAPTER = ""  # force re-resolve on next call


def _get_adapter_addr() -> str:
    """Get cached preferred adapter address."""
    global _PREFERRED_ADAPTER
    if _ADAPTER_OVERRIDE:
        return _ADAPTER_OVERRIDE
    if not _PREFERRED_ADAPTER:
        _PREFERRED_ADAPTER = _find_preferred_adapter()
    return _PREFERRED_ADAPTER


def _run_btctl(args: list[str], timeout: float = 10.0) -> tuple[int, str, str]:
    """Run a bluetoothctl command, selecting the preferred adapter first.

    When multiple BT adapters are present, pipes 'select <addr>' before the
    actual command via stdin to ensure we always target the right adapter.
    """
    adapter = _get_adapter_addr()
    cmd_str = "bluetoothctl " + " ".join(args)
    if adapter:
        cmd_str = f"bluetoothctl (adapter={adapter}) " + " ".join(args)
    log.debug("btctl >>> %s", cmd_str)
    try:
        # Use stdin to select adapter then run command in interactive mode
        if adapter and args and args[0] != "list":
            stdin_cmds = f"select {adapter}\n" + " ".join(args) + "\nexit\n"
            result = subprocess.run(
                ["bluetoothctl"],
                capture_output=True, text=True, timeout=timeout,
                input=stdin_cmds,
            )
        else:
            result = subprocess.run(
                ["bluetoothctl"] + args,
                capture_output=True, text=True, timeout=timeout,
            )
        if result.stdout.strip():
            log.debug("btctl <<< rc=%d stdout=%s", result.returncode,
                      result.stdout.strip()[:200])
        if result.stderr.strip():
            log.debug("btctl <<< stderr=%s", result.stderr.strip()[:200])
        return result.returncode, result.stdout, result.stderr
    except FileNotFoundError:
        log.error("btctl: bluetoothctl not found on system")
        return -1, "", "bluetoothctl not found"
    except subprocess.TimeoutExpired:
        log.warning("btctl: command timed out after %.1fs: %s", timeout, cmd_str)
        return -2, "", "bluetoothctl timed out"


class BluetoothManager:
    """Manages Bluetooth connections for audio streaming and calls.

    Capabilities:
        - A2DP Sink: phone streams music to headunit
        - HFP: hands-free phone calls with mic/speaker routing
        - Device scanning, pairing, and connection management

    Events published:
        - bt.connected: {address: str, name: str}
        - bt.disconnected: {address: str}
        - bt.a2dp_active: bool
        - bt.hfp_active: bool (triggers audio.phone_call for ducking)
        - bt.device_list: list of paired devices
        - bt.scan_result: list of discovered devices
    """

    def __init__(self, config: Any, event_bus: EventBus):
        self._config = config
        self._event_bus = event_bus
        self._available = False
        self._connected_device: Optional[dict[str, str]] = None
        self._a2dp_active = False
        self._hfp_active = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._running = False
        self._scanning = False
        self._scan_thread: Optional[threading.Thread] = None
        self._discovered_devices: list[dict[str, str]] = []
        # Address the user explicitly disconnected from. The monitor
        # checks this before triggering auto-reconnect so a manual
        # Disconnect tap doesn't immediately bring the device back.
        # Cleared on connect() and on remove().
        self._user_disconnect_addr: Optional[str] = None

        # Force internal Intel 8087 (overrides default "prefer USB dongle"
        # bias) — paired with the hci watchdog that bounces the adapter
        # on tx-timeout.
        try:
            prefer_internal = bool(config.get("bluetooth.prefer_internal", False))
        except Exception:
            prefer_internal = False
        if prefer_internal:
            set_prefer_internal(True)
            log.info("BT: prefer_internal=true — using integrated Intel adapter")

        # Optional explicit adapter override from config — pin a specific
        # USB BT dongle MAC if auto-detect picks the wrong one.
        try:
            override = (config.get("bluetooth.preferred_adapter", "") or "").strip()
        except Exception:
            override = ""
        if override:
            set_adapter_override(override)
            log.info("BT: preferred adapter override = %s", override)

        self._check_availability()

        # Subscribe to call events for HFP routing
        self._event_bus.subscribe("bt.call_incoming", self._on_call_incoming)
        self._event_bus.subscribe("bt.call_ended", self._on_call_ended)

    def _check_availability(self) -> None:
        """Check if Bluetooth is available (retries up to 5 times)."""
        log.info("Checking Bluetooth availability...")
        for attempt in range(5):
            rc, out, err = _run_btctl(["show"])
            if rc == 0 and "Controller" in out:
                self._available = True
                for line in out.splitlines():
                    if line.strip().startswith("Controller"):
                        log.info("Bluetooth controller found: %s", line.strip())
                        break
                rc_pwr, out_pwr, _ = _run_btctl(["power", "on"])
                if rc_pwr == 0:
                    log.info("Bluetooth power ON")
                else:
                    log.warning("Bluetooth power on failed: %s", out_pwr)
                # Always re-assert pairable + discoverable on every start.
                # Phones look for the Pairable flag at the moment they
                # initiate the AA bootstrap and many BlueZ builds drop it
                # back to false after PairableTimeout regardless of the
                # main.conf setting.
                _run_btctl(["pairable", "on"])
                _run_btctl(["discoverable", "on"])
                _run_btctl(["discoverable-timeout", "0"])
                if not _start_pairing_agent():
                    log.warning("D-Bus pairing agent failed — falling back to bluetoothctl agent")
                    _run_btctl(["agent", "DisplayYesNo"])
                    _run_btctl(["default-agent"])
                else:
                    log.info("D-Bus pairing agent registered successfully")
                # Kick off background auto-connect to all paired+trusted
                # devices — the phone may already be in range when BCM
                # starts, and waiting for the user to tap Connect every
                # time defeats the purpose of "trusted".
                threading.Thread(
                    target=self._auto_connect_paired_on_boot,
                    daemon=True, name="bt-boot-autoconnect",
                ).start()
                return
            if attempt < 4:
                log.info("Bluetooth not ready (attempt %d/5) — retrying in 2s...", attempt + 1)
                time.sleep(2)
        self._available = False
        log.warning("Bluetooth not available after 5 attempts (last rc=%d)", rc)

    def _auto_connect_paired_on_boot(self) -> None:
        """Try to (re)connect to every paired+trusted device after boot.

        Phones that were paired before reboot expect the head unit to be
        the one that initiates the link, the same way a car carkit does.
        Rather than depend on a single ``multimedia.last_bt_device``
        config key, walk the actual paired set and connect to whichever
        one answers first. Stops as soon as one device is connected.
        """
        # Give the adapter a moment to settle after power on.
        time.sleep(2)
        if not self._available:
            return
        try:
            paired = self.get_paired_devices()
        except Exception:
            paired = []
        if not paired:
            log.info("BT auto-connect: no paired devices")
            return

        # Bias toward the configured "last" device first, then everyone
        # else. The last-known device is the most likely match.
        try:
            last_addr = self._config.get("multimedia.last_bt_device", None)
        except Exception:
            last_addr = None
        ordered = sorted(
            paired,
            key=lambda d: 0 if last_addr and d.get("address") == last_addr else 1,
        )
        log.info("BT auto-connect: trying %d paired device(s)", len(ordered))
        for dev in ordered:
            addr = dev.get("address")
            if not addr or self._connected_device:
                break
            info = self.get_device_info(addr)
            if info.get("connected"):
                log.info("BT auto-connect: %s already connected", addr)
                self._publish_connected(addr, info.get("name", addr))
                return
            # Make sure it's trusted so BlueZ accepts our outbound link.
            _run_btctl(["trust", addr])
            try:
                if self.connect(addr):
                    log.info("BT auto-connect: linked to %s on boot", addr)
                    return
            except Exception:
                log.exception("BT auto-connect to %s raised", addr)
        log.info("BT auto-connect: nothing answered on boot")

    @property
    def available(self) -> bool:
        return self._available

    @property
    def connected(self) -> bool:
        return self._connected_device is not None

    @property
    def connected_device(self) -> Optional[dict[str, str]]:
        return self._connected_device

    @property
    def a2dp_active(self) -> bool:
        return self._a2dp_active

    @property
    def hfp_active(self) -> bool:
        return self._hfp_active

    @property
    def scanning(self) -> bool:
        return self._scanning

    def get_controller_info(self) -> dict[str, Any]:
        """Get BT controller info (address, name, powered, discoverable)."""
        if not self._available:
            return {
                "available": False,
                "address": "N/A",
                "name": "Simulated",
                "powered": False,
                "discoverable": False,
            }
        rc, out, _ = _run_btctl(["show"])
        if rc != 0:
            return {"available": True, "address": "?", "name": "?",
                    "powered": False, "discoverable": False}
        info: dict[str, Any] = {"available": True}
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("Controller"):
                info["address"] = line.split()[1] if len(line.split()) > 1 else "?"
            elif line.startswith("Name:"):
                info["name"] = line.split(":", 1)[1].strip()
            elif line.startswith("Powered:"):
                info["powered"] = "yes" in line.lower()
            elif line.startswith("Discoverable:"):
                info["discoverable"] = "yes" in line.lower()
        return info

    def enable_discoverable(self, timeout: int = 120) -> bool:
        """Make headunit discoverable for pairing.

        Sets the adapter as pairable and discoverable so phones can
        find it. The Android Auto profile UUID is already advertised
        via the D-Bus profile registered at startup.
        """
        if not self._available:
            log.info("BT discoverable (simulated, %ds)", timeout)
            return True

        _run_btctl(["pairable", "on"])
        _run_btctl(["discoverable", "on"])
        # Set discoverable timeout via bluetoothctl
        _run_btctl(["discoverable-timeout", str(timeout)])
        log.info("BT discoverable for %ds (AA profile active)", timeout)
        return True

    def set_powered(self, on: bool) -> bool:
        """Power the BT adapter on or off.

        Wraps `bluetoothctl power on/off` and `rfkill`. On baremetal
        ARM boards (and many laptops) the adapter is rfkill-soft-blocked
        until something explicitly unblocks it — `bluetoothctl power on`
        alone returns success but the radio stays dark, which is why
        the toggle "doesn't influence the modem". Always rfkill-unblock
        before powering on, and rfkill-block after powering off so the
        toggle actually mutes the radio.
        """
        if not self._available and on:
            # If we previously failed to find an adapter, give it another
            # try now that the user explicitly asked to power on — rfkill
            # may have been blocking the controller from showing up.
            try:
                subprocess.run(["rfkill", "unblock", "bluetooth"],
                               capture_output=True, timeout=3)
            except Exception:
                pass
            self._check_availability()

        action = "on" if on else "off"
        try:
            if on:
                subprocess.run(["rfkill", "unblock", "bluetooth"],
                               capture_output=True, timeout=3)
            rc, out, err = _run_btctl(["power", action])
            if rc != 0:
                log.warning("BT power %s failed: %s", action,
                            (err or out).strip())
                return False
            if not on:
                # Soft-block so the radio is actually dark — without
                # this BlueZ keeps the adapter usable internally even
                # though `Powered: no` is reported.
                subprocess.run(["rfkill", "block", "bluetooth"],
                               capture_output=True, timeout=3)
            log.info("BT power %s", action)
            return True
        except FileNotFoundError:
            log.warning("rfkill/bluetoothctl not installed — cannot toggle BT")
            return False
        except Exception:
            log.exception("BT power toggle failed")
            return False

    def disable_discoverable(self) -> None:
        """Disable discoverable mode."""
        if self._available:
            _run_btctl(["discoverable", "off"])

    def start_scan(self, duration: int = 15) -> bool:
        """Start scanning for nearby BT devices.

        Uses a long-running bluetoothctl subprocess so the discovery
        session stays alive for the full duration — `_run_btctl(["scan",
        "on"])` exits immediately and BlueZ stops the discovery as soon
        as the bluetoothctl client disconnects.
        """
        if self._scanning:
            return False

        self._scanning = True
        self._discovered_devices = []

        if not self._available:
            # Simulated scan
            self._discovered_devices = [
                {"address": "AA:BB:CC:DD:EE:01", "name": "iPhone (simulated)"},
                {"address": "AA:BB:CC:DD:EE:02", "name": "Samsung Galaxy (simulated)"},
            ]
            self._scanning = False
            self._event_bus.publish("bt.scan_result", self._discovered_devices)
            log.info("BT scan (simulated): %d devices", len(self._discovered_devices))
            return True

        adapter = _get_adapter_addr()

        def _scan_worker():
            proc = None
            try:
                # Keep bluetoothctl alive for the whole scan window so
                # BlueZ's StartDiscovery (per-client) does not get torn
                # down. We feed `select <adapter>` + `scan on`, then
                # close stdin via `exit` only AFTER `duration` seconds.
                stdin_input = ""
                if adapter:
                    stdin_input += f"select {adapter}\n"
                stdin_input += "scan on\n"
                log.debug("btctl: starting long scan (%ds)", duration)
                proc = subprocess.Popen(
                    ["bluetoothctl"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    text=True,
                )
                proc.stdin.write(stdin_input)
                proc.stdin.flush()

                # Sleep in 1s chunks so stop_scan() can interrupt.
                for _ in range(duration):
                    if not self._scanning:
                        break
                    time.sleep(1)

                # Stop discovery cleanly.
                try:
                    proc.stdin.write("scan off\nexit\n")
                    proc.stdin.flush()
                    proc.stdin.close()
                except (BrokenPipeError, OSError):
                    pass
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2)

                # Now query the device list (separate short-lived call).
                rc, out, _ = _run_btctl(["devices"])
                if rc == 0:
                    paired = {d["address"] for d in self.get_paired_devices()}
                    for line in out.strip().splitlines():
                        parts = line.strip().split(None, 2)
                        if len(parts) >= 3 and parts[0] == "Device":
                            addr = parts[1]
                            name = parts[2]
                            if addr not in paired:
                                self._discovered_devices.append(
                                    {"address": addr, "name": name}
                                )
                self._event_bus.publish("bt.scan_result", self._discovered_devices)
                log.info("BT scan complete: %d new devices found",
                         len(self._discovered_devices))
            except Exception as e:
                log.error("BT scan error: %s", e)
                if proc and proc.poll() is None:
                    try:
                        proc.kill()
                    except Exception:
                        pass
            finally:
                self._scanning = False

        self._scan_thread = threading.Thread(target=_scan_worker, daemon=True)
        self._scan_thread.start()
        log.info("BT scan started (%ds)", duration)
        return True

    def stop_scan(self) -> None:
        """Stop an ongoing scan."""
        # Setting _scanning False lets the worker break out of its sleep
        # loop; the worker itself sends `scan off` to bluetoothctl.
        self._scanning = False

    @property
    def discovered_devices(self) -> list[dict[str, str]]:
        return self._discovered_devices

    def get_paired_devices(self) -> list[dict[str, str]]:
        """List paired Bluetooth devices."""
        if not self._available:
            return [
                {"address": "AA:BB:CC:DD:EE:01", "name": "iPhone (simulated)"},
                {"address": "AA:BB:CC:DD:EE:02", "name": "Samsung Galaxy (simulated)"},
            ]

        # BlueZ 5.72+: "paired-devices" was removed, use "devices Paired"
        rc, out, _ = _run_btctl(["devices", "Paired"])
        if rc != 0:
            # Fallback for older BlueZ versions
            rc, out, _ = _run_btctl(["paired-devices"])
            if rc != 0:
                log.warning("Cannot list paired devices (both 'devices Paired' "
                            "and 'paired-devices' failed)")
                return []

        devices = []
        for line in out.strip().splitlines():
            parts = line.strip().split(None, 2)
            if len(parts) >= 3 and parts[0] == "Device":
                devices.append({"address": parts[1], "name": parts[2]})

        log.debug("Paired devices: %d found", len(devices))
        self._event_bus.publish("bt.device_list", devices)
        return devices

    def get_device_info(self, address: str) -> dict[str, Any]:
        """Get detailed info about a specific device."""
        if not self._available:
            return {"address": address, "name": "Simulated", "connected": False,
                    "paired": False, "trusted": False}
        rc, out, _ = _run_btctl(["info", address])
        if rc != 0:
            return {"address": address, "error": "not found"}
        info: dict[str, Any] = {"address": address}
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("Name:"):
                info["name"] = line.split(":", 1)[1].strip()
            elif line.startswith("Connected:"):
                info["connected"] = "yes" in line.lower()
            elif line.startswith("Paired:"):
                info["paired"] = "yes" in line.lower()
            elif line.startswith("Trusted:"):
                info["trusted"] = "yes" in line.lower()
        return info

    def pair(self, address: str) -> bool:
        """Pair with a device.

        On success, trust + automatically connect — phones expect the
        head unit to come up immediately after the passkey is accepted,
        and asking the user to tap Connect again is friction we don't
        need. Falls through to the verify-then-trust connect path so
        a flaky link still surfaces honestly.
        """
        log.info("BT pair requested: %s", address)
        if not self._available:
            log.info("BT pair (simulated): %s", address)
            return True

        # DO NOT trust before pairing — trust defeats PIN confirmation
        rc, out, err = _run_btctl(["pair", address], timeout=30.0)
        combined = (out + err).lower()
        if rc == 0 or "already" in combined:
            _run_btctl(["trust", address])
            log.info("BT paired + trusted: %s", address)
            # Clear any stale user-disconnect so the auto-connect (and
            # the monitor's auto-reconnect) can actually run for this
            # address.
            if self._user_disconnect_addr == address:
                self._user_disconnect_addr = None
            # Run the verify-then-trust connect in a background thread
            # so the HTTP /bt/pair request returns as soon as pairing
            # itself succeeds. Without this, the request blocks for the
            # full pair (≤30s) + connect verify (≤10s) and risks browser
            # timeouts. The settings UI polls /bt/devices afterwards
            # and will surface the connected state when it lands.
            def _post_pair_connect():
                try:
                    if self.connect(address):
                        log.info("BT auto-connect after pair succeeded: %s",
                                 address)
                    else:
                        log.warning("BT paired but auto-connect did not "
                                    "verify: %s", address)
                except Exception:
                    log.exception("BT auto-connect after pair raised")

            threading.Thread(
                target=_post_pair_connect, daemon=True,
                name=f"bt-postpair-{address[-5:]}",
            ).start()
            return True
        if "org.bluez.error" in combined:
            log.error("BT pair failed (BlueZ error): %s — %s", address,
                      (out + err).strip()[:200])
        else:
            log.error("BT pair failed: rc=%d out=%s err=%s", rc,
                      out.strip()[:100], err.strip()[:100])
        return False

    def trust(self, address: str) -> bool:
        """Trust a device (auto-reconnect)."""
        if not self._available:
            return True
        rc, _, err = _run_btctl(["trust", address])
        if rc == 0:
            log.info("BT trusted: %s", address)
            return True
        log.error("BT trust failed: %s", err)
        return False

    def remove(self, address: str) -> bool:
        """Remove (unpair) a device."""
        if not self._available:
            log.info("BT remove (simulated): %s", address)
            return True

        # Disconnect first if connected
        if self._connected_device and self._connected_device["address"] == address:
            self.disconnect()

        _run_btctl(["untrust", address])
        rc, _, err = _run_btctl(["remove", address])
        if rc == 0:
            log.info("BT removed + untrusted: %s", address)
            return True
        log.error("BT remove failed: %s", err)
        return False

    def get_connected_devices(self) -> list[dict[str, Any]]:
        """Get all currently connected Bluetooth devices with detailed status."""
        connected = []
        if not self._available:
            if self._connected_device:
                connected.append({
                    **self._connected_device,
                    "connected": True,
                    "a2dp": self._a2dp_active,
                    "hfp": self._hfp_active,
                })
            return connected

        # BlueZ 5.72+: "devices Connected" lists only connected devices
        rc, out, _ = _run_btctl(["devices", "Connected"])
        if rc == 0 and out.strip():
            for line in out.strip().splitlines():
                parts = line.strip().split(None, 2)
                if len(parts) >= 3 and parts[0] == "Device":
                    addr = parts[1]
                    name = parts[2]
                    is_tracked = (self._connected_device
                                  and self._connected_device["address"] == addr)
                    connected.append({
                        "address": addr,
                        "name": name,
                        "connected": True,
                        "a2dp": self._a2dp_active and is_tracked,
                        "hfp": self._hfp_active and is_tracked,
                    })
                    # Sync internal state if device is connected but we
                    # didn't track it (e.g. phone auto-connected)
                    if not self._connected_device:
                        log.info("BT device %s (%s) connected externally — "
                                 "syncing internal state", addr, name)
                        self._connected_device = {"address": addr, "name": name}
                        self._a2dp_active = True
                        self._event_bus.publish("bt.connected",
                                                self._connected_device)
                        self._event_bus.publish("bt.a2dp_active", True)
                        self._event_bus.publish("audio.source_available", {
                            "source": "bluetooth", "available": True,
                        })

        log.debug("Connected devices: %d", len(connected))
        return connected

    def connect(self, address: str) -> bool:
        """Connect to a paired device.

        ``bluetoothctl connect`` exits rc=0 the moment it printed
        "Attempting to connect …" — long before the BlueZ link layer
        has actually finished. The previous "rc==0 → success" check
        produced a tight flap loop: optimistic success → monitor reads
        Connected:no 5 s later → disconnect → auto-reconnect → repeat.
        Verify the link with ``info`` polling before declaring success.
        """
        log.info("BT connect requested: %s", address)

        if not self._available:
            self._connected_device = {"address": address, "name": "Simulated"}
            self._a2dp_active = True
            self._event_bus.publish("bt.connected", self._connected_device)
            self._event_bus.publish("bt.a2dp_active", True)
            self._event_bus.publish("audio.source_available", {
                "source": "bluetooth", "available": True,
            })
            log.info("BT connected (simulated): %s", address)
            return True

        # Check if device is paired first
        info = self.get_device_info(address)
        if info.get("error"):
            log.error("BT connect: device %s not found — pair it first", address)
            return False

        if info.get("connected"):
            log.info("BT connect: device %s already connected", address)
            name = info.get("name", address)
            self._publish_connected(address, name)
            return True

        # Ensure device is trusted before connecting (needed for reconnection)
        log.debug("BT connect: trusting %s before connect", address)
        _run_btctl(["trust", address])

        max_attempts = 2
        verify_budget_seconds = 10.0
        verify_step = 0.5

        for attempt in range(1, max_attempts + 1):
            log.info("BT connect attempt %d/%d to %s",
                     attempt, max_attempts, address)
            rc, out, err = _run_btctl(["connect", address], timeout=15.0)
            combined = (out + err).lower()

            # Hard-fail conditions surface in bluetoothctl's stdout/stderr
            # even when rc=0; bail early so we don't burn the verify budget.
            if "not available" in combined:
                log.error("BT connect: device %s not available (out of range?)",
                          address)
                return False
            if "does not exist" in combined:
                log.error("BT connect: device %s does not exist — needs pairing",
                          address)
                return False

            # Verify the connection actually came up. ``info`` is the
            # source of truth because BlueZ updates the Connected
            # property when the link layer settles.
            deadline = time.time() + verify_budget_seconds
            while time.time() < deadline:
                v = self.get_device_info(address)
                if v.get("connected"):
                    name = v.get("name", address)
                    self._publish_connected(address, name)
                    log.info("BT connected: %s (%s) on attempt %d",
                             address, name, attempt)
                    return True
                time.sleep(verify_step)

            log.warning("BT connect attempt %d not verified within %.1fs "
                        "(rc=%d out=%s err=%s)", attempt, verify_budget_seconds,
                        rc, out.strip()[:100], err.strip()[:100])
            if attempt < max_attempts:
                time.sleep(2)

        log.error("BT connect failed after %d attempts: %s",
                  max_attempts, address)
        return False

    def _publish_connected(self, address: str, name: str) -> None:
        """Common state-update path when a verified connect lands."""
        self._connected_device = {"address": address, "name": name}
        self._a2dp_active = True
        self._user_disconnect_addr = None
        self._event_bus.publish("bt.connected", self._connected_device)
        self._event_bus.publish("bt.a2dp_active", True)
        self._event_bus.publish("audio.source_available", {
            "source": "bluetooth", "available": True,
        })
        # Remember this address so the next cold boot can bias auto-
        # connect toward the phone that was actually being used. Best-
        # effort — failure here is harmless because we already iterate
        # the full paired set on boot.
        try:
            self._config.set("multimedia.last_bt_device", address)
            self._config.save()
        except Exception:
            log.debug("Could not persist last_bt_device (non-critical)")

    def disconnect(self) -> None:
        """Disconnect current device (user-initiated).

        Marks the address so the monitor's auto-reconnect logic skips
        it — the user just hit Disconnect, they don't want it to come
        back 5 s later.
        """
        if self._connected_device:
            addr = self._connected_device["address"]
            name = self._connected_device.get("name", "?")
            log.info("BT disconnect requested: %s (%s)", addr, name)
            self._user_disconnect_addr = addr
            if self._available:
                rc, out, err = _run_btctl(["disconnect", addr])
                if rc != 0:
                    log.warning("BT disconnect command failed: rc=%d %s",
                                rc, (out + err).strip()[:100])

            self._a2dp_active = False
            self._hfp_active = False
            self._event_bus.publish("bt.disconnected", {"address": addr})
            self._event_bus.publish("bt.a2dp_active", False)
            self._event_bus.publish("audio.source_available", {
                "source": "bluetooth", "available": False,
            })
            log.info("BT disconnected: %s (%s)", addr, name)
            self._connected_device = None
        else:
            log.debug("BT disconnect: no device connected")

    def start_monitor(self) -> None:
        """Start monitoring BT connection status and AVRCP media metadata."""
        if self._running:
            return
        self._running = True
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop, daemon=True
        )
        self._monitor_thread.start()
        # Start AVRCP media metadata monitor (D-Bus)
        self._start_media_monitor()
        # Register HFP call command handlers
        self._init_hfp_commands()
        # Watchdog for the documented Intel 8087 tx-timeout — only
        # engaged when the user has asked for the internal adapter.
        if _PREFER_INTERNAL:
            threading.Thread(
                target=self._hci_watchdog, daemon=True, name="bt-hci-watchdog",
            ).start()

    def _hci_watchdog(self) -> None:
        """Recover from Intel 8087 tx-timeout by bouncing the hci device.

        Only runs when ``bluetooth.prefer_internal`` is set. dmesg shows
        ``command 0x… tx timeout`` followed by ``Resetting usb device.``
        after which BlueZ stops reporting the controller. ``hciconfig
        hciX down/up`` restores it without a kernel-level USB reset.
        """
        miss = 0
        while self._running:
            time.sleep(15)
            if not self._available:
                continue
            rc, out, _ = _run_btctl(["show"])
            if rc == 0 and "Controller" in out:
                miss = 0
                continue
            miss += 1
            if miss < 2:
                continue
            # Two consecutive misses → controller gone. Find the hci by
            # the adapter address we resolved and bounce it.
            addr = _get_adapter_addr()
            hci = None
            try:
                hc = subprocess.run(
                    ["hciconfig"], capture_output=True, text=True, timeout=3,
                )
                current = None
                for line in hc.stdout.splitlines():
                    if line and not line[0].isspace() and ":" in line:
                        current = line.split(":")[0].strip()
                    if current and addr and addr in line:
                        hci = current
                        break
            except Exception:
                pass
            if not hci:
                hci = "hci0"
            log.warning("BT hci watchdog: controller missing — bouncing %s", hci)
            for cmd in (["rfkill", "unblock", "bluetooth"],
                        ["hciconfig", hci, "down"],
                        ["hciconfig", hci, "up"]):
                try:
                    subprocess.run(cmd, capture_output=True, timeout=4)
                except Exception:
                    pass
            time.sleep(2)
            self._check_availability()
            miss = 0

    def stop_monitor(self) -> None:
        """Stop the connection monitor."""
        self._running = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=2.0)

    def _monitor_loop(self) -> None:
        """Periodically check BT connection status and handle reconnection.

        A single ``Connected: no`` read is treated as a transient — BlueZ
        will momentarily report a stale state during AVRCP renegotiation,
        codec switches, or while the daemon is busy. We require two
        consecutive negative reads (with a short gap) before declaring
        an unexpected disconnect. This mirrors the verify-then-trust
        connect path so a single timing blip can't tear down a working
        link and trigger the auto-reconnect cascade.
        """
        _reconnect_attempts = 0
        _max_reconnect = 3
        _last_device_addr: Optional[str] = None
        _disconnect_strikes = 0
        _strike_threshold = 2
        # When fully idle (no connected device, no pending reconnect)
        # poll the paired-but-disconnected set every N ticks so a phone
        # that comes into range mid-drive gets picked up automatically.
        _idle_sweep_every = 12   # × 2.5s sleep below = ~30s
        _idle_ticks = 0

        while self._running:
            if self._available and self._connected_device:
                addr = self._connected_device["address"]
                rc, out, _ = _run_btctl(["info", addr])
                disconnected = (rc == 0 and "Connected: no" in out)
                if disconnected:
                    _disconnect_strikes += 1
                    if _disconnect_strikes >= _strike_threshold:
                        log.warning("BT device %s disconnected unexpectedly "
                                    "(%d strikes)", addr, _disconnect_strikes)
                        _last_device_addr = addr
                        _reconnect_attempts = 0
                        _disconnect_strikes = 0
                        # Drop internal state without calling disconnect()
                        # — the link is already gone, an extra
                        # bluetoothctl disconnect just generates noise.
                        self._a2dp_active = False
                        self._hfp_active = False
                        self._connected_device = None
                        self._event_bus.publish(
                            "bt.disconnected", {"address": addr},
                        )
                        self._event_bus.publish("bt.a2dp_active", False)
                        self._event_bus.publish("audio.source_available", {
                            "source": "bluetooth", "available": False,
                        })
                    else:
                        log.debug("BT %s transient Connected:no (strike %d)",
                                  addr, _disconnect_strikes)
                else:
                    if _disconnect_strikes:
                        log.debug("BT %s transient cleared", addr)
                    _reconnect_attempts = 0
                    _last_device_addr = None
                    _disconnect_strikes = 0

            elif (self._available and not self._connected_device
                  and _last_device_addr and _reconnect_attempts < _max_reconnect
                  and not self._user_disconnect_addr):
                # Try to reconnect to the last device. Skipped if the
                # user explicitly hit Disconnect for this address —
                # auto-reconnecting after a manual disconnect feels
                # like a bug to users.
                _reconnect_attempts += 1
                log.info("BT auto-reconnect attempt %d/%d to %s",
                         _reconnect_attempts, _max_reconnect, _last_device_addr)
                if self.connect(_last_device_addr):
                    log.info("BT auto-reconnect succeeded to %s",
                             _last_device_addr)
                    _last_device_addr = None
                    _reconnect_attempts = 0
                else:
                    log.warning("BT auto-reconnect failed (%d/%d)",
                                _reconnect_attempts, _max_reconnect)
                    if _reconnect_attempts >= _max_reconnect:
                        log.info("BT auto-reconnect exhausted — giving up "
                                 "for %s", _last_device_addr)
                        _last_device_addr = None

            elif (self._available and not self._connected_device
                  and not _last_device_addr):
                # Idle — periodically sweep the paired set so a phone
                # that powers on (or wakes from doze) inside range
                # auto-links without the user touching anything.
                _idle_ticks += 1
                if _idle_ticks >= _idle_sweep_every:
                    _idle_ticks = 0
                    try:
                        self._auto_connect_paired_on_boot()
                    except Exception:
                        log.exception("BT idle sweep raised")

            time.sleep(2.5)

    # --- HFP call handling via D-Bus / ofono / BlueZ ---

    def _init_hfp_commands(self) -> None:
        """Subscribe to HFP call command events from the dashboard."""
        self._event_bus.subscribe("bt.cmd.dial", self._on_cmd_dial)
        self._event_bus.subscribe("bt.cmd.answer", self._on_cmd_answer)
        self._event_bus.subscribe("bt.cmd.hangup", self._on_cmd_hangup)
        log.info("HFP call command handlers registered")

    def _on_cmd_dial(self, topic: str, value: Any, timestamp: float) -> None:
        """Initiate an outgoing call via BT HFP."""
        number = str(value).strip()
        if not number:
            return
        log.info("HFP dial request: %s", number)
        self._hfp_active = True
        self._event_bus.publish("bt.hfp_active", True)
        self._event_bus.publish("bt.call_state", "ringing")
        self._event_bus.publish("bt.call_info", {"number": number, "name": ""})
        # Try ofono D-Bus for actual call
        if HAS_DBUS:
            try:
                self._hfp_dial_dbus(number)
            except Exception as e:
                log.warning("HFP D-Bus dial failed: %s (call may still work via phone)", e)

    def _on_cmd_answer(self, topic: str, value: Any, timestamp: float) -> None:
        """Answer an incoming call via BT HFP."""
        log.info("HFP answer request")
        self._hfp_active = True
        self._event_bus.publish("bt.hfp_active", True)
        self._event_bus.publish("bt.call_state", "active")
        self._event_bus.publish("audio.phone_call", True)
        if HAS_DBUS:
            try:
                self._hfp_answer_dbus()
            except Exception as e:
                log.warning("HFP D-Bus answer failed: %s", e)

    def _on_cmd_hangup(self, topic: str, value: Any, timestamp: float) -> None:
        """Hang up or reject a call via BT HFP."""
        log.info("HFP hangup request")
        self._hfp_active = False
        self._event_bus.publish("bt.hfp_active", False)
        self._event_bus.publish("bt.call_state", "idle")
        self._event_bus.publish("bt.call_info", {})
        self._event_bus.publish("audio.phone_call", False)
        if HAS_DBUS:
            try:
                self._hfp_hangup_dbus()
            except Exception as e:
                log.warning("HFP D-Bus hangup failed: %s", e)

    def _hfp_dial_dbus(self, number: str) -> None:
        """Dial via ofono VoiceCallManager or direct AT command."""
        import dbus
        bus = dbus.SystemBus()
        # Try ofono first (standard HFP interface)
        try:
            manager = bus.get_object("org.ofono", "/")
            modems = dbus.Interface(manager, "org.ofono.Manager").GetModems()
            for path, props in modems:
                if "org.ofono.VoiceCallManager" in props.get("Interfaces", []):
                    vcm = dbus.Interface(
                        bus.get_object("org.ofono", path),
                        "org.ofono.VoiceCallManager"
                    )
                    vcm.Dial(number, "")
                    log.info("HFP dial via ofono: %s", number)
                    return
        except dbus.DBusException:
            pass
        log.debug("ofono not available for dial — phone app handles the call")

    def _hfp_answer_dbus(self) -> None:
        """Answer via ofono VoiceCall."""
        import dbus
        bus = dbus.SystemBus()
        try:
            manager = bus.get_object("org.ofono", "/")
            modems = dbus.Interface(manager, "org.ofono.Manager").GetModems()
            for path, props in modems:
                if "org.ofono.VoiceCallManager" in props.get("Interfaces", []):
                    vcm_obj = bus.get_object("org.ofono", path)
                    calls = dbus.Interface(vcm_obj, "org.ofono.VoiceCallManager").GetCalls()
                    for call_path, call_props in calls:
                        if call_props.get("State") == "incoming":
                            call_iface = dbus.Interface(
                                bus.get_object("org.ofono", call_path),
                                "org.ofono.VoiceCall"
                            )
                            call_iface.Answer()
                            log.info("HFP answered via ofono")
                            return
        except dbus.DBusException:
            pass
        log.debug("ofono not available for answer")

    def _hfp_hangup_dbus(self) -> None:
        """Hangup via ofono VoiceCallManager.HangupAll()."""
        import dbus
        bus = dbus.SystemBus()
        try:
            manager = bus.get_object("org.ofono", "/")
            modems = dbus.Interface(manager, "org.ofono.Manager").GetModems()
            for path, props in modems:
                if "org.ofono.VoiceCallManager" in props.get("Interfaces", []):
                    vcm = dbus.Interface(
                        bus.get_object("org.ofono", path),
                        "org.ofono.VoiceCallManager"
                    )
                    vcm.HangupAll()
                    log.info("HFP hangup via ofono")
                    return
        except dbus.DBusException:
            pass
        log.debug("ofono not available for hangup")

    # --- AVRCP media metadata ---

    def _start_media_monitor(self) -> None:
        """Start monitoring AVRCP media metadata via D-Bus.

        Watches org.bluez.MediaPlayer1 properties for track info and
        playback status changes. Publishes:

          * ``bt.media.track`` (full dict for renderer.py)
          * ``bt.media_title`` / ``bt.media_artist`` / ``bt.media_album``
            / ``bt.media_duration`` / ``bt.media_playing`` / ``bt.media_position``
            (flat keys read by web_viewer.py — without these the A1
            now-playing card never receives anything)

        Also seeds the topics from any MediaPlayer1 that already exists
        when the monitor starts. ``PropertiesChanged`` only fires on
        deltas, so a phone that's already streaming when BCM connects
        would otherwise leave the card empty until the next track.
        """
        if not HAS_DBUS:
            log.debug("D-Bus not available — AVRCP media monitor disabled")
            return

        def _publish_track(track_info: dict) -> None:
            self._media_track = track_info
            self._event_bus.publish("bt.media.track", track_info)
            self._event_bus.publish("bt.media_title", track_info.get("title", ""))
            self._event_bus.publish("bt.media_artist", track_info.get("artist", ""))
            self._event_bus.publish("bt.media_album", track_info.get("album", ""))
            self._event_bus.publish("bt.media_duration",
                                    track_info.get("duration", 0))

        def _publish_status(status: str) -> None:
            self._media_status = status
            self._event_bus.publish("bt.media.status", status)
            self._event_bus.publish("bt.media_playing", status == "playing")

        def _publish_position(position: int) -> None:
            self._media_position = position
            self._event_bus.publish("bt.media.position", position)
            self._event_bus.publish("bt.media_position", position)

        def _track_dict_from_props(track) -> dict:
            return {
                "title": str(track.get("Title", "")),
                "artist": str(track.get("Artist", "")),
                "album": str(track.get("Album", "")),
                "duration": int(track.get("Duration", 0)),
                "track_number": int(track.get("TrackNumber", 0)),
            }

        def _seed_from_existing(bus) -> None:
            """Read existing MediaPlayer1 objects so the card fills on connect."""
            try:
                om = dbus.Interface(
                    bus.get_object("org.bluez", "/"),
                    "org.freedesktop.DBus.ObjectManager",
                )
                objects = om.GetManagedObjects()
            except Exception:
                return
            for _path, ifaces in objects.items():
                mp = ifaces.get("org.bluez.MediaPlayer1")
                if not mp:
                    continue
                if "Track" in mp:
                    info = _track_dict_from_props(mp["Track"])
                    _publish_track(info)
                    log.info("BT AVRCP seeded: %s - %s",
                             info["artist"], info["title"])
                if "Status" in mp:
                    _publish_status(str(mp["Status"]).lower())
                if "Position" in mp:
                    _publish_position(int(mp["Position"]))

        def _media_monitor():
            try:
                import dbus
                import dbus.mainloop.glib
                from gi.repository import GLib

                dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
                bus = dbus.SystemBus()

                def _on_properties_changed(interface, changed, invalidated,
                                           path=None):
                    if interface != "org.bluez.MediaPlayer1":
                        return

                    if "Track" in changed:
                        info = _track_dict_from_props(changed["Track"])
                        _publish_track(info)
                        log.info("BT AVRCP track: %s - %s",
                                 info["artist"], info["title"])

                    if "Status" in changed:
                        status = str(changed["Status"]).lower()
                        _publish_status(status)
                        log.debug("BT AVRCP status: %s", status)

                    if "Position" in changed:
                        _publish_position(int(changed["Position"]))

                bus.add_signal_receiver(
                    _on_properties_changed,
                    dbus_interface="org.freedesktop.DBus.Properties",
                    signal_name="PropertiesChanged",
                    path_keyword="path",
                )
                # New MediaPlayer1 objects appear via InterfacesAdded after
                # a phone connects; re-seed when that fires so we don't
                # have to wait for the next Track delta.
                def _on_interfaces_added(_path, ifaces):
                    if "org.bluez.MediaPlayer1" in ifaces:
                        try:
                            _seed_from_existing(bus)
                        except Exception:
                            pass

                bus.add_signal_receiver(
                    _on_interfaces_added,
                    dbus_interface="org.freedesktop.DBus.ObjectManager",
                    signal_name="InterfacesAdded",
                )

                _seed_from_existing(bus)
                log.info("BT AVRCP media monitor started (D-Bus)")

                loop = GLib.MainLoop()
                loop.run()
            except Exception:
                log.debug("BT AVRCP media monitor failed (non-critical)")

        self._media_track: dict = {}
        self._media_status: str = "stopped"
        self._media_position: int = 0

        t = threading.Thread(target=_media_monitor, daemon=True,
                             name="bt-avrcp-monitor")
        t.start()

    @property
    def media_track(self) -> dict:
        """Current AVRCP track metadata."""
        return getattr(self, "_media_track", {})

    @property
    def media_status(self) -> str:
        """Current AVRCP playback status (playing/paused/stopped)."""
        return getattr(self, "_media_status", "stopped")

    # --- HFP call handling ---

    def _on_call_incoming(self, topic: str, value: Any, timestamp: float) -> None:
        self._hfp_active = True
        self._event_bus.publish("bt.hfp_active", True)
        self._event_bus.publish("audio.phone_call", True)
        log.info("HFP call active")

    def _on_call_ended(self, topic: str, value: Any, timestamp: float) -> None:
        self._hfp_active = False
        self._event_bus.publish("bt.hfp_active", False)
        self._event_bus.publish("audio.phone_call", False)
        log.info("HFP call ended")


class DemoMediaGenerator:
    """Simulates BT AVRCP media track cycling for x86 demo mode.

    Publishes bt.media.track, bt.media.status, and bt.media.position
    to the event bus, cycling through a playlist of Italian/themed tracks.
    """

    DEMO_PLAYLIST = [
        {"title": "Vivere la Vita", "artist": "Alessandro", "album": "Dolce Vita", "duration": 234000},
        {"title": "Nightcall (Drive OST)", "artist": "Kavinsky", "album": "OutRun", "duration": 258000},
        {"title": "Interstellar Overdrive", "artist": "The Psychedelic Sounds", "album": "Space Rock", "duration": 312000},
        {"title": "Nessun Dorma", "artist": "Pavarotti", "album": "Turandot", "duration": 198000},
        {"title": "La Gazza Ladra", "artist": "Rossini", "album": "Overtures", "duration": 276000},
    ]

    def __init__(self, event_bus: EventBus):
        self._bus = event_bus
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._track_index = 0

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="demo-media")
        self._thread.start()
        log.info("DemoMediaGenerator started (%d tracks)", len(self.DEMO_PLAYLIST))

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)

    def _loop(self) -> None:
        # Publish initial "playing" status — flat key is what web_viewer reads
        self._bus.publish("bt.media.status", "playing")
        self._bus.publish("bt.media_playing", True)
        position = 0

        while self._running:
            track = self.DEMO_PLAYLIST[self._track_index]
            track_info = {
                "title": track["title"],
                "artist": track["artist"],
                "album": track["album"],
                "duration": track["duration"],
                "track_number": self._track_index + 1,
            }
            self._bus.publish("bt.media.track", track_info)
            self._bus.publish("bt.media_title", track_info["title"])
            self._bus.publish("bt.media_artist", track_info["artist"])
            self._bus.publish("bt.media_album", track_info["album"])
            self._bus.publish("bt.media_duration", track_info["duration"])

            # Simulate playback — advance position every second
            duration_s = track["duration"] // 1000
            position = 0
            while self._running and position < duration_s:
                self._bus.publish("bt.media.position", position * 1000)
                self._bus.publish("bt.media_position", position * 1000)
                time.sleep(1)
                position += 1

            # Move to next track
            self._track_index = (self._track_index + 1) % len(self.DEMO_PLAYLIST)
