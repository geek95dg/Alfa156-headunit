"""Route planner — computes directions, weather along route, incidents.

This module integrates with two external APIs:

1. **OpenRouteService** (``ors_api_key`` in config) — free tier driving
   directions. Returns a polyline, total distance, and duration.

2. **TomTom Traffic** (``tomtom_api_key`` in config) — paid tier road
   incidents (road works, accidents, closures). Gracefully degrades to
   an empty list when no key is configured.

Weather along the route reuses the existing OpenWeatherMap integration
in :mod:`src.weather.weather` — we query the 5-day / 3-hour forecast
for a handful of waypoints spaced evenly along the route and match
each waypoint to the forecast slot closest to the estimated ETA at
that point.

Fuel estimates are a simple linear calculation based on the live
average consumption (L/100km) reported by :class:`TripComputer`.

Design goals:
- All network calls isolated behind the ``_http_get`` wrapper so tests
  can monkey-patch.
- Pure helpers (``estimate_fuel``, ``sample_waypoints``) have no
  side-effects and are unit-testable.
- The planner does *not* mutate ``TripComputer`` directly; it returns
  a dict that ``TripComputer.set_destination()`` stores and publishes.
"""

from __future__ import annotations

import math
import time
from typing import Any, Optional

from src.core.logger import get_logger

log = get_logger("trip.route_planner")

# How many evenly-spaced waypoints we sample along the route polyline
# for weather and incident lookups. 8 gives good coverage for any
# reasonable road trip in Poland without making too many HTTP calls.
WAYPOINT_COUNT = 8

# ORS & TomTom endpoints
ORS_DIRECTIONS = "https://api.openrouteservice.org/v2/directions/driving-car"
ORS_GEOCODE = "https://api.openrouteservice.org/geocode/search"
TOMTOM_INCIDENTS = "https://api.tomtom.com/traffic/services/5/incidentDetails"


# ---------------------------------------------------------------------- #
# Pure helpers (no network)                                              #
# ---------------------------------------------------------------------- #


def estimate_fuel(distance_km: float, avg_l100: float) -> float:
    """Return predicted litres for ``distance_km`` at ``avg_l100`` L/100km.

    ``avg_l100`` is the trip computer's running average. Falls back to
    7.0 L/100km (a reasonable diesel cruising figure for the Alfa 156
    1.9 JTD 8V) if the trip computer has no data yet.
    """
    if distance_km <= 0:
        return 0.0
    if avg_l100 <= 0:
        avg_l100 = 7.0  # sane default
    return round(distance_km * avg_l100 / 100.0, 2)


def sample_waypoints(geometry: list[tuple[float, float]],
                     count: int = WAYPOINT_COUNT) -> list[tuple[float, float]]:
    """Return ``count`` evenly spaced (lat, lon) samples from ``geometry``.

    ``geometry`` is an ordered list of (lat, lon) tuples from ORS.
    The result always includes the first and last point so the
    planner shows the start and end weather even for short routes.
    """
    n = len(geometry)
    if n == 0:
        return []
    if n <= count:
        return list(geometry)
    step = (n - 1) / (count - 1)
    return [geometry[round(i * step)] for i in range(count)]


def _haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Return the great-circle distance between two (lat, lon) points in km."""
    R = 6371.0
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


# ---------------------------------------------------------------------- #
# HTTP wrapper                                                           #
# ---------------------------------------------------------------------- #


def _http_get(url: str, params: dict[str, Any] | None = None,
              headers: dict[str, str] | None = None,
              timeout: float = 6.0) -> Optional[dict]:
    """Thin wrapper around ``requests.get`` that returns parsed JSON or None."""
    try:
        import requests
    except ImportError:
        log.warning("requests library not available — route planner offline")
        return None
    try:
        r = requests.get(url, params=params or {}, headers=headers or {}, timeout=timeout)
        if r.status_code >= 400:
            log.warning("HTTP %s from %s: %s", r.status_code, url, r.text[:200])
            return None
        return r.json()
    except Exception as e:
        log.warning("HTTP error calling %s: %s", url, e)
        return None


def _http_post(url: str, body: dict[str, Any],
               headers: dict[str, str] | None = None,
               timeout: float = 10.0) -> Optional[dict]:
    """POST wrapper — ORS directions API requires POST with JSON body."""
    try:
        import requests
    except ImportError:
        return None
    try:
        r = requests.post(url, json=body, headers=headers or {}, timeout=timeout)
        if r.status_code >= 400:
            log.warning("HTTP %s from %s: %s", r.status_code, url, r.text[:200])
            return None
        return r.json()
    except Exception as e:
        log.warning("HTTP error calling %s: %s", url, e)
        return None


# ---------------------------------------------------------------------- #
# RoutePlanner                                                           #
# ---------------------------------------------------------------------- #


class RoutePlanner:
    """Compute travel plans: route, weather, incidents, fuel estimate."""

    def __init__(self, config: Any, event_bus: Any = None,
                 weather_manager: Any = None):
        self._config = config
        self._bus = event_bus
        self._weather = weather_manager

        self._ors_key = str(config.get("travel.openrouteservice_key", "") or "")
        self._tomtom_key = str(config.get("travel.tomtom_key", "") or "")

        log.info(
            "RoutePlanner initialised (ors=%s, tomtom=%s)",
            "on" if self._ors_key else "off",
            "on" if self._tomtom_key else "off",
        )

    # ------------------------------------------------------------------ #
    # Public API                                                         #
    # ------------------------------------------------------------------ #

    def plan(self, start: tuple[float, float],
             dest: tuple[float, float],
             avg_consumption: float = 0.0) -> dict:
        """Compute a full travel plan from ``start`` to ``dest``.

        Returns a dict with the following keys:
            distance_km        float
            duration_min       float
            geometry           list[[lat, lon], ...]   (ORS polyline)
            waypoints          list[{lat, lon}]        (sampled for weather)
            weather_points     list[dict]              (one per waypoint)
            incidents          list[dict]              (TomTom or [])
            predicted_fuel_l   float                   (distance * avg/100)
            computed_at        float                   (unix ts)
        """
        route = self._fetch_route(start, dest)
        if not route:
            return {
                "error": "route_unavailable",
                "distance_km": 0.0,
                "duration_min": 0.0,
                "geometry": [],
                "waypoints": [],
                "weather_points": [],
                "incidents": [],
                "predicted_fuel_l": 0.0,
                "computed_at": time.time(),
            }

        dist_km = route["distance_km"]
        duration_min = route["duration_min"]
        geometry = route["geometry"]

        samples = sample_waypoints(geometry, WAYPOINT_COUNT)
        weather_points = self._weather_along_route(samples, duration_min)

        # Incidents fetched once for the bounding box of the whole route.
        bbox = _bounding_box(geometry)
        incidents = self._fetch_incidents(bbox) if self._tomtom_key else []

        predicted_fuel = estimate_fuel(dist_km, avg_consumption)

        return {
            "distance_km": round(dist_km, 1),
            "duration_min": round(duration_min, 1),
            "geometry": geometry,
            "waypoints": [{"lat": lat, "lon": lon} for lat, lon in samples],
            "weather_points": weather_points,
            "incidents": incidents,
            "predicted_fuel_l": predicted_fuel,
            "computed_at": time.time(),
        }

    # ------------------------------------------------------------------ #
    # ORS directions                                                     #
    # ------------------------------------------------------------------ #

    def _fetch_route(self, start: tuple[float, float],
                     dest: tuple[float, float]) -> Optional[dict]:
        if not self._ors_key:
            log.info("No OpenRouteService key — skipping real routing, "
                     "using straight-line estimate")
            return self._straight_line_fallback(start, dest)

        body = {
            "coordinates": [
                [start[1], start[0]],  # ORS wants [lon, lat]
                [dest[1], dest[0]],
            ],
            "instructions": False,
            "units": "km",
        }
        headers = {
            "Authorization": self._ors_key,
            "Content-Type": "application/json",
        }
        data = _http_post(f"{ORS_DIRECTIONS}/geojson", body, headers=headers)
        if not data or not data.get("features"):
            return None
        feat = data["features"][0]
        props = feat.get("properties", {}) or {}
        summary = props.get("summary", {}) or {}
        coords_lonlat = feat.get("geometry", {}).get("coordinates", [])
        geometry = [(pt[1], pt[0]) for pt in coords_lonlat]
        return {
            "distance_km": float(summary.get("distance", 0.0)),
            "duration_min": float(summary.get("duration", 0.0)) / 60.0,
            "geometry": geometry,
        }

    def _straight_line_fallback(self, start: tuple[float, float],
                                dest: tuple[float, float]) -> dict:
        """Used when no ORS key is available — straight line 'route'.

        Returns a 2-point geometry with a haversine distance and an
        80 km/h assumed average to get a rough ETA. This lets the UI
        still show something useful during development.
        """
        dist = _haversine_km(start, dest)
        return {
            "distance_km": dist,
            "duration_min": dist / 80.0 * 60.0,
            "geometry": [start, dest],
        }

    # ------------------------------------------------------------------ #
    # Weather along route                                                #
    # ------------------------------------------------------------------ #

    def _weather_along_route(self, samples: list[tuple[float, float]],
                             duration_min: float) -> list[dict]:
        """Return weather summary for each sampled waypoint.

        Uses the shared WeatherManager when available; otherwise falls
        back to a single OpenWeatherMap /forecast call per waypoint
        (rate-limited and costly — prefer sharing the manager).
        """
        if not samples:
            return []
        result: list[dict] = []
        for i, (lat, lon) in enumerate(samples):
            eta_min = (duration_min / max(1, len(samples) - 1)) * i
            entry = {
                "lat": lat, "lon": lon,
                "eta_min": round(eta_min, 1),
                "condition": "unknown",
                "temp": None,
                "rain_mm": 0.0,
            }
            if self._weather:
                try:
                    forecast = self._weather.forecast_at(lat, lon, eta_min)
                    if forecast:
                        entry.update({
                            "condition": forecast.get("condition", "unknown"),
                            "temp": forecast.get("temp"),
                            "rain_mm": forecast.get("rain_mm", 0.0),
                            "icon": forecast.get("icon"),
                        })
                except AttributeError:
                    # WeatherManager doesn't implement forecast_at yet —
                    # graceful degradation until Phase 13 adds it.
                    pass
                except Exception as e:
                    log.debug("forecast_at failed for %s,%s: %s", lat, lon, e)
            result.append(entry)
        return result

    # ------------------------------------------------------------------ #
    # TomTom incidents                                                   #
    # ------------------------------------------------------------------ #

    def _fetch_incidents(self, bbox: tuple[float, float, float, float]) -> list[dict]:
        """Query TomTom incidents inside the given lat/lon bounding box.

        bbox is (min_lat, min_lon, max_lat, max_lon).
        """
        if not self._tomtom_key:
            return []
        params = {
            "key": self._tomtom_key,
            "bbox": f"{bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]}",  # TomTom wants lon,lat,lon,lat
            "fields": "{incidents{type,geometry{type,coordinates},properties{iconCategory,magnitudeOfDelay,events{description,code,iconCategory}}}}",
            "language": "pl-PL",
            "categoryFilter": "0,1,6,7,8,9,10,11",  # road closures, works, accidents
            "timeValidityFilter": "present",
        }
        data = _http_get(TOMTOM_INCIDENTS, params=params)
        if not data:
            return []
        incidents: list[dict] = []
        for inc in data.get("incidents", []) or []:
            props = inc.get("properties", {}) or {}
            events = props.get("events", []) or []
            if not events:
                continue
            incidents.append({
                "description": events[0].get("description", ""),
                "icon_category": props.get("iconCategory"),
                "delay_magnitude": props.get("magnitudeOfDelay"),
            })
        return incidents


def _bounding_box(geometry: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    """Return (min_lat, min_lon, max_lat, max_lon) for a polyline."""
    if not geometry:
        return (0.0, 0.0, 0.0, 0.0)
    lats = [p[0] for p in geometry]
    lons = [p[1] for p in geometry]
    return (min(lats), min(lons), max(lats), max(lons))
