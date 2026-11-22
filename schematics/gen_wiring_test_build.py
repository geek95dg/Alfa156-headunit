#!/usr/bin/env python3
"""Generator schematu połączeniowego wariantu testowo-rozwojowego.

Rysuje:
    schematics/wiring_test_build.svg — jeden arkusz, zacisk po zacisku:
    tor ładowania (2 × XY-SK120 → 2 × XH-M603 → FC1/FC2 → F12), bank
    7 × HR1221W w dwóch koszach z blokami zbiorczymi, LVD, rozłącznik masy,
    punkt masy, odbiorniki (step-up 20 V, LM2596, MP1584) oraz sygnały
    (dwa PC817, Arduino Nano, moduł przekaźnika na przycisku M910q).

Uruchomienie (z katalogu głównego repo):
    python3 schematics/gen_wiring_test_build.py

Źródło danych: §10 docs/SCHEMATY_POLACZEN.md (numery przewodów, przekroje,
wkładki, kolejność podłączania) oraz docs/ZASILANIE_BUFOROWANE.md (ZB —
nastawy, klasy wkładek, przekroje przewodów masy). Ten sam tor
komponentowo: schematic_test_power.svg i schematic_test_signals.svg
(gen_test_schematics.py). Po zmianie tabel popraw ten plik i wygeneruj SVG
ponownie — nie edytuj SVG ręcznie.

Do wygenerowania wystarcza biblioteka standardowa; wynik jest
deterministyczny. Przed zapisem generator sam sprawdza rysunek: bloki nie
nachodzą na siebie, przewody nie przechodzą przez bloki ani przez napisy,
napisy mieszczą się w ramkach i nie zachodzą na siebie. Do zmierzenia
napisów używa fontu DejaVu Sans przez Pillow, jeśli jest dostępny (bez
niego tę jedną kontrolę pomija z ostrzeżeniem).
"""

import os
import re
import sys

try:
    from PIL import ImageFont
except ImportError:                                           # pragma: no cover
    ImageFont = None

DEJAVU = {
    False: "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    True:  "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
}

OUT = "schematics/wiring_test_build.svg"
W, H = 1800, 1990

STYLE = '''<style>
 .bg{fill:#ffffff}
 .wp{stroke:#c0392b;stroke-width:2.6;fill:none;stroke-linecap:round}
 .wg{stroke:#46586a;stroke-width:2.2;fill:none;stroke-linecap:round}
 .ws{stroke:#2b4a8a;stroke-width:1.8;fill:none;stroke-linecap:round}
 .wo{stroke:#9a6b12;stroke-width:2.2;fill:none;stroke-linecap:round}
 .wd{stroke:#7a8b99;stroke-width:1.6;fill:none;stroke-dasharray:5 4}
 .sym{stroke:#1b2b36;stroke-width:2;fill:none}
 .blk{fill:#f7f9fb;stroke:#2b3a45;stroke-width:2;rx:5}
 .blkg{fill:#eef7ee;stroke:#2d6a2d;stroke-width:2;rx:5}
 .blko{fill:#fdf3e6;stroke:#9a6b12;stroke-width:2;rx:5}
 .blkb{fill:#eef2fa;stroke:#2b4a8a;stroke-width:2;rx:5}
 .blkp{fill:#fbf3fb;stroke:#7a3d8f;stroke-width:2;rx:5;stroke-dasharray:7 4}
 .bus{fill:#f3e0c8;stroke:#9a6b12;stroke-width:1.6;rx:3}
 .busg{fill:#dde3e8;stroke:#46586a;stroke-width:1.6;rx:3}
 .kosz{fill:none;stroke:#7a3d8f;stroke-width:1.6;stroke-dasharray:6 4;rx:6}
 .res{fill:#ffffff;stroke:#1b2b36;stroke-width:2;rx:3}
 .fbox{fill:#ffffff;stroke:#a8321a;stroke-width:2;rx:3}
 .note{fill:#fbfcfd;stroke:#c8d2da;stroke-width:1.5;rx:5}
 .pp{fill:#c0392b;rx:9}
 .pg{fill:#46586a;rx:9}
 .ps{fill:#2b4a8a;rx:9}
 .ttl{font-size:21px;font-weight:bold;fill:#10202b}
 .sub{font-size:12px;fill:#5a6b78}
 .sec{font-size:13px;font-weight:bold;fill:#2d6a2d;letter-spacing:0.5px}
 .secb{font-size:13px;font-weight:bold;fill:#2b4a8a;letter-spacing:0.5px}
 .ref{font-size:11.5px;font-weight:bold;fill:#a8321a;text-anchor:middle}
 .mh{font-size:12.5px;font-weight:bold;fill:#10202b;text-anchor:middle}
 .ms{font-size:10.5px;fill:#5a6b78;text-anchor:middle}
 .tm{font-size:10.5px;font-weight:bold;fill:#10202b}
 .tme{font-size:10.5px;font-weight:bold;fill:#10202b;text-anchor:end}
 .tmc{font-size:10.5px;font-weight:bold;fill:#10202b;text-anchor:middle}
 .fz{font-size:10.5px;font-weight:bold;fill:#a8321a;text-anchor:middle}
 .wn{font-size:10.5px;font-weight:bold;fill:#ffffff;text-anchor:middle}
 .xs{font-size:10.5px;fill:#33424e}
 .xsc{font-size:10.5px;fill:#33424e;text-anchor:middle}
 .xse{font-size:10.5px;fill:#33424e;text-anchor:end}
 .go{font-size:10.5px;font-weight:bold;fill:#9a6b12;text-anchor:middle}
 .src{font-size:11px;font-weight:bold;fill:#10202b;text-anchor:end}
 .nh{font-size:12.5px;font-weight:bold;fill:#10202b}
 .nt{font-size:11px;fill:#4a5a66}
 .ntb{font-size:11px;font-weight:bold;fill:#10202b}
</style>'''


def _class_metrics(css):
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

#: Ramki, w których napis startujący w środku MUSI się zmieścić i przez
#: które nie wolno przeprowadzić przewodu.
FRAMES = ("blk", "blkg", "blko", "blkb", "blkp", "note", "fbox", "res", "bus",
          "busg", "pp", "pg", "ps")
#: Ramki, na których przewody się kończą, ale przez które nie przechodzą.
SOLID = FRAMES
#: Pastylki numerów przewodów leżą NA przewodzie celowo.
PILLS = ("pp", "pg", "ps")
WIRES = ("wp", "wg", "ws", "wo", "wd")


def _approx_w(s, size, bold):
    """Szerokość napisu bez Pillow — tylko do szerokości pastylek, żeby
    wynik był deterministyczny niezależnie od zainstalowanych pakietów.
    Kontrola z Pillow sprawdza potem, czy ten zapas wystarcza."""
    return len(s) * size * (0.66 if bold else 0.58)


class Sheet:
    def __init__(self, w, h, title):
        self.W, self.H = w, h
        self.o = []
        self.rects = []      # (x, y, w, h, cls)
        self.texts = []      # (x, y, s, cls)
        self.segs = []       # (x1, y1, x2, y2, cls)
        self.outlines = []   # (x, y, w, h) — kreskowane obrysy koszy
        self.a(f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
               f'viewBox="0 0 {w} {h}" font-family="DejaVu Sans, Verdana, sans-serif">')
        self.a(f'<title>{title}</title>')
        self.a(STYLE)
        self.a(f'<rect class="bg" x="0" y="0" width="{w}" height="{h}"/>')

    def a(self, s):
        self.o.append(s)

    def save(self, path):
        self.a("</svg>")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(self.o) + "\n")

    # ---- prymitywy
    def txt(self, x, y, s, c="xs"):
        self.texts.append((x, y, s, c))
        e = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        self.a(f'<text class="{c}" x="{x}" y="{y}">{e}</text>')

    def rect(self, x, y, w, h, c, check=True):
        if check:
            self.rects.append((x, y, w, h, c))
        elif c == "kosz":
            self.outlines.append((x, y, w, h))
        self.a(f'<rect class="{c}" x="{x}" y="{y}" width="{w}" height="{h}"/>')

    def wire(self, pts, c="wp"):
        for i in range(len(pts) - 1):
            (x1, y1), (x2, y2) = pts[i], pts[i + 1]
            self.segs.append((x1, y1, x2, y2, c))
        d = " ".join(f"{'M' if i == 0 else 'L'} {x} {y}" for i, (x, y) in enumerate(pts))
        self.a(f'<path class="{c}" d="{d}"/>')

    def dot(self, x, y, fill="#1b2b36"):
        self.a(f'<circle cx="{x}" cy="{y}" r="3.6" fill="{fill}"/>')

    def pill(self, x, y, s, kind="p"):
        """Pastylka z numerem przewodu, wycentrowana na (x, y) — na przewodzie."""
        w = max(22, round(_approx_w(s, 10.5, True) + 12))
        self.rect(x - w / 2, y - 9, w, 18, "p" + kind)
        self.txt(x, y + 4, s, "wn")
        return w

    def fuse(self, cx, cy, s, w=None):
        """Oprawka bezpiecznika w linii przewodu; zwraca (lewo, prawo, góra, dół)."""
        if w is None:
            w = max(60, round(_approx_w(s, 10.5, True) + 16))
        self.rect(cx - w / 2, cy - 11, w, 22, "fbox")
        self.txt(cx, cy + 4, s, "fz")
        return cx - w / 2, cx + w / 2, cy - 11, cy + 11

    def gnd_tag(self, x, y, s):
        """Pastylka „do punktu masy” — koniec przewodu masy przy module."""
        w = round(_approx_w(s, 10.5, True) + 14)
        self.rect(x - w / 2, y, w, 18, "pg")
        self.txt(x, y + 13, s, "wn")

    def chassis(self, x, y, label=None, label_dy=40):
        self.segs.append((x, y, x, y + 10, "wo"))
        self.a(f'<line class="wo" x1="{x}" y1="{y}" x2="{x}" y2="{y+10}"/>')
        self.a(f'<line class="wo" x1="{x-15}" y1="{y+10}" x2="{x+15}" y2="{y+10}"/>')
        for dx in (-11, -3, 5, 13):
            self.a(f'<line class="wo" x1="{x+dx}" y1="{y+10}" x2="{x+dx-7}" y2="{y+22}"/>')
        if label:
            self.txt(x, y + label_dy, label, "go")

    def module(self, x, y, w, h, cls, lines, terms, ly0=19):
        """Blok modułu: linie opisu od góry i zaciski na krawędziach.

        terms: (klucz, strona L/R/T/B, pozycja, etykieta). Kropka zacisku
        leży na krawędzi; przewód kończy się dokładnie na niej.
        """
        self.rect(x, y, w, h, cls)
        cy = y + ly0
        for s, c in lines:
            self.txt(x + w / 2, cy, s, c)
            cy += 16 if c in ("ms", "xsc") else 17
        p = {}
        for key, side, pos, lab in terms:
            if side == "L":
                pt = (x, pos)
                self.txt(x + 7, pos + 4, lab, "tm")
            elif side == "R":
                pt = (x + w, pos)
                self.txt(x + w - 7, pos + 4, lab, "tme")
            elif side == "T":
                pt = (pos, y)
                self.txt(pos, y + 16, lab, "tmc")
            else:
                pt = (pos, y + h)
                self.txt(pos, y + h - 8, lab, "tmc")
            p[key] = pt
        for pt in p.values():
            self.dot(pt[0], pt[1], "#10202b")
        return p

    def sect(self, x, y, s, c="sec"):
        self.txt(x, y, s, c)

    def note(self, x, y, w, h, head, lines, step=17):
        self.rect(x, y, w, h, "note")
        self.txt(x + 16, y + 24, head, "nh")
        for i, ln in enumerate(lines):
            if isinstance(ln, tuple):
                s, c = ln
            else:
                s, c = ln, "nt"
            self.txt(x + 16, y + 46 + i * step, s, c)

    # ---- kontrola rysunku
    def _text_box(self, x, y, s, cls):
        size, bold, anchor = METRICS[cls]
        w = _measure(s, size, bold)
        x0 = x - w / 2 if anchor == "middle" else (x - w if anchor == "end" else x)
        return (x0, y - size * 0.78, x0 + w, y + size * 0.24)

    def check_overlaps(self):
        bad = []
        rs = [r for r in self.rects if r[4] != "kosz"]
        for i, (x1, y1, w1, h1, c1) in enumerate(rs):
            for x2, y2, w2, h2, c2 in rs[i + 1:]:
                if x1 < x2 + w2 and x2 < x1 + w1 and y1 < y2 + h2 and y2 < y1 + h1:
                    bad.append(f"{c1}@({x1},{y1}) x {c2}@({x2},{y2})")
        if bad:
            raise SystemExit("bloki nachodzą na siebie: " + "; ".join(bad))

    def check_wires(self):
        """Przewód nie może przechodzić przez blok ani przez obcą pastylkę."""
        bad = []
        for x1, y1, x2, y2, c in self.segs:
            if x1 != x2 and y1 != y2:
                bad.append(f"przewód ukośny ({x1},{y1})-({x2},{y2})")
                continue
            lo_x, hi_x = min(x1, x2), max(x1, x2)
            lo_y, hi_y = min(y1, y2), max(y1, y2)
            for rx, ry, rw, rh, rc in self.rects:
                if rc not in SOLID:
                    continue
                if rc in PILLS:
                    # pastylka może leżeć na przewodzie, który przez nią
                    # przechodzi wzdłuż swojej osi — ale nie w poprzek
                    cx, cy = rx + rw / 2, ry + rh / 2
                    along = (y1 == y2 == cy) or (x1 == x2 == cx)
                    if along:
                        continue
                # wnętrze ramki pomniejszone o 1 px: przewód może dojść do krawędzi
                ix0, iy0, ix1, iy1 = rx + 1, ry + 1, rx + rw - 1, ry + rh - 1
                if lo_x < ix1 and hi_x > ix0 and lo_y < iy1 and hi_y > iy0:
                    if rc == "fbox":
                        # przewód może dojść do oprawki, nie przez nią
                        pass
                    bad.append(f"przewód ({x1},{y1})-({x2},{y2}) [{c}] przez {rc}@({rx},{ry})")
        if bad:
            raise SystemExit("przewody do poprawki:\n  " + "\n  ".join(bad))

    def check_text(self):
        if ImageFont is None or not os.path.exists(DEJAVU[False]):
            print("uwaga: brak Pillow albo fontu DejaVu — pomijam kontrolę napisów",
                  file=sys.stderr)
            return
        frames = [r for r in self.rects if r[4] in FRAMES]
        bad, boxes = [], []
        for x, y, s, cls in self.texts:
            if cls not in METRICS:
                bad.append(f"nieznana klasa {cls!r}: {s!r}")
                continue
            if METRICS[cls][0] < 9:
                bad.append(f"napis mniejszy niż 9 px: {s!r}")
            bx = self._text_box(x, y, s, cls)
            boxes.append((bx, s, cls))
            if bx[0] < 4 or bx[2] > self.W - 4 or bx[1] < 0 or bx[3] > self.H:
                bad.append(f"poza arkuszem: {s!r}")
                continue
            for fx, fy, fw, fh, fcls in frames:
                inside = (fx <= bx[0] <= fx + fw and fy <= bx[1] <= fy + fh)
                if inside:
                    if bx[2] > fx + fw - 2 or bx[3] > fy + fh or bx[0] < fx + 2:
                        bad.append(f"wychodzi z ramki {fcls}@({fx},{fy}): {s!r}")
                    continue
                if (bx[0] < fx + fw - 1 and fx < bx[2] - 1 and
                        bx[1] < fy + fh - 1 and fy < bx[3] - 1):
                    bad.append(f"napis wchodzi w ramkę {fcls}@({fx},{fy}): {s!r}")
            # napis nie może dotykać kreskowanego obrysu kosza (min. 3 px)
            for ox, oy, ow, oh in self.outlines:
                for ex0, ey0, ex1, ey1 in ((ox, oy, ox, oy + oh), (ox + ow, oy, ox + ow, oy + oh),
                                           (ox, oy, ox + ow, oy), (ox, oy + oh, ox + ow, oy + oh)):
                    if (ex0 - 3 < bx[2] and ex1 + 3 > bx[0] and
                            ey0 - 3 < bx[3] and ey1 + 3 > bx[1]):
                        bad.append(f"napis dotyka obrysu kosza ({ox},{oy}): {s!r}")
            if cls == "wn":
                continue
            # napis nie może leżeć na przewodzie
            for x1, y1, x2, y2, c in self.segs:
                lo_x, hi_x = min(x1, x2) - 1, max(x1, x2) + 1
                lo_y, hi_y = min(y1, y2) - 1, max(y1, y2) + 1
                if lo_x < bx[2] and hi_x > bx[0] and lo_y < bx[3] and hi_y > bx[1]:
                    bad.append(f"przewód ({x1},{y1})-({x2},{y2}) przez napis {s!r}")
        for i, (a, sa, ca) in enumerate(boxes):
            for b, sb, cb in boxes[i + 1:]:
                if (a[0] < b[2] - 1 and b[0] < a[2] - 1 and
                        a[1] < b[3] - 1 and b[1] < a[3] - 1):
                    bad.append(f"napisy zachodzą: {sa!r} x {sb!r}")
        if bad:
            raise SystemExit("napisy do poprawki:\n  " + "\n  ".join(bad))


_FONTS = {}


def _measure(s, size, bold):
    key = (round(size * 2) / 2, bold)
    if key not in _FONTS:
        _FONTS[key] = ImageFont.truetype(DEJAVU[bold], key[0])
    return _FONTS[key].getlength(s)


# =====================================================================
s = Sheet(W, H, "BCM v8.5 — schemat połączeniowy wariantu testowo-rozwojowego, "
                "zacisk po zacisku (M910q)")
s.txt(24, 34, "Schemat połączeniowy — wariant testowo-rozwojowy (M910q zasilany stale z banku)", "ttl")
s.txt(24, 56, "Każdy zacisk podpisany, każdy przewód ponumerowany jak w tabelach "
              "docs/SCHEMATY_POLACZEN.md §10. Ten sam tor komponentowo: "
              "schematic_test_power.svg i schematic_test_signals.svg. "
              "Nastawy i uzasadnienia: docs/ZASILANIE_BUFOROWANE.md (ZB).", "sub")
s.a('<line x1="24" y1="68" x2="1776" y2="68" stroke="#c8d2da" stroke-width="1.5"/>')

# legenda
LY = 90
s.wire([(24, LY), (64, LY)], "wp")
s.txt(72, LY + 4, "„+” zasilania", "xs")
s.wire([(180, LY), (220, LY)], "wg")
s.txt(228, LY + 4, "masa", "xs")
s.wire([(276, LY), (316, LY)], "ws")
s.txt(324, LY + 4, "sygnał", "xs")
s.wire([(384, LY), (424, LY)], "wo")
s.txt(432, LY + 4, "masa instalacji auta", "xs")
s.pill(578, LY, "5a", "p")
s.txt(596, LY + 4, "numer przewodu z §10", "xs")
s.gnd_tag(784, LY - 9, "PM · 2,5 mm²")
s.txt(836, LY + 4, "przewód do punktu masy przy banku (§10.6), z przekrojem", "xs")
s.dot(1222, LY)
s.txt(1232, LY + 4, "zacisk / połączenie · skrzyżowanie bez kropki = brak połączenia", "xs")

# =====================================================================
# 1 · TOR ŁADOWANIA
s.sect(24, 128, "1 · TOR ŁADOWANIA — komora silnika → bagażnik (§10.1)")

Y1 = 232           # główna linia „+” toru ładowania
Y1m = 254          # rząd zacisków masy
bt = s.module(24, 152, 170, 116, "blk",
              [("Akumulator", "mh"), ("rozruchowy", "mh"), ("12 V · komora silnika", "ms")],
              [("p", "R", Y1, "+"), ("m", "R", Y1m, "−")])
s.wire([bt["m"], (214, Y1m), (214, 268)], "wo")
s.chassis(214, 268, "nadwozie", label_dy=40)

f1 = s.fuse(300, Y1, "F1 · 20 A")
s.wire([bt["p"], (f1[0], Y1)])
s.pill(235, Y1, "1")
s.txt(235, Y1 - 16, "6 mm²", "xsc")
s.txt(300, Y1 + 28, "MIDI/AMI lub ANL", "xsc")
s.txt(300, Y1 + 42, "≤ 30 cm od klemy „+”", "xsc")

tv = s.module(540, 152, 180, 116, "blk",
              [("D5 + C1", "mh"), ("TVS SMCJ20CA", "ms"), ("470 µF / 35 V low-ESR", "ms")],
              [("i", "L", Y1, "+"), ("o", "R", Y1, "+"), ("m", "B", 630, "−")])
s.wire([(f1[1], Y1), tv["i"]])
s.pill(392, Y1, "2")
s.txt(392, Y1 - 16, "6 mm² · ~5 m", "xsc")
s.txt(470, Y1 + 20, "do bagażnika", "xsc")
s.wire([tv["m"], (630, 284)], "wg")
s.gnd_tag(630, 284, "PM · 2,5 mm²")

k1 = s.module(800, 152, 170, 116, "blk",
              [("K1 · przekaźnik 30 A", "mh"), ("SPDT + podstawka", "ms"),
               ("87: dwa oczka (5 i 5a)", "ms")],
              [("30", "L", Y1, "30"), ("87", "R", Y1, ""), ("87a", "R", Y1 + 18, ""),
               ("85", "B", 840, "85"), ("86", "B", 930, "86")])
# zacisk 87 z dwoma oczkami: dwie kropki spięte listwą, przewody 5 i 5a
# zaczynają się każdy na swoim oczku — bez złączki poza przekaźnikiem
s.a(f'<line x1="967" y1="{Y1}" x2="967" y2="{Y1 + 18}" stroke="#10202b" stroke-width="4"/>')
s.txt(959, Y1 + 13, "87", "tme")
s.wire([tv["o"], k1["30"]])
s.pill(760, Y1, "3")
s.txt(760, Y1 - 16, "6 mm²", "xsc")
s.wire([k1["85"], (840, 284)], "wg")
s.gnd_tag(840, 284, "PM · 0,75 mm²")

# przewód 4 — cewka K1 z zapłonu / D+
Y4 = 340
s.wire([k1["86"], (930, Y4), (470, Y4)], "wp")
fk = s.fuse(430, Y4, "FK · 1 A", w=80)
s.wire([(fk[0], Y4), (330, Y4)], "wp")
s.a(f'<circle cx="322" cy="{Y4}" r="7" fill="#ffffff" stroke="#10202b" stroke-width="2.2"/>')
s.txt(306, Y4 - 3, "ZAPŁON / D+", "src")
s.txt(306, Y4 + 12, "z przodu, 12 V przy pracy", "xse")
s.pill(620, Y4, "4")
s.txt(620, Y4 + 24, "0,75 mm² · ~4–5 m", "xsc")
s.txt(430, Y4 + 28, "przy wpięciu w zapłon", "xsc")
s.txt(830, Y4 + 24, "D6 1N4007 na 85–86, pasek → 86", "xsc")

# dwie gałęzie ładowarek
XA, XB = 1060, 1320
Y2, Y2m = 410, 432
m1a = s.module(XA, 152, 190, 116, "blkg",
               [("M1a · XY-SK120 #1", "mh"), ("CV 14,40 V · CC 5,0 A", "ms")],
               [("in", "L", Y1, "IN+"), ("inm", "B", 1090, "IN−"),
                ("out", "R", Y1, "OUT+"), ("outm", "R", Y1m, "OUT−")])
m1b = s.module(XA, 330, 190, 116, "blkg",
               [("M1b · XY-SK120 #2", "mh"), ("CV 14,40 V · CC 5,0 A", "ms")],
               [("in", "L", Y2, "IN+"), ("inm", "B", 1090, "IN−"),
                ("out", "R", Y2, "OUT+"), ("outm", "R", Y2m, "OUT−")])
s.wire([k1["87"], m1a["in"]])
s.pill(1030, Y1, "5")
s.txt(1030, Y1 - 16, "2,5 mm²", "xsc")
s.wire([k1["87a"], (995, Y1 + 18), (995, Y2), m1b["in"]])
s.pill(1030, Y2, "5a")
s.txt(1030, Y2 - 16, "2,5 mm²", "xsc")
for m in (m1a, m1b):
    x, y = m["inm"]
    s.wire([(x, y), (x, y + 12)], "wg")
    s.gnd_tag(x, y + 12, "PM · 2,5 mm²")

m2a = s.module(XB, 152, 170, 116, "blko",
               [("M2a · XH-M603 #1", "mh"), ("15,30 / 14,00 V", "ms")],
               [("in", "L", Y1, "DC-IN+"), ("inm", "L", Y1m, "DC-IN−"),
                ("out", "R", Y1, "OUT+")])
m2b = s.module(XB, 330, 170, 116, "blko",
               [("M2b · XH-M603 #2", "mh"), ("15,30 / 14,00 V", "ms")],
               [("in", "L", Y2, "DC-IN+"), ("inm", "L", Y2m, "DC-IN−"),
                ("out", "R", Y2, "OUT+")])
JX = 1700
for ma, mb, n, nn, fc, yy, gy in ((m1a, m2a, "6", "7", "FC1 · 7,5 A", Y1, Y1m),
                                  (m1b, m2b, "6a", "7a", "FC2 · 7,5 A", Y2, Y2m)):
    s.wire([ma["out"], mb["in"]])
    s.pill(1285, yy, n)
    s.txt(1285, yy - 16, "2,5 mm²", "xsc")
    s.wire([ma["outm"], mb["inm"]], "wg")
    s.dot(1285, gy)
    s.wire([(1285, gy), (1285, gy + 26)], "wg")
    s.gnd_tag(1285, gy + 26, "PM · 2,5 mm²")
    f = s.fuse(1560, yy, fc, w=92)
    s.wire([mb["out"], (f[0], yy)])
    s.wire([(f[1], yy), (JX, yy)])
    s.pill(1650, yy, nn)
    s.txt(1650, yy - 16, "2,5 mm²", "xsc")
    s.txt(1560, yy + 28, "tuż przy OUT+", "xsc")
s.wire([(JX, Y1), (JX, Y2)])
s.dot(JX, Y2)
s.txt(1712, 300, "złączenie", "xs")
s.txt(1712, 314, "gałęzi —", "xs")
s.txt(1712, 328, "obie równe", "xs")

# przewód B — złączenie → F12 → blok L+
YB = 500
LPX = 770          # gdzie B wchodzi na blok L+
s.wire([(JX, Y2), (JX, YB), (LPX, YB), (LPX, 514)])
f12 = s.fuse(LPX, 525, "F12 · 15 A", w=88)
s.pill(1500, YB, "B")
s.txt(1500, YB - 14, "4 mm² · ≤ 1 m", "xsc")
s.txt(LPX - 52, 530, "MIDI/ANL, przy L+", "xse")

# =====================================================================
# 2 · BANK
s.sect(24, 496, "2 · BANK 7 × CSB HR1221W W DWÓCH KOSZACH · LVD · ROZŁĄCZNIK MASY (§10.2)")

KL_X, KP_X = 300, 920
KY0, KY1 = 538, 800
BUS_P, BUS_M = 548, 764
PK_Y = 630

s.rect(KL_X, KY0, 560, KY1 - KY0, "kosz", check=False)
s.rect(KP_X, KY0, 420, KY1 - KY0, "kosz", check=False)
s.wire([(LPX, f12[3]), (LPX, BUS_P)])
s.rect(KL_X + 14, BUS_P, 532, 22, "bus")
s.txt(KL_X + 24, BUS_P + 15, "blok L+ (kołki M6, pokrywa)", "tm")
s.rect(KL_X + 14, BUS_M, 532, 22, "bus")
s.txt(KL_X + 24, BUS_M + 15, "blok L−", "tm")
s.rect(KP_X + 14, BUS_P, 392, 22, "bus")
s.txt(KP_X + 24, BUS_P + 15, "blok P+", "tm")
s.rect(KP_X + 14, BUS_M, 392, 22, "bus")
s.txt(KP_X + 24, BUS_M + 15, "blok P− (nie jest punktem masy)", "tm")

packs = [(KL_X + 40 + i * 128, i + 1) for i in range(4)] + \
        [(KP_X + 40 + i * 128, i + 5) for i in range(3)]
for px, n in packs:
    pk = s.module(px, PK_Y, 100, 84, "blk",
                  [(f"#{n} HR1221W", "mh"), ("12 V · 5,1 Ah", "ms")],
                  [("p", "T", px + 26, "+"), ("m", "B", px + 74, "−")], ly0=40)
    fb = s.fuse(px + 26, 600, f"FB{n} · 10 A", w=78)
    s.wire([(px + 26, BUS_P + 22), (px + 26, fb[2])])
    s.wire([(px + 26, fb[3]), pk["p"]])
    s.wire([pk["m"], (px + 74, BUS_M)], "wg")
# łączniki między koszami
s.wire([(KL_X + 546, BUS_P + 11), (KP_X + 14, BUS_P + 11)])
s.txt(890, BUS_P + 30, "6 mm²", "xsc")
s.wire([(KL_X + 546, BUS_M + 11), (KP_X + 14, BUS_M + 11)], "wg")
s.txt(890, BUS_M - 4, "6 mm²", "xsc")
s.txt(KL_X + 280, 820, "KOSZ L — pakiety #1…#4", "mh")
s.txt(KP_X + 215, 820, "KOSZ P — pakiety #5…#7", "mh")
s.txt(815, 842, "pakiet → blok: 14 odcinków FLRY-B 2,5 mm² równej długości (0,25 m ±30 mm), nasuwki F2 6,3 mm w pełni "
                "izolowane · FB1…FB7 10 A 5–10 cm od „+” · łączniki L+↔P+ i L−↔P−: 6 mm² OFC, 0,4–0,6 m, "
                "obie żyły równe", "xsc")

# LVD + przewód 8
lvd = s.module(24, 538, 180, 170, "blko",
               [("M3 · XH-M609", "mh"), ("LVD · przełącza „+”", "ms"),
                ("odcięcie 11,00 V", "ms"), ("powrót 12,60 V", "ms")],
               [("vin", "R", BUS_P + 11, "VIN+"), ("vinm", "R", 640, "VIN−"),
                ("vout", "B", 60, "VOUT+"), ("voutm", "B", 140, "VOUT−")], ly0=40)
f7 = s.fuse(238, BUS_P + 11, "F7 · 20 A", w=60)
s.wire([lvd["vin"], (f7[0], BUS_P + 11)])
s.wire([(f7[1], BUS_P + 11), (KL_X + 14, BUS_P + 11)])
s.pill(283, BUS_P + 11, "8")
s.txt(238, BUS_P - 14, "6 mm²", "xsc")
s.txt(238, BUS_P + 39, "MIDI/ANL", "xsc")
s.wire([lvd["vinm"], (240, 640), (240, 728)], "wg")
s.gnd_tag(240, 728, "PM · 0,75 mm²")
s.txt(140, 724, "wolny", "xsc")

# S1 i punkt masy
s1 = s.module(1390, 742, 150, 66, "blk",
              [("S1 · rozłącznik", "mh"), ("masy 100 A", "ms")],
              [("a", "L", 790, "1"), ("b", "R", 790, "2")])
s.wire([(KP_X + 406, BUS_M + 11), (1355, BUS_M + 11), (1355, 790), s1["a"]], "wg")
s.pill(1373, 790, "9", "g")
s.txt(1373, 816, "6 mm²", "xsc")
pm = s.module(1590, 520, 186, 300, "blk",
              [("PM · PUNKT MASY", "mh"), ("osobny blok masowy", "ms"),
               ("przy banku (§10.6)", "ms")],
              [("s1", "L", 790, "← 9 (S1)"), ("ch", "B", 1683, "")])
for i, ln in enumerate(["TVS / C1 „−”", "K1 zacisk 85", "IN−/OUT− XY-SK120 ×2",
                        "DC-IN− XH-M603 ×2", "XH-M609 VIN−", "step-up IN−",
                        "powrót z przodu:", "LM2596 + MP1584 IN−", "bank: P− przez S1"]):
    # wiersz 7 to ciąg dalszy punktu „powrót z przodu:” — wcięty pod tekst
    s.txt(1604 + (_measure("• ", 11, False) if i == 7 else 0), 594 + i * 17,
          ("• " if i != 7 else "") + ln, "nt")
s.wire([s1["b"], pm["s1"]], "wg")
s.pill(1565, 790, "9", "g")
s.wire([pm["ch"], (1683, 840)], "wo")
s.chassis(1683, 840)
s.txt(1663, 854, "6 mm² →", "xse")
s.txt(1683, 882, "nadwozie (bagażnik)", "go")

# =====================================================================
# 3 · ODBIORNIKI
s.sect(84, 900, "3 · ODBIORNIKI — zasilane stale, za LVD; wkładki w bagażniku (§10.3)", "secb")
YBUS = 950
s.wire([lvd["vout"], (60, YBUS)])
s.pill(60, 818, "10")
s.txt(76, 822, "4 mm²", "xs")
s.wire([(60, YBUS), (1440, YBUS)])
s.dot(60, YBUS)
s.txt(470, YBUS - 8, "szyna odbiorników 12 V — dystrybucja w bagażniku, za LVD", "xsc")

YM, YMa, YMb = 1030, 1110, 1140


def branch(x, fz, num, xsec, mod_left_x, last=False):
    if not last:
        s.dot(x, YBUS)
    f = s.fuse(x, 982, fz, w=72)
    s.wire([(x, YBUS), (x, f[2])])
    s.wire([(x, f[3]), (x, YMa), (mod_left_x, YMa)])
    s.pill(x, 1030, num)
    s.txt(x - 16, 1060, xsec, "xse")


# step-up → wtyk M910q
su = s.module(150, YM, 190, 130, "blkb",
              [("M4 · step-up 12 → 20 V", "mh"), ("zalewany, 10 A / 200 W", "ms"),
               ("bagażnik", "ms")],
              [("in", "L", YMa, "IN+"), ("inm", "L", YMb, "IN−"),
               ("out", "R", YMa, "OUT+"), ("outm", "R", YMb, "OUT−")])
branch(90, "F8 · 10 A", "11", "4 mm²", su["in"][0])
s.wire([su["inm"], (115, YMb), (115, 1185)], "wg")
s.gnd_tag(115, 1185, "PM · 4 mm²")
f5 = s.fuse(400, YMa, "5 A", w=60)
s.wire([su["out"], (f5[0], YMa)])
s.wire([(f5[1], YMa), (600, YMa)])
s.wire([su["outm"], (600, YMb)], "wg")
s.txt(400, YMa - 18, "przy wyjściu", "xsc")
s.pill(500, YMa, "12")
s.pill(500, YMb, "12", "g")
s.txt(500, YMb + 26, "4 mm² · ~4 m", "xsc")
s.txt(500, YMb + 40, "„+” i „−”", "xsc")
s.module(600, YM, 200, 130, "blkb",
         [("WTYK M910q", "mh"), ("20 V · do 3,25 A (65 W)", "ms"), ("zasilany STALE", "ms")],
         [("p", "L", YMa, "środek „+”"), ("m", "L", YMb, "ekran „−”")])

# LM2596 → podświetlenie panelu
lm = s.module(940, YM, 170, 130, "blkb",
              [("M5 · LM2596", "mh"), ("12 → 5 V · przód", "ms"), ("nastaw wg panelu", "ms")],
              [("in", "L", YMa, "IN+"), ("inm", "L", YMb, "IN−"),
               ("out", "R", YMa, "OUT+"), ("outm", "R", YMb, "OUT−")])
branch(880, "F9 · 2 A", "13", "1,5 mm²", lm["in"][0])
s.wire([lm["inm"], (905, YMb), (905, 1185)], "wg")
s.gnd_tag(905, 1185, "PM · powrót 2,5 mm²")
pn = s.module(1200, YM, 170, 130, "blkb",
              [("Panel 7\"", "mh"), ("podświetlenie", "ms"), ("logika + dotyk: USB", "ms")],
              [("p", "L", YMa, "PWM+"), ("m", "L", YMb, "GND")])
s.wire([lm["out"], pn["p"]])
s.wire([lm["outm"], pn["m"]], "wg")
s.pill(1155, YMa, "14")
s.pill(1155, YMb, "14", "g")
s.txt(1155, YMb + 26, "1,5 mm²", "xsc")

# MP1584 → Nano (przewód 25 w sekcji 4)
mp = s.module(1500, YM, 170, 130, "blkb",
              [("M6 · MP1584", "mh"), ("12 → 5,0 V · przód", "ms"), ("logika: Nano", "ms")],
              [("in", "L", YMa, "IN+"), ("inm", "L", YMb, "IN−"),
               ("out", "R", YMa, "OUT+"), ("outm", "R", YMb, "OUT−")])
branch(1440, "F10 · 3 A", "13a", "0,75 mm²", mp["in"][0], last=True)
s.wire([mp["inm"], (1465, YMb), (1465, 1185)], "wg")
s.gnd_tag(1465, 1185, "PM · powrót 2,5 mm²")
s.txt(1040, 1226, "IN− obu bucków z przodu: jeden wspólny powrót 2,5 mm² do PM (ZB §8.2) · "
                  "przewody 13 i 13a idą ~4 m do przodu", "xsc")
# =====================================================================
# 4 · SYGNAŁY
s.sect(24, 1262, "4 · SYGNAŁY — zapłon, bieg wsteczny, przycisk M910q (§10.4, §10.5) · "
                 "wszystkie 0,5 mm², przewód 25: 0,75 mm²", "secb")

YU1a, YU1b = 1320, 1360          # U1: pin 1/4 i 2/3
YU2a, YU2b = 1450, 1490          # U2 lustrzanie: pin 2/3 i 1/4
YG = 1405                         # Nano GND (strona D)

u1 = s.module(380, 1290, 150, 100, "blkp",
              [("U1 · PC817", "ref"), ("zapłon", "ms")],
              [("1", "L", YU1a, "1"), ("2", "L", YU1b, "2"),
               ("4", "R", YU1a, "4"), ("3", "R", YU1b, "3")])
u2 = s.module(380, 1420, 150, 100, "blkp",
              [("U2 · PC817", "ref"), ("bieg wsteczny", "ms")],
              [("2", "L", YU2a, "2"), ("1", "L", YU2b, "1"),
               ("3", "R", YU2a, "3"), ("4", "R", YU2b, "4")])
for y, name, sub, rr, num, pin in ((YU1a, "ZAPŁON / ACC", "12 V po kluczyku", "R1 2,2 kΩ", "15", u1["1"]),
                                   (YU2b, "ŚWIATŁO COFANIA", "12 V z czujnika skrzyni", "R3 2,2 kΩ", "15a", u2["1"])):
    s.a(f'<circle cx="150" cy="{y}" r="7" fill="#ffffff" stroke="#10202b" stroke-width="2.2"/>')
    s.txt(134, y - 2, name, "src")
    s.txt(134, y + 13, sub, "xse")
    r = (173, 257)
    s.rect(r[0], y - 11, r[1] - r[0], 22, "res")
    s.txt(215, y + 4, rr, "tmc")
    s.wire([(157, y), (r[0], y)], "ws")
    s.wire([(r[1], y), pin], "ws")
    s.pill(300, y, num, "s")
s.txt(215, YU1a + 26, "0,25 W", "xsc")
s.txt(215, YU2b + 26, "0,25 W", "xsc")
# masa auta: 16 i 16a
GX = 345
s.wire([u1["2"], (GX, YU1b), (GX, YU2a), u2["2"]], "wo")
s.dot(GX, YG)
s.wire([(GX, YG), (300, YG)], "wo")
s.chassis(300, YG)
s.pill(GX, 1382, "16", "s")
s.pill(GX, 1428, "16a", "s")
s.txt(228, YG + 6, "masa instalacji", "go")
s.txt(228, YG + 20, "auta — NIE PM", "go")

nano = s.module(900, 1290, 200, 240, "blkg",
                [("A1 · Arduino Nano", "mh"), ("sensor_hub.ino", "ms")],
                [("d9", "L", YU1a, "D9"), ("gnd", "L", YG, "GND"), ("d10", "L", YU2b, "D10"),
                 ("rg25", "R", YU1a - 16, ""), ("rg", "R", YU1a, ""), ("a0", "R", YG, "A0"),
                 ("r5", "R", 1470, ""), ("r525", "R", 1486, "")], ly0=64)
# 5V i GND Nano: po dwa przewody na pinie (22 i 25) — dwie kropki spięte
# listwą jak zacisk 87 K1; żadnej złączki na przewodzie 22
for ya, yb, lab in ((YU1a - 16, YU1a, "GND"), (1470, 1486, "5V")):
    s.a(f'<line x1="1097" y1="{ya}" x2="1097" y2="{yb}" stroke="#10202b" stroke-width="4"/>')
    s.txt(1089, (ya + yb) / 2 + 4, lab, "tme")
s.txt(985, 1548, "5V i GND: przewody 22 i 25 na tym samym pinie", "xsc")
s.txt(1000, 1460, "USB → M910q", "tmc")
s.txt(1000, 1476, "żyła VBUS przecięta", "ms")
s.wire([u1["4"], nano["d9"]], "ws")
s.pill(610, YU1a, "17", "s")
s.wire([u1["3"], (860, YU1b), (860, YG), nano["gnd"]], "ws")
s.pill(610, YU1b, "18", "s")
s.wire([u2["3"], (860, YU2a), (860, YG)], "ws")
s.dot(860, YG)
s.pill(610, YU2a, "18a", "s")
s.wire([u2["4"], nano["d10"]], "ws")
s.pill(610, YU2b, "17a", "s")
# C3 / C4 (przewody 20 / 20a)
for cx, ya, yb, ref, num in ((780, YU1a, YU1b, "C3 100 nF", "20"),
                             (780, YU2a, YU2b, "C4 100 nF", "20a")):
    ym = (ya + yb) / 2
    s.dot(cx, ya)
    s.dot(cx, yb)
    s.wire([(cx, ya), (cx, ym - 4)], "ws")
    s.wire([(cx, ym + 4), (cx, yb)], "ws")
    s.a(f'<line class="sym" x1="{cx-10}" y1="{ym-4}" x2="{cx+10}" y2="{ym-4}"/>')
    s.a(f'<line class="sym" x1="{cx-10}" y1="{ym+4}" x2="{cx+10}" y2="{ym+4}"/>')
    s.txt(cx - 16, ym + 4, ref, "xse")
    s.pill(cx + 30, ym, num, "s")

rl = s.module(1240, 1290, 200, 210, "blko",
              [("M7 · moduł", "mh"), ("przekaźnika 5 V", "mh"), ("1 kanał", "ms")],
              [("gnd", "L", YU1a, "GND"), ("in", "L", YG, "IN"), ("vcc", "L", 1470, "VCC"),
               ("com", "R", YU1a + 60, "COM"), ("no", "R", YU1a + 110, "NO")], ly0=42)
s.wire([nano["a0"], rl["in"]], "ws")
s.pill(1150, YG, "21", "s")
s.wire([nano["rg"], rl["gnd"]], "ws")
s.wire([nano["r5"], rl["vcc"]], "ws")
s.pill(1170, YU1a, "22", "s")
s.pill(1200, 1470, "22", "s")
bt2 = s.module(1500, 1320, 240, 160, "blk",
               [("M910q — przycisk", "mh"), ("zasilania", "mh"), ("styki równolegle,", "ms"),
                ("przycisk działa dalej", "ms")],
               [("t1", "L", YU1a + 60, "zacisk 1"), ("t2", "L", YU1a + 110, "zacisk 2")])
s.wire([rl["com"], bt2["t1"]], "ws")
s.pill(1470, YU1a + 60, "23", "s")
s.wire([rl["no"], bt2["t2"]], "ws")
s.pill(1470, YU1a + 110, "24", "s")
# przewód 25: MP1584 → Nano 5V / GND
s.wire([mp["outm"], (1700, YMb), (1700, 1250), (1125, 1250), (1125, YU1a - 16),
        nano["rg25"]], "wg")
s.wire([mp["out"], (1745, YMa), (1745, 1560), (1125, 1560), (1125, 1486), nano["r525"]], "wp")
s.pill(1450, 1250, "25", "g")
s.pill(1450, 1560, "25", "p")
s.txt(1450, 1585, "MP1584 OUT+ → Nano 5V, OUT− → Nano GND · 0,75 mm²", "xsc")

# =====================================================================
# 5 · NOTATKI
NY = 1620
s.note(24, NY, 560, 350, "Kolejność podłączania (§10.7)", [
    "1. S1 rozwarty, bank odłączony, F1 wyjęty z oprawki.",
    "2. Nastawy na stole (ZB §11 Etap 1): step-up 19,9–20,5 V bez",
    "    obciążenia · 2 × XY-SK120 CV 14,40 V / CC 5,0 A ·",
    "    2 × XH-M603 15,30 / 14,00 V · XH-M609 11,00 / 12,60 V.",
    "3. Punkt masy przy banku — komplet z §10.6.",
    "4. Bank w koszach, bloki, FB1…FB7, łączniki; pomiar L+ / P−.",
    "5. Przewody 8, 9, 10 — bank przez F7 do LVD, P− przez S1.",
    "6. Przewody 11 i 12 — step-up. POMIAR 19,9–20,5 V BEZ M910q.",
    "7. Dopiero teraz M910q, potem 13–14 (podświetlenie) oraz 13a",
    "    i 25 (MP1584 → Nano; POMIAR 5,0 V przed podłączeniem Nano).",
    "8. Na końcu 1–7a i B — tor ładowania, przy zgaszonym silniku.",
    "9. Rozruch, pomiar prądu cęgami: ok. 10 A przy F12.",
    ("Pominięty krok 6 zabija płytę główną, pominięty krok 8 — bank.", "ntb"),
], step=19)
s.note(604, NY, 580, 350, "Przekroje i wkładki", [
    "1, 2, 3 · 6 mm² (2: ~5 m do bagażnika) · F1 20 A MIDI/ANL",
    "4 · 0,75 mm² ~4–5 m · FK 1 A z przodu, przy wpięciu",
    "5, 5a, 6, 6a, 7, 7a · 2,5 mm² · FC1 / FC2 7,5 A przy OUT+",
    "B · 4 mm² ≤ 1 m · F12 15 A (MIDI/ANL) przy bloku L+",
    "8 · 6 mm² · F7 20 A (MIDI/ANL) przy bloku L+",
    "9 · 6 mm² · 10 · 4 mm² · 11, 12 · 4 mm² (F8 10 A, 5 A na wyjściu)",
    "13, 14 · 1,5 mm² (F9 2 A) · 13a, 25 · 0,75 mm² (F10 3 A)",
    "15–24 · 0,5 mm² · pakiety: FLRY-B 2,5 mm² + FB 10 A",
    ("Masy bez numeru w §10 — przekroje wg §2 i ZB §8.2:", "ntb"),
    "TVS/C1, XY-SK120, XH-M603 → PM 2,5 mm² · K1 85, LVD VIN− 0,75 mm²",
    "step-up IN− 4 mm² · PM → nadwozie: jeden przewód 6 mm²",
    "Tylko miedź (FLRY / OFC), nie CCA. Końcówki zaciskane",
    "zaciskarką zapadkową + koszulka termokurczliwa z klejem.",
    "Wkładki przed LVD (F1, F7, F12) — klasa MIDI/AMI lub ANL;",
    "za LVD i w gałęziach ładowarek wystarczą ATO (ZB §8.1).",
], step=19)
s.note(1204, NY, 572, 350, "Masy i to, czego w tym wariancie nie ma", [
    "Wszystkie masy zestawu schodzą się w JEDNYM punkcie PM przy",
    "banku. P− dochodzi do niego wyłącznie przez S1 — nic nie",
    "ląduje na P− i nie ma mostka P− → PM (§7).",
    "Brak osobnego przewodu masy do klemy „−” rozruchowego —",
    "prąd wraca przez PM i nadwozie (ZB §5.6).",
    ("Wyjątek: 16 / 16a idą do masy instalacji auta (optoizolacja).", "ntb"),
    "Rozłącznik S1 przełączaj tylko bez obciążenia.",
    ("Nie ma w torze: diody blokującej, przekaźnika zapłonu przed", "ntb"),
    ("odbiornikami ani termistora szeregowego; limit RAPL zbędny.", "ntb"),
    "Zapłon jest tylko SYGNAŁEM (przewód 15) — M910q usypia impuls",
    "z A0 na przycisk zasilania (250 ms: S3 / wybudzenie; 5 s: twarde",
    "wyłączenie). Wersja docelowa dokłada F11 (AUX), F13 (telefon)",
    "i wzmacniacz na osobnej gałęzi z rozruchowego — tu ich nie ma.",
    "Wariant PCB: 3, 5, 5a, TVS, C1, K1, D6 na płytce A",
    "(docs/PCB_ZASILANIE.md §1).",
], step=19)

_errors = []
for _check in (s.check_overlaps, s.check_wires, s.check_text):
    try:
        _check()
    except SystemExit as e:
        _errors.append(str(e))
if _errors:
    raise SystemExit("\n".join(_errors))
s.save(OUT)
print("ok —", OUT)
