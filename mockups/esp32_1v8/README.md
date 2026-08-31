# Wyświetlacz ESP32 1,8" — źródła projektu ekranów

Pliki `.dc.html` to pojedyncze artboardy kanwy Claude Design; `canvas.json`
opisuje ich rozmieszczenie i przypięte notatki.

| Plik | Co pokazuje |
|---|---|
| `Main.dc.html` | Ekran 1 — Now Playing, wszystkie kontrolki wygaszone |
| `NowPlayingActive.dc.html` | Ekran 1 — usterka ABS, hamulec ręczny, tempomat 130 km/h |
| `Doors.dc.html` | Ekran 2 — otwarte przednie lewe i bagażnik |
| `DoorsAll.dc.html` | Ekran 2 — wszystkie sześć paneli otwarte |
| `Telltales.dc.html` | Arkusz symboli kontrolek (referencja dla firmware) |

Oba ekrany rysowane są w prawdziwych pikselach ST7735 (128×160, pionowo)
w kontenerze przeskalowanym `transform: scale(4)` — wartości `font-size`,
`width` i `height` w środku to bezpośrednio piksele wyświetlacza.
Arkusz kontrolek to referencja, nie ekran, więc ma własny format 640×512.

## Regeneracja

Wszystko jest generowane, żeby symbole i geometria bryły nie rozjechały
się między artboardami:

```bash
python3 _gen_screens.py     # Main / NowPlayingActive / Doors / DoorsAll
python3 _gen_telltales.py   # Telltales
```

`_icons.py` trzyma symbole kontrolek — jedno źródło dla ekranu 1
i arkusza. Bryła auta mieszka w `_gen_screens.py` (`car()`).

`assets_preview.png` nie jest artboardem — to podgląd sprite'ów wypalonych
z renderów przez `tools/esp32_assets.py`, wrzucany tu po każdym przebiegu
generatora, żeby dało się je obejrzeć okiem przed wgraniem na panel.

Opis obu ekranów, palety, sygnałów i zasilania:
`docs/WYSWIETLACZ_ESP32_1V8.md`.
