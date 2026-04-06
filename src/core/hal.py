"""Hardware Abstraction Layer — GPIO, UART, SPI, I2C, 1-Wire wrappers.

On x86: returns mock objects that log calls but do nothing.
On OPi (arm64): uses gpiod, pyserial, spidev, smbus2 for real hardware.
"""

import time
from typing import Any, Optional

from .logger import get_logger

log = get_logger("hal")


# ---------------------------------------------------------------------------
# Mock implementations (x86 / simulation)
# ---------------------------------------------------------------------------

class MockGPIOPin:
    """Simulated GPIO pin for x86 testing."""

    def __init__(self, pin: int, direction: str = "in"):
        self.pin = pin
        self.direction = direction
        self._value = 0
        log.debug("MockGPIO pin %d configured as %s", pin, direction)

    def read(self) -> int:
        return self._value

    def write(self, value: int) -> None:
        self._value = value
        log.debug("MockGPIO pin %d -> %d", self.pin, value)

    def set_mock_value(self, value: int) -> None:
        """Allow simulators to inject values."""
        self._value = value


class MockUART:
    """Simulated UART for x86 testing."""

    def __init__(self, port: str, baudrate: int = 9600):
        self.port = port
        self.baudrate = baudrate
        self._rx_buffer = bytearray()
        log.debug("MockUART opened: %s @ %d baud", port, baudrate)

    def write(self, data: bytes) -> int:
        log.debug("MockUART TX [%s]: %s", self.port, data.hex())
        return len(data)

    def read(self, size: int = 1, timeout: float = 1.0) -> bytes:
        result = bytes(self._rx_buffer[:size])
        self._rx_buffer = self._rx_buffer[size:]
        return result

    def inject_rx(self, data: bytes) -> None:
        """Allow simulators to inject received data."""
        self._rx_buffer.extend(data)

    def close(self) -> None:
        log.debug("MockUART closed: %s", self.port)


class MockPWM:
    """Simulated PWM output for x86 testing."""

    def __init__(self, pin: int, frequency: int = 1000):
        self.pin = pin
        self.frequency = frequency
        self._duty = 0
        log.debug("MockPWM pin %d @ %d Hz", pin, frequency)

    def set_duty(self, duty: int) -> None:
        """Set duty cycle 0-100."""
        self._duty = max(0, min(100, duty))
        log.debug("MockPWM pin %d duty -> %d%%", self.pin, self._duty)

    @property
    def duty(self) -> int:
        return self._duty

    def stop(self) -> None:
        self._duty = 0


class MockSPI:
    """Simulated SPI bus for x86 testing."""

    def __init__(self, bus: int = 0, device: int = 0):
        self.bus = bus
        self.device = device
        log.debug("MockSPI opened: bus=%d dev=%d", bus, device)

    def transfer(self, data: list[int]) -> list[int]:
        log.debug("MockSPI transfer: %s", data)
        return [0] * len(data)

    def close(self) -> None:
        log.debug("MockSPI closed")


class MockI2C:
    """Simulated I2C bus for x86 testing."""

    def __init__(self, bus: int = 1):
        self.bus = bus
        log.debug("MockI2C opened: bus=%d", bus)

    def read_byte(self, address: int, register: int) -> int:
        log.debug("MockI2C read: addr=0x%02X reg=0x%02X", address, register)
        return 0

    def write_byte(self, address: int, register: int, value: int) -> None:
        log.debug("MockI2C write: addr=0x%02X reg=0x%02X val=0x%02X", address, register, value)

    def close(self) -> None:
        log.debug("MockI2C closed")


class MockOneWire:
    """Simulated 1-Wire bus for x86 testing."""

    def __init__(self) -> None:
        self._devices: dict[str, float] = {}
        log.debug("MockOneWire initialized")

    def add_device(self, device_id: str, initial_value: float = 20.0) -> None:
        """Register a simulated 1-Wire device."""
        self._devices[device_id] = initial_value

    def list_devices(self) -> list[str]:
        return list(self._devices.keys())

    def read_temperature(self, device_id: str) -> Optional[float]:
        return self._devices.get(device_id)

    def set_mock_temperature(self, device_id: str, temp: float) -> None:
        """Allow simulators to inject temperature readings."""
        self._devices[device_id] = temp


# ---------------------------------------------------------------------------
# Real hardware implementations (OPi / arm64)
# ---------------------------------------------------------------------------

class RealGPIOPin:
    """GPIO pin using libgpiod (gpiod Python bindings)."""

    def __init__(self, pin: int, direction: str = "in"):
        import gpiod  # type: ignore
        self.pin = pin
        self.direction = direction
        self._chip = gpiod.Chip("gpiochip0")
        config = gpiod.LineSettings()
        if direction == "out":
            config.direction = gpiod.line.Direction.OUTPUT
        else:
            config.direction = gpiod.line.Direction.INPUT
        self._request = self._chip.request_lines(
            consumer="bcm",
            config={pin: config},
        )
        log.debug("RealGPIO pin %d configured as %s", pin, direction)

    def read(self) -> int:
        return self._request.get_value(self.pin).value

    def write(self, value: int) -> None:
        import gpiod  # type: ignore
        self._request.set_value(
            self.pin,
            gpiod.line.Value.ACTIVE if value else gpiod.line.Value.INACTIVE,
        )

    def close(self) -> None:
        self._request.release()


class RealUART:
    """UART using pyserial."""

    def __init__(self, port: str, baudrate: int = 9600):
        import serial  # type: ignore
        self.port = port
        self.baudrate = baudrate
        self._ser = serial.Serial(port, baudrate, timeout=1)
        log.debug("RealUART opened: %s @ %d baud", port, baudrate)

    def write(self, data: bytes) -> int:
        return self._ser.write(data)

    def read(self, size: int = 1, timeout: float = 1.0) -> bytes:
        self._ser.timeout = timeout
        return self._ser.read(size)

    def close(self) -> None:
        self._ser.close()
        log.debug("RealUART closed: %s", self.port)


class RealSPI:
    """SPI using spidev."""

    def __init__(self, bus: int = 0, device: int = 0):
        import spidev  # type: ignore
        self._spi = spidev.SpiDev()
        self._spi.open(bus, device)
        self._spi.max_speed_hz = 1000000
        log.debug("RealSPI opened: bus=%d dev=%d", bus, device)

    def transfer(self, data: list[int]) -> list[int]:
        return self._spi.xfer2(data)

    def close(self) -> None:
        self._spi.close()


class RealI2C:
    """I2C using smbus2."""

    def __init__(self, bus: int = 1):
        import smbus2  # type: ignore
        self._bus = smbus2.SMBus(bus)
        log.debug("RealI2C opened: bus=%d", bus)

    def read_byte(self, address: int, register: int) -> int:
        return self._bus.read_byte_data(address, register)

    def write_byte(self, address: int, register: int, value: int) -> None:
        self._bus.write_byte_data(address, register, value)

    def close(self) -> None:
        self._bus.close()


class RealOneWire:
    """1-Wire via kernel sysfs (w1-gpio, w1-therm)."""

    W1_BASE = "/sys/bus/w1/devices"

    def __init__(self) -> None:
        log.debug("RealOneWire initialized")

    def list_devices(self) -> list[str]:
        from pathlib import Path
        base = Path(self.W1_BASE)
        if not base.exists():
            return []
        return [
            d.name for d in base.iterdir()
            if d.name.startswith("28-")  # DS18B20 family code
        ]

    def read_temperature(self, device_id: str) -> Optional[float]:
        from pathlib import Path
        slave = Path(self.W1_BASE) / device_id / "w1_slave"
        if not slave.exists():
            return None
        text = slave.read_text()
        if "YES" not in text:
            return None  # CRC check failed
        pos = text.find("t=")
        if pos == -1:
            return None
        return int(text[pos + 2:]) / 1000.0


# ---------------------------------------------------------------------------
# Redmi / Ubuntu Touch implementations
# ---------------------------------------------------------------------------

class RedmiSensorHubGPIO:
    """GPIO proxy via Arduino sensor hub over USB serial.

    On Redmi Note 8 Pro (Ubuntu Touch), there is no GPIO header.
    All GPIO-dependent sensors (parking, ignition, rain, etc.) are
    offloaded to an Arduino Nano/ESP32 "sensor hub" connected via
    USB-C OTG hub. The Arduino reads sensors and relays and
    communicates via JSON over serial.

    Wire protocol (newline-delimited JSON):
        BCM → Arduino: {"cmd":"write","pin":84,"val":1}
        BCM → Arduino: {"cmd":"read","pin":85}
        Arduino → BCM: {"pin":85,"val":1}
        Arduino → BCM: {"type":"parking","distances":[0.5,1.2,1.8,2.5]}
        Arduino → BCM: {"type":"ignition","val":1}
    """

    def __init__(self, pin: int, direction: str = "in",
                 hub: Optional[Any] = None):
        self.pin = pin
        self.direction = direction
        self._value = 0
        self._hub = hub  # Reference to shared SensorHubSerial instance
        log.debug("RedmiSensorHubGPIO pin %d configured as %s (via USB hub)",
                  pin, direction)

    def read(self) -> int:
        if self._hub:
            return self._hub.read_pin(self.pin)
        return self._value

    def write(self, value: int) -> None:
        self._value = value
        if self._hub:
            self._hub.write_pin(self.pin, value)
        log.debug("RedmiSensorHubGPIO pin %d -> %d", self.pin, value)

    def set_mock_value(self, value: int) -> None:
        """Allow simulators to inject values (desk testing without hub)."""
        self._value = value


class SensorHubSerial:
    """Manages serial connection to Arduino sensor hub for Redmi platform.

    The sensor hub Arduino handles:
    - HC-SR04 parking sensors (4x)
    - Parking buzzer
    - Ignition/door/rain optoisolated inputs
    - Wiper relay output
    - DS18B20 temperature (via Arduino 1-Wire)
    - PWM backlight (if external display used)

    All data exchanged as newline-delimited JSON at 115200 baud.
    """

    def __init__(self, port: str = "/dev/ttyUSB0", baudrate: int = 115200):
        self.port = port
        self.baudrate = baudrate
        self._serial = None
        self._pin_values: dict[int, int] = {}
        self._temperature: Optional[float] = None
        self._distances: list[float] = [2.5, 2.5, 2.5, 2.5]
        self._lock = __import__("threading").Lock()
        self._running = False
        self._thread: Optional[Any] = None
        log.info("SensorHub initialized: %s @ %d baud", port, baudrate)
        self._connect()

    def _connect(self) -> None:
        """Attempt to open serial connection to sensor hub."""
        try:
            import serial  # type: ignore
            self._serial = serial.Serial(
                self.port, self.baudrate, timeout=0.1
            )
            log.info("SensorHub connected: %s", self.port)
        except Exception as e:
            log.warning("SensorHub not available (%s) — running in "
                        "simulation mode", e)
            self._serial = None

    def read_pin(self, pin: int) -> int:
        with self._lock:
            return self._pin_values.get(pin, 0)

    def write_pin(self, pin: int, value: int) -> None:
        with self._lock:
            self._pin_values[pin] = value
        if self._serial:
            import json
            cmd = json.dumps({"cmd": "write", "pin": pin, "val": value})
            try:
                self._serial.write((cmd + "\n").encode())
            except Exception:
                log.warning("SensorHub write failed for pin %d", pin)

    @property
    def temperature(self) -> Optional[float]:
        with self._lock:
            return self._temperature

    @property
    def distances(self) -> list[float]:
        with self._lock:
            return list(self._distances)

    def start_listener(self) -> None:
        """Start background thread that reads sensor hub data."""
        if self._running or not self._serial:
            return
        self._running = True
        self._thread = __import__("threading").Thread(
            target=self._listen_loop, daemon=True
        )
        self._thread.start()
        log.info("SensorHub listener started")

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        if self._serial:
            self._serial.close()

    def _listen_loop(self) -> None:
        """Read JSON lines from sensor hub and update pin values."""
        import json
        while self._running and self._serial:
            try:
                line = self._serial.readline().decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                data = json.loads(line)
                with self._lock:
                    if "pin" in data and "val" in data:
                        self._pin_values[data["pin"]] = data["val"]
                    if data.get("type") == "parking":
                        self._distances = data.get("distances", self._distances)
                    if data.get("type") == "temperature":
                        self._temperature = data.get("value")
            except Exception:
                pass  # Malformed line, skip


class RedmiOneWire:
    """1-Wire proxy via Arduino sensor hub for Redmi platform.

    DS18B20 temperature sensor is connected to the Arduino sensor hub
    (since Redmi has no GPIO). The hub reports temperature via JSON serial.
    Falls back to mock if hub not available.
    """

    def __init__(self, sensor_hub: Optional[SensorHubSerial] = None):
        self._hub = sensor_hub
        self._mock_devices: dict[str, float] = {}
        log.debug("RedmiOneWire initialized (hub=%s)",
                  "connected" if sensor_hub else "mock")

    def add_device(self, device_id: str, initial_value: float = 20.0) -> None:
        self._mock_devices[device_id] = initial_value

    def list_devices(self) -> list[str]:
        if self._hub and self._hub.temperature is not None:
            return ["28-redmi-hub"]
        return list(self._mock_devices.keys())

    def read_temperature(self, device_id: str) -> Optional[float]:
        if self._hub and device_id == "28-redmi-hub":
            return self._hub.temperature
        return self._mock_devices.get(device_id)

    def set_mock_temperature(self, device_id: str, temp: float) -> None:
        self._mock_devices[device_id] = temp


# ---------------------------------------------------------------------------
# HAL factory
# ---------------------------------------------------------------------------

class HAL:
    """Hardware Abstraction Layer — factory for platform-appropriate drivers.

    Supported platforms:
        - "x86"   — Mock drivers for development/testing
        - "opi"   — Real GPIO/UART/SPI/I2C via libgpiod/pyserial on Orange Pi
        - "redmi" — USB-serial sensor hub + native phone hardware on
                     Redmi Note 8 Pro with Ubuntu Touch

    Usage:
        hal = HAL(platform="x86")
        pin = hal.gpio(79, "out")
        pin.write(1)

        uart = hal.uart("/dev/ttyS3", 10400)
        uart.write(b"\\x81")
    """

    def __init__(self, platform: str = "x86"):
        self.platform = platform
        self._sensor_hub: Optional[SensorHubSerial] = None

        # On Redmi, initialize the sensor hub (Arduino via USB serial)
        if platform == "redmi":
            hub_port = "/dev/ttyUSB0"
            try:
                self._sensor_hub = SensorHubSerial(port=hub_port)
                self._sensor_hub.start_listener()
            except Exception as e:
                log.warning("Sensor hub init failed (%s) — GPIO will use "
                            "mock values", e)

        log.info("HAL initialized for platform: %s", platform)

    @property
    def sensor_hub(self) -> Optional[SensorHubSerial]:
        """Access the sensor hub (Redmi only, None on other platforms)."""
        return self._sensor_hub

    def gpio(self, pin: int, direction: str = "in") -> Any:
        if self.platform == "opi":
            return RealGPIOPin(pin, direction)
        if self.platform == "redmi":
            return RedmiSensorHubGPIO(pin, direction, hub=self._sensor_hub)
        return MockGPIOPin(pin, direction)

    def uart(self, port: str, baudrate: int = 9600) -> Any:
        if self.platform in ("opi", "redmi"):
            return RealUART(port, baudrate)
        return MockUART(port, baudrate)

    def pwm(self, pin: int, frequency: int = 1000) -> Any:
        # Real PWM on OPi would use sysfs or a dedicated library
        # On Redmi: backlight is handled by phone OS, external display
        # PWM via sensor hub Arduino
        return MockPWM(pin, frequency)

    def spi(self, bus: int = 0, device: int = 0) -> Any:
        if self.platform == "opi":
            return RealSPI(bus, device)
        return MockSPI(bus, device)

    def i2c(self, bus: int = 1) -> Any:
        if self.platform == "opi":
            return RealI2C(bus)
        return MockI2C(bus)

    def onewire(self) -> Any:
        if self.platform == "opi":
            return RealOneWire()
        if self.platform == "redmi":
            return RedmiOneWire(sensor_hub=self._sensor_hub)
        return MockOneWire()

    def shutdown(self) -> None:
        """Clean up HAL resources."""
        if self._sensor_hub:
            self._sensor_hub.stop()
