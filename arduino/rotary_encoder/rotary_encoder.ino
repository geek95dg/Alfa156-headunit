/*
 * BCM v7 — Rotary Encoder + Buttons + Steering Wheel Remote → USB HID
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
 * Steering wheel remote decoder box:
 *   White wire  → A0 (analog signal, resistor-ladder output)
 *   Black wire  → GND (chassis ground)
 *   Red wire    → VCC (12V accessory — powers the decoder, NOT connected to Arduino)
 *
 * The decoder box outputs different voltages on the white wire depending
 * on which button is pressed. Each button = unique resistance = unique ADC value.
 *
 * SWC button pods (2x 6-button round pods):
 *   Pod 1: VOL+, VOL-, UP, DOWN, MUTE, MODE (center)
 *   Pod 2: PHONE PICKUP, PHONE HANGUP, PREV, NEXT, VOICE, SRC (center)
 *
 * Output: USB HID keyboard/consumer keycodes
 *   Encoder CW   → KEY_DOWN_ARROW
 *   Encoder CCW  → KEY_UP_ARROW
 *   Encoder SW   → KEY_RETURN (Enter)
 *   HOME         → KEY_HOME
 *   BACK         → KEY_BACKSPACE
 *   MEDIA        → MEDIA_PLAY_PAUSE
 *   VOL+         → Volume Up (consumer)
 *   VOL-         → Volume Down (consumer)
 *   --- SWC buttons (analog) ---
 *   SWC VOL+     → Volume Up (consumer)
 *   SWC VOL-     → Volume Down (consumer)
 *   SWC UP       → KEY_UP_ARROW
 *   SWC DOWN     → KEY_DOWN_ARROW
 *   SWC MUTE     → MEDIA_VOLUME_MUTE
 *   SWC MODE     → KEY_HOME (settings toggle)
 *   SWC NEXT     → MEDIA_NEXT
 *   SWC PREV     → MEDIA_PREVIOUS
 *   SWC PICKUP   → KEY_F5 (phone answer)
 *   SWC HANGUP   → KEY_F6 (phone hangup)
 *   SWC VOICE    → KEY_F7 (voice assistant trigger)
 *   SWC SRC      → KEY_F8 (audio source cycle)
 *
 * Calibration mode:
 *   Hold HOME + BACK at boot → enters calibration mode.
 *   Press each SWC button when prompted via serial.
 *   Stores thresholds in EEPROM.
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

// --- Debounce ---
#define DEBOUNCE_MS 50
#define ENCODER_DEBOUNCE_MS 5
#define SWC_DEBOUNCE_MS 150
#define ADC_TOLERANCE 40

// --- SWC button count ---
#define SWC_BUTTON_COUNT 12
#define SWC_IDLE_THRESHOLD 1000  // ADC > this = no button pressed

// --- EEPROM layout ---
#define EEPROM_MAGIC_ADDR 0
#define EEPROM_MAGIC_VALUE 0xBC
#define EEPROM_SWC_ADDR 1   // 12 x 2 bytes (uint16_t) = 24 bytes

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

// --- Default ADC values (typical resistor-ladder, 10-bit ADC) ---
// These are starting defaults; calibration overwrites them.
// Typical cheap SWC decoders output voltages roughly:
//   0V(0) to ~4.5V(920) spread across buttons
uint16_t swcValues[SWC_BUTTON_COUNT] = {
  75,   // VOL+
  150,  // VOL-
  230,  // UP
  310,  // DOWN
  390,  // MUTE
  470,  // MODE
  540,  // NEXT
  610,  // PREV
  690,  // PICKUP
  760,  // HANGUP
  830,  // VOICE
  900,  // SRC
};

// --- State ---
volatile int encoderPos = 0;
int lastEncoderPos = 0;
int lastCLK = HIGH;

unsigned long lastButtonTime[6] = {0};
bool lastButtonState[6] = {HIGH, HIGH, HIGH, HIGH, HIGH, HIGH};
const int buttonPins[6] = {ENC_SW, BTN_HOME, BTN_BACK, BTN_MEDIA, BTN_VOLUP, BTN_VOLDN};

int lastSWCButton = -1;
unsigned long lastSWCTime = 0;
bool calibrationMode = false;

// --- Forward declarations ---
void handleButtonPress(int buttonIndex);
void handleSWCButton(int buttonIndex);
void readEncoder();
void loadSWCCalibration();
void saveSWCCalibration();
void runCalibration();
int readSWCButton();

void setup() {
  // Encoder pins (external pull-ups)
  pinMode(ENC_CLK, INPUT);
  pinMode(ENC_DT, INPUT);

  // Button pins (internal pull-ups)
  pinMode(ENC_SW, INPUT_PULLUP);
  pinMode(BTN_HOME, INPUT_PULLUP);
  pinMode(BTN_BACK, INPUT_PULLUP);
  pinMode(BTN_MEDIA, INPUT_PULLUP);
  pinMode(BTN_VOLUP, INPUT_PULLUP);
  pinMode(BTN_VOLDN, INPUT_PULLUP);

  // SWC analog input
  pinMode(SWC_PIN, INPUT);

  // Encoder interrupt
  attachInterrupt(digitalPinToInterrupt(ENC_CLK), readEncoder, CHANGE);

  // Start USB HID
  Keyboard.begin();
  Consumer.begin();

  // Start serial for calibration/debug
  Serial.begin(115200);

  // Load calibration from EEPROM
  loadSWCCalibration();

  // Check calibration mode: hold HOME + BACK at boot
  delay(100);
  if (digitalRead(BTN_HOME) == LOW && digitalRead(BTN_BACK) == LOW) {
    calibrationMode = true;
    runCalibration();
    calibrationMode = false;
  }

  Serial.println("BCM v7 Input Controller ready (encoder + buttons + SWC)");
}

void loop() {
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

  // --- Handle physical buttons (debounced) ---
  for (int i = 0; i < 6; i++) {
    bool currentState = digitalRead(buttonPins[i]);
    unsigned long now = millis();

    if (currentState != lastButtonState[i] && (now - lastButtonTime[i]) > DEBOUNCE_MS) {
      lastButtonTime[i] = now;
      lastButtonState[i] = currentState;

      if (currentState == LOW) {  // Button pressed (active LOW)
        handleButtonPress(i);
      }
    }
  }

  // --- Handle SWC analog buttons ---
  unsigned long now = millis();
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

  delay(1);  // Small delay to prevent busy-waiting
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
  // Read ADC, average 4 samples for noise rejection
  long sum = 0;
  for (int i = 0; i < 4; i++) {
    sum += analogRead(SWC_PIN);
    delayMicroseconds(100);
  }
  int adc = sum / 4;

  // No button pressed
  if (adc > SWC_IDLE_THRESHOLD) {
    return -1;
  }

  // Find closest matching button
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

  return -1;  // No match within tolerance
}

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

    // Wait for idle (no button)
    while (analogRead(SWC_PIN) < SWC_IDLE_THRESHOLD) {
      delay(50);
    }
    delay(300);

    // Wait for button press
    int adc = 0;
    while (true) {
      long sum = 0;
      for (int s = 0; s < 8; s++) {
        sum += analogRead(SWC_PIN);
        delay(5);
      }
      adc = sum / 8;
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

  // Sort check: warn if two buttons have overlapping values
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
      encoderPos++;   // CW
    } else {
      encoderPos--;   // CCW
    }
    lastCLK = clkState;
  }
}
