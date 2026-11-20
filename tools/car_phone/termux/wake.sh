#!/data/data/com.termux/files/usr/bin/sh
# Termux:Widget — budzenie komputera w aucie podczerwienią (plan E, TYLKO
# wersja z buforem: Nano #2 z FEATURE_WAKE_IR i odbiornikiem TSOP na A3).
#
# Instalacja (telefon w aucie, Termux z F-Droid; opis całości: nagłówek
# tools/car_phone/termux/bcm_agent.py, „Budzenie komputera w aucie”):
#   pkg install termux-api            # termux-infrared-transmit, termux-toast
#   mkdir -p ~/.shortcuts
#   cp wake.sh ~/.shortcuts/ && chmod 700 ~/.shortcuts/wake.sh
#   # Termux:Widget (F-Droid) → widżet na ekranie → „wake.sh”
#
# Co robi: jedno `bcm_agent.py --wake` — ten sam limit (1 próba na minutę,
# 3 udane na godzinę, 6 na dobę) i ta sama blokada pliku co polecenie SMS
# „WAKE <kod>” w działającym agencie. Kod IR (adres i polecenie NEC)
# i przełącznik remote_session przychodzą z BCM (config.json agenta); ten
# skrypt NICZEGO nie przekazuje dalej — żadnych argumentów od użytkownika,
# tylko stałe teksty komunikatów. Agent sam wysyła 3 ramki IR; czy komputer
# wstanie, decyduje Nano (zapłon zgaszony, limit, bank).

STATE_DIR="$HOME/.config/bcm_agent"
AGENT="$HOME/bcm_agent/bcm_agent.py"

umask 077
mkdir -p "$STATE_DIR"
python "$AGENT" --state-dir "$STATE_DIR" --wake
rc=$?

case "$rc" in
    0) msg="BCM: budzenie wyslane" ;;
    3) msg="BCM: budzenie wylaczone (modules.remote_session w BCM)" ;;
    4) msg="BCM: limit budzenia - sprobuj za minute" ;;
    5) msg="BCM: trwa inne budzenie" ;;
    *) msg="BCM: budzenie nieudane (nadajnik IR, Termux:API?)" ;;
esac

if command -v termux-toast >/dev/null 2>&1; then
    termux-toast "$msg"
else
    echo "$msg"
fi
exit "$rc"
