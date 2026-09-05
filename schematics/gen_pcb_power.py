#!/usr/bin/env python3
"""Generator projektu PCB zasilania buforowanego (dwie płytki do wytrawienia).

Rysuje:
    schematics/pcb_power_schematic.svg — schemat ideowy obu płytek + otoczenie
    schematics/pcb_power_layout.svg    — montażówka 1:1 (widok od strony elementów)
    schematics/pcb_power_etch.svg      — mozaika miedzi 1:1 do termotransferu / fotorezystu

Uruchomienie (z katalogu głównego repo):
    python3 schematics/gen_pcb_power.py

Opis projektu, BOM i procedura trawienia: docs/PCB_ZASILANIE.md.
Numery przewodów i oznaczenia elementów są zgodne z §10
docs/SCHEMATY_POLACZEN.md (K1, K2, D1, D5, D6, D7, C1, F8–F10, M1–M6).
Po zmianie projektu popraw ten plik i wygeneruj SVG ponownie — nie
edytuj SVG ręcznie.

Arkusze 1:1 (layout i mozaika) mają jednostki w mm i linijkę kontrolną
50 mm — drukuj w skali 100 % i sprawdź linijkę przed trawieniem.
"""

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
 .brd{fill:none;stroke:#7a3d8f;stroke-width:2.4;rx:8;stroke-dasharray:9 5}
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
 .tb{font-size:12.5px;font-weight:bold;fill:#0d1c26}
 .gl{font-size:11px;font-weight:bold;fill:#3d4f5c;text-anchor:middle}
 .nh{font-size:13px;font-weight:bold;fill:#0d1c26}
 .nt{font-size:11.5px;fill:#4a5a66}
 .wn{font-size:11px;font-weight:bold;fill:#0d1c26;text-anchor:middle}
 .wnb{fill:#ffffff;stroke:#8b9aa6;stroke-width:1.2;rx:3}
 .brdl{font-size:14px;font-weight:bold;fill:#7a3d8f}
</style>'''


class Sheet:
    """Arkusz schematu w px — te same idiomy co gen_test_schematics.py."""

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

    def res_v(self, x, y, ref, val, side=1):
        """Rezystor pionowy, wejście y, wyjście y+54."""
        self.w(x, y, x, y + 10)
        self.a(f'<rect class="sym" x="{x-10}" y="{y+10}" width="20" height="34" fill="#fff"/>')
        self.w(x, y + 44, x, y + 54)
        if side > 0:
            self.txt(x + 16, y + 24, ref, "r")
            self.txt(x + 16, y + 39, val, "v")
        else:
            self.txt(x - 16, y + 24, ref, "re")
            self.txt(x - 16, y + 39, val, "ve")
        return y + 54

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

    def contact(self, x, y, ref, note=None, ny=44, l_left="30", l_right="87"):
        """Styk zwierny NO, poziomy. Zacisk l_left w x, l_right w x+96."""
        self.w(x, y, x + 14, y)
        self.a(f'<circle class="sym" cx="{x+18}" cy="{y}" r="4.5" fill="#fff"/>')
        self.w(x + 21, y - 3, x + 74, y - 24)
        self.a(f'<circle class="sym" cx="{x+78}" cy="{y}" r="4.5" fill="#fff"/>')
        self.w(x + 82, y, x + 96, y)
        self.a(f'<line class="wd" x1="{x+48}" y1="{y-14}" x2="{x+48}" y2="{y+26}"/>')
        self.txt(x + 48, y - 34 if ny > 0 else y - 52, ref, "rc")
        self.txt(x + 14, y + 22, l_left, "pin")
        self.txt(x + 82, y + 22, l_right, "pine")
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

    def term(self, x, y, t, sub=None, side=1):
        self.a(f'<circle class="term" cx="{x}" cy="{y}" r="7"/>')
        if side > 0:
            self.txt(x - 16, y + 5, t, "te")
            if sub:
                self.txt(x - 16, y + 22, sub, "ve")
        else:
            self.txt(x + 16, y + 5, t, "tb")
            if sub:
                self.txt(x + 16, y + 22, sub, "v")

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
#  SCHEMAT IDEOWY — obie płytki + otoczenie
# ======================================================================
def build_schematic(out_path):
    s = Sheet(1660, 2210,
              "PCB zasilania buforowanego — schemat ideowy dwóch płytek",
              "Płytka A: tor ładowania (K1, ładowarka izolowana, XH-M603 w torze). "
              "Płytka B: dystrybucja szyny za S1 (F8–F11, dzielnik pomiaru banku). "
              "Oznaczenia i numery przewodów zgodne z §10 SCHEMATY_POLACZEN.md.")

    # ------------------------------------------------------------------
    s.sect(40, 122, "A", "PŁYTKA A — TOR ŁADOWANIA (100 × 75 mm, jednostronna)")
    RAIL, ACCY, GMA = 250, 580, 720
    BXL, BXR = 250, 1010         # krawędzie płytki A na rysunku
    LX = 1084                    # listwa L1 przy banku (strona izolowana)

    s.a(f'<rect class="brd" x="{BXL}" y="160" width="{BXR-BXL}" height="610"/>')
    s.txt(BXL + 12, 148, "PŁYTKA A", "brdl")

    # --- akumulator rozruchowy + F1 (poza płytką)
    s.txt(100, 186, "AKUMULATOR", "lbb")
    s.txt(100, 202, "ROZRUCHOWY", "lbb")
    s.battery(100, RAIL, "BT0", "12 V")
    s.w(100, RAIL + 62, 100, 400)
    s.star_gnd(100, 400, "gwiazda")
    s.w(100, RAIL, 130, RAIL)
    s.wn(118, RAIL - 15, 1)
    x = s.fuse_h(130, RAIL, "F1", "15 A")
    s.txt(159, RAIL + 42, "≤ 30 cm od klemy", "vc")
    s.w(x, RAIL, BXL, RAIL)
    s.wn(216, RAIL - 15, 2)
    s.term(BXL, RAIL, "", None)
    s.txt(BXL + 12, RAIL - 14, "X1.1 +AKU", "pin")

    # --- D5 + C1 na płytce, lokalny węzeł masy z zaciskiem X1.2
    s.path([(BXL, RAIL), (400, RAIL)])
    s.dot(300, RAIL)
    s.dot(360, RAIL)
    yy = s.tvs_v(300, RAIL + 10, "D5", "1.5KE33CA")
    s.path([(300, yy), (300, 350)])
    yy = s.cap_v(360, RAIL + 46, "C1", "470 µF/35 V", pol=True)
    s.path([(360, RAIL), (360, RAIL + 46)])
    s.path([(360, yy), (360, 350)])
    s.term(BXL, 320, "", None)
    s.txt(BXL + 8, 314, "X1.2 −", "pin")
    s.path([(BXL, 320), (272, 320), (272, 350), (366, 350)])
    s.dot(300, 350)
    s.dot(360, 350)
    s.dot(330, 350)
    s.path([(330, 350), (330, GMA)])

    # --- styk K1
    x = s.contact(400, RAIL, "K1", "T90 · wlutowany", ny=-32)
    n87x = x + 24
    s.dot(n87x, RAIL)

    # --- brak diody blokującej: ładowarka M1 jest izolowana galwanicznie,
    #     więc prąd z banku nie ma czym wrócić do instalacji auta. Odpada
    #     MBR2545CT razem z radiatorem i 4,4 W strat.
    s.path([(n87x, RAIL), (BXR, RAIL)])
    s.txt(660, RAIL - 22, "bez diody blokującej —", "vc")
    s.txt(660, RAIL - 6, "izolacja w M1 zastępuje MBR2545CT", "vc")
    s.term(BXR, RAIL, "", None)
    s.txt(BXR - 14, RAIL - 14, "X2.1", "pine")
    s.wn(BXR + 60, RAIL - 16, 6)

    # --- M1 moduł CC-CV (poza płytką, po prawej; piny wprost naprzeciw zacisków)
    m1 = s.module(1150, 158, 250, 236, "M1", "ŁADOWARKA IZOLOWANA",
                  "DC-DC B2B · CV 14,40 V / CC 8,0 A",
                  left=(("in+", "IN +"), ("in-", "IN −"),
                        ("out+", "OUT +"), ("out-", "OUT −")), cls="blkc")
    # bariera galwaniczna wewnątrz ładowarki — rysowana między parą wejściową
    # a wyjściową, bo to ona rozdziela masę pojazdu od masy banku
    ybar = (m1["in-"][1] + m1["out+"][1]) / 2
    s.a(f'<line class="wd" x1="1150" y1="{ybar}" x2="1400" y2="{ybar}"/>')
    s.txt(1275, ybar - 8, "izolacja galwaniczna", "vc")
    s.path([(BXR, RAIL), (m1["in+"][0], m1["in+"][1])])
    # IN− → X2.2 (GND)
    s.term(BXR, m1["in-"][1], "", None)
    s.txt(BXR - 14, m1["in-"][1] - 14, "X2.2", "pine")
    s.path([(m1["in-"][0], m1["in-"][1]), (BXR, m1["in-"][1])])
    s.path([(BXR, m1["in-"][1]), (920, m1["in-"][1]), (920, GMA)])
    # OUT+ → L1.1 (listwa przy banku)
    s.term(LX, m1["out+"][1], "", None)
    s.txt(LX - 14, m1["out+"][1] - 14, "L1.1", "pine")
    s.path([(m1["out+"][0], m1["out+"][1]), (LX, m1["out+"][1])])
    # OUT− → L1.2, dalej wprost na masę banku
    s.term(LX, m1["out-"][1], "", None)
    s.txt(LX - 14, m1["out-"][1] + 24, "L1.2", "pine")
    s.path([(m1["out-"][0], m1["out-"][1]), (LX, m1["out-"][1])])
    s.path([(LX, m1["out-"][1]), (1050, m1["out-"][1]), (1050, 690)])
    # L1.1 → L1.3 (mostek w listwie, wejście M2)
    s.path([(LX, m1["out+"][1]), (1064, m1["out+"][1]), (1064, 472), (LX, 472)])

    # --- cewka K1 + D6, zasilana z ACC (X6)
    s.term(BXL, ACCY, "", None)
    s.txt(BXL + 12, ACCY - 14, "X6.1 ZAPŁON / ACC", "pin")
    s.wn(216, ACCY - 15, 4)
    s.path([(190, ACCY), (BXL, ACCY)])
    # Oba napisy są kotwiczone końcem (text-anchor:end), a dłuższy z nich ma
    # ok. 123 px — przy x=120 wychodził poza lewą krawędź arkusza i pierwszy
    # znak był ucinany w rastrze. x=164 stawia jego lewy koniec na marginesie
    # 40 px, tym samym co tytuł i blok notatek, i zostawia 26 px do przewodu.
    s.txt(164, ACCY + 4, "z linii ACC", "te")
    s.txt(164, ACCY + 20, "(albo D+ alternatora)", "ve")
    s.path([(BXL, ACCY), (438, ACCY)])
    s.dot(376, ACCY)
    s.diode_v(376, ACCY + 6, "D6", "1N4007", up=True, side=-1)
    s.coil(438, ACCY, "K1")
    s.path([(376, ACCY + 56), (376, ACCY + 80), (438, ACCY + 80)])
    s.dot(438, ACCY + 80)
    s.path([(438, ACCY + 80), (438, GMA)])
    # X6.2 — przelot ACC dalej (drugi zacisk tej samej złączki)
    s.dot(290, ACCY)
    s.path([(290, ACCY), (290, ACCY + 44), (BXL, ACCY + 44)])
    s.term(BXL, ACCY + 44, "", None)
    s.txt(BXL + 12, ACCY + 64, "X6.2 ACC dalej", "pin")
    s.txt(470, 540, "X6.2 = przelot ACC dalej", "v")
    s.txt(470, 556, "(PC817 przy Arduino, REM wzmacniacza)", "v")

    # --- XH-M603 w torze ładowania (X5): boost OUT+ → M2 IN+ → M2 OUT+ → bank
    m2 = s.module(1150, 380, 250, 214, "M2", "XH-M603",
                  "rozłącznik nadnapięciowy · rozwarcie 15,30 V",
                  left=(("in+", "DC-IN +"), ("in-", "DC-IN −"),
                        ("out+", "OUT +")), cls="blkr")
    yi, yg, yo = m2["in+"][1], m2["in-"][1], m2["out+"][1]
    # X5.1 → M2 IN+ (przewód 7a″)
    s.term(LX, yi, "", None)
    s.txt(LX - 14, yi - 14, "L1.3", "pine")
    s.path([(LX, yi), (m2["in+"][0], yi)])
    s.txt(1140, yi - 10, "7a″", "wn")
    # X5.2 → M2 IN− (GND, przewód 7b)
    s.term(LX, yg, "", None)
    s.txt(LX - 14, yg - 14, "L1.2", "pine")
    s.path([(LX, yg), (m2["in-"][0], yg)])
    s.txt(1140, yg - 10, "7b", "wn")
    s.path([(1050, yg), (LX, yg)])
    s.dot(1050, yg)
    # X5.3 ← M2 OUT+ (przewód 7d″)
    s.term(LX, yo, "", None)
    s.txt(LX - 14, yo - 14, "L1.4", "pine")
    s.path([(m2["out+"][0], yo), (LX, yo)])
    s.txt(1140, yo - 10, "7d″", "wn")
    # X5.3 → X5.4 (ścieżka na płytce) i wyjście na szynę banku
    yb = yo + 36
    s.term(LX, yb, "", None)
    s.txt(LX - 14, yb - 14, "L1.5", "pine")
    s.path([(LX, yo), (1064, yo), (1064, yb), (LX, yb)])
    s.path([(LX, yb), (1120, yb), (1120, 690), (1142, 690)])
    s.wn(1136, 668, 7)
    s.txt(1152, 686, "przewód 7 → SZYNA „+” BANKU", "tb")
    s.txt(1152, 702, "(7 × HR1221W = 35,7 Ah, wkładki FB1…FB7)", "v")
    s.txt(1152, 718, "uwaga: bank wychodzi z L1.5 (+) i L1.6 (−) —", "v")
    s.txt(1152, 734, "bez M2 zewrzyj L1.3 z L1.4 drutem", "v")

    # --- masa płytki A
    s.path([(300, GMA), (930, GMA)], "wg")
    s.txt(560, GMA - 32, "POLE MASY PŁYTKI A", "gl")
    s.txt(560, GMA - 16, "(dolny pas miedzi)", "gl")
    s.path([(520, GMA), (520, GMA + 10)], "wg")
    s.a(f'<circle class="term" cx="520" cy="{GMA+20}" r="10"/>')
    s.a(f'<circle class="symf" cx="520" cy="{GMA+20}" r="3"/>')
    s.txt(540, GMA + 16, "GND — śruba M4, oczko 6 mm²", "tb")
    s.txt(540, GMA + 32, "jedyna masa płytki → punkt gwiazdowy", "v")
    s.path([(520, GMA + 30), (520, GMA + 68), (300, GMA + 68), (300, GMA + 82)], "wg")
    s.star_gnd(300, GMA + 82, "gwiazda")

    # --- wyspa masy banku (strona izolowana) — NIE łączy się z polem masy
    s.dot(1050, 690)
    s.term(LX, 726, "", None)
    s.txt(LX - 14, 746, "L1.6", "pine")
    s.path([(1050, 690), (1050, 726), (LX, 726)], "wg")
    s.a('<rect class="brd" x="1040" y="300" width="88" height="452" fill="none"/>')
    s.txt(1044, 276, "LISTWA L1", "brdl")
    s.txt(560, GMA + 96, "Masa pojazdu i masa banku spotykają się TYLKO w aucie, w jednym punkcie —", "v")
    s.txt(560, GMA + 112, "na płytce nie wolno ich zewrzeć, bo znika cały zysk z izolacji.", "v")

    # ------------------------------------------------------------------
    s.sect(40, 900, "B", "PŁYTKA B — DYSTRYBUCJA SZYNY BUFOROWANEJ (100 × 60 mm, jednostronna)")

    BUS, GB = 1000, 1272
    BBL, BBR = 250, 1180
    s.a(f'<rect class="brd" x="{BBL}" y="936" width="{BBR-BBL}" height="356"/>')
    s.txt(BBL + 12, 926, "PŁYTKA B", "brdl")

    # łańcuch przed płytką: bank → F7 → LVD → S1 → X8
    s.box(40, BUS - 30, 96, 60, "blkc")
    s.txt(88, BUS - 6, "SZYNA „+”", "lbb")
    s.txt(88, BUS + 12, "banku", "vc")
    s.w(136, BUS, 148, BUS)
    s.wn(142, BUS - 17, 8)
    x = s.fuse_h(140, BUS, "F7", "15 A")
    s.box(x + 4, BUS - 26, 60, 52, "blkr")
    s.txt(x + 34, BUS - 4, "M3", "rc")
    s.txt(x + 34, BUS + 14, "LVD", "vc")
    s.w(x + 64, BUS, x + 74, BUS)
    x = s.switch_h(x + 74, BUS, "S1", "wyłącznik główny")
    s.w(x, BUS, BBL, BUS)
    s.wn(x + 18, BUS - 15, 11)
    s.term(BBL, BUS, "", None)
    s.txt(BBL + 12, BUS - 14, "X8.1 SZYNA+", "pin")

    # szyna na płytce + odgałęzienia
    s.path([(BBL, BUS), (1096, BUS)], "wp")
    drops = [
        (380, "F8", "7,5 / 10 A", "X9", "M4 · PRZETWORNICA 19,5 V",
         "XL6019 (45 W) albo „1500 W 30 A” CC-CV",
         "→ wtyk M910q, bezp. 5 A w linii"),
        (600, "F9", "2 A", "X10", "M5 · LM2596 → 5 V",
         "podświetlenie panelu 7”", "→ PWM+ / GND panelu"),
        (790, "F10", "3 A", "X11", "M6 · MP1584 → 5 V",
         "zasilanie Arduino Nano", "→ Nano 5V/GND (przew. 25)"),
        (960, "F11", "5 A", "X12", "AUX 12 V",
         "rezerwa: moduł przekaźników,", "wentylator radiatora"),
    ]
    for dx, fr, fv, xr, mn, ms, ml in drops:
        s.dot(dx, BUS)
        yy = s.fuse_v(dx, BUS, fr, fv)
        s.path([(dx, yy), (dx, 1252)])
        s.term(dx, 1252, "", None)
        s.txt(dx + 12, 1248, xr, "pin")
        s.path([(dx, 1262), (dx, 1310)])
        s.box(dx - 92, 1310, 184, 62, "blkm")
        s.txt(dx, 1332, mn, "mname")
        s.txt(dx, 1350, ms, "vc")
        if ml:
            s.txt(dx, 1366, ml, "vc")

    # dzielnik pomiaru napięcia banku
    DVX = 1096
    s.dot(DVX, BUS)
    yy = s.res_v(DVX, BUS, "R5", "100 kΩ 1 %", side=-1)
    s.dot(DVX, yy + 12)
    sig = yy + 12
    s.path([(DVX, yy), (DVX, sig)])
    yy = s.res_v(DVX, sig + 6, "R6", "27 kΩ 1 %", side=-1)
    s.path([(DVX, sig), (DVX, sig + 6)])
    s.path([(DVX, yy), (DVX, GB)])
    s.path([(DVX, sig), (BBR, sig)])
    s.term(BBR, sig, "", None)
    s.txt(BBR - 14, sig - 14, "J1.1 V_BANK", "pine")
    s.path([(BBR, sig), (1300, sig)])
    s.txt(1310, sig + 4, "→ ADC sensor-huba", "tb")
    s.txt(1310, sig + 20, "(dzielnik: 15 V → 3,2 V)", "v")
    cx7 = 1140
    yy2 = s.cap_v(cx7, sig, "C7", "100 nF")
    s.path([(DVX, sig), (cx7, sig)])
    s.dot(cx7, sig)
    s.path([(cx7, yy2), (cx7, GB)])

    # masa płytki B
    s.path([(BBL, GB), (BBR, GB)], "wg")
    s.txt(700, GB + 16, "POLE MASY PŁYTKI B — dolny pas miedzi", "gl")
    s.term(BBL, GB, "", None)
    s.txt(BBL + 14, GB + 26, "X8.2 GND → gwiazda", "pin")
    s.w(BBL, GB, 200, GB, "wg")
    s.star_gnd(200, GB, "gwiazda")
    s.term(BBR, GB, "", None)
    s.txt(BBR - 14, GB + 26, "J1.2 GND", "pine")

    # ------------------------------------------------------------------
    s.sect(40, 1470, "C", "ZACISKI — CO POD CO")

    rows_a = [
        ("PŁYTKA A", ""),
        ("X1.1 / X1.2", "„+” z F1 15 A (przewód 2) · masa do punktu gwiazdowego"),
        ("X2.1 / X2.2", "M1 IN+ / IN− — wejście ładowarki, strona pojazdu (przewód 6)"),
        ("L1.1 … L1.6", "listwa PRZY BANKU, strona izolowana: L1.1 M1 OUT+ · L1.2 M1 OUT− i M2 DC-IN− · "
         "L1.3 M2 DC-IN+ · L1.4 M2 OUT+ · L1.5 szyna „+” banku · L1.6 masa banku (4 mm²)"),
        
        
        ("X6.1 / X6.2", "zapłon / ACC (przewód 4) · przelot ACC dalej (PC817, REM)"),
        ("GND M4", "oczko 6 mm² → punkt gwiazdowy masy"),
    ]
    rows_b = [
        ("PŁYTKA B", ""),
        ("X8.1 / X8.2", "szyna za S1 (przewód 11) · masa → punkt gwiazdowy"),
        ("X9", "przetwornica 19,5 V IN+ (za F8)"),
        ("X10", "LM2596 IN+ (za F9, przewód 13)"),
        ("X11", "MP1584 IN+ (za F10)"),
        ("X12", "AUX 12 V (za F11) — moduł przekaźników / wentylator"),
        ("J1.1 / J1.2", "V_BANK → ADC sensor-huba · GND sygnałowa"),
    ]
    y0 = 1500
    for i, (a, b) in enumerate(rows_a):
        s.txt(60, y0 + i * 24, a, "tb" if b else "nh")
        s.txt(240, y0 + i * 24, b, "nt")
    for i, (a, b) in enumerate(rows_b):
        s.txt(880, y0 + i * 24, a, "tb" if b else "nh")
        s.txt(1040, y0 + i * 24, b, "nt")

    s.box(40, 1720, 1580, 372, "note")
    notes = [
        ("XH-M603 pracuje W TORZE ładowania (IN+ → OUT+), nie jako pilot przekaźnika K2 — zmiana wobec §6.3.",
         "Zweryfikowane działanie modułu: przekaźnik siedzi wewnętrznie między DC-IN+ a OUT+, a pomiar napięcia "
         "jest po stronie OUT (akumulatora). W układzie „pilot + K2” po zadziałaniu OUT spada do zera przez cewkę "
         "i moduł natychmiast zwiera z powrotem — oscylacja niszczy styki. W torze działa zgodnie z przeznaczeniem: "
         "przy CC 8,0 A (nastawa dla banku siedmiu pakietów, §5.3) płytka modułu pracuje na 80 % swojej "
         "obciążalności — bez komfortowego zapasu; wyżej trzeba modułu z wolnym stykiem i przekaźnika K2. "
         "Moduł mierzy wprost napięcie banku. "
         "Zasilanie ma z toru ładowania, więc na postoju pobór wynosi zero. Progi: rozwarcie 15,30 V, powrót 14,00 V."),
        ("Ładowarka jest IZOLOWANA — stąd dwie masy na płytce A.",
         "M1 to gotowa ładowarka DC-DC typu battery-to-battery z transformatorem, a nie moduł boost. Wejście "
         "(masa pojazdu) i wyjście (masa banku) nie mają wspólnego potencjału, więc prąd ładowania i tętnienia "
         "alternatora nie płyną wspólnym powrotem z prądem odbiorników — bank zostaje jedynym źródłem dla "
         "szyny buforowanej. Konsekwencje na płytce: (1) odpada dioda D1 MBR2545CT wraz z radiatorem, bo izolacja "
         "sama blokuje przepływ wsteczny — mniej o 4,4 W strat; (2) pole masy płytki (X1.2, D5, C1, cewka K1, "
         "M1 IN−) NIE MOŻE stykać się z wyspą masy banku (X3.2, X5.2, X3.3) — prześwit minimum 4 mm, żadnej "
         "przelotki ani zworki; (3) masa banku dochodzi do nadwozia w JEDNYM punkcie w aucie, nie na płytce. "
         "Zwarcie obu mas na płytce nie uszkodzi niczego, ale kasuje cały zysk z izolacji."),
        ("Budowa etapami.",
         "Zanim kupisz M2 (XH-M603), zewrzyj L1.3 z L1.4 kawałkiem przewodu w listwie — tor ładowania działa "
         "bez warstwy nadnapięciowej. Tak samo można zacząć bez M1: ładowanie pomijasz, a płytka B i bank pracują."),
        ("Czego celowo NIE ma na płytkach.",
         "K2, D7 i JP1 (patrz wyżej — pilot odpada), X4 (bank wychodzi z X5.4), REM wzmacniacza (bierz z przelotu "
         "ACC X6.2), drugi TVS, kondensator na szynie za LVD (bank to bufor), NTC rozruchowy (tylko przy czkawce "
         "XL6019 — w linii, poza płytką), kompensacja temperaturowa (wariant B świadomie bez niej), C6 470 µF na "
         "wyjściu przetwornicy 19,5 V (moduł „1500 W 30 A” ma własne kondensatory)."),
        ("Masy.", "Każda płytka ma jeden odpływ masy do punktu gwiazdowego (A: śruba M4 w polu masy, B: X8.2). "
         "Otwory montażowe są odizolowane — tulejki/słupki nylonowe, żeby nie zrobić drugiej drogi masy przez karoserię."),
    ]
    yn = 1748
    for h, t in notes:
        s.txt(60, yn, h, "nh")
        # zawijanie ręczne co ~150 znaków
        words = t.split()
        line, lines = "", []
        for wd in words:
            if len(line) + len(wd) > 148:
                lines.append(line)
                line = wd
            else:
                line = (line + " " + wd).strip()
        lines.append(line)
        for ln in lines:
            yn += 18
            s.txt(78, yn, ln, "nt")
        yn += 30

    s.txt(40, 2140, "Nastawy: M1 CV 14,40 V / CC 8,0 A · M2 rozwarcie 15,30 V, powrót 14,00 V · "
                    "M3 (XH-M609) 11,00 / 12,60 V · przetwornica 19,5 V pod obciążeniem.", "nh")
    s.txt(40, 2164, "Montaż i trawienie: docs/PCB_ZASILANIE.md · mozaika: pcb_power_etch.svg · "
                    "rozmieszczenie: pcb_power_layout.svg", "nt")
    s.save(out_path)


# ======================================================================
#  MODEL PŁYTKI (mm) — pady, ścieżki, pola, sitodruk
# ======================================================================
#
# Wszystkie współrzędne w mm, widok OD STRONY ELEMENTÓW (top view),
# oś +Y w dół. Miedź jest na spodzie (płytka jednostronna).
# Druk mozaiki 1:1 w tej samej orientacji = strona z tonerem do miedzi
# (termotransfer i fotorezyst — patrz uwagi na arkuszu).
#
# Footprinty wg zweryfikowanych źródeł (datasheet Songle SLA + biblioteka
# KiCad Relay_THT dla T90/L90; KiCad Fuse.pretty dla oprawki ATO):
#   T90/SLA:  COM-A (0,0) · cewka (2.54,±5.1) · COM-B (15.2,−8.9)
#             NO (17.74,+8.9) · NC (25.34,+8.9); styki Φ2,0, cewka Φ1,1
#   ATO 2pin: otwory Φ2,0 w rozstawie 9,2 mm + czop Φ2,4 w (±1.2, 4.6)

class Pcb:
    def __init__(self, name, w, h):
        self.name, self.w, self.h = name, w, h
        self.pads = []      # (x, y, kind, a, b, drill, net, label)
        self.traces = []    # (net, width, [pts])
        self.pours = []     # (net, x, y, w, h)
        self.holes = []     # (x, y, drill, ring)  — otwory odizolowane
        self.silk = []      # ('rect'|'circle'|'line'|'text', ...)
        self.ctext = []     # napisy w miedzi: (x, y, s, h)

    def pad(self, x, y, kind, a, b, drill, net, label=""):
        self.pads.append((x, y, kind, a, b, drill, net, label))

    def trace(self, net, width, pts):
        self.traces.append((net, width, pts))

    def pour(self, net, x, y, w, h):
        self.pours.append((net, x, y, w, h))

    def hole(self, x, y, drill, ring=7.0):
        self.holes.append((x, y, drill, ring))

    # ---------------- kontrola spójności ----------------
    def _pt_on_seg(self, px, py, ax, ay, bx, by, tol):
        vx, vy = bx - ax, by - ay
        ln2 = vx * vx + vy * vy
        if ln2 == 0:
            return abs(px - ax) <= tol and abs(py - ay) <= tol
        t = max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / ln2))
        dx, dy = px - (ax + t * vx), py - (ay + t * vy)
        return (dx * dx + dy * dy) ** 0.5 <= tol

    def _seg_dist(self, a, b, c, d):
        def pd(p, a, b):
            vx, vy = b[0] - a[0], b[1] - a[1]
            ln2 = vx * vx + vy * vy
            if ln2 == 0:
                return ((p[0] - a[0]) ** 2 + (p[1] - a[1]) ** 2) ** 0.5
            t = max(0.0, min(1.0, ((p[0] - a[0]) * vx + (p[1] - a[1]) * vy) / ln2))
            return ((p[0] - a[0] - t * vx) ** 2 + (p[1] - a[1] - t * vy) ** 2) ** 0.5
        return min(pd(a, c, d), pd(b, c, d), pd(c, a, b), pd(d, a, b))

    def check(self):
        errs = []
        # 1) każdy pad z siecią leży na ścieżce/polu swojej sieci
        for (x, y, kind, a, b, drill, net, lab) in self.pads:
            if net is None:
                continue
            ok = False
            for (tn, tw, pts) in self.traces:
                if tn != net:
                    continue
                for i in range(len(pts) - 1):
                    if self._pt_on_seg(x, y, *pts[i], *pts[i + 1], tol=0.05):
                        ok = True
            for (pn, px, py, pw, ph) in self.pours:
                if pn == net and px - 0.1 <= x <= px + pw + 0.1 \
                        and py - 0.1 <= y <= py + ph + 0.1:
                    ok = True
            if not ok:
                errs.append(f"{self.name}: pad {lab or net} ({x},{y}) "
                            f"wisi poza ścieżką sieci {net}")
        # 2) ścieżki jednej sieci tworzą jedną spójną całość (z polami)
        for net in {t[0] for t in self.traces}:
            items = [t for t in self.traces if t[0] == net]
            pr = [p for p in self.pours if p[0] == net]
            n = len(items) + len(pr)
            parent = list(range(n))

            def find(i):
                while parent[i] != i:
                    parent[i] = parent[parent[i]]
                    i = parent[i]
                return i

            for i in range(n):
                for j in range(i + 1, n):
                    touch = False
                    if i < len(items) and j < len(items):
                        for p in items[i][2]:
                            for k in range(len(items[j][2]) - 1):
                                if self._pt_on_seg(p[0], p[1], *items[j][2][k],
                                                   *items[j][2][k + 1], tol=0.05):
                                    touch = True
                        for p in items[j][2]:
                            for k in range(len(items[i][2]) - 1):
                                if self._pt_on_seg(p[0], p[1], *items[i][2][k],
                                                   *items[i][2][k + 1], tol=0.05):
                                    touch = True
                    elif i >= len(items) and j >= len(items):
                        _, x1, y1, w1, h1 = pr[i - len(items)]
                        _, x2, y2, w2, h2 = pr[j - len(items)]
                        if not (x1 > x2 + w2 + 0.1 or x2 > x1 + w1 + 0.1 or
                                y1 > y2 + h2 + 0.1 or y2 > y1 + h1 + 0.1):
                            touch = True
                    else:
                        tr = items[i] if i < len(items) else items[j]
                        po = pr[(j if j >= len(items) else i) - len(items)]
                        _, px, py, pw, ph = po
                        for p in tr[2]:
                            if px - 0.1 <= p[0] <= px + pw + 0.1 \
                                    and py - 0.1 <= p[1] <= py + ph + 0.1:
                                touch = True
                    if touch:
                        parent[find(i)] = find(j)
            roots = {find(i) for i in range(n)}
            if len(roots) > 1:
                errs.append(f"{self.name}: sieć {net} rozspójniona "
                            f"({len(roots)} wysp)")
        # 3) prześwit ścieżka ↔ pad innej sieci
        for (tn, tw, pts) in self.traces:
            for (x, y, kind, a, b, drill, net, lab) in self.pads:
                if net == tn:
                    continue
                r = max(a, b) / 2
                for i in range(len(pts) - 1):
                    d = self._seg_dist(pts[i], pts[i + 1], (x, y), (x, y))
                    if d < tw / 2 + r + 0.65:
                        errs.append(f"{self.name}: prześwit {tn}↔pad "
                                    f"{lab or net} ({x},{y}) = "
                                    f"{d - tw/2 - r:.2f} mm")
        # 4) prześwit ścieżka ↔ ścieżka innej sieci
        for i1, (n1, w1, p1) in enumerate(self.traces):
            for (n2, w2, p2) in self.traces[i1 + 1:]:
                if n1 == n2:
                    continue
                for i in range(len(p1) - 1):
                    for j in range(len(p2) - 1):
                        d = self._seg_dist(p1[i], p1[i + 1], p2[j], p2[j + 1])
                        if d < w1 / 2 + w2 / 2 + 0.65:
                            errs.append(f"{self.name}: prześwit {n1}↔{n2} "
                                        f"= {d - w1/2 - w2/2:.2f} mm")
        return errs


# ---------------------------------------------------------------------
def footprint_kf(p, x, y, n, pitch, vert, nets, labels, drill, pad_d, body_len=None):
    """Złączka śrubowa KF: n padów co pitch, pionowo (vert) lub poziomo."""
    L = body_len or (n * pitch + 0.2)
    for i in range(n):
        px, py = (x, y + i * pitch) if vert else (x + i * pitch, y)
        p.pad(px, py, "c", pad_d, pad_d, drill, nets[i], labels[i])
    if vert:
        p.silk.append(("rect", x - 4.8, y - (L - (n - 1) * pitch) / 2,
                       9.6, L, None))
    else:
        p.silk.append(("rect", x - (L - (n - 1) * pitch) / 2, y - 4.8,
                       L, 9.6, None))


def footprint_t90(p, ox, oy, nets):
    """Przekaźnik T90/SLA. Origin = pin COM-A. nets: dict com/no/coil1/coil2."""
    p.pad(ox, oy, "c", 4.0, 4.0, 2.0, None, "K1:COM-A (wolny)")
    p.pad(ox + 2.54, oy - 5.1, "c", 2.2, 2.2, 1.2, nets["coil1"], "K1:86")
    p.pad(ox + 2.54, oy + 5.1, "c", 2.2, 2.2, 1.2, nets["coil2"], "K1:85")
    p.pad(ox + 15.2, oy - 8.9, "c", 4.0, 4.0, 2.0, nets["com"], "K1:30 (COM)")
    p.pad(ox + 17.74, oy + 8.9, "c", 4.0, 4.0, 2.0, nets["no"], "K1:87 (NO)")
    p.pad(ox + 25.34, oy + 8.9, "c", 4.0, 4.0, 2.0, None, "K1:NC (wolny)")
    p.silk.append(("rect", ox - 3.96, oy - 13.2, 31.8, 27.4, "K1"))


def footprint_fuse_ato(p, x, y, net_top, net_bot, ref):
    """Oprawka ATO 2-pin pionowo: otwory Φ2 co 9,2 mm + czop Φ2,4."""
    p.pad(x, y, "o", 6.0, 4.0, 2.0, net_top, f"{ref}:1")
    p.pad(x, y + 9.2, "o", 6.0, 4.0, 2.0, net_bot, f"{ref}:2")
    p.hole(x + 1.2, y + 4.6, 2.4, 3.4)
    p.silk.append(("rect", x - 3.2, y - 3.0, 6.4, 15.2, ref))


# ---------------------------------------------------------------------
def build_board_a():
    """Płytka A po przejściu na ładowarkę izolowaną.

    Zostaje wyłącznie strona pojazdu: bezpiecznik, ochrona przepięciowa,
    przekaźnik ładowania i wyjście na wejście ładowarki. Strona izolowana
    (wyjście ładowarki, XH-M603, bank) nie ma tu czego szukać — to trzy
    przewody schodzące się na szynie banku, a nie zaciski na tej płytce.
    Dzięki temu płytka ma znów JEDNĄ masę i nie trzeba dzielić pola miedzi.
    """
    p = Pcb("PŁYTKA A — ŁADOWANIE (strona pojazdu)", 100, 75)

    # --- lewa kolumna zacisków
    footprint_kf(p, 9, 8, 2, 7.62, True, ["AKU", "GND"],
                 ["X1.1 +AKU", "X1.2 −"], 1.5, 4.4)
    footprint_kf(p, 9, 27, 2, 5.0, True, ["ACC", "ACC"],
                 ["X6.1 ACC", "X6.2 ACC dalej"], 1.3, 3.0)

    # --- prawa kolumna: wyłącznie wejście ładowarki
    footprint_kf(p, 90, 8, 2, 7.62, True, ["CHGIN", "GND"],
                 ["X2.1 → M1 IN+", "X2.2 → M1 IN−"], 1.5, 4.4)

    # --- elementy
    p.pad(16, 8, "c", 2.8, 2.8, 1.3, "AKU", "D5:a")
    p.pad(16, 20.7, "c", 2.8, 2.8, 1.3, "GND", "D5:b")
    p.silk.append(("rect", 13.4, 9.6, 5.2, 9.6, "D5"))
    p.pad(26, 8, "c", 2.4, 2.4, 1.0, "AKU", "C1:+")
    p.pad(26, 13, "c", 2.4, 2.4, 1.0, "GND", "C1:−")
    p.silk.append(("circle", 26, 10.5, 5.2, "C1"))
    footprint_t90(p, 40, 21, {"coil1": "ACC", "coil2": "GND",
                              "com": "AKU", "no": "CHGIN"})
    p.pad(30, 36, "c", 2.2, 2.2, 1.0, "ACC", "D6:k")
    p.pad(30, 46.16, "c", 2.2, 2.2, 1.0, "GND", "D6:a")
    p.silk.append(("rect", 27.9, 37.6, 4.2, 7.0, "D6"))

    # --- ścieżki
    p.trace("AKU", 6, [(9, 8), (50, 8)])
    p.trace("AKU", 4, [(50, 8), (55.2, 8), (55.2, 12.1)])
    p.trace("GND", 3, [(9, 15.62), (11, 20.7), (26, 20.7)])
    p.trace("GND", 2.5, [(26, 13), (26, 20.7)])
    p.trace("GND", 3, [(9, 15.62), (4, 15.62), (4, 66.5)])
    p.trace("ACC", 2, [(9, 27), (9, 32)])
    p.trace("ACC", 2.5, [(9, 32), (34, 32), (34, 15.9), (42.54, 15.9)])
    p.trace("ACC", 2, [(30, 36), (30, 32)])
    p.trace("GND", 2, [(30, 46.16), (30, 66.5)])
    p.trace("GND", 2, [(42.54, 26.1), (42.54, 66.5)])
    # styk 87 przekaźnika wprost na zacisk wejścia ładowarki — bez diody
    p.trace("CHGIN", 4, [(57.74, 29.9), (57.74, 18), (85, 18), (85, 10), (90, 8)])
    p.trace("GND", 3.5, [(90, 15.62), (96, 15.62)])
    p.trace("GND", 5, [(96, 15.62), (96, 66.5)])

    # --- pole masy + śruba M4 + otwory montażowe
    p.pour("GND", 3, 66, 94, 6)
    p.pour("GND", 46, 62, 16, 10)
    p.pad(54, 68.5, "c", 11, 11, 4.5, "GND", "GND M4 → gwiazda")
    for hx, hy in ((4, 4), (96, 4), (4, 71), (96, 71)):
        p.hole(hx, hy, 3.2)
    p.ctext.append((57, 59.5, "BCM-A", 3.2))
    p.ctext.append((70, 45, "wolne pole — po usunięciu D1", 2.4))
    p.ctext.append((70, 50, "i zacisków strony izolowanej", 2.4))
    return p


def build_board_b():
    p = Pcb("PŁYTKA B — DYSTRYBUCJA", 100, 60)

    footprint_kf(p, 9, 10, 2, 7.62, True, ["GND", "BUS"],
                 ["X8.2 GND → gwiazda", "X8.1 SZYNA+ (za S1)"], 1.5, 4.4)
    footprint_fuse_ato(p, 24, 27, "BUS", "F8O", "F8")
    footprint_fuse_ato(p, 42, 27, "BUS", "F9O", "F9")
    footprint_fuse_ato(p, 58, 27, "BUS", "F10O", "F10")
    footprint_fuse_ato(p, 74, 27, "BUS", "F11O", "F11")
    footprint_kf(p, 20.2, 52, 2, 7.62, False, ["F8O", "F8O"],
                 ["X9 → M4 IN+", "X9 (drugi)"], 1.5, 4.4)
    footprint_kf(p, 39.5, 52, 2, 5.0, False, ["F9O", "F9O"],
                 ["X10 → M5 IN+", ""], 1.3, 3.0)
    footprint_kf(p, 55.5, 52, 2, 5.0, False, ["F10O", "F10O"],
                 ["X11 → M6 IN+", ""], 1.3, 3.0)
    footprint_kf(p, 71.5, 52, 2, 5.0, False, ["F11O", "F11O"],
                 ["X12 AUX 12 V", ""], 1.3, 3.0)
    footprint_kf(p, 83, 52, 2, 5.0, False, ["SIG", "GND"],
                 ["J1.1 V_BANK", "J1.2 GND"], 1.3, 3.0)

    p.pad(86, 17.62, "c", 2.2, 2.2, 1.0, "BUS", "R5:a")
    p.pad(86, 27.78, "c", 2.2, 2.2, 1.0, "SIG", "R5:b")
    p.silk.append(("rect", 84.4, 19.4, 3.2, 6.6, "R5"))
    p.pad(86, 32, "c", 2.2, 2.2, 1.0, "SIG", "R6:a")
    p.pad(86, 42.16, "c", 2.2, 2.2, 1.0, "GND", "R6:b")
    p.silk.append(("rect", 84.4, 33.8, 3.2, 6.6, "R6"))
    p.pad(93, 32, "c", 2.4, 2.4, 1.0, "SIG", "C7:1")
    p.pad(93, 40, "c", 2.4, 2.4, 1.0, "GND", "C7:2")
    p.silk.append(("rect", 91.4, 33.6, 3.2, 4.8, "C7"))

    p.trace("BUS", 8, [(9, 17.62), (86, 17.62)])
    for x, net in ((24, "F8O"), (42, "F9O"), (58, "F10O"), (74, "F11O")):
        p.trace("BUS", 6, [(x, 17.62), (x, 27)])
        p.trace(net, 6, [(x, 36.2), (x, 52)])
    p.trace("F8O", 6, [(20.2, 52), (27.8, 52)])
    p.trace("F9O", 4, [(39.5, 52), (44.5, 52)])
    p.trace("F10O", 4, [(55.5, 52), (60.5, 52)])
    p.trace("F11O", 4, [(71.5, 52), (76.5, 52)])
    p.trace("SIG", 1.5, [(86, 27.78), (86, 32)])
    p.trace("SIG", 1.5, [(86, 30), (93, 30), (93, 32)])
    p.trace("SIG", 1.5, [(86, 30), (83, 30), (83, 52)])
    p.trace("GND", 2, [(93, 40), (93, 42.16)])
    p.trace("GND", 2, [(86, 42.16), (97, 42.16)])
    p.trace("GND", 2, [(88, 42.16), (88, 52)])
    p.trace("GND", 2, [(9, 10), (14, 5), (97, 5), (97, 42.16)])

    for hx, hy in ((4, 4), (4, 56), (96, 49)):
        p.hole(hx, hy, 3.2)
    p.ctext.append((29, 47.5, "BCM-B", 3.0))
    return p


# ======================================================================
#  ARKUSZE 1:1 (mm)
# ======================================================================
MM_STYLE = '''<style>
 .bg{fill:#ffffff}
 .cu{fill:#111111;stroke:none}
 .cuw{stroke:#111111;fill:none;stroke-linecap:round;stroke-linejoin:round}
 .drl{fill:#ffffff;stroke:none}
 .brd{fill:none;stroke:#111111;stroke-width:0.35}
 .brdg{fill:none;stroke:#98a6b0;stroke-width:0.3}
 .cul{fill:#d8dde2;stroke:none}
 .culw{stroke:#d8dde2;fill:none;stroke-linecap:round;stroke-linejoin:round}
 .drll{fill:#ffffff;stroke:#7d8c99;stroke-width:0.18}
 .sk{fill:none;stroke:#16242e;stroke-width:0.3}
 .ttl{font-size:5px;font-weight:bold;fill:#0d1c26}
 .sub{font-size:2.6px;fill:#576875}
 .h{font-size:3.4px;font-weight:bold;fill:#0d1c26}
 .l{font-size:2.2px;fill:#33424e}
 .lb{font-size:2.4px;font-weight:bold;fill:#0d1c26}
 .r{font-size:2.4px;font-weight:bold;fill:#a8321a}
 .re{font-size:2.4px;font-weight:bold;fill:#a8321a;text-anchor:end}
 .w{font-size:2.2px;fill:#2b4a8a;font-weight:bold}
 .we{font-size:2.2px;fill:#2b4a8a;font-weight:bold;text-anchor:end}
 .n{font-size:2.4px;fill:#4a5a66}
 .nb{font-size:2.6px;font-weight:bold;fill:#0d1c26}
 .ldr{stroke:#7d8c99;stroke-width:0.2;fill:none}
</style>'''


class MmSheet:
    def __init__(self, w, h, title):
        self.o = []
        self.a(f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}mm" '
               f'height="{h}mm" viewBox="0 0 {w} {h}" '
               f'font-family="DejaVu Sans, Verdana, sans-serif">')
        self.a(f'<title>{title}</title>')
        self.a(MM_STYLE)
        self.a(f'<rect class="bg" x="0" y="0" width="{w}" height="{h}"/>')

    def a(self, s):
        self.o.append(s)

    def txt(self, x, y, s, c="l"):
        s = str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        self.a(f'<text class="{c}" x="{x}" y="{y}">{s}</text>')

    def save(self, path):
        self.a("</svg>")
        open(path, "w", encoding="utf-8").write("\n".join(self.o))

    def ruler(self, x, y, ln=50):
        self.a(f'<line x1="{x}" y1="{y}" x2="{x+ln}" y2="{y}" '
               f'stroke="#111" stroke-width="0.3"/>')
        for i in range(ln + 1):
            t = 3 if i % 10 == 0 else (2 if i % 5 == 0 else 1.2)
            self.a(f'<line x1="{x+i}" y1="{y}" x2="{x+i}" y2="{y+t}" '
                   f'stroke="#111" stroke-width="{0.3 if i % 10 == 0 else 0.15}"/>')
        for i in range(0, ln + 1, 10):
            self.txt(x + i - 1.4, y + 6, str(i), "l")
        self.txt(x + ln + 3, y + 3, "mm — po wydruku zmierz: 50 mm ±0,5", "lb")

    def copper(self, b, ox, oy, mirror=False, light=False):
        """Mozaika miedzi. mirror=True → widok od strony miedzi."""
        cu, cuw, drl = ("cul", "culw", "drll") if light else ("cu", "cuw", "drl")
        tr = (f'translate({ox+b.w},{oy}) scale(-1,1)' if mirror
              else f'translate({ox},{oy})')
        self.a(f'<g transform="{tr}">')
        for (net, px, py, pw, ph) in b.pours:
            self.a(f'<rect class="{cu}" x="{px}" y="{py}" width="{pw}" '
                   f'height="{ph}"/>')
        for (net, wd, pts) in b.traces:
            d = "M " + " L ".join(f"{x} {y}" for x, y in pts)
            self.a(f'<path class="{cuw}" stroke-width="{wd}" d="{d}"/>')
        for (x, y, kind, a, bb, drill, net, lab) in b.pads:
            if kind == "c":
                self.a(f'<circle class="{cu}" cx="{x}" cy="{y}" r="{a/2}"/>')
            else:
                self.a(f'<rect class="{cu}" x="{x-a/2}" y="{y-bb/2}" '
                       f'width="{a}" height="{bb}" rx="{min(a,bb)/2}"/>')
        # otwory montażowe: pierścień izolacyjny (biały) + obrys
        for (x, y, drill, ring) in b.holes:
            if ring:
                self.a(f'<circle class="{drl}" cx="{x}" cy="{y}" r="{ring/2}"/>')
        # napisy w miedzi — lustrzane w widoku od elementów, proste na miedzi
        for (x, y, s, hh) in b.ctext:
            self.a(f'<g transform="translate({x},{y}) scale(-1,1)">'
                   f'<text x="{-2*hh*len(s)*0.32}" y="0" font-size="{hh}" '
                   f'font-weight="bold" fill="{"#d8dde2" if light else "#111"}"'
                   f'>{s}</text></g>')
        # wiercenia
        for (x, y, kind, a, bb, drill, net, lab) in b.pads:
            self.a(f'<circle class="{drl}" cx="{x}" cy="{y}" r="{drill/2}"/>')
        for (x, y, drill, ring) in b.holes:
            self.a(f'<circle class="{drl}" cx="{x}" cy="{y}" r="{drill/2}"/>')
        self.a(f'<rect class="brd" x="0" y="0" width="{b.w}" height="{b.h}"/>')
        self.a('</g>')

    def assembly(self, b, ox, oy):
        """Widok montażowy: jasna miedź pod spodem + elementy + opisy."""
        self.copper(b, ox, oy, mirror=False, light=True)
        self.a(f'<g transform="translate({ox},{oy})">')
        for item in b.silk:
            if item[0] == "rect":
                _, x, y, w, h, ref = item
                self.a(f'<rect class="sk" x="{x}" y="{y}" width="{w}" '
                       f'height="{h}" rx="0.8"/>')
                if ref:
                    self.txt(x + 0.8, y - 0.7, ref, "r")
            elif item[0] == "circle":
                _, x, y, d, ref = item
                self.a(f'<circle class="sk" cx="{x}" cy="{y}" r="{d/2}"/>')
                if ref:
                    self.txt(x + d / 2 + 0.5, y + 0.8, ref, "r")
        self.a('</g>')
    # opisy zacisków dodaje się osobno na arkuszu (callouty)


def build_pcb_sheets(layout_path, etch_path):
    A, B = build_board_a(), build_board_b()
    errs = A.check() + B.check()
    if errs:
        raise SystemExit("BŁĘDY PROJEKTU PCB:\n" + "\n".join(errs))

    # ---------------- arkusz montażowy ----------------
    s = MmSheet(210, 297, "PCB zasilania — rozmieszczenie elementów 1:1")
    s.txt(12, 12, "PCB ZASILANIA — ROZMIESZCZENIE 1:1 (od strony elementów)", "ttl")
    s.txt(12, 17, "Miedź (szara) jest na spodzie. Opisy X• zgodne ze schematem "
                  "pcb_power_schematic.svg i §10 SCHEMATY_POLACZEN.md.", "sub")

    ax, ay = 42, 26
    s.txt(ax, ay - 2.5, "PŁYTKA A — ŁADOWANIE · 100 × 75 mm · laminat jednostronny", "h")
    s.assembly(A, ax, ay)
    for (x, y, kind, a, bb, drill, net, lab) in A.pads:
        if not lab or ":" in lab and not lab.startswith(("X", "GND M4")):
            continue
        if x < 50:
            s.a(f'<line class="ldr" x1="{ax+x-a/2-0.4}" y1="{ay+y}" '
                f'x2="{ax-2.5}" y2="{ay+y}"/>')
            s.txt(ax - 3, ay + y + 0.8, lab, "we")
        elif x > 50:
            s.a(f'<line class="ldr" x1="{ax+x+a/2+0.4}" y1="{ay+y}" '
                f'x2="{ax+A.w+2.5}" y2="{ay+y}"/>')
            s.txt(ax + A.w + 3, ay + y + 0.8, lab, "w")
    s.txt(ax, ay + A.h + 4.5, "Strona izolowana (wyjście ładowarki, XH-M603, bank) schodzi się na listwie L1 "
                              "przy banku — nie na tej płytce. Wolne pole zostaje po diodzie D1.", "n")
    s.txt(ax, ay + A.h + 8, "K1: T90/SLA-12VDC-SL-A — pady COM-A i NC wiercone, zostają wolne "
                            "(warianty 4/5/6-pin). C1: 470 µF, raster 5,0 mm.", "n")
    s.txt(ax, ay + A.h + 11.5, "GND M4: śruba M4 z oczkiem 6 mm² do punktu gwiazdowego. Otwory "
                               "montażowe Φ3,2 odizolowane — słupki nylonowe.", "n")

    bx, by = 42, 130
    s.txt(bx, by - 2.5, "PŁYTKA B — DYSTRYBUCJA · 100 × 60 mm · laminat jednostronny", "h")
    s.assembly(B, bx, by)
    for (x, y, kind, a, bb, drill, net, lab) in B.pads:
        if not lab.startswith(("X", "J1")):
            continue
        if y > 44:
            s.a(f'<line class="ldr" x1="{bx+x}" y1="{by+y+bb/2+0.4}" '
                f'x2="{bx+x}" y2="{by+B.h+2.5}"/>')
            s.a(f'<g transform="translate({bx+x-0.8},{by+B.h+4}) rotate(45)">'
                f'<text class="w" x="0" y="0">{lab}</text></g>')
        else:
            s.a(f'<line class="ldr" x1="{bx+x-a/2-0.4}" y1="{by+y}" '
                f'x2="{bx-2.5}" y2="{by+y}"/>')
            s.txt(bx - 3, by + y + 0.8, lab, "we")
    s.txt(bx, by + B.h + 22, "F8: wkładka 7,5 A (XL6019) / 10 A („1500 W 30 A”). F9: 2 A · F10: 3 A · "
                             "F11: 5 A. Oprawki ATO 2-pin: otwory Φ2,0 co 9,2 mm + czop Φ2,4", "n")
    s.txt(bx, by + B.h + 25.5, "albo bezpiecznik wlutowany wprost (pady rozwierć w slot 6×2 mm). "
                               "R5/R6: dzielnik 100/27 kΩ 1 % — V_BANK do ADC (§13.4).", "n")

    s.txt(12, 232, "ELEMENTY LUTOWANE W PŁYTKI (moduły M1–M6 podłączasz do zacisków — nie wlutowujesz):", "h")
    bom = [
        "PŁYTKA A:  K1 = SLA-12VDC-SL-A (T90 30 A) · D5 = 1.5KE33CA · D6 = 1N4007 · "
        "C1 = 470 µF/35 V low-ESR — diody D1 nie ma, ładowarka jest izolowana",
        "           X1/X2 = KF7.62-2P · X6 = KF301-2P · śruba M4 + oczko · L1 = listwa 6-torowa przy banku",
        "PŁYTKA B:  4 × oprawka ATO PCB (albo klipsy) · R5 = 100 kΩ 1 % · R6 = 27 kΩ 1 % · C7 = 100 nF · "
        "X8/X9 = KF7.62-2P · X10–X12, J1 = KF301-2P",
        "Ścieżki mocy (AKU, KL87, CHGIN/OUT, BANK, BUS, F8) pocynuj grubo albo wzmocnij drutem 1,5 mm² "
        "wzdłuż ścieżki. Sieci: patrz pcb_power_etch.svg.",
    ]
    for i, t in enumerate(bom):
        s.txt(12, 237 + i * 3.6, t, "n")
    s.ruler(12, 258)
    s.txt(12, 272, "Wygenerowano: schematics/gen_pcb_power.py · opis projektu: docs/PCB_ZASILANIE.md", "sub")
    s.save(layout_path)

    # ---------------- arkusz do trawienia ----------------
    e = MmSheet(210, 297, "PCB zasilania — mozaika miedzi 1:1 do trawienia")
    e.txt(12, 12, "MOZAIKA MIEDZI 1:1 — DRUK BEZ SKALOWANIA (100 %)", "ttl")
    e.txt(12, 17, "Orientacja: widok od strony elementów. Termotransfer: drukuj tak jak jest, "
                  "toner do miedzi. Fotorezyst: folia tonerem do płytki.", "sub")
    e.txt(12, 21, "Kontrola po wytrawieniu: napis „BCM-•” ma się czytać poprawnie "
                  "patrząc NA MIEDŹ.", "sub")

    ax, ay = 16, 30
    e.txt(ax, ay - 2.5, "PŁYTKA A · 100 × 75 mm", "h")
    e.copper(A, ax, ay)
    bx, by = 16, 115
    e.txt(bx, by - 2.5, "PŁYTKA B · 100 × 60 mm", "h")
    e.copper(B, bx, by)

    cx = 128
    e.txt(cx, 27.5, "KONTROLA — od strony miedzi (55 %)", "h")
    e.a(f'<g transform="translate({cx},30) scale(0.55)">')
    e.copper(A, 0, 0, mirror=True, light=True)
    e.copper(B, 0, 82, mirror=True, light=True)
    e.a('</g>')

    e.txt(cx, 116, "WIERCENIE", "h")
    drills = [
        ("Φ 1,0", "R5, R6, C7, C1, D6"),
        ("Φ 1,2", "cewka K1"),
        ("Φ 1,3", "KF301 (X6, X10–X12, J1), D5"),
        ("Φ 1,5", "KF7.62 (X1, X2, X8, X9)"),
        ("Φ 2,0", "styki K1 (COM/NO/NC), pady bezpieczników"),
        ("Φ 2,4", "czopy oprawek ATO (bez miedzi)"),
        ("Φ 3,2", "otwory montażowe (odizolowane)"),
        ("Φ 4,5", "śruba masy M4 (płytka A)"),
    ]
    for i, (d, t) in enumerate(drills):
        e.txt(cx, 121 + i * 3.6, d, "lb")
        e.txt(cx + 12, 121 + i * 3.6, t, "n")

    e.ruler(16, 186)
    e.txt(12, 200, "PROCES (termotransfer):", "h")
    steps = [
        "1. Wydruk laserowy 1:1 na papierze kredowym, tryb najciemniejszy. Zmierz linijkę!",
        "2. Laminat przetrzyj acetonem, papierem ściernym 400 na mokro, znów acetonem.",
        "3. Żelazko ~180 °C przez 2–4 min przez kartkę, dociskaj równomiernie.",
        "4. Mocz w wodzie 10 min, zroluj papier palcem. Ubytki popraw markerem permanentnym.",
        "5. Traw w B327 (nadsiarczan sodu, ~45 °C) albo FeCl3. Poruszaj kuwetą.",
        "6. Toner zmyj acetonem. Przewierć otwory wg tabeli (najpierw 1,0, potem rozwiercaj).",
        "7. Ścieżki mocy pocynuj grubą warstwą albo przylutuj wzdłuż drut 1,5 mm².",
        "8. Kontrola: omomierzem sąsiednie sieci (zwarcia) i ciągłość każdej ścieżki.",
    ]
    for i, t in enumerate(steps):
        e.txt(12, 205 + i * 3.8, t, "n")
    e.txt(12, 240, "Sieci na płytce A: AKU (X1→K1) · CHGIN (styk 87 → X2.1 → M1 IN+) · "
                   "ACC (cewka K1) · GND (pole dolne). Strona izolowana jest poza płytką — listwa L1.", "n")
    e.txt(12, 244, "Sieci na płytce B: BUS (X8→bezpieczniki) · F8O–F11O (odgałęzienia) · "
                   "SIG (dzielnik) · GND (obwódka górna).", "n")
    e.txt(12, 252, "Wygenerowano: schematics/gen_pcb_power.py — nie edytuj SVG ręcznie.", "sub")
    e.save(etch_path)


if __name__ == "__main__":
    build_schematic("schematics/pcb_power_schematic.svg")
    build_pcb_sheets("schematics/pcb_power_layout.svg",
                     "schematics/pcb_power_etch.svg")
    print("OK: pcb_power_schematic.svg, pcb_power_layout.svg, pcb_power_etch.svg")
