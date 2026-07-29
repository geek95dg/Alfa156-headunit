#!/usr/bin/env python3
"""Generator dwóch arkuszy schematu komponentowego wariantu testowego.

Rysuje:
    schematics/schematic_test_power.svg    — arkusz 1/2, tor zasilania
    schematics/schematic_test_signals.svg  — arkusz 2/2, sygnały i Arduino

Uruchomienie (z katalogu głównego repo):
    python3 schematics/gen_test_schematics.py

Źródło danych: tabele §10 docs/SCHEMATY_POLACZEN.md. Po zmianie tabel
popraw ten plik i wygeneruj SVG ponownie — nie edytuj SVG ręcznie.
"""

import math

STYLE = '''<style>
 .bg{fill:#ffffff}
 .w{stroke:#16242e;stroke-width:2.2;fill:none;stroke-linecap:round}
 .wp{stroke:#c0392b;stroke-width:2.8;fill:none;stroke-linecap:round}
 .wg{stroke:#3d4f5c;stroke-width:2.4;fill:none;stroke-linecap:round}
 .wo{stroke:#9a6b12;stroke-width:2.4;fill:none;stroke-linecap:round}
 .wd{stroke:#8b9aa6;stroke-width:1.6;fill:none;stroke-dasharray:5 4}
 .sym{stroke:#16242e;stroke-width:2.2;fill:none}
 .symf{stroke:#16242e;stroke-width:2.2;fill:#16242e}
 .blk{fill:#f5f8fa;stroke:#2b3a45;stroke-width:2.2;rx:5}
 .blkm{fill:#eef4fa;stroke:#2b4a8a;stroke-width:2.2;rx:5}
 .blkr{fill:#fdf6e8;stroke:#9a6b12;stroke-width:2.2;rx:5}
 .blkc{fill:#eef8ee;stroke:#2d6a2d;stroke-width:2.2;rx:5}
 .opto{fill:#fbf3fb;stroke:#7a3d8f;stroke-width:2.2;rx:5;stroke-dasharray:7 4}
 .dash{fill:none;stroke:#7a3d8f;stroke-width:2;rx:5;stroke-dasharray:7 4}
 .term{fill:#ffffff;stroke:#16242e;stroke-width:2.4}
 .note{fill:#fbfcfd;stroke:#c8d2da;stroke-width:1.5;rx:6}
 .sectb{fill:#2d6a2d;rx:4}
 .ttl{font-size:23px;font-weight:bold;fill:#0d1c26}
 .sub{font-size:13px;fill:#576875}
 .sec{font-size:16px;font-weight:bold;fill:#2d6a2d}
 .sn{font-size:15px;font-weight:bold;fill:#ffffff;text-anchor:middle}
 .r{font-size:12.5px;font-weight:bold;fill:#a8321a}
 .rc{font-size:12.5px;font-weight:bold;fill:#a8321a;text-anchor:middle}
 .re{font-size:12.5px;font-weight:bold;fill:#a8321a;text-anchor:end}
 .v{font-size:11.5px;fill:#40515e}
 .vc{font-size:11.5px;fill:#40515e;text-anchor:middle}
 .ve{font-size:11.5px;fill:#40515e;text-anchor:end}
 .vb{font-size:14px;font-weight:bold;fill:#16242e;text-anchor:middle}
 .lbl{font-size:11.5px;fill:#33424e}
 .lbb{font-size:13px;font-weight:bold;fill:#0d1c26;text-anchor:middle}
 .pin{font-size:11.5px;font-weight:bold;fill:#2b4a8a}
 .pine{font-size:11.5px;font-weight:bold;fill:#2b4a8a;text-anchor:end}
 .pinc{font-size:11.5px;font-weight:bold;fill:#2b4a8a;text-anchor:middle}
 .mref{font-size:14px;font-weight:bold;fill:#a8321a;text-anchor:middle}
 .mname{font-size:12.5px;font-weight:bold;fill:#0d1c26;text-anchor:middle}
 .te{font-size:12.5px;font-weight:bold;fill:#0d1c26;text-anchor:end}
 .gl{font-size:11px;font-weight:bold;fill:#3d4f5c;text-anchor:middle}
 .go{font-size:11px;font-weight:bold;fill:#9a6b12;text-anchor:middle}
 .nh{font-size:13px;font-weight:bold;fill:#0d1c26}
 .nt{font-size:11.5px;fill:#4a5a66}
 .wn{font-size:11px;font-weight:bold;fill:#0d1c26;text-anchor:middle}
 .wnb{fill:#ffffff;stroke:#8b9aa6;stroke-width:1.2;rx:3}
 .ldr{stroke:#7d8c99;stroke-width:1.3;fill:none}
 .ldrf{fill:#7d8c99;stroke:none}
</style>'''


class Sheet:
    def __init__(self, w, h, title, subtitle):
        self.o = []
        self.W, self.H = w, h
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
        s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        self.a(f'<text class="{c}" x="{x}" y="{y}">{s}</text>')

    def box(self, x, y, w, h, c="blk"):
        self.a(f'<rect class="{c}" x="{x}" y="{y}" width="{w}" height="{h}"/>')

    def leader(self, x0, y0, x1, y1, bend=None):
        """Cienki odnośnik od (x0,y0) do (x1,y1); grot przy (x1,y1)."""
        pts = [(x0, y0)] + ([bend] if bend else []) + [(x1, y1)]
        for i in range(len(pts) - 1):
            a, b = pts[i], pts[i + 1]
            self.a(f'<line class="ldr" x1="{a[0]}" y1="{a[1]}" '
                   f'x2="{b[0]}" y2="{b[1]}"/>')
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

    def wn(self, x, y, n):
        self.a(f'<rect class="wnb" x="{x-12}" y="{y-10}" width="24" height="18"/>')
        self.txt(x, y + 4, str(n), "wn")

    # ---- symbole
    def fuse_h(self, x, y, ref, val):
        self.w(x, y, x + 10, y)
        self.a(f'<rect class="sym" x="{x+10}" y="{y-9}" width="38" height="18" fill="#fff"/>')
        self.w(x + 10, y, x + 48, y)
        self.w(x + 48, y, x + 58, y)
        self.txt(x + 29, y - 17, ref, "rc")
        self.txt(x + 29, y + 27, val, "vc")
        return x + 58

    def fuse_v(self, x, y, ref, val, side=1):
        self.w(x, y, x, y + 10)
        self.a(f'<rect class="sym" x="{x-9}" y="{y+10}" width="18" height="38" fill="#fff"/>')
        self.w(x, y + 10, x, y + 48)
        self.w(x, y + 48, x, y + 58)
        if side > 0:
            self.txt(x + 15, y + 26, ref, "r")
            self.txt(x + 15, y + 41, val, "v")
        else:
            self.txt(x - 15, y + 26, ref, "re")
            self.txt(x - 15, y + 41, val, "ve")
        return y + 58

    def res_h(self, x, y, ref, val):
        self.w(x, y, x + 12, y)
        self.a(f'<rect class="sym" x="{x+12}" y="{y-10}" width="34" height="20" fill="#fff"/>')
        self.w(x + 46, y, x + 58, y)
        self.txt(x + 29, y - 17, ref, "rc")
        self.txt(x + 29, y + 28, val, "vc")
        return x + 58

    def cap_v(self, x, y, ref, val, pol=False, side=1):
        """Wejście w y, wyjście w y+50."""
        self.w(x, y, x, y + 20)
        self.w(x - 17, y + 20, x + 17, y + 20, "sym")
        if pol:
            self.a(f'<path class="sym" d="M {x-17} {y+34} Q {x} {y+24} {x+17} {y+34}"/>')
            self.txt(x + 26 if side < 0 else x - 26, y + 15, "+", "vb")
            self.w(x, y + 30, x, y + 50)
        else:
            self.w(x - 17, y + 30, x + 17, y + 30, "sym")
            self.w(x, y + 30, x, y + 50)
        if side > 0:
            self.txt(x + 24, y + 20, ref, "r")
            self.txt(x + 24, y + 35, val, "v")
        else:
            self.txt(x - 24, y + 20, ref, "re")
            self.txt(x - 24, y + 35, val, "ve")
        return y + 50

    def diode_v(self, x, y, ref, val=None, up=False, side=1):
        """Pionowa dioda, wejście y, wyjście y+50. up=True → katoda u góry."""
        self.w(x, y, x, y + 16)
        if up:
            self.a(f'<polygon class="symf" points="{x-11},{y+16} {x+11},{y+16} {x},{y+34}"/>')
            bar = y + 16
        else:
            self.a(f'<polygon class="symf" points="{x-11},{y+34} {x+11},{y+34} {x},{y+16}"/>')
            bar = y + 34
        self.w(x - 13, bar, x + 13, bar, "sym")
        self.w(x, bar, x, y + 50)
        if side > 0:
            self.txt(x + 20, y + 20, ref, "r")
            if val:
                self.txt(x + 20, y + 35, val, "v")
        else:
            self.txt(x - 34, y + 20, ref, "re")
            if val:
                self.txt(x - 34, y + 35, val, "ve")
        return y + 50

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

    def schottky_h(self, x, y):
        """Schottky pozioma, wejście x, wyjście x+52, katoda po prawej."""
        self.w(x, y, x + 16, y)
        self.a(f'<polygon class="symf" points="{x+16},{y-11} {x+16},{y+11} {x+34},{y}"/>')
        self.a(f'<path class="sym" d="M {x+40} {y-15} L {x+34} {y-15} L {x+34} {y+15} '
               f'L {x+28} {y+15}"/>')
        self.w(x + 34, y, x + 52, y)
        return x + 52

    def battery(self, x, y, ref, val):
        """Pionowo: '+' w y, '−' w y+62."""
        self.w(x, y, x, y + 18)
        self.w(x - 21, y + 18, x + 21, y + 18, "sym")
        self.w(x - 11, y + 27, x + 11, y + 27, "sym")
        self.w(x - 21, y + 36, x + 21, y + 36, "sym")
        self.w(x - 11, y + 45, x + 11, y + 45, "sym")
        self.w(x, y + 45, x, y + 62)
        self.txt(x + 30, y + 15, "+", "vb")
        self.txt(x + 30, y + 52, "−", "vb")
        self.txt(x - 29, y + 26, ref, "re")
        self.txt(x - 29, y + 41, val, "ve")
        return y + 62

    def coil(self, x, y, ref, lab86="86", lab85="85"):
        """Cewka przekaźnika, pionowa. 86 w y, 85 w y+80."""
        self.w(x, y, x, y + 14)
        self.a(f'<rect class="sym" x="{x-14}" y="{y+14}" width="28" height="52" fill="#fff"/>')
        self.w(x, y + 66, x, y + 80)
        self.txt(x + 22, y + 36, ref, "r")
        self.txt(x + 22, y + 51, "cewka", "v")
        self.txt(x - 20, y + 8, lab86, "pine")
        self.txt(x - 20, y + 78, lab85, "pine")
        return y + 80

    def contact(self, x, y, ref, note=None, ny=44):
        """Styk zwierny NO, poziomy. 30 w x, 87 w x+96."""
        self.w(x, y, x + 14, y)
        self.a(f'<circle class="sym" cx="{x+18}" cy="{y}" r="4.5" fill="#fff"/>')
        self.w(x + 21, y - 3, x + 74, y - 24)
        self.a(f'<circle class="sym" cx="{x+78}" cy="{y}" r="4.5" fill="#fff"/>')
        self.w(x + 82, y, x + 96, y)
        self.a(f'<line class="wd" x1="{x+48}" y1="{y-14}" x2="{x+48}" y2="{y+26}"/>')
        self.txt(x + 48, y - 34 if ny > 0 else y - 52, ref, "rc")
        self.txt(x + 14, y + 22, "30", "pin")
        self.txt(x + 82, y + 22, "87", "pine")
        if note:
            self.txt(x + 48, y + ny, note, "vc")
        return x + 96

    def switch_h(self, x, y, ref, val):
        self.w(x, y, x + 14, y)
        self.a(f'<circle class="sym" cx="{x+18}" cy="{y}" r="4.5" fill="#fff"/>')
        self.w(x + 21, y - 3, x + 74, y - 26)
        self.a(f'<circle class="sym" cx="{x+78}" cy="{y}" r="4.5" fill="#fff"/>')
        self.w(x + 82, y, x + 96, y)
        self.txt(x + 48, y - 38, ref, "rc")
        self.txt(x + 48, y + 26, val, "vc")
        return x + 96

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

    def term(self, x, y, t, sub=None):
        self.a(f'<circle class="term" cx="{x}" cy="{y}" r="7"/>')
        self.txt(x - 16, y + 5, t, "te")
        if sub:
            self.txt(x - 16, y + 22, sub, "ve")

    def module(self, x, y, w, h, ref, name, sub=None,
               left=(), right=(), cls="blkm"):
        self.box(x, y, w, h, cls)
        self.txt(x + w / 2, y + 25, ref, "mref")
        self.txt(x + w / 2, y + 44, name, "mname")
        if sub:
            self.txt(x + w / 2, y + 62, sub, "vc")
        p = {}
        for i, (k, lab) in enumerate(left):
            py = y + 92 + i * 36
            self.w(x - 18, py, x, py)
            self.txt(x + 10, py + 5, lab, "pin")
            p[k] = (x - 18, py)
        for i, (k, lab) in enumerate(right):
            py = y + 92 + i * 36
            self.w(x + w, py, x + w + 18, py)
            self.txt(x + w - 10, py + 5, lab, "pine")
            p[k] = (x + w + 18, py)
        return p


# ======================================================================
#  ARKUSZ 1 — ZASILANIE
# ======================================================================
s = Sheet(1620, 1946,
          "BCM v8.5 — arkusz 1/2: ZASILANIE (wariant testowo-rozwojowy, M910q)",
          "Każdy element osobno. Cewki i styki przekaźników rozdzielone — "
          "K1 i K2 to po jednym przekaźniku Bosch, narysowanym w dwóch "
          "miejscach. Moduły kupne jako prostokąty z zaciskami.")

s.sect(40, 118, "A", "TOR ŁADOWANIA — akumulator rozruchowy → bank")
RAIL, GA = 240, 720

# --- akumulator rozruchowy
s.txt(110, 196, "AKUMULATOR", "lbb")
s.txt(110, 212, "ROZRUCHOWY", "lbb")
s.battery(110, RAIL, "BT0", "12 V")
s.w(110, RAIL + 62, 110, GA)
s.star_gnd(110, GA)
s.w(110, RAIL, 156, RAIL)
s.wn(133, RAIL - 15, 1)
x = s.fuse_h(156, RAIL, "F1", "15 A")
s.wn(x + 18, RAIL - 15, 2)

# --- TVS i C1 (osobno!)
s.w(x, RAIL, 430, RAIL)
s.dot(258, RAIL)
s.dot(420, RAIL)
yy = s.tvs_v(258, RAIL + 22, "D5", "1.5KE33CA")
s.w(258, yy, 258, GA)
s.star_gnd(258, GA)
s.txt(258, GA + 44, "TVS — obcina load dump", "vc")
s.txt(258, GA + 60, "CA = dwukierunkowa, montaż dowolnie", "vc")
yy = s.cap_v(420, RAIL + 22, "C1", "470 µF / 35 V", pol=True, side=1)
s.w(420, yy, 420, GA)
s.star_gnd(420, GA)
s.txt(430, GA + 44, "bufor wejścia", "vc")

# --- styk K1
s.w(430, RAIL, 470, RAIL)
s.wn(437, RAIL - 15, 3)
x = s.contact(470, RAIL, "K1", "zwiera po zapłonie", ny=-32)
s.dot(600, RAIL)
s.w(x, RAIL, 660, RAIL)
s.wn(632, RAIL - 15, 5)

# --- cewka K1 + dioda gasząca
s.term(250, 470, "ZAPŁON / ACC", "12 V po przekręceniu kluczyka")
s.w(257, 470, 518, 470)
s.wn(400, 455, 4)
s.coil(518, 470, "K1")
s.w(518, 550, 518, GA)
s.star_gnd(518, GA)
s.dot(444, 470)
s.w(444, 470, 444, 486)
s.diode_v(444, 486, "D6", "1N4007", up=True, side=-1)
s.path([(444, 536), (444, 550), (518, 550)])
s.dot(518, 550)

# --- D1 MBR2545CT
s.a('<rect class="dash" x="660" y="130" width="196" height="224"/>')
s.txt(758, 118, "D1", "rc")
s.txt(758, 376, "MBR2545CT — anody 1 i 3 zwarte", "vc")
s.txt(758, 392, "blaszka = katoda (pin 2), izoluj od radiatora", "vc")
s.path([(660, RAIL), (686, RAIL)])
s.dot(686, RAIL)
s.path([(686, 190), (686, 290)])
s.schottky_h(686, 190)
s.schottky_h(686, 290)
s.path([(738, 190), (830, 190), (830, 290), (738, 290)])
s.dot(830, RAIL)
s.txt(712, 176, "pin 1 — anoda", "vc")
s.txt(712, 322, "pin 3 — anoda", "vc")
s.txt(806, 254, "pin 2 — katoda", "ve")
s.leader(810, 250, 828, 241)
s.w(830, RAIL, 902, RAIL)
s.wn(874, RAIL - 15, 6)

# --- ładowarka CC-CV
m1 = s.module(902, 148, 214, 200, "M1", "MODUŁ CC-CV BOOST", "SZBK07 / „900 W 15 A”",
              left=[("in+", "IN+"), ("in-", "IN−")],
              right=[("out+", "OUT+"), ("out-", "OUT−")])
s.txt(1009, 372, "CV 14,40 V · CC 7,5 A", "vc")
s.path([(902, RAIL), (884, RAIL), (884, m1["in+"][1]), (m1["in+"][0], m1["in+"][1])])
s.path([(m1["in-"][0], m1["in-"][1]), (866, m1["in-"][1]), (866, GA)])
s.star_gnd(866, GA)
s.path([(m1["out-"][0], m1["out-"][1]), (1160, m1["out-"][1]), (1160, GA)])
s.star_gnd(1160, GA)

# --- styk K2
s.path([(m1["out+"][0], m1["out+"][1]), (1216, m1["out+"][1]), (1216, RAIL),
        (1240, RAIL)])
s.wn(1216, RAIL - 15, "B")
x = s.contact(1240, RAIL, "K2", "rozwiera przy przeładowaniu")
s.w(x, RAIL, 1470, RAIL)
s.wn(1400, RAIL - 15, 7)
s.w(1470, RAIL, 1470, 930)
s.txt(1358, RAIL - 34, "→ szyna „+” banku", "lbl")

# --- cewka K2 + D7
s.coil(1240, 470, "K2")
s.w(1240, 550, 1240, GA)
s.star_gnd(1240, GA)
s.wn(1215, 590, "7e")
s.dot(1330, 470)
s.path([(1240, 470), (1330, 470), (1330, 486)])
s.diode_v(1330, 486, "D7", "1N4007", up=True)
s.path([(1330, 536), (1330, 550), (1240, 550)])
s.dot(1240, 550)

# --- M2 rozłącznik nadnapięciowy
m2 = s.module(910, 470, 214, 210, "M2", "XH-M603", "rozłącznik nadnapięciowy",
              left=[("vp", "V+"), ("com", "COM"), ("vm", "V−")],
              right=[("no", "NO")])
s.txt(1017, 704, "rozwiera 15,30 V · wraca 14,00 V", "vc")
s.txt(1017, 720, "zasilany z K1:87 — na postoju martwy", "vc")
# V+ i COM z węzła za stykiem K1
s.path([(600, RAIL), (600, 420), (760, 420), (760, m2["vp"][1]),
        (m2["vp"][0], m2["vp"][1])])
s.wn(700, 406, "7a")
s.dot(700, 420)
s.path([(700, 420), (700, m2["com"][1]), (m2["com"][0], m2["com"][1])])
s.wn(740, m2["com"][1] - 15, "7c")
# V- na masę
s.path([(m2["vm"][0], m2["vm"][1]), (820, m2["vm"][1]), (820, GA)])
s.star_gnd(820, GA)
s.wn(848, m2["vm"][1] + 20, "7b")
# NO → cewka K2:86
s.path([(m2["no"][0], m2["no"][1]), (1180, m2["no"][1]), (1180, 470), (1240, 470)])
s.wn(1180, m2["no"][1] - 15, "7d")

s.a('<line class="wd" x1="40" y1="800" x2="1580" y2="800"/>')

# ---------------- BAND B
s.sect(40, 852, "B", "BANK BUFOROWY · OCHRONA ROZŁADOWANIA · WYŁĄCZNIK GŁÓWNY")
PB, NB = 930, 1160
s.a(f'<line class="wp" x1="150" y1="{PB}" x2="1470" y2="{PB}"/>')
s.a(f'<line class="wg" x1="150" y1="{NB}" x2="1300" y2="{NB}"/>')
s.txt(156, PB - 14, "SZYNA „+” BANKU · 2,5 mm²", "nh")
s.txt(156, NB + 26, "SZYNA „−” BANKU · 2,5 mm²", "nh")
s.dot(1470, PB)

for i in range(4):
    bx = 210 + i * 140
    s.dot(bx, PB)
    yy = s.fuse_v(bx, PB, f"F{i+2}", "10 A", side=1 if i % 2 == 0 else -1)
    s.w(bx, yy, bx, yy + 12)
    s.battery(bx, yy + 12, f"BT{i+1}", "5,1 Ah")
    s.w(bx, yy + 74, bx, NB)
    s.dot(bx, NB)
s.txt(430, 1222, "4 × CSB HR1221W F2 · 12 V / 5,1 Ah AGM · równolegle = 20,4 Ah", "vc")

s.dot(790, PB)
x = s.fuse_h(790, PB, "F7", "15 A")
s.wn(x + 18, PB - 15, 8)
m3 = s.module(920, 878, 214, 200, "M3", "XH-M609", "ochrona głębokiego rozładowania",
              left=[("vin+", "VIN+"), ("vin-", "VIN−")],
              right=[("vout+", "VOUT+"), ("vout-", "VOUT−")])
s.txt(1027, 1102, "odcina 11,00 V · wraca 12,60 V", "vc")
s.w(x, PB, m3["vin+"][0], m3["vin+"][1])
s.path([(880, NB), (880, m3["vin-"][1]), (m3["vin-"][0], m3["vin-"][1])])
s.dot(880, NB)
s.wn(902, m3["vin-"][1] - 15, 9)
s.path([(m3["vout-"][0], m3["vout-"][1]), (1300, m3["vout-"][1]), (1300, NB)])
s.dot(1300, NB)
s.w(1300, NB, 1400, NB, "wg")
s.star_gnd(1400, NB)

s.path([(m3["vout+"][0], m3["vout+"][1]), (1200, m3["vout+"][1])])
s.wn(1176, m3["vout+"][1] - 15, 10)
x = s.switch_h(1200, m3["vout+"][1], "S1", "rozłącznik masy 100 A")
s.path([(x, m3["vout+"][1]), (1540, m3["vout+"][1]), (1540, 1340)])

s.a('<line class="wd" x1="40" y1="1240" x2="1580" y2="1240"/>')

# ---------------- BAND C
s.sect(40, 1292, "C", "ODBIORNIKI — zasilane stale, niezależnie od zapłonu")
LB, LG = 1340, 1700
s.a(f'<line class="wp" x1="180" y1="{LB}" x2="1540" y2="{LB}"/>')
s.dot(1540, LB)
s.txt(186, LB - 14, "SZYNA ODBIORNIKÓW +12 V (za S1)", "nh")

conv = [
    (240, "F8", "7,5 A", 11, "M4", "XL6019", "step-up 12 → 19,5 V"),
    (860, "F9", "2 A", 13, "M5", "LM2596", "step-down 12 → 5 V"),
    (1250, "F10", "3 A", 25, "M6", "MP1584", "step-down 12 → 5 V"),
]
mo = {}
for bx, fr, fv, wnum, mr, mn, ms in conv:
    s.dot(bx, LB)
    yy = s.fuse_v(bx, LB, fr, fv)
    m = s.module(bx + 40, yy + 26, 180, 186, mr, mn, ms,
                 left=[("in+", "IN+"), ("in-", "IN−")],
                 right=[("out+", "OUT+"), ("out-", "OUT−")])
    s.path([(bx, yy), (bx, m["in+"][1]), (m["in+"][0], m["in+"][1])])
    s.wn(bx, m["in+"][1] - 22, wnum)
    s.path([(m["in-"][0], m["in-"][1]), (bx - 22, m["in-"][1]), (bx - 22, LG)])
    s.star_gnd(bx - 22, LG)
    mo[mr] = m

# XL6019 → C6 → wtyk M910q
m4 = mo["M4"]
s.w(m4["out+"][0], m4["out+"][1], 620, m4["out+"][1])
s.dot(520, m4["out+"][1])
yy = s.cap_v(520, m4["out+"][1], "", "", pol=True, side=1)
s.txt(478, m4["out+"][1] + 136, "C6", "re")
s.txt(478, m4["out+"][1] + 152, "470 µF / 35 V", "ve")
s.leader(492, m4["out+"][1] + 116, 504, m4["out+"][1] + 26)
s.w(520, yy, 520, LG)
s.star_gnd(520, LG)
s.path([(m4["out-"][0], m4["out-"][1]), (486, m4["out-"][1]), (486, LG)])
s.star_gnd(486, LG)
s.box(620, m4["out+"][1] - 44, 178, 112)
s.txt(709, m4["out+"][1] - 20, "WTYK M910q", "lbb")
s.txt(709, m4["out+"][1] + 2, "środek = „+”  ·  ekran = „−”", "vc")
s.txt(709, m4["out+"][1] + 22, "19,5 V / 4,74 A", "vc")
s.txt(709, m4["out+"][1] + 44, "M910q zasilany STALE", "vc")

s.wn(580, m4["out+"][1] - 22, 12)

# LM2596 → panel
m5 = mo["M5"]
s.w(m5["out+"][0], m5["out+"][1], 1110, m5["out+"][1])
s.w(m5["out-"][0], m5["out-"][1], 1110, m5["out-"][1])
s.box(1110, m5["out+"][1] - 30, 110, 96)
s.txt(1165, m5["out+"][1] - 8, "PANEL 7\"", "lbb")
s.txt(1165, m5["out+"][1] + 12, "PWM+ / GND", "vc")
s.txt(1165, m5["out+"][1] + 32, "tylko", "vc")
s.txt(1165, m5["out+"][1] + 48, "podświetlenie", "vc")
s.wn(1090, m5["out+"][1] - 22, 14)

# MP1584 → arkusz 2
m6 = mo["M6"]
s.w(m6["out+"][0], m6["out+"][1], 1500, m6["out+"][1])
s.w(m6["out-"][0], m6["out-"][1], 1500, m6["out-"][1])
s.term(1507, m6["out+"][1], "")
s.term(1507, m6["out-"][1], "")
s.txt(1520, m6["out+"][1] + 5, "5 V", "pin")
s.txt(1520, m6["out-"][1] + 5, "GND", "pin")
s.txt(1490, m6["out-"][1] + 34, "→ ARKUSZ 2", "rc")
s.txt(1490, m6["out-"][1] + 50, "Arduino Nano", "vc")

for _bx, _t in ((240, "45 W · dlatego F8 = 7,5 A, nie 5 A"),
                (860, "logika i dotyk panelu idą po USB"),
                (1250, "Nano musi żyć, gdy M910q śpi")):
    s.txt(_bx + 60, 1756, _t, "vc")
    s.leader(_bx + 60, 1742, _bx + 60, 1620)

s.box(60, 1790, 1000, 56, "note")
s.txt(80, 1814, "MASA — punkt gwiazdowy", "nh")
s.txt(80, 1834, "Wszystkie symbole masy na tym arkuszu to JEDEN punkt: "
                "„−” BT0, „−” D5 i C1, K1:85, K2:85, IN−/OUT− M1, V− M2, "
                "szyna „−” banku, VIN−/VOUT− M3, IN− M4/M5/M6.", "nt")
s.box(1090, 1790, 470, 56, "note")
s.txt(1110, 1814, "Numery w ramkach", "nh")
s.txt(1110, 1834, "= numery przewodów z tabel §10 docs/SCHEMATY_POLACZEN.md", "nt")

s.box(60, 1862, 1500, 74, "note")
s.txt(80, 1886, "KIERUNKI DIOD — sprawdź przed lutowaniem", "nh")
s.txt(80, 1906, "D5 (1.5KE33CA lub SMCJ26CA): sufiks CA = dwukierunkowa. "
                "Nie ma anody ani katody, wlutuj w dowolną stronę. Uwaga: "
                "1.5KE33A (bez C) to inna dioda — jednokierunkowa,", "nt")
s.txt(80, 1926, "tam pasek/katoda idzie na PLUS. Sprawdź miernikiem w trybie "
                "diody: dwukierunkowa daje OL w obie strony.   ·   "
                "D1 MBR2545CT: blaszka = katoda → IN+ ładowarki.   ·   "
                "D6 i D7 (1N4007): pasek = katoda → zacisk 86 cewki.", "nt")

s.save("schematics/schematic_test_power.svg")


# ======================================================================
#  ARKUSZ 2 — SYGNAŁY
# ======================================================================
t = Sheet(1620, 1230,
          "BCM v8.5 — arkusz 2/2: SYGNAŁY I STEROWANIE (Arduino Nano)",
          "Zapłon i bieg wsteczny przez transoptory. Arduino zwiera przycisk "
          "zasilania M910q — żadnego protokołu, resztę robi acpid. "
          "Skrzyżowanie przewodów BEZ kropki = brak połączenia.")

t.sect(40, 118, "D", "WEJŚCIA OPTOIZOLOWANE — zapłon i bieg wsteczny")


def opto(sh, x, y, ref, name, pinlab):
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


Y1, Y2 = 180, 430
t.term(180, Y1 + 32, "ZAPŁON / ACC", "12 V po kluczyku")
x = t.res_h(210, Y1 + 32, "R1", "2,2 kΩ")
t.wn(276, Y1 + 17, 15)
u1 = opto(t, x + 50, Y1, "U1", "PC817 — zapłon", "wyjście → D9")
t.w(x, Y1 + 32, u1["p1"][0], u1["p1"][1])

t.term(180, Y2 + 32, "ŚWIATŁO COFANIA", "12 V z czujnika skrzyni")
x = t.res_h(210, Y2 + 32, "R3", "2,2 kΩ")
t.wn(276, Y2 + 17, "15a")
u2 = opto(t, x + 50, Y2, "U2", "PC817 — bieg wsteczny", "wyjście → D10")
t.txt(x + 125, Y2 + 186, "wymaga FEATURE_REV w firmware", "vc")
t.w(x, Y2 + 32, u2["p1"][0], u2["p1"][1])

# masa auta — WYŁĄCZNIE strona diod obu transoptorów
t.path([(u1["p2"][0], u1["p2"][1]), (256, u1["p2"][1]), (256, u2["p2"][1])])
t.path([(u2["p2"][0], u2["p2"][1]), (256, u2["p2"][1])])
t.dot(256, u2["p2"][1])
t.path([(256, u2["p2"][1]), (256, 660)])
t.wn(256, 360, 16)
t.chassis_gnd(256, 660, "MASA AUTA — nie łączyć z gwiazdą!")

# --- Arduino Nano
NX, NY = 900, 170
t.box(NX, NY, 250, 500, "blkc")
t.txt(NX + 125, NY + 32, "A1", "mref")
t.txt(NX + 125, NY + 52, "ARDUINO NANO V3", "mname")
t.txt(NX + 125, NY + 70, "ATmega328PB", "vc")
t.txt(NX + 125, NY + 94, "sensor_hub.ino", "vc")
np_ = {}
for i, (k, lab) in enumerate([("d9", "D9"), ("gnd", "GND"), ("d10", "D10"),
                              ("v5", "5V")]):
    py = NY + 140 + i * 78
    t.w(NX - 18, py, NX, py)
    t.txt(NX + 12, py + 5, lab, "pin")
    np_[k] = (NX - 18, py)
py = NY + 140
t.w(NX + 250, py, NX + 268, py)
t.txt(NX + 238, py + 5, "A0", "pine")
np_["a0"] = (NX + 268, py)
t.w(NX + 125, NY + 500, NX + 125, NY + 534)
t.txt(NX + 125, NY + 548, "USB → M910q", "lbb")
t.txt(NX + 125, NY + 566, "żyła VBUS (czerwona) PRZECIĘTA —", "vc")
t.txt(NX + 125, NY + 582, "dwa źródła 5 V nie mogą się bić", "vc")

D9Y, GNDY, D10Y, V5Y = (np_[k][1] for k in ("d9", "gnd", "d10", "v5"))

# U1 kolektor → D9   (korytarz x=620)
t.path([(u1["p4"][0], u1["p4"][1]), (620, u1["p4"][1]), (620, D9Y), (NX, D9Y)])
t.wn(680, D9Y - 15, 17)
# U1 emiter → GND    (korytarz x=530)
t.path([(u1["p3"][0], u1["p3"][1]), (530, u1["p3"][1]), (530, GNDY), (NX, GNDY)])
t.wn(560, u1["p3"][1] - 15, 18)
# U2 kolektor → D10  (korytarz x=680)
t.path([(u2["p4"][0], u2["p4"][1]), (680, u2["p4"][1]), (680, D10Y), (NX, D10Y)])
t.wn(636, 440, "17a")
# U2 emiter → GND    (korytarz x=740, na prawo od korytarza D10)
t.path([(u2["p3"][0], u2["p3"][1]), (740, u2["p3"][1]), (740, GNDY)])
t.dot(740, GNDY)
t.wn(770, u2["p3"][1] - 15, "18a")

# C3 (D9) i C4 (D10) — filtry do GND
t.dot(800, D9Y)
yy = t.cap_v(800, D9Y, "C3", "100 nF", side=-1)
t.path([(800, yy), (800, GNDY)])
t.dot(800, GNDY)
t.dot(860, D10Y)
yy = t.cap_v(860, D10Y, "C4", "100 nF", side=-1)
t.path([(860, yy), (860, 700), (580, 700), (580, GNDY)])
t.dot(580, GNDY)

# zasilanie z arkusza 1 (MP1584)
t.term(1420, 132, "")
t.txt(1408, 137, "5 V   (M6, arkusz 1)", "te")
t.term(1420, 166, "")
t.txt(1408, 171, "GND  (M6, arkusz 1)", "te")
t.path([(1420, 132), (1500, 132), (1500, 786), (540, 786), (540, V5Y), (NX, V5Y)])
t.wn(1330, 772, 25)
t.path([(1420, 166), (1466, 166), (1466, 764), (500, 764), (500, GNDY)])
t.dot(500, GNDY)

t.a('<line class="wd" x1="40" y1="820" x2="1580" y2="820"/>')

# --- sterowanie przyciskiem
t.sect(40, 872, "E", "STEROWANIE PRZYCISKIEM ZASILANIA M910q")
m7 = t.module(660, 900, 220, 210, "M7", "MODUŁ PRZEKAŹNIKA 5 V",
              "1-kanałowy, z optoizolacją",
              left=[("in", "IN"), ("vcc", "VCC"), ("gnd", "GND")],
              right=[("com", "COM"), ("no", "NO")], cls="blkr")
# A0 → IN
t.path([(np_["a0"][0], np_["a0"][1]), (1230, np_["a0"][1]), (1230, 856),
        (580, 856), (580, m7["in"][1]), (m7["in"][0], m7["in"][1])])
t.wn(940, 842, 21)
# 5 V → VCC   (z tego samego toru co zasilanie Nano)
t.dot(606, 786)
t.path([(606, 786), (606, m7["vcc"][1]), (m7["vcc"][0], m7["vcc"][1])])
t.wn(606, m7["vcc"][1] - 15, 22)
# GND → GND
t.dot(632, 764)
t.path([(632, 764), (632, m7["gnd"][1]), (m7["gnd"][0], m7["gnd"][1])])

# przycisk M910q — styki przekaźnika równolegle
BX, BY = 1180, 900
t.box(BX, BY, 320, 210)
t.txt(BX + 160, BY + 30, "M910q — PRZYCISK ZASILANIA", "lbb")
t.w(BX, BY + 70, BX + 76, BY + 70)
t.a(f'<circle class="sym" cx="{BX+80}" cy="{BY+70}" r="4.5" fill="#fff"/>')
t.a(f'<circle class="sym" cx="{BX+80}" cy="{BY+120}" r="4.5" fill="#fff"/>')
t.w(BX, BY + 120, BX + 76, BY + 120)
t.w(BX + 84, BY + 66, BX + 84, BY + 124)
t.w(BX + 84, BY + 95, BX + 104, BY + 95)
t.w(BX + 104, BY + 82, BX + 104, BY + 108, "sym")
t.txt(BX + 120, BY + 74, "zacisk 1", "pin")
t.txt(BX + 120, BY + 124, "zacisk 2", "pin")
t.txt(BX + 160, BY + 156, "oryginalny przycisk działa dalej — styki", "vc")
t.txt(BX + 160, BY + 174, "przekaźnika RÓWNOLEGLE do niego", "vc")
t.txt(BX + 160, BY + 196, "zaciski znajdź miernikiem ciągłości", "vc")
t.path([(m7["com"][0], m7["com"][1]), (1060, m7["com"][1]), (1060, BY + 70),
        (BX, BY + 70)])
t.wn(1120, BY + 56, 23)
t.path([(m7["no"][0], m7["no"][1]), (1020, m7["no"][1]), (1020, BY + 120),
        (BX, BY + 120)])
t.wn(1120, BY + 106, 24)

# tabela impulsów
t.box(60, 900, 480, 210, "note")
t.txt(80, 928, "Impuls na A0 — sekwencje z sensor_hub.ino", "nh")
for i, (a_, b_) in enumerate([("250 ms przy pracy", "uśpienie do S3"),
                              ("250 ms w S3", "wybudzenie w ~3 s"),
                              ("250 ms po wyłączeniu", "start zimny, ~40 s"),
                              ("5 s", "twarde wyłączenie, ~80–120 mA")]):
    yy = 958 + i * 25
    t.txt(80, yy, a_, "nt")
    t.txt(280, yy, "→", "nt")
    t.txt(306, yy, b_, "nt")
t.txt(80, 1070, "Zapłon potwierdzany 2 s — zapad przy", "nt")
t.txt(80, 1090, "rozruchu nie usypia BCM. Zamiar jest jednorazowy.", "nt")

# kamera
t.box(60, 1140, 1500, 62, "note")
t.txt(80, 1164, "KAMERA USB (podróbka C920, za tylną szybą)", "nh")
t.txt(80, 1186, "Wpięta wprost w port USB M910q — nie przechodzi przez Arduino. "
                "Bieg wsteczny tylko PRZEŁĄCZA obraz na ekran; strumień leci cały "
                "czas i jest nagrywany. W S3 port USB gaśnie i kamera milknie — "
                "to normalne.", "nt")

t.save("schematics/schematic_test_signals.svg")
print("ok")
