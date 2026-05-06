# BCM boot splash videos

Drop two MP4 files in here to replace the Armbian / Ubuntu kernel
boot log with a branded BCM startup animation:

| File | Target display | Audio? | Suggested format |
|------|----------------|--------|------------------|
| `main.mp4`  | Main 7"/10" touchscreen | **Yes — plays through the car audio system during boot** | 1024×600 or 1280×800, 5–10 s seamless loop, H.264 video + AAC/MP3 audio track |
| `small.mp4` | Small 4.3" stats display — breathing Alfa Romeo logo | No (silent) | 800×480, 3–5 s loop, no audio track, H.264 |

**DRM connector names vary by platform:**
- OPi 5 Pro (2× HDMI): `HDMI-A-1` (main), `HDMI-A-2` (small)
- Lenovo M910q (2× DP): `DP-1` (main), `DP-2` (small) — use passive DP-to-HDMI adapters for HDMI displays
- GA-N3050N-D2P (HDMI+VGA): `HDMI-1` (main), `DP-2` (VGA/small)
- Discover yours: `for f in /sys/class/drm/card*-*/status; do echo "$f: $(cat $f)"; done`

Both are picked up by the two systemd services at
`config/systemd/bcm-splash-main.service` and
`config/systemd/bcm-splash-small.service`, which
`mpv --vo=drm --drm-connector=HDMI-A-{1,2}` the respective file
full-screen on the correct DRM connector the moment systemd
reaches `multi-user.target`, and hand over to Chromium when
`bcm-kiosk.service` takes the framebuffer.

## Audio on `main.mp4`

The main splash service opens the sound card directly through
ALSA via `mpv --ao=alsa,pipewire,pulse`. At boot time no user
session is active yet, so PipeWire and Pulse are normally not
running — mpv picks ALSA, opens `/dev/snd/` as root (the unit
runs in the `audio` supplementary group), and plays the audio
track embedded in `main.mp4`.

When `bcm-headunit.service` later starts (on ignition), the
splash service is killed via its `PartOf=` directive, mpv
releases the ALSA device cleanly, and the normal BCM audio
pipeline (PipeWire → amp → car speakers) takes over.

Tips for `main.mp4` audio:
- Keep the total clip ~5–10 s so it loops seamlessly while the
  viewer waits for ignition ON.
- Match the loop boundary in both video and audio (silent
  fade-in / fade-out works well).
- Normalise the audio at ~-14 LUFS so the startup jingle isn't
  jarringly louder than ambient car audio.
- `ffmpeg -i in.mov -c:v libx264 -c:a aac -b:a 128k -ac 2
     -t 8 -vf "scale=1024:600" -movflags +faststart main.mp4`
  is a reasonable one-liner to transcode from any source.

If the file is missing the matching systemd service no-ops via
`ConditionPathExists=` so nothing breaks; the boot just falls
back to the normal kernel log and the init splash embedded in
the Flask frontend takes over ~3 s after Chromium opens.

**Neither file is shipped in this repo** — they're user-supplied
branding.

See [`docs/OPI5PRO_SETUP.md`](../../docs/OPI5PRO_SETUP.md) §10
for the full setup recipe including the kernel
`quiet loglevel=3` flags that hide Linux's own boot output so
only the MP4 (with audio) is visible from power-on.
