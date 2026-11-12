#!/bin/bash
# Correct the clock from an authoritative HTTP Date header.
#
# This machine has no NTP client and cannot easily get one: the only
# packaged option, systemd-timesyncd, pulls a systemd+udev upgrade with
# it, and udev ordering is what the boot splash hangs off (see
# docs and bcm-splash-main.service). So we sync the cheap way instead —
# an HTTPS HEAD request, whose Date header is served to the second and is
# already authenticated by TLS. Accuracy is a second or two, which is
# what a dashboard clock needs.
#
# The original fault this fixes: the RTC had been written with LOCAL time
# while `RTC in local TZ` was `no`, so every boot read 22:30 as UTC and
# added the Warsaw +2 on top — the dashboard showed 00:30. Correcting the
# system clock and letting systemd write the RTC back cures the stored
# value; this unit keeps it cured if the CMOS cell ever goes flat or the
# clock drifts while the car sits.
#
# Offline is the normal case in a car, not an error: no uplink means no
# correction and a silent exit 0, so the timer can retry later without
# the unit going into a failed state.

set -u

# Any host that serves a Date header will do; two of them so one being
# unreachable (or blocked by a captive portal) is not the end of it.
HOSTS=(
    "https://www.google.com"
    "https://cloudflare.com"
)

# Proof of a good sync for other parts of BCM: the car phone module
# (src/network/car_phone.py) sets the clock from the phone over USB only
# when THIS script has not succeeded within its last timer period (1 h, plus
# 15 min slack for the timer's accuracy and curl) — the internet is the
# better source. Written on every success (clock already right, or
# corrected), never when offline. /run is tmpfs: a fresh boot starts without
# it, which is exactly "no sync since the power cut". Content:
# "<CLOCK_BOOTTIME seconds> <epoch>" — boot time (from /proc/uptime) because
# the wall clock is the thing that may just have jumped; it also counts
# time spent in S3.
OK_MARKER=/run/bcm-timesync.ok

mark_ok() {
    local up _rest
    read -r up _rest < /proc/uptime 2>/dev/null || return 0
    printf '%s %s\n' "${up%%.*}" "$(date -u +%s)" > "$OK_MARKER.tmp" 2>/dev/null \
        && mv -f "$OK_MARKER.tmp" "$OK_MARKER" 2>/dev/null
    return 0
}

# Below this we do not touch the clock. Rewriting the RTC on every tick
# for sub-minute jitter buys nothing and costs a write; the fault we care
# about is hours out, not seconds.
THRESHOLD_SEC=30

fetch_date() {
    curl -sSI --max-time 10 "$1" 2>/dev/null \
        | grep -i '^date:' | head -1 | cut -d' ' -f2- | tr -d '\r'
}

for host in "${HOSTS[@]}"; do
    remote="$(fetch_date "$host")"
    [ -n "$remote" ] || continue

    remote_epoch="$(date -u -d "$remote" +%s 2>/dev/null)" || continue
    [ -n "$remote_epoch" ] || continue
    local_epoch="$(date -u +%s)"

    drift=$(( remote_epoch - local_epoch ))
    [ "$drift" -lt 0 ] && drift=$(( -drift ))

    if [ "$drift" -lt "$THRESHOLD_SEC" ]; then
        echo "clock within ${drift}s of $host — leaving it alone"
        mark_ok
        exit 0
    fi

    # set-time (not `date -s`) because it also writes the RTC, which is
    # the half that has to survive a power cut.
    if timedatectl set-time "@${remote_epoch}" 2>/dev/null \
       || date -u -s "$remote" >/dev/null 2>&1; then
        echo "clock corrected by ${drift}s from $host — now $(date)"
        # `date -s` fallback leaves the RTC stale; push it explicitly.
        timedatectl set-time "$(date '+%Y-%m-%d %H:%M:%S')" 2>/dev/null || true
        mark_ok
        exit 0
    fi

    echo "could not set the clock (drift was ${drift}s)" >&2
    exit 1
done

echo "no uplink to read a Date header from — clock left as it is"
exit 0
