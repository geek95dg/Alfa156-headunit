// Obsługa fontu bitmapowego z font.h: UTF-8, metryki, przycinanie tekstu.
//
// Plik pisany RĘCZNIE — font.h to same dane z tools/esp32_font.py, a tutaj
// siedzi logika. Czysty C++, zero Arduino, więc kompiluje się i testuje na
// hoście (g++ -std=c++17 -Wall -Wextra -Werror). Samo malowanie pikseli
// zostaje w esp32_display.ino, bo zależy od TFT_eSPI.
//
// Zasady, które trzymają się razem z generatorem:
//   * codepoints[] jest posortowane rosnąco — stąd wyszukiwanie binarne;
//   * brakujący codepoint podmieniamy na '?', nigdy nie wywalamy programu
//     ani nie wypisujemy śmieci (metadane z BCM przychodzą z internetu,
//     więc trafi się i emoji, i cyrylica);
//   * szerokość napisu to suma pól advance — dokładnie tak, jak liczy
//     kursor pętla rysująca, więc wyśrodkowanie nigdy się nie rozjedzie.
#pragma once

#include <stdint.h>

#include "font.h"

// Kolejny codepoint z napisu UTF-8. *pos to indeks BAJTA, przesuwany na
// początek następnego znaku. Zwraca -1 na końcu napisu.
//
// Uszkodzona sekwencja (samotny bajt ciągły, urwany wielobajt) daje '?'
// i przesuwa pozycję o co najmniej jeden bajt — pętla wywołująca zawsze
// dobiega do końca, nigdy nie czyta za bajtem zerowym.
inline int utf8_next(const char *s, int *pos)
{
    if (s == nullptr || pos == nullptr) {
        return -1;
    }
    const unsigned char *u = reinterpret_cast<const unsigned char *>(s);
    const int i = *pos;
    const unsigned char lead = u[i];

    if (lead == 0x00) {
        return -1;
    }
    if (lead < 0x80) {
        *pos = i + 1;
        return static_cast<int>(lead);
    }

    int extra;
    int cp;
    if ((lead & 0xE0) == 0xC0) {
        extra = 1;
        cp = lead & 0x1F;
    } else if ((lead & 0xF0) == 0xE0) {
        extra = 2;
        cp = lead & 0x0F;
    } else if ((lead & 0xF8) == 0xF0) {
        extra = 3;
        cp = lead & 0x07;
    } else {
        *pos = i + 1;                     // bajt ciągły bez wiodącego
        return '?';
    }

    for (int k = 1; k <= extra; k++) {
        const unsigned char b = u[i + k];
        if ((b & 0xC0) != 0x80) {
            *pos = i + k;                 // urwana sekwencja — stajemy na bajcie winnym
            return '?';
        }
        cp = (cp << 6) | (b & 0x3F);
    }
    *pos = i + extra + 1;
    return cp;
}

// Glif dla codepointu albo nullptr, gdy kroju go nie ma.
inline const Glyph *font_glyph(const Font *f, uint16_t cp)
{
    if (f == nullptr || f->codepoints == nullptr || f->glyphs == nullptr) {
        return nullptr;
    }
    int lo = 0;
    int hi = static_cast<int>(f->count) - 1;
    while (lo <= hi) {
        const int mid = lo + (hi - lo) / 2;
        const uint16_t here = f->codepoints[mid];
        if (here == cp) {
            return &f->glyphs[mid];
        }
        if (here < cp) {
            lo = mid + 1;
        } else {
            hi = mid - 1;
        }
    }
    return nullptr;
}

// To samo, ale z podmianą na '?' — tego używa rysowanie i pomiary.
// Zwraca nullptr tylko wtedy, gdy krój nie ma nawet '?', czyli nigdy
// dla fontów z font.h.
inline const Glyph *font_glyph_or_fallback(const Font *f, int cp)
{
    if (cp >= 0 && cp <= 0xFFFF) {
        const Glyph *g = font_glyph(f, static_cast<uint16_t>(cp));
        if (g != nullptr) {
            return g;
        }
    }
    return font_glyph(f, static_cast<uint16_t>('?'));
}

// Szerokość napisu w pikselach = suma advance wszystkich glifów.
inline int font_text_width(const Font *f, const char *utf8)
{
    if (f == nullptr || utf8 == nullptr) {
        return 0;
    }
    int width = 0;
    int pos = 0;
    for (;;) {
        const int cp = utf8_next(utf8, &pos);
        if (cp < 0) {
            break;
        }
        const Glyph *g = font_glyph_or_fallback(f, cp);
        if (g != nullptr) {
            width += static_cast<int>(g->advance);
        }
    }
    return width;
}

// Ile BAJTÓW napisu mieści się w max_px. Cięcie zawsze wypada na granicy
// znaku, więc wynik da się bezpiecznie podać dalej jako długość napisu
// (przydaje się przy łamaniu tytułu na dwie linie i przy dopisywaniu "…").
inline int font_fit(const Font *f, const char *utf8, int max_px)
{
    if (f == nullptr || utf8 == nullptr || max_px <= 0) {
        return 0;
    }
    int width = 0;
    int pos = 0;
    int fitted = 0;
    for (;;) {
        const int cp = utf8_next(utf8, &pos);
        if (cp < 0) {
            break;
        }
        const Glyph *g = font_glyph_or_fallback(f, cp);
        const int advance = (g != nullptr) ? static_cast<int>(g->advance) : 0;
        if (width + advance > max_px) {
            break;
        }
        width += advance;
        fitted = pos;
    }
    return fitted;
}
