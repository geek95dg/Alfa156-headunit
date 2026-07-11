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
 * Calibration mode: hold HOME + BACK at boot → SWC calibration via serial.
 * Watchdog: 2 s (enabled after the calibration window).
 */

#include <avr/wdt.h>
// UWAGA: nie dołączać <Keyboard.h> — HID-Project dostarcza własny obiekt
// Keyboard (ImprovedKeyboard) i definiuje KEY_* jako enum; makra KEY_*
// ze stockowego Keyboard.h psują kompilację (konflikt makro vs enum).
#include <HID-Project.h>
#include <EEPROM.h>

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
#define SWC_DEBOUNCE_MS 150
#define ADC_TOLERANCE 40
#define LIGHT_REPORT_MS 2000  // Send light level every 2 seconds

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

// --- State: encoder ---
volatile int encoderPos = 0;
int lastEncoderPos = 0;
int lastCLK = HIGH;

// --- State: main buttons (6: enc_sw, home, back, media, vol+, vol-) ---
#define MAIN_BTN_COUNT 6
unsigned long lastButtonTime[MAIN_BTN_COUNT] = {0};
bool lastButtonState[MAIN_BTN_COUNT] = {HIGH, HIGH, HIGH, HIGH, HIGH, HIGH};
const int buttonPins[MAIN_BTN_COUNT] = {ENC_SW, BTN_HOME, BTN_BACK, BTN_MEDIA, BTN_VOLUP, BTN_VOLDN};

// --- State: music panel buttons (5) ---
#define MUSIC_BTN_COUNT 5
unsigned long lastMusicTime[MUSIC_BTN_COUNT] = {0};
bool lastMusicState[MUSIC_BTN_COUNT] = {HIGH, HIGH, HIGH, HIGH, HIGH};
const int musicPins[MUSIC_BTN_COUNT] = {MUS_PREV, MUS_NEXT, MUS_VOLUP, MUS_VOLDN, MUS_MUTE};

// --- State: stalk brightness button ---
unsigned long lastStalkTime = 0;
bool lastStalkState = HIGH;

// --- State: SWC (per-pod) ---
int lastSWCButton1 = -1;
int lastSWCButton2 = -1;
unsigned long lastSWCTime1 = 0;
unsigned long lastSWCTime2 = 0;
bool calibrationMode = false;

// --- State: light sensor ---
unsigned long lastLightReport = 0;
unsigned long lastFuelReport = 0;

// --- Forward declarations ---
void handleButtonPress(int buttonIndex);
void handleMusicButton(int buttonIndex);
void handleSWCButton(int buttonIndex);
void readEncoder();
void loadSWCCalibration();
void saveSWCCalibration();
void runCalibration();
int readSWCButton(int pin, int offset);
void reportLightLevel();
void reportFuelLevel();

void setup() {
  // Encoder pins (external pull-ups)
  pinMode(ENC_CLK, INPUT);
  pinMode(ENC_DT, INPUT);

  // Main button pins (internal pull-ups)
  pinMode(ENC_SW, INPUT_PULLUP);
  pinMode(BTN_HOME, INPUT_PULLUP);
  pinMode(BTN_BACK, INPUT_PULLUP);
  pinMode(BTN_MEDIA, INPUT_PULLUP);
  pinMode(BTN_VOLUP, INPUT_PULLUP);
  pinMode(BTN_VOLDN, INPUT_PULLUP);

  // Music panel pins (internal pull-ups)
  pinMode(MUS_PREV, INPUT_PULLUP);
  pinMode(MUS_NEXT, INPUT_PULLUP);
  pinMode(MUS_VOLUP, INPUT_PULLUP);
  pinMode(MUS_VOLDN, INPUT_PULLUP);
  pinMode(MUS_MUTE, INPUT_PULLUP);

  // Brightness stalk button (internal pull-up)
  pinMode(STALK_BTN_PIN, INPUT_PULLUP);

  // Analog inputs (no pull-up needed)
  pinMode(SWC_PIN1, INPUT);
  pinMode(SWC_PIN2, INPUT);
  pinMode(LDR_PIN, INPUT);

  // Encoder interrupt
  attachInterrupt(digitalPinToInterrupt(ENC_CLK), readEncoder, CHANGE);

  // Start USB HID
  Keyboard.begin();
  Consumer.begin();

  // Start serial for calibration/debug + light sensor data
  Serial.begin(115200);

  // Load SWC calibration from EEPROM
  loadSWCCalibration();

  // Check calibration mode: hold HOME + BACK at boot
  delay(100);
  if (digitalRead(BTN_HOME) == LOW && digitalRead(BTN_BACK) == LOW) {
    calibrationMode = true;
    runCalibration();
    calibrationMode = false;
  }

  Serial.println("BCM v7 Input Controller ready (encoder + buttons + SWC + music + brightness)");

  // Watchdog ON dopiero po (ewentualnej) kalibracji — kalibracja
  // czeka na przyciski użytkownika dłużej niż 2 s.
  wdt_enable(WDTO_2S);
}

void loop() {
  wdt_reset();
  unsigned long now = millis();

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

  // --- Handle main buttons (debounced) ---
  for (int i = 0; i < MAIN_BTN_COUNT; i++) {
    bool currentState = digitalRead(buttonPins[i]);

    if (currentState != lastButtonState[i] && (now - lastButtonTime[i]) > DEBOUNCE_MS) {
      lastButtonTime[i] = now;
      lastButtonState[i] = currentState;

      if (currentState == LOW) {
        handleButtonPress(i);
      }
    }
  }

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
        Serial.println("STALK: Brightness cycle");
      }
    }
  }

  // --- Handle SWC analog buttons (Pod 1 on A0, Pod 2 on A6) ---
  if ((now - lastSWCTime1) > SWC_DEBOUNCE_MS) {
    int btn = readSWCButton(SWC_PIN1, 0);
    if (btn != lastSWCButton1) {
      if (btn >= 0) {
        handleSWCButton(btn);
        Serial.print("SWC1: ");
        Serial.print(SWC_NAMES[btn]);
        Serial.print(" (ADC=");
        Serial.print(analogRead(SWC_PIN1));
        Serial.println(")");
      }
      lastSWCButton1 = btn;
      lastSWCTime1 = now;
    }
  }
  if ((now - lastSWCTime2) > SWC_DEBOUNCE_MS) {
    int btn = readSWCButton(SWC_PIN2, SWC_BUTTONS_PER_POD);
    if (btn != lastSWCButton2) {
      if (btn >= 0) {
        handleSWCButton(btn);
        Serial.print("SWC2: ");
        Serial.print(SWC_NAMES[btn]);
        Serial.print(" (ADC=");
        Serial.print(analogRead(SWC_PIN2));
        Serial.println(")");
      }
      lastSWCButton2 = btn;
      lastSWCTime2 = now;
    }
  }

  // --- Report light level periodically via serial ---
  if ((now - lastLightReport) > LIGHT_REPORT_MS) {
    reportLightLevel();
    lastLightReport = now;
  }

  // --- Report fuel sender ADC periodically via serial ---
  if ((now - lastFuelReport) > FUEL_REPORT_MS) {
    reportFuelLevel();
    lastFuelReport = now;
  }

  delay(1);
}

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

void handleMusicButton(int buttonIndex) {
  switch (buttonIndex) {
    case 0:  // MUSIC PREV
      Consumer.write(MEDIA_PREVIOUS);
      Serial.println("MUSIC: PREV");
      break;
    case 1:  // MUSIC NEXT
      Consumer.write(MEDIA_NEXT);
      Serial.println("MUSIC: NEXT");
      break;
    case 2:  // MUSIC VOL+
      Consumer.write(MEDIA_VOLUME_UP);
      Serial.println("MUSIC: VOL+");
      break;
    case 3:  // MUSIC VOL-
      Consumer.write(MEDIA_VOLUME_DOWN);
      Serial.println("MUSIC: VOL-");
      break;
    case 4:  // MUSIC MUTE
      Consumer.write(MEDIA_VOLUME_MUTE);
      Serial.println("MUSIC: MUTE");
      break;
  }
}

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

int readSWCButton(int pin, int offset) {
  long sum = 0;
  for (int i = 0; i < 4; i++) {
    sum += analogRead(pin);
    delayMicroseconds(100);
  }
  int adc = sum / 4;

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

void reportLightLevel() {
  long sum = 0;
  for (int i = 0; i < 4; i++) {
    sum += analogRead(LDR_PIN);
    delayMicroseconds(200);
  }
  Serial.print("LIGHT:");
  Serial.println((int)(sum / 4));
}

void reportFuelLevel() {
  long sum = 0;
  for (int i = 0; i < 8; i++) {
    sum += analogRead(FUEL_PIN);
    delay(2);
  }
  Serial.print("FUEL:");
  Serial.println((int)(sum / 8));
}

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

void calibratePod(int pin, int offset, const char* podName) {
  Serial.print("--- Calibrating ");
  Serial.print(podName);
  Serial.println(" ---");

  for (int i = 0; i < SWC_BUTTONS_PER_POD; i++) {
    Serial.print("Press: ");
    Serial.print(SWC_NAMES[offset + i]);
    Serial.println(" ...");

    while (analogRead(pin) < SWC_IDLE_THRESHOLD) {
      delay(50);
    }
    delay(300);

    int adc = 0;
    while (true) {
      long s = 0;
      for (int j = 0; j < 8; j++) {
        s += analogRead(pin);
        delay(5);
      }
      adc = s / 8;
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
  calibratePod(SWC_PIN2, SWC_BUTTONS_PER_POD, "Pod 2 (A6)");

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
