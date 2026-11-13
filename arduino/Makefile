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
#   make sensor_hub-upload PORT=/dev/ttyUSB0 SENSOR_HUB_FEATURES=BATT_ADC
#                             # + funkcje zakomentowane w sketchu (flagą -D)
#   make output_controller-upload PORT=/dev/ttyUSB1
#   make esp32_display-upload PORT=/dev/ttyACM_display
#   make esp32_display-test   # testy hosta (g++), bez płytki i bez arduino-cli
#   make sensor_hub-test      # testy hosta logiki przycisku zasilania (g++)
#   make test                 # oba powyższe
#   make sensor_hub-variants  # sensor_hub z każdą opcjonalną funkcją osobno
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

# Opcjonalne funkcje sensor_hub, które w sketchu są domyślnie wyłączone
# (zakomentowane #define). Zwykłe `make` ich nie kompiluje, więc bez tego celu
# nikt by nie zauważył, że się zepsuły. Każdy wariant to osobna kompilacja
# z flagą -DFEATURE_<nazwa> i WŁASNYM katalogiem build: arduino-cli trzyma
# w nim skompilowany rdzeń i obiekty, a flagi różnią się między wariantami.
# Katalogi leżą w arduino/build/ — poza folderem sketcha (arduino-cli nie
# zbiera z niego plików) i pod regułą `build/` z .gitignore.
SENSOR_HUB_VARIANTS ?= BATT_ADC BATT_INA226
VARIANTS_BUILD_DIR := $(CURDIR)/build

# Funkcje sensor_hub do włączenia w ZWYKŁEJ kompilacji i wgraniu, np.
#   make sensor_hub-upload PORT=/dev/ttyUSB0 SENSOR_HUB_FEATURES=BATT_ADC
# Kilka: SENSOR_HUB_FEATURES="BATT_INA226 AIRBAG". Pusta (domyślnie) = sketch
# jak w repo. Flaga zamiast odkomentowania #define: repo zostaje czyste
# (git pull bez konfliktów), a BATT_* muszą zostać zakomentowane, bo tak je
# sprawdzają testy i kompiluje CI. Dozwolone są tylko nazwy zakomentowanych
# przełączników ze sketcha — literówka (BAT_ADC) skompilowałaby po cichu
# firmware BEZ tej funkcji. sed nie dostaje niczego od użytkownika.
SENSOR_HUB_FEATURES ?=
SENSOR_HUB_OPTIONAL = $(shell sed -n 's|^// *.define FEATURE_\([A-Z0-9_]*\).*|\1|p' \
                        $(CURDIR)/sensor_hub/sensor_hub.ino)
SENSOR_HUB_UNKNOWN = $(filter-out $(SENSOR_HUB_OPTIONAL),$(SENSOR_HUB_FEATURES))
SENSOR_HUB_FLAGS = $(if $(strip $(SENSOR_HUB_FEATURES)),--build-property \
                     "compiler.cpp.extra_flags=$(addprefix -DFEATURE_,$(SENSOR_HUB_FEATURES))")
SENSOR_HUB_TEST_BIN := $(VARIANTS_BUILD_DIR)/sensor_hub-test/test_power_logic

.PHONY: all $(SKETCHES) $(addsuffix -upload,$(SKETCHES)) esp32_display-test test clean \
        sensor_hub-variants sensor_hub-test

all: $(SKETCHES)

test: esp32_display-test sensor_hub-test

$(filter-out sensor_hub,$(AVR_SKETCHES)):
	$(ARDUINO_CLI) compile --profile default --warnings default $(CURDIR)/$@

# Bez SENSOR_HUB_FEATURES polecenie jest identyczne jak dla pozostałych AVR.
# sensor_hub-upload (reguła %-upload niżej) najpierw robi ten cel, więc wgrywa
# firmware z tymi samymi flagami (arduino-cli przebudowuje wszystko, gdy
# flagi zmieniły się od poprzedniej kompilacji).
sensor_hub:
	$(if $(strip $(SENSOR_HUB_UNKNOWN)),$(error SENSOR_HUB_FEATURES: nieznane \
		"$(SENSOR_HUB_UNKNOWN)" - dozwolone: $(SENSOR_HUB_OPTIONAL)))
	$(ARDUINO_CLI) compile --profile default --warnings default $(SENSOR_HUB_FLAGS) \
		$(CURDIR)/sensor_hub

esp32_display:
	$(ARDUINO_CLI) compile --profile default --warnings default \
		--build-property "compiler.cpp.extra_flags=$(TFT_ESPI_FLAGS)" \
		$(CURDIR)/esp32_display

sensor_hub-variants:
	@for v in $(SENSOR_HUB_VARIANTS); do \
		echo "== sensor_hub + FEATURE_$$v"; \
		$(ARDUINO_CLI) compile --profile default --warnings default \
			--build-path $(VARIANTS_BUILD_DIR)/sensor_hub-$$v \
			--build-property "compiler.cpp.extra_flags=-DFEATURE_$$v" \
			$(CURDIR)/sensor_hub || exit 1; \
	done

esp32_display-test:
	@mkdir -p $(dir $(ESP32_TEST_BIN))
	$(CXX) $(HOST_CXXFLAGS) -o $(ESP32_TEST_BIN) \
		$(CURDIR)/esp32_display/test/test_host.cpp
	$(ESP32_TEST_BIN)

# power_logic.h to czysty C++ (decyzje przycisku zasilania M910q, bez I/O).
# Binarka w arduino/build/, poza folderem sketcha.
sensor_hub-test:
	@mkdir -p $(dir $(SENSOR_HUB_TEST_BIN))
	$(CXX) $(HOST_CXXFLAGS) -o $(SENSOR_HUB_TEST_BIN) \
		$(CURDIR)/sensor_hub/test/test_power_logic.cpp
	$(SENSOR_HUB_TEST_BIN)

# Statyczna reguła wzorcowa, nie zwykłe „%-upload: %”: cele *-upload są w
# .PHONY, a dla celów .PHONY make w ogóle nie szuka reguł wzorcowych — zwykły
# wzorzec kończył się cichym „Nothing to be done” i niczego nie wgrywał.
$(addsuffix -upload,$(SKETCHES)): %-upload: %
	@test -n "$(PORT)" || { echo "Podaj port: make $@ PORT=/dev/ttyACM0"; exit 1; }
	$(ARDUINO_CLI) upload --profile default -p $(PORT) $(CURDIR)/$*

clean:
	rm -rf $(addsuffix /build,$(SKETCHES)) $(VARIANTS_BUILD_DIR)
