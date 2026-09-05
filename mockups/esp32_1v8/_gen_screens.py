# -*- coding: utf-8 -*-
"""Generator artboardow wyswietlacza 1,8" na ESP32.

Panel ST7735 128x160 px w pionie (dluzsza krawedz pionowo). Kazdy artboard
rysuje ekran w prawdziwych pikselach wyswietlacza w kontenerze
przeskalowanym scale(4), wiec kazde "px" w srodku to jeden piksel panelu.
"""

import _icons
from _icons import telltale, ABS, AIRBAG, IMMO, BRAKE, CRUISE

W, H = 128, 160

BG = "#0a0a0a"
LINE = "#27272a"
TEXT = "#f4f4f5"
TEXT_MID = "#a1a1aa"
TEXT_DIM = "#52525b"
AMBER = "#f59e0b"
GREEN = "#22c55e"
OFF = _icons.OFF

# --- bryla auta: rzut z gory Alfy 156 Berlina, nos u gory ---------------
# 1 jednostka rysunku ~ 39,6 mm; nadwozie zajmuje x 0..44, y 0..112.

DIM = "#6a6a73"
BODY = "#b4b4bc"
GLASS = "#18181b"
OPEN = "#ef4444"

BODY_PATH = (
    "M22 0.5c7.5 0 12.5 2 14.5 6L39.5 15c2 5 3 11 3.5 19"
    "c.5 9 .5 26 0 42c-.5 13-2 22-4.5 28c-2 4.5-8.5 7.5-16.5 7.5"
    "s-14.5-3-16.5-7.5c-2.5-6-4-15-4.5-28c-.5-16-.5-33 0-42"
    "c.5-8 1.5-14 3.5-19L7.5 6.5c2-4 7-6 14.5-6Z"
)
BONNET = "M8.5 10h27l2.5 22h-32Z"
TRUNK = "M7.5 88h29l-2 15h-25Z"
BONNET_LID = "M8 8h28l3-13h-34Z"
TRUNK_LID = "M9.5 105h25l3.5 12h-32Z"
VIEWBOX = "-15 -8 74 127"

FLAPS = {
    "fl": "M1.5 45-10.5 47-12 58 1.5 63.5Z",
    "rl": "M1.5 66.5-10 68.5-11.5 79 1.5 85Z",
    "fr": "M42.5 45 54.5 47 56 58 42.5 63.5Z",
    "rr": "M42.5 66.5 54 68.5 55.5 79 42.5 85Z",
}


def car(width, height, open_set):
    """Bryla auta. Uniesione pokrywy i wychylone drzwi rysowane na wierzchu
    obrysu, zeby sylwetka czytala sie takze przy wszystkim otwartym."""
    o = open_set.__contains__
    p = ['<svg viewBox="%s" width="%s" height="%s" fill="none" preserveAspectRatio="xMidYMid meet"'
         ' aria-label="Rzut z gory Alfa Romeo 156">' % (VIEWBOX, width, height)]

    # 1. wypelnienie nadwozia
    p.append('<path d="%s" fill="#141417"></path>' % BODY_PATH)

    # 2. panele w obrysie
    p.append('<path d="%s" fill="%s" stroke="%s" stroke-width="1"></path>'
             % (BONNET, OPEN if o("bonnet") else "none", OPEN if o("bonnet") else DIM))
    p.append('<path d="M6.5 32h31l-3.5 12h-24Z" fill="%s" stroke="%s" stroke-width="1"></path>' % (GLASS, DIM))
    p.append('<rect x="10" y="44" width="24" height="32" rx="2" fill="%s" stroke="%s" stroke-width="1"></rect>' % (GLASS, DIM))
    p.append('<path d="M10 76h24l3 12h-30Z" fill="%s" stroke="%s" stroke-width="1"></path>' % (GLASS, DIM))
    p.append('<path d="%s" fill="%s" stroke="%s" stroke-width="1"></path>'
             % (TRUNK, OPEN if o("trunk") else "none", OPEN if o("trunk") else DIM))

    # 3. szwy drzwi
    for y in (44, 65.5, 86):
        p.append('<path d="M1.2 %s h9" stroke="%s" stroke-width="0.9"></path>' % (y, DIM))
        p.append('<path d="M42.8 %s h-9" stroke="%s" stroke-width="0.9"></path>' % (y, DIM))

    # 4. obrys nadwozia na wierzchu paneli
    p.append('<path d="%s" fill="none" stroke="%s" stroke-width="1.6"></path>' % (BODY_PATH, BODY))
    p.append('<path d="M1.6 44.5-2.6 46.5 1.4 49.5Z" fill="%s"></path>' % BODY)
    p.append('<path d="M42.4 44.5 46.6 46.5 42.6 49.5Z" fill="%s"></path>' % BODY)

    # 5. to, co odstaje od bryly: skrzydla drzwi i uniesione pokrywy
    for key, d in FLAPS.items():
        if o(key):
            p.append('<path d="%s" fill="%s"></path>' % (d, OPEN))
    if o("bonnet"):
        p.append('<path d="%s" fill="%s"></path>' % (BONNET_LID, OPEN))
    if o("trunk"):
        p.append('<path d="%s" fill="%s"></path>' % (TRUNK_LID, OPEN))

    p.append("</svg>")
    return "\n        ".join(p)


# --- szkielet artboardu -------------------------------------------------

DOC = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <script src="./support.js"></script>
</head>
<body>
<x-dc>
<helmet>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Public+Sans:wght@400;600;700;800;900&display=swap">
  <style>
    body { margin: 0; background: %(bg)s; font-family: 'Public Sans', system-ui, sans-serif; }
    a { color: %(amber)s; } a:hover { color: #b45309; }
  </style>
</helmet>
<div style="position: relative; width: %(fw)dpx; height: %(fh)dpx; overflow: hidden; background: %(bg)s;">
  <div style="position: absolute; top: 0; left: 0; width: %(w)dpx; height: %(h)dpx; transform: scale(4);
              transform-origin: 0 0; background: %(bg)s; display: flex; flex-direction: column;">
%%s
  </div>
</div>
</x-dc>
</body>
</html>
""" % {"bg": BG, "amber": AMBER, "fw": W * 4, "fh": H * 4, "w": W, "h": H}


def now_playing(source, title, artist, progress, abs_lit, airbag_lit, immo_lit, brake_lit, cruise_speed):
    """Ekran 1 — cztery kontrolki w pasmie gornym, metadane posrodku.

    Rozklad jest kontraktem (docs/WYSWIETLACZ_ESP32_1V8.md, "Ekran 1"):
    pasmo gorne 32 px to WSZYSTKIE cztery lampki usterek w kolejnosci
    ABS, hamulec, poduszka, immobilizer — tej samej, ktora ma TELLTALES[]
    w assets.h i InputId w state.h. Pasmo dolne 36 px nalezy w calosci do
    tempomatu, a jego lewe 40 px zostaje PUSTE jako rezerwa (miejsce na
    przyszla piata informacje, np. temperature zewnetrzna).
    """
    if cruise_speed is None:
        cruise_slot = ('%s\n        <span style="font-size: 12px; font-weight: 800; letter-spacing: 1.4px;'
                       ' color: %s;">---</span>' % (telltale(CRUISE, False), OFF))
    else:
        cruise_slot = ('%s\n        <div style="display: flex; align-items: baseline; gap: 2px;">'
                       '<span style="font-size: 16px; font-weight: 900; line-height: 1; letter-spacing: -0.5px;'
                       ' color: %s;">%d</span>'
                       '<span style="font-size: 7px; font-weight: 700; letter-spacing: 0.3px; color: %s;">km/h</span>'
                       '</div>' % (telltale(CRUISE, True), GREEN, cruise_speed, TEXT_DIM))

    body = """
    <div style="height: 32px; flex-shrink: 0; display: flex; align-items: center; justify-content: space-around;
                border-bottom: 1px solid {line};">
      {t_abs}
      {t_brake}
      {t_airbag}
      {t_immo}
    </div>

    <div style="flex-grow: 1; display: flex; flex-direction: column; align-items: center; justify-content: center;
                gap: 6px; padding: 0 8px; min-height: 0;">
      <!-- sam napis, bez trojkata odtwarzania: FONT_LABEL nie ma strzalki,
           wiec firmware dopisuje przy pauzie " . PAUZA" (text_layout.h) -->
      <div style="display: flex; align-items: center;">
        <span style="font-size: 7px; font-weight: 800; letter-spacing: 0.7px; color: {dim};">{source}</span>
      </div>
      <div style="font-size: 15px; font-weight: 800; line-height: 1.15; color: {text}; text-align: center;
                  max-width: 112px; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
                  overflow: hidden;">{title}</div>
      <div style="font-size: 10px; font-weight: 600; line-height: 1.1; color: {mid}; text-align: center;
                  max-width: 112px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">{artist}</div>
      <div style="width: 104px; height: 3px; background: {line}; margin-top: 3px;">
        <div style="width: {progress}%; height: 3px; background: {amber};"></div>
      </div>
    </div>

    <div style="height: 36px; flex-shrink: 0; display: flex; align-items: stretch; border-top: 1px solid {line};">
      <!-- lewe 40 px: rezerwa, celowo puste -->
      <div style="width: 40px;"></div>
      <div style="flex-grow: 1; display: flex; align-items: center; justify-content: center; gap: 3px; padding-right: 3px;">
        {cruise}
      </div>
    </div>
""".format(line=LINE, dim=TEXT_DIM, text=TEXT, mid=TEXT_MID, amber=AMBER,
           source=source, title=title, artist=artist, progress=progress,
           t_abs=telltale(ABS, abs_lit), t_airbag=telltale(AIRBAG, airbag_lit),
           t_immo=telltale(IMMO, immo_lit), t_brake=telltale(BRAKE, brake_lit),
           cruise=cruise_slot)
    return DOC % body


def doors(open_set):
    """Ekran 2 — sama bryla, bez opisow; zaslania ekran 1 na stale."""
    body = """
    <div style="flex-grow: 1; display: flex; align-items: center; justify-content: center;">
        %s
    </div>
""" % car(120, 152, open_set)
    return DOC % body


open("Main.dc.html", "w").write(now_playing(
    "BLUETOOTH", "Nightcall", "Kavinsky", 62,
    abs_lit=False, airbag_lit=False, immo_lit=False, brake_lit=False, cruise_speed=None))

open("NowPlayingActive.dc.html", "w").write(now_playing(
    "ANDROID AUTO", "Interstellar Overdrive", "The Psychedelic Sounds", 24,
    abs_lit=True, airbag_lit=False, immo_lit=False, brake_lit=True, cruise_speed=130))

open("Doors.dc.html", "w").write(doors({"fl", "trunk"}))
open("DoorsAll.dc.html", "w").write(doors({"fl", "fr", "rl", "rr", "bonnet", "trunk"}))
print("ok")
