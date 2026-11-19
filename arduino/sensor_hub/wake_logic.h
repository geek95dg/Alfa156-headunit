/*
 * BCM v8.5 — wybudzanie M910q z zewnątrz (sensor_hub, FEATURE_WAKE_*)
 *
 * Wersja DOCELOWA z buforem (Nano #2 zasilany 24/7, przekaźnik przycisku
 * zasilania na A0, dioda panelu na A1). W aucie testowym bez bufora nic
 * z tego się nie kompiluje — flagi są domyślnie wyłączone.
 *
 * Czysty C++ bez Arduino, jak power_logic.h: same decyzje, zero I/O, więc
 * całość — reguły przyjęcia prośby, dzierżawa, limity, blokada po zgaszeniu,
 * dekoder NEC z pilota IR i czytnik linii z hosta — ma testy na PC, także
 * przy przepełnieniu millis() (~49,7 dnia) i micros() (~71,6 min):
 *
 *   make -C arduino sensor_hub-test
 *
 * DLACZEGO TAK
 * ------------
 * M910q w S3 odcina zasilanie portów USB, więc ani telefon, ani klawiatura
 * go nie obudzą. Jedyna droga, która działa i z S3, i z OFF: Nano #2
 * „naciska” przycisk zasilania (power_logic.h). Każdy wyzwalacz to tylko
 * PROŚBA do tej logiki — przycisk zawsze naciska power_logic.h, z jego
 * zabezpieczeniami (stan z diody, cisza po impulsie, okno usypiania, limit
 * impulsów na zamiar):
 *   IR   — odbiornik TSOP na A3, telefon w aucie nadaje ramkę NEC
 *          z prywatnym adresem (termux-infrared-transmit);
 *   DOOR — otwarcie drzwi kierowcy (D2, FEATURE_DOORS);
 *   EXT  — impuls na A2 przez transoptor PC817 (np. „odblokuj” z centralnego
 *          zamka albo płytka BLE w przyszłości).
 *
 * Prośba jest przyjmowana TYLKO, gdy:
 *   - zapłon jest potwierdzony jako wyłączony (przy włączonym prośby nie ma
 *     w ogóle — otwieranie drzwi w trasie niczego nie loguje);
 *   - maszyna jest stabilnie w S3 albo wyłączona (pwrSteady), bez trwającego
 *     impulsu, ciszy po impulsie, okna usypiania i innego zamiaru —
 *     inaczej WAKE_DENIED:STATE;
 *   - drzwi: PIERWSZE otwarcie drzwi kierowcy po zgaszeniu zapłonu (po
 *     jeździe) to wysiadanie — nie budzi i nie jest odmową, nawet gdy
 *     kierowca siedział dłużej niż blokada (rozmowa); po WAKE_DOOR_EXIT_MS
 *     bez otwarcia uznajemy, że wysiadł inaczej (drzwi pasażera) i następne
 *     otwarcie to już powrót. Dodatkowo nie wcześniej niż
 *     WAKE_DOOR_HOLDOFF_MS po zgaszeniu (ponowne otwarcie przy wysiadaniu)
 *     — WAKE_DENIED:HOLDOFF;
 *   - limit: WAKE_MAX_PER_HOUR (3) w godzinie i WAKE_MAX_PER_DAY (6) na dobę
 *     przyjętych pobudek — WAKE_DENIED:RATE;
 *   - z pomiarem banku (FEATURE_BATT_*): świeży odczyt > WAKE_BATT_MIN_MV
 *     (12,2 V) — brak odczytu też jest odmową (WAKE_DENIED:LOWBATT). Bez
 *     BATT_* napięcia nie ma czym sprawdzić i ten warunek jest POMIJANY.
 *
 * Dzierżawa (lease): przyjęta pobudka daje komputerowi WAKE_LEASE_DOOR_MS
 * (5 min) albo WAKE_LEASE_REMOTE_MS (10 min, IR i EXT). Kolejna prośba
 * w trakcie przedłuża ją (bez naciskania i bez liczenia do limitu), host
 * może ją przedłużyć poleceniem HOLD:<min> (1..60) albo zakończyć RELEASE.
 * Cała sesja nie dłużej niż WAKE_SESSION_MAX_MS (90 min) od pobudki — także
 * przy hoście, który bez końca wysyła HOLD. Koniec dzierżawy przy
 * wyłączonym zapłonie = zamiar S3: power_logic.h naciska SHORT tylko na
 * STABILNIE pracującą maszynę (nigdy LONG — eskalacja do OFF zostaje jak
 * była, po 2 h od pobudki). Zapłon kasuje dzierżawę bez naciskania.
 *
 * Reset Nano (CH340 resetuje płytkę przy KAŻDYM otwarciu portu przez BCM —
 * DTR — czyli zaraz po każdej pobudce; także watchdog) nie może gubić
 * dzierżawy ani limitów: wtedy BCM nigdy nie dowiedziałby się o pobudce,
 * a komputer pracowałby do eskalacji (2 h). Dlatego WakeLogic leży
 * w sketchu w sekcji .noinit (RAM przeżywa reset, nie przeżywa zaniku
 * zasilania) i jest pieczętowany sumą kontrolną (wakeSeal) po każdym
 * obiegu; po resecie wakeBoot() sprawdza znacznik i sumę i ciągnie zegar
 * budzenia dalej (+WAKE_RESET_GAP_MS na bootloader). Po zaniku zasilania
 * (śmieci w RAM) — czysty start, a blokada drzwi liczy się od startu.
 *
 * CZAS: jak w power_logic.h — uint32_t i wyłącznie różnice:
 *   (uint32_t)(now - start) >= okres     — „minęło już tyle”
 *   (int32_t)(now - termin) < 0          — „termin jeszcze nie nadszedł”
 * Znaczniki, które mogłyby przeleżeć ponad 2^31 ms, mają flagę ważności
 * i są porzucane, gdy minie ich okno (sloty limitu, blokada drzwi, para
 * ramek IR) — stary znacznik sprzed miesięcy nigdy nie wygląda na świeży.
 * Zegar budzenia (`wnow`) i millis() (`pnow`, dla power_logic.h) to dwa
 * zegary: po resecie millis() startuje od zera, zegar budzenia nie.
 *
 * NIESPRAWDZONE NA STOLE: tolerancje NEC z prawdziwym TSOP (zakresy niżej
 * są szerokie, z zapasem na wydłużanie znaczników przez odbiornik), zasięg
 * diody IR Redmi do TSOP pod osłonką, przetrwanie .noinit przez bootloader
 * (optiboot nie pisze do RAM bez programowania; stary bootloader — sprawdź:
 * po otwarciu portu linie WAKE:/LEASE: mają trwać dalej).
 */
#pragma once

#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include "power_logic.h"

// --- dzierżawa i limity -------------------------------------------------------
#define WAKE_LEASE_DOOR_MS      300000UL   // drzwi: 5 min
#define WAKE_LEASE_REMOTE_MS    600000UL   // IR / EXT: 10 min
#define WAKE_SESSION_MAX_MS    5400000UL   // cała sesja: 90 min od pobudki
#define WAKE_HOLD_MAX_MIN           60     // HOLD:<min> — najwyżej tyle naraz
#define WAKE_MAX_PER_HOUR            3
#define WAKE_MAX_PER_DAY             6
#define WAKE_HOUR_MS           3600000UL
#define WAKE_DAY_MS           86400000UL
#define WAKE_DOOR_HOLDOFF_MS    120000UL   // 2 min po zgaszeniu: wysiadanie
#define WAKE_DOOR_EXIT_MS      1800000UL   // pierwsze otwarcie w ciągu 30 min = wysiadanie
#define WAKE_BATT_MIN_MV         12200L    // bank > 12,2 V
// Po starcie płytki wejścia przez tyle ms tylko obserwujemy: debouncery
// w sketchu startują od „zamknięte / nieaktywne”, więc pierwsze odczyty
// wyglądałyby jak otwarcie drzwi.
#define WAKE_INPUT_SETTLE_MS      1000UL
#define WAKE_EXT_DEBOUNCE_MS        50UL   // impuls EXT ≥ 50 ms
// Bootloader po resecie (DTR, watchdog) trwa ~1–2 s — o tyle zegar budzenia
// przesuwa się w przód (dokładność nieistotna przy minutach dzierżawy).
#define WAKE_RESET_GAP_MS         2000UL
#define WAKE_MAGIC          0x57414B32UL   // "WAK2"; zmiana układu = nowa wartość

// --- IR (FEATURE_WAKE_IR) -----------------------------------------------------
// Prywatny kod NEC: 16-bitowy adres (bajt młodszy wysyłany pierwszy; NIE
// musi być parą adres/~adres jak w zwykłym NEC — prywatny adres rozszerzony
// rzadziej trafia na cudze piloty) i polecenie z negacją. TE SAME wartości
// muszą być w BCM: power.remote_session.ir_address / ir_command
// (local.yaml) — agent w telefonie dostaje je stamtąd. Zmiana tutaj =
// edycja dwóch #define i wgranie firmware.
#ifndef WAKE_IR_ADDRESS
#define WAKE_IR_ADDRESS        0x7A15U
#endif
#ifndef WAKE_IR_COMMAND
#define WAKE_IR_COMMAND          0x56U
#endif
#define WAKE_IR_PAIR_MS           1000UL   // 2 identyczne ramki w ciągu 1 s
#define WAKE_IR_REARM_MS          3000UL   // po przyjętej parze: cisza
                                           // (telefon nadaje 3 ramki)

enum WakeSrc : uint8_t { WAKE_SRC_NONE = 0, WAKE_SRC_IR, WAKE_SRC_DOOR, WAKE_SRC_EXT };
enum WakeDeny : uint8_t {
  WAKE_DENY_NONE = 0, WAKE_DENY_RATE, WAKE_DENY_LOWBATT, WAKE_DENY_HOLDOFF, WAKE_DENY_STATE
};
enum WakeIgn : uint8_t { WAKE_IGN_UNKNOWN = 0, WAKE_IGN_OFF, WAKE_IGN_ON };

// Stan w .noinit — tylko proste typy (bez konstruktorów), bo w .noinit nikt
// go nie inicjalizuje; pole `sum` MUSI być ostatnie (suma liczy wszystko
// przed nim).
struct WakeLogic {
  uint32_t magic;
  uint16_t size;
  uint32_t clock;          // ostatni odczyt zegara budzenia (ciągłość po resecie)

  uint8_t  ign;            // WakeIgn — ostatni potwierdzony zapłon
  bool     holdoff;        // trwa blokada drzwi po zgaszeniu
  bool     exitPending;    // po jeździe: pierwsze otwarcie drzwi = wysiadanie
  uint32_t ignOffAt;

  bool     lease;          // trwa dzierżawa
  uint8_t  reason;         // WakeSrc ostatniej prośby w sesji
  uint32_t leaseUntil;
  uint32_t sessionAt;      // przyjęcie pobudki (limit sesji)

  bool     slotUsed[WAKE_MAX_PER_DAY];   // przyjęte pobudki z ostatniej doby
  uint32_t slotAt[WAKE_MAX_PER_DAY];

  uint16_t denied;         // odmowy od zaniku zasilania (nasycenie 65535)
  uint8_t  lastDenied;     // WakeDeny ostatniej odmowy

  // Wejścia — nie przeżywają resetu (wakeBoot je zeruje).
  uint32_t bootAt;
  bool     settled;
  bool     doorKnown;
  bool     doorOpen;
  bool     extKnown;
  bool     extState;
  bool     extRaw;
  uint32_t extChangeAt;
  bool     irPrev;         // pierwsza ramka pary
  uint32_t irPrevAt;
  bool     irHold;         // cisza po przyjętej parze
  uint32_t irHoldAt;

  uint16_t sum;
};

// Co sketch podaje w każdym obiegu.
struct WakeIn {
  bool    doorOpen;        // zdebouncowane drzwi kierowcy (FEATURE_WAKE_DOOR)
  bool    extActive;       // SUROWY poziom A2: true = transoptor przewodzi
  bool    irPair;          // w tym obiegu przyszła para ramek (wakeIrFrame)
  bool    pulsing;         // trwa impuls przekaźnika
  bool    battCheck;       // skompilowany pomiar banku (FEATURE_BATT_*)
  int32_t battMv;          // świeży odczyt banku [mV]; < 0 = brak
};

// Co sketch ma wypisać po obiegu.
struct WakeOut {
  uint8_t wake;            // WakeSrc przyjętej albo przedłużającej prośby → WAKE:
  uint8_t denied;          // WakeDeny → WAKE_DENIED:
  bool    lease;           // zmiana dzierżawy → LEASE:<s>
};

// --- pieczęć .noinit ------------------------------------------------------------

// Suma Fletchera modulo 256 po wszystkim przed `sum` (dwa dodawania na bajt —
// liczona w KAŻDYM obiegu, więc bez dzielenia, które na AVR kosztuje setki
// cykli). Pojedynczy przekłamany bajt i zamiana bajtów miejscami zmieniają
// wynik; po zaniku zasilania przypadkowa zgodność znacznika (32 bity),
// rozmiaru i sumy jest praktycznie niemożliwa.
inline uint16_t wakeChecksum(const WakeLogic& s) {
  const uint8_t* p = reinterpret_cast<const uint8_t*>(&s);
  uint8_t a = 0x5A, b = 0xA5;
  for (size_t i = 0; i < offsetof(WakeLogic, sum); i++) {
    a = (uint8_t)(a + p[i]);
    b = (uint8_t)(b + a);
  }
  return (uint16_t)(((uint16_t)b << 8) | a);
}

inline void wakeSeal(WakeLogic& s) { s.sum = wakeChecksum(s); }

inline bool wakeValid(const WakeLogic& s) {
  return s.magic == WAKE_MAGIC && s.size == (uint16_t)sizeof(WakeLogic) &&
         s.sum == wakeChecksum(s);
}

// Start płytki (setup). `now` = millis(). Zwraca zegar budzenia „na teraz”:
// po resecie z ważnym stanem — zapisany + WAKE_RESET_GAP_MS (dzierżawa,
// limity i blokada drzwi trwają dalej), po zaniku zasilania — `now` i czysty
// stan. Sketch liczy potem wnow = (zwrócone - now) + millis().
inline uint32_t wakeBoot(WakeLogic& s, uint32_t now) {
  if (wakeValid(s)) {
    s.clock += WAKE_RESET_GAP_MS;
  } else {
    memset(&s, 0, sizeof(s));        // także dopełnienie struktury (suma)
    s.magic = WAKE_MAGIC;
    s.size = (uint16_t)sizeof(WakeLogic);
    s.clock = now;
  }
  s.bootAt = s.clock;
  s.settled = false;
  s.doorKnown = false;
  s.doorOpen = false;
  s.extKnown = false;
  s.extState = false;
  s.extRaw = false;
  s.extChangeAt = s.clock;
  s.irPrev = false;
  s.irHold = false;
  wakeSeal(s);
  return s.clock;
}

// --- dzierżawa ------------------------------------------------------------------

inline uint32_t wakeLeaseMs(uint8_t src) {
  return src == WAKE_SRC_DOOR ? WAKE_LEASE_DOOR_MS : WAKE_LEASE_REMOTE_MS;
}

// Przedłuż do `wnow + ms`, nigdy nie skracaj, nie dalej niż limit sesji.
inline void wakeExtend(WakeLogic& s, uint32_t wnow, uint32_t ms) {
  uint32_t until = wnow + ms;
  const uint32_t cap = s.sessionAt + WAKE_SESSION_MAX_MS;
  if ((int32_t)(until - cap) > 0) until = cap;
  if ((int32_t)(until - s.leaseUntil) > 0) s.leaseUntil = until;
}

// Koniec dzierżawy (czas minął albo RELEASE). Przy wyłączonym zapłonie
// zamiar S3 — power_logic.h naciśnie SHORT tylko na stabilnie pracującą
// maszynę i tylko raz (śpiąca zostaje w spokoju).
inline void wakeEnd(WakeLogic& s, PwrLogic& p, uint32_t pnow, WakeOut& out) {
  s.lease = false;
  out.lease = true;
  if (p.ignKnown && !p.ignLevel) pwrSetIntent(p, PWR_SLEEP, pnow);
}

// Ile sekund dzierżawy zostało (0 = brak), w górę — LEASE:<s>.
inline uint32_t wakeLeaseLeft(const WakeLogic& s, uint32_t wnow) {
  if (!s.lease) return 0;
  const int32_t d = (int32_t)(s.leaseUntil - wnow);
  return d <= 0 ? 0 : ((uint32_t)d + 999UL) / 1000UL;
}

// --- limit pobudek ---------------------------------------------------------------

inline bool wakeRateOk(const WakeLogic& s, uint32_t wnow) {
  uint8_t hour = 0, day = 0;
  for (uint8_t i = 0; i < WAKE_MAX_PER_DAY; i++) {
    if (!s.slotUsed[i]) continue;
    day++;
    if ((uint32_t)(wnow - s.slotAt[i]) < WAKE_HOUR_MS) hour++;
  }
  return hour < WAKE_MAX_PER_HOUR && day < WAKE_MAX_PER_DAY;
}

inline void wakeRateTake(WakeLogic& s, uint32_t wnow) {
  for (uint8_t i = 0; i < WAKE_MAX_PER_DAY; i++) {
    if (!s.slotUsed[i]) {
      s.slotUsed[i] = true;
      s.slotAt[i] = wnow;
      return;
    }
  }
}

// --- prośba -----------------------------------------------------------------------

inline void wakeDeny(WakeLogic& s, uint8_t why, WakeOut& out) {
  if (s.denied < 0xFFFFU) s.denied++;
  s.lastDenied = why;
  out.denied = why;
}

// Czy power_logic.h może teraz bezpiecznie wcisnąć przycisk „na pobudkę”.
inline bool wakePwrReady(const PwrLogic& p, uint32_t pnow, bool pulsing) {
  if (pulsing || p.settling || p.grace || p.desired != PWR_UNKNOWN) return false;
  if (!pwrSteady(p, pnow)) return false;
  return p.state == PWR_SLEEP || p.state == PWR_OFF;
}

inline void wakeRequest(WakeLogic& s, PwrLogic& p, uint8_t src, uint32_t wnow,
                        uint32_t pnow, const WakeIn& in, WakeOut& out) {
  // Zapłon włączony albo jeszcze niepotwierdzony (2 s po resecie): to nie
  // jest prośba o pobudkę, komputer i tak pracuje albo zaraz wstanie.
  if (!p.ignKnown || p.ignLevel) return;
  if (s.lease) {
    // Trwa sesja: przedłużenie, bez naciskania i bez liczenia do limitu.
    wakeExtend(s, wnow, wakeLeaseMs(src));
    s.reason = src;
    out.wake = src;
    out.lease = true;
    return;
  }
  if (src == WAKE_SRC_DOOR && s.holdoff) {
    wakeDeny(s, WAKE_DENY_HOLDOFF, out);
    return;
  }
  if (!wakePwrReady(p, pnow, in.pulsing)) {
    wakeDeny(s, WAKE_DENY_STATE, out);
    return;
  }
  if (!wakeRateOk(s, wnow)) {
    wakeDeny(s, WAKE_DENY_RATE, out);
    return;
  }
  if (in.battCheck && (in.battMv < 0 || in.battMv <= WAKE_BATT_MIN_MV)) {
    wakeDeny(s, WAKE_DENY_LOWBATT, out);
    return;
  }
  wakeRateTake(s, wnow);
  s.lease = true;
  s.reason = src;
  s.sessionAt = wnow;
  s.leaseUntil = wnow;               // wakeExtend tylko wydłuża
  wakeExtend(s, wnow, wakeLeaseMs(src));
  pwrSetIntent(p, PWR_RUNNING, pnow);
  out.wake = src;
  out.lease = true;
}

// Ramka NEC z dekodera (pętla, po zdjęciu z przerwania). True = przyszła
// druga identyczna ramka z prywatnym adresem w ciągu WAKE_IR_PAIR_MS — prośba
// IR (sketch podaje ją w WakeIn.irPair). Cudze kody i powtórzenia (repeat)
// nic nie robią.
inline bool wakeIrFrame(WakeLogic& s, uint16_t addr, uint8_t cmd, uint32_t wnow) {
  if (!s.settled || s.irHold) return false;
  if (addr != (uint16_t)WAKE_IR_ADDRESS || cmd != (uint8_t)WAKE_IR_COMMAND) return false;
  if (s.irPrev && (uint32_t)(wnow - s.irPrevAt) <= WAKE_IR_PAIR_MS) {
    s.irPrev = false;
    s.irHold = true;
    s.irHoldAt = wnow;
    return true;
  }
  s.irPrev = true;
  s.irPrevAt = wnow;
  return false;
}

// --- jeden obieg loop() --------------------------------------------------------------
//
// `wnow` = zegar budzenia, `pnow` = millis() (dla power_logic.h). Wołać
// w każdym obiegu, także w trakcie impulsu (in.pulsing); po nim wakeSeal().
inline void wakeStep(WakeLogic& s, PwrLogic& p, uint32_t wnow, uint32_t pnow,
                     const WakeIn& in, WakeOut& out) {
  out.wake = WAKE_SRC_NONE;
  out.denied = WAKE_DENY_NONE;
  out.lease = false;
  s.clock = wnow;

  // 1. Znaczniki, którym minęło okno, przestają istnieć (rollover).
  if (!s.settled && (uint32_t)(wnow - s.bootAt) >= WAKE_INPUT_SETTLE_MS) s.settled = true;
  for (uint8_t i = 0; i < WAKE_MAX_PER_DAY; i++) {
    if (s.slotUsed[i] && (uint32_t)(wnow - s.slotAt[i]) >= WAKE_DAY_MS) s.slotUsed[i] = false;
  }
  if (s.holdoff && (uint32_t)(wnow - s.ignOffAt) >= WAKE_DOOR_HOLDOFF_MS) s.holdoff = false;
  if (s.exitPending && (uint32_t)(wnow - s.ignOffAt) >= WAKE_DOOR_EXIT_MS) s.exitPending = false;
  if (s.irPrev && (uint32_t)(wnow - s.irPrevAt) > WAKE_IR_PAIR_MS) s.irPrev = false;
  if (s.irHold && (uint32_t)(wnow - s.irHoldAt) >= WAKE_IR_REARM_MS) s.irHold = false;

  // 2. Zapłon (potwierdzony przez power_logic.h — ten sam, który usypia).
  //    Zgaszenie (także „nie wiadomo → wyłączony” po zaniku zasilania)
  //    zaczyna blokadę drzwi; włączenie kasuje dzierżawę bez naciskania.
  //    Wysiadanie (exitPending) tylko po prawdziwej jeździe (ON → OFF): po
  //    zaniku zasilania nie wiadomo, czy ktoś w ogóle siedzi w aucie.
  if (p.ignKnown) {
    const uint8_t ign = p.ignLevel ? WAKE_IGN_ON : WAKE_IGN_OFF;
    if (ign != s.ign) {
      const uint8_t prev = s.ign;
      s.ign = ign;
      if (ign == WAKE_IGN_ON) {
        s.exitPending = false;
        if (s.lease) {
          s.lease = false;
          out.lease = true;
        }
      } else {
        s.holdoff = true;
        s.exitPending = prev == WAKE_IGN_ON;
        s.ignOffAt = wnow;
      }
    }
  }

  // 3. Koniec dzierżawy — tylko przy POTWIERDZONYM zapłonie. Przez ~2 s po
  //    każdym resecie Nano (DTR przy każdym otwarciu portu przez BCM)
  //    ignKnown jest false; zakończona wtedy dzierżawa nie dałaby zamiaru S3,
  //    a komputer zostałby włączony na banku aż do eskalacji (do 2 h).
  //    Dzierżawa czeka więc na potwierdzenie: zapłon wyłączony → SHORT,
  //    włączony → krok 2 kasuje ją bez naciskania.
  if (s.lease && p.ignKnown && (int32_t)(wnow - s.leaseUntil) >= 0) wakeEnd(s, p, pnow, out);

  // 4. Wejścia → prośby. Przed WAKE_INPUT_SETTLE_MS tylko poziom, bez zboczy.
  if (!s.settled || !s.doorKnown) {
    s.doorOpen = in.doorOpen;
    s.doorKnown = s.settled;
  } else if (in.doorOpen != s.doorOpen) {
    s.doorOpen = in.doorOpen;
    if (in.doorOpen) {
      // Pierwsze otwarcie po jeździe = kierowca wysiada: bez pobudki i bez
      // odmowy (nie zjada limitu, nie nabija licznika odmów). Tylko przy
      // potwierdzonym, wyłączonym zapłonie — przy włączonym prośby i tak
      // nie ma, a flagi nie wolno wtedy zużyć.
      if (s.exitPending && p.ignKnown && !p.ignLevel) {
        s.exitPending = false;
      } else {
        wakeRequest(s, p, WAKE_SRC_DOOR, wnow, pnow, in, out);
      }
    }
  }

  if (in.extActive != s.extRaw) {
    s.extRaw = in.extActive;
    s.extChangeAt = wnow;
  }
  if ((uint32_t)(wnow - s.extChangeAt) >= WAKE_EXT_DEBOUNCE_MS) {
    if (!s.extKnown) {
      if (s.settled) {
        s.extKnown = true;
        s.extState = s.extRaw;
      }
    } else if (s.extRaw != s.extState) {
      s.extState = s.extRaw;
      if (s.extState) wakeRequest(s, p, WAKE_SRC_EXT, wnow, pnow, in, out);
    }
  }

  if (in.irPair) wakeRequest(s, p, WAKE_SRC_IR, wnow, pnow, in, out);
}

// --- polecenia z hosta (BCM: src/power/remote_session.py) ------------------------

// HOLD:<min> — przedłuż dzierżawę do co najmniej `min` minut od teraz (w
// granicach sesji). Bez dzierżawy nic (komputer nie był budzony z zewnątrz —
// tym rządzi zwykła eskalacja). Zwraca, czy przedłużył.
inline bool wakeHold(WakeLogic& s, uint8_t minutes, uint32_t wnow) {
  if (!s.lease || minutes < 1 || minutes > WAKE_HOLD_MAX_MIN) return false;
  // Dzierżawa już minęła (albo RELEASE czeka na potwierdzenie zapłonu po
  // resecie): HOLD jej nie wskrzesza — sesja jest skończona.
  if (wakeLeaseLeft(s, wnow) == 0) return false;
  wakeExtend(s, wnow, (uint32_t)minutes * 60000UL);
  return true;
}

// RELEASE — zakończ dzierżawę teraz (SHORT, gdy komputer stabilnie pracuje).
// Zapłon jeszcze niepotwierdzony (~2 s po resecie Nano — a BCM ponawia
// nieudany RELEASE właśnie po ponownym otwarciu portu): dzierżawa kończy się
// „na papierze” (LEASE:0 od razu), a naprawdę — z zamiarem S3 — w kroku 3
// wakeStep, gdy power_logic.h potwierdzi zapłon.
inline bool wakeRelease(WakeLogic& s, PwrLogic& p, uint32_t wnow, uint32_t pnow,
                        WakeOut& out) {
  if (!s.lease) return false;
  if (!p.ignKnown) {
    if ((int32_t)(s.leaseUntil - wnow) > 0) s.leaseUntil = wnow;
    out.lease = true;
    return true;
  }
  wakeEnd(s, p, pnow, out);
  return true;
}

// --- czytnik linii z hosta -----------------------------------------------------------
//
// Sketch dotąd nie czytał Serial wcale. Teraz czyta, ale ostrożnie: najwyżej
// WAKE_LINE_MAX znaków na linię (dłuższa jest w całości odrzucana aż do
// końca linii), tylko drukowalne ASCII, i przyjmuje WYŁĄCZNIE dwa polecenia:
//   HOLD:<min>   1..60, bez zer wiodących  → LEASE:<s>
//   RELEASE                                → LEASE:0
// Nic z hosta nie naciska przycisku bezpośrednio: HOLD tylko przedłuża
// istniejącą dzierżawę (w granicach sesji 90 min), RELEASE ją kończy.

#define WAKE_LINE_MAX 16

struct WakeLine {
  char    buf[WAKE_LINE_MAX + 1];
  uint8_t len;
  bool    bad;             // za długa albo znak spoza ASCII — do końca linii
};

// Jeden znak. True = w buf jest kompletna, poprawna linia (bez '\n').
inline bool wakeLineFeed(WakeLine& r, char c) {
  if (c == '\n' || c == '\r') {
    const bool ok = !r.bad && r.len > 0;
    r.buf[r.len] = '\0';
    r.len = 0;
    r.bad = false;
    return ok;
  }
  if (r.bad) return false;
  const uint8_t u = (uint8_t)c;
  if (u < 0x20 || u > 0x7E || r.len >= WAKE_LINE_MAX) {
    r.bad = true;
    return false;
  }
  r.buf[r.len++] = c;
  return false;
}

enum WakeCmd : uint8_t { WAKE_CMD_NONE = 0, WAKE_CMD_HOLD, WAKE_CMD_RELEASE };

// Ścisłe rozpoznanie polecenia (bez spacji, bez małych liter, bez znaku).
inline uint8_t wakeParseCmd(const char* s, uint8_t& minutes) {
  static const char REL[] = "RELEASE";
  uint8_t i = 0;
  while (REL[i] && s[i] == REL[i]) i++;
  if (!REL[i] && !s[i]) return WAKE_CMD_RELEASE;
  if (s[0] != 'H' || s[1] != 'O' || s[2] != 'L' || s[3] != 'D' || s[4] != ':') {
    return WAKE_CMD_NONE;
  }
  const char* d = s + 5;
  if (d[0] < '1' || d[0] > '9') return WAKE_CMD_NONE;
  uint8_t v = (uint8_t)(d[0] - '0');
  if (d[1]) {
    if (d[1] < '0' || d[1] > '9' || d[2]) return WAKE_CMD_NONE;
    v = (uint8_t)(v * 10 + (d[1] - '0'));
  }
  if (v < 1 || v > WAKE_HOLD_MAX_MIN) return WAKE_CMD_NONE;
  minutes = v;
  return WAKE_CMD_HOLD;
}

// --- dekoder NEC (FEATURE_WAKE_IR) ------------------------------------------------------
//
// Bez bibliotek (CI nie instaluje IRremote): przerwanie zmiany stanu na A3
// woła necEdge() przy KAŻDYM zboczu wyjścia TSOP z micros(). Dekoder klasyfikuje
// odcinek, który właśnie się skończył (znacznik = nośna = wyjście TSOP LOW,
// przerwa = HIGH), po jego długości:
//   prowadzący znacznik 9 ms, przerwa 4,5 ms, 32 bity (znacznik 562 µs,
//   przerwa 562 µs = 0 / 1687 µs = 1, najmłodszy bit pierwszy), znacznik
//   końcowy 562 µs. Ramka „repeat” (9 ms + 2,25 ms) nic nie daje.
// Bity: adres 16 (młodszy bajt pierwszy), polecenie 8, negacja polecenia 8 —
// ramka z niezgodną negacją jest odrzucana. Różnice micros() przez uint32_t,
// więc przepełnienie (~71,6 min) nie psuje żadnego pomiaru; odcinek dłuższy
// niż 2^32 µs to bezczynność, a każda nowa ramka zaczyna się od 9 ms
// znacznika, który zawsze zaczyna dekodowanie od nowa. Zgubione zbocze (dwa
// odcinki tego samego poziomu) = od nowa.
//
// Przerwanie tylko pisze, pętla czyta pod noInterrupts() (bariera pamięci),
// więc stan nie musi być volatile. Tolerancje szerokie: TSOP wydłuża
// znaczniki i skraca przerwy o ~100–200 µs.

#define NEC_LEAD_MARK_MIN    7500UL
#define NEC_LEAD_MARK_MAX   10500UL
#define NEC_LEAD_SPACE_MIN   3500UL
#define NEC_LEAD_SPACE_MAX   5500UL
#define NEC_BIT_MARK_MIN      250UL
#define NEC_BIT_MARK_MAX      900UL
#define NEC_ZERO_MIN          250UL
#define NEC_ZERO_MAX          900UL
#define NEC_ONE_MIN          1200UL
#define NEC_ONE_MAX          2200UL

enum NecPhase : uint8_t { NEC_IDLE = 0, NEC_LEAD_SPACE, NEC_BITS, NEC_STOP };

struct NecDecoder {
  uint8_t  phase;
  bool     primed;         // pierwsze zbocze już było
  bool     mark;           // poziom bieżącego odcinka (true = nośna)
  uint32_t edgeAt;         // micros() ostatniego zbocza
  uint8_t  bits;
  uint32_t data;
  bool     ready;          // jest ramka do odebrania
  uint16_t addr;
  uint8_t  cmd;
};

inline void necInit(NecDecoder& d) { memset(&d, 0, sizeof(d)); }

inline bool necIn(uint32_t v, uint32_t lo, uint32_t hi) { return v >= lo && v <= hi; }

// Odcinek o poziomie `wasMark`, trwający `dur` µs, właśnie się skończył.
inline void necSegment(NecDecoder& d, bool wasMark, uint32_t dur) {
  switch (d.phase) {
    case NEC_LEAD_SPACE:
      if (!wasMark && necIn(dur, NEC_LEAD_SPACE_MIN, NEC_LEAD_SPACE_MAX)) {
        d.phase = NEC_BITS;
        d.bits = 0;
        d.data = 0;
        return;
      }
      break;
    case NEC_BITS:
      if (wasMark) {
        if (necIn(dur, NEC_BIT_MARK_MIN, NEC_BIT_MARK_MAX)) return;
      } else if (necIn(dur, NEC_ZERO_MIN, NEC_ZERO_MAX) || necIn(dur, NEC_ONE_MIN, NEC_ONE_MAX)) {
        if (dur >= NEC_ONE_MIN) d.data |= (1UL << d.bits);
        if (++d.bits == 32) d.phase = NEC_STOP;
        return;
      }
      break;
    case NEC_STOP:
      if (wasMark && necIn(dur, NEC_BIT_MARK_MIN, NEC_BIT_MARK_MAX)) {
        const uint8_t cmd = (uint8_t)(d.data >> 16);
        const uint8_t inv = (uint8_t)(d.data >> 24);
        if ((uint8_t)(cmd ^ inv) == 0xFF) {
          d.addr = (uint16_t)(d.data & 0xFFFFUL);
          d.cmd = cmd;
          d.ready = true;
        }
        d.phase = NEC_IDLE;
        return;
      }
      break;
    default:
      break;
  }
  // IDLE albo odcinek nie pasuje: od nowa — a ten odcinek może być
  // prowadzącym znacznikiem następnej ramki.
  d.phase = (wasMark && necIn(dur, NEC_LEAD_MARK_MIN, NEC_LEAD_MARK_MAX)) ? NEC_LEAD_SPACE
                                                                         : NEC_IDLE;
}

// Zbocze: `mark` = poziom PO zboczu (true = TSOP widzi nośną, wyjście LOW).
inline void necEdge(NecDecoder& d, bool mark, uint32_t nowUs) {
  if (!d.primed) {
    d.primed = true;
    d.mark = mark;
    d.edgeAt = nowUs;
    return;
  }
  const uint32_t dur = (uint32_t)(nowUs - d.edgeAt);
  d.edgeAt = nowUs;
  if (mark == d.mark) {          // zgubione zbocze — dwa odcinki jednego poziomu
    d.phase = NEC_IDLE;
    return;
  }
  const bool wasMark = d.mark;
  d.mark = mark;
  necSegment(d, wasMark, dur);
}
