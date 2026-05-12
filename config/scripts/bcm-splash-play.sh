#!/bin/bash
# Boot splash player — mpv on the main connector.
#
# Reverted from the gst-launch dual-kmssink experiment (which tried to
# black out the small connector via a second branch). On baremetal that
# pipeline failed to publish a frame and the user just saw a black main
# screen until xinit took over. mpv with --vo=drm on the main connector
# is the known-good path; the small connector stays as the kernel's
# default framebuffer until X starts.
#
# Exit conditions:
#   • /api/ready posted by App.init (kiosk painted) → exit immediately
#   • Flask root responding for ≥ FLASK_GATE_SECONDS without /api/ready
#     → exit so X can take DRM master from us
#   • MAX_WAIT seconds elapsed → hard ceiling

set -u

VIDEO=${BCM_SPLASH_VIDEO:-/opt/bcm/assets/splash/main.mp4}
CONN_MAIN=${BCM_SPLASH_DRM_MAIN:-HDMI-A-1}
MIN_SECONDS=${BCM_SPLASH_MIN_SECONDS:-0}
READY_URL=${BCM_SPLASH_READY_URL:-http://localhost:5002/api/ready}
FALLBACK_URL=${BCM_SPLASH_FALLBACK_URL:-http://localhost:5002}
CARD=${BCM_SPLASH_CARD:-/dev/dri/card0}
MAX_WAIT=${BCM_SPLASH_MAX_WAIT:-60}
FLASK_GATE_SECONDS=${BCM_SPLASH_FLASK_GATE_SECONDS:-12}

log() { echo "[bcm-splash] $*"; }

# Wait for /dev/dri/card0 to appear — boots can race kmsdrm.
for _ in $(seq 1 100); do
    [ -e "$CARD" ] && break
    sleep 0.1
done
if [ ! -e "$CARD" ]; then
    log "DRM device $CARD not found; skipping splash"
    exit 0
fi
if [ ! -r "$VIDEO" ]; then
    log "splash video $VIDEO not found; skipping"
    exit 0
fi

PLAYER_PID=""
start_player() {
    if ! command -v mpv >/dev/null; then
        log "mpv not installed; cannot show splash"
        return 1
    fi
    log "splash: mpv on $CONN_MAIN ($VIDEO)"
    # mpv 0.40 removed --drm-atomic (atomic is now the default and the
    # option is rejected as unknown — that's what was killing the splash
    # at the very first frame). Keep --vo=drm + --drm-connector only.
    mpv --fs --loop-file=inf --no-audio --vo=drm \
        --drm-connector="$CONN_MAIN" --input-conf=/dev/null \
        --msg-level=all=warn "$VIDEO" >/tmp/bcm-splash-mpv.log 2>&1 &
    PLAYER_PID=$!
    return 0
}

stop_player() {
    [ -z "${PLAYER_PID:-}" ] && return
    kill "$PLAYER_PID" 2>/dev/null || true
    pkill -P "$PLAYER_PID" 2>/dev/null || true
    pkill -f "mpv.*$VIDEO" 2>/dev/null || true
    wait "$PLAYER_PID" 2>/dev/null || true
}

trap 'stop_player; exit 0' TERM INT

if ! start_player; then
    exit 0
fi

sleep 1
if [ -n "${PLAYER_PID:-}" ] && ! kill -0 "$PLAYER_PID" 2>/dev/null; then
    log "splash player exited immediately; check connectors / DRM"
    exit 0
fi

# Two-stage gate:
#   1. /api/ready (App.init posts to this once Chromium has rendered)
#       → exit immediately, no padding.
#   2. Flask root has been responding for ≥ FLASK_GATE_SECONDS without
#      /api/ready firing → exit anyway, so the x86 .bash_profile can
#      hand DRM master over to X and let Chromium take the screen.
#   3. Hard MAX_WAIT ceiling so a wedged Flask never wedges splash.
start_ts=$(date +%s)
flask_up_since=0
while true; do
    now=$(date +%s)
    elapsed=$(( now - start_ts ))

    if curl -sf "$READY_URL" >/dev/null 2>&1; then
        if [ "$elapsed" -lt "$MIN_SECONDS" ]; then
            sleep $(( MIN_SECONDS - elapsed ))
        fi
        log "kiosk ready after ${elapsed}s — exiting splash"
        break
    fi

    if curl -sf "$FALLBACK_URL" >/dev/null 2>&1; then
        if [ "$flask_up_since" = "0" ]; then
            flask_up_since=$now
            log "Flask up after ${elapsed}s — waiting up to ${FLASK_GATE_SECONDS}s for kiosk readiness"
        elif [ $(( now - flask_up_since )) -ge "$FLASK_GATE_SECONDS" ]; then
            log "kiosk readiness gate (${FLASK_GATE_SECONDS}s) elapsed — exiting splash so X can take over"
            break
        fi
    fi

    if [ "$elapsed" -ge "$MAX_WAIT" ]; then
        log "max wait ${MAX_WAIT}s reached — exiting splash"
        break
    fi
    sleep 1
done

stop_player
exit 0
