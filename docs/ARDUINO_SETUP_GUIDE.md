# Arduino Setup Guide — Beginner Walkthrough

This guide walks you through flashing the two Arduino boards used by the
BCM headunit on the x86 (Lenovo M910q) platform, from a completely fresh
start. **No prior Arduino experience required.**

> **Absolute beginner — never plugged an Arduino in at all?** Read
> [`ARDUINO_OD_ZERA.md`](ARDUINO_OD_ZERA.md) (PL) first. It covers the
> layer below this guide: which cable, the CH340 driver, installing the
> IDE, finding the serial port, a Blink smoke test, and a minimal
> first-upload config for `sensor_hub` that needs no external libraries.
> Come back here for the full pin tables and SWC calibration.

You will end up with:

| Board | Role | Sketch | USB device |
|-------|------|--------|------------|
| **Arduino Pro Micro** (ATmega32U4) — *Domain B* | Inputs — buttons, rotary encoder, SWC, light sensor, fuel sender | `arduino/rotary_encoder/rotary_encoder.ino` | `/dev/ttyACM0` (also USB HID keyboard) |
| **Arduino Nano** (ATmega328P, CH340) — *Domain A (always-on)* | 4-window remote, BLE-gated trunk button, **display backlight PWM** | `arduino/output_controller/output_controller.ino` | `/dev/ttyUSB0` |
| **Arduino Nano #2** (ATmega328P, CH340) — *Domain B* | **Vehicle sensor hub** — doors/bonnet/trunk, handbrake, ignition, rain, DS18B20 temp, (opt.) parking, cruise/immo/airbag | `arduino/sensor_hub/sensor_hub.ino` | `/dev/ttyUSB1` |

> **Build from the command line (recommended, repeatable):** every sketch
> has a pinned `sketch.yaml` profile — `make -C arduino` compiles all
> three, `make -C arduino sensor_hub-upload PORT=/dev/ttyUSB1` flashes
> one. Requires `arduino-cli` (install: see `arduino/Makefile` header).
>
> **Firmware changes v8.5.2:**
> - All three sketches run a **2 s hardware watchdog** — a hang
>   self-resets the board instead of requiring a power pull.
> - **Pro Micro wiring change:** encoder push button moved **D4 → D1**
>   (on the Pro Micro D4 and A6 are the same physical pin, so the old
>   wiring conflicted with SWC Pod 2). If you wired before v8.5.2,
>   move that one wire.
> - The always-on Nano's BLE scan is now **non-blocking** — the window
>   remote and the auto-release safety cutoff keep working during the
>   2.5 s trunk-tag scan.
> - **New sensor hub sketch** feeds `src/input/arduino_serial.py` the
>   `DOOR:/HBRAKE:/IGN:/RAIN:/TEMP:/PARK:` telemetry that was documented
>   but never actually transmitted by any firmware. Each input group is
>   a `#define FEATURE_*` toggle at the top of the sketch — comment out
>   what you don't wire.

The Pro Micro plugs into the powered USB hub on **Domain B** (powered with
the M910q; off when the BCM sleeps). The Nano runs on **Domain A** — its
5 V supply comes from the 12 V battery buffer (4-6 × SLA 5 Ah in parallel)
via a small buck converter, so it stays alive while the car is parked
and the BCM is asleep. See `docs/X86_PLATFORM_SETUP.md` § Power
Architecture for the wiring diagram.

> **What the always-on Nano does even while the BCM sleeps:**
> - Watches the 2nd 433 MHz keyfob → drives 4 window relays hold-to-move
> - Watches the trunk button → if the HM-10 BLE module sees a known tag
>   within range, pulses the trunk relay
>
> **What it does only while the BCM is up:**
> - Receives `backlight` PWM commands over USB serial to dim the screens

---

## 1. What you need

### Hardware

**Microcontrollers and cables:**
- 1 × Arduino Pro Micro (ATmega32U4, 5 V / 16 MHz). Genuine SparkFun or
  any of the very common clones. Avoid 3.3 V variants.
- 1 × Arduino Nano (ATmega328P) with a **CH340** USB-UART chip — the
  classic blue-PCB clone. The FTDI variant works too.
- 1 × Micro-USB cable (Pro Micro) and 1 × Mini-USB cable (most Nanos
  use mini-USB; some clones use micro). Both must be **data cables**
  — charge-only cables look identical and will not enumerate.
- Your computer for flashing (the same M910q is fine, or any laptop).

**For the always-on Nano subsystem (Domain A):**
- 1 × **HM-10 BLE module** (CC2540/CC2541 based, the green PCB with a
  small chip antenna). ~5 EUR. *Not* an HC-05 — that's Bluetooth Classic
  and won't work as a scanner.
- 1 × **RXB6 (or equivalent) 433 MHz superheterodyne receiver**. ~3 EUR.
  Avoid the cheap blue-board "MX-RM-5V" receivers — they have poor
  selectivity and you'll get phantom triggers from neighbour's gates.
- 1 × **Secondary 4-button 433 MHz keyfob remote** (EV1527 or PT2262
  fixed-code type). The repository's RCSwitch library decodes both.
  Get one with 4 distinct buttons — you'll assign them: front pair
  down, front pair up, rear pair down, rear pair up. ~3 EUR.
- 1 × **BLE tag** for proximity detection. Options:
  - An **iTag** / **Tile** / similar BLE beacon (~3 EUR). Advertises
    its MAC continuously; HM-10 picks it up at ~5-10 m.
  - Your **smartphone** running a BLE-advertise app (e.g. nRF
    Connect on Android, "Advertise" mode). Zero extra cost but you
    need to keep the app running.
- 1 × **Momentary push-button** for the new trunk-release button
  (panel-mount, NO contacts). 12 mm IP67-rated chrome ones look factory
  on a dash trim panel. ~3 EUR.
- 1 × **10-channel 5 V opto-isolated relay module** (active-LOW). The
  always-on Nano uses 9 channels: 4 windows × 2 directions + 1 trunk.
- 4-6 × **12 V 5 Ah SLA (sealed lead-acid) batteries** for the buffer
  (you own 8; using 4-6 puts the always-on bus at 20-30 Ah, good for
  ~14-21 days parked-car standby).
- 1 × **Buck converter 12 V → 5 V** (LM2596 or similar, 1 A minimum)
  to feed the Nano's Vin from the battery bus.
- 1 × **LVD (low-voltage disconnect)** module set to 11.0 V to protect
  the SLA bank from deep discharge.

### Software
- **Arduino IDE 2.x** — the modern editor with built-in board/library
  manager. Download from <https://www.arduino.cc/en/software>.
- **CH340 driver** — only needed on Windows / macOS. On Linux the
  driver (`ch341`) ships with the kernel; nothing to install.

### Tools (only the IDE — no soldering iron needed yet for the flashing step)
- Arduino IDE
- Serial Monitor (built into the IDE, accessed by the magnifying-glass icon)
- A USB port on your computer (any one — you can flash both boards
  one after the other from a single port)

---

## 2. Install the Arduino IDE

### Linux (Debian / Ubuntu — the M910q itself)

```bash
# Easiest: use the AppImage from arduino.cc
cd ~/Downloads
wget https://downloads.arduino.cc/arduino-ide/arduino-ide_latest_Linux_64bit.AppImage
chmod +x arduino-ide_latest_Linux_64bit.AppImage
./arduino-ide_latest_Linux_64bit.AppImage
```

You also need to be in the `dialout` group so the IDE can open the serial
ports without `sudo`:

```bash
sudo usermod -aG dialout $USER
```

Then **log out and back in** (or reboot). This step is the single most
common cause of "permission denied /dev/ttyACM0" errors later.

### Windows

1. Download the Windows installer from <https://www.arduino.cc/en/software>.
2. Run it, accept the defaults (it will offer to install USB drivers — say yes).
3. Separately install the CH340 driver:
   <https://www.wch-ic.com/downloads/CH341SER_EXE.html> — run, reboot if asked.

### macOS

1. Download the .dmg from <https://www.arduino.cc/en/software>.
2. Drag Arduino IDE into Applications.
3. CH340 driver: <https://github.com/adrianmihalko/ch340g-ch34g-ch34x-mac-os-x-driver>
   — follow the README for your macOS version.

---

## 3. First launch — open the project sketches

1. Start the Arduino IDE.
2. **File → Open…** and navigate to the cloned repo:
   - For the Pro Micro: `arduino/rotary_encoder/rotary_encoder.ino`
   - For the Nano:      `arduino/output_controller/output_controller.ino`

   You can have both open at once — the IDE will create a window per
   sketch.

> **Tip:** Arduino requires every sketch file to live inside a folder
> with the **same name** as the `.ino`. The repo already follows this —
> just don't rename the folders.

---

## 4. Install the required libraries

Open **Tools → Manage Libraries…** (or `Ctrl+Shift+I`). In the search
box, install each of these one at a time — click the entry, then
**Install** (use the latest version unless noted):

| Library | Used by | Notes |
|---------|---------|-------|
| **HID-Project** by NicoHood | Pro Micro | Provides `Consumer.write(MEDIA_*)` — media-key HID support |
| **ArduinoJson** by Benoit Blanchon | Nano | **Version 7.x** (the sketch uses the v7 `JsonDocument` API) |
| **RCSwitch** by sui77 | Nano | Required for the 433 MHz window-remote decoder |
| **SoftwareSerial** | Nano | Bundled with the IDE — no install needed. Used for the HM-10 BLE module on D3/D4. |

The IDE downloads and installs them into `~/Arduino/libraries/`.

---

## 5. Flash the Pro Micro (input controller)

### 5.1 Select the board

In Arduino IDE, with the **Pro Micro sketch window active**:

1. **Tools → Board → Arduino AVR Boards → Arduino Leonardo**
   - The Pro Micro is not in the default list. It uses the same chip
     (ATmega32U4) as the Leonardo, so the Leonardo profile flashes it
     correctly. If you want the proper name, install the SparkFun
     boards package: Tools → Boards Manager → search "SparkFun AVR" →
     install → then select **SparkFun Pro Micro (5 V, 16 MHz)**.

### 5.2 Plug in the Pro Micro and select the port

1. Connect the Pro Micro via USB. The on-board LED should light up.
2. **Tools → Port** — pick the new port:
   - Linux: `/dev/ttyACM0` (or `ttyACM1`)
   - Windows: `COM3`, `COM4`, …
   - macOS: `/dev/cu.usbmodem*`

If you don't see any port, the cable is charge-only — swap it.

### 5.3 Compile and upload

1. Click the **checkmark** (Verify) in the toolbar. It compiles the
   sketch. The first compile takes ~30 s; subsequent ones are fast.
   Expect a clean "Done compiling" message — warnings about unused
   variables are harmless.
2. Click the **arrow** (Upload). The IDE compiles again, then flashes.

> **Pro Micro tip — the "double-tap reset" trick.** If upload fails with
> `avrdude: butterfly_recv(): programmer is not responding`, the
> bootloader window timed out. Click Upload, then quickly tap the RST
> pad on the Pro Micro to GND **twice in <750 ms** — the IDE will then
> find the bootloader. Some clones expose RST on a labelled pad you can
> short with a wire; on others you bridge RST↔GND with tweezers.

After upload the Pro Micro re-enumerates as both a USB keyboard
**and** a serial port — that's normal. Don't be alarmed if your mouse
suddenly types `H` once — that's a stray HID event during reset.

### 5.4 Verify it's alive

Open **Tools → Serial Monitor**. Set baud to **115200** (bottom-right
dropdown). You should see:

```
BCM v7 Input Controller ready (encoder + buttons + SWC + music + brightness)
LIGHT:512
LIGHT:513
…
```

The `LIGHT:` line repeats every 2 s — that's the LDR sensor (or a
floating value if you haven't wired one yet).

### 5.5 Optional — SWC calibration

The Pro Micro stores SWC button thresholds in EEPROM. If you have the
steering-wheel control pods wired, calibrate them once:

1. **Unplug** the Pro Micro.
2. Press and **hold HOME + BACK** buttons.
3. Plug the USB back in (keep holding).
4. Open Serial Monitor at 115200.
5. Release the buttons and follow the on-screen prompt — it asks for
   each of the 24 buttons (Pod 1 × 12, Pod 2 × 12). Press one,
   release, wait for "→ ADC = …".
6. Done — values are saved to EEPROM and survive power cycles.

You can skip this step now and do it later — the sketch falls back to
sane defaults.

---

## 6. Flash the Nano (output controller)

### 6.1 Select the board

With the **Nano sketch window active**:

1. **Tools → Board → Arduino AVR Boards → Arduino Nano**
2. **Tools → Processor → ATmega328P** *(try this first)*
   - If upload fails later with `stk500_recv(): programmer is not
     responding`, change to **ATmega328P (Old Bootloader)** and retry.
     About half of the cheap clones use the old bootloader.

### 6.2 Plug in the Nano and select the port

1. Connect via USB. The on-board red power LED lights up.
2. **Tools → Port** — pick the new port:
   - Linux: `/dev/ttyUSB0` (CH340 → `ch341` driver)
   - Windows: `COM*` (whatever appears)
   - macOS: `/dev/cu.wchusbserial*`

If no port appears on Linux, run `dmesg | tail` after plugging in —
you should see `ch341-uart converter now attached to ttyUSB0`. If not,
your cable is charge-only.

### 6.3 Compile and upload

Click **Verify** (checkmark), then **Upload** (arrow). The on-board RX
and TX LEDs flicker during flashing. On success the IDE prints
`avrdude done. Thank you.`.

### 6.4 Verify it's alive

Open **Tools → Serial Monitor** — **change baud to 9600** (different
from the Pro Micro). You should see immediately after reset:

```
{"event":"ready","fw":"bcm-output-v8.5"}
```

And the on-board LED (D13) starts blinking once per second — that's
the heartbeat.

Now type a test command into the Serial Monitor input box. Make sure
the line-ending dropdown is set to **Newline**, then send:

```
{"cmd":"ping"}
```

Reply:

```
{"event":"pong"}
```

Try the 7" display backlight (PWM 50 %). With nothing wired you can't
see anything change, but no error means the firmware accepted it:

```
{"cmd":"backlight","display":"large","brightness":50}
```

Ask the Nano for its current state:

```
{"cmd":"status"}
```

Reply (something like):

```
{"event":"status","active_slot":"none","ble_mac_set":false,"ble_rssi_threshold":-80,"codes":[0,0,0,0,0,0,0,0]}
```

A fresh sketch has no learned RF codes (all zeros) and no BLE MAC set
yet. The next two sub-sections walk you through learning both.

### 6.5 Learn the window remote (one-time)

The Nano stores 8 RF codes in EEPROM, one per window direction. Pair
each button of your 4-button 433 MHz keyfob to a (window, direction)
slot. The natural mapping for a 4-button remote is:

| Remote button | Slot you assign it to | Effect |
|---------------|----------------------|--------|
| Button 1 | `FL_DOWN` (then loop into `FR_DOWN` via JSON) | Lower front windows |
| Button 2 | `FL_UP`   (then `FR_UP`)   | Raise front windows |
| Button 3 | `RL_DOWN` (then `RR_DOWN`) | Lower rear windows |
| Button 4 | `RL_UP`   (then `RR_UP`)   | Raise rear windows |

If your remote sends the same code on press-and-hold (most do), the
Nano keeps the relay engaged for as long as the code keeps arriving
and releases ~250 ms after you let go. A hard safety cutoff at 8 s
prevents the relay sticking on and burning out the window motor.

Procedure (run in Serial Monitor with Newline line-ending):

1. Send `{"cmd":"learn_window","slot":"FL_DOWN"}` → expect
   `{"event":"learn_window_armed","slot":"FL_DOWN"}`.
2. Press Button 1 on the remote briefly. The Nano captures the code
   and replies `{"event":"learned","slot":"FL_DOWN","code":1234567}`.
3. Repeat for the other 7 slots. To pair Button 1 to both `FL_DOWN`
   and `FR_DOWN` (so it drops both front windows together), arm
   `FR_DOWN` and press the *same* Button 1 — the code is recorded
   into the second slot too.
4. Verify with `{"cmd":"status"}` — all 8 entries in the `codes` array
   should be non-zero.

After learning, just press buttons on the remote (no Serial Monitor
needed) and the Nano emits `{"event":"window","slot":"…"}` while you
hold, and `{"event":"window_release",…}` when you let go.

### 6.6 Pair the BLE tag (one-time)

The HM-10 must be wired up first — see § 7 for the wiring table.

The simplest path is **learn-by-scan**: with the BLE tag close to the
HM-10 antenna (within 30 cm), send:

```
{"cmd":"learn_ble"}
```

The Nano triggers a 5 s discovery scan and picks the device with the
strongest RSSI. Reply (example):

```
{"event":"ble_learned","mac":"AA1122334455","rssi":-42}
```

If you have multiple BLE devices nearby, the strongest-RSSI heuristic
might pick the wrong one. Set the MAC explicitly instead:

```
{"cmd":"set_ble_mac","mac":"AA1122334455"}
```

Tune the proximity threshold (lower number = farther away):

```
{"cmd":"set_ble_rssi","threshold":-75}
```

Defaults to -80 dBm (≈ 5 m line-of-sight with an iTag).

Test: press the trunk button.

- Tag in pocket nearby → `{"event":"trunk","rssi":-52}` + 200 ms relay pulse.
- Tag in another room → `{"event":"trunk_denied","reason":"weak","rssi":-95}`.
- Tag not advertising / out of range → `{"event":"trunk_denied","reason":"no_key"}`.

### 6.7 Optional — wipe EEPROM and start over

```
{"cmd":"clear"}
```

Replies `{"event":"cleared"}` — all 8 window codes and the BLE MAC are
forgotten and you can re-learn from scratch.

---

## 7. Wiring quick-reference — Arduino Nano (always-on Domain A)

Wire as you build out each subsystem; you don't need everything at once.
Starting from a bare Nano, the minimum to drive the displays is just
GND + D9/D10 to the panels' PWM pads. The window remote and trunk-BLE
features layer on top.

| Pin | Function | Wire to |
|-----|----------|---------|
| **D2**  | **433 MHz RXB6 data input**          | **RXB6 DATA pin** |
| **D3**  | **HM-10 RXD** (Nano TX → HM-10)       | **HM-10 RXD** |
| **D4**  | **HM-10 TXD** (HM-10 → Nano RX)       | **HM-10 TXD** |
| D5  | Trunk relay (200 ms pulse)             | Relay module IN1 |
| D6  | Trunk button input (pull-up)           | **NO momentary switch → GND** |
| D7  | Front-Left  UP   relay (hold)          | Relay module IN2 |
| D8  | Front-Left  DOWN relay (hold)          | Relay module IN3 |
| **D9**  | **main 10.1" display backlight PWM**  | **Display "PWM" pad** |
| **D10** | **second 6.86" display backlight PWM** | **Display PWM pad (M_PWM)** |
| D11 | Front-Right UP   relay (hold)          | Relay module IN4 |
| D12 | Front-Right DOWN relay (hold)          | Relay module IN5 |
| D13 | Status LED (on-board, no wiring)       | — |
| A0  | Rear-Left   UP   relay (hold)          | Relay module IN6 |
| A1  | Rear-Left   DOWN relay (hold)          | Relay module IN7 |
| A2  | Rear-Right  UP   relay (hold)          | Relay module IN8 |
| A3  | Rear-Right  DOWN relay (hold)          | Relay module IN9 |
| A4  | reserved (I2C SDA, future expansion)   | — |
| A5  | reserved (I2C SCL, future expansion)   | — |
| 5V  | Logic supply                           | Relay module VCC, RXB6 VCC, HM-10 VCC |
| GND | Ground (common!)                       | Relay module GND, **display GND pads**, RXB6 GND, HM-10 GND, trunk button COM |
| Vin (7-12V) | Battery-bus input via buck      | 5 V from LM2596 (set output to 5.0 V; do NOT feed >5 V here unless you remove the buck and use the raw Vin regulator) |

> **Common ground is mandatory:** every module — the displays, the
> relay board, RXB6, HM-10, the trunk button — shares a single ground
> with the Nano. Without it the M_PWM gate has no reference and the
> RXB6/HM-10 see noise.

> **HM-10 wiring gotcha:** the HM-10's RXD pin is *the input you
> drive*. So Nano D3 (`PIN_BLE_TO`) goes to HM-10 **RXD**, and HM-10
> **TXD** comes back to Nano D4 (`PIN_BLE_FROM`). The labels look
> reversed at first glance — they are correct.

> **Display PWM input** on the 7" Waveshare "Display-D" board: the on-
> board N-MOSFET on M_PWM accepts 0-5 V logic-level PWM directly, no
> level shifter needed.

> **Important — common ground:** the display's `GND` pad **must** be
> tied to the Nano's GND, otherwise the M_PWM gate has no reference
> and the backlight won't respond. Run a single wire from any Nano GND
> pin to the display GND pad.

> **5 V logic on the display PWM input:** the 7" Waveshare-style
> Display-D board has an N-MOSFET on `M_PWM`. The Nano outputs 0–5 V
> logic on D9/D10, which is well above the MOSFET's gate threshold.
> No level shifter needed.

---

## 7b. Wiring quick-reference — Arduino Nano #2 (vehicle sensor hub)

All switch inputs use the internal pull-ups — wire each switch between
the pin and **chassis GND** (active LOW). The 12 V ignition signal MUST
go through a PC817 optocoupler, never directly to a pin.

| Pin | Signal | Notes |
|-----|--------|-------|
| D2-D5 | Door switches FL/FR/RL/RR | OEM door plunger switches ground when open |
| D6 | Bonnet switch | |
| D7 | Trunk switch | |
| D8 | Handbrake switch | LOW = engaged |
| D9 | Ignition (via **PC817**) | 12 V ACC → 4.7 kΩ → PC817 LED; collector → D9 |
| D10 | Rain sensor module DO | comparator digital output, LOW = rain |
| D11 | DS18B20 data | 4.7 kΩ pull-up to 5 V |
| D12 | HC-SR04 TRIG (shared ×4) | only with `FEATURE_PARK` |
| A0-A3 | HC-SR04 ECHO FL/FR/RL/RR | **1 kΩ/2 kΩ divider from 5 V!** |
| A4/A5 | Cruise / Immo (optional) | `FEATURE_CRUISE` / `FEATURE_IMMO` |
| D13 | Airbag OK (optional) | shares the on-board LED — prefer leaving off |

Every input group is compiled in/out with a `#define FEATURE_*` switch at
the top of `sensor_hub.ino` — disable what you don't wire and the pins are
freed. `FEATURE_PARK` is **off by default** (parking sensors are normally
handled by the parking module; enable only if the HC-SR04s hang off this
Nano instead).

Verify it talks (115200 baud):

```bash
picocom -b 115200 /dev/ttyUSB1
# expect lines like:
#   DOOR:FL=0,FR=0,RL=0,RR=0,BONNET=0,TRUNK=0
#   HBRAKE:1
#   IGN:0
#   TEMP:21.4
```

`src/input/arduino_serial.py` auto-detects the port and publishes these
as `vehicle.*` events on the BCM bus (doors → alarm, rain → wipers, etc.).

## 8. Powering the boards in the car

Once both sketches are flashed and verified, the in-car wiring splits
into two power domains. See `docs/X86_PLATFORM_SETUP.md` § Power
Architecture for the full picture; in short:

**Domain B — Pro Micro + M910q (ignition-controlled)**

The Pro Micro plugs into the **powered USB hub** that sits on the
M910q. Domain B comes up when the M910q powers on (either ignition
ON, or the RTC alarm wakes it for a tracking ping). When the M910q
sleeps, the hub usually drops too — the Pro Micro is off, which is
fine because none of its features are needed while parked.

**Domain A — Nano + HM-10 + RXB6 + relays (always-on, battery-backed)**

The Nano runs continuously from the 12 V battery buffer (4-6 × 5 Ah
SLA in parallel), via a 12 V → 5 V buck converter feeding the Nano's
Vin pin. Its USB cable still goes to the M910q's hub so the BCM can
send `backlight` commands when it's awake — but the Nano keeps
running even with USB disconnected, because Vin is supplied
independently.

> **Important — don't power the Nano from two sources at once.**
> The Nano has a diode-OR between USB-5V and the Vin regulator's 5V,
> but the diode drop is fine only if Vin is > 7 V. If you wire Vin
> directly to 5 V from the buck (bypassing the on-board regulator),
> you must remove or de-solder the buck output when the Nano is on
> USB-power on the bench. The cleanest setup is: buck output = 5 V,
> wired to the Nano's **5V** pin (not Vin), and let USB-5V coexist
> via the on-board protection diode.

Confirm both boards enumerate when the M910q is on:

```bash
ls -l /dev/ttyACM* /dev/ttyUSB*
# /dev/ttyACM0 → Pro Micro
# /dev/ttyUSB0 → Nano
```

Confirm permissions (you should be in `dialout`):

```bash
groups | grep dialout
```

The BCM Python code auto-detects both ports on startup
(`src/input/arduino_serial.py` and `src/vehicle/central_lock.py`).
Check `journalctl -u bcm-headunit | grep -i arduino` after boot.

---

## 9. Common errors and fixes

| Symptom | Cause / fix |
|---------|-------------|
| Upload fails: `avrdude: ser_open(): can't open device '/dev/ttyACM0': Permission denied` | You aren't in the `dialout` group, or you haven't logged out/in since adding yourself. Run `sudo usermod -aG dialout $USER`, then **reboot**. |
| Upload fails: `avrdude: stk500_recv(): programmer is not responding` (Nano) | Wrong bootloader. **Tools → Processor → ATmega328P (Old Bootloader)** and retry. |
| Upload fails: `avrdude: butterfly_recv(): programmer is not responding` (Pro Micro) | Bootloader window closed. Click Upload, then double-tap RST→GND on the Pro Micro within 750 ms. |
| Serial Monitor shows garbage characters | Wrong baud rate. Pro Micro = **115200**, Nano = **9600**. |
| `Library ArduinoJson not found` at compile time | Open Library Manager and install the ArduinoJson package (v7.x). |
| `JsonDocument has no member named …` at compile time | You installed ArduinoJson **v6** instead of **v7**. Uninstall and install the latest. |
| Nano not detected on Linux (no `/dev/ttyUSB0`) | Cable is charge-only; or the CH340 didn't enumerate. Run `dmesg \| tail` after plugging in. |
| Nano not detected on Windows | Install the CH340 driver from WCH (link in §2). |
| 7" display brightness doesn't change when you send `backlight` commands | Check the GND wire between Nano and display PWM pad. Check D9 is going to the display PWM pad (multimeter, ~2.5 V at 50 % duty). |
| Pro Micro acts as a keyboard and types stuff into your editor | Normal during reset — it's a feature, not a bug. Switch focus to Serial Monitor while testing. |

---

## 10. What to do next

Once both Arduinos are flashed and verified:

- Wire the display PWM pads to **Nano D9 (main 10.1") and D10 (second 6.86")**
  plus a common GND, then verify in Serial Monitor with
  `{"cmd":"backlight","display":"large","brightness":20}` and watch the
  screen dim.
- Wire the RXB6 receiver to D2 + 5V + GND and learn the four window
  keyfob buttons (§ 6.5). With nothing else wired you'll see
  `{"event":"window","slot":…}` lines in Serial Monitor — confirms
  the RF decode works before you wire any motor relays.
- Wire the HM-10 to D3/D4 + 5V + GND and pair your BLE tag (§ 6.6).
  Once paired, the trunk button + tag combination will fire the
  trunk relay.
- Build out the 9 relay outputs (4 window pairs + trunk) on the
  10-channel relay module. Test each relay channel with the keyfob
  before connecting it to the car wiring.
- Add a Python-side consumer in the BCM (forwarding
  `power.backlight_brightness` events to the Nano serial port). This
  is the last piece needed to wire the existing
  `src/power/brightness.py` controller — the auto-brightness, stalk
  button cycle, and Settings screen will all then drive the real
  hardware. *(Ask Claude to write this — it's a ~40-line module.)*

> **Note — features not on this Nano.** The earlier project docs
> mentioned the same Arduino driving headlights, horn, wipers, and
> blinkers as part of a "replace the OEM body computer" concept. That
> idea has been dropped — the original Alfa 156 systems stay
> untouched. If you ever want those outputs back, run a *second*
> Nano on Domain B with a slimmer sketch; the pin budget on this
> always-on Nano is fully committed to the new windows + trunk + BLE
> scope.

You now have a working, debuggable two-Arduino bridge between the
M910q and the car, with always-on window + trunk remote control.
Have fun.
