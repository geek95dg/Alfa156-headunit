"""GPS from the phone (src/location/gps.py) and its consumers.

Network tests use real sockets on 127.0.0.1 with port 0 only; ``ip`` and
``/proc/net/route`` are scripted fakes, the serial port is a fake factory.
"""

import random
import socket
import sys
import threading
import time
from datetime import datetime, timezone

import pytest

from src.core.event_bus import EventBus
from src.location import gps as gps_mod
from src.location.gps import (
    DemoGPSGenerator,
    GPSManager,
    NMEAParser,
    _parse_ip_addr,
    _parse_proc_net_route,
    _resolve_sources,
)

POSITION_KEYS = {"lat", "lon", "alt", "altitude", "speed", "heading", "satellites",
                 "fix", "time_utc", "source"}


def nmea(body: str) -> str:
    """``body`` → ``$body*hh`` with the correct checksum."""
    checksum = 0
    for ch in body:
        checksum ^= ord(ch)
    return f"${body}*{checksum:02X}"


RMC_BODY = "GPRMC,123519.50,A,5213.782,N,02100.732,E,010.0,084.4,081126,,,A"
GGA_BODY = "GPGGA,123519.50,5213.782,N,02100.732,E,1,08,0.9,110.5,M,46.9,M,,"
RMC = nmea(RMC_BODY)
GGA = nmea(GGA_BODY)
# Stationary: speed 0, EMPTY course field (what many receivers send parked).
RMC_NO_COURSE = nmea("GPRMC,123520.50,A,5213.782,N,02100.732,E,000.0,,081126,,,A")
GSV = nmea("GPGSV,3,1,11,03,03,111,00,04,15,270,00,06,01,010,00,13,06,292,00")
UBX_BY_ID = "/dev/serial/by-id/usb-u-blox_AG_-_www.u-blox.com_u-blox_7_-_GPS_GNSS_Receiver-if00"
BY_PATH = "/dev/serial/by-path/pci-0000:00:14.0-usb-0:2:1.0-port0"


class FakeClock:
    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


class Recorder:
    """Every event published on a bus, in order."""

    def __init__(self, bus: EventBus) -> None:
        self.events: list = []
        bus.subscribe("*", lambda topic, value, ts: self.events.append((topic, value)))

    def topics(self) -> list:
        return [t for t, _ in self.events]

    def values(self, topic: str) -> list:
        return [v for t, v in self.events if t == topic]


def wait_until(predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def make_manager(gps_cfg=None, platform="x86", **kwargs):
    bus = EventBus()
    rec = Recorder(bus)
    kwargs.setdefault("clock", FakeClock())
    # The default allowed_sources include "pan", which runs `ip -o -4 addr
    # show` — never the real one in a test (the answer would depend on the
    # host's interfaces).
    kwargs.setdefault("ip_runner", FakeRunner(""))
    mgr = GPSManager(bus, {"hardware": {"gps": dict(gps_cfg or {"source": "udp"})}},
                     platform, **kwargs)
    return mgr, bus, rec


class FakeSerial:
    """pyserial stand-in: RMC, a read timeout, GGA, then timeouts."""

    def __init__(self):
        self.lines = [(RMC + "\r\n").encode(), b"", (GGA + "\r\n").encode()]

    def readline(self, size=-1):
        if self.lines:
            return self.lines.pop(0)
        time.sleep(0.01)
        return b""

    def close(self):
        pass


# ── parser ───────────────────────────────────────────────────────────────

class TestParser:
    @pytest.mark.parametrize("talker", ["GP", "GN", "GL", "GA", "BD", "GB", "GQ"])
    def test_every_gnss_talker(self, talker):
        p = NMEAParser()
        assert p.parse(nmea(talker + RMC_BODY[2:])) is True
        assert p.parse(nmea(talker + GGA_BODY[2:])) is True
        assert p.fix_count == 2
        assert p.lat == pytest.approx(52.2297) and p.lon == pytest.approx(21.0122)

    @pytest.mark.parametrize("body", [
        "XXRMC" + RMC_BODY[5:],       # unknown talker
        "GPGSV,3,1,11,03,03,111,00,04,15,270,00,06,01,010,00,13,06,292,00",
        "GPGSA,A,3,04,05,,09,12,,,24,,,,,2.5,1.3,2.1",
        "PGRME,15.0,M,45.0,M,25.0,M",
        "GPRM" + RMC_BODY[5:],        # 4-letter head
    ])
    def test_other_sentences_are_not_accepted(self, body):
        p = NMEAParser()
        assert p.parse(nmea(body)) is False
        assert p.fix_count == 0

    def test_gsv_no_longer_overrides_satellites(self):
        p = NMEAParser()
        assert p.parse(GGA)
        p.parse(nmea("GPGSV,3,1,11,03,03,111,00,04,15,270,00,06,01,010,00,13,06,292,00"))
        assert p.satellites == 8

    def test_checksum_is_required_by_default(self):
        assert NMEAParser().parse("$" + RMC_BODY) is False
        assert NMEAParser(require_checksum=False).parse("$" + RMC_BODY) is True

    @pytest.mark.parametrize("line", [
        RMC[:-2] + ("00" if RMC[-2:] != "00" else "01"),
        RMC[:-2] + "G1",
        RMC + "0",
        RMC[:-1],                     # "*h" — one digit
    ])
    def test_bad_checksum_rejected_even_when_optional(self, line):
        assert NMEAParser(require_checksum=False).parse(line) is False

    def test_lowercase_checksum_and_crlf_ok(self):
        assert NMEAParser().parse(RMC[:-2] + RMC[-2:].lower() + "\r\n") is True

    @pytest.mark.parametrize("body", [
        "GPRMC,123519,V,5213.782,N,02100.732,E,010.0,084.4,081126,,,N",   # status V
        "GPRMC,123519,A,5213.782,N,02100.732,E,010.0,084.4,081126,,,N",   # mode N
        "GPRMC,123519,A,5213.782,N,02100.732,E,010.0,084.4,081126,,,S",   # simulator
        "GPGGA,123519,5213.782,N,02100.732,E,0,00,,,M,,M,,",              # quality 0
        "GPGGA,123519,5213.782,N,02100.732,E,8,08,0.9,110.5,M,46.9,M,,",  # simulation
        "GPRMC,,V,,,,,,,,,,N",
        "GPGGA,,,,,,0,00,99.99,,,,,,",
    ])
    def test_no_fix_sentences_are_ignored(self, body):
        p = NMEAParser()
        assert p.parse(nmea(body)) is True      # well-formed …
        assert p.fix_count == 0                 # … but no position
        assert p.fix is False

    def test_south_and_west_are_negative(self):
        p = NMEAParser()
        assert p.parse(nmea("GNRMC,010203,A,3351.500,S,15112.600,W,0.5,10.0,081126,,,A"))
        assert p.lat == pytest.approx(-(33 + 51.5 / 60))
        assert p.lon == pytest.approx(-(151 + 12.6 / 60))

    def test_rmc_date_and_time_to_epoch(self):
        p = NMEAParser()
        assert p.parse(RMC)
        expected = datetime(2026, 11, 8, 12, 35, 19, 500000, tzinfo=timezone.utc).timestamp()
        assert p.time_utc == pytest.approx(expected)

    @pytest.mark.parametrize("date", ["230394", "081106", "310226", "001126", "081300"])
    def test_insane_dates_drop_time_but_keep_the_fix(self, date):
        p = NMEAParser()
        body = RMC_BODY.replace("081126", date)
        assert p.parse(nmea(body)) is True
        assert p.fix_count == 1
        assert p.time_utc is None

    def test_knots_to_kmh(self):
        p = NMEAParser()
        assert p.parse(RMC)
        assert p.speed_kmh == pytest.approx(18.52)
        assert p.heading == pytest.approx(84.4)

    def test_vtg_speed_and_course(self):
        p = NMEAParser()
        assert p.parse(nmea("GNVTG,054.7,T,034.4,M,005.5,N,010.2,K,A")) is True
        assert p.speed_kmh == pytest.approx(10.2)
        assert p.heading == pytest.approx(54.7)
        assert p.fix_count == 0                 # no position in VTG
        p2 = NMEAParser()
        assert p2.parse(nmea("GPVTG,054.7,T,034.4,M,005.5,N,,K,A"))
        assert p2.speed_kmh == pytest.approx(5.5 * 1.852)

    def test_gga_altitude_and_satellites(self):
        p = NMEAParser()
        assert p.parse(GGA)
        assert p.alt == pytest.approx(110.5)
        assert p.satellites == 8

    @pytest.mark.parametrize("line", [
        "$" + "GPRMC," + "1" * 130,                       # overlong
        nmea(RMC_BODY.replace("N,", "Ñ,", 1)),             # non-ASCII
        RMC.replace(",", ",\x07", 1),                       # control character
        "GPRMC" + RMC[1:],                                  # no '$'
        "",
    ])
    def test_overlong_non_ascii_and_junk_lines(self, line):
        assert NMEAParser(require_checksum=False).parse(line) is False

    def test_bytes_input(self):
        p = NMEAParser()
        assert p.parse((RMC + "\r\n").encode()) is True
        assert p.parse("$GPRMC,ż".encode("utf-8")) is False
        assert p.parse(b"\xff\xfe" * 10) is False

    @pytest.mark.parametrize("lat, ns, lon, ew", [
        ("5213782", "N", "02100.732", "E"),     # no dot
        ("5213.782", "N", "02100732", "E"),
        ("5260.000", "N", "02100.732", "E"),    # 60 minutes
        ("9130.000", "N", "02100.732", "E"),    # > 90°
        ("5213.782", "X", "02100.732", "E"),    # bad hemisphere
        ("5213.782", "N", "18100.000", "E"),    # > 180°
        ("0000.000", "N", "00000.000", "E"),    # null island
        ("nan", "N", "02100.732", "E"),
        ("5213.782", "N", "", "E"),
    ])
    def test_invalid_coordinates_rejected(self, lat, ns, lon, ew):
        body = f"GPRMC,123519,A,{lat},{ns},{lon},{ew},010.0,084.4,081126,,,A"
        p = NMEAParser()
        assert p.parse(nmea(body)) is False
        assert p.fix_count == 0

    @pytest.mark.parametrize("speed", ["nan", "inf", "1e3", "-", "0x10"])
    def test_non_decimal_numbers_rejected(self, speed):
        body = RMC_BODY.replace("010.0", speed)
        assert NMEAParser().parse(nmea(body)) is False


# ── publication policy ───────────────────────────────────────────────────

class TestPublishing:
    def test_nothing_published_before_a_fix(self):
        mgr, bus, rec = make_manager()
        for line in [nmea("GPRMC,,V,,,,,,,,,,N"), nmea("GPGGA,,,,,,0,00,99.99,,,,,,"),
                     "garbage", nmea("GPGSV,1,1,00"), "$" + RMC_BODY]:
            mgr.feed(line, "udp")
        assert rec.events == []
        assert bus.get_last("gps.position") is None and bus.get_last("gps.fix") is None

    def test_first_fix_publishes_fix_and_full_payload(self):
        mgr, bus, rec = make_manager()
        assert mgr.feed(GGA, "udp") is True
        assert rec.topics()[0] == "gps.fix" and rec.values("gps.fix") == [True]
        pos = rec.values("gps.position")[0]
        assert set(pos) == POSITION_KEYS
        assert pos["alt"] == pos["altitude"] == pytest.approx(110.5)
        assert pos["fix"] is True and pos["source"] == "udp" and pos["satellites"] == 8
        assert pos["speed"] is None                 # no RMC/VTG yet …
        assert "gps.speed" not in rec.topics()      # … so no speed topic at all
        assert rec.values("gps.lat") == [pytest.approx(52.2297)]
        assert rec.values("gps.lon") == [pytest.approx(21.0122)]
        assert rec.values("gps.satellites") == [8]

    def test_rmc_adds_speed_heading_and_time(self):
        clock = FakeClock()
        mgr, bus, rec = make_manager(clock=clock)
        mgr.feed(GGA, "udp")
        clock.t += 1.0
        mgr.feed(RMC, "udp")
        pos = rec.values("gps.position")[-1]
        assert pos["speed"] == pytest.approx(18.5)
        assert pos["heading"] == pytest.approx(84.4)
        assert pos["alt"] == pytest.approx(110.5)          # GGA still fresh
        assert pos["time_utc"] == rec.values("gps.time_utc")[-1]
        assert rec.values("gps.speed") == [pytest.approx(18.5)]
        assert rec.values("gps.heading") == [pytest.approx(84.4)]
        assert rec.values("gps.fix") == [True]             # only on acquire

    def test_publication_is_throttled(self):
        clock = FakeClock()
        mgr, bus, rec = make_manager(clock=clock)
        for _ in range(10):
            mgr.feed(RMC, "udp")
            mgr.feed(GGA, "udp")
        assert len(rec.values("gps.position")) == 1
        clock.t += gps_mod.MIN_PUBLISH_INTERVAL_S
        mgr.feed(GGA, "udp")
        assert len(rec.values("gps.position")) == 2

    def test_stale_fix_publishes_false_exactly_once(self):
        clock = FakeClock()
        mgr, bus, rec = make_manager({"source": "udp", "stale_sec": 5}, clock=clock)
        mgr.feed(RMC, "udp")
        clock.t += 4.0
        mgr.tick()
        assert rec.values("gps.fix") == [True]
        clock.t += 1.5
        mgr.tick()
        assert rec.values("gps.fix") == [True, False]
        for _ in range(5):
            clock.t += 3.0
            mgr.tick()
        assert rec.values("gps.fix") == [True, False]
        # Losing the fix must not look like a stop (crash_detect, timer).
        assert 0.0 not in rec.values("gps.speed")
        clock.t += 1.0
        mgr.feed(RMC, "udp")
        assert rec.values("gps.fix") == [True, False, True]

    def test_old_gga_does_not_leak_altitude_into_new_fixes(self):
        clock = FakeClock()
        mgr, bus, rec = make_manager({"source": "udp", "stale_sec": 5}, clock=clock)
        mgr.feed(GGA, "udp")
        clock.t += 10.0
        mgr.feed(RMC, "udp")
        pos = rec.values("gps.position")[-1]
        assert pos["alt"] is None and pos["satellites"] == 0

    def test_heading_goes_stale_without_rmc_or_vtg(self):
        clock = FakeClock()
        mgr, bus, rec = make_manager({"source": "udp", "stale_sec": 5}, clock=clock)
        mgr.feed(RMC, "udp")
        assert rec.values("gps.position")[-1]["heading"] == pytest.approx(84.4)
        for _ in range(6):                  # GGA only (RMC/VTG stopped)
            clock.t += 1.0
            mgr.feed(GGA, "udp")
        positions = rec.values("gps.position")
        assert positions[-1]["heading"] is None and positions[-1]["speed"] is None
        # gps.heading only while fresh — never once the payload says None.
        fresh = [p["heading"] for p in positions if p["heading"] is not None]
        assert rec.values("gps.heading") == fresh and len(fresh) < len(positions)

    def test_empty_course_keeps_the_heading_while_the_fix_lasts(self):
        clock = FakeClock()
        mgr, bus, rec = make_manager({"source": "udp", "stale_sec": 5}, clock=clock)
        mgr.feed(RMC, "udp")
        for _ in range(10):                 # parked: RMC with an empty course
            clock.t += 1.0
            mgr.feed(RMC_NO_COURSE, "udp")
            mgr.tick()
        pos = rec.values("gps.position")[-1]
        assert pos["heading"] == pytest.approx(84.4) and pos["speed"] == 0.0

    def test_losing_the_fix_forgets_the_heading(self):
        clock = FakeClock()
        mgr, bus, rec = make_manager({"source": "udp", "stale_sec": 5}, clock=clock)
        mgr.feed(RMC, "udp")
        clock.t += 6.0
        mgr.tick()
        assert rec.values("gps.fix") == [True, False]
        clock.t += 60.0                     # outage: the car may have turned
        mgr.feed(RMC_NO_COURSE, "udp")      # back, parked, no course in RMC
        pos = rec.values("gps.position")[-1]
        assert rec.values("gps.fix") == [True, False, True]
        assert pos["heading"] is None
        assert rec.values("gps.heading") == [pytest.approx(84.4)]

    def test_source_state_every_ten_seconds(self):
        clock = FakeClock()
        mgr, bus, rec = make_manager(clock=clock)
        mgr.tick()
        clock.t += 5.0
        mgr.tick()
        assert len(rec.values("gps.source_state")) == 1
        clock.t += 4.0
        mgr.feed(RMC, "udp")
        clock.t += 1.0
        mgr.tick()
        states = rec.values("gps.source_state")
        assert len(states) == 2
        assert {"source", "state", "peer", "last_ts"} <= set(states[-1])
        assert states[-1]["state"] == "fix" and states[-1]["source"] == "udp"
        assert [i["source"] for i in states[-1]["inputs"]] == ["udp"]

    def test_demo_payload_has_the_same_shape(self):
        mgr, bus, rec = make_manager({"source": "demo"})
        mgr.publish_demo(DemoGPSGenerator().tick())
        pos = rec.values("gps.position")[0]
        assert set(pos) == POSITION_KEYS
        assert pos["fix"] is True and pos["source"] == "demo"
        assert pos["alt"] == pos["altitude"] == 120.0
        assert rec.values("gps.fix") == [True]
        assert rec.values("gps.speed") and rec.values("gps.lat")


# ── source selection ─────────────────────────────────────────────────────

class TestSources:
    @pytest.mark.parametrize("value, platform, expected, auto", [
        (None, "x86", ["demo"], True),
        ("auto", "x86", ["demo"], True),
        ("auto", "opi", ["serial"], True),
        (["auto"], "opi", ["serial"], True),
        ("udp", "x86", ["udp"], False),
        (["udp", "tcp"], "x86", ["udp", "tcp"], False),
        ("udp, tcp", "x86", ["udp", "tcp"], False),
        (["udp", "udp", "bogus"], "x86", ["udp"], False),
        (["gps"], "x86", [], False),
        (42, "x86", [], False),
    ])
    def test_resolve(self, value, platform, expected, auto):
        assert _resolve_sources(value, platform) == (expected, auto)

    def test_auto_on_x86_runs_the_demo(self):
        bus = EventBus()
        mgr = GPSManager(bus, {"hardware": {"gps": {"enabled": True, "port": "/dev/ttyUSB0"}}},
                         "x86")
        assert mgr.sources == ["demo"] and mgr.auto is True
        mgr.start()
        try:
            assert wait_until(lambda: bus.get_last("gps.position") is not None)
            assert bus.get_last("gps.position")[0]["source"] == "demo"
        finally:
            mgr.stop()

    def test_explicit_serial_without_port_never_runs_the_demo(self):
        def no_port(port, baud):
            raise OSError(2, "No such file or directory", port)

        bus = EventBus()
        mgr = GPSManager(bus, {"hardware": {"gps": {"source": "serial",
                                                    "port": "/dev/ttyBCM_NOPE"}}},
                         "x86", serial_factory=no_port)
        mgr.start()
        try:
            assert wait_until(lambda: mgr.inputs["serial"].state == "error")
            time.sleep(0.2)
            assert bus.get_last("gps.position") is None
            assert bus.get_last("gps.fix") is None
        finally:
            mgr.stop()

    def test_auto_on_hardware_keeps_the_legacy_demo_fallback(self):
        def no_port(port, baud):
            raise OSError("no such port")

        bus = EventBus()
        mgr = GPSManager(bus, {"hardware": {"gps": {}}}, "opi", serial_factory=no_port)
        assert mgr.sources == ["serial"] and mgr.auto
        mgr.start()
        try:
            assert wait_until(lambda: bus.get_last("gps.position") is not None)
            assert bus.get_last("gps.position")[0]["source"] == "demo"
            assert mgr.inputs["serial"].state == "demo_fallback"
        finally:
            mgr.stop()

    def test_serial_lines_are_parsed(self):
        opened = []

        def factory(port, baud):
            opened.append((port, baud))
            return FakeSerial()

        bus = EventBus()
        mgr = GPSManager(bus, {"hardware": {"gps": {"source": "serial", "port": "/dev/rfcomm0",
                                                    "baudrate": 4800}}},
                         "x86", serial_factory=factory)
        mgr.start()
        try:
            assert wait_until(lambda: bus.get_last("gps.position") is not None)
            assert bus.get_last("gps.position")[0]["source"] == "serial"
            assert opened == [("/dev/rfcomm0", 4800)]
        finally:
            mgr.stop()

    def test_unknown_sources_run_nothing(self):
        bus = EventBus()
        mgr = GPSManager(bus, {"hardware": {"gps": {"source": ["gsm"]}}}, "x86")
        assert mgr.sources == [] and mgr.inputs == {}

    @pytest.mark.parametrize("port, ok", [
        ("/dev/ttyUSB0", True),
        ("/dev/rfcomm0", True),
        ("/dev/ttyBCM_GPS", True),
        (UBX_BY_ID, True),                      # 82 characters
        (BY_PATH, True),                        # ':' in the name
        ("/dev/../etc/shadow", False),
        ("/dev/serial/../../etc/shadow", False),
        ("/dev/tty USB0", False),
        ("/dev/ttyUSB0\n", False),
        ("/dev/tty\x00", False),
        ("/dev/ttyż", False),
        ("/dev/", False),
        ("/devx/ttyUSB0", False),
        ("ttyUSB0", False),
        ("/dev/" + "a" * 300, False),
        (None, False),
        (0, False),
    ])
    def test_serial_port_validation(self, port, ok):
        assert gps_mod._valid_serial_port(port) is ok

    @pytest.mark.parametrize("port", [UBX_BY_ID, BY_PATH])
    def test_auto_on_hardware_opens_a_stable_device_path(self, port):
        opened = []

        def factory(p, baud):
            opened.append((p, baud))
            return FakeSerial()

        bus = EventBus()
        mgr = GPSManager(bus, {"hardware": {"gps": {"port": port}}}, "opi",
                         serial_factory=factory)
        assert mgr.sources == ["serial"] and mgr.auto
        mgr.start()
        try:
            assert wait_until(lambda: bus.get_last("gps.position") is not None)
            assert bus.get_last("gps.position")[0]["source"] == "serial"   # not demo
            assert opened == [(port, 9600)]
        finally:
            mgr.stop()


# ── UDP ──────────────────────────────────────────────────────────────────

IP_ADDR_OUT = (
    "1: lo    inet 127.0.0.1/8 scope host lo\\       valid_lft forever preferred_lft forever\n"
    "2: wlp2s0    inet 192.168.1.20/24 brd 192.168.1.255 scope global dynamic wlp2s0\\ "
    "      valid_lft 86000sec preferred_lft 86000sec\n"
    "5: bnep0    inet 192.168.44.23/24 brd 192.168.44.255 scope global dynamic "
    "noprefixroute bnep0\\       valid_lft 3590sec preferred_lft 3590sec\n"
    "6: bnep1    inet 10.1.0.2/8 scope global bnep1\n"
)


class FakeRunner:
    def __init__(self, stdout="", exc=None):
        self.stdout = stdout
        self.exc = exc
        self.calls = []

    def __call__(self, argv, **kw):
        import subprocess
        assert not kw.get("shell")
        self.calls.append(list(argv))
        if self.exc is not None:
            raise self.exc
        return subprocess.CompletedProcess(argv, 0, stdout=self.stdout, stderr="")


class TestUDP:
    def test_parse_ip_addr_keeps_bnep_subnets_only(self):
        import ipaddress
        nets = _parse_ip_addr(IP_ADDR_OUT)
        # bnep1's /8 is wider than any phone PAN — never trusted
        assert nets == [ipaddress.ip_network("192.168.44.0/24")]
        assert _parse_ip_addr("") == [] and _parse_ip_addr("garbage\n1: x") == []

    def test_real_socket_receives_rmc_and_gga(self):
        bus = EventBus()
        rec = Recorder(bus)
        mgr = GPSManager(bus, {"hardware": {"gps": {
            "source": "udp", "udp": {"bind": "127.0.0.1", "port": 0}}}}, "x86",
            ip_runner=FakeRunner(""))
        mgr.start()
        try:
            udp = mgr.inputs["udp"]
            assert udp.bound.wait(2.0)
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as tx:
                tx.sendto((RMC + "\r\n" + GGA + "\r\n").encode(), ("127.0.0.1", udp.bound_port))
            assert wait_until(lambda: bool(rec.values("gps.position")))
            pos = rec.values("gps.position")[0]
            assert pos["source"] == "udp" and pos["lat"] == pytest.approx(52.2297)
            assert udp.peer.startswith("127.0.0.1:")
        finally:
            mgr.stop()

    def test_datagram_from_a_foreign_source_is_ignored(self):
        mgr, bus, rec = make_manager()
        udp = mgr.inputs["udp"]
        assert udp.handle_datagram(RMC.encode(), ("8.8.8.8", 4000)) == 0
        assert udp.handle_datagram(RMC.encode(), ("192.168.1.20", 4000)) == 0
        assert udp.handle_datagram(RMC.encode(), ("not-an-ip", 4000)) == 0
        assert rec.events == []
        assert udp.handle_datagram(RMC.encode(), ("10.0.0.23", 4000)) == 1
        assert rec.values("gps.position")[0]["source"] == "udp"
        assert udp.peer == "10.0.0.23:4000"

    def test_pan_sources_from_ip_addr_cached(self):
        clock = FakeClock()
        runner = FakeRunner(IP_ADDR_OUT)
        mgr, bus, rec = make_manager({"source": "udp", "udp": {"allowed_sources": ["pan"]}},
                                     clock=clock, ip_runner=runner)
        udp = mgr.inputs["udp"]
        assert udp.source_allowed("192.168.44.1") is True
        assert udp.source_allowed("10.0.0.23") is False
        assert udp.source_allowed("10.1.0.5") is False
        assert udp.source_allowed("::ffff:192.168.44.1") is True
        assert runner.calls == [["ip", "-o", "-4", "addr", "show"]]
        clock.t += gps_mod.PAN_CACHE_S + 1
        udp.source_allowed("192.168.44.1")
        assert len(runner.calls) == 2

    def test_missing_ip_tool_allows_nothing_and_does_not_crash(self):
        runner = FakeRunner(exc=FileNotFoundError("ip"))
        mgr, bus, rec = make_manager({"source": "udp", "udp": {"allowed_sources": ["pan"]}},
                                     ip_runner=runner)
        assert mgr.inputs["udp"].handle_datagram(RMC.encode(), ("192.168.44.1", 1)) == 0
        assert rec.events == []

    def test_oversize_datagram_dropped(self):
        mgr, bus, rec = make_manager({"source": "udp", "udp": {"max_datagram": 256}})
        data = (RMC + "\r\n") * 5
        assert len(data) > 256
        assert mgr.inputs["udp"].handle_datagram(data.encode(), ("127.0.0.1", 1)) == 0
        assert rec.events == []

    def test_per_source_rate_cap(self):
        clock = FakeClock()
        mgr, bus, rec = make_manager({"source": "udp", "udp": {"max_datagram": 65000}},
                                     clock=clock)
        udp = mgr.inputs["udp"]
        many = ("\n".join([GGA] * 60)).encode()
        assert udp.handle_datagram(many, ("10.0.0.23", 1)) == gps_mod.RATE_PER_SOURCE
        assert udp.handle_datagram(GGA.encode(), ("10.0.0.23", 1)) == 0
        assert udp.handle_datagram(GGA.encode(), ("10.0.0.24", 1)) == 1   # other source
        clock.t += 1.0
        assert udp.handle_datagram(GGA.encode(), ("10.0.0.23", 1)) == 1

    def test_invalid_allowed_entries_are_skipped(self):
        mgr, bus, rec = make_manager({"source": "udp", "udp": {
            "allowed_sources": ["bogus", "10.0.0.0/24"], "bind": "not-an-ip"}})
        udp = mgr.inputs["udp"]
        assert udp.source_allowed("10.0.0.5") and not udp.source_allowed("127.0.0.1")
        assert udp._bind == "0.0.0.0"

    @pytest.mark.parametrize("gsv_per_epoch", [28, 80])
    def test_gsv_heavy_phone_keeps_every_epoch(self, gsv_per_epoch):
        # A multi-GNSS phone: dozens of GSV lines per 1 Hz epoch, RMC/GGA
        # last, one sentence per datagram, ±30 ms jitter between epochs.
        # GSV must not use up the allowance of the lines with the fix.
        clock = FakeClock()
        mgr, bus, rec = make_manager(clock=clock)
        udp = mgr.inputs["udp"]
        rng = random.Random(156)
        per_epoch = []
        for epoch in range(12):
            clock.t = 1000.0 + epoch + rng.uniform(-0.03, 0.03)
            for _ in range(gsv_per_epoch):
                assert udp.handle_datagram(GSV.encode(), ("10.0.0.23", 4000)) == 0
                clock.t += 0.001
            got = udp.handle_datagram(RMC.encode(), ("10.0.0.23", 4000))
            clock.t += 0.001
            got += udp.handle_datagram(GGA.encode(), ("10.0.0.23", 4000))
            per_epoch.append(got)
        assert per_epoch == [2] * 12

    def test_whole_epoch_in_one_datagram(self):
        clock = FakeClock()
        mgr, bus, rec = make_manager(clock=clock)
        udp = mgr.inputs["udp"]
        epoch = "\r\n".join([GSV] * 30 + [RMC, GGA]) + "\r\n"
        assert len(epoch) > 2048                # larger than the old default
        for i in range(5):
            clock.t = 1000.0 + i + (0.03 if i % 2 else -0.03)
            assert udp.handle_datagram(epoch.encode(), ("10.0.0.23", 4000)) == 2

    def test_raw_line_flood_is_bounded(self):
        clock = FakeClock()
        mgr, bus, rec = make_manager(clock=clock)
        udp = mgr.inputs["udp"]
        sent = 0
        for _ in range(gps_mod.RAW_LINES_PER_SOURCE):
            sent += udp.handle_datagram(GSV.encode(), ("10.0.0.23", 1))
        # The raw allowance is spent: even a valid fix is dropped unsplit …
        assert udp.handle_datagram(RMC.encode(), ("10.0.0.23", 1)) == 0
        # … for this source only, and only until the bucket refills.
        assert udp.handle_datagram(RMC.encode(), ("10.0.0.24", 1)) == 1
        clock.t += 1.0
        assert udp.handle_datagram(RMC.encode(), ("10.0.0.23", 1)) == 1

    def test_token_bucket_refills_continuously(self):
        clock = FakeClock()
        bucket = gps_mod._TokenBucket(10, 10, clock)
        assert all(bucket.take("a") for _ in range(10))
        assert bucket.take("a") is False
        clock.t += 0.25                         # 2.5 tokens back
        assert bucket.take("a") and bucket.take("a") and not bucket.take("a")
        assert bucket.take("a", 5) is False     # all-or-nothing
        clock.t -= 100.0                        # a clock step back drains nothing
        assert bucket.take("b") is True

    def test_second_instance_cannot_steal_the_port(self):
        cfg = {"source": "udp", "udp": {"bind": "127.0.0.1", "port": 0}}
        first = GPSManager(EventBus(), {"hardware": {"gps": cfg}}, "x86",
                           ip_runner=FakeRunner(""))
        first.start()
        try:
            assert first.inputs["udp"].bound.wait(2.0)
            port = first.inputs["udp"].bound_port
            cfg2 = {"source": "udp", "udp": {"bind": "127.0.0.1", "port": port}}
            second = GPSManager(EventBus(), {"hardware": {"gps": cfg2}}, "x86",
                                ip_runner=FakeRunner(""))
            second.start()
            try:
                # EADDRINUSE (logged) instead of silently sharing the port.
                assert wait_until(lambda: second.inputs["udp"].state == "error")
                assert not second.inputs["udp"].bound.is_set()
            finally:
                second.stop()
        finally:
            first.stop()


# ── TCP ──────────────────────────────────────────────────────────────────

PROC_NET_ROUTE = (
    "Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT\n"
    "wlp2s0\t00000000\t0101A8C0\t0003\t0\t0\t600\t00000000\t0\t0\t0\n"
    "wlp2s0\t0001A8C0\t00000000\t0001\t0\t0\t600\t00FFFFFF\t0\t0\t0\n"
    "bnep0\t002CA8C0\t00000000\t0001\t0\t0\t750\t00FFFFFF\t0\t0\t0\n"
    "bnep0\t00000000\t012CA8C0\t0003\t0\t0\t750\t00000000\t0\t0\t0\n"
)


class TestTCP:
    def test_parse_proc_net_route(self):
        assert _parse_proc_net_route(PROC_NET_ROUTE) == "192.168.44.1"
        assert _parse_proc_net_route(PROC_NET_ROUTE, prefix="wlp") == "192.168.1.1"
        no_pan = "\n".join(line for line in PROC_NET_ROUTE.splitlines() if "bnep" not in line)
        assert _parse_proc_net_route(no_pan) is None
        assert _parse_proc_net_route("") is None
        assert _parse_proc_net_route("garbage\nbnep0 zz yy") is None

    def test_lowest_metric_wins(self):
        text = PROC_NET_ROUTE + "bnep1\t00000000\t0102A8C0\t0003\t0\t0\t100\t00000000\t0\t0\t0\n"
        assert _parse_proc_net_route(text) == "192.168.2.1"

    def test_down_or_gatewayless_routes_ignored(self):
        text = ("Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\n"
                "bnep0\t00000000\t012CA8C0\t0002\t0\t0\t750\t00000000\n"     # not UP
                "bnep0\t00000000\t00000000\t0001\t0\t0\t750\t00000000\n")    # no gateway
        assert _parse_proc_net_route(text) is None

    def test_streams_lines_then_reconnects_after_close(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", 0))
        srv.listen(4)
        srv.settimeout(5.0)
        port = srv.getsockname()[1]
        accepted = []

        def serve():
            for _ in range(2):
                try:
                    conn, _ = srv.accept()
                except OSError:
                    return
                accepted.append(conn)
                conn.sendall((RMC + "\r\n" + GGA + "\r\n").encode())
                conn.close()

        threading.Thread(target=serve, daemon=True).start()
        bus = EventBus()
        mgr = GPSManager(bus, {"hardware": {"gps": {"source": "tcp", "tcp": {
            "host": "127.0.0.1", "port": port, "backoff_min_sec": 0.05,
            "backoff_max_sec": 0.2}}}}, "x86")
        mgr.start()
        try:
            assert wait_until(lambda: len(accepted) == 2, timeout=3.0)
            assert wait_until(lambda: bus.get_last("gps.position") is not None)
            assert bus.get_last("gps.position")[0]["source"] == "tcp"
            assert mgr.inputs["tcp"].connections >= 2
        finally:
            mgr.stop()
            srv.close()

    def test_pan_gateway_missing_means_waiting(self):
        bus = EventBus()
        mgr = GPSManager(bus, {"hardware": {"gps": {"source": "tcp", "tcp": {
            "backoff_min_sec": 0.05, "backoff_max_sec": 0.1}}}}, "x86",
            route_reader=lambda: PROC_NET_ROUTE.splitlines()[0] + "\n")
        mgr.start()
        try:
            assert wait_until(lambda: mgr.inputs["tcp"].state == "waiting")
            assert mgr.inputs["tcp"].connections == 0
        finally:
            mgr.stop()

    def test_invalid_host_falls_back_to_pan_gateway(self):
        mgr, bus, rec = make_manager({"source": "tcp", "tcp": {"host": "-oProxyCommand=x"}})
        assert mgr.inputs["tcp"]._host == "pan-gateway"

    def test_gsv_heavy_stream_keeps_every_epoch(self):
        clock = FakeClock()
        mgr, bus, rec = make_manager({"source": "tcp"}, clock=clock)
        tcp = mgr.inputs["tcp"]
        rng = random.Random(7)
        fixes = []
        for epoch in range(12):
            clock.t = 1000.0 + epoch + rng.uniform(-0.03, 0.03)
            before = mgr._parser.fix_count
            for line in [GSV] * 80 + [RMC, GGA]:
                tcp._line(line.encode())
                clock.t += 0.001
            fixes.append(mgr._parser.fix_count - before)
        assert fixes == [2] * 12

    def test_waiting_for_pan_does_not_grow_the_backoff(self, monkeypatch):
        # PAN comes up after ~10 polls; with a growing backoff (0.05 s
        # doubling to 30 s) the first connect would come minutes later.
        monkeypatch.setattr(gps_mod, "PAN_POLL_S", 0.02)
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        gateway = int.from_bytes(bytes([127, 0, 0, 1]), sys.byteorder)
        route_up = (PROC_NET_ROUTE.splitlines()[0] + "\n"
                    f"bnep0\t00000000\t{gateway:08X}\t0003\t0\t0\t750\t00000000\t0\t0\t0\n")
        polls = []

        def reader():
            polls.append(1)
            return route_up if len(polls) > 10 else PROC_NET_ROUTE.splitlines()[0] + "\n"

        bus = EventBus()
        mgr = GPSManager(bus, {"hardware": {"gps": {"source": "tcp", "tcp": {
            "port": port, "backoff_min_sec": 0.05, "backoff_max_sec": 30}}}}, "x86",
            route_reader=reader)
        mgr.start()
        try:
            assert wait_until(lambda: mgr.inputs["tcp"].connections == 1, timeout=3.0)
            assert mgr.inputs["tcp"].peer == f"127.0.0.1:{port}"
        finally:
            mgr.stop()
            srv.close()


# ── consumers ────────────────────────────────────────────────────────────

class TestConsumers:
    def test_trip_computer_uses_only_a_fresh_fix(self, monkeypatch):
        from src.dashboard import trip_computer as tc_mod
        from src.dashboard.trip_computer import TripComputer

        bus = EventBus()
        tc = TripComputer(event_bus=bus)
        fallback = ((50.0647, 19.9450), "fallback")
        assert tc._current_gps_or_fallback() == fallback
        bus.publish("gps.lat", 52.2297)
        bus.publish("gps.lon", 21.0122)
        assert tc._current_gps_or_fallback() == fallback       # no gps.fix yet
        bus.publish("gps.fix", True)
        assert tc._current_gps_or_fallback() == ((52.2297, 21.0122), "gps")
        real = time.time
        monkeypatch.setattr(tc_mod.time, "time", lambda: real() + 31)
        assert tc._current_gps_or_fallback() == fallback       # 31 s old
        monkeypatch.setattr(tc_mod.time, "time", real)
        bus.publish("gps.fix", False)
        assert tc._current_gps_or_fallback() == fallback

    def test_tracker_and_weather_read_the_new_payload(self, tmp_path):
        from src.location.tracker import GPSTracker
        from src.weather.weather import _plausible_fix

        class Cfg:
            def get(self, key, default=None):
                return {"tracking.db_path": str(tmp_path / "t.db"),
                        "tracking.interval_sec": 0}.get(key, default)

        mgr, bus, rec = make_manager()
        trk = GPSTracker(bus, config=Cfg())
        trk.start()
        try:
            mgr.feed(GGA, "udp")               # no speed yet: no trip
            assert trk._in_trip is False
            mgr._clock.t += 1.0
            mgr.feed(RMC, "udp")               # 18.5 km/h opens a trip
            assert trk._in_trip is True
            row = trk._db.execute("SELECT altitude, speed FROM tracks").fetchone()
            assert row == (pytest.approx(110.5), pytest.approx(18.5))
        finally:
            trk.stop()
        assert _plausible_fix(rec.values("gps.position")[-1]) == (
            pytest.approx(52.2297), pytest.approx(21.0122))
