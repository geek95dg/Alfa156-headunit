"""Arduino serial data reader — parses telemetry and vehicle signals.

The Arduino sends HID keycodes for button presses (handled by evdev/arduino_hid),
but also sends plain-text serial data for sensors and vehicle status:

    Inputs (Arduino reads):
        LIGHT:XXX          — LDR light sensor (ADC 0-1023)
        DOOR:FL=1,FR=0,RL=0,RR=0,BONNET=0,TRUNK=0  — door/panel states
        HBRAKE:1           — handbrake engaged (1) or released (0)
        IGN:1              — ignition/ACC 12V detected
        RAIN:1             — rain sensor triggered
        TEMP:23.5          — DS18B20 external temperature
        PARK:FL=123,FR=45,RL=200,RR=180  — parking sensor distances (cm)
        CRUISE:1           — cruise control active
        IMMO:1             — immobilizer recognized key
        AIRBAG:1           — airbag system OK (0=fault)

    Debug (logged only):
        SWC:..., MUSIC:..., STALK:...

On x86: tries /dev/ttyACM0..1, /dev/ttyUSB0..2, falls back to stub mode.
On OPi: same auto-detection.
"""

import threading
from typing import Any, Optional

from src.core.event_bus import EventBus
from src.core.logger import get_logger

log = get_logger("input.arduino_serial")

try:
    import serial
    _SERIAL_AVAILABLE = True
except ImportError:
    _SERIAL_AVAILABLE = False


ARDUINO_SERIAL_PORTS = [
    "/dev/ttyACM0",
    "/dev/ttyACM1",
    "/dev/ttyUSB0",
    "/dev/ttyUSB1",
    "/dev/ttyUSB2",
]
BAUD_RATE = 115200


def find_arduino_serial() -> Optional[str]:
    """Find the Arduino serial port."""
    if not _SERIAL_AVAILABLE:
        return None

    for port in ARDUINO_SERIAL_PORTS:
        try:
            s = serial.Serial(port, BAUD_RATE, timeout=0.5)
            s.close()
            return port
        except (serial.SerialException, OSError):
            continue
    return None


class ArduinoSerialListener:
    """Reads serial data from Arduino and publishes to event bus.

    Publishes:
        arduino.light_level  — int (0-1023 ADC)
        vehicle.doors        — dict {fl, fr, rl, rr, bonnet, trunk} bool
        vehicle.handbrake    — bool
        vehicle.ignition_raw — bool (raw 12V detection from Arduino)
        vehicle.rain         — bool
        vehicle.ext_temp_raw — float (DS18B20 reading)
        vehicle.parking_raw  — dict {fl, fr, rl, rr} int (cm)
        vehicle.cruise       — bool
        vehicle.immo_ok      — bool
        vehicle.airbag_ok    — bool
    """

    def __init__(self, event_bus: EventBus):
        self._bus = event_bus
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._port: Optional[str] = find_arduino_serial()

    @property
    def available(self) -> bool:
        return self._port is not None

    def start(self) -> None:
        if self._running:
            return
        self._running = True

        if self.available:
            self._thread = threading.Thread(target=self._listen_loop, daemon=True)
            self._thread.start()
            log.info("Arduino serial listener started: %s", self._port)
        else:
            log.info("Arduino serial: no port found (sensors disabled)")

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _listen_loop(self) -> None:
        try:
            ser = serial.Serial(self._port, BAUD_RATE, timeout=1.0)
            while self._running:
                line = ser.readline().decode("utf-8", errors="ignore").strip()
                if not line:
                    continue
                self._parse_line(line)
        except serial.SerialException as e:
            log.error("Arduino serial lost: %s", e)
            self._running = False
        except Exception as e:
            log.error("Arduino serial error: %s", e)
            self._running = False

    def _parse_line(self, line: str) -> None:
        """Parse Arduino serial output line."""
        try:
            if line.startswith("LIGHT:"):
                self._bus.publish("arduino.light_level", int(line[6:]))

            elif line.startswith("DOOR:"):
                self._parse_doors(line[5:])

            elif line.startswith("HBRAKE:"):
                self._bus.publish("vehicle.handbrake", line[7:] == "1")

            elif line.startswith("IGN:"):
                self._bus.publish("vehicle.ignition_raw", line[4:] == "1")

            elif line.startswith("RAIN:"):
                self._bus.publish("vehicle.rain", line[5:] == "1")

            elif line.startswith("TEMP:"):
                self._bus.publish("vehicle.ext_temp_raw", float(line[5:]))

            elif line.startswith("PARK:"):
                self._parse_parking(line[5:])

            elif line.startswith("CRUISE:"):
                self._bus.publish("vehicle.cruise", line[7:] == "1")

            elif line.startswith("IMMO:"):
                self._bus.publish("vehicle.immo_ok", line[5:] == "1")

            elif line.startswith("AIRBAG:"):
                self._bus.publish("vehicle.airbag_ok", line[7:] == "1")

            elif line.startswith(("SWC:", "MUSIC:", "STALK:")):
                log.debug("Arduino: %s", line)

            else:
                log.debug("Arduino unknown: %s", line)

        except (ValueError, IndexError) as e:
            log.debug("Parse error '%s': %s", line, e)

    def _parse_doors(self, payload: str) -> None:
        """Parse DOOR:FL=1,FR=0,RL=0,RR=0,BONNET=0,TRUNK=0"""
        doors = {}
        for pair in payload.split(","):
            if "=" in pair:
                key, val = pair.split("=", 1)
                doors[key.strip().lower()] = val.strip() == "1"
        self._bus.publish("vehicle.doors", doors)

    def _parse_parking(self, payload: str) -> None:
        """Parse PARK:FL=123,FR=45,RL=200,RR=180 (distances in cm)"""
        distances = {}
        for pair in payload.split(","):
            if "=" in pair:
                key, val = pair.split("=", 1)
                try:
                    distances[key.strip().lower()] = int(val.strip())
                except ValueError:
                    distances[key.strip().lower()] = 999
        self._bus.publish("vehicle.parking_raw", distances)
