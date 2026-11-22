# Zasilanie buforowane — Lenovo M910q w Alfa Romeo 156

Kompletny opis układu zasilania head unitu BCM v8.5: bufor z akumulatorów
CSB HR1221W (AGM) w dwóch koszach w bagażniku, ładowanie z dwóch modułów
XY-SK120, blokada przeładowania, ochrona przed głębokim rozładowaniem,
sterowanie stanem komputera i zalewana przetwornica step-up 12 → 20 V.

**Schematy blokowe:** [`../schematics/power_buffered_m910q.svg`](../schematics/power_buffered_m910q.svg) ·
[`../schematics/charging_lvd.svg`](../schematics/charging_lvd.svg) ·
[`../schematics/power_domains_m910q.svg`](../schematics/power_domains_m910q.svg)

> **Rysunki zgodne z tym dokumentem (22.11.2026).** Wszystkie arkusze
> zasilania — `charging_lvd`, `power_domains_m910q`, `wiring_power_modules`,
> `power_test_build`, `schematic_test_build`, `wiring_test_build` — są
> przerysowane pod bieżący projekt i powstają z generatorów `gen_*.py`;
> pliki PNG w `schematics/png/` są wyrenderowane z bieżących SVG, a mozaika
> miedzi PCB ma plik do druku na laminat 600 dpi
> (`schematics/png/pcb_power_etch_600dpi.png`). Przy każdej rozbieżności
> obowiązuje ten dokument.

**Projekt koszy na bank (stal, 4 + 3 szt.):** [`mechanika/kosze_HR1221W_4+3.pdf`](mechanika/kosze_HR1221W_4+3.pdf) — streszczenie w §4.7

**Jak to pospiąć — zacisk po zacisku:** [`SCHEMATY_POLACZEN.md`](SCHEMATY_POLACZEN.md)

**Wdrożenie całości:** [`WDROZENIE_M910Q.md`](WDROZENIE_M910Q.md)

---

## Spis treści

1. [Po co bufor](#1-po-co-bufor)
2. [Architektura — jedna szyna, trzy stany maszyny](#2-architektura--jedna-szyna-trzy-stany-maszyny)
3. [Przetwornica step-up 12 → 20 V, 10 A (zalewana)](#3-przetwornica-step-up-12--20-v-10-a-zalewana)
4. [Bank akumulatorów CSB HR1221W](#4-bank-akumulatorów-csb-hr1221w)
5. [Ładowanie — 2 × XY-SK120](#5-ładowanie--2--xy-sk120)
6. [Blokada przeładowania](#6-blokada-przeładowania)
7. [LVD — moduł XH-M609](#7-lvd--moduł-xh-m609)
8. [Bezpieczniki, przekroje, masa](#8-bezpieczniki-przekroje-masa)
9. [Budżet energetyczny i czas postoju](#9-budżet-energetyczny-i-czas-postoju)
10. [Lista zakupowa](#10-lista-zakupowa)
11. [Procedura pierwszego uruchomienia](#11-procedura-pierwszego-uruchomienia)
12. [Serwis i kontrola okresowa](#12-serwis-i-kontrola-okresowa)
13. [Znane rozbieżności i luki](#13-znane-rozbieżności-i-luki)
14. [Wybudzanie z zewnątrz: drzwi, telefon (IR), wejście EXT](#14-wybudzanie-z-zewnątrz-drzwi-telefon-ir-wejście-ext)

---

## 1. Po co bufor

Trzy niezależne powody — każdy sam w sobie wystarczyłby:

| Problem | Bez bufora | Z buforem |
|---------|-----------|-----------|
| **Rozruch silnika** | Instalacja 12 V zapada na 6–8 V przez 200–600 ms. M910q gubi zasilanie i twardo się resetuje przy każdym przekręceniu kluczyka. | Bank trzyma szynę powyżej 12 V przez cały rozruch — komputer nawet nie mrugnie. |
| **Funkcje na postoju** | Pilot szyb 433 MHz i bramkowany BLE przycisk bagażnika muszą żyć non stop. Wpięte w akumulator rozruchowy rozładują go w kilka dni. | Domena A żyje z banku. Akumulator rozruchowy jest odizolowany i zawsze gotowy do rozruchu. |
| **Jakość napięcia** | Instalacja auta to śmietnik EMI: przepięcia od cewek, load dump z alternatora, tętnienia. | Bank o pojemności 35,7 Ah to gigantyczny kondensator — wygładza wszystko, co jest za nim. |

Kluczowa konsekwencja architektury: **akumulator rozruchowy nigdy nie zasila
head unitu na postoju**. Rozdzielają je przekaźnik ładowania K1 (rozwarty przy
zgaszonym silniku) — sam w sobie wystarczający — oraz rozłączniki XH-M603,
które bez zasilania mają być rozwarte; to drugie jest przyjęciem do
sprawdzenia na stole (§5.4, §6.4 pkt 6). Auto zawsze odpali, choćby bank był
pusty.

---

## 2. Architektura — jedna szyna, trzy stany maszyny

Rysunek: [`../schematics/power_domains_m910q.svg`](../schematics/power_domains_m910q.svg)
(przy rozbieżności obowiązuje tekst §2)

Wszystko wisi na **jednej szynie buforowanej** za LVD i wyłącznikiem
głównym. Zapłon nie odcina już żadnego odbiornika — jest wyłącznie
**sygnałem**, który Arduino zamienia na „naciśnięcie" przycisku zasilania
M910q.

| | |
|---|---|
| **Odbiorniki stale zasilane** | M910q (przez step-up 20 V), hub USB, oba wyświetlacze, Arduino Pro Micro, Nano #1, Nano #2, HM-10 BLE, RXB6 433 MHz, moduł 9 przekaźników, DAC USB, graber AHD; opcjonalnie telefon w aucie (Redmi) przez wstrzykiwacz 5 V (§9.1, §14.6) |
| **Przekaźniki w torze mocy** | **K1 w ładowaniu** — rozłącza tor ładowania od instalacji auta przy zgaszonym silniku (§5.4) — oraz przekaźnik samego LVD (§7). **Przekaźnika zapłonu przed odbiornikami nie ma** |
| **Rola zapłonu** | sygnał do Arduino → impuls na styki przycisku zasilania → S3 albo wybudzenie; ten sam sygnał (albo D+ alternatora) steruje cewką K1 |

### 2.1 Trzy stany i trzy poziomy poboru

Bank ma **7 pakietów (35,7 Ah)**. Do 50 % DoD zostaje **17,85 Ah**
użytecznych, a w reżimie rutynowym 30 % DoD — **10,71 Ah**.

| Stan | Co pobiera | Pobór z banku | 7 pakietów (35,7 Ah), do 50 % DoD |
|------|-----------|---------------|----------------------|
| **Praca** | wszystko | **≈ 50–75 W, czyli ≈ 4–6 A** przy 12,6 V; przyjmujemy **5 A** | **~3,6 h** przy zgaszonym silniku (17,85 Ah / 5 A) |
| **S3** | M910q w S3 + Arduino + LVD + jałowy step-upu | **200–460 mA** (zmierzone z poprzednią przetwornicą XL6019) **+ I_jał** | **1,6–3,7 dnia** bez I_jał |
| **Wyłączony** (impuls 5 s) | przetwornice + Arduino + LVD | **50–150 mA** (oszacowane z poprzednią przetwornicą XL6019) **+ I_jał** | **5,0–14,9 dnia** bez I_jał |

Skąd 5 A w pracy — rachunek przy 12,6 V na szynie (podczas jazdy szyna stoi
wyżej, na 13,5–14,4 V, więc prąd jest wtedy o kilka procent mniejszy):

| Odbiornik | Moc / prąd typowy | Szczyt |
|-----------|-------------------|--------|
| M910q przez step-up (sprawność 0,90) | 30 W na wtyku → 33 W z szyny → **2,65 A** | 65 W → 72 W → 5,7 A (przy 11,0 V: 6,6 A) |
| Wyświetlacze (buck LM2596) | **~0,8 A** | ~1,5 A |
| Hub USB z peryferiami | **~0,7 A** | ~1,0 A |
| Domena A (logika, cewki przekaźników) | **~0,2 A** | ~0,5 A |
| Telefon przez wstrzykiwacz 5 V (opcja) | **~0,5 A** (doładowuje się) | ~0,9 A |
| **Razem** | **≈ 4,85 A ≈ 5 A** (≈ 61 W) | ≈ 9,6 A przy 12,6 V, **≈ 10,5 A przy 11,0 V** |

Widełki 4–6 A to zakres od samego dashboardu (M910q ~20 W, telefon
naładowany) do Android Auto z dekodowaniem wideo (~40 W) i ładującym się
telefonem. Poprzednie wydanie podawało tu „10–55 W (3,5 A)" — 55 W przy
12,6 V to 4,4 A, a nie 3,5 A; liczba 3,5 A wynikała z limitu RAPL dla
słabego XL6019 i pomijała telefon. Obie rzeczy przestały obowiązywać (§3).

> **Pobór w S3 jest zmierzony — ale z poprzednią przetwornicą.** Pomiar
> 200–460 mA ([`WDROZENIE_TESTOWE.md`](WDROZENIE_TESTOWE.md) §3.1a) był
> robiony z M910q zasilanym **przez XL6019**, a wiersz „Wyłączony" też
> liczono z nią. Nowa zalewana przetwornica 20 V / 200 W wisi na szynie
> **cały czas** — w S3 i po wyłączeniu — i dokłada **własny prąd jałowy
> I_jał**, którego sprzedawcy nie podają. Dopóki go nie zmierzysz (§3.4,
> §11 Etap 1), oba wiersze i wszystkie czasy postoju z §9.2 są **dolną
> granicą poboru**, czyli górną granicą czasu. Wyświetlacz gaśnie razem
> z komputerem, bo M910q **odcina zasilanie portów USB w S3** — z szyny
> ciągną wtedy tylko sam komputer i Arduino. To także przesądza dwie rzeczy:
> „Wake on USB" jest tu bezużyteczne (port jest martwy), a Arduino **musi**
> mieć własne 5 V z MP1584, inaczej nie ma czym nacisnąć przycisku.
> Telefon na buforze (opcja z §14.6) dokłada do S3 i do stanu wyłączonego
> swój pobór — §9.1.

Kolumna czasów jest liczona **prądem, a nie mocą**: pojemność katalogowa C20
razy frakcja DoD, podzielona przez pobór, bez poprawki Peukerta i bez korekty
temperaturowej. Wiersz „Praca" stoi na 5 A z banku — tym samym obciążeniu,
na którym opiera się rachunek ładowania w §9.4.

W wierszu **Wyłączony** rozrzut (100 mA) bierze się w całości z **własnego
poboru XH-M609** (20–125 mA wg wersji płytki); do tego dochodzi nieznany
I_jał step-upu — to dwie liczby warte zmierzenia multimetrem. W wierszu
**S3** jest inaczej: sam M910q w S3 daje 160–320 mA rozrzutu (pomiar
z poprzednią przetwornicą XL6019, [`WDROZENIE_TESTOWE.md`](WDROZENIE_TESTOWE.md) §3.1a), czyli
więcej niż LVD. Tam zmierzyć trzeba wszystkie trzy.

Wszystko do 50 % DoD. Wniosek jest praktyczny: **S3 do krótkich postojów,
twarde wyłączenie do długich**. Arduino przełącza między nimi samo — po
2 godzinach zgaszonego zapłonu daje dłuższy impuls i maszyna gaśnie
całkowicie. Powrót to znowu krótki impuls.

> **Siedem pakietów nie zmienia bilansu dobowego.** Kupuje dłuższy postój
> między doładowaniami, ale minimalna dzienna jazda potrzebna do utrzymania
> bilansu zależy od **prądu ładowania netto**, a nie od pojemności banku —
> tabela w §9.4.

### 2.2 Dlaczego nie przekaźnik odcinający komputer

Wcześniejsze wydanie tej dokumentacji odcinało M910q i wyświetlacze
przekaźnikiem zapłonu („domena B"). Model został **porzucony** — oto
dlaczego:

| | Przekaźnik odcinający | Stałe zasilanie + S3 |
|---|---|---|
| Postój (7 pakietów) | ~9,3 dnia | ~1,6–3,7 dnia w S3, ~5,0–14,9 po wyłączeniu |
| Wybudzenie | zimny start ~40 s | **~3 s** z S3 |
| Ryzyko ucięcia zapisu na dysk | **przy każdym przekręceniu kluczyka** | mniejsze — maszyna schodzi do S3 sama, ale LVD, wyłącznik główny i luźny styk nadal tną prąd |
| Przekaźnik zapłonu w torze mocy | przekaźnik 30 A + okablowanie | **brak** |
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
wpiąć w zasilanie logiki panelu idące po USB. Drugi powód: z portów USB
M910q i tak nie wyciągniesz prądu dla dwóch paneli z zapasem, a osobny buck
na 12 V nie obciąża toru 20 V komputera.

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

## 3. Przetwornica step-up 12 → 20 V, 10 A (zalewana)

To jedyny element toru, który zasila komputer bezpośrednio. Poprzednie
wydanie opierało się na posiadanym module XL6019 — **ten moduł nie daje rady**:
limit prądu klucza 5 A ogranicza go do ok. 45 W ciągłej mocy wyjściowej, co
wymuszało limit RAPL 28 W na CPU. Zastępuje go zalewany moduł 200 W, który
przy realnym poborze M910q pracuje z dużym zapasem i bez żadnych ograniczeń
programowych.

### 3.1 Napięcie: dlaczego 20 V, a nie 19 V

Oryginalny zasilacz M910q to **20 V / 65 W**. Dokumentacja produkcyjna w tym
repozytorium (`docs/x86-production/02-assembly.html`) podaje, że **M910q
pracuje w zakresie 19–21 V i nie wystartuje poza nim**.

Przetwornica stoi w bagażniku przy koszach (§8a.1), a M910q przy nogach
pasażera — **ok. 4 m przewodu**. Spadek na tej trasie liczymy na pętli
(„+" i „−"), miedź ρ = 0,0172 Ω·mm²/m:

| Wielkość | Wartość |
|----------|---------|
| Rezystancja pętli 2 × 4 m, 4 mm² | 0,0172 × 8 / 4 = **34,4 mΩ** |
| Spadek przy 45 W (2,26 A) | **0,078 V** |
| Spadek przy 65 W (3,27 A) | **0,112 V** |
| Odcinek oryginalnego kabla z wtykiem (0,3–0,4 m, przekrój nieznany) | kilkadziesiąt mV — zmierzyć |

Przy 20,0 V na wyjściu modułu zostaje na wtyku **ok. 19,9 V** (19,8 V
w najgorszym razie) — pewnie w oknie 19–21 V. Moduł 19 V zszedłby w tym
samym rachunku do 18,8–18,9 V, **poniżej dolnej granicy** — dlatego 20 V.

> Zalewane moduły 20 V są zwykle **nieregulowane** (brak potencjometru).
> Nie ma czego „podkręcać" — sprawdzasz tylko, czy dana sztuka trzyma
> napięcie (§3.4). Gdyby wyjście bez obciążenia przekraczało 20,5 V, sztukę
> odrzuć: 21 V to górna granica okna M910q.

### 3.2 Jaki moduł i ile prądu bierze z banku

**Rodzina, nie konkretny model.** Szukasz bezmarkowego, zalewanego żywicą
modułu boost w obudowie IP67/IP68, opisywanego zwykle jako
„DC-DC step-up 12 V → 20 V 10 A 200 W" (do laptopa / do auta), sprzedawanego
na Allegro i AliExpress pod wieloma nazwami. Typowe parametry z opisów
sprzedawców (nie z karty katalogowej — tej dla takich modułów zwykle nie ma):

| Parametr (wg opisu sprzedawcy) | Typowo |
|-------------------------------|--------|
| Wejście | 9–18 V (czasem 10–16 V — sprawdź opis konkretnej oferty; potrzebujesz pracy od 11 V w górę) |
| Wyjście | 20 V stałe, 10 A, 200 W |
| Sprawność | „90–93 %" — **deklaracja sprzedawcy**, do rachunku bierzemy 90 % |
| Obudowa | aluminium albo tworzywo zalane żywicą, IP67/IP68, przewody wyprowadzone na stałe |

Ile to bierze z banku (sprawność 0,90 — konserwatywnie; przy deklarowanych
0,93 prąd jest o ok. 3 % mniejszy):

| Moc na wtyku M910q | Moc z szyny | 12,6 V (bank w spoczynku) | 12,0 V | 11,0 V (próg LVD) |
|--------------------|-------------|---------------------------|--------|-------------------|
| 30 W (dashboard) | 33,3 W | **2,65 A** | 2,78 A | 3,03 A |
| 45 W (AA + wideo) | 50,0 W | **3,97 A** | 4,17 A | 4,55 A |
| 65 W (znamionowa) | 72,2 W | **5,73 A** | 6,02 A | **6,57 A** |

Straty w module: przy 90 % — 3,3 / 5,0 / 7,2 W, przy deklarowanych 93 % —
2,3 / 3,4 / 4,9 W (30 / 45 / 65 W).

**Zapas.** 65 W to **33 %** mocy z tabliczki (200 W). Bezmarkowy moduł
zalewany realnie oddaje ciągle zwykle mniej niż napis — nawet gdyby
wytrzymywał tylko ~70 % tabliczki (ok. 140 W), znamionowe 65 W M910q to
nadal **ok. 45 %** jego realnej mocy, a typowe 30–45 W to 20–30 %. Stąd:

- **limit RAPL nie jest potrzebny** — M910q może brać pełne 65 W (§3.5a
  zostaje jako opcja, np. dla cichszej pracy albo niższej temperatury);
- **nie łącz dwóch przetwornic równolegle** „dla mocy" — nie ma po co, a moduły
  bez podziału obciążenia i tak by się o nią biły.

**Wejście:** z szyny za LVD przez bezpiecznik **F8 10 A** (6,57 A przy 11 V
i 65 W to 66 % wkładki), przewód **4 mm²**. **Wyjście:** 4 mm² do M910q
(3,3 A), bezpiecznik **5 A** przy wyjściu przetwornicy, wtyk z uciętego
oryginalnego kabla (§3.3).

### 3.2a Zachowanie przy braku sterowania

Boost **nie potrafi dać napięcia niższego niż wejściowe**. Jeżeli moduł
wyłączy regulację (np. po zejściu wejścia poniżej swojego minimum), na
wyjściu zwykłego boostu zostaje napięcie wejściowe pomniejszone o spadek na
diodzie (~11–12 V). M910q przy takim napięciu nie wystartuje, ale też się nie
uszkodzi. Jak zachowuje się konkretna sztuka — sprawdzasz w §3.4 (próba
przy 11 V i poniżej).

Praktyczna konsekwencja: **wyjścia przetwornicy nie da się użyć jako
wyłącznika komputera** — i nie jest to potrzebne. M910q jest zasilany stale,
a wyłącza go impuls na przycisk zasilania (§2.1).

### 3.2b Prąd rozruchowy

Kondensatory wejściowe M910q przy załączeniu pobierają krótki impuls prądu.
Moduł 200 W zwykle przyjmuje go bez kłopotu; jeżeli jednak przy
podłączaniu M910q wejdzie w zabezpieczenie i startuje cyklicznie („czkawka"):

- **kondensator 470 µF / 35 V low-ESR na wyjściu** przetwornicy.

Jeżeli czkawka zostaje mimo kondensatora, ten egzemplarz **nie przechodzi
testu z §3.4** — zwróć go albo wymień na inny. Ewentualnie można sprawdzić
na stole moduł typu „soft-start / ogranicznik prądu rozruchowego” (kategoria,
nie konkretny model), ale przyjmij go dopiero, gdy pomiar pokaże
**≥ 19,5 V na wtyku** przy pełnym obciążeniu i przy przejściu S3 → wznowienie.

**Bez termistora NTC szeregowo na wyjściu.** Dlaczego: M910q jest zasilany
stale i na postoju śpi w S3, pobierając po stronie 20 V ok. 0,1–0,2 A —
przy takim prądzie NTC się nie nagrzewa i zostaje przy swojej zimnej
rezystancji (kilka Ω). Przy wznowieniu prąd skacze do 1,5–3,3 A i na zimnym
NTC spada kilka woltów — M910q dostaje brown-out. Nawet nagrzany NTC typowo
zostawia dziesiąte części oma (szacunek, nie wartość z karty), czyli
0,15–0,5 V straty przy 3 A, a nieregulowany moduł 20 V nie ma czym tego
nadrobić względem kryterium ≥ 19,5 V.

### 3.3 Wtyk zasilania

M910q używa firmowego wtyku Lenovo (slim tip). Kupowanie „uniwersalnej"
końcówki to loteria — pasowanie mechaniczne i obecność środkowego pinu
identyfikacyjnego różnią się między wersjami.

**Najpewniejsze rozwiązanie: poświęć oryginalny zasilacz.** Odetnij kabel
30–40 cm od wtyku, sprawdź polaryzację multimetrem (środek = „+", ekran =
masa) i połącz z przewodem 4 mm² idącym od przetwornicy (tulejka zaciskana
albo złączka, koszulka z klejem). Zyskujesz gwarantowane pasowanie
mechaniczne; cienki odcinek oryginalnego kabla jest krótki, więc spadek na
nim jest mały — zmierz go w §3.4.

> **Pin identyfikacyjny.** W zasilaczach Lenovo slim-tip środkowy pin
> przenosi sygnał identyfikacyjny z układu w kostce zasilacza. Po odcięciu
> kabla ten sygnał znika. Laptopy ThinkPad wyświetlają wtedy ostrzeżenie
> i ograniczają ładowanie; **komputery ThinkCentre Tiny w praktyce startują
> normalnie**, ale tego nie da się założyć w ciemno dla konkretnej sztuki.
> Dlatego test z §3.4 jest obowiązkowy i musi się odbyć **przed** zabudową
> auta.

### 3.4 Test na biurku — obowiązkowy

Moduł jest bezmarkowy, więc **każdą sztukę sprawdzasz po zakupie**, zanim
cokolwiek trafi do samochodu:

```bash
# 1. Zasil przetwornicę z akumulatora 12 V (albo zasilacza laboratoryjnego
#    z limitem prądu 10 A). Zmierz wyjście BEZ obciążenia.
# 2. Podłącz M910q. Musi wystartować i wejść do systemu.
# 3. Obciąż CPU i sprawdź, czy napięcie się trzyma:
sudo apt install -y stress-ng
stress-ng --cpu 4 --timeout 1800s
```

W trakcie testu mierz i zapisuj:

| Pomiar | Wartość dopuszczalna |
|--------|---------------------|
| Napięcie wyjściowe bez obciążenia | **19,9–20,5 V** (powyżej 20,5 V — odrzuć sztukę, §3.1) |
| Napięcie na wyjściu modułu przy ~60 W | **≥ 19,8 V** |
| Napięcie na wtyku M910q pod obciążeniem | **≥ 19,5 V** przez cały czas (0,5 V zapasu nad 19 V) |
| Prąd wejściowy przetwornicy | zgodny z §3.2 (±10 %), bez pulsowania |
| **Prąd jałowy I_jał** przy wejściu 12,6 V: (a) M910q odłączony, (b) M910q wyłączony, (c) M910q w S3 | **zapisz wszystkie trzy** — (a) to I_jał do §9.2, (b)/(c) minus pobór samego M910q pokazuje, czy moduł przy małym obciążeniu nie bierze więcej niż bez niego. Producent tej liczby nie podaje, więc nie ma progu „dobrze/źle" — wchodzi wprost w budżet postoju (§2.1, §9.2) |
| Temperatura obudowy po 30 min przy ~60 W | **< 60 °C** — nasze kryterium, nie dane producenta; powyżej 70 °C moduł jest słabszy niż opis albo za słabo chłodzony |
| Stabilność systemu | brak resetów, brak wpisów o zaniku zasilania w `journalctl -b` |

Obciążenie ~60 W dają razem `stress-ng` na CPU i odtwarzanie wideo; jeżeli
M910q tyle nie pobiera, użyj obciążenia elektronicznego albo opornika mocy
(np. 6,8 Ω / 100 W ≈ 59 W przy 20 V) zamiast komputera.

**Powtórz test przy napięciu wejściowym 11,0 V** (symulacja rozładowanego
banku tuż przed progiem LVD). To najgorszy przypadek — prąd wejściowy
~6,6 A i największe grzanie. Wyjście ma trzymać ≥ 19,8 V. Potem **zejdź
wolno poniżej 11 V** i zapisz, przy jakim napięciu moduł przestaje
regulować i co robi: czysto się wyłącza albo przechodzi w napięcie
wejściowe — dobrze; drga, piszczy albo cyklicznie restartuje M910q — źle
(wtedy LVD musi odcinać wyżej, §7.3).

Jeżeli którykolwiek pomiar wypadnie poza normę, wymień sztukę. Nie próbuj
tego „docisnąć" w aucie.

### 3.5 Chłodzenie i montaż

Przetwornica przy typowych 30–45 W i sprawności 90 % rozprasza **3–5 W**,
przy pełnych 65 W ok. **7 W**. Zalewany moduł oddaje to ciepło całą obudową:

- przykręć go płasko do blachy (grodź bagażnika obok kosza albo własny
  wspornik), żeby obudowa miała kontakt z metalem,
- **nie** kładź go na koszu z akumulatorami ani na wykładzinie i nie owijaj
  niczym — §4.6: każde +10 °C przy akumulatorach skraca ich życie,
- zostaw ≥ 5 cm wolnego miejsca wokół; wentylator nie jest potrzebny,
- przewody odciąż opaską przy obudowie — wyprowadzenia zalanego modułu są
  na stałe i nie da się ich wymienić.

### 3.5a Ograniczenie poboru M910q — opcjonalne

W poprzednim wydaniu, przy XL6019, ten limit był **obowiązkowy**. Z przetwornicą 200 W nie jest
potrzebny; zostaje jako opcja, jeśli chcesz cichszej pracy, niższej
temperatury w zabudowie albo mniejszego poboru z banku podczas jazdy.
Najprościej przez **RAPL**:

```bash
# sprawdź, gdzie jest pakiet (zwykle intel-rapl:0)
ls /sys/class/powercap/

# odczyt bieżącego limitu (w mikrowatach)
cat /sys/class/powercap/intel-rapl:0/constraint_0_power_limit_uw

# ustaw limit pakietu na 28 W
echo 28000000 | sudo tee /sys/class/powercap/intel-rapl:0/constraint_0_power_limit_uw
```

Utrwalenie przez systemd (tylko jeśli limit naprawdę chcesz mieć):

```ini
# /etc/systemd/system/bcm-power-cap.service
[Unit]
Description=BCM — opcjonalny limit poboru pakietu CPU
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

**28 W pakietu + ~10 W reszty systemu = ~38 W** — tyle, ile M910q bierze
przy Android Auto. Dla dashboardu i AA to bez znaczenia, bo dekodowanie
wideo idzie po VAAPI, a nie po CPU.

---

## 4. Bank akumulatorów CSB HR1221W

### 4.1 Karta katalogowa

| Parametr | Wartość |
|----------|---------|
| Typ | **VRLA AGM** (separator z maty szklanej), seria **HR — High Rate** |
| Napięcie / cele | 12 V / 6 cel |
| Pojemność | **5,1 Ah** przy rozładowaniu 20-godzinnym |
| Moc | 21 W/celę przez 15 min do 1,67 V/celę |
| Zaciski | **F2** — nasuwka faston 6,35 mm (część wersji ma F1 4,75 mm — sprawdź swoje sztuki) |
| Wymiary | 90 × 70 × 101 mm (z zaciskami 101,8 mm) |
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

| Liczba pakietów | Pojemność | Masa pakietów | Maks. prąd ładowania | Uwagi |
|-----------------|-----------|---------------|---------------------|-------|
| 4 | 20,4 Ah | 7,2 kg | 8,4 A | konfiguracja poprzedniego wydania |
| 5 | 25,5 Ah | 9,0 kg | 10,5 A | — |
| 6 | 30,6 Ah | 10,8 kg | 12,6 A | **scenariusz awaryjny** — tyle zostaje po utracie jednego pakietu |
| **7** | **35,7 Ah** | **12,6 kg** | **14,7 A** | **przyjęte** — kosze 4 + 3 (§4.7) |
| 8 | 40,8 Ah | 14,4 kg | 16,8 A | wszystkie posiadane, zero zapasu |

**Bank ma siedem pakietów** w dwóch koszach: **lewy 4 szt., prawy 3 szt.**,
w bagażniku, przy grodzi za tylną kanapą (§4.7). Wobec czwórki to +75 %
pojemności (20,4 → 35,7 Ah) i sufit ładowania podniesiony z 8,4 na 14,7 A.

| Co jest ograniczeniem | Przy 4 pakietach | Przy 7 pakietach |
|-----------------------|------------------|------------------|
| Pojemność banku | wiążąca — 10,2 Ah użytecznych do 50 % DoD | przestała być wąskim gardłem: **17,85 Ah** |
| Prąd ładowania | wiązał **akumulator** (sufit 8,4 A) | wiąże **tor ładowania**: 2 × 5 A z ładowarek, netto do banku ≈ 5 A, czyli 34 % sufitu 14,7 A (§5.3) |
| Masa i mocowanie | 7,2 kg, temat marginalny | **≈ 16,8 kg z koszami** — realne wymaganie konstrukcyjne (§4.7) |

**Zapas.** Z ośmiu posiadanych pakietów siedem idzie do banku, **jeden zostaje
w zapasie**. Trzeba wiedzieć, co to naprawdę znaczy: wobec zasady z §4.3 („nie
dokładaj nowego pakietu do starego banku — wyrównuj cały komplet") jeden
pakiet **nie zastępuje kompletu**. Realny scenariusz awaryjny: przy padniętym
pakiecie **schodzisz na sześć** (30,6 Ah, sufit 12,6 A) i jedziesz dalej —
prąd ładowania netto (≈ 5 A) i tak jest dużo niższy od sufitu. Czasy postoju
dla sześciu pakietów są w §9.2.

**Gabaryty.** Pakiety stoją pionowo, zaciskami do góry, w rzędzie po
szerokości 90 mm: kosz lewy mieści **4 × 90 = 360 × 70 mm**, prawy
**3 × 90 = 270 × 70 mm** (wymiary wnętrza po gumie: 361 × 71 i 271 × 71 mm).
Między koszami zostaje **290–296 mm** wolnego miejsca na otwór do przewozu
nart. Szczegóły w §4.7.

> **Bank w dwóch lokalizacjach to inny obwód niż jedna szyna.** Dwa kosze
> spięte łącznikiem 0,4–0,6 m nie są drabinką z równymi przęsłami; rozkład
> prądów jest policzony osobno w §4.3 dla tego właśnie układu.

### 4.3 Łączenie równoległe na lince — dwa kosze 4 + 3

Nierówne łączenie równoległe to najczęstszy powód, dla którego bank umiera
przedwcześnie: pakiet z najniższą rezystancją toru bierze na siebie większość
prądu i wykańcza się pierwszy. Zasady, niezależnie od tego, czym łączysz:

- **jednakowe pakiety** — ten sam model, ta sama dostawa (zbliżony wiek
  i partia produkcyjna),
- **jednakowe odcinki do pakietów** — ten sam przekrój i ta sama długość
  (±30 mm), nawet jeśli pakiety stoją różnie,
- **odbiór po przekątnej** — „+" z jednego końca banku, „−" z drugiego,
- **bezpiecznik 10 A na „+" każdego pakietu** (**FB1…FB7**) — zwarta cela
  w jednym pakiecie nie zabiera wtedy całego banku,
- **nie dokładaj nowego pakietu do starego banku** — wyrównuj cały komplet.

#### Czy linka zamiast listwy miedzianej dużo zmienia? Nie — pod trzema warunkami

Poprzednie wydanie zalecało płaskowniki miedziane 20 × 3 mm. Linka jest
prostsza do zrobienia i — przy tym banku — **praktycznie nic nie zmienia**,
jeżeli:

1. **przewód zbiorczy jest gruby** — łącznik między koszami i odbiory 6 mm²,
2. **odcinki do pakietów są równe** — każdy pakiet ma swój przewód 2,5 mm²
   tej samej długości do bloku zbiorczego swojego kosza,
3. **odbiór jest po przekątnej** — **„+" z kosza lewego, „−" z kosza prawego**.

Listwa i tak nie przeskoczyłaby przerwy 290–296 mm na narty — łącznik między
koszami jest potrzebny w każdym wariancie.

**Rachunek** (miedź ρ = 0,0172 Ω·mm²/m, R = ρ · L / A):

| Element | Rachunek | Rezystancja |
|---------|----------|-------------|
| Odcinek pakiet → blok, 2,5 mm², 0,25 m na biegun | 0,0172 × 0,25 / 2,5 | 1,72 mΩ na biegun, **3,44 mΩ pętli** |
| Wkładka 10 A + oprawka inline | przyjęcie (repozytorium nie ma pomiaru) | ~7 mΩ |
| Dwie nasuwki faston + dwa oczka | przyjęcie | ~1 mΩ |
| Ogniwo (karta CSB) | — | 23,0 mΩ |
| **`R` jednej gałęzi** | 23 + 3,44 + 7 + 1 | **≈ 34,4 mΩ** |
| Łącznik między koszami, 6 mm², 0,4 / 0,5 / 0,6 m | 0,0172 × L / 6 | 1,15 / **1,43** / 1,72 mΩ (+ ~0,2 mΩ na dwóch oczkach) |

**Jak rozwiązany jest obwód (bloki, odbiór L+ / P−).** Blok zbiorczy to
gwiazda, więc kosz lewy to cztery gałęzie `R` równolegle (`R/4` = 8,61 mΩ),
a kosz prawy trzy (`R/3` = 11,48 mΩ). Łącznik na każdym biegunie ma
`r = 0,0172 × L / 6 + 0,2 mΩ` (dwa oczka). Rezystancję szynek w blokach
pomijamy (krótka mosiężna/miedziana szynka — ułamki mΩ, przyjęcie). Od L+
do P− prowadzą dwie drogi:

- droga A: pakiety kosza lewego, potem łącznik „−": `R/4 + r`,
- droga B: łącznik „+", potem pakiety kosza prawego: `r + R/3`.

Stąd rezystancja banku `R_b = (R/4 + r) ∥ (r + R/3)`, a prąd dzieli się
odwrotnie do rezystancji dróg: `I_A / I_B = (r + R/3) / (R/4 + r)`.
Przykład dla 0,5 m: `r` = 1,43 + 0,2 = 1,63 mΩ, A = 10,24 mΩ,
B = 13,11 mΩ, `R_b` = 10,24 × 13,11 / 23,35 = **5,75 mΩ**. Przy 5 A droga A
niesie 2,81 A (**0,702 A na pakiet**), droga B 2,19 A (**0,731 A na
pakiet**); rozrzut (0,731 − 0,702) / (5/7) = **4,1 %**.

Ten sam rachunek dla innych długości łącznika i, dla porównania, dla innych
układów (obciążenie 5 A):

| Układ | Łącznik 0,4 m | **0,5 m** | 0,6 m | Rezystancja banku na odbiorach (0,4 / 0,5 / 0,6 m) |
|-------|---------------|-----------|-------|-----------------------------------------|
| **Bloki zbiorcze w koszach, odbiór L+ / P−** (przyjęte) | 3,4 % | **4,1 %** | 4,7 % | 5,61 / **5,75** / 5,90 mΩ |
| Linka 6 mm² wzdłuż koszy, odczepy co 90 mm, łącznik między #4 a #5, odbiór „+" przy #1, „−" przy #7 | 9,3 % | 9,9 % | 10,5 % | 6,43 / 6,57 / 6,72 mΩ |
| Oba bieguny z kosza lewego — z bloków (L+ / L−) | 21 % | 24 % | 28 % | ← **zakazane** |
| Oba bieguny z kosza lewego — linka z odczepami, odbiór przy #1 | 44 % | 47 % | 50 % | ← **zakazane** |

Wariant z odczepami nie ma prostego wzoru (drabinka: 90 mm linki 6 mm² =
0,26 mΩ między sąsiednimi pakietami na każdym biegunie) — liczony
rozwiązaniem węzłowym tej samej sieci, z tymi samymi `R` i `r`.

Rozrzut to różnica prądu między najbardziej i najmniej obciążonym pakietem
w odniesieniu do średniej. Przy 5 A pakiety biorą **0,70–0,73 A**, przy
ładowaniu netto 5 A tyle samo, a przy szczycie 10,5 A — ok. 1,5 A. Wszystko
daleko od sufitu 2,1 A na pakiet i od wkładki 10 A.

Skala odniesienia:

- **listwa miedziana 20 × 3 mm** dawała w jednym rzędzie ok. 0,5–1 %;
  różnica 3–4 punktów procentowych przy ~0,7 A na pakiet to setne części
  ampera — dla AGM bez znaczenia,
- **rozrzut produkcyjny ogniw jest większy**: 23 mΩ ± 10 % w jednej dostawie
  daje przy gałęziach 34,4 mΩ ok. **13 %** rozrzutu prądów. Geometria linki
  z blokami jest więc mniejszym problemem niż sama chemia,
- **odbiór obu biegunów z jednego kosza psuje wszystko** (24 % z bloków,
  47 % na lince z odczepami) — to jedyny naprawdę zły układ.

> Wartości 7 mΩ (wkładka z oprawką) i 1 mΩ (przejścia) to **przyjęcia**,
> a nie pomiary. ±20 % na `R` przesuwa rezystancję banku i rozrzut
> proporcjonalnie, ale **nie zmienia żadnej decyzji** z tego rozdziału.

#### Konkret: przewody i złącza

| Odcinek | Przewód | Szczegóły |
|---------|---------|-----------|
| **Łącznik kosz L ↔ kosz P** („+" i „−" osobno) | **6 mm² (10 AWG), czysta miedź OFC — nie CCA**, linka klasy 5/6 (drobnodrutowa), izolacja 105 °C, np. **FLRY-B 6 mm²** albo przewód car-audio OFC 6 mm² | długość 0,4–0,6 m, **obie żyły tej samej długości**; trasa wzdłuż dolnej krawędzi grodzi pod osłoną (bagaż i narty nie mogą po nim jeździć), mocowanie co 15 cm |
| **Odcinek pakiet → blok** (14 szt.) | **FLRY-B 2,5 mm²** (ISO 6722) | **równa długość ±30 mm** (ok. 0,25 m; nadmiar w pętlę, nie przycinać krócej niż najdłuższy); na pakiecie **w pełni izolowana nasuwka żeńska 6,3 × 0,8 mm** na 1,5–2,5 mm², zaciskana zaciskarką zapadkową; na bloku oczko M6 |
| **Bezpiecznik pakietu FB1…FB7** | oprawka inline na 2,5 mm² | **10 A ATO albo mini**, na „+", **5–10 cm od zacisku** pakietu |
| **Odbiór „+" do LVD** | 6 mm² (jak łącznik) | z bloku L+ przez **F7** (§7.4) |
| **Doprowadzenie ładowania** | 4 mm² | do bloku L+ przez **F12** (§5.4) |
| **Masa banku** | 6 mm² | z bloku P− do **jednego** punktu masy (§8.3) |

Pakiety numerujemy od zewnętrznego końca kosza lewego: **#1–#4 w koszu L,
#5–#7 w koszu P** (#7 przy zewnętrznym końcu kosza P).

**Jak łączyć odcinki z linką 6 mm²: izolowany blok zbiorczy z kołkami M6
i oczka zaciskane.** W każdym koszu po jednym bloku na biegun (razem cztery:
L+, L−, P+, P−) — izolowana podstawa z mosiężną lub miedzianą szynką,
**4 kołki M6 i pokrywa**. Do kołków idą oczka M6: z odcinków pakietów
(2,5 mm²), z łącznika i z odbiorów (6 mm²), **najwyżej dwa oczka na kołek**,
grubsze na spód, nakrętka z podkładką sprężystą.

Dlaczego blok z kołkami, a nie „odczepy" na ciągłej lince ani blok
z wkrętami dociskowymi:

- **elektrycznie to gwiazda** — wszystkie pakiety kosza spotykają się
  w jednym punkcie, więc wewnątrz kosza nie ma drabinki i rozrzut spada
  z ok. 10 % do ok. 4 % (tabela wyżej); zostaje tylko asymetria 4 : 3
  przez łącznik,
- **mniej połączeń**: 4 bloki zamiast 14 odczepów i 10 przerwanych odcinków
  linki — każde połączenie to miejsce, które w aucie może się poluzować,
- **oczko pod nakrętką jest odporne na drgania**, a wkręt dociskowy na
  drobnodrutowej lince bez tulejki z czasem luzuje się i grzeje,
- **pokrywa** zamyka gołe kołki — przy prądzie zwarciowym ~2,2 kA
  (§4.4) upuszczony klucz nie może ich dotknąć.

Bloki przykręć na płytce izolacyjnej (tworzywo ≥ 3 mm) **od strony
bagażnika**: do przedniego płaskownika wieńca albo na własnym izolowanym
wsporniku przed koszem — **nie** do dna kosza, nie tak, żeby kołki mogły
dotknąć stali, i **nie do grodzi nad koszem**. Uziemiona belka dociskowa
leży od strony grodzi, 25–29 mm nad zaciskami (§4.7), a odcinki pakietów
mają od niej uciekać w stronę bagażnika; blok na grodzi zmusiłby je, żeby
przeszły nad belką.

```
   KOSZ LEWY (4)                                   KOSZ PRAWY (3)
  [#1][#2][#3][#4]                                 [#5][#6][#7]
   │+  │+  │+  │+    ← FB1…FB4 10 A, 2,5 mm² ±30 mm   │+  │+  │+    ← FB5…FB7
   └───┴─┬─┴───┘                                    └─┬─┴───┘
        [L+]════════ łącznik 6 mm², 0,4–0,6 m ════════[P+]
         ║ ║
         ║ ╚═ F12 ← ładowanie (2 × XY-SK120 → 2 × XH-M603)
         ╚═══ F7 → LVD → szyna odbiorników
   ┌───┬─┴─┬───┐                                    ┌─┴─┬───┐
   │−  │−  │−  │−                                   │−  │−  │−
        [L−]════════ łącznik 6 mm², ta sama długość ══[P−]
                                                      ║
                                    masa banku 6 mm² ═╝ → punkt masy (§8.3)
```

> **Stara wersja z listwami.** Płaskowniki miedziane 15 × 2 / 20 × 3 mm
> z siedmioma odczepami M6 nadal byłyby poprawne (rozrzut ~1 %), ale przy
> dwóch koszach dawałyby dwie krótkie listwy i ten sam łącznik — zysk
> kilku punktów procentowych nie jest wart pracy i wierconej miedzi.

**Zaciski F2 w samochodzie.** Nasuwki 6,35 mm prądowo wystarczają z ogromnym
zapasem (bezpiecznik 10 A jest tu elementem ograniczającym), ale w aucie
problemem są wibracje i bliskość stali:

- nasuwki żeńskie **w pełni izolowane**, zaciskane zaciskarką zapadkową —
  nie kombinerkami, do tego **kapturki** na wszystkie 14 biegunów (poz. 9 BOM
  w PDF koszy),
- **odcinek przed bezpiecznikiem (zacisk „+" → FB) nie jest niczym
  chroniony** — zwarcie go do kosza to prąd zwarciowy całego pakietu. Stąd
  5–10 cm do wkładki i przewody prowadzone **od belki dociskowej w stronę
  bagażnika**, nigdy pod nią ani po ostrej krawędzi wieńca,
- **odciążenie mechaniczne**: wiązkę przypnij opaską, żeby ciężar przewodu
  i oprawki nie wisiał na nasuwce,
- odrobina smaru stykowego przeciw korozji ciernej (fretting).

**Hierarchia ważności**, gdyby trzeba było wybierać, na czym oszczędzić:

1. pakiety z jednej dostawy, wyrównane napięciowo przed łączeniem (§11 Etap 2),
2. odcinki do pakietów o równej długości,
3. odbiór po przekątnej (L+ / P−),
4. bloki zbiorcze zamiast odczepów na ciągłej lince,
5. parzystość liczby pakietów — **bez znaczenia**.

Rysunki: [`../schematics/wiring_power_modules.svg`](../schematics/wiring_power_modules.svg)
(zacisk po zacisku) oraz [`../schematics/power_buffered_m910q.svg`](../schematics/power_buffered_m910q.svg)
(tor główny) — oba pokazują bank na lince z blokami zbiorczymi.

### 4.4 AGM — nastawy ładowania

Ponieważ HR1221W to AGM, obowiązują wartości z karty katalogowej CSB:

| Parametr | Zakres katalogowy | **Przyjęta nastawa** | Dlaczego |
|----------|------------------|---------------------|----------|
| Absorpcja (cykl) | 14,4–15,0 V | **14,40 V** | dolny kraniec — najłagodniejszy dla żywotności (wybór CV w §5.5) |
| Podtrzymanie (float) | 13,5–13,8 V | **13,65 V** | środek zakresu; XY-SK120 nie ma osobnego stopnia float — §5.5 |
| Prąd ładowania | maks. 2,1 A/pakiet (14,7 A na bank) | **2 × 5,0 A z ładowarek**, netto do banku **≈ 5 A** (4–6 A) | 34 % sufitu; ok. 0,7 A na pakiet |

> **Napięcia nie zależą od liczby pakietów.** Łączenie równoległe sumuje
> pojemność i prąd, a napięcie zostawia bez zmian: siedem bloków 12 V
> równolegle to nadal 12 V, a nie 84 V. Ta tabela, cała kompensacja
> temperaturowa z §4.5, progi rozłącznika nadnapięciowego 15,30 / 14,00 V
> (§6.2) i progi LVD 11,00 / 12,60 V (§7.2) obowiązują **dosłownie**, tak samo
> jak przy czterech pakietach. Zmienia się wyłącznie **prąd** i **czas trwania
> faz**.

> **Korekta wcześniejszej wersji tego dokumentu.** Wcześniejsze wydanie
> zakładało akumulatory żelowe i podawało 14,20 V / 13,70 V oraz ostrzeżenie,
> że 14,4 V jest za dużo. **Dla HR1221W jest inaczej: 14,4 V mieści się
> w katalogowym zakresie cyklicznym.** Wartości 15–20 A z oryginalnych
> notatek repo przekraczały sufit czterech pakietów (8,4 A) dwukrotnie; przy
> siedmiu sufit to 14,7 A, a dzisiejsze netto ≈ 5 A jest daleko poniżej.

**Seria HR to akumulator buforowy, nie trakcyjny.** Konstrukcja z cienkimi
płytami jest zoptymalizowana pod krótkie rozładowania dużym prądem (UPS) —
i to akurat **bardzo dobrze pasuje** do roli bufora rozruchowego. Czego HR nie
lubi, to **głębokie cyklowanie** — stąd LVD i dyscyplina DoD z §9.

**Rezystancja banku.** Katalogowe 23 mΩ na pakiet daje po zrównolegleniu
siedmiu sztuk **23 / 7 = 3,29 mΩ na samych ogniwach**. Realnie każda gałąź ma
więcej (rozbicie w §4.3): **`R` ≈ 34,4 mΩ**, czyli same gałęzie dają
34,4 / 7 = **4,92 mΩ**, a z łącznikiem 0,5 m między koszami na zaciskach
odbioru (L+ / P−) — **5,75 mΩ** (rachunek w §4.3).

Skutki praktyczne:

- **spadek napięcia**: przy typowym obciążeniu 5 A bank ugina się
  o 5 × 5,75 mΩ ≈ **29 mV**, przy szczycie 10,5 A (§7.4) o **60 mV**. To
  o rząd wielkości mniej niż histereza LVD (1,6 V) — bez wpływu na próg
  11,00 V i na okno wejściowe przetwornicy,
- **prąd zwarciowy pojedynczej gałęzi**: 12,85 V / 34,4 mΩ = **≈ 374 A**,
  niezależnie od liczby pakietów — dlatego bezpieczniki gałęziowe zostają
  wkładkami ATO / mini (zdolność wyłączania ok. 1 kA, §8.1),
- **prąd zwarciowy prospektywny banku**: na zaciskach odbioru
  12,85 V / 5,75 mΩ ≈ **2,2 kA**; górna granica (zwarcie tuż przy blokach

  kosza, same gałęzie) 12,85 V / 4,92 mΩ ≈ **2,6 kA**. To jedyna liczba
  w tym rozdziale działająca **na niekorzyść** — konsekwencje dla doboru
  wkładek są w §7.4 i §8.1, a dla obsługi rozłącznika masy w §8.4.

> **Skąd 34 mΩ, skoro karta podaje 23 mΩ.** Rezystancje odcinka i przejść
> (nasuwka F2, wkładka, oprawka, oczka) są **przyjęciem** — repozytorium ich
> nie podaje. Rozbicie jest wypisane po to, żeby dało się je przeliczyć po
> pomiarze mostkiem. Poprzednie wydanie miało 37 mΩ, bo liczyło ogonki
> 1,5 mm² × 0,30 m; przy 2,5 mm² × 0,25 m gałąź jest o ok. 3 mΩ sztywniejsza,
> a prąd zwarciowy banku o ok. 8 % wyższy.

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

**XY-SK120 nie ma wejścia czujnika temperatury**, więc kompensacja jest
**ręczna, sezonowa** — nastawy w §5.5. Czujnik NTC 10 kΩ ma sens tylko przy
ładowarce, która go przyjmuje (alternatywa B2B, §5.7); wtedy przyklej go do
boku **środkowego pakietu kosza lewego** (#2 albo #3), nie do skrajnego i nie
na biegunie.

### 4.6 Temperatura, nie cyklowanie, wyznacza żywotność

Karta podaje **3–5 lat pracy buforowej przy 25 °C**. Reguła Arrheniusa dla
akumulatorów ołowiowych: **każde +10 °C mniej więcej połowi ten czas.**

| Miejsce montażu | Szacowana żywotność |
|-----------------|--------------------|
| kabina, pod fotelem / za panelem (wariant poprzedniego wydania) | 2–4 lata |
| **bagażnik (przyjęte)** | **1,5–3 lata** |
| przy tunelu wydechowym | < 1,5 roku |

Dla porównania strona cykliczna: > 260 cykli przy 100 % DoD, czyli grubo ponad
500 cykli przy 50 % DoD. Nawet gdybyś co tydzień schodził do 50 % DoD, to
~50 cykli rocznie — cyklowanie wyczerpie się po dekadzie, a kalendarz i ciepło
znacznie wcześniej.

**Bagażnik to świadomy kompromis.** Kabina byłaby dla akumulatorów
chłodniejsza, ale siedem pakietów w dwóch koszach mieści się tylko
w bagażniku, z wolnym otworem na narty. Żeby nie tracić więcej niż trzeba:

- kosze otwarte od góry — **nie przykrywaj ich szczelną pokrywą** i nie
  zastawiaj bagażem, latem otwórz bagażnik po postoju w słońcu,
- źródła ciepła (przetwornica, dwie XY-SK120 po ~10 W strat, §5.2) **obok
  koszy, nie nad akumulatorami** i nie w kontakcie z nimi,
- latem obniż CV (§5.5) — w gorącym bagażniku 14,40 V to przeładowanie.

### 4.7 Montaż mechaniczny — dwa kosze w bagażniku

Bank stoi w **dwóch stalowych koszach** z projektu
[`mechanika/kosze_HR1221W_4+3.pdf`](mechanika/kosze_HR1221W_4+3.pdf):
przykręconych do **pionowej blachy grodzi za tylną kanapą** i opartych na
**podłodze bagażnika**. Między koszami zostaje 290–296 mm na otwór do
przewozu nart (klapka za podłokietnikiem kanapy). Rysunki 3D na stronach 2
i 4 PDF-u się nie wyrenderowały (są puste) — wymiary niżej pochodzą z tekstu
i tabel PDF-u.

**Konstrukcja (z PDF-u):**

| | Kosz lewy (4 szt.) | Kosz prawy (3 szt.) |
|---|---|---|
| Klatka zewn. (szer. × gł. × wys.) | **373 × 83 × 98 mm** | **283 × 83 × 98 mm** |
| Z wieńcem i nakrętkami | 416 × 89 mm | 326 × 89 mm |
| Wnętrze po gumie 3 mm | 361 × 71 mm (na 360 × 70) | 271 × 71 mm (na 270 × 70) |
| Otwory w grodzi Ø 8,5 mm | 4 (rozstaw 333 mm) | 4 (rozstaw 243 mm) |
| Belka dociskowa 20 × 3 | 416 mm, otwory co 395 mm | 326 mm, otwory co 305 mm |

- dolna rama i 4 słupki narożne z **kątownika 25 × 25 × 3 mm** (S235JR),
  wysokość 98 mm — 4 mm poniżej górnej krawędzi obudowy pakietu,
- górny wieniec z **płaskownika 20 × 3 mm** szerszą krawędzią w pionie
  (78–98 mm), dospawane po zewnątrz nakrętki M8,
- **górna belka dociskowa 20 × 3 mm** leży na obudowach w tylnej części,
  **25–29 mm od zacisków faston**, przykręcona dwiema M8 × 30 (kl. 8.8)
  w dospawane nakrętki; pod nią podwójny pasek EPDM (6 mm),
- **wyklejenie gumą EPDM/SBR 3 mm** dna, narożników i spodu belek,
- mocowanie do grodzi: **M8 × 25 kl. 8.8 z nakrętką samokontrującą DIN 985**,
  po 2 podkładki poszerzane **DIN 9021 (Ø 24 mm)** na śrubę (wg PDF-u; obie
  daj od strony kabiny — ramka niżej); od strony kabiny
  **listwy kontrujące 30 × 4 mm** (KL-9 365 mm, KP-9 275 mm) pod górnymi
  śrubami; dolny rząd otworów 14 mm, górny 88 mm nad podłogą,
- BOM stali na oba kosze: 3 × 1 m kątownika 25 × 25 × 3, 3 × 1 m płaskownika
  20 × 3, 1 × 1 m płaskownika 30 × 4, 4 nakrętki M8 do spawania, 4 kpl. śrub
  belek, 8 kpl. śrub kotwiących, 16 podkładek DIN 9021, arkusz EPDM
  400 × 500 × 3 mm, 14 kapturków na zaciski, podkład i lakier.

> **Do sprawdzenia przed spawaniem / przy przymiarce.** Punkty niżej to
> **wnioski z wymiarów samego PDF-u** (rysunki 3D się nie wyrenderowały), nie
> pomiar — sprawdź je na wyciętych elementach, zanim zespawasz klatkę:
>
> - **Otwory trafiają w słupki.** Otwory Ø 8,5 mm leżą 20 mm od boków klatki
>   (rozstaw 333 / 243 mm), czyli w tylnym ramieniu słupków narożnych KL-4 /
>   KP-4 (25 × 25 × 3, spawanych wewnątrz narożników). Krok 1 PDF-u wierci
>   tylko KL-2 / KL-6 / KL-9 (i KP-), przed spawaniem — śruba przez słupek
>   nie przejdzie. Wierć otwory kotwiące **przez zespawaną ściankę razem ze
>   słupkiem** albo przesuń je poza słupki i poza obrys pakietów.
> - **Z tyłu w środku jest ~1 mm luzu** (71 mm wnętrza na 70 mm pakietu).
>   Łeb M8 albo nakrętka DIN 985 z podkładką DIN 9021 wystaje do kosza o ok.
>   7–10 mm, akurat w narożniku skrajnych pakietów (#1/#4/#5/#7) — pakiet nie
>   wejdzie. Od strony kosza daj **łeb niski / stożkowy** (np. DIN 7991
>   w otworze fazowanym przez kątownik i słupek) albo przesuń otwory poza
>   obrys pakietów; **w środku mała podkładka albo żadna**, nie DIN 9021.
> - **Podkładki Ø 24 i listwy 30 × 4 tylko od strony kabiny.** W dolnym
>   rzędzie (oś 14 mm) podkładka Ø 24 sięga do 2 mm nad podłogą — nie
>   położy się płasko na półce kątownika i jego zaokrągleniu.
> - **Uskok ~3 mm między wieńcem a dolnym kątownikiem.** Klatka ma 83 mm
>   głębokości, z wieńcem 89 mm, a wieniec jest spawany po zewnątrz słupków —
>   tylny płaskownik wieńca (KL-6 / KP-6) wystaje więc ok. 3 mm poza
>   płaszczyznę KL-2 / KP-2. Albo przyspawaj tylny płaskownik wieńca **równo
>   z płaszczyzną KL-2**, albo podłóż pod dolny rząd **listwę dystansową
>   3 mm**. Nie dociągaj ramy do grodzi śrubami — wygniesz ją albo zostanie
>   szczelina.
> - **Długość śrub.** Po dołożeniu słupka, dystansu i listew przelicz
>   pakiet (kątownik / wieniec + słupek + dystans + blacha grodzi +
>   podkładki + listwa + DIN 985): za nakrętką mają zostać min. 2–3 zwoje.
>   Jeśli M8 × 25 nie wystarcza, weź dłuższą tej samej klasy (8.8).

**Zasady, których nie wolno złamać:**

- **nie wierć podłogi bagażnika.** W Alfie 156 zbiornik paliwa jest pod
  siedziskiem kanapy i pod podłogą tuż przed dolną belką grodzi. Kosze stoją
  na podłodze swobodnie (podłoga przenosi ciężar w pionie), a wszystkie
  8 otworów Ø 8,5 mm wiercisz **wyłącznie poziomo przez grodź**, po wyjęciu
  siedziska i oparcia kanapy — i po obejrzeniu, co jest za blachą od strony
  kabiny (przewody, mocowania pasów),
- **belka dociskowa jest blisko zacisków „+"** (25–29 mm) i jest uziemiona
  przez śruby. Kapturki na wszystkie bieguny, nasuwki w pełni izolowane,
  przewody prowadzone od belki w stronę bagażnika (§4.3),
- pakiety **stojąco, zaciskami do góry** — AGM toleruje dowolną orientację
  poza do góry nogami, ale kosz jest zaprojektowany na pion,
- dostęp do zacisków bez demontażu kanapy — przy siedmiu pakietach to
  **14 nasuwek** i 4 bloki do okresowej kontroli (§12).

#### Liczby do mocowania (≈ 16,8 kg)

Masa z PDF-u: **≈ 16,8 kg** razem (7 pakietów ~12,6 kg + stal i guma).
Podział na kosze przyjmujemy proporcjonalnie do liczby pakietów:
**L ≈ 9,6 kg, P ≈ 7,2 kg**.

| Wielkość | Razem | Kosz L | Kosz P |
|----------|-------|--------|--------|
| Siła przy 10 g (kryterium robocze) | **1,65 kN** | 0,94 kN | 0,71 kN |
| Siła przy 20 g (jak dla mocowania ładunku) | **3,30 kN** | 1,88 kN | 1,41 kN |
| Na jedną z 4 śrub kosza przy 20 g | — | **≈ 470 N** | ≈ 355 N |

Jak te siły działają na grodź:

- **hamowanie i zderzenie czołowe** pchają kosze **na grodź** — blacha pracuje
  na docisk przez całą tylną ściankę kosza, śruby są prawie nieobciążone,
- **uderzenie w tył** ciągnie kosze **od grodzi** — wtedy śruby pracują na
  rozciąganie, a ryzykiem jest **przeciągnięcie łba przez blachę**; od tego
  są listwy 30 × 4 i podkładki Ø 24 mm,
- **siły boczne** (zakręt, uderzenie z boku) — ścinanie śrub i tarcie
  docisku; M8 kl. 8.8 przenosi rzędu kilkunastu kN, więc ~0,5 kN na śrubę
  nie jest dla niej problemem,
- **w pionie** ciężar bierze podłoga, a przy podbiciu na nierówności pakiety
  trzyma belka dociskowa.

> **Czego ten rachunek nie rozstrzyga.** **Grubość i nośność grodzi w Alfie
> 156 są nieznane** — repozytorium ich nie zawiera. Dolne śruby (14 mm nad
> podłogą) siedzą w narożniku grodź–podłoga, który zwykle jest sztywny, ale
> według PDF-u mają tylko podkładki DIN 9021. Jeżeli blacha ugina się przy
> dokręcaniu, dołóż drugą parę listew 30 × 4 pod dolny rząd (kolejne
> 0,64 m płaskownika). Kryteria 10 g / 20 g są przyjęte z praktyki
> motoryzacyjnej, nie z normy, a 16,8 kg w bagażniku tuż za oparciem
> kanapy to masa istotna dla bezpieczeństwa pasażerów — sposób mocowania
> jest decyzją człowieka, nie wynikiem tego rachunku.

**Wentylacja i ciepło.** AGM jest szczelny (VRLA, rekombinacja gazów),
ale przy awarii ładowania zawór bezpieczeństwa wypuszcza wodór. Kosze są
otwarte od góry i tak ma zostać: **żadnej szczelnej pokrywy nad pakietami**,
a elementy, które iskrzą (przekaźnik K1, przekaźniki XH-M603 i XH-M609,
bezpieczniki), montuj **obok koszy, nie bezpośrednio nad nimi** — wodór
idzie do góry. Bagażnik sedana nie jest hermetyczny, a XH-M603 (§6) odcina
ładowanie, zanim AGM zacznie intensywnie gazować.

**Trasa do przodu.** Z bagażnika do M910q przy nogach pasażera jest
**ok. 4 m**: przez grodź istniejącą przelotką (albo nową, zawsze z gumową
przelotką), wzdłuż progu pod listwami, w peszlu, z dala od mechanizmów
foteli i pasów. Przewody i przekroje tej trasy — §8a.2.

---

## 5. Ładowanie — 2 × XY-SK120

Rysunek: [`../schematics/charging_lvd.svg`](../schematics/charging_lvd.svg)
(przy rozbieżności obowiązuje tekst §5)

### 5.1 Dlaczego zwykły buck DC-DC tu nie zadziała

Wcześniejsze wydania dokumentacji proponowały moduł **buck** (XL4016) między
diodą a bankiem. To nie może działać poprawnie, i warto wiedzieć dlaczego:

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

Potrzebna jest topologia, która **potrafi i podnieść, i obniżyć napięcie**:
buck-boost. Taka jest XY-SK120 — z 12,5–14,7 V z instalacji robi stabilne
14,40 V w obie strony, więc problem „CV musi być wyższe od wejścia" znany ze
zwykłego boostu tu nie istnieje, a dioda MBR2545CT nie jest potrzebna.

### 5.2 Przyjęte: dwie XY-SK120 równolegle

**XY-SK120** (Sinilink; spotykana też jako nowsza **XY-SK120X**) to
cyfrowy moduł zasilacza **buck-boost CC-CV** z wyświetlaczem i przyciskami.
Fakty z opisu i instrukcji (dostępne fragmenty dotyczą głównie wersji
SK120X — plain SK120 może się różnić domyślnymi wartościami i menu):

| Cecha | Wartość |
|-------|---------|
| Topologia | buck-boost, CC-CV (SK120X dodatkowo tryb stałej mocy) |
| Wejście | **6–36 V** |
| Wyjście | do **6 A / 120 W** |
| Obsługa | wyświetlacz, nastawa cyfrowa napięcia i prądu z odczytem |
| Zabezpieczenia w menu | **OVP** (przepięcie wyjścia), **LVP/UVP** (podnapięcie wejścia), OCP, OPP, OTP |
| Orientacyjna cena | ok. 60–90 PLN sztuka (ogłoszenia — zmienne) |

> **Skąd te liczby.** Pełnej instrukcji XY-SK120 nie udało się przy pisaniu
> otworzyć — widzieliśmy tylko fragmenty instrukcji SK120X (LVP 5,5–36 V,
> OVP 0–38 V, OCP domyślnie 6,2 A, OPP, OTP). **Wejście 6–36 V i wyjście
> 6 A / 120 W pochodzą z opisów sprzedażowych**, nie z instrukcji. Sprawdź je
> w instrukcji i na obudowie kupionej sztuki, zanim ustawisz CC 5,0 A
> i podasz na wejście więcej niż ~15 V.

**Nastawy każdego modułu:** **CV 14,40 V, CC 5,0 A** (≈ 72 W — 60 % ze
120 W, zapas cieplny). Dwa moduły równolegle dają razem **≈ 10 A**.

Czego nie wiemy i trzeba sprawdzić po zakupie:

- **sprawność** — producent jej nie podaje w dostępnych materiałach; do
  rachunku przyjmujemy **88 %** (przyjęcie, nie dana), czyli ok. **10 W strat
  na moduł** przy 72 W. Zmierz temperaturę radiatora po 30 min przy 5 A;
  modułu nie zamykaj w szczelnej obudowie,
- **prąd CC** — ustaw 5,0 A i sprawdź amperomierzem na wyjściu przy
  rozładowanym banku (odczyt na ekranie modułu bywa przesunięty),
- **„wyjście po włączeniu zasilania"** — moduły tej rodziny mają ustawienie,
  czy wyjście startuje samo po podaniu zasilania. Jeżeli jest wyłączone, po
  każdym uruchomieniu silnika moduł stoi z wyjściem OFF i **bank się nie
  ładuje, bez żadnego objawu**. Ustaw „ON" i sprawdź, odcinając i podając
  zasilanie,
- **wersja i menu** — czy Twoja sztuka ma LVP z regulacją (instrukcja SK120X
  podaje LVP 5,5–36 V, domyślnie 5,5 V) i czy ma którąś z funkcji końca
  ładowania (§5.5).

### 5.3 Dlaczego dwie, a nie jedna

Z nową przetwornicą komputer nie jest już przycięty do ~38 W, a w budżecie
jest telefon — podczas jazdy szyna bierze **≈ 4–6 A** (§2.1). Ładowarka
zasila **najpierw odbiorniki**, a do banku idzie dopiero reszta:

| Ładowanie | Wyjście razem | Obciążenie | **Netto do banku** | Faza CC z progu LVD (26,78 Ah) |
|-----------|---------------|------------|--------------------|--------------------------------|
| jedna XY-SK120, CC 5 A | 5 A | 4–6 A | **≈ −1…+1 A** — bank się w trasie **nie ładuje** | — |
| jedna XY-SK120, CC 6 A (maks.) | 6 A | 4–6 A | ≈ 0–2 A | 13 h i więcej |
| **dwie XY-SK120, CC 2 × 5 A** | **10 A** | 4–6 A | **≈ 4–6 A** (≈ 5 A) | **≈ 5,4 h** (4,5–6,7 h) |
| dwie XY-SK120, CC 2 × 6 A | 12 A | 4–6 A | ≈ 6–8 A | ≈ 3,8 h — bez zapasu cieplnego, nie zalecane |

Jedna sztuka ledwo pokryłaby obciążenie, więc bank po postoju **nie
odzyskiwałby ładunku w czasie jazdy**. Dwie dają netto ≈ 5 A, czyli ok.
0,7 A na pakiet — 34 % katalogowego sufitu 14,7 A, bez ryzyka dla AGM.

**Jak dwa CC-CV dzielą prąd.** Dopóki bank jest poniżej 14,40 V, oba moduły
siedzą w CC i każdy daje swoje 5 A — podział jest wymuszony nastawą, a nie
rezystancją przewodów. Gdy bank dochodzi do CV, moduł z odrobinę wyższą
nastawą przejmuje podtrzymanie, a drugi schodzi z prądu; to nieszkodliwe,
bo prąd w fazie absorpcji i tak maleje poniżej 5 A. **To przyjęcie, nie
sprawdzony fakt:** schematu XY-SK120 nie znamy, a synchroniczny buck-boost
pracujący w wymuszonym CCM może przy wyjściu podniesionym ponad swoją
nastawę **oddawać prąd wstecz** (wyjście → wejście) — moduły krążyłyby
wtedy prąd między sobą, grzejąc oba i obciążając FC1/FC2. Sprawdź to
pomiarem z §11 Etap 5 (prąd każdej gałęzi pod koniec absorpcji). Nastaw oba CV w granicach
±0,02 V i daj obu przewody wyjściowe tej samej długości. Mierz multimetrem,
nie odczytem modułu — i **nie w fazie CC przy 10 A**: wtedy w pętli
4 mm² + F12 spada ok. 0,09 V, a gdybyś „dociągnął" CV tak, żeby bank
pokazał 14,40 V, to pod koniec absorpcji, gdy prąd zanika, bank stanąłby
o te 0,05–0,09 V wyżej. Nastawiaj CV na wyjściu modułu **bez banku**
(wyjście rozpięte albo za otwartym XH-M603), a na zaciskach banku tylko
sprawdzaj — **pod koniec absorpcji, przy prądzie < 1 A**.

### 5.4 Tor ładowania

```
akumulator rozruchowy ─ F1 20 A (≤ 30 cm od klemy) ─ 6 mm², ~5 m do bagażnika
  ─ TVS SMCJ20CA + 470 µF / 35 V ─ K1 30 A (cewka: zapłon albo D+, przez FK 1 A)
       ├─ XY-SK120 #1 (CV 14,40 V / CC 5,0 A) ─ XH-M603 #1 ─ FC1 7,5 A ─┐
       └─ XY-SK120 #2 (CV 14,40 V / CC 5,0 A) ─ XH-M603 #2 ─ FC2 7,5 A ─┴─ 4 mm² ─ F12 15 A ─ blok L+ banku
  masa obu modułów (wejście = wyjście) ─ punkt masy przy banku (§8.3)
```

| Element | Rola | Nastawa / uwaga |
|---------|------|-----------------|
| **F1 20 A** przy klemie, **MIDI/AMI lub ANL** | chroni ~5 m przewodu 6 mm² przez całe auto | §8.1 — dlaczego 20 A, a nie 15 A, i dlaczego klasa jak F7 |
| **TVS + 470 µF** | krótkie szpilki i tętnienia; nietłumionego load dumpu nie przeżyje (§5.8) | — |
| **K1** 30 A SPDT + podstawka | rozłącza tor, gdy silnik nie pracuje | dioda 1N4007 równolegle do cewki |
| **2 × XY-SK120** | CC-CV 14,40 V / 5,0 A każda | §5.2, §5.5 |
| **2 × XH-M603** — po jednym na moduł | odcięcie przy przepięciu na banku | 15,30 / 14,00 V; dlaczego dwa — §6.3 |
| **FC1, FC2 7,5 A ATO** — po jednej na gałąź, tuż przy OUT+ swojego XH-M603, przed złączeniem | chronią płytkę XH-M603 (≤ 8 A, §6.3) od strony banku i przed nadprądem z uszkodzonej XY-SK120 | 5 A to 67 % wkładki; 10 A byłoby powyżej granicy płytki — niedopuszczalne |
| **F12 15 A** przy bloku L+ | zwarcie przewodu ładowania zasilane od strony banku | klasa jak F7 (≥ 2,5 kA, §8.1); 10 A to 67 % wkładki |
| **FK 1 A** w miejscu wpięcia w zapłon / D+ | chroni ~4–5 m przewodu 0,75 mm² do cewki K1 | cewka ~0,15 A; bezpiecznik obwodu auta (15–20 A) tego przewodu nie chroni |

**Po co FC1/FC2, skoro jest F12.** F12 15 A siedzi za złączeniem i chroni
przewód 4 mm², a nie pojedynczą gałąź. Gdy przekaźnik XH-M603 jest zwarty,
jego płytka jest wpięta wprost w bank; częściowe uszkodzenie XY-SK120
(przebity tranzystor wyjściowy, kondensator, nadpalony zacisk) może wtedy
pchać przez jedną płytkę 8–15 A — do tego może dołożyć prąd druga ładowarka
przez złączenie — a F12 tego nie przerwie. Rozłącznik też nie, bo reaguje
tylko na **wzrost** napięcia banku. Stąd wkładka w każdej gałęzi.

**Czy ATO wyłączy prąd zwarcia w tym miejscu** (oszacowanie, jak przyjęcia
w §4.3): źródło to bank ~5,75 mΩ, do tego ~1 m 4 mm² na „+" (4,3 mΩ),
powrót przez masę 6 mm² (~1,4 mΩ) i wkładki F12 + FC z oprawkami
(~10–15 mΩ, przyjęcie, nie pomiar) — razem ~22–27 mΩ, czyli
12,85 V / 22–27 mΩ ≈ **480–590 A**, poniżej ~1 kA zdolności wyłączania
ATO. **Selektywność nie jest gwarantowana**: przy twardym zwarciu F12 może
zadziałać pierwszy albo razem z FC — to dopuszczalne, bo każda z nich
przerywa obwód.

**Prąd z akumulatora rozruchowego.** Na wyjściu 2 × 72 W = 144 W; przy
przyjętej sprawności 88 % to 164 W z instalacji: **11,9 A przy 13,8 V**
(silnik pracuje) i **13,0 A przy 12,6 V** (kluczyk na ON, silnik stoi —
tylko gdy K1 idzie z zapłonu).

**Czym sterować cewkę K1.** Najprościej **zapłonem**. Koszt: przy kluczyku
w pozycji ON bez pracującego silnika moduły ładują bank **z akumulatora
rozruchowego prądem ~13 A**. Przy normalnym uruchamianiu to kilka sekund;
przy dłuższym staniu z kluczykiem (radio na postoju, diagnostyka) — wyraźnie
rozładowuje rozruchowy. Dwie poprawki, najlepiej obie:

- cewka z **D+/L alternatora** zamiast z zapłonu — sygnał znaczy wtedy
  „alternator ładuje". Sprawdź potem, czy lampka kontrolna ładowania dalej
  działa poprawnie — cewka pobiera ~150 mA z jej obwodu,
- **LVP modułów na 12,8 V** (jeśli Twoja wersja ma regulowane LVP): przy
  stojącym silniku rozruchowy ma 12,4–12,7 V i moduły stoją, przy pracującym
  na wejściu jest 13,4–14,2 V. To także druga bariera, gdyby styki K1 się
  zespawały. Sprawdź na wolnych obrotach z włączonymi światłami, czy moduły
  nie klapkują na progu; jeżeli tak — obniż LVP do 12,7 V.
  **Uwaga:** tuż po jeździe rozruchowy trzyma przez godzinę i dłużej
  12,9–13,1 V ładunku powierzchniowego — wtedy sam LVP **nie blokuje**
  ładowania przy kluczyku na ON: moduły ruszą, pobiorą ~13 A, wejście siądzie
  poniżej 12,8 V, staną, napięcie wróci i tak w kółko. Pewniejsza jest cewka
  K1 z D+; przy samym LVP sprawdź kluczyk na ON ok. 10 min po jeździe.

**Przepływ wsteczny (bank → instalacja auta).** Dioda MBR2545CT z dawnego
wariantu B nie jest potrzebna, ale warto wiedzieć, co ją zastępuje:

1. **K1 rozwarty** przy zgaszonym silniku — wejścia modułów wiszą w powietrzu.
   To wystarcza, żeby **akumulator rozruchowy** był odcięty od banku,
   niezależnie od tego, co robi XH-M603,
2. **zakładamy**, że XH-M603 jest zasilany z DC-IN, czyli z wyjścia swojego
   modułu, a jego przekaźnik jest w spoczynku rozwarty: gdy moduł gaśnie,
   gaśnie XH-M603 i **odcina wyjście modułu od banku**. To **przyjęcie, nie
   fakt** — płytka mierzy po stronie OUT (bank), więc mogłaby też brać
   zasilanie od banku albo przez swój dzielnik pomiarowy. Wtedy na postoju
   trzymałaby przekaźnik zwarty (bank < 15,3 V), podpinała bank pod martwe
   wyjście XY-SK120 i dokładała własny pobór do budżetu postoju. Przyjęcie
   potwierdza albo obala **test z §6.4 pkt 6** — do tego czasu ten punkt
   traktuj jako niezweryfikowany,
3. z samą XY-SK120 nie liczymy na nic: czy jej stopień wyjściowy przewodzi
   wstecz albo pobiera prąd z wyjścia przy braku wejścia — **nie wiadomo**
   (schematu brak). Dlatego punkt 2.

Kontrola w §11 Etap 5: przy zgaszonym silniku prąd z banku w stronę ładowarek
ma być zerowy (< 1 mA na amperomierzu w przewodzie przy F12) — to ostatnia
siatka bezpieczeństwa, już w aucie.

### 5.5 Nastawa CV i brak prądu końca ładowania

W dostępnych materiałach XY-SK120 / SK120X **nie znaleźliśmy funkcji
kończenia ładowania prądem** (ustawienia typu „stop przy spadku prądu do
X A" ani przejścia na float). Niektóre moduły tej rodziny mają limity typu
OAH (amperogodziny) albo OHP (czas) — **dla SK120 tego nie potwierdziliśmy**;
jeżeli Twoja sztuka je ma, nie zastępują one prawdziwego przejścia na float.
Zakładamy więc najgorszy przypadek: **moduł trzyma CV przez cały czas pracy
silnika**.

Ponieważ XY-SK120 to buck-boost, **CV może być dowolne** — także poniżej
napięcia wejściowego — a CC działa zawsze. To zmienia rachunek wobec dawnego
boostu, któremu nastawa 13,8 V wyłączała ograniczenie prądu:

Liczby w tabeli wynikają wprost z §4.5 (absorpcja −30 mV/°C, float
−18 mV/°C od 25 °C). Temperatura to temperatura **pakietów w bagażniku
podczas jazdy**, nie powietrza na zewnątrz:

| Nastawa CV | Kiedy | Plus | Minus |
|-----------|-------|------|-------|
| **14,40 V** (domyślnie) | pakiety ok. **25 °C** (i chłodniej — zima); typowa jazda do ~2 h dziennie, bank często po postoju | pełne naładowanie, najkrótsza absorpcja; = absorpcja §4.5 dla 25 °C | przy długiej trasie AGM stoi godzinami na napięciu absorpcji — utrata wody, szybsze starzenie |
| **13,80 V** | ok. **25 °C** i częste trasy po kilka godzin | górna granica katalogowego float **przy 25 °C** — stać na tym bez końca można tylko przy ok. 25 °C lub chłodniej; powyżej obniżaj o ~18 mV/°C | ładowanie do pełna wyraźnie dłuższe (absorpcja na niższym napięciu) |
| **13,95 V** | **lato, gorący bagażnik (~40 °C)**, typowe jazdy | = absorpcja §4.5 dla 40 °C | jak 14,40 V przy 25 °C: na wielogodzinnej trasie to nadal napięcie absorpcji, nie float |
| **13,40 V** | **lato (~40 °C) i częste trasy po kilka godzin** | ≈ float §4.5 dla 40 °C (13,38 V) — tu można stać godzinami | bank po postoju doładowuje się bardzo powoli; przy krótkich jazdach za mało |

14,10 V (dawna „letnia" nastawa) odpowiada absorpcji przy ok. **35 °C**, nie
40 °C, i jest o ok. 0,7 V powyżej float dla 40 °C — na długiej letniej trasie
to stałe przeładowanie. Nie używaj jej jako nastawy „na całe lato".

Co trzyma 14,40 V w ryzach, gdy zostaje:

- napięcie jest podawane **tylko podczas jazdy** (K1, LVP) — na postoju bank
  stoi na własnym napięciu spoczynkowym,
- rozłączniki nadnapięciowe 15,30 V łapią awarię modułu (§6),
- **OVP modułów ustaw na 15,0 V** — pierwsza, wewnętrzna warstwa (nie chroni
  przed przebiciem tego samego modułu, od tego jest XH-M603).

Kompensacji temperaturowej nie ma (§4.5) — przestawiasz CV sezonowo: zima
14,40 V, lato w gorącym bagażniku **13,95 V** (przy częstych wielogodzinnych
trasach **13,40 V**).

### 5.6 Brak izolacji galwanicznej — zasady masy

XY-SK120 **nie jest izolowana**: masa wejścia i masa wyjścia to ten sam
zacisk. Prąd ładowania i tętnienia alternatora wracają przez wspólny punkt
masy, a nie przez transformator. Bank bocznikuje część zakłóceń swoją niską
impedancją, ale nie wszystkie. Zasady są te same co w dawnym nieizolowanym
wariancie B:

1. **Masa banku i masa pojazdu spotykają się w JEDNYM punkcie** — przy
   banku, krótkim przewodem 6 mm² do oczyszczonej blachy nadwozia w bagażniku
   (§8.3). Wejściowa masa modułów **nie dostaje osobnego przewodu do klemy
   „−" rozruchowego** — prąd wejściowy wraca przez ten jeden punkt i nadwozie.
   Drugi przewód masowy to pętla.
2. **Wszystkie masy head unitu schodzą się w tym punkcie**: bank, moduły,
   LVD, dystrybucja, powrót 20 V z M910q i powrót 12 V z przodu (§8a.2).
3. **Wzmacniacz nadal wisi na akumulatorze rozruchowym** z własną masą
   (§2). Ekran RCA łączy więc dwie różne masy i to jest główna droga
   sprzężenia. Jeżeli pojawi się przydźwięk, rozstrzyga się to izolatorem
   pętli masy na RCA albo przeniesieniem punktu masy — nie kolejnym przewodem
   masowym.

### 5.7 Alternatywa: izolowana ładowarka B2B (droższa)

Samochodowa ładowarka DC-DC („B2B") z **izolacją galwaniczną** rozwiązuje
w jednym pudełku topologię, profil wielostopniowy z presetem AGM i float,
a transformator przerywa pętlę masy między instalacją auta a zestawem.

| Model | Prąd | Izolacja | Orientacyjna cena | Uwagi |
|-------|------|----------|------------------|-------|
| **VEVOR 12/12-20** (i klony pod innymi markami) | 20 A / 250 W | deklarowana | ~400–550 PLN | trójstopniowy profil, tryb AGM, wyzwalanie zapłonem |
| Renogy REGO 12/12-20 | 20 A | tak | ~700–900 PLN | preset AGM |
| Victron Orion-Tr Smart 12/12-18 | 18 A | **wersja izolowana to osobny wariant** — sprawdź symbol | ~800–1000 PLN | konfiguracja przez Bluetooth, preset AGM |

> **Czego nie dało się zweryfikować.** Specyfikacje i ceny pochodzą z opisów
> sklepowych, nie z kart katalogowych. Przed zakupem potwierdź: **czy wyjście
> jest naprawdę odizolowane** (omomierz między masą wejścia i wyjścia —
> rozwarcie), **czy jest float**, **czy ładowanie startuje z zapłonu / D+**
> i **czy da się ustawić prąd**.

Dwa haczyki, przez które to nie jest zamiana „wkręć i jedź":

- **20 A bez regulacji to za dużo**: przy obciążeniu 5 A do banku poszłoby
  ~15 A — tyle, co sufit 14,7 A. Potrzebna jest nastawa prądu ≤ ~12 A albo
  model 10–15 A,
- **warstwa nadnapięciowa z §6 dalej obowiązuje**, a jeden XH-M603 nie
  przeniesie 10–20 A z jednego wyjścia (§6.3). To osobny projekt (rozłącznik
  z wolnym stykiem i przekaźnik mocy) i decyzja człowieka.

Przy B2B izolowanym masa wyjścia jest tylko masą banku: punkt masy z §5.6
zostaje, ale wejście ładowarki dostaje własny powrót do „−" rozruchowego.

### 5.8 Ochrona wejścia

Instalacja 12 V auta bywa brudna elektrycznie. Na **wejściu toru ładowania**
(przed K1):

- **dioda TVS SMCJ20CA** równolegle do wejścia — obcina **krótkie szpilki**
  (mikrosekundy–pojedyncze milisekundy). Napięcie ograniczania serii SMCJ20
  przy pełnym prądzie impulsu to wg typowych kart ok. **32 V**, czyli poniżej
  maksymalnych **36 V** wejścia XY-SK120. Dawniej zalecane **1.5KE33CA
  ogranicza dopiero przy ok. 45 V** — dla tego modułu za wysoko. Potwierdź Vc
  w karcie kupionej diody. **Prawdziwego, nietłumionego load dumpu ta dioda
  nie przeżyje**: trwa on setki milisekund i niesie dziesiątki dżuli, a dioda
  1500 W klasy SMC jest na to za mała — zewrze się i F1 się przepali, tak jak
  przy rozruchu „z 24 V" niżej. Pełna ochrona przed load dumpem zależy od
  tłumienia w samym alternatorze, a tego dla tego auta nie sprawdziliśmy,

- **kondensator elektrolityczny** 470 µF / 35 V low-ESR, 105 °C, równolegle —
  wygładza tętnienia i pomaga przy zapadach,
- TVS 20 V zaczyna przewodzić od ok. 22 V: przy rozruchu „z 24 V" albo
  długim przepięciu przegrzeje się i zewrze — **F1 wtedy przepala się
  zamiast modułów**. To zamierzone.

> **Sufiks „CA" znaczy dwukierunkowa — i to nie jest szczegół.** SMCJ20**CA**
> nie ma anody ani katody; wlutuj ją w dowolną stronę. Pasek na obudowie,
> jeśli w ogóle jest nadrukowany, nic nie znaczy. Ale **SMCJ20A** (bez „C")
> to inna dioda — **jednokierunkowa**, i tam pasek (katoda) musi iść na
> **plus**. Odwrotnie wlutowana jest spolaryzowana w kierunku przewodzenia,
> czyli jest zwarciem ~1 V na zasilaniu, i bezpiecznik idzie natychmiast po
> podaniu napięcia.
>
> **Sprawdzenie miernikiem** (tryb testu diody): dwukierunkowa daje **OL
> w obie strony**, jednokierunkowa ~0,7 V w jedną i OL w drugą. Próg 22 V
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
| Prąd przez styki **jednego** modułu | **≤ 8 A** (u nas 5 A) | granica płytki, nie przekaźnika — §6.3 |

### 6.3 Realizacja: XH-M603, po jednym na ładowarkę

#### Ile prądu tam płynie i dlaczego dwa moduły

Rozłącznik siedzi **między wyjściem ładowarki a bankiem** — płynie przez niego
wyłącznie prąd ładowania, ograniczony nastawą CC. Przy dwóch XY-SK120 to
razem **10 A**.

Na płytkach XH-M603 siedzi zwykle przekaźnik z nadrukiem 30 A, ale
**ograniczeniem jest płytka, nie przekaźnik**: ścieżki i zaciski śrubowe
wytrzymują realnie ok. **8–10 A** (oszacowanie z oględzin, nie z karty),
a przyjęta granica to **≤ 8 A**. **Jeden XH-M603 na 10 A nie wystarcza.**

Rozwiązanie: **jeden XH-M603 na każdą XY-SK120.** Każdy przenosi 5 A —
62 % granicy 8 A — i każdy jest zasilany z wyjścia swojego modułu.
Dlaczego nie „jeden moduł jako pilot + mocniejszy przekaźnik": XH-M603 nie
ma wolnego styku — przekaźnik siedzi wewnętrznie w torze DC-IN+ → OUT+,
a pomiar jest po stronie OUT. Gdy OUT steruje cewką przekaźnika mocy, po
zadziałaniu napięcie na OUT spada do zera przez cewkę → moduł widzi „pusty
akumulator" → zwiera z powrotem → oscylacja niszczy styki. Układ „pilot"
działa tylko z modułem, który ma wolny styk COM/NO — tego nie potwierdziliśmy
dla żadnego modelu z rodziny (§13.7).

Oba XH-M603 widzą to samo napięcie banku. Jeżeli jedna XY-SK120 się przebije
i zacznie pchać bank w górę, przy 15,30 V **rozwierają oba** — awaria
jednego modułu odcina całe ładowanie, a to jest właściwy kierunek.

#### Gdzie kończy się tor ładowania

| Element toru | Jego limit | Wobec nastaw (2 × 5 A) |
|--------------|-----------|------------------------|
| **XY-SK120** | 6 A / 120 W każda | 5 A × 14,4 V = 72 W — 83 % prądu, 60 % mocy; **nastawa wybrana z zapasem cieplnym** |
| **XH-M603** — płytka i zaciski | ≤ 8 A (spec przyjęta), ~10 A realnie | 5 A — 62 % |
| **FC1, FC2 7,5 A** — wkładka w gałęzi, przy OUT+ XH-M603 | 6 A ciągle (80 %) | 5 A — 67 %; chroni płytkę ≤ 8 A z obu stron (§5.4) |
| Przewód AKU → bagażnik 6 mm², ~5 m | spadek 3 % (0,41 V) | 11,9 A wejścia → 0,17 V na „+" (1,2 %) |
| **F1 20 A** przy 80 % obciążalności ciągłej | 16 A wejścia | 11,9–13,0 A — 60–65 % wkładki |
| Przekaźnik K1 30 A | 30 A | 13 A |
| **F12 15 A** przy banku | 12 A ciągle | 10 A |
| Cewka K1 przez **FK 1 A** | 0,8 A ciągle | ~0,15 A |
| **Sufit katalogowy CSB: 7 × 2,1 A** — dotyczy prądu **netto** do banku | 14,7 A | ≈ 5 A (maks. ~10 A, gdy odbiorniki prawie nic nie biorą) |

Przy 2 × 5 A żaden element nie pracuje na granicy. Podnoszenie CC do 6 A na
moduł jest możliwe elektrycznie (XH-M603 nadal ≤ 8 A), ale moduły pracowałyby
na 100 % prądu i ~86 W — w bagażniku latem to zły pomysł.

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

Połączenie każdego: **DC-IN** z wyjścia swojej XY-SK120, **OUT** przez
swoją wkładkę FC1 / FC2 na wspólny przewód 4 mm² do F12 i bloku L+ banku.
**Zakładamy**, że moduł zasilany z wyjścia ładowarki nie bierze nic z banku
na postoju — przy zgaszonym silniku cały węzeł jest martwy, a przekaźnik
rozwarty (§5.4). Bez schematu płytki to przyjęcie; potwierdza je dopiero
test z §6.4 pkt 6.

> **Tę liczbę trzeba potwierdzić pomiarem.** Obciążalność ~8–10 A jest
> **oszacowaniem** z oględzin płytki. Zmierz temperaturę zacisków przy 5 A
> przez 30 min (§11 Etap 1), zanim zamkniesz instalację.

#### Czego ten rozłącznik NIE robi

**Nie chroni przed przepięciami na wejściu.** Moduł reaguje w dziesiątkach
do setek milisekund, a szpilka z instalacji trwa mikrosekundy — od tego jest
dioda TVS na wejściu (§5.8), a przed pełnym load dumpem chroni dopiero
tłumienie w alternatorze. To różne warstwy, jedna nie zastępuje drugiej.

**Nie musi chronić odbiorników.** Bank trzyma napięcie szyny, a przetwornica
step-up (wejście do 18 V wg opisu) i bucki LM2596 / MP1584 przyjmują 15–16 V.
Odcięcie samego ładowania w zupełności wystarcza.

**Alternatywa izolowana (§5.7) też potrzebuje tej warstwy.** Gotowa ładowarka
B2B jest zwykle niezawodna, ale nie jest niezniszczalna — a komplet
**siedmiu** HR1221W jest wielokrotnie droższy niż moduł za 60 PLN.

### 6.4 Kontrola „na sucho"

Każdy z dwóch XH-M603 osobno, po zamontowaniu, przed podłączeniem banku:

1. Zasilacz laboratoryjny (ograniczenie prądu ~0,5 A) podłącz **naraz na
   DC-IN i OUT** — mostkiem, oba „+" razem i oba „−" razem; OUT udaje bank.
   Stan przekaźnika odczytuj z jego diody / kliknięcia i ze wskazania płytki
   (omomierz DC-IN+ ↔ OUT+ nic tu nie pokaże — mostek zwiera styk). Dlaczego
   tak: moduł mierzy stronę OUT (§6.3). Gdy zasilasz samo DC-IN, rozwarcie
   przekaźnika zeruje napięcie na OUT, płytka widzi < 14,00 V, zwiera
   ponownie i zamiast progu dostajesz klapanie. Wolno podnoś napięcie.
2. Przy 15,30 V ± 0,05 V przekaźnik musi **rozewrzeć**.
3. Obniżaj — przy 14,00 V musi **zewrzeć z powrotem**.
4. Powtórz trzy razy; próg nie może pływać o więcej niż 0,05 V.
5. Odłącz zasilanie modułu — przekaźnik musi być **rozwarty** (to jest
   bariera przeciw przepływowi wstecznemu z §5.4).
6. **Zasilanie tylko od strony banku.** DC-IN zostaw odłączone, a 12,6 V
   z zasilacza podaj **wyłącznie na zaciski OUT** (tam, gdzie w aucie będzie
   bank), z miliamperomierzem w szereg. Wyświetlacz ma pozostać **ciemny**,
   przekaźnik **rozwarty** (omomierz DC-IN+ ↔ OUT+: rozwarcie), a prąd
   **< 1 mA**. Punkt 5 tego nie sprawdza, bo wtedy na OUT nic nie ma.

Jeżeli pkt 6 nie przejdzie — płytka świeci, zwiera przekaźnik albo bierze
więcej niż 1 mA — założenie z §5.4 pkt 2 jest fałszywe. Akumulator rozruchowy
dalej odcina K1, ale bank na postoju byłby podpięty pod martwe wyjście
XY-SK120 i karmiłby wyświetlacz płytki. Dwie poprawki:

- **dioda Schottky'ego w szereg w każdej gałęzi** między OUT XH-M603
  a złączeniem (anoda od strony płytki). XH-M603 musi wtedy mierzyć stronę
  banku (za diodą), a CV podnosisz o **zmierzony** spadek diody przy 5 A.
  Konkretny typ podawaj dopiero po wybraniu diody i sprawdzeniu jej karty
  (prąd ciągły z zapasem, chłodzenie — przy 5 A to kilka watów),
- albo **dodatkowy styk przekaźnika** w każdej gałęzi, zasilany tylko wtedy,
  gdy K1 jest zwarty (cewka równolegle do K1 albo przekaźnik z dwoma torami).

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

> Jeżeli w okolicy 11 V moduł zachowuje się niepewnie — albo przetwornica
> step-up w §3.4 przestała regulować powyżej 11 V — **podnieś próg do
> 11,5 V**. Dla AGM przy poborze rzędu 100 mA to nadal głębokie rozładowanie,
> więc ochrona zostaje zachowana, a moduły pracują w swoim zakresie.

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

Tak, z prawie dwukrotnym zapasem. Przez LVD przechodzi cały prąd odbiorników
(najgorszy przypadek: bank tuż nad progiem 11,0 V):

| Odbiornik | Prąd szczytowy |
|-----------|---------------|
| Step-up (65 W na wtyku, wejście przy 11 V) | do 6,6 A |
| Hub USB z peryferiami | ~1,0 A |
| Buck wyświetlaczy (LM2596) | ~1,5 A |
| Domena A (logika + cewki) | ~0,5 A |
| Telefon przez wstrzykiwacz 5 V (opcja) | ~0,9 A |
| **Razem** | **~10,5 A** |

Typowo płynie ≈ 5 A (§2.1). Kluczowe jest to, że **wzmacniacze idą osobną
gałęzią** prosto z akumulatora rozruchowego (§2). Gdyby szły przez LVD, ich
szczyty 15–20 A przekroczyłyby przekaźnik 20 A.

Bezpiecznik **F7** między blokiem L+ banku a VIN+: **20 A**. Reguła
producenta modułu to 1,5 × prąd szczytowy, czyli 1,5 × 10,5 = 15,75 A —
najbliższa większa wkładka to 20 A. (Poprzednie wydanie miało 15 A przy
szczycie 7,5 A z XL6019; z pełnymi 65 W i telefonem 15 A schodzi poniżej
reguły.) Przewód odbioru 6 mm² jest wkładką 20 A chroniony z dużym zapasem.
Wartość **nie zależy od liczby pakietów**: przez F7 płynie wyłącznie prąd
odbiorników, a prąd ładowania wchodzi do bloku L+ obok niego (przez F12).

> **Wymagana klasa wkładki.** Prąd zwarciowy na zaciskach odbioru banku to
> ok. **2,2 kA** (§4.4), a wkładka ATO/ATC ma katalogową zdolność wyłączania
> ok. **1 kA @ 32 V DC** (ISO 8820 / SAE J1888). Poza tą wartością
> bezpiecznik zamiast przerwać obwód może zapalić łuk. Na F7 i F12 użyj
> wkładki **MIDI/AMI albo ANL** o zdolności wyłączania **≥ 2,5 kA** wg karty.
> Uwaga praktyczna: typoszeregi MIDI/ANL bywają dostępne dopiero od ok.
> 30 A — jeżeli 15 / 20 A w tej klasie nie da się kupić, opisz to w §13.7
> i zdecyduj świadomie (30 A nadal chroni przewód 6 mm², ale nie przekaźnik
> LVD przed przeciążeniem; przed tym chronią go wkładki odgałęzień F8–F13).
> Repozytorium nie zawiera kart tych wkładek — potwierdź przed zakupem.

### 7.5 Co odcina LVD

Całą szynę buforowaną. Logika też przestaje działać (pilot szyb i BLE
bagażnika nie odpowiadają), ale to celowe: bank przetrwa i naładuje się przy
następnym uruchomieniu silnika. Alternatywa — pozwolić Nano dojechać bank
do 9 V — kończy się wymianą kompletu pakietów.

Moduł montuj **w bagażniku, za bankiem, przed rozgałęzieniem odbiorników**
— patrz [`power_buffered_m910q.svg`](../schematics/power_buffered_m910q.svg).

> **XH-M609 nie zastąpi blokady przeładowania z §6.** To moduł ochrony
> **podnapięciowej** — rozłącza *poniżej* progu. Warstwa 2 potrzebuje logiki
> odwrotnej (rozwarcie *powyżej* 15,3 V), więc pozostaje osobnym modułem.

---

## 8. Bezpieczniki, przekroje, masa

### 8.1 Bezpieczniki

| Bezpiecznik | Wartość | Umiejscowienie |
|-------------|---------|----------------|
| Tor ładowania (**F1**) | **20 A**, klasa jak F7 (**MIDI/AMI lub ANL**, zdolność wyłączania ≥ prąd zwarciowy akumulatora rozruchowego wg karty; przyjmij ≥ 2,5 kA) | **maks. 30 cm od klemy „+"** akumulatora rozruchowego — jedyne połączenie zestawu z rozruchowym (poza osobną gałęzią wzmacniacza) |
| Na pakiet banku (**FB1…FB7**) | 10 A ATO / mini × 7 | na „+" każdego pakietu, **5–10 cm od zacisku** |
| Blok L+ → XH-M609 VIN+ (**F7**) | 20 A, **MIDI/AMI lub ANL** | przy bloku L+ — klasa w §7.4 |
| Przewód ładowania → blok L+ (**F12**) | 15 A, klasa jak F7 | przy bloku L+ (§5.4) |
| Gałęzie ładowarek (**FC1**, **FC2**) | 7,5 A ATO × 2 | przy zacisku OUT+ każdego XH-M603, przed złączeniem gałęzi (§5.4) |
| Cewka K1 (**FK**) | 1 A ATO | w miejscu wpięcia w obwód zapłonu / D+ (§5.4) |
| Wejście step-up (**F8**) | 10 A | na dystrybucji za LVD |
| Buck LM2596 — wyświetlacze (**F9**) | 2 A | na dystrybucji za LVD |
| Buck MP1584 — logika, Arduino (**F10**) | 3 A | na dystrybucji za LVD |
| AUX 12 V — moduł przekaźników, wentylator (**F11**) | 5 A | na dystrybucji za LVD |
| Wstrzykiwacz 5 V telefonu (**F13**, opcja) | 2 A | na dystrybucji za LVD |
| Wyjście step-up | 5 A | przy wyjściu przetwornicy, w bagażniku |
| Przewód pomiarowy banku (`FEATURE_BATT_ADC`, §13.4) | 1 A | przy banku |
| Gałąź wzmacniacza | wg karty modułu (20–30 A), klasa jak F1 | osobno, przy klemie akumulatora rozruchowego |

Bezpiecznik **przy źródle**, nie przy urządzeniu — zwarcie przewodu
o karoserię w połowie trasy ma być przerwane przy źródle, inaczej cały
przewód staje się grzałką. Dlatego wszystkie odgałęzienia biegnące do przodu
(F9, F10, F11, F13, wyjście step-up) mają wkładki **w bagażniku**, na
początku trasy, a przewód cewki K1, który biegnie w drugą stronę — **FK
z przodu**, tam, gdzie wpinasz się w zapłon / D+: bezpiecznik obwodu auta
(15–20 A) nie chroni 4–5 m przewodu 0,75 mm².

**FC1/FC2 przy OUT, a nie przy DC-IN XH-M603.** Groźny prąd w gałęzi
przychodzi od banku (przez zwarty przekaźnik płytki do uszkodzonej
XY-SK120) albo z drugiej ładowarki przez złączenie — oba wchodzą do gałęzi
od strony złączenia. Wkładka przy OUT przerywa je przed płytką; ta sama
wkładka przerywa też nadprąd w przód z uszkodzonego regulatora CC.

**Dlaczego F1 to 20 A, a nie 15 A.** Dwie XY-SK120 biorą z instalacji
11,9 A (silnik pracuje) do 13,0 A (kluczyk ON, silnik stoi) — §5.4. Wkładka
15 A przy ciągłych 12–13 A pracowałaby na 80–87 % przez całą jazdę, w ciepłej
komorze silnika — to przepis na przepalenie bez usterki. 20 A daje 60–65 %,
a przewód 6 mm² jest nią chroniony z zapasem.

**Wkładki za LVD (F8–F11, F13) i w gałęziach ładowarek (FC1, FC2) mogą być
zwykłymi ATO** — dla FC rachunek ~480–590 A jest w §5.4. Zwarcie za LVD zasila
bank przez F7, przekaźnik LVD, przewody i samą wkładkę odgałęzienia; ich
rezystancje (kilkanaście mΩ razem — oszacowanie) ograniczają prąd do
kilkuset amperów, czyli poniżej ~1 kA zdolności wyłączania ATO. Wkładki
**przed** LVD (F7, F12) widzą pełne ~2,2 kA i muszą być wyższej klasy.

**F1 (i gałąź wzmacniacza) — ta sama klasa co F7.** Akumulator rozruchowy
60–70 Ah ma rezystancję wewnętrzną rzędu kilku mΩ, a 30 cm przewodu 6 mm²
z klemą i oprawką dokłada ok. 1 mΩ — zwarcie tuż za F1 to więc ok.
**1,2–2,5 kA**, powyżej ~1 kA zdolności wyłączania ATO. To **szacunek**, nie
pomiar (rezystancji Twojego akumulatora nie znamy). Jeśli MIDI/ANL 20 A nie
da się kupić, **30 A** w tej klasie nadal chroni przewód 6 mm² — zmniejsza
tylko zapas wkładki nad 11,9–13,0 A poboru ładowarek (§13.7 #8). Zwykła ATO
w tym miejscu to świadomy kompromis, nie wariant równoważny.

**Dlaczego 10 A na pakiet, skoro pakiet wiezie ~0,7 A.** Prąd roboczy jednej
gałęzi to 5/7 ≈ **0,71 A** przy typowym rozładowaniu (≈ 1,5 A w szczycie
10,5 A) i ≈ **0,71 A** przy ładowaniu netto 5 A, więc wkładka 10 A ma
zapas kilkukrotny. Jej wartość wynika z obciążalności nasuwki F2 i przewodu
2,5 mm² oraz z selektywności, a nie z liczby pakietów.

**Selektywność.** Przy zwarciu wewnątrz jednego pakietu przez jego wkładkę
płynie prąd z sześciu pozostałych: 12,85 V / (34,4/6 + 11,4) mΩ ≈ **750 A**
(11,4 mΩ to odcinek, wkładka i przejścia zwartej gałęzi), a przez każdą
z sześciu zdrowych gałęzi ≈ 125 A. Stosunek 6 : 1 — pali się właściwy
bezpiecznik. 750 A mieści się w ~1 kA zdolności wyłączania wkładki ATO.
Dla zwartej pojedynczej celi (ΔU 2,1 V) wychodzi 2,1 V / (34,4 + 5,7) mΩ ≈
**52 A**, czyli ok. 5 × prąd znamionowy wkładki — też zadziała.

> **Oznaczenia: FB1…FB7, a nie F2…F8.** Proste rozciągnięcie dawnego ciągu
> F2…F5 na siedem pakietów weszłoby w kolizję z **F7** (bank → LVD)
> i **F8** (wejście przetwornicy na płytce B,
> [`PCB_ZASILANIE.md`](PCB_ZASILANIE.md) §1). Bezpieczniki gałęziowe banku
> mają więc własną serię **FB**; F12 (przewód ładowania przy banku) i F13
> (telefon) to nowe pozycje w tym wydaniu.

### 8.2 Przekroje przewodów

Przewody samochodowe (FLRY/FLRY-B, czysta miedź), nie instalacyjne YDY
i **nie CCA** (aluminium miedziowane ma ~1,6 × większą rezystancję i gorzej
znosi zaciskanie). Spadek liczony na pętli, ρ = 0,0172 Ω·mm²/m.

| Odcinek | Długość | Prąd | Przekrój | Spadek |
|---------|---------|------|----------|--------|
| Akumulator → F1 → bagażnik (TVS/C/K1) | ~5 m (zmierz) | 11,9–13,0 A | **6 mm²** | 0,17–0,19 V na „+" (14,3 mΩ); powrót przez nadwozie i punkt masy (§5.6) |
| K1 → każda XY-SK120 | ≤ 1 m | ~6–6,5 A | 2,5 mm² | pomijalny |
| XY-SK120 → XH-M603 → FC1/FC2 → złączenie | ≤ 0,5 m, obie gałęzie równe | 5 A | 2,5 mm² | pomijalny; wkładka 7,5 A przy OUT+ XH-M603 |
| Złączenie → F12 → blok L+ | ≤ 1 m | 10 A | **4 mm²** | 0,09 V pętli przy 10 A — CV nastawiaj bez banku, na banku sprawdzaj przy < 1 A (§5.3) |
| Pakiet → blok (14 szt.) | 0,25 m ±30 mm | ≤ 1,5 A | **FLRY-B 2,5 mm²** | §4.3 |
| Łącznik L ↔ P („+" i „−") | 0,4–0,6 m | ≤ ~6 A | **6 mm² OFC** | §4.3 |
| Blok L+ → F7 → LVD | ≤ 0,5 m | do 10,5 A | **6 mm²** | pomijalny |
| Masa banku P− → punkt masy | ≤ 0,5 m | do ~13 A (powrót ładowania) | **6 mm²** | pomijalny |
| LVD → dystrybucja | ≤ 0,5 m | do 10,5 A | 4 mm² | pomijalny |
| F8 → step-up | ≤ 1 m | do 6,6 A | 4 mm² | pomijalny |
| **Step-up → M910q** („+" i „−") | **~4 m** | 3,3 A @ 20 V | **4 mm²** | **0,11 V** (§3.1) |
| F9 → LM2596 wyświetlaczy (przód) | ~4 m | ~1,5 A | 1,0 mm² | 0,10 V na „+" |
| F10 → MP1584 logiki (przód) | ~4 m | < 1 A | 0,75 mm² | < 0,1 V |
| F13 → wstrzykiwacz telefonu (przód) | ~4 m | < 1 A | 0,75 mm² | < 0,1 V |
| F11 → AUX (moduł przekaźników) | wg miejsca | do ~2 A | 1,5 mm² | — |
| **Wspólny powrót 12 V z przodu** → punkt masy | ~4 m | do ~4 A | **2,5 mm²** | 0,11 V |
| K1 cewka ← FK 1 A ← zapłon / D+ | ~4–5 m | ~0,15 A | 0,75 mm² | — |
| Gałąź wzmacniacza | ~4 m do bagażnika | wg modułu | 6 mm² | — |

**Dlaczego bucki stoją z przodu, a do przodu idzie 12 V.** 5 V z bucka przy
1,5 A na 4 m spadłoby o kilka procent i pływało z obciążeniem; 12 V na tej
samej trasie traci < 1 %, a buck przy odbiorniku i tak stabilizuje. Każde
odgałęzienie ma własną wkładkę w bagażniku i własny przewód „+"; powrót jest
wspólny (2,5 mm²) do punktu masy przy banku — nie przez karoserię z przodu.

**Ładowarki tuż przy banku.** Moduły XY-SK120 i XH-M603 stoją w bagażniku
obok koszy, więc przewód ładowania do banku ma ≤ 1 m i spadek w pętli CV
jest pomijalny (dawniej 3 m i dyskusja 2,5 vs 4 mm²).

### 8.3 Masa

- **jeden punkt masy** dla całego head unitu — gwiazda, nie łańcuszek —
  **w bagażniku przy banku**: blok P− (albo osobny blok masowy tuż obok,
  spięty z P− krótkim 6 mm²) i z niego **jeden** przewód 6 mm² do karoserii,
- śruba do gołego metalu nadwozia, powierzchnia oczyszczona ze szpachli
  i lakieru, po dokręceniu zabezpieczona wazeliną techniczną — **nie** w
  podłodze nad zbiornikiem (§4.7); użyj istniejącego punktu masy w bagażniku
  albo śruby w grodzi / nadkolu,
- w tym punkcie schodzą się: bank, masy XY-SK120 (wejście i wyjście),
  XH-M603, LVD, dystrybucja, step-up, powrót 20 V z M910q, wspólny powrót
  12 V z przodu i masa audio,
- M910q, panele i moduły z przodu **nie dostają własnej masy do karoserii**;
  jeżeli obudowa M910q dotyka metalu, to jest druga droga masy — przy
  przydźwięku sprawdź to pierwsze,
- masa wzmacniacza osobno, blisko wzmacniacza — inaczej dostaniesz pętlę
  masy i przydźwięk alternatora w głośnikach.

### 8.4 Praktyka montażowa

- przejścia przez blachę **zawsze** przez przelotkę gumową,
- wiązki w peszlu/oplocie, mocowane co 30 cm (łącznik między koszami co
  15 cm, pod osłoną),
- konektory zaciskane właściwą zaciskarką i dodatkowo koszulka
  termokurczliwa z klejem; lutowanie w miejscach narażonych na wibracje
  łamie się przy wyjściu z lutu,
- zapas długości przy każdym urządzeniu (pętla serwisowa),
- **wyłącznik główny masy** banku (rozłącznik 100 A) — bardzo ułatwia
  serwis i jest wymagany, jeśli auto stanie na dłużej. Przenosi maksymalnie
  ~13 A (powrót ładowania) albo 10,5 A (rozładowanie),
- ⚠ **rozłącznik masy rozłączaj wyłącznie bez obciążenia.** Prąd zwarciowy
  prospektywny banku to ~2,2–2,6 kA (§4.4), a typowe rozłączniki podają
  100 A ciągle / ~1250 A rozruchowo / ~2500 A chwilowo — jesteś blisko
  granicy. Sprawdź kartę katalogową swojego egzemplarza,
- **bloki zbiorcze banku muszą mieć pokrywę.** Szesnaście kołków M6 przy
  ponad 2 kA prądu zwarciowego to nie jest miejsce na upuszczony klucz.

---

## 8a. Bagażnik i trasa do przodu

Rozmieszczenie przyjęte do dalszych prac: **bank w dwóch koszach w bagażniku**
(§4.7), obok nich **ładowarki, LVD, dystrybucja i przetwornica step-up**;
**M910q przy nogach pasażera**, ok. 4 m dalej.

### 8a.1 Gdzie postawić przetwornicę — to nie jest obojętne

Przez długą trasę do przodu opłaca się przesyłać **20 V, nie 12 V**. Ta sama
moc przy wyższym napięciu to mniejszy prąd, a straty spadają z kwadratem
prądu (M910q 45 W, 4 mm², pętla 2 × 4 m = 34,4 mΩ):

| Wariant | Prąd w trasie | Spadek | Straty w przewodzie |
|---------|---------------|--------|---------------------|
| step-up z przodu, 12 V do przodu | 4,0 A | 0,14 V (1,1 %) | 0,55 W |
| **step-up w bagażniku, 20 V do przodu** | **2,26 A** | **0,08 V (0,4 %)** | **0,18 W** |

Drugi powód jest ważniejszy od strat: **LVD musi mierzyć napięcie banku,
a nie napięcie po czterech metrach przewodu**. Trzymając LVD i przetwornicę
przy banku, mierzysz to, co trzeba.

### 8a.2 Wiązka bagażnik → deska

Do przodu idzie jedna wiązka w peszlu (przekroje w §8.2):

| Żyła | Przekrój | Wkładka (w bagażniku) |
|------|----------|-----------------------|
| 20 V „+" i „−" do M910q | 2 × 4 mm² | 5 A na wyjściu przetwornicy |
| 12 V do LM2596 (wyświetlacze) | 1,0 mm² | F9 2 A |
| 12 V do MP1584 (logika, Arduino) | 0,75 mm² | F10 3 A |
| 12 V do wstrzykiwacza telefonu (opcja) | 0,75 mm² | F13 2 A |
| 12 V AUX (jeśli moduł przekaźników jest z przodu) | 1,5 mm² | F11 5 A |
| wspólny powrót 12 V | 2,5 mm² | — |
| sygnał zapłonu / D+ do cewki K1 (w drugą stronę) | 0,75 mm² | **FK 1 A z przodu**, przy wpięciu w zapłon / D+ |

| pomiar napięcia banku do sensor huba (opcja, §13.4) | 0,5 mm² | 1 A przy banku |

Ekran i przewody RCA do wzmacniacza prowadź **po drugiej stronie auta** niż
tę wiązkę i przewód F1.

### 8a.3 Bezpiecznik przy banku — bezwzględnie

Każdy przewód wychodzący z bloku L+ **musi mieć bezpiecznik w odległości do
30 cm od bloku**: F7 (odbiorniki) i F12 (ładowanie). Bank daje prąd
zwarciowy prospektywny ok. **2,2 kA**; niezabezpieczony przewód to przy
zwarciu palnik. Klasa wkładek w §7.4.

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
| Przetwornica step-up bez obciążenia (M910q wyłączony) — **I_jał** | **do zmierzenia** (§3.4) — zalewane moduły nie podają prądu jałowego; wisi na szynie także w S3 i po wyłączeniu |
| Telefon na buforze przez wstrzykiwacz 5 V (opcja, §14.6) | **~30–100 mA** naładowany (szacunek, do zmierzenia); **do ~0,9 A**, gdy się ładuje |

> **Pobór własny LVD jest częścią budżetu postoju.** XH-M609 ma wyświetlacz
> LED i przekaźnik trzymany w stanie załączonym, więc nie jest to element
> pomijalny — katalogowe „< 1,5 W" przy 12 V oznaczałoby aż 125 mA, czyli
> **dwukrotnie więcej niż cała reszta logiki**. Realny pobór przy 12 V jest
> zwykle znacznie niższy (spec obejmuje cały zakres do 36 V), ale dopóki nie
> zmierzysz, nie wiesz, w której kolumnie tabeli poniżej jesteś.

> **Telefon to największa niewiadoma postoju.** Jeżeli trzymasz go na
> buforze (wybudzanie IR z §14.6), dolicz jego pobór do wiersza z §9.2:
> +60 mA przesuwa Cię mniej więcej o jeden wiersz w dół (np. 80 → 130 mA).
> Telefon, który przy każdym postoju doładowuje się od 50 %, zjada przez
> 1–2 h po 0,9 A — czyli 1–2 Ah na postój. W aucie testowym bez bufora
> telefon jest zasilany z obwodu zapłonu i do tego budżetu nie wchodzi
> ([`PRZYGOTOWANIE_TELEFONU.md`](PRZYGOTOWANIE_TELEFONU.md) §18).

> **Czego w tym budżecie nie ma.** Tabela obejmuje domenę A w rozumieniu §2:
> Nano #1, HM-10, RXB6, moduł przekaźników i straty bucka, plus telefon jako
> opcję. Nie ma w niej Arduino Pro Micro, Nano #2 ani modułu wyświetlacza
> 1,8" na ESP32 ([`WYSWIETLACZ_ESP32_1V8.md`](WYSWIETLACZ_ESP32_1V8.md)) —
> a ten ostatni bierze ok. **60 mA z 12 V**, czyli tyle, co cała reszta
> logiki razem wzięta. Jeżeli panel trafi na szynę buforowaną, przesuwasz się
> o jeden–dwa wiersze w dół tabeli §9.2: postój schodzi z 9,3–4,0 na
> **5,3–3,0 dnia**. Rachunek i decyzja — w tamtym dokumencie.

### 9.2 Czas postoju

Czas zależy od tego, ile pobiera XH-M609 — dlatego tabela jest rozpisana
wg **sumarycznego poboru**. Logika i przekaźniki to stałe 60 mA; reszta to
moduł LVD, **prąd jałowy step-upu I_jał** i ewentualnie telefon (§9.1).

> **I_jał dodaj do każdego wiersza.** Tabele niżej są liczone bez niego,
> bo dla nowej przetwornicy nikt go jeszcze nie zmierzył (§3.4). Zmierzony
> prąd dodajesz wprost do kolumny „Pobór całkowity" i czytasz czas
> z wiersza o tym poborze. **Dla ilustracji, nie jako wartość zmierzona:**
> gdyby I_jał wyszedł 50 mA, wiersz 80 mA staje się wierszem 130 mA
> (9,3 → 5,7 dnia do 50 % DoD); gdyby 100 mA — wychodzi ok. 180 mA, prawie
> wiersz 185 mA (ok. 4,1 dnia zamiast 9,3).

**Bank 7 pakietów — 35,7 Ah** (konfiguracja przyjęta):

| Pobór całkowity | Ponad 60 mA logiki (XH-M609 + I_jał + telefon) | Do 30 % DoD | Do 50 % DoD | Do progu LVD |
|-----------------|---------|-------------|-------------|--------------|
| 80 mA | 20 mA | ~5,6 dnia | ~9,3 dnia | ~13,9 dnia |
| 100 mA | 40 mA | ~4,5 dnia | ~7,4 dnia | ~11,2 dnia |
| 130 mA | 70 mA | ~3,4 dnia | ~5,7 dnia | ~8,6 dnia |
| 185 mA | 125 mA (sam XH-M609 wg spec max) | ~2,4 dnia | ~4,0 dnia | ~6,0 dnia |

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

> **Korekta rachunkowa wobec starszego wydania.** Tabela podpisana tam
> „Bank 4 pakiety — 20,4 Ah" była w rzeczywistości policzona dla **25,5 Ah**
> (pięciu pakietów) — wszystkie dwanaście komórek było zawyżonych dokładnie
> o 25 %. Liczby wyżej policzono od zera.

Kolumna 30 % DoD jest tu dlatego, że HR1221W to seria buforowa (UPS), a nie
trakcyjna — płytsze rozładowanie wyraźnie wydłuża jej życie. Przy okazjonalnym
dłuższym postoju 50 % DoD jest w porządku; jako **rutyna** lepiej trzymać 30 %.

> **Siedem pakietów kupuje łagodniejszy reżim, nie tylko dłuższy postój.**
> Siódemka przy 30 % DoD daje 10,71 Ah użytecznych, czyli **więcej niż czwórka
> przy 50 % DoD** (10,2 Ah).

> **Pomiar poboru XH-M609 nadal rozstrzyga.** Kierunek „więcej akumulatorów"
> jest wyczerpany; pomiar z §7.3 decyduje, w którym wierszu powyższej tabeli
> siedzisz. Jeżeli wypadnie przy 125 mA, realne kierunki to:
>
> - **wymiana LVD** na moduł bez wyświetlacza (prosty komparator
>   z przekaźnikiem pobiera 5–10 mA zamiast 20–125 mA),
> - **skrócenie progu eskalacji** z 2 h do np. 30 min, żeby maszyna szybciej
>   schodziła z S3 (200–460 mA + I_jał) do wyłączenia (50–150 mA + I_jał),
> - **wyłącznik główny** przy dłuższym postoju — jedyne prawdziwe zero.

> **Korekta wobec starszych notatek.** `docs/X86_PLATFORM_SETUP.md` § 2.3
> i `10-power-suspend.html` podają dla banku 25 Ah „~17 dni" z adnotacją
> „ograniczone do 50 % DoD". Te dwie rzeczy się wykluczają: 25 Ah / 0,060 A
> = 417 h = 17,4 dnia to **pełne rozładowanie do zera**. Obowiązuje tabela
> z §2.1 i powyższa.

Samorozładowanie HR1221W (> 75 % pojemności po 6 miesiącach @ 25 °C, czyli
≤ 4 %/miesiąc) odpowiada ok. **2,0 mA** przy banku 35,7 Ah — wobec 60 mA
logiki to 3,3 %, czyli pomijalne. W gorącym bagażniku rośnie kilkukrotnie,
ale nadal nie zmienia obrazu. Po rozłączeniu wyłącznika głównego
samorozładowanie zostaje **jedynym** odbiornikiem i bank i tak zejdzie
o kilka procent miesięcznie.

Kolumna „do progu LVD" zakłada zejście do ~75 % DoD (11,0 V pod bardzo
lekkim obciążeniem). Jest osiągalna, ale każde takie zejście kosztuje
żywotność — traktuj ją jako rezerwę awaryjną, nie tryb normalnej pracy.

> **Brak poprawki Peukerta.** Pojemność katalogowa 5,1 Ah jest podana dla
> rozładowania 20-godzinnego (C/20). Przy pracy z 5 A siedem pakietów pracuje
> z krotnością ok. C/7, czyli szybciej niż w karcie — realny czas pracy przy
> zgaszonym silniku będzie nieco krótszy niż 3,6 h z §2.1. Skali tej korekty
> nie da się policzyć bez krzywych rozładowania HR1221W, których repozytorium
> nie zawiera. Postoje (50–460 mA) są bliżej C/20 i tej korekty praktycznie
> nie potrzebują.

### 9.3 Budzenie RTC

Jeśli włączysz budzenie M910q z RTC (np. co 15 min na ping pozycji), dolicz
ok. **5 Ah tygodniowo** — czyli **+29,8 mA** równoważnego poboru ciągłego
(5 Ah / 168 h). Przy poborze bazowym 80 mA skraca to powyższe czasy do
**ok. 73 %**: 9,3 dnia → 6,8 dnia do 50 % DoD. Przy większym poborze bazowym
efekt jest jeszcze mniejszy. Przy dłuższym postoju wyłącz budzenie z UI.

> **Budzenie RTC dokłada prąd, a nie zabiera pojemność**, więc skrócenie jest
> ilorazem `I / (I + 29,8 mA)` i przy 80 mA wynosi 0,73 — niezależnie od
> liczby pakietów. Żeby czasy naprawdę spadły o połowę, budzenie musiałoby
> kosztować ~13,4 Ah tygodniowo.

### 9.4 Ładowanie po postoju

Ładowarki dają razem **10 A** (2 × 5 A), odbiorniki w czasie jazdy biorą
**≈ 5 A** (4–6 A, §2.1), więc bank ładuje się netto prądem **≈ 5 A**
(4–6 A). Mnożnik z fazy CC na pełne naładowanie to ×1,3–1,5 (absorpcja).

| Stan wyjściowy | Do uzupełnienia | Faza CC przy 5 A netto | Realnie jazdy (×1,3–1,5) | Przy netto 4 A / 6 A (faza CC) |
|----------------|-----------------|------------------------|--------------------------|--------------------------------|
| 30 % DoD (reżim rutynowy dla serii HR) | 10,71 Ah | 2,14 h | **2,8–3,2 h** | 2,68 h / 1,79 h |
| 50 % DoD (po rutynowym postoju) | 17,85 Ah | 3,57 h | **4,6–5,4 h** | 4,46 h / 2,98 h |
| próg LVD (~75 % DoD) | 26,78 Ah | 5,36 h | **7,0–8,0 h** | 6,70 h / 4,46 h |

Porównanie wariantów ładowania (faza CC z progu LVD, obciążenie 5 A):

| Ładowanie | Netto do banku | Faza CC z progu LVD |
|-----------|----------------|---------------------|
| poprzednie wydanie: boost CC 8,0 A, obciążenie 3,5 A (XL6019 z RAPL) | 4,5 A | 5,95 h |
| jedna XY-SK120 CC 5 A | ≈ 0 A | bank się nie ładuje |
| **2 × XY-SK120 CC 5 A — przyjęte** | **≈ 5 A** | **5,36 h** |
| 2 × XY-SK120 CC 6 A (bez zapasu cieplnego) | ≈ 7 A | 3,83 h |

> **Uczciwie: czas ładowania prawie się nie zmienił.** Dwie ładowarki dają
> więcej prądu niż dawny boost (10 vs 8 A), ale komputer bez limitu RAPL
> i telefon biorą więcej (5 vs 3,5 A). Netto wychodzi podobnie — zysk
> polega na tym, że M910q nie jest już przycięty, a cały tor pracuje z
> zapasem.

> **Minimalna dzienna jazda podtrzymująca bilans** zależy od **prądu netto**,
> a nie od pojemności banku:
>
> | Pobór spoczynkowy | Pobór dobowy | Minimalna jazda przy netto 5 A | przy netto 4 A |
> |-------------------|--------------|--------------------------------|----------------|
> | 80 mA | 1,92 Ah | **23 min/dobę** | 29 min |
> | 130 mA | 3,12 Ah | **37 min/dobę** | 47 min |
> | 185 mA | 4,44 Ah | **53 min/dobę** | 67 min |
> | 300 mA (S3) | 7,20 Ah | **86 min/dobę** | 108 min |
>
> Pobór spoczynkowy w tej tabeli to **całość, razem z I_jał step-upu**
> (§9.2): zmierzony I_jał dodajesz do wiersza, zanim odczytasz minuty
> (np. 80 mA + 50 mA = wiersz 130 mA).

Krótkie przejazdy po mieście nie doładują banku po dłuższym postoju. Jeśli
tak wygląda Twój profil użytkowania, **ładowarka sieciowa na czas parkowania
w garażu przestaje być opcją i staje się częścią układu** (§10.3).

> **Te czasy są optymistyczne o 5–15 %.** Nie stosujemy współczynnika
> przyjęcia ładunku (AGM wymaga oddania 105–115 % pobranych amperogodzin).
> Przy 5,36 h fazy CC to dodatkowe 0,3–0,8 h.

---

## 10. Lista zakupowa

> Ta lista dotyczy **wersji docelowej**. Budujesz wariant testowy?
> Wszystko w jednej tabeli: [`LISTA_ZAKUPOWA.md`](LISTA_ZAKUPOWA.md).
> Ceny są orientacyjne (ogłoszenia, zmienne). Pozycje oznaczone „do wyceny"
> nie mają w repozytorium żadnej ceny i nie wchodzą do sumy.

### 10.1 Już posiadane

| Element | Rola w torze | Uwaga |
|---------|--------------|-------|
| **XH-M609** — moduł ochrony | **LVD** (warstwa 3), 11,00 / 12,60 V | przekaźnik 20 A wystarcza; zmierz pobór własny, §7.3 |
| **CSB HR1221W F2** × 8 (12 V / 5,1 Ah AGM) | bank buforowy | **użyj 7 (35,7 Ah)** — jeden zostaje jako zapas; §4.2 mówi, czego ten jeden pakiet nie załatwia |
| Lenovo ThinkCentre M910q Tiny + oryginalny zasilacz | komputer; z zasilacza bierzesz kabel z wtykiem (§3.3) | |
| XL6019 — moduł step-up | **zastąpiony** (§3) | zostaje na półce; nie używaj go zamiast przetwornicy 200 W |

### 10.2 Do dokupienia — obowiązkowe

| # | Element | Specyfikacja | Szt. | Cena (PLN) |
|---|---------|--------------|------|-----------|
| 1 | **Przetwornica step-up** | zalewana IP67/IP68, 12 V → **20 V, 10 A (200 W)**, wejście ~9–18 V — §3.2; sprawdzenie po zakupie §3.4 | 1 | 60–130 |
| 2 | **Ładowarka CC-CV** | **XY-SK120** (albo XY-SK120X), buck-boost 6–36 V, 6 A / 120 W — §5.2 | **2** | 120–180 |
| 3 | **Rozłącznik nadnapięciowy** | **XH-M603** (albo XH-M604), 15,30 / 14,00 V — **po jednym na ładowarkę**, §6.3 | **2** | 80–160 |
| 4 | **Przekaźnik ładowania K1** | 12 V / 30 A SPDT + podstawka (jedyny przekaźnik poza LVD) | 1 | 15–25 |
| 5 | **Dystrybucja za LVD** | listwa bezpiecznikowa 6–8 obwodów ATO z pokrywą albo płytka B ([`PCB_ZASILANIE.md`](PCB_ZASILANIE.md)) | 1 | 40–70 |
| 6 | **F1 + oprawka** | 20 A (albo 30 A, jeśli 20 A brak), **MIDI/AMI lub ANL**, zdolność wyłączania ≥ 2,5 kA wg karty, do montażu przy klemie (§8.1) | 1 | do wyceny |
| 7 | **FB1…FB7, FC1, FC2, FK + oprawki inline** | ATO / mini, oprawki na 2,5 mm² (FK na 0,75 mm²); wkładki: FB 10 A, FC 7,5 A, FK 1 A (§5.4) | 10 | 35–57 |
| 8 | **F7 i F12 + oprawki** | 20 A i 15 A, **MIDI/AMI lub ANL**, zdolność wyłączania ≥ 2,5 kA wg karty (§7.4) | 2 | do wyceny |
| 9 | **Wkładki nożowe** | 10 A (F8), 2 A (F9), 3 A (F10), 5 A (F11), 2 A (F13), 5 A (wyjście step-up), 1 A (pomiar), zapas FB 10 A / FC 7,5 A / FK 1 A | kpl. | 10–15 |
| 9a | **Oprawki inline ATO × 2** do wkładek z poz. 9 | jedna na przewód **4 mm²** (5 A, wyjście step-upu — oprawki z poz. 7 są na 2,5 / 0,75 mm²), jedna na **0,5 mm²** (1 A, pomiar banku) | 2 | 10–20 |
| 10 | **Buck 12 → 5 V** (logika, Arduino) | **MP1584**, min. 1 A | 1 | 5–10 |
| 11 | **Buck 12 → 5 V** (wyświetlacze) | **LM2596**, moduł 3 A (realnie ≤ 2 A ciągle) — potrzebny przez **PWM podświetlenia** (§2.2) | 1 | 5–15 |
| 12 | **Dioda TVS** | **SMCJ20CA** (§5.8) | 2 | 5–10 |
| 13 | **Kondensator elektrolityczny** | 470 µF / 35 V, low-ESR, 105 °C | 2 | 5–10 |
| 14 | **Dioda gaszeniowa** | 1N4007 (cewka K1) | 5 | 2–5 |
| 15 | **Przewód 6 mm²** | **OFC, nie CCA**, FLRY-B albo car-audio, 105 °C: czerwony ~7 m (F1 do bagażnika, łącznik „+", odbiór) + czarny ~2 m (łącznik „−", masa) — §4.3, §8.2 | — | 90–135 |
| 16 | **Przewód 4 mm²** | FLRY: czerwony ~7,5 m + czarny ~5,5 m (20 V do M910q, wejście step-up, LVD, ładowanie) | — | 65–110 |
| 17 | **Przewód 2,5 mm²** | **FLRY-B**: 14 odcinków pakietów (~0,25 m) + gałęzie ładowarek + wspólny powrót z przodu — ok. 12 m razem | — | 50–80 |
| 18 | **Przewody 0,5–1,5 mm²** | FLRY, kilka kolorów: odgałęzienia do przodu, cewka K1, pomiar (§8a.2) — ok. 25–30 m | — | do wyceny |
| 19 | **Bloki zbiorcze banku** | izolowane, **4 kołki M6 + pokrywa** (L+, L−, P+, P−) — §4.3 | 4 | do wyceny |
| 20 | **Oczka zaciskane M6** | izolowane, na 2,5 mm² (14+) i 6 mm² (8+) | ~30 | 45–75 |
| 21 | **Nasuwki, tulejki, koszulki** | 14 **w pełni izolowanych** nasuwek żeńskich 6,3 × 0,8 mm na 1,5–2,5 mm², koszulki z klejem | kpl. | 30–50 |
| 22 | **Peszel / oplot + przelotki gumowe** | ~8 m peszla + komplet przelotek + osłona łącznika między koszami | kpl. | 25–40 |
| 23 | **Kosze na bank** | stal, złącza M8, EPDM, kapturki, chemia — BOM w [`mechanika/kosze_HR1221W_4+3.pdf`](mechanika/kosze_HR1221W_4+3.pdf) §3, streszczenie §4.7 | 2 | do wyceny |
| 24 | **Rozłącznik masy** | 100 A, kluczykowy lub pokrętło | 1 | 40–70 |
| | | | **Razem (bez pozycji „do wyceny")** | **~735–1265 PLN** |

Ceny poz. 15–17 to ceny z poprzedniego wydania przeliczone na nowe długości,
a poz. 7 — cena siedmiu oprawek przeliczona na dziesięć — sprawdź w sklepie. **Wypadły** wobec poprzedniego wydania: boost CC-CV
z diodą MBR2545CT i radiatorem, przekaźnik zapłonu, przekaźnik mocy K2,
skrzynka z pasami, płaskowniki miedziane, radiator i wentylator do XL6019.

### 10.3 Do dokupienia — zalecane

| # | Element | Po co | Cena (PLN) |
|---|---------|-------|-----------|
| 25 | **Woltomierz/amperomierz z bocznikiem 50 A** | podgląd stanu banku bez multimetru | 40–70 |
| 26 | **Multimetr z pomiarem prądu DC 10 A** | pomiary przy uruchomieniu i serwisie | 80–200 |
| 27 | **Ładowarka sieciowa AGM** | doładowanie w garażu przy krótkich przejazdach | 150–300 |
| 28 | **Zaciskarka zapadkowa** (nasuwki i oczka) | zaciski niepewne to najczęstsza usterka instalacji | 60–150 |
| 29 | **Kondensator 470 µF / 35 V low-ESR** | na wyjście step-upu, tylko jeśli §3.2b (bez NTC — §3.2b) | 2–5 (szacunek wg poz. 13, nie sprawdzony) |
| 30 | **Wstrzykiwacz 5 V do telefonu** | przetwornica 12 → 5,1–5,2 V, z odciętym VBUS od strony komputera ([`PRZYGOTOWANIE_TELEFONU.md`](PRZYGOTOWANIE_TELEFONU.md) §18) | do wyceny |

Alternatywa izolowana: VEVOR B2B zamiast poz. 2 (2 × XY-SK120) to
+280–370 PLN, **bez** rozwiązania nadnapięciowego na pełny prąd (§5.7).

### 10.4 Czego **nie** kupować

| Element | Dlaczego |
|---------|----------|
| Moduł buck XL4016 jako ładowarka (z dawnych notatek) | nie podniesie napięcia do absorpcji — patrz §5.1 |
| Przetwornica step-up 19 V | na wtyku po 4 m zejdzie poniżej 19 V — §3.1 |
| Moduł XL6019 zamiast przetwornicy 200 W | wcześniej użyty, daje ok. 45 W — §3 |
| Przewód CCA („miedziowane aluminium") | większa rezystancja, gorzej znosi zaciskanie — §8.2 |
| Jeden XH-M603 na 10 A z dwóch ładowarek | płytka realnie ~8–10 A — §6.3 |
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
Przetwornica step-up 12 → 20 V (§3.4)
[ ] Wyjście bez obciążenia 19,9–20,5 V (multimetr)
[ ] Test obciążeniowy ~60 W przez 30 min — na wyjściu modułu ≥ 19,8 V,
    na wtyku M910q ≥ 19,5 V
[ ] Powtórka przy wejściu 11,0 V — wyjście ≥ 19,8 V, prąd wejściowy ~6,6 A
[ ] Zapisane napięcie wejścia, przy którym moduł przestaje regulować,
    i jego zachowanie (czyste wyłączenie / bez drgań)
[ ] Temperatura obudowy po 30 min przy ~60 W < 60 °C
[ ] Prąd jałowy I_jał przy wejściu 12,6 V zmierzony i zapisany: M910q
    odłączony / wyłączony / w S3 (§3.4) — wpisany do budżetu §9.2
[ ] Brak trybu „czkawki" przy podłączaniu M910q (jeśli jest — §3.2b)

XY-SK120 × 2 (§5.2, §5.5)
[ ] CV 14,40 V (lato ~40 °C: 13,95 V, przy częstych długich trasach
    13,40 V — §5.5) — oba w granicach ±0,02 V, nastawiane bez banku
[ ] CC 5,0 A — sprawdzone amperomierzem na wyjściu, nie tylko na ekranie
[ ] OVP 15,0 V; LVP 12,8 V (jeśli wersja ma regulowane LVP)
[ ] Wyjście po włączeniu zasilania: ON — sprawdzone odcięciem i podaniem
    zasilania
[ ] Temperatura radiatora po 30 min przy 5 A — zapisana

XH-M603 × 2 (§6.4)
[ ] Rozwarcie 15,30 V, powrót 14,00 V — każdy osobno, zasilacz naraz na
    DC-IN i OUT (§6.4 pkt 1)
[ ] Bez zasilania przekaźnik rozwarty
[ ] 12,6 V tylko na OUT (DC-IN odłączone): wyświetlacz ciemny, przekaźnik
    rozwarty, prąd < 1 mA (§6.4 pkt 6) — jeśli nie, poprawka z §6.4
    PRZED montażem
[ ] Temperatura zacisków po 30 min przy 5 A — letnie, nie gorące

XH-M609 (LVD)
[ ] Próg odcięcia 11,00 V, próg powrotu 12,60 V
[ ] Moduł pracuje stabilnie przy 11,0 V — bez drgania styku (§7.3 pkt 1)
[ ] Omomierzem sprawdzone, że przełącza PLUS, nie masę (§7.3 pkt 2)
[ ] Zmierzony pobór własny przy 12 V, wpisany do budżetu §9
[ ] Jeśli pobór wyszedł przy górnej granicy (125 mA) — rozważ wymianę
    modułu na prosty komparator: przy 185 mA łącznie bank siedmiu pakietów
    daje 4,0 dnia do 50 % DoD zamiast 9,3 (§9.2)

Pozostałe
[ ] Buck logiki (MP1584): wyjście 5,0 V
[ ] Buck wyświetlaczy (LM2596): wyjście wg panelu
[ ] TVS: SMCJ20CA (dwukierunkowa) — test diody: OL w obie strony (§5.8)
```

### Etap 2 — bank

```
[ ] Pomiar napięcia spoczynkowego każdego z SIEDMIU pakietów osobno
    (rozrzut > 0,2 V = pakiet do odrzucenia)
[ ] Pomiar rezystancji wewnętrznej każdego pakietu mostkiem, jeśli masz czym
    (rozrzut ±10 % daje ~13 % rozrzutu prądów — więcej niż cała geometria
     połączeń, §4.3)
[ ] Doładowanie wszystkich pakietów do tego samego napięcia PRZED łączeniem
    (prąd wyrównawczy przy ΔU 0,20 V to kilka amperów — wielokrotność
     ~0,7 A, którym pakiet pracuje normalnie)
[ ] Kapturki na wszystkich 14 biegunach
[ ] Bezpiecznik 10 A na „+" każdego pakietu, 5–10 cm od zacisku — FB1…FB7
[ ] Odcinki pakiet → blok FLRY-B 2,5 mm², równa długość ±30 mm; nadmiar
    w pętlę serwisową, NIE przycięty
[ ] Bloki L+, L−, P+, P− z pokrywami; max 2 oczka na kołek
[ ] Łącznik L ↔ P 6 mm² OFC, obie żyły tej samej długości
[ ] Odbiór PO PRZEKĄTNEJ: „+" z bloku L+, „−" z bloku P− (§4.3).
    NIGDY oba bieguny z tego samego kosza
[ ] Pomiar napięcia banku po połączeniu — na L+/P− i na każdym pakiecie
    (różnica < 0,02 V po kilku minutach)
```

### Etap 3 — montaż w aucie, bez podłączenia do akumulatora

```
[ ] Przymiarka przed spawaniem wg ramki w §4.7: otwory przez słupki, nic nie
    wystaje do środka kosza (luz ~1 mm), uskok wieńca ~3 mm wyrównany,
    długość śrub przeliczona
[ ] Kosze przykręcone do grodzi 8 × M8 kl. 8.8 z DIN 985; podkładki DIN 9021
    i listwy 30 × 4 od strony kabiny, w koszu łeb niski (§4.7). PODŁOGA NIE WIERCONA
[ ] Przed wierceniem grodzi sprawdzone od strony kabiny, co jest za blachą
[ ] Pakiety stojąco, belki dociskowe dokręcone na gumie, belka nie dotyka
    zacisków ani nasuwek
[ ] Nad koszami nic szczelnego; przekaźniki i ładowarki obok koszy, nie nad nimi
[ ] Punkt masy przygotowany w bagażniku (goły metal, śruba, wazelina)
[ ] Wiązka do przodu przepięta, przelotki w blachach, RCA po drugiej stronie
[ ] Łącznik między koszami pod osłoną, mocowany co 15 cm
[ ] Rozłącznik masy banku w pozycji ROZWARTY
[ ] Wszystkie połączenia sprawdzone wizualnie i pociągnięciem
```

### Etap 4 — pierwsze załączenie

```
[ ] F1 20 A WYJĘTY
[ ] Podłączenie przewodu F1 do klemy „+" akumulatora rozruchowego
[ ] Rozłącznik masy banku ZWARTY
[ ] Pomiar: napięcie banku = napięcie szyny za LVD (silnik zgaszony)
[ ] Pomiar prądu spoczynkowego logiki → oczekiwane ~60 mA + LVD + I_jał
    z Etapu 1 (rozbieżność > 100 mA = szukaj upływu, NIE jedź dalej)
[ ] Włożenie F1 — obserwuj, czy nic nie iskrzy/grzeje; przy zgaszonym
    silniku i wyjętym kluczyku oba XY-SK120 ciemne
```

### Etap 5 — silnik i ładowanie

```
[ ] Uruchomienie silnika
[ ] Pomiar: napięcie na akumulatorze rozruchowym (13,8–14,5 V)
[ ] K1 zwarty, oba XY-SK120 świecą i są w CC (ok. 5,0 A każdy)
[ ] Prąd na przewodzie ładowania przy F12 ≈ 10 A, na odbiorze F7 ≈ 4–6 A —
    różnica to prąd netto do banku (≈ 5 A)
[ ] Prąd wejściowy toru (cęgi przy F1) ≈ 12 A
[ ] Wkładki FC1, FC2 (7,5 A) i FK (1 A) na miejscu; po 30 min oprawki FC
    letnie, nie gorące
[ ] Napięcie banku rośnie, nie przekracza nastawy CV (14,40 V)
[ ] Po 30 min: temperatura pakietów ręką — letnie, nie gorące;
    radiatory XY-SK120 i zaciski XH-M603 bez przegrzania
[ ] Zgaszenie silnika → K1 rozwiera, oba moduły i oba XH-M603 gasną
[ ] Pomiar: prąd z banku w stronę ładowarek < 1 mA (amperomierz przy F12)
[ ] Kluczyk na ON bez silnika: przy cewce z D+ albo z LVP 12,8 V moduły
    NIE ładują (§5.4); przy samym LVP sprawdź też ok. 10 min po jeździe
[ ] Pod koniec absorpcji (prąd banku < 2 A): prąd każdej gałęzi (cęgi albo
    bocznik przy FC1 i FC2) — żaden NIE może być ujemny (§5.3). Jeśli jest:
    jeden moduł w CV, drugi z CV o 0,1 V niżej, albo dioda w każdej gałęzi
    jak w §6.4
```

### Etap 6 — komputer i sterowanie zapłonem

```
[ ] M910q zasilany stale — na wtyku 19,8–20,5 V bez obciążenia (jak §3.4),
    niezależnie od kluczyka
[ ] Przekręcenie kluczyka → Arduino daje impuls, M910q startuje,
    dashboard pojawia się na wyświetlaczu głównym
[ ] Rozruch silnika przy działającym BCM → komputer NIE resetuje się
    (to jest test, dla którego cały ten bufor powstał)
[ ] Pod obciążeniem (Android Auto + wideo) na wtyku ≥ 19,5 V
[ ] Wyłączenie zapłonu → Arduino daje impuls, M910q schodzi do S3
[ ] Pomiar poboru w S3 — oczekiwane 200–460 mA + I_jał z Etapu 1 (§2.1,
    + telefon, jeśli jest)
[ ] Po 2 h → impuls 5 s, maszyna gaśnie, pobór spada do 50–150 mA + I_jał
    (§2.1)
[ ] Domena A dalej działa — test pilota 433 MHz i BLE bagażnika
```

### Etap 7 — próba postoju

```
[ ] Auto zaparkowane na 48 h bez uruchamiania
[ ] Pomiar napięcia banku przed i po
[ ] Spadek zgodny z pomiarem z Etapu 6 (w S3 przy 300 mA to 14,4 Ah przez 48 h,
    czyli 40 % DoD z 35,7 Ah — próba mieści się pod 50 % DoD. To nadal
    zejście poniżej rutynowego reżimu 30 % DoD, do którego przy 300 mA
    starcza 35,7 h)
[ ] Akumulator rozruchowy bez zmian — auto odpala normalnie
```

---

## 12. Serwis i kontrola okresowa

| Częstotliwość | Czynność | Kryterium |
|---------------|----------|-----------|
| Co miesiąc | Napięcie banku po nocy postoju | > 12,4 V |
| Co 3 miesiące | Napięcie każdego z **siedmiu** pakietów osobno | rozrzut < 0,2 V |
| Co 3 miesiące | **14 nasuwek** (pociągnięcie), nakrętki na **4 blokach**, śruby belek dociskowych i kotwiące M8 | bez luzu, bez śladów grzania |
| Co 6 miesięcy | Napięcie ładowania przy pracującym silniku, na zaciskach banku, **pod koniec absorpcji (prąd < 1 A)** | = nastawa CV (14,40 / 13,95 / 13,40 V) ± 0,05 V |
| Co 6 miesięcy | Prąd CC obu XY-SK120 | 5,0 A ± 0,2 A każdy |
| Co 6 miesięcy | Prąd spoczynkowy logiki | ~60 mA ± 20 % (+ LVD + I_jał, jeśli mierzysz całą szynę) |
| Co 12 miesięcy | Test pojemności banku (rozładowanie kontrolowane) | > 70 % znamionowej, czyli **> 25,0 Ah** |
| Co 12 miesięcy | Kontrola przewodów: przetarcia (łącznik pod osłoną!), korozja konektorów | bez zmian |
| Przed latem / zimą | Przestawienie CV (§5.5) | lato 13,95 V (długie trasy 13,40 V) / zima 14,40 V |

**Objawy zużycia banku:** szybszy spadek napięcia na postoju, dłuższa faza
CC przy ładowaniu, wybrzuszona obudowa pakietu (natychmiastowa wymiana),
grzanie się pojedynczego pakietu przy ładowaniu.

Żywotność katalogowa HR1221W w pracy buforowej to **3–5 lat przy 25 °C**,
i to temperatura montażu decyduje, gdzie w tym przedziale wylądujesz (§4.6) —
w bagażniku licz 1,5–3 lata. Przy przeładowywaniu albo braku sezonowej
korekty CV — **1–2 sezony**.

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
  CSB podaje **2,1 A na pakiet**, czyli 14,7 A dla siedmiu. Obowiązujące
  ładowanie to **2 × 5 A z dwóch XY-SK120**, netto do banku ≈ 5 A
  (§5.3) — 34 % sufitu katalogowego.

Brakuje tam też kompensacji temperaturowej, która dla tej serii ma **dwa różne
współczynniki** (−18 mV/°C float, −30 mV/°C cykl) — patrz §4.5.

### 13.2 Buck jako ładowarka

Ta sama starsza dokumentacja proponowała moduł buck XL4016 między diodą a bankiem.
Topologia buck nie jest w stanie osiągnąć napięcia absorpcji — patrz §5.1.
Użyj ładowania z §5.

### 13.3 Czas postoju „17 dni"

Liczba pochodzi z pełnego rozładowania, mimo adnotacji o 50 % DoD.
Poprawione wartości w §9.2.

### 13.4 Moduł `battery` nie monitoruje banku buforowego

> **Stan obecny (przygotowane, domyślnie wyłączone).** Wszystkie trzy kroki
> z listy niżej są już w repozytorium:
>
> - firmware: `arduino/sensor_hub/sensor_hub.ino` ma przełączniki
>   `FEATURE_BATT_ADC` (dzielnik 100k/27k na A6, samo napięcie) i
>   `FEATURE_BATT_INA226` (I2C na A4/A5 + bocznik, napięcie **i** prąd);
>   oba są zakomentowane, CI kompiluje każdy osobno
>   (`make -C arduino sensor_hub-variants`);
> - format linii: **`BATT:<mV>[,<mA>]`**, np. `BATT:12650,-3400` = 12,65 V,
>   3,4 A rozładowania (prąd dodatni = ładowanie); bez INA226 samo
>   `BATT:12650`. Parser w `src/input/arduino_serial.py` przyjmuje też
>   starszą postać z punktu 2 (`BATT:12.65`), ale wolty **tylko z kropką
>   dziesiętną** — liczba całkowita to zawsze miliwolty, więc linia ucięta
>   przez zakłócenie (`BATT:12` zamiast `BATT:12650`) daje 0,012 V i jest
>   odrzucana, a nie czytana jako zdrowe 12 V. Odczyty spoza 5–20 V albo
>   ±100 A też odrzuca. Publikuje `arduino.battery_voltage` [V]
>   i `arduino.battery_current` [A];
> - `src/power/battery.py` (`BatteryMonitor`) ma progi AGM z tabeli niżej
>   w bloku `battery:` configu (z histerezą 0,1 V, wykrywaniem ładowania
>   powyżej 13,2 V albo 0,2 A i medianą z 5 odczytów) i publikuje
>   `battery.state` = charging | full | ok | low | critical | unknown.
>   Niczego nie wyłącza — to robi sprzętowe LVD.
>
> **Włączenie** — trzy kroki:
>
> 1. Firmware z pomiarem, **flagą przy kompilacji**, bez edycji sketcha:
>
>    ```bash
>    make -C arduino sensor_hub-upload PORT=/dev/ttyUSB1 SENSOR_HUB_FEATURES=BATT_ADC
>    # albo z INA226 (napięcie i prąd):
>    make -C arduino sensor_hub-upload PORT=/dev/ttyUSB1 SENSOR_HUB_FEATURES=BATT_INA226
>    ```
>
>    **Nie odkomentowuj** `#define FEATURE_BATT_…` w sketchu: przełączniki
>    BATT muszą zostać zakomentowane (sprawdzają to testy, CI kompiluje
>    każdy wariant osobno flagą `-D`), a flaga z `SENSOR_HUB_FEATURES`
>    robi dokładnie to samo. Makefile przyjmuje tylko nazwy przełączników
>    zakomentowanych w sketchu — literówka (`BAT_ADC`) kończy się błędem,
>    a nie cichym firmware bez pomiaru. Sama kompilacja, bez płytki:
>    `make -C arduino sensor_hub SENSOR_HUB_FEATURES=BATT_ADC`.
> 2. Port sensor huba w `arduino.sensor_hub_port` (stała nazwa: szablon
>    `config/udev/99-bcm-sensor-hub.rules`).
> 3. `modules.battery: true` (w `config/local.yaml`).
>
> **Kalibracja** (raz, po montażu; BCM zatrzymany, bo trzyma port):
>
> - `picocom -b 115200 /dev/ttyUSB1` — linia `BATT:` co 2 s. Napięcie
>   ma stać w miejscu: silnik wyłączony od kilku minut (przy ładowaniu
>   pływa i odczyt multimetru nie zgra się w czasie z `BATT:`).
> - **`FEATURE_BATT_ADC`:** zmierz multimetrem napięcie na zaciskach banku
>   i porównaj z `BATT:`. Firmware już mnoży odczyt przez `BATT_ADC_CAL`,
>   więc nową wartość liczy się **od obecnej**:
>   `nowe BATT_ADC_CAL = obecne BATT_ADC_CAL × U_multimetr / U_BATT`.
>   Np. przy domyślnym 1.000: multimetr 12,71 V, `BATT:12560` →
>   1,000 × 12,71 / 12,56 = **1.012**. Gdyby kolejny pomiar (np. po
>   wymianie rezystora) dał multimetr 12,60 V przy `BATT:12650`, to
>   1,012 × 12,60 / 12,65 = **1.008** — samo `U_multimetr / U_BATT`
>   (0,996) skasowałoby pierwszą korektę. Wpisz wynik
>   w linię `#define BATT_ADC_CAL` w `sensor_hub.ino` (to jedyna wartość
>   w sketchu, którą zmienia się pod konkretną płytkę — referencją ADC jest
>   VCC z MP1584, a rezystory mają tolerancję), wgraj ponownie poleceniem
>   z kroku 1 i sprawdź jeszcze raz; różnica powinna zejść poniżej
>   ~0,05 V. Lokalna zmiana sketcha może zablokować `git pull` (gdy sketch
>   zmieni się też w repo) — przed aktualizacją `git stash`, po niej
>   `git stash pop`.
> - **`FEATURE_BATT_INA226`:** napięcie mierzy sam układ (bez dzielnika),
>   kalibruje się **znak prądu**. Przy pracującym silniku (ładowarka
>   ładuje) `BATT:<mV>,<mA>` musi mieć prąd **dodatni**, na postoju
>   z włączonym komputerem — ujemny. Jeśli jest odwrotnie, najprościej
>   ustawić `battery.current_sign: -1` w `config/local.yaml` (bez
>   ponownego wgrywania); alternatywnie zamienić przewody IN+/IN- albo
>   `BATT_INA_SIGN -1` w sketchu. Wartość bezwzględną prądu porównaj
>   z miernikiem cęgowym DC, jeśli jest pod ręką: rozjazd oznacza inny
>   bocznik niż 20 A / 75 mV (`BATT_SHUNT_MOHM`).
>
> Opis poniżej zostaje jako zapis tego, skąd te zmiany się wzięły.

`src/power/battery.py` był napisany pod **ogniwo Li-ion 18650**:

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
   `BATT:<napięcie>`, mapowana na `arduino.battery_voltage`. (Firmware
   wysyła ostatecznie miliwolty i opcjonalnie prąd: `BATT:<mV>[,<mA>]`;
   parser przyjmuje obie postacie — patrz ramka wyżej.)
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
z listy zalecanych zakupów (poz. 25).

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

Dokumenty HTML (`x86-production/*.html`, `bcm_v85_docs.html`) są już
poprawione do gotowego wzmacniacza; wariant DIY został w nich tylko
w szarych blokach „Historyczne (nieaktualne)”.

### 13.6 Ograniczenia wynikające z wybranych modułów

Tani moduł to zawsze kompromis. Przy tym układzie realne ograniczenia są
**cztery**:

| Moduł | Ograniczenie | Konsekwencja |
|-------|--------------|--------------|
| **Przetwornica step-up 20 V** (bezmarkowa, zalewana) | brak karty katalogowej; sprawność 90–93 % i 200 W to deklaracje sprzedawcy | każdą sztukę sprawdzasz po zakupie (§3.4); zapas wobec 65 W jest duży nawet przy słabszej sztuce (§3.2) |
| **XY-SK120** | brak potwierdzonej funkcji końca ładowania i float, brak wejścia NTC, brak izolacji, sprawność nieznana (przyjęte 88 %) | CV wybierasz świadomie i przestawiasz sezonowo (§5.5); masa w jednym punkcie (§5.6); temperatura do zmierzenia (§5.2) |
| **XH-M609** | pobór własny do 125 mA wg spec + zakres zasilania od 12 V | wchodzi wprost w budżet postoju (§9) i wymaga sprawdzenia pracy przy progu 11 V (§7.3) |
| **XH-M603** | realna obciążalność płytki ok. **8–10 A** (oględziny), brak wolnego styku | jeden moduł nie przeniesie 10 A — stąd **dwa**, po jednym na ładowarkę (§6.3) |

Żadne z nich nie dyskwalifikuje modułu. XL6019 z poprzedniego wydania był
ograniczeniem twardym (ok. 45 W i obowiązkowy limit RAPL) — dlatego został
zastąpiony (§3).

### 13.7 Decyzje otwarte

Rzeczy, których ta dokumentacja **nie rozstrzyga sama** — wymagają pomiaru
albo decyzji właściciela.

| # | Sprawa | Dlaczego otwarta | Gdzie |
|---|--------|------------------|-------|
| 1 | **Grodź za kanapą: grubość, nośność, co jest za blachą** | Repozytorium tego nie zawiera; PDF koszy zakłada mocowanie przez grodź. Obejrzyj od strony kabiny przed wierceniem, dołóż listwy pod dolny rząd, jeśli blacha się ugina | §4.7 |
| 2 | **Kryterium wytrzymałościowe** | 3,3 kN przy 20 g to wymaganie, nie wynik normy; 16,8 kg tuż za oparciem kanapy jest istotne dla bezpieczeństwa pasażerów | §4.7 |
| 2a | **Geometria koszy z PDF-u (otwory, luz, uskok wieńca)** | Wnioski z wymiarów w tekście PDF-u, bez rysunków 3D: otwory 20 mm od boków trafiają w słupki KL-4/KP-4, z tyłu ~1 mm luzu na łby i podkładki, tylny płaskownik wieńca ~3 mm poza płaszczyzną dolnego kątownika. Sprawdź na wyciętych elementach przed spawaniem | §4.7, §11 Etap 3 |
| 3 | **Sprawność i temperatura XY-SK120 przy 5 A** | Producent nie podaje sprawności; przyjęte 88 % daje ~10 W strat na moduł. Od tego zależą prąd z rozruchowego (F1) i czy 5 A jest „zimne" | §5.2, §6.3 |
| 4 | **Funkcje końca ładowania w Twojej wersji XY-SK120 i jej dane** | W dostępnych materiałach nie znaleźliśmy prądu końca ładowania; OAH/OHP niepotwierdzone. Wejście 6–36 V i 6 A / 120 W pochodzą z opisów sprzedażowych — pełnej instrukcji nie udało się otworzyć. Jeśli funkcje są — opisz, co robią po osiągnięciu limitu | §5.2, §5.5 |

| 5 | **LVP modułów a wolne obroty** | Próg 12,8 V ma odcinać ładowanie z niepracującego rozruchowego; na wolnych obrotach z obciążeniem instalacji trzeba sprawdzić, czy moduły nie klapkują | §5.4 |
| 6 | **Przepływ wsteczny przez XY-SK120 i zasilanie XH-M603** | Schematu modułu brak; barierą są K1 i rozwarte bez zasilania XH-M603. To, że XH-M603 nie zasila się od strony banku (OUT), jest przyjęciem — test §6.4 pkt 6 na stole, potem prąd < 1 mA przy zgaszonym silniku w aucie | §5.4, §6.4, §11 Etap 1, Etap 5 |
| 7 | **Obciążalność płytki XH-M603 (~8–10 A)** | Liczba z oględzin, nie z karty; przy 5 A na moduł zapas jest, ale zmierz temperaturę zacisków | §6.3 |
| 8 | **Dostępność wkładek MIDI/ANL 15–20 A (F1, F7, F12)** | Typoszeregi tej klasy często zaczynają się od ok. 30 A; dla F1 30 A nadal chroni 6 mm², tylko zmniejsza zapas nad 11,9–13,0 A poboru ładowarek; zdolności wyłączania (ATO ~1 kA, MIDI/AMI ≥ 2 kA, ANL ≥ 2,7 kA @ 32 V DC) pochodzą z typowych kart, nie z repozytorium | §7.4, §8.1 |
| 9 | **Pobór własny XH-M609 — wciąż niezmierzony** | Przy 185 mA łącznie nawet 35,7 Ah daje tylko 4,0 dnia do 50 % DoD | §7.3, §9.2 |
| 10 | **Pobór telefonu na buforze** | 30–100 mA naładowany to szacunek; telefon, który się doładowuje, bierze do ~0,9 A. Zmierz w S3 i po wyłączeniu | §9.1 |
| 11 | **Obciążenie szyny podczas jazdy (≈ 5 A)** | Wyprowadzone z poboru odbiorników (§2.1), nie zmierzone. Czas ładowania jest odwrotnie proporcjonalny do prądu netto: przy 6 A obciążenia faza CC z progu LVD to 6,7 h zamiast 5,4 h | §2.1, §9.4 |
| 12 | **Zdolność łączeniowa chwilowa rozłącznika masy 100 A** | Typowe egzemplarze podają ~2500 A chwilowo, a prąd zwarciowy banku to ~2,2–2,6 kA. Rozłączaj wyłącznie bez obciążenia | §8.4 |
| 13 | **Wiek i pochodzenie pakietów** | Rozrzut rezystancji ±10 % daje ~13 % rozrzutu prądów — więcej niż cała geometria połączeń na lince. Zmierz rezystancję mostkiem, nie tylko napięcie spoczynkowe | §4.3, §11 Etap 2 |
| 14 | **Siedem czy osiem pakietów** | Kosze z PDF-u są na 4 + 3; ósmy pakiet wymagałby zmiany kosza prawego. Zapas jednego pakietu i tak nie pozwala wymienić kompletu (§4.2) | §4.2, §9.2 |
| 15 | **Skąd zasilać wyświetlacz 1,8" na ESP32** | Przy 35,7 Ah wariant „z szyny buforowanej" mieści się w budżecie (postój 5,3–3,0 zamiast 9,3–4,0 dnia), ale wymaga dopisania panelu do §9.1 i odgałęzienia w §8.2. Wariant „+15" jest prostszy, lecz kłóci się z §2 | [`WYSWIETLACZ_ESP32_1V8.md`](WYSWIETLACZ_ESP32_1V8.md) |
| 16 | **Rysunki i PNG — przerysowane 22.11.2026** | Wszystkie arkusze zasilania pokazują bieżący projekt i powstają z generatorów; PNG wyrenderowane na nowo (`render_png.py --check` → „aktualny”), mozaika miedzi do druku 600 dpi w `schematics/png/pcb_power_etch_600dpi.png`. Punkt zamknięty — zostaje dla ciągłości numeracji. Przy rozbieżności obowiązuje ten dokument | nagłówek, [`../schematics/README.md`](../schematics/README.md) |
| 17 | **Prąd jałowy przetwornicy step-up 20 V (I_jał)** | Zalewane moduły go nie podają, a przetwornica wisi na szynie w S3 i po wyłączeniu. Pomiary S3 i stanu wyłączonego z §2.1 pochodzą z poprzedniej przetwornicy XL6019 — nowy moduł dokłada nieznany prąd do każdego wiersza budżetu postoju | §3.4, §9.1, §9.2, §11 Etap 6 |

Dwie rzeczy, które trzeba wiedzieć o samych liczbach:

- **Brak współczynnika przyjęcia ładunku.** AGM wymaga oddania 105–115 %
  pobranych amperogodzin, więc wszystkie czasy ładowania z §9.4 są zaniżone
  o 5–15 %.
- **Brak krzywych rozładowania i danych Peukerta dla HR1221W.** Przy 5 A
  siedem pakietów pracuje z krotnością ok. C/7, czyli szybciej niż
  rozładowanie 20-godzinne, na którym oparta jest pojemność 5,1 Ah. Czas pracy
  przy zgaszonym silniku z §2.1 jest przez to optymistyczny, ale skali korekty
  nie da się policzyć bez tych krzywych.

---

## 14. Wybudzanie z zewnątrz: drzwi, telefon (IR), wejście EXT

> **Tylko wersja z buforem.** W aucie testowym bez bufora komputer na postoju
> nie śpi, tylko traci prąd — nie ma czego budzić. Kod jest gotowy, ale
> wszystko jest **domyślnie wyłączone**: flagi `FEATURE_WAKE_*` w firmware
> są zakomentowane, `modules.remote_session` jest `false` w kodzie i w obu
> configach, a przełącznik w agencie telefonu przychodzi z BCM. Włączaj
> dopiero po montażu bufora i Nano #2 oraz po sprawdzeniu na stole dekodera
> diody zasilania (§14.8, krok 1).

### 14.1 Jak to działa

M910q w S3 odcina zasilanie portów USB (§2.1), więc ani telefon, ani
klawiatura, ani „Wake on USB” go nie obudzą. Jedyna droga, która działa
i z S3, i z wyłączenia: **Nano #2 naciska przycisk zasilania** — ten sam
przekaźnik na A0 co przy zapłonie. Każdy wyzwalacz to tylko **prośba** do
Nano; o naciśnięciu decyduje firmware (`arduino/sensor_hub/wake_logic.h`),
a samo naciśnięcie robi zawsze ta sama logika co przy zapłonie
(`power_logic.h`: stan z diody, cisza po impulsie, okno usypiania, limit
impulsów).

| Wyzwalacz | Flaga | Wejście | Dzierżawa |
|-----------|-------|---------|-----------|
| Otwarcie drzwi kierowcy | `FEATURE_WAKE_DOOR` | D2 (krańcówka FL, `FEATURE_DOORS`) | 5 min |
| Podczerwień z telefonu w aucie | `FEATURE_WAKE_IR` | A3 (odbiornik TSOP) | 10 min |
| Impuls zewnętrzny ≥ 50 ms | `FEATURE_WAKE_EXT` | A2 (transoptor PC817) | 10 min |

Prośba przechodzi **tylko**, gdy:

- zapłon jest potwierdzony jako wyłączony (przy włączonym prośby nie ma
  wcale — otwieranie drzwi w trasie nic nie robi);
- komputer jest **stabilnie** w S3 albo wyłączony (stan z diody, bez
  trwającego impulsu i okna usypiania) — inaczej `WAKE_DENIED:STATE`;
- drzwi: **pierwsze otwarcie drzwi kierowcy po jeździe to wysiadanie** —
  nie budzi komputera i nie jest odmową, także gdy kierowca posiedział po
  zgaszeniu dłużej (np. kończył rozmowę). Jeśli przez 30 min po zgaszeniu
  nikt nie otworzył drzwi kierowcy (wysiadł drzwiami pasażera), następne
  otwarcie jest już powrotem i budzi. Każde kolejne otwarcie nie wcześniej
  niż **2 min po zgaszeniu zapłonu** — inaczej `WAKE_DENIED:HOLDOFF`. Po
  zaniku zasilania Nano (świeży start) nie wiadomo, czy ktoś siedzi
  w aucie, więc liczy się tylko blokada 2 min od startu;
- limit: **3 pobudki na godzinę, 6 na dobę** — `WAKE_DENIED:RATE`;
- z pomiarem banku (`FEATURE_BATT_ADC` albo `FEATURE_BATT_INA226`, §13.4):
  świeży odczyt **powyżej 12,2 V**; brak odczytu też jest odmową
  (`WAKE_DENIED:LOWBATT`). **Bez `FEATURE_BATT_*` tego warunku nie ma czym
  sprawdzić i jest pomijany** — dlatego CI kompiluje wybudzanie razem
  z oboma wariantami pomiaru.

**Dzierżawa.** Przyjęta pobudka daje komputerowi 5 min (drzwi) albo 10 min
(IR, EXT). Kolejna prośba w trakcie ją przedłuża (bez naciskania i bez
liczenia do limitu), BCM może ją przedłużyć poleceniem `HOLD:<min>` albo
zakończyć `RELEASE`. Po jej końcu, przy wyłączonym zapłonie, Nano naciska
SHORT — komputer wraca do S3 zwykłą drogą (acpid → `bcm-power-toggle.sh`:
zatrzymanie BCM, uśpienie). Zapłon kasuje dzierżawę bez naciskania. Cała
sesja trwa najwyżej **90 min** od pobudki, nawet gdy BCM bez końca wysyła
`HOLD`. Eskalacja do OFF zostaje jak była: 2 h od pobudki i **LONG tylko na
maszynę stabilnie uśpioną**, nigdy na pracującą.

**Reset Nano nie gubi pobudki.** Nano z CH340 resetuje się przy każdym
otwarciu portu (linia DTR), a BCM otwiera port zaraz po każdej pobudce —
startuje przecież dopiero po wybudzeniu. Stan pobudek (dzierżawa, limity,
blokada drzwi, licznik odmów) leży więc w RAM w sekcji `.noinit`
(przeżywa reset, nie przeżywa zaniku zasilania) z sumą kontrolną; po
resecie zegar budzenia ciągnie dalej. Z tego samego powodu Nano powtarza
`WAKE:` i `LEASE:` co 2 s w pełnym stanie — BCM, który właśnie wstał,
dowiaduje się o pobudce najpóźniej po 2 s.

### 14.2 Okablowanie

**Odbiornik IR na A3** (TSOP38238, TSOP4838 albo VS1838B — nośna 38 kHz,
ok. 0,4 mA):

```
5 V Nano ──[100 Ω]──┬── VS (zasilanie TSOP)
                    │
                  [4,7 µF] (+ 100 nF ceramiczny równolegle, tuż przy TSOP)
                    │
GND Nano ───────────┴── GND TSOP
A3 Nano ────────────── OUT TSOP   (LOW = nośna; pull-up jest w TSOP)
```

- Filtr RC 100 Ω / 4,7 µF jest **obowiązkowy**: zasilanie Nano z MP1584
  i przekaźnik niosą zakłócenia, a TSOP reaguje na nie fałszywymi impulsami.
- Przewód 3-żyłowy w wiązce kabla USB telefonu, do Nano #2. Odbiornik
  montuje się **między górną krawędzią telefonu a szybą**
  (`docs/PRZYGOTOWANIE_TELEFONU.md` §18): 5–10 cm od diody IR telefonu, soczewką do tyłu — na
  diodę, nie w słońce — pod małą czarną osłonką, poza polem widzenia
  kierowcy i kamery za lusterkiem. TSOP-y wytrzymują ok. 85 °C; latem
  sprawdź temperaturę pod podsufitką.
- A3 jest wolny przy `FEATURE_PWRBTN`. Z `FEATURE_PARK` (A0–A3 to ECHO
  czujników HC-SR04) kompilacja kończy się błędem `#error`.
- Przerwanie zmiany stanu A3 to wektor `PCINT1`; nie dodawaj do sketcha
  biblioteki SoftwareSerial (zajmuje wszystkie wektory PCINT).

**Wejście EXT na A2** (PC817, np. impuls „odblokuj” centralnego zamka albo
w przyszłości płytka BLE):

```
sygnał 12 V ──[1,5 kΩ]──► anoda LED PC817 ──► katoda ── masa auta
                 (1N4148 antyrównolegle do LED — ochrona przed odwrotną polaryzacją)
A2 Nano ◄──── kolektor PC817, emiter ── GND Nano   (INPUT_PULLUP; LOW = aktywny)
```

- Impuls musi trwać **co najmniej 50 ms** (krótszy jest odrzucany jako
  zakłócenie). Prośbą jest początek impulsu, nie jego trwanie.
- Okablowania „odblokuj” w Alfie 156 **nie sprawdzono** — przed podpięciem
  zmierz przebieg miernikiem albo oscyloskopem.

**Drzwi na D2** — ta sama krańcówka drzwi kierowcy co dla `DOOR:` (masa przy
otwartych, `INPUT_PULLUP`). Auto z kierownicą po prawej: w sketchu
`WAKE_DOOR_INDEX 1` (FR, D3).

### 14.3 Firmware: flagi i wgranie

Flagi tylko przez `SENSOR_HUB_FEATURES` (repo zostaje czyste), np. pomiar
banku INA226 i pobudka podczerwienią oraz drzwiami:

```bash
make -C arduino sensor_hub-upload PORT=/dev/ttyUSB0 SENSOR_HUB_FEATURES="BATT_INA226 WAKE_IR WAKE_DOOR"
```

- Każda `WAKE_*` wymaga `FEATURE_PWRLED` (domyślnie włączony; bez diody
  firmware nie wie, czy komputer śpi), `WAKE_DOOR` — także `FEATURE_DOORS`.
  Złe zestawienie kończy kompilację błędem `#error`.
- **Kod IR** (prywatny adres NEC 16-bitowy i polecenie): domyślne
  `WAKE_IR_ADDRESS 0x7A15` i `WAKE_IR_COMMAND 0x56` z
  `arduino/sensor_hub/wake_logic.h` są publiczne (każdy, kto czyta repo,
  je zna) — BCM ostrzega w logu i w wierszu „Wybudzanie”, dopóki ich nie
  zmienisz. Własne podaj przy `make`, **bez edycji** śledzonego
  `wake_logic.h` (inaczej trafią do gita przy następnym commicie); make
  przyjmuje tylko `0x` i cyfry szesnastkowe, zakres (adres do `0xFFFF`,
  polecenie do `0xFF`) sprawdza `#error` w `wake_logic.h`:

  ```bash
  make -C arduino sensor_hub-upload PORT=/dev/ttyUSB0 SENSOR_HUB_FEATURES="BATT_INA226 WAKE_IR WAKE_DOOR" WAKE_IR_ADDRESS=0x1B2C WAKE_IR_COMMAND=0x3D
  ```

  (`0x1B2C` / `0x3D` to tylko przykład — wybierz własne). **Te same**
  wartości wpisz w `config/local.yaml` (`power.remote_session.ir_address`
  i `ir_command`, §14.5) — telefon dostaje je od BCM.
- Testy logiki na PC (reguły, dzierżawa, limity, przepełnienie `millis()`
  i `micros()`, reset `.noinit`, dekoder NEC, czytnik linii):

  ```bash
  make -C arduino sensor_hub-test
  ```

- CI kompiluje warianty `WAKE_DOOR`, `WAKE_EXT`, `WAKE_IR` i zestawy
  z `BATT_ADC` / `BATT_INA226` (`make -C arduino sensor_hub-variants`).
  Za duży program arduino-cli odrzuca sam; RAM (Nano ma 2048 B, resztę
  zajmuje stos) pilnuje ten cel: zmienne globalne wariantu ponad
  `SENSOR_HUB_RAM_MAX` (domyślnie 1536 B = 75 %) kończą kompilację błędem.
  Własny zestaw flag sprawdzisz tak samo:

  ```bash
  make -C arduino sensor_hub-variants SENSOR_HUB_VARIANTS="WAKE_IR+WAKE_DOOR+BATT_INA226"
  ```

### 14.4 Protokół Nano ↔ BCM

Nano → BCM (115200 baud, linie zakończone `\n`):

| Linia | Kiedy | Znaczenie |
|-------|-------|-----------|
| `WAKE:IR` / `WAKE:DOOR` / `WAKE:EXT` | przy przyjęciu prośby i co 2 s w trakcie dzierżawy | pobudka (albo przedłużenie) z tego źródła |
| `WAKE_DENIED:RATE` / `LOWBATT` / `HOLDOFF` / `STATE` | przy odmowie | powód odmowy |
| `LEASE:<s>` | co 2 s i przy każdej zmianie | ile sekund dzierżawy zostało (0 = brak) |
| `WAKESTAT:<n>,<powód>` | co 2 s | odmowy od zaniku zasilania Nano i ostatnia (`NONE` = żadnej) |

BCM → Nano — **jedyne dwie linie, jakie Nano przyjmuje** (czytnik linii
najwyżej 16 znaków; dłuższa linia albo znak spoza ASCII jest w całości
odrzucana; bez `FEATURE_WAKE_*` sketch nie czyta portu wcale):

| Linia | Skutek | Odpowiedź |
|-------|--------|-----------|
| `HOLD:<min>` (1–60, bez zer wiodących) | dzierżawa co najmniej `<min>` minut od teraz, w granicach 90 min sesji; bez dzierżawy nic | `LEASE:<s>` |
| `RELEASE` | koniec dzierżawy teraz → SHORT na pracujący komputer | `LEASE:0` |

Żadna linia z hosta nie naciska przycisku bezpośrednio: `HOLD` tylko
przedłuża istniejącą dzierżawę, `RELEASE` ją kończy.

Reset Nano (każde otwarcie portu przez BCM ustawia DTR) zaczyna od nowa
odczyt zapłonu — przez ~2 s Nano nie wie, czy zapłon jest wyłączony. Gdy
w tym oknie przyjdzie `RELEASE` albo minie dzierżawa, Nano odpowiada od
razu `LEASE:0`, ale SHORT naciska dopiero po potwierdzeniu zapłonu
(wyłączony → S3; włączony → dzierżawa znika bez naciskania). `HOLD` w tym
oknie nie wskrzesza zakończonej dzierżawy.

### 14.5 BCM: moduł `remote_session`

`src/power/remote_session.py`, przełącznik `modules.remote_session`
(wymaga `input`, który czyta port sensor_hub). BCM:

- pokazuje **baner** na każdym ekranie (także na Android Auto), nie
  modalny, u dołu nad paskiem nawigacji (pasek i przeciągnięcie od dolnej
  krawędzi działają dalej): „Wybudzono: telefon — uśpienie za mm:ss [Nie
  usypiaj 30 min] [Uśpij teraz]”. Przyciski działają tylko na ekranie w aucie
  (trasy `/api/remote_session/hold` i `/sleep` przyjmują wyłącznie
  loopback, także przy `remote_access: full`);
- „Nie usypiaj” = `HOLD:<hold_step_min>`; razem najwyżej
  `hold_max_min` minut przedłużeń w jednej sesji;
- po `idle_suspend_min` bez użycia wysyła `RELEASE` wcześniej — dzierżawa
  Nano i tak jest twardą granicą. Użycie to: dotyk ekranu w aucie (każdy
  ekran BCM i Android Auto; liczy się tylko kiosk na tym komputerze, nie
  telefon w sieci auta), klawisz przez `/ws/input`, przycisk na kierownicy,
  stuknięcie w baner, połączenie lub rozłączenie Android Auto, kolejna
  prośba przy aucie, koniec rozmowy i koniec muzyki. **Rozmowa** i **grająca
  muzyka z telefonu** (`bt.media_playing`) wstrzymują odliczanie na cały
  czas trwania — samo połączenie telefonu przez Bluetooth już nie (główny
  telefon zwykle jest połączony). Gdy bezczynność skończyłaby sesję przed
  dzierżawą (czyli po „Nie usypiaj”), baner odlicza do niej z dopiskiem
  „(bez użycia)”, więc kierowca widzi, kiedy komputer naprawdę zaśnie;
- **rozmowa telefoniczna** w trakcie sesji nie jest przerywana: 90 s przed
  końcem dzierżawy BCM sam wysyła ten sam `HOLD` (z tego samego budżetu);
- wiersz „Wybudzanie” w Ustawieniach: ostatnia pobudka (źródło, godzina),
  liczba odmów Nano i ostatni powód, brak połączenia z Nano;
- **nigdy sam nie usypia komputera** — tylko prosi Nano (`RELEASE`), więc
  do S3 prowadzi jedna droga, ta sama co przy zapłonie.
  `ignition_watcher` zostaje nieruszony: jego naprawa włączyłaby drugą,
  konkurencyjną ścieżkę usypiania.

Włączenie (`config/local.yaml`, BCM zatrzymany; minuty 1–60):

```yaml
modules:
  remote_session: true
power:
  remote_session:
    idle_suspend_min: 10
    hold_step_min: 30
    hold_max_min: 60
    ir_address: 0x7A15     # domyślne z repo — wpisz WŁASNE, te same co
    ir_command: 0x56       # WAKE_IR_ADDRESS / WAKE_IR_COMMAND przy make (§14.3)
```

### 14.6 Telefon w aucie jako pilot IR

Redmi Note 8 Pro ma nadajnik IR. Agent w Termuxie (`bcm_agent.py` ≥ 1.4.0,
nagłówek pliku: „Budzenie komputera w aucie”) nadaje kod z §14.3:

- **SMS `WAKE <kod>`** z numeru z białej listy alarmu na postoju, z kodem
  TOTP z aplikacji „authenticator” (ten sam sekret co `PARK OFF`; tworzy
  go `python ~/bcm_agent/bcm_agent.py --park-setup`,
  `PRZYGOTOWANIE_TELEFONU.md` §12). Skrzynka jest czytana także przy
  wyłączonym alarmie na postoju (wtedy działa tylko `WAKE`). **Biała lista
  przy wyłączonym alarmie:** BCM wysyła `park_numbers` tylko z
  `modules.parking_guard: true` — bez alarmu ustaw numery w samym
  telefonie: `python ~/bcm_agent/bcm_agent.py --park-numbers '+48…'`.
  Bez numerów agent nie czyta skrzynki i raz zapisuje w logu
  `PARK: no numbers for SMS commands (WAKE)`. Odpowiedź:
  `ALFA 156: BUDZENIE wyslane` albo powód odmowy; gdy BCM milczał przed
  budzeniem i w ciągu 10 min przyjdzie od niego pierwsze podpisane żądanie
  (komputer wstał, forward agenta działa), ten sam numer dostaje drugą
  odpowiedź `ALFA 156: komputer obudzony - BCM odpowiada` (agent ≥ 1.5.0;
  raz na budzenie, w dziennym budżecie odpowiedzi). Brak jej po 10 min =
  komputer nie wstał albo nie doszedł do telefonu;
- **skrót Termux:Widget** `tools/car_phone/termux/wake.sh` (albo
  `python ~/bcm_agent/bcm_agent.py --wake`) — na telefonie w aucie, bez
  sieci i bez kodu. Instalacja (tylko wersja z buforem): aplikacja
  **Termux:Widget** z F-Droid — z tego samego źródła co Termux (inny
  podpis = nie zadziała, `PRZYGOTOWANIE_TELEFONU.md` §4); na M910q
  dołóż `wake.sh` do kopiowania z `PRZYGOTOWANIE_TELEFONU.md` §9.2:

  ```bash
  cd /opt/bcm && sudo env ADB_SERVER_SOCKET=localfilesystem:/run/bcm-adb/adb.sock adb push tools/car_phone/termux/wake.sh /sdcard/Download/
  ```

  potem w Termuxie:

  ```bash
  mkdir -p ~/.shortcuts
  ```

  ```bash
  cp ~/storage/downloads/wake.sh ~/.shortcuts/ && chmod 700 ~/.shortcuts/wake.sh
  ```

  i na ekranie głównym telefonu dodaj widżet Termux:Widget → „wake.sh”.
  Skrypt nie przyjmuje żadnych argumentów; wynik pokazuje dymkiem;
- limit w telefonie: 1 próba na minutę, 3 udane na godzinę, 6 na dobę
  (niezależnie od limitu Nano); jedno nadanie to 3 ramki NEC co 108 ms
  (`termux-infrared-transmit -f 38000 …`), Nano przyjmuje 2 identyczne
  w ciągu 1 s.

Warunki: przełącznik `remote_session` i kod IR telefon dostaje od BCM przez
`modules.car_phone_agent` — agent musi raz zsynchronizować konfigurację,
gdy BCM pracuje. Telefon musi być **zasilany z bufora**, niezależnie od
portu USB M910q (w S3 port jest martwy): wstrzykiwacz VBUS jak przy Nano #2
albo osobna ładowarka. Czy Termux:API widzi nadajnik:

```bash
termux-infrared-frequencies
```

(lista zakresów częstotliwości z 38000 w środku = działa).

### 14.7 BIOS i system

| Ustawienie | Wartość | Dlaczego |
|------------|---------|----------|
| After Power Loss | **Power On** | powrót prądu = start komputera |
| Tryb uśpienia | **S3** (`deep`) | patrz niżej; Modern Standby (s2idle) zostawia komputer „półprzytomny” i bez stabilnego migania diody |
| Wake on USB | **Disabled** | w S3 porty USB są martwe — zostają tylko fałszywe wybudzenia |
| Wake on LAN | **Disabled** | port Ethernet nie jest używany, a S5 i tak nie gwarantuje wybudzenia |

```bash
cat /sys/power/mem_sleep
```

Ma pokazać `[deep]` (w nawiasie). Jeśli nie — `docs/WDROZENIE_M910Q.md`
(`mem_sleep_default=deep`).

### 14.8 Sprawdzenie na stole (po kolei)

1. **Dekoder diody.** Bez stabilnego `PWR:SLEEP` w S3 żadna pobudka nie
   przejdzie (`WAKE_DENIED:STATE`) — `docs/WDROZENIE_TESTOWE.md` §3.1a.
2. **Linie co 2 s.** BCM zatrzymany, port otwarty `picocom -b 115200
   /dev/ttyBCM_SENSOR`: obok `PWR:` i `BATT:` są `LEASE:0` i `WAKESTAT:0,NONE`.
3. **Drzwi.** Zapłon włączony, potem zgaszony, komputer w S3. Otwórz
   i zamknij drzwi kierowcy (wysiadanie): cisza — ani `WAKE:`, ani
   `WAKE_DENIED:`. Otwórz je ponownie od razu: `WAKE_DENIED:HOLDOFF`.
   Odczekaj 2 min od zgaszenia i otwórz: `WAKE:DOOR`, `LEASE:300`,
   `PWRACT:SHORT`, komputer wstaje.
4. **IR.** Na telefonie skrót `wake.sh` (instalacja: §14.6) albo
   `bcm_agent.py --wake`: `WAKE:IR`. Bez reakcji: odległość i kąt diody do TSOP, osłonka, filtr RC.
5. **Reset przy otwarciu portu.** Po starcie BCM baner pokazuje pozostały
   czas (dzierżawa przeżyła reset Nano przez DTR). Jeśli baner się nie
   pojawia, a w porcie jest `LEASE:0` — bootloader nadpisał RAM: zgłoś to
   (wariant: kondensator 10 µF RESET–GND blokujący auto-reset; zdejmij go
   do wgrywania).
6. **Baner.** „Nie usypiaj 30 min” → w porcie `LEASE:` ok. 1800; „Uśpij
   teraz” → `LEASE:0`, `PWRACT:SHORT`, komputer zasypia.
7. **Limit.** Czwarta pobudka w godzinie: `WAKE_DENIED:RATE`; wiersz
   „Wybudzanie” w Ustawieniach pokazuje odmowę.

### 14.9 Bezpieczeństwo i ograniczenia

- **Kod IR nie jest uwierzytelniony** (NEC to zwykły pilot): ktoś z
  nadajnikiem IR i Twoim kodem obudzi komputer — nie otworzy auta i nie
  wyłączy alarmu na postoju (ten rozbraja tylko dowód właściciela). Limity
  3/h i 6/dobę ograniczają zużycie banku; zmień domyślny kod (§14.3 —
  BCM ostrzega, dopóki jest domyślny).
- **Pobudka od drzwi** daje telefonowi w aucie jeden podpisany sygnał
  drzwi dla czuwania kabiny (`WDROZENIE_TESTOWE.md` §5.13) — tylko sygnał,
  nigdy rozbrojenie.
- SMS `WAKE` wymaga numeru z białej listy **i** jednorazowego kodu TOTP
  (powtórka nie przejdzie, 5 złych kodów w godzinie blokuje numer).
- Z hosta do Nano trafiają tylko `HOLD:<1–60>` i `RELEASE`, sprawdzane po
  obu stronach.
- **Niesprawdzone na sprzęcie:** tolerancje dekodera NEC z prawdziwym TSOP,
  zasięg diody Redmi, Termux:API i nadajnik IR na crDroid 13, przetrwanie
  `.noinit` przez bootloader, okablowanie „odblokuj” w Alfie 156, pobór
  prądu TSOP w S3.
- **Na przyszłość (nie w tej wersji):** budzenie z głównego telefonu przez
  prywatny temat ntfy/MQTT z podpisem HMAC (dziś zapasem jest SMS
  `WAKE <kod>`), geofence przy podejściu, płytka BLE (nRF52840) na wejściu
  EXT.

---

## Powiązane dokumenty

| Dokument | Zakres |
|----------|--------|
| [`PCB_ZASILANIE.md`](PCB_ZASILANIE.md) | **dwie płytki drukowane do wytrawienia** — tor ładowania i dystrybucja zamiast „pająka" (może jeszcze opisywać poprzedni tor ładowania — §13.7 poz. 16) |
| [`WDROZENIE_M910Q.md`](WDROZENIE_M910Q.md) | pełne wdrożenie: sprzęt, BIOS, OS, usługi, odbiór |
| [`X86_PLATFORM_SETUP.md`](X86_PLATFORM_SETUP.md) | referencja krok-po-kroku (EN) — pamiętaj o §13 |
| [`x86-production/10-power-suspend.html`](x86-production/10-power-suspend.html) | zasilanie + S3 w wersji ilustrowanej |
| [`x86-production/02-assembly.html`](x86-production/02-assembly.html) | montaż mechaniczny, layout USB |
| [`mechanika/kosze_HR1221W_4+3.pdf`](mechanika/kosze_HR1221W_4+3.pdf) | projekt warsztatowy dwóch koszy stalowych na bank 4 + 3 (§4.7) |
| [`ARDUINO_SETUP_GUIDE.md`](ARDUINO_SETUP_GUIDE.md) | okablowanie trzech płytek Arduino, sygnały pojazdu |
| [`SCHEMATY_POLACZEN.md`](SCHEMATY_POLACZEN.md) | tabele połączeń, przekroje, bezpieczniki, kolejność montażu |
| [`../schematics/README.md`](../schematics/README.md) | indeks schematów |
