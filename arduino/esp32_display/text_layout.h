/*
 * BCM v8.5 — składanie napisów dla wyświetlacza 1,8" (ESP32-S3)
 *
 * Łamanie tytułu na dwie linie, przycinanie z wielokropkiem i linia źródła.
 * Wszystko, co decyduje o TREŚCI napisu — bez ani jednego piksela; samo
 * malowanie zostaje w esp32_display.ino, bo zależy od TFT_eSPI.
 *
 * CZYSTY C++ — zero Arduino, więc kompiluje się i testuje na hoście
 * (g++ -std=c++17 -Wall -Wextra -Werror, patrz test/test_host.cpp).
 * Metryki bierzemy z font_draw.h, przycinanie do granicy znaku UTF-8
 * z protocol.h — dzięki temu w buforze nigdy nie ląduje pół ogonka.
 *
 * Każda funkcja ZAWSZE zostawia w dst napis zakończony zerem i nigdy nie
 * pisze poza `cap` bajtów, nawet gdy bufor jest absurdalnie mały.
 */
#pragma once

#include <stdio.h>
#include <string.h>

#include "font_draw.h"
#include "protocol.h"

// Wielokropek U+2026 — jest w zestawie fontu (patrz tools/esp32_font.py).
#define TEXT_ELLIPSIS "\xE2\x80\xA6"

// Napis przycięty do max_px z dopisanym wielokropkiem. font_fit() tnie
// zawsze na granicy znaku UTF-8, więc ogonek nigdy nie rozpada się na pół
// bajtu. Gdy bufor jest za ciasny nawet na sam wielokropek, zostaje zwykłe
// obcięcie — lepiej krótszy napis niż wyjście poza bufor.
inline void text_fit_ellipsis(const Font *f, const char *src, int max_px,
                              char *dst, int cap)
{
    if (dst == nullptr || cap <= 0) {
        return;
    }
    if (src == nullptr) {
        dst[0] = '\0';
        return;
    }
    static const char ELLIPSIS[] = TEXT_ELLIPSIS;
    const int elen = static_cast<int>(sizeof(ELLIPSIS));   // z bajtem zerowym

    if (font_text_width(f, src) <= max_px || cap < elen) {
        proto_copy_text(dst, cap, src, static_cast<int>(strlen(src)));
        return;
    }

    const int ew = font_text_width(f, ELLIPSIS);
    int n = font_fit(f, src, max_px - ew);
    while (n > 0 && src[n - 1] == ' ') {
        n--;                                               // bez dziury przed "…"
    }
    if (n > cap - elen) {
        n = cap - elen;
    }
    if (n < 0) {
        n = 0;
    }
    n = proto_utf8_trim(src, n);
    if (n > 0) {
        memcpy(dst, src, static_cast<size_t>(n));
    }
    memcpy(dst + n, ELLIPSIS, static_cast<size_t>(elen));
}

// Tytuł łamany na maksymalnie dwie linie po max_px pikseli. Łamiemy po
// ostatniej spacji, która się mieści; gdy w linii nie ma ani jednej (jedno
// długie słowo), łamiemy twardo tam, gdzie kończy się miejsce. Reszta,
// która nie wchodzi w drugą linię, dostaje wielokropek.
inline void text_wrap_two_lines(const Font *f, const char *src, int max_px,
                                char *l1, int c1, char *l2, int c2)
{
    if (l1 != nullptr && c1 > 0) {
        l1[0] = '\0';
    }
    if (l2 != nullptr && c2 > 0) {
        l2[0] = '\0';
    }
    if (l1 == nullptr || c1 <= 0 || src == nullptr || src[0] == '\0') {
        return;
    }
    if (font_text_width(f, src) <= max_px) {
        proto_copy_text(l1, c1, src, static_cast<int>(strlen(src)));
        return;
    }

    const int cut = font_fit(f, src, max_px);
    int brk = 0;
    for (int i = cut; i > 0; i--) {
        if (src[i - 1] == ' ') {
            brk = i;
            break;
        }
    }
    int end = (brk > 0) ? brk : cut;
    const int next = end;
    while (end > 0 && src[end - 1] == ' ') {
        end--;
    }
    int rest = next;
    while (src[rest] == ' ') {
        rest++;
    }
    proto_copy_text(l1, c1, src, end);
    text_fit_ellipsis(f, src + rest, max_px, l2, c2);
}

// Rozwinięcie kodu z protokołu na nazwę czytaną z fotela kierowcy. Kabel
// niesie "BT"/"AA" (kontrakt protokołu, patrz protocol.h), ale na panelu
// ma stać słowo — tak jak w projekcie ekranów
// (docs/WYSWIETLACZ_ESP32_1V8.md, mockups/esp32_1v8/Main.dc.html).
// W FONT_LABEL "ANDROID AUTO · PAUZA" ma 85 px przy polu 112 px, więc
// najdłuższy wariant mieści się z zapasem. Nieznany kod przepisujemy
// żywcem — protokół wolno rozszerzyć bez ruszania firmware'u.
inline const char *text_source_name(const char *code)
{
    if (code == nullptr) {
        return "---";
    }
    if (strcmp(code, "BT") == 0) {
        return "BLUETOOTH";
    }
    if (strcmp(code, "AA") == 0) {
        return "ANDROID AUTO";
    }
    return code;
}

// Linia źródła: nazwa źródła, a przy pauzie z dopiskiem. Znak "·" jest
// w zestawie fontu, strzałki odtwarzania nie ma — stąd słowo "PAUZA"
// zamiast przekreślonego trójkąta. Po utracie BCM (online = false)
// zostaje samo "---", bez dopisku.
inline void text_compose_source(char *dst, int cap, const char *source,
                                bool online, bool playing)
{
    if (dst == nullptr || cap <= 0) {
        return;
    }
    const bool known = online && source != nullptr && source[0] != '\0';
    const char *src = known ? text_source_name(source) : "---";
    if (known && !playing) {
        char tmp[PROTO_SOURCE_MAX + 32];
        snprintf(tmp, sizeof(tmp), "%s \xC2\xB7 PAUZA", src);
        proto_copy_text(dst, cap, tmp, static_cast<int>(strlen(tmp)));
    } else {
        proto_copy_text(dst, cap, src, static_cast<int>(strlen(src)));
    }
}
