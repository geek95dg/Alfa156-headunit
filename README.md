# Alfa156-headunit

BCM v8.5 — custom head unit for Alfa Romeo 156 1.9 JTD 8V, built on a
**Lenovo ThinkCentre M910q Tiny** (x86) with a buffered 12 V SLA supply.

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

## Quick start

```bash
git clone <repo> && cd Alfa156-headunit
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-x86.txt
./run_x86.sh          # dashboard: http://localhost:5002, small: :5003
```

- Modules are toggled in `config/bcm_config.yaml` (`modules:` block,
  plus `bluetooth.enabled`, `wifi.enabled`, `fuel_sender.enabled`).
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
  `docs/WDROZENIE_TESTOWE.md`, config `config/bcm_config_test.yaml`.
  Everything to buy for it, in one table: `docs/LISTA_ZAKUPOWA.md`.
- **Wyświetlacz pomocniczy 1,8" na ESP32** (ST7735 160×128) — projekt
  dwóch ekranów: metadane muzyki z 5 kontrolkami oraz rzut z góry auta
  z otwartymi drzwiami: `docs/WYSWIETLACZ_ESP32_1V8.md`, źródła kanwy
  w `mockups/esp32_1v8/`.
- Repo audit + improvement roadmap: `AUDYT_I_PLAN.md`. Unused legacy
  code lives in `legacy/`; docs for retired platforms (Orange Pi 5 Pro /
  5 Plus, Orange Pi PC bench rig, VMware smoke tests) live in
  `Archive/`.
- K-Line sniffing / reverse-engineering ECU PIDs (RPM, temps, …):
  `docs/KLINE_SNIFFING.md` + `tools/kline_sniffer.py`.
