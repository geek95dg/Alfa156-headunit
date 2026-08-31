# -*- coding: utf-8 -*-
"""Generator artboardow ekranu 2 (rzut z gory Alfy 156 Berlina).

Geometria auta zyje w jednym miejscu, zeby wszystkie warianty ekranu
rysowaly dokladnie te sama bryle. Uklad wspolrzednych: nos u gory,
nadwozie zajmuje x 0..44, y 0..112 (4430 x 1743 mm w skali 1 j. = 39,6 mm).
"""

DIM = "#6a6a73"        # szwy zamknietych paneli
BODY = "#8a8a92"       # obrys nadwozia
GLASS = "#18181b"      # szyby i dach
OPEN = "#ef4444"       # panel otwarty

# Nadwozie: zaokraglony nos, szeroki przelot nadkoli, krotki tyl.
BODY_PATH = (
    "M22 0.5c7.5 0 12.5 2 14.5 6L39.5 15c2 5 3 11 3.5 19"
    "c.5 9 .5 26 0 42c-.5 13-2 22-4.5 28c-2 4.5-8.5 7.5-16.5 7.5"
    "s-14.5-3-16.5-7.5c-2.5-6-4-15-4.5-28c-.5-16-.5-33 0-42"
    "c.5-8 1.5-14 3.5-19L7.5 6.5c2-4 7-6 14.5-6Z"
)

BONNET = "M8.5 10h27l2.5 22h-32Z"
TRUNK = "M7.5 88h29l-2 15h-25Z"
# Uniesiona pokrywa - wysunieta poza obrys, oddzielona szczelina zagiecia.
BONNET_LID = "M8 8h28l3-13h-34Z"
TRUNK_LID = "M9.5 105h25l3.5 12h-32Z"

VIEWBOX = "-15 -8 74 127"

FLAPS = {
    "fl": "M1.5 45-10.5 47-12 58 1.5 63.5Z",
    "rl": "M1.5 66.5-10 68.5-11.5 79 1.5 85Z",
    "fr": "M42.5 45 54.5 47 56 58 42.5 63.5Z",
    "rr": "M42.5 66.5 54 68.5 55.5 79 42.5 85Z",
}


def car_body(open_set):
    """Same ksztalty, bez elementu <svg> - zeby dalo sie je obrocic."""
    o = open_set.__contains__
    p = []
    p.append('<path d="%s" fill="#141417" stroke="%s" stroke-width="1.4"></path>' % (BODY_PATH, BODY))

    if o("bonnet"):
        p.append('<path d="%s" fill="%s"></path>' % (BONNET, OPEN))
        p.append('<path d="%s" fill="%s"></path>' % (BONNET_LID, OPEN))
    else:
        p.append('<path d="%s" fill="none" stroke="%s" stroke-width="1"></path>' % (BONNET, DIM))

    p.append('<path d="M6.5 32h31l-3.5 12h-24Z" fill="%s" stroke="%s" stroke-width="1"></path>' % (GLASS, DIM))
    p.append('<rect x="10" y="44" width="24" height="32" rx="2" fill="%s" stroke="%s" stroke-width="1"></rect>' % (GLASS, DIM))
    p.append('<path d="M10 76h24l3 12h-30Z" fill="%s" stroke="%s" stroke-width="1"></path>' % (GLASS, DIM))

    if o("trunk"):
        p.append('<path d="%s" fill="%s"></path>' % (TRUNK, OPEN))
        p.append('<path d="%s" fill="%s"></path>' % (TRUNK_LID, OPEN))
    else:
        p.append('<path d="%s" fill="none" stroke="%s" stroke-width="1"></path>' % (TRUNK, DIM))

    p.append('<path d="M1.6 44.5-2.6 46.5 1.4 49.5Z" fill="%s"></path>' % BODY)
    p.append('<path d="M42.4 44.5 46.6 46.5 42.6 49.5Z" fill="%s"></path>' % BODY)

    for y in (44, 65.5, 86):
        p.append('<path d="M1.2 %s h9" stroke="%s" stroke-width="0.9"></path>' % (y, DIM))
        p.append('<path d="M42.8 %s h-9" stroke="%s" stroke-width="0.9"></path>' % (y, DIM))

    for key, d in FLAPS.items():
        if o(key):
            p.append('<path d="%s" fill="%s"></path>' % (d, OPEN))

    return "\n          ".join(p)


def car_portrait(width, height, open_set):
    return ('<svg viewBox="%s" width="%s" height="%s" fill="none" preserveAspectRatio="xMidYMid meet" '
            'aria-label="Rzut z gory Alfa Romeo 156">\n          %s\n        </svg>'
            % (VIEWBOX, width, height, car_body(open_set)))


def car_landscape(width, height, open_set):
    """Ten sam rysunek obrocony nosem w lewo."""
    return ('<svg viewBox="-8 0 130 76" width="%s" height="%s" fill="none" preserveAspectRatio="xMidYMid meet" '
            'aria-label="Rzut z gory Alfa Romeo 156">\n        <g transform="translate(0 60) rotate(-90)">\n          %s\n        </g>\n        </svg>'
            % (width, height, car_body(open_set)))


HEAD = """<!doctype html>
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
    body { margin: 0; background: #0a0a0a; font-family: 'Public Sans', system-ui, sans-serif; }
    a { color: #f59e0b; } a:hover { color: #b45309; }
  </style>
</helmet>
<div style="position: relative; width: 640px; height: 512px; overflow: hidden; background: #0a0a0a;">
  <div style="position: absolute; top: 0; left: 0; width: 160px; height: 128px; transform: scale(4); transform-origin: 0 0; background: #0a0a0a; display: flex;">
"""

TAIL = """  </div>
</div>
</x-dc>
</body>
</html>
"""

NAMES_PL = {
    "fl": "PRZÓD L", "fr": "PRZÓD P",
    "rl": "TYŁ L", "rr": "TYŁ P",
    "bonnet": "MASKA", "trunk": "BAGAŻNIK",
}
ORDER = ["fl", "fr", "rl", "rr", "bonnet", "trunk"]

WARN_ICON = ('<svg viewBox="0 0 24 24" width="12" height="12" fill="none" aria-label="Uwaga" style="flex-shrink: 0;">'
             '<path d="M12 3.6 22 20.4H2Z" stroke="%(c)s" stroke-width="2.1" stroke-linejoin="round"></path>'
             '<path d="M12 10v4.4" stroke="%(c)s" stroke-width="2.1" stroke-linecap="round"></path>'
             '<circle cx="12" cy="17.6" r="1.2" fill="%(c)s"></circle>'
             '</svg>')


def option_a(open_set):
    """Wariant A - bryla po lewej, po prawej naglowek i lista otwartych paneli."""
    items = "\n          ".join(
        '<div style="display: flex; align-items: center; gap: 5px;">'
        '<div style="width: 4px; height: 4px; background: #ef4444; flex-shrink: 0;"></div>'
        '<span style="font-size: 10px; font-weight: 700; line-height: 1; color: #f4f4f5; letter-spacing: 0.3px;">%s</span>'
        '</div>' % NAMES_PL[k]
        for k in ORDER if k in open_set
    )
    return HEAD + """
    <div style="width: 68px; flex-shrink: 0; display: flex; align-items: center; justify-content: center;">
        %s
    </div>

    <div style="flex-grow: 1; display: flex; flex-direction: column; justify-content: center; gap: 6px; padding: 0 6px 0 2px; min-width: 0;">
      <div style="display: flex; align-items: center; gap: 4px;">
        %s
        <span style="font-size: 10px; font-weight: 900; line-height: 1; letter-spacing: 1px; color: #ef4444;">OTWARTE</span>
      </div>
      <div style="height: 1px; background: #27272a;"></div>
      <div style="display: flex; flex-direction: column; gap: 5px;">
          %s
      </div>
    </div>
""" % (car_portrait(66, 112, open_set), WARN_ICON % {"c": "#ef4444"}, items) + TAIL


def option_b(open_set):
    """Wariant B - baner alarmowy u gory, bryla poziomo przez cala szerokosc."""
    return HEAD + """
    <div style="flex-grow: 1; display: flex; flex-direction: column;">
      <div style="height: 22px; flex-shrink: 0; background: #ef4444; display: flex; align-items: center; justify-content: center; gap: 6px;">
        %s
        <span style="font-size: 11px; font-weight: 900; letter-spacing: 1.6px; color: #0a0a0a;">OTWARTE</span>
        <div style="width: 15px; height: 15px; background: #0a0a0a; display: flex; align-items: center; justify-content: center;">
          <span style="font-size: 10px; font-weight: 900; line-height: 1; color: #ef4444;">%d</span>
        </div>
      </div>
      <div style="flex-grow: 1; display: flex; align-items: center; justify-content: center; min-height: 0;">
        %s
      </div>
    </div>
""" % (WARN_ICON % {"c": "#0a0a0a"}, len(open_set), car_landscape(156, 92, open_set)) + TAIL


open("Doors.dc.html", "w").write(option_a({"fl", "trunk"}))
open("DoorsAll.dc.html", "w").write(option_a({"fl", "fr", "rl", "rr", "bonnet", "trunk"}))
open("DoorsCentral.dc.html", "w").write(option_b({"fl", "trunk"}))
print("ok")
