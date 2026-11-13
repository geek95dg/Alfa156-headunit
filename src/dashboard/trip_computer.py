"""Trip computer — distance, fuel used, average speed, range estimation.

Also holds the optional *travel plan* state (destination, precomputed
route, predicted fuel, waypoint weather, incidents). The travel plan
fields are populated by :meth:`TripComputer.set_destination`, which
delegates heavy lifting to :class:`src.trip.route_planner.RoutePlanner`
running in a background thread so the OBD event handler never blocks.

Route origin: the current GPS fix when there is a fresh one, otherwise a
fixed fallback (Kraków city centre). The plan says which
(``origin_source``: ``gps`` | ``fallback`` | ``given``, plus
``origin_lat/origin_lon``) — it used to fall back silently, and a route from
Kraków looks like a real one. When ``gps.fix`` turns True while the active
plan started from the fallback, the same destination is planned once more
from the GPS position (after :data:`REPLAN_DELAY_S`, see _on_gps_fix).
"""

import math
import threading
import time
from typing import Any, Optional

from src.core.logger import get_logger

log = get_logger("trip_computer")

#: A GPS position older than this is not used as the route origin.
GPS_MAX_AGE_S = 30.0
#: Route origin when there is no fresh GPS fix (Kraków city centre).
FALLBACK_ORIGIN = (50.0647, 19.9450)
#: Delay between ``gps.fix`` → True and the re-plan from the GPS position.
#: The GPS module publishes gps.fix BEFORE gps.lat/gps.lon of the same fix,
#: and on the async bus our callback may run in between; the delay also
#: merges a fix that flaps in a tunnel into one re-plan.
REPLAN_DELAY_S = 3.0


def _start_daemon(target, name: str) -> None:
    threading.Thread(target=target, daemon=True, name=name).start()


def _start_timer(delay: float, target) -> None:
    timer = threading.Timer(delay, target)
    timer.daemon = True
    timer.start()


def _finite(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


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
        # Bumped by every new plan / clear / reset (under _plan_lock): a
        # planner worker or a scheduled re-plan that belongs to an older
        # plan must not write over the current one.
        self._plan_seq = 0
        self._replan_scheduled = False
        # Seams for tests (no threads there): run a worker / a delayed call.
        self._start_worker = _start_daemon
        self._schedule = _start_timer
        self.reset()
        if event_bus is not None:
            event_bus.subscribe("gps.fix", self._on_gps_fix)

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
        self.route_approximate: bool = False
        self.plan_error: Optional[str] = None
        self.plan_computed_at: float = 0.0
        # Where the active plan's route starts (see the module docstring).
        self.origin_source: Optional[str] = None
        self.origin_lat: Optional[float] = None
        self.origin_lon: Optional[float] = None
        with self._plan_lock:
            self._plan_seq += 1

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
            self._plan_seq += 1
            seq = self._plan_seq
            self.destination_lat = lat
            self.destination_lon = lon
            self.destination_name = name
            self.plan_error = None
            self.origin_source = None
            self.origin_lat = None
            self.origin_lon = None

        log.info("Planning travel to %s (%.4f, %.4f)", name, lat, lon)

        if self._bus:
            self._bus.publish("trip.destination", {
                "lat": lat, "lon": lon, "name": name,
            })
            self._bus.publish("trip.planning", True)

        def _worker():
            if origin is not None:
                start, source = origin, "given"
            else:
                start, source = self._current_gps_or_fallback()
            log.info("Route origin: %s (%.4f, %.4f)", source, start[0], start[1])
            with self._plan_lock:
                stale = seq != self._plan_seq
                idle = self.destination_lat is None
                if not stale:
                    # Set before planning: a gps.fix during the (slow) planner
                    # call must already see that this plan starts from fallback.
                    self.origin_source = source
                    self.origin_lat, self.origin_lon = float(start[0]), float(start[1])
            if stale:                           # replaced before it started
                self._stale_worker_done(idle)
                return
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
                stale = seq != self._plan_seq
                idle = self.destination_lat is None
                if not stale:
                    self.plan_error = result["error"] if result.get("error") else None
                    self.route_distance_km = float(result.get("distance_km", 0.0))
                    self.route_eta_min = float(result.get("duration_min", 0.0))
                    self.predicted_fuel_l = float(result.get("predicted_fuel_l", 0.0))
                    self.route_geometry = list(result.get("geometry", []))
                    self.route_waypoints = list(result.get("waypoints", []))
                    self.route_weather_points = list(result.get("weather_points", []))
                    self.route_incidents = list(result.get("incidents", []))
                    # True gdy planer nie miał klucza ORS i policzył linię prostą.
                    # UI musi to nazwać, bo sama liczba wygląda jak realna trasa.
                    self.route_approximate = bool(result.get("approximate", False))
                    self.plan_computed_at = float(result.get("computed_at", time.time()))
            if stale:
                # A newer plan (or a clear) came in meanwhile — its own
                # worker publishes; this result belongs to the old one.
                log.info("Route plan to %s superseded — result dropped", name)
                self._stale_worker_done(idle)
                return

            if self._bus:
                self._bus.publish("trip.route", self.get_plan_dict())
                self._bus.publish("trip.planning", False)

        self._start_worker(_worker, "trip-planner")

    def _stale_worker_done(self, idle: bool) -> None:
        """A superseded worker ends. A newer plan publishes its own result;
        after a clear/reset (no destination) nobody else would end the
        "Computing route…" state, so do it here."""
        if idle and self._bus:
            self._bus.publish("trip.planning", False)

    def clear_destination(self) -> None:
        """Clear the active travel plan and return to live trip stats."""
        with self._plan_lock:
            self._plan_seq += 1
            self.destination_lat = None
            self.destination_lon = None
            self.destination_name = None
            self.origin_source = None
            self.origin_lat = None
            self.origin_lon = None
            self.route_distance_km = 0.0
            self.route_eta_min = 0.0
            self.predicted_fuel_l = 0.0
            self.route_geometry = []
            self.route_waypoints = []
            self.route_weather_points = []
            self.route_incidents = []
            self.route_approximate = False
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
                "approximate": self.route_approximate,
                "error": self.plan_error,
                "computed_at": self.plan_computed_at,
                "origin_source": self.origin_source,
                "origin_lat": self.origin_lat,
                "origin_lon": self.origin_lon,
            }

    def _on_gps_fix(self, topic: str, value: Any, timestamp: float) -> None:
        """``gps.fix`` → True: re-plan once if the active plan used the fallback.

        Event-bus callback: only schedules (no planning, no network here).
        At most one re-plan is pending; it is bound to the plan it was
        scheduled for (``_plan_seq``), so a new destination or a clear in
        the meantime cancels it.
        """
        if value is not True:
            return
        with self._plan_lock:
            if self.destination_lat is None or self.origin_source != "fallback" \
                    or self._replan_scheduled:
                return
            self._replan_scheduled = True
            seq = self._plan_seq
        log.info("GPS fix acquired — re-planning the route from the GPS position "
                 "in %.0f s (it started from the fallback origin)", REPLAN_DELAY_S)
        self._schedule(REPLAN_DELAY_S, lambda: self._replan_from_gps(seq))

    def _replan_from_gps(self, seq: int) -> None:
        """The delayed half of _on_gps_fix (timer thread)."""
        with self._plan_lock:
            self._replan_scheduled = False
            if seq != self._plan_seq or self.destination_lat is None \
                    or self.origin_source != "fallback":
                return
            lat, lon = self.destination_lat, self.destination_lon
            name = self.destination_name or "Destination"
        _coords, source = self._current_gps_or_fallback()
        if source != "gps":
            # Fix reported but no fresh position yet (or lost again): keep
            # the plan; the next gps.fix edge tries again.
            log.info("Route re-plan skipped — no fresh GPS position yet")
            return
        self.set_destination(lat, lon, name)

    def _current_gps_or_fallback(self) -> tuple[tuple[float, float], str]:
        """Best-effort origin for a travel plan: ``((lat, lon), source)``.

        ``source`` is ``"gps"`` or ``"fallback"``. Uses ``gps.lat``/
        ``gps.lon`` only while ``gps.fix`` is True and both are younger than
        :data:`GPS_MAX_AGE_S` — the bus keeps the last value until restart,
        and a position from before the fix was lost (phone taken out of the
        car, GPS app killed) can be kilometres off. Otherwise falls back to
        :data:`FALLBACK_ORIGIN` (Kraków city centre) so demo mode still
        produces a meaningful route — and the plan says so.
        """
        if self._bus is not None:
            fix = self._bus.get_last("gps.fix")
            lat = self._bus.get_last("gps.lat")
            lon = self._bus.get_last("gps.lon")
            if fix and fix[0] is True and lat and lon:
                now = time.time()
                fresh = all(-5.0 <= now - item[1] < GPS_MAX_AGE_S for item in (lat, lon))
                coords = (_finite(lat[0]), _finite(lon[0]))
                if fresh and None not in coords and abs(coords[0]) <= 90 \
                        and abs(coords[1]) <= 180:
                    return coords, "gps"
        return FALLBACK_ORIGIN, "fallback"
