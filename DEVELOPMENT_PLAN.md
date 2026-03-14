# BCM v7 - Alfa Romeo 156 Head Unit - Development Plan

## Context

This project builds a complete Body Computer Module (BCM v7) for an Alfa Romeo 156 1.9 JTD 8V (pre-facelift). It replaces the factory head unit with a dual-screen system based on Orange Pi 5 Plus, providing: vehicle diagnostics (K-Line/KWP2000), multimedia (Android Auto/CarPlay), dashcam, parking sensors, voice control, and a 4.1 audio system.

**Two-phase approach:**
- **Phase A (x86):** Proof of concept on Debian/Ubuntu desktop — test UI, logic, and integration using simulated hardware (mock sensors, virtual displays in windows)
- **Phase B (OPi):** Production deployment on Orange Pi 5 Plus with real GPIO, UART, cameras, and framebuffer rendering

The plan is split into **13 independent parts**. Each part can be requested and implemented separately. Dependencies between parts are clearly noted.

---

## Repository Structure (Part 1 creates this)

```
Alfa156-headunit/
├── bcm_v7_docs.html              # Existing technical documentation
├── README.md                      # Existing
├── LICENSE                        # Existing
├── config/
│   ├── bcm_config.yaml           # Master configuration
│   ├── pipewire/                 # PipeWire configs (Part 6)
│   └── systemd/                  # Service files (Part 13)
├── src/
│   ├── core/                     # Part 1: Skeleton
│   │   ├── __init__.py
│   │   ├── config.py             # YAML config loader
│   │   ├── event_bus.py          # Inter-module message bus
│   │   ├── logger.py             # Logging setup
│   │   └── hal.py                # Hardware Abstraction Layer
│   ├── dashboard/                # Part 2: BCM Dashboard Renderer
│   │   ├── __init__.py
│   │   ├── renderer.py           # Main PyGame/Pillow renderer
│   │   ├── gauges.py             # RPM, speed, temp, fuel gauges
│   │   ├── trip_computer.py      # Trip/fuel consumption calc
│   │   ├── status_bar.py         # Top status bar (BT, temp, icons)
│   │   ├── overlays.py           # Parking overlay, icing alert
│   │   ├── settings_screen.py    # BCM settings menu
│   │   ├── themes/               # Switchable UI themes
│   │   │   ├── theme_base.py     # Base theme class
│   │   │   ├── classic_alfa.py   # Alfa racing red/dark (default)
│   │   │   ├── modern_dark.py    # Tesla-like minimal
│   │   │   └── oem_digital.py    # Giulia/Stelvio style
│   │   ├── web_viewer.py          # Flask+WebSocket browser preview (x86)
│   │   └── assets/               # Fonts, icons, backgrounds
│   ├── obd/                      # Part 3: K-Line / OBD-II
│   │   ├── __init__.py
│   │   ├── kline.py              # K-Line serial protocol
│   │   ├── kwp2000.py            # KWP2000 implementation
│   │   ├── edc15c7.py            # Bosch ECU specific PIDs
│   │   └── simulator.py          # x86 mock ECU for testing
│   ├── parking/                  # Part 4: Parking Sensors
│   │   ├── __init__.py
│   │   ├── hcsr04.py             # Ultrasonic sensor driver
│   │   ├── distance.py           # Zone calculation logic
│   │   ├── buzzer.py             # Audio buzzer controller
│   │   └── simulator.py          # x86 mock sensors
│   ├── environment/              # Part 5: Temperature & Alerts
│   │   ├── __init__.py
│   │   ├── ds18b20.py            # Temperature sensor driver
│   │   ├── icing.py              # Icing detection algorithm
│   │   └── simulator.py          # x86 mock temperature
│   ├── audio/                    # Part 6: Audio & PipeWire
│   │   ├── __init__.py
│   │   ├── pipewire_ctrl.py      # PipeWire routing/EQ control
│   │   ├── source_manager.py     # Audio source switching
│   │   ├── ducking.py            # Audio priority & ducking system
│   │   └── volume.py             # Volume control
│   ├── voice/                    # Part 7: Vosk Voice Control
│   │   ├── __init__.py
│   │   ├── recognizer.py         # Vosk speech recognition
│   │   ├── wake_word.py          # Wake word detection
│   │   ├── commands.py           # Command grammar & dispatch
│   │   ├── languages.py          # PL + EN command definitions
│   │   ├── tts.py                # Text-to-speech announcements (pyttsx3)
│   │   └── models/               # Vosk models (Polish + English)
│   ├── input/                    # Part 8: Input Controllers
│   │   ├── __init__.py
│   │   ├── rotary_encoder.py     # USB HID rotary encoder handler
│   │   ├── bt_remote.py          # BT steering wheel remote
│   │   └── action_dispatch.py    # Key mapping → actions
│   ├── camera/                   # Part 9: Cameras & Dashcam
│   │   ├── __init__.py
│   │   ├── dashcam.py            # GStreamer recording pipeline
│   │   ├── reverse_cam.py        # Reverse camera display
│   │   └── ahd_grabber.py        # AHD USB grabber interface
│   ├── power/                    # Part 10: Power Management
│   │   ├── __init__.py
│   │   ├── power_manager.py      # Wake/sleep state machine
│   │   ├── backlight.py          # PWM backlight control
│   │   └── shutdown.py           # Graceful shutdown sequence
│   └── multimedia/               # Part 11: Android Auto / Media
│       ├── __init__.py
│       ├── openauto.py           # OpenAuto Pro integration
│       └── bluetooth.py          # A2DP/HFP management
├── arduino/                      # Part 8: Arduino firmware
│   └── rotary_encoder/
│       └── rotary_encoder.ino    # ATmega32U4 USB HID firmware
├── schematics/                   # Part 12: Electrical diagrams
│   ├── README.md                 # Assembly instructions
│   ├── main_wiring.svg           # Complete wiring diagram
│   ├── kline_circuit.svg         # L9637D schematic
│   ├── backlight_mosfet.svg      # MOSFET PWM circuit
│   ├── parking_sensors.svg       # HC-SR04 wiring
│   ├── audio_system.svg          # DAC → AMP → Speakers
│   ├── power_supply.svg          # 12V → 5.1V converter
│   ├── gpio_pinout.svg           # Complete GPIO mapping
│   └── vehicle_layout.svg        # Cable routing in car
├── tests/                        # Unit tests per module
│   ├── test_dashboard.py
│   ├── test_obd.py
│   ├── test_parking.py
│   ├── test_environment.py
│   ├── test_voice.py
│   └── ...
├── requirements.txt              # Python dependencies
├── requirements-x86.txt          # x86-only deps (mock libs)
├── requirements-opi.txt          # OPi-only deps (GPIO, etc.)
└── main.py                       # Entry point
```

---

## PART 1: Project Skeleton & Core Infrastructure

**Goal:** Set up repository structure, configuration system, logging, event bus, and hardware abstraction layer.

**Files to create:**
- `src/core/config.py` — YAML config loader with platform detection (x86 vs arm64)
- `src/core/event_bus.py` — Publish/subscribe message bus for inter-module communication
- `src/core/logger.py` — Structured logging with per-module log levels
- `src/core/hal.py` — Hardware Abstraction Layer: GPIO, UART, SPI, I2C, 1-Wire wrappers
- `config/bcm_config.yaml` — Master config (display resolution, GPIO pins, serial ports, features toggle)
- `main.py` — Entry point that initializes modules based on config
- `requirements.txt`, `requirements-x86.txt`, `requirements-opi.txt`

**x86 vs OPi:**
- x86: HAL returns mock GPIO/UART objects, platform auto-detected
- OPi: HAL uses `gpiod`, `pyserial`, real `/dev/` devices

**Dependencies:** None (this is the foundation)

**Testing:** `python main.py --platform x86 --dry-run` starts and lists loaded modules

---

## PART 2: BCM Dashboard Renderer (4.3" Screen)

**Goal:** Build the dashboard UI that displays vehicle gauges, trip computer, status bar, and overlays.

**Files to create:**
- `src/dashboard/renderer.py` — Main render loop (PyGame window on x86, framebuffer `/dev/fb0` on OPi)
- `src/dashboard/gauges.py` — Circular/bar gauges for RPM, speed, engine temp, fuel level, instant/avg consumption
- `src/dashboard/trip_computer.py` — Trip distance, fuel used, average speed, range estimation
- `src/dashboard/status_bar.py` — Top bar: BT icon, temperature, icing warning, clock, audio source
- `src/dashboard/overlays.py` — Reverse camera overlay with parking distance bars, icing alert popup
- `src/dashboard/themes/` — Theme system with switchable styles
  - `src/dashboard/themes/theme_base.py` — Base theme class (colors, fonts, gauge styles, layout)
  - `src/dashboard/themes/classic_alfa.py` — Red/dark Alfa Romeo racing heritage, circular analog gauges
  - `src/dashboard/themes/modern_dark.py` — Clean dark theme with flat gauges (Tesla-like)
  - `src/dashboard/themes/oem_digital.py` — Modern Alfa digital dashboard style (Giulia/Stelvio inspired)
- `src/dashboard/settings_screen.py` — BCM settings menu (theme selection, units, brightness, language)
- `src/dashboard/assets/` — Fonts, icons, backgrounds (per-theme subdirectories)

**Key specs:**
- Resolution: 800x480 (4.3" screen)
- Target frame rate: 10-15 FPS (gauge data changes slowly)
- Layout: gauges in center, status bar on top, trip data at bottom
- **3 switchable UI themes** — selectable from BCM settings menu via rotary encoder:
  1. **Classic Alfa Racing** (default) — red/dark, circular analog-style gauges, Alfa heritage
  2. **Modern Dark Minimal** — flat gauges, clean dark theme, Tesla-like
  3. **OEM Digital** — mimics modern Alfa Romeo digital dashboards (Giulia/Stelvio)
- Theme saved in config, persists across reboots
- Reverse mode: full-screen camera feed with parking distance overlay

**BCM Settings Menu** (accessible via rotary encoder long-press HOME):
- Theme selection (Classic Alfa / Modern Dark / OEM Digital)
- Voice language (Polski / English)
- Unit system (km/h + °C / mph + °F)
- Display brightness (0-100%)
- Audio EQ preset (Flat / Rock / Jazz / Bass Boost / Custom)
- Wake word sensitivity (Low / Medium / High)
- All settings persisted in `bcm_config.yaml`

**x86 vs OPi:**
- x86: PyGame window 800x480 + **Flask+WebSocket web viewer** (browser preview at `http://localhost:5000`)
- OPi: Direct framebuffer rendering via PyGame `fbcon` driver or Pillow → `/dev/fb0`

**x86 Simulation modes** (both available):
- **Auto demo mode** (default): sensors auto-generate realistic data (RPM ramp, temperature drift, parking approach)
- **Keyboard override**: manual control at any time (arrows=RPM, R=reverse, T=temperature, etc.)

**Dependencies:** Part 1 (config, event bus)

**Testing:** Run on x86 desktop — dashboard in PyGame window + open browser to web viewer. Both show live gauges with demo data. Switch themes from settings menu.

---

## PART 3: OBD-II / K-Line Communication

**Goal:** Implement KWP2000 protocol over K-Line UART to read ECU data from Bosch EDC15C7.

**Files to create:**
- `src/obd/kline.py` — K-Line physical layer: 5-baud init, 10400 baud serial, timing
- `src/obd/kwp2000.py` — KWP2000 protocol: startDiagnosticSession, readDataByLocalIdentifier, keepAlive
- `src/obd/edc15c7.py` — Bosch EDC15C7 specific: PID addresses for RPM, coolant temp, fuel rate, injector quantity, battery voltage, turbo pressure
- `src/obd/simulator.py` — x86 mock ECU: responds to KWP2000 requests with realistic simulated data

**Key specs:**
- L9637D transceiver: OPi UART3 (pins 8,10) at 10400 baud
- 5-baud initialization sequence (address 0x01 for EDC15)
- Polling cycle: ~100ms per parameter, round-robin through active PIDs
- Data published to event bus: `obd.rpm`, `obd.coolant_temp`, `obd.fuel_rate`, etc.

**Electrical (OPi only):**
```
+12V → [510Ω] → K-Line (OBD pin 7) → L9637D pin 1 (K)
L9637D pin 3 (RX) ← OPi UART3_TX (pin 8)
L9637D pin 4 (TX) → OPi UART3_RX (pin 10)
L9637D pin 5 (VS) ← +12V
L9637D pin 2 (GND) → GND
[100nF cap] between VS and GND
```

**x86 vs OPi:**
- x86: `simulator.py` creates a virtual serial pair (PTY), mock ECU runs in a thread
- OPi: Real `/dev/ttyS3` UART via L9637D transceiver to OBD-II port

**Dependencies:** Part 1 (config, event bus, HAL)

**Testing:** x86 — run simulator + reader, verify correct RPM/temp values published to event bus

---

## PART 4: Parking Sensors System

**Goal:** Drive 4x HC-SR04 ultrasonic sensors, calculate distances, display visual overlay, drive buzzer.

**Files to create:**
- `src/parking/hcsr04.py` — HC-SR04 driver: trigger pulse, echo timing, distance calculation
- `src/parking/distance.py` — Zone logic: >1m green, 0.5-1m yellow, 0.3-0.5m orange, <0.3m red
- `src/parking/buzzer.py` — Buzzer control: beep frequency proportional to distance, continuous <0.3m
- `src/parking/simulator.py` — x86 mock: keyboard/slider controls simulated distances

**Key specs:**
- Shared TRIG pin (one GPIO triggers all 4 sensors sequentially)
- 4 individual ECHO pins with 5V→3.3V voltage dividers (1kΩ + 2kΩ)
- Measurement cycle: ~60ms per sensor, 4 sensors = ~240ms full scan
- Activated only when reverse gear detected (event from power/ignition module)
- Visual: colored bars on 4.3" screen overlay (Part 2 `overlays.py`)

**Electrical (OPi only):**
```
GPIO_TRIG → 4× HC-SR04 TRIG (shared)
HC-SR04_1 ECHO → [1kΩ] → GPIO_ECHO_1 → [2kΩ] → GND
HC-SR04_2 ECHO → [1kΩ] → GPIO_ECHO_2 → [2kΩ] → GND
HC-SR04_3 ECHO → [1kΩ] → GPIO_ECHO_3 → [2kΩ] → GND
HC-SR04_4 ECHO → [1kΩ] → GPIO_ECHO_4 → [2kΩ] → GND
Buzzer: GPIO_BUZZ → [1kΩ] → BC547 base → collector → Buzzer → +5V
[1N4148 flyback diode across buzzer]
```

**x86 vs OPi:**
- x86: Simulated distances via keyboard (arrow keys) or random walk
- OPi: Real GPIO timing via `gpiod`

**Dependencies:** Part 1 (HAL, event bus), Part 2 (overlay rendering)

**Testing:** x86 — simulate approach to wall, verify zone transitions and buzzer frequency changes

---

## PART 5: Temperature & Environment Monitoring

**Goal:** Read exterior temperature from DS18B20, detect icing conditions, trigger alerts.

**Files to create:**
- `src/environment/ds18b20.py` — 1-Wire DS18B20 driver (reads `/sys/bus/w1/devices/` on OPi)
- `src/environment/icing.py` — Icing detection: temp <3°C with falling trend → alert; ≤0°C → permanent icon
- `src/environment/simulator.py` — x86 mock: configurable temperature curve

**Key specs:**
- DS18B20 on GPIO4_C1 (pin 7) with 4.7kΩ pull-up to 3.3V
- Read interval: every 10 seconds
- Icing alert: overlay popup + 3x buzzer beeps when temp drops below 3°C
- Status bar icon: snowflake when ≤0°C
- Published events: `env.temperature`, `env.icing_alert`

**Electrical (OPi only):**
```
DS18B20 DQ → GPIO pin 7 (1-Wire) + [4.7kΩ] → 3.3V
DS18B20 VDD → 3.3V
DS18B20 GND → GND
Sensor mounted under front bumper (shielded from engine heat)
```

**x86 vs OPi:**
- x86: Simulated temperature (configurable sine wave or manual input)
- OPi: Real 1-Wire kernel driver (`w1-gpio`, `w1-therm`)

**Dependencies:** Part 1 (HAL, event bus), Part 2 (status bar icon, alert overlay)

**Testing:** x86 — simulate temperature drop from 10°C to -5°C, verify alert triggers at 3°C

---

## PART 6: Audio System & PipeWire Integration

**Goal:** Configure PipeWire for 4.1 audio routing, EQ, source switching, and volume control.

**Files to create:**
- `src/audio/pipewire_ctrl.py` — PipeWire control via `pw-cli`/`pw-link`: route sources to DAC, set EQ
- `src/audio/source_manager.py` — Audio source switching: Android Auto, BT A2DP, FM Radio, system sounds
- `src/audio/ducking.py` — Audio priority & ducking: parking beeps > voice announcements > calls > music
- `src/audio/volume.py` — Volume control (master + per-source)
- `config/pipewire/pipewire.conf` — PipeWire configuration for USB DAC
- `config/pipewire/eq-profile.json` — 10-band EQ preset

**Key specs:**
- **USB DAC: ES9038Q2M** module (32-bit/384kHz, 129dB SNR, USB audio class compliant, ~45-75 PLN)
- **Main amplifier: TDA7388** (CD7388CZ) — 4-channel Class AB, 4×41W @ 14.4V/4Ω, MOSFET output (~45-70 PLN)
  - Built-in thermal shutdown and short circuit protection
  - Requires aluminum heatsink (Class AB ~50-60% efficiency, significant heat at load)
  - Supply voltage: 8-18V (nominal 14.4V car battery)
  - THD: <0.1% @ 1W/1kHz
- **Subwoofer amplifier: TDA2050** — mono Class AB, 32W @ 4Ω (~20-30 PLN)
  - Clean, musical output ideal for subwoofer duty
  - Requires small heatsink
  - Supply voltage: ±4.5V to ±25V (single supply 9-50V); on 12V car battery ~20W continuous
- **Total audio module cost: ~125-200 PLN** (within 150-200 PLN budget incl. heatsinks + wiring)
- PipeWire routes: AA/BT/FM → mixer → EQ → USB DAC (ES9038Q2M) → RCA → TDA7388 (4ch) + TDA2050 (sub)
- 10-band parametric EQ via PipeWire filter-chain
- **Audio priority & ducking system:**
  - Priority 1 (highest): **Parking sensor beeps** — music soft-muted to -18dB, beeps at full volume. Music stays in background as long as reverse gear is engaged.
  - Priority 2: **Voice announcements** (icing/overheating/low fuel TTS) — music soft-muted to -12dB, TTS voice at +3dB above normal. Music audible but clearly in background.
  - Priority 3: **Phone calls** (HFP) — music ducked to -15dB
  - Priority 4 (lowest): **Music/radio** — normal playback
  - Ducking: instant on trigger, smooth 1-second fade-back when priority event ends
  - Multiple priorities can stack (e.g., parking beeps + voice warning = music at -18dB, both beeps and voice audible)
- Volume control via BT remote (VOL+/VOL-) and rotary encoder

**Why ES9038Q2M over PCM5102A?**
- With Class AB amplification, DAC quality matters — AB faithfully reproduces the input signal
- ES9038Q2M: 129dB SNR vs PCM5102A 112dB — audible difference in mids/highs clarity
- THD+N: -120dB vs -93dB — cleaner signal, less distortion
- Worth the extra ~20-40 PLN for noticeably better audio quality

**Why Class AB over Class D (TPA3116D2)?**
- Class AB provides warmer, more natural sound with lower crossover distortion
- TDA7388 is a proven car audio IC used in factory head units
- Better transient response for music listening
- Tradeoff: lower efficiency (~55% vs ~90%), requires proper heatsink and ventilation

**Why not TDA2003?**
- TDA2003 is mono 10W only — would need 5 separate chips for 4.1 setup
- TDA7388 integrates 4 channels in one IC with better specs and protection

**x86 vs OPi:**
- x86: PipeWire with default sound card (laptop/desktop speakers)
- OPi: PipeWire with USB DAC (PCM5102A) as default sink

**Dependencies:** Part 1 (config, event bus), Part 8 (volume control from input)

**Testing:** x86 — play test tones, switch between sources, verify EQ applies

---

## PART 7: Voice Control (Vosk Integration)

**Goal:** Offline speech recognition with Vosk for hands-free car control.

**Files to create:**
- `src/voice/recognizer.py` — Vosk recognizer: microphone capture, continuous recognition
- `src/voice/wake_word.py` — Wake word detection ("Hej komputer" or configurable)
- `src/voice/commands.py` — Command grammar and dispatch to BCM modules
- `src/voice/languages.py` — Language-specific command definitions (PL + EN)
- `src/voice/tts.py` — Text-to-speech engine for voice announcements (pyttsx3, bilingual)
- Download/place Vosk models:
  - `src/voice/models/vosk-model-small-pl/` — Polish model (~50MB)
  - `src/voice/models/vosk-model-small-en-us/` — English model (~40MB)

**Key specs:**
- **Dual language support** — Polish and English, switchable from BCM settings
- Vosk small models (~40-50MB each) for low latency
- Active language saved in config, switchable at runtime via voice command or settings menu
- USB microphone input (mounted on ceiling/sun visor)
- Wake word activates 5-second listening window
  - Polish wake word: "Hej komputer"
  - English wake word: "Hey computer"
- Commands (Polish / English):
  - "Pokaż temperaturę" / "Show temperature" → show temperature overlay
  - "Włącz radio" / "Turn on radio" → switch audio to FM
  - "Następny utwór" / "Next track" → track control
  - "Poprzedni utwór" / "Previous track" → track control
  - "Głośniej" / "Volume up" → volume +10%
  - "Ciszej" / "Volume down" → volume -10%
  - "Pokaż zużycie" / "Show consumption" → fuel consumption screen
  - "Status samochodu" / "Car status" → read out RPM, temp, fuel via TTS
  - "Nagrywaj" / "Start recording" → dashcam on
  - "Zatrzymaj nagrywanie" / "Stop recording" → dashcam off
  - "Zmień język" / "Change language" → toggle PL↔EN
  - "Zmień styl" / "Change theme" → cycle dashboard theme
- Audio feedback: short beep on wake word detection, spoken response via TTS (pyttsx3, language-matched)
- **Voice announcements (TTS alerts)** — BCM speaks important events aloud:
  - Icing warning: "Uwaga, temperatura spada poniżej zera, możliwy lód na drodze" / "Warning, temperature below zero, possible ice on road"
  - Engine overheating: "Uwaga, wysoka temperatura silnika" / "Warning, engine temperature high"
  - Low fuel: "Niski poziom paliwa" / "Low fuel level"
  - Service reminder: "Zbliża się termin przeglądu" / "Service due soon"
  - Reverse gear engaged: short beep (no voice, parking sensors take over)
  - All voice announcements trigger audio ducking (music fades to background)

**x86 vs OPi:**
- x86: Same — USB microphone or laptop built-in mic, Vosk works on x86 natively
- OPi: Same Vosk model, USB mic, may need to test latency

**Dependencies:** Part 1 (event bus), Part 6 (audio source management for mic routing)

**Testing:** x86 — speak commands into mic, verify events dispatched correctly. Test in quiet and noisy (car engine sound playback) conditions.

---

## PART 8: Input Controllers

**Goal:** Handle rotary encoder (USB HID) and Bluetooth steering wheel remote.

**Files to create:**
- `arduino/rotary_encoder/rotary_encoder.ino` — Arduino Pro Micro firmware: encoder + 5 buttons → USB HID keycodes
- `src/input/rotary_encoder.py` — Listen for USB HID events from Arduino (via `evdev` or `hidapi`)
- `src/input/bt_remote.py` — Listen for BT HID events from steering wheel remote (via `evdev`)
- `src/input/action_dispatch.py` — Map keycodes to actions (navigate menu, volume, play/pause, etc.)

**Key specs:**
- Arduino Pro Micro (ATmega32U4) as USB HID keyboard
  - Encoder rotation → UP/DOWN arrows
  - Encoder push → ENTER
  - Buttons: HOME, BACK, MEDIA, VOL+, VOL-
- BT Remote (off-the-shelf BT HID): VOL+, VOL-, NEXT, PREV, PLAY/PAUSE, PHONE
- Action mapping published to event bus: `input.menu_up`, `input.volume_up`, etc.

**Arduino wiring:**
```
D2 ← Encoder CLK + [10kΩ pull-up]
D3 ← Encoder DT + [10kΩ pull-up]
D4 ← Encoder SW (push button)
D5 ← HOME button
D6 ← BACK button
D7 ← MEDIA button
D8 ← VOL+ button
D9 ← VOL- button
All buttons: active LOW with internal pull-ups
USB micro-B → cable 0.5m → OPi USB hub
```

**x86 vs OPi:**
- x86: Keyboard input simulation (arrow keys, enter, etc.) OR actual Arduino plugged in via USB
- OPi: Same USB HID + real BT remote paired

**Dependencies:** Part 1 (event bus)

**Testing:** x86 — plug in Arduino, rotate encoder, verify events. BT remote: pair and test key events.

---

## PART 9: Camera & Dashcam System

**Goal:** Dual-channel AHD dashcam recording + reverse camera feed on 4.3" display.

**Files to create:**
- `src/camera/ahd_grabber.py` — AHD USB3.0 grabber interface (V4L2)
- `src/camera/dashcam.py` — GStreamer pipeline: capture → H.264 encode → loop record to USB drive
- `src/camera/reverse_cam.py` — Reverse camera: on reverse-gear event, pipe rear camera to dashboard overlay

**Key specs:**
- 2× AHD 720P cameras (front windshield + rear license plate frame)
- 4-channel USB3.0 AHD grabber (presents as V4L2 devices)
- GStreamer pipeline: `v4l2src → videoconvert → x264enc/mpph264enc → splitmuxsink`
- Loop recording: 5-minute segments, oldest deleted when 128GB full (~47 hours capacity)
- Reverse camera: on `power.reverse_gear` event, feed rear camera to Part 2 overlay
- Hardware H.264 on RK3588 via `mpph264enc` (GStreamer rockchip plugin)

**x86 vs OPi:**
- x86: USB webcam as mock camera, software x264 encoding
- OPi: AHD grabber + hardware H.264 encoding (RK3588 VPU)

**Dependencies:** Part 1 (config, event bus), Part 2 (reverse camera overlay), Part 10 (reverse gear event)

**Testing:** x86 — record from webcam for 60s, verify file created and playable

---

## PART 10: Power Management

**Goal:** Handle ignition-based wake/sleep, backlight control, graceful shutdown.

**Files to create:**
- `src/power/power_manager.py` — State machine: STANDBY → WAKE → ACTIVE → REVERSE → SHUTDOWN
- `src/power/backlight.py` — PWM control for 2× display backlights (independent fade-in/out)
- `src/power/shutdown.py` — Graceful shutdown: stop dashcam, flush logs, sync filesystem

**Key specs:**
- Ignition signal via optoisolator (12V → 3.3V GPIO): HIGH = ignition ON
- Central lock signal via optoisolator: lock → initiate shutdown timer (30s)
- State machine:
  - STANDBY: backlights OFF, ~100mA draw
  - WAKE: ignition ON → backlights fade-in (1s), start modules
  - ACTIVE: full operation, ~1.2A
  - REVERSE: reverse gear detected → parking mode on 4.3" screen
  - SHUTDOWN: lock detected → save state → power down
- PWM backlight: 2× independent channels (GPIO PWM2 pin 32, PWM3 pin 33)

**Electrical (OPi only):**
```
Backlight 4.3":
  GPIO_PWM2 (pin 32) → [1kΩ] → BC547 base
  BC547 collector → IRLZ44N-A gate
  IRLZ44N-A: drain = display backlight GND, source = GND

Backlight 7":
  GPIO_PWM3 (pin 33) → [1kΩ] → BC547 base
  BC547 collector → IRLZ44N-B gate
  IRLZ44N-B: drain = display backlight GND, source = GND

Optoisolators (5× PC817):
  12V signal → [4.7kΩ] → PC817 LED → GND
  PC817 collector → GPIO (pull-up 10kΩ to 3.3V)
  PC817 emitter → GND
  Signals: IGN, DOOR, RAIN, SPRAYER, CENTRAL_LOCK
```

**x86 vs OPi:**
- x86: Simulated state machine via keyboard (I=ignition, R=reverse, L=lock)
- OPi: Real GPIO inputs via optoisolators

**Dependencies:** Part 1 (HAL, event bus, config)

**Testing:** x86 — simulate ignition cycle, verify state transitions and module start/stop

---

## PART 11: Android Auto / Multimedia (7" Screen)

**Goal:** Set up OpenAuto Pro on the 7" screen with Bluetooth audio.

**Files to create:**
- `src/multimedia/openauto.py` — OpenAuto Pro launcher and control interface
- `src/multimedia/bluetooth.py` — BlueZ configuration for A2DP sink + HFP

**Key specs:**
- OpenAuto Pro renders on HDMI-2 (7" touchscreen, 1024x600)
- Touch input via USB from the 7" panel
- BT A2DP sink: phone streams music → PipeWire → DAC
- BT HFP: phone calls with mic + speaker routing
- Optional: Carlinkit USB dongle for wireless Android Auto/CarPlay
- Optional: RTL-SDR for FM radio reception

**x86 vs OPi:**
- x86: OpenAuto Pro in windowed mode (if available) or stub with BT audio only
- OPi: OpenAuto Pro full-screen on HDMI-2, EGL/SDL2 rendering

**Dependencies:** Part 1 (config), Part 6 (PipeWire routing), Part 8 (BT remote control)

**Testing:** x86 — pair phone via BT, stream music, verify audio output

---

## PART 12: Electrical Schematics & Hardware Assembly

**Goal:** Create clear, complete electrical diagrams and assembly instructions.

**Files to create:**
- `schematics/README.md` — Assembly guide with step-by-step instructions
- `schematics/main_wiring.svg` — Complete system wiring overview
- `schematics/kline_circuit.svg` — L9637D K-Line transceiver schematic
- `schematics/backlight_mosfet.svg` — Dual MOSFET backlight PWM circuits
- `schematics/parking_sensors.svg` — HC-SR04 wiring with voltage dividers
- `schematics/audio_system.svg` — USB DAC → AMP → Speaker wiring
- `schematics/power_supply.svg` — LM2596 12V→5.1V, fusing, distribution
- `schematics/gpio_pinout.svg` — Complete 40-pin GPIO allocation map
- `schematics/optoisolators.svg` — PC817 circuits for vehicle signal isolation
- `schematics/vehicle_layout.svg` — Cable routing through the Alfa 156

**Key circuits documented:**

1. **Power Supply:** Battery 12V → 20A fuse → LM2596 (5.1V/4A) → OPi + peripherals
   - Separate 12V path (25A fused) for TDA7388 + TDA2050 amplifiers (Class AB draws more than Class D)
2. **K-Line:** L9637D transceiver with 510Ω pull-up, 100nF decoupling
3. **Backlights:** 2× BC547 + IRLZ44N MOSFET per display, PWM driven
4. **Parking:** Shared TRIG, 4× ECHO with resistive dividers, buzzer with flyback diode
5. **Optoisolators:** 5× PC817 for 12V vehicle signals to 3.3V GPIO
6. **Audio:** USB DAC (ES9038Q2M) → RCA → TDA7388 Class AB (4ch) + TDA2050 (sub) → 4 speakers + subwoofer
7. **Temperature:** DS18B20 with 4.7kΩ pull-up, 3-wire to under bumper
8. **ADC:** MCP3008 on SPI for analog fuel pump sensor
9. **RTC:** DS3231 on I2C for accurate timekeeping

**Dependencies:** None (documentation only, but references all other parts)

**Deliverable:** SVG diagrams created using text-based schematic descriptions (ASCII art and/or KiCad-compatible files)

---

## PART 13: System Integration & Testing

**Goal:** Wire all modules together, create systemd services, perform end-to-end testing.

**Files to create:**
- `config/systemd/bcm-dashboard.service` — 4.3" dashboard renderer
- `config/systemd/bcm-obd.service` — OBD-II reader
- `config/systemd/bcm-dashcam.service` — Dashcam recording
- `config/systemd/bcm-voice.service` — Voice recognition
- `config/systemd/bcm-power.service` — Power manager (started first)
- `src/core/event_bus.py` — Enhance for cross-process communication (Unix sockets or Redis)
- Integration tests in `tests/`

**Key specs:**
- Each module runs as independent systemd service
- Inter-service communication via Unix domain sockets (or shared event bus)
- Boot sequence: power_manager → dashboard → obd → dashcam → voice → multimedia
- Total boot time target: <3 seconds from ignition to dashboard display
- Watchdog: systemd watchdog for each service, auto-restart on crash

**x86 vs OPi:**
- x86: Run all modules in single process or tmux for integration testing
- OPi: Full systemd deployment with service dependencies

**Dependencies:** All other parts (this is the final integration)

**Testing:** Full integration test: simulate ignition → dashboard appears → OBD data flows → voice command → dashcam recording → reverse gear → parking overlay → shutdown

---

## Dependency Graph

```
Part 1 (Skeleton) ← foundation for everything
  ├── Part 2 (Dashboard) ← visual output
  │     ├── Part 4 (Parking) ← overlay on dashboard
  │     └── Part 5 (Environment) ← overlay on dashboard
  ├── Part 3 (OBD) ← data for dashboard
  ├── Part 6 (Audio) ← sound system
  │     └── Part 7 (Voice) ← uses audio for mic
  ├── Part 8 (Input) ← controls everything
  ├── Part 9 (Camera) ← depends on Part 2 (overlay) + Part 10 (reverse)
  ├── Part 10 (Power) ← state management
  ├── Part 11 (Multimedia) ← depends on Part 6 (audio)
  ├── Part 12 (Schematics) ← independent, hardware docs
  └── Part 13 (Integration) ← depends on all
```

## Recommended Implementation Order

1. **Part 1** — Project Skeleton (required first)
2. **Part 2** — Dashboard Renderer (visual feedback early)
3. **Part 3** — OBD-II Communication (core car data)
4. **Part 8** — Input Controllers (interact with dashboard)
5. **Part 5** — Temperature Monitoring (simple sensor, visible result)
6. **Part 7** — Voice Control / Vosk (key feature, test early)
7. **Part 4** — Parking Sensors (needs dashboard overlay)
8. **Part 10** — Power Management (state machine)
9. **Part 6** — Audio / PipeWire (complex config)
10. **Part 9** — Camera / Dashcam (GStreamer pipeline)
11. **Part 11** — Multimedia / Android Auto (external dependency)
12. **Part 12** — Electrical Schematics (can be done anytime)
13. **Part 13** — System Integration (last)

## Verification

For each part on x86:
1. `pip install -r requirements.txt -r requirements-x86.txt`
2. `python main.py --platform x86 --modules <module_name>`
3. Module-specific tests: `pytest tests/test_<module>.py`
4. Visual verification: dashboard window shows correct gauges/overlays

For OPi deployment:
1. Flash Armbian to eMMC/SD
2. Install dependencies: `pip install -r requirements.txt -r requirements-opi.txt`
3. Configure GPIO/UART in `bcm_config.yaml`
4. Deploy systemd services: `sudo cp config/systemd/*.service /etc/systemd/system/`
5. `sudo systemctl enable --now bcm-power bcm-dashboard bcm-obd bcm-dashcam bcm-voice`
6. Connect hardware per Part 12 schematics
7. Full integration test per Part 13
