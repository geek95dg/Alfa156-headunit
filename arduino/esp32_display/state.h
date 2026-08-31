/*
 * BCM v8.5 — stan wejść i wybór ekranu dla wyświetlacza 1,8" (ESP32-S3)
 *
 * Dziesięć wejść z transoptorów PC817 (INPUT_PULLUP, stan aktywny LOW):
 * cztery kontrolki na pasmo górne ekranu 1 i sześć czujników otwarcia
 * nadwozia na ekran 2. Wszystkie idą wprost z auta, więc działają także
 * wtedy, gdy M910q jeszcze wstaje albo już śpi.
 *
 * CZYSTY C++ — czas jest WSTRZYKIWANY (`now_ms` z millis()), żadnego
 * Arduino, więc debounce i wybór ekranu da się przetestować na hoście
 * bez płytki (test/test_host.cpp).
 *
 * Odejmowanie czasu robimy zawsze na uint32_t (`now - since`), więc
 * przekręcenie millis() po 49 dniach niczego nie psuje.
 */
#pragma once

#include <stdint.h>

enum {
    INPUT_DEBOUNCE_MS = 30,     // drgania styków i krańcówek drzwi
    BCM_TIMEOUT_MS    = 5000    // brak linii przez tyle = BCM offline
};

// Kolejność JEST kontraktem: pierwsze cztery odpowiadają TELLTALES[] z
// assets.h (abs, brake, airbag, immo), sześć kolejnych — PANELS[]
// (bonnet, fl, fr, rl, rr, trunk). Dzięki temu indeks sprite'a to po
// prostu id - TELLTALE_FIRST / id - PANEL_FIRST.
enum InputId : uint8_t {
    IN_ABS = 0,
    IN_BRAKE,
    IN_AIRBAG,
    IN_IMMO,
    IN_BONNET,
    IN_DOOR_FL,
    IN_DOOR_FR,
    IN_DOOR_RL,
    IN_DOOR_RR,
    IN_TRUNK,
    INPUT_COUNT
};

enum {
    TELLTALE_FIRST = IN_ABS,
    TELLTALE_COUNT = 4,
    PANEL_FIRST    = IN_BONNET,
    PANEL_COUNT    = 6
};

enum Screen : uint8_t {
    SCREEN_NOW_PLAYING = 0,   // ekran 1 — metadane + kontrolki
    SCREEN_BODY_OPEN   = 1    // ekran 2 — otwarte nadwozie
};

struct InputState {
    bool     stable[INPUT_COUNT];      // stan po odfiltrowaniu drgań
    bool     raw[INPUT_COUNT];         // ostatni surowy odczyt
    uint32_t changed_at[INPUT_COUNT];  // kiedy surowy odczyt ostatnio drgnął
};

inline void inputs_init(InputState *s, uint32_t now_ms)
{
    if (s == nullptr) {
        return;
    }
    for (uint8_t i = 0; i < INPUT_COUNT; i++) {
        s->stable[i] = false;
        s->raw[i] = false;
        s->changed_at[i] = now_ms;
    }
}

// Stan początkowy wprost z pinów, z pominięciem debounce'u. W chwili startu
// nie ma jeszcze czego odfiltrowywać, a pierwsza klatka ma od razu mówić
// prawdę — otwarty bagażnik nie może czekać 30 ms na własny ekran.
inline void inputs_preset(InputState *s, const bool *active, uint32_t now_ms)
{
    if (s == nullptr || active == nullptr) {
        return;
    }
    for (uint8_t i = 0; i < INPUT_COUNT; i++) {
        s->raw[i] = active[i];
        s->stable[i] = active[i];
        s->changed_at[i] = now_ms;
    }
}

// `active[i]` to surowy odczyt: true = sygnał aktywny (GPIO w stanie LOW).
// Zwraca MASKĘ wejść, których zdebouncowany stan właśnie się zmienił —
// renderer przerysowuje dokładnie te kontrolki i panele, nic więcej.
inline uint32_t inputs_update(InputState *s, const bool *active, uint32_t now_ms)
{
    if (s == nullptr || active == nullptr) {
        return 0;
    }
    uint32_t changed = 0;
    for (uint8_t i = 0; i < INPUT_COUNT; i++) {
        if (active[i] != s->raw[i]) {
            s->raw[i] = active[i];
            s->changed_at[i] = now_ms;      // drgnęło — licznik od nowa
        }
        if (s->raw[i] != s->stable[i] &&
            (now_ms - s->changed_at[i]) >= INPUT_DEBOUNCE_MS) {
            s->stable[i] = s->raw[i];
            changed |= (1UL << i);
        }
    }
    return changed;
}

inline bool input_active(const InputState *s, uint8_t id)
{
    if (s == nullptr || id >= INPUT_COUNT) {
        return false;
    }
    return s->stable[id];
}

// Czy cokolwiek w nadwoziu jest otwarte (maska, czworo drzwi, klapa).
inline bool inputs_any_open(const InputState *s)
{
    if (s == nullptr) {
        return false;
    }
    for (uint8_t i = 0; i < PANEL_COUNT; i++) {
        if (s->stable[PANEL_FIRST + i]) {
            return true;
        }
    }
    return false;
}

// Zasłonięcie STAŁE: dopóki cokolwiek jest otwarte, ekran 2 przykrywa
// ekran 1 w całości — bez timeoutu, bez przełączania naprzemiennego.
// Kontrolki usterek (ABS, hamulec, poduszka, immo) NIE przełączają ekranu.
inline Screen screen_select(const InputState *s)
{
    return inputs_any_open(s) ? SCREEN_BODY_OPEN : SCREEN_NOW_PLAYING;
}

// Czy BCM się odzywa. Dopóki nie przyszła ani jedna linia (`seen` = false),
// jest offline — także zaraz po starcie, zanim M910q wstanie.
inline bool bcm_online(bool seen, uint32_t last_rx_ms, uint32_t now_ms)
{
    if (!seen) {
        return false;
    }
    return (now_ms - last_rx_ms) < BCM_TIMEOUT_MS;
}
