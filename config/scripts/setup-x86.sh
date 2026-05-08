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

# WiFi AP
WIFI_IFACE="wlp2s0"
WIFI_SSID="ALFA_AA"
WIFI_PASS="AlfaRomeo156"
WIFI_CHANNEL="6"
WIFI_COUNTRY="PL"
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
nmcli device set "$WIFI_IFACE" managed yes 2>/dev/null || true
ip addr flush dev "$WIFI_IFACE" 2>/dev/null || true

rm -f /etc/acpi/events/power-button
rm -f /usr/local/bin/bcm-power-toggle.sh
rm -f /etc/systemd/logind.conf.d/bcm-power.conf

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
    git curl wget \
    xserver-xorg xinit x11-xserver-utils xinput xdotool \
    xvfb matchbox-window-manager \
    unclutter chromium \
    intel-media-va-driver vainfo libva-drm2 \
    pipewire pipewire-pulse wireplumber alsa-utils mpv \
    firmware-iwlwifi bluez bluez-tools network-manager hostapd dnsmasq iw wireless-tools \
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

# Create venv as the BCM user, not as root
su - "$BCM_USER" -c "cd $BCM_DIR && $PYTHON_BIN -m venv .venv" || {
    warn "venv creation failed with $PYTHON_BIN, trying virtualenv fallback..."
    apt-get install -y -qq python3-virtualenv
    su - "$BCM_USER" -c "cd $BCM_DIR && virtualenv --python=$PYTHON_BIN .venv"
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

mkdir -p /etc/systemd/system/bcm-splash-main.service.d
cat > /etc/systemd/system/bcm-splash-main.service.d/connector.conf <<EOF
[Service]
Environment=BCM_SPLASH_DRM_MAIN=$DRM_MAIN
EOF

mkdir -p /etc/systemd/system/bcm-splash-small.service.d
cat > /etc/systemd/system/bcm-splash-small.service.d/connector.conf <<EOF
[Service]
Environment=BCM_SPLASH_DRM_SMALL=$DRM_SMALL
EOF

systemctl daemon-reload
systemctl enable bcm-ignition-watcher bcm-splash-main bcm-splash-small bcm-resume
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
    # Wait for splash video to finish before starting X.
    # Splash uses DRM framebuffer — X would steal it and kill the splash.
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

    # hostapd
    mkdir -p /etc/hostapd
    cat > /etc/hostapd/hostapd.conf <<EOF
interface=$WIFI_IFACE
driver=nl80211
ssid=$WIFI_SSID
hw_mode=g
channel=$WIFI_CHANNEL
ieee80211n=1
wpa=2
wpa_passphrase=$WIFI_PASS
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
wpa_pairwise=CCMP
country_code=$WIFI_COUNTRY
wmm_enabled=1
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

    # Set regulatory domain (required for 5GHz channels like 149)
    iw reg set "$WIFI_COUNTRY" 2>/dev/null || true
    mkdir -p /etc/modprobe.d
    echo "options cfg80211 ieee80211_regdom=$WIFI_COUNTRY" > /etc/modprobe.d/bcm-wifi-regdom.conf
    if [ -f /etc/default/crda ]; then
        sed -i "s/^REGDOMAIN=.*/REGDOMAIN=$WIFI_COUNTRY/" /etc/default/crda
    else
        echo "REGDOMAIN=$WIFI_COUNTRY" > /etc/default/crda
    fi

    # Apply now
    ip addr flush dev "$WIFI_IFACE" 2>/dev/null || true
    ip addr add 192.168.44.1/24 dev "$WIFI_IFACE" 2>/dev/null || true
    ip link set "$WIFI_IFACE" up 2>/dev/null || true

    systemctl unmask hostapd 2>/dev/null || true
    systemctl enable hostapd dnsmasq

    # Ensure hostapd starts after network is ready and restarts on failure
    mkdir -p /etc/systemd/system/hostapd.service.d
    cat > /etc/systemd/system/hostapd.service.d/bcm-ordering.conf <<EOF
[Unit]
After=network-online.target
Wants=network-online.target

[Service]
Restart=on-failure
RestartSec=3
EOF

    # Disable BCM's internal WiFi AP manager (conflicts with system hostapd)
    # Disable simulation mode (no fake OBD/BT/GPS data on real hardware)
    if [ -f "$BCM_DIR/config/bcm_config.yaml" ]; then
        sed -i '/^wifi:/,/^[^ ]/{s/^\(  enabled:\) true/\1 false/}' \
            "$BCM_DIR/config/bcm_config.yaml"
        # Add simulation: false under system: section
        if ! grep -q "simulation:" "$BCM_DIR/config/bcm_config.yaml"; then
            sed -i '/^  log_file:/a\  simulation: false' \
                "$BCM_DIR/config/bcm_config.yaml"
        else
            sed -i 's/^\(  simulation:\).*/\1 false/' \
                "$BCM_DIR/config/bcm_config.yaml"
        fi
        if grep -A1 "^wifi:" "$BCM_DIR/config/bcm_config.yaml" | grep -q "enabled: true"; then
            warn "Could not patch wifi.enabled — edit bcm_config.yaml manually: set wifi.enabled to false"
        else
            echo "  Set wifi.enabled=false in bcm_config.yaml (systemd manages the AP)"
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
        warn "hostapd failed — trying channel 1 fallback..."
        sed -i 's/^channel=.*/channel=1/' /etc/hostapd/hostapd.conf
        systemctl restart hostapd 2>/dev/null || true
        sleep 2
        if systemctl is-active --quiet hostapd; then
            echo -e "  ${GREEN}hostapd running (ch36 fallback)${NC}"
        else
            warn "hostapd still failing — check: sudo journalctl -u hostapd -n 20"
        fi
    fi
    ok
fi

# ─── Phase 9b: LTE modem (Huawei E3372) ──────────────────────────

step 10 "Configuring LTE modem..."

LTE_IFACE=""
for iface in /sys/class/net/ww*; do
    [ -e "$iface" ] && LTE_IFACE=$(basename "$iface") && break
done

if [ -n "$LTE_IFACE" ]; then
    echo "  Found LTE interface: $LTE_IFACE"

    # Don't let NetworkManager manage the LTE interface
    # (we use simple DHCP so it doesn't conflict with WiFi AP)
    cat >> /etc/NetworkManager/conf.d/bcm-unmanage-wifi.conf <<EOF

[keyfile]
unmanaged-devices=interface-name:$LTE_IFACE
EOF

    # Bring up with DHCP via systemd-networkd
    mkdir -p /etc/systemd/network
    cat > /etc/systemd/network/50-lte.network <<EOF
[Match]
Name=$LTE_IFACE

[Network]
DHCP=yes

[DHCPv4]
RouteMetric=700
UseDNS=yes

[Link]
RequiredForOnline=no
EOF

    # Disable wait-online (was blocking boot for 2min waiting for LTE DHCP)
    systemctl disable systemd-networkd-wait-online.service 2>/dev/null || true
    systemctl mask systemd-networkd-wait-online.service 2>/dev/null || true

    systemctl enable systemd-networkd 2>/dev/null || true
    systemctl restart systemd-networkd 2>/dev/null || true

    # Bring up now
    ip link set "$LTE_IFACE" up 2>/dev/null || true
    dhclient -nw "$LTE_IFACE" 2>/dev/null || true

    sleep 3
    if ip addr show "$LTE_IFACE" 2>/dev/null | grep -q "inet "; then
        LTE_IP=$(ip -4 addr show "$LTE_IFACE" | grep -oP 'inet \K[\d.]+')
        echo -e "  ${GREEN}LTE online: $LTE_IP${NC}"
    else
        warn "LTE interface up but no IP yet — may need SIM PIN or APN config"
    fi
    ok
else
    echo "  No LTE modem found — skipping."
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

# Enable Bluetooth (needed for AA wireless pairing)
cp "$BCM_DIR/config/systemd/bcm-bluetooth.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable bluetooth bcm-bluetooth 2>/dev/null || true
systemctl start bluetooth 2>/dev/null || true
systemctl start bcm-bluetooth 2>/dev/null || true

# Auto-power BT adapter on boot
if [ -f /etc/bluetooth/main.conf ]; then
    sed -i 's/^#*AutoEnable.*/AutoEnable=true/' /etc/bluetooth/main.conf
    if ! grep -q "^AutoEnable" /etc/bluetooth/main.conf; then
        sed -i '/^\[Policy\]/a AutoEnable=true' /etc/bluetooth/main.conf
    fi
else
    mkdir -p /etc/bluetooth
    cat > /etc/bluetooth/main.conf <<EOF
[Policy]
AutoEnable=true
EOF
fi
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
