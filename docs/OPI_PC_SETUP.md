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
