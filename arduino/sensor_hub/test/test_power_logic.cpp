/*
 * BCM v8.5 — testy hosta dla logiki przycisku zasilania (sensor_hub)
 *
 * Kompilacja i uruchomienie BEZ Arduino i bez płytki:
 *
 *   make -C arduino sensor_hub-test
 *   # albo ręcznie:
 *   g++ -std=c++17 -Wall -Wextra -Werror -o test_power_logic test_power_logic.cpp && ./test_power_logic
 *
 * Sprawdzamy power_logic.h na symulowanej maszynie: zapłon, impulsy na
 * przycisk, fizyczna dioda panelu (z dekoderem pwrLedSample, różne rytmy
 * migania w S3), host, który usypia się dopiero po zatrzymaniu BCM, i upływ
 * czasu — także przez przepełnienie millis() (2^32 ms ≈ 49,7 dnia) i po
 * ponad 24,8 dnia bez żadnego impulsu. Pętla sim_loop() woła logikę w tej
 * samej kolejności co handlePwrButton() w sketchu. Na stole zostają:
 * przekaźnik, Serial i PRAWDZIWY rytm diody M910q w S3 (model tylko go
 * zakłada; test_flicker_* i test_*_undecodable_led sprawdzają, co się dzieje,
 * gdy dekoder go nie rozpozna).
 */
#ifdef NDEBUG
#error "Testy stoją na assert() — nie kompiluj z NDEBUG."
#endif

#include <cassert>
#include <cstdint>
#include <cstdio>

#include "../power_logic.h"

static int g_checks = 0;

#define CHECK(cond)                                                            \
    do {                                                                       \
        g_checks++;                                                            \
        assert(cond);                                                          \
    } while (0)

static const uint32_t SEC = 1000UL;
static const uint32_t MIN = 60UL * SEC;
static const uint32_t HOUR = 60UL * MIN;
static const uint32_t DAY = 24UL * HOUR;
static const uint32_t WRAP = 0xFFFFFFFFUL;     // millis() tuż przed przepełnieniem

static const uint32_t PULSE_SHORT_MS = 250;     // jak PWR_PULSE_SHORT_MS w sketchu
static const uint32_t PULSE_LONG_MS = 5000;     // jak PWR_PULSE_LONG_MS

// --- model: M910q + pętla loop() sensor_hub -----------------------------------

struct Sim {
    PwrLogic s;
    PwrLed led;
    uint32_t now;
    bool ign;               // zdebouncowany zapłon (inIgn.state)
    PwrState pc;            // prawdziwy stan maszyny
    uint32_t pcSince;       // od kiedy (faza migania diody w S3)
    bool closed;            // FEATURE_PWRLED
    bool refuseSleep;       // host nie zasypia na SHORT (np. trwa start)
    uint32_t suspendDelay;  // host zasypia tyle ms po SHORT (stop BCM, sleep 1)
    bool sleepPending;      // trwa bcm-power-toggle.sh
    uint32_t sleepAt;
    int missPresses;        // tyle kolejnych wciśnięć przekaźnik „gubi”
    uint32_t blinkMs;       // okres migania diody w S3
    bool decodeFlicker;     // najgorszy przypadek: wyjście dekodera w S3
                            // skacze SLEEP/RUNNING co okno (rytm nie do odczytania)
    unsigned flip;
    bool pulsing;
    uint32_t pulseUntil;
    int shorts;
    int longs;
    int longsWhileRunning;  // LONG przy pracującym systemie = utrata danych
    int doublePress;        // SHORT w trakcie bcm-power-toggle.sh (drugi suspend)
    int wakesWhileParked;   // SHORT, który obudził maszynę przy zgaszonym zapłonie
    int windowsInS3;        // zamknięte okna diody w S3 (po wejściu w stan)...
    int windowsInS3NotSleep;  // ...i ile z nich dekoder NIE odczytał jako SLEEP
    PwrAction lastAction;
};

static void sim_set_pc(Sim &m, PwrState pc)
{
    if (pc != m.pc) {
        m.pc = pc;
        m.pcSince = m.now;
    }
    if (pc != PWR_RUNNING) {
        m.sleepPending = false;
    }
}

static void sim_init(Sim &m, bool closed, uint32_t boot, PwrState pc, bool ign)
{
    m = Sim();
    m.closed = closed;
    m.now = boot;
    m.pc = pc;
    m.pcSince = boot;
    m.ign = ign;
    m.blinkMs = 2000;       // ~0,5 Hz; inne okresy w test_blink_rates_*
    pwrInit(m.s, closed, boot);
    pwrLedInit(m.led, boot);
}

// Fizyczna dioda: świeci = praca, miga = S3, ciemna = wyłączona.
static bool led_lit(const Sim &m)
{
    switch (m.pc) {
    case PWR_RUNNING:
        return true;
    case PWR_SLEEP:
        return ((uint32_t)(m.now - m.pcSince) % m.blinkMs) < m.blinkMs / 2;
    default:
        return false;
    }
}

// Reakcja systemu na krótkie wciśnięcie (acpid → bcm-power-toggle.sh:
// stop bcm-headunit, sleep 1, systemctl suspend — ZAWSZE suspend).
static void sim_short(Sim &m)
{
    m.shorts++;
    if (m.missPresses > 0) {
        m.missPresses--;
        return;
    }
    switch (m.pc) {
    case PWR_RUNNING:
        if (m.sleepPending) {
            m.doublePress++;    // drugi skrypt: po wybudzeniu znów suspend
            return;
        }
        if (m.refuseSleep) {
            return;
        }
        if (m.suspendDelay) {
            m.sleepPending = true;
            m.sleepAt = m.now + m.suspendDelay;
        } else {
            sim_set_pc(m, PWR_SLEEP);
        }
        break;
    case PWR_SLEEP:
    case PWR_OFF:
        if (!m.ign) {
            m.wakesWhileParked++;
        }
        sim_set_pc(m, PWR_RUNNING);
        break;
    default:
        break;
    }
}

// Jeden obieg loop() — kolejność jak w handlePwrButton().
static void sim_loop(Sim &m)
{
    if (m.sleepPending && (int32_t)(m.now - m.sleepAt) >= 0) {
        sim_set_pc(m, PWR_SLEEP);
    }
    if (m.pulsing) {
        if ((int32_t)(m.now - m.pulseUntil) >= 0) {
            m.pulsing = false;
            pwrPulseDone(m.s, m.now);
        }
        return;
    }
    if (m.closed && pwrLedSample(m.led, led_lit(m), m.now)) {
        PwrState seen = m.led.decoded;
        if (m.decodeFlicker && m.pc == PWR_SLEEP) {
            seen = (m.flip++ & 1U) ? PWR_SLEEP : PWR_RUNNING;
        }
        // Po wejściu w S3 dekoder potrzebuje dwóch zboczy (pełny okres
        // migania) i okna na ich zliczenie.
        if (m.pc == PWR_SLEEP &&
            (uint32_t)(m.now - m.pcSince) >= m.blinkMs + 2 * PWR_LED_WINDOW_MS) {
            m.windowsInS3++;
            if (seen != PWR_SLEEP) {
                m.windowsInS3NotSleep++;
            }
        }
        pwrObserve(m.s, seen, m.now);
    }
    const PwrAction a = pwrStep(m.s, m.now, m.ign);
    if (a == PWR_ACT_SHORT) {
        sim_short(m);
        m.pulsing = true;
        m.pulseUntil = m.now + PULSE_SHORT_MS;
    } else if (a == PWR_ACT_LONG) {
        m.longs++;
        if (m.pc == PWR_RUNNING) {
            m.longsWhileRunning++;
        }
        sim_set_pc(m, PWR_OFF);
        m.pulsing = true;
        m.pulseUntil = m.now + PULSE_LONG_MS;
    }
    if (a != PWR_ACT_NONE) {
        m.lastAction = a;
    }
}

// `ms` < 2^32 - dt; czas w modelu przekręca się razem z m.now.
static void sim_run(Sim &m, uint32_t ms, uint32_t dt = 50)
{
    for (uint32_t t = 0; t < ms; t += dt) {
        sim_loop(m);
        m.now += dt;
    }
}

// Zapłon wyłączony od startu, maszyna w S3, logika zsynchronizowana.
static void parked_in_s3(Sim &m, bool closed, uint32_t boot)
{
    sim_init(m, closed, boot, PWR_SLEEP, true);
    sim_run(m, 30 * SEC);               // start z zapłonem: pierwsza obserwacja
    sim_set_pc(m, PWR_RUNNING);         // (kierowca jechał; maszyna pracuje)
    sim_run(m, 30 * SEC);
    m.ign = false;
    sim_run(m, 30 * SEC);               // zbocze → SHORT → S3
    CHECK(m.pc == PWR_SLEEP);
}

// --- zwykły cykl zapłonu ------------------------------------------------------

static void test_ignition_cycle(void)
{
    Sim m;
    sim_init(m, true, 1000, PWR_RUNNING, true);
    sim_run(m, 30 * SEC);
    CHECK(m.shorts == 0);               // pierwsza obserwacja nie wywołuje akcji

    m.ign = false;
    sim_run(m, 1 * SEC);
    CHECK(m.shorts == 0);               // jeszcze bez potwierdzenia (2 s)
    sim_run(m, 20 * SEC);
    CHECK(m.shorts == 1);
    CHECK(m.lastAction == PWR_ACT_SHORT);
    CHECK(m.pc == PWR_SLEEP);

    m.ign = true;
    sim_run(m, 20 * SEC);
    CHECK(m.shorts == 2);
    CHECK(m.pc == PWR_RUNNING);
    CHECK(m.longs == 0);
}

static void test_first_observation_takes_no_action(void)
{
    // Reset płytki (watchdog) przy włączonym zapłonie i uśpionej maszynie:
    // firmware nie wie, kto ją uśpił — nie naciska.
    Sim m;
    sim_init(m, true, 1000, PWR_SLEEP, true);
    sim_run(m, 5 * MIN);
    CHECK(m.shorts == 0 && m.longs == 0);
}

static void test_cranking_dip_is_ignored(void)
{
    Sim m;
    sim_init(m, true, 1000, PWR_RUNNING, true);
    sim_run(m, 30 * SEC);
    m.ign = false;                      // zapad przy rozruchu
    sim_run(m, 1500);
    m.ign = true;
    sim_run(m, 1 * MIN);
    CHECK(m.shorts == 0);
    CHECK(m.pc == PWR_RUNNING);
}

// --- eskalacja do OFF -----------------------------------------------------------

static void test_escalation_from_sleep(void)
{
    Sim m;
    parked_in_s3(m, true, 1000);
    CHECK(m.shorts == 1);
    sim_run(m, 2 * HOUR - 2 * MIN);
    CHECK(m.longs == 0);
    sim_run(m, 3 * MIN);
    CHECK(m.longs == 1);
    CHECK(m.lastAction == PWR_ACT_LONG);
    CHECK(m.pc == PWR_OFF);
    sim_run(m, 5 * HOUR, 1000);         // raz wysłany LONG się nie powtarza
    CHECK(m.longs == 1 && m.shorts == 1);
}

// Błąd b: ręcznie obudzona maszyna przy zgaszonym zapłonie nie może dostać
// LONG (5 s twardego wyłączenia) w trakcie pracy Linuksa.
static void test_no_long_while_running(void)
{
    Sim m;
    parked_in_s3(m, true, 1000);
    sim_run(m, 1 * HOUR, 1000);
    sim_set_pc(m, PWR_RUNNING);         // ktoś nacisnął przycisk ręcznie
    sim_run(m, 90 * MIN, 1000);         // 2,5 h od zgaszenia
    CHECK(m.longs == 0);
    CHECK(m.shorts == 1);
    CHECK(m.pc == PWR_RUNNING);

    // 2 h od wybudzenia: najpierw S3 (SHORT), LONG dopiero po potwierdzeniu.
    sim_run(m, 31 * MIN, 1000);
    CHECK(m.shorts == 2);
    CHECK(m.longs == 1);
    CHECK(m.longsWhileRunning == 0);
    CHECK(m.pc == PWR_OFF);
}

static void test_running_host_that_refuses_sleep(void)
{
    // Maszyna pracuje przy zgaszonym zapłonie od startu płytki i nie
    // zasypia na SHORT. Nigdy LONG; ponowienie SHORT co 30 min, nie częściej.
    Sim m;
    sim_init(m, true, 1000, PWR_RUNNING, false);
    m.refuseSleep = true;
    sim_run(m, 2 * HOUR - 1 * MIN);
    CHECK(m.shorts == 0);
    sim_run(m, 2 * MIN);
    CHECK(m.shorts == 1);
    sim_run(m, 29 * MIN);
    CHECK(m.shorts == 1);
    sim_run(m, 2 * MIN);
    CHECK(m.shorts == 2);
    sim_run(m, 5 * HOUR, 1000);
    CHECK(m.longs == 0 && m.longsWhileRunning == 0);
    CHECK(m.shorts <= 2 + 10 + 1);
}

// Błąd c: po wybudzeniu z OFF przy zgaszonym zapłonie eskalacja wraca.
static void test_escalation_rearms_after_wake_from_off(void)
{
    Sim m;
    parked_in_s3(m, true, 1000);
    sim_run(m, 2 * HOUR + 2 * MIN, 1000);
    CHECK(m.longs == 1 && m.pc == PWR_OFF);

    sim_set_pc(m, PWR_RUNNING);         // ręczne włączenie
    sim_run(m, 1 * HOUR, 1000);
    CHECK(m.longs == 1 && m.shorts == 1);
    sim_run(m, 1 * HOUR + 2 * MIN, 1000);
    CHECK(m.shorts == 2);               // S3...
    CHECK(m.longs == 2);                // ...potem OFF
    CHECK(m.longsWhileRunning == 0);
    CHECK(m.pc == PWR_OFF);
}

static void test_ignition_on_cancels_escalation(void)
{
    Sim m;
    sim_init(m, true, 1000, PWR_RUNNING, false);
    // 2 h liczone od chwili, gdy dioda stabilnie pokazała pracę (~16 s po
    // starcie płytki: 4 okna ciszy + PWR_STABLE_MS).
    sim_run(m, 2 * HOUR + 20 * SEC);    // eskalacja: SHORT na pracującą
    CHECK(m.shorts == 1 && m.pc == PWR_SLEEP);
    m.ign = true;                       // kierowca wsiada w trakcie ciszy
    sim_run(m, 1 * MIN);
    CHECK(m.longs == 0);
    CHECK(m.shorts == 2 && m.pc == PWR_RUNNING);
    sim_run(m, 3 * HOUR, 1000);
    CHECK(m.longs == 0);
}

static void test_unstable_led_blocks_long(void)
{
    // Rytm mrugania w S3 nie do odczytania: wyjście dekodera skacze między
    // S3 a pracą. Bez stabilnego S3 nie ma LONG ani ponownego uzbrojenia.
    Sim m;
    sim_init(m, true, 1000, PWR_SLEEP, false);
    m.decodeFlicker = true;
    sim_run(m, 3 * HOUR, 200);
    CHECK(m.longs == 0 && m.shorts == 0);
    CHECK(m.s.escDue);
    m.decodeFlicker = false;
    sim_run(m, 30 * SEC);
    CHECK(m.longs == 1 && m.pc == PWR_OFF);
}

// Z review: maszyna stabilnie pracuje, zapłon gaśnie, SHORT → S3, a odczyt
// diody w S3 skacze co okno. `stable` zostało RUNNING sprzed zgaszenia, więc
// dawne `stable == state` przepuszczało każde okno „RUNNING” i eskalacja
// po 2 h wysyłała SHORT do śpiącej maszyny — budziła ją co godzinę.
static void test_flicker_after_ignition_off_never_wakes(void)
{
    Sim m;
    sim_init(m, true, 1000, PWR_RUNNING, true);
    m.decodeFlicker = true;             // dotyczy tylko S3
    sim_run(m, 60 * SEC);
    m.ign = false;
    sim_run(m, 30 * SEC);
    CHECK(m.shorts == 1 && m.pc == PWR_SLEEP);
    sim_run(m, 6 * HOUR, 200);
    CHECK(m.shorts == 1);
    CHECK(m.longs == 0);
    CHECK(m.wakesWhileParked == 0);
    CHECK(m.pc == PWR_SLEEP);
    CHECK(m.s.desired == PWR_UNKNOWN);  // zamiar S3 wygasł, nie wisi
}

// Ta sama sytuacja z PRAWDZIWYM dekoderem i wolnym miganiem: dawny dekoder
// (jedno okno 1,6 s) przy 2 s świeci / 2 s nie widział raz 0, raz 1 zbocze
// i skakał między RUNNING a OFF. Z histerezą to stabilne SLEEP — eskalacja
// działa normalnie i nikogo nie budzi.
static void test_blink_rates_decode_as_sleep(void)
{
    const uint32_t periods[] = {300, 1000, 2000, 4000, 8000, 12000};
    for (uint32_t period : periods) {
        Sim m;
        sim_init(m, true, 1000, PWR_RUNNING, true);
        m.blinkMs = period;
        sim_run(m, 60 * SEC);
        m.ign = false;
        sim_run(m, 2 * HOUR + 1 * MIN);
        CHECK(m.windowsInS3 > 1000);
        CHECK(m.windowsInS3NotSleep == 0);
        CHECK(m.shorts == 1);
        CHECK(m.longs == 1 && m.longsWhileRunning == 0);
        CHECK(m.wakesWhileParked == 0);
        CHECK(m.pc == PWR_OFF);
    }
}

// --- dekoder diody (pwrLedSample) ------------------------------------------------

// Dekoder sam: poziom diody jako funkcja czasu, próbki co `dt` ms. Zwraca
// liczbę okien, w których stan był inny niż `allowed1` i `allowed2`.
struct LedRun {
    PwrLed d;
    uint32_t now;
    int windows;
    int other;
};

static void led_feed(LedRun &r, bool lit, uint32_t ms, PwrState a1, PwrState a2,
                     uint32_t dt = 10)
{
    for (uint32_t t = 0; t < ms; t += dt) {
        if (pwrLedSample(r.d, lit, r.now)) {
            r.windows++;
            if (r.d.decoded != a1 && r.d.decoded != a2) {
                r.other++;
            }
        }
        r.now += dt;
    }
}

static void test_led_decoder_steady_levels(void)
{
    LedRun r = LedRun();
    r.now = WRAP - 5 * SEC;             // okna przez przepełnienie millis()
    pwrLedInit(r.d, r.now);
    led_feed(r, true, 6 * SEC, PWR_UNKNOWN, PWR_UNKNOWN);   // jeszcze za mało ciszy
    CHECK(r.d.decoded == PWR_UNKNOWN && r.other == 0);
    led_feed(r, true, 1 * MIN, PWR_UNKNOWN, PWR_RUNNING);
    CHECK(r.d.decoded == PWR_RUNNING && r.other == 0);

    // Praca → twarde wyłączenie: jedno zbocze, potem ciemno. Nigdy SLEEP.
    led_feed(r, false, 1 * MIN, PWR_RUNNING, PWR_OFF);
    CHECK(r.d.decoded == PWR_OFF && r.other == 0);
    // Start z wyłączenia: jedno zbocze, potem ciągłe światło. Nigdy SLEEP.
    led_feed(r, true, 1 * MIN, PWR_OFF, PWR_RUNNING);
    CHECK(r.d.decoded == PWR_RUNNING && r.other == 0);
}

static void test_led_decoder_pwm_and_noise(void)
{
    // Dioda „oddychająca” przez PWM: zbocze w każdej próbce → S3.
    LedRun r = LedRun();
    r.now = 1000;
    pwrLedInit(r.d, r.now);
    bool lit = true;
    for (int i = 0; i < 20000; i++) {
        lit = !lit;
        led_feed(r, lit, 1, PWR_UNKNOWN, PWR_SLEEP, 1);
    }
    CHECK(r.d.decoded == PWR_SLEEP && r.other == 0);
    // Po wybudzeniu: RUNNING dopiero po PWR_LED_QUIET_WINDOWS oknach ciszy.
    led_feed(r, true, (PWR_LED_QUIET_WINDOWS - 1) * PWR_LED_WINDOW_MS, PWR_SLEEP, PWR_SLEEP);
    CHECK(r.d.decoded == PWR_SLEEP && r.other == 0);
    led_feed(r, true, 10 * SEC, PWR_SLEEP, PWR_RUNNING);
    CHECK(r.d.decoded == PWR_RUNNING);
}

// --- zapłon wraca, gdy host jeszcze się usypia --------------------------------

// Z review: SHORT na pracującą maszynę → bcm-power-toggle.sh zatrzymuje BCM
// (do 45 s) i dopiero potem usypia. Zapłon wraca w tym czasie (zgasły silnik,
// ponowny rozruch). Dawniej zamiar RUNNING znikał po 15 s ciszy, bo dioda
// jeszcze świeciła — maszyna zasypiała z włączonym zapłonem do kolejnego
// cyklu kluczyka.
static void test_ignition_back_while_host_suspends(void)
{
    const uint32_t delays[] = {5 * SEC, 20 * SEC, 30 * SEC, 46 * SEC, 75 * SEC};
    for (uint32_t delay : delays) {
        Sim m;
        sim_init(m, true, 1000, PWR_RUNNING, true);
        m.suspendDelay = delay;
        sim_run(m, 60 * SEC);
        m.ign = false;
        sim_run(m, 3 * SEC);            // potwierdzenie → SHORT
        CHECK(m.shorts == 1 && m.sleepPending);
        sim_run(m, 7 * SEC);
        m.ign = true;                   // ponowny rozruch po ~10 s
        sim_run(m, 3 * MIN);
        CHECK(m.pc == PWR_RUNNING);
        CHECK(m.shorts == 2);           // S3, potem pobudka — nic więcej
        CHECK(m.doublePress == 0);
        CHECK(m.s.desired == PWR_UNKNOWN);
        sim_run(m, 10 * MIN);
        CHECK(m.shorts == 2 && m.pc == PWR_RUNNING);
    }
}

// Host zignorował SHORT (dioda świeci przez całe okno) i zapłon wrócił:
// zamiar RUNNING jest spełniony, nie naciskamy — to by maszynę uśpiło.
static void test_ignition_back_host_never_suspended(void)
{
    Sim m;
    sim_init(m, true, 1000, PWR_RUNNING, true);
    m.refuseSleep = true;
    sim_run(m, 60 * SEC);
    m.ign = false;
    sim_run(m, 10 * SEC);
    CHECK(m.shorts == 1);
    m.ign = true;
    sim_run(m, 5 * MIN);
    CHECK(m.shorts == 1 && m.pc == PWR_RUNNING);
    CHECK(m.s.desired == PWR_UNKNOWN);
}

// Ten sam wyścig z SHORT eskalacji (2 h po zgaszeniu, maszyna pracuje).
static void test_ignition_back_during_escalation_suspend(void)
{
    Sim m;
    sim_init(m, true, 1000, PWR_RUNNING, false);
    m.suspendDelay = 30 * SEC;
    sim_run(m, 2 * HOUR + 20 * SEC);    // SHORT eskalacji ~2 h 16 s
    CHECK(m.shorts == 1 && m.sleepPending);
    m.ign = true;
    sim_run(m, 3 * MIN);
    CHECK(m.pc == PWR_RUNNING);
    CHECK(m.shorts == 2 && m.doublePress == 0);
    CHECK(m.longs == 0);
}

// Zapłon: wył. → wł. → wył. w trakcie usypiania. Drugi SHORT uruchomiłby
// skrypt drugi raz (suspend po wybudzeniu) — w oknie nie naciskamy.
static void test_no_second_press_while_host_suspends(void)
{
    Sim m;
    sim_init(m, true, 1000, PWR_RUNNING, true);
    m.suspendDelay = 40 * SEC;
    sim_run(m, 60 * SEC);
    m.ign = false;
    sim_run(m, 5 * SEC);
    CHECK(m.shorts == 1);
    m.ign = true;
    sim_run(m, 5 * SEC);
    m.ign = false;
    sim_run(m, 3 * MIN);
    CHECK(m.shorts == 1 && m.doublePress == 0);
    CHECK(m.pc == PWR_SLEEP);
    CHECK(m.s.desired == PWR_UNKNOWN);
}

// --- ponowienia i limity -------------------------------------------------------

static void test_missed_wake_press_is_retried(void)
{
    Sim m;
    parked_in_s3(m, true, 1000);
    sim_run(m, 10 * MIN, 1000);
    m.missPresses = 1;                  // przekaźnik nie zwarł raz
    m.ign = true;
    sim_run(m, 40 * SEC);
    CHECK(m.shorts == 3);               // S3 + nieudana pobudka + ponowienie
    CHECK(m.pc == PWR_RUNNING);
}

static void test_dead_relay_is_not_pressed_forever(void)
{
    Sim m;
    parked_in_s3(m, true, 1000);
    sim_run(m, 10 * MIN, 1000);
    m.missPresses = 1000;
    m.ign = true;
    sim_run(m, 30 * MIN, 200);
    CHECK(m.shorts == 1 + PWR_INTENT_PULSES);
    CHECK(m.s.desired == PWR_UNKNOWN);
}

// Dioda nie do odczytania: zapłon i tak budzi maszynę (z opóźnieniem
// PWR_UNSTEADY_MS) — ciągłe światło pracy dekoduje się zawsze, więc stan,
// który się nie ustala, to nie praca.
static void test_ignition_wakes_with_undecodable_led(void)
{
    Sim m;
    sim_init(m, true, 1000, PWR_RUNNING, true);
    m.decodeFlicker = true;
    sim_run(m, 60 * SEC);
    m.ign = false;
    sim_run(m, 30 * SEC);
    CHECK(m.shorts == 1 && m.pc == PWR_SLEEP);
    sim_run(m, 1 * HOUR, 200);
    CHECK(m.shorts == 1);
    m.ign = true;
    sim_run(m, 20 * SEC);
    CHECK(m.shorts == 1);               // jeszcze czekamy na stabilny odczyt
    sim_run(m, 25 * SEC);
    CHECK(m.shorts == 2 && m.pc == PWR_RUNNING);
    sim_run(m, 10 * MIN);
    CHECK(m.shorts == 2 && m.pc == PWR_RUNNING);
}

// Zamiar S3 przy stanie w ruchu nie może czekać godzinami: człowiek, który
// potem obudzi maszynę, nie dostaje od razu SHORT.
static void test_stale_sleep_intent_does_not_fight_manual_wake(void)
{
    Sim m;
    sim_init(m, true, 1000, PWR_SLEEP, true);
    m.decodeFlicker = true;
    sim_run(m, 60 * SEC);
    m.ign = false;                      // zamiar S3, stan się nie ustala
    sim_run(m, 10 * MIN);
    CHECK(m.shorts == 0);
    CHECK(m.s.desired == PWR_UNKNOWN);  // wygasł po PWR_INTENT_TTL_MS
    sim_set_pc(m, PWR_RUNNING);         // człowiek naciska przycisk
    sim_run(m, 10 * MIN);
    CHECK(m.shorts == 0 && m.pc == PWR_RUNNING);
}

// --- przepełnienie millis() -----------------------------------------------------

// Błąd a: termin ciszy sprzed przepełnienia („now < pwrSettleUntil”)
// blokował sterowanie na tygodnie po przekręceniu się millis().
static void test_settle_across_millis_rollover(void)
{
    Sim m;
    sim_init(m, true, WRAP - 3 * HOUR, PWR_SLEEP, false);
    sim_run(m, 1 * HOUR, 1000);
    m.ign = true;
    sim_run(m, 30 * SEC);               // SHORT ~2 h przed przepełnieniem
    CHECK(m.shorts == 1 && m.pc == PWR_RUNNING);
    sim_run(m, 2 * HOUR + 1 * MIN, 1000);
    CHECK(m.now < 10 * MIN);            // millis() już się przekręciło
    m.ign = false;
    sim_run(m, 10 * SEC);
    CHECK(m.shorts == 2);
    CHECK(m.pc == PWR_SLEEP);
}

static void test_pulse_and_settle_straddling_rollover(void)
{
    Sim m;
    sim_init(m, true, WRAP - 10 * MIN, PWR_RUNNING, true);
    sim_run(m, 10 * MIN - 8 * SEC);
    m.ign = false;                      // SHORT ~6 s przed przepełnieniem,
    sim_run(m, 2500);                   // termin ciszy wypada już po zerze
    CHECK(m.shorts == 1 && m.pc == PWR_SLEEP);
    m.ign = true;                       // zapłon potwierdzony w trakcie ciszy
    sim_run(m, 10 * SEC);
    CHECK(m.now < 10 * SEC);            // przekręcone
    CHECK(m.shorts == 1);               // cisza (15 s) nadal obowiązuje
    sim_run(m, 10 * SEC);
    CHECK(m.shorts == 2 && m.pc == PWR_RUNNING);
}

static void test_escalation_across_rollover(void)
{
    Sim m;
    parked_in_s3(m, true, WRAP - 30 * MIN);
    sim_run(m, 2 * HOUR + 2 * MIN, 1000);
    CHECK(m.now < 2 * HOUR);            // przekręcone
    CHECK(m.longs == 1 && m.pc == PWR_OFF);
}

// Termin ciszy porównywany ze znakiem działa tylko do 2^31 ms (~24,8 dnia).
// Po miesiącu bez impulsu zapłon i tak musi obudzić maszynę.
static void test_month_without_pulses(void)
{
    const uint32_t boots[] = {1000, WRAP - 10 * DAY};
    for (uint32_t boot : boots) {
        Sim m;
        parked_in_s3(m, true, boot);
        sim_run(m, 2 * HOUR + 2 * MIN, 1000);
        CHECK(m.pc == PWR_OFF);
        sim_run(m, 30 * DAY, 1000);
        CHECK(m.longs == 1 && m.shorts == 1);
        m.ign = true;
        sim_run(m, 5 * SEC);
        CHECK(m.shorts == 2);
        CHECK(m.pc == PWR_RUNNING);
    }
}

// Eskalacja raz osiągnięta trwa, aż się zakończy — także gdy różnica
// now - ignOffAt przekręci się po ~49,7 dnia (zatrzask escDue).
static void test_escalation_latch_survives_counter_wrap(void)
{
    Sim m;
    sim_init(m, true, 1000, PWR_RUNNING, false);
    m.refuseSleep = true;               // eskalacja nigdy się nie kończy
    sim_run(m, 25 * DAY, 1000);
    sim_run(m, 24 * DAY + 18 * HOUR, 1000);
    CHECK(m.s.escDue);
    CHECK((uint32_t)(m.now - m.s.ignOffAt) < 2 * HOUR);  // różnica przekręcona
    CHECK(m.longs == 0);
}

// --- pętla otwarta (bez FEATURE_PWRLED) -------------------------------------------

static void test_open_loop(void)
{
    // Po resecie płytki stan maszyny jest nieznany: żadnego LONG na ślepo.
    Sim m;
    sim_init(m, false, 1000, PWR_OFF, false);
    sim_run(m, 5 * HOUR, 1000);
    CHECK(m.shorts == 0 && m.longs == 0);

    m.ign = true;                       // zbocze: SHORT, założenie RUNNING
    sim_run(m, 30 * SEC);
    CHECK(m.shorts == 1 && m.pc == PWR_RUNNING);
    CHECK(m.s.state == PWR_RUNNING);
    m.ign = false;                      // SHORT, założenie S3
    sim_run(m, 30 * SEC);
    CHECK(m.shorts == 2 && m.pc == PWR_SLEEP);
    CHECK(m.s.state == PWR_SLEEP);
    sim_run(m, 2 * HOUR, 1000);         // eskalacja jak dotąd
    CHECK(m.longs == 1 && m.pc == PWR_OFF);
    CHECK(m.s.state == PWR_OFF);
}

// Pętla otwarta, ten sam wyścig: bez diody nie widać, kiedy host zaśnie,
// więc pobudka czeka do końca okna usypiania. Dawniej SHORT szedł po 15 s,
// w trakcie bcm-power-toggle.sh — drugi skrypt usypiał maszynę od razu.
static void test_open_loop_waits_for_suspend_window(void)
{
    Sim m;
    sim_init(m, false, 1000, PWR_SLEEP, false);
    sim_run(m, 10 * SEC);
    m.ign = true;
    sim_run(m, 30 * SEC);
    CHECK(m.shorts == 1 && m.pc == PWR_RUNNING);
    m.suspendDelay = 40 * SEC;
    m.ign = false;
    sim_run(m, 10 * SEC);
    CHECK(m.shorts == 2 && m.sleepPending);
    m.ign = true;                       // zapłon wraca po ~10 s
    sim_run(m, 60 * SEC);
    CHECK(m.shorts == 2);               // okno trwa — nie naciskamy
    CHECK(m.pc == PWR_SLEEP);           // host zasnął po swoich 40 s
    sim_run(m, 30 * SEC);
    CHECK(m.shorts == 3 && m.pc == PWR_RUNNING);
    CHECK(m.doublePress == 0);
}

// ---------------------------------------------------------------------------

int main(void)
{
    test_ignition_cycle();
    test_first_observation_takes_no_action();
    test_cranking_dip_is_ignored();
    test_escalation_from_sleep();
    test_no_long_while_running();
    test_running_host_that_refuses_sleep();
    test_escalation_rearms_after_wake_from_off();
    test_ignition_on_cancels_escalation();
    test_unstable_led_blocks_long();
    test_flicker_after_ignition_off_never_wakes();
    test_blink_rates_decode_as_sleep();
    test_led_decoder_steady_levels();
    test_led_decoder_pwm_and_noise();
    test_ignition_back_while_host_suspends();
    test_ignition_back_host_never_suspended();
    test_ignition_back_during_escalation_suspend();
    test_no_second_press_while_host_suspends();
    test_missed_wake_press_is_retried();
    test_dead_relay_is_not_pressed_forever();
    test_ignition_wakes_with_undecodable_led();
    test_stale_sleep_intent_does_not_fight_manual_wake();
    test_settle_across_millis_rollover();
    test_pulse_and_settle_straddling_rollover();
    test_escalation_across_rollover();
    test_month_without_pulses();
    test_escalation_latch_survives_counter_wrap();
    test_open_loop();
    test_open_loop_waits_for_suspend_window();

    printf("sensor_hub power_logic: OK (%d asercji)\n", g_checks);
    return 0;
}
