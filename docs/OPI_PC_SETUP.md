# Orange Pi PC 1.2 — Setup & Testing Guide

Pre-production test rig using Orange Pi PC (Allwinner H3, 1GB RAM) before
moving to the primary production board — the **Orange Pi 5 Pro 4GB**
(see [`OPI5PRO_SETUP.md`](OPI5PRO_SETUP.md) for the final in-car build).

> **Note:** On the OPi PC test rig the 4-camera set, the multi-camera
> priority controller, and the blinker GPIO monitor are all disabled
> by default in `config/bcm_config_opi_pc.yaml`. The 1 GB of RAM and
> USB 2.0 bandwidth on the H3 can't drive four AHD streams at once.
> Test each subsystem individually by flipping `modules.blinker_monitor`
> and `camera.controller` to `true` one at a time.

---

## What You Need

| Item | Notes |
|------|-------|
| Orange Pi PC 1.2 | H3 quad-core, 1GB RAM |
| 5V/3A PSU | Micro-USB or barrel jack |
| 8GB+ microSD | Class 10 minimum |
| 7" HDMI display (1024x600) | Touchscreen via USB |
| USB keyboard + mouse | For initial setup |
| Ethernet cable | No built-in WiFi |
| CP2102 USB-UART adapter | For K-Line / OBD |
| USB WiFi dongle (optional) | RTL8188 or similar |
| USB BT dongle (optional) | For BT audio/phone |

Full BOM with prices: see `docs/OPI_PC_BOM.md`

---

## Phase 1 — Armbian Install + Desk Test

### 1.1 Flash Armbian

Download Armbian Bookworm CLI for Orange Pi PC from armbian.com.

```bash
# On your PC — flash SD card
sudo dd if=Armbian_*_Orangepipc_*.img of=/dev/sdX bs=1M status=progress
sync
```

Insert SD into OPi PC, connect HDMI + keyboard + ethernet, power on.

### 1.2 First Boot

```bash
# Default login: root / 1234 — creates your user on first boot

sudo hostnamectl set-hostname bcm-test
sudo timedatectl set-timezone Europe/Warsaw
sudo apt update && sudo apt upgrade -y
```

### 1.3 Install System Packages

```bash
sudo apt install -y \
  python3 python3-pip python3-venv python3-dev \
  git chromium-browser \
  libgpiod2 libgpiod-dev \
  pipewire pipewire-alsa wireplumber \
  bluez blueman \
  v4l-utils ffmpeg \
  usb-modeswitch \
  i2c-tools
```

### 1.4 Clone & Setup BCM

```bash
cd /opt
sudo git clone https://github.com/geek95dg/Alfa156-headunit.git bcm
sudo chown -R $USER:$USER /opt/bcm
cd /opt/bcm

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-opi-pc.txt
```

### 1.5 Run Desk Test (Simulated)

```bash
cd /opt/bcm
source .venv/bin/activate

# No GPIO, everything simulated
./run_opi_pc.sh --no-watcher --simulate
```

Open Chromium on the OPi PC display:
- `http://localhost:5002` — main dashboard

### 1.6 Test Checklist

- [ ] Armbian boots, SSH works
- [ ] BCM starts without errors
- [ ] Dashboard loads in Chromium
- [ ] All screens render (A1-A7)
- [ ] Theme switching works
- [ ] Language PL/EN works

---

## Phase 2 — Audio + Bluetooth

### 2.1 Test Internal DAC (3.5mm Jack)

```bash
# Check sound card
aplay -l
# Should show: sun4i-codec

# Test output
speaker-test -t wav -c 2 -l 1
```

Connect 3.5mm jack to amplifier or headphones. Start BCM and test volume control in the UI.

### 2.2 USB Bluetooth Dongle

```bash
# Plug in USB BT dongle
hciconfig
# Should show hci0 UP

bluetoothctl
> power on
> agent on
> scan on
# Find your device, pair it
> pair XX:XX:XX:XX:XX:XX
> connect XX:XX:XX:XX:XX:XX
> quit
```

### 2.3 Test Checklist

- [ ] `aplay -l` shows sun4i-codec
- [ ] Sound plays through 3.5mm jack
- [ ] BT dongle detected (`hciconfig` shows hci0)
- [ ] BT device pairs and connects
- [ ] Volume control works in BCM UI

---

## Phase 3a — GPIO: Sensors + Buzzer

### 3.1 Enable GPIO Overlay

```bash
# Edit Armbian boot config
sudo nano /boot/armbianEnv.txt

# Add/modify:
overlays=uart3 i2c0 spi-spidev w1-gpio
param_w1_pin=PA6
param_w1_pin_int_pullup=1
```

Reboot.

### 3.2 Verify GPIO Access

```bash
sudo apt install -y gpiod
gpioinfo gpiochip0 | head -40

# Test reading a pin (PA7 = line 7, ignition)
gpioget gpiochip0 7
```

### 3.3 Wiring — Parking Sensors (4x HC-SR04)

```
OPi PC Pin 16 (PC4)  ──────────────┬──── HC-SR04 #1 TRIG
                                    ├──── HC-SR04 #2 TRIG
                                    ├──── HC-SR04 #3 TRIG
                                    └──── HC-SR04 #4 TRIG

HC-SR04 #1 ECHO ── [1kOhm] ──┬── OPi Pin 18 (PC7)
                              └── [2kOhm] ── GND

HC-SR04 #2 ECHO ── [1kOhm] ──┬── OPi Pin 22 (PA2)
                              └── [2kOhm] ── GND

HC-SR04 #3 ECHO ── [1kOhm] ──┬── OPi Pin 24 (PA3)
                              └── [2kOhm] ── GND

HC-SR04 #4 ECHO ── [1kOhm] ──┬── OPi Pin 26 (PA21)
                              └── [2kOhm] ── GND

HC-SR04 VCC ── 5V
HC-SR04 GND ── GND
```

**Important:** The 1k/2k voltage divider drops 5V ECHO to ~3.3V safe for H3 GPIO.

Test:

```bash
# Quick GPIO test — trigger and read one sensor
source /opt/bcm/.venv/bin/activate
python3 -c "
import gpiod, time
chip = gpiod.Chip('gpiochip0')
trig = chip.request_lines(consumer='test', config={68: gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT)})
echo = chip.request_lines(consumer='test', config={71: gpiod.LineSettings(direction=gpiod.line.Direction.INPUT)})
# Send 10us pulse
trig.set_value(68, gpiod.line.Value.ACTIVE)
time.sleep(0.00001)
trig.set_value(68, gpiod.line.Value.INACTIVE)
print('Trigger sent, reading echo...')
# Read echo (simplified — real driver handles timing)
time.sleep(0.1)
val = echo.get_value(71)
print(f'Echo pin value: {val}')
"
```

### 3.4 Wiring — Buzzer

```
OPi Pin 12 (PD14) ── [1kOhm] ── BC547 Base
                                 BC547 Emitter ── GND
                                 BC547 Collector ── Buzzer (-) 
                                                    Buzzer (+) ── 5V
                                 [1N4148 diode across buzzer, cathode to +5V]
```

Test:

```bash
gpioset gpiochip0 110=1   # buzzer ON
sleep 0.5
gpioset gpiochip0 110=0   # buzzer OFF
```

### 3.5 Wiring — DS18B20 Temperature Sensor

```
OPi Pin 7 (PA6) ──┬── DS18B20 DQ (data)
                   └── [4.7kOhm] ── 3.3V
DS18B20 VDD ── 3.3V
DS18B20 GND ── GND
```

Test:

```bash
# After reboot with w1-gpio overlay
ls /sys/bus/w1/devices/
# Should show 28-xxxxxxxxxxxx

cat /sys/bus/w1/devices/28-*/temperature
# Returns temp in millidegrees, e.g. 23125 = 23.125C
```

### 3.6 Wiring — Optoisolators (Ignition, Door, Rain, Lock)

All vehicle 12V signals go through PC817 optoisolators:

```
12V signal ── [4.7kOhm] ── PC817 Anode (pin 1)
                            PC817 Cathode (pin 2) ── GND

3.3V ── [10kOhm] ── PC817 Collector (pin 4) ──── OPi GPIO pin
                     PC817 Emitter (pin 3) ── GND
```

| Signal | 12V Source | PC817 | OPi Pin | GPIO Line |
|--------|-----------|-------|---------|-----------|
| Ignition | IGN wire | PC817 #1 | Pin 29 | PA7 (line 7) |
| Door | Door switch | PC817 #2 | Pin 31 | PA8 (line 8) |
| Rain sensor | Rain out | PC817 #3 | Pin 35 | PA19 (line 19) |
| Central lock | Lock wire | PC817 #4 | Pin 37 | PA20 (line 20) |

**Logic:** 12V present = PC817 pulls GPIO LOW (active-low).

Test ignition input:

```bash
# Read ignition line (should be HIGH with no 12V, LOW with 12V)
gpioget gpiochip0 7
```

### 3.7 Run BCM With Sensors

```bash
cd /opt/bcm
source .venv/bin/activate
./run_opi_pc.sh --no-watcher
```

### 3.8 Test Checklist

- [ ] `gpioinfo gpiochip0` lists all pins
- [ ] HC-SR04 trigger pin toggles (measure with multimeter)
- [ ] Buzzer sounds with `gpioset gpiochip0 110=1`
- [ ] DS18B20 appears in `/sys/bus/w1/devices/`
- [ ] Temperature reads correctly
- [ ] Ignition pin reads correct state through PC817
- [ ] Parking distances show on dashboard
- [ ] Buzzer beeps on close distance

---

## Phase 3b — OBD/K-Line + Camera + USB

### 3.8 K-Line via USB-UART Adapter

Wire the CP2102/CH340 adapter to the L9637D K-Line transceiver:

```
CP2102 TX ── L9637D Pin 3 (RX)
CP2102 RX ── L9637D Pin 4 (TX)
CP2102 GND ── GND

L9637D Pin 1 (K) ── [510 Ohm] ── +12V
L9637D Pin 1 (K) ── OBD-II connector Pin 7
L9637D Pin 5 (VS) ── +12V
L9637D Pin 2 (GND) ── GND
[100nF cap between Pin 5 and GND]
```

```bash
# Plug in USB-UART adapter
dmesg | tail -5
# Should show: cp210x converter now attached to ttyUSB0

# Verify port
ls -la /dev/ttyUSB0

# Add permission
sudo usermod -aG dialout $USER
```

Config already points to `/dev/ttyUSB0` in `bcm_config_opi_pc.yaml`.

### 3.9 USB Camera (Dashcam Test)

```bash
# Plug in USB webcam
v4l2-ctl --list-devices
# Should show /dev/video0

# Test capture
ffmpeg -f v4l2 -video_size 640x480 -i /dev/video0 -frames 1 /tmp/test.jpg
ls -la /tmp/test.jpg
```

Config uses 640x480 + software x264 encoding (H3 has no hardware encoder).

### 3.10 USB WiFi Dongle (Optional)

```bash
# Plug in WiFi dongle
ip link show wlan0

# Connect to network
sudo nmcli dev wifi connect "YourSSID" password "YourPass"
```

### 3.11 LTE Modem — Huawei E3372 (Optional)

```bash
# Plug in E3372
sudo usb_modeswitch -v 12d1 -p 1f01 -M '55534243...'
# HiLink mode: appears as usb0 network interface

ip addr show usb0
ping -I usb0 8.8.8.8
```

### 3.12 Test Checklist

- [ ] `/dev/ttyUSB0` appears for K-Line adapter
- [ ] K-Line 5-baud init succeeds (test in car or with ECU sim)
- [ ] Camera captures frame to file
- [ ] DVR recording works in BCM
- [ ] WiFi dongle connects (if using)
- [ ] LTE modem gets IP (if using)

---

## Phase 4 — Full System Integration

### 4.1 Install Systemd Services

```bash
cd /opt/bcm

sudo cp config/systemd/bcm-ignition-watcher.service /etc/systemd/system/
sudo cp config/systemd/bcm-headunit.service /etc/systemd/system/
sudo cp config/systemd/bcm-kiosk.service /etc/systemd/system/

sudo systemctl daemon-reload
sudo systemctl enable bcm-ignition-watcher.service
```

### 4.2 Test Ignition Watcher (Simulated)

Without car 12V, use the file-based simulation:

```bash
# Start watcher in simulate mode
sudo systemctl stop bcm-ignition-watcher  # stop if running

cd /opt/bcm
source .venv/bin/activate
python3 -m src.power.ignition_watcher --simulate --config config/bcm_config_opi_pc.yaml

# In another terminal — simulate ignition ON:
touch /tmp/bcm_ignition_on
# Watcher should start bcm-headunit.service

# Simulate ignition OFF:
rm /tmp/bcm_ignition_on
# Watcher should stop bcm-headunit.service
```

### 4.3 Test Ignition Watcher (Real GPIO)

Wire a bench button between Pin 33 (PB5) and GND. The ignition watcher
reads this as a toggle — press once to start BCM, press again to stop.

```bash
sudo systemctl start bcm-ignition-watcher
journalctl -fu bcm-ignition-watcher
# Press bench button — should see "IGNITION ON — Starting BCM headunit"
```

### 4.4 Chromium Kiosk Auto-Start

The `bcm-kiosk.service` starts Chromium in full-screen kiosk mode
pointing at `http://localhost:5002`. It waits for the Flask server
to be ready (up to 30s).

```bash
# Test manually first
DISPLAY=:0 chromium-browser --kiosk --noerrdialogs http://localhost:5002
```

For headless boot to kiosk, ensure X/Wayland starts automatically:

```bash
# Install minimal X
sudo apt install -y xserver-xorg xinit x11-xserver-utils unclutter

# Auto-start X on boot (add to /etc/rc.local or use a login manager)
cat > /home/$USER/.xinitrc << 'XEOF'
xset s off
xset -dpms
xset s noblank
unclutter -idle 1 &
exec openbox-session
XEOF

# Or use auto-login + startx in .bash_profile
```

### 4.5 Full Boot Test

Reboot the OPi PC with everything wired:

```bash
sudo reboot
```

Expected boot sequence:
1. Armbian boots (~15s)
2. `bcm-ignition-watcher` starts (waits for GPIO or bench button)
3. Ignition ON → `bcm-headunit` starts (~5s)
4. Flask server ready → `bcm-kiosk` opens Chromium → dashboard visible

### 4.6 Monitoring

```bash
# Watch all BCM services
journalctl -fu bcm-ignition-watcher -u bcm-headunit -u bcm-kiosk

# Check service status
systemctl status bcm-ignition-watcher bcm-headunit bcm-kiosk

# Check memory (1GB is tight)
free -h

# Check CPU temp (H3 runs hot)
cat /sys/class/thermal/thermal_zone0/temp
# Divide by 1000 for Celsius
```

### 4.7 Test Checklist

- [ ] `bcm-ignition-watcher` starts at boot
- [ ] Simulated ignition (file trigger) starts/stops BCM
- [ ] Bench button toggles BCM on/off
- [ ] Chromium kiosk opens dashboard full-screen
- [ ] OBD data shows on A1 (in car or with sim)
- [ ] Parking sensors active on reverse
- [ ] Temperature reads on dashboard
- [ ] Audio plays through 3.5mm DAC
- [ ] System stable for 30+ minutes
- [ ] RAM usage < 800MB (`free -h`)
- [ ] CPU temp < 75C under load

---

## Phase 5 — In-Car Installation

### 5.1 Power Supply

```
Car 12V ACC ── [20A fuse] ── LM2596 step-down ── 5.1V / 3A ── OPi PC micro-USB
                         └── 12V direct to TDA7388 amp (separate 25A fuse)
                         └── 12V direct to TDA2050 sub amp
```

Use ACC (switched) line so the OPi PC powers off with ignition.
Or use always-on 12V + ignition watcher for clean shutdown.

### 5.2 Mount

- OPi PC: behind dashboard, zip-tied or screwed to metal bracket
- 7" display: in DIN slot or custom bracket
- HC-SR04 sensors: rear bumper, evenly spaced
- DS18B20: under front bumper (shielded from engine)
- K-Line adapter: near OBD-II port under steering column
- Camera: behind rearview mirror (front) / above license plate (rear)

### 5.3 Wire Everything

Connect per the wiring from phases 3a/3b. Key connections:

| What | Where |
|------|-------|
| HDMI | OPi PC → 7" display |
| USB touch | 7" display → OPi PC USB |
| USB-UART | OPi PC USB → L9637D → OBD-II port |
| 3.5mm audio | OPi PC → TDA7388 input |
| Parking sensors | HC-SR04 → OPi PC GPIO (via dividers) |
| Temperature | DS18B20 → OPi PC Pin 7 |
| Ignition | 12V ACC → PC817 → OPi PC Pin 29 |
| Camera | USB webcam → OPi PC USB |
| BT dongle | OPi PC USB |

### 5.4 In-Car Test Checklist

- [ ] OPi powers on with ignition key
- [ ] Dashboard appears on 7" screen within 30s
- [ ] Touch input works on display
- [ ] OBD reads real ECU data (RPM, coolant, speed)
- [ ] Audio plays through car speakers
- [ ] Parking sensors beep on reverse
- [ ] Reverse camera shows on screen
- [ ] Temperature sensor reads exterior temp
- [ ] BT pairs with phone
- [ ] System survives engine vibration
- [ ] No overheating (check `thermal_zone0`)
- [ ] Clean shutdown on ignition OFF

---

## Troubleshooting

### GPIO Permission Denied

```bash
sudo usermod -aG gpio $USER
# Or run BCM as root (systemd services already do this)
```

### No Sound

```bash
aplay -l                          # list cards
pactl info                        # check PipeWire/Pulse
speaker-test -t wav -c 2 -l 1    # test output
```

### DS18B20 Not Found

```bash
# Check overlay loaded
dmesg | grep w1
ls /sys/bus/w1/devices/
# If empty, check wiring and /boot/armbianEnv.txt overlay
```

### H3 Overheating

```bash
cat /sys/class/thermal/thermal_zone0/temp
```

If > 80C: add heatsink + fan. Reduce dashboard FPS in config:
```yaml
display:
  dashboard:
    fps: 5
```

### Serial Device Not Found

```bash
dmesg | grep ttyUSB
ls -la /dev/ttyUSB*
sudo chmod 666 /dev/ttyUSB0   # quick fix
```

### Out of Memory (1GB Limit)

```bash
free -h

# Disable unused modules in bcm_config_opi_pc.yaml:
# voice: false
# multimedia: false

# Add swap if needed
sudo fallocate -l 512M /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

### Chromium Won't Start

```bash
# Check DISPLAY is set
echo $DISPLAY   # should be :0

# Try manually
DISPLAY=:0 chromium-browser --no-sandbox http://localhost:5002
```
