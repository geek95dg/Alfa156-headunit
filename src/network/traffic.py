"""Live traffic data — TomTom/HERE Traffic API integration.

Fetches traffic flow/incidents near the current GPS position.
Publishes traffic alerts to event bus for map overlay and small display popups.
"""

import threading
import time
from src.core.logger import get_logger

log = get_logger("traffic")


class TrafficModule:
    """Live traffic data fetcher."""

    def __init__(self, config, event_bus):
        self.config = config
        self.bus = event_bus
        self._running = False
        self._thread = None
        self._api_key = config.get("traffic.api_key", "")
        self._provider = config.get("traffic.provider", "tomtom")  # "tomtom" or "here"
        self._poll_interval = config.get("traffic.poll_interval_min", 5) * 60

    def start(self):
        if not self._api_key:
            log.warning("Traffic API key not configured — traffic overlay disabled")
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        log.info("Traffic module started (provider: %s, poll: %dmin)",
                 self._provider, self._poll_interval // 60)

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            try:
                pos = self.bus.get_last("gps.position")
                if pos and pos[0]:
                    lat = pos[0].get("lat", 0)
                    lon = pos[0].get("lon", 0)
                    if lat and lon:
                        incidents = self._fetch_incidents(lat, lon)
                        if incidents:
                            self.bus.publish("traffic.incidents", incidents)
                            # Publish alert for small display popup
                            nearest = incidents[0]
                            self.bus.publish("traffic.alert",
                                             f"{nearest.get('type', 'Korek')}: {nearest.get('desc', '')}")
            except Exception:
                log.exception("Traffic fetch failed")
            time.sleep(self._poll_interval)

    def _fetch_incidents(self, lat, lon):
        """Fetch traffic incidents near position. Returns list of dicts."""
        try:
            import urllib.request
            import json

            if self._provider == "tomtom":
                url = (f"https://api.tomtom.com/traffic/services/5/incidentDetails"
                       f"?key={self._api_key}&bbox={lon-0.1},{lat-0.1},{lon+0.1},{lat+0.1}"
                       f"&fields={{incidents{{type,geometry{{type,coordinates}},properties{{description}}}}}}")
            else:
                # HERE placeholder
                url = f"https://traffic.ls.hereapi.com/traffic/6.2/incidents.json?apiKey={self._api_key}&bbox={lat+0.1},{lon-0.1};{lat-0.1},{lon+0.1}"

            req = urllib.request.Request(url, headers={"User-Agent": "BCM/8.5"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())

            # Parse response (simplified)
            incidents = []
            if self._provider == "tomtom" and "incidents" in data:
                for inc in data["incidents"][:5]:
                    props = inc.get("properties", {})
                    incidents.append({
                        "type": props.get("iconCategory", "traffic"),
                        "desc": props.get("description", ""),
                    })
            return incidents

        except Exception as e:
            log.debug("Traffic API error: %s", e)
            return []


def start_traffic(config, event_bus, hal=None, **kwargs):
    mod = TrafficModule(config, event_bus)
    mod.start()
    return mod
