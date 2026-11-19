# Auto testowe — wdrożenie zmian #126–#129 krok po kroku

Instrukcja „co, gdzie, czym” dla właściciela auta testowego: Lenovo M910q
z Debianem 13 **bez zasilania buforowanego** (każde zgaszenie silnika to
twarde odcięcie prądu komputera i USB telefonu w aucie), Android Auto
bezprzewodowo z **głównego telefonu** (on też obsługuje rozmowy przez
Bluetooth) i **telefon w aucie** (Redmi Note 8 Pro z crDroid 13, na USB
pod podsufitką).

Jak czytać tę instrukcję:

- polecenia wpisujesz **na M910q** (SSH albo klawiatura), w katalogu
  repozytorium `/opt/bcm`, chyba że opis mówi inaczej;
- każde polecenie jest w osobnym bloku — kopiuj blok w całości;
  wartości przykładowe (`<…>`, `+48XXXXXXXXX`, `AA:BB:…`) podmień na własne;
- polecenia z `sudo` wymagają uprawnień roota — także `journalctl`
  (użytkownik kiosku nie widzi dziennika systemowego);
- „Ustawienia → X” = ekran Ustawień BCM w aucie, wiersz albo karta „X”;
- **NIESPRAWDZONE** = opisane według kodu i dokumentacji, jeszcze nie
  sprawdzone na sprzęcie w aucie.

Przygotowanie samego telefonu w aucie (ROM, Termux, agent, 112, postój,
kabina): [`PRZYGOTOWANIE_TELEFONU.md`](PRZYGOTOWANIE_TELEFONU.md).
Szczegóły techniczne każdej funkcji: [`WDROZENIE_TESTOWE.md`](WDROZENIE_TESTOWE.md)
§5.6–§5.14.

---

## Spis treści

1. [Co się zmieniło (#126–#129)](#1-co-się-zmieniło-126129)
2. [Ustawienia: baza, `local.yaml`, `bcm.env`](#2-ustawienia-baza-localyaml-bcmenv)
3. [Już wdrożyłem #126/#127/#128 — co teraz](#3-już-wdrożyłem-126127128--co-teraz)
4. [BIOS](#4-bios)
5. [Główny telefon: internet, GPS, uprawnienia](#5-główny-telefon-internet-gps-uprawnienia)
6. [Audio i mikrofon](#6-audio-i-mikrofon)
7. [Telefon w aucie](#7-telefon-w-aucie)
8. [Przełączniki modułów](#8-przełączniki-modułów)
9. [Sprawdź każdą funkcję](#9-sprawdź-każdą-funkcję)
10. [Gdy coś nie działa](#10-gdy-coś-nie-działa)
11. [Wycofanie zmian](#11-wycofanie-zmian)
12. [Czego nie sprawdzono na sprzęcie](#12-czego-nie-sprawdzono-na-sprzęcie)

---

## 1. Co się zmieniło (#126–#129)

Każda nowa funkcja ma własny przełącznik `modules.<nazwa>` (Ustawienia →
Moduły). W produkcyjnym `config/bcm_config.yaml` nic się nie zmienia —
nowe moduły są tam wyłączone; pełna tabela: §8.

**#126 — ustawienia i odporność na odcięcie prądu**

- Ustawienia w trzech warstwach (§2): baza `config/bcm_config_test.yaml`
  (BCM jej nie zmienia), zmiany z ekranu w `config/local.yaml`, sekrety
  w `/etc/bcm/bcm.env`. Przeniesienie starych ustawień z auta:
  `tools/migrate_local_config.py`.
- `config/scripts/bcm-harden.sh`: dziennik systemowy w RAM-ie, krótsze okno
  niezapisanych danych, `noatime`, `fsck.repair=yes` zamiast
  `fsck.mode=skip`, bez automatycznych aktualizacji, zegar z internetu
  (`bcm-timesync`).
- Log `logs/bcm.log` z rotacją (`system.log_max_mb`, `system.log_backups`).

**#127 — ekran, Android Auto, audio, internet i GPS z telefonu**

- Zegar w pasku tyka sam; **przeciągnięcie z górnej krawędzi w dół** = następny
  ekran (A1→A2→A3→A4); na Android Auto przewijanie i przeciąganie trafia do
  telefonu; obraz AA wraca po restarcie autoapp bez F5.
- Audio: backend Qt w autoapp (`multimedia.aa_audio_backend: qt` — koniec
  zawieszania i brzęczenia), wybór mikrofonu (`audio.mic_router`,
  `audio.mic_phone`), BCM widzi rozmowy z oFono (nakładka połączenia), bez
  mikrofonu przycisk głosu pokazuje „Brak mikrofonu – sterowanie głosowe
  wyłączone”. Diagnostyka: `tools/bcm-audio-diag.sh` (§6).
- Internet z głównego telefonu przez Bluetooth PAN: `modules.phone_tether`.
- GPS z telefonu (UDP albo TCP, §5): `modules.location`; trasy i GPX:
  `modules.tracking` (lista tras pod `/trips`).
- Dostęp z sieci: `dashboard.remote_access: tracking` w configu testowym —
  z sieci tylko trasy; ekran auta (loopback) zawsze ma pełny dostęp.

**#128 — telefon w pasku, telefon w aucie, stłuczka**

- Bateria, zasięg i operator głównego telefonu w pasku: `modules.phone_status`.
- Pogoda od pierwszej pozycji GPS, planer tras mówi „start: domyślny (brak
  GPS)”, wiersz GPS w Ustawieniach (§5.2).
- Klawiatura ekranowa mieści się na ekranie 1024×600.
- `/api/phone/dial` odrzuca numery alarmowe z sieci (403) — z ekranu auta
  działają.
- Ustawienia → Moduły: każdy dodatek z przełącznikiem, zależnościami
  i opisem sprzętu.
- Telefon w aucie na USB: `modules.car_phone` (internet, GPS, bateria,
  zegar), `modules.car_phone_hotspot`; autoapp tylko bezprzewodowo
  (`BCM_AA_USB=0`, §3.9).
- Czujniki telefonu: `modules.phone_sensors`; wykrywanie stłuczki:
  `modules.crash_detect`; agent w Termuxie: `modules.car_phone_agent`; SMS
  po stłuczce z odliczaniem: `modules.crash_sms`.
- Pomiar banku BATT przygotowany (`modules.battery`, wyłączony — wymaga
  bufora i Nano #2).

**#129 — 112, postój, kabina, jasność, ta instrukcja**

- Przygotowanie telefonu na crDroid 13 (`docs/WDROZENIE_TESTOWE.md` §5.7a
  i `docs/PRZYGOTOWANIE_TELEFONU.md`).
- „Zadzwoń 112” w oknie wypadku, zawsze ręcznie: `modules.call112`.
- Pozycja i alarm auta na postoju (działa w telefonie): `modules.parking_guard`.
- Czuwanie kabiny przednią kamerą telefonu: `modules.cabin_watch`.
- Automatyczna jasność ekranu: `modules.auto_brightness`.
- Wybudzanie BCM z telefonu (`modules.remote_session`) — tylko zapowiedź,
  „niedostępny w tej wersji”.

---

## 2. Ustawienia: baza, `local.yaml`, `bcm.env`

| Warstwa | Plik | Kto pisze | Co tam jest |
|---------|------|-----------|-------------|
| baza | `config/bcm_config_test.yaml` (w gicie) | nikt w aucie — tylko `git pull` | wszystkie klucze z wartościami dla auta testowego |
| nakładka | `config/local.yaml` (poza gitem, 0600) | BCM (zmiany z ekranu, zapis atomowy) i Ty | tylko różnice względem bazy; poprzednia dobra wersja w `config/local.yaml.bak` |
| sekrety | `/etc/bcm/bcm.env` (0600 root:root) | tylko Ty | klucze API, hasła, sekret agenta — nigdy w YAML-u |

Usługa `bcm-headunit` bierze bazę z linii `BCM_CONFIG` (domyślnie
`config/bcm_config_test.yaml`, można ją nadpisać w `/etc/bcm/bcm.env`),
nakłada `config/local.yaml` (inne położenie: `BCM_LOCAL_CONFIG`), a na
końcu sekrety ze środowiska. Wzór pliku sekretów z opisem każdej zmiennej:
`config/bcm.env.example`.

**Ręczna edycja `config/local.yaml` — tylko przy zatrzymanym BCM.** BCM
trzyma ustawienia w pamięci i przy następnym zapisie (zmiana na ekranie,
połączenie Bluetooth) nadpisuje plik swoją wersją — zmiana wpisana w trakcie
pracy BCM by zniknęła. Zatrzymaj BCM:

```bash
sudo systemctl stop bcm-ignition-watcher bcm-headunit
```

Edytuj (wcięcia spacjami, jak w bazie):

```bash
sudo nano /opt/bcm/config/local.yaml
```

Sprawdź składnię YAML (bez błędu = nic nie wypisze):

```bash
sudo /opt/bcm/.venv/bin/python -c "import yaml; yaml.safe_load(open('/opt/bcm/config/local.yaml'))"
```

(Venv może się nazywać `/opt/bcm/venv` — tak jak w unicie, który bierze
`.venv`, a gdy go nie ma, `venv`.) Uruchom BCM z powrotem:

```bash
sudo systemctl start bcm-ignition-watcher bcm-headunit
```

Uszkodzony `config/local.yaml` nie blokuje startu: BCM odkłada go jako
`local.yaml.broken-…`, bierze `config/local.yaml.bak`, a w ostateczności
samą bazę — i pisze o tym w logu (linia `Config:`, §9.1).

---

## 3. Już wdrożyłem #126/#127/#128 — co teraz

Jeśli auto ma już kod z #126–#128, ale nie przeszedłeś jeszcze tych kroków,
BCM może dalej startować ze starego `config/bcm_config_temp.yaml` — bez
klucza pogody, bez nowych funkcji (PAN, GPS, trasy, mikrofon, backend Qt
w autoapp). Zrób kroki po kolei; każdy jest bezpieczny do powtórzenia.

Repozytorium `/opt/bcm` należy do użytkownika kiosku (`setup-x86.sh`,
domyślnie `abner`): polecenia `git` wpisuj jako on (bez `sudo`), resztę
z `sudo`.

> **Prąd przez cały §3.** W aucie testowym nie ma bufora: przekręcenie
> kluczyka w trakcie kroku twardo odcina M910q. Najgroźniej w §3.7–§3.9
> (apt, `update-grub`, zmiana `/etc/fstab`, długa kompilacja autoapp) —
> przerwany `dpkg` potrafi zostawić system, który się nie uruchamia — ale
> też przy `git pull` (§3.4) i edycji `/etc/bcm/bcm.env` (§3.6). Dlatego:
>
> - §3.2–§3.10 zrób za jednym podejściem, **bez gaszenia silnika**:
>   silnik na chodzie na zewnątrz (nigdy w zamkniętym garażu) albo M910q
>   na stole z oryginalnego zasilacza Lenovo 20 V;
> - następne polecenie wpisuj dopiero, gdy poprzednie skończy się i wróci
>   znak zachęty.
>
> Prąd jednak zniknął w trakcie kroku — §3.11.

### 3.1 Z jakim configiem startuje usługa

```bash
systemctl cat bcm-headunit | grep -E 'BCM_CONFIG|--config|EnvironmentFile'
```

- `Environment=BCM_CONFIG=config/bcm_config_test.yaml` i
  `EnvironmentFile=-/etc/bcm/bcm.env` — unit jest już nowy (bcm-harden
  przeszedł). Zatrzymaj BCM (§3.2 — migracja przy działającym BCM by
  przepadła), sprawdź §3.3 i idź dalej od §3.4. Migrację (§3.5) zrób, jeśli
  stary plik z auta nigdy nie trafił do `config/local.yaml` **albo**
  `config/local.yaml` zaczyna się od linii `# base: bcm_config_temp.yaml`
  (§3.3) — taki plik BCM stosuje, ale nie zapisuje w nim zmian z ekranu.
- `--config config/bcm_config_temp.yaml` bez `EnvironmentFile` — stary unit;
  zrób wszystkie kroki.

### 3.2 Zatrzymaj BCM

Żeby nic nie zapisało ustawień w trakcie migracji:

```bash
sudo systemctl stop bcm-ignition-watcher bcm-headunit
```

### 3.3 Odzyskaj stare ustawienia z auta

Stary `config/bcm_config_temp.yaml` z auta (z kartą dźwiękową, ostatnim
telefonem BT i ustawieniami z ekranu) jest potrzebny jako źródło migracji.
Sprawdź, gdzie jest:

```bash
cd /opt/bcm && git status --short config/ && git stash list && ls -l config/local.yaml* 2>/dev/null
```

- ` M config/bcm_config_temp.yaml` — plik w katalogu to dalej wersja z auta.
  Skopiuj ją w bezpieczne miejsce (są w niej klucze, stąd `/root` i 0600)
  i przywróć wersję z gita, inaczej `git pull` odmówi:

  ```bash
  sudo install -m 600 /opt/bcm/config/bcm_config_temp.yaml /root/bcm_config_temp.yaml.device
  ```

  ```bash
  cd /opt/bcm && git checkout -- config/bcm_config_temp.yaml
  ```

- Masz kopię zrobioną przy wcześniejszym wdrożeniu — użyj jej (dalej
  jako `/root/bcm_config_temp.yaml.device`).
- `git stash list` pokazuje wpis — sprawdź, który zawiera ten plik
  (`stash@{0}` to najnowszy):

  ```bash
  cd /opt/bcm && git stash show --name-only 'stash@{0}'
  ```

  i wyciągnij go do `/root` (podmień `0` na właściwy numer):

  ```bash
  cd /opt/bcm && git show 'stash@{0}:config/bcm_config_temp.yaml' | sudo sh -c 'umask 077; cat > /root/bcm_config_temp.yaml.device'
  ```

- Nic z powyższych (plik z auta przepadł przy wcześniejszym `git pull`) —
  sprawdź, czy jest `config/local.yaml` i dla jakiej bazy go zapisano
  (pierwsze linie pliku):

  ```bash
  sudo head -n 3 /opt/bcm/config/local.yaml
  ```

  - „No such file” — nie ma czego migrować, §3.5 pomiń. Ustawienia
    z ekranu ustawisz od nowa (pary Bluetooth zostają w systemie, nie
    w YAML-u).
  - linia `# base: bcm_config_temp.yaml` — to zmiany z ekranu, które nowy
    BCM zapisał pod starym unitem (np. ostatni telefon BT). Przenieś je
    w §3.5, **wariant B** (źródłem jest plik z repo
    `config/bcm_config_temp.yaml` — to względem niego BCM liczył ten
    `local.yaml`). Bez migracji BCM po przejściu na
    `config/bcm_config_test.yaml` stosuje ten plik, ale nie zapisuje
    w nim nic nowego — zmiany z ekranu znikałyby po każdym zgaszeniu
    silnika.
  - linia `# base: bcm_config_test.yaml` — plik jest już dla nowej bazy,
    §3.5 pomiń.

Masz kopię z auta, a `config/local.yaml` też istnieje (linia
`# base: bcm_config_temp.yaml`)? Napisał go nowy BCM, który działał ze
starym unitem. Nie kasuj go — migracja niżej (wariant A z
`--merge-existing`) połączy go z kopią z auta.

### 3.4 Pobierz nową wersję

```bash
cd /opt/bcm && git pull --ff-only
```

### 3.5 Migracja ustawień do `config/local.yaml`

BCM musi być zatrzymany (§3.2) — inaczej przy pierwszym zapisie (zmiana na
ekranie, połączenie Bluetooth) nadpisze wynik swoją wersją z pamięci.

Najpierw podgląd — nic nie zapisuje, pokazuje grupy WRITE (trafi do
`local.yaml`), REVIEW (sprzętowe — sprawdź, czy pasują do auta), DROPPED
(sekrety, dane chwilowe i klucze, których kod już nie czyta; przy sekrecie
podaje nazwę zmiennej do `bcm.env`, nigdy wartość) i SKIPPED (baza celowo
to zmienia, np. włącza funkcję, której stary plik nie miał).

Narzędzie samo pomija stare wartości domyślne, które nowa baza celowo
zmienia — np. `modules.crash_detect: false` ze starego pliku trafia do
SKIPPED (w configu testowym wykrywanie stłuczki jest włączone), a stare
progi `crash_detection.speed_drop_threshold`, `g_force_threshold`
i `post_crash_record_sec` do DROPPED. Mimo to porównaj każde
`modules.…: false` w WRITE z kolumną „Test” tabeli w §8: czego świadomie
nie wyłączałeś, wyklucz z migracji, dopisując `--exclude modules.<nazwa>`
do podglądu i do zapisu. Wartość z SKIPPED zachowasz przez
`--keep-source <ścieżka>`.

**Wariant A — kopia z auta** (`/root/bcm_config_temp.yaml.device`, §3.3).
Podgląd:

```bash
cd /opt/bcm && sudo .venv/bin/python tools/migrate_local_config.py --source /root/bcm_config_temp.yaml.device --base config/bcm_config_test.yaml
```

Gdy plan jest dobry — zapis:

```bash
cd /opt/bcm && sudo .venv/bin/python tools/migrate_local_config.py --source /root/bcm_config_temp.yaml.device --base config/bcm_config_test.yaml --write
```

Gdy `config/local.yaml` już istnieje, podgląd to powie, a zapis odmówi.
Wtedy dopisz `--merge-existing` (wartości z istniejącego `local.yaml`
wygrywają — są nowsze niż kopia z auta) albo `--force` (nadpisanie,
stary plik zostaje jako `.bak`):

```bash
cd /opt/bcm && sudo .venv/bin/python tools/migrate_local_config.py --source /root/bcm_config_temp.yaml.device --base config/bcm_config_test.yaml --write --merge-existing
```

**Wariant B — bez kopii z auta, `config/local.yaml` z linią
`# base: bcm_config_temp.yaml`** (§3.3). Źródłem jest plik z repo, względem
którego BCM liczył ten `local.yaml`; `--merge-existing` zachowuje wszystko,
co BCM w nim zapisał (wygrywa nad plikiem z repo), i przepisuje nagłówek na
`# base: bcm_config_test.yaml`. Podgląd:

```bash
cd /opt/bcm && sudo .venv/bin/python tools/migrate_local_config.py --source config/bcm_config_temp.yaml --base config/bcm_config_test.yaml
```

Zapis:

```bash
cd /opt/bcm && sudo .venv/bin/python tools/migrate_local_config.py --source config/bcm_config_temp.yaml --base config/bcm_config_test.yaml --write --merge-existing
```

W REVIEW sprawdź `audio.sink` (karta USB) i `modules.blinker_monitor`.
Stary plik `config/local.yaml` zostaje jako `config/local.yaml.bak`.

Kod wyjścia 2 = „nic do migracji” (źródło niczym nie różni się od bazy) —
to nie błąd. Kopię `/root/bcm_config_temp.yaml.device` usuń dopiero, gdy
BCM po restarcie działa dobrze (są w niej stare klucze).

### 3.6 Sekrety: `/etc/bcm/bcm.env`

Plik nie istnieje? Załóż go ze wzoru (krok 2 `bcm-harden.sh` zrobi to samo).
Drugie polecenie niczego nie nadpisze — gdy plik już jest, nic nie robi:

```bash
sudo install -d -m 700 /etc/bcm
```

```bash
cd /opt/bcm && { sudo test -e /etc/bcm/bcm.env || sudo install -m 600 -o root -g root config/bcm.env.example /etc/bcm/bcm.env; }
```

Wpisz wartości: odkomentuj (usuń `#`) **tylko** linie kluczy, które
wypełniasz. `BCM_CONFIG` i `BCM_LOCAL_CONFIG` zostaw zakomentowane — to
wycofanie z §11; odkomentowane cofnęłyby BCM na stary plik configu:

```bash
sudo nano /etc/bcm/bcm.env
```

- **`BCM_OWM_API_KEY` — NOWY klucz OpenWeatherMap.** Stary klucz był
  w śledzonych YAML-ach i **zostaje w historii gita** — uznaj go za spalony: w
  https://home.openweathermap.org/api_keys wygeneruj nowy, a stary usuń.
- **`BCM_ORS_API_KEY`** — darmowy klucz OpenRouteService (konto na
  openrouteservice.org), dla planera tras.
- `BCM_TOMTOM_API_KEY` — opcjonalnie, utrudnienia na trasie.
- **`BCM_CAR_PHONE_AGENT_SECRET`** — sekret agenta w telefonie w aucie
  (dopiero gdy będziesz go uruchamiać, §7). Wygeneruj na M910q:

  ```bash
  python3 -c 'import secrets;print(secrets.token_hex(32))'
  ```

Jedna zmienna na linię, `NAZWA=wartość`, komentarz tylko w osobnej linii.
Prawa muszą zostać 600 root:root — sprawdzenie (ma wypisać `600 root:root`):

```bash
sudo stat -c '%a %U:%G' /etc/bcm/bcm.env
```

### 3.7 `bcm-harden.sh` — najpierw podgląd, potem naprawdę

Podgląd (niczego nie zmienia, pokazuje każdą zmianę i różnice fstab/GRUB):

```bash
cd /opt/bcm && sudo bash config/scripts/bcm-harden.sh --dry-run
```

Przeczytaj go. Ostrzeżenie „zainstalowany bcm-headunit.service startuje
z config/bcm_config_temp.yaml, a config/local.yaml jeszcze nie ma” znaczy,
że §3.5 nie zostało zrobione; „config/local.yaml jest zapisany dla starej
bazy (# base: bcm_config_temp.yaml)” — że brakuje wariantu B z §3.5. Potem
naprawdę:

```bash
cd /opt/bcm && sudo bash config/scripts/bcm-harden.sh
```

Skrypt podmienia unity BCM (od teraz `BCM_CONFIG` + `bcm.env`), robi kopie
`/etc/fstab` i `/etc/default/grub` (ścieżki w podsumowaniu) i przypomina
o BIOS-ie (§4). Pełny efekt po restarcie (§3.10).

### 3.8 `apply-fixes.sh`

Instaluje drop-in WirePlumbera i politykę D-Bus dla rozmów (oFono), `adb`
(telefon w aucie), `ddcutil` i `i2c-dev` (opcjonalne ściemnianie DDC/CI),
restartuje usługi audio użytkownika kiosku. Potrzebny internet (apt):

```bash
sudo bash /opt/bcm/config/scripts/apply-fixes.sh
```

### 3.9 autoapp tylko bezprzewodowo

Obowiązkowe przed podłączeniem telefonu w aucie na USB, zalecane zawsze:
autoapp bez łatki wysyła handshake Android Auto do każdego urządzenia USB.
Przebudowa z łatką (internet, kompilacja trwa długo):

```bash
cd /opt/bcm && sudo BCM_AA_USB=0 bash config/scripts/install-openauto.sh --force
```

### 3.10 Restart i pierwsze sprawdzenie

```bash
sudo reboot
```

Po starcie (szczegóły w §9.1):

```bash
sudo journalctl -u bcm-headunit -b | grep -E 'Config:|Local overlay|Secrets from environment'
```

Ma być `Config: …bcm_config_test.yaml`, `Local overlay: …local.yaml`
i `Secrets from environment:` z **nazwami** (nie wartościami) wpisanych
sekretów. Nie może być ostrzeżenia `Config: … saving is disabled …` —
wtedy `config/local.yaml` jest dalej dla starej bazy (§3.3, wariant B
w §3.5).

### 3.11 Prąd zniknął w trakcie kroku

Po ponownym starcie, po kolei:

0. BCM wstał sam razem z komputerem — zatrzymaj go jeszcze raz (§3.2),
   zanim wrócisz do migracji.
1. Dokończ przerwane instalacje pakietów:

   ```bash
   sudo dpkg --configure -a
   ```

   ```bash
   sudo apt-get -f install
   ```

2. Powtórz przerwany krok — skrypty są bezpieczne do powtórzenia; autoapp
   tym samym poleceniem co w §3.9 (z `BCM_AA_USB=0` i `--force`).
3. Sprawdź repozytorium (jako użytkownik kiosku, bez `sudo`):

   ```bash
   git -C /opt/bcm fsck
   ```

   Przy błędach pobierz brakujące obiekty i powtórz §3.4:

   ```bash
   git -C /opt/bcm fetch
   ```

   ```bash
   git -C /opt/bcm pull --ff-only
   ```

4. Sprawdź plik sekretów — ma być `600 root:root` i rozmiar większy niż
   0; pusty = wpisz sekrety jeszcze raz (§3.6):

   ```bash
   sudo stat -c '%a %U:%G %s' /etc/bcm/bcm.env
   ```

5. M910q nie startuje po przerwanym apt: w menu GRUB „Advanced options for
   Debian GNU/Linux” → wpis „(recovery mode)” → hasło roota → w powłoce
   `dpkg --configure -a`, potem `reboot` (gdy pisze o systemie plików
   tylko do odczytu: najpierw `mount -o remount,rw /`). Bez hasła roota
   (konto zablokowane przy instalacji z `sudo`) recovery mode nie wpuści —
   wtedy pendrive z Debianem live i `chroot` na dysk M910q. NIESPRAWDZONE
   na tym M910q.

---

## 4. BIOS

Wejście: **F1** przy starcie M910q.

| Ustawienie | Ścieżka | Wartość | Dlaczego |
|------------|---------|---------|----------|
| **After Power Loss** | Power | **Power On** | w aucie testowym każde przekręcenie kluczyka to powrót prądu — bez tego komputer się nie włączy |
| **Wake on USB** | Power | **Disabled** | M910q w S3 odcina zasilanie portów USB, więc nic na USB go nie obudzi; budzi przekaźnik na przycisku zasilania (Nano #2, wersja z buforem); zostają tylko fałszywe wybudzenia |
| **Wake on LAN** | Power (w BIOS-ach Lenovo zwykle w podmenu „Automatic Power On”; NIESPRAWDZONE na tej sztuce) | **Disabled** | port Ethernet nie jest używany, a S5 i tak nie gwarantuje wybudzenia |

Bez bufora komputer w ogóle nie śpi na postoju — prąd znika razem z
zapłonem — więc ustawienia wybudzania mają znaczenie dopiero po montażu
bufora (`docs/ZASILANIE_BUFOROWANE.md`).

---

## 5. Główny telefon: internet, GPS, uprawnienia

Główny telefon to Twój telefon z Android Auto. Jest zapasem dla telefonu
w aucie (internet i GPS) albo jedynym źródłem, dopóki Redmi nie jest
zamontowany.

### 5.1 Internet przez Bluetooth (`modules.phone_tether`)

1. W telefonie: Ustawienia → Sieć i internet → Hotspot i tethering →
   **Tethering przez Bluetooth: włączony** (nazwy różnią się między
   telefonami). Android potrafi go wyłączać po restarcie telefonu —
   sprawdź, gdy internet w aucie zniknie.
2. W szczegółach sparowanego urządzenia BCM (Bluetooth → ikona zębatki):
   **Kontakty i historia połączeń** włączone (książka telefoniczna
   w BCM) oraz — jeśli telefon to pokazuje — **dostęp do internetu**.
3. Ustawienia → „Internet z telefonu”: „połączono”, IP i interfejs
   (`bnep0`). „włącz tethering Bluetooth w telefonie” = punkt 1.

BCM bierze MAC z ostatnio połączonego telefonu; inny telefon na stałe:
`network.phone_tether.mac` w `config/local.yaml`. Profil NetworkManagera:
`bcm-phone-pan` (metryka 750; telefon w aucie na USB ma 650 — niższa
metryka wygrywa, więc gdy działają oba, ruch idzie przez USB).

### 5.2 GPS z głównego telefonu

Potrzebny tylko bez telefonu w aucie (Redmi podaje pozycję przez kabel
i ma pierwszeństwo — `hardware.gps.priority: [tcp, udp]`). Wiersz GPS
w Ustawieniach pokazuje źródło, stan i podpowiedź, gdzie wysyłać NMEA.

- **Wariant A — GPSd Forwarder (F-Droid), UDP:** adres = **IP `bnep0`
  headunitu** z wiersza „Internet z telefonu” (Ustawienia), port **10110**.
  **NIE** `10.0.0.1`: Wi-Fi Android Auto jest w telefonie siecią tylko dla
  AA, więc pakiety innych aplikacji do `10.0.0.1` idą danymi komórkowymi
  i przepadają. Interfejs PAN jest osiągalny dla wszystkich aplikacji.
  Wada: IP `bnep0` może się zmienić po ponownym połączeniu.
- **Wariant B — aplikacja „serwer NMEA TCP”, port 50000:** BCM sam znajduje
  telefon jako bramę PAN (`pan-gateway`) przy `hardware.gps.tcp.host: auto`
  — odporne na zmianę IP.

W obu: lokalizacja dla aplikacji **„Zezwalaj zawsze”**, dokładna;
bateria **bez ograniczeń**. BCM przyjmuje UDP tylko z `10.0.0.0/24`
i z PAN (`hardware.gps.udp.allowed_sources`) i nie ustawia zegara z NMEA.

### 5.3 Uprawnienia i zachowanie

- Rozmowy idą przez HFP (oFono) — telefon musi mieć włączone „Połączenia
  telefoniczne” dla BCM w szczegółach urządzenia Bluetooth.
- Bateria, zasięg i operator w pasku (`modules.phone_status`) — oFono nie
  zawsze podaje zasięg; pasek pokazuje wtedy samą baterię.
- Trasy z przeglądarki telefonu: `http://<IP bnep0>:5002/trips` (przy
  `dashboard.remote_access: tracking` z sieci działa tylko to).

---

## 6. Audio i mikrofon

### 6.1 Diagnostyka

Tylko odczyt (wersje, karty, graf PipeWire, domyślne źródło, `[Audio]`
z `openauto.ini`, oFono, dziennik):

```bash
sudo bash /opt/bcm/tools/bcm-audio-diag.sh --no-tests
```

Z testami rozstrzygającymi — każdy rusza dopiero po odpowiedzi `t`:

```bash
sudo bash /opt/bcm/tools/bcm-audio-diag.sh
```

Co czytać w wyniku:

| Sekcja | Dobrze | Źle |
|--------|--------|-----|
| 5. Domyślne źródło | `mikrofon: alsa_input…` albo `bcm_mic` (z redukcją echa) | `MONITOR wyjścia` — asystent słyszy muzykę auta; `bcm_null_mic` = brak mikrofonu (cisza, poprawne bez mikrofonu) |
| 6. openauto.ini | `backend audio autoapp: Qt` | `RtAudio — znany z pętli bufora` → `multimedia.aa_audio_backend: qt` (w configu testowym już jest) |
| 7. oFono | `jest modem z VoiceCallManager` | `brak modemu…` — telefon nie jest połączony przez HFP |
| 9. AEC | `jest libspa-aec-webrtc.so` | brak — `audio.mic_echo_cancel: auto` zostanie wyłączone |

### 6.2 Drzewo decyzji: skąd mikrofon

1. **Test A** (w trakcie brzęczenia wycisza na 5 s tylko autoapp):
   brzęczenie ucichło → pętla bufora autoapp — sprawdź sekcję 6 (backend Qt).
   Brzęczy dalej → źródło inne niż autoapp (karta, wzmacniacz, masa).
2. **Test B** (15 s nagrywania z wejścia karty USB przy grającej muzyce):
   - **czysto** → mikrofon do gniazda karty USB: 2-przewodowy mikrofon
     elektretowy do samochodowych zestawów głośnomówiących, wtyk 3,5 mm
     **TRS** (nie TRRS od słuchawek telefonu), na podsufitce przy lusterku,
     30–50 cm od ust, kabel z dala od zasilania wzmacniacza;
   - **muzyka się zacina / błędy USB w jądrze** → karta tylko na wyjście
     (`audio.mic_disable_unused_inputs: true`, domyślnie) i osobny mały
     **mikrofon USB**.
3. **Dongle Bluetooth** (USB, np. RTL8761BU — slot M.2 zajmuje MT7921)
   tylko wtedy, gdy **Test C** z `btmon` pokazuje błędy SCO albo rozmowa
   działa przy wyłączonym AA, a psuje się przy włączonym (radio MT7921
   dzielone z Wi-Fi AA).

### 6.3 Wpis `audio.mic_phone`

Nazwa węzła mikrofonu (`node.name`) z grafu PipeWire użytkownika kiosku
(`abner` — domyślny użytkownik z `setup-x86.sh`; jeśli inny, podmień):

```bash
U=abner; sudo -u "$U" XDG_RUNTIME_DIR=/run/user/$(id -u "$U") wpctl status --name
```

Szukaj w „Sources” wpisu `alsa_input.usb-…`. Do `config/local.yaml`
(BCM zatrzymany, §2) wpisz fragment tej nazwy — im dokładniej, tym lepiej
(samo `alsa_input.usb-` pasuje też do wejścia karty USB):

```yaml
audio:
  mic_phone: alsa_input.usb-C-Media_Electronics
  # mic_echo_cancel: auto   # przy echu u rozmówcy (§6.4)
```

### 6.4 Test asystenta i rozmowy, redukcja echa

- **Asystent AA:** przycisk głosu na kierownicy → asystent słyszy; po jego
  zamknięciu muzyka wraca bez brzęczenia. Mikrofon wybrany po starcie BCM
  działa od **następnej** sesji AA (autoapp wybiera mikrofon raz na sesję).
- **Rozmowa:** zadzwoń na główny telefon → nakładka połączenia (A8) →
  odbierz z ekranu albo kierownicy. Słyszysz rozmówcę? Rozmówca słyszy
  Ciebie? W logu BCM linia `Call audio: downlink … uplink …`.
- **Echo u rozmówcy** (słyszy siebie): `audio.mic_echo_cancel: auto`
  w `config/local.yaml` — działa tylko z `libspa-aec-webrtc.so` (sekcja 9
  diagnostyki); każdy błąd = surowy mikrofon i jeden błąd w logu.

---

## 7. Telefon w aucie

Redmi Note 8 Pro na USB daje internet (tethering USB, metryka 650 — przed
Bluetooth PAN), pozycję GPS, czujniki (stłuczka, jasność), zegar, a przez
agenta w Termuxie: SMS po stłuczce, „Zadzwoń 112” na głośniku, alarm na
postoju i czuwanie kabiny. **Całe przygotowanie telefonu krok po kroku:
[`PRZYGOTOWANIE_TELEFONU.md`](PRZYGOTOWANIE_TELEFONU.md).**

Kolejność po stronie BCM (wszystko domyślnie wyłączone):

1. autoapp bez USB (§3.9) i `adb` (§3.8);
2. Ustawienia → Moduły → `car_phone` (potem `phone_sensors`,
   `car_phone_agent`, …), restart BCM;
3. sekret agenta w `/etc/bcm/bcm.env` (§3.6) i parowanie
   (`PRZYGOTOWANIE_TELEFONU.md` §10);
4. funkcje bezpieczeństwa tylko w trybie testowym, dopóki nie przejdą
   sprawdzeń na stole: `crash_detection.sms.dry_run: true`,
   `safety.call112.test_mode: true`, `parking_guard.log_only: true`
   (tak jest w configu testowym).

Po wyłączeniu `modules.car_phone` usuń profil NetworkManagera — inaczej NM
dalej kieruje ruch przez każdy telefon z włączonym tetheringiem USB:

```bash
sudo nmcli connection delete bcm-car-phone
```

---

## 8. Przełączniki modułów

Ustawienia → Moduły (zapis w `config/local.yaml`; zmiana działa po
restarcie BCM). Moduł, którego zależności nie działają, nie startuje: BCM
loguje jedno ostrzeżenie, a Ustawienia proponują włączenie zależności.
„Produkcja” = `config/bcm_config.yaml`, „Test” = `config/bcm_config_test.yaml`
(z dawnymi kluczami jak `bluetooth.enabled`).

| Moduł | Co robi | Wymaga | Sprzęt | Produkcja | Test |
|-------|---------|--------|--------|-----------|------|
| `dashboard` | ekran BCM (kiosk, port 5002) | — | ekran + Chromium | wł. | wł. |
| `multimedia` | Android Auto (autoapp) | — | telefon z AA bezprzewodowym, MT7921 | wł. | wł. |
| `bluetooth` | Bluetooth: parowanie, A2DP/HFP, start AA | — | karta BT (MT7921) | wł. | wł. |
| `wifi_ap` | Wi-Fi Direct (P2P-GO) dla AA | — | karta MT7921 | wł. | wł. |
| `input` | przyciski SWC, linie z Arduino | — | Pro Micro (SWC) | wł. | wł. |
| `audio` | głośność, EQ, mikrofon | — | karta dźwiękowa | wł. | wł. |
| `network` | stan łącza LTE | — | modem LTE (opcjonalnie) | wył. | wł. |
| `phone_tether` | internet z głównego telefonu (Bluetooth PAN) | `bluetooth` | tethering przez Bluetooth w telefonie | wył. | wł. |
| `phonebook` | kontakty i historia połączeń (PBAP) | `bluetooth` | telefon przez BT | wył. | wł. |
| `phone_status` | bateria, zasięg, operator w pasku | `bluetooth` | telefon przez BT (oFono) | wył. | wł. |
| `weather` | pogoda (OpenWeatherMap) | — | internet, `BCM_OWM_API_KEY` | wł. | wł. |
| `route_planner` | planer tras (OpenRouteService) | — | internet, `BCM_ORS_API_KEY` | wł. | wł. |
| `location` | pozycja GPS (NMEA z telefonu) | — | telefon z aplikacją NMEA | wył. | wł. |
| `tracking` | zapis tras (SQLite) i GPX | — | pozycja z `location` | wył. | wł. |
| `crash_detect` | wykrywanie stłuczki, ochrona nagrań | `location` | GPS; pełne z `phone_sensors` | wył. | wł. |
| `car_phone` | telefon w aucie: internet USB, GPS, bateria, zegar | — | Redmi na USB (adb), autoapp z `BCM_AA_USB=0` | wył. | wył. |
| `car_phone_hotspot` | stan hotspotu telefonu w aucie | `car_phone` | hotspot w Redmi | wył. | wył. |
| `phone_sensors` | akcelerometr i światło z telefonu | `car_phone` | SensorServer, sztywny uchwyt | wył. | wył. |
| `car_phone_agent` | agent w Termuxie (SMS, 112, postój, kabina) | `car_phone` | Termux + `bcm_agent.py`, sekret w `bcm.env` | wył. | wył. |
| `crash_sms` | SMS do bliskich po stłuczce, z odliczaniem | `crash_detect`, `phone_sensors`, `car_phone_agent` | Redmi z kartą SIM | wył. | wył. |
| `call112` | „Zadzwoń 112” w oknie wypadku (ręcznie) | `crash_detect`; `car_phone_agent` lub `bluetooth` | Redmi z rootem albo główny telefon + mikrofon | wył. | wył. |
| `parking_guard` | pozycja i alarm na postoju (w telefonie) | `car_phone_agent` | Redmi z SIM, agent ≥ 1.2.0, kod TOTP | wył. | wył. |
| `cabin_watch` | zdjęcia kabiny przednią kamerą przy alarmie | `car_phone_agent`, `parking_guard` | Redmi z rootem, blokada „Brak”, agent ≥ 1.3.0 | wył. | wył. |
| `auto_brightness` | jasność ekranu z czujnika światła | `phone_sensors` lub `input` | czujnik w telefonie albo LDR Arduino | wył. | wył. |
| `battery` | pomiar banku buforowego (BATT) | — | bufor, Nano #2 z `FEATURE_BATT_*` | wył. | wył. |
| `remote_session` | wybudzanie BCM z telefonu — niedostępny w tej wersji | `input` | Nano #2 z `FEATURE_WAKE_*`, przekaźnik | wył. | wył. |
| `wifi_hotspot` | dodatkowy AP ALFA-NET — w aucie testowym musi zostać wyłączony (MT7921 obsługuje AA) | — | osobny dongiel Wi-Fi | wył. | wył. |

Pozostałe moduły (OBD, kamery, czujniki parkowania, Nano #1, alarm, ekran
pomocniczy) są wyłączone w obu configach — wymagają sprzętu, którego
w aucie testowym nie ma. Kalibracja BATT, gdy kiedyś będzie bufor:
`docs/ZASILANIE_BUFOROWANE.md` §13.4.

Wyłączenie modułu ręcznie (BCM zatrzymany, §2):

```yaml
modules:
  cabin_watch: false
```

---

## 9. Sprawdź każdą funkcję

### 9.1 System

```bash
systemctl cat bcm-headunit | grep -E 'BCM_CONFIG|EnvironmentFile'
```

```bash
sudo stat -c '%a %U:%G' /etc/bcm/bcm.env
```

```bash
sudo journalctl -u bcm-headunit -b | grep -E 'Config:|Local overlay|Secrets from environment'
```

Dziennik systemowy po `bcm-harden.sh` jest tylko w RAM-ie: `-b` pokazuje
bieżący start, wcześniejsze jazdy z niego znikają. Log BCM z poprzednich
jazd jest w `logs/bcm.log` (`system.log_file`; starsze w `bcm.log.1` …
`bcm.log.3`):

```bash
sudo tail -n 100 /opt/bcm/logs/bcm.log
```

```bash
findmnt -no OPTIONS /
```

(ma zawierać `noatime`)

```bash
cat /proc/cmdline
```

(ma być `fsck.repair=yes`, nie może być `fsck.mode=skip`)

```bash
systemctl list-timers bcm-timesync.timer
```

Po dniu jazdy w repozytorium nie może być zmienionych plików (BCM pisze
tylko do `config/local.yaml` i `data/`, poza gitem):

```bash
git -C /opt/bcm status --short
```

Moduły, które ruszyły, i te, które nie wystartowały (z powodem):

```bash
sudo journalctl -u bcm-headunit -b | grep -E 'ENABLED|NOT STARTED'
```

### 9.2 Ekran i Android Auto

- [ ] Zegar w pasku tyka bez dotykania ekranu.
- [ ] Przeciągnięcie z górnej krawędzi w dół zmienia ekran A1→A2→A3→A4→A1.
- [ ] Na AA przewijanie listy i przeciąganie mapy działa.
- [ ] Po „Restartuj AA” (ekran A2 albo Ustawienia) obraz AA wraca sam,
      bez odświeżania strony (F5).
- [ ] Awaria autoapp: BCM sam go podnosi. Ubij proces:

      ```bash
      sudo pkill -x autoapp
      ```

      W logu BCM `OpenAuto exited (code …) — restart 1/3 in 3s`; po
      ponownym połączeniu telefonu obraz AA na ekranie A2 wraca bez F5.
- [ ] Klawiatura ekranowa: widać wszystkie klawisze (także SPACJA i OK).

### 9.3 Audio

```bash
sudo grep -A3 '^\[Audio\]' /opt/bcm/openauto.ini
```

(ma być `OutputBackendType=1` = Qt; plik ma prawa 0600 root, bo trzyma
hasło Wi-Fi Direct — nie zmieniaj ich)

- [ ] Bez mikrofonu: przycisk głosu → powiadomienie „Brak mikrofonu –
      sterowanie głosowe wyłączone”, nic się nie zawiesza.
- [ ] Z mikrofonem: asystent słyszy; po nim muzyka bez brzęczenia (§6.4).
- [ ] Rozmowa przychodząca → nakładka, odbieranie z ekranu, obie strony
      się słyszą.

### 9.4 Internet, GPS, trasy, pogoda

```bash
nmcli connection show --active
```

(`bcm-phone-pan` — główny telefon; `bcm-car-phone` — telefon w aucie)

```bash
curl -sI https://www.google.com | head -n 1
```

```bash
curl -s http://127.0.0.1:5002/api/data | python3 -m json.tool | grep '"gps_'
```

- [ ] Ustawienia → „Internet z telefonu” / „Telefon w aucie”: „połączono”.
- [ ] Ustawienia → GPS: „jest pozycja”, źródło i nadawca.
- [ ] Ekran pogody: plakietka na mapie „GPS AKTYWNY” (nie „BRAK GPS”);
      planer tras nie pisze „start: domyślny (brak GPS)”.
- [ ] Trasy: `http://<IP bnep0>:5002/trips` w przeglądarce telefonu, GPX
      się pobiera.
- [ ] Ikony telefonu (bateria, zasięg) w pasku górnym.

### 9.5 Telefon w aucie i funkcje bezpieczeństwa

Wiersze w Ustawieniach i co mają pokazywać (opis telefonu:
`PRZYGOTOWANIE_TELEFONU.md` §15):

| Wiersz | Dobrze |
|--------|--------|
| „Telefon w aucie” | „połączono”, IP, bateria, °C, GPS |
| „Agent w telefonie” | „działa”, wersja, SIM, „112: gotowy (test)” przy `call112` |
| „SMS po stłuczce” | „tryb testowy (SMS nie wychodzą)”, liczba odbiorców, ostatni potwierdzony test |
| „Postój” | „rozbrojony” przy jeździe; z odłączonym kablem BCM nie widzi agenta — „telefon nie odpowiada”; po > 5 min bez kabla i ponownym podłączeniu (telefon właściciela bez Bluetooth): „uzbrojony — tylko log, bez SMS”, aż do dowodu właściciela |
| „Czuwanie kabiny” | „czeka na uzbrojenie postoju”, „kamera gotowa” |
| „Jasność ekranu” | „Auto (telefon) · … lx · …%” |

**„Zadzwoń 112” — test TYLKO numerem testowym, NIGDY prawdziwym 112.**
`safety.call112.test_mode: true` (config testowy) i numer zaufanej osoby
w `safety.call112.test_number` (`config/local.yaml`). Okno bez wypadku —
działa tylko w trybie testowym z numerem testowym (inaczej 409), najwyżej
raz na 10 s, bez SMS-a:

```bash
curl -s -X POST -H 'Content-Type: application/json' -d '{}' http://127.0.0.1:5002/api/crash/call112/test
```

Przycisk mówi „PRZYTRZYMAJ 2 s – TEST”. Sprawdź: za krótko albo zjechanie
palcem — nic; 2 s — dzwoni numer testowy; „PRZYTRZYMAJ 1 s – ROZŁĄCZ”;
obie drogi (telefon główny z mikrofonem i telefon w aucie); głośnik
w Redmi; ściszenie muzyki BCM. Reszta testu: `docs/WDROZENIE_TESTOWE.md`
§5.11. Prawdziwe 112 (`test_mode: false` w `config/local.yaml`) dopiero
po tych sprawdzeniach.

**Jasność:** zasłoń czujnik telefonu dłonią — po kilku sekundach ekran
ciemnieje. Log:

```bash
sudo journalctl -u bcm-headunit -b | grep -i brightness
```

---

## 10. Gdy coś nie działa

| Objaw | Przyczyna i co zrobić |
|-------|-----------------------|
| Brak pogody; w logu `WeatherManager started (api_key=not set)` | `BCM_OWM_API_KEY` w `/etc/bcm/bcm.env` (§3.6), restart BCM. Świeżo wygenerowany klucz OpenWeatherMap może zacząć działać dopiero po jakimś czasie (zależy od dostawcy). |
| W logu `Secrets from environment` bez nazwy klucza | Linia w `bcm.env` zakomentowana albo z komentarzem za wartością (komentarz tylko w osobnej linii). |
| Zmiany z ekranu znikają po restarcie (przy modułach: „nie zapisano w local.yaml — zmiana zniknie po restarcie”) | `config/local.yaml` zapisany dla innej bazy (linia `# base:` na początku pliku) — BCM go stosuje, ale nie nadpisuje; w logu `Config: … saving is disabled …`. BCM zatrzymany (§3.2), potem: migracja — z kopią z auta wariant A, bez niej wariant B (`--source config/bcm_config_temp.yaml … --write --merge-existing`, §3.5); nagłówek staje się `# base: bcm_config_test.yaml`. Tylko gdy migracja jest niemożliwa: usuń linię `# base:` w `config/local.yaml` (podpowiedź z logu) — przepadną wtedy wartości z ery temp, których nie było w nakładce (np. `audio.sink` wraca do `auto`, `blinker_monitor`, przycisk SWC mute, motyw). |
| Prąd zniknął w trakcie kroku z §3 | §3.11: `sudo dpkg --configure -a`, powtórz krok, `git -C /opt/bcm fsck`, rozmiar `/etc/bcm/bcm.env`. |
| Moduł „nie wystartuje — brak …” | Włącz wymienione moduły (Ustawienia proponują „Włącz z zależnościami”), restart BCM. |
| „włącz tethering Bluetooth w telefonie” | §5.1, punkt 1. |
| GPS: „brak pozycji” | Aplikacja NMEA działa? Adres `bnep0`, nie `10.0.0.1` (§5.2). Telefon w aucie: `PRZYGOTOWANIE_TELEFONU.md` §6. |
| Asystent AA słyszy muzykę / szum | `bcm-audio-diag.sh`, sekcja 5 (§6.1); `audio.mic_phone` (§6.3). |
| Rozmówca mnie nie słyszy | Mikrofon (§6.2); w oknie 112 „Dyspozytor może Cię nie słyszeć” — przycisk proponuje telefon w aucie. |
| Brzęczenie przy asystencie | Sekcja 6 diagnostyki: backend Qt; `multimedia.aa_audio_backend: qt`. |
| „autoapp przełącza telefon w tryb Android Auto” | §3.9, potem odłącz i podłącz telefon. |
| Telefon w aucie, agent, 112, postój, kabina | `PRZYGOTOWANIE_TELEFONU.md` §20. |
| BCM nie wstaje | `sudo journalctl -u bcm-headunit -b -n 100`; zły `config/local.yaml` BCM omija sam (§2); wycofanie: §11. |

---

## 11. Wycofanie zmian

**Stary plik configu jedną linią.** W `/etc/bcm/bcm.env` odkomentuj:

```bash
sudo nano /etc/bcm/bcm.env
```

linię `BCM_CONFIG=config/bcm_config_temp.yaml`. `config/local.yaml`
zapisany dla innej bazy jest wtedy stosowany, ale nie nadpisywany — żeby
zmiany z ekranu się zapisywały, wskaż osobny plik:
`BCM_LOCAL_CONFIG=/opt/bcm/config/local-temp.yaml`. Potem:

```bash
sudo systemctl restart bcm-ignition-watcher bcm-headunit
```

**Moduły.** Ustawienia → Moduły → wyłącz, restart BCM (albo wpis
`modules.<nazwa>: false` w `config/local.yaml`, §8). Po wyłączeniu
`car_phone`: `sudo nmcli connection delete bcm-car-phone` (§7). Wyłączenie
`auto_brightness` w Ustawieniach oddaje monitorowi pełną jasność.

**Audio.** Powrót do RtAudio w autoapp: `multimedia.aa_audio_backend: rtaudio`
w `config/local.yaml`. Bez routera mikrofonu: `audio.mic_router: false`.

**autoapp znowu z USB** (telefon w aucie wtedy nie działa):

```bash
cd /opt/bcm && sudo BCM_AA_USB=1 bash config/scripts/install-openauto.sh --force
```

**Dostęp z laptopa w sieci** (pełny, nie tylko trasy):
`dashboard.remote_access: full` w `config/local.yaml` — **tylko na chwilę,
z własnego laptopa**. Przy `full` każde urządzenie, które dosięgnie portu
5002 (Wi-Fi Android Auto, Bluetooth PAN, hotspot; `allowed_networks` wtedy
nie działa), bez hasła dostaje prawie wszystko: Ustawienia i przełączniki
modułów, hasła Wi-Fi, restart komputera, wpisywanie do Android Auto,
wybieranie numerów (poza alarmowymi). Tylko ekran auta zostaje przy 112,
SMS-ach po stłuczce, parowaniu agenta i Uzbrój/Rozbrój. Potem wróć do
`tracking` (BCM zatrzymany, §2).

**`bcm-harden.sh`.** Każdy punkt cofa się osobno — polecenia są w nagłówku
skryptu (sekcja „Cofnięcie”):

```bash
sed -n '/^# Cofnięcie/,/^# --dry-run/p' /opt/bcm/config/scripts/bcm-harden.sh
```

Kopie `/etc/fstab` i `/etc/default/grub` (z datą w nazwie) wypisuje
podsumowanie skryptu; przywrócenie: `sudo cp KOPIA ORYGINAŁ`, po GRUB-ie
`sudo update-grub`.

**Pełna deinstalacja BCM** — `config/scripts/cleanup-x86.sh` usuwa
wszystkie unity BCM, kiosk, autologin, konfigurację AP i venv (zostawia
`/etc/bcm/bcm.env`, fstab i GRUB). Tylko przed instalacją od zera.

---

## 12. Czego nie sprawdzono na sprzęcie

- przeciąganie w AA przez `xdotool` (czy autoapp mapuje ruch myszy na
  przeciągnięcie) i backend Qt w autoapp na tym M910q;
- stabilność rozmów (SCO) na MT7921 przy włączonym AA;
- dostępność IP `bnep0` dla GPSd Forwarder w Twoim telefonie;
- telefon w aucie na crDroid 13: `svc usb setFunctions`, SensorServer
  ≥ 100 Hz w tle, `termux-sms-send` ze stdin, phantom process killer,
  głośnik i stan rozmowy przy 112, `termux-sensor` i aparat przy wygaszonym
  ekranie, realne zużycie baterii na postoju
  (`PRZYGOTOWANIE_TELEFONU.md` — punkty NIESPRAWDZONE);
- progi wykrywania stłuczki, alarmu na postoju i kabiny w prawdziwym aucie;
- krzywa jasności i DDC/CI na ekranie zasilanym z USB;
- menu „Wake on LAN” w BIOS-ie tej sztuki M910q.
