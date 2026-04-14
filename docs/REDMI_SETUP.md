# BCM v8.5 — Redmi Note 8 Pro (Ubuntu Touch) — Setup & Testing Guide

## Overview

This guide covers running BCM v8.5 on a **Redmi Note 8 Pro** (codename `begonia`)
with **Ubuntu Touch** instead of the Orange Pi 5 Plus. The phone's 6.53" screen
replaces the 7/8" touchscreen, and all GPIO-dependent modules are offloaded to
an Arduino sensor hub via USB-C OTG.

**Testing is organized in 4 phases** — you can start with just the phone on your
desk and progressively add hardware.

---

## Prerequisites

### Hardware (minimum for Phase 1)
- Redmi Note 8 Pro with **unlocked bootloader**
- USB-C cable for flashing
- PC with `fastboot` and `adb`

### Software
- Ubuntu Touch for `begonia` — https://devices.ubuntu-touch.io/device/begonia/
- UBports Installer (recommended for flashing)

---

## Phase 1: Desk Testing — Phone Only (No External Hardware)

**Goal:** Run BCM dashboard on the phone, verify web UI, demo data, themes.

### 1.1 Install Ubuntu Touch

```bash
# Option A: UBports Installer (GUI — recommended)
# Download from https://ubports.com/installer
# Select device: Redmi Note 8 Pro (begonia)
# Follow on-screen instructions (unlock bootloader, flash)

# Option B: Manual fastboot
fastboot flash boot boot.img
fastboot flash system system.img
fastboot flash userdata userdata.img
fastboot reboot
```

### 1.2 Enable Developer Mode

On the phone:
1. Settings → About → tap Build Number 7 times
2. Settings → Developer → enable Developer Mode
3. Settings → Developer → enable SSH (note the password)

### 1.3 Connect via SSH

```bash
# Find phone IP (usually via USB network 10.15.19.82)
ssh phablet@10.15.19.82
```

### 1.4 Set Up Python Environment

Ubuntu Touch uses a read-only root filesystem. Use Libertine containers or
the writable home directory:

```bash
# Make the filesystem writable temporarily
sudo mount -o remount,rw /

# Install Python 3 and pip (if not already available)
sudo apt update
sudo apt install -y python3 python3-pip python3-venv git

# Clone the project
cd ~
git clone https://github.com/geek95dg/Alfa156-headunit.git
cd Alfa156-headunit

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt -r requirements-redmi.txt
```

### 1.5 Run BCM in Desk Testing Mode

```bash
# Desk mode: all sensors simulated, demo data active
./run_redmi.sh --desk
```

### 1.6 Access the Dashboard

Open the phone's browser (Morph Browser on UT):
- **Main display:** `http://localhost:5002`
- **Small display:** `http://localhost:5003`

Or from your PC on the same network:
- `http://<phone-ip>:5002`
- `http://<phone-ip>:5003`

### 1.7 Phase 1 Test Checklist

- [ ] `./run_redmi.sh --desk` starts without errors
- [ ] `http://localhost:5002` loads in phone browser
- [ ] Init screen → auto-transition to A1 Dashboard
- [ ] All screens render: A1 (Dashboard), A2 (AA placeholder), A3 (Trip),
      A4 (Weather), A5 (Service), A6 (DVR), A7 (Performance)
- [ ] Theme switching works: Heritage / Modern / Autodelta
- [ ] Language switching: PL ↔ EN
- [ ] `http://localhost:5003` shows the static 2×2 stats grid (small display)
- [ ] Press R key → reverse camera overlay appears
- [ ] WebSocket data updates in real-time (gauges animate)
- [ ] REST API responds: `curl http://localhost:5002/api/data`
- [ ] Phone performance acceptable (no excessive lag)

---

## Phase 2: Audio Testing — Phone Speakers + Bluetooth

**Goal:** Test audio routing through phone speakers, then Bluetooth.

### 2.1 Audio via Phone Speakers

BCM uses PipeWire/PulseAudio. On Ubuntu Touch, PulseAudio is the default
audio server. Test with built-in speakers first:

```bash
# Verify PulseAudio is running
pactl info

# Test speaker output
speaker-test -t wav -c 2 -l 1

# Run BCM — audio should route to phone speaker
./run_redmi.sh --desk
```

In the BCM web UI, test:
- [ ] System notification sounds play
- [ ] Volume control works (A1 dashboard)

### 2.2 Bluetooth Audio (A2DP)

Pair your phone with a Bluetooth speaker or car stereo (for desk testing):

```bash
# Scan for BT devices
bluetoothctl scan on

# Pair and connect
bluetoothctl pair XX:XX:XX:XX:XX:XX
bluetoothctl connect XX:XX:XX:XX:XX:XX
```

Test in BCM:
- [ ] BT device appears in Settings screen
- [ ] Music playback info shows on A1 (artist, title)
- [ ] Audio streams to BT speaker

### 2.3 Phase 2 Test Checklist

- [ ] PulseAudio detected and working
- [ ] Phone speaker outputs audio
- [ ] Bluetooth pairing works from BCM Settings
- [ ] A2DP streaming works
- [ ] Volume control adjusts output level

---

## Phase 3: USB-C OTG Hub + External Hardware

**Goal:** Connect USB accessories via OTG hub — USB-UART for OBD, cameras.

### 3.1 USB-C OTG Hub Setup

Connect a powered USB-C hub to the phone. See `docs/REDMI_USB_HUB.md` for
recommended hubs and wiring.

```bash
# Verify USB devices are detected
lsusb

# Check serial devices
ls -la /dev/ttyUSB*
```

### 3.2 OBD-II via USB-UART Adapter

Connect a CP2102 or CH340 USB-UART adapter to the OTG hub:

```bash
# Verify adapter is detected
dmesg | grep ttyUSB

# The K-Line adapter should appear as /dev/ttyUSB1
# (ttyUSB0 is reserved for sensor hub)
```

Update `config/bcm_config_redmi.yaml` if your port differs:
```yaml
serial:
  kline:
    port_redmi: /dev/ttyUSB1  # adjust to your adapter
```

Test OBD communication:
```bash
# Run with OBD module only
./run_redmi.sh --modules obd,dashboard
```

- [ ] K-Line adapter detected as /dev/ttyUSBx
- [ ] 5-baud initialization succeeds (in car only)
- [ ] RPM, coolant temp, speed data appears on A1

### 3.3 USB DAC (Audio Upgrade)

Connect ES9038Q2M USB DAC to the OTG hub:

```bash
# Verify DAC is detected
pactl list sinks short

# Set as default sink
pactl set-default-sink <dac-sink-name>
```

Update config:
```yaml
audio:
  dac: ES9038Q2M  # change from 'builtin'
```

- [ ] USB DAC appears in PulseAudio sinks
- [ ] Audio routes through DAC → amplifiers → speakers

### 3.4 Camera / DVR

Connect USB AHD grabber to the OTG hub:

```bash
# Check video devices
v4l2-ctl --list-devices

# Test capture
ffmpeg -f v4l2 -i /dev/video0 -frames 1 test.jpg
```

- [ ] AHD grabber detected
- [ ] Front camera captures frames
- [ ] DVR recording starts (check recording path)

### 3.5 Phase 3 Test Checklist

- [ ] USB-C OTG hub recognized, all devices enumerated
- [ ] At least 3 USB devices work simultaneously
- [ ] USB-UART adapter works for OBD
- [ ] USB DAC outputs audio (if connected)
- [ ] Camera capture works (if connected)
- [ ] No USB bandwidth issues or disconnects

---

## Phase 4: Arduino Sensor Hub + Full System

**Goal:** Connect Arduino sensor hub for parking sensors, ignition detection,
temperature, and relay control. Full system integration.

### 4.1 Flash Arduino Sensor Hub Firmware

The sensor hub Arduino handles all GPIO-dependent modules. Flash the firmware:

```bash
# From a PC with Arduino IDE
# Open: arduino/sensor_hub/sensor_hub.ino
# Board: Arduino Nano (or Pro Mini)
# Upload
```

**Sensor hub Arduino wiring:**
| Arduino Pin | Function | Connected To |
|-------------|----------|--------------|
| D2 | HC-SR04 TRIG (shared) | 4x sensor TRIG |
| D3 | HC-SR04 ECHO 1 (LL) | Sensor 1 ECHO |
| D4 | HC-SR04 ECHO 2 (CL) | Sensor 2 ECHO |
| D5 | HC-SR04 ECHO 3 (CR) | Sensor 3 ECHO |
| D6 | HC-SR04 ECHO 4 (RR) | Sensor 4 ECHO |
| D7 | Buzzer | Piezo buzzer |
| D8 | Ignition input | PC817 optoisolator |
| D9 | Door input | PC817 optoisolator |
| D10 | Rain sensor input | PC817 optoisolator |
| D11 | Wiper relay output | Relay module |
| D12 | Central lock input | PC817 optoisolator |
| A0 | DS18B20 DATA | Temperature sensor |
| USB | Serial 115200 baud | → USB-C OTG hub → Redmi |

### 4.2 Connect and Test Sensor Hub

```bash
# Verify sensor hub appears
ls -la /dev/ttyUSB0

# Test communication
python3 -c "
import serial, json, time
s = serial.Serial('/dev/ttyUSB0', 115200, timeout=1)
time.sleep(2)
while True:
    line = s.readline().decode().strip()
    if line:
        print(json.loads(line))
"
```

### 4.3 Run Full System

```bash
# Production mode (no --desk flag)
./run_redmi.sh
```

### 4.4 Phase 4 Test Checklist

- [ ] Sensor hub Arduino responds on /dev/ttyUSB0
- [ ] Parking sensor distances update on small display
- [ ] Buzzer sounds when distance < 0.5m
- [ ] Temperature reading appears on A1
- [ ] Ignition signal detected (in car)
- [ ] Rain sensor triggers wiper relay (if connected)
- [ ] Central lock Arduino on /dev/ttyUSB2 responds
- [ ] Full system runs stable for 30+ minutes

---

## Phase 5: Car Installation

**Goal:** Mount everything in the Alfa 156 and verify in-car operation.

### 5.1 Mounting

- Mount phone in DIN slot or custom bracket (landscape orientation)
- Route USB-C OTG hub behind dashboard
- Mount 4.3" second screen in instrument cluster area
- Connect to car 12V via LM2596 (5.1V for USB hub power)

### 5.2 Second Display Setup

Connect 4.3" screen via USB-C to HDMI adapter (see `docs/REDMI_USB_HUB.md`):

```bash
# Open Chromium/Morph on second display
# Point to small display server
http://localhost:5003
```

### 5.3 In-Car Test Checklist

- [ ] Phone powers on with ignition
- [ ] BCM auto-starts (systemd service or UT app)
- [ ] OBD reads real ECU data
- [ ] Audio plays through car amplifiers
- [ ] Parking sensors work during reverse
- [ ] Camera switches on reverse gear
- [ ] GPS acquires fix
- [ ] Bluetooth pairs with driver's phone
- [ ] Android Auto connects (wireless via WiFi AP)
- [ ] System survives engine vibration
- [ ] USB connections remain stable
- [ ] Temperature doesn't cause throttling

---

## Auto-Start on Boot

### Option A: Systemd User Service

```bash
mkdir -p ~/.config/systemd/user/

cat > ~/.config/systemd/user/bcm.service << 'EOF'
[Unit]
Description=BCM v8.5 Alfa Romeo 156 Head Unit
After=network.target

[Service]
Type=simple
WorkingDirectory=%h/Alfa156-headunit
ExecStart=%h/Alfa156-headunit/run_redmi.sh
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF

systemctl --user enable bcm.service
systemctl --user start bcm.service
```

### Option B: UT Autostart Script

```bash
mkdir -p ~/.config/autostart/
cat > ~/.config/autostart/bcm.sh << 'EOF'
#!/bin/bash
sleep 10  # Wait for system to settle
cd ~/Alfa156-headunit
./run_redmi.sh &
EOF
chmod +x ~/.config/autostart/bcm.sh
```

---

## Troubleshooting

### USB OTG Not Working
```bash
# Check OTG mode
cat /sys/class/typec/port0/data_role
# Should show "host" — if "device", switch:
echo host | sudo tee /sys/class/typec/port0/data_role
```

### Serial Devices Not Appearing
```bash
# Check kernel modules
lsmod | grep -E "ch341|cp210x|ftdi"
# If missing:
sudo modprobe cp210x
sudo modprobe ch341
```

### Audio Not Working
```bash
# Check PulseAudio
pactl info
pactl list sinks short

# Restart PulseAudio
pulseaudio --kill
pulseaudio --start
```

### Phone Overheating
The Helio G90T can throttle under sustained load. Mitigations:
- Use a phone case with ventilation/heatsink
- Reduce dashboard FPS in config (`display.dashboard.fps: 10`)
- Disable modules you don't need
- Ensure good airflow in the DIN slot

### Permission Denied on /dev/ttyUSB*
```bash
# Add user to dialout group
sudo usermod -aG dialout phablet
# Or set permissions directly
sudo chmod 666 /dev/ttyUSB*
```

### Web UI Slow / Laggy
- Reduce animation complexity: use "Modern" theme (lightest)
- Lower WebSocket update rate in config
- Close other apps on the phone
- Disable unused modules

---

## Performance Notes

| Aspect | Redmi Note 8 Pro | Orange Pi 5 Plus |
|--------|-----------------|------------------|
| CPU | Helio G90T (2×A76 + 6×A55) | RK3588 (4×A76 + 4×A55) |
| RAM | 6 GB | 8-16 GB |
| GPU | Mali-G76 MC4 | Mali-G610 MP4 |
| USB | 1× USB-C OTG | 1×USB3 + 2×USB2 + USB-C |
| Display | 1× built-in 6.53" | 2× HDMI 2.1 |
| GPIO | None (sensor hub) | 40-pin header |
| Storage | 128 GB UFS 2.1 | 64 GB eMMC + NVMe |
| WiFi | WiFi 5 (ac) | WiFi 6 (ax) |
| BT | 5.0 | 5.0 |
| GPS | Built-in | External USB module |
| Cellular | Built-in 4G LTE | External USB modem |

**Advantages of Redmi:** Built-in GPS, LTE, BT, mic, screen, battery.
**Advantages of OPi:** Multiple USB ports, native GPIO, dual HDMI, more RAM.
