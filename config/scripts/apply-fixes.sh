#!/bin/bash
# One-shot installer for the BT / WiFi / AA / splash / call-audio fixes.
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

# Kiosk/session user: PipeWire + WirePlumber run as this user. Explicit
# BCM_USER wins, then the autologin drop-in setup-x86.sh wrote (the ground
# truth for the kiosk session, also right from a plain root shell), then
# SUDO_USER, then setup-x86.sh's default.
AUTOLOGIN_CONF=/etc/systemd/system/getty@tty1.service.d/autologin.conf
if [ -z "${BCM_USER:-}" ] && [ -f "$AUTOLOGIN_CONF" ]; then
    BCM_USER=$(sed -n 's/.*--autologin[[:space:]]\{1,\}\([^[:space:]]\{1,\}\).*/\1/p' "$AUTOLOGIN_CONF" | head -n1)
fi
if [ -z "${BCM_USER:-}" ] && [ -n "${SUDO_USER:-}" ] && [ "${SUDO_USER}" != "root" ]; then
    BCM_USER=$SUDO_USER
fi
BCM_USER=${BCM_USER:-abner}

echo "==> 1/8  Installing splash player + units"
install -m 0755 "$BCM_DIR/config/scripts/bcm-splash-play.sh" /usr/local/bin/bcm-splash-play.sh
install -m 0644 "$BCM_DIR/config/systemd/bcm-splash-main.service" /etc/systemd/system/bcm-splash-main.service
install -m 0644 "$BCM_DIR/config/systemd/bcm-splash-small.service" /etc/systemd/system/bcm-splash-small.service
systemctl disable bcm-splash-small.service 2>/dev/null || true
rm -f /etc/systemd/system/multi-user.target.wants/bcm-splash-small.service

echo "==> 2/8  Installing Bluetooth setup (Class=carkit + AlwaysPairable)"
install -m 0755 "$BCM_DIR/config/scripts/bcm-bluetooth-setup.sh" /usr/local/bin/bcm-bluetooth-setup.sh
install -m 0644 "$BCM_DIR/config/systemd/bcm-bluetooth.service" /etc/systemd/system/bcm-bluetooth.service

# Remove leftover Intel-disable artifacts from prior installs (M910q used
# to ship with an Intel 8087 BT chip that we hard-disabled via udev; the
# MT7921 combo card replaces it cleanly so the rule is no longer needed).
rm -f /etc/udev/rules.d/81-bcm-disable-intel-bt.rules
if [ -f /etc/default/bcm-bluetooth ]; then
    sed -i '/^BCM_BT_KEEP_INTERNAL=/d;/^BCM_BT_PREFER_INTERNAL=/d' /etc/default/bcm-bluetooth
fi
udevadm control --reload-rules 2>/dev/null || true

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
    # [Policy] — AutoEnable powers the adapter on at boot; Reconnect* makes
    # bluetoothd re-establish the audio/HFP profiles to a trusted device the
    # moment the link drops (phone back in range / out of doze) on its own.
    for kv in "AutoEnable=true" "ReconnectAttempts=7" \
              "ReconnectIntervals=1,2,4,8,16,32,64"; do
        key=${kv%%=*}
        if grep -qE "^[#[:space:]]*${key}[[:space:]]*=" /etc/bluetooth/main.conf; then
            sed -i "s|^[#[:space:]]*${key}[[:space:]]*=.*|${kv}|" /etc/bluetooth/main.conf
        elif grep -q '^\[Policy\]' /etc/bluetooth/main.conf; then
            sed -i "/^\[Policy\]/a ${kv}" /etc/bluetooth/main.conf
        else
            printf '\n[Policy]\n%s\n' "$kv" >> /etc/bluetooth/main.conf
        fi
    done
fi
systemctl restart bluetooth.service 2>/dev/null || true

echo "==> 3/8  Writing hostapd config (5 GHz ch149, country US)"
# MT7921 exposes UNII-3 (ch149-165) at 30 dBm with the worldwide regdom
# baked into firmware-mediatek, so the AP comes up on 5 GHz without any
# regdom tricks. AA Wireless gets clean H.264 throughput over 80 MHz here.
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
ieee80211h=1
hw_mode=a
channel=149
ieee80211n=1
ieee80211ac=1
ht_capab=[HT40+][SHORT-GI-20][SHORT-GI-40]
vht_capab=[SHORT-GI-80][MAX-MPDU-11454]
vht_oper_chwidth=1
vht_oper_centr_freq_seg0_idx=155
wpa=2
wpa_passphrase=${PASS:-AlfaRomeo156}
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
wmm_enabled=1
EOF
    systemctl restart hostapd.service 2>/dev/null || true
    sleep 2
fi

echo "==> 4/8  Installing NAT helper for internet sharing"
# Tracked script, the same file setup-x86.sh installs (it used to be a
# heredoc here that had drifted: operstate==up only, so LTE (operstate
# unknown) was skipped, and bnep*/p2p-* were NAT-ed like real uplinks).
install -m 0755 "$BCM_DIR/config/scripts/bcm-nat.sh" /usr/local/bin/bcm-nat.sh

AP_IFACE_DETECTED=$(awk -F= '/^interface=/{print $2; exit}' /etc/hostapd/hostapd.conf 2>/dev/null)
AP_IFACE_DETECTED=${AP_IFACE_DETECTED:-wlp2s0}
# No ExecStartPost with a half-minute sleep here (an older revision had
# one): it held bcm-nat.service in "activating" for 30 s on every boot,
# at the top of systemd-analyze blame.
# Uplinks that come up late are handled by bcm-nat-late.timer below,
# exactly as setup-x86.sh does it.
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
TimeoutStartSec=20

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/bcm-nat-late.service <<EOF
[Unit]
Description=BCM — re-apply NAT once uplink has settled
After=bcm-nat.service

[Service]
Type=oneshot
Environment=AP_IFACE=$AP_IFACE_DETECTED
ExecStart=/usr/local/bin/bcm-nat.sh
EOF
cat > /etc/systemd/system/bcm-nat-late.timer <<EOF
[Unit]
Description=BCM — fire bcm-nat once 30 s after boot

[Timer]
OnBootSec=30s
Unit=bcm-nat-late.service

[Install]
WantedBy=timers.target
EOF

# Persist IP forwarding
if grep -q '^#net.ipv4.ip_forward' /etc/sysctl.conf 2>/dev/null; then
    sed -i 's/^#\s*net\.ipv4\.ip_forward.*/net.ipv4.ip_forward=1/' /etc/sysctl.conf
fi
grep -q '^net.ipv4.ip_forward=1' /etc/sysctl.conf 2>/dev/null \
    || echo 'net.ipv4.ip_forward=1' >> /etc/sysctl.conf
sysctl -w net.ipv4.ip_forward=1 >/dev/null 2>&1 || true

echo "==> 5/8  Audio for calls and AA voice (oFono, WirePlumber, D-Bus policy)"
# ofono = the HFP backend (51-bcm-hfp-ofono.conf). Missing ofonod means calls
# never reach the head unit, so check it loudly instead of `|| true`.
apt-get install -y ofono || true
if command -v ofonod >/dev/null 2>&1 || [ -x /usr/sbin/ofonod ]; then
    echo "    ofonod: $(command -v ofonod 2>/dev/null || echo /usr/sbin/ofonod)"
else
    echo "    WARNING: ofono (ofonod) is NOT installed — phone calls will NOT reach the head unit."
    echo "             Fix: sudo apt-get install ofono, then re-run this script."
fi

# The drop-ins use WirePlumber 0.5 syntax; 0.4 ignores them silently.
WP_VER=$(wireplumber --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+(\.[0-9]+)?' | head -n1)
if [ -z "$WP_VER" ]; then
    echo "    WARNING: wireplumber --version gave no version — cannot check >= 0.5"
else
    WP_MAJOR=${WP_VER%%.*}
    WP_MINOR=${WP_VER#*.}
    WP_MINOR=${WP_MINOR%%.*}
    if [ "$WP_MAJOR" -eq 0 ] && [ "$WP_MINOR" -lt 5 ]; then
        echo "    WARNING: WirePlumber $WP_VER < 0.5 — 51-bcm-hfp-ofono.conf is ignored, the dialer will not work."
    else
        echo "    WirePlumber $WP_VER"
    fi
fi

install -d /etc/systemd/system/ofono.service.d
install -m 0644 "$BCM_DIR/config/systemd/ofono.service.d/10-bcm-hfp-only.conf" \
    /etc/systemd/system/ofono.service.d/10-bcm-hfp-only.conf
install -d /etc/wireplumber/wireplumber.conf.d
install -m 0644 "$BCM_DIR/config/wireplumber/wireplumber.conf.d/51-bcm-hfp-ofono.conf" \
    /etc/wireplumber/wireplumber.conf.d/51-bcm-hfp-ofono.conf

# D-Bus policy: WirePlumber (as $BCM_USER) registers oFono's
# HandsfreeAudioAgent on org.ofono; the stock ofono.conf only allows root, so
# the registration was rejected ("Register() failed" / "Rejecting" in the
# journal) and calls got no audio. The user name is validated before it goes
# into the XML.
if [[ "$BCM_USER" =~ ^[A-Za-z_][A-Za-z0-9_.-]*$ ]]; then
    install -d /etc/dbus-1/system.d
    cat > /etc/dbus-1/system.d/bcm-ofono-pipewire.conf <<EOF
<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-BUS Bus Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<!-- Installed by BCM (setup-x86.sh / apply-fixes.sh). WirePlumber runs as
     "$BCM_USER" and, with bluez5.hfphsp-backend = "ofono"
     (51-bcm-hfp-ofono.conf), registers oFono's HandsfreeAudioAgent on the
     system bus. The stock ofono.conf allows that only for root, so without
     this file the agent registration is rejected and calls get no audio.
     Remove this file to revert. -->
<busconfig>
  <policy user="$BCM_USER">
    <allow send_destination="org.ofono"/>
  </policy>
</busconfig>
EOF
    chmod 0644 /etc/dbus-1/system.d/bcm-ofono-pipewire.conf
    # dbus-daemon notices new policy files by itself; reload to be sure.
    systemctl reload dbus.service 2>/dev/null || true
else
    echo "    WARNING: BCM_USER='$BCM_USER' is not a valid user name — D-Bus policy NOT installed"
fi

systemctl daemon-reload
systemctl enable ofono 2>/dev/null || true
systemctl restart ofono 2>/dev/null || true
# Restart the user's audio stack so the drop-in and the policy apply now ...
systemctl --user -M "$BCM_USER@" restart wireplumber pipewire pipewire-pulse 2>/dev/null || true
# ... wait (max ~5 s) until WirePlumber has created the ALSA sinks again: BCM's
# wait_for_pipewire() only checks that `wpctl status` answers, so a BCM that
# starts too early logs "No hardware audio sinks found" and runs without the
# EQ / output selection ...
BCM_UID=$(id -u "$BCM_USER" 2>/dev/null || true)
if [ -n "$BCM_UID" ]; then
    for _ in $(seq 1 10); do
        if sudo -u "$BCM_USER" LC_ALL=C "XDG_RUNTIME_DIR=/run/user/$BCM_UID" \
                wpctl status --name 2>/dev/null | grep -q 'alsa_output\.'; then
            break
        fi
        sleep 0.5
    done
fi
# ... and then bcm-headunit: its EQ filter-chain is a `pipewire -c` child BCM
# does not supervise. It lost its PipeWire connection with the restart above,
# and without a BCM restart there is no EQ sink (= no sound). try-restart:
# only if it is running — a head unit stopped on purpose (or left to the
# ignition watcher) stays stopped.
systemctl try-restart bcm-headunit.service 2>/dev/null || true

echo "==> 6/8  Car phone tools (adb for modules.car_phone)"
# adb = the car phone module (src/network/car_phone.py): USB tethering, GPS
# forward, battery. Checked like ofono above — a missing adb is said
# loudly, the module then only shows "brak adb". Debian package only.
apt-get install -y adb || true
if command -v adb >/dev/null 2>&1; then
    echo "    adb: $(command -v adb)"
else
    echo "    WARNING: adb is NOT installed — the car phone (modules.car_phone) will NOT work."
    echo "             Fix: sudo apt-get install adb, then re-run this script."
fi
# bcm-timesync.sh now leaves /run/bcm-timesync.ok on success; car_phone
# reads it to decide whether the phone's clock may be used (plan D1).
if [ -f /usr/local/bin/bcm-timesync.sh ]; then
    install -m 0755 "$BCM_DIR/config/scripts/bcm-timesync.sh" /usr/local/bin/bcm-timesync.sh
fi

echo "==> 7/8  Reloading systemd + enabling units"
systemctl daemon-reload
systemctl enable bcm-nat.service 2>/dev/null || true
systemctl enable bcm-nat-late.timer 2>/dev/null || true
systemctl restart bcm-nat.service 2>/dev/null || true
systemctl start bcm-nat-late.timer 2>/dev/null || true
systemctl restart bcm-bluetooth.service 2>/dev/null || true

echo "==> 8/8  Done."
echo
echo "Next: reboot to verify"
echo "  - Splash plays on the main display, small stays black, exits"
echo "    when the dashboard is rendered."
echo "  - Phone sees AP on 5 GHz ch 149, gets internet via LTE NAT."
echo "  - BCM auto-connects to the last paired phone on boot,"
echo "    advertises HFP/PBAP/AA so phonebook + dialer light up."
echo "  - Android Auto fills the full content area, touch lines up 1:1."
echo "  - Calls: an incoming call switches the dashboard to the A8 overlay"
echo "    (answer / reject; on the Android Auto screen AA shows its own)."
echo "    Audio problems: sudo bash $BCM_DIR/tools/bcm-audio-diag.sh"
echo
echo "  sudo reboot"
