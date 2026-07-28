# BCM v8.5 — schematy elektryczne (platforma Lenovo M910q)

Schematy obowiązujące dla **produkcyjnej platformy x86 — Lenovo ThinkCentre
M910q Tiny**.

| Chcesz wiedzieć | Zajrzyj do |
|-----------------|-----------|
| **co i dlaczego** — architektura, dobór podzespołów, nastawy, zakupy | [`../docs/ZASILANIE_BUFOROWANE.md`](../docs/ZASILANIE_BUFOROWANE.md) |
| **jak to pospiąć** — zacisk po zacisku, tabele połączeń, kolejność montażu | [`../docs/SCHEMATY_POLACZEN.md`](../docs/SCHEMATY_POLACZEN.md) |

---

## Zawartość

### Schematy blokowe — architektura

| Plik | Co przedstawia |
|------|----------------|
| [`power_buffered_m910q.svg`](power_buffered_m910q.svg) | **Tor główny zasilania** — od klemy akumulatora, przez przekaźnik ładowania, ładowarkę CC-CV, blokadę przeładowania, bank CSB HR1221W i LVD, po wyłącznik główny, przetwornicę step-up 19 V i M910q. Zawiera tabelę przekrojów przewodów i bezpieczników. |
| [`charging_lvd.svg`](charging_lvd.svg) | **Ładowanie i ochrona banku** — cztery warstwy (przekaźnik ładowania → CC-CV → rozłącznik nadnapięciowy → LVD), komplet nastaw dla **CSB HR1221W (AGM)**, dwie tabele kompensacji temperaturowej, wpływ temperatury na żywotność, przebieg CC → CV → float. |
| [`power_domains_m910q.svg`](power_domains_m910q.svg) | **Rozdział odbiorników** — co wisi na szynie buforowanej, bezpieczniki odgałęzień, budżet poboru w trzech stanach maszyny (praca / S3 / wyłączona), tabela czasu postoju, osobna gałąź wzmacniaczy. |
| [`audio_system.svg`](audio_system.svg) | **Tor audio** — ES9038Q2M (USB DAC) → RCA → **gotowy wzmacniacz samochodowy** → głośniki 4 Ω. Wzmacniacz zasilany wprost z akumulatora rozruchowego, z własną masą — całkowicie odseparowany od systemu buforowanego. |
| [`power_test_build.svg`](power_test_build.svg) | **Wariant testowo-rozwojowy** — uproszczony tor dla instalacji jeżdżącej z minimalnym zestawem funkcji: ładowanie wariantem B (przekaźnik + MBR2545CT + CC-CV boost), bank, LVD, XL6019 i panel 7". M910q zasilany stale, zapłon tylko jako sygnał. Bez domeny A i bez wzmacniacza. Opis: [`../docs/WDROZENIE_TESTOWE.md`](../docs/WDROZENIE_TESTOWE.md). |

### Schematy połączeniowe — montaż

| Plik | Co przedstawia |
|------|----------------|
| [`schematic_test_power.svg`](schematic_test_power.svg) | **Arkusz 1/2 — zasilanie, komponentowo.** Każdy element osobno: BT0, F1, D5 (TVS) i C1 narysowane oddzielnie, styki i cewki K1/K2 rozdzielone, D1 jako dwie diody Schottky ze zwartymi anodami, cztery pakiety banku z własnymi bezpiecznikami, S1, trzy przetwornice. Moduły kupne (M1…M6) jako prostokąty z nazwanymi zaciskami. Numery przewodów zgodne z §10 [`../docs/SCHEMATY_POLACZEN.md`](../docs/SCHEMATY_POLACZEN.md). |
| [`schematic_test_signals.svg`](schematic_test_signals.svg) | **Arkusz 2/2 — sygnały i Arduino, komponentowo.** Dwa transoptory PC817 (zapłon → D9, bieg wsteczny → D10) z rezystorami i filtrami, Arduino Nano, moduł przekaźnika i przycisk zasilania M910q ze stykami równolegle. Pokazuje rozdział mas: gwiazda vs masa auta. Wejście biegu wstecznego wymaga `FEATURE_REV` w firmwarze. |
| [`gen_test_schematics.py`](gen_test_schematics.py) | **Generator obu arkuszy.** `python3 schematics/gen_test_schematics.py` z katalogu głównego repo. Po zmianie tabel §10 popraw generator i wygeneruj SVG ponownie — nie edytuj tych dwóch SVG ręcznie. |
| [`schematic_test_build.svg`](schematic_test_build.svg) | **Schemat ideowy wariantu testowego, wersja skrócona** — symbole elektryczne, ale elementy pogrupowane w bloki. Szybki przegląd; do montażu użyj dwóch arkuszy powyżej. Opis: [`../docs/WDROZENIE_TESTOWE.md`](../docs/WDROZENIE_TESTOWE.md). |
| [`ignition_sense.svg`](ignition_sense.svg) | **Wykrywanie zapłonu → S3** — układ wejściowy z optoizolacją PC817 i wartościami elementów (R1 2,2 kΩ, R2 10 kΩ, C2 100 nF), przebieg uśpienia i wybudzania, oraz spis tego, czego brakuje w kodzie i firmwarze. |
| [`wiring_test_build.svg`](wiring_test_build.svg) | **Schemat połączeniowy wariantu testowego** — każdy zacisk podpisany, każdy przewód ponumerowany (1–20 + złącze B), punkt gwiazdowy masy, kolejność podłączania, przekroje. Tabele: [`../docs/SCHEMATY_POLACZEN.md`](../docs/SCHEMATY_POLACZEN.md) § 10. |
| [`wiring_power_modules.svg`](wiring_power_modules.svg) | **Moduły zasilania zacisk po zacisku** — każdy zacisk podpisany i ponumerowany, przekroje przewodów, bezpieczniki, punkty masy, kolejność podłączania. |
| [`wiring_vehicle_arduino.svg`](wiring_vehicle_arduino.svg) | **Sygnały pojazdu → Arduino** — punkty poboru w aucie, stopień PC817, dzielniki napięcia, podciągnięcia, rozpiska pinów trzech płytek, tor K-Line. |
| [`wiring_usb_av.svg`](wiring_usb_av.svg) | **USB, obraz, audio, kamery** — co idzie przez hub, a co bezpośrednio w port, przejściówki DP → HDMI, tor audio i przypisanie kamer. |
| [`vehicle_layout_m910q.svg`](vehicle_layout_m910q.svg) | **Rozmieszczenie w aucie** — rzut z góry Alfy 156 ze strefami montażu, trasami kablowymi, uzasadnieniem lokalizacji i bilansem masy. |

---

## Kolejność czytania przy montażu

1. **`power_domains_m910q.svg`** — najpierw ustal, co gdzie ma wisieć
   i jaki jest budżet poboru w każdym ze stanów maszyny.
2. **`power_buffered_m910q.svg`** — trasa zasilania, przekroje, bezpieczniki.
3. **`charging_lvd.svg`** — nastaw ładowarkę, rozłącznik nadnapięciowy i LVD
   **przed** pierwszym podłączeniem banku.
4. **`wiring_power_modules.svg`** — teraz łącz, zacisk po zacisku.
   Tabele „skąd → dokąd”: [`../docs/SCHEMATY_POLACZEN.md`](../docs/SCHEMATY_POLACZEN.md) § 2.
5. **`wiring_vehicle_arduino.svg`** — sygnały z auta, po jednym obwodzie.
6. **`wiring_usb_av.svg`** + **`audio_system.svg`** — peryferia i tor audio.

Zanim zaczniesz cokolwiek wiercić i prowadzić: **`vehicle_layout_m910q.svg`**
— pokazuje, co gdzie ląduje w aucie i którędy idą wiązki.

### Wariant testowo-rozwojowy — osobny komplet

Budujesz wariant z [`../docs/WDROZENIE_TESTOWE.md`](../docs/WDROZENIE_TESTOWE.md)?
Powyższa kolejność Cię **nie** dotyczy — tam nie ma domeny A ani przekaźnika
odcinającego odbiorniki. Czytaj trzy rysunki w tej kolejności:

1. **`schematic_test_build.svg`** — co z czym się łączy i dlaczego.
2. **`ignition_sense.svg`** — układ wejściowy zapłonu, wartości elementów.
3. **`wiring_test_build.svg`** — dopiero teraz zaciski, numery przewodów
   i kolejność podłączania.

---

## Konwencje na schematach

| Element | Znaczenie |
|---------|-----------|
| Gruba czerwona linia | Zasilanie 12 V (moc) |
| Zielona linia | Tor ładowania |
| Niebieska linia | Odgałęzienie odbiorników (za LVD i wyłącznikiem) |
| Linia przerywana | Sygnał sterujący (ACC, NTC), nie moc |
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
