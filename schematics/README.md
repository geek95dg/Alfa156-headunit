# BCM v8.5 — schematy elektryczne (platforma Lenovo M910q)

Schematy obowiązujące dla **produkcyjnej platformy x86 — Lenovo ThinkCentre
M910q Tiny**. Opis słowny, dobór podzespołów, nastawy i lista zakupowa:
**[`../docs/ZASILANIE_BUFOROWANE.md`](../docs/ZASILANIE_BUFOROWANE.md)**.

---

## Zawartość

| Plik | Co przedstawia |
|------|----------------|
| [`power_buffered_m910q.svg`](power_buffered_m910q.svg) | **Tor główny zasilania** — od klemy akumulatora, przez rozdział ładowania, ładowarkę CC-CV, blokadę przeładowania, bank żelowy i LVD, po przekaźnik zapłonu, przetwornicę step-up 19 V i M910q. Zawiera tabelę przekrojów przewodów i bezpieczników. |
| [`charging_lvd.svg`](charging_lvd.svg) | **Ładowanie i ochrona banku** — cztery warstwy (VSR → CC-CV → rozłącznik nadnapięciowy → LVD), komplet nastaw dla akumulatorów **żelowych**, tabela kompensacji temperaturowej, przebieg CC → CV → float. |
| [`power_domains_m910q.svg`](power_domains_m910q.svg) | **Domeny A/B** — rozdział obciążeń między część zawsze zasilaną a część załączaną zapłonem, bezpieczniki odgałęzień, budżet poboru spoczynkowego, tabela czasu postoju, osobna gałąź wzmacniaczy. |
| [`audio_system.svg`](audio_system.svg) | **Tor audio** — ES9038Q2M (USB DAC) → TDA7388 4 × 45 W + TDA2050 (subwoofer) → układ głośników 4.1. Niezależny od platformy — obowiązuje bez zmian. |

---

## Kolejność czytania przy montażu

1. **`power_domains_m910q.svg`** — najpierw ustal, co gdzie ma wisieć.
   Podział na domeny determinuje całą resztę okablowania.
2. **`power_buffered_m910q.svg`** — trasa zasilania, przekroje, bezpieczniki.
3. **`charging_lvd.svg`** — nastaw ładowarkę, rozłącznik nadnapięciowy i LVD
   **przed** pierwszym podłączeniem banku.
4. **`audio_system.svg`** — tor audio, osobna gałąź 12 V.

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
