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
