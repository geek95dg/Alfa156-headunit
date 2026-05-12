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

# rfkill — almost every "BT works on the VM but not on baremetal" report
# traces back to a soft-block here. Many ARM boards (OPi 5 Pro, RPi-class)
# and several Intel NUC firmwares boot with bluetooth rfkill-blocked, and
# `bluetoothctl power on` returns "succeeded" against a still-dark radio.
# Unblock once before we even ask BlueZ for the controller, and verify.
if command -v rfkill >/dev/null 2>&1; then
    rfkill unblock bluetooth 2>/dev/null || true
    if rfkill list bluetooth 2>/dev/null | grep -q "Soft blocked: yes"; then
        echo "WARN: bluetooth still soft-blocked after rfkill unblock"
    fi
fi

# Hard-disable the integrated Intel 8087 controller.
# Why: on the M910q (and other NUC-class boards) both the internal Intel
# 8087:0a2b and an external CSR/Realtek dongle land on hciX simultaneously,
# and BlueZ happily advertises both — phones then see two carkits with the
# same alias and pairing latches onto the Intel one which mid-session
# `tx timeout`s and drops. Preferring the dongle in userspace isn't
# enough: the Intel still publishes the advertising RA, A2DP-Sink endpoint
# on the wrong BD_ADDR, and HFP profile that the phone may pick first.
#
# Unbind it from its USB driver so the kernel removes /sys/class/bluetooth/hciN
# entirely. BlueZ then only sees the dongle.  Can be re-enabled by setting
# BCM_BT_KEEP_INTERNAL=1 in /etc/default/bcm-bluetooth.
[ -f /etc/default/bcm-bluetooth ] && . /etc/default/bcm-bluetooth
if [ "${BCM_BT_KEEP_INTERNAL:-0}" != "1" ]; then
    for hci_dir in /sys/class/bluetooth/hci*; do
        [ -e "$hci_dir" ] || continue
        hci=$(basename "$hci_dir")
        dev_real=$(readlink -f "$hci_dir/device" 2>/dev/null || true)
        [ -n "$dev_real" ] || continue
        # Walk up to the USB interface node (has idVendor/bInterfaceNumber).
        cur="$dev_real"
        vendor=""
        usb_iface=""
        for _ in 1 2 3 4 5; do
            if [ -f "$cur/idVendor" ]; then
                vendor=$(cat "$cur/idVendor" 2>/dev/null | tr A-Z a-z)
                usb_iface="$cur"
                break
            fi
            parent=$(dirname "$cur")
            [ "$parent" = "$cur" ] && break
            cur="$parent"
        done
        if [ "$vendor" = "8087" ] && [ -n "$usb_iface" ]; then
            # The USB *device* node (one level up from interface) is what
            # we unbind from the usb driver. dev_real for hciX usually
            # points to interface .0 of the device, e.g.
            #   /sys/bus/usb/devices/1-7:1.0  →  parent device 1-7
            usb_dev=$(dirname "$usb_iface")
            usb_name=$(basename "$usb_dev")
            echo "BT setup: unbinding internal Intel 8087 at $usb_name ($hci)"
            hciconfig "$hci" down 2>/dev/null || true
            if [ -e /sys/bus/usb/drivers/usb/unbind ]; then
                echo "$usb_name" > /sys/bus/usb/drivers/usb/unbind 2>/dev/null || true
            fi
        fi
    done
fi

# NOTE: do NOT touch /etc/bluetooth/main.conf here, and do NOT restart
# bluetooth.service from within this script. The unit has
# Requires=bluetooth.service, so bouncing the daemon makes systemd
# cascade-stop *us* (SIGTERM 15) before bluetoothctl finishes — the
# whole bcm-bluetooth.service then loops with "Start request repeated
# too quickly" and never lands the discoverable/pairable state. main.conf
# (Class, AlwaysPairable, AutoEnable, etc.) is populated once by
# setup-x86.sh which runs outside systemd; this helper just talks to the
# already-running daemon.
#
# bcm-bluetooth.service has Requires= + After=bluetooth.service, so by
# the time we get here the daemon is already up — no manual start needed.

# Wait for adapter to appear (BlueZ may still be initialising).
for i in $(seq 1 30); do
    if bluetoothctl show 2>/dev/null | grep -q "^Controller "; then
        break
    fi
    # Some USB BT dongles need an explicit hciconfig up after rfkill
    # unblock to publish themselves on D-Bus.
    if [ "$i" = "10" ] && command -v hciconfig >/dev/null 2>&1; then
        for hci in /sys/class/bluetooth/hci*; do
            [ -e "$hci" ] || continue
            hciconfig "$(basename "$hci")" up 2>/dev/null || true
        done
    fi
    sleep 1
done

# Pick the preferred adapter. On the M910q the integrated Intel 8087:0a2b
# (BT 4.2 on paper, vs the typical CSR dongle's 4.0) is the *spec-better*
# choice but the hardware is documented-broken: dmesg shows repeated
# `Bluetooth: hciX: command 0xNNNN tx timeout` followed by
# `Resetting usb device.` after ~15 min, after which the controller
# vanishes from sysfs entirely. So default to a non-8087 (CSR/Realtek/
# Broadcom) USB dongle when one is plugged in. To force a specific
# controller MAC anyway, set BCM_BT_ADAPTER in /etc/default/bcm-bluetooth.
PREFERRED_ADDR=""
NON_INTEL_ADDR=""
INTEL_ADDR=""
FIRST_ADDR=""
# shellcheck source=/dev/null
[ -f /etc/default/bcm-bluetooth ] && . /etc/default/bcm-bluetooth
for hci_dir in $(ls -d /sys/class/bluetooth/hci* 2>/dev/null | sort); do
    [ -e "$hci_dir" ] || continue
    hci=$(basename "$hci_dir")
    dev_real=$(readlink -f "$hci_dir/device" 2>/dev/null || true)
    vendor=""
    cur="$dev_real"
    for _ in 1 2 3 4; do
        if [ -f "$cur/idVendor" ]; then
            vendor=$(cat "$cur/idVendor" 2>/dev/null | tr A-Z a-z)
            break
        fi
        parent=$(dirname "$cur")
        [ "$parent" = "$cur" ] && break
        cur="$parent"
    done
    addr=$(hciconfig "$hci" 2>/dev/null | awk '/BD Address/{print $3; exit}')
    [ -n "$addr" ] || continue
    [ -z "$FIRST_ADDR" ] && FIRST_ADDR="$addr"
    if [ "$vendor" = "8087" ]; then
        [ -z "$INTEL_ADDR" ] && INTEL_ADDR="$addr"
    elif [ -n "$vendor" ] && [ -z "$NON_INTEL_ADDR" ]; then
        NON_INTEL_ADDR="$addr"
        echo "BT setup: non-Intel candidate $hci ($addr, vendor $vendor)"
    fi
done
if [ -n "${BCM_BT_ADAPTER:-}" ]; then
    PREFERRED_ADDR="$BCM_BT_ADAPTER"
    echo "BT setup: explicit override BCM_BT_ADAPTER=$PREFERRED_ADDR"
elif [ "${BCM_BT_PREFER_INTERNAL:-0}" = "1" ] && [ -n "$INTEL_ADDR" ]; then
    PREFERRED_ADDR="$INTEL_ADDR"
    echo "BT setup: BCM_BT_PREFER_INTERNAL=1 — using Intel $PREFERRED_ADDR"
elif [ -n "$NON_INTEL_ADDR" ]; then
    PREFERRED_ADDR="$NON_INTEL_ADDR"
elif [ -n "$FIRST_ADDR" ]; then
    PREFERRED_ADDR="$FIRST_ADDR"
    echo "BT setup: no preferred adapter, falling back to $PREFERRED_ADDR"
fi

# Find the hciX index for the chosen address — used for hciconfig fallback
# when bluetoothctl property writes get racy (Intel adapters often need a
# power cycle before discoverable-timeout commits, which interactive
# bluetoothctl doesn't sequence reliably).
PREFERRED_HCI=""
if [ -n "$PREFERRED_ADDR" ]; then
    for hci_dir in /sys/class/bluetooth/hci*; do
        [ -e "$hci_dir" ] || continue
        h=$(basename "$hci_dir")
        a=$(hciconfig "$h" 2>/dev/null | awk '/BD Address/{print $3; exit}')
        if [ "$a" = "$PREFERRED_ADDR" ]; then
            PREFERRED_HCI="$h"
            break
        fi
    done
fi

# Force the carkit Class-of-Device via hciconfig. bluetoothd's CoD
# synthesis from registered profiles produces non-carkit values
# (0x006c0104 = "Computer with Audio/Rendering" or 0x00400104 = "AV
# remote only" while the A2DP-Sink endpoint registration is still in
# flight). The phone's Android Auto trigger looks at this byte to decide
# "is this a real carkit" — Audio+Telephony+Networking service bits +
# AV major + Carkit minor is the combination that switches on the AA
# pairing flow on stock Android. Decode of 0x620420:
#   bit 17 = Networking | bit 21 = Audio | bit 22 = Telephony
#   major (bits 8-12)   = 0x04 → AudioVideo
#   minor (bits 2-7)    = 0x08 → Carkit
if [ -n "$PREFERRED_HCI" ] && command -v hciconfig >/dev/null 2>&1; then
    hciconfig "$PREFERRED_HCI" up 2>/dev/null || true
    hciconfig "$PREFERRED_HCI" class 0x620420 2>/dev/null || true
fi

# Retry the configure-and-verify block up to 5 times. Order matters:
# select → power on → wait → discoverable-timeout → pairable-timeout →
# pairable on → discoverable on. Setting timeouts BEFORE the radio is
# powered loses them; setting them too quickly after power on races the
# kernel's bring-up.
for attempt in 1 2 3 4 5; do
    if [ -n "$PREFERRED_ADDR" ]; then
        bluetoothctl <<EOF
select $PREFERRED_ADDR
power on
EOF
        sleep 0.5
        bluetoothctl <<EOF
select $PREFERRED_ADDR
system-alias "Alfa156 Headunit"
discoverable-timeout 0
pairable on
discoverable on
EOF
    else
        bluetoothctl <<'EOF'
power on
EOF
        sleep 0.5
        bluetoothctl <<'EOF'
system-alias "Alfa156 Headunit"
discoverable-timeout 0
pairable on
discoverable on
EOF
    fi
    sleep 1
    state=$(bluetoothctl show "$PREFERRED_ADDR" 2>/dev/null)
    [ -z "$state" ] && state=$(bluetoothctl show 2>/dev/null)
    if echo "$state" | grep -q "Pairable: yes" \
       && echo "$state" | grep -q "Discoverable: yes"; then
        echo "BT adapter ready for pairing (attempt $attempt)"
        echo "$state" | grep -E "Powered|Discoverable|Pairable|Class"
        exit 0
    fi
    echo "BT setup attempt $attempt did not stick, retrying..."
    sleep 2
done

echo "WARN: BT adapter never reached pairable+discoverable; final state:"
bluetoothctl show "$PREFERRED_ADDR" 2>/dev/null | grep -E "Powered|Discoverable|Pairable|Class"
# Exit 0 so systemd doesn't mark the unit failed — the BCM headunit
# can still call enable_discoverable() once its agent is up.
exit 0
