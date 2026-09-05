# -*- coding: utf-8 -*-
"""Arkusz kontrolek — referencja implementacyjna dla firmware ESP32."""

from _icons import telltale, ABS, AIRBAG, IMMO, BRAKE, CRUISE

# Cztery pierwsze lampki wchodzą wprost na GPIO przez PC817 (stan aktywny LOW);
# tempomat przychodzi z BCM po USB, bo w aucie nie ma go jako prostego napięcia.
ROWS = [
    (ABS,    "ABS",            "GPIO4  \u2190 PC817*", "usterka układu ABS",       "#F59E0B", "bursztyn"),
    (AIRBAG, "Poduszka (SRS)", "GPIO6  \u2190 PC817*", "usterka SRS",              "#EF4444", "czerwony"),
    (IMMO,   "Immobilizer",    "GPIO7  \u2190 PC817",  "klucz nierozpoznany",      "#F59E0B", "bursztyn"),
    (BRAKE,  "Hamulec ręczny", "GPIO5  \u2190 PC817",  "dźwignia zaciągnięta",     "#EF4444", "czerwony"),
    (CRUISE, "Tempomat",       "CRUISE: \u2190 USB",   "aktywny + zadana prędkość","#22C55E", "zielony"),
]

ROW = """      <div style="display: flex; align-items: center; gap: 16px; padding: 8px 0; border-top: 1px solid #1c1c1f;">
        {big}
        {on}
        {off}
        <div style="width: 168px; flex-shrink: 0; display: flex; flex-direction: column; gap: 3px;">
          <span style="font-size: 14px; font-weight: 800; color: #f4f4f5;">{name}</span>
          <span style="font-size: 11px; font-weight: 600; color: #71717a; font-family: ui-monospace, Menlo, monospace;">{topic}</span>
        </div>
        <div style="flex-grow: 1; display: flex; flex-direction: column; gap: 4px; min-width: 0;">
          <span style="font-size: 12px; font-weight: 600; color: #a1a1aa;">{cond}</span>
          <div style="display: flex; align-items: center; gap: 6px;">
            <div style="width: 9px; height: 9px; background: {hexcol};"></div>
            <span style="font-size: 11px; font-weight: 700; color: #71717a; letter-spacing: 0.4px;">{hexcol} &middot; {colname}</span>
          </div>
        </div>
      </div>"""

rows = "\n".join(
    ROW.format(
        big=telltale(spec, True, size=40, chip=48, glow=5, radius=5),
        on=telltale(spec, True),
        off=telltale(spec, False),
        name=name, topic=topic, cond=cond, hexcol=hexcol, colname=colname,
    )
    for spec, name, topic, cond, hexcol, colname in ROWS
)

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
    body { margin: 0; background: #0a0a0a; font-family: 'Public Sans', system-ui, sans-serif; }
    a { color: #f59e0b; } a:hover { color: #b45309; }
  </style>
</helmet>
<div style="width: 640px; height: 512px; background: #0a0a0a; padding: 20px 22px; box-sizing: border-box; display: flex; flex-direction: column;">

  <div style="display: flex; flex-direction: column; gap: 4px; padding-bottom: 10px;">
    <span style="font-size: 17px; font-weight: 900; color: #f4f4f5; letter-spacing: -0.2px;">Kontrolki — arkusz symboli</span>
    <span style="font-size: 11px; font-weight: 600; color: #71717a;">ST7735 128&times;160 &middot; symbol 22&times;22 px w podkładce 26&times;26 &middot; kolumny: 4&times;, świeci, wygaszona &middot; źródło sygnału</span>
  </div>

%s

  <div style="margin-top: auto; padding-top: 12px; border-top: 1px solid #1c1c1f; display: flex; align-items: center; gap: 12px;">
    <div style="display: flex; align-items: baseline; gap: 4px; flex-shrink: 0;">
      <span style="font-size: 24px; font-weight: 900; color: #22c55e; line-height: 1; letter-spacing: -0.8px;">130</span>
      <span style="font-size: 11px; font-weight: 700; color: #52525b;">km/h</span>
    </div>
    <span style="font-size: 11px; font-weight: 600; color: #a1a1aa; line-height: 1.45;"><span style="color: #f59e0b; font-weight: 800;">*</span> do zmierzenia miernikiem, czy ta linia jest na złączu fabrycznego wyświetlacza. Zapalona kontrolka dostaje podkładkę w swoim kolorze (13&nbsp;%%&nbsp;krycia) i wąską poświatę. Zadana prędkość: 16&nbsp;px / waga&nbsp;900 / kolor kontrolki; <span style="font-family: ui-monospace, Menlo, monospace; color: #d4d4d8;">vehicle.cruise_set_speed</span> nie ma jeszcze producenta w BCM, więc do czasu znalezienia ramki w ECU pole pokazuje <span style="font-family: ui-monospace, Menlo, monospace; color: #d4d4d8;">---</span>.</span>
  </div>

</div>
</x-dc>
</body>
</html>
""" % rows

open("Telltales.dc.html", "w").write(DOC)
print("ok")
