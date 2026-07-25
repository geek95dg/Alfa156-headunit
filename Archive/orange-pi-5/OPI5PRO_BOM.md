# BCM v8.5 — Orange Pi 5 Pro 4GB — Bill of Materials

Primary recommended production build for the Alfa 156 BCM head unit.
Prices in **PLN**, Q1 2026 estimates from Polish retailers.

The **Orange Pi 5 Pro 4GB** replaces the more expensive OPi 5 Plus for
this build: it has the same RK3588S SoC class, two HDMI outputs
(**HDMI 2.1 + HDMI 2.0** — perfect for the 7" main + 4.3" small displays),
built-in WiFi 6 + BT 5.0, and hardware H.264 encoding for the dashcam.
4 GB of RAM is plenty for the full feature set including Android Auto,
dashcam recording and the travel planner.

---

## STAGE 1: Core System — Dashboard + Audio + OBD

| # | Component | Model / Spec | Qty | Price (PLN) | Notes |
|---|-----------|-------------|-----|-------------|-------|
| 1 | SBC | **Orange Pi 5 Pro 4GB** (RK3588S, HDMI 2.1 + 2.0, WiFi 6, BT 5.0) | 1 | 350-450 | Primary compute platform |
| 2 | Heatsink + fan | 40×40 mm for RK3588S | 1 | 25-40 | Required for sustained load |
| 3 | microSD / NVMe | 64 GB microSD (Class 10) or 128 GB NVMe | 1 | 40-120 | NVMe recommended if slot is used |
| 4 | Power supply | LM2596 12V → 5.1V 4A | 1 | 30-50 | Step-down from car 12V |
| 5 | USB-C power cable | 5.1V PD trigger 5A | 1 | 20-30 | Into the OPi USB-C power port |
| 6 | Fuses | 5A blade (OPi) + 25A blade (amps) | 2 | 10 | |
| 7 | Main display | 7" IPS 1024×600 HDMI + USB touch | 1 | 200-350 | → HDMI 2.1 |
| 8 | Small display | 4.3" TFT 800×480 HDMI (no touch) | 1 | 150-250 | → HDMI 2.0, static 2×2 grid |
| 9 | USB DAC | ES9038Q2M module | 1 | 45-75 | 32-bit audio out |
| 10 | Amplifier (main) | TDA7388 (4×45 W Class AB) | 1 | 45-70 | 4-channel + thermal shutdown |
| 11 | Heatsink | Aluminium (TDA7388) | 1 | 10-15 | |
| 12 | K-Line adapter | CP2102 USB-UART + L9637D + 510 Ω | 1 | 25-40 | OBD-II on UART3 |
| 13 | Cables | 2× HDMI, USB-A, power, audio RCA | — | 50-80 | |

**Stage 1 cost: ~1 000 — 1 560 PLN**

---

## STAGE 2: Cameras (4-way) + Sensors + Dashcam

This is the phase that changed the most in the v8.5 update: four cameras
instead of two, plus a 4-channel USB video grabber.

| # | Component | Model / Spec | Qty | Price (PLN) | Notes |
|---|-----------|-------------|-----|-------------|-------|
| 14 | **4-camera set** (front / rear / left / right) | [AliExpress ~228 PLN set — **promo ~125 PLN**](https://pl.aliexpress.com/item/1005009603425964.html) | 1 | 110-230 | Includes 4 AHD 720p cameras + cables + a video interface |
| 15 | 4-ch USB video grabber | USB 2.0/3.0 4-channel AHD capture (e.g. EasyCap 4ch) | 1 | 150-250 | Presents as 4× `/dev/videoN` |
| 16 | Parking sensors | HC-SR04 ultrasonic | 4 | 40-60 | Rear bumper |
| 17 | Buzzer | Piezo 5V | 1 | 5-10 | Parking warning |
| 18 | Temperature sensor | DS18B20 waterproof | 1 | 20-30 | Under front bumper |
| 19 | Optoisolators | PC817 | 6 | 12-18 | Ignition, door, rain, lock, **left blinker**, **right blinker** |
| 20 | Transistors | BC547 kit | 1 | 5-10 | Buzzer + backlight drivers |
| 21 | MOSFETs | IRLZ44N for backlight PWM | 2 | 5-10 | |
| 22 | Resistor kit | 1 kΩ, 2 kΩ, 4.7 kΩ, 10 kΩ | 1 | 10-15 | Voltage dividers, pull-ups |
| 23 | Perfboard + headers | For sensor wiring | 1 | 10-15 | |
| 24 | USB SSD (dashcam) | 128 GB USB 3.0 | 1 | 80-150 | ~47 h of HW H.264 loop |

**Stage 2 cost: ~447 — 798 PLN**

> The 4-camera set + 4-channel grabber are the new production baseline
> because the A3 Trip screen and the 4.3" small display now switch
> between rear / left / right feeds automatically (reverse gear, left
> blinker, right blinker).

---

## STAGE 3: Input, Connectivity

| # | Component | Model / Spec | Qty | Price (PLN) | Notes |
|---|-----------|-------------|-----|-------------|-------|
| 25 | USB microphone | Condenser, ceiling-mount | 1 | 30-60 | HFP phone calls |
| 26 | Input Arduino | Pro Micro (ATmega32U4) | 1 | 40-60 | SWC + rotary encoder |
| 26a | **SWC button kits** | AliExpress round pods (2× pods + decoder box) | 2 | ~80 | Dual-pod, 24 buttons total, resistor-ladder → Arduino A0 |
| 27 | Rotary encoder | Panel-mount with push button | 1 | 10-20 | |
| 28 | GPS module | u-blox 7/8 USB | 1 | 40-80 | Built-in on some OPi 5 Pro revisions |
| 29 | LTE modem | Huawei E3372 HiLink | 1 | 60-120 | Optional (for travel planner) |

**Stage 3 cost: ~260 — 420 PLN**

---

## STAGE 4: Subwoofer + Rain Sensor

| # | Component | Model / Spec | Qty | Price (PLN) | Notes |
|---|-----------|-------------|-----|-------------|-------|
| 30 | Subwoofer amp | TDA2050 (40 W mono Class AB) | 1 | 20-30 | |
| 31 | Heatsink (sub) | Aluminium | 1 | 5-10 | |
| 32 | Rain sensor | Digital rain sensor module | 1 | 30-50 | Optoisolated input |
| 33 | Wiper relay | 5V relay module | 1 | 8-12 | |

**Stage 4 cost: ~63 — 102 PLN**

---

## STAGE 5: Optional security & tracking (unchanged from OPi 5 Plus build)

| # | Component | Model / Spec | Qty | Price (PLN) | Notes |
|---|-----------|-------------|-----|-------------|-------|
| 34 | Central lock Arduino | Nano / Pro Mini | 1 | 20-30 | 433 MHz RF + lock relays |
| 35 | Relay module | 10-ch 5V | 1 | 40-60 | |
| 36 | RF receiver | RXB6 433 MHz | 1 | 15-25 | Key fob |
| 37 | Siren | 12V piezo 120 dB | 1 | 25-40 | |
| 38 | PIR | HC-SR501 mini | 1 | 10-15 | Cabin motion |
| 39 | Shock sensor | Piezo vibration | 1 | 8-12 | |
| 40 | Accelerometer | MPU6050 | 1 | 15-30 | Crash / tilt detection |
| 41 | Backup battery | 18650 Li-ion 5000 mAh | 1 | 20-30 | GPS tracking when off |
| 42 | Charger + boost | TP4056 + MT3608 | 1 | 18-30 | |
| 43 | Power relay | Switching | 1 | 8-12 | |

**Stage 5 cost: ~180 — 285 PLN**

---

## Cost summary

| Stage | What you get | Min | Max | Cumulative |
|-------|--------------|-----|-----|------------|
| 1. Core | Dashboard + Audio + OBD + dual HDMI + WiFi/BT | 1 000 | 1 560 | 1 000 – 1 560 |
| 2. Cameras + sensors | 4-way cameras, parking, DS18B20, dashcam | 447 | 798 | 1 447 – 2 358 |
| 3. Input + LTE | SWC dual-pod, GPS, LTE modem | 260 | 420 | 1 707 – 2 778 |
| 4. Subwoofer + rain | | 63 | 102 | 1 770 – 2 880 |
| 5. Security + tracking | Alarm, central lock, battery backup | 180 | 285 | 1 950 – 3 165 |

### **Total: ~1 950 — 3 165 PLN**

### Savings vs. the older OPi 5 Plus build

- SBC: 600-750 PLN (OPi 5 Plus) → **350-450 PLN** (OPi 5 Pro 4GB)
  **= 250-300 PLN saved**
- No separate WiFi / BT dongle needed (built in).
- Same dual-HDMI topology, same feature set.

---

## Where to buy (Poland)

| Retailer | Best for |
|----------|----------|
| Allegro | OPi boards, Arduino, used parts |
| Botland | Arduino, sensors, breakout boards |
| Kamami | ICs, resistors, transistors, PCBs |
| Nettigo | Custom kits, breakout modules |
| AliExpress | **4-camera set**, USB grabber, bulk sensors |
| Amazon.pl | USB-C hubs, displays, USB DAC |

---

## Not included in prices

- 4× car speakers — reuse existing or ~200-400 PLN
- 1× subwoofer driver — ~100-200 PLN
- 12V automotive wiring + connectors — ~50-100 PLN
- DIN bracket / 3D-printed mount — ~20-50 PLN
- SIM card with data plan (for LTE)
- Labour / installation time
