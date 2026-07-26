# Wdrożenie testowo-rozwojowe — mało funkcji, pełny tor zasilania

Wariant do bieżącej weryfikacji i poprawek **w jeżdżącym aucie**: Android Auto
wireless + dźwięk przez mini-jack M910q, ekran 7", przyciski SWC, modem LTE.
Wszystko pozostałe wyłączone.

Wdrożenie docelowe (pełne): [`WDROZENIE_M910Q.md`](WDROZENIE_M910Q.md).

> **To nie jest stanowisko biurkowe.** Zestaw jedzie w aucie, więc tor
> zasilania jest kompletny: ładowanie banku, blokada przeładowania, LVD
> i przekaźnik zapłonu. Oszczędzamy na funkcjach BCM i na wariancie
> ładowarki — **nie na zabezpieczeniach**.

> **Ekran 7" to konfiguracja tymczasowa.** Docelowy panel to **10,1"
> 1280×800**, opcjonalnie drugi **6,86" 1280×480** — i tak jest ustawione
> w `config/bcm_config.yaml`. Ten wariant używa osobnego pliku
> `config/bcm_config_test.yaml` z 1024×600, żeby nie ruszać konfiguracji
> produkcyjnej.

---

## Spis treści

1. [Co uruchamiamy](#1-co-uruchamiamy)
2. [Co już masz](#2-co-już-masz)
3. [Zasilanie](#3-zasilanie)
4. [Lista zakupowa](#4-lista-zakupowa)
5. [Instalacja software'u](#5-instalacja-softwareu)
6. [Uruchomienie](#6-uruchomienie)
7. [Odbiór](#7-odbiór)
8. [Czego celowo nie ma](#8-czego-celowo-nie-ma)
9. [Droga do wersji docelowej](#9-droga-do-wersji-docelowej)

---

## 1. Co uruchamiamy

Pięć modułów zamiast dwudziestu ośmiu, plus dwa podsystemy potrzebne do
Android Auto wireless:

| Przełącznik | Po co | Czego wymaga |
|-------------|-------|--------------|
| `dashboard` | frontend na porcie 5002 | ekran 7" + Chromium |
| `multimedia` | **Android Auto** (openauto) | telefon + BT + P2P-GO |
| `input` | **przyciski SWC** | Arduino Pro Micro (USB HID) |
| `audio` | głośność i EQ | wyjście analogowe M910q |
| `network` | status łącza | modem LTE (przez NetworkManager) |
| `bluetooth` | bootstrap handshake'u AA wireless | karta/dongiel BT |
| `wifi_ap` | P2P-GO — łącze danych AA | karta MT7921 |

Reszta — OBD, kamery, parkowanie, czujniki, przekaźniki, GPS, alarm — jest
**wyłączona**, bo nie ma podłączonego sprzętu. Włączanie modułów bez
hardware'u produkuje tylko szum w logach.

### Trzy ustalenia z kodu, które upraszczają ten wariant

**Dźwięk nie wymaga DAC-a USB.** `src/audio/pipewire_ctrl.py` na x86 używa
**domyślnego sinka PipeWire** — czyli tego, co ustawisz w systemie. Wyjście
analogowe M910q (mini-jack) działa bez żadnych zmian w kodzie. DAC USB
ES9038Q2M to podniesienie jakości, nie warunek uruchomienia.

**Modem LTE nie wymaga konfiguracji w BCM.** `src/network/lte.py` na x86
tylko **raportuje** stan łącza (`lte.connected`, `lte.signal`, `lte.ip`);
samo połączenie robi NetworkManager. Huawei E3372 w trybie HiLink zgłasza się
jako karta sieciowa i działa od podłączenia.

**Moduł `power` zostaje wyłączony mimo przekaźnika zapłonu.** `PowerManager`
(`src/power/power_manager.py`) reaguje na zdarzenia `hal.ignition` /
`sim.ignition`, a na x86 nikt takich zdarzeń nie publikuje — nie ma wejścia
GPIO. Odcięcie domeny B robi tu sprzęt (przekaźnik na ACC), nie software.

---

## 2. Co już masz

| Element | Uwaga |
|---------|-------|
| Lenovo M910q | |
| Ekran 7" | 1024×600, HDMI + dotyk USB |
| Karta WiFi MediaTek MT7921 | **AA wireless po P2P-GO już działa** |
| Pody SWC + dekoder | rezystorowa drabinka → wejście analogowe |
| Modem LTE Huawei E3372 | HiLink, USB |
| Akumulatory CSB HR1221W × 8 | AGM 12 V / 5,1 Ah |
| **XL6019** | step-up 12 → 19,5 V dla M910q |
| **XH-M609** | LVD, ochrona banku przed rozładowaniem |

---

## 3. Zasilanie

### 3.1 Tor — co jedzie w aucie

![Tor zasilania wariantu testowego](../schematics/power_test_build.svg)

```
akumulator rozruchowy
   │  bezpiecznik 15 A przy klemie „+", przewód 2,5 mm²
   ▼
TVS + kondensator 470 µF/35 V        ← ochrona wejścia (§5.4 ZASILANIE)
   │
   ▼
VSR  (zał. 13,3 V / wył. 12,8 V)     ← zwiera dopiero, gdy alternator pracuje
   │
   ▼
moduł CC-CV boost  (CV 14,40 V, CC wg §3.3)
   │
   ▼
rozłącznik nadnapięciowy (próg 15,30 V)   ← warstwa 2
   │
   ▼
BANK AGM 5 × HR1221W ── bezpiecznik 10 A na „+" każdego pakietu
   │
   ▼
XH-M609 (LVD)  ── bezpiecznik 15 A przed VIN+
   │  odcięcie 11,00 V · powrót 12,60 V
   ▼
wyłącznik główny na „+"  (albo rozłącznik masy na „−" banku)
   │
   ├── przekaźnik zapłonu (cewka z ACC, dioda 1N4007) — DOMENA B
   │      ├── bezp. 5 A → XL6019 12 → 19,5 V → M910q
   │      └── bezp. 3 A → panel 7"
   │
   └── DOMENA A — w tym wariancie pusta (nie ma jeszcze Nano, HM-10, RXB6)
```

Trzy rzeczy warto tu zauważyć:

- **Domena A jest pusta**, więc na postoju z banku pobiera prąd wyłącznie
  sam XH-M609. To czyni pomiar jego poboru (§7.3
  [`ZASILANIE_BUFOROWANE.md`](ZASILANIE_BUFOROWANE.md)) najważniejszą liczbą
  całego wariantu — patrz tabela w §3.3.
- **Przekaźnik zapłonu nie jest opcją.** Bez niego XL6019 i M910q wiszą na
  banku na postoju i rozkładają go w kilkanaście godzin.
- **Panel 7" zasilaj wprost z 12 V**, jeśli tego wymaga. Buck 12 → 5 V dokup
  tylko wtedy, gdy Twój panel jest 5-woltowy.

### 3.2 Ładowanie — wariant B, i dlaczego akurat on

[`ZASILANIE_BUFOROWANE.md`](ZASILANIE_BUFOROWANE.md) §5 opisuje dwa warianty:
gotową ładowarkę B2B (800–1000 PLN) albo VSR + moduł CC-CV boost
(120–220 PLN). Na etapie testowym bierzemy **wariant B** — różnica to
kilkaset złotych za funkcje, które przy jeździe testowej niewiele wnoszą.

**CV ustawiamy na 14,40 V, nie niżej.** To nie jest wybór estetyczny: boost
ma władzę nad prądem tylko wtedy, gdy faktycznie przetwarza, czyli gdy
wyjście jest wyżej niż wejście. Na wejściu modułu przy pracującym alternatorze
jest 13,4–14,2 V, więc nastawa 13,8 V wepchnęłaby moduł w **pass-through**,
gdzie pętla CC nie ma czym sterować, a rozładowany bank ciągnąłby ponad 30 A
przez sam dławik. Pełne wyprowadzenie: §5.3b
[`ZASILANIE_BUFOROWANE.md`](ZASILANIE_BUFOROWANE.md).

Konsekwencje 14,40 V bez kompensacji temperaturowej — i co je łagodzi:

| | |
|---|---|
| ✅ | CC działa zawsze, więc prąd ładowania jest naprawdę ograniczony |
| ✅ | absorpcja podawana **tylko przy pracującym silniku** — VSR rozwiera obwód na postoju, bank nie stoi na 14,4 V |
| ✅ | bank ładuje się do 100 %, nie do 90 % |
| ⚠️ | brak kompensacji: przy 40 °C prawidłowa absorpcja to 13,95 V, czyli jedziesz 0,45 V za wysoko |
| ⚠️ | próg warstwy 2 zostaje na **15,30 V** |

Jeśli bagażnik latem dochodzi do 50 °C — zejdź z CV do **14,10 V**. Nadal
powyżej wejścia, więc CC pozostaje sprawne.

**Dlaczego VSR, a nie dioda Schottky:** boost nie potrafi dać napięcia
niższego niż wejściowe, więc przy zgaszonym silniku podawałby 14,4 V
i **rozładowywał akumulator auta**. VSR rozłącza obwód fizycznie poniżej
12,8 V. Szczegóły: §5.3 [`ZASILANIE_BUFOROWANE.md`](ZASILANIE_BUFOROWANE.md).

### 3.2a Konkretne moduły

**Moduł CC-CV** — trzy sensowne opcje, wszystkie to boost:

| Model | Dane | Cena (PLN) | Kiedy ten |
|-------|------|-----------|-----------|
| **„900 W 15 A" z wyświetlaczem** (typ CNC/DPS, wej. 8–60 V, wyj. 10–120 V) | CC 0–15 A, nastawa cyfrowa z odczytem | 90–140 | **bierz ten** — wpisujesz 14,40 V i 8,0 A i odczytujesz z powrotem; przy pierwszej instalacji to warte tych 40 zł różnicy |
| **SZBK07** (SZ-BT07CCCV-D1 „1500 W 30 A", wej. 10–60 V, wyj. 12–90 V) | CC 0,8–20 A ±0,3 A · sprawność 92–97 % · ochrona odwrotnej polaryzacji · 130 × 84 × 52 mm | 80–130 | duży zapas mocy, pracuje zimno; nastawa potencjometrami — mierz multimetrem |
| **„600 W 10 A"** (wej. 10–60 V, wyj. 12–80 V) | CC-CV potencjometrami | 50–80 | tylko przy trzech pakietach (CC do 6 A) |

> **Sprawdź „auto output on power-on"** w module z wyświetlaczem. Jeśli ta
> opcja jest wyłączona, po każdym uruchomieniu silnika wyjście stoi w OFF
> i bank się nie ładuje — bez żadnego objawu, dopóki nie zejdzie do LVD.

Modułu **buck-boost LTC3780** (WD2002SJ / XR-131) *nie* bierz do pięciu
pakietów: utrzymałby 13,8 V, ale ciągle daje tylko 7 A / 80 W, czyli ~5,8 A
przy 13,8 V. Po odjęciu 3,5 A obciążenia zostaje 2,3 A do banku.

**VSR** — cztery opcje, od markowej do najtańszej:

| Model | Progi | Cena (PLN) | Uwaga |
|-------|-------|-----------|-------|
| **Durite 0-727-11** — 12 V / 140 A | zał. 13,3 V · rozł. 12,65 V | 150–250 | zalany żywicą, LED stanu, progi fabrycznie takie, jakich potrzebujesz |
| **Victron Cyrix-ct 12/24-120** | mikroprocesorowy | 250–350 | bezobsługowy; przy 9 A przesada |
| Bezmarkowy „VSR 12 V 140 A" | zwykle 13,3 / 12,8 V | 60–120 | **zweryfikuj progi zasilaczem** — bywają przekłamane o 0,3 V |
| **Przekaźnik 30 A z D+ alternatora** | zwiera, gdy alternator ładuje | 15–25 | tor niesie 9 A, więc 140 A to przesada. Trzeba znaleźć zacisk **D+/L** i sprawdzić, czy lampka kontrolna dalej działa — cewka bierze ~150 mA z jej obwodu |

### 3.3 Prąd ładowania — policz go z obciążeniem

Moduł CC-CV limituje **prąd wyjściowy**, czyli obciążenie **plus** ładowanie.
Zestaw testowy pobiera podczas jazdy ok. **3,5 A** (M910q ~30 W przez XL6019
o sprawności ~85 % ≈ 2,7 A, panel ~0,6 A, reszta drobiazgi). Jeżeli ustawisz
CC na 4 A, do banku popłynie 0,5 A i **nigdy się nie doładuje**.

Reguła:

```
CC = obciążenie (≈3,5 A) + docelowy prąd ładowania
     jednocześnie CC ≤ 2,1 A × liczba pakietów   ← sufit katalogowy CSB
```

| Pakiety | Sufit katalogowy | Zalecane CC | Netto do banku |
|---------|------------------|-------------|----------------|
| 3 | 6,3 A | 6,0 A | 2,5 A |
| **5** | **10,5 A** | **8,0 A** | **4,5 A** |
| 8 | 16,8 A | 10,0 A (limit modułu) | 6,5 A |

Przy 8 A ciągłego prądu tani moduł „300 W / 10 A" **wymaga radiatora
i przewiewu** — traktuj katalogowe 10 A jako wartość szczytową, nie roboczą.

### 3.4 Ile pakietów

**Pięć (25,5 Ah)** — tak jak w wersji docelowej, więc skrzynka, mocowanie
i okablowanie nie będą do przerobienia po testach. Trzy wystarczą, jeśli
w fazie testowej brakuje miejsca.

| Pakiety | Pojemność | Praca przy zgaszonym silniku (3,5 A) | Postój przy 40 mA | Doładowanie z 50 % |
|---------|-----------|--------------------------------------|-------------------|--------------------|
| 3 | 15,3 Ah | ~2,2 h | ~8,0 dnia | ~3,1 h jazdy |
| **5** | **25,5 Ah** | **~3,6 h** | **~13,3 dnia** | **~2,8 h jazdy** |
| 8 | 40,8 Ah | ~5,8 h | ~21,3 dnia | ~3,1 h jazdy |

Wszystko liczone do 50 % DoD. Postój wypada dłużej niż w wersji docelowej,
bo domena A jest pusta — jedynym odbiornikiem jest XH-M609. Przy jego
poborze 20 mA czasy się podwajają, przy 125 mA (katalogowe maksimum) spadają
ponad trzykrotnie — **dlatego to zmierz**.

> Krótkie przejazdy po mieście nie doładują banku po dłuższym postoju.
> Kolumna „doładowanie" zakłada ciągłą jazdę z pracującym alternatorem.

> **Bezpieczników na pakietach nie pomijaj.** Zwarty HR1221W potrafi oddać
> ponad 100 A — 5 Ah wystarczy, żeby zapalić przewód.

### 3.5 Nastawy modułów

| Moduł | Nastawa | Uwaga |
|-------|---------|-------|
| **XL6019** | wyjście **19,5 V** pod obciążeniem | ustaw multimetrem, zabezpiecz potencjometr |
| **XH-M609** | odcięcie **11,00 V**, powrót **12,60 V** | sprawdź, czy pracuje stabilnie przy 11 V |
| **VSR** | zał. **13,3 V**, wył. **12,8 V** | zwykle fabryczne, sprawdź kartę |
| **CC-CV boost** | CV **14,40 V**, CC wg §3.3 | ustaw CV **bez obciążenia**, CC na sztucznym obciążeniu; nigdy poniżej napięcia wejściowego — §3.2 |
| **Rozłącznik nadnapięciowy** | próg **15,30 V**, powrót **14,00 V** | test zasilaczem laboratoryjnym, nie „na aucie" |

Obowiązkowe sprawdzenia XL6019 i XH-M609 przed pierwszym załączeniem:
[`ZASILANIE_BUFOROWANE.md`](ZASILANIE_BUFOROWANE.md) §3.4 i §7.3.

> **Limit poboru CPU ustaw od razu**, nie „potem". XL6019 daje ok. 45 W,
> a M910q pod pełnym obciążeniem czterech wątków dobija do 55 W. Instrukcja:
> [`ZASILANIE_BUFOROWANE.md`](ZASILANIE_BUFOROWANE.md) §3.5a.

### 3.6 Wyłączanie — przekaźnik tnie twardo

Przekaźnik zapłonu odcina domenę B **natychmiast** po przekręceniu kluczyka.
Jeśli w tym momencie system pisze na dysk, ryzykujesz uszkodzenie
systemu plików — a przy budowie rozwojowej cykli zasilania są dziesiątki
dziennie.

Procedura na czas testów:

```
1. Zaparkuj.
2. Przycisk zasilania M910q  →  S3  (acpid + bcm-power-toggle.sh, §7.3 WDROZENIE_M910Q)
3. Dopiero teraz kluczyk OFF.
```

W S3 nic nie jest zapisywane, więc odcięcie zasilania jest wtedy nieszkodliwe
— maszyna wystartuje zimno przy następnym ACC. Zapominalskim ext4 zwykle
wybacza, ale nie liczyłbym na to w nieskończoność.

Automatyczne, „grzeczne" wyłączanie na zaniku ACC wymagałoby przekaźnika
z opóźnieniem plus sygnału ACC podanego do Pro Micro i zmian w firmware —
poza zakresem tego wariantu.

---

## 4. Lista zakupowa

Ceny orientacyjne, rynek PL, 2025/2026.

### 4.1 Tor ładowania i ochrona — obowiązkowe

| # | Element | Specyfikacja | Cena (PLN) |
|---|---------|--------------|-----------|
| 1 | **VSR** | Durite 0-727-11 albo bezmarkowy 12 V / 140 A — modele w §3.2a | 60–250 |
| 2 | **Moduł CC-CV boost** | „900 W 15 A" z wyświetlaczem albo SZBK07 — modele w §3.2a | 50–140 |
| 3 | **Rozłącznik nadnapięciowy** | przekaźnik napięciowy programowalny (XY-WJ01 lub odpowiednik), próg 15,30 V | 40–80 |
| 4 | **Przekaźnik zapłonu** | Bosch 12 V / 30 A SPDT + podstawka | 15–25 |
| 5 | **Dioda 1N4007** | gaszeniowa, równolegle do cewki | 2–5 |
| 6 | **Dioda TVS + kondensator** | 1.5KE33CA lub SMCJ26CA + 470 µF/35 V low-ESR | 10–20 |
| 7 | **Radiator + wentylator 40 mm** | do XL6019 — w aucie obowiązkowy | 20–35 |
| 8 | **Kondensator wyjściowy** | 470 µF/35 V low-ESR na wyjście XL6019 | 3–6 |
| | | **Podsuma** | **200–561** |

### 4.2 Bezpieczniki i okablowanie — obowiązkowe

| # | Element | Specyfikacja | Cena (PLN) |
|---|---------|--------------|-----------|
| 9 | Bezpiecznik **15 A** + oprawka przy klemie „+" | zasilanie ładowarki | 15–25 |
| 10 | Bezpieczniki inline **10 A × 5** + oprawki | po jednym na pakiet | 25–40 |
| 11 | Bezpiecznik inline **15 A** + oprawka | przed VIN+ modułu XH-M609 | 8–12 |
| 12 | Bezpiecznik **5 A** + oprawka | wyjście XL6019 | 8–12 |
| 13 | Bezpiecznik **3 A** + oprawka | panel 7" | 8–12 |
| 14 | Przewód **2,5 mm²** | FLRY, czerwony 5 m + czarny 3 m | 40–60 |
| 15 | Przewód **1,5 mm²** | FLRY, czerwony + czarny po 3 m | 15–25 |
| 16 | Przewód **0,75 mm²** | FLRY, kilka kolorów po 2 m (ACC, sterowanie) | 15–25 |
| 17 | Nasuwki **F2 6,35 mm** izolowane | do zacisków HR1221W, komplet | 15–25 |
| 18 | Konektory oczkowe, tulejki, koszulki | zestaw, koszulki z klejem | 30–50 |
| 19 | **Rozłącznik masy** | 100 A — na czas montażu i dłuższego postoju | 40–70 |
| 20 | Skrzynka / wspornik na bank + pasy | na 5 pakietów, mocowanie do nadwozia | 60–120 |
| 21 | Peszel + przelotki gumowe | przejścia przez blachę | 25–40 |
| | | **Podsuma** | **304–516** |

**Razem obowiązkowo: ~504–1077 PLN.** Dolny kraniec to bezmarkowy VSR
i moduł „600 W" na potencjometrach, górny — Victron Cyrix i boost
z wyświetlaczem. Przy pierwszej instalacji warto dopłacić przynajmniej
za moduł CC-CV z odczytem cyfrowym.

> **Przekrój 2,5 mm² zamiast 6 mm²** jest tu policzony pod ten wariant:
> 8 A ładowania to ok. 9 A po stronie wejścia, a bezpiecznik 15 A chroni
> przewód z zapasem. Przy przejściu na ładowarkę B2B (18–25 A) trzeba
> **wymienić i przewód, i bezpiecznik** na 6 mm² / 30 A.

### 4.3 Zależne od tego, co już masz

| # | Element | Kiedy potrzebne | Cena (PLN) |
|---|---------|----------------|-----------|
| 22 | **Arduino Pro Micro** (ATmega32U4) | jeśli nie masz — pody SWC bez niego nie zadziałają | 40–60 |
| 23 | **Wtyk zasilania do M910q** | najtaniej: odetnij kabel od oryginalnego zasilacza (koszt 0) | 0–40 |
| 24 | **Przejściówka DP → HDMI** | tylko jeśli Twój egzemplarz M910q ma wyjścia DisplayPort — sprawdź (§5.2) | 0–25 |
| 25 | **Buck 12 → 5 V** (MP1584, 3 A) | tylko jeśli panel 7" jest 5-woltowy | 0–15 |
| 26 | **Zaciskarka zapadkowa** | zaciski robione kombinerkami to najczęstsza usterka instalacji | 0–150 |
| 27 | **Ładowarka sieciowa AGM** | doładowanie w garażu przy krótkich przejazdach | 0–250 |

### 4.4 Warto, ale nie na start

| # | Element | Po co | Cena (PLN) |
|---|---------|-------|-----------|
| 28 | Woltomierz/amperomierz panelowy z bocznikiem | podgląd banku i prądu ładowania bez multimetru | 40–70 |
| 29 | Multimetr z pomiarem prądu DC 10 A | pomiar poboru XH-M609 i prądu ładowania | 80–200 |

### 4.5 Czego **nie** kupuj na tym etapie

| Element | Dlaczego |
|---------|----------|
| Ładowarka B2B (Victron / Redarc) | wariant B robi to samo za ~1/5 ceny — §3.2 |
| Czujnik NTC | tanie moduły CC-CV nie mają wejścia kompensacji, więc nie ma go gdzie wpiąć — §3.2 |
| Moduł buck-boost LTC3780 | utrzyma 13,8 V, ale tylko 80 W ciągle — za mało przy pięciu pakietach, §3.2a |
| Przewód 6 mm², bezpiecznik główny 30 A | wymiarowane pod ładowarkę B2B — §4.2 |
| Listwa dystrybucyjna 6–8 obwodów | cztery obwody obsłużą oprawki inline |
| Buck 12 → 5 V dla domeny A | nie ma jeszcze Nano, HM-10 ani RXB6 |
| Moduł 9 przekaźników, oba Nano, HM-10, RXB6 | odpowiednie moduły są wyłączone |
| DAC USB ES9038Q2M | mini-jack M910q wystarcza do weryfikacji — §1 |
| Karta WiFi | **masz MT7921 i P2P-GO już działa** |
| Wzmacniacz, głośniki | osobna gałąź z akumulatora rozruchowego, po testach |
| Drugi ekran, kamery, graber, czujniki | odpowiednie moduły są wyłączone |

---

## 5. Instalacja software'u

### 5.1 System i BCM

Debian 13 (Trixie) minimal + pakiety + `/opt/bcm` + venv —
kroki §5 i §6 z [`WDROZENIE_M910Q.md`](WDROZENIE_M910Q.md). Bez zmian.

### 5.2 Nazwy złączy — sprawdź, nie zakładaj

```bash
for f in /sys/class/drm/card*-*/status; do echo "$f: $(cat $f)"; done
xrandr | grep " connected"
```

Na referencyjnym M910q złącza enumerują się jako `HDMI-A-1` / `HDMI-A-2`,
a główny panel wyszedł na **złączu 2**. Twoja sztuka może mieć inaczej.

### 5.3 Wyjście audio na mini-jack

```bash
# lista sinków
wpctl status

# ustaw analogowe wyjście M910q jako domyślne (podstaw swoje ID)
wpctl set-default <ID_sinka_analogowego>

# test
speaker-test -c2 -twav -l1
```

BCM nie wymaga tu żadnej konfiguracji — bierze domyślny sink.

### 5.4 Konfiguracja wariantu testowego

Repozytorium zawiera gotowy plik `config/bcm_config_test.yaml`: pięć
modułów plus `bluetooth` i `wifi_ap` włączone, reszta wyłączona,
ekran 1024×600.

> `--config` **podmienia całą konfigurację**, nie nakłada się na
> `bcm_config.yaml`. Dlatego jest to pełna kopia z pozmienianymi kluczami,
> a nie krótka nakładka.

### 5.5 Firmware Pro Micro

```bash
make -C arduino rotary_encoder-upload PORT=/dev/ttyACM0
```

Pody SWC podłącz do **A0** (Pod 1) i **A6** (Pod 2), dekoder: czerwony → ACC,
czarny → masa. Kalibracja: przytrzymaj HOME + BACK przy starcie płytki
i naciskaj kolejne przyciski wg podpowiedzi na porcie szeregowym. Progi
zapisują się w EEPROM.

Szczegóły: [`ARDUINO_SETUP_GUIDE.md`](ARDUINO_SETUP_GUIDE.md).

### 5.6 Android Auto wireless (P2P-GO)

`openauto` kompilowany ze źródeł — procedura w
[`WDROZENIE_M910Q.md`](WDROZENIE_M910Q.md) §13.3. Łącze jest **bezprzewodowe**:
Bluetooth zestawia handshake, dane lecą po Wi-Fi Direct z karty MT7921.

Co robi który element (wprost z kodu):

| Element | Rola |
|---------|------|
| `modules.bluetooth` | rejestruje PBAP-PCE i MAP-MCE, wymusza Class-of-Device **0x620420** (carkit) |
| **autoapp / btservice** | właściwy handshake AA po RFCOMM — BCM celowo **nie** rejestruje UUID Android Auto |
| `modules.wifi_ap` | tworzy grupę **P2P-GO** i zapisuje `wifi.bssid_runtime` |
| `openauto.py` | czyta `wifi.bssid_runtime` i podaje telefonowi adres punktu |

Klucze w `config/bcm_config_test.yaml`, sekcja `wifi:` — ustawione domyślnie:

```yaml
wifi:
  enabled: true       # openauto ostrzega w logu, jeśli false
  mode: p2p_go
  band: a             # AA wireless wymaga 5 GHz
  channel: 149        # kanał 149 istnieje tylko w regdom US
  country: US
  regdom: US
```

Dwie pułapki, obie udokumentowane w kodzie:

- **Class-of-Device.** `bluetoothd` sam syntezuje CoD z zarejestrowanych
  wtyczek — PipeWire rejestruje A2DP/HFP i nadpisuje klasę carkit na
  „Computer". Telefon używa bitów CoD do bramkowania AA, więc z klasą
  „Computer" **wireless nigdy się nie pojawi**. `_force_carkit_cod()`
  przestempluje ją po każdej burzy rejestracji.
- **`wifi_hotspot` (ALFA-NET) musi zostać wyłączony.** MT7921 zgłasza
  `#{AP, P2P-GO} <= 1` — druga sieć na tym samym radiu rozwali grupę P2P.
  Współdzielenie internetu wymaga **osobnego** dongla USB.

Parowanie: telefon → BT → sparuj z adapterem BCM → Android sam zaproponuje
Android Auto. Kolejne uruchomienia łączą się automatycznie (boot sweep
w `BluetoothManager`).

---

## 6. Uruchomienie

### 6.1 Ręcznie (do rozwoju)

```bash
cd /opt/bcm
source .venv/bin/activate
python3 main.py --platform x86 --config config/bcm_config_test.yaml --frontend
```

Dashboard: `http://localhost:5002`. Zatrzymanie: `Ctrl+C`.

Sprawdzenie bez startowania modułów:

```bash
python3 main.py --platform x86 --config config/bcm_config_test.yaml --dry-run
```

Powinno wypisać **5 modules would load** — `bluetooth` i `wifi_ap` to
podsystemy startowane wprost w `main.py`, więc nie liczą się do tej sumy.

### 6.2 Kiosk

Na etapie testów wystarczy Chromium ręcznie:

```bash
chromium --app=http://localhost:5002 --window-size=1024,600 --start-fullscreen
```

Pełny kiosk z autologinem, splashem i usługami systemd zostaw na wersję
docelową — §7–§8 [`WDROZENIE_M910Q.md`](WDROZENIE_M910Q.md).

### 6.3 Kolejność załączania

```
 1. Rozłącznik masy ROZWARTY, bank odłączony, ładowarka odłączona
 2. Nastawy XL6019, XH-M609, boostu i rozłącznika nadnapięciowego
    sprawdzone na zasilaczu laboratoryjnym — wszystkie cztery
 3. Bezpieczniki na pakietach założone, bank złożony i zmierzony
 4. Bank → XH-M609 (bezpiecznik 15 A)
 5. Pomiar napięcia na wyjściu XL6019 BEZ podłączonego M910q → 19,5 V
 6. Dopiero teraz M910q
 7. Tor ładowania podłączany JAKO OSTATNI, przy zgaszonym silniku
 8. Rozruch silnika i pomiar prądu ładowania cęgami/bocznikiem
```

Punkt 5 pomijany „bo przecież ustawiałem" to najczęstszy sposób na zabicie
płyty głównej. Punkt 7 pomijany to najczęstszy sposób na zabicie banku.

Pełna procedura siedmioetapowa (z pomiarami na każdym kroku):
[`ZASILANIE_BUFOROWANE.md`](ZASILANIE_BUFOROWANE.md) §11.

---

## 7. Odbiór

**Software**

```
[ ] python3 main.py --dry-run pokazuje 5 modułów
[ ] curl http://localhost:5002 zwraca HTML
[ ] Dashboard widoczny na ekranie 7", dotyk działa
[ ] wpctl status pokazuje analogowe wyjście jako domyślny sink
[ ] Dźwięk słychać (speaker-test)
[ ] Przyciski SWC wywołują akcje (głośność, utwory)
[ ] Modem LTE widoczny w nmcli device, BCM raportuje łącze
[ ] hciconfig pokazuje class 0x620420 PO starcie BCM
[ ] Android Auto łączy się bezprzewodowo, bez kabla
[ ] Po restarcie telefon łączy się sam (boot sweep)
```

**Zasilanie — postój**

```
[ ] Napięcie na wtyku M910q ≥ 19,0 V pod obciążeniem
[ ] Po 30 min pracy XL6019 nie parzy w dotyku
[ ] XH-M609 odcina przy 11,00 V (test zasilaczem, nie rozładowywaniem banku)
[ ] Kluczyk OFF → domena B zanika w całości (pomiar na wyjściu przekaźnika)
[ ] Pobór z banku przy kluczyku OFF = pobór własny XH-M609 — ZMIERZ i zapisz
```

**Zasilanie — ładowanie**

```
[ ] Silnik zgaszony → VSR rozwarty, zerowy prąd z akumulatora rozruchowego
[ ] Silnik pracuje → VSR zwiera się w ciągu kilku sekund
[ ] Prąd wyjściowy boostu nie przekracza nastawy CC (§3.3)
[ ] Napięcie na banku po godzinie jazdy w przedziale 14,35–14,45 V
[ ] Prąd ładowania spada w miarę ładowania (dowód, że moduł REGULUJE,
    a nie stoi w pass-through — §3.2)
[ ] Rozłącznik nadnapięciowy odcina przy 15,30 V (test zasilaczem)
[ ] Moduł boost po 30 min jazdy w granicach temperatury (radiator, przewiew)
```

Wynik pomiaru poboru XH-M609 zapisz — od niego zależy, czy na dłuższy postój
wystarczy 5 pakietów, czy trzeba dołożyć pozostałe trzy (§3.4).

---

## 8. Czego celowo nie ma

| Nie ma | Wróci przy |
|--------|-----------|
| Domeny A (Nano ×2, HM-10, RXB6, przekaźniki) | dokupieniu płytek + buck 12 → 5 V |
| Kompensacji temperaturowej ładowania | ładowarce B2B (wariant A, §5.2 `ZASILANIE_BUFOROWANE.md`) |
| Modułu `power` w BCM | wejściu zapłonu, którego x86 nie ma — §1 |
| Drugiego ekranu | panelu 6,86" — jest hot-plug, wystarczy wpiąć |
| OBD / K-Line | CP2102 + L9637D |
| Kamer, parkowania, czujników | grabera, HC-SR04, DS18B20, obu Nano |
| Wzmacniacza i głośników | zakupie gotowego modułu (osobna gałąź) |
| Współdzielenia internetu (ALFA-NET) | osobnym dongle'u WiFi — §5.6 |

---

## 9. Droga do wersji docelowej

Kolejność, w jakiej warto to rozbudowywać — każdy krok jest niezależny
i weryfikowalny osobno:

| Krok | Co dochodzi | Co włączyć w configu |
|------|-------------|---------------------|
| 1 | ekran 10,1" 1280×800 | `display.dashboard` → 1280×800 (czyli `bcm_config.yaml`) |
| 2 | wzmacniacz + głośniki | bez zmian w configu — osobna gałąź zasilania |
| 3 | DAC USB ES9038Q2M | bez zmian — zmiana domyślnego sinka PipeWire |
| 4 | CP2102 + L9637D | `obd`, `obd.use_real_hardware: true` |
| 5 | Nano #2 (sensor hub) | `environment`, `rain_sensor`, `blinker_monitor` |
| 6 | Nano #1 + przekaźniki + buck domeny A | `central_lock`, `lighting` |
| 7 | kamery + graber | `camera`, `crash_detect` |
| 8 | GPS | `location`, `tracking` |
| 9 | ekran 6,86" | `small_display` (hotplug — wystarczy wpiąć) |
| 10 | ładowarka B2B zamiast VSR + boost | bez zmian w configu — absorpcja 14,4 V, próg 15,30 V, przewód 6 mm² |

Po każdym kroku przełóż odpowiedni klucz z `bcm_config_test.yaml` albo
przejdź na `bcm_config.yaml`, gdy większość będzie już podłączona.

---

## Powiązane dokumenty

| Dokument | Zakres |
|----------|--------|
| [`WDROZENIE_M910Q.md`](WDROZENIE_M910Q.md) | wdrożenie docelowe, pełne |
| [`ZASILANIE_BUFOROWANE.md`](ZASILANIE_BUFOROWANE.md) | warianty ładowania, nastawy modułów, sprawdzenia przed załączeniem |
| [`SCHEMATY_POLACZEN.md`](SCHEMATY_POLACZEN.md) | tabele połączeń dla wersji docelowej |
| [`ARDUINO_SETUP_GUIDE.md`](ARDUINO_SETUP_GUIDE.md) | Pro Micro, kalibracja SWC |
| [`URUCHOMIENIE.md`](URUCHOMIENIE.md) | symulacja bez sprzętu, przełączniki modułów |
