"""DS18B20 1-Wire temperature sensor driver.

On OPi: reads from kernel sysfs at /sys/bus/w1/devices/<device-id>/w1_slave.
On x86: uses HAL MockOneWire with simulator-injected temperatures.

Electrical (OPi):
    DS18B20 DQ -> GPIO pin 7 (1-Wire) + [4.7kOhm] -> 3.3V
    DS18B20 VDD -> 3.3V
    DS18B20 GND -> GND
"""

import threading
import time
from typing import Any, Callable, Optional

from src.core.event_bus import EventBus
from src.core.logger import get_logger

log = get_logger("environment.ds18b20")

# DS18B20 family code prefix
DS18B20_FAMILY = "28-"
DEFAULT_READ_INTERVAL = 10.0  # seconds


class TemperatureReader:
    """Reads temperature from DS18B20 sensor via HAL 1-Wire interface.

    Publishes `env.temperature` events at a configurable interval.
    """

    def __init__(self, hal: Any, event_bus: EventBus,
                 read_interval: float = DEFAULT_READ_INTERVAL):
        """
        Args:
            hal: HAL instance for 1-Wire access.
            event_bus: EventBus for publishing temperature events.
            read_interval: Seconds between readings (default 10s).
        """
        self._onewire = hal.onewire()
        self._event_bus = event_bus
        self._read_interval = read_interval
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._device_id: Optional[str] = None
        self._last_temp: Optional[float] = None
        self._on_reading: Optional[Callable[[float], None]] = None

        # Try to find a DS18B20 device
        self._discover_device()

    def _discover_device(self) -> None:
        """Find the first DS18B20 device on the 1-Wire bus."""
        devices = self._onewire.list_devices()
        for dev in devices:
            if dev.startswith(DS18B20_FAMILY):
                self._device_id = dev
                log.info("DS18B20 found: %s", dev)
                return

        log.warning("No DS18B20 device found on 1-Wire bus")

    def set_callback(self, callback: Callable[[float], None]) -> None:
        """Set a callback for each temperature reading."""
        self._on_reading = callback

    def read_once(self) -> Optional[float]:
        """Read temperature once.

        Returns:
            Temperature in Celsius, or None if read failed.
        """
        if self._device_id is None:
            self._discover_device()
            if self._device_id is None:
                return None

        temp = self._onewire.read_temperature(self._device_id)
        if temp is not None:
            self._last_temp = temp
            self._event_bus.publish("env.temperature", temp)
            if self._on_reading:
                self._on_reading(temp)
            log.debug("Temperature: %.1f°C", temp)
        else:
            log.warning("Failed to read temperature from %s", self._device_id)

        return temp

    @property
    def last_temperature(self) -> Optional[float]:
        return self._last_temp

    @property
    def onewire(self) -> Any:
        """Expose the 1-Wire interface for simulator injection."""
        return self._onewire

    def start(self) -> None:
        """Start periodic temperature reading in a background thread."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()
        log.info("Temperature reader started (interval=%.0fs)", self._read_interval)

    def stop(self) -> None:
        """Stop periodic reading."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=self._read_interval + 2)
            self._thread = None
        log.info("Temperature reader stopped")

    def _read_loop(self) -> None:
        """Background loop — read temperature at configured interval."""
        while self._running:
            self.read_once()
            # Sleep in small increments so we can stop quickly
            deadline = time.monotonic() + self._read_interval
            while self._running and time.monotonic() < deadline:
                time.sleep(0.5)
