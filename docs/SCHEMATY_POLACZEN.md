# Schematy połączeniowe — jak to pospiąć w całość

Praktyczny przewodnik montażowy: co z czym połączyć, jakim przewodem, przez
jaki bezpiecznik i w jakiej kolejności. Uzupełnia schematy blokowe
(architektura) o poziom **zacisk po zacisku**.

| Rysunek | Co pokazuje |
|---------|-------------|
| [`wiring_power_modules.svg`](../schematics/wiring_power_modules.svg) | Moduły zasilania — każdy zacisk podpisany, przekroje, bezpieczniki, masy |
| [`wiring_vehicle_arduino.svg`](../schematics/wiring_vehicle_arduino.svg) | Sygnały pojazdu → układy dopasowujące (PC817, dzielniki) → Arduino |
| [`wiring_usb_av.svg`](../schematics/wiring_usb_av.svg) | USB, wyświetlacze, audio, kamery |
| [`vehicle_layout_m910q.svg`](../schematics/vehicle_layout_m910q.svg) | Rozmieszczenie w aucie — strefy montażu, trasy kablowe, bilans masy |

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
| +12 V stałe (przed LVD) | czerwony |
| +12 V buforowane (za LVD) | czerwono-biały |
| +12 V odbiorników (za wyłącznikiem głównym) | pomarańczowy |
| +5 V | żółty |
| +19 V do M910q | brązowy |
| Masa | czarny |
| Sygnały do Arduino | szary / niebieski |
| ACC (sterowanie) | zielony |

### Zaciski na rysunkach

Zaciski są narysowane **na krawędziach obudów** i ponumerowane. Numery
w tabelach poniżej odpowiadają numerom na
[`wiring_power_modules.svg`](../schematics/wiring_power_modules.svg).

---

## 2. Tabela połączeń — zasilanie

### 2.1 Tor główny (od auta do banku)

| # | Skąd | Dokąd | Przewód | Zabezpieczenie |
|---|------|-------|---------|----------------|
| 1 | Akumulator „+” | Bezpiecznik główny (wejście) | 6 mm² | — |
| 2 | Bezpiecznik główny (wyjście) | Przekaźnik ładowania **30** | 6 mm² | 30 A, ≤ 30 cm od klemy |
| 3 | Przekaźnik ładowania **87** | Dioda MBR2545CT — anody (1 + 3) | 6 mm² | — |
| 4 | Dioda MBR2545CT — katoda (2 / blaszka) | Ładowarka **IN +** (zacisk 1) | 6 mm² | blaszka pod potencjałem katody — izoluj od masy |
| 5 | Ładowarka **IN −** (2) | punkt gwiazdowy masy | 6 mm² | — |
| 6 | Ładowarka **OUT +** (3) | Blokada przeładowania **COM** (7) | 2,5 mm² | — |
| 7 | Ładowarka **OUT −** (4) | punkt gwiazdowy masy | 2,5 mm² | — |
| 8 | Blokada **NC** (8) | szyna „+” banku | 2,5 mm² | — |
| 9 | Blokada **VCC** (5) | szyna „+” banku (pomiar) | 0,75 mm² | 2 A |
| 10 | Blokada **GND** (6) | punkt gwiazdowy masy | 0,75 mm² | — |

**Ochrona wejścia ładowarki** — montowana bezpośrednio na zaciskach IN+/IN−:
dioda TVS 1.5KE33CA równolegle oraz kondensator 470 µF / 35 V równolegle.

### 2.2 Bank akumulatorów

| # | Skąd | Dokąd | Przewód | Zabezpieczenie |
|---|------|-------|---------|----------------|
| 11 | HR1221W #1 **„+” F2** | szyna „+” banku | 1,5 mm² | 10 A inline |
| 12 | HR1221W #2 **„+” F2** | szyna „+” banku | 1,5 mm² | 10 A inline |
| 13 | HR1221W #3 **„+” F2** | szyna „+” banku | 1,5 mm² | 10 A inline |
| 14 | HR1221W #4 **„+” F2** | szyna „+” banku | 1,5 mm² | 10 A inline |
| 15 | HR1221W #5 **„+” F2** | szyna „+” banku | 1,5 mm² | 10 A inline |
| 16 | HR1221W #1–#5 **„−” F2** | mostek masowy banku | 1,5 mm² | — |
| 17 | mostek masowy banku | punkt gwiazdowy masy | 6 mm² | rozłącznik masy 100 A |
| 18 | NTC 10 kΩ | wejście czujnika ładowarki | 0,5 mm² | — |

> **Jednakowe długości.** Przewód od każdego pakietu do szyny musi mieć tę
> samą długość i przekrój, nawet jeśli pakiety leżą w różnych miejscach.
> Nierówność rezystancji = nierówny rozdział prądu = jeden pakiet umiera
> pierwszy.

> **Zaciski F2.** Nasuwki 6,35 mm w pełni izolowane, zaciskane zaciskarką
> zapadkową, koszulka termokurczliwa z klejem, wiązka przypięta opaską do
> skrzynki (odciążenie mechaniczne).

### 2.3 LVD i dystrybucja

| # | Skąd | Dokąd | Przewód | Zabezpieczenie |
|---|------|-------|---------|----------------|
| 19 | szyna „+” banku | XH-M609 **VIN +** (9) | 2,5 mm² | **15 A** |
| 20 | XH-M609 **VIN −** (10) | punkt gwiazdowy masy | 2,5 mm² | — |
| 21 | XH-M609 **VOUT +** (11) | listwa dystrybucyjna, wejście | 2,5 mm² | — |
| 22 | XH-M609 **VOUT −** (12) | punkt gwiazdowy masy | 2,5 mm² | — |
| 23 | listwa, szyna masowa | punkt gwiazdowy masy | 6 mm² | — |

> **XH-M609 — sprawdź przed montażem.** Przekaźnik ma przerywać **plus**.
> Omomierz między VIN− a VOUT− musi pokazywać zwarcie niezależnie od stanu
> przekaźnika; jeżeli pokazuje przerwę, moduł przełącza masę i rozspójnia
> topologię jednego punktu gwiazdowego. Szczegóły i pozostałe dwa sprawdzenia:
> [`ZASILANIE_BUFOROWANE.md`](ZASILANIE_BUFOROWANE.md) §7.3.
>
> Bezpiecznik 15 A przed VIN+ wynika z zalecenia producenta modułu
> (1,5 × prąd szczytowy obciążenia, tu ~7,5 A).

### 2.4 Domena A (zawsze zasilana)

| # | Skąd | Dokąd | Przewód | Zabezpieczenie |
|---|------|-------|---------|----------------|
| 24 | listwa, obwód 1 | Buck LM2596 **IN +** | 0,75 mm² | 3 A |
| 25 | Buck LM2596 **IN −** | masa | 0,75 mm² | — |
| 26 | Buck **OUT +** (5,0 V) | Nano #1 pin **5V** | 0,75 mm² | — |
| 27 | Buck **OUT +** (5,0 V) | Nano #2 pin **5V** | 0,75 mm² | — |
| 28 | Buck **OUT +** (5,0 V) | HM-10 **VCC**, RXB6 **VCC** | 0,5 mm² | — |
| 29 | Buck **OUT −** | Nano #1/#2 **GND**, HM-10, RXB6 | 0,75 mm² | — |
| 30 | listwa, obwód 1 | Moduł 9 przekaźników **VCC** (12 V) | 0,75 mm² | wspólny z poz. 24 |
| 31 | Moduł przekaźników **GND** | masa | 0,75 mm² | — |

> **Nie podawaj napięcia na pin Vin Nano.** Buck jest ustawiony na 5,0 V
> i idzie wprost na pin **5V**, z pominięciem wewnętrznego stabilizatora.

### 2.5 Domena B (za zapłonem)

| # | Skąd | Dokąd | Przewód | Zabezpieczenie |
|---|------|-------|---------|----------------|
| 32 | listwa, obwód 2 | Przekaźnik **30** | 2,5 mm² | 30 A |
| 33 | Przekaźnik **87** | XL6019 **IN +** (13) | 2,5 mm² | — |
| 34 | Przekaźnik **87** | Buck MP1584 **IN +** | 1,0 mm² | 3 A |
| 35 | Przekaźnik **87** | Hub USB, zasilanie | 1,0 mm² | 3 A |
| 36 | Przekaźnik **86** | linia ACC z zamka kluczyka | 0,75 mm² | 5 A |
| 37 | Przekaźnik **85** | masa | 0,75 mm² | — |
| 38 | XL6019 **IN −** (14) | masa | 2,5 mm² | — |
| 39 | XL6019 **OUT +** (15) | wtyk M910q, **środek** | 1,5 mm² | 5 A |
| 40 | XL6019 **OUT −** (16) | wtyk M910q, **ekran** | 1,5 mm² | — |
| 39a | XL6019 **OUT +** ↔ **OUT −** | kondensator 470 µF / 35 V low-ESR | — | — |
| 41 | Buck MP1584 **OUT +** | panel główny 10,1", 5 V | 1,0 mm² | — |
| 42 | Buck MP1584 **OUT +** | panel drugi 6,86", 5 V *(opcjonalny)* | 1,0 mm² | — |
| 43 | Buck MP1584 **OUT −** | masa paneli (wspólna z Nano #1) | 1,0 mm² | — |

> **Dioda gaszeniowa 1N4007** równolegle do cewki przekaźnika: **katoda do
> zacisku 86**, anoda do 85. Bez niej przepięcie przy rozwarciu cewki wraca
> do instalacji.

> **XL6019 daje ok. 45 W, nie 65 W** (limit prądu klucza 5 A). Przed
> uruchomieniem w aucie ustaw limit poboru pakietu CPU na M910q —
> [`ZASILANIE_BUFOROWANE.md`](ZASILANIE_BUFOROWANE.md) §3.5a. Wyjścia
> przetwornicy **nie da się użyć jako wyłącznika** komputera: boost przepuszcza
> napięcie wejściowe. Komputera nie odcina nic — usypia go impuls z Arduino
> na przycisk zasilania (§10.5).

### 2.6 Gałąź wzmacniacza (niezależna)

Wzmacniacz to **gotowy moduł samochodowy** z wejściami RCA, nie układ DIY.
Podłącza się go jak radio samochodowe: zasilanie wprost z akumulatora, własna
masa, wyzwalanie sygnałem REM.

| # | Skąd | Dokąd | Przewód | Zabezpieczenie |
|---|------|-------|---------|----------------|
| 44 | Akumulator „+” | Wzmacniacz **+12V** | 6 mm² | wg karty modułu, przy klemie |
| 45 | Wzmacniacz **GND** | masa lokalna, przy wzmacniaczu | 6 mm² | — |
| 46 | Przekaźnik **87** | Wzmacniacz **REM** | 0,75 mm² | 2 A |

> **Bezpiecznik dobierz wg karty wzmacniacza**, nie „na oko". Typowy moduł
> 4 × 50 W RMS ma na płytce bezpiecznik 20–30 A i tyle samo powinien mieć
> przy klemie. Przewód 6 mm² wynika ze spadku napięcia na trasie do bagażnika
> (~4 m), nie z samego prądu.

> **Masa wzmacniacza osobno.** To jedyny obwód mocy, który **nie** idzie do
> punktu gwiazdowego — wspólna masa z komputerem daje pętlę i przydźwięk
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
| SWC Pod 2 | biały przewód dekodera | Pro Micro **A6** |

Dekoder SWC: **czerwony → ACC**, **czarny → masa**, **biały → wejście
analogowe**.

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
| A0, A6 | SWC Pod 1, Pod 2 |
| A1 | LDR |
| A2 | przycisk na manetce |

> **v8.5.2:** przycisk enkodera przeniesiony z **D4 na D1** — na Pro Micro
> D4 i A6 to ten sam fizyczny pin i kolidowało z SWC Pod 2. Przy starszym
> okablowaniu przepnij jeden przewód.

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

> **Pętla masy.** DAC ma masę przez USB (punkt gwiazdowy pod deską),
> wzmacniacz ma masę lokalną w bagażniku, a ekran RCA łączy oba punkty.
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

| Wartość | Gdzie | Chroni |
|---------|-------|--------|
| 30 A | przy klemie „+”, ≤ 30 cm | cały tor główny |
| wg karty modułu (20–30 A) | przy klemie „+”, osobno | gałąź wzmacniacza |
| 10 A × 5 | na „+” każdego pakietu banku | zwarcie pojedynczego pakietu |
| 30 A | listwa, obwód 2 | odbiorniki 12 V |
| 5 A | wyjście step-up, przed wtykiem | M910q |
| 5 A | linia ACC do cewki przekaźnika | obwód sterowania |
| 3 A | listwa, obwód 1 | logika 5 V |
| 3 A | odgałęzienie buck MP1584 | panele wyświetlaczy |
| 3 A | odgałęzienie hub USB | hub i peryferia |
| 15 A | między bankiem a XH-M609 **VIN +** | moduł LVD i cała szyna za nim |
| 2 A | zasilanie/pomiar modułu nadnapięciowego | obwód pomiarowy |

Wszystkie w listwie dystrybucyjnej ATO/ATC z pokrywą, w miejscu dostępnym
bez demontażu deski rozdzielczej. Wyjątek: bezpiecznik główny 30 A i 20 A
gałęzi wzmacniacza — w oprawkach przy klemie akumulatora.

---

## 7. Masy

**Jeden punkt gwiazdowy** dla całego head unitu:

- śruba do gołego metalu nadwozia, powierzchnia oczyszczona ze szpachli
  i lakieru, po dokręceniu zabezpieczona wazeliną techniczną,
- schodzą się w nim: masa banku (przez rozłącznik 100 A), masa listwy
  dystrybucyjnej, masa M910q, masa Arduino, masa audio od DAC-a,
- przekrój do nadwozia: **6 mm²**.

**Dwa wyjątki:**

1. **Masa wzmacniacza** — osobno, blisko wzmacniacza. Wspólna z komputerem
   daje pętlę masy i przydźwięk alternatora.
2. **Masa pojazdu po stronie PC817** — celowo odizolowana od masy Arduino.
   To sens optoizolacji.

---

## 8. Kolejność montażu

```
0. Rozplanuj strefy montażu wg vehicle_layout_m910q.svg — zanim cokolwiek wywiercisz
1. Punkt gwiazdowy masy — przygotuj i sprawdź omomierzem (< 0,5 Ω do klemy „−”)
2. Trasy przewodów — peszel, przelotki gumowe w każdej blasze
3. Listwa dystrybucyjna — zamontowana, dostępna, BEZ bezpieczników
4. Moduły zasilania — wszystkie zaciski dokręcone, BEZ zasilania
5. Bank — pakiety zmierzone osobno, wyrównane, bezpieczniki 10 A założone
6. Rozłącznik masy banku w pozycji ROZWARTY
7. Nastawy modułów na stole (patrz ZASILANIE_BUFOROWANE.md § 11 etap 1)
8. Bezpiecznik główny 30 A — wkładany JAKO OSTATNI
```

**Zasada:** każdy etap kończy się pomiarem. Podłączenie wszystkiego naraz
i szukanie potem, co nie działa, kosztuje wielokrotnie więcej czasu niż
sprawdzanie po jednym obwodzie.

To samo dotyczy Arduino: wgraj firmware i sprawdź każdą płytkę przez
`picocom` **na stole**, zanim podłączysz cokolwiek z auta.

---

## 9. Lista kontrolna przed pierwszym załączeniem

```
[ ] Bezpiecznik główny 30 A WYJĘTY
[ ] Rozłącznik masy banku ROZWARTY
[ ] Polaryzacja na wtyku M910q sprawdzona multimetrem (środek „+”)
[ ] XL6019 ustawiony na 19,5 V i przetestowany pod obciążeniem
[ ] Limit poboru pakietu CPU ustawiony na M910q (wymóg przy XL6019)
[ ] Ładowarka: CV 14,40 V, CC 6,0 A
[ ] Rozłącznik nadnapięciowy: 15,30 V / 14,00 V, sprawdzony zasilaczem lab.
[ ] XH-M609: 11,00 V / 12,60 V, sprawdzony zasilaczem laboratoryjnym
[ ] XH-M609: potwierdzone, że przełącza plus, i zmierzony pobór własny
[ ] Buck logiki: 5,0 V na wyjściu (zmierzone, nie „powinno być”)
[ ] Buck paneli: 5,0 V na wyjściu
[ ] Dioda 1N4007 na cewce przekaźnika — katoda do 86
[ ] TVS i kondensator na wejściu ładowarki zamontowane
[ ] Wszystkie pakiety banku zmierzone osobno, rozrzut < 0,2 V
[ ] Bezpieczniki 10 A na każdym pakiecie
[ ] Wszystkie zaciski dokręcone i pociągnięte ręką
[ ] Masa: < 0,5 Ω między punktem gwiazdowym a klemą „−” akumulatora
[ ] Żaden przewód nie ociera o krawędź blachy
[ ] Nic z instalacji 12 V nie idzie bezpośrednio na pin Arduino
```

Po odhaczeniu całości przejdź do procedury pomiarowej:
[`ZASILANIE_BUFOROWANE.md`](ZASILANIE_BUFOROWANE.md) § 11, etap 4.

---

## 10. Tabela połączeń — wariant testowo-rozwojowy

Ten rozdział dotyczy **wyłącznie** wariantu z
[`WDROZENIE_TESTOWE.md`](WDROZENIE_TESTOWE.md): mniej modułów, mniej okablowania,
M910q zasilany stale. Tabele §2–§5 opisują wersję docelową i tutaj **nie
obowiązują**.

**Rysunki:** [`../schematics/schematic_test_build.svg`](../schematics/schematic_test_build.svg)
(ideowy) · [`../schematics/wiring_test_build.svg`](../schematics/wiring_test_build.svg)
(połączeniowy, numery przewodów jak niżej) ·
[`../schematics/ignition_sense.svg`](../schematics/ignition_sense.svg)
(wykrywanie zapłonu)

### 10.1 Tor ładowania

| # | Skąd | Dokąd | Przewód | Zabezpieczenie |
|---|------|-------|---------|----------------|
| 1 | Akumulator rozruchowy **„+”** | Bezpiecznik **F1** (wejście) | 2,5 mm² | — |
| 2 | **F1** (wyjście) | Płytka **TVS + C1**, biegun „+” | 2,5 mm² | 15 A, ≤ 30 cm od klemy |
| 3 | **TVS + C1** „+” | Przekaźnik **K1**, zacisk **30** | 2,5 mm² | — |
| 4 | Zapłon / ACC (albo **D+** alternatora) | **K1** zacisk **86** | 0,75 mm² | — |
| 5 | **K1** zacisk **87** | **D1 MBR2545CT**, anody **1 + 3** zwarte | 2,5 mm² | — |
| 6 | **D1** katoda **2** (blaszka) | Moduł CC-CV boost **IN+** | 2,5 mm² | — |
| **B** | Boost **OUT+** | **K2** (przekaźnik mocy) zacisk **30** | 2,5 mm² | — |
| 7 | **K2** zacisk **87** | Szyna **„+”** banku | 2,5 mm² | — |
| 7a | **K1** zacisk **87** | **XH-M603** zasilanie „+" | 0,75 mm² | — |
| 7b | **XH-M603** zasilanie „−" | Punkt gwiazdowy masy | 0,75 mm² | — |
| 7c | **K1** zacisk **87** | **XH-M603** styk **COM** | 0,75 mm² | — |
| 7d | **XH-M603** styk **NO** | **K2** zacisk **86** (cewka) | 0,75 mm² | — |
| 7e | **K2** zacisk **85** | Punkt gwiazdowy masy | 0,75 mm² | — |

> **XH-M603 i cewka K2 wiszą na zacisku 87 przekaźnika ładowania, nie na
> banku.** Na banku dokładałyby ~160 mA przez całą dobę — tyle, ile
> w stanie wyłączonym pobiera cała reszta instalacji. Uzasadnienie
> i zachowanie po zadziałaniu: §6.3 [`ZASILANIE_BUFOROWANE.md`](ZASILANIE_BUFOROWANE.md).

> **Dioda 1N4007** równolegle do cewki K2 (zaciski 85–86), katodą do „+”.
> Przy **CC ≤ 6 A** można pominąć K2 i puścić 8 A wprost przez styki
> modułu — wtedy przewody 7c–7e odpadają, a 7 idzie z **NO** modułu.

Masy tego toru (K1 zacisk 85, „−” TVS/C1, boost **IN−** i **OUT−**, „−”
zasilania rozłącznika) idą do punktu gwiazdowego — §10.4.

> **Dioda 1N4007** równolegle do cewki K1 (zaciski 85–86), katodą do „+”.
> Bez niej impuls samoindukcji cewki wraca w instalację przy każdym
> przekręceniu kluczyka.

### 10.2 Bank, LVD, wyłącznik

| # | Skąd | Dokąd | Przewód | Zabezpieczenie |
|---|------|-------|---------|----------------|
| — | „+” każdego pakietu HR1221W | Szyna **„+”** banku | 2,5 mm² | **F2…F5** 10 A, osobno na pakiet |
| — | „−” każdego pakietu | Szyna **„−”** banku | 2,5 mm² | — |
| 8 | Szyna **„+”** banku | **XH-M609 VIN+** | 2,5 mm² | **F7** 15 A |
| 9 | Szyna **„−”** banku | **XH-M609 VIN−** | 2,5 mm² | — |
| 10 | **XH-M609 VOUT+** | **S1** wyłącznik główny, zacisk 1 | 2,5 mm² | — |

Nasuwki **F2 6,35 mm** izolowane, zaciskane zaciskarką zapadkową.
Łączenie równoległe pakietów: [`ZASILANIE_BUFOROWANE.md`](ZASILANIE_BUFOROWANE.md) §4.3.

### 10.3 Odbiorniki — zasilane stale

| # | Skąd | Dokąd | Przewód | Zabezpieczenie |
|---|------|-------|---------|----------------|
| 11 | **S1** zacisk 2 (szyna odbiorników) | **XL6019 IN+** | 1,5 mm² | **F8** 7,5 A |
| 12 | **XL6019 OUT+** / **OUT−** | Wtyk M910q: środek „+”, ekran „−” | 1,5 mm² | — |
| 13 | **S1** zacisk 2 (szyna odbiorników) | **LM2596 IN+** | 1,5 mm² | **F9** 2 A |
| 14 | **LM2596 OUT+** / **OUT−** | Panel 7", złącze **PWM+** / **GND** | 1,5 mm² | — |

> **F8 to 7,5 A, nie 5 A.** Przy 45 W na wyjściu XL6019 i sprawności 85 %
> prąd wejściowy sięga 4,2 A przy 12,6 V i **4,6 A** przy napięciu banku
> bliskim progu LVD. Wkładka 5 A pracowałaby na krawędzi.

**Logika panelu i dotyk zostają na USB M910q** — osobno idzie wyłącznie
podświetlenie. Panel ma jeden kabel USB do komputera i jedno złącze
zasilania podświetlenia.

### 10.4 Wykrywanie zapłonu

Wartości elementów i uzasadnienie: [`../schematics/ignition_sense.svg`](../schematics/ignition_sense.svg).

| # | Skąd | Dokąd | Przewód |
|---|------|-------|---------|
| 15 | Zapłon / ACC **12 V** | **R1** 2,2 kΩ / 0,25 W → **U1 (PC817)** pin **1** | 0,5 mm² |
| 16 | **U1** pin **2** | **Masa instalacji auta** — NIE punkt gwiazdowy | 0,5 mm² |
| 17 | **U1** pin **4** | Pro Micro **D0 (RXI)** | 0,5 mm² |
| 18 | **U1** pin **3** | Pro Micro **GND** | 0,5 mm² |
| 19 | Pro Micro **D0** | **R2** 10 kΩ → Pro Micro **+5 V** (opcjonalny) | 0,5 mm² |
| 20 | Pro Micro **D0** | **C2** 100 nF → Pro Micro **GND** | 0,5 mm² |

> **Przewody 16 i 18 celowo idą do różnych mas.** Na tym polega optoizolacja:
> po jednej stronie PC817 jest masa auta, po drugiej masa Pro Micro. Zwarcie
> ich niweczy cały sens układu i wpuszcza do komputera wszystko, co jeździ po
> linii ACC.

### 10.5 Sterowanie przyciskiem zasilania M910q

Arduino nie wysyła żadnego protokołu — po prostu **zwiera przycisk
zasilania**, a resztę robi acpid, który jest już skonfigurowany
(§7.3 [`WDROZENIE_M910Q.md`](WDROZENIE_M910Q.md)).

| # | Skąd | Dokąd | Przewód |
|---|------|-------|---------|
| 21 | Pro Micro **A2** | Moduł przekaźnika **IN** | 0,5 mm² |
| 22 | Pro Micro **+5 V** / **GND** | Moduł przekaźnika **VCC** / **GND** | 0,5 mm² |
| 23 | Przekaźnik **COM** | Przycisk zasilania M910q, zacisk 1 | 0,5 mm² |
| 24 | Przekaźnik **NO** | Przycisk zasilania M910q, zacisk 2 | 0,5 mm² |
| 25 | **MP1584 OUT+** / **OUT−** | Pro Micro **VCC** / **GND** | 0,75 mm² |

Styki przekaźnika idą **równolegle** do przycisku — przycisk dalej działa
normalnie i zostaje ratunkiem awaryjnym.

| Impuls na A2 | Efekt |
|--------------|-------|
| **250 ms** przy pracy | uśpienie do S3 |
| **250 ms** w S3 | wybudzenie w ~3 s |
| **250 ms** po wyłączeniu | start (zimny, ~40 s) |
| **5 s** | twarde wyłączenie — pobór spada do ~80–120 mA |

> **Przetnij żyłę VBUS (czerwoną) w kablu USB do Pro Micro.** Płytka jest
> zasilana z MP1584 (przewód 25) i musi żyć, gdy M910q śpi. Dwa źródła 5 V
> zwarte razem to niepotrzebne ryzyko; dane po USB działają bez VBUS.

> **Zaciski przycisku znajdź miernikiem** w trybie ciągłości, przy maszynie
> odłączonej od zasilania: rozwarte, zwarte przy wciśnięciu.

### 10.6 Punkt gwiazdowy masy

Lądują na nim: „−” akumulatora rozruchowego, „−” TVS/C1, zacisk **85** K1,
**IN−** i **OUT−** boostu, „−” zasilania rozłącznika nadnapięciowego, szyna
**„−”** banku, **VIN−** i **VOUT−** modułu XH-M609, **IN−** przetwornic
XL6019 i LM2596.

**Jedyny wyjątek:** masa układu wykrywania zapłonu (**U1 pin 2**, przewód 16)
idzie do masy instalacji auta.

### 10.7 Kolejność podłączania

```
1. S1 rozwarty, bank odłączony, F1 wyjęty z oprawki.
2. Nastawy na zasilaczu laboratoryjnym — wszystkie pięć:
   XL6019 19,5 V · LM2596 wg panelu · boost 14,40 V / 8 A
   rozłącznik 15,30 V · XH-M609 11,00 / 12,60 V
3. Punkt gwiazdowy masy — komplet z §10.5.
4. Bank (4 pakiety) z bezpiecznikami F2…F5, pomiar napięcia na szynie.
5. Przewody 8, 9, 10 — bank przez F7 do LVD i S1.
6. Przewody 11 i 12 — XL6019. POMIAR 19,5 V BEZ podłączonego M910q.
7. Dopiero teraz M910q, potem 13–14 (podświetlenie).
8. Na końcu przewody 1–7 i B — tor ładowania, przy zgaszonym silniku.
9. Rozruch silnika, pomiar prądu ładowania cęgami lub bocznikiem.
```

Punkt 6 pomijany „bo przecież ustawiałem" to najczęstszy sposób na zabicie
płyty głównej. Punkt 8 pomijany — na zabicie banku.

---

## Powiązane dokumenty

| Dokument | Zakres |
|----------|--------|
| [`ZASILANIE_BUFOROWANE.md`](ZASILANIE_BUFOROWANE.md) | dobór podzespołów, nastawy, lista zakupowa, procedura rozruchu |
| [`WDROZENIE_M910Q.md`](WDROZENIE_M910Q.md) | pełne wdrożenie: sprzęt, BIOS, OS, usługi, odbiór |
| [`ARDUINO_SETUP_GUIDE.md`](ARDUINO_SETUP_GUIDE.md) | wgrywanie firmware, kalibracja SWC, pełne tabele pinów |
| [`KLINE_SNIFFING.md`](KLINE_SNIFFING.md) | podsłuch K-Line, poznawanie PID-ów ECU |
| [`../schematics/README.md`](../schematics/README.md) | indeks wszystkich schematów |
