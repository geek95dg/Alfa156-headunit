#!/bin/bash
# Activate the LTE data session via NetworkManager + ModemManager.
#
# On x86 the modem (Huawei E3372 12d1:1506) is owned by ModemManager
# and exposed to NetworkManager as a gsm device on ttyUSB0. nmcli is
# the canonical way to dial: it sets the APN/auth on the right CID,
# triggers AT^NDISDUP through MM, and runs DHCP on the wwx ethernet
# interface — all the things that AT-by-hand misses on this firmware.
#
# Reads APN from /etc/bcm/lte.conf (Orange Polska defaults).
#
# IMPORTANT: this script must NOT block multi-user.target. The actual
# `nmcli con up` is forked into the background so the systemd oneshot
# returns within seconds even when the modem is slow to register or
# the carrier session takes a long time to establish.

set -u

CONF=/etc/bcm/lte.conf
[ -r "$CONF" ] && . "$CONF"

APN=${APN:-internet}
LTE_USER=${LTE_USER:-internet}
LTE_PASS=${LTE_PASS:-internet}
# 0=none, 1=PAP, 2=CHAP — Orange PL uses PAP (gsm.password-flags 0).
AUTH=${AUTH:-1}
CON_NAME=${CON_NAME:-bcm-lte}
# Quick probe so a missing/slow modem doesn't keep boot blocked. The
# service used to wait 30s here, then run a `nmcli con up` that itself
# could take another 60s, blocking multi-user.target for ~90s.
MODEM_WAIT=${MODEM_WAIT:-8}

log() { echo "[bcm-lte] $*"; logger -t bcm-lte "$*"; }

if ! command -v nmcli >/dev/null 2>&1; then
    log "nmcli not installed — cannot manage LTE; install network-manager"
    exit 0
fi

# Wait briefly for ModemManager to enumerate the modem; if absent, exit
# 0 and skip dialing. Boot must not stall on a missing SIM/modem.
GSM_DEV=""
for i in $(seq 1 "$MODEM_WAIT"); do
    GSM_DEV=$(nmcli -t -f DEVICE,TYPE device 2>/dev/null \
              | awk -F: '$2=="gsm"{print $1; exit}')
    [ -n "$GSM_DEV" ] && break
    sleep 1
done
if [ -z "$GSM_DEV" ]; then
    log "no gsm device after ${MODEM_WAIT}s — skipping (no modem fitted)"
    exit 0
fi
log "gsm device: $GSM_DEV (APN=$APN auth=$AUTH)"

# Create-or-update the connection profile so APN edits in lte.conf
# always propagate.
if ! nmcli -t -f NAME con show 2>/dev/null | grep -qx "$CON_NAME"; then
    nmcli con add type gsm ifname '*' con-name "$CON_NAME" apn "$APN" \
        connection.autoconnect yes >/dev/null
    log "created nmcli profile $CON_NAME"
fi

# Map AUTH integer to nmcli pap/chap flags. Orange PL uses PAP, but
# nmcli doesn't have a single auth-method knob — it tries both unless
# explicitly disabled. Setting username+password covers PAP; refuse-chap
# below restricts to PAP only when AUTH=1.
nmcli con modify "$CON_NAME" \
    gsm.apn "$APN" \
    gsm.username "$LTE_USER" \
    gsm.password "$LTE_PASS" \
    gsm.password-flags 0 \
    ipv4.method auto \
    ipv6.method ignore \
    connection.autoconnect yes \
    connection.autoconnect-retries 0 \
    >/dev/null

case "$AUTH" in
    0) # No auth — clear creds entirely so nmcli doesn't force PAP/CHAP.
       nmcli con modify "$CON_NAME" gsm.username "" gsm.password "" >/dev/null
       ;;
    2) # CHAP-only — most carriers accept either, this just biases toward CHAP.
       nmcli con modify "$CON_NAME" +ppp.refuse-pap yes >/dev/null 2>&1 || true
       ;;
    *) # PAP (default for Orange PL).
       nmcli con modify "$CON_NAME" +ppp.refuse-chap yes >/dev/null 2>&1 || true
       ;;
esac

# Fire the actual dial in the background so the unit returns quickly
# and multi-user.target isn't held up by carrier/RAN attach time.
log "starting nmcli con up $CON_NAME in background"
(
    nmcli con down "$CON_NAME" >/dev/null 2>&1 || true
    sleep 1
    if nmcli con up "$CON_NAME" >/tmp/bcm-lte-up.log 2>&1; then
        logger -t bcm-lte "$CON_NAME up: $(grep -oE 'successfully activated.*' /tmp/bcm-lte-up.log || echo activated)"
    else
        logger -t bcm-lte "nmcli con up failed: $(tail -1 /tmp/bcm-lte-up.log 2>/dev/null)"
    fi

    sleep 3
    LTE_IFACE=$(nmcli -t -f GENERAL.DEVICES con show "$CON_NAME" 2>/dev/null \
                | awk -F: '{print $2}')
    [ -z "$LTE_IFACE" ] && LTE_IFACE=$(ls /sys/class/net/ | grep -m1 '^ww' || true)
    if [ -n "$LTE_IFACE" ] && ip -4 addr show "$LTE_IFACE" 2>/dev/null | grep -q "inet "; then
        IP=$(ip -4 addr show "$LTE_IFACE" | awk '/inet /{print $2; exit}')
        logger -t bcm-lte "online: $LTE_IFACE = $IP"
    else
        logger -t bcm-lte "no IP yet — NM will keep retrying autoconnect"
    fi
) </dev/null >/dev/null 2>&1 &
disown
exit 0
