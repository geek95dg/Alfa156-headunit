#!/data/data/com.termux/files/usr/bin/env python3
"""Agent BCM w telefonie w aucie (Termux) — SMS po stłuczce i wspólny kanał
dla kolejnych funkcji (alarm postojowy D4, „Zadzwoń 112” H, czuwanie kabiny I).

Po co to jest
-------------
Telefon zamontowany w aucie (Redmi, plan C) ma kartę SIM. BCM nie może sam
wysłać SMS-a, a jego wiadomość nie może zależeć od tego, czy BCM po
uderzeniu jeszcze działa (kabel, zasilanie, uśpienie). Dlatego BCM tylko
„uzbraja” zdarzenie, a termin wysyłki pilnuje TEN agent w telefonie: bez
odwołania wysyła SMS-y o czasie, nawet gdy BCM padnie albo komputer zaśnie.
Treść SMS-a składa telefon ze stałych szablonów (GSM-7); od BCM przychodzą
tylko zwalidowane liczby — żaden tekst z zewnątrz nie trafia do SMS-a ani do
wiersza polecenia.

Wymagania: sam Python 3 z biblioteką standardową (bez pip), jeden plik.

Instalacja (Termux z F-Droid, NIE ze Sklepu Play)
-------------------------------------------------
1. Aplikacje: **Termux**, **Termux:API** i **Termux:Boot** (wszystkie
   z F-Droid — podpisy muszą się zgadzać). Termux:Boot uruchom raz ręcznie,
   żeby Android pozwolił mu startować przy włączeniu telefonu.
2. W Termuxie::

       pkg install python termux-api
       mkdir -p ~/bcm_agent ~/.termux/boot
       cp bcm_agent.py ~/bcm_agent/            # ten plik
       cp boot_bcm_agent.sh ~/.termux/boot/    # tools/car_phone/termux/
       chmod 700 ~/.termux/boot/boot_bcm_agent.sh

3. Uprawnienia Termux:API (Ustawienia → Aplikacje → Termux:API →
   Uprawnienia): **SMS** (wysyłanie i odczyt — odczyt skrzynek „wysłane”
   i „nieudane” służy do potwierdzenia wysyłki) i **Telefon** (stan karty
   SIM, wybór slotu). Pierwsze ``termux-sms-send`` wywołaj ręcznie, żeby
   zaakceptować okno.
4. Optymalizacja baterii **wyłączona** dla Termux, Termux:API i
   Termux:Boot (Ustawienia → Bateria → Bez ograniczeń). Skrypt startowy
   bierze ``termux-wake-lock``, żeby Android nie usypiał procesu.
5. **crDroid / AOSP, Android 12–13** (zalecany ROM, docs/WDROZENIE_TESTOWE.md
   §5.7a): wyłącz „phantom process killer”, który ubija procesy Termuxa
   w tle (telefon zrootowany)::

       su -c '/system/bin/device_config set_sync_disabled_for_tests persistent'
       su -c '/system/bin/device_config put activity_manager max_phantom_processes 2147483647'

   oraz, jeśli jest, Opcje programisty → Feature flags →
   ``settings_enable_monitor_phantom_procs`` wyłączone. Na Androidzie 13
   zezwól też na powiadomienia dla Termux i Termux:API. Termux i obie
   wtyczki tylko z F-Droid (ten sam podpis).

   **Tylko Xiaomi z MIUI/HyperOS** ma dodatkowo dwie własne blokady, bez
   których agent nie wystartuje albo nie wyśle SMS-a bez człowieka:

   * Ustawienia → Aplikacje → Termux oraz Termux:Boot → **Autostart: ON**
     (bez tego Termux:Boot nie dostaje BOOT_COMPLETED i po restarcie
     telefonu agent nie rusza);
   * Ustawienia → Aplikacje → Termux:API → Uprawnienia → **Wysyłanie SMS:
     „Zezwalaj”**, NIE „Pytaj” (przy „Pytaj” każdy ``termux-sms-send``
     czeka na kliknięcie na ekranie i SMS po stłuczce nigdy nie wyjdzie);
   * zablokuj Termux w ostatnich aplikacjach (kłódka), żeby czyszczenie
     pamięci go nie zamykało.
6. Restart telefonu → agent działa (log: ``~/.config/bcm_agent/agent.log``).
   Ręcznie: ``python ~/bcm_agent/bcm_agent.py`` (``-v`` = log także na ekran).

Aktualizacja (po każdej aktualizacji BCM, która zmienia ten plik): skopiuj
nowy ``bcm_agent.py`` do ``~/bcm_agent/`` i zrestartuj agenta —
``pkill -f bcm_agent.py`` (pętla w ``boot_bcm_agent.sh`` uruchomi go po
10 s) albo restart telefonu. Wiersz „Agent w telefonie” w Ustawieniach BCM
pokazuje wersję (``VERSION``); stan, sekret, nonce i zdarzenia w
``~/.config/bcm_agent`` zostają. „Zadzwoń 112” z telefonu w aucie wymaga
wersji ≥ 1.1.0 (starszą BCM pokazuje jako „zaktualizuj bcm_agent.py”).

Parowanie z BCM
---------------
Wspólny sekret (≥ 32 bajty, 64+ znaków hex) wygeneruj na komputerze BCM::

    python3 -c 'import secrets;print(secrets.token_hex(32))'

i wpisz w ``/etc/bcm/bcm.env`` jako ``BCM_CAR_PHONE_AGENT_SECRET=…``
(restart BCM). Potem w telefonie::

    python ~/bcm_agent/bcm_agent.py --pair

Polecenie zapisuje w ``~/.config/bcm_agent/PAIRING`` (0600) świeży,
jednorazowy **kod parowania** (10 cyfr) i wypisuje go na ekranie. W BCM:
Ustawienia → „Agent w telefonie” → wpisz kod → **Sparuj**. Agent przyjmuje
``POST /v1/pair`` WYŁĄCZNIE, gdy istnieje plik ``PAIRING``, i tylko z
podpisem HMAC-SHA256 zrobionym TYM kodem (ten sam schemat co niżej, kod
zamiast sekretu); po udanym parowaniu sam usuwa plik, po
:data:`PAIR_MAX_FAILS` złych kodach też (trzeba wtedy wygenerować nowy).
Samo ``touch ~/.config/bcm_agent/PAIRING`` też działa — agent wpisze kod do
pustego pliku w ciągu kilku sekund (``cat`` go pokaże). Sekret leży w
``~/.config/bcm_agent/secret`` (0600, katalog 0700) i nigdy nie trafia do
logu.

Dlaczego kod idzie z telefonu do BCM, a nie odwrotnie: z agentem może
połączyć się KAŻDY lokalny proces — każda aplikacja w telefonie przez
127.0.0.1:8765 i każdy użytkownik komputera BCM (także nieuprzywilejowany
użytkownik kiosku) przez port forwardu 952 (zająć go nie może, połączyć się
— tak). Bez kodu ktokolwiek z nich mógłby „sparować się” pierwszy, gdy tylko
pojawi się plik PAIRING. Kod leży w prywatnym katalogu Termuxa, którego inne
aplikacje nie czytają, a do BCM trafia tylko z rąk kierowcy. Ryzyko, które
zostaje: sekret jedzie przy parowaniu otwartym tekstem przez forward adb —
jeśli w miejscu martwego agenta port 8765 zajęła inna aplikacja, dostałaby
go. Dlatego BCM, który raz już potwierdził parowanie tym sekretem, przy
„agent nie zna sekretu” pokazuje ostrzeżenie (``agent_reset``) i paruje
dopiero po wyraźnym „Sparuj mimo to”.

Bezpieczeństwo
--------------
* Nasłuch TYLKO na 127.0.0.1 (BCM łączy się przez ``adb forward``; z Wi-Fi
  i z sieci komórkowej agent jest nieosiągalny). Najwyżej
  :data:`MAX_CONNECTIONS` połączeń naraz, limit czasu gniazda, treść żądania
  najwyżej :data:`MAX_BODY` bajtów, wyłącznie JSON.
* Każde żądanie jest podpisane HMAC-SHA256 nad
  ``METODA\\nŚCIEŻKA\\nTS\\nNONCE\\nSHA256HEX(treść)`` (nagłówki
  ``X-BCM-Ts``, ``X-BCM-Nonce``, ``X-BCM-Sig``; ``/v1/pair`` kodem
  parowania, reszta sekretem): ``|ts − teraz| ≤ 60 s``,
  nonce ściśle rosnący i zapisywany atomowo (``os.replace``) PRZED
  wykonaniem żądania — powtórka nie przejdzie także po restarcie agenta.
  Porównanie w stałym czasie (``hmac.compare_digest``).
* Odpowiedzi na uwierzytelnione żądania są podpisane (``X-BCM-Sig`` nad
  ``RESP\\nSTATUS\\nNONCE\\nSHA256HEX(treść)``; przedrostek ``RESP`` nie
  pozwala pomylić podpisu odpowiedzi z podpisem żądania), więc program,
  który zająłby port w miejsce agenta, nie potrafi udawać „wysłano”.
  Odpowiedzi na żądania bez ważnego podpisu NIE są podpisywane — agent nie
  produkuje podpisów dla obcych — i nie mówią nic o parowaniu (ani czy
  istnieje plik PAIRING, ani czy agent jest sparowany).
* Do ``termux-sms-send`` trafia jako argument wyłącznie zwalidowany numer
  (``^\\+[1-9][0-9]{7,14}$``) i stały numer slotu; tekst idzie na stdin.
  Wszystkie polecenia to listy argumentów (nigdy powłoka) przez jeden
  wstrzykiwany ``runner`` (testy).

Endpointy (JSON)
----------------
``GET /v1/health``, ``PUT /v1/config``, ``POST /v1/crash``,
``POST /v1/crash/<id>/cancel``, ``POST /v1/crash/<id>/send_now``,
``GET /v1/crash/<id>``, ``POST /v1/test``, ``POST /v1/pair``,
``POST /v1/call112``, ``GET /v1/call112``, ``POST /v1/call112/hangup``,
``POST /v1/call112/mark`` —
opis przy metodach :class:`Agent`. Bateria i SIM w ``/v1/health`` są odświeżane w tle
tylko wtedy, gdy BCM o nie pyta (auto na postoju nie budzi Termux:API co
minutę).

Zdarzenie wypadku
-----------------
``armed`` (odliczanie trwa) → ``pending`` (termin minął, czeka na zasięg
albo kolejkę) → ``sending`` → ``sent`` | ``partial`` | ``failed``; albo
``cancelled``. Termin liczony zegarem CLOCK_BOOTTIME telefonu (płynie też we
śnie, nie skacze ze zmianą czasu), a zapisany jako czas ścienny — po
restarcie agenta zdarzenie wraca: przed terminem odlicza dalej, po terminie
(mniej niż 30 min) wysyła od razu, starsze oznacza jako ``failed``
(``expired``). Limity pilnowane tutaj, zapisane na dysku: 1 zdarzenie na
10 min i 3 na dobę (zdarzenie odwołane, zanim cokolwiek wyszło, się nie
liczy; zdarzenie w trybie testowym ``dry_run`` nie liczy się do limitu
prawdziwych, bo nic nie wysłało — fałszywy alarm na stole nie może
zablokować prawdziwego), testowy SMS najwyżej raz na 10 min.

Odwołanie jest ostateczne: odbiorca, do którego SMS jeszcze nie wyszedł,
już go nie dostanie — także gdy odwołanie trafi w trwające sprawdzanie
zasięgu albo skrzynki (agent sprawdza je ponownie tuż przed
``termux-sms-send``) i gdy agent zrestartuje się w trakcie (wysyłka „w
locie” nie jest wtedy powtarzana). Nie da się przerwać tylko samego
``termux-sms-send``; taki odbiorca, jak każdy, do kogo SMS mógł wyjść,
dostaje jeden SMS odwołujący.

Wysyłka: jedno ``termux-sms-send -n <NUMER> -s <SLOT>`` na odbiorcę, tekst
na stdin (według pomocy termux-api tekst czytany jest ze stdin, gdy nie ma
go w argumentach — NIESPRAWDZONE na tym ROM-ie). Najpierw do 2 min czekania
na zasięg (``termux-telephony-deviceinfo``), potem kontrola skrzynek
(``termux-sms-list -t all``, pole ``type`` każdej wiadomości) co 30 s:
wiadomość w „wysłanych” = wysłana; w „nieudanych” = ponowienie (do 3, po
30/60/120 s); w żadnej = jeszcze w drodze (Android zapisuje SMS aplikacji,
która nie jest domyślną aplikacją SMS, dopiero gdy radio skończy — przy
słabym zasięgu albo SMS-ie z 2 części to trwa) — czekam do 5 min i wtedy
uznaję „wysłany, niepotwierdzony”, BEZ ponownej wysyłki. Przed każdym
ponowieniem sprawdzam, czy wcześniejsza kopia nie doszła w międzyczasie.
Ponowienie po „nieudanym” albo restart agenta w trakcie wysyłki nadal
mogą dać duplikat — przy alarmie to mniejsze zło niż brak SMS-a.
``dry_run`` = agent tylko loguje treść (stan ``sent_dry``) i dla SMS-ów
o wypadku i odwołujących NIGDY nie woła ``termux-sms-send``. Testowy SMS
idzie naprawdę tylko na wyraźne ``real_test: true`` w ``POST /v1/test``
(po stronie BCM wolno je wysłać wyłącznie z ekranu auta, z limitem i po
potwierdzeniu kierowcy — to wymaganie dla trasy testowego SMS-a w
module ``crash_sms``).

„Zadzwoń 112” z telefonu w aucie (plan H, ścieżka B)
-----------------------------------------------------
ZAWSZE ręcznie: kierowca przytrzymuje przycisk w oknie wypadku na ekranie
auta, BCM wysyła podpisane ``POST /v1/call112`` z polami
``{"mode": "real"|"test", "event_id": "<hex>"}`` (``mode`` to strażnik:
agent odmawia, gdy jego własny tryb jest inny — nigdy prawdziwe 112 przy
teście ani odwrotnie; ``event_id`` to zdarzenie z okna wypadku w BCM — tylko
jego SMS dostaje dopisek o 112). **Numeru nigdy nie ma w żądaniu**: ``112`` jest stałą w tym pliku, a w trybie testowym
(``call112_test_mode``) agent dzwoni na SWÓJ ``call112_test_number``
(E.164, przysłany wcześniej w ``PUT /v1/config`` i sprawdzony po obu
stronach). Bez przełącznika ``toggles.call112`` agent odmawia. Najwyżej
jedno połączenie na :data:`CALL112_COOLDOWN_S` (zapisane na dysku; próba,
której ``am start`` się nie udał, się nie liczy).

Wykonanie: Magisk ``su`` (nadany WYŁĄCZNIE aplikacji Termux; NIE ``adb
shell`` — serwer adb na komputerze BCM jest dostępny lokalnie). ``su -c``
bierze JEDEN ciąg dla powłoki roota, więc każdy taki ciąg jest składany
tylko ze stałych tekstów i zwalidowanych cyfr (:func:`call_command`,
:func:`volume_set_command`) i przed uruchomieniem jeszcze raz sprawdzany
wyrażeniem :data:`SU_SAFE_RE` (litery, cyfry, spacja i ``._:+-``)::

    am start -a android.intent.action.CALL_PRIVILEGED -d tel:112 \\
        --ez android.telecom.extra.START_CALL_WITH_SPEAKERPHONE true
    (test: android.intent.action.CALL i tel:<numer testowy>)
    cmd media_session volume --stream 0 --get      → „... in range [a..b]”
    cmd media_session volume --stream 0 --set <b>  (głośność rozmowy na max)
    dumpsys telephony.registry                     → mCallState=0|1|2
    input keyevent KEYCODE_ENDCALL                 (Rozłącz z ekranu auta)

NIESPRAWDZONE na crDroid 13 (do sprawdzenia na stole — numerem testowym,
NIGDY prawdziwym 112): że ``START_CALL_WITH_SPEAKERPHONE`` z intencji
włącza głośnik, format wyjścia ``cmd media_session volume`` i że strumień 0
to głośność rozmowy, że ``mCallState`` w ``dumpsys telephony.registry``
odzwierciedla połączenie alarmowe (OFFHOOK = wybieranie LUB rozmowa — agent
nie odróżni „łączy” od „rozmawia”), że ``KEYCODE_ENDCALL`` kończy rozmowę.
Magisk pokazuje komunikat przy każdym użyciu ``su`` — w aplikacji Magisk →
Superużytkownik → Termux wyłącz powiadomienia (agent sprawdza ``su`` co
10 min i co 2 s w trakcie rozmowy).

``GET /v1/health`` mówi ``call112_capable`` (przełącznik włączony, ``su``
działa — sprawdzane ``su -c 'id -u'`` w wątku stanu — i w teście jest
numer), ``call112_mode`` i ``call_state`` (ostatni odczyt ``mCallState``
albo None). ``GET /v1/call112`` — stan bieżącego połączenia (``queued`` →
``placed`` → ``offhook`` → ``ended``, albo ``failed``); ``POST
/v1/call112/hangup`` — rozłączenie. Połączenie prowadzi osobny wątek
(nigdy za wysyłką SMS-a, która potrafi trwać minutę).

Powiązanie z SMS-em o wypadku (nie w trybie testowym): zdarzenie
``event_id`` (to z żądania, nie „najnowsze” — okno BCM mogło otworzyć inne,
np. samo-GPS-owe zdarzenie, którego telefon w ogóle nie zna; wtedy nic się
nie oznacza) dostaje znacznik ``called_112`` — po udanym ``am start`` z tego
telefonu albo na ``POST /v1/call112/mark {"event_id"}`` (BCM wybrał
prawdziwe 112 przez GŁÓWNY telefon, HFP). Jeśli SMS jeszcze do nikogo nie
wyszedł, do treści
dochodzi „Z auta wybrano 112 o hh:mm.”; jeśli już wyszedł — po zakończeniu
wysyłki idzie JEDEN SMS uzupełniający do tych, do których wyszedł, i
zużywa to budżet SMS-a odwołującego (potem SMS-a „ODWOLANE” już nie ma).
112 nigdy nie odwołuje SMS-a.

Czego agent nie obiecuje: doręczenia (brak raportów doręczenia, zasięg,
środki na karcie), działania przy wyłączonym lub przegrzanym telefonie,
działania, gdy Android zabije Termux (phantom process killer), zestawienia
połączenia z 112 ani jakości głośnika pod podsufitką. To nie eCall.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import logging
import logging.handlers
import math
import os
import re
import secrets
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Mapping, Optional

#: 1.1.0 — „Zadzwoń 112” (plan H): ``/v1/call112*``, pola ``call112_*`` w
#: konfiguracji. BCM z włączonym ``modules.call112`` wymaga co najmniej tej
#: wersji (starszą pokazuje w Ustawieniach jako „zaktualizuj bcm_agent.py”).
VERSION = "1.1.0"

log = logging.getLogger("bcm_agent")

# ── stałe ─────────────────────────────────────────────────────────────────

#: Jedyny adres nasłuchu. Nie ma opcji, żeby to zmienić.
BIND_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_STATE_DIR = os.path.join(os.path.expanduser("~"), ".config", "bcm_agent")
#: Największa treść żądania (bajty). Prawdziwe żądania mają < 1 KB.
MAX_BODY = 8192
MAX_PATH = 128
#: Najwięcej równoczesnych połączeń (wątków obsługi); nadmiarowe są
#: zamykane od razu, więc lokalna aplikacja nie zje pamięci telefonu.
MAX_CONNECTIONS = 8
SOCKET_TIMEOUT_S = 10.0
TS_WINDOW_S = 60
#: Nonce mieści się w 19 cyfrach (int64 po stronie BCM).
NONCE_MAX_DIGITS = 19
#: Najmniejszy odstęp prób parowania (liczone tylko poprawnie zbudowane
#: próby przy otwartym PAIRING — śmieci nie zużywają limitu).
PAIR_MIN_INTERVAL_S = 3.0
#: Tyle złych kodów parowania i plik PAIRING jest usuwany (nowy kod: --pair).
PAIR_MAX_FAILS = 5
PAIR_CODE_LEN = 10
#: Nieudane uwierzytelnienia loguję najwyżej raz na tyle sekund.
AUTH_LOG_EVERY_S = 60.0

SECRET_RE = re.compile(r"^[0-9a-f]{64,128}$")
PAIR_CODE_RE = re.compile(r"^[0-9]{%d}$" % PAIR_CODE_LEN)
E164_RE = re.compile(r"^\+[1-9][0-9]{7,14}$")
#: Etykieta auta w SMS-ie: tylko znaki GSM-7, które nic nie psują w tekście.
LABEL_RE = re.compile(r"^[A-Za-z0-9 .-]{1,20}$")
EVENT_ID_RE = re.compile(r"^[0-9a-f]{1,32}$")
SIG_RE = re.compile(r"^[0-9a-f]{64}$")
DIGITS_RE = re.compile(r"^[0-9]{1,%d}$" % NONCE_MAX_DIGITS)

MAX_RECIPIENTS = 3
TOGGLES = ("crash_sms", "parking_guard", "cabin_watch", "call112")
DEFAULT_LABEL = "ALFA 156"
COUNTDOWN_MIN_S = 15
COUNTDOWN_MAX_S = 120
MAX_SPEED_KMH = 400
MAX_FIX_AGE_S = 86400
#: Rozsądny zakres znacznika czasu zdarzenia (2020-09 … 2096).
EVENT_TS_MIN = 1_600_000_000
EVENT_TS_MAX = 4_000_000_000

CRASH_COOLDOWN_S = 600
CRASH_MAX_PER_DAY = 3
DAY_S = 86400
TEST_COOLDOWN_S = 600
#: Zdarzenie po terminie wznawiane po restarcie tylko, gdy jest młodsze.
RESUME_MAX_LATE_S = 1800
#: SMS odwołujący tylko w tym czasie od wyjścia SMS-a o wypadku.
CANCEL_WINDOW_S = 900
MAX_EVENTS = 64
KEEP_EVENTS_S = 2 * DAY_S

SERVICE_WAIT_S = 120.0
SERVICE_POLL_S = 10.0
#: Kontrola skrzynek co tyle sekund po przekazaniu SMS-a Androidowi …
VERIFY_AFTER_S = 30.0
#: … a najdłużej tyle: Android ponawia na poziomie radia (3 próby, ~40 s
#: każda); wiadomość nadal ani w „wysłanych”, ani w „nieudanych” =
#: „wysłana, niepotwierdzona” — bez ponownej wysyłki (duplikat).
VERIFY_WINDOW_S = 300.0
RETRY_DELAYS_S = (30.0, 60.0, 120.0)
SMS_SEND_TIMEOUT_S = 60.0
API_TIMEOUT_S = 20.0
#: Ostatnie wiadomości (wszystkie skrzynki) brane pod uwagę przy kontroli.
SMS_LIST_LIMIT = 100
SMS_LIST_MAX_BYTES = 1024 * 1024
STATUS_REFRESH_S = 60.0
#: Bateria i SIM odświeżane tylko, gdy ktoś czyta /v1/health (BCM działa):
#: auto na postoju, telefon na własnej baterii — nikt nie pyta, nic nie woła
#: Termux:API co minutę.
STATUS_IDLE_S = 300.0
#: Zasięg sprawdzam najwyżej co tyle sekund (wynik w pamięci podręcznej).
SERVICE_CACHE_S = 10.0
SCHED_MAX_WAIT_S = 5.0

LOG_FILE = "agent.log"
LOG_MAX_BYTES = 256 * 1024
LOG_BACKUPS = 2

RC_MISSING = 127
RC_TIMEOUT = 124

# ── „Zadzwoń 112” (plan H) ────────────────────────────────────────────────
#: Jedyny numer alarmowy, jaki agent wybiera. Stała — nigdy z żądania.
CALL112_NUMBER = "112"
#: Najwyżej jedno połączenie na tyle sekund (próba z nieudanym ``am start``
#: się nie liczy — kolejna może pójść od razu).
CALL112_COOLDOWN_S = 60
CALL_MODES = ("real", "test")
#: Stany połączenia: przyjęte → ``am start`` wykonany → telefon w rozmowie
#: (OFFHOOK) → zakończone; albo nieudane.
CALL_STATES = ("queued", "placed", "offhook", "ended", "failed")
CALL_ACTIVE = ("queued", "placed", "offhook")
CALL_ERRORS = ("", "su_missing", "su_denied", "am_failed", "no_call")
#: Odczyt ``mCallState`` w trakcie połączenia co tyle sekund.
CALL_POLL_S = 2.0
#: Połączenie śledzę najdłużej tyle.
CALL_FOLLOW_MAX_S = 3600.0
#: Stanu rozmowy nie da się odczytać: po tylu sekundach przestaję pytać
#: (połączenie zostaje „placed”, ``final``).
CALL_NO_STATE_S = 120.0
#: Stan da się odczytać, a telefon nie wszedł w rozmowę po ``am start``
#: przez tyle sekund: połączenie się nie zaczęło (``no_call``).
CALL_IDLE_FAIL_S = 20.0
#: Tyle kolejnych odczytów „idle” po OFFHOOK = rozmowa zakończona.
CALL_IDLE_ENDS = 2
SU_TIMEOUT_S = 15.0
#: ``su -c 'id -u'`` co tyle sekund (gdy BCM pyta o health i 112 włączone);
#: po porażce częściej.
SU_PROBE_OK_S = 600.0
SU_PROBE_FAIL_S = 60.0
#: Górna granica indeksu głośności, którą przyjmę z ``--get``.
CALL_VOLUME_MAX = 100
#: Co wolno w ciągu przekazanym ``su -c`` (powłoka roota). Wszystko inne —
#: cudzysłów, ``;``, ``$``, ``|``, ``&``, ``/``, ``\\``, nowa linia — odpada.
SU_SAFE_RE = re.compile(r"^[A-Za-z0-9 ._:+-]{1,200}$")
_VOLUME_RANGE_RE = re.compile(r"range \[([0-9]{1,3})\.\.([0-9]{1,3})\]")
_CALL_STATE_RE = re.compile(r"mCallState=([0-9])")
#: Wyjście ``dumpsys``, które w ogóle czytam.
DUMPSYS_MAX_CHARS = 512 * 1024

#: Stany odbiorcy, które kończą jego wysyłkę.
RCPT_FINAL = ("sent", "sent_dry", "failed", "skipped")
RCPT_OK = ("sent", "sent_dry")
EVENT_ACTIVE = ("armed", "pending", "sending")
EVENT_STATES = ("armed", "pending", "sending", "sent", "partial", "failed", "cancelled")

#: Podstawowy alfabet GSM 03.38 (bez ESC 0x1B i tablicy rozszerzeń: znak
#: spoza tego zbioru — np. polska litera albo „–” — przełącza SMS na UCS-2
#: i skraca część ze 160 do 70 znaków).
GSM7_BASIC = frozenset(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
    "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà")


# ── narzędzia ─────────────────────────────────────────────────────────────

def boot_clock() -> float:
    """Sekundy od startu telefonu (CLOCK_BOOTTIME): płynie także we śnie
    i nie reaguje na zmianę czasu — termin wysyłki nie przesunie się przez
    NITZ ani przez uśpienie."""
    try:
        return time.clock_gettime(time.CLOCK_BOOTTIME)
    except (AttributeError, OSError):
        return time.monotonic()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def request_message(method: str, path: str, ts: int, nonce: int, body: bytes) -> bytes:
    return f"{method}\n{path}\n{ts}\n{nonce}\n{sha256_hex(body)}".encode("ascii")


def response_message(status: int, nonce: int, body: bytes) -> bytes:
    return f"RESP\n{status}\n{nonce}\n{sha256_hex(body)}".encode("ascii")


def sign(key: bytes, message: bytes) -> str:
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def config_hash(cfg: Mapping[str, Any]) -> str:
    """Skrót konfiguracji (16 znaków hex): BCM porównuje go ze swoim i wysyła
    ``PUT /v1/config`` tylko przy różnicy — także po wymianie agenta.

    Pola ``call112_*`` liczą się do skrótu TYLKO przy włączonym
    przełączniku ``call112``. Dlaczego: BCM wysyła je wyłącznie przy
    włączonym ``modules.call112``, a agent z #128 (1.0.0) pomija nieznane
    klucze. Dzięki temu przy wyłączonym 112 stary agent z nowym BCM i nowy
    agent ze starym BCM liczą ten sam skrót — sama aktualizacja jednej
    strony nie kończy się „config_refused” (a ten wymusza tryb testowy
    SMS-a po stłuczce)."""
    toggles = cfg.get("toggles")
    on = isinstance(toggles, Mapping) and toggles.get("call112") is True
    view = {k: v for k, v in cfg.items() if on or not k.startswith("call112_")}
    return sha256_hex(canonical_json(view).encode("ascii"))[:16]


def is_gsm7(text: str) -> bool:
    return all(ch in GSM7_BASIC for ch in text)


def sms_segments(text: str) -> int:
    """Liczba części SMS-a GSM-7 (160 znaków w jednej, 153 w każdej części
    wiadomości łączonej)."""
    n = len(text)
    return 1 if n <= 160 else -(-n // 153)


def _wait_s(seconds: float) -> int:
    """``retry_after``: pełne sekundy w górę, co najmniej 1."""
    return max(1, int(math.ceil(seconds)))


def new_pairing_code() -> str:
    """Losowy kod parowania: :data:`PAIR_CODE_LEN` cyfr z ``secrets``
    (10^10 możliwości przy najwyżej :data:`PAIR_MAX_FAILS` próbach)."""
    return str(secrets.randbelow(10 ** PAIR_CODE_LEN)).zfill(PAIR_CODE_LEN)


def mask_number(num: str) -> str:
    """``+48601234567`` → ``+48...567`` (log, odpowiedzi)."""
    return f"{num[:3]}...{num[-3:]}" if len(num) > 6 else "..."


def _reject_constant(name: str) -> Any:
    raise ValueError(f"{name} is not valid JSON here")


def parse_json_object(body: bytes) -> dict:
    """Treść żądania → słownik. ValueError dla czegokolwiek innego (także
    NaN/Infinity i zduplikowanych kluczy)."""
    def pairs(items: list) -> dict:
        out: dict = {}
        for k, v in items:
            if k in out:
                raise ValueError(f"duplicate key {k!r}")
            out[k] = v
        return out

    if not body:
        return {}
    obj = json.loads(body.decode("utf-8"), parse_constant=_reject_constant,
                     object_pairs_hook=pairs)
    if not isinstance(obj, dict):
        raise ValueError("expected a JSON object")
    return obj


def _number(value: Any, lo: float, hi: float, integer: bool = False) -> Optional[float]:
    """Skończona liczba w ``[lo, hi]`` albo None. bool odrzucony (True ≠ 1)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if integer and not isinstance(value, int):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if not lo <= value <= hi:
        return None
    return value


def atomic_write(path: str, data: bytes, mode: int = 0o600) -> None:
    """Zapis przez plik tymczasowy + fsync + ``os.replace`` — po zaniku
    zasilania zostaje stara albo nowa wersja, nigdy pół pliku."""
    directory = os.path.dirname(path) or "."
    tmp = os.path.join(directory, f".{os.path.basename(path)}.{os.getpid()}."
                                  f"{threading.get_ident()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, mode)
    try:
        try:
            os.fchmod(fd, mode)
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view):]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    try:
        dfd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except OSError:
        pass


def read_small(path: str, limit: int = 256 * 1024) -> Optional[bytes]:
    try:
        with open(path, "rb") as f:
            data = f.read(limit + 1)
    except FileNotFoundError:
        return None
    if len(data) > limit:
        raise ValueError(f"{path} is too large")
    return data


# ── treści SMS (stałe szablony, plan F „Treści SMS”) ──────────────────────

def _fmt_age(age_s: int) -> str:
    if age_s < 120:
        return f"{age_s} s"
    if age_s < 7200:
        return f"{age_s // 60} min"
    return f"{min(age_s // 3600, 999)} h"


def crash_text(label: str, event_ts: int, lat: Optional[float], lon: Optional[float],
               fix_age_s: Optional[int], speed_kmh: Optional[float],
               dv_kmh: Optional[float],
               localtime: Callable[[float], time.struct_time] = time.localtime) -> str:
    """SMS o możliwym wypadku. Wstawiane są tylko zwalidowane liczby
    (współrzędne z 5 miejscami po przecinku, reszta jako liczby całkowite)
    i etykieta auta z :data:`LABEL_RE`."""
    t = localtime(event_ts)
    when = time.strftime("%d.%m.%Y %H:%M", t)
    if lat is not None and lon is not None:
        age = f" (GPS sprzed {_fmt_age(int(fix_age_s))})" if fix_age_s is not None else " (GPS)"
        pos = f"https://maps.google.com/?q={lat:.5f},{lon:.5f}{age}"
    else:
        pos = "nieznana (brak GPS)"
    speed = f"{int(round(speed_kmh))} km/h" if speed_kmh is not None else "nieznana"
    dv = f", zmiana ok. {int(round(dv_kmh))} km/h" if dv_kmh is not None else ""
    return (f"{label}: MOZLIWY WYPADEK {when}. Pozycja: {pos}. "
            f"Predkosc przed: {speed}{dv}. Wiadomosc automatyczna, NIE jest to "
            f"zgloszenie na 112. Zadzwon do kierowcy; jesli nie odbiera, dzwon 112 "
            f"i podaj pozycje.")


def cancel_text(label: str, event_ts: int,
                localtime: Callable[[float], time.struct_time] = time.localtime) -> str:
    hm = time.strftime("%H:%M", localtime(event_ts))
    return f"{label}: ODWOLANE - kierowca potwierdzil, ze nic sie nie stalo (alarm z {hm})."


def test_text(label: str) -> str:
    return f"{label}: TEST powiadomien o wypadku. Nic sie nie stalo, nie reaguj."


def called_112_suffix(call_wall: float,
                      localtime: Callable[[float], time.struct_time] = time.localtime) -> str:
    """Dopisek do SMS-a o wypadku, który jeszcze nie wyszedł (GSM-7)."""
    return f"Z auta wybrano 112 o {time.strftime('%H:%M', localtime(call_wall))}."


def call112_text(label: str, call_wall: float, event_ts: int,
                 localtime: Callable[[float], time.struct_time] = time.localtime) -> str:
    """SMS uzupełniający, gdy SMS o wypadku już wyszedł (GSM-7, 1 część)."""
    hm = time.strftime("%H:%M", localtime(call_wall))
    ev = time.strftime("%H:%M", localtime(event_ts))
    return f"{label}: Z auta wybrano 112 o {hm} (alarm o wypadku z {ev})."


# ── polecenia „Zadzwoń 112” (stałe ciągi dla ``su -c``) ──────────────────

def su_argv(command: str) -> list:
    """``["su", "-c", command]`` — ``su -c`` przekazuje ``command`` powłoce
    roota JAKO JEDEN CIĄG, więc wolno tu podać wyłącznie ciąg zbudowany
    przez funkcje poniżej (stałe + zwalidowane cyfry). Sprawdzam go jeszcze
    raz (:data:`SU_SAFE_RE`): ValueError zamiast uruchomienia czegokolwiek
    innego. ``su`` z PATH Termuxa (termux-tools ma nakładkę, która szuka
    prawdziwego ``su`` Magiska)."""
    if not isinstance(command, str) or not SU_SAFE_RE.fullmatch(command):
        raise ValueError("refusing to pass this string to su")
    return ["su", "-c", command]


def call_command(test_number: Optional[str] = None) -> str:
    """``am start`` dla 112 (``test_number`` None) albo dla numeru
    testowego (zwalidowany E.164 — w ciągu dla powłoki to tylko ``+`` i
    cyfry). CALL_PRIVILEGED: numer alarmowy idzie bez potwierdzenia, także
    bez karty SIM; numer testowy zwykłym CALL — CALL_PRIVILEGED dla
    zwykłego numeru też by zadzwonił, ale test ma zachowywać się jak
    zwykła rozmowa."""
    speaker = "--ez android.telecom.extra.START_CALL_WITH_SPEAKERPHONE true"
    if test_number is None:
        return f"am start -a android.intent.action.CALL_PRIVILEGED -d tel:{CALL112_NUMBER} {speaker}"
    if not isinstance(test_number, str) or not E164_RE.fullmatch(test_number):
        raise ValueError("test number must be E.164")
    return f"am start -a android.intent.action.CALL -d tel:{test_number} {speaker}"


VOLUME_GET_COMMAND = "cmd media_session volume --stream 0 --get"
CALL_STATE_COMMAND = "dumpsys telephony.registry"
HANGUP_COMMAND = "input keyevent KEYCODE_ENDCALL"
SU_PROBE_COMMAND = "id -u"


def volume_set_command(index: Any) -> str:
    """Głośność strumienia rozmowy (0 = STREAM_VOICE_CALL) na ``index`` —
    liczba całkowita 0..:data:`CALL_VOLUME_MAX`, nic innego."""
    if isinstance(index, bool) or not isinstance(index, int) \
            or not 0 <= index <= CALL_VOLUME_MAX:
        raise ValueError("volume index out of range")
    return f"cmd media_session volume --stream 0 --set {index}"


def parse_volume_max(text: Any) -> Optional[int]:
    """``volume is 4 in range [1..7]`` → 7 (None, gdy nie pasuje)."""
    if not isinstance(text, str):
        return None
    m = _VOLUME_RANGE_RE.search(text[:4096])
    if m is None:
        return None
    lo, hi = int(m.group(1)), int(m.group(2))
    return hi if lo <= hi <= CALL_VOLUME_MAX else None


def parse_call_state(text: Any) -> Optional[int]:
    """``mCallState=N`` z ``dumpsys telephony.registry`` → 0 (idle),
    1 (dzwoni), 2 (OFFHOOK: wybieranie albo rozmowa); przy kilku
    telefonach/kartach — najwyższy. None = nie da się odczytać."""
    if not isinstance(text, str):
        return None
    values = [int(v) for v in _CALL_STATE_RE.findall(text[:DUMPSYS_MAX_CHARS])
              if v in ("0", "1", "2")]
    return max(values) if values else None


# ── polecenia w telefonie ─────────────────────────────────────────────────

Runner = Callable[[list, Optional[str], float], "tuple[int, str, str]"]


def default_runner(argv: list, stdin: Optional[str], timeout: float) -> tuple[int, str, str]:
    """Jedno polecenie: lista argumentów (NIGDY powłoka), limit czasu, nigdy
    nie rzuca. 127 = brak programu, 124 = przekroczony czas."""
    if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
        return 2, "", "invalid command"
    try:
        res = subprocess.run(argv, input=stdin if stdin is not None else "",
                             capture_output=True, text=True, errors="replace",
                             timeout=timeout, shell=False)
    except FileNotFoundError:
        return RC_MISSING, "", f"{argv[0]} not installed"
    except subprocess.TimeoutExpired:
        return RC_TIMEOUT, "", f"{argv[0]} timed out"
    except OSError as e:
        return 1, "", f"{argv[0]}: {e}"
    return res.returncode, res.stdout or "", res.stderr or ""


def _clean(text: Any, limit: int = 160) -> str:
    s = re.sub(r"[\x00-\x1f\x7f]+", " ", str(text)).strip()
    return s[:limit]


def _digits(num: Any) -> str:
    return re.sub(r"[^0-9]", "", num) if isinstance(num, str) else ""


class Phone:
    """Termux:API przez ``runner``. Każda metoda nigdy nie rzuca."""

    def __init__(self, runner: Runner, clock: Callable[[], float]) -> None:
        self._run = runner
        self._clock = clock
        self._service: Optional[tuple[float, Optional[bool]]] = None
        self.sms_permission: Optional[bool] = None

    def _json(self, argv: list, timeout: float = API_TIMEOUT_S, limit: int = 262144) -> Any:
        rc, out, _err = self._run(argv, None, timeout)
        if rc != 0 or len(out) > limit:
            return None
        try:
            return json.loads(out, parse_constant=_reject_constant)
        except (ValueError, RecursionError):
            return None

    def battery(self) -> Optional[dict]:
        obj = self._json(["termux-battery-status"])
        if not isinstance(obj, dict):
            return None
        pct = _number(obj.get("percentage"), 0, 100, integer=True)
        temp = _number(obj.get("temperature"), -40, 100)
        plugged = obj.get("plugged")
        status = obj.get("status")
        return {
            "pct": pct,
            "temp_c": round(float(temp), 1) if temp is not None else None,
            "plugged": plugged if isinstance(plugged, str) and re.fullmatch(r"[A-Z_]{1,24}", plugged)
            else None,
            "status": status if isinstance(status, str) and re.fullmatch(r"[A-Z_]{1,24}", status)
            else None,
        }

    def device_info(self) -> Optional[dict]:
        obj = self._json(["termux-telephony-deviceinfo"])
        return obj if isinstance(obj, dict) else None

    def sim_ready(self) -> Optional[bool]:
        """True/False tylko, gdy telefon podał stan karty; obiekt bez
        ``sim_state`` (błąd Termux:API, brak READ_PHONE_STATE) = None, nie
        „brak SIM”."""
        info = self.device_info()
        state = info.get("sim_state") if info is not None else None
        if not isinstance(state, str):
            return None
        return state.lower() == "ready"

    def service_ok(self) -> Optional[bool]:
        """Karta gotowa i telefon zarejestrowany u operatora; None = nie
        wiadomo (brak Termux:API, uprawnień albo pól w odpowiedzi — wtedy
        NIE czekamy na zasięg: lepiej spróbować wysłać od razu, niż na
        ROM-ie, który tych pól nie podaje, opóźniać każdy alarm o 2 min).
        False tylko dla podanego stanu karty innego niż gotowa albo pustego
        operatora przy gotowej karcie."""
        now = self._clock()
        if self._service is not None and now - self._service[0] < SERVICE_CACHE_S:
            return self._service[1]
        info = self.device_info()
        value: Optional[bool] = None
        if info is not None:
            sim = info.get("sim_state")
            op = info.get("network_operator")
            if isinstance(sim, str):
                if sim.lower() != "ready":
                    value = False
                elif isinstance(op, str):
                    value = bool(op.strip())
        self._service = (now, value)
        return value

    def sms_counts(self, num: str, text: str) -> Optional[dict]:
        """Ile wiadomości do ``num`` z dokładnie tą treścią jest w skrzynce
        „wysłane” (``sent``) i ile w „nieudane” (``failed``), wśród
        ostatnich :data:`SMS_LIST_LIMIT` (``termux-sms-list -t all``, pole
        ``type``; ``-t`` nie zna skrzynki „failed”). None = nie da się
        sprawdzić (brak READ_SMS, za duża odpowiedź albo stara wersja
        Termux:API bez pola ``type``).

        Po co obie: Android zapisuje SMS aplikacji, która nie jest domyślną
        aplikacją SMS, dopiero gdy radio skończy — jako ``sent`` albo
        ``failed``. Wiadomość, której nie ma w żadnej, jest jeszcze w drodze;
        ponowienie wtedy dałoby duplikat."""
        obj = self._json(["termux-sms-list", "-t", "all", "-l", str(SMS_LIST_LIMIT)],
                         limit=SMS_LIST_MAX_BYTES)
        if not isinstance(obj, list):
            return None
        items = [i for i in obj[:SMS_LIST_LIMIT * 2] if isinstance(i, dict)]
        if items and not any(isinstance(i.get("type"), str) for i in items):
            return None
        want = _digits(num)[-9:]
        body = text.strip()
        out = {"sent": 0, "failed": 0}
        for item in items:
            kind = item.get("type")
            got = _digits(item.get("number"))
            msg = item.get("body")
            if isinstance(kind, str) and kind in out and got and got[-9:] == want \
                    and isinstance(msg, str) and msg.strip() == body:
                out[kind] += 1
        return out

    def send_sms(self, num: str, text: str, slot: Optional[int]) -> tuple[bool, str, bool]:
        """Jedno ``termux-sms-send``: numer (już zwalidowany) i slot jako
        argumenty, tekst na stdin. ``(ok, błąd, mogło_wyjść)`` — trzecie
        pole jest True także dla przekroczonego czasu: proces wisiał, ale
        Android mógł już przyjąć wiadomość (odbiorca dostanie wtedy SMS
        odwołujący, a ponowienie sprawdzi najpierw skrzynkę)."""
        if not E164_RE.fullmatch(num):
            return False, "invalid number", False
        argv = ["termux-sms-send", "-n", num]
        if slot in (0, 1):
            argv += ["-s", str(slot)]
        rc, out, err = self._run(argv, text, SMS_SEND_TIMEOUT_S)
        detail = _clean(err or out)
        low = detail.lower()
        if "permission" in low:
            self.sms_permission = False
        if rc != 0 or any(w in low for w in ("error", "exception", "permission")):
            return False, detail or f"termux-sms-send exit {rc}", rc == RC_TIMEOUT
        self.sms_permission = True
        return True, "", True

    def su(self, command: str, timeout: float = SU_TIMEOUT_S) -> tuple[int, str, str]:
        """Jedno polecenie przez Magisk ``su -c`` (patrz :func:`su_argv`:
        tylko ciągi zbudowane z naszych stałych). Nigdy nie rzuca."""
        try:
            argv = su_argv(command)
        except ValueError:
            return 2, "", "refused: not a fixed command"
        return self._run(argv, None, timeout)


# ── wysyłka do listy odbiorców ────────────────────────────────────────────

#: Pola odbiorcy dodane po wersji 1.0.0 i ich wartości domyślne (stary
#: events.json dostaje je przy wczytaniu).
_RCPT_DEFAULTS = {"verified": None, "pre": None, "pre_failed": None, "fails": 0,
                  "handed": False, "sub_wall": None}


def new_rcpt(num: str, due: float) -> dict:
    """Odbiorca jednej wysyłki.

    ``pre``/``pre_failed``: ile pasujących wiadomości było w „wysłanych” /
    „nieudanych” PRZED pierwszym przekazaniem (punkt odniesienia kontroli,
    brany raz); ``fails``: ile wpisów „nieudane” już obsłużono ponowieniem;
    ``handed``: SMS mógł wyjść do tego odbiorcy (przekazany Androidowi
    choć raz) — taki odbiorca dostaje SMS odwołujący; ``sub_wall``: czas
    ścienny ostatniego przekazania (okno :data:`VERIFY_WINDOW_S`)."""
    return {"num": num, "st": "queued", "tries": 0, "err": "", **_RCPT_DEFAULTS,
            "_next": due, "_wait_since": None}


def new_delivery(kind: str, text: str, recipients: list, dry: bool, slot: int,
                 wall: float, due: float) -> dict:
    return {
        "kind": kind, "text": text, "dry": bool(dry), "slot": slot,
        "created_wall": wall, "out_wall": None, "no_retry": False,
        "rcpt": [new_rcpt(n, due) for n in recipients],
    }


def fill_delivery_defaults(d: dict) -> None:
    """Brakujące pola zapisanej wysyłki (starszy agent) — po walidacji."""
    d.setdefault("no_retry", False)
    for r in d["rcpt"]:
        for k, v in _RCPT_DEFAULTS.items():
            r.setdefault(k, v)


def delivery_done(d: dict) -> bool:
    return all(r["st"] in RCPT_FINAL for r in d["rcpt"])


def delivery_outcome(d: dict) -> str:
    rc = d["rcpt"]
    ok = sum(1 for r in rc if r["st"] in RCPT_OK)
    if rc and ok == len(rc):
        return "sent"
    return "partial" if ok else "failed"


def test_verified(d: Any) -> bool:
    """Testowy SMS naprawdę wysłany (nie ``dry_run``) i potwierdzony
    w „wysłanych” u każdego odbiorcy."""
    return isinstance(d, dict) and not d.get("dry") and bool(d.get("rcpt")) \
        and delivery_done(d) and all(r["st"] == "sent" and r.get("verified") is True
                                     for r in d["rcpt"])


def test_covers(d: Any, cfg: Mapping[str, Any]) -> bool:
    """Czy test objął WSZYSTKICH obecnych odbiorców (i ten sam slot SIM)?
    Test do numeru A nie dowodzi niczego o numerze B dopisanym później —
    a od potwierdzonego testu zależy, czy SMS po stłuczce jest prawdziwy."""
    if not isinstance(d, dict) or d.get("slot") != cfg.get("sim_slot"):
        return False
    tested = {r.get("num") for r in d.get("rcpt") or [] if isinstance(r, dict)}
    return bool(cfg.get("recipients")) and set(cfg["recipients"]) <= tested


def delivery_view(d: dict) -> list:
    return [{"to": mask_number(r["num"]), "state": r["st"], "tries": r["tries"],
             "verified": r["verified"], "error": r["err"]} for r in d["rcpt"]]


_RCPT_STATES = ("queued", "wait", "retry", "sending", "submitted", "verifying",
                *RCPT_FINAL)


def valid_delivery(d: Any) -> bool:
    """Kształt zapisanej wysyłki (plik mógł zostać uszkodzony albo podmieniony)."""
    if not isinstance(d, dict) or d.get("kind") not in ("crash", "cancel", "test", "call112"):
        return False
    if not isinstance(d.get("text"), str) or not isinstance(d.get("dry"), bool) \
            or d.get("slot") not in (0, 1) or isinstance(d.get("slot"), bool) \
            or _number(d.get("created_wall"), 0, EVENT_TS_MAX) is None:
        return False
    if d.get("out_wall") is not None and _number(d["out_wall"], 0, EVENT_TS_MAX) is None:
        return False
    if not isinstance(d.get("no_retry", False), bool):
        return False
    rcpt = d.get("rcpt")
    if not isinstance(rcpt, list) or len(rcpt) > MAX_RECIPIENTS:
        return False
    for r in rcpt:
        if not isinstance(r, dict) or not isinstance(r.get("num"), str) \
                or not E164_RE.fullmatch(r["num"]) or r.get("st") not in _RCPT_STATES \
                or _number(r.get("tries"), 0, 100, integer=True) is None \
                or not isinstance(r.get("err", ""), str) \
                or not isinstance(r.get("handed", False), bool) \
                or _number(r.get("fails", 0), 0, 10**6, integer=True) is None:
            return False
        for key in ("pre", "pre_failed"):
            if r.get(key) is not None and _number(r[key], 0, 10**6, integer=True) is None:
                return False
        if r.get("sub_wall") is not None and _number(r["sub_wall"], 0, EVENT_TS_MAX) is None:
            return False
        if r.get("verified") not in (None, True):
            return False
    return True


def valid_event(ev: Any) -> bool:
    if not isinstance(ev, dict) or not isinstance(ev.get("id"), str) \
            or not EVENT_ID_RE.fullmatch(ev["id"]) or ev.get("state") not in EVENT_STATES:
        return False
    if not isinstance(ev.get("dry"), bool) \
            or _number(ev.get("countdown_s"), COUNTDOWN_MIN_S, COUNTDOWN_MAX_S,
                       integer=True) is None \
            or _number(ev.get("created_wall"), 0, EVENT_TS_MAX) is None \
            or _number(ev.get("deadline_wall"), 0, EVENT_TS_MAX) is None \
            or _number(ev.get("event_ts"), EVENT_TS_MIN, EVENT_TS_MAX, integer=True) is None:
        return False
    if not valid_delivery(ev.get("crash")) or ev["crash"]["kind"] != "crash":
        return False
    if ev.get("cancel") is not None and not valid_delivery(ev["cancel"]):
        return False
    if ev.get("cancelled_wall") is not None \
            and _number(ev["cancelled_wall"], 0, EVENT_TS_MAX) is None:
        return False
    # Pola „Zadzwoń 112” (opcjonalne — starszy events.json ich nie ma).
    if ev.get("called_112_wall") is not None \
            and _number(ev["called_112_wall"], 0, EVENT_TS_MAX) is None:
        return False
    for key in ("c112_pending", "follow_up_used"):
        if not isinstance(ev.get(key, False), bool):
            return False
    if ev.get("c112") is not None and (not valid_delivery(ev["c112"])
                                       or ev["c112"]["kind"] != "call112"):
        return False
    label = ev.get("label")
    return label is None or (isinstance(label, str) and bool(LABEL_RE.fullmatch(label)))


def _persistable(obj: Any) -> Any:
    """Kopia bez pól czasu wykonania (``_…`` — zegar BOOTTIME tego startu)."""
    if isinstance(obj, dict):
        return {k: _persistable(v) for k, v in obj.items() if not str(k).startswith("_")}
    if isinstance(obj, list):
        return [_persistable(v) for v in obj]
    return obj


# ── agent ─────────────────────────────────────────────────────────────────

class Agent:
    """Stan agenta, uwierzytelnianie i obsługa endpointów. Bez wątków —
    :func:`main` uruchamia serwer, :meth:`run_scheduler` i
    :meth:`run_status`; testy wołają :meth:`handle` i :meth:`step` same.

    Args:
        state_dir: katalog stanu (tworzony z prawami 0700).
        runner: ``(argv, stdin, timeout) -> (rc, stdout, stderr)``.
        clock: CLOCK_BOOTTIME w sekundach (terminy).
        wall: czas ścienny (znaczniki, okno ±60 s, zapis terminów).
        localtime: ``time.localtime`` (godzina w SMS-ie).
    """

    def __init__(self, state_dir: str = DEFAULT_STATE_DIR, runner: Runner = default_runner,
                 clock: Callable[[], float] = boot_clock,
                 wall: Callable[[], float] = time.time,
                 localtime: Callable[[float], time.struct_time] = time.localtime) -> None:
        self.dir = state_dir
        self._clock = clock
        self._wall = wall
        self._localtime = localtime
        self.phone = Phone(runner, clock)
        self._lock = threading.Lock()
        self.wake = threading.Event()
        self._started = clock()
        self._auth_logged_at: Optional[float] = None
        self._pair_at: Optional[float] = None
        #: ``[kod, liczba złych prób]`` — licznik zeruje się z nowym kodem.
        self._pair_fails: list = [None, 0]
        self._pair_closed_logged_at: Optional[float] = None
        self._status: dict[str, Any] = {"sim_ready": None, "battery": None}
        self._status_ts: Optional[float] = None
        self._health_at: Optional[float] = None
        #: Budzi wątek stanu (health ze starą pamięcią podręczną, stop).
        self.status_kick = threading.Event()
        os.makedirs(self.dir, mode=0o700, exist_ok=True)
        try:
            os.chmod(self.dir, 0o700)
        except OSError:
            pass
        self._key: Optional[bytes] = self._load_secret()
        self._nonce = self._load_nonce()
        self.config = self._load_config()
        self.meta = self._load_json("meta.json", {"last_test_wall": None, "last_sent_ts": None,
                                                  "last_verified_test_ts": None, "test": None,
                                                  "call112_wall": None})
        test = self.meta.get("test")
        if test is not None and not (isinstance(test, dict)
                                     and valid_delivery(test.get("delivery"))):
            self.meta["test"] = None
        elif test is not None:
            fill_delivery_defaults(test["delivery"])
        for key in ("last_test_wall", "last_sent_ts", "last_verified_test_ts", "call112_wall"):
            if _number(self.meta.get(key), 0, EVENT_TS_MAX) is None:
                self.meta[key] = None
        self.events: list[dict] = self._load_events()
        # „Zadzwoń 112”: bieżące (albo ostatnie) połączenie — tylko w
        # pamięci (po restarcie agenta stan rozmowy i tak jest nieznany;
        # limit 1 na minutę jest w meta.json). ``su`` sprawdzany w wątku
        # stanu: None = jeszcze nie wiadomo.
        self.call: Optional[dict] = None
        self._call_seq = 0
        self.call_wake = threading.Event()
        self._su_ok: Optional[bool] = None
        self._su_checked: Optional[float] = None
        self._call_state: Optional[int] = None
        self._resume()

    # ── pliki ────────────────────────────────────────────────────────────

    def _path(self, name: str) -> str:
        return os.path.join(self.dir, name)

    def _load_json(self, name: str, default: Any) -> Any:
        try:
            raw = read_small(self._path(name))
            if raw is None:
                return default
            obj = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant)
        except (OSError, ValueError, UnicodeDecodeError, RecursionError) as e:
            log.warning("Cannot read %s (%s) — starting from defaults", name, _clean(e))
            return default
        return obj if isinstance(obj, type(default)) else default

    def _save_json(self, name: str, obj: Any) -> None:
        atomic_write(self._path(name), canonical_json(_persistable(obj)).encode("ascii"))

    def _load_secret(self) -> Optional[bytes]:
        try:
            raw = read_small(self._path("secret"), 1024)
        except (OSError, ValueError):
            raw = None
        if raw is None:
            return None
        text = raw.decode("ascii", "replace").strip().lower()
        if not SECRET_RE.fullmatch(text) or len(text) % 2:
            log.warning("Stored secret is invalid — the agent is unpaired")
            return None
        return bytes.fromhex(text)

    def _load_nonce(self) -> int:
        try:
            raw = read_small(self._path("nonce"), 64)
        except (OSError, ValueError):
            raw = None
        text = raw.decode("ascii", "replace").strip() if raw else "0"
        return int(text) if DIGITS_RE.fullmatch(text) else 0

    def _load_config(self) -> dict:
        cfg = self._load_json("config.json", {})
        norm, _err = normalize_config(cfg)
        return norm if norm is not None else default_config()

    def _load_events(self) -> list:
        """Zdarzenia z dysku; uszkodzony wpis jest pomijany (z ostrzeżeniem),
        zamiast wywracać harmonogram przy każdym kroku."""
        obj = self._load_json("events.json", {"events": []})
        events = obj.get("events") if isinstance(obj, dict) else None
        out = []
        for ev in events if isinstance(events, list) else []:
            if valid_event(ev):
                for key in ("crash", "cancel", "c112"):
                    if isinstance(ev.get(key), dict):
                        fill_delivery_defaults(ev[key])
                out.append(ev)
            else:
                log.warning("Skipping a damaged event record in events.json")
        return out[-MAX_EVENTS:]

    def _save_events(self) -> None:
        self._save_json("events.json", {"version": 1, "events": self.events})

    def _save_meta(self) -> None:
        self._save_json("meta.json", self.meta)

    @property
    def paired(self) -> bool:
        return self._key is not None

    @property
    def pairing_open(self) -> bool:
        return os.path.isfile(self._path("PAIRING"))

    def pairing_code(self) -> Optional[str]:
        """Kod parowania z pliku ``PAIRING`` albo None (plik nie istnieje).

        Pusty albo nieprawidłowy plik (``touch``) dostaje świeży losowy kod
        (zapis atomowy, 0600) — użytkownik czyta go ``cat``-em. Kodu nie
        loguję: log leży w tym samym katalogu, ale kod ma znać tylko ten,
        kto patrzy na ekran telefonu."""
        path = self._path("PAIRING")
        if not os.path.isfile(path):
            return None
        try:
            raw = read_small(path, 64)
        except (OSError, ValueError):
            raw = b""
        text = (raw or b"").decode("ascii", "replace").strip()
        if PAIR_CODE_RE.fullmatch(text):
            return text
        code = new_pairing_code()
        try:
            atomic_write(path, (code + "\n").encode("ascii"))
        except OSError as e:
            log.error("Cannot write the pairing code into PAIRING (%s)", _clean(e))
            return None
        log.info("Pairing code written into %s — show it with: cat %s", path, path)
        return code

    # ── wznowienie po restarcie ───────────────────────────────────────────

    def _resume(self) -> None:
        """Zdarzenia sprzed restartu: odliczanie z zapisanego terminu
        ściennego (nie dłużej niż pierwotne odliczanie), po terminie —
        wysyłka od razu, jeśli minęło < 30 min, inaczej ``failed``.
        Wysyłka odwołanego zdarzenia, która była „w locie”, NIE jest
        powtarzana (:meth:`_reset_runtime`) — ten odbiorca dostaje tylko SMS
        odwołujący."""
        now = self._clock()
        wall = self._wall()
        changed = False
        for ev in self.events:
            interrupted: list = []
            for key in ("crash", "cancel", "c112"):
                d = ev.get(key)
                if isinstance(d, dict):
                    found = self._reset_runtime(d, now)
                    if key == "crash":
                        interrupted += found
            state = ev["state"]
            if state == "armed":
                rem = float(ev.get("deadline_wall", 0)) - wall
                if rem > 0:
                    ev["_deadline"] = now + min(rem, float(ev.get("countdown_s", COUNTDOWN_MAX_S)))
                elif -rem <= RESUME_MAX_LATE_S:
                    ev["_deadline"] = now
                    log.warning("Event %s: deadline passed while the agent was down — "
                                "sending now", ev["id"])
                else:
                    self._expire(ev)
                    changed = True
            elif state in ("pending", "sending"):
                if wall - float(ev.get("deadline_wall", 0)) > RESUME_MAX_LATE_S:
                    self._expire(ev)
                    changed = True
                else:
                    log.warning("Event %s: resuming the interrupted sending", ev["id"])
            if interrupted:
                # Odwołane, a SMS o wypadku do tych odbiorców był „w locie”
                # przy restarcie: mógł wyjść, więc nie wysyłam go ponownie,
                # tylko dopisuję ich do SMS-a odwołującego (jeśli włączony
                # i w oknie 15 min) — lepiej zbędne „ODWOLANE” niż alarm
                # bez odwołania.
                for num in interrupted:
                    self._follow_up(ev, num)
                changed = True
            d = ev.get("cancel")
            if isinstance(d, dict) and not delivery_done(d) \
                    and wall - float(d.get("created_wall", 0)) > CANCEL_WINDOW_S:
                self._fail_rest(d, "expired")
                changed = True
        test = self.meta.get("test")
        if isinstance(test, dict) and isinstance(test.get("delivery"), dict):
            d = test["delivery"]
            self._reset_runtime(d, now)
            if not delivery_done(d) and wall - float(d.get("created_wall", 0)) > RESUME_MAX_LATE_S:
                self._fail_rest(d, "expired")
                test["state"] = delivery_outcome(d)
                changed = True
        if changed:
            self._persist_quietly()

    @staticmethod
    def _reset_runtime(d: dict, now: float) -> list:
        """Pola czasu wykonania po restarcie. Zwraca numery odbiorców, do
        których wysyłka była „w locie”, gdy przyszło odwołanie (``no_retry``)
        — patrz :meth:`_resume`."""
        stop = bool(d.get("no_retry"))
        interrupted = []
        for r in d.get("rcpt", []):
            r["_next"] = now
            r["_wait_since"] = None
            st = r.get("st")
            # Stan „w locie” mógł trafić na dysk razem z cudzym zapisem
            # (np. odwołania). Wysyłka nieznana → jeszcze raz (możliwy
            # duplikat), kontrola → kontrola od nowa. ALE po odwołaniu nigdy
            # nie wysyłam ponownie: odwołanie jest ostateczne.
            if st == "sending" and stop:
                r["st"] = "failed"
                r["err"] = "cancelled; send interrupted, outcome unknown"
                r["handed"] = True
                interrupted.append(r["num"])
            elif st == "sending":
                r["st"] = "retry" if r.get("tries") else "queued"
            elif st == "verifying":
                r["st"] = "submitted"
            elif stop and st in ("queued", "wait", "retry"):
                r["st"] = "skipped"
                r["err"] = "cancelled"
        return interrupted

    @staticmethod
    def _fail_rest(d: dict, why: str) -> None:
        for r in d["rcpt"]:
            if r["st"] not in RCPT_FINAL:
                r["st"] = "failed"
                r["err"] = why

    def _expire(self, ev: dict) -> None:
        d = ev.get("crash")
        if isinstance(d, dict):
            self._fail_rest(d, "expired")
            ev["state"] = delivery_outcome(d)
        else:
            ev["state"] = "failed"
        ev["error"] = "expired"
        log.warning("Event %s expired while the agent was down — marked %s", ev["id"],
                    ev["state"])

    def _persist_quietly(self) -> bool:
        try:
            self._save_events()
            self._save_meta()
            return True
        except OSError as e:
            log.error("Saving the agent state failed: %s", _clean(e))
            return False

    # ── HTTP ──────────────────────────────────────────────────────────────

    def handle(self, method: str, path: str, headers: Mapping[str, str],
               body: bytes) -> tuple[int, bytes, dict]:
        """Jedno żądanie → ``(status, treść, nagłówki)``. Nigdy nie rzuca."""
        try:
            return self._handle(method, path, headers, body)
        except Exception:
            log.exception("Request %s %s failed", method, path[:64])
            return self._reply(500, {"error": "internal"})

    def _reply(self, status: int, obj: dict, nonce: Optional[int] = None,
               key: Optional[bytes] = None) -> tuple[int, bytes, dict]:
        """Podpis TYLKO, gdy żądanie było uwierzytelnione (``nonce`` i klucz)."""
        data = canonical_json(obj).encode("ascii")
        hdrs = {"Content-Type": "application/json"}
        key = key if key is not None else self._key
        if nonce is not None and key is not None:
            hdrs["X-BCM-Sig"] = sign(key, response_message(status, nonce, data))
        return status, data, hdrs

    def _unauth(self, status: int, error: str) -> tuple[int, bytes, dict]:
        """Odpowiedź dla nieuwierzytelnionego klienta: bez podpisu i BEZ
        informacji o parowaniu (czy jest plik PAIRING) — obcy proces nie może
        po niej czekać na okno parowania. ``time`` zostaje: BCM pokazuje
        z niego różnicę zegarów przy ``stale_ts``."""
        return self._reply(status, {"error": error, "version": VERSION,
                                    "time": int(self._wall())})

    def _route(self, method: str, path: str) -> tuple[Optional[str], Optional[str], bool]:
        """``(nazwa trasy, id zdarzenia, metoda pasuje)``; nazwa None = 404."""
        if path == "/v1/health":
            return "health", None, method == "GET"
        if path == "/v1/config":
            return "config", None, method == "PUT"
        if path == "/v1/crash":
            return "arm", None, method == "POST"
        if path == "/v1/test":
            return "test", None, method == "POST"
        if path == "/v1/pair":
            return "pair", None, method == "POST"
        if path == "/v1/call112":
            return ("call112_get" if method == "GET" else "call112"), None, \
                method in ("GET", "POST")
        if path == "/v1/call112/hangup":
            return "call112_hangup", None, method == "POST"
        if path == "/v1/call112/mark":
            return "call112_mark", None, method == "POST"
        parts = path.split("/")
        if len(parts) in (4, 5) and parts[0] == "" and parts[1] == "v1" and parts[2] == "crash" \
                and EVENT_ID_RE.fullmatch(parts[3]):
            if len(parts) == 4:
                return "get", parts[3], method == "GET"
            if parts[4] == "cancel":
                return "cancel", parts[3], method == "POST"
            if parts[4] == "send_now":
                return "send_now", parts[3], method == "POST"
        return None, None, False

    def _handle(self, method: str, path: str, headers: Mapping[str, str],
                body: bytes) -> tuple[int, bytes, dict]:
        if len(path) > MAX_PATH or len(body) > MAX_BODY:
            return self._reply(413 if len(body) > MAX_BODY else 414, {"error": "too_large"})
        name, event_id, method_ok = self._route(method, path)
        if name is None:
            return self._reply(404, {"error": "not_found"})
        if not method_ok:
            return self._reply(405, {"error": "method_not_allowed"})
        if name == "pair":
            return self._pair(headers, body)
        if self._key is None:
            return self._unauth(403, "unpaired")
        nonce, err = self._authenticate(method, path, headers, body)
        if err == "replay":
            # Podpis był dobry, tylko nonce stary: podpisana odpowiedź
            # pozwala BCM przeskoczyć licznik po utracie swojego pliku.
            with self._lock:
                floor = self._nonce + 1
            return self._reply(409, {"error": "replay", "min_nonce": floor}, nonce)
        if err == "storage":
            return self._reply(500, {"error": "storage"})
        if err:
            return self._unauth(401, err)
        assert nonce is not None
        try:
            obj = parse_json_object(body) if method != "GET" else {}
            if method == "GET" and body:
                raise ValueError("GET with a body")
        except (ValueError, UnicodeDecodeError, RecursionError) as e:
            return self._reply(400, {"error": "bad_json", "detail": _clean(e, 80)}, nonce)
        if name == "health":
            status, out = 200, self.health()
        elif name == "config":
            status, out = self.put_config(obj)
        elif name == "arm":
            status, out = self.arm(obj)
        elif name == "test":
            status, out = self.test(obj)
        elif name == "get":
            status, out = self.get_event(event_id)
        elif name == "cancel":
            status, out = self.cancel(event_id)
        elif name == "call112":
            status, out = self.call112(obj)
        elif name == "call112_get":
            status, out = self.call112_view()
        elif name == "call112_hangup":
            status, out = self.call112_hangup(obj)
        elif name == "call112_mark":
            status, out = self.call112_mark(obj)
        else:
            status, out = self.send_now(event_id)
        return self._reply(status, out, nonce)

    def _authenticate(self, method: str, path: str, headers: Mapping[str, str],
                      body: bytes) -> tuple[Optional[int], str]:
        """``(nonce, "")`` dla poprawnego żądania; nonce zapisany na dysku,
        ZANIM żądanie zostanie wykonane. Kolejność: format → okno czasu →
        HMAC → nonce."""
        ts_s = (headers.get("X-BCM-Ts") or "").strip()
        nonce_s = (headers.get("X-BCM-Nonce") or "").strip()
        sig = (headers.get("X-BCM-Sig") or "").strip().lower()
        if not DIGITS_RE.fullmatch(ts_s) or not DIGITS_RE.fullmatch(nonce_s) \
                or not SIG_RE.fullmatch(sig):
            self._log_auth("missing or malformed auth headers")
            return None, "bad_auth"
        ts, nonce = int(ts_s), int(nonce_s)
        if abs(ts - self._wall()) > TS_WINDOW_S:
            self._log_auth(f"timestamp {ts} outside ±{TS_WINDOW_S} s")
            return None, "stale_ts"
        key = self._key
        assert key is not None
        expected = sign(key, request_message(method, path, ts, nonce, body))
        if not hmac.compare_digest(expected, sig):
            self._log_auth("bad signature")
            return None, "bad_auth"
        with self._lock:
            if nonce <= self._nonce:
                self._log_auth(f"replayed nonce ({nonce} <= {self._nonce})")
                return nonce, "replay"
            try:
                atomic_write(self._path("nonce"), str(nonce).encode("ascii"))
            except OSError as e:
                log.error("Cannot save the nonce (%s) — request refused", _clean(e))
                return None, "storage"
            self._nonce = nonce
        return nonce, ""

    def _log_auth(self, why: str) -> None:
        now = self._clock()
        if self._auth_logged_at is None or now - self._auth_logged_at >= AUTH_LOG_EVERY_S:
            self._auth_logged_at = now
            log.warning("Unauthenticated request refused: %s", why)

    # ── parowanie ─────────────────────────────────────────────────────────

    def _pair(self, headers: Mapping[str, str], body: bytes) -> tuple[int, bytes, dict]:
        """``POST /v1/pair {secret}`` — tylko przy pliku ``PAIRING`` i tylko
        z podpisem HMAC zrobionym kodem parowania z tego pliku (ten sam
        schemat co dla innych żądań, kod zamiast sekretu; okno ±60 s).
        Kod zna tylko ten, kto widzi ekran telefonu — inny lokalny proces
        (aplikacja w telefonie, użytkownik kiosku na komputerze BCM), który
        też dosięga agenta, nie sparuje się pierwszy. Odpowiedź jest
        podpisana NOWYM sekretem nad nonce żądania, więc BCM wie, że agent
        zapisał właśnie jego.

        Kolejność: plik → format nagłówków i treści → limit prób (liczony
        tylko dla poprawnie zbudowanych prób, więc śmieci go nie zużyją) →
        okno czasu → podpis kodem. Po :data:`PAIR_MAX_FAILS` złych kodach
        plik ``PAIRING`` jest usuwany."""
        code = self.pairing_code()
        if code is None:
            now = self._clock()
            if self._pair_closed_logged_at is None \
                    or now - self._pair_closed_logged_at >= AUTH_LOG_EVERY_S:
                self._pair_closed_logged_at = now
                log.warning("Pairing refused: no PAIRING file in %s (create one: "
                            "python bcm_agent.py --pair)", self.dir)
            return self._unauth(403, "pairing_closed")
        ts_s = (headers.get("X-BCM-Ts") or "").strip()
        nonce_s = (headers.get("X-BCM-Nonce") or "").strip()
        sig = (headers.get("X-BCM-Sig") or "").strip().lower()
        if not DIGITS_RE.fullmatch(ts_s) or not DIGITS_RE.fullmatch(nonce_s) \
                or not SIG_RE.fullmatch(sig):
            return self._unauth(400, "bad_request")
        try:
            obj = parse_json_object(body)
        except (ValueError, UnicodeDecodeError, RecursionError):
            return self._unauth(400, "bad_json")
        secret = obj.get("secret")
        if not isinstance(secret, str) or not SECRET_RE.fullmatch(secret.strip().lower()) \
                or len(secret.strip()) % 2:
            return self._unauth(400, "bad_secret")
        now = self._clock()
        with self._lock:
            limited = self._pair_at is not None and now - self._pair_at < PAIR_MIN_INTERVAL_S
            if not limited:
                self._pair_at = now
        if limited:
            return self._unauth(429, "rate_limited")
        ts, nonce = int(ts_s), int(nonce_s)
        if abs(ts - self._wall()) > TS_WINDOW_S:
            return self._unauth(401, "stale_ts")
        expected = sign(code.encode("ascii"), request_message("POST", "/v1/pair", ts, nonce,
                                                               body))
        if not hmac.compare_digest(expected, sig):
            return self._pair_failed(code)
        text = secret.strip().lower()
        with self._lock:
            # Podłoga nonce tylko rośnie: parowanie (nawet tym samym
            # sekretem) nie może otworzyć powtórki starszych żądań.
            floor = max(self._nonce, nonce)
            try:
                atomic_write(self._path("secret"), text.encode("ascii"))
                atomic_write(self._path("nonce"), str(floor).encode("ascii"))
            except OSError as e:
                log.error("Pairing failed: cannot store the secret (%s)", _clean(e))
                return self._unauth(500, "storage")
            self._key = bytes.fromhex(text)
            self._nonce = floor
            self._pair_fails = [None, 0]
        try:
            os.unlink(self._path("PAIRING"))
        except OSError as e:
            log.warning("Paired, but the PAIRING file could not be removed (%s) — remove "
                        "it by hand, or the agent accepts a new pairing", _clean(e))
        log.info("Paired with BCM (new secret stored, PAIRING removed)")
        return self._reply(200, {"paired": True, "version": VERSION}, nonce)

    def _pair_failed(self, code: str) -> tuple[int, bytes, dict]:
        """Zły kod parowania: licznik prób dla TEGO kodu; po
        :data:`PAIR_MAX_FAILS` plik PAIRING znika (nowy kod: ``--pair``)."""
        with self._lock:
            if self._pair_fails[0] != code:
                self._pair_fails = [code, 0]
            self._pair_fails[1] += 1
            fails = self._pair_fails[1]
            if fails >= PAIR_MAX_FAILS:
                self._pair_fails = [None, 0]
        if fails >= PAIR_MAX_FAILS:
            try:
                os.unlink(self._path("PAIRING"))
            except OSError:
                pass
            log.warning("Pairing closed after %d wrong codes — someone may be guessing; "
                        "create a new code with: python bcm_agent.py --pair", PAIR_MAX_FAILS)
            return self._unauth(403, "pairing_closed")
        log.warning("Pairing refused: wrong pairing code (%d of %d)", fails, PAIR_MAX_FAILS)
        return self._unauth(401, "bad_code")

    # ── endpointy ─────────────────────────────────────────────────────────

    def health(self) -> dict:
        """``GET /v1/health``: wersja, czas działania, SIM, bateria (z
        odświeżania w tle — odpowiedź nigdy nie czeka na Termux:API; to, że
        ktoś pyta, włącza odświeżanie, patrz :meth:`run_status`).

        ``last_test.verified``: True tylko, gdy prawdziwy (nie ``dry_run``)
        testowy SMS do KAŻDEGO odbiorcy widniał w „wysłanych”;
        ``last_verified_test_ts`` — kiedy ostatnio tak było (warunek planu F
        przed włączeniem prawdziwych SMS-ów)."""
        now = self._clock()
        with self._lock:
            self._health_at = now
            stale = self._status_ts is None or now - self._status_ts >= STATUS_REFRESH_S
            active = next((e["id"] for e in self.events if e["state"] in EVENT_ACTIVE), None)
            test = self.meta.get("test")
            last_test = None
            if isinstance(test, dict):
                last_test = {"state": test.get("state"), "ts": test.get("wall"),
                             "dry_run": test.get("dry"),
                             "verified": test_verified(test.get("delivery"))
                             and test_covers(test.get("delivery"), self.config)}
            out = {
                "version": VERSION,
                "uptime_s": int(self._clock() - self._started),
                "paired": True,
                "pairing": self.pairing_open,
                "sim_ready": self._status.get("sim_ready"),
                "battery": self._status.get("battery"),
                "sms_permission": self.phone.sms_permission,
                "last_sent_ts": self.meta.get("last_sent_ts"),
                "toggles": dict(self.config["toggles"]),
                "dry_run": self.config["dry_run"],
                "recipients_n": len(self.config["recipients"]),
                "config_hash": config_hash(self.config),
                "active_event": active,
                "last_test": last_test,
                "last_verified_test_ts": self.meta.get("last_verified_test_ts"),
                "time": int(self._wall()),
                # „Zadzwoń 112” (plan H): gotowość, tryb, stan rozmowy.
                "call112_capable": self._call112_capable(),
                "call112_mode": "test" if self.config["call112_test_mode"] else "real",
                "call_state": self._call_state,
                "call112_call": self._call_view_locked(),
            }
            su_due = self.config["toggles"]["call112"] and self._su_probe_due(now)
        if stale or su_due:
            self.status_kick.set()
        return out

    def _call112_capable(self) -> bool:
        """(pod blokadą) Przełącznik włączony, ``su`` działa, a w trybie
        testowym jest numer testowy — tylko wtedy BCM pokaże ścieżkę B."""
        cfg = self.config
        if not cfg["toggles"]["call112"] or self._su_ok is not True:
            return False
        return not cfg["call112_test_mode"] or bool(E164_RE.fullmatch(cfg["call112_test_number"]))

    def _su_probe_due(self, now: float) -> bool:
        if self._su_checked is None:
            return True
        every = SU_PROBE_OK_S if self._su_ok else SU_PROBE_FAIL_S
        return now - self._su_checked >= every

    def put_config(self, obj: dict) -> tuple[int, dict]:
        """``PUT /v1/config`` — pełna konfiguracja (patrz
        :func:`normalize_config`), zapisana przed odpowiedzią."""
        norm, err = normalize_config(obj, strict=True)
        if norm is None:
            return 400, {"error": "bad_config", "detail": err}
        with self._lock:
            try:
                self._save_json("config.json", norm)
            except OSError as e:
                log.error("Cannot save the config: %s", _clean(e))
                return 500, {"error": "storage"}
            changed = norm != self.config
            # Inny zestaw odbiorców albo slot SIM: potwierdzony test ich nie
            # dotyczył — BCM wróci do trybu testowego do nowego testu.
            # (Zmiana samych przełączników / dry_run / etykiety go nie kasuje.)
            retest = (set(norm["recipients"]) != set(self.config["recipients"])
                      or norm["sim_slot"] != self.config["sim_slot"]) \
                and self.meta.get("last_verified_test_ts") is not None
            self.config = norm
            if retest:
                self.meta["last_verified_test_ts"] = None
                try:
                    self._save_meta()
                except OSError as e:
                    log.error("Cannot save the test state: %s", _clean(e))
        if retest:
            log.warning("Recipients or SIM slot changed — the verified test no longer counts; "
                        "send a new test SMS")
        if changed:
            log.info("Config updated: %d recipient(s), slot %d, toggles %s, dry_run=%s, "
                     "112: %s", len(norm["recipients"]), norm["sim_slot"],
                     ",".join(k for k, v in norm["toggles"].items() if v) or "-",
                     norm["dry_run"],
                     ("TEST -> " + mask_number(norm["call112_test_number"])
                      if norm["call112_test_number"] else "TEST (no number)")
                     if norm["call112_test_mode"] else "real")
        if norm["toggles"]["call112"]:
            # ``su`` sprawdzony od razu, nie przy następnym odświeżeniu stanu.
            self.status_kick.set()
        return 200, {"ok": True, "config_hash": config_hash(norm)}

    def arm(self, obj: dict) -> tuple[int, dict]:
        """``POST /v1/crash`` — uzbrojenie; idempotentne po ``event_id``,
        zapisane na dysku przed odpowiedzią. Od tej chwili termin pilnuje
        agent: bez ``cancel`` SMS-y wychodzą po ``countdown_s``."""
        params, err = validate_crash(obj)
        if params is None:
            return 400, {"error": "bad_request", "detail": err}
        eid = params["event_id"]
        with self._lock:
            ev = self._find(eid)
            if ev is not None:
                if ev.get("_unsaved"):
                    if self._try_save_events():
                        ev.pop("_unsaved", None)
                    else:
                        return 500, {"error": "storage", "id": eid}
                return 200, dict(self._event_view(ev), created=False)
            cfg = self.config
            if not cfg["toggles"]["crash_sms"]:
                return 409, {"error": "crash_sms_off"}
            if not cfg["recipients"]:
                return 409, {"error": "no_recipients"}
            # dry liczony PRZED limitem: zdarzenie testowe nie blokuje
            # prawdziwego (patrz _crash_limit).
            dry = bool(cfg["dry_run"] or params["dry_run"])
            self._prune()
            wait = self._crash_limit(dry)
            if wait is not None:
                log.warning("Event %s refused: crash SMS limit (1 per %d min, %d per day)",
                            eid, CRASH_COOLDOWN_S // 60, CRASH_MAX_PER_DAY)
                return 429, {"error": "rate_limited", "retry_after": wait}
            if len(self.events) >= MAX_EVENTS:
                return 429, {"error": "too_many_events", "retry_after": 600}
            now, wall = self._clock(), self._wall()
            countdown = int(params["countdown_s"])
            text = crash_text(cfg["vehicle_label"], params["event_ts"], params["lat"],
                              params["lon"], params["fix_age_s"], params["speed_kmh"],
                              params["dv_kmh"], self._localtime)
            ev = {
                "id": eid, "state": "armed", "dry": dry, "countdown_s": countdown,
                "created_wall": wall, "deadline_wall": wall + countdown,
                "event_ts": params["event_ts"], "follow_up_cancel": cfg["follow_up_cancel"],
                "label": cfg["vehicle_label"], "error": "",
                "crash": new_delivery("crash", text, list(cfg["recipients"]), dry,
                                      cfg["sim_slot"], wall, now + countdown),
                "cancel": None, "_deadline": now + countdown,
            }
            self.events.append(ev)
            saved = self._try_save_events()
            if not saved:
                ev["_unsaved"] = True
        self.wake.set()
        log.warning("Event %s ARMED: SMS to %d recipient(s) in %d s%s", eid,
                    len(ev["crash"]["rcpt"]), countdown, " (dry run)" if dry else "")
        if not saved:
            return 500, {"error": "storage", "id": eid}
        return 200, dict(self._event_view(ev), created=True)

    def cancel(self, eid: str) -> tuple[int, dict]:
        """``POST /v1/crash/<id>/cancel``. Przed wysyłką: nic nie wychodzi
        (ostatecznie — także odbiorca, którego wysyłka jest właśnie
        sprawdzana, patrz :meth:`_run_action`). Gdy SMS o wypadku mógł już
        wyjść do kogoś (przekazany Androidowi choć raz, nawet jeśli czeka na
        ponowienie): jeden SMS odwołujący do tych odbiorców
        (``follow_up_cancel``, w ciągu 15 min) — nigdy drugi."""
        with self._lock:
            ev = self._find(eid)
            if ev is None:
                return 404, {"error": "unknown_event"}
            if ev["state"] == "cancelled":
                return 200, self._event_view(ev)
            d = ev["crash"]
            went = [r["num"] for r in d["rcpt"]
                    if r.get("handed") or r["st"] in ("submitted", "verifying", "sent",
                                                      "sent_dry")]
            for r in d["rcpt"]:
                if r["st"] in ("queued", "wait", "retry"):
                    r["st"] = "skipped"
                    r["err"] = "cancelled"
            d["no_retry"] = True
            ev["state"] = "cancelled"
            ev["cancelled_wall"] = self._wall()
            self._maybe_cancel_sms(ev, went)
            self._try_save_events()
            view = self._event_view(ev)
        self.wake.set()
        log.warning("Event %s CANCELLED%s", eid,
                    " — cancel SMS queued" if ev.get("cancel") else "")
        return 200, view

    def _maybe_cancel_sms(self, ev: dict, went: list) -> None:
        d = ev["crash"]
        if not went or not ev.get("follow_up_cancel", True) or ev.get("cancel") is not None:
            return
        if ev.get("follow_up_used"):
            # Jedyny SMS uzupełniający tego zdarzenia poszedł (albo pójdzie)
            # jako „Z auta wybrano 112” — budżet SMS-a odwołującego zużyty.
            log.info("Event %s: the follow-up SMS budget went to the 112 notice — no cancel "
                     "SMS", ev["id"])
            return
        # Okno 15 min od wyjścia SMS-a o wypadku; gdy nic nie zostało
        # potwierdzone jako przekazane (wysyłka przerwana restartem) — od
        # odwołania.
        start = d.get("out_wall")
        if start is None:
            start = ev.get("cancelled_wall")
        if start is not None and self._wall() - float(start) > CANCEL_WINDOW_S:
            log.info("Event %s: crash SMS went out more than %d min ago — no cancel SMS",
                     ev["id"], CANCEL_WINDOW_S // 60)
            return
        text = cancel_text(ev.get("label") or DEFAULT_LABEL, int(ev["event_ts"]),
                           self._localtime)
        ev["cancel"] = new_delivery("cancel", text, went, d["dry"], d["slot"], self._wall(),
                                    self._clock())

    def send_now(self, eid: str) -> tuple[int, dict]:
        """``POST /v1/crash/<id>/send_now`` — termin teraz (tylko ``armed``)."""
        with self._lock:
            ev = self._find(eid)
            if ev is None:
                return 404, {"error": "unknown_event"}
            if ev["state"] == "armed":
                now = self._clock()
                ev["_deadline"] = now
                for r in ev["crash"]["rcpt"]:
                    r["_next"] = now
            view = self._event_view(ev)
        self.wake.set()
        return 200, view

    def get_event(self, eid: str) -> tuple[int, dict]:
        with self._lock:
            ev = self._find(eid)
            if ev is None:
                return 404, {"error": "unknown_event"}
            return 200, self._event_view(ev)

    def test(self, obj: dict) -> tuple[int, dict]:
        """``POST /v1/test`` — SMS testowy do wszystkich odbiorców, najwyżej
        raz na 10 min (zapisane). Bez pól: jak w konfiguracji (``dry_run``).
        ``dry_run: true`` wymusza tryb testowy. ``real_test: true`` wysyła
        naprawdę MIMO ``dry_run`` w konfiguracji — osobne, jawne pole, bo
        tylko tak da się sprawdzić prawdziwą wysyłkę, zanim alarm wypadkowy
        wyjdzie z trybu testowego (treść testu jest niegroźna), a zwykłe
        żądanie nigdy nie omija ``dry_run`` po cichu. ``dry_run: false`` jest
        odrzucane (dwuznaczne)."""
        dry_req = obj.get("dry_run")
        real = obj.get("real_test")
        if dry_req is not None and dry_req is not True:
            return 400, {"error": "bad_request",
                         "detail": "dry_run can only be true; a real test is real_test: true"}
        if real is not None and not isinstance(real, bool):
            return 400, {"error": "bad_request", "detail": "real_test must be a boolean"}
        if dry_req and real:
            return 400, {"error": "bad_request", "detail": "dry_run and real_test together"}
        with self._lock:
            cfg = self.config
            if not cfg["recipients"]:
                return 409, {"error": "no_recipients"}
            wall = self._wall()
            last = self.meta.get("last_test_wall")
            if isinstance(last, (int, float)) and abs(wall - last) < TEST_COOLDOWN_S:
                return 429, {"error": "rate_limited",
                             "retry_after": _wait_s(TEST_COOLDOWN_S - abs(wall - last))}
            dry = True if dry_req else (False if real else cfg["dry_run"])
            d = new_delivery("test", test_text(cfg["vehicle_label"]), list(cfg["recipients"]),
                             dry, cfg["sim_slot"], wall, self._clock())
            self.meta["last_test_wall"] = wall
            self.meta["test"] = {"state": "pending", "wall": wall, "dry": dry, "delivery": d}
            try:
                self._save_meta()
            except OSError as e:
                log.error("Cannot save the test state: %s", _clean(e))
        self.wake.set()
        log.info("Test SMS queued for %d recipient(s)%s", len(d["rcpt"]),
                 " (dry run)" if dry else "")
        return 200, {"ok": True, "state": "pending", "dry_run": dry}

    # ── „Zadzwoń 112” (plan H, ścieżka B) ─────────────────────────────────

    def call112(self, obj: dict) -> tuple[int, dict]:
        """``POST /v1/call112 {"mode": "real"|"test"}`` — połączenie
        z głośnikiem z TEGO telefonu. Numer nigdy nie przychodzi z żądania
        (112 to stała; w teście numer z konfiguracji agenta). ``mode`` to
        tylko strażnik: musi zgadzać się z trybem agenta, inaczej 409 — po
        zmianie konfiguracji w BCM, której telefon jeszcze nie dostał, nic
        nie wybierze „nie tego” numeru. Samo połączenie robi wątek
        połączeń (:meth:`call_step`); odpowiedź wraca od razu."""
        mode = obj.get("mode")
        eid = obj.get("event_id")
        if set(obj) != {"mode", "event_id"} or mode not in CALL_MODES \
                or not isinstance(eid, str) or not EVENT_ID_RE.fullmatch(eid):
            return 400, {"error": "bad_request",
                         "detail": 'body: {"mode": "real"|"test", "event_id": "<hex>"}'}
        with self._lock:
            cfg = self.config
            if not cfg["toggles"]["call112"]:
                return 409, {"error": "call112_off"}
            mine = "test" if cfg["call112_test_mode"] else "real"
            if mode != mine:
                log.warning("112 call refused: BCM expects %s mode, the agent is in %s mode "
                            "(config not synced yet?)", mode, mine)
                return 409, {"error": "mode_mismatch", "mode": mine}
            number = cfg["call112_test_number"] if mine == "test" else None
            if mine == "test" and not E164_RE.fullmatch(number or ""):
                return 409, {"error": "no_test_number"}
            if self._su_ok is False:
                return 409, {"error": "no_root"}
            if self.call is not None and self.call["state"] in CALL_ACTIVE \
                    and not self.call["final"]:
                # Połączenie „final” w stanie placed (stanu rozmowy nie da się
                # odczytać) już nie blokuje — inaczej po takim jednym 112
                # kolejne byłoby niemożliwe aż do restartu agenta.
                return 409, dict(self._call_view_locked() or {}, error="busy")
            wall = self._wall()
            last = self.meta.get("call112_wall")
            if isinstance(last, (int, float)) and abs(wall - last) < CALL112_COOLDOWN_S:
                return 429, {"error": "rate_limited",
                             "retry_after": _wait_s(CALL112_COOLDOWN_S - abs(wall - last))}
            self._call_seq += 1
            self.call = {"seq": self._call_seq, "state": "queued", "mode": mine,
                         "number": number, "error": "", "requested_wall": wall,
                         "event_id": eid,
                         "placed_wall": None, "offhook_wall": None, "ended_wall": None,
                         "final": False, "hangup": False, "_prev_wall": last,
                         "_placed": None, "_idle": 0, "_seen_state": False}
            self.meta["call112_wall"] = wall
            try:
                self._save_meta()
            except OSError as e:
                # Połączenie i tak idzie — limit zostaje w pamięci.
                log.error("Cannot save the 112 call time: %s", _clean(e))
            # Znacznik called_112 na zdarzeniu dopiero po udanym ``am start``
            # (:meth:`_place_call`): odmowa ``su`` nie może dopisać do SMS-a
            # „Z auta wybrano 112”.
            view = self._call_view_locked()
        self.call_wake.set()
        log.critical("112 CALL requested by BCM (%s)",
                     "TEST -> " + mask_number(number) if number else "REAL 112, speaker")
        return 200, view

    def call112_view(self) -> tuple[int, dict]:
        """``GET /v1/call112`` — bieżące albo ostatnie połączenie."""
        with self._lock:
            view = self._call_view_locked()
        return 200, {"call": view, "call_state": self._call_state}

    def call112_hangup(self, obj: dict) -> tuple[int, dict]:
        """``POST /v1/call112/hangup`` (treść ``{}``) — „Rozłącz” z ekranu
        auta; wątek połączeń wysyła KEYCODE_ENDCALL."""
        if obj:
            return 400, {"error": "bad_request"}
        with self._lock:
            call = self.call
            # Także połączenie „final” w stanie placed: stanu rozmowy nie da
            # się odczytać, ale KEYCODE_ENDCALL nadal może ją zakończyć.
            if call is None or call["state"] not in CALL_ACTIVE:
                return 409, {"error": "no_call"}
            call["hangup"] = True
            view = self._call_view_locked()
        self.call_wake.set()
        log.warning("112 call: hang-up requested by BCM")
        return 200, view

    def call112_mark(self, obj: dict) -> tuple[int, dict]:
        """``POST /v1/call112/mark {"event_id": "<hex>"}`` — BCM wybrał 112
        przez GŁÓWNY telefon (HFP, ścieżka A) i oFono przyjęło połączenie.
        TO zdarzenie wypadku dostaje znacznik ``called_112`` tak samo jak po
        połączeniu z tego telefonu (:meth:`_flag_called_112`); nieznane —
        nic. BCM wysyła to tylko dla prawdziwego 112 — nigdy w trybie
        testowym."""
        req = obj.get("event_id")
        if set(obj) != {"event_id"} or not isinstance(req, str) \
                or not EVENT_ID_RE.fullmatch(req):
            return 400, {"error": "bad_request", "detail": 'body: {"event_id": "<hex>"}'}
        with self._lock:
            if not self.config["toggles"]["call112"]:
                return 409, {"error": "call112_off"}
            eid = self._flag_called_112(self._wall(), req)
        log.warning("112 called from the main phone (BCM) — event %s", eid or "unknown here")
        return 200, {"ok": True, "event_id": eid}

    def _call_view_locked(self) -> Optional[dict]:
        call = self.call
        if call is None:
            return None

        def ts(key: str) -> Optional[int]:
            v = call.get(key)
            return None if v is None else int(v)

        return {"seq": call["seq"], "state": call["state"], "mode": call["mode"],
                "number": mask_number(call["number"]) if call["number"] else CALL112_NUMBER,
                "error": call["error"], "final": bool(call["final"]),
                "requested_ts": ts("requested_wall"), "placed_ts": ts("placed_wall"),
                "offhook_ts": ts("offhook_wall"), "ended_ts": ts("ended_wall")}

    def _flag_called_112(self, wall: float, event_id: str) -> Optional[str]:
        """(pod blokadą) Zdarzenie ``event_id`` dostaje znacznik
        ``called_112`` — tylko gdy agent je zna, nie jest odwołane i ma
        najwyżej 30 min (nigdy „najnowsze inne”: SMS starego zdarzenia nie
        może stracić budżetu odwołania przez 112 do innego). SMS jeszcze nie
        wyszedł do nikogo → dopisek w jego treści (budżet odwołania zostaje);
        już wyszedł → jeden SMS uzupełniający po zakończeniu wysyłki
        (z budżetu SMS-a odwołującego)."""
        cands = [e for e in self.events
                 if e["id"] == event_id
                 and e["state"] in ("armed", "pending", "sending", "sent", "partial")
                 and 0 <= wall - float(e["created_wall"]) <= RESUME_MAX_LATE_S]
        if not cands:
            return None
        ev = cands[0]
        if ev.get("called_112_wall") is not None:
            return ev["id"]
        ev["called_112_wall"] = wall
        d = ev["crash"]
        untouched = d.get("out_wall") is None and all(
            r["tries"] == 0 and not r.get("handed") and r["st"] in ("queued", "wait")
            for r in d["rcpt"])
        if untouched:
            d["text"] = f"{d['text']} {called_112_suffix(wall, self._localtime)}"
            log.warning("Event %s: the crash SMS will say that 112 was called", ev["id"])
        else:
            ev["c112_pending"] = True
            ev["follow_up_used"] = True
            log.warning("Event %s: the crash SMS already went out — one follow-up SMS about "
                        "the 112 call goes after it", ev["id"])
        self._try_save_events()
        self.wake.set()
        return ev["id"]

    def _start_c112_sms(self, ev: dict, now: float) -> None:
        """(pod blokadą) SMS uzupełniający „Z auta wybrano 112” do tych,
        do których SMS o wypadku wyszedł (albo mógł wyjść)."""
        ev["c112_pending"] = False
        d = ev["crash"]
        went = [r["num"] for r in d["rcpt"]
                if r.get("handed") or r["st"] in ("submitted", "verifying", "sent", "sent_dry")]
        if not went or ev.get("c112") is not None:
            return
        text = call112_text(ev.get("label") or DEFAULT_LABEL, float(ev["called_112_wall"]),
                            int(ev["event_ts"]), self._localtime)
        ev["c112"] = new_delivery("call112", text, went, d["dry"], d["slot"], self._wall(), now)
        log.warning("Event %s: 112 follow-up SMS queued for %d recipient(s)", ev["id"],
                    len(went))

    def run_calls(self, stop: threading.Event) -> None:
        """Wątek połączeń 112 — osobny, żeby rozmowa nigdy nie czekała za
        wysyłką SMS-a (``termux-sms-send`` potrafi trwać minutę)."""
        while not stop.is_set():
            self.call_wake.clear()
            try:
                wait = self.call_step()
            except Exception:
                log.exception("112 call step failed")
                wait = CALL_POLL_S
            if wait > 0:
                self.call_wake.wait(wait)

    def call_step(self) -> float:
        """Jeden krok połączenia (polecenia ``su`` POZA blokadą). Zwraca, za
        ile sekund następny krok."""
        with self._lock:
            call = self.call
            if call is None or call["state"] not in CALL_ACTIVE:
                return 60.0
            state, number, hangup = call["state"], call["number"], call["hangup"]
            if hangup:
                call["hangup"] = False
            if state == "queued" and hangup:
                # „Rozłącz”, zanim ``am start`` w ogóle poszedł: nic nie
                # wybieram, a limit 1 na minutę wraca (nic nie wybrano).
                call.update(state="ended", ended_wall=self._wall(), final=True)
                self.meta["call112_wall"] = call.get("_prev_wall")
                self._persist_quietly()
                log.warning("112 call: hung up before it was placed — nothing dialled")
                return 60.0
            if call["final"] and not hangup:
                return 60.0
        if state == "queued":
            self._place_call(call, number)
            return 0.5
        if hangup:
            rc, _out, err = self.phone.su(HANGUP_COMMAND)
            if rc != 0:
                log.error("112 call: hang-up failed (rc %d: %s)", rc, _clean(err, 80))
            with self._lock:
                if self.call is call and call["final"] and call["state"] in CALL_ACTIVE \
                        and rc == 0:
                    # Stanu rozmowy nie da się odczytać: po wysłanym
                    # KEYCODE_ENDCALL uznaję ją za zakończoną.
                    call.update(state="ended", ended_wall=self._wall())
                    return 60.0
        rc, out, _err = self.phone.su(CALL_STATE_COMMAND)
        cs = parse_call_state(out) if rc == 0 else None
        now, wall = self._clock(), self._wall()
        with self._lock:
            self._call_state = cs
            if self.call is not call or call["state"] not in ("placed", "offhook"):
                return CALL_POLL_S
            placed = call["_placed"] if call["_placed"] is not None else now
            if cs is not None:
                call["_seen_state"] = True
            if cs == 2:
                call["_idle"] = 0
                if call["state"] != "offhook":
                    call["state"] = "offhook"
                    call["offhook_wall"] = wall
                    log.warning("112 call: the phone is in the call (OFFHOOK)")
            elif cs == 0 and call["state"] == "offhook":
                call["_idle"] += 1
                if call["_idle"] >= CALL_IDLE_ENDS:
                    call.update(state="ended", ended_wall=wall, final=True)
                    log.warning("112 call ended")
            elif cs == 0 and call["state"] == "placed" and now - placed >= CALL_IDLE_FAIL_S:
                call.update(state="failed", error="no_call", ended_wall=wall, final=True)
                log.error("112 call: the phone never went into the call after am start")
            elif cs is None and not call["_seen_state"] and now - placed >= CALL_NO_STATE_S:
                # Stanu nie da się odczytać: połączenie wysłane, dalej nie wiem.
                call["final"] = True
                log.warning("112 call: the call state is not readable (dumpsys "
                            "telephony.registry) — no longer followed")
            if call["state"] in CALL_ACTIVE and now - placed >= CALL_FOLLOW_MAX_S:
                call.update(state="ended", ended_wall=wall, final=True)
            return CALL_POLL_S

    def _place_call(self, call: dict, number: Optional[str]) -> None:
        """``am start`` przez ``su`` i głośność rozmowy na maksimum."""
        command = call_command(number)
        rc, out, err = self.phone.su(command)
        text = f"{out}\n{err}"
        low = text.lower()
        now, wall = self._clock(), self._wall()
        if rc == RC_MISSING:
            error = "su_missing"
        elif "denied" in low or "not allowed" in low or rc == RC_TIMEOUT:
            # Odmowa Magiska; przekroczony czas = okno „Zezwolić?” na ekranie
            # telefonu, na które nikt nie odpowie.
            error = "su_denied"
        elif rc != 0 or "Error" in text or "Exception" in text:
            error = "am_failed"
        else:
            error = ""
        with self._lock:
            if error in ("su_missing", "su_denied"):
                self._su_ok = False
                self._su_checked = now
            if self.call is not call:
                return
            if error:
                # Próba, która nie wybrała, nie zużywa limitu 1 na minutę.
                call.update(state="failed", error=error, ended_wall=wall, final=True)
                self.meta["call112_wall"] = call.get("_prev_wall")
                self._persist_quietly()
            else:
                call.update(state="placed", placed_wall=wall, _placed=now)
                if call["mode"] == "real":
                    # Dopiero teraz (``am start`` przeszedł): SMS o wypadku
                    # z okna, z którego dzwoniono, powie „Z auta wybrano 112”.
                    self._flag_called_112(wall, call["event_id"])
        if error:
            log.error("112 call FAILED (%s, rc %d): %s", error, rc, _clean(text, 160))
            return
        log.critical("112 call placed (%s)", "TEST" if number else "REAL 112")
        self._raise_call_volume()

    def _raise_call_volume(self) -> None:
        """Głośność rozmowy na maksimum strumienia (zakres z ``--get``).
        Porażka tylko w logu — rozmowa trwa i bez tego."""
        rc, out, err = self.phone.su(VOLUME_GET_COMMAND)
        top = parse_volume_max(f"{out}\n{err}") if rc == 0 else None
        if top is None:
            log.warning("112 call: cannot read the call volume range (rc %d) — volume "
                        "unchanged", rc)
            return
        rc, _out, err = self.phone.su(volume_set_command(top))
        if rc != 0:
            log.warning("112 call: setting the call volume failed (rc %d: %s)", rc,
                        _clean(err, 80))
        else:
            log.info("112 call: call volume set to %d", top)

    def probe_su(self) -> None:
        """``su -c 'id -u'`` → ``0`` (wątek stanu; tylko z włączonym 112)."""
        rc, out, _err = self.phone.su(SU_PROBE_COMMAND, timeout=SU_TIMEOUT_S)
        ok = rc == 0 and out.strip() == "0"
        with self._lock:
            changed = ok != self._su_ok
            self._su_ok = ok
            self._su_checked = self._clock()
        if changed:
            (log.info if ok else log.warning)(
                "Root (Magisk su) %s — 112 from this phone %s", "works" if ok else
                f"NOT available (rc {rc})", "possible" if ok else "impossible")

    # ── pomocnicze (pod self._lock) ───────────────────────────────────────

    def _find(self, eid: str) -> Optional[dict]:
        return next((e for e in self.events if e["id"] == eid), None)

    def _try_save_events(self) -> bool:
        try:
            self._save_events()
            return True
        except OSError as e:
            log.error("Cannot save events: %s", _clean(e))
            return False

    def _event_view(self, ev: dict) -> dict:
        deadline_in = 0
        if ev["state"] == "armed":
            deadline_in = max(0, int(math.ceil(ev.get("_deadline", 0) - self._clock())))
        cancel = ev.get("cancel")
        c112 = ev.get("c112")
        called = ev.get("called_112_wall")
        return {
            "id": ev["id"], "state": ev["state"], "dry_run": ev["dry"],
            "countdown_s": ev["countdown_s"], "deadline_in_s": deadline_in,
            "armed_ts": int(ev["created_wall"]), "error": ev.get("error", ""),
            "results": delivery_view(ev["crash"]),
            "cancel_sms": None if not isinstance(cancel, dict) else {
                "state": delivery_outcome(cancel) if delivery_done(cancel) else "sending",
                "results": delivery_view(cancel)},
            # „Zadzwoń 112”: kiedy wybrano, SMS uzupełniający i czy zostało
            # coś z budżetu SMS-a odwołującego (BCM chowa wtedy „Jestem OK”).
            "called_112_ts": None if called is None else int(called),
            "c112_sms": None if not isinstance(c112, dict) else {
                "state": delivery_outcome(c112) if delivery_done(c112) else "sending"},
            "follow_up_left": not ev.get("follow_up_used", False),
        }

    def _counted(self, ev: dict) -> bool:
        """Czy zdarzenie liczy się do limitów: odwołane, zanim cokolwiek
        wyszło — nie (fałszywy alarm nie może zablokować prawdziwego)."""
        if ev["state"] == "cancelled":
            return ev["crash"].get("out_wall") is not None
        return True

    def _crash_limit(self, dry: bool) -> Optional[int]:
        """None = wolno uzbroić; inaczej po ilu sekundach spróbować.

        Jedno zdarzenie naraz — testowe czy prawdziwe. Do limitu 10 min /
        3 na dobę PRAWDZIWEGO zdarzenia zdarzenia w trybie testowym się nie
        liczą: nic nie wysłały, więc nikogo nie chronią, a liczone
        blokowałyby prawdziwy alarm zaraz po wyjściu z ``dry_run`` (nawet na
        ~doba). Zdarzenie testowe liczy wszystkie (sprawdzanie limitów na
        stole działa). ``crash.dry`` (nie ``ev.dry``): tryb testowy
        przełączony w trakcie odliczania zmienia tylko flagę wysyłki."""
        wall = self._wall()
        counted = [e for e in self.events if self._counted(e)]
        if any(e["state"] in EVENT_ACTIVE for e in counted):
            return 60
        counted = [e for e in counted if dry or not e["crash"]["dry"]]
        ages = [abs(wall - float(e["created_wall"])) for e in counted]
        recent = [a for a in ages if a < CRASH_COOLDOWN_S]
        if recent:
            return _wait_s(CRASH_COOLDOWN_S - max(recent))
        # Od najmłodszego: limit puści, gdy z okna wypadnie trzecie od końca.
        day = sorted(a for a in ages if a < DAY_S)
        if len(day) >= CRASH_MAX_PER_DAY:
            return _wait_s(DAY_S - day[CRASH_MAX_PER_DAY - 1])
        return None

    def _prune(self) -> None:
        wall = self._wall()
        keep = [e for e in self.events
                if e["state"] in EVENT_ACTIVE
                or abs(wall - float(e["created_wall"])) < KEEP_EVENTS_S
                or e.get("c112_pending")
                or any(isinstance(e.get(k), dict) and not delivery_done(e[k])
                       for k in ("cancel", "c112"))]
        # ">=": zostaw miejsce na nowe zdarzenie (wołane z arm()), inaczej
        # 64 odwołane fałszywe alarmy zablokowałyby prawdziwy.
        while len(keep) >= MAX_EVENTS:
            victim = next((e for e in keep if e["state"] == "cancelled" and not self._counted(e)),
                          None) or next((e for e in keep if e["state"] not in EVENT_ACTIVE), None)
            if victim is None:
                break
            keep.remove(victim)
        self.events = keep

    # ── harmonogram i wysyłka ─────────────────────────────────────────────

    def step(self) -> float:
        """Jeden krok harmonogramu: zdarzenia po terminie, jedna akcja
        wysyłki (``termux-sms-send`` / kontrola wysłanych — POZA blokadą).
        Zwraca, za ile sekund jest następna praca."""
        now = self._clock()
        action = None
        next_due = now + 60.0
        with self._lock:
            changed = False
            for ev in self.events:
                if ev["state"] == "armed":
                    if now >= ev.get("_deadline", now):
                        ev["state"] = "pending"
                        d = ev["crash"]
                        # Tryb testowy jest „lepki”: przełączony w trakcie
                        # odliczania wygrywa, odwrotnie — nie.
                        d["dry"] = bool(d["dry"] or self.config["dry_run"])
                        for r in d["rcpt"]:
                            r["_next"] = min(r.get("_next", now), now)
                        log.warning("Event %s: deadline reached — sending%s", ev["id"],
                                    " (dry run)" if d["dry"] else "")
                        changed = True
                    else:
                        next_due = min(next_due, ev["_deadline"])
                if ev.get("c112_pending") and delivery_done(ev["crash"]):
                    self._start_c112_sms(ev, now)
                    changed = True
            for d, ev in self._deliveries():
                if d.get("no_retry"):
                    # Odwołane: to, co jeszcze nie wyszło, już nie wyjdzie.
                    for r in d["rcpt"]:
                        if r["st"] in ("queued", "wait", "retry"):
                            r["st"] = "skipped"
                            r["err"] = "cancelled"
                            changed = True
                act, due = self._next_action(d, now)
                if act is not None and action is None:
                    action = (d, ev, act)
                if due is not None:
                    next_due = min(next_due, due)
            dry_done = False
            if action is not None:
                d, ev, (idx, kind) = action
                r = d["rcpt"][idx]
                if kind == "send" and d["dry"]:
                    self._dry_send(d, ev, r)
                    changed = dry_done = True
                    action = None
                else:
                    r["_prev_st"] = r["st"]
                    r["st"] = "sending" if kind == "send" else "verifying"
                    if ev is not None and ev["state"] == "pending" and kind == "send":
                        ev["state"] = "sending"
            if changed:
                self._finish_states()
                self._persist_quietly()
        if action is not None:
            d, ev, (idx, kind) = action
            self._run_action(d, ev, idx, kind)
            return 0.0
        if dry_done:
            return 0.0      # następny odbiorca od razu, nie po SCHED_MAX_WAIT_S
        return max(0.0, next_due - self._clock())

    def _deliveries(self):
        """``(dostawa, zdarzenie|None)`` w kolejności pilności: wypadek,
        odwołanie, „wybrano 112”, test."""
        for ev in self.events:
            if ev["state"] in ("pending", "sending") or (
                    ev["state"] == "cancelled" and not delivery_done(ev["crash"])):
                yield ev["crash"], ev
        for ev in self.events:
            c = ev.get("cancel")
            if isinstance(c, dict) and not delivery_done(c):
                yield c, ev
        for ev in self.events:
            c = ev.get("c112")
            if isinstance(c, dict) and not delivery_done(c):
                yield c, ev
        test = self.meta.get("test")
        if isinstance(test, dict) and isinstance(test.get("delivery"), dict) \
                and not delivery_done(test["delivery"]):
            yield test["delivery"], None

    @staticmethod
    def _next_action(d: dict, now: float) -> tuple[Optional[tuple[int, str]], Optional[float]]:
        due: Optional[float] = None
        for i, r in enumerate(d["rcpt"]):
            st = r["st"]
            if st in RCPT_FINAL or st in ("sending", "verifying"):
                continue
            nxt = r.get("_next", 0.0)
            if now < nxt:
                due = nxt if due is None else min(due, nxt)
                continue
            if st in ("queued", "wait", "retry"):
                return (i, "send"), None
            if st == "submitted":
                return (i, "verify"), None
        return None, due

    def _dry_send(self, d: dict, ev: Optional[dict], r: dict) -> None:
        r["st"] = "sent_dry"
        r["tries"] += 1
        if d.get("out_wall") is None:
            d["out_wall"] = self._wall()
        log.warning("DRY RUN %s SMS to %s (%d chars): %s", d["kind"], mask_number(r["num"]),
                    len(d["text"]), d["text"])

    def _stopped(self, d: dict) -> bool:
        """Czy wysyłkę odwołano w międzyczasie (pod blokadą)."""
        with self._lock:
            return bool(d.get("no_retry"))

    def _run_action(self, d: dict, ev: Optional[dict], idx: int, kind: str) -> None:
        """Polecenia w telefonie bez blokady; wynik wpisany pod blokadą.

        Wysyłka: zasięg → skrzynki → ``termux-sms-send``. Sprawdzenie
        zasięgu i skrzynek trwa (każde do :data:`API_TIMEOUT_S`), a
        odwołanie może przyjść w trakcie, więc ``no_retry`` sprawdzam po
        każdym z nich i tuż przed ``termux-sms-send``: zostaje tylko samo
        wywołanie wysyłki, którego nie da się przerwać (takiego odbiorcę
        obejmuje SMS odwołujący, :meth:`_after_out`)."""
        r = d["rcpt"][idx]
        now = self._clock()
        result: dict[str, Any] = {}
        if kind == "send":
            wait_since = r.get("_wait_since")
            if wait_since is None:
                wait_since = now
            service = self.phone.service_ok()
            if self._stopped(d):
                result = {"cancelled": True}
            elif service is False and now - wait_since < SERVICE_WAIT_S:
                result = {"wait": wait_since}
            else:
                counts = self.phone.sms_counts(r["num"], d["text"])
                pre = r.get("pre")
                if self._stopped(d):
                    result = {"cancelled": True}
                elif r.get("handed") and counts is not None and pre is not None \
                        and counts["sent"] > pre:
                    # Wcześniejsza kopia doszła w międzyczasie: ponowienie
                    # byłoby duplikatem alarmu.
                    result = {"landed": True}
                else:
                    ok, err, maybe = self.phone.send_sms(r["num"], d["text"], d["slot"])
                    result = {"ok": ok, "err": err, "maybe": maybe, "counts": counts}
        else:
            result = {"counts": self.phone.sms_counts(r["num"], d["text"])}
        with self._lock:
            now = self._clock()
            prev = r.pop("_prev_st", "queued")
            if kind == "send":
                if "cancelled" in result or ("wait" in result and d.get("no_retry")):
                    # Odwołane w trakcie sprawdzania zasięgu/skrzynek albo
                    # czekania na zasięg: nic już nie wysyłam.
                    r["st"] = "skipped"
                    r["err"] = "cancelled"
                    r["_wait_since"] = None
                elif "wait" in result:
                    r["st"] = "wait" if prev != "retry" else "retry"
                    r["_wait_since"] = result["wait"]
                    r["_next"] = now + SERVICE_POLL_S
                elif "landed" in result:
                    r["st"] = "sent"
                    r["verified"] = True
                    r["err"] = ""
                    r["_wait_since"] = None
                    self._mark_sent(d, r, "an earlier copy reached the sent box — no resend")
                else:
                    if r["tries"] == 0:
                        # Punkt odniesienia kontroli: raz, przed PIERWSZYM
                        # przekazaniem (przy ponowieniu wcześniejsza kopia
                        # mogłaby już siedzieć w skrzynce).
                        counts = result["counts"]
                        r["pre"] = counts["sent"] if counts is not None else None
                        r["pre_failed"] = counts["failed"] if counts is not None else None
                        r["fails"] = 0
                    r["tries"] += 1
                    r["_wait_since"] = None
                    if result["maybe"]:
                        r["handed"] = True
                        r["sub_wall"] = self._wall()
                        if d.get("out_wall") is None:
                            d["out_wall"] = self._wall()
                        self._after_out(d, ev, r)
                    if result["ok"]:
                        r["st"] = "submitted"
                        r["err"] = ""
                        r["_next"] = now + VERIFY_AFTER_S
                        log.info("%s SMS to %s handed to Android (try %d)", d["kind"],
                                 mask_number(r["num"]), r["tries"])
                    else:
                        self._retry_or_fail(d, r, now, result["err"])
            else:
                self._verify(d, r, now, result["counts"])
            self._finish_states()
            self._persist_quietly()

    def _verify(self, d: dict, r: dict, now: float, counts: Optional[dict]) -> None:
        """Kontrola skrzynek po przekazaniu (pod blokadą): „wysłane” wzrosło
        = wysłany; nowy wpis w „nieudanych” = ponowienie; ani to, ani to =
        jeszcze w drodze — kolejna kontrola za :data:`VERIFY_AFTER_S`, a po
        :data:`VERIFY_WINDOW_S` „wysłany, niepotwierdzony” BEZ ponownej
        wysyłki (sam brak w skrzynce nie jest dowodem porażki)."""
        pre, pre_failed = r.get("pre"), r.get("pre_failed")
        if counts is None or pre is None:
            r["st"] = "sent"
            r["verified"] = None
            self._mark_sent(d, r, "unverified (the SMS boxes are not readable)")
            return
        if counts["sent"] > pre:
            r["st"] = "sent"
            r["verified"] = True
            self._mark_sent(d, r, "verified in the sent box")
            return
        new_fails = counts["failed"] - pre_failed if pre_failed is not None else 0
        if new_fails > r.get("fails", 0):
            r["fails"] = new_fails
            self._retry_or_fail(d, r, now, "Android reports the SMS as failed")
            return
        elapsed = self._wall() - float(r.get("sub_wall") or 0)
        if 0 <= elapsed < VERIFY_WINDOW_S:
            r["st"] = "submitted"
            r["_next"] = now + VERIFY_AFTER_S
            return
        r["st"] = "sent"
        r["verified"] = None
        self._mark_sent(d, r, "unverified: in neither the sent nor the failed box after "
                              f"{VERIFY_WINDOW_S / 60:.0f} min")

    def _after_out(self, d: dict, ev: Optional[dict], r: dict) -> None:
        """SMS o wypadku wyszedł (albo mógł wyjść) do odbiorcy już PO
        odwołaniu (był w trakcie ``termux-sms-send``): ten odbiorca też
        dostaje SMS odwołujący."""
        if ev is None or d is not ev.get("crash") or ev["state"] != "cancelled":
            return
        self._follow_up(ev, r["num"])

    def _follow_up(self, ev: dict, num: str) -> None:
        """Dopisz ``num`` do SMS-a odwołującego zdarzenia (pod blokadą albo
        przy starcie): nowy, jeśli go nie ma (reguły jak w
        :meth:`_maybe_cancel_sms`), albo do trwającego — nigdy drugi."""
        c = ev.get("cancel")
        if c is None:
            self._maybe_cancel_sms(ev, [num])
        elif num not in [x["num"] for x in c["rcpt"]] and not delivery_done(c):
            c["rcpt"].append(new_rcpt(num, self._clock()))

    def _mark_sent(self, d: dict, r: dict, how: str) -> None:
        if not d["dry"]:
            self.meta["last_sent_ts"] = int(self._wall())
        log.info("%s SMS to %s sent (%s)", d["kind"], mask_number(r["num"]), how)

    def _retry_or_fail(self, d: dict, r: dict, now: float, err: str) -> None:
        r["err"] = _clean(err)
        retries = r["tries"] - 1
        if not d.get("no_retry") and retries < len(RETRY_DELAYS_S):
            r["st"] = "retry"
            r["_next"] = now + RETRY_DELAYS_S[retries]
            log.warning("%s SMS to %s: %s — retry in %.0f s", d["kind"], mask_number(r["num"]),
                        r["err"], RETRY_DELAYS_S[retries])
        else:
            r["st"] = "failed"
            log.error("%s SMS to %s FAILED after %d tries: %s", d["kind"],
                      mask_number(r["num"]), r["tries"], r["err"])

    def _finish_states(self) -> None:
        """Stan zdarzenia z wyników odbiorców (pod blokadą)."""
        for ev in self.events:
            if ev["state"] in ("pending", "sending") and delivery_done(ev["crash"]):
                ev["state"] = delivery_outcome(ev["crash"])
                log.warning("Event %s: %s", ev["id"], ev["state"])
        test = self.meta.get("test")
        if isinstance(test, dict) and isinstance(test.get("delivery"), dict):
            d = test["delivery"]
            state = delivery_outcome(d) if delivery_done(d) else (
                "sending" if any(r["tries"] for r in d["rcpt"]) else "pending")
            if state != test.get("state"):
                test["state"] = state
                if delivery_done(d):
                    log.info("Test SMS: %s", state)
                    # Only if it reached every CURRENT recipient: a test
                    # queued before the list changed proves nothing new.
                    if test_verified(d) and test_covers(d, self.config):
                        self.meta["last_verified_test_ts"] = int(self._wall())
                    elif test_verified(d):
                        log.warning("Test SMS verified, but the recipients changed since it "
                                    "was queued — it does not count")

    def run_scheduler(self, stop: threading.Event) -> None:
        while not stop.is_set():
            self.wake.clear()
            try:
                wait = self.step()
                # Pusty PAIRING (``touch``) dostaje kod najpóźniej po
                # SCHED_MAX_WAIT_S — ``cat`` go pokaże.
                self.pairing_code()
            except Exception:
                log.exception("Scheduler step failed")
                wait = SCHED_MAX_WAIT_S
            if wait > 0:
                self.wake.wait(min(wait, SCHED_MAX_WAIT_S))

    def refresh_status(self) -> None:
        """Bateria i karta SIM do ``/v1/health`` (wątek w tle); przy
        włączonym 112 także ``su`` (co :data:`SU_PROBE_OK_S`)."""
        with self._lock:
            now = self._clock()
            stale = self._status_ts is None or now - self._status_ts >= STATUS_REFRESH_S
            su_due = self.config["toggles"]["call112"] and self._su_probe_due(now)
        if su_due:
            self.probe_su()
        if not stale and su_due:
            return
        battery = self.phone.battery()
        sim = self.phone.sim_ready()
        with self._lock:
            self._status = {"battery": battery, "sim_ready": sim}
            self._status_ts = self._clock()

    def status_wanted(self) -> bool:
        """Czy ktoś czytał ``/v1/health`` w ostatnich :data:`STATUS_IDLE_S`."""
        with self._lock:
            at = self._health_at
        return at is not None and self._clock() - at < STATUS_IDLE_S

    def run_status(self, stop: threading.Event) -> None:
        """Odświeżanie baterii i SIM co :data:`STATUS_REFRESH_S`, ale tylko
        gdy BCM pyta (auto na postoju: zero wywołań Termux:API). Pierwsze
        pytanie po przerwie budzi wątek (``status_kick``) i dostaje jeszcze
        starą pamięć podręczną — health nigdy nie czeka."""
        while not stop.is_set():
            self.status_kick.clear()
            if self.status_wanted():
                try:
                    self.refresh_status()
                except Exception:
                    log.exception("Status refresh failed")
            self.status_kick.wait(STATUS_REFRESH_S)


# ── walidacja danych od BCM ───────────────────────────────────────────────

def default_config() -> dict:
    """Konfiguracja przed pierwszym ``PUT /v1/config``: bez odbiorców, tryb
    testowy, wszystkie przełączniki wyłączone."""
    return {"recipients": [], "sim_slot": 0, "vehicle_label": DEFAULT_LABEL,
            "toggles": {k: False for k in TOGGLES}, "dry_run": True, "follow_up_cancel": True,
            # Bez konfiguracji z BCM: 112 w trybie TESTOWYM bez numeru = nic
            # nie da się wybrać (i tak przełącznik call112 jest wyłączony).
            "call112_test_mode": True, "call112_test_number": ""}


def normalize_config(obj: Any, strict: bool = False) -> tuple[Optional[dict], str]:
    """``{recipients ≤ 3 × E.164, sim_slot 0|1, vehicle_label, toggles,
    dry_run, follow_up_cancel, call112_test_mode, call112_test_number}`` →
    postać kanoniczna (ta sama co w BCM, bo skrót musi się zgadzać).
    Nieznane klucze są pomijane. ``strict`` = brakujące pola to błąd
    (``PUT``); bez niego — wartości domyślne (wczytanie zapisanego pliku).
    Pola 112 są opcjonalne także w ``PUT`` (domyślnie tryb TESTOWY bez
    numeru — nic nie da się wybrać), a numer testowy to "" albo E.164."""
    if not isinstance(obj, dict):
        return None, "expected an object"
    base = default_config()
    out: dict[str, Any] = {}
    for key in ("recipients", "sim_slot", "vehicle_label", "toggles", "dry_run"):
        if key not in obj and strict:
            return None, f"missing {key}"
    rec = obj.get("recipients", base["recipients"])
    if not isinstance(rec, list) or len(rec) > MAX_RECIPIENTS:
        return None, f"recipients must be a list of at most {MAX_RECIPIENTS} numbers"
    nums: list[str] = []
    for n in rec:
        if not isinstance(n, str) or not E164_RE.fullmatch(n):
            return None, "every recipient must match ^\\+[1-9][0-9]{7,14}$"
        if n not in nums:
            nums.append(n)
    out["recipients"] = nums
    slot = obj.get("sim_slot", base["sim_slot"])
    if isinstance(slot, bool) or slot not in (0, 1):
        return None, "sim_slot must be 0 or 1"
    out["sim_slot"] = int(slot)
    label = obj.get("vehicle_label", base["vehicle_label"])
    if not isinstance(label, str) or not LABEL_RE.fullmatch(label) or label != label.strip():
        return None, "vehicle_label: 1-20 characters A-Z a-z 0-9 space . -"
    out["vehicle_label"] = label
    toggles = obj.get("toggles", base["toggles"])
    if not isinstance(toggles, dict):
        return None, "toggles must be an object"
    out["toggles"] = {}
    for k in TOGGLES:
        v = toggles.get(k, False)
        if not isinstance(v, bool):
            return None, f"toggles.{k} must be a boolean"
        out["toggles"][k] = v
    for key in ("dry_run", "follow_up_cancel", "call112_test_mode"):
        v = obj.get(key, base[key])
        if not isinstance(v, bool):
            return None, f"{key} must be a boolean"
        out[key] = v
    num = obj.get("call112_test_number", base["call112_test_number"])
    if not isinstance(num, str) or (num and not E164_RE.fullmatch(num)):
        return None, "call112_test_number must be '' or match ^\\+[1-9][0-9]{7,14}$"
    out["call112_test_number"] = num
    return out, ""


def validate_crash(obj: dict) -> tuple[Optional[dict], str]:
    """Pola ``POST /v1/crash``. Do treści SMS-a trafiają WYŁĄCZNIE liczby
    stąd (i stała etykieta z konfiguracji)."""
    eid = obj.get("event_id")
    if not isinstance(eid, str) or not EVENT_ID_RE.fullmatch(eid):
        return None, "event_id: 1-32 lowercase hex characters"
    countdown = _number(obj.get("countdown_s"), COUNTDOWN_MIN_S, COUNTDOWN_MAX_S, integer=True)
    if countdown is None:
        return None, f"countdown_s: integer {COUNTDOWN_MIN_S}..{COUNTDOWN_MAX_S}"
    lat_raw, lon_raw = obj.get("lat"), obj.get("lon")
    if lat_raw is None and lon_raw is None:
        lat = lon = None
    else:
        lat = _number(lat_raw, -90, 90)
        lon = _number(lon_raw, -180, 180)
        if lat is None or lon is None:
            return None, "lat/lon: both numbers in range, or both null"
    out: dict[str, Any] = {"event_id": eid, "countdown_s": int(countdown),
                           "lat": None if lat is None else float(lat),
                           "lon": None if lon is None else float(lon)}
    age = obj.get("fix_age_s")
    if age is not None:
        age = _number(age, 0, MAX_FIX_AGE_S, integer=True)
        if age is None:
            return None, f"fix_age_s: integer 0..{MAX_FIX_AGE_S} or null"
    out["fix_age_s"] = age
    for key in ("speed_kmh", "dv_kmh"):
        v = obj.get(key)
        if v is not None:
            v = _number(v, 0, MAX_SPEED_KMH)
            if v is None:
                return None, f"{key}: number 0..{MAX_SPEED_KMH} or null"
        out[key] = v
    ts = _number(obj.get("event_ts"), EVENT_TS_MIN, EVENT_TS_MAX, integer=True)
    if ts is None:
        return None, "event_ts: integer epoch seconds"
    out["event_ts"] = int(ts)
    dry = obj.get("dry_run", False)
    if not isinstance(dry, bool):
        return None, "dry_run must be a boolean"
    out["dry_run"] = dry
    return out, ""


# ── serwer HTTP ───────────────────────────────────────────────────────────

class AgentHandler(BaseHTTPRequestHandler):
    """Cienka warstwa HTTP nad :meth:`Agent.handle`. HTTP/1.0: jedno żądanie
    na połączenie (żaden klient nie trzyma wątku w keep-alive)."""

    protocol_version = "HTTP/1.0"
    server_version = "bcm-agent"
    sys_version = ""
    timeout = SOCKET_TIMEOUT_S

    def do_GET(self) -> None:
        self._serve("GET")

    def do_POST(self) -> None:
        self._serve("POST")

    def do_PUT(self) -> None:
        self._serve("PUT")

    def _send(self, status: int, data: bytes, headers: Mapping[str, str]) -> None:
        try:
            self.send_response(status)
            for k, v in headers.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
        except OSError:
            pass

    def _serve(self, method: str) -> None:
        agent: Agent = self.server.agent          # type: ignore[attr-defined]
        if self.headers.get("Transfer-Encoding"):
            self._send(411, b'{"error":"length_required"}', {"Content-Type": "application/json"})
            return
        raw_len = (self.headers.get("Content-Length") or "0").strip()
        if not re.fullmatch(r"[0-9]{1,7}", raw_len):
            self._send(400, b'{"error":"bad_length"}', {"Content-Type": "application/json"})
            return
        length = int(raw_len)
        if length > MAX_BODY:
            # Treści NIE czytam — połączenie i tak się zamyka (HTTP/1.0).
            self._send(413, b'{"error":"too_large"}', {"Content-Type": "application/json"})
            return
        try:
            body = self.rfile.read(length) if length else b""
        except OSError:
            return
        if len(body) != length:
            return
        headers = {k: self.headers.get(k, "") for k in ("X-BCM-Ts", "X-BCM-Nonce", "X-BCM-Sig")}
        status, data, hdrs = agent.handle(method, self.path, headers, body)
        self._send(status, data, hdrs)

    def log_message(self, fmt: str, *args: Any) -> None:
        # Nigdy nagłówki ani treść (sekret przy parowaniu) — tylko linia żądania.
        log.debug("%s %s", self.address_string(), _clean(fmt % args, 200))


class AgentServer(ThreadingHTTPServer):
    """Wątek na połączenie, ale najwyżej :data:`MAX_CONNECTIONS` naraz."""

    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = MAX_CONNECTIONS

    def __init__(self, addr: tuple, agent: Agent, max_conn: int = MAX_CONNECTIONS) -> None:
        self.agent = agent
        self._slots = threading.BoundedSemaphore(max_conn)
        super().__init__(addr, AgentHandler)

    def verify_request(self, request: Any, client_address: Any) -> bool:
        return isinstance(client_address, tuple) and client_address[0] == BIND_HOST

    def process_request(self, request: Any, client_address: Any) -> None:
        if not self._slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self._slots.release()
            raise

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


def make_server(agent: Agent, port: int = DEFAULT_PORT) -> AgentServer:
    """Serwer na 127.0.0.1:``port`` (0 = wolny port, testy). Innego adresu
    nie da się podać."""
    if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65535:
        raise ValueError("port must be 0..65535")
    return AgentServer((BIND_HOST, port), agent)


# ── uruchomienie ──────────────────────────────────────────────────────────

def setup_logging(state_dir: str, verbose: bool = False) -> None:
    handler = logging.handlers.RotatingFileHandler(
        os.path.join(state_dir, LOG_FILE), maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUPS,
        encoding="utf-8")
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    handler.setFormatter(fmt)
    log.addHandler(handler)
    if verbose:
        err = logging.StreamHandler(sys.stderr)
        err.setFormatter(fmt)
        log.addHandler(err)
    log.setLevel(logging.DEBUG if verbose else logging.INFO)
    try:
        os.chmod(os.path.join(state_dir, LOG_FILE), 0o600)
    except OSError:
        pass


def write_pairing_code(state_dir: str, out: Any = None) -> int:
    """``--pair``: nowy jednorazowy kod w ``PAIRING`` (0600, nadpisuje
    stary — działający agent bierze go przy następnej próbie) i na ekran.
    Serwera nie uruchamia; agent może w tym czasie działać."""
    out = out if out is not None else sys.stdout
    try:
        os.chmod(state_dir, 0o700)
    except OSError:
        pass
    code = new_pairing_code()
    path = os.path.join(state_dir, "PAIRING")
    try:
        atomic_write(path, (code + "\n").encode("ascii"))
    except OSError as e:
        print(f"Nie mogę zapisać {path}: {_clean(e)}", file=sys.stderr)
        return 1
    print(f"Kod parowania: {code}", file=out)
    print("Wpisz go w BCM: Ustawienia -> Agent w telefonie -> Sparuj. Kod jest "
          f"jednorazowy; po {PAIR_MAX_FAILS} zlych probach trzeba wygenerowac nowy.", file=out)
    return 0


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="BCM agent for the car phone (Termux)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help="port on 127.0.0.1 (default 8765)")
    parser.add_argument("--state-dir", default=DEFAULT_STATE_DIR)
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--pair", action="store_true",
                        help="write a fresh one-time pairing code into PAIRING, print it, exit")
    args = parser.parse_args(argv)
    os.makedirs(args.state_dir, mode=0o700, exist_ok=True)
    if args.pair:
        return write_pairing_code(args.state_dir)
    setup_logging(args.state_dir, args.verbose)
    agent = Agent(args.state_dir)
    server = make_server(agent, args.port)
    stop = threading.Event()
    threads = [threading.Thread(target=agent.run_scheduler, args=(stop,), daemon=True,
                                name="scheduler"),
               threading.Thread(target=agent.run_status, args=(stop,), daemon=True,
                                name="status"),
               threading.Thread(target=agent.run_calls, args=(stop,), daemon=True,
                                name="call112")]
    for t in threads:
        t.start()

    def _stop(signum: int, frame: Any) -> None:
        stop.set()
        agent.wake.set()
        agent.status_kick.set()
        agent.call_wake.set()
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    log.info("BCM agent %s listening on %s:%d (paired: %s, pairing file: %s)", VERSION,
             BIND_HOST, server.server_address[1], agent.paired, agent.pairing_open)
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        stop.set()
        server.server_close()
    log.info("BCM agent stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
