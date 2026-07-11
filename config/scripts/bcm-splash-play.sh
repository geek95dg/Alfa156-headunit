#!/bin/bash
# Boot splash player.
#
# Plays the splash video on EVERY connected DRM connector from a SINGLE
# process. card0 has one DRM master at a time, so two players (two mpv,
# or the old gst-vs-mpv fight) can never coexist — exactly what made the
# previous dual-screen attempts go black. The rules here:
#
#   • Connectors are AUTO-DETECTED from /sys/class/drm — we never hardcode
#     a connector again. The old config pinned HDMI-A-1, which is
#     DISCONNECTED on the M910q (the panel is on HDMI-A-2), so mpv hit
#     "Chosen connector is disconnected" and the splash silently vanished.
#   • One connected connector  → mpv --drm-connector=<name> (known-good,
#     loops natively).
#   • Two+ connected connectors → ONE gst-launch pipeline: decode once,
#     tee, one kmssink per connector. Same frame on every screen, one
#     DRM master. Falls back to mpv on the primary connector if gst can't
#     start, so a bad pipeline never leaves the main screen black.
#
# Exit conditions (unchanged):
#   • /api/ready posted by App.init (kiosk painted) → exit immediately
#   • Flask root responding for ≥ FLASK_GATE_SECONDS without /api/ready
#     → exit so X can take DRM master from us
#   • MAX_WAIT seconds elapsed → hard ceiling

set -u

VIDEO=${BCM_SPLASH_VIDEO:-/opt/bcm/assets/splash/small.mp4}
# Optional: pin/prefer a connector (listed first if connected). Empty =
# pure auto-detect. The old BCM_SPLASH_DRM_MAIN/_SMALL env are honoured as
# "preferred first" hints only — a disconnected hint is ignored, not fatal.
PREFER_CONN=${BCM_SPLASH_DRM_MAIN:-}
MIN_SECONDS=${BCM_SPLASH_MIN_SECONDS:-0}
READY_URL=${BCM_SPLASH_READY_URL:-http://localhost:5002/api/ready}
FALLBACK_URL=${BCM_SPLASH_FALLBACK_URL:-http://localhost:5002}
CARD=${BCM_SPLASH_CARD:-/dev/dri/card0}
DRM_DIR=${BCM_SPLASH_DRM_DIR:-/sys/class/drm}
MAX_WAIT=${BCM_SPLASH_MAX_WAIT:-60}
FLASK_GATE_SECONDS=${BCM_SPLASH_FLASK_GATE_SECONDS:-12}

log() { echo "[bcm-splash] $*"; }

# --- connector discovery -------------------------------------------------

# Echo connected connector names (e.g. "HDMI-A-2"), preferred one first.
connected_connectors() {
    local prefer="$1" found=() name
    for s in "$DRM_DIR"/card0-*/status; do
        [ -r "$s" ] || continue
        [ "$(cat "$s" 2>/dev/null)" = "connected" ] || continue
        name=$(basename "$(dirname "$s")"); name=${name#card0-}
        found+=("$name")
    done
    # Emit the preferred connector first if it is actually connected.
    local emitted=()
    if [ -n "$prefer" ]; then
        for n in "${found[@]}"; do
            if [ "$n" = "$prefer" ]; then echo "$n"; emitted+=("$n"); fi
        done
    fi
    for n in "${found[@]}"; do
        local skip=0
        for e in "${emitted[@]:-}"; do [ "$n" = "$e" ] && skip=1; done
        [ "$skip" = 0 ] && echo "$n"
    done
}

# Resolve a connector NAME to its numeric KMS id (needed by kmssink).
# Intel i915 exposes it in debugfs; other drivers may not, in which case
# we return empty and the caller degrades to the single-connector path.
resolve_connector_id() {
    local name="$1" f
    for f in /sys/kernel/debug/dri/*/i915_display_info; do
        [ -r "$f" ] || continue
        # line: "[CONNECTOR:121:HDMI-A-2]: status: connected"
        sed -n "s/.*\[CONNECTOR:\([0-9]\+\):${name}\].*/\1/p" "$f" 2>/dev/null | head -1
        return
    done
}

# --- players -------------------------------------------------------------

PLAYER_PID=""

start_mpv() {  # $1 = connector name
    local conn="$1"
    if ! command -v mpv >/dev/null; then
        log "mpv not installed; cannot show splash"
        return 1
    fi
    log "splash: mpv on $conn ($VIDEO)"
    # mpv 0.40 removed --drm-atomic (atomic is the default; passing it is
    # rejected and killed the splash at frame one). --vo=drm + connector only.
    mpv --fs --loop-file=inf --no-audio --vo=drm \
        --drm-connector="$conn" --input-conf=/dev/null \
        --msg-level=all=warn "$VIDEO" >/tmp/bcm-splash-mpv.log 2>&1 &
    PLAYER_PID=$!
}

start_gst_multi() {  # $@ = connector names (>=2)
    command -v gst-launch-1.0 >/dev/null || { log "gst-launch missing"; return 1; }
    local sinks="" ids=()
    for conn in "$@"; do
        local id; id=$(resolve_connector_id "$conn")
        if [ -z "$id" ]; then
            log "could not resolve KMS id for $conn — multi-screen unavailable"
            return 1
        fi
        ids+=("$id")
        sinks+=" t. ! queue ! kmssink connector-id=$id force-modesetting=true"
    done
    log "splash: gst tee → ${#ids[@]} screens (connector-ids: ${ids[*]})"
    # Decode once, fan out to every connector. gst-launch has no native
    # loop, so a watcher relaunches it if it exits before the gate fires.
    (
        while true; do
            gst-launch-1.0 -q filesrc location="$VIDEO" \
                ! decodebin ! videoconvert ! tee name=t $sinks \
                >/tmp/bcm-splash-gst.log 2>&1
            # If gst dies in <2s it's a hard failure, not end-of-clip — stop
            # relooping so the fallback can take the screen.
            [ -f /tmp/bcm-splash-gst.stop ] && break
            sleep 0.3
        done
    ) &
    PLAYER_PID=$!
    # Detect immediate hard failure (bad pipeline / lost master).
    sleep 1.5
    if ! kill -0 "$PLAYER_PID" 2>/dev/null; then
        log "gst multi-sink failed to start"
        return 1
    fi
    if grep -qiE "error|erroneous|could not|failed" /tmp/bcm-splash-gst.log 2>/dev/null; then
        log "gst reported an error — falling back"
        stop_player
        return 1
    fi
    return 0
}

start_player() {
    mapfile -t CONNS < <(connected_connectors "$PREFER_CONN")
    if [ "${#CONNS[@]}" -eq 0 ]; then
        log "no connected DRM connector found; skipping splash"
        return 1
    fi
    log "connected connector(s): ${CONNS[*]}"
    if [ "${#CONNS[@]}" -ge 2 ]; then
        rm -f /tmp/bcm-splash-gst.stop
        if start_gst_multi "${CONNS[@]}"; then
            return 0
        fi
        log "multi-screen path unavailable — falling back to mpv on ${CONNS[0]}"
    fi
    start_mpv "${CONNS[0]}"
}

stop_player() {
    touch /tmp/bcm-splash-gst.stop 2>/dev/null || true
    [ -z "${PLAYER_PID:-}" ] && return
    kill "$PLAYER_PID" 2>/dev/null || true
    pkill -P "$PLAYER_PID" 2>/dev/null || true
    pkill -f "mpv.*$VIDEO" 2>/dev/null || true
    pkill -f "gst-launch.*$VIDEO" 2>/dev/null || true
    wait "$PLAYER_PID" 2>/dev/null || true
}

# --- main ----------------------------------------------------------------

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
#   1. /api/ready (App.init posts once Chromium rendered) → exit now.
#   2. Flask root up ≥ FLASK_GATE_SECONDS without /api/ready → exit so X
#      can take DRM master.
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
