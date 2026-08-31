# Wyświetlacz pomocniczy 1,8" na ESP32 — projekt ekranów

Mały panel ST7735 **160×128 px, landscape**, sterowany z ESP32 po SPI,
pokazujący dwa ekrany: metadane odtwarzanej muzyki z kontrolkami oraz
ostrzeżenie o otwartym nadwoziu.

Projekt wizualny (kanwa Claude Design, sześć artboardów) jest wygenerowany
ze źródeł w `mockups/esp32_1v8/` — patrz `mockups/esp32_1v8/README.md`.

## Założenia

- Panel jest **wyłącznie wyświetlaczem** — bez dotyku, bez przycisków.
  Wszystkie sterowanie zostaje na głównym ekranie 10,1" i przy kierownicy.
- Rysunek w prawdziwych pikselach: artboardy mają kontener 160×128
  przeskalowany `scale(4)`, więc każda wartość `px` w środku to jeden
  piksel wyświetlacza.
- Paleta z motywu **Heritage** (domyślny w `config/bcm_config.yaml`),
  ta sama, którą ma drugi ekran 6,86":

  | rola | kolor |
  |---|---|
  | tło | `#0a0a0a` |
  | tekst główny | `#f4f4f5` |
  | tekst drugorzędny | `#a1a1aa` / `#71717a` |
  | akcent (pasek postępu) | `#f59e0b` |
  | linie podziału | `#27272a` |
  | kontrolka wygaszona | `#3f3f46` |

- Krój **Public Sans** — ten sam, którego używa `small_display/css/small.css`.

## Ekran 1 — Now Playing

Trzy pasma w pionie, zgodnie z układem „kontrolki powyżej i poniżej,
metadane pośrodku”:

```
┌──────────────────────────────────────┐  27 px
│   (ABS)      airbag        klucz     │  kontrolki usterek
├──────────────────────────────────────┤
│            ▶ BLUETOOTH               │
│             Nightcall                │  67 px
│              Kavinsky                │  metadane
│         ▬▬▬▬▬▬▬▬▬────────            │
├──────────────────────────────────────┤
│    (P)     │  ⊙  130 km/h            │  31 px
└──────────────────────────────────────┘  kontrolki kierowcy
```

| element | rozmiar | waga | kolor |
|---|---|---|---|
| źródło dźwięku | 7 px | 800 | `#52525b` |
| tytuł | 15 px | 800 | `#f4f4f5` |
| wykonawca | 10 px | 600 | `#a1a1aa` |
| pasek postępu | 132 × 3 px | — | `#f59e0b` na `#27272a` |
| symbol kontrolki | 20 × 20 px | — | zależnie od stanu |
| zadana prędkość | 20 px | 900 | `#22c55e` |

Tytuł i wykonawca są ucinane wielokropkiem przy 132 px (ok. 20 znaków).

Podział kontrolek jest celowy: **górne pasmo to lampki usterek**
(ABS, poduszka, immobilizer), **dolne to stany zależne od kierowcy**
(hamulec ręczny, tempomat). Slot tempomatu jest szerszy, bo po włączeniu
rozwija się o zadaną prędkość; przy wyłączonym tempomacie zostaje w nim
sam wygaszony symbol i `---`.

Kolory lampek zgodne z zegarami 156: ABS i immobilizer bursztynowe
(`#f59e0b`), hamulec i poduszka czerwone (`#ef4444`), tempomat zielony
(`#22c55e`).

## Ekran 2 — otwarte nadwozie

**Zasłonięcie stałe**: dopóki którykolwiek czujnik zgłasza otwarcie, ten
ekran przykrywa ekran 1 w całości — bez timeoutu, bez naprzemiennego
przełączania i bez powrotu do muzyki. Znika dopiero, gdy wszystko jest
zamknięte.

Bryła to rzut z góry Alfy Romeo 156 Berlina w proporcji 4430 : 1743 mm
(1 jednostka rysunku ≈ 39,6 mm). Otwarte drzwi rysowane są jako skrzydło
wychylone na zewnątrz na przednim zawiasie; maska i klapa bagażnika jako
wypełniony panel plus wysunięta poza obrys uniesiona pokrywa.

Do wyboru są **dwa warianty** (artboardy obok siebie na kanwie):

- **Wariant A** *(wiodący)* — bryła po lewej (66 × 112 px), po prawej
  nagłówek `⚠ OTWARTE` i lista nazw paneli. Czyta się bez interpretowania
  grafiki i mieści wszystkie sześć pozycji naraz (`DoorsAll.dc.html`).
- **Wariant B** — czerwony baner alarmowy u góry z licznikiem otwartych
  paneli, pod nim bryła obrócona nosem w lewo przez całą szerokość
  ekranu. Mocniejszy alarmowo i lepiej wykorzystuje format landscape,
  ale identyfikacja panelu opiera się wyłącznie na grafice.

Nazwy paneli po polsku: `PRZÓD L`, `PRZÓD P`, `TYŁ L`, `TYŁ P`, `MASKA`,
`BAGAŻNIK`.

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

1. Wariant A czy B dla ekranu 2.
2. Sposób podłączenia ESP32 do BCM (UART do M910q kontra własny link do
   `sensor_hub`) — nie jest częścią tego projektu wizualnego.
3. Czy przy tytułach dłuższych niż 132 px zostawić wielokropek, czy dodać
   przewijanie (marquee).
