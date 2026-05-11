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
        self._method: Optional[str] = None  # "p2p_go" | "nmcli" | "hostapd"
        self._ap_ip = config.get("wifi.ip", "10.0.0.1")
        self._netmask = config.get("wifi.netmask", "255.255.255.0")
        self._ssid = config.get("wifi.ssid", "Alfa156_AA")
        self._password = config.get("wifi.password", "alfa156headunit")
        self._nm_conn_name = "bcm-aa-hotspot"

        # hostapd/dnsmasq/wpa_supplicant processes
        self._hostapd_proc: Optional[subprocess.Popen] = None
        self._dnsmasq_proc: Optional[subprocess.Popen] = None
        self._wpa_proc: Optional[subprocess.Popen] = None
        # Secondary AP ("ALFA-NET" internet share) — only spun up when
        # the radio admits two concurrent VIFs (Intel 8265 typically
        # supports one P2P-GO + one AP at the same time on the same
        # channel). On phys that reject the combo we fall back to
        # time-multiplexing.
        self._net_iface: Optional[str] = None
        self._net_hostapd_proc: Optional[subprocess.Popen] = None
        self._net_dnsmasq_proc: Optional[subprocess.Popen] = None

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

        mode = self._config.get("wifi.mode", "hostapd")
        log.info("WiFi AP mode: %s", mode)

        # Honor the configured mode strictly. Multi-BSS (ALFA-NET on a
        # second BSSID) is only supported by the hostapd path — it's
        # inlined inside _start_hostapd so we don't call
        # _maybe_start_alfa_net here for hostapd.
        if mode == "p2p_go":
            if self._start_p2p_go():
                self._method = "p2p_go"
                self._running = True
                self._publish_started()
                self._maybe_start_alfa_net()
                return True
            log.warning("P2P-GO failed — falling back to hostapd")
            mode = "hostapd"

        if mode == "nmcli":
            if _has_networkmanager() and self._start_nmcli():
                self._method = "nmcli"
                self._running = True
                self._publish_started()
                self._maybe_start_alfa_net()
                return True
            log.warning("nmcli hotspot failed — falling back to hostapd")
            mode = "hostapd"

        # hostapd path — supports multi-BSS for ALFA + ALFA-NET
        # broadcasting from the same radio.
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

        # Secondary ALFA-NET AP first so dnsmasq releases the VIF before
        # we kill wpa_supplicant on the main interface.
        self._stop_alfa_net()

        if self._method == "p2p_go":
            self._stop_p2p_go()
        elif self._method == "nmcli":
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

            # Default to 2.4 GHz channel 6. The Intel 8265 firmware
            # rejects every 5 GHz frequency under country=PL with
            # "Frequency NNNN not allowed for AP mode, flags: NO-IR"
            # — both UNII-3 ch149 and UNII-1 ch36/40/44/48 fail. 2.4 GHz
            # ch1/6/11 always works and AA Wireless H.264 video runs
            # fine over 802.11n 40 MHz on 2.4 GHz.
            channel = self._config.get("wifi.channel", 6)
            band = self._config.get("wifi.band", "bg")
            result = subprocess.run(
                [
                    "nmcli", "device", "wifi", "hotspot",
                    "ifname", self._interface,
                    "con-name", self._nm_conn_name,
                    "ssid", self._ssid,
                    "band", band,
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
                if self._config.get("wifi.share_internet", True):
                    self._enable_internet_sharing()
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

        # Multi-BSS secondary VIF — bring up IP + a second dnsmasq for
        # ALFA-NET clients. hostapd creates the iface but doesn't
        # assign an IP; if we skip this, clients associate but can't
        # get DHCP. Best-effort: failures here don't tear down the
        # primary AA path.
        if self._net_iface:
            self._setup_alfa_net_secondary_bss()

        if self._config.get("wifi.share_internet", True):
            self._enable_internet_sharing()
        return True

    def _setup_alfa_net_secondary_bss(self) -> None:
        """Assign IP + start a second dnsmasq on the multi-BSS ALFA-NET VIF.

        hostapd's `bss=` directive creates the virtual interface but
        leaves IP/DHCP up to us. We give it a separate subnet from the
        primary AP (default 10.0.1.0/24) and a small dedicated dnsmasq
        process so its DHCP doesn't fight the primary AP's leases.
        """
        iface = self._net_iface
        net_ip = self._config.get("wifi.alfa_net.ip", "10.0.1.1")
        netmask = self._config.get("wifi.alfa_net.netmask", "255.255.255.0")
        prefix = _netmask_to_prefix(netmask)
        # hostapd brings up the bss= iface but it starts in some
        # drivers as DOWN — explicitly bring it up.
        for cmd in (["ip", "link", "set", iface, "up"],
                    ["ip", "addr", "flush", "dev", iface],
                    ["ip", "addr", "add", f"{net_ip}/{prefix}", "dev", iface]):
            subprocess.run(cmd, capture_output=True, timeout=4)
        dhcp_start = self._config.get("wifi.alfa_net.dhcp_start", "10.0.1.10")
        dhcp_end = self._config.get("wifi.alfa_net.dhcp_end", "10.0.1.50")
        try:
            self._net_dnsmasq_proc = subprocess.Popen(
                ["dnsmasq",
                 f"--interface={iface}",
                 "--bind-interfaces",
                 f"--dhcp-range={dhcp_start},{dhcp_end},{netmask},24h",
                 "--no-daemon", "--no-resolv", "--no-hosts"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
        except FileNotFoundError:
            log.warning("dnsmasq missing — ALFA-NET clients won't get DHCP")
            return
        log.info("ALFA-NET multi-BSS: %s up on %s/%d, DHCP %s-%s",
                 iface, net_ip, prefix, dhcp_start, dhcp_end)
        if self._config.get("wifi.alfa_net.share_internet", True):
            self._add_nat_for(iface)

    def _enable_internet_sharing(self) -> None:
        """Turn the AP into an internet gateway by NAT'ing through any
        non-AP uplink (LTE wwx*, eth*, usb0, etc.).

        Without this the phone gets an IP from dnsmasq but every
        outbound packet is dropped at the headunit because the kernel
        doesn't forward by default and there's no MASQUERADE rule.
        Best-effort: failures here don't tear down the AP — the user
        still gets the AA data link, just no public internet.
        """
        # 1. Enable IPv4 forwarding (transient — stays until reboot)
        try:
            with open("/proc/sys/net/ipv4/ip_forward", "w") as f:
                f.write("1\n")
        except OSError as e:
            log.warning("Could not enable IP forwarding: %s", e)
            return

        # 2. Find an uplink interface — anything that isn't us.
        uplinks = []
        try:
            for iface in os.listdir("/sys/class/net"):
                if iface in ("lo", self._interface):
                    continue
                # Prefer modem-style (ww*, wwan*) and ethernet up first
                operstate_path = f"/sys/class/net/{iface}/operstate"
                try:
                    with open(operstate_path) as f:
                        state = f.read().strip()
                except OSError:
                    state = ""
                if state == "up":
                    uplinks.append(iface)
        except OSError:
            pass

        if not uplinks:
            log.warning("WiFi AP: no uplink interface up — phone will get "
                        "an IP but no internet")
            return

        log.info("WiFi AP: enabling NAT via uplinks: %s", ", ".join(uplinks))

        # 3. Wire up iptables. -C check first so re-runs don't stack
        # duplicate rules, and -I FORWARD goes at the top because the
        # default Debian/NM FORWARD chain has a DROP near the end.
        rules = []
        for up in uplinks:
            rules.append(["-t", "nat", "-A", "POSTROUTING",
                          "-o", up, "-j", "MASQUERADE"])
            rules.append(["-A", "FORWARD",
                          "-i", up, "-o", self._interface,
                          "-m", "state",
                          "--state", "RELATED,ESTABLISHED",
                          "-j", "ACCEPT"])
            rules.append(["-A", "FORWARD",
                          "-i", self._interface, "-o", up,
                          "-j", "ACCEPT"])
        for rule in rules:
            try:
                # Replace -A/-I with -C to test for the rule first
                check = ["iptables"] + ["-C" if a == "-A" else a
                                         for a in rule]
                r = subprocess.run(check, capture_output=True, timeout=3)
                if r.returncode == 0:
                    continue   # already present
                subprocess.run(["iptables"] + rule,
                               capture_output=True, timeout=3, check=True)
            except FileNotFoundError:
                log.warning("iptables not installed — internet sharing "
                            "disabled")
                return
            except subprocess.CalledProcessError as e:
                log.warning("iptables rule failed: %s — %s",
                            rule, (e.stderr or b"").decode(errors="replace"))

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
        """Configure the WiFi interface with a static IP.

        For a Wi-Fi Direct GO child interface (``p2p-*``), we MUST NOT
        bring the link down — wpa_supplicant interprets that as the
        group going away and tears the P2P-GO down, after which the
        ``p2p-*`` iface vanishes entirely. Just flush the IP table and
        add ours. For regular hostapd-managed wlan ifaces the link
        cycle stays — those need an explicit down/up to clear leftover
        STA-mode state.
        """
        iface = self._interface
        is_p2p = iface.startswith("p2p-")
        try:
            if not is_p2p:
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
        """Generate hostapd config and start the daemon.

        Verbatim from the user's tested known-good config for the M910q
        Intel 7265 — extras like ieee80211d/wmm_enabled/macaddr_acl have
        repeatedly broken broadcast on this card, while this exact set
        comes up first try.

        When ``wifi.alfa_net.enabled`` is true, appends a second BSS
        section so hostapd broadcasts BOTH ``ALFA`` and ``ALFA-NET`` on
        the same channel from the same radio — Intel 8265's
        interface_combinations rejects AP+P2P-GO concurrent but allows
        multi-BSS within a single AP role.
        """
        config_path = os.path.join(RUNTIME_DIR, "hostapd.conf")
        # Channel/band/country are sourced from wifi.* in the YAML so the
        # BCM-internal AP path stays in sync with what setup-x86.sh wrote
        # to /etc/hostapd/hostapd.conf — defaults are 2.4 GHz ch6,
        # hw_mode=g, country=PL. The Intel 8265 firmware rejects every
        # 5 GHz frequency under PL regdom (NO-IR), so 5 GHz isn't usable
        # on this hardware regardless of how non-DFS the channel is.
        channel = self._config.get("wifi.channel", 6)
        hw_mode = self._config.get("wifi.band", "g")
        country = self._config.get("wifi.country", "PL")
        is_5ghz = hw_mode == "a"
        config_content = (
            f"interface={self._interface}\n"
            f"driver=nl80211\n"
            f"ssid={self._ssid}\n"
            f"hw_mode={hw_mode}\n"
            f"channel={channel}\n"
            f"ieee80211n=1\n"
            f"{'ieee80211ac=1' if is_5ghz else '#ieee80211ac=1 (2.4 GHz)'}\n"
            f"wpa=2\n"
            f"wpa_passphrase={self._password}\n"
            f"wpa_key_mgmt=WPA-PSK\n"
            f"rsn_pairwise=CCMP\n"
            f"wpa_pairwise=CCMP\n"
            f"country_code={country}\n"
        )

        # Multi-BSS: append a second virtual AP for ALFA-NET if enabled.
        # The `bss=` directive creates an additional BSSID on the same
        # radio/channel. Hostapd's auto-derivation increments the
        # primary MAC's last octet by 1 — which collides with the
        # kernel's reserved P2P-device handle MAC (primary+1 is the
        # canonical Wi-Fi Direct device address). Set `bssid=` to
        # primary+2 to dodge the collision; the locally-administered
        # bit is also flipped so the MAC is unambiguously synthetic.
        if self._config.get("wifi.alfa_net.enabled", True):
            net_ssid = self._config.get("wifi.alfa_net.ssid", "ALFA-NET")
            net_pwd = self._config.get("wifi.alfa_net.password",
                                       "AlfaRomeo156")
            bss_iface = f"{self._interface}_net"
            # Read primary MAC + derive secondary BSSID.
            try:
                with open(f"/sys/class/net/{self._interface}/address") as f:
                    primary_mac = f.read().strip().lower()
                octets = [int(o, 16) for o in primary_mac.split(":")]
                # +2 in last octet (avoid +1 = P2P-device handle), and
                # set the locally-administered bit on the first octet
                # so the address can't be confused with the OUI.
                octets[0] |= 0x02
                octets[5] = (octets[5] + 2) & 0xff
                secondary_bssid = ":".join(f"{o:02x}" for o in octets)
            except Exception:
                secondary_bssid = ""
            config_content += (
                f"\n# Secondary BSS — ALFA-NET internet share\n"
                f"bss={bss_iface}\n"
                f"ssid={net_ssid}\n"
                + (f"bssid={secondary_bssid}\n" if secondary_bssid else "") +
                f"wpa=2\n"
                f"wpa_passphrase={net_pwd}\n"
                f"wpa_key_mgmt=WPA-PSK\n"
                f"rsn_pairwise=CCMP\n"
            )
            self._net_iface = bss_iface
            log.info("hostapd multi-BSS: primary=%s secondary=%s "
                     "(BSSID=%s, SSID=%s)",
                     self._ssid, net_ssid,
                     secondary_bssid or "auto", net_ssid)

        with open(config_path, "w") as f:
            f.write(config_content)

        # Unblock rfkill before hostapd — the radio comes up soft-blocked
        # on the M910q at cold boot and hostapd reports rc=0 on a blocked
        # interface, just never broadcasts.
        try:
            subprocess.run(["rfkill", "unblock", "wifi"],
                           capture_output=True, timeout=3)
            subprocess.run(["rfkill", "unblock", "all"],
                           capture_output=True, timeout=3)
        except Exception:
            pass

        def _launch(path: str) -> bool:
            try:
                self._hostapd_proc = subprocess.Popen(
                    ["hostapd", path],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                )
            except Exception:
                log.exception("Failed to launch hostapd")
                return False
            time.sleep(2)
            if self._hostapd_proc.poll() is None:
                threading.Thread(
                    target=self._read_proc_logs,
                    args=(self._hostapd_proc, "hostapd"),
                    daemon=True,
                ).start()
                log.info("hostapd started (PID %d)", self._hostapd_proc.pid)
                return True
            out = self._hostapd_proc.stdout.read().decode(
                "utf-8", errors="replace") if self._hostapd_proc.stdout else ""
            log.error("hostapd failed to start: %s", out.strip())
            self._hostapd_proc = None
            return False

        if _launch(config_path):
            return True

        # Multi-BSS failure recovery: iwlwifi 8265's interface_combinations
        # admits exactly ONE AP role on this radio (`#{AP, P2P-client,
        # P2P-GO} <= 1`), so the `bss=` secondary trips
        # "Could not set interface wlp2s0_net flags (UP): Device or
        # resource busy". If we asked for ALFA-NET and the dual-BSS
        # launch failed, retry single-BSS so the primary ALFA still
        # comes up; ALFA-NET is unavailable on this hardware without
        # a second radio (USB dongle).
        if self._net_iface and self._config.get("wifi.alfa_net.enabled", True):
            log.warning("Multi-BSS rejected by iwlwifi (8265 admits 1 AP "
                        "only) — retrying ALFA single-BSS without "
                        "ALFA-NET. Plug a USB WiFi dongle to get the "
                        "second SSID concurrently.")
            single_bss = config_content.split("\n# Secondary BSS")[0]
            with open(config_path, "w") as f:
                f.write(single_bss)
            self._net_iface = None
            if _launch(config_path):
                return True
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

    # ------------------------------------------------------------------
    # wpa_supplicant P2P-GO method (Wi-Fi Direct Group Owner)
    # ------------------------------------------------------------------

    def _start_p2p_go(self) -> bool:
        """Bring up the AA WiFi as a Wi-Fi Direct Group Owner on ch149.

        Why this path: the AA Wireless protocol the phone speaks is
        Wi-Fi Direct internally, and P2P-GO is the only AP-equivalent
        role iwlwifi 8265 lets us start on 5 GHz under a self-managed
        regdom (the regular AP role gets ``Frequency NNNN not allowed,
        flags: NO-IR``). We also rfkill-unblock + force regdom first
        because the Intel firmware still honors a country hint when
        choosing which channels it'll *accept* a P2P GO on.
        """
        # Make sure NetworkManager isn't holding the interface — wpa_s
        # P2P refuses to bind otherwise.
        if _has_networkmanager():
            subprocess.run(
                ["nmcli", "device", "set", self._interface, "managed", "no"],
                capture_output=True, timeout=5,
            )
            time.sleep(0.3)

        # Best-effort regdom kick. User waived country compliance so we
        # try a country that the iwlwifi 8265 firmware admits is OK on
        # ch149 (BO/JP/IN have historically worked). `iw reg set` is a
        # no-op on self-managed PHYs but costs nothing to attempt.
        regdom = self._config.get("wifi.regdom", "BO")
        for cmd in (["rfkill", "unblock", "wifi"],
                    ["rfkill", "unblock", "all"],
                    ["iw", "reg", "set", regdom]):
            try:
                subprocess.run(cmd, capture_output=True, timeout=3)
            except Exception:
                pass

        os.makedirs(RUNTIME_DIR, exist_ok=True)
        ctrl_dir = os.path.join(RUNTIME_DIR, "wpa-ctrl")
        os.makedirs(ctrl_dir, exist_ok=True)
        conf_path = os.path.join(RUNTIME_DIR, "wpa-p2p.conf")
        # device_name carries through to the phone's Wi-Fi Direct picker.
        wpa_conf = (
            f"ctrl_interface=DIR={ctrl_dir} GROUP=netdev\n"
            f"update_config=1\n"
            f"country={regdom}\n"
            f"device_name=Alfa156 Headunit\n"
            f"device_type=8-0050F204-2\n"  # AudioVideo / Carkit
            f"p2p_go_intent=15\n"
            f"p2p_go_ht40=1\n"
            f"p2p_go_vht=1\n"
            f"persistent_reconnect=1\n"
        )
        with open(conf_path, "w") as f:
            f.write(wpa_conf)

        # Kill stale wpa_supplicant on this interface so we don't race.
        try:
            subprocess.run(["pkill", "-f",
                            f"wpa_supplicant.*{self._interface}"],
                           capture_output=True, timeout=3)
        except Exception:
            pass
        time.sleep(0.5)

        try:
            self._wpa_proc = subprocess.Popen(
                ["wpa_supplicant",
                 "-i", self._interface,
                 "-D", "nl80211",
                 "-c", conf_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
        except FileNotFoundError:
            log.warning("wpa_supplicant not installed — install via apt")
            return False

        # Wait for ctrl socket to appear.
        ctrl_path = os.path.join(ctrl_dir, self._interface)
        deadline = time.time() + 5.0
        while time.time() < deadline and not os.path.exists(ctrl_path):
            if self._wpa_proc.poll() is not None:
                log.error("wpa_supplicant exited before ctrl socket ready")
                return False
            time.sleep(0.2)
        if not os.path.exists(ctrl_path):
            log.error("wpa_supplicant ctrl socket never appeared at %s",
                      ctrl_path)
            self._stop_p2p_go()
            return False

        # Start a persistent P2P group. Channel→freq mapping differs
        # between bands: 2.4 GHz ch1-13 uses 2407+5*N (and ch14 is the
        # special-case 2484 MHz for JP), while 5 GHz uses 5000+5*N.
        # Picking the wrong formula sends ch6 to 5030 MHz which is
        # NO-IR on the Intel 8265 firmware — silent `p2p_group_add: FAIL`.
        channel = int(self._config.get("wifi.channel", 6))
        if channel <= 14:
            freq = 2484 if channel == 14 else 2407 + 5 * channel
        else:
            freq = 5000 + 5 * channel
        cli_cmd = [
            "wpa_cli", "-p", ctrl_dir, "-i", self._interface,
            "p2p_group_add", f"freq={freq}", "persistent",
        ]
        r = subprocess.run(cli_cmd, capture_output=True, text=True, timeout=10)
        if r.returncode != 0 or "FAIL" in (r.stdout + r.stderr).upper():
            log.error("p2p_group_add failed: %s%s",
                      r.stdout.strip(), r.stderr.strip())
            self._stop_p2p_go()
            return False
        log.info("wpa_cli p2p_group_add OK: %s", r.stdout.strip())

        # Find the p2p-wlan*-N interface wpa_s just created.
        time.sleep(1.5)
        p2p_iface = self._find_p2p_iface(self._interface)
        if not p2p_iface:
            log.warning("Could not locate p2p group interface — using "
                        "primary %s for IP", self._interface)
            p2p_iface = self._interface

        # Wi-Fi Direct GOs broadcast a spec-mandated `DIRECT-XX` SSID
        # with a random WPA2 passphrase. Read what wpa_supplicant
        # generated and overwrite self._ssid / self._password so the
        # downstream openauto.ini regen sends the *real* SSID + PSK
        # to the phone over BT. Without this, the phone is told to
        # join "ALFA" while the actual GO is "DIRECT-Qi" → AA-Wireless
        # connect fails silently.
        if p2p_iface != self._interface:
            real_ssid = self._wpa_query(ctrl_dir, p2p_iface, "status",
                                        prop="ssid")
            real_psk = self._wpa_query(ctrl_dir, p2p_iface,
                                       "p2p_get_passphrase")
            real_bssid = self._wpa_query(ctrl_dir, p2p_iface, "status",
                                         prop="bssid")
            if real_ssid:
                self._ssid = real_ssid
            if real_psk:
                self._password = real_psk
            # The GO has its own MAC (parent±2 typically) — publish so
            # openauto.ini gets the right BSSID for WifiInfoResponse.
            log.info("P2P-GO advertising SSID=%s psk=%s… on BSSID=%s",
                     self._ssid, (self._password or "")[:3],
                     real_bssid or "?")
            try:
                self._config.set("wifi.ssid_runtime", self._ssid)
                self._config.set("wifi.password_runtime", self._password)
                if real_bssid:
                    self._config.set("wifi.bssid_runtime", real_bssid)
            except Exception:
                log.debug("Could not persist runtime SSID/PSK")
            self._event_bus.publish("wifi.ap_credentials", {
                "ssid": self._ssid,
                "password": self._password,
                "bssid": real_bssid,
            })

        # Assign IP + start dnsmasq on the GO interface.
        prev_iface = self._interface
        self._interface = p2p_iface
        if not self._setup_interface():
            self._interface = prev_iface
            self._stop_p2p_go()
            return False
        if not self._start_dnsmasq():
            self._stop_p2p_go()
            return False

        if self._config.get("wifi.share_internet", True):
            self._enable_internet_sharing()
        return True

    @staticmethod
    def _wpa_query(ctrl_dir: str, iface: str, cmd: str,
                   prop: Optional[str] = None) -> str:
        """Run wpa_cli and return either a single property from `status`
        output (when `prop` is set) or the trimmed raw response.
        """
        try:
            r = subprocess.run(
                ["wpa_cli", "-p", ctrl_dir, "-i", iface, cmd],
                capture_output=True, text=True, timeout=4,
            )
        except Exception:
            return ""
        out = (r.stdout or "").strip()
        if not prop:
            # Single-line responses like p2p_get_passphrase come back
            # as `9aAuzYNy` with no key=value framing.
            return out.splitlines()[-1].strip() if out else ""
        for line in out.splitlines():
            if line.startswith(prop + "="):
                return line.split("=", 1)[1].strip().strip('"')
        return ""

    @staticmethod
    def _find_p2p_iface(primary: str) -> Optional[str]:
        """Locate the p2p-wlan*-N child interface for `primary`."""
        try:
            for iface in os.listdir("/sys/class/net"):
                if iface.startswith("p2p-") and primary.split("-")[0] in iface:
                    return iface
            # Fallback — any p2p-* iface
            for iface in os.listdir("/sys/class/net"):
                if iface.startswith("p2p-"):
                    return iface
        except OSError:
            pass
        return None

    def _stop_p2p_go(self) -> None:
        """Tear down wpa_supplicant P2P-GO group + dnsmasq."""
        self._stop_dnsmasq()
        ctrl_dir = os.path.join(RUNTIME_DIR, "wpa-ctrl")
        if self._interface and self._interface.startswith("p2p-"):
            try:
                subprocess.run(
                    ["wpa_cli", "-p", ctrl_dir, "-i", self._interface,
                     "p2p_group_remove", self._interface],
                    capture_output=True, timeout=5,
                )
            except Exception:
                pass
        if self._wpa_proc and self._wpa_proc.poll() is None:
            self._wpa_proc.send_signal(signal.SIGTERM)
            try:
                self._wpa_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._wpa_proc.kill()
        self._wpa_proc = None

        if _has_networkmanager():
            primary = self._config.get("wifi.interface", "") or "wlan0"
            subprocess.run(
                ["nmcli", "device", "set", primary, "managed", "yes"],
                capture_output=True, timeout=5,
            )

    # ------------------------------------------------------------------
    # Secondary "ALFA-NET" internet-sharing AP
    # ------------------------------------------------------------------

    def _maybe_start_alfa_net(self) -> None:
        """Bring up the editable ALFA-NET hotspot on a second VIF.

        Strategy (in order — first that works wins):
          1. **Different physical radio** — if a second wireless iface
             exists (USB dongle), park ALFA-NET there.
          2. **Concurrent VIF on same phy** — iw add interface __ap;
             only succeeds when the driver advertises an AP/GO + AP
             combination. iwlwifi 8265 advertises ``#{AP, P2P-GO} <= 1``
             which means it does NOT — adding an AP VIF on the same
             PHY as an active P2P-GO group collapses the GO. The
             concurrent-VIF check below catches that and skips.
          3. **Skip** — log a warning and require a USB dongle for
             ALFA-NET. Time-multiplexing is intentionally NOT done
             here because the AA P2P-GO group is the primary mission
             and must stay up.
        """
        if not self._config.get("wifi.alfa_net.enabled", True):
            return
        ssid = self._config.get("wifi.alfa_net.ssid", "ALFA-NET")
        password = self._config.get("wifi.alfa_net.password", "AlfaRomeo156")
        net_ip = self._config.get("wifi.alfa_net.ip", "10.0.1.1")
        net_mask = self._config.get("wifi.alfa_net.netmask", "255.255.255.0")
        # When the primary AP is P2P-GO, self._interface is the child
        # `p2p-<parent>-N` iface but the radio actually being used is
        # the parent — derive it from the iface name so the same-PHY
        # check below treats the parent as already-claimed.
        primary = self._interface or ""
        parent = primary
        if primary.startswith("p2p-"):
            # p2p-wlp2s0-0 → wlp2s0
            try:
                parent = primary.split("-", 2)[1]
            except IndexError:
                parent = primary
        primary_phy = (self._phy_for_iface(parent)
                       or self._phy_for_iface(primary))
        if not primary_phy:
            log.warning("ALFA-NET: couldn't resolve primary PHY — "
                        "skipping to avoid clobbering the AA group")
            return
        candidate = None
        try:
            for iface in sorted(os.listdir("/sys/class/net")):
                if iface in (primary, parent):
                    continue
                if not (iface.startswith(("wlan", "wlp", "wlx"))
                        or os.path.isdir(f"/sys/class/net/{iface}/wireless")):
                    continue
                phy = self._phy_for_iface(iface)
                if phy and phy != primary_phy:
                    candidate = iface
                    break
        except OSError:
            pass

        if candidate:
            log.info("ALFA-NET: using separate radio %s", candidate)
            if self._start_alfa_net_on(candidate, ssid, password,
                                       net_ip, net_mask):
                self._net_iface = candidate
                return

        # Path 2: concurrent VIF on same PHY. Intel 8265's
        # interface_combinations advertises `#{AP, P2P-GO} <= 1`, so
        # adding an AP VIF while a P2P-GO group is active will
        # silently collapse the GO. The `iw phy ... interface add`
        # command often returns rc=0 anyway, then hostapd starts and
        # knocks AA off the air. Skip this path entirely when the
        # primary is p2p_go to keep AA up.
        if self._method == "p2p_go":
            log.warning(
                "ALFA-NET disabled — primary AP is P2P-GO and the "
                "Intel 8265 PHY can't host AA + ALFA-NET concurrently. "
                "Plug a USB WiFi dongle for ALFA-NET."
            )
            return

        if primary_phy:
            vif = f"{primary}_net"
            try:
                r = subprocess.run(
                    ["iw", "phy", primary_phy, "interface", "add",
                     vif, "type", "__ap"],
                    capture_output=True, text=True, timeout=4,
                )
                if r.returncode == 0:
                    log.info("ALFA-NET: created concurrent VIF %s on %s",
                             vif, primary_phy)
                    if self._start_alfa_net_on(vif, ssid, password,
                                               net_ip, net_mask):
                        self._net_iface = vif
                        return
                    subprocess.run(["iw", "dev", vif, "del"],
                                   capture_output=True, timeout=3)
                else:
                    log.warning("ALFA-NET: PHY rejects concurrent AP VIF "
                                "(driver combo): %s",
                                (r.stderr or r.stdout).strip())
            except Exception as e:
                log.warning("ALFA-NET concurrent VIF setup raised: %s", e)

        log.warning("ALFA-NET disabled — no spare radio and PHY won't "
                    "host a second AP VIF. Plug a USB WiFi dongle to "
                    "enable internet sharing without losing AA Wireless.")

    @staticmethod
    def _phy_for_iface(iface: str) -> Optional[str]:
        try:
            r = subprocess.run(
                ["iw", "dev", iface, "info"],
                capture_output=True, text=True, timeout=3,
            )
            for line in r.stdout.splitlines():
                line = line.strip()
                if line.startswith("wiphy "):
                    return f"phy{line.split()[1]}"
        except Exception:
            pass
        return None

    def _start_alfa_net_on(self, iface: str, ssid: str, password: str,
                           net_ip: str, netmask: str) -> bool:
        """Bring up hostapd + dnsmasq for the secondary ALFA-NET SSID."""
        os.makedirs(RUNTIME_DIR, exist_ok=True)
        conf_path = os.path.join(RUNTIME_DIR, "hostapd-alfanet.conf")
        # 2.4 GHz ch6 — works everywhere, doesn't share the main 5 GHz
        # frequency unless the radio forces it.
        channel = int(self._config.get("wifi.alfa_net.channel", 6))
        country = self._config.get("wifi.alfa_net.country", "BO")
        conf = (
            f"interface={iface}\n"
            f"driver=nl80211\n"
            f"ssid={ssid}\n"
            f"hw_mode=g\n"
            f"channel={channel}\n"
            f"ieee80211n=1\n"
            f"wpa=2\n"
            f"wpa_passphrase={password}\n"
            f"wpa_key_mgmt=WPA-PSK\n"
            f"rsn_pairwise=CCMP\n"
            f"country_code={country}\n"
        )
        with open(conf_path, "w") as f:
            f.write(conf)

        # IP + bring iface up before hostapd binds.
        prefix = _netmask_to_prefix(netmask)
        for cmd in (["ip", "link", "set", iface, "up"],
                    ["ip", "addr", "flush", "dev", iface],
                    ["ip", "addr", "add", f"{net_ip}/{prefix}", "dev", iface]):
            subprocess.run(cmd, capture_output=True, timeout=4)

        try:
            self._net_hostapd_proc = subprocess.Popen(
                ["hostapd", conf_path],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
            time.sleep(1.5)
            if self._net_hostapd_proc.poll() is not None:
                out = (self._net_hostapd_proc.stdout.read().decode(
                    errors="replace") if self._net_hostapd_proc.stdout else "")
                log.error("ALFA-NET hostapd failed: %s", out.strip())
                self._net_hostapd_proc = None
                return False
        except FileNotFoundError:
            log.warning("hostapd not installed — ALFA-NET disabled")
            return False

        # dnsmasq on a different range than the primary AA AP.
        dhcp_start = self._config.get("wifi.alfa_net.dhcp_start", "10.0.1.10")
        dhcp_end = self._config.get("wifi.alfa_net.dhcp_end", "10.0.1.50")
        try:
            self._net_dnsmasq_proc = subprocess.Popen(
                ["dnsmasq",
                 f"--interface={iface}",
                 "--bind-interfaces",
                 f"--dhcp-range={dhcp_start},{dhcp_end},{netmask},24h",
                 "--no-daemon", "--no-resolv", "--no-hosts"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
        except FileNotFoundError:
            log.warning("dnsmasq missing — ALFA-NET clients won't get IPs")
            self._stop_alfa_net()
            return False

        log.info("ALFA-NET up: SSID=%s on %s IP=%s/%d ch%d",
                 ssid, iface, net_ip, prefix, channel)
        # Best-effort NAT for ALFA-NET clients too.
        if self._config.get("wifi.alfa_net.share_internet", True):
            self._add_nat_for(iface)
        return True

    def _stop_alfa_net(self) -> None:
        for proc in (self._net_dnsmasq_proc, self._net_hostapd_proc):
            if proc and proc.poll() is None:
                proc.send_signal(signal.SIGTERM)
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
        self._net_dnsmasq_proc = None
        self._net_hostapd_proc = None
        if self._net_iface:
            # Delete the VIF we created (only if it ends in _net — the
            # USB-dongle path uses a real interface that should survive).
            if self._net_iface.endswith("_net"):
                subprocess.run(["iw", "dev", self._net_iface, "del"],
                               capture_output=True, timeout=3)
            self._net_iface = None

    def _add_nat_for(self, iface: str) -> None:
        """Add MASQUERADE for ALFA-NET clients via any non-WiFi uplink."""
        try:
            with open("/proc/sys/net/ipv4/ip_forward", "w") as f:
                f.write("1\n")
        except OSError:
            return
        uplinks = []
        try:
            for u in os.listdir("/sys/class/net"):
                if u in ("lo", iface, self._interface):
                    continue
                if u.startswith(("wlan", "wlp", "wlx", "p2p-")):
                    continue
                try:
                    with open(f"/sys/class/net/{u}/operstate") as f:
                        if f.read().strip() == "up":
                            uplinks.append(u)
                except OSError:
                    pass
        except OSError:
            return
        for up in uplinks:
            for rule in (["-t", "nat", "-A", "POSTROUTING",
                          "-o", up, "-j", "MASQUERADE"],
                         ["-A", "FORWARD", "-i", up, "-o", iface,
                          "-m", "state", "--state",
                          "RELATED,ESTABLISHED", "-j", "ACCEPT"],
                         ["-A", "FORWARD", "-i", iface, "-o", up,
                          "-j", "ACCEPT"]):
                try:
                    subprocess.run(["iptables"] + rule,
                                   capture_output=True, timeout=3)
                except FileNotFoundError:
                    return

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
