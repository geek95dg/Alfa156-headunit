#!/bin/bash
# BCM — diagnostyka audio: nasłuch Android Auto (zawieszenie / brzęczenie)
# i rozmowy przez Bluetooth (HFP / oFono).
#
#   sudo bash /opt/bcm/tools/bcm-audio-diag.sh             # odczyt + pytania o testy
#   sudo bash /opt/bcm/tools/bcm-audio-diag.sh --no-tests  # tylko odczyt
#
# Domyślnie TYLKO CZYTA: wersje, karty, graf PipeWire, domyślne źródło,
# sekcje [Audio]/[Input] z openauto.ini (nigdy [WiFi] — tam jest hasło),
# stan oFono i polityki D-Bus, ostatnie wpisy dziennika. Na końcu proponuje
# testy rozstrzygające; każdy rusza dopiero po odpowiedzi "t"/"y":
#   (A) w trakcie brzęczenia wycisza na 5 s TYLKO strumień autoapp i go
#       odcisza (jedyna zmiana stanu w tym skrypcie, odwracalna) —
#       brzęczenie ustaje => to pętla bufora w autoapp (RtAudio), nie karta;
#   (B) przy grającej muzyce 15 s nagrywa wejście karty USB do /dev/null,
#       pokazując dziennik jądra i pw-top — zawieszenie/brzęczenie => karta
#       nie radzi sobie z pracą duplex (wejście + wyjście naraz);
#   (C) podpowiedzi do testu rozmowy (+ opcjonalnie 60 s btmon).
set -u

BCM_DIR=${BCM_DIR:-/opt/bcm}
RUN_TESTS=1
[ "${1:-}" = "--no-tests" ] && RUN_TESTS=0

if [ -t 1 ]; then
    C_H='\033[1;36m'; C_OK='\033[0;32m'; C_W='\033[1;33m'; C_E='\033[0;31m'; C_N='\033[0m'
else
    C_H=''; C_OK=''; C_W=''; C_E=''; C_N=''
fi
hdr()  { echo -e "\n${C_H}=== $* ===${C_N}"; }
ok()   { echo -e "  ${C_OK}OK${C_N}   $*"; }
warn() { echo -e "  ${C_W}UWAGA${C_N} $*"; }
bad()  { echo -e "  ${C_E}BŁĄD${C_N}  $*"; }
info() { echo "  $*"; }
have() { command -v "$1" >/dev/null 2>&1; }

# Pytanie t/N z terminala; bez terminala (np. potok) — zawsze "nie".
confirm() {
    local answer=""
    [ -r /dev/tty ] || return 1
    read -r -p "  $1 [t/N] " answer </dev/tty || return 1
    [[ "$answer" =~ ^[tTyY]$ ]]
}

# ─── Użytkownik sesji (PipeWire/WirePlumber działają jako on) ───────────
# Jak w setup-x86.sh/apply-fixes.sh: BCM_USER, potem autologin z
# getty@tty1, potem SUDO_USER, na końcu domyślny "abner".
AUTOLOGIN_CONF=/etc/systemd/system/getty@tty1.service.d/autologin.conf
if [ -z "${BCM_USER:-}" ] && [ -f "$AUTOLOGIN_CONF" ]; then
    BCM_USER=$(sed -n 's/.*--autologin[[:space:]]\{1,\}\([^[:space:]]\{1,\}\).*/\1/p' "$AUTOLOGIN_CONF" | head -n1)
fi
if [ -z "${BCM_USER:-}" ] && [ -n "${SUDO_USER:-}" ] && [ "${SUDO_USER}" != "root" ]; then
    BCM_USER=$SUDO_USER
fi
BCM_USER=${BCM_USER:-abner}
if ! [[ "$BCM_USER" =~ ^[A-Za-z_][A-Za-z0-9_.-]*$ ]]; then
    bad "niepoprawna nazwa użytkownika: '$BCM_USER'"; exit 1
fi
U_UID=$(id -u "$BCM_USER" 2>/dev/null || true)
U_HOME=$(getent passwd "$BCM_USER" 2>/dev/null | cut -d: -f6)
if [ -z "$U_UID" ]; then
    bad "użytkownik '$BCM_USER' nie istnieje (ustaw BCM_USER=...)"; exit 1
fi
# U: uruchom polecenie w sesji audio użytkownika (tablica, bez eval).
# LC_ALL=C: część wyjścia jest parsowana (pactl, wpctl), a sudo zachowuje
# LANG/LC_* — po polsku pactl pisze "Wejście odpływu #42" zamiast
# "Sink Input #42" i parser zwracał puste identyfikatory.
if [ "$(id -u)" -eq 0 ]; then
    U=(sudo -u "$BCM_USER" LC_ALL=C "XDG_RUNTIME_DIR=/run/user/$U_UID")
else
    U=(env LC_ALL=C "XDG_RUNTIME_DIR=/run/user/$U_UID")
fi

echo "BCM — diagnostyka audio ($(date '+%F %T'))"
info "użytkownik sesji: $BCM_USER (uid $U_UID), runtime /run/user/$U_UID"
[ "$(id -u)" -eq 0 ] || warn "nie jako root — część odczytów (dziennik, busctl) może być niepełna"

# ─── 1. Wersje ──────────────────────────────────────────────────────────
hdr "1. Wersje"
if [ -r /etc/os-release ]; then
    info "system:      $(. /etc/os-release && echo "${PRETTY_NAME:-?}")"
fi
info "jądro:       $(uname -r)"
info "pipewire:    $(pipewire --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | tail -n1 || echo brak)"
WP_VER=$(wireplumber --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+(\.[0-9]+)?' | head -n1)
info "wireplumber: ${WP_VER:-brak}"
if [ -n "$WP_VER" ]; then
    WP_MAJOR=${WP_VER%%.*}; WP_MINOR=${WP_VER#*.}; WP_MINOR=${WP_MINOR%%.*}
    if [ "$WP_MAJOR" -eq 0 ] && [ "$WP_MINOR" -lt 5 ]; then
        bad "WirePlumber < 0.5: drop-in 51-bcm-hfp-ofono.conf (składnia 0.5) jest ignorowany"
    fi
fi
if have dpkg-query; then
    for pkg in ofono wireplumber pipewire pipewire-pulse libspa-0.2-bluetooth \
               libqt5multimedia5-plugins pulseaudio-utils; do
        ver=$(dpkg-query -W -f='${Version} ${db:Status-Status}' "$pkg" 2>/dev/null || true)
        case "$ver" in
            *" installed") info "pakiet $pkg: ${ver% installed}" ;;
            *) if [ "$pkg" = ofono ] || [ "$pkg" = libspa-0.2-bluetooth ] \
                  || [ "$pkg" = libqt5multimedia5-plugins ]; then
                   bad "pakiet $pkg: NIEZAINSTALOWANY"
               else
                   info "pakiet $pkg: niezainstalowany"
               fi ;;
        esac
    done
fi
if command -v ofonod >/dev/null 2>&1 || [ -x /usr/sbin/ofonod ]; then
    ok "ofonod obecny"
else
    bad "brak ofonod — rozmowy nie trafią do headunitu"
fi

# ─── 2. Pozostałości konfiguracji PipeWire/WirePlumber ─────────────────
hdr "2. Pliki konfiguracji (pozostałości po starych instalacjach)"
for dir in /etc/pipewire /etc/wireplumber "$U_HOME/.config/pipewire" "$U_HOME/.config/wireplumber"; do
    if [ -d "$dir" ]; then
        files=$(find "$dir" -maxdepth 3 -type f 2>/dev/null | sort)
        if [ -n "$files" ]; then
            info "$dir:"
            echo "$files" | sed 's/^/      /'
        else
            info "$dir: (pusty)"
        fi
    fi
done
[ -f /etc/wireplumber/wireplumber.conf.d/51-bcm-hfp-ofono.conf ] \
    && ok "51-bcm-hfp-ofono.conf zainstalowany" \
    || bad "brak /etc/wireplumber/wireplumber.conf.d/51-bcm-hfp-ofono.conf (apply-fixes.sh)"

# ─── 3. Karty dźwiękowe i USB ───────────────────────────────────────────
hdr "3. Karty dźwiękowe"
if [ -r /proc/asound/cards ]; then
    sed 's/^/  /' /proc/asound/cards
else
    warn "brak /proc/asound/cards"
fi
if have lsusb; then
    hdr "3b. Urządzenia USB"
    lsusb | sed 's/^/  /'
fi

# ─── 4. Graf PipeWire ───────────────────────────────────────────────────
hdr "4. wpctl status"
if have wpctl; then
    "${U[@]}" wpctl status 2>&1 | sed 's/^/  /' || bad "wpctl status nie odpowiada — sesja PipeWire nie działa?"
else
    bad "brak wpctl"
fi

# ─── 5. Domyślne źródło (to bierze asystent AA i rozmowa) ──────────────
hdr "5. Domyślne źródło (mikrofon dla AA i rozmów)"
if have wpctl; then
    SRC_INFO=$("${U[@]}" wpctl inspect @DEFAULT_AUDIO_SOURCE@ 2>&1 || true)
    echo "$SRC_INFO" | grep -E 'node\.name|node\.description|media\.class|api\.alsa\.path|device\.id' | sed 's/^/  /'
    SRC_NAME=$(echo "$SRC_INFO" | sed -n 's/.*node\.name = "\(.*\)".*/\1/p' | head -n1)
    case "$SRC_NAME" in
        "") bad "brak domyślnego źródła" ;;
        *.monitor) bad "domyślne źródło to MONITOR wyjścia ($SRC_NAME) — asystent słyszy własne audio auta" ;;
        bcm_null_mic) warn "domyślne źródło to cisza (bcm_null_mic) — brak mikrofonu, głos AA wyłączony" ;;
        bcm_mic) ok "mikrofon z redukcją echa (bcm_mic)" ;;
        alsa_input.*) ok "mikrofon: $SRC_NAME" ;;
        *) warn "nietypowe domyślne źródło: $SRC_NAME" ;;
    esac
fi

# ─── 6. openauto.ini ([Audio] i [Input] — bez [WiFi]) ──────────────────
hdr "6. openauto.ini: [Audio] i [Input]"
INI="$BCM_DIR/openauto.ini"
if [ -r "$INI" ]; then
    awk '/^\[/{show=($0=="[Audio]"||$0=="[Input]")} show' "$INI" | sed 's/^/  /'
    if grep -q '^OutputBackendType=1' "$INI"; then
        ok "backend audio autoapp: Qt (suspend działa)"
    else
        warn "backend audio autoapp: RtAudio — znany z pętli bufora (brzęczenie); multimedia.aa_audio_backend: qt"
    fi
else
    warn "brak $INI (autoapp jeszcze nie startował?)"
fi

# ─── 7. oFono i polityka D-Bus ──────────────────────────────────────────
hdr "7. oFono (rozmowy)"
if have systemctl; then
    info "ofono.service: $(systemctl is-active ofono 2>/dev/null || true)"
fi
if have busctl; then
    if busctl --system list 2>/dev/null | grep -q '^org\.ofono '; then
        ok "org.ofono jest na szynie systemowej"
        MODEMS=$(busctl --system call org.ofono / org.ofono.Manager GetModems 2>&1 || true)
        echo "$MODEMS" | tr ' ' '\n' | grep -E '^"/' | sed 's/^/  modem: /' || true
        if echo "$MODEMS" | grep -q 'org.ofono.VoiceCallManager'; then
            ok "jest modem z VoiceCallManager (telefon połączony przez HFP)"
        else
            warn "brak modemu z VoiceCallManager — telefon nie jest połączony przez HFP?"
        fi
    else
        bad "org.ofono NIE jest na szynie — ofonod nie działa"
    fi
fi
POLICY=/etc/dbus-1/system.d/bcm-ofono-pipewire.conf
if [ -r "$POLICY" ]; then
    if grep -q "policy user=\"$BCM_USER\"" "$POLICY"; then
        ok "polityka D-Bus $POLICY dla $BCM_USER"
    else
        bad "$POLICY nie dotyczy użytkownika $BCM_USER:"
        sed 's/^/      /' "$POLICY"
    fi
else
    bad "brak $POLICY — WirePlumber nie zarejestruje agenta oFono (apply-fixes.sh)"
fi

# ─── 8. Dziennik: znane błędy ───────────────────────────────────────────
hdr "8. Dziennik (ostatnie wpisy, znane błędy)"
if have journalctl; then
    PATTERN='Register\(\) failed|oFono not available|Rejecting|HandsfreeAudio|ofono|sco|SCO'
    info "-- ofono --"
    journalctl -u ofono -n 30 --no-pager 2>/dev/null | sed 's/^/    /' || true
    info "-- wireplumber (użytkownik $BCM_USER) --"
    journalctl "_SYSTEMD_USER_UNIT=wireplumber.service" "_UID=$U_UID" -n 300 --no-pager 2>/dev/null \
        | grep -E "$PATTERN" | tail -n 30 | sed 's/^/    /' || true
    for needle in 'Register() failed' 'oFono not available' 'Rejecting'; do
        if journalctl -b --no-pager 2>/dev/null | grep -qF "$needle"; then
            bad "w dzienniku od startu: \"$needle\""
        fi
    done
    info "-- BCM (mikrofon, rozmowy) --"
    journalctl -u bcm-headunit -n 2000 --no-pager 2>/dev/null \
        | grep -E 'Mic state|Default source|Mic router|AA audio|Call audio|oFono|Echo cancel' \
        | tail -n 20 | sed 's/^/    /' || true
fi

# ─── 9. Redukcja echa ───────────────────────────────────────────────────
hdr "9. Redukcja echa (AEC)"
AEC_LIB=$(ls /usr/lib/*/spa-0.2/aec/libspa-aec-webrtc.so /usr/lib64/spa-0.2/aec/libspa-aec-webrtc.so 2>/dev/null | head -n1)
if [ -n "$AEC_LIB" ]; then
    ok "jest $AEC_LIB (audio.mic_echo_cancel: auto zadziała)"
else
    info "brak libspa-aec-webrtc.so — audio.mic_echo_cancel: auto zostanie wyłączone"
fi

[ "$RUN_TESTS" -eq 1 ] || { echo; echo "Koniec (bez testów)."; exit 0; }

# ─── Testy rozstrzygające (tylko po potwierdzeniu) ──────────────────────

# Węzły z pw-dump: "id<TAB>nazwa" dla strumieni autoapp / wejść USB.
pw_nodes() {
    "${U[@]}" pw-dump 2>/dev/null | python3 -c '
import json, sys
kind = sys.argv[1]
try:
    objs = json.load(sys.stdin)
except Exception:
    sys.exit(0)
for o in objs:
    if not str(o.get("type", "")).endswith("Interface:Node"):
        continue
    p = (o.get("info") or {}).get("props") or {}
    name = str(p.get("node.name", ""))
    cls = str(p.get("media.class", ""))
    app = (str(p.get("application.process.binary", "")) + " " + str(p.get("application.name", ""))).lower()
    if kind == "autoapp" and cls == "Stream/Output/Audio" and ("autoapp" in app or "openauto" in app):
        print("%s\t%s" % (o.get("id"), name))
    elif kind == "usbin" and cls == "Audio/Source" and name.startswith("alsa_input.usb-"):
        print("%s\t%s" % (o.get("id"), name))
' "$1"
}

hdr "Test A: czy brzęczenie to pętla bufora autoapp?"
info "Uruchom, gdy brzęczy (po nasłuchu AA). Wycisza na 5 s TYLKO strumienie autoapp."
if confirm "Wykonać test A teraz?"; then
    MUTED=()        # identyfikatory, które trzeba odciszyć (pułapka niżej)
    N_MUTED=0       # ile wyciszeń faktycznie się udało
    MUTE_TOOL=""
    set_mute() {    # set_mute <id> <0|1>
        if [ "$MUTE_TOOL" = pactl ]; then
            "${U[@]}" pactl set-sink-input-mute "$1" "$2"
        else
            "${U[@]}" wpctl set-mute "$1" "$2"
        fi
    }
    restore_mute() {
        local id
        for id in "${MUTED[@]}"; do set_mute "$id" 0 >/dev/null 2>&1 || true; done
        MUTED=()
    }
    # Pułapka PRZED pętlą wyciszania: Ctrl-C w jej trakcie też odcisza.
    trap restore_mute EXIT
    trap 'restore_mute; exit 130' INT TERM

    # Identyfikatory z pw-dump (JSON, niezależny od języka) + wpctl; pactl
    # tylko jako zapas, gdy nie ma python3/wpctl.
    CANDIDATES=()
    if have wpctl && have python3; then
        MUTE_TOOL=wpctl
        mapfile -t CANDIDATES < <(pw_nodes autoapp | cut -f1)
    fi
    if [ "${#CANDIDATES[@]}" -eq 0 ] && have pactl && "${U[@]}" pactl info >/dev/null 2>&1; then
        MUTE_TOOL=pactl
        mapfile -t CANDIDATES < <("${U[@]}" pactl list sink-inputs 2>/dev/null | awk '
            /^Sink Input #/ {id=substr($3,2)}
            /application.process.binary = "autoapp"/ {print id}')
    fi
    for id in "${CANDIDATES[@]}"; do
        # Tylko liczby: pusty lub dziwny identyfikator nie trafia do wpctl/pactl.
        [[ "$id" =~ ^[0-9]+$ ]] || continue
        MUTED+=("$id")   # najpierw na listę — pułapka odciszy go w każdym razie
        if set_mute "$id" 1; then N_MUTED=$((N_MUTED + 1)); fi
    done

    if [ "$N_MUTED" -eq 0 ]; then
        restore_mute
        warn "nie znaleziono / nie wyciszono strumieni autoapp (AA nie gra?) — test pominięty, brak wniosku"
    else
        info "wyciszone strumienie autoapp ($MUTE_TOOL): ${MUTED[*]} — słuchaj przez 5 s..."
        sleep 5
        restore_mute
        ok "odciszone"
        info "Brzęczenie ucichło na 5 s => pętla bufora w autoapp (włącz multimedia.aa_audio_backend: qt)."
        info "Brzęczało dalej => źródło inne niż autoapp (karta/wzmacniacz/masa)."
    fi
    trap - EXIT INT TERM
fi

hdr "Test B: czy karta USB wytrzymuje duplex?"
info "Puść muzykę. Przez 15 s nagrywamy wejście karty USB do /dev/null i patrzymy na błędy."
if confirm "Wykonać test B teraz?"; then
    USB_IN=$(pw_nodes usbin | head -n1 | cut -f2)
    if [ -z "$USB_IN" ]; then
        warn "brak wejścia alsa_input.usb-* (profil karty bez wejścia?) — test pominięty"
    elif ! have pw-record; then
        warn "brak pw-record — test pominięty"
    else
        info "nagrywam z: $USB_IN"
        if have journalctl; then
            timeout 16 journalctl -k -f -n 0 --no-pager 2>/dev/null | sed 's/^/  [jądro] /' &
        fi
        "${U[@]}" timeout 15 pw-record --target "$USB_IN" - >/dev/null 2>&1 &
        if have pw-top; then
            "${U[@]}" timeout 15 pw-top -b 2>/dev/null | grep -E 'ERR|^ *[RS] ' | tail -n 20 | sed 's/^/  [pw-top] /'
        else
            sleep 15
        fi
        wait
        info "Muzyka się zacięła / brzęczała / w jądrze błędy USB (xHCI, 'cannot submit urb')"
        info "=> karta nie radzi sobie z duplexem: zostaw ją tylko na wyjście (audio.mic_disable_unused_inputs)"
        info "   i dołóż osobny mikrofon USB. Czysto => mikrofon może iść do gniazda tej karty."
    fi
fi

hdr "Test C: rozmowa"
info "1. Zadzwoń na telefon. Na ekranie A8 powinna pojawić się nakładka połączenia."
info "2. Odbierz z ekranu albo SWC. W logu BCM: 'Call audio: downlink ... uplink ...'."
info "3. Słyszysz rozmówcę? (downlink -> bcm_eq_sink). Rozmówca słyszy Ciebie? (uplink <- mikrofon)."
info "4. Błędy SCO widać w btmon: szukaj 'SCO', 'eSCO', 'Error', 'Failed'."
if have btmon && confirm "Uruchomić teraz btmon na 60 s (tylko podgląd)?"; then
    timeout 60 btmon 2>/dev/null | grep -iE 'sco|esco|error|fail|disconn' | sed 's/^/  [btmon] /'
fi
echo
echo "Koniec."
