#!/bin/bash
# BCM power button handler — toggle between running and suspended.
# Installed to /usr/local/bin/ and triggered by acpid on power button press.
#
# When BCM is running: stop it, then suspend to S3.
# When system resumes: bcm-resume.service auto-starts BCM.

if systemctl is-active --quiet bcm-headunit.service; then
    systemctl stop bcm-headunit.service
    sleep 1
fi

# Disable USB wake sources (touchscreens, hubs send spurious wake events)
for f in /sys/bus/usb/devices/*/power/wakeup; do
    echo disabled > "$f" 2>/dev/null
done

# Unbind LTE modem — it blocks suspend with "Failed to suspend device"
for dev in /sys/bus/usb/drivers/cdc_ether/*/; do
    [ -e "$dev" ] && echo "$(basename "$dev")" > /sys/bus/usb/drivers/cdc_ether/unbind 2>/dev/null
done

systemctl suspend
