# Orange Pi PC 1.2 — Setup & Testing Manual

Bench test rig for the Alfa 156 BCM head unit, built around the
**Orange Pi PC 1.2** (Allwinner H3, 1 GB RAM, armv7l) running
**Armbian Trixie** (Debian 13, kernel ≥ 6.18). The rig is meant as
a cheap pre-production sanity check before committing to the
production board — see [`../orange-pi-5/OPI5PRO_SETUP.md`](../orange-pi-5/OPI5PRO_SETUP.md) for
the Orange Pi 5 Pro 4 GB build intended for the in-car install.

The manual is organised so each **Part** is self-contained and can
be tested before moving to the next one. **Parts 1 and 2 are
software-only** — no soldering, no sensors, no wiring. The goal of
Parts 1+2 is to boot the OPi PC, start X, launch BCM, and watch
the dashboard render with simulated data, before touching any
hardware.

---

## Part 0 — What you need to start

### Absolute minimum (Parts 1 + 2 — software desk test)

| Item | Notes |
|------|-------|
| Orange Pi PC 1.2 | Allwinner H3 quad-core Cortex-A7, 1 GB LPDDR3 |
| 5 V / 3 A PSU | Barrel jack (4.0×1.7 mm) preferred over micro-USB |
| 8 GB+ microSD | Class 10, UHS-I |
| HDMI display | Any monitor, 1024×600 or higher |
| USB keyboard | For first-boot login + reboots |
| Ethernet cable | No built-in WiFi — wired network only for Part 1 |
| Armbian image | `Armbian_*_Orangepipc_trixie_current_minimal.img.xz` |

That's it. You don't need a second monitor, a touchscreen, or a
single wire soldered before you finish Part 2.

### Added later

| Part | What you add |
|------|--------------|
| Part 3 | USB WiFi / BT / UART / webcam / GPS / LTE dongles |
| Part 4 | HC-SR04 parking sensors, DS18B20 temperature probe, buzzer, PC817 optoisolators for ignition / door / blinker signals |
| Part 5 | Bench button on a real GPIO line for the ignition watcher |
| Part 6 | In-car mount (the real car) |

---

## Part 1 — Desk Test (nothing wired)

### 1.1 Flash Armbian Trixie

On your PC, download the latest **Armbian Trixie CLI minimal** image
for Orange Pi PC from <https://www.armbian.com/orange-pi-pc/> and
flash it to the microSD card:

```bash
xz -d Armbian_*_Orangepipc_trixie_current_minimal.img.xz
sudo dd if=Armbian_*_Orangepipc_trixie_current_minimal.img \
        of=/dev/sdX bs=4M status=progress conv=fsync
sync
```

Replace `/dev/sdX` with your actual SD card device (check with
`lsblk` before dd-ing). Insert the SD into the OPi PC, connect
HDMI + keyboard + Ethernet, then apply power.

### 1.2 First boot

Default Armbian login on first boot is `root` / `1234`. The
firstlogin helper then asks you to:

1. Change the root password.
2. Create a normal user. **Remember the username** — every later
   step assumes it. This manual uses `alfa` as the example.
3. Pick a default shell (bash is fine).
4. Set timezone / locale.

After the helper exits, finish the basics:

```bash
sudo hostnamectl set-hostname bcm-test
sudo timedatectl set-timezone Europe/Warsaw
sudo apt update && sudo apt -y full-upgrade
```

Reboot if the kernel was updated:

```bash
sudo reboot
```

### 1.3 Core system packages

Install the core runtime BCM needs (no X yet, no kiosk — just what
the Python modules import):

```bash
sudo apt install -y \
  python3 python3-pip python3-venv python3-dev \
  git curl \
  libgpiod-dev gpiod python3-libgpiod \
  pipewire pipewire-alsa wireplumber \
  bluez blueman \
  v4l-utils ffmpeg \
  gstreamer1.0-tools gstreamer1.0-plugins-good \
  usb-modeswitch usb-modeswitch-data \
  i2c-tools
```

> **Debian Trixie vs Bookworm — the libgpiod rename.**
> On Bookworm the runtime package was `libgpiod2` (= libgpiod 1.x).
> On Trixie it's been bumped to `libgpiod3` (= libgpiod 2.x) and the
> old `libgpiod2` name is gone. The apt line above sidesteps the
> rename entirely by installing **`libgpiod-dev` + `python3-libgpiod`**:
>
> - `libgpiod-dev` is a virtual name that resolves to whichever
>   runtime (libgpiod2 or libgpiod3) matches the current release.
> - `python3-libgpiod` is the Debian-built Python binding — it's
>   compiled by the distro against the matching runtime, so BCM
>   doesn't have to build `gpiod` from source via pip (which fails
>   against Python 3.13 headers on Trixie, same reason `spidev`
>   fails).
> - The `gpiod` CLI tool (`gpioinfo`, `gpioget`, `gpioset`) ships in
>   the `gpiod` package — you'll use it from Part 4 onwards to
>   verify individual GPIO lines before BCM touches them.
>
> This means the BCM Python venv in §1.7 must be created with
> `python3 -m venv --system-site-packages .venv` so it can see the
> apt-installed `python3-libgpiod`. That's the default for the
> OPi PC from here on.

Quick sanity check:

```bash
gpioinfo gpiochip0 | head -5      # should list PA* lines
pactl info | grep 'Server Name'   # should say PipeWire
```

If either fails the rest of the manual will not work — fix the
underlying package first.

### 1.4 Install X server (Debian Trixie specifics)

This is the step the previous manual skipped. On a minimal
Armbian Trixie image there is **no X server at all**, no window
manager, and `startx` isn't even installed. Install the full set:

```bash
sudo apt install -y \
  xserver-xorg xserver-xorg-video-fbdev xserver-xorg-video-modesetting \
  xserver-xorg-input-libinput xserver-xorg-input-evdev \
  xserver-xorg-legacy xinit x11-xserver-utils \
  matchbox-window-manager unclutter \
  chromium xdotool \
  xvfb mpv alsa-utils
```

`mpv` + `alsa-utils` are only needed if you later enable the
optional boot-splash services (Part 6.5) — `mpv` loops a branded
MP4 on the HDMI output to hide the Armbian kernel log during
boot, and `alsa-utils` provides `alsactl` so the audio track
embedded in `main.mp4` actually plays through the 3.5 mm jack
at boot time. Keep both installed even on the bench rig so the
service files work out of the box when you copy them.

> `xvfb` is the headless X framebuffer that `src/multimedia/openauto.py`
> launches when the multimedia module is enabled (even on the OPi PC
> it's used as a fallback when Android Auto is tested off the main
> HDMI output). Keep it installed so the `modules.multimedia: true`
> path works later.

`matchbox-window-manager` is reused by BCM to force-maximise the
Android Auto window later — keep it installed even if you're not
testing AA on this rig.

### 1.5 Allow non-root users to start X (the real fix for "startx fails")

On Debian Trixie, `Xorg` refuses to start when launched by a normal
user unless `/etc/X11/Xwrapper.config` says so. If the user reports
`Only console users are allowed to run the X server`, this is why:

```bash
sudo sed -i \
    -e 's/^allowed_users=.*/allowed_users=anybody/' \
    -e 's/^needs_root_rights=.*/needs_root_rights=yes/' \
    /etc/X11/Xwrapper.config
```

If the file doesn't exist yet (some minimal images), create it:

```bash
sudo tee /etc/X11/Xwrapper.config >/dev/null <<'EOF'
allowed_users=anybody
needs_root_rights=yes
EOF
```

Log out and log back in so the group membership refreshes.

### 1.6 Manual X smoke test — before touching BCM

This is the single most important test in Part 1. Before you run
any BCM code, prove that X itself actually works:

```bash
startx /usr/bin/matchbox-window-manager -- -use_titlebar no -use_cursor no
```

Expected result:
- HDMI output flickers, backlight stays on.
- Screen goes grey.
- A mouse cursor appears if a USB mouse is connected.
- There are no decorations, no desktop — just grey.

Press `Ctrl+Alt+Backspace` (or switch to another tty with
`Ctrl+Alt+F2` and `sudo pkill Xorg`) to exit.

If this fails, **stop here and fix X first**. Common failures:

- `command not found: startx` → `xinit` package not installed.
- `Only console users are allowed to run the X server` → §1.5 not
  done, or you didn't log out / back in afterwards.
- `no screens found` → on Allwinner H3, make sure `fbdev` driver
  package is installed (`xserver-xorg-video-fbdev`).
- Blank HDMI → check `/boot/armbianEnv.txt` has `console=both`
  and the HDMI cable is plugged in before boot.

Once the grey X screen appears, you have a working display stack
and you're ready to install BCM itself.

### 1.7 Clone BCM and create the Python venv

> **Important — always use `--system-site-packages` on the OPi PC.**
> The venv must be able to see the `python3-libgpiod` apt package
> installed in §1.3; without `--system-site-packages` the venv
> hides every apt-installed Python module and BCM fails to import
> `gpiod` at startup. This is the single most common gotcha on
> Trixie — see §7 Troubleshooting.

```bash
sudo mkdir -p /opt
cd /opt
sudo git clone https://github.com/geek95dg/Alfa156-headunit.git bcm
sudo chown -R $USER:$USER /opt/bcm
cd /opt/bcm

python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt -r requirements-opi-pc.txt
```

> **Important — do NOT install `requirements-x86.txt` on the OPi PC.**
> The x86 file contains desktop-only dependencies that may fail to
> build on armv7l. The OPi PC runs BCM in `--frontend` mode using
> Flask + Chromium, so desktop rendering libraries are unnecessary.

> **Also note — `opencv-python-headless`, `Pillow`, `spidev` and
> `smbus2` are NOT in `requirements-opi-pc.txt`.** All four would
> compile C code on install:
>
> - `opencv-python-headless` and `Pillow` have no pre-built armv7l
>   wheels on PyPI, so pip falls back to a 4+ GB RAM source build
>   that OOM-kills on the 1 GB OPi PC.
> - `spidev` always ships as a source distribution and its C
>   extension refuses to build against the Python 3.13 headers that
>   Armbian Trixie installs.
> - `smbus2` is pure Python but depends on `i2c-tools` + kernel
>   i2c-dev nodes that the bench rig doesn't use yet.
>
> BCM uses all four through lazy `try/except import` blocks
> (`src/dashboard/web_viewer.py`, `src/dashboard/small_viewer.py`,
> `src/dashboard/overlays.py`, `src/location/map_renderer.py`,
> `src/core/hal.py::RealSPI`, `src/core/hal.py::RealI2C`), so BCM
> starts and runs cleanly without them — SPI / I²C / camera /
> map-image features just stay inactive. That is exactly what you
> want for the desk test in Parts 1–2 because neither a camera
> nor an I²C sensor is connected yet.

Sanity-check that every **required** runtime import succeeds — this
catches missing `python3-libgpiod` (or the wrong venv flag) early:

```bash
python3 -c "import gpiod, yaml, flask, flask_sock, serial; print('ok')"
```

(Don't add `cv2` or `PIL` here — see the next section for when you
actually want them.)

If you see `ImportError: No module named gpiod` even though the
apt package is installed, the venv was created **without**
`--system-site-packages` and can't see `python3-libgpiod`. Fix:

```bash
rm -rf .venv
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-opi-pc.txt
python3 -c "import gpiod; print(gpiod.__version__)"
```

If you see import errors for desktop-only packages when you later
run `main.py` **without** `--frontend`, you accidentally installed
the x86 requirements. Rebuild the venv and install only
`requirements.txt` + `requirements-opi-pc.txt`.

#### Optional — enabling the camera stream endpoint later

Once you actually plug in a USB webcam in Part 3.4 and want the
`/api/camera/stream?cam=front` endpoint on `:5002`/`:5003` to
return real frames instead of a placeholder, install the Debian
system packages and recreate the venv with `--system-site-packages`
so the apt-installed OpenCV is visible from inside the venv:

```bash
sudo apt install -y python3-opencv python3-pil

cd /opt/bcm
rm -rf .venv
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt -r requirements-opi-pc.txt

# Verify
python3 -c "import cv2, PIL; print(cv2.__version__, PIL.__version__)"
```

The `--system-site-packages` flag is the critical bit — without
it the venv hides the `python3-opencv` apt package. On Armbian
Trixie the Debian `python3-opencv` binary weighs ~80 MB and is
pre-built by the distro; the OPi PC never has to compile anything.

The same recipe enables two other optional BCM features that live
behind lazy imports:

| apt package    | Enables (lazy import site)                    |
|----------------|-----------------------------------------------|
| `python3-opencv` | `/api/camera/stream` MJPEG endpoint (cv2)  |
| `python3-pil`    | GPS map PNG export in `src/location/map_renderer.py` |
| `python3-evdev`  | BT remote + Arduino HID input modules (`src/input/bt_remote.py`, `src/input/arduino_hid.py`) |
| `python3-dbus`   | Native Linux Bluetooth manager in `src/multimedia/bluetooth.py` |
| `python3-spidev` | SPI MCP3008 ADC for SWC analog decoder (not used yet, reserved for Part 4+) |
| `python3-smbus`  | I²C sensor expansion (not used yet, reserved for Part 4+) |

All six have pre-built Debian binaries — none of them compile on
the OPi PC. Install only the ones you actually need and rebuild
the venv with `--system-site-packages` to expose them. Leaving
them uninstalled is also fine; BCM just skips the corresponding
feature and logs a single warning at startup.

### 1.8 Lean the config for a 1 GB RAM bench test

The default OPi PC config enables Android Auto (`modules.multimedia`)
and LTE (`modules.network`). Both are memory-heavy and pointless on
an empty bench — disable them now so BCM has room to breathe on the
first manual run. You can flip them back on later in Part 3 / Part 5.

```bash
cd /opt/bcm
sed -i \
  -e 's/^  multimedia: true.*/  multimedia: false/' \
  -e 's/^  network: true.*/  network: false/' \
  config/bcm_config_opi_pc.yaml

grep -E 'multimedia:|network:' config/bcm_config_opi_pc.yaml
# Expect both to read `false`.
```

Leave `obd`, `parking`, `environment`, `audio`, `camera`, `power`,
`location`, `weather`, `input`, `swc` and `dashboard` on their defaults —
all of them degrade gracefully to mock / simulator mode when their
hardware isn't present (confirmed in `src/camera/ahd_grabber.py`,
`src/environment/ds18b20.py`, and the HAL factory in
`src/core/hal.py`).

### 1.9 First manual run — the only correct desk invocation

```bash
cd /opt/bcm
source .venv/bin/activate
./run_opi_pc.sh --no-watcher
```

**Important** — don't add `--simulate`. That flag is only meaningful
when the **ignition watcher** is running; with `--no-watcher` it is
silently passed through to `main.py` as an unknown positional arg
and ignored. The launcher prints:

```
╠══════════════════════════════════════════════════╣
║   Mode: Direct start (no ignition watcher)       ║
║   Web frontend: http://localhost:5002             ║
║   Small display: http://localhost:5003            ║
╚══════════════════════════════════════════════════╝
```

The process stays in the foreground and prints log lines
(Dashboard, OBD simulator, WebViewer on :5002, SmallDisplayServer
on :5003). You'll need a **second terminal** (SSH, a second tty
switched with `Ctrl+Alt+F2`, or tmux) for §1.10.

### 1.10 Open the dashboard in Chromium

From the second terminal:

```bash
# First verify Flask is actually answering
curl -sf http://localhost:5002 | head -c 200 && echo
curl -sf http://localhost:5003 | head -c 200 && echo
```

Both should return HTML. Then in an X session (from §1.6 — start
a new one if you closed it), launch the two browser windows:

```bash
export DISPLAY=:0
chromium --kiosk --noerrdialogs --disable-infobars \
    --user-data-dir=/tmp/bcm-chromium-main \
    http://localhost:5002 &

# Optional — second Chromium for the small display (4.3" 2×2 grid)
chromium --new-window --noerrdialogs \
    --user-data-dir=/tmp/bcm-chromium-small \
    http://localhost:5003 &
```

What you should see on :5002:

1. **Init splash** (~4 seconds) with the Alfa logo.
2. **A1 Dashboard** — simulated RPM / speed / coolant / fuel gauges
   ramping on demo data.
3. Use the nav bar at the bottom to walk through A2 (AA placeholder
   — "Waiting for device" because `multimedia` is off), A3 (Trip
   with the **Travel Plan** toggle button), A4 (Weather demo card),
   A5 (Service), A6 (DVR), A7 (Performance), A8 (Phone).

And on :5003: the static 2×2 stats grid (fuel / coolant / ext
temp / int temp) with the top clock header.

### 1.11 Part 1 checklist

Check each box before moving to Part 2. If any fails, the later
parts will fail too.

- [ ] Armbian boots to a `login:` prompt within ~20 s.
- [ ] `gpioinfo gpiochip0` lists PA lines (libgpiod runtime works).
- [ ] `startx ... matchbox-window-manager` shows a grey X screen.
- [ ] Python venv import smoke test prints `ok`.
- [ ] `./run_opi_pc.sh --no-watcher` stays running without tracebacks.
- [ ] `curl -sf http://localhost:5002` returns HTML.
- [ ] Chromium loads `http://localhost:5002` and the init splash
      animates into A1 Dashboard.
- [ ] Nav bar at the bottom cycles through A1 → A8.
- [ ] `http://localhost:5003` shows the 2×2 stats grid.
- [ ] `Ctrl+C` on the launcher shuts everything down cleanly.

Once all ten boxes are ticked, you have a fully functional BCM
running on simulated data with zero wiring. Move on to Part 2.

---

## Part 2 — Auto-start (still no hardware)

Goal of this Part: make the rig boot straight to the kiosk view
of BCM, without you having to SSH in and run `./run_opi_pc.sh` by
hand. Still no wiring required — the ignition watcher uses a file
trigger (`/tmp/bcm_ignition_on`) to simulate the real 12 V signal.

### 2.1 Autologin on tty1

BCM assumes a single user logs into tty1 at boot and then runs
`startx`. Autologin via a systemd drop-in:

```bash
sudo mkdir -p /etc/systemd/system/getty@tty1.service.d
sudo tee /etc/systemd/system/getty@tty1.service.d/autologin.conf >/dev/null <<EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin $USER --noclear %I \$TERM
EOF
sudo systemctl daemon-reload
```

`$USER` is expanded **now** (while you're logged in as `alfa` or
whatever) so the file ends up hard-coded to that account. Verify:

```bash
cat /etc/systemd/system/getty@tty1.service.d/autologin.conf
# ExecStart=-/sbin/agetty --autologin alfa --noclear %I $TERM
```

### 2.2 Start X automatically on tty1 login

Append to `~/.bash_profile` (create it if missing) so `startx` only
runs on the real console, not inside SSH sessions:

```bash
cat >> ~/.bash_profile <<'EOF'

# BCM kiosk: start X automatically on tty1 only
if [ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then
    exec startx
fi
EOF
```

### 2.3 .xinitrc — matchbox + Chromium kiosks

`~/.xinitrc` runs when `startx` fires. It starts matchbox (the
window manager), waits for the BCM Flask servers, then opens
two Chromium kiosks — one for :5002 (main display) and one for
:5003 (small display).

```bash
cat > ~/.xinitrc <<'EOF'
#!/bin/sh
# BCM kiosk session

# Disable all screen blanking / power saving
xset s off
xset -dpms
xset s noblank

# Hide the mouse cursor after 0.5 s of inactivity
unclutter -idle 0.5 -root &

# Start the window manager — matchbox auto-maximises every window
matchbox-window-manager -use_titlebar no -use_cursor no &

# Wait up to 60 s for the BCM Flask servers to come up.
# bcm-headunit.service is the thing that actually launches them.
for i in $(seq 1 60); do
    curl -sf http://localhost:5002 >/dev/null && break
    sleep 1
done

# Main display (7" HDMI)
chromium --kiosk --noerrdialogs --disable-infobars \
    --disable-features=TranslateUI --no-first-run --fast \
    --user-data-dir=/tmp/bcm-chromium-main \
    http://localhost:5002 &

# Small display (4.3" HDMI) — only useful when you actually have
# a second screen attached. Leave uncommented and it will open on
# the same screen anyway, which is fine for development.
chromium --new-window --noerrdialogs --disable-infobars \
    --user-data-dir=/tmp/bcm-chromium-small \
    http://localhost:5003 &

wait
EOF
chmod +x ~/.xinitrc
```

### 2.4 Install the three BCM systemd services

The repo ships all three already. Copy them into `/etc/systemd/system/`
and enable just the ignition watcher — that one pulls in
`bcm-headunit.service` on demand, which in turn pulls in
`bcm-kiosk.service` via `BindsTo=`.

```bash
cd /opt/bcm
sudo cp config/systemd/bcm-ignition-watcher.service /etc/systemd/system/
sudo cp config/systemd/bcm-headunit.service         /etc/systemd/system/
sudo cp config/systemd/bcm-kiosk.service            /etc/systemd/system/

sudo systemctl daemon-reload
sudo systemctl enable bcm-ignition-watcher.service
```

Do **not** enable `bcm-headunit.service` directly — the ignition
watcher is what should start/stop it.

### 2.5 Boot test with the ignition file trigger

Reboot the OPi PC:

```bash
sudo reboot
```

Expected sequence:

1. Armbian boots (~15 s).
2. tty1 autologins as `alfa`, `.bash_profile` fires `startx`.
3. X comes up, matchbox launches, two Chromium windows open but
   immediately show a connection error (BCM isn't running yet —
   the watcher is waiting for the ignition trigger).
4. `systemctl status bcm-ignition-watcher` should show
   `active (running)` with the log line
   `Ignition watcher started — waiting for ignition signal...`.

Now simulate ignition ON — from a second terminal (SSH in or
`Ctrl+Alt+F2`):

```bash
sudo touch /tmp/bcm_ignition_on
```

Within ~1 second the watcher starts `bcm-headunit.service` (first
start logs `Boot mode: cold`), which starts the Flask servers on
:5002/:5003, which `bcm-kiosk.service` then connects to. The
Chromium windows flip from "connection refused" to the A1
Dashboard (cold boot skips the 4s init screen).

Simulate ignition OFF:

```bash
sudo rm /tmp/bcm_ignition_on
```

`bcm-headunit.service` and `bcm-kiosk.service` stop cleanly. The
OS stays running (deep idle on backup battery). The Chromium
windows stay open but show a connection error again. Repeat
`touch /tmp/bcm_ignition_on` — this time the log shows
`Boot mode: warm` and the frontend shows the 4s init screen.

You can also test the SWC toggle (while BCM is running or stopped):

```bash
touch /tmp/bcm_swc_toggle
```

### 2.6 journalctl cheat sheet

When something misbehaves, these are the commands you'll run over
and over again. Keep them handy:

```bash
# Watch everything BCM is doing, live
sudo journalctl -fu bcm-ignition-watcher -u bcm-headunit -u bcm-kiosk

# Just the last boot
sudo journalctl -b -u bcm-headunit

# Failures only
sudo systemctl --failed
systemctl status bcm-ignition-watcher bcm-headunit bcm-kiosk

# Xorg log (for "startx fails on reboot but works by hand")
cat ~/.local/share/xorg/Xorg.0.log | tail -50

# Memory + CPU temperature
free -h
cat /sys/class/thermal/thermal_zone0/temp
```

### 2.7 Part 2 checklist

- [ ] After reboot, tty1 autologins into `alfa` without asking for
      a password.
- [ ] X starts automatically and matchbox is running
      (`pgrep matchbox-window-manager` returns a PID).
- [ ] Two Chromium windows open.
- [ ] `sudo touch /tmp/bcm_ignition_on` makes both Chromium windows
      show the BCM dashboard within ~5 s.
- [ ] `sudo rm /tmp/bcm_ignition_on` stops BCM cleanly; `systemctl
      status bcm-headunit` reports `inactive`.
- [ ] `free -h` shows at least ~200 MB free with BCM running.
- [ ] CPU temp stays under 70 °C idle.

If all boxes are ticked, you now have a booting-to-kiosk OPi PC
rig. **No wires connected yet.** Everything from here on is
additive — Parts 3, 4, 5 can be tackled in any order.

---

## Part 3 — USB dongles (plug-and-play, no soldering)

This Part is a collection of independent recipes for the USB
peripherals BCM talks to. Plug each one in, follow the one-page
recipe for that device, then move on. Nothing in Part 3 requires
anything from Part 4 — these are all pure USB.

### 3.1 USB WiFi dongle

Any recent realtek-based dongle (RTL8188EUS / RTL8821CU / RTL8192CU)
works out of the box on Armbian Trixie — the drivers are in the
kernel. Plug it in and check:

```bash
lsusb | grep -i -e realtek -e wireless
ip link show          # a `wlan0` or `wlx...` interface appears
```

Connect to the network with NetworkManager (already installed as
part of Armbian):

```bash
sudo nmcli device wifi list
sudo nmcli device wifi connect "SSID_HERE" password "PASS_HERE"
```

For the "car hotspot" use case (the BCM itself broadcasts an AP
the driver's phone joins), that's Part 5 material — leave `wlan0`
as a client for now.

### 3.2 USB Bluetooth dongle

Same story — any CSR-based or Broadcom dongle just works:

```bash
lsusb | grep -i bluetooth
hciconfig            # expect `hci0` with state UP
systemctl status bluetooth
```

Pair a test device (phone or speaker):

```bash
bluetoothctl
> power on
> agent on
> default-agent
> scan on
# ... wait for your phone to appear ...
> pair AA:BB:CC:DD:EE:FF
> trust AA:BB:CC:DD:EE:FF
> connect AA:BB:CC:DD:EE:FF
> quit
```

Verify A2DP audio:

```bash
pactl list sinks short | grep -i bluez
# bluez_output.AA_BB_CC_DD_EE_FF.a2dp_sink  ...
```

Start BCM and play a test track from the phone — the A1 dashboard
should show the media card populated from BlueZ MediaPlayer1.

### 3.3 CP2102 / CH340 USB-UART for K-Line / OBD

BCM uses a USB-UART adapter plus an L9637D transceiver chip as
the K-Line front end. For the bench test you can skip the L9637D
entirely — the OBD module has a built-in simulator that creates a
virtual PTY pair and responds to KWP2000 requests, so you can
verify the A1 gauge wiring without a car.

Physical check anyway:

```bash
lsusb | grep -i -e cp210 -e ch340 -e ftdi
dmesg | tail -n 5    # look for `cp210x converter now attached to ttyUSB0`
ls -la /dev/ttyUSB*
sudo usermod -aG dialout $USER      # then log out + back in
```

The port is already set in `config/bcm_config_opi_pc.yaml`:

```yaml
serial:
  kline:
    port_opi_pc: /dev/ttyUSB0
    baudrate: 10400
    ecu_address: 1
```

Change the port if `dmesg` reported something other than `ttyUSB0`.

### 3.4 USB webcam (first-camera sanity check)

Before you invest in a real 4-channel USB AHD grabber, a single
random USB webcam is enough to prove the camera module works.

```bash
lsusb
ls -la /dev/video*
v4l2-ctl --list-devices

# Capture one frame (purely through ffmpeg — no opencv needed here)
ffmpeg -f v4l2 -video_size 640x480 -i /dev/video0 -frames 1 /tmp/test.jpg
ls -l /tmp/test.jpg
```

In `config/bcm_config_opi_pc.yaml` the front camera already
defaults to `/dev/video0`, so BCM picks it up automatically. In
the running dashboard you should see a preview whenever the
camera module is active.

> **If the browser shows "NO CAMERA" instead of a live feed**, the
> BCM `/api/camera/stream?cam=front` endpoint needs OpenCV to turn
> V4L2 frames into MJPEG. On the OPi PC (armv7l) OpenCV is an
> optional extra — run the Debian `python3-opencv` install recipe
> from §1.7 ("Optional — enabling the camera stream endpoint later")
> to install it through apt and expose it to the venv with
> `--system-site-packages`. Restart BCM afterwards. The ffmpeg
> capture above still works regardless — it bypasses OpenCV
> entirely.

### 3.5 USB GPS (u-blox 7 / 8)

u-blox GPS sticks enumerate as `/dev/ttyACM0` (or `ttyACM1` if
you have the USB-UART adapter in `ttyACM0`). Verify raw NMEA:

```bash
lsusb | grep -i u-blox
dmesg | tail -n 5
sudo cat /dev/ttyACM0 | head -5
# Expect NMEA sentences like $GNRMC,123519.00,...
```

The BCM `location` module opens `/dev/ttyACM0` at 9600 baud by
default. If your GPS is on a different port, edit
`config/bcm_config_opi_pc.yaml` → `hardware.gps.port`.

### 3.6 Huawei E3372 LTE dongle — full recipe

This is the part the old manual left blank. The E3372 ships in
three possible USB modes; you need to know which one yours is in
before you can bring it up.

**Step 1 — detect the mode:**

```bash
lsusb | grep -i huawei
```

| USB ID      | Mode         | What it is                                     |
|-------------|--------------|------------------------------------------------|
| `12d1:1f01` | Mass Storage | "Install CD-ROM" — needs `usb_modeswitch`      |
| `12d1:14db` | HiLink       | USB Ethernet (`usb0`, fixed 192.168.8.x)       |
| `12d1:155e` | Stick        | Serial modem (`/dev/ttyUSB*`), needs ModemManager |

**Step 2 — kick it out of storage mode (if `1f01`):**

```bash
sudo usb_modeswitch -v 12d1 -p 1f01 -J
# Re-run lsusb — it should now show 14db or 155e.
```

If the re-detection doesn't stick, a udev rule persists it across
reboots. On Debian Trixie this file usually already exists:

```bash
ls /usr/share/usb_modeswitch/12d1:1f01 2>/dev/null && \
  echo "usb_modeswitch data present — reboot should re-switch"
```

**Step 3a — HiLink path (14db, easy):**

The dongle runs its own DHCP server on 192.168.8.1. Linux just
needs to DHCP on `usb0`:

```bash
nmcli device status
sudo nmcli connection add type ethernet \
     ifname usb0 con-name huawei-lte autoconnect yes
sudo nmcli connection up huawei-lte

ip addr show usb0       # 192.168.8.x/24
ping -c 3 -I usb0 8.8.8.8
```

Open the dongle's built-in web UI at <http://192.168.8.1/> from a
browser to set the APN, PIN, and carrier settings (one-time).

**Step 3b — Stick / ModemManager path (155e):**

```bash
sudo apt install -y modemmanager
sudo systemctl enable --now ModemManager

sudo mmcli -L
# /org/freedesktop/ModemManager1/Modem/0 [Huawei] E3372

sudo nmcli connection add type gsm ifname '*' \
     con-name huawei-3g apn internet
sudo nmcli connection up huawei-3g
ping -c 3 8.8.8.8
```

Replace `internet` with your carrier's APN (Orange PL: `internet`,
Play: `internet`, T-Mobile PL: `internet`, Plus: `plus`).

**Step 4 — flip BCM back on:**

Once LTE is up, re-enable the BCM network module you disabled in
§1.8:

```bash
sed -i 's/^  network: false.*/  network: true/' \
    config/bcm_config_opi_pc.yaml
```

Restart `bcm-headunit` (via the ignition file trigger) and verify
the A1 status bar shows the LTE bars icon.

### 3.7 Part 3 checklist

- [ ] `lsusb` shows every dongle you plugged in.
- [ ] WiFi: `nmcli connection show --active` lists the SSID.
- [ ] BT: `bluetoothctl paired-devices` lists the test phone.
- [ ] USB-UART: `/dev/ttyUSB0` exists and the user is in `dialout`.
- [ ] Webcam: `/tmp/test.jpg` contains an actual image.
- [ ] GPS: NMEA sentences stream on `/dev/ttyACM0`.
- [ ] LTE: `ping -I usb0 8.8.8.8` returns replies.

---

## Part 4 — GPIO and sensors (soldering starts here)

Up to this point the rig has zero wires. Part 4 is the first time
you touch a soldering iron. Everything here is optional — if you
just want to validate BCM on the desk, Parts 1+2+3 are enough.
Part 4 prepares the rig to validate the in-car wiring *before*
you actually drive to the car.

Every sensor below is individually verifiable with a one-shot
command, so you can wire them one at a time and only move on when
the previous one works.

### 4.1 Enable the device-tree overlays you need

Armbian manages overlays through `/boot/armbianEnv.txt`. Edit:

```bash
sudo nano /boot/armbianEnv.txt
```

Add (or merge into the existing `overlays=` line):

```
overlays=uart3 i2c0 spi-spidev w1-gpio
param_w1_pin=PA6
param_w1_pin_int_pullup=1
```

| Overlay | What it enables |
|---------|-----------------|
| `uart3` | UART3 on PA13/PA14 (physical pins 8 + 10) for K-Line |
| `i2c0`  | I²C bus 0 on PA11/PA12 (pins 3 + 5) — optional sensors |
| `spi-spidev` | SPI bus for the MCP3008 ADC (optional SWC decoder) |
| `w1-gpio` | 1-Wire for DS18B20 temperature probe |
| `param_w1_pin=PA6` | Puts 1-Wire on physical pin 7 |
| `param_w1_pin_int_pullup=1` | Built-in pull-up — skip the 4.7 kΩ |

Reboot, then verify:

```bash
sudo reboot
# ...after it comes back:
ls /sys/bus/w1/devices/         # expect w1_bus_master1
ls /dev/ttyS*                   # ttyS3 should now exist (UART3)
gpioinfo gpiochip0 | grep -E 'PA6|PA13|PA14'
```

### 4.2 Parking sensors — 4× HC-SR04

HC-SR04 sensors run at 5 V and their ECHO pins output 5 V, which
will damage the H3's 3.3 V GPIO if you connect directly. A simple
resistive voltage divider fixes that.

**Wiring (per sensor):**

```
           5V ──────── VCC
          GND ──────── GND
   OPi Pin 16 ──────── TRIG   (all four sensors share this)
                                                   (ECHO)
                      1 kΩ                           │
                  ┌────/\/\────┐                     │
  OPi GPIO ◄──────┤            │◄───────────────────┘
                  │            │
                  └────/\/\────┴──── GND
                      2 kΩ
```

Pin map (from `config/bcm_config_opi_pc.yaml` — every line below
is exposed on the OPi PC 40-pin header AND marked "unused" in
`gpioinfo gpiochip0` on a stock Armbian Trixie image. Don't use
PA2 / PA3 — on Trixie they're claimed by the UART2 serial
console. Don't use anything on PB* / PD* — those banks aren't on
the 40-pin header at all):

| Sensor | Role     | OPi pin | H3 pin | libgpiod line | Config key |
|--------|----------|---------|--------|--------------- |------------|
| Shared | TRIG     | 16      | PC4    | 68             | `gpio.parking_trig` |
| #1     | ECHO LL  | 18      | PC7    | 71             | `gpio.parking_echo[0]` |
| #2     | ECHO CL  | 26      | PA21   | 21             | `gpio.parking_echo[1]` |
| #3     | ECHO CR  | 32      | PG8    | 200            | `gpio.parking_echo[2]` |
| #4     | ECHO RR  | 33      | PG9    | 201            | `gpio.parking_echo[3]` |

**Wiring verification — each sensor, one at a time:**

First, confirm the lines you intend to use are actually free on
your specific Armbian image — a stray overlay might already have
grabbed one:

```bash
gpioinfo gpiochip0 | awk 'NR==1 || /unused/'  | \
    sed -n '1p; /line  *\(6\|68\|71\|21\|200\|201\|9\|7\|8\|203\)/p'
# Every one of those line numbers should appear in the output with
# its "consumer" column showing "unused". If a line is missing, it
# means another driver has claimed it — pick a different line from
# the "RELIABLY FREE" table at the top of
# config/bcm_config_opi_pc.yaml and update the config.
```

Then test one sensor at a time:

```bash
# Fire the TRIG pulse manually
gpioset --mode=time --sec=0 --usec=10 gpiochip0 68=1
# Read one of the ECHO lines
gpioget gpiochip0 71
```

If you see a `1` briefly after a TRIG pulse (object in front of
the sensor), the divider is correct. Repeat for lines 21, 200, 201.

### 4.3 DS18B20 temperature probe

Wiring with the built-in pull-up enabled in §4.1:

```
DS18B20 VDD ── 3.3 V  (OPi pin 1)
DS18B20 GND ── GND    (OPi pin 6)
DS18B20 DQ  ── PA6    (OPi pin 7)
```

Verify:

```bash
ls /sys/bus/w1/devices/
# w1_bus_master1  28-xxxxxxxxxxxx
cat /sys/bus/w1/devices/28-*/temperature
# e.g. 21750  (millidegrees C → 21.75 °C)
```

The BCM `environment` module polls `/sys/bus/w1/devices/28-*/temperature`
automatically — no config changes needed.

### 4.4 Piezo buzzer (BC547 + flyback diode)

The H3 GPIO can't source enough current to drive a 5 V piezo
directly. A BC547 NPN on a 1 kΩ base resistor does the job.

> **Pin correction** — older drafts of this manual used
> `gpio.buzzer=110` (H3 line PD14), but PD* lines are the
> parallel LCD data bus and are *not* exposed on the OPi PC
> 40-pin header at all. The correct default is now
> `gpio.buzzer=9` (PA9, physical pin 35).

```
 OPi Pin 35 (PA9, line 9) ── [1 kΩ] ── BC547 base
                                         BC547 emitter ── GND
                                         BC547 collector ── Buzzer (-)
                                                            Buzzer (+) ── 5 V
                                [1N4148 across the buzzer, cathode to +5 V]
```

Smoke test:

```bash
gpioset gpiochip0 9=1 ; sleep 0.3 ; gpioset gpiochip0 9=0
# You should hear a short beep.
```

### 4.5 Ignition / door / blinker inputs via PC817 optoisolators

Every 12 V vehicle signal BCM reads is isolated via a PC817.
Identical wiring pattern for all of them — 12 V on the car side,
3.3 V on the OPi side, active-low from the OPi's point of view.

```
 12 V signal ── [4.7 kΩ] ── PC817 anode (pin 1)
                             PC817 cathode (pin 2) ── GND

        3.3 V ── [10 kΩ] ── PC817 collector (pin 4) ──── OPi GPIO line
                            PC817 emitter  (pin 3) ── GND
```

Active-low: when 12 V is present on the input side, PC817 pulls
the OPi line LOW.

| Signal          | OPi pin | H3 pin | libgpiod line | Config key |
|-----------------|---------|--------|---------------|------------|
| Ignition        | 29      | PA7    | 7             | `gpio.ignition`, `power.ignition_watcher.ignition_line` |
| Door            | 31      | PA8    | 8             | `gpio.door` |
| Rain / sprayer  | 36      | PA10   | 10            | `gpio.rain_sensor` / `gpio.sprayer` (shared) |
| Central lock    | 37      | PA20   | 20            | `gpio.central_lock` |
| Bench button    | 38      | PG11   | 203           | `gpio.bench_button`, `power.ignition_watcher.bench_button_line` |
| Left blinker    | 40      | PG10   | 202           | `gpio.blinker_left` |
| Right blinker   | **—**   | **—**  | **—**         | `gpio.blinker_right` — left at 0 in the shipped config; pick a free PG* line and edit |

> **Pin correction from older drafts:** the previous config
> claimed `blinker_left=10` (PA10) on physical pin 19 and
> `blinker_right=11` (PA11) on physical pin 23. Those are wrong —
> PA11 is on pin 5 and is claimed by the I²C0 driver, and
> PA10 is on pin 36 not 19. The new config uses PA10 for rain
> sensor and PG10 for left blinker, both of which are on the
> header and unused by kernel drivers.

Verify each input line with:

```bash
gpioget gpiochip0 7        # ignition, PA7 (pin 29)
gpioget gpiochip0 8        # door, PA8 (pin 31)
gpioget gpiochip0 10       # rain/sprayer, PA10 (pin 36)
gpioget gpiochip0 20       # central lock, PA20 (pin 37)
gpioget gpiochip0 203      # bench button, PG11 (pin 38)
gpioget gpiochip0 202      # blinker left, PG10 (pin 40)
```

Every line reads `1` (pull-up) with no input connected. Grounding
the OPi side of the PC817 (or pressing the bench button) should
flip that reading to `0`.

For bench testing without 12 V, you can also short each PC817
input to GND with a jumper — same effect.

### 4.6 Re-enable modules in the config

Back in §1.8 you turned off `multimedia` and `network`.
Parking / environment / camera are already `true` by default.
Once the wiring is verified, enable the blinker monitor:

```bash
sed -i 's/^  blinker_monitor: false.*/  blinker_monitor: true/' \
    config/bcm_config_opi_pc.yaml
```

If you want to test the multi-camera priority logic, also set
`camera.controller: true`. Leave `multimedia` off on
the 1 GB test rig — the H3 doesn't have the RAM for it when
anything else is running.

> **SWC calibration note:** If you have an SWC button kit wired to the
> Arduino A0 analog input, run the calibration mode (hold HOME+BACK at
> Arduino boot) and follow the serial prompts before configuring button
> mappings in the Web Settings UI. Each button's analog voltage threshold
> is stored in the Arduino EEPROM and doesn't need to be repeated unless
> you change the resistor ladder or swap pods.

### 4.7 Part 4 checklist

- [ ] `gpioinfo gpiochip0 | grep -v '\[used\]'` confirms every
      line from §4.1–§4.5 is marked `unused` (i.e. no other
      kernel driver has claimed it).
- [ ] `/sys/bus/w1/devices/28-*/temperature` returns millidegrees.
- [ ] `gpioget gpiochip0 71` / `21` / `200` / `201` each read the
      four HC-SR04 ECHO lines individually.
- [ ] `gpioset gpiochip0 9=1` produces an audible beep through
      the piezo buzzer on pin 35.
- [ ] `gpioget gpiochip0 7` flips from 1 to 0 when you short the
      ignition PC817 input (pin 29 → GND for the bench test).
- [ ] `gpioget gpiochip0 203` flips from 1 to 0 while the
      PC-style push button on pin 38 is held down.
- [ ] With `modules.parking: true`, the A1 dashboard parking
      overlay shows distances changing in real time when you
      wave your hand at a sensor.
- [ ] With `modules.blinker_monitor: true`, grounding the left
      blinker input on pin 40 (line 202, PG10) flips the small
      display (:5003) to the left camera overlay (or placeholder
      if no camera is attached).

---

## Part 5 — Full bench run (real ignition GPIO)

At this point the rig has:

- A working X + kiosk auto-start from Part 2.
- Some or all of the sensors from Part 4 wired up.
- Optionally: the dongles from Part 3.

The only thing left to replace is the `/tmp/bcm_ignition_on` file
trigger — swap it for a real GPIO input so the rig behaves exactly
like the production car.

### 5.1 The two ignition inputs — pick one

The ignition watcher (`src/power/ignition_watcher.py`) reads
**two** GPIO inputs every 100 ms. Either of them can start / stop
BCM, and you only need to wire one.

| Input | Config key | OPi PC pin | H3 pin | libgpiod line | Behaviour |
|-------|-----------|-----------|--------|----------------|-----------|
| **Ignition line** (car 12 V via PC817) | `power.ignition_watcher.ignition_line` (default **7**) | Physical pin 29 | PA7 | 7 | **Level-triggered.** Holding the line LOW (= 12 V present on the PC817 input) keeps BCM ON. Releasing it shuts BCM down. |
| **Bench push button** (PC-style momentary) | `power.ignition_watcher.bench_button_line` (default **203**) | Physical pin 38 | PG11 | 203 | **Edge-triggered toggle.** Press once → BCM ON. Press again → BCM OFF. No optoisolator required, no 12 V supply needed. |

Both use `active_low: true` — the GPIO pin reads LOW when the
input is "active". You can wire both, only the bench button, or
only the ignition line.

> **Pin correction:** older drafts said the bench button was on
> physical pin 33 / PB5 / line 37. That was wrong — PB5 is not
> exposed on the OPi PC 40-pin header at all, so that wiring
> could never work. The correct default is physical pin 38 /
> PG11 / line 203.

### 5.2 Wire a PC-style push button (recommended for bench testing)

This is the quickest path to a production-equivalent rig: the
same kind of **two-pin momentary push button** you'd find on a
PC case power button. Wire one leg to **physical pin 38**
(PG11, libgpiod line 203) and the other leg to any GND pin on
the header (pin 6 / 9 / 14 / 20 / 25 / 30 / 34 / 39):

```
   OPi Pin 38 (PG11, line 203) ──┐
                                  │   [push button — normally open]
                                  │
   OPi Pin 39 (GND)           ────┘
```

**No pull-up resistor, no optoisolator, no 12 V** — the OPi PC
libgpiod request already configures `Bias.PULL_UP` inside
`ignition_watcher._start_gpio()` so the line sits at 3.3 V when
the button is open and drops to GND when pressed.

### 5.3 Wire the real ignition line (optional — mirrors car wiring)

Only needed if you also want to test the 12 V optoisolated path
that the car will actually use. Same pattern as all the other
PC817 inputs from §4.5:

```
    12 V signal ── [4.7 kΩ] ── PC817 anode
                                PC817 cathode ── GND

         3.3 V ── [10 kΩ] ── PC817 collector ──── OPi Pin 29 (PA7)
                             PC817 emitter   ── GND
```

Active-low: 12 V present on the input side pulls pin 29 LOW,
which the watcher sees as "ignition ON".

### 5.4 Switch the watcher from simulation to real GPIO

Nothing to change in the config — the watcher auto-detects real
GPIO as soon as `libgpiod` can open `gpiochip0`. Just remove any
stale simulation trigger file and restart the service:

```bash
sudo rm -f /tmp/bcm_ignition_on
sudo systemctl restart bcm-ignition-watcher
sudo journalctl -fu bcm-ignition-watcher
```

Expected log:

```
Ignition watcher started — waiting for ignition signal...
Opened GPIO chip: gpiochip0
Watching: ignition=line 7, button=line 203
```

If you see `SIMULATION MODE — ignition watcher`, libgpiod
couldn't open the chip. Check that `gpioinfo gpiochip0` returns
output and that `/tmp/bcm_ignition_on` isn't still present.

### 5.5 Test the full cycle

Press the PC-style button once:

```
Bench button pressed — ignition ON
=== IGNITION ON — Starting BCM headunit ===
Boot mode: cold
systemctl start bcm-headunit.service — OK
BCM headunit service started successfully
```

Within ~5 s the Chromium kiosk on `:5002` flips from
"connection refused" to the BCM dashboard (cold boot skips
the 4s init screen, goes straight to last screen).

Press the button **again** to stop BCM:

```
Bench button pressed — ignition OFF
=== IGNITION OFF — Stopping BCM headunit ===
systemctl stop bcm-headunit.service — OK
BCM headunit service stopped — OS stays in deep idle
```

`systemctl status bcm-headunit` should go from
`active (running)` to `inactive (dead)`. The OS stays running
(deep idle). Each subsequent press flips the state. The second
start will show `Boot mode: warm` (with 4s init screen).

**SWC toggle test (simulation mode):** From another terminal:

```bash
# While BCM is running — puts BCM in standby:
touch /tmp/bcm_swc_toggle

# While BCM is stopped — wakes BCM:
touch /tmp/bcm_swc_toggle
```

**12h timer test:** Set a short timeout in
`config/bcm_config_opi_pc.yaml`:

```yaml
power:
  standby_max_hours: 0.001    # 3.6 seconds for testing
  splash_duration_seconds: 3  # shorter splash for testing
```

Then: ignition ON → BCM starts (cold) → ignition OFF → wait
5s → ignition ON → splash plays 3s → BCM starts (cold-like,
skip init).

### 5.4 Part 5 checklist

- [ ] `systemctl is-enabled bcm-ignition-watcher` returns `enabled`.
- [ ] On boot, the watcher starts and logs `Opened GPIO chip`,
      `Standby window: 12h`, `Splash duration: 15s`.
- [ ] Pressing the bench button triggers a start / stop of
      `bcm-headunit` within ~1 s.
- [ ] First start shows `Boot mode: cold`. Second shows `warm`.
- [ ] `touch /tmp/bcm_swc_toggle` toggles BCM on/off (simulation).
- [ ] After ignition OFF, OS stays running (no poweroff).
- [ ] `/tmp/bcm_power_state` file exists with `boot_mode=` line.
- [ ] All Part 4 sensors still read correctly while BCM is running
      (no GPIO ownership conflicts).
- [ ] The rig can cycle through at least 10 ignition on/off events
      without a service failure or memory leak.

At the end of Part 5 the test rig behaves exactly like the
production head unit. Any bug you can still reproduce here is a
BCM bug, not a wiring or environment bug.

---

## Part 6 — Moving to the car

The OPi PC 1.2 is intentionally **not** the production target —
it's a cheap bench rig for validating everything before you spend
money on the real board. Once Part 5 passes end to end, migrate
to the Orange Pi 5 Pro 4 GB for the in-car install.

Everything you learned in Parts 1-5 carries over. The only
differences on the 5 Pro are:

- Dual HDMI (2.1 + 2.0) drives both 7" main and 4.3" small
  screens natively — no second X server trick needed.
- Hardware H.264 encoding (RK3588 VPU) for the dashcam.
- 4 GB RAM makes Android Auto comfortable with headroom to spare.
- Built-in WiFi 6 + BT 5.0 — no USB dongles.

The full install sequence for the 5 Pro is in
[`../orange-pi-5/OPI5PRO_SETUP.md`](../orange-pi-5/OPI5PRO_SETUP.md). Wiring reuses the Part 4
sensor topology verbatim — same PC817 optoisolators, same HC-SR04
voltage dividers, same DS18B20, same buzzer.

Bill of materials (with Q1 2026 PLN prices) for the production
build: [`../orange-pi-5/OPI5PRO_BOM.md`](../orange-pi-5/OPI5PRO_BOM.md).

---

## Part 6.5 — Optional: boot splash with audio

> ### ⚠ OPi PC cannot decode 720p video in software
>
> The Allwinner H3 is a 1.2 GHz quad-core Cortex-A7 with no
> hardware video decoder that mainline mpv knows how to drive
> by default. Software-decoding a 1024×600 H.264 MP4 with mpv
> runs at roughly **1–2 FPS** (the exact number users have seen
> on real OPi PC hardware is "1/16 framerate" — i.e. one frame
> every ~500 ms). This is useless for a boot splash.
>
> **Two fixes, pick one:**
>
> 1. **Use a small SD-resolution MP4.** Transcode your splash
>    to **640×360** (or 480×272) H.264 with the audio track
>    preserved. At that size the H3's software path manages
>    ~20–25 FPS which is enough. `ffmpeg` one-liner in the
>    "Prepare the video" subsection below.
>
> 2. **Enable cedrus hardware decode.** Armbian Trixie kernel
>    6.x ships the `sun4i-drm` + `cedrus` drivers in mainline.
>    mpv can offload H.264 to the cedrus v4l2m2m endpoint with
>    `--hwdec=v4l2m2m-copy`, which gets the full 25 FPS at
>    720p on real H3 silicon. Needs `v4l2-utils` and a kernel
>    that exposes `/dev/video0` as a v4l2m2m decoder node (run
>    `v4l2-ctl --list-devices` — you want "sun4i-decoder" or
>    "sunxi-cedrus").
>
> Both approaches are documented below. The 640×360 fallback is
> the safer first choice because it requires nothing beyond
> mpv and ffmpeg from the apt repo, and it works even on
> kernels where cedrus hasn't been wired up yet.
>
> The production **Orange Pi 5 Pro** does not have this problem
> — RK3588S has a hardware VPU that mpv uses via the rkmpp
> plugin, and full 1080p video plays at 60 FPS without any
> special flags. This caveat is OPi PC only.

By default Armbian prints a kernel boot log to the HDMI output
for ~12–15 s until `bcm-kiosk.service` opens Chromium. The user
sees a wall of `[  0.123] usb ...` text. To replace that with a
branded MP4 loop (video **+ audio** through the 3.5 mm jack),
drop one video file and install two systemd services.

> **OPi PC is the single-HDMI bench rig.** Only the "main"
> splash applies here — the small-display splash
> (`bcm-splash-small.service`) is a no-op because there's no
> second HDMI. Everything below installs both service files for
> consistency with the OPi 5 Pro build; the small one disables
> itself via `ConditionPathExists=` when `small.mp4` is absent.

### Prepare the video — keep it small

Transcode your source clip down to a size the H3 can actually
play. 640×360 H.264 + AAC at ~500 kbps is a good target:

```bash
# On your desktop / the OPi PC (ffmpeg is cheap)
ffmpeg -i INPUT.mov \
    -vf "scale=640:360" \
    -c:v libx264 -preset veryfast -crf 28 -maxrate 600k -bufsize 1M \
    -c:a aac -b:a 96k -ac 2 \
    -t 8 -movflags +faststart \
    main.mp4
```

The 8-second clip loops via `--loop-file=inf` so the viewer
doesn't care how long it is. Keep it under ~10 s so the loop
boundary isn't noticeable while waiting for ignition. The
frame will be upscaled to 1024×600 by the DRM scaler
automatically — a slightly soft image is a fair trade for
smooth playback on a 1 GB bench rig.

### Quick install

```bash
# 1. Drop your (640×360) MP4 file in
sudo mkdir -p /opt/bcm/assets/splash
sudo cp main.mp4 /opt/bcm/assets/splash/main.mp4
sudo chown -R $USER:$USER /opt/bcm/assets/splash

# 2. Make sure the ALSA mixer isn't muted (default on sun4i-codec)
sudo alsactl init
amixer set 'Line Out' unmute 85% || true
amixer set Master unmute 85% || true
sudo alsactl store

# 3. Install the systemd units shipped in the repo
cd /opt/bcm
sudo cp config/systemd/bcm-splash-main.service  /etc/systemd/system/
sudo cp config/systemd/bcm-splash-small.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable bcm-splash-main.service bcm-splash-small.service

# 4. Hide the kernel log (OPi PC uses /boot/armbianEnv.txt)
sudo sed -i '/^extraargs=/d' /boot/armbianEnv.txt
echo 'extraargs=quiet loglevel=3 vt.global_cursor_default=0' | \
    sudo tee -a /boot/armbianEnv.txt

sudo reboot
```

After reboot the HDMI output + 3.5 mm jack goes:

1. U-Boot (~1 s of unavoidable serial text)
2. Kernel loads silently
3. `bcm-splash-main.service` starts `mpv` → your MP4 loops on
   the HDMI output **and** the audio track plays through the
   3.5 mm headphone jack / amplifier
4. Ignition watcher waits for the button press or file trigger
5. Ignition ON → `bcm-headunit.service` starts → Chromium kiosk
   opens → splash mpv is killed by `PartOf=bcm-headunit.service`,
   releasing both the framebuffer and the ALSA device
6. BCM dashboard visible, normal PipeWire audio pipeline takes
   over the card

### Quick audio smoke test (before the first reboot)

```bash
# Verify ALSA sees the sun4i-codec
aplay -l
speaker-test -c 2 -t wav -l 1

# Verify mpv plays audio + video to HDMI-A-1 as root (exactly
# what the systemd unit does)
sudo mpv --vo=drm --drm-connector=HDMI-A-1 \
    --ao=alsa,pipewire,pulse \
    --fs --loop-file=inf --really-quiet \
    /opt/bcm/assets/splash/main.mp4
```

Press `Ctrl+C` to exit. If the video plays but there's no
sound, see the "no sound from splash" entry in Part 7. If the
video plays at 1–2 FPS you either skipped the 640×360
transcode step above or you're on a kernel without cedrus —
read the next subsection.

### Optional: hardware decode via cedrus (v4l2m2m)

If you want 720p or larger video on the OPi PC, the H3's
built-in cedrus video decoder has to do the work — software
decoding on 4× Cortex-A7 @ 1.2 GHz simply isn't fast enough.

Check whether cedrus is exposed as a v4l2m2m node:

```bash
sudo apt install -y v4l-utils
v4l2-ctl --list-devices
# Expect something like:
#   sun4i-codec (platform:1c22c00.codec):
#     /dev/video0
#   sun4i-csi (platform:1cb0000.csi):
#     /dev/video1
```

If the list includes a node labelled `sun4i-codec`, `cedrus`,
or `sunxi-cedrus`, mpv can use it via its v4l2m2m hwdec path:

```bash
sudo mpv --vo=drm --drm-connector=HDMI-A-1 \
    --hwdec=v4l2m2m-copy \
    --ao=alsa,pipewire,pulse \
    --fs --loop-file=inf --really-quiet \
    /opt/bcm/assets/splash/main.mp4
```

Watch `journalctl -f` while it runs — if mpv logs `Using
hardware decoding (v4l2m2m-copy)` you're getting accelerated
decode. If it falls back to `Software decoding` the kernel
doesn't have cedrus wired up on this image; stay with the
640×360 software path.

To make the systemd service use hwdec, edit
`/etc/systemd/system/bcm-splash-main.service` and add
`--hwdec=v4l2m2m-copy` to the `ExecStart` shim's mpv flag
list, then `sudo systemctl daemon-reload && sudo systemctl
restart bcm-splash-main`. The change is purely local — the
repo's shipped unit file stays at the safer software-decode
default because cedrus availability varies between Armbian
builds.

### DRM connector name — fixing the wrong HDMI on the OPi PC

The H3's mainline DRM driver names its one HDMI output
`HDMI-A-1` on most kernels, which matches the default in
`bcm-splash-main.service`. If your kernel exposes something
different, `ls /sys/class/drm/` lists the actual name — pick
whatever comes after `card0-` and edit the `--drm-connector=`
flag in `/etc/systemd/system/bcm-splash-main.service`.

See [`../orange-pi-5/OPI5PRO_SETUP.md`](../orange-pi-5/OPI5PRO_SETUP.md) §10 for the full
dual-display version of this recipe, the deeper audio
troubleshooting section, and a transcoding one-liner for
creating a properly-sized, loop-friendly `main.mp4` with an
AAC audio track.

---

## Part 7 — Troubleshooting

### X server won't start

**`startx: command not found`**
  → `xinit` package missing. Re-run the §1.4 apt install line.

**`Only console users are allowed to run the X server`**
  → §1.5 wasn't applied. Edit `/etc/X11/Xwrapper.config` and set
  `allowed_users=anybody`. Log out and back in.

**`no screens found`**
  → Missing `xserver-xorg-video-fbdev`. Reinstall the §1.4 set.
  If HDMI still isn't detected, check `/boot/armbianEnv.txt` has
  `console=both` and the HDMI cable was connected before power-on.

**`Failed to load module matchbox-window-manager`**
  → `matchbox-window-manager` package not installed. Same fix.

### BCM launcher

**`./run_opi_pc.sh: command not found`**
  → Forgot `chmod +x` after `git clone` on a filesystem that
  doesn't preserve permissions. Run `chmod +x run_opi_pc.sh`.

**`ImportError: No module named gpiod`**
  → On Debian Trixie BCM uses the apt-installed `python3-libgpiod`
  (not pip) because the pip `gpiod>=2.0` package won't build from
  source against Python 3.13 headers. If you see this error,
  either the apt package is missing or the venv wasn't created
  with `--system-site-packages`:
  ```bash
  sudo apt install -y python3-libgpiod libgpiod-dev gpiod
  cd /opt/bcm
  rm -rf .venv
  python3 -m venv --system-site-packages .venv
  source .venv/bin/activate
  pip install -r requirements.txt -r requirements-opi-pc.txt
  python3 -c "import gpiod; print(gpiod.__version__)"
  ```

**`E: Unable to locate package libgpiod2`** (from the old setup guide)
  → The package was renamed between Debian Bookworm and Trixie.
  On Trixie the runtime library is `libgpiod3` and the Python
  binding is `python3-libgpiod`. Install both via `libgpiod-dev`
  (meta-package that pulls the right runtime) + `python3-libgpiod`:
  ```bash
  sudo apt install -y libgpiod-dev python3-libgpiod gpiod
  ```

**`Failed to request lines: Device or resource busy`**
  → Another process already owns the GPIO. Usually
  `bcm-ignition-watcher` started from a previous run. Stop it:
  `sudo systemctl stop bcm-ignition-watcher`.

### pip install fails

**`Failed to build opencv-python-headless`** / `skbuild`, `cmake`,
or `ninja` error during pip install
  → You're on the OPi PC (armv7l) and pip is trying to build
  OpenCV from source because PyPI has no pre-built wheel for this
  architecture. This **should not happen** with a fresh
  `requirements-opi-pc.txt` checkout (opencv was dropped from it
  in commit `ccb8761` and the file explicitly explains why).
  If it does, you probably have an older copy of the file — `git
  pull` and try again, or install via apt:
  ```bash
  sudo apt install -y python3-opencv
  cd /opt/bcm
  rm -rf .venv
  python3 -m venv --system-site-packages .venv
  source .venv/bin/activate
  pip install -r requirements.txt -r requirements-opi-pc.txt
  ```

**`Failed to build Pillow`** / missing `zlib.h`, `jpeglib.h`, etc.
  → Same story — Pillow is not a required OPi PC dep, use
  `sudo apt install -y python3-pil` plus `--system-site-packages`
  as above.

**`Failed to build spidev`** / `Python.h: No such file or directory`
  or `error: unknown type name 'PyObject'` against Python 3.13
  → spidev is NOT required for the desk test (Parts 1-2) or for any
  currently-shipping BCM module; it's listed as a stub in
  `src/core/hal.py::RealSPI` for future MCP3008 SWC decoder use. If
  you need it later (Part 4+), install via apt and recreate the
  venv with `--system-site-packages`:
  ```bash
  sudo apt install -y python3-spidev python3-smbus
  cd /opt/bcm
  rm -rf .venv
  python3 -m venv --system-site-packages .venv
  source .venv/bin/activate
  pip install -r requirements.txt -r requirements-opi-pc.txt
  ```

**`Failed to build` a C-extension package** / `sdl-config: command not found`
  → You accidentally installed `requirements-x86.txt`. Rebuild the
  venv and only install `requirements.txt` + `requirements-opi-pc.txt`.

**`error: externally-managed-environment`** (Debian Trixie)
  → You ran `pip install` outside a virtual environment. Always
  `source .venv/bin/activate` first. Never `sudo pip install`
  anything.

### Chromium / kiosk

**Chromium opens but shows a blank page**
  → Flask isn't up yet. Confirm with `curl http://localhost:5002`
  from another terminal first. In the kiosk path, `.xinitrc` waits
  for `/5002` to answer before spawning Chromium.

**Chromium opens but doesn't go full-screen**
  → Matchbox window manager isn't running. `pgrep matchbox-window-manager`
  should return a PID. If not, the `.xinitrc` from §2.3 didn't run
  properly — check `~/.xsession-errors`.

**Android Auto canvas is too big and overlaps AppBar / NavBar**
  → Stale `openauto.ini`. Delete it and restart BCM:
  ```
  rm -f /opt/bcm/openauto.ini
  sudo systemctl restart bcm-headunit
  grep Touchscreen /opt/bcm/openauto.ini
  # Expect TouchscreenWidth=1024 / TouchscreenHeight=504
  ```
  Cross-reference: `../orange-pi-5/OPI5PRO_SETUP.md` §10 has the full
  explanation of the AA canvas-sizing mechanism.

### Audio (sun4i-codec)

**No sound from `aplay -l`**
  → On kernel 6.x the sun4i-codec driver needs `asound.state` to
  be initialised. Run `sudo alsactl init sun4i-codec` and retry.
  Also check `amixer -c 0` — the `Line Out` mixer is muted by
  default on some Armbian builds:
  ```
  amixer -c 0 sset 'Line Out' unmute
  amixer -c 0 sset 'Line Out' 80%
  ```

**PipeWire reports no default sink**
  → `systemctl --user status pipewire wireplumber`. If they aren't
  running, `systemctl --user enable --now pipewire wireplumber`.
  Remember PipeWire runs per-user, not as root.

**Boot splash video plays on HDMI but there's no sound at all**
  → The splash service runs as root before PipeWire is up and
  opens ALSA directly. If ALSA's default mixer state ships muted
  (common on sun4i-codec), `mpv` will happily write silence to
  the device. Fix once:
  ```
  sudo alsactl init
  amixer -c 0 sset 'Line Out' unmute 85%
  amixer -c 0 sset Master    unmute 85%  2>/dev/null || true
  sudo alsactl store
  sudo systemctl restart bcm-splash-main
  ```
  `speaker-test -c 2 -t wav -l 1` should now produce an audible
  tone on the 3.5 mm jack. The state is persisted to
  `/var/lib/alsa/asound.state`, so the next boot will pick it up
  automatically.

**Splash video + audio play, but stutter every 5 s**
  → The `main.mp4` audio track is not a seamless loop. Either
  re-encode with a 1–2 frame silent fade at the boundary, or use
  a shorter one-shot jingle and accept that it will repeat until
  ignition fires and BCM takes over. See OPI5PRO_SETUP.md §10.1
  for a loop-friendly `ffmpeg` one-liner.

**Splash video plays at ~1 FPS (slideshow)**
  → The Allwinner H3 cannot decode 720p H.264 in software in
  real time. Either transcode `main.mp4` down to 640×360
  (Part 6.5 "Prepare the video — keep it small"), or switch to
  hardware decode via cedrus v4l2m2m (Part 6.5 "Optional:
  hardware decode via cedrus"). Do NOT try to solve this by
  raising `mpv --hwdec=auto` — mpv's auto path on armv7l
  doesn't pick cedrus and will stay on software decode.

**`bcm-splash-main.service` status=0 but nothing happens on the
display**
  → The mpv shim exited immediately because
  `/opt/bcm/assets/splash/main.mp4` didn't exist (the service
  has `ConditionPathExists=` so it silently no-ops). Check the
  file is in place and readable by root:
  ```
  sudo ls -l /opt/bcm/assets/splash/main.mp4
  sudo systemctl restart bcm-splash-main
  sudo journalctl -u bcm-splash-main -n 20
  ```

### LTE modem

**`lsusb` shows `12d1:1f01` forever**
  → `usb_modeswitch` isn't running automatically. Force it once:
  `sudo usb_modeswitch -v 12d1 -p 1f01 -J`. If the mode doesn't
  stick across reboots, add the udev rule shipped with
  `usb-modeswitch-data` (`dpkg -L usb-modeswitch-data | grep
  40-usb_modeswitch.rules`).

**`ping -I usb0 8.8.8.8` returns "Destination Host Unreachable"**
  → HiLink mode DHCP didn't complete. Check `ip addr show usb0` —
  if there's no IPv4 address, run `sudo nmcli connection up huawei-lte`
  again. If the dongle is in storage mode (§3.6 Step 2 failed),
  ping will never work.

### Memory pressure (1 GB RAM)

**OOM killer takes down `bcm-headunit`**
  → Disable `modules.multimedia` in
  `config/bcm_config_opi_pc.yaml` — Android Auto is the
  biggest consumer. Add a 512 MB swap file as a safety net:
  ```
  sudo fallocate -l 512M /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
  ```

**`free -h` shows `Swap` growing by the minute**
  → One of the modules is leaking. Most likely suspects are
  `camera` (if `opencv-python` is loaded but no camera is
  attached) and `weather` (if the OpenWeatherMap API key is
  invalid and the retry loop keeps allocating JSON objects).
  Check with `sudo journalctl -fu bcm-headunit`.

### CPU temperature

**`thermal_zone0/temp` climbs past 85 °C**
  → Add a small heatsink. The H3 aggressively throttles at 90 °C,
  which causes visible UI stutter and Chromium frame drops. A
  cheap 14×14 mm aluminium heatsink is enough for idle use.
