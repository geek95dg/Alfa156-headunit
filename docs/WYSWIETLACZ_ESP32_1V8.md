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

## Sygnały

Gotowe na magistrali zdarzeń BCM (`src/input/arduino_serial.py`,
`arduino/sensor_hub/sensor_hub.ino`):

| temat | typ | używa |
|---|---|---|
| `vehicle.doors` | dict `{fl, fr, rl, rr, bonnet, trunk}` | ekran 2 |
| `vehicle.handbrake` | bool | ekran 1 |
| `vehicle.cruise` | bool | ekran 1 |
| `vehicle.immo_ok` | bool | ekran 1 |
| `vehicle.airbag_ok` | bool | ekran 1 |
| `bt.media_title` / `_artist` / `_position` / `_duration` / `_playing` | — | ekran 1 |

Do dodania:

| temat | typ | skąd |
|---|---|---|
| `vehicle.abs_fault` | bool | brak — wymaga nowego wejścia w `sensor_hub` |
| `vehicle.cruise_set_speed` | int (km/h) | ECU → K-Line → BCM → ESP32 |

`FEATURE_CRUISE`, `FEATURE_IMMO` i `FEATURE_AIRBAG` są w firmware
`sensor_hub` domyślnie zakomentowane — dla tego wyświetlacza trzeba je
włączyć.

## Do rozstrzygnięcia

1. Sposób podłączenia ESP32 do BCM (UART do M910q kontra własny link do
   `sensor_hub`) — nie jest częścią tego projektu wizualnego.
2. Czy przy tytułach dłuższych niż dwie linie zostawić wielokropek, czy
   dodać przewijanie (marquee).
