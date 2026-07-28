/*
 * BCM v7 — Rotary Encoder + Buttons + SWC + Music Panel + Brightness → USB HID
 *
 * Hardware: Arduino Pro Micro (ATmega32U4)
 *
 * Wiring:
 *   D2 ← Encoder CLK + 10kΩ pull-up to VCC
 *   D3 ← Encoder DT  + 10kΩ pull-up to VCC
 *   D1 ← Encoder SW   (push button, active LOW)
 *        !!! ZMIANA OKABLOWANIA: przycisk enkodera przeniesiony z D4 na D1
 *        (TXO). Na Pro Micro D4 i A6 to FIZYCZNIE TEN SAM pin (PD4/ADC8),
 *        więc przycisk enkodera na D4 wykluczał SWC Pod 2 na A6. Jeśli
 *        masz starsze okablowanie: przepnij jeden przewód z D4 na D1.
 *   D5 ← HOME button  (active LOW, internal pull-up)
 *   D6 ← BACK button  (active LOW, internal pull-up)
 *   D7 ← MEDIA button (active LOW, internal pull-up)
 *   D8 ← VOL+ button  (active LOW, internal pull-up)
 *   D9 ← VOL- button  (active LOW, internal pull-up)
 *   A0 ← SWC Pod 1 (white wire, analog 0-5V)
 *   A6 ← SWC Pod 2 (white wire, analog 0-5V)
 *
 *   Music panel (5 buttons near 7" AA screen, active LOW, internal pull-ups):
 *   D10 ← MUSIC PREV
 *   D14 ← MUSIC NEXT
 *   D15 ← MUSIC VOL+
 *   D16 ← MUSIC VOL-
 *   A3  ← MUSIC MUTE
 *
 *   Brightness:
 *   A1  ← LDR light sensor (voltage divider: LDR + 10kΩ to GND → A1)
 *   A2  ← Stalk button (spare button on column stalk, active LOW, internal pull-up)
 *
 * SWC decoder boxes: Pod 1 white → A0, Pod 2 white → A6, both black → GND, both red → 12V ACC
 *
 * Music panel buttons send same keycodes as SWC/encoder equivalents:
 *   MUSIC PREV  → MEDIA_PREVIOUS (consumer)
 *   MUSIC NEXT  → MEDIA_NEXT (consumer)
 *   MUSIC VOL+  → MEDIA_VOLUME_UP (consumer)
 *   MUSIC VOL-  → MEDIA_VOLUME_DOWN (consumer)
 *   MUSIC MUTE  → MEDIA_VOLUME_MUTE (consumer)
 *
 * Brightness stalk button → KEY_F9 (brightness cycle)
 * Light sensor → serial line "LIGHT:<0-1023>" every 2 s (no keypress)
 * Fuel sender → serial line "FUEL:<0-1023>" every 5 s
 *   NOTE: A4 is not broken out on a classic Pro Micro — it needs a clone
 *   with the A4 pad (or the inner bottom pad). See docs/ARDUINO_SETUP_GUIDE.md.
 *
 * Calibration mode: hold HOME + BACK at boot (gdy FEATURE_BUTTONS jest
 *   włączone) ALBO wyślij "CAL" na port szeregowy w dowolnym momencie.
 * Watchdog: 2 s (wyłączany na czas kalibracji).
 *
 * ---------------------------------------------------------------------------
 * v8.5.3 — naprawa fałszywych przycisków SWC
 *
 * Objaw: przy niepodłączonych podach płytka sypała zdarzeniami, przy czym
 * OBA pody raportowały ten sam przycisk przy niemal tej samej wartości ADC.
 * Trzy niezależne przyczyny, wszystkie usunięte:
 *
 *   1. Wejścia analogowe były ustawione jako gołe INPUT. Kod uznaje spoczynek
 *      za "ADC > SWC_IDLE_THRESHOLD" (≈ VCC), więc WYMAGA, żeby coś trzymało
 *      linię wysoko. Teraz INPUT_PULLUP. W aucie i tak lepszy jest zewnętrzny
 *      10 kΩ do VCC — wewnętrzny ma 20–50 kΩ i szeroką tolerancję.
 *
 *   2. Multiplekser ADC ma JEDEN kondensator sample-and-hold na wszystkie
 *      kanały. Pierwsza konwersja po przełączeniu kanału niesie ładunek
 *      z kanału poprzedniego — przy pływającym wejściu praktycznie w całości.
 *      Stąd Pod 2 był kopią Pod 1. Teraz: adcStable() odrzuca dwie pierwsze
 *      konwersje i zwraca MEDIANĘ (mediana ignoruje pik, średnia go rozmazuje).
 *
 *   3. Nie było realnego debounce'u: licznik czasu odświeżał się tylko przy
 *      ZMIANIE odczytu, więc pierwsza odbiegająca próbka natychmiast wysyłała
 *      klawisz. Teraz kandydat musi być stabilny przez SWC_CONFIRM_MS, a między
 *      dwoma różnymi przyciskami wymagany jest powrót do spoczynku.
 *
 * To nie była wyłącznie uciążliwość: SWC MODE wysyła F10, które BCM mapuje na
 * input.bcm_power_toggle — szum potrafił wyłączyć komputer.
 *
 * Przy okazji: piny enkodera dostały INPUT_PULLUP (bez podłączonego enkodera
 * pływały i przerwanie CHANGE sypało strzałkami), a wejścia, których nie masz
 * podłączonych, można teraz wyłączyć przełącznikami FEATURE_* poniżej.
 * ---------------------------------------------------------------------------
 */

#include <avr/wdt.h>
// UWAGA: nie dołączać <Keyboard.h> — HID-Project dostarcza własny obiekt
// Keyboard (ImprovedKeyboard) i definiuje KEY_* jako enum; makra KEY_*
// ze stockowego Keyboard.h psują kompilację (konflikt makro vs enum).
#include <HID-Project.h>
#include <EEPROM.h>

// --- Przełączniki funkcji -------------------------------------------------
// Zakomentuj to, czego nie masz podłączonego. Niepodłączone wejścia cyfrowe
// z pull-upem są nieszkodliwe, ale wyłączenie ich skraca pętlę i usuwa szum
// z portu szeregowego. Wejścia ANALOGOWE wyłączaj zawsze, gdy nic na nich
// nie wisi — pływający pin to śmieci w multiplekserze ADC.
//
// Domyślnie: tylko pody SWC. To jedyna rzecz, która ma teraz działać.
#define FEATURE_SWC        // pody SWC na kierownicy (A0 + A6)
// #define FEATURE_ENCODER // enkoder obrotowy + przycisk (D2, D3, D1)
// #define FEATURE_BUTTONS // HOME / BACK / MEDIA / VOL+ / VOL− (D5–D9)
// #define FEATURE_MUSIC   // panel muzyczny (D10, D14, D15, D16, A3)
// #define FEATURE_STALK   // przycisk manetki → F9 (A2)
// #define FEATURE_LIGHT   // fotorezystor LDR (A1)
// #define FEATURE_FUEL    // czujnik paliwa (A4) — patrz #error niżej

#if defined(FEATURE_FUEL)
#error "A4 nie jest wyprowadzone na klasycznym Pro Micro (PF1). Potrzebny klon z padem A4 albo inna plytka — patrz docs/ARDUINO_SETUP_GUIDE.md."
#endif

#if !defined(FEATURE_SWC) && !defined(FEATURE_ENCODER) && !defined(FEATURE_BUTTONS) \
    && !defined(FEATURE_MUSIC) && !defined(FEATURE_STALK) && !defined(FEATURE_LIGHT)
#error "Wszystkie FEATURE_* sa zakomentowane — plytka nie robilaby nic. Odkomentuj przynajmniej FEATURE_SWC."
#endif

// --- Pin definitions ---
#define ENC_CLK 2
#define ENC_DT  3
#define ENC_SW  1   // was D4 — moved: D4 == A6 (SWC Pod 2) on Pro Micro
#define BTN_HOME  5
#define BTN_BACK  6
#define BTN_MEDIA 7
#define BTN_VOLUP 8
#define BTN_VOLDN 9
#define SWC_PIN1  A0
#define SWC_PIN2  A6

// Music panel buttons (near 7" Android Auto screen)
#define MUS_PREV  10
#define MUS_NEXT  14
#define MUS_VOLUP 15
#define MUS_VOLDN 16
#define MUS_MUTE  A3

// Brightness
#define LDR_PIN       A1   // Light sensor analog input
#define STALK_BTN_PIN A2   // Spare stalk button (brightness cycle)

// Fuel sender (resistive float in tank, via voltage divider)
#define FUEL_PIN      A4   // Fuel sender analog input
#define FUEL_REPORT_MS 5000 // Report fuel level every 5 seconds

// --- Debounce ---
#define DEBOUNCE_MS 50
#define ENCODER_DEBOUNCE_MS 5
#define ADC_TOLERANCE 40
#define LIGHT_REPORT_MS 2000  // Send light level every 2 seconds

// --- Odczyt ADC (patrz nota v8.5.3 w nagłówku) ---
// Dwie konwersje na rozruch multipleksera, potem 5 próbek i mediana.
// Koszt: ~2,4 ms na kanał. Przy dwóch podach pętla trwa ~5 ms — bez znaczenia
// wobec 50 ms debounce'u przycisków i 2 s watchdoga.
#define ADC_SETTLE_US   200   // po przełączeniu kanału, na naładowanie S/H
#define ADC_SAMPLES       5   // nieparzyście — mediana musi mieć środek
#define ADC_SPACING_US  400   // rozrzut próbek, żeby nie złapać jednego piku

// Kandydat musi być odczytany tak samo przez tyle czasu, zanim poleci HID.
// 60 ms to kompromis: krócej łapie zakłócenia, dłużej daje wrażenie opóźnienia.
#define SWC_CONFIRM_MS   60

// --- SWC button count (12 per pod x 2 pods = 24 total) ---
#define SWC_BUTTONS_PER_POD 12
#define SWC_BUTTON_COUNT 24
#define SWC_IDLE_THRESHOLD 1000

// --- EEPROM layout ---
#define EEPROM_MAGIC_ADDR 0
#define EEPROM_MAGIC_VALUE 0xBD   // bumped from 0xBC to force re-calibration
#define EEPROM_SWC_ADDR 1         // 24 x 2 bytes = 48 bytes

// SWC button indices — Pod 1 (0-11), Pod 2 (12-23)
enum SWCButton {
  SWC_VOLUP   = 0,
  SWC_VOLDN   = 1,
  SWC_UP      = 2,
  SWC_DOWN    = 3,
  SWC_MUTE    = 4,
  SWC_MODE    = 5,
  SWC_NEXT    = 6,
  SWC_PREV    = 7,
  SWC_PICKUP  = 8,
  SWC_HANGUP  = 9,
  SWC_VOICE   = 10,
  SWC_SRC     = 11,
  SWC2_VOLUP  = 12,
  SWC2_VOLDN  = 13,
  SWC2_UP     = 14,
  SWC2_DOWN   = 15,
  SWC2_MUTE   = 16,
  SWC2_MODE   = 17,
  SWC2_NEXT   = 18,
  SWC2_PREV   = 19,
  SWC2_PICKUP = 20,
  SWC2_HANGUP = 21,
  SWC2_VOICE  = 22,
  SWC2_SRC    = 23,
};

const char* SWC_NAMES[SWC_BUTTON_COUNT] = {
  "VOL+", "VOL-", "UP", "DOWN", "MUTE", "MODE",
  "NEXT", "PREV", "PICKUP", "HANGUP", "VOICE", "SRC",
  "2:VOL+", "2:VOL-", "2:UP", "2:DOWN", "2:MUTE", "2:MODE",
  "2:NEXT", "2:PREV", "2:PICKUP", "2:HANGUP", "2:VOICE", "2:SRC"
};

// ADC calibration values — Pod 1 indices 0-11, Pod 2 indices 12-23
uint16_t swcValues[SWC_BUTTON_COUNT] = {
  75, 150, 230, 310, 390, 470,
  540, 610, 690, 760, 830, 900,
  75, 150, 230, 310, 390, 470,
  540, 610, 690, 760, 830, 900,
};

#ifdef FEATURE_ENCODER
// --- State: encoder ---
volatile int encoderPos = 0;
int lastEncoderPos = 0;
int lastCLK = HIGH;
#endif

#if defined(FEATURE_BUTTONS) || defined(FEATURE_ENCODER)
// --- State: main buttons (6: enc_sw, home, back, media, vol+, vol-) ---
#define MAIN_BTN_COUNT 6
unsigned long lastButtonTime[MAIN_BTN_COUNT] = {0};
bool lastButtonState[MAIN_BTN_COUNT] = {HIGH, HIGH, HIGH, HIGH, HIGH, HIGH};
const int buttonPins[MAIN_BTN_COUNT] = {ENC_SW, BTN_HOME, BTN_BACK, BTN_MEDIA, BTN_VOLUP, BTN_VOLDN};
#endif

#ifdef FEATURE_MUSIC
// --- State: music panel buttons (5) ---
#define MUSIC_BTN_COUNT 5
unsigned long lastMusicTime[MUSIC_BTN_COUNT] = {0};
bool lastMusicState[MUSIC_BTN_COUNT] = {HIGH, HIGH, HIGH, HIGH, HIGH};
const int musicPins[MUSIC_BTN_COUNT] = {MUS_PREV, MUS_NEXT, MUS_VOLUP, MUS_VOLDN, MUS_MUTE};
#endif

#ifdef FEATURE_STALK
// --- State: stalk brightness button ---
unsigned long lastStalkTime = 0;
bool lastStalkState = HIGH;
#endif

#ifdef FEATURE_SWC
// --- State: SWC (per-pod) ---
//
// reported  — ostatni stan wysłany do komputera (-1 = spoczynek)
// candidate — odczyt oczekujący na potwierdzenie
// candAt    — od kiedy candidate jest niezmienny
struct SwcPod {
  uint8_t      pin;
  uint8_t      offset;
  int8_t       reported;
  int8_t       candidate;
  unsigned long candAt;
  const char*  tag;
};

SwcPod swcPods[2] = {
  {SWC_PIN1, 0,                   -1, -1, 0, "SWC1"},
  {SWC_PIN2, SWC_BUTTONS_PER_POD, -1, -1, 0, "SWC2"},
};
#endif

#ifdef FEATURE_LIGHT
// --- State: light sensor ---
unsigned long lastLightReport = 0;
#endif

// --- Forward declarations ---
#if defined(FEATURE_BUTTONS) || defined(FEATURE_ENCODER)
void handleButtonPress(int buttonIndex);
#endif
#ifdef FEATURE_MUSIC
void handleMusicButton(int buttonIndex);
#endif
#ifdef FEATURE_ENCODER
void readEncoder();
#endif
#ifdef FEATURE_SWC
void handleSWCButton(int buttonIndex);
void loadSWCCalibration();
void saveSWCCalibration();
void runCalibration();
int  readSWCButton(uint8_t pin, uint8_t offset);
void handlePod(SwcPod &p, unsigned long now);
#endif
#ifdef FEATURE_LIGHT
void reportLightLevel();
#endif
int adcStable(uint8_t pin);

void setup() {
#ifdef FEATURE_ENCODER
  // Enkoder — INPUT_PULLUP, nie gołe INPUT. Bez podłączonej płytki enkodera
  // pin pływa, a przerwanie CHANGE sypie strzałkami do komputera. Zewnętrzne
  // 10 kΩ (jeśli je masz) po prostu zadziała równolegle.
  pinMode(ENC_CLK, INPUT_PULLUP);
  pinMode(ENC_DT, INPUT_PULLUP);
  pinMode(ENC_SW, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(ENC_CLK), readEncoder, CHANGE);
#endif

#ifdef FEATURE_BUTTONS
  pinMode(BTN_HOME, INPUT_PULLUP);
  pinMode(BTN_BACK, INPUT_PULLUP);
  pinMode(BTN_MEDIA, INPUT_PULLUP);
  pinMode(BTN_VOLUP, INPUT_PULLUP);
  pinMode(BTN_VOLDN, INPUT_PULLUP);
#endif

#ifdef FEATURE_MUSIC
  pinMode(MUS_PREV, INPUT_PULLUP);
  pinMode(MUS_NEXT, INPUT_PULLUP);
  pinMode(MUS_VOLUP, INPUT_PULLUP);
  pinMode(MUS_VOLDN, INPUT_PULLUP);
  pinMode(MUS_MUTE, INPUT_PULLUP);
#endif

#ifdef FEATURE_STALK
  pinMode(STALK_BTN_PIN, INPUT_PULLUP);
#endif

#ifdef FEATURE_SWC
  // INPUT_PULLUP, nie INPUT. Spoczynek jest tu zdefiniowany jako ADC ≈ VCC,
  // więc linia MUSI być czymś podciągnięta. Wewnętrzny pull-up (20–50 kΩ)
  // wystarcza na biurku; w aucie dołóż zewnętrzne 10 kΩ do VCC i skalibruj
  // pody DOPIERO po jego zamontowaniu — przy pasywnej drabince rezystorowej
  // podciągnięcie współtworzy dzielnik i zmienia wszystkie progi.
  pinMode(SWC_PIN1, INPUT_PULLUP);
  pinMode(SWC_PIN2, INPUT_PULLUP);
#endif

#ifdef FEATURE_LIGHT
  pinMode(LDR_PIN, INPUT);
#endif

  // Start USB HID
  Keyboard.begin();
  Consumer.begin();

  // Start serial for calibration/debug + light sensor data
  Serial.begin(115200);
  // Domyślny timeout to 1000 ms — przy strumieniu bez znaku nowej linii
  // readStringUntil() blokowałby pętlę na sekundę przy każdym przebiegu.
  Serial.setTimeout(50);

#ifdef FEATURE_SWC
  loadSWCCalibration();

#ifdef FEATURE_BUTTONS
  // Kalibracja z przycisków: HOME + BACK przy starcie. Sprawdzane tylko gdy
  // te przyciski są w ogóle skonfigurowane — inaczej czytalibyśmy pływający
  // pin i wchodzili w kalibrację przypadkiem.
  delay(100);
  if (digitalRead(BTN_HOME) == LOW && digitalRead(BTN_BACK) == LOW) {
    runCalibration();
  }
#endif
#endif

  Serial.println(F("BCM v8.5.3 Input Controller ready"));
#ifdef FEATURE_SWC
  Serial.println(F("SWC: wpisz CAL i Enter, aby uruchomic kalibracje podow"));
#endif

  // Watchdog ON dopiero po (ewentualnej) kalibracji — kalibracja
  // czeka na przyciski użytkownika dłużej niż 2 s.
  wdt_enable(WDTO_2S);
}

// Odczyt ADC odporny na przesłuch multipleksera i pojedyncze piki.
//
// ATmega32U4 ma jeden kondensator sample-and-hold na WSZYSTKIE kanały. Po
// przełączeniu kanału pierwsza konwersja niesie w sobie ładunek z kanału
// poprzedniego — przy wysokiej impedancji źródła praktycznie w całości.
// To dlatego niepodłączony Pod 2 raportował dokładnie to samo co Pod 1.
//
// Mediana zamiast średniej: pojedynczy pik przesuwa średnią, medianę
// zostawia w spokoju.
int adcStable(uint8_t pin) {
  analogRead(pin);                    // 1. przełącz multiplekser
  delayMicroseconds(ADC_SETTLE_US);
  analogRead(pin);                    // 2. S/H zdążył się naładować
  delayMicroseconds(ADC_SETTLE_US);

  int s[ADC_SAMPLES];
  for (uint8_t i = 0; i < ADC_SAMPLES; i++) {
    s[i] = analogRead(pin);
    delayMicroseconds(ADC_SPACING_US);
  }

  // Sortowanie przez wstawianie — przy 5 elementach najtańsze co do bajtów.
  for (uint8_t i = 1; i < ADC_SAMPLES; i++) {
    int v = s[i];
    int8_t j = (int8_t)i - 1;
    while (j >= 0 && s[j] > v) {
      s[j + 1] = s[j];
      j--;
    }
    s[j + 1] = v;
  }
  return s[ADC_SAMPLES / 2];
}

#ifdef FEATURE_SWC
// Jeden pod, jeden przebieg: odczyt → potwierdzenie → ewentualny HID.
//
// Zasada: nic nie leci do komputera, dopóki ten sam odczyt nie utrzyma się
// przez SWC_CONFIRM_MS. Dodatkowo między dwoma RÓŻNYMI przyciskami wymagany
// jest powrót do spoczynku — na drabince rezystorowej przeskok A→B bez
// rozwarcia to zawsze artefakt, nie intencja kierowcy.
void handlePod(SwcPod &p, unsigned long now) {
  int btn = readSWCButton(p.pin, p.offset);

  if (btn != p.candidate) {          // odczyt się zmienił — licz od nowa
    p.candidate = (int8_t)btn;
    p.candAt = now;
    return;
  }
  if ((now - p.candAt) < SWC_CONFIRM_MS) return;   // jeszcze nie stabilny
  if (btn == p.reported) return;                   // nic nowego

  if (btn >= 0 && p.reported >= 0) {
    // Przycisk → przycisk bez spoczynku pomiędzy. Czekamy na rozwarcie;
    // p.reported celowo NIE jest aktualizowane, więc kolejne przejścia też
    // są blokowane aż do powrotu na -1.
    return;
  }

  p.reported = (int8_t)btn;
  if (btn >= 0) {
    handleSWCButton(btn);
    Serial.print(p.tag);
    Serial.print(F(": "));
    Serial.println(SWC_NAMES[btn]);
  }
}
#endif

void loop() {
  wdt_reset();
  unsigned long now = millis();

#ifdef FEATURE_ENCODER
  // --- Handle encoder rotation ---
  if (encoderPos != lastEncoderPos) {
    int diff = encoderPos - lastEncoderPos;
    lastEncoderPos = encoderPos;

    if (diff > 0) {
      Keyboard.press(KEY_DOWN_ARROW);
      delay(10);
      Keyboard.release(KEY_DOWN_ARROW);
    } else if (diff < 0) {
      Keyboard.press(KEY_UP_ARROW);
      delay(10);
      Keyboard.release(KEY_UP_ARROW);
    }
  }
#endif

#if defined(FEATURE_BUTTONS) || defined(FEATURE_ENCODER)
  // --- Handle main buttons (debounced) ---
  // Bez FEATURE_ENCODER pomijamy indeks 0 (ENC_SW), bez FEATURE_BUTTONS
  // pomijamy resztę — pinMode tych pinów nie był ustawiany.
#ifdef FEATURE_ENCODER
  const int btnFrom = 0;
#else
  const int btnFrom = 1;
#endif
#ifdef FEATURE_BUTTONS
  const int btnTo = MAIN_BTN_COUNT;
#else
  const int btnTo = 1;
#endif
  for (int i = btnFrom; i < btnTo; i++) {
    bool currentState = digitalRead(buttonPins[i]);

    if (currentState != lastButtonState[i] && (now - lastButtonTime[i]) > DEBOUNCE_MS) {
      lastButtonTime[i] = now;
      lastButtonState[i] = currentState;

      if (currentState == LOW) {
        handleButtonPress(i);
      }
    }
  }
#endif

#ifdef FEATURE_MUSIC
  // --- Handle music panel buttons (debounced) ---
  for (int i = 0; i < MUSIC_BTN_COUNT; i++) {
    bool currentState = digitalRead(musicPins[i]);

    if (currentState != lastMusicState[i] && (now - lastMusicTime[i]) > DEBOUNCE_MS) {
      lastMusicTime[i] = now;
      lastMusicState[i] = currentState;

      if (currentState == LOW) {
        handleMusicButton(i);
      }
    }
  }
#endif

#ifdef FEATURE_STALK
  // --- Handle stalk brightness button (debounced) ---
  {
    bool stalkState = digitalRead(STALK_BTN_PIN);
    if (stalkState != lastStalkState && (now - lastStalkTime) > DEBOUNCE_MS) {
      lastStalkTime = now;
      lastStalkState = stalkState;

      if (stalkState == LOW) {
        Keyboard.press(KEY_F9);
        delay(10);
        Keyboard.release(KEY_F9);
        Serial.println(F("STALK: Brightness cycle"));
      }
    }
  }
#endif

#ifdef FEATURE_SWC
  // --- Handle SWC analog buttons (Pod 1 on A0, Pod 2 on A6) ---
  handlePod(swcPods[0], now);
  handlePod(swcPods[1], now);

  // --- Kalibracja na żądanie: wyślij "CAL" na port szeregowy ---
  // Alternatywa dla HOME + BACK przy starcie, która działa także wtedy, gdy
  // nie masz podłączonych przycisków (czyli w domyślnej konfiguracji).
  if (Serial.available() > 0) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    if (cmd.equalsIgnoreCase("CAL")) {
      wdt_disable();               // kalibracja czeka na człowieka > 2 s
      runCalibration();
      wdt_enable(WDTO_2S);
    }
  }
#endif

#ifdef FEATURE_LIGHT
  // --- Report light level periodically via serial ---
  if ((now - lastLightReport) > LIGHT_REPORT_MS) {
    reportLightLevel();
    lastLightReport = now;
  }
#endif

  delay(1);
}

#if defined(FEATURE_BUTTONS) || defined(FEATURE_ENCODER)
void handleButtonPress(int buttonIndex) {
  switch (buttonIndex) {
    case 0:  // Encoder push → Enter
      Keyboard.press(KEY_RETURN);
      delay(10);
      Keyboard.release(KEY_RETURN);
      break;
    case 1:  // HOME
      Keyboard.press(KEY_HOME);
      delay(10);
      Keyboard.release(KEY_HOME);
      break;
    case 2:  // BACK
      Keyboard.press(KEY_BACKSPACE);
      delay(10);
      Keyboard.release(KEY_BACKSPACE);
      break;
    case 3:  // MEDIA
      Consumer.write(MEDIA_PLAY_PAUSE);
      break;
    case 4:  // VOL+
      Consumer.write(MEDIA_VOLUME_UP);
      break;
    case 5:  // VOL-
      Consumer.write(MEDIA_VOLUME_DOWN);
      break;
  }
}
#endif

#ifdef FEATURE_MUSIC
void handleMusicButton(int buttonIndex) {
  switch (buttonIndex) {
    case 0:  // MUSIC PREV
      Consumer.write(MEDIA_PREVIOUS);
      Serial.println(F("MUSIC: PREV"));
      break;
    case 1:  // MUSIC NEXT
      Consumer.write(MEDIA_NEXT);
      Serial.println(F("MUSIC: NEXT"));
      break;
    case 2:  // MUSIC VOL+
      Consumer.write(MEDIA_VOLUME_UP);
      Serial.println(F("MUSIC: VOL+"));
      break;
    case 3:  // MUSIC VOL-
      Consumer.write(MEDIA_VOLUME_DOWN);
      Serial.println(F("MUSIC: VOL-"));
      break;
    case 4:  // MUSIC MUTE
      Consumer.write(MEDIA_VOLUME_MUTE);
      Serial.println(F("MUSIC: MUTE"));
      break;
  }
}
#endif

#ifdef FEATURE_SWC
void handleSWCButton(int buttonIndex) {
  // Pod 2 buttons (12-23) send the same keycodes as their Pod 1 equivalents
  int base = buttonIndex % SWC_BUTTONS_PER_POD;
  switch (base) {
    case 0:  // VOLUP
      Consumer.write(MEDIA_VOLUME_UP);
      break;
    case 1:  // VOLDN
      Consumer.write(MEDIA_VOLUME_DOWN);
      break;
    case 2:  // UP
      Keyboard.press(KEY_UP_ARROW);
      delay(10);
      Keyboard.release(KEY_UP_ARROW);
      break;
    case 3:  // DOWN
      Keyboard.press(KEY_DOWN_ARROW);
      delay(10);
      Keyboard.release(KEY_DOWN_ARROW);
      break;
    case 4:  // MUTE
      Consumer.write(MEDIA_VOLUME_MUTE);
      break;
    case 5:  // MODE → power toggle (F10)
      Keyboard.press(KEY_F10);
      delay(10);
      Keyboard.release(KEY_F10);
      break;
    case 6:  // NEXT
      Consumer.write(MEDIA_NEXT);
      break;
    case 7:  // PREV
      Consumer.write(MEDIA_PREVIOUS);
      break;
    case 8:  // PICKUP
      Keyboard.press(KEY_F5);
      delay(10);
      Keyboard.release(KEY_F5);
      break;
    case 9:  // HANGUP
      Keyboard.press(KEY_F6);
      delay(10);
      Keyboard.release(KEY_F6);
      break;
    case 10: // VOICE → voice AA trigger (F7)
      Keyboard.press(KEY_F7);
      delay(10);
      Keyboard.release(KEY_F7);
      break;
    case 11: // SRC → navigate AA (F8)
      Keyboard.press(KEY_F8);
      delay(10);
      Keyboard.release(KEY_F8);
      break;
  }
}

int readSWCButton(uint8_t pin, uint8_t offset) {
  int adc = adcStable(pin);

  if (adc > SWC_IDLE_THRESHOLD) {
    return -1;
  }

  int bestMatch = -1;
  int bestDiff = ADC_TOLERANCE + 1;

  for (int i = 0; i < SWC_BUTTONS_PER_POD; i++) {
    int diff = abs(adc - (int)swcValues[offset + i]);
    if (diff < bestDiff) {
      bestDiff = diff;
      bestMatch = offset + i;
    }
  }

  if (bestDiff <= ADC_TOLERANCE) {
    return bestMatch;
  }

  return -1;
}
#endif

#ifdef FEATURE_LIGHT
void reportLightLevel() {
  Serial.print(F("LIGHT:"));
  Serial.println(adcStable(LDR_PIN));
}
#endif

#ifdef FEATURE_SWC
// --- SWC calibration ---

void loadSWCCalibration() {
  if (EEPROM.read(EEPROM_MAGIC_ADDR) == EEPROM_MAGIC_VALUE) {
    for (int i = 0; i < SWC_BUTTON_COUNT; i++) {
      uint8_t lo = EEPROM.read(EEPROM_SWC_ADDR + i * 2);
      uint8_t hi = EEPROM.read(EEPROM_SWC_ADDR + i * 2 + 1);
      swcValues[i] = (hi << 8) | lo;
    }
    Serial.println("SWC: Loaded calibration from EEPROM");
  } else {
    Serial.println("SWC: Using default ADC values (not calibrated)");
  }
}

void saveSWCCalibration() {
  EEPROM.write(EEPROM_MAGIC_ADDR, EEPROM_MAGIC_VALUE);
  for (int i = 0; i < SWC_BUTTON_COUNT; i++) {
    EEPROM.write(EEPROM_SWC_ADDR + i * 2, swcValues[i] & 0xFF);
    EEPROM.write(EEPROM_SWC_ADDR + i * 2 + 1, (swcValues[i] >> 8) & 0xFF);
  }
  Serial.println("SWC: Calibration saved to EEPROM");
}

void calibratePod(uint8_t pin, uint8_t offset, const char* podName) {
  Serial.print("--- Calibrating ");
  Serial.print(podName);
  Serial.println(" ---");

  for (int i = 0; i < SWC_BUTTONS_PER_POD; i++) {
    Serial.print("Press: ");
    Serial.print(SWC_NAMES[offset + i]);
    Serial.println(" ...");

    // Czekaj na rozwarcie wszystkich przycisków tego poda.
    while (adcStable(pin) < SWC_IDLE_THRESHOLD) {
      delay(50);
    }
    delay(300);

    // Czekaj na wciśnięcie i zmierz. adcStable() już odrzuca przesłuch
    // multipleksera i pojedyncze piki, więc jedna próbka wystarczy.
    int adc = 0;
    while (true) {
      adc = adcStable(pin);
      if (adc < SWC_IDLE_THRESHOLD) {
        break;
      }
      delay(20);
    }

    swcValues[offset + i] = adc;
    Serial.print("  -> ADC = ");
    Serial.println(adc);
    delay(300);
  }

  // Check for collisions within this pod
  for (int i = 0; i < SWC_BUTTONS_PER_POD; i++) {
    for (int j = i + 1; j < SWC_BUTTONS_PER_POD; j++) {
      if (abs((int)swcValues[offset + i] - (int)swcValues[offset + j]) < ADC_TOLERANCE) {
        Serial.print("  WARNING: ");
        Serial.print(SWC_NAMES[offset + i]);
        Serial.print(" and ");
        Serial.print(SWC_NAMES[offset + j]);
        Serial.println(" are too close! Re-calibrate.");
      }
    }
  }
}

void runCalibration() {
  Serial.println();
  Serial.println("=== SWC CALIBRATION MODE (Dual Pod) ===");
  Serial.println("Press each steering wheel button when prompted.");
  Serial.println("Release all buttons between presses.");
  Serial.println();

  calibratePod(SWC_PIN1, 0, "Pod 1 (A0)");
  Serial.println();
  calibratePod(SWC_PIN2, SWC_BUTTONS_PER_POD, "Pod 2 (A6 = pad 4)");

  Serial.println();
  Serial.println("Calibration results:");
  for (int i = 0; i < SWC_BUTTON_COUNT; i++) {
    Serial.print("  ");
    Serial.print(SWC_NAMES[i]);
    Serial.print(": ");
    Serial.println(swcValues[i]);
  }

  saveSWCCalibration();
  Serial.println("=== CALIBRATION COMPLETE ===");
  Serial.println();
}
#endif  // FEATURE_SWC

#ifdef FEATURE_ENCODER
void readEncoder() {
  int clkState = digitalRead(ENC_CLK);
  int dtState = digitalRead(ENC_DT);

  if (clkState != lastCLK) {
    if (dtState != clkState) {
      encoderPos++;
    } else {
      encoderPos--;
    }
    lastCLK = clkState;
  }
}
#endif  // FEATURE_ENCODER
