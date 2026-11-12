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
 *   BATT:12650,-3400                             bank buforowy: napięcie [mV],
 *                                                prąd [mA] (+ ładowanie,
 *                                                - rozładowanie). Bez INA226
 *                                                tylko napięcie: BATT:12650
 *
 * ================= WŁĄCZANIE / WYŁĄCZANIE FUNKCJI =================
 * Każda funkcja ma własny przełącznik kompilacji. Zakomentuj
 * #define, żeby całkowicie usunąć funkcję z firmware (pin wraca
 * do dyspozycji). Po zmianie: make -C arduino sensor_hub-upload
 * Funkcje zakomentowane niżej lepiej włączać flagą niż edycją sketcha
 * (repo zostaje czyste, git pull bez konfliktów), a BATT_* WYŁĄCZNIE
 * flagą — patrz blok „Pomiar banku buforowego” niżej:
 *   make -C arduino sensor_hub-upload PORT=/dev/ttyUSB0 SENSOR_HUB_FEATURES=BATT_ADC
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
// #define FEATURE_BATT_ADC    // napięcie banku przez dzielnik 100k/27k na A6
                               // (ZASILANIE_BUFOROWANE.md §13.4). Tylko napięcie.
// #define FEATURE_BATT_INA226 // INA226 na I2C (A4=SDA, A5=SCL) + bocznik
                               // — napięcie I prąd banku. Zalecane: prąd
                               // odróżnia ładowanie od postoju i pozwala
                               // liczyć stan naładowania. Wyklucza się
                               // z FEATURE_CRUISE/IMMO i FEATURE_BATT_ADC.
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
 *   A4/A5 I2C SDA/SCL do INA226        (FEATURE_BATT_INA226)
 *   A6  Dzielnik napięcia banku        (FEATURE_BATT_ADC; wejście tylko
 *       analogowe: +BANK─100k─┬─A6, ┴─27k─GND, 100 nF A6─GND)
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
 * miga = S3, zgaszona = wyłączony) i sam się synchronizuje. Rytm migania
 * M910q w S3 NIE jest sprawdzony na stole: przed poleganiem na eskalacji
 * trzeba zobaczyć, że w S3 każda linia to PWR:SLEEP, bez przeskoków
 * (docs/WDROZENIE_TESTOWE.md §3.1a). Naciskamy tylko na stan, który się
 * utrzymał, więc dioda, której nie da się odczytać, nie budzi komputera
 * na postoju (po włączeniu zapłonu pobudka przychodzi wtedy po ~30 s).
 *
 * Po 2 h zgaszonego zapłonu eskalacja do OFF: LONG (5 s) dostaje TYLKO
 * maszyna stabilnie uśpiona. Działającą (np. obudzoną ręcznie) najpierw
 * usypia SHORT, LONG idzie po potwierdzeniu S3. Ręczne wybudzenie przy
 * zgaszonym zapłonie liczy 2 h od nowa. W pętli otwartej „uśpiona” znaczy
 * „tak zakładamy po własnym SHORT” — tu tylko dioda daje pewność.
 * Po SHORT na pracującą maszynę firmware przez 90 s nie naciska drugi raz
 * (bcm-power-toggle.sh najpierw zatrzymuje BCM, do 45 s, a drugie
 * wciśnięcie uśpiłoby ją ponownie po wybudzeniu); gdy zapłon wróci w tym
 * czasie, a maszyna jednak zaśnie, dostaje SHORT i wstaje.
 * Sama logika (bez I/O) siedzi w power_logic.h i ma testy na PC, także
 * dla przepełnienia millis() po ~49,7 dnia: make -C arduino sensor_hub-test
 */

#include <avr/wdt.h>

#ifdef FEATURE_BATT_INA226
#include <Wire.h>
#endif

#ifdef FEATURE_PWRBTN
#include "power_logic.h"
#endif

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
#if defined(FEATURE_BATT_INA226) && (defined(FEATURE_CRUISE) || defined(FEATURE_IMMO))
#error "Konflikt pinow: FEATURE_BATT_INA226 uzywa A4/A5 (I2C), tak jak CRUISE/IMMO"
#endif
#if defined(FEATURE_BATT_INA226) && defined(FEATURE_BATT_ADC)
#error "Wybierz jedno zrodlo pomiaru banku: FEATURE_BATT_INA226 albo FEATURE_BATT_ADC"
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
// Czasy decyzji (cisza po impulsie, potwierdzenie zapłonu, eskalacja po 2 h,
// okno usypiania) i dekoder diody (PWR_LED_WINDOW_MS) są w power_logic.h
// razem z logiką, którą testuje się na PC.
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
const char* const PWR_NAMES[4] = {"UNKNOWN", "RUNNING", "SLEEP", "OFF"};

#ifdef FEATURE_PWRLED
#define PWR_CLOSED_LOOP true
#else
#define PWR_CLOSED_LOOP false
#endif

PwrLogic      pwr;                       // stan i decyzje: power_logic.h
PwrState      pwrReported = PWR_UNKNOWN; // ostatnio wysłane PWR:

// Osobna flaga zamiast „pwrPulseUntil == 0 znaczy brak impulsu”: millis()+ms
// potrafi po przepełnieniu wypaść dokładnie na 0 i przekaźnik zostałby
// zwarty na stałe.
bool          pwrPulsing    = false;
unsigned long pwrPulseUntil = 0;         // koniec trwającego impulsu
#endif

#ifdef FEATURE_PWRLED
PwrLed        pwrLed;                    // zbocza diody → stan: power_logic.h
#endif

unsigned long lastStateRefresh = 0;

// =============================================================================
// Pomiar banku buforowego (BATT:). Raport idzie razem z pełnym stanem co 2 s.
// Oba warianty są domyślnie wyłączone; CI kompiluje każdy z nich osobno
// (make -C arduino sensor_hub-variants, flaga -DFEATURE_BATT_...), więc
// przełączniki wyżej muszą zostać zakomentowane — sama flaga je zastępuje.
// Wgranie na płytkę z pomiarem banku (też przez flagę, bez edycji sketcha):
//   make -C arduino sensor_hub-upload PORT=/dev/ttyUSB0 SENSOR_HUB_FEATURES=BATT_ADC
// (albo BATT_INA226). Kalibracja: ZASILANIE_BUFOROWANE.md §13.4.
// Po stronie BCM: src/input/arduino_serial.py → arduino.battery_voltage/
// _current, src/power/battery.py (modules.battery, domyślnie wyłączony).
// =============================================================================
#ifdef FEATURE_BATT_ADC
#define PIN_BATT_ADC     A6
// Dzielnik 100k/27k: V_bank = V_adc * (100 + 27) / 27. Przy 15 V na A6 jest
// 3,19 V – bezpiecznie poniżej 5 V. Referencją jest VCC z MP1584, więc
// współczynnik trzeba SKALIBROWAĆ: zmierz multimetrem napięcie banku i ustaw
// BATT_ADC_CAL tak, żeby BATT: w monitorze portu pokazywał to samo. BATT:
// zawiera już obecną korektę, więc: nowe = obecne × U_multimetr / U_BATT
// (ZASILANIE_BUFOROWANE.md §13.4).
#define BATT_ADC_VREF_MV 5000L
#define BATT_ADC_R1_K     100L
#define BATT_ADC_R2_K      27L
// Liczy się tylko STOSUNEK R1:R2 — jednostka dowolna, byle wspólna. Stałe
// są typu long, żeby rachunek w battReport() został na liczbach
// całkowitych. Wariant 10k/2,2k: wpisz R1_K=100, R2_K=22 (oba ×10), a nie
// 10 i 2.2 — ułamek przełączyłby całe wyrażenie na float (zadziała, ale
// po nic). Przy 15 V na A6 jest wtedy 2,70 V.
// Wybór dzielnika: 100k/27k to ~21 kΩ impedancji źródła, więcej niż
// zalecane dla ADC 10 kΩ, więc kondensator 100 nF A6─GND jest OBOWIĄZKOWY
// (on ładuje kondensator próbkujący). 10k/2,2k obejdzie się bez niego, ale
// stale pobiera z banku ~1 mA zamiast ~0,1 mA (≈ 25 mAh na dobę postoju).
// Przepełnienie: 1023 * BATT_ADC_VREF_MV * (R1 + R2) musi zmieścić się
// w long (2^31), czyli R1 + R2 <= 400.
#define BATT_ADC_CAL     1.000f   // korekta po kalibracji (np. 1.012)
#define BATT_ADC_SAMPLES     9    // nieparzyście – mediana

static_assert(BATT_ADC_SAMPLES % 2 == 1 && BATT_ADC_SAMPLES <= 31,
              "BATT_ADC_SAMPLES: nieparzysta liczba <= 31 (mediana, int8_t j)");
static_assert(BATT_ADC_R1_K + BATT_ADC_R2_K <= 400,
              "BATT_ADC_R1_K + BATT_ADC_R2_K > 400 przepelni long w battReport()");

// Mediana z kilku odczytów – odporna na pojedyncze piki z instalacji.
int battAdcMedian() {
  analogRead(PIN_BATT_ADC);            // przełącz multiplekser, odrzuć
  delayMicroseconds(200);
  int s[BATT_ADC_SAMPLES];
  for (uint8_t i = 0; i < BATT_ADC_SAMPLES; i++) {
    s[i] = analogRead(PIN_BATT_ADC);
    delayMicroseconds(300);
  }
  for (uint8_t i = 1; i < BATT_ADC_SAMPLES; i++) {   // sortowanie wstawianiem
    int v = s[i]; int8_t j = i - 1;
    while (j >= 0 && s[j] > v) { s[j + 1] = s[j]; j--; }
    s[j + 1] = v;
  }
  return s[BATT_ADC_SAMPLES / 2];
}

void battInit() {}

void battReport() {
  long adc = battAdcMedian();
  long mv  = adc * BATT_ADC_VREF_MV * (BATT_ADC_R1_K + BATT_ADC_R2_K)
             / (1023L * BATT_ADC_R2_K);
  mv = (long)(mv * BATT_ADC_CAL);
  Serial.print(F("BATT:"));
  Serial.println(mv);
}
#endif

#ifdef FEATURE_BATT_INA226
// INA226: magistrala do 36 V mierzona bezpośrednio (bez dzielnika), prąd
// z bocznika w linii MINUS banku (low-side) albo PLUS (high-side) – układ
// mierzy oba warianty. Kierunek: prąd DO banku (ładowanie) ma dać wynik
// dodatni; jeśli wychodzi odwrotnie, zamień przewody IN+/IN- albo ustaw
// BATT_INA_SIGN na -1.
#define BATT_INA_ADDR     0x40     // A0=A1=GND
#define BATT_SHUNT_MOHM   3.75f    // bocznik 20 A / 75 mV = 3,75 mΩ
#define BATT_INA_SIGN     1
#define INA_REG_CONFIG    0x00
#define INA_REG_SHUNT     0x01     // LSB 2,5 µV, ze znakiem
#define INA_REG_BUS       0x02     // LSB 1,25 mV
// AVG=16, VBUSCT=VSHCT=1,1 ms, tryb ciągły shunt+bus → nowy wynik co ~35 ms
#define INA_CONFIG_VALUE  0x4527

bool battInaOk = false;

bool inaWrite(uint8_t reg, uint16_t v) {
  Wire.beginTransmission(BATT_INA_ADDR);
  Wire.write(reg);
  Wire.write((uint8_t)(v >> 8));
  Wire.write((uint8_t)(v & 0xFF));
  return Wire.endTransmission() == 0;
}

bool inaRead(uint8_t reg, uint16_t& v) {
  Wire.beginTransmission(BATT_INA_ADDR);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom((uint8_t)BATT_INA_ADDR, (uint8_t)2) != 2) return false;
  // Dwa osobne odczyty: w wyrażeniu „read() << 8 | read()” kolejność
  // wywołań nie jest w C++ określona — kompilator może zamienić bajty.
  uint8_t hi = Wire.read();
  uint8_t lo = Wire.read();
  v = ((uint16_t)hi << 8) | lo;
  return true;
}

void battInit() {
  Wire.begin();
  // setWireTimeout jest w rdzeniu arduino:avr od 1.8.3 (sketch.yaml: 1.8.6).
  // 3 ms + reset magistrali: zawieszony INA226 nie zatrzyma loop(), a watchdog
  // (2 s) jeszcze w setup() nie działa.
  Wire.setWireTimeout(3000, true);
  battInaOk = inaWrite(INA_REG_CONFIG, INA_CONFIG_VALUE);
  if (!battInaOk) Serial.println(F("BATT: INA226 nie odpowiada"));
}

void battReport() {
  uint16_t rawBus = 0, rawShunt = 0;
  if (!battInaOk) {                         // ponów inicjalizację
    battInaOk = inaWrite(INA_REG_CONFIG, INA_CONFIG_VALUE);
    if (!battInaOk) return;
  }
  if (!inaRead(INA_REG_BUS, rawBus) || !inaRead(INA_REG_SHUNT, rawShunt)) {
    battInaOk = false;
    return;
  }
  long mv = ((long)rawBus * 125L) / 100L;                 // 1,25 mV/LSB
  // µV / mΩ = mA
  long ma = (long)((int16_t)rawShunt * 2.5f / BATT_SHUNT_MOHM) * BATT_INA_SIGN;
  Serial.print(F("BATT:"));
  Serial.print(mv);
  Serial.print(',');
  Serial.println(ma);
}
#endif

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
  pwrInit(pwr, PWR_CLOSED_LOOP, millis());
#endif
#ifdef FEATURE_PWRLED
  pinMode(PIN_PWR_LED, INPUT_PULLUP);
  pwrLedInit(pwrLed, millis());
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

#if defined(FEATURE_BATT_ADC) || defined(FEATURE_BATT_INA226)
  battInit();
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

// PWR: tylko przy zmianie stanu (pełny stan i tak idzie co 2 s).
void pwrReportState() {
  if (pwr.state == pwrReported) return;
  pwrReported = pwr.state;
  Serial.print(F("PWR:"));
  Serial.println(PWR_NAMES[pwr.state]);
}

// Impuls jest NIEBLOKUJĄCY — 5 s w delay() zabiłoby watchdoga (2 s).
void pwrStartPulse(unsigned long ms, const __FlashStringHelper* what) {
  pwrRelay(true);
  pwrPulsing = true;
  pwrPulseUntil = millis() + ms;
  Serial.print(F("PWRACT:"));
  Serial.println(what);
}

#ifdef FEATURE_PWRLED
// Dioda panelu: świeci ciągle = praca, miga = S3, zgaszona = wyłączony.
// Dekoder (zbocza w oknach, z histerezą na wolne miganie) jest w
// power_logic.h, bo tylko tam da się go przetestować na PC.
void pwrObserveLed(unsigned long now) {
  bool lit = digitalRead(PIN_PWR_LED) == (PWR_LED_ACTIVE_LOW ? LOW : HIGH);
  if (pwrLedSample(pwrLed, lit, now)) pwrObserve(pwr, pwrLed.decoded, now);
}
#endif

void handlePwrButton(unsigned long now) {
  // 1. Domknij trwający impuls. Impuls trwa najwyżej 5 s i jest sprawdzany
  //    w każdym obiegu, więc różnica ze znakiem jest tu bezpieczna.
  if (pwrPulsing) {
    if ((long)(now - pwrPulseUntil) >= 0) {
      pwrRelay(false);
      pwrPulsing = false;
      pwrPulseDone(pwr, now);   // cisza, aż maszyna wykona przejście
    }
    return;
  }

#ifdef FEATURE_PWRLED
  pwrObserveLed(now);
#endif

  // 2. Decyzja: potwierdzenie zapłonu, eskalacja, cisza po impulsie —
  //    power_logic.h (testy: make -C arduino sensor_hub-test).
  switch (pwrStep(pwr, now, inIgn.state)) {
    case PWR_ACT_SHORT:
      pwrStartPulse(PWR_PULSE_SHORT_MS, F("SHORT"));
      break;
    case PWR_ACT_LONG:
      pwrStartPulse(PWR_PULSE_LONG_MS, F("LONG"));
      break;
    default:
      break;
  }
  pwrReportState();
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
  Serial.println(PWR_NAMES[pwr.state]);
#endif
#if defined(FEATURE_BATT_ADC) || defined(FEATURE_BATT_INA226)
  battReport();
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
