"""Flask server for the 6.86" widescreen second display (port 5003).

Default view: a 1x4 row of stats (fuel, coolant temp, ext temp, int temp)
with a time/date header, a persistent media bar (now-playing + transport),
and notification popups (weather, traffic, icing, low fuel, service, TPMS).

During reverse the cameras + parking-sensor visualization move to the MAIN
display; this second screen switches to a full-screen media-control view
(now-playing + prev/play-pause/next).
"""

import json
import os
import time
import threading

from src.core.logger import get_logger

log = get_logger("small_display")

try:
    from flask import Flask, send_from_directory, jsonify, request, Response
    from flask_sock import Sock
    HAS_FLASK = True
except ImportError:
    HAS_FLASK = False


# A single 1x1 black JPEG encoded inline so the camera endpoint can always
# return *something* when the camera is missing, without importing Pillow.
_BLACK_1x1_JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n"
    b"\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d"
    b"\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\xff\xc0\x00\x0b"
    b"\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01\x05"
    b"\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03"
    b"\x04\x05\x06\x07\x08\t\n\x0b\xff\xc4\x00\xb5\x10\x00\x02\x01\x03\x03"
    b"\x02\x04\x03\x05\x05\x04\x04\x00\x00\x01}\x01\x02\x03\x00\x04\x11\x05"
    b"\x12!1A\x06\x13Qa\x07\"q\x142\x81\x91\xa1\x08#B\xb1\xc1\x15R\xd1\xf0$3"
    b"br\x82\t\n\x16\x17\x18\x19\x1a%&'()*456789:CDEFGHIJSTUVWXYZcdefghij"
    b"stuvwxyz\x83\x84\x85\x86\x87\x88\x89\x8a\x92\x93\x94\x95\x96\x97\x98"
    b"\x99\x9a\xa2\xa3\xa4\xa5\xa6\xa7\xa8\xa9\xaa\xb2\xb3\xb4\xb5\xb6\xb7"
    b"\xb8\xb9\xba\xc2\xc3\xc4\xc5\xc6\xc7\xc8\xc9\xca\xd2\xd3\xd4\xd5\xd6"
    b"\xd7\xd8\xd9\xda\xe1\xe2\xe3\xe4\xe5\xe6\xe7\xe8\xe9\xea\xf1\xf2\xf3"
    b"\xf4\xf5\xf6\xf7\xf8\xf9\xfa\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xfb"
    b"\xd3\xff\xd9"
)


def _placeholder_jpeg(_label: str = "") -> bytes:
    """Return a minimal JPEG payload used when no real camera is available."""
    return _BLACK_1x1_JPEG


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
            # BT now-playing for the persistent media bar / reverse media view.
            "bt_media_title": v("bt.media_title", ""),
            "bt_media_artist": v("bt.media_artist", ""),
            "bt_media_playing": bool(v("bt.media_playing", False)),
            "bt_connected": bool(v("bt.connected", False)),
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

        @app.route("/assets/<path:f>")
        def assets(f):
            main_assets = os.path.join(os.path.dirname(__file__), "web", "assets")
            return send_from_directory(main_assets, f)

        @app.route("/splash/<path:f>")
        def splash_asset(f):
            # Boot/wake splash video, shared with the main display.
            splash_dir = os.path.join(
                os.path.dirname(__file__), "..", "..", "assets", "splash"
            )
            return send_from_directory(os.path.abspath(splash_dir), f)

        @app.route("/api/media/<action>", methods=["POST"])
        def api_media_control(action):
            # AVRCP transport control for the second display's media bar /
            # reverse media view. Mirrors the main viewer: republish on
            # bt.cmd.media and let BluetoothManager drive the phone.
            action = (action or "").lower()
            if action not in ("play", "pause", "playpause", "next", "previous"):
                return jsonify({"ok": False, "error": "bad action"}), 400
            if server._event_bus:
                server._event_bus.publish("bt.cmd.media", action)
            return jsonify({"ok": True, "action": action})

        @app.route("/api/data")
        def api_data():
            return jsonify(server._get_data())

        @app.route("/api/config")
        def api_config():
            cfg = server._config
            if not cfg:
                return jsonify({"theme": "heritage"})
            return jsonify({"theme": cfg.get("display.dashboard.theme", "heritage")})

        @app.route("/api/camera/stream")
        def camera_stream():
            """MJPEG stream from a role-addressed USB camera.

            Query param ``cam`` selects which feed to stream
            (front | rear | left | right). Defaults to rear for
            back-compat with the old reverse-only behaviour.
            Falls back to a static placeholder JPEG if opencv is
            missing or the device is unreachable.
            """
            try:
                import cv2
            except ImportError:
                return _placeholder_jpeg("NO OPENCV"), 200, {
                    "Content-Type": "image/jpeg"}

            role = (request.args.get("cam") or "rear").lower()
            if role not in ("front", "rear", "left", "right"):
                return "invalid cam role", 400

            device_path = None
            if server._config:
                device_path = server._config.get(
                    f"camera.{role}_device", None)

            def _open():
                if device_path:
                    c = cv2.VideoCapture(device_path)
                    if c.isOpened():
                        return c
                return cv2.VideoCapture(0)

            def gen():
                cap = _open()
                if not cap.isOpened():
                    # Return a single placeholder frame then stop
                    yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' +
                           _placeholder_jpeg(f"NO CAMERA: {role.upper()}") +
                           b'\r\n')
                    return
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                try:
                    while server._running:
                        ok, frame = cap.read()
                        if not ok:
                            break
                        _, buf = cv2.imencode('.jpg', frame,
                                              [cv2.IMWRITE_JPEG_QUALITY, 70])
                        yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n'
                               + buf.tobytes() + b'\r\n')
                finally:
                    cap.release()

            return Response(
                gen(),
                mimetype='multipart/x-mixed-replace; boundary=frame',
            )

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
