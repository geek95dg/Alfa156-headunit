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

set -euo pipefail

FORCE=0
[[ "${1:-}" == "--force" ]] && FORCE=1

BIN=/usr/local/bin/autoapp
WORK="${OPENAUTO_WORKDIR:-/tmp/bcm-openauto-build}"

log()  { printf '\n\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[uwaga]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[błąd]\033[0m %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Uruchom przez sudo — instalacja idzie do /usr/local."

if [[ -x "$BIN" && $FORCE -eq 0 ]]; then
    log "autoapp już jest: $BIN"
    ls -la "$BIN"
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

mkdir -p build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j"$(nproc)"
make install
ldconfig

# ---------------------------------------------------------------- 11.5 weryfikacja
log "Weryfikacja"
[[ -x "$BIN" ]] || die "Kompilacja przeszła, ale nie ma $BIN — sprawdź wyjście 'make install' wyżej."
ls -la "$BIN"

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
