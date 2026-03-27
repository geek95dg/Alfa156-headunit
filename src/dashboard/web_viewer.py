"""Flask web server for HTML5/Tailwind dashboard frontend.

Serves the SPA frontend and provides:
- REST API endpoints for config, data, and i18n
- WebSocket for real-time event bus streaming
- WebSocket for browser keyboard input

Replaces the old Pygame frame-streaming viewer.
"""

import json
import os
import time
import threading
from typing import Optional, Any

from src.core.logger import get_logger

log = get_logger("web_viewer")

# Optional imports — Flask/gevent not required on OPi if using Pygame only
try:
    from flask import Flask, send_from_directory, jsonify, request
    from flask_sock import Sock
    HAS_FLASK = True
except ImportError:
    HAS_FLASK = False
    log.debug("Flask not available — web viewer disabled")


# Key name mapping: browser KeyboardEvent.key -> action_dispatch key names
_BROWSER_KEY_MAP = {
    "ArrowUp": "up",
    "ArrowDown": "down",
    "ArrowLeft": "left",
    "ArrowRight": "right",
    "Enter": "enter",
    "Home": "home",
    "Backspace": "backspace",
    "Escape": "escape",
    " ": "space",
}


class WebViewer:
    """HTML5/Tailwind dashboard served via Flask + WebSocket.

    Provides real-time event bus data to the browser via WebSocket
    and accepts keyboard input from the browser.
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 5002,
                 event_bus=None, config=None) -> None:
        self.host = host
        self.port = port
        self._event_bus = event_bus
        self._config = config
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._ws_clients: list = []
        self._ws_lock = threading.Lock()
        self._broadcast_thread: Optional[threading.Thread] = None

        # Path to the web frontend files
        self._web_dir = os.path.join(os.path.dirname(__file__), "web")

    def start(self) -> None:
        """Start the Flask web server in a background thread."""
        if not HAS_FLASK:
            log.warning("Flask not installed — web viewer disabled.")
            return

        self._running = True
        self._thread = threading.Thread(target=self._run_server, daemon=True)
        self._thread.start()

        # Start broadcast thread for pushing event bus data to WebSocket clients
        self._broadcast_thread = threading.Thread(
            target=self._broadcast_loop, daemon=True
        )
        self._broadcast_thread.start()

        log.info("Web viewer started at http://%s:%d", self.host, self.port)

    def stop(self) -> None:
        self._running = False

    def _get_dashboard_data(self) -> dict:
        """Collect all current event bus values into a JSON-serializable dict."""
        bus = self._event_bus
        if bus is None:
            return {}

        def _val(topic: str, default: Any = None) -> Any:
            result = bus.get_last(topic)
            return result[0] if result is not None else default

        return {
            # Engine
            "rpm": _val("obd.rpm", 0),
            "speed": _val("obd.speed", 0),
            "coolant_temp": _val("obd.coolant_temp", 0),
            "fuel_level": _val("obd.fuel_level", 50),
            "fuel_rate": _val("obd.fuel_rate", 0),
            "battery_voltage": _val("obd.battery_voltage", 12.6),
            "boost": _val("obd.boost", 0),
            "oil_pressure": _val("obd.oil_pressure", 0),
            # Trip
            "trip_distance": _val("trip.distance", 0),
            "trip_time": _val("trip.time_str", "00:00:00"),
            "trip_fuel_used": _val("trip.fuel_used", 0),
            "avg_speed": _val("trip.avg_speed", 0),
            "avg_consumption": _val("trip.avg_consumption", 0),
            "instant_consumption": _val("trip.instant_consumption", 0),
            "estimated_range": _val("trip.estimated_range", 0),
            # Service
            "service_km": _val("service.km_remaining", 4500),
            "oil_level_pct": _val("service.oil_level", -1),
            "tpms_pressures": _val("service.tpms_pressures", [0, 0, 0, 0]),
            # State
            "gear": _val("vehicle.gear", "N"),
            "reverse": _val("vehicle.reverse", False),
            "defrost_active": _val("vehicle.defrost", False),
            # External
            "ext_temp": _val("env.temperature", None),
            # GPS
            "gps_lat": _val("gps.lat", 0),
            "gps_lon": _val("gps.lon", 0),
            "gps_speed": _val("gps.speed", 0),
            "gps_heading": _val("gps.heading", 0),
            "gps_fix": _val("gps.fix", False),
            "gps_satellites": _val("gps.satellites", 0),
            # Weather
            "weather_condition": _val("weather.condition", ""),
            "weather_temp": _val("weather.temp", None),
            "weather_feels_like": _val("weather.feels_like", None),
            "weather_humidity": _val("weather.humidity", 0),
            "weather_wind_speed": _val("weather.wind_speed", 0),
            "weather_city": _val("weather.city", ""),
            "weather_forecast": _val("weather.forecast", []),
            # BT Media
            "bt_media_title": _val("bt.media_title", ""),
            "bt_media_artist": _val("bt.media_artist", ""),
            "bt_media_album": _val("bt.media_album", ""),
            "bt_media_playing": _val("bt.media_playing", False),
            "bt_media_position": _val("bt.media_position", 0),
            "bt_media_duration": _val("bt.media_duration", 0),
            # Connectivity
            "bt_connected": _val("bt.connected", False),
            "lte_connected": _val("lte.connected", False),
            "lte_signal": _val("lte.signal_strength", 0),
            # Notifications
            "notifications": _val("system.notifications", []),
            # Parking
            "parking_distances": _val("parking.distances", []),
            "parking_active": _val("parking.active", False),
        }

    def _handle_browser_key(self, key: str) -> None:
        """Map browser key to event bus input."""
        if self._event_bus is None:
            return
        mapped = _BROWSER_KEY_MAP.get(key, key.lower())
        self._event_bus.publish("input.raw_keyname", mapped)
        log.debug("Browser key: %s -> %s", key, mapped)

    def _broadcast_loop(self) -> None:
        """Periodically broadcast event bus data to all WebSocket clients."""
        while self._running:
            try:
                data = self._get_dashboard_data()
                payload = json.dumps(data, default=str)

                with self._ws_lock:
                    dead = []
                    for ws in self._ws_clients:
                        try:
                            ws.send(payload)
                        except Exception:
                            dead.append(ws)
                    for ws in dead:
                        self._ws_clients.remove(ws)
            except Exception:
                log.exception("Broadcast error")

            time.sleep(0.066)  # ~15 FPS

    def _run_server(self) -> None:
        app = Flask(__name__, static_folder=self._web_dir)
        sock = Sock(app)
        viewer = self

        # --- Static file serving ---

        @app.route("/")
        def index():
            return send_from_directory(viewer._web_dir, "index.html")

        @app.route("/css/<path:filename>")
        def css(filename):
            return send_from_directory(
                os.path.join(viewer._web_dir, "css"), filename
            )

        @app.route("/js/<path:filename>")
        def js(filename):
            return send_from_directory(
                os.path.join(viewer._web_dir, "js"), filename
            )

        @app.route("/assets/<path:filename>")
        def assets(filename):
            return send_from_directory(
                os.path.join(viewer._web_dir, "assets"), filename
            )

        # --- REST API ---

        @app.route("/api/data")
        def api_data():
            return jsonify(viewer._get_dashboard_data())

        @app.route("/api/config", methods=["GET"])
        def api_config_get():
            cfg = viewer._config
            if cfg is None:
                return jsonify({})
            return jsonify({
                "theme": cfg.get("display.dashboard.theme", "heritage"),
                "language": cfg.get("language", "pl"),
                "speed_unit": cfg.get("units.speed", "km/h"),
                "temp_unit": cfg.get("units.temperature", "C"),
                "brightness": cfg.get("display.dashboard.brightness", 70),
            })

        @app.route("/api/config", methods=["POST"])
        def api_config_set():
            cfg = viewer._config
            if cfg is None:
                return jsonify({"error": "no config"}), 500

            data = request.get_json(silent=True) or {}
            for key, config_key in [
                ("theme", "display.dashboard.theme"),
                ("language", "language"),
                ("speed_unit", "units.speed"),
                ("temp_unit", "units.temperature"),
                ("brightness", "display.dashboard.brightness"),
            ]:
                if key in data:
                    cfg.set(config_key, data[key])

            # Notify event bus of config change
            if viewer._event_bus:
                viewer._event_bus.publish("config.changed", data)

            return jsonify({"ok": True})

        @app.route("/api/i18n/<lang>")
        def api_i18n(lang):
            from src.dashboard.i18n import STRINGS
            strings = STRINGS.get(lang, STRINGS.get("en", {}))
            return jsonify(strings)

        # --- WebSocket: real-time data stream ---

        @sock.route("/ws")
        def ws_data_handler(ws):
            with viewer._ws_lock:
                viewer._ws_clients.append(ws)
            log.info("WebSocket client connected (data)")
            try:
                # Send initial full state snapshot
                try:
                    snapshot = json.dumps(viewer._get_dashboard_data(), default=str)
                    ws.send(snapshot)
                except Exception:
                    pass

                while viewer._running:
                    try:
                        # Keep connection alive — receive pings/pongs
                        msg = ws.receive(timeout=5)
                    except TimeoutError:
                        continue
                    except Exception:
                        break
                    if msg is None:
                        continue
            except Exception:
                pass
            finally:
                with viewer._ws_lock:
                    try:
                        viewer._ws_clients.remove(ws)
                    except ValueError:
                        pass
                log.info("WebSocket client disconnected (data)")

        # --- WebSocket: browser input ---

        @sock.route("/ws/input")
        def ws_input_handler(ws):
            log.info("WebSocket client connected (input)")
            while viewer._running:
                try:
                    msg = ws.receive(timeout=1)
                    if msg is None:
                        continue
                    data = json.loads(msg)
                    if data.get("type") == "keydown" and "key" in data:
                        viewer._handle_browser_key(data["key"])
                except json.JSONDecodeError:
                    log.debug("Invalid JSON from browser input WS")
                except Exception:
                    break

        app.run(host=self.host, port=self.port, debug=False, use_reloader=False)
