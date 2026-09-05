#!/usr/bin/env python3
"""Generator schematu wyświetlacza pomocniczego 1,8" (ESP32-S3 + ST7735).

Rysuje:
    schematics/esp32_display_wiring.svg — jeden arkusz: dziesięć wejść 12 V
    przez PC817, panel ST7735 po SPI, zasilanie z +15 i dane po USB.

Uruchomienie (z katalogu głównego repo):
    python3 schematics/gen_esp32_display.py

Źródło danych: §11 docs/SCHEMATY_POLACZEN.md (tabela wejść i pinout) oraz
docs/WYSWIETLACZ_ESP32_1V8.md (projekt ekranów, zasilanie, protokół).
Numery pinów są kontraktem firmware'u — te same wartości siedzą
w arduino/esp32_display/esp32_display.ino. Po zmianie tabel popraw ten
plik i wygeneruj SVG ponownie — nie edytuj SVG ręcznie.

Stopień PC817 rysowany jest RAZ, bo dla wszystkich dziesięciu sygnałów
jest identyczny (§3.1 tego samego dokumentu). Reszta to tabela U1–U10.
"""

import math
import os
import re
import sys

try:
    from PIL import ImageFont
except ImportError:                                           # pragma: no cover
    ImageFont = None

# Font, którym przeglądarka narysuje ten arkusz (patrz font-family niżej).
# Służy WYŁĄCZNIE do zmierzenia napisów w kontroli geometrii — do samego
# SVG nic z niego nie trafia.
DEJAVU = {
    False: "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    True:  "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
}

STYLE = '''<style>
 .bg{fill:#ffffff}
 .w{stroke:#16242e;stroke-width:2.2;fill:none;stroke-linecap:round}
 .wp{stroke:#c0392b;stroke-width:2.8;fill:none;stroke-linecap:round}
 .wg{stroke:#3d4f5c;stroke-width:2.4;fill:none;stroke-linecap:round}
 .wo{stroke:#9a6b12;stroke-width:2.4;fill:none;stroke-linecap:round}
 .wu{stroke:#2d6a2d;stroke-width:2.6;fill:none;stroke-linecap:round}
 .wd{stroke:#8b9aa6;stroke-width:1.6;fill:none;stroke-dasharray:5 4}
 .sym{stroke:#16242e;stroke-width:2.2;fill:none}
 .symf{stroke:#16242e;stroke-width:2.2;fill:#16242e}
 .blk{fill:#f5f8fa;stroke:#2b3a45;stroke-width:2.2;rx:5}
 .blkm{fill:#eef4fa;stroke:#2b4a8a;stroke-width:2.2;rx:5}
 .blkr{fill:#fdf6e8;stroke:#9a6b12;stroke-width:2.2;rx:5}
 .blkc{fill:#eef8ee;stroke:#2d6a2d;stroke-width:2.2;rx:5}
 .opto{fill:#fbf3fb;stroke:#7a3d8f;stroke-width:2.2;rx:5;stroke-dasharray:7 4}
 .term{fill:#ffffff;stroke:#16242e;stroke-width:2.4}
 .note{fill:#fbfcfd;stroke:#c8d2da;stroke-width:1.5;rx:6}
 .tbl{fill:#ffffff;stroke:#c8d2da;stroke-width:1.5;rx:6}
 .tbh{fill:#eef4fa;stroke:none}
 .sectb{fill:#2d6a2d;rx:4}
 .ttl{font-size:23px;font-weight:bold;fill:#0d1c26}
 .sub{font-size:13px;fill:#576875}
 .sec{font-size:16px;font-weight:bold;fill:#2d6a2d}
 .sn{font-size:15px;font-weight:bold;fill:#ffffff;text-anchor:middle}
 .r{font-size:12.5px;font-weight:bold;fill:#a8321a}
 .rc{font-size:12.5px;font-weight:bold;fill:#a8321a;text-anchor:middle}
 .v{font-size:11.5px;fill:#40515e}
 .vc{font-size:11.5px;fill:#40515e;text-anchor:middle}
 .ve{font-size:11.5px;fill:#40515e;text-anchor:end}
 .lbl{font-size:11.5px;fill:#33424e}
 .lbb{font-size:13px;font-weight:bold;fill:#0d1c26;text-anchor:middle}
 .pin{font-size:11.5px;font-weight:bold;fill:#2b4a8a}
 .pine{font-size:11.5px;font-weight:bold;fill:#2b4a8a;text-anchor:end}
 .mref{font-size:14px;font-weight:bold;fill:#a8321a;text-anchor:middle}
 .mname{font-size:12.5px;font-weight:bold;fill:#0d1c26;text-anchor:middle}
 .te{font-size:12.5px;font-weight:bold;fill:#0d1c26;text-anchor:end}
 .tb{font-size:12px;font-weight:bold;fill:#0d1c26}
 .td{font-size:12px;fill:#33424e}
 .go{font-size:11px;font-weight:bold;fill:#9a6b12;text-anchor:middle}
 .gl{font-size:11px;font-weight:bold;fill:#3d4f5c;text-anchor:middle}
 .nh{font-size:13px;font-weight:bold;fill:#0d1c26}
 .nt{font-size:11.5px;fill:#4a5a66}
 .ldr{stroke:#7d8c99;stroke-width:1.3;fill:none}
 .ldrf{fill:#7d8c99;stroke:none}
</style>'''


def _class_metrics(css):
    """Rozmiar, grubość i wyrównanie każdej klasy tekstu — prosto z CSS-a
    wyżej, żeby kontrola geometrii mierzyła dokładnie to, co narysuje
    przeglądarka, a nie drugą kopię tych samych liczb."""
    out = {}
    for m in re.finditer(r"\.(\w+)\{([^}]*)\}", css):
        name, body = m.group(1), m.group(2)
        size = re.search(r"font-size:([\d.]+)px", body)
        if size is None:
            continue
        anchor = re.search(r"text-anchor:(\w+)", body)
        out[name] = (float(size.group(1)), "font-weight:bold" in body,
                     anchor.group(1) if anchor else "start")
    return out


METRICS = _class_metrics(STYLE)

# Ramki, w których napis MUSI się zmieścić. Reszta prostokątów to symbole.
FRAMES = ("blk", "blkm", "blkr", "blkc", "note", "tbl")


class Sheet:
    """Arkusz SVG — te same prymitywy i klasy stylów co gen_test_schematics.py."""

    def __init__(self, w, h, title, subtitle):
        self.o = []
        self.W, self.H = w, h
        self.rects = []          # do kontroli nachodzenia bloków
        self.texts = []          # do kontroli napisów (x, y, treść, klasa)
        self.a(f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
               f'viewBox="0 0 {w} {h}" font-family="DejaVu Sans, Verdana, sans-serif">')
        self.a(f'<title>{title}</title>')
        self.a(STYLE)
        self.a(f'<rect class="bg" x="0" y="0" width="{w}" height="{h}"/>')
        self.txt(40, 44, title, "ttl")
        self.txt(40, 68, subtitle, "sub")

    def a(self, s):
        self.o.append(s)

    def save(self, path):
        self.a("</svg>")
        open(path, "w", encoding="utf-8").write("\n".join(self.o))

    # ---- prymitywy
    def w(self, x1, y1, x2, y2, c="w"):
        self.a(f'<line class="{c}" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}"/>')

    def path(self, pts, c="w"):
        for i in range(len(pts) - 1):
            self.w(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1], c)

    def dot(self, x, y):
        self.a(f'<circle class="symf" cx="{x}" cy="{y}" r="3.8"/>')

    def txt(self, x, y, s, c="lbl"):
        self.texts.append((x, y, s, c))
        s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        self.a(f'<text class="{c}" x="{x}" y="{y}">{s}</text>')

    def box(self, x, y, w, h, c="blk", check=True):
        if check:
            self.rects.append((x, y, w, h, c))
        self.a(f'<rect class="{c}" x="{x}" y="{y}" width="{w}" height="{h}"/>')

    def leader(self, x0, y0, x1, y1, bend=None):
        """Cienki odnośnik od (x0,y0) do (x1,y1); grot przy (x1,y1)."""
        pts = [(x0, y0)] + ([bend] if bend else []) + [(x1, y1)]
        for i in range(len(pts) - 1):
            p, q = pts[i], pts[i + 1]
            self.a(f'<line class="ldr" x1="{p[0]}" y1="{p[1]}" '
                   f'x2="{q[0]}" y2="{q[1]}"/>')
        ax, ay = pts[-2]
        dx, dy = x1 - ax, y1 - ay
        ln = math.hypot(dx, dy) or 1.0
        ux, uy = dx / ln, dy / ln
        nx, ny = -uy, ux
        p1 = (x1 - ux * 9 + nx * 3.4, y1 - uy * 9 + ny * 3.4)
        p2 = (x1 - ux * 9 - nx * 3.4, y1 - uy * 9 - ny * 3.4)
        self.a(f'<polygon class="ldrf" points="{x1},{y1} '
               f'{p1[0]:.1f},{p1[1]:.1f} {p2[0]:.1f},{p2[1]:.1f}"/>')

    def sect(self, x, y, n, t):
        self.a(f'<rect class="sectb" x="{x}" y="{y-20}" width="26" height="26"/>')
        self.txt(x + 13, y - 1, n, "sn")
        self.txt(x + 38, y, t, "sec")

    # ---- symbole
    def term(self, x, y, t, sub=None):
        self.a(f'<circle class="term" cx="{x}" cy="{y}" r="7"/>')
        self.txt(x - 16, y + 5, t, "te")
        if sub:
            self.txt(x - 16, y + 22, sub, "ve")

    def fuse_h(self, x, y, ref, val):
        self.w(x, y, x + 10, y)
        self.a(f'<rect class="sym" x="{x+10}" y="{y-9}" width="38" height="18" fill="#fff"/>')
        self.w(x + 10, y, x + 48, y)
        self.w(x + 48, y, x + 58, y)
        self.txt(x + 29, y - 17, ref, "rc")
        self.txt(x + 29, y + 27, val, "vc")
        return x + 58

    def res_h(self, x, y, ref, val):
        self.w(x, y, x + 12, y)
        self.a(f'<rect class="sym" x="{x+12}" y="{y-10}" width="34" height="20" fill="#fff"/>')
        self.w(x + 46, y, x + 58, y)
        self.txt(x + 29, y - 17, ref, "rc")
        self.txt(x + 29, y + 28, val, "vc")
        return x + 58

    def tvs_v(self, x, y, ref, val):
        """TVS dwukierunkowy, wejście y, wyjście y+72."""
        self.w(x, y, x, y + 14)
        self.a(f'<polygon class="symf" points="{x-11},{y+32} {x+11},{y+32} {x},{y+14}"/>')
        self.a(f'<path class="sym" d="M {x-14} {y+38} L {x-14} {y+32} L {x+14} {y+32} '
               f'L {x+14} {y+26}"/>')
        self.a(f'<polygon class="symf" points="{x-11},{y+40} {x+11},{y+40} {x},{y+58}"/>')
        self.a(f'<path class="sym" d="M {x-14} {y+34} L {x-14} {y+40} L {x+14} {y+40} '
               f'L {x+14} {y+46}"/>')
        self.w(x, y + 58, x, y + 72)
        self.txt(x + 22, y + 26, ref, "r")
        self.txt(x + 22, y + 41, val, "v")
        return y + 72

    def star_gnd(self, x, y, label=None):
        self.w(x, y, x, y + 12)
        self.w(x - 18, y + 12, x + 18, y + 12, "wg")
        self.w(x - 11, y + 19, x + 11, y + 19, "wg")
        self.w(x - 4, y + 26, x + 4, y + 26, "wg")
        if label:
            self.txt(x, y + 42, label, "gl")

    def chassis_gnd(self, x, y, label=None):
        self.w(x, y, x, y + 12)
        self.w(x - 17, y + 12, x + 17, y + 12, "wo")
        for dx in (-12, -4, 4, 12):
            self.a(f'<line class="wo" x1="{x+dx}" y1="{y+12}" x2="{x+dx-8}" y2="{y+26}"/>')
        if label:
            self.txt(x, y + 44, label, "go")

    def module(self, x, y, w, h, ref, name, sub=None,
               left=(), right=(), cls="blkm", step=36):
        """Prostokąt modułu z nazwanymi zaciskami. Zwraca słownik punktów."""
        self.box(x, y, w, h, cls)
        self.txt(x + w / 2, y + 25, ref, "mref")
        self.txt(x + w / 2, y + 44, name, "mname")
        if sub:
            self.txt(x + w / 2, y + 62, sub, "vc")
        p = {}
        for i, (k, lab) in enumerate(left):
            py = y + 92 + i * step
            self.w(x - 18, py, x, py)
            self.txt(x + 10, py + 5, lab, "pin")
            p[k] = (x - 18, py)
        for i, (k, lab) in enumerate(right):
            py = y + 92 + i * step
            self.w(x + w, py, x + w + 18, py)
            self.txt(x + w - 10, py + 5, lab, "pine")
            p[k] = (x + w + 18, py)
        return p

    # ---- kontrola rysunku
    def check_overlaps(self):
        """Bloki i tabele nie mogą na siebie nachodzić — łatwo to przeoczyć
        przy ręcznie dobieranych współrzędnych, a w SVG nikt nie krzyknie."""
        bad = []
        for i, (x1, y1, w1, h1, c1) in enumerate(self.rects):
            for x2, y2, w2, h2, c2 in self.rects[i + 1:]:
                if x1 < x2 + w2 and x2 < x1 + w1 and y1 < y2 + h2 and y2 < y1 + h1:
                    bad.append(f"{c1}@({x1},{y1}) x {c2}@({x2},{y2})")
        if bad:
            raise SystemExit("bloki nachodzą na siebie: " + "; ".join(bad))

    # Pudełko napisu w pikselach; None, gdy nie ma czym mierzyć.
    def _text_box(self, x, y, s, cls):
        size, bold, anchor = METRICS[cls]
        w = _measure(s, size, bold)
        if anchor == "middle":
            x0 = x - w / 2
        elif anchor == "end":
            x0 = x - w
        else:
            x0 = x
        # DejaVu Sans: ascender ~0,76 em, descender ~0,24 em.
        return (x0, y - size * 0.78, x0 + w, y + size * 0.24)

    def check_text(self):
        """Napisy muszą mieścić się w arkuszu i w swoich ramkach, i nie mogą
        na siebie właźć.

        Sam SVG nigdy nie krzyknie: za długi napis po prostu wychodzi poza
        ramkę albo wchodzi na sąsiedni, a w diffie widać wyłącznie zmieniony
        łańcuch znaków. Dlatego mierzymy tu każdy napis tym samym fontem,
        którym narysuje go przeglądarka (DejaVu Sans z font-family arkusza).
        """
        if ImageFont is None or not os.path.exists(DEJAVU[False]):
            print("uwaga: brak Pillow albo fontu DejaVu — pomijam kontrolę napisów",
                  file=sys.stderr)
            return
        frames = [r for r in self.rects if r[4] in FRAMES]
        bad, boxes = [], []
        for x, y, s, cls in self.texts:
            if cls not in METRICS:
                bad.append(f"nieznana klasa tekstu {cls!r} przy {s!r}")
                continue
            if not s.strip():
                continue
            bx = self._text_box(x, y, s, cls)
            boxes.append((bx, s, cls))
            if bx[0] < 0 or bx[2] > self.W or bx[1] < 0 or bx[3] > self.H:
                bad.append(f"poza arkuszem: {s!r}")
                continue
            for fx, fy, fw, fh, fcls in frames:
                starts_inside = (fx <= bx[0] <= fx + fw and fy <= bx[1] <= fy + fh)
                if starts_inside:
                    if bx[2] > fx + fw - 2 or bx[3] > fy + fh:
                        bad.append(f"wychodzi z ramki {fcls}@({fx},{fy}): {s!r}")
                    continue
                # Ramki mają nieprzezroczyste tło i są rysowane w kolejności
                # wywołań — napis, który wpada w cudzą ramkę, po prostu
                # znika pod nią albo z niej wystaje. Jedno i drugie źle.
                if (bx[0] < fx + fw - 1 and fx < bx[2] - 1 and
                        bx[1] < fy + fh - 1 and fy < bx[3] - 1):
                    bad.append(f"napis wchodzi w ramkę {fcls}@({fx},{fy}): {s!r}")
        for i, (a, sa, ca) in enumerate(boxes):
            for b, sb, cb in boxes[i + 1:]:
                if (a[0] < b[2] - 1 and b[0] < a[2] - 1 and
                        a[1] < b[3] - 1 and b[1] < a[3] - 1):
                    bad.append(f"napisy zachodzą: {sa!r} [{ca}] x {sb!r} [{cb}]")
        if bad:
            raise SystemExit("napisy do poprawki:\n  " + "\n  ".join(bad))


_FONTS = {}


def _measure(s, size, bold):
    """Szerokość napisu w pikselach. Rozmiar zaokrąglamy tak, jak zrobi to
    rasteryzator — na tych wielkościach różnica i tak nie przekracza piksela."""
    key = (round(size), bold)
    if key not in _FONTS:
        _FONTS[key] = ImageFont.truetype(DEJAVU[bold], key[0])
    return _FONTS[key].getlength(s)


def opto(sh, x, y, ref, name, pinlab):
    """Transoptor PC817: dioda po lewej, fototranzystor po prawej.

    Zwraca punkty wyprowadzeń: p1/p2 (dioda, strona pojazdu),
    p4/p3 (kolektor/emiter, strona ESP32).
    """
    sh.a(f'<rect class="opto" x="{x}" y="{y}" width="150" height="130"/>')
    sh.txt(x + 75, y - 12, ref, "rc")
    sh.txt(x + 75, y + 152, name, "vc")
    sh.w(x, y + 32, x + 38, y + 32)
    sh.w(x + 38, y + 32, x + 38, y + 46)
    sh.a(f'<polygon class="symf" points="{x+27},{y+46} {x+49},{y+46} {x+38},{y+66}"/>')
    sh.w(x + 26, y + 66, x + 50, y + 66, "sym")
    sh.w(x + 38, y + 66, x + 38, y + 98)
    sh.w(x + 38, y + 98, x, y + 98)
    sh.a(f'<line class="sym" x1="{x+54}" y1="{y+44}" x2="{x+66}" y2="{y+34}"/>')
    sh.a(f'<polygon class="symf" points="{x+66},{y+34} {x+57},{y+34} {x+62},{y+42}"/>')
    sh.a(f'<line class="sym" x1="{x+54}" y1="{y+58}" x2="{x+66}" y2="{y+48}"/>')
    sh.a(f'<polygon class="symf" points="{x+66},{y+48} {x+57},{y+48} {x+62},{y+56}"/>')
    sh.txt(x - 8, y + 36, "1", "pine")
    sh.txt(x - 8, y + 102, "2", "pine")
    bx = x + 104
    sh.w(bx, y + 40, bx, y + 90)
    sh.w(bx, y + 48, bx + 26, y + 30)
    sh.w(bx, y + 82, bx + 22, y + 98)
    sh.a(f'<polygon class="symf" points="{bx+22},{y+98} {bx+12},{y+92} {bx+14},{y+101}"/>')
    sh.w(bx + 26, y + 30, bx + 26, y + 24)
    sh.w(bx + 26, y + 24, x + 150, y + 24)
    sh.w(bx + 22, y + 98, bx + 26, y + 102)
    sh.w(bx + 26, y + 102, x + 150, y + 102)
    sh.txt(x + 158, y + 28, "4", "pin")
    sh.txt(x + 158, y + 106, "3", "pin")
    sh.txt(x + 75, y + 168, pinlab, "vc")
    return {"p1": (x, y + 32), "p2": (x, y + 98),
            "p4": (x + 150, y + 24), "p3": (x + 150, y + 102)}


# Kolejność JEST kontraktem — zgodna z InputId w arduino/esp32_display/state.h
# i z tablicami TELLTALES[]/PANELS[] w assets.h.
INPUTS = [
    ("U1", "ABS", "GPIO4", "1", "złącze fabrycznego wyświetlacza"),
    ("U2", "Hamulec ręczny", "GPIO5", "1", "wyłącznik dźwigni"),
    ("U3", "Poduszka (SRS)", "GPIO6", "1", "złącze fabrycznego wyświetlacza"),
    ("U4", "Immobilizer", "GPIO7", "1", "złącze fabrycznego wyświetlacza"),
    ("U5", "Maska", "GPIO1", "2", "wyłącznik maski"),
    ("U6", "Drzwi przód lewe", "GPIO15", "2", "krańcówka oświetlenia wnętrza"),
    ("U7", "Drzwi przód prawe", "GPIO16", "2", "krańcówka oświetlenia wnętrza"),
    ("U8", "Drzwi tył lewe", "GPIO17", "2", "krańcówka oświetlenia wnętrza"),
    ("U9", "Drzwi tył prawe", "GPIO18", "2", "krańcówka oświetlenia wnętrza"),
    ("U10", "Klapa bagażnika", "GPIO2", "2", "wyłącznik klapy"),
]

# Panel ST7735 — para (pin ESP32, pin modułu). Kolejność rysowania = kolejność
# na obu blokach, dzięki czemu przewody idą prosto, bez plątaniny.
SPI_PINS = [
    ("sck", "GPIO12", "SCL / SCK"),
    ("mosi", "GPIO11", "SDA / MOSI"),
    ("cs", "GPIO10", "CS"),
    ("dc", "GPIO13", "DC / A0"),
    ("rst", "GPIO14", "RES"),
    ("bl", "GPIO21", "BLK / LED"),
    ("v33", "3V3", "VCC"),
    ("gnd_r", "GND", "GND"),
]

W, H = 1620, 1600
s = Sheet(W, H,
          "BCM v8.5 — wyświetlacz pomocniczy 1,8\" (ESP32-S3 + ST7735 128×160)",
          "Dziesięć wejść 12 V przez PC817, panel po SPI, zasilanie z +15, dane po USB.")
s.txt(40, 88, "Stopień PC817 narysowany raz — dla wszystkich dziesięciu sygnałów jest "
              "identyczny (§3.1 SCHEMATY_POLACZEN.md). Skrzyżowanie przewodów bez "
              "kropki = brak połączenia.", "sub")

# ======================================================================
#  A — WEJŚCIE 12 V PRZEZ PC817
# ======================================================================
s.sect(40, 130, "A", "WEJŚCIE 12 V PRZEZ PC817 — jeden stopień, powtarzany ×10")

YO = 190                      # górna krawędź transoptora
YS = YO + 32                  # linia sygnału

s.term(250, YS, "ABS  (U1)", "12 V z auta")
s.w(257, YS, 350, YS)
s.dot(300, YS)
s.w(300, YS, 300, YS + 20)
y_tvs = s.tvs_v(300, YS + 20, "D1", "SMBJ24A")
x = s.res_h(350, YS, "R1", "4,7 kΩ")
s.w(x, YS, 460, YS)
u1 = opto(s, 460, YO, "U1", "PC817 — ABS", "wyjście → GPIO4 (INPUT_PULLUP)")

# masa POJAZDU — wyłącznie strona diody transoptora i TVS
GV = 560
s.path([(u1["p2"][0], u1["p2"][1]), (340, u1["p2"][1]), (340, GV)])
s.path([(300, y_tvs), (300, GV), (340, GV)])
s.dot(340, GV)
s.chassis_gnd(340, GV, "MASA POJAZDU — nie łączyć z masą ESP32")

# ======================================================================
#  B — ESP32-S3 I PANEL ST7735
# ======================================================================
s.sect(900, 130, "B", "ESP32-S3 I PANEL ST7735 PO SPI")

# EW dobrane tak, żeby druga kolumna opisów (EX+96) nie dotykała nazw
# pinów SPI dosuniętych do prawej krawędzi — pilnuje tego check_text().
EX, EY, EW, EH = 900, 170, 310, 680
left = [("gnd_l", "GND")] + [(ref.lower(), gpio) for ref, _, gpio, _, _ in INPUTS]
right = [(k, gpio) for k, gpio, _ in SPI_PINS]
e = s.module(EX, EY, EW, EH, "A5", "ESP32-S3 (N16R8)",
             "esp32_display.ino · USB CDC On Boot = ON",
             left=left, right=right, cls="blkc")

# druga kolumna opisów w bloku: przy każdym GPIO nazwa sygnału
s.txt(EX + 96, e["gnd_l"][1] + 5, "masa emiterów PC817", "lbl")
for ref, name, _gpio, _scr, _src in INPUTS:
    s.txt(EX + 96, e[ref.lower()][1] + 5, name, "lbl")

# U1: kolektor → GPIO4, emiter → GND
s.path([(u1["p4"][0], u1["p4"][1]), (720, u1["p4"][1]),
        (720, e["u1"][1]), (e["u1"][0], e["u1"][1])])
s.path([(u1["p3"][0], u1["p3"][1]), (660, u1["p3"][1]),
        (660, e["gnd_l"][1]), (e["gnd_l"][0], e["gnd_l"][1])])

# U2–U10: dziewięć identycznych stopni, zebranych w wiązkę
BUS = 800
ys = [e[ref.lower()][1] for ref, _, _, _, _ in INPUTS[1:]]
s.w(BUS, ys[0], BUS, ys[-1])
for py in ys:
    s.w(BUS, py, e["u2"][0], py)
s.w(BUS - 30, (ys[0] + ys[-1]) / 2, BUS, (ys[0] + ys[-1]) / 2)
s.txt(BUS - 38, (ys[0] + ys[-1]) / 2 - 8, "U2–U10 — dziewięć identycznych", "ve")
s.txt(BUS - 38, (ys[0] + ys[-1]) / 2 + 8, "stopni PC817 (tabela niżej)", "ve")

# --- panel ST7735
PX, PY, PW, PH = 1400, 170, 180, 420
s.box(PX, PY, PW, PH, "blk")
s.txt(PX + PW / 2, PY + 25, "DS3", "mref")
s.txt(PX + PW / 2, PY + 44, "PANEL ST7735", "mname")
s.txt(PX + PW / 2, PY + 62, "1,8\" 128×160, pionowo", "vc")
for k, _gpio, plab in SPI_PINS:
    py = e[k][1]
    s.w(PX - 18, py, PX, py)
    s.txt(PX + 10, py + 5, plab, "pin")
    s.w(e[k][0], py, PX - 18, py)
s.txt((e["bl"][0] + PX - 18) / 2, e["bl"][1] - 8, "PWM — kanał LEDC", "vc")

s.box(1240, 620, 340, 210, "note")
s.txt(1258, 646, "PANEL — co sprawdzić przy module", "nh")
for i, line in enumerate([
        "Kolejność pinów na module bywa różna — czytaj",
        "opisy na płytce, nie kolejność na tym rysunku.",
        "Moduł z AMS1117 i buforem 74HC245 zasilaj 5 V;",
        "moduł bez stabilizatora — 3,3 V. Sygnały: 3,3 V.",
        "BLK bywa zwarty do VCC — wtedy ściemnianie",
        "wymaga przecięcia ścieżki albo tranzystora.",
        "TFT_eSPI: User_Setup z ST7735_DRIVER,",
        "TFT_WIDTH 128 / TFT_HEIGHT 160, SPI 27 MHz."]):
    s.txt(1258, 670 + i * 19, line, "nt")

# ======================================================================
#  tabela wejść U1–U10
# ======================================================================
TX, TY, TW = 60, 660, 770
ROWS = len(INPUTS)
s.box(TX, TY, TW, 52 + ROWS * 24, "tbl")
s.a(f'<rect class="tbh" x="{TX+2}" y="{TY+2}" width="{TW-4}" height="42"/>')
s.txt(TX + 20, TY + 28, "DZIESIĘĆ WEJŚĆ — każde przez własny stopień PC817 "
                        "(R 4,7 kΩ + TVS)", "nh")
COLS = (20, 70, 240, 330, 400)
for i, (ref, name, gpio, scr, src) in enumerate(INPUTS):
    py = TY + 66 + i * 24
    s.txt(TX + COLS[0], py, ref, "tb")
    s.txt(TX + COLS[1], py, name, "td")
    s.txt(TX + COLS[2], py, gpio, "tb")
    s.txt(TX + COLS[3], py, "ekran " + scr, "td")
    s.txt(TX + COLS[4], py, src, "td")

s.txt(TX, TY + 52 + ROWS * 24 + 18,
      "Oznaczenia U1–U10, D1, F12, M8, A5 i DS3 należą do TEGO podukładu — "
      "arkusze wariantu testowego (§10) mają własną numerację.", "nt")

# ======================================================================
#  C — ZASILANIE I USB
# ======================================================================
s.sect(40, 1000, "C", "ZASILANIE Z +15 (PO ZAPŁONIE), DANE PO USB")

# Góra bloku bucka musi być PONIŻEJ nagłówka sekcji C, inaczej jasne tło
# prostokąta zamaluje jego koniec. Wysokość linii +15 wynika z bloku:
# module() stawia pierwszy zacisk 92 px od górnej krawędzi.
MY = 1024
YP = MY + 92
s.term(250, YP, "+15", "po zapłonie")
s.w(257, YP, 320, YP)
x = s.fuse_h(320, YP, "F12", "2 A")
s.w(x, YP, 442, YP)
m1 = s.module(460, MY, 214, 200, "M8", "BUCK 12 V → 5 V", "MP1584 (klasa jak M6)",
              left=[("in+", "IN+"), ("in-", "IN−")],
              right=[("out+", "OUT+"), ("out-", "OUT−")], cls="blkr")
s.path([(m1["in-"][0], m1["in-"][1]), (410, m1["in-"][1]), (410, 1240)])
s.star_gnd(410, 1240, "PUNKT GWIAZDOWY")

# 5 V i masa w spód płytki
X5, XG, XU = 960, 1045, 1130
s.w(X5, EY + EH, X5, EY + EH + 40)
s.w(XG, EY + EH, XG, EY + EH + 40)
s.w(XU, EY + EH, XU, EY + EH + 40)
s.txt(X5 + 8, EY + EH + 22, "5V", "lbl")
s.txt(XG + 8, EY + EH + 22, "GND", "lbl")
s.txt(XU + 8, EY + EH + 22, "USB-C (natywne, 303a:1001)", "lbl")
s.path([(m1["out+"][0], m1["out+"][1]), (X5, m1["out+"][1]), (X5, EY + EH + 40)])
s.path([(m1["out-"][0], m1["out-"][1]), (XG, m1["out-"][1]), (XG, EY + EH + 40)])
s.dot(XG, m1["out-"][1])
s.path([(XG, m1["out-"][1]), (XG, 1240)])
s.star_gnd(XG, 1240, "ta sama gwiazda co M910q")

# USB do M910q
s.path([(XU, EY + EH + 40), (XU, 1180), (1330, 1180)], "wu")
s.box(1330, 1120, 250, 120, "blkm")
s.txt(1455, 1152, "M910q", "mname")
s.txt(1455, 1176, "port USB (przez hub)", "vc")
s.txt(1455, 1200, "/dev/ttyACM_display", "vc")
s.txt(1455, 1222, "reguła udev 99-bcm-esp32-display", "vc")
s.txt(1230, 1166, "USB CDC 115200", "vc")

# ======================================================================
#  NOTATKI
# ======================================================================
s.box(60, 1330, 740, 110, "note")
s.txt(80, 1356, "PINY ESP32-S3 — zajęte i zakazane", "nh")
for i, line in enumerate([
        "Użyte: 1, 2, 4, 5, 6, 7 (wejścia) · 10–14 i 21 (panel) · "
        "15–18 (wejścia drzwi).",
        "NIE WOLNO: 0, 3, 45, 46 — strapping (płytka nie wstanie albo "
        "wejdzie w bootloader);",
        "19, 20 — natywne USB, czyli cały protokół; 26–37 — flash "
        "i PSRAM modułu N16R8."]):
    s.txt(80, 1382 + i * 20, line, "nt")

s.box(820, 1330, 760, 110, "note")
s.txt(840, 1356, "WEJŚCIA I MASY", "nh")
for i, line in enumerate([
        "Wszystkie dziesięć w trybie INPUT_PULLUP, stan aktywny LOW, "
        "debounce 30 ms (state.h).",
        "Polaryzacji NIE zakładaj — zmierz. Krańcówki drzwi w autach tej "
        "epoki zwykle zwierają do masy.",
        "Masa pojazdu dotyka wyłącznie diod transoptorów (piny 1–2). "
        "Po stronie pinów 3–4 jest masa ESP32."]):
    s.txt(840, 1382 + i * 20, line, "nt")

s.box(60, 1470, 1520, 104, "note")
s.txt(80, 1496, "ZASILANIE I VBUS — dwa warianty, oba poprawne", "nh")
for i, line in enumerate([
        "Osobno z +15 (rysunek): ekran wstaje z zapłonem, kontrolki działają "
        "zanim M910q się podniesie. WARUNEK: przetnij żyłę VBUS (czerwoną) "
        "w kablu USB — 5 V z buck'a i 5 V z portu",
        "nie mogą się bić. Masa w kablu USB zostaje połączona, inaczej nie ma "
        "wspólnego punktu odniesienia dla danych.   ·   Tylko z USB: bez M8 "
        "i bez bezpiecznika, jeden kabel, zero poboru na postoju,",
        "ale ekran wstaje dopiero z komputerem — sprawdź też w BIOS-ie, czy "
        "port nie jest zasilany w S5 (Always On USB). Uzasadnienie obu: "
        "docs/WYSWIETLACZ_ESP32_1V8.md §Zasilanie i pobór."]):
    s.txt(80, 1522 + i * 20, line, "nt")

s.check_overlaps()
s.check_text()
s.save("schematics/esp32_display_wiring.svg")
print("ok — schematics/esp32_display_wiring.svg")
