#!/bin/sh
# BCM — second-display hotplug watcher.
#
# The small (6.86" 1280x480) display is optional and may be plugged in
# after boot. The kiosk xinitrc used to launch its Chromium window only
# if the panel was connected at boot, so a later hotplug did nothing.
# This watcher runs inside the X session (launched from xinitrc, so it
# inherits DISPLAY/XAUTHORITY) and brings the window up/down whenever the
# connector is plugged/unplugged.
#
# Usage: small-display-watch.sh <SMALL_OUTPUT> <MAIN_OUTPUT> <MAIN_W>
#   SMALL_OUTPUT  xrandr name of the small panel (e.g. HDMI-2)
#   MAIN_OUTPUT   xrandr name of the main panel  (e.g. HDMI-1)
#   MAIN_W        main panel width in px — x offset for the small window

SMALL_OUTPUT="$1"
MAIN_OUTPUT="$2"
MAIN_W="${3:-1024}"

[ -n "$SMALL_OUTPUT" ] || exit 0

# Unique marker so pgrep/pkill only ever match this window, never the
# main one or the watcher itself.
SMALL_PROFILE="/tmp/bcm-chromium-small"

launch_small() {
    # Enable the output at its native mode, to the right of main.
    xrandr --output "$SMALL_OUTPUT" --auto --right-of "$MAIN_OUTPUT" 2>/dev/null

    # Wait (bounded) for the small-display Flask server on :5003.
    i=0
    while [ "$i" -lt 30 ]; do
        curl -sf http://localhost:5003 >/dev/null 2>&1 && break
        i=$((i + 1))
        sleep 1
    done

    # Don't double-launch if a window is already up.
    if pgrep -f "$SMALL_PROFILE" >/dev/null 2>&1; then
        return
    fi

    S_W=$(xrandr | grep "^${SMALL_OUTPUT} " | grep -oP '\d+(?=x)' | head -1)
    S_H=$(xrandr | grep "^${SMALL_OUTPUT} " | grep -oP 'x\K\d+' | head -1)
    S_W=${S_W:-1280}
    S_H=${S_H:-480}

    rm -rf "$SMALL_PROFILE"
    chromium --app=http://localhost:5003 \
        --window-size="${S_W},${S_H}" --window-position="${MAIN_W},0" \
        --noerrdialogs --disable-infobars \
        --disable-features=TranslateUI --no-first-run \
        --disable-session-crashed-bubble \
        --user-data-dir="$SMALL_PROFILE" &
}

kill_small() {
    pkill -f "$SMALL_PROFILE" 2>/dev/null
    xrandr --output "$SMALL_OUTPUT" --off 2>/dev/null
}

last=""
while true; do
    if xrandr 2>/dev/null | grep -q "^${SMALL_OUTPUT} connected"; then
        state="connected"
    else
        state="disconnected"
    fi

    if [ "$state" != "$last" ]; then
        if [ "$state" = "connected" ]; then
            launch_small
        else
            kill_small
        fi
        last="$state"
    fi

    sleep 2
done
