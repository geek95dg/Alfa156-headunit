"""Route planner — computes directions, weather along route, incidents.

This module integrates with two external APIs:

1. **OpenRouteService** (``travel.openrouteservice_key``, filled from
   ``BCM_ORS_API_KEY`` in ``/etc/bcm/bcm.env``) — free tier driving
   directions. Returns a polyline, total distance, and duration.

2. **TomTom Traffic** (``travel.tomtom_key``, ``BCM_TOMTOM_API_KEY``) — road
   incidents (road works, accidents, closures). Gracefully degrades to
   an empty list when no key is configured.

Weather along the route reuses the existing OpenWeatherMap integration
in :mod:`src.weather.weather` — we query the 5-day / 3-hour forecast
for a handful of waypoints spaced evenly along the route and match
each waypoint to the forecast slot closest to the estimated ETA at
that point.

Fuel estimates are a simple linear calculation: the caller's average
(:class:`TripComputer` with OBD), else the refuel log's average
(``fuel.stats`` ``avg_l100_overall``, src/trip/fuel_log.py — the only real
figure in the test car, which has no OBD), else 7.0 L/100 km. The plan says
which (``fuel_l100`` / ``fuel_l100_source``: ``trip`` | ``log`` | ``default``).

The weather manager comes from the constructor or, when main.py built the
planner without one (it always did — route weather was always empty), from
``weather._internals`` at plan time: the weather module may start before or
after the planner.

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
from urllib.parse import urlsplit

from src.core.logger import get_logger
from src.network import net_services

log = get_logger("trip.route_planner")

# How many evenly-spaced waypoints we sample along the route polyline
# for weather and incident lookups. 8 gives good coverage for any
# reasonable road trip in Poland without making too many HTTP calls.
WAYPOINT_COUNT = 8

# ORS & TomTom endpoints
ORS_DIRECTIONS = "https://api.openrouteservice.org/v2/directions/driving-car"
ORS_GEOCODE = "https://api.openrouteservice.org/geocode/search"
TOMTOM_INCIDENTS = "https://api.tomtom.com/traffic/services/5/incidentDetails"


#: Fallback consumption (diesel cruising, Alfa 156 1.9 JTD 8V).
DEFAULT_L100 = 7.0
#: A refuel-log average outside this range is not trusted for a plan.
LOG_L100_MIN, LOG_L100_MAX = 2.0, 30.0


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
        avg_l100 = DEFAULT_L100  # sane default
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


def _http_call(method: str, url: str, *, params: dict[str, Any] | None = None,
               body: dict[str, Any] | None = None,
               headers: dict[str, str] | None = None, timeout: float = 6.0,
               service: str = "", source: str = "") -> tuple[Optional[dict], Optional[dict]]:
    """One request → ``(parsed JSON or None, error or None)``.

    ``error`` is ``{service, result, http_code}`` with ``result`` one of
    ``http`` / ``network`` / ``bad_response`` (src/network/net_services.py
    codes). It used to be only a log line: a 401 from ORS (wrong key) looked
    exactly like "no route", and the screen never said why. With
    ``service`` the outcome is also recorded for Settings → "Internet i
    usługi". Never logs the URL's query (TomTom's key is a parameter) or
    the request headers (ORS's key is the Authorization header).
    """
    def fail(result: str, code: Optional[int] = None) -> tuple[None, dict]:
        if service:
            net_services.record(service, result, code, source=source)
        return None, {"service": service, "result": result, "http_code": code}

    try:
        import requests
    except ImportError:
        log.warning("requests library not available — route planner offline")
        return fail("network")
    host = urlsplit(url).netloc
    try:
        if method == "POST":
            r = requests.post(url, json=body, headers=headers or {}, timeout=timeout)
        else:
            r = requests.get(url, params=params or {}, headers=headers or {}, timeout=timeout)
    except Exception as e:
        # requests' exception text includes the full URL (with TomTom's key
        # in the query) — log only the type and the host.
        log.warning("HTTP error calling %s: %s", host, type(e).__name__)
        return fail("network")
    status = getattr(r, "status_code", None)
    if not isinstance(status, int) or status >= 400:
        log.warning("HTTP %s from %s: %s", status, host,
                    str(getattr(r, "text", ""))[:200].replace("\n", " "))
        return fail("http", status if isinstance(status, int) else None)
    try:
        data = r.json()
    except Exception:
        log.warning("Invalid JSON from %s", host)
        return fail("bad_response")
    if not isinstance(data, dict):
        return fail("bad_response")
    if service:
        net_services.record(service, "ok", source=source)
    return data, None


def _http_get(url: str, params: dict[str, Any] | None = None,
              headers: dict[str, str] | None = None,
              timeout: float = 6.0) -> Optional[dict]:
    """GET returning parsed JSON or None (kept for callers that do not care why)."""
    return _http_call("GET", url, params=params, headers=headers, timeout=timeout)[0]


def _http_post(url: str, body: dict[str, Any],
               headers: dict[str, str] | None = None,
               timeout: float = 10.0) -> Optional[dict]:
    """POST wrapper — ORS directions API requires POST with JSON body."""
    return _http_call("POST", url, body=body, headers=headers, timeout=timeout)[0]


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

        self._ors_key = str(config.get("travel.openrouteservice_key", "") or "").strip()
        self._tomtom_key = str(config.get("travel.tomtom_key", "") or "").strip()
        if self._ors_key:
            log.info(
                "RoutePlanner initialised (ors=on, tomtom=%s)",
                "on" if self._tomtom_key else "off",
            )
        else:
            # Bez klucza planer nie liczy trasy — zwraca odległość w linii
            # prostej. Wygląda to jak działająca funkcja i dlatego jest gorsze
            # niż jawny błąd: dostajesz liczbę, która po prostu kłamie
            # (w mieście potrafi zaniżyć czas przejazdu dwukrotnie).
            log.error(
                "RoutePlanner: brak travel.openrouteservice_key — trasy będą "
                "liczone W LINII PROSTEJ, bez dróg i bez realnego czasu "
                "przejazdu. Załóż darmowe konto na openrouteservice.org i "
                "wpisz klucz do /etc/bcm/bcm.env jako BCM_ORS_API_KEY "
                "(config/bcm.env.example)."
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
            approximate        bool                    (True = brak klucza ORS,
                                                        odległość w linii prostej)
        """
        # Errors of THIS plan (``service_errors`` in the result): one entry
        # per failing service, so trip.js can say "ORS: błąd 401" instead of
        # an empty route. A local list, not an attribute: the trip computer
        # starts a worker per destination change / GPS replan, so two plans
        # can overlap and must not see each other's errors.
        errors: list[dict] = []
        route = self._fetch_route(start, dest, errors)
        if not route:
            return {
                "error": "route_unavailable",
                "service_errors": list(errors),
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
        incidents = self._fetch_incidents(bbox, errors) if self._tomtom_key else []

        l100, l100_source = self._consumption(avg_consumption)
        predicted_fuel = estimate_fuel(dist_km, l100)

        return {
            "fuel_l100": round(l100, 2),
            "fuel_l100_source": l100_source,
            "approximate": bool(route.get("approximate")),
            "distance_km": round(dist_km, 1),
            "duration_min": round(duration_min, 1),
            "geometry": geometry,
            "waypoints": [{"lat": lat, "lon": lon} for lat, lon in samples],
            "weather_points": weather_points,
            "incidents": incidents,
            "predicted_fuel_l": predicted_fuel,
            "computed_at": time.time(),
            "service_errors": list(errors),
        }

    def _consumption(self, avg_consumption: Any) -> tuple[float, str]:
        """L/100 km for the fuel estimate and where it came from."""
        if isinstance(avg_consumption, (int, float)) and not isinstance(avg_consumption, bool) \
                and math.isfinite(avg_consumption) and avg_consumption > 0:
            return float(avg_consumption), "trip"
        last = self._bus.get_last("fuel.stats") if self._bus is not None else None
        stats = last[0] if last and isinstance(last[0], dict) else {}
        avg = stats.get("avg_l100_overall")
        if isinstance(avg, (int, float)) and not isinstance(avg, bool) \
                and math.isfinite(avg) and LOG_L100_MIN <= avg <= LOG_L100_MAX:
            return float(avg), "log"
        return DEFAULT_L100, "default"

    def _weather_manager(self) -> Any:
        """Constructor's manager, else the running one (weather._internals)."""
        if self._weather is not None:
            return self._weather
        last = self._bus.get_last("weather._internals") if self._bus is not None else None
        if last and isinstance(last[0], dict):
            return last[0].get("manager")
        return None

    # ------------------------------------------------------------------ #
    # ORS directions                                                     #
    # ------------------------------------------------------------------ #

    def _fetch_route(self, start: tuple[float, float],
                     dest: tuple[float, float],
                     errors: Optional[list[dict]] = None) -> Optional[dict]:
        if not self._ors_key:
            log.warning("No OpenRouteService key — straight-line estimate only")
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
        data, err = _http_call("POST", f"{ORS_DIRECTIONS}/geojson", body=body,
                               headers=headers, timeout=10.0, service="ors", source="route")
        if err is not None:
            if errors is not None:
                errors.append(err)
            return None
        if not data.get("features"):
            # 200 without a route: points ORS cannot route between (sea,
            # > 6000 km). Not a key problem — no service error.
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
            # Oznaczone, żeby UI mogło to nazwać po imieniu. Bez tej flagi
            # ekran pokazuje liczbę nieodróżnialną od prawdziwej trasy.
            "approximate": True,
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
        manager = self._weather_manager()
        for i, (lat, lon) in enumerate(samples):
            eta_min = (duration_min / max(1, len(samples) - 1)) * i
            entry = {
                "lat": lat, "lon": lon,
                "eta_min": round(eta_min, 1),
                "condition": "unknown",
                "temp": None,
                "rain_mm": 0.0,
            }
            if manager is not None:
                try:
                    forecast = manager.forecast_at(lat, lon, eta_min)
                    if forecast:
                        entry.update({
                            "condition": forecast.get("condition", "unknown"),
                            "temp": forecast.get("temp"),
                            "rain_mm": forecast.get("rain_mm", 0.0),
                            "icon": forecast.get("icon"),
                        })
                except Exception as e:
                    log.debug("forecast_at failed for %s,%s: %s", lat, lon, e)
            result.append(entry)
        return result

    # ------------------------------------------------------------------ #
    # TomTom incidents                                                   #
    # ------------------------------------------------------------------ #

    def _fetch_incidents(self, bbox: tuple[float, float, float, float],
                         errors: Optional[list[dict]] = None) -> list[dict]:
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
        data, err = _http_call("GET", TOMTOM_INCIDENTS, params=params,
                               service="tomtom", source="incidents")
        if err is not None:
            if errors is not None:
                errors.append(err)
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
