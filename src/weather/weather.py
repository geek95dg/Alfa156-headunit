"""Weather data module — fetches weather from OpenWeatherMap API.

Subscribes to gps.position for coordinates, requires lte.connected=True.
Polls every 15 minutes (configurable). Caches last response to disk.
On x86 without API key: returns hardcoded Milan demo weather data.

Publishes to event bus:
    weather.current  — dict with condition, temp, feels_like, humidity, wind
    weather.forecast — list of daily forecast dicts
    weather.city     — str
"""

import json
import logging
import os
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)

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

    def __init__(self, event_bus, config: dict, platform: str = "x86"):
        self._bus = event_bus
        self._config = config
        self._platform = platform
        self._running = False
        self._thread = None
        self._lat = 0.0
        self._lon = 0.0
        self._has_gps = False
        self._lte_connected = False
        self._last_fetch = 0
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
        self._bus.subscribe("weather.search_location", self._on_search_location)

        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="weather-poller")
        self._thread.start()
        log.info("WeatherManager started (api_key=%s)",
                 "set" if self._api_key else "not set")

    def stop(self):
        """Stop weather polling."""
        self._running = False
        self._bus.unsubscribe("gps.position", self._on_gps_position)
        self._bus.unsubscribe("lte.connected", self._on_lte_status)
        self._bus.unsubscribe("weather.search_location", self._on_search_location)
        if self._thread:
            self._thread.join(timeout=3)
        log.info("WeatherManager stopped")

    def _on_gps_position(self, topic, value, timestamp):
        """Handle GPS position updates."""
        if isinstance(value, dict):
            self._lat = value.get("lat", 0.0)
            self._lon = value.get("lon", 0.0)
            self._has_gps = True

    def _on_lte_status(self, topic, value, timestamp):
        """Handle LTE connectivity updates."""
        self._lte_connected = bool(value)

    def _on_search_location(self, topic, value, timestamp):
        """Handle user-selected city from weather search."""
        if isinstance(value, dict):
            self._lat = value.get("lat", self._lat)
            self._lon = value.get("lon", self._lon)
            self._has_gps = True
            self._last_fetch = 0  # Force immediate re-fetch
            log.info("Weather location set via search: %.2f, %.2f (%s)",
                     self._lat, self._lon, value.get("city", ""))

    def _run(self):
        """Main weather polling loop."""
        # Load cached data on startup
        cached = self._load_cache()
        if cached:
            self._publish_data(cached)
            log.info("Weather loaded from cache: %s", cached.get("city", "?"))

        # If no API key or x86, publish demo data immediately
        if not self._api_key:
            self._publish_data(DEMO_WEATHER)
            log.info("No weather API key — using demo data (Milan)")

        while self._running:
            now = time.time()

            # Use default location when GPS is not available
            has_location = self._has_gps
            if not has_location and self._default_lat and self._default_lon:
                self._lat = self._default_lat
                self._lon = self._default_lon
                has_location = True

            # Fetch if we have location, connectivity (or x86 dev), API key, and enough time passed
            if (self._api_key and has_location
                    and (self._lte_connected or self._platform == "x86")
                    and now - self._last_fetch >= self._poll_interval):
                try:
                    data = self._fetch_weather()
                    if data:
                        self._publish_data(data)
                        self._save_cache(data)
                        self._last_fetch = now
                except Exception as e:
                    log.warning("Weather fetch failed: %s", e)

            time.sleep(30)  # Check conditions every 30s

    def _fetch_weather(self) -> dict | None:
        """Fetch current weather + forecast from OpenWeatherMap API."""
        try:
            import urllib.request
            import urllib.error

            # Current weather
            url = (f"https://api.openweathermap.org/data/2.5/weather"
                   f"?lat={self._lat}&lon={self._lon}"
                   f"&appid={self._api_key}&units=metric")
            req = urllib.request.Request(url, headers={"User-Agent": "BCM-v7/1.0"})
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    current_raw = json.loads(resp.read())
            except urllib.error.HTTPError as e:
                log.error("Weather API error: HTTP %d — %s (key may not be activated yet)",
                          e.code, e.reason)
                return None

            # 5-day forecast
            url_fc = (f"https://api.openweathermap.org/data/2.5/forecast"
                      f"?lat={self._lat}&lon={self._lon}"
                      f"&appid={self._api_key}&units=metric&cnt=24")
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
        """Save weather data to disk cache."""
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            data["_ts"] = time.time()
            with open(CACHE_FILE, "w") as f:
                json.dump(data, f)
        except Exception as e:
            log.warning("Weather cache save failed: %s", e)


def start_weather(config, event_bus, hal, **kwargs):
    """Module entry point — called by main.py module registry."""
    platform = config.get("system", {}).get("platform", "x86")
    weather = WeatherManager(event_bus, config, platform)
    weather.start()
    return weather
