"""Trip computer — distance, fuel used, average speed, range estimation.

Also holds the optional *travel plan* state (destination, precomputed
route, predicted fuel, waypoint weather, incidents). The travel plan
fields are populated by :meth:`TripComputer.set_destination`, which
delegates heavy lifting to :class:`src.trip.route_planner.RoutePlanner`
running in a background thread so the OBD event handler never blocks.
"""

import threading
import time
from typing import Any, Optional

from src.core.logger import get_logger

log = get_logger("trip_computer")


class TripComputer:
    """Tracks trip data based on OBD events.

    Subscribes to event bus for speed, fuel rate, and fuel level.
    Calculates derived values: distance, fuel used, averages, range.
    """

    def __init__(self, event_bus: Any = None,
                 route_planner: Any = None) -> None:
        self._bus = event_bus
        self._planner = route_planner
        self._plan_lock = threading.Lock()
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

        # Travel-plan state — populated by set_destination(). None means
        # no plan active; the UI falls back to live trip stats.
        self.destination_name: Optional[str] = None
        self.destination_lat: Optional[float] = None
        self.destination_lon: Optional[float] = None
        self.route_distance_km: float = 0.0
        self.route_eta_min: float = 0.0
        self.predicted_fuel_l: float = 0.0
        self.route_geometry: list = []
        self.route_waypoints: list = []
        self.route_weather_points: list = []
        self.route_incidents: list = []
        self.plan_error: Optional[str] = None
        self.plan_computed_at: float = 0.0

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

    # ------------------------------------------------------------------ #
    # Travel plan                                                        #
    # ------------------------------------------------------------------ #

    def set_destination(self, lat: float, lon: float, name: str,
                        origin: tuple[float, float] | None = None) -> None:
        """Start computing a travel plan to (lat, lon) in the background.

        The heavy lifting (ORS routing, TomTom lookups, weather sampling)
        happens in a worker thread so this method returns immediately.
        Results are written back to ``self`` under ``self._plan_lock``
        and published to the event bus when ready.

        Args:
            lat, lon: destination coordinates.
            name: human-readable label (shown in the UI).
            origin: optional (lat, lon) start point. If None, the last
                GPS fix from the event bus is used (or a demo default).
        """
        if self._planner is None:
            log.warning("set_destination called with no RoutePlanner — ignoring")
            return

        with self._plan_lock:
            self.destination_lat = lat
            self.destination_lon = lon
            self.destination_name = name
            self.plan_error = None

        log.info("Planning travel to %s (%.4f, %.4f)", name, lat, lon)

        if self._bus:
            self._bus.publish("trip.destination", {
                "lat": lat, "lon": lon, "name": name,
            })
            self._bus.publish("trip.planning", True)

        def _worker():
            start = origin
            if start is None:
                start = self._current_gps_or_fallback()
            try:
                result = self._planner.plan(
                    start=start,
                    dest=(lat, lon),
                    avg_consumption=self.avg_consumption,
                )
            except Exception as e:
                log.error("Route planning failed: %s", e, exc_info=True)
                result = {"error": "planner_exception"}

            with self._plan_lock:
                if result.get("error"):
                    self.plan_error = result["error"]
                else:
                    self.plan_error = None
                self.route_distance_km = float(result.get("distance_km", 0.0))
                self.route_eta_min = float(result.get("duration_min", 0.0))
                self.predicted_fuel_l = float(result.get("predicted_fuel_l", 0.0))
                self.route_geometry = list(result.get("geometry", []))
                self.route_waypoints = list(result.get("waypoints", []))
                self.route_weather_points = list(result.get("weather_points", []))
                self.route_incidents = list(result.get("incidents", []))
                self.plan_computed_at = float(result.get("computed_at", time.time()))

            if self._bus:
                self._bus.publish("trip.route", self.get_plan_dict())
                self._bus.publish("trip.planning", False)

        threading.Thread(target=_worker, daemon=True,
                         name="trip-planner").start()

    def clear_destination(self) -> None:
        """Clear the active travel plan and return to live trip stats."""
        with self._plan_lock:
            self.destination_lat = None
            self.destination_lon = None
            self.destination_name = None
            self.route_distance_km = 0.0
            self.route_eta_min = 0.0
            self.predicted_fuel_l = 0.0
            self.route_geometry = []
            self.route_waypoints = []
            self.route_weather_points = []
            self.route_incidents = []
            self.plan_error = None
            self.plan_computed_at = 0.0
        log.info("Travel plan cleared")
        if self._bus:
            self._bus.publish("trip.destination", None)
            self._bus.publish("trip.route", None)
            self._bus.publish("trip.planning", False)

    def get_plan_dict(self) -> dict:
        """Return a JSON-serialisable snapshot of the current travel plan."""
        with self._plan_lock:
            return {
                "destination_name": self.destination_name,
                "destination_lat": self.destination_lat,
                "destination_lon": self.destination_lon,
                "distance_km": self.route_distance_km,
                "eta_min": self.route_eta_min,
                "predicted_fuel_l": self.predicted_fuel_l,
                "geometry": self.route_geometry,
                "waypoints": self.route_waypoints,
                "weather_points": self.route_weather_points,
                "incidents": self.route_incidents,
                "error": self.plan_error,
                "computed_at": self.plan_computed_at,
            }

    def _current_gps_or_fallback(self) -> tuple[float, float]:
        """Best-effort origin coordinate for a travel plan.

        Uses the most recent ``gps.lat``/``gps.lon`` published on the
        event bus if available; otherwise falls back to a sensible
        default (Kraków city centre) so demo mode still produces a
        meaningful route.
        """
        if self._bus is not None:
            lat = self._bus.get_last("gps.lat")
            lon = self._bus.get_last("gps.lon")
            if lat and lon:
                return (float(lat[0]), float(lon[0]))
        return (50.0647, 19.9450)
