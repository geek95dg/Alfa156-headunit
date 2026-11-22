# Schematy połączeniowe — jak to pospiąć w całość

Praktyczny przewodnik montażowy: co z czym połączyć, jakim przewodem, przez
jaki bezpiecznik i w jakiej kolejności. Uzupełnia schematy blokowe
(architektura) o poziom **zacisk po zacisku**.

| Rysunek | Co pokazuje |
|---------|-------------|
| [`wiring_power_modules.svg`](../schematics/wiring_power_modules.svg) | Moduły zasilania — każdy zacisk podpisany, przekroje, bezpieczniki, masy. **Pokazuje jeszcze poprzedni tor** (domena za zapłonem, boost z diodą, listwy) i czeka na przerysowanie — obowiązują tabele §2 |
| [`wiring_vehicle_arduino.svg`](../schematics/wiring_vehicle_arduino.svg) | Sygnały pojazdu → układy dopasowujące (PC817, dzielniki) → Arduino |
| [`wiring_usb_av.svg`](../schematics/wiring_usb_av.svg) | USB, wyświetlacze, audio, kamery |
| [`vehicle_layout_m910q.svg`](../schematics/vehicle_layout_m910q.svg) | Rozmieszczenie w aucie — strefy montażu, trasy kablowe, bilans masy |
| [`esp32_display_wiring.svg`](../schematics/esp32_display_wiring.svg) | Wyświetlacz pomocniczy 1,8" — dziesięć wejść przez PC817, panel ST7735 po SPI, zasilanie z +15 |

Schematy blokowe (co i dlaczego): [`../schematics/README.md`](../schematics/README.md).
Dobór podzespołów i nastawy: [`ZASILANIE_BUFOROWANE.md`](ZASILANIE_BUFOROWANE.md).

---

## Spis treści

1. [Konwencje](#1-konwencje)
2. [Tabela połączeń — zasilanie](#2-tabela-połączeń--zasilanie)
3. [Tabela połączeń — sygnały pojazdu](#3-tabela-połączeń--sygnały-pojazdu)
4. [Tabela połączeń — Arduino](#4-tabela-połączeń--arduino)
5. [Tabela połączeń — USB, obraz, audio](#5-tabela-połączeń--usb-obraz-audio)
6. [Bezpieczniki — zestawienie](#6-bezpieczniki--zestawienie)
7. [Masy](#7-masy)
8. [Kolejność montażu](#8-kolejność-montażu)
9. [Lista kontrolna przed pierwszym załączeniem](#9-lista-kontrolna-przed-pierwszym-załączeniem)
10. [Tabela połączeń — wariant testowo-rozwojowy](#10-tabela-połączeń--wariant-testowo-rozwojowy)
11. [Wyświetlacz pomocniczy 1,8" na ESP32](#11-wyświetlacz-pomocniczy-18-na-esp32)

---

## 1. Konwencje

### Kolory na schematach

| Kolor | Znaczenie |
|-------|-----------|
| Czerwony gruby | zasilanie 12 V (moc) |
| Pomarańczowy | zasilanie 5 V |
| Czarny | masa |
| Niebieski | sygnał logiczny |
| Niebieski przerywany | sygnał sterujący (ACC, NTC, REM) |
| Zielony | USB |
| Fioletowy | obraz (DisplayPort / HDMI / AHD) |
| Bordowy | audio analogowe |

### Kolory przewodów w aucie — propozycja

Repozytorium nie narzuca kolorystyki, ale warto się jednej trzymać — przy
diagnostyce po roku od montażu to oszczędza godziny:

| Obwód | Kolor |
|-------|-------|
| +12 V stałe (przed LVD: ładowanie, bank) | czerwony |
| +12 V buforowane (za LVD, dystrybucja) | czerwono-biały |
| +12 V odgałęzień do przodu (za F9–F13) | pomarańczowy |
| +5 V | żółty |
| +20 V do M910q | brązowy |
| Masa | czarny |
| Sygnały do Arduino | szary / niebieski |
| Zapłon / D+ (sterowanie K1, sygnał) | zielony |

### Zaciski na rysunkach

Zaciski są narysowane **na krawędziach obudów** i ponumerowane.
**Obowiązuje numeracja z tabel poniżej** (6/6a, 7/7a, bloki L+/L−/P+/P−,
FC1/FC2, F12). [`wiring_power_modules.svg`](../schematics/wiring_power_modules.svg)
ma jeszcze starą numerację zacisków 1–8 i zostanie przenumerowany przy
przerysowaniu.

---

## 2. Tabela połączeń — zasilanie

Wartości wkładek, przekroje i nastawy pochodzą z
[`ZASILANIE_BUFOROWANE.md`](ZASILANIE_BUFOROWANE.md) (dalej: ZB) — przy
rozbieżności obowiązuje tamten dokument. Wszystko, co dotyczy banku,
ładowania, LVD i przetwornicy step-up, stoi **w bagażniku, przy koszach**;
do przodu idzie jedna wiązka (ZB §8a.2).

### 2.1 Tor ładowania (od akumulatora rozruchowego do banku)

Dwie ładowarki **XY-SK120** (buck-boost CC-CV) pracują równolegle, każda
z własnym rozłącznikiem nadnapięciowym **XH-M603** — ZB §5.2–§5.4, §6.3.

| # | Skąd | Dokąd | Przewód | Zabezpieczenie |
|---|------|-------|---------|----------------|
| 1 | Akumulator rozruchowy „+” | **F1** (wejście) | 6 mm² | — |
| 2 | **F1** (wyjście) | TVS + C1, biegun „+” (w bagażniku, przed K1) | 6 mm², ~5 m — zmierz | **F1 20 A**, MIDI/AMI lub ANL, ≤ 30 cm od klemy |
| 3 | TVS + C1 „+” | **K1** zacisk **30** | 6 mm² | — |
| 4 | zapłon albo **D+** alternatora | **K1** zacisk **86** (cewka) | 0,75 mm², ~4–5 m | **FK 1 A** z przodu, w miejscu wpięcia |
| 5 | **K1** zacisk **85** | punkt masy przy banku | 0,75 mm² | — |
| 6 | **K1** zacisk **87** | XY-SK120 #1 **IN+** | 2,5 mm², ≤ 1 m | — |
| 6a | **K1** zacisk **87** | XY-SK120 #2 **IN+** | 2,5 mm², ≤ 1 m | — |
| 7 / 7a | XY-SK120 #1 / #2 **OUT+** | XH-M603 #1 / #2 **DC-IN+** | 2,5 mm², ≤ 0,5 m | — |
| 8 / 8a | XH-M603 #1 / #2 **OUT+** | złączenie gałęzi | 2,5 mm², obie gałęzie tej samej długości | **FC1 / FC2 7,5 A** ATO, tuż przy OUT+ |
| 9 | złączenie gałęzi | **blok L+** banku | **4 mm²**, ≤ 1 m | **F12 15 A**, MIDI/AMI lub ANL, przy bloku L+ |
| 10 | IN− / OUT− obu XY-SK120, DC-IN− obu XH-M603, „−” TVS i C1 | punkt masy przy banku | 2,5 mm² | — |

> **Bez diody blokującej i bez izolacji.** XY-SK120 robi 14,40 V z dowolnego
> napięcia 12,5–14,7 V z instalacji (ZB §5.1), więc dawna dioda MBR2545CT
> nie jest potrzebna. Bank od instalacji auta na postoju odcina rozwarty
> K1. Masa wejścia i wyjścia XY-SK120 to ten sam zacisk: **żadnego
> osobnego przewodu masy do klemy „−” rozruchowego** — prąd wejściowy wraca
> przez punkt masy przy banku i nadwozie (ZB §5.6).

> **Ochrona wejścia** — przed K1, na jednym zacisku: dioda TVS **SMCJ20CA**
> (dwukierunkowa; Vc ok. 32 V wg typowych kart, poniżej 36 V wejścia
> XY-SK120 — potwierdź w karcie kupionej diody) i kondensator
> **470 µF / 35 V** low-ESR, 105 °C, oba równolegle. Nietłumionego load
> dumpu ta dioda nie przeżyje — ZB §5.8.

> **Dioda gaszeniowa 1N4007** równolegle do cewki K1: **katoda do zacisku
> 86**, anoda do 85.

> **XH-M603 zasilany z wyjścia swojej ładowarki** (DC-IN), mierzy po stronie
> OUT (bank). Przyjęcie, że bez zasilania ma rozwarty przekaźnik i nie bierze
> prądu z banku, sprawdza test ZB §6.4 pkt 6 — **przed** montażem.
> Nastawy: rozwarcie 15,30 V, powrót 14,00 V. Ładowarki: CV 14,40 V (lato
> 13,95 V), CC 5,0 A każda, OVP 15,0 V, wyjście po włączeniu zasilania ON —
> ZB §5.2, §5.5, §11 Etap 1.

> **Wariant PCB.** TVS, C1, K1 z diodą D6 i rozgałęzienie na przewody 6/6a
> mogą siedzieć na płytce A —
> [`PCB_ZASILANIE.md`](PCB_ZASILANIE.md) §1. Ładowarki, XH-M603, FC1/FC2
> i F12 zostają przy banku, na przewodach.

### 2.2 Bank akumulatorów — dwa kosze, linka i bloki zbiorcze

Bank ma **siedem pakietów** łączonych **równolegle** (12 V / 35,7 Ah) w dwóch
koszach przy grodzi za tylną kanapą: **kosz L — #1…#4, kosz P — #5…#7**
(numeracja od zewnętrznego końca kosza L). W każdym koszu po jednym
**bloku zbiorczym na biegun** — L+, L−, P+, P−: izolowana podstawa
z szynką, **4 kołki M6 i pokrywa** (ZB §4.3).

| # | Skąd | Dokąd | Przewód | Zabezpieczenie |
|---|------|-------|---------|----------------|
| 11 | HR1221W #1…#4 **„+” F2** | blok **L+** | FLRY-B 2,5 mm², 0,25 m ±30 mm | **FB1…FB4** 10 A inline, 5–10 cm od zacisku |
| 12 | HR1221W #5…#7 **„+” F2** | blok **P+** | FLRY-B 2,5 mm², 0,25 m ±30 mm | **FB5…FB7** 10 A inline, 5–10 cm od zacisku |
| 13 | HR1221W #1…#4 **„−” F2** | blok **L−** | FLRY-B 2,5 mm², ta sama długość | — |
| 14 | HR1221W #5…#7 **„−” F2** | blok **P−** | FLRY-B 2,5 mm², ta sama długość | — |
| 15 | blok **L+** | blok **P+** — łącznik „+” | **6 mm² OFC**, 0,4–0,6 m | chroniony wkładkami FB pakietów |
| 16 | blok **L−** | blok **P−** — łącznik „−” | **6 mm² OFC**, ta sama długość co 15 | — |
| 17 | blok **P−** | **S1** rozłącznik masy 100 A → punkt masy | 6 mm², ≤ 0,5 m | — |
| 18 | blok **L+** | pomiar napięcia banku (`FEATURE_BATT_ADC`, ZB §13.4) | 0,5 mm² | 1 A przy banku |

> **Odbiór po przekątnej.** „+” bierzesz z bloku **L+** (przewody 9 i 19),
> „−” z bloku **P−** (przewód 17). **Nigdy oba bieguny z tego samego
> kosza** — rozrzut prądów skacze wtedy z ok. 4 % do ok. 24 % (ZB §4.3).

> **Linka zamiast listwy — warunki.** Łącznik i odbiory 6 mm² z czystej
> miedzi (**nie CCA**), linka drobnodrutowa klasy 5/6, izolacja 105 °C,
> np. FLRY-B 6 mm² albo przewód car-audio OFC 6 mm². Odcinki pakiet → blok
> **równej długości (±30 mm)** — nadmiar zwiń w pętlę, nie skracaj. Na blok
> oczka M6, najwyżej dwa na kołek, grubsze na spód, nakrętka z podkładką
> sprężystą. Rachunek: ZB §4.3.

> **Zaciski F2 i belka dociskowa.** Nasuwki żeńskie 6,3 × 0,8 mm **w pełni
> izolowane** (na 1,5–2,5 mm²), zaciskane zaciskarką zapadkową, kapturki na
> wszystkich 14 biegunach. Uziemiona belka dociskowa kosza leży 25–29 mm nad
> zaciskami — przewody prowadź **od belki w stronę bagażnika**, nigdy pod
> nią. Bloki na płytce izolacyjnej ≥ 3 mm od strony bagażnika, **nie** na
> grodzi nad koszem (ZB §4.3, §4.7). Prąd zwarciowy banku to ok. 2,2 kA —
> pokrywy bloków są obowiązkowe.

### 2.3 LVD i dystrybucja

| # | Skąd | Dokąd | Przewód | Zabezpieczenie |
|---|------|-------|---------|----------------|
| 19 | blok **L+** | XH-M609 **VIN+** | **6 mm²**, ≤ 0,5 m | **F7 20 A**, klasa **MIDI/AMI lub ANL** (≥ 2,5 kA wg karty), przy bloku L+ |
| 20 | XH-M609 **VIN−** | punkt masy | 0,75 mm² | — |
| 21 | XH-M609 **VOUT+** | dystrybucja — listwa ATO z pokrywą albo płytka B (X8.1) | 4 mm², ≤ 0,5 m | — |
| 22 | dystrybucja, masa (X8.2) | punkt masy | 2,5 mm² | — |

> **XH-M609 — sprawdź przed montażem.** Przekaźnik ma przerywać **plus**.
> Omomierz między VIN− a VOUT− musi pokazywać zwarcie niezależnie od stanu
> przekaźnika; jeżeli pokazuje przerwę, moduł przełącza masę i rozspójnia
> topologię jednego punktu masy. VOUT− zostaw niepodłączony — powroty
> odbiorników idą wprost do punktu masy. Pozostałe sprawdzenia: ZB §7.3.
>
> **F7 20 A**: reguła producenta modułu 1,5 × prąd szczytowy
> (1,5 × 10,5 A = 15,75 A) daje najbliższą większą wkładkę 20 A. Wartość
> nie zależy od liczby pakietów — przez F7 płynie wyłącznie prąd
> odbiorników. Klasa wynika z ok. 2,2 kA prądu zwarciowego na bloku — ATO ma
> zdolność wyłączania ok. 1 kA (ZB §7.4).

### 2.4 Odgałęzienia za LVD — wszystkie wkładki w bagażniku

Bezpiecznik stoi **przy źródle**, czyli na początku trasy do przodu —
zwarcie w połowie czterech metrów ma się przepalić w bagażniku (ZB §8.1).

| # | Skąd | Dokąd | Przewód | Zabezpieczenie |
|---|------|-------|---------|----------------|
| 23 | dystrybucja | przetwornica step-up **IN+** | 4 mm², ≤ 1 m | **F8 10 A** |
| 24 | step-up **IN−** | punkt masy | 4 mm² | — |
| 25 | step-up **OUT+** | wtyk M910q, **środek** | 4 mm², ~4 m + odcinek oryginalnego kabla | **5 A** przy wyjściu przetwornicy |
| 26 | step-up **OUT−** | wtyk M910q, **ekran** | 4 mm², ~4 m | — |
| 27 | dystrybucja | LM2596 **IN+** (z przodu — wyświetlacze) | 1,0 mm², ~4 m | **F9 2 A** |
| 28 | dystrybucja | MP1584 **IN+** (z przodu — logika, Arduino) | 0,75 mm², ~4 m | **F10 3 A** |
| 29 | dystrybucja | AUX 12 V: moduł 9 przekaźników **VCC** | 1,5 mm² | **F11 5 A** |
| 30 | dystrybucja | wstrzykiwacz 5 V telefonu (opcja, ZB §14.6) | 0,75 mm², ~4 m | **F13 2 A** |
| 31 | IN− LM2596 i MP1584, GND modułu przekaźników i wstrzykiwacza (z przodu) | wspólny powrót → punkt masy przy banku | **2,5 mm²**, ~4 m | — |

> **Przetwornica step-up 12 → 20 V, 10 A (200 W), zalewana.** Moduł
> bezmarkowy i zwykle bez regulacji — każdą sztukę sprawdzasz na biurku
> przed zabudową: bez obciążenia **19,9–20,5 V**, przy ~60 W na wyjściu
> modułu ≥ 19,8 V, na wtyku ≥ 19,5 V, także przy wejściu 11,0 V (ZB §3.4).
> M910q jest zasilany **stale** — wyjścia przetwornicy nie używa się jako
> wyłącznika; usypia go impuls z Arduino na przycisk zasilania (§10.5).
> Wtyk: z uciętego oryginalnego kabla, środek = „+”, ekran = masa; uwaga
> o pinie identyfikacyjnym — ZB §3.3.

> **Hub USB.** ZB nie przypisuje mu osobnej wkładki. Hub z wejściem 12 V
> zasil z gałęzi **F11** (moduł przekaźników ~10 mA w spoczynku + hub do
> ~1 A mieści się w 5 A); hub 5 V — przez własny buck z tej samej gałęzi.
> Osiem urządzeń nie wyrobi się na prądzie z portu M910q (§5.3).

### 2.5 Odbiorniki 5 V z przodu — logika i wyświetlacze

| # | Skąd | Dokąd | Przewód | Zabezpieczenie |
|---|------|-------|---------|----------------|
| 32 | MP1584 **OUT+** (5,0 V) | Nano #1 pin **5V**, Nano #2 pin **5V** | 0,75 mm² | — |
| 33 | MP1584 **OUT+** (5,0 V) | HM-10 **VCC**, RXB6 **VCC** | 0,5 mm² | — |
| 34 | MP1584 **OUT−** | Nano #1/#2 **GND**, HM-10, RXB6 | 0,75 mm² | — |
| 35 | LM2596 **OUT+** (wg panelu) | panel główny 10,1" — zasilanie podświetlenia przez stopień MOSFET (PWM z Nano #1) | 1,0 mm² | — |
| 36 | LM2596 **OUT+** | panel drugi 6,86" *(opcjonalny)* | 1,0 mm² | — |
| 37 | LM2596 **OUT−** | masa paneli (wspólna z Nano #1) | 1,0 mm² | — |

> **Role bucków.** **MP1584** zasila logikę i Arduino — Nano #2 musi żyć,
> gdy M910q śpi, bo w S3 porty USB są martwe (ZB §2.1). **LM2596** zasila
> wyświetlacze — osobno, bo podświetlenie jest sterowane PWM-em z Nano #1,
> czego nie da się zrobić na zasilaniu z USB (ZB §2.2).

> **Nie podawaj napięcia na pin Vin Nano.** Buck jest ustawiony na 5,0 V
> i idzie wprost na pin **5V**, z pominięciem wewnętrznego stabilizatora.

### 2.6 Gałąź wzmacniacza (niezależna)

Wzmacniacz to **gotowy moduł samochodowy** z wejściami RCA, nie układ DIY.
Podłącza się go jak radio samochodowe: zasilanie wprost z akumulatora, własna
masa, wyzwalanie sygnałem REM.

| # | Skąd | Dokąd | Przewód | Zabezpieczenie |
|---|------|-------|---------|----------------|
| 44 | Akumulator „+” | Wzmacniacz **+12V** | 6 mm² | wg karty modułu, przy klemie |
| 45 | Wzmacniacz **GND** | masa lokalna, przy wzmacniaczu | 6 mm² | — |
| 46 | linia zapłonu (ACC) | Wzmacniacz **REM** | 0,75 mm² | 2 A |

> **Bezpiecznik dobierz wg karty wzmacniacza**, nie „na oko". Typowy moduł
> 4 × 50 W RMS ma na płytce bezpiecznik 20–30 A i tyle samo powinien mieć
> przy klemie. Przewód 6 mm² wynika ze spadku napięcia na trasie do bagażnika
> (~4 m), nie z samego prądu.

> **Dlaczego nie z banku.** Szczyty 20–30 A przekroczyłyby przekaźnik LVD
> (20 A) — ZB §2.2. REM idzie z zapłonu: wzmacniacz ma grać, gdy jedziesz,
> a nie gdy komputer jest w S3.

> **Masa wzmacniacza osobno.** To jedyny obwód mocy, który **nie** idzie do
> punktu masy przy banku — wspólna masa z komputerem daje pętlę i przydźwięk
> alternatora. Masa krótka (do 1 m), do gołego metalu, tym samym przekrojem
> co „+”.

> **REM bez rezystora szeregowego.** Wejście REM gotowego wzmacniacza jest
> wysokoomowe (10–20 kΩ) i ma własne wyciszanie startu — rezystor 1 kΩ był
> potrzebny tylko przy płytce DIY.

---

## 3. Tabela połączeń — sygnały pojazdu

Wszystkie sygnały 12 V idą przez **PC817**. Stan aktywny to **LOW**.

### 3.1 Stopień PC817 (powtarzany dla każdego sygnału 12 V)

| Element | Połączenie |
|---------|------------|
| Sygnał 12 V z auta | → rezystor 4,7 kΩ → PC817 **pin 1** (anoda) |
| PC817 **pin 2** (katoda) | → masa pojazdu |
| PC817 **pin 4** (kolektor) | → pin Arduino (tryb `INPUT_PULLUP`) |
| PC817 **pin 3** (emiter) | → masa Arduino |

Rezystor podciągający jest wewnątrz mikrokontrolera — zewnętrznego 10 kΩ
nie trzeba. **Masa pojazdu i masa Arduino są tu rozdzielone** — na tym
polega izolacja.

### 3.2 Sygnały 12 V

| Sygnał | Skąd w aucie | Przez | Dokąd |
|--------|--------------|-------|-------|
| Zapłon / ACC | zamek kluczyka, poz. I/II | PC817 | Nano #2 **D9** |
| Kierunkowskaz lewy | wiązka tylnej lampy | PC817 | Nano #2 (wolny pin) |
| Kierunkowskaz prawy | wiązka tylnej lampy | PC817 | Nano #2 (wolny pin) |
| Bieg wsteczny | wyłącznik na skrzyni | PC817 | Nano #2 (wolny pin) |
| Podświetlenie | włącznik świateł | PC817 | Nano #2 (wolny pin) |

### 3.3 Styki zwierane do masy (bez PC817)

| Sygnał | Skąd | Dokąd |
|--------|------|-------|
| Drzwi przód lewe | wyłącznik oświetlenia wnętrza | Nano #2 **D2** |
| Drzwi przód prawe | j.w. | Nano #2 **D3** |
| Drzwi tył lewe | j.w. | Nano #2 **D4** |
| Drzwi tył prawe | j.w. | Nano #2 **D5** |
| Maska | wyłącznik maski | Nano #2 **D6** |
| Klapa bagażnika | wyłącznik klapy | Nano #2 **D7** |
| Hamulec ręczny | wyłącznik dźwigni | Nano #2 **D8** |

Wyłączniki OEM zwierają do masy — wpinaj je **wprost na pin**, bez
optoizolatora. Tryb `INPUT_PULLUP`, stan aktywny LOW.

### 3.4 Czujniki

| Czujnik | Dopasowanie | Dokąd |
|---------|-------------|-------|
| DS18B20 (temperatura) | 4,7 kΩ z DATA do 5 V | Nano #2 **D11** |
| Czujnik deszczu | wyjście cyfrowe DO modułu | Nano #2 **D10** |
| HC-SR04 TRIG (wspólny ×4) | wprost | Nano #2 **D12** |
| HC-SR04 ECHO ×4 | dzielnik 1 kΩ / 2 kΩ | Nano #2 **A0–A3** |
| LDR (jasność) | 5 V → LDR → węzeł → A1; węzeł → 10 kΩ → masa | Pro Micro **A1** |
| SWC Pod 1 | biały przewód dekodera | Pro Micro **A0** |
| SWC Pod 2 | biały przewód dekodera | Pro Micro **A6** = pad opisany **`4`** |

Dekoder SWC: **czerwony → ACC**, **czarny → masa**, **biały → wejście
analogowe**.

> **Na Pro Micro nie ma pola opisanego „A6" — szukasz pada `4`.** Na
> ATmega32U4 kanały ADC **A6–A11 są zmultipleksowane z pinami cyfrowymi**
> i na płytce drukowane są tylko numery cyfrowe. Opisane analogowo są
> wyłącznie A0–A3.
>
> | W kodzie | Pad na płytce | Port AVR |
> |----------|---------------|----------|
> | **A6** | **`4`** | PD4 / ADC8 |
> | A7 | `6` | PD7 / ADC10 |
> | A8 | `8` | PB4 / ADC11 |
> | A9 | `9` | PB5 / ADC12 |
> | A10 | `10` | PB6 / ADC13 |
>
> W sketchu zostaje `#define SWC_PIN2 A6` — nazwa `A6` służy tylko temu,
> żeby `analogRead()` wybrał właściwy kanał ADC. **A4 i A5 nie są
> wyprowadzone** na klasycznym Pro Micro.

### 3.5 K-Line (osobny tor, bez Arduino)

| Skąd | Dokąd | Uwagi |
|------|-------|-------|
| M910q, port USB | CP2102 | reguła udev → `/dev/ttyUSB_kline` |
| CP2102 **TX** | L9637D **pin 1** (TXD) | |
| CP2102 **RX** | L9637D **pin 2** (RXD) | |
| L9637D **pin 3** | masa | |
| L9637D **pin 4** | +5 V | kondensator 100 nF do masy, przy kostce |
| L9637D **pin 6** (EN) | +5 V | |
| L9637D **pin 8** (K-Line) | OBD-II **pin 7** | rezystor 510 Ω z linii K do +12 V |
| OBD-II **pin 4/5** | masa | |

---

## 4. Tabela połączeń — Arduino

Pełne tabele pinów: [`ARDUINO_SETUP_GUIDE.md`](ARDUINO_SETUP_GUIDE.md) § 7
i § 7b. Poniżej to, co dotyczy okablowania międzymodułowego.

### 4.1 Nano #1 (wyjścia — przekaźniki, PWM)

| Pin | Dokąd |
|-----|-------|
| D2 | RXB6 433 MHz **DATA** |
| D3 | HM-10 **RXD** |
| D4 | HM-10 **TXD** |
| D5 | Moduł przekaźników **IN1** (bagażnik) |
| D6 | przycisk bagażnika → masa |
| D7, D8 | **IN2, IN3** — szyba przód lewa góra/dół |
| D9 | panel główny 10,1" — **M_PWM** |
| D10 | panel drugi 6,86" — **M_PWM** |
| D11, D12 | **IN4, IN5** — szyba przód prawa |
| A0, A1 | **IN6, IN7** — szyba tył lewa |
| A2, A3 | **IN8, IN9** — szyba tył prawa |
| 5V, GND | buck LM2596 **OUT+/OUT−** |

> **HM-10 wygląda na odwrotnie opisany, ale jest poprawnie:** Nano **D3**
> idzie do HM-10 **RXD**, a HM-10 **TXD** wraca do Nano **D4**.

> **Wspólna masa z panelami wyświetlaczy jest obowiązkowa** — bez niej
> bramka MOSFET-a na `M_PWM` nie ma odniesienia i podświetlenie nie
> reaguje.

### 4.2 Pro Micro (wejścia — enkoder, SWC, zapłon)

| Pin | Dokąd |
|-----|-------|
| D2, D3 | enkoder **CLK**, **DT** (+10 kΩ do VCC) |
| D1 | przycisk enkodera → masa |
| D5–D9 | HOME, BACK, MEDIA, VOL+, VOL− → masa |
| D10, D14, D15, D16, A3 | panel muzyczny (PREV, NEXT, VOL+, VOL−, MUTE) |
| A0, A6 | SWC Pod 1, Pod 2 — **A6 to pad opisany `4`**, patrz §3.4 |
| A1 | LDR |
| A2 | przycisk na manetce |

> **v8.5.2:** przycisk enkodera przeniesiony z **D4 na D1** — na Pro Micro
> D4 i A6 to ten sam fizyczny pin (PD4 / ADC8) i kolidowało z SWC Pod 2.
> Przy starszym okablowaniu przepnij jeden przewód.

### 4.3 Nano #2 (sensor hub)

Patrz §3.3 i §3.4. Funkcje włącza się `#define FEATURE_*` na górze
`sensor_hub.ino` — wyłączony `FEATURE` zwalnia pin.

---

## 5. Tabela połączeń — USB, obraz, audio

### 5.1 Obraz

| Skąd | Dokąd | Uwagi |
|------|-------|-------|
| M910q, wyjście główne | wyświetlacz **10,1" 1280×800** + dotyk USB | dashboard, port 5002 |
| M910q, wyjście drugie | wyświetlacz **6,86" 1280×480** *(opcjonalny)* | statystyki, port 5003 |

> **Nazwy złączy sprawdź na swojej maszynie**, nie zakładaj z góry. Na
> referencyjnym M910q złącza enumerują się jako `HDMI-A-1` / `HDMI-A-2`
> (xrandr: `HDMI-1` / `HDMI-2`), a **główny panel wyszedł na złączu 2** —
> patrz komentarz w `config/scripts/bcm-splash-play.sh`. Jeżeli Twoja sztuka
> ma wyjścia DisplayPort, potrzebne będą pasywne przejściówki DP → HDMI.

Nazwy złączy sprawdź: `for f in /sys/class/drm/card*-*/status; do echo "$f: $(cat $f)"; done`

**Aktywne przejściówki nie są potrzebne** i bywają źródłem problemów
z wykryciem ekranu.

### 5.2 USB — bezpośrednio w port M910q

| Urządzenie | Dlaczego bezpośrednio |
|------------|----------------------|
| DAC ES9038Q2M | USB Audio Class 2 — hub dokłada opóźnienie i rywalizację o pasmo |
| Graber AHD 4-kanałowy | cztery strumienie 720p naraz potrzebują stałego pasma |

### 5.3 USB — przez hub (zasilany, 7 portów)

| Urządzenie | Port |
|------------|------|
| Arduino Pro Micro | `/dev/ttyACM0` |
| Arduino Nano #1 | `/dev/ttyUSB0` |
| Arduino Nano #2 | `/dev/ttyUSB1` |
| CP2102 (K-Line) | `/dev/ttyUSB_kline` |
| ESP32-S3 (wyświetlacz 1,8", § 11) | `/dev/ttyACM_display` |
| GPS u-blox NEO-M8N | — |
| Modem LTE Huawei E3372 | — |
| Mikrofon USB | — |
| Dotyk wyświetlacza głównego | — |

> **Hub musi mieć własne zasilanie** (z szyny buforowanej). Osiem urządzeń nie
> wyrobi się na prądzie z portu M910q.

> **Reguły udev są konieczne.** Bez nich numeracja `/dev/ttyUSBn` zmienia
> się między restartami i K-Line trafia na port Arduino.

### 5.4 Audio

| Skąd | Dokąd | Kabel |
|------|-------|-------|
| DAC **RCA L/R** | Wzmacniacz, wejścia RCA przód | RCA ekranowany |
| DAC **RCA L/R** | Wzmacniacz, wejścia RCA tył (rozgałęźnik Y) | RCA ekranowany |
| Wzmacniacz **CH1** | głośnik przód lewy (4 Ω) | 1,5 mm² |
| Wzmacniacz **CH2** | głośnik przód prawy | 1,5 mm² |
| Wzmacniacz **CH3** | głośnik tył lewy | 1,5 mm² |
| Wzmacniacz **CH4** | głośnik tył prawy | 1,5 mm² |

Zasilanie i REM — §2.6.

> **Kabel RCA prowadź po przeciwnej stronie auta niż kabel zasilania
> wzmacniacza.** Równoległy przebieg to najprostszy sposób na przydźwięk.

> **Pętla masy.** DAC ma masę przez USB i M910q (powrót 20 V idzie do punktu
> masy przy banku), wzmacniacz ma własną masę lokalną, a ekran RCA łączy oba
> punkty.
> Jeżeli słychać buczenie zmieniające się z obrotami silnika: najpierw popraw
> masę wzmacniacza, potem przetrasuj RCA, i dopiero na końcu sięgaj po
> izolator pętli masy — pogarsza pasmo.

**Ustawienie wzmocnienia:** głośność systemu ~75 %, EQ płasko, gain
wzmacniacza na minimum; podnoś do pierwszych zniekształceń i cofnij o krok.
Bez subwoofera włącz filtr górnoprzepustowy ok. 80 Hz na wszystkich kanałach.

### 5.5 Kamery

| Kanał | Miejsce | Wyzwalanie |
|-------|---------|-----------|
| CH0 | przód, za lusterkiem wstecznym | ręcznie / DVR |
| CH1 | tył, ramka tablicy rejestracyjnej | bieg wsteczny |
| CH2 | lewe lusterko / błotnik | lewy kierunkowskaz |
| CH3 | prawe lusterko / błotnik | prawy kierunkowskaz |

Priorytet: **bieg wsteczny > lewy kierunkowskaz > prawy kierunkowskaz >
brak**. Sygnały wyzwalające wchodzą przez PC817 na Nano #2.

---

## 6. Bezpieczniki — zestawienie

Pełna tabela z uzasadnieniem: ZB §8.1. Skrót:

| Oznaczenie | Wartość | Gdzie | Chroni |
|------------|---------|-------|--------|
| **F1** | 20 A, MIDI/AMI lub ANL | przy klemie „+”, ≤ 30 cm | ~5 m przewodu 6 mm² do ładowarek (biorą 11,9–13,0 A) |
| **FK** | 1 A ATO | z przodu, w miejscu wpięcia w zapłon / D+ | przewód 0,75 mm² do cewki K1 |
| **FC1, FC2** | 7,5 A ATO | przy OUT+ każdego XH-M603, przed złączeniem | płytki XH-M603 (≤ 8 A) od strony banku |
| **F12** | 15 A, MIDI/AMI lub ANL | przy bloku L+ | przewód ładowania 4 mm² od strony banku |
| **FB1…FB7** | 10 A ATO / mini | na „+” każdego pakietu, 5–10 cm od zacisku | zwarcie pojedynczego pakietu |
| **F7** | 20 A, MIDI/AMI lub ANL | przy bloku L+, przed XH-M609 VIN+ | moduł LVD i cała szyna za nim (~2,2 kA zwarciowo) |
| **F8** | 10 A | dystrybucja | wejście step-upu (do 6,6 A przy 11 V) |
| — | 5 A | wyjście step-upu, w bagażniku | przewód 20 V do M910q |
| **F9** | 2 A | dystrybucja | LM2596 — wyświetlacze |
| **F10** | 3 A | dystrybucja | MP1584 — logika, Arduino |
| **F11** | 5 A | dystrybucja | AUX 12 V: moduł przekaźników, hub USB |
| **F13** | 2 A (opcja) | dystrybucja | wstrzykiwacz 5 V telefonu |
| — | 1 A | przy banku | przewód pomiaru napięcia banku |
| — | 2 A | odgałęzienie +15 → buck 5 V wyświetlacza ESP32 | moduł wyświetlacza 1,8" (§ 11.3) |
| — | wg karty modułu (20–30 A), klasa jak F1 | przy klemie „+”, osobno | gałąź wzmacniacza |

Wkładki za LVD (F8–F11, F13) i FC1/FC2 mogą być zwykłymi ATO — prąd
zwarciowy ogranicza tam rezystancja przewodów i przekaźnika LVD (ZB §8.1).
**F7 i F12 widzą pełne ~2,2 kA banku** i muszą mieć zdolność wyłączania
≥ 2,5 kA wg karty. **F1** (i gałąź wzmacniacza) przy klemie rozruchowego
widzi szacunkowo 1,2–2,5 kA — ta sama klasa (ZB §8.1). Wszystkie odgałęzienia biegnące do przodu mają wkładki
**w bagażniku**, na początku trasy; wyjątek to FK, bo jego przewód biegnie
w drugą stronę.

---

## 7. Masy

**Jeden punkt masy** dla całego head unitu — **w bagażniku, przy banku**
(ZB §8.3):

- punkt masy to **osobny blok masowy** tuż obok banku, a z niego **jeden**
  przewód 6 mm² do karoserii; śruba do gołego metalu,
  oczyszczonego ze szpachli i lakieru, zabezpieczona wazeliną techniczną —
  **nie** w podłodze nad zbiornikiem paliwa (ZB §4.7),
- blok P− banku dochodzi do niego **wyłącznie przez rozłącznik S1 100 A**
  (przewód 17). Z S1 w torze **nie używaj P− jako punktu masy** i nie
  dawaj żadnego bezpośredniego mostka P− → blok masowy: każda masa
  wylądowana na P− albo taki mostek omija S1 i po jego otwarciu wszystkie
  odbiorniki dalej wiszą na banku — S1 nic by nie odcinał (ZB §8.3 mówi
  „blok P− albo blok obok spięty z P−" — to opis sprzed S1; przy S1
  obowiązuje osobny blok, zgodnie z §8.4 ZB),
- schodzą się w nim: masa banku (z P− przez S1), masy obu
  XY-SK120 (wejście i wyjście to jeden zacisk) i obu XH-M603, LVD,
  dystrybucja, step-up, powrót 20 V z M910q, wspólny powrót 12 V z przodu
  (2,5 mm²) i masa audio,
- M910q, panele i moduły z przodu **nie dostają własnej masy do
  karoserii**; jeżeli obudowa M910q dotyka metalu, to druga droga masy —
  przy przydźwięku sprawdź to pierwsze.

**Dwa wyjątki:**

1. **Masa wzmacniacza** — osobno, blisko wzmacniacza. Wspólna z komputerem
   daje pętlę masy i przydźwięk alternatora.
2. **Masa pojazdu po stronie PC817** — celowo odizolowana od masy Arduino.
   To sens optoizolacji.

---

## 8. Kolejność montażu

```
0. Rozplanuj strefy montażu wg vehicle_layout_m910q.svg — zanim cokolwiek wywiercisz
1. Kosze przykręcone do grodzi (8 × M8, ZB §4.7) — PODŁOGI NIE WIERCISZ
2. Punkt masy przy banku — przygotuj i sprawdź omomierzem (< 0,5 Ω do klemy „−”)
3. Trasy przewodów — peszel, przelotki gumowe w każdej blasze, łącznik
   między koszami pod osłoną
4. Dystrybucja (listwa albo płytka B) — zamontowana, dostępna, BEZ wkładek
5. Moduły zasilania — wszystkie zaciski dokręcone, BEZ zasilania
6. Bank — siedem pakietów zmierzonych osobno i wyrównanych, bloki L+/L−/P+/P−
   z pokrywami, odcinki równej długości, FB1…FB7 10 A założone
7. Rozłącznik masy banku S1 w pozycji ROZWARTY
8. Nastawy modułów na stole (ZB § 11 etap 1)
9. Bezpiecznik F1 20 A — wkładany JAKO OSTATNI
```

**Zasada:** każdy etap kończy się pomiarem. Podłączenie wszystkiego naraz
i szukanie potem, co nie działa, kosztuje wielokrotnie więcej czasu niż
sprawdzanie po jednym obwodzie.

To samo dotyczy Arduino: wgraj firmware i sprawdź każdą płytkę przez
`picocom` **na stole**, zanim podłączysz cokolwiek z auta.

---

## 9. Lista kontrolna przed pierwszym załączeniem

```
[ ] Bezpiecznik F1 20 A WYJĘTY
[ ] Rozłącznik masy banku S1 ROZWARTY
[ ] Polaryzacja na wtyku M910q sprawdzona multimetrem (środek „+”)
[ ] Step-up: bez obciążenia 19,9–20,5 V; test ~60 W i przy 11,0 V wejścia
    zaliczony; prąd jałowy zapisany (ZB §3.4)
[ ] XY-SK120 × 2: CV 14,40 V (±0,02 V między modułami), CC 5,0 A
    sprawdzone amperomierzem, OVP 15,0 V, wyjście po włączeniu: ON
[ ] XH-M603 × 2: 15,30 V / 14,00 V, sprawdzone zasilaczem lab.; test
    „12,6 V tylko na OUT” zaliczony (ZB §6.4 pkt 6)
[ ] XH-M609: 11,00 V / 12,60 V, sprawdzony zasilaczem laboratoryjnym
[ ] XH-M609: potwierdzone, że przełącza plus, i zmierzony pobór własny
[ ] Buck logiki MP1584: 5,0 V na wyjściu (zmierzone, nie „powinno być”)
[ ] Buck wyświetlaczy LM2596: napięcie wg panelu
[ ] Dioda 1N4007 na cewce K1 — katoda do 86
[ ] TVS SMCJ20CA i kondensator 470 µF przed K1 zamontowane
[ ] FC1/FC2 7,5 A przy OUT+ XH-M603; F12 15 A i F7 20 A (MIDI/ANL) przy L+
[ ] Wszystkie siedem pakietów zmierzone osobno, rozrzut < 0,2 V
[ ] Bezpieczniki FB1…FB7 10 A na każdym pakiecie, 5–10 cm od zacisku
[ ] Odbiór po przekątnej: „+” z bloku L+, „−” z bloku P−
[ ] Odcinki pakietów równej długości (±30 mm), bloki pod pokrywami
[ ] Wszystkie zaciski dokręcone i pociągnięte ręką
[ ] Masa: < 0,5 Ω między punktem masy a klemą „−” akumulatora
[ ] Żaden przewód nie ociera o krawędź blachy ani o belkę dociskową kosza
[ ] Nic z instalacji 12 V nie idzie bezpośrednio na pin Arduino
```

Po odhaczeniu całości przejdź do procedury pomiarowej:
ZB § 11, etap 4.

---

## 10. Tabela połączeń — wariant testowo-rozwojowy

Ten rozdział dotyczy **wyłącznie** wariantu z
[`WDROZENIE_TESTOWE.md`](WDROZENIE_TESTOWE.md): mniej modułów, mniej okablowania,
M910q zasilany stale. Tabele §2–§5 opisują wersję docelową i tutaj **nie
obowiązują**.

> **Auto testowe dziś jeździ bez bufora** — M910q i telefon tracą zasilanie
> przy każdym zgaszeniu silnika ([`WDROZENIE_TESTOWE.md`](WDROZENIE_TESTOWE.md)
> §3). Poniższe tabele opisują tor buforowany, który ma to zmienić: ten sam
> co w ZB (step-up 20 V, 2 × XY-SK120, 2 × XH-M603, bank 7 × HR1221W
> w koszach 4 + 3), tylko bez logiki domeny stałej, wzmacniacza i drugiego
> ekranu.

**Rysunki — zacznij od tych dwóch.** Każdy element jest na nich narysowany
osobno: TVS i C1 to nie jeden bloczek, tylko dwa symbole z własnymi
połączeniami; cewka i styk K1 są rozdzielone (to jeden przekaźnik,
narysowany w dwóch miejscach).

| Arkusz | Zakres |
|--------|--------|
| [`../schematics/schematic_test_power.svg`](../schematics/schematic_test_power.svg) | **1/2 — zasilanie.** Tor ładowania z dwiema XY-SK120, bank w dwóch koszach z bezpiecznikami pakietów, LVD, rozłącznik masy, trzy przetwornice. Numery przewodów jak w tabelach niżej. |
| [`../schematics/schematic_test_signals.svg`](../schematics/schematic_test_signals.svg) | **2/2 — sygnały.** Oba transoptory, Arduino Nano, moduł przekaźnika, przycisk M910q, rozdział mas. |

Generator obu: [`../schematics/gen_test_schematics.py`](../schematics/gen_test_schematics.py)
— po zmianie tabel popraw generator i wygeneruj SVG ponownie, nie edytuj ich ręcznie.

Uzupełniająco: [`ignition_sense.svg`](../schematics/ignition_sense.svg)
(przebiegi czasowe uśpienia i wybudzania). Rysunki
[`schematic_test_build.svg`](../schematics/schematic_test_build.svg) i
[`wiring_test_build.svg`](../schematics/wiring_test_build.svg) pokazują
jeszcze **poprzedni** tor (boost z diodą, XL6019) i czekają na
przerysowanie — przy rozbieżności obowiązują tabele niżej
([`../schematics/README.md`](../schematics/README.md)).

### 10.1 Tor ładowania

> **Wariant PCB.** Przewody 3, 5 i 5a oraz TVS, C1, K1 i D6 mogą siedzieć na
> trawionej płytce A — wtedy łączysz zaciski X1, X2 i X6 wg
> [`PCB_ZASILANIE.md`](PCB_ZASILANIE.md) §1.

| # | Skąd | Dokąd | Przewód | Zabezpieczenie |
|---|------|-------|---------|----------------|
| 1 | Akumulator rozruchowy **„+”** | Bezpiecznik **F1** (wejście) | 6 mm² | — |
| 2 | **F1** (wyjście) | **TVS + C1**, biegun „+” | 6 mm², ~5 m | **20 A** (MIDI/ANL), ≤ 30 cm od klemy |
| 3 | **TVS + C1** „+” | Przekaźnik **K1**, zacisk **30** | 6 mm² | — |
| 4 | Zapłon albo **D+** alternatora | **K1** zacisk **86** | 0,75 mm² | **FK 1 A** przy wpięciu |
| 5 | **K1** zacisk **87** | **XY-SK120 #1** (M1a) **IN+** | 2,5 mm² | — |
| 5a | **K1** zacisk **87** | **XY-SK120 #2** (M1b) **IN+** | 2,5 mm² | — |
| 6 / 6a | M1a / M1b **OUT+** | **XH-M603 #1 / #2** (M2a / M2b) **DC-IN+** | 2,5 mm² | — |
| 7 / 7a | M2a / M2b **OUT+** | złączenie gałęzi | 2,5 mm², obie równe | **FC1 / FC2 7,5 A** przy OUT+ |
| **B** | złączenie | **blok L+** banku | **4 mm²** | **F12 15 A** (MIDI/ANL) przy bloku |

Nastawy i powody: §2.1 wyżej i ZB §5. Masy tego toru (K1 zacisk 85, „−”
TVS/C1, IN−/OUT− obu XY-SK120, DC-IN− obu XH-M603) idą do punktu masy przy
banku — §10.6.

> **Dioda 1N4007** równolegle do cewki K1 (zaciski 85–86), katodą do „+”.
> Bez niej impuls samoindukcji cewki wraca w instalację przy każdym
> zgaszeniu silnika.

#### Kierunki diod — sprawdź przed lutowaniem

| Element | Kierunek |
|---------|----------|
| **D5** — TVS SMCJ20**CA** | **bez znaczenia.** Sufiks „CA" = dwukierunkowa: nie ma anody ani katody, pasek na obudowie (jeśli w ogóle jest) nic nie znaczy |
| **D6** — 1N4007 | **pasek = katoda** → na zacisk **86** cewki, czyli po stronie plusa |

> **Pułapka przy zakupie TVS.** **SMCJ20A** (bez „C") to inna dioda —
> jednokierunkowa — i tam pasek musi iść na plus. Odwrotnie wlutowana jest
> zwarciem ~1 V na zasilaniu i **F1 idzie natychmiast**. Rozpoznasz miernikiem
> w trybie testu diody: **dwukierunkowa daje OL w obie strony**,
> jednokierunkowa ~0,7 V w jedną. Uzasadnienie: ZB §5.8.

### 10.2 Bank, LVD, rozłącznik masy

| # | Skąd | Dokąd | Przewód | Zabezpieczenie |
|---|------|-------|---------|----------------|
| — | „+” pakietów #1…#4 / #5…#7 | bloki **L+** / **P+** | FLRY-B 2,5 mm², 0,25 m ±30 mm | **FB1…FB7** 10 A, osobno na pakiet |
| — | „−” pakietów #1…#4 / #5…#7 | bloki **L−** / **P−** | FLRY-B 2,5 mm², ta sama długość | — |
| — | L+ ↔ P+, L− ↔ P− | łączniki między koszami | 6 mm² OFC, 0,4–0,6 m, obie żyły równe | — |
| 8 | blok **L+** | **XH-M609 VIN+** | 6 mm² | **F7** 20 A (MIDI/AMI lub ANL) |
| 9 | blok **P−** | **S1** rozłącznik masy 100 A → punkt masy | 6 mm² | — |
| 10 | **XH-M609 VOUT+** | szyna odbiorników | 4 mm² | — |

Nasuwki **F2 6,35 mm** w pełni izolowane, zaciskane zaciskarką zapadkową,
kapturki na biegunach. Odbiór po przekątnej: „+” z L+, „−” z P− — §2.2
i ZB §4.3.

### 10.3 Odbiorniki — zasilane stale

| # | Skąd | Dokąd | Przewód | Zabezpieczenie |
|---|------|-------|---------|----------------|
| 11 | szyna odbiorników | **step-up 20 V IN+** (M4) | 4 mm² | **F8** 10 A |
| 12 | **step-up OUT+** / **OUT−** | Wtyk M910q: środek „+”, ekran „−” | 4 mm² | 5 A przy wyjściu przetwornicy |
| 13 | szyna odbiorników | **LM2596 IN+** | 1,5 mm² | **F9** 2 A |
| 14 | **LM2596 OUT+** / **OUT−** | Panel 7", złącze **PWM+** / **GND** | 1,5 mm² | — |
| 13a | szyna odbiorników | **MP1584 IN+** (M6 — logika, Nano; wyjście = przewód 25, §10.5) | 0,75 mm² | **F10** 3 A |

> **F8 to 10 A.** Pełne 65 W na wtyku M910q przy wejściu 11,0 V to
> ok. 6,6 A z szyny (ZB §3.2) — 66 % wkładki. Z tą przetwornicą limit
> poboru CPU (RAPL) nie jest potrzebny.

**Logika panelu i dotyk zostają na USB M910q** — osobno idzie wyłącznie
podświetlenie. Panel ma jeden kabel USB do komputera i jedno złącze
zasilania podświetlenia.

### 10.4 Wejścia optoizolowane — zapłon i bieg wsteczny

Rysunek: [`../schematics/schematic_test_signals.svg`](../schematics/schematic_test_signals.svg).
Przebiegi czasowe: [`../schematics/ignition_sense.svg`](../schematics/ignition_sense.svg).

**Płytką jest Arduino Nano** z `arduino/sensor_hub/sensor_hub.ino` — nie Pro
Micro. Pro Micro obsługuje SWC, enkoder i przyciski i do tej części nie jest
potrzebne. Piny poniżej odpowiadają `PIN_IGN 9` i `PIN_PWR_RELAY A0`
z firmware'u.

| # | Skąd | Dokąd | Przewód |
|---|------|-------|---------|
| 15 | Zapłon / ACC **12 V** | **R1** 2,2 kΩ / 0,25 W → **U1 (PC817)** pin **1** | 0,5 mm² |
| 16 | **U1** pin **2** | **Masa instalacji auta** — NIE punkt masy przy banku | 0,5 mm² |
| 17 | **U1** pin **4** | Nano **D9** | 0,5 mm² |
| 18 | **U1** pin **3** | Nano **GND** | 0,5 mm² |
| 20 | Nano **D9** | **C3** 100 nF → Nano **GND** | 0,5 mm² |
| 15a | Światło cofania **12 V** | **R3** 2,2 kΩ / 0,25 W → **U2 (PC817)** pin **1** | 0,5 mm² |
| 16a | **U2** pin **2** | **Masa instalacji auta** — wspólnie z przewodem 16 | 0,5 mm² |
| 17a | **U2** pin **4** | Nano **D10** | 0,5 mm² |
| 18a | **U2** pin **3** | Nano **GND** | 0,5 mm² |
| 20a | Nano **D10** | **C4** 100 nF → Nano **GND** | 0,5 mm² |

Rezystory podciągające są zbędne — oba wejścia pracują jako `INPUT_PULLUP`.

> **Wejście biegu wstecznego wymaga jeszcze zmiany w firmwarze.** Sketch ma
> dziś `FEATURE_IGN` i `FEATURE_PWRBTN`, nie ma `FEATURE_REV`. Sam układ
> wejściowy jest kopią zapłonu, więc okablowanie możesz zrobić od razu.
> Sygnał bierz z obwodu świateł cofania — czujnik na skrzyni podaje 12 V,
> a lampa jest w tej samej kloszy, obok której i tak biegnie kabel kamery.

> **Przewody 16/16a i 18/18a celowo idą do różnych mas.** Na tym polega
> optoizolacja: po jednej stronie PC817 jest masa auta, po drugiej masa
> Arduino. Zwarcie ich niweczy cały sens układu i wpuszcza do komputera
> wszystko, co jeździ po linii ACC.

### 10.5 Sterowanie przyciskiem zasilania M910q

Arduino nie wysyła żadnego protokołu — po prostu **zwiera przycisk
zasilania**, a resztę robi acpid, który jest już skonfigurowany
(§7.3 [`WDROZENIE_M910Q.md`](WDROZENIE_M910Q.md)).

| # | Skąd | Dokąd | Przewód |
|---|------|-------|---------|
| 21 | Nano **A0** | Moduł przekaźnika **IN** | 0,5 mm² |
| 22 | Nano **5 V** / **GND** | Moduł przekaźnika **VCC** / **GND** | 0,5 mm² |
| 23 | Przekaźnik **COM** | Przycisk zasilania M910q, zacisk 1 | 0,5 mm² |
| 24 | Przekaźnik **NO** | Przycisk zasilania M910q, zacisk 2 | 0,5 mm² |
| 25 | **MP1584 OUT+** / **OUT−** | Nano **5 V** / **GND** | 0,75 mm² |

Styki przekaźnika idą **równolegle** do przycisku — przycisk dalej działa
normalnie i zostaje ratunkiem awaryjnym.

| Impuls na A0 | Efekt |
|--------------|-------|
| **250 ms** przy pracy | uśpienie do S3 |
| **250 ms** w S3 | wybudzenie w ~3 s |
| **250 ms** po wyłączeniu | start (zimny, ~40 s) |
| **5 s** | twarde wyłączenie — pobór spada do 50–150 mA + prąd jałowy step-upu (ZB §2.1) |

> **Przetnij żyłę VBUS (czerwoną) w kablu USB do Nano.** Płytka jest
> zasilana z MP1584 (przewód 25) i musi żyć, gdy M910q śpi — a wtedy port USB
> jest martwy. Dwa źródła 5 V zwarte razem to niepotrzebne ryzyko; dane po USB
> działają bez VBUS.

> **Zaciski przycisku znajdź miernikiem** w trybie ciągłości, przy maszynie
> odłączonej od zasilania: rozwarte, zwarte przy wciśnięciu.

### 10.6 Punkt masy przy banku

Punkt masy to **osobny blok masowy**, nie blok P− — P− łączy się z nim
tylko przez S1 (§7). Lądują na nim: „−” TVS/C1, zacisk **85** K1, **IN−/OUT−** obu XY-SK120
(jeden zacisk — brak izolacji), **DC-IN−** obu XH-M603, blok **P−** banku
przez **S1**, **VIN−** modułu XH-M609, **IN−** przetwornic step-up, LM2596
i MP1584. „−” akumulatora rozruchowego łączy się z nim przez nadwozie —
osobnego przewodu masy z ładowarek do klemy „−” **nie ma** (ZB §5.6).

**Jedyny wyjątek:** masa wejść optoizolowanych (**U1 pin 2** i **U2 pin 2**,
przewody 16 i 16a) idzie do masy instalacji auta.

### 10.7 Kolejność podłączania

```
1. S1 rozwarty, bank odłączony, F1 wyjęty z oprawki.
2. Nastawy i testy na stole (ZB §11 Etap 1):
   step-up 19,9–20,5 V bez obciążenia, test ~60 W i przy 11,0 V ·
   LM2596 wg panelu · 2 × XY-SK120 CV 14,40 V / CC 5,0 A ·
   2 × XH-M603 15,30 / 14,00 V (i test „12,6 V tylko na OUT”) ·
   XH-M609 11,00 / 12,60 V
3. Punkt masy przy banku — komplet z §10.6.
4. Bank (7 pakietów) w koszach, bloki L+/L−/P+/P−, FB1…FB7, łączniki,
   pomiar napięcia na L+/P−. Odbiór po przekątnej — ZB §4.3.
5. Przewody 8, 9, 10 — bank przez F7 do LVD, P− przez S1 do masy.
6. Przewody 11 i 12 — step-up. POMIAR 19,9–20,5 V BEZ podłączonego M910q.
7. Dopiero teraz M910q, potem 13–14 (podświetlenie) oraz 13a i 25
   (MP1584 → Nano; POMIAR 5,0 V na wyjściu przed podłączeniem Nano).
8. Na końcu przewody 1–7a i B — tor ładowania, przy zgaszonym silniku.
9. Rozruch silnika, pomiar prądu ładowania cęgami lub bocznikiem
   (ok. 10 A przy F12, ok. 5–7 A netto do banku w wariancie testowym —
   WDROZENIE_TESTOWE §3.3; ZB §11 Etap 5).
```

Punkt 6 pomijany „bo przecież sprawdzałem na biurku" to najczęstszy sposób
na zabicie płyty głównej. Punkt 8 pomijany — na zabicie banku.

---

## 11. Wyświetlacz pomocniczy 1,8" na ESP32

Rysunek: [`esp32_display_wiring.svg`](../schematics/esp32_display_wiring.svg)
(generator `schematics/gen_esp32_display.py` — po zmianie tabel poniżej popraw
generator i wygeneruj SVG ponownie, nie edytuj SVG ręcznie). Projekt ekranów,
protokół i budżet poboru: [`WYSWIETLACZ_ESP32_1V8.md`](WYSWIETLACZ_ESP32_1V8.md).

> **Oznaczenia elementów (U1–U10, D1, F12, M8, A5, DS3) należą do tego
> podukładu.** Arkusze wariantu testowego (§ 10) mają własną numerację —
> tamtejsze `U1`/`U2` to transoptory zapłonu i biegu wstecznego. **F12**
> w [`ZASILANIE_BUFOROWANE.md`](ZASILANIE_BUFOROWANE.md) §8.1 to inny
> element: bezpiecznik przewodu ładowania przy bloku L+ banku.

Panel **ST7735 128 × 160 px zamontowany pionowo**, sterowany z **ESP32-S3**.
Dwa niezależne źródła danych: dziesięć sygnałów 12 V wprost z auta (przez
PC817) oraz metadane muzyki i tempomatu z M910q po USB. Dzięki temu ekran
otwartego nadwozia działa także wtedy, gdy komputer jeszcze wstaje albo już śpi.

### 11.1 Dziesięć wejść 12 V przez PC817

Stopień wejściowy jest **identyczny dla wszystkich dziesięciu sygnałów** i jest
już opisany w § 3.1 (sygnał → 4,7 kΩ → PC817 pin 1, pin 2 → masa pojazdu,
pin 4 → GPIO w `INPUT_PULLUP`, pin 3 → masa ESP32). Zmienia się wyłącznie pin
docelowy:

| Oznaczenie | Sygnał | Skąd w aucie | Pin ESP32-S3 | Ekran |
|------------|--------|--------------|--------------|-------|
| U1 | ABS | złącze fabrycznego wyświetlacza | **GPIO4** | 1 |
| U2 | Hamulec ręczny | wyłącznik dźwigni | **GPIO5** | 1 |
| U3 | Poduszka (SRS) | złącze fabrycznego wyświetlacza | **GPIO6** | 1 |
| U4 | Immobilizer | złącze fabrycznego wyświetlacza | **GPIO7** | 1 |
| U5 | Maska | wyłącznik maski | **GPIO1** | 2 |
| U6 | Drzwi przód lewe | krańcówka oświetlenia wnętrza | **GPIO15** | 2 |
| U7 | Drzwi przód prawe | j.w. | **GPIO16** | 2 |
| U8 | Drzwi tył lewe | j.w. | **GPIO17** | 2 |
| U9 | Drzwi tył prawe | j.w. | **GPIO18** | 2 |
| U10 | Klapa bagażnika | wyłącznik klapy | **GPIO2** | 2 |

Kolejność U1–U10 jest **kontraktem firmware'u** — odpowiada wyliczeniu
`InputId` w `arduino/esp32_display/state.h` oraz tablicom `TELLTALES[]`
i `PANELS[]` w `arduino/esp32_display/assets.h`. Stan aktywny to **LOW**,
debounce **30 ms**.

> **GPIO ESP32-S3 są 3,3 V i nie tolerują nawet 5 V**, o 12 V nie wspominając,
> a instalacja samochodowa potrafi wypuścić impulsy grubo powyżej 40 V.
> Optoizolacja z § 3.1 jest obowiązkowa, a każde wejście zasługuje dodatkowo
> na **TVS (SMBJ24A) po stronie pojazdu**, przed rezystorem 4,7 kΩ.

> **Polaryzacji nie zakładaj — zmierz.** Krańcówki drzwi w autach tej epoki
> zwykle **zwierają do masy** (12 V przy zamkniętych, 0 V przy otwartych),
> czyli działają odwrotnie niż sterowana plusem lampka. Linia zwierana do masy
> nie potrzebuje PC817 — wchodzi wprost na pin, tak jak w § 3.3. Dla każdego
> z dziesięciu sygnałów sprawdź miernikiem: napięcie w spoczynku, w stanie
> aktywnym i czy linia źródłuje prąd, czy go zwiera.

> **ABS i poduszka to dwie najmniej pewne pozycje** — w wielu wersjach rysują
> je zegary z własnej magistrali i nie podają dalej na złącze. Jeśli ich tam
> nie ma, zostaje wzięcie ich z BCM albo rezygnacja z tych dwóch lampek.

### 11.2 Panel ST7735 po SPI

| ESP32-S3 | Panel ST7735 | Uwagi |
|----------|--------------|-------|
| **GPIO12** | SCL / SCK | zegar SPI |
| **GPIO11** | SDA / MOSI | dane |
| **GPIO10** | CS | wybór układu |
| **GPIO13** | DC / A0 | dane ↔ komenda |
| **GPIO14** | RST / RES | reset panelu |
| **GPIO21** | BLK / LED | podświetlenie, PWM przez LEDC |
| **3V3** | VCC | moduł ze stabilizatorem AMS1117 zasilaj 5 V |
| **GND** | GND | masa ESP32 — nie masa pojazdu |

Kolejność pinów **na module bywa różna** (najczęściej LED, SCK, SDA, A0, RESET,
CS, GND, VCC) — czytaj opisy na płytce, nie kolejność z tabeli. Część modułów
ma BLK zwarty do VCC; wtedy ściemnianie wymaga przecięcia ścieżki albo małego
tranzystora. Sygnały sterujące zawsze 3,3 V, także na module 5-woltowym.

W `TFT_eSPI` panel opisuje `User_Setup` z `ST7735_DRIVER`, `TFT_WIDTH 128`,
`TFT_HEIGHT 160` i powyższymi pinami; obrót do pionu robi firmware.

### 11.3 Zasilanie i USB

| Skąd | Dokąd | Uwagi |
|------|-------|-------|
| **+15** (po zapłonie), listwa ATO — *albo* szyna buforowana za LVD | bezpiecznik **2 A** | § 6; wybór źródła jest otwarty — patrz ramka niżej |
| bezpiecznik 2 A | buck 12 V → 5 V, **IN+** | MP1584, jak M6 w § 10 |
| buck **IN−** | punkt masy | § 7 |
| buck **OUT+** | ESP32-S3 **5V** | ~60 mA z 12 V przy pracy |
| buck **OUT−** | ESP32-S3 **GND** + punkt masy | |
| ESP32-S3, **natywne** gniazdo USB-C | port USB M910q (przez hub, § 5.3) | `/dev/ttyACM_display` |

> **Żyła VBUS w kablu USB musi być przecięta**, jeśli moduł ma własne
> zasilanie. Dwa źródła 5 V — buck i port M910q — nie mogą pracować na jedną
> szynę. Masa (GND) w kablu **zostaje połączona**: bez wspólnego punktu
> odniesienia transmisja nie ma sensu.

> **Skąd wziąć te 12 V — decyzja otwarta.** W wariancie testowym **+15**
> zeruje pobór na postoju i tak jest tu narysowane. W wersji **docelowej**
> zapłon nie jest już źródłem zasilania, tylko sygnałem
> ([`ZASILANIE_BUFOROWANE.md`](ZASILANIE_BUFOROWANE.md) §2), więc panel
> powinien wisieć na **szynie buforowanej za LVD** (S1 odcina masę banku). Przy banku siedmiu
> pakietów (35,7 Ah) kosztuje to 24–43 % czasu postoju: 5,3–3,0 dnia zamiast
> 9,3–4,0. Rachunek i warunki:
> [`WYSWIETLACZ_ESP32_1V8.md`](WYSWIETLACZ_ESP32_1V8.md), sekcja „Czy można
> wpiąć na stałe do akumulatora", wariant 4. Elektrycznie zmienia się tylko
> to, do którego zacisku podpinasz wejście bucka.

> **Na płytkach z dwoma gniazdami USB-C** jedno idzie do natywnego USB
> ESP32-S3, a drugie do mostka UART (CH343/CP2102). Protokół chodzi po
> **natywnym** — to ono zgłasza się jako `303a:1001` i to jego łapie reguła
> udev `config/udev/99-bcm-esp32-display.rules`.

Wariant alternatywny — zasilanie **wprost z USB**, bez bucka i bezpiecznika:
jeden kabel, zero poboru na postoju, ale ekran wstaje dopiero razem z M910q,
więc kontrolki bezpieczeństwa pojawiają się z opóźnieniem całego bootu.
Porównanie obu: [`WYSWIETLACZ_ESP32_1V8.md`](WYSWIETLACZ_ESP32_1V8.md)
§ Zasilanie i pobór.

### 11.4 Piny, których nie wolno użyć

| Piny | Dlaczego |
|------|----------|
| 0, 3, 45, 46 | strapping — stan przy resecie decyduje o trybie startu |
| 19, 20 | natywne USB (D−/D+), czyli cały protokół z BCM |
| 26–37 | flash i PSRAM modułu (N16R8) |

Pozostałe wolne piny są do dyspozycji, ale zestaw z § 11.1 i § 11.2 jest
kontraktem — te same numery siedzą w firmwarze i w generatorze schematu.

---

## Powiązane dokumenty

| Dokument | Zakres |
|----------|--------|
| [`ZASILANIE_BUFOROWANE.md`](ZASILANIE_BUFOROWANE.md) | dobór podzespołów, nastawy, lista zakupowa, procedura rozruchu |
| [`WDROZENIE_M910Q.md`](WDROZENIE_M910Q.md) | pełne wdrożenie: sprzęt, BIOS, OS, usługi, odbiór |
| [`ARDUINO_SETUP_GUIDE.md`](ARDUINO_SETUP_GUIDE.md) | wgrywanie firmware, kalibracja SWC, pełne tabele pinów |
| [`KLINE_SNIFFING.md`](KLINE_SNIFFING.md) | podsłuch K-Line, poznawanie PID-ów ECU |
| [`WYSWIETLACZ_ESP32_1V8.md`](WYSWIETLACZ_ESP32_1V8.md) | wyświetlacz pomocniczy 1,8": ekrany, protokół, firmware, pobór |
| [`../schematics/README.md`](../schematics/README.md) | indeks wszystkich schematów |
