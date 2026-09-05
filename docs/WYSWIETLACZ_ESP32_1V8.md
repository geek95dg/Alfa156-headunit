# Wyświetlacz pomocniczy 1,8" na ESP32 — projekt ekranów

Mały panel ST7735 **128×160 px, pionowo** (dłuższa krawędź w pionie),
sterowany z ESP32 po SPI, pokazujący dwa ekrany: metadane odtwarzanej
muzyki z kontrolkami oraz ostrzeżenie o otwartym nadwoziu.

Projekt wizualny (kanwa Claude Design, pięć artboardów) jest wygenerowany
ze źródeł w `mockups/esp32_1v8/` — patrz
[`../mockups/esp32_1v8/README.md`](../mockups/esp32_1v8/README.md).

| Gdzie co jest | Plik |
|---|---|
| Firmware (parser, debounce, font, szkic, testy) | [`../arduino/esp32_display/`](../arduino/esp32_display/) |
| Generator sprite'ów / fontu | [`../tools/esp32_assets.py`](../tools/esp32_assets.py) · [`../tools/esp32_font.py`](../tools/esp32_font.py) |
| Most po stronie BCM | [`../src/dashboard/esp32_link.py`](../src/dashboard/esp32_link.py) |
| Schemat połączeń | [`../schematics/esp32_display_wiring.svg`](../schematics/esp32_display_wiring.svg) (generator [`../schematics/gen_esp32_display.py`](../schematics/gen_esp32_display.py)) |
| Tabele „skąd → dokąd” | [`SCHEMATY_POLACZEN.md`](SCHEMATY_POLACZEN.md) §11 |
| Reguła udev | [`../config/udev/99-bcm-esp32-display.rules`](../config/udev/99-bcm-esp32-display.rules) |
| Wpięcie i uruchomienie na M910q | [`WDROZENIE_M910Q.md`](WDROZENIE_M910Q.md) §20 |

## Założenia

- Panel jest **wyłącznie wyświetlaczem** — bez dotyku, bez przycisków.
  Całe sterowanie zostaje na głównym ekranie 10,1" i przy kierownicy.
- Rysunek w prawdziwych pikselach: artboardy mają kontener 128×160
  przeskalowany `scale(4)`, więc każda wartość `px` w środku to jeden
  piksel wyświetlacza.
- Paleta z motywu **Heritage** (domyślny w `config/bcm_config.yaml`),
  ta sama, którą ma drugi ekran 6,86":

  | rola | kolor |
  |---|---|
  | tło | `#0a0a0a` |
  | tekst główny | `#f4f4f5` |
  | tekst drugorzędny | `#a1a1aa` / `#52525b` |
  | akcent (pasek postępu) | `#f59e0b` |
  | linie podziału | `#27272a` |
  | kontrolka wygaszona | `#3f3f46` |

- Krój **Public Sans** — ten sam, którego używa `src/dashboard/small_display/css/small.css`.

## Ekran 1 — Now Playing

Trzy pasma w pionie, zgodnie z układem „wszystkie kontrolki u góry,
metadane pośrodku, tempomat na dole”:

```
┌────────────────────────┐
│ (ABS) (P) airbag klucz │  y 0..31    cztery kontrolki 26 × 26
├────────────────────────┤  y 32       linia #27272a
│       BLUETOOTH        │  7 px       źródło
│       Nightcall        │  15 px × 2  tytuł
│        Kavinsky        │  10 px      wykonawca
│    ▬▬▬▬▬▬▬───────      │  104 × 3 px pasek postępu
├────────────────────────┤  y 123      linia #27272a
│ (rezerwa)   ⊙ 130 km/h │  y 124..159 tempomat
└────────────────────────┘
```

Rozkład w pikselach panelu — to jest kontrakt, po nim liczy firmware:

| pasmo | y | zawartość |
|---|---|---|
| górne | 0–31 (32 px) | cztery kontrolki 26 × 26 rozstawione równomiernie: ABS, hamulec, poduszka, immobilizer |
| linia | 32 (1 px) | `#27272a` |
| środek | 33–122 (90 px) | źródło (7 px), tytuł (15 px, do 2 linii), wykonawca (10 px), pasek postępu 104 × 3 px |
| linia | 123 (1 px) | `#27272a` |
| dolne | 124–159 (36 px) | lewe 40 px — rezerwa; prawa komórka: symbol tempomatu, zadana prędkość (16 px) i `km/h` (7 px) |

| element | rozmiar | waga | kolor |
|---|---|---|---|
| źródło dźwięku | 7 px | 800 | `#52525b` |
| tytuł (do 2 linii) | 15 px | 800 | `#f4f4f5` |
| wykonawca | 10 px | 600 | `#a1a1aa` |
| pasek postępu | 104 × 3 px | — | `#f59e0b` na `#27272a` |
| symbol kontrolki | 22 × 22 px w podkładce 26 × 26 | — | zależnie od stanu |
| zadana prędkość | 16 px | 900 | `#22c55e` |

Pole tekstu ma 112 px szerokości. Tytuł łamie się do dwóch linii i dopiero
wtedy dostaje wielokropek; wykonawca zawsze jedna linia z wielokropkiem.

Linia źródła pokazuje **nazwę, nie kod z kabla**: `SRC:BT` → `BLUETOOTH`,
`SRC:AA` → `ANDROID AUTO`, wszystko inne (i cisza z BCM) → `---`. Mapowanie
robi `text_source_name()` w `text_layout.h`, po stronie panelu — protokół
zostaje przy dwuliterowych kodach. Przy pauzie dochodzi ` · PAUZA`; strzałki
odtwarzania w foncie nie ma, stąd słowo zamiast symbolu. Najdłuższy wariant,
`ANDROID AUTO · PAUZA`, ma 85 px przy polu 112 px (pilnuje tego
`test_text_compose_source()` w testach hosta).

Podział jest celowy: **wszystkie cztery lampki usterek stoją w paśmie
górnym** — czyta się je jednym spojrzeniem, w tej samej linii, w której
siedzą na zegarach. **Dolne pasmo należy do tempomatu**: jest szersze, bo
po włączeniu rozwija się o zadaną prędkość; przy wyłączonym zostaje w nim
sam wygaszony symbol i `---`. Lewe 40 px dolnego pasma zostaje **puste
jako rezerwa** — to miejsce na przyszłą piątą informację (np. temperatura
zewnętrzna), a nie na kolejną lampkę: pasmo górne mieści komplet.

### Kontrolki

Rysowane są **sprite'ami 26 × 26 z `assets.h`** (`TELLTALES[]`, po dwie
bitmapy na lampkę: zapalona i wygaszona), rozstawionymi równomiernie na
całej szerokości pasma. Kolejność `ABS, hamulec, poduszka, immobilizer`
jest wspólna dla `assets.h`, wyliczenia `InputId` w `state.h` i tabeli
wejść w [`SCHEMATY_POLACZEN.md`](SCHEMATY_POLACZEN.md) §11.1 — indeks
sprite'a to po prostu numer wejścia.

Symbole trzymają się zegarów 156. ABS i hamulec ręczny mają wspólne
klamry z dwóch łuków po każdej stronie — czytają się jako jedna rodzina
hamulcowa, a rozróżnia je zawartość koła (`ABS` kontra `P`). Poduszka to
pasażer w fotelu z workiem przed sobą, immobilizer to kluczyk, tempomat
to otwarta tarcza prędkościomierza z igłą.

Zapalona kontrolka dostaje **podkładkę w swoim kolorze przy 13 % krycia
(promień 3 px) i wąską poświatę** — ten sam język, którym motyw Heritage
podświetla wartości na ekranie 6,86" (`text-shadow: 0 0 10px rgba(...)`).
Poświata jest opcjonalna, jeśli na ESP32 okaże się zbyt kosztowna —
sama podkładka wystarczy, żeby stan był czytelny.

Kolory zgodne z zegarami 156: ABS i immobilizer bursztynowe (`#f59e0b`),
hamulec i poduszka czerwone (`#ef4444`), tempomat zielony (`#22c55e`).

## Ekran 2 — otwarte nadwozie

**Zasłonięcie stałe**: dopóki którykolwiek czujnik zgłasza otwarcie, ten
ekran przykrywa ekran 1 w całości — bez timeoutu, bez naprzemiennego
przełączania i bez powrotu do muzyki. Znika dopiero, gdy wszystko jest
zamknięte.

Ekran to **sama bryła, bez nagłówka i bez nazw paneli** — który panel
jest otwarty, widać z rysunku. Rzut z góry Alfy Romeo 156 Berlina
w proporcji 4430 : 1743 mm (1 jednostka rysunku ≈ 39,6 mm), wpisany
w cały ekran: nadwozie 53 × 136 px, po bokach margines na wychylone
skrzydła.

Otwarte drzwi rysowane są jako skrzydło wychylone na przednim zawiasie;
maska i klapa bagażnika jako wypełniony panel plus uniesiona pokrywa
wysunięta poza obrys. Skrzydła i pokrywy leżą **na wierzchu obrysu
nadwozia**, żeby sylwetka czytała się także wtedy, gdy otwarte jest
wszystko sześć (osobny artboard pokazuje ten przypadek).

## Assety — z renderów do `assets.h`

Grafika nie jest rysowana prymitywami w firmware, tylko wypalona w sprite'y
RGB565. Powód jest prosty: poświata i miękka kreska z renderów są nie do
odtworzenia `drawLine()`, a w bitmapie kosztują zero.

Generuje je `tools/esp32_assets.py`:

```bash
python tools/esp32_assets.py            # -> arduino/esp32_display/assets.h
python tools/esp32_assets.py --thicken 7    # grubsza kreska
```

Skrypt bierze **dwa** pliki z `mockups/`:

- `screen (9).png` — rzut z góry narysowany w dwóch kolorach naraz:
  bursztynowe nadwozie (kompletne, zamknięte) i czerwone otwarte panele.
  Skrypt rozdziela je po barwie, a warstwę czerwoną rozbija na sześć
  osobnych brył po położeniu środka ciężkości: maska, czworo drzwi, klapa.
- `screen.png` — kontrolki w kolorach zegarów 156. Stan wygaszony jest
  **wyliczany** z zapalonego (przygaszenie do 30 % + odsycenie), więc
  osobne rendery zgaszonych lampek są niepotrzebne.

**Nie wolno mieszać różnych renderów.** Każdy z nich to osobny rysunek:
`screen (9)` ma nadwozie 425 × 1069 px, `screen (10)` — 470 × 1040 px,
a ich obrysy rozjeżdżają się o kilka pikseli na całej długości. Panele
z jednego pliku nałożone na bryłę z drugiego dadzą podwójne kontury.
Spasowanie działa tylko dlatego, że wszystko pochodzi z jednego rysunku
i przechodzi przez tę samą transformację (klasa `Frame`).

Kreska w źródle ma ~3 px, a zjazd do 128 × 160 to skala ~1:7 — bez
pogrubienia maski przed skalowaniem linia gaśnie do brązu. Domyślne 5 px
daje jasny, czytelny obrys.

Każdy panel zapisywany jest w dwóch wersjach wyciętych z **tego samego**
rastra: `closed` (sama karoseria) i `open` (karoseria z czerwonym panelem).
Firmware przełącza stan jednym nieprzezroczystym blitem prostokąta — bez
kanału alfa, bo tło ekranu jest jednolicie czarne. Sześć niezależnych
paneli daje wszystkie 64 kombinacje bez ani jednego dodatkowego obrazka.

Budżet: **~84 KB** we flashu (bryła 40 KB, dwanaście wycinków paneli
~30 KB, osiem kontrolek 13,5 KB). Podgląd do obejrzenia okiem ląduje
w `mockups/esp32_1v8/assets_preview.png`.

Czego w assetach nie ma: **font bitmapowy** na tytuł, wykonawcę i cyfry
prędkości — to dane, zmieniają się w locie, więc mają własny generator
i własny plik (niżej).

## Font — z TTF do `font.h`

Cztery kroje wypalone z jednego pliku zmiennego **Public Sans**
(`assets/fonts/PublicSans-Variable.ttf`, licencja OFL — `assets/fonts/OFL.txt`),
tego samego, którego używa `src/dashboard/small_display/css/small.css`:

| krój | rozmiar | waga | do czego |
|---|---|---|---|
| `FONT_TITLE` | 15 px | 800 | tytuł utworu, do dwóch linii |
| `FONT_ARTIST` | 10 px | 600 | wykonawca |
| `FONT_LABEL` | 7 px | 800 | źródło dźwięku, `km/h` |
| `FONT_SPEED` | 16 px | 900 | zadana prędkość tempomatu |

```bash
python tools/esp32_font.py                 # -> arduino/esp32_display/font.h
python tools/esp32_font.py --threshold 140 # cieńsza kreska
```

Rasteryzacja jest **jednobitowa**: dla każdego glifu trzymamy maskę „tu
jest atrament”, a firmware maluje ją kolorem tekstu na tle `#0a0a0a`.
Antyaliasing przy 7–16 px na tak ciemnym tle nic nie daje, a kosztowałby
albo cztery razy więcej flasha, albo blending w pętli rysującej.

Zestaw znaków: ASCII `0x20–0x7E` + polskie `ĄĆĘŁŃÓŚŹŻ ąćęłńóśźż` + `°`,
`·`, `—`, `…`. Latin Extended-A jest obowiązkowe, bo tytuły z Bluetootha
przychodzą z ogonkami. **Brakujący codepoint podmieniany jest na `?`** —
nigdy nie wywala programu i nie wypisuje śmieci, a przez kabel przyjdzie
prędzej czy później i emoji, i cyrylica.

Budżet: **~11,5 KB** we flashu — 117 glifów × cztery kroje, z czego bitmapy
4,9 KB, reszta to tablice `codepoints[]` i `Glyph[]` (generator wypisuje
dokładne liczby po każdym przebiegu). Przy ~84 KB assetów to margines,
którego nie warto oszczędzać kosztem ogonków.

**`line_height` jest większy niż nominalny rozmiar kroju** (TITLE 19 px przy
15 px oczka, ARTIST 13/10, LABEL 9/7, SPEED 20/16) — to metryki Public Sans,
nie zapas. Warstwa rysująca liczy wiersze po `Font.line_height`, nie po
rozmiarze z tabeli wyżej: dwie linie tytułu zajmują 2 × 19 = 38 px, a nie
2 × 15. Pola w sketchu (`TITLE_H`, `ARTIST_H`, `SRC_H`, `SPD_H`) są równe
dokładnie `line_height` swojego kroju i tak trzeba je trzymać — wtedy
atrament nigdy nie wychodzi poza czyszczony prostokąt (pilnuje tego
`test_font_ink_bounds()` w testach hosta).

Same dane siedzą w `font.h` (generowane, nie edytuj ręcznie), a logika —
dekoder UTF-8, szerokość napisu, przycinanie do liczby pikseli — w pisanym
ręcznie [`../arduino/esp32_display/font_draw.h`](../arduino/esp32_display/font_draw.h).
`codepoints[]` jest posortowane rosnąco, więc szukanie glifu to
wyszukiwanie binarne; szerokość napisu liczona jest jako suma pól
`advance`, dokładnie tak, jak przesuwa się kursor przy rysowaniu — dzięki
temu wyśrodkowanie nigdy się nie rozjeżdża.

## Sygnały — dwa źródła

Kontrolki i otwarcia idą **wprost do ESP32**: w miejscu montażu jest
złącze fabrycznego wyświetlacza, na którym te stany są dostępne jako
poziomy 12 V / 0 V. Z BCM przychodzi tylko to, czego w aucie nie ma
w postaci prostego napięcia.

### Wprost z auta, przez PC817

| sygnał | pin ESP32-S3 | ekran |
|---|---|---|
| ABS | GPIO4 | 1 |
| hamulec ręczny | GPIO5 | 1 |
| poduszka (SRS) | GPIO6 | 1 |
| immobilizer | GPIO7 | 1 |
| maska | GPIO1 | 2 |
| drzwi przód lewe / prawe | GPIO15 / GPIO16 | 2 |
| drzwi tył lewe / prawe | GPIO17 / GPIO18 | 2 |
| klapa bagażnika | GPIO2 | 2 |

Debounce **30 ms** (`INPUT_DEBOUNCE_MS` w `state.h`) — tyle wystarcza na
drgania styków i krańcówek. Komplet pinów, z panelem i zasilaniem, jest
w tabeli niżej; okablowanie zacisk po zacisku w
[`SCHEMATY_POLACZEN.md`](SCHEMATY_POLACZEN.md) §11 i na rysunku
[`../schematics/esp32_display_wiring.svg`](../schematics/esp32_display_wiring.svg).

Układ wejściowy jest już w projekcie opisany — [`SCHEMATY_POLACZEN.md`](SCHEMATY_POLACZEN.md)
§3.1: sygnał 12 V → 4,7 kΩ → PC817 pin 1, pin 2 → masa pojazdu, pin 4
(kolektor) → GPIO w trybie `INPUT_PULLUP`, pin 3 (emiter) → masa ESP32.
Stan aktywny to **LOW**. Dla ESP32-S3 obowiązuje ten sam schemat — GPIO
są 3,3 V i **nie tolerują nawet 5 V**, o 12 V nie wspominając, a instalacja
samochodowa potrafi wypuścić impulsy grubo powyżej 40 V. Każde wejście
zasługuje dodatkowo na TVS (np. SMBJ24A) po stronie pojazdu.

**Nie zakładaj polaryzacji — zmierz ją.** W autach tej epoki krańcówki
drzwi są zwykle **zwierane do masy** (linia ma ~12 V przy zamkniętych,
0 V przy otwartych), czyli działają odwrotnie niż sterowana plusem lampka.
Firmware `sensor_hub` już to zresztą tak traktuje (`INPUT_PULLUP`,
`LOW = otwarte`). Dla każdej linii trzeba sprawdzić miernikiem: napięcie
w spoczynku, w stanie aktywnym oraz czy linia źródłuje prąd, czy go zwiera.

Osobno warto zweryfikować, czy **ABS i poduszka** w ogóle występują na tym
złączu jako osobne linie. To dwie najmniej pewne pozycje — w wielu wersjach
rysują je zegary z własnej magistrali i nie podają dalej. Jeśli ich tam nie
ma, zostaje wzięcie ich z BCM albo rezygnacja z tych dwóch lampek.

### Z BCM, po USB

| dane | temat na magistrali |
|---|---|
| stan tempomatu | `vehicle.cruise` |
| zadana prędkość | `vehicle.cruise_set_speed` — do dodania, z ECU przez K-Line |
| metadane muzyki | `bt.media_title` / `_artist` / `_position` / `_duration` / `_playing` |
| źródło dźwięku | `audio.source_changed` |

ESP32-S3 ma natywny kontroler USB-OTG, więc wpina się wprost w port USB
M910q i zgłasza jako CDC-ACM — bez mostka UART. W Arduino trzeba włączyć
**USB CDC On Boot**; wtedy `Serial` to ten port. Na płytkach z dwoma
gniazdami USB-C jedno idzie do natywnego USB, a drugie do mostka
(CH343/CP2102) — potrzebne jest to pierwsze.

**Reguła udev jest konieczna**, dokładnie z tego samego powodu co przy
K-Line ([`WDROZENIE_M910Q.md`](WDROZENIE_M910Q.md) §12): numeracja
`/dev/ttyACM*` przeskakuje między restartami, a jeden taki węzeł jest już
zajęty przez Pro Micro. Wzorem `/dev/ttyUSB_kline` robimy `/dev/ttyACM_display`,
dopasowanie po VID:PID (natywne USB Espressifa to `303a:1001`) i po numerze
seryjnym, jeśli w aucie są dwie płytki z tej rodziny.

Gotowy plik: [`../config/udev/99-bcm-esp32-display.rules`](../config/udev/99-bcm-esp32-display.rules).
Instalacja i weryfikacja: [`WDROZENIE_M910Q.md`](WDROZENIE_M910Q.md) §20.2.

Protokół — ten sam kształt linii `KLUCZ:wartość`, którym mówi już
`sensor_hub`, tylko w drugą stronę: tu BCM pisze, a ESP32 czyta.

```
SRC:BT
TITLE:Nightcall
ARTIST:Kavinsky
PLAY:1
DUR:258
POS:87
CRUISE:1
SETSPD:130
PING
```

Kolejność w pełnym zrzucie jest taka jak wyżej (`KEY_ORDER`
w `esp32_link.py`): najpierw źródło i metadane, potem `DUR` przed `POS`,
żeby ESP32 miał czym podzielić pozycję, zanim narysuje pasek. Później lecą
już tylko klucze, których wartość się zmieniła.

Kodowanie UTF-8; po stronie ESP32 trzeba odwzorować polskie znaki na
pozycje w foncie bitmapowym.

Po stronie BCM robi to `src/dashboard/esp32_link.py` — odwrotność
`src/input/arduino_serial.py`: tam Arduino pisze, a BCM czyta, tutaj
odwrotnie. Moduł nazywa się `esp32_display` (przełącznik `modules.esp32_display`,
blok `esp32_display:` w `config/bcm_config.yaml`) i startuje generycznie
z rejestru w `src/core/modules_catalog.py`.

Trzy rzeczy, których nie widać w samym protokole:

- **wysyłane są tylko zmiany.** `bt.media_position` tyka co sekundę,
  a zmiany źródła czy tempomatu przychodzą seriami — bez filtru port
  dostawałby wielokrotnie więcej linii, niż wynika ze stanu;
- **`PING` co 2 s.** ESP32 uznaje BCM za offline po 5 s ciszy i wygasza
  metadane do `---`. Przy zatrzymanym odtwarzaniu nic innego nie leci
  przez kabel nawet przez kilkanaście minut;
- **po `READY` idzie pełny zrzut stanu.** To samo dzieje się po
  ponownym podłączeniu portu — świeżo wstała płytka nie wie nic
  o utworze, który leci od dziesięciu minut.

Skanowany port (gdy reguły udev nie ma) musi odpowiedzieć `PONG`, zanim
cokolwiek do niego pójdzie. **Na `/dev/ttyACM*` z trzech płytek Arduino
siedzi tylko Pro Micro** (`arduino/rotary_encoder`, ATmega32U4 z natywnym
USB) — oba Nano idą przez CH340 na `/dev/ttyUSB0` i `/dev/ttyUSB1`
([`SCHEMATY_POLACZEN.md`](SCHEMATY_POLACZEN.md) §5.3), więc skanu w ogóle
nie dotyczą. `TITLE:` wpisane po omacku w Pro Micro niczego dobrego nie
zrobi. Ścieżce `/dev/ttyACM_display` z udev ufamy bez pytania.

Port, który nie odpowie trzy razy z rzędu, wypada ze skanu do czasu
przepięcia kabla (zniknięcia i powrotu węzła w `/dev`). Powód jest
przyziemny: `/dev/ttyACM0` trzyma otwarty `src/input/arduino_serial.py`,
a handshake czyta z tego samego węzła przez 1,5 s — czyli **podkrada mu
bajty**, gubiąc na ten czas linie SWC i telemetrii. Bez limitu auto bez
wyświetlacza robiłoby to co cykl ponowienia, w kółko. To kolejny argument
za regułą udev: ze stałą ścieżką skan w ogóle nie rusza.

Uwaga na **1200 bps**: rdzeń Arduino dla S3 traktuje otwarcie portu przy
tej prędkości jako żądanie wejścia w bootloader. Otwieranie z Pythona przy
115200 jest bezpieczne, ale skrypty przelatujące prędkościami potrafią
zresetować płytkę.

Sygnały pojazdu idą wprost na GPIO, więc **ekran 2 działa niezależnie od
komputera** — ostrzeżenie o otwartych drzwiach nie czeka na wstanie
M910q.

Po stronie systemu moduł nazywa się `esp32_display` i jest **domyślnie
wyłączony**; włączenie, reguła udev i weryfikacja („czy linie lecą”):
[`WDROZENIE_M910Q.md`](WDROZENIE_M910Q.md) §20.

## Pinout ESP32-S3

Ustalony, wspólny dla firmware'u, schematu i tabel montażowych:

| funkcja | pin | uwagi |
|---|---|---|
| TFT SCK / MOSI | 12 / 11 | SPI panelu |
| TFT CS / DC / RST | 10 / 13 / 14 | |
| TFT BL | 21 | podświetlenie na kanale LEDC (PWM) |
| ABS / hamulec / poduszka / immo | 4 / 5 / 6 / 7 | wejścia, `INPUT_PULLUP` |
| drzwi FL / FR / RL / RR | 15 / 16 / 17 / 18 | wejścia, `INPUT_PULLUP` |
| maska / bagażnik | 1 / 2 | wejścia, `INPUT_PULLUP` |

Wszystkie wejścia są **aktywne w stanie LOW** (wyjście transoptora zwiera
pin do masy).

**Zajęte i zakazane:** 0, 3, 45, 46 to piny strappingowe (stan przy resecie
decyduje o trybie startu), 19 i 20 to natywne USB — czyli cały protokół,
a 26–37 to flash i PSRAM modułu. Żadnego z nich nie wolno użyć.

## Firmware — podział na pliki

Podział jest podyktowany **testowalnością**: wszystko, co da się sprawdzić
bez płytki, jest czystym C++ i kompiluje się zwykłym `g++`. W szkicu
zostaje wyłącznie I/O.

| plik | zawartość | testowalny na hoście |
|---|---|---|
| [`../arduino/esp32_display/protocol.h`](../arduino/esp32_display/protocol.h) | składanie linii z bajtów, parser `KLUCZ:wartość` → `DisplayData` | tak |
| [`../arduino/esp32_display/state.h`](../arduino/esp32_display/state.h) | debounce dziesięciu wejść, wybór ekranu, timeout BCM | tak |
| [`../arduino/esp32_display/font_draw.h`](../arduino/esp32_display/font_draw.h) | UTF-8, metryki, przycinanie tekstu | tak |
| [`../arduino/esp32_display/text_layout.h`](../arduino/esp32_display/text_layout.h) | łamanie tytułu na dwie linie, wielokropek, linia źródła | tak |
| [`../arduino/esp32_display/font.h`](../arduino/esp32_display/font.h) | dane fontu (generowane) | — |
| [`../arduino/esp32_display/assets.h`](../arduino/esp32_display/assets.h) | sprite'y RGB565 (generowane) | — |
| `arduino/esp32_display/esp32_display.ino` | TFT_eSPI, GPIO, USB CDC, LEDC — tylko I/O | nie |
| [`../arduino/esp32_display/test/test_host.cpp`](../arduino/esp32_display/test/test_host.cpp) | `main()` z asercjami | to on |

```bash
make -C arduino esp32_display-test    # g++ -std=c++17 -Wall -Wextra -Werror
make -C arduino esp32_display         # kompilacja szkicu (rdzeń esp32:esp32)
make -C arduino esp32_display-upload PORT=/dev/ttyACM_display
```

Konfiguracja `TFT_eSPI` (sterownik, rozmiar, piny, zegar SPI) siedzi
w [`../arduino/Makefile`](../arduino/Makefile) jako flagi kompilatora,
a nie w `User_Setup.h` biblioteki — inaczej kompilacja na innej maszynie
dawałaby inny wynik.

## Zasilanie i pobór

| stan | ESP32-S3 | podświetlenie | razem @3,3 V | z 12 V przy sprawności 85 % |
|---|---|---|---|---|
| praca, Wi-Fi | 80–120 mA | 20–60 mA | 150–200 mA | **~60 mA** |
| praca, tylko UART | 30–40 mA | 20–60 mA | 60–110 mA | ~35 mA |
| light sleep | ~240 µA | 0 | ~0,3 mA | — |
| deep sleep | ~8 µA | 0 | ~20 µA | zależy od przetwornicy |

Podświetlenie warto wyprowadzić na kanał LEDC (PWM) — projekt ma już
`arduino.light_level` z fotorezystora, więc ten ekran może ściemniać się
razem z resztą, a przy okazji schodzi w dolne rejony tabeli.

### Czy można wpiąć na stałe do akumulatora

Najpierw rozróżnienie, którego wcześniejsze wydanie tej sekcji nie robiło:
w tym projekcie są **dwa** źródła i tylko jedno z nich jest przedmiotem
rachunku poniżej.

| Źródło | Kto z niego żyje | Panel |
|--------|------------------|-------|
| **Akumulator rozruchowy** (60–70 Ah) | rozrusznik, wzmacniacz, instalacja auta | przypadek opisany zaraz niżej |
| **Bank buforowy** — 7 × CSB HR1221W, **35,7 Ah** ([`ZASILANIE_BUFOROWANE.md`](ZASILANIE_BUFOROWANE.md) §4.2) | cały head unit, non stop | osobny rachunek — **wariant 4** |

**Z akumulatora rozruchowego: nie, nie za samą przetwornicą step-down.**
Przy ~60 mA ciągłego poboru to 1,44 Ah na dobę. Akumulator w 156 to ok.
60–70 Ah, a samo auto pobiera już ~20–30 mA na spoczynku. Po dwóch tygodniach
postoju zabraknie blisko połowy pojemności — a JTD potrzebuje zdrowego
akumulatora, żeby ruszyć. Przyjęta granica pasożytniczego poboru dla całego
auta to ~30–50 mA i ten budżet jest już w dużej części zajęty.

Cztery wyjścia, od najprostszego:

1. **Zasilanie z +15 (po zapłonie), nie z +30.** Pobór na postoju zeruje
   się całkowicie. Projekt i tak ma rozpoznawanie zapłonu
   (`schematics/ignition_sense.svg`, `vehicle.ignition_raw`).
2. **Buck z +30, ale bramkowany wejściem EN** — zapłonem albo sumą linii
   drzwiowych przez diody. Moduł jest wtedy naprawdę wyłączony przy
   zamkniętym aucie i budzi się, gdy otworzysz drzwi. Sensowne, jeśli
   ekran ma ostrzegać o niedomkniętym bagażniku po zaparkowaniu.
3. **Deep sleep z wybudzaniem EXT1** na liniach drzwiowych — ale wtedy
   o wyniku decyduje **prąd spoczynkowy przetwornicy, nie ESP32**.
   Popularny LM2596 bierze 5–10 mA i przekreśla całą operację; MP1584
   jest lepszy, ale moduły z dzielnikiem sprzężenia i tak siedzą na
   ~0,1–1 mA. Do tego scenariusza trzeba przetwornicy z niskim prądem
   własnym (klasa TPS62840 / TPS62740, jednostki µA), a nie modułu
   z targu. Budżet do utrzymania: ≤100 µA łącznie.
4. **Zasilanie z szyny buforowanej (domena A), zamiast z instalacji auta.**
   To nie jest wariant „z akumulatora" w sensie punktów 1–3: bank i tak żyje
   non stop i to on, a nie akumulator rozruchowy, zasila head unit na postoju
   — [`ZASILANIE_BUFOROWANE.md`](ZASILANIE_BUFOROWANE.md) §1 mówi wprost, że
   „akumulator rozruchowy **nigdy** nie zasila head unitu na postoju";
   rozdziela je przekaźnik ładowania z diodą. Pobór panelu jest wtedy pozycją
   budżetu **banku**, a nie budżetu pasożytniczego auta.

   Co to kosztuje przy dzisiejszym banku (liczone do 50 % DoD, metodyka §9.2
   tamtego dokumentu):

   | | Bank 4 pakiety (poprzednio) | **Bank 7 pakietów (dziś)** |
   |---|---|---|
   | Pojemność użyteczna do 50 % DoD | 10,2 Ah | **17,85 Ah** |
   | Sam panel (60 mA) wytrzymałby | 7,1 dnia | **12,4 dnia** |
   | Postój przy bazie 80 mA + panel = 140 mA | 3,0 dnia | **5,3 dnia** |
   | Postój przy bazie 185 mA + panel = 245 mA | 1,7 dnia | **3,0 dnia** |
   | *dla porównania — postój bez panelu* | *5,3 / 2,3 dnia* | *9,3 / 4,0 dnia* |

   Stałe zasilanie panelu kosztuje więc **24–43 % czasu postoju**. Przy
   czterech pakietach schodziło to do 3,0–1,7 dnia i było nie do przyjęcia;
   przy siedmiu zostaje **5,3–3,0 dnia** i to już jest do obrony. W zamian
   znika własna skarga tego dokumentu (sekcja niżej): kontrolki bezpieczeństwa
   pojawiają się od przekręcenia kluczyka, a nie po pełnym boocie M910q.

   Warunki: wpięcie **za LVD i wyłącznikiem głównym S1**, własna wkładka
   2 A z listwy, i **dopisanie panelu do budżetu §9.1**
   [`ZASILANIE_BUFOROWANE.md`](ZASILANIE_BUFOROWANE.md) — dziś go tam nie ma,
   tabela obejmuje tylko Nano #1, HM-10, RXB6, moduł przekaźników i straty
   bucka (razem 60 mA).

Rekomendacja: **wariant 1 albo 4** — i to jest wybór architektoniczny, nie
elektryczny.

- **Wariant 1 (+15)** jest najprostszy i zeruje pobór na postoju, ale
  w wersji **docelowej** szyna +15 nie jest już źródłem zasilania niczego:
  [`ZASILANIE_BUFOROWANE.md`](ZASILANIE_BUFOROWANE.md) §2 stwierdza, że
  „zapłon nie odcina już żadnego odbiornika — jest wyłącznie **sygnałem**".
  Wzięcie stamtąd prądu oznacza w praktyce ciągnięcie z akumulatora
  rozruchowego, czyli dokładnie to, czego zakazuje §1. W wariancie
  **testowym**, gdzie panel i tak jest osobnym bytem, zarzut ten nie jest
  jeszcze wiążący.
- **Wariant 4 (domena A)** jest zgodny z architekturą docelową i przy banku
  35,7 Ah mieści się w budżecie. Kosztuje 24–43 % czasu postoju i wymaga
  aktualizacji §9.1.

Wariant 2 zostaje, jeśli ostrzeżenie ma działać przy wyłączonym zapłonie bez
sięgania do banku. Wariant 3 tylko wtedy, gdy ekran ma być stale rezydentny,
i wyłącznie z policzoną przetwornicą.

### Zasilać z USB czy osobno

Skoro dane i tak idą po USB, kabel do M910q jest już położony — kusi, żeby
wziąć z niego też 5 V. Dwie drogi, obie sensowne:

**Z USB.** Najprostsze elektrycznie: jeden przewód, jedno zasilanie, zero
pasożytniczego poboru, bo port gaśnie razem z komputerem. Koszt: ekran
wstaje dopiero, gdy wstanie M910q, więc kontrolki — informacja bezpieczeństwa
— pojawiają się z opóźnieniem całego bootu, mimo że ich sygnały siedzą
na GPIO od przekręcenia kluczyka. Trzeba też sprawdzić w BIOS-ie ThinkCentre,
czy port nie jest zasilany na stałe w S5 (opcja typu *Always On USB*) —
jeśli jest, wracamy do pasożytniczego poboru z §wyżej.

**Osobno z +15, dane po USB.** Ekran wstaje z zapłonem i od razu pokazuje
stan pojazdu; muzyka i tempomat dochodzą, gdy komputer się podniesie.
Wymaga tylko pilnowania, żeby własne 5 V nie trafiło w VBUS: albo płytka
rozdzielająca zasilanie zewnętrzne od VBUS, albo kabel z odłączoną żyłą
VBUS i wykrywaniem obecności hosta osobnym GPIO. Masa musi być wspólna.

Rekomendacja: **osobno, nie z USB.** Lampka ABS czy poduszki, która zapala
się pół minuty po przekręceniu kluczyka, jest gorsza niż jej brak. Skąd wziąć
te 12 V, rozstrzyga sekcja wyżej: **z +15** w wariancie testowym (pobór na
postoju zerowy) albo **z szyny buforowanej / domeny A** w wersji docelowej
(zgodne z architekturą, kosztuje 24–43 % czasu postoju przy banku 35,7 Ah).
Elektrycznie i mechanicznie oba rozwiązania są identyczne — różni je tylko to,
do którego zacisku podepniesz wejście bucka.

## Do rozstrzygnięcia

Rozstrzygnięte — zostają na liście, żeby było widać, czym się skończyło:

- ~~Zasilanie: z USB czy osobno~~ → **osobno**, z przeciętą żyłą VBUS
  w kablu USB. Lampka bezpieczeństwa, która zapala się pół minuty po
  przekręceniu kluczyka, jest gorsza niż jej brak. Wariant „tylko z USB”
  zostaje opisany jako alternatywa, bo elektrycznie jest prostszy.
- ~~Rozkład kontrolek między pasmami~~ → **cztery lampki usterek w paśmie
  górnym**, dolne pasmo w całości dla tempomatu, lewe 40 px jako rezerwa.
- ~~Font bitmapowy z ogonkami~~ → Public Sans, cztery kroje wypalone przez
  `tools/esp32_font.py`, brakujący znak → `?`.
- ~~Czy przy tytułach dłuższych niż dwie linie zostawić wielokropek~~ →
  **wielokropek** (`font_fit()`), bez przewijania. Marquee wymagałby
  przerysowywania paska tekstu co klatkę i miga na ST7735 bez podwójnego
  bufora; można wrócić do tematu, jeśli okaże się, że tytuły faktycznie
  przycinają się często.

Otwarte:

0. **Skąd wziąć 12 V dla panelu w wersji docelowej: +15 czy szyna buforowana
   (domena A).** Sekcja „Czy można wpiąć na stałe do akumulatora", wariant 1
   vs 4. Rachunek jest policzony i przy banku 35,7 Ah wariant 4 mieści się
   w budżecie (postój 5,3–3,0 dnia zamiast 9,3–4,0), ale +15 jako **źródło
   zasilania** kłóci się z [`ZASILANIE_BUFOROWANE.md`](ZASILANIE_BUFOROWANE.md)
   §2, gdzie zapłon jest wyłącznie sygnałem. Decyzja pociąga za sobą dopisanie
   panelu do budżetu §9.1 tamtego dokumentu i wiersz w tabeli przekrojów §8.2
   — dlatego nie została podjęta tu samodzielnie.
1. Czy **ABS i poduszka** są dostępne na złączu fabrycznego wyświetlacza
   jako osobne linie 12 V — do zmierzenia w aucie. Jeśli nie, zostaje
   wzięcie ich z BCM albo rezygnacja z tych dwóch lampek.
2. **Polaryzacja każdej z dziesięciu linii** — do zmierzenia. Linie zwierane
   do masy wchodzą wprost na pin, bez PC817 (`SCHEMATY_POLACZEN.md` §3.3),
   więc dopiero pomiar mówi, ile stopni transoptorów trzeba zlutować.
3. **Skąd wziąć zadaną prędkość tempomatu.** `vehicle.cruise_set_speed`
   subskrybuje już `esp32_link.py`, ale **nikt tego tematu nie publikuje** —
   trzeba znaleźć ramkę w ECU (`KLINE_SNIFFING.md`) albo pogodzić się z tym,
   że pole pokazuje `---`. Sam stan tempomatu (`vehicle.cruise`) idzie
   z `sensor_hub`, ale wymaga włączenia `FEATURE_CRUISE`
   ([`WDROZENIE_M910Q.md`](WDROZENIE_M910Q.md) §11.2).
4. **Montaż panelu** — czy w miejscu fabrycznego wyświetlacza da się osadzić
   moduł 1,8" bez przeróbki konsoli, i którędy poprowadzić kabel USB.
