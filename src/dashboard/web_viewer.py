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
    from flask import Flask, send_from_directory, jsonify, request, Response
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

        # --- DVR API ---

        @app.route("/api/dvr/list")
        def api_dvr_list():
            """List DVR recordings."""
            import glob
            rec_dir = "/media/dashcam"
            recordings = []
            for path in sorted(glob.glob(f"{rec_dir}/*.mp4"), reverse=True)[:50]:
                fname = os.path.basename(path)
                try:
                    size_mb = os.path.getsize(path) / (1024 * 1024)
                except OSError:
                    size_mb = 0
                cam = "front" if "front" in fname else "rear" if "rear" in fname else "front"
                recordings.append({
                    "filename": fname,
                    "camera": cam,
                    "size": f"{size_mb:.0f}MB",
                    "date": fname[:19].replace("_", " ") if len(fname) > 19 else fname,
                })
            return jsonify({"recordings": recordings})

        @app.route("/api/dvr/play/<filename>")
        def api_dvr_play(filename):
            rec_dir = "/media/dashcam"
            return send_from_directory(rec_dir, filename)

        @app.route("/api/dvr/delete/<filename>", methods=["DELETE"])
        def api_dvr_delete(filename):
            rec_dir = "/media/dashcam"
            path = os.path.join(rec_dir, filename)
            if os.path.exists(path):
                os.remove(path)
                return jsonify({"ok": True})
            return jsonify({"error": "not found"}), 404

        @app.route("/api/dvr/export", methods=["POST"])
        def api_dvr_export():
            """Export selected files to USB drive (with optional target folder)."""
            data = request.get_json(silent=True) or {}
            files = data.get("files", [])
            target_path = data.get("target_path", "/")
            # Find USB mount point
            import glob as g
            usb_mounts = g.glob("/media/usb*") + g.glob("/mnt/usb*")
            if not usb_mounts:
                return jsonify({"error": "no USB drive"}), 400
            usb_root = usb_mounts[0]
            dest = os.path.normpath(os.path.join(usb_root, target_path.lstrip("/")))
            if not dest.startswith(usb_root):
                return jsonify({"error": "invalid target path"}), 400
            os.makedirs(dest, exist_ok=True)
            import shutil
            copied = 0
            for f in files:
                src = os.path.join("/media/dashcam", f)
                if os.path.exists(src):
                    shutil.copy2(src, os.path.join(dest, f))
                    copied += 1
            return jsonify({"ok": True, "count": copied, "target": dest})

        @app.route("/api/dvr/usb/status")
        def api_dvr_usb_status():
            import glob as g
            usb_mounts = g.glob("/media/usb*") + g.glob("/mnt/usb*")
            if not usb_mounts:
                return jsonify({"available": False})
            import shutil
            usage = shutil.disk_usage(usb_mounts[0])
            return jsonify({
                "available": True,
                "free_gb": round(usage.free / (1024**3), 1),
                "total_gb": round(usage.total / (1024**3), 1),
            })

        @app.route("/api/dvr/usb/browse")
        def api_dvr_usb_browse():
            """List directories on USB drive for export target selection."""
            import glob as g
            usb_mounts = g.glob("/media/usb*") + g.glob("/mnt/usb*")
            if not usb_mounts:
                return jsonify({"error": "no USB drive"}), 400
            usb_root = usb_mounts[0]
            rel_path = request.args.get("path", "/")
            abs_path = os.path.normpath(os.path.join(usb_root, rel_path.lstrip("/")))
            if not abs_path.startswith(usb_root):
                return jsonify({"error": "invalid path"}), 400
            if not os.path.isdir(abs_path):
                return jsonify({"error": "not a directory"}), 400
            entries = []
            for name in sorted(os.listdir(abs_path)):
                full = os.path.join(abs_path, name)
                if os.path.isdir(full):
                    entries.append({"name": name, "type": "dir"})
            rel = os.path.relpath(abs_path, usb_root)
            return jsonify({"path": "/" if rel == "." else "/" + rel, "dirs": entries})

        # --- Android Auto proxy ---

        @app.route("/aa/stream")
        def aa_stream():
            """Proxy MJPEG stream from OpenAuto (port 5001) through BCM port 5002."""
            import urllib.request
            try:
                req = urllib.request.urlopen("http://localhost:5001/stream", timeout=3)
                return Response(
                    req,
                    mimetype=req.headers.get("Content-Type", "multipart/x-mixed-replace; boundary=frame"),
                )
            except Exception:
                return "", 503

        @app.route("/aa/status")
        def aa_status():
            """Check if OpenAuto is reachable."""
            import urllib.request
            try:
                urllib.request.urlopen("http://localhost:5001/", timeout=2)
                return jsonify({"available": True})
            except Exception:
                return jsonify({"available": False})

        # --- Phone API ---

        @app.route("/api/phone/contacts")
        def api_phone_contacts():
            """Get synced contacts from BT PBAP."""
            if viewer._event_bus:
                contacts = viewer._event_bus.get_last("bt.contacts")
                if contacts and contacts[0]:
                    return jsonify({"contacts": contacts[0]})
            return jsonify({"contacts": []})

        @app.route("/api/phone/history")
        def api_phone_history():
            """Get call history from BT PBAP."""
            if viewer._event_bus:
                history = viewer._event_bus.get_last("bt.call_history")
                if history and history[0]:
                    return jsonify({"history": history[0]})
            return jsonify({"history": []})

        @app.route("/api/phone/dial", methods=["POST"])
        def api_phone_dial():
            data = request.get_json(silent=True) or {}
            number = data.get("number", "")
            if number and viewer._event_bus:
                viewer._event_bus.publish("bt.cmd.dial", number)
            return jsonify({"ok": True, "number": number})

        @app.route("/api/phone/answer", methods=["POST"])
        def api_phone_answer():
            if viewer._event_bus:
                viewer._event_bus.publish("bt.cmd.answer", True)
            return jsonify({"ok": True})

        @app.route("/api/phone/hangup", methods=["POST"])
        def api_phone_hangup():
            if viewer._event_bus:
                viewer._event_bus.publish("bt.cmd.hangup", True)
            return jsonify({"ok": True})

        @app.route("/api/phone/status")
        def api_phone_status():
            state = "idle"
            info = {}
            if viewer._event_bus:
                s = viewer._event_bus.get_last("bt.call_state")
                if s: state = s[0] or "idle"
                i = viewer._event_bus.get_last("bt.call_info")
                if i: info = i[0] or {}
            return jsonify({"state": state, "info": info})

        # --- DTC API ---

        @app.route("/api/dtc/read")
        def api_dtc_read():
            """Read DTC error codes from ECU."""
            if viewer._event_bus:
                viewer._event_bus.publish("obd.dtc.read_request", True)
            codes = []
            if viewer._event_bus:
                result = viewer._event_bus.get_last("obd.dtc.codes")
                if result:
                    codes = result[0] or []
            return jsonify({"codes": codes})

        @app.route("/api/dtc/clear", methods=["POST"])
        def api_dtc_clear():
            """Clear DTC error codes from ECU."""
            if viewer._event_bus:
                viewer._event_bus.publish("obd.dtc.clear_request", True)
            return jsonify({"ok": True})

        @app.route("/api/i18n/<lang>")
        def api_i18n(lang):
            from src.dashboard.i18n import STRINGS
            strings = STRINGS.get(lang, STRINGS.get("en", {}))
            return jsonify(strings)

        # --- Camera MJPEG stream for reverse view ---

        @app.route("/api/camera/stream")
        def camera_stream():
            """MJPEG stream from USB camera (/dev/video0)."""
            try:
                import cv2
            except ImportError:
                return "opencv not available", 503

            from flask import Response

            def gen_frames():
                cap = cv2.VideoCapture(0)
                if not cap.isOpened():
                    return
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                try:
                    while viewer._running:
                        ok, frame = cap.read()
                        if not ok:
                            break
                        _, buf = cv2.imencode('.jpg', frame,
                                              [cv2.IMWRITE_JPEG_QUALITY, 70])
                        yield (b'--frame\r\n'
                               b'Content-Type: image/jpeg\r\n\r\n' +
                               buf.tobytes() + b'\r\n')
                finally:
                    cap.release()

            return Response(gen_frames(),
                            mimetype='multipart/x-mixed-replace; boundary=frame')

        @app.route("/api/camera/available")
        def camera_available():
            """Check if a USB camera is available."""
            try:
                import cv2
                cap = cv2.VideoCapture(0)
                available = cap.isOpened()
                cap.release()
                return jsonify({"available": available})
            except Exception:
                return jsonify({"available": False})

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
