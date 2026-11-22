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
    python3 schematics/render_png.py --print             # tylko mozaika miedzi 600 dpi

Wynik ląduje w ``schematics/png/`` pod tą samą nazwą co źródło.
Wyjątek: mozaika miedzi do druku, ``pcb_power_etch_600dpi.png`` (niżej).

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
(1640 × 2680 px, ``wiring_power_modules.svg``) daje przy tej skali
3280 × 5360 px i ok. 1,3 MB —
z zapasem pod przyjęty limit 2 MB. Skala 3,0 kosztuje +60 % objętości
i nie dokłada nic, czego nie widać już przy 2,0, bo źródło jest
wektorowe i nie ma w nim detalu poniżej piksela.

Arkusze w milimetrach (montażówka i mozaika miedzi PCB, A4 210 × 297 mm)
przelicza cairosvg po 96 dpi, więc skala 2,0 daje w ich przypadku
192 dpi i PNG bez zapisanej rozdzielczości — to tylko podgląd, **nie do
trawienia**. Dlatego oba arkusze 1:1 w tej postaci są poza domyślnym
kompletem — trzeba je wskazać z nazwy albo użyć ``--all``.

Mozaika miedzi do druku: ``pcb_power_etch_600dpi.png``
--------------------------------------------------------
Osobny plik do laserowego wydruku na papier do termotransferu. Źródłem
prawdy zostaje ``pcb_power_etch.svg``; ten PNG jest jego równorzędną
kopią 1:1 dla drukarek i komputerów, które SVG skalują po swojemu:

* 600 dpi, A4 (4961 × 7016 px), rozdzielczość zapisana w pliku (chunk
  pHYs) — program, który ją honoruje, drukuje rozmiar rzeczywisty,
* miedź czysto czarna (#000) na białym tle, skala szarości; reszta
  arkusza (opisy, szary widok kontrolny) zostaje do orientacji,
* orientacja jak w SVG: widok od strony elementów, napisy „BCM-A/B”
  na papierze **lustrzane** — po przyłożeniu tonerem do miedzi czytają
  się poprawnie. Niczego nie odbijaj w sterowniku drukarki.

Druk: skala **100 % / „rzeczywisty rozmiar”**, wyłączone „dopasuj do
strony” i marginesy „bez obramowania”; po wydruku zmierz linijkę
kontrolną — 50 mm ±0,5. Bez tej kontroli nie traw.

Plik powstaje w domyślnym przebiegu, z ``--all`` i z ``--print``
(tylko on); ``--check`` sprawdza go jak każdy inny. ``--scale`` go nie
dotyczy — rozdzielczość jest stała. Wymaga Pillow (jest w
requirements-x86.txt) do zapisu skali szarości i pHYs.

Powtarzalność: cairosvg nie zapisuje w PNG ani znacznika czasu, ani
niczego innego, co zmieniałoby się między przebiegami — dwa uruchomienia
na tym samym SVG dają bajtowo identyczny plik (``md5sum``). Warunkiem
jest obecność fontu DejaVu Sans, tego samego, którym schematy są
opisane; bez niego cairo podstawi inny krój i napisy zmienią metryki.

Zależności: cairosvg (pip install cairosvg); dla mozaiki 600 dpi także
Pillow.
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

# Mozaika miedzi do druku na papier transferowy — patrz docstring.
ETCH_SVG = "pcb_power_etch.svg"
ETCH_PRINT_PNG = "pcb_power_etch_600dpi.png"
PRINT_DPI = 600
# Kolory miedzi w arkuszu z gen_pcb_power.py (#111 — ciemny, ale nie
# czarny, żeby na ekranie odróżniał się od opisów) → czysta czerń w druku.
# Jasny widok kontrolny (#d8dde2) i opisy zostają bez zmian.
COPPER_COLORS = ("#111111", '"#111"')

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


def render_etch_print(src):
    """Mozaika miedzi 1:1 do druku: 600 dpi, pHYs, czarna miedź, skala szarości.

    Zwraca bajty PNG. Deterministyczne: Pillow nie zapisuje daty ani
    metadanych poza pHYs, a wejście (SVG + DejaVu) jest stałe.
    """
    try:
        from PIL import Image
    except ImportError:                                       # pragma: no cover
        sys.exit("Mozaika 600 dpi wymaga Pillow: pip install Pillow")
    import io

    with open(src, encoding="utf-8") as fh:
        svg = fh.read()
    for color in COPPER_COLORS:
        if color not in svg:
            sys.exit(f"{ETCH_SVG}: brak koloru miedzi {color} — zmienił się "
                     "gen_pcb_power.py, popraw COPPER_COLORS w render_png.py")
        svg = svg.replace(color, color.replace("1", "0"))
    raw = cairosvg.svg2png(bytestring=svg.encode("utf-8"), dpi=PRINT_DPI,
                           background_color=BACKGROUND)
    img = Image.open(io.BytesIO(raw)).convert("L")
    out = io.BytesIO()
    img.save(out, format="PNG", dpi=(PRINT_DPI, PRINT_DPI), optimize=True)
    return out.getvalue()


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
    ap.add_argument("--print", dest="etch_print", action="store_true",
                    help=f"tylko mozaika miedzi do druku ({ETCH_PRINT_PNG}, "
                         f"{PRINT_DPI} dpi)")
    args = ap.parse_args()

    if args.list:
        print("Komplet zasilania (domyślny):")
        for name in POWER_SHEETS:
            print(f"  {name}")
        print("\nArkusze 1:1 jako podgląd 192 dpi — tylko z nazwy albo --all:")
        for name in PRINT_SHEETS:
            print(f"  {name}")
        print(f"\nDruk mozaiki miedzi (domyślnie, --all, --print):\n"
              f"  {ETCH_PRINT_PNG}  ← {ETCH_SVG}, {PRINT_DPI} dpi, skala 100 %")
        return

    if args.scale <= 0:
        sys.exit("--scale musi być dodatnia.")
    if not os.path.exists(DEJAVU):
        print("uwaga: brak fontu DejaVu Sans — cairo podstawi inny krój "
              "i napisy rozjadą się wobec SVG", file=sys.stderr)

    if args.etch_print:
        if args.svg or args.all:
            sys.exit("--print nie łączy się z nazwami plików ani z --all.")
        sheets = []
    else:
        sheets = resolve(args.svg, args.all)
    # (nazwa wyświetlana, źródło SVG, plik wynikowy, funkcja renderu)
    jobs = [(name, src, name[:-4] + ".png", lambda s: render(s, args.scale))
            for name, src in sheets]
    etch_src = os.path.join(SRC_DIR, ETCH_SVG)
    if (args.etch_print or not args.svg) and os.path.exists(etch_src):
        jobs.append((ETCH_PRINT_PNG, etch_src, ETCH_PRINT_PNG, render_etch_print))
    elif args.etch_print:
        sys.exit(f"Nie ma {ETCH_SVG} — uruchom schematics/gen_pcb_power.py.")
    if not args.check:
        os.makedirs(args.out_dir, exist_ok=True)

    stale, oversize = [], []
    for name, src, out_name, render_fn in jobs:
        dst = os.path.join(args.out_dir, out_name)
        blob = render_fn(src)
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
