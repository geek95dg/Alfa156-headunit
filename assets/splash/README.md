# BCM boot splash videos

Drop two MP4 files in here to replace the Armbian / Ubuntu kernel
boot log with a branded BCM startup animation:

| File | Target display | Suggested format |
|------|----------------|------------------|
| `main.mp4`  | Main 7" / 8" touchscreen (HDMI 2.1, `HDMI-A-1`) | 1024×600 or 1280×800, 5–10 s loop, no audio, H.264 |
| `small.mp4` | Small 4.3" stats display (HDMI 2.0, `HDMI-A-2`) — breathing Alfa Romeo logo | 800×480, 3–5 s loop, no audio, H.264 |

Both are picked up by the two systemd services at
`config/systemd/bcm-splash-main.service` and
`config/systemd/bcm-splash-small.service`, which `mpv --vo=drm`
the respective file full-screen on the correct DRM connector
the moment systemd reaches `multi-user.target`, and hand over
to Chromium when `bcm-kiosk.service` is up.

**Neither file is shipped in this repo** — they're user-supplied
branding. When the files are missing the services no-op via
`ConditionPathExists` so nothing breaks; the boot just falls
back to the normal kernel log and the init splash embedded in
the Flask frontend takes over ~3 s later.

See `docs/OPI5PRO_SETUP.md` §11 (new) for the full setup recipe
including the kernel `quiet loglevel=3` flags that hide Linux's
own boot output so only the MP4 is visible from power-on.
