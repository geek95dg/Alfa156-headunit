#!/bin/bash
# Configure the BT adapter for headunit pairing.
#
# Properties are set inside ONE bluetoothctl session — non-interactive
# `bluetoothctl pairable on` etc. report success but the property does
# not actually persist after the process exits. A single piped session
# keeps the connection alive long enough for BlueZ to commit them.
#
# The pairing agent itself is registered by the BCM headunit (see
# src/multimedia/bluetooth.py:_start_pairing_agent) — keeping it out of
# this oneshot avoids a phantom default-agent that vanishes immediately.

set -u

# Wait for adapter to appear (BlueZ may still be initialising).
for i in $(seq 1 30); do
    if bluetoothctl show 2>/dev/null | grep -q "^Controller "; then
        break
    fi
    sleep 1
done

# Retry the configure-and-verify block up to 5 times. Some Intel/CSR
# adapters need an extra power-cycle before pairable/discoverable stick.
for attempt in 1 2 3 4 5; do
    bluetoothctl <<'EOF'
power on
system-alias "Alfa156 Headunit"
discoverable-timeout 0
pairable on
discoverable on
EOF
    sleep 1
    state=$(bluetoothctl show 2>/dev/null)
    if echo "$state" | grep -q "Pairable: yes" \
       && echo "$state" | grep -q "Discoverable: yes"; then
        echo "BT adapter ready for pairing (attempt $attempt)"
        echo "$state" | grep -E "Powered|Discoverable|Pairable"
        exit 0
    fi
    echo "BT setup attempt $attempt did not stick, retrying..."
    sleep 2
done

echo "WARN: BT adapter never reached pairable+discoverable; final state:"
bluetoothctl show 2>/dev/null | grep -E "Powered|Discoverable|Pairable"
# Exit 0 so systemd doesn't mark the unit failed — the BCM headunit
# can still call enable_discoverable() once its agent is up.
exit 0
