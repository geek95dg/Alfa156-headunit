# Arduino Setup Guide — Beginner Walkthrough

This guide walks you through flashing the two Arduino boards used by the
BCM headunit on the x86 (Lenovo M910q) platform, from a completely fresh
start. **No prior Arduino experience required.**

You will end up with:

| Board | Role | Sketch | USB device |
|-------|------|--------|------------|
| **Arduino Pro Micro** (ATmega32U4) | Inputs — buttons, rotary encoder, SWC, light sensor, fuel sender | `arduino/rotary_encoder/rotary_encoder.ino` | `/dev/ttyACM0` (also USB HID keyboard) |
| **Arduino Nano** (ATmega328P, CH340) | Outputs — relays, lights, horn, wipers, **display backlight PWM** | `arduino/output_controller/output_controller.ino` | `/dev/ttyUSB0` |

Both plug into the powered USB hub described in `docs/X86_PLATFORM_SETUP.md`.

---

## 1. What you need

### Hardware
- 1 × Arduino Pro Micro (ATmega32U4, 5 V / 16 MHz). Genuine SparkFun or
  any of the very common clones. Avoid 3.3 V variants.
- 1 × Arduino Nano (ATmega328P) with a **CH340** USB-UART chip — the
  classic blue-PCB clone. The FTDI variant works too.
- 1 × Micro-USB cable (Pro Micro) and 1 × Mini-USB cable (most Nanos
  use mini-USB; some clones use micro). Both must be **data cables**
  — charge-only cables look identical and will not enumerate.
- Your computer for flashing (the same M910q is fine, or any laptop).

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
| **RCSwitch** by sui77 | Nano *(optional)* | Only needed if you set `ENABLE_RF = 1` for 433 MHz keyfobs |

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

Try the lock relay (it will pulse for 200 ms — even with no relay
wired you'll see the D13 LED flash and the receive activity):

```
{"cmd":"lock"}
```

Reply:

```
{"event":"locked"}
```

Try the 7" display backlight (PWM 50 %). With nothing wired you can't
see anything change, but no error means the firmware accepted it:

```
{"cmd":"backlight","display":"large","brightness":50}
```

---

## 7. Wiring quick-reference — Arduino Nano

When you're ready to connect actual hardware, here are the pins. Wire
relay/input pins only as you build out each subsystem; you don't need
them all at once.

| Pin | Function | Wire to |
|-----|----------|---------|
| D2  | Lock relay (pulse 200 ms)              | Relay module IN1 |
| D3  | Unlock relay (pulse 200 ms)            | Relay module IN2 |
| D4  | Trunk release relay                    | Relay module IN3 |
| D5  | Window UP relay (hold)                 | Relay module IN4 |
| D6  | Window DOWN relay (hold)               | Relay module IN5 |
| D7  | Headlights relay                       | Relay module IN6 |
| D8  | Left blinker relay (toggle)            | Relay module IN7 |
| **D9**  | **7" display backlight PWM**       | **Display "PWM" pad** |
| **D10** | **4.3" display backlight PWM**     | **Display PWM pin (M_PWM)** |
| D11 | Horn relay (hold)                      | Relay module IN8 |
| D12 | RF receiver data (optional)            | RXB6 DATA pin |
| D13 | Status LED (on-board, no wiring)       | — |
| A0  | Right blinker relay (toggle)           | Relay module IN9 |
| A1  | Wipers relay (pulse, duration)         | Relay module IN10 |
| 5V  | Logic supply                           | Relay module VCC, RXB6 VCC |
| GND | Ground (common!)                       | Relay module GND, **display GND pad**, RXB6 GND |

> **Important — common ground:** the display's `GND` pad **must** be
> tied to the Nano's GND, otherwise the M_PWM gate has no reference
> and the backlight won't respond. Run a single wire from any Nano GND
> pin to the display GND pad.

> **5 V logic on the display PWM input:** the 7" Waveshare-style
> Display-D board has an N-MOSFET on `M_PWM`. The Nano outputs 0–5 V
> logic on D9/D10, which is well above the MOSFET's gate threshold.
> No level shifter needed.

---

## 8. Plugging both Arduinos into the M910q

Once both sketches are flashed and verified:

1. Plug both Arduinos into the **powered USB hub** (not directly into
   the M910q if you can avoid it — the hub provides clean 5 V and
   makes the wiring tidier under the dash).
2. Confirm they enumerate:

   ```bash
   ls -l /dev/ttyACM* /dev/ttyUSB*
   # /dev/ttyACM0 → Pro Micro
   # /dev/ttyUSB0 → Nano
   ```

3. Confirm permissions (you should be in `dialout`):

   ```bash
   groups | grep dialout
   ```

4. The BCM Python code auto-detects both ports on startup
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

- Wire the display PWM pads to **Nano D9 (large 7") and D10 (small 4.3")**
  plus a common GND, then verify in Serial Monitor with
  `{"cmd":"backlight","display":"large","brightness":20}` and watch the
  screen dim.
- Add a Python-side consumer in the BCM (forwarding
  `power.backlight_brightness` events to the Nano serial port). This
  is the last piece needed to wire the existing
  `src/power/brightness.py` controller — the auto-brightness, stalk
  button cycle, and Settings screen will all then drive the real
  hardware. *(Ask Claude to write this — it's a ~40-line module.)*
- Build out the relay outputs (lock, lights, etc.) one at a time as
  you have hardware on the bench.

You now have a working, debuggable two-Arduino bridge between the
M910q and the car. Have fun.
