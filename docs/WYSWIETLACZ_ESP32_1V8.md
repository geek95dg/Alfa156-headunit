# Wyświetlacz pomocniczy 1,8" na ESP32 — projekt ekranów

Mały panel ST7735 **128×160 px, pionowo** (dłuższa krawędź w pionie),
sterowany z ESP32 po SPI, pokazujący dwa ekrany: metadane odtwarzanej
muzyki z kontrolkami oraz ostrzeżenie o otwartym nadwoziu.

Projekt wizualny (kanwa Claude Design, pięć artboardów) jest wygenerowany
ze źródeł w `mockups/esp32_1v8/` — patrz `mockups/esp32_1v8/README.md`.

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

- Krój **Public Sans** — ten sam, którego używa `small_display/css/small.css`.

## Ekran 1 — Now Playing

Trzy pasma w pionie, zgodnie z układem „kontrolki powyżej i poniżej,
metadane pośrodku”:

```
┌────────────────────────┐
│  (ABS)  airbag  klucz  │  32 px — lampki usterek
├────────────────────────┤
│      ▶ BLUETOOTH       │
│       Nightcall        │  90 px — metadane
│        Kavinsky        │
│    ▬▬▬▬▬▬▬───────      │
├────────────────────────┤
│  (P)  │  ⊙ 130 km/h    │  36 px — stany kierowcy
└────────────────────────┘
```

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

Podział kontrolek jest celowy: **górne pasmo to lampki usterek**
(ABS, poduszka, immobilizer), **dolne to stany zależne od kierowcy**
(hamulec ręczny, tempomat). Slot tempomatu jest szerszy, bo po włączeniu
rozwija się o zadaną prędkość; przy wyłączonym zostaje w nim sam
wygaszony symbol i `---`.

### Kontrolki

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

Czego w assetach nie ma i trzeba dorobić osobno: **font bitmapowy**
na tytuł, wykonawcę i cyfry prędkości — to dane, zmieniają się w locie.
Koniecznie z Latin Extended-A, bo tytuły z BT przychodzą z ogonkami.

## Sygnały — dwa źródła

Kontrolki i otwarcia idą **wprost do ESP32**: w miejscu montażu jest
złącze fabrycznego wyświetlacza, na którym te stany są dostępne jako
poziomy 12 V / 0 V. Z BCM przychodzi tylko to, czego w aucie nie ma
w postaci prostego napięcia.

### Wprost z auta, przez PC817

| sygnał | ekran |
|---|---|
| ABS | 1 |
| hamulec ręczny | 1 |
| poduszka (SRS) | 1 |
| immobilizer | 1 |
| drzwi ×4, maska, klapa | 2 |

Układ wejściowy jest już w projekcie opisany — `docs/SCHEMATY_POLACZEN.md`
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

ESP32-S3 ma natywny kontroler USB-OTG, więc wpina się wprost w port USB
M910q i zgłasza jako CDC-ACM — bez mostka UART. W Arduino trzeba włączyć
**USB CDC On Boot**; wtedy `Serial` to ten port. Na płytkach z dwoma
gniazdami USB-C jedno idzie do natywnego USB, a drugie do mostka
(CH343/CP2102) — potrzebne jest to pierwsze.

**Reguła udev jest konieczna**, dokładnie z tego samego powodu co przy
K-Line (`docs/WDROZENIE_M910Q.md` §12): numeracja `/dev/ttyACM*` przeskakuje
między restartami, a w aucie siedzą już dwa Arduino na USB. Wzorem
`/dev/ttyUSB_kline` robimy `/dev/ttyACM_display`, dopasowanie po VID:PID
(natywne USB Espressifa to `303a:1001`) i po numerze seryjnym, jeśli
ustawisz własny.

Protokół — ten sam kształt linii `KLUCZ:wartość`, którym mówi już
`sensor_hub`, tylko w drugą stronę: tu BCM pisze, a ESP32 czyta.

```
TITLE:Nightcall
ARTIST:Kavinsky
PLAY:1
POS:87
DUR:258
CRUISE:1
SETSPD:130
```

Kodowanie UTF-8; po stronie ESP32 trzeba odwzorować polskie znaki na
pozycje w foncie bitmapowym. Po stronie BCM potrzebny jest mały moduł
subskrybujący powyższe tematy i wypisujący te linie do portu —
odwrotność `src/input/arduino_serial.py`.

Uwaga na **1200 bps**: rdzeń Arduino dla S3 traktuje otwarcie portu przy
tej prędkości jako żądanie wejścia w bootloader. Otwieranie z Pythona przy
115200 jest bezpieczne, ale skrypty przelatujące prędkościami potrafią
zresetować płytkę.

Sygnały pojazdu idą wprost na GPIO, więc **ekran 2 działa niezależnie od
komputera** — ostrzeżenie o otwartych drzwiach nie czeka na wstanie
M910q.

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

**Nie za samą przetwornicą step-down.** Przy ~60 mA ciągłego poboru to
1,44 Ah na dobę. Akumulator w 156 to ok. 60–70 Ah, a samo auto pobiera
już ~20–30 mA na spoczynku. Po dwóch tygodniach postoju zabraknie blisko
połowy pojemności — a JTD potrzebuje zdrowego akumulatora, żeby ruszyć.
Przyjęta granica pasożytniczego poboru dla całego auta to ~30–50 mA i ten
budżet jest już w dużej części zajęty.

Trzy wyjścia, od najprostszego:

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

Rekomendacja: wariant 1, a jeśli ostrzeżenie ma działać przy wyłączonym
zapłonie — wariant 2. Wariant 3 tylko wtedy, gdy ekran ma być stale
rezydentny, i wyłącznie z policzoną przetwornicą.

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

Rekomendacja: **osobno z +15**. Lampka ABS czy poduszki, która zapala się
pół minuty po przekręceniu kluczyka, jest gorsza niż jej brak, a zasilanie
z zapłonu i tak wychodzi na zero pod względem poboru.

## Do rozstrzygnięcia

1. Czy ABS i poduszka są dostępne na złączu fabrycznego wyświetlacza jako
   osobne linie 12 V — do zmierzenia w aucie.
2. Zasilanie: z USB czy osobno z +15 (patrz wyżej).
3. Czy przy tytułach dłuższych niż dwie linie zostawić wielokropek, czy
   dodać przewijanie (marquee).
