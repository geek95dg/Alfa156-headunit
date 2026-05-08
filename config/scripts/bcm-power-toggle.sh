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

# Disable ALL USB wake sources
for f in /sys/bus/usb/devices/*/power/wakeup; do
    echo disabled > "$f" 2>/dev/null
done

# Disable XHCI/EHCI/USB wake in ACPI (main culprit for instant wake)
if [ -f /proc/acpi/wakeup ]; then
    awk '/XHC|EHC|USB/ && /enabled/ {print $1}' /proc/acpi/wakeup | while read -r dev; do
        echo "$dev" > /proc/acpi/wakeup 2>/dev/null
    done
fi

systemctl suspend
