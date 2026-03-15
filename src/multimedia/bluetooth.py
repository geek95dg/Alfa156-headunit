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

    NOTE: A2DP Sink and HFP profiles are NOT registered here — they are
    managed by PipeWire/WirePlumber via libspa-0.2-bluetooth. Registering
    them here would block PipeWire (BlueZ: NotPermitted) and break audio.

    The Android Auto BT service is NOT registered here — it is handled
    by autoapp's built-in btservice (Qt Bluetooth RFCOMM server) which
    properly implements the AA wireless protocol handshake. Registering
    the AA UUID here would conflict with autoapp's btservice and cause
    "Server start failed" errors.
    """
    # No custom profiles to register:
    # A2DP/HFP → PipeWire, AA → autoapp btservice
    log.debug("BT profile registration: A2DP/HFP=PipeWire, AA=autoapp")


def _configure_adapter(bus) -> None:
    """Configure BT adapter name and class for headunit discovery."""
    try:
        adapter = dbus.Interface(
            bus.get_object("org.bluez", "/org/bluez/hci0"),
            "org.freedesktop.DBus.Properties",
        )
        # Set friendly name so phones see "Alfa156 Headunit"
        adapter.Set("org.bluez.Adapter1", "Alias",
                     dbus.String("Alfa156 Headunit"))
        log.info("BT adapter alias set to 'Alfa156 Headunit'")
    except Exception:
        # Non-critical — fall back to system hostname
        log.debug("Could not set BT adapter alias (non-critical)")


def _start_pairing_agent() -> bool:
    """Register the D-Bus pairing agent and BT profiles with BlueZ.

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
        manager.RegisterAgent(AGENT_PATH, AGENT_CAPABILITY)
        manager.RequestDefaultAgent(AGENT_PATH)
        log.info("BT pairing agent active (capability=%s)", AGENT_CAPABILITY)

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


def _run_btctl(args: list[str], timeout: float = 10.0) -> tuple[int, str, str]:
    """Run a bluetoothctl command."""
    cmd_str = "bluetoothctl " + " ".join(args)
    log.debug("btctl >>> %s", cmd_str)
    try:
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

        self._check_availability()

        # Subscribe to call events for HFP routing
        self._event_bus.subscribe("bt.call_incoming", self._on_call_incoming)
        self._event_bus.subscribe("bt.call_ended", self._on_call_ended)

    def _check_availability(self) -> None:
        """Check if Bluetooth is available."""
        log.info("Checking Bluetooth availability...")
        rc, out, err = _run_btctl(["show"])
        if rc == 0 and "Controller" in out:
            self._available = True
            # Parse controller address for logging
            for line in out.splitlines():
                if line.strip().startswith("Controller"):
                    log.info("Bluetooth controller found: %s", line.strip())
                    break
            rc_pwr, out_pwr, _ = _run_btctl(["power", "on"])
            if rc_pwr == 0:
                log.info("Bluetooth power ON")
            else:
                log.warning("Bluetooth power on failed: %s", out_pwr)
            # Register D-Bus pairing agent (handles phone-initiated pairing)
            if not _start_pairing_agent():
                log.warning("D-Bus pairing agent failed — falling back to bluetoothctl agent")
                # Fallback to bluetoothctl agent (limited — phone-initiated may fail)
                _run_btctl(["agent", "DisplayYesNo"])
                _run_btctl(["default-agent"])
            else:
                log.info("D-Bus pairing agent registered successfully")
        else:
            self._available = False
            log.warning("Bluetooth not available (rc=%d, err=%s) — will be simulated",
                        rc, err.strip() if err else "none")

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

    def disable_discoverable(self) -> None:
        """Disable discoverable mode."""
        if self._available:
            _run_btctl(["discoverable", "off"])

    def start_scan(self, duration: int = 15) -> bool:
        """Start scanning for nearby BT devices."""
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

        def _scan_worker():
            try:
                _run_btctl(["scan", "on"])
                time.sleep(duration)
                _run_btctl(["scan", "off"])

                # Get discovered devices
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
            finally:
                self._scanning = False

        self._scan_thread = threading.Thread(target=_scan_worker, daemon=True)
        self._scan_thread.start()
        log.info("BT scan started (%ds)", duration)
        return True

    def stop_scan(self) -> None:
        """Stop an ongoing scan."""
        if self._available:
            _run_btctl(["scan", "off"])
        self._scanning = False

    @property
    def discovered_devices(self) -> list[dict[str, str]]:
        return self._discovered_devices

    def get_paired_devices(self) -> list[dict[str, str]]:
        """List paired Bluetooth devices."""
        if not self._available:
            return []

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
        """Pair with a device."""
        log.info("BT pair requested: %s", address)
        if not self._available:
            log.info("BT pair (simulated): %s", address)
            return True

        # Trust first to auto-accept
        log.debug("BT pair: trusting %s before pairing", address)
        _run_btctl(["trust", address])
        rc, out, err = _run_btctl(["pair", address], timeout=30.0)
        combined = (out + err).lower()
        if rc == 0 or "already" in combined:
            log.info("BT paired successfully: %s", address)
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

        rc, _, err = _run_btctl(["remove", address])
        if rc == 0:
            log.info("BT removed: %s", address)
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
        """Connect to a paired device."""
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
            self._connected_device = {"address": address, "name": name}
            self._a2dp_active = True
            self._event_bus.publish("bt.connected", self._connected_device)
            self._event_bus.publish("bt.a2dp_active", True)
            self._event_bus.publish("audio.source_available", {
                "source": "bluetooth", "available": True,
            })
            return True

        # Ensure device is trusted before connecting (needed for reconnection)
        log.debug("BT connect: trusting %s before connect", address)
        _run_btctl(["trust", address])

        # Try to connect with retries
        max_attempts = 2
        for attempt in range(1, max_attempts + 1):
            log.info("BT connect attempt %d/%d to %s", attempt, max_attempts, address)
            rc, out, err = _run_btctl(["connect", address], timeout=15.0)
            combined = (out + err).lower()

            if rc == 0 or "successful" in combined or "connection successful" in combined:
                # Resolve name
                info = self.get_device_info(address)
                name = info.get("name", address)
                self._connected_device = {"address": address, "name": name}
                self._a2dp_active = True
                self._event_bus.publish("bt.connected", self._connected_device)
                self._event_bus.publish("bt.a2dp_active", True)
                self._event_bus.publish("audio.source_available", {
                    "source": "bluetooth", "available": True,
                })
                log.info("BT connected: %s (%s) on attempt %d", address, name, attempt)
                return True

            # Check for specific error conditions
            if "not available" in combined:
                log.error("BT connect: device %s not available (out of range?)", address)
                return False
            if "does not exist" in combined:
                log.error("BT connect: device %s does not exist — needs pairing", address)
                return False

            log.warning("BT connect attempt %d failed: rc=%d out=%s err=%s",
                        attempt, rc, out.strip()[:100], err.strip()[:100])
            if attempt < max_attempts:
                time.sleep(2)

        log.error("BT connect failed after %d attempts: %s", max_attempts, address)
        return False

    def disconnect(self) -> None:
        """Disconnect current device."""
        if self._connected_device:
            addr = self._connected_device["address"]
            name = self._connected_device.get("name", "?")
            log.info("BT disconnect requested: %s (%s)", addr, name)
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
        """Start monitoring BT connection status."""
        if self._running:
            return
        self._running = True
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop, daemon=True
        )
        self._monitor_thread.start()

    def stop_monitor(self) -> None:
        """Stop the connection monitor."""
        self._running = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=2.0)

    def _monitor_loop(self) -> None:
        """Periodically check BT connection status and handle reconnection."""
        _reconnect_attempts = 0
        _max_reconnect = 3
        _last_device_addr: Optional[str] = None

        while self._running:
            if self._available and self._connected_device:
                addr = self._connected_device["address"]
                rc, out, _ = _run_btctl(["info", addr])
                if rc == 0 and "Connected: no" in out:
                    log.warning("BT device %s disconnected unexpectedly", addr)
                    _last_device_addr = addr
                    _reconnect_attempts = 0
                    self.disconnect()
                else:
                    # Still connected — reset reconnect state
                    _reconnect_attempts = 0
                    _last_device_addr = None

            elif (self._available and not self._connected_device
                  and _last_device_addr and _reconnect_attempts < _max_reconnect):
                # Try to reconnect to the last device
                _reconnect_attempts += 1
                log.info("BT auto-reconnect attempt %d/%d to %s",
                         _reconnect_attempts, _max_reconnect, _last_device_addr)
                if self.connect(_last_device_addr):
                    log.info("BT auto-reconnect succeeded to %s", _last_device_addr)
                    _last_device_addr = None
                    _reconnect_attempts = 0
                else:
                    log.warning("BT auto-reconnect failed (%d/%d)",
                                _reconnect_attempts, _max_reconnect)
                    if _reconnect_attempts >= _max_reconnect:
                        log.info("BT auto-reconnect exhausted — giving up for %s",
                                 _last_device_addr)
                        _last_device_addr = None

            time.sleep(5)

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
