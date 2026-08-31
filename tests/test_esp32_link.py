"""Testy mostu do wyświetlacza ESP32 (src/dashboard/esp32_link.py).

Cały ruch idzie przez atrapę portu — żaden test nie otwiera prawdziwego
``/dev/ttyACM*``. ``Esp32DisplayLink`` konstruuje się bez ``start()``,
więc wątek roboczy nigdy nie rusza, a ``tick()`` wołamy ręcznie.
"""

import pytest

import src.dashboard.esp32_link as esp32_link
from src.core.event_bus import EventBus
from src.dashboard.esp32_link import (
    Esp32DisplayLink,
    clean_text,
    find_display_ports,
    to_flag,
    to_seconds,
    to_source,
    to_speed,
)


class _Config:
    """Konfiguracja z domyślnymi wartościami, z opcjonalną nadpiską."""

    def __init__(self, **overrides):
        self._data = overrides

    def get(self, key, default=None):
        return self._data.get(key, default)


class _FakePort:
    """Atrapa serial.Serial: zbiera zapisy, oddaje zakolejkowane linie."""

    def __init__(self, replies=(), fail_on_write=False):
        self.written = bytearray()
        self.closed = False
        self.fail_on_write = fail_on_write
        self._inbox = bytearray()
        for line in replies:
            self._inbox += (line + "\n").encode("utf-8")

    # --- API używane przez moduł ---
    def write(self, data):
        if self.fail_on_write:
            raise OSError("port zniknął")
        self.written += data
        return len(data)

    @property
    def in_waiting(self):
        return len(self._inbox)

    def readline(self):
        idx = self._inbox.find(b"\n")
        if idx < 0:
            out, self._inbox = bytes(self._inbox), bytearray()
            return out
        out = bytes(self._inbox[:idx + 1])
        del self._inbox[:idx + 1]
        return out

    def close(self):
        self.closed = True

    # --- pomocnicze dla asercji ---
    @property
    def lines(self):
        text = self.written.decode("utf-8")
        return [ln for ln in text.split("\n") if ln]


@pytest.fixture()
def link():
    """Most na świeżej magistrali, bez portu."""
    return Esp32DisplayLink(_Config(), EventBus())


@pytest.fixture()
def wired(link):
    """Most z podpiętą atrapą portu i pustą historią wysyłek."""
    port = _FakePort()
    link._serial = port
    return link, port


def _sent_map(port):
    return dict(ln.split(":", 1) for ln in port.lines if ":" in ln)


class TestLineFormatting:
    def test_first_flush_sends_full_snapshot(self, link):
        lines = link.pending_lines()
        assert lines == [
            "SRC:---\n", "TITLE:\n", "ARTIST:\n", "PLAY:0\n",
            "DUR:0\n", "POS:0\n", "CRUISE:0\n", "SETSPD:\n",
        ]

    def test_key_value_shape(self, wired):
        link, port = wired
        link.bus.publish("bt.media_title", "Nightcall")
        link.bus.publish("bt.media_artist", "Kavinsky")
        link.tick()
        sent = _sent_map(port)
        assert sent["TITLE"] == "Nightcall"
        assert sent["ARTIST"] == "Kavinsky"

    def test_every_line_ends_with_newline(self, link):
        link.bus.publish("bt.media_title", "Nightcall")
        assert all(ln.endswith("\n") for ln in link.pending_lines())

    def test_playing_flag(self, link):
        link.pending_lines()
        link.bus.publish("bt.media_playing", True)
        assert link.pending_lines() == ["PLAY:1\n"]
        link.bus.publish("bt.media_playing", False)
        assert link.pending_lines() == ["PLAY:0\n"]

    def test_position_and_duration_are_seconds(self, link):
        link.pending_lines()
        link.bus.publish("bt.media_duration", 258000)
        link.bus.publish("bt.media_position", 87500)
        assert link.pending_lines() == ["DUR:258\n", "POS:87\n"]

    def test_time_unit_seconds_when_configured(self):
        link = Esp32DisplayLink(_Config(**{"esp32_display.time_unit": "s"}), EventBus())
        link.pending_lines()
        link.bus.publish("bt.media_duration", 258)
        assert link.pending_lines() == ["DUR:258\n"]

    @pytest.mark.parametrize("unit", ["s", "S", " sec ", "seconds"])
    def test_seconds_unit_spelling_is_forgiving(self, unit):
        # Pomyłka w zapisie jednostki dawałaby pasek postępu tysiąc razy
        # za krótki, i to bez jednego słowa w logu.
        link = Esp32DisplayLink(_Config(**{"esp32_display.time_unit": unit}), EventBus())
        link.pending_lines()
        link.bus.publish("bt.media_duration", 258)
        assert link.pending_lines() == ["DUR:258\n"]

    def test_cruise_and_set_speed(self, link):
        link.pending_lines()
        link.bus.publish("vehicle.cruise", True)
        link.bus.publish("vehicle.cruise_set_speed", 130)
        assert link.pending_lines() == ["CRUISE:1\n", "SETSPD:130\n"]

    def test_set_speed_stays_empty_when_never_published(self, link):
        # vehicle.cruise_set_speed nie ma jeszcze producenta w repo —
        # ESP32 dostaje pustą wartość i rysuje "---".
        link.bus.publish("vehicle.cruise", True)
        assert "SETSPD:\n" in link.pending_lines()

    def test_source_mapping(self, link):
        link.pending_lines()
        link.bus.publish("audio.source_changed", "bluetooth")
        assert link.pending_lines() == ["SRC:BT\n"]
        link.bus.publish("audio.source_changed", "android_auto")
        assert link.pending_lines() == ["SRC:AA\n"]
        link.bus.publish("audio.source_changed", "fm_radio")
        assert link.pending_lines() == ["SRC:---\n"]


class TestOnlyChangesAreSent:
    def test_second_tick_sends_only_ping(self, wired):
        link, port = wired
        link.tick()
        first = len(port.lines)
        assert first == len(esp32_link.KEY_ORDER) + 1  # zrzut stanu + PING
        link._last_ping = 0.0  # wymuś kolejny keepalive
        link.tick()
        assert port.lines[first:] == ["PING"]

    def test_repeated_same_value_not_resent(self, link):
        link.pending_lines()
        link.bus.publish("bt.media_title", "Nightcall")
        assert link.pending_lines() == ["TITLE:Nightcall\n"]
        link.bus.publish("bt.media_title", "Nightcall")
        assert link.pending_lines() == []

    def test_position_ticking_within_same_second_is_silent(self, link):
        link.pending_lines()
        link.bus.publish("bt.media_position", 87000)
        assert link.pending_lines() == ["POS:87\n"]
        link.bus.publish("bt.media_position", 87400)
        assert link.pending_lines() == []
        link.bus.publish("bt.media_position", 88000)
        assert link.pending_lines() == ["POS:88\n"]

    def test_only_changed_key_is_sent(self, link):
        link.pending_lines()
        link.bus.publish("bt.media_title", "A")
        link.bus.publish("bt.media_artist", "B")
        link.pending_lines()
        link.bus.publish("bt.media_artist", "C")
        assert link.pending_lines() == ["ARTIST:C\n"]


class TestTextSanitising:
    def test_newline_cannot_split_a_line(self, link):
        link.pending_lines()
        link.bus.publish("bt.media_title", "Zła\nlinia")
        lines = link.pending_lines()
        assert lines == ["TITLE:Zła linia\n"]
        assert lines[0].count("\n") == 1

    def test_carriage_return_and_tab_removed(self):
        assert clean_text("a\r\nb\tc") == "a  b c"

    def test_leading_trailing_whitespace_stripped(self):
        assert clean_text("  Nightcall  ") == "Nightcall"

    def test_title_truncated(self, link):
        link.pending_lines()
        link.bus.publish("bt.media_title", "x" * 200)
        line = link.pending_lines()[0]
        assert line == "TITLE:" + "x" * esp32_link.MAX_TITLE_BYTES + "\n"

    def test_artist_has_its_own_shorter_budget(self, link):
        link.pending_lines()
        link.bus.publish("bt.media_artist", "y" * 200)
        assert link.pending_lines()[0] == "ARTIST:" + "y" * esp32_link.MAX_ARTIST_BYTES + "\n"

    def test_non_string_values_survive(self):
        assert clean_text(None) == ""
        assert clean_text(1234) == "1234"

    def test_utf8_polish_letters_go_out_as_utf8(self, wired):
        link, port = wired
        link.bus.publish("bt.media_title", "Zażółć gęślą jaźń")
        link.tick()
        assert b"TITLE:Za\xc5\xbc\xc3\xb3\xc5\x82\xc4\x87" in port.written
        assert _sent_map(port)["TITLE"] == "Zażółć gęślą jaźń"

    def test_utf8_title_cut_on_a_codepoint_boundary(self, link):
        # Budżet jest w bajtach (bufory firmware'u), a "ą" ma dwa — cięcie
        # nie może zostawić połówki znaku.
        link.bus.publish("bt.media_title", "ą" * 100)
        title = _sent_map_from_lines(link.pending_lines())["TITLE"]
        assert title == "ą" * (esp32_link.MAX_TITLE_BYTES // 2)
        assert len(title.encode("utf-8")) <= esp32_link.MAX_TITLE_BYTES

    @pytest.mark.parametrize("text", ["ą" * 100, "Zażółć " * 40, "x" * 300, "łódź…" * 30])
    def test_values_always_fit_the_firmware_buffers(self, link, text):
        # PROTO_TITLE_MAX / PROTO_ARTIST_MAX w arduino/esp32_display/protocol.h
        link.bus.publish("bt.media_title", text)
        link.bus.publish("bt.media_artist", text)
        sent = _sent_map_from_lines(link.pending_lines())
        assert len(sent["TITLE"].encode("utf-8")) < 96
        assert len(sent["ARTIST"].encode("utf-8")) < 64


def _sent_map_from_lines(lines):
    return dict(ln.rstrip("\n").split(":", 1) for ln in lines)


class TestBusWiring:
    def test_state_seeded_from_last_bus_values(self):
        # Moduł wstający po reszcie systemu musi zobaczyć to, co już poszło
        # przez magistralę — inaczej ESP32 dostaje pusty ekran.
        bus = EventBus()
        bus.publish("bt.media_title", "Nightcall")
        bus.publish("vehicle.cruise", True)
        link = Esp32DisplayLink(_Config(), bus)
        sent = _sent_map_from_lines(link.pending_lines())
        assert sent["TITLE"] == "Nightcall"
        assert sent["CRUISE"] == "1"

    def test_broken_value_does_not_kill_the_subscription(self, link):
        class _Explodes:
            def __str__(self):
                raise RuntimeError("boom")

        link.pending_lines()
        link.bus.publish("bt.media_title", _Explodes())
        link.bus.publish("bt.media_artist", "Kavinsky")
        assert link.pending_lines() == ["ARTIST:Kavinsky\n"]

    def test_unknown_topics_are_not_subscribed(self, link):
        assert set(link._topics) == {
            "bt.media_title", "bt.media_artist", "bt.media_playing",
            "bt.media_position", "bt.media_duration",
            "vehicle.cruise", "vehicle.cruise_set_speed",
            "audio.source_changed",
        }


class TestValueHelpers:
    @pytest.mark.parametrize("value,expected", [
        (True, "1"), (False, "0"), (None, "0"),
        ("1", "1"), ("0", "0"), ("playing", "1"), ("paused", "0"),
    ])
    def test_flag(self, value, expected):
        assert to_flag(value) == expected

    @pytest.mark.parametrize("value,expected", [
        (258000, "258"), (0, "0"), (-5000, "0"),
        ("87000", "87"), (None, "0"), ("bzdura", "0"), (float("inf"), "0"),
    ])
    def test_seconds(self, value, expected):
        assert to_seconds(value) == expected

    @pytest.mark.parametrize("value,expected", [
        ("bluetooth", "BT"), ("android_auto", "AA"), ("BlueTooth", "BT"),
        ("fm_radio", "---"), ("", "---"), (None, "---"),
    ])
    def test_source(self, value, expected):
        assert to_source(value) == expected

    @pytest.mark.parametrize("value,expected", [
        (130, "130"), ("130", "130"), (130.4, "130"),
        (None, ""), ("", ""), ("bzdura", ""), (-10, "0"), (9999, "320"),
    ])
    def test_speed(self, value, expected):
        assert to_speed(value) == expected


class TestPortDiscovery:
    def test_fixed_path_wins(self, monkeypatch):
        monkeypatch.setattr(esp32_link.os.path, "exists", lambda p: True)
        assert find_display_ports()[0] == esp32_link.DEFAULT_PORT

    def test_scan_used_when_fixed_path_missing(self, monkeypatch):
        monkeypatch.setattr(esp32_link.os.path, "exists",
                            lambda p: p == "/dev/ttyACM1")
        assert find_display_ports() == ["/dev/ttyACM1"]

    def test_scan_can_be_disabled(self, monkeypatch):
        monkeypatch.setattr(esp32_link.os.path, "exists",
                            lambda p: p == "/dev/ttyACM1")
        assert find_display_ports(scan=False) == []

    def test_nothing_present(self, monkeypatch):
        monkeypatch.setattr(esp32_link.os.path, "exists", lambda p: False)
        assert find_display_ports() == []


class TestNoPort:
    def test_writes_are_dropped_not_raised(self, link):
        assert link._write("TITLE:x\n") is False

    def test_tick_without_port_is_silent(self, link):
        link.tick()  # nie może rzucić
        assert not link.available

    def test_start_without_pyserial_stays_idle(self, link, monkeypatch):
        monkeypatch.setattr(esp32_link, "_SERIAL_AVAILABLE", False)
        link.start()
        assert link._thread is None
        link.stop()

    def test_events_keep_updating_state_without_port(self, link):
        link.bus.publish("bt.media_title", "Nightcall")
        link.tick()
        # Stan czeka na port — po podłączeniu poleci pełny zrzut.
        assert _sent_map_from_lines(link.pending_lines())["TITLE"] == "Nightcall"

    def test_reconnect_gives_up_gracefully(self, link, monkeypatch):
        monkeypatch.setattr(esp32_link, "find_display_ports", lambda *a, **k: [])
        link._reconnect()
        assert not link.available
        assert link._backoff_idx == 1


class TestReconnect:
    def test_write_failure_drops_the_port(self, link):
        port = _FakePort(fail_on_write=True)
        link._serial = port
        with pytest.raises(OSError):
            link.tick()
        # pętla robocza łapie wyjątek i zamyka port
        link._drop_port()
        assert not link.available
        assert port.closed

    def test_reconnect_resends_full_snapshot(self, wired):
        link, port = wired
        link.bus.publish("bt.media_title", "Nightcall")
        link.tick()
        link._drop_port()
        new_port = _FakePort()
        link._serial = new_port
        link.tick()
        sent = _sent_map(new_port)
        assert set(sent) == set(esp32_link.KEY_ORDER)
        assert sent["TITLE"] == "Nightcall"

    def test_ready_from_esp32_resends_full_snapshot(self, link):
        port = _FakePort(replies=["READY"])
        link._serial = port
        link.tick()
        before = len(port.lines)
        link._last_ping = 0.0
        link.tick()
        resent = [ln for ln in port.lines[before:] if ln != "PING"]
        assert len(resent) == len(esp32_link.KEY_ORDER)

    def test_pong_does_not_trigger_resend(self, link):
        port = _FakePort(replies=["PONG"])
        link._serial = port
        link.tick()
        before = len(port.lines)
        link._last_ping = 0.0
        link.tick()
        assert port.lines[before:] == ["PING"]

    def test_backoff_grows_and_is_capped(self, link):
        for _ in range(20):
            link._bump_backoff()
        assert link._backoff_idx == len(esp32_link.RECONNECT_BACKOFF_S) - 1

    def test_backoff_resets_after_port_loss(self, wired):
        link, _port = wired
        link._backoff_idx = 3
        link._drop_port()
        assert link._backoff_idx == 0

    def test_scanned_port_must_answer_pong(self, link, monkeypatch):
        good = _FakePort(replies=["PONG"])
        bad = _FakePort()  # milczy — to nie nasz wyświetlacz
        opened = {"/dev/ttyACM0": bad, "/dev/ttyACM1": good}
        monkeypatch.setattr(esp32_link, "find_display_ports",
                            lambda *a, **k: ["/dev/ttyACM0", "/dev/ttyACM1"])
        monkeypatch.setattr(esp32_link, "HANDSHAKE_TIMEOUT_S", 0.05)
        monkeypatch.setattr(esp32_link, "serial",
                            type("_S", (), {"Serial": staticmethod(
                                lambda path, baud, timeout: opened[path])}))
        link._reconnect()
        assert link._serial is good
        assert bad.closed

    def test_fixed_path_is_trusted_without_handshake(self, link, monkeypatch):
        port = _FakePort()  # milczy, ale to ścieżka z udev
        monkeypatch.setattr(esp32_link, "find_display_ports",
                            lambda *a, **k: [esp32_link.DEFAULT_PORT])
        monkeypatch.setattr(esp32_link, "serial",
                            type("_S", (), {"Serial": staticmethod(
                                lambda path, baud, timeout: port)}))
        link._reconnect()
        assert link._serial is port
        assert link._port == esp32_link.DEFAULT_PORT


class TestKeepalive:
    def test_ping_sent_on_first_tick(self, wired):
        link, port = wired
        link.tick()
        assert "PING" in port.lines

    def test_ping_not_repeated_within_interval(self, wired):
        link, port = wired
        link.tick()
        link.tick()
        assert port.lines.count("PING") == 1

    def test_ping_repeats_after_interval(self, wired):
        link, port = wired
        link.tick()
        link._last_ping -= esp32_link.PING_INTERVAL_S
        link.tick()
        assert port.lines.count("PING") == 2


class TestModuleEntry:
    def test_catalog_entry_matches_the_start_function(self):
        from src.core import modules_catalog
        info = modules_catalog.MODULES["esp32_display"]
        assert info["entry"] == ("src.dashboard.esp32_link", "start_esp32_link")
        assert info["default"] is False

    def test_start_without_pyserial_returns_idle_module(self, monkeypatch):
        monkeypatch.setattr(esp32_link, "_SERIAL_AVAILABLE", False)
        mod = esp32_link.start_esp32_link(_Config(), EventBus(), hal=None)
        assert isinstance(mod, Esp32DisplayLink)
        assert not mod.available
        mod.stop()


class _FakeStop:
    """Atrapa ``threading.Event`` — przepuszcza N obrotów ``_worker()``.

    Pozwala sprawdzić pętlę roboczą bez wątku i bez zegara: ``is_set()``
    oddaje ``False`` dokładnie ``rounds`` razy, a każde ``wait()``
    ląduje w ``waits`` zamiast czegokolwiek usypiać.
    """

    def __init__(self, rounds):
        self.rounds = rounds
        self.waits = []

    def is_set(self):
        if self.rounds <= 0:
            return True
        self.rounds -= 1
        return False

    def wait(self, timeout=None):
        self.waits.append(timeout)
        return False

    def set(self):
        self.rounds = 0

    def clear(self):
        pass


class _DeadPort:
    """Port po wyrwaniu kabla: zapis jeszcze udaje, że działa, odczyt nie."""

    def __init__(self):
        self.written = bytearray()
        self.closed = False

    def write(self, data):
        self.written += data
        return len(data)

    @property
    def in_waiting(self):
        raise OSError(5, "Input/output error")

    def readline(self):
        raise OSError(5, "Input/output error")

    def close(self):
        self.closed = True


class TestPortLostMidRun:
    def test_read_error_is_not_swallowed(self, link):
        # Zjedzony OSError zostawiłby most w stanie "podłączony" na zawsze:
        # przy zatrzymanej muzyce jedynym ruchem jest PING, a zapis do
        # martwego portu potrafi przez chwilę udawać, że przechodzi.
        link._serial = _DeadPort()
        with pytest.raises(OSError):
            link.tick()

    def test_worker_drops_the_port_and_goes_back_to_searching(self, link, monkeypatch):
        monkeypatch.setattr(esp32_link, "find_display_ports", lambda *a, **k: [])
        port = _DeadPort()
        link._serial = port
        link._stop = _FakeStop(rounds=2)
        link._worker()
        assert not link.available
        assert port.closed

    def test_first_retry_uses_the_shortest_backoff(self, link, monkeypatch):
        # RECONNECT_BACKOFF_S[0] = 1 s jest dla przepiętego kabla — musi
        # być naprawdę użyte, a nie przeskoczone przez podbicie licznika.
        monkeypatch.setattr(esp32_link, "find_display_ports", lambda *a, **k: [])
        link._stop = _FakeStop(rounds=3)
        link._worker()
        assert link._stop.waits == list(esp32_link.RECONNECT_BACKOFF_S[:3])


class TestPartialReplies:
    def test_ready_split_across_two_reads_is_reassembled(self, link):
        # readline() na porcie z timeoutem potrafi oddać kawałek linii.
        # Zgubione READY to ekran z metadanymi sprzed resetu płytki.
        link._serial = _FakePort()
        link.tick()
        before = len(link._serial.lines)
        link._feed_rx(b"REA")
        link._feed_rx(b"DY\n")
        link._last_ping = 0.0
        link.tick()
        resent = [ln for ln in link._serial.lines[before:] if ln != "PING"]
        assert len(resent) == len(esp32_link.KEY_ORDER)

    def test_crlf_from_arduino_println_is_tolerated(self, link):
        link._serial = _FakePort()
        link.tick()
        before = len(link._serial.lines)
        link._feed_rx(b"READY\r\n")
        link._last_ping = 0.0
        link.tick()
        resent = [ln for ln in link._serial.lines[before:] if ln != "PING"]
        assert len(resent) == len(esp32_link.KEY_ORDER)

    def test_two_replies_in_one_read_are_both_seen(self, link):
        link._serial = _FakePort()
        link.tick()
        before = len(link._serial.lines)
        link._feed_rx(b"PONG\nREADY\n")
        link._last_ping = 0.0
        link.tick()
        resent = [ln for ln in link._serial.lines[before:] if ln != "PING"]
        assert len(resent) == len(esp32_link.KEY_ORDER)

    def test_garbage_without_newline_does_not_grow_forever(self, link):
        link._feed_rx(b"x" * 10000)
        assert len(link._rx) <= esp32_link.RX_BUFFER_MAX

    def test_rx_buffer_cleared_with_the_port(self, link):
        link._serial = _FakePort()
        link._feed_rx(b"REA")
        link._drop_port()
        assert not link._rx


class TestForeignPortsAreLeftAlone:
    """Każde otwarcie /dev/ttyACM* szarpie DTR i resetuje Arduino."""

    @staticmethod
    def _stub_serial(monkeypatch, opens):
        def _open(path, baud, timeout):
            opens.append(path)
            return _FakePort()          # milczy — to nie wyświetlacz
        monkeypatch.setattr(esp32_link, "serial",
                            type("_S", (), {"Serial": staticmethod(_open)}))
        monkeypatch.setattr(esp32_link, "HANDSHAKE_TIMEOUT_S", 0.01)

    def test_silent_port_is_probed_a_bounded_number_of_times(self, link, monkeypatch):
        opens = []
        monkeypatch.setattr(esp32_link, "find_display_ports",
                            lambda *a, **k: ["/dev/ttyACM0"])
        self._stub_serial(monkeypatch, opens)
        for _ in range(6):
            link._reconnect()
        assert opens == ["/dev/ttyACM0"] * esp32_link.HANDSHAKE_ATTEMPTS
        assert not link.available

    def test_replugged_node_gets_a_fresh_chance(self, link, monkeypatch):
        opens = []
        present = ["/dev/ttyACM0"]
        monkeypatch.setattr(esp32_link, "find_display_ports",
                            lambda *a, **k: list(present))
        self._stub_serial(monkeypatch, opens)
        for _ in range(4):
            link._reconnect()
        assert len(opens) == esp32_link.HANDSHAKE_ATTEMPTS
        present.clear()               # kabel wyjęty — węzeł znika z /dev
        link._reconnect()
        present.append("/dev/ttyACM0")  # i z powrotem
        link._reconnect()
        assert len(opens) == esp32_link.HANDSHAKE_ATTEMPTS + 1

    def test_the_display_is_still_found_next_to_a_rejected_port(self, link, monkeypatch):
        good = _FakePort(replies=["PONG"])
        opened = {"/dev/ttyACM0": _FakePort(), "/dev/ttyACM1": good}
        monkeypatch.setattr(esp32_link, "find_display_ports",
                            lambda *a, **k: ["/dev/ttyACM0", "/dev/ttyACM1"])
        monkeypatch.setattr(esp32_link, "HANDSHAKE_TIMEOUT_S", 0.01)
        monkeypatch.setattr(esp32_link, "serial",
                            type("_S", (), {"Serial": staticmethod(
                                lambda path, baud, timeout: opened[path])}))
        for _ in range(5):
            link._reconnect()
        assert link._serial is good

    def test_udev_path_is_never_written_off(self, link, monkeypatch):
        opens = []
        monkeypatch.setattr(esp32_link, "find_display_ports",
                            lambda *a, **k: [esp32_link.DEFAULT_PORT])
        self._stub_serial(monkeypatch, opens)
        for _ in range(5):
            link._reconnect()
            link._drop_port()
        # Ścieżka z reguły udev nie prowadzi do cudzego Arduino, więc
        # limit prób jej nie dotyczy — i tak nie robimy handshake'u.
        assert len(opens) == 5


class TestOddMetadata:
    def test_empty_title_goes_out_as_empty_value(self, link):
        link.pending_lines()
        link.bus.publish("bt.media_title", "Nightcall")
        link.pending_lines()
        link.bus.publish("bt.media_title", "")
        assert link.pending_lines() == ["TITLE:\n"]

    def test_whitespace_only_title_is_empty_too(self, link):
        link.bus.publish("bt.media_title", "Nightcall")
        link.pending_lines()
        link.bus.publish("bt.media_title", "   \t  ")
        assert link.pending_lines() == ["TITLE:\n"]

    def test_characters_outside_the_font_are_passed_through(self, link):
        # Font ma ASCII + polskie znaki; emoji i cyrylicę ESP32 podmienia
        # na '?' — ale linia musi dojść cała i być poprawnym UTF-8.
        link.pending_lines()
        link.bus.publish("bt.media_title", "🎵 Кино 日本語")
        line = link.pending_lines()[0]
        assert line == "TITLE:🎵 Кино 日本語\n"
        line.encode("utf-8")

    def test_lone_surrogate_does_not_lose_the_update(self, link):
        # Tag ID3 przepuszczony przez cudze dekodowanie potrafi przynieść
        # samotny surogat. Kiedyś wysypywał .encode() i tytuł zostawał
        # stary; teraz znika sam znak.
        link.pending_lines()
        link.bus.publish("bt.media_title", "Night\udcffcall")
        assert link.pending_lines() == ["TITLE:Nightcall\n"]

    def test_every_state_value_is_writable_to_the_port(self, wired):
        link, port = wired
        link.bus.publish("bt.media_title", "Zażółć \udcff gęślą 🎵")
        link.bus.publish("bt.media_artist", "\udcfe" * 50)
        link.tick()   # _write() koduje UTF-8; wyjątek = udawana utrata portu
        assert port.written.decode("utf-8")

    def test_very_long_polish_title_fits_and_stays_valid(self, link):
        link.bus.publish("bt.media_title", "Zażółć gęślą jaźń — " * 30)
        title = _sent_map_from_lines(link.pending_lines())["TITLE"]
        raw = title.encode("utf-8")
        assert len(raw) <= esp32_link.MAX_TITLE_BYTES
        assert raw.decode("utf-8") == title   # nie ucięliśmy znaku w pół
