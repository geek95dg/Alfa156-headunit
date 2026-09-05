#!/usr/bin/env python3
"""Eksport schematów do PNG — powtarzalny render SVG → raster (cairosvg).

Robi rastrową kopię schematów dla miejsc, w których SVG się nie nadaje:
podgląd na telefonie w garażu, wklejka do notatki, wydruk z byle
przeglądarki obrazków. Źródłem prawdy pozostaje SVG — PNG jest zawsze
plikiem wynikowym i **nigdy** się go nie poprawia ręcznie.

Uruchomienie (z katalogu głównego repo):
    python3 schematics/render_png.py                     # komplet zasilania
    python3 schematics/render_png.py --all               # wszystkie SVG w schematics/
    python3 schematics/render_png.py pcb_power_schematic.svg
    python3 schematics/render_png.py --scale 1.5         # lżejsze pliki
    python3 schematics/render_png.py --check             # czy PNG są aktualne (CI)
    python3 schematics/render_png.py --list              # co wchodzi do kompletu

Wynik ląduje w ``schematics/png/`` pod tą samą nazwą co źródło.

Dlaczego skala 2,0 (a nie 1,0 ani 3,0)
--------------------------------------
Arkusze zasilania są rysowane w pikselach, a najdrobniejszy napis ma
9 px (nazwy pakietów na kaflach banku w ``wiring_power_modules.svg``);
typowy dolny stopień to 10,5 px — oznaczniki zacisków i przekroje
przewodów. Przy skali 1:1 taki tekst wychodzi w rastrze dokładnie tak,
jak pokazuje go przeglądarka, czyli na granicy czytelności i bez zapasu
na powiększenie. Skala 2,0 robi z tych 9 px 18 px, a z 10,5 px 21 px:
napis czyta się bez mrużenia oczu przy oglądaniu 1:1 i zostaje margines
na przybliżenie, a kreski 1,5–2,8 px nie gubią się w zaokrągleniu do
piksela. Największy arkusz
(1660 × 2210 px) daje przy tej skali 3320 × 4420 px i ok. 0,8 MB —
z zapasem pod przyjęty limit 2 MB. Skala 3,0 kosztuje +60 % objętości
i nie dokłada nic, czego nie widać już przy 2,0, bo źródło jest
wektorowe i nie ma w nim detalu poniżej piksela.

Arkusze w milimetrach (montażówka i mozaika miedzi PCB, A4 210 × 297 mm)
przelicza cairosvg po 96 dpi, więc skala 2,0 daje w ich przypadku
192 dpi. To wystarcza na podgląd, ale **nie do trawienia**: mozaikę
drukuj wyłącznie z SVG w skali 100 % i sprawdź linijkę kontrolną 50 mm.
Dlatego oba arkusze 1:1 są poza domyślnym kompletem — trzeba je wskazać
z nazwy albo użyć ``--all``.

Powtarzalność: cairosvg nie zapisuje w PNG ani znacznika czasu, ani
niczego innego, co zmieniałoby się między przebiegami — dwa uruchomienia
na tym samym SVG dają bajtowo identyczny plik (``md5sum``). Warunkiem
jest obecność fontu DejaVu Sans, tego samego, którym schematy są
opisane; bez niego cairo podstawi inny krój i napisy zmienią metryki.

Zależności: cairosvg (pip install cairosvg).
"""

import argparse
import os
import sys

try:
    import cairosvg
except ImportError as exc:                                    # pragma: no cover
    sys.exit(f"Brak zależności ({exc.name}). Zainstaluj: pip install cairosvg\n"
             "cairosvg korzysta z systemowej biblioteki cairo — na Debianie/Ubuntu:\n"
             "    sudo apt install libcairo2")


# --- Konfiguracja ----------------------------------------------------------

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(REPO, "schematics")
OUT_DIR = os.path.join(SRC_DIR, "png")

DEJAVU = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

# Komplet zasilania — to renderuje się domyślnie, w kolejności czytania
# z schematics/README.md (najpierw architektura, potem montaż).
POWER_SHEETS = (
    "power_domains_m910q.svg",
    "power_buffered_m910q.svg",
    "charging_lvd.svg",
    "wiring_power_modules.svg",
    "power_test_build.svg",
    "schematic_test_build.svg",
    "schematic_test_power.svg",
    "wiring_test_build.svg",
    "pcb_power_schematic.svg",
)

# Arkusze drukowane 1:1 — poza domyślnym kompletem, bo raster kusi, żeby
# wydrukować go „mniej więcej”, a mozaika miedzi wybacza błąd skali gorzej
# niż cokolwiek innego w tym repo.
PRINT_SHEETS = (
    "pcb_power_layout.svg",
    "pcb_power_etch.svg",
)

SCALE = 2.0          # patrz uzasadnienie w docstringu
MAX_MB = 2.0         # próg ostrzeżenia o rozmiarze pliku
BACKGROUND = "#ffffff"


# --- Wybór plików ----------------------------------------------------------

def all_sheets():
    """Wszystkie SVG w schematics/, alfabetycznie (stała kolejność wyniku)."""
    return tuple(sorted(n for n in os.listdir(SRC_DIR) if n.endswith(".svg")))


def resolve(names, want_all):
    """Zamień argumenty wiersza poleceń na listę ścieżek do SVG.

    Brak pliku wskazanego z nazwy jest błędem — użytkownik się pomylił.
    Brak pliku z domyślnego kompletu to tylko ostrzeżenie: lista POWER_SHEETS
    jest spisana ręcznie i nie może blokować renderu reszty, kiedy któryś
    arkusz zmieni nazwę albo zniknie.
    """
    available = all_sheets()

    if want_all:
        return [(n, os.path.join(SRC_DIR, n)) for n in available]

    if names:
        chosen = tuple(os.path.basename(n) for n in names)
        missing = [n for n in chosen if n not in available]
        if missing:
            sys.exit("Nie ma takich schematów: %s\nDostępne: %s"
                     % (", ".join(missing), ", ".join(available)))
    else:
        chosen = tuple(n for n in POWER_SHEETS if n in available)
        for gone in (n for n in POWER_SHEETS if n not in available):
            print(f"uwaga: {gone} z kompletu zasilania nie istnieje — pomijam "
                  "(popraw POWER_SHEETS w tym skrypcie)", file=sys.stderr)
        if not chosen:
            sys.exit("Żaden arkusz z domyślnego kompletu nie istnieje — "
                     "popraw POWER_SHEETS albo wskaż pliki z nazwy.")

    return [(n, os.path.join(SRC_DIR, n)) for n in chosen]


# --- Render ----------------------------------------------------------------

def render(src, scale):
    """Zwróć PNG jako bajty. Bez zapisu — żeby --check nie ruszał dysku."""
    return cairosvg.svg2png(url=src, scale=scale, background_color=BACKGROUND)


def png_size(blob):
    """Wymiary z nagłówka IHDR — bez wciągania Pillow tylko dla dwóch liczb."""
    return int.from_bytes(blob[16:20], "big"), int.from_bytes(blob[20:24], "big")


# --- Główny przebieg -------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("svg", nargs="*",
                    help="nazwy plików SVG do wyrenderowania; puste = komplet zasilania")
    ap.add_argument("--all", action="store_true",
                    help="wyrenderuj wszystkie SVG z schematics/, nie tylko zasilanie")
    ap.add_argument("--scale", type=float, default=SCALE,
                    help=f"mnożnik rozdzielczości wobec rozmiaru własnego SVG (domyślnie {SCALE})")
    ap.add_argument("--out-dir", default=OUT_DIR, help="katalog wynikowy")
    ap.add_argument("--max-mb", type=float, default=MAX_MB,
                    help=f"próg ostrzeżenia o wielkości pliku w MB (domyślnie {MAX_MB})")
    ap.add_argument("--check", action="store_true",
                    help="nie zapisuj — tylko sprawdź, czy PNG w repo są aktualne")
    ap.add_argument("--list", action="store_true",
                    help="wypisz, co wchodzi do domyślnego kompletu, i zakończ")
    args = ap.parse_args()

    if args.list:
        print("Komplet zasilania (domyślny):")
        for name in POWER_SHEETS:
            print(f"  {name}")
        print("\nArkusze 1:1 — tylko z nazwy albo --all (druk wyłącznie z SVG):")
        for name in PRINT_SHEETS:
            print(f"  {name}")
        return

    if args.scale <= 0:
        sys.exit("--scale musi być dodatnia.")
    if not os.path.exists(DEJAVU):
        print("uwaga: brak fontu DejaVu Sans — cairo podstawi inny krój "
              "i napisy rozjadą się wobec SVG", file=sys.stderr)

    sheets = resolve(args.svg, args.all)
    if not args.check:
        os.makedirs(args.out_dir, exist_ok=True)

    stale, oversize = [], []
    for name, src in sheets:
        dst = os.path.join(args.out_dir, name[:-4] + ".png")
        blob = render(src, args.scale)
        width, height = png_size(blob)
        mb = len(blob) / 1e6

        old = None
        if os.path.exists(dst):
            with open(dst, "rb") as fh:
                old = fh.read()

        if args.check:
            state = "aktualny" if old == blob else ("BRAK" if old is None else "NIEAKTUALNY")
            if old != blob:
                stale.append(name)
        elif old == blob:
            state = "bez zmian"
        else:
            with open(dst, "wb") as fh:
                fh.write(blob)
            state = "zapisano"

        flag = ""
        if mb > args.max_mb:
            oversize.append(name)
            flag = f"  <- ponad {args.max_mb:g} MB"
        print(f"{name:<28} {width:>5} x {height:<5} px  {mb:5.2f} MB  {state}{flag}")

    if oversize:
        print(f"\nZa duże pliki: {', '.join(oversize)}.\n"
              f"Zejdź ze skalą, np. --scale {args.scale / 2:g}.", file=sys.stderr)

    if args.check and stale:
        sys.exit(f"\nPNG nieaktualne wobec SVG: {', '.join(stale)}.\n"
                 "Uruchom: python3 schematics/render_png.py")


if __name__ == "__main__":
    main()
