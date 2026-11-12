/*
 * BCM v8.5 — logika przycisku zasilania M910q (sensor_hub, FEATURE_PWRBTN)
 *
 * Czysty C++ bez Arduino: same decyzje, zero I/O. Sketch czyta zapłon
 * i diodę panelu, raz na obieg loop() woła pwrLedSample() (z FEATURE_PWRLED)
 * i pwrStep(), a potem wykonuje zwrócony impuls. Dzięki temu całą logikę
 * da się sprawdzić zwykłym g++ na PC, łącznie z przepełnieniem millis()
 * po ~49,7 dnia:
 *
 *   make -C arduino sensor_hub-test
 *
 * Nano #2 jest w docelowej wersji zasilany z bufora 24/7, więc przepełnienie
 * millis() to nie teoria, tylko rzecz, która zdarza się co półtora miesiąca.
 *
 * CZAS: uint32_t, a nie unsigned long. Na AVR to ten sam typ (32 bity), ale
 * na 64-bitowym PC unsigned long ma 64 bity i test przepełnienia niczego by
 * nie sprawdził. Porównania WYŁĄCZNIE przez różnicę:
 *   (uint32_t)(now - start) >= okres     — „minęło już tyle”
 *   (int32_t)(now - termin) < 0          — „termin jeszcze nie nadszedł”
 * Nigdy `now < termin`: po przepełnieniu now jest małe, stary termin duży
 * i warunek trwa do kolejnego przepełnienia (sterowanie martwe na tygodnie).
 * Druga postać działa tylko dla terminów bliższych niż 2^31 ms (~24,8 dnia),
 * dlatego termin ciszy po impulsie ma flagę `settling` i jest porzucany,
 * gdy minie — stary termin sprzed miesiąca znów wyglądałby na przyszły.
 * Tak samo okno usypiania (`grace`).
 *
 * Zasady (opis sprzętu i reakcji systemu: sensor_hub.ino, FEATURE_PWRBTN):
 *   - zbocze zapłonu (potwierdzone PWR_IGN_CONFIRM_MS) daje zamiar:
 *     włączony → RUNNING, zgaszony → S3. Zamiar nie jest stanem, do którego
 *     firmware dąży bez końca: po spełnieniu, po limicie impulsów albo po
 *     PWR_INTENT_TTL_MS znika, więc firmware nie walczy z człowiekiem;
 *   - naciskamy tylko na podstawie stanu, który się UTRZYMAŁ (pwrSteady):
 *     pojedyncze okno diody źle rozpoznane — np. przy nieznanym rytmie
 *     mrugania w S3 — nie może wyzwolić ani SHORT, ani LONG;
 *   - SHORT na działającą maszynę host wykonuje po swojemu: acpid →
 *     bcm-power-toggle.sh zatrzymuje bcm-headunit (TimeoutStopSec=45),
 *     czeka 1 s i dopiero wtedy usypia. Przez to okno (PWR_SUSPEND_GRACE_MS)
 *     dioda legalnie świeci dalej. Drugi SHORT w tym czasie uruchomiłby
 *     skrypt drugi raz, a ten zawsze kończy się `systemctl suspend` — po
 *     wybudzeniu maszyna zasnęłaby ponownie. Dlatego w oknie nie naciskamy
 *     drugi raz, a zamiar RUNNING (zapłon wrócił w trakcie usypiania) czeka:
 *     gdy maszyna jednak zaśnie, dostaje SHORT i wstaje;
 *   - po PWR_OFF_AFTER_MS zgaszonego zapłonu eskalacja do OFF, ale LONG
 *     (twarde wyłączenie) idzie TYLKO na maszynę stabilnie uśpioną (S3).
 *     Działającą (np. obudzoną ręcznie) najpierw usypia SHORT — Linux
 *     zamyka się po swojemu — a LONG przychodzi dopiero po potwierdzeniu S3;
 *   - wybudzenie z zewnątrz przy zgaszonym zapłonie (stan stabilnie przechodzi
 *     w RUNNING) uzbraja eskalację od nowa i liczy 2 h od tej chwili.
 *
 * NIESPRAWDZONE NA STOLE: rytm diody M910q w S3. Dekoder niżej rozpoznaje
 * każde miganie z przerwami krótszymi niż ~6 s, ale zanim zacznie się polegać
 * na eskalacji, trzeba zobaczyć w `picocom`, że w S3 każda linia to
 * `PWR:SLEEP` (bez przeskoków na RUNNING/OFF) — WDROZENIE_TESTOWE.md §3.1a.
 */
#pragma once

#include <stdint.h>

#define PWR_SETTLE_MS        15000UL      // po impulsie nie ruszamy niczego
#define PWR_IGN_CONFIRM_MS    2000UL      // zapłon musi się utrzymać (rozruch!)
#define PWR_OFF_AFTER_MS   7200000UL      // 2 h zgaszonego zapłonu → wyłącz
// Stan z diody uznajemy za pewny, gdy nie zmienił się przez tyle ms (kilka
// okien odczytu).
#define PWR_STABLE_MS        10000UL
// Eskalacja przy działającej maszynie: kolejny SHORT najwcześniej po tylu ms,
// gdyby host pierwszy zignorował (np. trwał start systemu).
#define PWR_ESC_RETRY_MS   1800000UL      // 30 min
// Okno usypiania po SHORT na działającą maszynę: stop bcm-headunit (do 45 s)
// + sleep 1 + suspend, z zapasem. Kończy się wcześniej, gdy dioda pokaże
// stabilny stan inny niż praca (host wykonał wciśnięcie).
#define PWR_SUSPEND_GRACE_MS 90000UL
// Zamiar RUNNING, a stan diody od tylu ms nie ustalił się ani razu: dioda
// pracującej maszyny świeci ciągle i zawsze się dekoduje, więc to nie jest
// praca — naciskamy (z limitem PWR_INTENT_PULSES).
#define PWR_UNSTEADY_MS      30000UL
// Zamiar, którego nie da się zrealizować (stan w ruchu), wygasa po tylu ms
// od ustawienia albo od ostatniego impulsu. Bez tego zamiar sprzed godzin
// uśpiłby maszynę, którą człowiek właśnie obudził.
#define PWR_INTENT_TTL_MS   120000UL
// Najwyżej tyle impulsów na jeden zamiar RUNNING (S3 dostaje jeden) —
// zepsuty przekaźnik albo dioda nie mogą naciskać w nieskończoność.
#define PWR_INTENT_PULSES        2

// Dekoder diody (FEATURE_PWRLED): zliczanie zboczy w oknach.
#define PWR_LED_WINDOW_MS     1600UL
// Ciągłe światło / ciemność dopiero po tylu kolejnych oknach bez zbocza.
// Mniej znaczyłoby, że wolne miganie (np. 2 s świeci, 2 s nie) w części okien
// wygląda jak praca, a w części jak wyłączenie.
#define PWR_LED_QUIET_WINDOWS    4

enum PwrState : uint8_t { PWR_UNKNOWN = 0, PWR_RUNNING, PWR_SLEEP, PWR_OFF };
enum PwrAction : uint8_t { PWR_ACT_NONE = 0, PWR_ACT_SHORT, PWR_ACT_LONG };

struct PwrLogic {
  bool     closedLoop;     // FEATURE_PWRLED: stan z diody, nie z założeń
  PwrState state;          // co (naszym zdaniem) robi maszyna — ostatni odczyt
  PwrState stable;         // stan, który utrzymał się PWR_STABLE_MS
  uint32_t stateSince;     // kiedy `state` ostatnio się zmienił
  uint32_t steadyAt;       // ostatni obieg, w którym stan był pewny

  PwrState desired;        // zamiar ze zbocza zapłonu (UNKNOWN = brak)
  uint32_t desiredAt;      // kiedy ustawiony albo ostatnio naciśnięty
  uint8_t  intentPulses;   // impulsy wysłane dla tego zamiaru

  bool     ignKnown;       // czy zapłon jest już potwierdzony
  bool     ignLevel;       // ostatni potwierdzony poziom
  bool     ignCand;        // kandydat oczekujący na potwierdzenie
  uint32_t ignCandAt;

  uint32_t ignOffAt;       // początek odliczania do eskalacji
  bool     escDue;         // minęło PWR_OFF_AFTER_MS (zatrzask — patrz pwrStep)
  bool     offDone;        // eskalacja zakończona (LONG wysłany / już OFF)
  bool     escShortSent;   // eskalacja wysłała SHORT na działającą maszynę
  uint32_t escShortAt;

  bool     settling;       // trwa cisza po impulsie
  uint32_t settleUntil;
  bool     grace;          // trwa okno usypiania po SHORT na pracującą
  uint32_t graceAt;
};

// Stan początkowy. `now` = millis() w setup(): liczniki startują od chwili
// startu płytki, a nie od zera (ważne dla testu z czasem tuż przed
// przepełnieniem; na płytce millis() w setup() i tak jest bliskie zera).
inline void pwrInit(PwrLogic& s, bool closedLoop, uint32_t now) {
  s = PwrLogic();
  s.closedLoop = closedLoop;
  s.stateSince = now;
  s.steadyAt   = now;
  s.ignCandAt  = now;
}

// Pętla otwarta (bez diody): stan to nasze założenie po własnym impulsie,
// więc od razu jest „stabilny”. W pętli zamkniętej stan mówi wyłącznie
// dioda — tu nic nie zmieniamy.
inline void pwrAssume(PwrLogic& s, PwrState st, uint32_t now) {
  if (s.closedLoop) return;
  s.state = st;
  s.stable = st;
  s.stateSince = now;
}

// Odczyt diody (pętla zamknięta): wołać po każdym zamkniętym oknie.
inline void pwrObserve(PwrLogic& s, PwrState seen, uint32_t now) {
  if (seen == s.state) return;
  s.state = seen;
  s.stateSince = now;
}

// Stan, który naprawdę się utrzymał. Samo `stable == state` nie wystarcza:
// `stable` zmienia się dopiero po PWR_STABLE_MS, więc gdy odczyt skacze
// (RUNNING, SLEEP, RUNNING…), przy każdym powrocie do starej wartości oba
// pola są równe, choć stan trwa ułamek sekundy. Na tym eskalacja wysyłała
// SHORT do maszyny w S3 i budziła ją co godzinę na postoju.
inline bool pwrSteady(const PwrLogic& s, uint32_t now) {
  return s.state != PWR_UNKNOWN && s.state == s.stable &&
         (uint32_t)(now - s.stateSince) >= PWR_STABLE_MS;
}

// Koniec impulsu: od teraz cisza PWR_SETTLE_MS, maszyna wykonuje przejście.
inline void pwrPulseDone(PwrLogic& s, uint32_t now) {
  s.settling = true;
  s.settleUntil = now + PWR_SETTLE_MS;   // przepełnienie tu jest w porządku
}

// Odliczanie do eskalacji od `now`, eskalacja znów możliwa.
inline void pwrArmEscalation(PwrLogic& s, uint32_t now) {
  s.ignOffAt = now;
  s.escDue = false;
  s.offDone = false;
  s.escShortSent = false;
}

inline void pwrSetIntent(PwrLogic& s, PwrState want, uint32_t now) {
  s.desired = want;
  s.desiredAt = now;
  s.intentPulses = 0;
}

// Krótkie wciśnięcie. Na działającą maszynę otwiera okno usypiania hosta.
inline PwrAction pwrShort(PwrLogic& s, uint32_t now, PwrState expect) {
  if (s.state == PWR_RUNNING) {
    s.grace = true;
    s.graceAt = now;
  }
  pwrAssume(s, expect, now);
  return PWR_ACT_SHORT;
}

// Zamiar w pętli otwartej: jak dawniej jednorazowy (nie ma czym sprawdzić
// skutku), tylko nie w oknie usypiania — w nim host może jeszcze wykonywać
// poprzednie wciśnięcie.
inline PwrAction pwrIntentOpen(PwrLogic& s, uint32_t now) {
  const PwrState want = s.desired;
  if (want == s.state || (want == PWR_SLEEP && s.state == PWR_OFF)) {
    s.desired = PWR_UNKNOWN;
    return PWR_ACT_NONE;
  }
  if (s.grace) return PWR_ACT_NONE;
  s.desired = PWR_UNKNOWN;
  return pwrShort(s, now, want);
}

// Zamiar w pętli zamkniętej: skutek widać na diodzie.
inline PwrAction pwrIntentClosed(PwrLogic& s, uint32_t now, bool steady) {
  const PwrState want = s.desired;

  // Cel osiągnięty. W oknie usypiania zamiar RUNNING czeka dalej: zapłon
  // wrócił, ale host po wcześniejszym SHORT może jeszcze zasnąć.
  if (steady && (s.state == want || (want == PWR_SLEEP && s.state == PWR_OFF))) {
    if (!s.grace) s.desired = PWR_UNKNOWN;
    return PWR_ACT_NONE;
  }
  if (s.intentPulses >= PWR_INTENT_PULSES ||
      (!s.grace && (uint32_t)(now - s.desiredAt) >= PWR_INTENT_TTL_MS)) {
    s.desired = PWR_UNKNOWN;
    return PWR_ACT_NONE;
  }

  if (want == PWR_SLEEP) {
    // Usypiamy tylko pewnie pracującą maszynę, najwyżej raz na zamiar i nie
    // w oknie usypiania. Gdy host po naszym SHORT dalej pracuje (zignorował
    // albo człowiek go obudził), nie naciskamy drugi raz — po 2 h zrobi to
    // eskalacja, z własnym rytmem ponowień.
    if (s.intentPulses) {
      if (!s.grace) s.desired = PWR_UNKNOWN;
      return PWR_ACT_NONE;
    }
    if (!steady || s.state != PWR_RUNNING || s.grace) return PWR_ACT_NONE;
  } else {
    // RUNNING: maszyna pewnie w S3 / wyłączona → wciskamy od razu. Stan
    // w ruchu → czekamy, aż się ustali, ale nie bez końca (PWR_UNSTEADY_MS).
    if (!steady) {
      if (s.state == PWR_RUNNING) return PWR_ACT_NONE;
      if ((uint32_t)(now - s.steadyAt) < PWR_UNSTEADY_MS) return PWR_ACT_NONE;
      if ((uint32_t)(now - s.desiredAt) < PWR_UNSTEADY_MS) return PWR_ACT_NONE;
    }
  }
  s.intentPulses++;
  s.desiredAt = now;
  return pwrShort(s, now, want);
}

// Jeden obieg loop() (poza trwającym impulsem). `ign` = zdebouncowany zapłon.
// Zwraca impuls do wykonania; sketch po jego końcu woła pwrPulseDone().
inline PwrAction pwrStep(PwrLogic& s, uint32_t now, bool ign) {
  // 1. Stabilny stan i wybudzenie z zewnątrz. Zbocze, nie poziom: gdyby
  //    każdy obieg z RUNNING przy zgaszonym zapłonie zerował odliczanie,
  //    działająca maszyna nigdy nie doczekałaby się eskalacji.
  if (s.state != s.stable && (uint32_t)(now - s.stateSince) >= PWR_STABLE_MS) {
    const PwrState prev = s.stable;
    s.stable = s.state;
    if (s.stable == PWR_RUNNING && prev != PWR_RUNNING && s.ignKnown && !s.ignLevel) {
      // Ktoś obudził maszynę przy zgaszonym zapłonie (człowiek przyciskiem,
      // powrót zasilania). Bez tego po wybudzeniu z OFF komputer już nigdy
      // nie wróciłby do OFF — offDone kasowało tylko zbocze zapłonu.
      pwrArmEscalation(s, now);
    }
  }
  const bool steady = pwrSteady(s, now);
  if (steady) s.steadyAt = now;

  // 1a. Koniec okna usypiania: czas minął albo (tylko z diodą) host już
  //     wykonał wciśnięcie. W pętli otwartej stan „uśpiona” to nasze
  //     założenie z chwili impulsu, więc tam decyduje wyłącznie czas.
  if (s.grace && ((uint32_t)(now - s.graceAt) >= PWR_SUSPEND_GRACE_MS ||
                  (s.closedLoop && steady && s.state != PWR_RUNNING))) {
    s.grace = false;
  }

  // 2. Potwierdzenie zapłonu. DEBOUNCE_MS (50 ms) wystarcza do raportowania
  //    IGN:, ale nie do usypiania komputera — zapad przy rozruchu potrafi
  //    zgasić ACC na chwilę. Stąd osobne, dłuższe potwierdzenie.
  if (ign != s.ignCand) { s.ignCand = ign; s.ignCandAt = now; }
  if (!s.ignKnown) {
    if ((uint32_t)(now - s.ignCandAt) >= PWR_IGN_CONFIRM_MS) {
      s.ignLevel = ign;
      s.ignKnown = true;
      if (!ign) pwrArmEscalation(s, now);
    }
    return PWR_ACT_NONE;  // pierwsza obserwacja po starcie NIE wywołuje akcji
  }
  if (s.ignCand != s.ignLevel && (uint32_t)(now - s.ignCandAt) >= PWR_IGN_CONFIRM_MS) {
    s.ignLevel = s.ignCand;
    if (s.ignLevel) {
      pwrSetIntent(s, PWR_RUNNING, now);
    } else {
      pwrArmEscalation(s, now);
      pwrSetIntent(s, PWR_SLEEP, now);
    }
  }

  // 3. Po dwóch godzinach postoju S3 przestaje się opłacać. Zatrzask, a nie
  //    samo porównanie: różnica now - ignOffAt przekręca się po ~49,7 dnia.
  if (!s.ignLevel && !s.escDue && (uint32_t)(now - s.ignOffAt) >= PWR_OFF_AFTER_MS) {
    s.escDue = true;
  }

  // 4. Cisza po impulsie — maszyna jeszcze wykonuje przejście.
  if (s.settling) {
    if ((int32_t)(now - s.settleUntil) < 0) return PWR_ACT_NONE;
    s.settling = false;
  }

  // 5. Zamiar ze zbocza zapłonu ma pierwszeństwo przed eskalacją.
  if (s.desired != PWR_UNKNOWN) {
    return s.closedLoop ? pwrIntentClosed(s, now, steady) : pwrIntentOpen(s, now);
  }

  // 6. Eskalacja. Tylko na stan, który naprawdę się utrzymał, i nie w oknie
  //    usypiania. Twarde wyłączenie TYLKO uśpionej maszyny — 5 s na
  //    przycisku przy pracującym Linuksie to utrata danych.
  if (!s.ignLevel && s.escDue && !s.offDone) {
    if (!steady) return PWR_ACT_NONE;   // stan w ruchu albo nieznany — czekamy
    if (s.grace) return PWR_ACT_NONE;   // host może jeszcze usypiać
    switch (s.state) {
      case PWR_SLEEP:
        s.offDone = true;
        pwrAssume(s, PWR_OFF, now);
        return PWR_ACT_LONG;
      case PWR_OFF:
        s.offDone = true;          // już wyłączona — nie ma czego eskalować
        return PWR_ACT_NONE;
      case PWR_RUNNING:
        // Najpierw zwykłe S3 (host: acpid → bcm-power-toggle.sh). LONG
        // przyjdzie później, gdy dioda potwierdzi S3.
        if (s.escShortSent && (uint32_t)(now - s.escShortAt) < PWR_ESC_RETRY_MS) {
          return PWR_ACT_NONE;
        }
        s.escShortSent = true;
        s.escShortAt = now;
        return pwrShort(s, now, PWR_SLEEP);
      default:
        // UNKNOWN: pętla otwarta po resecie płytki nie wie, czy maszyna
        // pracuje — na ślepo nie wyłączamy.
        return PWR_ACT_NONE;
    }
  }
  return PWR_ACT_NONE;
}

// --- dekoder diody panelu (FEATURE_PWRLED) -----------------------------------
//
// Świeci ciągle = praca, miga = S3, zgaszona = wyłączona. Rytm migania M910q
// w S3 nie jest znany, więc dekoder nie zakłada konkretnej częstotliwości:
//   - dwa zbocza bez przerwy PWR_LED_QUIET_WINDOWS okien → SLEEP (miga);
//   - PWR_LED_QUIET_WINDOWS okien bez zbocza → RUNNING albo OFF wg poziomu;
//   - pojedyncze zbocze po ciszy (np. LONG gasi diodę, start ją zapala) nie
//     zmienia stanu, dopóki sprawa się nie wyjaśni.
// Dawny dekoder patrzył na jedno okno: dwa zbocza = S3, inaczej poziom na
// końcu okna. Miganie wolniejsze niż ~1 Hz daje w oknie 1,6 s raz jedno, raz
// dwa zbocza, więc S3 skakało między SLEEP a RUNNING/OFF.

struct PwrLed {
  bool     primed;         // pierwszy odczyt już był (nie jest zboczem)
  bool     lit;            // ostatni odczyt
  uint8_t  edges;          // zbocza w bieżącym oknie
  uint8_t  quiet;          // kolejne zamknięte okna bez zbocza
  uint8_t  burst;          // zbocza od ostatniej ciszy
  PwrState decoded;
  uint32_t windowAt;       // początek bieżącego okna
};

inline void pwrLedInit(PwrLed& d, uint32_t now) {
  d = PwrLed();
  d.windowAt = now;
}

// Wołać w każdym obiegu z surowym poziomem diody (true = świeci). Zwraca
// true, gdy zamknęło się okno — wtedy d.decoded jest świeże.
inline bool pwrLedSample(PwrLed& d, bool lit, uint32_t now) {
  if (!d.primed) {
    d.primed = true;
    d.lit = lit;
  } else if (lit != d.lit) {
    d.lit = lit;
    if (d.edges < 250) d.edges++;
  }
  if ((uint32_t)(now - d.windowAt) < PWR_LED_WINDOW_MS) return false;
  d.windowAt = now;

  if (d.edges) {
    d.quiet = 0;
    d.burst = (uint8_t)((d.burst + d.edges > 250) ? 250 : d.burst + d.edges);
    if (d.burst >= 2) d.decoded = PWR_SLEEP;
  } else {
    if (d.quiet < 250) d.quiet++;
    if (d.quiet >= PWR_LED_QUIET_WINDOWS) {
      d.burst = 0;
      d.decoded = d.lit ? PWR_RUNNING : PWR_OFF;
    }
  }
  d.edges = 0;
  return true;
}
