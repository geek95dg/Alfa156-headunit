#!/data/data/com.termux/files/usr/bin/sh
# Termux:Boot — start agenta BCM (bcm_agent.py) po włączeniu telefonu w aucie.
#
# Instalacja (opis całości: nagłówek tools/car_phone/termux/bcm_agent.py):
#   mkdir -p ~/bcm_agent ~/.termux/boot
#   cp bcm_agent.py ~/bcm_agent/
#   cp boot_bcm_agent.sh ~/.termux/boot/ && chmod 700 ~/.termux/boot/boot_bcm_agent.sh
#
# termux-wake-lock trzyma procesor telefonu na nogach: termin wysyłki SMS-a
# po stłuczce pilnuje agent, więc Android nie może go uśpić. Optymalizacja
# baterii dla Termux / Termux:API / Termux:Boot musi być wyłączona.
#
# Pętla: gdy agent się wywróci (albo port jeszcze zajęty po restarcie), po
# 10 s rusza znowu. Wyjście agenta i ewentualne błędy Pythona trafiają do
# boot.log; własny log agenta (z rotacją) to agent.log w tym samym katalogu.

STATE_DIR="$HOME/.config/bcm_agent"
AGENT="$HOME/bcm_agent/bcm_agent.py"

umask 077
mkdir -p "$STATE_DIR"
termux-wake-lock

while true; do
    # boot.log nie rośnie bez końca: powyżej ~256 KB zaczyna od nowa.
    if [ -f "$STATE_DIR/boot.log" ] && [ "$(wc -c < "$STATE_DIR/boot.log")" -gt 262144 ]; then
        mv -f "$STATE_DIR/boot.log" "$STATE_DIR/boot.log.1"
    fi
    python "$AGENT" --state-dir "$STATE_DIR" >>"$STATE_DIR/boot.log" 2>&1
    rc=$?
    echo "$(date '+%Y-%m-%d %H:%M:%S') bcm_agent exited ($rc), restart in 10 s" \
        >>"$STATE_DIR/boot.log"
    sleep 10
done
