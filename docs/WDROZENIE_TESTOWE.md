# Wdrożenie testowo-rozwojowe — minimalny zestaw

Wariant do bieżącej weryfikacji i poprawek: **Android Auto + dźwięk przez
mini-jack M910q, ekran 7", przyciski SWC, modem LTE**, zasilanie z posiadanego
banku i modułów. Wszystko pozostałe wyłączone.

Wdrożenie docelowe (pełne): [`WDROZENIE_M910Q.md`](WDROZENIE_M910Q.md).

> **Ekran 7" to konfiguracja tymczasowa.** Docelowy panel to **10,1"
> 1280×800**, opcjonalnie drugi **6,86" 1280×480** — i tak jest ustawione
> w `config/bcm_config.yaml`. Ten wariant używa osobnego pliku
> `config/bcm_config_bench.yaml` z 1024×600, żeby nie ruszać konfiguracji
> produkcyjnej.

---

## Spis treści

1. [Co uruchamiamy](#1-co-uruchamiamy)
2. [Co już masz](#2-co-już-masz)
3. [Zasilanie — wersja minimalna](#3-zasilanie--wersja-minimalna)
4. [Lista zakupowa](#4-lista-zakupowa)
5. [Instalacja software'u](#5-instalacja-softwareu)
6. [Uruchomienie](#6-uruchomienie)
7. [Odbiór](#7-odbiór)
8. [Czego celowo nie ma](#8-czego-celowo-nie-ma)
9. [Droga do wersji docelowej](#9-droga-do-wersji-docelowej)

---

## 1. Co uruchamiamy

Pięć modułów zamiast dwudziestu ośmiu:

| Moduł | Po co | Czego wymaga |
|-------|-------|--------------|
| `dashboard` | frontend na porcie 5002 | ekran 7" + Chromium |
| `multimedia` | **Android Auto** (openauto) | telefon po kablu USB |
| `input` | **przyciski SWC** | Arduino Pro Micro (USB HID) |
| `audio` | głośność i EQ | wyjście analogowe M910q |
| `network` | status łącza | modem LTE (przez NetworkManager) |

Reszta — OBD, kamery, parkowanie, czujniki, przekaźniki, GPS, alarm,
Bluetooth, WiFi AP — **wyłączona**, bo nie ma podłączonego sprzętu. Włączanie
modułów bez hardware'u produkuje tylko szum w logach.

### Dwa ustalenia z kodu, które upraszczają ten wariant

**Dźwięk nie wymaga DAC-a USB.** `src/audio/pipewire_ctrl.py` na x86 używa
**domyślnego sinka PipeWire** — czyli tego, co ustawisz w systemie. Wyjście
analogowe M910q (mini-jack) działa bez żadnych zmian w kodzie. DAC USB
ES9038Q2M to podniesienie jakości, nie warunek uruchomienia.

**Modem LTE nie wymaga konfiguracji w BCM.** `src/network/lte.py` na x86
tylko **raportuje** stan łącza (`lte.connected`, `lte.signal`, `lte.ip`);
samo połączenie robi NetworkManager. Huawei E3372 w trybie HiLink zgłasza się
jako karta sieciowa i działa od podłączenia.

---

## 2. Co już masz

| Element | Uwaga |
|---------|-------|
| Lenovo M910q | |
| Ekran 7" | 1024×600, HDMI + dotyk USB |
| Pody SWC + dekoder | rezystorowa drabinka → wejście analogowe |
| Modem LTE Huawei E3372 | HiLink, USB |
| Akumulatory CSB HR1221W × 8 | AGM 12 V / 5,1 Ah |
| **XL6019** | step-up 12 → 19,5 V dla M910q |
| **XH-M609** | LVD, ochrona banku przed rozładowaniem |

---

## 3. Zasilanie — wersja minimalna

To jest miejsce, gdzie da się zaoszczędzić najwięcej, i to bez pogorszenia
bezpieczeństwa.

### 3.1 Czego NIE potrzebujesz na stanowisku

Na biurku nie ma alternatora, więc **cały tor ładowania jest zbędny**:

| Element | Dlaczego zbędny na stanowisku |
|---------|------------------------------|
| Ładowarka CC-CV / B2B | nie ma z czego ładować — bank ładujesz między sesjami ładowarką sieciową |
| VSR (rozdział ładowania) | nie ma akumulatora rozruchowego, od którego trzeba się odseparować |
| Rozłącznik nadnapięciowy | zagrożeniem był alternator; ładowarka sieciowa ma własną regulację |
| Przekaźnik zapłonu | włączasz wyłącznikiem, nie kluczykiem |
| Dioda TVS, kondensator wejściowy | chroniły przed load dumpem alternatora |

To oszczędza **od 150 do 1000 PLN** (w zależności od wariantu ładowarki)
i wycina najbardziej kłopotliwą część układu.

### 3.2 Czego potrzebujesz

```
bank AGM (2–3 pakiety)
   │  bezpiecznik 10 A na „+” każdego pakietu
   ▼
XH-M609 (LVD)  ── bezpiecznik 15 A przed VIN+
   │  odcięcie 11,00 V · powrót 12,60 V
   ▼
wyłącznik / rozłącznik
   │
   ▼
XL6019 (step-up 12 → 19,5 V)  ── bezpiecznik 5 A na wyjściu
   │
   ▼
M910q — oryginalny wtyk
```

Cztery elementy, wszystkie już masz poza bezpiecznikami i przewodami.

### 3.3 Ile pakietów

**Dwa do trzech, nie pięć.** Na stanowisku mniej energii to mniej rzeczy, które
mogą pójść źle, a czasu i tak wystarcza:

| Pakiety | Pojemność | Czas pracy przy ~2,7 A (M910q ~30 W) |
|---------|-----------|--------------------------------------|
| 2 | 10,2 Ah | ~1,9 h do 50 % DoD |
| 3 | 15,3 Ah | ~2,8 h do 50 % DoD |
| 5 | 25,5 Ah | ~4,7 h do 50 % DoD |

Sesja rozwojowa rzadko trwa dłużej niż dwie godziny bez przerwy, a lżejszy
zestaw łatwiej przestawić.

> **Bezpieczników na pakietach nie pomijaj nawet na stanowisku.** Zwarty
> HR1221W potrafi oddać ponad 100 A — 5 Ah wystarczy, żeby zapalić przewód.

### 3.4 Nastawy modułów

| Moduł | Nastawa | Uwaga |
|-------|---------|-------|
| **XL6019** | wyjście **19,5 V** pod obciążeniem | ustaw multimetrem, zabezpiecz potencjometr |
| **XH-M609** | odcięcie **11,00 V**, powrót **12,60 V** | sprawdź, czy pracuje stabilnie przy 11 V |

Obowiązkowe sprawdzenia obu modułów przed pierwszym załączeniem:
[`ZASILANIE_BUFOROWANE.md`](ZASILANIE_BUFOROWANE.md) §3.4 i §7.3.

> **Limit poboru CPU ustaw od razu**, nie „potem". XL6019 daje ok. 45 W,
> a M910q pod pełnym obciążeniem czterech wątków dobija do 55 W. Instrukcja:
> [`ZASILANIE_BUFOROWANE.md`](ZASILANIE_BUFOROWANE.md) §3.5a.

---

## 4. Lista zakupowa

### 4.1 Obowiązkowe

| # | Element | Specyfikacja | Cena (PLN) |
|---|---------|--------------|-----------|
| 1 | Oprawki bezpiecznikowe inline + wkładki | 10 A × 3 (pakiety), 15 A × 1 (LVD), 5 A × 1 (step-up) | 25–40 |
| 2 | Przewód 2,5 mm² | czerwony + czarny, po 2 m | 20–30 |
| 3 | Przewód 1,5 mm² | czerwony + czarny, po 2 m | 12–20 |
| 4 | Nasuwki F2 6,35 mm izolowane | do zacisków HR1221W, komplet | 15–25 |
| 5 | Konektory oczkowe + koszulki termokurczliwe | zestaw | 20–30 |
| 6 | Wyłącznik / rozłącznik | kołyskowy 20 A albo rozłącznik masy | 15–40 |
| 7 | Kabel USB do telefonu | dobrej jakości, do **Android Auto po kablu** | 20–40 |
| | | **Razem** | **~130–225 PLN** |

### 4.2 Zależne od tego, co już masz

| # | Element | Kiedy potrzebne | Cena (PLN) |
|---|---------|----------------|-----------|
| 8 | **Arduino Pro Micro** (ATmega32U4) | jeśli nie masz — pody SWC bez niego nie zadziałają | 40–60 |
| 9 | **Wtyk zasilania do M910q** | najtaniej: odetnij kabel od oryginalnego zasilacza (koszt 0). Kupować tylko, jeśli zasilacza nie masz | 0–40 |
| 10 | **Przejściówka DP → HDMI** | tylko jeśli Twój egzemplarz M910q ma wyjścia DisplayPort — sprawdź (§5.2) | 0–25 |
| 11 | **Ładowarka sieciowa AGM** | do doładowania banku między sesjami; zwykła prostownikowa z trybem AGM wystarcza | 0–250 |
| 12 | **Zaciskarka zapadkowa** | zaciski robione kombinerkami to najczęstsza usterka instalacji | 0–150 |

### 4.3 Warto, ale nie na start

| # | Element | Po co | Cena (PLN) |
|---|---------|-------|-----------|
| 13 | Woltomierz/amperomierz panelowy z bocznikiem | podgląd banku i poboru bez multimetru | 40–70 |
| 14 | Radiator + wentylator 40 mm do XL6019 | na stanowisku przy ~30 W jeszcze nie krytyczne, w aucie obowiązkowe | 20–35 |

### 4.4 Czego **nie** kupuj na tym etapie

| Element | Dlaczego |
|---------|----------|
| Ładowarka CC-CV / B2B | bez alternatora nie ma czego regulować — §3.1 |
| VSR, rozłącznik nadnapięciowy | jw. |
| DAC USB ES9038Q2M | mini-jack M910q wystarcza do weryfikacji — §1 |
| Karta WiFi MT7921 | AA po kablu nie potrzebuje P2P-GO |
| Wzmacniacz, głośniki | na stanowisku wystarczą głośniki komputerowe albo słuchawki |
| Drugi ekran, kamery, graber, czujniki | odpowiednie moduły są wyłączone |

**Realny koszt startu: ~130–225 PLN**, plus Pro Micro i ładowarka AGM,
jeśli ich nie masz.

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

### 5.4 Konfiguracja stanowiska

Repozytorium zawiera gotowy plik `config/bcm_config_bench.yaml`: pięć
modułów włączonych, reszta wyłączona, ekran 1024×600.

> `--config` **podmienia całą konfigurację**, nie nakłada się na
> `bcm_config.yaml`. Dlatego jest to pełna kopia z pozmienianymi kluczami,
> a nie krótka nakładka.

### 5.5 Firmware Pro Micro

```bash
make -C arduino rotary_encoder-upload PORT=/dev/ttyACM0
```

Pody SWC podłącz do **A0** (Pod 1) i **A6** (Pod 2), dekoder: czerwony → ACC
(na stanowisku +12 V), czarny → masa. Kalibracja: przytrzymaj HOME + BACK
przy starcie płytki i naciskaj kolejne przyciski wg podpowiedzi na porcie
szeregowym. Progi zapisują się w EEPROM.

Szczegóły: [`ARDUINO_SETUP_GUIDE.md`](ARDUINO_SETUP_GUIDE.md).

### 5.6 Android Auto

`openauto` kompilowany ze źródeł — procedura w
[`WDROZENIE_M910Q.md`](WDROZENIE_M910Q.md) §13.3. Na tym etapie używamy
**połączenia po kablu USB**: bez Bluetootha i bez WiFi P2P, czyli o dwie
warstwy mniej do diagnozowania.

---

## 6. Uruchomienie

### 6.1 Ręcznie (do rozwoju)

```bash
cd /opt/bcm
source .venv/bin/activate
python3 main.py --platform x86 --config config/bcm_config_bench.yaml --frontend
```

Dashboard: `http://localhost:5002`. Zatrzymanie: `Ctrl+C`.

Sprawdzenie bez startowania modułów:

```bash
python3 main.py --platform x86 --config config/bcm_config_bench.yaml --dry-run
```

Powinno wypisać **5 modules would load**.

### 6.2 Kiosk

Na stanowisku wystarczy Chromium ręcznie:

```bash
chromium --app=http://localhost:5002 --window-size=1024,600 --start-fullscreen
```

Pełny kiosk z autologinem, splashem i usługami systemd zostaw na wersję
docelową — §7–§8 [`WDROZENIE_M910Q.md`](WDROZENIE_M910Q.md).

### 6.3 Kolejność załączania

```
1. Bank odłączony, wyłącznik ROZWARTY
2. Nastawy XL6019 i XH-M609 sprawdzone na zasilaczu laboratoryjnym
3. Bezpieczniki na pakietach założone
4. Bank podłączony do XH-M609 (bezpiecznik 15 A)
5. Pomiar napięcia na wyjściu XL6019 BEZ podłączonego M910q → 19,5 V
6. Dopiero teraz M910q
```

Punkt 5 pomijany „bo przecież ustawiałem" to najczęstszy sposób na zabicie
płyty głównej.

---

## 7. Odbiór

```
[ ] python3 main.py --dry-run pokazuje 5 modułów
[ ] curl http://localhost:5002 zwraca HTML
[ ] Dashboard widoczny na ekranie 7"
[ ] Dotyk działa
[ ] wpctl status pokazuje analogowe wyjście jako domyślny sink
[ ] Dźwięk słychać (speaker-test)
[ ] Przyciski SWC wywołują akcje (głośność, utwory)
[ ] Modem LTE widoczny w nmcli device, BCM raportuje łącze
[ ] Android Auto łączy się po kablu USB
[ ] Napięcie na wtyku M910q ≥ 19,0 V pod obciążeniem
[ ] Po 30 min pracy XL6019 nie parzy w dotyku
[ ] XH-M609 odcina przy 11,00 V (test zasilaczem, nie rozładowywaniem banku)
```

---

## 8. Czego celowo nie ma

| Nie ma | Wróci przy |
|--------|-----------|
| Ładowania banku | zabudowie w aucie (§5 `ZASILANIE_BUFOROWANE.md`) |
| Domen A/B i przekaźnika zapłonu | zabudowie w aucie |
| Drugiego ekranu | panelu 6,86" — jest hot-plug, wystarczy wpiąć |
| OBD / K-Line | CP2102 + L9637D |
| Kamer, parkowania, czujników | grabera, HC-SR04, DS18B20, obu Nano |
| Bluetooth, WiFi AP | karty MT7921 i przejścia na AA wireless |
| Wzmacniacza i głośników | zakupie gotowego modułu |

---

## 9. Droga do wersji docelowej

Kolejność, w jakiej warto to rozbudowywać — każdy krok jest niezależny
i weryfikowalny osobno:

| Krok | Co dochodzi | Co włączyć w configu |
|------|-------------|---------------------|
| 1 | ekran 10,1" 1280×800 | `display.dashboard` → 1280×800 (czyli `bcm_config.yaml`) |
| 2 | karta MT7921 → AA wireless | `bluetooth`, `wifi_ap` |
| 3 | wzmacniacz + głośniki | bez zmian w configu |
| 4 | CP2102 + L9637D | `obd`, `obd.use_real_hardware: true` |
| 5 | Nano #2 (sensor hub) | `environment`, `rain_sensor`, `blinker_monitor` |
| 6 | Nano #1 + przekaźniki | `central_lock`, `lighting` |
| 7 | kamery + graber | `camera`, `crash_detect` |
| 8 | GPS | `location`, `tracking` |
| 9 | ekran 6,86" | `small_display` (hotplug — wystarczy wpiąć) |
| 10 | zabudowa w aucie, pełne zasilanie | `power` + tor ładowania |

Po każdym kroku przełóż odpowiedni klucz z `bcm_config_bench.yaml` albo
przejdź na `bcm_config.yaml`, gdy większość będzie już podłączona.

---

## Powiązane dokumenty

| Dokument | Zakres |
|----------|--------|
| [`WDROZENIE_M910Q.md`](WDROZENIE_M910Q.md) | wdrożenie docelowe, pełne |
| [`ZASILANIE_BUFOROWANE.md`](ZASILANIE_BUFOROWANE.md) | nastawy XL6019 i XH-M609, sprawdzenia przed załączeniem |
| [`SCHEMATY_POLACZEN.md`](SCHEMATY_POLACZEN.md) | tabele połączeń dla wersji docelowej |
| [`ARDUINO_SETUP_GUIDE.md`](ARDUINO_SETUP_GUIDE.md) | Pro Micro, kalibracja SWC |
| [`URUCHOMIENIE.md`](URUCHOMIENIE.md) | symulacja bez sprzętu, przełączniki modułów |
