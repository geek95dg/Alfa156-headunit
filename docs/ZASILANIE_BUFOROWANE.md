# Zasilanie buforowane — Lenovo M910q w Alfa Romeo 156

Kompletny opis układu zasilania head unitu BCM v8.5: bufor z akumulatorów
CSB HR1221W (AGM), ładowanie, blokada przeładowania, ochrona przed głębokim
rozładowaniem, sterowanie stanem komputera i przetwornica step-up do 19 V.

**Schematy blokowe:** [`../schematics/power_buffered_m910q.svg`](../schematics/power_buffered_m910q.svg) ·
[`../schematics/charging_lvd.svg`](../schematics/charging_lvd.svg) ·
[`../schematics/power_domains_m910q.svg`](../schematics/power_domains_m910q.svg)

**Jak to pospiąć — zacisk po zacisku:** [`SCHEMATY_POLACZEN.md`](SCHEMATY_POLACZEN.md)

**Wdrożenie całości:** [`WDROZENIE_M910Q.md`](WDROZENIE_M910Q.md)

---

## Spis treści

1. [Po co bufor](#1-po-co-bufor)
2. [Architektura — jedna szyna, trzy stany maszyny](#2-architektura--jedna-szyna-trzy-stany-maszyny)
3. [Przetwornica step-up XL6019 — weryfikacja](#3-przetwornica-step-up-xl6019--weryfikacja)
4. [Bank akumulatorów CSB HR1221W](#4-bank-akumulatorów-csb-hr1221w)
5. [Ładowanie — dwa warianty](#5-ładowanie--dwa-warianty)
6. [Blokada przeładowania](#6-blokada-przeładowania)
7. [LVD — moduł XH-M609](#7-lvd--moduł-xh-m609)
8. [Bezpieczniki, przekroje, masa](#8-bezpieczniki-przekroje-masa)
9. [Budżet energetyczny i czas postoju](#9-budżet-energetyczny-i-czas-postoju)
10. [Lista zakupowa](#10-lista-zakupowa)
11. [Procedura pierwszego uruchomienia](#11-procedura-pierwszego-uruchomienia)
12. [Serwis i kontrola okresowa](#12-serwis-i-kontrola-okresowa)
13. [Znane rozbieżności i luki](#13-znane-rozbieżności-i-luki)

---

## 1. Po co bufor

Trzy niezależne powody — każdy sam w sobie wystarczyłby:

| Problem | Bez bufora | Z buforem |
|---------|-----------|-----------|
| **Rozruch silnika** | Instalacja 12 V zapada na 6–8 V przez 200–600 ms. M910q gubi zasilanie i twardo się resetuje przy każdym przekręceniu kluczyka. | Bank trzyma szynę powyżej 12 V przez cały rozruch — komputer nawet nie mrugnie. |
| **Funkcje na postoju** | Pilot szyb 433 MHz i bramkowany BLE przycisk bagażnika muszą żyć non stop. Wpięte w akumulator rozruchowy rozładują go w kilka dni. | Domena A żyje z banku. Akumulator rozruchowy jest odizolowany i zawsze gotowy do rozruchu. |
| **Jakość napięcia** | Instalacja auta to śmietnik EMI: przepięcia od cewek, load dump z alternatora, tętnienia. | Bank o pojemności 25,5 Ah to gigantyczny kondensator — wygładza wszystko, co jest za nim. |

Kluczowa konsekwencja architektury: **akumulator rozruchowy nigdy nie zasila
head unitu na postoju**. Rozdziela je przekaźnik ładowania z diodą, więc auto
zawsze odpali, choćby bank był pusty.

---

## 2. Architektura — jedna szyna, trzy stany maszyny

![Rozdział zasilania](../schematics/power_domains_m910q.svg)

Wszystko wisi na **jednej szynie buforowanej** za LVD i wyłącznikiem
głównym. Zapłon nie odcina już żadnego odbiornika — jest wyłącznie
**sygnałem**, który Arduino zamienia na „naciśnięcie" przycisku zasilania
M910q.

| | |
|---|---|
| **Odbiorniki stale zasilane** | M910q, hub USB, oba wyświetlacze, Arduino Pro Micro, Nano #1, Nano #2, HM-10 BLE, RXB6 433 MHz, moduł 9 przekaźników, DAC USB, graber AHD |
| **Jedyny przekaźnik w torze mocy** | w **ładowaniu**, nie w odbiornikach — rozłącza bank od instalacji auta przy zgaszonym silniku (§5.3c) |
| **Rola zapłonu** | sygnał do Arduino → impuls na styki przycisku zasilania → S3 albo wybudzenie |

### 2.1 Trzy stany i trzy poziomy poboru

| Stan | Co pobiera | Pobór z banku | 5 pakietów | 8 pakietów |
|------|-----------|---------------|-----------|-----------|
| **Praca** | wszystko | 10–55 W | — | — |
| **S3** | logika + M910q w S3 + straty przetwornic | **400–550 mA** | ~1,2 dnia | ~1,9 dnia |
| **Wyłączony** (impuls 5 s) | logika + straty przetwornic | **100–200 mA** | ~3,5–5,3 dnia | ~5,7–8,5 dnia |

Wszystko do 50 % DoD. Wniosek jest praktyczny: **S3 do krótkich postojów,
twarde wyłączenie do długich**. Arduino przełącza między nimi samo — po
2 godzinach zgaszonego zapłonu daje dłuższy impuls i maszyna gaśnie
całkowicie. Powrót to znowu krótki impuls.

### 2.2 Dlaczego nie przekaźnik odcinający komputer

Wcześniejsze wydanie tej dokumentacji odcinało M910q i wyświetlacze
przekaźnikiem zapłonu („domena B"). Model został **porzucony** — oto
dlaczego:

| | Przekaźnik odcinający | Stałe zasilanie + S3 |
|---|---|---|
| Postój (5 pakietów) | ~6,6 dnia | ~1,2 dnia w S3, ~3,5–5,3 po wyłączeniu |
| Wybudzenie | zimny start ~40 s | **~3 s** z S3 |
| Ryzyko ucięcia zapisu na dysk | **przy każdym przekręceniu kluczyka** | brak — maszyna schodzi do S3 sama |
| Elementy w torze mocy | przekaźnik 30 A + okablowanie | **brak** |
| Kod / firmware | brak | impuls z Arduino, po stronie hosta zero zmian |

Twarde odcięcie zasilania pracującemu Linuksowi kilka razy dziennie to
proszenie się o uszkodzenie systemu plików, a różnica w czasie postoju
znika, gdy tylko dołożymy eskalację do pełnego wyłączenia. Realizacja
i pomiary: [`../schematics/ignition_sense.svg`](../schematics/ignition_sense.svg)
oraz [`WDROZENIE_TESTOWE.md`](WDROZENIE_TESTOWE.md) §3.1a.

**Dlaczego wyświetlacze mają własny buck, a nie USB.** Same panele
spokojnie zasiliłyby się z portów USB M910q — i tak właśnie robi wariant
testowy ([`WDROZENIE_TESTOWE.md`](WDROZENIE_TESTOWE.md) §3.1). W wersji
docelowej stoi temu na przeszkodzie **regulacja jasności**: podświetlenie
jest sterowane PWM-em z Nano #1 przez stopień MOSFET, a tego nie da się
wpiąć w zasilanie logiki panelu idące po USB. Drugi powód jest energetyczny
— dwa panele na szynie 19,5 V wypchnęłyby XL6019 poza jego ~45 W.

**Wzmacniacz idzie osobną gałęzią** prosto z akumulatora rozruchowego —
gotowy moduł samochodowy, podłączany jak radio: własny bezpiecznik przy klemie
(wg karty modułu, zwykle 20–30 A), przewód 6 mm², **własna masa lokalna**
i wyzwalanie sygnałem **REM wprost z linii zapłonu** — wzmacniacz ma grać,
gdy jedziesz, a nie gdy komputer jest w S3.

Powód: 4 × 50 W RMS to w szczytach 20–30 A. Taki prąd rozłożyłby bank AGM
w kilkanaście minut i przekroczyłby przekaźnik LVD (20 A). Z systemem
buforowanym łączy wzmacniacz wyłącznie **sygnał REM i ekran kabla RCA** —
żaden prąd mocy przez bank nie przechodzi.

Tor audio, pętla masy i ustawianie wzmocnienia:
[`../schematics/audio_system.svg`](../schematics/audio_system.svg).

---

## 3. Przetwornica step-up XL6019 — weryfikacja

Moduł jest już kupiony, więc zamiast doboru — **lista kontrolna i realne
ograniczenia tego konkretnego układu**. To jedyny element toru, który zasila
komputer bezpośrednio.

### 3.1 Napięcie: 19 V czy 20 V?

Oryginalny zasilacz M910q to **20 V / 65 W**. Dokumentacja produkcyjna w tym
repozytorium (`docs/x86-production/02-assembly.html`) podaje, że **M910q
pracuje w zakresie 19–21 V i nie wystartuje poza nim**.

19 V mieści się w zakresie, ale leży **przy samej dolnej granicy**. Pod
obciążeniem dojdzie do tego:

- spadek na przewodzie step-up → wtyk (przy 3,5 A i 1,5 mm² na 1 m ≈ 0,04 V — pomijalny),
- spadek na samej przetwornicy przy wzroście obciążenia (regulacja obciążeniowa, typowo 1–3 %),
- spadek napięcia wejściowego, gdy bank schodzi w stronę LVD.

> **Ustaw wyjście na 19,5 V, nie 19,0 V.** Nadal bezpiecznie w zakresie
> 19–21 V, a daje ~0,5 V zapasu na zapady. Reguluj potencjometrem pod
> obciążeniem, nie na biegu jałowym, i po ustawieniu zabezpiecz śrubę
> kroplą lakieru do paznokci lub kleju — wibracje w aucie potrafią
> rozstroić potencjometr.

### 3.2 Ile XL6019 naprawdę udźwignie

Najpierw czego **potrzebowałby** zasilacz o pełnej mocy znamionowej M910q:

| Wielkość | Wartość |
|----------|---------|
| Znamionowa moc M910q | 65 W |
| Prąd wyjściowy przy 19,5 V | 65 / 19,5 = **3,34 A** |
| Moc wejściowa przy sprawności 88 % | 65 / 0,88 = **73,9 W** |
| Prąd wejściowy przy 12,6 V (bank w spoczynku) | 73,9 / 12,6 = **5,9 A** |
| Prąd wejściowy przy 11,0 V (próg LVD) | 73,9 / 11,0 = **6,7 A** |

A teraz czego XL6019 **jest w stanie dostarczyć**. Układ ma **limit prądu
klucza 5 A**, a w topologii boost prąd klucza to w przybliżeniu prąd
wejściowy. Po odjęciu marginesu na tętnienie zostaje ok. **4,0–4,5 A
użytecznego prądu wejściowego**:

| Napięcie wejściowe | Moc wejściowa przy 4,5 A | Moc wyjściowa (88 %) |
|-------------------|--------------------------|---------------------|
| 12,6 V (bank w spoczynku) | 56,7 W | **~50 W** |
| 12,0 V | 54,0 W | **~47 W** |
| 11,0 V (próg LVD) | 49,5 W | **~43 W** |

> **Wniosek: ten moduł da ok. 45 W ciągle, nie 65 W.** Napis „150 W" albo
> „400 W" na płytce odnosi się do szczytu przy najwyższym dopuszczalnym
> napięciu wejściowym i z chłodzeniem — nie do pracy ciągłej przy 12 V.

Czy 45 W wystarczy? Realny pobór M910q jest znacznie niższy niż znamionowe
65 W:

| Stan | Pobór |
|------|-------|
| Dashboard, praca normalna | 20–30 W |
| Android Auto + dekodowanie wideo (VAAPI) | 30–40 W |
| Pełne obciążenie 4 wątków CPU | 50–55 W |

Czyli **normalna praca mieści się z zapasem, a tylko pełne obciążenie CPU
wychodzi poza możliwości modułu**. Rozwiązanie jest programowe — patrz §3.6.

> **Nie łącz dwóch XL6019 równolegle**, żeby uzyskać więcej prądu. Te moduły
> nie mają podziału obciążenia; ten z wyżej ustawionym napięciem weźmie
> całość i wejdzie w ograniczenie prądowe, a drugi będzie stał bezczynnie.

Bezpiecznik na wyjściu 19,5 V ma mieć **5 A**.

### 3.2a Zachowanie przy braku sterowania

Boost **nie potrafi dać napięcia niższego niż wejściowe**. Przy wyłączonej
regulacji na wyjściu pojawia się napięcie wejściowe pomniejszone o spadek na
diodzie (~11,4 V przy 12 V wejścia). M910q przy takim napięciu nie wystartuje,
ale też się nie uszkodzi.

Praktyczna konsekwencja: **wyjścia XL6019 nie da się użyć jako wyłącznika
komputera**. Odcinać musi przekaźnik zapłonu po stronie wejścia — i dokładnie
tak było w poprzednim modelu. Dziś M910q jest zasilany stale, a wyłącza go
impuls na przycisk zasilania (§2.1) — wyjście XL6019 i tak nie służy do
odcinania.

### 3.2b Prąd rozruchowy

Kondensatory wejściowe M910q przy załączeniu pobierają krótki impuls prądu,
który potrafi wprowadzić XL6019 w ograniczenie prądowe i tryb „czkawki"
(hiccup) — moduł próbuje startować cyklicznie zamiast wejść w normalną pracę.

Jeżeli tak się zachowa:

- **kondensator 470 µF / 35 V low-ESR na wyjściu** przetwornicy (i tak warto),
- **termistor NTC ograniczający prąd rozruchowy** (np. 5 Ω / 5 A) szeregowo
  na wyjściu — po nagrzaniu jego rezystancja spada do ułamka oma.

### 3.3 Wtyk zasilania

M910q używa firmowego wtyku Lenovo (slim tip). Kupowanie „uniwersalnej"
końcówki to loteria — pasowanie mechaniczne i obecność środkowego pinu
identyfikacyjnego różnią się między wersjami.

**Najpewniejsze rozwiązanie: poświęć oryginalny zasilacz.** Odetnij kabel
30–40 cm od wtyku, sprawdź polaryzację multimetrem (środek = „+", ekran =
masa) i podłącz do wyjścia przetwornicy. Zyskujesz gwarantowane pasowanie
mechaniczne i oryginalny przewód o właściwym przekroju.

> **Pin identyfikacyjny.** W zasilaczach Lenovo slim-tip środkowy pin
> przenosi sygnał identyfikacyjny z układu w kostce zasilacza. Po odcięciu
> kabla ten sygnał znika. Laptopy ThinkPad wyświetlają wtedy ostrzeżenie
> i ograniczają ładowanie; **komputery ThinkCentre Tiny w praktyce startują
> normalnie**, ale tego nie da się założyć w ciemno dla konkretnej sztuki.
> Dlatego test z §3.4 jest obowiązkowy i musi się odbyć **przed** zabudową
> auta.

### 3.4 Test na biurku — obowiązkowy

Zanim cokolwiek trafi do samochodu:

```bash
# 1. Zasil przetwornicę z akumulatora 12 V (albo zasilacza laboratoryjnego
#    z limitem prądu 10 A). Wyjście USTAW NA 19,5 V bez obciążenia.
# 2. Podłącz M910q. Musi wystartować i wejść do systemu.
# 3. Obciąż CPU i sprawdź, czy napięcie się trzyma:
sudo apt install -y stress-ng
stress-ng --cpu 4 --timeout 600s
```

W trakcie testu mierz i zapisuj:

| Pomiar | Wartość dopuszczalna |
|--------|---------------------|
| Napięcie na wtyku M910q pod obciążeniem | **≥ 19,0 V** przez cały czas |
| Prąd wejściowy przetwornicy | zgodny z §3.2, bez pulsowania |
| Temperatura cewki i układu scalonego po 10 min | **< 85 °C** (bezdotykowo lub termoparą) |
| Stabilność systemu | brak resetów, brak wpisów o zaniku zasilania w `journalctl -b` |

**Powtórz test przy napięciu wejściowym 11,0 V** (symulacja rozładowanego
banku tuż przed progiem LVD). To najgorszy przypadek — największy prąd
wejściowy i największe grzanie.

Jeżeli którykolwiek pomiar wypadnie poza normę: dołóż radiator i wentylator
40 mm, a jeśli to nie pomoże — wymień przetwornicę na mocniejszą. Nie
próbuj tego „docisnąć" w aucie.

### 3.5a Ograniczenie poboru M910q — wymagane przy XL6019

Skoro moduł daje ok. 45 W, a pełne obciążenie CPU potrafi dobić do 55 W,
trzeba ograniczyć maksymalny pobór pakietu. Najprościej przez **RAPL**:

```bash
# sprawdź, gdzie jest pakiet (zwykle intel-rapl:0)
ls /sys/class/powercap/

# odczyt bieżącego limitu (w mikrowatach)
cat /sys/class/powercap/intel-rapl:0/constraint_0_power_limit_uw

# ustaw limit pakietu na 28 W
echo 28000000 | sudo tee /sys/class/powercap/intel-rapl:0/constraint_0_power_limit_uw
```

Utrwalenie przez systemd:

```ini
# /etc/systemd/system/bcm-power-cap.service
[Unit]
Description=BCM — limit poboru pakietu CPU (zasilanie z XL6019)
After=multi-user.target

[Service]
Type=oneshot
ExecStart=/bin/sh -c 'echo 28000000 > /sys/class/powercap/intel-rapl:0/constraint_0_power_limit_uw'
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now bcm-power-cap
```

Alternatywa (jeśli RAPL nie jest dostępny) — ograniczenie przez `intel_pstate`:

```bash
echo 70 | sudo tee /sys/devices/system/cpu/intel_pstate/max_perf_pct
```

**28 W pakietu + ~10 W reszty systemu = ~38 W**, czyli komfortowo poniżej
45 W możliwości modułu. Dla dashboardu i Android Auto to bez znaczenia —
dekodowanie wideo i tak idzie po VAAPI, a nie po CPU.

### 3.5 Chłodzenie i montaż

Przetwornica przy 65 W i sprawności 88 % rozprasza ~9 W. W zamkniętej
zabudowie za deską rozdzielczą, latem, to wystarczy do przegrzania.

- radiator na układzie scalonym i na cewce, klej termoprzewodzący,
- wentylator 40 mm zasilany z szyny buforowanej (5 V albo 12 V),
- montaż na blasze albo profilu aluminiowym pełniącym rolę radiatora,
- **nie** montuj płytki bezpośrednio na tapicerce ani wykładzinie.

---

## 4. Bank akumulatorów CSB HR1221W

### 4.1 Karta katalogowa

| Parametr | Wartość |
|----------|---------|
| Typ | **VRLA AGM** (separator z maty szklanej), seria **HR — High Rate** |
| Napięcie / cele | 12 V / 6 cel |
| Pojemność | **5,1 Ah** przy rozładowaniu 20-godzinnym |
| Moc | 21 W/celę przez 15 min do 1,67 V/celę |
| Zaciski | **F2** — nasuwka faston 6,35 mm |
| Wymiary | 90 × 70 × 101 mm |
| Masa | ~1,8 kg |
| Rezystancja wewnętrzna | ~23 mΩ |
| Maks. prąd rozładowania | 60 A przez 5 s |
| **Ładowanie buforowe (float)** | **13,5–13,8 V @ 25 °C** |
| **Ładowanie cykliczne** | **14,4–15,0 V @ 25 °C** |
| **Maks. prąd ładowania** | **2,1 A na pakiet** |
| Kompensacja temperaturowa | **−18 mV/°C** (float), **−30 mV/°C** (cykl) |
| Żywotność projektowa | **3–5 lat** pracy buforowej @ 25 °C |
| Żywotność cykliczna | **> 260 cykli** przy 100 % DoD |
| Samorozładowanie | > 75 % pojemności po 6 miesiącach @ 25 °C |

> **To jest akumulator AGM, nie żelowy.** Ma to bezpośrednie przełożenie
> na nastawy ładowania — patrz §4.4.

### 4.2 Konfiguracja banku

Pakiety łączone **równolegle** — napięcie zostaje 12 V, sumuje się pojemność.

| Liczba pakietów | Pojemność | Masa | Maks. prąd ładowania | Uwagi |
|-----------------|-----------|------|---------------------|-------|
| 4 | 20,4 Ah | 7,2 kg | 8,4 A | minimum sensowne |
| **5** | **25,5 Ah** | **9,0 kg** | **10,5 A** | **optimum — zalecane** |
| 6 | 30,6 Ah | 10,8 kg | 12,6 A | jeśli jest miejsce |
| 8 | 40,8 Ah | 14,4 kg | 16,8 A | przemyśl, czy 14 kg w aucie jest warte 5 dni więcej |

Notatki w repozytorium mówią o **ośmiu posiadanych pakietach**. Użycie pięciu
daje optimum, a trzy zostają jako zapas — pakiety starzeją się też leżąc, więc
rotacja jest korzystna.

Pięć pakietów obok siebie zajmuje ok. **350 × 90 × 101 mm** (bokiem, szerokość
70 mm każdy) plus miejsce na przewody i pasy.

### 4.3 Zasady łączenia równoległego

Nierówne łączenie równoległe to najczęstszy powód, dla którego bank umiera
przedwcześnie: pakiet z najniższą rezystancją bierze na siebie większość prądu
i wykańcza się pierwszy.

- **jednakowe pakiety** — ten sam model i najlepiej ta sama dostawa
  (zbliżony wiek i partia produkcyjna),
- **jednakowe przewody** — identyczna długość i przekrój od każdego pakietu
  do szyny, nawet jeśli fizycznie leżą różnie,
- **łączenie po przekątnej** — pobór z „+" pierwszego pakietu i „−" ostatniego,
  albo (lepiej) dedykowana szyna/mostek miedziany, do którego wszystkie pakiety
  wpinają się osobno,
- **bezpiecznik 10 A na dodatnim biegunie każdego pakietu** — zwarta cela
  w jednym pakiecie nie zabiera wtedy całej szyny,
- **nie dokładaj nowego pakietu do starego banku** — wyrównuj cały komplet.

**Zaciski F2 w samochodzie.** Nasuwki 6,35 mm prądowo wystarczają z ogromnym
zapasem (bezpiecznik 10 A jest tu elementem ograniczającym), ale w aucie
problemem są wibracje:

- nasuwki żeńskie 6,35 mm **w pełni izolowane**, zaciskane zaciskarką
  zapadkową — nie kombinerkami,
- koszulka termokurczliwa z klejem na całym połączeniu,
- **odciążenie mechaniczne**: wiązkę przypnij opaską do skrzynki, żeby ciężar
  przewodu nie wisiał na nasuwce,
- odrobina smaru stykowego przeciw korozji ciernej (fretting).

### 4.4 AGM — nastawy ładowania

Ponieważ HR1221W to AGM, obowiązują wartości z karty katalogowej CSB:

| Parametr | Zakres katalogowy | **Przyjęta nastawa** | Dlaczego |
|----------|------------------|---------------------|----------|
| Absorpcja (cykl) | 14,4–15,0 V | **14,40 V** | dolny kraniec — najłagodniejszy dla żywotności |
| Podtrzymanie (float) | 13,5–13,8 V | **13,65 V** | środek zakresu |
| Prąd ładowania | maks. 2,1 A/pakiet | **6,0 A** dla 5 pakietów | 57 % katalogowego limitu 10,5 A |

> **Korekta wcześniejszej wersji tego dokumentu.** Wcześniejsze wydanie
> zakładało akumulatory żelowe i podawało 14,20 V / 13,70 V oraz ostrzeżenie,
> że 14,4 V jest za dużo. **Dla HR1221W jest inaczej: 14,4 V mieści się
> w katalogowym zakresie cyklicznym**, a wartości 15–20 A z oryginalnych
> notatek repo są za wysokie nie dlatego, że to żel, tylko dlatego, że limit
> katalogowy wynosi 2,1 A na pakiet (10,5 A na bank pięciu).

**Seria HR to akumulator buforowy, nie trakcyjny.** Konstrukcja z cienkimi
płytami jest zoptymalizowana pod krótkie rozładowania dużym prądem (UPS) —
i to akurat **bardzo dobrze pasuje** do roli bufora rozruchowego: rezystancja
23 mΩ na pakiet daje po zrównolegleniu 4,6 mΩ, więc pobór 7 A przez step-up
powoduje spadek zaledwie ~32 mV. Czego HR nie lubi, to **głębokie cyklowanie**
— stąd LVD i dyscyplina DoD z §9.

### 4.5 Kompensacja temperaturowa

CSB podaje **dwa różne współczynniki**:

| Tryb | Współczynnik (blok 12 V) |
|------|-------------------------|
| Ładowanie buforowe (float) | **−18 mV/°C** |
| Ładowanie cykliczne (absorpcja) | **−30 mV/°C** |

| Temperatura | Absorpcja | Float |
|-------------|-----------|-------|
| −10 °C | 15,00 V * | 14,28 V |
| 0 °C | 15,00 V * | 14,10 V |
| +15 °C | 14,70 V | 13,83 V |
| **+25 °C** | **14,40 V** | **13,65 V** |
| +40 °C | 13,95 V | 13,38 V |
| +50 °C | 13,65 V | 13,20 V |

\* obliczeniowo 15,15 V (0 °C) i 15,45 V (−10 °C), ale **ograniczone do 15,0 V**
— górnej granicy katalogowej CSB. Ładowarka, która nie ma takiego ograniczenia,
przy mrozie wyjedzie ponad kartę katalogową.

Czujnik NTC 10 kΩ przyklej do **boku obudowy pakietu w środku banku** (nie na
skrajnym, nie na biegunie).

### 4.6 Temperatura, nie cyklowanie, wyznacza żywotność

Karta podaje **3–5 lat pracy buforowej przy 25 °C**. Reguła Arrheniusa dla
akumulatorów ołowiowych: **każde +10 °C mniej więcej połowi ten czas.**

| Miejsce montażu | Szacowana żywotność |
|-----------------|--------------------|
| kabina, pod fotelem / za panelem | 2–4 lata |
| bagażnik | 1,5–3 lata |
| przy tunelu wydechowym | < 1,5 roku |

Dla porównania strona cykliczna: > 260 cykli przy 100 % DoD, czyli grubo ponad
500 cykli przy 50 % DoD. Nawet gdybyś co tydzień schodził do 50 % DoD, to
~50 cykli rocznie — cyklowanie wyczerpie się po dekadzie, a kalendarz i ciepło
znacznie wcześniej.

**Wniosek praktyczny: miejsce montażu ma większy wpływ na żywotność banku niż
dyscyplina rozładowania.** Kabina bije bagażnik.

### 4.7 Montaż mechaniczny

- miejsce montażu: **pod fotelem pasażera**, nie w bagażniku — patrz
  [`../schematics/vehicle_layout_m910q.svg`](../schematics/vehicle_layout_m910q.svg),
- pakiety w **skrzynce lub na wsporniku**, przypięte pasami — 5 × 1,8 kg
  luzem w bagażniku to pocisk przy hamowaniu,
- pozycja: AGM toleruje dowolną orientację poza **do góry nogami**;
  stojąco albo leżąco na boku,
- **jak najdalej od źródeł ciepła** — patrz §4.6, to nie jest porada
  kosmetyczna,
- dostęp do zacisków bez demontażu połowy auta — będą potrzebne przy
  pomiarach okresowych,
- AGM jest szczelny (VRLA, rekombinacja gazów), więc montaż w kabinie jest
  dozwolony — ale **skrzynki nie zamykaj hermetycznie**. Przy awarii ładowania
  zawór bezpieczeństwa wypuszcza wodór; potrzebna jest szczelina wentylacyjna.

---

## 5. Ładowanie — dwa warianty

![Ładowanie i ochrona](../schematics/charging_lvd.svg)

### 5.1 Dlaczego zwykły buck DC-DC tu nie zadziała

Starsze notatki w repozytorium proponują moduł **buck** (XL4016) między diodą
a bankiem. To nie może działać poprawnie, i warto wiedzieć dlaczego:

```
alternator             14,4 V
− spadek na przewodach −0,2 V
− dioda Schottky       −0,45 V
─────────────────────────────
wejście przetwornicy   13,75 V
```

Przetwornica **buck obniża napięcie** — z 13,75 V nie zrobi 14,40 V absorpcji.
Bank nigdy nie dojdzie powyżej ~13,5 V, czyli utknie na ~85 % pojemności
i nigdy się w pełni nie naładuje.

Potrzebna jest topologia, która **potrafi podnieść napięcie**: buck-boost,
SEPIC albo zwykły boost o małym przełożeniu.

### 5.2 Wariant A — gotowa ładowarka DC-DC (zalecany)

Samochodowa ładowarka DC-DC („B2B", battery-to-battery) rozwiązuje w jednym
pudełku wszystko: topologię buck-boost, limit prądu, profil wielostopniowy
z presetem **AGM**, kompensację temperaturową i detekcję pracy alternatora.

| Model | Prąd | Orientacyjna cena | Uwagi |
|-------|------|------------------|-------|
| Victron Orion-Tr Smart 12/12-18 | 18 A | ~800–1000 PLN | konfiguracja przez Bluetooth, preset AGM, izolowana |
| Victron Orion XS 12/12-50 | 50 A | ~1200–1500 PLN | mocno przewymiarowana dla 25,5 Ah |
| Redarc BCDC1225D | 25 A | ~1300–1600 PLN | bardzo odporna, popularna w off-roadzie |
| Sterling BB1230 | 30 A | ~900–1200 PLN | |

Prąd nastaw i tak na **6 A** (katalogowy sufit dla pięciu HR1221W to 10,5 A)
— większy model to tylko zapas i mniejsze grzanie. Dla banku 25,5 Ah
**najmniejsza dostępna wersja w zupełności wystarcza**.

**Co odpada przy wariancie A:** przekaźnik ładowania (ładowarka sama wykrywa
pracę silnika), dioda Schottky (izolacja jest w środku), osobny czujnik NTC
(jest wbudowany albo w komplecie).

### 5.3 Wariant B — DIY

Tańszy, ale wymaga uwagi przy nastawianiu i regularnej kontroli.

```
akumulator → bezp. 15 A → TVS + C → przekaźnik ładowania → dioda MBR2545CT
           → moduł CC-CV boost → blokada nadnapięcia → bank
```

| Element | Rola | Nastawa | Cena |
|---------|------|---------|------|
| **Przekaźnik ładowania** 30 A SPDT | rozłącza tor ładowania, gdy silnik nie pracuje | cewka z zapłonu (patrz §5.3c) | 15–25 PLN |
| **Dioda Schottky MBR2545CT** | blokuje wsteczny przepływ do instalacji auta | obie połówki równolegle, na radiatorze | 5–12 PLN |
| **Moduł CC-CV boost** z regulacją prądu i napięcia | podnosi 13,7 V → 14,4 V i limituje prąd | CV 14,40 V, CC 6,0 A | 50–140 PLN |

#### 5.3a Konkretne moduły CC-CV

Wszystkie trzy to **boost**, więc nastawa CV musi być wyższa od napięcia
wejściowego — patrz §5.3b.

| Model | Dane | Cena | Kiedy ten |
|-------|------|------|-----------|
| **„900 W 15 A" z wyświetlaczem** (typ CNC/DPS, wej. 8–60 V, wyj. 10–120 V) | CC 0–15 A, nastawa cyfrowa z odczytem, pamięć nastaw | 90–140 PLN | **domyślny wybór** — wpisujesz 14,40 V i 6,0 A i odczytujesz z powrotem, zamiast celować potencjometrem |
| **SZBK07** (SZ-BT07CCCV-D1, „1500 W 30 A", wej. 10–60 V, wyj. 12–90 V) | CC 0,8–20 A ±0,3 A · sprawność 92–97 % · ochrona odwrotnej polaryzacji · 130 × 84 × 52 mm | 80–130 PLN | gdy chcesz duży zapas mocy i zimną pracę; nastawa potencjometrami |
| **„600 W 10 A"** (wej. 10–60 V, wyj. 12–80 V) | CC-CV potencjometrami | 50–80 PLN | wystarczy przy trzech pakietach (CC do 6 A) |

> **„Auto output on power-on".** Moduły z wyświetlaczem mają opcję
> automatycznego załączenia wyjścia po podaniu zasilania. Jeżeli zostanie
> wyłączona, to po każdym uruchomieniu silnika moduł stoi z wyjściem OFF
> i **bank się nie ładuje, bez żadnego objawu**. Ustaw to przy nastawianiu
> i sprawdź, odcinając i podając zasilanie.

#### 5.3b Nastawa CV musi być wyższa od wejścia

Boost ma władzę nad prądem **tylko wtedy, gdy przetwarza** — czyli gdy
napięcie wyjściowe jest wyższe od wejściowego. Poniżej tego progu duty
schodzi do zera i moduł przechodzi w **pass-through**: prąd płynie przez
dławik i diodę, a pętla CC nie ma czym sterować. To ta sama fizyka, którą
§3.2a opisuje dla XL6019.

Praktycznie: przy pracującym alternatorze na wejściu modułu jest
**13,4–14,2 V** (zależnie od spadku na przewodzie). Rozładowany bank ma
12,0 V. W pass-through różnicę 1,5–2 V ogranicza tylko rezystancja
okablowania i banku — przy ~50 mΩ to **ponad 30 A**, czyli przepalony
bezpiecznik w najlepszym razie.

| Nastawa CV | Co się dzieje |
|-----------|---------------|
| **14,40 V** | wyjście zawsze powyżej wejścia → moduł zawsze przetwarza → **CC działa** ✅ |
| 13,80 V | wejście bywa wyższe → pass-through → **CC nie działa** ❌ |

Dlatego **CV = 14,40 V**, a nie 13,80 V. Konsekwencje przyjmujesz świadomie:
próg warstwy 2 zostaje na **15,30 V** (§6.2), a kompensacji temperaturowej
nie ma.

**Co to łagodzi:** napięcie absorpcji jest podawane **wyłącznie przy
załączonym przekaźniku ładowania**, czyli podczas jazdy. Na postoju przekaźnik
jest rozwarty i bank stoi na własnym napięciu spoczynkowym — nie jest trzymany
na 14,4 V na okrągło. To zupełnie inny reżim niż stały float 14,4 V i dla
pracy buforowej całkowicie akceptowalny.

Dioda MBR2545CT dodatkowo obniża wejście boostu o ~0,5 V, czyli **powiększa
zapas nad nastawą CV** — pass-through z §5.3b staje się jeszcze mniej
prawdopodobny.

**Jeżeli mimo wszystko chcesz 13,80 V**, potrzebujesz topologii z władzą
w obie strony — modułu **buck-boost**:

| Model | Dane | Cena | Haczyk |
|-------|------|------|--------|
| **LTC3780** (moduł WD2002SJ / XR-131, wej. 5–32 V, wyj. 1–30 V) | buck-boost, CC + CV + próg podnapięciowy (trzy potencjometry), 10 A szczytowo | 50–90 PLN | **7 A i 80 W ciągle** — przy 13,8 V to tylko ~5,8 A, więc po odjęciu obciążenia do banku idzie mało. Do trzech pakietów w porządku, do ośmiu bez sensu |

#### 5.3c Przekaźnik ładowania i dioda MBR2545CT

Rozdział ładowania robią tu dwa tanie elementy zamiast modułu napięciowego.

**Dlaczego w ogóle coś tu musi być.** Boost nie potrafi dać napięcia niższego
niż wejściowe. Gdyby jego wejście wisiało na stałe na akumulatorze
rozruchowym, to przy zgaszonym silniku (12,4 V) dalej próbowałby podawać
14,4 V i **rozładowywałby akumulator auta**. Tor ładowania musi więc być
fizycznie rozłączany, gdy silnik nie pracuje.

| Element | Rola | Uwaga |
|---------|------|-------|
| **Przekaźnik 30 A SPDT** + podstawka | rozłącza tor, gdy silnik nie pracuje | dioda 1N4007 równolegle do cewki |
| **MBR2545CT** — 25 A / 45 V, TO-220AB | druga bariera: blokuje przepływ wsteczny, gdyby styki przekaźnika się zespawały | dwie połówki po 12,5 A ze **wspólną katodą** |

**Czym sterować cewkę.** Najprościej **zapłonem** i tak jest w tej
dokumentacji założone. Ma to jeden koszt, który warto znać: przy kluczyku
w pozycji ON bez pracującego silnika przekaźnik jest zwarty, więc boost
ładuje bank **z akumulatora rozruchowego**. Przy normalnym uruchamianiu
to kilka sekund i nie ma znaczenia; przy dłuższym staniu z kluczykiem
(radio na postoju, diagnostyka) — ma.

Jeżeli chcesz to wyeliminować, podepnij cewkę pod **D+/L alternatora**
zamiast pod zapłon. To dosłownie jeden przewód inaczej, a sygnał znaczy
wtedy „alternator ładuje", a nie „kluczyk przekręcony". Sprawdź potem, czy
lampka kontrolna ładowania dalej działa poprawnie — cewka pobiera ~150 mA
z jej obwodu.

**Montaż diody.** MBR2545CT to dwie diody ze wspólną katodą, a **katoda jest
połączona z blaszką montażową**:

- **zewrzyj obie anody** (piny 1 i 3) i podaj na nie plus z przekaźnika,
  katodę (pin 2 / blaszka) na wejście boostu — dostajesz pełne 25 A i niższy
  spadek: przy 9 A łącznie każda połówka wiezie 4,5 A, czyli Vf ≈ 0,45–0,50 V,
- **radiator obowiązkowy** — 9 A × 0,5 V to ok. **4,5 W** ciągłej straty,
- blaszka jest pod potencjałem katody, więc albo **izoluj ją podkładką
  mikową**, albo przykręcaj do radiatora, który nie dotyka masy nadwozia.

**Kompensacja temperaturowa w wariancie B** jest ręczna: tanie moduły CC-CV
jej nie mają, a — jak pokazuje §5.3b — zejście z CV do „bezpiecznych" 13,8 V
kupuje spokój kosztem utraty ograniczenia prądowego, czyli w złą stronę.
Zostaje **14,40 V bez kompensacji**, z trzema rzeczami, które to trzymają
w ryzach:

- przekaźnik ładowania podaje to napięcie **tylko podczas jazdy**, nie na postoju,
- rozłącznik nadnapięciowy 15,30 V łapie awarię modułu (§6),
- bank w bagażniku rzadko przekracza 30 °C, a przy 40 °C prawidłowa absorpcja
  to 13,95 V — czyli 14,40 V to przegrzanie o 0,45 V przez kilka godzin jazdy,
  a nie stałe przeładowanie.

Jeżeli auto stoi latem w słońcu i bagażnik dochodzi do 50 °C, obniż CV do
**14,10 V** — nadal powyżej wejścia, więc CC pozostaje sprawne.

### 5.4 Ochrona wejścia

Instalacja 12 V auta bywa brudna elektrycznie. Na **wejściu ładowarki**
(strona od akumulatora rozruchowego):

- **dioda TVS** 1.5KE33CA albo SMCJ26CA równolegle do wejścia — obcina
  load dump z alternatora,
- **kondensator elektrolityczny** 470 µF / 35 V równolegle — wygładza
  tętnienia i pomaga przy zapadach,
- sprawdź w karcie katalogowej modułu **maksymalne napięcie wejściowe** —
  jeśli to 30 V, to przy load dumpie bez TVS zostanie z niego dym.

---

## 6. Blokada przeładowania

To jest ta warstwa, o którą pytasz wprost — i jest **oddzielna od ładowarki**.

### 6.1 Dlaczego osobny element

Etap CV w ładowarce to warstwa pierwsza i w normalnej pracy w zupełności
wystarcza. Problem pojawia się przy **awarii ładowarki**: przebity tranzystor
klucza zwiera wejście z wyjściem i na bank idzie pełne napięcie alternatora
(14,5 V, przy uszkodzonym regulatorze nawet 16 V+) bez żadnego ograniczenia.
Bank AGM w takim reżimie gotuje się w kilkanaście godzin.

Rozłącznik nadnapięciowy jest **niezależnym urządzeniem**, które mierzy
napięcie na banku i rozwiera obwód ładowania, gdy przekroczy próg.

### 6.2 Nastawy

| Parametr | Wartość | Uzasadnienie |
|----------|---------|--------------|
| Próg rozwarcia | **15,30 V** | powyżej katalogowego maksimum 15,0 V, poniżej napięcia, przy którym AGM intensywnie odgazowuje |
| Próg powrotu | **14,00 V** | poniżej absorpcji — nie klapkuje w kółko |
| Zwłoka zadziałania | 1–3 s | ignoruje krótkie piki, reaguje na realne przeładowanie |
| Obciążalność styków | ≥ 10 A | musi przenieść prąd ładowania z zapasem |

### 6.3 Realizacja

**Moduł programowalnego przekaźnika napięciowego** (na rynku jako „DC 6–30 V
programmable voltage control relay", np. XY-WJ01 lub odpowiednik z wyświetlaczem):
ustawiasz próg załączenia i wyłączenia, moduł steruje przekaźnikiem. Koszt
40–80 PLN.

> **Sprawdź kierunek działania.** Większość tanich modułów jest fabrycznie
> skonfigurowana jako ochrona **podnapięciowa** (załącz powyżej progu).
> Potrzebujesz trybu odwrotnego: **rozwarcie powyżej progu**. Część modułów
> ma to jako tryb pracy (F-1/F-2), część wymaga użycia styku NC zamiast NO.
> Zweryfikuj na stole zasilaczem laboratoryjnym, zanim wepniesz to w auto.

Jeżeli styki modułu nie wyrabiają prądowo — steruj nimi **przekaźnik
mocy 30 A** (ten sam typ, co przekaźnik zapłonu).

**Wariant A i tak potrzebuje tej warstwy.** Ładowarka Victron/Redarc jest
bardzo niezawodna, ale nie jest niezniszczalna — a komplet pięciu HR1221W
jest wielokrotnie droższy niż moduł za 60 PLN.

### 6.4 Kontrola „na sucho"

Po zamontowaniu, przed podłączeniem banku:

1. Zasilacz laboratoryjny na wejście modułu, wolno podnoś napięcie.
2. Przy 15,30 V ± 0,05 V przekaźnik musi **rozewrzeć**.
3. Obniżaj — przy 14,00 V musi **zewrzeć z powrotem**.
4. Powtórz trzy razy; próg nie może pływać o więcej niż 0,05 V.

---

## 7. LVD — moduł XH-M609

Druga strona medalu: bank nie może zejść zbyt nisko, bo siarczanowanie płyt
przy głębokim rozładowaniu jest równie nieodwracalne, co przeładowanie.
Tę rolę pełni posiadany **XH-M609**.

### 7.1 Dane modułu

| Parametr | Wartość katalogowa |
|----------|-------------------|
| Napięcie zasilania | 12–36 V DC |
| Przekaźnik | **20 A / 14 V DC** |
| Dokładność nastawy | 0,1 V |
| Pobór własny | **< 1,5 W** (wartość maksymalna dla całego zakresu) |
| Zaciski | VIN + / VIN − (od banku), VOUT + / VOUT − (do obciążenia) |
| Obsługa | wyświetlacz LED + dwa przyciski (próg i histereza) |

### 7.2 Nastawy

| Parametr | Wartość |
|----------|---------|
| Próg odcięcia | **11,00 V** |
| Próg powrotu | **12,60 V** |

**Histereza jest obowiązkowa.** Po odcięciu obciążenia napięcie banku
„odbija" o 0,3–0,5 V. Bez histerezy moduł zacznie klapkować z częstotliwością
kilku Hz i w krótkim czasie spali styki. Próg powrotu 12,60 V oznacza, że
szyna wróci dopiero po realnym doładowaniu z alternatora.

Procedura: krótkie naciśnięcie przycisku pokazuje bieżący próg, długie
przytrzymanie wprowadza w tryb edycji (wartość zaczyna migać), przyciskami
„+" i „−" ustawiasz wartość. Drugi przycisk ustawia histerezę (próg powrotu).

### 7.3 Trzy rzeczy do sprawdzenia na stole

Przed zabudową, na zasilaczu laboratoryjnym:

**1. Czy moduł działa przy 11 V.** Katalogowy zakres zasilania to **12–36 V**,
a próg odcięcia ustawiamy na **11,00 V** — czyli poniżej deklarowanego
minimum. Wersje tego modułu różnią się (część listingów podaje 6–60 V),
więc trzeba to zwyczajnie sprawdzić: zjedź napięciem do 11,0 V i zobacz, czy
przekaźnik rozwiera się czysto, bez drgania styku i bez resetów wyświetlacza.

> Jeżeli w okolicy 11 V moduł zachowuje się niepewnie — **podnieś próg do
> 11,5 V**. Dla AGM przy poborze rzędu 100 mA to nadal głębokie rozładowanie,
> więc ochrona zostaje zachowana, a moduł pracuje w swoim zakresie.

**2. Który biegun przełącza przekaźnik.** Musi przerywać **plus**. Gdyby
przerywał masę, rozspójniłoby to topologię jednego punktu gwiazdowego —
obciążenia miałyby masę tylko przez ten przekaźnik. Sprawdź omomierzem
między VIN− a VOUT−: powinno być zwarcie niezależnie od stanu przekaźnika.

**3. Ile moduł sam pobiera.** Katalogowe „< 1,5 W" to maksimum dla całego
zakresu 12–36 V. Przy 12 V realny pobór (przekaźnik + wyświetlacz + logika)
jest zwykle znacznie niższy, ale **to trzeba zmierzyć** — amperomierz
szeregowo w linii VIN+, moduł w stanie załączonym. Wynik wpisz do budżetu
z §9; ma bezpośredni wpływ na czas postoju.

### 7.4 Obciążalność — czy 20 A wystarczy

Tak, z dwukrotnym zapasem. Przez LVD przechodzi:

| Odbiornik | Prąd szczytowy |
|-----------|---------------|
| Step-up (wejście przy 11 V) | do 4,5 A |
| Hub USB z peryferiami | ~1,0 A |
| Buck paneli wyświetlaczy | ~1,5 A |
| Domena A (logika + cewki) | ~0,5 A |
| **Razem** | **~7,5 A** |

Kluczowe jest to, że **wzmacniacze idą osobną gałęzią** prosto z akumulatora
rozruchowego (§2). Gdyby szły przez LVD, ich szczyty 15–20 A przekroczyłyby
przekaźnik 20 A.

Bezpiecznik między bankiem a VIN+: **15 A** (1,5 × prąd szczytowy, zgodnie
z zaleceniem producenta modułu).

### 7.5 Co odcina LVD

Całą szynę buforowaną. Logika też przestaje działać (pilot szyb i BLE
bagażnika nie odpowiadają), ale to celowe: bank przetrwa i naładuje się przy
następnym uruchomieniu silnika. Alternatywa — pozwolić Nano dojechać bank
do 9 V — kończy się wymianą kompletu pakietów.

Moduł montuj **za bankiem, przed rozgałęzieniem odbiorników** — patrz
[`power_buffered_m910q.svg`](../schematics/power_buffered_m910q.svg).

> **XH-M609 nie zastąpi blokady przeładowania z §6.** To moduł ochrony
> **podnapięciowej** — rozłącza *poniżej* progu. Warstwa 2 potrzebuje logiki
> odwrotnej (rozwarcie *powyżej* 15,3 V), więc pozostaje osobnym modułem.

---

## 8. Bezpieczniki, przekroje, masa

### 8.1 Bezpieczniki

| Bezpiecznik | Wartość | Umiejscowienie |
|-------------|---------|----------------|
| Główny | 30 A | **maks. 30 cm od klemy „+"** akumulatora rozruchowego |
| Na pakiet banku | 10 A × 5 | na zacisku F2 „+" każdego pakietu |
| Wyjście step-up | 5 A | między przetwornicą a wtykiem M910q |
| Odgałęzienie logiki (Nano, HM-10, RXB6) | 3 A | przed buckiem 12 → 5 V |
| Odgałęzienie wyświetlaczy | 3 A | przed buckiem 12 → 5 V wyświetlaczy |
| Gałąź wzmacniacza | wg karty modułu (20–30 A) | osobno, przy klemie akumulatora rozruchowego |

Bezpiecznik główny **przy klemie**, nie przy urządzeniu — zwarcie przewodu
o karoserię w połowie trasy ma być przerwane przy źródle, inaczej cały
przewód staje się grzałką. Wkładki nożowe ATO/ATC w listwie dystrybucyjnej
z pokrywą, w miejscu dostępnym bez demontażu deski rozdzielczej.

### 8.2 Przekroje przewodów

Dla trasy ok. 3 m (komora silnika → deska rozdzielcza) przy spadku < 3 %:

| Odcinek | Prąd | Przekrój |
|---------|------|----------|
| Akumulator → bezpiecznik → przekaźnik/ładowarka | do 30 A | **6 mm²** |
| Ładowarka → bank | do 6 A | 2,5 mm² |
| Pakiet HR1221W → szyna | do 10 A | 1,5 mm² |
| Szyna → LVD → przekaźnik → step-up | do 7 A | 2,5 mm² |
| Step-up → M910q | 3,5 A @ 19 V | 1,5 mm² |
| Odgałęzienie logiki (Nano, HM-10, RXB6) | < 1 A | 0,75 mm² |
| Gałąź wzmacniacza | wg karty modułu | 6 mm² (trasa ~4 m do bagażnika) |
| Masa do nadwozia | — | **6 mm²** |

Przewody samochodowe (FLRY/FLY), nie instalacyjne YDY — potrzebna jest
linka, nie drut, i izolacja odporna na temperaturę i oleje.

### 8.3 Masa

- **jeden punkt masy** dla całego head unitu — gwiazda, nie łańcuszek,
- śruba do gołego metalu nadwozia, powierzchnia oczyszczona ze szpachli
  i lakieru, po dokręceniu zabezpieczona wazeliną techniczną,
- masa banku, masa M910q, masa Arduino i masa audio schodzą się **w tym
  jednym punkcie**,
- masa wzmacniacza osobno, blisko wzmacniacza — inaczej dostaniesz pętlę
  masy i przydźwięk alternatora w głośnikach.

### 8.4 Praktyka montażowa

- przejścia przez blachę **zawsze** przez przelotkę gumową,
- wiązki w peszlu/oplocie, mocowane co 30 cm,
- konektory zaciskane właściwą zaciskarką i dodatkowo koszulka
  termokurczliwa z klejem; lutowanie w miejscach narażonych na wibracje
  łamie się przy wyjściu z lutu,
- zapas długości przy każdym urządzeniu (pętla serwisowa),
- **wyłącznik główny masy** banku (rozłącznik 100 A) — bardzo ułatwia
  serwis i jest wymagany, jeśli auto stanie na dłużej.

---

## 9. Budżet energetyczny i czas postoju

### 9.1 Pobór odbiorników stałych (bez komputera)

| Element | Pobór |
|---------|-------|
| Arduino Nano #1 (output controller) | ~25 mA |
| HM-10 BLE (nasłuch) | ~15 mA |
| RXB6 433 MHz (nasłuch) | ~5 mA |
| Moduł przekaźników (spoczynek) | ~10 mA |
| Straty przetwornicy buck | ~5 mA |
| **Podsuma — logika i przekaźniki** | **~60 mA (0,7 W)** |
| **XH-M609 (LVD)** | **do zmierzenia — patrz §7.3** |

> **Pobór własny LVD jest częścią budżetu postoju.** XH-M609 ma wyświetlacz
> LED i przekaźnik trzymany w stanie załączonym, więc nie jest to element
> pomijalny — katalogowe „< 1,5 W" przy 12 V oznaczałoby aż 125 mA, czyli
> **dwukrotnie więcej niż cała reszta logiki**. Realny pobór przy 12 V jest
> zwykle znacznie niższy (spec obejmuje cały zakres do 36 V), ale dopóki nie
> zmierzysz, nie wiesz, w której kolumnie tabeli poniżej jesteś.

### 9.2 Czas postoju

Czas zależy od tego, ile pobiera XH-M609 — dlatego tabela jest rozpisana
wg **sumarycznego poboru**. Logika i przekaźniki to stałe 60 mA; reszta to
moduł LVD.

**Bank 5 pakietów — 25,5 Ah:**

| Pobór całkowity | XH-M609 | Do 30 % DoD | Do 50 % DoD | Do progu LVD |
|-----------------|---------|-------------|-------------|--------------|
| 80 mA | 20 mA | ~4,0 dnia | ~6,6 dnia | ~10,0 dnia |
| 100 mA | 40 mA | ~3,2 dnia | ~5,3 dnia | ~8,0 dnia |
| 130 mA | 70 mA | ~2,5 dnia | ~4,1 dnia | ~6,1 dnia |
| 185 mA | 125 mA (spec max) | ~1,7 dnia | ~2,9 dnia | ~4,3 dnia |

**Bank 8 pakietów — 40,8 Ah** (masz osiem, więc to realna opcja):

| Pobór całkowity | Do 30 % DoD | Do 50 % DoD | Do progu LVD |
|-----------------|-------------|-------------|--------------|
| 80 mA | ~6,4 dnia | ~10,6 dnia | ~15,9 dnia |
| 100 mA | ~5,1 dnia | ~8,5 dnia | ~12,8 dnia |
| 130 mA | ~3,9 dnia | ~6,5 dnia | ~9,8 dnia |
| 185 mA | ~2,8 dnia | ~4,6 dnia | ~6,9 dnia |

Kolumna 30 % DoD jest tu dlatego, że HR1221W to seria buforowa (UPS), a nie
trakcyjna — płytsze rozładowanie wyraźnie wydłuża jej życie. Przy okazjonalnym
dłuższym postoju 50 % DoD jest w porządku; jako **rutyna** lepiej trzymać 30 %.

> **Jeżeli pomiar z §7.3 wypadnie powyżej ~40 mA**, najprostszą reakcją jest
> użycie **wszystkich ośmiu pakietów zamiast pięciu**. Masz je, a 40,8 Ah
> cofa czas postoju mniej więcej tam, gdzie był przy 25,5 Ah i niskim poborze
> LVD. Kosztem jest 14,4 kg zamiast 9,0 kg i więcej miejsca pod fotelem.
>
> Drugi kierunek to wymiana LVD na moduł bez wyświetlacza (prosty komparator
> z przekaźnikiem pobiera 5–10 mA), ale skoro XH-M609 już jest — najpierw
> zmierz, a decyduj potem.

> **Korekta wobec starszych notatek.** `docs/X86_PLATFORM_SETUP.md` § 2.3
> i `10-power-suspend.html` podają dla banku 25 Ah „~17 dni" z adnotacją
> „ograniczone do 50 % DoD". Te dwie rzeczy się wykluczają: 25 Ah / 0,060 A
> = 417 h = 17,4 dnia to **pełne rozładowanie do zera**. Przy realnym
> ograniczeniu do 50 % DoD i faktycznej pojemności 25,5 Ah wychodzi
> 12,75 Ah / 0,060 A = 212 h = **8,9 dnia**. Tabela powyżej rozdziela
> wszystkie trzy przypadki.

Samorozładowanie HR1221W (> 75 % pojemności po 6 miesiącach @ 25 °C, czyli
≤ 4 %/miesiąc) odpowiada ok. **1,4 mA** przy banku 25,5 Ah — wobec 60 mA
logiki jest pomijalne. W upale rośnie kilkukrotnie, ale nadal nie zmienia
obrazu.

Kolumna „do progu LVD" zakłada zejście do ~75 % DoD (11,0 V pod bardzo
lekkim obciążeniem). Jest osiągalna, ale każde takie zejście kosztuje
żywotność — traktuj ją jako rezerwę awaryjną, nie tryb normalnej pracy.

### 9.3 Budzenie RTC

Jeśli włączysz budzenie M910q z RTC (np. co 15 min na ping pozycji), dolicz
ok. 5 Ah tygodniowo — to **mniej więcej połowi** powyższe czasy. Przy dłuższym
postoju wyłącz je z UI.

### 9.4 Ładowanie po postoju

Bank rozładowany do 50 % (12,75 Ah do uzupełnienia) przy prądzie ładowania
6 A potrzebuje ~2,2 h w fazie CC plus ~2 h absorpcji — czyli **około
4–5 godzin jazdy**. Podniesienie prądu do katalogowego sufitu 10,5 A skraca
fazę CC do ~1,3 h, ale absorpcja i tak trwa swoje. Krótkie przejazdy po mieście nie doładują banku po
dłuższym postoju; jeśli tak wygląda Twój profil użytkowania, rozważ
ładowarkę sieciową na czas parkowania w garażu.

---

## 10. Lista zakupowa

> Ta lista dotyczy **wersji docelowej**. Budujesz wariant testowy?
> Wszystko w jednej tabeli: [`LISTA_ZAKUPOWA.md`](LISTA_ZAKUPOWA.md).

### 10.1 Już posiadane

| Element | Rola w torze | Uwaga |
|---------|--------------|-------|
| **XL6019** — moduł step-up | 12 V → 19,5 V dla M910q | ok. **45 W ciągle**, nie 65 W — wymaga ograniczenia poboru CPU, §3.2 i §3.5a |
| **XH-M609** — moduł ochrony | **LVD** (warstwa 3), 11,00 / 12,60 V | przekaźnik 20 A wystarcza; zmierz pobór własny, §7.3 |
| **CSB HR1221W F2** × 8 (12 V / 5,1 Ah AGM) | bank buforowy | użyj 5 (25,5 Ah) albo 8 (40,8 Ah) — decyzja po pomiarze z §7.3 |
| Lenovo ThinkCentre M910q Tiny | komputer | |

### 10.2 Do dokupienia — obowiązkowe

| # | Element | Specyfikacja | Szt. | Cena (PLN) |
|---|---------|--------------|------|-----------|
| 1 | **Ładowarka DC-DC** *(wariant A)* | Victron Orion-Tr Smart 12/12-18 lub odpowiednik z presetem **AGM** | 1 | 800–1000 |
| | *albo:* przekaźnik + dioda + moduł CC-CV boost *(wariant B)* | przekaźnik 30 A SPDT + **MBR2545CT** na radiatorze · boost: **„900 W 15 A" z wyświetlaczem** albo **SZBK07** — pełne zestawienie w §5.3a i §5.3c | 1+1+1 | 70–180 |
| 2 | **Rozłącznik nadnapięciowy** | programowalny przekaźnik napięciowy, próg 15,3 V / powrót 14,0 V | 1 | 40–80 |
| 3 | ~~Moduł LVD~~ | **posiadany — XH-M609** | — | 0 |
| 4 | **Przekaźnik zapłonu** | Bosch 12 V / 30 A SPDT + podstawka | 1 | 15–25 |
| 5 | **Przekaźnik mocy** (do poz. 2, jeśli styki modułu za słabe) | 12 V / 30 A + podstawka | 1 | 15–25 |
| 6 | **Listwa dystrybucyjna bezpiecznikowa** | 6–8 obwodów ATO/ATC, z pokrywą | 1 | 40–70 |
| 7 | **Bezpiecznik główny + oprawka** | 30 A, oprawka do montażu przy klemie | 1 | 15–25 |
| 8 | **Bezpieczniki inline** | 10 A × 5–8 (pakiety) + oprawki, oraz 15 A przed VIN+ modułu XH-M609 | 6–9 | 20–35 |
| 9 | **Bezpieczniki nożowe** | 5 A, 3 A × 2, 20 A + zapas | kpl. | 10–15 |
| 10 | **Buck 12 → 5 V** (logika) | LM2596, min. 1 A | 1 | 5–10 |
| 11 | **Buck 12 → 5 V** (wyświetlacze) | MP1584 / MP2307, min. 3 A — potrzebny przez **PWM podświetlenia**, patrz niżej | 1 | 5–15 |
| 12 | **Dioda TVS** | 1.5KE33CA lub SMCJ26CA | 2 | 5–10 |
| 13 | **Kondensator elektrolityczny** | 470 µF / 35 V, low-ESR, 105 °C | 2 | 5–10 |
| 14 | **Dioda gaszeniowa** | 1N4007 (na cewki przekaźników) | 5 | 2–5 |
| 15 | **Przewód 6 mm²** | FLRY, czerwony 4 m + czarny 2 m | — | 60–90 |
| 16 | **Przewód 2,5 mm²** | FLRY, czerwony + czarny, po 3 m | — | 25–40 |
| 17 | **Przewód 1,5 mm²** | FLRY, czerwony + czarny, po 3 m | — | 15–25 |
| 18 | **Przewód 0,75 mm²** | FLRY, kilka kolorów, po 2 m | — | 15–25 |
| 19 | **Konektory oczkowe M6/M8** | do 6 mm², zaciskane | 10 | 15–25 |
| 20 | **Konektory / tulejki / koszulki** | zestaw, koszulki z klejem | kpl. | 30–50 |
| 21 | **Peszel / oplot + przelotki gumowe** | 5 m peszla + komplet przelotek | kpl. | 25–40 |
| 22 | **Skrzynka / wspornik na bank + pasy** | na 5 pakietów, mocowanie do nadwozia | 1 | 60–120 |
| 23 | **Rozłącznik masy** | 100 A, kluczykowy lub pokrętło | 1 | 40–70 |
| 24 | **Radiator + wentylator 40 mm** | do XL6019 — przy 45 W obowiązkowe | kpl. | 20–35 |
| 24a | **Kondensator wyjściowy** | 470 µF / 35 V low-ESR na wyjście XL6019 | 1 | 3–6 |
| 24b | **Termistor NTC** | 5 Ω / 5 A, ogranicznik prądu rozruchowego (tylko jeśli §3.2b) | 1 | 3–6 |
| | | | **Razem wariant A** | **~1280–1870 PLN** |
| | | | **Razem wariant B** | **~530–1030 PLN** |

Kwoty są niższe niż w pierwszej wersji listy, bo moduł LVD i przetwornica
step-up są już na stanie.

### 10.3 Do dokupienia — zalecane

| # | Element | Po co | Cena (PLN) |
|---|---------|-------|-----------|
| 25 | **Czujnik NTC 10 kΩ** | kompensacja temperaturowa (wariant B) | 5–10 |
| 26 | **Woltomierz/amperomierz z bocznikiem 50 A** | podgląd stanu banku bez multimetru | 40–70 |
| 27 | **Multimetr z pomiarem prądu DC 10 A** | pomiary przy uruchomieniu i serwisie | 80–200 |
| 28 | **Ładowarka sieciowa AGM** | doładowanie w garażu przy krótkich przejazdach | 150–300 |
| 29 | **Zaciskarka do konektorów** | zaciski niepewne to najczęstsza usterka instalacji | 60–150 |

### 10.4 Czego **nie** kupować

| Element | Dlaczego |
|---------|----------|
| Moduł buck XL4016 jako ładowarka | nie podniesie napięcia do absorpcji — patrz §5.1 |
| Drugi XL6019 „równolegle dla mocy” | te moduły nie dzielą obciążenia — patrz §3.2 |
| Dioda krzemowa (1N5408 itp.) zamiast Schottky | spadek 0,7–1,0 V zjada całą rezerwę napięcia |
| „Uniwersalna" końcówka do M910q | pasowanie i pin ID to loteria — patrz §3.3 |
| Ładowarka/BMS do LiFePO₄ lub Li-ion | zupełnie inne napięcia — zniszczy bank AGM |
| Akumulatory rozruchowe zamiast HR1221W | nie znoszą pracy cyklicznej, umrą w kilka miesięcy |
| Ładowarka z presetem GEL | profil żelowy jest ~0,2–0,3 V niższy — bank AGM nigdy nie dojdzie do pełna |

---

## 11. Procedura pierwszego uruchomienia

Kolejność jest istotna — każdy etap kończy się pomiarem, a bank podłączasz
dopiero, gdy wszystko przed nim jest zweryfikowane.

### Etap 1 — nastawy na stole (bez auta, bez banku)

```
XL6019 (step-up)
[ ] Wyjście 19,5 V bez obciążenia (multimetr)
[ ] Limit poboru pakietu CPU ustawiony na M910q (§3.5a) PRZED testem
[ ] Test obciążeniowy wg §3.4 — 10 min stress-ng, napięcie ≥ 19,0 V
[ ] Powtórka testu przy wejściu 11,0 V (najgorszy przypadek)
[ ] Prąd wejściowy nie przekracza 4,5 A
[ ] Temperatura cewki i układu po 10 min < 85 °C
[ ] Brak trybu „czkawki" przy załączaniu (jeśli jest — §3.2b)
[ ] Radiator i wentylator 40 mm zamontowane

XH-M609 (LVD)
[ ] Próg odcięcia 11,00 V, próg powrotu 12,60 V
[ ] Moduł pracuje stabilnie przy 11,0 V — bez drgania styku (§7.3 pkt 1)
[ ] Omomierzem sprawdzone, że przełącza PLUS, nie masę (§7.3 pkt 2)
[ ] Zmierzony pobór własny przy 12 V, wpisany do budżetu §9
[ ] Decyzja: 5 czy 8 pakietów w banku — na podstawie powyższego pomiaru
[ ] Bezpiecznik 15 A przed zaciskiem VIN+

Pozostałe
[ ] Ładowarka: CV 14,40 V (lub 13,80 V w wariancie B bez kompensacji)
[ ] Ładowarka: limit prądu CC 6,0 A (sufit katalogowy 10,5 A dla 5 pakietów)
[ ] Rozłącznik nadnapięciowy: rozwarcie 15,30 V, powrót 14,00 V (§6.4)
[ ] Buck logiki: wyjście 5,0 V
[ ] Buck wyświetlaczy: wyjście 5,0 V
```

### Etap 2 — bank

```
[ ] Pomiar napięcia spoczynkowego każdego pakietu osobno
    (rozrzut > 0,2 V = pakiet do odrzucenia)
[ ] Doładowanie wszystkich pakietów do tego samego napięcia PRZED łączeniem
[ ] Bezpiecznik 10 A na „+" każdego pakietu
[ ] Łączenie równoległe — jednakowe przewody, szyna/mostek
[ ] Pomiar napięcia banku po połączeniu
[ ] Czujnik NTC przyklejony do środkowego pakietu
```

### Etap 3 — montaż w aucie, bez podłączenia do akumulatora

```
[ ] Skrzynka banku zamocowana i przypięta pasami
[ ] Punkt masy przygotowany (goły metal, śruba, wazelina)
[ ] Trasy przewodów przepięte, przelotki w blachach
[ ] Listwa bezpiecznikowa zamontowana w dostępnym miejscu
[ ] Rozłącznik masy banku w pozycji ROZWARTY
[ ] Wszystkie połączenia sprawdzone wizualnie i pociągnięciem
```

### Etap 4 — pierwsze załączenie

```
[ ] Bezpiecznik główny 30 A WYJĘTY
[ ] Podłączenie masy do nadwozia
[ ] Podłączenie „+" do klemy akumulatora rozruchowego
[ ] Włożenie bezpiecznika głównego — obserwuj, czy nic nie iskrzy/grzeje
[ ] Pomiar: napięcie na szynie buforowanej (silnik zgaszony)
[ ] Rozłącznik masy banku ZWARTY
[ ] Pomiar: napięcie banku = napięcie szyny
[ ] Pomiar prądu spoczynkowego logiki → oczekiwane ~60 mA
    (rozbieżność > 100 mA = szukaj upływu, NIE jedź dalej)
```

### Etap 5 — silnik i ładowanie

```
[ ] Uruchomienie silnika
[ ] Pomiar: napięcie na akumulatorze rozruchowym (13,8–14,5 V)
[ ] Pomiar: przekaźnik ładowania zwarty / ładowarka aktywna
[ ] Pomiar: prąd ładowania banku ≤ 6 A
[ ] Pomiar: napięcie banku rośnie, nie przekracza 14,40 V (wg kompensacji temp.)
[ ] Po 30 min: temperatura pakietów ręką — letnie, nie gorące
[ ] Zgaszenie silnika → przekaźnik ładowania rozwiera się, prąd spada do zera
[ ] Pomiar: brak prądu z banku do akumulatora rozruchowego
```

### Etap 6 — komputer i sterowanie zapłonem

```
[ ] Przekręcenie kluczyka na ACC → przekaźnik zapłonu zwiera
[ ] Pomiar: 19,5 V na wtyku M910q
[ ] M910q startuje, dashboard pojawia się na wyświetlaczu głównym
[ ] Rozruch silnika przy działającym BCM → komputer NIE resetuje się
    (to jest test, dla którego cały ten bufor powstał)
[ ] Wyłączenie zapłonu → Arduino daje impuls, M910q schodzi do S3
[ ] Pomiar poboru w S3 — oczekiwane 400–550 mA (§2.1)
[ ] Po 2 h → impuls 5 s, maszyna gaśnie, pobór spada do 100–200 mA
[ ] Domena A dalej działa — test pilota 433 MHz i BLE bagażnika
```

### Etap 7 — próba postoju

```
[ ] Auto zaparkowane na 48 h bez uruchamiania
[ ] Pomiar napięcia banku przed i po
[ ] Spadek zgodny z ~60 mA (dla 25,5 Ah: ok. 2,9 Ah = ~0,2–0,3 V)
[ ] Akumulator rozruchowy bez zmian — auto odpala normalnie
```

---

## 12. Serwis i kontrola okresowa

| Częstotliwość | Czynność | Kryterium |
|---------------|----------|-----------|
| Co miesiąc | Napięcie banku po nocy postoju | > 12,4 V |
| Co 3 miesiące | Napięcie każdego pakietu osobno | rozrzut < 0,2 V |
| Co 3 miesiące | Dokręcenie połączeń na szynie i biegunach | bez luzu |
| Co 6 miesięcy | Napięcie ładowania przy pracującym silniku | ≤ 14,40 V (lub wg kompensacji) |
| Co 6 miesięcy | Prąd spoczynkowy logiki | ~60 mA ± 20 % |
| Co 12 miesięcy | Test pojemności banku (rozładowanie kontrolowane) | > 70 % pojemności znamionowej |
| Co 12 miesięcy | Kontrola przewodów: przetarcia, korozja konektorów | bez zmian |

**Objawy zużycia banku:** szybszy spadek napięcia na postoju, dłuższa faza
CC przy ładowaniu, wybrzuszona obudowa pakietu (natychmiastowa wymiana),
grzanie się pojedynczego pakietu przy ładowaniu.

Żywotność katalogowa HR1221W w pracy buforowej to **3–5 lat przy 25 °C**,
i to temperatura montażu decyduje, gdzie w tym przedziale wylądujesz (§4.6).
Przy przeładowywaniu albo braku kompensacji temperaturowej — **1–2 sezony**.

---

## 13. Znane rozbieżności i luki

Rzeczy, które wyszły przy porządkowaniu dokumentacji. Nic z tego nie blokuje
wdrożenia, ale warto wiedzieć.

### 13.1 Limit prądu ładowania w starszej dokumentacji

`docs/X86_PLATFORM_SETUP.md` § 2.2 i `docs/x86-production/10-power-suspend.html`
podają 14,4 V absorpcji, 13,8 V float i limit prądu **15–20 A**.

- **Napięcia są prawidłowe** dla CSB HR1221W (AGM): katalog dopuszcza
  14,4–15,0 V cyklicznie i 13,5–13,8 V buforowo.
- **Limit prądu jest za wysoki.** Karta katalogowa CSB podaje **2,1 A na
  pakiet**, czyli 10,5 A dla banku pięciu — nie 15–20 A.

Brakuje tam też kompensacji temperaturowej, która dla tej serii ma **dwa różne
współczynniki** (−18 mV/°C float, −30 mV/°C cykl) — patrz §4.5.

### 13.2 Buck jako ładowarka

Ta sama dokumentacja proponuje moduł buck XL4016 między diodą a bankiem.
Topologia buck nie jest w stanie osiągnąć napięcia absorpcji — patrz §5.1.
Użyj wariantu A albo B z §5.

### 13.3 Czas postoju „17 dni"

Liczba pochodzi z pełnego rozładowania, mimo adnotacji o 50 % DoD.
Poprawione wartości w §9.2.

### 13.4 Moduł `battery` nie monitoruje banku buforowego

`src/power/battery.py` jest napisany pod **ogniwo Li-ion 18650**:

```python
FULL_V = 4.2
NOMINAL_V = 3.7
LOW_V = 3.3
CRITICAL_V = 3.0
```

Moduł nasłuchuje zdarzenia `arduino.battery_voltage`, którego **żaden
z trzech sketchy Arduino w repozytorium nie publikuje**. W efekcie
`modules.battery: true` w `config/bcm_config.yaml` włącza kod, który nigdy
nic nie policzy.

Żeby monitoring banku faktycznie działał, potrzeba trzech rzeczy:

1. **Dzielnik napięcia** na wejściu ADC Arduino (sensor hub): 12 V → poniżej
   5 V, np. 100 kΩ / 27 kΩ daje przy 15 V ok. 3,2 V — bezpiecznie w zakresie.
   Rezystory 1 %, kondensator 100 nF na wyjściu dzielnika.
2. **Publikacja odczytu** z `arduino/sensor_hub/sensor_hub.ino` jako
   `BATT:<napięcie>`, mapowana na `arduino.battery_voltage`.
3. **Progi dla banku 12 V** zamiast ogniwa Li-ion:

   | Stała | Wartość dla banku AGM 12 V |
   |-------|---------------------------|
   | `FULL_V` | 12,85 |
   | `NOMINAL_V` | 12,40 |
   | `LOW_V` | 11,80 |
   | `CRITICAL_V` | 11,20 |

   (`CRITICAL_V` powyżej progu LVD 11,0 V, żeby BCM zdążył zareagować,
   zanim LVD odetnie zasilanie.)

Do czasu wykonania tych trzech kroków stan banku kontroluj woltomierzem
z listy zalecanych zakupów (poz. 26).

---

### 13.5 Gałąź audio — gotowy wzmacniacz

Wcześniejsze wersje dokumentacji zakładały samodzielnie zbudowany tor
TDA7388 + TDA2050. Projekt używa teraz **gotowego wzmacniacza samochodowego**,
co dla zasilania buforowanego zmienia trzy rzeczy:

| | Poprzednio (DIY TDA) | Teraz (gotowy moduł) |
|---|---|---|
| Bezpiecznik gałęzi | 20 A | **wg karty modułu**, zwykle 20–30 A |
| Przekrój przewodu | 4 mm² | **6 mm²** (spadek na trasie ~4 m do bagażnika) |
| Sygnał REM | przez rezystor 1 kΩ | **wprost z zacisku 87** — wejście REM jest wysokoomowe |

Sama zasada nie zmienia się wcale: gałąź audio idzie prosto z akumulatora
rozruchowego, ma własną masę lokalną i **nie dotyka banku, LVD ani listwy
dystrybucyjnej**.

Dokumenty źródłowe (`x86-production/*.html`, `bcm_v85_docs.html`) wciąż
opisują wariant DIY — zostają jako referencja historyczna.

### 13.6 Ograniczenia wynikające z posiadanych modułów

Dwa moduły są już kupione i projekt jest dopasowany pod nie, a nie odwrotnie.
Wynikają z tego dwa realne ograniczenia:

| Moduł | Ograniczenie | Konsekwencja |
|-------|--------------|--------------|
| **XL6019** | limit prądu klucza 5 A → ok. **45 W** wyjścia, nie 65 W | konieczny limit poboru pakietu CPU (§3.5a); bez niego pełne obciążenie czterech wątków wyjdzie poza możliwości modułu |
| **XH-M609** | pobór własny do 125 mA wg spec + zakres zasilania od 12 V | wchodzi wprost w budżet postoju (§9) i wymaga sprawdzenia pracy przy progu 11 V (§7.3) |

Żadne z nich nie dyskwalifikuje modułu — oba są do obejścia, odpowiednio
konfiguracją systemu i doborem liczby pakietów. Trzeba tylko o nich wiedzieć
przed zabudową, a nie po.

---

## Powiązane dokumenty

| Dokument | Zakres |
|----------|--------|
| [`WDROZENIE_M910Q.md`](WDROZENIE_M910Q.md) | pełne wdrożenie: sprzęt, BIOS, OS, usługi, odbiór |
| [`X86_PLATFORM_SETUP.md`](X86_PLATFORM_SETUP.md) | referencja krok-po-kroku (EN) — pamiętaj o §13 |
| [`x86-production/10-power-suspend.html`](x86-production/10-power-suspend.html) | zasilanie + S3 w wersji ilustrowanej |
| [`x86-production/02-assembly.html`](x86-production/02-assembly.html) | montaż mechaniczny, layout USB |
| [`ARDUINO_SETUP_GUIDE.md`](ARDUINO_SETUP_GUIDE.md) | okablowanie trzech płytek Arduino, sygnały pojazdu |
| [`SCHEMATY_POLACZEN.md`](SCHEMATY_POLACZEN.md) | tabele połączeń, przekroje, bezpieczniki, kolejność montażu |
| [`../schematics/README.md`](../schematics/README.md) | indeks schematów |
