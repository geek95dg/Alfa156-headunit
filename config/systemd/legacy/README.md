# Legacy systemd service units (BCM v7 era)

These six service files date from the original BCM v7 design where
every module ran in its own Python process with its own systemd
service and the modules talked to each other over Unix sockets.

**They are no longer used.** BCM v8 / v8.5 consolidated everything
into a single `main.py --frontend` process controlled by three
services at `../`:

- `bcm-ignition-watcher.service`  — boots on startup, watches the
  GPIO / file trigger, decides when BCM should be running
- `bcm-headunit.service`          — the `main.py --frontend` process
  that runs the Flask servers on :5002 and :5003 with every module
  in-process and the event bus shared between them
- `bcm-kiosk.service`             — Chromium in kiosk mode on :0,
  pinned to `bcm-headunit.service` via `BindsTo=`

The files in this directory are kept only as historical reference.
**Do not install or enable them.** If you run
`sudo cp config/systemd/*.service /etc/systemd/system/` the shell
glob will not descend into this directory, so these files are
safely ignored.

---

## Why they're broken today

Every file in this folder references code paths that no longer exist
or that only work in the old per-module deployment:

| File | What it does | Why it's broken |
|------|--------------|-----------------|
| `bcm-power.service` | starts a standalone `src.power.service` module | the power code is now loaded in-process by main.py |
| `bcm-dashboard.service` | starts `src.dashboard.renderer --service` (pygame) | pygame isn't installed on OPi PC / 5 Pro, and `--frontend` renders via Flask instead |
| `bcm-obd.service` | starts a standalone OBD reader | OBD is a module inside main.py now |
| `bcm-dashcam.service` | starts the dashcam in its own process | dashcam is part of the camera module inside main.py |
| `bcm-multimedia.service` | standalone OpenAuto controller | multimedia module is inside main.py |

If you need the v7-style split architecture (e.g. for a headless
multi-board setup), copy these files out of `legacy/` and fix them
up — but the supported deployment for every current target board
uses the three services at the parent directory.
