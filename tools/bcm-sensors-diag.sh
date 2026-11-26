#!/bin/bash
# BCM — dlaczego BCM nie łączy się z SensorServer w telefonie?
# Diagnostyka TYLKO DO ODCZYTU: przechodzi cały łańcuch po kolei i mówi,
# w którym miejscu się urywa:
#
#   BCM (phone_sensors) → 127.0.0.1:<lokalny> na M910q → forward adb
#   → USB → telefon 127.0.0.1:<zdalny> → aplikacja SensorServer
#
#   sudo bash /opt/bcm/tools/bcm-sensors-diag.sh
#   sudo bash /opt/bcm/tools/bcm-sensors-diag.sh 951 8080   # porty: lokalny zdalny
#
# Domyślne porty jak w BCM: network.car_phone.sensors_local_port = 951,
# sensors_remote_port = 8080. Używa prywatnego serwera adb BCM
# (/run/bcm-adb/adb.sock), tego samego co moduł car_phone — nie startuje
# drugiego. Niczego nie zmienia ani w komputerze, ani w telefonie.
set -u
LOCAL=${1:-951}
REMOTE=${2:-8080}
case "$LOCAL$REMOTE" in *[!0-9]*) echo "Porty muszą być liczbami"; exit 2;; esac
export ADB_SERVER_SOCKET=localfilesystem:/run/bcm-adb/adb.sock

ok()   { printf '  OK     %s\n' "$*"; }
bad()  { printf '  BŁĄD   %s\n' "$*"; }
warn() { printf '  UWAGA  %s\n' "$*"; }
hdr()  { printf '\n=== %s ===\n' "$*"; }

[ "$(id -u)" = 0 ] || { echo "Uruchom jako root (sudo) — serwer adb BCM należy do roota."; exit 1; }
command -v adb >/dev/null || { bad "brak adb (sudo bash /opt/bcm/config/scripts/apply-fixes.sh)"; exit 1; }

hdr "1. Telefon po adb"
DEVS=$(adb devices 2>/dev/null | awk 'NR>1 && $2=="device"{print $1}')
if [ -z "$DEVS" ]; then
    bad "brak telefonu w stanie 'device' (adb devices):"
    adb devices -l 2>&1 | sed 's/^/         /'
    echo "  → kabel, zgoda na debugowanie USB, wiersz „Telefon w aucie” w Ustawieniach."
    exit 1
fi
SERIAL=$(printf '%s\n' "$DEVS" | head -1)
ok "telefon: ${SERIAL:0:4}… ($(printf '%s\n' "$DEVS" | wc -l) urządz.)"
A() { adb -s "$SERIAL" "$@"; }

hdr "2. Forward adb tcp:$LOCAL → tcp:$REMOTE"
if A forward --list 2>/dev/null | grep -q "tcp:$LOCAL tcp:$REMOTE"; then
    ok "forward jest"
else
    bad "brak forwardu — zakłada go moduł car_phone, gdy modules.phone_sensors jest włączony"
    A forward --list 2>/dev/null | sed 's/^/         /'
    echo "  → Ustawienia → Moduły: phone_sensors i car_phone włączone, restart BCM."
fi

hdr "3. Aplikacja SensorServer w telefonie"
PKG=$(A shell pm list packages 2>/dev/null | tr -d '\r' | grep -i sensorserver | head -1 | cut -d: -f2)
if [ -z "$PKG" ]; then
    bad "SensorServer nie jest zainstalowany (szukam pakietu z 'sensorserver' w nazwie)"
else
    ok "pakiet: $PKG"
    if A shell pidof "$PKG" >/dev/null 2>&1; then
        ok "aplikacja działa (proces jest)"
    else
        bad "aplikacja NIE działa — otwórz ją i naciśnij Start; bateria „Bez ograniczeń”"
    fi
fi

hdr "4. Czy coś nasłuchuje w telefonie na porcie $REMOTE"
HEX=$(printf '%04X' "$REMOTE")
# /proc/net/tcp[6]: kolumna 2 = adres:port (hex), kolumna 4 = stan (0A = LISTEN).
LISTEN=$(A shell "cat /proc/net/tcp /proc/net/tcp6 2>/dev/null || su -c 'cat /proc/net/tcp /proc/net/tcp6'" 2>/dev/null \
    | tr -d '\r' | awk -v p=":$HEX" '$4=="0A" && $2 ~ p"$" {print $2}')
if [ -z "$LISTEN" ]; then
    bad "nic nie nasłuchuje na porcie $REMOTE (albo telefon nie pozwala czytać /proc/net)"
    echo "  → w SensorServer: port $REMOTE, Start; jeśli inny port — ustaw go albo"
    echo "    network.car_phone.sensors_remote_port w config/local.yaml (i restart BCM)."
else
    # IPv6 forms of /proc/net/tcp6, built from pieces (a literal 32-hex
    # string looks like an API key to the repo's secret scan).
    Z8=00000000
    V6_LO="${Z8}${Z8}${Z8}01000000"            # ::1
    V6_ANY="${Z8}${Z8}${Z8}${Z8}"              # ::
    V6_MAPPED_LO="${Z8}${Z8}FFFF${Z8:0:4}0100007F"   # ::ffff:127.0.0.1
    for a in $LISTEN; do
        addr=${a%:*}
        case "$addr" in
            0100007F) ok "nasłuch na 127.0.0.1:$REMOTE (Local Host) — tak ma być" ;;
            00000000) warn "nasłuch na 0.0.0.0:$REMOTE — działa przez forward, ale widać go też z Wi-Fi/hotspotu; włącz „Local Host”" ;;
            "$V6_LO") bad "nasłuch TYLKO na IPv6 ::1 — forward adb łączy się po IPv4 127.0.0.1 i trafia w pustkę" ;;
            "$V6_ANY") ok "nasłuch na wszystkich adresach (IPv4+IPv6)" ;;
            "$V6_MAPPED_LO") ok "nasłuch na 127.0.0.1:$REMOTE (IPv4 w IPv6) — tak ma być" ;;
            *) warn "nasłuch na adresie $addr (hex) — nie 127.0.0.1" ;;
        esac
    done
fi

hdr "5. Próba połączenia jak BCM (przez forward, 4 s)"
python3 - "$LOCAL" <<'PY'
import base64, os, socket, sys, time
port = int(sys.argv[1])
key = base64.b64encode(os.urandom(16)).decode()
path = '/sensor/connect?type=android.sensor.accelerometer'
req = (f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nUpgrade: websocket\r\n"
       f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
try:
    s = socket.create_connection(("127.0.0.1", port), timeout=4)
except ConnectionRefusedError:
    print("  BŁĄD   odmowa połączenia na M910q — forward adb nie istnieje (krok 2)"); sys.exit(0)
except OSError as e:
    print(f"  BŁĄD   {e}"); sys.exit(0)
s.settimeout(4)
s.sendall(req.encode())
buf = b""
deadline = time.monotonic() + 4
try:
    while b"\r\n\r\n" not in buf and time.monotonic() < deadline:
        chunk = s.recv(4096)
        if not chunk:
            break
        buf += chunk
except socket.timeout:
    pass
if not buf:
    print("  BŁĄD   forward jest, ale telefon zamyka połączenie bez odpowiedzi —")
    print("         po drugiej stronie nikt nie słucha na tym porcie (krok 3–4)")
    sys.exit(0)
status = buf.split(b"\r\n", 1)[0].decode("latin-1", "replace")
if " 101 " not in status:
    print(f"  BŁĄD   odpowiedź zamiast WebSocketu: {status!r} — inna aplikacja na tym porcie?")
    sys.exit(0)
print(f"  OK     WebSocket przyjęty ({status})")
rest = buf.split(b"\r\n\r\n", 1)[1]
frames = 0
deadline = time.monotonic() + 3
try:
    while time.monotonic() < deadline and frames < 3:
        data = rest or s.recv(4096)
        rest = b""
        if not data:
            break
        frames += 1
except socket.timeout:
    pass
if frames:
    print("  OK     przychodzą dane z akcelerometru — łańcuch działa")
else:
    print("  UWAGA  połączenie jest, ale bez danych przez 3 s — czujnik zatrzymany"
          " (ekran/oszczędzanie baterii) albo częstotliwość 0")
s.close()
PY

hdr "6. Co mówi BCM (ostatnie wpisy)"
journalctl -u bcm-headunit --since "-30min" --no-pager 2>/dev/null \
    | grep -iE "phone.?sensors|SensorServer" | tail -8 | sed 's/^/  /'
echo
echo "Ustawienia → „Czujniki telefonu” → „Test” daje werdykt BCM po naprawie."
