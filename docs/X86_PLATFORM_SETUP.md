# BCM v8.5 — x86 Platform Setup (Car PC)

Running the BCM headunit on a standard x86 PC (Intel Celeron N or similar)
inside the car. All GPIO is handled by USB Arduinos — the x86 board only
needs USB + HDMI + audio.

> **Tested on:** Gigabyte GA-N3050N-D2P (Celeron N3050, 4 GB DDR3L,
> 64 GB SSD, single HDMI, Debian 12 Bookworm minimal).

---

## 1. Hardware Requirements

### 1.1 Minimum x86 specs

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| CPU | Celeron N3050 (2C/2T) | Celeron N100/N5105 (4C/4T) |
| RAM | 2 GB | 4 GB |
| Storage | 16 GB SSD | 64 GB+ SSD (DVR recording) |
| USB | 4× USB 2.0 (use hub) | 6+ USB (mix 2.0/3.0) |
| HDMI | 1× HDMI | 1× is enough (see §1.6) |
| Audio | USB DAC (ES9038Q2M) | same |
| Network | USB WiFi + USB BT | same |

### 1.2 Displays — HDMI + optional USB-HDMI

Most mini-ITX Celeron boards (including GA-N3050N-D2P) have only **one
HDMI output**. For a second display, use a USB-to-HDMI adapter with
a DisplayLink chipset.

**Primary:** HDMI → 7" touchscreen (main dashboard, port 5002)
**Secondary (optional):** USB-HDMI → 4.3" display (small dashboard, port 5003)

#### USB-HDMI adapter setup (DisplayLink)

DisplayLink adapters need the proprietary `evdi` kernel module.

```bash
# 1. Install build dependencies
sudo apt install -y dkms build-essential linux-headers-$(uname -r)

# 2. Download the DisplayLink driver
#    Go to https://www.synaptics.com/products/displaylink-graphics/downloads/ubuntu
#    Download the latest .run file (e.g., DisplayLink USB Graphics Software for Ubuntu 6.x)
#    Or from the direct URL:
cd /tmp
wget https://www.synaptics.com/sites/default/files/exe_files/2024-04/DisplayLink%20USB%20Graphics%20Software%20for%20Ubuntu6.0-EXE.zip
unzip "DisplayLink USB Graphics Software for Ubuntu6.0-EXE.zip"
chmod +x displaylink-driver-*.run
sudo ./displaylink-driver-*.run

# 3. Reboot
sudo reboot

# 4. Verify the adapter appears as a display
xrandr --listmonitors
# Should show: HDMI-1 (or similar) + DVI-I-1-1 (DisplayLink)
```

**Known limitations:**
- ~10-30ms latency compared to native HDMI (acceptable for status display)
- CPU usage ~5-10% for USB frame compression
- Must use the proprietary driver — no open-source alternative
- Some cheap adapters have compatibility issues — recommended chipsets:
  DL-3500, DL-3900, DL-6950

**Configure dual display in .xinitrc** (see §4.4 for full file):
```bash
# After matchbox starts, arrange displays:
xrandr --output HDMI-1 --primary --auto
xrandr --output DVI-I-1-1 --right-of HDMI-1 --auto
# Then open two Chromium windows on each display
```

If DisplayLink doesn't work on your hardware, use the single HDMI for
the main display and optionally drive the small screen from a Raspberry
Pi Zero W showing `http://<x86-ip>:5003` in its own Chromium kiosk.

### 1.3 WiFi and Bluetooth dongles

The GA-N3050N-D2P has no built-in WiFi or Bluetooth. For wireless
Android Auto you need:

| Dongle | Chipset | Purpose | Price (PLN) |
|--------|---------|---------|-------------|
| TP-Link Archer T3U Plus | RTL8812BU | WiFi 5GHz AP (AA wireless) | ~70 |
| TP-Link UB500 | RTL8761B | Bluetooth 5.0 (AA pairing) | ~35 |

Install drivers after OS setup (see §3.3).

### 1.4 Power supply — DC-ATX for car 12V

A standard ATX PSU cannot run from car 12V. Use a **DC-ATX converter**
(PicoPSU) that takes 12V DC input and outputs all ATX voltages via the
24-pin connector.

| Module | Input | Output | Price (PLN) | Notes |
|--------|-------|--------|-------------|-------|
| **PicoPSU-160-XT** | 12-25V DC | 160W ATX | 150-250 | Most popular, proven |
| **M4-ATX** | 6-30V DC | 250W ATX | 300-500 | Built-in ignition logic |
| Generic "DC-ATX 200W" | 12-24V DC | 200W | 60-120 | AliExpress, works fine |

**Wiring:**

```
Car Battery 12V ──┐
                  ├──[25A fuse]──► DC-ATX ──► 24-pin ATX + 4-pin CPU
                  │
ACC/Ignition ─────┼──[PC817]──► Arduino (reports IGN:1 over serial)
                  │
                  └──[20A fuse]──► TDA7388 amp (direct 12V)
```

### 1.5 Suspend / wake (power button + ignition)

The x86 board supports S3 suspend (sleep). BCM uses this for instant
wake (~2s) when ignition turns on or power button is pressed:

| Event | Action | Wake time |
|-------|--------|-----------|
| Ignition ON | Resume from S3 (or start BCM if already awake) | ~2s |
| Ignition OFF | Stop BCM, suspend to S3 | instant |
| Power button press | Toggle: suspend ↔ wake | ~2s |
| 12h standby timeout | Still in S3, next wake = cold splash | ~2s |

See §4 for suspend setup.

### 1.6 USB device layout

```
x86 motherboard USB ports
  ├── USB Hub (powered, 7-port recommended)
  │     ├── Arduino Pro Micro #1 (input controller)
  │     ├── Arduino Nano #2 (relay controller)
  │     ├── TP-Link UB500 (Bluetooth 5.0)
  │     ├── TP-Link Archer T3U Plus (WiFi 5GHz AP)
  │     ├── USB GPS (NEO-M8N)
  │     ├── USB LTE modem (Huawei E3372)
  │     └── USB microphone
  ├── USB DAC (ES9038Q2M) → RCA → TDA7388 + TDA2050
  └── USB 4-ch AHD grabber (cameras)
```

---

## 2. OS Installation

### 2.1 Install Debian 12 minimal

Download **Debian 12 (Bookworm) netinst** amd64 ISO. Write to USB
stick with Rufus/Etcher. Boot and install:

- **Partitioning:** single ext4 root, no swap (use zram instead)
- **Software selection:** UNCHECK everything except "SSH server" and
  "standard system utilities" — no desktop environment
- **User:** create your user (e.g., `abner`), set root password

### 2.2 Post-install — essential packages

```bash
sudo apt update && sudo apt upgrade -y

# Core
sudo apt install -y \
    python3 python3-venv python3-pip python3-dev python3-serial \
    git curl wget

# Display / kiosk
sudo apt install -y \
    xserver-xorg xserver-xorg-video-intel xinit x11-xserver-utils \
    matchbox-window-manager unclutter chromium

# Audio
sudo apt install -y \
    pipewire pipewire-pulse wireplumber alsa-utils mpv

# Bluetooth + networking
sudo apt install -y \
    bluez bluez-tools network-manager

# Camera / video
sudo apt install -y \
    ffmpeg v4l-utils

# Suspend support
sudo apt install -y \
    acpid pm-utils
```

### 2.3 WiFi driver (RTL8812BU for Archer T3U Plus)

```bash
sudo apt install -y dkms bc build-essential linux-headers-$(uname -r)
cd /tmp
git clone https://github.com/morrownr/88x2bu-20210702.git
cd 88x2bu-20210702
sudo ./install-driver.sh
```

Verify after reboot:
```bash
iw list | grep -A5 "Supported interface modes"
# Must show "AP" in the list
```

### 2.4 Bluetooth firmware (RTL8761B for UB500)

```bash
sudo apt install -y firmware-realtek
# Reboot, then verify:
bluetoothctl show
# Should show "Powered: yes"
```

---

## 3. Boot Optimization — Fast + Silent + Splash Video

Goal: **BIOS logo → black → your Alfa Romeo splash video → BCM dashboard**.
No GRUB menu, no kernel log, no service status spam. The splash video
(not a Plymouth spinner) plays from early boot until the dashboard is ready.

### 3.1 BIOS settings (GA-N3050N-D2P)

Enter BIOS (press DEL at boot):
- **Boot → Fast Boot:** Enabled
- **Boot → Boot Option #1:** your SSD
- **Boot → Quiet Boot:** Enabled (shows Gigabyte logo briefly)
- **Peripherals → USB Configuration → Legacy USB:** Disabled
  (saves ~2s — Linux handles USB natively)
- **Power → Restore on AC Power Loss:** Power On (auto-boot after
  battery disconnect/reconnect)

### 3.2 GRUB — hidden, zero timeout, silent kernel

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

Key parameters:
- `quiet` — suppress kernel boot messages
- `loglevel=0` — no kernel messages on console
- `vt.global_cursor_default=0` — hide blinking text cursor
- `rd.systemd.show_status=false` — hide `[  OK  ] Started ...` lines
- `console=tty2` — redirect any remaining output to tty2 (invisible)
- `fsck.mode=skip` — skip filesystem check on SSD

**Do NOT add `splash`** — that keyword enables Plymouth, which would
show a spinner instead of your splash video.

### 3.3 Disable Plymouth (we use mpv splash instead)

Plymouth shows a spinner/logo during boot. We don't want that — we
want the mpv splash video to own the screen from early boot.

```bash
# Remove Plymouth completely
sudo apt remove -y plymouth plymouth-themes
# Or if you want to keep it installed but disabled:
sudo systemctl mask plymouth-start.service
sudo systemctl mask plymouth-quit.service
sudo systemctl mask plymouth-quit-wait.service
sudo systemctl mask plymouth-read-write.service

# Rebuild initramfs without Plymouth
sudo update-initramfs -u
```

### 3.4 BCM splash video — plays from early boot

The `bcm-splash-main.service` plays your MP4 fullscreen on the
framebuffer using `mpv --vo=drm` (no X server needed). It starts
immediately after the kernel hands off to systemd, and auto-stops
when BCM takes over the display.

```bash
# Install mpv
sudo apt install -y mpv

# Create splash directory and place your video
mkdir -p /opt/bcm/assets/splash

# Your video should be H.264, matching display resolution (e.g. 1024x600),
# 5-15 seconds, with optional audio track:
cp your_alfa_romeo_animation.mp4 /opt/bcm/assets/splash/main.mp4

# Install and enable the splash service
sudo cp /opt/bcm/config/systemd/bcm-splash-main.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable bcm-splash-main
```

**Test the splash manually** (without rebooting):
```bash
# This should play your video fullscreen, no X needed:
sudo mpv --fs --vo=drm --drm-connector=HDMI-A-1 /opt/bcm/assets/splash/main.mp4

# If --vo=drm doesn't work on your Intel GPU, try:
sudo mpv --fs --vo=drm /opt/bcm/assets/splash/main.mp4
# Or check which connectors exist:
ls /sys/class/drm/
# Look for card0-HDMI-A-1, card0-VGA-1, etc.
```

### 3.5 Disable unnecessary services (saves 3-5s boot time)

```bash
# Check what's slow:
systemd-analyze blame | head -20

# Disable common bloat:
sudo systemctl disable ModemManager 2>/dev/null
sudo systemctl disable apt-daily.timer
sudo systemctl disable apt-daily-upgrade.timer
sudo systemctl disable e2scrub_reap.service 2>/dev/null
sudo systemctl disable man-db.timer 2>/dev/null
sudo systemctl disable logrotate.timer
```

### 3.6 Use zram instead of swap

```bash
sudo apt install -y zram-tools
echo -e 'ALGO=lz4\nPERCENT=50' | sudo tee /etc/default/zramswap
sudo systemctl enable zramswap
```

### 3.7 Expected boot timeline

| Time | What happens |
|------|-------------|
| 0-3s | BIOS POST (Gigabyte logo — fast boot enabled) |
| 3s | GRUB (hidden, zero timeout, instant) |
| 3-5s | Kernel loads (black screen, silent — no Plymouth) |
| 5-6s | `bcm-splash-main` starts → **your MP4 plays fullscreen** |
| 6-12s | BCM loads behind splash (Flask starts, services init) |
| 12-14s | X starts, Chromium kiosk opens, splash auto-stops |
| **~14s** | **Dashboard visible** |

Cold boot: **~12-15s**. S3 resume: **~3-5s**.
After 24h standby, next wake replays the splash video (cold-like wake).

---

## 4. Kiosk Display Setup

### 4.1 Allow non-root startx

```bash
sudo tee /etc/X11/Xwrapper.config >/dev/null <<EOF
allowed_users=anybody
needs_root_rights=yes
EOF
```

### 4.2 Autologin on tty1

```bash
sudo mkdir -p /etc/systemd/system/getty@tty1.service.d
sudo tee /etc/systemd/system/getty@tty1.service.d/autologin.conf >/dev/null <<EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin $USER --noclear %I \$TERM
EOF
sudo systemctl daemon-reload
```

### 4.3 Auto-start X on login (no cursor)

```bash
cat >> ~/.bash_profile <<'EOF'

# BCM kiosk: start X on tty1 only, hide cursor
if [ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then
    exec startx -- -nocursor
fi
EOF
```

### 4.4 Create ~/.xinitrc — kiosk Chromium

**Single display (HDMI only):**

```bash
cat > ~/.xinitrc <<'XEOF'
#!/bin/sh
# BCM kiosk — single display

xset s off && xset -dpms && xset s noblank
unclutter -idle 0.5 -root &
matchbox-window-manager -use_titlebar no -use_cursor no &

# Wait for Flask (up to 60s)
for i in $(seq 1 60); do
    curl -sf http://localhost:5002 >/dev/null && break
    sleep 1
done

# Clear stale Chromium profile (prevents "restore session" bar)
rm -rf /tmp/bcm-chromium-main

# Main dashboard — full kiosk
chromium --kiosk --noerrdialogs --disable-infobars \
    --disable-features=TranslateUI --no-first-run --fast \
    --disable-session-crashed-bubble --disable-translate \
    --disable-pinch --overscroll-history-navigation=0 \
    --user-data-dir=/tmp/bcm-chromium-main \
    http://localhost:5002 &

wait
XEOF
chmod +x ~/.xinitrc
```

**Dual display (HDMI + USB-HDMI DisplayLink):**

```bash
cat > ~/.xinitrc <<'XEOF'
#!/bin/sh
# BCM kiosk — dual display (HDMI + DisplayLink)

xset s off && xset -dpms && xset s noblank
unclutter -idle 0.5 -root &
matchbox-window-manager -use_titlebar no -use_cursor no &

# Arrange displays (adjust output names from: xrandr --listmonitors)
sleep 1
xrandr --output HDMI-1 --primary --auto
xrandr --output DVI-I-1-1 --right-of HDMI-1 --mode 800x480 2>/dev/null

# Wait for Flask
for i in $(seq 1 60); do
    curl -sf http://localhost:5002 >/dev/null && break
    sleep 1
done

rm -rf /tmp/bcm-chromium-main /tmp/bcm-chromium-small

# Main display (HDMI) — port 5002
chromium --kiosk --noerrdialogs --disable-infobars \
    --disable-features=TranslateUI --no-first-run --fast \
    --disable-session-crashed-bubble --disable-translate \
    --disable-pinch --overscroll-history-navigation=0 \
    --user-data-dir=/tmp/bcm-chromium-main \
    http://localhost:5002 &

sleep 2

# Small display (DisplayLink) — port 5003
# window-position places it on the second monitor
MAIN_W=$(xrandr | grep 'HDMI-1' | grep -oP '\d+x\d+\+\K\d+' | head -1)
chromium --kiosk --noerrdialogs --disable-infobars \
    --disable-features=TranslateUI --no-first-run \
    --window-size=800,480 \
    --window-position=${MAIN_W:-1024},0 \
    --user-data-dir=/tmp/bcm-chromium-small \
    http://localhost:5003 &

wait
XEOF
chmod +x ~/.xinitrc
```

---

## 5. Suspend / Wake Setup

The power button on the x86 case and the ignition signal both control
suspend (S3 sleep). This gives instant ~2s wake instead of cold boot.

### 5.1 Configure ACPI power button for suspend

By default, pressing the power button shuts down the PC. Change it to
suspend instead:

```bash
# Install acpid
sudo apt install -y acpid

# Override power button action
sudo mkdir -p /etc/acpi/events
sudo tee /etc/acpi/events/power-button >/dev/null <<EOF
event=button/power
action=/usr/local/bin/bcm-power-toggle.sh
EOF

# Create the toggle script
sudo tee /usr/local/bin/bcm-power-toggle.sh >/dev/null <<'EOF'
#!/bin/bash
# Power button: toggle between suspend and wake
# (wake is handled by BIOS — pressing power in S3 wakes the system)

STATE=$(cat /sys/power/state 2>/dev/null)
if systemctl is-active --quiet bcm-headunit.service; then
    # BCM is running → stop it and suspend
    systemctl stop bcm-headunit.service
    sleep 1
    systemctl suspend
else
    # BCM is not running → just suspend
    systemctl suspend
fi
EOF
sudo chmod +x /usr/local/bin/bcm-power-toggle.sh

# Restart acpid
sudo systemctl enable acpid
sudo systemctl restart acpid
```

### 5.2 Auto-start BCM after resume from suspend

```bash
# systemd service that starts BCM on resume
sudo tee /etc/systemd/system/bcm-resume.service >/dev/null <<EOF
[Unit]
Description=BCM — Resume from suspend (restart headunit)
After=suspend.target

[Service]
Type=oneshot
ExecStart=/bin/bash -c 'sleep 2 && systemctl start bcm-headunit.service'

[Install]
WantedBy=suspend.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable bcm-resume
```

### 5.3 Ignition / Arduino poweroff → auto-suspend

The ignition watcher has built-in suspend support. When BCM stops
(ignition off, Arduino POWEROFF button, SWC MODE), it waits 5 seconds
then suspends to S3 automatically. This is enabled in the config:

```yaml
# config/bcm_config.yaml → power.ignition_watcher:
autostart: true            # start BCM immediately on boot
suspend_on_stop: true      # suspend to S3 when BCM stops
suspend_delay_seconds: 5   # wait before suspend (engine restart grace)
standby_max_hours: 24      # after 24h, next wake = cold boot with splash
```

No extra scripts needed — the ignition watcher handles everything.

### 5.4 BIOS wake settings

Enter BIOS (DEL at boot):
- **Power → Restore on AC Power Loss:** Power On (auto-boot if
  battery was disconnected and reconnected)
- **Power → Wake on USB:** Enabled (so USB Arduino can wake from S3)

### 5.5 Test suspend/wake from command line

```bash
# Manual suspend
sudo systemctl suspend

# Press power button → should wake and BCM starts in ~3s

# Check suspend worked
journalctl -u bcm-resume --no-pager -n5
```

---

## 6. BCM Installation and Services

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
# Log out and back in for this to take effect
```

### 6.3 Install systemd services

```bash
# Copy service files
sudo cp config/systemd/bcm-ignition-watcher.service /etc/systemd/system/
sudo cp config/systemd/bcm-headunit.service /etc/systemd/system/
sudo cp config/systemd/bcm-splash-main.service /etc/systemd/system/
sudo cp config/systemd/bcm-resume.service /etc/systemd/system/

# The ignition watcher service already has --autostart and x86 config.
# Edit the headunit service for x86:
sudo sed -i 's/--platform opi_pc/--platform x86/' /etc/systemd/system/bcm-headunit.service
sudo sed -i 's/bcm_config_opi_pc.yaml/bcm_config.yaml/' /etc/systemd/system/bcm-headunit.service

# Mask the kiosk service (.xinitrc handles Chromium, not systemd)
sudo systemctl mask bcm-kiosk.service

# Enable services
sudo systemctl daemon-reload
sudo systemctl enable bcm-ignition-watcher   # starts BCM on boot (--autostart)
sudo systemctl enable bcm-splash-main        # splash video on cold boot
sudo systemctl enable bcm-resume             # restart BCM after S3 wake

# Set up power button → suspend
sudo apt install -y acpid
sudo mkdir -p /etc/acpi/events
sudo tee /etc/acpi/events/power-button >/dev/null <<EOF
event=button/power
action=/usr/local/bin/bcm-power-toggle.sh
EOF
sudo cp /opt/bcm/config/scripts/bcm-power-toggle.sh /usr/local/bin/
sudo chmod +x /usr/local/bin/bcm-power-toggle.sh
sudo systemctl enable acpid
```

**What happens on boot:**
1. OS boots → splash video plays (mpv, no X)
2. `bcm-ignition-watcher` starts with `--autostart`
3. BCM starts immediately (no ignition file needed)
4. X starts → Chromium kiosk opens → splash auto-stops
5. Dashboard visible

**What happens on standby trigger** (power button / Arduino / ignition off):
1. BCM stops
2. Wait 5 seconds (grace period)
3. System suspends to S3 (~2W draw)
4. Press power button (or ignition on) → wake in ~2-3s
5. `bcm-resume.service` restarts BCM

**After 24h standby:** next wake replays the splash video (cold-like wake).

### 6.5 Test manually before reboot

```bash
source /opt/bcm/.venv/bin/activate
python3 main.py --platform x86 --config config/bcm_config.yaml --frontend

# In another terminal: open browser to http://localhost:5002
# Ctrl+C to stop
```

---

## 7. Troubleshooting

**Chromium not in kiosk mode (shows address bar, tabs):**
- The `--kiosk` flag in `.xinitrc` must be present
- Delete old profile: `rm -rf /tmp/bcm-chromium-main`
- Ensure matchbox-window-manager is running (`-use_titlebar no`)
- Check that `.xinitrc` is executable: `chmod +x ~/.xinitrc`

**Kernel messages visible during boot:**
- Run: `sudo update-grub` after editing `/etc/default/grub`
- Verify with: `cat /proc/cmdline` — should show `quiet splash loglevel=0`
- Install Plymouth: `sudo apt install plymouth plymouth-themes`

**GRUB menu still showing:**
- Set `GRUB_TIMEOUT=0` and `GRUB_HIDDEN_TIMEOUT=0`
- Run `sudo update-grub`
- Remove `/etc/grub.d/30_os-prober`: `sudo chmod -x /etc/grub.d/30_os-prober`

**Splash video not playing:**
- Check file exists: `ls -la /opt/bcm/assets/splash/main.mp4`
- Check mpv is installed: `which mpv`
- Test manually: `mpv --fs --vo=drm /opt/bcm/assets/splash/main.mp4`
- Check journal: `journalctl -u bcm-splash-main`

**USB-to-HDMI adapter not working:**
- DisplayLink adapters require proprietary `evdi` kernel module
- On Linux this is unreliable — **do not use**
- Use single HDMI for main display, skip small display

**Suspend not working:**
- Check: `cat /sys/power/state` — should list `mem` (S3)
- Test: `sudo systemctl suspend` — should sleep, power button wakes
- BIOS: ensure S3 is enabled (not S0ix/Modern Standby)
- Check acpid: `sudo systemctl status acpid`

**Arduino not detected:**
```bash
ls /dev/ttyACM* /dev/ttyUSB*
dmesg | grep -i "arduino\|acm\|usb"
# If permission denied:
sudo usermod -aG dialout $USER
```

**No sound from USB DAC:**
```bash
wpctl status                    # list PipeWire devices
wpctl set-default <sink-id>     # set DAC as default
speaker-test -D plughw:1,0 -t sine   # test ALSA directly
```

---

## 8. Arduino Wiring Reference

### Arduino #1 — Input controller (Pro Micro, 115200 baud)

```
Analog:
  A0 ← SWC pod 1 (resistor ladder)
  A1 ← LDR (ambient light)
  A6 ← SWC pod 2 / music panel

Digital (PC817 optoisolators, active-low):
  D2 ← Ignition/ACC 12V
  D3 ← Handbrake
  D4 ← Door FL        D5 ← Door FR
  D6 ← Door RL        D7 ← Door RR
  D8 ← Bonnet         D9 ← Trunk
  D10 ← Rain sensor

DS18B20 (1-Wire):  D14 ← Ext. temperature

HC-SR04 parking:
  D15 → TRIG (shared)
  D16 ← ECHO FL       A2 ← ECHO FR
  A3 ← ECHO RL        A7 ← ECHO RR
```

### Arduino #2 — Output controller (Nano, 9600 baud JSON)

```
Relay outputs:
  D2 → Lock       D3 → Unlock     D4 → Trunk
  D5 → Window up  D6 → Window dn  D7 → Headlights
  D8 → L blinker  D9 → R blinker  D10 → Wipers
  D11 → Horn

Input:
  D12 ← RF 433MHz receiver (RXB6)
```

### Serial protocol

See `src/input/arduino_serial.py` for the full parser. Messages:

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
