# Audyt repozytorium BCM v8.5 + plan naprawczy

Data audytu: 2026-07-04

## STATUS REALIZACJI (zaakceptowane 2026-07-04)

| Pozycja | Status |
|---|---|
| Przepisanie historii gita (usunięcie `.venv` 289 MB + ZIP 22 MB) | ✅ zrobione — pack 173 MB → 57 MB |
| Martwy kod → `legacy/` z oznaczeniem | ✅ zrobione — `legacy/README.md` |
| Logger GPS (`tracker.py`) jako moduł `tracking` | ✅ zrobione — naprawiony, domykanie tripów, statystyki, GPX |
| Arduino: sensor_hub (DOOR/IGN/RAIN/TEMP/PARK), watchdogi, nieblokujące BLE, `make -C arduino` | ✅ zrobione — wszystkie 3 sketche kompilują się |
| Optymalizacja startu (M910q): lazy-importy (import 2.29 s → 0.05 s), statyczny Tailwind (419 KB JS → 37 KB CSS), `defer`, idle-skip broadcastu, `bluetooth.enabled` | ✅ zrobione — rendering zweryfikowany na 4 ekranach |
| **Etap 1** — jednolite przełączniki `modules.*` (27 pozycji) + ekran Settings→Moduły + `/api/modules` + naprawa martwych kluczy configu + fix 5 modułów z NameError | ✅ zrobione |
| **Etap 2** — liveness-restart po crashu (watcher + `Restart=on-failure`), asynchroniczny EventBus, broadcast WS poza lockiem, watchdog pipeline'ów dashcam | ✅ zrobione (waitress świadomie pominięty — flask-sock nie działa pod waitress; kiosk = 1 klient) |
| **Etap 4** — prawdziwe DTC (KWP2000 0x18/0x14 + słownik EDC15C7 + symulator) i prawdziwy EQ (PipeWire filter-chain, 10 biquadów, `audio.eq_dsp_enabled`) | ✅ zrobione — DTC zweryfikowane end-to-end na symulatorze |
| **Etap 6** — suita testów zielona (419 passed; naprawione stare testy + nowe: arduino_serial, tracker, central_lock; `pytest-timeout`), ruff czysty, CI (GitHub Actions: ruff + pytest + kompilacja 3 sketchy arduino-cli) | ✅ zrobione |
| **Etap 7** — `docs/URUCHOMIENIE.md` (pełna polska instrukcja: x86 sim / M910q produkcja / OPi PC bench / Arduino / tabela 27 przełączników / troubleshooting) | ✅ zrobione |
| Sekrety w `config/bcm_config.yaml` (klucz OpenWeatherMap, hasła WiFi) | ⚠️ do decyzji — rotacja + przeniesienie do `.env` |

Zakres: cały kod (`src/`, `main.py`, `arduino/`, `config/`, `tests/`), dokumentacja (`README.md`,
`DEVELOPMENT_PLAN.md`, `bcm_v85_docs.html`, `docs/*.md`, `docs/x86-production/*.html`), frontend web.

Dokument składa się z trzech części:

- **Część I — Ustalenia audytu** (co jest nie tak i dlaczego, z odnośnikami do plików)
- **Część II — Zgodność z dokumentacją** (które założenia działają, które są częściowe, a które to atrapy)
- **Część III — Plan naprawczy w etapach** (do akceptacji; każdy etap można zamówić osobno)

---

## CZĘŚĆ I — USTALENIA AUDYTU

### 1. Higiena repozytorium (dlaczego repo „ładuje się" wolno)

| Problem | Skala | Skutek |
|---|---|---|
| Katalog `.venv/` jest zacommitowany do gita | **3241 plików, ~289 MB** na dysku, pack gita ~173 MB | Klonowanie/fetch trwa minuty zamiast sekund; venv z x86 i tak nie działa na ARM (Orange Pi) |
| Plik `stitch_heritage_warmth_wood_glow_prd (1).zip` w repo | 22 MB | Martwy balast w każdej kopii repo |
| Rzeczywisty kod + dokumentacja + assety | **~40 MB** | Tyle powinno ważyć całe repo |

`.gitignore` nie zawiera wpisu `.venv/` — środowisko wirtualne trafiło do historii commitem
„Add files via upload". Samo usunięcie z trackingu odchudzi checkout; pełne odchudzenie
`.git` wymaga przepisania historii (`git filter-repo`) — **decyzja do akceptacji** (przepisanie
historii unieważnia istniejące klony).

### 2. Krytyczny błąd systemu włącz/wyłącz modułów

To jest najważniejsze znalezisko audytu, bo dotyczy wprost Twojego wymagania
„pełne wdrożenie z opcją włączenia/wyłączenia fragmentów kodu":

- `BCMConfig.is_module_enabled()` (`src/core/config.py:127`) czyta **wyłącznie** klucz
  `modules.<nazwa>`, domyślnie `False`.
- Oba pliki YAML mają dodatkowy blok **`modules_v85:`**, którego **żaden kod nigdy nie czyta**
  (grep po całym `src/` — zero trafień).
- Skutek: **7 modułów v8.5 jest trwale wyłączonych**, mimo że w configu wyglądają na włączone:
  `rain_sensor`, `central_lock`, `lighting`, `performance`, `alarm`, `crash_detect`, `battery`
  (dodatkowo `battery` ma niezgodną nazwę — w YAML figuruje jako `battery_backup`).
- Kolejne podsystemy startują **z pominięciem systemu przełączników** (nie da się ich wyłączyć
  z configu): dashboard (zawsze), `BluetoothManager` (`main.py:203`), synchronizacja książki
  telefonicznej PBAP (`main.py:237`), `RoutePlanner`, `TripComputer`, `WebViewer :5002`,
  `SmallDisplayServer :5003`. `FuelSender` i `WiFi AP` mają klucze ad-hoc
  (`fuel_sender.enabled`, `wifi.enabled`) poza konwencją `modules.*`.

### 3. Stabilność — najpoważniejsze ryzyka

1. **Brak samonaprawy po crashu.** `bcm-headunit.service` ma `Restart=no`, a
   `ignition_watcher` reaguje tylko na **zbocza** sygnału zapłonu
   (`src/power/ignition_watcher.py:609-618`) — nigdy nie sprawdza, czy usługa nadal żyje.
   Jeśli aplikacja padnie w trakcie jazdy, ekran pozostaje martwy do wyłączenia i ponownego
   włączenia zapłonu. Dla urządzenia samochodowego to luka nr 1.
2. **Synchroniczny EventBus.** `publish()` woła subskrybentów inline
   (`src/core/event_bus.py:115-125`) — jeden wolny/zablokowany subskrybent (serial, subprocess,
   sieć) zamraża wątek nadawcy, np. pętlę odczytu OBD.
3. **Broadcast WebSocket pod globalnym lockiem.** `web_viewer.py:258-266` trzyma `_ws_lock`
   podczas `ws.send()` do każdego klienta — jeden na-wpół-zerwany klient blokuje cały UI.
4. **Wyciek procesów ffmpeg.** Strumień MJPEG (`web_viewer.py:681-683`): `proc.wait(timeout=3)`
   bez `except TimeoutExpired` i bez `kill()` — przy szybkich reconnectach mnożą się procesy
   ffmpeg, każdy zjada rdzeń CPU.
5. **Dashcam bez nadzoru.** `dashcam.py:182-193` sprawdza pipeline GStreamera raz, 0,5 s po
   starcie. Jeśli padnie w trasie — cicha utrata nagrań, bez restartu (krytyczne dla funkcji DVR).
6. **Serwer deweloperski Flaska w produkcji.** `app.run()` (Werkzeug) w `web_viewer.py:1456`,
   `small_viewer.py:292` — nieprzeznaczony do pracy 24/7 (nielimitowane wątki).

Na plus: wszystkie wątki mają `daemon=True`, prawie wszystkie `subprocess.run` mają `timeout`,
moduły startują w `try/except` (awaria jednego nie wywala reszty).

### 4. Wydajność — start systemu i frontend

1. **Eager importy w `main.py:34-51`** — importuje 19 funkcji startowych nawet dla wyłączonych
   modułów; m.in. `openauto` → `bluetooth.py` ciągnie `dbus` + GLib na starcie. Zmierzony import
   samego `main.py`: **~2,3 s** (na x86; na Orange Pi PC będzie wielokrotnie wolniej). Wzorzec
   lazy-import już istnieje w repo (`_lazy_start_dashboard`, `main.py:28-32`) — wystarczy go
   zastosować do wszystkich modułów.
2. **Tailwind Play/JIT w przeglądarce.** `index.html:8` ładuje pełny runtime 419 KB, który
   **kompiluje CSS na żywo przy każdym otwarciu strony** — bardzo kosztowne na Chromium kiosku
   na Orange Pi i blokuje pierwszy render. Docelowo: prekompilacja do jednego statycznego
   `.css` (Tailwind CLI) i usunięcie runtime'u.
3. **22 synchroniczne `<script>` bez `defer`** (~330 KB niezminifikowanego JS) + Leaflet ładowany
   zawsze, choć mapa jest tylko na ekranie Trip.
4. **Pętla broadcastu 15 FPS pracuje nawet bez klientów** (`web_viewer.py:253-270`) — ~60 odczytów
   z event busa + `json.dumps` co 66 ms na pustym łączu; stały pobór CPU na OPi.

### 5. Arduino — firmware vs oprogramowanie

1. **Brakujący producent telemetrii pojazdu (krytyczne).** Parser
   `src/input/arduino_serial.py:130-155` oczekuje linii `DOOR:`, `HBRAKE:`, `IGN:`, `RAIN:`,
   `TEMP:`, `PARK:`, `CRUISE:`, `IMMO:`, `AIRBAG:` — a firmware `rotary_encoder.ino` wysyła
   **tylko** `LIGHT:` i `FUEL:`. Dokument `docs/x86-production/06-arduino.html:643-680` opisuje
   te komunikaty, jakby istniały. Efekt: tematy `vehicle.doors`, `vehicle.rain`,
   `vehicle.handbrake` itd. nie mają producenta, więc zależne funkcje (alarm od drzwi, auto-wycieraczki,
   temperatura zewn. z Arduino) **nie mają danych na prawdziwym sprzęcie**. Trzeba dopisać
   obsługę tych wejść w firmware (lub jawnie wyciąć z dokumentacji).
2. **Brak watchdoga w obu sketchach** — szczególnie groźne dla `output_controller.ino` (Nano
   zasilane na stałe z bufora akumulatora): pojedyncze zawieszenie = konieczność fizycznego
   odłączenia zasilania.
3. **Blokujące operacje w pętli always-on Nano**: skan BLE do 2,5 s i nauka BLE do 5 s
   zamrażają obsługę pilota 433 MHz i auto-stop szyby (`output_controller.ino:484-545`).
4. **Brak jakiegokolwiek narzędzia budowania** — nie ma `platformio.ini` / `sketch.yaml` /
   `arduino-cli`; sketchy nie da się skompilować ani zweryfikować poza IDE. Biblioteki
   (HID-Project, RCSwitch, ArduinoJson 7) są tylko wspomniane w komentarzach.
5. Drobne: błędny docstring w `swc_remote.py:4-5` (Pod 2 jest na **A6**, nie A1; A1 to czujnik
   światła), nieużywane symbole w `output_controller.ino`, ciasne progi drabinki ADC.
6. **Co się zgadza** (zweryfikowane): baudy (115200 Pro Micro, 9600 Nano), mapa keycode'ów SWC,
   pełny protokół JSON `central_lock.py` ↔ `output_controller.ino`.

### 6. Testy i CI

- **Suita testów jest czerwona i nie nadaje się na bramkę wdrożeniową:**
  - `tests/test_input.py` — `ImportError` (importuje `SWC_BUTTONS`/`get_swc_action`, których już
    nie ma w `swc_remote.py`) → cała kolekcja pada z rc=2.
  - `tests/test_multimedia.py::TestBluetoothManager` — **wisi w nieskończoność** (konstruktor
    `BluetoothManager` sonduje sprzęt 5× z `sleep(2)`, brak trybu testowego; brak
    `pytest-timeout` w dev-deps).
  - Po ominięciu powyższych: **24 testy nieaktualne** (stare API `CameraController`, stare nazwy
    motywów `classic_alfa`/`modern_dark`/`oem_digital`, wersja „BCM v7", przeniesiony
    `bcm-power.service`). Wynik per plik: 249 pass / 24 fail / 1 error / 1 hang.
- **Zero CI** — brak `.github/workflows`, brak lintera (ruff/flake8), brak pre-commit, brak
  kompilacji Arduino w CI.
- Brak testów w ogóle dla: `src/vehicle/*` (w tym `central_lock`!), `src/location/*`,
  `src/network/*`, `src/weather/*`, `src/performance/*`, `arduino_serial.py`.

### 7. Rozjazdy klucz konfiguracyjny ↔ kod (cichy brak działania)

Kod czyta klucze, których nie ma w YAML (używa defaultów), a YAML ma klucze martwe:

| Kod czyta | YAML definiuje | Skutek |
|---|---|---|
| `camera.storage_path` (`dashcam.py:51`) | `camera.recording_path` | Nagrania lądują w `/tmp/bcm_dashcam` zamiast `/media/dashcam` |
| `camera.max_storage_bytes` (`dashcam.py:213`) | `camera.max_storage_gb` | Limit 128 GB **nie jest egzekwowany** |
| `power.shutdown_delay` (`power_manager.py:159`) | `power.shutdown_delay_seconds` | Konfigurowane opóźnienie ignorowane |
| `serial.kline.port_opi` (`obd/simulator.py:286`) | `serial.kline.port_opi_pc` | Na benchu OPi PC K-Line otwiera zły port (`/dev/ttyS3` zamiast `/dev/ttyUSB0`) |
| — | `crash_detection.*`, `alarm.sensors.*`, `tracking.*`, `brightness.mode/steps`, `swc.enabled`, `music_panel.enabled` | Martwe klucze — nic ich nie czyta |

Dodatkowo rozjazd defaultów WiFi AP (SSID/hasło różne w kodzie i YAML) oraz brak auto-wyboru
`bcm_config_opi_pc.yaml` przy wykrytej platformie `opi_pc` (bez `--config` bench bierze config x86).

---

## CZĘŚĆ II — ZGODNOŚĆ Z ZAŁOŻENIAMI DOKUMENTACJI

Status funkcji obiecanych w `README.md` / `bcm_v85_docs.html` / `DEVELOPMENT_PLAN.md`:

### Działa (zaimplementowane)

Spectrum visualizer (FFT), dual DVR + przełączanie 4 kamer (cofanie/kierunkowskazy), czujniki
parkowania + buzzer, Android Auto kiosk (MJPEG + touch), dwa ekrany (:5002 + :5003), SWC 24
przyciski z trybem nauki, pogoda (OpenWeatherMap), LTE, alarm (stan/syrena/SMS), 3 motywy,
komputer podróży, poziom paliwa (ADC), alert oblodzenia, crash detect + ochrona nagrań, monitor
akumulatora, follow-me-home, timer 0-100, czujnik deszczu, książka telefoniczna + dialer (PBAP),
planer trasy (ORS/TomTom).

**Uwaga:** duża część z tego jest „zaimplementowana", ale **martwa w praktyce** przez błąd
`modules_v85` (część I, pkt 2) i/lub brak danych z Arduino (część I, pkt 5.1).

### Częściowe lub atrapy

| Funkcja | Stan faktyczny |
|---|---|
| **K-Line DTC read/clear** | **Atrapa.** UI i endpointy istnieją (`/api/dtc/read|clear`), ale publikują eventy, których nikt nie subskrybuje. W `src/obd/` nie ma usług KWP2000 0x18 (ReadDTC) / 0x14 (ClearDTC). Odczyt zawsze zwraca pustą listę, kasowanie to no-op. |
| **10-pasmowy EQ** | **Atrapa DSP.** Suwaki, presety i API działają, ale `apply_eq_preset` tylko publikuje eventy — żaden filtr PipeWire (filter-chain) nie jest tworzony; `config/pipewire/eq-profile.json` ma format własny, nieładowalny przez PipeWire. Dźwięk nie jest korygowany. |
| **GPS tracking** | Pozycja na żywo działa, ale **rejestrator trasy `src/location/tracker.py` (SQLite) to martwy kod** — nigdy nie startowany. |
| **Central lock RF433** | Moduł faktycznie obsługuje pilota szyby 433 MHz + bagażnik BLE + PWM podświetlenia przez Nano — **nie steruje zamkiem centralnym** wbrew nazwie w README. |
| **Voice assistant** | Tylko „tap" w mikrofon AA + ducking — brak realnego rozpoznawania (zgodne z planem, ale README tego nie precyzuje). |
| **i18n** | Tylko PL + EN. |
| **Traffic (HERE)** | `src/network/traffic.py` — placeholder, martwy kod. |

### Martwy kod (nigdzie nieimportowany w produkcji)

`src/location/tracker.py`, `src/location/map_renderer.py`, `src/network/remote_status.py`,
`src/network/traffic.py`, `src/multimedia/aa_display.py` (port 5001 — porzucony),
`src/power/brightness.py`, `src/dashboard/screens/{classic_alfa,modern,oem_digital}.py`
oraz cała legacy ścieżka Pygame (renderer + ekrany) używana tylko do dev/demo.

Frontend ↔ backend: **wszystkie wywołania JS mają istniejące endpointy** (brak zerwanych par);
kilka endpointów jest osieroconych (m.in. `/api/dvr/play`, `/api/dvr/delete`, `/api/phone/status`).

---

## CZĘŚĆ III — PLAN NAPRAWCZY (do akceptacji)

Etapy są niezależne — możesz zaakceptować całość albo wybrane. Kolejność = priorytet.
Przy każdym etapie: kryterium odbioru.

### ETAP 0 — Higiena repozytorium (mały, natychmiastowy zysk)

1. Usunięcie `.venv/` z trackingu gita + wpis w `.gitignore`; usunięcie pliku ZIP 22 MB.
2. **Opcja do decyzji:** przepisanie historii (`git filter-repo`) → repo z ~173 MB do ~40 MB
   (wymaga wymuszonego pusha i ponownego sklonowania przez wszystkich).
3. Dodanie `pyproject.toml` z konfiguracją `ruff` (lint + format).

**Odbiór:** świeży klon < 45 MB (lub < 45 MB pack po filter-repo), `ruff check` przechodzi.

### ETAP 1 — Jednolity system włącz/wyłącz (Twoje główne wymaganie)

1. Naprawa `is_module_enabled`: scalenie `modules_v85` do `modules.*` (+ alias wsteczny,
   mapowanie `battery_backup` → `battery`), żeby 7 martwych modułów dało się realnie włączyć.
2. Przełącznik `modules.*` dla **wszystkich** podsystemów startowanych w `main.py`:
   `bluetooth`, `phonebook`, `fuel_sender`, `wifi_ap`, `route_planner`, `small_display`,
   `dashboard` — jedna konwencja, koniec kluczy ad-hoc.
3. Ekran **Settings → Moduły** w UI: lista wszystkich modułów z przełącznikami ON/OFF,
   zapis do YAML (`/api/modules` GET/POST), informacja „wymaga restartu" tam, gdzie trzeba.
4. Naprawa rozjazdów kluczy z części I pkt 7 (camera.storage_path, max_storage_bytes,
   shutdown_delay, port_opi_pc, ujednolicenie defaultów WiFi).
5. Auto-wybór `bcm_config_opi_pc.yaml` przy wykrytej platformie `opi_pc`.

**Odbiór:** `python main.py --dry-run` pokazuje zgodny z YAML stan wszystkich ~26 podsystemów;
zmiana przełącznika w UI po restarcie faktycznie włącza/wyłącza moduł.

### ETAP 2 — Stabilność (samochód = 24/7)

1. Samonaprawa po crashu: liveness-check w pętli `ignition_watcher` + `Restart=on-failure`
   z `StartLimitIntervalSec` w unitach systemd.
2. EventBus: dyspozycja przez kolejkę/pulę wątków (wolny subskrybent nie blokuje nadawcy).
3. WebSocket broadcast poza lockiem + odcinanie martwych klientów; pomijanie serializacji,
   gdy nie ma klientów.
4. ffmpeg MJPEG: `kill()` po `TimeoutExpired`; dashcam: watchdog pipeline'u z restartem
   i backoffem.
5. Zamiana serwera dev Werkzeug na `waitress` (czysty Python, działa na ARM).

**Odbiór:** `kill -9` procesu BCM przy „włączonym zapłonie" → UI wraca w < 15 s; symulowany
wolny subskrybent nie zatrzymuje odczytu OBD; test reconnectów streamu nie zostawia procesów ffmpeg.

### ETAP 3 — Szybszy start i lżejszy frontend

1. Lazy-import wszystkich 19 modułów w `main.py` (wzorem `_lazy_start_dashboard`) — import tylko
   włączonych; dbus/GLib przestaje ładować się, gdy Bluetooth wyłączony.
2. Prekompilacja Tailwind do statycznego `themes+utilities.css` (Tailwind CLI w skrypcie
   `config/scripts/`), usunięcie runtime'u 419 KB.
3. Bundling + minifikacja JS (esbuild — jeden plik albo `defer` na wszystkich skryptach),
   lazy-load Leaflet dopiero przy wejściu na ekran Trip.

**Odbiór:** import `main.py` < 0,5 s na x86; pierwszy render kiosku na OPi zauważalnie szybszy
(brak JIT-kompilacji CSS); Lighthouse/devtools: brak render-blocking skryptów.

### ETAP 4 — Dokończenie funkcji z dokumentacji

1. **DTC (KWP2000 0x18/0x14):** implementacja ReadDTCByStatus + ClearDiagnosticInformation
   w `kwp2000.py`/`edc15c7.py`, subskrybent `obd.dtc.*` publikujący `obd.dtc.codes`,
   symulator DTC na x86 (żeby UI dało się przetestować bez auta), słownik kodów EDC15C7.
2. **EQ naprawdę działający:** generacja configu `libpipewire-module-filter-chain` (10 pasm bq)
   z presetów, przeładowanie przy zmianie; fallback „symulowany" na x86 bez PipeWire.
3. **GPS logger:** podłączenie `tracker.py` jako moduł `tracking` (z przełącznikiem) albo
   usunięcie — **do decyzji** (klucze `tracking.*` już są w YAML, sugeruję podłączyć).
4. **Martwy kod:** usunięcie `traffic.py`, `remote_status.py`, `map_renderer.py`,
   `aa_display.py`, legacy ekranów Pygame (albo przeniesienie do `legacy/`) — **do decyzji**.
5. Korekta README/docs tam, gdzie obietnica ≠ zakres (central lock, voice assistant).

**Odbiór:** na symulatorze x86: odczyt DTC pokazuje wstrzyknięte kody i kasuje je; zmiana presetu
EQ słyszalnie zmienia dźwięk na OPi (weryfikacja pw-dump: węzeł filter-chain istnieje).

### ETAP 5 — Arduino: brakująca telemetria + niezawodność + kompilacja w repo

1. **Rozszerzenie `rotary_encoder.ino`** o wejścia i komunikaty `DOOR:`, `HBRAKE:`, `IGN:`,
   `RAIN:`, `TEMP:`, `PARK:` (piny do ustalenia ze schematem) — zgodnie z kontraktem
   `arduino_serial.py`; `CRUISE:/IMMO:/AIRBAG:` oznaczyć jako opcjonalne (lub wyciąć z parsera
   i docs — **do decyzji**).
2. **Watchdog AVR** w obu sketchach (`wdt_enable(WDTO_2S)` + `wdt_reset()` w pętli).
3. Przerobienie blokującego skanu BLE w `output_controller.ino` na maszynę stanów
   (pilot 433 MHz i auto-stop szyby działają w trakcie skanu).
4. **Tooling budowania:** `sketch.yaml` per sketch (FQBN + przypięte wersje bibliotek) +
   `arduino/Makefile` z celami `compile`/`upload` przez `arduino-cli` + instrukcja
   w `docs/ARDUINO_SETUP_GUIDE.md`. Sketche kompilowane w CI (etap 6).
5. Poprawki drobne: docstring A6 w `swc_remote.py`, deklaracja `reportFuelLevel()`,
   usunięcie martwych symboli.

**Odbiór:** `arduino-cli compile` przechodzi dla obu płytek lokalnie i w CI; na benchu
zwarcie wejścia DOOR do masy → event `vehicle.doors` na busie i reakcja alarmu.

### ETAP 6 — Testy zielone + CI

1. Naprawa `test_input.py` (nowe API), aktualizacja 24 nieaktualnych testów (motywy, wersja,
   `CameraController`, ścieżka `bcm-power.service`).
2. Tryb testowy `BluetoothManager` (wstrzykiwany skip sondowania) + `pytest-timeout`
   w `requirements-dev.txt` — koniec wiszącej suity.
3. Nowe testy minimum dla: `central_lock` (protokół JSON), `arduino_serial` (parser linii),
   `alarm`, `fuel_sender`, modułu przełączników z etapu 1.
4. **GitHub Actions:** workflow `ci.yml` — ruff + pytest (z timeoutem) + `arduino-cli compile`
   obu sketchy na każdy PR.

**Odbiór:** `pytest` przechodzi w 100% w < 3 min; badge CI zielony na PR.

### ETAP 7 — Dokumentacja uruchomieniowa „wszystko w jednym"

1. Nowy `docs/URUCHOMIENIE.md` (po polsku): trzy ścieżki krok po kroku — (a) symulacja x86,
   (b) bench Orange Pi PC, (c) produkcja Orange Pi 5 Pro — od klonu repo, przez flash Arduino
   (`make -C arduino compile upload`), po `systemctl enable`; tabela wszystkich przełączników
   `modules.*` z opisem co włączają.
2. Aktualizacja `README.md` (stan rzeczywisty + odnośnik do URUCHOMIENIE.md) i korekta
   `docs/x86-production/06-arduino.html` (fałszywy kontrakt komunikatów — po etapie 5 stanie
   się prawdziwy).

**Odbiór:** osoba z zewnątrz uruchamia symulację x86 wyłącznie wg URUCHOMIENIE.md bez pytań.

---

## Decyzje wymagane przed startem prac

1. **Przepisać historię gita** (repo 173 MB → ~40 MB, wymaga re-clone), czy tylko usunąć
   `.venv`/ZIP „od teraz"?
2. Martwy kod (`traffic`, `remote_status`, `map_renderer`, `aa_display`, ekrany Pygame):
   **usunąć** czy **podłączyć/zostawić w `legacy/`**?
3. `tracker.py` (logger trasy GPS do SQLite): podłączyć jako moduł `tracking` czy usunąć?
4. Telemetria Arduino: dopisać w firmware **wszystkie** komunikaty z parsera
   (`CRUISE:/IMMO:/AIRBAG:` też), czy tylko te z realnym okablowaniem w aucie
   (DOOR/HBRAKE/IGN/RAIN/TEMP/PARK)?
5. Kolejność/zakres etapów: całość (0→7) czy wybrane?
