#!/bin/bash
# BCM — NAT internet sharing from the AP iface to every real uplink.
#
# Installed as /usr/local/bin/bcm-nat.sh by setup-x86.sh and apply-fixes.sh
# (it used to be a heredoc in both, and the two copies drifted apart).
# Run by bcm-nat.service at boot and once more by bcm-nat-late.timer 30 s
# later, for uplinks (LTE) that come up after the first pass.
#
# Applies MASQUERADE + FORWARD rules between the BCM AP iface and every
# uplink. Idempotent: every rule is checked (-C) before it is added (-A).
#
# Why "default route" and not only operstate: the LTE wwan driver
# (cdc_ether on Huawei E3372) reports operstate=unknown even when fully up,
# so an "operstate==up" check silently skipped LTE and AP clients only
# reached the internet via ethernet (if attached). Ifaces that are up or
# unknown are still added, which covers static-IP ethernet without a
# default route in the table at the moment we run.
#
# Never treated as uplinks:
#   lo, the AP itself  - obviously
#   p2p-*              - the Wi-Fi Direct group iface: that is the phone side
#   bnep*              - Bluetooth PAN = internet FROM the phone; NAT-ing the
#                        AP (where the phone is the client) out through it
#                        would loop the phone's own traffic back to the phone
#   docker*, veth*     - container bridges, not a way out
#
# Environment:
#   AP_IFACE   AP interface (default wlp2s0), set by bcm-nat.service
#
# A car spends most of its life without an uplink, so "nothing to do" is
# not an error: every early exit is exit 0 and the unit never fails on it.
set -u

AP_IFACE="${AP_IFACE:-wlp2s0}"

log() {
    logger -t bcm-nat "$*" 2>/dev/null || true
    echo "[bcm-nat] $*"
}

# Kernel iface names are at most 15 bytes and never contain '/' or
# whitespace. Anything else did not come from the kernel, so refuse it
# instead of handing it to iptables.
valid_iface() {
    case "$1" in
        '' | *[!A-Za-z0-9_.:-]*) return 1 ;;
    esac
    [ "${#1}" -le 15 ]
}

is_uplink_candidate() {
    valid_iface "$1" || return 1
    case "$1" in
        lo | "$AP_IFACE") return 1 ;;
        p2p-* | bnep* | docker* | veth*) return 1 ;;
    esac
    return 0
}

if ! valid_iface "$AP_IFACE"; then
    log "invalid AP_IFACE '$AP_IFACE' - nothing to do"
    exit 0
fi
if [ ! -d "/sys/class/net/$AP_IFACE" ]; then
    log "AP iface $AP_IFACE missing"
    exit 0
fi
if ! command -v iptables >/dev/null 2>&1; then
    log "iptables not installed - cannot share internet"
    exit 0
fi

sysctl -w net.ipv4.ip_forward=1 >/dev/null 2>&1 || true

declare -A UPLINKS=()

# 1) Every iface that carries a default route.
while read -r dev; do
    if is_uplink_candidate "$dev"; then
        UPLINKS["$dev"]=1
    fi
done < <(ip -4 route show default 2>/dev/null \
    | awk '{for (i = 1; i <= NF; i++) if ($i == "dev") print $(i + 1)}')

# 2) Every iface that is up/unknown (static ethernet, LTE before routing).
for path in /sys/class/net/*; do
    [ -e "$path" ] || continue
    up="${path##*/}"
    is_uplink_candidate "$up" || continue
    state=$(cat "$path/operstate" 2>/dev/null || echo down)
    case "$state" in
        up | unknown) UPLINKS["$up"]=1 ;;
    esac
done

if [ "${#UPLINKS[@]}" -eq 0 ]; then
    log "no uplink yet - nothing to share"
    exit 0
fi

# "-m state" (not the newer "-m conntrack --ctstate") on purpose: the -C
# check must match the rule earlier installs added, or a re-run would stack
# a second, equivalent rule next to the old one.
for up in "${!UPLINKS[@]}"; do
    ok=1
    iptables -t nat -C POSTROUTING -o "$up" -j MASQUERADE 2>/dev/null \
        || iptables -t nat -A POSTROUTING -o "$up" -j MASQUERADE \
        || ok=0
    iptables -C FORWARD -i "$up" -o "$AP_IFACE" -m state \
        --state RELATED,ESTABLISHED -j ACCEPT 2>/dev/null \
        || iptables -A FORWARD -i "$up" -o "$AP_IFACE" -m state \
            --state RELATED,ESTABLISHED -j ACCEPT \
        || ok=0
    iptables -C FORWARD -i "$AP_IFACE" -o "$up" -j ACCEPT 2>/dev/null \
        || iptables -A FORWARD -i "$AP_IFACE" -o "$up" -j ACCEPT \
        || ok=0
    if [ "$ok" -eq 1 ]; then
        log "NAT enabled: $AP_IFACE -> $up"
    else
        log "NAT for $AP_IFACE -> $up incomplete (iptables error, see above)"
    fi
done
exit 0
