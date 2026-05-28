# BCM v8.5 — x86 Platform Setup (Lenovo M910q)

Complete step-by-step guide to building the BCM headunit on a Lenovo
ThinkCentre M910q Tiny (or similar x86 mini-PC). Follow sections in
order — each builds on the previous one.

> **Quick setup:** After installing Debian 13 (§3), you can run the all-in-one
> script instead of following §4–§10 manually:
> ```bash
> cd /opt/bcm
> sudo bash config/scripts/setup-x86.sh
> ```
> Edit the USER CONFIG section at the top of the script first (display outputs,
> WiFi settings). The script is idempotent — safe to re-run after fixing issues.

> **Primary platform:** Lenovo M910q Tiny (i5-6400T, 8GB DDR4, 256GB NVMe)
> **Also tested:** Gigabyte GA-N3050N-D2P (Celeron N3050, legacy)

---

## 1. Hardware Overview

### 1.1 Lenovo M910q specs

| Component | Spec |
|-----------|------|
| CPU | Intel i5-6400T (4C/4T, 2.2-2.8GHz, Skylake) |
| GPU | Intel HD 530 (VAAPI hardware decode) |
| RAM | 8 GB DDR4 2400 |
| Storage | 256 GB NVMe SSD |
| WiFi | Intel 8265 2×2 802.11ac (built-in) |
| Bluetooth | Intel 8265 BT 4.2 (built-in) |
| Display | **2× DisplayPort** (mini-DP) |
| USB | 6× USB 3.0 + 1× USB-C |
| Power | 65W external 20V barrel jack |
| Form factor | 1 litre Tiny — fits behind car dash |

### 1.2 Dual display

Both outputs are **DisplayPort**. Most car displays have HDMI input —
use passive DP-to-HDMI adapter cables (~10-15 PLN each).

| Output | Display | Resolution | Content |
|--------|---------|-----------|---------|
| DP-1 | 7" or 10" IPS touchscreen (main) | 1024×600 or 1280×800 | BCM dashboard (port 5002) |
| DP-2 | 4.3" TFT (small, status) | 800×480 | Small dashboard (port 5003) |

**Discover your connector names** (run after OS install):
```bash
for f in /sys/class/drm/card*-*/status; do echo "$f: $(cat $f)"; done
```

### 1.3 WiFi and Bluetooth

Intel 8265 provides both. For wireless Android Auto you need 5GHz AP:
- Intel 8265 supports AP on 5GHz non-DFS channels — test in §10
- Fallback: USB WiFi dongle (RTL8812BU) if Intel AP fails
- BT 4.2 built-in is sufficient for AA pairing — no dongle needed

### 1.4 USB device layout

```
M910q USB ports
  ├── USB Hub (powered, 7-port)
  │     ├── Arduino Pro Micro #1 (input: SWC, buttons, doors, sensors)
  │     ├── Arduino Nano #2 (output: relays, lock, lights, wipers)
  │     ├── USB GPS (NEO-M8N)
  │     ├── USB LTE modem (Huawei E3372)
  │     └── USB microphone
  ├── USB DAC (ES9038Q2M) → RCA → TDA7388 + TDA2050
  └── USB 4-ch AHD grabber (cameras)
```

---

## 2. Power Supply + Battery Buffer

The system uses **two power domains** with separate rails. This is the
key design constraint that makes always-on features (window keyfob,
BLE-gated trunk button) possible without flattening the car battery.

### 2.1 Two power domains

| | **Domain A — always on** | **Domain B — ignition/RTC-only** |
|---|---|---|
| **Powered from** | 12 V battery buffer bus | Domain A *or* car ignition feed via relay |
| **Devices** | Arduino Nano, HM-10 BLE, RXB6 433 MHz RX, 9-channel relay module, all window/trunk relays | M910q PC, Pro Micro, powered USB hub, USB peripherals, displays, amplifier |
| **Idle draw** | ~30 mA (~0.36 W) | ~0 mA when off, ~10 W when M910q is up |
| **When parked, BCM asleep** | Continues running — listens for window remote, trunk button + BLE | Off; M910q can be RTC-woken every 15 min for location ping if desired |

### 2.2 Battery buffer — 4-6 × 12 V 5 Ah SLA in parallel

Four to six sealed lead-acid 12 V 5 Ah batteries wired in parallel form
the always-on bus. Using five is the sweet spot (25 Ah pack, ~17 days
parked-car standby at 60 mA Domain A draw). Six (30 Ah) gives ~21 days;
four (20 Ah) is still comfortably ~14 days.

```
Car 12V (ACC)  ──[30 A fuse]──┬──[Schottky diode MBR2045]──┐
                              │                            │
                              │                            ▼
                              │             ┌────────────────────────────┐
                              │             │  CC-CV charge controller   │
                              │             │  DC-DC buck, ~15-20 A max  │
                              │             │  14.4 V absorb / 13.8 V    │
                              │             │  float (3-stage SLA)       │
                              │             └────────────┬───────────────┘
                              │                          │
                              │            ┌─────────────▼──────────────┐
                              │            │  Battery buffer bus (12 V) │
                              │            │  4-6 × SLA 5 Ah parallel   │
                              │            │  (per-battery 10 A fuses)  │
                              │            └────────────┬───────────────┘
                              │                         │
                              │                  ┌──────┴───────┐
                              │                  │  LVD 11.0 V  │
                              │                  │  cutoff      │
                              │                  └──────┬───────┘
                              │                         │
                              │           ┌─────────────┼─────────────────┐
                              │           │             │                 │
                              ▼           ▼             ▼                 ▼
                       ┌─────────────┐ ┌──────────┐ ┌──────────────┐ ┌────────────────┐
                       │ Ignition    │ │ 12→5 V   │ │ 12→5 V buck  │ │ 9-ch relay     │
                       │ relay       │ │ buck     │ │ for Nano Vin │ │ module (12 V   │
                       │ (closes on  │ │ for      │ │ + HM-10 +    │ │ coil, switches │
                       │ ACC, opens  │ │ display  │ │ RXB6         │ │ via Nano)      │
                       │ on park)    │ │ panels   │ │              │ │                │
                       └──────┬──────┘ └──────────┘ └──────────────┘ └────────────────┘
                              │
                       ┌──────┴──────┐
                       │ 12→20 V     │
                       │ boost       │
                       │ (XL6019)    │
                       └──────┬──────┘
                              │
                              ▼
                       M910q barrel jack
                       + powered USB hub (Domain B)
```

**Component selection notes:**

- **Schottky diode (MBR2045):** prevents the buffer bus from
  backfeeding the car battery when the engine is off. 20 A / 45 V is
  oversize but cheap; do not substitute a regular silicon diode (the
  0.6 V drop bleeds energy).
- **CC-CV charge controller (XL4016 / DPS3020 / similar, 15-20 A):**
  the alternator can push 120 A into a depleted bus through the
  Schottky diode in a fraction of a second, well past what 5 Ah SLA
  packs tolerate (~1 C = 5 A per pack, or 25 A across 5 packs *as
  bulk-charge ceiling*). A CC-CV DC-DC module sits between the diode
  and the bus, limiting bulk-charge current to ~15-20 A and switching
  to constant-voltage at 14.4 V (absorb) then dropping to 13.8 V
  (float). Without this, expect Schottky failure, cell venting, and
  ~6-12 month SLA life instead of years. ~30-50 PLN for an XL4016
  module; a proper automotive B2B charger (Redarc BCDC, Sterling
  B2B, Victron Orion-Tr Smart) is ~600-1500 PLN if you want it
  bullet-proof.
- **LVD (low-voltage disconnect) module:** set to 11.0 V cutoff for
  SLA. AGM has gentler discharge curves than flooded; 10.5 V works
  too but 11.0 V leaves more headroom for the Domain A bus to keep
  driving the Nano cleanly. ~10-15 PLN.
- **Per-battery fusing:** each 5 Ah battery gets its own 10 A
  in-line fuse on the positive terminal before joining the bus. If
  one cell shorts you only lose that pack, not the bus.
- **Buck converters:** LM2596 modules are fine for the Nano feed
  (~100 mA peak). For the displays' 5 V rail, use a DC-DC with at
  least 3 A capacity (mini-MP1584 or similar).
- **12 V → 20 V boost (XL6019, ~15-30 PLN):** unchanged — still
  feeds the M910q's 65 W barrel jack. On Domain B only — when
  ignition relay opens, the boost goes dark and the M910q sees a
  clean power-loss event.

### 2.3 Standby budget

| Pack size | Total capacity | Domain A draw | Safe parked time before LVD |
|-----------|---------------|---------------|-----------------------------|
| 4 batteries | 20 Ah | 60 mA | ~14 days |
| 5 batteries | 25 Ah | 60 mA | ~17 days |
| 6 batteries | 30 Ah | 60 mA | ~21 days |

(60 mA = Nano ~25 mA + HM-10 idle ~15 mA + RXB6 idle ~5 mA + relay
quiescent ~10 mA + buck losses ~5 mA. Discharge limited to 50 % DoD
to preserve cycle life on SLA.)

If you also want the M910q to RTC-wake every 15 min for cloud tracking
(see § 9 Suspend/Wake), budget another ~5 Ah/week → halves the standby
figures above. For long parking, disable RTC wakes from the BCM UI.

---

## 3. OS Installation

### 3.1 Install Debian 13 (Trixie) minimal

Download **Debian 13 (Trixie) netinst** amd64 ISO. Write to USB stick.

> Debian 12 (Bookworm) also works. Trixie has newer kernel,
> better Intel GPU support, and Python 3.13.

**Lenovo BIOS:** Press **F1** at boot.
- Startup → Boot Priority → USB first

**Partitioning (manual):**

| Partition | Size | Type |
|-----------|------|------|
| ESP | 512MB-1GB | EFI System |
| Root | Rest of disk | ext4, mount `/` |
| Swap | **none** (use zram later) | — |

**Software selection:** UNCHECK everything except "SSH server" and
"standard system utilities". No desktop environment.

### 3.2 Post-install: sudo + non-free firmware

```bash
su -
apt install -y sudo
usermod -aG sudo abner
exit
# Log out and back in as abner

# Enable non-free firmware (Trixie may have it already)
grep non-free /etc/apt/sources.list || \
    sudo sed -i 's/main$/main contrib non-free non-free-firmware/' /etc/apt/sources.list
sudo apt update
```

### 3.3 Static IP (optional)

```bash
# Find interface name
ip addr show  # e.g., enp0s31f6

sudo tee /etc/network/interfaces.d/static >/dev/null <<EOF
auto enp0s31f6
iface enp0s31f6 inet static
    address 192.168.1.100
    netmask 255.255.255.0
    gateway 192.168.1.1
    dns-nameservers 8.8.8.8 1.1.1.1
EOF
sudo systemctl restart networking
```

---

## 4. System Packages

```bash
sudo apt update && sudo apt upgrade -y

# Core
sudo apt install -y \
    python3 python3-venv python3-full python3-dev python3-serial \
    git curl wget

# Display / kiosk (Debian 13: package is "chromium")
sudo apt install -y \
    xserver-xorg xinit x11-xserver-utils \
    unclutter chromium

# Intel GPU (VAAPI hardware video decode)
sudo apt install -y \
    intel-media-va-driver vainfo libva-drm2

# Audio
sudo apt install -y \
    pipewire pipewire-pulse wireplumber alsa-utils mpv

# Intel WiFi + Bluetooth
sudo apt install -y \
    firmware-iwlwifi bluez bluez-tools network-manager hostapd dnsmasq

# Camera / video
sudo apt install -y \
    ffmpeg v4l-utils

# Power management
sudo apt install -y acpid

# zram (replaces swap)
sudo apt install -y zram-tools
echo -e 'ALGO=lz4\nPERCENT=50' | sudo tee /etc/default/zramswap
sudo systemctl enable zramswap
```

Reboot, then verify VAAPI:
```bash
sudo reboot
# After reboot:
vainfo   # should show VAProfileH264 entries
```

---

## 5. BCM Installation

### 5.1 Clone and install

```bash
cd /opt
sudo git clone https://github.com/geek95dg/Alfa156-headunit.git bcm
sudo chown -R $USER:$USER /opt/bcm
cd /opt/bcm

# Debian 13 enforces PEP 668 — always use venv
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-x86.txt
```

### 5.2 Permissions

```bash
sudo usermod -aG dialout $USER   # serial ports (Arduino)
# Log out and back in
```

### 5.3 Display configuration

Edit `config/bcm_config.yaml` for your main display:

```yaml
display:
  dashboard:
    width: 1024       # 7" display; for 10" use 1280
    height: 600       # 7" display; for 10" use 800
```

### 5.4 Test BCM manually

```bash
source /opt/bcm/.venv/bin/activate
python3 main.py --platform x86 --config config/bcm_config.yaml --frontend
# Open browser: http://localhost:5002
# Ctrl+C to stop
```

If the dashboard loads in your browser — BCM works. Continue to next section.

---

## 6. Systemd Services

Install services so BCM auto-starts on boot.

### 6.1 Install all service files

```bash
cd /opt/bcm

sudo cp config/systemd/bcm-headunit-x86.service /etc/systemd/system/bcm-headunit.service
sudo cp config/systemd/bcm-ignition-watcher.service /etc/systemd/system/
sudo cp config/systemd/bcm-splash-main.service /etc/systemd/system/
sudo cp config/systemd/bcm-splash-small.service /etc/systemd/system/
sudo cp config/systemd/bcm-resume.service /etc/systemd/system/

sudo systemctl mask bcm-kiosk.service
sudo systemctl daemon-reload
sudo systemctl enable bcm-ignition-watcher bcm-splash-main bcm-splash-small bcm-resume
```

### 6.2 Power button → suspend

```bash
sudo mkdir -p /etc/acpi/events
sudo tee /etc/acpi/events/power-button >/dev/null <<EOF
event=button/power
action=/usr/local/bin/bcm-power-toggle.sh
EOF
sudo cp /opt/bcm/config/scripts/bcm-power-toggle.sh /usr/local/bin/
sudo chmod +x /usr/local/bin/bcm-power-toggle.sh
sudo systemctl enable acpid
```

### 6.3 Test services (no reboot yet)

```bash
sudo systemctl start bcm-ignition-watcher
sudo journalctl -fu bcm-ignition-watcher -u bcm-headunit
# Should show: AUTOSTART → BCM started
# Ctrl+C to stop watching

# Verify Flask is running
curl http://localhost:5002
```

---

## 7. Boot Optimization + Splash Video

### 7.1 BIOS settings (Lenovo M910q)

Press **F1** at boot:
- **Startup → Fast Boot:** Enabled
- **Security → Secure Boot:** Disabled
- **Power → After Power Loss:** Power On
- **USB Setup → USB Legacy:** Disabled

### 7.2 GRUB — hidden, silent

```bash
sudo cp /etc/default/grub /etc/default/grub.bak
sudo tee /etc/default/grub >/dev/null <<'EOF'
GRUB_DEFAULT=0
GRUB_TIMEOUT=0
GRUB_HIDDEN_TIMEOUT=0
GRUB_HIDDEN_TIMEOUT_QUIET=true
GRUB_DISTRIBUTOR=""
GRUB_CMDLINE_LINUX_DEFAULT="quiet loglevel=0 vt.global_cursor_default=0 rd.systemd.show_status=false rd.udev.log_level=3 fsck.mode=skip console=tty2"
GRUB_CMDLINE_LINUX=""
GRUB_DISABLE_OS_PROBER=true
EOF
sudo update-grub
```

**Do NOT add `splash`** — that enables Plymouth spinner.

### 7.3 Remove Plymouth

```bash
sudo apt remove -y plymouth plymouth-themes 2>/dev/null
sudo update-initramfs -u
```

### 7.4 Splash video files

```bash
mkdir -p /opt/bcm/assets/splash

# Encode main splash to match your display:
# 7":  ffmpeg -i source.mp4 -vf scale=1024:600 -c:v libx264 -crf 23 -c:a aac -y main.mp4
# 10": ffmpeg -i source.mp4 -vf scale=1280:800 -c:v libx264 -crf 23 -c:a aac -y main.mp4
cp your_main_video.mp4 /opt/bcm/assets/splash/main.mp4

# Small display splash (silent, 800x480):
# ffmpeg -i source.mp4 -vf scale=800:480 -an -c:v libx264 -crf 23 -y small.mp4
cp your_small_video.mp4 /opt/bcm/assets/splash/small.mp4
```

### 7.5 Test splash manually

```bash
# Stop X first (DRM needs exclusive framebuffer access)
sudo chvt 2
sudo pkill Xorg 2>/dev/null

# Find your connectors
for f in /sys/class/drm/card*-*/status; do echo "$f: $(cat $f)"; done

# Test main splash (replace DP-1 with your connector name)
sudo mpv --fs --vo=drm --hwdec=auto /opt/bcm/assets/splash/main.mp4
# Ctrl+C to stop

# Test small splash on second output
sudo mpv --fs --vo=drm --drm-connector=DP-2 --no-audio --hwdec=auto \
    /opt/bcm/assets/splash/small.mp4
```

If the connector name isn't `DP-1`/`DP-2`, update the splash services:
```bash
# For the small display splash:
sudo systemctl edit bcm-splash-small
# Add:
# [Service]
# Environment=BCM_SPLASH_DRM_SMALL=YourConnectorName
```

### 7.6 Expected boot timeline

| Time | What happens |
|------|-------------|
| 0-2s | Lenovo BIOS (fast boot) |
| 2-4s | Kernel loads (black, silent) |
| 4-5s | Splash video on both displays (VAAPI hw decode) |
| 5-10s | BCM Flask starts behind splash |
| 10-12s | Splash ends → X starts → Chromium kiosk |
| **~12s** | **Dashboard visible** |

---

## 8. Kiosk Display Setup

### 8.1 Allow non-root startx

```bash
sudo tee /etc/X11/Xwrapper.config >/dev/null <<EOF
allowed_users=anybody
needs_root_rights=yes
EOF
```

### 8.2 Autologin on tty1

```bash
sudo mkdir -p /etc/systemd/system/getty@tty1.service.d
sudo tee /etc/systemd/system/getty@tty1.service.d/autologin.conf >/dev/null <<EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin $USER --noclear %I \$TERM
EOF
sudo systemctl daemon-reload
```

### 8.3 Auto-start X

```bash
cat >> ~/.bash_profile <<'EOF'

# BCM kiosk: start X on tty1 only
if [ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then
    exec startx -- -nocursor
fi
EOF
```

### 8.4 Install dual-display xinitrc

```bash
cp /opt/bcm/config/scripts/xinitrc-x86-dual ~/.xinitrc
```

The xinitrc auto-detects your display resolution:
- **7" (≤1024px):** applies 1.1× scale (+10% bigger UI)
- **10" (≥1280px):** native scale (more screen space)

It positions DP-1 (main) at 0,0 and DP-2 (small) to the right.
Touch input is mapped to DP-1 only.

**If your connectors aren't DP-1/DP-2**, edit `~/.xinitrc`:
```bash
nano ~/.xinitrc
# Change DP-1 and DP-2 to match your actual connector names
```

### 8.5 Reboot and test

```bash
sudo reboot
```

You should see: splash video → BCM dashboard on main display,
small dashboard on second display. Both in kiosk mode, no cursor.

**If displays are merged** (both sites on one screen):
- Check that both displays are physically connected and detected
- Run `DISPLAY=:0 xrandr` via SSH to see the layout
- The xinitrc uses `--window-position` to place windows — verify
  the positions match your xrandr output

---

## 9. Suspend / Wake

### 9.1 Lifecycle

| Event | Action | Time |
|-------|--------|------|
| Cold boot | Splash → BCM starts (--autostart) | ~12s |
| Power button | Stop BCM → suspend to S3 | instant |
| Power button again | Resume → BCM restarts | ~3s |
| Ignition OFF | Stop BCM → suspend (5s delay) | ~5s |
| Ignition ON | Resume → BCM restarts | ~3s |
| 24h standby | Next wake → cold boot with splash | ~12s |

### 9.2 BIOS wake settings

Press F1:
- **Power → After Power Loss:** Power On
- **Power → Wake on USB:** Enabled (Arduino can wake from S3)

### 9.3 Prevent systemd-logind from handling power button

By default, logind intercepts the power button and triggers shutdown
(that's why you see 40s boot — it's a full shutdown, not suspend).
Tell logind to ignore it so only acpid handles it:

```bash
sudo mkdir -p /etc/systemd/logind.conf.d
sudo tee /etc/systemd/logind.conf.d/bcm-power.conf >/dev/null <<EOF
[Login]
HandlePowerKey=ignore
HandleSuspendKey=ignore
HandleLidSwitch=ignore
EOF
sudo systemctl restart systemd-logind
```

### 9.4 Test

```bash
sudo systemctl suspend
# Press power button → should wake in ~3s (not 40s cold boot)
journalctl -u bcm-resume --no-pager -n5
```

---

## 10. WiFi Access Point (for Wireless Android Auto)

### 10.1 Test Intel 8265 AP mode

The M910q's WiFi interface is `wlp2s0`:

```bash
# Verify AP mode is supported
iw list | grep -A5 "Supported interface modes"

# Set country code
sudo iw reg set PL

# Test AP on 5GHz channel 149
sudo tee /tmp/test-ap.conf >/dev/null <<EOF
interface=wlp2s0
driver=nl80211
ssid=ALFA_AA
hw_mode=a
channel=149
ieee80211n=1
ieee80211ac=1
wpa=2
wpa_passphrase=AlfaRomeo156
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
wpa_pairwise=CCMP
country_code=PL
EOF

sudo hostapd /tmp/test-ap.conf
```

If your phone can see "ALFA_AA" — Intel works. If connection fails,
try different channels: 36, 40, 44, 48, 149, 153, 157, 161.

### 10.2 USB dongle fallback (RTL8812BU)

If Intel 8265 can't hold connections on 5GHz:
```bash
sudo apt install -y dkms bc linux-headers-$(uname -r)
cd /tmp
git clone https://github.com/morrownr/88x2bu-20210702.git
cd 88x2bu-20210702
sudo ./install-driver.sh
sudo reboot
```

### 10.3 Persistent AP

Once you confirmed the test AP works (phone sees SSID):

```bash
WIFI_IFACE=wlp2s0   # change if using USB dongle

# Step 1: Release interface from NetworkManager
sudo nmcli device set $WIFI_IFACE managed no

# Step 2: hostapd config
sudo tee /etc/hostapd/hostapd.conf >/dev/null <<EOF
interface=$WIFI_IFACE
driver=nl80211
ssid=ALFA_AA
hw_mode=a
channel=149
ieee80211n=1
ieee80211ac=1
wpa=2
wpa_passphrase=AlfaRomeo156
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
wpa_pairwise=CCMP
country_code=PL
EOF

sudo tee /etc/default/hostapd >/dev/null <<EOF
DAEMON_CONF="/etc/hostapd/hostapd.conf"
EOF

# Step 3: DHCP — must bind to specific interface only
sudo tee /etc/dnsmasq.d/bcm-ap.conf >/dev/null <<EOF
interface=$WIFI_IFACE
bind-interfaces
dhcp-range=192.168.44.10,192.168.44.50,255.255.255.0,24h
EOF

# Step 4: Static IP (assign BEFORE hostapd starts)
sudo tee /etc/network/interfaces.d/bcm-ap >/dev/null <<EOF
auto $WIFI_IFACE
iface $WIFI_IFACE inet static
    address 192.168.44.1
    netmask 255.255.255.0
EOF

# Step 5: Prevent NetworkManager from reclaiming the interface on reboot
sudo tee /etc/NetworkManager/conf.d/bcm-unmanage-wifi.conf >/dev/null <<EOF
[keyfile]
unmanaged-devices=interface-name:$WIFI_IFACE
EOF

# Step 6: Apply IP now and start services
sudo ip addr flush dev $WIFI_IFACE
sudo ip addr add 192.168.44.1/24 dev $WIFI_IFACE
sudo ip link set $WIFI_IFACE up

sudo systemctl unmask hostapd
sudo systemctl enable hostapd dnsmasq
sudo systemctl start hostapd dnsmasq
```

### 10.4 BCM config

```yaml
# config/bcm_config.yaml:
wifi:
  enabled: true
  ssid: ALFA_AA
  password: AlfaRomeo156
```

---

## 11. Android Auto — Compile from Source (Optional)

> **Prerequisite:** BCM must be fully working (§1-§8) before this step.
> AA is optional — all other features work without it.

### 11.1 Install build dependencies

```bash
sudo apt install -y \
    cmake build-essential \
    libboost-all-dev libusb-1.0-0-dev libssl-dev \
    libprotobuf-dev protobuf-compiler \
    qtbase5-dev qtchooser qt5-qmake qtbase5-dev-tools \
    qtmultimedia5-dev libqt5multimedia5-plugins \
    qtconnectivity5-dev qtdeclarative5-dev \
    qml-module-qtquick2 qml-module-qtquick-controls2 \
    libqt5websockets5-dev libqt5bluetooth5 \
    libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev \
    gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly \
    gstreamer1.0-libav \
    libtag1-dev librtaudio-dev \
    xvfb matchbox-window-manager
```

### 11.2 Build aasdk

```bash
cd /tmp
git clone --recurse-submodules https://github.com/openDsh/aasdk.git
cd aasdk

# Fix: OpenSSL 3.0 removed FIPS_mode_set
sed -i 's/FIPS_mode_set(0);/\/\/ FIPS_mode_set(0); \/\/ removed in OpenSSL 3.0/' \
    src/Transport/SSLWrapper.cpp

mkdir build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j$(nproc)
sudo make install
sudo ldconfig
```

### 11.3 Build h264bitstream (no Makefile in repo)

```bash
cd /tmp
git clone https://github.com/aizvorski/h264bitstream.git
cd h264bitstream

gcc -c -fPIC h264_stream.c h264_sei.c -I.
ar rcs libh264bitstream.a h264_stream.o h264_sei.o

sudo cp libh264bitstream.a /usr/local/lib/
sudo cp h264_stream.h h264_sei.h h264_avcc.h h264_slice_data.h bs.h \
    /usr/local/include/
sudo ldconfig
```

### 11.4 Build openauto

```bash
cd /tmp
git clone --recurse-submodules https://github.com/openDsh/openauto.git
cd openauto

# Fix: Debian 13 librtaudio 6.x renamed RtAudioError
sed -i 's/catch(const RtAudioError& e)/catch(const std::exception\& e)/g' \
    openauto/Projection/RtAudioOutput.cpp

mkdir build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j$(nproc)
sudo make install
```

### 11.5 Verify

```bash
ls -la /usr/local/bin/autoapp
# Should show the binary (~5MB)

# Restart BCM to detect autoapp
sudo systemctl restart bcm-ignition-watcher
sudo journalctl -u bcm-headunit --no-pager | grep -i openauto
# Should show: "OpenAuto found: /usr/local/bin/autoapp"
```

### 11.6 Phone setup

1. Install **Android Auto** from Play Store
2. Enable **Developer options → USB debugging**
3. Connect phone via USB
4. Accept "Allow USB debugging" on phone
5. Select "Android Auto" mode
6. AA appears on BCM screen A2

For wireless: complete WiFi AP setup (§10) first.

---

## 12. Arduino Wiring Reference

All vehicle I/O through USB Arduinos — no GPIO on the x86 board.

### 12.1 Arduino #1 — Input (Pro Micro, 115200 baud)

```
Analog:  A0 ← SWC pod 1     A1 ← LDR     A6 ← SWC pod 2

Digital (PC817 optoisolators, active-low):
  D2 ← Ignition    D3 ← Handbrake
  D4 ← Door FL     D5 ← Door FR
  D6 ← Door RL     D7 ← Door RR
  D8 ← Bonnet      D9 ← Trunk
  D10 ← Rain sensor

DS18B20:  D14 ← External temperature
HC-SR04:  D15 → TRIG (shared)
          D16 ← ECHO FL   A2 ← ECHO FR
          A3 ← ECHO RL    A7 ← ECHO RR
```

### 12.2 Arduino #2 — Output (Nano, 9600 baud JSON)

```
Relay module (10-ch):
  D2 → Lock     D3 → Unlock    D4 → Trunk
  D5 → Win up   D6 → Win down  D7 → Headlights
  D8 → L blink  D9 → R blink   D10 → Wipers
  D11 → Horn

RF input:  D12 ← RXB6 433MHz receiver
```

### 12.3 Serial protocol

| Message | Example | Event bus topic |
|---------|---------|-----------------|
| `DOOR:keys` | `DOOR:FL=1,FR=0,...` | `vehicle.doors` |
| `HBRAKE:X` | `HBRAKE:1` | `vehicle.handbrake` |
| `IGN:X` | `IGN:1` | `vehicle.ignition_raw` |
| `RAIN:X` | `RAIN:1` | `vehicle.rain` |
| `TEMP:XX.X` | `TEMP:23.5` | `vehicle.ext_temp_raw` |
| `PARK:keys` | `PARK:FL=45,...` | `vehicle.parking_raw` |
| `LIGHT:XXX` | `LIGHT:512` | `arduino.light_level` |
| JSON ← | `{"cmd":"backlight","display":"large","brightness":80}` | display PWM duty 80% |
| JSON ← | `{"cmd":"learn_window","slot":"FL_DOWN"}` | arm next-RF-code capture |
| JSON ← | `{"cmd":"learn_ble"}` | scan for BLE tag, store strongest RSSI |
| JSON → | `{"event":"window","slot":"FL_DOWN"}` | window remote pressed |
| JSON → | `{"event":"trunk","rssi":-52}` | BLE-confirmed trunk press |

---

## 13. Verification Checklist

```
[ ] BCM Flask running: curl http://localhost:5002 returns HTML
[ ] Main display shows BCM dashboard (DP-1)
[ ] Small display shows status dashboard (DP-2)
[ ] Displays are separate (not merged/spanning)
[ ] Touch accurate on main display only
[ ] UI is 10% larger on 7" (or native on 10")
[ ] Splash video plays on cold boot (both screens)
[ ] Splash stops when dashboard appears
[ ] Power button → suspend to S3
[ ] Power button again → wake ~3s, dashboard appears
[ ] Audio plays through USB DAC / speakers
[ ] WiFi AP visible on phone (ALFA_AA)
[ ] Android Auto connects (if compiled)
[ ] No kernel messages during boot (black → splash → dashboard)
```

---

## 14. Clean Reset (if things are broken)

If you have config conflicts from multiple setup attempts, the easiest
path is the all-in-one script — it cleans everything and reinstalls:

```bash
cd /opt/bcm && git pull
sudo bash config/scripts/setup-x86.sh
```

Or for cleanup only (then follow §4 → §10 manually):

```bash
sudo bash config/scripts/cleanup-x86.sh
```

The cleanup removes:
- All BCM systemd services
- ~/.xinitrc, ~/.bash_profile
- Autologin override
- hostapd, dnsmasq, NetworkManager WiFi configs
- acpid power button override
- Chromium policy
- X11 wrapper config
- Python venv (rebuilt in §5)

---

## 15. Troubleshooting

**Splash not playing:**
```bash
# Check file exists
ls -la /opt/bcm/assets/splash/main.mp4
# Check service status
sudo journalctl -u bcm-splash-main --no-pager -n 20
# Test manually (stop X first):
sudo chvt 2 && sudo pkill Xorg
sudo mpv --fs --vo=drm --hwdec=auto /opt/bcm/assets/splash/main.mp4
# If DRM busy: X is still running. Kill it first.
```

**Displays merged (both sites on one screen):**
```bash
# Check both displays are detected
DISPLAY=:0 xrandr
# Should show two connected outputs (DP-1, DP-2) with separate resolutions
# If only one: check DP-to-HDMI adapter and cable on second display
# If both connected but merged: check ~/.xinitrc has correct xrandr --pos settings
```

**Touch offset:**
```bash
DISPLAY=:0 xinput list   # find touchscreen name
DISPLAY=:0 xinput map-to-output "YourTouchDevice" DP-1
```

**DRM connector names wrong:**
```bash
for f in /sys/class/drm/card*-*/status; do echo "$f: $(cat $f)"; done
# Update ~/.xinitrc and splash service overrides to match
```

**BCM not auto-starting:**
```bash
sudo journalctl -u bcm-ignition-watcher --no-pager -n 20
sudo journalctl -u bcm-headunit --no-pager -n 20
```

**venv broken (pip not found):**
```bash
rm -rf /opt/bcm/.venv
python3 -m venv /opt/bcm/.venv
source /opt/bcm/.venv/bin/activate
pip install -r requirements.txt -r requirements-x86.txt
```

**AA compile: FIPS_mode_set error:**
```bash
sed -i 's/FIPS_mode_set(0);/\/\/removed/' src/Transport/SSLWrapper.cpp
```

**AA compile: RtAudioError (Debian 13):**
```bash
sed -i 's/catch(const RtAudioError& e)/catch(const std::exception\& e)/g' \
    openauto/Projection/RtAudioOutput.cpp
```

**AA compile: missing h264bitstream:**
```bash
cd /tmp/h264bitstream
gcc -c -fPIC h264_stream.c h264_sei.c -I.
ar rcs libh264bitstream.a h264_stream.o h264_sei.o
sudo cp libh264bitstream.a /usr/local/lib/ && sudo cp *.h /usr/local/include/
```

**WiFi AP: phone sees but can't connect:**
- Try different channels: 36, 44, 149, 153
- Ensure `country_code=PL` is set
- Check dnsmasq is running: `sudo systemctl status dnsmasq`
- Check IP assigned: `sudo journalctl -u dnsmasq --no-pager -n 10`

**Suspend not working:**
```bash
cat /sys/power/state   # must list "mem"
# If not: BIOS → enable S3 (not S0ix/Modern Standby)
```

**No sound:**
```bash
wpctl status
wpctl set-default <sink-id>
speaker-test -t sine -l 1
```
