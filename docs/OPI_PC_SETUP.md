# Orange Pi PC 1.2 — Setup & Testing Manual

Bench test rig for the Alfa 156 BCM head unit, built around the
**Orange Pi PC 1.2** (Allwinner H3, 1 GB RAM, armv7l) running
**Armbian Trixie** (Debian 13, kernel ≥ 6.18). The rig is meant as
a cheap pre-production sanity check before committing to the
production board — see [`OPI5PRO_SETUP.md`](OPI5PRO_SETUP.md) for
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
  libgpiod2 libgpiod-dev gpiod \
  pipewire pipewire-alsa wireplumber \
  bluez blueman \
  v4l-utils ffmpeg \
  gstreamer1.0-tools gstreamer1.0-plugins-good \
  usb-modeswitch usb-modeswitch-data \
  i2c-tools
```

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
  chromium xdotool
```

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

```bash
sudo mkdir -p /opt
cd /opt
sudo git clone https://github.com/geek95dg/Alfa156-headunit.git bcm
sudo chown -R $USER:$USER /opt/bcm
cd /opt/bcm

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt -r requirements-opi-pc.txt
```

Sanity-check that every runtime import succeeds — this catches
missing `libgpiod2` or `python3-dev` early:

```bash
python3 -c "import gpiod, yaml, flask, flask_sock, serial; print('ok')"
```

If you see `ImportError: No module named gpiod` even though the
apt package is installed, your venv was created before libgpiod2
landed — rebuild it: `rm -rf .venv && python3 -m venv .venv`.

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
  -e 's/^  voice: .*/  voice: false/' \
  config/bcm_config_opi_pc.yaml

grep -E 'multimedia:|network:|voice:' config/bcm_config_opi_pc.yaml
# Expect all three to read `false`.
```

Leave `obd`, `parking`, `environment`, `audio`, `camera`, `power`,
`location`, `weather`, `input` and `dashboard` on their defaults —
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
- [ ] `gpioinfo gpiochip0` lists PA lines (libgpiod2 works).
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

Within ~1 second the watcher starts `bcm-headunit.service`, which
starts the Flask servers on :5002/:5003, which `bcm-kiosk.service`
then connects to. The Chromium windows flip from "connection refused"
to the init splash → A1 Dashboard.

Simulate ignition OFF:

```bash
sudo rm /tmp/bcm_ignition_on
```

`bcm-headunit.service` and `bcm-kiosk.service` stop cleanly. The
Chromium windows stay open but show a connection error again, which
is exactly the intended behaviour in car — the display stays lit
but BCM is unloaded to save RAM.

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

# Capture one frame
ffmpeg -f v4l2 -video_size 640x480 -i /dev/video0 -frames 1 /tmp/test.jpg
ls -l /tmp/test.jpg
```

In `config/bcm_config_opi_pc.yaml` the front camera already
defaults to `/dev/video0`, so BCM picks it up automatically. In
the running dashboard you should see a preview whenever the
camera module is active.

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

Pin map (from `config/bcm_config_opi_pc.yaml`):

| Sensor | Role | OPi physical pin | H3 line | Config key |
|--------|------|------------------|---------|------------|
| Shared | TRIG | 16 | PC4 (68) | `gpio.parking_trig` |
| #1     | ECHO LL | 18 | PC7 (71) | `gpio.parking_echo[0]` |
| #2     | ECHO CL | 22 | PA2 (2) | `gpio.parking_echo[1]` |
| #3     | ECHO CR | 24 | PA3 (3) | `gpio.parking_echo[2]` |
| #4     | ECHO RR | 26 | PA21 (21) | `gpio.parking_echo[3]` |

**Wiring verification — each sensor, one at a time:**

```bash
# Fire the TRIG pulse manually
gpioset --mode=time --sec=0 --usec=10 gpiochip0 68=1
# Read the ECHO line
gpioget gpiochip0 71
```

If you see a `1` briefly after a TRIG pulse (object in front of
the sensor), the divider is correct. Repeat for lines 2, 3, 21.

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
directly. A BC547 NPN on a 1 kΩ base resistor does the job:

```
 OPi Pin 12 (PD14, line 110) ── [1 kΩ] ── BC547 base
                                            BC547 emitter ── GND
                                            BC547 collector ── Buzzer (-)
                                                               Buzzer (+) ── 5 V
                                [1N4148 across the buzzer, cathode to +5 V]
```

Smoke test:

```bash
gpioset gpiochip0 110=1 ; sleep 0.3 ; gpioset gpiochip0 110=0
# You should hear a short beep.
```

### 4.5 Ignition / door / blinker inputs via PC817 optoisolators

Every 12 V vehicle signal BCM reads is isolated via a PC817.
Identical pattern for all of them — ignition (PA7), door (PA8),
rain sensor (PA19), central lock (PA20), left blinker (PA10),
right blinker (PA11):

```
 12 V signal ── [4.7 kΩ] ── PC817 anode (pin 1)
                             PC817 cathode (pin 2) ── GND

        3.3 V ── [10 kΩ] ── PC817 collector (pin 4) ──── OPi GPIO line
                            PC817 emitter  (pin 3) ── GND
```

Active-low: when 12 V is present on the input side, PC817 pulls
the OPi line LOW.

Verify ignition wiring (no 12 V connected → line reads HIGH; add
a test jumper from 12 V to the PC817 input → line reads LOW):

```bash
gpioget gpiochip0 7        # ignition, PA7
gpioget gpiochip0 8        # door, PA8
gpioget gpiochip0 10       # blinker left, PA10
gpioget gpiochip0 11       # blinker right, PA11
```

For bench testing without 12 V, you can also short each PC817
input to GND with a jumper — same effect.

### 4.6 Re-enable modules in the config

Back in §1.8 you turned off `multimedia`, `network`, and `voice`.
Parking / environment / camera are already `true` by default.
Once the wiring is verified, enable the blinker monitor:

```bash
sed -i 's/^  blinker_monitor: false.*/  blinker_monitor: true/' \
    config/bcm_config_opi_pc.yaml
```

If you want to test the multi-camera priority logic, also set
`camera.controller: true`. Leave `multimedia` and `voice` off on
the 1 GB test rig — the H3 doesn't have the RAM for them when
anything else is running.

### 4.7 Part 4 checklist

- [ ] `/sys/bus/w1/devices/28-*/temperature` returns millidegrees.
- [ ] `gpioget gpiochip0 71/2/3/21` reads individual HC-SR04 ECHOs.
- [ ] `gpioset gpiochip0 110=1` produces an audible beep.
- [ ] `gpioget gpiochip0 7` flips from 1 to 0 when you short the
      ignition PC817 input.
- [ ] With `modules.parking: true`, the A1 dashboard parking
      overlay shows distances changing in real time when you
      wave your hand at a sensor.
- [ ] With `modules.blinker_monitor: true`, grounding the left
      blinker input flips the small display (:5003) to the left
      camera overlay (or placeholder if no camera is attached).

---

## Part 5 — Full bench run (real ignition GPIO)

At this point the rig has:

- A working X + kiosk auto-start from Part 2.
- Some or all of the sensors from Part 4 wired up.
- Optionally: the dongles from Part 3.

The only thing left to replace is the `/tmp/bcm_ignition_on` file
trigger — swap it for a real GPIO line so the rig behaves exactly
like the production car.

### 5.1 Wire a bench button on PA7 (ignition)

A single momentary push button between physical pin 29 (PA7)
and GND, plus the standard PC817 pattern from §4.5 if you want
to test the 12 V side too.

For a pure bench button (no optoisolator):

```
OPi Pin 29 (PA7) ──┬── button ── GND
                    └── [10 kΩ pull-up] ── 3.3 V
```

The ignition watcher is `active_low: true` in the config, so
pressed = GND = line LOW = ignition ON.

### 5.2 Switch the watcher from simulation to real GPIO

Nothing to change in the config — the watcher auto-detects real
GPIO. Just remove any stale trigger file and restart the service:

```bash
sudo rm -f /tmp/bcm_ignition_on
sudo systemctl restart bcm-ignition-watcher
sudo journalctl -fu bcm-ignition-watcher
```

Expected log:

```
Ignition watcher started — waiting for ignition signal...
Opened GPIO chip: gpiochip0
Watching: ignition=line 7, button=line 37
```

### 5.3 Test the full cycle

Press the bench button once:

```
=== IGNITION ON — Starting BCM headunit ===
systemctl start bcm-headunit.service — OK
BCM headunit service started successfully
```

Release the button and watch the Chromium kiosk on :5002 load
the dashboard. Press again to trigger the ignition-OFF shutdown
sequence. `systemctl status bcm-headunit` should go from
`active (running)` to `inactive (dead)`.

### 5.4 Part 5 checklist

- [ ] `systemctl is-enabled bcm-ignition-watcher` returns `enabled`.
- [ ] On boot, the watcher starts and logs `Opened GPIO chip`.
- [ ] Pressing the bench button triggers a start / stop of
      `bcm-headunit` within ~1 s.
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
- 4 GB RAM makes Android Auto + Vosk comfortable.
- Built-in WiFi 6 + BT 5.0 — no USB dongles.

The full install sequence for the 5 Pro is in
[`OPI5PRO_SETUP.md`](OPI5PRO_SETUP.md). Wiring reuses the Part 4
sensor topology verbatim — same PC817 optoisolators, same HC-SR04
voltage dividers, same DS18B20, same buzzer.

Bill of materials (with Q1 2026 PLN prices) for the production
build: [`OPI5PRO_BOM.md`](OPI5PRO_BOM.md).

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
  → `libgpiod2` / `libgpiod-dev` wasn't installed before you ran
  `python3 -m venv .venv`. Fix: install the apt package, then
  `rm -rf .venv && python3 -m venv .venv && source .venv/bin/activate
  && pip install -r requirements.txt -r requirements-opi-pc.txt`.

**`Failed to request lines: Device or resource busy`**
  → Another process already owns the GPIO. Usually
  `bcm-ignition-watcher` started from a previous run. Stop it:
  `sudo systemctl stop bcm-ignition-watcher`.

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
  Cross-reference: `docs/OPI5PRO_SETUP.md` §10 has the full
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
  → Disable `modules.multimedia` and `modules.voice` in
  `config/bcm_config_opi_pc.yaml` — Android Auto + Vosk are the
  two biggest consumers. Add a 512 MB swap file as a safety net:
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
