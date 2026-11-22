#!/usr/bin/env python3
"""Generator arkusza „rozdział odbiorników" — power_domains_m910q.svg.

Rysuje jeden arkusz: co wisi na szynie buforowanej za LVD, wkładki
odgałęzień F8–F11 i F13, budżet poboru w trzech stanach maszyny
(praca / S3 / wyłączony) ze stratami step-upu 20 V, tabelę czasu postoju
dla banku 35,7 Ah i osobną gałąź wzmacniacza.

Uruchomienie (z katalogu głównego repo):
    python3 schematics/gen_power_domains_m910q.py

Źródło liczb: docs/ZASILANIE_BUFOROWANE.md (§2.1, §2.2, §3.2, §7, §8.1,
§8.2, §9.1–§9.3, §13.5) oraz docs/SCHEMATY_POLACZEN.md §2.4–§2.6 i §6.
Po zmianie liczb w dokumentach popraw ten plik i wygeneruj SVG ponownie —
nie edytuj SVG ręcznie.

Generator jest deterministyczny (bez dat i losowości). Przed zapisem
sprawdza, że ramki nie nachodzą na siebie częściowo, napisy mieszczą się
w arkuszu i w swoich ramkach, nie zachodzą na siebie i nie przecinają ich
przewody. Do mierzenia napisów używa Pillow + DejaVu Sans, jeśli są —
bez nich szacuje szerokość z zapasem.
"""

import os
import re

try:
    from PIL import ImageFont
except ImportError:                                           # pragma: no cover
    ImageFont = None

DEJAVU = {
    False: "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    True:  "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
}

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "power_domains_m910q.svg")

W, H = 1400, 1330

STYLE = '''<style>
 .bg{fill:#ffffff}
 .box{fill:#f7f9fb;stroke:#2b3a45;stroke-width:2}
 .boxA{fill:#eef7ee;stroke:#2d6a2d;stroke-width:2}
 .boxB{fill:#eef2fa;stroke:#2b4a8a;stroke-width:2}
 .boxC{fill:#fbeff1;stroke:#97324a;stroke-width:2}
 .boxO{fill:#fbf8f0;stroke:#8a6d2b;stroke-width:2;stroke-dasharray:7 4}
 .tbl{fill:#fbfcfd;stroke:#c8d2da;stroke-width:1.5}
 .thd{fill:#eef2f5;stroke:none}
 .rule{stroke:#c8d2da;stroke-width:1}
 .zone{stroke:#8b9aa6;stroke-width:1.6;fill:none;stroke-dasharray:9 6}
 .wire{stroke:#c0392b;stroke-width:3;fill:none}
 .wA{stroke:#2d6a2d;stroke-width:2.5;fill:none}
 .wB{stroke:#2b4a8a;stroke-width:2.5;fill:none}
 .wC{stroke:#97324a;stroke-width:2.5;fill:none}
 .wO{stroke:#8a6d2b;stroke-width:2.5;fill:none;stroke-dasharray:7 4}
 .fs{fill:#ffffff;stroke:#a8321a;stroke-width:2}
 .ttl{font-size:20px;font-weight:bold;fill:#10202b}
 .sub{font-size:12px;fill:#5a6b78}
 .h{font-size:13px;font-weight:bold;fill:#10202b;text-anchor:middle}
 .hl{font-size:14px;font-weight:bold;fill:#10202b}
 .t{font-size:11px;fill:#33424e;text-anchor:middle}
 .tl{font-size:11px;fill:#33424e}
 .tb{font-size:11px;font-weight:bold;fill:#10202b}
 .tbc{font-size:11px;font-weight:bold;fill:#10202b;text-anchor:middle}
 .note{font-size:10.5px;fill:#6a7a86}
 .notec{font-size:10.5px;fill:#6a7a86;text-anchor:middle}
 .notee{font-size:10.5px;fill:#6a7a86;text-anchor:end}
 .fuse{font-size:11px;font-weight:bold;fill:#a8321a}
 .fusec{font-size:10.5px;font-weight:bold;fill:#a8321a;text-anchor:middle}
 .zl{font-size:11px;font-weight:bold;fill:#5a6b78;text-anchor:end}
 .secA{font-size:13px;font-weight:bold;fill:#2d6a2d}
 .secC{font-size:13px;font-weight:bold;fill:#97324a;text-anchor:middle}
</style>'''


def _class_metrics(css):
    """Rozmiar, grubość i wyrównanie każdej klasy tekstu — z CSS-a wyżej."""
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
FRAMES = ("box", "boxA", "boxB", "boxC", "boxO", "tbl")
_FONTS = {}


def _measure(s, size, bold):
    if ImageFont is not None and os.path.exists(DEJAVU[bold]):
        key = (round(size), bold)
        if key not in _FONTS:
            _FONTS[key] = ImageFont.truetype(DEJAVU[bold], key[0])
        return _FONTS[key].getlength(s)
    # Bez Pillow: DejaVu Sans ma średnio ~0,62 em (bold ~0,68 em) — z zapasem.
    return len(s) * size * (0.68 if bold else 0.62)


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class Sheet:
    def __init__(self, title):
        self.o = []
        self.rects = []      # (x, y, w, h, cls)
        self.texts = []      # (x, y, s, cls)
        self.segs = []       # odcinki przewodów (x1, y1, x2, y2)
        self.a(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
               f'viewBox="0 0 {W} {H}" font-family="DejaVu Sans, Verdana, sans-serif">')
        self.a(f'  <title>{esc(title)}</title>')
        self.a(STYLE)
        self.a(f'<rect class="bg" x="0" y="0" width="{W}" height="{H}"/>')

    def a(self, s):
        self.o.append(s)

    def txt(self, x, y, s, c="tl"):
        # SVG zwija spacje — wcięcie wiersza-kontynuacji robimy przesunięciem x.
        n = len(s) - len(s.lstrip(" "))
        if n:
            x, s = x + 5 * n, s.lstrip(" ")
        self.texts.append((x, y, s, c))
        self.a(f'<text class="{c}" x="{x}" y="{y}">{esc(s)}</text>')

    def box(self, x, y, w, h, c="box"):
        self.rects.append((x, y, w, h, c))
        self.a(f'<rect class="{c}" x="{x}" y="{y}" width="{w}" height="{h}" rx="6"/>')

    def wire(self, pts, c="wire"):
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            self.segs.append((x1, y1, x2, y2))
        d = "M" + " L".join(f"{x} {y}" for x, y in pts)
        self.a(f'<path class="{c}" d="{d}"/>')

    def line(self, x1, y1, x2, y2, c="rule"):
        self.a(f'<line class="{c}" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}"/>')

    def dot(self, x, y, color="#c0392b"):
        self.a(f'<circle cx="{x}" cy="{y}" r="4" fill="{color}"/>')

    def fuse_v(self, x, y):
        """Wkładka pionowa: prostokąt 12 × 24 z przewodem przez środek."""
        self.a(f'<rect class="fs" x="{x - 6}" y="{y}" width="12" height="24" rx="2"/>')
        self.a(f'<line stroke="#a8321a" stroke-width="1.5" x1="{x}" y1="{y + 3}" '
               f'x2="{x}" y2="{y + 21}"/>')

    def fuse_h(self, x, y):
        self.a(f'<rect class="fs" x="{x}" y="{y - 6}" width="24" height="12" rx="2"/>')
        self.a(f'<line stroke="#a8321a" stroke-width="1.5" x1="{x + 3}" y1="{y}" '
               f'x2="{x + 21}" y2="{y}"/>')

    def lines(self, x, y, items, step=17):
        """Kolejne wiersze: items = [(tekst, klasa) | tekst]; zwraca następne y."""
        for it in items:
            s, c = it if isinstance(it, tuple) else (it, "tl")
            if s:
                self.txt(x, y, s, c)
            y += step
        return y

    def table(self, x, y, cols, header, rows, hh, rh, emph_first=True):
        """Tabela: cols = szerokości kolumn, komórki to listy wierszy tekstu."""
        tw = sum(cols)
        th = hh + rh * len(rows)
        self.box(x, y, tw, th, "tbl")
        self.a(f'<rect class="thd" x="{x + 1}" y="{y + 1}" width="{tw - 2}" '
               f'height="{hh - 1}"/>')
        self.line(x, y + hh, x + tw, y + hh)
        for i in range(1, len(rows)):
            self.line(x + 8, y + hh + i * rh, x + tw - 8, y + hh + i * rh)

        def cells(cy, cellrow, h, bold_all):
            cx = x
            for j, (w, cell) in enumerate(zip(cols, cellrow)):
                cell = cell if isinstance(cell, list) else [cell]
                n = len(cell)
                y0 = cy + (h - n * 15) / 2 + 11
                for k, s in enumerate(cell):
                    c = "tb" if (bold_all or (j == 0 and emph_first and k == 0)) else "tl"
                    if k > 0 and j == 0:
                        c = "note"
                    self.txt(cx + 8, round(y0 + k * 15, 1), s, c)
                    tw_ = _measure(s, *METRICS[c][:2])
                    if tw_ > w - 12:
                        raise SystemExit(f"za szeroko w kolumnie ({tw_:.0f} > {w - 12}): {s!r}")
                cx += w

        cells(y, header, hh, True)
        for i, r in enumerate(rows):
            cells(y + hh + i * rh, r, rh, False)
        return y + th

    def save(self):
        self.a("</svg>")
        with open(OUT, "w", encoding="utf-8") as f:
            f.write("\n".join(self.o) + "\n")

    # ---- kontrole geometrii
    def check_overlaps(self):
        bad = []
        for i, (x1, y1, w1, h1, c1) in enumerate(self.rects):
            for x2, y2, w2, h2, c2 in self.rects[i + 1:]:
                inter = x1 < x2 + w2 and x2 < x1 + w1 and y1 < y2 + h2 and y2 < y1 + h1
                if not inter:
                    continue
                a_in_b = x2 <= x1 and y2 <= y1 and x1 + w1 <= x2 + w2 and y1 + h1 <= y2 + h2
                b_in_a = x1 <= x2 and y1 <= y2 and x2 + w2 <= x1 + w1 and y2 + h2 <= y1 + h1
                if not (a_in_b or b_in_a):
                    bad.append(f"{c1}@({x1},{y1}) x {c2}@({x2},{y2})")
                elif not (x2 - x1 >= 8 or x1 - x2 >= 8):
                    bad.append(f"ramka w ramce bez marginesu: {c1}@({x1},{y1})")
        if bad:
            raise SystemExit("ramki nachodzą na siebie: " + "; ".join(bad))

    def _text_box(self, x, y, s, cls):
        size, bold, anchor = METRICS[cls]
        w = _measure(s, size, bold)
        x0 = x - w / 2 if anchor == "middle" else (x - w if anchor == "end" else x)
        return (x0, y - size * 0.78, x0 + w, y + size * 0.24)

    def check_text(self):
        bad, boxes = [], []
        for x, y, s, cls in self.texts:
            if cls not in METRICS:
                bad.append(f"nieznana klasa {cls!r}: {s!r}")
                continue
            if METRICS[cls][0] < 9:
                bad.append(f"napis poniżej 9 px: {s!r}")
            bx = self._text_box(x, y, s, cls)
            boxes.append((bx, s, cls))
            if bx[0] < 8 or bx[2] > W - 8 or bx[1] < 0 or bx[3] > H:
                bad.append(f"poza arkuszem: {s!r}")
                continue
            # Najmniejsza ramka, w której napis się zaczyna, musi go zmieścić;
            # w ramki, w których się nie zaczyna, nie może wchodzić.
            inside = [r for r in self.rects if r[4] in FRAMES and
                      r[0] <= bx[0] <= r[0] + r[2] and r[1] <= bx[1] <= r[1] + r[3]]
            for fx, fy, fw, fh, fc in self.rects:
                if fc not in FRAMES:
                    continue
                if (fx, fy, fw, fh, fc) in inside:
                    if bx[0] < fx + 3 or bx[2] > fx + fw - 3 or bx[3] > fy + fh - 2:
                        bad.append(f"wychodzi z ramki {fc}@({fx},{fy}): {s!r}")
                elif (bx[0] < fx + fw - 1 and fx < bx[2] - 1 and
                      bx[1] < fy + fh - 1 and fy < bx[3] - 1):
                    bad.append(f"napis wchodzi w ramkę {fc}@({fx},{fy}): {s!r}")
            for x1, y1, x2, y2 in self.segs:
                lx, hx = sorted((x1, x2))
                ly, hy = sorted((y1, y2))
                if lx - 2 < bx[2] and bx[0] < hx + 2 and ly - 2 < bx[3] and bx[1] < hy + 2:
                    bad.append(f"przewód przecina napis: {s!r}")
        for i, (a, sa, ca) in enumerate(boxes):
            for b, sb, cb in boxes[i + 1:]:
                if a[0] < b[2] - 1 and b[0] < a[2] - 1 and a[1] < b[3] - 1 and b[1] < a[3] - 1:
                    bad.append(f"napisy zachodzą: {sa!r} x {sb!r}")
        if bad:
            raise SystemExit("napisy do poprawki:\n  " + "\n  ".join(bad))


# ============================================================================
s = Sheet("BCM v8.5 — rozdział odbiorników, bezpieczniki i budżet poboru "
          "w trzech stanach (M910q)")
s.txt(24, 32, "Rozdział odbiorników, bezpieczniki i budżet poboru", "ttl")
s.txt(24, 52, "Jedna szyna buforowana za LVD — zapłon niczego nie odcina, zmienia "
      "tylko stan maszyny (impuls z Arduino na przycisk zasilania M910q).  "
      "Wg docs/ZASILANIE_BUFOROWANE.md (22.11.2026).", "sub")
s.line(24, 62, W - 24, 62)

# ---- źródło: ładowanie → bank → F7 → LVD -----------------------------------
TOP, TH = 84, 88
s.box(40, TOP, 280, TH)
s.lines(180, TOP + 22, [
    ("Ładowanie — osobny rysunek", "h"),
    ("F1 20 A → TVS + C1 → K1 30 A (zapłon / D+)", "t"),
    ("→ 2 × XY-SK120 → 2 × XH-M603 → FC1/FC2", "t"),
    ("charging_lvd.svg · power_buffered_m910q.svg", "notec")], step=19)

s.wire([(320, 128), (400, 128)])
s.fuse_h(348, 128)
s.txt(360, 104, "MIDI/ANL", "fusec")
s.txt(360, 116, "F12 15 A", "fusec")
s.txt(344, 150, "4 mm²", "note")

s.box(400, TOP, 300, TH)
s.lines(550, TOP + 22, [
    ("Bank 7 × CSB HR1221W — 35,7 Ah", "h"),
    ("2 kosze w bagażniku: L #1–#4, P #5–#7", "t"),
    ("FB1…FB7 10 A · łącznik L↔P 6 mm² OFC", "t"),
    ("odbiór po przekątnej: „+” z L+, „−” z P−", "t")], step=19)

s.wire([(700, 128), (790, 128)])
s.fuse_h(733, 128)
s.txt(745, 104, "MIDI/ANL", "fusec")
s.txt(745, 116, "F7 20 A", "fusec")
s.txt(729, 150, "6 mm²", "note")

s.box(790, TOP, 300, TH)
s.lines(940, TOP + 22, [
    ("XH-M609 — LVD", "h"),
    ("odcięcie 11,00 V · powrót 12,60 V", "t"),
    ("przekaźnik 20 A (szczyt odbiorników 10,5 A)", "t"),
    ("pobór własny 20–125 mA — zmierz (§7.3)", "t")], step=19)

s.box(1110, TOP, 250, TH)
s.lines(1235, TOP + 22, [
    ("Masa — blok masowy (gwiazda)", "h"),
    ("blok P− → S1 100 A → blok masowy", "t"),
    ("→ nadwozie 6 mm² · audio osobno", "t"),
    ("masy z bagażnika i powrót 2,5 mm² z przodu", "notec"),
    ("na bloku masowym, nie na P− (§10.6)", "notec")], step=15)

# ---- szyna i odgałęzienia ---------------------------------------------------
BUS = 204
COLX = [40, 307, 574, 841, 1108]
CW = 252
DX = [x + 30 for x in COLX]           # x przewodu odgałęzienia w kolumnie

s.wire([(940, TOP + TH), (940, BUS)])
s.txt(948, 192, "4 mm²", "note")
s.wire([(DX[0], BUS), (DX[-1], BUS)])
for x in DX:
    s.dot(x, BUS)
s.dot(940, BUS)
s.txt(84, 194, "SZYNA BUFOROWANA 12 V za LVD (11,0–14,4 V) — dystrybucja "
      "w bagażniku · F8–F11, F13: ATO przy źródle", "tb")
s.txt(1000, 194, "F7, F12: MIDI/ANL, ≥ 2,5 kA (ZB §7.4)", "note")

FUSES = [
    ("F8 10 A", "4 mm², ≤ 1 m · do 6,6 A", "wB"),
    ("F9 2 A", "1,0 mm², ~4 m · ~1,5 A", "wB"),
    ("F10 3 A", "0,75 mm², ~4 m · < 1 A", "wA"),
    ("F11 5 A", "1,5 mm² · do ~2 A", "wA"),
    ("F13 2 A (opcja)", "0,75 mm², ~4 m · < 1 A", "wO"),
]
FY = 218
for x, (ref, spec, wc) in zip(DX, FUSES):
    s.fuse_v(x, FY)
    s.txt(x + 14, FY + 11, ref, "fuse")
    s.txt(x + 14, FY + 27, spec, "note")

# kolumna 1 — step-up w bagażniku
SU_Y, SU_H = 262, 92
s.wire([(DX[0], BUS), (DX[0], FY)], "wire")
s.wire([(DX[0], FY + 24), (DX[0], SU_Y)], "wB")
s.box(COLX[0], SU_Y, CW, SU_H)
s.lines(COLX[0] + CW / 2, SU_Y + 22, [
    ("Step-up 12 → 20 V", "h"),
    ("10 A · 200 W · zalewany, w bagażniku", "t"),
    ("sprawność 90 % (do rachunku)", "t"),
    ("straty 3,3 / 5,0 / 7,2 W", "t"),
    ], step=18)
s.wire([(DX[0], SU_Y + SU_H), (DX[0], 430)], "wB")
s.fuse_v(DX[0], 362)
s.txt(DX[0] + 14, 373, "5 A — wyjście step-upu", "fuse")
s.txt(DX[0] + 14, 389, "4 mm² „+” i „−”, ~4 m · 3,3 A", "note")

# pozostałe kolumny: przewód od szyny przez wkładkę do przetwornicy z przodu
CONV_Y, CONV_H = 430, 64
LOAD_Y, LOAD_H = 520, 172
for i in range(1, 5):
    wc = FUSES[i][2]
    s.wire([(DX[i], BUS), (DX[i], FY)], "wire")
    s.wire([(DX[i], FY + 24), (DX[i], CONV_Y)], wc)
    s.wire([(DX[i], CONV_Y + CONV_H), (DX[i], LOAD_Y)], wc)

# granica bagażnik / przód
ZY = 408
s.line(24, ZY, 1376, ZY, "zone")
s.txt(1360, ZY - 8, "▲ BAGAŻNIK", "zl")
s.txt(1360, ZY + 16, "▼ PRZÓD — deska, ~4 m wiązki", "zl")

# kolumna 1 z przodu — M910q
s.box(COLX[0], CONV_Y, CW, LOAD_Y + LOAD_H - CONV_Y, "boxB")
cx = COLX[0] + CW / 2
s.txt(cx, CONV_Y + 22, "Lenovo M910q — 20 V", "h")
s.txt(cx, CONV_Y + 40, "wtyk z uciętego oryginalnego kabla", "t")
s.lines(COLX[0] + 18, CONV_Y + 66, [
    ("na wtyku → z szyny → przy 12,6 V", "note"),
    "30 W dashboard → 33,3 W → 2,65 A",
    "45 W AA + wideo → 50,0 W → 3,97 A",
    "65 W znamionowo → 72,2 W → 5,73 A",
    "przy 11,0 V i 65 W: 6,57 A (66 % F8)",
    "",
    "limit RAPL nie jest potrzebny",
    "w S3 porty USB są martwe",
    "",
    ("Praca: 2,65 A · szczyt 5,7 A", "tb"),
    ("(6,6 A przy 11,0 V)", "note"),
], step=17)

COLS = [
    # (klasa przetwornicy, nagłówek, podpis, klasa odbiorników, wiersze)
    ("box", "Buck LM2596", "z przodu · napięcie wg panelu", "boxB", [
        ("Wyświetlacze", "h"),
        "panel 10,1\" — podświetlenie",
        "  PWM z Nano #1 przez MOSFET",
        "panel 6,86\" (opcja)",
        "logika i dotyk paneli — po USB",
        "  M910q, więc gasną w S3",
        "",
        ("Praca: ~0,8 A · szczyt 1,5 A", "tb"),
    ]),
    ("box", "Buck MP1584 → 5,0 V", "z przodu · wprost na pin 5V", "boxA", [
        ("Logika — zawsze żywa", "h"),
        "Arduino Nano #1 (wyjścia, PWM)",
        "Arduino Nano #2 (czujniki, zapłon)",
        "HM-10 BLE · RXB6 433 MHz",
        "Nano #2 naciska przycisk M910q",
        "  — musi żyć, gdy USB jest martwe",
        "",
        ("Praca: ~0,2 A · szczyt 0,5 A", "tb"),
        ("(logika razem z cewkami z F11)", "note"),
    ]),
    ("box", "AUX 12 V", "wprost z szyny", "boxA", [
        ("Odbiorniki 12 V", "h"),
        "moduł 9 przekaźników: 4 szyby",
        "  × 2 kierunki, zamek bagażnika",
        "  (spoczynek ~10 mA)",
        "hub USB 7-portowy* z peryferiami:",
        "  Pro Micro, DAC USB, graber AHD",
        "wentylator",
        ("hub: ~0,7 A · szczyt 1,0 A", "tb"),
        ("* hub na F11 wg SCHEMATY §2.4", "note"),
    ]),
    ("boxO", "Wstrzykiwacz VBUS", "12 → 5 V, nastawa 5,1–5,2 V", "boxO", [
        ("Telefon w aucie (opcja)", "h"),
        "Redmi Note 8 Pro — pilot IR",
        "  do budzenia M910q (§14.6)",
        "VBUS od strony M910q odcięty,",
        "  dane zostają na USB",
        "",
        "",
        ("Praca: ~0,5 A · szczyt 0,9 A", "tb"),
        ("postój: 30–100 mA, gdy naładowany", "note"),
    ]),
]
for i, (cc, head, sub, lc, rows) in enumerate(COLS, start=1):
    x = COLX[i]
    s.box(x, CONV_Y, CW, CONV_H, cc)
    s.txt(x + CW / 2, CONV_Y + 26, head, "h")
    s.txt(x + CW / 2, CONV_Y + 46, sub, "t")
    s.box(x, LOAD_Y, CW, LOAD_H, lc)
    y = LOAD_Y + 24
    for it in rows:
        t, c = it if isinstance(it, tuple) else (it, "tl")
        if c == "h":
            s.txt(x + CW / 2, y, t, c)
            y += 22
            continue
        if t:
            s.txt(x + 46, y, t, c)
        y += 16

s.txt(24, 718, "Praca typowo: 2,65 + 0,8 + 0,7 + 0,2 + 0,5 = 4,85 A ≈ 5 A "
      "(≈ 61 W) przy 12,6 V · szczyt ≈ 9,6 A, przy 11,0 V ≈ 10,5 A "
      "(F7 20 A = 1,5 × szczyt, zaokrąglone w górę) — ZB §2.1, §7.4", "tb")

# ---- tabela trzech stanów ---------------------------------------------------
T1Y = 748
s.txt(40, T1Y, "Trzy stany maszyny — pobór z banku (ZB §2.1, straty step-upu §3.2)",
      "hl")
end1 = s.table(40, T1Y + 12, [128, 232, 196, 160, 144],
               [["Stan"], ["Co pobiera"], ["Pobór z banku"], ["Straty step-upu"],
                ["35,7 Ah, 50 % DoD"]],
               [
                   [["Praca", "kluczyk ON"],
                    ["wszystkie odbiorniki,", "telefon się doładowuje"],
                    ["≈ 5 A (≈ 61 W) przy 12,6 V", "szczyt 9,6 A", "10,5 A przy 11,0 V"],
                    ["3,3 W przy 30 W", "5,0 W przy 45 W", "7,2 W przy 65 W"],
                    ["~3,6 h", "silnik zgaszony"]],
                   [["S3", "kluczyk OFF"],
                    ["M910q w S3, Arduino, LVD,", "jałowy step-upu (I_jał);",
                     "USB i panele martwe"],
                    ["200–460 mA", "+ I_jał"],
                    ["I_jał — nieznany,", "zmierz (§3.4)"],
                    ["1,6–3,7 dnia", "bez I_jał"]],
                   [["Wyłączony", "po 2 h, impuls 5 s"],
                    ["przetwornice, Arduino, LVD"],
                    ["50–150 mA", "+ I_jał"],
                    ["I_jał"],
                    ["5,0–14,9 dnia", "bez I_jał"]],
               ], hh=30, rh=58)
s.lines(40, end1 + 20, [
    ("Użyteczne: 17,85 Ah do 50 % DoD, 10,71 Ah do 30 % DoD. Czasy liczone prądem, "
     "bez poprawki Peukerta — realne 3,6 h będzie nieco krótsze.", "note"),
    ("S3 zmierzono, a „Wyłączony” oszacowano jeszcze z poprzednią przetwornicą — "
     "z nową oba wiersze to dolna granica poboru, dopóki nie zmierzysz I_jał.", "note"),
    ("Rozrzut wiersza „Wyłączony” to pobór własny XH-M609. Telefon na buforze "
     "dokłada 30–100 mA (do 0,9 A przez 1–2 h, gdy się ładuje).", "note"),
], step=16)

# ---- tabela postoju 35,7 Ah -------------------------------------------------
T2X = 920
s.txt(T2X, T1Y, "Czas postoju — bank 35,7 Ah (ZB §9.2)", "hl")
end2 = s.table(T2X, T1Y + 12, [88, 116, 78, 78, 80],
               [["Pobór", "całkowity"], ["ponad 60 mA", "logiki"], ["do 30 %", "DoD"],
                ["do 50 %", "DoD"], ["do progu", "LVD"]],
               [
                   [["80 mA"], ["20 mA"], ["~5,6 dnia"], ["~9,3 dnia"], ["~13,9 dnia"]],
                   [["100 mA"], ["40 mA"], ["~4,5 dnia"], ["~7,4 dnia"], ["~11,2 dnia"]],
                   [["130 mA"], ["70 mA"], ["~3,4 dnia"], ["~5,7 dnia"], ["~8,6 dnia"]],
                   [["185 mA"], ["125 mA*"], ["~2,4 dnia"], ["~4,0 dnia"], ["~6,0 dnia"]],
               ], hh=38, rh=26)
s.lines(T2X, end2 + 20, [
    ("„Ponad 60 mA” = XH-M609 + I_jał step-upu + telefon.", "note"),
    ("* sam XH-M609 wg specyfikacji maks. (125 mA).", "note"),
    ("I_jał dodaj do każdego wiersza — np. +50 mA: 80 → 130 mA,", "note"),
    ("  czyli 9,3 → 5,7 dnia do 50 % DoD (ilustracja, nie pomiar).", "note"),
    ("Budzenie RTC co 15 min: +29,8 mA (5 Ah/tydz., §9.3).", "note"),
    ("Do progu LVD ≈ 75 % DoD — rezerwa awaryjna, nie rutyna.", "note"),
], step=16)

# ---- dolny rząd: pobór stały, wzmacniacz, uwagi ----------------------------
BY = 1064
s.txt(40, BY, "Pobór stały bez komputera (ZB §9.1)", "hl")
s.table(40, BY + 12, [266, 154],
        [["Element"], ["Pobór"]],
        [
            [["Arduino Nano #1"], ["~25 mA"]],
            [["HM-10 BLE (nasłuch)"], ["~15 mA"]],
            [["RXB6 433 MHz (nasłuch)"], ["~5 mA"]],
            [["moduł przekaźników (spoczynek)"], ["~10 mA"]],
            [["straty przetwornicy buck"], ["~5 mA"]],
            [["Podsuma: logika i przekaźniki"], ["~60 mA (0,7 W)"]],
            [["XH-M609 (LVD)"], ["20–125 mA, zmierz"]],
            [["I_jał step-upu 20 V"], ["zmierz (§3.4)"]],
            [["telefon na buforze (opcja)"], ["30–100 mA"]],
            [["Nano #2 — poza budżetem §9.1"], ["zmierz"]],
        ], hh=26, rh=21, emph_first=False)

AX, AW = 480, 420
s.box(AX, BY - 16, AW, 250, "boxC")
s.txt(AX + AW / 2, BY + 6, "GAŁĄŹ NIEZALEŻNA — wzmacniacz", "secC")
s.box(AX + 20, BY + 22, 140, 50)
s.txt(AX + 90, BY + 42, "Akumulator", "tbc")
s.txt(AX + 90, BY + 60, "rozruchowy 12 V", "t")
s.wire([(AX + 160, BY + 47), (AX + 260, BY + 47)], "wC")
s.fuse_h(AX + 198, BY + 47)
s.txt(AX + 210, BY + 36, "20–30 A", "fusec")
s.txt(AX + 194, BY + 66, "6 mm²", "note")
s.box(AX + 260, BY + 22, 140, 50, "box")
s.txt(AX + 330, BY + 42, "Wzmacniacz", "tbc")
s.txt(AX + 330, BY + 60, "4 × 50 W RMS", "t")
s.lines(AX + 20, BY + 98, [
    "• gotowy moduł samochodowy, podłączany jak radio",
    "• bezpiecznik przy klemie „+” wg karty modułu",
    "   (zwykle 20–30 A), klasa jak F1 (MIDI/ANL)",
    "• przewód 6 mm², ~4 m · własna masa lokalna",
    "• REM wprost z linii zapłonu (zacisk 87) —",
    "   gra w jeździe, nie w S3",
    "• z buforem łączy go tylko REM i ekran kabla RCA",
    ("Szczyty 20–30 A przekroczyłyby przekaźnik LVD (20 A).", "note"),
], step=16)

NX, NW = 920, 440
s.box(NX, BY - 16, NW, 250, "box")
s.txt(NX + 20, BY + 6, "Zasady", "hl")
s.lines(NX + 20, BY + 30, [
    "• Przekaźnika zapłonu przed odbiornikami nie ma. W torze",
    "   ładowania: K1 (§5.4) i przekaźniki obu XH-M603 (§6.3);",
    "   po stronie odbiorników jedyny przekaźnik to LVD (§7).",
    "• Wkładki odgałęzień (F8–F11, F13, wyjście step-upu) siedzą",
    "   w bagażniku, przy źródle — zwarcie w połowie trasy ma",
    "   przepalić wkładkę, a nie przewód (§8.1).",
    "• Poniżej 11,00 V LVD odcina całą szynę, także logikę.",
    "• Wyłącznik główny S1 to jedyne prawdziwe zero poboru —",
    "   na dłuższy postój rozłącz bank (bez obciążenia).",
    "• Wyświetlacz 1,8\" ESP32: w wariancie testowym z +15;",
    "   zasilanie z bufora to decyzja otwarta (+~60 mA na",
    "   postoju — ZB §9.1, SCHEMATY §11.3).",
    ("Przebiegi uśpienia i wybudzania: ignition_sense.svg", "note"),
    ("Tor ładowania i bank: charging_lvd.svg · power_buffered_m910q.svg", "note"),
], step=15)

s.check_overlaps()
s.check_text()
s.save()
print("ok —", os.path.relpath(OUT))
