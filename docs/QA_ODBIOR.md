# Ankieta QA — odbiór wdrożenia v8.5.3

Zakres: naprawa podów SWC, dźwięk przez gniazdo słuchawkowe, Android Auto,
przycięcie zestawu modułów do czterech funkcji (pogoda, planowanie trasy,
Android Auto, pody SWC).

Każdy punkt ma **dwie kolumny wyniku**:

- **[kontener]** — wypełnione podczas przygotowania zmian, na instancji BCM
  uruchomionej bez sprzętu (`main.py --platform x86 --config
  config/bcm_config.yaml --frontend`).
- **[M910q]** — do wypełnienia na docelowym komputerze, po `git pull`.

Legenda: **OK** · **BŁĄD** · **n/d** (nie do sprawdzenia w tym środowisku).

---

## A. Uruchomienie i zestaw modułów

| # | Sprawdzenie | Jak | Oczekiwane | [kontener] | [M910q] |
|---|-------------|-----|-----------|-----------|---------|
| A1 | BCM wstaje bez wyjątku | `journalctl -u bcm-headunit -n 100` | brak traceback | **OK** | |
| A2 | Startuje dokładnie 8 modułów | `curl -s localhost:5002/api/modules` | dashboard, audio, input, multimedia, weather, bluetooth, wifi_ap, route_planner | **OK** — dokładnie te 8 z 28 | |
| A3 | Wyłączone moduły milczą | log | brak wpisów od obd/parking/camera/gps/alarm | **OK** | |
| A4 | Interfejs odpowiada | `curl -o /dev/null -w '%{http_code}' localhost:5002/` | 200 | **OK** — 200, gotowe ~2 s od startu | |
| A5 | WebSocket podaje stan | połączenie na `ws://localhost:5002/ws` | snapshot z polami stanu | **OK** — 74 pola | |
| A6 | Start nie jest blokowany przez audio | znaczniki czasu w logu | moduł audio < 3 s | **OK** — 1 s (było 20 s przed poprawką) | |

## B. Dźwięk — gniazdo słuchawkowe na panelu przednim

> To był główny problem: kod **nigdy nie wybierał sinka sprzętowego**, a jedyne
> miejsce ustawiające domyślne wyjście kierowało je na łańcuch EQ. Ręczne
> `wpctl set-default` było cofane 0,3–3 s po starcie BCM.

| # | Sprawdzenie | Jak | Oczekiwane | [kontener] | [M910q] |
|---|-------------|-----|-----------|-----------|---------|
| B1 | BCM wybiera wyjście analogowe, nie HDMI | `journalctl -u bcm-headunit \| grep "Hardware sink"` | `Hardware sink -> alsa_output...analog-stereo` | **n/d** — brak PipeWire | |
| B2 | Wybór przeżywa restart usługi | restart + B1 | ta sama nazwa | **n/d** | |
| B3 | Łańcuch EQ jest przypięty do tego sinka | `grep target.object /tmp/bcm_eq_filter.conf` | wskazuje sink z B1 | **n/d** | |
| B4 | Sink EQ faktycznie powstaje | `wpctl status \| grep bcm_eq_sink` | widoczny | **n/d** | |
| B5 | Gdy EQ nie wstanie — wraca sink sprzętowy | log | `ERROR ... restoring ... as default` | **n/d** | |
| B6 | Wyjście jest odciszone | `wpctl get-volume @DEFAULT_AUDIO_SINK@` | brak `[MUTED]` | **n/d** | |
| B7 | **Z głośnika w jacku leci dźwięk** | `speaker-test -c2 -twav -l1` przy podłączonych słuchawkach | słychać | **n/d** | |
| B8 | Dźwięk z odtwarzania w BCM | uruchom cokolwiek na ekranie Audio | słychać | **n/d** | |
| B9 | Regulacja głośności działa | `curl -X POST -d '{"volume":55}' .../api/audio/volume` | `{"ok":true}` i słyszalna zmiana | **OK** (API) / **n/d** (słyszalność) | |
| B10 | Po zatrzymaniu BCM nie zostaje sierocy proces | `pgrep -af "pipewire -c /tmp/bcm_eq"` | pusto | **n/d** | |

**Logika wyboru sinka przetestowana jednostkowo** (nie wymaga sprzętu):
`pytest tests/test_audio.py -k OutputSelection` — 8 przypadków, w tym
„HDMI nigdy nie wygrywa z analogowym", „literówka w `audio.sink` nie zostawia
bez dźwięku", „sink EQ nie może zostać wybrany jako sprzętowy". **OK**

## C. Android Auto

> Przyczyna była poza kodem BCM: **binarki `autoapp` nie instaluje
> `setup-x86.sh`** — trzeba ją skompilować ze źródeł.

| # | Sprawdzenie | Jak | Oczekiwane | [kontener] | [M910q] |
|---|-------------|-----|-----------|-----------|---------|
| C1 | Brak binarki jest zgłaszany głośno | log przy starcie | `ERROR ... Android Auto WILL NOT WORK` + komenda naprawcza | **OK** | |
| C2 | Binarka po kompilacji | `sudo bash config/scripts/install-openauto.sh` → `ls -la /usr/local/bin/autoapp` | plik ~5 MB | **n/d** — brak dostępu do sieci | |
| C3 | BCM ją widzi | log | `OpenAuto found: /usr/local/bin/autoapp` | **n/d** | |
| C4 | Konfiguracja nie zawiera martwych credentiali | `grep _runtime config/bcm_config.yaml` | puste wartości | **OK** | |
| C5 | Credentiale P2P trafiają do `openauto.ini` | po starcie AP: `grep -i ssid openauto.ini` | SSID zgodny z `wpa_cli status` | **n/d** — brak karty WiFi | |
| C6 | P2P-GO wstaje | `journalctl \| grep -i p2p` | grupa utworzona, kanał 149 | **n/d** | |
| C7 | Telefon paruje się po BT | z telefonu | widoczne „Alfa156 Headunit" | **n/d** — brak `bluetoothctl` | |
| C8 | **Android Auto pokazuje obraz** | ekran A2 | pulpit AA zamiast komunikatu | **n/d** | |
| C9 | Ekran A2 nazywa problem po imieniu | ekran A2 bez binarki | „OpenAuto not installed" | **OK** — `aa_status=unavailable` | |

## D. Pody SWC („pin pad")

> Trzy niezależne przyczyny fałszywych zdarzeń: pływające wejścia analogowe,
> przesłuch multipleksera ADC (stąd oba pody raportowały **ten sam** przycisk
> przy tej samej wartości) i brak realnego debounce'u.

| # | Sprawdzenie | Jak | Oczekiwane | [kontener] | [M910q] |
|---|-------------|-----|-----------|-----------|---------|
| D1 | Firmware się kompiluje | `make -C arduino rotary_encoder` | bez błędów | **OK** — sprawdzone `g++ -fsyntax-only` na atrapach API, wszystkie kombinacje `FEATURE_*` czyste przy `-Wall -Wextra`; pełna kompilacja AVR w jobie `arduino` w CI | |
| D2 | **Płytka milczy, gdy nic nie jest wciśnięte** | monitor 115200 po wgraniu | brak linii `SWC1:`/`SWC2:` | **n/d** | |
| D3 | Odczyt spoczynkowy jest wysoki | kalibracja pokazuje ADC | ~1023 przy rozwarciu | **n/d** | |
| D4 | Pody nie kopiują się nawzajem | wciśnij przycisk na Pod 1 | reaguje **tylko** `SWC1:` | **n/d** | |
| D5 | Kalibracja bez przycisków | wyślij `CAL` + Enter na port | wchodzi w tryb kalibracji | **n/d** | |
| D6 | Kalibracja zapisuje się w EEPROM | restart płytki | `SWC: Loaded calibration from EEPROM` | **n/d** | |
| D7 | Przyciski działają w BCM | głośność/następny utwór z kierownicy | reakcja na ekranie | **n/d** | |
| D8 | Szum nie wyłącza BCM | obserwacja przez dłuższą jazdę | brak samoczynnych wyłączeń (SWC MODE wysyła F10 → `bcm_power_toggle`) | **n/d** | |

## E. Pogoda i planowanie trasy

| # | Sprawdzenie | Jak | Oczekiwane | [kontener] | [M910q] |
|---|-------------|-----|-----------|-----------|---------|
| E1 | Moduł pogody startuje | log | `WeatherManager started (api_key=set)` | **OK** | |
| E2 | Pogoda działa bez GPS i bez LTE | ekran pogody | dane dla `weather.default_lat/lon` | **OK** — fallback zadziałał | |
| E3 | Brak klucza ORS jest zgłaszany | log | `ERROR RoutePlanner: brak travel.openrouteservice_key` | **OK** | |
| E4 | Trasa przybliżona jest oznaczona | wyznacz cel bez klucza | `approximate=true` + pasek ostrzegawczy w UI | **OK** — Kraków→Gdynia 504,5 km w linii prostej (drogą ~590 km), flaga ustawiona | |
| E5 | **Trasa realna po wpisaniu klucza** | wpisz `travel.openrouteservice_key`, restart, wyznacz cel | `approximate=false`, dystans zgodny z drogą | **n/d** — brak klucza | |
| E6 | Wyszukiwanie celu | ekran Trip → wpisz miasto | podpowiedzi | **n/d** — wymaga internetu | |

## F. Regresja

| # | Sprawdzenie | Jak | Oczekiwane | [kontener] | [M910q] |
|---|-------------|-----|-----------|-----------|---------|
| F1 | Testy jednostkowe | `pytest -q` | wszystkie zielone | **OK** — 447 (+25 nowych) | |
| F2 | Lint | `ruff check .` | czysto | **OK** | |
| F3 | Przełączniki modułów są spójne | `pytest -k ShippedModuleConfig` | zielone | **OK** | |
| F4 | Brak osieroconych topików | analiza producent/subskrybent | żaden włączony moduł nie czeka na wyłączony | **OK** — `power.shutting_down` naprawione (publikuje `main.py`), `gps.*`/`lte.*` mają fallback na x86, `power.modules_start` dotyczy tylko wybudzenia w locie | |

---

## Znane pozostałości

1. **`weather.api_key` jest w repozytorium** (`config/bcm_config.yaml`) — działający
   klucz OpenWeatherMap w gicie. Nie ruszałem tego bez Twojej decyzji; proponuję
   przenieść do zmiennej środowiskowej albo pliku poza repo i unieważnić obecny.
2. **Regulacja jasności nie jest podpięta.** Przycisk manetki wysyła F9,
   `action_dispatch` mapuje to na `input.brightness_cycle`, ale
   `BrightnessController` nie jest nigdzie instancjonowany. To samo dotyczy
   fotorezystora. Poza zakresem tej rundy.
3. **`input.mute` nie ma subskrybenta** — przycisk MUTE na kierownicy nic nie robi
   po stronie BCM (wysyła też klawisz Consumer, więc system to wyciszy).

## Kolejność jutro na M910q

```bash
cd /opt/bcm
git pull                                         # gałąź claude/m910q-deployment-docs-33g92j
sudo bash config/scripts/install-openauto.sh     # 30–60 min kompilacji
# wpisz travel.openrouteservice_key w config/bcm_config.yaml
sudo systemctl restart bcm-headunit
journalctl -u bcm-headunit -f
```

Firmware Pro Micro osobno — z Arduino IDE albo:

```bash
make -C arduino rotary_encoder-upload PORT=/dev/ttyACM0
```

Potem kalibracja podów: podłącz się monitorem szeregowym na 115200 i wyślij
`CAL`. Pody muszą być **już podłączone**, a jeśli dokładasz zewnętrzne
podciągnięcie 10 kΩ do VCC — też przed kalibracją, bo przy pasywnej drabince
współtworzy ono dzielnik.
