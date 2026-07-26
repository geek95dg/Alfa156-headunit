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
 *   PWR:RUNNING|SLEEP|OFF|UNKNOWN                stan M910q
 *   PWRACT:SHORT|LONG                            wysłany impuls na przycisk
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
#define FEATURE_PWRBTN     // sterowanie przyciskiem zasilania M910q (A0)
                           // — zapłon usypia do S3 i wybudza. Wymaga
                           // FEATURE_IGN. Szczegóły niżej.
#define FEATURE_PWRLED     // odczyt diody zasilania panelu przedniego (A1)
                           // — zamyka pętlę: firmware WIE, czy maszyna
                           // pracuje, zamiast zgadywać. Opcjonalne.
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
 *   A0  Przekaźnik przycisku zasilania M910q  (FEATURE_PWRBTN)
 *   A1  Dioda zasilania panelu przedniego     (FEATURE_PWRLED)
 *   A0-A3 HC-SR04 ECHO FL/FR/RL/RR — TYLKO z FEATURE_PARK, które
 *         wyklucza się z FEATURE_PWRBTN (patrz #error niżej)
 *   A4  Tempomat, A5 Immo (opcje), D13 Airbag (opcja)
 *
 * Watchdog: 2 s — zawieszenie = automatyczny reset.
 *
 * --- Sterowanie zasilaniem M910q (FEATURE_PWRBTN) ---
 * Styki modułu przekaźnika 1-kanałowego wpięte RÓWNOLEGLE do przycisku
 * zasilania M910q. Nie ma tu żadnego protokołu — impuls zwiera przycisk,
 * a całą logikę ma już system operacyjny:
 *
 *   praca      + krótkie wciśnięcie → S3
 *   S3         + krótkie wciśnięcie → wybudzenie (~3 s)
 *   wyłączony  + krótkie wciśnięcie → start
 *   dowolny    + przytrzymanie 5 s  → twarde wyłączenie
 *
 * Po stronie hosta: acpid (event=button/power → bcm-power-toggle.sh)
 * plus HandlePowerKey=ignore w logind.conf — jedno i drugie jest już
 * skonfigurowane, patrz docs/WDROZENIE_M910Q.md §7.3.
 *
 * Płytka MUSI mieć własne 5 V (MP1584 z bufora), niezależne od USB —
 * inaczej gaśnie razem z komputerem i nie ma czym nacisnąć przycisku.
 * W kablu USB przetnij żyłę VBUS.
 *
 * Bez FEATURE_PWRLED firmware działa w pętli otwartej: zakłada stan
 * maszyny po własnych impulsach i reaguje wyłącznie na ZMIANĘ zapłonu,
 * więc reset watchdogiem nie powoduje przypadkowego wciśnięcia.
 * Z FEATURE_PWRLED odczytuje stan z diody panelu (świeci = praca,
 * miga = S3, zgaszona = wyłączony) i sam się synchronizuje.
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
#define PIN_PWR_RELAY A0
#define PIN_PWR_LED   A1

#if defined(FEATURE_PWRBTN) && !defined(FEATURE_IGN)
#error "FEATURE_PWRBTN wymaga FEATURE_IGN - to zaplon steruje maszyna"
#endif
#if defined(FEATURE_PWRBTN) && defined(FEATURE_PARK)
#error "Konflikt pinow: FEATURE_PARK uzywa A0-A3 na ECHO, FEATURE_PWRBTN A0/A1"
#endif
#if defined(FEATURE_PWRLED) && !defined(FEATURE_PWRBTN)
#error "FEATURE_PWRLED bez FEATURE_PWRBTN nie ma czego synchronizowac"
#endif

// --- Cadence ---
#define DEBOUNCE_MS        50
#define STATE_REFRESH_MS 2000   // pełny stan co 2 s nawet bez zmian
#define TEMP_REPORT_MS   5000
#define PARK_CYCLE_MS     100   // jeden czujnik na cykl → pełny skan 400 ms
#define PARK_ECHO_TIMEOUT_US 25000UL  // ~4.3 m maks. zasięg

#ifdef FEATURE_PWRBTN
// Większość tanich modułów przekaźnikowych wyzwala się stanem NISKIM.
// Jeśli Twój jest odwrotny — zmień na 0. Dodatkowo warto dać 10 kΩ
// pull-up na IN, żeby przekaźnik nie zadziałał w kilku ms przed setup().
#define PWR_RELAY_ACTIVE_LOW  1
#define PWR_LED_ACTIVE_LOW    1     // PC817 na diodzie: świeci → pin LOW

#define PWR_PULSE_SHORT_MS     250UL      // krótkie wciśnięcie
#define PWR_PULSE_LONG_MS     5000UL      // przytrzymanie → twarde wyłączenie
#define PWR_SETTLE_MS        15000UL      // po impulsie nie ruszamy niczego
#define PWR_IGN_CONFIRM_MS    2000UL      // zapłon musi się utrzymać (rozruch!)
#define PWR_OFF_AFTER_MS   7200000UL      // 2 h zgaszonego zapłonu → wyłącz
#define PWR_LED_WINDOW_MS     1600UL      // okno rozpoznania migania diody
#endif

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

#ifdef FEATURE_PWRBTN
enum PwrState : uint8_t { PWR_UNKNOWN = 0, PWR_RUNNING, PWR_SLEEP, PWR_OFF };
const char* const PWR_NAMES[4] = {"UNKNOWN", "RUNNING", "SLEEP", "OFF"};

PwrState pwrState   = PWR_UNKNOWN;   // co (naszym zdaniem) robi maszyna
PwrState pwrDesired = PWR_UNKNOWN;   // czego od niej chcemy

bool          pwrIgnKnown  = false;  // czy zapłon jest już potwierdzony
bool          pwrIgnLevel  = false;  // ostatni potwierdzony poziom
bool          pwrIgnCand   = false;  // kandydat oczekujący na potwierdzenie
unsigned long pwrIgnCandAt = 0;
unsigned long pwrIgnOffAt  = 0;      // kiedy zapłon zgasł (do eskalacji)
bool          pwrOffDone   = false;  // twarde wyłączenie już wysłane

unsigned long pwrPulseUntil  = 0;    // trwa impuls do tej chwili (0 = brak)
unsigned long pwrSettleUntil = 0;    // cisza po impulsie
#endif

#ifdef FEATURE_PWRLED
bool          pwrLedLit      = false;
uint8_t       pwrLedEdges    = 0;
unsigned long pwrLedWindowAt = 0;
#endif

unsigned long lastStateRefresh = 0;

// -----------------------------------------------------------------------------
void setup() {
  wdt_disable();  // czysty stan po resecie watchdogiem

#ifdef FEATURE_PWRBTN
  // NAJPIERW przekaźnik w stan nieaktywny — zanim cokolwiek innego zdąży
  // potrwać. Pin do tej chwili był wejściem (Hi-Z), stąd zalecany pull-up.
#if PWR_RELAY_ACTIVE_LOW
  digitalWrite(PIN_PWR_RELAY, HIGH);
#else
  digitalWrite(PIN_PWR_RELAY, LOW);
#endif
  pinMode(PIN_PWR_RELAY, OUTPUT);
#endif
#ifdef FEATURE_PWRLED
  pinMode(PIN_PWR_LED, INPUT_PULLUP);
#endif

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

#ifdef FEATURE_PWRBTN
void pwrRelay(bool on) {
#if PWR_RELAY_ACTIVE_LOW
  digitalWrite(PIN_PWR_RELAY, on ? LOW : HIGH);
#else
  digitalWrite(PIN_PWR_RELAY, on ? HIGH : LOW);
#endif
}

void pwrSetState(PwrState s) {
  if (s == pwrState) return;
  pwrState = s;
  Serial.print(F("PWR:"));
  Serial.println(PWR_NAMES[s]);
}

// Impuls jest NIEBLOKUJĄCY — 5 s w delay() zabiłoby watchdoga (2 s).
void pwrStartPulse(unsigned long ms, const __FlashStringHelper* what) {
  pwrRelay(true);
  pwrPulseUntil = millis() + ms;
  Serial.print(F("PWRACT:"));
  Serial.println(what);
}

#ifdef FEATURE_PWRLED
// Dioda panelu: świeci ciągle = praca, miga = S3, zgaszona = wyłączony.
// Rozpoznajemy przez zliczanie zboczy w oknie PWR_LED_WINDOW_MS.
void pwrObserveLed(unsigned long now) {
  bool lit = digitalRead(PIN_PWR_LED) == (PWR_LED_ACTIVE_LOW ? LOW : HIGH);
  if (lit != pwrLedLit) {
    pwrLedLit = lit;
    if (pwrLedEdges < 250) pwrLedEdges++;
  }
  if (now - pwrLedWindowAt < PWR_LED_WINDOW_MS) return;
  pwrLedWindowAt = now;

  if (pwrLedEdges >= 2)   pwrSetState(PWR_SLEEP);
  else if (pwrLedLit)     pwrSetState(PWR_RUNNING);
  else                    pwrSetState(PWR_OFF);
  pwrLedEdges = 0;
}
#endif

void handlePwrButton(unsigned long now) {
  // 1. Domknij trwający impuls i odczekaj, aż maszyna wykona przejście.
  if (pwrPulseUntil) {
    if ((long)(now - pwrPulseUntil) >= 0) {
      pwrRelay(false);
      pwrPulseUntil = 0;
      pwrSettleUntil = now + PWR_SETTLE_MS;
    }
    return;
  }

#ifdef FEATURE_PWRLED
  pwrObserveLed(now);
#endif

  // 2. Potwierdzenie zapłonu. DEBOUNCE_MS (50 ms) wystarcza do raportowania
  //    IGN:, ale nie do usypiania komputera — zapad przy rozruchu potrafi
  //    zgasić ACC na chwilę. Stąd osobne, dłuższe potwierdzenie.
  bool ign = inIgn.state;

  if (!pwrIgnKnown) {
    if (ign != pwrIgnCand) { pwrIgnCand = ign; pwrIgnCandAt = now; }
    if ((now - pwrIgnCandAt) >= PWR_IGN_CONFIRM_MS) {
      pwrIgnLevel = ign;
      pwrIgnKnown = true;
      if (!ign) pwrIgnOffAt = now;
    }
    return;  // pierwsza obserwacja po starcie NIE wywołuje akcji
  }

  if (ign != pwrIgnCand) { pwrIgnCand = ign; pwrIgnCandAt = now; }
  if (pwrIgnCand != pwrIgnLevel && (now - pwrIgnCandAt) >= PWR_IGN_CONFIRM_MS) {
    pwrIgnLevel = pwrIgnCand;
    if (pwrIgnLevel) {
      pwrDesired = PWR_RUNNING;
    } else {
      pwrIgnOffAt = now;
      pwrOffDone  = false;
      pwrDesired  = PWR_SLEEP;
    }
  }

  // 3. Eskalacja: po dwóch godzinach postoju S3 przestaje się opłacać.
  if (!pwrIgnLevel && !pwrOffDone && (now - pwrIgnOffAt) >= PWR_OFF_AFTER_MS) {
    pwrDesired = PWR_OFF;
  }

  // 4. Wykonanie. Zamiar jest JEDNORAZOWY — po impulsie kasujemy go, żeby
  //    firmware nie walczył z człowiekiem, który sam nacisnął przycisk.
  if (now < pwrSettleUntil) return;
  if (pwrDesired == PWR_UNKNOWN) return;
  if (pwrDesired == pwrState) { pwrDesired = PWR_UNKNOWN; return; }

  switch (pwrDesired) {
    case PWR_RUNNING:
      pwrStartPulse(PWR_PULSE_SHORT_MS, F("SHORT"));
#ifndef FEATURE_PWRLED
      pwrSetState(PWR_RUNNING);
#endif
      break;

    case PWR_SLEEP:
      // Z wyłączonej maszyny nie robimy S3 — krótki impuls by ją WŁĄCZYŁ.
      if (pwrState == PWR_OFF) { pwrDesired = PWR_UNKNOWN; break; }
      pwrStartPulse(PWR_PULSE_SHORT_MS, F("SHORT"));
#ifndef FEATURE_PWRLED
      pwrSetState(PWR_SLEEP);
#endif
      break;

    case PWR_OFF:
      pwrStartPulse(PWR_PULSE_LONG_MS, F("LONG"));
      pwrOffDone = true;
#ifndef FEATURE_PWRLED
      pwrSetState(PWR_OFF);
#endif
      break;

    default:
      break;
  }

  pwrDesired = PWR_UNKNOWN;
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
#ifdef FEATURE_PWRBTN
  Serial.print(F("PWR:"));
  Serial.println(PWR_NAMES[pwrState]);
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
#ifdef FEATURE_PWRBTN
  handlePwrButton(now);
#endif

  // Okresowe odświeżenie pełnego stanu — BCM po restarcie dostaje
  // komplet danych bez czekania na zmianę.
  if (now - lastStateRefresh >= STATE_REFRESH_MS) {
    lastStateRefresh = now;
    reportFullState();
  }

  delay(1);
}
