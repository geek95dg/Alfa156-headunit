# Alfa156-headunit

BCM v8.5 — custom head unit for Alfa Romeo 156 1.9 JTD 8V, built on a
**Lenovo ThinkCentre M910q Tiny** (x86) with a buffered 12 V supply (7 × CSB HR1221W AGM in parallel, two baskets in the trunk).

- Body computer functions (fuel consumption, fuel level, temperatures, weather, service notifications)
- 4-channel audio with 10-band EQ and spectrum visualizer — ES9038Q2M USB DAC
  into an off-the-shelf car amplifier fed straight from the starter battery
- Dual DVR (front + rear) + 4-camera auto-switching (reverse, blinkers)
- Ultrasonic parking sensors with buzzer
- Android Auto (kiosk mode, integrated in dashboard)
- Dual screen: 10.1" 1280x800 touchscreen (A1-A8 + Settings) + optional
  6.86" 1280x480 widescreen stats display (hot-pluggable)
- SWC steering wheel remote with configurable button mapping (dual-pod, 24 buttons, learn mode)
- K-Line OBD-II diagnostics (KWP2000) with DTC read/clear
- GPS tracking, weather, LTE connectivity
- Central lock with RF 433MHz remote, alarm system
- 3 themes: Heritage, Modern, Autodelta
- GPS route logger (SQLite + GPX export) — `modules.tracking`

## Auto testowe — instrukcja dla właściciela (PL)

- **[`docs/WDROZENIE_TESTOWE_TELEFON.md`](docs/WDROZENIE_TESTOWE_TELEFON.md)** —
  krok po kroku: co się zmieniło w #126–#129, „już wdrożyłem — co teraz”
  (migracja ustawień, sekrety, `bcm-harden.sh`, `apply-fixes.sh`, autoapp),
  BIOS, główny telefon (internet i GPS), audio i mikrofon, tabela
  przełączników modułów, lista sprawdzeń, wycofanie zmian, **przejście na
  konfigurację docelową `config/bcm_config.yaml` (§13)**.
- **[`docs/PRZYGOTOWANIE_TELEFONU.md`](docs/PRZYGOTOWANIE_TELEFONU.md)** —
  telefon w aucie (Redmi Note 8 Pro, crDroid 13): ROM, Termux, agent BCM,
  „Zadzwoń 112”, alarm na postoju, czuwanie kabiny, jasność.
- **[`docs/TRACCAR_SERWER.md`](docs/TRACCAR_SERWER.md)** — auto na mapie:
  własny serwer Traccar (LXC w Proxmoxie albo Docker), nginx z HTTPS
  (pozycje przez podkatalog, panel na subdomenie), Traccar Manager.
- **Gdzie są ustawienia:** baza `config/bcm_config.yaml` — konfiguracja
  docelowa auta od 23.11 (w gicie, BCM jej nie zmienia) → `config/local.yaml`
  (poza gitem; zmiany z ekranu, zapis atomowy) → `/etc/bcm/bcm.env`
  (sekrety: klucze API, sekret agenta; 0600 root:root, wzór
  w `config/bcm.env.example`). Bazę wskazuje `BCM_CONFIG` (domyślna
  w unicie; powrót na konfigurację testową `config/bcm_config_test.yaml`:
  linia w `/etc/bcm/bcm.env` + przywrócenie kopii `config/local.yaml`
  sprzed migracji, §13.7). Przejście z konfiguracji testowej na
  docelową (migracja `config/local.yaml` przez
  `tools/migrate_local_config.py`): `docs/WDROZENIE_TESTOWE_TELEFON.md` §13.

## Quick start

```bash
git clone <repo> && cd Alfa156-headunit
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-x86.txt
./run_x86.sh          # dashboard: http://localhost:5002, small: :5003
```

- Modules are toggled in Settings → Moduły on the car screen (saved to
  `config/local.yaml`) or in the base YAML (`modules:` block, plus the
  legacy `bluetooth.enabled`, `wifi.enabled`, `fuel_sender.enabled`).
  The list with dependencies lives in `src/core/modules_catalog.py`.
- Arduino firmware (3 boards): `make -C arduino` compiles all sketches,
  `make -C arduino <sketch>-upload PORT=/dev/ttyXXX` flashes one —
  see `docs/ARDUINO_SETUP_GUIDE.md`. Never touched an Arduino before?
  Start with `docs/ARDUINO_OD_ZERA.md` (PL) — cable, USB driver, IDE,
  first upload and a bench test, step by step.
- After changing Tailwind classes in the web UI run
  `config/scripts/build-frontend.sh` (CSS is precompiled — there is no
  runtime Tailwind engine).
- **Deployment (production, M910q):** `docs/WDROZENIE_M910Q.md` —
  hardware, BIOS, OS, services, verification. Power system in detail:
  `docs/ZASILANIE_BUFOROWANE.md` + `schematics/`.
- **Test / dev build** — a rolling install with the full power chain but only
  wireless Android Auto, audio and the steering-wheel buttons switched on:
  `docs/WDROZENIE_TESTOWE.md`, config `config/bcm_config_test.yaml` (since
  23.11 the bench config; the car runs the final `config/bcm_config.yaml`).
  Everything to buy for it, in one table: `docs/LISTA_ZAKUPOWA.md`.
- **Wyświetlacz pomocniczy 1,8" na ESP32** (ST7735 128×160, pionowo) — dwa
  ekrany: metadane muzyki z czterema kontrolkami i tempomatem oraz rzut z góry
  auta z otwartymi drzwiami. Projekt i protokół: `docs/WYSWIETLACZ_ESP32_1V8.md`; firmware
  `arduino/esp32_display/` (`make -C arduino esp32_display-test`); most po
  stronie BCM `src/dashboard/esp32_link.py` (`modules.esp32_display`);
  okablowanie `docs/SCHEMATY_POLACZEN.md` §11 +
  `schematics/esp32_display_wiring.svg`; wpięcie do M910q i reguła udev
  `docs/WDROZENIE_M910Q.md` §20.
- Repo audit + improvement roadmap: `AUDYT_I_PLAN.md`. Unused legacy
  code lives in `legacy/`; docs for retired platforms (Orange Pi 5 Pro /
  5 Plus, Orange Pi PC bench rig, VMware smoke tests) live in
  `Archive/`.
- K-Line sniffing / reverse-engineering ECU PIDs (RPM, temps, …):
  `docs/KLINE_SNIFFING.md` + `tools/kline_sniffer.py`.
