# Arduino od zera — pierwsze wgranie firmware

Przewodnik dla kogoś, kto **nigdy nie miał do czynienia z Arduino**. Zero
założeń. Od „czym to w ogóle podłączyć" do działającego sterownika zasilania
na biurku.

Efekt końcowy: Arduino Nano, które wykrywa zapłon i „naciska" przycisk
zasilania M910q — sprawdzone bez auta, na samym kablu USB.

> **Cały ten przewodnik robisz przy biurku.** Nic tu nie wymaga auta,
> akumulatorów ani 12 V. Arduino zasila się z USB komputera.

---

## Spis treści

1. [Co to w ogóle jest](#1-co-to-w-ogóle-jest)
2. [Czego potrzebujesz](#2-czego-potrzebujesz)
3. [Instalacja Arduino IDE](#3-instalacja-arduino-ide)
4. [Sterownik USB — najczęstsza przeszkoda](#4-sterownik-usb--najczęstsza-przeszkoda)
5. [Pierwsze podłączenie płytki](#5-pierwsze-podłączenie-płytki)
6. [Test „czy w ogóle działa" — miganie diodą](#6-test-czy-w-ogóle-działa--miganie-diodą)
7. [Otwarcie firmware BCM](#7-otwarcie-firmware-bcm)
8. [Konfiguracja minimalna na pierwszy raz](#8-konfiguracja-minimalna-na-pierwszy-raz)
9. [Wgranie i sprawdzenie](#9-wgranie-i-sprawdzenie)
10. [Test działania na biurku](#10-test-działania-na-biurku)
11. [Kiedy coś nie działa](#11-kiedy-coś-nie-działa)
12. [Druga płytka — Pro Micro](#12-druga-płytka--pro-micro)
13. [Co dalej](#13-co-dalej)

---

## 1. Co to w ogóle jest

Arduino Nano to mały komputerek wielkości gumy do żucia. Nie ma systemu
operacyjnego — wgrywasz w niego **jeden program**, który startuje po
podaniu zasilania i chodzi w kółko do odcięcia prądu.

Trzy rzeczy, które warto wiedzieć od razu:

| | |
|---|---|
| **Program nazywa się „sketch"** | to zwykły plik tekstowy `.ino` |
| **Wgrywanie idzie po USB** | ten sam kabel służy do zasilania, wgrywania i podglądu tego, co płytka „mówi" |
| **Wgranie nadpisuje poprzedni program** | nie da się mieć dwóch naraz, nie ma czego zepsuć na stałe |

**Niczego nie zniszczysz przez złe wgranie.** Płytkę można zepsuć podając
na nią 12 V albo zwierając zasilanie — ale nie programem. Wgrywaj śmiało.

---

## 2. Czego potrzebujesz

### Kabel

To pierwsza pułapka. Arduino Nano ma zwykle gniazdo **mini-USB** (starsze,
trapez) albo **micro-USB** (nowsze, płaskie) — sprawdź, które masz na
płytce, i dobierz kabel.

> **Kabel musi być „do danych", nie sam do ładowania.** Tanie kable od
> ładowarek mają często tylko żyły zasilania i **nie da się nimi nic
> wgrać** — komputer w ogóle nie zobaczy płytki. Jeśli podłączasz i nic
> się nie dzieje, to jest podejrzany numer jeden.

### Komputer

Windows, Linux albo macOS — wszystko jedno. Może to być ten sam M910q,
na którym pracuje BCM.

### Nic więcej

Na tym etapie **nie podłączaj nic do pinów płytki**. Żadnych przewodów,
żadnego 12 V, żadnego przekaźnika. Sam kabel USB.

---

## 3. Instalacja Arduino IDE

Arduino IDE to program na komputer, w którym edytujesz sketch i wysyłasz
go do płytki.

1. Wejdź na **https://www.arduino.cc/en/software**
2. Pobierz **Arduino IDE 2.x** dla swojego systemu
3. Zainstaluj standardowo (Windows: `.exe`, macOS: przeciągnij do
   Applications, Linux: AppImage — nadaj mu prawo wykonywania)

Po pierwszym uruchomieniu IDE może chwilę pobierać komponenty. Poczekaj.

### Dodanie obsługi płytki

IDE domyślnie zna płytki Arduino, ale upewnijmy się:

1. **Tools → Board → Boards Manager…** (albo ikona płytki na lewym pasku)
2. Wpisz `Arduino AVR`
3. Znajdź **„Arduino AVR Boards"** i kliknij **Install**, jeśli nie ma
   przy nim wersji

---

## 4. Sterownik USB — najczęstsza przeszkoda

Oryginalne Arduino Nano ma układ FTDI. **Klony — a Twój Nano V3 prawie
na pewno jest klonem — mają układ CH340.** To zmienia jedną rzecz:
komputer musi mieć sterownik CH340.

| System | Co zrobić |
|--------|-----------|
| **Linux** | nic — sterownik `ch341` jest w jądrze od lat. Płytka pojawi się jako `/dev/ttyUSB0` |
| **Windows 10/11** | zwykle instaluje się sam przez Windows Update. Jeśli nie: pobierz „CH340 driver" ze strony producenta (wch.cn) i zainstaluj |
| **macOS** | nowsze wersje mają sterownik wbudowany; jeśli nie widać portu, poszukaj „CH34x macOS driver" |

**Jak sprawdzić, czy zadziałało:** podłącz płytkę i zobacz, czy pojawia się
nowy port (§5). Jeśli tak — sterownik jest w porządku.

> **Na Linuksie może brakować uprawnień do portu.** Objaw: port widać, ale
> IDE pisze „Permission denied". Naprawa:
> ```bash
> sudo usermod -aG dialout $USER
> ```
> i **wyloguj się i zaloguj ponownie** (albo zrestartuj komputer).

---

## 5. Pierwsze podłączenie płytki

1. Podłącz Nano kablem USB do komputera
2. Na płytce powinna zapalić się mała dioda zasilania (zwykle czerwona lub
   zielona), a druga może zamigać kilka razy
3. W Arduino IDE: **Tools → Port**

Powinieneś zobaczyć nowy port:

| System | Jak wygląda |
|--------|-------------|
| Windows | `COM3`, `COM4`, `COM7`… (numer dowolny) |
| Linux | `/dev/ttyUSB0` |
| macOS | `/dev/cu.wchusbserial…` |

**Sztuczka na rozpoznanie, który to port:** otwórz listę portów, zapamiętaj,
odłącz Arduino, otwórz listę ponownie — port, który zniknął, to Twój.

### Wybór płytki

**Tools → Board → Arduino AVR Boards → Arduino Nano**

Potem **Tools → Processor**. Tu są dwie opcje i to bywa problem:

- `ATmega328P`
- `ATmega328P (Old Bootloader)`

**Klony prawie zawsze potrzebują „Old Bootloader".** Jeśli wgrywanie
kończy się błędem o timeoutach — wróć tu i przełącz na drugą opcję.

---

## 6. Test „czy w ogóle działa" — miganie diodą

Zanim ruszymy firmware BCM, wgraj gotowy przykład. To zajmuje minutę
i oddziela „coś nie działa w moim układzie" od „coś nie działa w ogóle".

1. **File → Examples → 01.Basics → Blink**
2. Kliknij strzałkę **→** (Upload) na górnym pasku
3. Poczekaj — na dole zobaczysz pasek postępu, potem `Done uploading`

**Efekt:** dioda `L` na płytce miga raz na sekundę.

Jeśli to zadziałało, masz potwierdzone: kabel jest dobry, sterownik jest,
port jest właściwy, płytka żyje. **Reszta to już tylko właściwy program.**

Jeśli nie zadziałało — [§11](#11-kiedy-coś-nie-działa).

---

## 7. Otwarcie firmware BCM

Firmware leży w repozytorium, w katalogu `arduino/sensor_hub/`.

1. **File → Open…**
2. Wskaż plik **`arduino/sensor_hub/sensor_hub.ino`**
3. IDE otworzy go w nowym oknie

> **Katalog musi się nazywać tak samo jak plik.** Arduino IDE tego wymaga
> — i tak właśnie jest w repo (`sensor_hub/sensor_hub.ino`), więc nic nie
> przenoś ani nie zmieniaj nazw.

---

## 8. Konfiguracja minimalna na pierwszy raz

Sketch obsługuje dużo rzeczy: drzwi, ręczny, deszcz, temperaturę, czujniki
parkowania. **Na pierwszy raz włączamy tylko to, co potrzebne do sterowania
zasilaniem** — mniej rzeczy, mniej powodów do porażki, zero dodatkowych
bibliotek do instalowania.

Na początku pliku znajdź blok `#define FEATURE_…` i ustaw go tak:

```cpp
// #define FEATURE_DOORS      // ← zakomentowane
// #define FEATURE_HBRAKE     // ← zakomentowane
#define FEATURE_IGN           // ← ZOSTAJE
// #define FEATURE_RAIN       // ← zakomentowane
// #define FEATURE_TEMP       // ← zakomentowane (to ono wymaga bibliotek)
#define FEATURE_PWRBTN        // ← ZOSTAJE
// #define FEATURE_PWRLED     // ← na razie zakomentowane, patrz niżej
```

**Zakomentować = dopisać `//` na początku linii.** Odkomentować = usunąć te
dwa znaki. To wszystko.

### Dlaczego akurat tak

| Wyłączamy | Powód |
|-----------|-------|
| `FEATURE_TEMP` | wymaga doinstalowania bibliotek OneWire i DallasTemperature — niepotrzebna komplikacja na start |
| `FEATURE_DOORS`, `HBRAKE`, `RAIN` | nie masz jeszcze podłączonych czujników; bez nich sketch wysyłałby same zera |
| `FEATURE_PWRLED` | wymaga podłączenia do diody panelu M910q, czego jeszcze nie zrobiłeś. **Na biurku wręcz przeszkadza** — patrz ostrzeżenie w §10 |

`FEATURE_IGN` i `FEATURE_PWRBTN` zostają, bo to właśnie one są przedmiotem
testu.

---

## 9. Wgranie i sprawdzenie

1. Upewnij się, że **Board = Arduino Nano** i **Port** wskazuje Twoją płytkę
2. Kliknij **✓** (Verify) — to tylko kompilacja, bez wysyłania.
   Powinno skończyć się `Done compiling`
3. Kliknij **→** (Upload)
4. Czekaj na `Done uploading`

### Podgląd tego, co płytka mówi

1. **Tools → Serial Monitor** (albo ikona lupy/monitora w prawym górnym rogu)
2. W prawym dolnym rogu monitora ustaw prędkość na **115200 baud**

Powinieneś zobaczyć:

```
BCM v8.5 Sensor Hub ready
IGN:0
PWR:UNKNOWN
IGN:0
PWR:UNKNOWN
```

…i tak co dwie sekundy. **To jest sukces.** Płytka żyje, czyta zapłon
(na razie „wyłączony") i raportuje stan komputera jako „nieznany".

> **Otwarcie Serial Monitora resetuje płytkę.** To normalne — zobaczysz
> wtedy ponownie „ready". Nie jest to objaw usterki.

---

## 10. Test działania na biurku

Teraz sprawdzimy, czy logika naprawdę działa — **bez auta i bez 12 V**.

Wejście zapłonu (pin **D9**) jest skonfigurowane jako `INPUT_PULLUP`:
w spoczynku ma stan wysoki, a **zwarcie do masy oznacza „zapłon włączony"**.
Docelowo robi to transoptor; na biurku wystarczy kawałek drutu.

### Potrzebny sprzęt

Jeden przewód połączeniowy (albo spinacz, albo kawałek drutu). Serio, tyle.

### Przebieg

| Krok | Co robisz | Co powinieneś zobaczyć w Serial Monitor |
|------|-----------|------------------------------------------|
| 1 | Nic — poczekaj 5 s po starcie | `IGN:0`, `PWR:UNKNOWN` |
| 2 | Zewrzyj **D9** z **GND** (dowolny pin GND) | po ~2 s: `IGN:1`, potem `PWRACT:SHORT` i `PWR:RUNNING` |
| 3 | Odczekaj 20 s | nic nowego — to cisza po impulsie |
| 4 | Rozewrzyj D9 od GND | po ~2 s: `IGN:0`, potem `PWRACT:SHORT` i `PWR:SLEEP` |

**`PWRACT:SHORT` to moment, w którym płytka „naciska" przycisk.** Gdyby był
podłączony moduł przekaźnika, usłyszałbyś teraz kliknięcie.

Jeśli te cztery kroki przechodzą — **firmware działa poprawnie i możesz
przejść do montażu**.

> **Dlaczego `FEATURE_PWRLED` przeszkadza na biurku.** Z włączonym odczytem
> diody panelu płytka patrzy na pin A1. Nic tam nie jest podłączone, więc
> odczyta „dioda zgaszona" = „komputer wyłączony". W kroku 4 nie wyśle
> wtedy impulsu — i słusznie, bo nie usypia się czegoś, co jest wyłączone.
> Wygląda to jak usterka, a jest poprawnym zachowaniem. Dlatego na testy
> biurkowe zostaw tę funkcję zakomentowaną.

### Podłączenie przekaźnika (opcjonalnie, żeby usłyszeć kliknięcie)

Jeżeli masz już moduł przekaźnika 1-kanałowego i chcesz sprawdzić całość:

| Moduł przekaźnika | Arduino Nano |
|-------------------|--------------|
| `VCC` | `5V` |
| `GND` | `GND` |
| `IN` | `A0` |

Styków (`COM`, `NO`) na razie **nie podłączaj do niczego** — chodzi tylko
o usłyszenie kliknięcia w krokach 2 i 4.

---

## 11. Kiedy coś nie działa

| Objaw | Najczęstsza przyczyna | Co zrobić |
|-------|----------------------|-----------|
| **Brak portu w Tools → Port** | kabel tylko do ładowania, bez żył danych | weź inny kabel — to statystycznie numer jeden |
| j.w. | brak sterownika CH340 | §4 |
| j.w. | uszkodzone gniazdo USB na płytce | delikatnie poruszaj wtyczką — jeśli port miga i znika, gniazdo jest wyrwane |
| **`avrdude: stk500_recv(): programmer is not responding`** | zły wybór „Processor" | Tools → Processor → **ATmega328P (Old Bootloader)** |
| j.w. | zły port | sprawdź metodą odłącz–podłącz z §5 |
| j.w. | Serial Monitor trzyma port | zamknij Serial Monitor i spróbuj ponownie |
| **`Permission denied` (Linux)** | brak grupy `dialout` | `sudo usermod -aG dialout $USER`, wyloguj się i zaloguj |
| **`Expected signature for ATmega328P`** | masz **328PB**, nie 328P | patrz niżej |
| **W Serial Monitor same krzaki** | zła prędkość | ustaw **115200** w prawym dolnym rogu |
| **Kompilacja: `OneWire.h: No such file`** | włączone `FEATURE_TEMP` | zakomentuj je (§8) albo doinstaluj biblioteki |
| **Nic się nie dzieje po zwarciu D9** | zwarcie do złego pinu | GND jest kilka — użyj tego obok pinu `5V` |

### Jeśli avrdude narzeka na sygnaturę (ATmega328PB)

Twój Nano V3 może mieć układ **ATmega328PB** — to nie to samo co 328P
i standardowy rdzeń Arduino go nie zna. Objaw jest jednoznaczny:

```
avrdude: Expected signature for ATmega328P is 1E 95 0F
         Double check chip, or use -F to override this check.
```

Najprostsze rozwiązanie — **MiniCore**:

1. **File → Preferences → Additional boards manager URLs**
2. Wklej:
   ```
   https://mcudude.github.io/MiniCore/package_MCUdude_MiniCore_index.json
   ```
3. **Tools → Board → Boards Manager…** → wpisz `MiniCore` → **Install**
4. **Tools → Board → MiniCore → ATmega328**
5. Ustaw: **Variant → 328PB**, **Clock → 16 MHz external**,
   **Bootloader → Yes (UART0)**
6. Port jak wcześniej, i wgrywaj

Sam firmware kompiluje się na obu układach bez zmian — używa wyłącznie
peryferiów, które mają jedno i drugie.

---

## 12. Druga płytka — Pro Micro

Pro Micro (ATmega32U4) obsługuje przyciski na kierownicy i udaje klawiaturę
USB. Wgrywa się prawie tak samo, z dwiema różnicami.

**Wybór płytki:** Tools → Board → Arduino AVR Boards → **Arduino Leonardo**
(Pro Micro to jego odpowiednik; niektóre paczki mają wprost „SparkFun Pro
Micro").

**Reset przed wgraniem.** Pro Micro potrafi „zgubić" port po wgraniu
programu, który go zajmuje. Jeśli wgrywanie się nie udaje:

1. Kliknij **Upload**
2. Gdy w konsoli pojawi się `Uploading…`, **szybko dwa razy zewrzyj pin
   `RST` z `GND`** (albo dwa razy naciśnij przycisk reset, jeśli płytka
   go ma)
3. Płytka wejdzie na ~8 s w tryb bootloadera i wgrywanie ruszy

Plik: **`arduino/rotary_encoder/rotary_encoder.ino`**.

> **Pro Micro nie jest potrzebne do sterowania zasilaniem.** Tym zajmuje
> się Nano. Pro Micro dochodzi wtedy, gdy podłączasz pody SWC.

---

## 13. Co dalej

Firmware działa na biurku. Kolejność montażu:

1. **Zbuduj układ wejściowy zapłonu** — transoptor PC817 i rezystory,
   wartości i schemat: [`../schematics/ignition_sense.svg`](../schematics/ignition_sense.svg)
2. **Podłącz moduł przekaźnika** równolegle do przycisku zasilania M910q —
   zaciski i numery przewodów w [`SCHEMATY_POLACZEN.md`](SCHEMATY_POLACZEN.md) §10.5
3. **Zasil Nano z MP1584**, nie z USB M910q — i **przetnij żyłę VBUS**
   w kablu USB. Powód: M910q odcina zasilanie portów w S3, więc płytka
   zasilana z USB zgasłaby razem z nim i nie miałaby czym nacisnąć przycisku
4. **Włącz `FEATURE_PWRLED`** dopiero po podłączeniu odczytu diody panelu

Szerszy kontekst — po co to wszystko i jak działa całość:
[`WDROZENIE_TESTOWE.md`](WDROZENIE_TESTOWE.md) §3.1a.

### Ponowne wgranie po zmianach

Kolejne wgrania to już tylko: podłącz USB → sprawdź Port → **Upload**.
Zmiana `#define`, zmiana progu, poprawka — za każdym razem ta sama droga.

### Dla wygodnych: bez klikania

Repozytorium ma też Makefile, jeśli wolisz terminal:

```bash
make -C arduino sensor_hub                       # sama kompilacja
make -C arduino sensor_hub-upload PORT=/dev/ttyUSB0
```

Wymaga zainstalowanego `arduino-cli`. **Na początek zostań przy IDE** —
Makefile jest wygodny, gdy już wiesz, co robisz.

---

## Powiązane dokumenty

| Dokument | Zakres |
|----------|--------|
| [`ARDUINO_SETUP_GUIDE.md`](ARDUINO_SETUP_GUIDE.md) | pełne tabele pinów wszystkich trzech płytek, kalibracja SWC |
| [`WDROZENIE_TESTOWE.md`](WDROZENIE_TESTOWE.md) | po co to sterowanie zasilaniem i ile kosztuje |
| [`SCHEMATY_POLACZEN.md`](SCHEMATY_POLACZEN.md) | zaciski i numery przewodów (§10.4 i §10.5) |
| [`../schematics/ignition_sense.svg`](../schematics/ignition_sense.svg) | schemat układu wejściowego z wartościami elementów |
