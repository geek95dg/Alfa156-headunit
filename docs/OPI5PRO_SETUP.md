# Orange Pi 5 Pro 4GB — Setup & Wiring Guide

Primary production build of the Alfa 156 BCM head unit on the
**Orange Pi 5 Pro 4GB** (RK3588S, HDMI 2.1 + HDMI 2.0, WiFi 6, BT 5.0).
This is the intended final in-car platform.

See also:
- [`OPI5PRO_BOM.md`](OPI5PRO_BOM.md) — parts list and prices
- [`OPI_PC_SETUP.md`](OPI_PC_SETUP.md) — bench test rig (pre-production)

---

## 1. Flash Armbian

1. Download the latest Armbian Bookworm CLI image for Orange Pi 5 Pro
   from armbian.com.
2. Flash to a microSD card or NVMe:
   ```bash
   sudo dd if=Armbian_*_Orangepi5pro_*.img of=/dev/sdX bs=1M status=progress
   sync
   ```
3. Insert the card / NVMe, connect HDMI, keyboard, and Ethernet. Power on.

First-boot checklist:
```bash
# Default: root / 1234 → create your user.
sudo hostnamectl set-hostname bcm
sudo timedatectl set-timezone Europe/Warsaw
sudo apt update && sudo apt upgrade -y
```

## 2. System packages

```bash
sudo apt install -y \
  python3 python3-pip python3-venv python3-dev \
  git chromium \
  libgpiod-dev gpiod python3-libgpiod \
  pipewire pipewire-alsa wireplumber \
  bluez blueman \
  v4l-utils ffmpeg \
  gstreamer1.0-tools gstreamer1.0-plugins-good \
  gstreamer1.0-plugins-bad gstreamer1.0-rockchip1 \
  xdotool matchbox-window-manager xvfb \
  usb-modeswitch \
  i2c-tools
```

> **Debian Trixie note:** the package is now `chromium` and the
> binary is `/usr/bin/chromium`. Older Debian releases and Ubuntu
> ship `chromium-browser`; the `bcm-kiosk.service` unit resolves
> whichever exists at runtime, so you don't need to care which one
> is installed.
>
> **Why `xvfb`:** when Android Auto is enabled, BCM renders autoapp
> inside an Xvfb virtual framebuffer and captures it as MJPEG for
> the A2 screen. Without this package the multimedia module fails
> silently at startup.

> **Important — Android Auto sizing**
>
> Three pieces have to line up for the A2 Android Auto screen to
> render correctly (fills the BCM frame, no header/nav overlap, and
> touch passthrough works):
>
> 1. **`matchbox-window-manager`** — BCM launches it inside the Xvfb
>    virtual display (on x86) or directly on `:0` (on OPi) before
>    starting autoapp. It force-maximises every Qt window so autoapp
>    can't render at its internal default size (~800×480).
> 2. **`xdotool`** — a secondary fallback that calls
>    `windowmove / windowsize / windowactivate` on the autoapp window
>    in case matchbox isn't present. Also used by `/aa/touch` to
>    forward browser clicks to Xvfb.
> 3. **`Xvfb`** — the virtual framebuffer AA renders into on x86 and
>    the OPi test rig. BCM sizes it to
>    `(dashboard.width, dashboard.height − AppBar − NavBar)`, i.e.
>    `1024×504` on the default 7" panel, so the AA canvas fits
>    exactly inside the BCM frame with no clipping.
>
> If you skip `matchbox-window-manager` the A2 screen will still work
> but you'll get black space on the right and broken touch mapping.
> All three packages are in the apt install line above.

## 3. Clone BCM + create venv

The venv must be created with `--system-site-packages` so it can
see the Debian `python3-libgpiod` package installed in §2 —
pip's own `gpiod` won't build from source against Python 3.13
headers on Trixie, same story as `spidev` and `opencv-python-headless`
on aarch64 when wheels are stale.

```bash
cd /opt
sudo git clone https://github.com/geek95dg/Alfa156-headunit.git bcm
sudo chown -R $USER:$USER /opt/bcm
cd /opt/bcm

python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt -r requirements-opi.txt
```

## 4. Dual-display wiring (HDMI 2.1 + HDMI 2.0)

The OPi 5 Pro v1.2 has two HDMI outputs at slightly different specs.
Use them like this:

| Port | Spec | Connected to | Frontend |
|------|------|--------------|----------|
| **HDMI 2.1** | 4K60 | 7" IPS 1024×600 touchscreen | `http://localhost:5002` |
| **HDMI 2.0** | 1080p60 | 4.3" TFT 800×480 (no touch)  | `http://localhost:5003` |

Both displays run Chromium in kiosk mode. The main display has a USB
HID touch input connected to the OPi USB 3.0 port; the small display
is display-only.

## 5. 4-camera wiring

The production build uses the **AliExpress 4-camera set** + a
**4-channel USB AHD grabber**. Wire each camera to its grabber input
and plug the grabber into the OPi USB 3.0 port.

```
 Front camera  ──► Grabber CH1 ──┐
 Rear camera   ──► Grabber CH2  ──┼── USB 3.0 ──► OPi 5 Pro USB-A
 Left camera   ──► Grabber CH3  ──┤
 Right camera  ──► Grabber CH4  ──┘
```

Default V4L2 mapping (override in `config/bcm_config.yaml` if your
grabber enumerates in a different order):

```yaml
camera:
  front_device: /dev/video0
  rear_device:  /dev/video1
  left_device:  /dev/video2
  right_device: /dev/video3
  controller:   true
```

Verify after first boot:
```bash
v4l2-ctl --list-devices
ls -la /dev/video*
ffmpeg -f v4l2 -video_size 640x480 -i /dev/video0 -frames 1 /tmp/test.jpg
```

### Camera trigger priority

The multi-camera controller (`src/camera/camera_controller.py`) decides
which feed the small display shows based on live event-bus state:

| Trigger event            | Camera shown | Badge |
|--------------------------|--------------|-------|
| `power.reverse_gear=True`| `rear`       | **R** (red) |
| `vehicle.left_blinker=True`  | `left`   | **L** (amber) |
| `vehicle.right_blinker=True` | `right`  | **P** (green) |
| none                     | (grid)       | — |

Reverse always wins. Parking sensor bar is only drawn for rear.

## 6. Blinker GPIO wiring (2 × PC817)

Tap into the car's turn-signal wires (before the relays) and run them
through two PC817 optoisolators to OPi GPIO pins. Same pattern as the
existing ignition / door optoisolators.

```
  12V L-blinker wire ── [4.7 kΩ] ── PC817 anode
                                    PC817 cathode ─ GND
        3.3V ── [10 kΩ] ── PC817 collector ──── OPi pin 11 (GPIO17)
                           PC817 emitter  ── GND

  12V R-blinker wire ── [4.7 kΩ] ── PC817 anode
                                    PC817 cathode ─ GND
        3.3V ── [10 kΩ] ── PC817 collector ──── OPi pin 13 (GPIO27)
                           PC817 emitter  ── GND
```

Active-low: when 12V is present on the blinker wire, PC817 pulls the
GPIO line LOW. Config uses `active_low: true`.

`config/bcm_config.yaml`:
```yaml
modules:
  blinker_monitor: true
gpio:
  blinker_left: 90          # adjust to match wired pin (RK3588S numbering)
  blinker_right: 91
vehicle:
  blinker_hold_sec: 0.8     # keeps camera overlay steady between flashes
```

Bench-test without a car:
```bash
# Simulate blinker events for camera priority testing
touch /tmp/bcm_blinker_left
# ... wait a second, watch the small display switch to left camera ...
rm /tmp/bcm_blinker_left
```

## 7. Travel Plan API keys

The A3 Travel Plan feature uses two external APIs. Both are optional —
the UI degrades gracefully when no key is set:

```yaml
travel:
  openrouteservice_key: ""   # free tier — needed for real driving routes
                             # (without it, RoutePlanner falls back to a
                             #  haversine straight-line estimate)
  tomtom_key: ""             # paid tier — needed for road works /
                             # incidents along the route (without it,
                             #  the incidents panel is hidden)
```

Sign up:
- OpenRouteService: https://openrouteservice.org (free tier available)
- TomTom Traffic: https://developer.tomtom.com (paid)

## 8. systemd services (boot to kiosk)

Copy the three service files and enable the ignition watcher. The
existing files under `config/systemd/` are reused — just make sure
the `ExecStart=` command uses `--platform opi` (not `opi_pc`).

```bash
cd /opt/bcm
sudo cp config/systemd/bcm-ignition-watcher.service /etc/systemd/system/
sudo cp config/systemd/bcm-headunit.service         /etc/systemd/system/
sudo cp config/systemd/bcm-kiosk.service            /etc/systemd/system/
# Adjust --platform arg for OPi 5 Pro
sudo sed -i 's/--platform opi_pc/--platform opi/' \
    /etc/systemd/system/bcm-headunit.service

sudo systemctl daemon-reload
sudo systemctl enable bcm-ignition-watcher.service
```

Expected boot sequence:
1. Armbian boots (~12 s)
2. `bcm-ignition-watcher` runs (waits for 12V on the ignition pin)
3. Ignition ON → `bcm-headunit` starts (main.py --frontend) (~4 s)
4. Flask ready → `bcm-kiosk` opens Chromium full-screen on HDMI 2.1
5. The small display can be a second Chromium instance pointing at
   `http://localhost:5003` (or a dedicated framebuffer browser).

## 9. Smoke test checklist

- [ ] Both Chromium instances load their respective Flask servers.
- [ ] Dashboard shows the last visited screen after a reload
      (localStorage persistence).
- [ ] A2 Android Auto fills the full content area — no black bar on
      the right (openauto.ini V4 with synced touchscreen dims).
- [ ] Small display (:5003) shows the **2×2 grid** with fuel /
      coolant / ext temp / int temp.
- [ ] With the engine in reverse, the small display switches to the
      rear camera + parking sensor bar.
- [ ] With the left blinker on, the small display switches to the
      left camera (amber L badge).
- [ ] With the right blinker on, the small display switches to the
      right camera (green P badge).
- [ ] A4 Weather map updates reactively when a new city is searched
      (no 6-second pause before the data appears).
- [ ] A3 Trip → **Travel Plan** → enter `Gdynia` → the route
      summary shows distance / ETA / fuel estimate and a weather
      strip. With a TomTom key set, the incidents list populates.
- [ ] `free -h` shows plenty of headroom on 4 GB RAM.
- [ ] `cat /sys/class/thermal/thermal_zone0/temp` stays below 80 °C.

## 10. Troubleshooting

### Android Auto window is too big / overlaps header or nav bar

BCM caches the OpenAuto config in `openauto.ini` next to `main.py`.
If you upgraded BCM from an earlier version, delete the cached file
and restart the headunit so the new canvas size (`1024×504`) is
regenerated:

```bash
rm -f /opt/bcm/openauto.ini
sudo systemctl restart bcm-headunit
```

Confirm the new file has the right dimensions:
```bash
grep Touchscreen /opt/bcm/openauto.ini
# Expected:
#   TouchscreenWidth=1024
#   TouchscreenHeight=504
```

### Android Auto still opens at 800×480

`matchbox-window-manager` is likely missing. Install it and restart:
```bash
sudo apt install -y matchbox-window-manager xdotool
sudo systemctl restart bcm-headunit
```
Then check the logs for `Window manager running inside …: matchbox-window-manager`.

### A2 touches don't reach the phone

Verify `xdotool` is installed (`which xdotool`) and that
`DISPLAY=:99 xdotool mousemove 100 100 click 1` works from the
shell. If not, `xdotool` itself is missing or Xvfb isn't running.
