# Lista zakupowa — wszystko w jednym miejscu

Pełna lista do instalacji docelowej w Alfie 156 1.9 JTD:

- **A.** zasilanie buforowe (bank 7 × AGM, przetwornica do M910q, ładowanie z alternatora);
- **B.** ekran 10,1" 1280 × 800 z dotykiem;
- **C.** dane auta po K-Line (temperatura płynu, obroty, prędkość) i poziom paliwa;
- **D.** przyciski: przełączanie ekranów przyciskiem w manetce, panel z pokrętłem (drabinka rezystorowa), **play/pause — długie naciśnięcie usypia BCM (S3)**;
- **E.** wzmacniacz (używany, kompletny) z własnym zasilaniem z akumulatora, **włączany sygnałem pracy BCM**, a nie stacyjką.

Uzasadnienia i nastawy toru zasilania: [`ZASILANIE_BUFOROWANE.md`](ZASILANIE_BUFOROWANE.md) (dalej **ZB**).

> **Linki.** „🔗 oferta” to konkretna oferta znaleziona w sieci (stan na
> 11.2026 — oferty na Allegro często się kończą, wtedy użyj wyszukiwania obok).
> „🔎” to gotowe wyszukiwanie z właściwą frazą. Ceny orientacyjne, rynek PL.

> **Moduły bezmarkowe** (przetwornica, XY-SK120X, XH-M603, XH-M609) nie mają
> kart katalogowych — parametry są z opisów sprzedawców. **Każdą sztukę
> sprawdzasz po zakupie** (ZB §3.4, §5.2, §6.4, §7.3, §11 Etap 1).

### Podsumowanie kosztów

| Sekcja | Cena (PLN) |
|--------|-----------|
| A. Zasilanie buforowe (bez stali na kosze) | ~1150–1650 |
| B. Ekran 10,1" | ~380–750 |
| C. K-Line, paliwo, temperatura | ~60–130 |
| D. Przyciski | ~100–130 |
| E. Wzmacniacz używany + okablowanie + sterowanie REM | ~400–850 |
| **Razem** | **~2100–3500** |

---

## Masz już — nie kupuj

| Element | Rola | Uwaga |
|---------|------|-------|
| Lenovo ThinkCentre M910q Tiny + oryginalny zasilacz | komputer | z zasilacza bierzesz kabel z wtykiem i pinem ID (ZB §3.3) |
| **CSB HR1221W F2 × 7** (12 V / 5,1 Ah AGM) | bank buforowy 35,7 Ah | wszystkie 7 idą do banku — **nie ma sztuki zapasowej** (ZB §4.2) |
| **XH-M609** | LVD — ochrona banku 11,00 / 12,60 V | sprawdź na stole (ZB §7.3) |
| **Arduino Pro Micro** (ATmega32U4) | SWC, panel przycisków, manetka, enkoder — USB HID | |
| **Arduino Nano** | Nano #2 (sensor hub): zapłon, przycisk zasilania M910q, budzenie, paliwo | zasilany z bufora przez MP1584 — działa także, gdy M910q śpi |
| **Redmi Note 8 Pro** | internet, GPS, czujniki, SMS | [`PRZYGOTOWANIE_TELEFONU.md`](PRZYGOTOWANIE_TELEFONU.md) |
| Ekran 7" 1024 × 600 | do czasu wymiany na 10,1" | potem zapas / ekran stołowy |
| Karta Wi-Fi MT7921, pody SWC + dekoder | Android Auto wireless, kierownica | |
| Przetwornica step-up (obecna) | **za słaba** — zostaje na półce | nie zasilaj nią M910q |
| XL6019 | **za słaba** (ok. 45 W) — zostaje na półce | ZB §3 |

> **Nano V3 z ATmega328PB** wymaga innej sygnatury przy wgrywaniu — rozwiązania
> w `arduino/sensor_hub/sketch.yaml`.

---

## A. Zasilanie buforowe

> **Budujesz na płytkach drukowanych?** [`PCB_ZASILANIE.md`](PCB_ZASILANIE.md)
> ma osobną listę elementów — wtedy wykreśl stąd A4 (przekaźnik z podstawką)
> i A5 (listwa).

### A.1 Moduły

| # | Element — konkretny model | Nastawa / po co | Szt. | Cena (PLN) | Gdzie |
|---|---------------------------|-----------------|------|-----------|-------|
| A1 | **Przetwornica step-up 1200 W / 20 A, wejście 8–60 V, wyjście 12–80 V** (płytka z dwoma radiatorami, potencjometrami napięcia, prądu i progu wejścia; np. Elektroweb 3-T-018) | **wyjście 20,0 V**, próg wejścia (UVLO) **10,5 V** — tuż pod LVD 11,0 V. Przy 65–95 W bierze z banku 6–10 A, czyli połowę dopuszczalnych 20 A — **bez wentylatora** (potrzebny dopiero powyżej 15 A). Po nastawieniu zabezpiecz potencjometry lakierem. **Nie ma ochrony przed odwrotną polaryzacją ani zwarciową** — stąd bezpieczniki F8 (wejście) i 5 A (wyjście). Test: ZB §3.4 | 1 | 45–60 | 🔗 [oferta](https://allegro.pl/oferta/przetwornica-ladowarka-20a-1200w-step-up-8-60v-12-80v-15504214222) · 🔗 [oferta 2](https://allegro.pl/oferta/przetwornica-1200w-dc-dc-step-up-8-60v-12-80v-11404888486) · 🔎 [AliExpress](https://www.aliexpress.com/w/wholesale-1200W-20A-DC-DC-boost-converter.html) |
| A1z | *(zapas, opcjonalnie)* **Lenovo ThinkPad 65W DC Travel Adapter (Slim Tip), P/N 0B47481** — oryginalna ładowarka samochodowa Lenovo z wtykiem slim tip **z pinem ID** | plan B, gdyby A1 sprawiała kłopoty; wejście 12 V (Lenovo nie podaje minimum — **sprawdź przy 11 V**), 65 W — starcza na M910q z procesorem 35 W | 0–1 | 80–200 | 🔎 [Allegro](https://allegro.pl/listing?string=lenovo%200B47481) |
| A2 | **XY-SK120X** (Sinilink, buck-boost CC-CV 6–36 V → 0–36 V, 6 A / 120 W) — wersja **X** (nowsza płytka, przyciski mechaniczne) | **CV 14,40 V, CC 5,0 A** każda; dwie równolegle ≈ 10 A (ZB §5.2–5.3). Po włączeniu zasilania wyjście startuje wyłączone, dopóki nie włączysz go w menu — ustaw włączanie przy starcie (ZB §5.2) | **2** | 120–200 | 🔎 [Allegro](https://allegro.pl/listing?string=XY-SK120X) · 🔎 [AliExpress](https://www.aliexpress.com/w/wholesale-XY-SK120X.html) |
| A3 | **XH-M603** (moduł sterowania ładowaniem 12–24 V, przekaźnik) — po jednym na ładowarkę | blokada przeładowania **15,30 / 14,00 V** (ZB §6.2–6.3) | **2** | 40–100 | 🔗 [oferta](https://allegro.pl/oferta/modul-sterowania-ladowania-akumulatora-xh-m603-9791660871) · 🔎 [Allegro](https://allegro.pl/listing?string=regulator%20xh%20m603) |
| A4 | **Przekaźnik Bosch 0 332 209 150** (12 V / 30 A, 5 pinów, przełączny) **+ podstawka 5-pin** | K1 — odcina tor ładowania przy zgaszonym silniku. Sprawdź liczbę pinów w ofercie (bywa mylony z 4-pinowym 0 332 019 150) | 1 | 25–45 | 🔎 [przekaźnik](https://allegro.pl/listing?string=przeka%C5%BAnik%20bosch%200%20332%20209%20150) · 🔎 [podstawka](https://allegro.pl/listing?string=podstawka%20przeka%C5%BAnika%20samochodowego%205%20pin) |
| A5 | **Listwa bezpiecznikowa ATO 6–8 obwodów z pokrywą** (albo płytka B z [`PCB_ZASILANIE.md`](PCB_ZASILANIE.md)) | dystrybucja za LVD: F8–F11, F13 | 1 | 40–70 | 🔎 [Allegro](https://allegro.pl/listing?string=skrzynka%20bezpiecznik%C3%B3w%20ATO%206%20obwod%C3%B3w%20pokrywa) |
| A6 | **Moduł przekaźnika 1-kanałowy 5 V z optoizolacją** (SRD-05VDC + EL817) | styki równolegle do przycisku zasilania M910q (Nano #2, A0) | 1 | 7–15 | 🔗 [oferta](https://allegro.pl/produkt/modul-przekaznika-1-kanal-z-optoizolacja-5v-10a-l-h-arduino-62c7336e-a9cb-46a4-9344-af5671d55ff7) |
| A7 | **MP1584** (buck 12 → 5 V, 3 A) | zasilanie Nano #2 niezależne od USB | 1–2 | 5–10 | 🔎 [Allegro](https://allegro.pl/listing?string=MP1584%20przetwornica) |
| A8 | **LM2596** (buck 12 → 5 V, 3 A, z woltomierzem albo bez) | 5 V dla ekranu 10,1", gdy port USB M910q nie wystarczy (sekcja B) | 1 | 8–15 | 🔎 [Allegro](https://allegro.pl/listing?string=LM2596%20przetwornica%20step%20down) |

> **Dlaczego nie „zalewana 12 → 20 V”.** Zalewane moduły 20 V w sklepach to
> w praktyce bezmarkowe „12 V → 19 V 10 A” (wejście zwykle 11–16 V — na granicy
> LVD) i rzadko spotykane 20 V bez danych; Twoja obecna jest właśnie taka
> i nie daje rady. Moduł A1 ma regulowane wyjście (ustawiasz dokładnie 20,0 V),
> regulowany próg wejścia i ok. dwukrotny zapas prądu. Jest otwarty — zamknij go
> w wentylowanej obudowie (np. perforowana puszka aluminiowa) w bagażniku przy
> koszach (ZB §3.5, §8a.1).

### A.2 Bezpieczniki

> **Prawdziwe przykręcane MIDI (Littelfuse 498, MTA MIDIVAL) zaczynają się od
> 30 A** — 15 i 20 A w tej klasie nie istnieją, a na Allegro „bezpiecznik MIDI
> 20 A” to zwykle zwykła wkładka nożowa ATO. Dlatego F1, F7 i F12 to **MIDI 30 A**
> (zdolność wyłączania 2 kA przy 32 V wg karty Littelfuse/MTA): 30 A nadal chroni
> przewód 6 mm² — to wariant przewidziany w ZB §8.1. Przewód przy F12 zrób wtedy
> też z **6 mm²** (to tylko krótki odcinek w bagażniku).

| # | Element | Specyfikacja | Szt. | Cena (PLN) | Gdzie |
|---|---------|--------------|------|-----------|-------|
| A9 | **MTA MIDIVAL 30 A** (albo Littelfuse MIDI 498 30 A) | F1 (≤ 30 cm od klemy „+” rozruchowego), F7 (blok L+ → XH-M609), F12 (przewód ładowania → L+) | 3 (+1 zapas) | 15–25 | 🔗 [oferta](https://allegro.pl/oferta/bezpiecznik-midival-midi-val-mta-30a-7066883537) |
| A10 | **Oprawka MIDI/MIDIVAL** (przykręcana M5, rozstaw 30 mm, z pokrywą) | do A9 | 3 | 45–90 | 🔗 [oferta](https://allegro.pl/gniazdo-obudowa-oprawa-bezpiecznika-midival-midi-i5997422487.html) · 🔗 [oferta 2](https://allegro.pl/oferta/gniazdo-oprawa-bezpiecznika-samochodowego-do-auta-obudowa-midi-17322407031) |
| A11 | **Oprawki inline ATO hermetyczne** | FB1…FB7 i FC1, FC2 na 2,5 mm²; FK na 0,75 mm²; jedna na **4 mm²** (5 A, wyjście przetwornicy); jedna na 0,5 mm² (1 A, pomiar banku) | 12 | 45–80 | 🔎 [Allegro](https://allegro.pl/listing?string=oprawka%20bezpiecznika%20ATO%20hermetyczna) |
| A12 | **Wkładki ATO** (Littelfuse/MTA, nie no-name) | FB 10 A × 7, FC 7,5 A × 2, FK 1 A; F8 10 A, F9 2 A, F10 3 A, F11 5 A, F13 2 A, wyjście przetwornicy 5 A, pomiar 1 A + zapas po 1 szt. | kpl. | 15–25 | 🔎 [Allegro](https://allegro.pl/listing?string=bezpieczniki%20ATO%20littelfuse%20zestaw) |

### A.3 Elementy dyskretne (TME)

| # | Element | Specyfikacja | Szt. | Cena (PLN) | Gdzie |
|---|---------|--------------|------|-----------|-------|
| A13 | **SMCJ20CA** (TVS 1,5 kW, dwukierunkowa — „CA”) | wejście toru ładowania (ZB §5.8) | 2 | 3–6 | 🔗 [TME](https://www.tme.eu/pl/details/smcj20ca-lf/diody-transil-dwukierunkowe-smd/littelfuse/smcj20ca/) |
| A14 | **Panasonic EEUFR1V471** (470 µF / 35 V, low-ESR, 105 °C) | wejście toru ładowania + **2 szt. na wyjście przetwornicy A1** (filtr tętnień, rozruch M910q) | 4 | 8–14 | 🔗 [TME](https://www.tme.eu/pl/details/eeufr1v471/kondensatory-elektrolityczne-tht/panasonic/) |
| A15 | 1N4007 | gaszenie cewki K1, ochrona VS w module K-Line (C) | 5 | 2–5 | 🔎 [TME](https://www.tme.eu/pl/katalog/?search=1N4007) |
| A16 | **PC817** (Sharp PC817XJ0000F, DIP-4) | wejście zapłonu + odczyt diody zasilania M910q (Nano #2) | 2 | 2–4 | 🔗 [TME](https://www.tme.eu/pl/details/pc817x/transoptory-z-wyjsciem-analogowym/sharp/pc817xj0000f/) |
| A17 | Rezystory 1/4 W | 2,2 kΩ × 2, 10 kΩ × 2, 1 kΩ × 2; dzielnik pomiaru banku 100 kΩ + 27 kΩ | kpl. | 5–10 | 🔎 [TME](https://www.tme.eu/pl/katalog/rezystory-tht_112304/) |
| A18 | Kondensator ceramiczny 100 nF | filtry wejść (zapłon, dioda, pomiar banku) | 5 | 2–4 | 🔎 [TME](https://www.tme.eu/pl/katalog/?search=100nF%2050V%20THT) |

### A.4 Przewody i złącza

Wszystkie przewody z **czystej miedzi** (FLRY / FLRY-B wg ISO 6722 albo
car-audio OFC), **nie CCA** — w ofercie szukaj „miedź / Cu” (ZB §8.2).

| # | Element | Specyfikacja | Ilość | Cena (PLN) | Gdzie |
|---|---------|--------------|-------|-----------|-------|
| A19 | **Przewód 6 mm²** | czerwony ~8 m + czarny ~2 m | 10 m | 110–160 | 🔎 [FLRY-B 6 mm²](https://allegro.pl/listing?string=przew%C3%B3d%20FLRY-B%206mm2) |
| A20 | **Przewód 4 mm²** | czerwony ~7 m + czarny ~5,5 m (20 V do M910q 2 × ~4 m, wejście przetwornicy, LVD → dystrybucja) | 12,5 m | 65–110 | 🔎 [FLRY-B 4 mm²](https://allegro.pl/listing?string=przew%C3%B3d%20FLRY-B%204mm2) |
| A21 | **Przewód 2,5 mm²** FLRY-B | 14 odcinków pakiet → blok (~0,25 m, **równe ±30 mm**), gałęzie ładowarek | ~12 m | 50–80 | 🔎 [FLRY-B 2,5 mm²](https://allegro.pl/listing?string=przew%C3%B3d%20FLRY-B%202.5mm2) |
| A22 | Przewody 1,5 / 0,75 / 0,5 mm² FLRY | 5 V do ekranu (1,5), cewka K1 (0,75 — ~5 m), sygnały: zapłon, przekaźnik, dioda, pomiar banku, paliwo, przyciski (0,5 — kilka kolorów) | ~30 m | 50–80 | 🔎 [Allegro](https://allegro.pl/kategoria/elektryka-i-akcesoria-kable-i-przewody-15962?string=flry&rodzaj-kabla=samochodowy) |
| A23 | **Bloki zbiorcze 4 × M6 z pokrywą** (L+, L−, P+, P−) | gwiazda w każdym koszu (ZB §4.3) | 4 | 80–140 | 🔎 [Allegro](https://allegro.pl/listing?string=blok%20rozdzielczy%20M6%204%20%C5%9Bruby%20pokrywa) |
| A24 | **Oczka zaciskane M6** izolowane | na 2,5 mm² (16+), na 6 mm² (10+) | ~30 | 45–75 | 🔎 [Allegro](https://allegro.pl/listing?string=ko%C5%84c%C3%B3wki%20oczkowe%20M6%20izolowane%206mm2) |
| A25 | **Nasuwki żeńskie 6,3 × 0,8 mm w pełni izolowane** + koszulki termokurczliwe z klejem | zaciski F2 pakietów (14 + zapas) | kpl. | 30–50 | 🔎 [Allegro](https://allegro.pl/listing?string=konektor%20%C5%BCe%C5%84ski%206.3%20w%20pe%C5%82ni%20izolowany) |
| A26 | Peszel + przelotki gumowe | bagażnik → deska (~8 m), osłona łącznika między koszami | kpl. | 25–40 | 🔎 [Allegro](https://allegro.pl/listing?string=peszel%20samochodowy%20karbowany) |
| A27 | **Rozłącznik masy 100 A** (S1), kluczykowy albo pokrętło | serwis, długi postój — rozłączaj bez obciążenia (ZB §8.4) | 1 | 40–70 | 🔎 [Allegro](https://allegro.pl/listing?string=od%C5%82%C4%85cznik%20masy%20100A) |
| A28 | **Kabel zasilacza Lenovo slim tip z pinem ID** (wtyk 11,0 × 4,5 mm) | tylko jeśli **nie chcesz** ciąć oryginalnego zasilacza — sprawdź omomierzem, czy środkowy pin jest wyprowadzony (tanie kable bywają dwużyłowe) | 0–1 | 10–30 | 🔗 [oferta](https://allegro.pl/oferta/kabel-zasilacza-ladowarki-do-laptopa-lenovo-wtyk-prosty-slim-tip-11-0-x-4-5-12387780523) |
| A29 | Kabel USB z przeciętą żyłą VBUS | Nano #2 ma własne 5 V z MP1584 | 1 | 0–15 | — |

### A.5 Kosze na bank

Dwa kosze stalowe wg [`mechanika/kosze_HR1221W_4+3.pdf`](mechanika/kosze_HR1221W_4+3.pdf)
(kosz L 4 szt., kosz P 3 szt.; ≈ 16,8 kg z pakietami — ZB §4.7). Materiał
(do wyceny w hurtowni stali / ślusarza):

| Poz. PDF | Materiał | Ilość |
|----------|----------|-------|
| 1 | kątownik 25 × 25 × 3 mm S235JR | 3 × 1,0 m |
| 2 | płaskownik 20 × 3 mm S235JR | 3 × 1,0 m |
| 3 | płaskownik 30 × 4 mm S235JR | 1 × 1,0 m (+1 m, jeśli grodź się ugina) |
| 4 | nakrętki do spawania M8 (DIN 934, czarne) | 4 |
| 5 | śruby M8 × 30 kl. 8.8 + podkładki sprężyste i zwykłe | 4 kpl. |
| 6 | śruby M8 × 25 kl. 8.8 + nakrętki DIN 985 | 8 kpl. |
| 7 | podkładki poszerzane M8 DIN 9021 | 16 |
| 8 | guma EPDM 400 × 500 × 3 mm | 1 |
| 9 | kapturki na zaciski + podkład epoksydowy i lakier | 14 + 2 spraye |

> **Podłogi bagażnika nie wierć** (zbiornik paliwa) — 8 otworów Ø 8,5 mm tylko
> poziomo przez grodź. Przed spawaniem przymiarka wg ramki w ZB §4.7.

---

## B. Ekran 10,1" 1280 × 800

| # | Element — konkretny model | Dlaczego | Szt. | Cena (PLN) | Gdzie |
|---|---------------------------|----------|------|-----------|-------|
| B1 | **Waveshare 10.1HP-CAPLCD Monitor** (1280 × 800 IPS, 350 cd/m², szkło hartowane klejone optycznie, dotyk pojemnościowy 10 pkt po USB, HDMI / USB-C, zasilanie 5 V USB-C, obudowa aluminiowa **VESA 75**) | gotowy monitor w obudowie; **jasność przez DDC/CI potwierdzona** — działa „Ściemnianie: Sprzętowe (DDC/CI)” w Ustawieniach; dotyk działa w Linuksie bez sterowników | 1 | 650–750 | 🔗 [Kamami](https://kamami.pl/en/tftips-displays/1185263-10-1inch-capacitive-touch-display-wide-color-gamut-1280-800-optical-bonding-toughened-glass-panel-5906623427604.html) · [strona producenta](https://www.waveshare.com/10.1hp-caplcd-monitor.htm) |
| B1z | *(tańsza alternatywa)* **Waveshare 10.1DP-CAPLCD** (SKU 23739) — ten sam rozmiar i rozdzielczość, 350 cd/m², szkło klejone optycznie, **bez obudowy**, 4 W | jeśli robisz własną ramkę w desce; DDC/CI prawdopodobne, ale niepotwierdzone (zostaje programowe ściemnianie) | 0–1 | 330–400 | 🔗 [Botland](https://botland.store/ips-displays/28607-101dp-caplcd-101-inch-capacitive-ips-lcd-touchscreen-1280x800px-hdmi-usb-waveshare-23739-5906623427208.html) |
| B2 | Kabel **DisplayPort → HDMI** (pasywny, 1–2 m) albo HDMI, jeśli Twój M910q ma port HDMI | obraz | 1 | 20–40 | 🔎 [Allegro](https://allegro.pl/listing?string=kabel%20displayport%20hdmi%201.8m) |
| B3 | Kabel **USB-A → USB-C** 1–2 m (z transmisją danych) | dotyk + zasilanie ekranu | 1 | 15–30 | 🔎 [Allegro](https://allegro.pl/listing?string=kabel%20usb%20a%20usb%20c%20dane%202m) |
| B4 | Uchwyt **VESA 75** / płytka adaptera do deski | montaż | 1 | 20–60 | 🔎 [Allegro](https://allegro.pl/listing?string=uchwyt%20vesa%2075%20p%C5%82ytka) |

> **Zasilanie ekranu.** Najpierw z portu USB M910q. Jeśli obraz miga przy pełnej
> jasności (port daje ~0,9 A, ekran ~1,2 A), zasil wejście 5 V z LM2596 (A8,
> bezpiecznik F9 2 A) — wtedy zmierz pobór ekranu w czuwaniu, bo wlicza się do
> budżetu postoju (ZB §9.1). Po zamontowaniu ustaw rozdzielczość 1280 × 800
> w `config/local.yaml` (blok `display`, `WDROZENIE_M910Q.md` §6.3).
>
> **Jasność 350 cd/m²** to typowa wartość dla 10,1" w tej cenie. Panele
> „sunlight readable” (1000 cd/m²) kosztują kilka razy więcej i są trudno
> dostępne w PL — przy słońcu pomaga daszek i matowa folia.

---

## C. K-Line: temperatura płynu, obroty, prędkość + poziom paliwa

**Co skąd w 156 1.9 JTD (EDC15C7, przed liftingiem):**

- **Temperatura płynu chłodzącego, obroty, prędkość** — ze sterownika silnika
  po K-Line (gniazdo OBD **pin 7**, KWP2000). Wystarczy **jeden kanał**.
  Kody (local ID) trzeba jeszcze potwierdzić podsłuchem MES —
  [`KLINE_SNIFFING.md`](KLINE_SNIFFING.md).
- **Poziom paliwa — nie z diagnostyki.** Zegary 156 sprzed liftingu czytają
  czujnik w baku analogowo i nie wystawiają poziomu na K-Line (MES też go nie
  pokazuje). Odczyt idzie z **przewodu czujnika** (pływak ok. 10–20 Ω pełny …
  ok. 300–340 Ω pusty — zmierz swój) do **Nano #2, wejście A7**:
  - **docelowo — zegary wylatują, w ich miejscu ekran BCM:** czujnik zasila
    Nano przez **330 Ω z D13, tylko na czas pomiaru** (`FEATURE_FUEL_DRIVE`),
    odczyt przez 1 kΩ + 100 nF. Kontrolki z zegarów (olej, ładowanie,
    hamulce, ABS, airbag, świece) muszą wtedy trafić gdzie indziej;
  - **przejściowo — zegary jeszcze są:** tylko podgląd napięcia przez
    dzielnik 100k/47k; **nie** podawaj zasilania z Arduino, bo wskazówka
    zaczęłaby kłamać.

  Schematy obu wariantów: `SCHEMATY_POLACZEN.md` §4.4.3 (PR z firmware).

| # | Element | Specyfikacja / po co | Szt. | Cena (PLN) | Gdzie |
|---|---------|----------------------|------|-----------|-------|
| C1 | **L9637D** (ST, SO-8) | transceiver K-Line | 1–2 | 5–15 | 🔎 [TME](https://www.tme.eu/pl/katalog/?search=L9637D) |
| C2 | **Płytka-przejściówka SO-8 → DIP-8** | do przylutowania L9637D | 2 | 3–8 | 🔎 [Allegro](https://allegro.pl/listing?string=adapter%20SO8%20DIP8%20p%C5%82ytka) |
| C3 | **Moduł USB-UART FT232RL** (oryginalny FTDI, przełącznik 3,3/5 V) — albo CP2102 | port `/dev/ttyUSB*` dla BCM; FTDI ma najpewniejsze taktowanie inicjalizacji 5 bodów | 1 | 15–30 | 🔎 [Allegro](https://allegro.pl/listing?string=ft232rl%20modu%C5%82%20usb%20uart) |
| C4 | Rezystor **510 Ω 0,5 W**, 100 nF, 1N4007 (A15), płytka uniwersalna, mała obudowa | pull-up linii K do +12 V, odsprzęganie, ochrona VS | kpl. | 10–20 | 🔎 [TME](https://www.tme.eu/pl/katalog/?search=510R%200.5W) |
| C5 | **Wtyk OBD-II męski z przewodem** (pigtail 16-pin) albo przewody wpięte za gniazdem | podłączenie pin 4/5 (masa), 7 (K), 16 (+12 V) | 1 | 15–30 | 🔎 [Allegro](https://allegro.pl/listing?string=wtyk%20OBD2%20m%C4%99ski%20z%20przewodem) |
| C6 | *(jeśli nie masz kabla KKL)* **Kabel KKL 409.1 z FTDI FT232RL** — do podsłuchu MES | sniffing kodów; potem zostaje do diagnostyki | 0–1 | 40–90 | 🔎 [Allegro](https://allegro.pl/listing?string=kabel%20kkl%20409.1%20ftdi%20ft232rl) |
| C7 | **Odczyt paliwa:** rezystory **330 Ω 0,5 W** + 1 kΩ + kondensator 100 nF (wariant bez zegarów); dla wariantu z zegarami dodatkowo 100 kΩ + 47 kΩ i dioda Zenera 5,1 V (BZX55C5V1); przewód 0,5 mm² do bagażnika (~4 m) | zasilanie impulsowe pływaka z D13 Nano #2 / podgląd bez obciążania zegarów; ochrona wejścia A7 | kpl. | 3–8 | 🔎 [TME](https://www.tme.eu/pl/katalog/?search=330R%200.5W%20THT) |

> **Rozkład pinów L9637D** (karta ST): 1 RX, 2 LO, 3 VCC, 4 TX, 5 GND, 6 K,
> 7 VS, 8 LI — bez wejścia EN. Starsze wydania `SCHEMATY_POLACZEN.md` §3.5
> i `x86-production/05-kline-obd.html` miały to pomieszane; są poprawione.

---

## D. Przyciski: manetka, panel z pokrętłem

| Funkcja | Jak | Co kupić |
|---------|-----|----------|
| **Przełączanie ekranów** przyciskiem w manetce | styk manetki (12 V) → transoptor PC817 → Pro Micro **A2** → następny ekran | D1 |
| **Panel z pokrętłem** (głośność, dalej, wstecz, mikrofon, wyciszenie, odbierz, odrzuć, play/pause) | kostka odbiornika to drabinka rezystorowa: biały **KEY1 → Pro Micro A6** z **pull-upem 1 kΩ do 5 V**, czerwony → +12 V z bufora przez 1 A, czarny → masa wspólna z Arduino | D2, D3 |
| **Play/pause: krótko = odtwarzaj/pauza, trzymane 2 s = uśpienie BCM (S3)** | w firmware Pro Micro (v8.6) — nic więcej do kupienia | — |

Schemat, wzór ADC, kalibracja (`CAL2`) i sprawdzenie (`ADC2`):
`SCHEMATY_POLACZEN.md` §4.4 (PR z firmware).

| # | Element | Specyfikacja / po co | Szt. | Cena (PLN) | Gdzie |
|---|---------|----------------------|------|-----------|-------|
| D1 | **Moduł transoptora PC817, wersja 12 V → 5 V** (1–4 kanały) | izolacja przycisku z manetki od Arduino; wolne kanały na zapas | 1 | 8–25 | 🔎 [Allegro](https://allegro.pl/listing?string=PC817%204%20kana%C5%82y%20optoizolator%2012V%205V) · 🔎 [AliExpress](https://www.aliexpress.com/w/wholesale-PC817-4-channel-optocoupler-isolation-board-12V-to-5V.html) |
| D2 | **Panel z pokrętłem** — [Twój link z AliExpress](https://pl.aliexpress.com/item/1005009589029595.html) | kostka KEY1 / +12 V / GND, panel z akumulatorem ładowanym przez USB-C (na stałe: 5 V z hubu albo LM2596) | 1 | ~80 | AliExpress |
| D3 | **Rezystor 1 kΩ 1 % 1/4 W** × 2 (pull-up A0 i A6; + 2,2 kΩ na zapas), kondensator 100 nF, bezpiecznik inline 1 A + oprawka, przewód 0,5 mm², złącza | pull-up dla drabinek, zasilanie kostki z bufora | kpl. | 10–25 | 🔎 [TME](https://www.tme.eu/pl/katalog/?search=1k%201%25%200.25W%20THT) |

## E. Wzmacniacz — używany, kompletny

**Założenie:** gotowy samochodowy wzmacniacz z rynku wtórnego (JBL, Alpine
i podobne), zasilany **osobną gałęzią prosto z akumulatora rozruchowego**
(nie z banku — szczyty 20–30 A przekroczyłyby LVD, ZB §2.2), a **włączany
sygnałem pracy BCM**: REM ma 12 V tylko wtedy, gdy M910q działa. Uśpienie
BCM (S3) albo jego wyłączenie gasi wzmacniacz, a stacyjka nie ma na to wpływu.

### E.1 Na co patrzeć przy zakupie używanego

| Wymaganie | Dlaczego |
|-----------|----------|
| **4 kanały**, klasa D albo AB, ok. 4 × 50–75 W RMS / 4 Ω | przód + tył; klasa D grzeje się mniej i bierze mniej prądu |
| **wejścia RCA** (najlepiej też tryb 2 → 4 kanały) | z mini-jacka M910q idą tylko 2 kanały |
| **wejście REM** (remote) | włączanie przez BCM |
| bezpieczniki na obudowie łącznie **≤ 40 A** | dobór okablowania niżej |
| test u sprzedawcy: gra na wszystkich kanałach, bez szumu i bez „protect” | używane wzmacniacze najczęściej padają na zasilaczu impulsowym |

Przykładowe modele (oceniaj stan, nie markę): JBL GTO-series 4-kanałowe, JBL
Stage A6004, Alpine MRV-F300 / MRP-F300 / MRV-F450, Pioneer GM-A6704, Kenwood
KAC-M3004.

### E.2 Lista

| # | Element | Specyfikacja / po co | Szt. | Cena (PLN) | Gdzie |
|---|---------|----------------------|------|-----------|-------|
| E1 | **Wzmacniacz 4-kanałowy używany** (wymagania z E.1) | | 1 | 150–450 | 🔎 [Allegro](https://allegro.pl/listing?string=wzmacniacz%20samochodowy%204%20kana%C5%82owy%20u%C5%BCywany) · 🔎 [OLX](https://www.olx.pl/oferty/q-wzmacniacz-samochodowy-4-kanalowy/) |
| E2 | **Przewód zasilający 10 mm² (8 AWG) OFC** czerwony ~5,5 m + czarny ~1 m (albo gotowy zestaw okablowania 8 AWG **OFC**, nie CCA) | akumulator w komorze silnika → bagażnik/pod fotel; masa krótko do karoserii | kpl. | 90–160 | 🔎 [Allegro](https://allegro.pl/listing?string=przew%C3%B3d%20zasilaj%C4%85cy%2010mm2%20OFC) |
| E3 | **Bezpiecznik MIDI 40 A + oprawka** (A9/A10, ta sama rodzina) | ≤ 30 cm od klemy „+” — chroni przewód, nie wzmacniacz | 1 | 20–35 | 🔎 [Allegro](https://allegro.pl/listing?string=bezpiecznik%20midival%2040A) |
| E4 | Oczka zaciskane M8 / pod zacisk wzmacniacza na 10 mm², przelotka przez grodź | | kpl. | 15–30 | 🔎 [Allegro](https://allegro.pl/listing?string=ko%C5%84c%C3%B3wki%20oczkowe%2010mm2%20M8) |
| E5 | **Kabel RCA 2 × RCA, 5 m, ekranowany** + **przejściówka mini-jack 3,5 mm → 2 × RCA** | sygnał z M910q; prowadź po przeciwnej stronie auta niż zasilanie | 1 | 30–60 | 🔎 [Allegro](https://allegro.pl/listing?string=kabel%20RCA%205m%20samochodowy) |
| E6 | *(w razie buczenia)* **Separator masy (ground loop isolator) RCA** | pętla masy z alternatorem (SCHEMATY_POLACZEN.md §5.4) | 0–1 | 15–30 | 🔎 [Allegro](https://allegro.pl/listing?string=separator%20masy%20RCA%20ground%20loop) |
| E7 | **Przewód głośnikowy 2 × 1,5 mm²** (~16 m) albo **adapter ISO** do fabrycznej wiązki głośników | wyjścia wzmacniacza → 4 głośniki | kpl. | 30–60 | 🔎 [Allegro](https://allegro.pl/listing?string=przew%C3%B3d%20g%C5%82o%C5%9Bnikowy%202x1.5%20OFC) |
| E8 | **Sterowanie REM:** moduł przekaźnika 1-kanałowy 5 V (jak A6) **zasilany z portu USB M910q** + kabel USB-A do przecięcia + bezpiecznik inline 1 A + przewód 0,75 mm² | styk NO przekaźnika podaje 12 V (z gałęzi wzmacniacza, przez 1 A) na REM. Port USB ma 5 V tylko, gdy M910q działa — w S3 i po wyłączeniu przekaźnik puszcza i wzmacniacz gaśnie | 1 kpl. | 15–30 | 🔗 [przekaźnik](https://allegro.pl/produkt/013-1-kanalowy-modul-przekaznika-5v-10a-1ch-avr-arduino-optoizolacja-4cf1d074-85ae-4309-9620-b445c09777d9?offerId=9431454240) |

> **REM — dwie rzeczy do sprawdzenia.** (1) Wepnij moduł **bezpośrednio w port
> M910q, nie w zasilany hub** — hub jest zasilany z bufora i trzymałby 5 V
> także w uśpieniu. (2) W BIOS M910q wyłącz ładowanie USB w uśpieniu / wyłączeniu
> i multimetrem potwierdź, że wybrany port w S3 ma 0 V. Wzmacniacz z typowym
> opóźnieniem włączania (0,5–2 s) nie „pyka” przy starcie; jeśli pyka przy
> usypianiu, BCM może wyciszyć dźwięk przed S3 (zmiana w oprogramowaniu).

---

## Narzędzia i pomiary

| Element | Po co | Cena (PLN) |
|---------|-------|-----------|
| **Multimetr z pomiarem prądu DC 10 A** | odbiór instalacji, pobór w S3, prąd ładowania — **bez niego nie uruchomisz bufora** | 80–200 |
| **Zaciskarka zapadkowa** (nasuwki, oczka do 6 mm²) + zaciskarka hydrauliczna / młotkowa do 10 mm² | zaciski kombinerkami to najczęstsza usterka | 60–200 |
| Lutownica + topnik (SO-8 dla L9637D) | moduł K-Line | — |
| Woltomierz/amperomierz panelowy z bocznikiem 50 A | podgląd banku | 40–70 |
| Ładowarka sieciowa AGM | doładowanie w garażu | 150–300 |

---

## Czego **nie** kupować

| Element | Dlaczego |
|---------|----------|
| Kolejna „zalewana 12 → 19/20 V 10 A” | taka już jest za słaba; w ofertach to zwykle 19 V z wejściem od 11 V (granica LVD) |
| Przetwornica „600 W / 10 A” | 10 A wejścia przy 11 V to ok. 100 W wyjścia — za blisko granicy |
| Przetwornica z wyjściem **19 V** | po 4 m przewodu na wtyku zejdzie poniżej 19 V (ZB §3.1) |
| „Bezpiecznik MIDI 15 / 20 A” z Allegro | prawdziwe MIDI zaczynają się od 30 A — to wkładki ATO o niskiej zdolności wyłączania |
| Moduł buck (XL4016 itp.) jako ładowarka | nie da 14,40 V z instalacji (ZB §5.1) |
| Jeden XH-M603 na obie ładowarki | 10 A ponad realne ~8 A płytki (ZB §6.3) |
| Przewód CCA | ok. 1,6 × większa rezystancja (ZB §8.2) |
| Waveshare 10.1" HDMI LCD (E) / (H) | to 1024 × 600, nie 1280 × 800 |
| Kable „USB-C PD trigger 12 V” do REM | z portu komputera dają tylko 5 V |
| Interfejs ELM327 do K-Line | BCM mówi po K-Line bezpośrednio (port szeregowy, inicjalizacja 5 bodów, KWP2000); ELM327 to inny interfejs (komendy AT) i z kodem BCM nie współpracuje |
| Drugi kanał K-Line | temperatura, obroty i prędkość są w ECU silnika (pin 7); paliwo idzie z ADC |
| Ładowarka/BMS do LiFePO₄ lub Li-ion, preset GEL | inne napięcia — zniszczy bank AGM |
| Akumulatory rozruchowe zamiast HR1221W | nie znoszą pracy cyklicznej |

---

## Powiązane dokumenty

| Dokument | Zakres |
|----------|--------|
| [`ZASILANIE_BUFOROWANE.md`](ZASILANIE_BUFOROWANE.md) | nastawy, uzasadnienia, procedura uruchomienia (§11) |
| [`SCHEMATY_POLACZEN.md`](SCHEMATY_POLACZEN.md) | tabele „skąd → dokąd”, K-Line §3.5, wzmacniacz §2.6 |
| [`KLINE_SNIFFING.md`](KLINE_SNIFFING.md) | jak znaleźć kody EDC15C7 (temperatura, obroty) |
| [`WDROZENIE_M910Q.md`](WDROZENIE_M910Q.md) | wdrożenie całości, rozdzielczość ekranu 10,1" (§6.3) |
| [`ARDUINO_OD_ZERA.md`](ARDUINO_OD_ZERA.md) | wgranie firmware na Nano i Pro Micro |
| [`PCB_ZASILANIE.md`](PCB_ZASILANIE.md) | wariant na płytkach drukowanych |
| [`mechanika/kosze_HR1221W_4+3.pdf`](mechanika/kosze_HR1221W_4+3.pdf) | projekt koszy na bank |
