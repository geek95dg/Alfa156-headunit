# Wyświetlacz ESP32 1,8" — źródła projektu ekranów

Pliki `.dc.html` to pojedyncze artboardy kanwy Claude Design; `canvas.json`
opisuje ich rozmieszczenie i przypięte notatki.

| Plik | Co pokazuje |
|---|---|
| `Main.dc.html` | Ekran 1 — Now Playing, wszystkie kontrolki wygaszone |
| `NowPlayingActive.dc.html` | Ekran 1 — usterka ABS, hamulec ręczny, tempomat 130 km/h |
| `Doors.dc.html` | Ekran 2, wariant A — bryła + lista otwartych paneli |
| `DoorsCentral.dc.html` | Ekran 2, wariant B — baner alarmowy + bryła poziomo |
| `DoorsAll.dc.html` | Ekran 2, wariant A — wszystkie sześć paneli otwarte |
| `Telltales.dc.html` | Arkusz symboli kontrolek (referencja dla firmware) |

Każdy artboard rysuje ekran w prawdziwych pikselach ST7735 (160×128)
w kontenerze przeskalowanym `transform: scale(4)` — wartości `font-size`,
`width` i `height` w środku to bezpośrednio piksele wyświetlacza.

## Regeneracja

Bryła auta i arkusz kontrolek są generowane, żeby geometria i symbole
były identyczne we wszystkich wariantach:

```bash
python3 _gen_doors.py       # Doors / DoorsAll / DoorsCentral
python3 _gen_telltales.py   # Telltales
```

`Main.dc.html` i `NowPlayingActive.dc.html` edytuje się bezpośrednio.

Opis obu ekranów, palety i sygnałów: `docs/WYSWIETLACZ_ESP32_1V8.md`.
