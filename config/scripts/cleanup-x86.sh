#!/bin/bash
# BCM x86 cleanup — removes all BCM services, configs, and user overrides.
# Run this before a fresh BCM reinstall on the same Debian system.
# Usage: sudo bash /opt/bcm/config/scripts/cleanup-x86.sh
#
# Also reverts what bcm-harden.sh changed, except /etc/fstab and
# /etc/default/grub: those are left as they are (noatime / fsck.repair=yes
# are safe on any system) and the backups bcm-harden.sh made are listed at
# the end for a manual restore. /etc/bcm/bcm.env (API keys, passwords) is
# kept as well.
set -e

APT_MARKER=/etc/bcm/.harden-apt-disabled
CLOUDINIT_MARKER=/etc/bcm/.harden-cloudinit-disabled
# The only units bcm-harden.sh ever disables — the marker is root-owned,
# but its content is still checked against this list before use.
APT_UNITS="apt-daily.timer apt-daily-upgrade.timer unattended-upgrades.service"

echo "=== BCM x86 Cleanup ==="

# 1. Stop and remove BCM services
echo "[1/9] Stopping BCM services..."
for svc in bcm-ignition-watcher bcm-headunit bcm-splash-main bcm-splash-small bcm-kiosk bcm-resume \
           bcm-nat bcm-nat-late bcm-timesync; do
    systemctl stop "$svc" 2>/dev/null || true
    systemctl disable "$svc" 2>/dev/null || true
done
for timer in bcm-timesync.timer bcm-nat-late.timer; do
    systemctl stop "$timer" 2>/dev/null || true
    systemctl disable "$timer" 2>/dev/null || true
done
rm -f /etc/systemd/system/bcm-*.service
rm -f /etc/systemd/system/bcm-*.timer
rm -f /usr/local/bin/bcm-timesync.sh
rm -f /usr/local/bin/bcm-nat.sh
systemctl unmask bcm-kiosk.service 2>/dev/null || true
systemctl daemon-reload

# 2. Remove user kiosk configs
echo "[2/9] Removing kiosk configs..."
REAL_USER=${SUDO_USER:-$(logname 2>/dev/null || echo abner)}
HOME_DIR=$(eval echo "~$REAL_USER")
rm -f "$HOME_DIR/.xinitrc"
rm -f "$HOME_DIR/.bash_profile"
rm -rf /tmp/bcm-chromium-*

# 3. Remove autologin
echo "[3/9] Removing autologin..."
rm -rf /etc/systemd/system/getty@tty1.service.d

# 4. Remove WiFi AP configs
echo "[4/9] Removing WiFi AP configs..."
systemctl stop hostapd dnsmasq 2>/dev/null || true
systemctl disable hostapd dnsmasq 2>/dev/null || true
rm -f /etc/hostapd/hostapd.conf
rm -f /etc/dnsmasq.d/bcm-ap.conf
rm -f /etc/network/interfaces.d/bcm-ap
rm -f /etc/network/interfaces.d/static
nmcli device set wlp2s0 managed yes 2>/dev/null || true
ip addr flush dev wlp2s0 2>/dev/null || true

# 5. Remove acpid power button override
echo "[5/9] Removing power button override..."
rm -f /etc/acpi/events/power-button
rm -f /usr/local/bin/bcm-power-toggle.sh

# 6. Remove Chromium policy
echo "[6/9] Removing Chromium policy..."
rm -f /etc/chromium/policies/managed/bcm.json

# 7. Remove X11 wrapper override
echo "[7/9] Removing X11 wrapper..."
rm -f /etc/X11/Xwrapper.config

# 8. Revert bcm-harden.sh
echo "[8/9] Reverting bcm-harden.sh (journald, sysctl, boot units)..."
if [ -f /etc/systemd/journald.conf.d/10-bcm-volatile.conf ]; then
    rm -f /etc/systemd/journald.conf.d/10-bcm-volatile.conf
    systemctl restart systemd-journald 2>/dev/null || true
fi
if [ -f /etc/sysctl.d/90-bcm-powerloss.conf ]; then
    rm -f /etc/sysctl.d/90-bcm-powerloss.conf
    # Back to the kernel defaults, then let any other sysctl.d file that
    # sets these keys win again.
    sysctl -q -w vm.dirty_expire_centisecs=3000 vm.dirty_writeback_centisecs=500 2>/dev/null || true
    sysctl --system >/dev/null 2>&1 || true
fi
systemctl unmask NetworkManager-wait-online.service 2>/dev/null || true
# apt timers / cloud-init only when bcm-harden.sh was the one that turned
# them off (marker present) — never override an admin's own choice.
if [ -f "$APT_MARKER" ]; then
    while read -r unit; do
        case "$unit" in
            '' | '#'*) continue ;;
        esac
        case " $APT_UNITS " in
            *" $unit "*)
                echo "  re-enabling $unit"
                systemctl enable --now "$unit" 2>/dev/null || true
                ;;
            *) echo "  ignoring unexpected entry in $APT_MARKER: $unit" ;;
        esac
    done <"$APT_MARKER"
    rm -f "$APT_MARKER"
fi
if [ -f "$CLOUDINIT_MARKER" ]; then
    echo "  re-enabling cloud-init"
    rm -f /etc/cloud/cloud-init.disabled
    rm -f "$CLOUDINIT_MARKER"
fi

# 9. Clean venv
echo "[9/9] Removing Python venv..."
rm -rf /opt/bcm/.venv

systemctl daemon-reload
echo ""
echo "=== Cleanup complete ==="
echo ""
echo "Kept on purpose:"
echo "  /etc/bcm/bcm.env — API keys and passwords (delete by hand if no longer needed)"
echo "  /etc/fstab and /etc/default/grub — changes by bcm-harden.sh (noatime,"
echo "  fsck.repair=yes) stay. Backups to restore from, if any:"
found_backup=0
for f in /etc/fstab.bcm-*.bak /etc/default/grub.bcm-*.bak; do
    if [ -e "$f" ]; then
        echo "    $f"
        found_backup=1
    fi
done
if [ "$found_backup" -eq 0 ]; then
    echo "    (none)"
fi
echo "  Restore: sudo cp BACKUP ORIGINAL (then sudo update-grub for GRUB)"
echo ""
echo "Before reinstalling, make sure system packages are installed (§4):"
echo "  sudo apt install -y python3 python3-venv python3-full python3-dev git curl"
echo ""
echo "Then follow docs/X86_PLATFORM_SETUP.md from §5 onwards:"
echo "  cd /opt/bcm && git pull"
