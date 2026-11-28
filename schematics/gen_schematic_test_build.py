#!/usr/bin/env python3
"""Generator skróconego schematu ideowego wariantu testowo-rozwojowego.

Rysuje:
    schematics/schematic_test_build.svg — jeden arkusz: symbole elektryczne,
    elementy pogrupowane w bloki. Szybki przegląd całości; do montażu służą
    dwa arkusze komponentowe schematic_test_power.svg i
    schematic_test_signals.svg (generator: gen_test_schematics.py).

Uruchomienie (z katalogu głównego repo):
    python3 schematics/gen_schematic_test_build.py

Źródła liczb: docs/ZASILANIE_BUFOROWANE.md (ZB — obowiązuje przy
rozbieżności), docs/SCHEMATY_POLACZEN.md §10 (numeracja bezpieczników
i przewodów wariantu testowego), docs/WDROZENIE_TESTOWE.md §3.
Po zmianie tych dokumentów popraw ten plik i wygeneruj SVG ponownie —
nie edytuj SVG ręcznie.

Wynik jest deterministyczny (ta sama treść przy każdym uruchomieniu).
Przed zapisem generator sprawdza, że bloki nie nachodzą na siebie, a każdy
napis mieści się w arkuszu, w swojej ramce i nie wchodzi na inny napis
(pomiar fontem DejaVu Sans przez Pillow, jeśli jest dostępny — bez niego
kontrola napisów jest pomijana z ostrzeżeniem).
"""

import os
import re
import sys

try:
    from PIL import ImageFont
except ImportError:                                           # pragma: no cover
    ImageFont = None

OUT = "schematics/schematic_test_build.svg"
W, H = 1600, 1400

DEJAVU = {
    False: "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    True:  "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
}

# Ten sam język wizualny co poprzednia wersja arkusza: kolory, klasy, font.
STYLE = '''<style>
 .bg{fill:#ffffff}
 .w{stroke:#1b2b36;stroke-width:2;fill:none;stroke-linecap:round}
 .wp{stroke:#c0392b;stroke-width:2.4;fill:none;stroke-linecap:round}
 .wg{stroke:#46586a;stroke-width:2;fill:none;stroke-linecap:round}
 .wo{stroke:#9a6b12;stroke-width:2;fill:none;stroke-linecap:round}
 .wd{stroke:#7a8b99;stroke-width:1.6;fill:none;stroke-dasharray:5 4}
 .bus{stroke:#d9a68c;stroke-width:9;fill:none;stroke-linecap:round}
 .busn{stroke:#c9b8a0;stroke-width:9;fill:none;stroke-linecap:round}
 .sym{stroke:#1b2b36;stroke-width:2;fill:none}
 .symf{stroke:#1b2b36;stroke-width:2;fill:#1b2b36}
 .blk{fill:#f7f9fb;stroke:#2b3a45;stroke-width:2;rx:4}
 .blkg{fill:#eef7ee;stroke:#2d6a2d;stroke-width:2;rx:4}
 .blko{fill:#fdf3e6;stroke:#9a6b12;stroke-width:2;rx:4}
 .blkb{fill:#eef4fa;stroke:#2b4a8a;stroke-width:2;rx:4}
 .grp{fill:none;stroke:#7a3d8f;stroke-width:1.6;stroke-dasharray:7 4;rx:6}
 .grpg{fill:none;stroke:#8b9aa6;stroke-width:1.6;stroke-dasharray:7 4;rx:6}
 .note{fill:#fbfcfd;stroke:#c8d2da;stroke-width:1.5;rx:5}
 .term{fill:#ffffff;stroke:#1b2b36;stroke-width:2.2}
 .ttl{font-size:21px;font-weight:bold;fill:#10202b}
 .sub{font-size:12.5px;fill:#5a6b78}
 .sec{font-size:14px;font-weight:bold;fill:#2d6a2d;letter-spacing:0.5px}
 .secb{font-size:14px;font-weight:bold;fill:#2b4a8a;letter-spacing:0.5px}
 .ref{font-size:12px;font-weight:bold;fill:#a8321a}
 .refe{font-size:12px;font-weight:bold;fill:#a8321a;text-anchor:end}
 .refc{font-size:12px;font-weight:bold;fill:#a8321a;text-anchor:middle}
 .lbl{font-size:11.5px;fill:#33424e}
 .lbe{font-size:11.5px;fill:#33424e;text-anchor:end}
 .lbc{font-size:11.5px;fill:#33424e;text-anchor:middle}
 .lbb{font-size:12px;font-weight:bold;fill:#10202b;text-anchor:middle}
 .lbbs{font-size:12px;font-weight:bold;fill:#10202b}
 .lbbe{font-size:12px;font-weight:bold;fill:#10202b;text-anchor:end}
 .grl{font-size:11.5px;font-weight:bold;fill:#7a3d8f}
 .go{font-size:11px;font-weight:bold;fill:#9a6b12;text-anchor:middle}
 .nh{font-size:13px;font-weight:bold;fill:#10202b}
 .nt{font-size:11.5px;fill:#4a5a66}
</style>'''


def _class_metrics(css):
    """Rozmiar, grubość i wyrównanie każdej klasy tekstu — wprost z CSS."""
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
FRAMES = ("blk", "blkg", "blko", "blkb", "note", "grp", "grpg")
MIN_FONT = 9.0

_FONTS = {}


def _measure(s, size, bold):
    key = (round(size), bold)
    if key not in _FONTS:
        _FONTS[key] = ImageFont.truetype(DEJAVU[bold], key[0])
    return _FONTS[key].getlength(s)


class Sheet:
    def __init__(self, w, h, title, subtitle):
        self.o, self.rects, self.texts = [], [], []
        self.W, self.H = w, h
        self.a(f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
               f'viewBox="0 0 {w} {h}" font-family="DejaVu Sans, Verdana, sans-serif">')
        self.a(f'<title>{title}</title>')
        self.a(STYLE)
        self.a(f'<rect class="bg" x="0" y="0" width="{w}" height="{h}"/>')
        self.txt(24, 34, "Schemat elektryczny — wariant testowo-rozwojowy (skrót)", "ttl")
        self.txt(24, 56, subtitle, "sub")
        self.a(f'<line x1="24" y1="68" x2="{w-24}" y2="68" stroke="#c8d2da" stroke-width="1.5"/>')

    def a(self, s):
        self.o.append(s)

    # ---- prymitywy
    def w(self, x1, y1, x2, y2, c="w"):
        self.a(f'<line class="{c}" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}"/>')

    def path(self, pts, c="w"):
        d = " ".join(f"{'M' if i == 0 else 'L'} {x} {y}" for i, (x, y) in enumerate(pts))
        self.a(f'<path class="{c}" d="{d}"/>')

    def dot(self, x, y):
        self.a(f'<circle class="symf" cx="{x}" cy="{y}" r="3.2"/>')

    def txt(self, x, y, s, c="lbl"):
        self.texts.append((x, y, s, c))
        s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        self.a(f'<text class="{c}" x="{x}" y="{y}">{s}</text>')

    def box(self, x, y, w, h, c="blk"):
        self.rects.append((x, y, w, h, c))
        self.a(f'<rect class="{c}" x="{x}" y="{y}" width="{w}" height="{h}"/>')

    def sep(self, y):
        self.a(f'<line x1="24" y1="{y}" x2="{self.W-24}" y2="{y}" stroke="#c8d2da" '
               f'stroke-width="1.5" stroke-dasharray="6 5"/>')

    # ---- symbole
    def fuse_h(self, x, y, c="w"):
        """Bezpiecznik poziomy, od x do x+50."""
        self.w(x, y, x + 8, y, c)
        self.a(f'<rect class="sym" x="{x+8}" y="{y-8}" width="34" height="16" fill="#ffffff"/>')
        self.w(x + 8, y, x + 42, y)
        self.w(x + 42, y, x + 50, y, c)
        return x + 50

    def fuse_v(self, x, y, c="w"):
        """Bezpiecznik pionowy, od y do y+50."""
        self.w(x, y, x, y + 8, c)
        self.a(f'<rect class="sym" x="{x-8}" y="{y+8}" width="16" height="34" fill="#ffffff"/>')
        self.w(x, y + 8, x, y + 42)
        self.w(x, y + 42, x, y + 50, c)
        return y + 50

    def res_h(self, x, y):
        self.w(x, y, x + 10, y)
        self.a(f'<rect class="sym" x="{x+10}" y="{y-7}" width="30" height="14" fill="#ffffff"/>')
        self.w(x + 40, y, x + 50, y)
        return x + 50

    def gnd(self, x, y):
        self.w(x, y, x, y + 8, "wg")
        self.w(x - 13, y + 8, x + 13, y + 8, "wg")
        self.w(x - 8, y + 13, x + 8, y + 13, "wg")
        self.w(x - 3, y + 18, x + 3, y + 18, "wg")

    def chassis(self, x, y):
        self.w(x, y, x, y + 10, "wo")
        self.w(x - 15, y + 10, x + 15, y + 10, "wo")
        for dx in (-10, -2, 6, 14):
            self.w(x + dx, y + 10, x + dx - 7, y + 21, "wo")

    def tvs_v(self, x, y):
        """TVS dwukierunkowy, od y do y+48."""
        self.w(x, y, x, y + 8)
        self.a(f'<path class="symf" d="M {x-10} {y+8} L {x+10} {y+8} L {x} {y+24} Z"/>')
        self.a(f'<path class="symf" d="M {x-10} {y+40} L {x+10} {y+40} L {x} {y+24} Z"/>')
        self.a(f'<path class="sym" d="M {x-13} {y+20} L {x-10} {y+24} L {x+10} {y+24} '
               f'L {x+13} {y+28}"/>')
        self.w(x, y + 40, x, y + 48)
        return y + 48

    def cap_v(self, x, y):
        """Kondensator elektrolityczny, od y do y+36."""
        self.w(x, y, x, y + 14)
        self.w(x - 11, y + 14, x + 11, y + 14)
        self.a(f'<path class="sym" d="M {x-11} {y+24} Q {x} {y+17} {x+11} {y+24}"/>')
        self.w(x, y + 21, x, y + 36)
        self.txt(x - 20, y + 12, "+", "lbl")
        return y + 36

    def cell_v(self, x, y):
        """Akumulator (jeden blok 12 V), od y (+) do y+34 (−)."""
        self.w(x, y, x, y + 12)
        self.w(x - 14, y + 12, x + 14, y + 12)
        self.a(f'<line class="sym" x1="{x-8}" y1="{y+19}" x2="{x+8}" y2="{y+19}" '
               f'stroke-width="4"/>')
        self.w(x - 14, y + 25, x + 14, y + 25)
        self.a(f'<line class="sym" x1="{x-8}" y1="{y+31}" x2="{x+8}" y2="{y+31}" '
               f'stroke-width="4"/>')
        self.w(x, y + 31, x, y + 34)
        return y + 34

    def switch_h(self, x, y, c="w"):
        """Zestyk zwierny, od x do x+42 (rysowany rozwarty)."""
        self.a(f'<circle class="symf" cx="{x}" cy="{y}" r="3"/>')
        self.w(x, y, x + 34, y - 15)
        self.a(f'<circle class="term" cx="{x+42}" cy="{y}" r="3.5"/>')
        return x + 42

    def term(self, x, y):
        self.a(f'<circle class="term" cx="{x}" cy="{y}" r="6"/>')

    def module(self, x, y, w, h, cls, lines):
        """Blok z wyśrodkowanymi liniami: [(tekst, klasa), ...]."""
        self.box(x, y, w, h, cls)
        n = len(lines)
        top = y + h / 2 - (n - 1) * 8 + 4
        for i, (t, c) in enumerate(lines):
            self.txt(x + w / 2, top + i * 16, t, c)

    def note(self, x, y, w, h, head, lines, step=17):
        self.box(x, y, w, h, "note")
        self.txt(x + 14, y + 22, head, "nh")
        for i, t in enumerate(lines):
            self.txt(x + 14, y + 44 + i * step, t, "nt")

    # ---- kontrole
    def check_overlaps(self):
        solid = [r for r in self.rects if r[4] not in ("grp", "grpg")]
        bad = []
        for i, (x1, y1, w1, h1, c1) in enumerate(solid):
            for x2, y2, w2, h2, c2 in solid[i + 1:]:
                if x1 < x2 + w2 and x2 < x1 + w1 and y1 < y2 + h2 and y2 < y1 + h1:
                    bad.append(f"{c1}@({x1},{y1}) x {c2}@({x2},{y2})")
        for x, y, w, h, c in self.rects:
            if x < 0 or y < 0 or x + w > self.W or y + h > self.H:
                bad.append(f"{c}@({x},{y}) poza arkuszem")
        if bad:
            raise SystemExit("bloki nachodzą na siebie: " + "; ".join(bad))

    def _text_box(self, x, y, s, cls):
        size, bold, anchor = METRICS[cls]
        w = _measure(s, size, bold)
        x0 = x - w / 2 if anchor == "middle" else (x - w if anchor == "end" else x)
        return (x0, y - size * 0.78, x0 + w, y + size * 0.24)

    def check_text(self):
        bad = []
        for _, _, s, cls in self.texts:
            if cls not in METRICS:
                bad.append(f"nieznana klasa {cls!r} przy {s!r}")
            elif METRICS[cls][0] < MIN_FONT:
                bad.append(f"za mały font {cls!r}")
        if ImageFont is None or not os.path.exists(DEJAVU[False]):
            print("uwaga: brak Pillow albo fontu DejaVu — pomijam pomiar napisów",
                  file=sys.stderr)
            if bad:
                raise SystemExit("\n".join(bad))
            return
        frames = [r for r in self.rects if r[4] in FRAMES]
        boxes = []
        for x, y, s, cls in self.texts:
            if cls not in METRICS or not s.strip():
                continue
            bx = self._text_box(x, y, s, cls)
            boxes.append((bx, s, cls))
            if bx[0] < 0 or bx[2] > self.W or bx[1] < 0 or bx[3] > self.H:
                bad.append(f"poza arkuszem: {s!r}")
                continue
            for fx, fy, fw, fh, fcls in frames:
                inside = (fx <= bx[0] <= fx + fw and fy <= bx[1] <= fy + fh)
                if inside:
                    if bx[2] > fx + fw - 3 or bx[3] > fy + fh - 1:
                        bad.append(f"wychodzi z ramki {fcls}@({fx},{fy}): {s!r}")
                    continue
                if (bx[0] < fx + fw - 1 and fx < bx[2] - 1 and
                        bx[1] < fy + fh - 1 and fy < bx[3] - 1):
                    bad.append(f"napis wchodzi w ramkę {fcls}@({fx},{fy}): {s!r}")
        for i, (a, sa, ca) in enumerate(boxes):
            for b, sb, cb in boxes[i + 1:]:
                if (a[0] < b[2] - 1 and b[0] < a[2] - 1 and
                        a[1] < b[3] - 1 and b[1] < a[3] - 1):
                    bad.append(f"napisy zachodzą: {sa!r} x {sb!r}")
        if bad:
            raise SystemExit("napisy do poprawki:\n  " + "\n  ".join(bad))

    def save(self, path):
        self.a("</svg>")
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(self.o) + "\n")


# =====================================================================
s = Sheet(W, H,
          "BCM v8.5 — schemat elektryczny wariantu testowo-rozwojowego, "
          "wersja skrócona (M910q)",
          "Ładowanie 2 × XY-SK120 przez K1 · bank 7 × CSB HR1221W w dwóch koszach "
          "(4 + 3) · LVD XH-M609 · step-up 20 V / 200 W · M910q zasilany stale. "
          "Do montażu: schematic_test_power.svg i schematic_test_signals.svg.")

# ------------------------------------------------------------------ A
YA = 175                      # szyna „+" toru ładowania
s.txt(24, 96, "A · TOR ŁADOWANIA — akumulator rozruchowy → 2 × XY-SK120 → bank (ZB §5.4)", "sec")

# akumulator rozruchowy
s.txt(70, 124, "Akumulator", "lbb")
s.txt(70, 139, "rozruchowy", "lbb")
s.w(60, YA, 108, YA, "wp")
s.w(60, YA, 60, 190, "wp")
s.cell_v(60, 190)
s.txt(16, 212, "BT0", "ref")
s.txt(16, 227, "12 V", "lbl")
s.w(60, 224, 60, 262, "wo")
s.chassis(60, 262)
s.txt(16, 304, "„−” BT0 przez", "lbl")
s.txt(16, 319, "nadwozie", "lbl")

# F1
s.fuse_h(108, YA, "wp")
s.txt(133, 156, "F1 · 20 A", "refc")
s.txt(133, 199, "MIDI/ANL", "lbc")
s.txt(133, 214, "≤ 30 cm od klemy", "lbc")
s.w(158, YA, 330, YA, "wp")
s.txt(212, 166, "6 mm² · ~5 m", "lbc")

# ochrona wejścia: TVS + C1
s.box(258, 108, 172, 165, "grp")
s.txt(266, 126, "Ochrona wejścia", "grl")
s.dot(300, YA)
s.tvs_v(300, YA)
s.txt(268, 205, "D5", "ref")
s.w(300, YA + 48, 300, 228, "wg")
s.gnd(300, 228)
s.txt(316, 200, "TVS", "lbl")
s.txt(316, 215, "SMCJ20CA", "lbl")
s.w(330, YA, 395, YA, "wp")
s.dot(395, YA)
s.cap_v(395, YA)
s.w(395, YA + 36, 395, 228, "wg")
s.gnd(395, 228)
s.txt(406, 205, "C1", "ref")
s.txt(334, 266, "470 µF / 35 V", "lbl")

s.w(395, YA, 480, YA, "wp")

# K1 — styk
s.switch_h(480, YA, "wp")
s.txt(520, 114, "K1 · 30 A SPDT", "refc")
s.txt(520, 129, "zwiera przy zapłonie", "lbc")
s.txt(530, 144, "(z D+: tylko przy pracy silnika)", "lbc")
s.w(522, YA, 600, YA, "wp")
s.a('<line class="wd" x1="499" y1="167" x2="499" y2="292"/>')
# cewka K1
s.box(476, 292, 46, 22, "blk")
s.txt(499, 307, "K1", "lbb")
s.w(522, 303, 548, 303, "wg")
s.gnd(548, 303)
s.term(250, 303)
s.txt(238, 299, "Zapłon / D+", "lbbe")
s.txt(238, 314, "12 V: kluczyk ON / D+", "lbe")
s.w(256, 303, 340, 303)
s.fuse_h(340, 303)
s.txt(365, 290, "FK · 1 A", "refc")
s.txt(365, 327, "przy wpięciu, 0,75 mm²", "lbc")
s.w(390, 303, 476, 303)
s.txt(499, 343, "cewka K1 · D6 1N4007", "lbc")
s.txt(499, 358, "równolegle (katoda → 86)", "lbc")

# rozgałęzienie na dwie ładowarki
YB1, YB2 = YA, 255
s.dot(600, YA)
s.w(600, YA, 600, YB2, "wp")
s.w(600, YB2, 640, YB2, "wp")
s.w(600, YA, 640, YA, "wp")
s.txt(594, 222, "2,5 mm²", "lbe")
for yb, n, ref1, ref2, fc in ((YB1, "#1", "M1a", "M2a", "FC1"),
                              (YB2, "#2", "M1b", "M2b", "FC2")):
    s.module(640, yb - 32, 190, 64, "blkg",
             [(f"{ref1} · XY-SK120 {n}", "lbb"), ("CV 14,40 V · CC 5,0 A", "lbc"),
              ("72 W, IN− = OUT−", "lbc")])
    s.w(830, yb, 870, yb, "wp")
    s.module(870, yb - 32, 190, 64, "blko",
             [(f"{ref2} · XH-M603 {n}", "lbb"), ("rozwiera 15,30 V", "lbc"),
              ("powrót 14,00 V", "lbc")])
    s.w(1060, yb, 1090, yb, "wp")
    s.fuse_h(1090, yb, "wp")
    s.txt(1115, yb - 15, f"{fc} · 7,5 A", "refc")
    s.w(1140, yb, 1180, yb, "wp")
s.txt(1115, YB1 + 25, "ATO, przy OUT+", "lbc")
s.txt(1115, YB2 + 25, "ATO, przy OUT+", "lbc")
s.txt(950, 300, "XH-M603 zasilany z wyjścia swojej XY-SK120", "lbc")
s.txt(950, 315, "— na postoju martwy i rozwarty (ZB §5.4, §6.4)", "lbc")
s.w(1180, YB1, 1180, YB2, "wp")
s.dot(1180, YB2)
s.txt(1192, 220, "złączenie", "lbl")
s.txt(1192, 235, "gałęzi", "lbl")
s.w(1180, YB2, 1180, 425, "wp")
s.txt(1196, 330, "4 mm² · ≤ 1 m", "lbl")
s.txt(1196, 345, "do F12 przy L+", "lbl")

s.note(1320, 92, 256, 238, "Tor ładowania — co tu jest",
       ["K1 rozwarty przy wyłączonym zapłonie",
        "(z D+: przy zgaszonym silniku).",
        "Kluczyk ON bez silnika ≈ 13 A",
        "z rozruchowego — cewka z D+",
        "albo LVP 12,8 V (ZB §5.4).",
        "Bez diody szeregowej i bez",
        "izolacji — wspólna masa, jeden",
        "punkt przy banku (ZB §5.6).",
        "2 × 5 A z ładowarek, netto do banku",
        "≈ 5 A; z instalacji 11,9–13,0 A.",
        "Oba XH-M603 widzą bank: przy",
        "15,30 V rozwierają obie gałęzie.",
        "F1, F7, F12: klasa ≥ 2,5 kA (ZB §8.1)."], step=15)

s.sep(395)

# ------------------------------------------------------------------ B
s.txt(24, 420, "B · BANK W DWÓCH KOSZACH 4 + 3 · LVD · ROZŁĄCZNIK MASY (ZB §4.3, §7)", "sec")
YP, YN = 500, 640             # bloki zbiorcze „+" i „−"
# doprowadzenie ładowania (przewód B) do L+
s.w(1180, 425, 1180, 440, "wp")
s.w(1180, 440, 130, 440, "wp")
s.w(130, 440, 130, 446, "wp")
s.fuse_v(130, 446, "wp")
s.w(130, 496, 130, YP, "wp")
s.txt(106, 466, "F12 · 15 A", "refe")
s.txt(106, 481, "MIDI/ANL", "lbe")
s.txt(106, 496, "≤ 30 cm", "lbe")
s.txt(760, 434, "przewód B: ładowanie 4 mm² → F12 → blok L+", "lbc")

# kosze
s.box(110, 470, 400, 220, "grp")
s.box(660, 470, 310, 220, "grp")
s.txt(200, 682, "KOSZ L — #1…#4", "grl")
s.txt(700, 682, "KOSZ P — #5…#7", "grl")
s.w(130, YP, 470, YP, "bus")
s.w(160, YN, 470, YN, "busn")
s.w(700, YP, 940, YP, "bus")
s.w(700, YN, 940, YN, "busn")
s.w(130, YP, 470, YP, "wp")
s.w(160, YN, 470, YN, "wg")
s.w(700, YP, 940, YP, "wp")
s.w(700, YN, 940, YN, "wg")
s.txt(120, 668, "L−", "lbbs")
s.txt(945, 668, "P−", "lbbs")
s.txt(945, 520, "P+", "lbbs")
s.txt(114, 524, "L+", "lbbs")
pk = [(180, 1), (260, 2), (340, 3), (420, 4), (740, 5), (820, 6), (900, 7)]
for x, n in pk:
    s.dot(x, YP)
    s.fuse_v(x, YP)
    s.txt(x + 12, YP + 24, f"FB{n}", "ref")
    s.txt(x + 12, YP + 38, "10 A", "lbl")
    s.w(x, YP + 50, x, 572)
    s.cell_v(x, 572)
    s.txt(x + 18, 600, f"#{n}", "lbbs")
    s.w(x, 606, x, YN)
    s.dot(x, YN)
# łączniki między koszami
s.w(470, YP, 700, YP, "wp")
s.w(470, YN, 700, YN, "wg")
s.txt(585, 490, "łącznik 6 mm² OFC", "lbc")
s.txt(585, 570, "0,4–0,6 m,", "lbc")
s.txt(585, 585, "obie żyły równe", "lbc")
s.txt(585, 660, "łącznik 6 mm² OFC", "lbc")
s.txt(310, 708, "7 × CSB HR1221W F2 · 12 V / 5,1 Ah AGM · równolegle = 35,7 Ah", "lbc")
s.txt(310, 723, "pakiet → blok: 14 × FLRY-B 2,5 mm², 0,25 m ±30 mm", "lbc")

# odbiór „+" z L+ → F7 → LVD
s.w(150, YP, 150, 458, "wp")
s.dot(150, YP)
s.w(150, 458, 160, 458, "wp")
s.fuse_h(160, 458, "wp")
s.txt(196, 484, "F7 · 20 A", "refc")
s.w(210, 458, 1075, 458, "wp")
s.w(1075, 458, 1075, 540, "wp")
s.w(1075, 540, 1100, 540, "wp")
s.txt(560, 453, "odbiór „+” z L+: F7 MIDI/ANL ≤ 30 cm od L+, dalej 6 mm² · ≤ 0,5 m do M3", "lbc")
s.module(1100, 515, 210, 96, "blkb",
         [("M3 · XH-M609 (LVD)", "lbb"), ("odcięcie 11,00 V", "lbc"),
          ("powrót 12,60 V", "lbc"), ("przekaźnik 20 A, tnie „+”", "lbc")])
s.w(1205, 611, 1205, 630, "wg")
s.gnd(1205, 630)
s.txt(1226, 646, "VIN−", "lbl")

# odbiór „−" z P− → S1 → punkt masy
s.w(940, YN, 1000, YN, "wg")
s.dot(940, YN)
s.switch_h(1000, YN, "wg")
s.w(1042, YN, 1070, YN, "wg")
s.gnd(1070, YN)
s.txt(1036, 682, "S1 · rozłącznik", "refc")
s.txt(1036, 697, "masy 100 A", "refc")
s.txt(1060, 714, "punkt masy (gwiazda)", "lbc")

s.note(1340, 420, 236, 210, "Bank na lince",
       ["bloki gwiazdowe L+ L− P+ P−,",
        "kołki M6, pokrywa",
        "FB1…FB7 10 A na „+”,",
        "5–10 cm od zacisku pakietu",
        "odbiór po przekątnej:",
        "„+” z L+, „−” z P− (≈ 4 %)",
        "masa banku 6 mm² z P−",
        "do jednego punktu masy",
        "≈ 16,8 kg z koszami (ZB §4.7)"], step=17)

# VOUT+ → szyna odbiorników
s.w(1310, 540, 1325, 540, "wp")
s.w(1325, 540, 1325, 660, "wp")
s.w(1325, 660, 1560, 660, "wp")
s.w(1560, 660, 1560, 790, "wp")
s.txt(1440, 652, "VOUT+ · 4 mm²", "lbc")

s.sep(740)

# ------------------------------------------------------------------ C
YS = 790
s.txt(24, 765, "C · ODBIORNIKI — szyna +12 V za LVD, zasilana STALE (zapłon niczego nie odcina)", "secb")
s.w(150, YS, 1560, YS, "wp")
s.dot(1560, YS)
s.txt(160, 782, "SZYNA ODBIORNIKÓW +12 V", "lbbs")

# F8 → step-up → M910q
s.dot(220, YS)
s.fuse_v(220, YS, "wp")
s.txt(234, 812, "F8 · 10 A", "ref")
s.txt(234, 827, "6,6 A przy 11 V", "lbl")
s.w(220, 840, 220, 860, "wp")
s.module(130, 860, 200, 82, "blkb",
         [("M4 · STEP-UP 12 → 20 V", "lbb"), ("1200 W / 20 A → 20 V", "lbc"),
          ("limit RAPL niepotrzebny", "lbc")])
s.w(160, 942, 160, 958, "wg")
s.gnd(160, 958)
s.w(330, 900, 350, 900, "wp")
s.fuse_h(350, 900, "wp")
s.txt(375, 884, "5 A", "refc")
s.txt(375, 924, "wyjście", "lbc")
s.w(400, 900, 470, 900, "wp")
s.txt(435, 940, "4 mm²", "lbc")
s.txt(435, 955, "~4 m", "lbc")
s.module(470, 852, 220, 96, "blk",
         [("M910q · 20 V, do 65 W", "lbb"), ("zasilany stale", "lbc"),
          ("USB: panel 7\" (logika + dotyk),", "lbc"),
          ("Pro Micro (SWC), modem LTE,", "lbc"), ("Nano — tylko dane", "lbc")])

# F9 → LM2596 → podświetlenie
s.dot(820, YS)
s.fuse_v(820, YS, "wp")
s.txt(834, 812, "F9 · 2 A", "ref")
s.w(820, 840, 820, 860, "wp")
s.module(740, 860, 180, 64, "blkb",
         [("M5 · LM2596", "lbb"), ("step-down 12 → 5 V", "lbc")])
s.w(770, 924, 770, 940, "wg")
s.gnd(770, 940)
s.w(920, 892, 950, 892, "wp")
s.module(950, 860, 180, 64, "blk",
         [("Panel 7\"", "lbb"), ("podświetlenie", "lbc"), ("PWM + GND", "lbc")])

# F10 → MP1584 → Nano
s.dot(1320, YS)
s.fuse_v(1320, YS, "wp")
s.txt(1334, 812, "F10 · 3 A", "ref")
s.w(1320, 840, 1320, 860, "wp")
s.module(1230, 860, 180, 64, "blkb",
         [("M6 · MP1584", "lbb"), ("step-down 12 → 5 V", "lbc")])
s.w(1260, 924, 1260, 940, "wg")
s.gnd(1260, 940)
s.w(1350, 924, 1350, 1060, "wp")
s.txt(1362, 960, "5 V · przewód 25", "lbl")
s.txt(1362, 975, "Nano żyje w S3", "lbl")

s.sep(995)

# ------------------------------------------------------------------ D
s.txt(24, 1020, "D · SYGNAŁY — zapłon tylko USYPIA i BUDZI M910q przyciskiem zasilania "
      "(schematic_test_signals.svg)", "sec")
# Nano
s.module(1230, 1060, 200, 112, "blkg",
         [("A1 · Arduino Nano", "lbb"), ("sensor_hub.ino", "lbc"),
          ("5 V z MP1584", "lbc"), ("USB do M910q: dane,", "lbc"),
          ("żyła VBUS przecięta", "lbc")])

for yy, name, sub, r, u, pin, extra in (
        (1080, "ZAPŁON / ACC", "12 V po kluczyku", "R1 · 2,2 kΩ", "U1 · PC817", "D9", ""),
        (1160, "ŚWIATŁO COFANIA", "12 V, opcja", "R3 · 2,2 kΩ", "U2 · PC817", "D10",
         "FEATURE_REV — do dopisania")):
    s.term(200, yy)
    s.txt(186, yy + 4, name, "lbbe")
    s.txt(186, yy + 19, sub, "lbe")
    s.w(206, yy, 240, yy)
    s.res_h(240, yy)
    s.txt(265, yy - 14, r, "refc")
    s.w(290, yy, 330, yy)
    # transoptor
    s.box(330, yy - 26, 110, 52, "grp")
    s.a(f'<path class="symf" d="M {352} {yy-9} L {368} {yy-9} L {360} {yy+5} Z"/>')
    s.w(352, yy + 5, 368, yy + 5)
    s.w(330, yy, 345, yy)
    s.w(345, yy, 345, yy - 9)
    s.w(360, yy - 9, 345, yy - 9)
    s.w(360, yy + 5, 360, yy + 14)
    s.w(360, yy + 14, 375, yy + 14)
    s.a(f'<path class="wd" d="M 376 {yy-2} L 392 {yy-2}"/>')
    s.w(400, yy - 14, 400, yy + 14)
    # kolektor u góry (U1) albo u dołu (U2) — tak, żeby szyna masy
    # emiterów nie przecinała przewodu do D10
    yc, ye = (yy - 16, yy + 16) if yy == 1080 else (yy + 16, yy - 16)
    s.w(400, yy - 6, 420, yy - 16)
    s.w(400, yy + 6, 420, yy + 16)
    s.w(420, yy - 16, 440, yy - 16)
    s.w(420, yy + 16, 440, yy + 16)
    # strzałka emitera
    sg = 1 if ye > yy else -1
    s.a(f'<path class="symf" d="M 420 {ye} l -9 {-sg} l 4 {-7 * sg} Z"/>')
    s.txt(480, yy - 30 if yy == 1080 else yy + 40, u, "ref")
    # katoda → masa auta
    s.w(375, yy + 14, 375, yy + 26)
    s.chassis(375, yy + 26)
    # kolektor → Nano
    yp = yy - 6 if yy == 1080 else yy - 10
    s.w(440, yc, 520, yc)
    s.w(520, yc, 520, yp)
    s.w(520, yp, 1230, yp)
    s.txt(1220, yp - 6, pin, "lbbe")
    # emiter → GND Nano
    s.w(440, ye, 460, ye, "wg")
    if extra:
        s.txt(700, yy + 32, extra, "lbc")
# masa auta dla strony LED obu transoptorów
s.txt(375, 1230, "masa auta — NIE z gwiazdą banku", "go")
# emitery → GND Nano
s.w(460, 1096, 460, 1144, "wg")
s.dot(460, 1120)
s.w(460, 1120, 1230, 1120, "wg")
s.txt(1220, 1114, "GND", "lbbe")
s.txt(860, 1114, "GND Nano (C3, C4 100 nF przy D9 / D10)", "lbc")

# A0 → moduł przekaźnika → przycisk zasilania
s.w(1430, 1100, 1460, 1100)
s.txt(1440, 1093, "A0", "lbbs")
s.module(1460, 1070, 120, 60, "blko",
         [("M7 · przekaźnik", "lbb"), ("5 V, 1-kanał.", "lbc")])
s.w(1490, 1130, 1490, 1180)
s.w(1550, 1130, 1550, 1180)
s.w(1490, 1180, 1500, 1180)
s.switch_h(1500, 1180)
s.w(1542, 1180, 1550, 1180)
s.txt(1520, 1210, "przycisk zasilania", "lbc")
s.txt(1520, 1225, "M910q (równolegle)", "lbc")
s.txt(1520, 1158, "COM–NO", "lbc")

s.note(24, 1252, 520, 132, "Impuls na A0 (ZB §2.1, SCHEMATY_POLACZEN §10.5)",
       ["250 ms przy pracy → uśpienie do S3; 250 ms w S3 → wybudzenie (~3 s)",
        "5 s (po 2 h postoju) → twarde wyłączenie",
        "postój w S3: 200–460 mA + I_jał step-upu",
        "po wyłączeniu: 50–150 mA + I_jał (WDROŻENIE_TESTOWE §3.1a)",
        "styki M7 równolegle do przycisku — przycisk działa dalej"])
s.note(560, 1252, 500, 132, "Masa — jeden punkt przy banku (ZB §8.3)",
       ["Symbole masy (trzy kreski) to JEDEN punkt — gwiazda przy P−:",
        "S1, IN−/OUT− ładowarek, DC-IN− XH-M603, VIN− LVD, M4–M6,",
        "K1:85, TVS/C1, powrót 20 V z M910q, wspólny powrót 12 V z przodu.",
        "Z punktu JEDEN przewód 6 mm² do karoserii; z przodu bez mas.",
        "Masa auta (kreskowana): „−” BT0 przez nadwozie, LED transoptorów."])
s.note(1076, 1252, 500, 132, "Czego na tym arkuszu celowo nie ma",
       ["przekaźnika zapłonu przed odbiornikami — K1 jest tylko w ładowaniu",
        "wzmacniacza: osobna gałąź z rozruchowego, własna masa",
        "F11 (AUX 12 V) i F13 (wstrzykiwacz 5 V telefonu, opcja) —",
        "tylko wersja docelowa (ZB §8.1); tu telefon na USB M910q",
        "autokompensacji temp.: CV ręcznie, 14,40 V / lato 13,95 V (ZB §5.5)"])

s.check_overlaps()
s.check_text()
s.save(OUT)
print("ok — " + OUT)
