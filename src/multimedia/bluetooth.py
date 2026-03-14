"""BlueZ Bluetooth configuration — A2DP sink + HFP for phone audio.

Manages Bluetooth pairing, A2DP audio streaming (phone -> PipeWire -> DAC),
and HFP hands-free calling with mic + speaker routing.

Uses bluetoothctl CLI for device management. On x86, works with built-in
or USB Bluetooth adapter. On OPi, uses onboard or USB BT.
"""

import subprocess
import threading
import time
from typing import Any, Optional

from src.core.event_bus import EventBus
from src.core.logger import get_logger

log = get_logger("multimedia.bluetooth")


def _run_btctl(args: list[str], timeout: float = 10.0) -> tuple[int, str, str]:
    """Run a bluetoothctl command."""
    try:
        result = subprocess.run(
            ["bluetoothctl"] + args,
            capture_output=True, text=True, timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr
    except FileNotFoundError:
        return -1, "", "bluetoothctl not found"
    except subprocess.TimeoutExpired:
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
        rc, out, _ = _run_btctl(["show"])
        if rc == 0 and "Controller" in out:
            self._available = True
            log.info("Bluetooth available")
            # Ensure agent is set up and adapter is powered
            _run_btctl(["agent", "NoInputNoOutput"])
            _run_btctl(["default-agent"])
            _run_btctl(["power", "on"])
        else:
            self._available = False
            log.warning("Bluetooth not available — will be simulated")

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
        """Make headunit discoverable for pairing."""
        if not self._available:
            log.info("BT discoverable (simulated, %ds)", timeout)
            return True

        _run_btctl(["pairable", "on"])
        rc, _, err = _run_btctl(["discoverable", "on"])
        if rc == 0:
            log.info("BT discoverable for %ds", timeout)
            threading.Timer(timeout, self.disable_discoverable).start()
            return True
        log.error("Failed to enable discoverable: %s", err)
        return False

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

        rc, out, _ = _run_btctl(["paired-devices"])
        if rc != 0:
            return []

        devices = []
        for line in out.strip().splitlines():
            parts = line.strip().split(None, 2)
            if len(parts) >= 3 and parts[0] == "Device":
                devices.append({"address": parts[1], "name": parts[2]})

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
        if not self._available:
            log.info("BT pair (simulated): %s", address)
            return True

        # Trust first to auto-accept
        _run_btctl(["trust", address])
        rc, out, err = _run_btctl(["pair", address], timeout=30.0)
        if rc == 0 or "already" in (out + err).lower():
            log.info("BT paired: %s", address)
            return True
        log.error("BT pair failed: %s %s", out, err)
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

    def connect(self, address: str) -> bool:
        """Connect to a paired device."""
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

        rc, _, err = _run_btctl(["connect", address])
        if rc == 0:
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
            log.info("BT connected: %s (%s)", address, name)
            return True
        log.error("BT connect failed: %s", err)
        return False

    def disconnect(self) -> None:
        """Disconnect current device."""
        if self._connected_device:
            addr = self._connected_device["address"]
            if self._available:
                _run_btctl(["disconnect", addr])

            self._a2dp_active = False
            self._hfp_active = False
            self._event_bus.publish("bt.disconnected", {"address": addr})
            self._event_bus.publish("bt.a2dp_active", False)
            self._event_bus.publish("audio.source_available", {
                "source": "bluetooth", "available": False,
            })
            log.info("BT disconnected: %s", addr)
            self._connected_device = None

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
        """Periodically check BT connection status."""
        while self._running:
            if self._available and self._connected_device:
                rc, out, _ = _run_btctl([
                    "info", self._connected_device["address"]
                ])
                if rc == 0 and "Connected: no" in out:
                    log.warning("BT device disconnected unexpectedly")
                    self.disconnect()
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
