# Lista zakupowa — wszystko w jednym miejscu

Jedna lista do wariantu z [`WDROZENIE_TESTOWE.md`](WDROZENIE_TESTOWE.md):
instalacja jeżdżąca z pełnym torem zasilania, Android Auto wireless, dźwiękiem
przez mini-jack i przyciskami SWC. Tor zasilania jest ten sam co w wersji
docelowej — [`ZASILANIE_BUFOROWANE.md`](ZASILANIE_BUFOROWANE.md) (dalej: ZB);
różnice są tylko po stronie odbiorników.

> **Auto testowe dziś jeździ bez bufora.** Ta lista to zakupy na tor
> buforowany, który ma to zmienić — do czasu montażu każde zgaszenie silnika
> odcina M910q (WDROZENIE_TESTOWE.md §3).

Ceny orientacyjne, rynek PL (ogłoszenia, zmienne). **Razem: ~805–1405 PLN**
bez pozycji „do wyceny” (wkładki MIDI/ANL, bloki zbiorcze, stal na kosze).

> **Moduły bezmarkowe.** Przetwornica step-up, XY-SK120, XH-M603 i XH-M609
> to rodziny modułów sprzedawane pod wieloma nazwami, bez kart
> katalogowych. Parametry w tabeli pochodzą z opisów sprzedawców — każdą
> sztukę sprawdzasz po zakupie (ZB §3.4, §5.2, §6.4, §7.3, §11 Etap 1).

---

## Masz już — nie kupuj

| Element | Rola |
|---------|------|
| Lenovo ThinkCentre M910q Tiny + oryginalny zasilacz | komputer; z zasilacza bierzesz kabel z wtykiem (ZB §3.3) |
| Ekran 7" 1024×600, HDMI + dotyk USB | wyświetlacz na czas testów |
| Karta WiFi MediaTek MT7921 | P2P-GO dla Android Auto wireless |
| Pody SWC + dekoder rezystorowy | przyciski na kierownicy |
| Modem LTE Huawei E3372 (HiLink) | internet |
| CSB HR1221W F2 × 8 (12 V / 5,1 Ah AGM) | bank buforowy — **użyj 7 (35,7 Ah)**, jeden zostaje w zapasie |
| **XH-M609** | LVD, ochrona banku (11,00 / 12,60 V) |
| **Arduino Pro Micro** (ATmega32U4) | SWC, enkoder, przyciski — USB HID |
| **Arduino Nano V3** (ATmega328PB) | zapłon + sterowanie zasilaniem M910q |
| **LM2596** | 12 → 5 V, podświetlenie panelu |
| **MP1584** | 12 → 5 V, zasilanie Nano niezależne od USB |
| XL6019 | **zastąpiony** — realnie ok. 45 W; zostaje na półce, nie zasilaj nim M910q (ZB §3) |

> **Nano V3 z 328PB wymaga uwagi przy wgrywaniu.** To nie jest 328P — ma inną
> sygnaturę i rdzeń `arduino:avr` jej nie zna. Objaw: avrdude przerywa
> z „Expected signature for ATmega328P". Rozwiązania są w
> `arduino/sensor_hub/sketch.yaml`. Sam firmware kompiluje się na obu.

---

## Do kupienia

> **Budujesz na płytkach drukowanych?** [`PCB_ZASILANIE.md`](PCB_ZASILANIE.md)
> ma osobną listę elementów wlutowywanych i wtedy **wykreśl stąd** poz. 4
> (przekaźnik z podstawką — zastępuje go T90 na płytce A) oraz listwę
> z poz. 5 (odgałęzienia F8–F11 są na płytce B).

### Moduły i przekaźnik

| # | Element | Specyfikacja | Po co | Cena (PLN) |
|---|---------|--------------|-------|-----------|
| 1 | **Przetwornica step-up** | zalewana IP67/IP68, **12 V → 20 V, 10 A (200 W)**, wejście ~9–18 V (potrzebujesz pracy od 11 V); po zakupie: bez obciążenia 19,9–20,5 V, test ~60 W i przy 11,0 V (ZB §3.4) | zasilanie M910q — stałe, bez limitu RAPL | 60–130 |
| 2 | **Ładowarka CC-CV × 2** | **XY-SK120** (albo XY-SK120X), buck-boost, wejście 6–36 V, do 6 A / 120 W (wg opisu sprzedawcy — sprawdź w instrukcji); nastawa CV 14,40 V, CC 5,0 A każda | dwie równolegle: ok. 10 A, netto do banku ok. 5 A przy obciążeniu 4–6 A; jedna by nie nadążyła (ZB §5.3) | 120–180 |
| 3 | **Rozłącznik nadnapięciowy × 2** | **XH-M603** (albo XH-M604) — ta sama rodzina co XH-M609 | blokada przeładowania 15,30 / 14,00 V, **po jednym na ładowarkę** — płytka realnie ok. 8 A (ZB §6.3) | 80–160 |
| 4 | **Przekaźnik ładowania K1** | 12 V / 30 A SPDT + podstawka | odcina tor ładowania przy zgaszonym silniku | 15–25 |
| 5 | **Dystrybucja za LVD** | listwa bezpiecznikowa ATO 6–8 obwodów z pokrywą albo płytka B ([`PCB_ZASILANIE.md`](PCB_ZASILANIE.md)) | odgałęzienia F8–F10 | 40–70 |
| 6 | **Moduł przekaźnika 1-kanałowy 5 V** | z optoizolacją | styki równolegle do przycisku zasilania M910q | 5–12 |

### Bezpieczniki

| # | Element | Specyfikacja | Po co | Cena (PLN) |
|---|---------|--------------|-------|-----------|
| 7 | **F1 + oprawka** | **20 A**, oprawka na przewód 6 mm², montaż ≤ 30 cm od klemy „+” | jedyne połączenie toru z akumulatorem rozruchowym; ładowarki biorą 11,9–13,0 A, więc 15 A pracowałoby na 80–87 % (ZB §8.1) | 15–25 |
| 8 | **FB1…FB7, FC1, FC2, FK + oprawki inline** | ATO albo mini; oprawki na 2,5 mm² (FK na 0,75 mm²); wkładki: **FB 10 A × 7**, **FC 7,5 A × 2**, **FK 1 A × 1** | FB — na „+” każdego pakietu, 5–10 cm od zacisku; FC — przy OUT+ każdego XH-M603; FK — przy wpięciu w zapłon / D+ | 35–57 |
| 9 | **F7 i F12 + oprawki** | **20 A** (F7) i **15 A** (F12), klasa **MIDI/AMI albo ANL**, zdolność wyłączania **≥ 2,5 kA wg karty** — prąd zwarciowy banku to ok. 2,2 kA, ATO ma ok. 1 kA | F7 — blok L+ → XH-M609; F12 — przewód ładowania przy bloku L+. Jeśli 15 / 20 A w tej klasie nie da się kupić, decyzja świadoma — ZB §7.4 | do wyceny |
| 10 | **Wkładki ATO** | 10 A (F8), 2 A (F9), 3 A (F10), 5 A (wyjście step-upu), 1 A (pomiar banku), zapas FB 10 A / FC 7,5 A / FK 1 A | odgałęzienia za LVD | 10–15 |
| 10a | **Oprawki inline ATO × 2** do wkładek z poz. 10 | jedna na przewód **4 mm²** (5 A, wyjście step-upu — oprawki z poz. 8 są na 2,5 / 0,75 mm² i tej żyły nie przyjmą), jedna na **0,5 mm²** (1 A, pomiar banku przy bloku L+) | wyjście 20 V do M910q i przewód pomiarowy `FEATURE_BATT_ADC` | 10–20 |

### Elementy dyskretne

| # | Element | Specyfikacja | Po co | Cena (PLN) |
|---|---------|--------------|-------|-----------|
| 11 | **Dioda TVS × 2** | **SMCJ20CA** — „CA” = dwukierunkowa; SMCJ20A (bez „C”) to inna, jednokierunkowa dioda | wejście toru ładowania; Vc ok. 32 V wg typowych kart, poniżej 36 V XY-SK120 — potwierdź w karcie kupionej (ZB §5.8). Dawna 1.5KE33CA ogranicza dopiero przy ok. 45 V — nie kupuj | 5–10 |
| 12 | **Kondensator 470 µF / 35 V × 2** | low-ESR, 105 °C | wejście toru ładowania; drugi w zapasie albo na wyjście step-upu przy „czkawce” (ZB §3.2b) | 5–10 |
| 13 | Dioda 1N4007 × 5 | | gaszenie cewki K1 | 2–5 |
| 14 | Transoptor **PC817** × 2 | DIP-4 | wejście zapłonu + odczyt diody panelu | 2–5 |
| 15 | Rezystory 1/4 W | 2,2 kΩ × 2, 10 kΩ × 2, 1 kΩ × 2 | do transoptorów i pull-upów | 5–10 |
| 16 | Kondensator 100 nF × 2 | ceramiczny | filtr na wejściach zapłonu i diody | 2–4 |

### Przewody i złącza

Wszystkie przewody samochodowe z **czystej miedzi** (FLRY / FLRY-B wg ISO
6722 albo car-audio OFC), **nie CCA** i nie instalacyjne YDY (ZB §8.2).

| # | Element | Specyfikacja | Po co | Cena (PLN) |
|---|---------|--------------|-------|-----------|
| 17 | **Przewód 6 mm² (10 AWG)** | **OFC, nie CCA**, linka klasy 5/6, izolacja 105 °C (FLRY-B 6 mm² albo car-audio OFC 6 mm²): czerwony ~7 m + czarny ~2 m | F1 → bagażnik (~5 m, zmierz), łącznik kosz L ↔ kosz P „+” i „−” (0,4–0,6 m, obie żyły równe), odbiór L+ → F7 → LVD, masa P− → S1 → punkt masy | 90–135 |
| 18 | **Przewód 4 mm²** | FLRY: czerwony ~7,5 m + czarny ~5,5 m | 20 V do M910q (2 × ~4 m), wejście step-upu (F8), LVD → dystrybucja, ładowanie → F12 → L+ | 65–110 |
| 19 | **Przewód 2,5 mm²** | **FLRY-B** (ISO 6722), ok. 12 m razem | 14 odcinków pakiet → blok (~0,25 m, **równe ±30 mm**), gałęzie ładowarek (K1 → XY-SK120 → XH-M603 → złączenie, ≤ 1 m każda, obie równe), masy modułów | 50–80 |
| 20 | Przewód **1,5 mm²** FLRY | czerwony + czarny po 5 m | LM2596 → podświetlenie panelu (przewody 13–14) | 25–40 |
| 21 | Przewód **0,75 mm²** FLRY | kilka kolorów po 2 m + ~5 m na cewkę K1 | cewka K1 (zapłon / D+ przez FK), MP1584 → Nano | 15–25 |
| 22 | Przewód **0,5 mm²** | kilka kolorów po 2 m | sygnały: zapłon, przekaźnik, dioda panelu, pomiar banku | 10–20 |
| 23 | **Bloki zbiorcze banku × 4** | izolowana podstawa z szynką, **4 kołki M6 + pokrywa** (L+, L−, P+, P−) | gwiazda w każdym koszu zamiast odczepów na lince (ZB §4.3) | do wyceny |
| 24 | **Oczka zaciskane M6** | izolowane, na 2,5 mm² (14+) i 6 mm² (8+) | odcinki pakietów, łączniki i odbiory na kołkach bloków | 45–75 |
| 25 | **Nasuwki żeńskie 6,3 × 0,8 mm, w pełni izolowane** | na 1,5–2,5 mm², 14 szt. + zapas; tulejki, koszulki termokurczliwe z klejem | zaciski F2 pakietów — zaciskane zaciskarką zapadkową, nie kombinerkami | 30–50 |
| 26 | Peszel / oplot + przelotki gumowe | ~8 m peszla + komplet przelotek + osłona łącznika między koszami | trasa bagażnik → deska, przejścia przez blachę | 25–40 |
| 27 | **Rozłącznik masy 100 A** (S1) | kluczykowy albo pokrętło; rozłączaj wyłącznie bez obciążenia (ZB §8.4) | serwis i dłuższy postój | 40–70 |
| 28 | Kabel USB z **przeciętą żyłą VBUS** | albo przetnij czerwoną w zwykłym | Nano ma własne 5 V — dwa źródła nie mogą się bić | 0–20 |

### Kosze na bank — stal i złączki (z PDF projektu)

| # | Element | Cena (PLN) |
|---|---------|-----------|
| 29 | **Dwa kosze stalowe** wg [`mechanika/kosze_HR1221W_4+3.pdf`](mechanika/kosze_HR1221W_4+3.pdf) — BOM niżej | do wyceny |

Zestawienie z §3 PDF-u, łącznie na oba kosze (kosz L 4 szt.: klatka
373 × 83 × 98 mm; kosz P 3 szt.: 283 × 83 × 98 mm; razem z pakietami
≈ 16,8 kg — ZB §4.7):

| Poz. PDF | Materiał | Specyfikacja | Ilość |
|----------|----------|--------------|-------|
| 1 | kątownik | 25 × 25 × 3 mm, S235JR | 3 × 1,0 m (netto 2,40 m) — dolne obwody i 8 słupków |
| 2 | płaskownik | 20 × 3 mm, S235JR | 3 × 1,0 m (netto 2,41 m) — wieńce i 2 belki dociskowe |
| 3 | płaskownik | 30 × 4 mm, S235JR | 1 × 1,0 m (netto 0,64 m) — listwy kontrujące od strony kabiny |
| 4 | nakrętka do spawania | M8, stal czarna (DIN 934, bez ocynku) | 4 szt. |
| 5 | śruby belek dociskowych | M8 × 30 kl. 8.8 + podkładka sprężysta + zwykła | 4 kpl. |
| 6 | śruby kotwiące przez grodź | M8 × 25 kl. 8.8 + nakrętka samokontrująca DIN 985 | 8 kpl. |
| 7 | podkładki poszerzane | M8, DIN 9021 (Ø 24 mm) | 16 szt. |
| 8 | guma EPDM / SBR | arkusz 400 × 500 × 3 mm | 1 |
| 9 | kapturki na zaciski F1/F2 + podkład epoksydowy i lakier | — | 14 szt. + 2 spraye |

> Rysunki 3D na stronach 2 i 4 PDF-u się nie wyrenderowały — wymiary są
> w tabelach i szkicach rozkroju (str. 5–8). **Podłogi bagażnika nie
> wierć** (zbiornik paliwa); 8 otworów Ø 8,5 mm tylko poziomo przez grodź.
> Jeśli blacha grodzi ugina się przy dokręcaniu, dołóż drugą parę listew
> 30 × 4 pod dolny rząd (kolejne 0,64 m płaskownika) — ZB §4.7.

---

## Warto, ale nie na start

| Element | Po co | Cena (PLN) |
|---------|-------|-----------|
| Multimetr z pomiarem prądu DC 10 A | pomiar poboru w S3 i prądu ładowania — **bez tego nie odbierzesz instalacji** | 80–200 |
| Zaciskarka zapadkowa | zaciski robione kombinerkami to najczęstsza usterka instalacji | 60–150 |
| Woltomierz/amperomierz panelowy z bocznikiem | podgląd banku bez multimetru | 40–70 |
| Ładowarka sieciowa AGM | doładowanie w garażu przy krótkich przejazdach | 150–300 |
| Przejściówka DP → HDMI | **tylko jeśli** Twój M910q ma wyjścia DisplayPort — sprawdź (`WDROZENIE_TESTOWE.md` §5.2) | 0–25 |
| Drugi kabel USB do panelu | jeśli panel przyszedł z rozgałęzieniem na dwa wtyki | 0–20 |

---

## Czego **nie** kupować

| Element | Dlaczego |
|---------|----------|
| Moduł buck (XL4016 i podobne) jako ładowarka | obniża napięcie — z instalacji nie zrobi 14,40 V absorpcji (ZB §5.1) |
| Moduł boost CC-CV z diodą blokującą (dawny „wariant B”: MBR2545CT, radiator, drugi przekaźnik) | XY-SK120 to buck-boost — dioda i drugi przekaźnik nie są potrzebne (ZB §5.1, §5.4) |
| Przetwornica step-up **19 V** | po 4 m przewodu na wtyku zejdzie poniżej 19 V — dolnej granicy M910q (ZB §3.1) |
| XL6019 jako zasilanie M910q | realnie ok. 45 W; wymuszał limit RAPL (ZB §3) |
| Jeden XH-M603 na obie ładowarki | 10 A przekracza realne ok. 8 A płytki (ZB §6.3) |
| Przewód CCA („miedziowane aluminium”) | ok. 1,6 × większa rezystancja, gorzej znosi zaciskanie (ZB §8.2) |
| Płaskowniki miedziane na szyny banku | przy dwóch koszach linka z blokami zbiorczymi daje ok. 4 % rozrzutu prądów — dla AGM bez znaczenia (ZB §4.3) |
| VSR / separator akumulatorów | zastąpiony przekaźnikiem K1 z zapłonu albo D+ (ZB §5.4) |
| Ładowarka B2B izolowana (VEVOR, Renogy, Victron) | droższa alternatywa (ZB §5.7) — ma sens dla izolacji galwanicznej, ale 20 A bez regulacji to za dużo dla banku, a warstwy nadnapięciowej na pełny prąd nadal trzeba |
| Czujnik NTC | w dostępnych materiałach XY-SK120 nie ma wejścia kompensacji — CV przestawiasz sezonowo (ZB §5.5) |
| „Uniwersalna” końcówka do M910q | pasowanie i pin ID to loteria (ZB §3.3) |
| Ładowarka/BMS do LiFePO₄ lub Li-ion, preset GEL | inne napięcia — bank AGM nie dojdzie do pełna albo się zniszczy |
| Buck 12 → 5 V dla logiki panelu | logika i dotyk idą po USB z M910q |
| DAC USB ES9038Q2M | mini-jack M910q wystarcza do weryfikacji |
| Karta WiFi | masz MT7921 i P2P-GO już działa |
| Wzmacniacz, głośniki, subwoofer | osobna gałąź wprost z akumulatora rozruchowego, po testach |
| Drugi ekran, kamery, graber, czujniki | odpowiednie moduły są wyłączone |
| Moduł 9 przekaźników, HM-10, RXB6 | dochodzą razem z Nano #1 przy rozbudowie |

---

## Powiązane dokumenty

| Dokument | Zakres |
|----------|--------|
| [`WDROZENIE_TESTOWE.md`](WDROZENIE_TESTOWE.md) | co z tym zrobić — krok po kroku |
| [`ARDUINO_OD_ZERA.md`](ARDUINO_OD_ZERA.md) | wgranie firmware na Nano — od kabla po test na biurku |
| [`ZASILANIE_BUFOROWANE.md`](ZASILANIE_BUFOROWANE.md) | nastawy, uzasadnienia, lista dla wersji docelowej (§10) |
| [`SCHEMATY_POLACZEN.md`](SCHEMATY_POLACZEN.md) | tabele „skąd → dokąd" (§10 — wariant testowy) |
| [`../schematics/schematic_test_power.svg`](../schematics/schematic_test_power.svg) | schemat komponentowy toru zasilania (arkusz 1/2) |
| [`mechanika/kosze_HR1221W_4+3.pdf`](mechanika/kosze_HR1221W_4+3.pdf) | projekt koszy na bank |
| [`../schematics/ignition_sense.svg`](../schematics/ignition_sense.svg) | wykrywanie zapłonu i sterowanie przyciskiem |
