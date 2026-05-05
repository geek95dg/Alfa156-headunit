#!/bin/bash
# BCM power button handler — toggle between running and suspended.
# Installed to /usr/local/bin/ and triggered by acpid on power button press.
#
# When BCM is running: stop it, then suspend to S3.
# When system resumes: bcm-resume.service auto-starts BCM.

if systemctl is-active --quiet bcm-headunit.service; then
    systemctl stop bcm-headunit.service
    sleep 1
    systemctl suspend
else
    systemctl suspend
fi
