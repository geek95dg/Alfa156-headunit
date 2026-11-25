#!/usr/bin/env bash
# =============================================================================
# bcm-net-auto.sh — M910q: internet przez KAŻDE dostępne łącze, wybierane
# automatycznie, zamiast sztywnej trasy po Ethernecie.
#
# Co robi (idempotentnie, z kopią i cofnięciem):
#  1. Ethernet ze statycznym IP ZOSTAJE (adres, maska, DNS bez zmian), ale
#     jego trasa domyślna dostaje metrykę 900 — najgorszą ze wszystkich, więc
#     używana jest tylko wtedy, gdy nic innego nie daje internetu.
#     Sztywny wpis "0.0.0.0/0 przez bramę" w ipv4.routes (wygrywa zawsze,
#     nawet bez internetu za kablem) zamienia na zwykłą bramę z tą metryką.
#     Z --eth-no-default eth w ogóle nie dostaje trasy domyślnej (sam LAN).
#  2. Włącza test łączności NetworkManagera (co 60 s). Łącze, które jest
#     podniesione, ale nie ma internetu, dostaje od NM karę +20000 do metryki
#     i ruch sam przechodzi na następne. Gdy internet wróci, kara znika.
#  3. Nie tworzy "Wired connection N" (metryka 100) dla telefonu po USB —
#     tym łączem zarządza BCM (profil bcm-car-phone, metryka 650).
#  4. Sprawdza trasy domyślne spoza NetworkManagera (ifupdown, netplan,
#     ręczne "ip route") i poprawia /etc/network/interfaces (metric 900)
#     albo mówi, co zmienić.
#
# Kolejność łączy po zmianie (niższa metryka = pierwsza):
#   Wi-Fi klient ~600 · USB z Redmi 650 · modem LTE 700 · Bluetooth PAN 750
#   · Ethernet (static) 900 · łącze bez internetu: +20000.
# Wi-Fi (AA, ALFA-NET) i profile BCM nie są ruszane.
#
# Użycie (na M910q, jako root):
#   sudo bash config/scripts/bcm-net-auto.sh --dry-run    # tylko pokaż
#   sudo bash config/scripts/bcm-net-auto.sh              # zastosuj
#   sudo bash config/scripts/bcm-net-auto.sh --eth-no-default
#   sudo bash config/scripts/bcm-net-auto.sh --undo       # przywróć
# Opcje: --eth-metric N (domyślnie 900).
# =============================================================================
set -euo pipefail

ETH_METRIC=900
DRY=0
UNDO=0
ETH_NO_DEFAULT=0
STATE_DIR=${BCM_NET_STATE_DIR:-/etc/bcm}
STATE=$STATE_DIR/net-auto.state
NM_CONF_DIR=${BCM_NM_CONF_DIR:-/etc/NetworkManager/conf.d}
CONN_CONF=$NM_CONF_DIR/bcm-connectivity.conf
NOAUTO_CONF=$NM_CONF_DIR/bcm-no-auto-default.conf
IFACES_FILE=${BCM_IFACES_FILE:-/etc/network/interfaces}
NETPLAN_DIR=${BCM_NETPLAN_DIR:-/etc/netplan}

usage() { sed -n '2,36p' "$0" | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run) DRY=1 ;;
        --undo) UNDO=1 ;;
        --eth-no-default) ETH_NO_DEFAULT=1 ;;
        --eth-metric)
            shift
            [[ "${1:-}" =~ ^[0-9]{1,5}$ ]] || { echo "--eth-metric: liczba 0-99999" >&2; exit 2; }
            ETH_METRIC=$1 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Nieznana opcja: $1 (--help)" >&2; exit 2 ;;
    esac
    shift
done

say()  { printf '  %s\n' "$*"; }
step() { printf '\n==> %s\n' "$*"; }
warn() { printf '  UWAGA: %s\n' "$*" >&2; }

# Każda zmiana idzie przez run(): w --dry-run tylko ją wypisuje.
run() {
    if [ "$DRY" = 1 ]; then
        printf '  [dry-run] %s\n' "$*"
    else
        "$@"
    fi
}

if [ "$DRY" = 0 ] && [ "$(id -u)" != 0 ] && [ -z "${BCM_NET_ALLOW_NONROOT:-}" ]; then
    echo "Uruchom jako root: sudo bash $0" >&2
    exit 1
fi
command -v nmcli >/dev/null 2>&1 || { echo "Brak nmcli (NetworkManager) — ten skrypt go wymaga." >&2; exit 1; }
if ! nmcli -t -f RUNNING general 2>/dev/null | grep -q running; then
    echo "NetworkManager nie działa (systemctl status NetworkManager)." >&2
    exit 1
fi

# ── cofnięcie ────────────────────────────────────────────────────────────────
if [ "$UNDO" = 1 ]; then
    step "Przywracanie ustawień sprzed bcm-net-auto.sh"
    if [ ! -f "$STATE" ]; then
        say "Brak $STATE — nic do przywrócenia."
    else
        # Linia: uuid|metric|never-default|gateway|routes. Separator "|", nie
        # tabulator: read zlewa sąsiednie białe znaki i gubi PUSTE pola.
        while IFS='|' read -r uuid metric nd gw routes; do
            [ -n "$uuid" ] || continue
            say "profil $uuid: metryka $metric, never-default $nd"
            run nmcli connection modify uuid "$uuid" ipv4.route-metric "$metric" \
                ipv4.never-default "$nd" ipv4.gateway "$gw" ipv4.routes "$routes"
            dev=$(nmcli -g GENERAL.DEVICES connection show uuid "$uuid" 2>/dev/null || true)
            [ -n "$dev" ] && run nmcli device reapply "$dev" || true
        done < "$STATE"
        run mv -f "$STATE" "$STATE.undone"
    fi
    for f in "$CONN_CONF" "$NOAUTO_CONF"; do
        [ -f "$f" ] && { say "usuwam $f"; run rm -f "$f"; }
    done
    [ -f "$IFACES_FILE.bcm-net-auto.bak" ] && {
        say "przywracam $IFACES_FILE z kopii"
        run cp -p "$IFACES_FILE.bcm-net-auto.bak" "$IFACES_FILE"
    }
    run systemctl reload NetworkManager || true
    step "Gotowe. Trasy domyślne teraz:"
    ip -4 route show default || true
    exit 0
fi

# ── 0. stan przed ────────────────────────────────────────────────────────────
step "Trasy domyślne PRZED zmianą"
ip -4 route show default || true

# ── 1. profile Ethernet w NetworkManagerze ───────────────────────────────────
step "1/4 Ethernet: statyczny IP zostaje, trasa domyślna na koniec kolejki"
[ "$DRY" = 1 ] || mkdir -p "$STATE_DIR"
found_eth=0
while IFS=: read -r uuid ctype; do
    [ "$ctype" = "802-3-ethernet" ] || continue
    # Wyniki "nmcli -g" dla jednego profilu: każde pole w osobnej linii.
    mapfile -t f < <(nmcli -g connection.id,ipv4.method,ipv4.route-metric,ipv4.never-default,ipv4.gateway,ipv4.routes \
                           connection show uuid "$uuid" 2>/dev/null || true)
    name=${f[0]:-?}; method=${f[1]:-}; metric=${f[2]:--1}; nd=${f[3]:-no}; gw=${f[4]:-}; routes=${f[5]:-}
    # Profil telefonu (rndis/ncm) ma swój: zostawiamy go BCM-owi.
    case "$name" in bcm-*) continue ;; esac
    [ "$method" = "manual" ] || { say "pomijam \"$name\" (ipv4.method=$method — nie statyczny)"; continue; }
    found_eth=1
    say "profil \"$name\": metryka=$metric, brama=${gw:-brak}, never-default=$nd"
    [ -n "$routes" ] && say "  trasy statyczne: $routes"

    # Kopia oryginału (tylko za pierwszym razem — kolejne uruchomienia nie
    # mogą nadpisać prawdziwego "przed").
    if [ "$DRY" = 0 ] && ! grep -q "^$uuid|" "$STATE" 2>/dev/null; then
        printf '%s|%s|%s|%s|%s\n' "$uuid" "$metric" "$nd" "$gw" "$routes" >> "$STATE"
        chmod 600 "$STATE"
    fi

    args=()
    # Sztywna trasa domyślna wpisana jako ipv4.routes "0.0.0.0/0 BRAMA [metryka]":
    # usuń ją, a jej bramę przenieś do ipv4.gateway (wtedy działa metryka).
    if [ -n "$routes" ]; then
        IFS=',' read -r -a rlist <<< "$routes"
        for r in "${rlist[@]}"; do
            r=$(echo "$r" | sed 's/^ *//; s/ *$//')
            if [[ "$r" =~ ^0\.0\.0\.0/0[[:space:]]+([0-9.]+) ]]; then
                say "  sztywna trasa domyślna \"$r\" → zwykła brama ${BASH_REMATCH[1]} z metryką"
                args+=("-ipv4.routes" "$r")
                [ -z "$gw" ] && gw=${BASH_REMATCH[1]} && args+=("ipv4.gateway" "$gw")
            fi
        done
    fi
    if [ "$ETH_NO_DEFAULT" = 1 ]; then
        say "  → bez trasy domyślnej (ipv4.never-default yes): eth tylko do sieci lokalnej"
        args+=("ipv4.never-default" "yes")
    else
        say "  → metryka $ETH_METRIC (eth zostaje zapasem, gdy nic innego nie daje internetu)"
        args+=("ipv4.route-metric" "$ETH_METRIC" "ipv4.never-default" "no")
    fi
    run nmcli connection modify uuid "$uuid" "${args[@]}"
    dev=$(nmcli -g GENERAL.DEVICES connection show uuid "$uuid" 2>/dev/null || true)
    if [ -n "$dev" ]; then
        # reapply = bez rozłączania; gdy NM odmówi, podniesienie profilu.
        run nmcli device reapply "$dev" || run nmcli connection up uuid "$uuid" || \
            warn "nie udało się zastosować na $dev — zadziała po restarcie"
    fi
done < <(nmcli -g UUID,TYPE connection show 2>/dev/null)
[ "$found_eth" = 1 ] || say "brak statycznego Ethernetu w NetworkManagerze (patrz krok 4)"

# ── 2. test łączności ────────────────────────────────────────────────────────
step "2/4 Test łączności NetworkManagera (łącze bez internetu → na koniec)"
conn_body='# bcm-net-auto.sh: NM co 60 s sprawdza internet na każdym łączu;
# łącze bez internetu dostaje +20000 do metryki trasy domyślnej, więc ruch
# sam przechodzi na następne. Usunięcie pliku = wyłączenie.
[connectivity]
enabled=true
uri=http://nmcheck.gnome.org/check_network_status.txt
response=NetworkManager is online
interval=60
'
if [ -f "$CONN_CONF" ] && [ "$(cat "$CONN_CONF")" = "$(printf '%s' "$conn_body")" ]; then
    say "$CONN_CONF już jest"
else
    say "zapisuję $CONN_CONF"
    if [ "$DRY" = 0 ]; then
        mkdir -p "$NM_CONF_DIR"
        printf '%s' "$conn_body" > "$CONN_CONF"
        chmod 644 "$CONN_CONF"
    fi
fi

# ── 3. bez automatycznych profili dla telefonu po USB ───────────────────────
step "3/4 Telefon po USB: bez \"Wired connection N\" z metryką 100"
noauto_body='# bcm-net-auto.sh: telefon po USB (rndis/ncm) ma profil BCM bcm-car-phone
# (metryka 650) — NM nie zakłada mu własnego "Wired connection N" (metryka 100).
[main]
no-auto-default=driver:rndis_host,driver:cdc_ncm
'
if grep -rqs "^no-auto-default" "$NM_CONF_DIR" --exclude="$(basename "$NOAUTO_CONF")"; then
    warn "inny plik w $NM_CONF_DIR ustawia już no-auto-default — zostawiam (dopisz tam driver:rndis_host,driver:cdc_ncm)"
elif [ -f "$NOAUTO_CONF" ] && [ "$(cat "$NOAUTO_CONF")" = "$(printf '%s' "$noauto_body")" ]; then
    say "$NOAUTO_CONF już jest"
else
    say "zapisuję $NOAUTO_CONF"
    [ "$DRY" = 1 ] || { printf '%s' "$noauto_body" > "$NOAUTO_CONF"; chmod 644 "$NOAUTO_CONF"; }
fi
# Już utworzone profile automatyczne dla telefonu (metryka 100 na rndis/ncm).
while IFS=: read -r uuid ctype dev; do
    [ "$ctype" = "802-3-ethernet" ] && [ -n "$dev" ] || continue
    drv=$(basename "$(readlink -f "/sys/class/net/$dev/device/driver" 2>/dev/null)" 2>/dev/null || true)
    case "$drv" in
        rndis_host|cdc_ncm)
            name=$(nmcli -g connection.id connection show uuid "$uuid" 2>/dev/null || echo "?")
            case "$name" in bcm-*) ;; *)
                say "profil \"$name\" na telefonie ($dev, $drv) — usuwam, BCM ma własny"
                run nmcli connection delete uuid "$uuid" || true ;;
            esac ;;
    esac
done < <(nmcli -g UUID,TYPE,DEVICE connection show --active 2>/dev/null)

# ── 4. trasy spoza NetworkManagera ──────────────────────────────────────────
step "4/4 Trasy domyślne spoza NetworkManagera"
# ifupdown: "gateway" w stanzie static bez "metric" → dopisz metric.
if [ -f "$IFACES_FILE" ] && grep -Eq '^[[:space:]]*gateway[[:space:]]' "$IFACES_FILE"; then
    if grep -Eq '^[[:space:]]*metric[[:space:]]' "$IFACES_FILE"; then
        say "$IFACES_FILE: brama z metryką już jest — sprawdź, czy ≥ $ETH_METRIC"
    else
        say "$IFACES_FILE: brama bez metryki → dopisuję \"metric $ETH_METRIC\" (kopia .bcm-net-auto.bak)"
        if [ "$DRY" = 0 ]; then
            [ -f "$IFACES_FILE.bcm-net-auto.bak" ] || cp -p "$IFACES_FILE" "$IFACES_FILE.bcm-net-auto.bak"
            sed -i -E "s/^([[:space:]]*)gateway([[:space:]].*)$/&\n\1metric $ETH_METRIC/" "$IFACES_FILE"
        fi
        say "zastosuje się po: sudo ifdown <eth> && sudo ifup <eth> (albo restart)"
    fi
fi
# netplan: tylko podpowiedź (edycja YAML-a automatem jest zbyt ryzykowna).
if ls "$NETPLAN_DIR"/*.yaml >/dev/null 2>&1 && \
        grep -Eqs '(gateway4|via):' "$NETPLAN_DIR"/*.yaml; then
    if grep -qs 'renderer: *NetworkManager' "$NETPLAN_DIR"/*.yaml; then
        say "netplan oddaje sieć NetworkManagerowi — krok 1 to obsłużył"
    else
        warn "netplan (networkd) ustawia bramę: w $NETPLAN_DIR zamień 'gateway4: X' na"
        warn "  routes: [{to: default, via: X, metric: $ETH_METRIC}]  i uruchom: sudo netplan apply"
    fi
fi
# Ręczne trasy (ip route, rc.local, skrypty): domyślna trasa na urządzeniu,
# którym NM nie zarządza.
while read -r line; do
    dev=$(sed -n 's/.* dev \([^ ]*\).*/\1/p' <<< "$line")
    [ -n "$dev" ] || continue
    state=$(nmcli -g GENERAL.STATE device show "$dev" 2>/dev/null || echo "")
    case "$state" in
        *unmanaged*|"") warn "trasa \"$line\" nie jest z NetworkManagera ($dev). Szukaj w: rc.local, crontab, /etc/network/if-up.d, skryptach systemd (grep -r 'route add' /etc)." ;;
    esac
done < <(ip -4 route show default 2>/dev/null)

# ── koniec ──────────────────────────────────────────────────────────────────
if [ "$DRY" = 0 ]; then
    systemctl reload NetworkManager 2>/dev/null || nmcli general reload 2>/dev/null || \
        warn "nie przeładowano NM — zrób: sudo systemctl restart NetworkManager"
    sleep 3
    nmcli networking connectivity check >/dev/null 2>&1 || true
fi
step "Trasy domyślne PO zmianie (pierwsza = używana)"
ip -4 route show default || true
say "Łączność NM: $(nmcli networking connectivity 2>/dev/null || echo '?')"
say "Sprawdzenie: ip route get 1.1.1.1   (pokazuje łącze, którym idzie ruch)"
say "Cofnięcie:   sudo bash $0 --undo"
