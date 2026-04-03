"""Flask web server for HTML5/Tailwind dashboard frontend.

Serves the SPA frontend and provides:
- REST API endpoints for config, data, and i18n
- WebSocket for real-time event bus streaming
- WebSocket for browser keyboard input

Replaces the old Pygame frame-streaming viewer.
"""

import glob
import json
import os
import shutil
import subprocess
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
                 event_bus=None, config=None, bt_manager=None) -> None:
        self.host = host
        self.port = port
        self._event_bus = event_bus
        self._config = config
        self._bt_manager = bt_manager
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

        # Weather: weather.py publishes weather.current as a single dict
        _wc = _val("weather.current", {})
        if not isinstance(_wc, dict):
            _wc = {}

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
            "weather_condition": _wc.get("condition", ""),
            "weather_temp": _wc.get("temp", None),
            "weather_feels_like": _wc.get("feels_like", None),
            "weather_humidity": _wc.get("humidity", 0),
            "weather_wind_speed": _wc.get("wind_speed", 0),
            "weather_city": _val("weather.city", ""),
            "weather_forecast": _val("weather.forecast", []),
            "weather_lat": _val("weather.lat", None),
            "weather_lon": _val("weather.lon", None),
            # BT Media
            "bt_media_title": _val("bt.media_title", ""),
            "bt_media_artist": _val("bt.media_artist", ""),
            "bt_media_album": _val("bt.media_album", ""),
            "bt_media_playing": _val("bt.media_playing", False),
            "bt_media_position": _val("bt.media_position", 0),
            "bt_media_duration": _val("bt.media_duration", 0),
            # Connectivity
            "bt_connected": _val("bt.connected", False),
            "bt_call_state": _val("bt.call_state", "idle"),
            "bt_call_info": _val("bt.call_info", {}),
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
            usb_mounts = glob.glob("/media/usb*") + glob.glob("/mnt/usb*")
            if not usb_mounts:
                return jsonify({"error": "no USB drive"}), 400
            usb_root = usb_mounts[0]
            dest = os.path.normpath(os.path.join(usb_root, target_path.lstrip("/")))
            if not dest.startswith(usb_root):
                return jsonify({"error": "invalid target path"}), 400
            os.makedirs(dest, exist_ok=True)
            copied = 0
            for f in files:
                src = os.path.join("/media/dashcam", f)
                if os.path.exists(src):
                    shutil.copy2(src, os.path.join(dest, f))
                    copied += 1
            return jsonify({"ok": True, "count": copied, "target": dest})

        @app.route("/api/dvr/usb/status")
        def api_dvr_usb_status():
            usb_mounts = glob.glob("/media/usb*") + glob.glob("/mnt/usb*")
            if not usb_mounts:
                return jsonify({"available": False})
            usage = shutil.disk_usage(usb_mounts[0])
            return jsonify({
                "available": True,
                "free_gb": round(usage.free / (1024**3), 1),
                "total_gb": round(usage.total / (1024**3), 1),
            })

        @app.route("/api/dvr/usb/browse")
        def api_dvr_usb_browse():
            """List directories on USB drive for export target selection."""
            usb_mounts = glob.glob("/media/usb*") + glob.glob("/mnt/usb*")
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

        # --- Android Auto — direct Xvfb MJPEG stream (no port 5001) ---

        def _aa_mjpeg_generator():
            """Stream MJPEG frames from Xvfb (:99) using ffmpeg."""
            cfg = viewer._config
            w = cfg.get("display.multimedia.width", 1024) if cfg else 1024
            h = cfg.get("display.multimedia.height", 600) if cfg else 600
            try:
                proc = subprocess.Popen(
                    ["ffmpeg", "-f", "x11grab", "-framerate", "30",
                     "-video_size", f"{w}x{h}",
                     "-draw_mouse", "0",
                     "-i", ":99",
                     "-f", "mjpeg", "-q:v", "2",
                     "-an", "pipe:1"],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                )
            except Exception:
                return
            buf = b""
            SOI = b"\xff\xd8"
            EOI = b"\xff\xd9"
            try:
                while True:
                    chunk = proc.stdout.read(4096)
                    if not chunk:
                        break
                    buf += chunk
                    while True:
                        start = buf.find(SOI)
                        if start == -1:
                            buf = b""
                            break
                        end = buf.find(EOI, start + 2)
                        if end == -1:
                            buf = buf[start:]
                            break
                        frame = buf[start:end + 2]
                        buf = buf[end + 2:]
                        yield (b"--frame\r\n"
                               b"Content-Type: image/jpeg\r\n\r\n"
                               + frame + b"\r\n")
            finally:
                proc.terminate()
                proc.wait(timeout=3)

        @app.route("/aa/stream")
        def aa_stream():
            """Direct MJPEG stream from Xvfb (:99) — no port 5001 proxy."""
            return Response(_aa_mjpeg_generator(),
                            mimetype="multipart/x-mixed-replace; boundary=frame")

        @app.route("/aa/status")
        def aa_status():
            """Check if OpenAuto / Xvfb is running."""
            available = False
            if viewer._event_bus:
                st = viewer._event_bus.get_last("multimedia.openauto_status")
                if st and st[0] in ("running", "connected"):
                    available = True
            return jsonify({"available": available})

        @app.route("/aa/touch", methods=["POST"])
        def aa_touch():
            """Forward touch/click to Xvfb via xdotool."""
            data = request.get_json(silent=True) or {}
            rel_x = data.get("x", 0.5)
            rel_y = data.get("y", 0.5)
            cfg = viewer._config
            w = cfg.get("display.multimedia.width", 1024) if cfg else 1024
            h = cfg.get("display.multimedia.height", 600) if cfg else 600
            px = max(0, min(w, int(rel_x * w)))
            py = max(0, min(h, int(rel_y * h)))
            try:
                subprocess.run(
                    ["xdotool", "mousemove", "--screen", "0",
                     str(px), str(py), "click", "1"],
                    timeout=2, capture_output=True,
                    env={**os.environ, "DISPLAY": ":99"},
                )
                return jsonify({"ok": True, "x": px, "y": py})
            except Exception:
                return jsonify({"ok": False}), 500

        # --- Bluetooth management API (moved from aa_display.py) ---

        @app.route("/bt/status")
        def bt_status():
            bt = viewer._bt_manager
            if not bt:
                return jsonify({"error": "BT manager not available"}), 503
            ctrl = bt.get_controller_info()
            ctrl["connected"] = bt.connected
            ctrl["connected_device"] = bt.connected_device
            ctrl["scanning"] = bt.scanning
            ctrl["a2dp_active"] = bt.a2dp_active
            ctrl["hfp_active"] = bt.hfp_active
            return jsonify(ctrl)

        @app.route("/bt/devices")
        def bt_devices():
            bt = viewer._bt_manager
            if not bt:
                return jsonify({"paired": [], "discovered": []})
            paired = bt.get_paired_devices()
            for dev in paired:
                info = bt.get_device_info(dev["address"])
                dev["connected"] = info.get("connected", False)
            discovered = bt.discovered_devices
            return jsonify({"paired": paired, "discovered": discovered})

        @app.route("/bt/scan", methods=["POST"])
        def bt_scan():
            bt = viewer._bt_manager
            if not bt:
                return jsonify({"error": "BT not available"}), 503
            duration = 15
            if request.is_json:
                duration = request.json.get("duration", 15)
            ok = bt.start_scan(duration=duration)
            return jsonify({"started": ok, "scanning": bt.scanning})

        @app.route("/bt/scan/stop", methods=["POST"])
        def bt_scan_stop():
            bt = viewer._bt_manager
            if not bt:
                return jsonify({"error": "BT not available"}), 503
            bt.stop_scan()
            return jsonify({"scanning": False})

        @app.route("/bt/pair/<address>", methods=["POST"])
        def bt_pair(address):
            bt = viewer._bt_manager
            if not bt:
                return jsonify({"error": "BT not available"}), 503
            ok = bt.pair(address)
            return jsonify({"success": ok, "address": address})

        @app.route("/bt/connect/<address>", methods=["POST"])
        def bt_connect(address):
            bt = viewer._bt_manager
            if not bt:
                return jsonify({"error": "BT not available"}), 503
            ok = bt.connect(address)
            return jsonify({"success": ok, "address": address})

        @app.route("/bt/disconnect", methods=["POST"])
        def bt_disconnect():
            bt = viewer._bt_manager
            if not bt:
                return jsonify({"error": "BT not available"}), 503
            bt.disconnect()
            return jsonify({"success": True})

        @app.route("/bt/remove/<address>", methods=["POST"])
        def bt_remove(address):
            bt = viewer._bt_manager
            if not bt:
                return jsonify({"error": "BT not available"}), 503
            ok = bt.remove(address)
            return jsonify({"success": ok, "address": address})

        @app.route("/bt/discoverable", methods=["POST"])
        def bt_discoverable():
            bt = viewer._bt_manager
            if not bt:
                return jsonify({"error": "BT not available"}), 503
            timeout = 120
            if request.is_json:
                timeout = request.json.get("timeout", 120)
            ok = bt.enable_discoverable(timeout=timeout)
            return jsonify({"success": ok})

        @app.route("/bt/connected")
        def bt_connected():
            bt = viewer._bt_manager
            if not bt:
                return jsonify({"connected": []})
            connected = bt.get_connected_devices()
            return jsonify({"connected": connected})

        @app.route("/bt/pairing")
        def bt_pairing_status():
            try:
                from src.multimedia.bluetooth import get_pending_pairing
                req = get_pending_pairing()
                return jsonify({"pending": req is not None, "request": req})
            except Exception:
                return jsonify({"pending": False, "request": None})

        @app.route("/bt/pairing/confirm", methods=["POST"])
        def bt_pairing_confirm():
            try:
                from src.multimedia.bluetooth import confirm_pairing
                accept = True
                if request.is_json:
                    accept = request.json.get("accept", True)
                ok = confirm_pairing(accept)
                return jsonify({"success": ok})
            except Exception:
                return jsonify({"success": False})

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

        # --- Weather search API ---

        @app.route("/api/weather/search")
        def api_weather_search():
            """Geocode city name via OpenWeatherMap Geocoding API."""
            import urllib.request
            import urllib.parse
            query = request.args.get("q", "").strip()
            if not query or len(query) < 2:
                return jsonify({"results": []})
            api_key = ""
            if viewer._config:
                api_key = viewer._config.get("weather", {}).get("api_key", "")
            if not api_key:
                return jsonify({"results": [], "error": "no API key"}), 400
            url = (f"https://api.openweathermap.org/geo/1.0/direct"
                   f"?q={urllib.parse.quote(query)}&limit=5&appid={api_key}")
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "BCM/1.0"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    raw = json.loads(resp.read())
                results = [{"name": r.get("name", ""),
                            "country": r.get("country", ""),
                            "state": r.get("state", ""),
                            "lat": r.get("lat", 0),
                            "lon": r.get("lon", 0)} for r in raw]
                return jsonify({"results": results})
            except Exception as e:
                return jsonify({"results": [], "error": str(e)}), 500

        @app.route("/api/weather/location", methods=["POST"])
        def api_weather_set_location():
            """Set weather location (from search). Triggers re-fetch."""
            data = request.get_json(silent=True) or {}
            lat = data.get("lat")
            lon = data.get("lon")
            city = data.get("city", "")
            if lat is not None and lon is not None and viewer._event_bus:
                viewer._event_bus.publish("weather.search_location",
                                          {"lat": lat, "lon": lon, "city": city})
                return jsonify({"ok": True})
            return jsonify({"error": "missing lat/lon"}), 400

        # --- Client-side logging ---

        @app.route("/api/log", methods=["POST"])
        def api_client_log():
            """Receive log messages from frontend JS for server-side logging."""
            data = request.get_json(silent=True) or {}
            level = data.get("level", "info")
            msg = data.get("message", "")
            if level == "error":
                log.error("[FRONTEND] %s", msg)
            elif level == "warn":
                log.warning("[FRONTEND] %s", msg)
            else:
                log.info("[FRONTEND] %s", msg)
            return jsonify({"ok": True})

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
