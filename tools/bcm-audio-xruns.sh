#!/bin/bash
# BCM — dlaczego muzyka „przycina”? Diagnostyka tylko do odczytu.
#
#   sudo bash /opt/bcm/tools/bcm-audio-xruns.sh          # 20 s pomiaru
#   sudo bash /opt/bcm/tools/bcm-audio-xruns.sh 60       # 60 s pomiaru
#
# Uruchom, GDY GRA MUZYKA (najlepiej, gdy przycina). Niczego nie zmienia.
# Pokazuje:
#  1. priorytet czasu rzeczywistego PipeWire (bez niego każde obciążenie
#     procesora może dać dziurę w dźwięku) i czy jest rtkit;
#  2. pw-top: licznik ERR (xrun = PipeWire nie zdążył z blokiem dźwięku)
#     dla każdego węzła — na początku i na końcu pomiaru;
#  3. obciążenie procesora i najbardziej zajęte procesy;
#  4. błędy USB / karty dźwiękowej w dzienniku jądra (ostatnia godzina);
#  5. zdarzenia BCM z ostatniej godziny, które przerywają lub ściszają
#     muzykę: restart korektora, ściszanie przy komunikatach, rozmowy.
set -u
SECS=${1:-20}
case "$SECS" in ''|*[!0-9]*) echo "Podaj liczbę sekund"; exit 2;; esac

hdr() { printf '\n=== %s ===\n' "$*"; }

# PipeWire działa w sesji użytkownika (uid 1000, użytkownik kiosku).
UID_PW=1000
USER_PW=$(id -nu "$UID_PW" 2>/dev/null || echo "")
RUNTIME=/run/user/$UID_PW
as_user() {
    if [ -n "$USER_PW" ] && [ "$(id -u)" = 0 ]; then
        runuser -u "$USER_PW" -- env XDG_RUNTIME_DIR="$RUNTIME" "$@"
    else
        env XDG_RUNTIME_DIR="$RUNTIME" "$@"
    fi
}

hdr "1. Priorytet czasu rzeczywistego"
if systemctl cat rtkit-daemon.service >/dev/null 2>&1; then
    echo "  rtkit: zainstalowany ($(systemctl is-active rtkit-daemon 2>/dev/null))"
else
    echo "  UWAGA: brak rtkit — PipeWire bez priorytetu RT (naprawa: sudo bash /opt/bcm/config/scripts/apply-fixes.sh)"
fi
echo "  Wątki PipeWire (CLS FF/RR = czas rzeczywisty, TS = zwykły):"
ps -eLo pid,cls,rtprio,ni,comm 2>/dev/null | awk 'NR==1 || /pipewire|data-loop|wireplumber/' | sed 's/^/    /'

hdr "2. pw-top — xruny (kolumna ERR) na starcie i po ${SECS} s"
if command -v pw-top >/dev/null 2>&1; then
    as_user pw-top -b -n 2 2>/dev/null | tail -n +1 | sed 's/^/    /' | head -40
    echo "  … mierzę ${SECS} s (graj muzykę) …"
    sleep "$SECS"
    as_user pw-top -b -n 2 2>/dev/null | sed 's/^/    /' | head -40
    echo "  ERR rośnie przy węźle karty USB / bcm_eq_sink = PipeWire nie nadąża (RT, obciążenie)."
    echo "  ERR rośnie przy bluez_* = problem po stronie Bluetooth (zasięg, Wi-Fi tego samego radia)."
else
    echo "  brak pw-top (pakiet pipewire-bin)"
fi

hdr "3. Obciążenie procesora"
uptime | sed 's/^/  /'
top -b -n 1 2>/dev/null | sed -n '7,17p' | sed 's/^/  /'

hdr "4. Jądro: USB / karta dźwiękowa (ostatnia godzina)"
journalctl -k --since "-60min" --no-pager 2>/dev/null \
    | grep -iE "usb .*(reset|disconnect)|xhci|snd[-_]usb|underrun|over-current" \
    | tail -15 | sed 's/^/  /' || true
echo "  (pusto = brak błędów USB)"

hdr "5. BCM: co przerywało / ściszało muzykę (ostatnia godzina)"
J=$(journalctl -u bcm-headunit --since "-60min" --no-pager 2>/dev/null)
count() { printf '%s\n' "$J" | grep -cE "$1" || true; }
echo "  restarty korektora (EQ, przerwa ~0,5–2 s): $(count 'EQ filter-chain started')"
echo "  ściszenia (komunikat / rozmowa / cofanie):  $(count 'Priority activated')"
echo "  komunikaty głosowe:                          $(count 'Voice: speech engine|announcement')"
echo "  restarty analizatora widma:                  $(count 'Spectrum capture ended')"
printf '%s\n' "$J" | grep -E "EQ filter-chain started|Priority activated|Ducking:" | tail -8 | sed 's/^/    /'

hdr "Jak czytać"
cat <<'TXT'
  - wątki PipeWire w klasie TS (nie FF/RR) albo brak rtkit → uruchom
    apply-fixes.sh (instaluje rtkit), zrestartuj komputer;
  - ERR rośnie przy bluez_* → przerywa Bluetooth, nie komputer: telefon bliżej,
    bez Wi-Fi 2,4 GHz w telefonie, sprawdź z wyłączonym Android Auto;
  - dużo „restartów korektora” → coś zmienia EQ (preset, echo-cancel) — napisz;
  - „ściszenia” w chwilach przycięcia → to komunikaty/rozmowy, nie błąd.
TXT
