"""x86 environment simulator — generates configurable temperature curves.

Simulates a realistic temperature drop from warm to sub-zero,
triggering icing detection along the way.

Also serves as the module entry point (start_environment) called from main.py.
"""

import math
import time
import threading
from typing import Any, Optional

from src.core.event_bus import EventBus
from src.core.logger import get_logger
from src.environment.ds18b20 import TemperatureReader
from src.environment.icing import IcingDetector

log = get_logger("environment.simulator")


class TemperatureSimulator:
    """Simulates DS18B20 temperature readings for x86 testing.

    Default mode: sinusoidal curve that drifts from ~10°C down to -5°C
    and back, triggering icing alerts during the descent.
    """

    def __init__(self, reader: TemperatureReader):
        self._reader = reader
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._t = 0.0
        self._manual_temp: Optional[float] = None

        # Register a mock device on the 1-Wire bus
        self._device_id = "28-000000000001"
        onewire = self._reader.onewire
        if hasattr(onewire, 'add_device'):
            onewire.add_device(self._device_id, 15.0)

    def set_temperature(self, temp: float) -> None:
        """Manually set temperature (for keyboard control)."""
        self._manual_temp = temp

    def start(self) -> None:
        """Start the simulation thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        log.info("Temperature simulator started (auto curve mode)")

    def stop(self) -> None:
        """Stop the simulation thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    def _run(self) -> None:
        """Generate simulated temperature and inject into mock 1-Wire device."""
        onewire = self._reader.onewire

        while self._running:
            if self._manual_temp is not None:
                temp = self._manual_temp
            else:
                temp = self._generate_auto()

            # Inject into mock 1-Wire
            if hasattr(onewire, 'set_mock_temperature'):
                onewire.set_mock_temperature(self._device_id, temp)

            self._t += 0.1
            time.sleep(1.0)  # Update every second (reader polls every 10s)

    def _generate_auto(self) -> float:
        """Generate auto-demo temperature curve.

        Slow sinusoidal drift: 10°C -> -5°C -> 10°C over ~5 minutes.
        Small noise added for realism.
        """
        # Primary wave: period ~300s (5 min), range ~15°C centered at 2.5°C
        cycle_period = 300.0
        base = 2.5 + 7.5 * math.cos(self._t * (2 * math.pi / cycle_period))

        # Small noise
        noise = 0.3 * math.sin(self._t * 1.7) + 0.1 * math.sin(self._t * 4.3)

        return base + noise


def start_environment(config: Any, event_bus: EventBus, hal: Any = None,
                      **kwargs) -> None:
    """Entry point called from main.py to start the environment module.

    On x86: starts temperature simulator + icing detector.
    On OPi: reads from real DS18B20 sensor.
    """
    platform = config.platform

    # Faster polling for demo on x86
    read_interval = 2.0 if platform == "x86" else 10.0

    # Create temperature reader
    reader = TemperatureReader(hal, event_bus, read_interval=read_interval)

    # Create icing detector (subscribes to env.temperature automatically)
    icing = IcingDetector(event_bus)

    # Start simulator on x86
    simulator = None
    if platform == "x86":
        simulator = TemperatureSimulator(reader)
        simulator.start()

    # Start periodic reading
    reader.start()

    log.info("Environment module running (platform=%s)", platform)

    # Store references for cleanup
    event_bus.publish("environment._internals", {
        "reader": reader,
        "icing": icing,
        "simulator": simulator,
    })
