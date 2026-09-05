# PCB zasilania buforowanego — dwie płytki do samodzielnego wytrawienia

Zasilanie buforowane z [`ZASILANIE_BUFOROWANE.md`](ZASILANIE_BUFOROWANE.md)
przeniesione z „pająka" na dwie jednostronne płytki drukowane, które trawisz
w domu. Elementy dyskretne (przekaźnik, dioda blokująca, TVS, kondensator,
dzielnik pomiarowy, bezpieczniki odgałęzień) są wlutowane; moduły kupne
(ładowarka CC-CV, XH-M603, XH-M609, przetwornica 19,5 V, bucki 5 V)
podłączasz do zacisków śrubowych — więc budujesz i wymieniasz je **etapami**,
bez lutownicy przy każdej zmianie.

| Plik | Co zawiera |
|------|-----------|
| [`../schematics/pcb_power_schematic.svg`](../schematics/pcb_power_schematic.svg) | schemat ideowy obu płytek + otoczenie (moduły, bank, LVD), tabela zacisków |
| [`../schematics/pcb_power_layout.svg`](../schematics/pcb_power_layout.svg) | rozmieszczenie elementów 1:1, opisy zacisków, BOM, wiercenie |
| [`../schematics/pcb_power_etch.svg`](../schematics/pcb_power_etch.svg) | **mozaika miedzi 1:1 do wydruku** + widok kontrolny + proces trawienia |
| [`../schematics/gen_pcb_power.py`](../schematics/gen_pcb_power.py) | generator trzech powyższych — po zmianie projektu popraw i wygeneruj ponownie |
| [`../schematics/png/pcb_power_schematic.png`](../schematics/png/pcb_power_schematic.png) | ten sam schemat ideowy w PNG — do podglądu na telefonie i wklejek; render [`../schematics/render_png.py`](../schematics/render_png.py) |

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
2. [Przetwornica 12 → 19,5 V z AliExpress](#2-przetwornica-12--195-v-z-aliexpress)
3. [Zmiany wobec dotychczasowej dokumentacji](#3-zmiany-wobec-dotychczasowej-dokumentacji)
4. [Co celowo pominięto (anty-overkill)](#4-co-celowo-pominięto-anty-overkill)
5. [Lista zakupowa płytek](#5-lista-zakupowa-płytek)
6. [Trawienie krok po kroku](#6-trawienie-krok-po-kroku)
7. [Montaż i budowa etapami](#7-montaż-i-budowa-etapami)
8. [Kontrola przed zabudową](#8-kontrola-przed-zabudową)

---

## 1. Co jest na której płytce

### Płytka A — tor ładowania (100 × 75 mm)

Realizuje przewody **2–7** z §10.1
[`SCHEMATY_POLACZEN.md`](SCHEMATY_POLACZEN.md) jako ścieżki:

```
X1 (+AKU za F1 15 A) → D5 (TVS) + C1 → K1 (styk) → D1 (MBR2545CT)
   → X2 (do ładowarki M1) …ładowarka… X3 (z ładowarki)
   → X5.1 (do XH-M603) …moduł… X5.3 → X5.4 (szyna „+" banku)
```

| Zacisk | Podłączenie | Przewód (§10.1) |
|--------|-------------|-----------------|
| X1.1 / X1.2 | „+" z F1 15 A · masa (opcjonalna, główna masa idzie śrubą M4) | 2 |
| X2.1 / X2.2 | M1 IN+ / IN− — wejście ładowarki CC-CV | 6 |
| X3.1 / X3.2 | M1 OUT+ / OUT− — wyjście ładowarki | B |
| X5.1 / X5.2 | XH-M603 DC-IN+ / DC-IN− | 7a″ / 7b |
| X5.3 / X5.4 | XH-M603 OUT+ · **szyna „+" banku** (**4 mm²** — spadek siedzi w pętli CV, §8.2 ZASILANIE) | 7d″ / 7 |
| X6.1 / X6.2 | zapłon / ACC (cewka K1) · przelot ACC dalej (PC817, REM) | 4 |
| GND M4 | oczko 6 mm² → punkt gwiazdowy masy | — |

K1 to **przekaźnik PCB T90 (SLA-12VDC-SL-A, 30 A)** wlutowany w płytkę —
zastępuje przekaźnik Bosch z podstawką. Datasheet Songle podaje **okrągłe**
otwory (styki Φ2,0, cewka Φ1,0) — bez slotów, zwykłe wiertła. Pady COM-A
i NC są wiercone, ale zostają wolne, więc pasują warianty 4-, 5- i 6-pinowe.

### Płytka B — dystrybucja szyny buforowanej (100 × 60 mm)

Rozdziela szynę za LVD (XH-M609) i wyłącznikiem S1 — przewody **11/13/25**
— i zastępuje osobną listwę bezpiecznikową dla odgałęzień:

| Zacisk | Gałąź | Bezpiecznik |
|--------|-------|-------------|
| X8.1 / X8.2 | wejście z S1 · masa → punkt gwiazdowy | — (F7 15 A przed LVD) |
| X9 | przetwornica 19,5 V IN+ | **F8**: 7,5 A (XL6019) / **10 A** (nowa przetwornica) |
| X10 | LM2596 IN+ (podświetlenie panelu) | **F9**: 2 A |
| X11 | MP1584 IN+ (Arduino Nano) | **F10**: 3 A |
| X12 | AUX 12 V (moduł przekaźników, wentylator) | **F11**: 5 A |
| J1.1 / J1.2 | V_BANK → ADC sensor-huba · GND sygnałowa | — |

Bezpieczniki to zwykłe **wkładki nożowe ATO** w pionowych oprawkach PCB
(otwory Φ2,0 w rozstawie 9,2 mm — standard potwierdzony w bibliotece KiCad;
czop centrujący Φ2,4). Dzielnik **R5/R6 = 100 kΩ/27 kΩ 1 % + C7 100 nF**
realizuje pomiar napięcia banku z §13.4
[`ZASILANIE_BUFOROWANE.md`](ZASILANIE_BUFOROWANE.md) (15 V → 3,2 V na ADC).

**Minusy modułów** (M1, M4–M6, XH-M609) idą jak dotąd do punktu gwiazdowego
— przez płytki nie płynie żaden prąd powrotny odbiorników (§10.6).

---

## 2. Przetwornica 12 → 19,5 V z AliExpress

Posiadany XL6019 daje realnie ~45 W (limit klucza 5 A) i wymaga limitowania
poboru CPU przez RAPL (§3.2, §3.5a ZASILANIE_BUFOROWANE). Za **≤ 100 zł**
da się to zamknąć raz na zawsze. Zweryfikowane kandydatury (ceny AliExpress
z dostawą do PL, 2026):

| Moduł | Cena | 65 W ciągle przy 11 V? | Uwagi |
|-------|------|------------------------|-------|
| **„1500 W 30 A" boost CC-CV** (wej. 10–60 V, wyj. 12–97 V) | **60–95 zł** | **tak, z dużym zapasem** — potrzebne ~6,6 A wejścia z realnych 15–20 A ciągłych | **zalecany**; wieloobrotowy potencjometr, prawdziwe CC-CV, wentylator startuje dopiero ~60 °C (przy 65 W nie wystartuje) |
| Hermetyczna IP68 12 V → **19,5 V lub 20 V** (wariant min. 10 A) | 45–90 zł | tak (3,4 A z uczciwych ~6–8 A) | zero regulacji, szczelna, pasywna — dobra do zabudowy pod deską; **koniecznie wariant 19,5/20 V, nie 19,0 V** |
| „600 W 10 A" boost | 20–45 zł | na styk (66 % limitu klucza) | opcja oszczędnościowa; słabe ścieżki — w aucie obowiązkowy wentylator 40 mm |
| BST900 „900 W 15 A" z wyświetlaczem | 95–150 zł | tak | zwykle ponad budżet, najniższa sprawność (~85 %) |
| LTC1871 „100 W" | 12–25 zł | **nie** — 100 % możliwości dławika ciągle | odpada |

> **Pułapka nazewnicza: SZBK07 to NIE jest boost.** SZBK07 (LM5116) to
> przetwornica **obniżająca** 300 W — wcześniejsze notatki wymieniały ją
> błędnie wśród boostów. Szukaj frazy **„boost converter 1500W 30A
> 10-60V"** — duża płytka z radiatorem i wentylatorem, ~475 g.

**Rekomendacja: „1500 W 30 A" boost CC-CV, ok. 65–85 zł** (jest też na
Allegro za 56–83 zł). Nastawy:

| Parametr | Wartość | Dlaczego |
|----------|---------|----------|
| Napięcie wyjściowe | **19,5–20,0 V** pod obciążeniem | oryginalny zasilacz M910q to 20 V; 20,0 V siedzi w środku okna 19–21 V — przy module CC-CV śmiało ustaw 20,0 V |
| Limit prądu CC | **~4 A** wyjścia | ochrona przy piku rozruchowym M910q — koniec z trybem „czkawki" |
| Potencjometry | zabezpiecz lakierem | wibracje w aucie rozstrajają nastawy |
| **F8 na płytce B** | wkładka **10 A** | pełne 65 W przy 11 V to ~6,6 A wejścia; 7,5 A pracowałaby na krawędzi |
| Limit RAPL (§3.5a) | **zbędny** | moduł ma zapas na pełne 65 W; przy XL6019 limit zostaje |

Test na biurku przed zabudową pozostaje obowiązkowy — procedura §3.4
ZASILANIE_BUFOROWANE bez zmian (stress-ng, pomiar przy 11,0 V wejścia).

---

## 3. Zmiany wobec dotychczasowej dokumentacji

### XH-M603 pracuje w torze ładowania, nie jako „pilot" przekaźnika K2

§6.3 ZASILANIE_BUFOROWANE zalecał: moduł steruje cewką osobnego przekaźnika
mocy K2. **Ta konfiguracja jest wadliwa dla XH-M603** — zweryfikowane
działanie modułu:

- przekaźnik siedzi **wewnętrznie** w torze DC-IN+ → OUT+ (nie ma wolnego
  styku COM/NO na złączce),
- napięcie mierzy **po stronie OUT** (tam, gdzie ma wisieć akumulator).

Gdyby OUT+ sterował cewką K2, po zadziałaniu (rozwarciu) napięcie na OUT
spada do zera przez rezystancję cewki → moduł widzi „pusty akumulator" →
natychmiast zwiera z powrotem → **oscylacja kilka razy na sekundę, styki
umierają**. W torze ładowania (do czego moduł zaprojektowano) wszystko się
zgadza: mierzy wprost napięcie banku, a zasilanie ma z toru ładowania — na
postoju pobiera **zero**. Progi bez zmian: rozwarcie 15,30 V, powrót 14,00 V.

**Prąd przez ten moduł przy banku siedmiu pakietów.** Obowiązująca nastawa to
**CC 8,0 A** (§4.4 i §6.3 ZASILANIE_BUFOROWANE) — 80 % realnej obciążalności
płytki (~10 A) i dokładnie deklarowana granica spec „≤ 8 A". To jest **wąskie
gardło całego toru ładowania**: sufit katalogowy siedmiu HR1221W wynosi
14,7 A i przestał być wiążący, więc powyżej 8,0 A ta konstrukcja (XH-M603
wprost w torze) traci ważność i trzeba wrócić do układu „pilot + K2"
z modułem mającym wolny styk COM/NO.

> **Zmierz temperaturę zacisków X5 przy 8 A przez 30 min** przed zabudową.
> Obciążalność ~10 A jest oszacowaniem, nie wartością katalogową, a od niej
> zależy nastawa CC całego układu.

Konsekwencje: **K2, D7 i drugi przekaźnik Bosch wypadają z projektu**,
a przewody 7a–7e z §10.1 zastępują 4 krótkie odcinki do zacisków X5
(patrz tabela w §1). Zachowanie po zadziałaniu jest inne niż „zatrzask"
z §6.3 — moduł cykluje między 15,30 a 14,00 V, co przy pojemności banku
oznacza cykle minutowe i pełną ochronę do końca jazdy.

### Pozostałe

| Zmiana | Powód |
|--------|-------|
| K1 = przekaźnik PCB T90 zamiast Bosch + podstawka | wlutowany, tańszy (3–6 zł), styki 30 A; podstawka i fastony odpadają |
| F8 = 10 A przy nowej przetwornicy | §2 wyżej; z XL6019 zostaje 7,5 A |
| Wyjście przetwornicy: 19,5–20,0 V | 20 V = napięcie oryginalnego zasilacza; środek okna 19–21 V |
| Odgałęzienia F8–F11 na płytce B | zastępują listwę bezpiecznikową (40–70 zł) dla tych obwodów; F1, F7 i bezpieczniki pakietów **FB1…FB7** zostają inline przy źródłach |
| SZBK07 wykreślony z listy ładowarek | to buck, nie boost — patrz §2 |

---

## 4. Co celowo pominięto (anty-overkill)

| Element | Dlaczego go nie ma |
|---------|--------------------|
| **K2 + D7 + JP1** | pilot z K2 odpada (§3); jeden przekaźnik i jedna dioda gasząca mniej |
| **X4 (osobny zacisk banku)** | bank wychodzi z X5.4 — ta sama sieć co OUT+ modułu M2 |
| **Drugi TVS** | jeden na wejściu wystarcza; za bankiem szyna jest buforowana samym bankiem |
| **Kondensator na szynie za LVD** | bank 35,7 Ah o rezystancji 5,29 mΩ to kondensator, jakiego nie kupisz |
| **C6 470 µF na wyjściu przetwornicy 19,5 V** | dotyczył „czkawki" XL6019; moduł „1500 W 30 A" ma własne kondensatory i limit CC |
| **Termistor NTC rozruchowy (§3.2b)** | jw. — potrzebny tylko, jeśli zostajesz przy XL6019 i faktycznie wystąpi czkawka; wtedy inline, poza płytką |
| **Kompensacja temperaturowa ładowania** | wariant B świadomie bez niej (§5.3c ZASILANIE_BUFOROWANE — absorpcja tylko podczas jazdy) |
| **REM wzmacniacza na płytce** | wysokoomowe wejście REM bierz z przelotu ACC (X6.2) — zero dodatkowych ścieżek mocy |
| **Woltomierz z bocznikiem 50 A** | dzielnik R5/R6 + ADC sensor-huba pokazuje napięcie banku w BCM; bocznik 50 A w torach ≤ 10 A nie ma czego mierzyć |
| **Metalizacja otworów, druga warstwa, soldermaska** | jednostronna, THT, ścieżki ≥ 2 mm, prześwity ≥ 0,7 mm — projekt od początku pod trawienie w domu |

---

## 5. Lista zakupowa płytek

Elementy **wlutowywane** (moduły M1–M6 kupujesz wg dotychczasowych list):

| # | Element | Ilość | Cena (PLN) |
|---|---------|-------|-----------|
| 1 | Laminat FR4 jednostronny 100 × 160 mm (starczy na obie płytki) albo 2 × 100 × 75 | 1–2 | 8–16 |
| 2 | Przekaźnik **SLA-12VDC-SL-A** (T90, 30 A, PCB) | 1 | 3–6 |
| 3 | **MBR2545CT** (TO-220) + radiator ~15 × 14 mm ≥ 6 K/W + podkładka mikowa | 1 | 12–25 |
| 4 | **1.5KE33CA** (TVS dwukierunkowy) | 1 | 2–5 |
| 5 | **1N4007** | 1 | 0,5 |
| 6 | **470 µF / 35 V low-ESR 105 °C** (Φ10, raster 5) | 1 | 3–6 |
| 7 | Rezystory 1 %: **100 kΩ, 27 kΩ** | 2 | 1–2 |
| 8 | Kondensator **100 nF** | 1 | 0,5 |
| 9 | Złączki **KF7.62-2P** (X1, X2, X3, X8, X9) | 5 | 8–15 |
| 10 | Złączki **KF301**: 4P × 1 (X5), 2P × 5 (X6, X10–X12, J1) | 6 | 6–12 |
| 11 | Oprawki bezpiecznika **ATO PCB pionowe 2-pin** (albo pary klipsów) | 4 | 8–16 |
| 12 | Wkładki ATO: 10 A (lub 7,5 A), 5 A, 3 A, 2 A + zapas | kpl. | 6–10 |
| 13 | Śruba M4 + nakrętka + oczko 6 mm² (masa płytki A) | 1 | 2–4 |
| 14 | Słupki/tulejki nylonowe M3 | 7 | 5–10 |
| 15 | Środek do trawienia (B327 / FeCl₃), papier kredowy, aceton | kpl. | 15–30 |
| | **Razem płytki** | | **~80–160** |
| 16 | **Przetwornica „1500 W 30 A" boost CC-CV** (§2) | 1 | **60–95** |

Do tego pozycje niezmienione z [`LISTA_ZAKUPOWA.md`](LISTA_ZAKUPOWA.md)
(ładowarka CC-CV M1, XH-M603, przewody, bezpieczniki inline F1, F7 i FB1…FB7).
**Wykreśl z tamtej listy:** oba przekaźniki Bosch z podstawkami (poz. 1
i 5a), drugi kondensator 470 µF (poz. 7 — wystarczy jeden).

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
   uciekać spod większych wierteł.
4. **Ścieżki mocy pocynuj grubo** albo przylutuj wzdłuż nich drut
   1,5 mm² (AKU, KL87, CHGIN/CHGOUT, BANK na płytce A; BUS i gałąź F8 na
   płytce B). 35 µm miedzi + gruba cyna spokojnie przenosi projektowe
   ≤ 10 A.
5. Po wytrawieniu: omomierz między sąsiednimi sieciami (zwarcia po
   transferze) i ciągłość każdej ścieżki.

Otwory montażowe są **odizolowane od miedzi** — montuj na słupkach
nylonowych, żeby nie zrobić drugiej drogi masy przez karoserię (masa
wyłącznie: płytka A śrubą M4 do punktu gwiazdowego, płytka B przez X8.2).

---

## 7. Montaż i budowa etapami

Kolejność pod budowę „sukcesywnie", każdy etap kończy się działającym
układem:

| Etap | Co robisz | Co działa po etapie |
|------|-----------|---------------------|
| **1** | Trawisz i uzbrajasz **płytkę B**. Przepinasz z pająka: S1 → X8, XL6019 → X9, LM2596 → X10, MP1584 → X11 (bezpieczniki F8–F10 przenoszą się z oprawek inline do płytki) | cała dystrybucja na płytce; koniec ze skrętkami przy przetwornicach |
| **2** | Podłączasz J1 → ADC sensor-huba (+ zmiany z §13.4 ZASILANIE_BUFOROWANE: `BATT:` w sketchu, progi w `battery.py`) | BCM widzi napięcie banku |
| **3** | Trawisz i uzbrajasz **płytkę A** (bez M2!): X5.1–X5.3 zwarte drutem w zaciskach. Podłączasz K1 pod ACC, ładowarkę M1 pod X2/X3, bank pod X5.4 | ładowanie wariantem B działa (bez warstwy nadnapięciowej) |
| **4** | Dokupujesz **XH-M603**, ustawiasz progi na zasilaczu (§8), wpinasz w X5, wyjmujesz zworkę | pełna ochrona przed przeładowaniem |
| **5** | Wymieniasz XL6019 na przetwornicę **„1500 W 30 A"** (19,5–20,0 V / CC 4 A), F8 → 10 A, kasujesz limit RAPL | pełne 65 W dla M910q |

> ⚠ **Etap 5 koliduje z bankiem siedmiu pakietów — nie planuj ich niezależnie.**
> Skasowanie limitu RAPL podnosi obciążenie szyny podczas jazdy z 3,5 A do
> ok. 5,1 A (a szczytowe z 7,5 do 9,7 A). Ponieważ moduł CC-CV limituje prąd
> **wyjściowy** (obciążenie plus ładowanie), przy CC 8,0 A do banku zostanie
> wtedy 2,9 A netto zamiast 4,5 A, a ładowanie od progu LVD wydłuży się
> z 5,95 do **9,2 h fazy CC**. Jeżeli oba kroki mają wejść, nastawa CC musi
> pójść na 10 A — a to wymaga wymiany modułu nadnapięciowego (na taki
> z wolnym stykiem COM/NO), F1 → 20 A, przewodu wejściowego 6 mm²
> i mocniejszego radiatora diody. Rachunek: §6.3 i §9.4
> [`ZASILANIE_BUFOROWANE.md`](ZASILANIE_BUFOROWANE.md).

Etapy 1–2 nie dotykają toru ładowania, 3–5 nie dotykają dystrybucji —
w każdej chwili masz jeżdżące auto.

---

## 8. Kontrola przed zabudową

```
Płytka A (zasilacz laboratoryjny, bez banku i bez auta)
[ ] zwarcia: omomierz między AKU / KL87 / CHGIN / CHGOUT / BANK / ACC / GND
[ ] 12 V na X6.1 → K1 klika, AKU pojawia się na anodach D1
[ ] spadek na D1 przy obciążeniu 3–6 A: 0,4–0,55 V (obie połówki grzeją równo)
[ ] radiator D1 odizolowany od masy (blaszka = katoda!)
[ ] XH-M603: na zasilaczu 15,30 V rozwiera, 14,00 V zwiera (3 próby, ±0,05 V)
[ ] TVS: OL w obu kierunkach w trybie testu diody (dwukierunkowa — §5.4)

Płytka B
[ ] zwarcia między BUS / F8O–F11O / SIG / GND
[ ] V_BANK: przy 12,60 V na X8.1 → 2,68 V na J1.1 (dzielnik 27/127)
[ ] każda gałąź: napięcie pojawia się dopiero po włożeniu wkładki

Przetwornica 19,5–20 V — pełny test §3.4 ZASILANIE_BUFOROWANE
[ ] 10 min stress-ng przy wejściu 12,6 V ORAZ 11,0 V, napięcie ≥ 19,0 V
[ ] temperatura dławika/klucza < 85 °C
```

Dalej obowiązuje procedura pierwszego uruchomienia
[`ZASILANIE_BUFOROWANE.md`](ZASILANIE_BUFOROWANE.md) §11 (etapy 2–7).

---

## Powiązane dokumenty

| Dokument | Zakres |
|----------|--------|
| [`ZASILANIE_BUFOROWANE.md`](ZASILANIE_BUFOROWANE.md) | architektura, nastawy, budżet energetyczny |
| [`SCHEMATY_POLACZEN.md`](SCHEMATY_POLACZEN.md) | numery przewodów §10 — zaciski płytek odwołują się do nich |
| [`WDROZENIE_TESTOWE.md`](WDROZENIE_TESTOWE.md) | wariant testowy, który te płytki porządkują |
| [`LISTA_ZAKUPOWA.md`](LISTA_ZAKUPOWA.md) | pozycje wspólne (moduły, przewody, bezpieczniki inline) |
