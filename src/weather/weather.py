"""Weather data module — fetches weather from OpenWeatherMap API.

Subscribes to gps.position for coordinates (plausible fixes only), requires
an uplink: lte.connected, net.phone_tether=connected, or the x86 platform.
Polls every 15 minutes (configurable). Caches last response to disk.
On x86 without API key: returns hardcoded Milan demo weather data.

Failed fetches back off: 60 s, 120 s, … up to the poll interval. (It used to
retry every ~5 s while offline — nothing was ever fetched successfully, so
"time since the last fetch" never stopped being due.) Scheduling uses a
monotonic clock: bcm-timesync may move the wall clock by hours, which must
neither stall the poller nor trigger a burst of requests.

When the phone's Bluetooth internet comes up (net.phone_tether, see
src/network/phone_tether.py) a fetch is forced — usually the first moment of
the drive real data can be had.

Location — what wins
--------------------
* No GPS yet: ``weather.default_lat/lon``. The boot fetch (and the one forced
  by the phone's internet) usually happens before the phone's GPS app has
  sent anything, so it is for the default city.
* The FIRST plausible GPS fix after such a default-location fetch forces one
  immediate re-fetch, whatever the fetch's age (it used to wait for the next
  poll — up to 15 min of weather for the wrong city). Only once per process:
  later fixes (also after a GPS outage) never force again.
* While driving: one re-fetch when the car is more than
  ``weather.refetch_distance_km`` (default 15, 0 = off) from where the last
  GPS-based fetch was made — at most once per fetched location.
* City search (A4): its immediate fetch is for the searched place, and that
  place stays until the next REGULAR poll (``poll_interval_min``): neither the
  first-fix force nor the distance re-fetch overrides it. The regular poll
  then uses the GPS again if there is a fix (without GPS the searched place
  simply stays, as it always has).

Publishes to event bus:
    weather.current  — dict with condition, temp, feels_like, humidity, wind
    weather.forecast — list of daily forecast dicts
    weather.city     — str
"""

import json
import math
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlencode

from src.core.fsutil import atomic_write_json
from src.core.logger import get_logger

log = get_logger("weather")

#: First retry after a failed fetch; doubles up to the poll interval.
RETRY_MIN_S = 60
#: How often the poller re-checks its conditions (events wake it sooner).
LOOP_S = 5
#: A forced fetch is skipped if good data arrived less than this long ago
#: (a flapping PAN link must not turn into a request storm).
FORCE_MIN_AGE_S = 60
#: Default for ``weather.refetch_distance_km`` (0 disables the re-fetch).
REFETCH_DISTANCE_KM = 15.0
#: Location sources a fetch can be made for (``_loc_source``).
LOC_DEFAULT, LOC_GPS, LOC_SEARCH = "default", "gps", "search"


def _distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance in km (haversine; plenty for "moved 15 km")."""
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 2 * 6371.0 * math.asin(min(1.0, math.sqrt(h)))


def _refetch_distance(value: Any) -> float:
    """``weather.refetch_distance_km`` → km >= 0; anything else → default."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        if value is not None:
            log.warning("weather.refetch_distance_km=%r is not a number — using %g",
                        value, REFETCH_DISTANCE_KM)
        return REFETCH_DISTANCE_KM
    value = float(value)
    if not math.isfinite(value) or value < 0:
        log.warning("weather.refetch_distance_km=%r is out of range — using %g",
                    value, REFETCH_DISTANCE_KM)
        return REFETCH_DISTANCE_KM
    return value


def valid_coords(lat: Any, lon: Any) -> Optional[tuple[float, float]]:
    """``(lat, lon)`` as floats if both are finite and in range, else None.

    The values go into the OpenWeatherMap URL; the search location comes
    from the browser, so nothing but a real coordinate may pass.
    """
    out = []
    for value, limit in ((lat, 90.0), (lon, 180.0)):
        if isinstance(value, bool):
            return None
        if not isinstance(value, (int, float, str)):
            return None
        try:
            value = float(value.strip() if isinstance(value, str) else value)
        except (ValueError, OverflowError):     # OverflowError: a 400-digit int
            return None
        if not math.isfinite(value) or abs(value) > limit:
            return None
        out.append(value)
    return out[0], out[1]


def _plausible_fix(value: Any) -> Optional[tuple[float, float]]:
    """Coordinates from a ``gps.position`` payload worth using, else None.

    A receiver without a fix reports 0,0 (and the payload may say
    ``fix: False``) — weather for the Gulf of Guinea is not what the driver
    wants, so those are ignored and the last good / default location stays.
    """
    if not isinstance(value, dict) or value.get("fix", True) is False:
        return None
    coords = valid_coords(value.get("lat"), value.get("lon"))
    if coords is None or (coords[0] == 0.0 and coords[1] == 0.0):
        return None
    return coords

CACHE_DIR = Path.home() / ".cache" / "bcm"
CACHE_FILE = CACHE_DIR / "weather.json"

# Demo weather data for Milan
DEMO_WEATHER = {
    "current": {
        "condition": "Partly Cloudy",
        "icon": "02d",
        "temp": 22.0,
        "feels_like": 24.0,
        "humidity": 42,
        "wind_speed": 12.0,
        "wind_deg": 180,
        "pressure": 1015,
    },
    "city": "Milan, IT",
    "forecast": [
        {"day": "Today", "high": 26, "low": 18, "condition": "Partly Cloudy", "icon": "02d"},
        {"day": "Wed", "high": 22, "low": 15, "condition": "Cloudy", "icon": "04d"},
        {"day": "Thu", "high": 19, "low": 13, "condition": "Light Rain", "icon": "10d"},
    ],
}


class WeatherManager:
    """Fetches and publishes weather data.

    Args:
        event_bus: EventBus instance.
        config: BCM config dict with weather.* settings.
        platform: "opi" or "x86".
    """

    def __init__(self, event_bus, config: dict, platform: str = "x86",
                 clock: Callable[[], float] = time.monotonic):
        self._bus = event_bus
        self._config = config
        self._platform = platform
        self._clock = clock
        self._running = False
        self._thread = None
        self._lat = 0.0
        self._lon = 0.0
        # True once _lat/_lon hold a location that is not the default (a GPS
        # fix or a searched city); _loc_source says which.
        self._has_gps = False
        self._loc_source = LOC_DEFAULT
        # _lat/_lon/_has_gps/_loc_source change together on the bus thread
        # (GPS, search) and are read together by the poller (_location()):
        # a fix landing between separate reads made a default-coordinates
        # fetch look like a GPS one (and skipped the first-fix force).
        self._loc_lock = threading.Lock()
        # What the last GOOD fetch was made for (None = none yet) and where —
        # the first-fix force and the distance re-fetch compare with these.
        self._fetch_source: Optional[str] = None
        self._fetched_coords: Optional[tuple[float, float]] = None
        # One-shot: the "first GPS fix after a default-location fetch" force
        # has been claimed (under _sched_lock — the bus thread and the
        # poller can both see the condition at once).
        self._gps_upgrade_done = False
        # A distance re-fetch was forced for the current _fetched_coords;
        # cleared by the next good fetch, so a failing fetch cannot turn
        # 1 Hz GPS updates into 1 Hz forces (each would reset the backoff).
        self._distance_force_pending = False
        self._search_coords: Optional[tuple[float, float]] = None
        self._lte_connected = False
        self._tether_connected = False
        self._last_fetch = 0          # wall time of the last good fetch (info only)
        # Scheduling, all on self._clock (monotonic):
        self._next_fetch = 0.0        # 0 = as soon as the conditions allow
        self._retry_delay = RETRY_MIN_S
        self._last_success: Optional[float] = None
        self._state_logged = False
        self._wake = threading.Event()
        # force_fetch() runs on the event-bus dispatcher while the poller may
        # be inside a fetch. _force_gen counts forces; a fetch that fails
        # after a force arrived must not push the forced retry out by the
        # backoff (the force usually means "the uplink just came up").
        self._sched_lock = threading.Lock()
        self._force_gen = 0
        # Counts forces that must survive a fetch already in flight (the
        # first-GPS-fix one, ignore_min_age): a good fetch for the OLD
        # location must not push them out to the next poll (_fetch_succeeded).
        self._urgent_gen = 0
        self._poll_interval = config.get("weather", {}).get("poll_interval_min", 15) * 60
        self._api_key = config.get("weather", {}).get("api_key", "")
        # Default location fallback when GPS is not available
        self._default_lat = config.get("weather", {}).get("default_lat", 50.06)
        self._default_lon = config.get("weather", {}).get("default_lon", 19.94)
        self._refetch_km = _refetch_distance(
            config.get("weather", {}).get("refetch_distance_km"))

    def start(self):
        """Start weather polling in background thread."""
        if self._running:
            return
        self._running = True

        # Subscribe to GPS, LTE, and search location events
        self._bus.subscribe("gps.position", self._on_gps_position)
        self._bus.subscribe("lte.connected", self._on_lte_status)
        self._bus.subscribe("net.phone_tether", self._on_phone_tether)
        self._bus.subscribe("weather.search_location", self._on_search_location)
        # The phone's internet may already be up (no edge to wait for).
        last = self._bus.get_last("net.phone_tether")
        if last is not None and isinstance(last[0], dict):
            self._tether_connected = last[0].get("state") == "connected"

        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="weather-poller")
        self._thread.start()
        log.info("WeatherManager started (api_key=%s)",
                 "set" if self._api_key else "not set")

    def stop(self):
        """Stop weather polling."""
        self._running = False
        self._wake.set()
        self._bus.unsubscribe("gps.position", self._on_gps_position)
        self._bus.unsubscribe("lte.connected", self._on_lte_status)
        self._bus.unsubscribe("net.phone_tether", self._on_phone_tether)
        self._bus.unsubscribe("weather.search_location", self._on_search_location)
        if self._thread:
            self._thread.join(timeout=3)
        log.info("WeatherManager stopped")

    def _on_gps_position(self, topic, value, timestamp):
        """Handle GPS position updates — plausible fixes only (no 0,0).

        Runs on the event-bus dispatcher at ~1-2 Hz: stores the position and
        at most schedules a fetch (no network here). See the module
        docstring ("Location — what wins") for when a fix forces one.
        """
        coords = _plausible_fix(value)
        if coords is None:
            return
        # Location first, then the force: the poller takes its schedule
        # snapshot before its location snapshot (_poll_once), so a force it
        # has already seen always comes with these coordinates.
        with self._loc_lock:
            self._lat, self._lon = coords
            self._has_gps = True
            self._loc_source = LOC_GPS
        if self._fetch_source == LOC_DEFAULT and self._claim_gps_upgrade():
            self.force_fetch("first GPS fix", ignore_min_age=True)
            return
        self._maybe_refetch_for_distance(coords)

    def _location(self) -> tuple[bool, str, tuple[float, float]]:
        """``(has_gps, source, (lat, lon))`` read together (see _loc_lock)."""
        with self._loc_lock:
            return self._has_gps, self._loc_source, (self._lat, self._lon)

    def _claim_gps_upgrade(self) -> bool:
        """True exactly once per process: the first-GPS-fix force is ours."""
        with self._sched_lock:
            if self._gps_upgrade_done:
                return False
            self._gps_upgrade_done = True
            return True

    def _maybe_refetch_for_distance(self, coords: tuple[float, float]) -> None:
        """Force one fetch when the car left the last GPS fetch's area.

        Only after a GPS-based fetch (a searched city is not "where the car
        was"), only once per fetched location, and force_fetch()'s minimum
        age still applies — a GPS glitch cannot cause a request storm.
        """
        if self._refetch_km <= 0 or self._fetch_source != LOC_GPS \
                or self._distance_force_pending:
            return
        fetched = self._fetched_coords
        if fetched is None:
            return
        moved = _distance_km(fetched, coords)
        if moved <= self._refetch_km:
            return
        # Claimed before forcing (a good fetch clears it under the same lock),
        # given back if force_fetch() skips it (data younger than 60 s).
        with self._sched_lock:
            if self._distance_force_pending:
                return
            self._distance_force_pending = True
        if not self.force_fetch(f"moved {moved:.0f} km"):
            with self._sched_lock:
                self._distance_force_pending = False

    def _on_lte_status(self, topic, value, timestamp):
        """Handle LTE connectivity updates."""
        self._lte_connected = bool(value)

    def _on_phone_tether(self, topic, value, timestamp):
        """Phone internet (BT PAN) state; going ``connected`` forces a fetch.

        Runs on the event-bus dispatcher: only flags and wakes the poller.
        """
        connected = isinstance(value, dict) and value.get("state") == "connected"
        was = self._tether_connected
        self._tether_connected = connected
        if connected and not was:
            self.force_fetch("phone internet connected")

    def force_fetch(self, reason: str = "", ignore_min_age: bool = False) -> bool:
        """Fetch on the poller's next pass, skipping any backoff.

        Ignored when good data is younger than :data:`FORCE_MIN_AGE_S`,
        unless ``ignore_min_age`` — for the first GPS fix: the data that
        just arrived is for the DEFAULT location, its age says nothing
        (callers make sure that happens once, see _claim_gps_upgrade).
        Returns True if a fetch was scheduled.
        """
        now = self._clock()
        if not ignore_min_age and self._last_success is not None \
                and now - self._last_success < FORCE_MIN_AGE_S:
            return False
        with self._sched_lock:
            self._force_gen += 1
            if ignore_min_age:
                self._urgent_gen += 1
            self._next_fetch = 0.0
            self._retry_delay = RETRY_MIN_S
        self._wake.set()
        log.info("Weather: fetch forced (%s)", reason or "request")
        return True

    def _on_search_location(self, topic, value, timestamp):
        """Handle user-selected city from weather search."""
        if isinstance(value, dict):
            coords = valid_coords(value.get("lat"), value.get("lon"))
            if coords is None:
                log.warning("Weather search location rejected (not a coordinate)")
                self._bus.publish("weather.search_done", time.time())
                return
            with self._loc_lock:
                self._lat, self._lon = coords
                self._has_gps = True
                self._loc_source = LOC_SEARCH
            # The immediate fetch uses exactly these coordinates: a GPS fix
            # arriving meanwhile (1-2 Hz) overwrites _lat/_lon, and the
            # searched city must win for its own fetch (module docstring).
            self._search_coords = coords
            log.info("Weather location set via search: %.2f, %.2f (%r)",
                     coords[0], coords[1], str(value.get("city", ""))[:80])
            # Directly trigger fetch in background thread instead of relying on poll loop
            threading.Thread(target=self._immediate_fetch, daemon=True,
                             name="weather-search-fetch").start()

    def _immediate_fetch(self):
        """Fetch weather immediately (called from search handler)."""
        if not self._api_key:
            log.warning("Cannot fetch weather: no API key")
            # Still signal "done" so the frontend can clear its spinner
            # instead of waiting forever when there's no API key.
            self._bus.publish("weather.search_done", time.time())
            return
        coords = self._search_coords
        try:
            data = self._fetch_weather(coords)
            if data:
                self._publish_data(data, coords)
                self._save_cache(data)
                self._fetch_succeeded(self._clock(), LOC_SEARCH, coords)
                log.info("Weather search fetch SUCCESS: %s, %.1f°C",
                         data.get("city", "?"),
                         data.get("current", {}).get("temp", 0))
            else:
                log.warning("Weather search fetch returned None")
        except Exception as e:
            log.error("Weather search fetch FAILED: %s", e, exc_info=True)
        finally:
            # Always notify the frontend that the search fetch cycle ended
            # (success or failure) so it can drop the loading spinner.
            self._bus.publish("weather.search_done", time.time())

    def _run(self):
        """Main weather polling loop."""
        # Always publish demo data on startup so UI is never empty
        self._publish_data(DEMO_WEATHER)
        log.info("Weather: published demo data as initial fallback")

        # Load cached data on startup (overrides demo)
        cached = self._load_cache()
        if cached:
            self._publish_data(cached)
            log.info("Weather loaded from cache: %s", cached.get("city", "?"))

        if not self._api_key:
            log.warning("No weather API key — staying on demo/cached data")
        else:
            # Never log the key itself (not even a prefix) — logs/bcm.log
            # and the journal are not secret stores.
            log.info("Weather API key set (%d chars), will fetch real data",
                     len(self._api_key))

        while self._running:
            # Clear before the pass: a wake-up during it is not lost.
            self._wake.clear()
            try:
                self._poll_once()
            except Exception as e:
                log.error("Weather poll FAILED: %s", e, exc_info=True)
            # Conditions are re-checked every LOOP_S; a search or the phone's
            # internet coming up wakes the loop at once.
            self._wake.wait(LOOP_S)

    def _poll_once(self) -> bool:
        """One poller pass. Returns True if a fetch was attempted.

        Fetches when there is a key, a location and an uplink, and the
        schedule (poll interval after success, backoff after failure) says
        it is due.
        """
        now = self._clock()

        # Schedule snapshot BEFORE the location one (see _on_gps_position):
        # a force counted here was issued after its fix was stored.
        with self._sched_lock:
            force_gen = self._force_gen
            urgent_gen = self._urgent_gen
        # One consistent snapshot of what this fetch is for. The default
        # location is NOT written into _lat/_lon: the bus thread may store a
        # fix at the same moment, and the poller must not overwrite it.
        has_gps, source, coords = self._location()
        has_location = has_gps
        if not has_gps and self._default_lat and self._default_lon:
            source, coords = LOC_DEFAULT, (self._default_lat, self._default_lon)
            has_location = True
        online = self._lte_connected or self._tether_connected or self._platform == "x86"

        # Log state once for debugging
        if not self._state_logged:
            self._state_logged = True
            log.info("Weather poll state: api_key=%s, has_location=%s (%.2f,%.2f), "
                     "lte=%s, phone_tether=%s, platform=%s, poll_interval=%ds",
                     bool(self._api_key), has_location, coords[0], coords[1],
                     self._lte_connected, self._tether_connected, self._platform,
                     self._poll_interval)

        if not (self._api_key and has_location and online):
            return False
        if now < self._next_fetch:
            return False

        log.info("Weather: attempting fetch for %.2f,%.2f (%s)", coords[0], coords[1], source)
        try:
            data = self._fetch_weather(coords)
        except Exception as e:
            log.error("Weather fetch FAILED: %s", e, exc_info=True)
            data = None
        if data:
            self._publish_data(data, coords)
            self._save_cache(data)
            self._fetch_succeeded(now, source, coords, urgent_gen=urgent_gen)
            log.info("Weather fetch SUCCESS: %s, %.1f°C",
                     data.get("city", "?"),
                     data.get("current", {}).get("temp", 0))
            # The first fix may have arrived while this BOOT request was in
            # flight: the GPS handler then saw no finished default fetch yet
            # (_fetch_source None) and did not force — do it here (one-shot).
            # A fix during a LATER default fetch forces from the handler;
            # _fetch_succeeded keeps that force (urgent_gen).
            if source == LOC_DEFAULT and self._loc_source == LOC_GPS \
                    and self._claim_gps_upgrade():
                self.force_fetch("first GPS fix (arrived during the fetch)",
                                 ignore_min_age=True)
        else:
            with self._sched_lock:
                if self._force_gen != force_gen:
                    # Forced while this (probably still offline) fetch ran:
                    # keep force_fetch()'s "now" — the wake event is set, the
                    # next pass fetches at once — and do not grow the backoff.
                    log.info("Weather fetch returned no data — retrying at once (forced)")
                    return True
                delay = self._retry_delay
                self._next_fetch = now + delay
                self._retry_delay = min(delay * 2, max(self._poll_interval, RETRY_MIN_S))
            log.warning("Weather fetch returned no data — next attempt in %ds", delay)
        return True

    def _fetch_succeeded(self, now: float, source: Optional[str] = None,
                         coords: Optional[tuple[float, float]] = None,
                         urgent_gen: Optional[int] = None) -> None:
        """Good data: next regular poll after the interval, backoff reset.

        Also records what the data is for (``source``/``coords``) — under
        the lock, together with the schedule, so a force from the GPS
        handler that saw the new ``_fetch_source`` cannot be overwritten
        by this method's ``_next_fetch``.

        ``urgent_gen``: _urgent_gen when the (poller's) fetch started. If the
        first-GPS-fix force came in meanwhile and this data is not for the
        GPS, the force stays (_next_fetch 0): e.g. the phone's PAN comes up,
        forcing a default-location fetch, and the GPS NMEA arriving over the
        same PAN lands during it. The search fetch passes None — the searched
        city stays until the next regular poll (module docstring).
        """
        with self._sched_lock:
            self._last_fetch = time.time()
            self._last_success = now
            self._retry_delay = RETRY_MIN_S
            if urgent_gen is not None and self._urgent_gen != urgent_gen \
                    and source != LOC_GPS:
                self._next_fetch = 0.0
                log.info("Weather: the first GPS fix arrived during this fetch — "
                         "fetching again for the GPS position")
            else:
                self._next_fetch = now + self._poll_interval
            if source is not None:
                self._fetch_source = source
                self._fetched_coords = coords
            self._distance_force_pending = False

    def _fetch_weather(self, coords: Optional[tuple[float, float]] = None) -> dict | None:
        """Fetch current weather + forecast from OpenWeatherMap API.

        ``coords`` default to the current location (``_lat``/``_lon``).
        """
        lat, lon = coords if coords is not None else (self._lat, self._lon)
        try:
            import urllib.request
            import urllib.error

            # Current weather
            # urlencode: the key comes from the environment and the
            # coordinates from GPS/search — none of them may add parameters.
            query = urlencode({"lat": lat, "lon": lon,
                               "appid": self._api_key, "units": "metric"})
            url = f"https://api.openweathermap.org/data/2.5/weather?{query}"
            req = urllib.request.Request(url, headers={"User-Agent": "BCM-v7/1.0"})
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    current_raw = json.loads(resp.read())
            except urllib.error.HTTPError as e:
                log.error("Weather API error: HTTP %d — %s (key may not be activated yet)",
                          e.code, e.reason)
                return None

            # 5-day forecast
            url_fc = f"https://api.openweathermap.org/data/2.5/forecast?{query}&cnt=24"
            req_fc = urllib.request.Request(url_fc, headers={"User-Agent": "BCM-v7/1.0"})
            try:
                with urllib.request.urlopen(req_fc, timeout=10) as resp:
                    forecast_raw = json.loads(resp.read())
            except urllib.error.HTTPError as e:
                log.warning("Weather forecast API error: HTTP %d — %s", e.code, e.reason)
                forecast_raw = {"list": []}

            # Parse current
            weather = current_raw.get("weather", [{}])[0]
            main = current_raw.get("main", {})
            wind = current_raw.get("wind", {})
            city_name = current_raw.get("name", "")
            country = current_raw.get("sys", {}).get("country", "")

            data = {
                "current": {
                    "condition": weather.get("description", "").title(),
                    "icon": weather.get("icon", "01d"),
                    "temp": round(main.get("temp", 0), 1),
                    "feels_like": round(main.get("feels_like", 0), 1),
                    "humidity": main.get("humidity", 0),
                    "wind_speed": round(wind.get("speed", 0) * 3.6, 1),  # m/s → km/h
                    "wind_deg": wind.get("deg", 0),
                    "pressure": main.get("pressure", 0),
                },
                "city": f"{city_name}, {country}" if country else city_name,
                "forecast": self._parse_forecast(forecast_raw),
            }
            log.info("Weather fetched: %s, %.1f°C, %s",
                     data["city"], data["current"]["temp"],
                     data["current"]["condition"])
            return data

        except Exception as e:
            log.warning("Weather API error: %s", e)
            return None

    @staticmethod
    def _parse_forecast(raw: dict) -> list:
        """Parse OpenWeatherMap 5-day forecast into daily summaries."""
        days = {}
        for item in raw.get("list", []):
            dt_txt = item.get("dt_txt", "")
            date = dt_txt.split(" ")[0] if dt_txt else ""
            if not date:
                continue

            main = item.get("main", {})
            weather = item.get("weather", [{}])[0]
            temp = main.get("temp", 0)

            if date not in days:
                days[date] = {
                    "high": temp, "low": temp,
                    "condition": weather.get("description", "").title(),
                    "icon": weather.get("icon", "01d"),
                }
            else:
                days[date]["high"] = max(days[date]["high"], temp)
                days[date]["low"] = min(days[date]["low"], temp)

        # Convert to list, max 3 days
        import datetime
        result = []
        for i, (date, info) in enumerate(sorted(days.items())[:3]):
            try:
                dt = datetime.datetime.strptime(date, "%Y-%m-%d")
                day_name = "Today" if i == 0 else dt.strftime("%a")
            except ValueError:
                day_name = date
            result.append({
                "day": day_name,
                "high": round(info["high"]),
                "low": round(info["low"]),
                "condition": info["condition"],
                "icon": info["icon"],
            })
        return result

    def _publish_data(self, data: dict, coords: Optional[tuple[float, float]] = None):
        """Publish weather data to event bus.

        ``coords``: the location the data is for (default: the current one).
        """
        lat, lon = coords if coords is not None else (self._lat, self._lon)
        self._bus.publish("weather.current", data.get("current", {}))
        self._bus.publish("weather.forecast", data.get("forecast", []))
        self._bus.publish("weather.city", data.get("city", ""))
        # Publish weather-specific coordinates so map can center on weather city
        self._bus.publish("weather.lat", lat)
        self._bus.publish("weather.lon", lon)

    @staticmethod
    def _load_cache() -> dict | None:
        """Load cached weather data from disk."""
        try:
            if CACHE_FILE.exists():
                with open(CACHE_FILE) as f:
                    data = json.load(f)
                # Check age (max 1 hour)
                age = time.time() - data.get("_ts", 0)
                if age < 3600:
                    return data
        except Exception:
            pass
        return None

    @staticmethod
    def _save_cache(data: dict):
        """Save weather data to disk cache.

        Atomic (temp file + rename): a power cut mid-write used to leave a
        truncated JSON behind. 0600 — the payload includes the location.
        """
        try:
            data["_ts"] = time.time()
            atomic_write_json(CACHE_FILE, data, mode=0o600)
        except Exception as e:
            log.warning("Weather cache save failed: %s", e)


def start_weather(config, event_bus, hal, **kwargs):
    """Module entry point — called by main.py module registry."""
    platform = config.get("system", {}).get("platform", "x86")
    weather = WeatherManager(event_bus, config, platform)
    weather.start()
    return weather
