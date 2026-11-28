// press_logic.h — jeden pod drabinki rezystorowej: odczyt → zdarzenie.
//
// Czysta logika (bez Arduino.h), żeby dało się ją przetestować na hoście
// (arduino/rotary_encoder/test/test_press_logic.cpp, uruchamiany z pytest).
//
// Wejście: numer przycisku odczytany z ADC w tej chwili (-1 = spoczynek)
// i czas w ms (millis()). Wyjście: co najwyżej jedno zdarzenie na krok.
//
// Zasady (jak dotąd w rotary_encoder.ino, plus długie naciśnięcie):
// - odczyt musi być taki sam przez `confirmMs`, zanim cokolwiek się stanie
//   (zakłócenia i przejścia drabinki nie wysyłają klawiszy);
// - między dwoma RÓŻNYMI przyciskami wymagany jest powrót do spoczynku;
// - przycisk zwykły: zdarzenie PRESS od razu po potwierdzeniu wciśnięcia;
// - przycisk z długim naciśnięciem (`holdable`): nic przy wciśnięciu;
//   trzymany `longMs` → LONG (raz), puszczony wcześniej → SHORT. Po LONG
//   puszczenie nie daje już SHORT.
//
// Wszystkie porównania czasu jako różnice `now - t` (unsigned) — odporne na
// przepełnienie millis() po ~49,7 dnia.
#pragma once
#include <stdint.h>

enum PressEvent : uint8_t {
  PRESS_NONE  = 0,
  PRESS_DOWN  = 1,   // zwykły przycisk wciśnięty
  PRESS_SHORT = 2,   // przycisk „holdable” puszczony przed longMs
  PRESS_LONG  = 3,   // przycisk „holdable” trzymany longMs
};

struct PressState {
  int8_t        reported;   // stan przyjęty (-1 = spoczynek)
  int8_t        candidate;  // odczyt czekający na potwierdzenie
  unsigned long candAt;     // od kiedy candidate jest niezmienny
  unsigned long pressAt;    // kiedy przyjęto wciśnięcie (holdable)
  bool          longFired;  // LONG już wysłane dla tego wciśnięcia
};

inline void pressInit(PressState &s, unsigned long now) {
  s.reported = -1;
  s.candidate = -1;
  s.candAt = now;
  s.pressAt = now;
  s.longFired = false;
}

// Jeden krok. `btn` — odczyt teraz (-1 = spoczynek); `holdable(b)` mówi,
// czy przycisk b ma długie naciśnięcie. Zwraca zdarzenie, a w `which`
// numer przycisku, którego dotyczy (bez zdarzenia: -1).
template <typename HoldFn>
inline PressEvent pressStep(PressState &s, int8_t btn, unsigned long now,
                            unsigned long confirmMs, unsigned long longMs,
                            HoldFn holdable, int8_t &which) {
  which = -1;

  // Trzymany przycisk „holdable”: LONG mija niezależnie od debounce'u
  // kolejnych odczytów (ten sam stan, nic się nie zmienia).
  if (s.reported >= 0 && holdable(s.reported) && !s.longFired
      && btn == s.reported && (now - s.pressAt) >= longMs) {
    s.longFired = true;
    which = s.reported;
    return PRESS_LONG;
  }

  if (btn != s.candidate) {          // odczyt się zmienił — licz od nowa
    s.candidate = btn;
    s.candAt = now;
    return PRESS_NONE;
  }
  if ((now - s.candAt) < confirmMs) return PRESS_NONE;   // jeszcze niestabilny
  if (btn == s.reported) return PRESS_NONE;              // nic nowego

  if (btn >= 0 && s.reported >= 0) {
    // Przycisk → inny przycisk bez spoczynku: artefakt drabinki. Czekamy
    // na rozwarcie (reported zostaje, więc blokada trwa do -1).
    return PRESS_NONE;
  }

  int8_t prev = s.reported;
  s.reported = btn;

  if (btn >= 0) {                    // wciśnięcie
    if (holdable(btn)) {
      s.pressAt = s.candAt;          // liczone od początku stabilnego odczytu
      s.longFired = false;
      return PRESS_NONE;
    }
    which = btn;
    return PRESS_DOWN;
  }

  // puszczenie (btn == -1)
  if (prev >= 0 && holdable(prev) && !s.longFired) {
    which = prev;
    return PRESS_SHORT;
  }
  return PRESS_NONE;
}
