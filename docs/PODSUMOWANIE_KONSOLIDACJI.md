# Podsumowanie konsolidacji dokumentacji pod M910q

Raport z porządkowania repozytorium: przejście na jedną platformę produkcyjną,
archiwizacja materiałów pozostałych platform i nowa dokumentacja wdrożeniowa
wraz ze schematami zasilania buforowanego.

**Data:** 2026-07-25
**Gałąź:** `claude/m910q-deployment-docs-33g92j`
**PR:** [#106](https://github.com/geek95dg/Alfa156-headunit/pull/106)

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
Nastawę ogranicza teraz **tor ładowania**, a nie akumulator: płytka XH-M603
wyrabia ok. 10 A i spec podaje „≤ 8 A". Przyjęta nastawa to **CC 8,0 A**,
czyli 54 % sufitu katalogowego i 80 % obciążalności płytki.

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
| kabina, pod fotelem | 2–4 lata |
| bagażnik | 1,5–3 lata |
| przy tunelu wydechowym | < 1,5 roku |

**Wniosek: miejsce montażu wpływa na życie banku bardziej niż dyscyplina
rozładowania.**

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

Podane dwie działające topologie:

| Wariant | Rozwiązanie | Koszt |
|---------|-------------|-------|
| **A — zalecany** | ładowarka DC-DC B2B z presetem AGM (Victron Orion-Tr Smart, Redarc BCDC, Sterling) — buck-boost, limit prądu, kompensacja temperaturowa, detekcja pracy alternatora w jednym pudełku | 800–1000 PLN |
| **B — DIY** | przekaźnik ładowania + dioda **MBR2545CT** + moduł **CC-CV boost** nastawiony na 14,40 V / **8,0 A** | 70–180 PLN |

W wariancie B tor ładowania **musi być fizycznie rozłączany**: boost nie może
dawać napięcia niższego niż wejściowe, więc przy zgaszonym silniku próbowałby
dalej podawać 14,4 V i rozładowywał akumulator rozruchowy. Robi to przekaźnik
sterowany zapłonem (albo D+ alternatora), a dioda MBR2545CT jest drugą
barierą na wypadek zespawania styków.

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

Przetwornica jest już kupiona (19 V), więc zamiast doboru powstała lista
kontrolna. Wnioski:

**19 V mieści się w zakresie, ale przy samej dolnej granicy.** Dokumentacja
produkcyjna w repozytorium podaje, że M910q pracuje w oknie **19–21 V i nie
wystartuje poza nim**. Pod obciążeniem dochodzi spadek na przewodzie,
regulacja obciążeniowa przetwornicy i spadek napięcia wejściowego, gdy bank
schodzi w stronę LVD.

> **Nastawa: 19,5 V, nie 19,0 V.** Nadal bezpiecznie w oknie, a daje ~0,5 V
> zapasu na zapady. Regulować pod obciążeniem, potem zabezpieczyć potencjometr
> przed rozstrojeniem wibracjami.

**Obciążalność — wymaganie policzone, nie przepisane z naklejki:**

| Wielkość | Wartość |
|----------|---------|
| Prąd wyjściowy przy 19,5 V | 3,34 A |
| Moc wejściowa przy sprawności 88 % | 73,9 W |
| Prąd wejściowy przy 12,6 V | 5,9 A |
| Prąd wejściowy przy 11,0 V (próg LVD) | **6,7 A** |

Wymaganie: **≥ 3,5 A wyjścia i ≥ 7 A wejścia w pracy ciągłej.**

> ⚠ **Uwaga do modułów „XL6019 150 W".** Sam układ XL6019 ma prąd klucza
> ok. 5 A, a przy 65 W wyjścia prąd klucza sięga ~7 A — **powyżej wartości
> katalogowej**. Taki moduł jest dobry do typowego obciążenia (25–35 W, czyli
> realny pobór M910q z dashboardem), ale ryzykowny w szczycie. Deklarowane
> „150 W" to zwykle szczyt przy maksymalnym napięciu wejściowym i z chłodzeniem.

**Wtyk zasilania.** Najpewniejsze rozwiązanie to poświęcić oryginalny zasilacz:
odciąć kabel 30–40 cm od wtyku i podłączyć do wyjścia przetwornicy. Gwarantuje
to pasowanie mechaniczne. Środkowy pin identyfikacyjny Lenovo po odcięciu
znika — ThinkCentre Tiny w praktyce startują normalnie, ale nie da się tego
założyć w ciemno, stąd obowiązkowy test.

**Test na biurku przed zabudową** (`stress-ng --cpu 4 --timeout 600s`):
napięcie na wtyku ≥ 19,0 V przez cały czas, temperatura cewki i układu
< 85 °C, brak resetów. **Powtórzyć przy napięciu wejściowym 11,0 V** — to
najgorszy przypadek pod względem prądu i grzania.

---

## 5. Co trzeba dokupić poza przetwornicą

Pełna lista (24 pozycje obowiązkowe + 5 zalecanych) jest
w `ZASILANIE_BUFOROWANE.md` §10. Rdzeń:

| Grupa | Elementy |
|-------|----------|
| **Ładowanie** | ładowarka DC-DC z profilem AGM (wariant A) **albo** przekaźnik + MBR2545CT + moduł CC-CV boost (wariant B) |
| **Ochrona** | rozłącznik nadnapięciowy 15,3 V (blokada przeładowania), moduł LVD 11,0 V, przekaźnik ładowania 30 A, przekaźnik mocy |
| **Zabezpieczenia** | listwa dystrybucyjna 6–8 obwodów, bezpiecznik główny 30 A, 5× inline 10 A na pakiety, wkładki 5/3/20 A |
| **Przetwornice pomocnicze** | buck 12→5 V 1 A (logika), buck 12→5 V 3 A (wyświetlacze) |
| **Ochrona wejścia** | dioda TVS 1.5KE33CA, kondensator 470 µF/35 V, diody gaszeniowe 1N4007 |
| **Okablowanie** | 6 mm² (główne + masa), 2,5 mm², 1,5 mm², 0,75 mm², konektory, peszel, przelotki |
| **Mechanika** | skrzynka/wspornik na bank z pasami, rozłącznik masy 100 A, radiator + wentylator 40 mm do przetwornicy |

**Orientacyjnie:** ~600–1100 PLN w wariancie DIY, ~1300–1900 PLN z gotową
ładowarką B2B.

Osobna sekcja **„czego nie kupować"** wymienia moduł buck jako ładowarkę,
diodę krzemową zamiast Schottky, „uniwersalne" końcówki do M910q, ładowarki
LiFePO₄/Li-ion, ładowarki z presetem GEL (profil żelowy jest o 0,2–0,3 V niższy —
bank AGM nigdy nie doszedłby do pełna) i akumulatory rozruchowe zamiast HR1221W.

---

## 6. Znaleziona luka — moduł `battery` nic nie liczy

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

**Nie zostało to naprawione** — to praca po stronie firmware'u Arduino,
wykraczająca poza zakres zadania dokumentacyjnego. Rozpisane
w `ZASILANIE_BUFOROWANE.md` §13.4 i `WDROZENIE_M910Q.md` §19.3. Do czasu
wykonania — kontrola woltomierzem z listy zalecanych zakupów.

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
| 1 | Dorobić monitoring banku buforowego (§6) | firmware Arduino + progi w `battery.py` |
| 2 | Poprawić domyślne `MAIN_OUTPUT`/`SMALL_OUTPUT` w `setup-x86.sh` na `DP-1`/`DP-2` | jedna linia, ale wymaga potwierdzenia na sprzęcie |
| 3 | Poprawić limit prądu ładowania i dopisać kompensację temperaturową w `X86_PLATFORM_SETUP.md` i `10-power-suspend.html` | dokumenty źródłowe, obecnie tylko oznaczone ⚠ |
| 4 | Przenieść treść `x86-production/*.html` do markdown albo odwrotnie | duplikacja treści między MD a HTML |
