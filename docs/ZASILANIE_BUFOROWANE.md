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
| **Jakość napięcia** | Instalacja auta to śmietnik EMI: przepięcia od cewek, load dump z alternatora, tętnienia. | Bank o pojemności 35,7 Ah to gigantyczny kondensator — wygładza wszystko, co jest za nim. |

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

Bank ma **7 pakietów (35,7 Ah)**. Do 50 % DoD zostaje **17,85 Ah**
użytecznych, a w reżimie rutynowym 30 % DoD — **10,71 Ah**.

| Stan | Co pobiera | Pobór z banku | 7 pakietów (35,7 Ah) |
|------|-----------|---------------|----------------------|
| **Praca** | wszystko | 10–55 W (**3,5 A z banku**) | ~5,1 h przy zgaszonym silniku |
| **S3** | M910q w S3 + Arduino + LVD | **200–460 mA** | **1,6–3,7 dnia** |
| **Wyłączony** (impuls 5 s) | przetwornice + Arduino + LVD | **50–150 mA** | **5,0–14,9 dnia** |

> **Pobór w S3 jest zmierzony, nie oszacowany.** Wyświetlacz gaśnie razem
> z komputerem, bo M910q **odcina zasilanie portów USB w S3** — z szyny
> ciągną wtedy tylko sam komputer i Arduino. To także przesądza dwie rzeczy:
> „Wake on USB" jest tu bezużyteczne (port jest martwy), a Arduino **musi**
> mieć własne 5 V z MP1584, inaczej nie ma czym nacisnąć przycisku.

Kolumna czasów jest liczona **prądem, a nie mocą**: pojemność katalogowa C20
razy frakcja DoD, podzielona przez pobór, bez poprawki Peukerta i bez korekty
temperaturowej. Wiersz „Praca" stoi na 3,5 A z banku — tym samym obciążeniu,
na którym opiera się rachunek ładowania w §9.4; widełki 10–55 W opisują pobór
odbiorników, a nie podstawę tego rachunku.

W wierszu **Wyłączony** rozrzut (100 mA) bierze się w całości z **własnego
poboru XH-M609** (20–125 mA wg wersji płytki) — to jedyna liczba warta
zmierzenia multimetrem. W wierszu **S3** jest inaczej: sam M910q w S3 daje
160–320 mA rozrzutu ([`WDROZENIE_TESTOWE.md`](WDROZENIE_TESTOWE.md) §3.1a),
czyli więcej niż LVD. Tam zmierzyć trzeba oba.

Wszystko do 50 % DoD. Wniosek jest praktyczny: **S3 do krótkich postojów,
twarde wyłączenie do długich**. Arduino przełącza między nimi samo — po
2 godzinach zgaszonego zapłonu daje dłuższy impuls i maszyna gaśnie
całkowicie. Powrót to znowu krótki impuls.

> **Siedem pakietów nie zmienia bilansu dobowego.** Kupuje dłuższy postój
> między doładowaniami, ale minimalna dzienna jazda potrzebna do utrzymania
> bilansu zależy od **prądu ładowania**, a nie od pojemności banku — tabela
> w §9.4.

### 2.2 Dlaczego nie przekaźnik odcinający komputer

Wcześniejsze wydanie tej dokumentacji odcinało M910q i wyświetlacze
przekaźnikiem zapłonu („domena B"). Model został **porzucony** — oto
dlaczego:

| | Przekaźnik odcinający | Stałe zasilanie + S3 |
|---|---|---|
| Postój (7 pakietów) | ~9,3 dnia | ~1,6–3,7 dnia w S3, ~5,0–14,9 po wyłączeniu |
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

Powód: 4 × 50 W RMS to w szczytach 20–30 A. Nawet bank siedmiu pakietów
oddałby przy takim prądzie swoje 17,85 Ah użytecznych w niecałą godzinę,
a przede wszystkim **przekroczyłby przekaźnik LVD (20 A)** — i to jest tu
argument rozstrzygający, bo on nie zależy od pojemności banku. Z systemem
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

- spadek na przewodzie step-up → wtyk (przy 3,5 A i 1,5 mm² na pętli 2 × 1 m ≈ 0,08 V — pomijalny),
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
| Prąd wyjściowy przy 19,5 V | 65 / 19,5 = **3,33 A** |
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

Przetwornica przy realnych ~45 W wyjścia (§3.2) i sprawności 88 % rozprasza
**~6 W**; gdyby faktycznie dawała 65 W, byłoby ~9 W. W zamkniętej zabudowie
za deską rozdzielczą, latem, jedno i drugie wystarczy do przegrzania.

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
Siedem pakietów to nadal **12 V**, a nie 84 V; szeregowo nie łączymy niczego.

| Liczba pakietów | Pojemność | Masa | Maks. prąd ładowania | Uwagi |
|-----------------|-----------|------|---------------------|-------|
| 4 | 20,4 Ah | 7,2 kg | 8,4 A | konfiguracja poprzedniego wydania |
| 5 | 25,5 Ah | 9,0 kg | 10,5 A | — |
| 6 | 30,6 Ah | 10,8 kg | 12,6 A | **scenariusz awaryjny** — tyle zostaje po utracie jednego pakietu |
| **7** | **35,7 Ah** | **12,6 kg** | **14,7 A** | **przyjęte** |
| 8 | 40,8 Ah | 14,4 kg | 16,8 A | wszystkie posiadane, zero zapasu |

**Bank ma siedem pakietów.** Wobec czwórki to +75 % pojemności
(20,4 → 35,7 Ah), +5,4 kg masy i sufit ładowania podniesiony z 8,4 na 14,7 A.

Uzasadnienie z poprzedniego wydania — „tyle się mieści" — **przestało
obowiązywać i nie zostało zastąpione innym argumentem o miejscu**. Przy
siedmiu pakietach zmieniają się trzy rzeczy naraz i warto je rozdzielić:

| Co jest ograniczeniem | Przy 4 pakietach | Przy 7 pakietach |
|-----------------------|------------------|------------------|
| Pojemność banku | wiążąca — 10,2 Ah użytecznych do 50 % DoD | przestała być wąskim gardłem: **17,85 Ah** |
| Prąd ładowania | wiązał **akumulator**: 7,5 A z sufitu 8,4 A = 89 % | wiąże **tor ładowania**: 8,0 A z sufitu 14,7 A = 54 % (§6.3) |
| Masa i mocowanie | 7,2 kg, temat marginalny | **12,6 kg** — realne wymaganie konstrukcyjne (§4.7) |

To jest sedno tej rozbudowy: **wąskie gardło przeniosło się z akumulatora na
tor ładowania**. Doładowanie trwa dłużej nie dlatego, że bank jest duży, tylko
dlatego, że CC stoi na 8,0 A (§9.4).

**Zapas.** Z ośmiu posiadanych pakietów siedem idzie do banku, **jeden zostaje
w zapasie**. Trzeba wiedzieć, co to naprawdę znaczy: wobec zasady z §4.3 („nie
dokładaj nowego pakietu do starego banku — wyrównuj cały komplet") jeden
pakiet **nie zastępuje kompletu**, a argument o rotacji zapasu co rok–dwa,
sensowny przy czterech leżakujących sztukach, przy jednej traci podstawę
materiałową. Realny scenariusz awaryjny wygląda inaczej: przy padniętym
pakiecie **schodzisz na sześć** (30,6 Ah, sufit 12,6 A) i jedziesz dalej —
układ tego nawet nie zauważy, bo tor ładowania i tak zamyka się na 8,0 A.
Czasy postoju dla sześciu pakietów są w §9.2.

**Gabaryty.** Pakiet leżący bokiem ma 90 × 70 × 101 mm, więc siedem sztuk
w jednym rzędzie to **490 × 90 × 101 mm** (7 × 70 mm, bez przerw). Zalecany
jest jednak układ **4 + 3 w dwóch rzędach: 280 × 180 × 101 mm**, ze skrzynką
ok. 300 × 200 × 115 mm. Powód jest mechaniczny, nie miejscowy — §4.7.

> **Miejsce montażu trzeba zmierzyć w aucie, zanim cokolwiek kupisz.**
> Ta dokumentacja nie zawiera ani jednego wymiaru przestrzeni pod fotelem
> pasażera, więc nie da się na papierze rozstrzygnąć, czy 300 × 200 × 115 mm
> tam wejdzie. Najbardziej podejrzana jest **wysokość**: 101 mm samego pakietu
> plus skrzynka to ok. 115 mm. Cała reszta tego rozdziału zakłada, że miejsce
> się znajdzie.
>
> Gdyby bank trzeba było **rozdzielić na dwie lokalizacje** (np. 4 pod fotelem
> i 3 gdzie indziej), rozstrzygnięcie topologiczne z §4.3 **przestaje
> obowiązywać w prostej postaci**: dwie szyny spięte jednym mostkiem to inny
> obwód, wzór 9 · r / R nie ma tam zastosowania i asymetrię trzeba policzyć
> osobno.

### 4.3 Zasady łączenia równoległego

Nierówne łączenie równoległe to najczęstszy powód, dla którego bank umiera
przedwcześnie: pakiet z najniższą rezystancją bierze na siebie większość prądu
i wykańcza się pierwszy.

- **jednakowe pakiety** — ten sam model, ta sama dostawa (zbliżony wiek
  i partia produkcyjna),
- **jednakowe ogonki** — identyczny przekrój i **rezystancja** od każdego
  pakietu do szyny, nawet jeśli pakiety leżą różnie; tolerancja liczbowa niżej,
- **szyna zbiorcza z płaskownika miedzianego**, po jednym odczepie na pakiet,
  z **odbiorem po przekątnej** — rozstrzygnięcie niżej,
- **bezpiecznik 10 A na dodatnim biegunie każdego pakietu** (**FB1…FB7**,
  siedem sztuk) — zwarta cela w jednym pakiecie nie zabiera wtedy całej szyny,
- **nie dokładaj nowego pakietu do starego banku** — wyrównuj cały komplet.

#### Siedem to liczba nieparzysta — i to nie jest problem

Przy siedmiu pakietach nie da się zbudować symetrycznego drzewa połączeń
(2-4-8) i to jedyna rzecz, którą nieparzystość naprawdę wyklucza. Symetryczne
drzewo jest jednak tylko **jednym ze sposobów** wyrównania rezystancji toru —
i akurat takim, którego ta dokumentacja nigdy nie proponowała. **Szyna zbiorcza
z równo rozstawionymi odczepami i odbiór po przekątnej działają dla dowolnej
liczby gałęzi**, parzystej i nieparzystej tak samo.

Rozstrzygnięcie jest ilościowe i wychodzi z rozwiązania drabinki: siedem
gałęzi o rezystancji `R` (§4.4), przęsła szyny o rezystancji `r` między
sąsiednimi odczepami. Rozrzut prądów między najbardziej i najmniej obciążoną
gałęzią zamyka się w trzech wzorach:

| Sposób odbioru z szyn | Rozrzut prądów |
|-----------------------|----------------|
| **po przekątnej** — „+" z odczepu 1, „−" z odczepu 7 | **9 · r / R** |
| oba bieguny ze środka (przy pakiecie #4) | 12 · r / R |
| oba bieguny z jednego końca szyny | 42 · r / R ← **zakazane** |

Dla naszej gałęzi (`R` ≈ 37 mΩ) i skoku odczepów 70 mm:

| Przewodnik szyny | `r` na przęsło | Przekątna | Ze środka | Z jednego końca |
|------------------|---------------|-----------|-----------|-----------------|
| **płaskownik 20 × 3 mm** (zalecany) | 20,4 µΩ | **0,50 %** | 0,66 % | 2,31 % |
| **płaskownik 15 × 2 mm** (minimum) | 40,8 µΩ | **0,99 %** | 1,32 % | 4,59 % |
| linka 6 mm² | 204 µΩ | 4,89 % | 6,54 % | 22,0 % |
| linka 4 mm² | 306 µΩ | 7,29 % | 9,74 % | 32,3 % |
| linka 1,5 mm² | 817 µΩ | 18,8 % | 25,2 % | 77,1 % |

> **Wzory wyżej są granicą dla `r` ≪ `R`, tabela — rozwiązaniem dokładnym.**
> Dlatego oba zestawy schodzą się dla płaskownika (0,50 % wobec 9·r/R = 0,50 %),
> a rozjeżdżają dla linki: przy 817 µΩ wzór dałby 19,9 % zamiast 18,8 %,
> a dla odbioru z jednego końca 92,7 % zamiast 77,1 %. Im większe `r`, tym
> mocniej drabinka „sama się dławi" i tym bardziej liniowe przybliżenie
> przeszacowuje rozrzut. Do decyzji doborowej wystarczają wzory — różnica
> jest widoczna dopiero tam, gdzie odpowiedź i tak brzmi „nie linką".

> **Skala odniesienia: sam rozrzut produkcyjny ogniw jest większy.**
> Rezystancja wewnętrzna 23 mΩ ± 10 % w obrębie jednej dostawy daje ok.
> **12,4 %** rozrzutu prądów przy gałęziach 37 mΩ. Geometria szyny
> z płaskownika dokłada do tego **mniej niż 0,1 punktu procentowego**,
> a nieparzystość liczby pakietów nie dokłada nic.
>
> Naprawdę groźne jest co innego: przejście z czterech pakietów na siedem
> **na mostkach z linki** pogarsza rozrzut z 4,3 % na 18,8 % przy odbiorze
> przekątnym, a przy odbiorze z jednego końca z 24,7 % na 77,1 %. Płaskownik
> miedziany kasuje ten efekt w całości. Jeżeli więc pakiety nie pochodzą
> z jednej dostawy i nie są w zbliżonym wieku, to **to** jest realne ryzyko
> dla siódemki — a nie nieparzystość.

#### Konkret: jak to zbudować

**Dwa płaskowniki miedziane** — osobny na „+", osobny na „−" — **minimum
15 × 2 mm (30 mm²), zalecane 20 × 3 mm (60 mm²)**, po **siedem odczepów
śrubowych M6 rozstawionych co 70 mm** (szerokość pakietu leżącego bokiem).
Odbiór **po przekątnej**: „+" z odczepu nr 1, „−" z odczepu nr 7.

```
                 odbiór „+”  (z ładowarki oraz do F7 → LVD)
                 │
   szyna „+”  ═══●═══●═══●═══●═══●═══●═══●
      odczep     1   2   3   4   5   6   7
                 │←─→│  skok odczepów 70 mm
                 │   │   │   │   │   │   │
                FB1 FB2 FB3 FB4 FB5 FB6 FB7    ← wkładki 10 A
                 │   │   │   │   │   │   │      ogonki 1,5 mm²
                [#1][#2][#3][#4][#5][#6][#7]   ← HR1221W, „+” i „−” F2
                 │   │   │   ▲   │   │   │
                 │   │   │   └── NTC 10 kΩ na boku obudowy pakietu #4
                 │   │   │   │   │   │   │
   szyna „−”  ═══●═══●═══●═══●═══●═══●═══●
      odczep     1   2   3   4   5   6   7
                                         │
                    odbiór „−” (masa) ───┘
```

Cztery warunki, bez których ten rysunek nic nie daje:

1. **Kolejność odczepów na obu szynach musi być ta sama** — odczep „−"
   pakietu *k* naprzeciw odczepu „+" pakietu *k*. Odwrócenie kolejności na
   jednej szynie zamienia przekątną w odbiór z jednego końca.
2. **Ogonki pakiet → szyna: 1,5 mm², o jednakowej rezystancji.** Twardy wymóg
   liczbowy: różnica długości pętli (żyła „+" i „−" razem) **≤ ±30 mm**.
   Ogonek 1,5 mm² ma 23,3 mΩ na metr pętli, więc 30 mm to 0,7 mΩ — 2 %
   rezystancji gałęzi. Przy ogonkach 2,5 mm² tolerancja rośnie do ±50 mm.
3. **Nadmiar ogonka w drugim rzędzie zwiń w pętlę serwisową, nie skracaj.**
   Równa ma być rezystancja, a nie odległość w linii prostej.
4. **Nigdy nie bierz obu biegunów z tego samego końca szyny.** To jedyny
   układ, który przy siedmiu pakietach naprawdę psuje rozdział prądów —
   4,6 razy gorzej niż przekątna.

W układzie 4 + 3 (§4.2) szynę **zginasz w L albo U** tak, żeby przechodziła
przez odczepy 1 → 7 po kolei. Dłuższy segment narożny jest praktycznie
darmowy: dla płaskownika 15 × 2 mm przejście z 70 na 200 mm zmienia rozrzut
z 0,99 % na 1,19 %, a dla 20 × 3 mm z 0,50 % na 0,60 %.

> **Dlaczego płaskownik, skoro prąd jest mały.** Przy odbiorze przekątnym
> i rozładowaniu 7,5 A najbardziej obciążony segment szyny (między odczepem 1
> a 2) wiezie 6/7 × 7,5 = **6,4 A**, a dalej coraz mniej — prądowo starczyłoby
> 1,5 mm². Przekrój wynika **wyłącznie** z rezystancji (tabela wyżej),
> z potrzeby mechanicznego utrzymania siedmiu odczepów M6 i z prądu
> zwarciowego **~2,4 kA** (§4.4). Szyny **muszą mieć pokrywę izolacyjną** —
> upuszczony na nie klucz to zwarcie 2,4 kA.

**Hierarchia ważności**, gdyby trzeba było wybierać, na czym oszczędzić:

1. pakiety z jednej dostawy, wyrównane napięciowo przed łączeniem (§11 Etap 2),
2. ogonki o równej rezystancji,
3. płaskownik zamiast linki,
4. odbiór po przekątnej,
5. parzystość liczby pakietów — **bez znaczenia**.

Rysunki: [`../schematics/wiring_power_modules.svg`](../schematics/wiring_power_modules.svg)
(zacisk po zacisku) oraz [`../schematics/power_buffered_m910q.svg`](../schematics/power_buffered_m910q.svg)
(tor główny).

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
| Prąd ładowania (CC) | maks. 2,1 A/pakiet | **8,0 A** dla 7 pakietów | 54 % katalogowego sufitu 14,7 A — nastawę ogranicza **tor**, nie bank (§6.3) |

> **Napięcia nie zależą od liczby pakietów.** Łączenie równoległe sumuje
> pojemność i prąd, a napięcie zostawia bez zmian: siedem bloków 12 V
> równolegle to nadal 12 V, a nie 84 V. Ta tabela, cała kompensacja
> temperaturowa z §4.5, progi rozłącznika nadnapięciowego 15,30 / 14,00 V
> (§6.2) i progi LVD 11,00 / 12,60 V (§7.2) obowiązują **dosłownie**, tak samo
> jak przy czterech pakietach. Zmienia się wyłącznie **prąd** i **czas trwania
> faz**. To jest najczęstsze nieporozumienie przy rozbudowie banku, więc
> zapisane wprost.

> **Korekta wcześniejszej wersji tego dokumentu.** Wcześniejsze wydanie
> zakładało akumulatory żelowe i podawało 14,20 V / 13,70 V oraz ostrzeżenie,
> że 14,4 V jest za dużo. **Dla HR1221W jest inaczej: 14,4 V mieści się
> w katalogowym zakresie cyklicznym.** Osobną sprawą jest prąd: przy banku
> czterech pakietów sufit katalogowy wynosił 8,4 A i wartości 15–20 A
> z oryginalnych notatek repo były dwukrotnym przekroczeniem. Przy banku
> siedmiu sufit to **14,7 A** — i dziś nastawy nie ogranicza już karta
> katalogowa akumulatora, tylko tor ładowania (§6.3, §13.1).

**Seria HR to akumulator buforowy, nie trakcyjny.** Konstrukcja z cienkimi
płytami jest zoptymalizowana pod krótkie rozładowania dużym prądem (UPS) —
i to akurat **bardzo dobrze pasuje** do roli bufora rozruchowego. Czego HR nie
lubi, to **głębokie cyklowanie** — stąd LVD i dyscyplina DoD z §9.

**Rezystancja banku.** Katalogowe 23 mΩ na pakiet daje po zrównolegleniu
siedmiu sztuk **23 / 7 = 3,29 mΩ na samych ogniwach**. Realnie każda gałąź ma
jednak więcej:

| Składnik gałęzi jednego pakietu | Rezystancja |
|---------------------------------|-------------|
| ogniwo (karta katalogowa CSB) | 23,0 mΩ |
| ogonek 1,5 mm², pętla 2 × 0,30 m | 7,0 mΩ |
| wkładka ATO 10 A + oprawka inline | ~7 mΩ |
| **razem `R` na gałąź** | **≈ 37 mΩ** |

Stąd rezystancja banku **37 / 7 = 5,29 mΩ**; przy czterech pakietach było
9,25 mΩ, czyli bank jest dziś o **43 % sztywniejszy**. Odbiór po przekątnej
(§4.3) dokłada każdej gałęzi jednakowe +0,24 mΩ, więc poprawka jest pomijalna.

Skutki praktyczne, prawie wszystkie na korzyść:

- **spadek napięcia**: przy najgorszym prądzie odbiorników 7,5 A (§7.4) bank
  ugina się o 7,5 × 5,29 mΩ = **39,6 mV**; na samych ogniwach 24,6 mV. To
  o rząd wielkości mniej niż histereza LVD (1,6 V) — bez wpływu na próg
  11,00 V i na okno wejściowe XL6019. Efekt drugiego rzędu: LVD odetnie przy
  napięciu spoczynkowym niższym o ~30 mV niż przy czwórce, co jest bez
  znaczenia praktycznego,
- **prąd zwarciowy pojedynczej gałęzi się nie zmienia**: 12,85 V / 37 mΩ =
  **347 A**, niezależnie od liczby pakietów. Dlatego bezpieczniki gałęziowe
  zostają wkładkami ATO (§8.1),
- **prąd zwarciowy prospektywny na szynie banku rośnie do ≈ 2,4 kA**
  (12,85 V / 5,29 mΩ; przy czterech pakietach ≈ 1,4 kA). To jedyna liczba
  w tym rozdziale działająca **na niekorzyść** — konsekwencje dla doboru
  wkładek są w §7.4 i §8.1, a dla obsługi rozłącznika masy w §8.4.

> **Skąd 37 mΩ, skoro karta podaje 23 mΩ.** Rezystancje ogonka i przejść
> (nasuwka F2, wkładka, oprawka) są **przyjęciem** — repozytorium ich nie
> podaje. Rozbicie jest wypisane po to, żeby dało się je przeliczyć po pomiarze
> mostkiem. Wrażliwość: ±20 % na `R` przenosi się 1:1 na rezystancję banku,
> prąd zwarciowy i rozrzut topologiczny z §4.3, ale **nie zmienia żadnej
> decyzji doborowej**.

> **Poprawka rachunkowa wobec poprzedniego wydania.** Było tu napisane, że
> „23 mΩ na pakiet daje po zrównolegleniu 4,6 mΩ, więc pobór 7 A powoduje
> spadek ~32 mV". 4,6 mΩ to 23/5 — wartość dla **pięciu** pakietów, pozostałość po
> starszej konfiguracji. Dla czterech byłoby 5,75 mΩ i 40 mV, dla dzisiejszych
> siedmiu jest 3,29 mΩ i 23 mV na samych ogniwach.

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

Czujnik NTC 10 kΩ przyklej do **boku obudowy pakietu #4** — środkowego
z siedmiu (nie na skrajnym, nie na biegunie). Tu nieparzystość akurat pomaga:
przy siedmiu pakietach środkowy jest jeden i jednoznaczny, przy ośmiu trzeba
by wybierać między dwoma. W układzie 4 + 3 z §4.2 to środkowy pakiet
pierwszego rzędu.

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

Siedem pakietów to **12,6 kg samych akumulatorów**; ze skrzynką, szynami
i pasami licz ok. **15 kg**. Wobec 7,2 kg przy czwórce to nie jest korekta
kosmetyczna — mocowanie staje się osobnym zadaniem konstrukcyjnym.

- miejsce montażu: **pod fotelem pasażera**, nie w bagażniku — patrz
  [`../schematics/vehicle_layout_m910q.svg`](../schematics/vehicle_layout_m910q.svg),
- **układ 4 + 3 w dwóch rzędach, nie siedem w rzędzie.** Powód jest liczbowy:
  moment gnący wspornika `M = m·g·L/8` wynosi **4,33 N·m** przy podparciu co
  280 mm (4 + 3) i **7,57 N·m** przy 490 mm (jeden rząd). Układ 4 + 3 rośnie
  wobec czwórki proporcjonalnie do masy (×1,75), jeden rząd — ×3,06,
- pakiety w **skrzynce lub na wsporniku**, przypięte pasami — 7 × 1,8 kg
  luzem to 12,6 kg pocisku przy hamowaniu,
- pozycja: AGM toleruje dowolną orientację poza **do góry nogami**;
  stojąco albo leżąco na boku,
- **jak najdalej od źródeł ciepła** — patrz §4.6, to nie jest porada
  kosmetyczna,
- dostęp do zacisków bez demontażu połowy auta — przy siedmiu pakietach to
  **14 odczepów** do okresowego dokręcenia (§12),
- AGM jest szczelny (VRLA, rekombinacja gazów), więc montaż w kabinie jest
  dozwolony — ale **skrzynki nie zamykaj hermetycznie**. Przy awarii ładowania
  zawór bezpieczeństwa wypuszcza wodór, a przy siedmiu pakietach jego objętość
  jest 1,75 × większa niż przy czterech; szczelina wentylacyjna jest tym
  bardziej obowiązkowa.

#### Liczby do wspornika

| Wielkość | Wartość |
|----------|---------|
| Masa banku (same pakiety) | **12,6 kg** |
| Siła bezwładności przy 10 g (kryterium robocze) | **1236 N** |
| Siła bezwładności przy 20 g (jak dla mocowania ładunku wg ECE R17) | **2472 N** |
| Na jeden z czterech punktów mocowania | 309 N (10 g) / **618 N** (20 g) |
| Pasy mocujące | 2 szt. ≥ 250 daN (razem 5 kN > 2,47 kN) |

Śruby nie są problemem: **M8 klasy 8.8 wytrzymuje na ścinanie ok. 17,6 kN**,
czyli ponad 28-krotny zapas. Problemem jest **blacha podłogi** — pod każdą
śrubą musi znaleźć się płytka rozkładająca nacisk **min. 40 × 40 × 3 mm**,
inaczej przy 618 N łeb przejdzie przez blachę.

> **Dwie rzeczy, których ten rachunek nie rozstrzyga.** Po pierwsze,
> **nośność podłogi pod fotelem pasażera w Alfie 156 jest nieznana** — 2,47 kN
> przy 20 g to wymaganie, ale nie wiadomo, czy blacha w tym miejscu przyjmie
> je bez wzmocnienia. Po drugie, **kryteria 10 g / 20 g są przyjęte z praktyki
> motoryzacyjnej**, a nie zaczerpnięte z normy, do której ten projekt miałby
> się stosować; poprzednie wydanie nie podawało tu żadnego kryterium poza
> zdaniem „to pocisk przy hamowaniu". 12,6 kg w kabinie to masa istotna dla
> bezpieczeństwa biernego i sposób mocowania jest decyzją człowieka, nie
> wynikiem tego rachunku.

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
| Victron Orion XS 12/12-50 | 50 A | ~1200–1500 PLN | przewymiarowana nawet dla 35,7 Ah |
| Redarc BCDC1225D | 25 A | ~1300–1600 PLN | bardzo odporna, popularna w off-roadzie |
| Sterling BB1230 | 30 A | ~900–1200 PLN | |

Prąd nastaw i tak na **8,0 A** — nie dlatego, że tyle wynosi sufit
akumulatorów (dla siedmiu HR1221W to 14,7 A), tylko dlatego, że tyle wynosi
sufit toru ładowania (§6.3). Dla banku 35,7 Ah **Orion-Tr Smart 12/12-18
nadal wystarcza z zapasem**: 8,0 A to 44 % jego zakresu, a gdyby kiedyś
podnieść CC do katalogowych 14,7 A — 82 %. To jedyna ładowarka z tej tabeli,
która udźwignęłaby pełne ładowanie siedmiu pakietów.

> **Wariant A nie omija ograniczenia z §6.3.** Warstwa nadnapięciowa jest
> wymagana także przy gotowej ładowarce B2B (§6.3), więc obciążalność
> XH-M603 ogranicza oba warianty tak samo. Sama ładowarka tego problemu nie
> rozwiązuje.

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
| **Moduł CC-CV boost** z regulacją prądu i napięcia | podnosi 13,7 V → 14,4 V i limituje prąd | CV 14,40 V, **CC 8,0 A** | 50–140 PLN |

#### 5.3a Konkretne moduły CC-CV

Wszystkie trzy to **boost**, więc nastawa CV musi być wyższa od napięcia
wejściowego — patrz §5.3b.

| Model | Dane | Cena | Kiedy ten |
|-------|------|------|-----------|
| **„900 W 15 A" z wyświetlaczem** (typ CNC/DPS, wej. 8–60 V, wyj. 10–120 V) | CC 0–15 A, nastawa cyfrowa z odczytem, pamięć nastaw | 90–140 PLN | **domyślny wybór** — wpisujesz 14,40 V i 8,0 A i odczytujesz z powrotem, zamiast celować potencjometrem |
| **„1500 W 30 A" boost CC-CV** (wej. 10–60 V, wyj. 12–97 V) | CC 0,8–22 A · sprawność 92–97 % · 130 × 84 × 52 mm, radiator + wentylator termiczny | 60–95 PLN | gdy chcesz duży zapas mocy i zimną pracę; nastawa potencjometrami |
| ~~**„600 W 10 A"**~~ (wej. 10–60 V, wyj. 12–80 V) | CC-CV potencjometrami | 50–80 PLN | **wypada przy siedmiu pakietach** — nastawa 8,0 A to 80 % jego zakresu CC, a ścieżki tej płytki są słabe. W aucie to praca na krawędzi |

Przy CC **8,0 A** moc wyjściowa wynosi 14,4 × 8,0 = **115 W**. „900 W 15 A"
pracuje wtedy na 53 % zakresu CC, ale ma niższą sprawność (~85 %), więc prąd
wejściowy rośnie do ok. 10,1 A i wkładka F1 15 A schodzi na 67 % — nadal
w porządku. „1500 W 30 A" pracuje na 36 % i zostawia zapas na ewentualne
podniesienie CC do 13 A.

> **Korekta: SZBK07 wypada z tej tabeli.** Wcześniejsze wydanie wymieniało
> tu SZBK07 — to przetwornica **obniżająca** (buck 300 W na LM5116), nie
> boost; z 13,7 V nie zrobi 14,4 V. Moduł „1500 W 30 A" o podobnych
> gabarytach szukaj po frazie „boost converter 1500W 30A 10-60V".

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
12,0 V. W pass-through różnicę 1,75 V ogranicza tylko rezystancja okablowania
(~30 mΩ) i samego banku (5,29 mΩ, §4.4) — to daje **ok. 50 A**, czyli
przepalony bezpiecznik w najlepszym razie.

> **Siedem pakietów wzmacnia ten argument.** Bank jest o 43 % sztywniejszy niż
> czwórka (5,29 zamiast 9,25 mΩ), więc w pass-through popłynie o ok. 11 %
> więcej prądu: 50 A zamiast 45 A. Nastawa **CV 14,40 V zostaje bez
> dyskusji**.

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
| **LTC3780** (moduł WD2002SJ / XR-131, wej. 5–32 V, wyj. 1–30 V) | buck-boost, CC + CV + próg podnapięciowy (trzy potencjometry), 10 A szczytowo | 50–90 PLN | **7 A i 80 W ciągle** — przy 13,8 V to tylko ~5,8 A, więc po odjęciu 3,5 A obciążenia do banku idzie 2,3 A. Przy siedmiu pakietach oznaczałoby to 11,6 h fazy CC z progu LVD zamiast 5,95 h (§9.4) — **odpada** |

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
  spadek: przy CC 8,0 A prąd wejściowy toru wynosi ok. **9,2 A**, czyli
  4,6 A na połówkę i Vf ≈ 0,48 V,
- **radiator obowiązkowy** — 9,2 A × 0,48 V to **4,4 W** ciągłej straty,
  czyli 98 % tego, na co radiator (~15 × 14 mm, ≥ 6 K/W) był dobrany przy
  czterech pakietach: **radiator zostaje bez zmian**. Prądowo dioda też nie
  jest wąskim gardłem — połówka wiezie 4,6 A z dopuszczalnych 12,5 A. Gdyby
  kiedyś podnieść CC: przy 10 A strata rośnie do 5,9 W (radiator ≤ 3 K/W),
  a przy katalogowych 14,7 A do 10,0 W (≤ 2 K/W z przewiewem albo dioda 40 A),
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

> **Sufiks „CA" znaczy dwukierunkowa — i to nie jest szczegół.** 1.5KE33**CA**
> i SMCJ26**CA** nie mają anody ani katody; wlutuj je w dowolną stronę. Pasek
> na obudowie, jeśli w ogóle jest nadrukowany, nic nie znaczy. Ale
> **1.5KE33A** (bez „C") to inna dioda — **jednokierunkowa**, i tam pasek
> (katoda) musi iść na **plus**. Odwrotnie wlutowana jest spolaryzowana
> w kierunku przewodzenia, czyli jest zwarciem ~1 V na zasilaniu, i bezpiecznik
> idzie natychmiast po podaniu napięcia.
>
> **Sprawdzenie miernikiem** (tryb testu diody): dwukierunkowa daje **OL
> w obie strony**, jednokierunkowa ~0,7 V w jedną i OL w drugą. Próg 33 V
> jest daleko poza zasięgiem miernika, więc w kierunku zaporowym zawsze
> zobaczysz OL — to normalne, nie oznacza uszkodzenia.

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
| Prąd przez styki | **≤ 8 A** | to nie jest zapas, tylko **granica** — wyznacza nastawę CC całego układu, §6.3 |

### 6.3 Realizacja

#### Ile prądu tam naprawdę płynie

To pytanie decyduje o doborze modułu, więc najpierw ono. Rozłącznik siedzi
**między wyjściem boostu a bankiem**, czyli w torze ładowania — nie w torze
odbiorników. Płynie przez niego wyłącznie **prąd ładowania, ograniczony
nastawą CC boostu** (§3.3 [`WDROZENIE_TESTOWE.md`](WDROZENIE_TESTOWE.md)),
czyli maksymalnie **8,0 A**.

**Przy siedmiu pakietach logika tego doboru się odwraca.** Przy czwórce prąd
przez ten moduł wynikał z sufitu katalogowego akumulatora (8,4 A). Przy
siódemce sufit akumulatora to 14,7 A i **przestał być wiążący** — o nastawie
CC decyduje dziś obciążalność samej płytki XH-M603. To jest wąskie gardło
całej rozbudowy i jedyny element, który trzeba by wymienić, żeby ładować
szybciej.

Nie myl tego z XH-M609: ten stoi po stronie odbiorników i przenosi prąd
odbiorników (**do ~7,5 A** wg zestawienia z §7.4), a ma przekaźnik 20 A —
tam zapas jest duży i **nie zmienia się z liczbą pakietów**, bo prąd
ładowania wchodzi na szynę banku obok niego.

#### Gdzie naprawdę kończy się tor ładowania

Element po elemencie, wszystko przeliczone na **prąd wyjścia ładowarki**
(= obciążenie 3,5 A + prąd do banku). Prąd wejściowy toru liczymy jako
`I_wej = 14,4 V × CC / (0,93 × 13,4 V)` = 1,16 × CC; dokumentacja zaokrągla
ten przelicznik do 1,2 i tak są wymiarowane wkładki — konserwatywnie.

| Element toru | Jego limit | Odpowiada nastawie CC |
|--------------|-----------|----------------------|
| **XH-M603 — płytka i zaciski śrubowe** | ~10 A; spec §6.2 „≤ 8 A" | **8,0 A** ← wąskie gardło |
| Radiator diody MBR2545CT dobrany na 4,5 W | 4,5 W | 8,1 A |
| Przewód AKU → boost 2,5 mm², 3 m (wariant testowy) | spadek 3 % | 8,6 A |
| Przewód ładowarka → bank 4 mm², 3 m | spadek 3 % | 10,3 A |
| Wkładka F1 15 A ATO przy 80 % obciążalności ciągłej | 12 A wejścia | 10,4 A |
| **Sufit katalogowy CSB: 7 × 2,1 A** | **14,7 A** | 14,7 A |
| Moduł boost „900 W 15 A" / „1500 W 30 A" | CC 15 A / 22 A | 15 A / 22 A |
| Dioda MBR2545CT 25 A (prądowo) | 25 A | ~21 A |
| Przekaźnik K1 30 A · bezpiecznik główny 30 A | 30 A | ~26 A |

**Żaden element toru z tej dokumentacji nie dochodzi do 14,7 A.** To jest
odwrócenie sytuacji z §4.2: bank przestał być ograniczony pojemnością, a stał
się ograniczony prądem ładowania. Wyjście powyżej 8,0 A jest możliwe, ale
kosztowne i sztywne w kolejności:

- **do 10 A** — wymiana modułu nadnapięciowego na taki z wolnym stykiem
  COM/NO plus F1 → 20 A,
- **do 13–14,7 A** — dodatkowo przekaźnik mocy K2, przewód wejściowy 6 mm²
  i mocniejszy radiator diody (8,4–10,0 W straty).

To jest osobny projekt i decyzja człowieka, a nie skutek uboczny dołożenia
pakietów.

#### Konkretne moduły

Rodzina XH-M60x, ta sama co posiadany XH-M609 — identyczna obsługa,
wyświetlacz, przyciski, nastawa co 0,1 V:

| Model | Zakres | Nastawy | Uwaga |
|-------|--------|---------|-------|
| **XH-M603** | zasilanie 10–30 V | próg górny i dolny osobno, precyzja 0,1 V | **domyślny wybór** — fabrycznie 12,0 / 14,5 V, przestaw na 14,00 / 15,30 V |
| **XH-M604** | zasilanie 6–60 V | j.w. | gdy chcesz zapas napięciowy albo masz go pod ręką |
| **XH-M601** / **XH-M602** | 12 V / 24 V | prostsze, część wersji bez regulacji obu progów | tylko jeśli potwierdzisz, że da się ustawić OBA progi |

Logika XH-M603 jest dokładnie tą, której potrzebujemy: **zwiera, gdy
napięcie jest poniżej progu górnego, rozwiera po jego przekroczeniu**,
a wraca dopiero przy progu dolnym. To jest sterownik ładowania, nie
ochrona podnapięciowa — nie trzeba go odwracać.

#### „30 A” na przekaźniku to nie 30 A na module

Na tych płytkach siedzi zwykle przekaźnik z nadrukiem 30 A / 14 VDC, ale
**ograniczeniem jest płytka, nie przekaźnik**: ścieżki i zaciski śrubowe
wytrzymują realnie ok. 10 A. Przy naszych **8,0 A jesteś na 80 %** tej
wartości i dokładnie na deklarowanej granicy spec z §6.2 — w spec, ale bez
komfortowego zapasu. To jest właśnie powód, dla którego warto zrobić o jeden
krok więcej.

> **Tę liczbę trzeba potwierdzić pomiarem.** Obciążalność ~10 A jest
> **oszacowaniem** z oględzin płytki, a nie wartością z karty katalogowej —
> a przy siedmiu pakietach to od niej zależy nastawa CC całego układu. Zmierz
> temperaturę zacisków przy 8 A przez 30 min, zanim oprzesz na tym projekt.
> Jeżeli moduł się grzeje, masz dwa wyjścia: zejść na CC 6,0 A i zaakceptować
> 14–16 h ładowania od progu LVD (§9.4), albo kupić moduł z wolnym stykiem
> COM/NO i przekaźnik mocy K2.

> **Uwaga — XH-M603 nie nadaje się do układu „pilot" opisanego niżej.**
> Zweryfikowane działanie tego modułu: przekaźnik siedzi wewnętrznie w torze
> DC-IN+ → OUT+ (nie ma wolnego styku na złączce), a pomiar napięcia jest po
> stronie OUT. Gdy OUT+ steruje cewką K2, po zadziałaniu napięcie na OUT
> spada do zera przez cewkę → moduł widzi „pusty akumulator" → zwiera
> z powrotem → oscylacja niszczy styki. **XH-M603 wpinaj w tor ładowania**
> (DC-IN z boostu, OUT na bank) przy **CC ≤ 8,0 A** — dokładnie tak robi to
> wariant PCB: [`PCB_ZASILANIE.md`](PCB_ZASILANIE.md) §3. Układ „pilot + K2"
> pozostaje poprawny tylko dla modułów z wolnym stykiem COM/NO na złączce.

#### Zalecane: moduł jako pilot, moc na osobnym przekaźniku

```
XH-M603 styk (COM/NO)  →  cewka przekaźnika Bosch 30 A  (~150 mA)
przekaźnik Bosch 30/87 →  w torze ładowania (te 8 A)
```

Moduł przełącza wtedy 150 mA zamiast 8 A i pytanie o obciążalność znika.
Koszt: +15–25 PLN za przekaźnik z podstawką.

> **Zepnij to tak, żeby awaria oznaczała „nie ładuje".** Cewka przekaźnika
> mocy ma być **zasilana, gdy moduł mówi OK**. Wtedy przepalona cewka,
> uszkodzony moduł albo urwany przewód sterujący dają rozwarty tor
> ładowania — najgorsze, co się stanie, to nienaładowany bank. Odwrotne
> zepnięcie (przekaźnik zwarty w spoczynku) przy awarii modułu zostawia
> ładowanie bez nadzoru.
>
> Zanim zalutujesz: sprawdź miernikiem, przy którym stanie modułu jego
> styk COM–NO jest zwarty. Wersje płytek się różnią.

#### Zasilaj to z przekaźnika ładowania, nie z banku

Łatwo tu zepsuć cały budżet postojowy. Cewka przekaźnika mocy bierze
~150 mA, moduł XH-M603 kilka do kilkunastu mA. Gdyby wisiały na banku,
**dokładałyby ~160 mA przez całą dobę** — czyli mniej więcej tyle, ile
w stanie wyłączonym pobiera wszystko pozostałe razem wzięte (§2.1).

Zasilaj więc i moduł, i cewkę **z zacisku 87 przekaźnika ładowania K1**:

```
K1 (zapłon)  ──87──┬── moduł CC-CV boost
                   ├── XH-M603 zasilanie
                   └── styk XH-M603 → cewka K2 (przekaźnik mocy)
```

Przy zgaszonym silniku K1 jest rozwarty, więc cały ten węzeł jest martwy:
zero poboru, K2 rozwarty, tor ładowania przerwany podwójnie.

**Skutek uboczny, który akurat działa na naszą korzyść:** moduł mierzy
wtedy napięcie po stronie boostu. Po zadziałaniu wyjście boostu bez
obciążenia nie spadnie do progu powrotu 14,00 V, więc rozłącznik zostaje
**zatrzaśnięty do końca jazdy** i wraca dopiero po przekręceniu kluczyka.
Dla usterki to lepsze zachowanie niż klapkowanie w kółko.

#### Kiedy można pominąć K2

Przy nastawie **CC ≤ 8,0 A** styki i płytka XH-M603 wyrabiają bez K2 — ale
to jest 80 % realnej obciążalności płytki, czyli **bez komfortowego zapasu**.
Tor wygląda wtedy tak: boost OUT+ → COM modułu → NO modułu → szyna „+" banku,
a moduł zasilasz z zacisku 87 K1 jak wyżej. Oszczędzasz 20 PLN i jedno
złącze, kosztem pracy na granicy.

Tak właśnie robi to wariant PCB ([`PCB_ZASILANIE.md`](PCB_ZASILANIE.md) §3),
gdzie XH-M603 siedzi wprost w torze ładowania. **Powyżej 8,0 A ta droga jest
zamknięta**: wracasz do układu „pilot + K2", a do tego potrzebujesz modułu
z wolnym stykiem COM/NO — którego XH-M603 nie ma.

#### Czego ten rozłącznik NIE robi

**Nie chroni przed load dumpem.** Moduł reaguje w dziesiątkach do setek
milisekund, a szpilka z alternatora trwa mikrosekundy — od tego jest dioda
TVS na wejściu (§5.4). To dwie różne warstwy, jedna nie zastępuje drugiej.

**Nie musi chronić odbiorników.** Bank trzyma napięcie szyny, a XL6019
i LM2596 przyjmują 15–16 V bez mrugnięcia. Odcięcie samego ładowania
w zupełności wystarcza.

**Wariant A i tak potrzebuje tej warstwy.** Ładowarka Victron/Redarc jest
bardzo niezawodna, ale nie jest niezniszczalna — a komplet **siedmiu**
HR1221W jest wielokrotnie droższy niż moduł za 60 PLN. To znaczy również, że
ograniczenie 8,0 A z tej sekcji dotyczy **obu wariantów tak samo**: gotowa
ładowarka go nie omija.

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

Bezpiecznik **F7** między szyną „+" banku a VIN+: **15 A**. Reguła producenta
modułu to 1,5 × prąd szczytowy, czyli 1,5 × 7,5 = 11,25 A — a najbliższa
większa wkładka typoszeregu to 15 A. Wartość **nie zależy od liczby pakietów**:
przez F7 płynie wyłącznie prąd odbiorników, a prąd ładowania wchodzi na szynę
banku obok niego. Nawet po wymianie XL6019 na moduł 65 W (szczyt 9,7 A)
wychodzi 1,5 × 9,7 = 14,6 A, czyli nadal 15 A.

> **Zmienia się natomiast wymagana klasa wkładki.** Prąd zwarciowy
> prospektywny na szynie banku urósł z ~1,4 kA (cztery pakiety) do **~2,4 kA**
> (§4.4), a wkładka ATO/ATC ma katalogową zdolność wyłączania ok. **1 kA
> @ 32 V DC** (ISO 8820 / SAE J1888). Poza tą wartością bezpiecznik zamiast
> przerwać obwód może zapalić łuk. Na F7 użyj wkładki **MIDI/AMI albo ANL**
> o zdolności wyłączania ≥ 2 kA. Uwaga uczciwościowa: to przekroczenie
> istniało już przy czterech pakietach, tylko mniejsze — siedem pakietów je
> pogłębia, a nie tworzy. Przed zakupem potwierdź zdolność wyłączania w karcie
> konkretnej wkładki; repozytorium tych danych nie zawiera.

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
| Tor ładowania (**F1**) | 15 A ATO | przy klemie „+", na wejściu toru ładowania (§5.3) |
| Na pakiet banku (**FB1…FB7**) | 10 A × 7 | na zacisku F2 „+" każdego pakietu |
| Szyna banku → XH-M609 VIN+ (**F7**) | 15 A, **MIDI/AMI lub ANL** | przy szynie banku — uzasadnienie klasy w §7.4 |
| Wyjście step-up | 5 A | między przetwornicą a wtykiem M910q |
| Odgałęzienie logiki (Nano, HM-10, RXB6) | 3 A | przed buckiem 12 → 5 V |
| Odgałęzienie wyświetlaczy | 3 A | przed buckiem 12 → 5 V wyświetlaczy |
| Gałąź wzmacniacza | wg karty modułu (20–30 A) | osobno, przy klemie akumulatora rozruchowego |

Bezpiecznik główny **przy klemie**, nie przy urządzeniu — zwarcie przewodu
o karoserię w połowie trasy ma być przerwane przy źródle, inaczej cały
przewód staje się grzałką. Wkładki nożowe ATO/ATC w listwie dystrybucyjnej
z pokrywą, w miejscu dostępnym bez demontażu deski rozdzielczej.

**Dlaczego 10 A na pakiet, skoro pakiet wiezie 1 A.** Prąd roboczy jednej
gałęzi to 7,5/7 = **1,07 A** przy rozładowaniu i 4,5/7 = **0,64 A** przy
ładowaniu, więc wkładka 10 A ma zapas dziewięciokrotny. Jej wartość wynika
z obciążalności nasuwki F2 i z selektywności, a nie z liczby pakietów — przy
siedmiu pakietach zmienia się **wyłącznie liczba sztuk**, z czterech na
siedem.

**Selektywność przy siedmiu pakietach jest lepsza niż przy czterech.** Przy
zwarciu wewnątrz jednego pakietu przez jego wkładkę płynie 12,85 V /
(37/6 + 14) mΩ = **637 A** (przy czwórce było 488 A), a przez każdą z sześciu
zdrowych gałęzi 637/6 = 106 A. Stosunek 6 : 1 zamiast 3 : 1 — pali się
właściwy bezpiecznik, i to szybciej. Obie liczby mieszczą się w ~1 kA
zdolności wyłączania wkładki ATO. Dla zwartej pojedynczej celi (ΔU 2,1 V)
wychodzi 48,6 A, czyli ok. 5 × prąd znamionowy wkładki — też zadziała.

> **Oznaczenia: FB1…FB7, a nie F2…F8.** Proste rozciągnięcie dotychczasowego
> ciągu F2…F5 na siedem pakietów weszłoby w kolizję z **F7** (szyna banku →
> LVD) i **F8** (wkładka przetwornicy 19,5 V na płytce B,
> [`PCB_ZASILANIE.md`](PCB_ZASILANIE.md) §1). Bezpieczniki gałęziowe banku
> dostają więc własną serię **FB** — „bezpieczniki banku" — a F1 i F7–F11
> zostają bez zmian.

> **Luka, której ta dokumentacja nie zamyka — do decyzji.** Między szyną „+"
> banku a wyjściem toru ładowania **nie ma żadnej wkładki**: F1 chroni odcinek
> od strony auta, F7 wyłącznie odgałęzienie do LVD. Zwarcie na odcinku
> ładowarka → szyna banku jest zasilane wprost z banku prądem ~2,4 kA i nic go
> nie przerywa. To luka **istniejąca** (przy czterech pakietach było ~1,4 kA),
> którą siódemka pogłębia o 75 %. Zalecenie: **MIDI/ANL 15 A na odgałęzieniu
> do ładowarki, przy szynie banku** — 1,5 × CC 8,0 A = 12 A, czyli wkładka
> 15 A. Ponieważ jest to **dodanie elementu**, a nie korekta istniejącego, nie
> wpisano go ani do tabeli wyżej, ani do listy zakupowej z §10.

### 8.2 Przekroje przewodów

Dla trasy ok. 3 m (komora silnika → deska rozdzielcza) przy spadku < 3 %:

| Odcinek | Prąd | Przekrój |
|---------|------|----------|
| Akumulator → bezpiecznik → przekaźnik/ładowarka | do 30 A | **6 mm²** |
| Ładowarka → szyna „+" banku | do 10 A | **4 mm²** |
| **Szyny zbiorcze banku** („+" i „−" osobno) | do 6,4 A | **płaskownik Cu 15 × 2 mm** (min.), **20 × 3 mm** (zalecany) — §4.3 |
| Pakiet HR1221W → szyna (ogonek, 7 sztuk) | do 10 A | 1,5 mm² |
| Szyna → LVD → przekaźnik → step-up | do 7,5 A | 2,5 mm² |
| Step-up → M910q | 3,5 A @ 19 V | 1,5 mm² |
| Odgałęzienie logiki (Nano, HM-10, RXB6) | < 1 A | 0,75 mm² |
| Odgałęzienie wyświetlaczy (buck paneli) | ~1,5 A | 0,75 mm² |
| Gałąź wzmacniacza | wg karty modułu | 6 mm² (trasa ~4 m do bagażnika) |
| Masa do nadwozia | — | **6 mm²** |

Przewody samochodowe (FLRY/FLY), nie instalacyjne YDY — potrzebna jest
linka, nie drut, i izolacja odporna na temperaturę i oleje.

**Dlaczego ładowarka → bank idzie na 4 mm².** Formalnie 2,5 mm² by się
zmieściło: na trasie 3 m przy 8,0 A daje 0,336 V, czyli 2,3 % z dopuszczalnych
3 %. Powód zmiany jest **regulacyjny, nie formalny** — ten spadek siedzi
w pętli CV, więc bank widziałby 14,06 V zamiast 14,40 V, a faza absorpcji
startowałaby później i trwała dłużej. Przy 4 mm² tracisz 0,21 V zamiast
0,34 V, a strata w samym przewodzie spada z 2,7 na 1,7 W. **Ten sam przekrój
weź na powrót** (OUT− ładowarki do punktu gwiazdowego masy) — spadek liczy
się na całej pętli, więc cieńszy powrót kasuje połowę zysku. Jeżeli ładowarka
stoi tuż przy banku (trasa ≤ 1,5 m), 2,5 mm² wystarcza. Od CC 10 A 4 mm²
przestaje być wyborem i staje się wymogiem.

**Dlaczego ogonki pakietów zostają na 1,5 mm², mimo że pakietów jest więcej.**
Przekroju nie wyznacza tu prąd — gałąź wiezie 1,07 A przy rozładowaniu
i 0,64 A przy ładowaniu — tylko wkładka gałęziowa 10 A i wymóg jednakowości.
Pogrubianie działa wręcz **przeciwko** symetrii banku: rezystancja ogonka
i oprawki rozcieńcza fabryczny rozrzut ogniw. ±10 % z 23 mΩ daje 20 %
rozrzutu prądów na gołych ogniwach, ale tylko 12,4 % na gałęziach 37 mΩ.
Tolerancja długości: ±30 mm różnicy pętli (§4.3).

**Odcinek szyna → LVD → step-up nie zmienia się wcale.** Płynie przez niego
wyłącznie prąd odbiorników (7,5 A szczytowo, §7.4), a ten od liczby pakietów
nie zależy: spadek na pętli 2 m przy 2,5 mm² to 105 mV, czyli 0,8 %.

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
  serwis i jest wymagany, jeśli auto stanie na dłużej. Przenosi maksymalnie
  8 A (ładowanie) albo 7,5 A (rozładowanie), czyli 8 % swojej obciążalności,
- ⚠ **rozłącznik masy rozłączaj wyłącznie bez obciążenia.** Prąd zwarciowy
  prospektywny banku siedmiu pakietów to ~2,4 kA (§4.4), a typowe rozłączniki
  podają 100 A ciągle / ~1250 A rozruchowo / ~2500 A chwilowo — jesteś blisko
  granicy. Sprawdź kartę katalogową swojego egzemplarza,
- **szyny zbiorcze banku muszą mieć pokrywę izolacyjną.** Czternaście odczepów
  śrubowych przy 2,4 kA prądu zwarciowego to nie jest miejsce na upuszczony
  klucz.

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

> **Czego w tym budżecie nie ma.** Tabela obejmuje wyłącznie domenę A
> w rozumieniu §2: Nano #1, HM-10, RXB6, moduł przekaźników i straty bucka.
> Nie ma w niej Arduino Pro Micro, Nano #2 ani modułu wyświetlacza 1,8" na
> ESP32 ([`WYSWIETLACZ_ESP32_1V8.md`](WYSWIETLACZ_ESP32_1V8.md)) — a ten
> ostatni bierze ok. **60 mA z 12 V**, czyli tyle, co cała reszta logiki razem
> wzięta. Jeżeli panel trafi na szynę buforowaną, przesuwasz się o jeden–dwa
> wiersze w dół tabeli §9.2: postój schodzi z 9,3–4,0 na **5,3–3,0 dnia**.
> Przy banku 35,7 Ah to jest do udźwignięcia; przy czterech pakietach nie było
> (3,0–1,7 dnia). Rachunek i decyzja — w tamtym dokumencie.

### 9.2 Czas postoju

Czas zależy od tego, ile pobiera XH-M609 — dlatego tabela jest rozpisana
wg **sumarycznego poboru**. Logika i przekaźniki to stałe 60 mA; reszta to
moduł LVD.

**Bank 7 pakietów — 35,7 Ah** (konfiguracja przyjęta):

| Pobór całkowity | XH-M609 | Do 30 % DoD | Do 50 % DoD | Do progu LVD |
|-----------------|---------|-------------|-------------|--------------|
| 80 mA | 20 mA | ~5,6 dnia | ~9,3 dnia | ~13,9 dnia |
| 100 mA | 40 mA | ~4,5 dnia | ~7,4 dnia | ~11,2 dnia |
| 130 mA | 70 mA | ~3,4 dnia | ~5,7 dnia | ~8,6 dnia |
| 185 mA | 125 mA (spec max) | ~2,4 dnia | ~4,0 dnia | ~6,0 dnia |

**Bank 6 pakietów — 30,6 Ah** (odniesienie — tyle zostaje po awarii jednego
pakietu; §4.2):

| Pobór całkowity | Do 30 % DoD | Do 50 % DoD | Do progu LVD |
|-----------------|-------------|-------------|--------------|
| 80 mA | ~4,8 dnia | ~8,0 dnia | ~12,0 dnia |
| 100 mA | ~3,8 dnia | ~6,4 dnia | ~9,6 dnia |
| 130 mA | ~2,9 dnia | ~4,9 dnia | ~7,4 dnia |
| 185 mA | ~2,1 dnia | ~3,4 dnia | ~5,2 dnia |

**Bank 8 pakietów — 40,8 Ah** (odniesienie — gdybyś użył także pakietu
zapasowego; czym się za to płaci, mówi §4.2):

| Pobór całkowity | Do 30 % DoD | Do 50 % DoD | Do progu LVD |
|-----------------|-------------|-------------|--------------|
| 80 mA | ~6,4 dnia | ~10,6 dnia | ~15,9 dnia |
| 100 mA | ~5,1 dnia | ~8,5 dnia | ~12,8 dnia |
| 130 mA | ~3,9 dnia | ~6,5 dnia | ~9,8 dnia |
| 185 mA | ~2,8 dnia | ~4,6 dnia | ~6,9 dnia |

> **Korekta rachunkowa wobec poprzedniego wydania.** Tabela podpisana tam
> „Bank 4 pakiety — 20,4 Ah" była w rzeczywistości policzona dla **25,5 Ah**
> (pięciu pakietów) — wszystkie dwanaście komórek było zawyżonych dokładnie
> o 25 %. Nowe liczby **nie są** starymi przemnożonymi przez 1,75 i nie da się
> ich uzyskać przeskalowaniem; policzono je od zera. Sąsiednia tabela
> ośmiopakietowa była i pozostaje poprawna.

Kolumna 30 % DoD jest tu dlatego, że HR1221W to seria buforowa (UPS), a nie
trakcyjna — płytsze rozładowanie wyraźnie wydłuża jej życie. Przy okazjonalnym
dłuższym postoju 50 % DoD jest w porządku; jako **rutyna** lepiej trzymać 30 %.

> **Siedem pakietów kupuje łagodniejszy reżim, nie tylko dłuższy postój.**
> Siódemka przy 30 % DoD daje 10,71 Ah użytecznych, czyli **więcej niż czwórka
> przy 50 % DoD** (10,2 Ah). Można zejść na reżim zalecany dla serii HR
> i mimo to mieć dłuższy postój niż poprzednio.

> **Pomiar poboru XH-M609 nadal rozstrzyga.** Dołożenie pakietów **właśnie
> zostało zrobione** — to była ta rozbudowa — więc kierunek „więcej
> akumulatorów" jest wyczerpany. Problem został złagodzony (przy górnej
> granicy spec, 185 mA łącznie, postój do 50 % DoD rośnie z 2,3 na 4,0 dnia),
> ale nie zniknął: pomiar z §7.3 decyduje, w którym wierszu powyższej tabeli
> siedzisz. Jeżeli wypadnie przy 125 mA, realne kierunki to nadal:
>
> - **wymiana LVD** na moduł bez wyświetlacza (prosty komparator
>   z przekaźnikiem pobiera 5–10 mA zamiast 20–125 mA),
> - **skrócenie progu eskalacji** z 2 h do np. 30 min, żeby maszyna szybciej
>   schodziła z S3 (200–460 mA) do wyłączenia (50–150 mA),
> - **wyłącznik główny** przy dłuższym postoju — jedyne prawdziwe zero.

> **Korekta wobec starszych notatek.** `docs/X86_PLATFORM_SETUP.md` § 2.3
> i `10-power-suspend.html` podają dla banku 25 Ah „~17 dni" z adnotacją
> „ograniczone do 50 % DoD". Te dwie rzeczy się wykluczają: 25 Ah / 0,060 A
> = 417 h = 17,4 dnia to **pełne rozładowanie do zera**. Do tego bank ma
> dziś **siedem pakietów, nie pięć**, a komputer nie jest już odcinany — więc
> liczba z tamtych notatek nie ma żadnego przełożenia na obecny układ.
> Obowiązuje tabela z §2.1.

Samorozładowanie HR1221W (> 75 % pojemności po 6 miesiącach @ 25 °C, czyli
≤ 4 %/miesiąc) odpowiada ok. **2,0 mA** przy banku 35,7 Ah — wobec 60 mA
logiki to 3,3 %, czyli nadal pomijalne. W upale rośnie kilkukrotnie, ale nadal
nie zmienia obrazu. Uwaga: po rozłączeniu wyłącznika głównego samorozładowanie
zostaje **jedynym** odbiornikiem i bank i tak zejdzie o ~4 % miesięcznie.

Kolumna „do progu LVD" zakłada zejście do ~75 % DoD (11,0 V pod bardzo
lekkim obciążeniem). Jest osiągalna, ale każde takie zejście kosztuje
żywotność — traktuj ją jako rezerwę awaryjną, nie tryb normalnej pracy.

> **Czasy dla siedmiu pakietów są mniej optymistyczne niż te same liczby były
> dla czterech — i to jest dobra wiadomość.** Pojemność katalogowa 5,1 Ah jest
> podana dla rozładowania 20-godzinnego (C/20). Przy 3,5 A siedem pakietów
> pracuje z krotnością C/10,2, a cztery pracowały z C/5,8 — im niższa
> krotność, tym bliżej warunków karty katalogowej. Skali tej korekty nie da
> się policzyć bez krzywych rozładowania HR1221W, których repozytorium nie
> zawiera; rachunek prowadzimy bez poprawki Peukerta, tak jak dotychczas.

### 9.3 Budzenie RTC

Jeśli włączysz budzenie M910q z RTC (np. co 15 min na ping pozycji), dolicz
ok. **5 Ah tygodniowo** — czyli **+29,8 mA** równoważnego poboru ciągłego
(5 Ah / 168 h). Przy poborze bazowym 80 mA skraca to powyższe czasy do
**ok. 73 %**: 9,3 dnia → 6,8 dnia do 50 % DoD. Przy większym poborze bazowym
efekt jest jeszcze mniejszy. Przy dłuższym postoju wyłącz budzenie z UI.

> **Poprzednie wydanie pisało tu „mniej więcej połowi" — i było to niepoprawne
> niezależnie od liczby pakietów.** Budzenie RTC dokłada **prąd**, a nie
> zabiera pojemność, więc skrócenie jest ilorazem `I / (I + 29,8 mA)` i przy
> 80 mA wynosi 0,73 — tak samo dla czterech pakietów, jak dla siedmiu. Żeby
> czasy naprawdę spadły o połowę, budzenie musiałoby kosztować ~13,4 Ah
> tygodniowo.

### 9.4 Ładowanie po postoju

Bank rozładowany do 50 % DoD (**17,85 Ah** do uzupełnienia) przy nastawie
**CC 8,0 A** i obciążeniu ~3,5 A ładuje się netto prądem **4,5 A**, czyli
**około 4,0 h w fazie CC** plus absorpcja. Realnie licz **5–6 godzin jazdy**
do pełna.

| Stan wyjściowy | Do uzupełnienia | Faza CC przy 4,5 A netto | Realnie jazdy |
|----------------|-----------------|--------------------------|---------------|
| 30 % DoD (reżim rutynowy dla serii HR) | 10,71 Ah | 2,38 h | **3–4 h** |
| 50 % DoD (po rutynowym postoju) | 17,85 Ah | 3,97 h | **5–6 h** |
| próg LVD (~75 % DoD) | 26,78 Ah | 5,95 h | **8–9 h** |

Mnożnik z fazy CC na pełne naładowanie to ×1,3–1,5 (faza absorpcji).

**Zdanie z poprzedniego wydania — „katalogowy sufit to 8,4 A, więc tego czasu
nie skrócisz" — przestało obowiązywać.** Sufit katalogowy wynosi teraz
**14,7 A**, a wąskim gardłem jest tor ładowania (§6.3). Czas skraca się dziś
**wyłącznie przez podniesienie CC**:

| Nastawa CC | Netto do banku | Faza CC z progu LVD | Realnie jazdy |
|-----------|----------------|---------------------|---------------|
| 6,0 A (nastawa z poprzedniego wydania PCB) | 2,5 A | 10,7 h | 14–16 h |
| **8,0 A — przyjęta** | **4,5 A** | **5,95 h** | **8–9 h** |
| 10 A (po wymianie modułu nadnapięciowego i F1 → 20 A) | 6,5 A | 4,12 h | 5–6 h |
| 14,7 A (sufit katalogowy — pełna przebudowa toru) | 11,2 A | 2,39 h | 3–4 h |

> **Najważniejszy skutek uboczny rozbudowy, i jest kontrintuicyjny.**
> Siedem pakietów kupuje **wyłącznie dłuższy postój między doładowaniami**.
> Nie kupuje ani minuty odporności na krótkie przejazdy, bo minimalna dzienna
> jazda podtrzymująca bilans zależy od **prądu ładowania**, a nie od
> pojemności banku:
>
> | Pobór spoczynkowy | Pobór dobowy | Minimalna jazda przy CC 8,0 A | przy CC 6,0 A |
> |-------------------|--------------|-------------------------------|---------------|
> | 80 mA | 1,92 Ah | **26 min/dobę** | 46 min |
> | 130 mA | 3,12 Ah | **42 min/dobę** | 75 min |
> | 185 mA | 4,44 Ah | **59 min/dobę** | 107 min |
> | 300 mA (S3) | 7,20 Ah | **96 min/dobę** | 173 min |
>
> Bilans dobowy poprawiło **podniesienie CC z 6,0 na 8,0 A**, a nie dołożenie
> pakietów.

Ostrzeżenie z poprzedniego wydania robi się przy siedmiu pakietach **dwa razy
mocniejsze**: krótkie przejazdy po mieście nie doładują banku po dłuższym
postoju — pojemność urosła o 75 %, a prąd netto do banku tylko o 12 %. Jeśli
tak wygląda Twój profil użytkowania, **ładowarka sieciowa na czas parkowania
w garażu przestaje być opcją i staje się częścią układu**.

> **Te czasy są optymistyczne o 5–15 %.** Nie stosujemy współczynnika
> przyjęcia ładunku (AGM wymaga oddania 105–115 % pobranych amperogodzin),
> bo poprzednie wydanie też go nie stosowało i wprowadzenie go rozjechałoby
> porównanie „przed / po". Przy 5,95 h fazy CC to dodatkowe 0,3–0,9 h.

---

## 10. Lista zakupowa

> Ta lista dotyczy **wersji docelowej**. Budujesz wariant testowy?
> Wszystko w jednej tabeli: [`LISTA_ZAKUPOWA.md`](LISTA_ZAKUPOWA.md).

### 10.1 Już posiadane

| Element | Rola w torze | Uwaga |
|---------|--------------|-------|
| **XL6019** — moduł step-up | 12 V → 19,5 V dla M910q | ok. **45 W ciągle**, nie 65 W — wymaga ograniczenia poboru CPU, §3.2 i §3.5a |
| **XH-M609** — moduł ochrony | **LVD** (warstwa 3), 11,00 / 12,60 V | przekaźnik 20 A wystarcza; zmierz pobór własny, §7.3 |
| **CSB HR1221W F2** × 8 (12 V / 5,1 Ah AGM) | bank buforowy | **użyj 7 (35,7 Ah)** — jeden zostaje jako zapas; §4.2 mówi, czego ten jeden pakiet nie załatwia |
| Lenovo ThinkCentre M910q Tiny | komputer | |

### 10.2 Do dokupienia — obowiązkowe

| # | Element | Specyfikacja | Szt. | Cena (PLN) |
|---|---------|--------------|------|-----------|
| 1 | **Ładowarka DC-DC** *(wariant A)* | Victron Orion-Tr Smart 12/12-18 lub odpowiednik z presetem **AGM** | 1 | 800–1000 |
| | *albo:* przekaźnik + dioda + moduł CC-CV boost *(wariant B)* | przekaźnik 30 A SPDT + **MBR2545CT** na radiatorze · boost: **„900 W 15 A" z wyświetlaczem** albo **„1500 W 30 A"** — pełne zestawienie w §5.3a i §5.3c. **Nie SZBK07** (to buck, nie boost) i **nie „600 W 10 A"** (za mało zapasu przy CC 8,0 A) | 1+1+1 | 70–180 |
| 2 | **Rozłącznik nadnapięciowy** | **XH-M603** (albo XH-M604), próg 15,30 V / powrót 14,00 V — §6.3 | 1 | 40–80 |
| 3 | ~~Moduł LVD~~ | **posiadany — XH-M609** | — | 0 |
| 4 | **Przekaźnik zapłonu** | Bosch 12 V / 30 A SPDT + podstawka | 1 | 15–25 |
| 5 | **Przekaźnik mocy** (do poz. 2, jeśli styki modułu za słabe) | 12 V / 30 A + podstawka | 1 | 15–25 |
| 6 | **Listwa dystrybucyjna bezpiecznikowa** | 6–8 obwodów ATO/ATC, z pokrywą | 1 | 40–70 |
| 7 | **Bezpiecznik główny + oprawka** | 30 A, oprawka do montażu przy klemie | 1 | 15–25 |
| 8 | **Bezpieczniki inline** | 10 A × 7 (**FB1…FB7**, pakiety) + oprawki, oraz 15 A **MIDI/AMI lub ANL** przed VIN+ modułu XH-M609 (§7.4) | 8 | 25–40 |
| 9 | **Bezpieczniki nożowe** | 5 A, 3 A × 2, 20 A + zapas | kpl. | 10–15 |
| 10 | **Buck 12 → 5 V** (logika) | LM2596, min. 1 A | 1 | 5–10 |
| 11 | **Buck 12 → 5 V** (wyświetlacze) | MP1584 / MP2307, min. 3 A — potrzebny przez **PWM podświetlenia**, patrz niżej | 1 | 5–15 |
| 12 | **Dioda TVS** | 1.5KE33CA lub SMCJ26CA | 2 | 5–10 |
| 13 | **Kondensator elektrolityczny** | 470 µF / 35 V, low-ESR, 105 °C | 2 | 5–10 |
| 14 | **Dioda gaszeniowa** | 1N4007 (na cewki przekaźników) | 5 | 2–5 |
| 15 | **Przewód 6 mm²** | FLRY, czerwony 4 m + czarny 2 m | — | 60–90 |
| 16 | **Przewód 2,5 mm²** | FLRY, czerwony + czarny, po 3 m | — | 25–40 |
| 16a | **Przewód 4 mm²** | FLRY, czerwony + czarny, **po 3 m** — pętla ładowarka → szyna banku wraz z powrotem OUT− do masy, §8.2 | — | 30–50 |
| 17 | **Przewód 1,5 mm²** | FLRY, czerwony + czarny, **po 5 m** — siedem ogonków pakietów po ~0,30 m na biegun plus pętle serwisowe | — | 25–40 |
| 18 | **Przewód 0,75 mm²** | FLRY, kilka kolorów, po 2 m | — | 15–25 |
| 19 | **Konektory oczkowe M6/M8** | do 6 mm², zaciskane | 10 | 15–25 |
| 20 | **Konektory / tulejki / koszulki** | zestaw, koszulki z klejem | kpl. | 30–50 |
| 21 | **Peszel / oplot + przelotki gumowe** | 5 m peszla + komplet przelotek | kpl. | 25–40 |
| 22 | **Skrzynka / wspornik na bank + pasy** | na **7 pakietów (12,6 kg)**; pojemność użytkowa min. 280 × 180 × 101 mm (układ 4 + 3) albo 490 × 90 × 101 mm (rząd); 4 punkty M8 z płytkami rozkładającymi ≥ 40 × 40 × 3 mm; 2 pasy ≥ 250 daN — §4.7 | 1 | 100–200 |
| 22a | **Szyny zbiorcze banku** | 2 × płaskownik miedziany **15 × 2 mm** (min.) albo **20 × 3 mm** (zalecany), dł. ok. 600 mm każdy, + 14 śrub M6 z podkładkami + pokrywa izolacyjna — §4.3 | kpl. | 60–140 |
| 23 | **Rozłącznik masy** | 100 A, kluczykowy lub pokrętło | 1 | 40–70 |
| 24 | **Radiator + wentylator 40 mm** | do XL6019 — przy 45 W obowiązkowe | kpl. | 20–35 |
| 24a | **Kondensator wyjściowy** | 470 µF / 35 V low-ESR na wyjście XL6019 | 1 | 3–6 |
| 24b | **Termistor NTC** | 5 Ω / 5 A, ogranicznik prądu rozruchowego (tylko jeśli §3.2b) | 1 | 3–6 |
| | | | **Razem wariant A** | **~1435–2145 PLN** |
| | | | **Razem wariant B** | **~705–1325 PLN** |

Moduł LVD i przetwornica step-up są już na stanie, więc nie ma ich w tej
tabeli. Wobec wersji czteropakietowej kwota urosła o ok. 145–290 PLN: to
szyny zbiorcze (poz. 22a), większa skrzynka z mocowaniem (poz. 22), trzy
dodatkowe wkładki gałęziowe z oprawkami, wkładka F7 w klasie MIDI/ANL,
przewód 4 mm² do banku i dłuższy 1,5 mm² na ogonki. Same pakiety nic nie
kosztują — leżą w zapasie.

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
[ ] Jeśli pobór wyszedł przy górnej granicy (125 mA) — rozważ wymianę
    modułu na prosty komparator: przy 185 mA łącznie bank siedmiu pakietów
    daje 4,0 dnia do 50 % DoD zamiast 9,3 (§9.2)
[ ] Bezpiecznik F7 15 A przed zaciskiem VIN+, klasa MIDI/AMI albo ANL
    (zdolność wyłączania ≥ 2 kA — §7.4)

Pozostałe
[ ] Ładowarka: CV 14,40 V — bez wyjątków. 13,80 V wprowadza moduł
    w pass-through i WYŁĄCZA ograniczenie prądowe (§5.3b)
[ ] Ładowarka: limit prądu CC 8,0 A (sufit katalogowy 14,7 A dla 7 pakietów
    — ogranicza tor ładowania, nie bank: §6.3)
[ ] Rozłącznik nadnapięciowy: rozwarcie 15,30 V, powrót 14,00 V (§6.4)
[ ] Buck logiki: wyjście 5,0 V
[ ] Buck wyświetlaczy: wyjście 5,0 V
```

### Etap 2 — bank

```
[ ] Pomiar napięcia spoczynkowego każdego z SIEDMIU pakietów osobno
    (rozrzut > 0,2 V = pakiet do odrzucenia)
[ ] Pomiar rezystancji wewnętrznej każdego pakietu mostkiem, jeśli masz czym
    (rozrzut ±10 % daje ~12 % rozrzutu prądów — kilkanaście razy więcej niż
     cała geometria szyny, §4.3)
[ ] Doładowanie wszystkich pakietów do tego samego napięcia PRZED łączeniem
    (przy siedmiu pakietach WAŻNIEJSZE niż przy czterech: prąd wyrównawczy
     przy ΔU 0,20 V rośnie z 4,05 na 4,63 A — to siedmiokrotność 0,64 A,
     którym pakiet jest ładowany w normalnej pracy)
[ ] Bezpiecznik 10 A na „+" każdego pakietu — FB1…FB7, siedem sztuk
[ ] Szyny zbiorcze z płaskownika miedzianego (min. 15 × 2 mm, zalecane
    20 × 3 mm), po siedem odczepów M6 co 70 mm, ta sama kolejność na „+" i „−"
[ ] Odbiór PO PRZEKĄTNEJ: „+" z odczepu 1, „−" z odczepu 7 (§4.3).
    NIGDY oba bieguny z tego samego końca szyny
[ ] Ogonki pakiet → szyna 1,5 mm², równa długość pętli ±30 mm; nadmiar
    zwinięty w pętlę serwisową, NIE przycięty
[ ] Pomiar napięcia banku po połączeniu
[ ] Czujnik NTC przyklejony do boku pakietu #4 — środkowego z siedmiu
[ ] Pokrywa izolacyjna na obu szynach (zwarcie na szynie to ~2,4 kA)
```

### Etap 3 — montaż w aucie, bez podłączenia do akumulatora

```
[ ] Skrzynka banku (7 pakietów, 12,6 kg) zamocowana na CZTERECH śrubach M8
    z płytkami rozkładającymi ≥ 40 × 40 × 3 mm pod blachą podłogi (§4.7)
[ ] Bank przypięty dwoma pasami ≥ 250 daN
[ ] Skrzynka NIE zamknięta hermetycznie — szczelina wentylacyjna zostaje
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
[ ] Pomiar: prąd na WYJŚCIU ładowarki ≤ 8 A (obciążenie PLUS ładowanie)
[ ] Pomiar: prąd wpływający do szyny banku ~4,5 A (cęgi na przewodzie
    ładowarka → szyna — to jest ta część, która ładuje pakiety)
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
[ ] Pomiar poboru w S3 — oczekiwane 200–460 mA (§2.1)
[ ] Po 2 h → impuls 5 s, maszyna gaśnie, pobór spada do 50–150 mA (§2.1)
[ ] Domena A dalej działa — test pilota 433 MHz i BLE bagażnika
```

### Etap 7 — próba postoju

```
[ ] Auto zaparkowane na 48 h bez uruchamiania
[ ] Pomiar napięcia banku przed i po
[ ] Spadek zgodny z pomiarem z §2.1 (w S3 przy 300 mA to 14,4 Ah przez 48 h,
    czyli 40 % DoD z 35,7 Ah — próba mieści się pod 50 % DoD i nie trzeba jej
    już obchodzić wyłącznikiem głównym ani skracać. To nadal zejście poniżej
    rutynowego reżimu 30 % DoD, do którego przy 300 mA starcza 35,7 h)
[ ] Akumulator rozruchowy bez zmian — auto odpala normalnie
```

---

## 12. Serwis i kontrola okresowa

| Częstotliwość | Czynność | Kryterium |
|---------------|----------|-----------|
| Co miesiąc | Napięcie banku po nocy postoju | > 12,4 V |
| Co 3 miesiące | Napięcie każdego z **siedmiu** pakietów osobno | rozrzut < 0,2 V |
| Co 3 miesiące | Dokręcenie **14 odczepów** szyn i biegunów pakietów | bez luzu |
| Co 6 miesięcy | Napięcie ładowania przy pracującym silniku | ≤ 14,40 V (lub wg kompensacji) |
| Co 6 miesięcy | Prąd spoczynkowy logiki | ~60 mA ± 20 % |
| Co 12 miesięcy | Test pojemności banku (rozładowanie kontrolowane) | > 70 % znamionowej, czyli **> 25,0 Ah** |
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
- **Limit prądu wymaga przeliczenia, a nie odrzucenia.** Karta katalogowa
  CSB podaje **2,1 A na pakiet**. Przy banku czterech dawało to sufit 8,4 A
  i stare „15–20 A" było przekroczeniem dwukrotnym. Przy dzisiejszym banku
  **siedmiu** sufit wynosi **14,7 A** i dolna wartość z tamtych notatek
  mieści się w karcie katalogowej. Zarzut zmienia więc adresata: nastawy
  ładowania nie ogranicza już akumulator, tylko **tor ładowania** — najsłabsze
  ogniwo to płytka XH-M603 (8,0 A, §6.3). Obowiązująca nastawa to
  **CC 8,0 A**, czyli 54 % sufitu katalogowego.

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

Projekt jest dopasowany pod moduły, które już są, a nie odwrotnie. Przy banku
siedmiu pakietów wynikają z tego **trzy** realne ograniczenia:

| Moduł | Ograniczenie | Konsekwencja |
|-------|--------------|--------------|
| **XL6019** | limit prądu klucza 5 A → ok. **45 W** wyjścia, nie 65 W | konieczny limit poboru pakietu CPU (§3.5a); bez niego pełne obciążenie czterech wątków wyjdzie poza możliwości modułu |
| **XH-M609** | pobór własny do 125 mA wg spec + zakres zasilania od 12 V | wchodzi wprost w budżet postoju (§9) i wymaga sprawdzenia pracy przy progu 11 V (§7.3) |
| **XH-M603** *(nowe przy siedmiu pakietach)* | realna obciążalność płytki ok. **10 A**, spec „≤ 8 A" | wyznacza nastawę **CC 8,0 A** dla całego układu i zamyka tor na 54 % sufitu katalogowego banku (14,7 A); to on, a nie akumulator, decyduje dziś o czasie ładowania (§6.3, §9.4) |

Żadne z nich nie dyskwalifikuje modułu — XL6019 obchodzi się konfiguracją
systemu, a XH-M609 pomiarem i ewentualną wymianą na prostszy komparator.

> **Uwaga redakcyjna.** Poprzednie wydanie wskazywało tu „dobór liczby
> pakietów" jako drogę wyjścia dla XH-M609. Liczba pakietów urosła z czterech
> do siedmiu i to faktycznie złagodziło problem — przy spec-owych 185 mA
> postój do 50 % DoD rośnie z 2,3 na 4,0 dnia — ale go nie usunęło. Pomiar
> z §7.3 nadal rozstrzyga, w którym wierszu tabeli §9.2 siedzisz, a kierunek
> „dołóż jeszcze pakietów" jest już wyczerpany.

### 13.7 Decyzje otwarte po przejściu na siedem pakietów

Rzeczy, które rozbudowa banku postawiła, a których ta dokumentacja **nie
rozstrzyga sama** — wymagają pomiaru albo decyzji właściciela.

| # | Sprawa | Dlaczego otwarta | Gdzie |
|---|--------|------------------|-------|
| 1 | **Miejsce montażu — zmierz przed zakupem czegokolwiek** | Repozytorium nie podaje ani jednego wymiaru przestrzeni pod fotelem pasażera. Nie da się na papierze sprawdzić, czy 300 × 200 × 115 mm tam wejdzie; najbardziej podejrzana jest wysokość. Cały rachunek zakłada, że miejsce się znajdzie | §4.2, §4.7 |
| 2 | **Co, jeśli bank trzeba rozdzielić na dwie lokalizacje** | Wzór 9 · r / R zakłada jedną parę szyn. Dwie szyny spięte mostkiem to inny obwód i asymetrię trzeba policzyć osobno — nie da się tego rozstrzygnąć z góry bez znajomości trasy mostka | §4.2, §4.3 |
| 3 | **Nośność podłogi i kryterium wytrzymałościowe** | 2,47 kN przy 20 g to wymaganie, ale nośność blachy w tym miejscu jest nieznana. Kryteria 10 g / 20 g są przyjęte z praktyki, nie z normy, do której projekt miałby się stosować | §4.7 |
| 4 | **Siedem czy osiem pakietów** | Przy ośmiu istniałoby symetryczne drzewo 2-4-8, sufit wynosiłby 16,8 A, a pojemność 40,8 Ah. Kosztem jest zerowy zapas — ale zapas jednego pakietu i tak nie pozwala wymienić kompletu (§4.3). Wysiłek montażowy jest identyczny. To decyzja właściciela, nie wynik rachunku | §4.2, §9.2 |
| 5 | **Obciążalność płytki XH-M603 (~10 A)** | Liczba pochodzi z oględzin, nie z karty. Od niej zależy nastawa CC 8,0 A i cała reszta rozdziału 5–6. Zmierz temperaturę zacisków przy 8 A przez 30 min | §6.3 |
| 6 | **Czy istnieje zamiennik z wolnym stykiem COM/NO** | Repozytorium nie zawiera potwierdzonych danych XH-M604 (czy styk jest wyprowadzony i jaka jest obciążalność jego płytki). Bez sprawdzenia miernikiem na sztuce droga powyżej CC 8,0 A jest zamknięta | §6.3 |
| 7 | **Pobór własny XH-M609 — wciąż niezmierzony** | Siedem pakietów przesuwa cały zakres w górę, ale nie zwalnia z pomiaru: przy 185 mA łącznie nawet 35,7 Ah daje tylko 4,0 dnia do 50 % DoD | §7.3, §9.2 |
| 8 | **Obciążenie szyny podczas jazdy (3,5 A) nie jest w repozytorium wyprowadzone** | Czas ładowania jest odwrotnie proporcjonalny do prądu netto. Gdyby realne obciążenie wynosiło 5 A, ładowanie od LVD rośnie z 5,95 na 8,9 h fazy CC. Zmierz razem z poborem LVD | §9.4 |
| 9 | **Kolizja z etapem 5 z [`PCB_ZASILANIE.md`](PCB_ZASILANIE.md) §7** | Wymiana XL6019 na moduł „1500 W 30 A" bez limitu RAPL podnosi obciążenie do ~5,1 A. Przy CC 8,0 A do banku zostaje 2,9 A netto i ładowanie od LVD wydłuża się do 9,2 h. Siedem pakietów i nowa przetwornica **nie mogą być planowane niezależnie** | §9.4, PCB §7 |
| 10 | **Dodanie wkładki w torze ładowania po stronie banku** | Zwarcie odcinka ładowarka → szyna banku jest zasilane wprost z banku prądem ~2,4 kA i nic go nie przerywa. To **dodanie elementu**, nie korekta liczby — nie wpisano go do tabel | §8.1 |
| 11 | **Zdolność wyłączania wkładek** | Wartości ATO ~1 kA, MIDI/AMI ≥ 2 kA, ANL ≥ 2,7 kA @ 32 V DC pochodzą z typowych kart katalogowych, nie z repozytorium. Przed zakupem potwierdź w karcie konkretnej wkładki | §7.4, §8.1 |
| 12 | **Zdolność łączeniowa chwilowa rozłącznika masy 100 A** | Typowe egzemplarze podają ~2500 A chwilowo, a prąd zwarciowy prospektywny banku to ~2,4 kA. Sprawdź kartę swojego egzemplarza i rozłączaj wyłącznie bez obciążenia | §8.4 |
| 13 | **Wiek i pochodzenie pakietów** | Rozrzut rezystancji ±10 % daje ~12 % rozrzutu prądów — kilkanaście razy więcej niż cała geometria szyny. Jeżeli siedem sztuk nie jest z jednej dostawy i w zbliżonym wieku, **to** jest realne ryzyko, a nie nieparzystość. Zmierz rezystancję mostkiem, nie tylko napięcie spoczynkowe | §4.3, §11 Etap 2 |
| 14 | **Skąd zasilać wyświetlacz 1,8" na ESP32** | Przy 35,7 Ah wariant „z szyny buforowanej" mieści się w budżecie (postój 5,3–3,0 zamiast 9,3–4,0 dnia) i jest zgodny z architekturą, ale wymaga dopisania panelu do §9.1 i wiersza w §8.2. Wariant „+15" jest prostszy, lecz kłóci się z §2 | [`WYSWIETLACZ_ESP32_1V8.md`](WYSWIETLACZ_ESP32_1V8.md) |

Dwie rzeczy, które trzeba wiedzieć o samych liczbach:

- **Brak współczynnika przyjęcia ładunku.** AGM wymaga oddania 105–115 %
  pobranych amperogodzin, więc wszystkie czasy ładowania z §9.4 są zaniżone
  o 5–15 %. Nie wprowadzamy poprawki, bo poprzednie wydanie też jej nie
  stosowało i rozjechałaby porównanie „przed / po".
- **Brak krzywych rozładowania i danych Peukerta dla HR1221W.** Przy 3,5 A
  siedem pakietów pracuje z krotnością C/10,2, czyli powyżej rozładowania
  20-godzinnego, na którym oparta jest pojemność 5,1 Ah. Czasy dla siódemki
  są przez to **mniej** optymistyczne niż te same liczby były dla czwórki
  (C/5,8), ale skali korekty nie da się policzyć bez tych krzywych.

---

## Powiązane dokumenty

| Dokument | Zakres |
|----------|--------|
| [`PCB_ZASILANIE.md`](PCB_ZASILANIE.md) | **dwie płytki drukowane do wytrawienia** — tor ładowania i dystrybucja zamiast „pająka"; dobór przetwornicy 19,5 V ≤ 100 zł |
| [`WDROZENIE_M910Q.md`](WDROZENIE_M910Q.md) | pełne wdrożenie: sprzęt, BIOS, OS, usługi, odbiór |
| [`X86_PLATFORM_SETUP.md`](X86_PLATFORM_SETUP.md) | referencja krok-po-kroku (EN) — pamiętaj o §13 |
| [`x86-production/10-power-suspend.html`](x86-production/10-power-suspend.html) | zasilanie + S3 w wersji ilustrowanej |
| [`x86-production/02-assembly.html`](x86-production/02-assembly.html) | montaż mechaniczny, layout USB |
| [`ARDUINO_SETUP_GUIDE.md`](ARDUINO_SETUP_GUIDE.md) | okablowanie trzech płytek Arduino, sygnały pojazdu |
| [`SCHEMATY_POLACZEN.md`](SCHEMATY_POLACZEN.md) | tabele połączeń, przekroje, bezpieczniki, kolejność montażu |
| [`../schematics/README.md`](../schematics/README.md) | indeks schematów |
