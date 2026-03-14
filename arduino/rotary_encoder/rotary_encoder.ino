/*
 * BCM v7 — Rotary Encoder + Buttons + SWC + Music Panel + Brightness → USB HID
 *
 * Hardware: Arduino Pro Micro (ATmega32U4)
 *
 * Wiring:
 *   D2 ← Encoder CLK + 10kΩ pull-up to VCC
 *   D3 ← Encoder DT  + 10kΩ pull-up to VCC
 *   D4 ← Encoder SW   (push button, active LOW)
 *   D5 ← HOME button  (active LOW, internal pull-up)
 *   D6 ← BACK button  (active LOW, internal pull-up)
 *   D7 ← MEDIA button (active LOW, internal pull-up)
 *   D8 ← VOL+ button  (active LOW, internal pull-up)
 *   D9 ← VOL- button  (active LOW, internal pull-up)
 *   A0 ← Steering wheel remote decoder (white wire, analog 0-5V)
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
 * SWC decoder box: white → A0, black → GND, red → 12V ACC
 *
 * Music panel buttons send same keycodes as SWC/encoder equivalents:
 *   MUSIC PREV  → MEDIA_PREVIOUS (consumer)
 *   MUSIC NEXT  → MEDIA_NEXT (consumer)
 *   MUSIC VOL+  → MEDIA_VOLUME_UP (consumer)
 *   MUSIC VOL-  → MEDIA_VOLUME_DOWN (consumer)
 *   MUSIC MUTE  → MEDIA_VOLUME_MUTE (consumer)
 *
 * Brightness stalk button → KEY_F9 (brightness cycle)
 * Light sensor → KEY_F10 with serial data (light level 0-1023)
 *
 * Calibration mode: hold HOME + BACK at boot → SWC calibration via serial.
 */

#include <Keyboard.h>
#include <HID-Project.h>
#include <EEPROM.h>

// --- Pin definitions ---
#define ENC_CLK 2
#define ENC_DT  3
#define ENC_SW  4
#define BTN_HOME  5
#define BTN_BACK  6
#define BTN_MEDIA 7
#define BTN_VOLUP 8
#define BTN_VOLDN 9
#define SWC_PIN   A0

// Music panel buttons (near 7" Android Auto screen)
#define MUS_PREV  10
#define MUS_NEXT  14
#define MUS_VOLUP 15
#define MUS_VOLDN 16
#define MUS_MUTE  A3

// Brightness
#define LDR_PIN       A1   // Light sensor analog input
#define STALK_BTN_PIN A2   // Spare stalk button (brightness cycle)

// --- Debounce ---
#define DEBOUNCE_MS 50
#define ENCODER_DEBOUNCE_MS 5
#define SWC_DEBOUNCE_MS 150
#define ADC_TOLERANCE 40
#define LIGHT_REPORT_MS 2000  // Send light level every 2 seconds

// --- SWC button count ---
#define SWC_BUTTON_COUNT 12
#define SWC_IDLE_THRESHOLD 1000

// --- EEPROM layout ---
#define EEPROM_MAGIC_ADDR 0
#define EEPROM_MAGIC_VALUE 0xBC
#define EEPROM_SWC_ADDR 1   // 12 x 2 bytes = 24 bytes

// SWC button indices
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
};

const char* SWC_NAMES[SWC_BUTTON_COUNT] = {
  "VOL+", "VOL-", "UP", "DOWN", "MUTE", "MODE",
  "NEXT", "PREV", "PICKUP", "HANGUP", "VOICE", "SRC"
};

uint16_t swcValues[SWC_BUTTON_COUNT] = {
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

// --- State: SWC ---
int lastSWCButton = -1;
unsigned long lastSWCTime = 0;
bool calibrationMode = false;

// --- State: light sensor ---
unsigned long lastLightReport = 0;

// --- Forward declarations ---
void handleButtonPress(int buttonIndex);
void handleMusicButton(int buttonIndex);
void handleSWCButton(int buttonIndex);
void readEncoder();
void loadSWCCalibration();
void saveSWCCalibration();
void runCalibration();
int readSWCButton();
void reportLightLevel();

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
  pinMode(SWC_PIN, INPUT);
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
}

void loop() {
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

  // --- Handle SWC analog buttons ---
  if ((now - lastSWCTime) > SWC_DEBOUNCE_MS) {
    int btn = readSWCButton();
    if (btn != lastSWCButton) {
      if (btn >= 0) {
        handleSWCButton(btn);
        Serial.print("SWC: ");
        Serial.print(SWC_NAMES[btn]);
        Serial.print(" (ADC=");
        Serial.print(analogRead(SWC_PIN));
        Serial.println(")");
      }
      lastSWCButton = btn;
      lastSWCTime = now;
    }
  }

  // --- Report light level periodically via serial ---
  if ((now - lastLightReport) > LIGHT_REPORT_MS) {
    reportLightLevel();
    lastLightReport = now;
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
  switch (buttonIndex) {
    case SWC_VOLUP:
      Consumer.write(MEDIA_VOLUME_UP);
      break;
    case SWC_VOLDN:
      Consumer.write(MEDIA_VOLUME_DOWN);
      break;
    case SWC_UP:
      Keyboard.press(KEY_UP_ARROW);
      delay(10);
      Keyboard.release(KEY_UP_ARROW);
      break;
    case SWC_DOWN:
      Keyboard.press(KEY_DOWN_ARROW);
      delay(10);
      Keyboard.release(KEY_DOWN_ARROW);
      break;
    case SWC_MUTE:
      Consumer.write(MEDIA_VOLUME_MUTE);
      break;
    case SWC_MODE:
      Keyboard.press(KEY_HOME);
      delay(10);
      Keyboard.release(KEY_HOME);
      break;
    case SWC_NEXT:
      Consumer.write(MEDIA_NEXT);
      break;
    case SWC_PREV:
      Consumer.write(MEDIA_PREVIOUS);
      break;
    case SWC_PICKUP:
      Keyboard.press(KEY_F5);
      delay(10);
      Keyboard.release(KEY_F5);
      break;
    case SWC_HANGUP:
      Keyboard.press(KEY_F6);
      delay(10);
      Keyboard.release(KEY_F6);
      break;
    case SWC_VOICE:
      Keyboard.press(KEY_F7);
      delay(10);
      Keyboard.release(KEY_F7);
      break;
    case SWC_SRC:
      Keyboard.press(KEY_F8);
      delay(10);
      Keyboard.release(KEY_F8);
      break;
  }
}

int readSWCButton() {
  long sum = 0;
  for (int i = 0; i < 4; i++) {
    sum += analogRead(SWC_PIN);
    delayMicroseconds(100);
  }
  int adc = sum / 4;

  if (adc > SWC_IDLE_THRESHOLD) {
    return -1;
  }

  int bestMatch = -1;
  int bestDiff = ADC_TOLERANCE + 1;

  for (int i = 0; i < SWC_BUTTON_COUNT; i++) {
    int diff = abs(adc - (int)swcValues[i]);
    if (diff < bestDiff) {
      bestDiff = diff;
      bestMatch = i;
    }
  }

  if (bestDiff <= ADC_TOLERANCE) {
    return bestMatch;
  }

  return -1;
}

void reportLightLevel() {
  // Read light sensor (LDR), average 4 samples
  long sum = 0;
  for (int i = 0; i < 4; i++) {
    sum += analogRead(LDR_PIN);
    delayMicroseconds(200);
  }
  int lightLevel = sum / 4;

  // Report via serial protocol: "LIGHT:XXX"
  // BCM Python code parses this from Arduino serial port
  Serial.print("LIGHT:");
  Serial.println(lightLevel);
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

void runCalibration() {
  Serial.println();
  Serial.println("=== SWC CALIBRATION MODE ===");
  Serial.println("Press each steering wheel button when prompted.");
  Serial.println("Release all buttons between presses.");
  Serial.println();

  for (int i = 0; i < SWC_BUTTON_COUNT; i++) {
    Serial.print("Press: ");
    Serial.print(SWC_NAMES[i]);
    Serial.println(" ...");

    while (analogRead(SWC_PIN) < SWC_IDLE_THRESHOLD) {
      delay(50);
    }
    delay(300);

    int adc = 0;
    while (true) {
      long s = 0;
      for (int j = 0; j < 8; j++) {
        s += analogRead(SWC_PIN);
        delay(5);
      }
      adc = s / 8;
      if (adc < SWC_IDLE_THRESHOLD) {
        break;
      }
      delay(20);
    }

    swcValues[i] = adc;
    Serial.print("  -> ADC = ");
    Serial.println(adc);
    delay(300);
  }

  Serial.println();
  Serial.println("Calibration results:");
  for (int i = 0; i < SWC_BUTTON_COUNT; i++) {
    Serial.print("  ");
    Serial.print(SWC_NAMES[i]);
    Serial.print(": ");
    Serial.println(swcValues[i]);

    for (int j = i + 1; j < SWC_BUTTON_COUNT; j++) {
      if (abs((int)swcValues[i] - (int)swcValues[j]) < ADC_TOLERANCE) {
        Serial.print("  WARNING: ");
        Serial.print(SWC_NAMES[i]);
        Serial.print(" and ");
        Serial.print(SWC_NAMES[j]);
        Serial.println(" are too close! Re-calibrate.");
      }
    }
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
