"""Arduino serial data reader — parses non-HID data from Arduino Pro Micro.

The Arduino sends HID keycodes for button presses (handled by evdev),
but also sends serial text data for:
    - Light sensor readings: "LIGHT:XXX" (ADC 0-1023)
    - Debug messages: "SWC: ...", "MUSIC: ...", etc.

This module reads the serial port and publishes light sensor data
to the event bus for the BrightnessController.

On x86: tries /dev/ttyACM0, falls back to stub mode.
On OPi: uses configured port (default /dev/ttyACM0).
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
    """Reads serial data from Arduino and publishes to event bus."""

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
            log.info("Arduino serial: no port found (light sensor disabled)")

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
        """Parse Arduino serial output."""
        if line.startswith("LIGHT:"):
            try:
                adc = int(line[6:])
                self._bus.publish("arduino.light_level", adc)
            except ValueError:
                pass
        elif line.startswith("SWC:") or line.startswith("MUSIC:") or line.startswith("STALK:"):
            log.debug("Arduino: %s", line)
