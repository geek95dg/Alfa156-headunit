#!/usr/bin/env python3
"""Generator arkusza blokowego toru zasilania wariantu testowo-rozwojowego.

Rysuje:
    schematics/power_test_build.svg — przegląd blokowy: ładowanie z dwiema
    XY-SK120, bank 7 × HR1221W w dwóch koszach, LVD, rozłącznik masy,
    trzy przetwornice i sterowanie przyciskiem M910q.

Uruchomienie (z katalogu głównego repo):
    python3 schematics/gen_power_test_build.py

Źródła: docs/WDROZENIE_TESTOWE.md §3, docs/SCHEMATY_POLACZEN.md §10,
docs/ZASILANIE_BUFOROWANE.md (przy rozbieżności obowiązuje ZB). Schemat
komponentowy tego samego toru: schematic_test_power.svg. Po zmianie
dokumentów popraw ten plik i wygeneruj SVG ponownie — nie edytuj SVG ręcznie.

Generator jest deterministyczny i przed zapisem sprawdza geometrię: ramki
nie nachodzą na siebie, napisy mieszczą się w swoich ramkach i nie wchodzą
na siebie ani na przewody, przewody nie przechodzą przez cudze ramki.
"""

import os
import sys

try:
    from PIL import ImageFont
except ImportError:                                           # pragma: no cover
    ImageFont = None

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "power_test_build.svg")

DEJAVU = {
    False: "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    True: "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
}

W, H = 1200, 1800

STYLE = """  <style>
    .bg   { fill: #ffffff; }
    .box  { fill: #f7f9fb; stroke: #2b3a45; stroke-width: 2; rx: 6; }
    .boxC { fill: #eef7ee; stroke: #2d6a2d; stroke-width: 2; rx: 6; }
    .boxB { fill: #fdf6e6; stroke: #9a6b12; stroke-width: 2; rx: 6; }
    .boxL { fill: #eef2fa; stroke: #2b4a8a; stroke-width: 2; rx: 6; }
    .boxS { fill: #f6f0fa; stroke: #6a3d8a; stroke-width: 2; rx: 6; }
    .boxW { fill: #fdecea; stroke: #a8321a; stroke-width: 2; rx: 6; }
    .pack { fill: #ffffff; stroke: #9a6b12; stroke-width: 1.5; rx: 4; }
    .note { fill: #fbfcfd; stroke: #c8d2da; stroke-width: 1.5; rx: 6; }
    .wire { stroke: #c0392b; stroke-width: 3; fill: none; }
    .wthin{ stroke: #c0392b; stroke-width: 1.8; fill: none; }
    .wgnd { stroke: #3d4f5c; stroke-width: 3; fill: none; }
    .wusb { stroke: #2b4a8a; stroke-width: 2; fill: none; stroke-dasharray: 6 4; }
    .wsig { stroke: #6a3d8a; stroke-width: 2; fill: none; stroke-dasharray: 6 4; }
    .zone { stroke: #8b9aa6; stroke-width: 1.5; fill: none; stroke-dasharray: 8 5; }
    .dot  { fill: #c0392b; }
    .ttl  { font-size: 19px; font-weight: bold; fill: #10202b; }
    .sub  { font-size: 12px; fill: #5a6b78; }
    .h    { font-size: 13.5px; font-weight: bold; fill: #10202b; text-anchor: middle; }
    .t    { font-size: 11.5px; fill: #33424e; text-anchor: middle; }
    .tl   { font-size: 11.5px; fill: #33424e; }
    .tb   { font-size: 11.5px; font-weight: bold; fill: #10202b; }
    .tbm  { font-size: 11.5px; font-weight: bold; fill: #10202b; text-anchor: middle; }
    .sec  { font-size: 13.5px; font-weight: bold; }
    .nh   { font-size: 12.5px; font-weight: bold; fill: #10202b; }
    .nt   { font-size: 11px; fill: #4a5a66; }
    .ntm  { font-size: 11px; fill: #4a5a66; text-anchor: middle; }
    .fuse { font-size: 11px; font-weight: bold; fill: #a8321a; }
    .fusem{ font-size: 11px; font-weight: bold; fill: #a8321a; text-anchor: middle; }
    .fusee{ font-size: 11px; font-weight: bold; fill: #a8321a; text-anchor: end; }
    .wl   { font-size: 11px; fill: #4a5a66; }
    .wle  { font-size: 11px; fill: #4a5a66; text-anchor: end; }
    .zl   { font-size: 11px; font-weight: bold; fill: #6a7a86; }
    .foot { font-size: 10.5px; fill: #6a7a86; }
  </style>"""

# klasa -> (rozmiar px, pogrubienie, wyrównanie)
METRICS = {
    "ttl": (19, True, "start"), "sub": (12, False, "start"),
    "h": (13.5, True, "middle"), "t": (11.5, False, "middle"),
    "tl": (11.5, False, "start"), "tb": (11.5, True, "start"),
    "tbm": (11.5, True, "middle"), "sec": (13.5, True, "start"),
    "nh": (12.5, True, "start"), "nt": (11, False, "start"),
    "ntm": (11, False, "middle"), "fuse": (11, True, "start"),
    "fusem": (11, True, "middle"), "fusee": (11, True, "end"),
    "wl": (11, False, "start"), "wle": (11, False, "end"),
    "zl": (11, True, "start"), "foot": (10.5, False, "start"),
}

SEC_COLOR = {"C": "#2d6a2d", "B": "#9a6b12", "L": "#2b4a8a", "S": "#6a3d8a"}

_FONTS = {}


def measure(s, size, bold):
    if ImageFont is not None and os.path.exists(DEJAVU[bold]):
        key = (size, bold)
        if key not in _FONTS:
            # layout_engine BASIC: wynik nie zależy od zainstalowanego raqm
            _FONTS[key] = ImageFont.truetype(
                DEJAVU[bold], size, layout_engine=ImageFont.Layout.BASIC)
        return _FONTS[key].getlength(s)
    # zapas, gdy nie ma czym mierzyć: DejaVu Sans jest szeroki
    return len(s) * size * (0.66 if bold else 0.60)


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class Sheet:
    def __init__(self):
        self.out = []          # elementy SVG w kolejności rysowania
        self.rects = []        # (x, y, w, h, nazwa, rodzic)
        self.texts = []        # (bbox, napis, ramka-właściciel albo None)
        self.wires = []        # (x1, y1, x2, y2, klasa, połączone ramki)

    # ---- prymitywy
    def rect(self, x, y, w, h, cls, name, parent=None):
        self.out.append(f'  <rect class="{cls}" x="{x}" y="{y}" width="{w}" height="{h}"/>')
        self.rects.append((x, y, w, h, name, parent))
        return name

    def text(self, x, y, s, cls, owner=None, fill=None):
        size, bold, anchor = METRICS[cls]
        w = measure(s, size, bold)
        x0 = x - w / 2 if anchor == "middle" else (x - w if anchor == "end" else x)
        bbox = (x0, y - size * 0.78, x0 + w, y + size * 0.24)
        self.texts.append((bbox, s, owner))
        f = f' fill="{fill}"' if fill else ""
        self.out.append(f'  <text class="{cls}" x="{x}" y="{y}"{f}>{esc(s)}</text>')

    def path(self, pts, cls, ends=()):
        d = "M" + " L".join(f"{x} {y}" for x, y in pts)
        self.out.append(f'  <path class="{cls}" d="{d}"/>')
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            self.wires.append((x1, y1, x2, y2, cls, tuple(ends)))

    def dot(self, x, y):
        self.out.append(f'  <circle class="dot" cx="{x}" cy="{y}" r="4.5"/>')

    def comment(self, s):
        self.out.append(f"\n  <!-- {s} -->")

    # ---- bloki
    def block(self, x, y, w, h, cls, name, head, lines=(), step=18, head_dy=23):
        self.rect(x, y, w, h, cls, name)
        cx = x + w / 2
        self.text(_n(cx), y + head_dy, head, "h", name)
        for i, s in enumerate(lines):
            self.text(_n(cx), y + head_dy + 19 + i * step, s, "t", name)
        return name

    def note(self, x, y, w, head, lines, step=17, name=None, gap=None):
        """Notatka z nagłówkiem; pusty napis = pół odstępu przerwy."""
        name = name or head
        n = 0.0
        for s in lines:
            n += 0.5 if s == "" else 1.0
        h = int(22 + 12 + n * step + 4)
        self.rect(x, y, w, h, "note", name)
        self.text(x + 16, y + 22, head, "nh", name)
        yy = y + 22 + (gap or 21)
        for s in lines:
            if s == "":
                yy += step / 2
                continue
            cls = "nt"
            if isinstance(s, tuple):
                s, cls = s
            self.text(x + 16, _n(yy), s, cls, name)
            yy += step
        return y + h

    # ---- kontrola
    def check(self):
        bad = []
        rmap = {r[4]: r for r in self.rects}
        if len(rmap) != len(self.rects):
            bad.append("powtórzona nazwa ramki")

        def inside(a, b):           # a w b
            return (a[0] >= b[0] and a[1] >= b[1] and
                    a[0] + a[2] <= b[0] + b[2] and a[1] + a[3] <= b[1] + b[3])

        def ancestors(name):
            out = set()
            r = rmap.get(name)
            while r and r[5]:
                out.add(r[5])
                r = rmap.get(r[5])
            return out

        for r in self.rects:
            if r[0] < 0 or r[1] < 0 or r[0] + r[2] > W or r[1] + r[3] > H:
                bad.append(f"ramka poza arkuszem: {r[4]}")
            if r[5] and not inside(r, rmap[r[5]]):
                bad.append(f"ramka {r[4]} wystaje z {r[5]}")
        for i, a in enumerate(self.rects):
            for b in self.rects[i + 1:]:
                if a[4] == b[5] or b[4] == a[5] or a[4] in ancestors(b[4]) or b[4] in ancestors(a[4]):
                    continue
                if (a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and
                        a[1] < b[1] + b[3] and b[1] < a[1] + a[3]):
                    bad.append(f"ramki nachodzą: {a[4]} x {b[4]}")

        def hit(bb, r, pad=0.0):
            return (bb[0] < r[0] + r[2] - pad and r[0] + pad < bb[2] and
                    bb[1] < r[1] + r[3] - pad and r[1] + pad < bb[3])

        for bb, s, owner in self.texts:
            if bb[0] < 4 or bb[2] > W - 4 or bb[1] < 0 or bb[3] > H - 2:
                bad.append(f"napis poza arkuszem: {s!r}")
            if owner:
                o = rmap[owner]
                if (bb[0] < o[0] + 6 or bb[2] > o[0] + o[2] - 6 or
                        bb[1] < o[1] + 2 or bb[3] > o[1] + o[3] - 2):
                    bad.append(f"napis wychodzi z ramki {owner}: {s!r}")
            allowed = {owner} | ancestors(owner) if owner else set()
            for r in self.rects:
                if r[4] in allowed:
                    continue
                if hit(bb, r):
                    bad.append(f"napis {s!r} wchodzi w ramkę {r[4]}")
        for i, (a, sa, _) in enumerate(self.texts):
            for b, sb, _ in self.texts[i + 1:]:
                if a[0] < b[2] - 1 and b[0] < a[2] - 1 and a[1] < b[3] - 1 and b[1] < a[3] - 1:
                    bad.append(f"napisy zachodzą: {sa!r} x {sb!r}")
        for x1, y1, x2, y2, cls, ends in self.wires:
            seg = (min(x1, x2) - 1.5, min(y1, y2) - 1.5, max(x1, x2) + 1.5, max(y1, y2) + 1.5)
            for bb, s, _ in self.texts:
                if seg[0] < bb[2] and bb[0] < seg[2] and seg[1] < bb[3] and bb[1] < seg[3]:
                    bad.append(f"przewód {cls} ({x1},{y1})-({x2},{y2}) przez napis {s!r}")
            for r in self.rects:
                if r[4] in ends:
                    continue
                # przewód może dochodzić do krawędzi, ale nie wchodzić w ramkę
                if hit(seg, r, pad=2.0):
                    bad.append(f"przewód {cls} ({x1},{y1})-({x2},{y2}) przez ramkę {r[4]}")
        if bad:
            raise SystemExit("rysunek do poprawki:\n  " + "\n  ".join(bad))

    def svg(self):
        head = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
                f'viewBox="0 0 {W} {H}" font-family="DejaVu Sans, Verdana, sans-serif">\n'
                "  <title>BCM v8.5 — tor zasilania wariantu testowo-rozwojowego (M910q)</title>\n"
                + STYLE + "\n\n"
                f'  <rect class="bg" x="0" y="0" width="{W}" height="{H}"/>')
        return head + "\n" + "\n".join(self.out) + "\n</svg>\n"


def _n(v):
    """Liczba do SVG bez zbędnego „.0” — wynik ma być bajt w bajt powtarzalny."""
    return int(v) if float(v).is_integer() else round(v, 1)


def build():
    s = Sheet()

    # ---------------- nagłówek
    s.text(24, 32, "Wariant testowo-rozwojowy — tor zasilania z buforem (przegląd blokowy)", "ttl")
    s.text(24, 52, "Ten sam tor co w wersji docelowej (ZB); różnice tylko po stronie odbiorników: "
           "jeden panel 7\", bez domeny stałej logiki i bez wzmacniacza.", "sub")
    s.out.append('  <line x1="24" y1="64" x2="1176" y2="64" stroke="#c8d2da" stroke-width="1.5"/>')

    s.rect(24, 76, 1152, 50, "boxW", "stan")
    s.text(40, 96, "Stan auta testowego dziś: bufora jeszcze nie ma — nic z tego arkusza nie jest "
           "zamontowane.", "tb", "stan")
    s.text(40, 115, "Każde zgaszenie silnika to twarde odcięcie prądu M910q (i USB telefonu). Do "
           "montażu chronią atomowe zapisy BCM i bcm-harden.sh (WDROZENIE_TESTOWE §3).", "tl", "stan")

    # ================= A. ŁADOWANIE
    s.comment("A. ŁADOWANIE")
    cx = 397
    s.text(24, 152, "ŁADOWANIE — przy zapłonie albo tylko przy pracy silnika (cewka K1 z D+)", "sec", fill=SEC_COLOR["C"])

    s.block(197, 162, 400, 56, "boxC", "aku", "Akumulator rozruchowy 12 V",
            ["„−” przez nadwozie do punktu masy przy banku"])
    s.path([(cx, 218), (cx, 266)], "wire", ("aku", "ochr"))
    s.text(409, 238, "F1 20 A (MIDI/ANL), ≤ 30 cm od klemy „+”", "fuse")
    s.text(409, 254, "przewody 1–2 · 6 mm², ok. 5 m do bagażnika", "wl")

    s.block(197, 266, 400, 56, "boxC", "ochr", "Ochrona wejścia — D5 + C1",
            ["TVS SMCJ20CA (dwukierunkowa) · C1 470 µF / 35 V low-ESR"])
    s.path([(cx, 322), (cx, 352)], "wire", ("ochr", "k1"))
    s.text(409, 341, "przewód 3 · 6 mm²", "wl")

    s.block(197, 352, 400, 74, "boxC", "k1", "K1 — przekaźnik ładowania 30 A",
            ["cewka 85/86 z zapłonu albo D+ · 1N4007 (D6) na cewce",
             "zwiera przy zapłonie (z D+: tylko przy pracy silnika)"])
    s.block(30, 362, 118, 54, "box", "ign", "ZAPŁON / D+",
            ["12 V: ON / praca"], head_dy=22)
    s.path([(148, 395), (197, 395)], "wire", ("ign", "k1"))
    s.text(153, 388, "FK 1 A", "fuse")

    # rozgałęzienie na dwie ładowarki
    bl, br = 210, 585
    s.path([(cx, 426), (cx, 454)], "wire", ("k1",))
    s.path([(bl, 454), (br, 454)], "wire")
    s.path([(bl, 454), (bl, 482)], "wire", ("xy1",))
    s.path([(br, 454), (br, 482)], "wire", ("xy2",))
    s.dot(cx, 454)
    s.text(409, 445, "przewody 5 / 5a · 2,5 mm² z zacisku 87", "wl")

    for c, n, m1, m2, fc in ((bl, 1, "M1a", "M2a", "FC1"), (br, 2, "M1b", "M2b", "FC2")):
        x = c - 150
        s.block(x, 482, 300, 56, "boxC", f"xy{n}", f"XY-SK120 #{n} ({m1})",
                ["buck-boost CC-CV · CV 14,40 V · CC 5,0 A"])
        s.path([(c, 538), (c, 568)], "wire", (f"xy{n}", f"xm{n}"))
        s.text(c + 12, 557, f"przewód {'6' if n == 1 else '6a'} · 2,5 mm²", "wl")
        s.block(x, 568, 300, 56, "boxC", f"xm{n}", f"XH-M603 #{n} ({m2})",
                ["blokada przeładowania · 15,30 / 14,00 V"])
        s.path([(c, 624), (c, 668)], "wire", (f"xm{n}",))
        s.text(c + 12, 643, f"{fc} 7,5 A przy OUT+", "fuse")
        s.text(c + 12, 658, f"przewód {'7' if n == 1 else '7a'} · 2,5 mm²", "wl")

    s.path([(bl, 668), (br, 668)], "wire")
    s.dot(cx, 668)
    s.text(cx + 12, 689, "złączenie gałęzi (obie równej długości)", "wl")

    # ================= B. BANK
    s.comment("B. BANK")
    lp_cx = 145
    # przewód B: ze złączenia w dół, potem w lewo do L+
    s.path([(cx, 668), (cx, 700), (lp_cx, 700), (lp_cx, 744)], "wire", ("lplus",))
    s.text(157, 721, "F12 15 A (MIDI/ANL) przy bloku L+", "fuse")
    s.text(157, 736, "przewód B · 4 mm²", "wl")
    s.text(24, 724, "BANK", "sec", fill=SEC_COLOR["B"])

    # bloki „+”
    s.rect(110, 744, 70, 30, "boxB", "lplus")
    s.text(lp_cx, 764, "L+", "tbm", "lplus")
    s.rect(505, 744, 70, 30, "boxB", "pplus")
    s.text(540, 764, "P+", "tbm", "pplus")
    s.path([(180, 759), (505, 759)], "wire", ("lplus", "pplus"))
    s.text(342, 753, "łącznik „+” 6 mm² OFC", "ntm")

    # kosze
    s.rect(60, 790, 400, 120, "boxB", "koszL")
    s.text(260, 810, "KOSZ L — 4 × HR1221W (#1–#4)", "tbm", "koszL")
    s.rect(480, 790, 280, 120, "boxB", "koszP")
    s.text(620, 810, "KOSZ P — 3 × HR1221W (#5–#7)", "tbm", "koszP")
    for i in range(7):
        if i < 4:
            px, par = 80 + i * 92, "koszL"
        else:
            px, par = 500 + (i - 4) * 88, "koszP"
        nm = f"pak{i + 1}"
        s.rect(px, 822, 76, 46, "pack", nm, par)
        s.text(px + 38, 840, f"#{i + 1}", "tbm", nm)
        s.text(px + 38, 858, f"FB{i + 1} 10 A", "fusem", nm)
    s.text(260, 892, "FLRY-B 2,5 mm², 0,25 m ±30 mm, równej długości", "t", "koszL")
    s.text(620, 892, "jak w koszu L", "t", "koszP")
    # odcinki pakiet → blok (symbolicznie: jedna para na kosz)
    s.path([(lp_cx, 774), (lp_cx, 790)], "wthin", ("lplus", "koszL"))
    s.path([(540, 774), (540, 790)], "wthin", ("pplus", "koszP"))
    s.path([(lp_cx, 910), (lp_cx, 926)], "wthin", ("koszL", "lminus"))
    s.path([(675, 910), (675, 926)], "wthin", ("koszP", "pminus"))

    # bloki „−”
    s.rect(110, 926, 70, 30, "boxB", "lminus")
    s.text(lp_cx, 946, "L−", "tbm", "lminus")
    s.rect(640, 926, 70, 30, "boxB", "pminus")
    s.text(675, 946, "P−", "tbm", "pminus")
    s.path([(180, 941), (640, 941)], "wgnd", ("lminus", "pminus"))
    s.text(410, 935, "łącznik „−” 6 mm² OFC (obie żyły równe, 0,4–0,6 m)", "ntm")
    s.text(64, 978, "7 × CSB HR1221W F2 równolegle = 35,7 Ah · ≈ 16,8 kg z koszami · "
           "odbiór po przekątnej: „+” z L+, „−” z P−", "tl")

    # masa banku → S1 → punkt masy (prawa kolumna)
    s.path([(710, 941), (800, 941)], "wgnd", ("pminus", "s1"))
    s.text(716, 934, "9 · 6 mm²", "wl")
    s.block(800, 918, 376, 46, "boxB", "s1", "S1 — rozłącznik masy 100 A", head_dy=29)
    s.path([(988, 964), (988, 986)], "wgnd", ("s1", "masa"))
    masa_lines = [
        "osobny blok masowy, nie blok P−. Lądują na nim:",
        "„−” D5/C1, K1:85, IN−/OUT− obu XY-SK120 (bez izolacji),",
        "DC-IN− obu XH-M603, S1 (masa banku), VIN− XH-M609,",
        "IN− step-upu i powrót 20 V z M910q (żyła „−” przewodu 12),",
        "wspólny powrót 12 V z przodu (LM2596, MP1584) 2,5 mm².",
        ("→ karoseria: JEDEN przewód 6 mm² (ok. 13 A).", "tb"),
        "„−” akumulatora rozruchowego — tylko przez nadwozie.",
        "Wyjątek: masa wejść PC817 (U1 pin 2) → masa auta.",
    ]
    ymasa = s.note(800, 986, 376, "Punkt masy przy banku — JEDEN (ZB §5.6, §8.3)",
                   masa_lines, name="masa")

    # ================= C. ODBIORNIKI
    s.comment("C. ODBIORNIKI")
    # F7: z L+ w lewo i w dół do LVD
    s.path([(110, 759), (36, 759), (36, 1032), (60, 1032)], "wire", ("lplus", "lvd"))
    s.text(40, 752, "F7 20 A", "fuse")
    s.text(64, 1003, "ODBIORNIKI — zasilane stale, niezależnie od zapłonu", "sec", fill=SEC_COLOR["L"])

    s.block(60, 1010, 300, 74, "boxL", "lvd", "M3 XH-M609 — LVD",
            ["odcięcie 11,00 V · powrót 12,60 V",
             "wejście: F7 przy L+, przewód 8, 6 mm²"])
    c1, c2, c3 = 185, 450, 665
    s.path([(c1, 1084), (c1, 1110)], "wire", ("lvd",))
    s.path([(c1, 1110), (c3, 1110)], "wire")
    s.dot(c1, 1110)
    s.text(372, 1048, "szyna odbiorników +12 V za LVD", "tb")
    s.text(372, 1064, "przewód 10 · 4 mm²", "wl")
    for c, f, wl in ((c1, "F8 10 A", "przewód 11 · 4 mm²"),
                     (c2, "F9 2 A", "przewód 13 · 1,5 mm²"),
                     (c3, "F10 3 A", "przewód 13a\n0,75 mm²")):
        s.text(c + 12, 1131, f, "fuse")
        for k, part in enumerate(wl.split("\n")):
            s.text(c + 12, 1146 + k * 15, part, "wl")
    s.dot(c2, 1110)
    s.path([(c1, 1110), (c1, 1158)], "wire", ("stepup",))
    s.path([(c2, 1110), (c2, 1296)], "wire", ("lm",))
    s.path([(c3, 1110), (c3, 1296)], "wire", ("mp",))

    s.block(40, 1158, 290, 74, "boxL", "stepup", "M4 STEP-UP 12 → 20 V",
            ["zalewany, 10 A / 200 W · bez regulacji",
             "do 6,6 A z szyny przy 11 V (65 W)"])

    # granica bagażnik / przód
    # wkładka 5 A siedzi przy wyjściu przetwornicy, w bagażniku (ZB §8.1);
    # granicę przecina dopiero przewód 12
    s.path([(24, 1263), (772, 1263)], "zone")
    s.text(28, 1257, "▲ BAGAŻNIK", "zl")
    s.text(28, 1280, "▼ PRZÓD", "zl")

    s.path([(c1, 1232), (c1, 1296)], "wire", ("stepup", "m910q"))
    s.text(c1 + 12, 1250, "5 A na wyjściu step-upu (w bagażniku)", "fuse")
    s.text(c1 + 12, 1287, "12 · 2 × 4 mm², ok. 4 m", "wl")

    s.block(40, 1296, 290, 128, "box", "m910q", "M910q — ZASILANY STALE",
            ["20 V, do 3,25 A (65 W) · RAPL niepotrzebny",
             "zapłon go nie odcina — S3 robi Arduino",
             "USB: panel 7\" (logika + dotyk),",
             "Pro Micro, modem LTE",
             "przycisk zasilania ← przekaźnik Nano"])
    s.block(350, 1296, 200, 56, "boxL", "lm", "M5 LM2596",
            ["12 → 5 V · tylko podświetlenie"])
    s.block(570, 1296, 190, 56, "boxL", "mp", "M6 MP1584",
            ["12 → 5 V · logika"])
    s.path([(c2, 1352), (c2, 1382)], "wire", ("lm", "panel"))
    s.text(c2 + 12, 1371, "przewód 14", "wl")
    s.path([(c3, 1352), (c3, 1382)], "wire", ("mp", "nano"))
    s.text(c3 + 12, 1371, "przewód 25", "wl")
    s.block(350, 1382, 200, 74, "box", "panel", "PANEL 7\" 1024×600",
            ["podświetlenie: PWM+ / GND", "logika + dotyk: USB"])
    s.block(570, 1382, 190, 74, "boxS", "nano", "Arduino Nano",
            ["żyje, gdy M910q śpi", "USB bez żyły VBUS"])
    s.path([(330, 1404), (350, 1404)], "wusb", ("m910q", "panel"))

    # sygnał: zapłon → PC817 → Nano → przekaźnik → przycisk M910q
    s.text(24, 1488, "STEROWANIE — zapłon jest tylko sygnałem (§3.1a, SCHEMATY §10.4–10.5)", "sec",
           fill=SEC_COLOR["S"])
    s.block(24, 1500, 150, 48, "boxS", "sig1", "ZAPŁON / ACC", ["12 V"], step=16, head_dy=20)
    s.block(200, 1500, 150, 48, "boxS", "sig2", "PC817 (U1)", ["R1 2,2 kΩ → D9"], step=16, head_dy=20)
    s.block(376, 1500, 180, 48, "boxS", "sig3", "Nano → przekaźnik", ["A0 · impuls 250 ms / 5 s"],
            step=16, head_dy=20)
    s.block(582, 1500, 178, 48, "boxS", "sig4", "przycisk M910q", ["równolegle do styków"],
            step=16, head_dy=20)
    s.path([(174, 1524), (200, 1524)], "wsig", ("sig1", "sig2"))
    s.path([(350, 1524), (376, 1524)], "wsig", ("sig2", "sig3"))
    s.path([(556, 1524), (582, 1524)], "wsig", ("sig3", "sig4"))
    s.text(24, 1568, "250 ms: praca → S3, S3 → wybudzenie (~3 s), wyłączony → start · 5 s: "
           "twarde wyłączenie (eskalacja po 2 h postoju)", "tl")

    # ================= NOTATKI (prawa kolumna)
    s.comment("NOTATKI")
    nx, nw = 800, 376
    y = s.note(nx, 140, nw, "Dlaczego tor ładowania musi się rozłączać", [
        "Bez K1 wejścia ładowarek wisiałyby stale na akumulatorze",
        "rozruchowym i na postoju ładowały bank jego kosztem.",
        "Cewka z zapłonu: kluczyk ON bez silnika = ok. 13 A",
        "z rozruchowego. Lepiej z D+/L alternatora; LVP 12,8 V.",
        "K1 nie odcina niczego po stronie odbiorników.",
    ])
    y = s.note(nx, y + 14, nw, "Dwie XY-SK120 — CC liczysz z obciążeniem", [
        "Moduł limituje prąd WYJŚCIOWY: obciążenie plus ładowanie.",
        "Zestaw testowy bierze w jeździe ok. 3–5 A (szacunek).",
        ("1 × CC 5 A  →  netto do banku 0–2 A — za mało", "nt"),
        ("2 × CC 5 A  →  netto ≈ 5–7 A (0,7–1,0 A na pakiet)", "tb"),
        "Sufit CSB 2,1 A × 7 = 14,7 A — daleko. Jeden XH-M603",
        "realnie ok. 8 A, więc po jednym na ładowarkę (ZB §6.3).",
    ])
    y = s.note(nx, y + 14, nw, "Nastawy (WDROZENIE_TESTOWE §3.5)", [
        "XY-SK120 × 2: CV 14,40 V · CC 5,0 A · OVP 15,0 V,",
        "  LVP 12,8 V · wyjście po włączeniu: ON; oba CV ±0,02 V,",
        "  nastawiane bez banku. Lato: 13,95 V (ZB §5.5).",
        "XH-M603 × 2: próg 15,30 V · powrót 14,00 V",
        "XH-M609: odcięcie 11,00 V · powrót 12,60 V",
        "Step-up: bez regulacji; bez obciążenia 19,9–20,5 V,",
        "  ~60 W: ≥ 19,8 V na wyjściu, ≥ 19,5 V na wtyku.",
    ])
    y = s.note(nx, y + 14, nw, "Bank na lince — bloki zbiorcze (ZB §4.3)", [
        "Blok zbiorczy na biegun w każdym koszu (L+, L−, P+, P−):",
        "izolowany, 4 kołki M6, pokrywa. 14 odcinków FLRY-B 2,5 mm²",
        "równej długości; FB1…FB7 10 A na „+”, 5–10 cm od zacisku.",
        "Po przekątnej rozrzut prądów ok. 4 %; oba bieguny",
        "z jednego kosza — ok. 24 %, zakaz.",
    ])
    assert y <= 904, y

    y = s.note(nx, ymasa + 14, nw, "Pobór postojowy — S3 to nie zero (§3.1a)", [
        "M910q w S3 160–320 mA + Nano 15 mA + XH-M609",
        "20–125 mA + prąd jałowy step-upu (I_jał — zmierz).",
        ("S3: 200–460 mA + I_jał → 1,6–3,7 dnia (bez I_jał)", "tb"),
        "Wyłączony (impuls 5 s): 50–150 mA + I_jał → 5,0–14,9 dnia.",
        "Dłuższy postój: S1 rozwarty — jedyne prawdziwe zero.",
    ])
    tbl = [
        ("akumulator → F1 → bagażnik", "F1 20 A", "6 mm²"),
        ("K1 → każda XY-SK120", "—", "2,5 mm²"),
        ("XH-M603 → złączenie", "FC1/FC2 7,5 A", "2,5 mm²"),
        ("złączenie → L+ (przewód B)", "F12 15 A", "4 mm²"),
        ("pakiet → blok (× 14)", "FB 10 A", "2,5 mm²"),
        ("łącznik L ↔ P (+ i −)", "—", "6 mm² OFC"),
        ("L+ → XH-M609", "F7 20 A", "6 mm²"),
        ("P− → S1 → punkt masy", "—", "6 mm²"),
        ("punkt masy → karoseria (jeden)", "—", "6 mm²"),
        ("wspólny powrót 12 V z przodu", "—", "2,5 mm²"),
        ("LVD → szyna odbiorników", "—", "4 mm²"),
        ("szyna → step-up", "F8 10 A", "4 mm²"),
        ("step-up → M910q (+ i −)", "5 A", "4 mm²"),
        ("szyna → LM2596", "F9 2 A", "1,5 mm²"),
        ("szyna → MP1584", "F10 3 A", "0,75 mm²"),
        ("zapłon / D+ → cewka K1", "FK 1 A", "0,75 mm²"),
    ]
    ty = y + 14
    th = 22 + 12 + 22 + len(tbl) * 17 + 45
    s.rect(nx, ty, nw, th, "note", "tabela")
    s.text(nx + 16, ty + 22, "Bezpieczniki i przekroje (SCHEMATY §10)", "nh", "tabela")
    s.out.append(f'  <line x1="{nx + 16}" y1="{ty + 31}" x2="{nx + nw - 16}" y2="{ty + 31}" '
                 'stroke="#c8d2da"/>')
    s.text(nx + 16, ty + 48, "Obwód", "tb", "tabela")
    s.text(nx + 196, ty + 48, "Bezp.", "tb", "tabela")
    s.text(nx + 296, ty + 48, "Przekrój", "tb", "tabela")
    for i, (a, b, c) in enumerate(tbl):
        yy = ty + 70 + i * 17
        s.text(nx + 16, yy, a, "nt", "tabela")
        s.text(nx + 196, yy, b, "nt", "tabela")
        s.text(nx + 296, yy, c, "nt", "tabela")
    s.text(nx + 16, ty + th - 27, "F7 i F12: ≤ 30 cm od bloku L+ (ZB §8a.3).", "foot", "tabela")
    s.text(nx + 16, ty + th - 12, "Oba przewody masy: bez numeru w SCHEMATY §10.3/§10.6.",
           "foot", "tabela")
    assert ty + th <= 1690, ty + th

    # ---------------- stopka
    s.text(24, 1712, "Bagażnik: bank, ładowarki, LVD, wkładki F7, F8–F10, F12 i step-up; przód: M910q przy nogach "
           "pasażera, panel, LM2596, MP1584 i Nano.", "foot")
    s.text(24, 1730, "Do przodu idą: 20 V (para 4 mm²), dwie żyły 12 V (F9, F10) i wspólny powrót 12 V 2,5 mm² do punktu masy przy banku (ZB §8.2, §8a).", "foot")
    s.text(24, 1748, "Wzmacniacz nie występuje w tym wariancie. Gdy dojdzie — osobna gałąź wprost "
           "z akumulatora rozruchowego, własny bezpiecznik i własna masa; przez bank nie idzie wtedy "
           "żaden prąd mocy.", "foot")
    s.text(24, 1766, "Schemat komponentowy tego toru (numery przewodów): schematics/schematic_test_power.svg "
           "· tabele: docs/SCHEMATY_POLACZEN.md §10 · nastawy i pomiary: docs/ZASILANIE_BUFOROWANE.md", "foot")
    s.text(24, 1784, "Generator: schematics/gen_power_test_build.py — po zmianie dokumentów popraw generator, "
           "nie edytuj SVG ręcznie.", "foot")
    return s


def main():
    s = build()
    s.check()
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(s.svg())
    print(f"zapisano {os.path.relpath(OUT)}")


if __name__ == "__main__":
    sys.exit(main())
