# BCM v8.5 — Redmi Note 8 Pro — Shopping List & Prices

## Overview

This is the complete shopping list for building BCM v8.5 using a **Redmi Note 8 Pro**
instead of the Orange Pi 5 Plus. The phone replaces the SBC, main display, GPS module,
LTE modem, Bluetooth adapter, and one microphone — saving significant cost.

**Prices are in PLN, estimated for Q1 2026.** Prices may vary by retailer.

---

## STAGE 1: Core System — Dashboard + Audio + OBD

*Minimum viable system. Start here.*

| # | Component | Model / Spec | Qty | Price (PLN) | Notes |
|---|-----------|-------------|-----|-------------|-------|
| 1 | Phone | **Redmi Note 8 Pro 6GB** (used, unlocked BL) | 1 | 300-500 | Codename: begonia. Must have unlocked bootloader |
| 2 | USB-C OTG Hub | 7-in-1 with HDMI + PD charging | 1 | 80-150 | HDMI for 4.3" screen, PD for charging |
| 3 | DC-DC Converter | LM2596 12V→5.1V 4A | 1 | 30-50 | Powers hub + phone via PD |
| 4 | Fuses | 5A + 25A blade fuse | 2 | 10 | 5V line + 12V audio |
| 5 | USB DAC | ES9038Q2M | 1 | 45-75 | 32-bit audio, RCA out |
| 6 | Amplifier (main) | TDA7388 (4×45W) | 1 | 45-70 | 4-channel Class AB |
| 7 | Heatsink | Aluminum (for TDA7388) | 1 | 10-15 | |
| 8 | K-Line adapter | USB-UART CP2102 + L9637D + 510Ω | 1 | 25-40 | OBD-II communication |
| 9 | Arduino (input) | Pro Micro ATmega32U4 | 1 | 40-60 | SWC buttons + LDR |
| 10 | Optoisolators | PC817 | 3 | 6-9 | Ignition, door, reverse |
| 11 | Resistors/transistors | BC547 + resistor kit | — | 15-20 | Pull-ups, dividers |
| 12 | USB-C cable | Short (20-30cm) | 2 | 15-25 | Phone to hub, power to hub |
| 13 | Cables + connectors | HDMI mini, USB-A, power | — | 40-60 | |
| 14 | Phone mount | DIN bracket or 3D-printed | 1 | 20-50 | Landscape orientation |

### Stage 1 Cost: **~680 — 1,125 PLN**

**What you get:** Touchscreen dashboard with 8 screens (A1-A8), 3 themes,
music via Bluetooth (built-in), OBD-II engine data, Android Auto via WiFi,
built-in GPS, built-in LTE internet, voice control via built-in mic.

> **Savings vs Orange Pi:** ~670-775 PLN less than OPi Stage 1 (1,350-1,900 PLN)
> because the phone replaces: SBC (600-750), main display (400-600),
> BT adapter (30-60), GPS module, LTE modem.

---

## STAGE 2: Cameras + Sensors + Second Screen

*DVR, reverse camera, parking sensors, temperature, small display.*

| # | Component | Model / Spec | Qty | Price (PLN) | Notes |
|---|-----------|-------------|-----|-------------|-------|
| 15 | Second screen | 4.3" TFT HDMI 800×480 | 1 | 150-250 | Static 2×2 stats grid + auto-switching camera |
| 16 | AHD Cameras | 720P front + rear | 2 | 200-400 | Waterproof, IR night vision |
| 17 | Video grabber | USB3.0 4-ch AHD capture | 1 | 150-250 | Via OTG hub |
| 18 | USB drive (DVR) | USB 3.0 128GB | 1 | 80-150 | Loop recording storage |
| 19 | Sensor hub Arduino | Arduino Nano + CH340 | 1 | 20-35 | Handles all GPIO sensors |
| 20 | Parking sensors | HC-SR04 ultrasonic | 4 | 60-80 | Connected to sensor hub |
| 21 | Buzzer | Piezo 5V | 1 | 5-10 | Parking warning |
| 22 | Temperature sensor | DS18B20 waterproof | 1 | 20-30 | Connected to sensor hub |
| 23 | Optoisolators (extra) | PC817 | 3 | 6-9 | Rain, wiper, lock signals |
| 24 | USB Microphone #2 | Mini/clip USB mic | 1 | 20-40 | Phone calls / AA (separate from built-in) |
| 25 | Voltage dividers | 1kΩ + 2kΩ resistors | 4 sets | 8-12 | HC-SR04 echo 5V→3.3V |
| 26 | Perfboard + headers | For sensor hub wiring | 1 | 10-15 | |

### Stage 2 Cost: **~730 — 1,280 PLN**

**What you get:** Dashcam (front + rear), reverse camera with parking overlay,
4-zone parking sensors with buzzer, external temperature, small stats display,
dedicated phone/AA microphone.

---

## STAGE 3: Connectivity + Subwoofer + Rain Sensor

*Enhanced audio, weather, auto-wipers.*

| # | Component | Model / Spec | Qty | Price (PLN) | Notes |
|---|-----------|-------------|-----|-------------|-------|
| 27 | Subwoofer amp | TDA2050 (40W mono) | 1 | 20-30 | Class AB, LP filter ~120Hz |
| 28 | Heatsink (sub) | Aluminum | 1 | 5-10 | |
| 29 | Rain sensor | Digital rain sensor module | 1 | 30-50 | Via optoisolator to sensor hub |
| 30 | Wiper relay | 5V relay module | 1 | 8-12 | Wiper activation |

### Stage 3 Cost: **~63 — 102 PLN**

**What you get:** Subwoofer bass, auto-wipers on rain detection.

> **Note:** GPS, LTE, and weather are **free** on Redmi — the phone has built-in
> GPS and cellular data. No external modules needed (saves ~140-280 PLN vs OPi).

---

## STAGE 4: Central Lock + Alarm + Tracking

*Smart lock, security system, battery backup.*

| # | Component | Model / Spec | Qty | Price (PLN) | Notes |
|---|-----------|-------------|-----|-------------|-------|
| 31 | Arduino (lock) | Nano / Pro Mini | 1 | 20-30 | Central lock controller |
| 32 | Relay module | 10-ch relay 5V | 1 | 40-60 | Lock, windows, trunk, lights |
| 33 | RF receiver | RXB6 433MHz | 1 | 15-25 | Key fob receiver |
| 34 | Siren | 12V piezo 120dB | 1 | 25-40 | Alarm output |
| 35 | PIR sensor | HC-SR501 mini | 1 | 10-15 | Motion detection (cabin) |
| 36 | Shock sensor | Piezo vibration sensor | 1 | 8-12 | Impact detection |
| 37 | Accelerometer | MPU6050 6-axis | 1 | 15-30 | Tilt/tow detection |
| 38 | Alarm LED | 5mm LED + resistor | 1 | 2-3 | Dashboard indicator |
| 39 | Backup battery | Li-ion 18650 5000mAh | 1 | 20-30 | GPS tracking when off |
| 40 | Charger + boost | TP4056 + MT3608 | 1 | 18-30 | 3.7V→5V conversion |
| 41 | Power relay | Switching relay | 1 | 8-12 | Battery/car power switch |

### Stage 4 Cost: **~180 — 285 PLN**

**What you get:** Central lock with RF 433MHz key fob, window/trunk control,
car alarm (motion + shock + tilt), follow-me-home lights, greeting blinks,
GPS tracking for 30h on battery backup, crash detection with DVR protection.

---

## Cost Summary

| Stage | What You Get | Min (PLN) | Max (PLN) | Cumulative |
|-------|-------------|-----------|-----------|------------|
| **1. Core** | Dashboard + Audio + OBD + AA + BT + GPS + LTE | 680 | 1,125 | 680 — 1,125 |
| **2. Cameras** | DVR + Reverse + Parking + Temp + Small Screen | 730 | 1,280 | 1,410 — 2,405 |
| **3. Audio+** | Subwoofer + Rain Sensor | 63 | 102 | 1,473 — 2,507 |
| **4. Security** | Lock + Alarm + Tracking + Battery | 180 | 285 | 1,653 — 2,792 |

### **TOTAL: ~1,650 — 2,800 PLN**

---

## Cost Comparison: Redmi vs Orange Pi

| Component | Orange Pi Build | Redmi Build | Savings |
|-----------|----------------|-------------|---------|
| SBC / Phone | 600-750 (OPi 5+) | 300-500 (used Redmi) | 300-250 |
| Main display (7") | 400-600 | 0 (built-in) | 400-600 |
| BT adapter | 30-60 | 0 (built-in) | 30-60 |
| GPS module | 40-80 | 0 (built-in) | 40-80 |
| LTE modem | 100-200 | 0 (built-in) | 100-200 |
| Microphone #1 | 30-50 | 0 (built-in) | 30-50 |
| MOSFET backlight | 4-6 | 0 (phone handles) | 4-6 |
| USB-C Hub w/HDMI | 0 (not needed) | 80-150 | -80 to -150 |
| Sensor Hub Arduino | 0 (GPIO direct) | 20-35 | -20 to -35 |
| **Total difference** | **2,480 — 3,840** | **1,650 — 2,800** | **~830 — 1,040 saved** |

> **Bottom line:** The Redmi build saves approximately **830-1,040 PLN** compared
> to the Orange Pi build, mainly because the phone integrates the display, GPS,
> LTE, Bluetooth, and microphone.

---

## Where to Buy (Poland)

| Retailer | Best For | URL |
|----------|----------|-----|
| Allegro | Used Redmi, sensors, Arduinos | allegro.pl |
| Botland | Arduino, sensors, electronics | botland.com.pl |
| Kamami | Electronic components, ICs | kamami.pl |
| AliExpress | Bulk sensors, USB hubs, cameras | aliexpress.com |
| Amazon.pl | USB-C hubs, displays, USB DAC | amazon.pl |
| OLX | Used Redmi Note 8 Pro | olx.pl |
| Nettigo | Arduino, breakout boards | nettigo.pl |

---

## Not Included in Prices

- Car speakers (4× coaxial) — reuse existing or ~200-400 PLN
- Subwoofer driver (1× 8") — ~100-200 PLN
- Automotive wiring (12V cables, connectors) — ~50-100 PLN
- DIN mounting bracket / 3D print — ~20-50 PLN
- SIM card with data plan (for LTE) — use existing phone SIM
- Key fob 433MHz transmitter — ~20-40 PLN each
- Labor / installation time
