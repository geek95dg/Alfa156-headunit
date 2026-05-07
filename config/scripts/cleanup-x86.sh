#!/bin/bash
# BCM x86 cleanup — removes all BCM services, configs, and user overrides.
# Run this before a fresh BCM reinstall on the same Debian system.
# Usage: sudo bash /opt/bcm/config/scripts/cleanup-x86.sh
set -e

echo "=== BCM x86 Cleanup ==="

# 1. Stop and remove BCM services
echo "[1/8] Stopping BCM services..."
for svc in bcm-ignition-watcher bcm-headunit bcm-splash-main bcm-splash-small bcm-kiosk bcm-resume; do
    systemctl stop "$svc" 2>/dev/null || true
    systemctl disable "$svc" 2>/dev/null || true
done
rm -f /etc/systemd/system/bcm-*.service
systemctl unmask bcm-kiosk.service 2>/dev/null || true
systemctl daemon-reload

# 2. Remove user kiosk configs
echo "[2/8] Removing kiosk configs..."
REAL_USER=${SUDO_USER:-$(logname 2>/dev/null || echo abner)}
HOME_DIR=$(eval echo "~$REAL_USER")
rm -f "$HOME_DIR/.xinitrc"
rm -f "$HOME_DIR/.bash_profile"
rm -rf /tmp/bcm-chromium-*

# 3. Remove autologin
echo "[3/8] Removing autologin..."
rm -rf /etc/systemd/system/getty@tty1.service.d

# 4. Remove WiFi AP configs
echo "[4/8] Removing WiFi AP configs..."
systemctl stop hostapd dnsmasq 2>/dev/null || true
systemctl disable hostapd dnsmasq 2>/dev/null || true
rm -f /etc/hostapd/hostapd.conf
rm -f /etc/dnsmasq.d/bcm-ap.conf
rm -f /etc/network/interfaces.d/bcm-ap
rm -f /etc/network/interfaces.d/static
nmcli device set wlp2s0 managed yes 2>/dev/null || true
ip addr flush dev wlp2s0 2>/dev/null || true

# 5. Remove acpid power button override
echo "[5/8] Removing power button override..."
rm -f /etc/acpi/events/power-button
rm -f /usr/local/bin/bcm-power-toggle.sh

# 6. Remove Chromium policy
echo "[6/8] Removing Chromium policy..."
rm -f /etc/chromium/policies/managed/bcm.json

# 7. Remove X11 wrapper override
echo "[7/8] Removing X11 wrapper..."
rm -f /etc/X11/Xwrapper.config

# 8. Clean venv
echo "[8/8] Removing Python venv..."
rm -rf /opt/bcm/.venv

systemctl daemon-reload
echo ""
echo "=== Cleanup complete ==="
echo ""
echo "Before reinstalling, make sure system packages are installed (§4):"
echo "  sudo apt install -y python3 python3-venv python3-full python3-dev git curl"
echo ""
echo "Then follow docs/X86_PLATFORM_SETUP.md from §5 onwards:"
echo "  cd /opt/bcm && git pull"
