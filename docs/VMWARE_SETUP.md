# BCM v7 — VMware Workstation Setup Guide

How to run and test the full BCM v7 headunit system on a VMware Workstation virtual machine (x86/x64).

---

## 1. VM Requirements

| Setting | Recommended | Minimum |
|---------|-------------|---------|
| **VMware Version** | Workstation 17 Pro | Workstation 16+ |
| **Guest OS** | Ubuntu 24.04 LTS (64-bit) | Ubuntu 22.04+ / Debian 12+ |
| **CPUs** | 4 cores | 2 cores |
| **RAM** | 8 GB | 4 GB |
| **Disk** | 40 GB (thin provisioned) | 20 GB |
| **Display** | 3D acceleration ON, 256 MB VRAM | 128 MB VRAM |
| **Network** | NAT (for pip/apt) | NAT or Bridged |
| **USB** | USB 3.1 controller | USB 2.0 |
| **Sound** | HD Audio (Auto detect) | Any sound card |

---

## 2. Create the VM

### Step-by-step in VMware Workstation:

1. **File → New Virtual Machine → Custom (advanced)**
2. **Hardware compatibility:** Workstation 17.x
3. **Installer disc image:** Ubuntu 24.04 LTS ISO
4. **Guest OS:** Linux → Ubuntu 64-bit
5. **VM name:** `BCM-v7-Headunit`
6. **Processors:** 4 cores (2 processors × 2 cores each)
7. **Memory:** 8192 MB
8. **Network:** NAT
9. **I/O Controller:** LSI Logic
10. **Disk:** SCSI, 40 GB, Store as single file
11. **Finish and install Ubuntu**

### Post-install VM settings (Edit → Settings):

```
Display:
  ☑ Accelerate 3D graphics
  Graphics memory: 256 MB
  Monitor: Use host setting for monitors

Sound Card:
  Device: Auto detect
  ☑ Connect at power on

USB Controller:
  USB compatibility: USB 3.1
  ☑ Show all USB input devices
  ☑ Share Bluetooth devices with the virtual machine

Serial Port (optional — for K-Line testing):
  ☑ Use physical serial port OR Use named pipe
  Pipe: \\.\pipe\kline_sim
```

---

## 3. VMX File Tweaks (Optional Performance Boost)

Open `BCM-v7-Headunit.vmx` in a text editor and add/modify:

```vmx
# Enable nested virtualization (for any containers)
vhv.enable = "TRUE"

# Better timer resolution for real-time audio
rtc.startTime = "0"
tools.syncTime = "TRUE"

# USB passthrough performance
usb.generic.allowHID = "TRUE"
usb.generic.allowLastHID = "TRUE"

# Disable side-channel mitigations for performance in testing
ulm.disableMitigations = "TRUE"

# Audio latency reduction
sound.autoDetect = "TRUE"
sound.virtualDev = "hdaudio"

# Better display performance
mks.enable3d = "TRUE"
mks.gl.allowBlacklistedDrivers = "TRUE"
svga.vramSize = "268435456"
```

---

## 4. Guest OS Setup

### 4.1 System packages

```bash
sudo apt update && sudo apt upgrade -y

# Essential build tools
sudo apt install -y \
    python3.12 python3.12-venv python3-pip \
    git build-essential pkg-config \
    open-vm-tools open-vm-tools-desktop

# Audio (PipeWire)
sudo apt install -y \
    pipewire pipewire-pulse pipewire-alsa wireplumber \
    pavucontrol

# Bluetooth (for BT testing with USB adapter passthrough)
sudo apt install -y \
    bluez bluez-tools pulseaudio-module-bluetooth

# Display libraries (for dashboard renderer)
sudo apt install -y \
    python3-pygame libsdl2-dev libsdl2-image-dev \
    libcairo2-dev libgirepository1.0-dev

# USB serial (for K-Line simulation)
sudo apt install -y \
    socat picocom

# Optional: camera testing
sudo apt install -y \
    v4l-utils ffmpeg
```

### 4.2 Clone and setup the project

```bash
cd ~
git clone https://github.com/geek95dg/Alfa156-headunit.git
cd Alfa156-headunit

# Create virtual environment
python3.12 -m venv .venv
source .venv/bin/activate

# Install dependencies (common + x86 simulation + dev/test tools)
pip install -r requirements.txt
pip install -r requirements-x86.txt
pip install -r requirements-dev.txt

# Verify installation
python -m pytest tests/ -v
```

### 4.3 PipeWire audio verification

```bash
# Check PipeWire is running
systemctl --user status pipewire pipewire-pulse wireplumber

# List audio outputs
pw-cli list-objects | grep -i node

# Test audio output
speaker-test -t wav -c 2

# If no sound, restart PipeWire
systemctl --user restart pipewire pipewire-pulse wireplumber
```

---

## 5. Running the System

### 5.1 Quick test — dry run

```bash
cd ~/Alfa156-headunit
source .venv/bin/activate

python main.py --platform x86 --dry-run
```

### 5.2 Start with HTML5 Frontend (Recommended)

```bash
./run_x86.sh
```

This starts the system with the **HTML5/Tailwind dashboard frontend**. No Pygame or X display needed.

**Open your browser:** http://localhost:5002

You'll see the head unit dashboard with:
- **3 themes:** Heritage (amber/walnut), Modern (blue/white), Autodelta (orange/black)
- **5 screens:** Init → A1 Main → A2 Trip → A3 Weather → A4 Service
- **Live telemetry:** simulated engine data updating at ~15 FPS
- **Interactive maps:** Leaflet.js with OpenStreetMap on Weather screen
- **Real-time WebSocket:** all data streams via WebSocket to the browser

**Access from your host machine (outside the VM):**
1. Find VM IP: `ip addr show`
2. Open host browser: `http://<VM_IP>:5002`
3. If using VMware NAT and host can't reach VM, switch to **Bridged** networking

### 5.2.1 Dashboard keyboard controls (in browser)

| Key | Action |
|-----|--------|
| **LEFT/RIGHT** | Navigate between screens (A1 → A2 → A3 → A4) |
| **HOME** | Jump to A1 Main screen |
| **ESC** | Return from Settings to dashboard |

### 5.2.2 Dashboard screens (v8 — HTML5 Frontend)

| Screen | Name | Content |
|--------|------|---------|
| **Init** | Boot Sequence | Car sketch with breathing animation, progress bar, brand identity |
| **A1** | Main Hub | Engine temp, fuel level, notifications, media player, driving stats |
| **A2** | Trip Stats | Trip distance/time/speed, consumption chart (bar or line graph) |
| **A3** | Weather | Live map (Leaflet.js), current conditions, 3-day forecast |
| **A4** | Service | Vehicle diagnostics, car sketch, TPMS, oil/battery/engine status |
| **Settings** | Config | Theme switch, language, units, brightness |

### 5.2.3 Theme switching

Switch themes via the Settings screen in the browser, or via REST API:

```bash
curl -X POST http://localhost:5002/api/config \
  -H "Content-Type: application/json" \
  -d '{"theme": "autodelta"}'
```

Available themes: `heritage`, `modern`, `autodelta`

### 5.2.4 REST API for testing

```bash
# Get live telemetry data
curl -s http://localhost:5002/api/data | python3 -m json.tool

# Get current config
curl -s http://localhost:5002/api/config

# Switch language to English
curl -X POST http://localhost:5002/api/config \
  -H "Content-Type: application/json" -d '{"language":"en"}'
```

### 5.3 Start with Legacy Pygame Renderer (Optional)

```bash
./run_x86.sh --pygame
```

Requires X display (`$DISPLAY` must be set). Opens a Pygame window at 800x480.

### 5.4 Dual display (Android Auto)

The AA/BT management web UI runs at http://localhost:5001 regardless of frontend mode.

### 5.5 Start specific modules only

```bash
./run_x86.sh --modules obd,dashboard
./run_x86.sh --pygame --modules obd,dashboard
```

### 5.6 Run tests

```bash
python -m pytest tests/ -v
python -m pytest tests/ --cov=src --cov-report=term-missing
```

---

## 6. USB Passthrough (for Real Hardware Testing)

VMware can pass through USB devices from the host to the VM. This is useful for testing with real hardware.

### 6.1 Bluetooth adapter

1. Plug USB BT adapter into host
2. In VMware: **VM → Removable Devices → [BT Adapter] → Connect**
3. In guest: `bluetoothctl show` should show the adapter
4. Test: `bluetoothctl scan on` → pair phone → stream A2DP

### 6.2 USB serial adapter (for K-Line)

1. Plug USB-to-serial adapter into host
2. Passthrough in VMware
3. In guest: `ls /dev/ttyUSB*` should show the device
4. Alternative — simulate serial with socat:

```bash
# Terminal 1: Create virtual serial pair
socat -d -d pty,raw,echo=0 pty,raw,echo=0
# Note the two /dev/pts/X paths printed

# Terminal 2: Use one end as the K-Line port
# Set in config: obd.serial_port = "/dev/pts/X"
```

### 6.3 USB webcam (for camera module)

1. Passthrough USB webcam in VMware
2. Verify: `v4l2-ctl --list-devices`
3. Test: `ffplay /dev/video0`

### 6.4 USB sound card / DAC

1. Passthrough USB DAC in VMware
2. Check: `pw-cli list-objects | grep -i usb`
3. Set as default: `wpctl set-default <node-id>`

---

## 7. Simulated K-Line Testing (No Hardware)

Create a virtual serial port pair for OBD testing without real hardware:

```bash
# Terminal 1: Create virtual serial pair
socat -d -d pty,raw,echo=0,link=/tmp/kline_opi pty,raw,echo=0,link=/tmp/kline_sim

# Terminal 2: Start BCM with virtual port
# Edit config/bcm_config.yaml:
#   obd:
#     serial_port: /tmp/kline_opi
python main.py --platform x86 --modules obd,dashboard

# Terminal 3: Send simulated ECU responses
python -c "
import serial, time
ser = serial.Serial('/tmp/kline_sim', 10400, timeout=1)
# Simulate ECU init response
while True:
    data = ser.read(100)
    if data:
        print(f'Received: {data.hex()}')
        # Echo back a fake RPM response
        ser.write(bytes([0x48, 0x6B, 0x11, 0x41, 0x0C, 0x1A, 0xF8, 0x00]))
    time.sleep(0.1)
"
```

---

## 8. Testing Checklist

Run through this checklist to verify the full system:

### Core
- [ ] `python main.py --platform x86 --dry-run` — lists all modules
- [ ] `python -m pytest tests/ -v` — all tests pass
- [ ] Event bus delivers messages between modules

### HTML5 Frontend (v8)
- [ ] `./run_x86.sh` starts without errors
- [ ] http://localhost:5002 loads the dashboard
- [ ] Init screen: car sketch + breathing animation + progress bar
- [ ] A1 Main: engine temp, fuel level, notifications update in real-time
- [ ] A2 Trip: consumption chart renders, stats update
- [ ] A3 Weather: Leaflet map loads, weather data displays
- [ ] A4 Service: diagnostics list, car sketch renders
- [ ] Theme switch: Heritage/Modern/Autodelta all render correctly
- [ ] `curl /api/data` returns JSON with live RPM/speed/temp values
- [ ] WebSocket reconnects after disconnect (refresh browser, verify)
- [ ] Keyboard nav: LEFT/RIGHT cycles screens in browser
- [ ] Multiple tabs: all receive real-time updates simultaneously

### Legacy Pygame (Part 2 — optional, with --pygame)
- [ ] Pygame window opens at 800×480
- [ ] Gauges render (RPM, speed, coolant temp)
- [ ] Updates in real-time from simulated OBD data

### OBD (Part 3)
- [ ] Simulated ECU data flows to event bus
- [ ] RPM, speed, coolant temp values are realistic

### Parking (Part 4)
- [ ] Simulated sensor distances published
- [ ] Buzzer frequency increases as distance decreases
- [ ] Overlay renders on dashboard when reverse gear engaged

### Environment (Part 5)
- [ ] Simulated temperature readings published
- [ ] Dashboard shows temperature overlay

### Audio (Part 6)
- [ ] PipeWire detected (or graceful fallback)
- [ ] Volume control responds to events
- [ ] EQ configuration loads

### Voice (Part 7)
- [ ] Vosk model loads (or stub mode)
- [ ] Keyboard commands work as fallback
- [ ] Voice events published to event bus

### Input (Part 8)
- [ ] Keyboard input captured
- [ ] Rotary encoder simulated via arrow keys
- [ ] Button events published

### Camera (Part 9)
- [ ] Simulated camera frames generated
- [ ] Dashcam recording starts/stops with events

### Power (Part 10)
- [ ] State machine: STANDBY → RUNNING → SHUTDOWN
- [ ] Ignition events trigger state transitions
- [ ] Backlight PWM simulated

### Multimedia (Part 11)
- [ ] Bluetooth manager initializes (simulated mode)
- [ ] Connect/disconnect events published
- [ ] HFP call events trigger audio ducking
- [ ] OpenAuto reports unavailable (expected on x86)

---

## 9. Troubleshooting

### No sound in VM
```bash
# Ensure PipeWire is running
systemctl --user restart pipewire wireplumber
# Check VMware sound card is connected
# VM → Removable Devices → Sound Card → Connect
```

### Pygame window doesn't open
```bash
# Install display dependencies
sudo apt install -y python3-pygame libsdl2-dev
# If running headless, use virtual display
export SDL_VIDEODRIVER=dummy
```

### `No module named pytest`
```bash
# pytest is in the dev requirements — install it
pip install -r requirements-dev.txt
```

### Tests fail with import errors
```bash
# Ensure you're in the venv
source .venv/bin/activate
# Ensure all requirement files are installed
pip install -r requirements.txt
pip install -r requirements-x86.txt
pip install -r requirements-dev.txt
# Ensure project root is in PYTHONPATH
export PYTHONPATH=/home/$USER/Alfa156-headunit:$PYTHONPATH
# Or run with: python -m pytest tests/
```

### USB passthrough not working
```bash
# Install VMware USB arbitrator on host (Windows)
# Services → VMware USB Arbitration Service → Start
# On Linux host:
sudo systemctl restart vmware-USBArbitrator
```

### Bluetooth not detected
```bash
# Check if BT adapter is passed through
hciconfig -a
# If no adapter, ensure USB passthrough is configured
# VM → Removable Devices → [BT adapter] → Connect
```

---

## 10. Performance Tips

1. **Disable swap:** The VM has enough RAM
   ```bash
   sudo swapoff -a
   ```

2. **Use tmpfs for logs:** Reduce disk I/O
   ```bash
   sudo mount -t tmpfs -o size=256m tmpfs /tmp
   ```

3. **Pin VM to host cores:** In VMware → Processors → Advanced → Affinity

4. **Disable screen lock:** Prevents display driver issues
   ```bash
   gsettings set org.gnome.desktop.session idle-delay 0
   gsettings set org.gnome.desktop.screensaver lock-enabled false
   ```

5. **Use Wayland session:** Better PipeWire integration in Ubuntu 24.04

6. **Snapshot before testing:** Take a VM snapshot so you can quickly revert
   ```
   VM → Snapshot → Take Snapshot → "Clean state"
   ```
