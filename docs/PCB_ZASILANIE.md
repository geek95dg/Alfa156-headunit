# PCB zasilania buforowanego — dwie płytki do samodzielnego wytrawienia

Zasilanie buforowane z [`ZASILANIE_BUFOROWANE.md`](ZASILANIE_BUFOROWANE.md)
(dalej: ZB) przeniesione z „pająka" na dwie jednostronne płytki drukowane,
które trawisz w domu. Elementy dyskretne (przekaźnik ładowania, TVS,
kondensator, dzielnik pomiarowy, bezpieczniki odgałęzień) są wlutowane;
moduły kupne (2 × XY-SK120, 2 × XH-M603, XH-M609, przetwornica step-up 20 V,
bucki 5 V) podłączasz do zacisków śrubowych albo przewodami — więc budujesz
i wymieniasz je **etapami**, bez lutownicy przy każdej zmianie.

| Plik | Co zawiera |
|------|-----------|
| [`../schematics/pcb_power_schematic.svg`](../schematics/pcb_power_schematic.svg) | schemat ideowy obu płytek + otoczenie (dwie gałęzie ładowania, bank, LVD), tabela zacisków |
| [`../schematics/pcb_power_layout.svg`](../schematics/pcb_power_layout.svg) | rozmieszczenie elementów 1:1, opisy zacisków, BOM, wiercenie |
| [`../schematics/pcb_power_etch.svg`](../schematics/pcb_power_etch.svg) | **mozaika miedzi 1:1 do wydruku** + widok kontrolny + proces trawienia |
| [`../schematics/gen_pcb_power.py`](../schematics/gen_pcb_power.py) | generator trzech powyższych — po zmianie projektu popraw i wygeneruj ponownie |
| [`../schematics/png/pcb_power_schematic.png`](../schematics/png/pcb_power_schematic.png) | ten sam schemat ideowy w PNG — do podglądu na telefonie; render [`../schematics/render_png.py`](../schematics/render_png.py). **Uwaga:** PNG trzeba wygenerować ponownie po tej zmianie (wymaga `cairosvg`) — do tego czasu pokazuje poprzedni projekt |

Generator sam sprawdza spójność sieci i prześwity (uruchom
`python3 schematics/gen_pcb_power.py` — błędy projektu przerywają generację).

Rastrową kopię schematu ideowego robi `python3 schematics/render_png.py`
(wynik w `schematics/png/`, szczegóły w
[`../schematics/README.md`](../schematics/README.md#eksport-do-png)). Montażówki
i mozaiki miedzi **nie drukuj z PNG** — te dwa arkusze idą do druku wyłącznie
z SVG w skali 100 %, z kontrolą linijki 50 mm.

---

## Spis treści

1. [Co jest na której płytce](#1-co-jest-na-której-płytce)
2. [Przetwornica step-up 20 V — poza płytkami](#2-przetwornica-step-up-20-v--poza-płytkami)
3. [Decyzje projektowe](#3-decyzje-projektowe)
4. [Co celowo pominięto (anty-overkill)](#4-co-celowo-pominięto-anty-overkill)
5. [Lista zakupowa płytek](#5-lista-zakupowa-płytek)
6. [Trawienie krok po kroku](#6-trawienie-krok-po-kroku)
7. [Montaż i budowa etapami](#7-montaż-i-budowa-etapami)
8. [Kontrola przed zabudową](#8-kontrola-przed-zabudową)

---

## 1. Co jest na której płytce

Obie płytki stoją **w bagażniku, przy koszach banku** — tam, gdzie
ładowarki, LVD i przetwornica (ZB §8a). Numery przewodów odpowiadają §10
[`SCHEMATY_POLACZEN.md`](SCHEMATY_POLACZEN.md).

### Płytka A — tor ładowania, strona pojazdu (100 × 75 mm)

Realizuje przewody **3, 5 i 5a** jako ścieżki:

```
X1 (+AKU za F1 20 A) → D5 (TVS) + C1 → K1 (styk 30 → 87)
   → X2.1 → XY-SK120 #1 IN+
   → X2.2 → XY-SK120 #2 IN+
```

| Zacisk | Podłączenie | Przewód (§10.1) |
|--------|-------------|-----------------|
| X1.1 / X1.2 | „+" z F1 20 A (6 mm²) · masa (opcjonalna — główna masa idzie śrubą M4) | 2 |
| X2.1 / X2.2 | IN+ XY-SK120 #1 / IN+ XY-SK120 #2 (2,5 mm², ≤ 1 m każdy) | 5 / 5a |
| X6.1 / X6.2 | zapłon albo D+ przez FK 1 A (cewka K1) · przelot sygnału dalej — **tylko gdy X6.1 = zapłon/ACC**; przy D+ X6.2 zostaje wolny, a PC817 (przewód 15, §10.4) i REM biorą zapłon/ACC osobno z przodu | 4 |
| GND M4 | oczko 6 mm² → punkt masy przy banku | — |

Na płytce **nie ma** ładowarek, XH-M603, wkładek FC1/FC2 ani F12. Przez
nie płyną prądy od strony banku — przy F12 do ok. 2,2 kA zwarciowo — których
ścieżka na laminacie nie ma prawa nieść. Stoją obok, na przewodach 2,5 mm²
i 4 mm², dokładnie jak w §2.1 [`SCHEMATY_POLACZEN.md`](SCHEMATY_POLACZEN.md).
Masy obu XY-SK120 (wejście = wyjście, brak izolacji) i obu XH-M603 idą
**prosto do punktu masy przy banku**, nie przez płytkę (ZB §5.6).

K1 to **przekaźnik PCB T90 (SLA-12VDC-SL-A, 30 A)** wlutowany w płytkę —
zastępuje przekaźnik z podstawką. Datasheet Songle podaje **okrągłe**
otwory (styki Φ2,0, cewka Φ1,0) — bez slotów, zwykłe wiertła. Pady COM-A
i NC są wiercone, ale zostają wolne, więc pasują warianty 4-, 5- i 6-pinowe.
Przez styk płynie do **13 A** (dwie ładowarki przy kluczyku na ON, ZB §5.4)
— 43 % nominału styków.

Cewkę K1 lepiej zasilać z D+ (ZB §5.4) — ładowanie rusza dopiero przy
pracującym silniku. Wtedy **nie** używaj przelotu X6.2: D+ na wejściu
PC817 dałoby Arduino „zapłon wyłączony" przy kluczyku na ON aż do
uruchomienia silnika (M910q zostaje w S3), a transoptor dociążyłby obwód
lampki ładowania.

**D5 = SMCJ20CA** w obudowie SMC (DO-214AB) — SMD, lutowana **od strony
miedzi** na dwóch padach bez otworów. Dawna osiowa 1.5KE33CA ogranicza
dopiero przy ok. 45 V, a XY-SK120 przyjmuje najwyżej 36 V (ZB §5.8). Pady
3,4 × 2,6 mm w rozstawie 7,0 mm to przyjęcie z typowych land patternów SMC —
**porównaj z kartą kupionej diody przed trawieniem**.

### Płytka B — dystrybucja szyny buforowanej (100 × 60 mm)

Rozdziela szynę za LVD (XH-M609) — przewody **10, 11, 13 i 13a** — i zastępuje
osobną listwę bezpiecznikową dla odgałęzień:

| Zacisk | Gałąź | Bezpiecznik |
|--------|-------|-------------|
| X8.1 / X8.2 | wejście z XH-M609 VOUT+ · masa → punkt masy | — (F7 20 A MIDI/ANL przy bloku L+, przed LVD) |
| X9 | przetwornica step-up 20 V IN+ | **F8**: 10 A |
| X10 | LM2596 IN+ (podświetlenie panelu) | **F9**: 2 A |
| X11 | MP1584 IN+ (Arduino Nano) | **F10**: 3 A |
| X12 | AUX 12 V (moduł przekaźników, hub USB) | **F11**: 5 A |
| J1.1 / J1.2 | V_BANK → ADC sensor-huba · GND sygnałowa | — |

Wkładka **F13 2 A** (wstrzykiwacz 5 V telefonu, opcja z ZB §14.6) nie ma
miejsca na płytce — oprawka inline obok, z tej samej szyny X8.1.

Wyłącznik główny **S1** to rozłącznik masy banku (ZB §8.4) — siedzi
w przewodzie P− → punkt masy, nie w torze „+”, więc płytka B go nie widzi.

Bezpieczniki to zwykłe **wkładki nożowe ATO** w pionowych oprawkach PCB
(otwory Φ2,0 w rozstawie 9,2 mm — standard potwierdzony w bibliotece KiCad;
czop centrujący Φ2,4). Dzielnik **R5/R6 = 100 kΩ/27 kΩ 1 % + C7 100 nF**
realizuje pomiar napięcia banku z ZB §13.4 (15 V → 3,2 V na ADC).

**Minusy modułów** (XY-SK120, XH-M603, XH-M609, przetwornice) idą do punktu
masy przy banku — przez płytki nie płynie żaden prąd powrotny odbiorników
(SCHEMATY_POLACZEN.md §10.6).

---

## 2. Przetwornica step-up 20 V — poza płytkami

Komputer zasila **zalewana przetwornica step-up 12 → 20 V, 10 A (200 W)**,
IP67/IP68 — rodzina bezmarkowych modułów, opisana w ZB §3. Na płytce B ma
tylko zacisk X9 za wkładką **F8 10 A** (65 W przy 11,0 V to ok. 6,6 A
wejścia). Powtórzone tu najważniejsze:

- **20 V, nie 19 V** — po ok. 4 m przewodu 4 mm² do M910q na wtyku zostaje
  ok. 19,9 V; moduł 19 V zszedłby poniżej dolnej granicy 19 V (ZB §3.1),
- moduł jest zwykle **bez regulacji** — nie ma czego nastawiać; sprawdzasz
  każdą sztukę: bez obciążenia **19,9–20,5 V**, przy ~60 W ≥ 19,8 V na
  wyjściu i ≥ 19,5 V na wtyku, powtórka przy wejściu 11,0 V, temperatura
  obudowy < 60 °C po 30 min, prąd jałowy zapisany (ZB §3.4),
- limit RAPL **nie jest potrzebny** (ZB §3.5a zostaje jako opcja),
- kondensator 470 µF i NTC na wyjściu — tylko przy „czkawce” (ZB §3.2b),
  w linii, poza płytką.

Wcześniejsze wydanie tego dokumentu zalecało boost CC-CV „1500 W 30 A”
nastawiany potencjometrem na 19,5–20 V; obowiązuje moduł z ZB §3.

---

## 3. Decyzje projektowe

### Dwie XY-SK120, każda z własnym XH-M603 w torze

XH-M603 ma przekaźnik **wewnątrz**, w torze DC-IN+ → OUT+ (bez wolnego styku
COM/NO), i mierzy napięcie **po stronie OUT** — tam, gdzie wisi bank. Gdyby
OUT sterował cewką osobnego przekaźnika mocy, po zadziałaniu napięcie na OUT
spadłoby do zera przez cewkę → moduł widzi „pusty akumulator" → zwiera
z powrotem → **oscylacja kilka razy na sekundę, styki umierają**. W torze
ładowania (do czego moduł zaprojektowano) wszystko się zgadza.

Płytka modułu wytrzymuje realnie ok. **8 A** (oszacowanie z oględzin, nie
karta). Dwie ładowarki dają razem 10 A, więc **jeden XH-M603 na każdą
XY-SK120** — każdy niesie 5 A, 62 % granicy (ZB §6.3). Przy przebiciu jednej
ładowarki oba XH-M603 widzą to samo napięcie banku i przy 15,30 V rozwierają
oba. Progi: rozwarcie 15,30 V, powrót 14,00 V.

> **Zmierz temperaturę zacisków XH-M603 przy 5 A przez 30 min** przed
> zabudową (ZB §11 Etap 1). Obciążalność ~8 A jest oszacowaniem.

### Bez diody blokującej i bez przekaźnika K2

XY-SK120 to **buck-boost**: z 12,5–14,7 V z instalacji robi 14,40 V w obie
strony, więc nie potrzebuje wejścia wyższego od CV, a dawna dioda MBR2545CT
z radiatorem odpada (ZB §5.1). Przepływ wsteczny na postoju zatrzymuje
rozwarty K1; czy XH-M603 bez zasilania ma rozwarty przekaźnik i nie bierze
prądu z banku — to **przyjęcie**, które potwierdza test ZB §6.4 pkt 6.

### Pozostałe

| Decyzja | Powód |
|---------|-------|
| F1 = 20 A | ładowarki biorą z instalacji 11,9–13,0 A; 15 A pracowałoby na 80–87 % (ZB §8.1) |
| K1 = przekaźnik PCB T90 zamiast przekaźnika z podstawką | wlutowany, tańszy (3–6 zł), styki 30 A; podstawka i fastony odpadają |
| D5 = SMCJ20CA (SMD) | Vc poniżej 36 V wejścia XY-SK120 (ZB §5.8) |
| F8 = 10 A | przetwornica 200 W, M910q do 65 W bez limitu RAPL |
| Odgałęzienia F8–F11 na płytce B | zastępują listwę bezpiecznikową (40–70 zł) dla tych obwodów; F1, F7, F12, FC1/FC2, FK i **FB1…FB7** zostają inline przy źródłach |
| Ścieżki AKU / CHGIN wzmocnione drutem 2,5 mm² | do 13 A przez płytkę A |

---

## 4. Co celowo pominięto (anty-overkill)

| Element | Dlaczego go nie ma |
|---------|--------------------|
| **Dioda blokująca + radiator** | XY-SK120 to buck-boost (§3) |
| **K2 + dioda gasząca + zworka** | XH-M603 pracuje w torze, nie jako pilot (§3) |
| **XH-M603, FC1/FC2, F12 na płytce** | prądy od strony banku — oprawki inline przy banku (§1) |
| **Drugi TVS** | jeden na wejściu wystarcza; za bankiem szyna jest buforowana samym bankiem |
| **Kondensator na szynie za LVD** | bank 35,7 Ah o rezystancji ok. 5,75 mΩ (ZB §4.4) to kondensator, jakiego nie kupisz |
| **470 µF / NTC na wyjściu step-upu** | tylko przy „czkawce” (ZB §3.2b) — wtedy w linii, poza płytką |
| **Kompensacja temperaturowa ładowania** | XY-SK120 nie ma wejścia NTC (w dostępnych materiałach) — CV przestawiasz sezonowo (ZB §5.5) |
| **REM wzmacniacza na płytce** | wzmacniacz ma własną gałąź z akumulatora rozruchowego; REM bierz z linii zapłonu |
| **Woltomierz z bocznikiem 50 A** | dzielnik R5/R6 + ADC sensor-huba pokazuje napięcie banku w BCM |
| **Metalizacja otworów, druga warstwa, soldermaska** | jednostronna, THT (poza D5), ścieżki ≥ 2 mm, prześwity ≥ 0,7 mm — projekt od początku pod trawienie w domu |

---

## 5. Lista zakupowa płytek

Elementy **wlutowywane** (moduły kupujesz wg
[`LISTA_ZAKUPOWA.md`](LISTA_ZAKUPOWA.md)):

| # | Element | Ilość | Cena (PLN) |
|---|---------|-------|-----------|
| 1 | Laminat FR4 jednostronny 100 × 160 mm (starczy na obie płytki) albo 2 × 100 × 75 | 1–2 | 8–16 |
| 2 | Przekaźnik **SLA-12VDC-SL-A** (T90, 30 A, PCB) | 1 | 3–6 |
| 3 | **SMCJ20CA** (TVS dwukierunkowy, SMC) | 1 | 2–5 |
| 4 | **1N4007** | 1 | 0,5 |
| 5 | **470 µF / 35 V low-ESR 105 °C** (Φ10, raster 5) | 1 | 3–6 |
| 6 | Rezystory 1 %: **100 kΩ, 27 kΩ** | 2 | 1–2 |
| 7 | Kondensator **100 nF** | 1 | 0,5 |
| 8 | Złączki **KF7.62-2P** (X1, X2, X8, X9) | 4 | 6–12 |
| 9 | Złączki **KF301-2P** (X6, X10–X12, J1) | 5 | 5–10 |
| 10 | Oprawki bezpiecznika **ATO PCB pionowe 2-pin** (albo pary klipsów) | 4 | 8–16 |
| 11 | Wkładki ATO: 10 A, 5 A, 3 A, 2 A + zapas | kpl. | 6–10 |
| 12 | Śruba M4 + nakrętka + oczko 6 mm² (masa płytki A) | 1 | 2–4 |
| 13 | Słupki/tulejki nylonowe M3 | 7 | 5–10 |
| 14 | Drut miedziany 2,5 mm² do wzmocnienia ścieżek | ~0,5 m | 2–4 |
| 15 | Środek do trawienia (B327 / FeCl₃), papier kredowy, aceton | kpl. | 15–30 |
| | **Razem płytki** | | **~67–132** |

Przy budowie na płytkach **wykreśl** z [`LISTA_ZAKUPOWA.md`](LISTA_ZAKUPOWA.md)
przekaźnik K1 z podstawką (poz. 4) i listwę bezpiecznikową (poz. 5).
Wszystko inne — ładowarki, XH-M603, przewody, F1, F7, F12, FC1/FC2, FK
i FB1…FB7 — kupujesz według tamtej listy.

---

## 6. Trawienie krok po kroku

Cały proces jest nadrukowany na
[`pcb_power_etch.svg`](../schematics/pcb_power_etch.svg). Najważniejsze:

1. **Drukuj 1:1 (100 %, bez „dopasuj do strony")** i **zmierz linijkę
   kontrolną** — 50 mm ± 0,5. Bez tego rozstawy 7,62/9,2 mm nie trafią.
2. Orientacja jest już właściwa dla termotransferu (widok od strony
   elementów, toner do miedzi) — **niczego nie odbijaj lustrzanie**.
   Kontrola po wytrawieniu: napis „BCM-A"/„BCM-B" czyta się poprawnie,
   patrząc na miedź.
3. Wiercenie wg tabeli na arkuszu (1,0 / 1,2 / 1,3 / 1,5 / 2,0 / 2,4 /
   3,2 / 4,5 mm). Zaczynaj 1,0 i rozwiercaj — pady bez metalizacji lubią
   uciekać spod większych wierteł. Pady D5 (SMD) **nie** są wiercone.
4. **Ścieżki mocy pocynuj grubo i przylutuj wzdłuż nich drut 2,5 mm²**
   (AKU i CHGIN na płytce A — do 13 A; BUS i gałąź F8 na płytce B). Sama
   miedź 35 µm nie jest do tego prądu.
5. Po wytrawieniu: omomierz między sąsiednimi sieciami (zwarcia po
   transferze) i ciągłość każdej ścieżki.

Otwory montażowe są **odizolowane od miedzi** — montuj na słupkach
nylonowych, żeby nie zrobić drugiej drogi masy przez karoserię (masa
wyłącznie: płytka A śrubą M4 do punktu masy, płytka B przez X8.2).

---

## 7. Montaż i budowa etapami

Kolejność pod budowę „sukcesywnie", każdy etap kończy się działającym
układem:

| Etap | Co robisz | Co działa po etapie |
|------|-----------|---------------------|
| **1** | Trawisz i uzbrajasz **płytkę B**. XH-M609 VOUT+ → X8, step-up → X9, LM2596 → X10, MP1584 → X11 (bezpieczniki F8–F10 przenoszą się z oprawek inline do płytki) | cała dystrybucja na płytce |
| **2** | Podłączasz J1 → ADC sensor-huba (ZB §13.4: `BATT:` w sketchu, progi w `battery.py`) | BCM widzi napięcie banku |
| **3** | Trawisz i uzbrajasz **płytkę A**. Na stole ustawiasz i sprawdzasz **obie** XY-SK120 i **oba** XH-M603 (ZB §11 Etap 1, z testem §6.4 pkt 6). Podłączasz K1 pod zapłon / D+ (przez FK 1 A), ładowarki pod X2.1 / X2.2, gałęzie z FC1/FC2, przewód przez F12 do bloku L+ | ładowanie z warstwą nadnapięciową |

> ⚠ **Ładowarek nie podłączaj do banku w aucie bez XH-M603.** To jedyna
> warstwa, która łapie przebitą ładowarkę (ZB §6.1) — zworka „na chwilę”
> zostaje zwykle na lata. Jeśli XH-M603 jeszcze nie ma, pomiń etap 3:
> płytka B i bank pracują bez ładowania z alternatora, a bank doładowujesz
> ładowarką sieciową AGM.

Etapy 1–2 nie dotykają toru ładowania, etap 3 nie dotyka dystrybucji —
w każdej chwili masz jeżdżące auto.

---

## 8. Kontrola przed zabudową

```
Płytka A (zasilacz laboratoryjny, bez banku i bez auta)
[ ] zwarcia: omomierz między AKU / CHGIN / ACC / GND
[ ] 12 V na X6.1 → K1 klika, napięcie z X1.1 pojawia się na X2.1 i X2.2
[ ] spadek X1.1 → X2.1 przy 6 A: dziesiątki mV, styk i ścieżka nie grzeją się
[ ] TVS: OL w obu kierunkach w trybie testu diody (dwukierunkowa — ZB §5.8)
[ ] pady D5 przylutowane od strony miedzi, bez mostka cyny do sąsiednich sieci

Moduły obok płytki A
[ ] XY-SK120 × 2: CV 14,40 V (±0,02 V), CC 5,0 A, OVP 15,0 V, wyjście ON
[ ] XH-M603 × 2: na zasilaczu 15,30 V rozwiera, 14,00 V zwiera (3 próby,
    ±0,05 V); 12,6 V tylko na OUT → ciemny, rozwarty, < 1 mA (ZB §6.4)

Płytka B
[ ] zwarcia między BUS / F8O–F11O / SIG / GND
[ ] V_BANK: przy 12,60 V na X8.1 → 2,68 V na J1.1 (dzielnik 27/127)
[ ] każda gałąź: napięcie pojawia się dopiero po włożeniu wkładki

Przetwornica step-up 20 V — pełny test ZB §3.4
[ ] bez obciążenia 19,9–20,5 V
[ ] 30 min ~60 W przy wejściu 12,6 V ORAZ 11,0 V: wyjście ≥ 19,8 V,
    na wtyku M910q ≥ 19,5 V, obudowa < 60 °C
```

Dalej obowiązuje procedura pierwszego uruchomienia ZB §11 (etapy 2–7).

---

## Powiązane dokumenty

| Dokument | Zakres |
|----------|--------|
| [`ZASILANIE_BUFOROWANE.md`](ZASILANIE_BUFOROWANE.md) | architektura, nastawy, budżet energetyczny |
| [`SCHEMATY_POLACZEN.md`](SCHEMATY_POLACZEN.md) | numery przewodów §10 — zaciski płytek odwołują się do nich |
| [`WDROZENIE_TESTOWE.md`](WDROZENIE_TESTOWE.md) | wariant testowy, który te płytki porządkują |
| [`LISTA_ZAKUPOWA.md`](LISTA_ZAKUPOWA.md) | pozycje wspólne (moduły, przewody, bezpieczniki inline) |
