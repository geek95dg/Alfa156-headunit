# BCM v8.5 — schematy elektryczne (platforma Lenovo M910q)

Schematy obowiązujące dla **produkcyjnej platformy x86 — Lenovo ThinkCentre
M910q Tiny**.

| Chcesz wiedzieć | Zajrzyj do |
|-----------------|-----------|
| **co i dlaczego** — architektura, dobór podzespołów, nastawy, zakupy | [`../docs/ZASILANIE_BUFOROWANE.md`](../docs/ZASILANIE_BUFOROWANE.md) |
| **jak to pospiąć** — zacisk po zacisku, tabele połączeń, kolejność montażu | [`../docs/SCHEMATY_POLACZEN.md`](../docs/SCHEMATY_POLACZEN.md) |

> **Stan rysunków: wszystkie aktualne na 22.11.2026.** Obowiązuje:
> zalewany step-up 12 → 20 V / 200 W, 2 × XY-SK120 z dwoma XH-M603, bank
> 7 × HR1221W na lince w dwóch koszach w bagażniku
> ([`ZASILANIE_BUFOROWANE.md`](../docs/ZASILANIE_BUFOROWANE.md)).
> Wszystkie arkusze zasilania są przerysowane pod ten projekt — większość
> z generatorów `gen_*.py` (po zmianie dokumentów popraw generator, nie SVG);
> odręczne są tylko `power_buffered_m910q.svg` i `vehicle_layout_m910q.svg`.
> Pliki PNG w `png/` są wyrenderowane na nowo z bieżących SVG
> (`render_png.py --check` → „aktualny”), a mozaika miedzi PCB ma osobny
> plik do druku na laminat: `png/pcb_power_etch_600dpi.png` (600 dpi, A4).
> Przy rozbieżności rysunku z dokumentem obowiązuje ZB.

---

## Zawartość

### Schematy blokowe — architektura

| Plik | Co przedstawia |
|------|----------------|
| [`power_buffered_m910q.svg`](power_buffered_m910q.svg) | **Tor główny zasilania** — od klemy akumulatora, przez przekaźnik ładowania K1, dwie ładowarki XY-SK120 i dwa XH-M603, bank 7 × CSB HR1221W w dwóch koszach, LVD i dystrybucję, po przetwornicę step-up 20 V i M910q. Zawiera tabelę przekrojów przewodów i bezpieczników. Rysunek odręczny — przy zmianie popraw napisy w SVG. |
| [`charging_lvd.svg`](charging_lvd.svg) | **Ładowanie i ochrona banku** — cztery warstwy: F1 (MIDI/ANL) → TVS + C1 → przekaźnik ładowania K1 30 A (zapłon / D+) → 2 × XY-SK120 (CV 14,40 V, CC 5 A) → 2 × XH-M603 → FC1/FC2 → F12 → bank, potem F7 → LVD XH-M609 (11,00 / 12,60 V); rozłącznik masy S1 i blok masowy. Komplet nastaw dla **CSB HR1221W (AGM)**, dwie tabele kompensacji temperaturowej, wpływ temperatury na żywotność, przebieg CC → CV. Generator: [`gen_charging_lvd.py`](gen_charging_lvd.py). |
| [`power_domains_m910q.svg`](power_domains_m910q.svg) | **Rozdział odbiorników** — co wisi na szynie buforowanej za LVD, wkładki odgałęzień F8–F11 i F13 (opcja), step-up 20 V z wkładką 5 A na wyjściu, bucki LM2596 i MP1584 z przodu, wstrzykiwacz VBUS telefonu, budżet poboru w trzech stanach maszyny (praca / S3 / wyłączony) ze stratami step-upu, tabela czasu postoju dla banku 35,7 Ah, blok masowy za S1 i osobna gałąź wzmacniacza z akumulatora rozruchowego. Generator: [`gen_power_domains_m910q.py`](gen_power_domains_m910q.py). |
| [`audio_system.svg`](audio_system.svg) | **Tor audio** — ES9038Q2M (USB DAC) → RCA → **gotowy wzmacniacz samochodowy** → głośniki 4 Ω. Wzmacniacz zasilany wprost z akumulatora rozruchowego, z własną masą — całkowicie odseparowany od systemu buforowanego. |
| [`power_test_build.svg`](power_test_build.svg) | **Wariant testowo-rozwojowy** — przegląd blokowy toru dla instalacji jeżdżącej z minimalnym zestawem funkcji: ładowanie przez K1 i 2 × XY-SK120 → 2 × XH-M603, bank 7 × HR1221W w dwóch koszach (FB1…FB7, odbiór po przekątnej), F7 → LVD, S1 i jeden punkt masy, step-up 20 V, LM2596, MP1584, sterowanie przyciskiem M910q; granica bagażnik / przód, nastawy i tabela bezpieczników i przekrojów. Opis: §3 [`../docs/WDROZENIE_TESTOWE.md`](../docs/WDROZENIE_TESTOWE.md). Generator: [`gen_power_test_build.py`](gen_power_test_build.py). |

### Schematy połączeniowe — montaż

| Plik | Co przedstawia |
|------|----------------|
| [`schematic_test_power.svg`](schematic_test_power.svg) | **Arkusz 1/2 — zasilanie, komponentowo.** Każdy element osobno: BT0, F1 20 A, D5 (TVS SMCJ20CA) i C1 narysowane oddzielnie, styk i cewka K1 rozdzielone (cewka przez FK 1 A), dwie gałęzie ładowania XY-SK120 → XH-M603 → FC1/FC2 → F12, siedem pakietów (BT1…BT7) z wkładkami FB1…FB7 w dwóch koszach (4 + 3) z blokami zbiorczymi i łącznikami, F7 20 A, LVD, rozłącznik masy S1, trzy przetwornice (step-up 20 V, LM2596, MP1584). Detal łączenia koszy (odbiór po przekątnej L+ / P−). Moduły kupne (M1a/M1b, M2a/M2b, M3…M6) jako prostokąty z nazwanymi zaciskami. Numery przewodów zgodne z §10 [`../docs/SCHEMATY_POLACZEN.md`](../docs/SCHEMATY_POLACZEN.md). |
| [`schematic_test_signals.svg`](schematic_test_signals.svg) | **Arkusz 2/2 — sygnały i Arduino, komponentowo.** Dwa transoptory PC817 (zapłon → D9, bieg wsteczny → D10) z rezystorami i filtrami, Arduino Nano, moduł przekaźnika i przycisk zasilania M910q ze stykami równolegle. Pokazuje rozdział mas: gwiazda vs masa auta. Wejście biegu wstecznego wymaga `FEATURE_REV` w firmwarze. |
| [`gen_test_schematics.py`](gen_test_schematics.py) | **Generator obu arkuszy.** `python3 schematics/gen_test_schematics.py` z katalogu głównego repo (wystarcza biblioteka standardowa — działa też z venv BCM). Po zmianie tabel §10 popraw generator i wygeneruj SVG ponownie — nie edytuj tych dwóch SVG ręcznie. |
| [`schematic_test_build.svg`](schematic_test_build.svg) | **Schemat ideowy wariantu testowego, wersja skrócona** — symbole elektryczne, ale elementy pogrupowane w bloki: tor ładowania z F12 przy bloku L+, bank w dwóch koszach, F7 → LVD, przetwornice i sygnały (PC817, Nano, przycisk M910q). Szybki przegląd; do montażu użyj dwóch arkuszy powyżej. Opis: [`../docs/WDROZENIE_TESTOWE.md`](../docs/WDROZENIE_TESTOWE.md). Generator: [`gen_schematic_test_build.py`](gen_schematic_test_build.py). |
| [`ignition_sense.svg`](ignition_sense.svg) | **Wykrywanie zapłonu → S3** — układ wejściowy z optoizolacją PC817 i wartościami elementów (R1 2,2 kΩ, R2 10 kΩ, C2 100 nF), przebieg uśpienia i wybudzania, oraz spis tego, czego brakuje w kodzie i firmwarze. |
| [`pcb_power_schematic.svg`](pcb_power_schematic.svg) | **PCB zasilania — schemat ideowy dwóch płytek** (A: strona pojazdu toru ładowania — TVS, C1, K1 i dwa wyjścia na 2 × XY-SK120, z gałęziami XH-M603 → FC1/FC2 → F12 narysowanymi obok; B: dystrybucja szyny za LVD z F8–F11 i dzielnikiem pomiaru banku) wraz z tabelą zacisków. Opis: [`../docs/PCB_ZASILANIE.md`](../docs/PCB_ZASILANIE.md). |
| [`pcb_power_layout.svg`](pcb_power_layout.svg) | **PCB zasilania — rozmieszczenie elementów 1:1** — widok od strony elementów, opisy wszystkich zacisków, BOM elementów lutowanych, uwagi montażowe. |
| [`pcb_power_etch.svg`](pcb_power_etch.svg) | **PCB zasilania — mozaika miedzi 1:1 do wytrawienia** — druk bez skalowania (linijka kontrolna 50 mm), widok kontrolny od strony miedzi, tabela wierceń i proces termotransferu. |
| [`gen_pcb_power.py`](gen_pcb_power.py) | **Generator trzech powyższych.** `python3 schematics/gen_pcb_power.py` — sam sprawdza spójność sieci i prześwity. Po zmianie projektu popraw generator, nie SVG. |
| [`wiring_test_build.svg`](wiring_test_build.svg) | **Schemat połączeniowy wariantu testowego** — każdy zacisk podpisany, każdy przewód ponumerowany wg § 10 (tor ładowania 2 × XY-SK120 → 2 × XH-M603 → FC1/FC2 → F12, bank z blokami zbiorczymi, LVD, S1, punkt masy, step-up, LM2596, MP1584, PC817, Nano i moduł przekaźnika), kolejność podłączania, przekroje. Tabele: [`../docs/SCHEMATY_POLACZEN.md`](../docs/SCHEMATY_POLACZEN.md) § 10. Generator: [`gen_wiring_test_build.py`](gen_wiring_test_build.py). |
| [`wiring_power_modules.svg`](wiring_power_modules.svg) | **Moduły zasilania zacisk po zacisku (wersja docelowa)** — F1, TVS + C1, K1, 2 × XY-SK120, 2 × XH-M603, FC1/FC2, F12, bank 7 × HR1221W w koszach 4 + 3 z blokami zbiorczymi, FB1…FB7 i łącznikami 6 mm², odbiór po przekątnej, LVD, S1 i punkt masy, dystrybucja F8–F11 i F13, step-up 20 V, bucki z przodu, gałąź wzmacniacza; każdy zacisk podpisany, przewody ponumerowane, przekroje, kolejność podłączania i tabela zgodności z numeracją § 10. Generator: [`gen_wiring_power_modules.py`](gen_wiring_power_modules.py). |
| [`wiring_vehicle_arduino.svg`](wiring_vehicle_arduino.svg) | **Sygnały pojazdu → Arduino** — punkty poboru w aucie, stopień PC817, dzielniki napięcia, podciągnięcia, rozpiska pinów trzech płytek, tor K-Line. |
| [`wiring_usb_av.svg`](wiring_usb_av.svg) | **USB, obraz, audio, kamery** — co idzie przez hub, a co bezpośrednio w port, przejściówki DP → HDMI, tor audio i przypisanie kamer. |
| [`vehicle_layout_m910q.svg`](vehicle_layout_m910q.svg) | **Rozmieszczenie w aucie** — rzut z góry Alfy 156 ze strefami montażu (bank w dwóch koszach w bagażniku przy grodzi, z otworem na narty pośrodku), trasami kablowymi, uzasadnieniem lokalizacji i bilansem masy. Rysunek odręczny. |
| [`esp32_display_wiring.svg`](esp32_display_wiring.svg) | **Wyświetlacz pomocniczy 1,8" (ESP32-S3 + ST7735)** — stopień PC817 narysowany raz plus tabela dziesięciu wejść z numerami GPIO, panel po SPI, zasilanie z +15 przez buck 5 V, dane po natywnym USB. Rozdział mas i uwaga o przeciętej żyle VBUS. Tabele: [`../docs/SCHEMATY_POLACZEN.md`](../docs/SCHEMATY_POLACZEN.md) § 11. |
| [`gen_esp32_display.py`](gen_esp32_display.py) | **Generator powyższego.** `python3 schematics/gen_esp32_display.py` — przed zapisem sam sprawdza, czy bloki na siebie nie nachodzą i czy żaden napis nie wychodzi z ramki, nie wpada pod sąsiedni prostokąt ani na inny napis (mierzy je fontem DejaVu Sans, tym samym, którym narysuje je przeglądarka). Po zmianie § 11 popraw generator, nie SVG. |

### Eksport do PNG

| Plik | Co robi |
|------|---------|
| [`render_png.py`](render_png.py) | **Render SVG → PNG.** `python3 schematics/render_png.py` z katalogu głównego repo — komplet schematów zasilania ląduje w `png/` pod tymi samymi nazwami, razem z mozaiką miedzi do druku `pcb_power_etch_600dpi.png`. Pojedynczy arkusz: `python3 schematics/render_png.py charging_lvd.svg`; wszystkie arkusze w katalogu: `--all`; sama mozaika 600 dpi: `--print`; kontrola aktualności bez zapisu (do CI): `--check`; lżejsze pliki: `--scale 1.5`. Wymaga `pip install cairosvg` (mozaika 600 dpi także Pillow). |

PNG jest **plikiem wynikowym**: poprawia się SVG (a dla arkuszy generowanych —
generator) i renderuje ponownie, nigdy odwrotnie. Skala domyślna 2,0 robi
z najdrobniejszego napisu na arkuszu (9 px — nazwy pakietów na kaflach banku;
typowy dolny stopień to 10,5 px) odpowiednio 18 i 21 px, czyli tekst czyta się
przy oglądaniu 1:1 i zostaje zapas na przybliżenie; najcięższy arkusz waży przy
niej ok. 1,3 MB (limit 2 MB). Dwa przebiegi na tym samym SVG dają **bajtowo identyczny** plik, więc
`git status` po ponownym renderze zostaje czysty, o ile w systemie jest font
**DejaVu Sans** — ten sam, którym opisane są schematy. Bez niego cairo podstawi
inny krój i napisy rozjadą się wobec SVG.

Domyślny komplet to **dziewięć arkuszy zasilania**: `power_domains_m910q`,
`power_buffered_m910q`, `charging_lvd`, `wiring_power_modules`,
`power_test_build`, `schematic_test_build`, `schematic_test_power`,
`wiring_test_build` i `pcb_power_schematic` — dokładną listę wypisuje
`--list`. Arkusze spoza zasilania (m.in. [`vehicle_layout_m910q.svg`](vehicle_layout_m910q.svg)
i [`audio_system.svg`](audio_system.svg)) **nie mają PNG w repo** i nie pilnuje
ich `--check`; wyrenderujesz je z nazwy albo przez `--all`.

Dwa arkusze drukowane 1:1 — [`pcb_power_layout.svg`](pcb_power_layout.svg)
i [`pcb_power_etch.svg`](pcb_power_etch.svg) — są **poza** domyślnym kompletem
podglądów (raster 210 mm przy 96 dpi × 2 = 192 dpi, bez zapisanej
rozdzielczości — `png/pcb_power_layout.png` to tylko podgląd).

**Mozaika miedzi na laminat:** [`png/pcb_power_etch_600dpi.png`](png/pcb_power_etch_600dpi.png)
— 600 dpi, A4 (4961 × 7016 px), miedź czysto czarna, rozdzielczość zapisana
w pliku. Jest równorzędna z `pcb_power_etch.svg`: drukuj jedno albo drugie
w skali **100 % / „rzeczywisty rozmiar”**, bez „dopasuj do strony”, niczego
nie odbijaj w sterowniku (napisy „BCM-A/B” są na papierze lustrzane celowo)
i przed trawieniem zmierz linijkę kontrolną — 50 mm ±0,5.

---

## Kolejność czytania przy montażu

1. **[`../docs/ZASILANIE_BUFOROWANE.md`](../docs/ZASILANIE_BUFOROWANE.md) §2**
   — najpierw ustal, co gdzie ma wisieć i jaki jest budżet poboru w każdym
   ze stanów maszyny.
2. **`power_buffered_m910q.svg`** — trasa zasilania, przekroje, bezpieczniki.
3. **Nastawy z ZB §4.4 / §5 / §6 / §7** (CV 14,40 V, CC 2 × 5,0 A na
   XY-SK120, progi XH-M603 15,30 / 14,00 V, LVD XH-M609 11,00 / 12,60 V) —
   ustaw ładowarki, rozłączniki nadnapięciowe i LVD **przed** pierwszym
   podłączeniem banku.
4. **`schematic_test_power.svg`** + **`pcb_power_schematic.svg`** — teraz
   łącz, zacisk po zacisku, wg tabel „skąd → dokąd” w
   [`../docs/SCHEMATY_POLACZEN.md`](../docs/SCHEMATY_POLACZEN.md) § 2
   i kolejności montażu z tego samego dokumentu § 8.
   Zacisk po zacisku w wersji docelowej: **`wiring_power_modules.svg`**;
   nastawy ładowania i LVD zebrane na **`charging_lvd.svg`**, budżet
   poboru i odgałęzienia na **`power_domains_m910q.svg`**.
5. **`wiring_vehicle_arduino.svg`** — sygnały z auta, po jednym obwodzie.
6. **`wiring_usb_av.svg`** + **`audio_system.svg`** — peryferia i tor audio.

Zanim zaczniesz cokolwiek wiercić i prowadzić: **`vehicle_layout_m910q.svg`**
— pokazuje, co gdzie ląduje w aucie i którędy idą wiązki.

### Wariant testowo-rozwojowy — osobny komplet

Budujesz wariant z [`../docs/WDROZENIE_TESTOWE.md`](../docs/WDROZENIE_TESTOWE.md)?
Tor zasilania jest ten sam co w wersji docelowej, ale bez stałej logiki
(Nano #1, HM-10, RXB6), wzmacniacza i drugiego ekranu. Czytaj w tej
kolejności:

1. **`schematic_test_power.svg`** — tor zasilania, element po elemencie.
2. **`ignition_sense.svg`** — układ wejściowy zapłonu, wartości elementów.
3. **`schematic_test_signals.svg`** — transoptory, Nano i przycisk M910q;
   zaciski i kolejność podłączania — §10 SCHEMATY_POLACZEN.md.

---

## Konwencje na schematach

| Element | Znaczenie |
|---------|-----------|
| Gruba czerwona linia | Zasilanie 12 V (moc) |
| Zielona linia | Tor ładowania |
| Niebieska linia | Odgałęzienie odbiorników (za LVD i wyłącznikiem) |
| Linia przerywana | Sygnał sterujący (ACC, D+), nie moc |
| Ramka pomarańczowa | Element zabezpieczający (bezpiecznik, LVD, rozłącznik) |
| Ramka zielona | Tor ładowania / bank akumulatorów |
| Ramka niebieska | Odbiorniki |
| Ramka czerwona | Gałąź niezależna (wzmacniacze) |

---

## I/O pojazdu — gdzie szukać

Na M910q **nie ma GPIO**. Wszystkie sygnały pojazdu (zapłon, drzwi,
kierunkowskazy, deszcz, temperatura, czujniki parkowania, podświetlenie PWM,
przekaźniki szyb i bagażnika) wchodzą i wychodzą przez **trzy płytki Arduino
po USB**. Okablowanie pin-po-pinie jest w
**[`../docs/ARDUINO_SETUP_GUIDE.md`](../docs/ARDUINO_SETUP_GUIDE.md)**:

| Płytka | Sketch | Rola |
|--------|--------|------|
| Pro Micro | `arduino/rotary_encoder` | Enkoder, przyciski, SWC, panel muzyczny, jasność |
| Nano #1 | `arduino/output_controller` | Domena A: pilot 433 MHz, bagażnik przez BLE, PWM podświetlenia |
| Nano #2 | `arduino/sensor_hub` | Telemetria: drzwi, maska, ręczny, zapłon, deszcz, DS18B20 |
| ESP32-S3 *(opcjonalna)* | `arduino/esp32_display` | Wyświetlacz pomocniczy 1,8": kontrolki i otwarcia z GPIO, metadane z BCM po USB |

Interfejs K-Line (L9637D) na M910q idzie przez **CP2102 po USB**, a nie przez
UART na złączu GPIO — patrz [`../docs/KLINE_SNIFFING.md`](../docs/KLINE_SNIFFING.md).

---

## Schematy dla platform zarchiwizowanych

Komplet schematów **BCM v7** dla Orange Pi 5 Plus / 5 Pro (I/O pojazdu wpięte
wprost w 40-pinowe złącze GPIO, zasilanie LM2596 12 V → 5,1 V) leży w
[`../Archive/orange-pi-5/schematics-v7/`](../Archive/orange-pi-5/schematics-v7/).
Te rysunki **nie obowiązują** dla M910q — numery pinów i cały tor zasilania są
inne. Bywają przydatne jako referencja samych układów analogowych (PC817,
dzielniki napięcia HC-SR04, sterownik MOSFET podświetlenia), bo te części
przeniosły się na Arduino bez zmian wartości elementów.
