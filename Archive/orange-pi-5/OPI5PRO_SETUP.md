# Orange Pi 5 Pro 4GB — Setup & Wiring Guide

Primary production build of the Alfa 156 BCM head unit on the
**Orange Pi 5 Pro 4GB** (RK3588S, HDMI 2.1 + HDMI 2.0, WiFi 6, BT 5.0).
This is the intended final in-car platform.

See also:
- [`OPI5PRO_BOM.md`](OPI5PRO_BOM.md) — parts list and prices
- [`../orange-pi-pc/OPI_PC_SETUP.md`](../orange-pi-pc/OPI_PC_SETUP.md) — bench test rig (pre-production)

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
  pipewire pipewire-alsa wireplumber alsa-utils \
  bluez blueman \
  v4l-utils ffmpeg mpv \
  gstreamer1.0-tools gstreamer1.0-plugins-good \
  gstreamer1.0-plugins-bad gstreamer1.0-rockchip1 \
  xdotool matchbox-window-manager xvfb \
  usb-modeswitch \
  i2c-tools
```

`mpv` + `alsa-utils` are optional-but-recommended — they power
the §10 boot splash. `mpv` loops branded MP4 clips on both HDMI
outputs before Chromium comes up; `alsa-utils` provides the
`alsactl` command that unmutes the default mixer state so the
audio track embedded in `main.mp4` actually reaches the car
speakers during boot.

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

## 6.5 Ignition wiring — PC-style push button OR 12 V optoisolator

The `bcm-ignition-watcher.service` daemon polls **two** GPIO
inputs to decide when `bcm-headunit.service` should run. Wire
whichever of the two matches your physical setup — or both.

| Input | Config key | Behaviour |
|-------|-----------|-----------|
| **12 V ignition line** (via PC817 optoisolator) | `power.ignition_watcher.ignition_line` | **Level-triggered.** Holding the line LOW (= 12 V accessory present) keeps BCM ON. This is how the real car will wire it. |
| **Push button** (2-pin momentary — PC-case style) | `power.ignition_watcher.bench_button_line` | **Edge-triggered toggle.** Press once → BCM ON. Press again → BCM OFF. Ideal for bench tests on the desk, or as a manual override in the car. |

Both are configured with `active_low: true` — the line reads
LOW when active. Defaults in `config/bcm_config.yaml` are
`ignition_line: 7` and `bench_button_line: 37`; adjust the
integers to match whichever OPi 5 Pro GPIO lines you picked.
`gpioinfo gpiochip0` lists every line by name so you can choose
two unused ones.

### 6.5.1 PC-style push button (simplest — no 12 V needed)

Two legs of a normally-open momentary button → two pins on the
OPi 5 Pro header. One leg to the chosen GPIO (e.g. line 37), the
other to any GND pin:

```
   OPi GPIO line 37 ──┐
                      │  [push button — normally open]
   OPi GND            ┘
```

libgpiod enables `Bias.PULL_UP` internally inside
`ignition_watcher._start_gpio()` so the pin sits at 3.3 V while
the button is open and drops to GND when pressed — no external
resistor required. Each press toggles BCM on / off via
`bcm-headunit.service`.

### 6.5.2 12 V ignition line (production wiring)

Same PC817 pattern as the door / rain / blinker inputs:

```
    12 V ACC ── [4.7 kΩ] ── PC817 anode
                             PC817 cathode ── GND

       3.3 V ── [10 kΩ] ── PC817 collector ──── OPi ignition GPIO
                          PC817 emitter   ── GND
```

12 V present → OPi pin LOW → ignition ON. 12 V off → OPi pin
HIGH (pull-up) → BCM stops gracefully after
`power.shutdown_delay_seconds`.

### 6.5.3 Test from the shell

```bash
# Watch the daemon in one terminal
sudo journalctl -fu bcm-ignition-watcher

# In another, press the button or toggle the 12 V source. Expect:
#   Bench button pressed — ignition ON
#   === IGNITION ON — Starting BCM headunit ===
# or:
#   Ignition signal changed — ON
#   === IGNITION ON — Starting BCM headunit ===
```

## 6.6 SWC calibration (dual-pod steering wheel remote)

If you have one or two AliExpress SWC button kits (up to 24 buttons
across two pods) wired through a resistor-ladder decoder to the
Arduino A0 analog input, run the calibration procedure before
configuring button mappings:

1. Hold **HOME + BACK** on the Arduino at boot to enter calibration mode.
2. Follow the serial prompts — press each button in turn; the Arduino
   records the analog voltage threshold for every button.
3. Thresholds are stored in Arduino EEPROM and persist across reboots.

After calibration, open the BCM **Web Settings UI** (accessible from
the Settings screen) to assign actions to each button. The config uses
an action-centric `swc.mapping` schema (replaces the old `swc.buttons`
format). Available action types include `bcm_power_toggle`,
`voice_aa_trigger`, and `navigate_aa` in addition to the standard
volume / track / phone / source actions.

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

## 10. Boot splash (optional but highly recommended)

By default Armbian prints a kernel log to both HDMI outputs until
`bcm-kiosk.service` opens Chromium ~12–15 s into the boot. That's
ugly for an in-car head unit. This optional section replaces that
period with two branded MP4 loops — one full-screen loading
animation **with audio** on the big display, and a silent slow
breathing Alfa Romeo logo on the small display — that hand over
to the BCM UI as soon as the Flask servers are ready.

> **OPi 5 Pro has full hardware video acceleration.** The
> RK3588S VPU decodes 1080p H.264 at 60 FPS through the kernel's
> `rkmpp` GStreamer/FFmpeg plugin, which mpv picks up
> automatically. Use whatever resolution matches your panel
> (1024×600 / 1280×800) and mpv will play it smoothly at
> 25 FPS+. The 1-FPS slideshow problem that the OPi PC bench
> rig hits with 720p video does **not** apply here — don't
> downsize your source clips for the production board.

### 10.1 Drop your video files in

The repo doesn't ship the actual videos — they're user-supplied
branding. Put whatever you want in here:

```bash
sudo mkdir -p /opt/bcm/assets/splash
sudo cp main.mp4  /opt/bcm/assets/splash/main.mp4     # 1024x600,  5–10 s loop, H.264+AAC
sudo cp small.mp4 /opt/bcm/assets/splash/small.mp4    #  800x480,  3–5 s loop, H.264 (silent)
sudo chown -R $USER:$USER /opt/bcm/assets/splash
```

| File | Audio track? | Size | Length |
|------|--------------|------|--------|
| `main.mp4`  | **Yes** — plays through the car speakers during the boot-to-kiosk handoff. AAC 128 kbps stereo is fine. | 1024×600 (7") or 1280×800 (8"). Match `display.dashboard.{width,height}` in `config/bcm_config.yaml`. | 5–10 s seamless loop. |
| `small.mp4` | **No** — silent breathing logo. Don't ship an audio track (or at least don't expect it to play). | 800×480 to match the 4.3" stats display. | 3–5 s loop. |

One-liner to transcode any source video into a loop-friendly
`main.mp4` with audio:

```bash
ffmpeg -i INPUT \
    -c:v libx264 -preset medium -crf 22 \
    -c:a aac -b:a 128k -ac 2 \
    -t 8 -vf "scale=1024:600" \
    -movflags +faststart \
    main.mp4
```

If a file is missing the matching systemd service no-ops via
`ConditionPathExists=` — the boot just falls back to the normal
kernel log + the existing Flask init splash.

> **Why does only `main.mp4` play audio?** The boot splash runs
> before any user session exists, so PipeWire isn't up yet; the
> `bcm-splash-main.service` opens ALSA directly through
> `mpv --ao=alsa,pipewire,pulse`. Running two mpv instances
> against the same ALSA card would fight for the device and
> produce crackling, so the small display stays silent. The
> "main" in the service name refers to "main audio source", not
> just "main display".

### 10.2 Install the two splash services

The repo ships two systemd unit files for this, already at
`config/systemd/bcm-splash-main.service` and
`config/systemd/bcm-splash-small.service`:

```bash
cd /opt/bcm
sudo cp config/systemd/bcm-splash-main.service  /etc/systemd/system/
sudo cp config/systemd/bcm-splash-small.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable bcm-splash-main.service
sudo systemctl enable bcm-splash-small.service
```

Both units are `PartOf=bcm-headunit.service`, so the moment
Chromium comes up the splash `mpv` instance is killed cleanly
and the HDMI framebuffer is released.

### 10.3 Hide the kernel boot log

`quiet loglevel=3` in the kernel cmdline removes 95 % of the
Armbian printk noise. On the OPi 5 Pro Armbian uses
`/boot/armbianEnv.txt`:

```bash
sudo sed -i '/^extraargs=/d' /boot/armbianEnv.txt
echo 'extraargs=quiet loglevel=3 vt.global_cursor_default=0' | \
    sudo tee -a /boot/armbianEnv.txt
```

After `sudo reboot` the boot sequence looks like:

1. U-Boot (unavoidable — ~1 s of serial text on HDMI)
2. Kernel loads (quiet → blank screen)
3. `systemd-vconsole-setup` → tty1 blank
4. **`bcm-splash-main.service` + `bcm-splash-small.service` fire**
   → your two MP4 loops start on the two HDMI outputs
5. `bcm-ignition-watcher.service` starts (splash still running)
6. Ignition → `bcm-headunit.service` starts, Flask on :5002 / :5003
7. `bcm-kiosk.service` opens Chromium → splash mpv processes exit
8. BCM UI visible

### 10.4 Smoke test

```bash
# Play the main splash manually with audio (exactly as the
# systemd unit will run it at boot)
sudo mpv --vo=drm --drm-connector=HDMI-A-1 \
    --ao=alsa,pipewire,pulse \
    --fs --loop-file=inf --really-quiet \
    /opt/bcm/assets/splash/main.mp4

# Ctrl+C to stop, then the silent small-display splash
sudo mpv --vo=drm --drm-connector=HDMI-A-2 \
    --fs --loop-file=inf --really-quiet --no-audio \
    /opt/bcm/assets/splash/small.mp4
```

Run these as root so they match exactly what the systemd
services do (both units run as root and pick up the `video`,
`render`, and — for the main one only — `audio` supplementary
groups). If the main one works but the audio is silent, skip
ahead to §10.5 for the ALSA mixer fix.

If either command fails with `Failed to open DRM device` your
kernel doesn't expose DRM modesetting on that HDMI output — on
Armbian Trixie this usually means you booted with `extlinux.conf`
rather than a proper Armbian image; re-flash from an official
`Armbian_*_Orangepi5-pro_trixie_*.img.xz`.

### 10.5 Troubleshooting the splash

- **Splash never shows, kernel log still visible** →
  `quiet loglevel=3` wasn't applied. Check `/boot/armbianEnv.txt`
  has the `extraargs=` line and reboot.
- **Splash video plays but there is no sound** → ALSA mixers
  are muted by default on some Armbian images. Install
  `alsa-utils` and restore the state:
  ```bash
  sudo apt install -y alsa-utils
  sudo alsactl init
  amixer set Master unmute 90%    # or the name your card uses
  sudo alsactl store              # persist for next boot
  sudo systemctl restart bcm-splash-main
  ```
  `aplay -l` should list the sound card and `speaker-test -c 2
  -t wav -l 1` should produce an audible tone. If it does, the
  splash service will play audio on the next boot.
- **Audio plays but stutters or loops** → the `main.mp4` audio
  track isn't a seamless loop. Re-encode with a 1–2 frame
  fade-in/fade-out so the boundary is silent, or use a shorter
  one-shot jingle and accept that it'll repeat every 5–10 s
  until BCM takes over.
- **Splash shows but doesn't go away when BCM starts** → the
  `PartOf=bcm-headunit.service` directive didn't take. Re-run
  `sudo systemctl daemon-reload && sudo systemctl restart
  bcm-headunit`.
- **"no mpv/ffplay found — install with apt"** → the ExecStart
  shim couldn't find a player binary. `sudo apt install -y mpv`.
- **DRM connector name wrong** → run `ls /sys/class/drm/` on the
  live system. You should see entries like `card0-HDMI-A-1` and
  `card0-HDMI-A-2`. If your SoC exposes different names (e.g.
  `HDMI-A-0`), edit the two unit files' `--drm-connector=` flags
  and `sudo systemctl daemon-reload`.

## 11. Troubleshooting

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
