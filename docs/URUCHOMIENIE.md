# BCM v8.5 — Instrukcja uruchomienia (Alfa Romeo 156 Head Unit)

Kompletny przewodnik uruchomienia projektu — od symulacji na laptopie,
przez produkcyjną instalację w aucie (Lenovo M910q), po stanowisko
testowe na Orange Pi PC i firmware Arduino.

---

## 1. Ścieżka A — symulacja na x86 (dev/test, ~10 minut)

Nie potrzebujesz żadnego sprzętu — cały system uruchamia się na zwykłym
PC/laptopie z Linuksem, z symulowanymi danymi pojazdu.

```bash
git clone https://github.com/geek95dg/Alfa156-headunit.git
cd Alfa156-headunit

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-x86.txt

./run_x86.sh
```

Po starcie otwórz w przeglądarce:

| Adres | Co to jest |
|-------|------------|
| http://localhost:5002 | Główny ekran (7/8" dotykowy) — strony A1–A8 + Settings, 3 motywy; Android Auto i Bluetooth zintegrowane na tym porcie |
| http://localhost:5003 | Mały wyświetlacz (4.3") — karuzela statystyk + kamera cofania |

Zatrzymanie: `Ctrl+C`.

### Tryby uruchomienia

```bash
./run_x86.sh                        # domyślnie: frontend HTML5/Tailwind
./run_x86.sh --pygame               # legacy renderer Pygame (okno 800x480, wymaga $DISPLAY)
./run_x86.sh --headless             # sam backend + web frontend, bez wyświetlacza
./run_x86.sh --modules obd,dashboard  # tylko wybrane moduły (lista rozdzielona przecinkami)
```

Dodatkowe flagi trafiają wprost do `main.py` (np. `--dry-run` wypisuje
listę modułów bez startu, `--config <plik>` wskazuje inny YAML).

### Testy

```bash
pip install -r requirements-dev.txt
pytest            # uruchamia całość z katalogu tests/
```

---

## 2. Ścieżka B — produkcja na Lenovo M910q (x86)

Pełna, krok-po-kroku instrukcja: **[docs/X86_PLATFORM_SETUP.md](X86_PLATFORM_SETUP.md)**.
Wersja HTML z ilustracjami (BOM, montaż, K-Line, czujniki, weryfikacja):
**[docs/x86-production/index.html](x86-production/index.html)** (rozdziały 01–12).

Kolejność prac w skrócie:

1. **Sprzęt i zasilanie** — M910q Tiny (i5-6400T, 2× DisplayPort), dwie
   domeny zasilania: A (always-on, bufor 4–6× SLA 5 Ah — Nano, BLE, przekaźniki)
   i B (za zapłonem — M910q, hub USB, wyświetlacze). Szczegóły: §1–§2
   X86_PLATFORM_SETUP.md, `01-bom.html`, `02-assembly.html`.
2. **OS** — Debian 13 (Trixie) netinst, minimalny (tylko SSH + standard
   utils), non-free-firmware włączone (`firmware-mediatek` dla WiFi/BT
   MT7921). §3, `03-os-install.html`.
3. **Pakiety systemowe** — python3-venv, Xorg + chromium (kiosk),
   intel-media-va-driver (VAAPI), pipewire, bluez, hostapd/dnsmasq,
   acpid, zram-tools. §4.
4. **Instalacja BCM do /opt/bcm:**

   ```bash
   cd /opt
   sudo git clone https://github.com/geek95dg/Alfa156-headunit.git bcm
   sudo chown -R $USER:$USER /opt/bcm
   cd /opt/bcm
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt -r requirements-x86.txt
   sudo usermod -aG dialout $USER   # porty szeregowe Arduino
   ```

   Test ręczny: `python3 main.py --platform x86 --config config/bcm_config.yaml --frontend`
   → http://localhost:5002 musi zwrócić dashboard.

   > **Skrót:** po instalacji OS można zamiast §4–§10 uruchomić
   > `sudo bash config/scripts/setup-x86.sh` (idempotentny; najpierw
   > edytuj sekcję USER CONFIG na górze skryptu).

5. **Usługi systemd** — aktualne pliki są w `config/systemd/`:

   ```bash
   cd /opt/bcm
   sudo cp config/systemd/bcm-headunit-x86.service /etc/systemd/system/bcm-headunit.service
   sudo cp config/systemd/bcm-ignition-watcher.service /etc/systemd/system/
   sudo cp config/systemd/bcm-splash-main.service /etc/systemd/system/
   sudo cp config/systemd/bcm-splash-small.service /etc/systemd/system/
   sudo cp config/systemd/bcm-resume.service /etc/systemd/system/
   sudo systemctl mask bcm-kiosk.service     # kiosk startuje z xinitrc, nie z systemd
   sudo systemctl daemon-reload
   sudo systemctl enable bcm-ignition-watcher bcm-splash-main bcm-splash-small bcm-resume
   ```

   **WAŻNE — cykl życia usług:**
   - `enable` dostaje **TYLKO** `bcm-ignition-watcher` (plus usługi
     splash/resume). `bcm-headunit` NIE jest enable'owany — startuje
     i zatrzymuje go watcher w reakcji na zapłon (`PartOf=`).
   - `bcm-headunit(-x86).service` ma `Restart=on-failure` — po crashu
     wstaje sam (RestartSec=3, limit 4 restartów / 120 s), ale czyste
     `systemctl stop` od watchera go nie wskrzesza.
   - Watcher ma dodatkowo **liveness-check**: cyklicznie sprawdza, czy
     BCM żyje i restartuje go, gdy padł — druga warstwa zabezpieczenia.
   - `bcm-headunit.service` (bez `-x86`) to wariant dla Orange Pi PC —
     na M910q kopiujesz `bcm-headunit-x86.service` pod nazwą
     `bcm-headunit.service`, jak wyżej.

6. **Boot + splash + kiosk** — GRUB wyciszony, splash wideo przez mpv/DRM,
   autologin na tty1 + `startx` z `config/scripts/xinitrc-x86-dual`
   (dwa ekrany: DP-1 główny, DP-2 mały). §7–§8, `09-display-touch.html`.
7. **Suspend/wake** — przycisk zasilania → S3 przez acpid
   (`bcm-power-toggle.sh`), logind ignoruje przycisk. §9,
   `10-power-suspend.html`.
8. **WiFi AP / Android Auto (opcjonalnie)** — P2P-GO na ch149 (MT7921)
   albo hostapd; openauto kompilowany ze źródeł. §10–§11,
   `08-wifi-bt.html`, `11-android-auto.html`.
9. **Weryfikacja** — checklista §13 / `12-verification.html`:

   ```bash
   sudo systemctl start bcm-ignition-watcher
   sudo journalctl -fu bcm-ignition-watcher -u bcm-headunit
   curl http://localhost:5002    # musi zwrócić HTML
   ```

---

## 3. Ścieżka C — stanowisko testowe Orange Pi PC

Tani bench-rig (Orange Pi PC 1.2, Armbian Trixie) do testów przed
zabudową w aucie. Pełna instrukcja, podzielona na samodzielne Party
(1–2 czysto software'owe, potem dongle USB, czujniki, przycisk zapłonu):
**[docs/OPI_PC_SETUP.md](OPI_PC_SETUP.md)**.

W skrócie: flash Armbiana → `/opt/bcm` + venv z
`requirements-opi-pc.txt` → `./run_opi_pc.sh` albo usługi systemd
(`bcm-headunit.service` — wariant opi_pc, config
`config/bcm_config_opi_pc.yaml`).

---

## 4. Arduino — trzy płytki

| Sketch | Płytka | Rola |
|--------|--------|------|
| `arduino/rotary_encoder` | **Pro Micro** (ATmega32U4), USB HID | Enkoder, przyciski, SWC (przyciski z kierownicy), panel muzyczny, jasność |
| `arduino/output_controller` | **Nano** #1 — **always-on** (domena A, zasilany z bufora bateryjnego) | Pilot szyb 433 MHz, otwieranie bagażnika bramkowane BLE (HM-10), PWM podświetlenia obu wyświetlaczy |
| `arduino/sensor_hub` | **Nano** #2 — **NOWY w v8.5.2** | Telemetria pojazdu: drzwi/maska/klapa, ręczny, zapłon, deszcz, temperatura DS18B20, opcjonalnie parkowanie/tempomat/immo/airbag |

**UWAGA (v8.5.2, rotary_encoder):** przycisk enkodera przeniesiony
z **D4 na D1** (na Pro Micro D4 i A6 to ten sam fizyczny pin —
kolidowało z SWC Pod 2). Przy starszym okablowaniu przepnij jeden
przewód z D4 na D1. Dodatkowo wszystkie trzy sketche mają 2-sekundowy
watchdog sprzętowy.

**sensor_hub — przełączniki funkcji:** na górze `sensor_hub.ino` każda
grupa wejść ma własny `#define FEATURE_*` (`FEATURE_DOORS`,
`FEATURE_HBRAKE`, `FEATURE_IGN`, `FEATURE_RAIN`, `FEATURE_TEMP`;
opcjonalne, domyślnie wyłączone: `FEATURE_PARK`, `FEATURE_CRUISE`,
`FEATURE_IMMO`, `FEATURE_AIRBAG`). Zakomentuj `#define`, aby usunąć
funkcję z firmware i zwolnić pin; po zmianie wgraj sketch ponownie.

### Kompilacja i wgrywanie (arduino-cli, profile przypięte w sketch.yaml)

```bash
# jednorazowo: instalacja narzędzia
curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh | sh
arduino-cli core update-index && arduino-cli core install arduino:avr

# kompilacja wszystkich trzech sketchy
make -C arduino

# wgrywanie (podaj właściwy port!)
make -C arduino rotary_encoder-upload    PORT=/dev/ttyACM0   # Pro Micro
make -C arduino output_controller-upload PORT=/dev/ttyUSB0   # Nano #1
make -C arduino sensor_hub-upload        PORT=/dev/ttyUSB1   # Nano #2
```

Okablowanie pin-po-pinie: **[docs/ARDUINO_SETUP_GUIDE.md](ARDUINO_SETUP_GUIDE.md)**
— §7 (Nano always-on) i **§7b (sensor hub)**. Szybki test sensor huba:
`picocom -b 115200 /dev/ttyUSB1` → linie `DOOR:...`, `IGN:0`, `TEMP:21.4`.

---

## 5. Przełączniki modułów (wszystkie)

Jedno źródło prawdy: `src/core/modules_catalog.py`. Każdy moduł/podsystem
włącza się i wyłącza na dwa sposoby:

- **UI:** Settings → Moduły (endpoint `/api/modules`),
- **YAML:** klucz `modules.<nazwa>` w `config/bcm_config.yaml`
  (`true`/`false`).

**Zmiany wymagają restartu BCM.** W obecnym `config/bcm_config.yaml`
wszystkie wpisy stoją na `true`; kolumna "domyślnie (katalog)" pokazuje,
co obowiązuje, gdyby klucz usunąć z YAML-a.

| Moduł | Opis | W bcm_config.yaml | Domyślnie (katalog) |
|-------|------|-------------------|---------------------|
| `dashboard` | Renderer pulpitu (frontend web / Pygame) | `true` | włączony |
| `obd` | Komunikacja OBD-II / K-Line z ECU | `true` | wyłączony |
| `parking` | Czujniki parkowania (HC-SR04) | `true` | wyłączony |
| `environment` | Monitoring temperatury i otoczenia | `true` | wyłączony |
| `audio` | System audio + PipeWire (głośność, EQ) | `true` | wyłączony |
| `input` | Kontrolery wejścia (pilot BT itd.) | `true` | wyłączony |
| `camera` | Kamery + wideorejestrator (kamera cofania) | `true` | wyłączony |
| `power` | Zarządzanie zasilaniem (shutdown/suspend) | `true` | wyłączony |
| `multimedia` | Android Auto / multimedia (openauto) | `true` | wyłączony |
| `location` | Pozycjonowanie GPS/GNSS | `true` | wyłączony |
| `tracking` | Rejestrator tras GPS (SQLite + eksport GPX) | `true` | wyłączony |
| `network` | Łączność LTE / modem komórkowy | `true` | wyłączony |
| `weather` | Dane pogodowe (OpenWeatherMap) | `true` | wyłączony |
| `rain_sensor` | Czujnik deszczu + automatyczne wycieraczki | `true` | wyłączony |
| `blinker_monitor` | Monitor kierunkowskazów (GPIO) | `true` | wyłączony |
| `central_lock` | Mostek do always-on Nano (pilot szyb + bagażnik BLE + PWM podświetlenia) | `true` | wyłączony |
| `lighting` | Oświetlenie: follow-me-home, mrugnięcie powitalne | `true` | wyłączony |
| `performance` | Pomiary osiągów (stoper 0–100, boost) | `true` | wyłączony |
| `alarm` | Alarm samochodowy (PIR, przechył, wstrząs, syrena) | `true` | wyłączony |
| `crash_detect` | Detekcja kolizji + ochrona nagrań DVR | `true` | wyłączony |
| `battery` | Monitor baterii buforowej (bufor SLA) | `true` | wyłączony |
| `bluetooth` | Bluetooth (BlueZ) — parowanie, A2DP/HFP, sterowanie mediami | `true` | włączony |
| `phonebook` | Synchronizacja książki telefonicznej PBAP + historia połączeń (ekran A8) | `true` | włączony (podąża za `bluetooth`, gdy brak własnego klucza) |
| `fuel_sender` | Kalibracja czujnika poziomu paliwa (ADC Arduino → %) | `true` | włączony |
| `wifi_ap` | WiFi dla Android Auto wireless (Wi-Fi Direct / P2P-GO, karta wewnętrzna) | `true` | wyłączony |
| `wifi_hotspot` | Dodatkowy Access Point ALFA-NET (współdzielenie internetu — **wymaga osobnego dongla WiFi**) | `false` | wyłączony |
| `route_planner` | Planowanie trasy / travel plan (OpenRouteService, TomTom) | `true` | włączony |
| `small_display` | Serwer małego wyświetlacza 4.3" (port 5003) | `true` | włączony |

Uwaga: honorowane są też starsze klucze (`bluetooth.enabled`,
`wifi.enabled`, `fuel_sender.enabled`, blok `modules_v85.*`), ale
`modules.<nazwa>` ma zawsze pierwszeństwo.

### WiFi — dwie niezależne funkcje

- **`wifi_ap`** = WiFi **tylko** do Android Auto wireless (tryb Wi-Fi
  Direct / P2P-GO na karcie wewnętrznej). To wystarcza, żeby telefon
  połączył się bezprzewodowo do AA. Domyślnie włączony.
- **`wifi_hotspot`** = dodatkowy Access Point **ALFA-NET** do
  współdzielenia internetu (np. z LTE) na inne urządzenia. Karta
  wewnętrzna **nie robi P2P-GO i AP jednocześnie**, więc ta funkcja
  wymaga **osobnego dongla USB WiFi**. Domyślnie wyłączony — włącz go
  (Settings → Moduły lub `modules.wifi_hotspot: true`) dopiero po
  podpięciu dongla.

### K-Line / OBD na x86 (produkcja)

Domyślnie x86 używa **symulatora ECU** (`obd.use_real_hardware: false`)
— wygodne do testów. Aby czytać z prawdziwego auta na M910q:

```yaml
obd:
  use_real_hardware: true
  fast_init: false
serial:
  kline:
    port_x86: /dev/ttyUSB_kline    # CP2102/VIAKEN KKL + reguła udev
```

Poznanie kodów PID (obroty, temperatury…) i pełna instrukcja podsłuchu:
**`docs/KLINE_SNIFFING.md`** + narzędzie `tools/kline_sniffer.py`.

---

## 6. Frontend — prekompilowany Tailwind CSS

Frontend **nie** używa runtime'owego `tailwind.js` — statyczny,
zminifikowany arkusz `src/dashboard/web/assets/vendor/tailwind.css`
(~37 KB) jest wygenerowany z góry i commitowany do repo.

Po **dodaniu nowych klas Tailwinda** w `src/dashboard/web/index.html`
lub `src/dashboard/web/js/**` trzeba przebudować arkusz:

```bash
./config/scripts/build-frontend.sh   # wymaga node/npm (npx pobierze tailwindcss@3)
```

Bez tego nowe klasy po prostu nie będą miały stylów.

---

## 7. Rozwiązywanie problemów

**Port 5002 zajęty** (`Address already in use`) — działa już inna
instancja BCM:

```bash
ss -tlnp | grep 5002        # albo: lsof -i :5002
pkill -f "main.py" || sudo systemctl stop bcm-headunit
```

**Brak `bluetoothctl` / błędy BlueZ** (typowe na maszynie deweloperskiej
bez Bluetootha) — wyłącz podsystem w `config/bcm_config.yaml`:

```yaml
modules:
  bluetooth: false
  phonebook: false
```

**Brak `gpiod` na x86** — to normalne: na x86 nie ma GPIO, całe I/O
pojazdu idzie przez Arduino po USB, a moduły GPIO działają w trybie
symulacji. Komunikat przy starcie można zignorować.

**Logi:**

```bash
tail -f logs/bcm.log                       # log aplikacji (ścieżka: system.log_file w YAML)
journalctl -u bcm-headunit -n 50           # produkcja: usługa BCM
journalctl -u bcm-ignition-watcher -n 50   # produkcja: watcher zapłonu
```

**BCM nie startuje po boocie (produkcja)** — sprawdź, czy enable'owany
jest `bcm-ignition-watcher` (to on startuje `bcm-headunit`), i zajrzyj
w `journalctl -u bcm-ignition-watcher`.

**Zepsuty venv** (`pip: command not found`):

```bash
rm -rf .venv && python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-x86.txt
```
