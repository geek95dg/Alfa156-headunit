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

# Unbind Huawei LTE modem (usb 1-3) — it fails to suspend and triggers wake
# Find by vendor ID 12d1 (Huawei) and unbind from USB driver entirely
for dev in /sys/bus/usb/devices/*/idVendor; do
    dir=$(dirname "$dev")
    if [ "$(cat "$dir/idVendor" 2>/dev/null)" = "12d1" ]; then
        devname=$(basename "$dir")
        echo "$devname" > /sys/bus/usb/drivers/usb/unbind 2>/dev/null
        echo "Unbound LTE modem $devname for suspend"
    fi
done

# Disable XHCI/EHC/USB ACPI wake sources
if [ -f /proc/acpi/wakeup ]; then
    awk '/XHC|EHC|USB/ && /enabled/ {print $1}' /proc/acpi/wakeup | while read -r dev; do
        echo "$dev" > /proc/acpi/wakeup 2>/dev/null
    done
fi

# Also disable PS2K (keyboard) wake — no PS2 keyboard in car
if grep -q "PS2K.*enabled" /proc/acpi/wakeup 2>/dev/null; then
    echo "PS2K" > /proc/acpi/wakeup 2>/dev/null
fi

systemctl suspend
