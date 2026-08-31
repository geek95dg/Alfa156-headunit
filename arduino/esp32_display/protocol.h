/*
 * BCM v8.5 — parser protokołu USB CDC dla wyświetlacza 1,8" (ESP32-S3)
 *
 * Ten sam kształt linii, którym mówi już sensor_hub — `KLUCZ:wartość`
 * zakończone '\n' — tylko w drugą stronę: tu BCM pisze, a ESP32 czyta.
 *
 *   TITLE:<tekst>      tytuł utworu (UTF-8, z ogonkami)
 *   ARTIST:<tekst>     wykonawca
 *   SRC:BT|AA|---      źródło dźwięku
 *   PLAY:0|1           1 = odtwarzanie, 0 = pauza
 *   POS:<sekundy>      pozycja w utworze
 *   DUR:<sekundy>      długość utworu
 *   CRUISE:0|1         tempomat aktywny
 *   SETSPD:<km/h>      zadana prędkość tempomatu
 *   PING               -> ESP32 odpowiada PONG
 *
 * CZYSTY C++ — zero Arduino, więc kompiluje się i testuje na hoście
 * (g++ -std=c++17 -Wall -Wextra -Werror, patrz test/test_host.cpp).
 * Cała warstwa I/O siedzi w esp32_display.ino.
 *
 * Odporność, bo po drugiej stronie kabla siedzi linuksowy proces, a w danych
 * metadane z internetu (a więc i emoji, i cyrylica, i tytuły na pół ekranu):
 *   * pusta wartość            -> pole czyszczone, renderer podmienia na "---";
 *   * nieznany klucz           -> ignorowany bez błędu;
 *   * brak dwukropka           -> ignorowany (poza gołym PING);
 *   * linia dłuższa niż bufor  -> obcinana, reszta idzie w kosz;
 *   * '\r' na końcu (CRLF)     -> zdejmowany;
 *   * UTF-8 ucięty w połowie   -> ogon urwanej sekwencji zdejmowany, żeby
 *                                 do fontu nigdy nie trafił kaleki znak.
 *
 * KAŻDA niepusta linia — nawet z nieznanym kluczem — jest dowodem, że BCM
 * żyje, i odświeża znacznik świeżości. Brak linii przez BCM_TIMEOUT_MS
 * (state.h) gasi metadane do "---"; kontrolki i ekran 2 idą wprost z GPIO
 * i działają dalej.
 */
#pragma once

#include <stdint.h>
#include <string.h>

enum {
    PROTO_LINE_MAX   = 192,   // najdłuższa linia, jaką bierzemy na poważnie
    PROTO_TITLE_MAX  = 96,    // tytuł: dwie linie po 112 px to grubo mniej
    PROTO_ARTIST_MAX = 64,
    PROTO_SOURCE_MAX = 8,     // "BT", "AA", "---"

    PROTO_SECONDS_MAX = 86400,  // sufit dla POS/DUR — doba, nie utwór
    PROTO_SPEED_MAX   = 999     // sufit dla SETSPD — trzy cyfry mieszczą się w polu
};

// Wszystko, co przychodzi z BCM i ląduje na ekranie 1.
struct DisplayData {
    char     title[PROTO_TITLE_MAX];
    char     artist[PROTO_ARTIST_MAX];
    char     source[PROTO_SOURCE_MAX];
    bool     playing;
    uint32_t position_s;
    uint32_t duration_s;
    uint32_t position_rx_ms;   // millis() przy ostatnim POS — do dosuwania paska
    bool     cruise;
    uint16_t set_speed;
    bool     seen;             // czy BCM w ogóle się kiedykolwiek odezwał
    uint32_t last_rx_ms;       // znacznik świeżości: millis() ostatniej linii
};

enum ProtoResult : uint8_t {
    PROTO_IGNORED = 0,   // nic się nie zmieniło (nieznany klucz, ta sama wartość)
    PROTO_UPDATED,       // pole zmieniło wartość — warto przerysować
    PROTO_PING           // trzeba odpowiedzieć PONG
};

// --- składanie linii z bajtów (ESP32 czyta Serial bajt po bajcie) ---
//
// Nadmiar ponad bufor jest ODRZUCANY, ale linia i tak zostaje oddana —
// lepiej pokazać obcięty tytuł niż zgubić całą aktualizację. Flaga
// `truncated` mówi, że tak się stało.
struct LineAssembler {
    char     buf[PROTO_LINE_MAX];
    uint16_t len;         // ile bajtów zebrano do tej pory
    bool     overflow;    // bieżąca linia przerosła bufor
    bool     truncated;   // ...tak było w linii ostatnio oddanej
};

inline void line_init(LineAssembler *a)
{
    if (a == nullptr) {
        return;
    }
    a->buf[0] = '\0';
    a->len = 0;
    a->overflow = false;
    a->truncated = false;
}

// Dokłada jeden bajt. Zwraca true, gdy w a->buf leży kompletna, zerowo
// zakończona linia (bez '\n' i bez '\r'). Licznik zeruje się od razu,
// więc wywołujący ma linię ważną do najbliższego kolejnego line_feed().
inline bool line_feed(LineAssembler *a, char c)
{
    if (a == nullptr) {
        return false;
    }
    if (c == '\r') {
        return false;                 // CRLF: '\r' nas nie interesuje nigdzie
    }
    if (c == '\n') {
        a->buf[a->len] = '\0';
        a->len = 0;
        a->truncated = a->overflow;
        a->overflow = false;
        return true;
    }
    if (a->len < PROTO_LINE_MAX - 1) {
        a->buf[a->len++] = c;
    } else {
        a->overflow = true;           // przepełnienie — reszta linii w kosz
    }
    return false;
}

// --- pomocnicze ---

// Ile z pierwszych `len` bajtów tworzy komplet znaków UTF-8. Ucina ogon
// urwany w połowie sekwencji — inaczej font_draw.h zobaczyłby kalekę
// i wypisał '?' na końcu każdego obciętego tytułu.
inline int proto_utf8_trim(const char *s, int len)
{
    if (s == nullptr || len <= 0) {
        return 0;
    }
    const unsigned char *u = reinterpret_cast<const unsigned char *>(s);
    int start = len - 1;
    int back = 0;
    while (start > 0 && (u[start] & 0xC0) == 0x80 && back < 3) {
        start--;
        back++;
    }
    const unsigned char lead = u[start];
    int need = 1;
    if ((lead & 0xE0) == 0xC0) {
        need = 2;
    } else if ((lead & 0xF0) == 0xE0) {
        need = 3;
    } else if ((lead & 0xF8) == 0xF0) {
        need = 4;
    }
    return (start + need <= len) ? len : start;
}

// Kopia tekstu z przycięciem do pojemności pola i do granicy znaku UTF-8.
inline void proto_copy_text(char *dst, int cap, const char *src, int src_len)
{
    if (dst == nullptr || cap <= 0) {
        return;
    }
    int n = (src == nullptr || src_len < 0) ? 0 : src_len;
    if (n > cap - 1) {
        n = cap - 1;
    }
    n = proto_utf8_trim(src, n);
    if (n > 0) {
        memcpy(dst, src, static_cast<size_t>(n));
    }
    dst[n] = '\0';
}

// Liczba całkowita bez znaku, z sufitem. Śmieci i pusta wartość dają 0
// (i false) — pole wraca do stanu "nie wiem", zamiast trzymać starą wartość.
inline bool proto_parse_uint(const char *s, int len, uint32_t *out, uint32_t max)
{
    uint32_t v = 0;
    bool any = false;
    int i = 0;
    while (i < len && (s[i] == ' ' || s[i] == '\t')) {
        i++;
    }
    for (; i < len; i++) {
        const char c = s[i];
        if (c < '0' || c > '9') {
            break;
        }
        any = true;
        if (v < max) {
            v = v * 10u + static_cast<uint32_t>(c - '0');
            if (v > max) {
                v = max;
            }
        }
    }
    if (out != nullptr) {
        *out = any ? v : 0u;
    }
    return any;
}

inline bool proto_key_eq(const char *line, int key_len, const char *key)
{
    const int n = static_cast<int>(strlen(key));
    return key_len == n && memcmp(line, key, static_cast<size_t>(n)) == 0;
}

inline void display_data_init(DisplayData *d)
{
    if (d == nullptr) {
        return;
    }
    memset(d, 0, sizeof(*d));
}

// Bierze JEDNĄ linię (bez '\n'; '\r' wolno zostawić) i wsypuje ją do `d`.
inline ProtoResult protocol_apply_line(DisplayData *d, const char *line, uint32_t now_ms)
{
    if (d == nullptr || line == nullptr) {
        return PROTO_IGNORED;
    }

    int len = static_cast<int>(strlen(line));
    while (len > 0 && (line[len - 1] == '\r' || line[len - 1] == '\n' || line[len - 1] == ' ')) {
        len--;
    }
    if (len == 0) {
        return PROTO_IGNORED;   // sama pusta linia nie jest dowodem życia
    }

    // Od tej chwili wiemy, że po drugiej stronie ktoś pisze — nawet jeśli
    // pisze bzdury. To wystarczy, żeby nie gasić metadanych.
    d->seen = true;
    d->last_rx_ms = now_ms;

    int colon = -1;
    for (int i = 0; i < len; i++) {
        if (line[i] == ':') {
            colon = i;
            break;
        }
    }

    if (colon < 0) {
        return proto_key_eq(line, len, "PING") ? PROTO_PING : PROTO_IGNORED;
    }

    const char *val = line + colon + 1;
    const int vlen = len - colon - 1;

    if (proto_key_eq(line, colon, "TITLE")) {
        char tmp[PROTO_TITLE_MAX];
        proto_copy_text(tmp, static_cast<int>(sizeof(tmp)), val, vlen);
        if (strcmp(tmp, d->title) != 0) {
            memcpy(d->title, tmp, strlen(tmp) + 1);
            return PROTO_UPDATED;
        }
        return PROTO_IGNORED;
    }

    if (proto_key_eq(line, colon, "ARTIST")) {
        char tmp[PROTO_ARTIST_MAX];
        proto_copy_text(tmp, static_cast<int>(sizeof(tmp)), val, vlen);
        if (strcmp(tmp, d->artist) != 0) {
            memcpy(d->artist, tmp, strlen(tmp) + 1);
            return PROTO_UPDATED;
        }
        return PROTO_IGNORED;
    }

    if (proto_key_eq(line, colon, "SRC")) {
        char tmp[PROTO_SOURCE_MAX];
        proto_copy_text(tmp, static_cast<int>(sizeof(tmp)), val, vlen);
        if (strcmp(tmp, d->source) != 0) {
            memcpy(d->source, tmp, strlen(tmp) + 1);
            return PROTO_UPDATED;
        }
        return PROTO_IGNORED;
    }

    if (proto_key_eq(line, colon, "PLAY")) {
        uint32_t v = 0;
        proto_parse_uint(val, vlen, &v, 1);
        const bool play = (v != 0);
        if (play != d->playing) {
            d->playing = play;
            // Pauza/wznowienie przestawia punkt odniesienia dla dosuwania
            // paska, inaczej po wznowieniu skoczyłby o czas pauzy.
            d->position_rx_ms = now_ms;
            return PROTO_UPDATED;
        }
        return PROTO_IGNORED;
    }

    if (proto_key_eq(line, colon, "POS")) {
        uint32_t v = 0;
        proto_parse_uint(val, vlen, &v, PROTO_SECONDS_MAX);
        d->position_rx_ms = now_ms;   // zawsze — nawet gdy sekunda ta sama
        if (v != d->position_s) {
            d->position_s = v;
            return PROTO_UPDATED;
        }
        return PROTO_IGNORED;
    }

    if (proto_key_eq(line, colon, "DUR")) {
        uint32_t v = 0;
        proto_parse_uint(val, vlen, &v, PROTO_SECONDS_MAX);
        if (v != d->duration_s) {
            d->duration_s = v;
            return PROTO_UPDATED;
        }
        return PROTO_IGNORED;
    }

    if (proto_key_eq(line, colon, "CRUISE")) {
        uint32_t v = 0;
        proto_parse_uint(val, vlen, &v, 1);
        const bool on = (v != 0);
        if (on != d->cruise) {
            d->cruise = on;
            return PROTO_UPDATED;
        }
        return PROTO_IGNORED;
    }

    if (proto_key_eq(line, colon, "SETSPD")) {
        uint32_t v = 0;
        proto_parse_uint(val, vlen, &v, PROTO_SPEED_MAX);
        const uint16_t spd = static_cast<uint16_t>(v);
        if (spd != d->set_speed) {
            d->set_speed = spd;
            return PROTO_UPDATED;
        }
        return PROTO_IGNORED;
    }

    return PROTO_IGNORED;   // nieznany klucz — cisza, żadnego błędu
}

// Pozycja w utworze dosunięta lokalnie między kolejnymi POS. BCM wysyła
// je co sekundę albo rzadziej; bez tego pasek szarpałby się skokami.
// Przy pauzie stoi, a przy znanej długości nigdy nie przekracza końca.
inline uint32_t display_position_now(const DisplayData *d, uint32_t now_ms)
{
    if (d == nullptr) {
        return 0;
    }
    uint32_t pos = d->position_s;
    if (d->playing) {
        pos += (now_ms - d->position_rx_ms) / 1000u;
    }
    if (d->duration_s > 0 && pos > d->duration_s) {
        pos = d->duration_s;
    }
    return pos;
}
