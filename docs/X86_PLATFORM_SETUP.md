# BCM v8.5 — x86 Platform Setup (Lenovo M910q)

Complete step-by-step guide to building the BCM headunit on a Lenovo
ThinkCentre M910q Tiny (or similar x86 mini-PC). Covers everything from
bare hardware to a fully working dual-display car dashboard with wireless
Android Auto, splash video, suspend/wake, and Arduino vehicle control.

> **Primary platform:** Lenovo M910q Tiny (i5-6400T, 8GB DDR4, 256GB NVMe)
> **Also tested:** Gigabyte GA-N3050N-D2P (Celeron N3050, legacy — some
> sections note differences)

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
| Display outputs | **2× DisplayPort** (mini-DP, model-dependent) |
| USB | 6× USB 3.0 + 1× USB-C |
| Power | 65W external 20V barrel jack |
| Form factor | 1 litre Tiny — fits behind car dash |

### 1.2 Dual display setup

The M910q has **two DisplayPort outputs** — both can drive displays
simultaneously with no USB adapter needed.

| Output | Display | Resolution | Content |
|--------|---------|-----------|---------|
| DP-1 | 7" or 10" IPS touchscreen (main) | 1024×600 or 1280×800 | BCM dashboard (port 5002) |
| DP-2 | 4.3" TFT (small, status) | 800×480 | Small dashboard (port 5003) |

Most car displays have HDMI input. Use **passive DP-to-HDMI adapter
cables** (~10-15 PLN each). Active adapters are not needed for
single-link resolutions under 1920×1200.

### 1.3 WiFi and Bluetooth

The Intel 8265 provides both WiFi and Bluetooth. For wireless Android
Auto, you need a 5GHz WiFi access point:

- **Intel 8265 AP mode:** supports AP on 5GHz non-DFS channels (36-48)
  on Linux. Test first (see §10). If it works, no external dongle needed.
- **Fallback:** USB WiFi dongle with RTL8812BU chipset (TP-Link Archer
  T3U Plus, ~70 PLN) if Intel AP mode doesn't work on 5GHz.
- **Bluetooth:** Intel 8265 BT 4.2 is sufficient for AA pairing. No
  external BT dongle needed.

### 1.4 USB device layout

```
M910q USB ports (6× USB 3.0 + 1× USB-C)
  ├── USB Hub (powered, 7-port, if needed)
  │     ├── Arduino Pro Micro #1 (input: SWC, buttons, doors, sensors)
  │     ├── Arduino Nano #2 (output: relays, lock, lights, wipers)
  │     ├── USB WiFi dongle (only if Intel AP fails — see §10)
  │     ├── USB GPS (NEO-M8N)
  │     ├── USB LTE modem (Huawei E3372)
  │     └── USB microphone
  ├── USB DAC (ES9038Q2M) → RCA → TDA7388 + TDA2050
  └── USB 4-ch AHD grabber (cameras)
```

> **Legacy note (GA-N3050N-D2P):** Has HDMI + VGA (shows as DP-2 in
> xrandr), no built-in WiFi/BT — needs both USB WiFi and BT dongles.
> See earlier revisions of this file for N3050-specific instructions.

---

## 2. Power Supply + Battery Buffer

### 2.1 M910q power requirements

The M910q uses a **65W 20V external barrel jack** — not an ATX 24-pin
connector. In the car, you need to convert 12V to 20V.

### 2.2 12V → 20V DC-DC converter

| Module | Input | Output | Price (PLN) |
|--------|-------|--------|-------------|
| XL6019 step-up module (adjustable) | 5-32V | 5-35V, 5A | 15-30 |
| Universal car laptop adapter (20V) | 12V cig. lighter | 19-20V, 3.5A | 50-100 |
| MT3608 boost + fine-tune | 2-24V | up to 28V, 2A | 8-15 |

**Recommended:** XL6019 module — set output to 20V with the trimmer
potentiometer. Verify with a multimeter before connecting to the M910q.

### 2.3 AGM battery buffer (12V 7.2Ah)

An AGM battery between the car battery and the DC-DC converter provides:
- **Cranking protection:** car battery voltage dips to ~9V during
  starter engagement — AGM holds steady 12V for the M910q
- **24h standby:** 7.2Ah at ~2W S3 draw ≈ 43 hours without car battery
- **UPS:** graceful shutdown on battery disconnect or flat car battery

### 2.4 Wiring diagram

```
                                   ┌─────────────────────┐
Car Battery 12V ──[25A fuse]──┬────┤ Schottky diode      │
                              │    │ (MBR2045, prevents   │
                              │    │  backfeed to car)    │
                              │    └──────────┬──────────┘
                              │               │
                              │          AGM 12V 7.2Ah
                              │               │
                              │    ┌──────────┘
                              │    │
                              └────┤
                                   │
                         ┌─────────┴──────────┐
                         │ LVD cutoff (10.5V)  │ ← protects AGM from deep discharge
                         └─────────┬──────────┘
                                   │
                    ┌──────────────┴──────────────┐
                    │                              │
              [12V→20V boost]                [20A fuse]
                    │                              │
              M910q barrel jack              TDA7388 amp
                                          (direct 12V)
```

**Components:**
- Schottky diode (MBR2045 or similar, 20A): prevents AGM from charging
  the car battery backwards. One-way current flow: car → AGM.
- Low-voltage disconnect (LVD): cuts power at 10.5V to protect AGM.
  Use an adjustable buck module with enable pin, or a dedicated LVD
  relay (~15 PLN). Set to reconnect at 12.5V (hysteresis).
- AGM battery: maintenance-free, safe for enclosed mounting. Standard
  UPS-style 12V 7.2Ah (~50-80 PLN).

**Charging:** Car alternator charges AGM through the Schottky diode
whenever the engine is running. No dedicated charge controller needed —
car alternator regulates at ~14.4V which is correct for AGM float charge.

### 2.5 Power budget

| State | M910q draw | Amp draw | Total from 12V |
|-------|-----------|----------|----------------|
| S3 suspend | ~2W | 0W | ~0.2A |
| Active (dashboard) | ~25W | ~5W | ~3A |
| Active + audio | ~25W | ~40W | ~6A |

AGM standby: 7.2Ah ÷ 0.2A = **36 hours** (exceeds 24h cycle requirement).

---

## 3. OS Installation

### 3.1 Install Debian 12 (Bookworm) minimal

Download **Debian 12 netinst** amd64 ISO. Write to USB stick (Rufus/Etcher).

**Lenovo BIOS:** Press **F1** at boot (not DEL like Gigabyte).
- Startup → Boot Priority → USB first
- Boot from USB, install Debian

**Install options:**
- Partitioning: single ext4 root on NVMe, no swap (use zram)
- Software: UNCHECK everything except "SSH server" and "standard system utilities"
- No desktop environment
- User: create your user (e.g., `abner`)

### 3.2 Enable non-free firmware

Intel 8265 needs `firmware-iwlwifi` from non-free:

```bash
sudo sed -i 's/main$/main contrib non-free non-free-firmware/' /etc/apt/sources.list
sudo apt update
```

---

## 4. System Packages

```bash
sudo apt update && sudo apt upgrade -y

# Core
sudo apt install -y \
    python3 python3-venv python3-pip python3-dev python3-serial \
    git curl wget

# Display / kiosk
sudo apt install -y \
    xserver-xorg xinit x11-xserver-utils \
    unclutter chromium

# Intel GPU (VAAPI hardware video decode)
sudo apt install -y \
    intel-media-va-driver vainfo libva-drm2

# Audio
sudo apt install -y \
    pipewire pipewire-pulse wireplumber alsa-utils mpv

# Intel WiFi + Bluetooth firmware
sudo apt install -y \
    firmware-iwlwifi bluez bluez-tools network-manager hostapd dnsmasq

# Camera / video
sudo apt install -y \
    ffmpeg v4l-utils

# Suspend / power management
sudo apt install -y \
    acpid

# zram (replaces swap, no SSD wear)
sudo apt install -y zram-tools
echo -e 'ALGO=lz4\nPERCENT=50' | sudo tee /etc/default/zramswap
sudo systemctl enable zramswap

# Android Auto build dependencies (see §7)
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

Reboot after package install:
```bash
sudo reboot
```

Verify VAAPI after reboot:
```bash
vainfo
# Should show "VAProfileH264" entries — hardware H.264 decode works
```

---

## 5. Boot Optimization

Goal: **BIOS logo → black → splash video (both screens) → BCM dashboard**.
No GRUB menu, no kernel log, no systemd service spam.

### 5.1 Lenovo BIOS settings

Press **F1** at boot to enter BIOS:
- **Startup → Fast Boot:** Enabled
- **Startup → Primary Boot Sequence:** NVMe first
- **Security → Secure Boot:** Disabled (Debian needs this off)
- **Power → After Power Loss:** Power On (auto-boot after battery reconnect)
- **USB Setup → USB Legacy Support:** Disabled (saves ~2s)

### 5.2 GRUB — hidden, silent

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

**Do NOT add `splash`** — that enables Plymouth, which shows a spinner
instead of your splash video.

### 5.3 Remove Plymouth

```bash
sudo apt remove -y plymouth plymouth-themes 2>/dev/null
sudo update-initramfs -u
```

### 5.4 Splash video on both screens

The splash plays fullscreen via `mpv --vo=drm` (direct framebuffer, no X).

```bash
sudo apt install -y mpv

# Create splash directory
mkdir -p /opt/bcm/assets/splash

# Main display splash (with audio, match your display resolution):
# For 7":  ffmpeg -i source.mp4 -vf scale=1024:600 -c:v libx264 -crf 23 -c:a aac -y main.mp4
# For 10": ffmpeg -i source.mp4 -vf scale=1280:800 -c:v libx264 -crf 23 -c:a aac -y main.mp4
cp your_alfa_animation.mp4 /opt/bcm/assets/splash/main.mp4

# Small display splash (silent, 800x480):
# ffmpeg -i source.mp4 -vf scale=800:480 -an -c:v libx264 -crf 23 -y small.mp4
cp your_alfa_logo_loop.mp4 /opt/bcm/assets/splash/small.mp4
```

**Discover your DRM connector names:**
```bash
for f in /sys/class/drm/card*-*/status; do echo "$f: $(cat $f)"; done
# M910q typically shows: card0-DP-1 and card0-DP-2
```

**Test splash manually** (must stop X first):
```bash
# Switch to text console
sudo chvt 2
sudo pkill Xorg

# Test main splash
sudo mpv --fs --vo=drm --hwdec=auto /opt/bcm/assets/splash/main.mp4
# Ctrl+C to stop

# Test small splash (on second DP)
sudo mpv --fs --vo=drm --drm-connector=DP-2 --no-audio /opt/bcm/assets/splash/small.mp4
```

### 5.5 Disable unnecessary services

```bash
systemd-analyze blame | head -20

sudo systemctl disable ModemManager 2>/dev/null
sudo systemctl disable apt-daily.timer
sudo systemctl disable apt-daily-upgrade.timer
sudo systemctl disable e2scrub_reap.service 2>/dev/null
sudo systemctl disable man-db.timer 2>/dev/null
sudo systemctl disable logrotate.timer
```

### 5.6 Expected boot timeline

| Time | What happens |
|------|-------------|
| 0-2s | Lenovo BIOS (fast boot) |
| 2s | GRUB (hidden, instant) |
| 2-4s | Kernel loads (black screen, silent) |
| 4-5s | Splash video starts on **both displays** (mpv DRM, VAAPI hw decode) |
| 5-10s | BCM Flask starts behind splash |
| 10-12s | Splash detects Flask ready → fades out → X starts |
| 12-14s | Chromium kiosk opens on both displays |
| **~12s** | **Dashboard visible** |

Cold boot: **~10-12s** (NVMe). S3 resume: **~2-3s**.
After 24h standby, next wake replays the splash (cold-like boot).

---

## 6. BCM Installation

### 6.1 Clone and install

```bash
cd /opt
sudo git clone https://github.com/geek95dg/Alfa156-headunit.git bcm
sudo chown -R $USER:$USER /opt/bcm
cd /opt/bcm

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-x86.txt
```

### 6.2 Serial port permissions

```bash
sudo usermod -aG dialout $USER
# Log out and back in
```

### 6.3 Configuration

The default config (`config/bcm_config.yaml`) has the display set to
1024×600 (7" screen). For a 10" display, edit:

```bash
nano /opt/bcm/config/bcm_config.yaml
```

```yaml
display:
  dashboard:
    width: 1280       # 10" display (or 1024 for 7")
    height: 800       # 10" display (or 600 for 7")
```

---

## 7. Android Auto — Compile from Source

Android Auto requires two open-source projects: **aasdk** (protocol library)
and **openauto** (Qt5 UI app). Both must be compiled on the target machine.

### 7.1 Build aasdk

```bash
cd /tmp
git clone --recurse-submodules https://github.com/openDsh/aasdk.git
cd aasdk

# Fix OpenSSL 3.0 compatibility (FIPS_mode_set was removed)
sed -i 's/FIPS_mode_set(0);/\/\/ FIPS_mode_set(0); \/\/ removed in OpenSSL 3.0/' \
    src/Transport/SSLWrapper.cpp

mkdir build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j$(nproc)
sudo make install
sudo ldconfig
```

### 7.2 Build h264bitstream (manual — no Makefile in repo)

```bash
cd /tmp
git clone https://github.com/aizvorski/h264bitstream.git
cd h264bitstream

# Compile manually
gcc -c -fPIC h264_stream.c h264_sei.c -I.
ar rcs libh264bitstream.a h264_stream.o h264_sei.o

# Install
sudo cp libh264bitstream.a /usr/local/lib/
sudo cp h264_stream.h h264_sei.h h264_avcc.h h264_slice_data.h bs.h \
    /usr/local/include/
sudo ldconfig
```

> **Note:** `h264_nal.h` does not exist in newer versions — this is normal.

### 7.3 Build openauto

```bash
cd /tmp
git clone --recurse-submodules https://github.com/openDsh/openauto.git
cd openauto
mkdir build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j$(nproc)
sudo make install
```

### 7.4 Verify

```bash
ls -la /usr/local/bin/autoapp
# Should show the binary (~5MB)
```

Restart BCM to pick up autoapp:
```bash
sudo systemctl restart bcm-ignition-watcher
sudo journalctl -u bcm-headunit --no-pager | grep -i openauto
# Should show: "OpenAuto found: /usr/local/bin/autoapp"
```

### 7.5 Phone setup for Android Auto

On your Android phone:
1. Install **Android Auto** from Play Store
2. Enable **Developer options** → **USB debugging**
3. Connect phone via USB cable
4. Accept "Allow USB debugging" prompt on phone
5. Select "Android Auto" when phone asks about USB mode
6. AA should appear on BCM screen A2

For wireless AA, complete the WiFi AP setup in §10 first.

---

## 8. Display Kiosk Setup

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

### 8.3 Auto-start X on login (no cursor)

```bash
cat >> ~/.bash_profile <<'EOF'

# BCM kiosk: start X on tty1 only, hide cursor
if [ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then
    exec startx -- -nocursor
fi
EOF
```

### 8.4 Install the dual-display xinitrc

```bash
cp /opt/bcm/config/scripts/xinitrc-x86-dual ~/.xinitrc
```

This xinitrc:
- Sets up DP-1 (main) + DP-2 (small) via xrandr
- **Auto-detects resolution**: 7" (≤1024px) gets `scale-factor=1.1`
  for +10% bigger UI; 10" (≥1280px) uses native scale (more room)
- Maps touchscreen to DP-1 only (prevents touch offset)
- Opens Chromium `--app` windows at correct positions per display
- No window manager — prevents screen merging

### 8.5 Display auto-adaptation

The BCM frontend uses viewport-relative units and Tailwind responsive
classes. It adapts to any resolution automatically:

| Display | Resolution | Scale factor | Effective viewport |
|---------|-----------|-------------|-------------------|
| 7" IPS | 1024×600 | 1.1 (+10%) | 931×545 CSS px |
| 10" IPS | 1280×800 | 1.0 (native) | 1280×800 CSS px |

If elements overlap at 1.1x scale, reduce to 1.05:
```bash
# Edit ~/.xinitrc, find the SCALE= line:
SCALE=1.05
```

---

## 9. Systemd Services

### 9.1 Install all services

```bash
cd /opt/bcm

# Use the x86-specific headunit service
sudo cp config/systemd/bcm-headunit-x86.service /etc/systemd/system/bcm-headunit.service
sudo cp config/systemd/bcm-ignition-watcher.service /etc/systemd/system/
sudo cp config/systemd/bcm-splash-main.service /etc/systemd/system/
sudo cp config/systemd/bcm-splash-small.service /etc/systemd/system/
sudo cp config/systemd/bcm-resume.service /etc/systemd/system/

# Mask the kiosk service (.xinitrc handles Chromium)
sudo systemctl mask bcm-kiosk.service

# Enable services
sudo systemctl daemon-reload
sudo systemctl enable bcm-ignition-watcher
sudo systemctl enable bcm-splash-main
sudo systemctl enable bcm-splash-small
sudo systemctl enable bcm-resume
```

### 9.2 Power button → suspend (acpid)

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

### 9.3 Lifecycle summary

**Cold boot** (first power-on or after 24h standby):
1. BIOS → GRUB (hidden) → kernel (silent)
2. `bcm-splash-main` + `bcm-splash-small` → video on both screens
3. `bcm-ignition-watcher` starts with `--autostart` → starts BCM immediately
4. Flask starts → splash detects it → kills mpv after 5s overlap
5. X starts → Chromium kiosk on both displays → dashboard visible

**Standby** (power button / Arduino POWEROFF / ignition off):
1. BCM stops → 5s grace period → system suspends to S3
2. Power draw: ~2W from AGM battery
3. AGM sustains 36+ hours of S3

**Wake** (power button / ignition on):
1. System resumes from S3 in ~2s
2. `bcm-resume.service` restarts BCM
3. Dashboard visible in ~3s total (no splash — warm wake)

**24h cycle reset:**
1. After 24h in standby, next wake is treated as cold boot
2. Splash video replays on both screens
3. Full BCM reinitialisation

---

## 10. WiFi Access Point for Wireless Android Auto

Wireless AA requires a 5GHz WiFi access point. The phone pairs via
Bluetooth (Intel 8265 built-in), then connects to the WiFi AP for
the TCP data stream.

### 10.1 Test Intel 8265 AP mode (try first)

```bash
# Check if AP mode is supported
iw list | grep -A5 "Supported interface modes"
# Must show "AP"

# Set regulatory domain
sudo iw reg set PL

# Test 5GHz AP
sudo tee /tmp/test-ap.conf >/dev/null <<EOF
interface=wlan0
driver=nl80211
ssid=ALFA_AA
hw_mode=a
channel=36
ieee80211n=1
ieee80211ac=1
wpa=2
wpa_passphrase=AlfaRomeo156
wpa_key_mgmt=WPA-PSK
EOF

sudo hostapd /tmp/test-ap.conf
```

If hostapd starts without errors and your phone can see "ALFA_AA" on
5GHz — **Intel 8265 works, skip §10.2.**

If it fails with "Could not set channel" or "DFS" errors — install
a USB WiFi dongle (§10.2).

### 10.2 USB WiFi dongle fallback (RTL8812BU)

```bash
sudo apt install -y dkms bc linux-headers-$(uname -r)
cd /tmp
git clone https://github.com/morrownr/88x2bu-20210702.git
cd 88x2bu-20210702
sudo ./install-driver.sh
# Reboot, then verify:
iw list | grep -A5 "Supported interface modes"
```

### 10.3 Persistent AP with hostapd + dnsmasq

Once you know which interface works (wlan0 for Intel, wlx... for USB):

```bash
# Find your WiFi interface name
ip link show | grep -E "wlan|wlx"
WIFI_IFACE=wlan0  # or wlxXXXXXXXXXXXX for USB dongle

# Configure hostapd
sudo tee /etc/hostapd/hostapd.conf >/dev/null <<EOF
interface=$WIFI_IFACE
driver=nl80211
ssid=ALFA
hw_mode=a
channel=36
ieee80211n=1
ieee80211ac=1
wmm_enabled=1
wpa=2
wpa_passphrase=AlfaRomeo156
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
EOF

sudo tee /etc/default/hostapd >/dev/null <<EOF
DAEMON_CONF="/etc/hostapd/hostapd.conf"
EOF

# Configure dnsmasq for DHCP
sudo tee /etc/dnsmasq.d/bcm-ap.conf >/dev/null <<EOF
interface=$WIFI_IFACE
dhcp-range=192.168.44.10,192.168.44.50,255.255.255.0,24h
EOF

# Static IP for the AP interface
sudo tee /etc/network/interfaces.d/bcm-ap >/dev/null <<EOF
auto $WIFI_IFACE
iface $WIFI_IFACE inet static
    address 192.168.44.1
    netmask 255.255.255.0
EOF

# Enable services
sudo systemctl unmask hostapd
sudo systemctl enable hostapd dnsmasq
sudo systemctl start hostapd dnsmasq
```

### 10.4 BCM config for WiFi

Edit `/opt/bcm/config/bcm_config.yaml`:
```yaml
wifi:
  enabled: true
  ssid: ALFA
  password: AlfaRomeo156
```

---

## 11. Arduino Wiring Reference

All vehicle I/O goes through USB Arduinos — no GPIO on the x86 board.

### 11.1 Arduino #1 — Input controller (Pro Micro, 115200 baud)

```
Analog:
  A0 ← SWC pod 1 (resistor ladder, 12 buttons)
  A1 ← LDR (ambient light sensor)
  A6 ← SWC pod 2 / music panel (resistor ladder)

Digital inputs (PC817 optoisolators, active-low):
  D2 ← Ignition/ACC 12V detect
  D3 ← Handbrake switch
  D4 ← Door FL       D5 ← Door FR
  D6 ← Door RL       D7 ← Door RR
  D8 ← Bonnet        D9 ← Trunk
  D10 ← Rain sensor digital output

DS18B20 (1-Wire):
  D14 ← External temperature probe

HC-SR04 parking sensors:
  D15 → TRIG (shared)
  D16 ← ECHO FL      A2 ← ECHO FR
  A3 ← ECHO RL       A7 ← ECHO RR

USB HID output: button keycodes (volume, media, nav)
Serial output: LIGHT, DOOR, HBRAKE, IGN, RAIN, TEMP, PARK
```

### 11.2 Arduino #2 — Output controller (Nano, 9600 baud JSON)

```
Relay outputs (10-channel relay module):
  D2 → Central lock (LOCK)      D3 → Central lock (UNLOCK)
  D4 → Trunk release            D5 → Window up (all)
  D6 → Window down (all)        D7 → Headlights (follow-me-home)
  D8 → Left blinker             D9 → Right blinker
  D10 → Wiper motor relay       D11 → Horn (alarm)

Input:
  D12 ← RF 433MHz receiver (RXB6) — key fob signal
```

### 11.3 Serial protocol

| Direction | Message | Example |
|-----------|---------|---------|
| Arduino→BCM | `LIGHT:XXX` | `LIGHT:512` |
| Arduino→BCM | `DOOR:keys` | `DOOR:FL=1,FR=0,RL=0,RR=0,BONNET=0,TRUNK=0` |
| Arduino→BCM | `HBRAKE:X` | `HBRAKE:1` |
| Arduino→BCM | `IGN:X` | `IGN:1` |
| Arduino→BCM | `RAIN:X` | `RAIN:1` |
| Arduino→BCM | `TEMP:XX.X` | `TEMP:23.5` |
| Arduino→BCM | `PARK:keys` | `PARK:FL=45,FR=60,RL=120,RR=150` |
| BCM→Arduino | JSON | `{"cmd":"lock"}` |
| BCM→Arduino | JSON | `{"cmd":"lights","state":1,"timeout":60}` |
| BCM→Arduino | JSON | `{"cmd":"wiper","state":1}` |
| BCM→Arduino | JSON | `{"cmd":"blink","count":2}` |

---

## 12. Verification Checklist

After completing all steps, verify each feature:

```
[ ] Both displays show splash video on cold boot
[ ] Main splash has audio through USB DAC / speakers
[ ] Small splash is silent
[ ] Splash stops when dashboard appears (no manual intervention)
[ ] BCM dashboard loads on DP-1 (main), small dashboard on DP-2
[ ] Touch only registers on DP-1 (main display)
[ ] UI is 10% larger on 7" screen (or native on 10")
[ ] No element overlapping on any screen (A1-A8 + Settings)
[ ] Power button press → suspend to S3
[ ] Power button again → wake in ~3s, dashboard appears
[ ] After 24h standby → next wake shows splash (cold-like)
[ ] Audio plays through USB DAC / speakers
[ ] Android Auto connects (USB cable to phone)
[ ] WiFi AP visible on phone (for wireless AA)
[ ] BT pairing works (Intel 8265)
[ ] Arduino serial data appears: journalctl -u bcm-headunit | grep Arduino
```

---

## 13. Troubleshooting

**DRM connector names — how to find yours:**
```bash
for f in /sys/class/drm/card*-*/status; do echo "$f: $(cat $f)"; done
# M910q: card0-DP-1: connected, card0-DP-2: connected
```

**Splash video laggy:**
- Re-encode to match display resolution (not 720p/1080p)
- Verify VAAPI: `vainfo | grep H264`
- Add `--hwdec=vaapi` explicitly to mpv command

**Splash not showing / DRM busy:**
- Splash must start before X. Check service ordering:
  `systemctl list-dependencies bcm-splash-main`
- If testing manually, stop X first: `sudo pkill Xorg`

**Screens merged into one (Chromium spans both):**
- Don't use matchbox-window-manager for dual display
- Use the `xinitrc-x86-dual` script (no WM, `--app` mode)
- Verify xrandr: `DISPLAY=:0 xrandr --listmonitors`

**Touch offset (pointer doesn't match finger):**
```bash
DISPLAY=:0 xinput list
# Find your touchscreen device name
DISPLAY=:0 xinput map-to-output "YourTouchDevice" DP-1
```

**Android Auto: FIPS_mode_set error (aasdk build):**
```bash
sed -i 's/FIPS_mode_set(0);/\/\/ removed in OpenSSL 3.0/' src/Transport/SSLWrapper.cpp
```

**Android Auto: missing h264bitstream (openauto build):**
```bash
cd /tmp/h264bitstream
gcc -c -fPIC h264_stream.c h264_sei.c -I.
ar rcs libh264bitstream.a h264_stream.o h264_sei.o
sudo cp libh264bitstream.a /usr/local/lib/
sudo cp *.h /usr/local/include/
sudo ldconfig
```

**Android Auto: missing Qt5Qml:**
```bash
sudo apt install -y qtdeclarative5-dev qml-module-qtquick2
```

**Intel 8265 WiFi won't create 5GHz AP:**
- Set country code: `sudo iw reg set PL`
- Use channel 36 (non-DFS)
- If still fails: install USB RTL8812BU dongle (§10.2)

**BCM not starting (autostart fails):**
```bash
sudo journalctl -u bcm-ignition-watcher --no-pager -n 20
sudo journalctl -u bcm-headunit --no-pager -n 20
# Common: wrong config path, venv broken, Python import error
```

**Suspend not working:**
```bash
cat /sys/power/state    # should list "mem"
sudo systemctl suspend  # test manually
# If no "mem": BIOS → enable S3 (not S0ix/Modern Standby)
```

**Scale factor causes overlapping:**
```bash
# Edit ~/.xinitrc — reduce scale
SCALE=1.05   # or 1.0 for no scaling
```

**No sound:**
```bash
wpctl status                  # list sinks
wpctl set-default <sink-id>   # set your DAC as default
speaker-test -t sine -l 1     # test
```

**Arduino not detected:**
```bash
ls /dev/ttyACM* /dev/ttyUSB*
dmesg | grep -i "arduino\|acm"
sudo usermod -aG dialout $USER  # then re-login
```
