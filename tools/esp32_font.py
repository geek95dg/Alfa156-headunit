#!/usr/bin/env python3
"""Generator fontu bitmapowego dla wyświetlacza 1,8" na ESP32 — z TTF do font.h.

Na ST7735 128x160 rysujemy tekst JEDNOBITOWO: dla każdego glifu trzymamy
maskę „tu jest atrament”, a firmware maluje ją kolorem tekstu na tle
#0a0a0a. Antyaliasing przy 7-16 px na tak ciemnym tle i tak nic nie daje
— półprzezroczysta krawędź wpada w tło, a kosztuje albo 4x więcej flasha
(4 bity krycia), albo blending w pętli rysującej. Dlatego rasteryzujemy
z progiem i pakujemy po jednym bicie na piksel.

Kroje bierzemy z jednego pliku zmiennego (Public Sans Variable), bo cztery
osobne statyczne TTF-y to cztery okazje na rozjazd metryk. PIL ustawia
wagę przez ``set_variation_by_name`` — nazwy instancji sprawdzisz przez
``ImageFont.truetype(...).get_variation_names()``.

Pułapki, na które warto uważać:

  * PIL NIE resetuje wariacji między wywołaniami — dla każdego kroju
    ładujemy font od nowa, inaczej ostatnio ustawiona waga „przecieka”
    na kolejne rozmiary.

  * Rozmiar podany w pikselach to wysokość EM, nie wysokość kreski.
    ``line_height`` (ascent + descent) wychodzi o ~25% większy i to jego
    używa firmware do rozstawiania linii — patrz wydruk na końcu.

  * Ogonki i akcenty (Ą, ż) wychodzą POZA prostokąt liter bazowych,
    ale mieszczą się w ascent/descent. Bitmapa glifu jest przycięta do
    samego atramentu, a ``xoff``/``yoff`` mówią, gdzie ją postawić
    względem kursora i linii bazowej. Bez tego ogonek Ą ucinałby się
    o wiersz.

  * Wynik musi być deterministyczny (dwa przebiegi = ten sam md5), więc
    nigdzie nie polegamy na kolejności słownika ani na ścieżkach
    bezwzględnych — znaki idą posortowane po codepointcie, a to samo
    sortowanie wykorzystuje wyszukiwanie binarne w font_draw.h.

Logikę rysowania (dekoder UTF-8, szerokość tekstu, przycinanie) trzyma
ręcznie pisany ``font_draw.h`` — tutaj powstają WYŁĄCZNIE dane.

Użycie:
    python tools/esp32_font.py                    # domyślne ścieżki
    python tools/esp32_font.py --threshold 140    # cieńsza kreska
    python tools/esp32_font.py --preview mockups/esp32_1v8/font_preview.png

Zależności: pillow (pip install pillow).
"""

import argparse
import math
import os
import sys

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError as exc:                                    # pragma: no cover
    sys.exit("Brak zależności (%s). Zainstaluj: pip install pillow" % exc.name)


# --- Konfiguracja ----------------------------------------------------------

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SOURCE_TTF = os.path.join(REPO, "assets", "fonts", "PublicSans-Variable.ttf")
OUT_HEADER = os.path.join(REPO, "arduino", "esp32_display", "font.h")

# Nazwa instancji w foncie zmiennym dla wagi z projektu ekranu.
WEIGHT_NAMES = {600: "SemiBold", 800: "ExtraBold", 900: "Black"}

# Kroje wymagane przez układ ekranu 1: (identyfikator C, px, waga, do czego).
FACES = [
    ("FONT_TITLE",  15, 800, "tytuł utworu, do dwóch linii"),
    ("FONT_ARTIST", 10, 600, "wykonawca"),
    ("FONT_LABEL",   7, 800, "źródło, jednostki, etykiety"),
    ("FONT_SPEED",  16, 900, "zadana prędkość tempomatu"),
]

# Próg krycia, powyżej którego piksel uznajemy za atrament. 110 zamiast
# neutralnych 128, bo przy 7 px cienkie elementy (kropka nad i, ogonek,
# przecinek) mają szczyt krycia ledwie w okolicy 60-70% i przy 128
# znikały co drugi raz. Niżej niż ~90 litery zaczynają się zlewać.
THRESHOLD = 110

# Zestaw znaków: ASCII drukowalne + polskie diakrytyki + garść typografii.
POLISH = "ĄĆĘŁŃÓŚŹŻąćęłńóśźż"
EXTRAS = "°·—…"

# Znak zastępczy dla brakujących codepointów — musi być w zestawie,
# bo font_draw.h podstawia go zamiast rzucać czymkolwiek.
FALLBACK = "?"

# Rozmiary struktur na ESP32 (32-bit, wyrównanie do 4) — tylko do wydruku.
SIZEOF_GLYPH = 12
SIZEOF_FONT = 16


# --- Zestaw znaków ---------------------------------------------------------

def charset():
    """Posortowana, odchudzona z duplikatów lista codepointów."""
    chars = set(chr(c) for c in range(0x20, 0x7F))
    chars.update(POLISH)
    chars.update(EXTRAS)
    chars.add(FALLBACK)
    return sorted(ord(c) for c in chars)


# --- Rasteryzacja ----------------------------------------------------------

def load_face(path, px, weight):
    """Wczytaj krój w danym rozmiarze i wadze.

    Ładowanie od zera dla każdego kroju jest celowe: obiekt fontu trzyma
    ustawioną wariację, więc współdzielenie go między wagami cicho
    podmieniłoby grubość.
    """
    name = WEIGHT_NAMES.get(weight)
    if name is None:
        sys.exit("Nie znam instancji fontu dla wagi %d (mam: %s)."
                 % (weight, ", ".join(str(w) for w in sorted(WEIGHT_NAMES))))
    font = ImageFont.truetype(path, px)
    available = [n.decode("utf-8") if isinstance(n, bytes) else n
                 for n in font.get_variation_names()]
    if name not in available:
        sys.exit("Font %s nie ma instancji %r (ma: %s)."
                 % (os.path.basename(path), name, ", ".join(available)))
    font.set_variation_by_name(name)
    return font, name


def render_glyph(font, ascent, descent, cp, threshold):
    """Zrasteryzuj jeden glif i zwróć (w, h, advance, xoff, yoff, wiersze).

    Rysujemy na zapasie ze wszystkich stron, bo akcent potrafi wyjść nad
    ascent, a ogonek pod descent — dopiero potem przycinamy do atramentu.
    ``wiersze`` to lista list bitów, po jednym na piksel.
    """
    pad = font.size + 4
    width = pad * 2 + int(math.ceil(font.getlength(chr(cp)))) + font.size * 2
    height = pad * 2 + ascent + descent
    canvas = Image.new("L", (width, height), 0)
    ImageDraw.Draw(canvas).text((pad, pad), chr(cp), font=font, fill=255)
    mono = canvas.point(lambda v: 255 if v >= threshold else 0)

    advance = int(math.floor(font.getlength(chr(cp)) + 0.5))
    baseline = pad + ascent

    box = mono.getbbox()
    if box is None:                       # spacja i inne puste glify
        return 0, 0, advance, 0, 0, []

    x0, y0, x1, y1 = box
    px = mono.load()
    rows = [[1 if px[x, y] else 0 for x in range(x0, x1)] for y in range(y0, y1)]
    return x1 - x0, y1 - y0, advance, x0 - pad, y0 - baseline, rows


def pack_rows(rows, width):
    """Spakuj wiersze bitów: 1 bit na piksel, MSB pierwszy, wiersz do bajtu."""
    stride = (width + 7) // 8
    out = bytearray()
    for row in rows:
        line = bytearray(stride)
        for x, bit in enumerate(row):
            if bit:
                line[x >> 3] |= 0x80 >> (x & 7)
        out.extend(line)
    return bytes(out)


def build_face(path, px, weight, threshold):
    """Zbuduj komplet danych jednego kroju."""
    font, variation = load_face(path, px, weight)
    ascent, descent = font.getmetrics()

    blobs = {b"": 0}                      # deduplikacja identycznych bitmap
    bitmaps = bytearray()
    glyphs = []
    empty = []

    for cp in charset():
        w, h, advance, xoff, yoff, rows = render_glyph(font, ascent, descent, cp, threshold)
        if w == 0 and cp != 0x20:
            empty.append(cp)
        blob = pack_rows(rows, w)
        offset = blobs.get(blob)
        if offset is None:
            offset = len(bitmaps)
            blobs[blob] = offset
            bitmaps.extend(blob)
        if not (-128 <= xoff <= 127 and -128 <= yoff <= 127):
            sys.exit("Glif U+%04X ma przesunięcie poza int8 (%d, %d)." % (cp, xoff, yoff))
        glyphs.append((cp, w, h, advance, xoff, yoff, offset))

    if empty:
        print("  UWAGA: puste glify (brak w kroju?): %s"
              % " ".join("U+%04X" % c for c in empty))

    return {
        "variation": variation,
        "px": px,
        "weight": weight,
        "line_height": ascent + descent,
        "baseline": ascent,
        "glyphs": glyphs,
        "bitmaps": bytes(bitmaps),
    }


# --- Wyjście ---------------------------------------------------------------

HEADER_PROLOGUE = """// Wygenerowane przez tools/esp32_font.py — nie edytuj ręcznie.
// Źródło: assets/fonts/PublicSans-Variable.ttf (OFL, patrz assets/fonts/OFL.txt).
// Rasteryzacja 1-bitowa z progiem %d; logika rysowania siedzi w font_draw.h.
#pragma once

#include <stdint.h>
#if defined(ARDUINO)
#include <pgmspace.h>
#else
#ifndef PROGMEM
#define PROGMEM
#endif
#endif

typedef struct {
    uint8_t  w, h;        // rozmiar bitmapy glifu (sam atrament, bez marginesów)
    uint8_t  advance;     // o ile przesunąć kursor po narysowaniu
    int8_t   xoff, yoff;  // lewy górny róg bitmapy względem kursora i linii bazowej
    uint32_t offset;      // indeks pierwszego bajtu w tablicy bitmap
} Glyph;

typedef struct {
    uint8_t  line_height, baseline;
    uint16_t count;
    const uint16_t *codepoints;   // posortowane rosnąco — wyszukiwanie binarne
    const Glyph    *glyphs;       // równoległa do codepoints
    const uint8_t  *bitmaps;      // 1 bit na piksel, wiersz wyrównany do bajtu, MSB pierwszy
} Font;
"""


def glyph_comment(cp):
    """Nazwa glifu do komentarza — bez samego znaku dla spacji i cudzysłowów."""
    if cp == 0x20:
        return "spacja"
    if cp in (0x22, 0x27, 0x5C):
        return "U+%04X" % cp
    return chr(cp)


def c_words(values, per_line, fmt):
    body = []
    for i in range(0, len(values), per_line):
        body.append("    " + " ".join(fmt % v for v in values[i:i + per_line]))
    return "\n".join(body)


def emit_face(ident, face, purpose):
    """Wypisz cztery tablice i strukturę Font dla jednego kroju."""
    glyphs = face["glyphs"]
    out = ["\n// --- %s: %d px, %s (waga %d) — %s ---\n"
           % (ident, face["px"], face["variation"], face["weight"], purpose)]

    out.append("static const uint16_t %s_codepoints[%d] PROGMEM = {\n%s\n};\n"
               % (ident, len(glyphs), c_words([g[0] for g in glyphs], 12, "0x%04X,")))

    out.append("\nstatic const Glyph %s_glyphs[%d] PROGMEM = {\n" % (ident, len(glyphs)))
    for cp, w, h, advance, xoff, yoff, offset in glyphs:
        out.append("    { %2d, %2d, %2d, %3d, %4d, %5d },  // U+%04X %s\n"
                   % (w, h, advance, xoff, yoff, offset, cp, glyph_comment(cp)))
    out.append("};\n")

    bitmaps = face["bitmaps"]
    out.append("\nstatic const uint8_t %s_bitmaps[%d] PROGMEM = {\n%s\n};\n"
               % (ident, len(bitmaps), c_words(list(bitmaps), 16, "0x%02X,")))

    out.append("\nstatic const Font %s = {\n"
               "    %d, %d, %d,\n"
               "    %s_codepoints, %s_glyphs, %s_bitmaps\n"
               "};\n"
               % (ident, face["line_height"], face["baseline"], len(glyphs),
                  ident, ident, ident))
    return "".join(out)


def write_header(path, faces, threshold):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    parts = [HEADER_PROLOGUE % threshold]
    for (ident, _px, _weight, purpose), face in faces:
        parts.append(emit_face(ident, face, purpose))
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("".join(parts))


def write_preview(path, faces, sample):
    """Kontaktówka 1:1 i 4:1 — żeby zobaczyć, co próg zrobił z kreską."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    zoom = 4
    lines = []
    for (ident, _px, _weight, _purpose), face in faces:
        index = {g[0]: g for g in face["glyphs"]}
        width = sum(index[ord(c)][3] for c in sample if ord(c) in index)
        strip = Image.new("L", (max(1, width), face["line_height"]), 0)
        pen = 0
        for ch in sample:
            glyph = index.get(ord(ch))
            if glyph is None:
                continue
            _cp, w, h, advance, xoff, yoff, offset = glyph
            stride = (w + 7) // 8
            for row in range(h):
                for col in range(w):
                    byte = face["bitmaps"][offset + row * stride + (col >> 3)]
                    if byte & (0x80 >> (col & 7)):
                        x = pen + xoff + col
                        y = face["baseline"] + yoff + row
                        if 0 <= x < strip.width and 0 <= y < strip.height:
                            strip.putpixel((x, y), 255)
            pen += advance
        lines.append((ident, strip))

    pad = 6
    sheet_w = max(s.width for _i, s in lines) * zoom + pad * 2
    sheet_h = sum(s.height * zoom + pad for _i, s in lines) + pad
    sheet = Image.new("L", (sheet_w, sheet_h), 10)
    y = pad
    for _ident, strip in lines:
        sheet.paste(strip.resize((strip.width * zoom, strip.height * zoom), Image.NEAREST),
                    (pad, y))
        y += strip.height * zoom + pad
    sheet.save(path)


# --- Główny przebieg -------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ttf", default=SOURCE_TTF, help="źródłowy font zmienny")
    ap.add_argument("--header", default=OUT_HEADER, help="wyjściowy plik .h")
    ap.add_argument("--threshold", type=int, default=THRESHOLD,
                    help="próg krycia (0-255), powyżej którego piksel to atrament")
    ap.add_argument("--preview", default=None,
                    help="opcjonalna kontaktówka .png z próbką tekstu")
    ap.add_argument("--sample", default="Zażółć gęślą jaźń · 130 km/h",
                    help="napis do kontaktówki")
    args = ap.parse_args()

    if not 1 <= args.threshold <= 255:
        sys.exit("Próg musi mieścić się w 1..255 (dostałem %d)." % args.threshold)
    if not os.path.exists(args.ttf):
        sys.exit("Nie ma pliku %s." % args.ttf)

    faces = []
    for spec in FACES:
        ident, px, weight, _purpose = spec
        print("%s: %d px, waga %d" % (ident, px, weight))
        faces.append((spec, build_face(args.ttf, px, weight, args.threshold)))

    write_header(args.header, faces, args.threshold)

    total = 0
    print("\n%-12s %-10s %5s %5s %8s %8s %8s"
          % ("krój", "instancja", "lh", "base", "bitmapy", "tablice", "razem"))
    for (ident, _px, _weight, _purpose), face in faces:
        count = len(face["glyphs"])
        tables = count * (SIZEOF_GLYPH + 2) + SIZEOF_FONT
        size = len(face["bitmaps"]) + tables
        total += size
        print("%-12s %-10s %5d %5d %6d B %6d B %6d B"
              % (ident, face["variation"], face["line_height"], face["baseline"],
                 len(face["bitmaps"]), tables, size))
    print("%-12s %-10s %5s %5s %8s %8s %6d B"
          % ("RAZEM", "", "", "", "", "", total))
    print("\nzapisano %s (%d glifów na krój, próg %d)"
          % (args.header, len(charset()), args.threshold))

    if args.preview:
        write_preview(args.preview, faces, args.sample)
        print("zapisano %s" % args.preview)


if __name__ == "__main__":
    main()
