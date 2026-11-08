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
        self._has_gps = False
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
        self._poll_interval = config.get("weather", {}).get("poll_interval_min", 15) * 60
        self._api_key = config.get("weather", {}).get("api_key", "")
        # Default location fallback when GPS is not available
        self._default_lat = config.get("weather", {}).get("default_lat", 50.06)
        self._default_lon = config.get("weather", {}).get("default_lon", 19.94)

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
        """Handle GPS position updates — plausible fixes only (no 0,0)."""
        coords = _plausible_fix(value)
        if coords is None:
            return
        self._lat, self._lon = coords
        self._has_gps = True

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

    def force_fetch(self, reason: str = "") -> bool:
        """Fetch on the poller's next pass, skipping any backoff.

        Ignored when good data is younger than :data:`FORCE_MIN_AGE_S`.
        Returns True if a fetch was scheduled.
        """
        now = self._clock()
        if self._last_success is not None and now - self._last_success < FORCE_MIN_AGE_S:
            return False
        with self._sched_lock:
            self._force_gen += 1
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
            self._lat, self._lon = coords
            self._has_gps = True
            log.info("Weather location set via search: %.2f, %.2f (%r)",
                     self._lat, self._lon, str(value.get("city", ""))[:80])
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
        try:
            data = self._fetch_weather()
            if data:
                self._publish_data(data)
                self._save_cache(data)
                self._fetch_succeeded(self._clock())
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

        # Use default location when GPS is not available
        has_location = self._has_gps
        if not has_location and self._default_lat and self._default_lon:
            self._lat = self._default_lat
            self._lon = self._default_lon
            has_location = True
        online = self._lte_connected or self._tether_connected or self._platform == "x86"

        # Log state once for debugging
        if not self._state_logged:
            self._state_logged = True
            log.info("Weather poll state: api_key=%s, has_location=%s (%.2f,%.2f), "
                     "lte=%s, phone_tether=%s, platform=%s, poll_interval=%ds",
                     bool(self._api_key), has_location, self._lat, self._lon,
                     self._lte_connected, self._tether_connected, self._platform,
                     self._poll_interval)

        if not (self._api_key and has_location and online):
            return False
        if now < self._next_fetch:
            return False

        log.info("Weather: attempting fetch for %.2f,%.2f", self._lat, self._lon)
        with self._sched_lock:
            force_gen = self._force_gen
        try:
            data = self._fetch_weather()
        except Exception as e:
            log.error("Weather fetch FAILED: %s", e, exc_info=True)
            data = None
        if data:
            self._publish_data(data)
            self._save_cache(data)
            self._fetch_succeeded(now)
            log.info("Weather fetch SUCCESS: %s, %.1f°C",
                     data.get("city", "?"),
                     data.get("current", {}).get("temp", 0))
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

    def _fetch_succeeded(self, now: float) -> None:
        """Good data: next regular poll after the interval, backoff reset."""
        self._last_fetch = time.time()
        self._last_success = now
        self._retry_delay = RETRY_MIN_S
        self._next_fetch = now + self._poll_interval

    def _fetch_weather(self) -> dict | None:
        """Fetch current weather + forecast from OpenWeatherMap API."""
        try:
            import urllib.request
            import urllib.error

            # Current weather
            # urlencode: the key comes from the environment and the
            # coordinates from GPS/search — none of them may add parameters.
            query = urlencode({"lat": self._lat, "lon": self._lon,
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

    def _publish_data(self, data: dict):
        """Publish weather data to event bus."""
        self._bus.publish("weather.current", data.get("current", {}))
        self._bus.publish("weather.forecast", data.get("forecast", []))
        self._bus.publish("weather.city", data.get("city", ""))
        # Publish weather-specific coordinates so map can center on weather city
        self._bus.publish("weather.lat", self._lat)
        self._bus.publish("weather.lon", self._lon)

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
