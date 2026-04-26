"""HC-SR04 ultrasonic sensor driver.

Drives 4 sensors with a shared TRIG pin and individual ECHO pins.
On x86: uses mock GPIO from HAL (distances injected by simulator).
On OPi: real GPIO timing via gpiod.

Wiring (OPi):
    GPIO_TRIG -> 4x HC-SR04 TRIG (shared)
    HC-SR04_n ECHO -> [1kOhm] -> GPIO_ECHO_n -> [2kOhm] -> GND
"""

import time
import threading
from typing import Any, Optional

from src.core.logger import get_logger

log = get_logger("parking.hcsr04")

# Speed of sound in air at ~20C: 343 m/s
# Distance = (echo_time * 343) / 2
SPEED_OF_SOUND_M_S = 343.0
MAX_DISTANCE_M = 2.5
TIMEOUT_S = MAX_DISTANCE_M * 2 / SPEED_OF_SOUND_M_S  # ~0.0146s


class HCSR04:
    """Driver for a single HC-SR04 ultrasonic sensor.

    On OPi, measures real echo pulse duration.
    On x86, the mock GPIO pin value is used directly as distance in cm
    (set by the simulator).
    """

    def __init__(self, trig_pin: Any, echo_pin: Any, sensor_id: int = 0):
        """
        Args:
            trig_pin: HAL GPIO pin configured as output (shared across sensors).
            echo_pin: HAL GPIO pin configured as input.
            sensor_id: Index for logging purposes.
        """
        self.trig_pin = trig_pin
        self.echo_pin = echo_pin
        self.sensor_id = sensor_id
        self._last_distance: float = MAX_DISTANCE_M
        self._mock_distance: Optional[float] = None

    def set_mock_distance(self, distance_m: float) -> None:
        """Allow simulator to inject a distance value (x86 only)."""
        self._mock_distance = max(0.0, min(MAX_DISTANCE_M, distance_m))

    def measure(self) -> float:
        """Measure distance in meters.

        On x86 with mock GPIO, returns the injected mock distance.
        On OPi, performs real trigger/echo measurement.

        Returns:
            Distance in meters (clamped to 0..MAX_DISTANCE_M).
        """
        # If mock distance is set (x86 simulator), return it directly
        if self._mock_distance is not None:
            self._last_distance = self._mock_distance
            return self._last_distance

        # Real measurement (OPi) — trigger pulse and measure echo
        try:
            self._last_distance = self._real_measure()
        except Exception:
            log.warning("Sensor %d measurement failed, using last value", self.sensor_id)

        return self._last_distance

    def _real_measure(self) -> float:
        """Perform real GPIO-based ultrasonic measurement."""
        # Send 10us trigger pulse
        self.trig_pin.write(1)
        time.sleep(0.00001)  # 10 microseconds
        self.trig_pin.write(0)

        # Wait for echo to go HIGH
        start_wait = time.monotonic()
        while self.echo_pin.read() == 0:
            if time.monotonic() - start_wait > TIMEOUT_S:
                return MAX_DISTANCE_M  # No echo — nothing in range

        pulse_start = time.monotonic()

        # Wait for echo to go LOW
        while self.echo_pin.read() == 1:
            if time.monotonic() - pulse_start > TIMEOUT_S:
                return MAX_DISTANCE_M  # Echo too long — very far or error

        pulse_end = time.monotonic()

        # Calculate distance
        pulse_duration = pulse_end - pulse_start
        distance_m = (pulse_duration * SPEED_OF_SOUND_M_S) / 2.0

        return max(0.0, min(MAX_DISTANCE_M, distance_m))

    @property
    def last_distance(self) -> float:
        return self._last_distance


class SensorArray:
    """Manages an array of 4 HC-SR04 sensors with sequential measurement.

    Sensors are triggered one at a time to avoid cross-talk.
    Full scan cycle: ~60ms per sensor x 4 = ~240ms.
    """

    def __init__(self, hal: Any, config: Any):
        """
        Args:
            hal: HAL instance for GPIO access.
            config: BCMConfig instance.
        """
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self.distances: list[float] = [MAX_DISTANCE_M] * 4

        # Get pin assignments from config
        trig_pin_num = config.get("gpio.parking_trig", 79)
        echo_pin_nums = config.get("gpio.parking_echo", [80, 81, 82, 83])

        # Create GPIO pins
        self._trig_pin = hal.gpio(trig_pin_num, "out")

        self.sensors: list[HCSR04] = []
        for i, echo_num in enumerate(echo_pin_nums):
            echo_pin = hal.gpio(echo_num, "in")
            sensor = HCSR04(self._trig_pin, echo_pin, sensor_id=i)
            self.sensors.append(sensor)

        log.info("SensorArray initialized: TRIG=%d, ECHO=%s",
                 trig_pin_num, echo_pin_nums)

    def measure_all(self) -> list[float]:
        """Measure all 4 sensors sequentially.

        Returns:
            List of 4 distances in meters [left, center-left, center-right, right].
        """
        results = []
        for sensor in self.sensors:
            dist = sensor.measure()
            results.append(dist)
            time.sleep(0.06)  # 60ms between sensors to avoid echo cross-talk

        with self._lock:
            self.distances = results

        return results

    def get_distances(self) -> list[float]:
        """Get the latest measured distances (thread-safe)."""
        with self._lock:
            return list(self.distances)

    def start_continuous(self, callback=None) -> None:
        """Start continuous measurement in a background thread.

        Args:
            callback: Optional function called with distances list after each scan.
        """
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._measurement_loop,
            args=(callback,),
            daemon=True,
        )
        self._thread.start()
        log.info("Continuous measurement started")

    def stop_continuous(self) -> None:
        """Stop the continuous measurement thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None
        log.info("Continuous measurement stopped")

    def _measurement_loop(self, callback) -> None:
        """Background measurement loop."""
        while self._running:
            try:
                distances = self.measure_all()
                if callback:
                    callback(distances)
            except Exception:
                log.exception("Measurement loop error")
                time.sleep(0.5)
