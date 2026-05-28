/*
 * BCM v8.5 — Always-On Output Controller (Arduino Nano, ATmega328P)
 *
 * Domain A controller. Powered continuously from the 12 V battery buffer
 * (4-6 x SLA 5 Ah in parallel, ~20-30 Ah total). Runs regardless of M910q
 * (BCM) state. Handles the always-on subsystem:
 *
 *   - 4-window remote control via a 2nd 433 MHz keyfob (hold-to-move)
 *   - BLE-proximity-gated trunk release (HM-10 + known tag MAC)
 *   - Backlight PWM for the 7" and 4.3" displays (only relevant when BCM up)
 *
 * The Nano does NOT replace the OEM central lock — the original Alfa 156
 * lock system is left untouched. RF keyfob learning for OEM lock copy is
 * gone; the 433 MHz path now serves only the secondary window remote.
 *
 * --- Pin map ---
 *   D2  433 MHz RXB6 data        (RCSwitch on INT 0)
 *   D3  HM-10 BLE RX  (Nano TX → HM-10 RX, SoftwareSerial TX)
 *   D4  HM-10 BLE TX  (HM-10 TX → Nano RX, SoftwareSerial RX)
 *   D5  Trunk relay              (200 ms pulse on BLE-confirmed button press)
 *   D6  Trunk button input       (internal pull-up, momentary to GND)
 *   D7  Front-Left  Up   relay
 *   D8  Front-Left  Down relay
 *   D9  Backlight LARGE (7")     (Timer1 PWM ~490 Hz, drives display M_PWM)
 *   D10 Backlight SMALL (4.3")   (Timer1 PWM ~490 Hz, drives display M_PWM)
 *   D11 Front-Right Up   relay
 *   D12 Front-Right Down relay
 *   D13 Status LED (on-board)
 *   A0  Rear-Left   Up   relay
 *   A1  Rear-Left   Down relay
 *   A2  Rear-Right  Up   relay
 *   A3  Rear-Right  Down relay
 *   A4  reserved (I2C SDA, future expansion)
 *   A5  reserved (I2C SCL, future expansion)
 *
 * --- JSON command protocol (BCM → Nano, 9600 baud, '\n' terminated) ---
 *   {"cmd":"backlight","display":"large","brightness":80}
 *   {"cmd":"backlight","display":"small","brightness":60}
 *   {"cmd":"backlight","display":"both","brightness":0}     standby/off
 *   {"cmd":"ping"}                                          → {"event":"pong"}
 *   {"cmd":"status"}                                        → full state dump
 *   {"cmd":"learn_window","slot":"FL_UP"}                   capture next RF code
 *                       slot ∈ FL_UP|FL_DOWN|FR_UP|FR_DOWN|
 *                              RL_UP|RL_DOWN|RR_UP|RR_DOWN
 *   {"cmd":"learn_ble"}                                     scan, store strongest
 *   {"cmd":"set_ble_mac","mac":"001122334455"}              explicit set
 *   {"cmd":"set_ble_rssi","threshold":-80}                  trunk-arm threshold
 *   {"cmd":"clear"}                                         wipe EEPROM, factory
 *
 * --- JSON events (Nano → BCM) ---
 *   {"event":"ready","fw":"bcm-domain-a-v8.5"}
 *   {"event":"window","slot":"FL_DOWN"}            remote press start
 *   {"event":"window_release","slot":"FL_DOWN"}    remote button released
 *   {"event":"trunk","rssi":-67}                   BLE-OK, trunk pulse fired
 *   {"event":"trunk_denied","reason":"no_key"}     button pressed, no BLE tag
 *   {"event":"trunk_denied","reason":"weak","rssi":-92}
 *   {"event":"learned","slot":"FL_UP","code":1234567}
 *   {"event":"learn_timeout","slot":"FL_UP"}
 *   {"event":"ble_learned","mac":"001122334455","rssi":-60}
 *   {"event":"rf_unknown","code":9999999}          unrecognised RF code
 *   {"event":"pong"}
 *
 * --- Libraries (Arduino IDE → Library Manager) ---
 *   RCSwitch       by sui77
 *   ArduinoJson    by Benoit Blanchon (v7.x)
 *   SoftwareSerial (bundled with the IDE — no install needed)
 *
 * See docs/ARDUINO_SETUP_GUIDE.md for the full step-by-step manual,
 * including HM-10 setup, window-remote learning, and BLE tag pairing.
 */

#include <ArduinoJson.h>
#include <EEPROM.h>
#include <RCSwitch.h>
#include <SoftwareSerial.h>

// --- Pin definitions ---------------------------------------------------------
#define PIN_RF_RX         2
#define PIN_BLE_TO        3   // Nano TX → HM-10 RXD
#define PIN_BLE_FROM      4   // HM-10 TXD → Nano RX
#define PIN_TRUNK_RELAY   5
#define PIN_TRUNK_BUTTON  6
#define PIN_FL_UP         7
#define PIN_FL_DOWN       8
#define PIN_BACKLIGHT_L   9   // 7" main display PWM
#define PIN_BACKLIGHT_S   10  // 4.3" small display PWM
#define PIN_FR_UP         11
#define PIN_FR_DOWN       12
#define PIN_LED           13
#define PIN_RL_UP         A0
#define PIN_RL_DOWN       A1
#define PIN_RR_UP         A2
#define PIN_RR_DOWN       A3

// Window slots — order matters: indexes are used in EEPROM layout
enum WindowSlot {
  FL_UP = 0, FL_DOWN, FR_UP, FR_DOWN,
  RL_UP,     RL_DOWN, RR_UP, RR_DOWN,
  WIN_COUNT
};

const char* SLOT_NAMES[WIN_COUNT] = {
  "FL_UP", "FL_DOWN", "FR_UP", "FR_DOWN",
  "RL_UP", "RL_DOWN", "RR_UP", "RR_DOWN",
};

const int SLOT_PINS[WIN_COUNT] = {
  PIN_FL_UP, PIN_FL_DOWN, PIN_FR_UP, PIN_FR_DOWN,
  PIN_RL_UP, PIN_RL_DOWN, PIN_RR_UP, PIN_RR_DOWN,
};

// --- Behaviour constants -----------------------------------------------------
#define TRUNK_PULSE_MS        200
#define WINDOW_RELEASE_MS     250    // RF re-trigger window; no code for N ms → release
#define WINDOW_MAX_HOLD_MS    8000   // safety cutoff: 8 s max continuous travel
#define BLE_SCAN_MS           2500   // HM-10 discovery scan window
#define BLE_DEFAULT_THRESHOLD -80    // RSSI threshold (dBm)
#define LEARN_TIMEOUT_MS      30000  // window-learn / BLE-learn timeout

// Relay polarity (active-LOW for typical opto-isolated relay modules)
#define RELAY_ACTIVE   LOW
#define RELAY_INACTIVE HIGH

// --- EEPROM layout (32 bytes total) ------------------------------------------
//   addr  0      magic byte (0xB5)
//   addr  1-32   8 × 4-byte RF codes (little-endian) for each WindowSlot
//   addr 33-38   6 bytes BLE tag MAC
//   addr 39      1 byte int8_t RSSI threshold
#define EEPROM_MAGIC_ADDR  0
#define EEPROM_MAGIC_VALUE 0xB5
#define EEPROM_CODES_ADDR  1
#define EEPROM_BLE_MAC     33
#define EEPROM_BLE_RSSI    39

// --- State -------------------------------------------------------------------
unsigned long winCodes[WIN_COUNT] = {0};
uint8_t bleMac[6] = {0};
int8_t  bleRssiThreshold = BLE_DEFAULT_THRESHOLD;
bool    bleMacValid = false;

RCSwitch rfRx = RCSwitch();
SoftwareSerial ble(PIN_BLE_FROM, PIN_BLE_TO);  // RX, TX

// Window control state
int activeSlot = -1;                  // currently-engaged slot (-1 = none)
unsigned long activeSlotStartedAt = 0;
unsigned long activeSlotLastSeen = 0;

// Trunk relay state
unsigned long trunkOffAt = 0;

// Trunk button debounce
bool lastTrunkButton = HIGH;
unsigned long lastTrunkChange = 0;

// Heartbeat LED
unsigned long lastHeartbeat = 0;
bool ledState = false;

// Learn modes
int  learnSlot = -1;           // -1 = not in window-learn mode
unsigned long learnUntil = 0;
bool learnBleActive = false;
uint8_t bestBleMac[6] = {0};
int8_t  bestBleRssi = -127;

// Serial input buffer
char lineBuf[160];
uint8_t lineLen = 0;

// --- Forward declarations ----------------------------------------------------
void handleCommand(const JsonDocument& doc);
void emitEvent(const char* name);
void emitErrorMsg(const char* msg);
void emitWindowEvent(const char* type, int slot);
void setRelay(int pin, bool active);
void setBacklight(const char* display, int brightness);
void engageSlot(int slot);
void releaseSlot();
int  findSlotForCode(unsigned long code);
void enterLearnWindow(const char* slotName);
void enterLearnBle();
void handleTrunkButton(unsigned long now);
bool bleScanAndGate(int8_t* outRssi);
void hmCommand(const char* cmd);
void loadEeprom();
void saveCode(int slot, unsigned long code);
void saveBleMac(const uint8_t* mac);
void saveBleRssi(int8_t r);
void clearEeprom();
int  slotByName(const char* name);

// =============================================================================
void setup() {
  // Relay outputs — all start INACTIVE
  const int relays[] = {
    PIN_FL_UP, PIN_FL_DOWN, PIN_FR_UP, PIN_FR_DOWN,
    PIN_RL_UP, PIN_RL_DOWN, PIN_RR_UP, PIN_RR_DOWN,
    PIN_TRUNK_RELAY,
  };
  for (uint8_t i = 0; i < sizeof(relays) / sizeof(relays[0]); i++) {
    pinMode(relays[i], OUTPUT);
    digitalWrite(relays[i], RELAY_INACTIVE);
  }

  // Inputs
  pinMode(PIN_TRUNK_BUTTON, INPUT_PULLUP);

  // Backlight PWM — start at 0 (BCM will command duty as needed)
  pinMode(PIN_BACKLIGHT_L, OUTPUT);
  pinMode(PIN_BACKLIGHT_S, OUTPUT);
  analogWrite(PIN_BACKLIGHT_L, 0);
  analogWrite(PIN_BACKLIGHT_S, 0);

  pinMode(PIN_LED, OUTPUT);

  // RF receiver (window remote) — RCSwitch interrupt-driven
  rfRx.enableReceive(digitalPinToInterrupt(PIN_RF_RX));

  // HM-10 BLE module on SoftwareSerial @ 9600 baud (HM-10 factory default)
  ble.begin(9600);

  // USB serial to BCM
  Serial.begin(9600);

  loadEeprom();

  delay(200);
  Serial.println(F("{\"event\":\"ready\",\"fw\":\"bcm-domain-a-v8.5\"}"));
}

// =============================================================================
void loop() {
  unsigned long now = millis();

  // -------- 1. USB serial — read JSON commands --------
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      if (lineLen > 0) {
        lineBuf[lineLen] = '\0';
        JsonDocument doc;
        DeserializationError err = deserializeJson(doc, lineBuf);
        if (err) emitErrorMsg(err.c_str());
        else     handleCommand(doc);
        lineLen = 0;
      }
    } else if (lineLen < sizeof(lineBuf) - 1) {
      lineBuf[lineLen++] = c;
    } else {
      lineLen = 0;
      emitErrorMsg("line too long");
    }
  }

  // -------- 2. 433 MHz receiver — window remote --------
  if (rfRx.available()) {
    unsigned long code = rfRx.getReceivedValue();
    rfRx.resetAvailable();

    if (code != 0) {
      if (learnSlot >= 0 && now < learnUntil) {
        // Learning mode — accept this code for the active slot
        saveCode(learnSlot, code);
        Serial.print(F("{\"event\":\"learned\",\"slot\":\""));
        Serial.print(SLOT_NAMES[learnSlot]);
        Serial.print(F("\",\"code\":"));
        Serial.print(code);
        Serial.println(F("}"));
        learnSlot = -1;
      } else {
        int slot = findSlotForCode(code);
        if (slot >= 0) {
          if (slot != activeSlot) {
            // New press — release whatever was active, engage this one
            if (activeSlot >= 0) releaseSlot();
            engageSlot(slot);
            emitWindowEvent("window", slot);
          }
          activeSlotLastSeen = now;
        } else {
          // Unknown code — could be the user's BLE tag or a stray
          Serial.print(F("{\"event\":\"rf_unknown\",\"code\":"));
          Serial.print(code);
          Serial.println(F("}"));
        }
      }
    }
  }

  // -------- 3. Window auto-release (button released or safety cutoff) --------
  if (activeSlot >= 0) {
    bool released  = (now - activeSlotLastSeen)   >= WINDOW_RELEASE_MS;
    bool safety    = (now - activeSlotStartedAt)  >= WINDOW_MAX_HOLD_MS;
    if (released || safety) {
      emitWindowEvent("window_release", activeSlot);
      releaseSlot();
    }
  }

  // -------- 4. Trunk button --------
  handleTrunkButton(now);
  if (trunkOffAt && now >= trunkOffAt) {
    setRelay(PIN_TRUNK_RELAY, false);
    trunkOffAt = 0;
  }

  // -------- 5. Learn-mode timeouts --------
  if (learnSlot >= 0 && now >= learnUntil) {
    Serial.print(F("{\"event\":\"learn_timeout\",\"slot\":\""));
    Serial.print(SLOT_NAMES[learnSlot]);
    Serial.println(F("\"}"));
    learnSlot = -1;
  }

  // -------- 6. Heartbeat LED (very slow — 0.5 Hz @ 5 % duty to save power) --
  if ((now - lastHeartbeat) >= 2000) {
    lastHeartbeat = now;
    ledState = !ledState;
    digitalWrite(PIN_LED, ledState ? HIGH : LOW);
  } else if (ledState && (now - lastHeartbeat) >= 100) {
    digitalWrite(PIN_LED, LOW);  // 100 ms on, then off until next 2 s mark
  }
}

// =============================================================================
// JSON command dispatch
// =============================================================================
void handleCommand(const JsonDocument& doc) {
  const char* cmd = doc["cmd"] | "";

  if (!strcmp(cmd, "backlight")) {
    const char* display = doc["display"] | "large";
    int brightness = doc["brightness"] | -1;
    if (brightness >= 0) setBacklight(display, brightness);

  } else if (!strcmp(cmd, "ping")) {
    emitEvent("pong");

  } else if (!strcmp(cmd, "status")) {
    JsonDocument out;
    out["event"] = "status";
    out["active_slot"] = (activeSlot >= 0) ? SLOT_NAMES[activeSlot] : "none";
    out["ble_mac_set"] = bleMacValid;
    out["ble_rssi_threshold"] = bleRssiThreshold;
    JsonArray codes = out["codes"].to<JsonArray>();
    for (int i = 0; i < WIN_COUNT; i++) codes.add(winCodes[i]);
    serializeJson(out, Serial);
    Serial.println();

  } else if (!strcmp(cmd, "learn_window")) {
    const char* slotName = doc["slot"] | "";
    enterLearnWindow(slotName);

  } else if (!strcmp(cmd, "learn_ble")) {
    enterLearnBle();

  } else if (!strcmp(cmd, "set_ble_mac")) {
    const char* mac = doc["mac"] | "";
    if (strlen(mac) == 12) {
      uint8_t buf[6];
      for (int i = 0; i < 6; i++) {
        char hex[3] = { mac[i*2], mac[i*2+1], 0 };
        buf[i] = (uint8_t) strtol(hex, nullptr, 16);
      }
      saveBleMac(buf);
      emitEvent("ble_mac_saved");
    } else {
      emitErrorMsg("mac must be 12 hex chars");
    }

  } else if (!strcmp(cmd, "set_ble_rssi")) {
    int t = doc["threshold"] | BLE_DEFAULT_THRESHOLD;
    saveBleRssi((int8_t) t);
    emitEvent("ble_rssi_saved");

  } else if (!strcmp(cmd, "clear")) {
    clearEeprom();
    emitEvent("cleared");

  } else {
    emitErrorMsg("unknown cmd");
  }
}

// =============================================================================
// Helpers — relays and slots
// =============================================================================
void setRelay(int pin, bool active) {
  digitalWrite(pin, active ? RELAY_ACTIVE : RELAY_INACTIVE);
}

void engageSlot(int slot) {
  activeSlot = slot;
  activeSlotStartedAt = millis();
  activeSlotLastSeen = activeSlotStartedAt;
  setRelay(SLOT_PINS[slot], true);
}

void releaseSlot() {
  if (activeSlot < 0) return;
  setRelay(SLOT_PINS[activeSlot], false);
  activeSlot = -1;
}

int findSlotForCode(unsigned long code) {
  for (int i = 0; i < WIN_COUNT; i++) {
    if (winCodes[i] != 0 && winCodes[i] == code) return i;
  }
  return -1;
}

int slotByName(const char* name) {
  for (int i = 0; i < WIN_COUNT; i++) {
    if (!strcmp(SLOT_NAMES[i], name)) return i;
  }
  return -1;
}

// =============================================================================
// Backlight
// =============================================================================
void setBacklight(const char* display, int brightness) {
  if (brightness < 0)   brightness = 0;
  if (brightness > 100) brightness = 100;
  int duty = (brightness * 255L) / 100;
  if (!strcmp(display, "large")) {
    analogWrite(PIN_BACKLIGHT_L, duty);
  } else if (!strcmp(display, "small")) {
    analogWrite(PIN_BACKLIGHT_S, duty);
  } else if (!strcmp(display, "both") || !strcmp(display, "all")) {
    analogWrite(PIN_BACKLIGHT_L, duty);
    analogWrite(PIN_BACKLIGHT_S, duty);
  } else {
    emitErrorMsg("unknown display");
  }
}

// =============================================================================
// Trunk + BLE
// =============================================================================
void handleTrunkButton(unsigned long now) {
  bool state = digitalRead(PIN_TRUNK_BUTTON);
  if (state != lastTrunkButton && (now - lastTrunkChange) > 50) {
    lastTrunkChange = now;
    lastTrunkButton = state;
    if (state == LOW) {
      // Falling edge — button pressed. Scan for BLE tag.
      if (!bleMacValid) {
        emitEvent("trunk_denied");  // no key configured
        return;
      }
      int8_t rssi;
      if (bleScanAndGate(&rssi)) {
        // Key present — pulse trunk
        setRelay(PIN_TRUNK_RELAY, true);
        trunkOffAt = millis() + TRUNK_PULSE_MS;
        Serial.print(F("{\"event\":\"trunk\",\"rssi\":"));
        Serial.print(rssi);
        Serial.println(F("}"));
      } else {
        if (rssi == -127) {
          Serial.println(F("{\"event\":\"trunk_denied\",\"reason\":\"no_key\"}"));
        } else {
          Serial.print(F("{\"event\":\"trunk_denied\",\"reason\":\"weak\",\"rssi\":"));
          Serial.print(rssi);
          Serial.println(F("}"));
        }
      }
    }
  }
}

// Issues AT+DISC? to HM-10, parses replies, looks for known MAC.
// Returns true if key found AND RSSI >= threshold.
// outRssi: best RSSI seen for the known MAC, or -127 if not seen.
bool bleScanAndGate(int8_t* outRssi) {
  *outRssi = -127;
  // Flush any leftover bytes
  while (ble.available()) ble.read();
  ble.print(F("AT+DISC?"));

  unsigned long deadline = millis() + BLE_SCAN_MS;
  char buf[80];
  uint8_t pos = 0;

  while (millis() < deadline) {
    while (ble.available()) {
      char c = ble.read();
      if (c == '\n' || c == '\r' || pos >= sizeof(buf) - 1) {
        buf[pos] = '\0';
        // Expected formats (HM-10 v6/v7+):
        //   OK+DISC:001122334455
        //   OK+RSSI:-67
        // or combined:
        //   OK+DIS0:001122334455:RSSI:-67
        // We match MAC on any line containing our 12 hex digits.
        if (pos > 0) {
          char macHex[13];
          for (int i = 0; i < 6; i++) snprintf(macHex + i*2, 3, "%02X", bleMac[i]);
          macHex[12] = 0;
          char* found = strstr(buf, macHex);
          if (found) {
            // Look for RSSI in same line or buffer
            char* rs = strstr(buf, "RSSI");
            int rssi = -127;
            if (rs) {
              rs = strchr(rs, '-');
              if (rs) rssi = atoi(rs);
            }
            if (rssi != -127 && rssi > *outRssi) *outRssi = (int8_t) rssi;
          }
        }
        pos = 0;
      } else {
        buf[pos++] = c;
      }
    }
  }
  return (*outRssi != -127) && (*outRssi >= bleRssiThreshold);
}

void hmCommand(const char* cmd) {
  ble.print(cmd);
}

// =============================================================================
// Learn modes
// =============================================================================
void enterLearnWindow(const char* slotName) {
  int slot = slotByName(slotName);
  if (slot < 0) { emitErrorMsg("bad slot"); return; }
  learnSlot = slot;
  learnUntil = millis() + LEARN_TIMEOUT_MS;
  Serial.print(F("{\"event\":\"learn_window_armed\",\"slot\":\""));
  Serial.print(slotName);
  Serial.println(F("\"}"));
}

void enterLearnBle() {
  // Scan briefly, pick MAC with strongest RSSI, store it.
  while (ble.available()) ble.read();
  ble.print(F("AT+DISC?"));
  unsigned long deadline = millis() + BLE_SCAN_MS * 2;
  char buf[80];
  uint8_t pos = 0;
  uint8_t bestMac[6] = {0};
  int8_t  bestRssi = -127;

  while (millis() < deadline) {
    while (ble.available()) {
      char c = ble.read();
      if (c == '\n' || c == '\r' || pos >= sizeof(buf) - 1) {
        buf[pos] = '\0';
        if (pos > 16) {
          // Try to extract a MAC and RSSI from the line
          // Heuristic: find 12 consecutive hex chars
          for (int i = 0; i + 12 <= (int)pos; i++) {
            bool isHex = true;
            for (int j = 0; j < 12; j++) {
              char ch = buf[i + j];
              if (!((ch >= '0' && ch <= '9') || (ch >= 'A' && ch <= 'F') || (ch >= 'a' && ch <= 'f'))) {
                isHex = false; break;
              }
            }
            if (isHex) {
              uint8_t mac[6];
              for (int k = 0; k < 6; k++) {
                char hex[3] = { buf[i + k*2], buf[i + k*2 + 1], 0 };
                mac[k] = (uint8_t) strtol(hex, nullptr, 16);
              }
              char* rs = strstr(buf, "RSSI");
              if (rs) {
                rs = strchr(rs, '-');
                if (rs) {
                  int rssi = atoi(rs);
                  if (rssi > bestRssi) {
                    bestRssi = (int8_t) rssi;
                    memcpy(bestMac, mac, 6);
                  }
                }
              }
              break;
            }
          }
        }
        pos = 0;
      } else {
        buf[pos++] = c;
      }
    }
  }

  if (bestRssi != -127) {
    saveBleMac(bestMac);
    char macHex[13];
    for (int i = 0; i < 6; i++) snprintf(macHex + i*2, 3, "%02X", bestMac[i]);
    macHex[12] = 0;
    Serial.print(F("{\"event\":\"ble_learned\",\"mac\":\""));
    Serial.print(macHex);
    Serial.print(F("\",\"rssi\":"));
    Serial.print(bestRssi);
    Serial.println(F("}"));
  } else {
    emitErrorMsg("no BLE device found");
  }
}

// =============================================================================
// EEPROM
// =============================================================================
void loadEeprom() {
  if (EEPROM.read(EEPROM_MAGIC_ADDR) != EEPROM_MAGIC_VALUE) {
    // Fresh chip — initialise to defaults
    bleRssiThreshold = BLE_DEFAULT_THRESHOLD;
    bleMacValid = false;
    return;
  }
  for (int i = 0; i < WIN_COUNT; i++) {
    unsigned long c = 0;
    for (int b = 0; b < 4; b++) {
      c |= ((unsigned long) EEPROM.read(EEPROM_CODES_ADDR + i*4 + b)) << (b*8);
    }
    winCodes[i] = c;
  }
  for (int i = 0; i < 6; i++) bleMac[i] = EEPROM.read(EEPROM_BLE_MAC + i);
  bleMacValid = false;
  for (int i = 0; i < 6; i++) if (bleMac[i]) { bleMacValid = true; break; }
  bleRssiThreshold = (int8_t) EEPROM.read(EEPROM_BLE_RSSI);
  if (bleRssiThreshold == -1 || bleRssiThreshold == 0) bleRssiThreshold = BLE_DEFAULT_THRESHOLD;
}

void saveCode(int slot, unsigned long code) {
  EEPROM.update(EEPROM_MAGIC_ADDR, EEPROM_MAGIC_VALUE);
  winCodes[slot] = code;
  for (int b = 0; b < 4; b++) {
    EEPROM.update(EEPROM_CODES_ADDR + slot*4 + b, (uint8_t)((code >> (b*8)) & 0xFF));
  }
}

void saveBleMac(const uint8_t* mac) {
  EEPROM.update(EEPROM_MAGIC_ADDR, EEPROM_MAGIC_VALUE);
  for (int i = 0; i < 6; i++) {
    EEPROM.update(EEPROM_BLE_MAC + i, mac[i]);
    bleMac[i] = mac[i];
  }
  bleMacValid = true;
}

void saveBleRssi(int8_t r) {
  EEPROM.update(EEPROM_MAGIC_ADDR, EEPROM_MAGIC_VALUE);
  EEPROM.update(EEPROM_BLE_RSSI, (uint8_t) r);
  bleRssiThreshold = r;
}

void clearEeprom() {
  for (int i = 0; i < 40; i++) EEPROM.update(i, 0xFF);
  for (int i = 0; i < WIN_COUNT; i++) winCodes[i] = 0;
  for (int i = 0; i < 6; i++) bleMac[i] = 0;
  bleMacValid = false;
  bleRssiThreshold = BLE_DEFAULT_THRESHOLD;
}

// =============================================================================
// JSON emit helpers
// =============================================================================
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

void emitWindowEvent(const char* type, int slot) {
  Serial.print(F("{\"event\":\""));
  Serial.print(type);
  Serial.print(F("\",\"slot\":\""));
  Serial.print(SLOT_NAMES[slot]);
  Serial.println(F("\"}"));
}
