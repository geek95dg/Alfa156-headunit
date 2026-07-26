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
| [`power_buffered_m910q.svg`](power_buffered_m910q.svg) | **Tor główny zasilania** — od klemy akumulatora, przez rozdział ładowania, ładowarkę CC-CV, blokadę przeładowania, bank CSB HR1221W i LVD, po przekaźnik zapłonu, przetwornicę step-up 19 V i M910q. Zawiera tabelę przekrojów przewodów i bezpieczników. |
| [`charging_lvd.svg`](charging_lvd.svg) | **Ładowanie i ochrona banku** — cztery warstwy (przekaźnik ładowania → CC-CV → rozłącznik nadnapięciowy → LVD), komplet nastaw dla **CSB HR1221W (AGM)**, dwie tabele kompensacji temperaturowej, wpływ temperatury na żywotność, przebieg CC → CV → float. |
| [`power_domains_m910q.svg`](power_domains_m910q.svg) | **Domeny A/B** — rozdział obciążeń między część zawsze zasilaną a część załączaną zapłonem, bezpieczniki odgałęzień, budżet poboru spoczynkowego, tabela czasu postoju, osobna gałąź wzmacniaczy. |
| [`audio_system.svg`](audio_system.svg) | **Tor audio** — ES9038Q2M (USB DAC) → RCA → **gotowy wzmacniacz samochodowy** → głośniki 4 Ω. Wzmacniacz zasilany wprost z akumulatora rozruchowego, z własną masą — całkowicie odseparowany od systemu buforowanego. |
| [`power_test_build.svg`](power_test_build.svg) | **Wariant testowo-rozwojowy** — uproszczony tor dla instalacji jeżdżącej z minimalnym zestawem funkcji: ładowanie wariantem B (przekaźnik + MBR2545CT + CC-CV boost), bank, LVD, XL6019 i panel 7". M910q zasilany stale, zapłon tylko jako sygnał. Bez domeny A i bez wzmacniacza. Opis: [`../docs/WDROZENIE_TESTOWE.md`](../docs/WDROZENIE_TESTOWE.md). |

### Schematy połączeniowe — montaż

| Plik | Co przedstawia |
|------|----------------|
| [`wiring_power_modules.svg`](wiring_power_modules.svg) | **Moduły zasilania zacisk po zacisku** — każdy zacisk podpisany i ponumerowany, przekroje przewodów, bezpieczniki, punkty masy, kolejność podłączania. |
| [`wiring_vehicle_arduino.svg`](wiring_vehicle_arduino.svg) | **Sygnały pojazdu → Arduino** — punkty poboru w aucie, stopień PC817, dzielniki napięcia, podciągnięcia, rozpiska pinów trzech płytek, tor K-Line. |
| [`wiring_usb_av.svg`](wiring_usb_av.svg) | **USB, obraz, audio, kamery** — co idzie przez hub, a co bezpośrednio w port, przejściówki DP → HDMI, tor audio i przypisanie kamer. |
| [`vehicle_layout_m910q.svg`](vehicle_layout_m910q.svg) | **Rozmieszczenie w aucie** — rzut z góry Alfy 156 ze strefami montażu, trasami kablowymi, uzasadnieniem lokalizacji i bilansem masy. |

---

## Kolejność czytania przy montażu

1. **`power_domains_m910q.svg`** — najpierw ustal, co gdzie ma wisieć.
   Podział na domeny determinuje całą resztę okablowania.
2. **`power_buffered_m910q.svg`** — trasa zasilania, przekroje, bezpieczniki.
3. **`charging_lvd.svg`** — nastaw ładowarkę, rozłącznik nadnapięciowy i LVD
   **przed** pierwszym podłączeniem banku.
4. **`wiring_power_modules.svg`** — teraz łącz, zacisk po zacisku.
   Tabele „skąd → dokąd”: [`../docs/SCHEMATY_POLACZEN.md`](../docs/SCHEMATY_POLACZEN.md) § 2.
5. **`wiring_vehicle_arduino.svg`** — sygnały z auta, po jednym obwodzie.
6. **`wiring_usb_av.svg`** + **`audio_system.svg`** — peryferia i tor audio.

Zanim zaczniesz cokolwiek wiercić i prowadzić: **`vehicle_layout_m910q.svg`**
— pokazuje, co gdzie ląduje w aucie i którędy idą wiązki.

---

## Konwencje na schematach

| Element | Znaczenie |
|---------|-----------|
| Gruba czerwona linia | Zasilanie 12 V (moc) |
| Zielona linia | Odgałęzienie domeny A (zawsze zasilana) |
| Niebieska linia | Odgałęzienie domeny B (za zapłonem) |
| Linia przerywana | Sygnał sterujący (ACC, NTC), nie moc |
| Ramka pomarańczowa | Element zabezpieczający (bezpiecznik, LVD, rozłącznik) |
| Ramka zielona | Domena A / bank akumulatorów |
| Ramka niebieska | Domena B |
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
