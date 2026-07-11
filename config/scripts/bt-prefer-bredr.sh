#!/bin/sh
# BCM — force BR/EDR-first connection for bonded phones.
#
# Why: BlueZ stores PreferredBearer=last-seen for dual-mode (BR/EDR+LE)
# devices. A phone constantly broadcasts BLE adverts, so "last seen" is
# always LE — Device1.Connect() then opens an LE link and NEVER pages
# classic BR/EDR (no HCI Create Connection). Android Auto, A2DP and HFP
# are all classic profiles, so they never come up and auto-connect on
# boot silently fails (the HCI trace shows only LE scanning).
#
# PreferredBearer is NOT settable over D-Bus in BlueZ 5.82 — it only
# lives in the on-disk bond record and is read when bluetoothd loads the
# device. So this runs as ExecStartPre on bluetooth.service (root, before
# the daemon loads records) and rewrites the bearer to "bredr" for every
# bond that has a classic [LinkKey].
#
# SAFETY: only touches records that contain a [LinkKey] section (a
# classic link key — i.e. a phone / classic device). LE-only devices
# (BLE trunk remote, window remote, etc.) have no [LinkKey] and are left
# completely untouched, so their LE connections keep working. Always
# exits 0 so a failure here can never block bluetooth.service from
# starting.

set -u
BT_DIR=/var/lib/bluetooth

[ -d "$BT_DIR" ] || exit 0

for info in "$BT_DIR"/*/*/info; do
    [ -f "$info" ] || continue
    # classic bond only — skip LE-only devices
    grep -q '^\[LinkKey\]' "$info" || continue

    if grep -q '^PreferredBearer=' "$info"; then
        grep -q '^PreferredBearer=bredr$' "$info" && continue
        sed -i 's/^PreferredBearer=.*/PreferredBearer=bredr/' "$info" 2>/dev/null || true
    elif grep -q '^\[General\]' "$info"; then
        sed -i '/^\[General\]/a PreferredBearer=bredr' "$info" 2>/dev/null || true
    fi
done

exit 0
