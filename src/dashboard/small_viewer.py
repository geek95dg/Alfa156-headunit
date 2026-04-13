"""Flask server for the 4.3" small display (port 5003).

Shows a static 2x2 grid of 4 values (fuel, coolant temp, ext temp, int temp)
with time/date header and notification popups (weather, traffic,
icing, low fuel, service, TPMS). Overlays the active camera feed
(rear/left/right) when reverse gear or a turn signal is engaged —
priority: reverse > left blinker > right blinker.
"""

import json
import os
import time
import threading
from typing import Optional, Any

from src.core.logger import get_logger

log = get_logger("small_display")

try:
    from flask import Flask, send_from_directory, jsonify
    from flask_sock import Sock
    HAS_FLASK = True
except ImportError:
    HAS_FLASK = False


class SmallDisplayServer:
    """Flask server for 4.3" stats display on port 5003."""

    def __init__(self, host="0.0.0.0", port=5003, event_bus=None, config=None):
        self.host = host
        self.port = port
        self._event_bus = event_bus
        self._config = config
        self._thread = None
        self._running = False
        self._ws_clients = []
        self._ws_lock = threading.Lock()
        self._web_dir = os.path.join(os.path.dirname(__file__), "small_display")

    def start(self):
        if not HAS_FLASK:
            log.warning("Flask not installed — small display disabled.")
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_server, daemon=True)
        self._thread.start()
        # Broadcast loop
        threading.Thread(target=self._broadcast_loop, daemon=True).start()
        log.info("Small display started at http://%s:%d", self.host, self.port)

    def stop(self):
        self._running = False

    def _get_data(self):
        bus = self._event_bus
        if not bus:
            return {}

        def v(topic, default=None):
            r = bus.get_last(topic)
            return r[0] if r is not None else default

        # Check for notification conditions
        notifications = []
        ext_temp = v("env.temperature")
        fuel = v("obd.fuel_level", 50)
        service_km = v("service.km_remaining", 9999)
        tpms = v("service.tpms_pressures", [0, 0, 0, 0])

        if ext_temp is not None and ext_temp < 3:
            notifications.append({"type": "icing", "icon": "ac_unit",
                                  "text": f"Oblodzenie! {ext_temp:.0f}\u00b0C",
                                  "severity": "danger", "duration": 5000})
        if fuel < 15:
            notifications.append({"type": "fuel", "icon": "local_gas_station",
                                  "text": f"Rezerwa paliwa: {fuel:.0f}%",
                                  "severity": "warning", "duration": 0})
        if service_km < 500:
            notifications.append({"type": "service", "icon": "build",
                                  "text": f"Serwis za {service_km} km",
                                  "severity": "warning", "duration": 10000})
        low_tire = [i for i, p in enumerate(tpms) if 0 < p < 2.0]
        if low_tire:
            pos = ["LL", "CL", "CR", "RR"][low_tire[0]]
            notifications.append({"type": "tpms", "icon": "tire_repair",
                                  "text": f"Ci\u015bnienie {pos}: {tpms[low_tire[0]]:.1f} BAR",
                                  "severity": "warning", "duration": 8000})

        # Weather/traffic alerts from event bus
        weather_alert = v("weather.alert")
        if weather_alert:
            notifications.append({"type": "weather", "icon": "thunderstorm",
                                  "text": str(weather_alert),
                                  "severity": "info", "duration": 10000})
        traffic_alert = v("traffic.alert")
        if traffic_alert:
            notifications.append({"type": "traffic", "icon": "traffic",
                                  "text": str(traffic_alert),
                                  "severity": "info", "duration": 8000})

        # Camera trigger logic — priority: reverse > left blinker > right blinker.
        # `camera.active_feed` is authoritative when CameraController is running;
        # otherwise derive the state here as a fallback for bench/simulator mode.
        reverse_on = bool(v("power.reverse_gear", False))
        left_blink = bool(v("vehicle.left_blinker", False))
        right_blink = bool(v("vehicle.right_blinker", False))
        camera_active = v("camera.active_feed", None)
        if camera_active is None:
            if reverse_on:
                camera_active = "rear"
            elif left_blink:
                camera_active = "left"
            elif right_blink:
                camera_active = "right"
            else:
                camera_active = None

        return {
            "fuel_level": fuel,
            "coolant_temp": v("obd.coolant_temp", 0),
            "ext_temp": ext_temp,
            "int_temp": v("env.int_temperature"),
            "reverse": reverse_on,
            "left_blinker": left_blink,
            "right_blinker": right_blink,
            "camera_active": camera_active,
            "parking_distances": v("parking.distances", []),
            "parking_active": v("parking.active", False),
            "notifications": notifications,
        }

    def _broadcast_loop(self):
        while self._running:
            try:
                data = self._get_data()
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
                pass
            time.sleep(0.2)  # 5 FPS — sufficient for stats display

    def _run_server(self):
        app = Flask(__name__, static_folder=self._web_dir)
        sock = Sock(app)
        server = self

        @app.route("/")
        def index():
            return send_from_directory(server._web_dir, "index.html")

        @app.route("/css/<path:f>")
        def css(f):
            return send_from_directory(os.path.join(server._web_dir, "css"), f)

        @app.route("/js/<path:f>")
        def js(f):
            return send_from_directory(os.path.join(server._web_dir, "js"), f)

        @app.route("/api/data")
        def api_data():
            return jsonify(server._get_data())

        @app.route("/api/config")
        def api_config():
            cfg = server._config
            if not cfg:
                return jsonify({"theme": "heritage"})
            return jsonify({"theme": cfg.get("display.dashboard.theme", "heritage")})

        @sock.route("/ws")
        def ws_handler(ws):
            with server._ws_lock:
                server._ws_clients.append(ws)
            try:
                snapshot = json.dumps(server._get_data(), default=str)
                ws.send(snapshot)
                while server._running:
                    try:
                        ws.receive(timeout=5)
                    except TimeoutError:
                        continue
                    except Exception:
                        break
            finally:
                with server._ws_lock:
                    try:
                        server._ws_clients.remove(ws)
                    except ValueError:
                        pass

        app.run(host=self.host, port=self.port, debug=False, use_reloader=False)
