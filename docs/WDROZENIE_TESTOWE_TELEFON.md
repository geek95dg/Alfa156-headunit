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

> **Od 23.11 auto jeździ na konfiguracji docelowej `config/bcm_config.yaml`**
> (wszystko, co działało w teście, plus Twoje ustawienia z `local.yaml`).
> Przejście krok po kroku, z poleceniami i wycofaniem:
> [§13](#13-przejście-na-konfigurację-docelową). Do czasu przejścia BCM
> stosuje Twój `config/local.yaml`, ale nie zapisuje w nim zmian z ekranu.

Przygotowanie samego telefonu w aucie (ROM, Termux, agent, 112, postój,
kabina): [`PRZYGOTOWANIE_TELEFONU.md`](PRZYGOTOWANIE_TELEFONU.md).
Szczegóły techniczne każdej funkcji: [`WDROZENIE_TESTOWE.md`](WDROZENIE_TESTOWE.md)
§5.6–§5.15.

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
13. [Przejście na konfigurację docelową](#13-przejście-na-konfigurację-docelową)

---

## 1. Co się zmieniło (#126–#129)

Każda nowa funkcja ma własny przełącznik `modules.<nazwa>` (Ustawienia →
Moduły). Domyślnie w kodzie każdy jest wyłączony; od 23.11 auto jeździ na
`config/bcm_config.yaml` (konfiguracja docelowa, §13) — co jest w niej
włączone, pokazuje kolumna „Docelowa” w §8.

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
- Wybudzanie BCM z telefonu i od drzwi (`modules.remote_session`) — kod
  gotowy, ale TYLKO dla wersji z buforem; w aucie testowym zostaje
  wyłączony (§7.1).

---

## 2. Ustawienia: baza, `local.yaml`, `bcm.env`

| Warstwa | Plik | Kto pisze | Co tam jest |
|---------|------|-----------|-------------|
| baza | `config/bcm_config.yaml` (w gicie; do 23.11 `config/bcm_config_test.yaml`) | nikt w aucie — tylko `git pull` | wszystkie klucze z wartościami dla auta |
| nakładka | `config/local.yaml` (poza gitem, 0600) | BCM (zmiany z ekranu, zapis atomowy) i Ty | tylko różnice względem bazy; poprzednia dobra wersja w `config/local.yaml.bak` |
| sekrety | `/etc/bcm/bcm.env` (0600 root:root) | tylko Ty | klucze API, hasła, sekret agenta — nigdy w YAML-u |

Usługa `bcm-headunit` bierze bazę z linii `BCM_CONFIG` (domyślnie
`config/bcm_config.yaml` — od 23.11, §13; wcześniej
`config/bcm_config_test.yaml`; można ją nadpisać w `/etc/bcm/bcm.env`),
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

> **Od 23.11 unity z repo startują z `config/bcm_config.yaml`.** Ten
> rozdział przenosi ustawienia ze starego pliku na konfigurację testową
> (`--base config/bcm_config_test.yaml`); zaraz po §3.5 zrób §13.2–§13.5
> (przejście na konfigurację docelową), a dopiero potem §3.6 i dalej —
> inaczej po restarcie (§3.10) BCM nie zapisze zmian z ekranu.

### 3.1 Z jakim configiem startuje usługa

```bash
systemctl cat bcm-headunit | grep -E 'BCM_CONFIG|--config|EnvironmentFile'
```

- `Environment=BCM_CONFIG=config/bcm_config.yaml` — unit jest już po
  przejściu na konfigurację docelową; jeśli `config/local.yaml` zaczyna się
  od `# base: bcm_config.yaml`, ten rozdział i §13 masz za sobą.
- `Environment=BCM_CONFIG=config/bcm_config_test.yaml` i
  `EnvironmentFile=-/etc/bcm/bcm.env` — unit jest już nowy (bcm-harden
  przeszedł), ale jeszcze na konfiguracji testowej (potem §13). Zatrzymaj BCM (§3.2 — migracja przy działającym BCM by
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
- **`BCM_ORS_API_KEY`** — darmowy klucz OpenRouteService, dla planera
  tras. Od 2026 usługę prowadzi HeiGIT: konto i klucze na
  account.heigit.org, BCM łączy się z `api.heigit.org` (stary adres
  `api.openrouteservice.org` odpowiada 410). Stary klucz działa dalej —
  jeśli test w „Internet i usługi” daje 401/403, skopiuj klucz z
  account.heigit.org jeszcze raz (bez spacji) i wpisz w `bcm.env`.
- `BCM_TOMTOM_API_KEY` — opcjonalnie, utrudnienia na trasie.
- **`BCM_CAR_PHONE_AGENT_SECRET`** — sekret agenta w telefonie w aucie
  (dopiero gdy będziesz go uruchamiać, §7). Wygeneruj na M910q:

  ```bash
  python3 -c 'import secrets;print(secrets.token_hex(32))'
  ```

Jedna zmienna na linię, `NAZWA=wartość`, komentarz tylko w osobnej linii.
Bez cudzysłowów i bez spacji wokół `=` (spacje i znak końca linii z Windows
BCM i tak obcina, ale systemd czyta plik po swojemu — trzymaj się wzoru):
`BCM_ORS_API_KEY=5b3c…`, nie `BCM_ORS_API_KEY = "5b3c…"`.
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

Ma być `Config: …bcm_config.yaml` (po §13; przed nim
`…bcm_config_test.yaml`), `Local overlay: …local.yaml`
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
bufora (`docs/ZASILANIE_BUFOROWANE.md`). Bufor dla tego auta to ten sam tor
co w wersji docelowej — zalewany step-up 20 V, dwie ładowarki XY-SK120,
bank 7 × HR1221W w dwóch koszach w bagażniku; opis i zakupy:
`docs/WDROZENIE_TESTOWE.md` §3 i `docs/LISTA_ZAKUPOWA.md`. Do czasu montażu
wszystko w tej instrukcji zakłada auto **bez** bufora.

---

## 5. Główny telefon: internet, GPS, uprawnienia

Główny telefon to Twój telefon z Android Auto. Jest zapasem dla telefonu
w aucie (internet i GPS) albo jedynym źródłem, dopóki Redmi nie jest
zamontowany.

> **Konfiguracja docelowa:** w `config/bcm_config.yaml` (decyzja 23.11)
> `modules.phone_tether` jest **wyłączony** — Redmi daje internet po USB.
> Wszystko z tego rozdziału działa dopiero po włączeniu Ustawienia →
> Moduły → `phone_tether` i restarcie BCM.

> Bez tego nie ma `bnep0`, profilu `bcm-phone-pan`, GPSd Forwarder /
> `pan-gateway` (§5.2) ani `/trips` po PAN (§5.3). Bez PAN telefon kierowcy nie ma
> sprawdzonej drogi do `/trips` (Wi-Fi Android Auto nie przepuszcza ruchu
> innych aplikacji do `10.0.0.1`, §5.2) — pobieranie GPX z telefonu
> kierowcy wymaga `phone_tether`.

### 5.1 Internet przez Bluetooth (`modules.phone_tether`)

Tylko z włączonym `modules.phone_tether` (w konfiguracji docelowej
wyłączony — zob. wyżej).

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

W `config/bcm_config.yaml` (konfiguracja docelowa, §13) moduły `car_phone`,
`car_phone_hotspot`, `phone_sensors` i `car_phone_agent` są już włączone —
wyłączone są tylko w kodzie i w `config/bcm_config_test.yaml` (tam włączasz
je na ekranie Ustawień i restartujesz BCM). Po stronie BCM zostaje:

1. autoapp bez USB: `sudo BCM_AA_USB=0 bash config/scripts/install-openauto.sh --force`
   (§3.9) i `adb` (§3.8);
2. sekret agenta `BCM_CAR_PHONE_AGENT_SECRET` w `/etc/bcm/bcm.env` (§3.6)
   i parowanie (`PRZYGOTOWANIE_TELEFONU.md` §10);
3. funkcje bezpieczeństwa tylko w trybie testowym, dopóki nie przejdą
   sprawdzeń na stole: `crash_detection.sms.dry_run: true`,
   `safety.call112.test_mode: true`, `parking_guard.log_only: true`
   (tak jest w `config/bcm_config.yaml` i w configu testowym).

Po wyłączeniu `modules.car_phone` usuń profil NetworkManagera — inaczej NM
dalej kieruje ruch przez każdy telefon z włączonym tetheringiem USB:

```bash
sudo nmcli connection delete bcm-car-phone
```

### 7.1 Wybudzanie (wersja z buforem)

**W aucie testowym nic tu nie włączaj.** Bez bufora komputer na postoju nie
śpi, tylko traci prąd razem z zapłonem — nie ma czego budzić.
`modules.remote_session` zostaje `false` (tak jest w obu configach).

W wersji z buforem komputer śpi w S3, a budzi go Nano #2 przyciskiem
zasilania: po otwarciu drzwi kierowcy (nie przy wysiadaniu — pierwsze
otwarcie po jeździe nie budzi — i najwcześniej 2 min po zgaszeniu zapłonu), po kodzie podczerwieni z telefonu w aucie (SMS `WAKE <kod>` albo
skrót Termux:Widget `tools/car_phone/termux/wake.sh` — instalacja skrótu
w `ZASILANIE_BUFOROWANE.md` §14.6) albo po impulsie na
wejściu EXT — najwyżej 3 razy na godzinę i 6 na dobę. Po pobudce BCM pokazuje
baner „Wybudzono: … — uśpienie za mm:ss [Nie usypiaj 30 min] [Uśpij teraz]”,
a po dzierżawie (drzwi 5 min, telefon 10 min) Nano usypia komputer z
powrotem. Stan i odmowy: Ustawienia, wiersz „Wybudzanie”.

Całość — okablowanie odbiornika IR (TSOP na A3, filtr 100 Ω / 4,7 µF),
transoptora na A2, flagi firmware, protokół, BIOS i kolejność sprawdzeń na
stole: [`ZASILANIE_BUFOROWANE.md`](ZASILANIE_BUFOROWANE.md) §14. Czy
telefon ma działający nadajnik IR, sprawdzisz już teraz
(`PRZYGOTOWANIE_TELEFONU.md` §15):

```bash
termux-infrared-frequencies
```

---

## 8. Przełączniki modułów

Ustawienia → Moduły (zapis w `config/local.yaml`; zmiana działa po
restarcie BCM). Moduł, którego zależności nie działają, nie startuje: BCM
loguje jedno ostrzeżenie, a Ustawienia proponują włączenie zależności.
„Docelowa” = `config/bcm_config.yaml` — konfiguracja, z którą auto jeździ od
23.11 (§13), „Test” = `config/bcm_config_test.yaml` — konfiguracja
stanowiskowa, na której auto jeździło wcześniej (przełączniki z okresu
testów).

| Moduł | Co robi | Wymaga | Sprzęt | Docelowa | Test |
|-------|---------|--------|--------|----------|------|
| `dashboard` | ekran BCM (kiosk, port 5002) | — | ekran + Chromium | wł. | wł. |
| `multimedia` | Android Auto (autoapp) | — | telefon z AA bezprzewodowym, MT7921 | wł. | wł. |
| `bluetooth` | Bluetooth: parowanie, A2DP/HFP, start AA | — | karta BT (MT7921) | wł. | wł. |
| `wifi_ap` | Wi-Fi Direct (P2P-GO) dla AA | — | karta MT7921 | wł. | wł. |
| `input` | przyciski SWC, linie z Arduino | — | Pro Micro (SWC) | wł. | wł. |
| `audio` | głośność, EQ, mikrofon | — | karta dźwiękowa | wł. | wł. |
| `network` | stan łącza LTE | — | modem LTE (opcjonalnie) | wył. | wł. |
| `phone_tether` | internet z głównego telefonu (Bluetooth PAN) | `bluetooth` | tethering przez Bluetooth w telefonie | wył. | wł. |
| `phonebook` | kontakty i historia połączeń (PBAP) | `bluetooth` | telefon przez BT | wł. | wł. |
| `phone_status` | bateria, zasięg, operator w pasku | `bluetooth` | telefon przez BT (oFono) | wł. | wł. |
| `weather` | pogoda (OpenWeatherMap) | — | internet, `BCM_OWM_API_KEY` | wł. | wł. |
| `weather_alerts` | ostrzeżenia pogodowe: oblodzenie, śnieg, ulewa, burza, wiatr, mgła (§9.7) | `weather` | internet, `BCM_OWM_API_KEY`; GPS dla prognozy w miejscu auta | wł. | wł. |
| `route_planner` | planer tras (OpenRouteService) | — | internet, `BCM_ORS_API_KEY` | wł. | wł. |
| `trip_gps` | komputer podróży z GPS na ekranie trasy: dystans, czas, średnia prędkość (§9.6) | `location` | GPS z telefonu albo odbiornika | wł. | wł. |
| `traffic_alerts` | utrudnienia TomTom w trakcie jazdy: korki, wypadki, zamknięcia przed autem albo na trasie (§9.8) | `location` | internet, `BCM_TOMTOM_API_KEY`; GPS z kursem; cel na ekranie trasy dla korytarza wzdłuż trasy | wł. | wł. |
| `voice_announce` | komunikaty głosowe: ostrzeżenia pogodowe i utrudnienia czytane po polsku (Piper, zapasowo espeak-ng), muzyka ściszana na czas komunikatu (§9.9) | `audio` | Piper z głosem `pl_PL-gosia-medium` albo espeak-ng (`apply-fixes.sh`), PipeWire w sesji użytkownika | wł. | wł. |
| `net_diag` | sonda internetu w `car_phone`/`phone_tether` i wiersz „Internet i usługi” z testem kluczy (§10.1) | — | klucze w `bcm.env` | wł. | wł. |
| `location` | pozycja GPS (NMEA z telefonu) | — | telefon z aplikacją NMEA | wł. | wł. |
| `tracking` | zapis tras (SQLite) i GPX | — | pozycja z `location` | wł. | wł. |
| `fuel_log` | dziennik tankowań: spalanie od pełna do pełna, koszt, zasięg (§9.6) | `tracking` | nic — wpis na ekranie trasy | wł. | wł. |
| `last_park` | ostatni postój: gdzie auto ostatnio stało — wiersz w Ustawieniach i link do mapy na `/trips` ([TRACCAR_SERWER.md](TRACCAR_SERWER.md) §8.5) | `location` | GPS | wł. | wył. |
| `crash_detect` | wykrywanie stłuczki, ochrona nagrań | `location` | GPS; pełne z `phone_sensors` | wył. | wł. |
| `car_phone` | telefon w aucie: internet USB, GPS, bateria, zegar | — | Redmi na USB (adb), autoapp z `BCM_AA_USB=0` | wł. | wył. |
| `car_phone_hotspot` | stan hotspotu telefonu w aucie | `car_phone` | hotspot w Redmi | wł. | wył. |
| `phone_sensors` | akcelerometr i światło z telefonu | `car_phone` | SensorServer, sztywny uchwyt | wł. | wył. |
| `car_phone_agent` | agent w Termuxie (SMS, 112, postój, kabina) | `car_phone` | Termux + `bcm_agent.py`, sekret w `bcm.env` | wł. | wył. |
| `crash_sms` | SMS do bliskich po stłuczce, z odliczaniem | `crash_detect`, `phone_sensors`, `car_phone_agent` | Redmi z kartą SIM | wył. | wył. |
| `call112` | „Zadzwoń 112” w oknie wypadku (ręcznie) | `crash_detect`; `car_phone_agent` lub `bluetooth` | Redmi z rootem albo główny telefon + mikrofon | wył. | wył. |
| `parking_guard` | pozycja i alarm na postoju (w telefonie) | `car_phone_agent` | Redmi z SIM, agent ≥ 1.2.0, kod TOTP; rozbrajanie telefonem właściciela tylko z `bluetooth` (HFP) | wył. | wył. |
| `cabin_watch` | zdjęcia kabiny przednią kamerą przy alarmie | `car_phone_agent`, `parking_guard` | Redmi z rootem, blokada „Brak”, agent ≥ 1.3.0 | wył. | wył. |
| `traccar` | pozycja auta na Twoim serwerze Traccar (wysyła telefon, także na postoju) | `car_phone_agent` | serwer Traccar ([TRACCAR_SERWER.md](TRACCAR_SERWER.md)), `traccar.url`, `BCM_TRACCAR_DEVICE_ID`, agent ≥ 1.6.0 | wł. | wył. |
| `auto_brightness` | jasność ekranu z czujnika światła | `phone_sensors` lub `input` | czujnik w telefonie albo LDR Arduino | wł. | wył. |
| `battery` | pomiar banku buforowego (BATT) | — | bufor, Nano #2 z `FEATURE_BATT_*` | wył. | wył. |
| `remote_session` | sesja po wybudzeniu od drzwi albo z telefonu (IR) — tylko wersja z buforem (§7.1) | `input` | Nano #2 z `FEATURE_WAKE_*` i `FEATURE_PWRLED`, przekaźnik, odbiornik TSOP | wył. | wył. |
| `wifi_hotspot` | dodatkowy AP ALFA-NET — w aucie testowym musi zostać wyłączony (MT7921 obsługuje AA) | — | osobny dongiel Wi-Fi | wył. | wył. |

Pozostałe moduły (OBD, kamery, czujniki parkowania, Nano #1, alarm, ekran
pomocniczy) są wyłączone w obu configach — wymagają sprzętu, którego
w aucie testowym nie ma. W konfiguracji docelowej są też włączone
`blinker_monitor` i `performance` (tak jak miałeś w `config/local.yaml`). Kalibracja BATT, gdy kiedyś będzie bufor:
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

(`bcm-car-phone` — telefon w aucie; `bcm-phone-pan` — główny telefon, tylko
z `phone_tether`, w konfiguracji docelowej go nie ma)

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
- [ ] Trasy (konfiguracja docelowa, bez PAN): lista tras odpowiada —
      `curl -s http://127.0.0.1:5002/trips | head -n 5` na komputerze.
- [ ] Trasy z telefonu — **tylko z `phone_tether`**:
      `http://<IP bnep0>:5002/trips` w przeglądarce telefonu, GPX się pobiera.
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
| „Czujniki telefonu” | „działa”, akcelerometr ~100 Hz, żyroskop ~100 Hz (albo „—”, gdy telefon go nie ma), „światło: … lx (… temu)”; „Test” → „test: wszystko działa” (§10.2) |
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

### 9.6 Tankowania i spalanie (`modules.fuel_log`)

Auto nie ma OBD z przepływem paliwa, więc spalanie liczy BCM z tego, co
wpiszesz po tankowaniu. Ekran trasy (A3): pod
nagłówkiem „Tankowania” duży przycisk „Zatankowano”. W okienku:

- **Litry** — wymagane, z paragonu (np. `45,5`; przecinek albo kropka są
  na klawiaturze ekranowej).
- **Cena za litr** — opcjonalnie; bez niej nie ma kosztu na 100 km.
- **Licznik** — opcjonalnie. Bez licznika dystans między tankowaniami
  bierze się z zapisanych tras GPS. GPS zaniża dystans o kilka procent
  (punkty co kilka sekund, początek jazdy przed złapaniem pozycji), więc
  gdy czasem wpiszesz licznik przy dwóch kolejnych tankowaniach do pełna,
  BCM wyliczy z tego poprawkę (najwyżej ±10 %) i zastosuje ją do przedziałów
  bez licznika.
- **Do pełna** — domyślnie włączone. Tankuj do pierwszego odbicia
  pistoletu i zostaw włączone; przy tankowaniu „za 100 zł” wyłącz. Spalanie
  liczy się tylko między DWOMA tankowaniami do pełna (litry drugiego plus
  częściowe pomiędzy, podzielone przez dystans), dlatego po pierwszym wpisie
  ekran pisze „brak danych do spalania — zatankuj do pełna jeszcze raz”.

Panel pokazuje średnie spalanie (ze wszystkich przedziałów), ostatni
przedział, koszt na 100 km, kilometry od ostatniego pełnego baku i zasięg
szacowany z pojemności baku (`fuel_sender.tank_capacity_litres`, 58 l).
Ta sama średnia trafia do planu podróży (paliwo na trasę „wg tankowań”
zamiast stałych 7 l/100 km). „Usuń ostatnie” cofa literówkę (tylko
najnowszy wpis). Historia jest też na stronie `/trips` (tabela
„Tankowania”): `http://127.0.0.1:5002/trips` na komputerze, z telefonu
`http://<IP bnep0>:5002/trips` — tylko z `phone_tether` (§5).

Gdy po kilku tankowaniach do pełna wciąż nie ma średniej, panel mówi
dlaczego: „brak dystansu — wpisz stan licznika przy następnym tankowaniu”
(nie było GPS ani licznika) albo „odcinki pominięte” (za krótkie lub
nierealne). Plik `data/fuel_log.db` ma prawa 0600 (zapisuje też miejsce
tankowania).

Dystans, czas i średnią prędkość bieżącej jazdy na A3 liczy osobny moduł
`trip_gps` (wymaga `location`); spalanie i zasięg w tych polach bierze
z dziennika tankowań. Bez GPS albo bez `fuel_log` pola pokazują „—”.

- [ ] Po wpisie panel pokazuje go na liście; po drugim tankowaniu do pełna
      — spalanie w l/100 km.
- [ ] Przedział krótszy niż 20 km albo spalanie poza 2–30 l/100 km jest
      na liście oznaczone „pominięte” i nie psuje średniej.

### 9.7 Ostrzeżenia pogodowe (`modules.weather_alerts`)

BCM sprawdza dane, które moduł `weather` i tak pobiera z OpenWeatherMap
(pogoda teraz i prognoza co 3 godziny), i ostrzega przed:

| Rodzaj | Ostrzeżenie | Niebezpieczne |
|--------|-------------|---------------|
| oblodzenie | ≤ 2 °C i opad, mgła, wilgotność ≥ 90 % albo punkt rosy ≤ 1 °C od temperatury; temperatura spadnie poniżej 0 °C w ciągu 3 h po deszczu | marznący deszcz albo deszcz/mżawka przy ≤ 0 °C („Gołoledź”) |
| śnieg | każdy opad śniegu | intensywny (≥ 3 mm na 3 h) |
| ulewa | ≥ 10 mm na 3 h | ≥ 20 mm na 3 h |
| burza | każda burza | silna burza |
| wiatr | porywy ≥ 15 m/s (54 km/h) albo wiatr ≥ 14 m/s | porywy ≥ 25 m/s (90 km/h) |
| mgła | widoczność < 200 m albo mgła wg OWM (kod 741) | widoczność < 50 m |

Do tego informacja „Zimna nawierzchnia” (tylko powiadomienie, bez głosu —
świadomie poziom „info”, nie ostrzeżenie): bezchmurna noc, 0–3 °C (mosty
i cień mogą być śliskie, choć powietrze ma plus).

Skąd dane: pogoda teraz, prognoza w miejscu auta (z GPS) na 6 godzin
naprzód (`weather_alerts.lookahead_h`) i — gdy na ekranie trasy jest cel —
punkty trasy („na trasie”). Bez GPS prognoza jest dla miejsca, dla którego
pobrano pogodę (domyślne miasto albo wyszukane na A4). Dane przykładowe
(„Milan, IT” przed pierwszym pobraniem) nigdy nie dają ostrzeżeń.

Co widać:

- powiadomienie na ekranie (na górze), np. „Ryzyko oblodzenia — 1 stopień
  i opady, teraz. Uważaj na mostach i w cieniu.”;
- pasek z ostrzeżeniem na mapie ekranu pogody (A4) — najpoważniejsze,
  „+1 więcej”, gdy jest ich kilka;
- ikona w pasku górnym (śnieżynka, wiatr, chmura z deszczem…) w kolorze:
  niebieski — informacja, pomarańczowy — ostrzeżenie, czerwony —
  niebezpieczne; dotknięcie otwiera ekran pogody;
- komunikat głosowy (`voice.announce`) — mówi go moduł `voice_announce`
  (§9.9).

To samo ostrzeżenie nie wraca co 15 minut: powtórka najwcześniej po
`cooldown_min` (60 min), wcześniej tylko wtedy, gdy się nasili (np.
z ostrzeżenia w niebezpieczne). Głos tylko dla ostrzeżeń
i niebezpiecznych; w godzinach `quiet_hours` (np. `'22:00-06:00'`) bez
głosu, poza niebezpiecznymi. Okienko oblodzenia na środku ekranu zostaje
wyłączone (wcześniejsza prośba) — jest tylko powiadomienie i głos.

Kategorie i progi: blok `weather_alerts` w `config/bcm_config.yaml` (konfiguracja docelowa; ten sam
w `bcm_config_test.yaml`)
(zmiany w `config/local.yaml`, §2), np. bez ostrzeżeń o wietrze:

```yaml
weather_alerts:
  categories:
    wind: false
```

Prognoza dla punktów trasy dalej niż 30 km od auta to osobne zapytania do
OpenWeatherMap (najwyżej 24 na 10 minut, wyniki trzymane 30 minut). Darmowy
klucz API 2.5 pozwala na 60 zapytań na minutę, więc ten limit go nie
przekroczy; w najgorszym przypadku (cały czas nowe komórki 0,1°) to jednak do
ok. 3456 zapytań na dobę — na hardware nie było to jeszcze mierzone.

```bash
curl -s http://127.0.0.1:5002/api/data | python3 -m json.tool | grep -A8 '"weather_alerts"'
```

(`null` — moduł wyłączony, `[]` — brak ostrzeżeń)

- [ ] Ekran pogody: wiersze prognozy (DZIŚ i dwa kolejne dni) mają
      prawdziwe temperatury z prognozy, a bez prognozy jest „brak prognozy”.
- [ ] Przy mrozie z opadem (albo progach obniżonych na próbę w
      `local.yaml`, np. `icing_temp_c: 5`, `icing_humidity_pct: 50`)
      pojawia się powiadomienie, pasek na A4 i ikona w pasku; drugi raz po
      15 minutach już nie.

### 9.8 Utrudnienia w trakcie jazdy (`modules.traffic_alerts`)

Planer tras pyta TomTom o utrudnienia tylko raz, przy wyznaczaniu trasy.
Ten moduł pyta w trakcie jazdy i mówi tylko o tym, co jest przed autem.

- **Kiedy:** tylko w jeździe — prędkość z GPS powyżej 15 km/h przez 30 s.
  Stanie w korku nie kończy jazdy: koniec dopiero po 10 minutach poniżej
  15 km/h albo po 2 minutach bez GPS. Pierwsze zapytanie zaraz po ruszeniu,
  potem co `poll_min` minut (domyślnie 5, najmniej 2).
- **Gdzie:** z celem na ekranie trasy — korytarz 3 km szerokości wzdłuż
  następnych `lookahead_km` km trasy (10 km) i tylko utrudnienia leżące na
  trasie. Bez celu (albo gdy zjedziesz z trasy dalej niż 2 km) — pole
  10 km przed autem i 3 km szerokości, obrócone zgodnie z kierunkiem jazdy,
  i tylko utrudnienia w kierunku jazdy (±60°). Utrudnienie na przeciwnej
  jezdni (biegnące w drugą stronę) jest pomijane. Trasa przybliżona (linia
  prosta do celu, gdy planer nie ma klucza ORS) nie jest drogą — wtedy też
  pole przed autem.
- **Ile zapytań:** twardy limit `daily_budget` (300) na dobę UTC, zapisany
  w `data/traffic_budget.json`, więc restart go nie zeruje. Darmowy klucz
  TomTom ma ok. 2500 zapytań na dobę, wspólnych z planerem tras i testem
  w Ustawieniach. Co 5 minut to 12 zapytań na godzinę jazdy, więc limit 300
  starcza na 25 godzin jazdy (przy `poll_min: 2` — na 10 godzin). Po błędzie przerwa: od 1 minuty
  rosnąco do 30 minut; po 429 (wyczerpany limit TomTom) od 15 minut do
  2 godzin; po 401/403 (zły klucz) 1 godzina. Cofnięcie zegara (np. zły
  czas RTC po starcie, poprawiony potem z telefonu) nie daje nowego limitu:
  licznik zeruje się tylko, gdy przyjdzie późniejsza doba.

O czym powiadamia: wypadek i zamknięta droga — zawsze; korek, roboty,
zwężenie i inne — gdy opóźnienie jest co najmniej `min_delay_s` (180 s)
albo TomTom określa je jako duże. Tylko nowe utrudnienia i takie, które
się nasiliły (z korka zrobiło się zamknięcie, opóźnienie wzrosło o co
najmniej 5 minut i o połowę). Najwyżej jedno powiadomienie na 2 minuty —
kolejne czeka, póki jest przed autem.

Co widać i słychać:

- powiadomienie na ekranie, np. „Korek za 3,2 km — S8 · opóźnienie ok.
  10 min · Wrocław → Oleśnica”;
- prośba o komunikat głosowy (`voice.announce`, kategoria `traffic`), np.
  „Uwaga, korek za 3 kilometry na drodze S8, opóźnienie około 10 minut.” —
  mówi go moduł `voice_announce` (§9.9; `voice: false` wyłącza same
  prośby);
- ekran trasy (A3): przycisk „Travel Plan” ma znaczek z liczbą utrudnień
  przed autem i odległością do najbliższego, np. „2 · 3,2 km” — widać go
  także bez celu;
- ekran trasy (A3 → „Travel Plan”): sekcja „Utrudnienia na bieżąco
  (TomTom)” (pod sekcją „Utrudnienia przy wyznaczaniu trasy”, czyli
  jednorazowym sprawdzeniem z planera) odświeżana w miejscu — lista przed autem, stan („sprawdzam
  w trakcie jazdy”, „zapytania dziś: 12/300”, błąd TomTom z kodem) — ukryta,
  gdy moduł jest wyłączony;
- ekran pomocniczy (`small_display`) pokazuje najbliższe utrudnienie.

Ustawienia: blok `traffic_alerts` w `config/bcm_config.yaml` (konfiguracja docelowa; ten sam
w `bcm_config_test.yaml`) (zmiany
w `config/local.yaml`, §2), np. rzadziej i dalej:

```yaml
traffic_alerts:
  poll_min: 10
  lookahead_km: 20
```

Stary blok `traffic:` (`api_key`, `poll_interval_min`) nie jest używany —
klucz to `BCM_TOMTOM_API_KEY` w `/etc/bcm/bcm.env`.

```bash
curl -s http://127.0.0.1:5002/api/data | python3 -m json.tool | grep -A30 '"traffic_alerts"'
```

(`null` — moduł wyłączony; `"state": "idle"` — postój, `"no_key"` — brak
klucza, `"backoff"` — przerwa po błędzie, `"budget"` — limit na dziś
wykorzystany)

- [ ] Na postoju: `"state": "idle"`, licznik `used` nie rośnie.
- [ ] Po ruszeniu (powyżej 15 km/h przez 30 s): `used` rośnie o 1, potem
      o 1 co 5 minut; w logu nie ma klucza (`journalctl -u bcm-headunit | grep -i tomtom`).
- [ ] Na drodze ze znanym korkiem przed autem: powiadomienie raz, nie co
      5 minut; utrudnienie za autem znika z listy.

### 9.9 Komunikaty głosowe (`modules.voice_announce`)

Ostrzeżenia pogodowe (§9.7) i utrudnienia (§9.8) BCM czyta na głos po
polsku. Muzyka jest na czas komunikatu ściszana o 12 dB i po nim płynnie
(1 s) wraca — Twoja głośność się przy tym nie zmienia (ściszany jest
strumień wyjściowy korektora, `bcm_eq_sink_output`, a nie suwak
głośności). Sam głos idzie z pominięciem korektora prosto na wyjście
sprzętowe, więc ściszanie muzyki go nie ścisza.

**Instalacja** — robi to `apply-fixes.sh` (krok 6/8) i `setup-x86.sh`:

- `espeak-ng` z Debiana — głos zapasowy (robotyczny, ale zawsze działa);
- Piper 2023.11.14-2 i głos `pl_PL-gosia-medium` do `/opt/bcm/piper`
  (`config/scripts/install-piper.sh`). Każdy pobrany plik jest sprawdzany
  sumą SHA-256 z `config/scripts/piper-sha256.txt`; plik bez sumy na liście
  albo z inną sumą NIE jest instalowany. Suma programu Piper jest na liście;
  sum głosu (`pl_PL-gosia-medium.onnx` i `.onnx.json`) jeszcze nie ma — skrypt
  to wypisze. Dopisz je raz:

```bash
# sumy podane na stronie pliku w Hugging Face (rhasspy/piper-voices,
# v1.0.0, pl/pl_PL/gosia/medium) — albo policzone z pobranych plików:
sudo install -d -m 0755 /etc/bcm
sudo nano /etc/bcm/piper.sha256
#   <suma>  pl_PL-gosia-medium.onnx
#   <suma>  pl_PL-gosia-medium.onnx.json
sudo bash /opt/bcm/config/scripts/install-piper.sh
```

Bez Pipera BCM mówi przez espeak-ng; bez obu tylko pokazuje powiadomienia
(i raz wpisuje do logu, czego brakuje). Gosia, a nie Darkman: wyższy,
kobiecy głos lepiej przebija się przez szum silnika, opon i bas muzyki.

**Ładny głos: Azure Neural (zalecane).** Piper i espeak-ng mówią po polsku
dość sztucznie. Głos z chmury Microsoft (Azure AI Speech) brzmi naturalnie;
domyślnie **Agnieszka** (`pl-PL-AgnieszkaNeural`) — młodszy, ciepły głos,
lekko spokojniejsze tempo (`rate: -4`) i odrobinę wyższy ton (`pitch: 3`).
Głosy w Azure to nagrania konkretnych lektorek — „charakter” wybierasz
głosem, a tempem i tonem tylko go doszlifujesz. Darmowy plan F0 daje
0,5 mln znaków miesięcznie; jedno ostrzeżenie to ~80 znaków, a każde zdanie
trafia do cache (`data/voice_cache`), więc powtórki nie zużywają limitu
i grają też bez internetu. Do Azure idzie wyłącznie tekst komunikatu (bez
pozycji, bez danych osobowych). Bez klucza, bez sieci albo przy błędzie
mówi Piper.

1. https://portal.azure.com → „Utwórz zasób” → **Speech** (Azure AI
   services) → region np. **West Europe** (albo Poland Central), plan
   cenowy **Free F0** → Utwórz.
2. Zasób → „Keys and Endpoint” → skopiuj **KEY 1** i nazwę regionu
   (np. `westeurope`).
3. Klucz do sekretów (bez cudzysłowów, bez spacji):

```bash
sudo nano /etc/bcm/bcm.env
```

   linia `BCM_AZURE_TTS_KEY=<KEY 1>`.
4. Region — jeśli inny niż `westeurope` — w `config/local.yaml`:

```yaml
voice_announce:
  azure:
    region: polandcentral
```

5. Restart BCM:

```bash
sudo systemctl restart bcm-headunit
```

6. Ustawienia → „Komunikaty głosowe”: status „Azure · Agnieszka”. W wierszu
   „Głos” wybierz Agnieszka / Zofia / Ava / Emma i za każdym razem
   **„Powiedz test”** — zostaw ten, który najbardziej Ci odpowiada (wybór
   zapisuje się w `config/local.yaml`). Ava i Emma to głosy wielojęzyczne
   (mówią po polsku z lekkim akcentem), Zofia jest bardziej lektorska.

Komunikaty w wierszu: „brak klucza” (punkt 3), „zły format klucza albo
regionu”, „Azure odrzucił klucz (401/403)” — klucz z innego regionu albo
źle skopiowany; „chwilowo niedostępny” — brak internetu, BCM spróbuje
ponownie za 1–15 min, a w tym czasie mówi Piper.

**Ustawienia → „Komunikaty głosowe”** (widać tylko przy włączonym
module):

- Wł./Wył. — wyłączony moduł działa dalej, tylko milczy;
- suwak głośności głosu (10–100 %);
- przełączniki „Mów o”: pogoda, utrudnienia, system;
- **„Powiedz test”** — BCM mówi stałe zdanie „Test komunikatów głosowych.
  Tak będą brzmiały ostrzeżenia.” (z ekranu w aucie, najwyżej raz na 8 s;
  zdania nie da się podać z zewnątrz).

Wiersz pokazuje też, czym BCM mówi (Piper / espeak-ng / brak) i jak
skończył się ostatni komunikat.

**Co i kiedy jest mówione:**

- tylko prośby z włączonych kategorii, najpierw niebezpieczne (oblodzenie,
  wypadek, zamknięta droga), potem reszta;
- przed komunikatem krótki dźwięk (`chime: false` go wyłącza);
- ten sam komunikat najwyżej raz na 5 minut (`dedupe_s`) — eskalacja
  (ostrzeżenie → niebezpieczeństwo, większe opóźnienie w korku) mówiona
  od razu, bo ma inny tekst albo wyższy priorytet; najwyżej 4 na
  minutę (`max_per_min`; niebezpieczne poza limitem), co najmniej 3 s
  przerwy (`min_gap_s`);
- starszy niż 60 s (`max_age_s`) już nie jest mówiony;
- **nigdy w trakcie rozmowy telefonicznej**: komunikat czeka najwyżej 45 s
  (`call_defer_s`), potem przepada; rozmowa, która zacznie się w trakcie
  komunikatu, go przerywa;
- milczy przy działających czujnikach parkowania (`quiet_when_parking`).

Ściszanie działa też (tak jak liczy je BCM od zawsze) przy czujnikach
parkowania (-18 dB), ale nie w trakcie rozmowy: rozmowa idzie przez ten
sam korektor, więc ściszenie ściszyłoby rozmówcę. Bez korektora
(`audio.eq_dsp_enabled: false`) ściszane są strumienie odtwarzania z
wyjątkiem głosu BCM i wewnętrznych strumieni BCM. Po awarii BCM przy
następnym starcie przywraca pełną głośność muzyki — także wtedy, gdy moduł
w międzyczasie wyłączono. Nieudane przywrócenie (zajęty PipeWire) BCM
ponawia kilka razy (1, 2, 4, 8 s).

Ustawienia: blok `voice_announce` w `config/bcm_config.yaml` (konfiguracja docelowa; ten sam
w `bcm_config_test.yaml`)
(zmiany w `config/local.yaml`, §2), np. ciszej i bez dźwięku przed komunikatem:

```yaml
voice_announce:
  volume: 60
  chime: false
```

```bash
curl -s http://127.0.0.1:5002/api/data | python3 -m json.tool | grep -A20 '"voice_announce"'
```

(`null` — moduł wyłączony; `"engine": "piper"` / `"espeak"` / `"none"`;
`"ducking": "eq"` — ściszany korektor, `"streams"` — strumienie, `"off"` —
bez PipeWire)

- [ ] „Powiedz test” przy grającej muzyce: dźwięk, zdanie, muzyka cichnie
      i po zdaniu płynnie wraca do tej samej głośności.
- [ ] Głośność muzyki pokrętłem przed i po teście — taka sama
      (`wpctl get-volume @DEFAULT_AUDIO_SINK@`).
- [ ] W trakcie rozmowy: „Powiedz test” odpowiada „trwa rozmowa”, nic nie
      słychać w słuchawce rozmówcy.
- [ ] Ostrzeżenie pogodowe albo utrudnienie: jeden komunikat, nie co
      kilka minut.

---

## 10. Gdy coś nie działa

| Objaw | Przyczyna i co zrobić |
|-------|-----------------------|
| Brak pogody; w logu `WeatherManager started (api_key=not set)` | `BCM_OWM_API_KEY` w `/etc/bcm/bcm.env` (§3.6), restart BCM. Świeżo wygenerowany klucz OpenWeatherMap może zacząć działać dopiero po jakimś czasie (zależy od dostawcy). |
| W logu `Secrets from environment` bez nazwy klucza | Linia w `bcm.env` zakomentowana albo z komentarzem za wartością (komentarz tylko w osobnej linii). |
| Zmiany z ekranu znikają po restarcie (przy modułach: „nie zapisano w local.yaml — zmiana zniknie po restarcie”) | `config/local.yaml` zapisany dla innej bazy (linia `# base:` na początku pliku) — BCM go stosuje, ale nie nadpisuje; w logu `Config: … saving is disabled …`. BCM zatrzymany (§3.2), potem: migracja — z kopią z auta wariant A, bez niej wariant B (`--source config/bcm_config_temp.yaml … --write --merge-existing`, §3.5); nagłówek staje się `# base: bcm_config_test.yaml`, więc zaraz potem §13.2–§13.5 (konfiguracja docelowa; albo od razu `--base config/bcm_config.yaml` — to samo polecenie podpowiada log). Tylko gdy migracja jest niemożliwa: usuń linię `# base:` w `config/local.yaml` (podpowiedź z logu) — przepadną wtedy wartości z ery temp, których nie było w nakładce (np. `audio.sink` wraca do `auto`, `blinker_monitor`, przycisk SWC mute, motyw). |
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

### 10.1 Internet i klucze API — diagnostyka

„Połączono” przy telefonie znaczyło dotąd tylko, że działa łącze do
telefonu — nie, że telefon przepuszcza ruch dalej. Z `modules.net_diag`
(konfiguracja docelowa i testowa: włączony) BCM sprawdza trzy rzeczy:
którym interfejsem idzie trasa domyślna, czy działa DNS i czy przechodzi
jedno zapytanie HTTPS (`HEAD` do `www.gstatic.com`, bez żadnych danych).
Bez internetu — najwyżej raz na 60 s; gdy internet działa — raz na 10 min
(plus od razu po każdym połączeniu telefonu i po „Test”), żeby auto nie
odzywało się do obcego serwera co minutę przez całą jazdę.

**Wiersz Ustawienia → „Internet i usługi”** — czytaj od góry:

1. Łącze: „USB z telefonu” / „Bluetooth z telefonu” / „inne łącze” (w nawiasie
   interfejs) i „internet: tak/nie” z powodem („brak trasy”, „DNS nie działa”,
   „HTTPS nie przechodzi”). „inne łącze” przy braku internetu = trasę
   domyślną przejął inny interfejs z niższą metryką (np. sieć Wi-Fi bez
   internetu) — odłącz go albo popraw metrykę.
2. Po jednej linii na usługę (OpenWeatherMap, OpenRouteService, TomTom):
   „klucz: tak/nie” i wynik ostatniego zapytania — „OK”, „błąd 401 — zły
   albo nieaktywny klucz”, „błąd 429 — wyczerpany limit zapytań”, „błąd
   sieci”, „nie testowano”. Wartość klucza nigdzie się nie pokazuje.
3. Przycisk „Test” (tylko z ekranu w aucie, najwyżej raz na 10 s): świeża
   sonda internetu i jedno małe zapytanie do każdej usługi z kluczem.
   Wynik po kilku–kilkunastu sekundach w tym samym wierszu.

Przy telefonie w wierszu „Telefon w aucie” / „Internet z telefonu” pojawia
się „połączono, bez internetu” i podpowiedź „telefon nie udostępnia
internetu: dane komórkowe wyłączone albo operator blokuje tethering”.
Ekran pogody pisze „dane przykładowe — …”, gdy na ekranie nie ma prawdziwych
danych, i dlaczego (brak klucza, błąd 401, brak połączenia).

**Czy BCM w ogóle wczytał klucze** — linia z nazwami (nigdy wartościami):

```bash
sudo journalctl -u bcm-headunit -b | grep -E 'Secrets from environment|Secret BCM_'
```

`Secrets from environment: BCM_ORS_API_KEY, BCM_OWM_API_KEY` = wczytane.
`Secret BCM_ORS_API_KEY is not set` = brak tej zmiennej w `/etc/bcm/bcm.env`
(albo linia zakomentowana) — popraw plik (§3.6) i zrestartuj BCM.
Ostrzeżenie pojawia się tylko dla kluczy włączonych modułów (`weather` →
OWM, `route_planner` → ORS i TomTom, `car_phone_agent` → sekret agenta).

**Sonda i wyniki usług z wiersza poleceń:**

```bash
curl -s http://127.0.0.1:5002/api/debug/weather | python3 -m json.tool
```

Pola `internet_probe`, `keys_set` (tak/nie per usługa), `service_results`
i `weather_status`.

| W wierszu / na ekranie | Co zrobić |
|------------------------|-----------|
| „klucz: nie” | Zmienna z wiersza (np. `BCM_ORS_API_KEY`) do `/etc/bcm/bcm.env`, restart BCM. |
| „błąd 401 — zły albo nieaktywny klucz” | Klucz przepisany z błędem albo jeszcze nieaktywny (nowy klucz OpenWeatherMap działa po kilkudziesięciu minutach, do 2 h). Porównaj z panelem dostawcy. |
| „internet: nie (brak trasy)” | Żadne łącze nie daje trasy domyślnej — telefon odłączony albo tethering wyłączony. |
| „internet: nie (DNS nie działa)” / „(HTTPS nie przechodzi)” | Telefon daje adres, ale nie przepuszcza ruchu: dane komórkowe, limit pakietu, blokada tetheringu u operatora. |
| Trasa „przybliżona — odległość w linii prostej” | Brak `BCM_ORS_API_KEY`. |
| Wyszukiwanie celu: „używa klucza OpenWeatherMap” | Wyszukiwarka celu korzysta z klucza pogody (`BCM_OWM_API_KEY`), nie z ORS. |

### 10.2 Czujniki telefonu i światło — test

Wiersz **Ustawienia → „Czujniki telefonu”** (moduł `phone_sensors`)
pokazuje stan strumienia SensorServer, ramki na sekundę z ostatnich 10 s
dla akcelerometru i żyroskopu oraz ostatni odczyt światła i jego wiek
(„światło: 120 lx (4 s temu)”). Czujnik światła wysyła odczyt tylko po
zmianie jasności — przy stałym świetle wiek rośnie i to jest w porządku.
Światło działa niezależnie od akcelerometru: „brak akcelerometru” przy
świeżym „światło: … lx” znaczy, że jasność ekranu działa, a wykrywanie
stłuczki z akcelerometru — nie.

**Przycisk „Test”** (tylko z ekranu w aucie, najwyżej raz na 12 s): BCM
liczy przez 10 s ramki każdego czujnika i pokazuje werdykt z podpowiedzią:

| Werdykt | Co zrobić |
|---------|-----------|
| „wszystko działa” | Nic. Pod spodem liczba ramek i zakres lux z tych 10 s; przy stałym świetle zamiast zakresu „światło stałe — ostatni odczyt … lx, … s temu” (0 ramek światła w 10 s to wtedy norma). |
| „brak połączenia z telefonem (forward „sensors”)” | Wg podpowiedzi: włącz moduł `car_phone`; albo `modules.phone_sensors: true` w `config/local.yaml` i restart BCM (forward powstaje przy starcie `car_phone`); albo podłącz telefon i zaakceptuj debugowanie USB. |
| „SensorServer nic nie wysyła” | Aplikacja uruchomiona? Local Host, port 8080, Start, praca w tle (`PRZYGOTOWANIE_TELEFONU.md` §7). |
| „brak odczytów światła” | Tylko gdy na obecnym połączeniu nie przyszedł żaden odczyt światła (albo ostatni ma ponad 10 min). Czujnik światła zaznaczony w SensorServer, praca w tle bez optymalizacji baterii, czujnik niezasłonięty. Powtórz test z włączonym i z wygaszonym ekranem telefonu. Podpowiedź „telefon odrzuca czujnik światła”: telefon 3 razy odmówił samego światła — sprawdź SensorServer i zrestartuj BCM. |
| „brak akcelerometru” | Akcelerometr zaznaczony w SensorServer. |
| „akcelerometr za wolny” | Próbkowanie 10000 µs (100 Hz); poniżej 80 Hz stłuczka z akcelerometru jest wyłączona. |

Gdy telefon odrzuci wspólne połączenie dla trzech czujników (albo 3 razy
z rzędu zamknie je bez odczytu), BCM najpierw próbuje bez żyroskopu; przy
kolejnej odmowie (albo od razu, gdy odmowa dotyczy światła lub
akcelerometru) przechodzi na osobne połączenie dla każdego czujnika
(w wierszu: „osobne połączenie dla każdego czujnika”) i zostaje przy tym
do restartu. Log:

```bash
sudo journalctl -u bcm-headunit -b | grep -iE 'phone sensors|czujnika światła'
```

`SensorServer nie wysyła czujnika światła — sprawdź w aplikacji, czy światło
jest włączone / ekran` pojawia się raz, po 30 s bez żadnego odczytu światła.
Test z wiersza poleceń (na M910q):

```bash
curl -s -X POST http://127.0.0.1:5002/api/phone_sensors/test; sleep 11
curl -s http://127.0.0.1:5002/api/data | python3 -c 'import json,sys; print(json.dumps(json.load(sys.stdin)["phone_sensors"], indent=1, ensure_ascii=False))'
```

---

### 10.3 Internet każdym łączem, nie tylko po Ethernecie

Objaw: „Internet i usługi” pokazuje **inne łącze** (np. `eno1`) zamiast
„USB z telefonu”, pogoda i trasy nie działają, a `ip route get 1.1.1.1`
mówi `dev eno1`. Przyczyna: Ethernet ze statycznym IP i bramą ma w
NetworkManagerze metrykę 100 (albo bramę wpisaną na sztywno jako trasa
`0.0.0.0/0`) i wygrywa z telefonem po USB (650), nawet gdy za kablem nie ma
internetu. Naprawa — `config/scripts/bcm-net-auto.sh`:

- statyczny adres na Ethernecie zostaje, ale jego trasa domyślna dostaje
  metrykę 900 (ostatnia w kolejce; `--eth-no-default` = eth tylko do sieci
  lokalnej, bez internetu);
- włącza test łączności NetworkManagera co 60 s: łącze bez internetu
  dostaje +20000 do metryki i ruch sam przechodzi na następne;
- blokuje automatyczne profile „Wired connection N” dla telefonu po USB.

Kolejność po zmianie: Wi-Fi ~600 · USB z Redmi 650 · LTE 700 ·
Bluetooth 750 · Ethernet 900. Profili BCM i Wi-Fi (AA, ALFA-NET) skrypt nie
rusza. Najpierw podgląd:

```bash
cd /opt/bcm && sudo bash config/scripts/bcm-net-auto.sh --dry-run
```

Potem naprawdę:

```bash
cd /opt/bcm && sudo bash config/scripts/bcm-net-auto.sh
```

Sprawdzenie (ma pokazać łącze telefonu, np. `usb0`/`enx…`):

```bash
ip route get 1.1.1.1
```

Cofnięcie (przywraca zapisane w `/etc/bcm/net-auto.state` ustawienia):

```bash
cd /opt/bcm && sudo bash config/scripts/bcm-net-auto.sh --undo
```

### 10.4 Muzyka „przycina” w trakcie odtwarzania

Niskie temperatury nie są przyczyną, dopóki w aucie jest powyżej zera:
M910q, karta USB i Bluetooth pracują w tym zakresie normalnie. Dziura
w dźwięku to prawie zawsze **xrun** — PipeWire nie zdążył przygotować
kolejnego bloku dźwięku. Najczęstsze powody w tym aucie:

- PipeWire bez priorytetu czasu rzeczywistego (brak `rtkit`) — wtedy każde
  chwilowe obciążenie procesora (animacje kiosku, strumień czujników
  telefonu, adb) przerywa muzykę. `apply-fixes.sh` instaluje `rtkit`;
- przerwy po stronie Bluetooth (telefon daleko, Wi-Fi 2,4 GHz w tym samym
  radiu) — widać to jako błędy przy węzłach `bluez_*`;
- zamierzone ściszenie przy komunikacie głosowym albo rozmowie.

BCM nie robi już w trakcie grania pełnego zrzutu grafu PipeWire co
10–15 s: analizator widma przy `pw-record` w ogóle, a router mikrofonu
zwalnia do raz na minutę, gdy nic się nie zmienia.

Diagnoza — uruchom, gdy gra muzyka (najlepiej, gdy przycina); tylko czyta:

```bash
sudo bash /opt/bcm/tools/bcm-audio-xruns.sh 60
```

Skrypt pokazuje priorytet wątków PipeWire, przyrost błędów (kolumna `ERR`
w `pw-top`) dla każdego węzła, obciążenie procesora, błędy USB z dziennika
jądra i zdarzenia BCM, które przerywają albo ściszają muzykę; na końcu
podpowiada, co z tego wynika.

## 11. Wycofanie zmian

**Powrót na konfigurację testową** (po §13): §13.7.

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
- progi ostrzeżeń pogodowych wobec prawdziwej drogi (oblodzenie z danych
  OpenWeatherMap, nie z czujnika w aucie) i zużycie zapytań OWM przy
  długiej trasie;
- utrudnienia TomTom: czy kolejność punktów linii utrudnienia to kierunek
  ruchu (od tego zależy pomijanie przeciwnej jezdni), czy pola `delay`,
  `roadNumbers`, `from`/`to` przychodzą po polsku i wypełnione, oraz ile
  zapytań naprawdę zużywa dzień jazdy;
- komunikaty głosowe: `pw-play --target` na sink sprzętowy z sesji
  uruchomionej jako root, `wpctl set-volume` na strumieniu wyjściowym
  korektora (`bcm_eq_sink_output`) i to, czy WirePlumber zapamiętuje tę
  głośność; czas syntezy Pipera na M910q; sumy SHA-256 głosu
  `pl_PL-gosia-medium` (do dopisania, §9.9);
- SensorServer: czy odrzuca wspólne połączenie kodem 4xxx, czy ramki
  z jednoczujnikowego `/sensor/connect?type=…` mają pole `type`, czy czujnik
  światła działa przy wygaszonym ekranie Redmi;
- menu „Wake on LAN” w BIOS-ie tej sztuki M910q;
- wybudzanie (wersja z buforem): dekoder NEC z prawdziwym odbiornikiem
  TSOP, nadajnik IR Redmi przez Termux:API na crDroid 13, przetrwanie stanu
  Nano przez reset przy otwarciu portu (`ZASILANIE_BUFOROWANE.md` §14.8).

---

## 13. Przejście na konfigurację docelową

Od 23.11 bazą auta jest `config/bcm_config.yaml` — konfiguracja docelowa.
Ma wszystko, co działało w `config/bcm_config_test.yaml`, a do tego to, co
miałeś w `config/local.yaml` auta (karta dźwiękowa USB, motyw
`autodelta`, jasność 62, autorestart Android Auto, wyciszenie pod
`SWC_VOICE`/`SWC2_MUTE`, moduły telefonu w aucie, `auto_brightness`,
`blinker_monitor`, `performance`) i nowe moduły (`fuel_log`,
`weather_alerts`, `traffic_alerts`, `voice_announce`, `traccar`,
`last_park`). Co jest
włączone: kolumna „Docelowa” w §8. `config/bcm_config_test.yaml` zostaje
w repo jako konfiguracja stanowiskowa — auto może na nią wrócić (linia
w `bcm.env` + przywrócenie kopii `config/local.yaml`, §13.7).

Celowo **inaczej** niż dotąd:

- `modules.phone_tether: false` — Redmi jest w aucie na stałe i daje
  internet po USB (`car_phone`), więc internet z głównego telefonu po
  Bluetooth (PAN) jest wyłączony; to zapasowa droga — włączysz ją
  w Ustawieniach → Moduły, gdy Redmi wypadnie z auta;
- `modules.network: false` i `modules.crash_detect: false` — tak jak
  miałeś w `config/local.yaml`;
- `modules.traccar: true` — moduł jest włączony, ale **nic nie wysyła**,
  dopóki nie ma obu: `traccar.url` w `config/local.yaml` i
  `BCM_TRACCAR_DEVICE_ID` w `/etc/bcm/bcm.env`
  ([TRACCAR_SERWER.md](TRACCAR_SERWER.md) §8).

**Bez zmian (tryb próbny, jak w teście):** `crash_detection.sms.dry_run:
true`, `parking_guard.log_only: true`, `safety.call112.test_mode: true`.
Jak je uzbroić, piszą komentarze przy tych blokach w
`config/bcm_config.yaml` — zawsze przez `config/local.yaml`, po
sprawdzeniach z `WDROZENIE_TESTOWE.md` §5.9, §5.11 i §5.12.

Ekran: 7" 1024×600. Wartości dla 10,1" 1280×800 są w komentarzu przy
bloku `display` w `config/bcm_config.yaml`.

Zrób kroki po kolei, **bez gaszenia silnika** (albo M910q na zasilaczu
Lenovo na stole) — tak samo jak w §3.

### 13.1 Zatrzymaj BCM

Migracja przy działającym BCM by przepadła (przy pierwszym zapisie BCM
nadpisze `config/local.yaml` swoją wersją z pamięci):

```bash
sudo systemctl stop bcm-ignition-watcher bcm-headunit
```

### 13.2 Kopia `config/local.yaml`

Narzędzie samo robi kopię, ale własna — poza repozytorium — nie zaszkodzi:

```bash
sudo cp -p /opt/bcm/config/local.yaml /root/local.yaml.przed-docelowa
```

### 13.3 Pobierz nową wersję

Jako użytkownik kiosku (bez `sudo`, §3):

```bash
cd /opt/bcm && git pull --ff-only
```

### 13.4 Migracja `config/local.yaml` — podgląd

`config/local.yaml` zaczyna się od `# base: bcm_config_test.yaml` — BCM
pod nową bazą zastosuje go, ale nie zapisze w nim zmian z ekranu (w logu
jest wtedy linia `Config: local.yaml jest zapisany dla bazy
bcm_config_test.yaml…` z tym samym poleceniem, a w Ustawieniach → Moduły
ramka „Zmiany nie są zapisywane”). Podgląd (nic nie zapisuje):

```bash
cd /opt/bcm && sudo .venv/bin/python tools/migrate_local_config.py --source config/local.yaml --base config/bcm_config.yaml
```

Liczą się tylko wartości z Twojego `config/local.yaml` (to Twoje wybory),
każda porównana z nową bazą:

- **WRITE** — zostaje w `config/local.yaml`; dla Twojego pliku powinien
  tu być tylko `multimedia.last_bt_device` (adres ostatniego telefonu
  Bluetooth — dana z auta, nie trafia do repo);
- **IN BASE** — nowa baza ma już tę wartość, więc znika z
  `config/local.yaml` (u Ciebie m.in. `audio.sink`,
  `display.dashboard.theme`, przełączniki modułów, `swc.mapping.mute`);
- **SKIPPED** — baza celowo ustawia inaczej: `modules.phone_tether`
  (decyzja 23.11, wyżej). Gdybyś jednak chciał zostawić Bluetooth PAN,
  dopisz do podglądu i do zapisu `--keep-source modules.phone_tether`;
- **DROPPED** — sekrety (nazwa zmiennej do `bcm.env`, nigdy wartość)
  i dane chwilowe; dla Twojego pliku powinno być pusto. Jeśli jest tu
  sekret (np. klucz wpisany kiedyś na ekranie), `--write` odmówi: najpierw
  wpisz go do `/etc/bcm/bcm.env` pod podaną nazwą, potem dodaj do zapisu
  `--drop-secrets`.

Wartość, której nie chcesz przenosić, wyklucz przez
`--exclude <ścieżka>` (w podglądzie i w zapisie).

### 13.5 Migracja — zapis

```bash
cd /opt/bcm && sudo .venv/bin/python tools/migrate_local_config.py --source config/local.yaml --base config/bcm_config.yaml --write
```

Narzędzie przepisuje plik w miejscu (0600), a stary zostawia jako
`config/local.yaml.bcm_config_test.bak`. Sprawdź nagłówek:

```bash
sudo head -3 /opt/bcm/config/local.yaml
```

Druga linia ma brzmieć `# base: bcm_config.yaml`. Kod wyjścia 2 („nic do
migracji”) znaczy, że plik jest już dla `bcm_config.yaml` — to nie błąd.

### 13.6 Unity, restart i sprawdzenie

Unity BCM z repo mają już `BCM_CONFIG=config/bcm_config.yaml`; instaluje
je `bcm-harden.sh` (krok 2). Najpierw podgląd — ostrzeżenie
„config/local.yaml jest zapisany dla bazy…” znaczy, że §13.5 nie zostało
zrobione:

```bash
cd /opt/bcm && sudo bash config/scripts/bcm-harden.sh --dry-run
```

Potem naprawdę (podmienia unity i sam robi `systemctl daemon-reload`;
pozostałe punkty są już zrobione z §3 i niczego nie zmienią):

```bash
cd /opt/bcm && sudo bash config/scripts/bcm-harden.sh
```

Przeładuj systemd i uruchom BCM:

```bash
sudo systemctl daemon-reload
```

```bash
sudo systemctl restart bcm-ignition-watcher bcm-headunit
```

Sprawdź, z jaką bazą wstał BCM:

```bash
sudo journalctl -u bcm-headunit -b | grep -E 'Config:|Local overlay'
```

Ma być `Config: /opt/bcm/config/bcm_config.yaml` i `Local overlay:
…local.yaml`, a **nie** może być linii „zapis zmian jest wyłączony do
migracji”. Na ekranie: Ustawienia → Moduły bez ramki „Zmiany nie są
zapisywane”, motyw i jasność jak dotąd, dźwięk z karty USB. Potem
sprawdzenia z §9.

### 13.7 Wycofanie

Powrót na konfigurację testową to **linia w `bcm.env` + przywrócenie kopii
`config/local.yaml`** — oba kroki są obowiązkowe. Po §13.5 w
`config/local.yaml` został praktycznie tylko `multimedia.last_bt_device`
(reszta przeszła do bazy jako IN BASE), więc sama linia w `bcm.env`
postawiłaby BCM na konfiguracji testowej prawie bez ustawień auta: dźwięk
z mini-jacka zamiast karty USB, `car_phone` wyłączony (bez internetu po USB
i bez GPS z telefonu), znów włączone `network`, `phone_tether`
i `crash_detect` — a zmiany z ekranu i tak by się nie zapisywały.

Zatrzymaj BCM:

```bash
sudo systemctl stop bcm-ignition-watcher bcm-headunit
```

W `/etc/bcm/bcm.env` dopisz (albo odkomentuj)
`BCM_CONFIG=config/bcm_config_test.yaml`:

```bash
sudo nano /etc/bcm/bcm.env
```

Przywróć kopię sprzed migracji (§13.5 zostawiło ją obok):

```bash
sudo cp -p /opt/bcm/config/local.yaml.bcm_config_test.bak /opt/bcm/config/local.yaml
```

Uruchom BCM:

```bash
sudo systemctl start bcm-ignition-watcher bcm-headunit
```

Jeśli zapomnisz o kopii, BCM zapisze w logu jedną linię z dokładnym
poleceniem `sudo cp -p …`, a `bcm-harden.sh` pokaże to samo ostrzeżenie.
