# Telefon w aucie — przygotowanie Redmi Note 8 Pro (crDroid, Android 13)

Instrukcja krok po kroku dla telefonu, który na stałe siedzi w aucie (pod
podsufitką) i jest podłączony kablem USB do BCM (Lenovo M910q). Telefon daje
BCM:

- **internet** przez tethering USB (Bluetooth PAN z głównego telefonu zostaje
  jako zapas),
- **pozycję GPS** (serwer NMEA w telefonie, BCM czyta go przez `adb forward`),
- **czujniki** — akcelerometr, żyroskop i światło (SensorServer) do wykrywania
  stłuczki i do automatycznej jasności ekranu,
- **agenta w Termuxie** — SMS po stłuczce, „Zadzwoń 112” na głośniku, alarm
  na postoju i czuwanie kabiny przednią kamerą,
- **baterię, temperaturę i zegar** — BCM ich pilnuje i ostrzega o przegrzaniu.

Główny telefon dalej obsługuje Android Auto i rozmowy. Wszystkie moduły BCM
od Redmi są domyślnie **wyłączone** — włączasz je w Ustawienia → Moduły.

Jak czytać tę instrukcję:

- **„W Termuxie”** = polecenie wpisujesz w aplikacji Termux na Redmi;
  **„Na M910q”** = w terminalu komputera BCM, w katalogu repozytorium
  (`cd /opt/bcm`);
- każde polecenie jest w osobnym bloku — kopiuj blok w całości,
  podmieniając wartości przykładowe (`<…>`, `+48XXXXXXXXX`, `AA:BB:…`)
  na własne;
- **NIESPRAWDZONE** = opisane według dokumentacji i kodu, ale jeszcze nie
  sprawdzone na tym telefonie i tym ROM-ie.

Powiązane: wdrożenie całej reszty w aucie (migracja ustawień, BIOS, audio,
główny telefon, lista przełączników) —
[`WDROZENIE_TESTOWE_TELEFON.md`](WDROZENIE_TESTOWE_TELEFON.md). Szczegóły
techniczne i powody każdego kroku: [`WDROZENIE_TESTOWE.md`](WDROZENIE_TESTOWE.md)
§5.7–§5.15 oraz nagłówek `tools/car_phone/termux/bcm_agent.py`.

---

## Spis treści

0. [Co przygotować](#0-co-przygotować)
1. [ROM i root](#1-rom-i-root)
2. [Pierwsze uruchomienie](#2-pierwsze-uruchomienie)
3. [Opcje programisty](#3-opcje-programisty)
4. [Aplikacje (tylko z F-Droid)](#4-aplikacje-tylko-z-f-droid)
5. [Android 13: tło, powiadomienia, bateria](#5-android-13-tło-powiadomienia-bateria)
6. [Serwer NMEA (pozycja GPS)](#6-serwer-nmea-pozycja-gps)
7. [SensorServer (czujniki i światło)](#7-sensorserver-czujniki-i-światło)
8. [Pierwsze podłączenie do M910q](#8-pierwsze-podłączenie-do-m910q)
9. [Agent BCM w Termuxie](#9-agent-bcm-w-termuxie)
10. [Agent i BCM: sekret, moduły, parowanie, SMS](#10-agent-i-bcm-sekret-moduły-parowanie-sms)
11. [„Zadzwoń 112” (`call112`)](#11-zadzwoń-112-call112)
12. [Alarm na postoju (`parking_guard`)](#12-alarm-na-postoju-parking_guard)
13. [Czuwanie kabiny (`cabin_watch`)](#13-czuwanie-kabiny-cabin_watch)
14. [Automatyczna jasność (`auto_brightness`)](#14-automatyczna-jasność-auto_brightness)
15. [Sprawdzenia na stole](#15-sprawdzenia-na-stole)
16. [Opcjonalnie: ACC (ochrona baterii)](#16-opcjonalnie-acc-ochrona-baterii)
17. [Opcjonalnie: hotspot dla pasażerów](#17-opcjonalnie-hotspot-dla-pasażerów)
18. [Montaż i zasilanie (skrót)](#18-montaż-i-zasilanie-skrót)
19. [Bezpieczeństwo telefonu](#19-bezpieczeństwo-telefonu)
20. [Gdy coś nie działa](#20-gdy-coś-nie-działa)

---

## 0. Co przygotować

- Redmi Note 8 Pro (begonia) z odblokowanym bootloaderem.
- **crDroid na Androidzie 13**, najlepiej **bez usług Google** (GApps).
  Kod BCM wymaga Androida 11 lub nowszego. Androidy 14–15 nie były
  sprawdzane (mocniej ograniczają pracę w tle).
- **Magisk** (root) — potrzebny do wyłączenia „phantom process killera”,
  do „Zadzwoń 112” na głośniku i do czuwania kabiny.
- **Karta SIM** z SMS-ami i pakietem danych, **bez PIN-u**.
- Kabel **USB-C, ciągły 3 m, 3 A, żyły zasilania ≥ 22 AWG**. Bez przedłużek
  i bez końcówek magnetycznych.
- Dostęp do M910q (terminal z `sudo`) i do katalogu repozytorium BCM
  (`/opt/bcm`).
- Na **głównym** telefonie (Twoim, nie w aucie): aplikacja „authenticator”
  z F-Droid, np. **Aegis** — do kodów alarmu na postoju (§12).

## 1. ROM i root

1. Wgraj crDroid 13 dla begonia według instrukcji z jego strony (recovery,
   format danych). Nie wgrywaj pakietu GApps.
2. Wgraj Magisk i sprawdź, czy aplikacja Magisk pokazuje zainstalowany root.
3. Nie instaluj żadnych innych aplikacji niż te z tej instrukcji.

## 2. Pierwsze uruchomienie

- **Bez kont** (żadnego Google ani Mi).
- **Blokada ekranu: „Brak”** — nie PIN, nie wzór i nie przesunięcie, bo:
  - telefon z PIN-em po każdym restarcie czeka na pierwsze odblokowanie
    i dopiero wtedy uruchamia aplikacje — agent by nie wstał;
  - czuwanie kabiny (przednia kamera, §13) wymaga Termuxa na pierwszym
    planie bez blokady.
- **Wygaszanie ekranu: 15 s** — gdyby agent zginął w trakcie serii zdjęć,
  ekran sam zgaśnie.
- **PIN karty SIM wyłączony** — inaczej po restarcie telefon nie wyśle SMS-a.
- Data i godzina: **automatycznie z sieci**, strefa czasowa automatycznie
  (Europa/Warszawa). Podpisy między BCM a agentem mają okno ±60 s.
- **Wyłącz:** Bluetooth, NFC, Wi-Fi (Wi-Fi tylko, jeśli będzie hotspot dla
  pasażerów — §17), oszczędzanie baterii, „bateria adaptacyjna”.
- **Dane komórkowe włączone**, roaming danych wyłączony.
- **Lokalizacja włączona**, dokładna.
- Aktualizacje systemu (Ustawienia → System → Aktualizator): wyłącz
  automatyczne sprawdzanie i pobieranie.

## 3. Opcje programisty

Ustawienia → Informacje o telefonie → 7× „Numer kompilacji”. Potem
Ustawienia → System → Opcje programisty:

- **Debugowanie USB: włączone.**
- **„Disable adb authorization timeout”: włączone** — bez tego telefon po
  kilku dniach zapomina zgodę dla BCM.
- **Debugowanie bezprzewodowe: wyłączone.** BCM używa adb tylko po kablu.
- „Domyślna konfiguracja USB”: **Tethering USB** (opcjonalnie — zapas, BCM
  i tak sam włącza tethering).
- Jeśli jest pozycja **Feature flags → `settings_enable_monitor_phantom_procs`**,
  wyłącz ją (dalszy ciąg w §5).

## 4. Aplikacje (tylko z F-Droid)

Zainstaluj F-Droid (APK z f-droid.org), a z niego:

| Aplikacja | Po co |
|-----------|-------|
| **Termux** | środowisko dla agenta BCM |
| **Termux:API** | SMS, bateria, stan karty SIM, lokalizacja, aparat, czujniki |
| **Termux:Boot** | start agenta po włączeniu telefonu |
| **SensorServer** | strumień akcelerometru, żyroskopu i światła do BCM |
| **serwer NMEA TCP** | pozycja GPS do BCM (§6) |

> Termux, Termux:API i Termux:Boot muszą pochodzić z **tego samego źródła**
> (F-Droid) — mają wtedy ten sam podpis. Wersje ze Sklepu Play się z nimi
> nie dogadają. Tylko w wersji z buforem dochodzi **Termux:Widget** (skrót
> budzenia `wake.sh`, z tego samego źródła) — `ZASILANIE_BUFOROWANE.md`
> §14.6; w aucie testowym niepotrzebny.

Po instalacji **raz otwórz Termux:Boot** — Android pozwoli mu wtedy
startować przy włączeniu telefonu.

## 5. Android 13: tło, powiadomienia, bateria

1. **Wyłącz „phantom process killer”** — inaczej Android potrafi ubić
   procesy Termuxa w tle. W Termuxie (Magisk zapyta o zgodę dla Termux —
   zezwól):

   ```bash
   su -c '/system/bin/device_config set_sync_disabled_for_tests persistent'
   ```

   ```bash
   su -c '/system/bin/device_config put activity_manager max_phantom_processes 2147483647'
   ```

   Sprawdzenie (ma wypisać `2147483647`):

   ```bash
   su -c '/system/bin/device_config get activity_manager max_phantom_processes'
   ```

   Jeśli w Opcjach programisty nie było Feature flags, to samo ustawienie
   z linii poleceń (NIESPRAWDZONE na crDroid 13 — nie zaszkodzi):

   ```bash
   su -c 'settings put global settings_enable_monitor_phantom_procs false'
   ```

2. **Powiadomienia: zezwól** dla Termux, Termux:API, Termux:Boot,
   SensorServer i aplikacji NMEA (Android 13 pyta o nie osobno; bez nich
   usługi w tle są mniej odporne).
3. **Bateria → „Bez ograniczeń”** dla tych samych pięciu aplikacji
   (Ustawienia → Aplikacje → aplikacja → Bateria).

> Kroki „Xiaomi MIUI/HyperOS” z nagłówka `bcm_agent.py` (Autostart,
> „Wysyłanie SMS: Zezwalaj”, kłódka w ostatnich aplikacjach) na crDroid
> **nie dotyczą** — ich odpowiednikiem jest ten punkt.

## 6. Serwer NMEA (pozycja GPS)

Dowolna aplikacja, która wystawia zdania NMEA jako **serwer TCP** (np.
gpsdRelay z F-Droid — NIESPRAWDZONE, czy ma ten tryb; sprawdź przed
montażem). W niej:

- tryb **serwer TCP**, port **50000** (`network.car_phone.gps_remote_port`);
- adres nasłuchu **127.0.0.1**, jeśli aplikacja pozwala wybrać. BCM i tak
  czyta pozycję przez `adb forward`, a przy hotspocie dla pasażerów serwer
  na 0.0.0.0 pokazywałby pozycję auta każdemu podłączonemu;
- start przy uruchomieniu telefonu;
- uprawnienie lokalizacji: **„Zezwalaj zawsze”**, dokładna lokalizacja.

## 7. SensorServer (czujniki i światło)

- **Local Host: włączone** (serwer słucha tylko na 127.0.0.1 telefonu),
  port **8080** (`network.car_phone.sensors_remote_port`);
- **częstotliwość próbkowania: 10000 µs** (100 Hz). Domyślna jest dużo
  wolniejsza, a poniżej 80 Hz (`crash_detection.min_rate_hz`) BCM wyłącza
  wykrywanie stłuczki z akcelerometru;
- start serwera przy uruchomieniu telefonu.

**Czujnik światła** (dla `auto_brightness`, §14):

- BCM sam prosi SensorServer o akcelerometr, żyroskop i światło — najpierw
  w jednym połączeniu. Gdy telefon odrzuci to połączenie (albo 3 razy
  z rzędu zamknie je bez żadnego odczytu), BCM najpierw próbuje bez
  żyroskopu; przy kolejnej odmowie (albo od razu, gdy odmowa dotyczy
  światła lub akcelerometru) — **osobne połączenie dla każdego czujnika**.
  Na osobne połączenia przechodzi też, gdy przez 15 s nie przyjdzie ani
  jeden odczyt światła albo światło przychodzi, a akcelerometr nie. Wtedy
  brak światła nie wyłącza akcelerometru i odwrotnie. Ten tryb zostaje do
  restartu BCM; wiersz „Czujniki telefonu” pisze wtedy „osobne połączenie
  dla każdego czujnika”. Gdy telefon 3 razy z rzędu odrzuci samo światło,
  BCM przestaje o nie prosić do restartu („telefon odrzuca czujnik
  światła”);
- jeśli Twoja wersja SensorServer ma listę czujników do udostępniania
  (zakładka z czujnikami), **zaznacz na niej czujnik światła** (Light) —
  NIESPRAWDZONE, czy crDroid 13 / ta wersja aplikacji go w ogóle ukrywa;
- **praca w tle:** SensorServer z baterią „Bez ograniczeń” i bez
  optymalizacji baterii (§5). Czujnik światła działa na zdarzenie (wysyła
  odczyt tylko po zmianie jasności), więc przy wygaszonym ekranie crDroid
  może go wstrzymać — NIESPRAWDZONE na tym telefonie; sprawdź przyciskiem
  „Test” (niżej) raz z włączonym, raz z wygaszonym ekranem. Przy stałym
  świetle BCM powtarza ostatni odczyt, ale najwyżej przez 10 min od
  ostatniego odczytu z telefonu — potem jasność ekranu bierze LDR
  z Arduino (jeśli jest), a bez niego zostaje na obecnym poziomie, aż
  przyjdzie nowy odczyt;
- czujnik siedzi przy przedniej kamerze, na górnej krawędzi ekranu — uchwyt
  ani etui nie może go zasłaniać.

Sprawdzenie: Ustawienia BCM → wiersz **„Czujniki telefonu”** → **Test**.
Po 10 s wiersz pokazuje werdykt: „wszystko działa” albo co poprawić
(„brak odczytów światła — w SensorServer zaznacz czujnik światła i zezwól
na pracę w tle…”). Gdy przez 30 s nie przyjdzie żaden odczyt światła, BCM
zapisze raz w logu „SensorServer nie wysyła czujnika światła — sprawdź
w aplikacji, czy światło jest włączone / ekran”. Szczegóły:
`docs/WDROZENIE_TESTOWE_TELEFON.md` §10.2.

## 8. Pierwsze podłączenie do M910q

### 8.1 autoapp tylko bezprzewodowo — ZANIM podłączysz Redmi

autoapp (Android Auto) bez łatki wysyła handshake AA do **każdego**
urządzenia USB i przełączyłby Redmi w tryb akcesorium (koniec tetheringu
i GPS). Przebuduj autoapp w wersji tylko bezprzewodowej (na M910q, potrzebny
internet, kompilacja trwa długo).

> **Nie gaś silnika w trakcie.** W aucie testowym nie ma bufora: kluczyk
> odcina M910q w pół kompilacji albo w trakcie apt, a przerwany `dpkg`
> potrafi zostawić system, który się nie uruchamia. Silnik na chodzie na
> zewnątrz (nigdy w zamkniętym garażu) albo M910q na stole z oryginalnego
> zasilacza Lenovo 20 V; czekaj, aż wróci znak zachęty. Gdy prąd jednak
> zniknął: [`WDROZENIE_TESTOWE_TELEFON.md`](WDROZENIE_TESTOWE_TELEFON.md)
> §3.11, potem to samo polecenie jeszcze raz.

```bash
cd /opt/bcm && sudo BCM_AA_USB=0 bash config/scripts/install-openauto.sh --force
```

`adb` instalują `config/scripts/setup-x86.sh` i `config/scripts/apply-fixes.sh`.
Sprawdzenie (ma wypisać ścieżkę):

```bash
command -v adb
```

### 8.2 Zgoda adb

BCM uruchamia adb przez **własne gniazdo** w katalogu dostępnym tylko dla
roota (zwykłe `sudo adb` uruchamia drugi serwer na `127.0.0.1:5037`, który
walczy z BCM o telefon). Podłącz telefon. Na M910q:

```bash
sudo install -d -m 0700 /run/bcm-adb
```

```bash
sudo env ADB_SERVER_SOCKET=localfilesystem:/run/bcm-adb/adb.sock adb devices -l
```

Na telefonie: zaznacz **„Zawsze zezwalaj z tego komputera”** → OK.
Ponowne polecenie ma pokazać telefon w stanie `device`.

Wygodny alias (dopisz do `~/.bashrc` na M910q):

```bash
alias bcm-adb='sudo env ADB_SERVER_SOCKET=localfilesystem:/run/bcm-adb/adb.sock adb'
```

Jeśli kiedyś uruchomiłeś zwykłe `sudo adb …` i telefon „skacze” między
stanami, zamknij drugi serwer:

```bash
sudo adb kill-server
```

Dwa telefony z Androidem na USB naraz: wpisz serial z `bcm-adb devices -l`
do `network.car_phone.serial` w `config/local.yaml` (bez tego moduł
`car_phone` nic nie robi i pokazuje podpowiedź).

## 9. Agent BCM w Termuxie

Jeden agent (`tools/car_phone/termux/bcm_agent.py`, sam Python z biblioteką
standardową) obsługuje SMS po stłuczce, „Zadzwoń 112”, alarm na postoju
i czuwanie kabiny. Słucha tylko na 127.0.0.1:8765 telefonu; BCM łączy się
z nim przez forward adb (port 952 na M910q).

### 9.1 Pakiety

W Termuxie:

```bash
pkg install python termux-api
```

```bash
termux-setup-storage
```

(drugie polecenie da Termuxowi dostęp do folderu Pobrane — zezwól).

Opcjonalnie, tylko dla czuwania kabiny (analiza zdjęć i usuwanie EXIF
przez przekodowanie; bez niego agent działa tak samo, a analiza jest
pomijana). To pakiet Termuxa, **nie** pip:

```bash
pkg install python-pillow
```

### 9.2 Pliki agenta z M910q na telefon

Na M910q (telefon podłączony i zatwierdzony, §8.2):

```bash
cd /opt/bcm && sudo env ADB_SERVER_SOCKET=localfilesystem:/run/bcm-adb/adb.sock adb push tools/car_phone/termux/bcm_agent.py tools/car_phone/termux/boot_bcm_agent.sh /sdcard/Download/
```

Potem w Termuxie:

```bash
mkdir -p ~/bcm_agent ~/.termux/boot
```

```bash
cp ~/storage/downloads/bcm_agent.py ~/bcm_agent/
```

```bash
cp ~/storage/downloads/boot_bcm_agent.sh ~/.termux/boot/ && chmod 700 ~/.termux/boot/boot_bcm_agent.sh
```

### 9.3 Uprawnienia Termux:API

Ustawienia → Aplikacje → Termux:API → Uprawnienia:

| Uprawnienie | Po co |
|-------------|-------|
| **SMS** (wysyłanie i odczyt) | SMS po stłuczce, potwierdzenie w „wysłanych”, polecenia SMS alarmu na postoju |
| **Telefon** | stan karty SIM i slot |
| **Lokalizacja: „Zezwalaj cały czas”** | pozycja w SMS-ach alarmu na postoju (bez „cały czas” `termux-location` w tle nic nie zwraca) |
| **Aparat** | tylko czuwanie kabiny (§13) |

Pierwszy SMS wyślij ręcznie, żeby zaakceptować okno zgody (to prawdziwy SMS —
na własny numer):

```bash
termux-sms-send -n +48XXXXXXXXX "test"
```

Stan karty SIM (sprawdzenie uprawnienia „Telefon”):

```bash
termux-telephony-deviceinfo
```

### 9.4 Start

Zrestartuj telefon. Termux:Boot uruchomi agenta (z `termux-wake-lock`,
restart po 10 s, gdy agent się wywróci). Sprawdzenie w Termuxie:

```bash
tail -n 20 ~/.config/bcm_agent/agent.log
```

Błędy startu Pythona trafiają do `~/.config/bcm_agent/boot.log`. Ręczny
start do testów (tylko gdy agent z Termux:Boot nie działa — inaczej port
8765 jest zajęty):

```bash
python ~/bcm_agent/bcm_agent.py -v
```

### 9.5 Aktualizacja agenta

Po każdej aktualizacji BCM, która zmienia `tools/car_phone/termux/bcm_agent.py`:
znowu `adb push` z §9.2 i `cp` do `~/bcm_agent/`, potem w Termuxie:

```bash
pkill -f bcm_agent.py
```

Pętla w `boot_bcm_agent.sh` uruchomi nowego agenta po 10 s. Sekret, nonce,
zdarzenia, parowanie i sekret TOTP w `~/.config/bcm_agent` zostają. Wiersz
„Agent w telefonie” w Ustawieniach pokazuje wersję. Wymagane wersje:
„Zadzwoń 112” ≥ 1.1.0, alarm na postoju ≥ 1.2.0, czuwanie kabiny ≥ 1.3.0,
budzenie podczerwienią (wersja z buforem) ≥ 1.4.0, pozycja na serwerze
Traccar (`traccar`) ≥ 1.6.0 (obecna: 1.6.0). Starszy agent przy włączonym
module = „agent w telefonie jest starszy niż BCM” albo „agent w telefonie
jest za stary”. Wersja 1.5.0 nie jest wymagana, ale zaktualizuj: dopiero
ona pilnuje dalej, gdy ktoś wyłączy alarm w Ustawieniach → Moduły przy
uzbrojonym, i nie uzbraja się sama po wypadku (szczegóły:
[WDROZENIE_TESTOWE.md](WDROZENIE_TESTOWE.md) §5.12).

**Aktualizacja do 1.6.0 (Traccar).** Kroki jak wyżej (`adb push`, `cp`,
`pkill -f bcm_agent.py`). Agent 1.6.0 jako pierwszy łączy się z internetem
sam: tylko HTTPS na adres z `traccar.url`, tylko przy włączonym module
`traccar` w BCM. Nic nie trzeba doinstalowywać — wystarczy Python z
Termuxa (certyfikaty CA są w pakiecie `ca-certificates`, instalowanym razem
z `python`; gdy `pkg upgrade` dawno nie był robiony, zrób go). Kolejka
punktów bez zasięgu leży w `~/.config/bcm_agent/traccar_queue.json` (0600,
najwyżej 500 punktów). Konfiguracja serwera i identyfikatora:
[TRACCAR_SERWER.md](TRACCAR_SERWER.md) §8.

## 10. Agent i BCM: sekret, moduły, parowanie, SMS

### 10.1 Sekret agenta (na M910q)

Wygeneruj sekret:

```bash
python3 -c 'import secrets;print(secrets.token_hex(32))'
```

Dopisz go do `/etc/bcm/bcm.env` (plik `0600`, właściciel root):

```bash
sudo nano /etc/bcm/bcm.env
```

jako linię `BCM_CAR_PHONE_AGENT_SECRET=<wygenerowany ciąg>`. Nigdy do
YAML-a ani do `config/local.yaml` (BCM go tam nie zapisze). Zmiana sekretu =
parowanie od nowa.

### 10.2 Moduły

Ustawienia → Moduły, po kolei (Ustawienia same zaproponują zależności):

1. `car_phone` — internet, GPS, bateria, czas;
2. `phone_sensors` — czujniki;
3. `car_phone_agent` — agent;
4. `crash_sms` — SMS po stłuczce (wymaga też `crash_detect`, w configu
   testowym już włączonego).

Opcjonalnie `car_phone_hotspot` (stan hotspotu w wierszu „Telefon
w aucie”). Moduły 112, postoju, kabiny i jasności — §11–§14. Po zmianach
**restart BCM**:

```bash
sudo systemctl restart bcm-headunit
```

### 10.3 Parowanie agenta

W Termuxie:

```bash
python ~/bcm_agent/bcm_agent.py --pair
```

Wypisze **10-cyfrowy kod**. Na ekranie auta: Ustawienia → „Agent
w telefonie” → wpisz kod → **Sparuj** (działa tylko z ekranu auta, nie
z sieci). Po 5 złych kodach trzeba wygenerować nowy (`--pair` jeszcze raz).
Wiersz pokaże stan, wersję agenta, kartę SIM i godzinę ostatniego kontaktu.

„Sparuj mimo to” pojawia się, gdy agent, z którym BCM już raz się sparował,
nagle „nie zna sekretu” — używaj go tylko, gdy wiesz dlaczego (np. po
przeinstalowaniu Termuxa). Inaczej na porcie agenta odpowiada inna aplikacja.

### 10.4 Odbiorcy SMS i test

Ustawienia → „SMS po stłuczce”:

1. **Odbiorcy** — do 3 numerów, z kierunkowym kraju: polski numer jako
   `48` i 9 cyfr **Twojego** numeru, np. `48 6XX XXX XXX` (pole ma już
   „+”). Samo 9 cyfr jest odrzucane.
   „Zapisz odbiorców”.
2. **„Wyślij testowy SMS”** — dwa stuknięcia (to prawdziwy SMS do
   wszystkich odbiorców). Uprzedź ich wcześniej.

Tryb testowy (`crash_detection.sms.dry_run: true`) zostaje, dopóki sam go
nie wyłączysz w `config/local.yaml`. Nawet wtedy prawdziwe SMS-y wychodzą
tylko przy sparowanym, zdrowym agencie i teście potwierdzonym w „wysłanych”
w ciągu 30 dni dla **obecnych** odbiorców (każda zmiana listy kasuje
potwierdzenie). Opis okna z odliczaniem: `docs/WDROZENIE_TESTOWE.md` §5.10.

## 11. „Zadzwoń 112” (`call112`)

Przycisk w oknie wypadku na ekranie auta — **zawsze ręcznie**, przytrzymanie
2 s. Droga „telefon w aucie, głośnik” to Redmi: BCM wysyła agentowi
podpisane żądanie **bez numeru**, a agent przez Magisk `su` uruchamia stałe
polecenie wybierania z numerem wpisanym w swój kod (w trybie testowym —
z numerem testowym). Pełny opis: `docs/WDROZENIE_TESTOWE.md` §5.11.

**Nigdy nie testuj prawdziwym 112.** Do testów jest tryb testowy z numerem
zaufanej osoby, która wie o teście.

W telefonie:

1. Agent ≥ 1.1.0 (§9.5).
2. Magisk → Superużytkownik → **Termux: zezwól** (tylko Termux — żadna
   inna aplikacja nie dostaje roota). Tam też wyłącz powiadomienia i logi
   dla Termuxa (agent sprawdza `su` co 10 min, a w trakcie rozmowy co 2 s).
3. Sprawdzenie w Termuxie — ma wypisać `0`:

   ```bash
   su -c 'id -u'
   ```

W BCM (opis bezpiecznej edycji `config/local.yaml`:
[`WDROZENIE_TESTOWE_TELEFON.md`](WDROZENIE_TESTOWE_TELEFON.md) §2):

1. W `config/local.yaml` numer testowy i opis auta (nigdy do repo).
   **Wpisz własny numer testowy** — zaufanej osoby, która wie o teście;
   wartość przykładowa `+48XXXXXXXXX` nie przejdzie walidacji (wiersz
   pokaże „112: niegotowy (su / numer testowy)”):

   ```yaml
   safety:
     call112:
       test_number: '+48XXXXXXXXX'   # wpisz własny; E.164: '+', kierunkowy, 8–15 cyfr
     vehicle:
       label: Alfa Romeo 156         # do 32 znaków
       colour: czerwona              # do 20 znaków
       plate: WX 12345               # litery, cyfry, spacja, '-', do 12 znaków
   ```

   `safety.call112.test_mode: true` jest w obu configach w repo i **zostaje**,
   dopóki wszystko nie przejdzie testów.
2. Ustawienia → Moduły → `call112` (wymaga `crash_detect` oraz
   `car_phone_agent` albo `bluetooth`), restart BCM.
3. Wiersz „Agent w telefonie” pokazuje „112: gotowy (test)”. „112: niegotowy
   (su / numer testowy)” = brak roota dla Termuxa albo brak numeru testowego.
4. Test na stole (okno wypadku bez wypadku, numer testowy) —
   [`WDROZENIE_TESTOWE_TELEFON.md`](WDROZENIE_TESTOWE_TELEFON.md) §9.5.

NIESPRAWDZONE na crDroid 13 (sprawdzisz numerem testowym): czy intencja
z `START_CALL_WITH_SPEAKERPHONE` włącza głośnik, czy agent podnosi
głośność rozmowy (`cmd media_session volume`), czy telefon pokazuje stan
rozmowy (`dumpsys telephony.registry`) i czy „Rozłącz” z ekranu auta kończy
rozmowę. Custom ROM-y na MediaTeku często nie mają VoLTE — rozmowa idzie
wtedy przez 2G.

## 12. Alarm na postoju (`parking_guard`)

Na postoju BCM nie działa — w aucie testowym zgaszenie silnika odcina prąd
M910q i zasilanie USB telefonu. Alarm działa więc **w telefonie**: po ok.
5 min bez prądu i bez kontaktu z BCM telefon sam się uzbraja, pilnuje
przechyłu i wstrząsów akcelerometrem, odpowiada na polecenia SMS z Twoich
numerów i wysyła SMS alarmowy z pozycją. Rozbraja go tylko dowód właściciela:
Twój telefon połączony z BCM przez Bluetooth z rozmowami (HFP — samo
„połączony” bez HFP się nie liczy), SMS `PARK OFF <kod>` albo kod wpisany
w wierszu „Postój”. Wyłączenie alarmu w Ustawieniach → Moduły przy
uzbrojonym NIE rozbraja (agent ≥ 1.5.0 pilnuje dalej do rozbrojenia), a po
wypadku i 112 telefon przez 6 h sam się nie uzbraja. Pełny opis (okno
wejścia, limity, bateria): `docs/WDROZENIE_TESTOWE.md` §5.12.

W telefonie:

1. Agent ≥ 1.2.0 (§9.5).
2. Uprawnienia Termux:API: **SMS** i **Lokalizacja: „Zezwalaj cały czas”**
   (§9.3).
3. Sekret kodów TOTP — w Termuxie:

   ```bash
   python ~/bcm_agent/bcm_agent.py --park-setup
   ```

   Polecenie wypisze adres `otpauth://…` i sam sekret. Dodaj go w aplikacji
   authenticator na **swoim głównym** telefonie (Aegis: wklej adres albo
   wpisz sekret ręcznie — TOTP, SHA1, 6 cyfr, 30 s). Nie zostawiaj go na
   Redmi: telefon w aucie nie ma blokady ekranu. Sekret leży w
   `~/.config/bcm_agent/park_totp` (0600) i nie trafia do logu. Drugie
   `--park-setup` pokazuje ten sam sekret; nowy (stary kod w aplikacji
   przestaje działać):

   ```bash
   python ~/bcm_agent/bcm_agent.py --park-setup --new
   ```

4. (Opcjonalnie) numery ustawione w samym telefonie, gdy BCM nie wysyła
   własnych (BCM ma pierwszeństwo; `''` czyści listę). **Wymagane** dla
   SMS `WAKE` w wersji z buforem, gdy alarm na postoju jest wyłączony — BCM
   wysyła numery tylko z `modules.parking_guard`. **Wpisz własne
   numery** (do 3, po przecinku) — z wartością przykładową agent odmówi:

   ```bash
   python ~/bcm_agent/bcm_agent.py --park-numbers '+48XXXXXXXXX'
   ```

W BCM:

1. Ustawienia → Moduły: `car_phone`, `car_phone_agent`, `parking_guard`;
   restart BCM.
2. W `config/local.yaml` (nigdy w repo — dane osobowe) **wpisz własny
   numer** i adres Bluetooth swojego telefonu w miejsce przykładowych:

   ```yaml
   parking_guard:
     numbers: ['+48XXXXXXXXX']            # wpisz własny; ≤ 3, E.164: alarm i polecenia SMS
     owner_macs: ['AA:BB:CC:DD:EE:FF']    # Twój telefon (Bluetooth), ≤ 4
     home: {lat: 52.2297, lon: 21.0122, radius_m: 150}   # opcjonalnie, ≥ 50 m
   ```

   Adres Bluetooth swojego telefonu znajdziesz w telefonie (Ustawienia →
   Informacje o telefonie) albo na M910q na liście znanych urządzeń:

   ```bash
   bluetoothctl devices
   ```

3. **Pierwszy tydzień `parking_guard.log_only: true`** (tak jest w kodzie
   i w configu testowym): wyzwalacze trafiają tylko do logu agenta
   (`PARK (log only, no SMS): …` w `~/.config/bcm_agent/agent.log`),
   automatyczne SMS-y nie wychodzą. Po tygodniu porównaj zdarzenia z tym,
   co się działo, w razie potrzeby dostrój `parking_guard.tilt_deg`
   i `parking_guard.shake_k` i dopiero wtedy wpisz w `config/local.yaml`
   `log_only: false` w bloku `parking_guard`.

Polecenia SMS (z numeru z listy, zawsze z 6-cyfrowym kodem z aplikacji):
`POZYCJA <kod>` (albo `GDZIE <kod>`), `PARK ON <kod>`, `PARK OFF <kod>`,
`PARK STATUS <kod>`. Wielkość liter i spacje bez znaczenia. Ten sam kod nie
przejdzie drugi raz.

Sprawdzenie na stole (kabel odłączony = postój):
`docs/WDROZENIE_TESTOWE.md` §5.12, „Sprawdzenie na stole”.

Bateria na postoju (szacunek, NIESPRAWDZONE): ok. 1–2% na godzinę; po dobie
albo poniżej 30% wersja „lekka”, poniżej 15% rozbrojenie z jednym SMS-em.

## 13. Czuwanie kabiny (`cabin_watch`)

Warstwa nad alarmem na postoju: gdy telefon jest uzbrojony, przy wejściu do
auta (lampka sufitowa + ruch, przechył) robi 3 zdjęcia przednią kamerą
(telefon wisi ekranem w dół, więc kamera i czujnik światła patrzą w kabinę)
i wysyła SMS „RUCH W KABINIE”. Kamera działa **tylko przy uzbrojonym**
alarmie, nigdy dźwięk. Zdjęcia **zostają w telefonie** — nie trafiają do
BCM ani nigdzie dalej. Pełny opis: `docs/WDROZENIE_TESTOWE.md` §5.13.

W telefonie:

1. Agent ≥ 1.3.0 (§9.5).
2. Uprawnienie Termux:API **Aparat** (§9.3); pierwsze `termux-camera-photo`
   wywołaj ręcznie (krok 6).
3. Magisk `su` dla Termuxa z wyłączonymi powiadomieniami (jak w §11).
4. Blokada ekranu **„Brak”** i wygaszanie po **15 s** (§2).
5. **Wyłącz każde inne budzenie ekranu** (Ustawienia crDroid → Wyświetlacz
   i tam, gdzie ROM je trzyma — nazwy różnią się między wersjami):
   wyświetlacz otoczenia (Ambient display / „zawsze włączony”), budzenie
   przy nowych powiadomieniach, „podnieś, aby wybudzić”, dwukrotne
   dotknięcie, budzenie po podłączeniu ładowarki. Czujnik światła jest po
   stronie ekranu: każde takie zapalenie ekranu to dla agenta „skok
   światła”.
6. **Id przedniej kamery** — w Termuxie; szukaj wpisu z
   `"facing": "front"` (zwykle `"id": "1"`):

   ```bash
   termux-camera-info
   ```

7. **Zdjęcie przy wygaszonym ekranie, po restarcie telefonu.** Zrestartuj
   telefon, poczekaj, aż agent wstanie, otwórz Termux i wpisz to, co robi
   agent, z minutą zwłoki na początku (`1` = id z kroku 6):

   ```bash
   sleep 60; su -c 'input keyevent KEYCODE_WAKEUP'; su -c 'am start -W -a android.intent.action.MAIN -c android.intent.category.LAUNCHER com.termux'; termux-camera-photo -c 1 ~/test.jpg; su -c 'input keyevent KEYCODE_SLEEP'
   ```

   Po Enterze naciśnij „Home” (Termux w tle, jak na postoju) i wygaś ekran
   przyciskiem. Po ok. minucie ekran sam się zapali, Termux wyjdzie na
   wierzch, a po zdjęciu ekran zgaśnie. Plik musi mieć ponad 0 bajtów:

   ```bash
   ls -l ~/test.jpg
   ```

   Obejrzyj go — w tym kadrze ustalisz maskę okien (`cabin_watch.mask`) —
   i usuń:

   ```bash
   termux-open ~/test.jpg
   ```

   ```bash
   rm ~/test.jpg
   ```

8. **Czujnik światła przy wygaszonym ekranie.** Nazwa czujnika (szukaj
   „Light”):

   ```bash
   termux-sensor -l
   ```

   Potem, przy wygaszonym ekranie, 10 odczytów (wstaw nazwę z poprzedniego
   polecenia) i zapal lampkę sufitową — wartości muszą skoczyć z kilku do
   kilkudziesięciu lux:

   ```bash
   termux-sensor -s '<nazwa czujnika światła>' -d 1000 -n 10
   ```

   Na koniec zwolnij czujnik:

   ```bash
   termux-sensor -c
   ```

   Jeśli czujnik przy wygaszonym ekranie milczy, zdjęcia dają już tylko
   przechył i ok. 20 s kołysania — alarm na postoju i tak wyśle SMS
   „wstrząs”.
9. (Opcjonalnie) Pillow — `pkg install python-pillow` (§9.1). Bez niego
   wiersz „Czuwanie kabiny” pokazuje „bez analizy zdjęć — w Termuxie: pkg
   install python-pillow”; SMS nigdy nie czeka na analizę.

W BCM: Ustawienia → Moduły: `car_phone`, `car_phone_agent`, `parking_guard`,
`cabin_watch`; restart BCM. Progi i maskę (`cabin_watch.entry_s`,
`cabin_watch.diff_pct`, `cabin_watch.mask`, `cabin_watch.light_ratio`,
`cabin_watch.light_lux`) opisuje `docs/WDROZENIE_TESTOWE.md` §5.13 —
maskę wpisz dopiero po obejrzeniu zdjęcia z kroku 7. Pierwszy tydzień
`parking_guard.log_only: true` obowiązuje też tu: zdjęcia tak, SMS-a nie.

**Prywatność** (to nie jest porada prawna):

- naklejka informacyjna na szybie (np. „Pojazd monitorowany — kamera
  w kabinie”) i **poinformuj domowników**, że auto robi zdjęcia kabiny;
- wyjątek RODO dla celów czysto osobistych jest prawdopodobny, ale wąski;
  zdjęcia bliskich bez ich wiedzy to realne ryzyko (art. 267 §3 i 191a
  k.k.);
- dowód właściciela w oknie wejścia **usuwa** zdjęcia tego zdarzenia;
  pozostałe są kasowane po 72 h (najwyżej 200 MB);
- skradziony telefon (blokada „Brak”!) ujawnia zdjęcia z ostatnich 72 h
  i sekrety agenta.

## 14. Automatyczna jasność (`auto_brightness`)

W telefonie **nic więcej** poza ustawieniami z §7 (praca w tle,
niezasłonięty czujnik); lux działa niezależnie od akcelerometru. W BCM: Ustawienia → Moduły → `auto_brightness` (wymaga
`phone_sensors` albo `input`), restart BCM. Po starcie w Ustawieniach
pojawia się wiersz „Jasność ekranu”, np. „Auto (telefon) · 120 lx · 47%”.
Sprawdzenie: zasłoń czujnik telefonu dłonią — po kilku sekundach ekran BCM
ciemnieje. Czujnik pod podsufitką patrzy w kabinę, nie na drogę — w tunelu
i pod latarniami może reagować inaczej niż oczy kierowcy (NIESPRAWDZONE
w aucie). Reszta (krzywa, ściemnianie programowe / DDC/CI):
`docs/WDROZENIE_TESTOWE.md` §5.14.

## 15. Sprawdzenia na stole

Zanim telefon trafi pod podsufitkę:

- [ ] Wiersz **„Telefon w aucie”** w Ustawieniach: „połączono”, IP,
      bateria, °C, GPS — i internet w BCM działa przez Redmi.
- [ ] **GPS**: wiersz GPS w Ustawieniach pokazuje „jest pozycja”.
- [ ] **SensorServer ~100 Hz**: w logu BCM przejście
      `Phone sensors: connecting -> streaming` (także przy wygaszonym
      ekranie telefonu). Po potwierdzonym testowym SMS-ie wiersz „SMS po
      stłuczce” nie może pokazywać „za wolne próbkowanie czujników” ani
      „brak danych z czujników telefonu” (dokładnej częstotliwości
      Ustawienia nie pokazują).

      ```bash
      sudo journalctl -u bcm-headunit -b | grep "Phone sensors"
      ```

- [ ] **Zakres akcelerometru**: BCM uznaje oś za nasyconą przy 98%
      `sensors.phone.accel_range_g` (domyślnie 8 g) — to wpływa na
      wykrywanie stłuczki. Lista czujników telefonu:

      ```bash
      sudo env ADB_SERVER_SOCKET=localfilesystem:/run/bcm-adb/adb.sock adb shell dumpsys sensorservice
      ```

      Szukaj wiersza akcelerometru (`android.sensor.accelerometer`). Jeśli
      podaje zakres (`maxRange`, w m/s²: 8 g ≈ 78,5), a ten jest inny niż
      8 g, wpisz go w g jako `sensors.phone.accel_range_g` do
      `config/local.yaml` (BCM zatrzymany). Po restarcie BCM w logu nie
      może być ostrzeżenia `… the accelerometer crash path can never
      trigger` (za mały zakres na progi stłuczki). NIESPRAWDZONE, czy
      crDroid 13 wypisuje tam zakres — jeśli nie, zostaw 8 g.

- [ ] **Kalibracja**: po ~10 s postoju (silnik na wolnych obrotach
      wystarczy) w tym samym logu `Phone sensors: gravity reference saved`;
      wiersz „SMS po stłuczce” nie pokazuje „czujniki telefonu
      nieskalibrowane”.
- [ ] **Agent**: wiersz „Agent w telefonie” = „działa”; po restarcie
      telefonu sam wraca do „działa”.
- [ ] **SMS**: testowy SMS dochodzi; w Termuxie lista pokazuje go jako
      wysłany:

      ```bash
      termux-sms-list -t all -l 5
      ```

- [ ] **Zwykłe połączenie** z karty w Redmi (nigdy próbnie na 112) —
      VoLTE albo 2G.
- [ ] **112 numerem testowym** (§11) — głośnik, głośność, „Rozłącz”.
- [ ] **Alarm na postoju** w `log_only` (§12) — odpowiedź na
      `PARK STATUS <kod>`.
- [ ] **Kamera przednia** przy wygaszonym ekranie (§13, krok 7) i czujnik
      światła (krok 8).
- [ ] **Nadajnik IR** (przyda się do wybudzania BCM w wersji z buforem):
      `termux-infrared-frequencies` zwraca listę (z 38000 w zakresie).
      Samo wybudzanie — SMS `WAKE <kod>` albo skrót Termux:Widget
      `wake.sh`, razem z instalacją skrótu — opisuje
      `ZASILANIE_BUFOROWANE.md` §14.6; w aucie testowym bez bufora nie ma
      czego budzić.
- [ ] **Prąd ładowania** z portu M910q (port daje tylko ~500 mA, §18):

      ```bash
      sudo env ADB_SERVER_SOCKET=localfilesystem:/run/bcm-adb/adb.sock adb shell dumpsys battery
      ```

- [ ] **Zasięg GPS** w miejscu montażu: porównaj liczbę satelitów w aucie
      i na zewnątrz, zanim zaczniesz wiercić.

## 16. Opcjonalnie: ACC (ochrona baterii)

Moduł Magiska **ACC** (Advanced Charging Controller) trzyma baterię
w oknie ładowania (np. 40–60 %) i ogranicza temperaturę ładowania
(45–50 °C). Telefon wisi na zasilaniu, więc to wydłuża życie baterii.
`acc -t` sprawdza, czy kernel tego telefonu obsługuje przełączanie
ładowania (MT6785 — NIESPRAWDZONE). Ustawienia według dokumentacji ACC.
Przy ograniczniku ładowania alarm na postoju dalej patrzy na pole `plugged`
z `termux-battery-status` (NIESPRAWDZONE z ACC).

## 17. Opcjonalnie: hotspot dla pasażerów

Ustawienia → Sieć → Hotspot: własny SSID, **WPA2/WPA3**, mocne hasło,
automatyczne wyłączanie hotspotu wyłączone. Android pozwala na tethering
USB i hotspot naraz. Pilnuj, żeby SensorServer i serwer NMEA słuchały
tylko na 127.0.0.1 (§6 i §7) — inaczej podłączeni widzą pozycję
i czujniki. W BCM moduł `car_phone_hotspot` tylko pokazuje stan hotspotu
w wierszu „Telefon w aucie”.

## 18. Montaż i zasilanie (skrót)

- **Miejsce**: belka nad szybą, środek, tuż po stronie pasażera od
  lusterka; nie może zasłaniać widoku ani kamery za lusterkiem.
  Telefon poziomo, **ekranem w dół**, górną krawędzią (GPS, IR) do szyby.
- **Sztywno** (od tego zależy akcelerometr): płytka aluminiowa 2–3 mm
  przykręcona do istniejących punktów, sztywna kołyska z blokadą; bez
  przyssawek, magnesów i rzepów. Po przełożeniu telefonu skasuj kalibrację
  na M910q (BCM zatrzymany, inaczej zapisze ją z powrotem):

  ```bash
  sudo systemctl stop bcm-ignition-watcher bcm-headunit
  ```

  ```bash
  sudo rm -f /opt/bcm/data/phone_sensors.json
  ```

  ```bash
  sudo systemctl start bcm-ignition-watcher bcm-headunit
  ```

- **Poduszki powietrzne**: sprawdź, czy auto ma kurtyny; wszystko
  w promieniu ±25 cm od lusterka, kabel nigdy między poduszką a tapicerką.
- **Zasilanie**: port M910q daje ~500 mA i gaśnie razem z autem. Na stałe —
  **wstrzykiwacz zasilania** przy M910q: mała przetwornica 12 → 5 V
  ustawiona na 5,1–5,2 V (moduł bezmarkowy — po zakupie zmierz napięcie bez
  obciążenia i przy ~1 A), wpięta w żyłę VBUS kabla telefonu, z **odciętym
  VBUS od strony komputera** (dane zostają na USB), przed nią bezpiecznik
  2 A. Skąd bierze 12 V, zależy od wersji:
  - **auto testowe (bez bufora) — z obwodu zapłonu** (to samo, co gaśnie
    z autem), nigdy ze stałego 12 V: alarm na postoju i czuwanie kabiny
    uzbrajają się same właśnie po UTRACIE zasilania USB
    (`WDROZENIE_TESTOWE.md` §5.12). Telefon zasilany na postoju stale
    zostaje „podłączony” i sam się nie uzbroi, a uzbrajania przez BCM przy
    zgaszeniu (wersja z buforem) w tej wersji nie ma;
  - **wersja z buforem — opcjonalnie z szyny za LVD** przez wkładkę **F13
    2 A** w bagażniku i przewód 0,75 mm² do przodu
    (`ZASILANIE_BUFOROWANE.md` §8.1, §8a.2). Tylko wtedy telefon może
    budzić komputer podczerwienią na postoju (`ZASILANIE_BUFOROWANE.md`
    §14.6), ale dokłada swój pobór do budżetu postoju (§9.1 tamże) i — jak
    wyżej — nie uzbroi się sam po utracie zasilania.
- **Ciepło**: osłona przeciwsłoneczna na postoju, szczelina ≥ 10 mm. BCM
  ostrzega przy 45 °C i alarmuje przy 50 °C (`network.car_phone.warn_temp_c`,
  `network.car_phone.critical_temp_c`). Jeśli latem często przekracza
  50 °C — przenieś telefon pod deskę.

## 19. Bezpieczeństwo telefonu

crDroid 13 raczej nie dostaje już poprawek bezpieczeństwa. Dla telefonu
tylko do auta to akceptowalne pod warunkiem, że:

- nie ma na nim żadnych kont;
- Bluetooth i NFC są wyłączone;
- ADB działa tylko po kablu (nigdy `adb tcpip`, debugowanie bezprzewodowe
  wyłączone);
- root (Magisk `su`) ma wyłącznie Termux;
- usługi (agent, SensorServer, serwer NMEA) słuchają tylko na 127.0.0.1;
- hotspot (jeśli jest) ma WPA2/WPA3 i mocne hasło.

Agent przyjmuje tylko żądania podpisane wspólnym sekretem; numer 112 jest
stałą w jego kodzie, a do SMS-ów i do `su` trafiają wyłącznie zwalidowane
numery i liczby — nigdy tekst z zewnątrz.

## 20. Gdy coś nie działa

| Objaw | Co zrobić |
|-------|-----------|
| „zezwól na debugowanie USB” / „odblokuj telefon i zaznacz »Zawsze zezwalaj«” | Na telefonie zaakceptuj zgodę dla debugowania USB (§8.2). |
| Telefon „skacze” online/offline | Drugi serwer adb: `sudo adb kill-server`, potem tylko `bcm-adb`. |
| „telefon nie włącza tetheringu USB” | Włącz „Domyślna konfiguracja USB: Tethering USB” (§3) albo sprawdź, czy operator nie blokuje tetheringu. |
| „autoapp przełącza telefon w tryb Android Auto” | Przebuduj autoapp bez USB (§8.1), odłącz i podłącz telefon. |
| „brak adb” | `sudo apt install adb` albo ponownie `config/scripts/apply-fixes.sh`. |
| Agent nie startuje po restarcie telefonu | `~/.config/bcm_agent/boot.log`; blokada ekranu „Brak”, Termux:Boot otwarty raz, phantom process killer (§5). |
| Agent znika po kilku godzinach | Phantom process killer nie jest wyłączony albo bateria nie „Bez ograniczeń” (§5). |
| „brak sekretu” | `BCM_CAR_PHONE_AGENT_SECRET` w `/etc/bcm/bcm.env` i restart BCM (§10.1). |
| „niesparowany” / „agent ma inny sekret” | W Termuxie `python ~/bcm_agent/bcm_agent.py --pair` i Sparuj (§10.3). |
| „agent nie zna już sekretu …” | Agent przeinstalowany albo inna aplikacja na porcie 8765 — sprawdź telefon; „Sparuj mimo to” tylko, gdy wiesz, czemu. |
| „zegar telefonu i BCM różni się o ponad minutę” | Data i godzina automatycznie z sieci (§2). |
| „agent w telefonie jest starszy niż BCM” / „za stary” | Aktualizacja agenta (§9.5). |
| Czujniki < 80 Hz | Próbkowanie SensorServer na 10000 µs (§7), bateria bez ograniczeń. |
| „Czujniki telefonu”: „światło: brak odczytu” / test „brak odczytów światła” | Czujnik światła w SensorServer, praca w tle, niezasłonięty czujnik; test z włączonym i z wygaszonym ekranem (§7). |
| „Czujniki telefonu”: „brak akcelerometru”, a światło jest | Akcelerometr zaznaczony w SensorServer? Stłuczka z akcelerometru nie działa, jasność tak (§7). |
| Brak GPS z telefonu | Aplikacja NMEA działa? Port 50000? Lokalizacja „Zezwalaj zawsze”? (§6) |
| „112: niegotowy (su / numer testowy)” | `su -c 'id -u'` musi dać `0` (§11); `safety.call112.test_number` w `config/local.yaml`. |
| „brak kodu TOTP …” w wierszu „Postój” | `python ~/bcm_agent/bcm_agent.py --park-setup` (§12). |
| „brak przedniej kamery — uprawnienie Aparat dla Termux:API?” | Uprawnienie Aparat (§9.3), potem `termux-camera-info` (§13). |
| Kabina: zdarzenia „światło” bez wejścia do auta | Inne budzenie ekranu nie jest wyłączone (§13, krok 5); progi `cabin_watch.light_ratio` / `cabin_watch.light_lux` stroisz w tygodniu `log_only` (`docs/WDROZENIE_TESTOWE.md` §5.13). |
