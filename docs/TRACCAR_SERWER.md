# Traccar — auto na mapie (serwer domowy + nginx)

Instrukcja postawienia własnego serwera [Traccar](https://www.traccar.org)
na domowym serwerze i wpięcia go w istniejący nginx z HTTPS na porcie 443.
Telefon w aucie (Redmi, agent BCM w Termuxie) wysyła pozycję na serwer,
a Ty oglądasz auto w aplikacji **Traccar Manager** albo w przeglądarce.

> Po stronie BCM i agenta obsługa Traccara powstaje w partii 12, etap 7.
> Klucze konfiguracyjne z §8 są docelowe — do tego czasu możesz postawić
> i przetestować serwer (§7) samym `curl`.

W tekście zamieniasz na swoje wartości:

| Znacznik | Co to jest | Przykład |
|---|---|---|
| `DOMENA` | Twoja domena z certyfikatem Let's Encrypt | `example.pl` |
| `TRACCAR_IP` | lokalny adres serwera Traccar (LXC/VM) albo `127.0.0.1` dla Dockera na tej samej maszynie co nginx | `192.168.1.50` |
| `NGINX_IP` | lokalny adres maszyny z nginx | `192.168.1.10` |
| `ID_AUTA` | losowy identyfikator urządzenia (§5) | `3f9c…` (32 znaki hex) |

## Spis treści

1. [Jak to działa](#1-jak-to-działa)
2. [Instalacja: LXC w Proxmoxie](#2-instalacja-lxc-w-proxmoxie)
3. [Instalacja: Docker](#3-instalacja-docker)
4. [Konfiguracja Traccara (`traccar.xml`)](#4-konfiguracja-traccara-traccarxml)
5. [Pierwsze logowanie i urządzenie „Alfa 156”](#5-pierwsze-logowanie-i-urządzenie-alfa-156)
6. [nginx: podkatalog dla pozycji + subdomena dla panelu](#6-nginx-podkatalog-dla-pozycji--subdomena-dla-panelu)
7. [Test bez auta](#7-test-bez-auta)
8. [Po stronie BCM i telefonu](#8-po-stronie-bcm-i-telefonu)
9. [Podgląd auta: Traccar Manager](#9-podgląd-auta-traccar-manager)
10. [Kopie, aktualizacje, rozwiązywanie problemów](#10-kopie-aktualizacje-rozwiązywanie-problemów)

## 1. Jak to działa

```
telefon w aucie ──HTTPS 443──► nginx ──/traccar-gps/──► TRACCAR_IP:5055  (pozycje, protokół OsmAnd)
Twój telefon    ──HTTPS 443──► nginx ──traccar.DOMENA──► TRACCAR_IP:8082 (panel www, Traccar Manager, WebSocket)
```

- **Pozycje** idą przez **podkatalog** na głównej domenie:
  `https://DOMENA/traccar-gps/?id=ID_AUTA&lat=…&lon=…&timestamp=…`.
  nginx obcina prefiks i przekazuje zapytanie na port 5055.
- **Panel** potrzebuje **własnej subdomeny** (`traccar.DOMENA`). Podkatalog
  tu nie zadziała, bo:
  - interfejs www Traccara woła swoje API ścieżkami bezwzględnymi
    (`/api/…`, WebSocket `/api/socket`), więc pod `/traccar/` zgubiłby
    połowę zapytań; oficjalnie Traccar nie wspiera pracy w podkatalogu;
  - jeśli na głównej domenie `/api/` jest już zajęte (np. przez Pi-hole v6),
    to nawet obejścia z `sub_filter` się z nim pogryzą;
  - aplikacja Traccar Manager przyjmuje tylko adres główny serwera.

  Subdomena to jeden rekord DNS i rozszerzenie certyfikatu (§6.4), a port
  zostaje ten sam — 443. Jeśli panelu nie chcesz wystawiać wcale, patrz
  §6.5 (tylko LAN/VPN).
- Na routerze **nie** otwierasz 5055 ani 8082. Z internetu widać tylko 443.

## 2. Instalacja: LXC w Proxmoxie

1. Utwórz kontener: szablon **Debian 12**, nieuprzywilejowany,
   1 vCPU, 1 GB RAM, 8 GB dysku, stały adres `TRACCAR_IP`.
2. W konsoli kontenera:

   ```bash
   apt update && apt install -y unzip wget ufw
   ```

3. Pobierz paczkę **Linux 64-bit** ze strony traccar.org/download (link
   z przycisku), rozpakuj i zainstaluj:

   ```bash
   unzip traccar-linux-64-*.zip && ./traccar.run
   ```

4. Ustaw `traccar.xml` (§4), potem:

   ```bash
   systemctl enable --now traccar
   ```

5. Zapora w kontenerze — porty tylko dla maszyny z nginx (i Twojego LAN-u
   do panelu, jeśli chcesz wchodzić bez proxy):

   ```bash
   ufw default deny incoming && ufw allow 22/tcp && ufw allow from NGINX_IP to any port 5055,8082 proto tcp && ufw enable
   ```

Dane: `/opt/traccar/data` (baza H2), konfiguracja: `/opt/traccar/conf/traccar.xml`,
logi: `/opt/traccar/logs`. Kopia = backup kontenera w Proxmoxie.

> Istnieją gotowe skrypty „jedną komendą” tworzące LXC z Traccarem
> (np. community-scripts). Działają, ale uruchamiasz cudzy skrypt jako root
> na hoście Proxmoxa. Ręcznie to te same kroki co wyżej.

## 3. Instalacja: Docker

Gdy Traccar stoi na tej samej maszynie co nginx, wystaw porty **tylko na
127.0.0.1** (wtedy `TRACCAR_IP` = `127.0.0.1` i zapora nie jest potrzebna).

```bash
sudo mkdir -p /opt/traccar/logs /opt/traccar/data && docker run --rm --entrypoint cat traccar/traccar:latest /opt/traccar/conf/traccar.xml | sudo tee /opt/traccar/traccar.xml
```

Popraw `/opt/traccar/traccar.xml` (§4), potem uruchom. Zamiast `latest`
wpisz konkretną wersję z Docker Hub, żeby aktualizacja nie przyszła sama:

```bash
docker run -d --name traccar --restart unless-stopped \
  -p 127.0.0.1:8082:8082 -p 127.0.0.1:5055:5055 \
  -v /opt/traccar/logs:/opt/traccar/logs \
  -v /opt/traccar/data:/opt/traccar/data \
  -v /opt/traccar/traccar.xml:/opt/traccar/conf/traccar.xml:ro \
  traccar/traccar:latest
```

Gdy Docker stoi na innej maszynie niż nginx: `-p 8082:8082 -p 5055:5055`
i zapora jak w §2 pkt 5 (`ufw` na hoście Dockera nie filtruje portów
wystawionych przez Dockera — ogranicz je w `DOCKER-USER` albo zostań przy
`127.0.0.1` i proxy na tej samej maszynie).

## 4. Konfiguracja Traccara (`traccar.xml`)

Traccar domyślnie otwiera **kilkaset portów** — po jednym na każdy protokół
trackerów. Potrzebny jest tylko OsmAnd (5055). Dopisz w `<properties>`:

```xml
<!-- tylko protokół OsmAnd (HTTP, port 5055) - reszta portów zamknięta -->
<entry key='protocols.enable'>osmand</entry>
```

Resztę (baza H2, port panelu 8082) zostaw domyślną. Po zmianie:
`systemctl restart traccar` (LXC) albo `docker restart traccar`.

## 5. Pierwsze logowanie i urządzenie „Alfa 156”

1. Z sieci lokalnej otwórz `http://TRACCAR_IP:8082` (w Dockerze na
   127.0.0.1 — dopiero przez subdomenę z §6). Pierwsze konto, które
   założysz, jest administratorem — zrób to od razu, mocnym hasłem.
2. Ustawienia → Serwer: **wyłącz rejestrację** nowych użytkowników.
3. Jeśli Twoja wersja ma weryfikację dwuetapową (TOTP) w ustawieniach konta,
   włącz ją — panel będzie dostępny z internetu.
4. Wygeneruj identyfikator auta:

   ```bash
   openssl rand -hex 16
   ```

5. Urządzenia → Dodaj: nazwa `Alfa 156`, identyfikator = wynik z pkt 4.

**Identyfikator to jedyne zabezpieczenie wysyłania pozycji** — protokół
OsmAnd nie ma hasła. Kto go zna, może wpisywać auto w dowolne miejsce.
Dlatego: długi losowy ciąg, nigdzie w repozytorium, w BCM tylko w
`/etc/bcm/bcm.env` (§8), a nginx nie zapisuje go w logach (§6.2).

## 6. nginx: podkatalog dla pozycji + subdomena dla panelu

Wszystkie fragmenty wklejasz do istniejącego pliku strony
(`/etc/nginx/sites-available/…`). Po każdej zmianie:

```bash
sudo nginx -t && sudo systemctl reload nginx
```

### 6.1 Limit zapytań (poza blokami `server`)

Na górze pliku, obok innych `map`/`geo` (kontekst `http` — pliki z
`sites-enabled` są do niego dołączane):

```nginx
# Traccar: najwyżej 2 pozycje/s z jednego adresu IP (auto wysyła co kilka s)
limit_req_zone $binary_remote_addr zone=traccar_gps:1m rate=2r/s;
```

### 6.2 Pozycje z auta — podkatalog `/traccar-gps/` na głównej domenie

W bloku `server { listen 443 ssl; server_name DOMENA …; }`, obok innych
`location ^~ /…/` (kolejność w pliku nie ma znaczenia — `^~` wygrywa
z wyrażeniami regularnymi, np. obsługą `.php`):

```nginx
# ===== TRACCAR: pozycje z auta (OsmAnd -> port 5055) =====
# Telefon w aucie wysyła: GET /traccar-gps/?id=...&lat=...&lon=...&timestamp=...
location ^~ /traccar-gps/ {
    # Telefon w aucie nie ma ciasteczka bramki logowania (TOTP/auth_request
    # na poziomie serwera) - zabezpieczeniem jest losowy identyfikator urządzenia.
    auth_request off;

    # OsmAnd to tylko GET (pozycja w adresie) albo POST z krótkim ciałem.
    limit_except GET POST { deny all; }
    client_max_body_size 64k;
    limit_req zone=traccar_gps burst=20 nodelay;

    # Identyfikator auta jest w adresie zapytania - nie zapisujemy go w logu.
    access_log off;

    # Końcowy "/" obcina prefiks: /traccar-gps/?id=... -> /?id=...
    proxy_pass http://TRACCAR_IP:5055/;
    proxy_http_version 1.1;
    proxy_set_header Host              $host;
    proxy_set_header X-Real-IP         $remote_addr;
    proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Connection        "";
    proxy_connect_timeout 5s;
    proxy_read_timeout    15s;
}
```

Jeśli w tym pliku bramka logowania jest włączona globalnie
(`auth_request …;` na poziomie `server`), `auth_request off;` w tym bloku
jest **wymagane** — bez niego auto dostanie przekierowanie 302 na stronę
logowania i żadna pozycja nie dojdzie.

### 6.3 Panel — subdomena `traccar.DOMENA`

Nowy, osobny blok `server` w tym samym pliku. Globalna bramka
`auth_request` z bloku głównej domeny tu **nie obowiązuje** (dziedziczy się
tylko w obrębie swojego `server`) — panel chroni logowanie Traccara (§5).

```nginx
# ===== TRACCAR: panel www + Traccar Manager (subdomena) =====
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;
    server_name traccar.DOMENA;

    # Ten sam certyfikat co główna domena - po rozszerzeniu o subdomenę (6.4)
    ssl_certificate     /etc/letsencrypt/live/DOMENA/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/DOMENA/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;

    server_tokens off;
    add_header Strict-Transport-Security "max-age=15552000; includeSubDomains" always;

    location / {
        # Opcjonalnie panel tylko z LAN/VPN - patrz 6.5:
        # if ($admin_network_allowed = 0) { return 403; }

        proxy_pass http://TRACCAR_IP:8082;
        proxy_http_version 1.1;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Pozycje na mapie odświeżają się przez WebSocket (/api/socket)
        proxy_set_header Upgrade    $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
}
```

### 6.4 DNS i certyfikat dla subdomeny

1. U operatora DNS dodaj rekord `traccar` → ten sam publiczny adres co
   `DOMENA` (rekord A albo CNAME na `DOMENA`).
2. W bloku `server { listen 80; … }` dopisz `traccar.DOMENA` do
   `server_name`, żeby działało wyzwanie ACME. **Uwaga na przekierowanie:**
   jeśli ten blok przekierowuje przez `return 301 https://$server_name…`,
   to `$server_name` jest zawsze *pierwszą* nazwą z listy — wejście na
   `http://traccar.DOMENA` wylądowałoby na głównej domenie. Zmień na
   `return 301 https://$host$request_uri;`.
3. Rozszerz certyfikat — to samo polecenie, którym go tworzyłeś, z dodanym
   `-d traccar.DOMENA` i `--expand`, np. przy metodzie webroot:

   ```bash
   sudo certbot certonly --webroot -w /var/www/html --expand -d DOMENA -d www.DOMENA -d traccar.DOMENA
   ```

   (podaj **wszystkie** nazwy, które certyfikat ma już teraz, plus nową —
   sprawdzisz je przez `sudo certbot certificates`).
4. `sudo nginx -t && sudo systemctl reload nginx`.

### 6.5 Wariant: panel tylko z LAN/VPN

Jeśli w konfiguracji masz już zmienną z listą sieci administracyjnych
(np. `geo $admin_network_allowed { … }`), odkomentuj w §6.3 linię
`if ($admin_network_allowed = 0) { return 403; }`. Wtedy:

- pozycje z auta dalej dochodzą (§6.2 nie ma tego ograniczenia),
- panel i Traccar Manager działają w domu albo przez VPN, a z internetu
  dostają 403.

Bez subdomeny w ogóle: panel tylko lokalnie pod `http://TRACCAR_IP:8082`
(LXC) — wtedy pomijasz §6.3 i §6.4.

## 7. Test bez auta

Z dowolnego komputera spoza domu (np. telefon na danych komórkowych z
Termuxem albo laptop):

```bash
curl -s -o /dev/null -w "%{http_code}\n" "https://DOMENA/traccar-gps/?id=ID_AUTA&lat=52.2297&lon=21.0122&timestamp=$(date +%s)"
```

- `200` — w panelu auto pojawi się w Warszawie, serwer gotowy.
- `302` — brak `auth_request off;` w §6.2.
- `404` — Traccar nie zna identyfikatora (urządzenie z §5) — pozycja jest
  odrzucana.
- `502`/`504` — nginx nie dosięga `TRACCAR_IP:5055` (zapora, zły adres,
  w `traccar.xml` brak `osmand`).
- `503` — zadziałał limit z §6.1 (zbyt wiele zapytań naraz).

## 8. Po stronie BCM i telefonu

(Docelowo, po etapie 7 partii 12.)

- `/etc/bcm/bcm.env` na M910q (0600 root:root):

  ```bash
  BCM_TRACCAR_DEVICE_ID=ID_AUTA
  ```

- adres serwera w `config/local.yaml` albo w Ustawieniach BCM:
  `traccar.url: https://DOMENA/traccar-gps/`.
- BCM przekazuje adres i identyfikator agentowi w telefonie przy
  parowaniu/synchronizacji konfiguracji. Agent wysyła pozycję:
  po zaparkowaniu, co kilka–kilkanaście minut na postoju, natychmiast
  przy alarmie i częściej w trakcie jazdy; bez zasięgu trzyma kolejkę
  i dosyła później.
- SMS `POZYCJA <kod>` (patrz `docs/PRZYGOTOWANIE_TELEFONU.md` §12) działa
  dalej niezależnie od Traccara.

## 9. Podgląd auta: Traccar Manager

Na swoim telefonie zainstaluj **Traccar Manager** (Android/iOS), jako adres
serwera wpisz `https://traccar.DOMENA` i zaloguj się kontem z §5. Widać
aktualną pozycję, historię tras (Raporty → Trasa) i postoje. Możesz też
założyć w Traccarze geostrefę „dom” i powiadomienia o wyjeździe z niej.

## 10. Kopie, aktualizacje, rozwiązywanie problemów

- **Kopia:** LXC — backup kontenera w Proxmoxie; Docker — katalog
  `/opt/traccar` (`data/` to baza).
- **Aktualizacja:** LXC — nowa paczka `traccar.run` na istniejącą
  instalację (zatrzymaj usługę, zrób kopię); Docker — zmień wersję w
  `docker run`, `docker rm -f traccar`, uruchom ponownie (dane zostają
  w `/opt/traccar`).
- **Logi:** `/opt/traccar/logs/tracker-server.log` — każda odebrana pozycja
  i odrzucony nieznany identyfikator są tam widoczne.
- **Mapa nie odświeża się na żywo** — WebSocket nie przechodzi przez proxy:
  sprawdź nagłówki `Upgrade`/`Connection` w §6.3.
- **Traccar Manager nie łączy się** — adres musi być główny
  (`https://traccar.DOMENA`, bez podkatalogu) i z ważnym certyfikatem.
