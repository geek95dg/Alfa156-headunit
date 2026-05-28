#!/bin/bash
# BCM x86 full setup — clean reset + install on Lenovo M910q
#
# This script does EVERYTHING: cleans old configs, installs system
# packages, creates the venv, installs services, sets up kiosk,
# configures suspend, and sets up WiFi AP.
#
# Usage:
#   cd /opt/bcm
#   sudo bash config/scripts/setup-x86.sh
#
# The script is idempotent — safe to run again after fixing issues.
set -euo pipefail

# ──── USER CONFIG ────────────────────────────────────────────────
# Change these if your hardware differs from the M910q reference.
BCM_USER="${SUDO_USER:-abner}"
BCM_HOME=$(eval echo "~$BCM_USER")
BCM_DIR="/opt/bcm"

# Display outputs (find with: for f in /sys/class/drm/card*-*/status; do echo "$f: $(cat $f)"; done)
MAIN_OUTPUT="HDMI-1"
SMALL_OUTPUT="HDMI-2"
TOUCH_DEVICE="QDtech MPI5001"

# Main display resolution (used for splash generation + touch calibration)
MAIN_W=1024
MAIN_H=600
SMALL_W=800
SMALL_H=480

# WiFi AP — 5 GHz channel 149, country US. MT7921 (mt7921e) exposes
# UNII-3 (ch149-165) at 30 dBm with the worldwide regdom in
# firmware-mediatek, so AP/P2P-GO on 5 GHz works first try.
WIFI_IFACE="wlp2s0"
WIFI_SSID="ALFA_AA"
WIFI_PASS="AlfaRomeo156"
# Default mode is wpa_supplicant P2P-GO (Wi-Fi Direct), driven by
# src/multimedia/wifi_ap.py — system hostapd is left disabled so the
# Python process owns the radio. The hostapd fallback below is kept
# for older deployments that flip wifi.mode back to "hostapd" in YAML.
WIFI_CHANNEL="149"
WIFI_HW_MODE="a"
WIFI_COUNTRY="US"
# ─────────────────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

step() { echo -e "\n${GREEN}[$1/$TOTAL] $2${NC}"; }
warn() { echo -e "${YELLOW}  WARN: $1${NC}"; }
fail() { echo -e "${RED}  FAIL: $1${NC}"; exit 1; }
ok()   { echo -e "${GREEN}  OK${NC}"; }

TOTAL=14

if [ "$(id -u)" -ne 0 ]; then
    fail "Run with sudo: sudo bash $0"
fi

if [ ! -f "$BCM_DIR/main.py" ]; then
    fail "$BCM_DIR/main.py not found. Clone the repo first:\n  sudo git clone https://github.com/geek95dg/Alfa156-headunit.git $BCM_DIR"
fi

echo "========================================="
echo " BCM x86 Setup — Lenovo M910q"
echo "========================================="
echo " User:    $BCM_USER"
echo " BCM dir: $BCM_DIR"
echo " Main:    $MAIN_OUTPUT"
echo " Small:   $SMALL_OUTPUT"
echo " Touch:   $TOUCH_DEVICE"
echo " WiFi:    $WIFI_IFACE ($WIFI_SSID)"
echo "========================================="
echo ""

# ─── Phase 1: Cleanup ────────────────────────────────────────────

step 1 "Cleaning old BCM configs..."

for svc in bcm-ignition-watcher bcm-headunit bcm-splash-main bcm-splash-small bcm-kiosk bcm-resume; do
    systemctl stop "$svc" 2>/dev/null || true
    systemctl disable "$svc" 2>/dev/null || true
done
rm -f /etc/systemd/system/bcm-*.service
rm -rf /etc/systemd/system/bcm-splash-main.service.d
rm -rf /etc/systemd/system/bcm-splash-small.service.d
rm -rf /etc/systemd/system/hostapd.service.d
rm -f /etc/modprobe.d/bcm-wifi-regdom.conf
systemctl unmask bcm-kiosk.service 2>/dev/null || true

rm -f "$BCM_HOME/.xinitrc"
rm -f "$BCM_HOME/.bash_profile"
rm -rf /tmp/bcm-chromium-*
rm -rf /etc/systemd/system/getty@tty1.service.d

systemctl stop hostapd dnsmasq 2>/dev/null || true
systemctl disable hostapd dnsmasq 2>/dev/null || true
rm -f /etc/hostapd/hostapd.conf
rm -f /etc/dnsmasq.d/bcm-ap.conf
rm -f /etc/network/interfaces.d/bcm-ap
rm -f /etc/network/interfaces.d/static
rm -f /etc/NetworkManager/conf.d/bcm-unmanage-wifi.conf
rm -f /etc/NetworkManager/conf.d/bcm-unmanage-p2p.conf
rm -f /etc/systemd/network/00-bcm-p2p.network
nmcli device set "$WIFI_IFACE" managed yes 2>/dev/null || true
ip addr flush dev "$WIFI_IFACE" 2>/dev/null || true

rm -f /etc/acpi/events/power-button
rm -f /usr/local/bin/bcm-power-toggle.sh
rm -f /usr/local/bin/bcm-bluetooth-setup.sh
rm -f /usr/local/bin/bcm-lte-up.sh
rm -f /lib/systemd/system-sleep/bcm-sleep
rm -f /etc/systemd/logind.conf.d/bcm-power.conf
rm -f /etc/systemd/system/bcm-lte.service
# leave /etc/bcm/lte.conf — user may have edited APN for non-Orange SIM

rm -f /etc/chromium/policies/managed/bcm.json
rm -f /etc/X11/Xwrapper.config
rm -rf "$BCM_DIR/.venv"

systemctl daemon-reload
ok

# ─── Phase 2: System packages ────────────────────────────────────

step 2 "Installing system packages..."

apt-get update -qq

apt-get install -y -qq \
    python3 python3-venv python3-full python3-dev python3-serial \
    python3-dbus python3-gi \
    git curl wget \
    xserver-xorg xinit x11-xserver-utils xinput xdotool \
    xvfb matchbox-window-manager \
    unclutter chromium \
    intel-media-va-driver vainfo libva-drm2 \
    pipewire pipewire-pulse wireplumber alsa-utils mpv \
    gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad gstreamer1.0-libav \
    firmware-mediatek bluez bluez-tools rfkill network-manager modemmanager hostapd dnsmasq iw wireless-tools wpasupplicant iptables \
    ffmpeg v4l-utils \
    acpid \
    zram-tools \
    fonts-dejavu-core

# zram config
echo -e 'ALGO=lz4\nPERCENT=50' > /etc/default/zramswap
systemctl enable zramswap 2>/dev/null || true

ok

# ─── Phase 3: Python venv ────────────────────────────────────────

step 3 "Creating Python venv + installing dependencies..."

chown -R "$BCM_USER:$BCM_USER" "$BCM_DIR"

# Debian 13 sometimes has issues with python3 -m venv if the
# python3 binary symlink is funky. Use the versioned binary directly.
PYTHON_BIN=""
for candidate in python3.13 python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
        PYTHON_BIN=$(command -v "$candidate")
        break
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    fail "No python3 found even after apt install. Check: dpkg -l | grep python3"
fi

echo "  Using: $PYTHON_BIN ($(${PYTHON_BIN} --version 2>&1))"

# Create venv as the BCM user, not as root.
# --system-site-packages is required for python3-dbus + python3-gi:
# the BlueZ pairing agent registers via dbus-python on the system bus,
# and dbus-python is impractical to install via pip (it builds C extensions
# against libdbus-1-dev + glib). Without this flag, src/multimedia/bluetooth.py
# logs "dbus-python not available — pairing agent disabled" and the BCM
# popup for phone-initiated pair confirmation never appears.
su - "$BCM_USER" -c "cd $BCM_DIR && $PYTHON_BIN -m venv --system-site-packages .venv" || {
    warn "venv creation failed with $PYTHON_BIN, trying virtualenv fallback..."
    apt-get install -y -qq python3-virtualenv
    su - "$BCM_USER" -c "cd $BCM_DIR && virtualenv --system-site-packages --python=$PYTHON_BIN .venv"
}

if [ ! -x "$BCM_DIR/.venv/bin/python" ]; then
    fail "venv created but $BCM_DIR/.venv/bin/python not found.\n  Debug: ls -la $BCM_DIR/.venv/bin/"
fi

su - "$BCM_USER" -c "cd $BCM_DIR && source .venv/bin/activate && pip install --quiet -r requirements.txt -r requirements-x86.txt"
ok

# ─── Phase 4: Vendor assets ──────────────────────────────────────

step 4 "Downloading vendor assets (Tailwind, Leaflet)..."

su - "$BCM_USER" -c "cd $BCM_DIR && bash config/scripts/download-vendor-assets.sh" || {
    warn "Vendor download failed — no internet? You can retry later:\n    bash /opt/bcm/config/scripts/download-vendor-assets.sh"
}
ok

# ─── Phase 5: Generate splash videos if missing ──────────────────

step 5 "Checking splash videos..."

SPLASH_DIR="$BCM_DIR/assets/splash"
mkdir -p "$SPLASH_DIR"

if [ -f "$SPLASH_DIR/main.mp4" ] && [ -f "$SPLASH_DIR/small.mp4" ]; then
    echo "  Splash videos already exist — skipping generation."
else
    echo "  Generating placeholder splash videos with ffmpeg..."

    if ! command -v ffmpeg >/dev/null 2>&1; then
        warn "ffmpeg not found — splash videos not generated."
    else
        FONT_FILE="/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

        # Main splash (1024x600, 8s, dark background + text + fade)
        if [ ! -f "$SPLASH_DIR/main.mp4" ]; then
            if [ -f "$FONT_FILE" ]; then
                MAIN_VF="drawtext=fontfile=${FONT_FILE}:text='ALFA ROMEO 156':fontcolor=white:fontsize=48:x=(w-text_w)/2:y=(h-text_h)/2-30,drawtext=fontfile=${FONT_FILE}:text='BCM v8.5':fontcolor=0xcccccc:fontsize=24:x=(w-text_w)/2:y=(h-text_h)/2+30,fade=t=in:st=0:d=1,fade=t=out:st=7:d=1"
            else
                warn "No font found — splash will be plain (no text)"
                MAIN_VF="fade=t=in:st=0:d=1,fade=t=out:st=7:d=1"
            fi
            ffmpeg -y -f lavfi \
                -i "color=c=0x1a1a2e:s=${MAIN_W}x${MAIN_H}:d=8:r=30" \
                -f lavfi -i "anullsrc=r=44100:cl=stereo" \
                -vf "$MAIN_VF" \
                -c:v libx264 -preset fast -crf 23 \
                -c:a aac -b:a 64k -ac 2 \
                -t 8 -movflags +faststart -shortest \
                "$SPLASH_DIR/main.mp4" 2>/tmp/bcm-ffmpeg-main.log && \
                echo "  Created: main.mp4 (${MAIN_W}x${MAIN_H}, 8s)" || {
                warn "drawtext failed — generating plain video (see /tmp/bcm-ffmpeg-main.log)"
                ffmpeg -y -f lavfi \
                    -i "color=c=0x1a1a2e:s=${MAIN_W}x${MAIN_H}:d=8:r=30" \
                    -f lavfi -i "anullsrc=r=44100:cl=stereo" \
                    -c:v libx264 -preset fast -crf 23 \
                    -c:a aac -b:a 64k -ac 2 \
                    -t 8 -movflags +faststart -shortest \
                    "$SPLASH_DIR/main.mp4" 2>/dev/null && \
                    echo "  Created: main.mp4 (plain, no text)" || \
                    warn "Could not generate any main splash video"
            }
        fi

        # Small splash (800x480, 5s, silent)
        if [ ! -f "$SPLASH_DIR/small.mp4" ]; then
            if [ -f "$FONT_FILE" ]; then
                SMALL_VF="drawtext=fontfile=${FONT_FILE}:text='ALFA ROMEO':fontcolor=white:fontsize=32:x=(w-text_w)/2:y=(h-text_h)/2,fade=t=in:st=0:d=1,fade=t=out:st=4:d=1"
            else
                SMALL_VF="fade=t=in:st=0:d=1,fade=t=out:st=4:d=1"
            fi
            ffmpeg -y -f lavfi \
                -i "color=c=0x1a1a2e:s=${SMALL_W}x${SMALL_H}:d=5:r=30" \
                -vf "$SMALL_VF" \
                -c:v libx264 -preset fast -crf 23 -an \
                -t 5 -movflags +faststart \
                "$SPLASH_DIR/small.mp4" 2>/tmp/bcm-ffmpeg-small.log && \
                echo "  Created: small.mp4 (${SMALL_W}x${SMALL_H}, 5s)" || {
                warn "drawtext failed — generating plain video (see /tmp/bcm-ffmpeg-small.log)"
                ffmpeg -y -f lavfi \
                    -i "color=c=0x1a1a2e:s=${SMALL_W}x${SMALL_H}:d=5:r=30" \
                    -c:v libx264 -preset fast -crf 23 -an \
                    -t 5 -movflags +faststart \
                    "$SPLASH_DIR/small.mp4" 2>/dev/null && \
                    echo "  Created: small.mp4 (plain, no text)" || \
                    warn "Could not generate any small splash video"
            }
        fi
    fi
fi

chown -R "$BCM_USER:$BCM_USER" "$SPLASH_DIR"
ok

# ─── Phase 6: Systemd services ───────────────────────────────────

step 6 "Installing systemd services..."

cp "$BCM_DIR/config/systemd/bcm-headunit-x86.service" /etc/systemd/system/bcm-headunit.service
cp "$BCM_DIR/config/systemd/bcm-ignition-watcher.service" /etc/systemd/system/
cp "$BCM_DIR/config/systemd/bcm-splash-main.service" /etc/systemd/system/
cp "$BCM_DIR/config/systemd/bcm-splash-small.service" /etc/systemd/system/
cp "$BCM_DIR/config/systemd/bcm-resume.service" /etc/systemd/system/

# Splash player helper — single process drives both connectors via
# gst-launch + two kmssinks (one DRM master, no race).
install -m 0755 "$BCM_DIR/config/scripts/bcm-splash-play.sh" /usr/local/bin/bcm-splash-play.sh

systemctl mask bcm-kiosk.service 2>/dev/null || true

# Override DRM connectors — translate xrandr names to DRM names
# xrandr: HDMI-1 → DRM: HDMI-A-1, xrandr: DP-1 → DRM: DP-1 (same)
drm_name() {
    local name="$1"
    case "$name" in
        HDMI-[0-9]*) echo "HDMI-A-${name#HDMI-}" ;;
        *) echo "$name" ;;
    esac
}
DRM_MAIN=$(drm_name "$MAIN_OUTPUT")
DRM_SMALL=$(drm_name "$SMALL_OUTPUT")

# bcm-splash-main now owns both displays (gst tee → two kmssinks), so
# we feed it both connector names. bcm-splash-small is left disabled
# to avoid a second process fighting for DRM master.
mkdir -p /etc/systemd/system/bcm-splash-main.service.d
cat > /etc/systemd/system/bcm-splash-main.service.d/connector.conf <<EOF
[Service]
Environment=BCM_SPLASH_DRM_MAIN=$DRM_MAIN
Environment=BCM_SPLASH_DRM_SMALL=$DRM_SMALL
EOF

# Keep the unit file installed for reference but make sure it doesn't
# auto-start (legacy enable from previous setups must be cleared).
systemctl disable bcm-splash-small 2>/dev/null || true
rm -f /etc/systemd/system/multi-user.target.wants/bcm-splash-small.service

systemctl daemon-reload
systemctl enable bcm-ignition-watcher bcm-splash-main bcm-resume
ok

# ─── Phase 6: Kiosk (autologin + X + xinitrc) ────────────────────

step 7 "Setting up kiosk (autologin + X11 + xinitrc)..."

# X11 wrapper
mkdir -p /etc/X11
cat > /etc/X11/Xwrapper.config <<EOF
allowed_users=anybody
needs_root_rights=yes
EOF

# Autologin on tty1
mkdir -p /etc/systemd/system/getty@tty1.service.d
cat > /etc/systemd/system/getty@tty1.service.d/autologin.conf <<EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin $BCM_USER --noclear %I \$TERM
EOF

# .bash_profile — start X on tty1
cat > "$BCM_HOME/.bash_profile" <<'BASHEOF'
if [ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then
    # Wait for splash to START (it may not be active yet when autologin runs)
    for _w in $(seq 1 50); do
        systemctl is-active --quiet bcm-splash-main.service 2>/dev/null && break
        sleep 0.1
    done
    # Wait for splash to FINISH (mpv releases DRM when Flask is ready)
    while systemctl is-active --quiet bcm-splash-main.service 2>/dev/null; do
        sleep 1
    done
    exec startx -- -nocursor
fi
BASHEOF
chown "$BCM_USER:$BCM_USER" "$BCM_HOME/.bash_profile"

# xinitrc — write directly with user's display config baked in
cat > "$BCM_HOME/.xinitrc" <<'XINITRC'
#!/bin/sh
# BCM kiosk — generated by setup-x86.sh
# ──── Display config (edit if outputs are swapped) ────
XINITRC

# Inject the actual values (not escaped, written literally)
cat >> "$BCM_HOME/.xinitrc" <<XINITRC_VARS
MAIN_OUTPUT="$MAIN_OUTPUT"
SMALL_OUTPUT="$SMALL_OUTPUT"
TOUCH_DEVICE="$TOUCH_DEVICE"
XINITRC_VARS

cat >> "$BCM_HOME/.xinitrc" <<'XINITRC'

xset s off
xset -dpms
xset s noblank
unclutter -idle 0.5 -root &

sleep 1

# Detect main display resolution
MAIN_W=$(xrandr | grep "^${MAIN_OUTPUT} " | grep -oP '\d+(?=x)' | head -1)
MAIN_H=$(xrandr | grep "^${MAIN_OUTPUT} " | grep -oP 'x\K\d+' | head -1)
MAIN_W=${MAIN_W:-1024}
MAIN_H=${MAIN_H:-600}

# Arrange: main at 0,0 — small to the right
xrandr --output "$MAIN_OUTPUT" --primary --auto --pos 0x0
if xrandr | grep -q "^${SMALL_OUTPUT} connected"; then
    xrandr --output "$SMALL_OUTPUT" --right-of "$MAIN_OUTPUT" --auto
fi

# ──── Touch mapping ────
if [ -n "$TOUCH_DEVICE" ]; then
    sleep 1
    TLOG="/tmp/bcm-xinput.log"
    echo "=== Touch setup $(date) ===" > "$TLOG"
    echo "MAIN_OUTPUT=$MAIN_OUTPUT TOUCH_DEVICE=$TOUCH_DEVICE" >> "$TLOG"
    xinput list >> "$TLOG" 2>&1
    xrandr >> "$TLOG" 2>&1

    TOUCH_ID=$(xinput list --id-only "$TOUCH_DEVICE" 2>/dev/null || true)
    if [ -n "$TOUCH_ID" ]; then
        echo "TOUCH_ID=$TOUCH_ID" >> "$TLOG"
        xinput map-to-output "$TOUCH_ID" "$MAIN_OUTPUT" 2>>"$TLOG" && \
            echo "Touch mapped: id=$TOUCH_ID -> $MAIN_OUTPUT" | tee -a "$TLOG" || \
            echo "WARN: map-to-output failed" | tee -a "$TLOG"
        xinput list-props "$TOUCH_ID" >> "$TLOG" 2>&1
    else
        echo "Touch device '$TOUCH_DEVICE' not found" | tee -a "$TLOG"
        echo "Available:" >> "$TLOG"
        xinput list --name-only >> "$TLOG" 2>&1
    fi
fi

# Wait for Flask
for i in $(seq 1 90); do
    curl -sf http://localhost:5002 >/dev/null && break
    sleep 1
done

rm -rf /tmp/bcm-chromium-main /tmp/bcm-chromium-small

# Main display — BCM dashboard
chromium --app=http://localhost:5002 \
    --window-size=${MAIN_W},${MAIN_H} --window-position=0,0 \
    --noerrdialogs --disable-infobars \
    --disable-features=TranslateUI --no-first-run \
    --disable-session-crashed-bubble \
    --user-data-dir=/tmp/bcm-chromium-main &

# Small display
if xrandr | grep -q "^${SMALL_OUTPUT} connected"; then
    sleep 2
    S_W=$(xrandr | grep "^${SMALL_OUTPUT} " | grep -oP '\d+(?=x)' | head -1)
    S_H=$(xrandr | grep "^${SMALL_OUTPUT} " | grep -oP 'x\K\d+' | head -1)
    S_W=${S_W:-800}; S_H=${S_H:-480}
    chromium --app=http://localhost:5003 \
        --window-size=${S_W},${S_H} --window-position=${MAIN_W},0 \
        --noerrdialogs --disable-infobars \
        --disable-features=TranslateUI --no-first-run \
        --disable-session-crashed-bubble \
        --user-data-dir=/tmp/bcm-chromium-small &
fi

wait
XINITRC
chown "$BCM_USER:$BCM_USER" "$BCM_HOME/.xinitrc"
chmod +x "$BCM_HOME/.xinitrc"

# Chromium policy
mkdir -p /etc/chromium/policies/managed
cp "$BCM_DIR/config/scripts/chromium-policy.json" /etc/chromium/policies/managed/bcm.json

systemctl daemon-reload
ok

# ─── Phase 7: Power button → suspend ─────────────────────────────

step 8 "Configuring power button → suspend (acpid)..."

mkdir -p /etc/acpi/events
cat > /etc/acpi/events/power-button <<EOF
event=button/power
action=/usr/local/bin/bcm-power-toggle.sh
EOF

cp "$BCM_DIR/config/scripts/bcm-power-toggle.sh" /usr/local/bin/
chmod +x /usr/local/bin/bcm-power-toggle.sh

# system-sleep hook — runs on every suspend regardless of trigger.
# Disables wake sources (USB, serio, HDA) and unbinds LTE before S3,
# rebinds + restarts headunit on resume. Replaces the old bcm-resume
# logic which only fired on systemd suspend.target activation.
mkdir -p /lib/systemd/system-sleep
cp "$BCM_DIR/config/scripts/bcm-sleep-hook.sh" /lib/systemd/system-sleep/bcm-sleep
chmod +x /lib/systemd/system-sleep/bcm-sleep

# Tell logind to ignore power button (let acpid handle it)
mkdir -p /etc/systemd/logind.conf.d
cat > /etc/systemd/logind.conf.d/bcm-power.conf <<EOF
[Login]
HandlePowerKey=ignore
HandleSuspendKey=ignore
HandleLidSwitch=ignore
EOF

systemctl enable acpid
systemctl restart systemd-logind 2>/dev/null || true
ok

# ─── Phase 8: WiFi Access Point ──────────────────────────────────

step 9 "Setting up WiFi AP ($WIFI_SSID on $WIFI_IFACE)..."

# Check if interface exists
if ! ip link show "$WIFI_IFACE" >/dev/null 2>&1; then
    warn "$WIFI_IFACE not found — skipping WiFi AP setup."
    warn "Available interfaces: $(ip -o link show | awk -F': ' '{print $2}' | tr '\n' ' ')"
else
    # Release from NetworkManager
    nmcli device set "$WIFI_IFACE" managed no 2>/dev/null || true

    mkdir -p /etc/NetworkManager/conf.d
    cat > /etc/NetworkManager/conf.d/bcm-unmanage-wifi.conf <<EOF
[keyfile]
unmanaged-devices=interface-name:$WIFI_IFACE
EOF

    # Wi-Fi Direct P2P group interfaces (p2p-*) need to be unmanaged
    # too — without this NetworkManager + systemd-networkd toggle the
    # link UP/DOWN, which wpa_supplicant interprets as the group going
    # away and tears the P2P-GO down. Only relevant if you flip
    # wifi.mode to p2p_go in YAML; harmless otherwise.
    cat > /etc/NetworkManager/conf.d/bcm-unmanage-p2p.conf <<'EOF'
[keyfile]
unmanaged-devices=interface-name:p2p-*
EOF
    mkdir -p /etc/systemd/network
    cat > /etc/systemd/network/00-bcm-p2p.network <<'EOF'
[Match]
Name=p2p-*

[Link]
Unmanaged=yes
EOF

    # Default regdom hint at module load. MT7921 doesn't need it (the
    # firmware-mediatek worldwide regdom already opens UNII-3 at 30 dBm),
    # but cfg80211 reads this on first attach so older deployments stay
    # consistent.
    mkdir -p /etc/modprobe.d
    echo "options cfg80211 ieee80211_regdom=US" > /etc/modprobe.d/cfg80211.conf

    # hostapd — 5 GHz ch149 (UNII-3), 80 MHz VHT. MT7921 supports up to
    # 802.11ac on this PHY, which is what AA Wireless wants for clean
    # H.264 throughput.
    mkdir -p /etc/hostapd
    cat > /etc/hostapd/hostapd.conf <<EOF
interface=$WIFI_IFACE
driver=nl80211
ssid=$WIFI_SSID
hw_mode=$WIFI_HW_MODE
channel=$WIFI_CHANNEL
country_code=$WIFI_COUNTRY
ieee80211d=1
ieee80211h=1
ieee80211n=1
ieee80211ac=1
ht_capab=[HT40+][SHORT-GI-20][SHORT-GI-40]
vht_capab=[SHORT-GI-80][MAX-MPDU-11454]
vht_oper_chwidth=1
vht_oper_centr_freq_seg0_idx=155
wmm_enabled=1
wpa=2
wpa_passphrase=$WIFI_PASS
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
EOF

    mkdir -p /etc/default
    cat > /etc/default/hostapd <<EOF
DAEMON_CONF="/etc/hostapd/hostapd.conf"
EOF

    # dnsmasq — bind-interfaces is critical
    mkdir -p /etc/dnsmasq.d
    cat > /etc/dnsmasq.d/bcm-ap.conf <<EOF
interface=$WIFI_IFACE
bind-interfaces
dhcp-range=192.168.44.10,192.168.44.50,255.255.255.0,24h
EOF

    # Static IP via interfaces.d
    mkdir -p /etc/network/interfaces.d
    cat > /etc/network/interfaces.d/bcm-ap <<EOF
auto $WIFI_IFACE
iface $WIFI_IFACE inet static
    address 192.168.44.1
    netmask 255.255.255.0
EOF

    # rfkill unblock — the WiFi card ships soft-blocked on first boot
    # of the M910q (same as BT). hostapd start succeeds rc=0 on a
    # blocked radio but the AP never actually broadcasts.
    rfkill unblock all 2>/dev/null || true
    rfkill unblock wifi 2>/dev/null || true

    # Apply now
    ip addr flush dev "$WIFI_IFACE" 2>/dev/null || true
    ip addr add 192.168.44.1/24 dev "$WIFI_IFACE" 2>/dev/null || true
    ip link set "$WIFI_IFACE" up 2>/dev/null || true

    # System hostapd is left DISABLED — the BCM-internal wifi_ap.py
    # owns the radio via wpa_supplicant P2P-GO. Concurrent hostapd
    # would race for the same iface and trigger nl80211 EBUSY. To
    # re-enable the legacy hostapd path, flip wifi.mode back to
    # "hostapd" in bcm_config.yaml and run `systemctl enable
    # hostapd dnsmasq`.
    systemctl disable hostapd 2>/dev/null || true
    systemctl stop hostapd 2>/dev/null || true
    systemctl mask hostapd 2>/dev/null || true

    # Disable simulation mode (no fake OBD/BT/GPS data on real hardware)
    if [ -f "$BCM_DIR/config/bcm_config.yaml" ]; then
        # Add simulation: false under system: section
        if ! grep -q "simulation:" "$BCM_DIR/config/bcm_config.yaml"; then
            sed -i '/^  log_file:/a\  simulation: false' \
                "$BCM_DIR/config/bcm_config.yaml"
        else
            sed -i 's/^\(  simulation:\).*/\1 false/' \
                "$BCM_DIR/config/bcm_config.yaml"
        fi
    fi

    systemctl daemon-reload

    # Verify config is correct
    echo "  hostapd config: SSID=$WIFI_SSID channel=$WIFI_CHANNEL iface=$WIFI_IFACE"
    grep "^channel=" /etc/hostapd/hostapd.conf || warn "No channel in hostapd.conf"

    # Start services now (|| true prevents set -e from killing the script)
    systemctl restart hostapd 2>/dev/null || true
    systemctl restart dnsmasq 2>/dev/null || true
    sleep 2
    if systemctl is-active --quiet hostapd; then
        echo -e "  ${GREEN}hostapd running${NC}"
    else
        # Don't try to "fix" the config by rewriting it — this exact
        # config is the user's tested known-good. If it didn't come up,
        # it's almost always rfkill or a busy interface. Tell the
        # operator and move on; systemd will retry on next boot.
        warn "hostapd not yet active — check: rfkill list, ip link show $WIFI_IFACE"
        warn "and: sudo journalctl -u hostapd -n 20"
    fi

    # ─── Internet sharing — NAT outbound traffic from AP via uplink ──
    # IPv4 forwarding + MASQUERADE so phones connected to the AP can
    # reach the internet through whatever uplink is up (LTE wwx*,
    # ethernet, etc.). Persists across reboots via sysctl + a small
    # bcm-nat oneshot.
    sed -i 's/^[#[:space:]]*net\.ipv4\.ip_forward.*/net.ipv4.ip_forward=1/' \
        /etc/sysctl.conf 2>/dev/null || true
    grep -q '^net.ipv4.ip_forward=1' /etc/sysctl.conf 2>/dev/null \
        || echo 'net.ipv4.ip_forward=1' >> /etc/sysctl.conf
    sysctl -w net.ipv4.ip_forward=1 >/dev/null 2>&1 || true

    # Persistent NAT helper. iptables rules don't survive reboot on
    # Debian by default; this oneshot reapplies them after the AP iface
    # comes up.
    cat > /usr/local/bin/bcm-nat.sh <<'NATEOF'
#!/bin/bash
# Apply MASQUERADE + FORWARD rules between the BCM AP iface and any
# uplink that has a default route. Idempotent — checks before adding.
#
# Why "default route" rather than operstate: the LTE wwan driver (cdc_ether
# on Huawei E3372) reports operstate=unknown even when fully up, so the
# previous "operstate==up" check silently skipped LTE and AP clients
# only reached the internet via ethernet (if attached).
set -u
AP_IFACE="${AP_IFACE:-wlp2s0}"
log() { logger -t bcm-nat "$*"; echo "[bcm-nat] $*"; }
[ -d "/sys/class/net/$AP_IFACE" ] || { log "AP iface $AP_IFACE missing"; exit 0; }
sysctl -w net.ipv4.ip_forward=1 >/dev/null 2>&1 || true

# Enumerate uplinks: any iface with a default route, plus any iface
# whose operstate is up/unknown (covers static-IP ethernet without a
# default route in the table at the moment we run).
declare -A UPLINKS=()
while read -r dev; do
    [ -n "$dev" ] && UPLINKS["$dev"]=1
done < <(ip -4 route show default 2>/dev/null | awk '{for(i=1;i<=NF;i++)if($i=="dev")print $(i+1)}')
for up in $(ls /sys/class/net); do
    [ "$up" = "lo" ] && continue
    [ "$up" = "$AP_IFACE" ] && continue
    state=$(cat "/sys/class/net/$up/operstate" 2>/dev/null || echo down)
    case "$state" in up|unknown) UPLINKS["$up"]=1 ;; esac
done

for up in "${!UPLINKS[@]}"; do
    [ "$up" = "$AP_IFACE" ] && continue
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

    cat > /etc/systemd/system/bcm-nat.service <<EOF
[Unit]
Description=BCM — NAT internet sharing from AP via uplink
After=hostapd.service network-online.target bcm-lte.service
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
Environment=AP_IFACE=$WIFI_IFACE
ExecStart=/usr/local/bin/bcm-nat.sh
TimeoutStartSec=20

[Install]
WantedBy=multi-user.target
EOF

    # Late retry — if an uplink (LTE wwx*) appears AFTER bcm-nat.service
    # has finished, a tiny timer re-runs the script once. Done as a timer
    # so it doesn't block boot the way ExecStartPost+sleep30 did
    # (systemd-analyze blame had bcm-nat.service at 30s on every boot).
    cat > /etc/systemd/system/bcm-nat-late.service <<EOF
[Unit]
Description=BCM — re-apply NAT once uplink has settled
After=bcm-nat.service

[Service]
Type=oneshot
Environment=AP_IFACE=$WIFI_IFACE
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
    systemctl daemon-reload
    systemctl enable bcm-nat.service 2>/dev/null || true
    systemctl enable bcm-nat-late.timer 2>/dev/null || true
    systemctl restart bcm-nat.service 2>/dev/null || true
    systemctl start bcm-nat-late.timer 2>/dev/null || true

    ok
fi

# ─── Phase 9b: LTE modem (Huawei E3372) ──────────────────────────

step 10 "Configuring LTE modem..."

# Install APN profile, dialer script, and systemd unit unconditionally
# — the modem may enumerate after setup and bcm-lte.service will pick
# it up on boot.
mkdir -p /etc/bcm
if [ ! -f /etc/bcm/lte.conf ]; then
    install -m 0644 "$BCM_DIR/config/lte.conf.example" /etc/bcm/lte.conf
    echo "  Installed Orange Polska APN profile → /etc/bcm/lte.conf"
fi
install -m 0755 "$BCM_DIR/config/scripts/bcm-lte-up.sh" /usr/local/bin/
install -m 0644 "$BCM_DIR/config/systemd/bcm-lte.service" /etc/systemd/system/

# LTE goes through NetworkManager + ModemManager — both must be active
# and NM must be allowed to manage the wwan ethernet (wwx*) that MM
# brings up after dialing. Earlier revisions handed wwx to systemd-networkd
# with plain DHCP, which never worked because nothing dialed AT^NDISDUP.
# (modemmanager and network-manager are installed in Phase 2.)
systemctl enable --now ModemManager 2>/dev/null || true
systemctl enable --now NetworkManager 2>/dev/null || true

# Strip any stale unmanage rule for the wwan iface (older setups added one).
if [ -f /etc/NetworkManager/conf.d/bcm-unmanage-wifi.conf ]; then
    sed -i '/^unmanaged-devices=interface-name:ww/d' /etc/NetworkManager/conf.d/bcm-unmanage-wifi.conf
fi
# And drop the legacy systemd-networkd LTE drop-in.
rm -f /etc/systemd/network/50-lte.network

# Avoid wait-online stalling boot if LTE is the only uplink.
systemctl disable systemd-networkd-wait-online.service 2>/dev/null || true
systemctl mask systemd-networkd-wait-online.service 2>/dev/null || true

systemctl daemon-reload
systemctl enable bcm-lte.service 2>/dev/null || true

LTE_IFACE=""
for iface in /sys/class/net/ww*; do
    [ -e "$iface" ] && LTE_IFACE=$(basename "$iface") && break
done

if [ -n "$LTE_IFACE" ] || mmcli -L 2>/dev/null | grep -q Modem; then
    echo "  LTE modem detected; dialing via nmcli + ModemManager..."
    /usr/local/bin/bcm-lte-up.sh 2>&1 | sed 's/^/  /' || true

    sleep 3
    LTE_IFACE=$(ls /sys/class/net/ | grep -m1 '^ww' || true)
    if [ -n "$LTE_IFACE" ] && ip addr show "$LTE_IFACE" 2>/dev/null | grep -q "inet "; then
        LTE_IP=$(ip -4 addr show "$LTE_IFACE" | grep -oP 'inet \K[\d.]+')
        echo -e "  ${GREEN}LTE online: $LTE_IFACE = $LTE_IP${NC}"
    else
        warn "LTE not online yet — check 'journalctl -u bcm-lte' and 'nmcli con show bcm-lte'"
        warn "APN defaults are Orange PL; edit /etc/bcm/lte.conf for other carriers"
    fi
    ok
else
    echo "  No LTE modem found — APN profile installed for next boot."
    ok
fi

# ─── Phase 10: GRUB (silent boot) ────────────────────────────────

step 11 "Configuring silent boot (GRUB)..."

if [ -f /etc/default/grub ]; then
    cp /etc/default/grub /etc/default/grub.bak
    cat > /etc/default/grub <<'EOF'
GRUB_DEFAULT=0
GRUB_TIMEOUT=0
GRUB_HIDDEN_TIMEOUT=0
GRUB_HIDDEN_TIMEOUT_QUIET=true
GRUB_DISTRIBUTOR=""
GRUB_CMDLINE_LINUX_DEFAULT="quiet loglevel=0 vt.global_cursor_default=0 rd.systemd.show_status=false rd.udev.log_level=3 fsck.mode=skip console=tty2"
GRUB_CMDLINE_LINUX=""
GRUB_DISABLE_OS_PROBER=true
EOF
    update-grub 2>/dev/null || true

    # Remove Plymouth if present
    apt-get remove -y -qq plymouth plymouth-themes 2>/dev/null || true
    update-initramfs -u 2>/dev/null || true
fi
ok

# ─── Phase 10: Permissions ────────────────────────────────────────

step 12 "Setting permissions..."

usermod -aG dialout "$BCM_USER" 2>/dev/null || true
usermod -aG video "$BCM_USER" 2>/dev/null || true
usermod -aG audio "$BCM_USER" 2>/dev/null || true
usermod -aG bluetooth "$BCM_USER" 2>/dev/null || true
chown -R "$BCM_USER:$BCM_USER" "$BCM_DIR"

# Auto-power BT adapter on boot AND keep it persistently pairable.
# Without AlwaysPairable=true, BlueZ drops Pairable to false shortly
# after every set, so phones can't initiate pairing reliably.
if [ -f /etc/bluetooth/main.conf ]; then
    # Ensure [General] keys: Class=0x620420 (AV/Carkit + Audio/Telephony/
    # Networking — phones use this to pick the carkit pairing flow),
    # DiscoverableTimeout=0, PairableTimeout=0, AlwaysPairable=true.
    for kv in "Class=0x620420" "DiscoverableTimeout=0" "PairableTimeout=0" "AlwaysPairable=true"; do
        key=${kv%%=*}
        if grep -qE "^[#[:space:]]*${key}[[:space:]]*=" /etc/bluetooth/main.conf; then
            sed -i "s|^[#[:space:]]*${key}[[:space:]]*=.*|${kv}|" /etc/bluetooth/main.conf
        else
            sed -i "/^\[General\]/a ${kv}" /etc/bluetooth/main.conf
        fi
    done
    # AutoEnable in [Policy]
    sed -i 's/^#*AutoEnable.*/AutoEnable=true/' /etc/bluetooth/main.conf
    if ! grep -q "^AutoEnable" /etc/bluetooth/main.conf; then
        sed -i '/^\[Policy\]/a AutoEnable=true' /etc/bluetooth/main.conf
    fi
else
    mkdir -p /etc/bluetooth
    cat > /etc/bluetooth/main.conf <<EOF
[General]
Class=0x620420
DiscoverableTimeout=0
PairableTimeout=0
AlwaysPairable=true

[Policy]
AutoEnable=true
EOF
fi

# A2DP / HFP profile registration needs PipeWire's bluez5 SPA plugin —
# without it bluetoothd answers `Protocol not available` to every A2DP
# connect attempt and pairing handshakes get dropped before the audio
# profile completes. pipewire-audio pulls in the right defaults for
# headset routing.
apt-get install -y libspa-0.2-bluetooth pipewire-audio rfkill iw bluez-obexd 2>/dev/null || true

# Enable Bluetooth (needed for AA wireless pairing)
cp "$BCM_DIR/config/scripts/bcm-bluetooth-setup.sh" /usr/local/bin/
chmod +x /usr/local/bin/bcm-bluetooth-setup.sh
cp "$BCM_DIR/config/systemd/bcm-bluetooth.service" /etc/systemd/system/

# Clean up Intel-8087 disable artifacts from prior installs (the MT7921
# combo card replaces the old internal Intel BT so the udev rule and
# BCM_BT_KEEP_INTERNAL/PREFER_INTERNAL flags are no longer needed).
rm -f /etc/udev/rules.d/81-bcm-disable-intel-bt.rules
if [ -f /etc/default/bcm-bluetooth ]; then
    sed -i '/^BCM_BT_KEEP_INTERNAL=/d;/^BCM_BT_PREFER_INTERNAL=/d' /etc/default/bcm-bluetooth
fi
udevadm control --reload-rules 2>/dev/null || true

# Persist BT rfkill unblock across boots — without this many baremetal
# boards (M910q, OPi 5 Pro) come up with bluetooth soft-blocked even
# though bluetooth.service is enabled, and the BCM "BT" toggle has
# nothing to talk to. systemd-rfkill restores the saved state on
# subsequent boots once we set it once now.
if command -v rfkill >/dev/null 2>&1; then
    rfkill unblock bluetooth 2>/dev/null || true
fi

systemctl daemon-reload
systemctl enable bluetooth bcm-bluetooth 2>/dev/null || true
systemctl enable systemd-rfkill 2>/dev/null || true
# Restart bluetooth so the new main.conf defaults (AlwaysPairable etc.)
# take effect before bcm-bluetooth applies adapter-level settings.
systemctl restart bluetooth 2>/dev/null || true
systemctl restart bcm-bluetooth 2>/dev/null || true
ok

# ─── Phase 11: Quick test ────────────────────────────────────────

step 13 "Testing BCM (headless)..."

TEST_OUTPUT=$(su - "$BCM_USER" -c "cd $BCM_DIR && source .venv/bin/activate && timeout 10 python main.py --platform x86 --config config/bcm_config.yaml --frontend 2>&1" || true)

if echo "$TEST_OUTPUT" | grep -qi "running on\|serving flask\|started"; then
    echo -e "  ${GREEN}Flask started OK${NC}"
else
    warn "Flask may not have started cleanly. Output:"
    echo "$TEST_OUTPUT" | head -5
    echo "  (Non-fatal — may work after reboot with displays connected)"
fi

# ─── Phase 12: Summary ───────────────────────────────────────────

step 14 "Done!"

echo ""
echo "========================================="
echo " Setup complete. Next steps:"
echo "========================================="
echo ""
echo " 1. Reboot:"
echo "    sudo reboot"
echo ""
echo " 2. After reboot, verify:"
echo "    - Splash plays on both displays"
echo "    - Dashboard appears on $MAIN_OUTPUT"
echo "    - Touch works on main display"
echo "    - Power button → suspend (not shutdown)"
echo "    - Phone sees '$WIFI_SSID' and gets IP"
echo ""
echo " To replace placeholder splash with your own:"
echo "    cp your_video.mp4 $BCM_DIR/assets/splash/main.mp4"
echo "    cp your_small.mp4 $BCM_DIR/assets/splash/small.mp4"
echo ""
echo " If displays are swapped, edit the top of"
echo " $BCM_HOME/.xinitrc (MAIN_OUTPUT/SMALL_OUTPUT)"
echo ""
echo " To re-run this script after changes:"
echo "    cd $BCM_DIR && sudo bash config/scripts/setup-x86.sh"
echo "========================================="
