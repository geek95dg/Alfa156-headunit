/*
 * BCM v8.5 — wyświetlacz pomocniczy 1,8" (ST7735 128x160, pionowo) na ESP32-S3
 *
 * Czwarta płytka w systemie i jedyna, która nic nie mierzy — sama pokazuje.
 * Dwa ekrany, opisane w docs/WYSWIETLACZ_ESP32_1V8.md:
 *
 *   ekran 1  Now Playing: pasmo kontrolek (32 px), metadane muzyki (90 px),
 *            pasmo tempomatu (36 px)
 *   ekran 2  otwarte nadwozie — rzut z góry z podświetlonymi panelami
 *
 * Zasłonięcie ekranem 2 jest STAŁE: dopóki cokolwiek jest otwarte, muzyka
 * nie wraca. Bez timeoutu, bez mrugania na przemian.
 *
 * Ten plik to WYŁĄCZNIE I/O: SPI do panelu, GPIO z transoptorów, USB CDC,
 * LEDC na podświetlenie. Cała logika, którą da się przetestować bez płytki,
 * siedzi obok i kompiluje się zwykłym g++:
 *
 *   protocol.h     parser linii KLUCZ:wartość z BCM
 *   state.h        debounce wejść, wybór ekranu, wykrycie utraty BCM
 *   font_draw.h    metryki i przycinanie tekstu UTF-8
 *   text_layout.h  łamanie tytułu, wielokropek, linia źródła
 *   test/test_host.cpp   -> make -C arduino esp32_display-test
 *
 * Dane graficzne są wygenerowane i nietykalne: assets.h (tools/esp32_assets.py)
 * i font.h (tools/esp32_font.py).
 *
 * --- Mapa pinów (ESP32-S3) ---
 *   TFT SPI:  SCK=12  MOSI=11  CS=10  DC=13  RST=14  BL=21 (LEDC, PWM)
 *   Wejścia z PC817, INPUT_PULLUP, stan aktywny LOW:
 *     ABS=4  hamulec=5  poduszka=6  immobilizer=7
 *     drzwi FL=15  FR=16  RL=17  RR=18  maska=1  bagażnik=2
 *   Zajęte/zakazane: 0, 3, 45, 46 (strapping), 19, 20 (USB), 26-37 (flash/PSRAM).
 *
 * --- Konfiguracja TFT_eSPI ---
 * Biblioteka czyta ustawienia z własnego User_Setup.h, czyli z KATALOGU
 * BIBLIOTEKI — a tego nie chcemy trzymać poza repo. Dlatego komplet definicji
 * idzie flagami kompilatora; robi to za nas arduino/Makefile (zmienna
 * TFT_ESPI_FLAGS), a ręcznie wygląda to tak:
 *
 *   arduino-cli compile --profile default \
 *     --build-property "compiler.cpp.extra_flags=-DUSER_SETUP_LOADED=1 \
 *        -DST7735_DRIVER=1 -DST7735_GREENTAB3=1 -DTFT_WIDTH=128 -DTFT_HEIGHT=160 \
 *        -DTFT_MISO=-1 -DTFT_MOSI=11 -DTFT_SCLK=12 -DTFT_CS=10 -DTFT_DC=13 \
 *        -DTFT_RST=14 -DLOAD_GLCD=1 -DSPI_FREQUENCY=27000000" \
 *     arduino/esp32_display
 *
 * ST7735 chodzi w kilku odmianach ("taby") różniących się przesunięciem
 * początku obrazu i inwersją kolorów. Jeśli obraz jest przesunięty o kilka
 * pikseli albo ma odwrócone barwy, podmień ST7735_GREENTAB3 na
 * ST7735_REDTAB / ST7735_BLACKTAB / ST7735_GREENTAB — to jedyna rzecz w tym
 * projekcie, której nie da się ustalić inaczej niż patrząc na panel.
 *
 * Podświetlenia NIE oddajemy bibliotece (żadnego -DTFT_BL): pin 21 obsługuje
 * LEDC, żeby dało się ściemniać razem z resztą kokpitu (arduino.light_level).
 *
 * --- USB CDC ---
 * ESP32-S3 wpina się wprost w port M910q i zgłasza jako CDC-ACM (303a:1001),
 * bez mostka UART. W profilu jest USBMode=hwcdc + CDCOnBoot=cdc, więc
 * `Serial` to ten natywny port. Uwaga: otwarcie portu przy 1200 bps rzuca
 * płytkę w bootloader — po stronie BCM otwieramy wyłącznie 115200.
 */
#if !defined(ARDUINO_ARCH_ESP32)
#error "Ten sketch jest pod ESP32-S3 (fqbn esp32:esp32:esp32s3)."
#endif

#include <TFT_eSPI.h>

#include "assets.h"
#include "font.h"
#include "font_draw.h"
#include "protocol.h"
#include "state.h"
#include "text_layout.h"

#if (TFT_WIDTH != DISPLAY_W) || (TFT_HEIGHT != DISPLAY_H)
#error "TFT_eSPI skonfigurowane na inny panel niż 128x160 z assets.h."
#endif

// --- paleta Heritage, RGB565 ------------------------------------------------
// Te same wartości co w motywie kokpitu (docs/WYSWIETLACZ_ESP32_1V8.md).
#define RGB565(r, g, b) \
    ((uint16_t)((((r) & 0xF8) << 8) | (((g) & 0xFC) << 3) | ((b) >> 3)))

static const uint16_t COL_BG     = RGB565(0x0a, 0x0a, 0x0a);  // tło
static const uint16_t COL_TEXT   = RGB565(0xf4, 0xf4, 0xf5);  // tytuł
static const uint16_t COL_DIM    = RGB565(0xa1, 0xa1, 0xaa);  // wykonawca
static const uint16_t COL_MUTED  = RGB565(0x52, 0x52, 0x5b);  // źródło, jednostki
static const uint16_t COL_LINE   = RGB565(0x27, 0x27, 0x2a);  // linie, tło paska
static const uint16_t COL_ACCENT = RGB565(0xf5, 0x9e, 0x0b);  // pasek postępu
static const uint16_t COL_OFF    = RGB565(0x3f, 0x3f, 0x46);  // symbol wygaszony
static const uint16_t COL_CRUISE = RGB565(0x22, 0xc5, 0x5e);  // tempomat aktywny

// --- układ ekranu 1, w pikselach panelu -------------------------------------
//
//   0..31    pasmo górne: cztery kontrolki 26x26
//   32       linia podziału
//   33..122  metadane: źródło, tytuł (do 2 linii), wykonawca, pasek
//   123      linia podziału
//   124..159 pasmo dolne: lewa komórka 40 px pusta (rezerwa), prawa tempomat
//
enum {
    TELLTALE_Y   = 3,      // (32 - 26) / 2
    LINE_TOP_Y   = 32,
    LINE_BOT_Y   = 123,

    TEXT_X       = 8,      // pole tekstu ma 112 px szerokości
    TEXT_W       = 112,

    SRC_Y        = 38,     // FONT_LABEL,  line_height 9
    SRC_H        = 9,
    TITLE_Y      = 50,     // FONT_TITLE,  2 x line_height 19
    TITLE_H      = 38,
    ARTIST_Y     = 90,     // FONT_ARTIST, line_height 13
    ARTIST_H     = 13,

    BAR_X        = 12,     // (128 - 104) / 2
    BAR_Y        = 112,
    BAR_W        = 104,
    BAR_H        = 3,

    RESERVE_W    = 40,     // lewa komórka pasma dolnego — celowo pusta

    CRUISE_CX    = 53,     // tarcza tempomatu
    CRUISE_CY    = 142,
    CRUISE_R     = 9,
    CRUISE_BOX_X = 42,     // prostokąt do czyszczenia tarczy
    CRUISE_BOX_Y = 132,
    CRUISE_BOX_W = 23,
    CRUISE_BOX_H = 21,

    SPD_X        = 64,     // "130 km/h" wyśrodkowane w tym polu
    SPD_Y        = 132,
    SPD_W        = 64,
    SPD_H        = 20,     // FONT_SPEED, line_height 20
    SPD_GAP      = 3       // odstęp między liczbą a jednostką
};

// Cztery kontrolki 26x26 rozstawione równomiernie w 128 px:
// środek i-tej wypada na (i + 0,5) * 32.
static const int16_t TELLTALE_X[TELLTALE_COUNT] = {3, 35, 67, 99};

// --- piny -------------------------------------------------------------------
// Kolejność MUSI odpowiadać InputId ze state.h.
static const uint8_t INPUT_PINS[INPUT_COUNT] = {
    4,   // IN_ABS
    5,   // IN_BRAKE
    6,   // IN_AIRBAG
    7,   // IN_IMMO
    1,   // IN_BONNET
    15,  // IN_DOOR_FL
    16,  // IN_DOOR_FR
    17,  // IN_DOOR_RL
    18,  // IN_DOOR_RR
    2    // IN_TRUNK
};

static const uint8_t PIN_BACKLIGHT = 21;

enum {
    BL_FREQ_HZ  = 5000,
    BL_RES_BITS = 8,
    BL_CHANNEL  = 0,     // tylko dla rdzenia 2.x, 3.x adresuje pinem
    BL_DUTY     = 220,   // docelowa jasność; tu wpina się ściemnianie
    SERIAL_BYTES_PER_LOOP = 256
};

// --- stan -------------------------------------------------------------------
static TFT_eSPI      tft;
static DisplayData   g_data;
static LineAssembler g_line;
static InputState    g_inputs;

// Kopia tego, CO AKTUALNIE WISI NA PANELU. Rysujemy różnicowo: pełna klatka
// to 128*160*2 = 40 KB po SPI (~12 ms przy 27 MHz) i widoczne mrugnięcie przy
// każdym czyszczeniu tła. Pasek postępu rusza się co sekundę, a metadane
// potrafią stać godzinami — przemalowywanie przy tym całego ekranu byłoby
// marnotrawstwem i psuło obraz. Dlatego każdy element ma tu swoją ostatnią
// narysowaną wartość i trafia na panel dopiero, gdy się od niej różni.
// Wyjątek: przełączenie ekranu (full = true) maluje wszystko od zera.
struct Shown {
    bool     valid;
    uint8_t  screen;
    bool     telltale[TELLTALE_COUNT];
    bool     panel[PANEL_COUNT];
    char     source[32];   // "ANDROID AUTO · PAUZA" to 21 B — z zapasem
    char     title[PROTO_TITLE_MAX];
    char     artist[PROTO_ARTIST_MAX];
    uint16_t bar_px;
    bool     cruise;
    char     speed[8];
};
static Shown g_shown;

// --- prymitywy rysowania ----------------------------------------------------

// Blit nieprzezroczystego prostokąta RGB565 prosto z flasha. Na ESP32 PROGMEM
// jest mapowane w przestrzeń adresową, więc wskaźnik z assets.h czyta się
// zwyczajnie — tak samo robi font_draw.h. const_cast, bo TFT_eSPI bierze
// wskaźnik bez const, choć danych nie rusza.
static inline void blit(int16_t x, int16_t y, uint16_t w, uint16_t h,
                        const uint16_t *data)
{
    tft.pushImage(x, y, w, h, const_cast<uint16_t *>(data));
}

static inline void clearRect(int16_t x, int16_t y, int16_t w, int16_t h)
{
    tft.fillRect(x, y, w, h, COL_BG);
}

// Czyszczenie WIERSZA tekstu na całej szerokości panelu. Pole tekstu ma
// 112 px (TEXT_X..TEXT_X+TEXT_W-1), ale atrament glifu potrafi wyjść poza
// własne `advance`: kilka znaków ma prawy nawis 1 px, a 'j' w FONT_TITLE
// ma xoff = -1. Napis dociśnięty przez font_fit() dokładnie do 112 px
// zostawiłby wtedy jedną kolumnę pikseli TUŻ obok pola — i nikt by jej
// nigdy nie zmazał, bo kolejne przerysowanie czyści tylko samo pole.
// W pasmie środkowym (33..122) poza tekstem i paskiem nic nie leży,
// więc czyścimy bezpiecznie od krawędzi do krawędzi.
static inline void clearTextRow(int16_t y, int16_t h)
{
    tft.fillRect(0, y, DISPLAY_W, h, COL_BG);
}

// Tekst z fontu bitmapowego: 1 bit na piksel, wiersz wyrównany do bajtu,
// MSB pierwszy. Rysujemy wyłącznie zapalone piksele (tło jest już czyste),
// całymi poziomymi ciągami — drawPixel na każdy punkt kosztowałby kilka razy
// więcej transakcji SPI. `baseline` to linia bazowa, nie górna krawędź.
static void drawText(const Font *f, const char *utf8, int16_t x, int16_t baseline,
                     uint16_t color)
{
    if (f == nullptr || utf8 == nullptr) {
        return;
    }
    int cursor = x;
    int pos = 0;
    tft.startWrite();
    for (;;) {
        const int cp = utf8_next(utf8, &pos);
        if (cp < 0) {
            break;
        }
        const Glyph *g = font_glyph_or_fallback(f, cp);
        if (g == nullptr) {
            continue;
        }
        const int stride = (g->w + 7) / 8;
        const uint8_t *bits = f->bitmaps + g->offset;
        const int gx = cursor + g->xoff;
        const int gy = baseline + g->yoff;
        for (int row = 0; row < g->h; row++) {
            const uint8_t *line = bits + row * stride;
            int col = 0;
            while (col < g->w) {
                if ((line[col >> 3] >> (7 - (col & 7))) & 1) {
                    int run = 1;
                    while (col + run < g->w &&
                           ((line[(col + run) >> 3] >> (7 - ((col + run) & 7))) & 1)) {
                        run++;
                    }
                    tft.drawFastHLine(gx + col, gy + row, run, color);
                    col += run;
                } else {
                    col++;
                }
            }
        }
        cursor += g->advance;
    }
    tft.endWrite();
}

static void drawTextCentered(const Font *f, const char *utf8, int16_t cx,
                             int16_t baseline, uint16_t color)
{
    const int w = font_text_width(f, utf8);
    drawText(f, utf8, static_cast<int16_t>(cx - w / 2), baseline, color);
}

// --- ekran 1 ----------------------------------------------------------------

static void drawTitleBlock(const char *title)
{
    char l1[PROTO_TITLE_MAX + 8];
    char l2[PROTO_TITLE_MAX + 8];
    text_wrap_two_lines(&FONT_TITLE, title, TEXT_W,
                        l1, static_cast<int>(sizeof(l1)),
                        l2, static_cast<int>(sizeof(l2)));

    clearTextRow(TITLE_Y, TITLE_H);
    const int lh = FONT_TITLE.line_height;
    if (l2[0] == '\0') {
        // jedna linia — wyśrodkowana w pionie w slocie dwuliniowym
        drawTextCentered(&FONT_TITLE, l1, DISPLAY_W / 2,
                         TITLE_Y + (TITLE_H - lh) / 2 + FONT_TITLE.baseline, COL_TEXT);
    } else {
        drawTextCentered(&FONT_TITLE, l1, DISPLAY_W / 2,
                         TITLE_Y + FONT_TITLE.baseline, COL_TEXT);
        drawTextCentered(&FONT_TITLE, l2, DISPLAY_W / 2,
                         TITLE_Y + lh + FONT_TITLE.baseline, COL_TEXT);
    }
}

// `on` decyduje o kolorze tarczy i liczby, `with_unit` o dopisku "km/h" —
// bo tempomat potrafi być włączony przy jeszcze nieznanej zadanej prędkości
// (BCM wysyła wtedy puste SETSPD) i "0 km/h" byłoby zwyczajnym kłamstwem.
static void drawCruiseCell(bool on, const char *speed, bool with_unit)
{
    const uint16_t col = on ? COL_CRUISE : COL_OFF;

    clearRect(CRUISE_BOX_X, CRUISE_BOX_Y, CRUISE_BOX_W, CRUISE_BOX_H);
    clearRect(SPD_X, SPD_Y, SPD_W, SPD_H);

    // Tarcza tempomatu jedyna rysowana prymitywami: assets.h dostarcza tylko
    // cztery kontrolki górnego pasma (ABS, hamulec, poduszka, immobilizer),
    // renderu tempomatu tam nie ma. Okrąg z igłą i piastą czyta się tak samo,
    // a nie dokłada kolejnego kilobajta do flasha.
    tft.drawCircle(CRUISE_CX, CRUISE_CY, CRUISE_R, col);
    tft.drawLine(CRUISE_CX, CRUISE_CY, CRUISE_CX + 5, CRUISE_CY - 5, col);
    tft.fillCircle(CRUISE_CX, CRUISE_CY, 1, col);

    const int sw = font_text_width(&FONT_SPEED, speed);
    const int uw = with_unit ? font_text_width(&FONT_LABEL, "km/h") : 0;
    const int gap = with_unit ? SPD_GAP : 0;
    int x = SPD_X + (SPD_W - (sw + gap + uw)) / 2;
    if (x < SPD_X) {
        x = SPD_X;
    }
    drawText(&FONT_SPEED, speed, static_cast<int16_t>(x), SPD_Y + FONT_SPEED.baseline, col);
    if (with_unit) {
        drawText(&FONT_LABEL, "km/h", static_cast<int16_t>(x + sw + gap),
                 SPD_Y + FONT_SPEED.baseline, COL_MUTED);
    }
}

static void renderNowPlaying(bool full, uint32_t now)
{
    const bool online = bcm_online(g_data.seen, g_data.last_rx_ms, now);

    if (full) {
        tft.fillScreen(COL_BG);
        tft.drawFastHLine(0, LINE_TOP_Y, DISPLAY_W, COL_LINE);
        tft.drawFastHLine(0, LINE_BOT_Y, DISPLAY_W, COL_LINE);
        // Lewa komórka pasma dolnego (0..39 px) zostaje pusta — rezerwa
        // pod kolejną kontrolkę, świadomie nieobsadzona.
    }

    // 1. kontrolki — każda osobno, tylko przy zmianie stanu
    for (uint8_t i = 0; i < TELLTALE_COUNT; i++) {
        const bool lit = input_active(&g_inputs, static_cast<uint8_t>(TELLTALE_FIRST + i));
        if (full || lit != g_shown.telltale[i]) {
            blit(TELLTALE_X[i], TELLTALE_Y, TELLTALE_SIZE, TELLTALE_SIZE,
                 lit ? TELLTALES[i].lit : TELLTALES[i].off);
            g_shown.telltale[i] = lit;
        }
    }

    // 2. źródło dźwięku
    char source[sizeof(g_shown.source)];
    text_compose_source(source, static_cast<int>(sizeof(source)),
                        g_data.source, online, g_data.playing);
    if (full || strcmp(source, g_shown.source) != 0) {
        clearTextRow(SRC_Y, SRC_H);
        drawTextCentered(&FONT_LABEL, source, DISPLAY_W / 2,
                         SRC_Y + FONT_LABEL.baseline, COL_MUTED);
        memcpy(g_shown.source, source, strlen(source) + 1);
    }

    // 3. tytuł — po utracie BCM metadane gasną do "---"
    const char *title = (online && g_data.title[0] != '\0') ? g_data.title : "---";
    if (full || strcmp(title, g_shown.title) != 0) {
        drawTitleBlock(title);
        proto_copy_text(g_shown.title, static_cast<int>(sizeof(g_shown.title)),
                        title, static_cast<int>(strlen(title)));
    }

    // 4. wykonawca — zawsze jedna linia z wielokropkiem
    const char *artist = (online && g_data.artist[0] != '\0') ? g_data.artist : "---";
    if (full || strcmp(artist, g_shown.artist) != 0) {
        char line[PROTO_ARTIST_MAX + 8];
        text_fit_ellipsis(&FONT_ARTIST, artist, TEXT_W, line,
                          static_cast<int>(sizeof(line)));
        clearTextRow(ARTIST_Y, ARTIST_H);
        drawTextCentered(&FONT_ARTIST, line, DISPLAY_W / 2,
                         ARTIST_Y + FONT_ARTIST.baseline, COL_DIM);
        proto_copy_text(g_shown.artist, static_cast<int>(sizeof(g_shown.artist)),
                        artist, static_cast<int>(strlen(artist)));
    }

    // 5. pasek postępu — dokładamy albo zdejmujemy TYLKO różnicę
    uint16_t bar = 0;
    if (online && g_data.duration_s > 0) {
        const uint32_t pos = display_position_now(&g_data, now);
        bar = static_cast<uint16_t>((pos * static_cast<uint32_t>(BAR_W)) / g_data.duration_s);
        if (bar > BAR_W) {
            bar = BAR_W;
        }
    }
    if (full) {
        tft.fillRect(BAR_X, BAR_Y, BAR_W, BAR_H, COL_LINE);
        if (bar > 0) {
            tft.fillRect(BAR_X, BAR_Y, bar, BAR_H, COL_ACCENT);
        }
        g_shown.bar_px = bar;
    } else if (bar != g_shown.bar_px) {
        if (bar > g_shown.bar_px) {
            tft.fillRect(BAR_X + g_shown.bar_px, BAR_Y, bar - g_shown.bar_px,
                         BAR_H, COL_ACCENT);
        } else {
            tft.fillRect(BAR_X + bar, BAR_Y, g_shown.bar_px - bar, BAR_H, COL_LINE);
        }
        g_shown.bar_px = bar;
    }

    // 6. tempomat — symbol i prędkość zmieniają się razem (wspólny kolor),
    //    więc idą jednym przerysowaniem komórki
    const bool cruise = online && g_data.cruise;
    const bool known = cruise && g_data.set_speed > 0;
    char speed[sizeof(g_shown.speed)];
    if (known) {
        snprintf(speed, sizeof(speed), "%u", static_cast<unsigned>(g_data.set_speed));
    } else {
        memcpy(speed, "---", 4);
    }
    if (full || cruise != g_shown.cruise || strcmp(speed, g_shown.speed) != 0) {
        drawCruiseCell(cruise, speed, known);
        g_shown.cruise = cruise;
        memcpy(g_shown.speed, speed, strlen(speed) + 1);
    }
}

// --- ekran 2 ----------------------------------------------------------------

static void renderBodyOpen(bool full)
{
    if (full) {
        // bryła bazowa to całe auto ZAMKNIĘTE — po niej dokładamy tylko
        // te panele, które faktycznie są otwarte
        blit(0, 0, DISPLAY_W, DISPLAY_H, car_base);
    }
    for (uint8_t i = 0; i < PANEL_COUNT; i++) {
        const bool open = input_active(&g_inputs, static_cast<uint8_t>(PANEL_FIRST + i));
        const bool paint = full ? open : (open != g_shown.panel[i]);
        if (paint) {
            const PanelSprite &p = PANELS[i];
            blit(p.x, p.y, p.w, p.h, open ? p.open : p.closed);
        }
        g_shown.panel[i] = open;
    }
}

static void render(uint32_t now)
{
    const Screen screen = screen_select(&g_inputs);
    const bool full = (!g_shown.valid || g_shown.screen != screen);
    if (full) {
        memset(&g_shown, 0, sizeof(g_shown));   // nic nie wisi — wszystko od nowa
    }

    if (screen == SCREEN_BODY_OPEN) {
        renderBodyOpen(full);
    } else {
        renderNowPlaying(full, now);
    }

    g_shown.screen = static_cast<uint8_t>(screen);
    g_shown.valid = true;
}

// --- podświetlenie ----------------------------------------------------------
// Rdzeń 3.x adresuje LEDC pinem, 2.x kanałem — obsługujemy oba, żeby
// przypięcie innej wersji w sketch.yaml nie wywracało kompilacji.
static void backlightInit(void)
{
#if ESP_ARDUINO_VERSION_MAJOR >= 3
    ledcAttach(PIN_BACKLIGHT, BL_FREQ_HZ, BL_RES_BITS);
#else
    ledcSetup(BL_CHANNEL, BL_FREQ_HZ, BL_RES_BITS);
    ledcAttachPin(PIN_BACKLIGHT, BL_CHANNEL);
#endif
}

static void backlightSet(uint8_t duty)
{
#if ESP_ARDUINO_VERSION_MAJOR >= 3
    ledcWrite(PIN_BACKLIGHT, duty);
#else
    ledcWrite(BL_CHANNEL, duty);
#endif
}

// --- wejścia i port ---------------------------------------------------------

static void readInputs(bool *active)
{
    for (uint8_t i = 0; i < INPUT_COUNT; i++) {
        // PC817 zwiera wejście do masy, pull-up trzyma je wysoko: LOW = aktywne
        active[i] = (digitalRead(INPUT_PINS[i]) == LOW);
    }
}

static void pumpSerial(uint32_t now)
{
    // Limit bajtów na obieg: przy zalewie linii rysowanie i tak musi dostać
    // swoją kolej, inaczej ekran zastyga.
    for (int guard = 0; guard < SERIAL_BYTES_PER_LOOP && Serial.available() > 0; guard++) {
        if (line_feed(&g_line, static_cast<char>(Serial.read()))) {
            if (protocol_apply_line(&g_data, g_line.buf, now) == PROTO_PING) {
                Serial.println("PONG");
            }
        }
    }
}

// -----------------------------------------------------------------------------
void setup()
{
    for (uint8_t i = 0; i < INPUT_COUNT; i++) {
        pinMode(INPUT_PINS[i], INPUT_PULLUP);
    }

    // Podświetlenie w zero PRZED inicjalizacją panelu: pamięć ST7735 po
    // podaniu zasilania jest pełna śmieci i bez tego mignęłyby na oczach.
    backlightInit();
    backlightSet(0);

    tft.init();
    tft.setRotation(0);        // 128x160 pionowo — natywna orientacja panelu
    tft.setSwapBytes(true);    // sprite'y to natywne uint16, panel chce big-endian
    tft.fillScreen(COL_BG);

    Serial.begin(115200);

    display_data_init(&g_data);
    line_init(&g_line);

    const uint32_t now = millis();
    bool active[INPUT_COUNT];
    readInputs(active);
    inputs_init(&g_inputs, now);
    inputs_preset(&g_inputs, active, now);   // stan wejść bez czekania na debounce
    memset(&g_shown, 0, sizeof(g_shown));

    render(now);               // pierwsza klatka jeszcze przy zgaszonym panelu
    for (uint16_t d = 0; d <= BL_DUTY; d += 4) {
        backlightSet(static_cast<uint8_t>(d));
        delay(2);              // ~110 ms rozjaśniania zamiast błysku
    }
    backlightSet(BL_DUTY);

    // Tylko przy podpiętym hoście: zapis do natywnego CDC bez odbiorcy
    // czeka na miejsce w FIFO i potrafi na chwilę zatrzymać pętlę.
    // Na PING odpowiadamy bez tego warunku — skoro PING przyszedł,
    // po drugiej stronie ktoś jest.
    if (Serial) {
        Serial.println("READY");
    }
}

void loop()
{
    const uint32_t now = millis();
    bool active[INPUT_COUNT];

    pumpSerial(now);
    readInputs(active);
    inputs_update(&g_inputs, active, now);
    render(now);
}
