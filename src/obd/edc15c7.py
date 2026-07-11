"""Bosch EDC15C7 ECU specific PID definitions and data reader.

The EDC15C7 is the engine ECU in the Alfa Romeo 156 1.9 JTD 8V.
This module defines the local identifiers for reading live data
and provides decoding functions for each parameter.
"""

import time
import threading
from typing import Optional, Callable

from src.core.event_bus import EventBus
from src.core.logger import get_logger
from src.obd.kwp2000 import KWP2000

log = get_logger("obd.edc15c7")


# EDC15C7 Local Identifier definitions
# Format: (local_id, name, event_topic, decode_function, unit)
class PID:
    """PID definition for an ECU parameter."""

    def __init__(
        self,
        local_id: int,
        name: str,
        event_topic: str,
        decode: Callable[[bytes], float],
        unit: str,
    ) -> None:
        self.local_id = local_id
        self.name = name
        self.event_topic = event_topic
        self.decode = decode
        self.unit = unit


def _decode_rpm(data: bytes) -> float:
    """Decode RPM (2 bytes, big-endian, × 0.25)."""
    if len(data) < 2:
        return 0.0
    return ((data[0] << 8) | data[1]) * 0.25


def _decode_coolant_temp(data: bytes) -> float:
    """Decode coolant temperature (1 byte, offset -40°C)."""
    if len(data) < 1:
        return 0.0
    return data[0] - 40.0


def _decode_fuel_rate(data: bytes) -> float:
    """Decode fuel rate in L/h (2 bytes, big-endian, × 0.01)."""
    if len(data) < 2:
        return 0.0
    return ((data[0] << 8) | data[1]) * 0.01


def _decode_injector_qty(data: bytes) -> float:
    """Decode injector quantity in mg/stroke (2 bytes, × 0.01)."""
    if len(data) < 2:
        return 0.0
    return ((data[0] << 8) | data[1]) * 0.01


def _decode_battery_voltage(data: bytes) -> float:
    """Decode battery voltage (1 byte, × 0.1)."""
    if len(data) < 1:
        return 0.0
    return data[0] * 0.1


def _decode_turbo_pressure(data: bytes) -> float:
    """Decode turbo boost pressure in mbar (2 bytes, big-endian)."""
    if len(data) < 2:
        return 0.0
    return (data[0] << 8) | data[1]


def _decode_vehicle_speed(data: bytes) -> float:
    """Decode vehicle speed in km/h (1 byte)."""
    if len(data) < 1:
        return 0.0
    return float(data[0])


def _decode_intake_air_temp(data: bytes) -> float:
    """Decode intake air temperature (1 byte, offset -40°C)."""
    if len(data) < 1:
        return 0.0
    return data[0] - 40.0


def _decode_throttle_position(data: bytes) -> float:
    """Decode throttle/pedal position in % (1 byte, × 0.4)."""
    if len(data) < 1:
        return 0.0
    return data[0] * 0.4


# Define all PIDs for the Bosch EDC15C7
PIDS = [
    PID(0x01, "Engine RPM", "obd.rpm", _decode_rpm, "rpm"),
    PID(0x02, "Vehicle Speed", "obd.speed", _decode_vehicle_speed, "km/h"),
    PID(0x03, "Coolant Temperature", "obd.coolant_temp", _decode_coolant_temp, "°C"),
    PID(0x04, "Fuel Rate", "obd.fuel_rate", _decode_fuel_rate, "L/h"),
    PID(0x05, "Injector Quantity", "obd.injector_qty", _decode_injector_qty, "mg/st"),
    PID(0x06, "Battery Voltage", "obd.battery_voltage", _decode_battery_voltage, "V"),
    PID(0x07, "Turbo Pressure", "obd.turbo_pressure", _decode_turbo_pressure, "mbar"),
    PID(0x08, "Intake Air Temp", "obd.intake_air_temp", _decode_intake_air_temp, "°C"),
    PID(0x09, "Throttle Position", "obd.throttle_position", _decode_throttle_position, "%"),
]

# Lookup by local ID
PID_MAP = {pid.local_id: pid for pid in PIDS}

# Default active PIDs for round-robin polling (most important parameters)
DEFAULT_ACTIVE_PIDS = [0x01, 0x02, 0x03, 0x04, 0x06]


def dtc_to_code(raw: int) -> str:
    """Convert a 16-bit DTC to its display code (e.g. 0x0380 -> 'P0380')."""
    letter = "PCBU"[(raw >> 14) & 0x03]
    return (f"{letter}{(raw >> 12) & 0x03}"
            f"{(raw >> 8) & 0x0F:X}{(raw >> 4) & 0x0F:X}{raw & 0x0F:X}")


# Common trouble codes on the Bosch EDC15C7 (Alfa 156 1.9 JTD 8V).
# Codes outside this map still display with their P-code, just without
# a description.
DTC_DESCRIPTIONS = {
    "P0100": "Mass air flow (MAF) sensor circuit",
    "P0105": "Manifold absolute pressure sensor circuit",
    "P0110": "Intake air temperature sensor circuit",
    "P0115": "Engine coolant temperature sensor circuit",
    "P0120": "Accelerator pedal position sensor circuit",
    "P0180": "Fuel temperature sensor circuit",
    "P0190": "Fuel rail pressure sensor circuit",
    "P0201": "Injector circuit — cylinder 1",
    "P0202": "Injector circuit — cylinder 2",
    "P0203": "Injector circuit — cylinder 3",
    "P0204": "Injector circuit — cylinder 4",
    "P0215": "Engine shutoff solenoid",
    "P0235": "Turbocharger boost pressure sensor circuit",
    "P0243": "Turbocharger wastegate solenoid",
    "P0335": "Crankshaft position sensor circuit",
    "P0380": "Glow plug circuit",
    "P0400": "EGR flow malfunction",
    "P0500": "Vehicle speed sensor",
    "P0560": "System voltage malfunction",
    "P0606": "ECU processor fault",
    "P1600": "Immobiliser communication fault",
    "P1610": "Immobiliser code mismatch",
}


class EDC15C7Reader:
    """Continuously polls the EDC15C7 ECU and publishes data to event bus.

    Runs in a background thread, polling active PIDs in round-robin fashion.
    Sends testerPresent keepalive every 2 seconds.
    """

    def __init__(
        self,
        kwp: KWP2000,
        event_bus: EventBus,
        active_pids: Optional[list[int]] = None,
    ) -> None:
        self.kwp = kwp
        self.bus = event_bus
        self.active_pids = active_pids or DEFAULT_ACTIVE_PIDS
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_keepalive = 0.0
        self._poll_interval = 0.1  # ~100ms between PID reads

        # Latest values cache
        self.values: dict[str, float] = {}

        # DTC requests are serviced INSIDE the poll loop so the serial
        # link is never used from two threads at once. The web endpoint
        # publishes obd.dtc.read_request / obd.dtc.clear_request; the
        # poll loop answers with obd.dtc.codes / obd.dtc.cleared.
        self._dtc_read_pending = False
        self._dtc_clear_pending = False
        event_bus.subscribe("obd.dtc.read_request", self._on_dtc_read_request)
        event_bus.subscribe("obd.dtc.clear_request", self._on_dtc_clear_request)

    def _on_dtc_read_request(self, topic, value, ts=None) -> None:
        self._dtc_read_pending = True

    def _on_dtc_clear_request(self, topic, value, ts=None) -> None:
        self._dtc_clear_pending = True

    def _service_dtc_requests(self) -> None:
        """Handle pending DTC read/clear inside the polling thread."""
        if self._dtc_clear_pending:
            self._dtc_clear_pending = False
            ok = self.kwp.clear_dtcs()
            self.bus.publish("obd.dtc.cleared", ok)
            self._dtc_read_pending = True  # re-read to confirm

        if self._dtc_read_pending:
            self._dtc_read_pending = False
            raw_dtcs = self.kwp.read_dtcs()
            if raw_dtcs is None:
                self.bus.publish("obd.dtc.codes", None)  # comms failure
                return
            codes = []
            for raw, status in raw_dtcs:
                code = dtc_to_code(raw)
                codes.append({
                    "code": code,
                    "status": status,
                    "desc": DTC_DESCRIPTIONS.get(code, ""),
                })
            self.bus.publish("obd.dtc.codes", codes)

    def start(self) -> None:
        """Start the polling thread."""
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        log.info("EDC15C7 reader started (polling %d PIDs)", len(self.active_pids))

    def stop(self) -> None:
        """Stop the polling thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
        log.info("EDC15C7 reader stopped")

    def _poll_loop(self) -> None:
        """Main polling loop — round-robin through active PIDs."""
        pid_index = 0
        consecutive_errors = 0

        while self._running:
            # Service queued DTC read/clear requests first
            try:
                self._service_dtc_requests()
            except Exception:
                log.exception("DTC request handling failed")

            # Send keepalive every 2 seconds
            now = time.time()
            if now - self._last_keepalive > 2.0:
                if self.kwp.session_active:
                    if self.kwp.tester_present():
                        self._last_keepalive = now
                    else:
                        log.warning("Keepalive failed")
                        consecutive_errors += 1

            # Read next PID
            local_id = self.active_pids[pid_index]
            pid = PID_MAP.get(local_id)

            if pid:
                raw = self.kwp.read_local_id(local_id)
                if raw is not None:
                    try:
                        value = pid.decode(raw)
                        self.values[pid.event_topic] = value
                        self.bus.publish(pid.event_topic, value)
                        consecutive_errors = 0
                    except Exception:
                        log.exception("Error decoding PID 0x%02X (%s)", local_id, pid.name)
                else:
                    consecutive_errors += 1
                    if consecutive_errors > 10:
                        log.error("Too many consecutive errors, pausing polling")
                        time.sleep(1.0)
                        consecutive_errors = 0

            # Advance to next PID
            pid_index = (pid_index + 1) % len(self.active_pids)
            time.sleep(self._poll_interval)
