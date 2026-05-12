#!/bin/bash
# /lib/systemd/system-sleep/bcm-sleep — runs on every suspend/resume.
#
# This fires no matter how suspend is triggered (power button, systemctl
# suspend, idle timer, etc.), unlike bcm-power-toggle.sh which only runs
# on the ACPI power button.
#
# Why so aggressive: x86 mini-PCs with LTE modems and HDA audio routinely
# wake from S3 within milliseconds because:
#   - Huawei LTE (vendor 12d1) returns "Failed to suspend device"
#   - serio0 (PS/2 keyboard wakeup) is enabled even when no keyboard is
#     attached — kernel default
#   - HDA audio controller (\_SB_.PCI0.HDAS) generates spurious GPEs
# We unbind/disable each before the kernel commits to S3.

case "$1/$2" in
    pre/suspend)
        # Unbind Huawei LTE — fails to suspend, triggers immediate wake.
        for dev in /sys/bus/usb/devices/*/idVendor; do
            dir=$(dirname "$dev")
            if [ "$(cat "$dev" 2>/dev/null)" = "12d1" ]; then
                devname=$(basename "$dir")
                echo "$devname" > /sys/bus/usb/drivers/usb/unbind 2>/dev/null
                # Remember which we unbound so post/resume can rebind exactly these.
                echo "$devname" >> /run/bcm-sleep-unbound 2>/dev/null
                logger -t bcm-sleep "pre-suspend: unbound LTE $devname"
            fi
        done

        # Disable wakeup on every USB device (root hubs and children).
        for f in /sys/bus/usb/devices/*/power/wakeup; do
            echo disabled > "$f" 2>/dev/null
        done

        # Disable wakeup on serio (PS/2 keyboard — enabled by default).
        for f in /sys/devices/platform/i8042/serio*/power/wakeup; do
            echo disabled > "$f" 2>/dev/null
        done

        # Disable wakeup on HD audio (spurious GPEs from \_SB_.PCI0.HDAS).
        for f in /sys/bus/pci/devices/*/power/wakeup; do
            class=$(cat "$(dirname "$f")/class" 2>/dev/null)
            # 0x040300 = audio device, 0x040100 = multimedia audio
            case "$class" in
                0x0403*|0x0401*) echo disabled > "$f" 2>/dev/null ;;
            esac
        done

        # Disable ACPI wake sources for XHCI/EHCI/USB/PS2K if still enabled.
        if [ -f /proc/acpi/wakeup ]; then
            awk '/(XHC|EHC|USB|PS2K|HDAS)/ && /enabled/ {print $1}' /proc/acpi/wakeup \
                | while read -r dev; do
                    echo "$dev" > /proc/acpi/wakeup 2>/dev/null
                done
        fi

        logger -t bcm-sleep "pre-suspend: wakeup sources disabled"
        ;;

    post/suspend)
        # Rebind LTE devices we explicitly unbound.
        if [ -f /run/bcm-sleep-unbound ]; then
            while read -r devname; do
                echo "$devname" > /sys/bus/usb/drivers/usb/bind 2>/dev/null
                logger -t bcm-sleep "post-resume: rebound $devname"
            done < /run/bcm-sleep-unbound
            rm -f /run/bcm-sleep-unbound
        fi

        # Give USB a moment to enumerate before BCM headunit talks to it.
        sleep 2

        # LTE: re-dial the data session. The unbind in pre-suspend tore
        # down the NDIS PDP context; the modem won't reactivate it on
        # its own when re-bound, so we have to send AT^NDISDUP again.
        if [ -x /usr/local/bin/bcm-lte-up.sh ]; then
            /usr/local/bin/bcm-lte-up.sh >/dev/null 2>&1 &
            logger -t bcm-sleep "post-resume: re-dialing LTE in background"
        fi

        # Restart BCM headunit if ignition watcher expects it running.
        # (ignition-watcher itself stays up across suspend; it'll re-trigger
        # the headunit on the next ignition edge, but on a wake-from-S3
        # we want the dashboard back without waiting for ignition cycling.)
        if systemctl is-active --quiet bcm-ignition-watcher.service \
           && ! systemctl is-active --quiet bcm-headunit.service; then
            systemctl start bcm-headunit.service 2>/dev/null
            logger -t bcm-sleep "post-resume: restarted bcm-headunit"
        fi
        ;;
esac

exit 0
