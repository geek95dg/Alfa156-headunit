/*
 * BCM v7 — Rotary Encoder + Buttons → USB HID Keyboard
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
 *
 * Output: USB HID keyboard keycodes
 *   Encoder CW  → KEY_DOWN_ARROW
 *   Encoder CCW → KEY_UP_ARROW
 *   Encoder SW  → KEY_RETURN (Enter)
 *   HOME        → KEY_HOME (0xD2 consumer)
 *   BACK        → KEY_BACKSPACE
 *   MEDIA       → 0xE2 (media select)
 *   VOL+        → Volume Up (consumer control)
 *   VOL-        → Volume Down (consumer control)
 */

#include <Keyboard.h>
#include <HID-Project.h>

// --- Pin definitions ---
#define ENC_CLK 2
#define ENC_DT  3
#define ENC_SW  4
#define BTN_HOME  5
#define BTN_BACK  6
#define BTN_MEDIA 7
#define BTN_VOLUP 8
#define BTN_VOLDN 9

// --- Debounce ---
#define DEBOUNCE_MS 50
#define ENCODER_DEBOUNCE_MS 5

// --- State ---
volatile int encoderPos = 0;
int lastEncoderPos = 0;
int lastCLK = HIGH;

unsigned long lastButtonTime[6] = {0};
bool lastButtonState[6] = {HIGH, HIGH, HIGH, HIGH, HIGH, HIGH};
const int buttonPins[6] = {ENC_SW, BTN_HOME, BTN_BACK, BTN_MEDIA, BTN_VOLUP, BTN_VOLDN};

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

  // Encoder interrupt
  attachInterrupt(digitalPinToInterrupt(ENC_CLK), readEncoder, CHANGE);

  // Start USB HID
  Keyboard.begin();
  Consumer.begin();
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

  // --- Handle buttons (debounced) ---
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
