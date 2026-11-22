#!/usr/bin/env python3
"""Generator arkusza ładowania i ochrony banku (schematics/charging_lvd.svg).

Rysuje jeden arkusz: tor ładowania z czterema warstwami (K1 → 2 × XY-SK120
→ 2 × XH-M603 → XH-M609), komplet nastaw dla CSB HR1221W (AGM), tabele
kompensacji temperaturowej, żywotność a temperatura i przebieg CC → CV.

Uruchomienie (z katalogu głównego repo):
    python3 schematics/gen_charging_lvd.py

Źródło liczb: docs/ZASILANIE_BUFOROWANE.md §4.1–§4.6, §5.2–§5.8, §6.2–§6.3,
§7.1–§7.4, §8.1–§8.4, §9.4. Po zmianie tamtych tabel popraw ten plik
i wygeneruj SVG ponownie — nie edytuj SVG ręcznie.

Wynik jest deterministyczny (żadnych dat, losowości ani kolejności ze
słowników zależnej od środowiska). Przed zapisem generator sprawdza, że
ramki na siebie nie nachodzą, napisy mieszczą się w swoich ramkach i nie
zachodzą na siebie, przewody nie przechodzą przez napisy, a najmniejszy
stopień pisma ma co najmniej 9 px. Do pomiaru napisów używa Pillow
z fontem DejaVu Sans, jeżeli jest dostępny; bez niego liczy szerokość
zachowawczym przybliżeniem (sama biblioteka standardowa).
"""

import math
import os
import re
import sys

try:
    from PIL import ImageFont
except ImportError:                                           # pragma: no cover
    ImageFont = None

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "charging_lvd.svg")

DEJAVU = {
    False: "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    True: "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
}

W, H = 1600, 1796

STYLE = """  <style>
    .bg   { fill: #ffffff; }
    .box  { fill: #f7f9fb; stroke: #2b3a45; stroke-width: 2; rx: 6; }
    .boxW { fill: #fdf3e6; stroke: #a8621a; stroke-width: 2; rx: 6; }
    .boxA { fill: #eef7ee; stroke: #2d6a2d; stroke-width: 2; rx: 6; }
    .boxB { fill: #eef4fa; stroke: #2b4a8a; stroke-width: 2; rx: 6; }
    .pan  { fill: #fbfcfd; stroke: #c8d2da; stroke-width: 1.5; rx: 6; }
    .rule { stroke: #c8d2da; stroke-width: 1; fill: none; }
    .wire { stroke: #c0392b; stroke-width: 3; fill: none; }
    .gnd  { stroke: #3d4f5c; stroke-width: 2.2; fill: none; }
    .ctrl { stroke: #2b4a8a; stroke-width: 1.8; fill: none; stroke-dasharray: 5 3; }
    .fuse { fill: #ffffff; stroke: #2b3a45; stroke-width: 1.8; }
    .dot  { fill: #c0392b; }
    .ttl  { font-size: 19px; font-weight: bold; fill: #10202b; }
    .sub  { font-size: 12px; fill: #5a6b78; }
    .sec  { font-size: 14px; font-weight: bold; fill: #2b4a8a; }
    .h    { font-size: 13px; font-weight: bold; fill: #10202b; text-anchor: middle; }
    .hl   { font-size: 13px; font-weight: bold; fill: #10202b; }
    .t    { font-size: 11px; fill: #33424e; text-anchor: middle; }
    .tl   { font-size: 11px; fill: #33424e; }
    .tr   { font-size: 11px; fill: #33424e; text-anchor: end; }
    .tb   { font-size: 11px; font-weight: bold; fill: #10202b; }
    .tbc  { font-size: 11px; font-weight: bold; fill: #10202b; text-anchor: middle; }
    .fl   { font-size: 10.5px; font-weight: bold; fill: #10202b; text-anchor: middle; }
    .note { font-size: 10.5px; fill: #6a7a86; }
    .notc { font-size: 10.5px; fill: #6a7a86; text-anchor: middle; }
    .warn { font-size: 11px; font-weight: bold; fill: #a8321a; }
    .warc { font-size: 11px; font-weight: bold; fill: #a8321a; text-anchor: middle; }
    .axis { stroke: #7b8b96; stroke-width: 1.5; fill: none; }
    .refl { stroke: #9aa8b2; stroke-width: 1.2; fill: none; stroke-dasharray: 4 3; }
    .refw { stroke: #a8321a; stroke-width: 1.2; fill: none; stroke-dasharray: 4 3; }
    .cv   { stroke: #2b4a8a; stroke-width: 2.5; fill: none; }
    .cc   { stroke: #c0392b; stroke-width: 2.5; fill: none; }
    .lv   { font-size: 10.5px; fill: #2b4a8a; }
    .lvr  { font-size: 10.5px; fill: #2b4a8a; text-anchor: end; }
    .li   { font-size: 10.5px; fill: #c0392b; }
    .lir  { font-size: 10.5px; fill: #c0392b; text-anchor: start; }
  </style>"""

FRAMES = ("box", "boxW", "boxA", "boxB", "pan")
LINE_CLASSES = ("wire", "gnd", "ctrl", "axis", "refl", "refw", "cv", "cc")


def _class_metrics(css):
    out = {}
    for m in re.finditer(r"\.(\w+)\s*\{([^}]*)\}", css):
        name, body = m.group(1), m.group(2)
        size = re.search(r"font-size:\s*([\d.]+)px", body)
        if size is None:
            continue
        anchor = re.search(r"text-anchor:\s*(\w+)", body)
        out[name] = (float(size.group(1)), "bold" in body,
                     anchor.group(1) if anchor else "start")
    return out


METRICS = _class_metrics(STYLE)
_FONTS = {}


def _measure(s, size, bold):
    """Szerokość napisu w px: Pillow + DejaVu, a bez nich przybliżenie
    zachowawcze (DejaVu Sans ma średnio ok. 0,58 em na znak, bold 0,64)."""
    if ImageFont is not None and os.path.exists(DEJAVU[bold]):
        key = (size, bold)
        if key not in _FONTS:
            _FONTS[key] = ImageFont.truetype(DEJAVU[bold], size)
        return _FONTS[key].getlength(s)
    return len(s) * size * (0.66 if bold else 0.60)


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def fmt(v):
    return f"{v:.1f}".rstrip("0").rstrip(".")


class Sheet:
    def __init__(self):
        self.o = []
        self.frames = []     # (x, y, w, h, cls)
        self.texts = []      # (bbox, s, cls)
        self.segs = []       # (x1, y1, x2, y2, cls)
        self.dy = 0          # bieżące przesunięcie grupy <g> (dla kontroli)
        self.group = False

    def shift(self, dy):
        """Dalsza część arkusza w grupie przesuniętej o dy w dół: pozwala
        powiększyć wyższą sekcję bez przeliczania współrzędnych niższych."""
        self.end_group()
        self.dy = dy
        self.group = True
        self.a(f'  <g transform="translate(0,{fmt(dy)})">')

    def end_group(self):
        if self.group:
            self.a("  </g>")
            self.group = False

    def a(self, s):
        self.o.append(s)

    # ---- ramki i napisy
    def frame(self, x, y, w, h, cls="box"):
        self.frames.append((x, y + self.dy, w, h, cls))
        self.a(f'  <rect class="{cls}" x="{fmt(x)}" y="{fmt(y)}" '
               f'width="{fmt(w)}" height="{fmt(h)}"/>')

    def txt(self, x, y, s, cls="tl"):
        size, bold, anchor = METRICS[cls]
        w = _measure(s, size, bold)
        x0 = x - w / 2 if anchor == "middle" else (x - w if anchor == "end" else x)
        yy = y + self.dy
        self.texts.append(((x0, yy - size * 0.78, x0 + w, yy + size * 0.24), s, cls))
        self.a(f'  <text class="{cls}" x="{fmt(x)}" y="{fmt(y)}">{esc(s)}</text>')

    def lines(self, x, y, items, cls="t", step=18):
        for i, s in enumerate(items):
            if isinstance(s, tuple):
                self.txt(x, y + i * step, s[0], s[1])
            else:
                self.txt(x, y + i * step, s, cls)
        return y + len(items) * step

    def block(self, x, y, w, h, title, items, cls="box"):
        """Ramka z nagłówkiem i wyśrodkowanymi wierszami."""
        self.frame(x, y, w, h, cls)
        self.txt(x + w / 2, y + 22, title, "h")
        self.lines(x + w / 2, y + 41, items, "t", 18)

    # ---- przewody
    def path(self, pts, cls="wire"):
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            self.segs.append((x1, y1 + self.dy, x2, y2 + self.dy, cls))
        d = " ".join(("M" if i == 0 else "L") + f"{fmt(x)} {fmt(y)}"
                     for i, (x, y) in enumerate(pts))
        self.a(f'  <path class="{cls}" d="{d}"/>')

    def dot(self, x, y):
        self.a(f'  <circle class="dot" cx="{fmt(x)}" cy="{fmt(y)}" r="4"/>')

    def fuse_h(self, x, y, ref, below=None):
        """Wkładka w poziomym przewodzie: x — lewy koniec symbolu (40 px)."""
        self.a(f'  <rect class="fuse" x="{fmt(x)}" y="{fmt(y - 7)}" width="40" '
               f'height="14" rx="3"/>')
        self.a(f'  <line class="rule" x1="{fmt(x + 4)}" y1="{fmt(y)}" '
               f'x2="{fmt(x + 36)}" y2="{fmt(y)}"/>')
        self.txt(x + 20, y - 13, ref, "fl")
        if below:
            self.txt(x + 20, y + 22, below, "notc")

    def fuse_v(self, x, y, ref, right=None):
        """Wkładka w pionowym przewodzie: y — górny koniec symbolu (40 px)."""
        self.a(f'  <rect class="fuse" x="{fmt(x - 7)}" y="{fmt(y)}" width="14" '
               f'height="40" rx="3"/>')
        self.txt(x + 14, y + 17, ref, "tb")
        if right:
            self.txt(x + 14, y + 32, right, "note")

    # ---- kontrola geometrii
    def check(self):
        bad = []
        size_min = min(m[0] for k, m in METRICS.items()
                       if any(t[2] == k for t in self.texts))
        if size_min < 9:
            bad.append(f"najmniejszy napis {size_min} px < 9 px")
        # 1) ramki: rozłączne albo całkowicie zagnieżdżone
        for i, a in enumerate(self.frames):
            for b in self.frames[i + 1:]:
                ax, ay, aw, ah, _ = a
                bx, by, bw, bh, _ = b
                inter = ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah
                nested = ((ax <= bx and ay <= by and bx + bw <= ax + aw and by + bh <= ay + ah)
                          or (bx <= ax and by <= ay and ax + aw <= bx + bw
                              and ay + ah <= by + bh))
                if inter and not nested:
                    bad.append(f"ramki nachodzą: {a} x {b}")
        # 2) napisy w arkuszu i w najmniejszej ramce, w której się zaczynają
        for bx, s, cls in self.texts:
            if bx[0] < 4 or bx[2] > W - 4 or bx[1] < 4 or bx[3] > H - 4:
                bad.append(f"poza arkuszem: {s!r}")
                continue
            owners = [f for f in self.frames
                      if f[0] <= bx[0] <= f[0] + f[2] and f[1] <= bx[1] <= f[1] + f[3]]
            if owners:
                fx, fy, fw, fh, fc = min(owners, key=lambda f: f[2] * f[3])
                if bx[0] < fx + 4 or bx[2] > fx + fw - 4 or bx[3] > fy + fh - 3:
                    bad.append(f"wychodzi z ramki {fc}@({fx},{fy}): {s!r}")
            for fx, fy, fw, fh, fc in self.frames:
                inside_start = fx <= bx[0] <= fx + fw and fy <= bx[1] <= fy + fh
                if inside_start:
                    continue
                if bx[0] < fx + fw and fx < bx[2] and bx[1] < fy + fh and fy < bx[3]:
                    # napis nad ramką-rodzicem jest w porządku, jeśli cała ta
                    # ramka zawiera ramkę-właściciela
                    if owners and any(o[0] >= fx and o[1] >= fy and
                                      o[0] + o[2] <= fx + fw and o[1] + o[3] <= fy + fh
                                      for o in owners):
                        continue
                    bad.append(f"napis wchodzi w ramkę {fc}@({fx},{fy}): {s!r}")
        # 3) napisy nie zachodzą na siebie
        for i, (a, sa, _) in enumerate(self.texts):
            for b, sb, _ in self.texts[i + 1:]:
                if a[0] < b[2] - 0.5 and b[0] < a[2] - 0.5 and a[1] < b[3] - 0.5 \
                        and b[1] < a[3] - 0.5:
                    bad.append(f"napisy zachodzą: {sa!r} x {sb!r}")
        # 4) przewody i krzywe nie przechodzą przez napisy
        for x1, y1, x2, y2, cls in self.segs:
            for bx, s, _ in self.texts:
                if _seg_hits_rect(x1, y1, x2, y2, (bx[0] - 2, bx[1] - 2,
                                                   bx[2] + 2, bx[3] + 2)):
                    bad.append(f"linia {cls} ({x1},{y1})-({x2},{y2}) przez napis {s!r}")
        if bad:
            raise SystemExit("arkusz do poprawki:\n  " + "\n  ".join(bad))

    def save(self, path):
        self.end_group()
        body = "\n".join(self.o)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(body + "\n</svg>\n")


def _seg_hits_rect(x1, y1, x2, y2, r):
    rx0, ry0, rx1, ry1 = r
    # Liang–Barsky
    dx, dy = x2 - x1, y2 - y1
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x1 - rx0), (dx, rx1 - x1), (-dy, y1 - ry0), (dy, ry1 - y1)):
        if p == 0:
            if q < 0:
                return False
        else:
            t = q / p
            if p < 0:
                t0 = max(t0, t)
            else:
                t1 = min(t1, t)
            if t0 > t1:
                return False
    return True


def table(sh, x, y, w, cols, header, rows, row_h=20, aligns=None):
    """Tabela w ramce rodzica: cols — przesunięcia kolumn od x; zwraca y końca."""
    aligns = aligns or ["tl"] * len(cols)
    sh.a(f'  <line class="rule" x1="{fmt(x)}" y1="{fmt(y)}" x2="{fmt(x + w)}" y2="{fmt(y)}"/>')
    for cx, s in zip(cols, header):
        sh.txt(x + cx, y + 18, s, "tb")
    y += 26
    sh.a(f'  <line class="rule" x1="{fmt(x)}" y1="{fmt(y)}" x2="{fmt(x + w)}" y2="{fmt(y)}"/>')
    for row in rows:
        n = max(len(c) if isinstance(c, list) else 1 for c in row)
        for cx, cell, al in zip(cols, row, aligns):
            cell = cell if isinstance(cell, list) else [cell]
            for k, s in enumerate(cell):
                cls = al
                if isinstance(s, tuple):
                    s, cls = s
                sh.txt(x + cx, y + 15 + k * 15, s, cls)
        y += row_h + (n - 1) * 15
    sh.a(f'  <line class="rule" x1="{fmt(x)}" y1="{fmt(y)}" x2="{fmt(x + w)}" y2="{fmt(y)}"/>')
    return y


def build():
    sh = Sheet()
    sh.a(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
         f'viewBox="0 0 {W} {H}" font-family="DejaVu Sans, Verdana, sans-serif">')
    sh.a("  <title>BCM v8.5 — Ładowanie banku CSB HR1221W (2 × XY-SK120), "
         "blokada przeładowania (2 × XH-M603) i LVD (XH-M609)</title>")
    sh.a(STYLE)
    sh.a(f'  <rect class="bg" x="0" y="0" width="{W}" height="{H}"/>')
    sh.txt(24, 32, "Ładowanie banku CSB HR1221W, blokada przeładowania i odcięcie LVD", "ttl")
    sh.txt(24, 52, "Cztery niezależne warstwy: K1 (rozdział od instalacji) · 2 × XY-SK120 "
           "(CC-CV) · 2 × XH-M603 (nadnapięcie) · XH-M609 (LVD). Liczby: "
           "ZASILANIE_BUFOROWANE.md §4.1–§9.4 — tekst ma pierwszeństwo przed rysunkiem.", "sub")
    sh.a('  <line class="rule" x1="24" y1="64" x2="1576" y2="64"/>')

    # ================================================================ 1. tor
    sh.txt(24, 88, "1  Tor ładowania — od klemy rozruchowego do banku w bagażniku (§5.4, §8.1)", "sec")

    cy = 251                      # oś toru wejściowego
    b1, b2 = 195, 307             # osie gałęzi ładowarek

    sh.block(24, 196, 170, 110, "Akumulator", [
        "rozruchowy 12 V",
        "jazda: 13,4–14,2 V",
        "postój: 12,4–12,7 V",
    ])
    sh.txt(109, 296, "F1 ≤ 30 cm od klemy „+”", "notc")
    sh.path([(194, cy), (286, cy)])
    sh.fuse_h(212, cy, "F1 20 A", "6 mm², ~5 m")
    sh.txt(232, cy - 27, "MIDI/ANL", "fl")

    sh.block(286, 196, 176, 110, "Ochrona wejścia", [
        "TVS SMCJ20CA (dwukier.)",
        "C1 470 µF / 35 V low-ESR",
        "szpilki i tętnienia —",
        "load dumpu nie przeżyje",
    ])
    sh.path([(462, cy), (492, cy)])

    sh.block(492, 180, 196, 142, "WARSTWA 0 — K1", [
        "przekaźnik 30 A SPDT",
        "rozwarty przy zgaszonym",
        "silniku: rozruchowy",
        "nie zasila banku",
        ("1N4007 na cewce", "notc"),
    ])
    sh.frame(492, 96, 196, 56, "boxB")
    sh.txt(590, 116, "Zapłon albo D+ alternatora", "tbc")
    sh.txt(590, 134, "D+ lepsze: „alternator ładuje”", "notc")
    sh.path([(590, 152), (590, 180)], "ctrl")
    sh.txt(598, 170, "FK 1 A · 0,75 mm²", "note")

    # rozgałęzienie na dwie ładowarki
    sh.path([(688, cy), (712, cy)])
    sh.path([(712, b1), (712, b2)])
    sh.dot(712, cy)
    for n, by in (("1", b1), ("2", b2)):
        sh.path([(712, by), (740, by)])
        sh.block(740, by - 45, 214, 90, f"WARSTWA 1 — XY-SK120 #{n}", [
            "buck-boost CC-CV",
            "CV 14,40 V · CC 5,0 A",
            "OVP 15,0 V · LVP 12,8 V",
        ], "boxB")
        sh.path([(954, by), (986, by)])
        sh.block(986, by - 45, 214, 90, f"WARSTWA 2 — XH-M603 #{n}", [
            "rozwarcie 15,30 V",
            "powrót 14,00 V",
            "zwłoka 1–3 s · ≤ 8 A",
        ], "boxW")
        sh.path([(1200, by), (1272, by)])
        sh.fuse_h(1216, by, f"FC{n} 7,5 A")
    sh.txt(970, 255, "2,5 mm² — K1 → XY-SK120 → XH-M603 → FC: obie gałęzie "
           "równej długości (§5.3, §8.2)", "notc")
    sh.path([(1272, b1), (1272, b2)])
    sh.dot(1272, cy)
    sh.path([(1272, cy), (1366, cy)])
    sh.fuse_h(1296, cy, "F12 15 A", "4 mm²")
    sh.txt(1319, 220, "≈ 10 A", "notc")

    sh.block(1366, 150, 210, 204, "Bank 7 × HR1221W", [
        "CSB, VRLA AGM, 12 V",
        "7 × 5,1 Ah = 35,7 Ah",
        "równolegle — nadal 12 V",
        "kosz L: #1–#4 · kosz P: #5–#7",
        "FB1…FB7 10 A na „+”",
        "FLRY-B 2,5 mm², równe",
        "łącznik koszy 6 mm² OFC",
        ("odbiór: „+” z L+, „−” z P−", "warc"),
    ], "boxA")

    sh.path([(1471, 354), (1471, 410)])
    sh.fuse_v(1471, 362, "F7 20 A", "6 mm²")
    sh.block(1366, 410, 210, 100, "WARSTWA 3 — LVD", [
        "XH-M609, przekaźnik 20 A",
        "odcięcie 11,00 V",
        "powrót 12,60 V",
    ], "boxW")
    sh.path([(1471, 510), (1471, 540)])
    sh.txt(1481, 529, "4 mm²", "note")
    sh.frame(1366, 540, 210, 142, "box")
    sh.txt(1471, 562, "Szyna buforowana", "h")
    sh.lines(1378, 581, [
        "F8 10 A — step-up 12 → 20 V",
        "F9 2 A — LM2596 (ekrany)",
        "F10 3 A — MP1584 (logika)",
        "F11 5 A — AUX 12 V",
        "F13 2 A — telefon (opcja)",
    ], "tl", 17)
    sh.txt(1378, 672, "szczyt ~10,5 A (§7.4)", "note")

    # masa — jeden punkt przy banku, P− dochodzi do niego tylko przez S1
    sh.frame(24, 366, 1316, 80, "pan")
    sh.lines(36, 382, [
        "Masa (§5.6, §8.3, §8.4): XY-SK120 nie jest izolowana — IN− = OUT−. "
        "Masy obu ładowarek, obu XH-M603,",
        "TVS, C1 i cewki K1 (zacisk 85) idą do JEDNEGO punktu masy przy banku "
        "(osobny blok, z P− przez S1),",
        "a z niego jeden przewód 6 mm² do nadwozia. Bez osobnej masy do klemy "
        "„−” rozruchowego (to byłaby pętla).",
        ("S1 rozłączaj tylko bez obciążenia. Wzmacniacz: osobna gałąź "
         "z rozruchowego, poza LVD.", "warn"),
    ], "tl", 15)
    gy = 406                                  # oś łańcucha masy
    sh.frame(866, 388, 70, 36, "boxA")
    sh.txt(901, gy + 4, "blok P−", "tbc")
    sh.path([(936, gy), (982, gy)], "gnd")
    sh.txt(959, gy - 6, "6 mm²", "notc")
    sh.frame(982, 386, 112, 40, "boxW")
    sh.txt(1038, 402, "S1 rozłącznik", "tbc")
    sh.txt(1038, 417, "masy 100 A", "notc")
    sh.path([(1094, gy), (1140, gy)], "gnd")
    sh.txt(1117, gy - 6, "6 mm²", "notc")
    sh.frame(1140, 386, 112, 40, "box")
    sh.txt(1196, 402, "punkt masy", "tbc")
    sh.txt(1196, 417, "osobny blok", "notc")
    sh.path([(1252, gy), (1300, gy), (1300, 416)], "gnd")
    sh.txt(1276, gy - 6, "6 mm²", "notc")
    for k, half in enumerate((11, 7, 3)):
        sh.path([(1300 - half, 416 + 4 * k), (1300 + half, 416 + 4 * k)], "gnd")
    sh.txt(1300, 440, "nadwozie", "notc")

    # ================================================================ 2. warstwy
    sh.shift(40)
    sh.txt(24, 436, "2  Co robi każda warstwa — działają niezależnie od siebie", "sec")
    cards = [
        ("WARSTWA 0 — K1 (§5.4)", "box", [
            "Rozłącza tor ładowania od instalacji,",
            "gdy silnik nie pracuje. Bez K1 wejścia",
            "ładowarek wisiałyby na rozruchowym.",
            "Cewka z zapłonu: kluczyk na ON bez",
            "silnika = ok. 13,0 A z rozruchowego.",
            "Cewka z D+ tego unika; LVP 12,8 V to",
            "druga bariera (tuż po jeździe nie blokuje",
            "— ładunek powierzchniowy 12,9–13,1 V).",
            "Pobór toru: 11,9 A przy 13,8 V (jazda).",
        ]),
        ("WARSTWA 1 — 2 × XY-SK120 (§5.2–§5.3)", "boxB", [
            "Buck-boost: z 12,5–14,7 V robi 14,40 V",
            "w obie strony; CC działa zawsze.",
            "Dwie, bo jedna ledwo pokrywa obciążenie",
            "(netto ≈ −1…+1 A). Dwie: 10 A, z czego",
            "≈ 5 A idzie do banku (≈ 0,7 A/pakiet).",
            "Oba CV ±0,02 V, nastawiane bez banku;",
            "„wyjście po włączeniu zasilania”: ON.",
        ]),
        ("WARSTWA 2 — 2 × XH-M603 (§6.2–§6.3)", "boxW", [
            "Mierzy napięcie banku, nie ładowarki.",
            "Przy przebiciu ładowarki rozwiera przy",
            "15,30 V — oba moduły, całe ładowanie.",
            "Po jednym na ładowarkę: płytka ≤ 8 A,",
            "przez każdą płynie 5 A (62 %).",
            "Nie łapie szpilek — od tego jest TVS.",
            "Test „12,6 V tylko na OUT” — §6.4 pkt 6.",
        ]),
        ("WARSTWA 3 — XH-M609 (§7.2–§7.4)", "boxW", [
            "Odcina całą szynę buforowaną przy",
            "11,00 V, wraca dopiero przy 12,60 V.",
            "Histereza obowiązkowa: bank po odcięciu",
            "odbija o 0,3–0,5 V. Przerywa „+”.",
            "Przekaźnik 20 A wobec szczytu 10,5 A.",
            "Niepewny przy 11 V → próg 11,5 V.",
            "Pobór własny: do zmierzenia (< 1,5 W).",
        ]),
    ]
    cw, gap = 314, 20
    for i, (title, cls, items) in enumerate(cards):
        x = 24 + i * (cw + gap)
        sh.frame(x, 448, cw, 200, cls)
        sh.txt(x + cw / 2, 470, title, "h")
        sh.lines(x + 12, 490, items, "tl", 17)

    # float — jak ZB radzi sobie bez stopnia float
    sh.frame(24, 660, 1316, 80, "pan")
    sh.txt(36, 680, "Float a XY-SK120: moduł nie ma osobnego stopnia float ani "
           "końca ładowania prądem — trzyma CV przez całą jazdę (§5.5).", "warn")
    sh.lines(36, 698, [
        "ZB to obchodzi: napięcie jest podawane tylko podczas jazdy (K1, LVP), "
        "CV przestawiasz sezonowo (tabela 3c), OVP modułu 15,0 V to warstwa wewnętrzna,",
        "a XH-M603 15,30 V łapie awarię modułu. 13,65 V to środek katalogowego float "
        "przy 25 °C; ZB nie ustawia go wprost — dla długich tras zamiast 14,40 V",
        "daje CV w zakresie float: 13,80 V (25 °C) albo 13,40 V (40 °C).",
    ], "tl", 16)

    # ================================================================ 3. nastawy
    sh.shift(80)
    sh.txt(24, 722, "3  Nastawy i tabele — CSB HR1221W (AGM), bank 7 × 5,1 Ah", "sec")

    # 3a — tabela nastaw
    x0, y0, w0 = 24, 734, 640
    sh.frame(x0, y0, w0, 548, "pan")
    sh.txt(x0 + w0 / 2, y0 + 22, "3a  Komplet nastaw", "h")
    rows = [
        ["Absorpcja (CV), obie XY-SK120", "14,40 V @ 25 °C", "1", "§4.4, §5.2"],
        ["Float — katalog 13,5–13,8 V", "13,65 V @ 25 °C", "—", "§4.4, §5.5"],
        ["Prąd CC, każda XY-SK120", "5,0 A (≈ 72 W)", "1", "§5.2"],
        ["Razem z ładowarek / netto do banku", "10 A / ≈ 5 A", "1", "§5.3"],
        ["Sufit katalogowy CSB", "2,1 A × 7 = 14,7 A", "—", "§4.1, §4.2"],
        ["Różnica CV między modułami", "≤ ±0,02 V", "1", "§5.3"],
        ["OVP modułu (wyjście)", "15,0 V", "1", "§5.5"],
        ["LVP modułu (jeśli regulowane)", "12,8 V (12,7 V)", "0/1", "§5.4"],
        ["XH-M603 — rozwarcie", "15,30 V", "2", "§6.2"],
        ["XH-M603 — powrót", "14,00 V", "2", "§6.2"],
        ["XH-M603 — zwłoka / prąd płytki", "1–3 s / ≤ 8 A", "2", "§6.2"],
        ["LVD XH-M609 — odcięcie", "11,00 V", "3", "§7.2"],
        ["LVD XH-M609 — powrót", "12,60 V", "3", "§7.2"],
        ["Kompensacja absorpcji", "−30 mV/°C", "ręczna", "§4.5"],
        ["Kompensacja float", "−18 mV/°C", "ręczna", "§4.5"],
        ["F1 / FK / FC1, FC2", "20 A / 1 A / 7,5 A", "—", "§8.1"],
        ["F12 / F7 / FB1…FB7", "15 A / 20 A / 10 A", "—", "§8.1"],
    ]
    y = table(sh, x0 + 14, y0 + 36, w0 - 28, [6, 262, 432, 506],
              ["Parametr", "Wartość", "Warstwa", "ZB"], rows, row_h=21)
    sh.txt(x0 + 20, y + 20, "HR1221W to AGM — 14,40 V jest prawidłowe, nie za dużo.", "warn")
    sh.lines(x0 + 20, y + 38, [
        "Napięcia nie zależą od liczby pakietów: równolegle sumuje się pojemność",
        "i prąd, napięcie zostaje 12 V. Progi 15,30 / 14,00 V i 11,00 / 12,60 V",
        "obowiązują dosłownie. F1, F7 i F12 w klasie MIDI/AMI albo ANL (≥ 2,5 kA).",
    ], "note", 15)

    # 3b — kompensacja §4.5
    x1, w1 = 684, 420
    sh.frame(x1, y0, w1, 266, "pan")
    sh.txt(x1 + w1 / 2, y0 + 22, "3b  Napięcie a temperatura (§4.5)", "h")
    rows = [
        ["−10 °C", "15,00 V *", "14,28 V"],
        ["0 °C", "15,00 V *", "14,10 V"],
        ["+15 °C", "14,70 V", "13,83 V"],
        [("+25 °C", "tb"), ("14,40 V", "tb"), ("13,65 V", "tb")],
        ["+40 °C", "13,95 V", "13,38 V"],
        ["+50 °C", "13,65 V", "13,20 V"],
    ]
    rows = [[c if isinstance(c, list) else [c] for c in r] for r in rows]
    y = table(sh, x1 + 14, y0 + 36, w1 - 28, [6, 130, 270],
              ["Temperatura", "Absorpcja", "Float"], rows, row_h=21)
    sh.lines(x1 + 20, y + 18, [
        "−30 mV/°C (absorpcja), −18 mV/°C (float), od 25 °C.",
        "* obliczeniowo 15,15 V (0 °C) i 15,45 V (−10 °C) — ograniczone",
        "do 15,0 V, górnej granicy katalogowej CSB.",
    ], "note", 15)

    # 3c — sezonowe CV §5.5
    x2, w2 = 1124, 452
    sh.frame(x2, y0, w2, 266, "pan")
    sh.txt(x2 + w2 / 2, y0 + 22, "3c  Nastawa CV — sezonowo, ręcznie (§5.5)", "h")
    rows = [
        [("14,40 V", "tb"), ["ok. 25 °C i zima; jazdy do ~2 h", "dziennie — domyślnie"]],
        [("13,80 V", "tb"), ["ok. 25 °C i częste trasy po kilka h", "(górna granica float przy 25 °C)"]],
        [("13,95 V", "tb"), ["lato, gorący bagażnik ~40 °C,", "typowe jazdy (= absorpcja 40 °C)"]],
        [("13,40 V", "tb"), ["lato ~40 °C i częste długie trasy", "(≈ float 40 °C: 13,38 V)"]],
    ]
    y = table(sh, x2 + 14, y0 + 36, w2 - 28, [6, 96], ["CV", "Kiedy"], rows, row_h=20)
    sh.lines(x2 + 20, y + 18, [
        "Temperatura pakietów w bagażniku podczas jazdy, nie powietrza.",
    ], "note", 15)
    sh.txt(x2 + 20, y + 36, "14,10 V to absorpcja ~35 °C — nie „na całe lato”.", "warn")

    # 3d — żywotność §4.6
    sh.frame(x1, 1016, w1 + 20 + w2, 266, "pan")
    sh.txt(x1 + (w1 + 20 + w2) / 2, 1038, "3d  Żywotność a temperatura (§4.6)", "h")
    rows = [
        ["kabina (wariant poprzedniego wydania)", "2–4 lata"],
        [("bagażnik — przyjęte", "tb"), ("1,5–3 lata", "tb")],
        ["przy tunelu wydechowym", "< 1,5 roku"],
    ]
    y = table(sh, x1 + 14, 1052, 400, [6, 300], ["Miejsce montażu", "Żywotność"],
              rows, row_h=21)
    sh.lines(x1 + 20, y + 20, [
        "Katalog: 3–5 lat pracy buforowej przy 25 °C.",
        "Każde +10 °C mniej więcej POŁOWI ten czas.",
        ("To temperatura, a nie cyklowanie, wyznacza", "tb"),
        ("życie tego banku.", "tb"),
    ], "tl", 17)
    sh.lines(x1 + 448, 1068, [
        ("Cykle: > 260 przy 100 % DoD,", "tl"),
        ("grubo ponad 500 przy 50 % DoD.", "tl"),
        ("~50 cykli rocznie wyczerpie się", "tl"),
        ("po dekadzie — kalendarz i ciepło", "tl"),
        ("znacznie wcześniej.", "tl"),
        ("", "tl"),
        ("Żeby nie tracić więcej niż trzeba:", "tb"),
        ("• kosze otwarte od góry, bez szczelnej", "tl"),
        ("\u00a0\u00a0pokrywy i bez bagażu na nich,", "tl"),
        ("• przetwornica i dwie XY-SK120 (~10 W", "tl"),
        ("\u00a0\u00a0strat każda) obok koszy, nie nad nimi,", "tl"),
        ("• latem obniż CV (tabela 3c).", "tl"),
    ], "tl", 16)

    # ================================================================ 4. krzywa
    cx0, cyy, cw0, ch0 = 24, 1300, 1552, 400
    sh.frame(cx0, cyy, cw0, ch0, "pan")
    sh.txt(cx0 + cw0 / 2, cyy + 22, "4  Przebieg ładowania CC → CV (bez float) — "
           "po postoju z progu LVD (§5.3, §5.5, §9.4)", "h")
    px0, px1 = 120, 1360           # oś czasu
    vy = lambda v: 1480 - (v - 12.0) * 37.0        # napięcie: 12,0 V → 1480
    iy = lambda a: 1660 - a * 11.0                  # prąd: 0 A → 1660
    t_cc, t_end = 640, 1160                         # koniec CC, zgaszenie silnika
    # osie
    sh.path([(px0, 1480), (px0, 1344)], "axis")
    sh.path([(px0, 1480), (px1, 1480)], "axis")
    sh.path([(px0, 1660), (px0, 1534)], "axis")
    sh.path([(px0, 1660), (px1, 1660)], "axis")
    for v in (12.0, 13.0, 14.0, 15.0):
        sh.txt(px0 - 8, vy(v) + 4, f"{v:.1f}".replace(".", ",") + " V", "tr")
    for a in (0, 5, 10):
        sh.txt(px0 - 8, iy(a) + 4, f"{a} A", "tr")
    # linie odniesienia
    sh.path([(px0, vy(15.30)), (px1, vy(15.30))], "refw")
    sh.txt(px1 + 10, vy(15.30) + 4, "15,30 V — XH-M603", "warn")
    sh.path([(px0, vy(14.40)), (t_cc, vy(14.40))], "refl")
    sh.path([(px0, vy(13.65)), (px1, vy(13.65))], "refl")
    sh.txt(px1 + 10, vy(13.65) + 4, "13,65 V — float @ 25 °C", "note")
    sh.txt(px1 + 10, vy(13.65) + 18, "(moduł go nie ustawia, §5.5)", "note")
    # napięcie banku
    pts = []
    for k in range(0, 41):
        t = px0 + (t_cc - px0) * k / 40
        u = k / 40
        v = 12.25 + (14.40 - 12.25) * (0.35 * u + 0.65 * u ** 3)
        pts.append((round(t, 1), round(vy(v), 1)))
    pts.append((t_end, vy(14.40)))
    for k in range(1, 21):
        t = t_end + (px1 - 20 - t_end) * k / 20
        v = 12.85 + (14.40 - 12.85) * math.exp(-k / 3.0)
        pts.append((round(t, 1), round(vy(v), 1)))
    sh.path(pts, "cv")
    sh.txt(260, 1436, "napięcie banku rośnie", "lv")
    sh.txt(t_cc + 20, vy(14.40) - 8, "CV 14,40 V — absorpcja trwa do zgaszenia silnika", "lv")
    sh.txt(t_end + 30, 1465, "napięcie spoczynkowe banku", "lv")
    # prąd do banku (netto)
    pts = [(px0, iy(5.0)), (t_cc, iy(5.0))]
    for k in range(1, 31):
        t = t_cc + (t_end - t_cc) * k / 30
        a = 5.0 * math.exp(-k / 8.0)
        pts.append((round(t, 1), round(iy(a), 1)))
    pts += [(t_end, iy(0)), (px1 - 20, iy(0))]
    sh.path(pts, "cc")
    sh.path([(px0, iy(10.0)), (t_cc, iy(10.0))], "refl")
    sh.txt(150, iy(10.0) - 6, "wyjście 2 × XY-SK120 = 10 A (CC): odbiorniki ≈ 5 A + bank ≈ 5 A",
           "note")
    sh.txt(150, iy(5.0) - 6, "netto do banku ≈ 5 A (CC)", "li")
    sh.txt(t_cc + 140, 1626, "prąd maleje — XY-SK120 nie kończy ładowania prądem", "li")
    # znaczniki czasu
    for t in (t_cc, t_end):
        sh.path([(t, 1344), (t, 1660)], "refl")
    sh.txt(t_cc - 8, 1502, "koniec CC: ≈ 5,4 h z progu LVD", "tr")
    sh.txt(t_cc - 8, 1516, "(26,78 Ah przy netto ≈ 5 A)", "tr")
    sh.txt(t_end + 8, 1502, "silnik zgaszony: K1 rozwiera,", "tl")
    sh.txt(t_end + 8, 1516, "ładowanie stoi do następnej jazdy", "tl")
    sh.txt(px1 - 4, 1678, "czas jazdy →", "tr")
    sh.txt(px0 + 4, 1688, "Do pełna realnie 7,0–8,0 h jazdy (CC × 1,3–1,5); "
           "z 50 % DoD 4,6–5,4 h. Kontrola CV na zaciskach banku — pod koniec "
           "absorpcji, przy prądzie < 1 A (§5.3).", "note")

    sh.check()
    return sh


def main():
    sh = build()
    sh.save(OUT)
    print(f"zapisano {os.path.relpath(OUT)}")


if __name__ == "__main__":
    sys.exit(main())
