# BCM v8.5 — USB-C Hub & Second Screen Guide (Redmi Note 8 Pro)

## Overview

The Redmi Note 8 Pro has a single USB-C port. To connect all BCM peripherals,
you need a **powered USB-C OTG hub** with HDMI output for the second (4.3")
display. Ubuntu Touch does **not support wireless display** (Miracast/WiDi),
so the second screen **must be connected via cable** (USB-C to HDMI adapter
or hub with HDMI port).

---

## Recommended USB-C Hub Configuration

### Option A: All-in-One USB-C Hub (Recommended)

A single hub that provides USB ports + HDMI + power delivery:

```
Redmi Note 8 Pro (USB-C)
    │
    └── USB-C Hub (powered)
         ├── HDMI OUT ──────────→ 4.3" TFT Display (800×480)
         ├── USB-A Port 1 ──────→ Arduino Sensor Hub (serial 115200)
         ├── USB-A Port 2 ──────→ USB-UART CP2102 (K-Line OBD)
         ├── USB-A Port 3 ──────→ ES9038Q2M USB DAC (audio)
         ├── USB-A Port 4 ──────→ USB AHD Grabber (cameras)
         ├── USB-A Port 5 ──────→ Arduino Central Lock (serial 9600)
         ├── USB-A Port 6 ──────→ USB BT adapter (or use built-in)
         ├── USB-A Port 7 ──────→ USB Microphone (Vosk voice)
         └── USB-C PD IN ───────→ 5V/3A Power Supply (from LM2596)
```

**Recommended hubs:**

| Hub Model | Ports | HDMI | PD | Price (PLN) |
|-----------|-------|------|----|-------------|
| Baseus 8-in-1 USB-C Hub | 3×USB3 + 1×USB2 | 4K@30Hz | 100W PD | 120-180 |
| UGREEN 7-in-1 USB-C | 3×USB3 | 4K@30Hz | 100W PD | 100-150 |
| MOKiN 9-in-1 USB-C | 2×USB3 + 2×USB2 | 4K@60Hz | 100W PD | 90-130 |
| Generic 7-port USB-C Hub | 4×USB3 | 1080p | 60W PD | 60-100 |

> **Important:** The hub MUST support **USB OTG mode** (host mode) and provide
> external power to avoid draining the phone battery. PD (Power Delivery) input
> on the hub keeps the phone charged while in use.

### Option B: USB-C Hub + Separate HDMI Adapter

If your hub doesn't have HDMI, use a separate USB-C to HDMI adapter:

```
Redmi Note 8 Pro (USB-C)
    │
    └── USB-C Splitter/Dock
         ├── USB-C ──→ USB-C to HDMI Adapter ──→ 4.3" Display
         └── USB-C ──→ Powered USB-A Hub (7+ ports)
                        ├── Port 1: Sensor Hub Arduino
                        ├── Port 2: USB-UART (K-Line)
                        ├── Port 3: USB DAC
                        ├── Port 4: AHD Grabber
                        ├── Port 5: Central Lock Arduino
                        ├── Port 6: Microphone
                        └── Port 7: (spare)
```

### Option C: Minimum Desk Testing Setup

For Phase 1-2 desk testing, you only need:

```
Redmi Note 8 Pro (USB-C)
    │
    └── Simple USB-C OTG Adapter (USB-C to USB-A female)
         └── (optional) USB-UART for OBD testing
```

Cost: 15-30 PLN for a basic OTG adapter.

---

## Second Screen (4.3" Dashboard Display)

### Why Cable Only?

Ubuntu Touch on Redmi Note 8 Pro **does not support**:
- Miracast / Wi-Fi Display
- Chromecast protocol
- Any wireless screen mirroring

The only option is a **wired HDMI connection** through the USB-C hub.

### Recommended 4.3" Displays

| Display | Resolution | Input | Touch | Price (PLN) |
|---------|-----------|-------|-------|-------------|
| Waveshare 4.3" HDMI LCD | 800×480 | HDMI mini | No | 180-250 |
| Elecrow 4.3" HDMI | 800×480 | HDMI | No | 150-200 |
| Generic 4.3" TFT HDMI | 800×480 | HDMI | No | 100-150 |

> The 4.3" display does NOT need touch — it's controlled by SWC and shows
> only the stats carousel + reverse camera overlay.

### HDMI Configuration

The USB-C hub's HDMI output acts as an extended display. On Ubuntu Touch,
configure it:

```bash
# Check connected displays
xrandr --listmonitors

# Set external display resolution
xrandr --output HDMI-1 --mode 800x480 --right-of DSI-1

# Or if using Wayland (default on UT):
# The display should auto-configure
```

### Launching BCM on Both Screens

```bash
# Start BCM (serves both displays via web)
./run_redmi.sh

# Main display (phone screen): open in Morph Browser
# URL: http://localhost:5002

# Second display (4.3" HDMI): open Chromium in kiosk mode
chromium-browser --kiosk --window-size=800,480 \
    --app=http://localhost:5003
```

**Auto-launch on second screen:**

```bash
# Add to BCM startup script or systemd service
# Wait for HDMI display to be detected, then launch browser
while ! xrandr | grep -q "HDMI.*connected"; do sleep 2; done
chromium-browser --kiosk --display=:0.1 \
    --window-size=800,480 \
    --app=http://localhost:5003 &
```

---

## USB Device Port Assignment

When multiple USB serial devices are connected, Linux assigns `/dev/ttyUSBx`
in detection order (which can vary). Use **udev rules** for consistent naming:

```bash
# Create udev rules for persistent device names
sudo cat > /etc/udev/rules.d/99-bcm-usb.rules << 'EOF'
# Arduino Sensor Hub (e.g., Arduino Nano with CH340)
SUBSYSTEM=="tty", ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="7523", \
    ATTRS{serial}=="SENSOR_HUB", SYMLINK+="bcm_sensor_hub"

# USB-UART K-Line adapter (CP2102)
SUBSYSTEM=="tty", ATTRS{idVendor}=="10c4", ATTRS{idProduct}=="ea60", \
    SYMLINK+="bcm_kline"

# Arduino Central Lock (Pro Mini with FTDI)
SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6001", \
    SYMLINK+="bcm_central_lock"
EOF

sudo udevadm control --reload-rules
sudo udevadm trigger
```

Then update `config/bcm_config_redmi.yaml`:
```yaml
serial:
  kline:
    port_redmi: /dev/bcm_kline
  sensor_hub:
    port: /dev/bcm_sensor_hub
central_lock:
  port: /dev/bcm_central_lock
```

---

## Power Supply

### In-Car Power Chain

```
Car Battery (12V)
    │
    ├── [25A fuse] ──→ TDA7388 amplifier (12V direct)
    │                  TDA2050 subwoofer amp (12V direct)
    │
    └── [5A fuse] ──→ LM2596 DC-DC (12V → 5.1V, 4A)
                       │
                       └── USB-C PD input on hub
                            │
                            ├── Phone charging (5V/2A)
                            └── USB devices power (5V total ~1.5A)
```

### Power Budget (5V rail)

| Device | Current (mA) |
|--------|-------------|
| Redmi Note 8 Pro (charging) | ~1500 |
| USB-C Hub overhead | ~100 |
| Arduino Sensor Hub | ~50 |
| USB-UART (CP2102) | ~30 |
| USB DAC (ES9038Q2M) | ~200 |
| AHD Grabber | ~500 |
| Arduino Central Lock | ~50 |
| USB Microphone | ~50 |
| **Total** | **~2480** |

> Use a **4A LM2596** or better — the phone's charging alone takes 1.5A.
> A powered USB-C hub with its own power input is essential.

### Power-On / Power-Off Sequence

```
Ignition ON  → 12V to LM2596 → Hub powers up → Phone wakes → BCM auto-starts
Ignition OFF → Sensor hub detects (optoisolator) → BCM shutdown sequence
             → 30s delay → Phone sleeps → LM2596 stays powered (standby)
```

---

## USB Bandwidth Considerations

USB-C on Redmi Note 8 Pro supports **USB 2.0** (480 Mbps). With all devices
connected through one hub, bandwidth allocation matters:

| Device | Bandwidth | Type |
|--------|-----------|------|
| AHD Grabber (720p) | ~50 Mbps | Isochronous |
| USB DAC (48kHz/16bit) | ~1.5 Mbps | Isochronous |
| Serial devices (3×) | ~0.3 Mbps | Bulk |
| USB Microphone | ~1.5 Mbps | Isochronous |
| **Total** | **~53 Mbps** | |

This is well within USB 2.0 limits (480 Mbps). However, isochronous
transfers (audio, video) get priority. If you experience USB glitches:

1. Use a hub with **TT (Transaction Translator)** — most modern hubs have this
2. Move the AHD grabber to a direct USB-C port if possible
3. Reduce camera resolution to 480p
4. Ensure the hub has its own power supply (not bus-powered)

---

## Wiring Diagram (Car Installation)

```
┌─────────────────────────────────────────────────────┐
│                  REDMI NOTE 8 PRO                   │
│               (mounted in DIN slot)                 │
│                                                     │
│  USB-C ──────→ USB-C Hub (behind dashboard)         │
│                 │                                   │
│  Built-in:      │   ┌─ HDMI ──→ 4.3" Display       │
│  - GPS          │   ├─ USB1 ──→ Sensor Hub Arduino  │
│  - LTE          │   ├─ USB2 ──→ CP2102 (K-Line)    │
│  - Bluetooth    │   ├─ USB3 ──→ USB DAC             │
│  - WiFi         │   ├─ USB4 ──→ AHD Grabber         │
│  - Mic          │   ├─ USB5 ──→ Central Lock Arduino│
│  - Screen       │   ├─ USB6 ──→ USB Mic (Vosk)     │
│  - Battery      │   └─ PD IN ←─ 5V/4A (LM2596)    │
└─────────────────────────────────────────────────────┘

                        Sensor Hub Arduino
                        ├── HC-SR04 ×4 (parking)
                        ├── Piezo buzzer
                        ├── DS18B20 (temperature)
                        ├── PC817 ×4 (ignition, door, rain, lock)
                        └── Relay (wiper)

                        Central Lock Arduino
                        ├── Relay module ×8
                        ├── RXB6 433MHz receiver
                        └── LED alarm
```

---

## Comparison: Cable Options for Second Screen

| Method | Works on UT? | Quality | Latency | Cost |
|--------|-------------|---------|---------|------|
| USB-C Hub with HDMI | YES | 800×480 native | <1ms | Included in hub |
| USB-C to HDMI adapter | YES | 800×480 native | <1ms | 40-80 PLN |
| Miracast / Wi-Fi Display | NO | N/A | N/A | N/A |
| Chromecast | NO | N/A | N/A | N/A |
| VNC / remote desktop | Possible but laggy | Low | 50-200ms | Free |
| Second phone via WiFi | YES (web viewer) | Good | 10-50ms | Free if you have one |

**Recommended:** USB-C hub with built-in HDMI port (Option A).

**Alternative:** If you have a spare phone/tablet, use it as the 4.3" display
by simply opening `http://<redmi-ip>:5003` in its browser. This requires no
cable and works well for the stats carousel. However, the reverse camera
feed may have 50-100ms additional latency over WiFi.
