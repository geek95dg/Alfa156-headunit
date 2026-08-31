# -*- coding: utf-8 -*-
"""Symbole kontrolek — jedno zrodlo dla ekranu 1 i arkusza referencyjnego.

Rysunek na siatce 24x24. Ksztalty trzymaja sie symboli z zegarow 156:
ABS i hamulec w klamrach z luków, poduszka jako pasazer z workiem,
immobilizer jako kluczyk, tempomat jako otwarta tarcza predkosciomierza.
"""

# Klamry po bokach — wspolne dla ABS i hamulca (rodzina symboli hamulcowych).
BRACKETS = (
    '<path d="M1.8 8.0a11 11 0 0 0 0 8" stroke="%(c)s" stroke-width="1.7" stroke-linecap="round"></path>'
    '<path d="M4.0 9.7a8.6 8.6 0 0 0 0 4.6" stroke="%(c)s" stroke-width="1.7" stroke-linecap="round"></path>'
    '<path d="M22.2 8.0a11 11 0 0 1 0 8" stroke="%(c)s" stroke-width="1.7" stroke-linecap="round"></path>'
    '<path d="M20.0 9.7a8.6 8.6 0 0 1 0 4.6" stroke="%(c)s" stroke-width="1.7" stroke-linecap="round"></path>'
)


def abs_icon(c):
    return (('<circle cx="12" cy="12" r="7.2" stroke="%(c)s" stroke-width="1.7"></circle>'
             '<text x="12" y="14.7" font-size="7.6" font-weight="800" fill="%(c)s" text-anchor="middle"'
             ' font-family="\'Public Sans\', sans-serif" letter-spacing="-0.2">ABS</text>')
            + BRACKETS) % {"c": c}


def brake_icon(c):
    return (('<circle cx="12" cy="12" r="7.2" stroke="%(c)s" stroke-width="1.7"></circle>'
             '<text x="12" y="15.6" font-size="10.5" font-weight="900" fill="%(c)s" text-anchor="middle"'
             ' font-family="\'Public Sans\', sans-serif">P</text>')
            + BRACKETS) % {"c": c}


def airbag_icon(c):
    return ('<circle cx="6.8" cy="6.4" r="2.7" fill="%(c)s"></circle>'
            '<path d="M4.2 19.2v-6.1c0-2.4 1.7-4 4.1-4h2.5" stroke="%(c)s" stroke-width="1.8"'
            ' stroke-linecap="round" stroke-linejoin="round"></path>'
            '<path d="M4.2 19.2h7.1" stroke="%(c)s" stroke-width="1.8" stroke-linecap="round"></path>'
            '<circle cx="16.9" cy="13.1" r="4.7" stroke="%(c)s" stroke-width="1.8"></circle>') % {"c": c}


def immo_icon(c):
    return ('<circle cx="6.7" cy="12" r="4.1" stroke="%(c)s" stroke-width="1.8"></circle>'
            '<circle cx="6.7" cy="12" r="1.2" fill="%(c)s"></circle>'
            '<path d="M10.8 12h9.6" stroke="%(c)s" stroke-width="1.8" stroke-linecap="round"></path>'
            '<path d="M16.3 12v3.9" stroke="%(c)s" stroke-width="1.8" stroke-linecap="round"></path>'
            '<path d="M19.6 12v2.7" stroke="%(c)s" stroke-width="1.8" stroke-linecap="round"></path>') % {"c": c}


def cruise_icon(c):
    return ('<path d="M6.34 17.66A8 8 0 1 1 17.66 17.66" stroke="%(c)s" stroke-width="1.7"'
            ' stroke-linecap="round"></path>'
            '<path d="M7.8 16.2 6.4 17.6M12 4v1.9M17.6 17.6l-1.4-1.4" stroke="%(c)s" stroke-width="1.6"'
            ' stroke-linecap="round"></path>'
            '<path d="m12 12 4.5-3.8" stroke="%(c)s" stroke-width="1.9" stroke-linecap="round"></path>'
            '<circle cx="12" cy="12" r="1.6" fill="%(c)s"></circle>') % {"c": c}


OFF = "#3f3f46"

# (funkcja, kolor swiecenia, rgb do poswiaty i podkladki)
ABS = (abs_icon, "#f59e0b", "245, 158, 11")
AIRBAG = (airbag_icon, "#ef4444", "239, 68, 68")
IMMO = (immo_icon, "#f59e0b", "245, 158, 11")
BRAKE = (brake_icon, "#ef4444", "239, 68, 68")
CRUISE = (cruise_icon, "#22c55e", "34, 197, 94")


def telltale(spec, lit, size=22, chip=26, glow=2.5, radius=3):
    """Kontrolka w stanie zapalonym (podkladka + poswiata) albo wygaszonym."""
    fn, color, rgb = spec
    if lit:
        box = 'background: rgba(%s, 0.13); border-radius: %dpx;' % (rgb, radius)
        shadow = ' style="filter: drop-shadow(0 0 %spx rgba(%s, 0.55));"' % (glow, rgb)
        body = fn(color)
    else:
        box = ""
        shadow = ""
        body = fn(OFF)
    return ('<div style="width: %dpx; height: %dpx; display: flex; align-items: center;'
            ' justify-content: center; %s">'
            '<svg viewBox="0 0 24 24" width="%d" height="%d" fill="none"%s>%s</svg>'
            '</div>') % (chip, chip, box, size, size, shadow, body)
