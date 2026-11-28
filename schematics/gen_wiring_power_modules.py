#!/usr/bin/env python3
"""Generator schematu połączeniowego modułów zasilania — zacisk po zacisku.

Rysuje:
    schematics/wiring_power_modules.svg — jeden arkusz wersji docelowej:
    tor ładowania (F1, TVS + C1, K1, 2 × XY-SK120, 2 × XH-M603, FC1/FC2,
    F12), bank 7 × CSB HR1221W w dwóch koszach 4 + 3 z blokami zbiorczymi,
    wkładkami FB1…FB7 i łącznikami, odbiór po przekątnej, LVD XH-M609,
    rozłącznik masy S1, punkt masy, dystrybucja F8–F11 i F13, step-up
    20 V, bucki LM2596 i MP1584 z przodu, gałąź wzmacniacza.

Uruchomienie (z katalogu głównego repo):
    python3 schematics/gen_wiring_power_modules.py

Źródło danych: docs/ZASILANIE_BUFOROWANE.md (ZB — wartości, nastawy,
przekroje; przy rozbieżności wygrywa) oraz docs/SCHEMATY_POLACZEN.md
(numery przewodów z tabel §2; tabela zgodności z numeracją wariantu
testowego §10 jest na dole arkusza). Po zmianie tabel popraw ten plik
i wygeneruj SVG ponownie — nie edytuj SVG ręcznie.

Wynik jest deterministyczny (bez dat i losowości). Przed zapisem generator
sprawdza, że bloki nie nachodzą na siebie, że napisy mieszczą się w swoich
ramkach i nie zachodzą na siebie ani na przewody, i że przewody nie
przechodzą przez obudowy modułów. Napisy mierzy fontem DejaVu Sans (przez
Pillow, jeśli jest — bez niego kontrola napisów jest pomijana z ostrzeżeniem).
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

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "wiring_power_modules.svg")

# Klasy jak w poprzednim wydaniu arkusza (mod/modP/modA/modB, term, plus,
# minus, sig, wl, wn …) — ten sam język wizualny, większe stopnie pisma.
STYLE = '''<style>
 .bg{fill:#ffffff}
 .mod{fill:#f7f9fb;stroke:#2b3a45;stroke-width:2;rx:6}
 .modP{fill:#fdf3e6;stroke:#a8621a;stroke-width:2;rx:6}
 .modA{fill:#eef7ee;stroke:#2d6a2d;stroke-width:2;rx:6}
 .modB{fill:#eef2fa;stroke:#2b4a8a;stroke-width:2;rx:6}
 .reg{fill:#f4f7fc;stroke:#2b4a8a;stroke-width:1.6;rx:8;stroke-dasharray:8 4}
 .regF{fill:#f6fbf4;stroke:#2d6a2d;stroke-width:1.6;rx:8;stroke-dasharray:8 4}
 .regD{fill:#fffaf2;stroke:#a8621a;stroke-width:2;rx:6}
 .noteb{fill:#fbfcfd;stroke:#c8d2da;stroke-width:1.5;rx:6}
 .tbl{fill:#ffffff;stroke:#c8d2da;stroke-width:1.2}
 .tbh{fill:#eef2fa;stroke:#c8d2da;stroke-width:1.2}
 .term{fill:#ffffff;stroke:#2b3a45;stroke-width:1.5;rx:2}
 .fuse{fill:#ffffff;stroke:#a8621a;stroke-width:2}
 .bar{fill:#d9a066;stroke:#8a5a22;stroke-width:1.5;rx:2}
 .barM{fill:#b9bec4;stroke:#4a545c;stroke-width:1.5;rx:2}
 .wtag{fill:#ffffff;stroke:#8b9aa6;stroke-width:1.2;rx:3}
 .plus{stroke:#c0392b;stroke-width:3;fill:none;stroke-linecap:round}
 .minus{stroke:#222831;stroke-width:2.6;fill:none;stroke-linecap:round}
 .sig{stroke:#2b4a8a;stroke-width:1.8;fill:none;stroke-dasharray:5 3}
 .g{stroke:#222831;stroke-width:2.4;fill:none}
 .gr{stroke:#6a7a86;stroke-width:2.2;fill:none}
 .ch{stroke:#9a6b12;stroke-width:2.2;fill:none}
 .dotf{fill:#222831}
 .dotp{fill:#c0392b}
 .ttl{font-size:22px;font-weight:bold;fill:#10202b}
 .sub{font-size:12.5px;fill:#5a6b78}
 .sec{font-size:15px;font-weight:bold;fill:#2d4150}
 .sn{font-size:14px;font-weight:bold;fill:#ffffff;text-anchor:middle}
 .mt{font-size:13px;font-weight:bold;fill:#10202b;text-anchor:middle}
 .ms{font-size:11px;fill:#4a5a66;text-anchor:middle}
 .rt{font-size:12.5px;font-weight:bold;fill:#2b4a8a}
 .tp{font-size:10.5px;font-weight:bold;fill:#10202b;text-anchor:middle}
 .fl{font-size:11.5px;font-weight:bold;fill:#a8321a;text-anchor:middle}
 .fls{font-size:11.5px;font-weight:bold;fill:#a8321a}
 .flse{font-size:11.5px;font-weight:bold;fill:#a8321a;text-anchor:end}
 .fv{font-size:10.5px;fill:#5a6b78;text-anchor:middle}
 .fvs{font-size:10.5px;fill:#5a6b78}
 .fve{font-size:10.5px;fill:#5a6b78;text-anchor:end}
 .wl{font-size:11px;fill:#a8321a}
 .wlc{font-size:11px;fill:#a8321a;text-anchor:middle}
 .wle{font-size:11px;fill:#a8321a;text-anchor:end}
 .wnum{font-size:10.5px;font-weight:bold;fill:#10202b;text-anchor:middle}
 .barl{font-size:10.5px;font-weight:bold;fill:#3b2408}
 .gl{font-size:10px;font-weight:bold;fill:#222831;text-anchor:middle}
 .grl{font-size:10px;font-weight:bold;fill:#6a7a86;text-anchor:middle}
 .chl{font-size:10px;font-weight:bold;fill:#9a6b12;text-anchor:middle}
 .wn{font-size:11px;fill:#33424e}
 .wnc{font-size:11px;fill:#33424e;text-anchor:middle}
 .nh{font-size:12.5px;font-weight:bold;fill:#10202b}
 .note{font-size:11px;fill:#4a5a66}
 .warn{font-size:11.5px;font-weight:bold;fill:#a8321a}
 .td{font-size:11px;fill:#33424e;text-anchor:middle}
 .tdb{font-size:11px;font-weight:bold;fill:#10202b;text-anchor:middle}
 .tdl{font-size:11px;font-weight:bold;fill:#10202b}
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
MIN_FONT = 9.0
REGION_MARGIN = 8             # min. odstęp obudowy od ramki strefy (px)
_FONTS = {}


def _measure(s, size, bold):
    """Szerokość napisu w px (DejaVu Sans); bez Pillow — zgrubne oszacowanie,
    używane wyłącznie do szerokości ramek zacisków i numerów przewodów."""
    if ImageFont is not None and os.path.exists(DEJAVU[bold]):
        key = (round(size), bold)
        if key not in _FONTS:
            _FONTS[key] = ImageFont.truetype(DEJAVU[bold], key[0])
        return _FONTS[key].getlength(s)
    return len(s) * size * (0.64 if bold else 0.58)


def _esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _seg_hits_rect(x1, y1, x2, y2, rx0, ry0, rx1, ry1):
    """Czy odcinek przecina wnętrze prostokąta (Liang–Barsky)."""
    dx, dy = x2 - x1, y2 - y1
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x1 - rx0), (dx, rx1 - x1), (-dy, y1 - ry0), (dy, ry1 - y1)):
        if p == 0:
            if q <= 0:
                return False
        else:
            t = q / p
            if p < 0:
                t0 = max(t0, t)
            else:
                t1 = min(t1, t)
            if t0 >= t1:
                return False
    return t1 - t0 > 1e-6


class Sheet:
    def __init__(self, w, h, title, subtitle):
        self.W, self.H = w, h
        self.o = []
        self.blocks = []     # (x,y,w,h,cls) — obudowy: nie nachodzą, przewody omijają
        self.regions = []    # (x,y,w,h,cls) — kosze, strefy: bloki w środku albo poza
        self.terms = []      # (x,y,w,h) — ramki zacisków i numerów przewodów
        self.syms = []       # (x,y,w,h) — symbole masy: napisy i przewody omijają
        self.texts = []      # (x,y,s,cls,owner)
        self.segs = []       # (x1,y1,x2,y2,cls)
        self.a(f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
               f'viewBox="0 0 {w} {h}" font-family="DejaVu Sans, Verdana, sans-serif">')
        self.a(f'  <title>{_esc(title)}</title>')
        self.a(STYLE)
        self.a(f'<rect class="bg" x="0" y="0" width="{w}" height="{h}"/>')
        self.txt(24, 34, title, "ttl")
        for i, line in enumerate(subtitle):
            self.txt(24, 56 + i * 17, line, "sub")

    def a(self, s):
        self.o.append(s)

    # ---- prymitywy ---------------------------------------------------
    def txt(self, x, y, s, c="wn", owner=None):
        self.texts.append((x, y, s, c, owner))
        self.a(f'<text class="{c}" x="{x}" y="{y}">{_esc(s)}</text>')

    def rect(self, x, y, w, h, c, kind="block"):
        if kind == "block":
            self.blocks.append((x, y, w, h, c))
        elif kind == "region":
            self.regions.append((x, y, w, h, c))
        self.a(f'<rect class="{c}" x="{x}" y="{y}" width="{w}" height="{h}"/>')

    def wire(self, pts, c="plus"):
        d = " ".join(("M" if i == 0 else "L") + f"{x} {y}" for i, (x, y) in enumerate(pts))
        self.a(f'<path class="{c}" d="{d}"/>')
        for (xa, ya), (xb, yb) in zip(pts, pts[1:]):
            self.segs.append((xa, ya, xb, yb, c))

    def dot(self, x, y, c="dotp"):
        self.a(f'<circle class="{c}" cx="{x}" cy="{y}" r="4"/>')

    def sect(self, x, y, n, t):
        self.a(f'<rect class="secb" x="{x}" y="{y-18}" width="24" height="24" '
               f'rx="4" fill="#2d4150"/>')
        self.txt(x + 12, y - 1, n, "sn")
        self.txt(x + 34, y, t, "sec")

    # ---- elementy ----------------------------------------------------
    def module(self, x, y, w, h, c, lines, top=22, step=17):
        """Obudowa z wyśrodkowanymi napisami: pierwszy pogrubiony."""
        self.rect(x, y, w, h, c)
        for i, s in enumerate(lines):
            self.txt(x + w / 2, y + top + i * step, s, "mt" if i == 0 else "ms")
        return (x, y, w, h)

    def term(self, box, side, pos, label):
        """Zacisk na krawędzi obudowy. side: l/r/t/b; pos: y (l/r) albo x (t/b).
        Zwraca punkt, do którego dochodzi przewód (zewnętrzna krawędź zacisku)."""
        x, y, w, h = box
        tw = max(18, _measure(label, 10.5, True) + 10)
        th = 18
        if side in "lr":
            cx = x if side == "l" else x + w
            cy = pos
        else:
            cx = pos
            cy = y if side == "t" else y + h
        rx, ry = cx - tw / 2, cy - th / 2
        rx, ry = round(rx, 1), round(ry, 1)
        tid = len(self.terms)
        self.terms.append((rx, ry, tw, th))
        self.a(f'<rect class="term" x="{rx}" y="{ry}" width="{tw:.1f}" height="{th}"/>')
        self.txt(round(cx, 1), round(cy + 4, 1), label, "tp", owner=("t", tid))
        if side == "l":
            return (round(rx, 1), cy)
        if side == "r":
            return (round(rx + tw, 1), cy)
        if side == "t":
            return (cx, round(ry, 1))
        return (cx, round(ry + th, 1))

    def tag(self, x, y, num):
        """Numer przewodu w białej ramce, położony NA przewodzie."""
        tw = max(20, _measure(num, 10.5, True) + 9)
        rx, ry = round(x - tw / 2, 1), y - 8
        tid = len(self.terms)
        self.terms.append((rx, ry, tw, 16))
        self.a(f'<rect class="wtag" x="{rx}" y="{ry}" width="{tw:.1f}" height="16"/>')
        self.txt(x, y + 4, num, "wnum", owner=("t", tid))

    def fuse_h(self, cx, y, ref, val, val2=None, above=True):
        """Bezpiecznik w przewodzie poziomym. Zwraca (lewy, prawy) koniec."""
        self.rect(cx - 18, y - 8, 36, 16, "fuse")
        self.a(f'<line class="g" x1="{cx-12}" y1="{y}" x2="{cx+12}" y2="{y}" '
               f'style="stroke-width:1.2"/>')
        if above:
            self.txt(cx, y - 14, ref, "fl")
            self.txt(cx, y + 23, val, "fv")
            if val2:
                self.txt(cx, y + 36, val2, "fv")
        else:
            self.txt(cx, y + 23, ref + " · " + val, "fv")
        return (cx - 18, y), (cx + 18, y)

    def fuse_v(self, x, cy, ref, val, side="r", val2=None):
        """Bezpiecznik w przewodzie pionowym. Zwraca (górny, dolny) koniec."""
        self.rect(x - 8, cy - 18, 16, 36, "fuse")
        self.a(f'<line class="g" x1="{x}" y1="{cy-12}" x2="{x}" y2="{cy+12}" '
               f'style="stroke-width:1.2"/>')
        if side == "r":
            self.txt(x + 14, cy - 3, ref, "fls")
            self.txt(x + 14, cy + 11, val, "fvs")
            if val2:
                self.txt(x + 14, cy + 24, val2, "fvs")
        else:
            self.txt(x - 14, cy - 3, ref, "flse")
            if val:
                self.txt(x - 14, cy + 11, val, "fve")
        return (x, cy - 18), (x, cy + 18)

    def gnd(self, x, y, label="PM", c="g", lc="gl"):
        """Symbol masy: c='g' — punkt masy przy banku, 'gr' — wspólny powrót 31,
        'ch' — nadwozie / masa lokalna."""
        if c == "ch":
            self.a(f'<path class="ch" d="M{x-12} {y} L{x+12} {y}"/>')
            for dx in (-10, -3, 4, 11):
                self.a(f'<path class="ch" d="M{x+dx} {y} L{x+dx-6} {y+9}"/>')
        else:
            self.a(f'<path class="{c}" d="M{x-12} {y} L{x+12} {y} M{x-8} {y+5} '
                   f'L{x+8} {y+5} M{x-4} {y+10} L{x+4} {y+10}"/>')
        self.syms.append((x - 13, y - 2, 26, 14))
        if label:
            self.txt(x, y + 24, label, lc)

    # ---- kontrola ----------------------------------------------------
    def _tbox(self, x, y, s, cls):
        size, bold, anchor = METRICS[cls]
        w = _measure(s, size, bold)
        x0 = x - w / 2 if anchor == "middle" else (x - w if anchor == "end" else x)
        return (x0, y - size * 0.78, x0 + w, y + size * 0.24)

    def check(self):
        bad = []
        # 1. obudowy nie nachodzą na siebie
        for i, (x1, y1, w1, h1, c1) in enumerate(self.blocks):
            for x2, y2, w2, h2, c2 in self.blocks[i + 1:]:
                if x1 < x2 + w2 and x2 < x1 + w1 and y1 < y2 + h2 and y2 < y1 + h1:
                    bad.append(f"bloki nachodzą: {c1}@({x1},{y1}) x {c2}@({x2},{y2})")
        # 2. obudowa w strefie w całości albo w ogóle
        for rx, ry, rw, rh, rc in self.regions:
            for x, y, w, h, c in self.blocks:
                inter = x < rx + rw and rx < x + w and y < ry + rh and ry < y + h
                inside = rx <= x and x + w <= rx + rw and ry <= y and y + h <= ry + rh
                if inter and not inside:
                    bad.append(f"blok {c}@({x},{y}) przecina strefę {rc}@({rx},{ry})")
                elif inside and min(x - rx, rx + rw - x - w, y - ry, ry + rh - y - h) < REGION_MARGIN:
                    bad.append(f"blok {c}@({x},{y}) za blisko ramki strefy {rc}@({rx},{ry})")
        # 3. przewody nie przechodzą przez obudowy, zaciski i symbole masy
        for x1, y1, x2, y2, c in self.segs:
            for x, y, w, h, bc in self.blocks:
                if _seg_hits_rect(x1, y1, x2, y2, x + 1.5, y + 1.5, x + w - 1.5, y + h - 1.5):
                    bad.append(f"przewód ({x1},{y1})-({x2},{y2}) przez blok {bc}@({x},{y})")
            for x, y, w, h in self.terms:
                cx, cy = x + w / 2, y + h / 2
                if _seg_hits_rect(x1, y1, x2, y2, x + 1.5, y + 1.5, x + w - 1.5, y + h - 1.5):
                    # numer przewodu leży na SWOIM przewodzie: odcinek przez środek ramki
                    on_axis = ((y1 == y2 and abs(y1 - cy) < 0.6) or
                               (x1 == x2 and abs(x1 - cx) < 0.6))
                    if not on_axis:
                        bad.append(f"przewód ({x1},{y1})-({x2},{y2}) przez ramkę @({x},{y})")
            for x, y, w, h in self.syms:
                if _seg_hits_rect(x1, y1, x2, y2, x + 1, y + 3, x + w - 1, y + h):
                    bad.append(f"przewód ({x1},{y1})-({x2},{y2}) przez symbol masy @({x},{y})")
        # 4. napisy
        for x, y, s, cls, owner in self.texts:
            if cls not in METRICS:
                bad.append(f"nieznana klasa {cls!r}: {s!r}")
            elif METRICS[cls][0] < MIN_FONT:
                bad.append(f"za mały stopień {cls}: {s!r}")
        if ImageFont is None or not os.path.exists(DEJAVU[False]):
            print("uwaga: brak Pillow albo fontu DejaVu — pomijam kontrolę napisów",
                  file=sys.stderr)
        else:
            bad += self._check_text()
        if bad:
            raise SystemExit("arkusz do poprawki:\n  " + "\n  ".join(bad))

    def _check_text(self):
        bad, boxes = [], []
        frames = [(x, y, w, h, c) for x, y, w, h, c in self.blocks]
        for x, y, s, cls, owner in self.texts:
            if not s.strip():
                continue
            b = self._tbox(x, y, s, cls)
            boxes.append((b, s, cls, owner))
            if b[0] < 4 or b[2] > self.W - 4 or b[1] < 4 or b[3] > self.H - 4:
                bad.append(f"poza arkuszem: {s!r}")
            if owner is not None:
                tx, ty, tw, th = self.terms[owner[1]]
                if b[0] < tx + 1 or b[2] > tx + tw - 1 or b[1] < ty or b[3] > ty + th:
                    bad.append(f"napis wychodzi z zacisku: {s!r}")
                continue
            # ramki zacisków i numerów: obcy napis nie może na nie wchodzić
            for tx, ty, tw, th in self.terms:
                if b[0] < tx + tw and tx < b[2] and b[1] < ty + th and ty < b[3]:
                    bad.append(f"napis wchodzi na zacisk/numer @({tx},{ty}): {s!r}")
            for sx, sy, sw, sh in self.syms:
                if b[0] < sx + sw and sx < b[2] and b[1] < sy + sh and sy < b[3]:
                    bad.append(f"napis wchodzi na symbol masy @({sx},{sy}): {s!r}")
            for fx, fy, fw, fh, fc in frames + self.regions:
                inside = (fx + 2 <= b[0] and b[2] <= fx + fw - 2 and
                          fy + 1 <= b[1] and b[3] <= fy + fh - 1)
                inter = b[0] < fx + fw and fx < b[2] and b[1] < fy + fh and fy < b[3]
                if inter and not inside:
                    bad.append(f"napis przecina ramkę {fc}@({fx},{fy}): {s!r}")
            for x1, y1, x2, y2, c in self.segs:
                if _seg_hits_rect(x1, y1, x2, y2, b[0] - 1, b[1] - 1, b[2] + 1, b[3] + 1):
                    bad.append(f"przewód ({x1},{y1})-({x2},{y2}) przez napis {s!r}")
        for i, (a, sa, ca, oa) in enumerate(boxes):
            for b, sb, cb, ob in boxes[i + 1:]:
                if a[0] < b[2] - 0.5 and b[0] < a[2] - 0.5 and a[1] < b[3] - 0.5 and b[1] < a[3] - 0.5:
                    bad.append(f"napisy zachodzą: {sa!r} x {sb!r}")
        return bad

    def save(self, path):
        self.a("</svg>")
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(self.o) + "\n")


# ======================================================================
W, H = 1640, 2680
s = Sheet(W, H,
          "BCM v8.5 — Schemat połączeniowy modułów zasilania (zacisk po zacisku)",
          ["Wersja docelowa, stan 22.11.2026: 2 × XY-SK120 + 2 × XH-M603, bank 7 × CSB HR1221W "
           "w dwóch koszach 4 + 3 na lince, LVD XH-M609, step-up 1200 W / 20 A ustawiony na 20 V. "
           "Wartości: docs/ZASILANIE_BUFOROWANE.md (ZB).",
           "Czerwony = „+” · czarny = masa · niebieski przerywany = sterowanie · "
           "w białych ramkach numery przewodów z tabel §2 docs/SCHEMATY_POLACZEN.md "
           "(zgodność z §10 na dole) · przy przewodach przekrój.",
           "Symbol masy „PM” = JEDEN punkt masy przy banku (blok masowy, ramka B). "
           "Szary symbol „31” = wspólny powrót z przodu. Brązowy = nadwozie / masa lokalna."])
s.a('<line x1="24" y1="100" x2="1616" y2="100" stroke="#c8d2da" stroke-width="1.5"/>')

# ======================================================================
#  A — TOR ŁADOWANIA
# ======================================================================
s.sect(24, 132, "A", "TOR ŁADOWANIA — akumulator rozruchowy → K1 → 2 × XY-SK120 → "
                     "2 × XH-M603 → F12 → blok L+  (ZB §5.4, §6.3)")
Y1 = 285

bt0 = s.module(40, 190, 200, 130, "mod",
               ["BT0", "akumulator rozruchowy", "Alfa 156 — komora silnika",
                "12 V, 60–70 Ah"])
p_bt = s.term(bt0, "r", Y1, "+")
m_bt = s.term(bt0, "b", 140, "−")
s.wire([m_bt, (140, 342)], "minus")
s.gnd(140, 342, "nadwozie", c="ch", lc="chl")

f1 = s.module(320, 245, 200, 80, "modP",
              ["F1 · 20 A", "MIDI/AMI lub ANL ≥ 2,5 kA", "≤ 30 cm od klemy „+”"])
s.wire([p_bt, (320, Y1)])
s.tag(284, Y1, "1")
s.txt(284, Y1 - 14, "6 mm²", "wlc")

tvs = s.module(690, 190, 230, 130, "modP",
               ["Ochrona wejścia (przed K1)", "D5 · TVS SMCJ20CA (dwukier.)",
                "C1 · 470 µF / 35 V low-ESR", "105 °C · oba równolegle"])
t_in = s.term(tvs, "l", Y1, "+")
t_out = s.term(tvs, "r", Y1, "+")
t_m = s.term(tvs, "b", 805, "−")
s.wire([(520, Y1), t_in])
s.tag(560, Y1, "2")
s.txt(586, Y1 - 6, "6 mm², ~5 m", "wl")
s.txt(586, Y1 + 18, "do bagażnika", "wl")
s.wire([t_m, (805, 362)], "minus")
s.tag(805, 344, "10")
s.txt(818, 348, "2,5 mm²", "wl")
s.gnd(805, 362)

k1 = s.module(1010, 190, 220, 130, "mod",
              ["K1 · przekaźnik 30 A SPDT", "podstawka · ISO 280",
               "D6 1N4007: katoda → 86", "87a — wolny"], top=44)
k30 = s.term(k1, "l", Y1, "30")
k87 = s.term(k1, "r", Y1, "87")
k86 = s.term(k1, "t", 1060, "86")
k85 = s.term(k1, "b", 1180, "85")
s.wire([t_out, k30])
s.tag(966, Y1, "3")
s.txt(966, Y1 - 14, "6 mm²", "wlc")
s.wire([k85, (1180, 362)], "minus")
s.tag(1180, 344, "5")
s.txt(1194, 348, "0,75 mm²", "wl")
s.gnd(1180, 362)

ign = s.module(1340, 128, 270, 66, "mod",
               ["Zapłon albo D+ alternatora", "z przodu · przewód zielony"])
ig = s.term(ign, "l", 175, "12 V")
fk_l, fk_r = s.fuse_h(1290, 175, "FK", "1 A ATO", above=True)
s.wire([ig, fk_r], "sig")
s.wire([fk_l, (1060, 175), k86], "sig")
s.tag(1100, 175, "4")
s.txt(1116, 165, "0,75 mm², ~4–5 m", "wl")

# K1:87 → oba wejścia ładowarek
YB1, YB2 = 470, 680
XF = 80
s.wire([k87, (1270, Y1), (1270, 400), (XF, 400), (XF, YB2)])
s.dot(XF, YB1)
s.txt(640, 416, "6 / 6a — z K1:87 do IN+ obu ładowarek, 2,5 mm², ≤ 1 m każdy", "wl")

notes_a = [
    ("Tor ładowania — zasady", "nh"),
    ("• Bez diody blokującej i bez izolacji: bank od", "note"),
    ("  instalacji odcina rozwarty K1 (ZB §5.4).", "note"),
    ("• IN− = OUT− w XY-SK120 (jeden zacisk). Żadnego", "note"),
    ("  przewodu masy do klemy „−” (ZB §5.6).", "note"),
    ("• Gałęzie 7–8 i 7a–8a tej samej długości;", "note"),
    ("  FC1/FC2 tuż przy OUT+ XH-M603, przed złączeniem.", "note"),
    ("• F12 ≤ 30 cm od bloku L+ (ZB §8a.3).", "note"),
    ("• Cewka K1 najlepiej z D+; LVP modułów 12,8 V.", "note"),
    ("• Pobór z instalacji: 11,9 A (13,8 V) – 13,0 A", "note"),
    ("  (12,6 V, kluczyk ON) — stąd F1 20 A (ZB §8.1).", "note"),
    ("• XH-M603 zasilany z wyjścia swojej ładowarki —", "note"),
    ("  sprawdź test ZB §6.4 pkt 6 przed montażem.", "note"),
]
s.rect(1300, 430, 316, 22 + 17 * len(notes_a), "noteb")
for i, (t, c) in enumerate(notes_a):
    s.txt(1312, 450 + i * 17, t, c)


def branch(y, n, sfx):
    xy = s.module(190, y - 40, 270, 135, "mod",
                  [f"M1{'ab'[n]} · XY-SK120 #{n+1}", "buck-boost CC-CV · 6–36 V",
                   "CV 14,40 V · CC 5,0 A", "OVP 15,0 V · start wyjścia: ON"], top=60)
    xin = s.term(xy, "l", y, "IN+")
    xout = s.term(xy, "r", y, "OUT+")
    xm1 = s.term(xy, "b", 250, "IN−")
    xm2 = s.term(xy, "b", 400, "OUT−")
    s.wire([(XF, y), xin])
    s.tag(122, y, "6" + sfx)
    s.txt(122, y - 13, "2,5 mm²", "wlc")
    s.wire([xm1, (250, y + 116), (400, y + 116), xm2], "minus")
    s.wire([(325, y + 116), (325, y + 130)], "minus")
    s.tag(287, y + 116, "10")
    s.gnd(325, y + 130)
    s.txt(352, y + 128, "2,5 mm²", "wl")

    xh = s.module(620, y - 40, 260, 135, "mod",
                  [f"M2{'ab'[n]} · XH-M603 #{n+1}", "rozłącznik nadnapięciowy",
                   "rozwiera 15,30 V · wraca 14,00 V", f"zasilany z OUT+ M1{'ab'[n]}"],
                  top=60)
    hin = s.term(xh, "l", y, "DC-IN+")
    hout = s.term(xh, "r", y, "OUT+")
    hm = s.term(xh, "b", 750, "DC-IN−")
    s.wire([xout, hin])
    s.tag(530, y, "7" + sfx)
    s.txt(530, y - 13, "2,5 mm², ≤ 0,5 m", "wlc")
    s.wire([hm, (750, y + 130)], "minus")
    s.tag(750, y + 117, "10")
    s.gnd(750, y + 130)
    s.txt(766, y + 121, "2,5 mm²", "wl")

    fl, fr = s.fuse_h(950, y, f"FC{n+1}", "7,5 A ATO")
    s.wire([hout, fl])
    s.wire([fr, (1060, y)])
    s.tag(1010, y, "8" + sfx)
    s.txt(1010, y - 13, "2,5 mm²", "wlc")


branch(YB1, 0, "")
branch(YB2, 1, "a")
YJ = (YB1 + YB2) // 2
s.wire([(1060, YB1), (1060, YB2)])
s.dot(1060, YJ)
s.txt(1048, YJ + 4, "złączenie", "wle")

# ======================================================================
#  B — BANK
# ======================================================================
YBH = 850
s.sect(24, YBH, "B", "BANK 7 × CSB HR1221W — dwa kosze 4 + 3, bloki zbiorcze, "
                     "FB1…FB7, łączniki 6 mm², odbiór po przekątnej  (ZB §4.3, §8)")

YT = 1002              # oś bloków „+”
YM = 1222              # oś bloków „−”
PK_T = 1095            # górna krawędź pakietów


def basket(x0, x1, nums, side, lead_p, lead_m, fb0, pitch=120):
    s.rect(x0, 900, x1 - x0, 390, "reg", kind="region")
    s.txt(x0 + 14, 922, f"KOSZ {side} — pakiety #{nums[0]}…#{nums[-1]}", "rt")
    bp = (x0 + 30, YT - 8, x1 - x0 - 60, 16)
    bm = (x0 + 30, YM - 8, x1 - x0 - 60, 16)
    s.rect(*bp, "bar")
    s.rect(*bm, "bar")
    s.txt(x0 + 38, YT + 4, f"{side}+", "barl")
    s.txt(x0 + 38, YM + 4, f"{side}−", "barl")
    # pakiety wyśrodkowane w koszu — margines do ramki strefy po obu stronach
    m0 = (x1 - x0 - (len(nums) - 1) * pitch - 100) // 2
    for i, n in enumerate(nums):
        px = x0 + m0 + i * pitch
        pk = s.module(px, PK_T, 100, 80, "modB", [f"#{n}", "HR1221W", "12 V · 5,1 Ah"],
                      top=28, step=16)
        pp = s.term(pk, "t", px + 50, "+")
        pm = s.term(pk, "b", px + 50, "−")
        ft, fbt = s.fuse_v(px + 50, 1045, f"FB{fb0 + i}", "10 A")
        s.wire([(px + 50, YT + 8), ft])
        s.wire([fbt, pp])
        s.tag(px + 50, 1075, lead_p)
        s.wire([pm, (px + 50, YM - 8)], "minus")
        s.tag(px + 50, 1200, lead_m)
    return bp, bm


bpL, bmL = basket(150, 700, [1, 2, 3, 4], "L", "11", "13", 1)
s.txt(164, 1252, "11 (+, przez FB1…FB4) i 13 (−): FLRY-B 2,5 mm², 0,25 m ±30 mm,", "note")
s.txt(164, 1268, "równa długość · nasuwki F2 6,3 × 0,8 w pełni izolowane, kapturki", "note")
s.txt(164, 1284, "FB 10 A ATO / mini 5–10 cm od zacisku · bloki: 4 kołki M6, pokrywa", "note")
bpP, bmP = basket(860, 1250, [5, 6, 7], "P", "12", "14", 5, pitch=112)
s.txt(874, 1252, "12 (+, przez FB5…FB7) i 14 (−): jak 11 / 13", "note")
s.txt(874, 1268, "najwyżej 2 oczka M6 na kołek, grubsze na spód", "note")
s.txt(874, 1284, "pakiety numerowane od zewnętrznego końca kosza L", "note")

# łączniki między koszami
s.wire([(bpL[0] + bpL[2], YT), (bpP[0], YT)])
s.tag(780, YT, "15")
s.txt(780, YT - 14, "łącznik „+”", "wlc")
s.txt(780, YT + 22, "6 mm² OFC", "wlc")
s.txt(780, YT + 36, "0,4–0,6 m", "wlc")
s.wire([(bmL[0] + bmL[2], YM), (bmP[0], YM)], "minus")
s.tag(780, YM, "16")
s.txt(780, YM - 14, "łącznik „−”", "wlc")
s.txt(780, YM + 22, "6 mm² OFC", "wlc")
s.txt(780, YM + 36, "ta sama dł.", "wlc")
s.txt(780, 1100, "przerwa", "wnc")
s.txt(780, 1115, "290–296 mm", "wnc")
s.txt(780, 1130, "(otwór na", "wnc")
s.txt(780, 1145, "narty)", "wnc")

# 9: złączenie ładowarek → F12 → L+
f12l, f12r = s.fuse_h(790, 890, "F12", "15 A · MIDI/ANL")
s.wire([(1060, YJ), (1100, YJ), (1100, 890), f12r])
s.wire([f12l, (640, 890), (640, YT - 8)])
s.tag(1100, 800, "9")
s.txt(1118, 790, "4 mm², ≤ 1 m", "wl")
s.txt(1118, 806, "ładowanie → L+", "wl")

# 18: pomiar napięcia banku
s.rect(380, 908, 230, 36, "noteb")
s.txt(495, 922, "18 · pomiar napięcia banku → Nano #2", "wnc")
s.txt(495, 937, "0,5 mm², opcja (ZB §13.4)", "wnc")
f18t, f18b = s.fuse_v(495, 967, "1 A", "", side="l")
s.wire([(495, 944), f18t])
s.wire([f18b, (495, YT - 8)])

# 19: L+ → F7 → (sekcja C) XH-M609 VIN+
X19 = 60
YLVD = 1440
f7t, f7b = s.fuse_v(X19, 1060, "F7", "20 A", val2="MIDI/ANL")
s.wire([(bpL[0], YT), (X19, YT), f7t])
s.wire([f7b, (X19, YLVD), (126, YLVD)])
s.tag(X19, 1160, "19")
s.txt(72, 1188, "6 mm²", "wl")
s.txt(72, 1203, "≤ 0,5 m", "wl")

# 17: P− → S1 → PM
s1 = s.module(1310, 1180, 140, 84, "modP", ["S1 · rozłącznik", "masy 100 A",
                                            "tylko bez obciążenia"])
s.wire([(bmP[0] + bmP[2], YM), (1310, YM)], "minus")
s.tag(1280, YM, "17")
s.txt(1280, YM - 14, "6 mm²", "wlc")
s.txt(1280, YM + 22, "≤ 0,5 m", "wlc")
pm_box = s.module(1300, 900, 316, 240, "regD",
                  ["PM · punkt masy przy banku", "osobny blok masowy — NIE blok P−",
                   "P− dochodzi tylko przez S1 (przewód 17)",
                   "→ jeden przewód 6 mm² do karoserii:",
                   "goły metal, wazelina, nie nad zbiornikiem", "",
                   "Lądują tu: 5 (K1:85) · 10 (TVS/C1,", "XY-SK120, XH-M603) · 17 · 20 (LVD)",
                   "22 (dystrybucja) · 24 (step-up IN−)",
                   "31 (wspólny powrót z przodu) · masa audio",
                   "Z przodu żadnej masy do karoserii."], top=24, step=18)
s.wire([(1450, YM), (1530, YM), (1530, 1140)], "minus")
s.txt(1490, YM - 8, "6 mm²", "wlc")
s.wire([(1590, 1140), (1590, 1168)], "minus")
s.txt(1580, 1160, "6 mm²", "wle")
s.gnd(1590, 1168, "karoseria", c="ch", lc="chl")

s.txt(84, 1318, "ODBIÓR PO PRZEKĄTNEJ: „+” z bloku L+ (przewody 9, 19), „−” z bloku P− "
               "(przewód 17) → rozrzut prądów pakietów ok. 4 %. Oba bieguny z jednego kosza: "
               "ok. 24 % — ZAKAZ (ZB §4.3).", "warn")

# ======================================================================
#  C — LVD, DYSTRYBUCJA, ODBIORNIKI
# ======================================================================
s.sect(84, 1362, "C", "LVD, DYSTRYBUCJA I ODBIORNIKI — szyna buforowana, zasilana stale  "
                      "(ZB §3, §7, §8; SCHEMATY §2.3–§2.5)")

lvd = s.module(150, 1400, 290, 130, "mod",
               ["M3 · XH-M609 (LVD)", "odcina 11,00 V · wraca 12,60 V",
                "przekaźnik 20 A — przerywa „+”", "VOUT− zostaje wolny"], top=72)
vin = s.term(lvd, "l", YLVD, "VIN+")
vim = s.term(lvd, "l", 1500, "VIN−")
vout = s.term(lvd, "r", YLVD, "VOUT+")
s.term(lvd, "r", 1500, "VOUT−")
s.wire([vim, (100, 1500), (100, 1532)], "minus")
s.tag(100, 1516, "20")
s.txt(88, 1520, "0,75 mm²", "wle")
s.gnd(100, 1532)

DX0, DX1 = 560, 780
ROWS = [1560, 1680, 1800, 1912, 2010]
dist = (DX0, 1400, DX1 - DX0, 640)
s.rect(*dist, "regD", kind="region")
s.txt((DX0 + DX1) / 2 + 10, 1468, "Dystrybucja za LVD", "mt")
s.txt((DX0 + DX1) / 2 + 10, 1485, "skrzynka ATO z pokrywą", "ms")
s.txt((DX0 + DX1) / 2 + 10, 1500, "albo płytka B (X8–X12)", "ms")
x81 = s.term(dist, "l", YLVD, "X8.1")
x82 = s.term(dist, "b", 640, "X8.2")
s.wire([vout, x81])
s.tag(492, YLVD, "21")
s.txt(492, YLVD - 13, "4 mm², ≤ 0,5 m", "wlc")
s.wire([x82, (640, 2080)], "minus")
s.tag(640, 2063, "22")
s.txt(654, 2067, "2,5 mm²", "wl")
s.gnd(640, 2080)

XBUS = 585
s.wire([(DX0 + 22, YLVD), (XBUS, YLVD), (XBUS, ROWS[-1])])
fuses = [("F8", "10 A"), ("F9", "2 A"), ("F10", "3 A"), ("F11", "5 A"), ("F13", "2 A · opcja")]
outs = []
for (ref, val), y in zip(fuses, ROWS):
    s.dot(XBUS, y)
    fl, fr = s.fuse_h(690, y, ref, val)
    s.wire([(XBUS, y), fl])
    outs.append(fr)

# step-up (w bagażniku, przy koszach — ZB §8a.1)
su = s.module(860, 1500, 270, 130, "mod",
              ["M4 · step-up 12 → 20 V", "1200 W / 20 A, nast. 20,0 V",
               "bez obciążenia 19,9–20,5 V", "czkawka? 470 µF na OUT"], top=62)
su_in = s.term(su, "l", 1560, "IN+")
su_m = s.term(su, "l", 1600, "IN−")
su_op = s.term(su, "r", 1540, "OUT+")
su_om = s.term(su, "r", 1600, "OUT−")
s.wire([outs[0], su_in])
s.tag(810, 1560, "23")
s.txt(810, 1547, "4 mm²", "wlc")
s.wire([su_m, (826, 1600), (826, 1640)], "minus")
s.tag(826, 1620, "24")
s.txt(842, 1648, "4 mm²", "wl")
s.gnd(826, 1640)

# strefa przednia
FZ = (1214, 1440, 402, 740)
s.rect(*FZ, "regF", kind="region")
s.txt(1228, 1462, "Z PRZODU — przy desce, ok. 4 m od bagażnika", "rt")

m910 = s.module(1380, 1490, 228, 130, "modA",
                ["Lenovo M910q", "zasilany stale", "wtyk z uciętego kabla",
                 "na wtyku ≥ 19,5 V · 65 W"], top=26)
mp = s.term(m910, "l", 1540, "środek +")
mm = s.term(m910, "l", 1600, "ekran −")
f5l, f5r = s.fuse_h(1180, 1540, "5 A", "wyjście")
s.wire([su_op, f5l])
s.wire([f5r, mp])
s.tag(1246, 1540, "25")
s.txt(1262, 1528, "4 mm², ~4 m", "wl")
s.wire([su_om, mm], "minus")
s.tag(1246, 1600, "26")
s.txt(1262, 1618, "4 mm², ~4 m", "wl")

XFB = 1256                      # lewa krawędź modułów przednich


def front_ret(pt, x=1232):
    """Masa modułu przedniego → wspólny powrót 31 (szary symbol)."""
    s.wire([pt, (x, pt[1]), (x, pt[1] + 12)], "minus")
    s.gnd(x, pt[1] + 12, "31", c="gr", lc="grl")


def buck(y0, ref, name, role, outv, yin, dest_title, dest_terms, tags, wnum, wtxt, row):
    b = s.module(XFB, y0, 140, 100, "modA", [ref + " · " + name, role, outv], top=18)
    b_in = s.term(b, "l", yin, "IN+")
    b_m = s.term(b, "l", yin + 36, "IN−")
    b_op = s.term(b, "r", yin, "OUT+")
    b_om = s.term(b, "r", yin + 50, "OUT−")
    s.wire([outs[row], b_in])
    s.tag(1000, yin, wnum)
    s.txt(1020, yin - 10, wtxt, "wl")
    front_ret(b_m)
    d = s.module(1510, y0, 98, 100, "modA", [dest_title], top=18)
    pa = s.term(d, "l", yin, dest_terms[0])
    pb = s.term(d, "l", yin + 25, dest_terms[1])
    pc = s.term(d, "l", yin + 50, dest_terms[2])
    s.wire([b_op, pa])
    s.dot(1432, yin)
    s.wire([(1432, yin), (1432, yin + 25), pb])
    s.wire([b_om, pc], "minus")
    s.tag(1458, yin, tags[0])
    s.tag(1458, yin + 25, tags[1])
    s.tag(1446, yin + 50, tags[2])


buck(1640, "M5", "LM2596", "wyświetlacze", "OUT wg panelu", 1680,
     "Panele", ("10,1″", "6,86″", "GND"), ("35", "36", "37"), "27", "1,0 mm², ~4 m", 1)
buck(1760, "M6", "MP1584", "logika, Arduino", "OUT 5,0 V", 1800,
     "Logika", ("Nano", "BLE/RF", "GND"), ("32", "33", "34"), "28", "0,75 mm², ~4 m", 2)

rel = s.module(XFB, 1890, 220, 66, "modA",
               ["Moduł 9 przekaźników", "+ hub USB 12 V (F11)"], top=24)
rl_in = s.term(rel, "l", 1912, "VCC")
rl_m = s.term(rel, "l", 1940, "GND")
s.wire([outs[3], rl_in])
s.tag(1000, 1912, "29")
s.txt(1020, 1902, "1,5 mm²", "wl")
front_ret(rl_m)

inj = s.module(XFB, 1984, 220, 66, "modA", ["Wstrzykiwacz 5 V", "telefon w aucie · opcja"],
               top=24)
ij_in = s.term(inj, "l", 2010, "IN+")
ij_m = s.term(inj, "l", 2036, "GND")
s.wire([outs[4], ij_in])
s.tag(1000, 2010, "30")
s.txt(1020, 2000, "0,75 mm², ~4 m", "wl")
front_ret(ij_m)

front_notes = [
    "31 = wspólny powrót 2,5 mm², ~4 m do PM;",
    "z przodu żadnej masy do karoserii.",
    "32, 34: 0,75 mm² · 33: 0,5 mm² · 35–37: 1,0 mm²",
    "35/36: podświetlenie przez MOSFET (PWM",
    "Nano #1); 6,86″ opcjonalny. Nano: pin 5V.",
]
for i, t in enumerate(front_notes):
    s.txt(1228, 2098 + i * 15, t, "note")

# 31: wspólny powrót z przodu → PM (rysowany w bagażniku)
s.wire([(1196, 2050), (880, 2050), (880, 2080)], "minus")
s.tag(1010, 2050, "31")
s.txt(1010, 2038, "← z przodu", "wlc")
s.gnd(880, 2080)

# ======================================================================
#  D — WZMACNIACZ, KOLEJNOŚĆ, ZGODNOŚĆ NUMERÓW
# ======================================================================
YD = 2225
s.sect(24, YD, "D", "GAŁĄŹ WZMACNIACZA · KOLEJNOŚĆ PODŁĄCZANIA · NUMERY PRZEWODÓW")

s.rect(40, YD + 20, 720, 260, "reg", kind="region")
s.txt(54, YD + 42, "Gałąź niezależna od bufora — z klemy akumulatora rozruchowego "
                   "(SCHEMATY §2.6)", "rt")
ab = s.module(60, YD + 70, 150, 60, "mod", ["BT0 „+”", "przy klemie"], top=24)
a_p = s.term(ab, "r", YD + 100, "+")
afl, afr = s.fuse_h(270, YD + 100, "wg karty", "20–30 A", val2="klasa jak F1")
s.wire([a_p, afl])
amp = s.module(470, YD + 62, 270, 150, "mod",
               ["Wzmacniacz samochodowy", "gotowy moduł, wejścia RCA",
                "REM z zapłonu, nie z komputera"], top=22)
am_p = s.term(amp, "l", YD + 100, "+12V")
am_r = s.term(amp, "l", YD + 185, "REM")
am_g = s.term(amp, "b", 560, "GND")
s.wire([afr, am_p])
s.tag(380, YD + 100, "44")
s.txt(380, YD + 87, "6 mm², ~4 m", "wlc")
s.wire([am_g, (560, YD + 250)], "minus")
s.tag(560, YD + 234, "45")
s.gnd(560, YD + 250, None, c="ch")
s.txt(578, YD + 238, "6 mm², masa lokalna ≤ 1 m", "wl")
acc = s.module(60, YD + 160, 150, 50, "mod", ["ACC (zapłon)"], top=30)
acc_p = s.term(acc, "r", YD + 185, "12 V")
rfl, rfr = s.fuse_h(270, YD + 185, "2 A", "", above=True)
s.wire([acc_p, rfl], "sig")
s.wire([rfr, am_r], "sig")
s.tag(380, YD + 185, "46")
s.txt(380, YD + 172, "0,75 mm²", "wlc")

order = [
    ("Kolejność podłączania (SCHEMATY §8, §9; ZB §11)", "nh"),
    ("1. Punkt masy PM przy banku — < 0,5 Ω do klemy „−” rozruchowego.", "note"),
    ("2. Dystrybucja i moduły przykręcone, zaciski dokręcone — BEZ wkładek i zasilania.", "note"),
    ("3. Nastawy na stole: XY-SK120 CV 14,40 V / CC 5,0 A, XH-M603 15,30 / 14,00 V,", "note"),
    ("    XH-M609 11,00 / 12,60 V, step-up 19,9–20,5 V bez obciążenia, MP1584 5,0 V.", "note"),
    ("4. Bank: 7 pakietów zmierzonych i wyrównanych, bloki L+/L−/P+/P− z pokrywami,", "note"),
    ("    odcinki 11–14 równej długości, FB1…FB7, łączniki 15–16. S1 ROZWARTY.", "note"),
    ("5. 17: P− przez S1 do PM, S1 ZWARTY. Potem 19 przez F7 do LVD i 21–37;", "note"),
    ("    step-up zmierz PRZED podłączeniem M910q.", "note"),
    ("6. Tor ładowania 1–10 przy zgaszonym silniku; F1 20 A wkładany JAKO OSTATNI.", "note"),
    ("7. Silnik: ok. 10 A przy F12; zgaszony — prąd w stronę ładowarek < 1 mA.", "note"),
]
s.rect(800, YD + 20, 816, 26 + 20 * len(order), "noteb")
for i, (t, c) in enumerate(order):
    s.txt(814, YD + 44 + i * 20, t, c)

# tabela zgodności numeracji §2 (ten arkusz) ↔ §10 (wariant testowy)
MAP = [("1", "1"), ("2", "2"), ("3", "3"), ("4", "4"), ("6 / 6a", "5 / 5a"),
       ("7 / 7a", "6 / 6a"), ("8 / 8a", "7 / 7a"), ("9", "B"), ("19", "8"),
       ("17", "9"), ("21", "10"), ("23", "11"), ("25 / 26", "12"), ("27", "13"),
       ("35 / 37", "14"), ("28", "13a"), ("32", "25")]
YT0 = YD + 320
s.txt(40, YT0, "Zgodność numerów: ten arkusz = SCHEMATY §2 (wersja docelowa); "
               "wariant testowy (§10, schematic_test_power.svg) numeruje te same przewody "
               "inaczej:", "nh")
CX0, RH = 40, 22
s.rect(CX0, YT0 + 12, 190, RH, "tbh", kind="none")
s.txt(CX0 + 8, YT0 + 27, "§2 — ten arkusz", "tdl")
s.rect(CX0, YT0 + 12 + RH, 190, RH, "tbl", kind="none")
s.txt(CX0 + 8, YT0 + 27 + RH, "§10 — wariant testowy", "tdl")
for i, (a, b) in enumerate(MAP):
    x = CX0 + 190 + i * 81
    s.rect(x, YT0 + 12, 81, RH, "tbh", kind="none")
    s.rect(x, YT0 + 12 + RH, 81, RH, "tbl", kind="none")
    s.txt(x + 40.5, YT0 + 27, a, "tdb")
    s.txt(x + 40.5, YT0 + 27 + RH, b, "td")
s.txt(40, YT0 + 78, "Bez numeru w §10: 5 i 10 (masy toru ładowania, §10.6), 11–16 (bank). "
                    "Tylko w wersji docelowej: 18, 20, 22, 24, 29–31, 33, 34, 36, 44–46.", "note")
s.txt(40, YT0 + 95, "Numeracja zacisków K1 wg ISO 280: 30 = wspólny, 87 = zwierny (NO), "
                    "87a = rozwierny (NC), 85/86 = cewka. Na tanich podstawkach opisy bywają "
                    "inne — sprawdź omomierzem.", "note")
s.txt(40, YT0 + 112, "Wariant testowy (SCHEMATY §10.3) celowo: przewody 13 i 14 · 1,5 mm² (zapas "
                     "na bezpieczniku 2 A) i panel 7″. Wersja docelowa (ten arkusz, ZB §8.2 / §8a.2): "
                     "1,0 mm² i panel 10,1″.", "note")

s.check()
s.save(OUT)
print(f"zapisano {os.path.relpath(OUT)}")
