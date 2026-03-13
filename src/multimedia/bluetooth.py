"""BlueZ Bluetooth configuration — A2DP sink + HFP for phone audio.

Manages Bluetooth pairing, A2DP audio streaming (phone → PipeWire → DAC),
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
        - Device pairing and connection management

    Events published:
        - bt.connected: {address: str, name: str}
        - bt.disconnected: {address: str}
        - bt.a2dp_active: bool
        - bt.hfp_active: bool (triggers audio.phone_call for ducking)
        - bt.device_list: list of paired devices
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

    def enable_discoverable(self, timeout: int = 60) -> bool:
        """Make headunit discoverable for pairing.

        Args:
            timeout: Discoverable duration in seconds.

        Returns:
            True if successful.
        """
        if not self._available:
            log.info("BT discoverable (simulated, %ds)", timeout)
            return True

        rc, _, err = _run_btctl(["discoverable", "on"])
        if rc == 0:
            log.info("BT discoverable for %ds", timeout)
            # Auto-disable after timeout
            threading.Timer(timeout, self.disable_discoverable).start()
            return True
        log.error("Failed to enable discoverable: %s", err)
        return False

    def disable_discoverable(self) -> None:
        """Disable discoverable mode."""
        if self._available:
            _run_btctl(["discoverable", "off"])

    def get_paired_devices(self) -> list[dict[str, str]]:
        """List paired Bluetooth devices."""
        if not self._available:
            return []

        rc, out, _ = _run_btctl(["paired-devices"])
        if rc != 0:
            return []

        devices = []
        for line in out.strip().splitlines():
            # Format: "Device XX:XX:XX:XX:XX:XX DeviceName"
            parts = line.strip().split(None, 2)
            if len(parts) >= 3 and parts[0] == "Device":
                devices.append({"address": parts[1], "name": parts[2]})

        self._event_bus.publish("bt.device_list", devices)
        return devices

    def connect(self, address: str) -> bool:
        """Connect to a paired device.

        Args:
            address: BT MAC address (XX:XX:XX:XX:XX:XX).

        Returns:
            True if connection successful.
        """
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
            self._connected_device = {"address": address, "name": address}
            self._a2dp_active = True
            self._event_bus.publish("bt.connected", self._connected_device)
            self._event_bus.publish("bt.a2dp_active", True)
            self._event_bus.publish("audio.source_available", {
                "source": "bluetooth", "available": True,
            })
            log.info("BT connected: %s", address)
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
        """Handle incoming phone call — activate HFP."""
        self._hfp_active = True
        self._event_bus.publish("bt.hfp_active", True)
        self._event_bus.publish("audio.phone_call", True)
        log.info("HFP call active")

    def _on_call_ended(self, topic: str, value: Any, timestamp: float) -> None:
        """Handle call end — deactivate HFP."""
        self._hfp_active = False
        self._event_bus.publish("bt.hfp_active", False)
        self._event_bus.publish("audio.phone_call", False)
        log.info("HFP call ended")
