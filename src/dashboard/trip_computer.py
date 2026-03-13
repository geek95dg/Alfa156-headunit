"""Trip computer — distance, fuel used, average speed, range estimation."""

import time
from src.core.logger import get_logger

log = get_logger("trip_computer")


class TripComputer:
    """Tracks trip data based on OBD events.

    Subscribes to event bus for speed, fuel rate, and fuel level.
    Calculates derived values: distance, fuel used, averages, range.
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        """Reset all trip counters."""
        self._start_time = time.time()
        self.distance_km: float = 0.0
        self.fuel_used_l: float = 0.0
        self.max_speed: float = 0.0
        self._speed_sum: float = 0.0
        self._speed_samples: int = 0
        self._last_update: float = time.time()

        # Current instantaneous values
        self.speed_kmh: float = 0.0
        self.rpm: float = 0.0
        self.coolant_temp: float = 0.0
        self.fuel_level_pct: float = 50.0
        self.fuel_rate_lph: float = 0.0
        self.battery_voltage: float = 12.6
        self.instant_consumption: float = 0.0  # L/100km

    def update(self, speed_kmh: float, fuel_rate_lph: float, dt: float | None = None) -> None:
        """Update trip with new speed and fuel rate readings.

        Args:
            speed_kmh: Current speed in km/h.
            fuel_rate_lph: Current fuel consumption rate in L/h.
            dt: Time delta in seconds (auto-calculated if None).
        """
        now = time.time()
        if dt is None:
            dt = now - self._last_update
        self._last_update = now

        if dt <= 0 or dt > 5:  # skip unreasonable deltas
            return

        self.speed_kmh = speed_kmh
        self.fuel_rate_lph = fuel_rate_lph

        # Distance
        dist_increment = (speed_kmh / 3600) * dt  # km
        self.distance_km += dist_increment

        # Fuel used
        fuel_increment = (fuel_rate_lph / 3600) * dt  # liters
        self.fuel_used_l += fuel_increment

        # Speed statistics
        if speed_kmh > 0:
            self._speed_sum += speed_kmh
            self._speed_samples += 1
            if speed_kmh > self.max_speed:
                self.max_speed = speed_kmh

        # Instant consumption (L/100km)
        if speed_kmh > 3:
            self.instant_consumption = (fuel_rate_lph / speed_kmh) * 100
        else:
            self.instant_consumption = 0.0

    @property
    def avg_speed(self) -> float:
        """Average speed in km/h."""
        if self._speed_samples == 0:
            return 0.0
        return self._speed_sum / self._speed_samples

    @property
    def avg_consumption(self) -> float:
        """Average fuel consumption in L/100km."""
        if self.distance_km < 0.01:
            return 0.0
        return (self.fuel_used_l / self.distance_km) * 100

    @property
    def estimated_range_km(self) -> float:
        """Estimated range in km based on current fuel level and avg consumption."""
        if self.avg_consumption <= 0:
            return 0.0
        # Assume 58L tank for Alfa 156 1.9 JTD
        tank_capacity = 58.0
        remaining_fuel = tank_capacity * (self.fuel_level_pct / 100.0)
        return (remaining_fuel / self.avg_consumption) * 100

    @property
    def trip_time_seconds(self) -> float:
        """Trip elapsed time in seconds."""
        return time.time() - self._start_time

    @property
    def trip_time_str(self) -> str:
        """Trip time as HH:MM:SS string."""
        t = int(self.trip_time_seconds)
        h, remainder = divmod(t, 3600)
        m, s = divmod(remainder, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"
