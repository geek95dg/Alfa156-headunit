# BCM v7 — VM Usage Guide

How to run, navigate, and test the BCM headunit system inside a VM (VMware or similar).

> **Prerequisites:** VM already set up per [VMWARE_SETUP.md](VMWARE_SETUP.md).

---

## 1. Starting the System

```bash
cd ~/Alfa156-headunit
source .venv/bin/activate

# Start all modules in x86 simulation mode
python main.py --platform x86
```

This opens the **dashboard window** (800x480) with live-simulated gauges, and starts all backend modules (OBD, parking, audio, voice, etc.) in simulation mode.

### Selective startup

```bash
# Dashboard + OBD only (lightweight)
python main.py --platform x86 --modules obd,dashboard

# Audio + multimedia only (BT/DAC testing)
python main.py --platform x86 --modules audio,multimedia

# Dry run — list all modules, start nothing
python main.py --platform x86 --dry-run
```

### Module list

| Module | Part | What it does |
|--------|------|-------------|
| `dashboard` | 2 | PyGame GUI — gauges, trip, overlays, settings |
| `obd` | 3 | Simulated ECU data (RPM, speed, coolant temp) |
| `parking` | 4 | Simulated ultrasonic sensors + buzzer |
| `environment` | 5 | Simulated exterior temperature |
| `audio` | 6 | PipeWire volume/EQ (or stub if PipeWire unavailable) |
| `voice` | 7 | Vosk speech recognition (or keyboard fallback) |
| `input` | 8 | Keyboard input (simulates rotary encoder) |
| `camera` | 9 | Simulated dashcam frames |
| `power` | 10 | Simulated ignition/shutdown state machine |
| `multimedia` | 11 | Bluetooth manager + OpenAuto stub |

---

## 2. Dashboard Keyboard Controls

Once the dashboard window is open, these keys work:

### Main Dashboard View

| Key | Action |
|-----|--------|
| `UP` | Increase RPM (demo mode, +200) |
| `DOWN` | Decrease RPM (demo mode, -200) |
| `R` | Toggle reverse gear (shows parking overlay) |
| `T` | Cycle exterior temperature down (-3 C per press, for icing test) |
| `I` | Trigger icing alert overlay manually |
| `H` or `HOME` | Open/close Settings menu |
| `0` | Mute (SWC mute simulation) |
| `F5` | Phone pickup (SWC simulation) |
| `F6` | Phone hangup (SWC simulation) |
| `F7` | Voice assistant trigger (SWC simulation) |
| `F8` | Audio source cycle (SWC simulation) |
| `ESC` | Close settings (if open) / Quit application |

### Settings Menu (press H to open)

| Key | Action |
|-----|--------|
| `UP` | Move selection up |
| `DOWN` | Move selection down |
| `LEFT` | Cycle setting value backward |
| `RIGHT` or `ENTER` | Cycle setting value forward |
| `H` / `HOME` | Save & close settings |
| `ESC` | Save & close settings |

### Settings Available

| Setting | Options |
|---------|---------|
| **Theme** | Classic Alfa Racing / Modern Dark / OEM Digital |
| **Language** | Polski / English |
| **Speed Units** | km/h / mph |
| **Temp Units** | C / F |
| **Brightness** | 0% — 100% (step 10%) |
| **EQ Preset** | Flat / Rock / Jazz / Bass Boost / Custom |
| **Wake Sensitivity** | Low / Medium / High |

Settings are saved to `config/bcm_config.yaml` when you close the menu.

---

## 3. Testing Demo Scenarios

### 3.1 Gauge operation

1. Start: `python main.py --platform x86 --modules obd,dashboard`
2. The demo data generator auto-produces sinusoidal RPM/speed/temp patterns
3. Watch gauges animate — RPM swings 750-5000, speed follows, coolant slowly rises to ~90 C
4. Press `UP`/`DOWN` to manually override RPM

### 3.2 Parking overlay

1. Press `R` to engage reverse gear
2. Full-screen parking overlay appears with 4 colored distance bars:
   - Green: > 1m (safe)
   - Yellow: 0.5-1m (caution)
   - Orange: 0.3-0.5m (warning)
   - Red: < 0.3m (danger)
3. Simulated sensors cycle through distances automatically
4. Press `R` again to disengage

### 3.3 Icing alert

1. Press `T` repeatedly to drop the temperature
2. At < 3 C: status bar shows snowflake icon + icing alert popup appears
3. At <= 0 C: persistent icing warning state
4. Or press `I` to trigger icing alert directly (5-second popup)

### 3.4 Theme switching

1. Press `H` to open Settings
2. Navigate to "Theme" (first item)
3. Press `RIGHT` to cycle: Classic Alfa Racing -> Modern Dark -> OEM Digital
4. Press `H` or `ESC` to close — theme applies immediately

### 3.5 K-Line OBD simulation (no hardware)

```bash
# Terminal 1: Create virtual serial pair
socat -d -d pty,raw,echo=0,link=/tmp/kline_opi pty,raw,echo=0,link=/tmp/kline_sim

# Terminal 2: Start BCM (edit config first: serial.kline.port_opi: /tmp/kline_opi)
python main.py --platform x86 --modules obd,dashboard

# Terminal 3: Feed simulated ECU responses
python -c "
import serial, time
ser = serial.Serial('/tmp/kline_sim', 10400, timeout=1)
while True:
    data = ser.read(100)
    if data:
        print(f'Received: {data.hex()}')
        # Fake RPM response (KWP2000 format)
        ser.write(bytes([0x48, 0x6B, 0x11, 0x41, 0x0C, 0x1A, 0xF8, 0x00]))
    time.sleep(0.1)
"
```

### 3.6 Voice commands (keyboard fallback)

When voice module is running in stub mode (no Vosk model), commands are dispatched via event bus. Available voice commands:

**Polish (default):**
- "hej komputer" — wake word
- "pokaz temperature" — show temperature
- "wlacz radio" — turn on radio
- "nastepny utwor" / "poprzedni utwor" — next/prev track
- "glosniej" / "ciszej" — volume up/down
- "pokaz zuzycie" — show fuel consumption
- "status samochodu" — car status
- "nagrywaj" / "zatrzymaj nagrywanie" — start/stop dashcam
- "zmien styl" — change theme
- "zmien jezyk" — change language

**English:**
- "hey computer" — wake word
- "show temperature", "turn on radio", "next track", "previous track"
- "volume up", "volume down", "show consumption", "car status"
- "start recording", "stop recording", "change theme", "change language"

### 3.7 Audio system

```bash
# Check PipeWire status
systemctl --user status pipewire wireplumber

# List audio sinks
pw-cli list-objects | grep -i node

# Test audio output
speaker-test -t wav -c 2

# If USB DAC is passed through to VM
wpctl set-default <node-id>
```

---

## 4. Running Tests

### All tests

```bash
cd ~/Alfa156-headunit
source .venv/bin/activate
python -m pytest tests/ -v
```

### Specific module tests

```bash
python -m pytest tests/test_dashboard.py -v    # Dashboard/GUI
python -m pytest tests/test_obd.py -v          # K-Line / KWP2000
python -m pytest tests/test_parking.py -v      # Parking sensors
python -m pytest tests/test_environment.py -v  # Temperature / icing
python -m pytest tests/test_audio.py -v        # PipeWire / volume
python -m pytest tests/test_voice.py -v        # Voice recognition
python -m pytest tests/test_input.py -v        # Rotary encoder / BT remote
python -m pytest tests/test_camera.py -v       # Dashcam
python -m pytest tests/test_power.py -v        # Power state machine
python -m pytest tests/test_multimedia.py -v   # OpenAuto / Bluetooth
python -m pytest tests/test_core.py -v         # Config / EventBus / HAL
python -m pytest tests/test_integration.py -v  # Cross-module IPC
```

### With coverage report

```bash
python -m pytest tests/ --cov=src --cov-report=term-missing
```

### Run a single test function

```bash
python -m pytest tests/test_dashboard.py::test_settings_cycle_value -v
```

---

## 5. Configuration Editing

The master config lives at `config/bcm_config.yaml`. Key sections you may want to adjust for VM testing:

```yaml
# Force x86 platform (auto should work in VM)
system:
  platform: auto        # auto | x86 | opi

# Enable/disable specific modules
modules:
  dashboard: true
  obd: true
  parking: true
  # ... set false to skip modules you don't need

# Dashboard display size
display:
  dashboard:
    width: 800
    height: 480
    fps: 15
    theme: classic_alfa  # classic_alfa | modern_dark | oem_digital

# Audio config
audio:
  eq_preset: flat
  master_volume: 70

# K-Line serial port (for socat testing)
serial:
  kline:
    port_opi: /dev/ttyS3      # real OPi
    # Override for VM: /tmp/kline_opi
```

---

## 6. Web Dashboard Viewer (x86 only)

An alternative browser-based viewer is available for x86 development:

```bash
# Requires flask + flask-sock
pip install flask flask-sock Pillow

# Start web viewer (separate from PyGame)
python -c "from src.dashboard.web_viewer import start_web_viewer; start_web_viewer()"
```

Opens at `http://localhost:5000` — shows dashboard frames via WebSocket.

---

## 7. Event Bus Debugging

All modules communicate via the EventBus. To debug events:

```python
# In Python REPL or test script:
from src.core.event_bus import EventBus

bus = EventBus()
bus.subscribe("*", lambda topic, value, ts: print(f"[{topic}] = {value}"))

# Now start modules — you'll see all published events
```

Common event topics:
- `obd.rpm`, `obd.speed`, `obd.coolant_temp`, `obd.fuel_level`, `obd.fuel_rate`
- `obd.battery_voltage`
- `env.temperature`
- `parking.distances` (list of 4 floats)
- `power.reverse_gear` (bool)
- `input.volume_up`, `input.volume_down`, `input.mute`
- `input.phone_pickup`, `input.phone_hangup` (SWC phone buttons)
- `input.voice_trigger` (SWC voice button)
- `input.source_cycle` (SWC source button)
- `voice.cmd.*` (voice command actions)

---

## 8. Logging

Logs go to `logs/bcm.log` and stdout. Adjust verbosity:

```yaml
# config/bcm_config.yaml
system:
  log_level: DEBUG     # DEBUG | INFO | WARNING | ERROR
```

Or watch logs live:

```bash
tail -f logs/bcm.log
```

---

## 9. Quick Test Checklist

- [ ] `python main.py --platform x86 --dry-run` — all 11 modules listed
- [ ] `python -m pytest tests/ -v` — all tests pass
- [ ] Dashboard window opens, gauges animate
- [ ] Press `H` — settings menu opens/closes
- [ ] Cycle theme in settings — theme changes on close
- [ ] Press `R` — parking overlay shows/hides
- [ ] Press `T` 4-5 times — icing warning triggers
- [ ] Press `I` — icing alert popup appears for 5s
- [ ] PipeWire audio works: `speaker-test -t wav -c 2`
- [ ] K-Line simulation works with socat (if testing OBD)
