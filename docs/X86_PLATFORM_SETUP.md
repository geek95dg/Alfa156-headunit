# BCM v8.5 — x86 Platform Setup (Car PC)

Running the BCM headunit on a standard x86 PC/SBC (Intel Celeron N or
similar) inside the car. All GPIO is handled by USB Arduinos — the x86
board only needs USB + HDMI + audio.

---

## 1. Hardware Requirements

### 1.1 Minimum x86 specs

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| CPU | Celeron N3350 (2C/2T) | Celeron N100/N5105 (4C/4T) |
| RAM | 2 GB | 4 GB |
| Storage | 16 GB eMMC/SSD | 64 GB+ SSD (DVR recording) |
| USB | 4× USB 2.0 (use hub) | 6+ USB (mix 2.0/3.0) |
| HDMI | 1× HDMI | 2× HDMI (main + small display) |
| Audio | USB DAC (ES9038Q2M) | same |
| Network | USB WiFi/LTE | built-in WiFi + USB LTE |

Suitable boards: any mini-ITX/thin-ITX with Celeron N, Pentium Silver,
or even old Core i3/i5. Fanless preferred for car environment.

### 1.2 Power supply — DC-ATX for car 12V

A standard ATX PSU can't run from car 12V. Use a **DC-ATX converter**
(also called PicoPSU or DC-DC ATX). This takes car 12V and outputs all
ATX voltages (3.3V, 5V, 12V, -12V) via the 24-pin ATX connector.

**Recommended options:**

| Module | Input | Output | Price (PLN) | Notes |
|--------|-------|--------|-------------|-------|
| **PicoPSU-160-XT** | 12-25V DC | 160W ATX | 150-250 | Most popular, proven |
| **M4-ATX** | 6-30V DC | 250W ATX | 300-500 | Has ignition logic built-in |
| **HD-Plex 200W** | 12-24V DC | 200W ATX | 200-350 | 19V laptop brick compatible |
| Generic "DC-ATX 200W" | 12-24V DC | 200W | 60-120 | AliExpress, works fine |

**Wiring diagram:**

```
Car Battery 12V ──┐
                  ├──[25A fuse]──► DC-ATX module ──► 24-pin ATX connector
                  │                    │                 └──► CPU 4/8-pin
                  │                    │
ACC/Ignition ─────┼──[PC817]──► Arduino (reports IGN:1 over USB serial)
                  │
                  └──[20A fuse]──► TDA7388 amp (direct 12V, no ATX needed)
```

### 1.3 DC-ATX wiring steps

1. **Input power:** Connect car 12V (after 25A fuse) to DC-ATX input.
   Use 2.5mm² wire minimum. Ground to chassis.

2. **ATX connectors:** Plug 24-pin into motherboard, 4-pin CPU power.
   The DC-ATX usually includes both cables.

3. **Power control (ignition on/off):** Two approaches:

   **Option A — Software controlled (recommended):**
   - DC-ATX always powered (car battery → DC-ATX → motherboard standby)
   - Arduino detects ignition 12V via optoisolator, sends `IGN:1` over serial
   - BCM ignition_watcher receives the serial event and starts the dashboard
   - On IGN off: BCM gracefully shuts down, x86 goes to S3 sleep or stays idle
   - Power draw in idle: ~3-5W (acceptable for car battery)

   **Option B — M4-ATX with built-in ignition logic:**
   - Wire ACC/ignition to M4-ATX "IGN" input
   - M4-ATX handles delayed startup (wait for cranking) and delayed shutdown
   - Programmable timers via DIP switches or USB config tool
   - More expensive but fully autonomous — works without software support

4. **Grounding:** Single chassis ground point near battery. Star topology —
   never daisy-chain ground wires.

### 1.4 Startup / shutdown sequence

```
Ignition ON
  → DC-ATX powers motherboard (or wakes from S3)
  → Linux boots (or resumes from suspend)
  → systemd starts bcm-ignition-watcher
  → Arduino reports IGN:1 over serial
  → ignition_watcher starts bcm-headunit.service
  → Flask starts, Chromium kiosk opens

Ignition OFF
  → Arduino reports IGN:0
  → ignition_watcher stops bcm-headunit
  → Optional: suspend to S3 (instant wake next time)
  → DC-ATX keeps standby power (motherboard draws <2W in S3)
```

### 1.5 Sleep vs always-on

| Mode | Wake time | Idle draw | Complexity |
|------|-----------|-----------|-----------|
| Always-on (idle) | Instant | 8-15W | Simple |
| S3 suspend | 2-5s | 2-3W | Needs `rtcwake` or WoL |
| Full shutdown + M4-ATX | 15-30s (cold boot) | <0.5W | M4-ATX handles everything |

For Celeron N with SSD: cold boot ≈ 10-15s, S3 resume ≈ 2s.

---

## 2. USB Device Layout

All I/O goes through USB. No PCIe GPIO card needed.

```
x86 motherboard USB ports
  ├── USB Hub (powered, 7-port)
  │     ├── Arduino Pro Micro #1 (input: SWC, buttons, LDR, ignition,
  │     │                          doors, handbrake, temp, rain, parking)
  │     ├── Arduino Nano #2 (output: relays for lock, lights, wipers,
  │     │                     windows + RF 433MHz receiver)
  │     ├── USB BT 5.0 dongle
  │     ├── USB GPS (NEO-M8N)
  │     ├── USB LTE modem (Huawei E3372)
  │     └── USB microphone
  ├── USB DAC (ES9038Q2M) → RCA → TDA7388 + TDA2050
  └── USB 4-ch AHD grabber (cameras)
```

### 2.1 Arduino #1 — Input controller

Reads all vehicle sensors and buttons, reports over USB Serial (115200 baud):

```
Analog inputs:
  A0 ← SWC pod 1 (resistor ladder, 12 buttons)
  A1 ← LDR (ambient light)
  A6 ← SWC pod 2 / music panel (resistor ladder)

Digital inputs (active-low, PC817 optoisolators):
  D2 ← Ignition/ACC 12V detect
  D3 ← Handbrake switch
  D4 ← Door FL (front-left)
  D5 ← Door FR (front-right)
  D6 ← Door RL (rear-left)
  D7 ← Door RR (rear-right)
  D8 ← Bonnet switch
  D9 ← Trunk switch
  D10 ← Rain sensor digital output

DS18B20 (1-Wire):
  D14 ← External temperature probe

HC-SR04 parking sensors:
  D15 (TRIG shared) → all 4 sensors
  D16 ← ECHO front-left
  A2 ← ECHO front-right
  A3 ← ECHO rear-left
  A7 ← ECHO rear-right

USB HID output: button keycodes (volume, media, nav)
Serial output: LIGHT, DOOR, HBRAKE, IGN, RAIN, TEMP, PARK messages
```

### 2.2 Arduino #2 — Output controller (relay board)

Controls relays and receives RF commands. JSON protocol over USB serial (9600 baud):

```
Digital outputs → relay module (10-channel):
  Relay 1: Central lock (LOCK)
  Relay 2: Central lock (UNLOCK)
  Relay 3: Trunk release
  Relay 4: Window up (all)
  Relay 5: Window down (all)
  Relay 6: Headlights (follow-me-home)
  Relay 7: Left blinker (greeting/alarm)
  Relay 8: Right blinker (greeting/alarm)
  Relay 9: Wiper motor relay
  Relay 10: Horn (alarm)

Input:
  RF 433MHz receiver (RXB6) ← key fob signal
```

---

## 3. Software Setup

### 3.1 OS installation

Any Debian 12+ / Ubuntu 22.04+ x86_64 works. Minimal server install
recommended (no desktop environment — BCM provides its own kiosk).

```bash
# After fresh install:
sudo apt update && sudo apt upgrade -y
sudo apt install -y \
    python3 python3-venv python3-pip python3-dev \
    git curl chromium xserver-xorg xinit \
    matchbox-window-manager unclutter x11-xserver-utils \
    pipewire pipewire-pulse wireplumber \
    bluez bluez-tools \
    ffmpeg v4l-utils
```

### 3.2 BCM installation

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

### 3.3 Configuration

Use the x86 config as base, adjust for your hardware:

```bash
cp config/bcm_config.yaml config/bcm_config_x86_car.yaml
```

Edit `config/bcm_config_x86_car.yaml`:
```yaml
system:
  name: BCM v8.5
  platform: x86
  log_level: INFO

# Arduino input controller serial port
arduino:
  input_port: /dev/ttyACM0    # Arduino #1 (auto-detected)
  input_baud: 115200

# Central lock Arduino
central_lock:
  port: /dev/ttyACM1           # Arduino #2
  baudrate: 9600
```

### 3.4 Autologin + kiosk (same as OPi)

Follow the same autologin → startx → .xinitrc pattern from the
OPi PC setup guide (Part 2). The kiosk chain is identical:

1. Autologin on tty1
2. `~/.bash_profile` runs `exec startx -- -nocursor`
3. `~/.xinitrc` starts matchbox + waits for Flask + opens Chromium kiosk

### 3.5 Systemd services

```bash
sudo cp config/systemd/bcm-ignition-watcher.service /etc/systemd/system/
sudo cp config/systemd/bcm-headunit.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable bcm-ignition-watcher
```

Edit `/etc/systemd/system/bcm-headunit.service` — change the ExecStart
config path to your x86 config:

```ini
ExecStart=/bin/bash -c '... main.py --platform x86 --config config/bcm_config_x86_car.yaml --frontend'
```

---

## 4. x86 vs OPi — Feature Parity

| Feature | x86 + USB Arduinos | OPi 5 Pro (native GPIO) |
|---------|-------------------|------------------------|
| Dashboard UI | Identical | Identical |
| Audio/EQ | Identical (USB DAC) | Identical |
| Android Auto | Identical | Identical |
| Bluetooth | Identical (USB dongle) | Built-in |
| Parking sensors | Arduino timing (better!) | GPIO (tight timing) |
| Door/handbrake/ignition | Arduino + optoisolators | GPIO + optoisolators |
| Central lock + relays | Arduino #2 | Arduino #2 (same) |
| Wipers/lights | Arduino #2 relays | Arduino #2 (same) |
| Boot time (cold) | 10-15s (SSD) | 8-12s (eMMC) |
| Power draw (active) | 15-25W | 5-10W |
| Power draw (idle) | 3-5W (S3: 2W) | 2-3W |
| Form factor | Mini-ITX: 170×170mm | 56×90mm |
| Cost | Free (existing HW) | 350-450 PLN |

---

## 5. Arduino Serial Protocol Reference

### Input Arduino (#1) → BCM (115200 baud)

| Message | Example | Frequency | Event bus topic |
|---------|---------|-----------|-----------------|
| `LIGHT:XXX` | `LIGHT:512` | Every 2s | `arduino.light_level` |
| `DOOR:keys` | `DOOR:FL=1,FR=0,RL=0,RR=0,BONNET=0,TRUNK=0` | On change | `vehicle.doors` |
| `HBRAKE:X` | `HBRAKE:1` | On change | `vehicle.handbrake` |
| `IGN:X` | `IGN:1` | On change | `vehicle.ignition_raw` |
| `RAIN:X` | `RAIN:1` | On change | `vehicle.rain` |
| `TEMP:XX.X` | `TEMP:23.5` | Every 10s | `vehicle.ext_temp_raw` |
| `PARK:keys` | `PARK:FL=45,FR=60,RL=120,RR=150` | 10Hz when reverse | `vehicle.parking_raw` |
| `CRUISE:X` | `CRUISE:1` | On change | `vehicle.cruise` |
| `IMMO:X` | `IMMO:1` | On startup | `vehicle.immo_ok` |
| `AIRBAG:X` | `AIRBAG:1` | On startup | `vehicle.airbag_ok` |

### Output Arduino (#2) ← BCM (9600 baud, JSON)

| Command | JSON | Action |
|---------|------|--------|
| Lock | `{"cmd":"lock"}` | Pulse relay 1 for 500ms |
| Unlock | `{"cmd":"unlock"}` | Pulse relay 2 for 500ms |
| Trunk | `{"cmd":"trunk"}` | Pulse relay 3 for 1s |
| Wipers on | `{"cmd":"wiper","state":1}` | Relay 9 on |
| Wipers off | `{"cmd":"wiper","state":0}` | Relay 9 off |
| Headlights | `{"cmd":"lights","state":1,"timeout":60}` | Relay 6 on for 60s |
| Blinker greet | `{"cmd":"blink","count":2}` | Flash relays 7+8 |

---

## 6. Troubleshooting

**Arduino not detected:**
```bash
ls /dev/ttyACM* /dev/ttyUSB*
# If missing — check USB cable, try different port
dmesg | grep -i "arduino\|acm\|usb"
```

**Permission denied on serial port:**
```bash
sudo usermod -aG dialout $USER
# Log out and back in
```

**DC-ATX doesn't start motherboard:**
- Check green wire (PS_ON) is connected — some DC-ATX modules have a
  jumper or switch to enable always-on mode
- Verify input voltage is >11.5V (car battery under load can dip)
- Some boards need a brief PS_ON pulse to wake from S5

**Display blank but Flask running:**
```bash
curl http://localhost:5002   # Should return HTML
# If yes → X/Chromium issue, check .xinitrc
# If no → BCM not started, check journalctl -u bcm-headunit
```
