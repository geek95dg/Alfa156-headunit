/*
 * BCM v8.5 — testy hosta dla firmware wyświetlacza 1,8" (ESP32-S3)
 *
 * Kompilacja i uruchomienie BEZ Arduino i bez płytki:
 *
 *   make -C arduino esp32_display-test
 *   # albo ręcznie:
 *   g++ -std=c++17 -Wall -Wextra -Werror -o test_host test_host.cpp && ./test_host
 *
 * Sprawdzamy dokładnie te trzy kawałki, które da się oderwać od sprzętu:
 * parser protokołu (protocol.h), debounce i wybór ekranu (state.h) oraz
 * metryki fontu (font_draw.h). Reszta — SPI, GPIO, LEDC — siedzi w .ino
 * i zostaje do sprawdzenia na stole.
 */
#ifdef NDEBUG
#error "Testy stoją na assert() — nie kompiluj z NDEBUG."
#endif

#include <cassert>
#include <cstdio>
#include <cstring>

#include "../protocol.h"
#include "../state.h"
#include "../font_draw.h"
#include "../text_layout.h"

static int g_checks = 0;

#define CHECK(cond)                                                            \
    do {                                                                       \
        g_checks++;                                                            \
        assert(cond);                                                          \
    } while (0)

// --- pomocnicze -------------------------------------------------------------

// Ile poprawnych codepointów ma napis i czy któryś zdegenerował do '?'.
static int decode_all(const char *s, int *fallbacks)
{
    int pos = 0;
    int n = 0;
    if (fallbacks != nullptr) {
        *fallbacks = 0;
    }
    for (;;) {
        const int cp = utf8_next(s, &pos);
        if (cp < 0) {
            break;
        }
        n++;
        if (cp == '?' && fallbacks != nullptr) {
            (*fallbacks)++;
        }
    }
    return n;
}

// Powtórzenie napisu `unit` `times` razy do bufora.
static void repeat(char *dst, size_t cap, const char *unit, int times)
{
    const size_t u = strlen(unit);
    size_t at = 0;
    for (int i = 0; i < times && at + u < cap; i++) {
        memcpy(dst + at, unit, u);
        at += u;
    }
    dst[at] = '\0';
}

static void feed_line(LineAssembler *a, DisplayData *d, const char *text, uint32_t now)
{
    for (const char *p = text; *p != '\0'; p++) {
        if (line_feed(a, *p)) {
            protocol_apply_line(d, a->buf, now);
        }
    }
}

// --- parser: podstawy -------------------------------------------------------

static void test_protocol_basics(void)
{
    DisplayData d;
    display_data_init(&d);

    CHECK(d.title[0] == '\0');
    CHECK(!d.seen);

    CHECK(protocol_apply_line(&d, "TITLE:Nightcall", 1000) == PROTO_UPDATED);
    CHECK(strcmp(d.title, "Nightcall") == 0);
    CHECK(d.seen);
    CHECK(d.last_rx_ms == 1000);

    // ta sama wartość drugi raz — nic do przerysowania, ale to nadal
    // dowód życia BCM
    CHECK(protocol_apply_line(&d, "TITLE:Nightcall", 2000) == PROTO_IGNORED);
    CHECK(d.last_rx_ms == 2000);

    CHECK(protocol_apply_line(&d, "ARTIST:Kavinsky", 2000) == PROTO_UPDATED);
    CHECK(strcmp(d.artist, "Kavinsky") == 0);

    CHECK(protocol_apply_line(&d, "SRC:BT", 2000) == PROTO_UPDATED);
    CHECK(strcmp(d.source, "BT") == 0);
    CHECK(protocol_apply_line(&d, "SRC:AA", 2000) == PROTO_UPDATED);
    CHECK(strcmp(d.source, "AA") == 0);
    CHECK(protocol_apply_line(&d, "SRC:---", 2000) == PROTO_UPDATED);
    CHECK(strcmp(d.source, "---") == 0);

    CHECK(protocol_apply_line(&d, "PLAY:1", 2000) == PROTO_UPDATED);
    CHECK(d.playing);
    CHECK(protocol_apply_line(&d, "PLAY:0", 2000) == PROTO_UPDATED);
    CHECK(!d.playing);

    CHECK(protocol_apply_line(&d, "POS:87", 3000) == PROTO_UPDATED);
    CHECK(d.position_s == 87);
    CHECK(d.position_rx_ms == 3000);
    CHECK(protocol_apply_line(&d, "DUR:258", 3000) == PROTO_UPDATED);
    CHECK(d.duration_s == 258);

    CHECK(protocol_apply_line(&d, "CRUISE:1", 3000) == PROTO_UPDATED);
    CHECK(d.cruise);
    CHECK(protocol_apply_line(&d, "SETSPD:130", 3000) == PROTO_UPDATED);
    CHECK(d.set_speed == 130);

    // PING to jedyna linia bez dwukropka, na którą odpowiadamy
    CHECK(protocol_apply_line(&d, "PING", 4000) == PROTO_PING);
    CHECK(d.last_rx_ms == 4000);
}

// --- parser: przypadki brzegowe --------------------------------------------

static void test_protocol_edge_cases(void)
{
    DisplayData d;
    display_data_init(&d);
    protocol_apply_line(&d, "TITLE:Nightcall", 100);
    protocol_apply_line(&d, "SETSPD:130", 100);

    // pusta wartość — pole się czyści, renderer podmieni na "---"
    CHECK(protocol_apply_line(&d, "TITLE:", 200) == PROTO_UPDATED);
    CHECK(d.title[0] == '\0');
    CHECK(protocol_apply_line(&d, "SETSPD:", 200) == PROTO_UPDATED);
    CHECK(d.set_speed == 0);
    CHECK(protocol_apply_line(&d, "POS:", 200) == PROTO_IGNORED);   // było 0
    CHECK(d.position_s == 0);

    // nieznany klucz — ignorowany, ale odświeża znacznik świeżości
    protocol_apply_line(&d, "ARTIST:Kavinsky", 300);
    CHECK(protocol_apply_line(&d, "FOOBAR:cokolwiek", 400) == PROTO_IGNORED);
    CHECK(strcmp(d.artist, "Kavinsky") == 0);
    CHECK(d.last_rx_ms == 400);

    // brak dwukropka — też ignorowany, też dowód życia
    CHECK(protocol_apply_line(&d, "TITLE Nightcall", 500) == PROTO_IGNORED);
    CHECK(strcmp(d.artist, "Kavinsky") == 0);
    CHECK(d.last_rx_ms == 500);

    // klucz podobny, ale nie ten sam
    CHECK(protocol_apply_line(&d, "TITLES:X", 500) == PROTO_IGNORED);
    CHECK(d.title[0] == '\0');

    // pusta linia niczego nie dowodzi
    CHECK(protocol_apply_line(&d, "", 600) == PROTO_IGNORED);
    CHECK(d.last_rx_ms == 500);
    CHECK(protocol_apply_line(&d, "\r", 600) == PROTO_IGNORED);
    CHECK(d.last_rx_ms == 500);

    // CRLF: '\r' zdejmowany także wtedy, gdy linia trafi tu wprost
    CHECK(protocol_apply_line(&d, "ARTIST:Kavinsky\r", 700) == PROTO_IGNORED);
    CHECK(protocol_apply_line(&d, "ARTIST:Perturbator\r", 700) == PROTO_UPDATED);
    CHECK(strcmp(d.artist, "Perturbator") == 0);

    // śmieci zamiast liczby -> 0, nie stara wartość
    protocol_apply_line(&d, "DUR:258", 800);
    CHECK(protocol_apply_line(&d, "DUR:abc", 800) == PROTO_UPDATED);
    CHECK(d.duration_s == 0);

    // sufity
    protocol_apply_line(&d, "SETSPD:99999", 900);
    CHECK(d.set_speed == PROTO_SPEED_MAX);
    protocol_apply_line(&d, "POS:4294967296123", 900);
    CHECK(d.position_s == PROTO_SECONDS_MAX);
    protocol_apply_line(&d, "PLAY:7", 900);
    CHECK(d.playing);

    // wartość z dwukropkiem w środku należy do wartości
    CHECK(protocol_apply_line(&d, "TITLE:Kraftwerk: Autobahn", 1000) == PROTO_UPDATED);
    CHECK(strcmp(d.title, "Kraftwerk: Autobahn") == 0);
}

static void test_protocol_overlong_line(void)
{
    DisplayData d;
    display_data_init(&d);

    // linia dłuższa niż bufor pola: wartość obcięta do PROTO_TITLE_MAX-1
    char line[PROTO_LINE_MAX * 4];
    char body[PROTO_LINE_MAX * 2];
    repeat(body, sizeof(body), "A", 500);
    snprintf(line, sizeof(line), "TITLE:%s", body);
    CHECK(protocol_apply_line(&d, line, 10) == PROTO_UPDATED);
    CHECK(strlen(d.title) == PROTO_TITLE_MAX - 1);

    // linia dłuższa niż bufor składania: nadmiar leci w kosz, ale linia
    // i tak dociera — lepiej obcięty tytuł niż zgubiona aktualizacja
    LineAssembler a;
    line_init(&a);
    bool ready = false;
    for (const char *p = line; *p != '\0'; p++) {
        ready = line_feed(&a, *p);
        CHECK(!ready);
    }
    ready = line_feed(&a, '\n');
    CHECK(ready);
    CHECK(a.truncated);
    CHECK(strlen(a.buf) == PROTO_LINE_MAX - 1);
    CHECK(a.len == 0);   // gotowy do następnej linii
}

static void test_protocol_utf8(void)
{
    DisplayData d;
    display_data_init(&d);

    CHECK(protocol_apply_line(&d, "TITLE:Zażółć gęślą jaźń", 10) == PROTO_UPDATED);
    CHECK(strcmp(d.title, "Zażółć gęślą jaźń") == 0);
    int bad = 0;
    CHECK(decode_all(d.title, &bad) == 17);
    CHECK(bad == 0);

    // 'ą' ma dwa bajty, więc obcięcie do 95 bajtów wypada w POŁOWIE znaku;
    // parser musi zejść do 94 i zostawić poprawne UTF-8
    char line[PROTO_LINE_MAX * 4];
    char body[PROTO_LINE_MAX * 2];
    repeat(body, sizeof(body), "ą", 80);
    snprintf(line, sizeof(line), "TITLE:%s", body);
    CHECK(protocol_apply_line(&d, line, 20) == PROTO_UPDATED);
    CHECK(strlen(d.title) == PROTO_TITLE_MAX - 2);        // 94, nie 95
    CHECK(static_cast<unsigned char>(d.title[93]) == 0x85);
    bad = 0;
    CHECK(decode_all(d.title, &bad) == (PROTO_TITLE_MAX - 2) / 2);
    CHECK(bad == 0);

    // to samo o piętro niżej: obcięcie w LineAssembler też nie może
    // zostawić kaleki na końcu
    LineAssembler a;
    line_init(&a);
    display_data_init(&d);
    feed_line(&a, &d, line, 30);
    feed_line(&a, &d, "\n", 30);
    CHECK(static_cast<unsigned char>(d.title[strlen(d.title) - 1]) == 0x85);
    bad = 0;
    decode_all(d.title, &bad);
    CHECK(bad == 0);

    // sekwencja urwana przez BCM w środku linii — ostatni znak znika
    display_data_init(&d);
    CHECK(protocol_apply_line(&d, "ARTIST:Kavinsk\xC4", 40) == PROTO_UPDATED);
    CHECK(strcmp(d.artist, "Kavinsk") == 0);
}

static void test_protocol_stream(void)
{
    LineAssembler a;
    DisplayData d;
    line_init(&a);
    display_data_init(&d);

    // strumień z CRLF i pustymi liniami — dokładnie tak, jak potrafi
    // wyjść z Pythona po drugiej stronie kabla
    feed_line(&a, &d, "TITLE:Nightcall\r\nARTIST:Kavinsky\n\nSRC:BT\r\nPLAY:1\n", 500);
    CHECK(strcmp(d.title, "Nightcall") == 0);
    CHECK(strcmp(d.artist, "Kavinsky") == 0);
    CHECK(strcmp(d.source, "BT") == 0);
    CHECK(d.playing);

    // linia bez zamykającego '\n' jeszcze nie istnieje
    feed_line(&a, &d, "TITLE:Odyssey", 600);
    CHECK(strcmp(d.title, "Nightcall") == 0);
    feed_line(&a, &d, "\n", 600);
    CHECK(strcmp(d.title, "Odyssey") == 0);
}

static void test_position_extrapolation(void)
{
    DisplayData d;
    display_data_init(&d);
    protocol_apply_line(&d, "DUR:100", 1000);
    protocol_apply_line(&d, "POS:10", 1000);

    CHECK(display_position_now(&d, 1000) == 10);
    CHECK(display_position_now(&d, 3500) == 10);      // pauza: pasek stoi

    protocol_apply_line(&d, "PLAY:1", 2000);
    CHECK(display_position_now(&d, 2000) == 10);
    CHECK(display_position_now(&d, 4500) == 12);      // 2,5 s gry
    CHECK(display_position_now(&d, 200000) == 100);   // nigdy poza koniec
}

// --- debounce ---------------------------------------------------------------

static void set_all(bool *active, bool v)
{
    for (int i = 0; i < INPUT_COUNT; i++) {
        active[i] = v;
    }
}

static void test_debounce(void)
{
    InputState s;
    bool active[INPUT_COUNT];
    set_all(active, false);
    inputs_init(&s, 0);

    CHECK(inputs_update(&s, active, 0) == 0);
    CHECK(!input_active(&s, IN_ABS));

    // ABS zapala się w chwili 100 — przez 30 ms to jeszcze nie fakt
    active[IN_ABS] = true;
    CHECK(inputs_update(&s, active, 100) == 0);
    CHECK(inputs_update(&s, active, 129) == 0);
    CHECK(!input_active(&s, IN_ABS));
    CHECK(inputs_update(&s, active, 130) == (1UL << IN_ABS));
    CHECK(input_active(&s, IN_ABS));
    CHECK(inputs_update(&s, active, 200) == 0);   // stan ustalony, cisza

    // drgania styku: każde odbicie zeruje licznik
    active[IN_ABS] = false;
    CHECK(inputs_update(&s, active, 300) == 0);
    active[IN_ABS] = true;
    CHECK(inputs_update(&s, active, 310) == 0);
    active[IN_ABS] = false;
    CHECK(inputs_update(&s, active, 320) == 0);
    CHECK(inputs_update(&s, active, 349) == 0);
    CHECK(input_active(&s, IN_ABS));              // wciąż zapalona
    CHECK(inputs_update(&s, active, 350) == (1UL << IN_ABS));
    CHECK(!input_active(&s, IN_ABS));

    // dwa wejścia naraz — maska ma oba bity
    active[IN_DOOR_FL] = true;
    active[IN_TRUNK] = true;
    CHECK(inputs_update(&s, active, 400) == 0);
    const uint32_t mask = inputs_update(&s, active, 430);
    CHECK(mask == ((1UL << IN_DOOR_FL) | (1UL << IN_TRUNK)));

    // stan startowy bierzemy wprost z pinów — bez czekania 30 ms
    inputs_init(&s, 1000);
    set_all(active, false);
    active[IN_TRUNK] = true;
    inputs_preset(&s, active, 1000);
    CHECK(input_active(&s, IN_TRUNK));
    CHECK(!input_active(&s, IN_ABS));
    CHECK(inputs_update(&s, active, 1000) == 0);   // nic nowego do zgłoszenia
    CHECK(screen_select(&s) == SCREEN_BODY_OPEN);

    // przekręcenie millis() po 49 dniach nie zawiesza debounce'u
    inputs_init(&s, 0xFFFFFFF0UL);
    set_all(active, false);
    inputs_update(&s, active, 0xFFFFFFF0UL);
    active[IN_IMMO] = true;
    CHECK(inputs_update(&s, active, 0xFFFFFFF0UL) == 0);
    CHECK(inputs_update(&s, active, 0x0000000EUL) == (1UL << IN_IMMO));
}

// --- wybór ekranu -----------------------------------------------------------

static void test_screen_select(void)
{
    InputState s;
    bool active[INPUT_COUNT];
    set_all(active, false);
    inputs_init(&s, 0);
    inputs_update(&s, active, 0);

    CHECK(screen_select(&s) == SCREEN_NOW_PLAYING);

    // kontrolki usterek NIE przełączają ekranu
    active[IN_ABS] = true;
    active[IN_BRAKE] = true;
    active[IN_AIRBAG] = true;
    active[IN_IMMO] = true;
    inputs_update(&s, active, 100);
    inputs_update(&s, active, 200);
    CHECK(screen_select(&s) == SCREEN_NOW_PLAYING);
    CHECK(!inputs_any_open(&s));

    // każdy z sześciu paneli z osobna zasłania ekran 1
    for (int p = 0; p < PANEL_COUNT; p++) {
        set_all(active, false);
        active[PANEL_FIRST + p] = true;
        inputs_update(&s, active, 1000 + 100 * p);
        inputs_update(&s, active, 1050 + 100 * p);
        CHECK(inputs_any_open(&s));
        CHECK(screen_select(&s) == SCREEN_BODY_OPEN);
    }

    // zasłonięcie jest STAŁE — nie znika samo z upływem czasu
    set_all(active, false);
    active[IN_DOOR_RL] = true;
    inputs_update(&s, active, 5000);
    inputs_update(&s, active, 5100);
    CHECK(screen_select(&s) == SCREEN_BODY_OPEN);
    inputs_update(&s, active, 5000000);
    CHECK(screen_select(&s) == SCREEN_BODY_OPEN);

    // ...i wraca dopiero po zamknięciu wszystkiego
    set_all(active, false);
    inputs_update(&s, active, 5000010);
    inputs_update(&s, active, 5000100);
    CHECK(screen_select(&s) == SCREEN_NOW_PLAYING);
}

// --- utrata BCM -------------------------------------------------------------

static void test_bcm_timeout(void)
{
    // zanim przyjdzie pierwsza linia, BCM jest offline
    CHECK(!bcm_online(false, 0, 0));
    CHECK(!bcm_online(false, 0, 100000));

    CHECK(bcm_online(true, 1000, 1000));
    CHECK(bcm_online(true, 1000, 1000 + BCM_TIMEOUT_MS - 1));
    CHECK(!bcm_online(true, 1000, 1000 + BCM_TIMEOUT_MS));
    CHECK(!bcm_online(true, 1000, 60000));

    // przekręcenie millis()
    const uint32_t late = 0xFFFFF000UL;
    CHECK(bcm_online(true, late, static_cast<uint32_t>(late + 4999UL)));
    CHECK(!bcm_online(true, late, static_cast<uint32_t>(late + 5000UL)));

    // ścieżka pełna: strumień -> znacznik -> ocena
    DisplayData d;
    display_data_init(&d);
    CHECK(!bcm_online(d.seen, d.last_rx_ms, 0));
    protocol_apply_line(&d, "TITLE:Nightcall", 10000);
    CHECK(bcm_online(d.seen, d.last_rx_ms, 12000));
    CHECK(!bcm_online(d.seen, d.last_rx_ms, 15000));
    protocol_apply_line(&d, "PING", 15000);
    CHECK(bcm_online(d.seen, d.last_rx_ms, 15000));
}

// --- font -------------------------------------------------------------------

static const Font *const ALL_FONTS[4] = {
    &FONT_TITLE, &FONT_ARTIST, &FONT_LABEL, &FONT_SPEED
};
static const char *const FONT_NAMES[4] = {
    "FONT_TITLE", "FONT_ARTIST", "FONT_LABEL", "FONT_SPEED"
};

static void test_font_charset(void)
{
    // pełny komplet ogonków plus znaki, których używa układ ekranu
    static const uint16_t NEEDED[] = {
        0x0104, 0x0106, 0x0118, 0x0141, 0x0143, 0x00D3, 0x015A, 0x0179, 0x017B,
        0x0105, 0x0107, 0x0119, 0x0142, 0x0144, 0x00F3, 0x015B, 0x017A, 0x017C,
        0x00B0, 0x00B7, 0x2014, 0x2026, '?', ' ', '0', '9', 'k', 'm', '/', 'h', '-'
    };
    for (int f = 0; f < 4; f++) {
        for (size_t i = 0; i < sizeof(NEEDED) / sizeof(NEEDED[0]); i++) {
            if (font_glyph(ALL_FONTS[f], NEEDED[i]) == nullptr) {
                printf("BRAK glifu U+%04X w %s\n", NEEDED[i], FONT_NAMES[f]);
            }
            CHECK(font_glyph(ALL_FONTS[f], NEEDED[i]) != nullptr);
        }
        // brakujący znak nie wywala programu, tylko schodzi do '?'
        CHECK(font_glyph(ALL_FONTS[f], 0x0416) == nullptr);          // Ж
        CHECK(font_glyph_or_fallback(ALL_FONTS[f], 0x0416) != nullptr);
        CHECK(font_glyph_or_fallback(ALL_FONTS[f], 0x0416) ==
              font_glyph(ALL_FONTS[f], '?'));
    }
}

static void test_font_width(void)
{
    CHECK(font_text_width(&FONT_TITLE, "") == 0);
    CHECK(font_text_width(&FONT_TITLE, nullptr) == 0);
    CHECK(font_text_width(nullptr, "cokolwiek") == 0);

    for (int f = 0; f < 4; f++) {
        const Font *fo = ALL_FONTS[f];

        // szerokość to suma advance — dokładnie tak liczy kursor rysowania
        const int sum = font_glyph(fo, 0x0104)->advance +
                        font_glyph(fo, 0x0106)->advance +
                        font_glyph(fo, 0x0118)->advance;
        CHECK(font_text_width(fo, "ĄĆĘ") == sum);

        // Ogonki NIE schodzą po cichu do '?' — inaczej "Zażółć" wyszłoby
        // jak "Za???". Liczymy sumę advance po codepointach z ręki
        // i porównujemy z tym, co wychodzi z dekodera UTF-8.
        static const uint16_t ZAZOLC[] = {
            'Z', 'a', 0x017C, 0x00F3, 0x0142, 0x0107, ' ',
            'g', 0x0119, 0x015B, 'l', 0x0105, ' ',
            'j', 'a', 0x017A, 0x0144
        };
        int expect = 0;
        for (size_t k = 0; k < sizeof(ZAZOLC) / sizeof(ZAZOLC[0]); k++) {
            const Glyph *g = font_glyph(fo, ZAZOLC[k]);
            CHECK(g != nullptr);
            expect += g->advance;
        }
        CHECK(font_text_width(fo, "Zażółć gęślą jaźń") == expect);
        CHECK(font_text_width(fo, "ż") == font_glyph(fo, 0x017C)->advance);

        // spoza zestawu: cyrylica i emoji spadają na '?', nie na śmieci
        const int q = font_text_width(fo, "?");
        CHECK(font_text_width(fo, "Ж") == q);
        CHECK(font_text_width(fo, "\xF0\x9F\x98\x80") == q);   // U+1F600
        CHECK(font_text_width(fo, "\xC4") == q);               // urwana sekwencja
        CHECK(font_text_width(fo, "\x85") == q);               // sam bajt ciągły
    }

    // tytuł musi się mieścić w polu 112 px w rozsądnych przypadkach
    CHECK(font_text_width(&FONT_TITLE, "Nightcall") <= 112);
    CHECK(font_text_width(&FONT_ARTIST, "Kavinsky") <= 112);
    CHECK(font_text_width(&FONT_SPEED, "130") <= 62);
    CHECK(font_text_width(&FONT_LABEL, "km/h") <= 30);
}

static void test_font_fit(void)
{
    static const char *const SAMPLES[] = {
        "Nightcall",
        "Zażółć gęślą jaźń",
        "ąąąąąąąąąąąąąąąą",
        "Kraftwerk — Autobahn",
        ""
    };

    for (int f = 0; f < 4; f++) {
        const Font *fo = ALL_FONTS[f];
        for (size_t i = 0; i < sizeof(SAMPLES) / sizeof(SAMPLES[0]); i++) {
            const char *s = SAMPLES[i];
            const int len = static_cast<int>(strlen(s));
            const int w = font_text_width(fo, s);

            CHECK(font_fit(fo, s, w) == len);          // całość mieści się w całości
            CHECK(font_fit(fo, s, w + 100) == len);
            CHECK(font_fit(fo, s, 0) == 0);
            CHECK(font_fit(fo, s, -5) == 0);
            if (len > 0) {
                CHECK(font_fit(fo, s, w - 1) < len);   // o piksel za mało = mniej znaków
            }

            // cięcie ZAWSZE na granicy znaku: prefiks musi się dekodować
            // bez ani jednego '?' (a to napisy z ogonkami)
            for (int px = 0; px <= w; px++) {
                char cut[128];
                const int n = font_fit(fo, s, px);
                CHECK(n >= 0 && n <= len);
                CHECK(n < static_cast<int>(sizeof(cut)));
                memcpy(cut, s, static_cast<size_t>(n));
                cut[n] = '\0';
                int bad = 0;
                decode_all(cut, &bad);
                CHECK(bad == 0);
                CHECK(font_text_width(fo, cut) <= px);
            }
        }
    }

    CHECK(font_fit(nullptr, "abc", 100) == 0);
    CHECK(font_fit(&FONT_TITLE, nullptr, 100) == 0);
}

static void test_utf8_next(void)
{
    int pos = 0;
    CHECK(utf8_next("A", &pos) == 'A');
    CHECK(pos == 1);
    CHECK(utf8_next("A", &pos) == -1);

    pos = 0;
    CHECK(utf8_next("ż", &pos) == 0x017C);
    CHECK(pos == 2);

    pos = 0;
    CHECK(utf8_next("\xE2\x80\xA6", &pos) == 0x2026);   // …
    CHECK(pos == 3);

    // urwana sekwencja: '?' i pozycja idzie do przodu, więc pętla dobiega
    pos = 0;
    CHECK(utf8_next("\xC4", &pos) == '?');
    CHECK(pos > 0);
    pos = 0;
    CHECK(utf8_next("\x85_", &pos) == '?');
    CHECK(pos == 1);
}


// --- składanie napisów (text_layout.h) --------------------------------------
//
// To tu ląduje wszystko, co przychodzi z internetu: pusty tytuł, tytuł na
// pół ekranu, cyrylica, emoji. Sprawdzamy trzy rzeczy naraz: napis mieści
// się w polu, nie rozpada się w połowie znaku UTF-8 i NIGDY nie wychodzi
// poza podany bufor.

enum { GUARD_PAD = 16, GUARD_TOTAL = 320 };
static char g_guard[GUARD_TOTAL];

// Bufor o pojemności `cap` otoczony wartownikiem 0x7E z obu stron.
static char *guard_open(int cap)
{
    memset(g_guard, 0x7E, sizeof(g_guard));
    (void)cap;
    return g_guard + GUARD_PAD;
}

static bool guard_intact(int cap)
{
    for (int i = 0; i < GUARD_PAD; i++) {
        if (g_guard[i] != 0x7E) {
            return false;
        }
    }
    for (size_t i = static_cast<size_t>(GUARD_PAD + cap); i < sizeof(g_guard); i++) {
        if (g_guard[i] != 0x7E) {
            return false;
        }
    }
    return true;
}

// Napisy, na których wykłada się naiwne przycinanie.
static const char *const TEXT_SAMPLES[] = {
    "",
    " ",
    "   ",
    "A",
    "Nightcall",
    "Zażółć gęślą jaźń",
    "Kraftwerk — Autobahn ’78",
    "ĄĆĘŁŃÓŚŹŻąćęłńóśźż ĄĆĘŁŃÓŚŹŻąćęłńóśźż ĄĆĘŁŃÓŚŹŻ",
    "Жжжж Ж Ж Ж ЖЖЖ",                                   // spoza zestawu
    "\xF0\x9F\x98\x80\xF0\x9F\x98\x80 emoji",            // U+1F600
    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "słowo słowo słowo słowo słowo słowo słowo słowo słowo słowo",
    "aiiiiiiiiiiiiiiiiiiiiiiiit",                        // FONT_TITLE: równo 111 px
    "jaaaiiiiiiiiiiiiiiiiiiii",                          // FONT_TITLE: równo 112 px
    "  wiodące i końcowe spacje  ",
};
enum { TEXT_SAMPLE_COUNT = sizeof(TEXT_SAMPLES) / sizeof(TEXT_SAMPLES[0]) };

static void test_text_fit_ellipsis(void)
{
    static const char ELL[] = "\xE2\x80\xA6";

    for (int f = 0; f < 4; f++) {
        const Font *fo = ALL_FONTS[f];
        for (int i = 0; i < TEXT_SAMPLE_COUNT; i++) {
            const char *src = TEXT_SAMPLES[i];
            for (int max_px = 0; max_px <= 128; max_px += 8) {
                const int cap = 200;
                char *dst = guard_open(cap);
                text_fit_ellipsis(fo, src, max_px, dst, cap);

                CHECK(guard_intact(cap));
                CHECK(strlen(dst) < static_cast<size_t>(cap));

                // nic się nie rozpadło w połowie znaku
                int bad = 0;
                decode_all(dst, &bad);
                CHECK(bad == 0);

                if (font_text_width(fo, src) <= max_px) {
                    CHECK(strcmp(dst, src) == 0);          // mieści się w całości
                } else {
                    // przycięte: mieści się w polu i kończy wielokropkiem
                    CHECK(font_text_width(fo, dst) <= max_px ||
                          font_text_width(fo, ELL) > max_px);
                    const size_t n = strlen(dst);
                    CHECK(n >= 3 && memcmp(dst + n - 3, ELL, 3) == 0);
                }
            }
        }
    }

    // ciasne bufory: ani bajtu poza cap, zawsze zero na końcu
    for (int cap = 1; cap <= 8; cap++) {
        char *dst = guard_open(cap);
        text_fit_ellipsis(&FONT_TITLE, "Zażółć gęślą jaźń bardzo długo", 40, dst, cap);
        CHECK(guard_intact(cap));
        CHECK(strlen(dst) < static_cast<size_t>(cap));
        int bad = 0;
        decode_all(dst, &bad);
        CHECK(bad == 0);
    }

    // wskaźniki zerowe i cap <= 0 nie wywalają programu
    char *dst = guard_open(16);
    text_fit_ellipsis(&FONT_TITLE, nullptr, 100, dst, 16);
    CHECK(dst[0] == '\0');
    CHECK(guard_intact(16));
    text_fit_ellipsis(&FONT_TITLE, "cokolwiek", 100, nullptr, 16);
    text_fit_ellipsis(&FONT_TITLE, "cokolwiek", 100, dst, 0);
    CHECK(guard_intact(16));
}

static void test_text_wrap_two_lines(void)
{
    static const char ELL[] = "\xE2\x80\xA6";
    const int max_px = 112;                    // TEXT_W ze sketcha

    for (int i = 0; i < TEXT_SAMPLE_COUNT; i++) {
        const char *src = TEXT_SAMPLES[i];
        char l1[200];
        const int cap2 = 200;
        char *l2 = guard_open(cap2);
        memset(l1, 0, sizeof(l1));

        text_wrap_two_lines(&FONT_TITLE, src, max_px,
                            l1, static_cast<int>(sizeof(l1)), l2, cap2);

        CHECK(guard_intact(cap2));
        CHECK(font_text_width(&FONT_TITLE, l1) <= max_px);
        CHECK(font_text_width(&FONT_TITLE, l2) <= max_px);

        int bad1 = 0, bad2 = 0;
        decode_all(l1, &bad1);
        decode_all(l2, &bad2);
        CHECK(bad1 == 0);
        CHECK(bad2 == 0);

        if (src[0] == '\0') {
            CHECK(l1[0] == '\0' && l2[0] == '\0');
        }
        if (font_text_width(&FONT_TITLE, src) <= max_px) {
            CHECK(strcmp(l1, src) == 0);       // jedna linia, bez łamania
            CHECK(l2[0] == '\0');
        } else {
            CHECK(l1[0] != '\0');              // pierwsza linia nie może być pusta
            CHECK(l2[0] != '\0');
            const size_t n = strlen(l2);
            if (n >= 3 && memcmp(l2 + n - 3, ELL, 3) != 0) {
                // druga linia bez wielokropka = zmieścił się cały ogon
                CHECK(font_text_width(&FONT_TITLE, l2) <= max_px);
            }
        }
    }

    // jedno bardzo długie słowo bez spacji — łamanie twarde
    char l1[200], l2[200];
    text_wrap_two_lines(&FONT_TITLE,
                        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                        max_px, l1, static_cast<int>(sizeof(l1)),
                        l2, static_cast<int>(sizeof(l2)));
    CHECK(l1[0] == 'a' && l2[0] == 'a');
    CHECK(font_text_width(&FONT_TITLE, l1) <= max_px);
    CHECK(font_text_width(&FONT_TITLE, l2) <= max_px);

    // łamanie po spacji: pierwsza linia nie kończy się spacją
    text_wrap_two_lines(&FONT_TITLE,
                        "Kraftwerk Autobahn Trans Europa Express Radioaktivitat",
                        max_px, l1, static_cast<int>(sizeof(l1)),
                        l2, static_cast<int>(sizeof(l2)));
    CHECK(l1[strlen(l1) - 1] != ' ');
    CHECK(l2[0] != ' ');

    // ciasne bufory i wskaźniki zerowe
    for (int cap = 1; cap <= 6; cap++) {
        char *small = guard_open(cap);
        char big[200];
        text_wrap_two_lines(&FONT_TITLE, "Zażółć gęślą jaźń i jedź dalej przez noc",
                            max_px, big, static_cast<int>(sizeof(big)), small, cap);
        CHECK(guard_intact(cap));
        CHECK(strlen(small) < static_cast<size_t>(cap));
    }
    text_wrap_two_lines(&FONT_TITLE, nullptr, max_px, l1, 200, l2, 200);
    CHECK(l1[0] == '\0' && l2[0] == '\0');
    text_wrap_two_lines(&FONT_TITLE, "cos", max_px, nullptr, 0, l2, 200);
}

static void test_text_compose_source(void)
{
    char buf[32];

    // Kabel niesie kod ("BT"/"AA"), panel pokazuje nazwę — tak jak projekt
    // ekranów w mockups/esp32_1v8/.
    text_compose_source(buf, sizeof(buf), "BT", true, true);
    CHECK(strcmp(buf, "BLUETOOTH") == 0);

    text_compose_source(buf, sizeof(buf), "BT", true, false);
    CHECK(strcmp(buf, "BLUETOOTH \xC2\xB7 PAUZA") == 0);

    text_compose_source(buf, sizeof(buf), "AA", true, true);
    CHECK(strcmp(buf, "ANDROID AUTO") == 0);

    text_compose_source(buf, sizeof(buf), "AA", true, false);
    CHECK(strcmp(buf, "ANDROID AUTO \xC2\xB7 PAUZA") == 0);

    // nieznany kod przepisujemy żywcem — protokół wolno rozszerzyć
    text_compose_source(buf, sizeof(buf), "FM", true, true);
    CHECK(strcmp(buf, "FM") == 0);

    // BCM offline — zostaje samo "---", nawet gdy w pamięci wisi stare źródło
    text_compose_source(buf, sizeof(buf), "BT", false, true);
    CHECK(strcmp(buf, "---") == 0);
    text_compose_source(buf, sizeof(buf), "BT", false, false);
    CHECK(strcmp(buf, "---") == 0);

    // puste źródło też daje "---", bez dopisku o pauzie
    text_compose_source(buf, sizeof(buf), "", true, false);
    CHECK(strcmp(buf, "---") == 0);
    text_compose_source(buf, sizeof(buf), nullptr, true, false);
    CHECK(strcmp(buf, "---") == 0);

    // linia źródła mieści się w polu tekstu (112 px) także w najdłuższym
    // wariancie, czyli "ANDROID AUTO · PAUZA"
    for (int i = 0; i < 3; i++) {
        static const char *CODES[3] = {"BT", "AA", "---"};
        text_compose_source(buf, sizeof(buf), CODES[i], true, false);
        CHECK(font_text_width(&FONT_LABEL, buf) <= 112);
        text_compose_source(buf, sizeof(buf), CODES[i], true, true);
        CHECK(font_text_width(&FONT_LABEL, buf) <= 112);
    }

    // ciasny bufor: ani bajtu poza cap, końcówka nie rozpada się na pół znaku
    for (int cap = 1; cap <= 20; cap++) {
        char *dst = guard_open(cap);
        text_compose_source(dst, cap, "BT", true, false);
        CHECK(guard_intact(cap));
        CHECK(strlen(dst) < static_cast<size_t>(cap));
        int bad = 0;
        decode_all(dst, &bad);
        CHECK(bad == 0);
    }
    text_compose_source(nullptr, 16, "BT", true, true);
}

// Atrament glifu potrafi wyjść poza własne `advance` — i to jest powód,
// dla którego sketch czyści CAŁY wiersz, a nie samo pole tekstu.
// Tu pilnujemy, żeby po regeneracji fontu wysięg nie urósł tak, że napis
// wyśrodkowany w panelu zaczyna wychodzić poza sam panel.
static void test_font_ink_bounds(void)
{
    enum { PANEL_W = 128, FIELD_W = 112 };   // DISPLAY_W i TEXT_W ze sketcha

    for (int f = 0; f < 4; f++) {
        const Font *fo = ALL_FONTS[f];
        int left = 0;      // najdalej w lewo od kursora
        int right = 0;     // najdalej w prawo poza advance
        for (uint16_t k = 0; k < fo->count; k++) {
            const Glyph &g = fo->glyphs[k];
            if (g.xoff < left) {
                left = g.xoff;
            }
            const int over = static_cast<int>(g.xoff) + static_cast<int>(g.w) -
                             static_cast<int>(g.advance);
            if (over > right) {
                right = over;
            }
            // atrament nie może wyjść poza wiersz nad linią bazową ani pod nią
            CHECK(-g.yoff <= fo->baseline);
            CHECK(g.yoff + g.h <= fo->line_height - fo->baseline);
        }

        // napis o maksymalnej szerokości pola, wyśrodkowany w panelu
        const int x = PANEL_W / 2 - FIELD_W / 2;
        CHECK(x + left >= 0);
        CHECK(x + FIELD_W + right - 1 < PANEL_W);
    }
}

// ---------------------------------------------------------------------------

int main(void)
{
    test_protocol_basics();
    test_protocol_edge_cases();
    test_protocol_overlong_line();
    test_protocol_utf8();
    test_protocol_stream();
    test_position_extrapolation();
    test_debounce();
    test_screen_select();
    test_bcm_timeout();
    test_font_charset();
    test_font_width();
    test_font_fit();
    test_utf8_next();
    test_text_fit_ellipsis();
    test_text_wrap_two_lines();
    test_text_compose_source();
    test_font_ink_bounds();

    printf("esp32_display: OK (%d asercji)\n", g_checks);
    return 0;
}
