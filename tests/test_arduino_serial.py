"""Tests for the Arduino serial telemetry parser (src/input/arduino_serial.py)."""

import threading
import time

import pytest

import src.input.arduino_serial as arduino_serial
from src.core.event_bus import EventBus
from src.input.arduino_serial import ArduinoSerialListener


@pytest.fixture()
def listener(monkeypatch):
    """ArduinoSerialListener wired to a fresh bus, with no real serial port."""
    monkeypatch.setattr(arduino_serial, "find_arduino_serial", lambda: None)
    bus = EventBus()
    lst = ArduinoSerialListener(bus)
    events: list[tuple[str, object]] = []
    for topic in (
        "arduino.light_level",
        "vehicle.doors",
        "vehicle.handbrake",
        "vehicle.ignition_raw",
        "vehicle.rain",
        "vehicle.ext_temp_raw",
        "vehicle.parking_raw",
        "vehicle.cruise",
        "vehicle.immo_ok",
        "vehicle.airbag_ok",
        "vehicle.fuel_raw",
        "vehicle.power_state",
        "arduino.battery_voltage",
        "arduino.battery_current",
        "arduino.sensor_hub_connected",
    ):
        bus.subscribe(topic, lambda t, v, ts: events.append((t, v)))
    lst._events = events  # test-only attachment
    return lst


def _only_event(listener):
    assert len(listener._events) == 1, listener._events
    return listener._events[0]


class TestParseLine:
    def test_light(self, listener):
        listener._parse_line("LIGHT:512")
        topic, value = _only_event(listener)
        assert topic == "arduino.light_level"
        assert value == 512
        assert isinstance(value, int)

    def test_door(self, listener):
        listener._parse_line("DOOR:FL=1,FR=0,RL=0,RR=0,BONNET=0,TRUNK=1")
        topic, value = _only_event(listener)
        assert topic == "vehicle.doors"
        assert value == {
            "fl": True, "fr": False, "rl": False,
            "rr": False, "bonnet": False, "trunk": True,
        }
        assert all(isinstance(v, bool) for v in value.values())

    def test_handbrake_on(self, listener):
        listener._parse_line("HBRAKE:1")
        topic, value = _only_event(listener)
        assert topic == "vehicle.handbrake"
        assert value is True

    def test_handbrake_off(self, listener):
        listener._parse_line("HBRAKE:0")
        topic, value = _only_event(listener)
        assert topic == "vehicle.handbrake"
        assert value is False

    def test_ignition(self, listener):
        listener._parse_line("IGN:1")
        topic, value = _only_event(listener)
        assert topic == "vehicle.ignition_raw"
        assert value is True

    def test_ignition_off(self, listener):
        listener._parse_line("IGN:0")
        topic, value = _only_event(listener)
        assert topic == "vehicle.ignition_raw"
        assert value is False

    def test_power_state(self, listener):
        listener._parse_line("PWR:RUNNING")
        topic, value = _only_event(listener)
        assert topic == "vehicle.power_state"
        assert value == "RUNNING"

    def test_power_state_sleep(self, listener):
        listener._parse_line("PWR:SLEEP")
        topic, value = _only_event(listener)
        assert topic == "vehicle.power_state"
        assert value == "SLEEP"

    def test_power_action_is_informational(self, listener):
        # PWRACT: to log diagnostyczny, nie zdarzenie na magistrali.
        listener._parse_line("PWRACT:LONG")
        assert listener._events == []

    def test_rain(self, listener):
        listener._parse_line("RAIN:1")
        topic, value = _only_event(listener)
        assert topic == "vehicle.rain"
        assert value is True

    def test_temp(self, listener):
        listener._parse_line("TEMP:23.5")
        topic, value = _only_event(listener)
        assert topic == "vehicle.ext_temp_raw"
        assert value == pytest.approx(23.5)
        assert isinstance(value, float)

    def test_temp_negative(self, listener):
        listener._parse_line("TEMP:-7.25")
        topic, value = _only_event(listener)
        assert topic == "vehicle.ext_temp_raw"
        assert value == pytest.approx(-7.25)

    def test_park(self, listener):
        listener._parse_line("PARK:FL=123,FR=45,RL=200,RR=180")
        topic, value = _only_event(listener)
        assert topic == "vehicle.parking_raw"
        assert value == {"fl": 123, "fr": 45, "rl": 200, "rr": 180}
        assert all(isinstance(v, int) for v in value.values())

    def test_park_invalid_distance_falls_back(self, listener):
        listener._parse_line("PARK:FL=abc,FR=45")
        topic, value = _only_event(listener)
        assert topic == "vehicle.parking_raw"
        assert value["fl"] == 999
        assert value["fr"] == 45

    def test_cruise(self, listener):
        listener._parse_line("CRUISE:1")
        topic, value = _only_event(listener)
        assert topic == "vehicle.cruise"
        assert value is True

    def test_immo(self, listener):
        listener._parse_line("IMMO:1")
        topic, value = _only_event(listener)
        assert topic == "vehicle.immo_ok"
        assert value is True

    def test_airbag_fault(self, listener):
        listener._parse_line("AIRBAG:0")
        topic, value = _only_event(listener)
        assert topic == "vehicle.airbag_ok"
        assert value is False

    def test_airbag_ok(self, listener):
        listener._parse_line("AIRBAG:1")
        topic, value = _only_event(listener)
        assert topic == "vehicle.airbag_ok"
        assert value is True

    def test_fuel(self, listener):
        listener._parse_line("FUEL:512")
        topic, value = _only_event(listener)
        assert topic == "vehicle.fuel_raw"
        assert value == 512
        assert isinstance(value, int)


class TestParseLineRobustness:
    def test_debug_lines_publish_nothing(self, listener):
        listener._parse_line("SWC:VOLUP")
        listener._parse_line("MUSIC:PLAY")
        listener._parse_line("STALK:UP")
        assert listener._events == []

    def test_unknown_line_publishes_nothing(self, listener):
        listener._parse_line("GARBAGE:???")
        assert listener._events == []

    def test_malformed_numeric_does_not_raise(self, listener):
        listener._parse_line("LIGHT:notanumber")
        listener._parse_line("TEMP:xx")
        listener._parse_line("FUEL:")
        assert listener._events == []

    def test_no_port_means_unavailable(self, listener):
        assert listener.available is False


# ── BATT: (sensor_hub FEATURE_BATT_ADC / FEATURE_BATT_INA226) ────────────


class TestBatt:
    def test_millivolts_and_milliamps(self, listener):
        listener._parse_line("BATT:12650,-3400")
        # Current first: battery.py evaluates on the voltage event and must
        # already see the current from the same line.
        assert listener._events == [
            ("arduino.battery_current", pytest.approx(-3.4)),
            ("arduino.battery_voltage", pytest.approx(12.65)),
        ]
        assert all(isinstance(v, float) for _, v in listener._events)

    def test_millivolts_only(self, listener):
        listener._parse_line("BATT:12650")
        assert listener._events == [("arduino.battery_voltage", pytest.approx(12.65))]

    def test_volts_form_from_older_docs(self, listener):
        listener._parse_line("BATT:12.65")
        assert listener._events == [("arduino.battery_voltage", pytest.approx(12.65))]

    def test_charging_current_is_positive(self, listener):
        listener._parse_line("BATT:14100,8000")
        assert ("arduino.battery_current", pytest.approx(8.0)) in listener._events

    @pytest.mark.parametrize("line, volts, amps", [
        ("BATT:5000", 5.0, None),                 # bottom of the plausible range
        ("BATT:20000", 20.0, None),               # top
        ("BATT:12650,-100000", 12.65, -100.0),    # current at the limit
        ("BATT: 12650 , 250 ", 12.65, 0.25),      # whitespace tolerated
    ])
    def test_boundaries_accepted(self, listener, line, volts, amps):
        listener._parse_line(line.strip())
        got = dict(listener._events)
        assert got["arduino.battery_voltage"] == pytest.approx(volts)
        if amps is None:
            assert "arduino.battery_current" not in got
        else:
            assert got["arduino.battery_current"] == pytest.approx(amps)

    @pytest.mark.parametrize("line", [
        "BATT:",
        "BATT:abc",
        "BATT: INA226 nie odpowiada",   # firmware boot message without the chip
        "BATT:12650,",
        "BATT:12650,-3400,1",
        "BATT:12650;-3400",
        "BATT:nan",
        "BATT:inf",
        "BATT:1e4",
        "BATT:0x3000",
        "BATT:12650\x1b[2J",
        "BATT:" + "9" * 40,
    ])
    def test_garbage_publishes_nothing(self, listener, line):
        listener._parse_line(line)
        assert listener._events == []

    @pytest.mark.parametrize("line", [
        "BATT:4999",            # 4.999 V — divider or wire broken
        "BATT:20001",
        "BATT:99",              # "volts" form, but 99 V
        "BATT:4.9",
        "BATT:-12650",
        "BATT:0",
        "BATT:12650,100001",    # > 100 A
        "BATT:12650,-100001",
    ])
    def test_out_of_range_publishes_nothing(self, listener, line):
        listener._parse_line(line)
        assert listener._events == []

    def test_rejects_are_logged_rate_limited(self, monkeypatch):
        monkeypatch.setattr(arduino_serial, "find_arduino_serial", lambda: None)
        now = [100.0]
        lst = ArduinoSerialListener(EventBus(), clock=lambda: now[0])
        calls: list[tuple] = []
        monkeypatch.setattr(arduino_serial.log, "debug", lambda *a, **k: calls.append(a))
        lst._parse_line("BATT:junk")
        lst._parse_line("BATT:junk")
        now[0] += 30
        lst._parse_line("BATT:4000")
        assert len(calls) == 1
        now[0] += 31          # > 60 s since the first report
        lst._parse_line("BATT:junk")
        assert len(calls) == 2
        assert "+2 more" in calls[1][-1]
        # Untrusted text reaches the log only as a cut repr (%r).
        assert "%r" in calls[0][0]
        assert calls[0][2] == "BATT:junk"
        now[0] += 61
        lst._parse_line("BATT:" + "x" * 500)
        assert len(calls[2][2]) == 64

    def test_parse_batt_pure(self):
        assert arduino_serial.parse_batt("12650,-3400") == (12.65, -3.4)
        assert arduino_serial.parse_batt("12650") == (12.65, None)
        assert arduino_serial.parse_batt("12.65") == (12.65, None)
        with pytest.raises(ValueError):
            arduino_serial.parse_batt("12650,abc")


# ── port selection ─────────────────────────────────────────────────────────


def _no_probe():
    raise AssertionError("the probe must not run")


class TestPortSelection:
    def test_configured_port_never_probes(self, monkeypatch):
        monkeypatch.setattr(arduino_serial, "find_arduino_serial", _no_probe)
        lst = ArduinoSerialListener(
            EventBus(), {"arduino": {"sensor_hub_port": "/dev/ttyBCM_SENSOR",
                                     "probe_ports": True}})
        assert lst.available is True
        assert lst.port == "/dev/ttyBCM_SENSOR"

    def test_explicit_port_argument_never_probes(self, monkeypatch):
        monkeypatch.setattr(arduino_serial, "find_arduino_serial", _no_probe)
        lst = ArduinoSerialListener(EventBus(), port="/dev/serial/by-path/pci-0000:00:14.0-usb-0:2:1.0-port0")
        assert lst.port.endswith("port0")

    @pytest.mark.parametrize("bad", ["ttyUSB0", "/dev/../etc/shadow", "/dev/tty USB0",
                                     "/etc/passwd", "/dev/ttyUSB0\n"])
    def test_invalid_configured_port_is_refused(self, monkeypatch, bad):
        monkeypatch.setattr(arduino_serial, "find_arduino_serial", _no_probe)
        lst = ArduinoSerialListener(EventBus(), {"arduino": {"sensor_hub_port": bad}})
        assert lst.available is False

    @pytest.mark.parametrize("probe", [False, "false", "off"])
    def test_probe_off_and_no_port_means_disabled(self, monkeypatch, probe):
        monkeypatch.setattr(arduino_serial, "find_arduino_serial", _no_probe)
        lst = ArduinoSerialListener(
            EventBus(), {"arduino": {"sensor_hub_port": "", "probe_ports": probe}})
        assert lst.available is False

    def test_default_config_probes_like_before(self, monkeypatch):
        calls = []

        def fake_probe(**kwargs):
            calls.append(kwargs)
            return "/dev/ttyUSB0"

        monkeypatch.setattr(arduino_serial, "find_arduino_serial", fake_probe)
        lst = ArduinoSerialListener(EventBus(), {"modules": {}})
        assert lst.port == "/dev/ttyUSB0"
        assert calls == [{}]        # the historical zero-argument call

    def test_ports_of_enabled_modules_are_excluded(self, monkeypatch):
        calls = []

        def fake_probe(**kwargs):
            calls.append(kwargs)
            return None

        monkeypatch.setattr(arduino_serial, "find_arduino_serial", fake_probe)
        cfg = {
            "modules": {"central_lock": True, "location": False, "obd": True},
            "central_lock": {"port": "/dev/ttyUSB1"},
            "hardware": {"gps": {"port": "/dev/ttyUSB0"}},
            "serial": {"kline": {"port_x86": "/dev/ttyUSB_kline"}},
        }
        ArduinoSerialListener(EventBus(), cfg)
        assert calls == [{"exclude": ["/dev/ttyUSB1", "/dev/ttyUSB_kline"]}]

    def test_owned_ports_ignore_disabled_modules(self):
        # Production config: every owner off → nothing excluded, the probe
        # behaves exactly as before.
        cfg = {"modules": {"central_lock": False, "location": False, "obd": False},
               "central_lock": {"port": "/dev/ttyUSB1"},
               "hardware": {"gps": {"port": "/dev/ttyUSB0"}}}
        assert arduino_serial.owned_serial_ports(cfg) == []


class TestProbe:
    def _factory(self, opened, fail=()):
        class _Port:
            def close(self):
                pass

        def factory(port, baud, timeout=None):
            opened.append(port)
            if port in fail:
                raise OSError("no such device")
            return _Port()
        return factory

    def test_probe_skips_excluded_ports(self):
        opened: list[str] = []
        port = arduino_serial.find_arduino_serial(
            exclude=["/dev/ttyACM0", "/dev/ttyACM1"],
            serial_factory=self._factory(opened, fail={"/dev/ttyUSB0"}))
        assert port == "/dev/ttyUSB1"
        assert "/dev/ttyACM0" not in opened and "/dev/ttyACM1" not in opened

    def test_probe_compares_real_paths(self, tmp_path):
        # A udev-style symlink in the config hides the node it points to.
        link = tmp_path / "ttyUSB_kline"
        link.symlink_to("/dev/ttyUSB0")
        opened: list[str] = []
        port = arduino_serial.find_arduino_serial(
            exclude=[str(link)],
            serial_factory=self._factory(opened, fail={"/dev/ttyACM0", "/dev/ttyACM1"}))
        assert port == "/dev/ttyUSB1"
        assert "/dev/ttyUSB0" not in opened

    def test_probe_returns_none_when_nothing_opens(self):
        opened: list[str] = []
        port = arduino_serial.find_arduino_serial(
            serial_factory=self._factory(opened, fail=set(arduino_serial.ARDUINO_SERIAL_PORTS)))
        assert port is None
        assert opened == arduino_serial.ARDUINO_SERIAL_PORTS


# ── reconnect loop ─────────────────────────────────────────────────────────


class _FakeSerial:
    """readline() hands out queued lines, then behaves like a read timeout."""

    def __init__(self, lines, fail_after=False):
        self._lines = list(lines)
        self._fail_after = fail_after
        self.closed = False

    def readline(self, size=-1):
        if self._lines:
            return self._lines.pop(0)
        if self._fail_after:
            raise OSError("device reports readiness to read but returned no data")
        time.sleep(0.01)
        return b""

    def close(self):
        self.closed = True


def _wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture()
def fast_backoff(monkeypatch):
    monkeypatch.setattr(arduino_serial, "RECONNECT_MIN_S", 0.01)
    monkeypatch.setattr(arduino_serial, "RECONNECT_MAX_S", 0.05)


class TestReconnect:
    def _bus(self):
        bus = EventBus()
        events: list[tuple[str, object]] = []
        lock = threading.Lock()

        def rec(t, v, ts):
            with lock:
                events.append((t, v))
        for topic in ("vehicle.ignition_raw", "arduino.sensor_hub_connected",
                      "arduino.battery_voltage"):
            bus.subscribe(topic, rec)
        return bus, events

    def test_open_failure_then_success(self, fast_backoff, monkeypatch):
        monkeypatch.setattr(arduino_serial, "find_arduino_serial", _no_probe)
        bus, events = self._bus()
        attempts = []

        def factory(port, baud, timeout=None):
            attempts.append((port, baud))
            if len(attempts) == 1:
                raise OSError("[Errno 2] could not open port /dev/ttyBCM_SENSOR")
            return _FakeSerial([b"IGN:1\r\n", b"BATT:12650\n"])

        lst = ArduinoSerialListener(bus, port="/dev/ttyBCM_SENSOR", serial_factory=factory)
        lst.start()
        try:
            assert _wait_for(lambda: ("arduino.battery_voltage", pytest.approx(12.65)) in events)
        finally:
            lst.stop()
        assert len(attempts) == 2
        assert attempts[0] == ("/dev/ttyBCM_SENSOR", arduino_serial.BAUD_RATE)
        assert ("vehicle.ignition_raw", True) in events
        conn = [v for t, v in events if t == "arduino.sensor_hub_connected"]
        assert conn[:2] == [False, True]          # published on change only
        assert lst._thread is None

    def test_read_error_reopens_the_port(self, fast_backoff, monkeypatch):
        monkeypatch.setattr(arduino_serial, "find_arduino_serial", _no_probe)
        bus, events = self._bus()
        ports: list[_FakeSerial] = []

        def factory(port, baud, timeout=None):
            ser = _FakeSerial([b"IGN:1\n"] if not ports else [b"IGN:0\n"],
                              fail_after=not ports)
            ports.append(ser)
            return ser

        lst = ArduinoSerialListener(bus, port="/dev/ttyUSB0", serial_factory=factory)
        lst.start()
        try:
            assert _wait_for(lambda: ("vehicle.ignition_raw", False) in events)
        finally:
            lst.stop()
        assert len(ports) >= 2
        assert ports[0].closed is True             # the broken session was closed
        conn = [v for t, v in events if t == "arduino.sensor_hub_connected"]
        assert conn[:3] == [True, False, True]

    def test_port_stays_open_between_reads(self, fast_backoff, monkeypatch):
        monkeypatch.setattr(arduino_serial, "find_arduino_serial", _no_probe)
        bus, events = self._bus()
        opened = []

        def factory(port, baud, timeout=None):
            opened.append(port)
            return _FakeSerial([b"IGN:1\n"])

        lst = ArduinoSerialListener(bus, port="/dev/ttyUSB0", serial_factory=factory)
        lst.start()
        try:
            assert _wait_for(lambda: ("vehicle.ignition_raw", True) in events)
            time.sleep(0.1)                        # several read timeouts
        finally:
            lst.stop()
        assert opened == ["/dev/ttyUSB0"]

    def test_stop_while_backing_off_is_prompt(self, monkeypatch):
        monkeypatch.setattr(arduino_serial, "find_arduino_serial", _no_probe)

        def factory(port, baud, timeout=None):
            raise OSError("gone")

        lst = ArduinoSerialListener(EventBus(), port="/dev/ttyUSB0", serial_factory=factory)
        lst.start()
        time.sleep(0.05)                           # now inside the 1 s backoff
        t0 = time.monotonic()
        lst.stop()
        assert time.monotonic() - t0 < 0.5
