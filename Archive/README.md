# Archive — materiały dla platform innych niż Lenovo M910q

Ten katalog zawiera dokumentację, konfiguracje i skrypty dla **poprzednich
i pomocniczych platform sprzętowych** projektu BCM. Są tu trzymane wyłącznie
jako **materiał referencyjny i historyczny**.

> **Platformą produkcyjną jest Lenovo ThinkCentre M910q Tiny (x86).**
> Aktualna, obowiązująca dokumentacja wdrożeniowa:
> **[`docs/WDROZENIE_M910Q.md`](../docs/WDROZENIE_M910Q.md)**.

Nic z tego katalogu nie jest utrzymywane ani weryfikowane. Zawartość może
odwoływać się do nieaktualnych ścieżek, wersji BCM (v7 / v8) i numerów pinów,
które na M910q nie obowiązują.

---

## Co tu jest i dlaczego

### `orange-pi-5/` — Orange Pi 5 Pro / 5 Plus (poprzednia platforma docelowa)

Do wersji v8.5 platformą docelową był **Orange Pi 5 Pro 4 GB** (RK3588S),
a wcześniej **Orange Pi 5 Plus** (RK3588, 16 GB). Projekt przeszedł na x86,
bo M910q daje pełne VAAPI, natywne S3, dwa wyjścia DisplayPort i stabilne
sterowniki bez łatanych jąder Armbiana.

| Plik | Opis |
|------|------|
| `OPI5PRO_SETUP.md` | Instrukcja instalacji na OPi 5 Pro 4 GB — była to główna platforma produkcyjna |
| `OPI5PRO_BOM.md` | Lista części dla wariantu OPi 5 Pro |
| `OPI5PLUS_INSTALL.md` | Starsza instrukcja dla OPi 5 Plus (RK3588, 16 GB) |
| `requirements-opi.txt` | Zależności Pythona specyficzne dla RK3588 (GPIO, sterowniki) |
| `schematics-v7/` | Komplet schematów elektrycznych BCM **v7** — patrz niżej |

#### `schematics-v7/` — schematy dla Orange Pi

Cały zestaw schematów v7 zakłada, że I/O pojazdu wisi bezpośrednio na
**40-pinowym złączu GPIO Orange Pi**. Na M910q GPIO **nie istnieje** — całe
I/O pojazdu idzie przez trzy płytki Arduino po USB, a zasilanie jest zupełnie
inne (bufor SLA + step-up do 19/20 V zamiast LM2596 12 V → 5,1 V).

| Plik | Dlaczego zarchiwizowany |
|------|-------------------------|
| `README.md` | Instrukcja montażu v7 z numerami pinów GPIO OPi 5 Plus |
| `power_supply.svg` | LM2596 12 V → 5,1 V dla OPi — na M910q obowiązuje `schematics/power_buffered_m910q.svg` |
| `gpio_pinout.svg` | Mapa 40-pinowego złącza OPi — na M910q bez zastosowania |
| `main_wiring.svg` | Przegląd okablowania z OPi 5 Plus / RK3588 w centrum |
| `vehicle_layout.svg` | Prowadzenie kabli przy zabudowie OPi |
| `kline_circuit.svg` | L9637D wpięty w UART GPIO OPi (piny 8/10) — na M910q przez CP2102 po USB |
| `optoisolators.svg` | PC817 → GPIO OPi — na M910q PC817 → wejścia Arduino |
| `parking_sensors.svg` | HC-SR04 → GPIO OPi — na M910q → Arduino sensor hub |
| `backlight_mosfet.svg` | PWM z GPIO OPi (piny 32/33) — na M910q PWM z Arduino Nano #1 |

**Schematy nadal aktualne** zostały w `schematics/` w katalogu głównym
(m.in. `audio_system.svg` — tor audio USB DAC → wzmacniacze jest niezależny
od platformy).

---

### `orange-pi-pc/` — Orange Pi PC 1.2 (stanowisko testowe / bench rig)

Tani rig na **Allwinner H3 / armv7l** pod Armbianem Trixie, używany do
sanity-checków przed zabudową w aucie. Zbędny, odkąd cały stack stoi na
M910q i można go testować bezpośrednio na docelowym sprzęcie.

| Plik | Opis |
|------|------|
| `OPI_PC_SETUP.md` | Instrukcja stanowiska testowego, podzielona na samodzielne Party |
| `OPI_PC_BOM.md` | Lista części bench-riga |
| `requirements-opi-pc.txt` | Zależności Pythona dla armv7l |
| `run_opi_pc.sh` | Launcher deweloperski dla OPi PC |
| `bcm_config_opi_pc.yaml` | Konfiguracja BCM dla stanowiska (GPIO/serial H3) |
| `bcm-headunit-opi-pc.service` | Jednostka systemd wariantu opi_pc (dawniej `config/systemd/bcm-headunit.service`) |

> **Uwaga o nazewnictwie:** plik `bcm-headunit.service` w `config/systemd/`
> był wariantem **OPi PC**, mimo neutralnej nazwy. Na M910q i tak kopiuje się
> `bcm-headunit-x86.service` *pod nazwą* `bcm-headunit.service`, więc przy
> archiwizacji dostał jednoznaczną nazwę `bcm-headunit-opi-pc.service`.

Kod nadal obsługuje `--platform opi_pc`. `src/core/config.py` szuka
`bcm_config_opi_pc.yaml` najpierw w `config/`, a potem w tym katalogu — więc
zarchiwizowany rig da się uruchomić bez przywracania plików.

---

### `vm-smoke-tests/` — testy dymne na maszynie wirtualnej

Uruchamianie całego stacku na **VMware Workstation** (gość Ubuntu 24.04 /
Debian 12) w celu szybkiego sprawdzenia frontendu i logiki bez sprzętu.

| Plik | Opis |
|------|------|
| `VMWARE_SETUP.md` | Konfiguracja VM-ki (BCM v7): CPU, RAM, 3D, USB passthrough |
| `VM_USAGE_GUIDE.md` | Jak uruchamiać i nawigować BCM wewnątrz VM (BCM v8) |

**Zastąpione przez:** `./run_x86.sh` na dowolnym Linuksie — ta sama ścieżka
symulacji bez narzutu VM-ki. Opisane w
[`docs/URUCHOMIENIE.md`](../docs/URUCHOMIENIE.md) § 1.

---

## Czego tu nie ma

- **Ubuntu Touch / Halium / UBports** — w repozytorium **nigdy nie było**
  materiałów o próbach uruchomienia na Ubuntu Touch. Przeszukano bieżące
  drzewo i całą historię gita: zero trafień. Jeśli takie próby były
  dokumentowane, żyją poza tym repozytorium.
- **Kod platformowy w `src/`** — `main.py` i `src/core/hal.py` nadal
  obsługują `--platform opi` i `--platform opi_pc`. To ścieżki runtime'owe,
  a nie dokumentacja; przeniesienie ich zepsułoby aplikację, więc zostały
  nietknięte.
- **`legacy/`** (katalog główny) — nieużywane ekrany Pygame. To dług
  techniczny niezwiązany z platformą, więc zostaje tam, gdzie był.

---

## Przywrócenie pliku z archiwum

Historia gita jest zachowana (pliki przeniesiono przez `git mv`), więc pełny
log każdego dokumentu jest dostępny:

```bash
git log --follow Archive/orange-pi-5/OPI5PRO_SETUP.md
git mv Archive/orange-pi-5/OPI5PRO_SETUP.md docs/    # przywrócenie
```
