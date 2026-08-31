"""Most do wyświetlacza pomocniczego 1,8" na ESP32-S3 (USB CDC).

Odwrotność ``src/input/arduino_serial.py``: tam Arduino pisze, a BCM
czyta; tutaj BCM pisze, a ESP32 czyta. Moduł subskrybuje magistralę
zdarzeń i wypisuje do portu linie ``KLUCZ:wartość`` — ten sam kształt
protokołu, którym mówi już ``sensor_hub``.

Projekt ekranów i uzasadnienie podziału sygnałów: ``docs/WYSWIETLACZ_ESP32_1V8.md``.

Protokół (115200 8N1, UTF-8, linie zakończone ``\\n``)::

    SRC:BT|AA|---      źródło dźwięku
    TITLE:<tekst>      tytuł utworu
    ARTIST:<tekst>     wykonawca
    PLAY:0|1           odtwarzanie
    POS:<sekundy>      pozycja w utworze
    DUR:<sekundy>      długość utworu
    CRUISE:0|1         tempomat
    SETSPD:<km/h>      zadana prędkość (pusta wartość = nieznana)
    PING               keepalive, ESP32 odpowiada PONG

ESP32 po starcie wysyła ``READY``; wtedy wypychamy pełny stan od nowa,
bo płytka zgubiła wszystko, co dostała wcześniej.

Zasady ruchu na porcie:

- **wysyłamy tylko zmiany** — stan trzymamy w ``_state``, a ``_sent``
  pamięta, co już poszło w kabel. Pozycja utworu tyka co sekundę, więc
  bez tego filtru port dostawałby ośmiokrotnie więcej linii niż trzeba,
  a ESP32 przerysowywałby ekran bez powodu;
- **PING co 2 s** — ESP32 uznaje BCM za offline po 5 s ciszy i wygasza
  metadane do ``---``. Sam ruch metadanych tego nie zapewni: przy
  zatrzymanym odtwarzaniu nic się nie zmienia przez wiele minut;
- **brak portu nie jest błędem** — moduł loguje to raz na poziomie INFO
  i czeka, próbując dalej z narastającym opóźnieniem. Wyświetlacz może
  być odłączony albo zasilany osobno z +15 i wstać przed komputerem.

Wykrywanie portu: najpierw stała ścieżka z reguły udev
(``/dev/ttyACM_display``, patrz ``docs/WYSWIETLACZ_ESP32_1V8.md`` §Sygnały),
a gdy jej nie ma — skan ``/dev/ttyACM*``. Skanowany port jest
**weryfikowany handshake'iem PING/PONG**, bo na ``/dev/ttyACM*`` siedzi już
Pro Micro (``arduino/rotary_encoder``, ATmega32U4 — jedyna z trzech płytek
z natywnym USB; oba Nano idą przez CH340 na ``/dev/ttyUSB*``, więc skan ich
nie dotyka). Ścieżce z udev ufamy bez pytania. Port, który milczy trzy razy
z rzędu, znika z puli do czasu przepięcia kabla: czytanie z cudzego portu
**podkrada bajty** temu, kto go trzyma — a ``/dev/ttyACM0`` trzyma otwarty
``src/input/arduino_serial.py``, więc każdy handshake to sekunda z okładem
zgubionych zdarzeń SWC i telemetrii.
"""

import math
import os
import re
import threading
import time
from typing import Any, Optional

from src.core.logger import get_logger

log = get_logger("dashboard.esp32_link")

try:
    import serial
    _SERIAL_AVAILABLE = True
except ImportError:
    _SERIAL_AVAILABLE = False


# Stała ścieżka z reguły udev (VID:PID natywnego USB Espressifa 303a:1001)
DEFAULT_PORT = "/dev/ttyACM_display"
# Fallback, gdy reguły udev nie ma — kolejność jak w find_arduino_serial()
SCAN_PORTS = ["/dev/ttyACM0", "/dev/ttyACM1", "/dev/ttyACM2", "/dev/ttyACM3"]
BAUD_RATE = 115200

PING_INTERVAL_S = 2.0        # ESP32 uznaje BCM za offline po 5 s ciszy
TICK_S = 0.2                 # co tyle worker sprawdza zmiany stanu
SERIAL_TIMEOUT_S = 0.3       # readline() na porcie
HANDSHAKE_TIMEOUT_S = 1.5    # ile czekamy na PONG przy weryfikacji portu
# Ile razy zagadujemy do obcego portu, zanim odpuścimy. Na /dev/ttyACM*
# w aucie jest jeszcze Pro Micro (arduino/rotary_encoder) — i to ten sam
# węzeł, który czyta w kółko src/input/arduino_serial.py. Handshake
# READLINE'uje przez HANDSHAKE_TIMEOUT_S z tego samego portu, więc
# PODKRADA MU BAJTY: każda próba to sekunda z okładem zgubionych linii
# SWC/telemetrii. Bez limitu skan robiłby to co backoff, dopóki
# wyświetlacza nie ma w aucie.
HANDSHAKE_ATTEMPTS = 3
RX_BUFFER_MAX = 256          # sufit na sklejanie odpowiedzi bez '\n'
# Narastające opóźnienie ponownych prób. Pierwsza próba po utracie portu
# jest szybka (przepięty kabel), potem schodzimy do co pół minuty.
RECONNECT_BACKOFF_S = (1.0, 2.0, 5.0, 10.0, 30.0)

# Tytuł z tagów ID3 potrafi mieć kilkaset znaków, a ekran mieści ~2 × 14 —
# wielokropek dokłada font_fit() na ESP32. Budżety są w BAJTACH i lustrzane
# do buforów firmware'u (PROTO_TITLE_MAX 96, PROTO_ARTIST_MAX 64
# w arduino/esp32_display/protocol.h), minus bajt na NUL. Liczenie w znakach
# nie wystarczy: "ą" to dwa bajty, więc 64 znaki z ogonkami przepełniłyby
# bufor tytułu i ESP32 uciąłby ogon po swojemu.
MAX_TITLE_BYTES = 95
MAX_ARTIST_BYTES = 63
MAX_SPEED_KMH = 320

# Znaki sterujące rozbiłyby linię protokołu (albo zawiesiły parser na
# ESP32), a i tak żadnego z nich nie ma w foncie bitmapowym.
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")

# audio.source_changed publikuje wartości z AudioSource (src/audio/source_manager.py)
_SOURCE_MAP = {
    "bluetooth": "BT",
    "android_auto": "AA",
}

# Kolejność wypychania stanu. TITLE/ARTIST przed PLAY i licznikami, żeby
# ESP32 zdążył zbudować ekran zanim ruszy pasek postępu.
KEY_ORDER = ("SRC", "TITLE", "ARTIST", "PLAY", "DUR", "POS", "CRUISE", "SETSPD")


def find_display_ports(preferred: Optional[str] = DEFAULT_PORT,
                       scan: bool = True) -> list[str]:
    """Kandydaci na port wyświetlacza, w kolejności prób.

    Najpierw stała ścieżka z konfiguracji/udev, potem skan ``ttyACM*``
    z pominięciem duplikatów. Zwracamy tylko ścieżki, które istnieją —
    otwieranie nieistniejącego węzła to strata czasu przy każdej próbie
    połączenia.
    """
    candidates: list[str] = []
    if preferred:
        candidates.append(preferred)
    if scan:
        candidates.extend(p for p in SCAN_PORTS if p not in candidates)
    return [p for p in candidates if os.path.exists(p)]


def clean_text(value: Any, max_bytes: int = MAX_TITLE_BYTES) -> str:
    """Tekst nadający się do wpisania w jedną linię protokołu.

    Obcinamy po zakodowaniu do UTF-8, na granicy znaku: ``errors="ignore"``
    przy dekodowaniu zjada niepełną sekwencję na końcu, więc ESP32 nigdy
    nie dostanie połówki polskiej litery.
    """
    if value is None:
        return ""
    text = value if isinstance(value, str) else str(value)
    text = _CONTROL_RE.sub(" ", text).strip()
    # Kodujemy z errors="ignore" i wracamy przez dekodowanie ZAWSZE, nie
    # tylko przy obcinaniu. Tag ID3 potrafi przynieść samotny surogat
    # (\udcff po nieudanym dekodowaniu w innym module) — bez tego
    # str.encode() rzuciłby wyjątek: albo tutaj, gubiąc całą aktualizację
    # tytułu, albo później w _write(), gdzie wyglądałby jak utrata portu
    # i zerwałby dobre połączenie.
    encoded = text.encode("utf-8", errors="ignore")[:max_bytes]
    return encoded.decode("utf-8", errors="ignore").rstrip()


def to_flag(value: Any) -> str:
    """Wartość logiczna jako ``0``/``1``.

    Uwaga na napisy: ``bool("0")`` to ``True``, a przez magistralę
    potrafi przyjść i ``"playing"``, i ``False``.
    """
    if isinstance(value, str):
        return "1" if value.strip().lower() in ("1", "true", "yes", "on", "playing") else "0"
    return "1" if value else "0"


def to_seconds(value: Any, millis: bool = True) -> str:
    """Czas w sekundach jako napis.

    ``bt.media_position`` / ``bt.media_duration`` niosą **milisekundy**
    (AVRCP przez BlueZ, tak samo DemoMediaGenerator), a protokół chce
    sekund — stąd domyślne ``millis=True``.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "0"
    if not math.isfinite(number) or number < 0:
        return "0"
    if millis:
        number /= 1000.0
    return str(int(number))


def to_source(value: Any) -> str:
    """Kod źródła dźwięku dla linii ``SRC``."""
    key = value.strip().lower() if isinstance(value, str) else ""
    return _SOURCE_MAP.get(key, "---")


def to_speed(value: Any) -> str:
    """Zadana prędkość tempomatu; pusto, gdy nieznana."""
    if value is None or value == "":
        return ""
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        return ""
    if not 0 <= number <= MAX_SPEED_KMH:
        number = max(0, min(MAX_SPEED_KMH, number))
    return str(number)


class Esp32DisplayLink:
    """Pisze protokół wyświetlacza do portu szeregowego ESP32.

    Subskrybuje
    -----------
    - ``bt.media_title`` / ``bt.media_artist`` (str) → ``TITLE`` / ``ARTIST``
    - ``bt.media_playing`` (bool) → ``PLAY``
    - ``bt.media_position`` / ``bt.media_duration`` (int, ms) → ``POS`` / ``DUR``
    - ``vehicle.cruise`` (bool) → ``CRUISE``
    - ``vehicle.cruise_set_speed`` (int km/h) → ``SETSPD``
    - ``audio.source_changed`` (str) → ``SRC``

    Nic nie publikuje — ruch jest jednokierunkowy, z portu czytamy tylko
    ``PONG`` i ``READY``.
    """

    def __init__(self, config, event_bus, hal=None):
        self.config = config
        self.bus = event_bus
        self.hal = hal

        self._preferred_port = config.get("esp32_display.port", DEFAULT_PORT)
        self._scan = bool(config.get("esp32_display.scan", True))
        self._baud = int(config.get("esp32_display.baudrate", BAUD_RATE))
        self._ping_interval = float(
            config.get("esp32_display.ping_interval", PING_INTERVAL_S))
        # "ms" albo "s" — awaryjny przełącznik na wypadek, gdyby kiedyś
        # ktoś zaczął publikować pozycję w sekundach. Rozpoznajemy kilka
        # zapisów sekund, bo pomyłka kosztuje tysiąckrotnie zły pasek
        # postępu, a nie komunikat o błędzie.
        unit = str(config.get("esp32_display.time_unit", "ms")).strip().lower()
        self._millis = unit not in ("s", "sec", "secs", "second", "seconds")

        self._state: dict[str, str] = {
            "SRC": "---",
            "TITLE": "",
            "ARTIST": "",
            "PLAY": "0",
            "POS": "0",
            "DUR": "0",
            "CRUISE": "0",
            "SETSPD": "",
        }
        self._sent: dict[str, str] = {}
        self._lock = threading.Lock()
        self._write_lock = threading.Lock()

        self._serial = None
        self._port: Optional[str] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._last_ping = 0.0
        self._backoff_idx = 0
        self._logged_missing = False
        self._rx = bytearray()          # niedokończona linia z portu
        # ścieżka -> ile razy nie odpowiedziała na PING (patrz HANDSHAKE_ATTEMPTS)
        self._rejected: dict[str, int] = {}

        # temat na magistrali -> (klucz protokołu, konwerter)
        self._topics = {
            "bt.media_title": ("TITLE", lambda v: clean_text(v, MAX_TITLE_BYTES)),
            "bt.media_artist": ("ARTIST", lambda v: clean_text(v, MAX_ARTIST_BYTES)),
            "bt.media_playing": ("PLAY", to_flag),
            "bt.media_position": ("POS", lambda v: to_seconds(v, self._millis)),
            "bt.media_duration": ("DUR", lambda v: to_seconds(v, self._millis)),
            "vehicle.cruise": ("CRUISE", to_flag),
            "vehicle.cruise_set_speed": ("SETSPD", to_speed),
            "audio.source_changed": ("SRC", to_source),
        }
        for topic in self._topics:
            self.bus.subscribe(topic, self._on_event)
            # Magistrala pamięta ostatnią wartość każdego tematu. Bez tego
            # moduł wystartowany po reszcie (albo po restarcie) wysłałby
            # pusty zrzut i czekał na następną zmianę utworu.
            last = self.bus.get_last(topic)
            if last is not None:
                self._apply(topic, last[0])

    @property
    def available(self) -> bool:
        """Czy port jest w tej chwili otwarty."""
        return self._serial is not None

    # ------------------------------------------------------------------
    # Cykl życia
    # ------------------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None:
            return
        if not _SERIAL_AVAILABLE:
            log.info("ESP32 display: brak pyserial — moduł bezczynny")
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._worker, daemon=True,
                                        name="esp32-display")
        self._thread.start()
        log.info("ESP32 display: most uruchomiony (port docelowy %s)",
                 self._preferred_port)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._drop_port()

    # ------------------------------------------------------------------
    # Zdarzenia z magistrali → stan
    # ------------------------------------------------------------------
    def _set(self, key: str, value: str) -> None:
        with self._lock:
            self._state[key] = value

    def _on_event(self, topic, value, timestamp) -> None:
        self._apply(topic, value)

    def _apply(self, topic: str, value: Any) -> None:
        key, convert = self._topics[topic]
        try:
            self._set(key, convert(value))
        except Exception:
            # Konwertery same łykają śmieci; to ostatnia siatka, żeby jedna
            # dziwna wartość na magistrali nie ubiła subskrypcji.
            log.debug("ESP32 display: nie umiem przetworzyć %s=%r", topic, value)

    # ------------------------------------------------------------------
    # Stan → linie protokołu
    # ------------------------------------------------------------------
    def pending_lines(self) -> list[str]:
        """Linie, które trzeba wysłać, żeby ESP32 nadążył za stanem.

        Puste ``_sent`` (start, reconnect, READY) daje pełny zrzut stanu;
        potem lecą wyłącznie zmienione klucze.
        """
        with self._lock:
            lines = []
            for key in KEY_ORDER:
                value = self._state[key]
                if self._sent.get(key) != value:
                    self._sent[key] = value
                    lines.append(f"{key}:{value}\n")
            return lines

    # ------------------------------------------------------------------
    # Port szeregowy
    # ------------------------------------------------------------------
    def _worker(self) -> None:
        while not self._stop.is_set():
            if self._serial is None:
                # Opóźnienie bierzemy PRZED próbą: _reconnect() sam podbija
                # licznik, więc czytane po nim dawałoby 2 s zamiast 1 s
                # przy pierwszym podejściu (przepięty kabel wraca od razu).
                delay = RECONNECT_BACKOFF_S[self._backoff_idx]
                self._reconnect()
                if self._serial is None:
                    self._stop.wait(delay)
                    continue
            try:
                self.tick()
            except Exception as exc:
                log.warning("ESP32 display: utrata portu %s (%s)", self._port, exc)
                self._drop_port()
                continue
            self._stop.wait(TICK_S)

    def tick(self) -> None:
        """Jeden obrót pętli: zmiany, keepalive, odpowiedzi.

        Bez portu nie robi nic — inaczej ``pending_lines()`` odhaczyłoby
        stan jako wysłany i po podłączeniu wyświetlacza zostałby pusty
        ekran aż do następnej zmiany utworu.
        """
        if self._serial is None:
            return
        for line in self.pending_lines():
            self._write(line)
        now = time.monotonic()
        if now - self._last_ping >= self._ping_interval:
            self._last_ping = now
            self._write("PING\n")
        self._read_replies()

    def _write(self, line: str) -> bool:
        port = self._serial
        if port is None:
            return False
        with self._write_lock:
            port.write(line.encode("utf-8"))
        log.debug("ESP32 <- %s", line.rstrip("\n"))
        return True

    def _read_replies(self) -> None:
        port = self._serial
        if port is None:
            return
        # Pętla ograniczona, żeby gadatliwa płytka nie zablokowała ticka.
        for _ in range(8):
            try:
                waiting = port.in_waiting
            except AttributeError:
                return          # port bez in_waiting — nie ma czego czytać
            # OSError (a więc i serial.SerialException) NIE jest tu łykany.
            # Tak właśnie objawia się wyrwany kabel, gdy akurat nic nie
            # wysyłamy: wyjątek leci do _worker(), ten zamyka port i wraca
            # do szukania wyświetlacza. Zjadany zostawiałby most w stanie
            # "podłączony" na zawsze, bo zapis do martwego portu potrafi
            # przez chwilę udawać, że działa.
            if not waiting:
                return
            raw = port.readline()
            if not raw:
                return
            self._feed_rx(raw)

    def _feed_rx(self, raw: bytes) -> None:
        """Skleja odpowiedzi z bajtów — ``readline()`` potrafi oddać kawałek.

        Przy timeoucie portu (albo gdy USB podzieli pakiet) ``READY\\n``
        wraca jako ``REA`` + ``DY\\n``. Bez sklejania przepadłyby oba
        kawałki, a razem z nimi jedyny sygnał, że płytka wstała od nowa
        i czeka na pełny zrzut stanu — ekran zostałby z metadanymi
        sprzed resetu aż do zmiany utworu.
        """
        self._rx += raw
        if len(self._rx) > RX_BUFFER_MAX:
            # Ktoś sypie bajtami bez '\n' — bufor nie może rosnąć bez końca.
            del self._rx[:-RX_BUFFER_MAX]
        while True:
            idx = self._rx.find(b"\n")
            if idx < 0:
                return
            line = bytes(self._rx[:idx])
            del self._rx[:idx + 1]
            self._handle_reply(line.decode("utf-8", errors="ignore").strip())

    def _handle_reply(self, line: str) -> None:
        if not line:
            return
        if line == "PONG":
            log.debug("ESP32 -> PONG")
        elif line == "READY":
            # Płytka wstała od nowa — jej kopia stanu jest pusta.
            log.info("ESP32 display: READY, wysyłam pełny stan")
            with self._lock:
                self._sent.clear()
        else:
            log.debug("ESP32 -> %s", line)

    def _reconnect(self) -> None:
        ports = find_display_ports(self._preferred_port, self._scan)
        # Węzeł, który zniknął z /dev, po ponownym pojawieniu się może być
        # już czym innym (to właśnie robi przepięcie kabla) — kasujemy
        # o nim pamięć i dajemy mu pełną pulę prób.
        for path in list(self._rejected):
            if path not in ports:
                del self._rejected[path]
        if not ports:
            if not self._logged_missing:
                log.info("ESP32 display: brak portu (%s) — tryb bezczynny",
                         self._preferred_port)
                self._logged_missing = True
            self._bump_backoff()
            return

        for path in ports:
            # Ścieżce z udev ufamy; skanowany port musi się przedstawić,
            # bo równie dobrze może to być Pro Micro (/dev/ttyACM0).
            verify = path != self._preferred_port
            if verify and self._rejected.get(path, 0) >= HANDSHAKE_ATTEMPTS:
                continue        # już się nie odezwał — nie zaczepiajmy go w kółko
            port = self._open(path, verify)
            if port is None:
                continue
            self._serial = port
            self._port = path
            self._rejected.pop(path, None)
            self._logged_missing = False
            self._backoff_idx = 0
            self._last_ping = 0.0
            with self._lock:
                self._sent.clear()
            log.info("ESP32 display podłączony: %s", path)
            return

        self._bump_backoff()

    def _open(self, path: str, verify: bool):
        try:
            port = serial.Serial(path, self._baud, timeout=SERIAL_TIMEOUT_S)
        except Exception as exc:
            log.debug("ESP32 display: %s niedostępny (%s)", path, exc)
            return None
        if not verify:
            return port
        try:
            if self._handshake(port):
                return port
            log.debug("ESP32 display: %s nie odpowiedział PONG — pomijam", path)
            self._reject(path)
        except Exception as exc:
            log.debug("ESP32 display: handshake na %s nieudany (%s)", path, exc)
            self._reject(path)
        try:
            port.close()
        except Exception:
            pass
        return None

    def _handshake(self, port) -> bool:
        """Sprawdza, czy po drugiej stronie jest nasz wyświetlacz."""
        port.write(b"PING\n")
        deadline = time.monotonic() + HANDSHAKE_TIMEOUT_S
        while time.monotonic() < deadline:
            raw = port.readline()
            if not raw:
                continue
            if raw.decode("utf-8", errors="ignore").strip() in ("PONG", "READY"):
                return True
        return False

    def _reject(self, path: str) -> None:
        """Odnotowuje port, który nie przedstawił się jako wyświetlacz."""
        count = self._rejected.get(path, 0) + 1
        self._rejected[path] = count
        if count == HANDSHAKE_ATTEMPTS:
            log.info("ESP32 display: %s nie jest wyświetlaczem (%d próby) "
                     "— przestaję go zaczepiać", path, count)

    def _drop_port(self) -> None:
        port, self._serial = self._serial, None
        self._port = None
        self._rx.clear()
        if port is not None:
            try:
                port.close()
            except Exception:
                pass
        # Po ponownym podłączeniu ESP32 musi dostać pełny stan.
        with self._lock:
            self._sent.clear()
        self._backoff_idx = 0

    def _bump_backoff(self) -> None:
        if self._backoff_idx < len(RECONNECT_BACKOFF_S) - 1:
            self._backoff_idx += 1


def start_esp32_link(config, event_bus, hal=None, **kwargs):
    """Punkt wejścia rejestru modułów (modules_catalog: ``esp32_display``)."""
    link = Esp32DisplayLink(config, event_bus, hal)
    link.start()
    return link
