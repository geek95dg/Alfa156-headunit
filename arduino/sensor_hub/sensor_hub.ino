/*
 * BCM v8.5 — Vehicle Sensor Hub (Arduino Nano, ATmega328P)
 *
 * Trzecia płytka w systemie. Dostarcza telemetrię pojazdu, której
 * oczekuje src/input/arduino_serial.py (audyt: dotąd te komunikaty
 * były udokumentowane, ale ŻADEN firmware ich nie wysyłał).
 *
 * Protokół: zwykły tekst @ 115200 baud, linie zakończone '\n':
 *   DOOR:FL=1,FR=0,RL=0,RR=0,BONNET=0,TRUNK=0   1 = otwarte
 *   HBRAKE:1                                     1 = zaciągnięty
 *   IGN:1                                        1 = zapłon/ACC 12V
 *   RAIN:1                                       1 = deszcz wykryty
 *   TEMP:23.5                                    DS18B20 [°C]
 *   PARK:FL=123,FR=45,RL=200,RR=180              dystanse [cm]
 *   CRUISE:1 / IMMO:1 / AIRBAG:1                 opcjonalne
 *
 * ================= WŁĄCZANIE / WYŁĄCZANIE FUNKCJI =================
 * Każda funkcja ma własny przełącznik kompilacji. Zakomentuj
 * #define, żeby całkowicie usunąć funkcję z firmware (pin wraca
 * do dyspozycji). Po zmianie: make -C arduino sensor_hub-upload
 */
#define FEATURE_DOORS      // 6x krańcówki drzwi/maski/klapy (D2-D7)
#define FEATURE_HBRAKE     // ręczny (D8)
#define FEATURE_IGN        // zapłon 12V przez transoptor PC817 (D9)
#define FEATURE_RAIN       // moduł czujnika deszczu, wyjście cyfrowe (D10)
#define FEATURE_TEMP       // DS18B20 1-Wire (D11) — wymaga bibliotek
                           // OneWire + DallasTemperature
// #define FEATURE_PARK    // 4x HC-SR04 (TRIG D12, ECHO A0-A3).
                           // DOMYŚLNIE WYŁĄCZONE — czujniki parkowania
                           // obsługuje moduł parking na GPIO (Part 4).
                           // Włącz tylko, jeśli czujniki wiszą na Nano.
// #define FEATURE_CRUISE  // tempomat aktywny (A4) — opcja
// #define FEATURE_IMMO    // immobilizer OK (A5) — opcja
// #define FEATURE_AIRBAG  // airbag OK (D13, uwaga: pin z LED) — opcja
/* ================================================================== */

/*
 * --- Mapa pinów ---
 *   D2  Drzwi FL      (krańcówka do GND, INPUT_PULLUP; LOW = otwarte)
 *   D3  Drzwi FR      (j.w.)
 *   D4  Drzwi RL      (j.w.)
 *   D5  Drzwi RR      (j.w.)
 *   D6  Maska         (j.w.)
 *   D7  Klapa bagażn. (j.w.)
 *   D8  Ręczny        (styk do GND, INPUT_PULLUP; LOW = zaciągnięty)
 *   D9  Zapłon        (PC817: 12V ACC → LED; kolektor → D9, INPUT_PULLUP;
 *                      LOW = zapłon włączony)
 *   D10 Deszcz        (wyjście DO modułu czujnika; LOW = deszcz)
 *   D11 DS18B20 DQ    (+4.7kΩ pull-up do 5V)
 *   D12 HC-SR04 TRIG  (wspólny dla 4 czujników)
 *   A0-A3 HC-SR04 ECHO FL/FR/RL/RR (przez dzielnik 1k/2k z 5V!)
 *   A4  Tempomat, A5 Immo (opcje), D13 Airbag (opcja)
 *
 * Watchdog: 2 s — zawieszenie = automatyczny reset.
 */

#include <avr/wdt.h>

#ifdef FEATURE_TEMP
#include <OneWire.h>
#include <DallasTemperature.h>
#endif

// --- Piny ---
#define PIN_DOOR_FL   2
#define PIN_DOOR_FR   3
#define PIN_DOOR_RL   4
#define PIN_DOOR_RR   5
#define PIN_BONNET    6
#define PIN_TRUNK     7
#define PIN_HBRAKE    8
#define PIN_IGN       9
#define PIN_RAIN      10
#define PIN_ONEWIRE   11
#define PIN_PARK_TRIG 12
#define PIN_CRUISE    A4
#define PIN_IMMO      A5
#define PIN_AIRBAG    13

// --- Cadence ---
#define DEBOUNCE_MS        50
#define STATE_REFRESH_MS 2000   // pełny stan co 2 s nawet bez zmian
#define TEMP_REPORT_MS   5000
#define PARK_CYCLE_MS     100   // jeden czujnik na cykl → pełny skan 400 ms
#define PARK_ECHO_TIMEOUT_US 25000UL  // ~4.3 m maks. zasięg

#ifdef FEATURE_DOORS
const uint8_t DOOR_PINS[6]  = {PIN_DOOR_FL, PIN_DOOR_FR, PIN_DOOR_RL,
                               PIN_DOOR_RR, PIN_BONNET, PIN_TRUNK};
const char*   DOOR_KEYS[6]  = {"FL", "FR", "RL", "RR", "BONNET", "TRUNK"};
bool doorState[6]        = {false, false, false, false, false, false};
bool doorRaw[6]          = {false, false, false, false, false, false};
unsigned long doorChangeAt[6] = {0};
#endif

// Wspólny debouncer dla pojedynczych wejść cyfrowych
struct DebouncedInput {
  uint8_t pin;
  bool activeLow;        // LOW = stan "1" w protokole
  bool state;            // zdebouncowany stan logiczny
  bool raw;
  unsigned long changeAt;
};

#ifdef FEATURE_HBRAKE
DebouncedInput inHbrake = {PIN_HBRAKE, true, false, false, 0};
#endif
#ifdef FEATURE_IGN
DebouncedInput inIgn = {PIN_IGN, true, false, false, 0};
#endif
#ifdef FEATURE_RAIN
DebouncedInput inRain = {PIN_RAIN, true, false, false, 0};
#endif
#ifdef FEATURE_CRUISE
DebouncedInput inCruise = {PIN_CRUISE, true, false, false, 0};
#endif
#ifdef FEATURE_IMMO
DebouncedInput inImmo = {PIN_IMMO, true, false, false, 0};
#endif
#ifdef FEATURE_AIRBAG
DebouncedInput inAirbag = {PIN_AIRBAG, true, false, false, 0};
#endif

#ifdef FEATURE_TEMP
OneWire oneWire(PIN_ONEWIRE);
DallasTemperature tempSensor(&oneWire);
bool tempRequested = false;
unsigned long tempRequestedAt = 0;
unsigned long lastTempReport = 0;
#endif

#ifdef FEATURE_PARK
const uint8_t PARK_ECHO_PINS[4] = {A0, A1, A2, A3};
const char*   PARK_KEYS[4]      = {"FL", "FR", "RL", "RR"};
int  parkDist[4] = {999, 999, 999, 999};
uint8_t parkIdx = 0;
unsigned long lastParkCycle = 0;
#endif

unsigned long lastStateRefresh = 0;

// -----------------------------------------------------------------------------
void setup() {
  wdt_disable();  // czysty stan po resecie watchdogiem

#ifdef FEATURE_DOORS
  for (uint8_t i = 0; i < 6; i++) pinMode(DOOR_PINS[i], INPUT_PULLUP);
#endif
#ifdef FEATURE_HBRAKE
  pinMode(PIN_HBRAKE, INPUT_PULLUP);
#endif
#ifdef FEATURE_IGN
  pinMode(PIN_IGN, INPUT_PULLUP);
#endif
#ifdef FEATURE_RAIN
  pinMode(PIN_RAIN, INPUT_PULLUP);
#endif
#ifdef FEATURE_CRUISE
  pinMode(PIN_CRUISE, INPUT_PULLUP);
#endif
#ifdef FEATURE_IMMO
  pinMode(PIN_IMMO, INPUT_PULLUP);
#endif
#ifdef FEATURE_AIRBAG
  pinMode(PIN_AIRBAG, INPUT_PULLUP);
#endif
#ifdef FEATURE_PARK
  pinMode(PIN_PARK_TRIG, OUTPUT);
  digitalWrite(PIN_PARK_TRIG, LOW);
  for (uint8_t i = 0; i < 4; i++) pinMode(PARK_ECHO_PINS[i], INPUT);
#endif

  Serial.begin(115200);

#ifdef FEATURE_TEMP
  tempSensor.begin();
  tempSensor.setWaitForConversion(false);  // konwersja asynchroniczna
#endif

  Serial.println(F("BCM v8.5 Sensor Hub ready"));
  wdt_enable(WDTO_2S);
}

// -----------------------------------------------------------------------------
// true gdy zdebouncowany stan się zmienił
bool updateDebounced(DebouncedInput& in, unsigned long now) {
  bool raw = digitalRead(in.pin) == (in.activeLow ? LOW : HIGH);
  if (raw != in.raw) {
    in.raw = raw;
    in.changeAt = now;
  }
  if (in.raw != in.state && (now - in.changeAt) >= DEBOUNCE_MS) {
    in.state = in.raw;
    return true;
  }
  return false;
}

void reportBool(const __FlashStringHelper* prefix, bool v) {
  Serial.print(prefix);
  Serial.println(v ? '1' : '0');
}

#ifdef FEATURE_DOORS
bool updateDoors(unsigned long now) {
  bool changed = false;
  for (uint8_t i = 0; i < 6; i++) {
    bool raw = digitalRead(DOOR_PINS[i]) == LOW;  // LOW = otwarte
    if (raw != doorRaw[i]) {
      doorRaw[i] = raw;
      doorChangeAt[i] = now;
    }
    if (doorRaw[i] != doorState[i] && (now - doorChangeAt[i]) >= DEBOUNCE_MS) {
      doorState[i] = doorRaw[i];
      changed = true;
    }
  }
  return changed;
}

void reportDoors() {
  Serial.print(F("DOOR:"));
  for (uint8_t i = 0; i < 6; i++) {
    if (i) Serial.print(',');
    Serial.print(DOOR_KEYS[i]);
    Serial.print('=');
    Serial.print(doorState[i] ? '1' : '0');
  }
  Serial.println();
}
#endif

#ifdef FEATURE_TEMP
void handleTemp(unsigned long now) {
  if (!tempRequested) {
    if (now - lastTempReport >= TEMP_REPORT_MS) {
      tempSensor.requestTemperatures();  // nieblokujące (async)
      tempRequested = true;
      tempRequestedAt = now;
    }
  } else if (now - tempRequestedAt >= 750) {  // 12-bit: maks. 750 ms
    float t = tempSensor.getTempCByIndex(0);
    tempRequested = false;
    lastTempReport = now;
    if (t > -100 && t < 100) {  // DEVICE_DISCONNECTED_C = -127
      Serial.print(F("TEMP:"));
      Serial.println(t, 1);
    }
  }
}
#endif

#ifdef FEATURE_PARK
// Jeden czujnik na cykl — pojedynczy pulseIn blokuje maks. 25 ms,
// więc watchdog (2 s) i debouncery pozostają bezpieczne.
void handlePark(unsigned long now) {
  if (now - lastParkCycle < PARK_CYCLE_MS) return;
  lastParkCycle = now;

  digitalWrite(PIN_PARK_TRIG, HIGH);
  delayMicroseconds(10);
  digitalWrite(PIN_PARK_TRIG, LOW);

  unsigned long us = pulseIn(PARK_ECHO_PINS[parkIdx], HIGH, PARK_ECHO_TIMEOUT_US);
  parkDist[parkIdx] = (us == 0) ? 999 : (int)(us / 58UL);  // us→cm

  parkIdx = (parkIdx + 1) % 4;
  if (parkIdx == 0) {  // pełny skan zakończony → raport
    Serial.print(F("PARK:"));
    for (uint8_t i = 0; i < 4; i++) {
      if (i) Serial.print(',');
      Serial.print(PARK_KEYS[i]);
      Serial.print('=');
      Serial.print(parkDist[i]);
    }
    Serial.println();
  }
}
#endif

void reportFullState() {
#ifdef FEATURE_DOORS
  reportDoors();
#endif
#ifdef FEATURE_HBRAKE
  reportBool(F("HBRAKE:"), inHbrake.state);
#endif
#ifdef FEATURE_IGN
  reportBool(F("IGN:"), inIgn.state);
#endif
#ifdef FEATURE_RAIN
  reportBool(F("RAIN:"), inRain.state);
#endif
#ifdef FEATURE_CRUISE
  reportBool(F("CRUISE:"), inCruise.state);
#endif
#ifdef FEATURE_IMMO
  reportBool(F("IMMO:"), inImmo.state);
#endif
#ifdef FEATURE_AIRBAG
  reportBool(F("AIRBAG:"), inAirbag.state);
#endif
}

// -----------------------------------------------------------------------------
void loop() {
  wdt_reset();
  unsigned long now = millis();

#ifdef FEATURE_DOORS
  if (updateDoors(now)) reportDoors();
#endif
#ifdef FEATURE_HBRAKE
  if (updateDebounced(inHbrake, now)) reportBool(F("HBRAKE:"), inHbrake.state);
#endif
#ifdef FEATURE_IGN
  if (updateDebounced(inIgn, now)) reportBool(F("IGN:"), inIgn.state);
#endif
#ifdef FEATURE_RAIN
  if (updateDebounced(inRain, now)) reportBool(F("RAIN:"), inRain.state);
#endif
#ifdef FEATURE_CRUISE
  if (updateDebounced(inCruise, now)) reportBool(F("CRUISE:"), inCruise.state);
#endif
#ifdef FEATURE_IMMO
  if (updateDebounced(inImmo, now)) reportBool(F("IMMO:"), inImmo.state);
#endif
#ifdef FEATURE_AIRBAG
  if (updateDebounced(inAirbag, now)) reportBool(F("AIRBAG:"), inAirbag.state);
#endif

#ifdef FEATURE_TEMP
  handleTemp(now);
#endif
#ifdef FEATURE_PARK
  handlePark(now);
#endif

  // Okresowe odświeżenie pełnego stanu — BCM po restarcie dostaje
  // komplet danych bez czekania na zmianę.
  if (now - lastStateRefresh >= STATE_REFRESH_MS) {
    lastStateRefresh = now;
    reportFullState();
  }

  delay(1);
}
