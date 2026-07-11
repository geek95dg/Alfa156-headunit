# LEGACY — kod nieużywany w produkcji

**Nic z tego katalogu nie jest importowane przez `main.py` ani żaden moduł produkcyjny.**
Pliki trafiły tu podczas audytu (patrz `AUDYT_I_PLAN.md`), zamiast zostać usunięte,
żeby zachować możliwość powrotu do nich. Każdy plik ma na górze baner `LEGACY`.

| Plik | Co to było | Dlaczego tu jest |
|---|---|---|
| `src/network/traffic.py` | Dane o ruchu drogowym (HERE) | Placeholder — provider nigdy nie podłączony, brak importerów |
| `src/network/remote_status.py` | Zdalny status przez HTTP (port 5004) | Nigdy nie startowany z `main.py` |
| `src/location/map_renderer.py` | Renderer kafelków mapy dla Pygame | Zastąpiony przez Leaflet w web frontendzie |
| `src/multimedia/aa_display.py` | Serwer AA na porcie 5001 | Port 5001 porzucony — AA jest serwowane z portu 5002 (`web_viewer.py`) |
| `src/dashboard/screens/classic_alfa.py` | Stary motyw ekranowy Pygame | Motywy przeniesione do `src/dashboard/themes/` (heritage/modern/autodelta) |
| `src/dashboard/screens/modern.py` | j.w. | j.w. |
| `src/dashboard/screens/oem_digital.py` | j.w. | j.w. |

Uwagi:

- Ścieżka Pygame (`src/dashboard/renderer.py` + pozostałe `src/dashboard/screens/*`)
  **nie** jest legacy w pełni — służy do dev/debug na x86 (`./run_x86.sh --pygame`)
  i dostarcza `DemoDataGenerator` dla trybu symulacji.
- `src/power/brightness.py` jest obecnie niepodłączony w produkcji, ale zostaje w `src/`,
  bo korzystają z niego testy i jest kandydatem do podłączenia (sterowanie jasnością z LDR).
- Starsze unity systemd leżą w `config/systemd/legacy/`.
