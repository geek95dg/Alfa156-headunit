#!/bin/bash
# BCM power button handler — toggle between running and suspended.
# Installed to /usr/local/bin/ and triggered by acpid on power button press.
#
# When BCM is running: stop it, then suspend to S3.
# Wake-source teardown (LTE unbind, USB/serio/HDA wakeup off) is handled
# by /lib/systemd/system-sleep/bcm-sleep so it runs no matter how suspend
# is triggered. Resume restart is handled by the same hook.

if systemctl is-active --quiet bcm-headunit.service; then
    systemctl stop bcm-headunit.service
    sleep 1
fi

systemctl suspend
