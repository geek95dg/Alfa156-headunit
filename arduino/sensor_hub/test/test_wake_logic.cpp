/*
 * BCM v8.5 — testy hosta dla wybudzania z zewnątrz (sensor_hub, wake_logic.h)
 *
 * Kompilacja i uruchomienie BEZ Arduino i bez płytki:
 *
 *   make -C arduino sensor_hub-test
 *   # albo ręcznie:
 *   g++ -std=c++17 -Wall -Wextra -Werror -o test_wake_logic test_wake_logic.cpp && ./test_wake_logic
 *
 * Symulowana maszyna (dioda panelu, reakcja na SHORT/LONG jak
 * w test_power_logic.cpp) plus pętla sketcha w tej samej kolejności co
 * loop(): handlePwrButton() (power_logic.h), potem handleWake()
 * (wake_logic.h), potem polecenia z hosta i pieczęć. Sprawdzamy reguły
 * przyjęcia prośby, dzierżawę, HOLD/RELEASE, limity, blokadę drzwi, brak
 * LONG przy pracującej maszynie, przepełnienie millis() i micros(), reset
 * płytki (.noinit) oraz dekoder NEC na syntetycznych ciągach impulsów
 * i czytnik linii.
 */
#ifdef NDEBUG
#error "Testy stoją na assert() — nie kompiluj z NDEBUG."
#endif

#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <vector>

#include "../wake_logic.h"

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

static const uint32_t PULSE_SHORT_MS = 250;
static const uint32_t PULSE_LONG_MS = 5000;

// --- model: M910q + pętla loop() sensor_hub z wybudzaniem ------------------------

struct Sim {
    PwrLogic s;
    PwrLed led;
    WakeLogic w;
    uint32_t now;           // millis()
    uint32_t wbase;         // zegar budzenia = wbase + now
    bool ign;
    PwrState pc;
    uint32_t pcSince;
    bool pulsing;
    uint32_t pulseUntil;
    // wejścia
    bool door;
    bool ext;
    bool irPair;            // jednorazowo w następnym obiegu
    bool battCheck;
    int32_t battMv;
    // liczniki
    int shorts;
    int longs;
    int longsWhileRunning;
    int wakes[4];           // WAKE: wg źródła
    int denies[5];          // WAKE_DENIED: wg powodu
    int leaseReports;
    uint32_t lastLease;     // ostatnie LEASE:<s>
};

static uint32_t wnow(const Sim &m) { return m.wbase + m.now; }

static void sim_set_pc(Sim &m, PwrState pc)
{
    if (pc != m.pc) {
        m.pc = pc;
        m.pcSince = m.now;
    }
}

static void sim_init(Sim &m, uint32_t boot, PwrState pc, bool ign)
{
    std::memset(&m, 0, sizeof(m));
    m.now = boot;
    m.pc = pc;
    m.pcSince = boot;
    m.ign = ign;
    pwrInit(m.s, true, boot);
    pwrLedInit(m.led, boot);
    m.wbase = wakeBoot(m.w, boot) - boot;
}

static bool led_lit(const Sim &m)
{
    switch (m.pc) {
    case PWR_RUNNING:
        return true;
    case PWR_SLEEP:
        return ((uint32_t)(m.now - m.pcSince) % 2000) < 1000;
    default:
        return false;
    }
}

// Host na SHORT: pracujący zasypia od razu, śpiący / wyłączony wstaje.
static void sim_short(Sim &m)
{
    m.shorts++;
    if (m.pc == PWR_RUNNING) {
        sim_set_pc(m, PWR_SLEEP);
    } else {
        sim_set_pc(m, PWR_RUNNING);
    }
}

static void sim_report(Sim &m, const WakeOut &out)
{
    if (out.wake) m.wakes[out.wake]++;
    if (out.denied) m.denies[out.denied]++;
    if (out.lease) {
        m.leaseReports++;
        m.lastLease = wakeLeaseLeft(m.w, wnow(m));
    }
}

// Jeden obieg loop(): handlePwrButton(), potem handleWake().
static void sim_loop(Sim &m)
{
    if (m.pulsing) {
        if ((int32_t)(m.now - m.pulseUntil) >= 0) {
            m.pulsing = false;
            pwrPulseDone(m.s, m.now);
        }
    } else {
        if (pwrLedSample(m.led, led_lit(m), m.now)) pwrObserve(m.s, m.led.decoded, m.now);
        const PwrAction a = pwrStep(m.s, m.now, m.ign);
        if (a == PWR_ACT_SHORT) {
            sim_short(m);
            m.pulsing = true;
            m.pulseUntil = m.now + PULSE_SHORT_MS;
        } else if (a == PWR_ACT_LONG) {
            m.longs++;
            if (m.pc == PWR_RUNNING) m.longsWhileRunning++;
            sim_set_pc(m, PWR_OFF);
            m.pulsing = true;
            m.pulseUntil = m.now + PULSE_LONG_MS;
        }
    }
    WakeIn in = WakeIn();
    in.doorOpen = m.door;
    in.extActive = m.ext;
    in.irPair = m.irPair;
    m.irPair = false;
    in.pulsing = m.pulsing;
    in.battCheck = m.battCheck;
    in.battMv = m.battMv;
    WakeOut out;
    wakeStep(m.w, m.s, wnow(m), m.now, in, out);
    sim_report(m, out);
    wakeSeal(m.w);
}

static void sim_run(Sim &m, uint32_t ms, uint32_t dt = 50)
{
    for (uint32_t t = 0; t < ms; t += dt) {
        sim_loop(m);
        m.now += dt;
    }
}

// Polecenie z hosta, jak handleWakeSerial(): linia → HOLD/RELEASE → LEASE:.
static bool sim_cmd(Sim &m, const char *line)
{
    WakeLine r;
    std::memset(&r, 0, sizeof(r));
    bool any = false;
    for (const char *c = line; *c; c++) {
        if (!wakeLineFeed(r, *c)) continue;
        uint8_t minutes = 0;
        WakeOut out = WakeOut();
        const uint8_t cmd = wakeParseCmd(r.buf, minutes);
        if (cmd == WAKE_CMD_HOLD) {
            wakeHold(m.w, minutes, wnow(m));
        } else if (cmd == WAKE_CMD_RELEASE) {
            wakeRelease(m.w, m.s, wnow(m), m.now, out);
        } else {
            continue;
        }
        any = true;
        m.lastLease = wakeLeaseLeft(m.w, wnow(m));
    }
    wakeSeal(m.w);
    return any;
}

static void open_door(Sim &m)
{
    m.door = true;
    sim_run(m, 2 * SEC);
    m.door = false;
    sim_run(m, 1 * SEC);
}

// Auto zaparkowane: jechało (zapłon, maszyna pracuje), zapłon zgaszony,
// maszyna stabilnie w S3, kierowca wysiadł drzwiami kierowcy (pierwsze
// otwarcie po jeździe — bez pobudki i bez odmowy, chyba że !driverExit),
// blokada drzwi minęła (chyba że keepHoldoff).
static void parked(Sim &m, uint32_t boot, bool keepHoldoff = false, bool driverExit = true)
{
    sim_init(m, boot, PWR_RUNNING, true);
    sim_run(m, 30 * SEC);
    m.ign = false;
    sim_run(m, 40 * SEC);               // zbocze → SHORT → S3, stan się ustala
    CHECK(m.pc == PWR_SLEEP);
    CHECK(pwrSteady(m.s, m.now));
    if (driverExit) {
        CHECK(m.w.exitPending);
        open_door(m);                   // wysiadanie
        CHECK(!m.w.exitPending);
        CHECK(m.w.denied == 0 && m.wakes[WAKE_SRC_DOOR] == 0);
    }
    if (!keepHoldoff) sim_run(m, 2 * MIN);
}

static void ir_pair(Sim &m)
{
    m.irPair = true;
    sim_run(m, 100);
}

// --- drzwi ------------------------------------------------------------------------

static void test_door_wake_and_lease_end(void)
{
    Sim m;
    parked(m, 1000);
    const int shorts = m.shorts;
    open_door(m);
    CHECK(m.wakes[WAKE_SRC_DOOR] == 1);
    sim_run(m, 30 * SEC);
    CHECK(m.shorts == shorts + 1);      // SHORT na pobudkę
    CHECK(m.pc == PWR_RUNNING);
    CHECK(m.w.lease);
    CHECK(wakeLeaseLeft(m.w, wnow(m)) <= 5 * 60);
    CHECK(wakeLeaseLeft(m.w, wnow(m)) > 4 * 60);

    sim_run(m, 4 * MIN);
    CHECK(m.pc == PWR_RUNNING);         // dzierżawa jeszcze trwa
    sim_run(m, 1 * MIN);
    CHECK(!m.w.lease);
    CHECK(m.lastLease == 0);
    CHECK(m.shorts == shorts + 2);      // koniec dzierżawy → SHORT → S3
    CHECK(m.pc == PWR_SLEEP);
    CHECK(m.longs == 0 && m.longsWhileRunning == 0);
    sim_run(m, 20 * MIN, 1000);
    CHECK(m.shorts == shorts + 2);      // śpiącej nikt nie rusza
}

static void test_door_holdoff_after_ignition_off(void)
{
    Sim m;
    parked(m, 1000, true);              // 40 s po zgaszeniu, kierowca wysiadł
    open_door(m);                       // wraca po coś zaraz po wyjściu
    CHECK(m.denies[WAKE_DENY_HOLDOFF] == 1);
    CHECK(m.wakes[WAKE_SRC_DOOR] == 0);
    CHECK(m.w.denied == 1 && m.w.lastDenied == WAKE_DENY_HOLDOFF);
    sim_run(m, 30 * SEC);
    CHECK(m.pc == PWR_SLEEP);
    sim_run(m, 2 * MIN);                // blokada minęła
    open_door(m);
    CHECK(m.wakes[WAKE_SRC_DOOR] == 1);
}

static void sim_reset(Sim &m, uint32_t gapMs);

// Kierowca siedzi po zgaszeniu dłużej niż blokada (rozmowa) i dopiero wtedy
// wysiada: to otwarcie nie budzi komputera (dawniej: fałszywa pobudka na
// 5 min i zjedzony slot limitu). Następne otwarcie — powrót — budzi.
static void test_door_exit_after_sitting_long(void)
{
    Sim m;
    parked(m, 1000, false, false);      // zgaszony, nikt jeszcze nie wysiadł
    sim_run(m, 3 * MIN);                // blokada dawno minęła
    CHECK(m.w.exitPending && !m.w.holdoff);
    open_door(m);                       // wysiada
    CHECK(m.wakes[WAKE_SRC_DOOR] == 0 && m.w.denied == 0);
    CHECK(!m.w.exitPending);
    int used = 0;
    for (int i = 0; i < WAKE_MAX_PER_DAY; i++) used += m.w.slotUsed[i] ? 1 : 0;
    CHECK(used == 0);                   // limit nietknięty
    sim_run(m, 20 * MIN, 1000);
    open_door(m);                       // wraca
    CHECK(m.wakes[WAKE_SRC_DOOR] == 1);

    // Wysiadł drzwiami pasażera: po WAKE_DOOR_EXIT_MS pierwsze otwarcie
    // drzwi kierowcy to już powrót.
    Sim p;
    parked(p, 1000, false, false);
    sim_run(p, 31 * MIN, 1000);
    CHECK(!p.w.exitPending);
    open_door(p);
    CHECK(p.wakes[WAKE_SRC_DOOR] == 1);

    // Reset Nano (DTR) nie gubi wysiadania; zanik zasilania (świeży start)
    // go nie wymyśla — nie wiadomo, czy ktoś siedzi w aucie.
    Sim r;
    parked(r, 1000, false, false);
    sim_reset(r, 0);
    sim_run(r, 5 * SEC);
    CHECK(r.w.exitPending);
    open_door(r);
    CHECK(r.wakes[WAKE_SRC_DOOR] == 0 && r.w.denied == 0);
    Sim f;
    sim_init(f, 1000, PWR_SLEEP, false);
    sim_run(f, 5 * SEC);
    CHECK(!f.w.exitPending);
}

static void test_no_request_with_ignition_on(void)
{
    Sim m;
    sim_init(m, 1000, PWR_RUNNING, true);
    sim_run(m, 30 * SEC);
    open_door(m);
    m.irPair = true;
    sim_run(m, 1 * SEC);
    CHECK(m.wakes[1] + m.wakes[2] + m.wakes[3] == 0);
    CHECK(m.w.denied == 0);             // przy zapłonie to nie są prośby
    CHECK(!m.w.lease);
}

static void test_state_denied_when_running_without_lease(void)
{
    Sim m;
    parked(m, 1000);
    sim_set_pc(m, PWR_RUNNING);         // ktoś nacisnął przycisk ręcznie
    sim_run(m, 30 * SEC);
    const int shorts = m.shorts;
    open_door(m);
    CHECK(m.denies[WAKE_DENY_STATE] == 1);
    ir_pair(m);
    CHECK(m.denies[WAKE_DENY_STATE] == 2);
    CHECK(m.shorts == shorts);          // żadnego naciśnięcia
    CHECK(!m.w.lease);
}

static void test_state_denied_while_settling(void)
{
    // Tuż po impulsie (cisza 15 s) stan nie jest pewny — odmowa, nie SHORT.
    Sim m;
    parked(m, 1000);
    ir_pair(m);
    CHECK(m.wakes[WAKE_SRC_IR] == 1);
    m.w.lease = false;                  // sztucznie: dzierżawy nie ma
    sim_run(m, 1 * SEC);
    ir_pair(m);
    CHECK(m.denies[WAKE_DENY_STATE] == 1);
}

static void test_door_settle_after_boot(void)
{
    // Drzwi otwarte już przy starcie płytki: to nie jest otwarcie.
    Sim m;
    sim_init(m, 1000, PWR_SLEEP, false);
    m.door = true;
    sim_run(m, 5 * MIN);
    CHECK(m.wakes[WAKE_SRC_DOOR] == 0 && m.w.denied == 0);
}

// --- dzierżawa i polecenia ------------------------------------------------------------

static void test_request_during_lease_extends(void)
{
    Sim m;
    parked(m, 1000);
    ir_pair(m);                         // 10 min
    sim_run(m, 8 * MIN);
    const int shorts = m.shorts;
    open_door(m);                       // przedłuża do co najmniej 5 min od teraz
    CHECK(m.wakes[WAKE_SRC_DOOR] == 1);
    CHECK(m.w.reason == WAKE_SRC_DOOR);
    CHECK(m.shorts == shorts);          // bez naciskania
    sim_run(m, 3 * MIN);                // 11 min od pobudki — wciąż pracuje
    CHECK(m.w.lease && m.pc == PWR_RUNNING);
    sim_run(m, 3 * MIN);
    CHECK(!m.w.lease && m.pc == PWR_SLEEP);
    // Przedłużenie nie zużyło limitu: jeszcze dwie pobudki w tej godzinie.
    int used = 0;
    for (int i = 0; i < WAKE_MAX_PER_DAY; i++) used += m.w.slotUsed[i] ? 1 : 0;
    CHECK(used == 1);
}

static void test_hold_and_release(void)
{
    Sim m;
    parked(m, 1000);
    ir_pair(m);
    sim_run(m, 1 * MIN);
    CHECK(sim_cmd(m, "HOLD:30\n"));
    CHECK(m.lastLease > 29 * 60 && m.lastLease <= 30 * 60);
    sim_run(m, 20 * MIN, 1000);
    CHECK(m.w.lease && m.pc == PWR_RUNNING);
    const int shorts = m.shorts;
    CHECK(sim_cmd(m, "RELEASE\r\n"));
    CHECK(m.lastLease == 0 && !m.w.lease);
    sim_run(m, 30 * SEC);
    CHECK(m.shorts == shorts + 1 && m.pc == PWR_SLEEP);
    CHECK(m.longsWhileRunning == 0);
    // Bez dzierżawy polecenia nic nie robią.
    CHECK(sim_cmd(m, "HOLD:10\n"));     // odpowiedź jest (LEASE:0)...
    CHECK(m.lastLease == 0 && !m.w.lease);
    CHECK(sim_cmd(m, "RELEASE\n"));
    sim_run(m, 1 * MIN);
    CHECK(m.shorts == shorts + 1);      // ...ale żadnego naciśnięcia
}

static void test_hold_never_shortens_and_session_cap(void)
{
    Sim m;
    parked(m, 1000);
    ir_pair(m);                         // 10 min
    sim_cmd(m, "HOLD:1\n");             // krócej niż zostało — bez zmiany
    CHECK(m.lastLease > 9 * 60);
    // Host bez końca prosi o HOLD:60 (co minutę) — sesja i tak kończy się
    // po 90 min od pobudki.
    uint32_t endedAfter = 0;
    for (int i = 0; i < 200 && m.w.lease; i++) {
        sim_cmd(m, "HOLD:60\n");
        sim_run(m, 1 * MIN, 1000);
        endedAfter = (uint32_t)(wnow(m) - m.w.sessionAt);
    }
    CHECK(!m.w.lease);
    CHECK(endedAfter >= WAKE_SESSION_MAX_MS);
    CHECK(endedAfter <= WAKE_SESSION_MAX_MS + 1 * MIN + SEC);
    sim_run(m, 1 * MIN);
    CHECK(m.pc == PWR_SLEEP && m.longsWhileRunning == 0);
}

static void test_ignition_cancels_lease(void)
{
    Sim m;
    parked(m, 1000);
    open_door(m);
    sim_run(m, 30 * SEC);
    CHECK(m.w.lease && m.pc == PWR_RUNNING);
    const int shorts = m.shorts;
    m.ign = true;
    sim_run(m, 10 * SEC);
    CHECK(!m.w.lease && m.lastLease == 0);
    sim_run(m, 30 * MIN, 1000);         // jazda: nikt nie usypia
    CHECK(m.shorts == shorts && m.pc == PWR_RUNNING);
    m.ign = false;                      // zwykłe zgaszenie — zwykłe S3
    sim_run(m, 30 * SEC);
    CHECK(m.shorts == shorts + 1 && m.pc == PWR_SLEEP);
}

// --- limity i bank ---------------------------------------------------------------------

static void wake_and_sleep(Sim &m)
{
    ir_pair(m);
    sim_run(m, 30 * SEC);
    sim_cmd(m, "RELEASE\n");
    sim_run(m, 40 * SEC);
}

static void test_rate_limit_hour_and_day(void)
{
    Sim m;
    parked(m, 1000);
    for (int i = 0; i < 3; i++) {
        wake_and_sleep(m);
        CHECK(m.pc == PWR_SLEEP);
    }
    CHECK(m.wakes[WAKE_SRC_IR] == 3);
    ir_pair(m);
    CHECK(m.denies[WAKE_DENY_RATE] == 1);
    CHECK(m.pc == PWR_SLEEP);
    sim_run(m, 1 * HOUR, 1000);         // godzina minęła
    for (int i = 0; i < 3; i++) wake_and_sleep(m);
    CHECK(m.wakes[WAKE_SRC_IR] == 6);
    sim_run(m, 2 * HOUR, 1000);
    ir_pair(m);                         // 6 na dobę wyczerpane
    CHECK(m.denies[WAKE_DENY_RATE] == 2);
    sim_run(m, 22 * HOUR, 1000);        // doba od pierwszej pobudki
    wake_and_sleep(m);
    CHECK(m.wakes[WAKE_SRC_IR] == 7);
    CHECK(m.longsWhileRunning == 0);
}

static void test_low_battery(void)
{
    Sim m;
    parked(m, 1000);
    m.battCheck = true;
    m.battMv = 12200;                   // równo 12,2 V to za mało (> 12,2 V)
    ir_pair(m);
    CHECK(m.denies[WAKE_DENY_LOWBATT] == 1);
    m.battMv = -1;                      // brak świeżego odczytu
    ir_pair(m);
    CHECK(m.denies[WAKE_DENY_LOWBATT] == 2);
    CHECK(m.pc == PWR_SLEEP);
    m.battMv = 12650;
    ir_pair(m);
    CHECK(m.wakes[WAKE_SRC_IR] == 1);
    // Bez BATT_* warunek jest pomijany.
    Sim n;
    parked(n, 1000);
    n.battCheck = false;
    n.battMv = -1;
    ir_pair(n);
    CHECK(n.wakes[WAKE_SRC_IR] == 1);
}

static void test_denied_counter_saturates(void)
{
    WakeLogic w;
    wakeBoot(w, 0);
    WakeOut out = WakeOut();
    w.denied = 0xFFFE;
    wakeDeny(w, WAKE_DENY_RATE, out);
    wakeDeny(w, WAKE_DENY_STATE, out);
    CHECK(w.denied == 0xFFFF && w.lastDenied == WAKE_DENY_STATE);
}

// --- EXT ---------------------------------------------------------------------------------

static void test_ext_pulse_debounce(void)
{
    Sim m;
    parked(m, 1000);
    m.ext = true;                       // 30 ms — za krótko
    sim_run(m, 30, 5);
    m.ext = false;
    sim_run(m, 1 * SEC, 5);
    CHECK(m.wakes[WAKE_SRC_EXT] == 0 && m.w.denied == 0);
    for (int i = 0; i < 6; i++) {       // drgania styku
        m.ext = (i & 1) == 0;
        sim_run(m, 10, 5);
    }
    m.ext = false;
    sim_run(m, 1 * SEC, 5);
    CHECK(m.wakes[WAKE_SRC_EXT] == 0);
    m.ext = true;                       // 80 ms — prośba
    sim_run(m, 80, 5);
    m.ext = false;
    sim_run(m, 1 * SEC, 5);
    CHECK(m.wakes[WAKE_SRC_EXT] == 1);
    sim_run(m, 30 * SEC);
    CHECK(m.pc == PWR_RUNNING);
    CHECK(wakeLeaseLeft(m.w, wnow(m)) > 9 * 60);   // EXT: 10 min
}

// --- IR: para ramek ----------------------------------------------------------------------

static void test_ir_pairing(void)
{
    WakeLogic w;
    uint32_t t = wakeBoot(w, 5000);
    const uint16_t A = WAKE_IR_ADDRESS;
    const uint8_t C = WAKE_IR_COMMAND;
    CHECK(!wakeIrFrame(w, A, C, t));    // przed WAKE_INPUT_SETTLE_MS — nic
    PwrLogic p;
    pwrInit(p, true, 0);
    WakeIn in = WakeIn();
    WakeOut out;
    t += 2000;
    wakeStep(w, p, t, 0, in, out);      // settled
    CHECK(w.settled);
    CHECK(!wakeIrFrame(w, A, C, t));
    CHECK(wakeIrFrame(w, A, C, t + 108));          // druga w 1 s
    CHECK(!wakeIrFrame(w, A, C, t + 216));         // trzecia: cisza po parze
    t += 4000;
    wakeStep(w, p, t, 0, in, out);
    CHECK(!wakeIrFrame(w, A, C, t));
    CHECK(!wakeIrFrame(w, A, C, t + 1200));        // za późno — nowa pierwsza
    CHECK(wakeIrFrame(w, A, C, t + 1300));
    t += 10000;
    wakeStep(w, p, t, 0, in, out);
    CHECK(!wakeIrFrame(w, (uint16_t)(A ^ 1), C, t));        // cudzy adres
    CHECK(!wakeIrFrame(w, (uint16_t)(A ^ 1), C, t + 100));
    CHECK(!wakeIrFrame(w, A, (uint8_t)(C ^ 1), t + 200));   // cudze polecenie
    CHECK(!wakeIrFrame(w, A, C, t + 300));
    CHECK(wakeIrFrame(w, A, C, t + 400));
}

static void test_ir_wake_end_to_end(void)
{
    Sim m;
    parked(m, 1000);
    ir_pair(m);
    CHECK(m.wakes[WAKE_SRC_IR] == 1);
    sim_run(m, 30 * SEC);
    CHECK(m.pc == PWR_RUNNING);
    sim_run(m, 10 * MIN);
    CHECK(m.pc == PWR_SLEEP && !m.w.lease);
}

// --- brak LONG przy pracującej, eskalacja po sesji ----------------------------------------

static void test_escalation_after_session_only_from_sleep(void)
{
    Sim m;
    parked(m, 1000);
    ir_pair(m);
    sim_run(m, 30 * SEC);
    sim_cmd(m, "HOLD:60\n");
    sim_run(m, 70 * MIN, 1000);         // cała sesja pracuje
    CHECK(m.longs == 0);
    CHECK(m.pc == PWR_SLEEP);           // koniec dzierżawy → S3
    sim_run(m, 2 * HOUR, 1000);         // eskalacja liczona od pobudki
    CHECK(m.longs == 1 && m.longsWhileRunning == 0);
    CHECK(m.pc == PWR_OFF);
    // Pobudka z OFF działa tak samo (stan stabilnie OFF).
    ir_pair(m);
    CHECK(m.wakes[WAKE_SRC_IR] == 2);
    sim_run(m, 30 * SEC);
    CHECK(m.pc == PWR_RUNNING);
    sim_run(m, 10 * MIN);
    CHECK(m.pc == PWR_SLEEP && m.longsWhileRunning == 0);
}

// --- przepełnienie zegarów --------------------------------------------------------------------

static void test_lease_across_millis_rollover(void)
{
    Sim m;
    parked(m, 0xFFFFFFFFUL - 6 * MIN);  // pobudka tuż przed przepełnieniem
    ir_pair(m);
    sim_run(m, 30 * SEC);
    CHECK(m.pc == PWR_RUNNING);
    sim_run(m, 8 * MIN);                // przez przepełnienie
    CHECK(m.w.lease && m.pc == PWR_RUNNING);
    sim_run(m, 2 * MIN);
    CHECK(!m.w.lease && m.pc == PWR_SLEEP);
    CHECK(m.longsWhileRunning == 0);
}

static void test_month_without_wakes_then_limits(void)
{
    // Ponad 2^31 ms (~24,8 dnia) bez niczego: stare sloty limitu i blokada
    // drzwi nie mogą „odżyć” po przekręceniu różnicy.
    Sim m;
    parked(m, 1000);
    for (int i = 0; i < 3; i++) wake_and_sleep(m);
    ir_pair(m);
    CHECK(m.denies[WAKE_DENY_RATE] == 1);
    // Krok 1 s (nie 1 min): dioda w S3 miga co 2 s i model musi ją widzieć.
    sim_run(m, 25 * DAY, 1000);
    sim_run(m, 25 * DAY, 1000);         // > 49,7 dnia — oba zegary przekręcone
    CHECK(m.pc == PWR_OFF);             // po drodze eskalacja (LONG z S3)
    for (int i = 0; i < 3; i++) wake_and_sleep(m);
    CHECK(m.wakes[WAKE_SRC_IR] == 6);
    open_door(m);                       // brak fałszywej blokady drzwi
    CHECK(m.denies[WAKE_DENY_HOLDOFF] == 0);
}

// --- reset płytki: .noinit ----------------------------------------------------------------------

static void sim_reset(Sim &m, uint32_t gapMs)
{
    // RAM WakeLogic przeżywa (kopia bajtów), reszta zaczyna od nowa:
    // power_logic, dekoder diody, millis() od zera.
    WakeLogic saved;
    std::memcpy(&saved, &m.w, sizeof(saved));
    const uint32_t before = wnow(m);
    m.now = 0;
    m.pulsing = false;
    pwrInit(m.s, true, m.now);
    pwrLedInit(m.led, m.now);
    std::memcpy(&m.w, &saved, sizeof(saved));
    m.wbase = wakeBoot(m.w, m.now) - m.now;
    CHECK((uint32_t)(wnow(m) - before) <= WAKE_RESET_GAP_MS + gapMs);
}

static void test_lease_survives_reset(void)
{
    Sim m;
    parked(m, 1000);
    ir_pair(m);
    sim_run(m, 40 * SEC);               // komputer wstaje, BCM otwiera port...
    CHECK(m.pc == PWR_RUNNING && m.w.lease);
    const uint32_t left = wakeLeaseLeft(m.w, wnow(m));
    sim_reset(m, 0);                    // ...i resetuje Nano przez DTR
    CHECK(m.w.lease);
    CHECK(wakeLeaseLeft(m.w, wnow(m)) <= left);
    CHECK(wakeLeaseLeft(m.w, wnow(m)) + 3 >= left);
    const int shorts = m.shorts;
    sim_run(m, 1 * MIN);
    CHECK(m.shorts == shorts);          // pierwsza obserwacja nic nie naciska
    sim_run(m, 9 * MIN);
    CHECK(!m.w.lease);
    CHECK(m.shorts == shorts + 1 && m.pc == PWR_SLEEP);
    // Limit też przeżył reset.
    int used = 0;
    for (int i = 0; i < WAKE_MAX_PER_DAY; i++) used += m.w.slotUsed[i] ? 1 : 0;
    CHECK(used == 1);
}

// RELEASE albo koniec dzierżawy w ~2 s po resecie Nano, zanim power_logic.h
// potwierdzi zapłon (BCM ponawia nieudany RELEASE właśnie po ponownym
// otwarciu portu, a otwarcie resetuje Nano): dzierżawa czeka na
// potwierdzenie i kończy się SHORT-em. Wcześniej znikała bez zamiaru S3 —
// komputer zostawał włączony na banku aż do eskalacji (do 2 h).
static Sim *reset_mid_session(Sim &m)
{
    parked(m, 1000);
    ir_pair(m);
    sim_run(m, 2 * MIN);
    CHECK(m.pc == PWR_RUNNING && m.w.lease);
    sim_reset(m, 0);
    CHECK(!m.s.ignKnown);
    return &m;
}

static void test_release_and_expiry_right_after_reset(void)
{
    const uint32_t release_at[] = {0, 500, 1950};
    for (uint32_t off : release_at) {
        Sim m;
        reset_mid_session(m);
        if (off) sim_run(m, off);
        CHECK(!m.s.ignKnown);
        const int shorts = m.shorts;
        CHECK(sim_cmd(m, "RELEASE\n"));
        CHECK(m.lastLease == 0);            // dla BCM sesja skończona od razu
        CHECK(sim_cmd(m, "HOLD:30\n"));
        CHECK(m.lastLease == 0);            // HOLD jej nie wskrzesza
        sim_run(m, 5 * MIN);
        CHECK(!m.w.lease);
        CHECK(m.shorts == shorts + 1 && m.pc == PWR_SLEEP);
        CHECK(m.longs == 0);
    }
    const uint32_t expire_at[] = {0, 1900};
    for (uint32_t off : expire_at) {
        Sim m;
        reset_mid_session(m);
        m.w.leaseUntil = wnow(m) + off;     // dzierżawa mija w oknie bez zapłonu
        wakeSeal(m.w);
        const int shorts = m.shorts;
        sim_run(m, 5 * MIN);
        CHECK(!m.w.lease);
        CHECK(m.shorts == shorts + 1 && m.pc == PWR_SLEEP);
    }
    {
        // Zapłon włączony w trakcie resetu: RELEASE kasuje dzierżawę, ale
        // niczego nie naciska — kierowca właśnie rusza.
        Sim m;
        reset_mid_session(m);
        m.ign = true;
        const int shorts = m.shorts;
        CHECK(sim_cmd(m, "RELEASE\n"));
        sim_run(m, 5 * MIN);
        CHECK(!m.w.lease);
        CHECK(m.shorts == shorts && m.pc == PWR_RUNNING);
    }
}

static void test_holdoff_survives_reset_and_corruption_resets(void)
{
    Sim m;
    parked(m, 1000, true);              // 40 s po zgaszeniu
    sim_reset(m, 0);
    sim_run(m, 5 * SEC);
    open_door(m);
    CHECK(m.denies[WAKE_DENY_HOLDOFF] == 1);   // blokada trwa po resecie
    // Zepsuty RAM (zanik zasilania): czysty start, bez dzierżawy.
    ir_pair(m);
    sim_run(m, 1 * SEC);
    reinterpret_cast<uint8_t *>(&m.w)[offsetof(WakeLogic, leaseUntil)] ^= 0x5A;
    CHECK(!wakeValid(m.w));
    WakeLogic w;
    std::memcpy(&w, &m.w, sizeof(w));
    wakeBoot(w, 123);
    CHECK(!w.lease && w.denied == 0 && w.clock == 123);
    CHECK(w.holdoff == false && w.ign == WAKE_IGN_UNKNOWN);
}

static void test_fresh_boot_holdoff_from_start(void)
{
    // Po zaniku zasilania nie wiadomo, kiedy zgaszono zapłon: blokada drzwi
    // liczy się od startu płytki (ostrożnie).
    Sim m;
    sim_init(m, 1000, PWR_SLEEP, false);
    sim_run(m, 30 * SEC);
    open_door(m);
    CHECK(m.denies[WAKE_DENY_HOLDOFF] == 1);
    sim_run(m, 2 * MIN);
    open_door(m);
    CHECK(m.wakes[WAKE_SRC_DOOR] == 1);
}

// --- dekoder NEC ---------------------------------------------------------------------------------

struct Pulse {
    bool mark;
    uint32_t us;
};

static void nec_frame(std::vector<Pulse> &v, uint16_t addr, uint8_t cmd, int32_t markAdj = 0,
                      bool badInverse = false)
{
    const uint32_t data = (uint32_t)addr | ((uint32_t)cmd << 16) |
                          ((uint32_t)(uint8_t)(badInverse ? cmd : ~cmd) << 24);
    auto mark = [&](uint32_t us) { v.push_back({true, (uint32_t)((int32_t)us + markAdj)}); };
    auto space = [&](uint32_t us) { v.push_back({false, (uint32_t)((int32_t)us - markAdj)}); };
    mark(9000);
    space(4500);
    for (int i = 0; i < 32; i++) {
        mark(562);
        space((data >> i) & 1U ? 1687 : 562);
    }
    mark(562);
}

// Puszcza ciąg odcinków przez necEdge (zbocze na początku każdego odcinka)
// i zbiera odebrane ramki.
static int nec_play(NecDecoder &d, const std::vector<Pulse> &v, uint32_t &t,
                    uint16_t *addr = nullptr, uint8_t *cmd = nullptr)
{
    int got = 0;
    for (const Pulse &p : v) {
        necEdge(d, p.mark, t);
        t += p.us;
        if (d.ready) {
            got++;
            if (addr) *addr = d.addr;
            if (cmd) *cmd = d.cmd;
            d.ready = false;
        }
    }
    necEdge(d, false, t);               // koniec ostatniego odcinka
    if (d.ready) {
        got++;
        if (addr) *addr = d.addr;
        if (cmd) *cmd = d.cmd;
        d.ready = false;
    }
    return got;
}

static void test_nec_decodes_frame(void)
{
    NecDecoder d;
    necInit(d);
    uint32_t t = 1000;
    necEdge(d, false, t);               // pierwszy odczyt linii (bezczynność)
    t += 50000;
    std::vector<Pulse> v;
    nec_frame(v, 0x7A15, 0x56);
    uint16_t a = 0;
    uint8_t c = 0;
    CHECK(nec_play(d, v, t, &a, &c) == 1);
    CHECK(a == 0x7A15 && c == 0x56);
}

static void test_nec_tolerates_tsop_distortion(void)
{
    for (int32_t adj : {-120, 0, 150, 250}) {
        NecDecoder d;
        necInit(d);
        uint32_t t = 0;
        necEdge(d, false, t);
        t += 20000;
        std::vector<Pulse> v;
        nec_frame(v, 0x1234, 0xA5, adj);
        uint16_t a = 0;
        uint8_t c = 0;
        CHECK(nec_play(d, v, t, &a, &c) == 1);
        CHECK(a == 0x1234 && c == 0xA5);
    }
}

static void test_nec_rejects_garbage(void)
{
    NecDecoder d;
    necInit(d);
    uint32_t t = 0;
    necEdge(d, false, t);
    t += 20000;
    std::vector<Pulse> bad;
    nec_frame(bad, 0x7A15, 0x56, 0, true);          // zła negacja polecenia
    CHECK(nec_play(d, bad, t) == 0);
    std::vector<Pulse> rep = {{true, 9000}, {false, 2250}, {true, 562}, {false, 40000}};
    CHECK(nec_play(d, rep, t) == 0);                 // ramka repeat
    std::vector<Pulse> noise;
    for (int i = 0; i < 500; i++) noise.push_back({(i & 1) == 0, (uint32_t)(100 + (i * 37) % 3000)});
    CHECK(nec_play(d, noise, t) == 0);
    // Ramka urwana w połowie, potem cała: tylko cała się liczy.
    std::vector<Pulse> v;
    nec_frame(v, 0x7A15, 0x56);
    std::vector<Pulse> half(v.begin(), v.begin() + 30);
    half.push_back({false, 30000});
    CHECK(nec_play(d, half, t) == 0);
    uint16_t a = 0;
    CHECK(nec_play(d, v, t, &a) == 1 && a == 0x7A15);
}

static void test_nec_missed_edge_resets(void)
{
    NecDecoder d;
    necInit(d);
    uint32_t t = 0;
    necEdge(d, false, t);
    t += 20000;
    std::vector<Pulse> v;
    nec_frame(v, 0x7A15, 0x56);
    // Zgubione zbocze: dwa odcinki tego samego poziomu pod rząd.
    std::vector<Pulse> broken(v);
    broken[20].mark = broken[19].mark;
    CHECK(nec_play(d, broken, t) == 0);
    t += 50000;
    CHECK(nec_play(d, v, t) == 1);
}

static void test_nec_three_frames_and_micros_rollover(void)
{
    // Telefon nadaje 3 ramki co 108 ms; start tuż przed przepełnieniem micros().
    NecDecoder d;
    necInit(d);
    uint32_t t = 0xFFFFFFFFUL - 150000UL;
    necEdge(d, false, t);
    t += 10000;
    WakeLogic w;
    uint32_t wt = wakeBoot(w, 0);
    PwrLogic p;
    pwrInit(p, true, 0);
    WakeIn in = WakeIn();
    WakeOut out;
    wt += 2000;
    wakeStep(w, p, wt, 0, in, out);
    int frames = 0, pairs = 0;
    for (int f = 0; f < 3; f++) {
        std::vector<Pulse> v;
        nec_frame(v, WAKE_IR_ADDRESS, WAKE_IR_COMMAND);
        uint32_t len = 0;
        for (const Pulse &p2 : v) len += p2.us;
        v.push_back({false, (uint32_t)(108000UL - len)});   // przerwa do następnej ramki
        uint16_t a = 0;
        uint8_t c = 0;
        const int got = nec_play(d, v, t, &a, &c);
        frames += got;
        if (got && wakeIrFrame(w, a, c, wt + (uint32_t)f * 108)) pairs++;
    }
    CHECK(t < 1000000UL);               // micros() naprawdę się przekręcił
    CHECK(frames == 3);
    CHECK(pairs == 1);                  // 3 ramki = jedna prośba
}

// --- czytnik linii ---------------------------------------------------------------------------------

static uint8_t parse_line(const char *text, uint8_t &minutes, int &lines)
{
    WakeLine r;
    std::memset(&r, 0, sizeof(r));
    uint8_t last = 0xFF;
    lines = 0;
    for (const char *c = text; *c; c++) {
        if (wakeLineFeed(r, *c)) {
            lines++;
            last = wakeParseCmd(r.buf, minutes);
        }
    }
    return last;
}

static void test_line_reader_and_commands(void)
{
    uint8_t mins = 0;
    int lines = 0;
    CHECK(parse_line("HOLD:30\n", mins, lines) == WAKE_CMD_HOLD && mins == 30 && lines == 1);
    CHECK(parse_line("HOLD:1\n", mins, lines) == WAKE_CMD_HOLD && mins == 1);
    CHECK(parse_line("HOLD:60\n", mins, lines) == WAKE_CMD_HOLD && mins == 60);
    CHECK(parse_line("RELEASE\r\n", mins, lines) == WAKE_CMD_RELEASE && lines == 1);
    const char *bad[] = {"HOLD:0\n", "HOLD:61\n", "HOLD:05\n", "HOLD:-5\n", "HOLD: 5\n",
                         "hold:30\n", "HOLD:30 \n", "HOLD:\n", "HOLD:300\n", "RELEASEX\n",
                         "RELEAS\n", "XHOLD:30\n", "HOLD30\n", "PWR:SHORT\n", "LONG\n"};
    for (const char *b : bad) {
        mins = 99;
        CHECK(parse_line(b, mins, lines) == WAKE_CMD_NONE);
        CHECK(mins == 99);
    }
    // Za długa linia: w całości odrzucona, następna działa.
    CHECK(parse_line("HOLD:30XXXXXXXXXXXXXXXXXXXXXXXXXXXXXX\nHOLD:20\n", mins, lines)
          == WAKE_CMD_HOLD);
    CHECK(mins == 20 && lines == 1);
    // Dokładnie 16 znaków mieści się, 17 już nie.
    CHECK(parse_line("AAAAAAAAAAAAAAAA\n", mins, lines) == WAKE_CMD_NONE && lines == 1);
    CHECK(parse_line("AAAAAAAAAAAAAAAAA\n", mins, lines) == 0xFF && lines == 0);
    // Znak spoza ASCII albo sterujący psuje linię.
    CHECK(parse_line("HOLD:3\x01" "0\n", mins, lines) == 0xFF && lines == 0);
    CHECK(parse_line("HOLD:\xC5\x82\n", mins, lines) == 0xFF);
    CHECK(parse_line("\n\n\r\n", mins, lines) == 0xFF && lines == 0);   // puste linie
}

// ---------------------------------------------------------------------------

int main(void)
{
    test_door_wake_and_lease_end();
    test_door_holdoff_after_ignition_off();
    test_door_exit_after_sitting_long();
    test_no_request_with_ignition_on();
    test_state_denied_when_running_without_lease();
    test_state_denied_while_settling();
    test_door_settle_after_boot();
    test_request_during_lease_extends();
    test_hold_and_release();
    test_hold_never_shortens_and_session_cap();
    test_ignition_cancels_lease();
    test_rate_limit_hour_and_day();
    test_low_battery();
    test_denied_counter_saturates();
    test_ext_pulse_debounce();
    test_ir_pairing();
    test_ir_wake_end_to_end();
    test_escalation_after_session_only_from_sleep();
    test_lease_across_millis_rollover();
    test_month_without_wakes_then_limits();
    test_lease_survives_reset();
    test_release_and_expiry_right_after_reset();
    test_holdoff_survives_reset_and_corruption_resets();
    test_fresh_boot_holdoff_from_start();
    test_nec_decodes_frame();
    test_nec_tolerates_tsop_distortion();
    test_nec_rejects_garbage();
    test_nec_missed_edge_resets();
    test_nec_three_frames_and_micros_rollover();
    test_line_reader_and_commands();

    printf("sensor_hub wake_logic: OK (%d asercji)\n", g_checks);
    return 0;
}
