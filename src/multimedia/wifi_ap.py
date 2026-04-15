"""WiFi Access Point manager for Android Auto wireless data link.

After BT pairing, the phone needs a WiFi connection to the headunit for
the AA TCP data stream (port 5000). This module creates a WiFi hotspot
on the designated WiFi interface.

Strategy:
  1. Try NetworkManager (nmcli device wifi hotspot) — works on Ubuntu/VMs
  2. Fall back to hostapd + dnsmasq — for minimal systems / OPi5

On x86 VM: uses a USB WiFi dongle passed through to the VM.
On OPi5: uses the onboard or dedicated WiFi card.
"""

import os
import signal
import subprocess
import threading
import time
from typing import Any, Optional

from src.core.event_bus import EventBus
from src.core.logger import get_logger

log = get_logger("multimedia.wifi_ap")

# Runtime directory for hostapd/dnsmasq config files
RUNTIME_DIR = "/tmp/bcm-wifi-ap"


def _find_wifi_interface() -> Optional[str]:
    """Auto-detect a wireless interface (wlan0, wlp*, wlx*, etc.)."""
    # Method 1: iw dev (most reliable, but may not be installed)
    try:
        result = subprocess.run(
            ["iw", "dev"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                line = line.strip()
                if line.startswith("Interface "):
                    return line.split()[1]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Method 2: check /sys/class/net for wireless indicators
    try:
        for iface in sorted(os.listdir("/sys/class/net")):
            iface_path = f"/sys/class/net/{iface}"
            # Check for wireless subdir or phy80211 subdir (both indicate WiFi)
            if (os.path.isdir(f"{iface_path}/wireless")
                    or os.path.isdir(f"{iface_path}/phy80211")):
                return iface
    except OSError:
        pass

    # Method 3: match common wireless interface name prefixes
    try:
        for iface in sorted(os.listdir("/sys/class/net")):
            if iface.startswith(("wlan", "wlp", "wlx")):
                return iface
    except OSError:
        pass

    return None


def _cmd_exists(name: str) -> bool:
    """Check if a command is available on the system."""
    try:
        result = subprocess.run(
            ["which", name], capture_output=True, timeout=3,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _netmask_to_prefix(netmask: str) -> int:
    """Convert dotted netmask to prefix length (e.g. 255.255.255.0 -> 24)."""
    parts = netmask.split(".")
    binary = "".join(f"{int(p):08b}" for p in parts)
    return binary.count("1")


def _has_networkmanager() -> bool:
    """Check if NetworkManager is running."""
    try:
        result = subprocess.run(
            ["nmcli", "general", "status"],
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


class WiFiAPManager:
    """Manages a WiFi access point for Android Auto wireless connectivity.

    Tries NetworkManager first (nmcli hotspot), falls back to
    hostapd + dnsmasq for systems without NM.
    """

    def __init__(self, config: Any, event_bus: EventBus):
        self._config = config
        self._event_bus = event_bus
        self._interface: Optional[str] = None
        self._running = False
        self._method: Optional[str] = None  # "nmcli" or "hostapd"
        self._ap_ip = config.get("wifi.ip", "10.0.0.1")
        self._netmask = config.get("wifi.netmask", "255.255.255.0")
        self._ssid = config.get("wifi.ssid", "Alfa156_AA")
        self._password = config.get("wifi.password", "alfa156headunit")
        self._nm_conn_name = "bcm-aa-hotspot"

        # hostapd/dnsmasq processes (only used in hostapd mode)
        self._hostapd_proc: Optional[subprocess.Popen] = None
        self._dnsmasq_proc: Optional[subprocess.Popen] = None

        # Subscribe to shutdown
        self._event_bus.subscribe("power.shutting_down", self._on_shutdown)

    @property
    def running(self) -> bool:
        return self._running

    @property
    def interface(self) -> Optional[str]:
        return self._interface

    @property
    def ip_address(self) -> str:
        return self._ap_ip

    def start(self) -> bool:
        """Start the WiFi access point.

        Returns:
            True if the AP started successfully.
        """
        log.info("=== WiFi AP starting (SSID=%s, IP=%s) ===",
                 self._ssid, self._ap_ip)
        if self._running:
            log.warning("WiFi AP already running")
            return True

        # Determine interface
        configured_iface = self._config.get("wifi.interface", "")
        if configured_iface:
            self._interface = configured_iface
            log.info("Using configured WiFi interface: %s", self._interface)
        else:
            self._interface = _find_wifi_interface()
            if self._interface:
                log.info("Auto-detected WiFi interface: %s", self._interface)

        if not self._interface:
            log.error("No WiFi interface found — cannot start AP. "
                      "Connect a WiFi dongle or set wifi.interface in config.")
            return False

        log.info("Using WiFi interface: %s", self._interface)

        # Try NetworkManager first (most compatible on desktop/VM Linux)
        if _has_networkmanager():
            if self._start_nmcli():
                self._method = "nmcli"
                self._running = True
                self._publish_started()
                return True
            log.warning("nmcli hotspot failed — trying hostapd fallback")

        # Fall back to hostapd + dnsmasq
        if self._start_hostapd_mode():
            self._method = "hostapd"
            self._running = True
            self._publish_started()
            return True

        log.error("All WiFi AP methods failed")
        return False

    def stop(self) -> None:
        """Stop the WiFi access point."""
        if not self._running:
            return

        self._running = False

        if self._method == "nmcli":
            self._stop_nmcli()
        elif self._method == "hostapd":
            self._stop_hostapd_mode()

        self._method = None
        self._event_bus.publish("wifi.ap_stopped", True)
        log.info("WiFi AP stopped")

    def _publish_started(self) -> None:
        self._event_bus.publish("wifi.ap_started", {
            "interface": self._interface,
            "ssid": self._ssid,
            "ip": self._ap_ip,
            "method": self._method,
        })
        log.info("WiFi AP started — SSID: %s, IP: %s, Interface: %s, Method: %s",
                 self._ssid, self._ap_ip, self._interface, self._method)

    # ------------------------------------------------------------------
    # NetworkManager method (nmcli)
    # ------------------------------------------------------------------

    def _start_nmcli(self) -> bool:
        """Create a WiFi hotspot using NetworkManager."""
        try:
            # Remove any previous BCM hotspot connection
            subprocess.run(
                ["nmcli", "connection", "delete", self._nm_conn_name],
                capture_output=True, timeout=5,
            )

            # Create the hotspot
            channel = self._config.get("wifi.channel", 6)
            result = subprocess.run(
                [
                    "nmcli", "device", "wifi", "hotspot",
                    "ifname", self._interface,
                    "con-name", self._nm_conn_name,
                    "ssid", self._ssid,
                    "band", "bg",
                    "channel", str(channel),
                    "password", self._password,
                ],
                capture_output=True, text=True, timeout=15,
            )

            if result.returncode != 0:
                log.error("nmcli hotspot failed: %s",
                          (result.stderr or result.stdout).strip())
                return False

            log.info("nmcli hotspot created: %s", result.stdout.strip())

            # Configure the static IP for the AP
            prefix_len = _netmask_to_prefix(self._netmask)
            subprocess.run(
                ["nmcli", "connection", "modify", self._nm_conn_name,
                 "ipv4.addresses", f"{self._ap_ip}/{prefix_len}",
                 "ipv4.method", "shared"],
                capture_output=True, timeout=5,
            )

            # Reactivate to apply IP changes
            subprocess.run(
                ["nmcli", "connection", "up", self._nm_conn_name],
                capture_output=True, timeout=10,
            )

            # Verify the AP is actually up
            time.sleep(1)
            if self._verify_ap_up():
                return True

            log.error("nmcli hotspot created but AP not broadcasting")
            return False

        except Exception:
            log.exception("nmcli hotspot setup failed")
            return False

    def _stop_nmcli(self) -> None:
        """Stop the NetworkManager hotspot."""
        try:
            subprocess.run(
                ["nmcli", "connection", "down", self._nm_conn_name],
                capture_output=True, timeout=5,
            )
            subprocess.run(
                ["nmcli", "connection", "delete", self._nm_conn_name],
                capture_output=True, timeout=5,
            )
        except Exception:
            log.exception("Failed to stop nmcli hotspot")

    # ------------------------------------------------------------------
    # hostapd + dnsmasq method (fallback)
    # ------------------------------------------------------------------

    def _start_hostapd_mode(self) -> bool:
        """Start AP using hostapd + dnsmasq (for systems without NM)."""
        for tool in ["hostapd", "dnsmasq"]:
            if not _cmd_exists(tool):
                log.error("%s not installed — cannot start WiFi AP. "
                          "Install: sudo apt install %s", tool, tool)
                return False

        os.makedirs(RUNTIME_DIR, exist_ok=True)

        # Kill any existing instances
        self._kill_existing()

        # Unmanage the interface from NetworkManager if present
        if _has_networkmanager():
            subprocess.run(
                ["nmcli", "device", "set", self._interface, "managed", "no"],
                capture_output=True, timeout=5,
            )
            time.sleep(0.5)

        # Configure IP on interface
        if not self._setup_interface():
            return False

        # Start hostapd
        if not self._start_hostapd():
            self._cleanup()
            return False

        # Start dnsmasq for DHCP
        if not self._start_dnsmasq():
            self._stop_hostapd()
            self._cleanup()
            return False

        return True

    def _stop_hostapd_mode(self) -> None:
        """Stop hostapd + dnsmasq and clean up."""
        self._stop_dnsmasq()
        self._stop_hostapd()
        self._cleanup()

        # Re-manage the interface in NetworkManager
        if _has_networkmanager() and self._interface:
            subprocess.run(
                ["nmcli", "device", "set", self._interface, "managed", "yes"],
                capture_output=True, timeout=5,
            )

    def _setup_interface(self) -> bool:
        """Configure the WiFi interface with a static IP."""
        iface = self._interface
        try:
            subprocess.run(["ip", "link", "set", iface, "down"],
                           capture_output=True, timeout=5)
            subprocess.run(["ip", "addr", "flush", "dev", iface],
                           capture_output=True, timeout=5)

            prefix_len = _netmask_to_prefix(self._netmask)
            result = subprocess.run(
                ["ip", "addr", "add", f"{self._ap_ip}/{prefix_len}",
                 "dev", iface],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0 and "RTNETLINK" not in result.stderr:
                log.error("Failed to assign IP to %s: %s",
                          iface, result.stderr.strip())
                return False

            subprocess.run(["ip", "link", "set", iface, "up"],
                           capture_output=True, timeout=5)
            log.info("Interface %s configured: %s/%d",
                     iface, self._ap_ip, prefix_len)
            return True
        except Exception:
            log.exception("Failed to configure interface %s", iface)
            return False

    def _start_hostapd(self) -> bool:
        """Generate hostapd config and start the daemon."""
        channel = self._config.get("wifi.channel", 6)

        config_path = os.path.join(RUNTIME_DIR, "hostapd.conf")
        config_content = (
            f"interface={self._interface}\n"
            f"driver=nl80211\n"
            f"ssid={self._ssid}\n"
            f"hw_mode=g\n"
            f"channel={channel}\n"
            f"wmm_enabled=0\n"
            f"macaddr_acl=0\n"
            f"auth_algs=1\n"
            f"ignore_broadcast_ssid=0\n"
            f"wpa=2\n"
            f"wpa_passphrase={self._password}\n"
            f"wpa_key_mgmt=WPA-PSK\n"
            f"wpa_pairwise=TKIP\n"
            f"rsn_pairwise=CCMP\n"
        )

        with open(config_path, "w") as f:
            f.write(config_content)

        try:
            self._hostapd_proc = subprocess.Popen(
                ["hostapd", config_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            # Wait and check if it started
            time.sleep(2)
            if self._hostapd_proc.poll() is not None:
                out = self._hostapd_proc.stdout.read().decode(
                    "utf-8", errors="replace") if self._hostapd_proc.stdout else ""
                log.error("hostapd failed to start: %s", out.strip())
                return False

            threading.Thread(
                target=self._read_proc_logs,
                args=(self._hostapd_proc, "hostapd"),
                daemon=True,
            ).start()

            log.info("hostapd started (PID %d)", self._hostapd_proc.pid)
            return True
        except Exception:
            log.exception("Failed to start hostapd")
            return False

    def _start_dnsmasq(self) -> bool:
        """Start dnsmasq for DHCP on the AP interface."""
        dhcp_start = self._config.get("wifi.dhcp_start", "10.0.0.10")
        dhcp_end = self._config.get("wifi.dhcp_end", "10.0.0.50")
        lease_file = os.path.join(RUNTIME_DIR, "dnsmasq.leases")
        pid_file = os.path.join(RUNTIME_DIR, "dnsmasq.pid")

        try:
            self._dnsmasq_proc = subprocess.Popen(
                [
                    "dnsmasq",
                    f"--interface={self._interface}",
                    "--bind-interfaces",
                    f"--dhcp-range={dhcp_start},{dhcp_end},{self._netmask},24h",
                    "--no-daemon",
                    "--no-resolv",
                    "--no-hosts",
                    f"--dhcp-leasefile={lease_file}",
                    f"--pid-file={pid_file}",
                    "--log-queries",
                    "--log-dhcp",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )

            time.sleep(0.5)
            if self._dnsmasq_proc.poll() is not None:
                out = self._dnsmasq_proc.stdout.read().decode(
                    "utf-8", errors="replace") if self._dnsmasq_proc.stdout else ""
                log.error("dnsmasq failed to start: %s", out.strip())
                return False

            threading.Thread(
                target=self._read_proc_logs,
                args=(self._dnsmasq_proc, "dnsmasq"),
                daemon=True,
            ).start()

            log.info("dnsmasq started (PID %d) — DHCP range %s-%s",
                     self._dnsmasq_proc.pid, dhcp_start, dhcp_end)
            return True
        except Exception:
            log.exception("Failed to start dnsmasq")
            return False

    def _stop_hostapd(self) -> None:
        if self._hostapd_proc and self._hostapd_proc.poll() is None:
            self._hostapd_proc.send_signal(signal.SIGTERM)
            try:
                self._hostapd_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._hostapd_proc.kill()
            log.info("hostapd stopped")
        self._hostapd_proc = None

    def _stop_dnsmasq(self) -> None:
        if self._dnsmasq_proc and self._dnsmasq_proc.poll() is None:
            self._dnsmasq_proc.send_signal(signal.SIGTERM)
            try:
                self._dnsmasq_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._dnsmasq_proc.kill()
            log.info("dnsmasq stopped")
        self._dnsmasq_proc = None

    def _kill_existing(self) -> None:
        """Kill any existing hostapd/dnsmasq using our config."""
        for name in ["hostapd", "dnsmasq"]:
            try:
                subprocess.run(
                    ["pkill", "-f", f"{name}.*{RUNTIME_DIR}"],
                    capture_output=True, timeout=3,
                )
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass

    def _cleanup(self) -> None:
        """Clean up runtime files."""
        for fname in ["hostapd.conf", "dnsmasq.leases", "dnsmasq.pid"]:
            path = os.path.join(RUNTIME_DIR, fname)
            try:
                os.remove(path)
            except OSError:
                pass

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _verify_ap_up(self) -> bool:
        """Check if the WiFi interface is in AP mode and has our IP."""
        try:
            result = subprocess.run(
                ["iw", "dev", self._interface, "info"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and "type AP" in result.stdout:
                log.info("Interface %s confirmed in AP mode", self._interface)
                return True

            # Also accept if NM says it's connected in hotspot mode
            result = subprocess.run(
                ["nmcli", "-t", "-f", "GENERAL.STATE", "device", "show",
                 self._interface],
                capture_output=True, text=True, timeout=5,
            )
            if "connected" in result.stdout.lower():
                log.info("Interface %s connected via NM", self._interface)
                return True

        except Exception:
            pass
        return False

    def _read_proc_logs(self, proc: subprocess.Popen, name: str) -> None:
        """Forward subprocess output to logger."""
        if not proc.stdout:
            return
        try:
            for line in proc.stdout:
                text = line.decode("utf-8", errors="replace").rstrip()
                if text:
                    log.debug("[%s] %s", name, text)
        except Exception:
            pass

    def _on_shutdown(self, topic: str, value: Any, timestamp: float) -> None:
        if value:
            self.stop()
