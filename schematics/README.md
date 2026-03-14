# BCM v7 — Electrical Schematics & Assembly Guide

## Alfa Romeo 156 Custom Headunit — Hardware Documentation

This directory contains all electrical schematics and wiring diagrams for the BCM v7 headunit system installed in an Alfa Romeo 156.

---

## System Overview

| Component | Description |
|-----------|-------------|
| **SBC** | Orange Pi 5 Plus (RK3588, 16GB RAM) |
| **Display 1** | 4.3" TFT (480×272) — BCM dashboard |
| **Display 2** | 7" IPS (1024×600) — Android Auto / multimedia |
| **Audio** | USB DAC (ES9038Q2M) → TDA7388 4ch Class AB + TDA2050 sub |
| **OBD** | L9637D K-Line transceiver → OBD-II port |
| **Cameras** | 2× AHD 720P via USB3.0 4ch grabber |
| **Parking** | 4× HC-SR04 ultrasonic sensors |
| **Input** | Arduino Pro Micro rotary encoder + BT remote |
| **Microphone** | USB condenser (ceiling mount) |
| **Temperature** | DS18B20 1-Wire (under front bumper) |

---

## Schematic Files

| File | Description |
|------|-------------|
| `main_wiring.svg` | Complete system wiring overview |
| `power_supply.svg` | 12V→5.1V LM2596 supply, fusing, distribution |
| `kline_circuit.svg` | L9637D K-Line transceiver for OBD-II |
| `backlight_mosfet.svg` | Dual MOSFET PWM backlight drivers |
| `parking_sensors.svg` | HC-SR04 wiring with voltage dividers |
| `audio_system.svg` | USB DAC (ES9038Q2M) → TDA7388 + TDA2050 → speaker layout |
| `gpio_pinout.svg` | Complete 40-pin GPIO allocation |
| `optoisolators.svg` | 5× PC817 vehicle signal isolation |
| `vehicle_layout.svg` | Cable routing through the Alfa 156 |

---

## Assembly Instructions

### Step 1: Power Supply

1. Connect battery 12V to 20A fuse holder (inline, under dash)
2. Wire fuse output to LM2596 module input (VIN+/VIN-)
3. Adjust LM2596 to 5.1V output (measure with multimeter before connecting!)
4. Wire LM2596 output to OPi 5 Plus via USB-C PD trigger board (5V/4A)
5. Separate 12V branch (25A fuse) directly to TDA7388 + TDA2050 amplifiers
   - Class AB amplifiers draw more current than Class D — 25A fuse recommended

**Warning:** Always verify 5.1V output before connecting Orange Pi. Overvoltage will damage the board.

### Step 2: K-Line Interface

1. Solder L9637D on perfboard with:
   - Pin 1 (TXD) → OPi UART TX (GPIO pin 8)
   - Pin 2 (RXD) → OPi UART RX (GPIO pin 10)
   - Pin 3 (GND) → common ground
   - Pin 4 (VCC) → 5V from LM2596
   - Pin 6 (K-Line) → OBD-II port pin 7
   - 510Ω pull-up from K-Line to 12V
   - 100nF decoupling cap on VCC-GND
2. Run 3-wire cable (TX, RX, GND) from perfboard to OPi GPIO header
3. Run 2-wire cable (K-Line, GND) to OBD-II connector under dash

### Step 3: Display Backlights

For each display (4.3" and 7"):

1. BC547 transistor:
   - Base → 1kΩ resistor → OPi GPIO PWM pin
   - Collector → 10kΩ resistor → IRLZ44N gate
   - Emitter → GND
2. IRLZ44N MOSFET:
   - Gate → BC547 collector (with 10kΩ pull-down to GND)
   - Drain → Display backlight GND wire
   - Source → System GND
3. Display backlight VCC → 12V supply

Pin assignments:
- 4.3" display: GPIO PWM2 (pin 32)
- 7" display: GPIO PWM3 (pin 33)

### Step 4: Parking Sensors

1. Mount 4× HC-SR04 in rear bumper (drill 16mm holes, equal spacing)
2. Wiring per sensor:
   - VCC → 5V
   - GND → GND
   - TRIG → Shared trigger line → OPi GPIO (pin 16)
   - ECHO → Voltage divider (1kΩ + 2kΩ) → Individual OPi GPIO pin
3. Echo pin assignments: pin 18, pin 22, pin 24, pin 26
4. Add 100nF decoupling cap per sensor (VCC-GND)
5. Piezo buzzer:
   - Positive → OPi GPIO (pin 12) via NPN transistor
   - 1N4148 flyback diode across buzzer terminals

### Step 5: Optoisolators (Vehicle Signals)

For each of the 5 signals (IGN, DOOR, RAIN, SPRAYER, CENTRAL_LOCK):

1. 12V signal → 4.7kΩ resistor → PC817 LED anode
2. PC817 LED cathode → GND
3. PC817 collector → OPi GPIO pin (with 10kΩ pull-up to 3.3V)
4. PC817 emitter → GND

GPIO assignments:
- Ignition: pin 29
- Door open: pin 31
- Rain sensor: pin 33
- Washer sprayer: pin 35
- Central lock: pin 37

### Step 6: Audio System

**Components (~125-200 PLN total):**
- ES9038Q2M USB DAC module (~45-75 PLN) — 129dB SNR, pairs well with Class AB
- TDA7388 (CD7388CZ) 4-channel Class AB amp board (~45-70 PLN)
- TDA2050 mono Class AB amp board for subwoofer (~20-30 PLN)
- Aluminum heatsink for TDA7388 (~15-25 PLN)

**Assembly:**
1. ES9038Q2M USB DAC module → USB port on OPi (auto-detected as ALSA sink)
2. DAC RCA L/R output → TDA7388 4-channel amplifier input (L/R stereo)
3. DAC RCA output → TDA2050 mono amp input (use L+R summed, or split from DAC)
4. TDA7388 outputs:
   - Channel 1 → Front Left door speaker (4Ω)
   - Channel 2 → Front Right door speaker (4Ω)
   - Channel 3 → Rear Left shelf speaker (4Ω)
   - Channel 4 → Rear Right shelf speaker (4Ω)
5. TDA2050 output → Subwoofer (4Ω, trunk mount)
6. Mount TDA7388 on aluminum heatsink (Class AB ~50-60% efficiency = significant heat)
7. Mount TDA2050 on small heatsink
8. Amplifier power: 12V direct from battery (25A fused, shared for both amps)
9. Mount both amps in trunk with ventilation (fan recommended for summer)

**Important:** Class AB amplifiers generate more heat than Class D. Ensure adequate
ventilation in the trunk enclosure. TDA7388 at moderate volume draws ~6-8A, peaks ~15A.

### Step 7: Temperature Sensor

1. DS18B20 (waterproof probe):
   - VCC (red) → 3.3V
   - GND (black) → GND
   - DATA (yellow) → OPi GPIO pin 7 (1-Wire)
   - 4.7kΩ pull-up between DATA and VCC
2. Route 3-wire cable through firewall to under front bumper
3. Secure probe to bumper frame with cable ties

### Step 8: Cameras

1. Mount front AHD camera behind rearview mirror
2. Mount rear AHD camera in license plate frame
3. Route cables through cabin to trunk
4. Connect both to USB3.0 AHD grabber (channels 0 + 1)
5. Connect grabber to OPi USB3.0 port

### Step 9: Input Controller

1. Arduino Pro Micro + rotary encoder assembly:
   - D2 ← Encoder CLK (with 10kΩ pull-up)
   - D3 ← Encoder DT (with 10kΩ pull-up)
   - D4 ← Encoder SW (push, active LOW, internal pull-up)
   - D5-D9 ← HOME, BACK, MEDIA, VOL+, VOL- buttons
2. Mount encoder/buttons in custom center console panel
3. USB cable from Arduino to OPi USB hub

### Step 10: Final Assembly

1. Mount OPi 5 Plus in ventilated enclosure behind dash
2. Connect all cables per schematic
3. Flash Arduino firmware (`arduino/rotary_encoder/rotary_encoder.ino`)
4. Install OS image with all software pre-configured
5. Test each subsystem individually before full integration
6. Secure all cables with cable ties and split loom tubing

---

## GPIO Pin Allocation (Orange Pi 5 Plus — 40-pin header)

| Pin | Function | Module |
|-----|----------|--------|
| 7 | 1-Wire DATA (DS18B20) | Environment |
| 8 | UART TX (L9637D TXD) | OBD |
| 10 | UART RX (L9637D RXD) | OBD |
| 12 | Buzzer control | Parking |
| 16 | HC-SR04 TRIG (shared) | Parking |
| 18 | HC-SR04 ECHO sensor 1 | Parking |
| 22 | HC-SR04 ECHO sensor 2 | Parking |
| 24 | HC-SR04 ECHO sensor 3 | Parking |
| 26 | HC-SR04 ECHO sensor 4 | Parking |
| 29 | Ignition signal (PC817) | Power |
| 31 | Door open signal (PC817) | Power |
| 32 | PWM2 — 4.3" backlight | Power |
| 33 | PWM3 — 7" backlight / Rain sensor | Power |
| 35 | Washer sprayer signal (PC817) | Power |
| 37 | Central lock signal (PC817) | Power |

---

## Power Budget

| Component | Voltage | Current | Notes |
|-----------|---------|---------|-------|
| Orange Pi 5 Plus | 5.1V | 2.0A max | Via USB-C PD |
| 4.3" Display | 12V | 0.15A | Backlight via MOSFET |
| 7" Display | 12V | 0.3A | Backlight via MOSFET |
| USB DAC | 5V | 0.1A | Via OPi USB |
| Arduino Pro Micro | 5V | 0.05A | Via OPi USB |
| HC-SR04 ×4 | 5V | 0.06A | 15mA each |
| DS18B20 | 3.3V | 0.001A | Negligible |
| USB Mic | 5V | 0.1A | Via OPi USB |
| AHD Grabber | 5V | 0.5A | Via USB3.0 |
| **5V Total** | **5.1V** | **~3.0A** | LM2596 4A rated |
| TDA7388 Amp (4ch) | 12V | 5-15A | Class AB, separate 25A fused line |
| TDA2050 Amp (sub) | 12V | 1-4A | Class AB, shared fused line |
| **12V Total** | **12V** | **~20A peak** | 25A fuse recommended |
