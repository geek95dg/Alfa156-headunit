# Podsumowanie konsolidacji dokumentacji pod M910q

Raport z porządkowania repozytorium: przejście na jedną platformę produkcyjną,
archiwizacja materiałów pozostałych platform i nowa dokumentacja wdrożeniowa
wraz ze schematami zasilania buforowanego.

**Data:** 2026-07-25
**Gałąź:** `claude/m910q-deployment-docs-33g92j`
**PR:** [#106](https://github.com/geek95dg/Alfa156-headunit/pull/106)

> **To zapis z 25.07.2026 — projekt zasilania od tego czasu się zmienił.**
> Obowiązuje [`ZASILANIE_BUFOROWANE.md`](ZASILANIE_BUFOROWANE.md): zalewana
> przetwornica step-up 12 → 20 V / 200 W zamiast posiadanego wtedy XL6019,
> ładowanie z dwóch XY-SK120 zamiast dawnych wariantów A/B, bank 7 × HR1221W
> w dwóch koszach w bagażniku. §3.1, §3.1a, §3.2, §4 i §5 niżej są
> zaktualizowane do tego stanu (22.11.2026); reszta raportu to zapis
> z chwili konsolidacji.

---

## Punkt wyjścia

Repozytorium niosło **cztery platformy sprzętowe naraz** — Orange Pi 5 Pro,
Orange Pi 5 Plus, Orange Pi PC (bench rig) i x86 (Lenovo M910q) — bez
jednoznacznego wskazania, która obowiązuje. `README.md` nadal opisywał projekt
jako build na Orange Pi 5 Pro, mimo że produkcja od dawna stała na M910q.
Dokumentacja wdrożeniowa dla x86 była rozrzucona po trzech miejscach
(`X86_PLATFORM_SETUP.md`, 12 rozdziałów HTML, `URUCHOMIENIE.md`), w dwóch
językach i bez wspólnego punktu wejścia.

---

## 1. Archiwizacja materiałów innych platform

21 plików przeniesionych przez `git mv` — historia zachowana, `git log --follow`
działa na każdym z nich.

| Katalog | Zawartość |
|---------|-----------|
| `Archive/orange-pi-5/` | instrukcje OPi 5 Pro / 5 Plus, BOM, `requirements-opi.txt`, komplet schematów v7 w `schematics-v7/` |
| `Archive/orange-pi-pc/` | bench rig: instrukcje, BOM, requirements, launcher, `bcm_config_opi_pc.yaml`, jednostka systemd |
| `Archive/vm-smoke-tests/` | `VMWARE_SETUP.md`, `VM_USAGE_GUIDE.md` |

`Archive/README.md` wyjaśnia, co gdzie leży i dlaczego zostało wycofane.

### Decyzje warte odnotowania

**Cały zestaw schematów v7 trafił do archiwum.** Każdy rysunek wpina I/O
pojazdu wprost w 40-pinowe złącze GPIO Orange Pi, którego M910q nie ma —
na x86 to samo I/O idzie przez trzy płytki Arduino po USB. Numery pinów są
więc nie tyle nieaktualne, co bez desygnatu. `audio_system.svg` został
w `schematics/`: tor USB DAC → wzmacniacze nie zależy od platformy.

Same układy analogowe (PC817, dzielniki HC-SR04, sterownik MOSFET
podświetlenia) przeniosły się na Arduino bez zmian wartości elementów, więc
zarchiwizowane rysunki nadal bywają użyteczne jako referencja — jest o tym
adnotacja w `Archive/README.md`.

**`config/systemd/bcm-headunit.service` był wariantem Orange Pi PC** mimo
zupełnie neutralnej nazwy. Przy archiwizacji dostał jednoznaczną nazwę
`bcm-headunit-opi-pc.service`. Na M910q i tak instaluje się
`bcm-headunit-x86.service` **pod nazwą** `bcm-headunit.service` — to
nazewnictwo było źródłem realnego zamieszania.

**Kod platformowy w `src/` został nietknięty.** `main.py` i `src/core/hal.py`
nadal obsługują `--platform opi` i `--platform opi_pc`. To ścieżki runtime'owe,
a nie dokumentacja; ich przeniesienie zepsułoby aplikację. Zakres zadania
obejmował konsolidację dokumentacji, nie okrajanie funkcjonalności.

**`legacy/`** (nieużywane ekrany Pygame) zostało tam, gdzie było — to dług
techniczny niezwiązany z platformą.

### Przepięte odwołania

Żadne odwołanie nie zostało martwą ścieżką:

| Plik | Zmiana |
|------|--------|
| `src/core/config.py` | sonduje `config/`, a potem `Archive/orange-pi-pc/` — zarchiwizowany rig wstaje bez odtwarzania plików |
| `src/power/ignition_watcher.py` | `DEFAULT_CONFIG` i przykład użycia |
| `src/vehicle/blinker_monitor.py` | odwołanie do instrukcji okablowania + nota, że na M910q ten sam stopień PC817 wchodzi na Arduino |
| `config/systemd/bcm-headunit-x86.service` | komentarz o wariancie opi_pc |
| `config/systemd/bcm-ignition-watcher.service` | jw. |
| `assets/splash/README.md` | link do instrukcji OPi 5 Pro |
| `bcm_v85_docs.html` | dwa linki `<a href>` + ścieżka do `requirements-opi.txt` |
| `DEVELOPMENT_PLAN.md` | nagłówek „dokument historyczny", drzewo katalogów, lista schematów |
| `docs/URUCHOMIENIE.md` | Ścieżka C przepisana na tabelę platform zarchiwizowanych |
| `README.md` | projekt opisany jako build na M910q, nie na OPi 5 Pro |
| pliki wewnątrz `Archive/` | linki między `orange-pi-5/` a `orange-pi-pc/` |

### Ubuntu Touch — nie było czego archiwizować

Przeszukano bieżące drzewo **i całą historię gita**: zero trafień na
`ubuntu touch`, `halium`, `ubports`, `waydroid`, `anbox`. W tym repozytorium
nigdy nie było materiałów o próbach uruchomienia na Ubuntu Touch. Odnotowane
w `Archive/README.md` w sekcji „Czego tu nie ma".

---

## 2. Nowa dokumentacja

### `docs/WDROZENIE_M910Q.md`

Skonsolidowana instrukcja wdrożeniowa po polsku — pojedynczy punkt wejścia
dla całego procesu:

sprzęt i BOM · BIOS · instalacja Debiana 13 · instalacja BCM · cykl życia
usług systemd · boot/splash/kiosk · suspend S3 · wyświetlacze i dotyk · trzy
płytki Arduino · K-Line/OBD · WiFi i Android Auto · audio · przełączniki
modułów · odbiór techniczny · tabela diagnostyczna · reset instalacji

Każda komenda i ścieżka odnosi się do tego, co faktycznie jest w drzewie.
Miejsca, w których dokumentacja źródłowa jest niespójna albo kod odbiega
od opisu, są oznaczone ⚠ i zebrane w §19.

### `docs/ZASILANIE_BUFOROWANE.md`

Zasilanie buforowane w szczegółach: architektura jednej szyny, weryfikacja
posiadanej przetwornicy, karta katalogowa i łączenie banku CSB HR1221W, ładowanie w dwóch
wariantach, blokada przeładowania, LVD, bezpieczniki i przekroje, budżet
energetyczny, **lista zakupowa rozbita na „już posiadane" i „do dokupienia"**,
procedura pierwszego uruchomienia w siedmiu etapach, plan serwisowy.

### `schematics/`

| Plik | Zawartość |
|------|-----------|
| `power_buffered_m910q.svg` | tor główny: akumulator → rozdział ładowania → CC-CV → blokada przeładowania → bank CSB HR1221W → LVD → wyłącznik główny → step-up → M910q, z tabelą przekrojów i bezpieczników |
| `charging_lvd.svg` | cztery warstwy ochrony, nastawy dla CSB HR1221W (AGM), dwie tabele kompensacji temperaturowej, wpływ temperatury na żywotność, przebieg CC → CV → float |
| `power_domains_m910q.svg` | rozdział odbiorników, bezpieczniki odgałęzień, budżet poboru w trzech stanach maszyny, tabela czasu postoju, osobna gałąź wzmacniaczy |
| `README.md` | indeks, kolejność czytania przy montażu, konwencje rysunkowe |

---

## 3. Ustalenia zmieniające projekt układu

Wyszły przy weryfikacji dokumentacji względem stanu repozytorium i karty
katalogowej użytych akumulatorów. Każde jest w dokumentach opisane
z uzasadnieniem, nie samą tezą.

### 3.1 Limit prądu ładowania jest za wysoki dla CSB HR1221W

> **Historia tej pozycji.** Pierwsze wydanie raportu zakładało akumulatory
> żelowe i twierdziło, że nastawy napięciowe w repo (14,4 V / 13,8 V) są za
> wysokie. Po wskazaniu konkretnego modelu — **CSB HR1221W F2** — okazało się,
> że to **AGM**, a nie żel, więc **nastawy napięciowe w repo były prawidłowe**.
> Ustalenie zostało przeredagowane do tego, co faktycznie się nie zgadza.

Istniejąca dokumentacja (`X86_PLATFORM_SETUP.md` § 2.2,
`x86-production/10-power-suspend.html`) podaje 14,4 V absorpcji, 13,8 V float
i limit prądu **15–20 A**.

| Parametr | Stare notatki | Karta katalogowa CSB HR1221W | Werdykt |
|----------|--------------|------------------------------|---------|
| Absorpcja @ 25 °C | 14,4 V | 14,4–15,0 V (cykl) | ✅ prawidłowo |
| Float @ 25 °C | 13,8 V | 13,5–13,8 V (bufor) | ✅ prawidłowo |
| Maks. prąd ładowania | 15–20 A | **2,1 A/pakiet → 14,7 A na 7** | ⚠ mieści się w karcie, ale nie w torze |
| Kompensacja temperaturowa | brak | **−18 mV/°C** float, **−30 mV/°C** cykl | ❌ brak |

**Dlaczego prąd ma znaczenie.** Ładowanie powyżej katalogowego limitu grzeje
płyty i przyspiesza korozję siatki. Przy banku, jaki opisywały tamte notatki
(pięć pakietów, sufit 10,5 A), 15–20 A było niemal dwukrotnym przekroczeniem.
Dzisiejszy bank ma **siedem pakietów** i sufit katalogowy **14,7 A**, więc
dolny kraniec „15–20 A" już się w karcie mieści — zarzut zmienia adresata.
Nastawę ogranicza teraz **tor ładowania**, a nie akumulator. Obowiązuje
**2 × XY-SK120 po CC 5,0 A** — razem ok. 10 A, a po odjęciu obciążenia 4–6 A
do banku idzie netto ok. 5 A, czyli 34 % sufitu katalogowego. Granicę płytki
XH-M603 (realnie ok. 8 A) obchodzi jeden moduł na ładowarkę — każdy niesie
5 A (ZB §5.3, §6.3).

**Dlaczego kompensacja ma znaczenie.** Bagażnik latem osiąga 45–55 °C. Bez
kompensacji bank przy stałych 14,4 V jest w takich warunkach stale
przeładowywany. Uwaga: seria HR ma **dwa różne współczynniki** — inny dla
pracy buforowej, inny dla cyklicznej.

### 3.1a Żywotność banku wyznacza temperatura, nie cyklowanie

Karta podaje **3–5 lat pracy buforowej @ 25 °C** i **> 260 cykli przy 100 %
DoD**. Każde +10 °C mniej więcej połowi żywotność kalendarzową, podczas gdy
cyklowanie — nawet przy zejściu do 50 % DoD co tydzień — wyczerpałoby się
dopiero po dekadzie.

| Miejsce montażu | Szacowana żywotność |
|-----------------|--------------------|
| kabina | 2–4 lata |
| bagażnik | 1,5–3 lata |
| przy tunelu wydechowym | < 1,5 roku |

**Wniosek: miejsce montażu wpływa na życie banku bardziej niż dyscyplina
rozładowania.** Bank ostatecznie stoi jednak **w bagażniku**, w dwóch
stalowych koszach 4 + 3 przy grodzi za tylną kanapą — tylko tam mieści się
siedem pakietów z zachowaniem otworu na narty (ZB §4.7). Stąd w planie
serwisowym 1,5–3 lata życia banku.

### 3.2 Proponowany moduł buck nie może pełnić roli ładowarki

Stara dokumentacja stawia moduł **buck** XL4016 między diodą Schottky
a bankiem. To nie może działać:

```
alternator             14,4 V
− spadek na przewodach −0,2 V
− dioda Schottky       −0,45 V
─────────────────────────────
wejście przetwornicy   13,75 V
```

Buck **obniża** napięcie — z 13,75 V nie zrobi 14,40 V absorpcji. Bank utknąłby
na ~85 % pojemności i nigdy nie naładował się do końca.

Obowiązująca topologia (ZB §5):

| Rozwiązanie | Co robi | Koszt |
|-------------|---------|-------|
| **2 × XY-SK120** (buck-boost CC-CV) + przekaźnik K1 z zapłonu / D+ + 2 × XH-M603 | z 12,5–14,7 V robi 14,40 V w obie strony, CC 5,0 A każda; tor rozłączany przez K1 przy zgaszonym silniku | ok. 120–180 PLN za ładowarki (ogłoszenia) |
| alternatywa: izolowana ładowarka B2B (np. VEVOR 12/12-20) | izolacja galwaniczna i profil AGM z float w jednym pudełku; 20 A bez regulacji to za dużo dla banku (ZB §5.7) | ok. 400–550 PLN |

Wcześniej rozważane warianty — markowa B2B (800–1000 PLN) oraz „DIY”
z przekaźnikiem, diodą Schottky i modułem boost — wypadły: buck-boost nie
potrzebuje diody blokującej, a tani moduł z regulowanym CC wystarcza.

### 3.3 Czas postoju „~17 dni" to pełne rozładowanie

Liczba w `X86_PLATFORM_SETUP.md` § 2.3 jest opisana jako „ograniczone do 50 %
DoD", ale 25 Ah / 0,060 A = 417 h = 17,4 dnia to **zejście do zera**. Dla
banku, jaki tamte notatki opisywały (pięć pakietów, czyli faktycznie
25,5 Ah), ograniczenie do 50 % DoD daje 12,75 Ah / 0,060 A = 212 h, czyli
8,9 dnia. Dzisiejszy bank ma **siedem pakietów (35,7 Ah)** — obowiązujący
wiersz jest w tabeli niżej.

| Pakiety | Pojemność | Do 30 % DoD | Do 50 % DoD | Do progu LVD |
|---------|-----------|-------------|-------------|--------------|
| 4 | 20,4 Ah | ~4,3 dnia | ~7,1 dnia | ~10,6 dnia |
| 5 | 25,5 Ah | ~5,3 dnia | ~8,9 dnia | ~13,3 dnia |
| 6 | 30,6 Ah | ~6,4 dnia | ~10,6 dnia | ~15,9 dnia |
| **7** | **35,7 Ah** | **~7,4 dnia** | **~12,4 dnia** | **~18,6 dnia** |
| 8 | 40,8 Ah | ~8,5 dnia | ~14,2 dnia | ~21,3 dnia |

> Wiersz 5 był pierwotnie przyjęty jako optimum energetyczne, a wydanie
> pośrednie zeszło na **cztery** pakiety z powodu miejsca. Ostatecznie bank
> ma **siedem pakietów** (35,7 Ah, 12,6 kg) — uzasadnienie i to, co się przez
> to przesunęło, są w §4.2 [`ZASILANIE_BUFOROWANE.md`](ZASILANIE_BUFOROWANE.md).
> Ta tabela liczy przy poborze 60 mA (sama logika); tabela §9.2 tamtego
> dokumentu liczy przy poborze sumarycznym z LVD i to ona jest operacyjna.

Kolumna 30 % DoD doszła dlatego, że HR to seria buforowa (UPS), a nie
trakcyjna — płytsze rozładowanie wyraźnie wydłuża jej życie.

Obie liczby są teraz w tabeli osobno, z zaznaczeniem, że kolumna „do progu
LVD" to rezerwa awaryjna kosztem żywotności, a nie tryb normalnej pracy.

---

## 4. Przetwornica step-up — weryfikacja

> **Zaktualizowane 22.11.2026.** W chwili konsolidacji przetwornica była już
> kupiona (19 V) i powstała dla niej lista kontrolna z nastawą 19,5 V; potem
> wyszło, że dawny, posiadany moduł XL6019 realnie daje ok. 45 W i wymusza limit
> RAPL. Obowiązuje zalewana przetwornica **12 → 20 V, 10 A (200 W)** — ZB §3.

**20 V, nie 19 V.** Dokumentacja produkcyjna w repozytorium podaje, że M910q
pracuje w oknie **19–21 V i nie wystartuje poza nim**. Przetwornica stoi
w bagażniku, ok. 4 m od komputera: na pętli 2 × 4 m przewodu 4 mm² przy 65 W
spada ok. 0,11 V, więc z 20,0 V na wtyku zostaje ok. 19,9 V. Moduł 19 V
zszedłby w tym samym rachunku poniżej dolnej granicy (ZB §3.1).

**Obciążalność — wymaganie policzone, nie przepisane z naklejki** (sprawność
przyjęta konserwatywnie 90 %, ZB §3.2):

| Wielkość | Wartość |
|----------|---------|
| Prąd wyjściowy przy 65 W / 20 V | 3,25 A |
| Moc wejściowa | 72,2 W |
| Prąd wejściowy przy 12,6 V | 5,73 A |
| Prąd wejściowy przy 11,0 V (próg LVD) | **6,57 A** |

65 W to 33 % mocy z tabliczki modułu 200 W; nawet gdyby bezmarkowa sztuka
realnie dawała ok. 70 % opisu, to wciąż ok. 45 %. Limit RAPL nie jest
potrzebny. Wejście: F8 10 A, przewód 4 mm².

**Wtyk zasilania.** Najpewniejsze rozwiązanie to poświęcić oryginalny zasilacz:
odciąć kabel 30–40 cm od wtyku i podłączyć do wyjścia przetwornicy. Gwarantuje
to pasowanie mechaniczne. Środkowy pin identyfikacyjny Lenovo po odcięciu
znika — ThinkCentre Tiny w praktyce startują normalnie, ale nie da się tego
założyć w ciemno, stąd obowiązkowy test.

**Test na biurku przed zabudową** (ZB §3.4): bez obciążenia **19,9–20,5 V**,
przy ~60 W na wyjściu modułu ≥ 19,8 V, na wtyku M910q ≥ 19,5 V, obudowa
< 60 °C po 30 min, brak resetów, zapisany prąd jałowy. **Powtórzyć przy
napięciu wejściowym 11,0 V** — to najgorszy przypadek pod względem prądu
i grzania.

---

## 5. Co trzeba dokupić poza przetwornicą

Pełna lista (24 pozycje obowiązkowe + 6 zalecanych) jest
w `ZASILANIE_BUFOROWANE.md` §10. Rdzeń (stan z 22.11.2026):

| Grupa | Elementy |
|-------|----------|
| **Ładowanie** | 2 × XY-SK120 (CV 14,40 V, CC 5,0 A każda), przekaźnik ładowania K1 30 A z zapłonu / D+ |
| **Ochrona** | 2 × XH-M603 (15,30 / 14,00 V, po jednym na ładowarkę), LVD XH-M609 11,00 / 12,60 V (posiadany) |
| **Zabezpieczenia** | F1 20 A przy klemie, 7 × FB 10 A na pakiety, FC1/FC2 7,5 A, FK 1 A, F7 20 A i F12 15 A w klasie MIDI/ANL, dystrybucja F8–F11 i F13 |
| **Przetwornice** | step-up 12 → 20 V 10 A zalewany, MP1584 (logika, Arduino), LM2596 (wyświetlacze) |
| **Ochrona wejścia** | dioda TVS SMCJ20CA, kondensator 470 µF/35 V, dioda gaszeniowa 1N4007 |
| **Okablowanie** | 6 mm² OFC (F1, łącznik koszy, odbiór, masa), 4 mm², FLRY-B 2,5 mm², 0,5–1,5 mm², 4 bloki zbiorcze M6, oczka, nasuwki w pełni izolowane, peszel, przelotki |
| **Mechanika** | dwa kosze stalowe 4 + 3 ([`mechanika/kosze_HR1221W_4+3.pdf`](mechanika/kosze_HR1221W_4+3.pdf)), rozłącznik masy 100 A |

**Orientacyjnie:** ~740–1270 PLN bez pozycji „do wyceny” (wkładki MIDI/ANL,
bloki zbiorcze, stal na kosze) — ZB §10.2. Izolowana ładowarka B2B zamiast
dwóch XY-SK120 to +280–370 PLN.

Osobna sekcja **„czego nie kupować"** (ZB §10.4) wymienia moduł buck jako
ładowarkę, przetwornicę 19 V, XL6019 zamiast przetwornicy 200 W, przewód CCA,
jeden XH-M603 na dwie ładowarki, „uniwersalne" końcówki do M910q, ładowarki
LiFePO₄/Li-ion, ładowarki z presetem GEL (profil żelowy jest o 0,2–0,3 V
niższy — bank AGM nigdy nie doszedłby do pełna) i akumulatory rozruchowe
zamiast HR1221W.

---

## 6. Znaleziona luka — moduł `battery` nic nie liczy (naprawione później)

> **Stan obecny.** Luka opisana niżej została zamknięta po konsolidacji
> (przygotowane, domyślnie wyłączone): `arduino/sensor_hub` wysyła
> `BATT:<mV>[,<mA>]` (warianty `FEATURE_BATT_ADC` — dzielnik na A6 — i
> `FEATURE_BATT_INA226` — napięcie i prąd), `arduino_serial.py` publikuje
> z tego `arduino.battery_voltage`, a `battery.py` ma progi AGM 12 V.
> Włączenie: `make -C arduino sensor_hub-upload PORT=… SENSOR_HUB_FEATURES=BATT_ADC`
> i `modules.battery: true`; kalibracja i szczegóły w
> `ZASILANIE_BUFOROWANE.md` §13.4. Tekst niżej to zapis stanu z chwili
> konsolidacji.

`src/power/battery.py` ma progi **ogniwa Li-ion 18650**:

```python
FULL_V = 4.2
NOMINAL_V = 3.7
LOW_V = 3.3
CRITICAL_V = 3.0
```

Moduł nasłuchuje zdarzenia `arduino.battery_voltage`, którego **żaden z trzech
sketchy Arduino w repozytorium nie publikuje**. `modules.battery: true`
w `config/bcm_config.yaml` włącza więc kod, który nigdy nic nie policzy.

Żeby monitoring banku faktycznie działał, potrzeba trzech rzeczy:

1. **dzielnik napięcia** na wejściu ADC sensor huba (np. 100 kΩ / 27 kΩ,
   rezystory 1 %, kondensator 100 nF),
2. **publikacja odczytu** z `sensor_hub.ino` jako `BATT:<napięcie>`,
3. **progi dla banku 12 V** zamiast ogniwa Li-ion — proponowane:
   12,85 / 12,40 / 11,80 / 11,20 V (`CRITICAL_V` powyżej progu LVD 11,0 V,
   żeby BCM zdążył zareagować, zanim LVD odetnie zasilanie).

W chwili konsolidacji **nie zostało to naprawione** — to praca po stronie
firmware'u Arduino, wykraczająca poza zakres zadania dokumentacyjnego.
Zrobione później (ramka wyżej); opis w `ZASILANIE_BUFOROWANE.md` §13.4
i `WDROZENIE_M910Q.md` §19.3.

---

## 7. Pozostałe odnotowane rozbieżności

| # | Rozbieżność | Gdzie opisana |
|---|-------------|---------------|
| 1 | `setup-x86.sh` ma w USER CONFIG `MAIN_OUTPUT="HDMI-1"` / `SMALL_OUTPUT="HDMI-2"`, a M910q ma **dwa wyjścia DisplayPort** (zwykle `DP-1`/`DP-2`) | `WDROZENIE_M910Q.md` §6.5, §19.1 |
| 2 | Nazewnictwo `bcm-headunit.service` — plik był wariantem OPi PC | `WDROZENIE_M910Q.md` §7.1, §19.5 |
| 3 | Limit prądu ładowania 15–20 A wobec katalogowych 10,5 A | `WDROZENIE_M910Q.md` §19.2 |
| 4 | Buck jako ładowarka | `ZASILANIE_BUFOROWANE.md` §5.1, §13.2 |
| 5 | Czas postoju „17 dni" | `WDROZENIE_M910Q.md` §19.4 |

---

## 8. Weryfikacja

| Sprawdzenie | Wynik |
|-------------|-------|
| `pytest tests/` | **419 passed** |
| `ruff check .` | **All checks passed** |
| Odnośniki względne w plikach `.md` | **81 sprawdzonych, 0 zepsutych** |
| Kotwice spisów treści w nowych dokumentach | zweryfikowane względem nagłówków |
| Nowe pliki SVG | zwalidowane jako XML, wyrenderowane do PNG i obejrzane pod kątem kolizji tekstu |

`tests/test_integration.py::test_current_headunit_service_exists` sprawdzał
zarchiwizowaną jednostkę OPi PC — teraz sprawdza `bcm-headunit-x86.service`,
czyli plik faktycznie instalowany na produkcji. To jedyna zmiana w testach.

---

## 9. Stan dokumentacji po konsolidacji

```
docs/
├── WDROZENIE_M910Q.md          ← punkt wejścia dla wdrożenia (NOWY)
├── ZASILANIE_BUFOROWANE.md     ← zasilanie + lista zakupowa (NOWY)
├── PODSUMOWANIE_KONSOLIDACJI.md ← ten dokument (NOWY)
├── URUCHOMIENIE.md             ← symulacja, przełączniki modułów
├── X86_PLATFORM_SETUP.md       ← referencja krok-po-kroku (EN)
├── ARDUINO_SETUP_GUIDE.md      ← okablowanie trzech płytek
├── ARDUINO_OD_ZERA.md          ← pierwsze wgranie firmware (NOWY)
├── KLINE_SNIFFING.md           ← podsłuch K-Line, PID-y ECU
└── x86-production/             ← 12 rozdziałów HTML z ilustracjami

schematics/
├── README.md                   ← indeks (NOWY)
├── power_buffered_m910q.svg    ← tor główny (NOWY)
├── charging_lvd.svg            ← ładowanie i ochrona (NOWY)
├── power_domains_m910q.svg     ← rozdział odbiorników (NOWY)
└── audio_system.svg            ← tor audio (bez zmian)

Archive/
├── README.md                   ← co gdzie leży i dlaczego (NOWY)
├── orange-pi-5/                ← OPi 5 Pro / 5 Plus + schematy v7
├── orange-pi-pc/               ← bench rig
└── vm-smoke-tests/             ← VMware
```

---

## 10. Co dalej

Rzeczy, które wyszły przy porządkowaniu, a nie zostały zrobione, bo wykraczają
poza zakres konsolidacji dokumentacji:

| # | Zadanie | Zakres |
|---|---------|--------|
| 1 | ~~Dorobić monitoring banku buforowego (§6)~~ — zrobione, domyślnie wyłączone | firmware Arduino + progi w `battery.py` |
| 2 | Poprawić domyślne `MAIN_OUTPUT`/`SMALL_OUTPUT` w `setup-x86.sh` na `DP-1`/`DP-2` | jedna linia, ale wymaga potwierdzenia na sprzęcie |
| 3 | Poprawić limit prądu ładowania i dopisać kompensację temperaturową w `X86_PLATFORM_SETUP.md` i `10-power-suspend.html` | dokumenty źródłowe, obecnie tylko oznaczone ⚠ |
| 4 | Przenieść treść `x86-production/*.html` do markdown albo odwrotnie | duplikacja treści między MD a HTML |
