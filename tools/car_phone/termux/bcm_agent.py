#!/data/data/com.termux/files/usr/bin/env python3
"""Agent BCM w telefonie w aucie (Termux) — SMS po stłuczce, alarm na postoju
(D4), „Zadzwoń 112” (H), czuwanie kabiny przednią kamerą (I), budzenie
komputera w aucie podczerwienią (E, wersja z buforem) i wspólny kanał dla
kolejnych funkcji.

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
Opcjonalnie Pillow (``pkg install python-pillow`` — pakiet Termuxa, nie
pip): tylko czuwanie kabiny używa go do analizy zdjęć i do ich przekodowania
bez EXIF; bez niego agent działa tak samo, a analiza zdjęć jest pomijana.

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
wersji ≥ 1.1.0 (starszą BCM pokazuje jako „zaktualizuj bcm_agent.py”),
alarm na postoju ≥ 1.2.0, czuwanie kabiny ≥ 1.3.0, budzenie IR ≥ 1.4.0.

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
``POST /v1/call112/mark``, ``GET /v1/park``, ``POST /v1/park/arm``,
``POST /v1/park/disarm``, ``POST /v1/park/event``, ``GET /v1/cabin`` —
opis przy metodach :class:`Agent`, :class:`ParkGuard` i :class:`CabinWatch`.
Bateria i SIM w ``/v1/health`` są odświeżane w tle
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

Alarm na postoju (plan D4, przełącznik ``toggles.parking_guard``)
-----------------------------------------------------------------
BCM na postoju nie działa (wersja testowa: każde zgaszenie silnika odcina
prąd komputerowi i USB telefonu), więc wszystko dzieje się TU, w telefonie.

* **Uzbrajanie samo:** brak zasilania USB (``termux-battery-status``:
  ``plugged`` = ``UNPLUGGED``) ORAZ żadnego podpisanego żądania BCM przez
  ``park_arm_after_min`` (3) min → ``arming``, a po kolejnych
  ``park_arm_delay_min`` (2) min (okno wyjścia: wysiadanie nie alarmuje)
  → ``armed``; razem ok. 5 min po zgaszeniu. Prąd, który wróci w oknie
  wyjścia, przerywa uzbrajanie. Albo podpisane ``POST /v1/park/arm
  {"delay_min": n}`` od BCM (wersja z buforem: BCM wie o zgaszeniu), albo
  SMS ``PARK ON <kod>``. Opcjonalna strefa „dom” (``park_home``: lat, lon,
  ``radius_m`` ≥ 50): samo uzbrajanie i to od BCM sprawdzają pozycję
  i w domu nie uzbrajają (pozycja nieznana albo niedokładna > 500 m →
  uzbrajam). Po rozbrojeniu bez prądu (np. ``PARK OFF`` z daleka) samo
  uzbrojenie czeka na następne odcięcie zasilania.
* **Rozbrajanie TYLKO dowodem właściciela** — nigdy samym prądem ani
  zapłonem: podpisane ``POST /v1/park/disarm {}`` od BCM (BCM wysyła je
  wyłącznie, gdy połączy się telefon właściciela przez Bluetooth/HFP/AA);
  ``POST /v1/park/disarm {"code": "<6 cyfr>"}`` (kod TOTP wpisany na
  ekranie auta, sprawdzany tutaj); SMS ``PARK OFF <kod>`` z numeru z białej
  listy. Prąd, który wraca przy uzbrojonym, daje ``park_grace_min`` (3) min
  na dowód; potem alarm „zasilanie wrocilo bez telefonu wlasciciela”.
  Wyłączenie ``modules.parking_guard`` / ``modules.cabin_watch`` w BCM
  (Ustawienia → Moduły — ma je każdy przy ekranie auta) NIE jest dowodem:
  przy uzbrojonym albo w alarmie alarm i czuwanie pilnują dalej (stare
  ustawienia ``park_*`` / ``cabin_*`` zostają, ``off_pending`` w widoku),
  a wyłączenie działa dopiero po rozbrojeniu dowodem właściciela, niską
  baterią albo strefą „dom”.
* **Po wypadku i 112** (:data:`PARK_CRASH_HOLDOFF_S`, 6 h): wariant testowy
  nie ma bufora, więc odcięcie prądu po wypadku wygląda jak zwykły postój,
  a ratownicy, policja i laweta otwierają drzwi i podnoszą auto. Przez 6 h
  po wypadku od BCM (``POST /v1/crash``, nieodwołany, nie na próbę) albo po
  prawdziwym 112 z tego telefonu oraz w czasie każdej rozmowy 112 alarm NIE
  uzbraja się sam (zasilanie, BCM — ``SMS PARK ON <kod>`` działa); alarm,
  który się uzbraja albo jest uzbrojony, gdy przychodzi wypadek / 112,
  zostaje rozbrojony bez alarmu (czekający alarm okna wejścia i czekające
  zdarzenie kabiny odwołane, ich zdjęcia usunięte; alarmy rozstrzygnięte
  wcześniej zostają). W czasie rozmowy 112 czuwanie kabiny nie robi zdjęć
  i nie przełącza ekranu. Działa TYLKO, gdy BCM doręczył wypadek
  telefonowi (``modules.crash_sms`` i sparowany agent) albo 112 poszło
  z tego telefonu.
* **Okno wejścia** (``park_entry_s``, 90 s; 0 = alarm od razu): przechył
  albo wstrząs przy uzbrojonym nie alarmuje od razu — właściciel, który
  otwiera drzwi i siada, wygląda dla czujnika tak samo jak złodziej, a jego
  dowód (telefon połączony z BCM) przychodzi dopiero po zapłonie, starcie
  komputera i połączeniu Bluetooth. Alarm czeka ``park_entry_s`` (kolejne
  wstrząsy nie przesuwają terminu); prąd, który w tym czasie wróci
  (zapłon), przesuwa termin do końca ``park_grace_min``; dowód właściciela
  kasuje alarm i SMS-y alarmowe, które jeszcze nie wyszły. Podnośnik
  i holowanie prądu nie przywracają — alarm po ``park_entry_s``. W oknie
  bateria co 15 s, a tuż przed terminem świeży odczyt.
* **Kod TOTP** (RFC 6238: SHA1, 6 cyfr, 30 s, ±1 krok): sekret tworzy
  ``python ~/bcm_agent/bcm_agent.py --park-setup`` (plik ``park_totp``,
  0600; wypisuje adres ``otpauth://`` dla aplikacji „authenticator”, np.
  Aegis z F-Droid; nigdy do logu; ``--new`` = nowy sekret). Użyty kod nie
  przechodzi drugi raz (zapisany krok, także po restarcie); 5 złych kodów
  w godzinie z jednego numeru = ten numer ignorowany do końca godziny.
* **Czujniki (oszczędnie):** tylko przy uzbrojonym jeden długo żyjący
  ``termux-sensor -s <akcelerometr> -d 100`` (nazwa raz z ``termux-sensor
  -l``; strumień JSON czytany ostrożnie, restart z backoffem 5 s → 5 min).
  Każde zatrzymanie (rozbrojenie, restart, przejście na wersję lekką):
  SIGTERM do całej grupy procesów (skrypt i pomocnik ``termux-api``), po
  3 s SIGKILL, potem ``termux-sensor -c`` — bez tego Termux:API próbkuje
  dalej, a następny strumień i paczki ``-n`` nie dostają nic. Polecenia
  Termux:API po przekroczeniu czasu też kończą się z całą grupą. Bateria
  co 3 min. Tuż przed SAMYM uzbrojeniem i tym od BCM jedna paczka próbek:
  ruch jak w jeździe (rozrzut > 0,25 m/s²) przesuwa uzbrojenie o minutę,
  najwyżej 30 razy — kabel USB, który odpadnie w czasie jazdy, nie uzbraja
  telefonu w ruchu. Wyzwalacze:
  przechył ≥ ``park_tilt_deg`` (0,5°) przez ≥ 3 s względem wolnego
  odniesienia (podnośnik, holowanie), kołysanie powyżej ``park_shake_k``
  (6) × szum przez ≥ 0,5 s, zasilanie bez właściciela. GPS tylko na
  żądanie albo przy alarmie (``termux-location -p gps -r once`` do 60 s,
  potem sieć, potem ostatnia znana); po nieudanym GPS polecenia i strefa
  „dom” przez 10 min od razu pytają sieć (garaż), alarm — zawsze GPS.
* **Pierwszy tydzień ``park_log_only: true``** (domyślnie): wyzwalacze
  tylko w logu (``PARK (log only, no SMS)``) do strojenia progów — żaden
  automatyczny SMS (alarm, bateria). Odpowiedzi na polecenia SMS idą zawsze
  (o nie prosił właściciel).
* **Polecenia SMS** z numerów z listy (``park_numbers`` z BCM, ≤ 3 E.164;
  gdy BCM nie wysyła żadnych — ``--park-numbers`` w telefonie):
  ``POZYCJA <kod>`` / ``GDZIE <kod>`` → ``ALFA 156: POZYCJA
  https://maps.google.com/?q=lat,lon (GPS sprzed N s, dokladnosc M m)``;
  ``PARK ON|OFF|STATUS <kod>``. Wielkość liter i spacje bez znaczenia.
  Kod liczy się względem czasu ODEBRANIA SMS-a przez telefon (nie chwili
  przeczytania skrzynki), więc odczyt co 30 s go nie unieważnia.
  Skrzynka odbiorcza co 30 s (``termux-sms-list -t inbox -l 10``, tylko
  z przełącznikiem, numerami i sekretem TOTP); powtórki, wiadomości
  sprzed startu agenta i starsze niż 10 min są pomijane, obcy nadawca —
  po cichu. Odpowiedź do numeru z LISTY (nigdy do tekstu z SMS-a), 1 na
  numer na 2 min, 10 na dobę.
* **SMS alarmowy** ``ALFA 156: ALARM <powód> <dd.mm hh:mm>. Pozycja:
  <link>`` (GSM-7) do numerów z listy: najwyżej 1 na 10 min i 6 na dobę,
  budżet osobny od SMS-a o wypadku (wspólny z czuwaniem kabiny — jeden
  alarm auta); kolejka wysyłki zawsze najpierw obsługuje wypadek.
* **Bateria:** po dobie uzbrojenia albo poniżej 30% wersja „lekka” (co
  20 s paczka 10 próbek ``termux-sensor -n 10`` zamiast strumienia);
  poniżej 15% rozbrojenie z jednym SMS-em (poza ``log_only``). Szacunkowe
  zużycie: blokada uśpienia Termuxa 30–80 mA, strumień akcelerometru kilka
  mA, skrzynka co 30 s i bateria co 3 min po ułamku sekundy — razem ok.
  1–2% baterii na godzinę (niesprawdzone na tym telefonie; ``PARK STATUS``
  pokazuje procent).
* Stan (``park.json``) zapisywany atomowo przy każdej zmianie — restart
  agenta albo telefonu go nie gubi. ``GET /v1/park``: ``{state (off |
  disarmed | arming | armed | alarm | log_only), since, by, arm_at,
  last_event, battery {pct, power}, log_only, light, sensor, totp_ready,
  numbers_n, home_set, alarms_today, entry_until, off_pending}``
  (``entry_until`` = termin czekającego alarmu okna wejścia albo null;
  ``off_pending`` = wyłączony w BCM, pilnuje do dowodu właściciela).

Uprawnienia Termux:API dla alarmu na postoju: **SMS** (odczyt skrzynki
odbiorczej i wysyłka), **Lokalizacja: zawsze** (Android 13: „Zezwalaj cały
czas”, inaczej ``termux-location`` w tle nic nie zwraca) — NIESPRAWDZONE na
crDroid 13, tak jak to, że ``termux-sensor`` działa przy wygaszonym
ekranie, a ``-n`` po paczce zwalnia czujnik.

Czuwanie kabiny (plan I, przełącznik ``toggles.cabin_watch``)
--------------------------------------------------------------
Warstwa NAD alarmem na postoju (działa tylko z ``toggles.parking_guard``
i tylko przy uzbrojonym — kamera NIGDY poza uzbrojeniem, NIGDY dźwięk).
Klasa :class:`CabinWatch`; zdjęcia robi osobny wątek (``cabin``), żeby
wątek postoju (skrzynka SMS, bateria, terminy) nie czekał na aparat.

* **T0, sygnały** — ten sam strumień ``termux-sensor`` co alarm na postoju,
  z dopisanym czujnikiem światła: ``termux-sensor -s <akcelerometr>,<światło>
  -d 100`` (obie nazwy raz z ``termux-sensor -l``; czujnik światła jest po
  stronie ekranu, a telefon wisi ekranem w dół — patrzy w kabinę). Sygnały:
  **skok światła** ×5 i +5 lux w ciągu 2 s (lampka sufitowa; powolna
  zmiana — chmura, zmierzch — się nie liczy), **ruch** i **przechył**
  z detektora alarmu na postoju, **drzwi** (podpisane ``POST /v1/park/event
  {"kind": "door"}`` od BCM — wersja docelowa z wybudzaniem E; sam sygnał
  drzwi NIGDY nie rozbraja). Ruch dla kabiny ma własny rytm: najwyżej raz na
  10 s (alarm na postoju — raz na 30 s, bez zmian). Zdarzenie kabiny:
  (światło I ruch w ciągu 10 s) ALBO przechył ALBO drzwi ALBO 3 słabe
  sygnały w 60 s, w tym co najmniej dwa ruchy (wszystkie skoki światła
  z okna liczą się jak jeden — powtarzające się błyski: awaryjne auta obok,
  koguty, burza, kolejne auta; ok. 20 s ciągłego kołysania wystarczy też
  w jasnej kabinie, gdzie lampka nie daje skoku ×5). Progi światła:
  ``cabin_light_ratio`` / ``cabin_light_lux`` z BCM (kalibracja w tygodniu
  ``park_log_only``; nowe działają od razu). Na czas zdjęć
  (ekran się włącza — czujnik światła widzi własny ekran) i 5 s po nich
  skoki światła się nie liczą. W wersji „lekkiej” alarmu na postoju
  (paczki próbek, bez czujnika światła i aparatu) przechył i ruch obsługuje
  sam alarm na postoju, do kabiny trafia tylko sygnał drzwi.
* **T1, zdjęcia — od razu:** przez Magisk ``su`` stałe ciągi ``input
  keyevent KEYCODE_WAKEUP`` i ``am start -W -a android.intent.action.MAIN -c
  android.intent.category.LAUNCHER com.termux`` (Termux na pierwszym planie
  — Android 11+ daje aparat tylko aplikacji „w użyciu”, a Termux:API ma ten
  sam UID co Termux; ``-W`` czeka, aż aktywność się wyświetli; blokada
  ekranu musi być „Brak”), potem 3 ×
  ``termux-camera-photo -c <id> <ścieżka>`` w 0/3/6 s i ``input keyevent
  KEYCODE_SLEEP``. ``<id>`` przedniej kamery raz z ``termux-camera-info``
  (liczba 0–99, w pamięci), ścieżka tylko z naszego katalogu i
  zwalidowanych znaków. Kamera wyłączona: bateria telefonu < 0 °C albo
  > 45 °C, ładowanie przy ≥ 40 °C, bateria < 30%, wersja „lekka” alarmu
  na postoju, brak odczytu temperatury, < 100 MB wolnego miejsca.
* **T2, analiza w telefonie** (tylko z Pillow; SMS NIGDY na nią nie
  czeka): 320×240 w odcieniach szarości, rozmycie, wyrównanie jasności,
  różnica względem zdjęcia odniesienia z tej samej klasy światła (ciemno
  < 10 lux, półmrok < 200, jasno; odniesienie: jedno zdjęcie 30 s po
  uzbrojeniu, w pliku tylko przetworzone 320×240) — bez odniesienia:
  względem pierwszego zdjęcia z serii; ≥ ``cabin_diff_pct`` (3%) zmienionych
  pikseli poza maską okien (``cabin_mask``, prostokąty w % kadru) =
  „zmiana”. Ciemne klatki (noc bez lampki) = „ciemno”. Bez Pillow:
  „pominięta”, alarm i tak idzie z czujników.
* **T3, alarm — najpierw SMS** (GSM-7) do numerów alarmu na postoju, po
  oknie wejścia ``cabin_entry_s`` (45–60 s; zapłon w tym czasie przesuwa
  termin do końca ``park_grace_min`` jak w alarmie na postoju):
  ``ALFA 156: RUCH W KABINIE 19.11 03:12 (swiatlo+ruch). Zdjecia: 3.
  Pozycja: <link>``; zdarzenie bez światła i drzwi (sam przechył albo ruch)
  ma treść alarmu na postoju, np. ``ALFA 156: ALARM przechyl (podnosnik
  albo holowanie) 19.11 03:12. Zdjecia: 3. Pozycja: <link>``. Krótsze
  ``park_entry_s`` czekającego alarmu postoju skraca okno kabiny do jego
  terminu (jeden SMS). Budżet SMS-ów WSPÓLNY z alarmem na postoju (jeden
  alarm auta na 10 min, 6 na dobę — jedno wejście do auta = jeden SMS:
  czekający alarm postoju i powrót prądu są objęte tym SMS-em), osobny od
  SMS-ów o wypadku (te i tak idą pierwsze). Zdarzeń kabiny (serii zdjęć)
  najwyżej 1 na 10 min i 6 na dobę, 3 zdjęcia na zdarzenie. ``park_log_only``
  obowiązuje także tu: zdarzenie i zdjęcia tak, SMS nie. Wysyłka zdjęć
  (ntfy, szyfrowanie ``age``) — NIE w tej wersji: zdjęcia zostają
  w telefonie.
* **Dowód właściciela w oknie wejścia** (telefon właściciela połączony z BCM,
  ``PARK OFF <kod>``, kod TOTP z ekranu auta) odwołuje alarm kabiny
  i USUWA zdjęcia tego zdarzenia (to był właściciel). Zdjęcia zdarzeń,
  po których poszedł alarm, zostają.
* **Zdjęcia:** ``~/.config/bcm_agent/cabin`` (0700, pliki 0600), bez EXIF
  (z Pillow — przekodowane do ≤ 1280 px; bez Pillow — usunięte segmenty
  APP1–APP15 i COM pliku JPEG), retencja 72 h i 200 MB (najstarsze
  pierwsze). Przez API NIGDY: ``GET /v1/cabin`` daje stan, zdarzenia
  i liczbę zdjęć — ``{state (off | idle | watching | pending), camera,
  light_sensor, lux, pillow, log_only, entry_until, photos_n, photos_mb,
  events_today, last_event, events}``.

Uprawnienia: Termux:API **Aparat** (Camera), Magisk ``su`` dla Termuxa
(jak przy 112), blokada ekranu **Brak**, wygaszanie ekranu po 15 s.
W crDroid WYŁĄCZ każde inne budzenie ekranu (wyświetlacz otoczenia /
Ambient display, budzenie ekranu przy powiadomieniach, podnieś, aby
wybudzić, dwukrotne dotknięcie, budzenie po podłączeniu ładowarki):
czujnik światła jest po stronie ekranu, więc każde takie zapalenie ekranu
to „skok światła” — na postoju ekran ma zapalać wyłącznie agent.
NIESPRAWDZONE na crDroid 13: zdjęcie przy wygaszonym ekranie po
``KEYCODE_WAKEUP`` i ``am start`` (Termux na pierwszym planie), czy
``termux-camera-photo`` kończy się po zapisaniu pliku, raportowanie
czujnika światła przy wygaszonym ekranie, prąd w mA na warstwę.

Budzenie komputera w aucie (plan E, przełącznik ``toggles.remote_session``)
--------------------------------------------------------------------------
Tylko WERSJA Z BUFOREM: komputer śpi w S3 (albo jest wyłączony), a budzi go
wyłącznie Nano #2 przyciskiem zasilania (arduino/sensor_hub,
``FEATURE_WAKE_IR``). Ten telefon jest „pilotem”: nadaje przez swoją diodę
IR ramkę NEC z prywatnym kodem do odbiornika TSOP przy Nano. Nano sam
pilnuje reguł (zapłon zgaszony, komputer śpi, 3 na godzinę / 6 na dobę,
bank > 12,2 V) — telefon może tylko poprosić. W aucie testowym bez bufora
nie ma czego budzić: przełącznik zostaje wyłączony.

* **Wyzwalacze:** SMS ``WAKE <kod>`` z numeru z białej listy alarmu na
  postoju (ten sam sekret TOTP co ``PARK OFF`` — tworzy go ``--park-setup``,
  ta sama ochrona przed powtórką i blokada po 5 złych kodach) — skrzynka
  jest czytana także wtedy, gdy sam alarm na postoju jest wyłączony, ale
  wtedy przyjmowane jest tylko ``WAKE``. Biała lista: ``park_numbers`` z BCM
  przychodzi TYLKO przy włączonym ``modules.parking_guard``; bez alarmu
  trzeba ją ustawić w telefonie (``--park-numbers``), inaczej agent raz
  ostrzega w logu („no numbers for SMS commands”) i skrzynki nie czyta.
  Albo lokalnie
  ``python ~/bcm_agent/bcm_agent.py --wake`` — skrót Termux:Widget
  ``wake.sh`` (tools/car_phone/termux), bez sieci i bez kodu (kto ma
  w ręku ten telefon, i tak siedzi w aucie).
* **Nadawanie:** ``termux-infrared-transmit -f 38000 <wzorzec>`` — stała
  lista argumentów, wzorzec (czasy w µs) zbudowany WYŁĄCZNIE z dwóch liczb
  z konfiguracji: ``wake_ir_address`` (0..65535) i ``wake_ir_command``
  (0..255), przysłanych przez BCM (``power.remote_session.ir_address`` /
  ``ir_command``, tylko przy włączonym przełączniku; muszą być takie same
  jak ``WAKE_IR_ADDRESS`` / ``WAKE_IR_COMMAND`` w firmware). Jedno
  wywołanie = 3 ramki co 108 ms (Nano przyjmuje 2 identyczne w ciągu 1 s).
  Wywołanie bez błędu = wyjście puste; tekst na wyjściu (np. brak nadajnika
  IR) = porażka.
* **Limit w telefonie** (niezależnie od Nano, zapisany w ``wake.json`` pod
  blokadą pliku ``wake.lock`` — agent i ``--wake`` to dwa procesy):
  najwyżej 1 próba na :data:`WAKE_COOLDOWN_S` s, 3 udane na godzinę i 6 na
  dobę.
* **Odpowiedź SMS** (tylko na polecenie SMS, w budżecie odpowiedzi alarmu na
  postoju, GSM-7): ``ALFA 156: BUDZENIE wyslane`` albo powód odmowy
  (wyłączone, limit, nieudane). „Wysłane” znaczy: dioda nadała — czy
  komputer wstał, decyduje Nano (BCM po starcie pokaże baner „Wybudzono”).
  Gdy BCM milczał przed budzeniem (:data:`WAKE_SILENT_S`) i w ciągu
  :data:`WAKE_CONFIRM_S` przyjdzie od niego pierwsze podpisane żądanie,
  ten sam numer dostaje drugą odpowiedź ``ALFA 156: komputer obudzony -
  BCM odpowiada`` (raz na budzenie; bez 2-minutowej przerwy odpowiedzi,
  w dziennym budżecie). Bez niej po 10 min — komputer nie wstał albo nie
  doszedł do agenta (brak osobnego SMS-a „nie wstał”).
* NIESPRAWDZONE na crDroid 13: że Termux:API obsługuje nadajnik IR tego
  telefonu (``termux-infrared-frequencies`` powinno pokazać zakres z 38 kHz)
  i że wzorzec 3 ramek mieści się w limicie długości ConsumerIrManager.
* Na przyszłość (nie w tej wersji): budzenie z głównego telefonu przez
  prywatny temat ntfy/MQTT z HMAC — dziś zapasem jest SMS ``WAKE <kod>``.

Czego agent nie obiecuje: doręczenia (brak raportów doręczenia, zasięg,
środki na karcie), działania przy wyłączonym lub przegrzanym telefonie,
działania, gdy Android zabije Termux (phantom process killer), zestawienia
połączenia z 112 ani jakości głośnika pod podsufitką. To nie eCall.
Czuwanie kabiny nie rozpozna człowieka (sama różnica klatek), a w nocy
bez lampki zdjęcia są czarne (kamera przednia ma filtr IR).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import logging
import logging.handlers
import math
import os
import queue
import re
import secrets
import signal
import stat
import struct
import subprocess
import sys
import threading
import time
import urllib.parse
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Mapping, Optional

try:                                # Termux (Linux) ma fcntl; inne systemy nie
    import fcntl
except ImportError:                 # pragma: no cover
    fcntl = None  # type: ignore[assignment]

#: 1.1.0 — „Zadzwoń 112” (plan H): ``/v1/call112*``, pola ``call112_*`` w
#: konfiguracji. BCM z włączonym ``modules.call112`` wymaga co najmniej tej
#: wersji (starszą pokazuje w Ustawieniach jako „zaktualizuj bcm_agent.py”).
#: 1.2.0 — alarm na postoju (plan D4): ``/v1/park*``, pola ``park_*``
#: (wymagane przez BCM z włączonym ``modules.parking_guard``).
#: 1.3.0 — czuwanie kabiny (plan I): ``GET /v1/cabin``, ``POST
#: /v1/park/event``, pola ``cabin_*`` (wymagane przez BCM z włączonym
#: ``modules.cabin_watch``).
#: 1.4.0 — budzenie komputera podczerwienią (plan E): przełącznik
#: ``toggles.remote_session``, pola ``wake_*``, SMS ``WAKE <kod>``,
#: ``--wake`` (wymagane przez BCM z włączonym ``modules.remote_session``).
#: 1.5.0 — wyłączenie z BCM przy uzbrojonym czeka na dowód właściciela
#: (``off_pending``), alarm na postoju nie uzbraja się sam po wypadku i 112,
#: kabina bez zdjęć w czasie rozmowy 112, odpowiedź „komputer obudzony” po
#: ``WAKE <kod>``. BCM tej wersji nie wymaga.
VERSION = "1.5.0"

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
TOGGLES = ("crash_sms", "parking_guard", "cabin_watch", "call112", "remote_session")
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

# ── alarm na postoju (plan D4) ────────────────────────────────────────────
#: Stany ``GET /v1/park``: ``off`` = przełącznik ``parking_guard`` wyłączony;
#: ``log_only`` = uzbrojony w trybie „tylko log” (pierwszy tydzień —
#: strojenie progów, żadnych automatycznych SMS-ów).
PARK_STATES = ("off", "disarmed", "arming", "armed", "alarm", "log_only")
#: Stany zapisywane na dysku (``off`` i ``log_only`` są tylko widokiem).
PARK_SAVED_STATES = ("disarmed", "arming", "armed", "alarm")
#: Kto/co ustawiło bieżący stan (``by`` w widoku i w park.json).
PARK_BY = ("", "power", "bcm", "sms", "owner_bt", "owner_sms", "owner_code", "low_battery",
           "home", "off", "power_back", "crash")
#: ``cabin`` = alarm czuwania kabiny (plan I) — ten sam „alarm auta”;
#: ``crash_holdoff`` = po wypadku / 112 bez uzbrojenia albo rozbrojony
#: (:data:`PARK_CRASH_HOLDOFF_S`).
PARK_EVENT_KINDS = ("tilt", "shake", "power", "low_battery", "home", "cabin", "crash_holdoff")
#: Konfiguracja z BCM (``PUT /v1/config``), wartości domyślne. Klucze
#: ``park_*`` liczą się do skrótu konfiguracji TYLKO przy włączonym
#: przełączniku ``parking_guard`` (zgodność wersji — jak ``call112_*``).
PARK_DEFAULTS: dict[str, Any] = {
    "park_numbers": [], "park_log_only": True, "park_arm_after_min": 3,
    "park_arm_delay_min": 2, "park_grace_min": 3, "park_home": None,
    "park_tilt_deg": 0.5, "park_shake_k": 6.0, "park_entry_s": 90,
}
#: (najmniej, najwięcej) dla liczb konfiguracji. ``park_entry_s`` = okno
#: wejścia (0 = alarm od razu, jak przed tą zmianą).
PARK_INT_RANGES = {"park_arm_after_min": (1, 60), "park_arm_delay_min": (0, 30),
                   "park_grace_min": (1, 15), "park_entry_s": (0, 300)}
PARK_FLOAT_RANGES = {"park_tilt_deg": (0.2, 10.0), "park_shake_k": (2.0, 50.0)}
PARK_HOME_RADIUS_M = (50, 5000)
#: Pozycja z gorszą dokładnością nie rozstrzyga „jestem w domu” (uzbrajam).
PARK_HOME_MAX_ACC_M = 500
#: Przechył musi trwać tyle, kołysanie tyle (plan D4).
TILT_HOLD_S = 3.0
SHAKE_HOLD_S = 0.5
#: SMS-y alarmowe: najwyżej 1 na 10 min i 6 na dobę — budżet OSOBNY od
#: SMS-ów o wypadku (te i tak idą pierwsze, patrz :meth:`Agent._deliveries`).
PARK_ALARM_COOLDOWN_S = 600
PARK_ALARM_MAX_PER_DAY = 6
#: Odpowiedzi na polecenia SMS: 1 na numer na 2 min, 10 na numer na dobę.
PARK_REPLY_COOLDOWN_S = 120
PARK_REPLY_MAX_PER_DAY = 10
#: Złe kody TOTP z jednego numeru: po tylu w godzinie numer jest
#: ignorowany do końca tej godziny (zgadywanie 6 cyfr).
PARK_BAD_CODE_MAX = 5
PARK_BAD_CODE_WINDOW_S = 3600
#: Skrzynka odbiorcza co 30 s (tylko z przełącznikiem, numerami i TOTP).
PARK_INBOX_EVERY_S = 30.0
PARK_INBOX_LIMIT = 10
PARK_INBOX_MAX_BYTES = 64 * 1024
#: Polecenie starsze niż 10 min (albo sprzed startu agenta) nie działa.
PARK_SMS_MAX_AGE_S = 600
PARK_SMS_MAX_BODY = 64
#: Ile identyfikatorów przeczytanych SMS-ów pamiętam (deduplikacja).
PARK_SEEN_MAX = 256
#: Bateria: co tyle przy uzbrojonym (zasilanie wróciło?), co tyle poza nim.
PARK_BATTERY_ARMED_S = 180.0
PARK_BATTERY_IDLE_S = 60.0
#: Kontakt BCM przy uzbrojonym → sprawdzenie zasilania najwyżej co tyle.
PARK_CONTACT_KICK_S = 30.0
#: Okno wejścia (``park_entry_s``): bateria co tyle, a przed terminem
#: odczyt nie starszy niż tyle — właściciel, który właśnie zapalił silnik,
#: nie może dostać alarmu tylko dlatego, że bateria była czytana 3 min temu.
PARK_ENTRY_BATTERY_S = 15.0
PARK_ENTRY_FRESH_S = 5.0
#: Rodzaje wyzwoleń, które czekają na okno wejścia (właściciel otwiera
#: drzwi i siada — to samo, co złodziej). Zasilanie bez właściciela ma
#: własne okno (``park_grace_min``).
PARK_ENTRY_KINDS = ("tilt", "shake")
#: Rozbrojenia przez właściciela: tylko one kasują czekający alarm i SMS-y
#: alarmowe, które jeszcze nie wyszły (wypadek — ``crash`` — kasuje tylko
#: czekający, patrz :meth:`ParkGuard.crash_locked`).
#: Niska bateria — nie: prawdziwy alarm ma wyjść mimo rozbrojenia.
#: Wyłączenie przełącznika z BCM (``off``) TEŻ NIE jest dowodem właściciela:
#: Ustawienia → Moduły ma każdy, kto siedzi przy ekranie auta (złodziej po
#: zapłonie też) — przy uzbrojonym czeka na dowód (:meth:`ParkGuard.step`).
PARK_OWNER_BY = ("owner_bt", "owner_code", "owner_sms")
#: Po wypadku (zdarzenie od BCM ``POST /v1/crash``, nieodwołane, nie na
#: próbę) albo po „Zadzwoń 112” z tego telefonu (prawdziwe, nie testowe):
#: tyle sekund bez SAMEGO uzbrojenia (zasilanie, BCM). Wariant testowy nie
#: ma bufora — odcięcie prądu po wypadku wygląda dla telefonu jak zwykły
#: postój, a właściciel jest przy aucie, ale nie ma jak tego udowodnić
#: (BCM nie działa, ranny kierowca nie wyśle PARK OFF). Krócej niż
#: :data:`KEEP_EVENTS_S` — zdarzenie jest jeszcze w pamięci. Działa TYLKO,
#: gdy BCM doręczył wypadek telefonowi (``modules.crash_sms`` + sparowany
#: agent) albo 112 poszło z tego telefonu.
PARK_CRASH_HOLDOFF_S = 6 * 3600
#: Samo uzbrojenie i to od BCM: paczka próbek tuż przed uzbrojeniem; ruch
#: większy niż jazda (odchylenie od średniej, m/s²) przesuwa uzbrojenie
#: o minutę — najwyżej tyle razy (potem uzbrajam mimo to: czujnik, który
#: zawsze „jedzie”, nie może wyłączyć alarmu na zawsze). Kabel USB, który
#: odpadnie w czasie jazdy, nie uzbraja telefonu w ruchu.
PARK_MOVING_MS2 = 0.25
PARK_MOVING_RETRY_S = 60.0
PARK_MOVING_MAX = 30
#: Po nieudanym GPS (``-r once``: brak pozycji albo przekroczony czas) tyle
#: sekund bez kolejnej próby GPS dla poleceń i strefy „dom” (garaż: każde
#: POZYCJA nie czeka 60 s na GPS, którego nie będzie). Alarm próbuje GPS
#: zawsze — auto mogło właśnie zostać wywiezione spod dachu.
PARK_GPS_SKIP_S = 600.0
#: Wersja „lekka” (paczka próbek co :data:`PARK_LIGHT_EVERY_S` zamiast
#: ciągłego strumienia): po dobie uzbrojenia albo poniżej 30% baterii.
PARK_LIGHT_AFTER_S = 24 * 3600.0
PARK_LIGHT_PCT = 30
PARK_LIGHT_EVERY_S = 20.0
PARK_BURST_SAMPLES = 10
#: Poniżej tylu % rozbrojenie z jednym SMS-em (telefon ma działać dalej).
PARK_LOW_PCT = 15
#: Czujnik: co 100 ms (10 Hz), restart strumienia z backoffem.
SENSOR_DELAY_MS = 100
SENSOR_BACKOFF_MIN_S = 5.0
SENSOR_BACKOFF_MAX_S = 300.0
#: Strumień bez próbki przez tyle sekund = zawieszony (restart).
SENSOR_STALL_S = 30.0
#: Strumień, który przeżył tyle, zeruje backoff.
SENSOR_GOOD_RUN_S = 60.0
#: Tyle czekam na koniec wątku czytającego po zatrzymaniu strumienia.
SENSOR_JOIN_S = 2.0
SENSOR_LIST_RETRY_S = 600.0
SENSOR_NAME_RE = re.compile(r"^[A-Za-z0-9 _.()/+-]{1,64}$")
SENSOR_LINE_MAX = 4096
SENSOR_OBJ_MAX_LINES = 64
#: Pozycja: GPS do 60 s, potem sieć, potem ostatnia znana (plan D4).
PARK_LOCATION_STEPS = ((["-p", "gps", "-r", "once"], 60.0),
                       (["-p", "network", "-r", "once"], 30.0),
                       (["-p", "gps", "-r", "last"], 10.0),
                       (["-p", "network", "-r", "last"], 10.0))
#: Pozycja młodsza niż tyle służy kolejnym zadaniom bez nowego pomiaru.
PARK_FIX_REUSE_S = 60.0
PARK_MAX_JOBS = 8
PARK_KEEP_SMS_S = 3600.0
PARK_MAX_SMS = 16
#: Najdłuższe czekanie wątku postoju (zdarzenia i tak go budzą).
PARK_MAX_WAIT_S = 30.0
#: TOTP (RFC 6238): SHA1, 6 cyfr, krok 30 s, ±1 krok.
TOTP_STEP_S = 30
TOTP_DIGITS = 6
TOTP_SKEW = 1
TOTP_SECRET_BYTES = 20
TOTP_FILE = "park_totp"
PARK_LOCAL_FILE = "park_local.json"
_B32_RE = re.compile(r"^[A-Z2-7]{16,64}$")
_PARK_CMD_RE = re.compile(r"^(POZYCJA|GDZIE|PARKON|PARKOFF|PARKSTATUS|WAKE)([0-9]{6})$")
_PARK_CODE_RE = re.compile(r"^[0-9]{6}$")
PARK_COMMANDS = {"POZYCJA": "position", "GDZIE": "position", "PARKON": "on",
                 "PARKOFF": "off", "PARKSTATUS": "status", "WAKE": "wake"}

# ── budzenie komputera podczerwienią (plan E) ─────────────────────────────
#: Konfiguracja z BCM (``power.remote_session.ir_address`` / ``ir_command``),
#: wartości domyślne = WAKE_IR_ADDRESS / WAKE_IR_COMMAND w wake_logic.h.
#: Klucze ``wake_*`` (i sam przełącznik ``remote_session``) liczą się do
#: skrótu konfiguracji TYLKO przy włączonym przełączniku (zgodność wersji —
#: jak ``call112_*``).
WAKE_DEFAULTS: dict[str, Any] = {"wake_ir_address": 0x7A15, "wake_ir_command": 0x56}
IR_CARRIER_HZ = 38000
#: NEC: znacznik prowadzący, przerwa, znacznik bitu, przerwa „0” / „1” [µs].
NEC_LEAD_MARK_US = 9000
NEC_LEAD_SPACE_US = 4500
NEC_BIT_MARK_US = 562
NEC_ZERO_US = 562
NEC_ONE_US = 1687
#: Ramki w jednym nadaniu i odstęp początków ramek (jak pilot NEC).
NEC_FRAMES = 3
NEC_PERIOD_US = 108000
#: Limit w telefonie (Nano ma własny: 3/h, 6/dobę przyjętych pobudek).
WAKE_COOLDOWN_S = 60
#: Po udanym ``WAKE <kod>``: pierwsze podpisane żądanie BCM w tym czasie =
#: „komputer obudzony” (BCM wstaje i forward agenta rośnie w 1–2 min; Nano
#: daje 10 min dzierżawy).
WAKE_CONFIRM_S = 600
#: … ale tylko, gdy BCM milczał przed budzeniem co najmniej tyle (działający
#: BCM pyta co 30 s — jego żądanie nie znaczy, że budzenie zadziałało).
WAKE_SILENT_S = 120
WAKE_MAX_PER_HOUR = 3
WAKE_MAX_PER_DAY = 6
WAKE_FILE = "wake.json"
WAKE_LOCK_FILE = "wake.lock"
WAKE_LOCK_WAIT_S = 30.0          # ``--wake`` (wake.sh) czeka dłużej
WAKE_LOCK_WAIT_SMS_S = 5.0       # wątek postoju — krótko
IR_TIMEOUT_S = 15.0
#: Wynik jednej próby: ``sent`` (dioda nadała), ``off`` (przełącznik
#: ``remote_session`` wyłączony), ``rate`` (limit), ``busy`` (inna próba
#: trwa), ``no_ir`` (brak termux-infrared-transmit / nadajnika), ``failed``.
WAKE_RESULTS = ("sent", "off", "rate", "busy", "no_ir", "failed")

# ── czuwanie kabiny (plan I) ──────────────────────────────────────────────
#: Stany ``GET /v1/cabin``: ``off`` = przełącznik ``cabin_watch`` albo
#: ``parking_guard`` wyłączony; ``idle`` = alarm na postoju NIE jest
#: uzbrojony (kamera nigdy poza uzbrojeniem); ``watching`` = czuwa;
#: ``pending`` = zdarzenie czeka w oknie wejścia na dowód właściciela.
CABIN_STATES = ("off", "idle", "watching", "pending")
#: Stan warstwy kamery: ``ok`` albo powód, dla którego jest wyłączona.
#: ``in_call`` = trwa połączenie 112 z tego telefonu (ekran rozmowy ma
#: zostać na wierzchu, żadnych zdjęć ludzi przy aucie).
CABIN_CAMERA = ("ok", "unknown", "light_mode", "low_battery", "no_temp", "cold", "hot",
                "charging_hot", "no_space", "no_front_camera", "bad_path", "in_call")
#: Wynik zdarzenia: ``pending`` (okno wejścia) → ``alarm`` (SMS w kolejce) |
#: ``owner`` (dowód właściciela: odwołane, zdjęcia usunięte) | ``off``
#: (tylko w starych plikach stanu: dawniej wyłączenie z BCM odwoływało jak
#: dowód właściciela) | ``crash`` (wypadek / 112: odwołane, zdjęcia
#: usunięte) | ``logged`` (``park_log_only``: bez SMS-a) | ``limited``
#: (budżet SMS-ów alarmu auta wyczerpany) | ``no_numbers`` | ``expired``
#: (agent nie działał w chwili terminu, ponad 30 min temu).
CABIN_OUTCOMES = ("pending", "alarm", "owner", "off", "logged", "limited", "no_numbers",
                  "expired", "crash")
#: Wyniki, przy których zdjęcia zdarzenia są usuwane i które nie liczą się
#: do limitu serii (wejście właściciela / po wypadku nie zużywa budżetu).
CABIN_PURGED = ("owner", "off", "crash")
#: Sygnały w kolejności, w jakiej trafiają do treści SMS-a. ``power`` =
#: prąd wrócił (zapłon) bez dowodu właściciela — tylko dopisek do alarmu.
CABIN_SIGNALS = ("door", "light", "shake", "tilt", "power")
CABIN_SIGNAL_TEXT = {"door": "drzwi", "light": "swiatlo", "shake": "ruch", "tilt": "przechyl",
                     "power": "zasilanie"}
#: Silne sygnały (każdy sam = zdarzenie) i słabe (para światło + ruch w
#: :data:`CABIN_PAIR_S` albo :data:`CABIN_WEAK_N` słabych w
#: :data:`CABIN_WEAK_WINDOW_S`, w tym co najmniej dwa ruchy — skoki światła
#: liczą się razem jak JEDEN słaby sygnał: powtarzające się błyski
#: (światła awaryjne auta obok, koguty lawety, burza, kolejne auta) to
#: wciąż jedno źródło, a nikt nie wejdzie do auta, nie kołysząc nim).
CABIN_STRONG = ("tilt", "door")
CABIN_WEAK = ("light", "shake")
CABIN_PAIR_S = 10.0
CABIN_WEAK_WINDOW_S = 60.0
CABIN_WEAK_N = 3
#: Ruch dla kabiny co najwyżej raz na tyle sekund (własny rytm, niezależny
#: od 30 s przerwy alarmu na postoju — :attr:`MotionDetector.COOLDOWN_S`):
#: inaczej w 60 s zmieszczą się tylko dwa ruchy i samo kołysanie (dzień,
#: jasna kabina, lampka bez skoku ×5) nigdy nie da 3 słabych sygnałów. Przy
#: 10 s ok. 20 s ciągłego kołysania = zdarzenie (zdjęcia); SMS-ów nie
#: przybywa — alarm postoju i tak alarmuje już pojedynczym wstrząsem.
CABIN_SHAKE_COOLDOWN_S = 10.0
#: Sygnały z zewnątrz (``POST /v1/park/event``).
CABIN_EXT_SIGNALS = ("door",)
#: Skok światła (lampka sufitowa): co najmniej ×5 i +5 lux względem
#: najciemniejszej próbki z ostatnich 2 s; potem 10 s przerwy. ×5 i +5 lux
#: to wartości domyślne — BCM może je zmienić (``cabin_light_ratio``,
#: ``cabin_light_lux``) po tygodniu kalibracji w trybie ``park_log_only``.
LIGHT_RATIO = 5.0
LIGHT_DELTA_LUX = 5.0
LIGHT_WINDOW_S = 2.0
LIGHT_COOLDOWN_S = 10.0
LIGHT_MAX_LUX = 200000.0
#: Ostatni odczyt światła jest „świeży” tyle sekund (widok, klasa światła).
LIGHT_FRESH_S = 60.0
#: Po sesji aparatu skoki światła się nie liczą jeszcze tyle sekund (ekran
#: był włączony, a czujnik światła jest po stronie ekranu).
CABIN_LIGHT_MUTE_S = 5.0
#: Górna granica wyciszenia na czas samej sesji (sesja trwa ok. 10 s).
CABIN_SESSION_MUTE_S = 120.0
CABIN_PHOTOS = 3
CABIN_PHOTO_GAP_S = 3.0
#: Po ostatnim zdjęciu tyle sekund na zapis pliku przez Termux:API.
CABIN_SETTLE_S = 2.0
CABIN_PHOTO_TIMEOUT_S = 20.0
CABIN_PHOTO_MAX_BYTES = 15 * 1024 * 1024
#: Zdarzeń kabiny (serii zdjęć): najwyżej 1 na 10 min i 6 na dobę (odwołane
#: przez właściciela się nie liczą).
CABIN_EVENT_COOLDOWN_S = 600
CABIN_EVENT_MAX_PER_DAY = 6
#: Bez aparatu: bateria telefonu poniżej 0 °C albo powyżej 45 °C, przy
#: ładowaniu już od 40 °C, bateria poniżej 30%.
CABIN_TEMP_MIN_C = 0.0
CABIN_TEMP_MAX_C = 45.0
CABIN_CHARGING_HOT_C = 40.0
CABIN_MIN_PCT = 30
#: Odczyt baterii starszy niż tyle — nowy przed sesją aparatu.
CABIN_BATTERY_FRESH_S = 60.0
#: Retencja zdjęć: 72 h i 200 MB (najstarsze pierwsze), sprawdzana co 10 min;
#: bez 100 MB wolnego miejsca aparat się nie włącza.
CABIN_KEEP_S = 72 * 3600.0
CABIN_MAX_BYTES = 200 * 1024 * 1024
CABIN_MIN_FREE_BYTES = 100 * 1024 * 1024
CABIN_CLEANUP_EVERY_S = 600.0
#: Pliki tymczasowe (przerwany zapis) starsze niż tyle — usuwane.
CABIN_TMP_KEEP_S = 3600.0
CABIN_CAMERA_RETRY_S = 3600.0
#: Zdjęcie odniesienia tyle sekund po uzbrojeniu (tylko z Pillow).
CABIN_REF_DELAY_S = 30.0
CABIN_MAX_EVENTS = 32
CABIN_VIEW_EVENTS = 5
CABIN_MAX_WAIT_S = 30.0
CABIN_DIR = "cabin"
CABIN_FILE = "cabin.json"
CABIN_REF_RAW = "ref_raw.jpg"
#: Konfiguracja z BCM (``PUT /v1/config``) — w skrócie konfiguracji TYLKO
#: przy włączonym przełączniku ``cabin_watch`` (zgodność wersji jak
#: ``park_*``). ``cabin_mask``: prostokąty ``[x0, y0, x1, y1]`` w % kadru
#: (okna), których analiza nie liczy.
#: ``cabin_light_ratio`` / ``cabin_light_lux``: progi skoku światła
#: (:class:`LightDetector`) — do kalibracji w aucie bez zmiany kodu.
CABIN_DEFAULTS: dict[str, Any] = {"cabin_entry_s": 60, "cabin_diff_pct": 3.0, "cabin_mask": [],
                                  "cabin_light_ratio": LIGHT_RATIO,
                                  "cabin_light_lux": LIGHT_DELTA_LUX}
CABIN_ENTRY_RANGE = (45, 60)
CABIN_DIFF_RANGE = (0.5, 50.0)
CABIN_LIGHT_RATIO_RANGE = (2.0, 50.0)
CABIN_LIGHT_LUX_RANGE = (1.0, 1000.0)
CABIN_MASK_MAX = 4
#: Analiza (Pillow): kadr, rozmycie, próg różnicy jasności piksela, średnia
#: jasność, poniżej której klatka jest „ciemna” (noc bez lampki).
CABIN_FRAME = (320, 240)
CABIN_BLUR = 2
CABIN_PIXEL_DELTA = 25
CABIN_DARK_MEAN = 12.0
CABIN_REENCODE_SIDE = 1280
CABIN_JPEG_QUALITY = 85
#: Klasy światła (lux, górna granica) — odniesienie tylko z tej samej klasy.
LIGHT_CLASSES = (("dark", 10.0), ("dim", 200.0), ("bright", math.inf))
CABIN_VERDICTS = ("change", "no_change", "dark", "skipped", "error")
CABIN_REF_MODES = ("ref", "burst")
CAMERA_ID_RE = re.compile(r"^[0-9]{1,2}$")
#: Ścieżka dla ``termux-camera-photo`` (skrypt wkleja ją bez cudzysłowu do
#: ``am broadcast`` — tylko te znaki, bez spacji).
CABIN_PATH_RE = re.compile(r"^/[A-Za-z0-9/._-]{1,240}$")
_CABIN_ID_RE = re.compile(r"^[0-9a-f]{16}$")
_CABIN_PHOTO_RE = re.compile(r"^cab_([0-9a-f]{16})_([0-2])\.jpg$")
_CABIN_REF_RE = re.compile(r"^ref_(dark|dim|bright)\.png$")
#: Stałe ciągi dla ``su -c`` (sprawdzane jeszcze raz przez :data:`SU_SAFE_RE`).
WAKE_COMMAND = "input keyevent KEYCODE_WAKEUP"
SLEEP_COMMAND = "input keyevent KEYCODE_SLEEP"
#: ``-W``: ``am start`` czeka, aż aktywność Termuxa się wyświetli — Android
#: 11+ daje aparat dopiero aplikacji na pierwszym planie, a bez ``-W``
#: pierwsze zdjęcie szłoby, gdy start aktywności jest jeszcze w toku.
FOREGROUND_COMMAND = ("am start -W -a android.intent.action.MAIN "
                      "-c android.intent.category.LAUNCHER com.termux")
CABIN_SU_COMMANDS = (WAKE_COMMAND, FOREGROUND_COMMAND, SLEEP_COMMAND)

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
    SMS-a po stłuczce). Tak samo pola ``park_*`` (alarm na postoju, 1.2.0)
    — tylko przy włączonym ``parking_guard``, a ``cabin_*`` (czuwanie
    kabiny, 1.3.0) — tylko przy włączonym ``cabin_watch``.

    Budzenie IR (1.4.0) idzie dalej, bo dokłada też PRZEŁĄCZNIK: wyłączony
    ``toggles.remote_session`` nie liczy się do skrótu wcale (BCM wysyła go
    tylko włączony, a agent ≤ 1.3.0 zna cztery przełączniki), a pola
    ``wake_*`` — tylko przy włączonym."""
    toggles = cfg.get("toggles")
    on = isinstance(toggles, Mapping) and toggles.get("call112") is True
    park = isinstance(toggles, Mapping) and toggles.get("parking_guard") is True
    cabin = isinstance(toggles, Mapping) and toggles.get("cabin_watch") is True
    wake = isinstance(toggles, Mapping) and toggles.get("remote_session") is True
    view = {k: v for k, v in cfg.items()
            if (on or not k.startswith("call112_")) and (park or not k.startswith("park_"))
            and (cabin or not k.startswith("cabin_")) and (wake or not k.startswith("wake_"))}
    if isinstance(toggles, Mapping) and not wake:
        view["toggles"] = {k: v for k, v in toggles.items() if k != "remote_session"}
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


def stop_process(proc: Any, term_s: float = 3.0, kill_s: float = 2.0) -> None:
    """Zatrzymaj proces razem z jego potomkami: SIGTERM do całej GRUPY
    procesów (proces startuje z ``start_new_session=True``), po ``term_s``
    SIGKILL. Dlaczego grupa: polecenia Termux:API to skrypty powłoki, które
    uruchamiają pomocnika ``termux-api`` jako dziecko — a bash z pułapką na
    SIGTERM czeka, aż dziecko skończy, więc sygnał do samego skryptu nic nie
    daje, a osierocony pomocnik trzyma rurę stdout i rejestrację czujnika.
    Bez liczbowego ``pid`` (atrapy w testach) — ``terminate()``/``kill()``.
    SIGKILL tylko do grupy procesu, który jeszcze nie został zebrany
    (``wait``), więc numer grupy nie mógł trafić do obcego procesu. Nigdy
    nie rzuca."""
    pid = getattr(proc, "pid", None)
    group = isinstance(pid, int) and not isinstance(pid, bool) and pid > 1

    def send(sig: int, fallback: str) -> None:
        if group:
            try:
                os.killpg(pid, sig)
                return
            except ProcessLookupError:
                return
            except OSError:
                pass
        try:
            getattr(proc, fallback)()
        except Exception:
            pass

    send(signal.SIGTERM, "terminate")
    try:
        proc.wait(timeout=term_s)
        return
    except Exception:
        pass
    send(signal.SIGKILL, "kill")
    try:
        proc.wait(timeout=kill_s)
    except Exception:
        pass


def default_runner(argv: list, stdin: Optional[str], timeout: float) -> tuple[int, str, str]:
    """Jedno polecenie: lista argumentów (NIGDY powłoka), limit czasu, nigdy
    nie rzuca. 127 = brak programu, 124 = przekroczony czas. Własna grupa
    procesów, a po przekroczeniu czasu :func:`stop_process` na całą grupę —
    zabicie samego skryptu Termux:API zostawiłoby jego pomocnika
    ``termux-api`` na zawsze (czeka w ``accept()`` bez limitu czasu)."""
    if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
        return 2, "", "invalid command"
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, errors="replace",
                                shell=False, start_new_session=True)
    except FileNotFoundError:
        return RC_MISSING, "", f"{argv[0]} not installed"
    except OSError as e:
        return 1, "", f"{argv[0]}: {e}"
    try:
        out, err = proc.communicate(input=stdin if stdin is not None else "", timeout=timeout)
    except subprocess.TimeoutExpired:
        stop_process(proc, term_s=1.0, kill_s=2.0)
        try:
            proc.communicate(timeout=2.0)
        except Exception:
            pass
        return RC_TIMEOUT, "", f"{argv[0]} timed out"
    except OSError as e:
        stop_process(proc, term_s=1.0, kill_s=2.0)
        return 1, "", f"{argv[0]}: {e}"
    return proc.returncode, out or "", err or ""


def _clean(text: Any, limit: int = 160) -> str:
    s = re.sub(r"[\x00-\x1f\x7f]+", " ", str(text)).strip()
    return s[:limit]


def _digits(num: Any) -> str:
    return re.sub(r"[^0-9]", "", num) if isinstance(num, str) else ""


# ── budzenie IR (plan E): czyste funkcje ──────────────────────────────────

def nec_frame(address: int, command: int) -> list:
    """Jedna ramka NEC jako czasy znacznik/przerwa w µs (zaczyna i kończy
    się znacznikiem): prowadzący 9 ms + 4,5 ms, 32 bity od najmłodszego —
    adres 16 bitów (młodszy bajt pierwszy), polecenie, negacja polecenia —
    i znacznik końcowy. Ten sam układ dekoduje wake_logic.h."""
    data = (address & 0xFFFF) | ((command & 0xFF) << 16) | (((~command) & 0xFF) << 24)
    out = [NEC_LEAD_MARK_US, NEC_LEAD_SPACE_US]
    for i in range(32):
        out.append(NEC_BIT_MARK_US)
        out.append(NEC_ONE_US if (data >> i) & 1 else NEC_ZERO_US)
    out.append(NEC_BIT_MARK_US)
    return out


def nec_pattern(address: Any, command: Any, frames: int = NEC_FRAMES) -> Optional[list]:
    """Wzorzec ``termux-infrared-transmit``: ``frames`` ramek co
    :data:`NEC_PERIOD_US` (przerwa dopełnia okres). None dla czegokolwiek
    poza liczbą całkowitą adresu 0..65535 i polecenia 0..255 — nic innego
    nie trafia do wiersza polecenia."""
    for v, hi in ((address, 0xFFFF), (command, 0xFF)):
        if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= hi:
            return None
    if isinstance(frames, bool) or not isinstance(frames, int) or not 1 <= frames <= 5:
        return None
    frame = nec_frame(address, command)
    out: list = []
    for i in range(frames):
        if i:
            out.append(NEC_PERIOD_US - sum(frame))     # przerwa (po znaczniku)
        out.extend(frame)
    return out


def ir_argv(pattern: list) -> list:
    """Stała lista argumentów: program, ``-f 38000`` i wzorzec z liczb."""
    if not isinstance(pattern, list) or not pattern or len(pattern) > 400 or not all(
            isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 200000 for v in pattern):
        raise ValueError("bad IR pattern")
    return ["termux-infrared-transmit", "-f", str(IR_CARRIER_HZ),
            ",".join(str(int(v)) for v in pattern)]


def wake_reply_text(label: str, result: str) -> str:
    """Odpowiedź na SMS ``WAKE <kod>`` (GSM-7, bez polskich liter)."""
    return {
        "sent": f"{label}: BUDZENIE wyslane",
        "off": f"{label}: BUDZENIE wylaczone w telefonie",
        "rate": (f"{label}: BUDZENIE odrzucone - limit (1 na minute, {WAKE_MAX_PER_HOUR} na "
                 f"godzine, {WAKE_MAX_PER_DAY} na dobe)"),
        "busy": f"{label}: BUDZENIE odrzucone - trwa inne budzenie",
        # Druga odpowiedź: po budzeniu przyszło pierwsze żądanie od BCM.
        "woke": f"{label}: komputer obudzony - BCM odpowiada",
    }.get(result, f"{label}: BUDZENIE nieudane - brak nadajnika IR albo blad Termux:API")


def _wake_lock(path: str, wait_s: float) -> Optional[int]:
    """Wyłączna blokada pliku (agent i ``--wake`` to dwa procesy) albo None
    po ``wait_s`` (inna próba trwa). Bez fcntl — bez blokady (nie Termux)."""
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    if fcntl is None:               # pragma: no cover
        return fd
    deadline = time.monotonic() + wait_s
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except OSError:
            if time.monotonic() >= deadline:
                os.close(fd)
                return None
            time.sleep(0.1)


def _wake_walls(raw: Any, wall: float) -> list:
    """Znaczniki z ``wake.json`` z ostatniej doby (bez śmieci, najwyżej 32)."""
    out = [float(w) for w in raw if _number(w, EVENT_TS_MIN, EVENT_TS_MAX) is not None] \
        if isinstance(raw, list) else []
    return sorted(w for w in out if abs(wall - w) < DAY_S)[-32:]


def wake_ir(state_dir: str, transmit: Callable[[list], "tuple[bool, str]"],
            cfg: Mapping[str, Any], wall: float, source: str,
            lock_wait_s: float = WAKE_LOCK_WAIT_S) -> str:
    """Jedna próba budzenia: przełącznik, limit, nadanie, zapis — pod
    blokadą pliku. Zwraca jeden z :data:`WAKE_RESULTS`. Nigdy nie rzuca.

    ``transmit(pattern) -> (ok, powód)`` to :meth:`Phone.ir_transmit`
    (testy: atrapa). Limit: najwyżej 1 próba na :data:`WAKE_COOLDOWN_S`
    (także nieudana — zepsuty nadajnik nie jest męczony co SMS), 3 udane na
    godzinę i 6 na dobę. ``source``: ``sms`` / ``local`` (tylko do logu)."""
    toggles = cfg.get("toggles") if isinstance(cfg, Mapping) else None
    if not (isinstance(toggles, Mapping) and toggles.get("remote_session") is True):
        log.warning("WAKE (%s): refused — remote_session is off on the phone", source)
        return "off"
    pattern = nec_pattern(cfg.get("wake_ir_address"), cfg.get("wake_ir_command"))
    if pattern is None:
        log.error("WAKE (%s): bad IR code in the config — not sent", source)
        return "failed"
    try:
        fd = _wake_lock(os.path.join(state_dir, WAKE_LOCK_FILE), lock_wait_s)
    except OSError as e:
        log.error("WAKE (%s): cannot open the lock file: %s", source, _clean(e))
        return "failed"
    if fd is None:
        log.warning("WAKE (%s): another wake is in progress", source)
        return "busy"
    try:
        path = os.path.join(state_dir, WAKE_FILE)
        try:
            raw = read_small(path, 16384)
            st = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant) if raw else {}
        except (OSError, ValueError, UnicodeDecodeError, RecursionError):
            st = {}
        if not isinstance(st, dict):
            st = {}
        tries, sent = _wake_walls(st.get("tries"), wall), _wake_walls(st.get("sent"), wall)
        if (tries and abs(wall - tries[-1]) < WAKE_COOLDOWN_S) or len(sent) >= WAKE_MAX_PER_DAY \
                or len([w for w in sent if abs(wall - w) < 3600]) >= WAKE_MAX_PER_HOUR:
            log.warning("WAKE (%s): refused — limit (1 per %d s, %d per hour, %d per day)",
                        source, WAKE_COOLDOWN_S, WAKE_MAX_PER_HOUR, WAKE_MAX_PER_DAY)
            return "rate"
        tries.append(wall)
        try:
            ok, why = transmit(pattern)
        except Exception as e:          # atrapa / nieprzewidziany błąd — nie wywracaj wątku
            ok, why = False, _clean(e)
        if ok:
            sent.append(wall)
        result = "sent" if ok else ("no_ir" if why == "no_ir" else "failed")
        st = {"tries": tries[-32:], "sent": sent[-32:],
              "last": {"wall": int(wall), "result": result,
                       "source": source if source in ("sms", "local") else "local"}}
        try:
            atomic_write(path, canonical_json(st).encode("ascii"))
        except OSError as e:
            log.error("WAKE: cannot save %s: %s", WAKE_FILE, _clean(e))
        if ok:
            log.warning("WAKE (%s): IR frame sent (3 frames, NEC %#06x/%#04x)", source,
                        cfg.get("wake_ir_address"), cfg.get("wake_ir_command"))
        else:
            log.warning("WAKE (%s): IR transmit failed (%s)", source, why or "?")
        return result
    finally:
        try:
            os.close(fd)                # zamknięcie zwalnia blokadę flock
        except OSError:
            pass


class Phone:
    """Termux:API przez ``runner``. Każda metoda nigdy nie rzuca."""

    def __init__(self, runner: Runner, clock: Callable[[], float]) -> None:
        self._run = runner
        self._clock = clock
        self._service: Optional[tuple[float, Optional[bool]]] = None
        self.sms_permission: Optional[bool] = None
        #: Kiedy (zegar od startu) ostatni GPS ``-r once`` nic nie dał.
        self.gps_failed_at: Optional[float] = None

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

    def ir_transmit(self, pattern: list) -> tuple[bool, str]:
        """``termux-infrared-transmit -f 38000 <wzorzec>`` (budzenie, plan E):
        ``(True, "")`` albo ``(False, powód)``. Powodzenie = kod 0 i puste
        wyjście — Termux:API pisze tekst, gdy nie ma nadajnika albo
        parametry są złe (NIESPRAWDZONE na crDroid 13). Nigdy nie rzuca."""
        try:
            argv = ir_argv(pattern)
        except ValueError:
            return False, "bad_pattern"
        rc, out, err = self._run(argv, None, IR_TIMEOUT_S)
        if rc == RC_MISSING:
            return False, "no_ir"
        text = ((out or "") + (err or "")).strip()
        if rc != 0 or text:
            return False, _clean(text or f"rc {rc}", 80)
        return True, ""

    def su(self, command: str, timeout: float = SU_TIMEOUT_S) -> tuple[int, str, str]:
        """Jedno polecenie przez Magisk ``su -c`` (patrz :func:`su_argv`:
        tylko ciągi zbudowane z naszych stałych). Nigdy nie rzuca."""
        try:
            argv = su_argv(command)
        except ValueError:
            return 2, "", "refused: not a fixed command"
        return self._run(argv, None, timeout)

    # ── alarm na postoju (plan D4) ────────────────────────────────────────

    def sms_inbox(self) -> Optional[list]:
        """Ostatnie :data:`PARK_INBOX_LIMIT` wiadomości ze skrzynki
        odbiorczej (``termux-sms-list -t inbox``) — surowe słowniki, które
        :meth:`ParkGuard._inbox_item` sprawdza pole po polu. None = nie da
        się odczytać (brak READ_SMS, błąd, za duża odpowiedź)."""
        obj = self._json(["termux-sms-list", "-t", "inbox", "-l", str(PARK_INBOX_LIMIT)],
                         limit=PARK_INBOX_MAX_BYTES)
        if not isinstance(obj, list):
            return None
        return [i for i in obj[:PARK_INBOX_LIMIT * 2] if isinstance(i, dict)]

    def location(self, try_gps: bool = True) -> Optional[dict]:
        """Jedna pozycja na żądanie: najpierw GPS (``-r once``, do 60 s),
        potem sieć, na końcu ostatnia znana (``-r last``) — zwalidowana
        przez :func:`parse_location`. None = żadna z prób nic nie dała.
        GPS włączany tylko tu (polecenie SMS, alarm, sprawdzenie strefy
        „dom”), nigdy stale — bateria na postoju. ``try_gps=False`` pomija
        GPS ``-r once`` (świeża porażka: garaż); porażkę i sukces GPS
        zapisuje :attr:`gps_failed_at`."""
        for args, timeout in PARK_LOCATION_STEPS:
            gps_once = args[1] == "gps" and args[3] == "once"
            if gps_once and not try_gps:
                continue
            rc, out, _err = self._run(["termux-location", *args], None, timeout)
            fix = parse_location(out) if rc == 0 and len(out) <= 65536 else None
            if gps_once:
                self.gps_failed_at = None if fix is not None else self._clock()
            if fix is not None:
                return fix
        return None

    def sensor_names(self) -> Optional[list]:
        """``termux-sensor -l`` → lista nazw czujników (None = błąd)."""
        obj = self._json(["termux-sensor", "-l"], limit=65536)
        names = obj.get("sensors") if isinstance(obj, dict) else None
        if not isinstance(names, list):
            return None
        return [n for n in names[:200] if isinstance(n, str)]

    def sensor_burst(self, name: str) -> str:
        """Paczka :data:`PARK_BURST_SAMPLES` próbek co 100 ms (tryb „lekki”
        i sprawdzenie „czy auto jedzie”; ``termux-sensor -n``, sam się
        kończy) — surowe wyjście albo "" (wtedy wołający zwalnia czujnik
        przez ``-c``: nieudana paczka mogła go zostawić zarejestrowanego)."""
        if not isinstance(name, str) or not SENSOR_NAME_RE.fullmatch(name):
            return ""
        rc, out, _err = self._run(["termux-sensor", "-s", name, "-d", str(SENSOR_DELAY_MS),
                                   "-n", str(PARK_BURST_SAMPLES)], None, 15.0)
        return out[:262144] if rc == 0 else ""

    def sensor_cleanup(self) -> None:
        """``termux-sensor -c``: Termux:API zwalnia czujnik. Zabicie procesu
        strumienia go nie wyrejestrowuje, a Termux:API tworzy nowego
        „pisarza” próbek tylko, gdy starego już nie ma — bez ``-c`` każdy
        następny strumień i każda paczka ``-n`` nie dostałyby nic (i czujnik
        pracowałby dalej: bateria)."""
        self._run(["termux-sensor", "-c"], None, 10.0)

    # ── czuwanie kabiny (plan I) ──────────────────────────────────────────

    def camera_info(self) -> Optional[str]:
        """Surowe wyjście ``termux-camera-info`` (None = błąd) — sprawdza je
        :func:`parse_camera_info`."""
        rc, out, _err = self._run(["termux-camera-info"], None, API_TIMEOUT_S)
        return out if rc == 0 and len(out) <= 262144 else None

    def camera_photo(self, camera_id: str, path: str) -> tuple[bool, str]:
        """Jedno ``termux-camera-photo -c <id> <ścieżka>``: id (1–2 cyfry)
        i ścieżka (:func:`valid_photo_path`) sprawdzone TUTAJ jeszcze raz —
        nic innego nie trafia do argumentów. ``(ok, błąd)``."""
        if not isinstance(camera_id, str) or not CAMERA_ID_RE.fullmatch(camera_id) \
                or not valid_photo_path(path):
            return False, "refused: invalid camera id or path"
        rc, out, err = self._run(["termux-camera-photo", "-c", camera_id, path], None,
                                 CABIN_PHOTO_TIMEOUT_S)
        detail = _clean(err or out)
        if rc != 0 or any(w in detail.lower() for w in ("error", "exception", "permission")):
            return False, detail or f"termux-camera-photo exit {rc}"
        return True, ""


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
#: Rodzaje wysyłek: wypadek, odwołanie, test, „wybrano 112” oraz SMS-y
#: alarmu na postoju (alarm, odpowiedź na polecenie, informacja o baterii).
DELIVERY_KINDS = ("crash", "cancel", "test", "call112", "park_alarm", "park_reply",
                  "park_info")


def valid_delivery(d: Any) -> bool:
    """Kształt zapisanej wysyłki (plik mógł zostać uszkodzony albo podmieniony)."""
    if not isinstance(d, dict) or d.get("kind") not in DELIVERY_KINDS:
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
        spawn: długo żyjący proces (strumień ``termux-sensor``; testy).
        mktime: odwrotność ``localtime`` (czas SMS-a z ``termux-sms-list``).
        pillow: czuwanie kabiny — ``"auto"`` (import PIL, jeśli jest), None
            (bez Pillow) albo obiekt z :func:`load_pillow` (testy).
    """

    def __init__(self, state_dir: str = DEFAULT_STATE_DIR, runner: Runner = default_runner,
                 clock: Callable[[], float] = boot_clock,
                 wall: Callable[[], float] = time.time,
                 localtime: Callable[[float], time.struct_time] = time.localtime,
                 spawn: Optional[Spawner] = None,
                 mktime: Callable[[time.struct_time], float] = time.mktime,
                 pillow: Any = "auto") -> None:
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
                                                  "call112_wall": None, "park_sms": [],
                                                  "call112_real_wall": None})
        # SMS-y alarmu na postoju (alarm, odpowiedzi, bateria) — w meta.json,
        # bo zapisuje go każdy krok harmonogramu wysyłki; uszkodzone pomijam.
        park_sms = self.meta.get("park_sms")
        self.meta["park_sms"] = [d for d in park_sms if valid_delivery(d)
                                 and d["kind"].startswith("park_")][:PARK_MAX_SMS] \
            if isinstance(park_sms, list) else []
        for d in self.meta["park_sms"]:
            fill_delivery_defaults(d)
        test = self.meta.get("test")
        if test is not None and not (isinstance(test, dict)
                                     and valid_delivery(test.get("delivery"))):
            self.meta["test"] = None
        elif test is not None:
            fill_delivery_defaults(test["delivery"])
        # ``call112_real_wall``: ostatnie PRAWDZIWE 112 z tego telefonu (nie
        # cofane po nieudanym ``am start``) — wstrzymuje samo uzbrojenie
        # alarmu na postoju (PARK_CRASH_HOLDOFF_S).
        for key in ("last_test_wall", "last_sent_ts", "last_verified_test_ts", "call112_wall",
                    "call112_real_wall"):
            if _number(self.meta.get(key), 0, EVENT_TS_MAX) is None:
                self.meta[key] = None
        self.events: list[dict] = self._load_events()
        # „Zadzwoń 112”: bieżące (albo ostatnie) połączenie — tylko w
        # pamięci (po restarcie agenta stan rozmowy i tak jest nieznany;
        # limit 1 na minutę jest w meta.json). ``su`` sprawdzany w wątku
        # stanu: None = jeszcze nie wiadomo.
        self.call: Optional[dict] = None
        # Numer połączenia rośnie także między restartami agenta (start od
        # milisekund zegara): BCM, któremu zginęła odpowiedź na POST,
        # rozpoznaje „swoje” połączenie po numerze większym niż każdy
        # widziany w tym przebiegu BCM — po restarcie agenta od 1 nowe
        # połączenie wyglądałoby na stare, BCM uznałby 112 za nieudane
        # i zaproponował drugie z głównego telefonu.
        self._call_seq = int(wall() * 1000)
        self.call_wake = threading.Event()
        self._su_ok: Optional[bool] = None
        self._su_checked: Optional[float] = None
        self._call_state: Optional[int] = None
        # Alarm na postoju (plan D4): stan z park.json, wątek :meth:`run_park`.
        self.park = ParkGuard(self, spawn if spawn is not None else default_spawn, mktime,
                              pillow)
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
        for d in self.meta.get("park_sms") or []:
            # SMS postoju sprzed restartu: dokończony, chyba że ma > 30 min
            # (alarm sprzed pół godziny nikomu już nie pomoże).
            self._reset_runtime(d, now)
            if not delivery_done(d) and wall - float(d.get("created_wall", 0)) > RESUME_MAX_LATE_S:
                self._fail_rest(d, "expired")
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
        if path == "/v1/park":
            return "park_get", None, method == "GET"
        if path == "/v1/park/arm":
            return "park_arm", None, method == "POST"
        if path == "/v1/park/disarm":
            return "park_disarm", None, method == "POST"
        if path == "/v1/park/event":
            return "park_event", None, method == "POST"
        if path == "/v1/cabin":
            return "cabin_get", None, method == "GET"
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
        # Podpisane żądanie = BCM żyje (alarm na postoju: „brak kontaktu z BCM”).
        self.park.note_contact()
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
        elif name == "park_get":
            status, out = 200, self.park.view()
        elif name == "park_arm":
            status, out = self.park.http_arm(obj)
        elif name == "park_disarm":
            status, out = self.park.http_disarm(obj)
        elif name == "park_event":
            status, out = self.park.http_event(obj)
        elif name == "cabin_get":
            status, out = 200, self.park.cabin.view()
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
            # Alarm uzbrojony, a BCM wyłączył przełącznik: ustawienia alarmu
            # zostają do dowodu właściciela (ParkGuard.keep_settings_locked).
            kept = self.park.keep_settings_locked(norm)
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
        if kept and changed:
            log.warning("Config: %s switched off on BCM while the parking guard is armed — its "
                        "settings stay until the owner disarms", "+".join(kept))
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
        if changed:
            if norm["toggles"]["parking_guard"]:
                log.info("Parking guard config: %d number(s), %s, arm after %d+%d min, home %s",
                         len(norm["park_numbers"]),
                         "LOG ONLY" if norm["park_log_only"] else "alarm SMS",
                         norm["park_arm_after_min"], norm["park_arm_delay_min"],
                         "set" if norm["park_home"] else "-")
            if norm["toggles"]["cabin_watch"]:
                log.info("Cabin watch config: entry window %d s, change >= %.2f%%, %d mask "
                         "rectangle(s), light jump x%.2f and +%.2f lux%s",
                         norm["cabin_entry_s"], norm["cabin_diff_pct"], len(norm["cabin_mask"]),
                         norm["cabin_light_ratio"], norm["cabin_light_lux"],
                         "" if norm["toggles"]["parking_guard"] else " — needs parking_guard")
            self.park.cabin.config_changed()
            self.park.wake.set()
            self.park.cabin.wake.set()
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
            if not dry:
                # Wypadek: alarm na postoju rozbrojony bez alarmu, samo
                # uzbrojenie wstrzymane (PARK_CRASH_HOLDOFF_S).
                self.park.crash_locked("crash event from BCM", wall)
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
            if mine == "real":
                self.meta["call112_real_wall"] = wall
            # Alarm na postoju / czuwanie kabiny nie mogą działać przy
            # rozmowie z dyspozytorem (zdjęcia, Termux na wierzchu, SMS).
            self.park.crash_locked("112 call", wall)
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
        odwołanie, „wybrano 112”, alarm na postoju, test."""
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
        # Alarm na postoju: ZA wszystkim, co dotyczy wypadku (pierwszeństwo
        # SMS-a o wypadku), przed SMS-em testowym.
        for d in self.meta.get("park_sms") or []:
            if isinstance(d, dict) and not delivery_done(d):
                yield d, None
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

    def run_park(self, stop: threading.Event) -> None:
        """Wątek alarmu na postoju (:meth:`ParkGuard.step`); przy wyłączonym
        ``parking_guard`` tylko co :data:`PARK_MAX_WAIT_S` sprawdza
        przełącznik — zero wywołań Termux:API."""
        while not stop.is_set():
            self.park.wake.clear()
            try:
                wait = self.park.step()
            except Exception:
                log.exception("Parking guard step failed")
                wait = 5.0
            if wait > 0:
                self.park.wake.wait(wait)
        try:
            self.park.shutdown()
        except Exception:
            log.exception("Parking guard shutdown failed")

    def run_cabin(self, stop: threading.Event) -> None:
        """Wątek czuwania kabiny (:meth:`CabinWatch.step`): aparat, analiza,
        EXIF, retencja — nigdy w wątku postoju ani pod blokadą agenta.
        Przy wyłączonym czuwaniu tylko retencja co 10 min."""
        cabin = self.park.cabin
        while not stop.is_set():
            cabin.wake.clear()
            try:
                wait = cabin.step()
            except Exception:
                log.exception("Cabin watch step failed")
                wait = 5.0
            if wait > 0:
                cabin.wake.wait(min(wait, CABIN_MAX_WAIT_S))
        try:
            cabin.shutdown()
        except Exception:
            log.exception("Cabin watch shutdown failed")


# ── alarm na postoju (plan D4): czyste funkcje ────────────────────────────

def totp_code(key: bytes, counter: int, digits: int = TOTP_DIGITS) -> str:
    """HOTP (RFC 4226) dla licznika ``counter``; TOTP (RFC 6238) to HOTP
    z licznikiem ``czas_unix // 30`` i HMAC-SHA1 — to samo liczy każda
    aplikacja „authenticator” (Aegis, FreeOTP)."""
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    off = mac[-1] & 0x0F
    value = struct.unpack(">I", mac[off:off + 4])[0] & 0x7FFFFFFF
    return str(value % (10 ** digits)).zfill(digits)


def totp_verify(key: bytes, code: Any, wall: float,
                last_counter: Optional[int]) -> tuple[str, Optional[int]]:
    """``("ok", krok)``, ``("replay", krok)`` (kod dobry, ale ten krok albo
    późniejszy był już użyty — RFC 6238 §5.2: drugi raz ten sam kod nie
    przechodzi) albo ``("bad", None)``. Okno ±:data:`TOTP_SKEW` kroku (zegar
    telefonu albo aplikacji spóźniony o kilkadziesiąt sekund). Porównanie
    w stałym czasie, zawsze wszystkie kroki okna."""
    if not isinstance(code, str) or not _PARK_CODE_RE.fullmatch(code) or not key:
        return "bad", None
    now = int(wall // TOTP_STEP_S)
    found: Optional[int] = None
    for step in range(now - TOTP_SKEW, now + TOTP_SKEW + 1):
        if step >= 0 and hmac.compare_digest(totp_code(key, step), code):
            found = step
    if found is None:
        return "bad", None
    if last_counter is not None and found <= last_counter:
        return "replay", found
    return "ok", found


def new_totp_secret() -> str:
    """Losowy sekret TOTP (20 bajtów z ``secrets``) w base32 bez ``=``."""
    return base64.b32encode(secrets.token_bytes(TOTP_SECRET_BYTES)).decode("ascii").rstrip("=")


def parse_totp_secret(text: Any) -> Optional[bytes]:
    """Zapisany sekret (base32) → bajty klucza; None dla czegokolwiek innego."""
    if not isinstance(text, str):
        return None
    s = text.strip().upper().replace(" ", "")
    if not _B32_RE.fullmatch(s):
        return None
    try:
        return base64.b32decode(s + "=" * (-len(s) % 8))
    except ValueError:
        return None


def otpauth_uri(secret_b32: str, label: str = DEFAULT_LABEL) -> str:
    """``otpauth://totp/…`` do aplikacji „authenticator” (wklejenie albo
    kod QR). Sekret tylko na ekran — nigdy do logu."""
    account = urllib.parse.quote(f"BCM:{label} postoj")
    return (f"otpauth://totp/{account}?secret={secret_b32}&issuer=BCM"
            f"&algorithm=SHA1&digits={TOTP_DIGITS}&period={TOTP_STEP_S}")


def power_of(battery: Any) -> Optional[str]:
    """``termux-battery-status`` → ``plugged`` | ``unplugged`` | None (nie
    wiadomo: błąd odczytu, brak pola, nieznana wartość). Tylko pole
    ``plugged`` — NIE ``status``: przy ograniczniku ładowania (ACC 40–60%)
    telefon na kablu raportuje DISCHARGING / NOT_CHARGING."""
    if not isinstance(battery, dict):
        return None
    plugged = battery.get("plugged")
    if plugged in ("UNPLUGGED", "NONE"):
        return "unplugged"
    if isinstance(plugged, str) and plugged.startswith("PLUGGED"):
        return "plugged"
    return None


def parse_location(text: Any) -> Optional[dict]:
    """Wyjście ``termux-location`` → ``{lat, lon, acc, age_s, provider}``
    albo None (brak pozycji, błąd API, wartości spoza zakresu, „null
    island” 0,0). ``age_s`` z ``elapsedMs`` (wiek pomiaru)."""
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        obj = json.loads(text, parse_constant=_reject_constant)
    except (ValueError, RecursionError):
        return None
    if not isinstance(obj, dict):
        return None
    lat = _number(obj.get("latitude"), -90, 90)
    lon = _number(obj.get("longitude"), -180, 180)
    if lat is None or lon is None or (lat == 0 and lon == 0):
        return None
    acc = _number(obj.get("accuracy"), 0, 1_000_000)
    age = _number(obj.get("elapsedMs"), 0, 10 ** 13)
    provider = obj.get("provider")
    return {"lat": float(lat), "lon": float(lon),
            "acc": None if acc is None else int(round(acc)),
            "age_s": None if age is None else int(age // 1000),
            "provider": provider if provider in ("gps", "network", "fused", "passive") else None}


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Odległość po kuli (haversine) w metrach."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371000.0 * math.asin(min(1.0, math.sqrt(h)))


def at_home(fix: Optional[dict], home: Optional[dict]) -> bool:
    """Czy pozycja jest w strefie „dom”. Bez pozycji albo z dokładnością
    gorszą niż :data:`PARK_HOME_MAX_ACC_M` — NIE (lepiej uzbroić w domu,
    niż nie uzbroić pod sklepem)."""
    if not fix or not home:
        return False
    acc = fix.get("acc")
    if acc is None or acc > PARK_HOME_MAX_ACC_M:
        return False
    return distance_m(fix["lat"], fix["lon"], home["lat"], home["lon"]) <= home["radius_m"]


def match_sender(raw: Any, numbers: list) -> Optional[str]:
    """Nadawca SMS-a → numer z białej listy (E.164, dokładnie ten zapis,
    który potem trafia do ``termux-sms-send``) albo None. ``+…``/``00…``
    musi się zgadzać co do cyfry; zapis krajowy (bez kierunkowego, ≥ 9
    cyfr) pasuje do końcówki numeru z listy, ale tylko jednoznacznie."""
    if not isinstance(raw, str) or len(raw) > 32:
        return None
    s = re.sub(r"[\s().-]", "", raw)
    if s.startswith("00"):
        s = "+" + s[2:]
    if s.startswith("+"):
        return s if E164_RE.fullmatch(s) and s in numbers else None
    if not re.fullmatch(r"[0-9]{9,15}", s):
        return None
    hits = [n for n in numbers if n.endswith(s) and 1 <= len(n) - 1 - len(s) <= 3]
    return hits[0] if len(hits) == 1 else None


def parse_park_command(body: Any) -> Optional[tuple[str, str]]:
    """Treść SMS-a → ``(polecenie, kod)``: wielkość liter i spacje bez
    znaczenia (``park off 123 456`` = ``PARKOFF123456``). Polecenia:
    POZYCJA / GDZIE → ``position``, PARK ON / OFF / STATUS → ``on`` /
    ``off`` / ``status``, WAKE → ``wake`` (budzenie komputera IR, plan E).
    Zawsze z 6-cyfrowym kodem TOTP."""
    if not isinstance(body, str) or len(body) > PARK_SMS_MAX_BODY:
        return None
    m = _PARK_CMD_RE.fullmatch(re.sub(r"\s+", "", body).upper())
    return (PARK_COMMANDS[m.group(1)], m.group(2)) if m else None


def parse_received(value: Any,
                   mktime: Callable[[time.struct_time], float] = time.mktime) -> Optional[float]:
    """``"2026-11-19 14:03:07"`` (czas lokalny telefonu z ``termux-sms-list``)
    → epoch; None, gdy format jest inny."""
    if not isinstance(value, str) or len(value) > 32:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            t = time.strptime(value.strip(), fmt)
        except ValueError:
            continue
        try:
            return float(mktime(t))
        except (OverflowError, ValueError):
            return None
    return None


def pick_accelerometer(names: Any) -> Optional[str]:
    """Nazwa akcelerometru z ``termux-sensor -l``: zawiera „accelerometer”,
    nie „uncalibrated” ani „linear” (te dwa to inne czujniki); nazwa
    trafia jako jeden argument do ``termux-sensor -s``, więc tylko bezpieczne
    znaki i bez przecinka (``-s`` dzieli listę przecinkami)."""
    if not isinstance(names, list):
        return None
    ok = [n for n in names if isinstance(n, str) and SENSOR_NAME_RE.fullmatch(n)]
    for want in ("accelerometer", "accel"):
        for n in ok:
            low = n.lower()
            if want in low and "uncalibrated" not in low and "linear" not in low:
                return n
    return None


def _vec3(values: Any) -> Optional[tuple[float, float, float]]:
    if not isinstance(values, list) or len(values) < 3:
        return None
    out = []
    for v in values[:3]:
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) \
                or abs(v) > 1000:
            return None
        out.append(float(v))
    return out[0], out[1], out[2]


def sensor_vectors(obj: Any, name: Optional[str] = None,
                   exclude: Optional[str] = None) -> list:
    """Obiekt ``termux-sensor`` (``{"<nazwa>": {"values": [x, y, z]}}``) →
    ``[(x, y, z)]`` — wpis o dokładnie tej nazwie (``-s`` dopasowuje też
    fragment nazwy, więc w strumieniu bywa np. wersja „Uncalibrated”),
    a bez niej pierwszy, który nie jest ``exclude`` (czujnik światła w tym
    samym strumieniu: jego ``[lux, 0, 0]`` nie może udawać przyspieszenia).
    Wszystko inne — pusta lista."""
    if not isinstance(obj, dict) or not obj:
        return []
    items = list(obj.items())[:8]
    chosen = [v for k, v in items if k == name] if name is not None else []
    rest = [v for k, v in items if k != exclude][:1]
    for item in chosen or rest:
        if isinstance(item, dict):
            vec = _vec3(item.get("values"))
            if vec is not None:
                return [vec]
    return []


def sensor_lux(obj: Any, name: Optional[str]) -> Optional[float]:
    """Natężenie światła (lux) z wpisu ``name`` obiektu ``termux-sensor``
    (``{"<nazwa>": {"values": [lux, …]}}``): skończona liczba
    0..:data:`LIGHT_MAX_LUX`, inaczej None."""
    if not name or not isinstance(obj, dict):
        return None
    item = obj.get(name)
    values = item.get("values") if isinstance(item, dict) else None
    if not isinstance(values, list) or not values:
        return None
    lux = _number(values[0], 0.0, LIGHT_MAX_LUX)
    return None if lux is None else float(lux)


def pick_light(names: Any) -> Optional[str]:
    """Nazwa czujnika światła z ``termux-sensor -l``: zawiera „light”, nie
    „uncalibrated” ani „flicker” (inne czujniki); najpierw taka bez
    „proximity” (czujnik łączony podaje czasem tylko zbliżenie). Te same
    zasady znaków co :func:`pick_accelerometer` (bez przecinka)."""
    if not isinstance(names, list):
        return None
    ok = [n for n in names if isinstance(n, str) and SENSOR_NAME_RE.fullmatch(n)
          and "light" in n.lower() and not any(w in n.lower()
                                               for w in ("uncalibrated", "flicker"))]
    pure = [n for n in ok if "proximity" not in n.lower()]
    return (pure or ok or [None])[0]


class SensorParser:
    """Wyjście ``termux-sensor`` linia po linii → wektory przyspieszenia
    (:meth:`feed_line`) albo próbki ``("a", (x, y, z))`` / ``("l", lux)``
    (:meth:`feed_items`, strumień z czujnikiem światła ``light``).

    termux-sensor wypisuje obiekty JSON jeden po drugim, sformatowane
    w wielu liniach (``{`` i ``}`` w pierwszej kolumnie); bywa też jeden
    obiekt w linii. Śmieci, urwane obiekty i za długie linie są pomijane
    (licznik ``garbage``) — parser nigdy nie rzuca i nie rośnie bez końca."""

    def __init__(self, name: Optional[str] = None, light: Optional[str] = None) -> None:
        self._name = name
        self._light = light
        self._buf: Optional[list] = None
        self._size = 0
        self.garbage = 0

    def _parse(self, text: str) -> Optional[list]:
        try:
            obj = json.loads(text, parse_constant=_reject_constant)
        except (ValueError, RecursionError):
            return None
        if not isinstance(obj, dict):
            return None
        out: list = [("a", v) for v in sensor_vectors(obj, self._name, self._light)]
        lux = sensor_lux(obj, self._light)
        if lux is not None:
            out.append(("l", lux))
        return out

    def feed_line(self, line: Any) -> list:
        """Jedna linia → wektory przyspieszenia (bez światła)."""
        return [v for k, v in self.feed_items(line) if k == "a"]

    def feed_items(self, line: Any) -> list:
        if not isinstance(line, str):
            return []
        if len(line) > SENSOR_LINE_MAX:
            self._buf = None
            self.garbage += 1
            return []
        text = line.rstrip("\r\n")
        stripped = text.strip()
        if not stripped:
            return []
        if text.startswith("{"):
            # Nowy obiekt najwyższego poziomu; niedokończony przed nim = śmieć.
            if self._buf is not None:
                self.garbage += 1
            self._buf = None
            if stripped.endswith("}"):
                one = self._parse(stripped)
                if one is not None:
                    return one
            self._buf = [text]
            self._size = len(text)
            return []
        if self._buf is None:
            self.garbage += 1
            return []
        self._buf.append(text)
        self._size += len(text)
        if text.startswith("}"):
            joined = "\n".join(self._buf)
            self._buf = None
            out = self._parse(joined)
            if out is None:
                self.garbage += 1
                return []
            return out
        if len(self._buf) > SENSOR_OBJ_MAX_LINES or self._size > SENSOR_LINE_MAX * 4:
            self._buf = None
            self.garbage += 1
        return []

    def feed_text(self, text: Any) -> list:
        """Całe wyjście (paczka ``-n``) → wektory przyspieszenia."""
        out: list = []
        for line in (text if isinstance(text, str) else "").splitlines()[:4000]:
            out.extend(self.feed_line(line))
        return out


def _sub(a: tuple, b: tuple) -> tuple:
    return a[0] - b[0], a[1] - b[1], a[2] - b[2]


def _norm(v: tuple) -> float:
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


def _lerp(a: tuple, b: tuple, k: float) -> tuple:
    return a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k, a[2] + (b[2] - a[2]) * k


def angle_deg(a: tuple, b: tuple) -> float:
    """Kąt między wektorami w stopniach (atan2 — dokładny także dla
    ułamków stopnia, gdzie acos traci precyzję)."""
    cross = (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
    dot = a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
    return math.degrees(math.atan2(_norm(cross), dot))


def burst_spread(vecs: list) -> Optional[float]:
    """Rozrzut paczki próbek (m/s²): pierwiastek ze średniego kwadratu
    odchylenia od średniej. Stojące auto ma tu setne części (szum czujnika,
    wiatr), jadące — dziesiąte i więcej (nierówności, silnik). None przy
    mniej niż 5 poprawnych próbkach."""
    vs = []
    for v in vecs or []:
        try:
            t = (float(v[0]), float(v[1]), float(v[2]))
        except (TypeError, ValueError, IndexError):
            continue
        if all(math.isfinite(c) and abs(c) < 200.0 for c in t):
            vs.append(t)
    if len(vs) < 5:
        return None
    n = float(len(vs))
    mean = (sum(v[0] for v in vs) / n, sum(v[1] for v in vs) / n, sum(v[2] for v in vs) / n)
    return math.sqrt(sum(_norm(_sub(v, mean)) ** 2 for v in vs) / n)


def _alpha(dt: float, tau: float) -> float:
    return 1.0 - math.exp(-dt / tau) if dt > 0 else 0.0


class MotionDetector:
    """Przechył i kołysanie z akcelerometru (m/s², z grawitacją). Czysta
    logika — czas podaje wywołujący (testy: sztuczny zegar).

    * **Kalibracja:** pierwsze :data:`CALIB_S` s po uzbrojeniu dają wektor
      odniesienia (kierunek grawitacji) i poziom szumu.
    * **Przechył** (podnośnik, holowanie): kąt między średnią krótką
      (τ 0,5 s) a wolnym odniesieniem (τ 15 min — dryf temperatury, siadające
      koło) ≥ ``tilt_deg`` przez ≥ :data:`TILT_HOLD_S`. Po wykryciu nowa
      pozycja staje się odniesieniem.
    * **Kołysanie / wstrząs:** odchylenie od średniej (τ 1 s) ponad
      ``shake_k`` × szum przez ≥ :data:`SHAKE_HOLD_S` (krótkie przerwy do
      0,25 s się nie liczą — pojedynczy pik, np. przejeżdżająca ciężarówka,
      nie wystarczy). Szum uczy się powoli, tylko w spokoju, z dolną granicą
      (idealnie cichy czujnik nie może dać progu ≈ 0).
    * Po każdym wykryciu :data:`COOLDOWN_S` przerwy dla tego rodzaju.
    * **Ruch dla czuwania kabiny** — te same kołysania, ale z własną,
      krótszą przerwą :data:`CABIN_SHAKE_COOLDOWN_S` i osobno od wyniku
      :meth:`feed`: po każdej próbce :attr:`cabin_shake` = krotność szumu
      albo None. Alarm na postoju (wynik :meth:`feed`) widzi dokładnie te same
      wstrząsy co bez kabiny (jego przerwa 30 s nie jest tym zużywana).
    """

    CALIB_S = 5.0
    WARM_S = 1.0
    FAST_TAU_S = 0.5
    HP_TAU_S = 1.0
    REF_TAU_S = 900.0
    NOISE_TAU_S = 120.0
    NOISE_FLOOR = 0.02
    GAP_S = 5.0
    COOLDOWN_S = 30.0
    SHAKE_GAP_S = 0.25
    MIN_G = 2.0
    MAX_G = 30.0

    def __init__(self, tilt_deg: float = 0.5, shake_k: float = 6.0) -> None:
        self.tilt_deg = float(tilt_deg)
        self.shake_k = float(shake_k)
        self.ref: Optional[tuple] = None
        self.noise: Optional[float] = None
        self.samples = 0
        self._cal_start: Optional[float] = None
        self._cal_sum = (0.0, 0.0, 0.0)
        self._cal_dev = 0.0
        self._cal_n = 0
        self._fast: Optional[tuple] = None
        self._hp: Optional[tuple] = None
        self._t: Optional[float] = None
        self._warm_until = 0.0
        self._tilt_since: Optional[float] = None
        self._shake_since: Optional[float] = None
        self._shake_last: Optional[float] = None
        self._shake_peak = 0.0
        self._cool: dict[str, float] = {}
        self._burst_tilt: Optional[float] = None
        #: Ruch dla czuwania kabiny z OSTATNIEJ próbki :meth:`feed` (krotność
        #: szumu) albo None — rytm co najwyżej 1 na CABIN_SHAKE_COOLDOWN_S.
        self.cabin_shake: Optional[float] = None

    @property
    def calibrated(self) -> bool:
        return self.ref is not None

    def gap(self) -> None:
        """Przerwa w danych (nowy proces strumienia): krótkie filtry od nowa."""
        self._t = None

    def _valid(self, v: tuple) -> bool:
        m = _norm(v)
        return math.isfinite(m) and self.MIN_G <= m <= self.MAX_G

    def _cooled(self, kind: str, t: float, cooldown: Optional[float] = None) -> bool:
        last = self._cool.get(kind)
        if last is not None and 0 <= t - last < (self.COOLDOWN_S if cooldown is None
                                                 else cooldown):
            return False
        self._cool[kind] = t
        return True

    def feed(self, t: float, x: float, y: float, z: float) -> Optional[tuple[str, float]]:
        """Jedna próbka strumienia → ``("tilt", stopnie)`` /
        ``("shake", krotność szumu)`` albo None (alarm na postoju); ruch dla
        czuwania kabiny osobno w :attr:`cabin_shake`."""
        self.cabin_shake = None
        v = (float(x), float(y), float(z))
        if not self._valid(v):
            return None
        self.samples += 1
        dt = None if self._t is None else t - self._t
        self._t = t
        if dt is None or dt < 0 or dt > self.GAP_S:
            self._fast = v
            self._hp = v
            self._warm_until = t + self.WARM_S
            self._tilt_since = None
            self._shake_since = None
            dt = 0.0
        else:
            self._fast = _lerp(self._fast, v, _alpha(dt, self.FAST_TAU_S))
            self._hp = _lerp(self._hp, v, _alpha(dt, self.HP_TAU_S))
        dev = _norm(_sub(v, self._hp))
        if self.ref is None:
            if self._cal_start is None:
                self._cal_start = t
            self._cal_sum = (self._cal_sum[0] + v[0], self._cal_sum[1] + v[1],
                             self._cal_sum[2] + v[2])
            self._cal_dev += dev
            self._cal_n += 1
            if t - self._cal_start >= self.CALIB_S and self._cal_n >= 10:
                n = float(self._cal_n)
                self.ref = (self._cal_sum[0] / n, self._cal_sum[1] / n, self._cal_sum[2] / n)
                self.noise = max(self.NOISE_FLOOR, self._cal_dev / n)
                self._warm_until = max(self._warm_until, t)
            return None
        if t < self._warm_until:
            return None
        event: Optional[tuple[str, float]] = None
        ang = angle_deg(self._fast, self.ref)
        if ang >= self.tilt_deg:
            if self._tilt_since is None:
                self._tilt_since = t
            elif t - self._tilt_since >= TILT_HOLD_S:
                self._tilt_since = None
                self.ref = self._fast            # nowa pozycja = odniesienie
                if self._cooled("tilt", t):
                    event = ("tilt", ang)
        else:
            self._tilt_since = None
            self.ref = _lerp(self.ref, self._fast, _alpha(dt, self.REF_TAU_S))
        noise = self.noise or self.NOISE_FLOOR
        ratio = dev / noise
        if ratio > self.shake_k:
            if self._shake_since is None:
                self._shake_since = t
                self._shake_peak = 0.0
            self._shake_last = t
            self._shake_peak = max(self._shake_peak, ratio)
            if t - self._shake_since >= SHAKE_HOLD_S:
                peak = self._shake_peak
                self._shake_since = None
                if self._cooled("cabin_shake", t, CABIN_SHAKE_COOLDOWN_S):
                    self.cabin_shake = peak
                if event is None and self._cooled("shake", t):
                    event = ("shake", peak)
        elif self._shake_last is None or t - self._shake_last > self.SHAKE_GAP_S:
            self._shake_since = None
        if ratio < self.shake_k / 2:
            self.noise = max(self.NOISE_FLOOR,
                             noise + (dev - noise) * _alpha(dt, self.NOISE_TAU_S))
        return event

    def feed_burst(self, t: float, samples: list,
                   step: float = SENSOR_DELAY_MS / 1000.0) -> Optional[tuple[str, float]]:
        """Paczka próbek z trybu „lekkiego” (``termux-sensor -n``, co
        :data:`PARK_LIGHT_EVERY_S`). Przechył: średnia paczki względem
        odniesienia w DWÓCH kolejnych paczkach (≥ :data:`TILT_HOLD_S`);
        kołysanie: ≥ 0,5 s kolejnych próbek ponad progiem w jednej paczce.
        Bez osobnego ruchu dla kabiny (w wersji lekkiej kabina nie robi zdjęć
        ruchu ani przechyłu)."""
        self.cabin_shake = None
        vs = [tuple(float(c) for c in s) for s in samples if len(s) >= 3]
        vs = [v for v in vs if self._valid(v)]
        if len(vs) < 3:
            return None
        self.samples += len(vs)
        n = float(len(vs))
        mean = (sum(v[0] for v in vs) / n, sum(v[1] for v in vs) / n, sum(v[2] for v in vs) / n)
        devs = [_norm(_sub(v, mean)) for v in vs]
        mdev = sum(devs) / n
        if self.ref is None:
            self.ref = mean
            self.noise = max(self.NOISE_FLOOR, mdev)
            self._burst_tilt = None
            return None
        event: Optional[tuple[str, float]] = None
        ang = angle_deg(mean, self.ref)
        if ang >= self.tilt_deg:
            if self._burst_tilt is None:
                self._burst_tilt = t
            elif t - self._burst_tilt >= TILT_HOLD_S:
                self._burst_tilt = None
                self.ref = mean
                if self._cooled("tilt", t):
                    event = ("tilt", ang)
        else:
            self._burst_tilt = None
            self.ref = _lerp(self.ref, mean, _alpha(PARK_LIGHT_EVERY_S, self.REF_TAU_S))
        noise = self.noise or self.NOISE_FLOOR
        need = max(2, int(math.ceil(SHAKE_HOLD_S / step)) + 1)
        run = peak = best = 0.0
        for d in devs:
            r = d / noise
            if r > self.shake_k:
                run += 1
                peak = max(peak, r)
                if run >= need:
                    best = max(best, peak)
            else:
                run = 0
                peak = 0.0
        if best and event is None and self._cooled("shake", t):
            event = ("shake", best)
        if max(devs) / noise < self.shake_k / 2:
            self.noise = max(self.NOISE_FLOOR,
                             noise + (mdev - noise) * _alpha(PARK_LIGHT_EVERY_S, self.NOISE_TAU_S))
        return event


# ── treści SMS alarmu na postoju (stałe szablony, tylko GSM-7) ────────────

PARK_REASON_TEXT = {"tilt": "przechyl (podnosnik albo holowanie)",
                    "shake": "wstrzas albo kolysanie",
                    "power": "zasilanie wrocilo bez telefonu wlasciciela"}
PARK_STATE_TEXT = {"off": "wylaczony", "disarmed": "rozbrojony", "arming": "uzbrajanie",
                   "armed": "uzbrojony", "alarm": "ALARM", "log_only": "uzbrojony (tylko log)"}
PARK_EVENT_TEXT = {"tilt": "przechyl", "shake": "wstrzas", "power": "zasilanie bez wlasciciela",
                   "low_battery": "niska bateria", "home": "dom, bez uzbrojenia",
                   "cabin": "ruch w kabinie"}


def _dm_hm(wall: float, localtime: Callable[[float], time.struct_time]) -> str:
    return time.strftime("%d.%m %H:%M", localtime(wall))


def fix_text(fix: Optional[dict]) -> str:
    """Link do mapy z wiekiem i dokładnością pomiaru (same liczby)."""
    if not fix:
        return "nieznana (brak GPS)"
    src = "siec" if fix.get("provider") == "network" else "GPS"
    parts = [f"{src} sprzed {_fmt_age(int(fix['age_s']))}" if fix.get("age_s") is not None
             else src]
    if fix.get("acc") is not None:
        parts.append(f"dokladnosc {int(fix['acc'])} m")
    return f"https://maps.google.com/?q={fix['lat']:.5f},{fix['lon']:.5f} ({', '.join(parts)})"


def park_alarm_text(label: str, reason: str, wall: float, fix: Optional[dict],
                    localtime: Callable[[float], time.struct_time] = time.localtime) -> str:
    return (f"{label}: ALARM {PARK_REASON_TEXT.get(reason, 'czujnik')} "
            f"{_dm_hm(wall, localtime)}. Pozycja: {fix_text(fix)}")


def park_position_text(label: str, fix: Optional[dict]) -> str:
    if not fix:
        return f"{label}: POZYCJA nieznana (brak GPS i sieci)"
    return f"{label}: POZYCJA {fix_text(fix)}"


def park_low_battery_text(label: str, pct: int) -> str:
    return (f"{label}: POSTOJ rozbrojony - bateria telefonu {int(pct)}%. Alarm wroci po "
            f"podlaczeniu zasilania.")


def park_ack_text(label: str, what: str, minutes: int = 0) -> str:
    if what == "arming":
        return (f"{label}: POSTOJ uzbrajanie za {int(minutes)} min." if minutes
                else f"{label}: POSTOJ uzbrojony.")
    return {"already": f"{label}: POSTOJ juz uzbrojony.",
            "off": f"{label}: POSTOJ rozbrojony.",
            "low_battery": f"{label}: POSTOJ nie uzbrojony - bateria telefonu za niska.",
            }.get(what, f"{label}: POSTOJ zly albo zuzyty kod.")


def park_status_text(label: str, view: dict,
                     localtime: Callable[[float], time.struct_time] = time.localtime) -> str:
    out = f"{label}: POSTOJ {PARK_STATE_TEXT.get(view.get('state'), 'nieznany')}"
    if view.get("since"):
        out += f" od {_dm_hm(view['since'], localtime)}"
    pct = (view.get("battery") or {}).get("pct")
    if isinstance(pct, int) and not isinstance(pct, bool):
        out += f", bateria {pct}%"
    ev = view.get("last_event")
    if isinstance(ev, dict) and ev.get("kind") in PARK_EVENT_TEXT and ev.get("ts"):
        out += f", ostatnie: {PARK_EVENT_TEXT[ev['kind']]} {_dm_hm(ev['ts'], localtime)}"
    if view.get("entry_until"):
        out += f", ruch - alarm o {_dm_hm(view['entry_until'], localtime)[-5:]} bez rozbrojenia"
    return out + "."


def normalize_park_numbers(raw: Any) -> Optional[list]:
    """Lista ≤ :data:`MAX_RECIPIENTS` numerów E.164 bez powtórzeń; None =
    zły kształt."""
    if not isinstance(raw, list) or len(raw) > MAX_RECIPIENTS:
        return None
    out: list[str] = []
    for n in raw:
        if not isinstance(n, str) or not E164_RE.fullmatch(n):
            return None
        if n not in out:
            out.append(n)
    return out


def _park_default_state() -> dict:
    return {"state": "disarmed", "since": None, "by": "", "arm_at": None, "armed_wall": None,
            "check_home": False, "await_plug": False, "power": None, "restored_wall": None,
            "last_event": None, "alarm_walls": [], "reply_walls": {}, "bad_codes": {},
            "totp_last": None, "pending": None}


def _walls(raw: Any) -> list:
    if not isinstance(raw, list):
        return []
    return [float(w) for w in raw[-32:] if _number(w, 0, EVENT_TS_MAX) is not None]


def normalize_park_state(obj: Any) -> dict:
    """``park.json`` → stan; każde uszkodzone pole = wartość domyślna (plik
    mógł zostać podmieniony), a stan bez potrzebnych znaczników czasu —
    rozbrojony."""
    st = _park_default_state()
    if not isinstance(obj, dict):
        return st
    if obj.get("state") in PARK_SAVED_STATES:
        st["state"] = obj["state"]
    if obj.get("by") in PARK_BY:
        st["by"] = obj["by"]
    for key in ("since", "arm_at", "armed_wall", "restored_wall"):
        if _number(obj.get(key), 0, EVENT_TS_MAX) is not None:
            st[key] = float(obj[key])
    for key in ("check_home", "await_plug"):
        if isinstance(obj.get(key), bool):
            st[key] = obj[key]
    if obj.get("power") in ("plugged", "unplugged"):
        st["power"] = obj["power"]
    ev = obj.get("last_event")
    if isinstance(ev, dict) and ev.get("kind") in PARK_EVENT_KINDS \
            and _number(ev.get("ts"), 0, EVENT_TS_MAX) is not None:
        val = _number(ev.get("value"), -1e6, 1e6)
        st["last_event"] = {"kind": ev["kind"], "ts": int(ev["ts"]),
                            "value": None if val is None else float(val),
                            "logged_only": ev.get("logged_only") is True}
    st["alarm_walls"] = _walls(obj.get("alarm_walls"))
    for key in ("reply_walls", "bad_codes"):
        m = obj.get(key)
        if isinstance(m, dict):
            st[key] = {k: _walls(v) for k, v in list(m.items())[:8]
                       if isinstance(k, str) and (k == "bcm" or E164_RE.fullmatch(k))}
    last = obj.get("totp_last")
    if _number(last, 0, 10 ** 12, integer=True) is not None:
        st["totp_last"] = int(last)
    pend = obj.get("pending")
    if isinstance(pend, dict) and pend.get("kind") in PARK_ENTRY_KINDS \
            and _number(pend.get("wall"), 0, EVENT_TS_MAX) is not None \
            and _number(pend.get("deadline"), 0, EVENT_TS_MAX) is not None:
        val = _number(pend.get("value"), -1e6, 1e6)
        st["pending"] = {"kind": pend["kind"], "value": None if val is None else float(val),
                         "wall": float(pend["wall"]), "deadline": float(pend["deadline"])}
    if st["state"] == "arming" and st["arm_at"] is None:
        st["state"] = "disarmed"
    if st["state"] in ("armed", "alarm") and st["armed_wall"] is None:
        if st["since"] is None:
            st["state"] = "disarmed"
        else:
            st["armed_wall"] = st["since"]
    if st["state"] != "armed":
        # Czekający alarm istnieje tylko przy uzbrojonym (przy „alarm”
        # kolejne wyzwolenia idą od razu).
        st["pending"] = None
    return st


# ── czuwanie kabiny (plan I): czyste funkcje ─────────────────────────────

class LightDetector:
    """Skok światła (lampka sufitowa po otwarciu drzwi): odczyt co najmniej
    ``ratio`` (domyślnie :data:`LIGHT_RATIO`) razy jaśniejszy I o ``delta``
    (:data:`LIGHT_DELTA_LUX`) lux jaśniejszy niż najciemniejsza próbka
    z ostatnich :data:`LIGHT_WINDOW_S` s.
    Chmura, zmierzch, latarnia, która się rozgrzewa — zmieniają światło
    wolniej, więc w oknie 2 s nie przechodzą. Spadek światła (lampka gaśnie)
    nie jest sygnałem. Po wykryciu :data:`LIGHT_COOLDOWN_S` przerwy (jedna
    lampka = jeden sygnał). Czysta logika, czas podaje wywołujący.

    ``mute(until)``: do tej chwili próbki tylko trafiają do historii (bez
    sygnału) — na czas zdjęć ekran telefonu świeci w czujnik światła."""

    def __init__(self, ratio: float = LIGHT_RATIO, delta: float = LIGHT_DELTA_LUX) -> None:
        self._hist: deque = deque(maxlen=256)
        self._cool_until = -math.inf
        self._mute_until = -math.inf
        self.ratio = float(ratio)
        self.delta = float(delta)

    def set_thresholds(self, ratio: float, delta: float) -> None:
        """Progi z konfiguracji (``cabin_light_ratio``, ``cabin_light_lux``,
        już sprawdzone przez :func:`normalize_cabin_config`)."""
        self.ratio = float(ratio)
        self.delta = float(delta)

    def reset(self) -> None:
        self._hist.clear()
        self._cool_until = -math.inf

    def mute(self, until: float) -> None:
        self._mute_until = float(until)

    def feed(self, t: float, lux: Any) -> Optional[tuple[str, float]]:
        """Jedna próbka → ``("light", lux)`` albo None."""
        value = _number(lux, 0.0, LIGHT_MAX_LUX)
        if value is None or not math.isfinite(t):
            return None
        value = float(value)
        while self._hist and (t - self._hist[0][0] > LIGHT_WINDOW_S or self._hist[0][0] > t):
            self._hist.popleft()
        low = min((v for _t, v in self._hist), default=None)
        self._hist.append((t, value))
        if low is None or t < self._mute_until or t < self._cool_until:
            return None
        if value >= self.ratio * low and value - low >= self.delta:
            self._cool_until = t + LIGHT_COOLDOWN_S
            return ("light", round(value, 1))
        return None


class CabinCombiner:
    """Reguła zdarzenia kabiny z sygnałów T0: przechył albo drzwi (silne)
    od razu; światło I ruch w ciągu :data:`CABIN_PAIR_S`; albo
    :data:`CABIN_WEAK_N` słabych sygnałów w :data:`CABIN_WEAK_WINDOW_S`,
    przy czym wszystkie skoki światła z okna liczą się jak JEDEN (3 ruchy
    albo światło + 2 ruchy). Pojedynczy wstrząs (ciężarówka, wiatr) albo same
    światła — przejeżdżające auta, awaryjne auta obok, koguty, błyskawice,
    choćby co 10 s — to za mało: bez ruchu auta zdjęć nie ma. Czas = chwila
    WYKRYCIA (zegar od startu telefonu), nie chwila obsługi kolejki."""

    def __init__(self) -> None:
        self._sig: deque = deque(maxlen=64)

    def reset(self) -> None:
        self._sig.clear()

    def feed(self, kind: str, t: float) -> Optional[tuple[list, bool]]:
        """Sygnał → ``(rodzaje z okna 60 s w kolejności CABIN_SIGNALS,
        słabe)`` dla zdarzenia albo None."""
        if kind not in CABIN_SIGNALS or kind == "power":
            return None
        self._sig = deque(((tt, k) for tt, k in self._sig
                           if abs(t - tt) <= CABIN_WEAK_WINDOW_S), maxlen=64)
        other = {"light": "shake", "shake": "light"}.get(kind)
        pair = other is not None and any(k == other and abs(t - tt) <= CABIN_PAIR_S
                                         for tt, k in self._sig)
        self._sig.append((t, kind))
        # Światła zostają w oknie (trafią do powodów późniejszego zdarzenia),
        # ale do progu słabych sygnałów liczą się najwyżej raz.
        shakes = sum(1 for _tt, k in self._sig if k == "shake")
        weak_n = shakes + (1 if any(k == "light" for _tt, k in self._sig) else 0)
        if kind in CABIN_STRONG or pair or weak_n >= CABIN_WEAK_N:
            seen = {k for _tt, k in self._sig}
            kinds = [k for k in CABIN_SIGNALS if k in seen]
            self._sig.clear()
            return kinds, not (kind in CABIN_STRONG or pair)
        return None


def light_class(lux: Optional[float]) -> Optional[str]:
    """Klasa światła (odniesienie analizy tylko z tej samej): ``dark`` /
    ``dim`` / ``bright``; None bez odczytu."""
    if lux is None or not isinstance(lux, (int, float)) or isinstance(lux, bool) \
            or not math.isfinite(lux) or lux < 0:
        return None
    for name, upper in LIGHT_CLASSES:
        if lux < upper:
            return name
    return None


def parse_camera_info(text: Any) -> Optional[str]:
    """Wyjście ``termux-camera-info`` (lista ``{"id": "1", "facing":
    "front", …}``) → id przedniej kamery jako ciąg 1–2 cyfr albo None.
    Id trafia jako argument do ``termux-camera-photo -c``, więc tylko cyfry
    (``"1; rm"`` albo ``"../x"`` — odrzucone)."""
    if not isinstance(text, str) or not text.strip() or len(text) > 262144:
        return None
    try:
        obj = json.loads(text, parse_constant=_reject_constant)
    except (ValueError, RecursionError):
        return None
    if not isinstance(obj, list):
        return None
    for item in obj[:16]:
        if not isinstance(item, dict) or not isinstance(item.get("facing"), str) \
                or item["facing"].strip().lower() != "front":
            continue
        cid = item.get("id")
        if isinstance(cid, int) and not isinstance(cid, bool) and 0 <= cid <= 99:
            return str(cid)
        if isinstance(cid, str) and CAMERA_ID_RE.fullmatch(cid):
            return cid
    return None


def valid_photo_path(path: Any) -> bool:
    """Ścieżka zdjęcia dla ``termux-camera-photo``: bezwzględna, tylko
    :data:`CABIN_PATH_RE`, bez ``..`` i pustych członów — skrypt przekazuje
    ją dalej bez cudzysłowu."""
    return isinstance(path, str) and bool(CABIN_PATH_RE.fullmatch(path)) \
        and all(part not in ("", ".", "..") for part in path.split("/")[1:])


def cabin_reason_text(reasons: Any, weak: bool) -> str:
    """``["light", "shake"]`` → ``swiatlo+ruch`` (GSM-7); ``weak`` dopisuje,
    że zdarzenie dały 3 słabe sygnały."""
    words = [CABIN_SIGNAL_TEXT[k] for k in CABIN_SIGNALS
             if isinstance(reasons, list) and k in reasons] or ["czujnik"]
    return "+".join(words) + (", 3 slabe sygnaly" if weak else "")


def cabin_inside(reasons: Any) -> bool:
    """Czy zdarzenie ma sygnał, który daje TYLKO kabina (lampka, drzwi).
    Sam przechył i ruch przychodzą z detektora alarmu na postoju i nie
    odróżniają człowieka w środku od podnośnika czy lawety."""
    return isinstance(reasons, list) and ("light" in reasons or "door" in reasons)


def cabin_alarm_text(label: str, reasons: Any, weak: bool, wall: float, photos: int,
                     fix: Optional[dict],
                     localtime: Callable[[float], time.struct_time] = time.localtime) -> str:
    """SMS alarmu kabiny (plan I, T3) — stałe słowa, liczby i link.

    Nagłówek według sygnałów: ze światłem albo drzwiami — ``RUCH W
    KABINIE (…)``; bez nich (sam przechył / ruch, ewentualnie zasilanie)
    — treść alarmu na postoju dla najważniejszego powodu (przechył, potem
    wstrząs, potem zasilanie), np. ``ALARM przechyl (podnosnik albo
    holowanie)``: właściciel, którego auto jest właśnie holowane, nie może
    przeczytać, że ktoś siedzi w środku. Liczba zdjęć — zawsze."""
    when = _dm_hm(wall, localtime)
    if not cabin_inside(reasons):
        main = next((k for k in ("tilt", "shake", "power")
                     if isinstance(reasons, list) and k in reasons), "shake")
        return (f"{label}: ALARM {PARK_REASON_TEXT[main]} {when}. Zdjecia: {int(photos)}. "
                f"Pozycja: {fix_text(fix)}")
    return (f"{label}: RUCH W KABINIE {when} "
            f"({cabin_reason_text(reasons, weak)}). Zdjecia: {int(photos)}. "
            f"Pozycja: {fix_text(fix)}")


def strip_jpeg_metadata(data: Any) -> Optional[bytes]:
    """JPEG bez segmentów APP1–APP15 (EXIF, XMP, miniatura z EXIF, dane
    producenta) i COM — sama biblioteka standardowa, bez przekodowania
    (obraz bit w bit ten sam). APP0 (JFIF) zostaje. None = to nie jest
    poprawny JPEG (wtedy wołający zostawia plik bez zmian i to loguje).
    Ostrożnie: każda długość segmentu sprawdzona, nic poza buforem."""
    if not isinstance(data, (bytes, bytearray)) or len(data) < 4 or data[:2] != b"\xff\xd8":
        return None
    out = bytearray(b"\xff\xd8")
    i, n = 2, len(data)
    while i < n:
        if data[i] != 0xFF:
            return None
        while i < n and data[i] == 0xFF:          # bajty wypełnienia
            i += 1
        if i >= n:
            return None
        marker = data[i]
        i += 1
        if marker == 0xD9:                        # EOI bez SOS — ale poprawny koniec
            out += b"\xff\xd9"
            return bytes(out)
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:
            out += bytes((0xFF, marker))
            continue
        if i + 2 > n:
            return None
        length = (data[i] << 8) | data[i + 1]
        if length < 2 or i + length > n:
            return None
        segment = bytes(data[i:i + length])
        i += length
        if marker == 0xDA:                        # SOS: dalej dane obrazu
            out += bytes((0xFF, marker)) + segment + bytes(data[i:])
            return bytes(out)
        if 0xE1 <= marker <= 0xEF or marker == 0xFE:
            continue                              # metadane — pomijam
        out += bytes((0xFF, marker)) + segment
    return None


def load_pillow() -> Any:
    """Pillow (``pkg install python-pillow``) albo None — opcjonalny:
    agent bez niego działa, tylko analiza zdjęć jest pomijana, a EXIF
    usuwa :func:`strip_jpeg_metadata`."""
    try:
        from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps, ImageStat
    except Exception:
        return None

    class _Pil:
        pass

    pil = _Pil()
    pil.Image, pil.ImageChops, pil.ImageDraw = Image, ImageChops, ImageDraw
    pil.ImageFilter, pil.ImageOps, pil.ImageStat = ImageFilter, ImageOps, ImageStat
    return pil


def pil_reencode(pil: Any, src: str, dst: str) -> None:
    """Przekodowanie zdjęcia (≤ :data:`CABIN_REENCODE_SIDE` px, JPEG
    jakość :data:`CABIN_JPEG_QUALITY`) do NOWEGO obrazu bez żadnych metadanych
    (EXIF, ICC, komentarz) — obrót z EXIF przeniesiony na piksele."""
    with pil.Image.open(src) as im:
        im.draft("RGB", (CABIN_REENCODE_SIDE, CABIN_REENCODE_SIDE))
        im = pil.ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((CABIN_REENCODE_SIDE, CABIN_REENCODE_SIDE))
        clean = pil.Image.new("RGB", im.size)
        clean.paste(im)
    clean.save(dst, "JPEG", quality=CABIN_JPEG_QUALITY)


def pil_prepare(pil: Any, path: str) -> Any:
    """Klatka do analizy: odcienie szarości, :data:`CABIN_FRAME`, rozmycie
    (szum matrycy i drobne drgania nie liczą się jako zmiana)."""
    with pil.Image.open(path) as im:
        im.draft("L", (CABIN_FRAME[0] * 2, CABIN_FRAME[1] * 2))
        frame = im.convert("L").resize(CABIN_FRAME)
    return frame.filter(pil.ImageFilter.GaussianBlur(CABIN_BLUR))


def pil_mean(pil: Any, frame: Any) -> float:
    return float(pil.ImageStat.Stat(frame).mean[0])


def pil_change_pct(pil: Any, ref: Any, frame: Any, mask: Any) -> float:
    """Ile % pikseli poza maską okien (prostokąty w % kadru) różni się
    o więcej niż :data:`CABIN_PIXEL_DELTA` po wyrównaniu średniej jasności
    (automatyka ekspozycji nie udaje zmiany)."""
    w, h = CABIN_FRAME
    if ref.size != (w, h):
        ref = ref.convert("L").resize((w, h))
    m_ref, m_frame = pil_mean(pil, ref), pil_mean(pil, frame)
    if m_frame > 1.0:
        k = m_ref / m_frame
        frame = frame.point([min(255, int(round(v * k))) for v in range(256)])
    diff = pil.ImageChops.difference(ref, frame).point(
        [255 if v > CABIN_PIXEL_DELTA else 0 for v in range(256)])
    keep = pil.Image.new("L", (w, h), 255)
    draw = pil.ImageDraw.Draw(keep)
    for x0, y0, x1, y1 in mask or []:
        draw.rectangle([x0 * w // 100, y0 * h // 100, max(0, x1 * w // 100 - 1),
                        max(0, y1 * h // 100 - 1)], fill=0)
    total = keep.histogram()[255]
    if total <= 0:
        return 0.0
    changed = pil.ImageChops.multiply(diff, keep).histogram()[255]
    return 100.0 * changed / total


def normalize_cabin_mask(raw: Any) -> Optional[list]:
    """≤ :data:`CABIN_MASK_MAX` prostokątów ``[x0, y0, x1, y1]`` (liczby
    całkowite 0–100, x0 < x1, y0 < y1); None = zły kształt."""
    if not isinstance(raw, list) or len(raw) > CABIN_MASK_MAX:
        return None
    out = []
    for rect in raw:
        if not isinstance(rect, list) or len(rect) != 4:
            return None
        vals = [_number(v, 0, 100, integer=True) for v in rect]
        if any(v is None for v in vals):
            return None
        x0, y0, x1, y1 = (int(v) for v in vals)
        if x0 >= x1 or y0 >= y1:
            return None
        out.append([x0, y0, x1, y1])
    return out


def normalize_cabin_config(obj: dict, base: dict) -> tuple[Optional[dict], str]:
    """Pola ``cabin_*`` — opcjonalne (BCM wysyła je tylko z włączonym
    ``modules.cabin_watch``), ale podane muszą być poprawne. Postać
    kanoniczna jak w BCM (skrót): liczba całkowita, ułamek do 0,01, maska
    jako lista list liczb całkowitych."""
    out: dict[str, Any] = {}
    lo, hi = CABIN_ENTRY_RANGE
    entry = _number(obj.get("cabin_entry_s", base["cabin_entry_s"]), lo, hi, integer=True)
    if entry is None:
        return None, f"cabin_entry_s: integer {lo}..{hi}"
    out["cabin_entry_s"] = int(entry)
    flo, fhi = CABIN_DIFF_RANGE
    diff = _number(obj.get("cabin_diff_pct", base["cabin_diff_pct"]), flo, fhi)
    if diff is None:
        return None, f"cabin_diff_pct: number {flo}..{fhi}"
    out["cabin_diff_pct"] = round(float(diff), 2)
    mask = normalize_cabin_mask(obj.get("cabin_mask", base["cabin_mask"]))
    if mask is None:
        return None, (f"cabin_mask: at most {CABIN_MASK_MAX} rectangles [x0, y0, x1, y1] "
                      f"in % (0..100, x0 < x1, y0 < y1)")
    out["cabin_mask"] = mask
    for key, (flo, fhi) in (("cabin_light_ratio", CABIN_LIGHT_RATIO_RANGE),
                            ("cabin_light_lux", CABIN_LIGHT_LUX_RANGE)):
        val = _number(obj.get(key, base[key]), flo, fhi)
        if val is None:
            return None, f"{key}: number {flo}..{fhi}"
        out[key] = round(float(val), 2)
    return out, ""


def _cabin_analysis(raw: Any) -> Optional[dict]:
    if not isinstance(raw, dict) or raw.get("verdict") not in CABIN_VERDICTS:
        return None
    pct = _number(raw.get("changed_pct"), 0.0, 100.0)
    return {"verdict": raw["verdict"], "changed_pct": None if pct is None else round(float(pct), 1),
            "ref": raw.get("ref") if raw.get("ref") in CABIN_REF_MODES else None}


def normalize_cabin_state(obj: Any) -> dict:
    """``cabin.json`` → ``{"events": [...]}``; uszkodzony wpis (plik mógł
    zostać podmieniony) jest pomijany, nazwy zdjęć tylko według wzorca
    tego zdarzenia (nic spoza katalogu zdjęć nigdy nie zostanie usunięte)."""
    out: dict[str, Any] = {"events": []}
    events = obj.get("events") if isinstance(obj, dict) else None
    for ev in events[-CABIN_MAX_EVENTS:] if isinstance(events, list) else []:
        if not isinstance(ev, dict) or not isinstance(ev.get("id"), str) \
                or not _CABIN_ID_RE.fullmatch(ev["id"]) \
                or ev.get("outcome") not in CABIN_OUTCOMES \
                or _number(ev.get("wall"), 0, EVENT_TS_MAX) is None \
                or _number(ev.get("deadline"), 0, EVENT_TS_MAX) is None:
            continue
        reasons = ev.get("reasons")
        reasons = [k for k in CABIN_SIGNALS if isinstance(reasons, list) and k in reasons]
        photos = ev.get("photos")
        photos = [p for p in photos[:CABIN_PHOTOS] if isinstance(p, str)
                  and (m := _CABIN_PHOTO_RE.fullmatch(p)) and m.group(1) == ev["id"]] \
            if isinstance(photos, list) else []
        lux = _number(ev.get("lux"), 0.0, LIGHT_MAX_LUX)
        camera = ev.get("camera")
        out["events"].append({
            "id": ev["id"], "wall": float(ev["wall"]), "deadline": float(ev["deadline"]),
            "reasons": reasons, "weak": ev.get("weak") is True,
            "lux": None if lux is None else float(lux), "photos": photos,
            "clean": ev.get("clean") is True, "outcome": ev["outcome"],
            "log_only": ev.get("log_only") is True,
            "analysis": _cabin_analysis(ev.get("analysis")),
            "camera": camera if camera in CABIN_CAMERA else "",
        })
    return out


Spawner = Callable[[list], Any]


def default_spawn(argv: list) -> Any:
    """Długo żyjący proces (strumień ``termux-sensor``): lista argumentów,
    NIGDY powłoka; stdout jako tekst, linia po linii. Własna grupa procesów
    (``start_new_session``): :func:`stop_process` zatrzymuje skrypt RAZEM
    z pomocnikiem ``termux-api``, który pisze próbki."""
    if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
        raise ValueError("invalid command")
    return subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, text=True, errors="replace", bufsize=1,
                            shell=False, start_new_session=True)


# ── alarm na postoju (plan D4): stan i wątek ──────────────────────────────

class ParkGuard:
    """Alarm na postoju w agencie (opis w nagłówku pliku, „Alarm na
    postoju”).

    Stan ``self.st`` (zapisywany atomowo w ``park.json`` przy każdej zmianie)
    zmienia się WYŁĄCZNIE pod blokadą agenta (``agent._lock``); polecenia
    w telefonie (bateria, skrzynka SMS, pozycja, czujnik) idą poza nią,
    w wątku postoju (:meth:`step`). Strumień akcelerometru czyta osobny
    wątek (najwyżej jeden naraz), który tylko karmi :class:`MotionDetector`
    (własna blokada, nigdy razem z blokadą agenta w odwrotnej kolejności)
    i wrzuca wykrycia do ograniczonej kolejki."""

    def __init__(self, agent: "Agent", spawn: Spawner,
                 mktime: Callable[[time.struct_time], float], pillow: Any = "auto") -> None:
        self.a = agent
        self._spawn = spawn
        self._mktime = mktime
        self.wake = threading.Event()
        self.st = normalize_park_state(agent._load_json("park.json", {}))
        self._started = agent._clock()
        self._start_wall = agent._wall()
        self._power: Optional[str] = self.st["power"]
        self._pct: Optional[int] = None
        #: Temperatura baterii (°C) z ostatniego odczytu — strażnik aparatu.
        self._temp: Optional[float] = None
        self._battery_at: Optional[float] = None
        self._kick = False
        self._kick_at: Optional[float] = None
        self._contact_at: Optional[float] = None
        self._inbox_at: Optional[float] = None
        self._seen: deque = deque()
        self._seen_set: set = set()
        self._jobs: list = []
        self._fix: Optional[dict] = None
        self._fix_at: Optional[float] = None
        self._warned: set = set()
        self._local: tuple = (None, [])
        self._light = False
        # Ile razy samo uzbrojenie przesunięto, bo auto jechało.
        self._moving_n = 0
        # Wyłączony z BCM przy uzbrojonym (log raz na przejście).
        self._off_held = False
        # Po udanym WAKE z SMS-a, gdy BCM milczał: {num, until} — pierwsze
        # podpisane żądanie BCM przed ``until`` = odpowiedź „obudzony”.
        self._wake_confirm: Optional[dict] = None
        # Powód wstrzymania samego uzbrojenia po wypadku (log raz na powód).
        self._holdoff_logged: Optional[str] = None
        # Czujnik (wątek postoju; ``_det`` i ``_last_sample`` pod _det_lock).
        self._det_lock = threading.Lock()
        self._det = MotionDetector()
        #: Wykrycia ``(rodzaj, wartość, chwila wykrycia, do alarmu postoju,
        #: do czuwania kabiny)`` — ograniczona, pełna = wykrycie pominięte.
        self._det_q: queue.Queue = queue.Queue(maxsize=32)
        self._last_sample: Optional[float] = None
        self._sensor_name: Optional[str] = None
        #: Czujnik światła (czuwanie kabiny) z tej samej listy ``-l``;
        #: ``_sensor_listed`` = lista już przeczytana (None = brak czujnika).
        self._light_name: Optional[str] = None
        self._sensor_listed = False
        self._sensor_list_at: Optional[float] = None
        #: (akcelerometr, światło|None) działającego strumienia.
        self._stream_names: Optional[tuple] = None
        self._proc: Any = None
        self._reader: Optional[threading.Thread] = None
        # Pokolenie strumienia (pod _det_lock): wątek czytający starego
        # procesu, który jeszcze żyje, porzuca próbki i kończy się.
        self._gen = 0
        self._proc_started = 0.0
        self._backoff = SENSOR_BACKOFF_MIN_S
        self._sensor_next = 0.0
        self._light_next = 0.0
        self._cleanup_due = False
        self.sensor_state = "off"
        # Czuwanie kabiny (plan I): warstwa nad tym alarmem.
        self.cabin = CabinWatch(self, pillow)

    # ── pomocnicze ───────────────────────────────────────────────────────

    def _warn_once(self, key: str, msg: str, *args: Any) -> None:
        if key not in self._warned:
            self._warned.add(key)
            log.warning(msg, *args)

    def _save_locked(self) -> None:
        try:
            self.a._save_json("park.json", self.st)
        except OSError as e:
            log.error("Cannot save the parking guard state: %s", _clean(e))

    def _on(self) -> bool:
        """(pod blokadą) Alarm działa: przełącznik ``parking_guard`` z BCM
        włączony ALBO alarm uzbrojony / w alarmie. Wyłączenie z BCM przy
        uzbrojonym NIE jest dowodem właściciela (Ustawienia → Moduły ma
        każdy, kto siedzi przy ekranie auta — złodziej po zapłonie też):
        alarm pilnuje dalej (czujnik, terminy, SMS-y, polecenia SMS), aż
        rozbroi go dowód właściciela, niska bateria albo strefa „dom”;
        dopiero potem wyłączenie działa (``off_pending`` w widoku)."""
        return self._toggle_on() or self.st["state"] in ("armed", "alarm")

    def _toggle_on(self) -> bool:
        return bool(self.a.config["toggles"]["parking_guard"])

    def keep_settings_locked(self, new: dict) -> list:
        """Nowa konfiguracja z BCM (``PUT /v1/config``, pod blokadą, PRZED
        zapisem): przy uzbrojonym albo w alarmie, gdy BCM wyłączył
        ``parking_guard`` / ``cabin_watch``, ustawienia ``park_*`` /
        ``cabin_*`` zostają stare. BCM przy wyłączonym przełączniku nie
        wysyła tych pól, więc bez tego alarm, który ma pilnować do dowodu
        właściciela, wróciłby do domyślnego ``park_log_only`` (bez SMS-a)
        i bez numerów z BCM. Te pola nie liczą się wtedy do skrótu
        konfiguracji, więc BCM nie widzi różnicy. Zwraca, co zostało."""
        if self.st["state"] not in ("armed", "alarm"):
            return []
        old, kept = self.a.config, []
        for toggle, defaults in (("parking_guard", PARK_DEFAULTS),
                                 ("cabin_watch", CABIN_DEFAULTS)):
            if not new["toggles"].get(toggle):
                for k in defaults:
                    v = old[k]
                    new[k] = [list(r) if isinstance(r, list) else r for r in v] \
                        if isinstance(v, list) else v
                kept.append(toggle)
        return kept

    def call_live_locked(self) -> bool:
        """(pod blokadą) Trwa połączenie 112 z tego telefonu."""
        call = self.a.call
        return call is not None and call["state"] in CALL_ACTIVE and not call["final"]

    def crash_holdoff_locked(self, wall: float) -> Optional[str]:
        """(pod blokadą) Powód, dla którego alarm nie uzbraja się SAM
        (:data:`PARK_CRASH_HOLDOFF_S`), albo None: ``call112`` — trwa
        połączenie 112 albo prawdziwe 112 poszło z tego telefonu niedawno;
        ``crash`` — niedawny wypadek od BCM (nieodwołany, nie na próbę)."""
        if self.call_live_locked():
            return "call112"
        for e in self.a.events:
            if e["state"] != "cancelled" and not e["dry"] \
                    and 0 <= wall - float(e["created_wall"]) < PARK_CRASH_HOLDOFF_S:
                return "crash"
        last = self.a.meta.get("call112_real_wall")
        if isinstance(last, (int, float)) and not isinstance(last, bool) \
                and 0 <= wall - last < PARK_CRASH_HOLDOFF_S:
            return "call112"
        return None

    def crash_locked(self, why: str, wall: float) -> None:
        """(pod blokadą) Wypadek od BCM albo 112 z tego telefonu: alarm,
        który się uzbraja albo jest uzbrojony, rozbrojony BEZ alarmu. Po
        wypadku w aucie są kierowca, ratownicy, policja i laweta, nie
        złodziej: czekający alarm (okno wejścia — wejście tuż przed jazdą)
        i czekające zdarzenie kabiny (zdjęcia usunięte) są odwoływane.
        Alarmy już rozstrzygnięte PRZED wypadkiem (SMS w kolejce) zostają —
        dotyczą tego, co działo się wcześniej. Samo uzbrojenie wraca po
        :data:`PARK_CRASH_HOLDOFF_S` (bez ``await_plug``)."""
        st = self.st
        if st["state"] not in ("arming", "armed", "alarm"):
            return
        log.warning("PARK: %s — the parking guard is disarmed without an alarm (people at the "
                    "car now are the driver and the rescuers)", why)
        st["last_event"] = {"kind": "crash_holdoff", "ts": int(wall), "value": None,
                            "logged_only": False}
        self._disarm_locked("crash", wall)
        st["await_plug"] = False
        self._save_locked()

    def _wake_on(self) -> bool:
        """Budzenie IR (plan E) — przełącznik ``remote_session`` z BCM."""
        return bool(self.a.config["toggles"].get("remote_session"))

    def _local_numbers(self) -> list:
        """Numery ustawione w telefonie (``--park-numbers``), czytane
        ponownie tylko po zmianie pliku."""
        path = self.a._path(PARK_LOCAL_FILE)
        try:
            mtime = os.stat(path).st_mtime_ns
        except OSError:
            self._local = (None, [])
            return []
        if self._local[0] == mtime:
            return list(self._local[1])
        obj = self.a._load_json(PARK_LOCAL_FILE, {})
        nums = normalize_park_numbers(obj.get("numbers", []) if isinstance(obj, dict) else None)
        if nums is None:
            log.warning("%s: 'numbers' is not a list of at most %d E.164 numbers — ignored",
                        PARK_LOCAL_FILE, MAX_RECIPIENTS)
            nums = []
        self._local = (mtime, nums)
        return list(nums)

    def numbers_locked(self) -> list:
        """Biała lista: z BCM (``park_numbers``), a gdy BCM nie podał żadnego
        — ustawiona w telefonie."""
        nums = self.a.config["park_numbers"]
        return list(nums) if nums else self._local_numbers()

    def totp_key(self) -> Optional[bytes]:
        try:
            raw = read_small(self.a._path(TOTP_FILE), 256)
        except (OSError, ValueError):
            return None
        return parse_totp_secret(raw.decode("ascii", "replace")) if raw else None

    def _no_contact_locked(self) -> bool:
        base = self._contact_at if self._contact_at is not None else self._started
        return self.a._clock() - base >= 60.0 * self.a.config["park_arm_after_min"]

    # ── zdarzenia z zewnątrz ─────────────────────────────────────────────

    def note_contact(self) -> None:
        """Podpisane żądanie BCM (dowolne). Liczy się do „brak kontaktu
        z BCM”; przy uzbrojonym — szybkie sprawdzenie zasilania (BCM żyje,
        więc prąd mógł wrócić) zamiast czekać do :data:`PARK_BATTERY_ARMED_S`."""
        now = self.a._clock()
        with self.a._lock:
            self._contact_at = now
            self._wake_confirmed_locked(now)
            kick = self._on() and self.st["state"] in ("armed", "alarm") and (
                self._kick_at is None or now - self._kick_at >= PARK_CONTACT_KICK_S)
            if kick:
                self._kick = True
                self._kick_at = now
        if kick:
            self.wake.set()

    def _wake_confirmed_locked(self, now: float) -> None:
        """(pod blokadą, z :meth:`note_contact`) BCM odezwał się po udanym
        ``WAKE <kod>``: jedna odpowiedź „obudzony” do numeru, który budził.
        Raz na budzenie; bez 2-minutowej przerwy odpowiedzi (pierwsza
        odpowiedź „BUDZENIE wyslane” wyszła przed chwilą), ale w dziennym
        budżecie odpowiedzi na numer."""
        conf, self._wake_confirm = self._wake_confirm, None
        if conf is None:
            return
        if now > conf["until"]:
            log.info("WAKE: BCM answered %d min after the wake — no reply", WAKE_CONFIRM_S // 60)
            return
        wall = self.a._wall()
        walls = [w for w in self.st["reply_walls"].get(conf["num"], []) if abs(wall - w) < DAY_S]
        if len(walls) >= PARK_REPLY_MAX_PER_DAY:
            log.warning("WAKE: BCM is up — reply to %s skipped (%d per day)",
                        mask_number(conf["num"]), PARK_REPLY_MAX_PER_DAY)
            return
        walls.append(wall)
        self.st["reply_walls"][conf["num"]] = walls[-PARK_REPLY_MAX_PER_DAY:]
        log.warning("WAKE: BCM is up after the wake — telling %s", mask_number(conf["num"]))
        self._queue_sms_locked("park_reply",
                               wake_reply_text(self.a.config["vehicle_label"], "woke"),
                               [conf["num"]], wall)
        self._save_locked()

    def view(self) -> dict:
        with self.a._lock:
            return self._view_locked(self.a._wall())

    def _view_locked(self, wall: float) -> dict:
        cfg, st = self.a.config, self.st
        state = st["state"]
        if not self._on():
            state = "off"
        elif state == "armed" and cfg["park_log_only"]:
            state = "log_only"
        ev = st["last_event"]
        entries = [d for d in (self._entry_deadline_locked(), self.cabin.next_deadline_locked())
                   if d is not None]
        entry = min(entries) if entries else None
        return {
            "state": state,
            "since": None if st["since"] is None else int(st["since"]),
            "by": st["by"],
            "arm_at": int(st["arm_at"]) if st["state"] == "arming" and st["arm_at"] else None,
            "last_event": dict(ev) if isinstance(ev, dict) else None,
            "battery": {"pct": self._pct, "power": self._power},
            "log_only": bool(cfg["park_log_only"]),
            "light": self._light,
            "sensor": self.sensor_state,
            "totp_ready": self.totp_key() is not None,
            "numbers_n": len(self.numbers_locked()),
            "home_set": cfg["park_home"] is not None,
            "alarms_today": sum(1 for w in st["alarm_walls"] if abs(wall - w) < DAY_S),
            # Okno wejścia: wykryto ruch, alarm o tej godzinie bez dowodu
            # właściciela (None = nic nie czeka). Czekające zdarzenie kabiny
            # liczy się też: jego SMS (wcześniejszy) obejmuje alarm postoju.
            "entry_until": None if entry is None else int(entry),
            # Wyłączony z BCM przy uzbrojonym: działa do dowodu właściciela.
            "off_pending": self._on() and not self._toggle_on(),
        }

    def _entry_deadline_locked(self) -> Optional[float]:
        """Termin czekającego alarmu (okno wejścia) albo None. Prąd, który
        wrócił w tym oknie (właściciel zapalił silnik, BCM startuje),
        przesuwa termin do końca ``park_grace_min`` — tyle trwa start
        komputera, przekierowanie adb i połączenie telefonu właściciela."""
        pend = self.st["pending"]
        if pend is None:
            return None
        deadline = float(pend["deadline"])
        restored = self.st["restored_wall"]
        if restored is not None:
            deadline = max(deadline, restored + 60.0 * self.a.config["park_grace_min"])
        return deadline

    def http_arm(self, obj: dict) -> tuple[int, dict]:
        """``POST /v1/park/arm {"delay_min": 0..30}`` — BCM wie, że auto
        zgaszono (wersja docelowa z buforem). Bez ``delay_min`` — opóźnienie
        z konfiguracji. Strefa „dom” obowiązuje."""
        if set(obj) - {"delay_min"}:
            return 400, {"error": "bad_request", "detail": 'body: {"delay_min": 0..30}'}
        delay = obj.get("delay_min")
        if delay is not None and _number(delay, 0, 30, integer=True) is None:
            return 400, {"error": "bad_request", "detail": "delay_min: integer 0..30"}
        with self.a._lock:
            if not self._on():
                return 409, {"error": "parking_guard_off"}
            wall = self.a._wall()
            hold = self.crash_holdoff_locked(wall)
            if hold is not None:
                log.warning("PARK: arming from BCM refused — %s within %d h", hold,
                            PARK_CRASH_HOLDOFF_S // 3600)
                return 409, dict(self._view_locked(wall), error="crash_holdoff")
            res = self._arm_locked("bcm", self.a.config["park_arm_delay_min"]
                                   if delay is None else int(delay), True, wall)
            view = self._view_locked(wall)
        self.wake.set()
        if res == "low_battery":
            return 409, dict(view, error="low_battery")
        return 200, view

    def http_disarm(self, obj: dict) -> tuple[int, dict]:
        """``POST /v1/park/disarm`` — dowód właściciela. ``{}``: BCM widzi
        połączony telefon właściciela (BT/HFP/AA) — BCM wysyła to TYLKO
        wtedy. ``{"code": "<6 cyfr>"}``: kod TOTP wpisany na ekranie auta
        (sprawdzany tu, jak w SMS-ie ``PARK OFF``; ten sam limit złych
        kodów i ochrona przed powtórką)."""
        if set(obj) - {"code"}:
            return 400, {"error": "bad_request", "detail": 'body: {} or {"code": "<6 digits>"}'}
        code = obj.get("code")
        if "code" in obj and (not isinstance(code, str) or not _PARK_CODE_RE.fullmatch(code)):
            return 400, {"error": "bad_request", "detail": "code: 6 digits"}
        key = self.totp_key() if code is not None else None
        with self.a._lock:
            if not self._on():
                return 409, {"error": "parking_guard_off"}
            wall = self.a._wall()
            if code is not None:
                if self._locked_out_locked("bcm", wall):
                    return 429, {"error": "rate_limited", "retry_after": 600}
                if key is None:
                    return 409, {"error": "no_totp"}
                res, step = totp_verify(key, code, wall, self.st["totp_last"])
                if res != "ok":
                    self._bad_code_locked("bcm", wall)
                    self._save_locked()
                    log.warning("PARK: disarm code from the car screen refused (%s)",
                                "already used" if res == "replay" else "wrong")
                    return 403, {"error": "code_used" if res == "replay" else "bad_code"}
                self.st["totp_last"] = step
                # Zapis TERAZ: _disarm_locked przy już rozbrojonym nic nie
                # zapisuje, a użyty krok ma przetrwać restart (powtórka).
                self._save_locked()
            self._disarm_locked("owner_code" if code is not None else "owner_bt", wall)
            view = self._view_locked(wall)
        self.wake.set()
        return 200, view

    def http_event(self, obj: dict) -> tuple[int, dict]:
        """``POST /v1/park/event {"kind": "door"}`` — sygnał drzwi od BCM
        (wersja docelowa: Nano #2 budzi BCM otwarciem drzwi, plan E). To
        TYLKO sygnał dla czuwania kabiny: nigdy nie rozbraja (złodziej też
        otwiera drzwi) i nie zmienia stanu alarmu na postoju. Odpowiedź:
        widok kabiny + ``accepted`` (False = nie czuwa, np. nie uzbrojony)."""
        if set(obj) - {"kind"} or obj.get("kind") not in CABIN_EXT_SIGNALS:
            return 400, {"error": "bad_request", "detail": 'body: {"kind": "door"}'}
        with self.a._lock:
            if not self._on():
                return 409, {"error": "parking_guard_off"}
            if not self.cabin.enabled_locked():
                return 409, {"error": "cabin_watch_off"}
            wall, now = self.a._wall(), self.a._clock()
            accepted = self.cabin.active_locked()
            if accepted:
                log.warning("CABIN: %s signal from BCM", obj["kind"])
                self.cabin.signal_locked(obj["kind"], None, now, wall)
            view = self.cabin.view_locked(wall)
        self.wake.set()
        return 200, dict(view, accepted=accepted)

    # ── przejścia stanu (pod blokadą agenta) ──────────────────────────────

    def _arm_locked(self, by: str, delay_min: int, check_home: bool, wall: float) -> str:
        """``arming`` (z oknem wyjścia ``delay_min``) — ``already`` /
        ``low_battery`` bez zmiany."""
        st = self.st
        if st["state"] in ("armed", "alarm"):
            return "already"
        if self._pct is not None and self._pct < PARK_LOW_PCT:
            log.warning("PARK: not arming (%s) — phone battery %d%%", by, self._pct)
            return "low_battery"
        home = self.a.config["park_home"]
        st.update(state="arming", by=by, since=wall, arm_at=wall + 60.0 * delay_min,
                  check_home=bool(check_home and home is not None), restored_wall=None,
                  pending=None)
        self._moving_n = 0
        log.warning("PARK: arming (%s) — armed in %d min%s", by, delay_min,
                    " unless the phone is at home" if st["check_home"] else "")
        self._save_locked()
        self.wake.set()
        return "arming"

    def _arm_now_locked(self, wall: float) -> None:
        cfg, st = self.a.config, self.st
        st.update(state="armed", since=wall, armed_wall=wall, arm_at=None, check_home=False,
                  restored_wall=None, pending=None)
        with self._det_lock:
            self._det = MotionDetector(cfg["park_tilt_deg"], cfg["park_shake_k"])
        while True:
            try:
                self._det_q.get_nowait()
            except queue.Empty:
                break
        self._light_next = 0.0
        log.warning("PARK: ARMED (%s)%s", st["by"],
                    " — LOG ONLY, no SMS" if cfg["park_log_only"] else "")
        self._save_locked()
        self.cabin.armed_locked(wall)
        self.wake.set()

    def _disarm_locked(self, by: str, wall: float) -> None:
        """Rozbrojenie. Po nim samo uzbrojenie (brak prądu + brak BCM)
        czeka na NOWE odcięcie zasilania (``await_plug``, gdy teraz nie ma
        prądu) — „PARK OFF” z daleka nie może się zaraz cofnąć.

        Rozbrojenie przez właściciela (:data:`PARK_OWNER_BY`) kasuje
        czekający alarm (okno wejścia), zadania alarmu i SMS-y alarmowe,
        które jeszcze nie wyszły — właściciel, który wsiadł i rozbroił,
        nie dostaje SMS-a o własnym wejściu. Wypadek (``crash``) kasuje
        tylko czekający alarm (:meth:`crash_locked`). Inne rozbrojenie
        (niska bateria, wyłączenie z BCM przy nieuzbrojonym) NIE: czekający
        alarm wychodzi od razu, bo mógł to być złodziej, a telefon zaraz
        przestanie pilnować."""
        st = self.st
        # Najpierw kabina: jej czekające zdarzenie odwołuje dowód właściciela,
        # a inne rozbrojenie wysyła jego alarm (obejmuje też czekający alarm
        # postoju — jeden SMS na wejście).
        self.cabin.disarmed_locked(by, wall)
        if by in PARK_OWNER_BY:
            self._jobs = [j for j in self._jobs
                          if j["kind"] not in ("alarm", "cabin_alarm", "arm_check")]
            self._cancel_alarm_sms_locked()
        else:
            self._jobs = [j for j in self._jobs if j["kind"] != "arm_check"]
            pend = st["pending"]
            if pend is not None and st["state"] == "armed" and by != "crash" \
                    and not self.a.config["park_log_only"]:
                st["pending"] = None
                self._alarm_locked(pend["kind"], pend["value"], float(pend["wall"]), wall)
        st["pending"] = None
        if st["state"] == "disarmed":
            return
        st.update(state="disarmed", by=by, since=wall, arm_at=None, check_home=False,
                  restored_wall=None, await_plug=self._power == "unplugged")
        log.warning("PARK: disarmed (%s)", by)
        self._save_locked()
        self.wake.set()

    def _cancel_alarm_sms_locked(self) -> None:
        """SMS-y alarmowe, które czekają w kolejce wysyłki (na zasięg, na
        ponowienie): odbiorcy jeszcze nieobsłużeni → ``skipped``, a
        ``no_retry`` zatrzymuje też ten, dla którego właśnie trwa
        sprawdzanie zasięgu/skrzynek (:meth:`Agent._run_action`). Samego
        ``termux-sms-send`` w toku nie da się cofnąć."""
        changed = False
        for d in self.a.meta.get("park_sms") or []:
            if not isinstance(d, dict) or d.get("kind") != "park_alarm" or delivery_done(d):
                continue
            if not d.get("no_retry"):
                d["no_retry"] = True
                changed = True
            for r in d["rcpt"]:
                if r["st"] in ("queued", "wait", "retry"):
                    r["st"] = "skipped"
                    r["err"] = "disarmed"
                    changed = True
        if changed:
            log.warning("PARK: disarmed by the owner — alarm SMS not sent yet are cancelled")
            self.a._persist_quietly()
            self.a.wake.set()

    def _trigger_locked(self, kind: str, value: Optional[float], wall: float) -> None:
        """Wyzwolenie przy uzbrojonym: zdarzenie, a poza ``log_only`` —
        alarm. Przechył i wstrząs przy ``armed`` najpierw czekają
        ``park_entry_s`` (okno wejścia, stan ``pending``): właściciel, który
        otwiera drzwi i siada, wygląda dla czujnika tak samo jak złodziej,
        a jego dowód (telefon połączony z BCM) przychodzi dopiero po
        zapłonie, starcie komputera i połączeniu Bluetooth. Podnośnik
        i holowanie nie przywracają prądu, więc alarmują po tym oknie."""
        st, cfg = self.st, self.a.config
        if st["state"] not in ("armed", "alarm"):
            return
        log_only = bool(cfg["park_log_only"])
        st["last_event"] = {"kind": kind, "ts": int(wall),
                            "value": None if value is None else round(float(value), 2),
                            "logged_only": log_only}
        detail = "" if value is None else f" ({value:.2f})"
        if log_only:
            log.warning("PARK (log only, no SMS): %s%s", kind, detail)
            self._save_locked()
            return
        entry = int(cfg["park_entry_s"])
        if kind in PARK_ENTRY_KINDS and st["state"] == "armed" and entry > 0:
            # Kolejne wstrząsy w oknie nie przesuwają terminu (inaczej
            # złodziej, który ciągle kołysze autem, nigdy by go nie dobił).
            if st["pending"] is None:
                st["pending"] = {"kind": kind,
                                 "value": None if value is None else round(float(value), 2),
                                 "wall": wall, "deadline": wall + entry}
                log.warning("PARK: %s%s — alarm in %d s unless the owner disarms (entry "
                            "window)", kind, detail, entry)
                self.wake.set()
            self._save_locked()
            return
        self._alarm_locked(kind, value, wall, wall)

    def _alarm_locked(self, kind: str, value: Optional[float], event_wall: float,
                      wall: float) -> None:
        """Stan ``alarm`` i SMS (z pozycją) w ramach budżetu 1 na 10 min /
        6 na dobę; ``event_wall`` = kiedy czujnik to wykrył (godzina w SMS-ie,
        także po oknie wejścia)."""
        st = self.st
        if st["state"] != "alarm":
            st["state"] = "alarm"
            st["since"] = wall
        detail = "" if value is None else f" ({value:.2f})"
        log.critical("PARK ALARM: %s%s", kind, detail)
        if not self.numbers_locked():
            self._warn_once("no_numbers", "PARK: no numbers for the alarm SMS (park_numbers "
                                          "from BCM, or --park-numbers on the phone)")
            self._save_locked()
            return
        wait = self._alarm_wait_locked(wall)
        if wait is not None:
            log.warning("PARK: alarm SMS limit (1 per %d min, %d per day) — next possible in "
                        "%d s", PARK_ALARM_COOLDOWN_S // 60, PARK_ALARM_MAX_PER_DAY, wait)
            self._save_locked()
            return
        st["alarm_walls"].append(wall)
        if len(self._jobs) < PARK_MAX_JOBS:
            self._jobs.append({"kind": "alarm", "reason": kind, "wall": event_wall})
        self._save_locked()
        self.wake.set()

    def _alarm_wait_locked(self, wall: float) -> Optional[int]:
        walls = [w for w in self.st["alarm_walls"] if abs(wall - w) < DAY_S]
        self.st["alarm_walls"] = walls
        ages = sorted(abs(wall - w) for w in walls)
        if ages and ages[0] < PARK_ALARM_COOLDOWN_S:
            return _wait_s(PARK_ALARM_COOLDOWN_S - ages[0])
        if len(ages) >= PARK_ALARM_MAX_PER_DAY:
            return _wait_s(DAY_S - ages[PARK_ALARM_MAX_PER_DAY - 1])
        return None

    def _reply_ok_locked(self, num: str, wall: float) -> bool:
        """Budżet odpowiedzi: 1 na numer na 2 min, 10 na numer na dobę."""
        walls = [w for w in self.st["reply_walls"].get(num, []) if abs(wall - w) < DAY_S]
        ok = not (walls and abs(wall - walls[-1]) < PARK_REPLY_COOLDOWN_S) \
            and len(walls) < PARK_REPLY_MAX_PER_DAY
        if ok:
            walls.append(wall)
        self.st["reply_walls"][num] = walls[-PARK_REPLY_MAX_PER_DAY:]
        if not ok:
            log.warning("PARK: reply to %s skipped (limit 1 per %d min, %d per day)",
                        mask_number(num), PARK_REPLY_COOLDOWN_S // 60, PARK_REPLY_MAX_PER_DAY)
        return ok

    def _bad_code_locked(self, key: str, wall: float) -> None:
        walls = [w for w in self.st["bad_codes"].get(key, [])
                 if abs(wall - w) < PARK_BAD_CODE_WINDOW_S]
        walls.append(wall)
        self.st["bad_codes"][key] = walls[-PARK_BAD_CODE_MAX:]

    def _locked_out_locked(self, key: str, wall: float) -> bool:
        walls = [w for w in self.st["bad_codes"].get(key, [])
                 if abs(wall - w) < PARK_BAD_CODE_WINDOW_S]
        return len(walls) >= PARK_BAD_CODE_MAX

    def _queue_sms_locked(self, kind: str, text: str, numbers: list, wall: float) -> None:
        """SMS do kolejki wysyłki agenta (ta sama ścieżka co SMS o wypadku:
        czekanie na zasięg, kontrola skrzynek, ponowienia) — ZA wysyłkami
        wypadku, odwołania i „wybrano 112”, które mają pierwszeństwo."""
        nums = [n for n in numbers if isinstance(n, str) and E164_RE.fullmatch(n)]
        if not nums:
            return
        if not is_gsm7(text):
            log.error("PARK: %s text is not GSM-7 — not sent", kind)
            return
        lst = self.a.meta.setdefault("park_sms", [])
        lst.append(new_delivery(kind, text, nums[:MAX_RECIPIENTS], False,
                                self.a.config["sim_slot"], wall, self.a._clock()))
        self._prune_sms_locked(wall)
        self.a._persist_quietly()
        self.a.wake.set()
        log.warning("PARK: %s SMS queued for %d recipient(s)", kind, len(nums))

    def _prune_sms_locked(self, wall: float) -> None:
        lst = self.a.meta.get("park_sms")
        if not isinstance(lst, list):
            self.a.meta["park_sms"] = []
            return
        keep = [d for d in lst if not delivery_done(d)
                or abs(wall - float(d["created_wall"])) < PARK_KEEP_SMS_S]
        while len(keep) > PARK_MAX_SMS:
            victim = next((d for d in keep if delivery_done(d)), keep[0])
            keep.remove(victim)
        self.a.meta["park_sms"] = keep

    # ── wątek postoju ─────────────────────────────────────────────────────

    def step(self) -> float:
        """Jeden krok: bateria, wykrycia, terminy, skrzynka SMS, pozycja,
        czujnik. Zwraca, za ile sekund następny."""
        a = self.a
        with a._lock:
            on = self._on()
            wake = self._wake_on()
            if not on:
                self._disarm_locked("off", a._wall())
            held = on and not self._toggle_on()
            if held != self._off_held:
                self._off_held = held
                if held:
                    log.warning("PARK: switched off on BCM while armed — stays armed until the "
                                "owner disarms (owner's phone, code, PARK OFF)")
        if not on:
            self._sensor_off()
            self._drain_detections()
            # Budzenie IR działa też bez alarmu na postoju: skrzynka SMS
            # tylko dla ``WAKE <kod>`` (pozostałe polecenia są wtedy pomijane).
            if wake and self._inbox_due(a._clock()):
                self._poll_inbox()
            self._run_wake_jobs()
            return PARK_MAX_WAIT_S
        now = a._clock()
        if self._battery_due(now):
            self._poll_battery(now)
        self._handle_detections()
        self._timers()
        if self._inbox_due(a._clock()):
            self._poll_inbox()
        self._run_jobs()
        self._manage_sensor()
        return self._next_wait()

    def shutdown(self) -> None:
        self._sensor_off()

    def _battery_every_locked(self) -> float:
        """Co ile bateria: w oknie wejścia często (prąd wrócił = właściciel
        zapalił silnik?), przy uzbrojonym rzadko, poza nim co minutę."""
        if self.st["pending"] is not None or self.cabin.next_deadline_locked() is not None:
            return PARK_ENTRY_BATTERY_S
        return PARK_BATTERY_ARMED_S if self.st["state"] in ("armed", "alarm") \
            else PARK_BATTERY_IDLE_S

    def _battery_due(self, now: float) -> bool:
        with self.a._lock:
            kick, self._kick = self._kick, False
            every = self._battery_every_locked()
        return kick or self._battery_at is None or now - self._battery_at >= every

    def _poll_battery(self, now: float) -> None:
        a = self.a
        with a._lock:
            fresh = a._status_ts is not None and now - a._status_ts < 20.0
            cached = a._status.get("battery") if fresh else None
        battery = cached if cached is not None else a.phone.battery()
        with a._lock:
            self._on_battery_locked(battery, a._clock(), a._wall())

    def _on_battery_locked(self, battery: Optional[dict], now: float, wall: float) -> None:
        """Odczyt baterii: zasilanie zniknęło / wróciło, wersja lekka,
        rozbrojenie przy :data:`PARK_LOW_PCT`. Nieudany odczyt niczego nie
        zmienia."""
        self._battery_at = now
        if battery is None:
            return
        pct = battery.get("pct")
        if isinstance(pct, int) and not isinstance(pct, bool):
            self._pct = pct
        temp = battery.get("temp_c")
        self._temp = float(temp) if isinstance(temp, (int, float)) \
            and not isinstance(temp, bool) and math.isfinite(temp) else None
        power = power_of(battery)
        st = self.st
        changed = False
        prev = st["power"]
        if power is not None:
            self._power = power
            if power != prev:
                st["power"] = power
                changed = True
            if power == "plugged" and st["await_plug"]:
                st["await_plug"] = False
                changed = True
        state = st["state"]
        if state == "arming" and power == "plugged" and st["by"] == "power":
            # Prąd wrócił w oknie wyjścia: kierowca wrócił przed uzbrojeniem.
            self._disarm_locked("power_back", wall)
            return
        if state in ("armed", "alarm") and power is not None:
            if prev == "unplugged" and power == "plugged" and st["restored_wall"] is None:
                st["restored_wall"] = wall
                changed = True
                log.warning("PARK: power is back — %d min for the owner's phone (BCM) or "
                            "PARK OFF, otherwise an alarm", self.a.config["park_grace_min"])
            elif power == "unplugged" and st["restored_wall"] is not None:
                st["restored_wall"] = None
                changed = True
                log.info("PARK: power gone again before the grace ended — no alarm")
        if state in ("arming", "armed", "alarm") and self._pct is not None \
                and self._pct < PARK_LOW_PCT:
            self._low_battery_locked(wall)
            return
        if changed:
            self._save_locked()

    def _low_battery_locked(self, wall: float) -> None:
        """Poniżej :data:`PARK_LOW_PCT`: rozbrojenie i JEDEN SMS (poza
        ``log_only``) — telefon ma jeszcze wysłać SMS o wypadku po
        powrocie do auta, a rozładowany trzeba włączać ręcznie."""
        cfg = self.a.config
        pct = int(self._pct or 0)
        log_only = bool(cfg["park_log_only"])
        self.st["last_event"] = {"kind": "low_battery", "ts": int(wall), "value": float(pct),
                                 "logged_only": log_only}
        self._disarm_locked("low_battery", wall)
        log.warning("PARK: phone battery %d%% — disarmed%s", pct,
                    " (log only, no SMS)" if log_only else "")
        if not log_only:
            self._queue_sms_locked("park_info", park_low_battery_text(cfg["vehicle_label"], pct),
                                   self.numbers_locked(), wall)
        self._save_locked()

    def _drain_detections(self) -> list:
        out = []
        while True:
            try:
                out.append(self._det_q.get_nowait())
            except queue.Empty:
                return out

    def _handle_detections(self) -> None:
        """Wykrycia z kolejki ``(rodzaj, wartość, chwila wykrycia, do
        postoju, do kabiny)``: przechył i wstrząs z rytmem alarmu na postoju
        → alarm na postoju; przechył, ruch z rytmem kabiny i skok światła →
        czuwanie kabiny, które łączy sygnały po chwili WYKRYCIA."""
        events = self._drain_detections()
        if not events:
            return
        with self.a._lock:
            wall = self.a._wall()
            for kind, value, t, to_park, to_cabin in events:
                if to_park:
                    self._trigger_locked(kind, value, wall)
                if to_cabin:
                    self.cabin.signal_locked(kind, value, t, wall)

    @staticmethod
    def _motion_items(ev: Optional[tuple], cabin_shake: Optional[float], t: float) -> list:
        """Wynik :meth:`MotionDetector.feed` → wpisy kolejki wykryć. Przechył
        idzie do obu; wstrząs alarmu postoju — do kabiny tylko, gdy minął też
        jej rytm (:attr:`MotionDetector.cabin_shake`); ruch tylko w rytmie
        kabiny — osobny wpis wyłącznie dla kabiny."""
        out = []
        if ev is not None:
            out.append((ev[0], ev[1], t, True, ev[0] != "shake" or cabin_shake is not None))
        if cabin_shake is not None and (ev is None or ev[0] != "shake"):
            out.append(("shake", cabin_shake, t, False, True))
        return out

    def _timers(self) -> None:
        a = self.a
        with a._lock:
            wall, st, cfg = a._wall(), self.st, a.config
            now = a._clock()
            hold = None
            if st["state"] == "disarmed" and self._power == "unplugged" \
                    and not st["await_plug"] and self._no_contact_locked():
                hold = self.crash_holdoff_locked(wall)
            if hold is not None:
                # Bez await_plug: po końcu okna uzbrajam sam jak zwykle.
                if hold != self._holdoff_logged:
                    log.warning("PARK: no USB power and no BCM, but %s within %d h — not "
                                "arming by itself (the owner may be at the car)", hold,
                                PARK_CRASH_HOLDOFF_S // 3600)
                self._holdoff_logged = hold
            elif st["state"] == "disarmed" and self._power == "unplugged" \
                    and not st["await_plug"] and self._no_contact_locked():
                self._holdoff_logged = None
                log.warning("PARK: no USB power and no BCM for %d min — arming",
                            cfg["park_arm_after_min"])
                if self._arm_locked("power", cfg["park_arm_delay_min"], True, wall) \
                        == "low_battery":
                    st["await_plug"] = True
                    self._save_locked()
            if st["state"] == "arming" and st["arm_at"] is not None and wall >= st["arm_at"]:
                if st["check_home"] or st["by"] in ("power", "bcm"):
                    # Poza blokadą (_run_jobs): paczka próbek „czy auto
                    # jedzie” i/lub pozycja dla strefy „dom”.
                    if not any(j["kind"] == "arm_check" for j in self._jobs):
                        self._jobs.append({"kind": "arm_check", "wall": wall})
                else:
                    self._arm_now_locked(wall)
            # Kabina PRZED oknem wejścia postoju: jej SMS (zdjęcia, powody)
            # obejmuje czekający alarm postoju — jeden SMS na wejście.
            cabin_wait = self.cabin.timers_locked(now, wall)
            entry_wait = self._entry_timer_locked(now, wall) or cabin_wait
            if not entry_wait and st["state"] in ("armed", "alarm") \
                    and st["restored_wall"] is not None \
                    and wall - st["restored_wall"] >= 60.0 * cfg["park_grace_min"]:
                st["restored_wall"] = None
                self._trigger_locked("power", None, wall)
            armed = st["state"] in ("armed", "alarm")
            light = armed and (
                (st["armed_wall"] is not None and wall - st["armed_wall"] >= PARK_LIGHT_AFTER_S)
                or (self._pct is not None and self._pct < PARK_LIGHT_PCT))
            if light != self._light and armed:
                log.info("PARK: %s sensor mode", "light (1 s burst every %d s)"
                         % PARK_LIGHT_EVERY_S if light else "continuous")
            self._light = light
            self._prune_sms_locked(wall)
            # Limits of numbers no longer in use (or long expired) go away —
            # park.json never grows with every number ever configured.
            for key, keep_s in (("reply_walls", DAY_S), ("bad_codes", PARK_BAD_CODE_WINDOW_S)):
                st[key] = {k: v for k, v in st[key].items()
                           if any(abs(wall - w) < keep_s for w in v)}

    def _entry_timer_locked(self, now: float, wall: float) -> bool:
        """Termin okna wejścia. True = alarm jeszcze czeka na świeży odczyt
        baterii (wtedy alarm „zasilanie bez właściciela” też nie idzie
        w tym kroku — jeden alarm, nie dwa)."""
        st = self.st
        pend = st["pending"]
        if pend is None:
            return False
        if st["state"] != "armed":
            st["pending"] = None
            self._save_locked()
            return False
        deadline = self._entry_deadline_locked()
        if deadline is None or wall < deadline:
            return False
        if self._battery_at is None or now - self._battery_at > PARK_ENTRY_FRESH_S:
            # Najpierw świeży odczyt: prąd, który wrócił przed chwilą (zapłon),
            # przesuwa termin o park_grace_min.
            self._kick = True
            return True
        st["pending"] = None
        st["restored_wall"] = None          # ten alarm obejmuje też powrót prądu
        log.warning("PARK: entry window over without the owner's proof — alarm")
        self._alarm_locked(pend["kind"], pend["value"], float(pend["wall"]), wall)
        return True

    # ── polecenia SMS ─────────────────────────────────────────────────────

    def _inbox_due(self, now: float) -> bool:
        if self._inbox_at is not None and now - self._inbox_at < PARK_INBOX_EVERY_S:
            return False
        with self.a._lock:
            nums = self.numbers_locked()
        if not nums:
            self._inbox_at = now
            if self._wake_on():
                # Bez alarmu na postoju BCM nie przysyła park_numbers (są
                # tylko w jego konfiguracji alarmu) — WAKE nie zadziałałby
                # wtedy po cichu. Raz w logu, z poleceniem naprawy.
                self._warn_once("no_numbers_cmd",
                                "PARK: no numbers for SMS commands (WAKE) — park_numbers come "
                                "from BCM only with modules.parking_guard on; otherwise run: "
                                "python ~/bcm_agent/bcm_agent.py --park-numbers '+48...'")
            return False
        if self.totp_key() is None:
            self._inbox_at = now
            self._warn_once("no_totp", "PARK: no TOTP secret — SMS commands are off (run: "
                                       "python ~/bcm_agent/bcm_agent.py --park-setup)")
            return False
        return True

    def _poll_inbox(self) -> None:
        self._inbox_at = self.a._clock()
        items = self.a.phone.sms_inbox()
        if items is None:
            self._warn_once("inbox", "PARK: cannot read the SMS inbox (termux-sms-list; READ_SMS "
                                     "for Termux:API?) — SMS commands do not work")
            return
        parsed = []
        for item in items:
            p = self._inbox_item(item)
            if p is not None:
                parsed.append(p)
        for rwall, num, cmd, code in sorted(parsed, key=lambda p: p[0]):
            self._command(num, cmd, code, rwall)

    def _seen_add(self, key: Any) -> bool:
        """False, gdy już przeczytana (deduplikacja po ``_id``, a bez niego
        po numerze, czasie i treści)."""
        if key in self._seen_set:
            return False
        self._seen.append(key)
        self._seen_set.add(key)
        while len(self._seen) > PARK_SEEN_MAX:
            self._seen_set.discard(self._seen.popleft())
        return True

    def _inbox_item(self, item: dict) -> Optional[tuple]:
        """Jedna wiadomość → ``(czas, numer z listy, polecenie, kod)`` albo
        None (powtórka, stara, sprzed startu agenta, obcy nadawca — po cichu,
        nie polecenie)."""
        num, body, received = item.get("number"), item.get("body"), item.get("received")
        if item.get("type") not in (None, "inbox") or not isinstance(body, str):
            return None
        mid = item.get("_id")
        if isinstance(mid, int) and not isinstance(mid, bool):
            key: Any = ("id", mid)
        else:
            key = ("h", sha256_hex(f"{num}\n{received}\n{body}".encode("utf-8", "replace"))[:24])
        if not self._seen_add(key):
            return None
        rwall = parse_received(received, self._mktime)
        wall = self.a._wall()
        if rwall is None or rwall < self._start_wall - 2 or wall - rwall > PARK_SMS_MAX_AGE_S \
                or rwall - wall > 120:
            return None
        with self.a._lock:
            owner = match_sender(num, self.numbers_locked())
        if owner is None:
            return None
        cmd = parse_park_command(body)
        if cmd is None:
            log.info("PARK: an SMS from %s is not a command — ignored", mask_number(owner))
            return None
        with self.a._lock:
            allowed = self._wake_on() if cmd[0] == "wake" else self._on()
        if not allowed:
            # Kod NIE jest zużywany: polecenie wyłączonej funkcji to nie próba.
            log.info("PARK: SMS command %s from %s ignored — that function is off on the phone",
                     cmd[0], mask_number(owner))
            return None
        return rwall, owner, cmd[0], cmd[1]

    def _command(self, num: str, cmd: str, code: str, rwall: float) -> None:
        """Polecenie z numeru z listy: kod TOTP (zapisany jako użyty PRZED
        wykonaniem — nawet po restarcie agenta nie zadziała drugi raz), potem
        akcja i odpowiedź w ramach budżetu.

        Kod sprawdzam względem CZASU ODEBRANIA SMS-a (``rwall``), nie chwili
        przetwarzania: skrzynkę czytam co :data:`PARK_INBOX_EVERY_S`, a wątek
        postoju może być zajęty pozycją (GPS + sieć do ok. 110 s) — przy
        oknie ±1 krok (30 s) prawdziwy kod często byłby już „zły” i liczył
        się do blokady numeru. ``rwall`` to czas zapisany przez telefon przy
        odbiorze (nie przez nadawcę), już ograniczony w :meth:`_inbox_item`
        (nie sprzed startu agenta, nie starszy niż 10 min); nie później niż
        teraz. Ochrona przed powtórką (``totp_last``) obowiązuje jak zwykle."""
        key = self.totp_key()
        with self.a._lock:
            wall, st, cfg = self.a._wall(), self.st, self.a.config
            label = cfg["vehicle_label"]
            if self._locked_out_locked(num, wall):
                log.warning("PARK: SMS command from %s ignored — %d wrong codes within an hour",
                            mask_number(num), PARK_BAD_CODE_MAX)
                return
            res, step = totp_verify(key, code, min(float(rwall), wall), st["totp_last"]) \
                if key else ("bad", None)
            if res != "ok":
                self._bad_code_locked(num, wall)
                log.warning("PARK: SMS command from %s refused (%s code)", mask_number(num),
                            "already used" if res == "replay" else "wrong")
                if self._reply_ok_locked(num, wall):
                    self._queue_sms_locked("park_reply", park_ack_text(label, "bad"), [num],
                                           wall)
                self._save_locked()
                return
            st["totp_last"] = step
            self._save_locked()
            log.warning("PARK: SMS command %s from %s accepted", cmd, mask_number(num))
            reply: Optional[str] = None
            if cmd == "position":
                if self._reply_ok_locked(num, wall) and len(self._jobs) < PARK_MAX_JOBS:
                    self._jobs.append({"kind": "position", "num": num, "wall": wall})
                    self.wake.set()
                self._save_locked()
                return
            if cmd == "wake":
                # Nadanie IR poza blokadą (wątek postoju, _run_wake_jobs);
                # odpowiedź SMS dopiero z wynikiem.
                if len(self._jobs) < PARK_MAX_JOBS:
                    self._jobs.append({"kind": "wake", "num": num, "wall": wall})
                    self.wake.set()
                self._save_locked()
                return
            if cmd == "on":
                delay = cfg["park_arm_delay_min"]
                res = self._arm_locked("sms", delay, False, wall)
                reply = park_ack_text(label, res, delay)
            elif cmd == "off":
                self._disarm_locked("owner_sms", wall)
                reply = park_ack_text(label, "off")
            else:
                reply = park_status_text(label, self._view_locked(wall), self.a._localtime)
            if self._reply_ok_locked(num, wall):
                self._queue_sms_locked("park_reply", reply, [num], wall)
            self._save_locked()

    # ── zadania z pozycją (GPS na żądanie) ────────────────────────────────

    def _run_wake_jobs(self) -> None:
        """``WAKE <kod>`` (plan E): nadanie IR poza blokadą agenta
        (:func:`wake_ir` — przełącznik, limit, blokada pliku), potem
        odpowiedź SMS z wynikiem do numeru z LISTY, w budżecie odpowiedzi."""
        a = self.a
        with a._lock:
            jobs = [j for j in self._jobs if j["kind"] == "wake"]
            if not jobs:
                return
            self._jobs = [j for j in self._jobs if j["kind"] != "wake"]
            cfg = dict(a.config)
            label = cfg["vehicle_label"]
        for job in jobs:
            # Krótkie czekanie na blokadę: to wątek postoju (bateria,
            # skrzynka, czujnik) — trwające ``--wake`` = odpowiedź „busy”.
            result = wake_ir(a.dir, a.phone.ir_transmit, cfg, a._wall(), "sms",
                             lock_wait_s=WAKE_LOCK_WAIT_SMS_S)
            with a._lock:
                wall = a._wall()
                now = a._clock()
                if result == "sent" and (self._contact_at is None
                                         or now - self._contact_at >= WAKE_SILENT_S):
                    # BCM spał: jego pierwsze żądanie = „obudzony” (note_contact).
                    self._wake_confirm = {"num": job["num"], "until": now + WAKE_CONFIRM_S}
                if self._reply_ok_locked(job["num"], wall):
                    self._queue_sms_locked("park_reply", wake_reply_text(label, result),
                                           [job["num"]], wall)
                self._save_locked()

    def _run_jobs(self) -> None:
        """Zadania wymagające poleceń w telefonie — poza blokadą: budzenie IR,
        pozycja (POZYCJA, alarm, strefa „dom”) i paczka próbek przed samym
        uzbrojeniem („czy auto jedzie”)."""
        self._run_wake_jobs()
        a = self.a
        with a._lock:
            jobs = list(self._jobs)
            st = self.st
            check = any(j["kind"] == "arm_check" for j in jobs) and st["state"] == "arming"
            want_motion = check and st["by"] in ("power", "bcm")
            check_home = check and st["check_home"]
            may_postpone = self._moving_n < PARK_MOVING_MAX
        if not jobs:
            return
        moving = self._moving_now() if want_motion else None
        postpone = bool(moving) and may_postpone
        need_fix = any(j["kind"] in ("alarm", "cabin_alarm", "position") for j in jobs) \
            or (check_home and not postpone)
        fix = self._fix if self._fix_at is not None \
            and a._clock() - self._fix_at < PARK_FIX_REUSE_S else None
        if fix is None and need_fix:
            gps_failed = a.phone.gps_failed_at
            # GPS zawsze przy alarmie; dla poleceń i strefy „dom” nie po
            # świeżej porażce (garaż — patrz PARK_GPS_SKIP_S).
            try_gps = any(j["kind"] in ("alarm", "cabin_alarm") for j in jobs) \
                or gps_failed is None \
                or a._clock() - gps_failed >= PARK_GPS_SKIP_S
            fix = a.phone.location(try_gps=try_gps)
            if fix is not None:
                self._fix, self._fix_at = fix, a._clock()
            else:
                log.warning("PARK: no position (GPS, network and last known all failed)")
        with a._lock:
            wall, st, cfg = a._wall(), self.st, a.config
            label = cfg["vehicle_label"]
            for job in jobs:
                if not any(j is job for j in self._jobs):
                    continue        # rozbrojone w międzyczasie
                self._jobs = [j for j in self._jobs if j is not job]
                if job["kind"] == "alarm":
                    self._queue_sms_locked("park_alarm", park_alarm_text(
                        label, job["reason"], job["wall"], fix, a._localtime),
                        self.numbers_locked(), wall)
                elif job["kind"] == "cabin_alarm":
                    # Ten sam rodzaj wysyłki co alarm postoju: dowód
                    # właściciela kasuje go z kolejki (_cancel_alarm_sms_locked).
                    ev = self.cabin.find_locked(job["id"])
                    if ev is not None and ev["outcome"] == "alarm":
                        self._queue_sms_locked("park_alarm", cabin_alarm_text(
                            label, ev["reasons"], ev["weak"], ev["wall"], len(ev["photos"]),
                            fix, a._localtime), self.numbers_locked(), wall)
                elif job["kind"] == "position":
                    self._queue_sms_locked("park_reply", park_position_text(label, fix),
                                           [job["num"]], wall)
                elif job["kind"] == "arm_check" and st["state"] == "arming":
                    hold = self.crash_holdoff_locked(wall) \
                        if st["by"] in ("power", "bcm") else None
                    if hold is not None:
                        # Wypadek / 112 w oknie wyjścia: samo uzbrojenie i to od
                        # BCM odwołane (PARK ON <kod> od właściciela — nie).
                        self.crash_locked(hold, wall)
                    elif postpone and self._moving_n < PARK_MOVING_MAX:
                        self._moving_n += 1
                        st["arm_at"] = wall + PARK_MOVING_RETRY_S
                        log.warning("PARK: the car seems to be moving (%s) — arming postponed "
                                    "by %d s (%d/%d)", st["by"], PARK_MOVING_RETRY_S,
                                    self._moving_n, PARK_MOVING_MAX)
                        self._save_locked()
                    elif st["check_home"] and at_home(fix, cfg["park_home"]):
                        st["last_event"] = {"kind": "home", "ts": int(wall), "value": None,
                                            "logged_only": False}
                        self._disarm_locked("home", wall)
                        log.info("PARK: the phone is at home — not arming")
                    else:
                        if moving:
                            log.warning("PARK: still moving after %d checks — arming anyway",
                                        PARK_MOVING_MAX)
                        self._arm_now_locked(wall)

    def _moving_now(self) -> Optional[bool]:
        """Jedna paczka próbek (1 s): True = ruch jak w jeździe (rozrzut
        ponad :data:`PARK_MOVING_MS2`), False = stoi, None = nie wiadomo
        (brak czujnika, nieudana paczka) — wtedy uzbrajam jak zwykle."""
        name = self._sensor()
        if name is None:
            return None
        vecs = self._burst(name)
        spread = burst_spread(vecs)
        if spread is None:
            return None
        log.info("PARK: motion check before arming: %.3f m/s2", spread)
        return spread > PARK_MOVING_MS2

    # ── czujnik ───────────────────────────────────────────────────────────

    def _manage_sensor(self) -> None:
        with self.a._lock:
            armed = self.st["state"] in ("armed", "alarm")
            light = self._light
        now = self.a._clock()
        if not armed:
            self._sensor_off()
        elif light:
            if self._proc is not None:
                # Przejście na wersję lekką: strumień zatrzymany I czujnik
                # zwolniony — inaczej Termux:API dalej próbkuje 10 Hz, a
                # paczki ``-n`` nie dostają nic (oszczędzanie nie działa).
                self._stop_stream()
                self._release_sensor()
            self._light_burst(now)
        else:
            self._ensure_stream(now)

    def _sensor(self) -> Optional[str]:
        """Nazwa akcelerometru (``termux-sensor -l`` raz, ponowienie co
        :data:`SENSOR_LIST_RETRY_S`)."""
        if self._sensor_name is not None:
            return self._sensor_name
        now = self.a._clock()
        if self._sensor_list_at is not None and now - self._sensor_list_at < SENSOR_LIST_RETRY_S:
            return None
        self._sensor_list_at = now
        names = self.a.phone.sensor_names()
        name = pick_accelerometer(names)
        if names is not None:
            self._sensor_listed = True
            self._light_name = pick_light(names)
            if self._light_name is not None:
                log.info("PARK: light sensor '%s'", self._light_name)
        if name is None:
            log.error("PARK: no accelerometer in 'termux-sensor -l' — only the power trigger "
                      "works (retry in %d min)", SENSOR_LIST_RETRY_S // 60)
            return None
        self._sensor_name = name
        log.info("PARK: accelerometer '%s'", name)
        return name

    def _wanted_names(self) -> Optional[tuple]:
        """``(akcelerometr, światło|None)`` strumienia: światło tylko przy
        włączonym czuwaniu kabiny (inaczej ten sam strumień co w D4 —
        czujnik światła to dodatkowe mA)."""
        name = self._sensor()
        if name is None:
            return None
        with self.a._lock:
            cabin = self.cabin.enabled_locked()
        return name, (self._light_name if cabin else None)

    def _ensure_stream(self, now: float) -> None:
        proc = self._proc
        wanted = self._wanted_names() if proc is not None and self._sensor_name is not None \
            else None
        if wanted is not None and self._stream_names is not None and wanted != self._stream_names:
            # Czuwanie kabiny włączone/wyłączone w trakcie: nowy zestaw
            # czujników od razu (bez backoffu — to nie awaria).
            log.info("PARK: sensor stream restarted for %s",
                     "the cabin watch (light)" if wanted[1] else "the accelerometer only")
            self._stop_stream()
            self._release_sensor()
            self._sensor_next = 0.0
            proc = None
        if proc is not None:
            with self._det_lock:
                last = self._last_sample
            alive = proc.poll() is None
            stalled = alive and now - (last if last is not None else self._proc_started) \
                > SENSOR_STALL_S
            if alive and not stalled:
                if last is not None and now - self._proc_started >= SENSOR_GOOD_RUN_S:
                    self._backoff = SENSOR_BACKOFF_MIN_S
                self.sensor_state = "ok" if last is not None else "starting"
                return
            log.warning("PARK: accelerometer stream %s — restart in %.0f s",
                        "stalled" if stalled else "ended", self._backoff)
            self._stop_stream()
            # Przed następnym strumieniem: bez ``-c`` nowy dostałby zero próbek.
            self._release_sensor()
            self._sensor_next = now + self._backoff
            self._backoff = min(self._backoff * 2, SENSOR_BACKOFF_MAX_S)
            self.sensor_state = "error"
            return
        if now < self._sensor_next:
            return
        names = self._wanted_names()
        if names is None:
            self.sensor_state = "no_sensor"
            return
        name, light = names
        # Jeden argument ``-s`` z listą rozdzieloną przecinkiem (obie nazwy
        # sprawdzone SENSOR_NAME_RE — bez przecinka); lista argumentów, nie
        # powłoka.
        sensors = name if light is None else f"{name},{light}"
        try:
            proc = self._spawn(["termux-sensor", "-s", sensors, "-d", str(SENSOR_DELAY_MS)])
        except (OSError, ValueError) as e:
            log.error("PARK: cannot start termux-sensor (%s) — retry in %.0f s", _clean(e),
                      self._backoff)
            self._sensor_next = now + self._backoff
            self._backoff = min(self._backoff * 2, SENSOR_BACKOFF_MAX_S)
            self.sensor_state = "error"
            return
        self._proc = proc
        self._stream_names = names
        self._proc_started = now
        self._cleanup_due = True
        with self._det_lock:
            self._last_sample = None
            self._det.gap()
            gen = self._gen
        self._reader = threading.Thread(target=self._read, args=(proc, name, gen, light),
                                        daemon=True, name="park-sensor")
        self._reader.start()
        self.sensor_state = "starting"

    def _read(self, proc: Any, name: str, gen: int, light: Optional[str] = None) -> None:
        """Wątek czytający strumień: parser → detektor ruchu (i detektor
        światła czuwania kabiny) → kolejka wykryć (patrz :attr:`_det_q`).
        Kończy się sam na EOF (koniec procesu) albo przy pierwszej próbce po
        zatrzymaniu strumienia (inne pokolenie — patrz
        :meth:`_stop_stream`)."""
        parser = SensorParser(name, light)
        stdout = getattr(proc, "stdout", None)
        if stdout is None:
            return
        cabin = self.cabin
        try:
            for line in stdout:
                items = parser.feed_items(line)
                if not items:
                    continue
                t = self.a._clock()
                for kind, value in items:
                    with self._det_lock:
                        if gen != self._gen:
                            return          # zatrzymany: nic już nie karmię
                        if kind == "a":
                            self._last_sample = t
                            ev = self._det.feed(t, *value)
                            found = self._motion_items(ev, self._det.cabin_shake, t)
                        else:
                            cabin.lux, cabin.lux_at = value, t
                            ev = cabin.light.feed(t, value)
                            found = [] if ev is None else [(ev[0], ev[1], t, False, True)]
                    for item in found:
                        try:
                            self._det_q.put_nowait(item)
                        except queue.Full:
                            pass
                    if found:
                        self.wake.set()
        except (OSError, ValueError):
            pass

    def _stop_stream(self) -> None:
        """Zatrzymanie strumienia: najpierw nowe pokolenie (stary wątek
        czytający już nic nie wrzuci do detektora), potem SIGTERM/SIGKILL do
        CAŁEJ grupy procesów (:func:`stop_process` — skrypt
        ``termux-sensor`` i jego pomocnik ``termux-api``; zamknięty pomocnik
        = EOF dla wątku czytającego). Zwolnienie czujnika (``-c``) — osobno,
        :meth:`_release_sensor`, po KAŻDYM zatrzymaniu."""
        proc, self._proc = self._proc, None
        self._stream_names = None
        if proc is None:
            return
        with self._det_lock:
            self._gen += 1
        stop_process(proc)
        reader, self._reader = self._reader, None
        if reader is not None:
            reader.join(timeout=SENSOR_JOIN_S)
            if reader.is_alive():
                # Rura wciąż otwarta (coś spoza grupy ją trzyma): wątek jest
                # już bez znaczenia (inne pokolenie) i skończy się przy
                # pierwszej próbce albo na EOF. Zamykanie stdout tutaj
                # mogłoby zablokować wątek postoju na czytającym.
                log.warning("PARK: the old accelerometer reader is still blocked — ignored")
            else:
                try:
                    proc.stdout.close()
                except Exception:
                    pass
        self._cleanup_due = True

    def _release_sensor(self) -> None:
        """``termux-sensor -c`` (jeśli od ostatniego był strumień albo
        paczka): Termux:API trzyma zarejestrowany czujnik także po zabiciu
        procesu, a nowego „pisarza” próbek tworzy dopiero po zwolnieniu."""
        if self._cleanup_due:
            self._cleanup_due = False
            self.a.phone.sensor_cleanup()

    def _burst(self, name: str) -> list:
        """Jedna paczka ``-n`` → wektory. Nieudana (błąd, przekroczony czas,
        pusta) → ``-c``: mogła zostawić czujnik zarejestrowany. Udana kończy
        się sama po stronie Androida (limit próbek)."""
        out = self.a.phone.sensor_burst(name)
        vecs = SensorParser(name).feed_text(out) if out else []
        self._cleanup_due = True
        if not vecs:
            self._release_sensor()
        return vecs

    def _sensor_off(self) -> None:
        """Strumień zatrzymany i ``termux-sensor -c`` (raz): Termux:API
        trzyma zarejestrowany czujnik także po zabiciu procesu."""
        self._stop_stream()
        self._release_sensor()
        self.sensor_state = "off"
        self._backoff = SENSOR_BACKOFF_MIN_S
        self._sensor_next = 0.0

    def _light_burst(self, now: float) -> None:
        if now < self._light_next:
            return
        self._light_next = now + PARK_LIGHT_EVERY_S
        name = self._sensor()
        if name is None:
            self.sensor_state = "no_sensor"
            return
        vecs = self._burst(name)
        if not vecs:
            self.sensor_state = "error"
            return
        t = self.a._clock()
        with self._det_lock:
            self._last_sample = t
            ev = self._det.feed_burst(t, vecs)
        self.sensor_state = "light"
        if ev is not None:
            try:
                # Kabina i tak pomija przechył i ruch w wersji lekkiej.
                self._det_q.put_nowait((ev[0], ev[1], t, True, True))
            except queue.Full:
                pass
            self.wake.set()

    def _next_wait(self) -> float:
        a = self.a
        now = a._clock()
        waits = [PARK_MAX_WAIT_S]
        with a._lock:
            wall, st, cfg = a._wall(), self.st, a.config
            armed = st["state"] in ("armed", "alarm")
            if self._jobs or self._kick:
                return 0.0
            if st["state"] == "arming" and st["arm_at"] is not None:
                waits.append(st["arm_at"] - wall)
            if armed and st["restored_wall"] is not None:
                waits.append(st["restored_wall"] + 60.0 * cfg["park_grace_min"] - wall)
            entry = self._entry_deadline_locked()
            if entry is not None:
                waits.append(entry - wall)
            cabin = self.cabin.next_deadline_locked()
            if cabin is not None:
                waits.append(cabin - wall)
            if st["state"] == "disarmed" and self._power == "unplugged" and not st["await_plug"]:
                base = self._contact_at if self._contact_at is not None else self._started
                waits.append(base + 60.0 * cfg["park_arm_after_min"] - now)
            light = self._light
            every = self._battery_every_locked()
        if self._battery_at is not None:
            waits.append(self._battery_at + every - now)
        if self._inbox_at is not None:
            waits.append(self._inbox_at + PARK_INBOX_EVERY_S - now)
        if armed and light:
            waits.append(self._light_next - now)
        elif armed and self._proc is None:
            waits.append(self._sensor_next - now)
        elif armed:
            waits.append(5.0)                    # zdrowie strumienia
        return min(PARK_MAX_WAIT_S, max(0.2, min(waits)))


# ── czuwanie kabiny (plan I): stan, aparat, analiza, retencja ─────────────

class CabinWatch:
    """Czuwanie kabiny (opis w nagłówku pliku, „Czuwanie kabiny”).

    Warstwa nad :class:`ParkGuard`: ten sam strumień czujników, ten sam stan
    uzbrojenia, ta sama kolejka SMS-ów i ten sam budżet alarmów auta.
    Zdarzenia (``self.st``, zapis atomowy w ``cabin.json``) zmieniają się
    WYŁĄCZNIE pod blokadą agenta — metody ``*_locked`` woła ParkGuard (wątek
    postoju, obsługa HTTP) pod tą blokadą i nie robią tam nic poza zapisem
    małego pliku stanu. Aparat, analiza, usuwanie EXIF i retencja idą
    w osobnym wątku kabiny (:meth:`step`, :meth:`Agent.run_cabin`) POZA
    blokadą: seria zdjęć trwa ok. 10 s i nie może wstrzymać skrzynki SMS ani
    terminów alarmu. Detektor światła (:attr:`light`) karmi wątek czytający
    strumień czujników, pod ``guard._det_lock`` (kolejność blokad: agent →
    detektor, nigdy odwrotnie).

    Args:
        guard: alarm na postoju, nad którym działa ta warstwa.
        pillow: ``"auto"`` (spróbuj ``import PIL`` przy pierwszej potrzebie),
            None (bez Pillow — testy) albo gotowy obiekt z :func:`load_pillow`.
    """

    def __init__(self, guard: "ParkGuard", pillow: Any = "auto") -> None:
        self.g = guard
        self.a = guard.a
        self.wake = threading.Event()
        self.dir = self.a._path(CABIN_DIR)
        self.st = normalize_cabin_state(self.a._load_json(CABIN_FILE, {}))
        self._pil_arg = pillow
        #: Czy jest Pillow (None = jeszcze nie sprawdzone) — do widoku.
        self.pillow: Optional[bool] = None if pillow == "auto" else pillow is not None
        # Pod guard._det_lock (wątek czytający strumień).
        self.light = LightDetector(self.a.config["cabin_light_ratio"],
                                   self.a.config["cabin_light_lux"])
        self.lux: Optional[float] = None
        self.lux_at: Optional[float] = None
        # Pod blokadą agenta.
        self._comb = CabinCombiner()
        self._todo: list = []
        self._purge: list = []
        self.camera = "unknown"
        self._limit_logged_at: Optional[float] = None
        #: Czuwanie działało przy uzbrojonym alarmie — zostaje do rozbrojenia
        #: (w pamięci: restart agenta przy wyłączonym przełączniku je kończy).
        self._latched = False
        # Tylko wątek kabiny.
        self._session: Optional[dict] = None
        self._front: Optional[str] = None
        self._front_at: Optional[float] = None
        self._cleanup_at: Optional[float] = None
        self._disk = (0, 0)
        self._warned: set = set()

    # ── pomocnicze ───────────────────────────────────────────────────────

    def _warn_once(self, key: str, msg: str, *args: Any) -> None:
        if key not in self._warned:
            self._warned.add(key)
            log.warning(msg, *args)

    def _save_locked(self) -> None:
        try:
            self.a._save_json(CABIN_FILE, self.st)
        except OSError as e:
            log.error("Cannot save the cabin watch state: %s", _clean(e))

    def _pillow(self) -> Any:
        """Pillow albo None; ``import`` dopiero przy pierwszej potrzebie
        (włączone czuwanie) — przy wyłączonym agent nie płaci pamięcią."""
        if self._pil_arg == "auto":
            self._pil_arg = load_pillow()
            self.pillow = self._pil_arg is not None
            if self._pil_arg is None:
                log.info("CABIN: no Pillow (pkg install python-pillow) — photos are kept "
                         "without analysis, EXIF removed without re-encoding")
        return self._pil_arg

    def _path(self, name: str) -> str:
        return os.path.join(self.dir, name)

    def enabled_locked(self) -> bool:
        """Przełączniki ``cabin_watch`` I ``parking_guard`` (warstwa nad
        alarmem na postoju — sama nie działa) — ALBO czuwanie, które było
        włączone przy uzbrojonym alarmie (zatrzask :attr:`_latched`, do
        rozbrojenia). Wyłączenie z BCM przy uzbrojonym nie jest dowodem
        właściciela (patrz :meth:`ParkGuard._on`): czekające zdarzenie
        nie jest odwoływane, a jego zdjęcia zostają."""
        toggles = self.a.config["toggles"]
        on = bool(toggles["cabin_watch"] and toggles["parking_guard"])
        armed = self.g.st["state"] in ("armed", "alarm")
        if on and armed:
            self._latched = True
        return on or (armed and self._latched)

    def active_locked(self) -> bool:
        """Czuwa: włączone i alarm na postoju uzbrojony (albo w alarmie)."""
        return self.enabled_locked() and self.g.st["state"] in ("armed", "alarm")

    def find_locked(self, eid: Any) -> Optional[dict]:
        return next((e for e in self.st["events"] if e["id"] == eid), None)

    def _pending_locked(self) -> Optional[dict]:
        return next((e for e in self.st["events"] if e["outcome"] == "pending"), None)

    def _deadline_locked(self, ev: dict) -> float:
        """Koniec okna wejścia; prąd, który wrócił (zapłon), przesuwa go do
        końca ``park_grace_min`` — tak samo jak w alarmie na postoju (start
        BCM i połączenie telefonu właściciela trwają dłużej niż 60 s).
        Czekający alarm postoju z WCZEŚNIEJSZYM terminem (``park_entry_s``
        krótsze niż ``cabin_entry_s``) skraca okno kabiny do swojego
        terminu: jedno wejście = jeden SMS, z liczbą zdjęć, o czasie, który
        wybrał właściciel — inaczej poszedłby SMS postoju, a alarm kabiny
        skończyłby się na limicie."""
        deadline = float(ev["deadline"])
        restored = self.g.st["restored_wall"]
        if restored is not None:
            deadline = max(deadline, restored + 60.0 * self.a.config["park_grace_min"])
        park = self.g._entry_deadline_locked()
        return deadline if park is None else min(deadline, park)

    def next_deadline_locked(self) -> Optional[float]:
        ev = self._pending_locked()
        return None if ev is None else self._deadline_locked(ev)

    def _lux_locked(self) -> Optional[float]:
        with self.g._det_lock:
            fresh = self.lux_at is not None and 0 <= self.a._clock() - self.lux_at < LIGHT_FRESH_S
            return self.lux if fresh else None

    # ── sygnały i zdarzenia (pod blokadą agenta) ──────────────────────────

    def signal_locked(self, kind: str, value: Optional[float], t: float, wall: float) -> None:
        """Sygnał T0 (``t`` = chwila wykrycia, zegar od startu telefonu).
        Przy czekającym zdarzeniu tylko dopisuje rodzaj do jego powodów
        (pełniejszy SMS: „swiatlo+ruch+przechyl”).

        W wersji „lekkiej” alarmu na postoju (po dobie albo < 30% baterii)
        nie ma aparatu ani czujnika światła: przechył i ruch zostają wtedy
        WYŁĄCZNIE alarmowi na postoju (jego treść SMS-a; nie zużywają też
        limitu serii zdjęć). Drzwi przyjmuje nadal — tylko kabina je obsługuje."""
        if kind not in CABIN_SIGNALS or not self.active_locked():
            return
        if kind in PARK_ENTRY_KINDS and self.g._light:
            return
        pend = self._pending_locked()
        if pend is not None:
            if kind not in pend["reasons"]:
                pend["reasons"] = [k for k in CABIN_SIGNALS if k in pend["reasons"] or k == kind]
                self._save_locked()
            return
        res = self._comb.feed(kind, t)
        if res is None:
            log.info("CABIN: weak signal %s%s", kind, "" if value is None else f" ({value:.2f})")
            return
        self._new_event_locked(res[0], res[1], wall)

    def _counted_walls_locked(self, wall: float) -> list:
        """Zdarzenia, które liczą się do limitu serii zdjęć: odwołane przez
        właściciela — nie (jego wejścia nie mogą zużyć budżetu na złodzieja)."""
        return sorted(abs(wall - e["wall"]) for e in self.st["events"]
                      if e["outcome"] not in CABIN_PURGED and abs(wall - e["wall"]) < DAY_S)

    def _event_wait_locked(self, wall: float) -> Optional[int]:
        ages = self._counted_walls_locked(wall)
        if ages and ages[0] < CABIN_EVENT_COOLDOWN_S:
            return _wait_s(CABIN_EVENT_COOLDOWN_S - ages[0])
        if len(ages) >= CABIN_EVENT_MAX_PER_DAY:
            return _wait_s(DAY_S - ages[CABIN_EVENT_MAX_PER_DAY - 1])
        return None

    def _new_event_locked(self, reasons: list, weak: bool, wall: float) -> None:
        wait = self._event_wait_locked(wall)
        if wait is not None:
            now = self.a._clock()
            if self._limit_logged_at is None or now - self._limit_logged_at >= 60.0:
                self._limit_logged_at = now
                log.warning("CABIN: motion in the cabin (%s), but the limit of photo series "
                            "(1 per %d min, %d per day) — next possible in %d s",
                            cabin_reason_text(reasons, weak), CABIN_EVENT_COOLDOWN_S // 60,
                            CABIN_EVENT_MAX_PER_DAY, wait)
            return
        cfg = self.a.config
        ev = {"id": secrets.token_hex(8), "wall": wall, "deadline": wall + cfg["cabin_entry_s"],
              "reasons": list(reasons), "weak": bool(weak), "lux": self._lux_locked(),
              "photos": [], "clean": True, "outcome": "pending",
              "log_only": bool(cfg["park_log_only"]), "analysis": None, "camera": ""}
        self.st["events"].append(ev)
        while len(self.st["events"]) > CABIN_MAX_EVENTS:
            victim = next((e for e in self.st["events"] if e["outcome"] != "pending"), None)
            if victim is None:
                break
            self.st["events"].remove(victim)
        # Seria zdjęć zdarzenia ma pierwszeństwo przed zdjęciem odniesienia.
        self._todo = [t for t in self._todo if t["kind"] != "ref"]
        self._todo.append({"kind": "event", "id": ev["id"]})
        log.warning("CABIN: motion in the cabin (%s) — photos now, alarm in %d s unless the "
                    "owner disarms%s", cabin_reason_text(reasons, weak), cfg["cabin_entry_s"],
                    " (log only, no SMS)" if ev["log_only"] else "")
        self._save_locked()
        self.wake.set()
        self.g.wake.set()

    def timers_locked(self, now: float, wall: float) -> bool:
        """Termin okna wejścia (wątek postoju, PRZED terminem alarmu na
        postoju — jeden SMS na wejście). True = alarm czeka na świeży odczyt
        baterii albo właśnie poszedł."""
        ev = self._pending_locked()
        if ev is None:
            return False
        # Wyłączenie z BCM NIE odwołuje czekającego zdarzenia (to nie dowód
        # właściciela): przy uzbrojonym alarm idzie po terminie jak zwykle.
        if self.g.st["state"] not in ("armed", "alarm"):
            # Rozbrojone bez przejścia przez disarmed_locked (np. stan
            # wczytany po restarcie) — nie wiadomo, kto rozbroił: bez SMS-a.
            ev["outcome"] = "expired"
            self._save_locked()
            return False
        deadline = self._deadline_locked(ev)
        if wall < deadline:
            return False
        if wall - deadline > RESUME_MAX_LATE_S:
            ev["outcome"] = "expired"
            log.warning("CABIN: the entry window of event %s ended while the agent was down "
                        "— no SMS", ev["id"])
            self._save_locked()
            return False
        g = self.g
        if g._battery_at is None or now - g._battery_at > PARK_ENTRY_FRESH_S:
            # Najpierw świeży odczyt: prąd, który wrócił przed chwilą (zapłon),
            # przesuwa termin o park_grace_min.
            g._kick = True
            return True
        log.warning("CABIN: entry window over without the owner's proof — alarm")
        self._fire_locked(ev, wall)
        return True

    def _fire_locked(self, ev: dict, wall: float) -> None:
        """Alarm kabiny: stan alarmu auta i SMS (zadanie z pozycją w wątku
        postoju) w ramach budżetu alarmu na postoju — wspólnego, bo to jeden
        alarm auta: czekający alarm postoju (okno wejścia) i powrót prądu
        obejmuje ten sam SMS."""
        g, cfg = self.g, self.a.config
        if g.st["restored_wall"] is not None and "power" not in ev["reasons"]:
            ev["reasons"] = [k for k in CABIN_SIGNALS if k in ev["reasons"] or k == "power"]
        log_only = bool(ev["log_only"] or cfg["park_log_only"])
        if cabin_inside(ev["reasons"]):
            g.st["last_event"] = {"kind": "cabin", "ts": int(ev["wall"]),
                                  "value": float(len(ev["photos"])), "logged_only": log_only}
        # Sam przechył / ruch: zdarzenie postoju (przechył, wstrząs) zapisał
        # już jego detektor — zostaje, jak treść SMS-a (cabin_alarm_text).
        why = cabin_reason_text(ev["reasons"], ev["weak"])
        if log_only:
            ev["outcome"] = "logged"
            log.warning("CABIN (log only, no SMS): %s, %d photo(s)", why, len(ev["photos"]))
        elif not g.numbers_locked():
            ev["outcome"] = "no_numbers"
            g._warn_once("no_numbers", "PARK: no numbers for the alarm SMS (park_numbers "
                                       "from BCM, or --park-numbers on the phone)")
        elif g._alarm_wait_locked(wall) is not None:
            ev["outcome"] = "limited"
            log.warning("CABIN: alarm SMS limit of the parked car (1 per %d min, %d per day) "
                        "— %s only logged", PARK_ALARM_COOLDOWN_S // 60, PARK_ALARM_MAX_PER_DAY,
                        why)
        else:
            ev["outcome"] = "alarm"
            g.st["alarm_walls"].append(wall)
            pend = g.st["pending"]
            if pend is not None:
                log.warning("PARK: the waiting %s alarm is covered by the cabin alarm (one SMS "
                            "per entry)", pend["kind"])
                g.st["pending"] = None
            g.st["restored_wall"] = None
            if g.st["state"] != "alarm":
                g.st["state"] = "alarm"
                g.st["since"] = wall
            if len(g._jobs) < PARK_MAX_JOBS:
                g._jobs.append({"kind": "cabin_alarm", "id": ev["id"], "wall": ev["wall"]})
            else:
                log.error("PARK: too many pending jobs — the cabin alarm SMS is dropped")
            log.critical("CABIN ALARM: %s, %d photo(s)", why, len(ev["photos"]))
            g.wake.set()
        g._save_locked()
        self._save_locked()

    def _cancel_locked(self, ev: dict, outcome: str) -> None:
        """Dowód właściciela (``owner``) albo wypadek / 112 (``crash``)
        w oknie wejścia: alarm odwołany, zdjęcia tego zdarzenia do usunięcia
        (wątek kabiny). Wyłączenie z BCM tu NIE trafia (to nie dowód)."""
        ev["outcome"] = outcome
        self._todo = [t for t in self._todo if t.get("id") != ev["id"]]
        if ev["id"] not in self._purge:
            self._purge.append(ev["id"])
        log.warning("CABIN: %s within the entry window — cabin alarm cancelled, its photos "
                    "are deleted", "the owner disarmed" if outcome == "owner"
                    else "crash / 112 call")
        self._save_locked()
        self.wake.set()

    def disarmed_locked(self, by: str, wall: float) -> None:
        """Alarm na postoju rozbrojony (woła :meth:`ParkGuard._disarm_locked`
        NA POCZĄTKU, zanim obsłuży własny czekający alarm). Dowód właściciela
        (:data:`PARK_OWNER_BY`) i wypadek (``crash``) odwołują zdarzenie
        i kasują jego zdjęcia; inne rozbrojenie (niska bateria,
        dom) wysyła alarm od razu — to mógł być złodziej, a telefon zaraz
        przestanie pilnować. Zatrzask czuwania (:attr:`_latched`) kończy
        się tu."""
        self._todo = [t for t in self._todo if t["kind"] != "ref"]
        self._comb.reset()
        self._latched = False
        ev = self._pending_locked()
        if ev is None:
            return
        if by in PARK_OWNER_BY or by == "crash":
            self._cancel_locked(ev, "crash" if by == "crash" else "owner")
        else:
            log.warning("CABIN: disarmed (%s) during the entry window — the cabin alarm goes "
                        "now", by)
            self._fire_locked(ev, wall)

    def config_changed(self) -> None:
        """Nowa konfiguracja z BCM (wołane po podmianie ``Agent.config``, bez
        blokady agenta — tu tylko ``_det_lock``): progi skoku światła działają
        od razu (kalibracja w tygodniu ``park_log_only`` bez restartu
        agenta)."""
        cfg = self.a.config
        with self.g._det_lock:
            self.light.set_thresholds(cfg["cabin_light_ratio"], cfg["cabin_light_lux"])

    def armed_locked(self, wall: float) -> None:
        """Świeże uzbrojenie: nowe filtry i zdjęcie odniesienia (pusta kabina,
        właściciel wyszedł w oknie wyjścia) po :data:`CABIN_REF_DELAY_S`."""
        self._comb.reset()
        with self.g._det_lock:
            self.light.reset()
        self._todo = [t for t in self._todo if t["kind"] != "ref"]
        if self.enabled_locked():
            self._todo.append({"kind": "ref", "due": self.a._clock() + CABIN_REF_DELAY_S})
            self.wake.set()

    # ── widok ────────────────────────────────────────────────────────────

    @staticmethod
    def _event_view(ev: dict) -> dict:
        a = ev.get("analysis") or {}
        return {"id": ev["id"], "ts": int(ev["wall"]), "reasons": list(ev["reasons"]),
                "weak": ev["weak"], "photos": len(ev["photos"]), "outcome": ev["outcome"],
                "verdict": a.get("verdict"), "changed_pct": a.get("changed_pct"),
                "ref": a.get("ref"), "camera": ev["camera"]}

    def view(self) -> dict:
        """``GET /v1/cabin`` — stan i zdarzenia, NIGDY zdjęcia."""
        with self.a._lock:
            return self.view_locked(self.a._wall())

    def view_locked(self, wall: float) -> dict:
        cfg, g = self.a.config, self.g
        enabled = self.enabled_locked()
        armed = g.st["state"] in ("armed", "alarm")
        pend = self._pending_locked()
        state = "off" if not enabled else "idle" if not armed else \
            "pending" if pend is not None else "watching"
        lux = self._lux_locked()
        light_sensor = "ok" if lux is not None else \
            "none" if g._sensor_listed and g._light_name is None else "unknown"
        events = self.st["events"]
        n, size = self._disk
        return {
            "state": state,
            "camera": self.camera if enabled and armed else "unknown",
            "light_sensor": light_sensor,
            "lux": None if lux is None else round(lux, 1),
            "pillow": self.pillow,
            "log_only": bool(cfg["park_log_only"]),
            "entry_until": None if pend is None else int(self._deadline_locked(pend)),
            "photos_n": int(n),
            "photos_mb": round(size / (1024 * 1024), 1),
            "events_today": len(self._counted_walls_locked(wall)),
            "last_event": self._event_view(events[-1]) if events else None,
            "events": [self._event_view(e) for e in events[-CABIN_VIEW_EVENTS:]],
        }

    # ── wątek kabiny ─────────────────────────────────────────────────────

    def step(self) -> float:
        """Jeden krok wątku kabiny: retencja (co 10 min), usuwanie zdjęć
        odwołanych zdarzeń, jedna czynność serii zdjęć albo start następnej.
        Przy wyłączonym czuwaniu — zero wywołań Termux:API. Zwraca, za ile
        sekund następny krok."""
        a = self.a
        now = a._clock()
        if self._cleanup_at is None or now - self._cleanup_at >= CABIN_CLEANUP_EVERY_S:
            self._cleanup_at = now
            self.cleanup()
        with a._lock:
            purge, self._purge = list(self._purge), []
            enabled, active = self.enabled_locked(), self.active_locked()
            dirty = [(e["id"], list(e["photos"])) for e in self.st["events"]
                     if e["photos"] and not e["clean"] and e["outcome"] not in CABIN_PURGED]
        for eid in purge:
            self._purge_event(eid)
        if self._session is not None:
            return self._session_step(a._clock())
        if enabled:
            self._pillow()
        for eid, names in dirty:
            self._clean_event(eid, names)       # przerwana seria (restart agenta)
        if not active:
            with a._lock:
                self._todo = []
            return CABIN_MAX_WAIT_S
        block = self._camera_block(now, fresh=False)
        with a._lock:
            self.camera = block or "ok"
            todo = next((t for t in self._todo if t["kind"] == "event"), None) or next(
                (t for t in self._todo if t["kind"] == "ref" and now >= t["due"]), None)
            if todo is not None:
                self._todo.remove(todo)
            refs = [t["due"] for t in self._todo if t["kind"] == "ref"]
        if todo is None:
            return min(CABIN_MAX_WAIT_S, max(0.2, min(refs) - now)) if refs else CABIN_MAX_WAIT_S
        if todo["kind"] == "ref":
            # Bez Pillow nie ma analizy — po co aparat; bez odczytu światła
            # nie wiadomo, do której klasy światła należy odniesienie;
            # w ciemności (< 10 lux) klatka i tak wyszłaby czarna — a ekran,
            # Termux na wierzchu i aparat w pustym aucie nocą tylko świecą
            # pod podsufitką i kosztują baterię.
            lux = self._lux_now()
            why = "no Pillow" if self._pillow() is None else \
                "no light reading" if lux is None else \
                f"dark cabin, {lux:.1f} lux" if light_class(lux) == "dark" else ""
            if why:
                log.info("CABIN: no reference photo (%s)", why)
                return 0.0
        block = self._camera_block(now, fresh=True)
        with a._lock:
            # Rozmowa 112 z tego telefonu: ekran rozmowy zostaje na wierzchu
            # (bez KEYCODE_WAKEUP / am start / SLEEP), żadnych zdjęć ludzi
            # przy aucie — sprawdzane tu, pod blokadą, tuż przed serią.
            if not block and self.g.call_live_locked():
                block = "in_call"
            self.camera = block or "ok"
            ev = self.find_locked(todo.get("id")) if todo["kind"] == "event" else None
            if todo["kind"] == "event" and (ev is None or ev["outcome"] != "pending"):
                return 0.0
            if ev is not None and block:
                ev["camera"] = block
                self._save_locked()
        if block:
            if todo["kind"] == "event":
                log.warning("CABIN: no photos (%s) — the alarm still goes on the sensors", block)
            return 0.0
        self._start(todo)
        return 0.0

    def _lux_now(self) -> Optional[float]:
        with self.a._lock:
            return self._lux_locked()

    def shutdown(self) -> None:
        """Koniec agenta w trakcie serii: ekran wygaszony, seria porzucona
        (zrobione zdjęcia zostają; EXIF usunie następny start)."""
        s, self._session = self._session, None
        if s is not None and s["woke"]:
            self._su(SLEEP_COMMAND)

    def _su(self, command: str) -> bool:
        rc, _out, err = self.a.phone.su(command)
        if rc != 0:
            self._warn_once("su:" + command, "CABIN: su '%s' failed (%s) — the screen or "
                            "Termux in the foreground may be missing, photos may fail "
                            "(Magisk: su for Termux)", command, _clean(err) or f"exit {rc}")
        return rc == 0

    def _ensure_dir(self) -> bool:
        """Katalog zdjęć 0700, NIE dowiązanie symboliczne (nic nie trafi poza
        prywatny katalog Termuxa), a ścieżka nadaje się dla aparatu."""
        try:
            os.makedirs(self.dir, mode=0o700, exist_ok=True)
            st = os.lstat(self.dir)
            if not stat.S_ISDIR(st.st_mode):
                return False
            if stat.S_IMODE(st.st_mode) != 0o700:
                os.chmod(self.dir, 0o700)
        except OSError:
            return False
        return valid_photo_path(self._path(f"cab_{'0' * 16}_0.jpg"))

    def _camera_block(self, now: float, fresh: bool) -> str:
        """Powód, dla którego aparat ma nie działać, albo "" (działa).
        ``fresh`` = przed serią: bateria nie starsza niż
        :data:`CABIN_BATTERY_FRESH_S` (temperatura!) i id przedniej kamery."""
        g, a = self.g, self.a
        if fresh:
            with a._lock:
                at = g._battery_at
            if at is None or now - at > CABIN_BATTERY_FRESH_S:
                g._poll_battery(now)
        with a._lock:
            light, pct, temp, power = g._light, g._pct, g._temp, g._power
        if light:
            return "light_mode"
        if pct is not None and pct < CABIN_MIN_PCT:
            return "low_battery"
        if temp is None:
            return "no_temp"
        if temp < CABIN_TEMP_MIN_C:
            return "cold"
        if temp > CABIN_TEMP_MAX_C:
            return "hot"
        if power == "plugged" and temp >= CABIN_CHARGING_HOT_C:
            return "charging_hot"
        if not self._ensure_dir():
            self._warn_once("dir", "CABIN: the photo directory %s is not a private directory "
                                   "with a plain path — no photos", self.dir)
            return "bad_path"
        try:
            vfs = os.statvfs(self.dir)
            if vfs.f_bavail * vfs.f_frsize < CABIN_MIN_FREE_BYTES:
                return "no_space"
        except OSError:
            return "bad_path"
        if not fresh:
            return "" if self._front is not None or self._front_at is None else "no_front_camera"
        return "" if self._front_camera(now) is not None else "no_front_camera"

    def _front_camera(self, now: float) -> Optional[str]:
        """Id przedniej kamery: ``termux-camera-info`` raz (w pamięci), po
        porażce najwcześniej za :data:`CABIN_CAMERA_RETRY_S`."""
        if self._front is not None:
            return self._front
        if self._front_at is not None and now - self._front_at < CABIN_CAMERA_RETRY_S:
            return None
        self._front_at = now
        front = parse_camera_info(self.a.phone.camera_info())
        if front is None:
            log.error("CABIN: no front camera in 'termux-camera-info' (Termux:API camera "
                      "permission?) — no photos, retry in %d min", CABIN_CAMERA_RETRY_S // 60)
            return None
        self._front = front
        log.info("CABIN: front camera id %s", front)
        return front

    # ── seria zdjęć (maszyna stanów, jedna czynność na krok) ──────────────

    def _start(self, todo: dict) -> None:
        now = self.a._clock()
        with self.a._lock:
            ev = self.find_locked(todo.get("id")) if todo["kind"] == "event" else None
            lux = ev["lux"] if ev is not None else self._lux_locked()
            if lux is None:
                lux = self._lux_locked()
        self._session = {"kind": todo["kind"], "id": todo.get("id"),
                         "n": CABIN_PHOTOS if todo["kind"] == "event" else 1, "i": 0,
                         "t0": now, "next": now, "files": [], "woke": False, "finish": False,
                         "lux": lux}
        with self.g._det_lock:
            # Ekran zaraz się włączy — czujnik światła patrzy w ekran.
            self.light.mute(now + CABIN_SESSION_MUTE_S)
        log.info("CABIN: photo series started (%s)", todo["kind"])

    def _session_stop(self, s: dict) -> tuple[bool, bool]:
        """``(przerwać, usunąć zdjęcia)``: rozbrojone / wyłączone — koniec
        serii; dowód właściciela — także usunięcie zdjęć."""
        with self.a._lock:
            # Połączenie 112 w trakcie serii: koniec serii (zdjęcia zostają,
            # ekran wygaszany jak zwykle — rozmowa trwa dalej).
            stop = not self.active_locked() or self.g.call_live_locked()
            purge = False
            if s["kind"] == "event":
                ev = self.find_locked(s["id"])
                purge = ev is None or ev["outcome"] in CABIN_PURGED
            return stop or purge, purge

    def _session_step(self, now: float) -> float:
        s = self._session
        assert s is not None
        stop, purge = self._session_stop(s)
        if stop and not s["finish"]:
            s["finish"], s["next"] = True, now
        if now < s["next"]:
            return s["next"] - now
        if s["finish"]:
            self._finish(s, purge)
            return 0.0
        if not s["woke"]:
            s["woke"] = True
            self._su(WAKE_COMMAND)
            self._su(FOREGROUND_COMMAND)
        i = s["i"]
        name = f"cab_{s['id']}_{i}.jpg" if s["kind"] == "event" else CABIN_REF_RAW
        ok, err = self.a.phone.camera_photo(self._front or "", self._path(name))
        if ok:
            s["files"].append(name)
            if s["kind"] == "event":
                with self.a._lock:
                    ev = self.find_locked(s["id"])
                    if ev is not None and name not in ev["photos"]:
                        ev["photos"].append(name)
                        ev["clean"] = False
                        self._save_locked()
        else:
            log.warning("CABIN: photo %d/%d failed: %s", i + 1, s["n"], err)
            self._unlink(name)          # termux-camera-photo zakłada pusty plik
        s["i"] += 1
        now = self.a._clock()
        if s["i"] < s["n"]:
            s["next"] = max(now, s["t0"] + CABIN_PHOTO_GAP_S * s["i"])
        else:
            s["finish"], s["next"] = True, now + CABIN_SETTLE_S
        return max(0.0, s["next"] - now)

    def _finish(self, s: dict, purge: bool) -> None:
        """Koniec serii: ekran wygaszony, pliki sprawdzone, EXIF usunięty,
        analiza (jeśli jest Pillow) — albo usunięcie, gdy właściciel zdążył
        w międzyczasie rozbroić."""
        self._session = None
        with self.a._lock:
            in_call = self.g.call_live_locked()
        if s["woke"] and not in_call:
            # Przy rozmowie 112 ekranu nie wygaszam — to ekran rozmowy.
            self._su(SLEEP_COMMAND)
        with self.g._det_lock:
            self.light.mute(self.a._clock() + CABIN_LIGHT_MUTE_S)
        names = [n for n in s["files"] if self._verify(n)]
        if s["kind"] == "ref":
            if names and not purge:
                self._make_ref(names[0], s["lux"])
            self._unlink(CABIN_REF_RAW)
            self.cleanup()
            return
        if purge:
            self._purge_event(s["id"])
            return
        for n in names:
            self._strip(n)
        with self.a._lock:
            diff_pct = float(self.a.config["cabin_diff_pct"])
            mask = [list(r) for r in self.a.config["cabin_mask"]]
        analysis = self._analyse(names, s["lux"], diff_pct, mask)
        with self.a._lock:
            ev = self.find_locked(s["id"])
            purge = ev is None or ev["outcome"] in CABIN_PURGED
            if not purge:
                ev["photos"] = [n for n in ev["photos"] if n in names]
                ev["clean"] = True
                ev["analysis"] = analysis
                self._save_locked()
        if purge:
            self._purge_event(s["id"])
            return
        log.info("CABIN: %d photo(s) kept, analysis: %s%s", len(names), analysis["verdict"],
                 "" if analysis.get("changed_pct") is None
                 else f" ({analysis['changed_pct']}% changed, vs {analysis['ref']})")
        self.cleanup()

    def _clean_event(self, eid: str, names: list) -> None:
        """Zdjęcia serii przerwanej restartem agenta: sprawdzone i bez EXIF."""
        kept = [n for n in names if self._verify(n)]
        for n in kept:
            self._strip(n)
        with self.a._lock:
            ev = self.find_locked(eid)
            if ev is not None:
                ev["photos"] = [n for n in ev["photos"] if n in kept]
                ev["clean"] = True
                self._save_locked()

    # ── pliki ─────────────────────────────────────────────────────────────

    def _unlink(self, name: str) -> bool:
        """Usuń plik z katalogu zdjęć — tylko zwykły plik (dowiązania i
        katalogi nie), tylko nazwę według naszych wzorców."""
        if not (_CABIN_PHOTO_RE.fullmatch(name) or _CABIN_REF_RE.fullmatch(name)
                or name == CABIN_REF_RAW or (name.startswith(".") and name.endswith(".tmp")
                                             and "/" not in name)):
            return False
        path = self._path(name)
        try:
            if not stat.S_ISREG(os.lstat(path).st_mode):
                return False
            os.unlink(path)
            return True
        except OSError:
            return False

    def _verify(self, name: str) -> bool:
        """Zdjęcie jest: zwykły plik, niepusty, nie większy niż
        :data:`CABIN_PHOTO_MAX_BYTES`; prawa 0600. Inaczej usunięte."""
        path = self._path(name)
        try:
            st = os.lstat(path)
        except OSError:
            return False
        if not stat.S_ISREG(st.st_mode):
            return False
        if not 0 < st.st_size <= CABIN_PHOTO_MAX_BYTES:
            self._unlink(name)
            return False
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return True

    def _strip(self, name: str) -> bool:
        """EXIF precz: z Pillow — przekodowanie do nowego obrazu (≤ 1280 px);
        bez Pillow (albo gdy przekodowanie zawiedzie) — wycięcie segmentów
        metadanych JPEG. False = plik zostaje, jaki był (log)."""
        path, tmp = self._path(name), self._path(f".{name}.tmp")
        pil = self._pillow()
        if pil is not None:
            try:
                pil_reencode(pil, path, tmp)
                os.chmod(tmp, 0o600)
                os.replace(tmp, path)
                return True
            except Exception as e:
                self._unlink(f".{name}.tmp")
                log.warning("CABIN: re-encoding %s failed (%s) — removing the metadata "
                            "without Pillow", name, _clean(e))
        try:
            data = read_small(path, CABIN_PHOTO_MAX_BYTES)
        except (OSError, ValueError):
            return False
        clean = strip_jpeg_metadata(data) if data else None
        if clean is None:
            log.warning("CABIN: %s is not a JPEG whose metadata I can remove — kept as it is "
                        "(EXIF may remain)", name)
            return False
        if clean != data:
            try:
                atomic_write(path, clean)
            except OSError as e:
                log.warning("CABIN: cannot rewrite %s without EXIF (%s)", name, _clean(e))
                return False
        return True

    def _analyse(self, names: list, lux: Optional[float], diff_pct: float,
                 mask: list) -> dict:
        """T2: różnica klatek względem odniesienia z tej samej klasy światła
        (bez niego — względem pierwszego zdjęcia serii). SMS nigdy na to nie
        czeka (alarm idzie z terminu okna wejścia)."""
        skipped = {"verdict": "skipped", "changed_pct": None, "ref": None}
        pil = self._pillow()
        if pil is None or not names:
            return skipped
        try:
            frames = [pil_prepare(pil, self._path(n)) for n in names]
            if max(pil_mean(pil, f) for f in frames) < CABIN_DARK_MEAN:
                return {"verdict": "dark", "changed_pct": None, "ref": None}
            ref = None
            cls = light_class(lux)
            ref_name = f"ref_{cls}.png" if cls else None
            if ref_name and self._verify(ref_name):
                with pil.Image.open(self._path(ref_name)) as im:
                    ref = im.convert("L").resize(CABIN_FRAME)
            if ref is not None:
                pcts, mode = [pil_change_pct(pil, ref, f, mask) for f in frames], "ref"
            elif len(frames) >= 2:
                pcts = [pil_change_pct(pil, frames[0], f, mask) for f in frames[1:]]
                mode = "burst"
            else:
                return skipped
        except Exception as e:
            log.warning("CABIN: photo analysis failed (%s)", _clean(e))
            return {"verdict": "error", "changed_pct": None, "ref": None}
        best = max(pcts)
        return {"verdict": "change" if best >= diff_pct else "no_change",
                "changed_pct": round(min(100.0, best), 1), "ref": mode}

    def _make_ref(self, name: str, lux: Optional[float]) -> None:
        """Odniesienie klasy światła: TYLKO przetworzona klatka 320×240
        w odcieniach szarości (PNG, 0600) — surowe zdjęcie jest usuwane."""
        pil, cls = self._pillow(), light_class(lux)
        if pil is None or cls is None:
            return
        tmp = f".ref_{cls}.png.tmp"
        try:
            frame = pil_prepare(pil, self._path(name))
            if pil_mean(pil, frame) < CABIN_DARK_MEAN:
                log.info("CABIN: the reference photo is dark (%s) — not stored", cls)
                return
            frame.save(self._path(tmp), "PNG")
            os.chmod(self._path(tmp), 0o600)
            os.replace(self._path(tmp), self._path(f"ref_{cls}.png"))
            log.info("CABIN: reference photo for light class %s stored (320x240 grey)", cls)
        except Exception as e:
            self._unlink(tmp)
            log.warning("CABIN: cannot store the reference photo (%s)", _clean(e))

    def _purge_event(self, eid: str) -> None:
        """Zdjęcia odwołanego zdarzenia (dowód właściciela) — usunięte."""
        if not isinstance(eid, str) or not _CABIN_ID_RE.fullmatch(eid):
            return
        n = 0
        for i in range(CABIN_PHOTOS):
            n += self._unlink(f"cab_{eid}_{i}.jpg")
            self._unlink(f".cab_{eid}_{i}.jpg.tmp")
        with self.a._lock:
            ev = self.find_locked(eid)
            if ev is not None:
                ev["photos"] = []
                ev["clean"] = True
                self._save_locked()
        if n:
            log.warning("CABIN: %d photo(s) of the cancelled event deleted", n)
        self.cleanup()

    def cleanup(self) -> None:
        """Retencja: zdjęcia (i odniesienia) starsze niż 72 h precz, potem
        najstarsze, dopóki wszystko razem przekracza 200 MB; porzucone pliki
        tymczasowe po godzinie. Tylko zwykłe pliki o naszych nazwach —
        nic innego w katalogu nie jest ruszane."""
        wall = self.a._wall()
        busy = set(self._session["files"]) if self._session is not None else set()
        try:
            with os.scandir(self.dir) as it:
                entries = [e for _i, e in zip(range(4096), it)]
        except FileNotFoundError:
            self._disk = (0, 0)
            return
        except OSError as e:
            self._warn_once("scandir", "CABIN: cannot list %s (%s)", self.dir, _clean(e))
            return
        files = []
        for e in entries:
            name = e.name
            photo = bool(_CABIN_PHOTO_RE.fullmatch(name) or _CABIN_REF_RE.fullmatch(name))
            temp = name == CABIN_REF_RAW or (name.startswith(".") and name.endswith(".tmp"))
            if not (photo or temp) or name in busy:
                continue
            try:
                st = e.stat(follow_symlinks=False)
            except OSError:
                continue
            if not stat.S_ISREG(st.st_mode):
                continue
            age = wall - st.st_mtime
            if (temp and age > CABIN_TMP_KEEP_S) or (photo and age > CABIN_KEEP_S):
                self._unlink(name)
            elif photo:
                files.append((st.st_mtime, name, st.st_size))
        files.sort()
        total = sum(f[2] for f in files)
        for n in busy:
            try:
                total += os.lstat(self._path(n)).st_size
            except OSError:
                pass
        while files and total > CABIN_MAX_BYTES:
            _mtime, name, size = files.pop(0)
            if self._unlink(name):
                total -= size
                log.warning("CABIN: %s deleted — photos over %d MB", name,
                            CABIN_MAX_BYTES // (1024 * 1024))
        left = {f[1] for f in files} | busy
        with self.a._lock:
            changed = False
            for ev in self.st["events"]:
                kept = [n for n in ev["photos"] if n in left]
                if kept != ev["photos"]:
                    ev["photos"] = kept
                    changed = True
            if changed:
                self._save_locked()
        self._disk = (sum(1 for n in left if _CABIN_PHOTO_RE.fullmatch(n)), max(0, total))


# ── walidacja danych od BCM ───────────────────────────────────────────────

def default_config() -> dict:
    """Konfiguracja przed pierwszym ``PUT /v1/config``: bez odbiorców, tryb
    testowy, wszystkie przełączniki wyłączone."""
    return {"recipients": [], "sim_slot": 0, "vehicle_label": DEFAULT_LABEL,
            "toggles": {k: False for k in TOGGLES}, "dry_run": True, "follow_up_cancel": True,
            # Bez konfiguracji z BCM: 112 w trybie TESTOWYM bez numeru = nic
            # nie da się wybrać (i tak przełącznik call112 jest wyłączony).
            "call112_test_mode": True, "call112_test_number": "",
            # Alarm na postoju: bez numerów, tylko log (przełącznik i tak off).
            **{k: (list(v) if isinstance(v, list) else v) for k, v in PARK_DEFAULTS.items()},
            # Czuwanie kabiny: okno wejścia 60 s, próg 3%, bez maski, skok światła ×5 i +5 lux.
            **{k: (list(v) if isinstance(v, list) else v) for k, v in CABIN_DEFAULTS.items()},
            # Budzenie IR: kod domyślny z firmware (przełącznik i tak off).
            **WAKE_DEFAULTS}


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
    park, err = normalize_park_config(obj, base)
    if park is None:
        return None, err
    out.update(park)
    cabin, err = normalize_cabin_config(obj, base)
    if cabin is None:
        return None, err
    out.update(cabin)
    wake, err = normalize_wake_config(obj, base)
    if wake is None:
        return None, err
    out.update(wake)
    return out, ""


def normalize_wake_config(obj: dict, base: dict) -> tuple[Optional[dict], str]:
    """Pola ``wake_*`` (budzenie IR) — opcjonalne (BCM wysyła je tylko
    z włączonym ``modules.remote_session``), ale podane muszą być liczbami
    całkowitymi w zakresie: to z nich (i tylko z nich) powstaje wzorzec
    ``termux-infrared-transmit``."""
    out: dict[str, Any] = {}
    for key, hi in (("wake_ir_address", 0xFFFF), ("wake_ir_command", 0xFF)):
        v = obj.get(key, base[key])
        if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= hi:
            return None, f"{key}: integer 0..{hi}"
        out[key] = int(v)
    return out, ""


def normalize_park_config(obj: dict, base: dict) -> tuple[Optional[dict], str]:
    """Pola ``park_*`` (alarm na postoju) — wszystkie opcjonalne (BCM wysyła
    je tylko z włączonym ``modules.parking_guard``), ale podane muszą być
    poprawne (BCM sam przycina wartości, więc wartość spoza zakresu to błąd,
    a nie „popraw po cichu”). Postać kanoniczna jak w BCM (skrót musi się
    zgadzać): liczby zmiennoprzecinkowe zaokrąglone do 0,01, współrzędne
    do 6 miejsc."""
    out: dict[str, Any] = {}
    nums = normalize_park_numbers(obj.get("park_numbers", base["park_numbers"]))
    if nums is None:
        return None, f"park_numbers: at most {MAX_RECIPIENTS} numbers ^\\+[1-9][0-9]{{7,14}}$"
    out["park_numbers"] = nums
    log_only = obj.get("park_log_only", base["park_log_only"])
    if not isinstance(log_only, bool):
        return None, "park_log_only must be a boolean"
    out["park_log_only"] = log_only
    for key, (lo, hi) in PARK_INT_RANGES.items():
        v = _number(obj.get(key, base[key]), lo, hi, integer=True)
        if v is None:
            return None, f"{key}: integer {lo}..{hi}"
        out[key] = int(v)
    for key, (flo, fhi) in PARK_FLOAT_RANGES.items():
        f = _number(obj.get(key, base[key]), flo, fhi)
        if f is None:
            return None, f"{key}: number {flo}..{fhi}"
        out[key] = round(float(f), 2)
    home = obj.get("park_home", base["park_home"])
    if home is not None:
        if not isinstance(home, dict) or set(home) != {"lat", "lon", "radius_m"}:
            return None, "park_home: null or {lat, lon, radius_m}"
        lat, lon = _number(home["lat"], -90, 90), _number(home["lon"], -180, 180)
        radius = _number(home["radius_m"], *PARK_HOME_RADIUS_M, integer=True)
        if lat is None or lon is None or radius is None:
            return None, (f"park_home: lat -90..90, lon -180..180, radius_m integer "
                          f"{PARK_HOME_RADIUS_M[0]}..{PARK_HOME_RADIUS_M[1]}")
        home = {"lat": round(float(lat), 6), "lon": round(float(lon), 6), "radius_m": int(radius)}
    out["park_home"] = home
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


def write_park_setup(state_dir: str, new: bool = False, out: Any = None) -> int:
    """``--park-setup``: sekret TOTP do poleceń SMS alarmu na postoju
    (``PARK OFF <kod>`` itd.) — tworzy go, gdy go nie ma (albo z ``--new``:
    nowy, stary kod w aplikacji przestaje działać), zapisuje w ``park_totp``
    (0600) i wypisuje NA EKRAN adres ``otpauth://`` dla aplikacji
    „authenticator”. Nigdy do logu. Działający agent bierze nowy sekret
    przy następnym poleceniu (bez restartu)."""
    out = out if out is not None else sys.stdout
    try:
        os.chmod(state_dir, 0o700)
    except OSError:
        pass
    path = os.path.join(state_dir, TOTP_FILE)
    try:
        raw = read_small(path, 256)
    except (OSError, ValueError):
        raw = None
    current = raw.decode("ascii", "replace").strip().upper() if raw else ""
    if parse_totp_secret(current) is not None and not new:
        secret = current
        print("Sekret TOTP juz jest (ten sam kod w aplikacji). Nowy: --park-setup --new",
              file=out)
    else:
        secret = new_totp_secret()
        try:
            atomic_write(path, (secret + "\n").encode("ascii"))
        except OSError as e:
            print(f"Nie moge zapisac {path}: {_clean(e)}", file=sys.stderr)
            return 1
        print("Nowy sekret TOTP zapisany (park_totp, 0600).", file=out)
    print("Dodaj go w aplikacji authenticator (np. Aegis z F-Droid) - wklej adres albo "
          "wpisz sekret recznie (TOTP, SHA1, 6 cyfr, 30 s):", file=out)
    print(otpauth_uri(secret), file=out)
    print(f"Sekret: {secret}", file=out)
    print("Polecenia SMS z numeru z listy: POZYCJA <kod>, PARK ON <kod>, PARK OFF <kod>, "
          "PARK STATUS <kod>.", file=out)
    return 0


def write_park_numbers(state_dir: str, text: str, out: Any = None) -> int:
    """``--park-numbers +48…,+48…``: biała lista ustawiona w telefonie
    (``park_local.json``, 0600) — używana, gdy BCM nie wysyła własnej
    (``parking_guard.numbers``). Pusty tekst czyści listę."""
    out = out if out is not None else sys.stdout
    items = [n.strip() for n in (text or "").split(",") if n.strip()]
    nums = normalize_park_numbers(items)
    if nums is None:
        print(f"Najwyzej {MAX_RECIPIENTS} numery w formacie +48601234567, rozdzielone "
              f"przecinkiem.", file=sys.stderr)
        return 2
    path = os.path.join(state_dir, PARK_LOCAL_FILE)
    try:
        atomic_write(path, canonical_json({"numbers": nums}).encode("ascii"))
    except OSError as e:
        print(f"Nie moge zapisac {path}: {_clean(e)}", file=sys.stderr)
        return 1
    print(f"Numery postoju w telefonie: {', '.join(mask_number(n) for n in nums) or 'brak'} "
          f"(BCM, jesli wysyla wlasne, ma pierwszenstwo).", file=out)
    return 0


#: ``--wake``: kod wyjścia dla wake.sh (komunikat w Termux:Widget).
WAKE_EXIT = {"sent": 0, "off": 3, "rate": 4, "busy": 5, "no_ir": 6, "failed": 6}


def run_wake(state_dir: str, out: Any = None,
             transmit: Optional[Callable[[list], "tuple[bool, str]"]] = None,
             wall: Callable[[], float] = time.time) -> int:
    """``--wake``: jedna próba budzenia komputera w aucie (plan E) bez
    serwera — ten sam limit i ta sama blokada pliku co ``WAKE <kod>``
    w działającym agencie. Konfiguracja (przełącznik ``remote_session``,
    kod IR) z ``config.json`` zapisanego przez agenta. Kod wyjścia:
    :data:`WAKE_EXIT`."""
    out = out if out is not None else sys.stdout
    raw = None
    try:
        raw = read_small(os.path.join(state_dir, "config.json"))
        obj = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant) if raw else {}
    except (OSError, ValueError, UnicodeDecodeError, RecursionError):
        obj = {}
    cfg, _err = normalize_config(obj if isinstance(obj, dict) else {})
    if cfg is None:
        cfg = default_config()
    if transmit is None:
        transmit = Phone(default_runner, boot_clock).ir_transmit
    result = wake_ir(state_dir, transmit, cfg, wall(), "local")
    print({"sent": "Budzenie wyslane (3 ramki IR).",
           "off": "Budzenie wylaczone - wlacz modules.remote_session w BCM (konfiguracja "
                  "przychodzi z BCM).",
           "rate": f"Limit budzenia: 1 na minute, {WAKE_MAX_PER_HOUR} na godzine, "
                   f"{WAKE_MAX_PER_DAY} na dobe.",
           "busy": "Trwa inne budzenie - sprobuj za chwile.",
           }.get(result, "Budzenie nieudane - brak nadajnika IR albo blad Termux:API "
                         "(termux-infrared-frequencies)."), file=out)
    return WAKE_EXIT.get(result, 6)


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="BCM agent for the car phone (Termux)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help="port on 127.0.0.1 (default 8765)")
    parser.add_argument("--state-dir", default=DEFAULT_STATE_DIR)
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--pair", action="store_true",
                        help="write a fresh one-time pairing code into PAIRING, print it, exit")
    parser.add_argument("--park-setup", action="store_true",
                        help="parking guard: create (or show) the TOTP secret, print the "
                             "otpauth:// URI, exit")
    parser.add_argument("--new", action="store_true",
                        help="with --park-setup: replace the TOTP secret")
    parser.add_argument("--park-numbers", metavar="LIST", default=None,
                        help="parking guard: allowed numbers set on the phone (comma "
                             "separated E.164, '' clears), exit")
    parser.add_argument("--wake", action="store_true",
                        help="wake the car computer: send the IR code once (rate-limited; "
                             "needs remote_session from BCM), exit — wake.sh")
    args = parser.parse_args(argv)
    os.makedirs(args.state_dir, mode=0o700, exist_ok=True)
    if args.pair:
        return write_pairing_code(args.state_dir)
    if args.park_setup:
        return write_park_setup(args.state_dir, args.new)
    if args.park_numbers is not None:
        return write_park_numbers(args.state_dir, args.park_numbers)
    if args.wake:
        return run_wake(args.state_dir)
    setup_logging(args.state_dir, args.verbose)
    agent = Agent(args.state_dir)
    server = make_server(agent, args.port)
    stop = threading.Event()
    threads = [threading.Thread(target=agent.run_scheduler, args=(stop,), daemon=True,
                                name="scheduler"),
               threading.Thread(target=agent.run_status, args=(stop,), daemon=True,
                                name="status"),
               threading.Thread(target=agent.run_calls, args=(stop,), daemon=True,
                                name="call112"),
               threading.Thread(target=agent.run_park, args=(stop,), daemon=True,
                                name="park"),
               threading.Thread(target=agent.run_cabin, args=(stop,), daemon=True,
                                name="cabin")]
    for t in threads:
        t.start()

    def _stop(signum: int, frame: Any) -> None:
        stop.set()
        agent.wake.set()
        agent.status_kick.set()
        agent.call_wake.set()
        agent.park.wake.set()
        agent.park.cabin.wake.set()
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    log.info("BCM agent %s listening on %s:%d (paired: %s, pairing file: %s)", VERSION,
             BIND_HOST, server.server_address[1], agent.paired, agent.pairing_open)
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        stop.set()
        agent.park.wake.set()
        agent.park.cabin.wake.set()
        server.server_close()
        # Wątek postoju zatrzymuje strumień czujnika (termux-sensor -c),
        # wątek kabiny wygasza ekran po przerwanej serii zdjęć.
        threads[-2].join(timeout=8)
        threads[-1].join(timeout=5)
    log.info("BCM agent stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
