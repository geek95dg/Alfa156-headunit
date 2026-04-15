"""LTE/Cellular connectivity module.

On OrangePi: manages USB LTE modem via NetworkManager (nmcli), monitors
signal strength via AT commands.
On x86: checks existing network connectivity (WiFi/ethernet), reports
as connected with full signal.

Publishes to event bus:
    lte.connected  — bool
    lte.signal     — int (0-5 bars)
    lte.ip         — str
"""

import logging
import subprocess
import threading
import time

log = logging.getLogger(__name__)


class LTEManager:
    """Manages LTE modem connectivity or checks existing network.

    Args:
        event_bus: EventBus instance for publishing connectivity data.
        config: BCM config dict with hardware.lte settings.
        platform: "opi" for real LTE modem, "x86" for network check.
    """

    def __init__(self, event_bus, config: dict, platform: str = "x86"):
        self._bus = event_bus
        self._config = config
        self._platform = platform
        self._running = False
        self._thread = None
        self._connected = False
        self._signal = 0
        self._ip = ""

    def start(self):
        """Start LTE monitoring in background thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="lte-monitor")
        self._thread.start()
        log.info("LTEManager started (platform=%s)", self._platform)

    def stop(self):
        """Stop LTE monitoring."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
        log.info("LTEManager stopped")

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def signal_strength(self) -> int:
        return self._signal

    def _run(self):
        """Main monitoring loop."""
        while self._running:
            try:
                if self._platform == "x86":
                    self._check_existing_network()
                else:
                    self._check_lte_modem()
            except Exception as e:
                log.warning("LTE check error: %s", e)

            self._publish()
            time.sleep(10)  # Check every 10 seconds

    def _check_existing_network(self):
        """x86: Check if we have internet via any interface."""
        try:
            # Try to reach a reliable host
            result = subprocess.run(
                ["ping", "-c", "1", "-W", "2", "8.8.8.8"],
                capture_output=True, timeout=5
            )
            self._connected = (result.returncode == 0)

            if self._connected:
                self._signal = 5  # Full signal on existing network
                # Get IP address
                try:
                    ip_result = subprocess.run(
                        ["hostname", "-I"],
                        capture_output=True, text=True, timeout=3
                    )
                    ips = ip_result.stdout.strip().split()
                    self._ip = ips[0] if ips else ""
                except Exception:
                    self._ip = "127.0.0.1"
            else:
                self._signal = 0
                self._ip = ""

        except (subprocess.TimeoutExpired, FileNotFoundError):
            self._connected = False
            self._signal = 0
            self._ip = ""

    def _check_lte_modem(self):
        """OPi: Check LTE modem via nmcli and AT commands."""
        lte_cfg = self._config.get("hardware", {}).get("lte", {})
        device = lte_cfg.get("device", "")

        # Check NetworkManager connection status
        try:
            result = subprocess.run(
                ["nmcli", "-t", "-f", "TYPE,STATE", "connection", "show", "--active"],
                capture_output=True, text=True, timeout=5
            )
            # Look for gsm/cellular connection
            for line in result.stdout.strip().split("\n"):
                if "gsm" in line.lower() and "activated" in line.lower():
                    self._connected = True
                    break
            else:
                # Try to bring up connection
                if device:
                    subprocess.run(
                        ["nmcli", "connection", "up", device],
                        capture_output=True, timeout=15
                    )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        # Check signal strength via AT commands (if serial device available)
        self._signal = self._read_signal_strength()

        # Get IP
        if self._connected:
            try:
                result = subprocess.run(
                    ["hostname", "-I"],
                    capture_output=True, text=True, timeout=3
                )
                ips = result.stdout.strip().split()
                self._ip = ips[0] if ips else ""
            except Exception:
                self._ip = ""

    def _read_signal_strength(self) -> int:
        """Read signal strength via AT+CSQ command. Returns 0-5 bars."""
        # AT+CSQ returns +CSQ: rssi,ber where rssi 0-31 (99=unknown)
        # Map: 0-5=0bars, 6-10=1bar, 11-15=2bars, 16-20=3bars, 21-25=4bars, 26-31=5bars
        try:
            lte_cfg = self._config.get("hardware", {}).get("lte", {})
            port = lte_cfg.get("at_port", "")
            if not port:
                return 3 if self._connected else 0

            import serial
            with serial.Serial(port, 115200, timeout=2) as ser:
                ser.write(b"AT+CSQ\r\n")
                time.sleep(0.5)
                response = ser.read(256).decode("ascii", errors="ignore")
                if "+CSQ:" in response:
                    csq_str = response.split("+CSQ:")[1].strip().split(",")[0]
                    rssi = int(csq_str)
                    if rssi == 99:
                        return 0
                    if rssi <= 5:
                        return 0
                    elif rssi <= 10:
                        return 1
                    elif rssi <= 15:
                        return 2
                    elif rssi <= 20:
                        return 3
                    elif rssi <= 25:
                        return 4
                    else:
                        return 5
        except Exception:
            return 3 if self._connected else 0
        return 0

    def _publish(self):
        """Publish LTE status to event bus."""
        self._bus.publish("lte.connected", self._connected)
        self._bus.publish("lte.signal", self._signal)
        self._bus.publish("lte.ip", self._ip)


def start_network(config, event_bus, hal, **kwargs):
    """Module entry point — called by main.py module registry."""
    platform = config.get("system", {}).get("platform", "x86")
    lte = LTEManager(event_bus, config, platform)
    lte.start()
    return lte
