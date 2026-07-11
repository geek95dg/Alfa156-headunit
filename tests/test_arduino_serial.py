"""Tests for the Arduino serial telemetry parser (src/input/arduino_serial.py)."""

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
