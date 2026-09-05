# BCM v8.5 — kompilacja i wgrywanie firmware Arduino przez arduino-cli
#
# Instalacja narzędzia (raz):
#   curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh | sh
#   arduino-cli core update-index && arduino-cli core install arduino:avr
#
# Dla wyświetlacza na ESP32-S3 dodatkowo rdzeń Espressifa (~1 GB):
#   arduino-cli core update-index \
#     --additional-urls https://espressif.github.io/arduino-esp32/package_esp32_index.json
#   arduino-cli core install esp32:esp32 \
#     --additional-urls https://espressif.github.io/arduino-esp32/package_esp32_index.json
#
# Użycie:
#   make            # kompiluje wszystkie cztery sketche
#   make rotary_encoder | sensor_hub | output_controller | esp32_display
#   make rotary_encoder-upload PORT=/dev/ttyACM0
#   make sensor_hub-upload PORT=/dev/ttyUSB0
#   make output_controller-upload PORT=/dev/ttyUSB1
#   make esp32_display-upload PORT=/dev/ttyACM_display
#   make esp32_display-test   # testy hosta (g++), bez płytki i bez arduino-cli
#
# Wersje płytek i bibliotek są przypięte w sketch.yaml każdego sketcha
# (profile arduino-cli) — kompilacja jest powtarzalna bez globalnego
# stanu bibliotek.

ARDUINO_CLI ?= arduino-cli
AVR_SKETCHES := rotary_encoder sensor_hub output_controller
SKETCHES := $(AVR_SKETCHES) esp32_display
PORT ?=

# Konfiguracja panelu dla TFT_eSPI. Biblioteka domyślnie czyta ją z własnego
# User_Setup.h — czyli z katalogu biblioteki, spoza repo. Podanie kompletu
# flagami trzyma ustawienia TUTAJ i sprawia, że kompilacja na cudzej maszynie
# daje ten sam wynik. ST7735 chodzi w kilku odmianach ("taby") różniących się
# przesunięciem obrazu i inwersją kolorów; jeśli obraz jest przesunięty albo
# ma odwrócone barwy, podmień ST7735_GREENTAB3 na ST7735_REDTAB,
# ST7735_BLACKTAB albo ST7735_GREENTAB.
TFT_ESPI_FLAGS ?= -DUSER_SETUP_LOADED=1 -DST7735_DRIVER=1 -DST7735_GREENTAB3=1 \
                  -DTFT_WIDTH=128 -DTFT_HEIGHT=160 \
                  -DTFT_MISO=-1 -DTFT_MOSI=11 -DTFT_SCLK=12 \
                  -DTFT_CS=10 -DTFT_DC=13 -DTFT_RST=14 \
                  -DLOAD_GLCD=1 -DSPI_FREQUENCY=27000000

# Testy hosta: protocol.h, state.h, font_draw.h i text_layout.h są czystym
# C++ i kompilują się zwykłym g++ — bez Arduino, bez płytki, bez arduino-cli.
CXX ?= g++
HOST_CXXFLAGS ?= -std=c++17 -Wall -Wextra -Werror
ESP32_TEST_BIN := $(CURDIR)/esp32_display/build/test_host

.PHONY: all $(SKETCHES) $(addsuffix -upload,$(SKETCHES)) esp32_display-test test clean

all: $(SKETCHES)

test: esp32_display-test

$(AVR_SKETCHES):
	$(ARDUINO_CLI) compile --profile default --warnings default $(CURDIR)/$@

esp32_display:
	$(ARDUINO_CLI) compile --profile default --warnings default \
		--build-property "compiler.cpp.extra_flags=$(TFT_ESPI_FLAGS)" \
		$(CURDIR)/esp32_display

esp32_display-test:
	@mkdir -p $(dir $(ESP32_TEST_BIN))
	$(CXX) $(HOST_CXXFLAGS) -o $(ESP32_TEST_BIN) \
		$(CURDIR)/esp32_display/test/test_host.cpp
	$(ESP32_TEST_BIN)

%-upload: %
	@test -n "$(PORT)" || { echo "Podaj port: make $@ PORT=/dev/ttyACM0"; exit 1; }
	$(ARDUINO_CLI) upload --profile default -p $(PORT) $(CURDIR)/$*

clean:
	rm -rf $(addsuffix /build,$(SKETCHES))
