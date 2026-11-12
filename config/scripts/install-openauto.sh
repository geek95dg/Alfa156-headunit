#!/usr/bin/env bash
# BCM v8.5 — budowa OpenAuto (autoapp) ze źródeł
#
# Android Auto w tym projekcie obsługuje zewnętrzny proces `autoapp` z openDsh.
# NIE jest on instalowany przez setup-x86.sh i nie ma go w żadnym repozytorium
# pakietów — trzeba go skompilować. Dopóki go nie ma, BCM wstaje normalnie,
# ale ekran Android Auto pokazuje „OpenAuto not installed", a w logu leci
# błąd z src/multimedia/openauto.py.
#
# Skrypt automatyzuje procedurę z docs/X86_PLATFORM_SETUP.md §11.1–11.5.
#
# Użycie:
#   sudo bash config/scripts/install-openauto.sh
#
# Czas: 30–60 min na i5-6400T/7500T. Wymaga ~3 GB wolnego miejsca w /tmp
# i działającego internetu (klonuje z GitHuba).
#
# Idempotentny: gdy binarka już jest, kończy się bez pracy (--force wymusza).
#
# Android Auto tylko bezprzewodowo (BCM_AA_USB, domyślnie 0)
# ----------------------------------------------------------
# autoapp z openDsh (App::waitForDevice → waitForUSBDevice + enumerateDevices;
# aasdk USBHub z hotplugiem LIBUSB_HOTPLUG_MATCH_ANY i
# ConnectedAccessoriesEnumerator) wysyła handshake Android Open Accessory
# (AOAP) do KAŻDEGO urządzenia USB. Telefon w aucie (moduł car_phone: Redmi na
# USB przez adb, tethering USB, forward GPS) zostałby przełączony w tryb
# akcesorium AA (18d1:2d00/2d01) — to kasuje tethering i forwardy adb, a BCM
# i autoapp przełączałyby go w pętli. W tym aucie AA działa bezprzewodowo
# (Wi-Fi Direct), więc domyślnie łatamy autoapp tak, żeby w ogóle nie
# dotykał USB:
#   BCM_AA_USB=0  (domyślnie) — tylko bezprzewodowo, USB nietknięte;
#   BCM_AA_USB=1  — zachowanie upstream (AA także po kablu USB).
# Łatka nie przejdzie po cichu: gdy upstream zmieni App.cpp i wzorca nie ma,
# skrypt kończy się błędem. Zmiana BCM_AA_USB działa dopiero po przebudowie:
#   sudo BCM_AA_USB=0 bash config/scripts/install-openauto.sh --force
# Tryb zbudowanej binarki zapisujemy w $MODE_FILE — bez niego (stara
# instalacja) skrypt ostrzega, że trzeba przebudować z --force.

set -euo pipefail

FORCE=0
[[ "${1:-}" == "--force" ]] && FORCE=1

BIN=/usr/local/bin/autoapp
WORK="${OPENAUTO_WORKDIR:-/tmp/bcm-openauto-build}"
MODE_FILE=/usr/local/share/bcm/autoapp-build-mode
BCM_AA_USB="${BCM_AA_USB:-0}"

log()  { printf '\n\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[uwaga]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[błąd]\033[0m %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Uruchom przez sudo — instalacja idzie do /usr/local."

case "$BCM_AA_USB" in
    0|1) ;;
    *) die "BCM_AA_USB=$BCM_AA_USB — dozwolone tylko 0 (AA tylko bezprzewodowo) albo 1 (także USB)." ;;
esac

if [[ -x "$BIN" && $FORCE -eq 0 ]]; then
    log "autoapp już jest: $BIN"
    ls -la "$BIN"
    built=$(cat "$MODE_FILE" 2>/dev/null || true)
    if [[ "$built" != "BCM_AA_USB=$BCM_AA_USB" ]]; then
        warn "Binarka zbudowana z '${built:-bez łatki USB (stara instalacja)}', a wybrano BCM_AA_USB=$BCM_AA_USB."
        warn "Telefon w aucie na USB (car_phone) wymaga BCM_AA_USB=0. Przebuduj:"
        warn "  sudo BCM_AA_USB=$BCM_AA_USB bash $0 --force"
    fi
    echo "Nic do roboty. Wymuszenie przebudowy: $0 --force"
    exit 0
fi

command -v git >/dev/null || die "Brak gita. apt install git"

# ---------------------------------------------------------------- 11.1 zależności
log "Instaluję zależności budowania (to potrwa)"
apt-get update
apt-get install -y \
    cmake build-essential git \
    libboost-all-dev libusb-1.0-0-dev libssl-dev \
    libprotobuf-dev protobuf-compiler \
    qtbase5-dev qtchooser qt5-qmake qtbase5-dev-tools \
    qtmultimedia5-dev libqt5multimedia5-plugins \
    qtconnectivity5-dev qtdeclarative5-dev \
    qml-module-qtquick2 qml-module-qtquick-controls2 \
    libqt5websockets5-dev libqt5bluetooth5 \
    libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev \
    gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly \
    gstreamer1.0-libav \
    libtag1-dev librtaudio-dev \
    xvfb matchbox-window-manager

rm -rf "$WORK"
mkdir -p "$WORK"

# ---------------------------------------------------------------- 11.2 aasdk
log "Buduję aasdk"
cd "$WORK"
git clone --depth 1 --recurse-submodules https://github.com/openDsh/aasdk.git
cd aasdk

# OpenSSL 3.0 usunęło FIPS_mode_set(). Bez tego aasdk nie linkuje się na
# Debianie 13. sed jest bezpieczny do powtórzenia — gdy wzorca nie ma, nic
# nie robi.
sed -i 's|FIPS_mode_set(0);|// FIPS_mode_set(0); // usunięte w OpenSSL 3.0|' \
    src/Transport/SSLWrapper.cpp

mkdir -p build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j"$(nproc)"
make install
ldconfig

# ---------------------------------------------------------------- 11.3 h264bitstream
log "Buduję h264bitstream (repozytorium nie ma Makefile'a)"
cd "$WORK"
git clone --depth 1 https://github.com/aizvorski/h264bitstream.git
cd h264bitstream

gcc -c -fPIC h264_stream.c h264_sei.c -I.
ar rcs libh264bitstream.a h264_stream.o h264_sei.o

cp libh264bitstream.a /usr/local/lib/
cp h264_stream.h h264_sei.h h264_avcc.h h264_slice_data.h bs.h /usr/local/include/
ldconfig

# ---------------------------------------------------------------- 11.4 openauto
log "Buduję openauto"
cd "$WORK"
git clone --depth 1 --recurse-submodules https://github.com/openDsh/openauto.git
cd openauto

# librtaudio 6.x (Debian 13) przemianowało RtAudioError na std::exception.
sed -i 's|catch(const RtAudioError\& e)|catch(const std::exception\& e)|g' \
    openauto/Projection/RtAudioOutput.cpp

# AA tylko bezprzewodowo (BCM_AA_USB=0) — dlaczego: nagłówek skryptu.
# Wyłączamy dwa wywołania w App::waitForDevice (gałąź develop openDsh,
# openauto/App.cpp): this->waitForUSBDevice() (USBHub, hotplug na każde
# urządzenie) i this->enumerateDevices() (AOAP do urządzeń już podłączonych).
# Bez nich autoapp nie rejestruje hotplugu i nie otwiera żadnego urządzenia
# USB; waitForWirelessDevice() (TCP :5000) zostaje. aoapDeviceHandler i
# onUSBHubError zostają w kodzie, ale nikt ich nie wywoła.
# W przeciwieństwie do łatek wyżej ta NIE może być cichym no-opem: brak
# wzorca = AA nadal przełącza telefon w aucie w tryb AOAP, więc błąd.
# Powtórzenie na załatanym pliku niczego nie zmienia (znacznik BCM_AA_USB=0).
patch_aa_wireless_only() {
    local f=$1 n
    [[ -f "$f" ]] || die "Brak $f — upstream openDsh zmienił układ źródeł; łatka BCM_AA_USB=0 nie da się nałożyć (BCM_AA_USB=1 buduje bez niej)."
    n=$(grep -c 'BCM_AA_USB=0' "$f" || true)
    if [[ "$n" == "2" ]]; then
        log "autoapp: łatka BCM_AA_USB=0 już nałożona ($f)"
        return 0
    fi
    [[ "$n" == "0" ]] || die "autoapp: $f jest załatany częściowo ($n z 2 znaczników BCM_AA_USB=0) — usuń $WORK i uruchom ponownie z --force."
    # Najpierw sprawdzamy OBA wzorce, dopiero potem zmieniamy plik — nigdy
    # nie zostaje w połowie załatany.
    for call in waitForUSBDevice enumerateDevices; do
        n=$(grep -cE "^[[:space:]]*this->${call}\(\);[[:space:]]*\$" "$f" || true)
        [[ "$n" == "1" ]] || die "autoapp: oczekiwano dokładnie jednego 'this->${call}();' w $f, jest ${n:-0} — upstream się zmienił, sprawdź App::waitForDevice i popraw łatkę."
    done
    for call in waitForUSBDevice enumerateDevices; do
        sed -i -E "s|^([[:space:]]*)this->${call}\(\);[[:space:]]*\$|\1/* BCM_AA_USB=0: ${call}() wyłączone — AA tylko bezprzewodowo (install-openauto.sh) */|" "$f"
    done
    n=$(grep -c 'BCM_AA_USB=0' "$f" || true)
    [[ "$n" == "2" ]] || die "autoapp: po łatce BCM_AA_USB=0 w $f jest $n znaczników zamiast 2."
    if grep -qE 'this->(waitForUSBDevice|enumerateDevices)\(\);' "$f"; then
        die "autoapp: w $f zostało wywołanie USB po łatce BCM_AA_USB=0."
    fi
    log "autoapp: USB wyłączone (BCM_AA_USB=0) — Android Auto tylko bezprzewodowo"
}

if [[ "$BCM_AA_USB" == "0" ]]; then
    patch_aa_wireless_only openauto/App.cpp
else
    warn "BCM_AA_USB=1: autoapp zostaje z USB (upstream). Telefon w aucie na USB (car_phone)"
    warn "będzie przełączany w tryb akcesorium AA (18d1:2d00/2d01) — tethering i forward GPS padną."
fi

mkdir -p build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j"$(nproc)"
make install
ldconfig

# ---------------------------------------------------------------- 11.5 weryfikacja
log "Weryfikacja"
[[ -x "$BIN" ]] || die "Kompilacja przeszła, ale nie ma $BIN — sprawdź wyjście 'make install' wyżej."
ls -la "$BIN"
# Z jakim BCM_AA_USB zbudowano binarkę — sprawdzane przy następnym
# uruchomieniu bez --force (ostrzeżenie, gdy wybrany tryb jest inny).
install -d -m 0755 "$(dirname "$MODE_FILE")"
echo "BCM_AA_USB=$BCM_AA_USB" > "$MODE_FILE"
echo "Tryb: BCM_AA_USB=$BCM_AA_USB ($([[ "$BCM_AA_USB" == 0 ]] && echo 'AA tylko bezprzewodowo' || echo 'AA także po USB'))"

cat <<'EOF'

Gotowe. Co dalej:

  sudo systemctl restart bcm-headunit
  journalctl -u bcm-headunit --no-pager | grep -i openauto

Oczekiwane w logu:  "OpenAuto found: /usr/local/bin/autoapp"

Jeżeli nadal widzisz błąd o braku binarki — BCM sprawdza tylko trzy ścieżki
(/usr/local/bin, /opt/openauto/bin, /usr/bin), więc upewnij się, że make
install nie odłożył jej gdzie indziej.

Katalog roboczy z kodem źródłowym możesz skasować:
EOF
echo "  rm -rf $WORK"
