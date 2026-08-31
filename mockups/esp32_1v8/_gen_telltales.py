# -*- coding: utf-8 -*-
"""Arkusz kontrolek — referencja implementacyjna dla firmware ESP32."""

def abs_icon(c):
    return ('<circle cx="12" cy="12" r="7.6" stroke="%(c)s" stroke-width="1.5"></circle>'
            '<text x="12" y="14.9" font-size="8" font-weight="800" fill="%(c)s" text-anchor="middle" font-family="\'Public Sans\', sans-serif">ABS</text>'
            '<path d="M2.4 8.2a9.4 9.4 0 0 0 0 7.6" stroke="%(c)s" stroke-width="1.5" stroke-linecap="round"></path>'
            '<path d="M21.6 8.2a9.4 9.4 0 0 1 0 7.6" stroke="%(c)s" stroke-width="1.5" stroke-linecap="round"></path>') % {"c": c}

def brake_icon(c):
    return ('<circle cx="12" cy="12" r="7.6" stroke="%(c)s" stroke-width="1.5"></circle>'
            '<text x="12" y="15.4" font-size="10" font-weight="800" fill="%(c)s" text-anchor="middle" font-family="\'Public Sans\', sans-serif">P</text>'
            '<path d="M2.4 8.2a9.4 9.4 0 0 0 0 7.6" stroke="%(c)s" stroke-width="1.5" stroke-linecap="round"></path>'
            '<path d="M21.6 8.2a9.4 9.4 0 0 1 0 7.6" stroke="%(c)s" stroke-width="1.5" stroke-linecap="round"></path>') % {"c": c}

def airbag_icon(c):
    return ('<circle cx="7.6" cy="6.2" r="2.5" fill="%(c)s"></circle>'
            '<path d="M4.6 18.6V12.4c0-2.1 1.5-3.4 3.4-3.4h2.2" stroke="%(c)s" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"></path>'
            '<path d="M4.6 18.6h6.6" stroke="%(c)s" stroke-width="1.6" stroke-linecap="round"></path>'
            '<circle cx="16.6" cy="12.6" r="4.4" stroke="%(c)s" stroke-width="1.6"></circle>') % {"c": c}

def immo_icon(c):
    return ('<circle cx="7.2" cy="12" r="3.8" stroke="%(c)s" stroke-width="1.6"></circle>'
            '<circle cx="7.2" cy="12" r="1.1" fill="%(c)s"></circle>'
            '<path d="M11 12h9.4" stroke="%(c)s" stroke-width="1.6" stroke-linecap="round"></path>'
            '<path d="M16.4 12v3.8" stroke="%(c)s" stroke-width="1.6" stroke-linecap="round"></path>'
            '<path d="M19.2 12v2.8" stroke="%(c)s" stroke-width="1.6" stroke-linecap="round"></path>') % {"c": c}

def cruise_icon(c):
    return ('<circle cx="12" cy="12" r="8.2" stroke="%(c)s" stroke-width="1.5"></circle>'
            '<path d="m12 12 4.6-3.9" stroke="%(c)s" stroke-width="1.6" stroke-linecap="round"></path>'
            '<circle cx="12" cy="12" r="1.5" fill="%(c)s"></circle>'
            '<path d="M6.1 17.9 7.3 16.7M12 3.8v1.7M17.9 17.9l-1.2-1.2" stroke="%(c)s" stroke-width="1.5" stroke-linecap="round"></path>') % {"c": c}


DIM = "#3f3f46"
ROWS = [
    (abs_icon,    "ABS",              "#f59e0b", "bursztyn",  "vehicle.abs_fault*", "swieci = usterka ABS"),
    (airbag_icon, "Poduszka (SRS)",   "#ef4444", "czerwony",  "vehicle.airbag_ok",  "swieci gdy airbag_ok = false"),
    (immo_icon,   "Immobilizer",      "#f59e0b", "bursztyn",  "vehicle.immo_ok",    "swieci gdy immo_ok = false"),
    (brake_icon,  "Hamulec reczny",   "#ef4444", "czerwony",  "vehicle.handbrake",  "swieci gdy zaciagniety"),
    (cruise_icon, "Tempomat",         "#22c55e", "zielony",   "vehicle.cruise",     "swieci gdy aktywny + zadana predkosc"),
]

PL = {
    "ABS": "ABS",
    "Poduszka (SRS)": "Poduszka (SRS)",
    "Immobilizer": "Immobilizer",
    "Hamulec reczny": "Hamulec ręczny",
    "Tempomat": "Tempomat",
}
COND = {
    "swieci = usterka ABS": "usterka układu ABS",
    "swieci gdy airbag_ok = false": "<code>airbag_ok = false</code>",
    "swieci gdy immo_ok = false": "<code>immo_ok = false</code>",
    "swieci gdy zaciagniety": "dźwignia zaciągnięta",
    "swieci gdy aktywny + zadana predkosc": "aktywny + zadana prędkość",
}
COLNAME = {"bursztyn": "bursztyn", "czerwony": "czerwony", "zielony": "zielony"}

rows_html = []
for fn, name, col, colname, topic, cond in ROWS:
    rows_html.append("""      <div style="display: flex; align-items: center; gap: 14px; padding: 9px 0; border-top: 1px solid #1c1c1f;">
        <svg viewBox="0 0 24 24" width="42" height="42" fill="none" style="flex-shrink: 0;">%s</svg>
        <div style="width: 34px; height: 34px; flex-shrink: 0; background: #141417; display: flex; align-items: center; justify-content: center;">
          <svg viewBox="0 0 24 24" width="20" height="20" fill="none">%s</svg>
        </div>
        <div style="width: 30px; height: 34px; flex-shrink: 0; background: #141417; display: flex; align-items: center; justify-content: center;">
          <svg viewBox="0 0 24 24" width="20" height="20" fill="none">%s</svg>
        </div>
        <div style="width: 170px; flex-shrink: 0; display: flex; flex-direction: column; gap: 3px;">
          <span style="font-size: 14px; font-weight: 800; color: #f4f4f5;">%s</span>
          <span style="font-size: 11px; font-weight: 600; color: #71717a; font-family: ui-monospace, 'SFMono-Regular', Menlo, monospace;">%s</span>
        </div>
        <div style="flex-grow: 1; display: flex; flex-direction: column; gap: 3px; min-width: 0;">
          <span style="font-size: 12px; font-weight: 600; color: #a1a1aa;">%s</span>
          <div style="display: flex; align-items: center; gap: 6px;">
            <div style="width: 9px; height: 9px; background: %s;"></div>
            <span style="font-size: 11px; font-weight: 700; color: #71717a; letter-spacing: 0.4px;">%s &middot; %s</span>
          </div>
        </div>
      </div>""" % (fn(col), fn(col), fn(DIM), PL[name], topic,
                   COND[cond].replace("<code>", '<span style="font-family: ui-monospace, Menlo, monospace; color: #d4d4d8;">').replace("</code>", "</span>"),
                   col, col.upper(), COLNAME[colname]))

doc = """<!doctype html>
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
<div style="width: 640px; height: 512px; background: #0a0a0a; padding: 20px 22px; box-sizing: border-box; display: flex; flex-direction: column;">

  <div style="display: flex; align-items: flex-end; justify-content: space-between; padding-bottom: 12px;">
    <div style="display: flex; flex-direction: column; gap: 4px;">
      <span style="font-size: 17px; font-weight: 900; color: #f4f4f5; letter-spacing: -0.2px;">Kontrolki — arkusz symboli</span>
      <span style="font-size: 11px; font-weight: 600; color: #71717a;">ST7735 160&times;128 &middot; symbol 20&times;20 px &middot; motyw Heritage &middot; kolumny: 4&times;, 1&times; świeci, 1&times; wygaszony</span>
    </div>
  </div>

%s

  <div style="margin-top: auto; padding-top: 14px; border-top: 1px solid #1c1c1f; display: flex; align-items: center; gap: 12px;">
    <div style="display: flex; align-items: baseline; gap: 4px;">
      <span style="font-size: 26px; font-weight: 900; color: #22c55e; line-height: 1; letter-spacing: -0.8px;">130</span>
      <span style="font-size: 11px; font-weight: 700; color: #52525b;">km/h</span>
    </div>
    <span style="font-size: 11px; font-weight: 600; color: #a1a1aa; line-height: 1.45;"><span style="color: #f59e0b; font-weight: 800;">*</span> sygnał, którego BCM jeszcze nie publikuje. Zadana prędkość: 20&nbsp;px / waga&nbsp;900 / kolor kontrolki. Źródło: ECU &rarr; K-Line &rarr; BCM &rarr; <span style="font-family: ui-monospace, Menlo, monospace; color: #d4d4d8;">vehicle.cruise_set_speed</span>.</span>
  </div>

</div>
</x-dc>
</body>
</html>
""" % ("\n".join(rows_html))

open("Telltales.dc.html", "w").write(doc)
print("ok")
