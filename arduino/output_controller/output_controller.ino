/*
 * BCM v8.5 — Output Controller (Arduino Nano, ATmega328P)
 *
 * Receives JSON commands over USB-serial from the M910q headunit and drives
 * the vehicle output devices: relays, lights, horn, wipers, and the two
 * LCD backlight PWM lines.
 *
 * USB: CH340 USB-UART bridge → /dev/ttyUSB0 on the host
 * Baud: 9600
 *
 * --- Pin map (revised v8.5 — adds backlight PWM on D9/D10) ---
 *
 *   Relays / digital outputs (active-LOW for opto-isolated relay modules):
 *     D2  Lock          (pulse 200 ms)
 *     D3  Unlock        (pulse 200 ms)
 *     D4  Trunk         (pulse 200 ms)
 *     D5  Window up     (hold while active)
 *     D6  Window down   (hold while active)
 *     D7  Headlights    (on/off + optional auto-off timeout)
 *     D8  Left blinker  (toggle on/off)
 *     D11 Horn          (hold while active)
 *     A0  Right blinker (toggle on/off)    ← relocated from D9 (freed for PWM)
 *     A1  Wipers        (pulse, configurable duration) ← relocated from D10
 *
 *   PWM outputs (display backlight, drives M_PWM gate on Waveshare 7" LCD):
 *     D9  Backlight LARGE (7" main display)     — Timer1, ~490 Hz PWM
 *     D10 Backlight SMALL (4.3" dashboard)      — Timer1, ~490 Hz PWM
 *
 *   Optional inputs:
 *     D12 RF receiver data (RXB6 433 MHz)       — disabled by default,
 *                                                 see ENABLE_RF below
 *
 *   Status LED:
 *     D13 Built-in LED — heartbeat + command-received flash
 *
 * --- JSON command protocol (one object per line, terminated by '\n') ---
 *
 *   {"cmd":"lock"}                                  D2 pulse 200 ms
 *   {"cmd":"unlock"}                                D3 pulse 200 ms
 *   {"cmd":"trunk"}                                 D4 pulse 200 ms
 *   {"cmd":"window","dir":"up","state":1}           D5 hold while state=1
 *   {"cmd":"window","dir":"down","state":1}         D6 hold while state=1
 *   {"cmd":"lights","state":1,"timeout":60}         D7 on, auto-off in N s
 *   {"cmd":"lights","state":0}                      D7 off
 *   {"cmd":"blinker","side":"left","state":1}       D8 on/off
 *   {"cmd":"blinker","side":"right","state":1}      A0 on/off
 *   {"cmd":"horn","state":1}                        D11 hold while state=1
 *   {"cmd":"wipers","duration":5}                   A1 active for 5 s
 *   {"cmd":"blink","count":2}                       D8+A0 alternating blinks
 *   {"cmd":"backlight","display":"large","brightness":80}
 *                                                   D9 PWM duty (0..100 %)
 *   {"cmd":"backlight","display":"small","brightness":40}
 *                                                   D10 PWM duty (0..100 %)
 *   {"cmd":"learn"}                                 Enter 10 s RF learn mode
 *   {"cmd":"ping"}                                  → {"event":"pong"}
 *
 * --- JSON events emitted back to host ---
 *
 *   {"event":"locked"}            after lock pulse
 *   {"event":"unlocked"}          after unlock pulse
 *   {"event":"trunk"}             after trunk pulse
 *   {"event":"rf_learned","code":12345678}
 *   {"event":"rf_received","code":12345678}
 *   {"event":"pong"}              health-check reply
 *   {"event":"error","msg":"..."} unrecognised command or parse error
 *
 * --- Libraries required (install via Arduino IDE → Library Manager) ---
 *
 *   ArduinoJson  by Benoit Blanchon  (v7.x)
 *   RCSwitch     by sui77            (only if ENABLE_RF = 1)
 *
 * See docs/ARDUINO_SETUP_GUIDE.md for the step-by-step beginner manual.
 */

#include <ArduinoJson.h>

// --- Feature toggles ---------------------------------------------------------
#define ENABLE_RF 0   // 1 → enable 433 MHz keyfob receiver on D12
                      // requires RCSwitch library and a wired RXB6 module.
                      // Disabled by default for the first beginner build.

#if ENABLE_RF
  #include <RCSwitch.h>
  RCSwitch rfReceiver = RCSwitch();
  bool rfLearnMode = false;
  unsigned long rfLearnUntil = 0;
#endif

// --- Pin definitions ---------------------------------------------------------
#define PIN_LOCK         2
#define PIN_UNLOCK       3
#define PIN_TRUNK        4
#define PIN_WINDOW_UP    5
#define PIN_WINDOW_DOWN  6
#define PIN_HEADLIGHTS   7
#define PIN_BLINKER_L    8
#define PIN_BACKLIGHT_L  9    // 7" main display PWM
#define PIN_BACKLIGHT_S  10   // 4.3" small dashboard PWM
#define PIN_HORN         11
#define PIN_RF_RX        12
#define PIN_LED          13
#define PIN_BLINKER_R    A0   // relocated from D9
#define PIN_WIPERS       A1   // relocated from D10

// --- Behaviour constants -----------------------------------------------------
#define PULSE_MS         200      // lock / unlock / trunk pulse length
#define BLINK_INTERVAL   400      // ms between blink toggles
#define DEFAULT_LIGHTS_TIMEOUT 0  // 0 = no auto-off

// Relay polarity: most cheap Chinese opto-isolated modules are ACTIVE-LOW
// (the relay closes when the input is pulled to GND). Set RELAY_ACTIVE to LOW
// for those, or HIGH if your module is the rarer active-high variant.
#define RELAY_ACTIVE   LOW
#define RELAY_INACTIVE HIGH

// --- State -------------------------------------------------------------------
// Non-blocking pulse timers (millis at which pin should return to INACTIVE)
unsigned long lockOffAt    = 0;
unsigned long unlockOffAt  = 0;
unsigned long trunkOffAt   = 0;
unsigned long wipersOffAt  = 0;
unsigned long lightsOffAt  = 0;   // 0 = lights are off or have no timeout

bool blinkerLeftOn  = false;
bool blinkerRightOn = false;
unsigned long lastBlinkToggle = 0;
bool blinkerLeftPhase  = false;
bool blinkerRightPhase = false;

// Heartbeat LED
unsigned long lastHeartbeat = 0;
bool ledState = false;

// Serial line buffer
char lineBuf[160];
uint8_t lineLen = 0;

// Backlight current duty (0..100 %), reported back on demand
uint8_t blDutyLarge = 80;
uint8_t blDutySmall = 80;

// --- Forward declarations ----------------------------------------------------
void handleCommand(const JsonDocument& doc);
void emitEvent(const char* name);
void emitErrorMsg(const char* msg);
void pulseRelay(int pin, unsigned long& offAt);
void setRelay(int pin, bool active);
void setBacklight(const char* display, int brightness);

// =============================================================================
void setup() {
  // Outputs — all relays start INACTIVE
  pinMode(PIN_LOCK,        OUTPUT); digitalWrite(PIN_LOCK,        RELAY_INACTIVE);
  pinMode(PIN_UNLOCK,      OUTPUT); digitalWrite(PIN_UNLOCK,      RELAY_INACTIVE);
  pinMode(PIN_TRUNK,       OUTPUT); digitalWrite(PIN_TRUNK,       RELAY_INACTIVE);
  pinMode(PIN_WINDOW_UP,   OUTPUT); digitalWrite(PIN_WINDOW_UP,   RELAY_INACTIVE);
  pinMode(PIN_WINDOW_DOWN, OUTPUT); digitalWrite(PIN_WINDOW_DOWN, RELAY_INACTIVE);
  pinMode(PIN_HEADLIGHTS,  OUTPUT); digitalWrite(PIN_HEADLIGHTS,  RELAY_INACTIVE);
  pinMode(PIN_BLINKER_L,   OUTPUT); digitalWrite(PIN_BLINKER_L,   RELAY_INACTIVE);
  pinMode(PIN_BLINKER_R,   OUTPUT); digitalWrite(PIN_BLINKER_R,   RELAY_INACTIVE);
  pinMode(PIN_HORN,        OUTPUT); digitalWrite(PIN_HORN,        RELAY_INACTIVE);
  pinMode(PIN_WIPERS,      OUTPUT); digitalWrite(PIN_WIPERS,      RELAY_INACTIVE);

  // Backlight PWM — start at 80 % so a freshly-flashed Nano lights the screens
  pinMode(PIN_BACKLIGHT_L, OUTPUT);
  pinMode(PIN_BACKLIGHT_S, OUTPUT);
  analogWrite(PIN_BACKLIGHT_L, (blDutyLarge * 255L) / 100);
  analogWrite(PIN_BACKLIGHT_S, (blDutySmall * 255L) / 100);

  pinMode(PIN_LED, OUTPUT);

#if ENABLE_RF
  rfReceiver.enableReceive(digitalPinToInterrupt(PIN_RF_RX));
#endif

  Serial.begin(9600);
  // Give the CH340 host driver a moment before printing the banner
  delay(200);
  Serial.println(F("{\"event\":\"ready\",\"fw\":\"bcm-output-v8.5\"}"));
}

// =============================================================================
void loop() {
  unsigned long now = millis();

  // -------- 1. Read incoming serial line-by-line --------
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      if (lineLen > 0) {
        lineBuf[lineLen] = '\0';
        JsonDocument doc;
        DeserializationError err = deserializeJson(doc, lineBuf);
        if (err) {
          emitErrorMsg(err.c_str());
        } else {
          digitalWrite(PIN_LED, HIGH);   // brief activity flash
          handleCommand(doc);
        }
        lineLen = 0;
      }
    } else if (lineLen < sizeof(lineBuf) - 1) {
      lineBuf[lineLen++] = c;
    } else {
      // overflow — discard buffer
      lineLen = 0;
      emitErrorMsg("line too long");
    }
  }

  // -------- 2. Service non-blocking timed outputs --------
  if (lockOffAt   && now >= lockOffAt)   { setRelay(PIN_LOCK,   false); lockOffAt   = 0; emitEvent("locked");   }
  if (unlockOffAt && now >= unlockOffAt) { setRelay(PIN_UNLOCK, false); unlockOffAt = 0; emitEvent("unlocked"); }
  if (trunkOffAt  && now >= trunkOffAt)  { setRelay(PIN_TRUNK,  false); trunkOffAt  = 0; emitEvent("trunk");    }
  if (wipersOffAt && now >= wipersOffAt) { setRelay(PIN_WIPERS, false); wipersOffAt = 0; }
  if (lightsOffAt && now >= lightsOffAt) { setRelay(PIN_HEADLIGHTS, false); lightsOffAt = 0; }

  // -------- 3. Blinker toggling --------
  if ((blinkerLeftOn || blinkerRightOn) && (now - lastBlinkToggle) >= BLINK_INTERVAL) {
    lastBlinkToggle = now;
    if (blinkerLeftOn)  { blinkerLeftPhase  = !blinkerLeftPhase;  setRelay(PIN_BLINKER_L, blinkerLeftPhase);  }
    if (blinkerRightOn) { blinkerRightPhase = !blinkerRightPhase; setRelay(PIN_BLINKER_R, blinkerRightPhase); }
  }

  // -------- 4. RF receiver poll (optional) --------
#if ENABLE_RF
  if (rfReceiver.available()) {
    unsigned long code = rfReceiver.getReceivedValue();
    rfReceiver.resetAvailable();
    if (code != 0) {
      if (rfLearnMode && now < rfLearnUntil) {
        Serial.print(F("{\"event\":\"rf_learned\",\"code\":"));
        Serial.print(code); Serial.println(F("}"));
        rfLearnMode = false;
      } else {
        Serial.print(F("{\"event\":\"rf_received\",\"code\":"));
        Serial.print(code); Serial.println(F("}"));
      }
    }
  }
  if (rfLearnMode && now > rfLearnUntil) {
    rfLearnMode = false;
    emitEvent("rf_learn_timeout");
  }
#endif

  // -------- 5. Activity LED off / heartbeat --------
  // The brief flash on command receipt is undone here on the next loop pass.
  // Slow 1 Hz heartbeat blink so you can see the Nano is alive.
  if ((now - lastHeartbeat) >= 1000) {
    lastHeartbeat = now;
    ledState = !ledState;
    digitalWrite(PIN_LED, ledState ? HIGH : LOW);
  }
}

// =============================================================================
// Command dispatch
// =============================================================================
void handleCommand(const JsonDocument& doc) {
  const char* cmd = doc["cmd"] | "";

  if (!strcmp(cmd, "lock")) {
    pulseRelay(PIN_LOCK, lockOffAt);

  } else if (!strcmp(cmd, "unlock")) {
    pulseRelay(PIN_UNLOCK, unlockOffAt);

  } else if (!strcmp(cmd, "trunk")) {
    pulseRelay(PIN_TRUNK, trunkOffAt);

  } else if (!strcmp(cmd, "window")) {
    const char* dir = doc["dir"] | "";
    int state = doc["state"] | 0;
    int pin = !strcmp(dir, "up") ? PIN_WINDOW_UP : PIN_WINDOW_DOWN;
    setRelay(pin, state ? true : false);

  } else if (!strcmp(cmd, "lights")) {
    int state   = doc["state"]   | 0;
    long tmo    = doc["timeout"] | (long)DEFAULT_LIGHTS_TIMEOUT;
    setRelay(PIN_HEADLIGHTS, state ? true : false);
    lightsOffAt = (state && tmo > 0) ? millis() + (unsigned long)tmo * 1000UL : 0;

  } else if (!strcmp(cmd, "blinker")) {
    const char* side = doc["side"] | "";
    int state = doc["state"] | 0;
    if (!strcmp(side, "left")) {
      blinkerLeftOn = state ? true : false;
      if (!blinkerLeftOn) { blinkerLeftPhase = false; setRelay(PIN_BLINKER_L, false); }
    } else if (!strcmp(side, "right")) {
      blinkerRightOn = state ? true : false;
      if (!blinkerRightOn) { blinkerRightPhase = false; setRelay(PIN_BLINKER_R, false); }
    }

  } else if (!strcmp(cmd, "horn")) {
    int state = doc["state"] | 0;
    setRelay(PIN_HORN, state ? true : false);

  } else if (!strcmp(cmd, "wipers")) {
    long dur = doc["duration"] | 5L;
    setRelay(PIN_WIPERS, true);
    wipersOffAt = millis() + (unsigned long)dur * 1000UL;

  } else if (!strcmp(cmd, "blink")) {
    // Acknowledgement flash on both blinker outputs (e.g. after lock).
    int count = doc["count"] | 2;
    for (int i = 0; i < count; i++) {
      setRelay(PIN_BLINKER_L, true); setRelay(PIN_BLINKER_R, true);
      delay(150);
      setRelay(PIN_BLINKER_L, false); setRelay(PIN_BLINKER_R, false);
      delay(150);
    }

  } else if (!strcmp(cmd, "backlight")) {
    const char* display = doc["display"] | "large";
    int brightness = doc["brightness"] | -1;
    if (brightness >= 0) setBacklight(display, brightness);

  } else if (!strcmp(cmd, "learn")) {
#if ENABLE_RF
    rfLearnMode = true;
    rfLearnUntil = millis() + 10000UL;
    emitEvent("rf_learn_start");
#else
    emitErrorMsg("RF disabled (set ENABLE_RF=1 and rebuild)");
#endif

  } else if (!strcmp(cmd, "ping")) {
    emitEvent("pong");

  } else {
    emitErrorMsg("unknown cmd");
  }
}

// =============================================================================
void pulseRelay(int pin, unsigned long& offAt) {
  setRelay(pin, true);
  offAt = millis() + PULSE_MS;
}

void setRelay(int pin, bool active) {
  digitalWrite(pin, active ? RELAY_ACTIVE : RELAY_INACTIVE);
}

void setBacklight(const char* display, int brightness) {
  if (brightness < 0)   brightness = 0;
  if (brightness > 100) brightness = 100;
  int duty = (brightness * 255L) / 100;
  if (!strcmp(display, "large")) {
    blDutyLarge = brightness;
    analogWrite(PIN_BACKLIGHT_L, duty);
  } else if (!strcmp(display, "small")) {
    blDutySmall = brightness;
    analogWrite(PIN_BACKLIGHT_S, duty);
  } else if (!strcmp(display, "both") || !strcmp(display, "all")) {
    blDutyLarge = blDutySmall = brightness;
    analogWrite(PIN_BACKLIGHT_L, duty);
    analogWrite(PIN_BACKLIGHT_S, duty);
  } else {
    emitErrorMsg("unknown display");
  }
}

void emitEvent(const char* name) {
  Serial.print(F("{\"event\":\""));
  Serial.print(name);
  Serial.println(F("\"}"));
}

void emitErrorMsg(const char* msg) {
  Serial.print(F("{\"event\":\"error\",\"msg\":\""));
  Serial.print(msg);
  Serial.println(F("\"}"));
}
