# Podsłuch K-Line i inżynieria wsteczna sygnałów (RPM, temperatura, itd.)

Ten dokument opisuje, jak **podsłuchać magistralę K-Line**, żeby poznać
kody (PID-y), których używa Twój ECU do wystawiania konkretnych wartości
— obroty silnika, temperatura cieczy, dawka wtrysku itd. — a potem
**wpisać je do BCM**, żeby dashboard czytał je sam, bez MES.

Dotyczy Alfy 156 1.9 JTD 8V ze sterownikiem **Bosch EDC15C7**, protokół
**KWP2000 (ISO 14230)** po jednoprzewodowej magistrali K-Line.

---

## 0. Najpierw sprostowanie sprzętowe (bo o to pytałeś)

**W wersji produkcyjnej K-Line NIE idzie przez Arduino i NIE przez FTDI.**
Projekt zakłada dedykowany moduł na USB:

```
M910q USB ──► CP2102 (USB-UART, Silicon Labs) ──► L9637D (transceiver K-Line) ──► OBD-II pin 7
```

- **CP2102** to mostek USB↔UART (jak FTDI FT232, ale inny producent —
  Silicon Labs, VID:PID `10c4:ea60`). To on daje `/dev/ttyUSB*`.
- **L9637D** to układ transceivera ISO 9141/14230 — zamienia logikę
  TTL 5 V na sygnalizację 12 V K-Line i realizuje półdupleks. Bez niego
  UART nie „dogada się" z magistralą 12 V.
- **Arduino** w tym projekcie obsługuje wyłącznie przyciski, wyjścia i
  czujniki (Pro Micro, 2× Nano) — **nie** diagnostykę silnika.

Pełny schemat: `docs/x86-production/05-kline-obd.html` +
`schematics/kline_circuit.svg`. Koszt modułu ~25–40 PLN.

> **Twój kabel VIAKEN KKL** ma w środku dokładnie to samo w jednej
> obudowie: mostek USB-UART (FTDI/CH340) + transceiver K-Line. Do
> **podsłuchu i inżynierii wstecznej używaj właśnie jego** — jest
> idealny. Moduł CP2102+L9637D zbudujesz dopiero do docelowej instalacji
> w aucie (żeby nie wisiał kabel diagnostyczny na stałe). Oba rozwiązania
> mówią tym samym protokołem, więc kody PID znalezione VIAKEN-em zadziałają
> 1:1 na module produkcyjnym.

> **Alternatywa na Arduino** — teoretycznie K-Line da się obsłużyć
> bezpośrednio na Arduino (UART sprzętowy + L9637D, bez CP2102), bo
> ATmega ma UART. To realne, ale **obecny kod BCM czyta K-Line przez
> `/dev/ttyUSB*` (pyserial), nie przez Arduino** — więc trzymając się
> repo, zostań przy CP2102. Jeśli świadomie chcesz wariant „Arduino jako
> interfejs K-Line", to osobny firmware i most szeregowy — napiszę go,
> jeśli zdecydujesz, ale nie jest to ścieżka z tego projektu.

---

## 1. Jak to działa (minimum teorii, żeby wiedzieć co łapać)

K-Line to **jeden przewód, półdupleks** — tester (MES) i ECU nadają na
przemian po tej samej linii. Każdy widzi też echo własnych bajtów.

### Sekwencja rozmowy
1. **Inicjalizacja 5-baud**: tester „wybija" adres ECU (0x01 dla silnika)
   bardzo wolno (5 bit/s), ECU odpowiada bajtem sync `0x55` i dwoma
   key-byte. Potem obie strony przełączają się na **10400 baud**.
2. **Sesja diagnostyczna**: `startDiagnosticSession` (0x10).
3. **Odczyt wartości**: tester wysyła `readDataByLocalIdentifier`
   (**SID 0x21**) + jednobajtowy **local ID**; ECU odsyła surowe bajty.
   To jest sedno — **każdej wielkości (RPM, temp…) odpowiada inne local ID**.
4. **Keep-alive**: `testerPresent` (0x3E) co ~2 s, żeby sesja nie wygasła.

### Format ramki (to dekoduje skrypt za Ciebie)
```
[fmt] [target] [source] [dane...] [checksum]
 │      │        │        │          └ suma wszystkich poprzednich & 0xFF
 │      │        │        └ SID + argumenty
 │      │        └ nadawca (0xF1 = tester, 0x01 = ECU)
 │      └ odbiorca
 └ bity 7-6: tryb adresowania; bity 5-0: długość danych (0 → osobny bajt długości)
```
Przykład realnej pary (obroty):
```
Tester → ECU:  82 01 F1 21 0B A0            (readLocalId 0x0B)
ECU → Tester:  84 F1 01 61 0B 1A F0 EC      (odpowiedź: dane = 1A F0)
                              └──┴ echo local ID   └──┴ 2 bajty surowej wartości
```
`0x1AF0 = 6896`, a RPM = `6896 × 0.25 = 1724 obr/min`. Skalę `0.25`
ustalasz metodą z §4.

---

## 2. Trzy metody zdobycia kodów PID

| Metoda | Co robi | Kiedy | Wiarygodność |
|---|---|---|---|
| **A. Podsłuch** | Czytasz magistralę, gdy MES odpytuje | Masz MES (Multiecuscan) — **Twój przypadek** | ★★★ najwyższa |
| **B. Log z MES** | Włączasz w MES logowanie komunikacji | Gdy MES na to pozwala | ★★☆ |
| **C. Aktywny skan** | Sam odpytujesz wszystkie ID po kolei | Bez MES, na czuja | ★☆☆ (ryzyko trafienia w zapis) |

Ponieważ masz **pełny MES**, metoda **A jest najlepsza** — MES już zna
poprawne kody dla EDC15C7, Ty je tylko podglądasz „na żywo".

---

## 3. Metoda A — podsłuch magistrali (krok po kroku)

### 3.1 Sprzęt
Potrzebujesz **drugiego** adaptera do samego czytania, podpiętego
**równolegle** do K-Line, podczas gdy VIAKEN prowadzi rozmowę z ECU.
Opcje:

- **Najprościej — drugi kabel VIAKEN/KKL** (albo moduł CP2102+L9637D):
  podepnij jego **K (pin 7)** i **GND (pin 4/5)** do tych samych pinów
  OBD-II co pierwszy. Transceiver drugiego adaptera tylko słucha —
  nie nadaje. Nic nie konfigurujesz po stronie ECU.
- **Analizator logiczny / drugi UART** na sygnale TTL między CP2102 a
  L9637D pierwszego adaptera (jeśli budujesz własny) — też działa, ale
  wygodniej dwoma adapterami.

> Podsłuch jest **pasywny i bezpieczny** — drugi adapter nie wysyła nic
> na magistralę, więc nie zakłóca sesji MES ani nie może nic zapisać do ECU.

### 3.2 Ustaw port
Sprawdź, który `/dev/ttyUSB*` to podsłuchujący adapter:
```bash
ls -la /dev/serial/by-id/          # czytelne nazwy
dmesg | tail                        # który się właśnie wpiął
```

### 3.3 Uruchom sniffer
Z katalogu głównego repo (venv aktywny):
```bash
python tools/kline_sniffer.py --passive --port /dev/ttyUSB1 --log kline_capture.txt
```
Zobaczysz strumień zdekodowanych ramek. `--log` zapisuje wszystko do pliku.

### 3.4 Wywołaj konkretną funkcję w MES
Teraz w **MES/Multiecuscan** wejdź w podgląd parametrów i **zaznaczaj po
jednej wielkości na raz** (najlepiej: włącz tylko „RPM", chwilę popatrz,
wyłącz; potem tylko „temperatura cieczy", itd.). W snifferze wyłapiesz,
które `readDataByLocalIdentifier` odpowiada której funkcji:

```
14:22:31  [F1->01] 82 01 f1 21 0b a0        |  REQ  readDataByLocalIdentifier  args=0b
14:22:31  [01->F1] 84 f1 01 61 0b 1a f0 ec  |  RESP readDataByLocalIdentifier  data=1a f0
```
→ Gdy w MES aktywne są tylko obroty, powtarza się **ID `0x0B`** →
to jest local ID obrotów. Zapisz sobie: `RPM = local ID 0x0B, 2 bajty`.

Powtórz dla każdej wielkości, którą chcesz mieć na dashboardzie:
obroty, prędkość, temperatura cieczy, temperatura powietrza, dawka
wtrysku, ciśnienie doładowania, napięcie, pozycja pedału…

> **Wskazówka:** izoluj po jednym parametrze. Jeśli MES odpytuje kilka
> naraz, w logu przeplatają się różne ID i trudniej je przypisać. Filtr:
> `grep "21 " kline_capture.txt` pokaże same żądania odczytu.

---

## 4. Zamiana surowych bajtów na wartość fizyczną (skala + offset)

Masz local ID i surowe bajty — teraz trzeba znaleźć wzór
`wartość = surowe × skala + offset`. Metoda „dwóch punktów":

1. W MES odczytaj **wyświetlaną** wartość (np. RPM = **1724**) i w tej
   samej chwili z sniffera surowe bajty (np. `1A F0` = `0x1AF0` = **6896**).
2. Zrób to dla drugiego, wyraźnie innego stanu (np. bieg jałowy 812 obr/min
   → surowe `0x0CB0` = 3248).
3. Policz:
   ```
   skala  = (1724 - 812) / (6896 - 3248) = 912 / 3648 = 0.25
   offset = 1724 - 6896 × 0.25 = 0
   ```
   → `RPM = surowe × 0.25`.

Typowe zależności EDC15C7 (dla orientacji — potwierdź podsłuchem u siebie):

| Wielkość | Bajty | Wzór typowy |
|---|---|---|
| Obroty (RPM) | 2 | `raw × 0.25` |
| Prędkość | 1 | `raw` (km/h) |
| Temp. cieczy | 1 | `raw − 40` (°C) |
| Temp. powietrza | 1 | `raw − 40` (°C) |
| Dawka wtrysku | 2 | `raw × 0.01` (mg/skok) |
| Napięcie | 1 | `raw × 0.1` (V) |
| Ciśnienie doładowania | 2 | `raw` (mbar) |
| Pozycja pedału | 1 | `raw × 0.4` (%) |

> Offset `−40` przy temperaturach to standard — 1 bajt bez znaku (0–255)
> pokrywa wtedy zakres −40…+215 °C. Jak zobaczysz „ok. 40" surowego przy
> zimnym silniku w temperaturze pokojowej, to na pewno ten offset.

---

## 5. Wpisanie znalezionych PID-ów do BCM

Wszystko żyje w **`src/obd/edc15c7.py`**. To jedyny plik, który edytujesz,
żeby dodać/poprawić parametr.

### 5.1 Dopisz dekoder (jeśli nowy wzór)
```python
def _decode_boost(data: bytes) -> float:
    """Ciśnienie doładowania w mbar (2 bajty, big-endian)."""
    if len(data) < 2:
        return 0.0
    return (data[0] << 8) | data[1]
```

### 5.2 Dodaj wpis do tabeli `PIDS`
Format: `PID(local_id, nazwa, temat_event_bus, funkcja_dekodująca, jednostka)`
```python
PIDS = [
    PID(0x0B, "Engine RPM",      "obd.rpm",           _decode_rpm,         "rpm"),
    PID(0x10, "Vehicle Speed",   "obd.speed",         _decode_vehicle_speed, "km/h"),
    PID(0x08, "Coolant Temp",    "obd.coolant_temp",  _decode_coolant_temp, "°C"),
    PID(0x0C, "Boost Pressure",  "obd.turbo_pressure", _decode_boost,       "mbar"),
    # ... podmień local_id (pierwsza liczba) na to, co znalazłeś podsłuchem
]
```
> **Uwaga:** wartości `local_id` w repo (0x01, 0x02…) to placeholdery z
> symulatora. **Prawdziwe ID z Twojego ECU wstaw tutaj** — to jedyna
> zmiana potrzebna, żeby dashboard czytał realne dane.

### 5.3 Wybierz, co ma być odpytywane w kółko
```python
# Najważniejsze parametry — pętla round-robin (co ~100 ms na jeden)
DEFAULT_ACTIVE_PIDS = [0x0B, 0x10, 0x08, 0x0C, 0x06]
```
Im mniej ID w tej liście, tym częściej odświeżany każdy (magistrala ma
skończoną przepustowość). Obroty i prędkość warto mieć, temperatury mogą
być rzadziej.

### 5.4 Ustaw port na prawdziwy sprzęt
W `config/bcm_config.yaml` (x86 / M910q) K-Line czyta port
`serial.kline.port_<platforma>`. Dodaj klucz dla x86 i regułę udev na
stabilną nazwę (żeby nie skakało `ttyUSB0/1`):
```yaml
serial:
  kline:
    port_x86: /dev/ttyUSB_kline    # patrz reguła udev niżej
    baudrate: 10400
    ecu_address: 1
```
Reguła udev (`/etc/udev/rules.d/99-kline.rules`) dla CP2102:
```
SUBSYSTEM=="tty", ATTRS{idVendor}=="10c4", ATTRS{idProduct}=="ea60", SYMLINK+="ttyUSB_kline"
```

> **Ważna uwaga o kodzie:** obecnie w `src/obd/simulator.py` platforma
> `x86` **zawsze** startuje symulator ECU (PTY), a nie realny port —
> bo x86 był dotąd trybem developerskim. Żeby M910q gadał z prawdziwym
> autem, trzeba dołożyć gałąź „realny serial na x86". To ~10 linii; mogę
> to dorobić razem z przełącznikiem `obd.use_real_hardware: true`, jeśli
> potwierdzisz, że tak chcesz. Do samego **podsłuchu i inżynierii
> wstecznej `tools/kline_sniffer.py` niczego nie wymaga** — działa
> niezależnie od BCM.

---

## 6. Metoda C — aktywny skan (bez MES, ostrożnie)

Jeśli kiedyś nie masz MES pod ręką, skaner sam odpyta zakres local ID i
pokaże, które zwracają dane:
```bash
# ODŁĄCZ MES — na magistrali może być tylko jeden master!
python tools/kline_sniffer.py --scan --port /dev/ttyUSB0 --from 0x01 --to 0x40
```
Wynik: lista ID, które odpowiedziały, z surowymi bajtami. Potem tak samo
ustalasz skalę (§4).

> **Bezpieczeństwo:** skan używa **tylko** `readDataByLocalIdentifier`
> (0x21) — usługi wyłącznie do **odczytu**. Nie dotyka `writeData` (0x2E),
> `inputOutputControl` (0x30) ani `securityAccess` (0x27), więc nie
> zmienia niczego w ECU. Mimo to: rób to na postoju z zaciągniętym
> ręcznym i zapłonem ON (silnik nie musi pracować).

### Weryfikacja pojedynczego kodu
Znalazłeś w logu ramkę i chcesz ją sprawdzić ręcznie:
```bash
python tools/kline_sniffer.py --replay 82 01 F1 21 0B --port /dev/ttyUSB0
```
Skrypt wyśle ją raz i zdekoduje odpowiedź.

---

## 7. Bezpieczeństwo i dobre praktyki

- **Do inżynierii wstecznej używaj podsłuchu (metoda A)** — jest pasywny,
  nie może nic popsuć, a MES zna właściwe kody lepiej niż zgadywanie.
- **Nigdy dwóch masterów naraz** na magistrali (MES + skaner aktywny) —
  kolizje i błędy sum kontrolnych. Podsłuch (read-only) można trzymać
  równolegle bez problemu.
- **Nie eksperymentuj z zapisem** (`writeData`, `securityAccess`,
  `clearDiagnosticInformation`) podczas nauki — łatwo skasować adaptacje
  albo kody, których jeszcze nie przeanalizowałeś.
- **Rób w garażu, nie w ruchu.** Zapłon ON wystarcza do odczytu; silnik
  pracujący tylko wtedy, gdy chcesz zobaczyć zmienne obroty do kalibracji.
- **Zapisuj logi** (`--log`) — łatwiej wrócić i porównać niż odczytywać
  ekran na żywo.
- Kasowanie DTC z poziomu BCM (ekran Serwis) używa już tych samych usług
  0x18/0x14 — patrz `src/obd/kwp2000.py`. Jak potwierdzisz kody live
  data, dashboard i diagnostyka będą spójne.

---

## 8. Ściąga — cały przepływ w skrócie

```
1. VIAKEN KKL → OBD-II   (rozmowa, jak zwykle w MES)
2. Drugi adapter → OBD-II pin 7 + GND   (tylko podsłuch)
3. python tools/kline_sniffer.py --passive --port /dev/ttyUSB1 --log cap.txt
4. MES → podgląd parametrów, zaznaczaj JEDNĄ wielkość na raz
5. Wynotuj: która wielkość = które local ID + ile bajtów
6. Ustal skalę/offset metodą dwóch punktów (§4)
7. Wpisz PID-y do src/obd/edc15c7.py (tabela PIDS + DEFAULT_ACTIVE_PIDS)
8. Ustaw serial.kline.port_x86 + reguła udev
9. (jeśli trzeba) dorób gałąź realnego serialu na x86 — patrz §5.4
```

Po tym dashboard BCM czyta obroty, temperatury itd. **bezpośrednio z ECU**,
bez MES — dokładnie tak, jak MES to robi, tylko na stałe.
