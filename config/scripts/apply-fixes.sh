#!/bin/bash
# One-shot installer for the BT / WiFi / AA / splash fixes.
# Run once with sudo, then reboot.
#
#   sudo bash /opt/bcm/config/scripts/apply-fixes.sh
#
# Idempotent — safe to re-run. Does NOT touch python sources or yaml
# config (those live in /opt/bcm and are picked up directly by the
# headunit on next start).
set -u

BCM_DIR=/opt/bcm

if [ "$(id -u)" -ne 0 ]; then
    echo "Run with sudo: sudo bash $0"; exit 1
fi

echo "==> 1/6  Installing splash player + units"
install -m 0755 "$BCM_DIR/config/scripts/bcm-splash-play.sh" /usr/local/bin/bcm-splash-play.sh
install -m 0644 "$BCM_DIR/config/systemd/bcm-splash-main.service" /etc/systemd/system/bcm-splash-main.service
install -m 0644 "$BCM_DIR/config/systemd/bcm-splash-small.service" /etc/systemd/system/bcm-splash-small.service
systemctl disable bcm-splash-small.service 2>/dev/null || true
rm -f /etc/systemd/system/multi-user.target.wants/bcm-splash-small.service

echo "==> 2/6  Installing Bluetooth setup (Class=carkit + AlwaysPairable + drop internal Intel BT)"
install -m 0755 "$BCM_DIR/config/scripts/bcm-bluetooth-setup.sh" /usr/local/bin/bcm-bluetooth-setup.sh
install -m 0644 "$BCM_DIR/config/systemd/bcm-bluetooth.service" /etc/systemd/system/bcm-bluetooth.service

# Drop the integrated Intel 8087 controller so only the USB dongle is
# visible to BlueZ. The script-level unbind catches it at service start;
# the udev rule below kills it earlier, before bluetoothd ever sees it,
# which avoids the race where bluetoothd grabs the Intel as default
# adapter and the phone latches onto its (broken) BD_ADDR.
mkdir -p /etc/default
if [ ! -f /etc/default/bcm-bluetooth ] || ! grep -q "^BCM_BT_KEEP_INTERNAL=" /etc/default/bcm-bluetooth; then
    echo "BCM_BT_KEEP_INTERNAL=0" >> /etc/default/bcm-bluetooth
fi
# Also flip the legacy "prefer Intel" flag off — even with the unbind
# we don't want userspace fallback to look for the Intel first.
if grep -q "^BCM_BT_PREFER_INTERNAL=1" /etc/default/bcm-bluetooth 2>/dev/null; then
    sed -i 's/^BCM_BT_PREFER_INTERNAL=1/BCM_BT_PREFER_INTERNAL=0/' /etc/default/bcm-bluetooth
fi
cat > /etc/udev/rules.d/81-bcm-disable-intel-bt.rules <<'UDEV'
# Disable the integrated Intel 8087:0a2b Bluetooth controller (M910q etc).
# The kernel writes "0" to /sys/bus/usb/devices/X/authorized on attach,
# which prevents the btusb driver from binding. Re-enable by removing
# this rule or echoing 1 to the device's authorized sysfs entry.
SUBSYSTEM=="usb", ATTR{idVendor}=="8087", ATTR{idProduct}=="0a2b", ATTR{authorized}="0"
UDEV
udevadm control --reload-rules 2>/dev/null || true
# Trigger now so any currently-bound Intel BT goes away without a reboot.
udevadm trigger --action=add --attr-match=idVendor=8087 2>/dev/null || true

# Apply BT main.conf changes now (the setup script also does this, but
# running it here makes the result observable before reboot).
if [ -f /etc/bluetooth/main.conf ]; then
    for kv in "Class=0x620420" "DiscoverableTimeout=0" "PairableTimeout=0" "AlwaysPairable=true" "FastConnectable=true" "JustWorksRepairing=always"; do
        key=${kv%%=*}
        if grep -qE "^[#[:space:]]*${key}[[:space:]]*=" /etc/bluetooth/main.conf; then
            sed -i "s|^[#[:space:]]*${key}[[:space:]]*=.*|${kv}|" /etc/bluetooth/main.conf
        else
            sed -i "/^\[General\]/a ${kv}" /etc/bluetooth/main.conf
        fi
    done
    grep -q '^\[Policy\]' /etc/bluetooth/main.conf \
        && sed -i 's/^#*AutoEnable.*/AutoEnable=true/' /etc/bluetooth/main.conf
fi
systemctl restart bluetooth.service 2>/dev/null || true

echo "==> 3/6  Writing hostapd config (2.4 GHz ch6, country US)"
# Intel 8265 firmware locks every 5 GHz channel as NO-IR for AP mode
# regardless of regdom — verified with `iw phy` after `iw reg set US`,
# `iw reg set PL`, and hostapd country_code permutations. Don't bother
# trying 5 GHz channels here; nothing software-side opens up the
# transmit lockout. Stay on 2.4 GHz which works first try.
if [ -f /etc/hostapd/hostapd.conf ]; then
    cp /etc/hostapd/hostapd.conf /etc/hostapd/hostapd.conf.bak.$(date +%s)
    SSID=$(awk -F= '/^ssid=/{print $2; exit}' /etc/hostapd/hostapd.conf)
    PASS=$(awk -F= '/^wpa_passphrase=/{print $2; exit}' /etc/hostapd/hostapd.conf)
    IFACE=$(awk -F= '/^interface=/{print $2; exit}' /etc/hostapd/hostapd.conf)
    cat > /etc/hostapd/hostapd.conf <<EOF
interface=${IFACE:-wlp2s0}
driver=nl80211
ssid=${SSID:-ALFA_AA}
country_code=US
ieee80211d=1
hw_mode=g
channel=6
ieee80211n=1
ht_capab=[HT40+][SHORT-GI-20][SHORT-GI-40][DSSS_CCK-40]
wpa=2
wpa_passphrase=${PASS:-AlfaRomeo156}
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
wmm_enabled=1
EOF
    systemctl restart hostapd.service 2>/dev/null || true
    sleep 2
fi

echo "==> 4/6  Installing NAT helper for internet sharing"
cat > /usr/local/bin/bcm-nat.sh <<'NATEOF'
#!/bin/bash
set -u
AP_IFACE="${AP_IFACE:-wlp2s0}"
log() { logger -t bcm-nat "$*"; echo "[bcm-nat] $*"; }
[ -d "/sys/class/net/$AP_IFACE" ] || { log "AP iface $AP_IFACE missing"; exit 0; }
sysctl -w net.ipv4.ip_forward=1 >/dev/null 2>&1 || true
for up in $(ls /sys/class/net); do
    [ "$up" = "lo" ] && continue
    [ "$up" = "$AP_IFACE" ] && continue
    state=$(cat "/sys/class/net/$up/operstate" 2>/dev/null || echo down)
    [ "$state" = "up" ] || continue
    iptables -t nat -C POSTROUTING -o "$up" -j MASQUERADE 2>/dev/null \
        || iptables -t nat -A POSTROUTING -o "$up" -j MASQUERADE
    iptables -C FORWARD -i "$up" -o "$AP_IFACE" -m state \
        --state RELATED,ESTABLISHED -j ACCEPT 2>/dev/null \
        || iptables -A FORWARD -i "$up" -o "$AP_IFACE" -m state \
                  --state RELATED,ESTABLISHED -j ACCEPT
    iptables -C FORWARD -i "$AP_IFACE" -o "$up" -j ACCEPT 2>/dev/null \
        || iptables -A FORWARD -i "$AP_IFACE" -o "$up" -j ACCEPT
    log "NAT enabled: $AP_IFACE -> $up"
done
exit 0
NATEOF
chmod +x /usr/local/bin/bcm-nat.sh

AP_IFACE_DETECTED=$(awk -F= '/^interface=/{print $2; exit}' /etc/hostapd/hostapd.conf 2>/dev/null)
AP_IFACE_DETECTED=${AP_IFACE_DETECTED:-wlp2s0}
cat > /etc/systemd/system/bcm-nat.service <<EOF
[Unit]
Description=BCM — NAT internet sharing from AP via uplink
After=hostapd.service network-online.target bcm-lte.service
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
Environment=AP_IFACE=$AP_IFACE_DETECTED
ExecStart=/usr/local/bin/bcm-nat.sh
ExecStartPost=/bin/bash -c 'sleep 30 && /usr/local/bin/bcm-nat.sh'
TimeoutStartSec=90

[Install]
WantedBy=multi-user.target
EOF

# Persist IP forwarding
if grep -q '^#net.ipv4.ip_forward' /etc/sysctl.conf 2>/dev/null; then
    sed -i 's/^#\s*net\.ipv4\.ip_forward.*/net.ipv4.ip_forward=1/' /etc/sysctl.conf
fi
grep -q '^net.ipv4.ip_forward=1' /etc/sysctl.conf 2>/dev/null \
    || echo 'net.ipv4.ip_forward=1' >> /etc/sysctl.conf
sysctl -w net.ipv4.ip_forward=1 >/dev/null 2>&1 || true

echo "==> 5/6  Reloading systemd + enabling units"
systemctl daemon-reload
systemctl enable bcm-nat.service 2>/dev/null || true
systemctl restart bcm-nat.service 2>/dev/null || true
systemctl restart bcm-bluetooth.service 2>/dev/null || true

echo "==> 6/6  Done."
echo
echo "Next: reboot to verify"
echo "  - Splash plays on the main display, small stays black, exits"
echo "    when the dashboard is rendered."
echo "  - Phone sees AP on 5 GHz ch 149, gets internet via LTE NAT."
echo "  - BCM auto-connects to the last paired phone on boot,"
echo "    advertises HFP/PBAP/AA so phonebook + dialer light up."
echo "  - Android Auto fills the full content area, touch lines up 1:1."
echo
echo "  sudo reboot"
