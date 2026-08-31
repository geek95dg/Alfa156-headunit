#!/usr/bin/env python3
"""Generator assetów dla wyświetlacza 1,8" na ESP32 — z renderów do assets.h.

Tnie rendery z ``mockups/`` na sprite'y RGB565 i wypluwa nagłówek C
z tablicami PROGMEM. Zamiast 64 kombinacji otwarć trzyma jedną bryłę
bazową i sześć niezależnych paneli, więc firmware składa dowolny stan
z klocków.

Skąd co pochodzi:

  ``mockups/screen (9).png``  — rzut z góry Alfy 156 narysowany w DWÓCH
      kolorach naraz: bursztynowe nadwozie (kompletne, zamknięte)
      i czerwone otwarte panele. Rozdzielamy je po barwie, a warstwę
      czerwoną rozbijamy na sześć osobnych brył (maska, czworo drzwi,
      klapa) po położeniu środka ciężkości. Panele są spasowane
      z karoserią z definicji, bo pochodzą z jednego rysunku — dlatego
      NIE WOLNO mieszać tu innych renderów: to osobne rysunki, których
      obrysy rozjeżdżają się o kilka pikseli.

  ``mockups/screen.png``      — kontrolki w kolorach zegarów 156.
      Stan wygaszony wyliczamy z zapalonego (przygaszenie + odsycenie),
      więc osobne rendery na zgaszone lampki są zbędne.

Dlaczego pogrubianie: kreska w renderze ma ~3 px, a zjazd do 128x160 to
skala ~1:7 — bez pogrubienia maski przed skalowaniem linia gaśnie do
brązu. Domyślne 5 px daje jasny, czytelny obrys.

Każdy panel zapisujemy w dwóch wersjach wyciętych z TEGO SAMEGO
rastra: ``closed`` (sama karoseria) i ``open`` (karoseria + czerwony
panel). Firmware przełącza stan jednym nieprzezroczystym blitem
prostokąta — bez kanału alfa, bo tło ekranu jest jednolicie czarne.

Użycie:
    python tools/esp32_assets.py                 # domyślne ścieżki
    python tools/esp32_assets.py --thicken 7     # grubsza kreska
    python tools/esp32_assets.py --no-preview

Zależności: pillow, numpy, scipy (pip install pillow numpy scipy).
"""

import argparse
import os
import sys

try:
    import numpy as np
    from PIL import Image
    from scipy import ndimage
except ImportError as exc:                                    # pragma: no cover
    sys.exit("Brak zależności (%s). Zainstaluj: pip install pillow numpy scipy" % exc.name)


# --- Konfiguracja ----------------------------------------------------------

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CAR_RENDER = os.path.join(REPO, "mockups", "screen (9).png")
TELLTALE_RENDER = os.path.join(REPO, "mockups", "screen.png")
OUT_HEADER = os.path.join(REPO, "arduino", "esp32_display", "assets.h")
OUT_PREVIEW = os.path.join(REPO, "mockups", "esp32_1v8", "assets_preview.png")

DISPLAY_W, DISPLAY_H = 128, 160
SPRITE = 26                      # bok kontrolki w pikselach panelu
BACKGROUND = (10, 10, 10)        # #0a0a0a — tło obu ekranów

# Kontrolki w renderze, w kolejności od lewej do prawej.
TELLTALES = ["abs", "brake", "airbag", "immo"]

# Panele nadwozia w kolejności, w jakiej trafiają do tablicy w assets.h.
PANELS = ["bonnet", "fl", "fr", "rl", "rr", "trunk"]

# Stan wygaszony lampki: ile zostaje jasności i ile barwy.
OFF_BRIGHTNESS = 0.30
OFF_DESATURATE = 0.55


# --- Rozdzielenie warstw ---------------------------------------------------

def despeckle(mask, min_area):
    """Usuń pojedyncze piksele, które zostały po sąsiedniej warstwie.

    Na styku czerwieni z bursztynem antyaliasing zostawia okruchy, które
    po pogrubieniu urosłyby w widoczny pył wokół zamkniętego auta.
    """
    if min_area <= 1:
        return mask
    labels, count = ndimage.label(mask, np.ones((3, 3)))
    if count == 0:
        return mask
    areas = ndimage.sum(np.ones_like(mask), labels, range(1, count + 1))
    keep = np.zeros(count + 1, bool)
    keep[1:] = areas >= min_area
    return keep[labels]


def split_layers(path, ink_threshold=45, red_ratio=0.60, min_area=60):
    """Rozdziel rysunek na maskę nadwozia i maskę otwartych paneli.

    Czerwone są piksele wyraźnie zdominowane przez kanał R; reszta
    narysowanego to bursztynowe nadwozie. Z maski nadwozia wycinamy
    rozszerzoną maskę czerwieni, żeby nie zostały po niej ciemne
    obwódki z antyaliasingu — powstałe przy tym mikroprzerwy w kresce
    i tak zniknie późniejsze pogrubianie.
    """
    rgb = np.asarray(Image.open(path).convert("RGB")).astype(int)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    ink = rgb.max(axis=2) > ink_threshold
    red = ink & (r > 80) & (g < r * red_ratio) & (b < r * red_ratio)
    body = ink & ~ndimage.binary_dilation(red, np.ones((3, 3)))
    return despeckle(body, min_area), despeckle(red, min_area), rgb


def find_panels(red):
    """Rozbij maskę czerwieni na sześć nazwanych paneli.

    Domykanie sklei przerwy w konturze, żeby każdy panel był jedną
    bryłą. Nazwy przypisujemy po położeniu: najwyższy środek ciężkości
    to maska, najniższy klapa, a cztery drzwi dzielimy na przednie
    i tylne, potem na lewe i prawe.
    """
    labels, count = ndimage.label(ndimage.binary_closing(red, np.ones((9, 9))),
                                  np.ones((3, 3)))
    if count < 6:
        sys.exit("Znaleziono tylko %d brył czerwonych — spodziewano się 6. "
                 "Sprawdź próg red_ratio albo czy to na pewno ten render." % count)

    areas = ndimage.sum(np.ones_like(red), labels, range(1, count + 1))
    biggest = [i + 1 for i in np.argsort(areas)[::-1][:6]]

    centres = {}
    for c in biggest:
        ys, xs = np.where(labels == c)
        centres[c] = (xs.mean(), ys.mean())

    by_row = sorted(biggest, key=lambda c: centres[c][1])
    out = {"bonnet": by_row[0], "trunk": by_row[-1]}
    doors = by_row[1:-1]
    front, rear = doors[:2], doors[2:]
    out["fl"], out["fr"] = sorted(front, key=lambda c: centres[c][0])
    out["rl"], out["rr"] = sorted(rear, key=lambda c: centres[c][0])
    return {name: (labels == comp) & red for name, comp in out.items()}


# --- Rasteryzacja do rozdzielczości panelu ---------------------------------

class Frame:
    """Wspólne odwzorowanie źródła na ekran — gwarant spasowania sprite'ów.

    Wszystkie rastry (bryła bazowa i każdy panel) powstają przez tę samą
    transformację, więc wycinki z nich schodzą się co do piksela.
    """

    def __init__(self, extent_mask, width, height):
        ys, xs = np.where(extent_mask)
        self.box = (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1)
        src_w = self.box[2] - self.box[0]
        src_h = self.box[3] - self.box[1]
        self.scale = min(width / src_w, height / src_h)
        self.dst_w = int(round(src_w * self.scale))
        self.dst_h = int(round(src_h * self.scale))
        self.off_x = (width - self.dst_w) // 2
        self.off_y = (height - self.dst_h) // 2
        self.width, self.height = width, height

    def render(self, layers, thicken):
        """Złóż warstwy (maska, kolor) i sprowadź do rozmiaru ekranu."""
        canvas = np.zeros((self.box[3] - self.box[1],
                           self.box[2] - self.box[0], 3), np.uint8)
        canvas[:] = BACKGROUND
        kernel = np.ones((thicken, thicken))
        for mask, colour in layers:
            fat = ndimage.binary_dilation(mask, kernel) if thicken > 1 else mask
            canvas[fat[self.box[1]:self.box[3], self.box[0]:self.box[2]]] = colour
        small = Image.fromarray(canvas).resize((self.dst_w, self.dst_h), Image.LANCZOS)
        out = Image.new("RGB", (self.width, self.height), BACKGROUND)
        out.paste(small, (self.off_x, self.off_y))
        return out

    def project(self, mask, margin=2):
        """Przelicz prostokąt maski ze źródła na współrzędne ekranu."""
        ys, xs = np.where(mask)
        x0 = int((xs.min() - self.box[0]) * self.scale) + self.off_x - margin
        y0 = int((ys.min() - self.box[1]) * self.scale) + self.off_y - margin
        x1 = int(np.ceil((xs.max() + 1 - self.box[0]) * self.scale)) + self.off_x + margin
        y1 = int(np.ceil((ys.max() + 1 - self.box[1]) * self.scale)) + self.off_y + margin
        return (max(0, x0), max(0, y0),
                min(self.width, x1), min(self.height, y1))


# --- Kontrolki -------------------------------------------------------------

def slice_telltales(path, names, size, band=(60, 250), pad=12):
    """Wytnij lampki z górnego pasma renderu i dorób stan wygaszony."""
    image = Image.open(path).convert("RGB")
    strip = np.asarray(image).astype(int)[band[0]:band[1]]
    ink = strip.max(axis=2) > 60
    labels, count = ndimage.label(ndimage.binary_closing(ink, np.ones((15, 15))),
                                  np.ones((3, 3)))
    if count < len(names):
        sys.exit("W paśmie kontrolek znaleziono %d kształtów, oczekiwano %d."
                 % (count, len(names)))
    areas = ndimage.sum(np.ones_like(ink), labels, range(1, count + 1))
    chosen = [i + 1 for i in np.argsort(areas)[::-1][:len(names)]]
    chosen.sort(key=lambda c: np.where(labels == c)[1].mean())

    out = {}
    for name, comp in zip(names, chosen):
        ys, xs = np.where(labels == comp)
        x0, x1 = xs.min() - pad, xs.max() + pad
        y0, y1 = ys.min() - pad + band[0], ys.max() + pad + band[0]
        side = max(x1 - x0, y1 - y0)
        cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
        lit = image.crop((cx - side // 2, cy - side // 2,
                          cx + side // 2, cy + side // 2)).resize((size, size), Image.LANCZOS)
        px = np.asarray(lit).astype(float)
        grey = px.mean(axis=2, keepdims=True)
        dim = px * OFF_BRIGHTNESS + (grey - px) * OFF_DESATURATE * OFF_BRIGHTNESS
        off = Image.fromarray(np.clip(dim, 0, 255).astype(np.uint8))
        out[name] = (lit, off)
    return out


# --- Wyjście ---------------------------------------------------------------

def to_rgb565(image):
    a = np.asarray(image.convert("RGB")).astype(np.uint16)
    return (((a[..., 0] & 0xF8) << 8) | ((a[..., 1] & 0xFC) << 3) | (a[..., 2] >> 3)).ravel()


def c_array(name, values, per_line=12):
    body = []
    for i in range(0, len(values), per_line):
        body.append("    " + " ".join("0x%04X," % v for v in values[i:i + per_line]))
    return ("static const uint16_t %s[] PROGMEM = {\n%s\n};\n"
            % (name, "\n".join(body)))


def write_header(path, car_base, panels, telltales, sprite):
    """Zapisz assets.h: tablice PROGMEM plus tabele pozycji."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    parts = ["""// Wygenerowane przez tools/esp32_assets.py — nie edytuj ręcznie.
// Źródła: mockups/screen (9).png (bryła + panele), mockups/screen.png (kontrolki).
#pragma once

#include <stdint.h>
#if defined(ARDUINO)
#include <pgmspace.h>
#else
#define PROGMEM
#endif

#define DISPLAY_W %d
#define DISPLAY_H %d
#define TELLTALE_SIZE %d

typedef struct {
    int16_t x, y;             // lewy górny róg na ekranie
    uint16_t w, h;
    const uint16_t *closed;   // sama karoseria w tym prostokącie
    const uint16_t *open;     // karoseria z czerwonym panelem
} PanelSprite;

typedef struct {
    const uint16_t *lit;
    const uint16_t *off;
} TelltaleSprite;

""" % (DISPLAY_W, DISPLAY_H, sprite)]

    parts.append("// --- bryła bazowa: całe auto zamknięte ---\n")
    parts.append(c_array("car_base", to_rgb565(car_base)))
    parts.append("\n// --- panele: dwa warianty wycięte z tego samego rastra ---\n")
    for name, (box, closed_img, open_img) in panels.items():
        parts.append(c_array("panel_%s_closed" % name, to_rgb565(closed_img)))
        parts.append(c_array("panel_%s_open" % name, to_rgb565(open_img)))

    parts.append("\nstatic const PanelSprite PANELS[%d] = {\n" % len(panels))
    for name in PANELS:
        box = panels[name][0]
        parts.append("    { %3d, %3d, %3d, %3d, panel_%s_closed, panel_%s_open },  // %s\n"
                     % (box[0], box[1], box[2] - box[0], box[3] - box[1], name, name, name))
    parts.append("};\n")

    parts.append("\n// --- kontrolki %dx%d ---\n" % (sprite, sprite))
    for name, (lit, off) in telltales.items():
        parts.append(c_array("telltale_%s_lit" % name, to_rgb565(lit)))
        parts.append(c_array("telltale_%s_off" % name, to_rgb565(off)))
    parts.append("\nstatic const TelltaleSprite TELLTALES[%d] = {\n" % len(telltales))
    for name in TELLTALES:
        parts.append("    { telltale_%s_lit, telltale_%s_off },  // %s\n" % (name, name, name))
    parts.append("};\n")

    with open(path, "w", encoding="utf-8") as fh:
        fh.write("".join(parts))


def write_preview(path, car_base, telltales, all_open, sample, sprite):
    """Kontaktówka do obejrzenia okiem, zanim cokolwiek trafi na panel."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    zoom = 2
    tiles = [car_base, sample, all_open]
    w = len(tiles) * (DISPLAY_W * zoom + 12) + 12
    h = DISPLAY_H * zoom + sprite * 2 * zoom + 48
    sheet = Image.new("RGB", (w, h), BACKGROUND)
    for i, img in enumerate(tiles):
        sheet.paste(img.resize((DISPLAY_W * zoom, DISPLAY_H * zoom), Image.NEAREST),
                    (12 + i * (DISPLAY_W * zoom + 12), 12))
    y = DISPLAY_H * zoom + 24
    for i, name in enumerate(TELLTALES):
        lit, off = telltales[name]
        x = 12 + i * (sprite * zoom + 8)
        sheet.paste(lit.resize((sprite * zoom,) * 2, Image.NEAREST), (x, y))
        sheet.paste(off.resize((sprite * zoom,) * 2, Image.NEAREST),
                    (x, y + sprite * zoom + 4))
    sheet.save(path)


# --- Główny przebieg -------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--car", default=CAR_RENDER, help="render bryły z otwartymi panelami")
    ap.add_argument("--telltales", default=TELLTALE_RENDER, help="render z kontrolkami")
    ap.add_argument("--header", default=OUT_HEADER, help="wyjściowy plik .h")
    ap.add_argument("--preview", default=OUT_PREVIEW, help="wyjściowa kontaktówka .png")
    ap.add_argument("--no-preview", action="store_true", help="nie zapisuj kontaktówki")
    ap.add_argument("--width", type=int, default=DISPLAY_W)
    ap.add_argument("--height", type=int, default=DISPLAY_H)
    ap.add_argument("--sprite", type=int, default=SPRITE, help="bok kontrolki w px")
    ap.add_argument("--thicken", type=int, default=5,
                    help="o ile pikseli pogrubić kreskę przed skalowaniem")
    ap.add_argument("--despeckle", type=int, default=60,
                    help="minimalna wielkość bryły w źródle, mniejsze to śmieci")
    args = ap.parse_args()

    body, red, _ = split_layers(args.car, min_area=args.despeckle)
    panel_masks = find_panels(red)

    frame = Frame(body | red, args.width, args.height)
    print("bryła: źródło %dx%d -> %dx%d (skala %.3f)"
          % (frame.box[2] - frame.box[0], frame.box[3] - frame.box[1],
             frame.dst_w, frame.dst_h, frame.scale))

    amber = (255, 186, 96)
    open_red = (239, 68, 68)

    car_base = frame.render([(body, amber)], args.thicken)
    all_open = frame.render([(body, amber), (red, open_red)], args.thicken)

    panels = {}
    for name in PANELS:
        mask = panel_masks[name]
        box = frame.project(mask)
        raster = frame.render([(body, amber), (mask, open_red)], args.thicken)
        panels[name] = (box, car_base.crop(box), raster.crop(box))
        print("  panel %-7s -> %3dx%3d px w (%3d, %3d)"
              % (name, box[2] - box[0], box[3] - box[1], box[0], box[1]))

    telltales = slice_telltales(args.telltales, TELLTALES, args.sprite)
    print("kontrolki: %s" % ", ".join(telltales))

    write_header(args.header, car_base, panels, telltales, args.sprite)
    total = (car_base.width * car_base.height
             + sum((b[2] - b[0]) * (b[3] - b[1]) * 2 for b, _, _ in panels.values())
             + len(telltales) * args.sprite * args.sprite * 2) * 2
    print("zapisano %s (%.1f KB assetów w RGB565)" % (args.header, total / 1024))

    if not args.no_preview:
        sample = frame.render([(body, amber),
                               (panel_masks["fl"] | panel_masks["trunk"], open_red)],
                              args.thicken)
        write_preview(args.preview, car_base, telltales, all_open, sample, args.sprite)
        print("zapisano %s" % args.preview)


if __name__ == "__main__":
    main()
