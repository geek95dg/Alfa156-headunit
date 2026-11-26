#!/system/bin/sh
# bcm_autoboot.sh — runs ONLY in charger mode (see bcm-autoboot.rc): wait for
# a minimum battery level, then reboot into the normal system.
#
# - MIN_PCT: below it the battery may not carry a boot (worse in the cold);
# - the wait is bounded (MAX_WAIT_S): a battery that does not charge (too
#   cold — the charger IC stops below ~0 °C) never triggers a boot loop;
#   unplugging in charger mode powers the phone off anyway;
# - one line per decision to the kernel log (dmesg | grep bcm_autoboot).
MIN_PCT=5
MAX_WAIT_S=7200
STEP_S=15
CAP=${BCM_AUTOBOOT_CAP:-/sys/class/power_supply/battery/capacity}

log() { echo "bcm_autoboot: $*" 2>/dev/null >/dev/kmsg; }

waited=0
while [ "$waited" -lt "$MAX_WAIT_S" ]; do
    pct=$(cat "$CAP" 2>/dev/null)
    case "$pct" in ''|*[!0-9]*) pct=0 ;; esac
    if [ "$pct" -ge "$MIN_PCT" ]; then
        log "battery ${pct}% >= ${MIN_PCT}% - rebooting into the system"
        setprop sys.powerctl reboot
        exit 0
    fi
    [ "$waited" -eq 0 ] && log "battery ${pct}% < ${MIN_PCT}% - charging first"
    sleep "$STEP_S"
    waited=$((waited + STEP_S))
done
log "battery still below ${MIN_PCT}% after ${MAX_WAIT_S}s - staying in charger mode"
exit 0
