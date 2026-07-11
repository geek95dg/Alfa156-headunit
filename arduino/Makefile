# BCM v8.5 — kompilacja i wgrywanie firmware Arduino przez arduino-cli
#
# Instalacja narzędzia (raz):
#   curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh | sh
#   arduino-cli core update-index && arduino-cli core install arduino:avr
#
# Użycie:
#   make            # kompiluje wszystkie trzy sketche
#   make rotary_encoder | sensor_hub | output_controller
#   make rotary_encoder-upload PORT=/dev/ttyACM0
#   make sensor_hub-upload PORT=/dev/ttyUSB0
#   make output_controller-upload PORT=/dev/ttyUSB1
#
# Wersje płytek i bibliotek są przypięte w sketch.yaml każdego sketcha
# (profile arduino-cli) — kompilacja jest powtarzalna bez globalnego
# stanu bibliotek.

ARDUINO_CLI ?= arduino-cli
SKETCHES := rotary_encoder sensor_hub output_controller
PORT ?=

.PHONY: all $(SKETCHES) $(addsuffix -upload,$(SKETCHES)) clean

all: $(SKETCHES)

$(SKETCHES):
	$(ARDUINO_CLI) compile --profile default --warnings default $(CURDIR)/$@

%-upload: %
	@test -n "$(PORT)" || { echo "Podaj port: make $@ PORT=/dev/ttyACM0"; exit 1; }
	$(ARDUINO_CLI) upload --profile default -p $(PORT) $(CURDIR)/$*

clean:
	rm -rf $(addsuffix /build,$(SKETCHES))
