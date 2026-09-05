# Lista zakupowa — wszystko w jednym miejscu

Jedna lista do wariantu z [`WDROZENIE_TESTOWE.md`](WDROZENIE_TESTOWE.md):
instalacja jeżdżąca z pełnym torem zasilania, Android Auto wireless, dźwiękiem
przez mini-jack i przyciskami SWC.

Ceny orientacyjne, rynek PL, 2025/2026. **Razem: ~670–1305 PLN.**

---

## Masz już — nie kupuj

| Element | Rola |
|---------|------|
| Lenovo ThinkCentre M910q Tiny | komputer |
| Ekran 7" 1024×600, HDMI + dotyk USB | wyświetlacz na czas testów |
| Karta WiFi MediaTek MT7921 | P2P-GO dla Android Auto wireless |
| Pody SWC + dekoder rezystorowy | przyciski na kierownicy |
| Modem LTE Huawei E3372 (HiLink) | internet |
| CSB HR1221W F2 × 8 (12 V / 5,1 Ah AGM) | bank buforowy — **użyj 7 (35,7 Ah)**, jeden zostaje w zapasie |
| **XL6019** | step-up 12 → 19,5 V dla M910q |
| **XH-M609** | LVD, ochrona banku |
| **Arduino Pro Micro** (ATmega32U4) | SWC, enkoder, przyciski — USB HID |
| **Arduino Nano V3** (ATmega328PB) | zapłon + sterowanie zasilaniem M910q |
| **LM2596** | 12 → 5 V, podświetlenie panelu |
| **MP1584** | 12 → 5 V, zasilanie Nano niezależne od USB |

> **Nano V3 z 328PB wymaga uwagi przy wgrywaniu.** To nie jest 328P — ma inną
> sygnaturę i rdzeń `arduino:avr` jej nie zna. Objaw: avrdude przerywa
> z „Expected signature for ATmega328P". Rozwiązania są w
> `arduino/sensor_hub/sketch.yaml`. Sam firmware kompiluje się na obu.

---

## Do kupienia

> **Budujesz na płytkach drukowanych?** [`PCB_ZASILANIE.md`](PCB_ZASILANIE.md)
> ma osobną listę elementów wlutowywanych (~80–160 zł) i wtedy **wykreśl
> stąd** poz. 1 i 5a (oba przekaźniki Bosch — zastępuje je T90 na płytce)
> oraz drugi kondensator z poz. 7.

| # | Element | Specyfikacja | Po co | Cena (PLN) |
|---|---------|--------------|-------|-----------|
| 1 | Przekaźnik 30 A SPDT + podstawka | Bosch 12 V | rozłącza tor ładowania przy zgaszonym silniku | 15–25 |
| 2 | **Dioda MBR2545CT** | 25 A / 45 V, TO-220AB | blokada wsteczna; **obie anody zwarte** | 5–12 |
| 3 | Radiator do TO-220 + podkładka mikowa | 4,4 W strat przy CC 8,0 A (≥ 6 K/W) | blaszka diody to katoda — musi być izolowana | 7–15 |
| 4 | **Moduł CC-CV boost** | „900 W 15 A" z wyświetlaczem albo „1500 W 30 A" boost (**nie SZBK07** — to buck, patrz [`PCB_ZASILANIE.md`](PCB_ZASILANIE.md) §2) | ładowarka: CV 14,40 V, **CC 8,0 A** | 50–140 |
| 5 | **Rozłącznik nadnapięciowy** | **XH-M603** (albo XH-M604) — ta sama rodzina co XH-M609 | blokada przeładowania: 15,30 V / powrót 14,00 V | 40–80 |
| 5a | Przekaźnik 30 A SPDT + podstawka (drugi) | Bosch 12 V | moduł steruje cewką zamiast przenosić 8 A — §6.3 ZASILANIE | 15–25 |
| 6 | Dioda TVS | 1.5KE33**CA** albo SMCJ26**CA** | ochrona wejścia przed load dumpem; **„CA" = dwukierunkowa**, wersja bez „C" jest inną diodą | 5–10 |
| 7 | Kondensator 470 µF / 35 V low-ESR × 2 | 105 °C | wejście ładowarki + wyjście XL6019 | 7–14 |
| 8 | Dioda 1N4007 × 5 | | gaszenie cewek przekaźników | 2–5 |
| 9 | Radiator + wentylator 40 mm | do XL6019 | w aucie obowiązkowy | 20–35 |
| 10 | **Moduł przekaźnika 1-kanałowy 5 V** | z optoizolacją | styki równolegle do przycisku zasilania M910q | 5–12 |
| 11 | Transoptor **PC817** × 2 | DIP-4 | wejście zapłonu + odczyt diody panelu | 2–5 |
| 12 | Rezystory 1/4 W | 2,2 kΩ × 2, 10 kΩ × 2, 1 kΩ × 2 | do transoptorów i pull-upów | 5–10 |
| 13 | Kondensator 100 nF × 2 | ceramiczny | filtr na wejściach zapłonu i diody | 2–4 |
| 14 | Bezpiecznik **15 A** + oprawka | przy klemie „+" | zasilanie ładowarki | 15–25 |
| 15 | Bezpieczniki inline **10 A × 7** + oprawki | oznaczenia **FB1…FB7** | po jednym na „+" każdego z siedmiu pakietów banku | 35–56 |
| 16 | Bezpiecznik inline **15 A** + oprawka | klasa **MIDI/AMI albo ANL** (zdolność wyłączania ≥ 2 kA — prąd zwarciowy banku siedmiu pakietów to ~2,4 kA, ATO ma tylko ~1 kA) | wejście XH-M609 (F7) | 15–30 |
| 17 | Bezpiecznik **7,5 A** + oprawka | | odgałęzienie XL6019 | 8–12 |
| 18 | Bezpiecznik **2 A** i **3 A** + oprawki × 2 | wkładki ATO/ATC | **F9** 2 A — LM2596 (podświetlenie panelu, §3.1b [`WDROZENIE_TESTOWE.md`](WDROZENIE_TESTOWE.md)); **F10** 3 A — MP1584 (Nano) | 12–20 |
| 19 | Przewód **2,5 mm²** FLRY | czerwony 3 m + czarny 2 m | odcinek bank → LVD → S1 (przewody 8–10) | 25–40 |
| 19a | Przewód **4 mm²** FLRY | czerwony **6 m** + czarny **4 m** | **cały tor ładowania** — wejście (przewody 1–3, 5–6, ~3 m od klemy) i pętla ładowarka → szyna „+" banku wraz z powrotem OUT− do masy (spadek siedzi w pętli CV — §8.2 ZASILANIE) | 50–85 |
| 20 | Przewód **1,5 mm²** FLRY | czerwony + czarny **po 5 m** | siedem ogonków pakietów (~0,30 m na biegun) + pętle serwisowe + odgałęzienia przetwornic | 25–40 |
| 21 | Przewód **0,75 mm²** FLRY | kilka kolorów po 2 m | cewki, zasilanie logiki | 15–25 |
| 22 | Przewód **0,5 mm²** | kilka kolorów po 2 m | sygnały: zapłon, przekaźnik, dioda panelu | 10–20 |
| 23 | Nasuwki **F2 6,35 mm** izolowane | komplet — 14 sztuk na bank plus zapas | zaciski akumulatorów HR1221W | 25–40 |
| 24 | Konektory oczkowe, tulejki, koszulki | zestaw, koszulki z klejem | | 30–50 |
| 25 | **Rozłącznik masy 100 A** | kluczykowy albo pokrętło | jedyne realne zero poboru na postoju | 40–70 |
| 26 | Skrzynka / wspornik na bank + pasy | na **7 pakietów (12,6 kg)**; min. 280 × 180 × 101 mm (układ 4 + 3) albo 490 × 90 × 101 mm (rząd); 2 pasy ≥ 250 daN | mocowanie do nadwozia — 4 punkty M8 z płytkami ≥ 40 × 40 × 3 mm | 100–200 |
| 26a | **Szyny zbiorcze banku** | 2 × płaskownik miedziany **15 × 2 mm** (min.) albo **20 × 3 mm** (zalecany), ok. 600 mm każdy + 14 śrub M6 + pokrywa izolacyjna | równy rozdział prądu między siedem pakietów — §4.3 ZASILANIE | 60–140 |
| 27 | Peszel + przelotki gumowe | 5 m + komplet | przejścia przez blachę | 25–40 |
| 28 | Kabel USB z **przeciętą żyłą VBUS** | albo przetnij czerwoną w zwykłym | Nano ma własne 5 V — dwa źródła nie mogą się bić | 0–20 |
| | | | **Razem** | **670–1305** |

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
| VSR / separator akumulatorów | zastąpiony przekaźnikiem z zapłonu i diodą — §5.3c [`ZASILANIE_BUFOROWANE.md`](ZASILANIE_BUFOROWANE.md) |
| Ładowarka B2B (Victron / Redarc) | przy nastawie CC 8,0 A wariant z przekaźnikiem i boostem robi to samo za ~1/5 ceny. Ocena przestaje być prawdziwa dopiero, gdyby ktoś chciał wejść na 13–14,7 A — wtedy Orion-Tr Smart 12/12-18 jest jedynym torem, który to udźwignie (ale warstwy nadnapięciowej i tak nie omija) |
| Moduł buck-boost LTC3780 | utrzyma 13,8 V, ale tylko 80 W ciągle — po odjęciu obciążenia zostaje 2,3 A do banku, czyli 11,6 h fazy CC z progu LVD przy siedmiu pakietach |
| Czujnik NTC | tanie moduły CC-CV nie mają wejścia kompensacji |
| Przewód 6 mm², bezpiecznik główny 30 A | wymiarowane pod ładowarkę B2B; przy CC 8,0 A tor wejściowy niesie 9,2 A i 2,5 mm² z F1 15 A mieści się w kryterium 3 % (0,39 V na 3 m) — choć bez zapasu, więc na ten odcinek zalecany jest 4 mm² (§3.1 [`WDROZENIE_TESTOWE.md`](WDROZENIE_TESTOWE.md)). 6 mm² staje się konieczne dopiero od CC 10 A |
| Buck 12 → 5 V dla panelu | logika i dotyk idą po USB z M910q |
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
| [`../schematics/schematic_test_build.svg`](../schematics/schematic_test_build.svg) | schemat ideowy |
| [`../schematics/wiring_test_build.svg`](../schematics/wiring_test_build.svg) | schemat połączeniowy |
| [`../schematics/ignition_sense.svg`](../schematics/ignition_sense.svg) | wykrywanie zapłonu i sterowanie przyciskiem |
