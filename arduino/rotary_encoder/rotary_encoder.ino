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
 *   A0 ← SWC pod ("KEY", biały przewód) — analog 0-5V (drabinka rezystorów).
 *        WYMAGA pull-up z A0 do VCC (5V). Dla TEGO modułu (rezystancje padów
 *        1Ω..14,66kΩ) właściwa wartość to **1 kΩ** — 10 kΩ ściska sześć padów
 *        o niskiej rezystancji w ADC 0-70 (nakładają się), a 330 kΩ pływa i
 *        "wariuje". 1 kΩ rozkłada wszystkie 10 padów w 0-1023 (patrz swcValues).
 *   A6 ← (NIEUŻYWANE) — drugi pod wyłączony w tej wersji (jeden pod).
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
 * Adapter SWC (uczący się, z Aliexpress): kostka red → 12V ACC, black → GND,
 * KEY (biały) → A0. Masa kostki MUSI być wspólna z GND Pro Micro. Pro Micro
 * zasilany z USB M910q (nie z 12V). Pull-up 1 kΩ z A0 do VCC. Jeden pod.
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
 * v8.5.4 — JEDEN pod, 10 przycisków, bez power-toggle
 *
 * Konfiguracja quick-start: tylko Pod 1 (A0), drugi pod (A6) wyłączony.
 * Zestaw 10 przycisków w kolejności kalibracji: VOL+, VOL-, MUTE, NEXT, PREV,
 * HOME, PICKUP (odbierz), HANGUP (odrzuć), VOICE (mikrofon), NAV (nawigacja).
 * Slot "MODE" (dawniej F10 → input.bcm_power_toggle) SKASOWANY i zastąpiony
 * przez HOME (KEY_HOME → ekran A1) — szum ADC nie wyłączy już komputera.
 * Kalibracja pyta tylko o te 10 przycisków. Pull-up ma być 1 kΩ (patrz wyżej).
 * ---------------------------------------------------------------------------
 * v8.6 — panel z pokrętłem (drugi pod na A6), długie play/pause = uśpienie,
 *        przycisk z manetki = następny ekran
 *
 * Panel („smart steering wheel controller”): bezprzewodowy pasek z pokrętłem,
 * odbiornik w czarnej kostce — biały KEY1, czerwony +12 V, czarny GND.
 * Kostka zwiera KEY1 do masy przez inną rezystancję dla każdego przycisku,
 * dokładnie jak adapter SWC na A0. Dlatego: KEY1 → A6 (= D4) + pull-up
 * **1 kΩ do 5 V**, masa kostki wspólna z GND Pro Micro.
 * Przyciski panelu (FEATURE_PANEL, kalibracja: CAL2):
 *   VOL+ / VOL- (pokrętło), PLAY (wciśnięcie pokrętła), NEXT, PREV, MUTE,
 *   PICKUP, HANGUP, VOICE (mikrofon).
 * PLAY: krótko → MEDIA_PLAY_PAUSE; trzymane ≥ PLAY_LONG_MS → F13
 *   (BCM: input.system_sleep → bcm-power-toggle.sh: stop BCM, S3).
 * Manetka (FEATURE_STALK, A2 przez transoptor): F14 → input.screen_next
 *   (następny ekran). Stare zachowanie (F9, cykl jasności): STALK_F9.
 * Logika wciśnięć: press_logic.h (test na hoście: test/test_press_logic.cpp).
 * Schemat podłączenia: docs/SCHEMATY_POLACZEN.md §4.3.
 * ---------------------------------------------------------------------------
 */

#include <avr/wdt.h>
// UWAGA: nie dołączać <Keyboard.h> — HID-Project dostarcza własny obiekt
// Keyboard (ImprovedKeyboard) i definiuje KEY_* jako enum; makra KEY_*
// ze stockowego Keyboard.h psują kompilację (konflikt makro vs enum).
#include <HID-Project.h>
#include <EEPROM.h>
#include "press_logic.h"

// --- Przełączniki funkcji -------------------------------------------------
// Zakomentuj to, czego nie masz podłączonego. Niepodłączone wejścia cyfrowe
// z pull-upem są nieszkodliwe, ale wyłączenie ich skraca pętlę i usuwa szum
// z portu szeregowego. Wejścia ANALOGOWE wyłączaj zawsze, gdy nic na nich
// nie wisi — pływający pin to śmieci w multiplekserze ADC.
//
// Domyślnie: tylko pody SWC. To jedyna rzecz, która ma teraz działać.
#define FEATURE_SWC        // adapter SWC kierownicy na A0 (10 przycisków)
#define FEATURE_PANEL      // panel z pokrętłem na A6 (KEY1 kostki odbiornika)
// #define FEATURE_ENCODER // enkoder obrotowy + przycisk (D2, D3, D1)
// #define FEATURE_BUTTONS // HOME / BACK / MEDIA / VOL+ / VOL− (D5–D9)
// #define FEATURE_MUSIC   // panel muzyczny (D10, D14, D15, D16, A3)
#define FEATURE_STALK      // przycisk manetki (A2) → F14 = następny ekran
// #define STALK_F9        // ...albo stare F9 = cykl jasności zamiast ekranu
// #define FEATURE_LIGHT   // fotorezystor LDR (A1)
// #define FEATURE_FUEL    // czujnik paliwa (A4) — patrz #error niżej

#if defined(FEATURE_FUEL)
#error "A4 nie jest wyprowadzone na klasycznym Pro Micro (PF1). Potrzebny klon z padem A4 albo inna plytka — patrz docs/ARDUINO_SETUP_GUIDE.md."
#endif

#if !defined(FEATURE_SWC) && !defined(FEATURE_PANEL) && !defined(FEATURE_ENCODER) \
    && !defined(FEATURE_BUTTONS) && !defined(FEATURE_MUSIC) && !defined(FEATURE_STALK) \
    && !defined(FEATURE_LIGHT)
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

// --- Długie naciśnięcie (PLAY na panelu) ---
// 2 s: dość, żeby zwykłe „pauza” nigdy go nie wyzwoliło, i nie tak długo,
// żeby kierowca zwątpił, czy działa.
#define PLAY_LONG_MS 2000

#define SWC_IDLE_THRESHOLD 1000
// Wartość „nieskalibrowany” — większa niż każdy odczyt ADC (0..1023),
// więc taki przycisk nigdy nie zostanie rozpoznany.
#define ADC_UNSET 0xFFFF

// --- Akcje (co wysłać do komputera) ---
enum Action : uint8_t {
  ACT_VOLUP, ACT_VOLDN, ACT_MUTE, ACT_NEXT, ACT_PREV, ACT_HOME,
  ACT_PICKUP, ACT_HANGUP, ACT_VOICE, ACT_NAV, ACT_PLAY,
};

// --- Pod 1: adapter SWC kierownicy (A0) — 10 przycisków, układ bez zmian ---
#define SWC_BUTTON_COUNT 10
const char* const SWC_NAMES[SWC_BUTTON_COUNT] = {
  "VOL+", "VOL-", "MUTE", "NEXT", "PREV",
  "HOME", "PICKUP", "HANGUP", "VOICE", "NAV"
};
const Action SWC_ACTIONS[SWC_BUTTON_COUNT] = {
  ACT_VOLUP, ACT_VOLDN, ACT_MUTE, ACT_NEXT, ACT_PREV,
  ACT_HOME, ACT_PICKUP, ACT_HANGUP, ACT_VOICE, ACT_NAV,
};

// ADC calibration values (pod 1). WSTĘPNE, policzone z rezystancji
// zmierzonych na module SWC (biały↔GND) i pull-upu 1 kΩ do 5 V:
//   ADC = 1023 * R / (R + 1000)
//   VOL+ 734Ω→433  VOL- 181Ω→157  MUTE 1863Ω→666  NEXT 472Ω→328  PREV 1Ω→1
//   HOME 331Ω→254  PICKUP 1237Ω→566  HANGUP 14660Ω→958  VOICE 4110Ω→823  NAV 82Ω→78
// Rozrzut min. 74 (tolerancja 40) — pody rozróżnialne. Uruchom CAL, by
// dostroić pod tolerancje własnego rezystora; te wartości działają od razu.
uint16_t swcValues[SWC_BUTTON_COUNT] = {
  433, 157, 666, 328, 1, 254, 566, 958, 823, 78,
};

// --- Pod 2: panel z pokrętłem (A6, KEY1 kostki odbiornika) — 9 przycisków ---
#define PANEL_BUTTON_COUNT 9
const char* const PANEL_NAMES[PANEL_BUTTON_COUNT] = {
  "VOL+", "VOL-", "PLAY", "NEXT", "PREV", "MUTE", "PICKUP", "HANGUP", "VOICE"
};
const Action PANEL_ACTIONS[PANEL_BUTTON_COUNT] = {
  ACT_VOLUP, ACT_VOLDN, ACT_PLAY, ACT_NEXT, ACT_PREV, ACT_MUTE,
  ACT_PICKUP, ACT_HANGUP, ACT_VOICE,
};
// Rezystancji tej kostki nie znamy — do pierwszej kalibracji (CAL2) żaden
// przycisk panelu nie jest rozpoznawany (wartość większa niż każdy odczyt).
uint16_t panelValues[PANEL_BUTTON_COUNT] = {
  ADC_UNSET, ADC_UNSET, ADC_UNSET, ADC_UNSET, ADC_UNSET,
  ADC_UNSET, ADC_UNSET, ADC_UNSET, ADC_UNSET,
};

// --- EEPROM layout ---
// Pod 1 zostaje tam, gdzie był (kalibracje z v8.5.4 przeżywają aktualizację).
#define EEPROM_MAGIC_ADDR 0
#define EEPROM_MAGIC_VALUE 0xBF   // wstępne nastawy z pomiarów (pull-up 1k)
#define EEPROM_SWC_ADDR 1         // 10 x 2 bytes = 20 bytes (1..20)
#define EEPROM_PANEL_MAGIC_ADDR 32
#define EEPROM_PANEL_MAGIC_VALUE 0xC1
#define EEPROM_PANEL_ADDR 33      // 9 x 2 bytes = 18 bytes (33..50)

// Opis jednego poda drabinki: pin, tablica nazw / akcji / progów ADC.
struct LadderPod {
  uint8_t          pin;
  uint8_t          count;
  const char* const* names;
  const Action*    actions;
  uint16_t*        values;
  const char*      tag;
  PressState       st;
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

#if defined(FEATURE_SWC) || defined(FEATURE_PANEL)
// --- State: pody drabinek rezystorowych ---
#ifdef FEATURE_SWC
LadderPod swcPod = {SWC_PIN1, SWC_BUTTON_COUNT, SWC_NAMES, SWC_ACTIONS, swcValues,
                    "SWC", {-1, -1, 0, 0, false}};
#endif
#ifdef FEATURE_PANEL
LadderPod panelPod = {SWC_PIN2, PANEL_BUTTON_COUNT, PANEL_NAMES, PANEL_ACTIONS, panelValues,
                      "PANEL", {-1, -1, 0, 0, false}};
#endif
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
#if defined(FEATURE_SWC) || defined(FEATURE_PANEL)
void doAction(Action a);
void tapKey(KeyboardKeycode k);
int8_t readLadder(const LadderPod &p);
void handlePod(LadderPod &p, unsigned long now);
void loadCalibration();
void calibratePod(LadderPod &p, uint8_t magicAddr, uint8_t magicValue, uint8_t dataAddr);
void handleSerialCommand();
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
  // wystarcza na biurku; w aucie dołóż zewnętrzne 1 kΩ do VCC i skalibruj
  // pody DOPIERO po jego zamontowaniu — przy pasywnej drabince rezystorowej
  // podciągnięcie współtworzy dzielnik i zmienia wszystkie progi.
  pinMode(SWC_PIN1, INPUT_PULLUP);
#endif
#ifdef FEATURE_PANEL
  // A6 = D4. Jak przy A0: wewnętrzny pull-up tylko na biurko, w aucie
  // zewnętrzne 1 kΩ do 5 V i kalibracja (CAL2) DOPIERO z nim.
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

#if defined(FEATURE_SWC) || defined(FEATURE_PANEL)
  loadCalibration();
#ifdef FEATURE_SWC
  pressInit(swcPod.st, millis());
#endif
#ifdef FEATURE_PANEL
  pressInit(panelPod.st, millis());
#endif
#endif

#if defined(FEATURE_SWC) && defined(FEATURE_BUTTONS)
  // Kalibracja z przycisków: HOME + BACK przy starcie. Sprawdzane tylko gdy
  // te przyciski są w ogóle skonfigurowane — inaczej czytalibyśmy pływający
  // pin i wchodzili w kalibrację przypadkiem.
  delay(100);
  if (digitalRead(BTN_HOME) == LOW && digitalRead(BTN_BACK) == LOW) {
    calibratePod(swcPod, EEPROM_MAGIC_ADDR, EEPROM_MAGIC_VALUE, EEPROM_SWC_ADDR);
  }
#endif

  Serial.println(F("BCM v8.6 Input Controller ready"));
#ifdef FEATURE_SWC
  Serial.println(F("SWC (A0): wpisz CAL i Enter, aby skalibrowac"));
#endif
#ifdef FEATURE_PANEL
  Serial.println(F("PANEL (A6): wpisz CAL2 i Enter, aby skalibrowac; ADC2 = podglad"));
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

#if defined(FEATURE_SWC) || defined(FEATURE_PANEL)
// PLAY ma długie naciśnięcie, reszta przycisków reaguje od razu.
static bool isHoldable(const LadderPod &p, int8_t b) {
  return b >= 0 && b < (int8_t)p.count && p.actions[b] == ACT_PLAY;
}

// Jeden pod, jeden przebieg: odczyt → press_logic.h → ewentualny HID.
// Zasady potwierdzania (SWC_CONFIRM_MS, powrót do spoczynku między
// przyciskami) i długie naciśnięcie są w press_logic.h.
void handlePod(LadderPod &p, unsigned long now) {
  int8_t btn = readLadder(p);
  int8_t which;
  PressEvent ev = pressStep(p.st, btn, now, SWC_CONFIRM_MS, PLAY_LONG_MS,
                            [&p](int8_t b) { return isHoldable(p, b); }, which);
  if (ev == PRESS_NONE || which < 0) return;

  Serial.print(p.tag);
  Serial.print(F(": "));
  Serial.print(p.names[which]);
  if (ev == PRESS_LONG) {
    // Długie PLAY → F13 → BCM: input.system_sleep (stop BCM + S3).
    Serial.println(F(" (dlugo) -> SLEEP"));
    tapKey(KEY_F13);
    return;
  }
  Serial.println();
  doAction(p.actions[which]);        // PRESS_DOWN albo PRESS_SHORT (PLAY)
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
#ifdef STALK_F9
        Keyboard.press(KEY_F9);      // stare: cykl jasności
        delay(10);
        Keyboard.release(KEY_F9);
        Serial.println(F("STALK: Brightness cycle"));
#else
        Keyboard.press(KEY_F14);     // BCM: input.screen_next — następny ekran
        delay(10);
        Keyboard.release(KEY_F14);
        Serial.println(F("STALK: Next screen"));
#endif
      }
    }
  }
#endif

#ifdef FEATURE_SWC
  handlePod(swcPod, now);            // adapter SWC kierownicy (A0)
#endif
#ifdef FEATURE_PANEL
  handlePod(panelPod, now);          // panel z pokrętłem (A6)
#endif
#if defined(FEATURE_SWC) || defined(FEATURE_PANEL)
  // Kalibracja / podgląd na żądanie przez port szeregowy (CAL, CAL2, ADC2).
  if (Serial.available() > 0) {
    handleSerialCommand();
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

#if defined(FEATURE_SWC) || defined(FEATURE_PANEL)
void tapKey(KeyboardKeycode k) {
  Keyboard.press(k);
  delay(10);
  Keyboard.release(k);
}

// Akcja → klawisz HID. Mapowanie po stronie BCM: src/input/action_dispatch.py.
void doAction(Action a) {
  switch (a) {
    case ACT_VOLUP:  Consumer.write(MEDIA_VOLUME_UP);   break;
    case ACT_VOLDN:  Consumer.write(MEDIA_VOLUME_DOWN); break;
    case ACT_MUTE:   Consumer.write(MEDIA_VOLUME_MUTE); break;
    case ACT_NEXT:   Consumer.write(MEDIA_NEXT);        break;
    case ACT_PREV:   Consumer.write(MEDIA_PREVIOUS);    break;
    case ACT_PLAY:   Consumer.write(MEDIA_PLAY_PAUSE);  break;
    case ACT_HOME:   tapKey(KEY_HOME); break;   // ekran A1
    case ACT_PICKUP: tapKey(KEY_F5);   break;   // input.phone_pickup
    case ACT_HANGUP: tapKey(KEY_F6);   break;   // input.phone_hangup
    case ACT_VOICE:  tapKey(KEY_F7);   break;   // input.voice_aa_trigger
    case ACT_NAV:    tapKey(KEY_F8);   break;   // input.navigate_aa → A2
  }
}

int8_t readLadder(const LadderPod &p) {
  int adc = adcStable(p.pin);
  if (adc > SWC_IDLE_THRESHOLD) {
    return -1;
  }
  int8_t bestMatch = -1;
  int bestDiff = ADC_TOLERANCE + 1;
  for (uint8_t i = 0; i < p.count; i++) {
    if (p.values[i] == ADC_UNSET) continue;          // nieskalibrowany
    int diff = abs(adc - (int)p.values[i]);
    if (diff < bestDiff) {
      bestDiff = diff;
      bestMatch = (int8_t)i;
    }
  }
  return bestDiff <= ADC_TOLERANCE ? bestMatch : -1;
}
#endif

#ifdef FEATURE_LIGHT
void reportLightLevel() {
  Serial.print(F("LIGHT:"));
  Serial.println(adcStable(LDR_PIN));
}
#endif

#if defined(FEATURE_SWC) || defined(FEATURE_PANEL)
// --- Kalibracja podów (EEPROM) ---

static void loadPod(LadderPod &p, uint8_t magicAddr, uint8_t magicValue, uint8_t dataAddr) {
  if (EEPROM.read(magicAddr) != magicValue) {
    Serial.print(p.tag);
    Serial.println(F(": wartosci domyslne (nie skalibrowano)"));
    return;
  }
  for (uint8_t i = 0; i < p.count; i++) {
    uint8_t lo = EEPROM.read(dataAddr + i * 2);
    uint8_t hi = EEPROM.read(dataAddr + i * 2 + 1);
    p.values[i] = (uint16_t)((hi << 8) | lo);
  }
  Serial.print(p.tag);
  Serial.println(F(": kalibracja z EEPROM"));
}

void loadCalibration() {
#ifdef FEATURE_SWC
  loadPod(swcPod, EEPROM_MAGIC_ADDR, EEPROM_MAGIC_VALUE, EEPROM_SWC_ADDR);
#endif
#ifdef FEATURE_PANEL
  loadPod(panelPod, EEPROM_PANEL_MAGIC_ADDR, EEPROM_PANEL_MAGIC_VALUE, EEPROM_PANEL_ADDR);
#endif
}

// Pyta kolejno o każdy przycisk poda, mierzy ADC i zapisuje do EEPROM.
// Watchdog musi być wyłączony (czeka na człowieka dłużej niż 2 s).
void calibratePod(LadderPod &p, uint8_t magicAddr, uint8_t magicValue, uint8_t dataAddr) {
  Serial.println();
  Serial.print(F("=== KALIBRACJA "));
  Serial.print(p.tag);
  Serial.println(F(" — zwalniaj przycisk miedzy wcisnieciami ==="));

  for (uint8_t i = 0; i < p.count; i++) {
    Serial.print(F("Nacisnij: "));
    Serial.print(p.names[i]);
    Serial.println(F(" ..."));

    while (adcStable(p.pin) < SWC_IDLE_THRESHOLD) {   // czekaj na rozwarcie
      delay(50);
    }
    delay(300);
    int adc = 0;
    while (true) {                                    // czekaj na wcisniecie
      adc = adcStable(p.pin);
      if (adc < SWC_IDLE_THRESHOLD) break;
      delay(20);
    }
    delay(80);                                        // ustalenie stanu
    adc = adcStable(p.pin);
    p.values[i] = (uint16_t)adc;
    Serial.print(F("  -> ADC = "));
    Serial.println(adc);
    delay(300);
  }

  for (uint8_t i = 0; i < p.count; i++) {
    for (uint8_t j = i + 1; j < p.count; j++) {
      if (abs((int)p.values[i] - (int)p.values[j]) < ADC_TOLERANCE) {
        Serial.print(F("  UWAGA: "));
        Serial.print(p.names[i]);
        Serial.print(F(" i "));
        Serial.print(p.names[j]);
        Serial.println(F(" za blisko — inny pull-up albo kalibracja jeszcze raz"));
      }
    }
  }

  EEPROM.write(magicAddr, magicValue);
  for (uint8_t i = 0; i < p.count; i++) {
    EEPROM.write(dataAddr + i * 2, p.values[i] & 0xFF);
    EEPROM.write(dataAddr + i * 2 + 1, (p.values[i] >> 8) & 0xFF);
  }
  Serial.println(F("=== ZAPISANO W EEPROM ==="));
  Serial.println();
}

// CAL — pod SWC (A0), CAL2 — panel (A6), ADC2 — 5 s podglądu surowego ADC
// panelu (sprawdzenie pull-upu i tego, czy kostka trzyma stan przy
// przytrzymaniu — od tego zależy długie PLAY).
void handleSerialCommand() {
  String cmd = Serial.readStringUntil('\n');
  cmd.trim();
  wdt_disable();
#ifdef FEATURE_SWC
  if (cmd.equalsIgnoreCase("CAL")) {
    calibratePod(swcPod, EEPROM_MAGIC_ADDR, EEPROM_MAGIC_VALUE, EEPROM_SWC_ADDR);
  }
#endif
#ifdef FEATURE_PANEL
  if (cmd.equalsIgnoreCase("CAL2")) {
    calibratePod(panelPod, EEPROM_PANEL_MAGIC_ADDR, EEPROM_PANEL_MAGIC_VALUE, EEPROM_PANEL_ADDR);
  } else if (cmd.equalsIgnoreCase("ADC2")) {
    for (uint8_t i = 0; i < 25; i++) {
      Serial.print(F("ADC2: "));
      Serial.println(adcStable(SWC_PIN2));
      delay(200);
    }
  }
#endif
  wdt_enable(WDTO_2S);
}
#endif  // FEATURE_SWC || FEATURE_PANEL

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
