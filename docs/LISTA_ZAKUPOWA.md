# Lista zakupowa — wszystko w jednym miejscu

Jedna lista do wariantu z [`WDROZENIE_TESTOWE.md`](WDROZENIE_TESTOWE.md):
instalacja jeżdżąca z pełnym torem zasilania, Android Auto wireless, dźwiękiem
przez mini-jack i przyciskami SWC.

Ceny orientacyjne, rynek PL, 2025/2026. **Razem: ~479–923 PLN.**

---

## Masz już — nie kupuj

| Element | Rola |
|---------|------|
| Lenovo ThinkCentre M910q Tiny | komputer |
| Ekran 7" 1024×600, HDMI + dotyk USB | wyświetlacz na czas testów |
| Karta WiFi MediaTek MT7921 | P2P-GO dla Android Auto wireless |
| Pody SWC + dekoder rezystorowy | przyciski na kierownicy |
| Modem LTE Huawei E3372 (HiLink) | internet |
| CSB HR1221W F2 × 8 (12 V / 5,1 Ah AGM) | bank buforowy — użyj 5, lepiej 8 |
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

| # | Element | Specyfikacja | Po co | Cena (PLN) |
|---|---------|--------------|-------|-----------|
| 1 | Przekaźnik 30 A SPDT + podstawka | Bosch 12 V | rozłącza tor ładowania przy zgaszonym silniku | 15–25 |
| 2 | **Dioda MBR2545CT** | 25 A / 45 V, TO-220AB | blokada wsteczna; **obie anody zwarte** | 5–12 |
| 3 | Radiator do TO-220 + podkładka mikowa | ok. 4,5 W strat | blaszka diody to katoda — musi być izolowana | 7–15 |
| 4 | **Moduł CC-CV boost** | „900 W 15 A" z wyświetlaczem albo **SZBK07** | ładowarka: CV 14,40 V, CC 8 A | 50–140 |
| 5 | Rozłącznik nadnapięciowy | przekaźnik napięciowy programowalny (XY-WJ01 lub odp.) | blokada przeładowania, próg 15,30 V | 40–80 |
| 6 | Dioda TVS | 1.5KE33CA albo SMCJ26CA | ochrona wejścia przed load dumpem | 5–10 |
| 7 | Kondensator 470 µF / 35 V low-ESR × 2 | 105 °C | wejście ładowarki + wyjście XL6019 | 7–14 |
| 8 | Dioda 1N4007 × 5 | | gaszenie cewek przekaźników | 2–5 |
| 9 | Radiator + wentylator 40 mm | do XL6019 | w aucie obowiązkowy | 20–35 |
| 10 | **Moduł przekaźnika 1-kanałowy 5 V** | z optoizolacją | styki równolegle do przycisku zasilania M910q | 5–12 |
| 11 | Transoptor **PC817** × 2 | DIP-4 | wejście zapłonu + odczyt diody panelu | 2–5 |
| 12 | Rezystory 1/4 W | 2,2 kΩ × 2, 10 kΩ × 2, 1 kΩ × 2 | do transoptorów i pull-upów | 5–10 |
| 13 | Kondensator 100 nF × 2 | ceramiczny | filtr na wejściach zapłonu i diody | 2–4 |
| 14 | Bezpiecznik **15 A** + oprawka | przy klemie „+" | zasilanie ładowarki | 15–25 |
| 15 | Bezpieczniki inline **10 A × 5** + oprawki | | po jednym na pakiet banku | 25–40 |
| 16 | Bezpiecznik inline **15 A** + oprawka | | wejście XH-M609 | 8–12 |
| 17 | Bezpiecznik **7,5 A** + oprawka | | odgałęzienie XL6019 | 8–12 |
| 18 | Bezpiecznik **3 A** + oprawka × 2 | | LM2596 (podświetlenie) i MP1584 (Nano) | 12–20 |
| 19 | Przewód **2,5 mm²** FLRY | czerwony 5 m + czarny 3 m | tor ładowania i bank | 40–60 |
| 20 | Przewód **1,5 mm²** FLRY | czerwony + czarny po 3 m | odgałęzienia przetwornic | 15–25 |
| 21 | Przewód **0,75 mm²** FLRY | kilka kolorów po 2 m | cewki, zasilanie logiki | 15–25 |
| 22 | Przewód **0,5 mm²** | kilka kolorów po 2 m | sygnały: zapłon, przekaźnik, dioda panelu | 10–20 |
| 23 | Nasuwki **F2 6,35 mm** izolowane | komplet | zaciski akumulatorów HR1221W | 15–25 |
| 24 | Konektory oczkowe, tulejki, koszulki | zestaw, koszulki z klejem | | 30–50 |
| 25 | **Rozłącznik masy 100 A** | kluczykowy albo pokrętło | jedyne realne zero poboru na postoju | 40–70 |
| 26 | Skrzynka / wspornik na bank + pasy | na 5–8 pakietów | mocowanie do nadwozia | 60–120 |
| 27 | Peszel + przelotki gumowe | 5 m + komplet | przejścia przez blachę | 25–40 |
| 28 | Kabel USB z **przeciętą żyłą VBUS** | albo przetnij czerwoną w zwykłym | Nano ma własne 5 V — dwa źródła nie mogą się bić | 0–20 |
| | | | **Razem** | **479–923** |

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
| Ładowarka B2B (Victron / Redarc) | wariant z przekaźnikiem i boostem robi to samo za ~1/5 ceny |
| Moduł buck-boost LTC3780 | utrzyma 13,8 V, ale tylko 80 W ciągle — za mało przy pięciu pakietach |
| Czujnik NTC | tanie moduły CC-CV nie mają wejścia kompensacji |
| Przewód 6 mm², bezpiecznik główny 30 A | wymiarowane pod ładowarkę B2B, nie pod 8 A |
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
| [`ZASILANIE_BUFOROWANE.md`](ZASILANIE_BUFOROWANE.md) | nastawy, uzasadnienia, lista dla wersji docelowej (§10) |
| [`SCHEMATY_POLACZEN.md`](SCHEMATY_POLACZEN.md) | tabele „skąd → dokąd" (§10 — wariant testowy) |
| [`../schematics/schematic_test_build.svg`](../schematics/schematic_test_build.svg) | schemat ideowy |
| [`../schematics/wiring_test_build.svg`](../schematics/wiring_test_build.svg) | schemat połączeniowy |
| [`../schematics/ignition_sense.svg`](../schematics/ignition_sense.svg) | wykrywanie zapłonu i sterowanie przyciskiem |
