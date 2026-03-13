"""Tests for OBD-II / K-Line module (Part 3)."""

import time
import pytest

from src.core.event_bus import EventBus
from src.obd.kwp2000 import _build_message, _parse_response, TESTER_ADDRESS, ECU_ADDRESS
from src.obd.edc15c7 import (
    PIDS, PID_MAP, DEFAULT_ACTIVE_PIDS,
    _decode_rpm, _decode_coolant_temp, _decode_fuel_rate,
    _decode_battery_voltage, _decode_vehicle_speed,
    _decode_turbo_pressure, _decode_injector_qty,
    _decode_intake_air_temp, _decode_throttle_position,
)
from src.obd.simulator import ECUSimulator, _build_response, _checksum


class TestKWP2000MessageBuilding:
    def test_build_short_message(self):
        msg = _build_message(ECU_ADDRESS, TESTER_ADDRESS, bytes([0x10, 0x81]))
        # Format: 0x80 | 2 = 0x82, target=0x01, source=0xF1, data=0x10 0x81, checksum
        assert msg[0] == 0x82
        assert msg[1] == ECU_ADDRESS
        assert msg[2] == TESTER_ADDRESS
        assert msg[3] == 0x10
        assert msg[4] == 0x81
        assert msg[-1] == sum(msg[:-1]) & 0xFF

    def test_build_message_checksum(self):
        msg = _build_message(0x01, 0xF1, bytes([0x3E]))
        expected_cs = sum(msg[:-1]) & 0xFF
        assert msg[-1] == expected_cs

    def test_parse_positive_response(self):
        # Build a response: SID 0x50 (startDiagSession positive), session type 0x81
        data = bytes([0x50, 0x81])
        raw = _build_response(TESTER_ADDRESS, ECU_ADDRESS, data)
        result = _parse_response(raw)
        assert result is not None
        sid, payload = result
        assert sid == 0x50
        assert payload == bytes([0x81])

    def test_parse_negative_response(self):
        data = bytes([0x7F, 0x10, 0x11])
        raw = _build_response(TESTER_ADDRESS, ECU_ADDRESS, data)
        result = _parse_response(raw)
        assert result is not None
        sid, payload = result
        assert sid == 0x7F

    def test_parse_invalid_message(self):
        assert _parse_response(b"") is None
        assert _parse_response(b"\x00") is None


class TestEDC15C7Decoding:
    def test_decode_rpm(self):
        # 3000 RPM / 0.25 = 12000 = 0x2EE0
        data = bytes([0x2E, 0xE0])
        assert _decode_rpm(data) == pytest.approx(3000.0)

    def test_decode_rpm_idle(self):
        # 850 RPM / 0.25 = 3400 = 0x0D48
        data = bytes([0x0D, 0x48])
        assert _decode_rpm(data) == pytest.approx(850.0)

    def test_decode_rpm_empty(self):
        assert _decode_rpm(b"") == 0.0

    def test_decode_coolant_temp(self):
        # 90°C + 40 = 130 = 0x82
        assert _decode_coolant_temp(bytes([130])) == pytest.approx(90.0)

    def test_decode_coolant_temp_cold(self):
        # 20°C + 40 = 60
        assert _decode_coolant_temp(bytes([60])) == pytest.approx(20.0)

    def test_decode_coolant_temp_negative(self):
        # -10°C + 40 = 30
        assert _decode_coolant_temp(bytes([30])) == pytest.approx(-10.0)

    def test_decode_fuel_rate(self):
        # 5.5 L/h / 0.01 = 550 = 0x0226
        data = bytes([0x02, 0x26])
        assert _decode_fuel_rate(data) == pytest.approx(5.50)

    def test_decode_battery_voltage(self):
        # 13.8V / 0.1 = 138
        assert _decode_battery_voltage(bytes([138])) == pytest.approx(13.8)

    def test_decode_vehicle_speed(self):
        assert _decode_vehicle_speed(bytes([120])) == 120.0
        assert _decode_vehicle_speed(bytes([0])) == 0.0

    def test_decode_turbo_pressure(self):
        # 1500 mbar = 0x05DC
        assert _decode_turbo_pressure(bytes([0x05, 0xDC])) == 1500.0

    def test_decode_injector_qty(self):
        # 25.5 mg/st / 0.01 = 2550 = 0x09F6
        data = bytes([0x09, 0xF6])
        assert _decode_injector_qty(data) == pytest.approx(25.50)

    def test_decode_intake_air_temp(self):
        # 35°C + 40 = 75
        assert _decode_intake_air_temp(bytes([75])) == pytest.approx(35.0)

    def test_decode_throttle_position(self):
        # 50% / 0.4 = 125
        assert _decode_throttle_position(bytes([125])) == pytest.approx(50.0)


class TestPIDDefinitions:
    def test_all_pids_have_required_fields(self):
        for pid in PIDS:
            assert pid.local_id > 0
            assert len(pid.name) > 0
            assert pid.event_topic.startswith("obd.")
            assert callable(pid.decode)
            assert len(pid.unit) > 0

    def test_pid_map_matches_pids(self):
        assert len(PID_MAP) == len(PIDS)
        for pid in PIDS:
            assert pid.local_id in PID_MAP

    def test_default_active_pids_exist(self):
        for pid_id in DEFAULT_ACTIVE_PIDS:
            assert pid_id in PID_MAP


class TestECUSimulator:
    def test_simulator_creates_pty(self):
        sim = ECUSimulator()
        port = sim.start()
        try:
            assert port.startswith("/dev/pts/") or port.startswith("/dev/pty")
            assert len(port) > 0
        finally:
            sim.stop()

    def test_simulator_responds_to_fast_init(self):
        """Test that simulator responds to startCommunication."""
        import serial as pyserial

        sim = ECUSimulator()
        port = sim.start()
        time.sleep(0.2)

        try:
            ser = pyserial.Serial(port, 10400, timeout=0.5)

            # Send startCommunication: fmt=0x81 target=0x01 source=0xF1 data=0x81 cs
            msg = _build_response(0x01, 0xF1, bytes([0x81]))
            ser.write(msg)
            time.sleep(0.1)

            # Read response
            response = ser.read(64)
            assert len(response) > 0, "No response from simulator"

            # Parse it
            result = _parse_response(response)
            assert result is not None, f"Could not parse response: {response.hex()}"
            sid, payload = result
            assert sid == 0xC1  # startCommunication positive response

            ser.close()
        finally:
            sim.stop()

    def test_simulator_responds_to_read_pid(self):
        """Test that simulator returns data for readDataByLocalIdentifier."""
        import serial as pyserial

        sim = ECUSimulator()
        port = sim.start()
        time.sleep(0.2)

        try:
            ser = pyserial.Serial(port, 10400, timeout=0.5)

            # First, start communication
            msg = _build_response(0x01, 0xF1, bytes([0x81]))
            ser.write(msg)
            time.sleep(0.1)
            ser.read(64)  # consume response

            # Read RPM (local ID 0x01)
            msg = _build_response(0x01, 0xF1, bytes([0x21, 0x01]))
            ser.write(msg)
            time.sleep(0.1)

            response = ser.read(64)
            assert len(response) > 0, "No response for RPM read"

            result = _parse_response(response)
            assert result is not None
            sid, payload = result
            assert sid == 0x61  # readDataByLocalId positive response
            assert len(payload) >= 3  # local_id + 2 bytes RPM data

            # Decode RPM value
            rpm_raw = payload[1:]  # skip echoed local_id
            rpm = _decode_rpm(rpm_raw)
            assert 500 < rpm < 6000, f"RPM out of range: {rpm}"

            ser.close()
        finally:
            sim.stop()


class TestIntegration:
    def test_full_obd_pipeline(self):
        """Integration test: simulator → KLine → KWP2000 → EDC15C7Reader → EventBus."""
        from src.obd.kline import KLine
        from src.obd.kwp2000 import KWP2000
        from src.obd.edc15c7 import EDC15C7Reader

        bus = EventBus()
        sim = ECUSimulator()
        port = sim.start()
        time.sleep(0.2)

        try:
            kline = KLine(port, echo=False)
            kline.open()

            kwp = KWP2000(kline)
            assert kwp.init_fast(), "Fast init failed"
            assert kwp.start_session(), "Start session failed"

            # Read a single PID manually
            raw = kwp.read_local_id(0x01)
            assert raw is not None, "Read RPM returned None"
            rpm = _decode_rpm(raw)
            assert 500 < rpm < 6000

            # Test reader with event bus
            received = {}

            def on_event(topic, value, ts):
                received[topic] = value

            bus.subscribe("obd.rpm", on_event)
            bus.subscribe("obd.coolant_temp", on_event)

            reader = EDC15C7Reader(kwp, bus, active_pids=[0x01, 0x03])
            reader.start()
            time.sleep(1.5)  # let it poll a few cycles
            reader.stop()

            assert "obd.rpm" in received, "RPM not received on event bus"
            assert "obd.coolant_temp" in received, "Coolant temp not received"
            assert 500 < received["obd.rpm"] < 6000
            assert -40 < received["obd.coolant_temp"] < 150

            kwp.stop_session()
            kline.close()
        finally:
            sim.stop()
