# BCM v7 — Orange Pi 5 Plus Installation Manual

Complete guide to deploying the BCM v7 headunit system on Orange Pi 5 Plus (RK3588) for the Alfa Romeo 156.

---

## 1. Hardware Requirements

### SBC

| Item | Specification |
|------|---------------|
| **Board** | Orange Pi 5 Plus |
| **SoC** | RK3588 (4× A76 + 4× A55) |
| **RAM** | 16 GB recommended (8 GB minimum) |
| **Storage** | 64 GB eMMC + 128 GB microSD (dashcam) |
| **Power** | 5.1V / 4A via USB-C |

### Peripherals

| Item | Model / Spec | Connection |
|------|-------------|------------|
| Display 1 (dashboard) | 4.3" TFT 800x480 | HDMI0 or DSI |
| Display 2 (multimedia) | 7" IPS 1024x600 | HDMI1 or DSI |
| USB DAC | ES9038Q2M module | USB 2.0 port |
| Amplifier (4ch) | TDA7388 board | RCA from DAC |
| Amplifier (sub) | TDA2050 board | RCA from DAC |
| K-Line transceiver | L9637D on perfboard | UART3 (pins 8, 10) |
| Parking sensors | 4× HC-SR04 | GPIO (see pin table) |
| Temperature sensor | DS18B20 waterproof probe | 1-Wire (pin 7) |
| Input controller | Arduino Pro Micro + rotary encoder | USB |
| Cameras | 2× AHD 720P | USB3.0 grabber |
| Microphone | USB condenser | USB |
| BT remote | Steering wheel remote | Bluetooth |
| Power supply | LM2596 12V→5.1V | USB-C PD trigger |

### Wiring & Electronics

See `schematics/README.md` for full assembly instructions, GPIO pinout, and circuit diagrams.

---

## 2. OS Installation

### 2.1 Download Armbian

Download Armbian for Orange Pi 5 Plus (bookworm/noble, CLI server image — no desktop needed):

```bash
# On your PC
wget https://redirect.armbian.com/orangepi5plus/Bookworm_current_minimal
# Or use Armbian's download page for the latest stable image
```

### 2.2 Flash to eMMC

Option A — Flash via SD card first, then transfer to eMMC:

```bash
# Flash SD card (on your PC)
sudo dd if=Armbian_*.img of=/dev/sdX bs=1M status=progress

# Boot from SD, then copy to eMMC
sudo armbian-install
# Select: Boot from eMMC, ext4 filesystem
```

Option B — Flash eMMC directly via USB-C (maskrom mode):

```bash
# Hold BOOT button, connect USB-C to PC
sudo rkdeveloptool db rk3588_spl_loader.bin
sudo rkdeveloptool wl 0 Armbian_*.img
sudo rkdeveloptool rd
```

### 2.3 First boot

```bash
# Connect via serial console (UART debug) or SSH
# Default: root / 1234, will prompt to create user

# Set hostname
sudo hostnamectl set-hostname bcm-v7

# Set timezone
sudo timedatectl set-timezone Europe/Warsaw

# Disable desktop environment (if accidentally installed)
sudo systemctl set-default multi-user.target
```

---

## 3. System Configuration

### 3.1 System packages

```bash
sudo apt update && sudo apt upgrade -y

# Core
sudo apt install -y \
    python3 python3-venv python3-pip \
    git build-essential pkg-config

# Audio (PipeWire)
sudo apt install -y \
    pipewire pipewire-pulse pipewire-alsa wireplumber \
    alsa-utils

# Bluetooth
sudo apt install -y \
    bluez bluez-tools

# Display / framebuffer
sudo apt install -y \
    python3-pygame libsdl2-dev libsdl2-image-dev \
    libdrm-dev

# Serial / UART
sudo apt install -y \
    python3-serial

# GPIO
sudo apt install -y \
    gpiod libgpiod-dev python3-libgpiod

# GStreamer (dashcam)
sudo apt install -y \
    gstreamer1.0-tools gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-good gstreamer1.0-plugins-bad \
    gstreamer1.0-plugins-ugly

# V4L2 (cameras)
sudo apt install -y \
    v4l-utils

# Optional: voice control
sudo apt install -y \
    python3-sounddevice portaudio19-dev
```

### 3.2 Enable hardware interfaces

```bash
# Enable UART3 (K-Line), SPI, I2C, 1-Wire via device tree overlays
# Edit /boot/armbianEnv.txt:
sudo nano /boot/armbianEnv.txt
```

Add/modify:

```
overlays=uart3 i2c3 spi1 w1-gpio
param_w1_pin=GPIO4_C1
param_w1_pin_int_pullup=1
```

```bash
# Reboot to apply
sudo reboot

# Verify UART3
ls -la /dev/ttyS3
# Should exist

# Verify 1-Wire
ls /sys/bus/w1/devices/
# Should show DS18B20 sensor ID (28-xxxx)

# Verify GPIO access
gpioinfo | head -20
```

### 3.3 User permissions

```bash
# Create bcm user (or use existing)
sudo useradd -m -s /bin/bash bcm
sudo usermod -aG gpio,i2c,spi,video,render,bluetooth,audio,dialout bcm

# Allow GPIO without root
sudo cp /opt/bcm/config/99-gpio.rules /etc/udev/rules.d/
# Content of 99-gpio.rules:
# SUBSYSTEM=="gpio", KERNEL=="gpiochip*", MODE="0660", GROUP="gpio"
sudo udevadm control --reload-rules
```

---

## 4. Application Deployment

### 4.1 Clone and install

```bash
sudo mkdir -p /opt/bcm
sudo chown bcm:bcm /opt/bcm

sudo -u bcm bash
cd /opt/bcm

git clone https://github.com/geek95dg/Alfa156-headunit.git .

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-opi.txt

# Verify
python -m pytest tests/ -v
```

### 4.2 Vosk speech models

```bash
cd /opt/bcm/src/voice/models

# Polish model (~40MB)
wget https://alphacephei.com/vosk/models/vosk-model-small-pl-0.22.zip
unzip vosk-model-small-pl-0.22.zip
mv vosk-model-small-pl-0.22 vosk-model-small-pl

# English model (~40MB)
wget https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip
unzip vosk-model-small-en-us-0.15.zip
mv vosk-model-small-en-us-0.15 vosk-model-small-en-us
```

### 4.3 PipeWire configuration

```bash
# User-level PipeWire config for USB DAC
sudo -u bcm mkdir -p /home/bcm/.config/pipewire/pipewire.conf.d
sudo -u bcm cp /opt/bcm/config/pipewire/pipewire.conf \
    /home/bcm/.config/pipewire/pipewire.conf.d/bcm-v7.conf

# Copy EQ profile
sudo -u bcm cp /opt/bcm/config/pipewire/eq-profile.json \
    /home/bcm/.config/pipewire/

# Restart PipeWire (as bcm user)
sudo -u bcm systemctl --user restart pipewire wireplumber

# Verify USB DAC is detected
sudo -u bcm wpctl status
# Should show ES9038Q2M as an audio sink
```

### 4.4 Arduino firmware

```bash
# On a PC with Arduino IDE:
# 1. Open arduino/rotary_encoder/rotary_encoder.ino
# 2. Select Board: Arduino Micro
# 3. Install HID-Project library
# 4. Upload to Arduino Pro Micro
# 5. Connect Arduino to OPi USB port

# Verify on OPi
sudo dmesg | tail -20
# Should show: "input: Arduino Micro as /devices/..."
cat /proc/bus/input/devices | grep -A5 Arduino
```

---

## 5. Systemd Services

### 5.1 Install services

```bash
sudo cp /opt/bcm/config/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
```

### 5.2 Service architecture

```
bcm-power.service          ← starts first (ignition, shutdown, backlight)
    ├── bcm-dashboard.service  ← depends on power (4.3" TFT renderer)
    ├── bcm-obd.service        ← depends on power (K-Line ECU comms)
    ├── bcm-dashcam.service    ← depends on power (GStreamer recording)
    ├── bcm-voice.service      ← depends on power (Vosk recognition)
    └── bcm-multimedia.service ← depends on power (OpenAuto + BT)
```

### 5.3 Enable auto-start

```bash
# Enable all services
sudo systemctl enable bcm-power bcm-dashboard bcm-obd \
    bcm-dashcam bcm-voice bcm-multimedia

# Start manually (for testing)
sudo systemctl start bcm-power

# Check status
sudo systemctl status bcm-power bcm-dashboard bcm-obd
```

### 5.4 Service paths

All services expect the application at `/opt/bcm` with a virtualenv at `/opt/bcm/venv`.

Key environment variables set by services:
- `PYTHONPATH=/opt/bcm`
- `BCM_PLATFORM=opi`
- `SDL_VIDEODRIVER=kmsdrm` (dashboard service)

### 5.5 Logs

```bash
# View service logs
journalctl -u bcm-power -f
journalctl -u bcm-dashboard -f

# Application logs
tail -f /opt/bcm/logs/bcm.log
```

---

## 6. Display Configuration

### 6.1 Dual display setup

The OPi 5 Plus has 2 HDMI outputs. Configure them:

```bash
# List connected displays
cat /sys/class/drm/card*/status

# Typical setup:
# HDMI-A-1 → 4.3" TFT (800x480, dashboard)
# HDMI-A-2 → 7" IPS (1024x600, multimedia / Android Auto)
```

### 6.2 Framebuffer for dashboard

The dashboard renders directly to framebuffer (no Xorg/Wayland needed):

```bash
# Check framebuffer
fbset -fb /dev/fb0

# Test pattern
cat /dev/urandom > /dev/fb0

# Dashboard uses SDL_VIDEODRIVER=kmsdrm for direct rendering
# This is set in bcm-dashboard.service
```

### 6.3 Backlight control

PWM backlight is managed by the power module:
- Pin 32 (PWM2) → 4.3" dashboard
- Pin 33 (PWM3) → 7" multimedia

Both screens are always linked to the same brightness level.

**Auto-brightness (light sensor):**
- LDR photoresistor on Arduino A1 reads ambient light every 2s
- Maps light level to brightness: bright sun → 100%, darkness → 15%
- Arduino sends `LIGHT:XXX` via serial, BCM adjusts both backlights

**Manual brightness (stalk button):**
- Spare button on steering column stalk (manettka) connected to Arduino A2
- Each press cycles: 15% → 30% → 45% → 60% → 80% → 100% → 15% ...
- Manual override active until ignition off, then reverts to auto sensor

Press F9 in VM to simulate the stalk button.

---

## 7. Audio Setup

### 7.1 USB DAC verification

```bash
# Check DAC is detected
aplay -l
# Should list ES9038Q2M as a USB audio device

# PipeWire status
wpctl status
# Look for: ES9038Q2M [vol: X.XX]

# Set as default sink
wpctl set-default <node-id>

# Test playback
speaker-test -t wav -c 2 -D plughw:CARD=ES9038Q2M
```

### 7.2 Audio chain

```
PipeWire (software mixer + EQ)
    ↓ USB
ES9038Q2M DAC (32-bit, 129dB SNR)
    ↓ RCA L/R
TDA7388 (4× 41W Class AB)  →  4 speakers (front L/R, rear L/R)
TDA2050 (32W Class AB mono) →  subwoofer
    ↑ 12V direct (25A fused)
```

### 7.3 EQ presets

EQ is managed via PipeWire filter chain. Presets defined in `config/pipewire/eq-profile.json`:
- **Flat** — no processing
- **Rock** — boosted lows + highs
- **Jazz** — warm mids emphasis
- **Bass Boost** — +6dB below 120Hz
- **Custom** — user-defined 10-band parametric

Switch presets via settings menu (press H on dashboard) or voice: "zmien styl" / "change theme".

---

## 8. K-Line / OBD-II Setup

### 8.1 Hardware verification

```bash
# Check UART3 is available
ls -la /dev/ttyS3

# Test serial loopback (short TX to RX)
stty -F /dev/ttyS3 10400 raw
echo "test" > /dev/ttyS3 &
cat /dev/ttyS3
```

### 8.2 ECU communication

The OBD module communicates with the Bosch EDC15C7 ECU at 10400 baud using KWP2000:

1. **5-baud init** to address 0x01
2. **KWP2000 fast init** handshake
3. **PID requests** for RPM, speed, coolant temp, fuel rate, etc.

Config in `bcm_config.yaml`:
```yaml
serial:
  kline:
    port_opi: /dev/ttyS3
    baudrate: 10400
    ecu_address: 0x01
```

### 8.3 Troubleshooting K-Line

```bash
# Check L9637D wiring
# Pin 6 (K-Line) should show ~12V idle (pulled up by 510Ω)

# Monitor raw serial traffic
picocom /dev/ttyS3 -b 10400 --imap lfcrlf

# Check user has dialout group
groups bcm | grep dialout
```

---

## 9. Parking Sensors

### 9.1 Verify GPIO

```bash
# Check pin access
gpioget gpiochip4 16  # TRIG pin — should read 0
gpioget gpiochip4 18  # ECHO pin 1

# Quick test (trigger + measure echo)
gpioset gpiochip4 16=1
sleep 0.00001
gpioset gpiochip4 16=0
# ECHO pin should pulse high for distance measurement
```

### 9.2 Sensor calibration

HC-SR04 measures distance by timing the ECHO pulse:
- Distance (cm) = pulse_duration × 17150
- Zones: safe (>100cm), caution (50-100cm), warning (30-50cm), danger (<30cm)
- Buzzer frequency increases as distance decreases

---

## 10. Camera & Dashcam

### 10.1 Verify cameras

```bash
# List V4L2 devices
v4l2-ctl --list-devices

# Test camera feed
ffplay /dev/video0 -video_size 1280x720

# Check AHD grabber channels
v4l2-ctl --device=/dev/video0 --get-input
v4l2-ctl --device=/dev/video0 --set-input=0   # Front cam
v4l2-ctl --device=/dev/video0 --set-input=1   # Rear cam
```

### 10.2 Dashcam storage

```bash
# Mount dedicated SD card for recordings
sudo mkdir -p /media/dashcam
sudo mount /dev/mmcblk1p1 /media/dashcam

# Add to fstab for auto-mount
echo "/dev/mmcblk1p1 /media/dashcam ext4 defaults,noatime 0 2" | sudo tee -a /etc/fstab

# Config
# camera.recording_path: /media/dashcam
# camera.segment_minutes: 5
# camera.max_storage_gb: 128
```

Dashcam records in H.264, 5-minute segments, auto-deletes oldest when storage exceeds 128 GB.

---

## 11. Bluetooth

### 11.1 Enable BT

```bash
# Check BT adapter (OPi 5 Plus has built-in BT 5.0)
bluetoothctl show

# Enable
bluetoothctl power on
bluetoothctl discoverable on
bluetoothctl pairable on

# Pair phone
bluetoothctl scan on
# Wait for phone to appear
bluetoothctl pair XX:XX:XX:XX:XX:XX
bluetoothctl trust XX:XX:XX:XX:XX:XX
bluetoothctl connect XX:XX:XX:XX:XX:XX
```

### 11.2 A2DP audio streaming

PipeWire handles A2DP sink automatically. Once paired, the phone can stream audio:

```bash
# Verify A2DP sink
wpctl status | grep -i bluetooth
```

### 11.3 HFP hands-free

Phone calls route through PipeWire with automatic audio ducking (music volume reduced during calls).

---

## 12. Voice Control

### 12.1 Microphone setup

```bash
# List input devices
arecord -l

# Test recording
arecord -f S16_LE -r 16000 -c 1 -d 5 /tmp/test.wav
aplay /tmp/test.wav

# Set USB mic as default source
wpctl set-default <source-node-id>
```

### 12.2 Wake word

- Polish: **"Hej komputer"**
- English: **"Hey computer"**

After wake word detection, speak a command within 5 seconds.

### 12.3 SWC remote (steering wheel buttons)

The steering wheel control remote uses two round button pods with a decoder box:
- Red wire → 12V accessory
- Black wire → chassis ground
- White wire → Arduino Pro Micro pin A0

Calibrate after installation:
1. Connect Arduino to PC (or SSH to OPi and open `picocom /dev/ttyACM0 -b 115200`)
2. Hold HOME + BACK buttons during Arduino boot
3. Press each button when prompted
4. Values saved to EEPROM

### 12.4 Available commands

| Polish | English | Action |
|--------|---------|--------|
| pokaz temperature | show temperature | Display exterior temp |
| wlacz radio | turn on radio | Switch audio source |
| nastepny utwor | next track | Next track |
| poprzedni utwor | previous track | Previous track |
| glosniej | volume up | Volume +10% |
| ciszej | volume down | Volume -10% |
| pokaz zuzycie | show consumption | Show fuel consumption |
| status samochodu | car status | Show vehicle status |
| nagrywaj | start recording | Start dashcam |
| zatrzymaj nagrywanie | stop recording | Stop dashcam |
| zmien styl | change theme | Cycle dashboard theme |
| zmien jezyk | change language | Switch PL/EN |

---

## 13. Power Management

### 13.1 Boot sequence

```
Ignition ON (12V signal via PC817 optoisolator)
    ↓
bcm-power.service starts (STANDBY → WAKE → ACTIVE)
    ↓
bcm-dashboard.service starts (gauges render in ~2s)
    ↓
bcm-obd.service starts (K-Line init, ECU handshake)
    ↓
bcm-dashcam.service, bcm-voice.service, bcm-multimedia.service
```

**Target boot time:** < 3 seconds from ignition to dashboard visible.

### 13.2 Shutdown sequence

```
Ignition OFF detected
    ↓
30-second delay (configurable: power.shutdown_delay_seconds)
    ↓
bcm-power publishes "power.shutdown" event
    ↓
All modules save state & stop gracefully
    ↓
Backlight fades out (1 second)
    ↓
OPi shuts down (sudo poweroff)
```

### 13.3 Fast boot optimization

```bash
# Disable unnecessary services
sudo systemctl disable NetworkManager-wait-online
sudo systemctl disable apt-daily.timer
sudo systemctl disable apt-daily-upgrade.timer
sudo systemctl disable man-db.timer

# Reduce kernel boot time
# Add to /boot/armbianEnv.txt:
# extraargs=quiet loglevel=0 fastboot

# Pre-load Python bytecache
cd /opt/bcm && python -m compileall src/
```

---

## 14. Maintenance

### 14.1 Update application

```bash
sudo -u bcm bash
cd /opt/bcm
source venv/bin/activate

git pull origin main
pip install -r requirements.txt -r requirements-opi.txt

# Run tests
python -m pytest tests/ -v

# Restart services
sudo systemctl restart bcm-power
```

### 14.2 Backup config

```bash
# Backup current settings
cp /opt/bcm/config/bcm_config.yaml /opt/bcm/config/bcm_config.yaml.bak

# Backup dashcam footage (optional)
rsync -av /media/dashcam/ /media/usb-backup/dashcam/
```

### 14.3 Monitoring

```bash
# System health
htop                           # CPU/RAM usage
sensors                        # SoC temperature
df -h                          # Disk usage
journalctl -u bcm-* --since today  # Today's logs

# BCM status
sudo systemctl status bcm-power bcm-dashboard bcm-obd bcm-dashcam bcm-voice bcm-multimedia
```

### 14.4 Common issues

| Problem | Solution |
|---------|----------|
| No display output | Check HDMI cable, verify `fbset -fb /dev/fb0` |
| No audio from DAC | `wpctl status`, check USB DAC is default sink |
| K-Line timeout | Check L9637D wiring, verify 510Ω pull-up, test with picocom |
| Parking sensors stuck | Check HC-SR04 VCC (5V), verify ECHO voltage dividers |
| High CPU temp | Check heatsink on RK3588, add small fan if >75C |
| Dashboard freezes | Check `journalctl -u bcm-dashboard`, restart service |
| Bluetooth won't pair | `bluetoothctl power off && bluetoothctl power on`, re-scan |
| Vosk not loading | Verify model paths in config, check RAM usage (needs ~200MB) |
| Boot too slow | Apply fast boot optimizations (section 13.3) |

---

## 15. Pin Reference (Quick Card)

```
Orange Pi 5 Plus — 40-pin GPIO Header
┌──────────────────────────────────────┐
│  Pin 7  — DS18B20 1-Wire (temp)      │
│  Pin 8  — UART3 TX (K-Line)          │
│  Pin 10 — UART3 RX (K-Line)          │
│  Pin 12 — Buzzer (parking)           │
│  Pin 16 — HC-SR04 TRIG (shared)      │
│  Pin 18 — HC-SR04 ECHO #1 (rear-L)  │
│  Pin 22 — HC-SR04 ECHO #2 (rear-CL) │
│  Pin 24 — HC-SR04 ECHO #3 (rear-CR) │
│  Pin 26 — HC-SR04 ECHO #4 (rear-R)  │
│  Pin 29 — Ignition (optoisolator)    │
│  Pin 31 — Door open (optoisolator)   │
│  Pin 32 — PWM2 (4.3" backlight)      │
│  Pin 33 — PWM3 (7" backlight)        │
│  Pin 35 — Washer sprayer (opto)      │
│  Pin 37 — Central lock (opto)        │
└──────────────────────────────────────┘
```

---

## 16. First Run Checklist

After full installation, verify each subsystem:

- [ ] OPi boots from eMMC, SSH accessible
- [ ] UART3 visible: `ls /dev/ttyS3`
- [ ] 1-Wire sensor visible: `ls /sys/bus/w1/devices/28-*`
- [ ] GPIO accessible: `gpioinfo | grep -c "unnamed"`
- [ ] PipeWire running: `systemctl --user status pipewire`
- [ ] USB DAC detected: `aplay -l | grep ES9038`
- [ ] Speakers output: `speaker-test -t wav -c 2`
- [ ] Dashboard renders on 4.3" TFT (check `/dev/fb0`)
- [ ] Arduino encoder works: `evtest /dev/input/eventX`
- [ ] Cameras visible: `v4l2-ctl --list-devices`
- [ ] Bluetooth adapter up: `bluetoothctl show`
- [ ] K-Line responds: ECU handshake via `bcm-obd.service`
- [ ] Parking sensors trigger: reverse gear → overlay appears
- [ ] Voice responds: "Hej komputer" → "Slucham"
- [ ] Dashcam records: check `/media/dashcam/*.mp4`
- [ ] `python -m pytest tests/ -v` — all tests pass
- [ ] All 6 systemd services: `sudo systemctl status bcm-*`
