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
from pathlib import Path
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
                 event_bus=None, config=None, bt_manager=None,
                 trip_computer=None, route_planner=None,
                 wifi_ap=None) -> None:
        self.host = host
        self.port = port
        self._event_bus = event_bus
        self._config = config
        self._bt_manager = bt_manager
        self._wifi_ap = wifi_ap
        self._trip_computer = trip_computer
        self._route_planner = route_planner
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._ws_clients: list = []
        self._ws_lock = threading.Lock()
        self._broadcast_thread: Optional[threading.Thread] = None

        # Path to the web frontend files
        self._web_dir = os.path.join(os.path.dirname(__file__), "web")

        # Forward voice-AA trigger to xdotool tap on AA mic icon
        if event_bus:
            event_bus.subscribe("aa.voice_trigger", self._on_aa_voice_trigger)

    def attach_trip(self, trip_computer, route_planner=None) -> None:
        """Attach trip computer + planner after construction.

        Used by the dashboard renderer which owns the TripComputer
        instance — it wires it up before calling ``start()``.
        """
        self._trip_computer = trip_computer
        if route_planner is not None:
            self._route_planner = route_planner

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
            # "reverse" removed — reverse camera only on small display (port 5003)
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
            # Increments each time the WeatherManager finishes an immediate
            # fetch after a location change — used by A4 Weather to drop
            # the "Loading..." spinner reactively (no hardcoded setTimeout).
            "weather_search_done": _val("weather.search_done", 0),
            # Travel plan (A3 Trip — only populated when destination is set)
            "trip_plan": (self._trip_computer.get_plan_dict()
                          if self._trip_computer else None),
            "trip_planning": _val("trip.planning", False),
            # BT Media
            "bt_media_title": _val("bt.media_title", ""),
            "bt_media_artist": _val("bt.media_artist", ""),
            "bt_media_album": _val("bt.media_album", ""),
            "bt_media_playing": _val("bt.media_playing", False),
            "bt_media_position": _val("bt.media_position", 0),
            "bt_media_duration": _val("bt.media_duration", 0),
            # Connectivity
            "bt_connected": _val("bt.connected", False),
            "bt_available": self._bt_manager.available if self._bt_manager else False,
            "bt_call_state": _val("bt.call_state", "idle"),
            "bt_call_info": _val("bt.call_info", {}),
            "aa_status": _val("multimedia.openauto_status", "unavailable"),
            "aa_available": _val("multimedia.openauto_status", "unavailable") in (
                "running", "connected", "restarting"),
            "lte_connected": _val("lte.connected", False),
            "lte_signal": _val("lte.signal_strength", 0),
            # Audio
            "audio_volume": _val("audio.volume", 70),
            "audio_muted": _val("audio.mute_changed", False),
            "audio_eq_preset": _val("audio.eq_preset", "jazz"),
            "audio_eq_gains": _val("audio.eq_gains", [0] * 10),
            "audio_spectrum": _val("audio.spectrum", [0] * 16),
            "audio_bass": _val("audio.bass", 0),
            "audio_treble": _val("audio.treble", 0),
            "audio_fader": _val("audio.fader", 0),
            "audio_balance": _val("audio.balance", 0),
            # Notifications
            "notifications": _val("system.notifications", []),
            # Vehicle status (from Arduino serial)
            "vehicle_doors": _val("vehicle.doors", {}),
            "vehicle_handbrake": _val("vehicle.handbrake", False),
            "vehicle_cruise": _val("vehicle.cruise", False),
            "vehicle_immo_ok": _val("vehicle.immo_ok", True),
            "vehicle_airbag_ok": _val("vehicle.airbag_ok", True),
            "vehicle_rain": _val("vehicle.rain", False),
            # Parking
            "parking_distances": _val("parking.distances", []),
            "parking_active": _val("parking.active", False),
            # SWC navigation
            "navigate_aa": _val("input.navigate_aa", False),
        }

    def _handle_browser_key(self, key: str) -> None:
        """Map browser key to event bus input."""
        if self._event_bus is None:
            return
        mapped = _BROWSER_KEY_MAP.get(key, key.lower())
        self._event_bus.publish("input.raw_keyname", mapped)
        log.debug("Browser key: %s -> %s", key, mapped)

    def _on_aa_voice_trigger(self, topic: str, value, timestamp: float) -> None:
        """Tap the AA mic icon via xdotool when voice button is pressed."""
        if not value:
            return
        try:
            rel_x, rel_y = 0.05, 0.08
            w = self._config.get("display.multimedia.width", 1024) if self._config else 1024
            h = self._config.get("display.multimedia.height", 504) if self._config else 504
            px = int(rel_x * w)
            py = int(rel_y * h)
            subprocess.run(
                ["xdotool", "mousemove", "--screen", "0",
                 str(px), str(py), "click", "1"],
                timeout=2, capture_output=True,
                env={**os.environ, "DISPLAY": ":99"},
            )
            log.info("Voice-AA: tapped AA mic icon at (%d, %d)", px, py)
        except Exception as e:
            log.warning("Voice-AA tap failed: %s", e)

    def _broadcast_loop(self) -> None:
        """Periodically broadcast event bus data to all WebSocket clients."""
        while self._running:
            try:
                # No clients — skip the ~60 event-bus reads + JSON dump
                # instead of burning CPU at 15 FPS into the void.
                with self._ws_lock:
                    has_clients = bool(self._ws_clients)
                if not has_clients:
                    time.sleep(0.2)
                    continue

                data = self._get_dashboard_data()
                payload = json.dumps(data, default=str)

                # Send OUTSIDE the lock — a half-open/slow client used to
                # block connect/disconnect handlers (same lock) and every
                # other client for the duration of its send().
                with self._ws_lock:
                    clients = list(self._ws_clients)
                dead = []
                for ws in clients:
                    try:
                        ws.send(payload)
                    except Exception:
                        dead.append(ws)
                if dead:
                    with self._ws_lock:
                        for ws in dead:
                            if ws in self._ws_clients:
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

        # --- Module toggles (Settings -> Moduły) ---

        @app.route("/api/modules", methods=["GET"])
        def api_modules_get():
            cfg = viewer._config
            if cfg is None:
                return jsonify({"modules": []})
            from src.core.modules_catalog import catalog_state
            return jsonify({"modules": catalog_state(cfg)})

        @app.route("/api/modules", methods=["POST"])
        def api_modules_set():
            """Persist a module toggle. Takes effect after BCM restart."""
            cfg = viewer._config
            if cfg is None:
                return jsonify({"error": "no config"}), 500
            data = request.get_json(silent=True) or {}
            name = data.get("name")
            from src.core.modules_catalog import MODULES
            if name not in MODULES:
                return jsonify({"error": f"unknown module: {name}"}), 400
            enabled = bool(data.get("enabled"))
            cfg.set(f"modules.{name}", enabled)
            # Keep the legacy ad-hoc key in sync so code that still reads
            # it directly (e.g. openauto's wifi.enabled warning) agrees.
            legacy = MODULES[name].get("legacy_key")
            if legacy:
                cfg.set(legacy, enabled)
            try:
                cfg.save()
            except Exception as e:
                return jsonify({"error": f"save failed: {e}"}), 500
            if viewer._event_bus:
                viewer._event_bus.publish("config.changed",
                                          {"module": name, "enabled": enabled})
            return jsonify({"ok": True, "restart_required": True})

        # --- SWC mapping API ---

        @app.route("/api/config/swc", methods=["GET"])
        def api_swc_get():
            cfg = viewer._config
            if cfg is None:
                return jsonify({})
            mapping = cfg.get("swc.mapping")
            if not isinstance(mapping, dict):
                from src.input.swc_remote import DEFAULT_MAPPING
                mapping = DEFAULT_MAPPING
            from src.input.swc_remote import ALL_BUTTONS, ACTIONS
            return jsonify({
                "mapping": mapping,
                "all_buttons": ALL_BUTTONS,
                "actions": [a for a in ACTIONS if a != "disabled"],
            })

        @app.route("/api/config/swc", methods=["POST"])
        def api_swc_set():
            cfg = viewer._config
            if cfg is None:
                return jsonify({"error": "no config"}), 500
            data = request.get_json(silent=True) or {}
            mapping = data.get("mapping")
            if not isinstance(mapping, dict):
                return jsonify({"error": "mapping must be a dict"}), 400
            cfg.set("swc.mapping", mapping)
            cfg.save()
            if viewer._event_bus:
                viewer._event_bus.publish("input.swc_config_changed", mapping)
            return jsonify({"ok": True})

        # --- SWC learn mode ---

        _swc_learn = {"active": False, "action": "", "pod": 0,
                      "result": None, "ts": 0}

        def _on_learn_keycode(topic, value, timestamp):
            if not _swc_learn["active"] or not isinstance(value, int):
                return
            from src.input.swc_remote import KEYCODE_TO_BUTTON
            btn_pair = KEYCODE_TO_BUTTON.get(value)
            if not btn_pair:
                return
            pod = _swc_learn["pod"]
            button_name = btn_pair[min(pod, 1)]
            action = _swc_learn["action"]
            _swc_learn["result"] = button_name
            _swc_learn["active"] = False
            cfg = viewer._config
            if cfg and action:
                from src.input.swc_remote import DEFAULT_MAPPING
                mapping = cfg.get("swc.mapping")
                if not isinstance(mapping, dict):
                    mapping = dict(DEFAULT_MAPPING)
                if action in mapping and isinstance(mapping[action], list):
                    mapping[action][min(pod, len(mapping[action]) - 1)] = button_name
                    cfg.set("swc.mapping", mapping)
                    cfg.save()

        def _on_learn_keyname(topic, value, timestamp):
            if not _swc_learn["active"] or not isinstance(value, str):
                return
            from src.input.action_dispatch import KEYBOARD_MAP
            keycode = KEYBOARD_MAP.get(value.lower())
            if keycode is not None:
                _on_learn_keycode("", keycode, timestamp)

        if viewer._event_bus:
            viewer._event_bus.subscribe("input.raw_keycode", _on_learn_keycode)
            viewer._event_bus.subscribe("input.raw_keyname", _on_learn_keyname)

        @app.route("/api/config/swc/learn", methods=["POST"])
        def api_swc_learn_start():
            data = request.get_json(silent=True) or {}
            _swc_learn.update(
                active=True, action=data.get("action", ""),
                pod=data.get("pod", 0), result=None, ts=time.time())
            return jsonify({"ok": True})

        @app.route("/api/config/swc/learn", methods=["GET"])
        def api_swc_learn_status():
            if _swc_learn["active"] and time.time() - _swc_learn["ts"] > 10:
                _swc_learn["active"] = False
            return jsonify({
                "active": _swc_learn["active"],
                "result": _swc_learn["result"],
                "action": _swc_learn["action"],
                "pod": _swc_learn["pod"],
            })

        # --- Audio EQ API ---

        def _get_audio_ctrl():
            if viewer._event_bus:
                result = viewer._event_bus.get_last("audio._internals")
                if result and result[0]:
                    return result[0].get("pipewire")
            return None

        @app.route("/api/audio/eq", methods=["GET"])
        def api_audio_eq_get():
            from src.audio.pipewire_ctrl import EQ_PRESETS, EQ_FREQUENCIES
            pw = _get_audio_ctrl()
            return jsonify({
                "preset": pw.current_eq_preset if pw else "flat",
                "gains": EQ_PRESETS.get(
                    pw.current_eq_preset if pw else "flat",
                    [0] * 10),
                "frequencies": EQ_FREQUENCIES,
                "presets": list(EQ_PRESETS.keys()),
                "bass": pw.bass if pw else 0,
                "treble": pw.treble if pw else 0,
                "fader": pw.fader if pw else 0,
                "balance": pw.balance if pw else 0,
            })

        @app.route("/api/audio/eq", methods=["POST"])
        def api_audio_eq_set():
            pw = _get_audio_ctrl()
            if not pw:
                return jsonify({"error": "audio not available"}), 503
            data = request.get_json(silent=True) or {}
            ok = True
            if "preset" in data:
                ok = pw.apply_eq_preset(data["preset"]) and ok
            if "gains" in data:
                ok = pw.set_custom_gains(data["gains"]) and ok
            if "bass" in data or "treble" in data:
                ok = pw.set_bass_treble(
                    data.get("bass", pw.bass),
                    data.get("treble", pw.treble),
                ) and ok
            if "fader" in data:
                ok = pw.set_fader(data["fader"]) and ok
            if "balance" in data:
                ok = pw.set_balance(data["balance"]) and ok
            return jsonify({"ok": ok})

        @app.route("/api/audio/volume", methods=["POST"])
        def api_audio_volume_set():
            data = request.get_json(silent=True) or {}
            if viewer._event_bus:
                internals = viewer._event_bus.get_last("audio._internals")
                if internals and internals[0]:
                    vol_ctrl = internals[0].get("volume")
                    if vol_ctrl:
                        if "volume" in data:
                            vol_ctrl.set_volume(int(data["volume"]))
                        if "mute" in data:
                            if data["mute"]:
                                vol_ctrl.mute()
                            else:
                                vol_ctrl.unmute()
                        return jsonify({"ok": True})
            return jsonify({"error": "audio not available"}), 503

        # --- Boot mode API ---

        # --- Kiosk readiness gate ---
        # Splash polls /api/ready and dismisses itself the moment the
        # browser-side App.init() has finished — that's the only way to
        # know Chromium has actually painted the dashboard, not just
        # that Flask is answering. POST flips the flag, GET returns
        # 200/204 depending on the state.
        @app.route("/api/ready", methods=["POST"])
        def api_ready_set():
            viewer._kiosk_ready = True
            return ("", 204)

        @app.route("/api/ready", methods=["GET"])
        def api_ready_get():
            if getattr(viewer, "_kiosk_ready", False):
                return jsonify({"ready": True})
            return jsonify({"ready": False}), 503

        @app.route("/api/boot_mode")
        def api_boot_mode():
            state_file = Path("/tmp/bcm_power_state")
            result = {"boot_mode": "warm"}
            if state_file.exists():
                try:
                    for line in state_file.read_text().strip().split("\n"):
                        if "=" in line:
                            k, v = line.split("=", 1)
                            result[k.strip()] = v.strip()
                except Exception:
                    pass
            return jsonify(result)

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

        def _aa_canvas_size_local() -> tuple[int, int]:
            """Match the AA canvas calculation in src.multimedia.openauto.

            Imported lazily so the web viewer doesn't hard-fail if the
            multimedia module is missing (e.g. when AA is disabled).
            """
            try:
                from src.multimedia.openauto import _aa_canvas_size
                return _aa_canvas_size(viewer._config) if viewer._config else (1024, 504)
            except Exception:
                cfg = viewer._config
                w = cfg.get("display.multimedia.width", 1024) if cfg else 1024
                h = cfg.get("display.multimedia.height", 504) if cfg else 504
                return int(w), int(h)

        def _aa_mjpeg_generator():
            """Stream MJPEG frames from Xvfb (:99) using ffmpeg."""
            w, h = _aa_canvas_size_local()
            try:
                proc = subprocess.Popen(
                    ["ffmpeg", "-f", "x11grab", "-framerate", "25",
                     "-video_size", f"{w}x{h}",
                     "-draw_mouse", "0",
                     "-i", ":99",
                     "-f", "mjpeg", "-q:v", "3",
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
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()  # ffmpeg ignored SIGTERM — don't leak it
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
            w, h = _aa_canvas_size_local()
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

        # --- Radio (BT + WiFi AP) toggles —--------------------------
        # Backs the two on/off switches in the settings page. The
        # cosmetic-only toggle that used to live in settings.js never
        # touched the radios (works in the simulator VM, didn't on
        # baremetal), which the user reported as "settings page for
        # WLAN, and BT are not influence on those modems".

        def _wifi_ap_status():
            wa = viewer._wifi_ap
            if wa is None:
                # WiFi AP module not loaded in this run, but the system
                # may still have hostapd running (setup-x86.sh installs
                # it as a system service) — surface that so the toggle
                # reflects reality.
                hostapd_active = False
                try:
                    rc = subprocess.run(
                        ["systemctl", "is-active", "hostapd"],
                        capture_output=True, text=True, timeout=3,
                    ).stdout.strip()
                    hostapd_active = (rc == "active")
                except Exception:
                    pass
                return {
                    "available": hostapd_active,
                    "running": hostapd_active,
                    "ssid": (viewer._config.get("wifi.ssid", "")
                             if viewer._config else ""),
                    "managed_by": "hostapd" if hostapd_active else None,
                }
            return {
                "available": True,
                "running": wa.running,
                "ssid": (viewer._config.get("wifi.ssid", "")
                         if viewer._config else ""),
                "interface": wa.interface,
                "managed_by": "bcm",
            }

        @app.route("/api/radio/status")
        def api_radio_status():
            bt = viewer._bt_manager
            bt_info = {"available": False, "powered": False,
                       "discoverable": False}
            if bt:
                ctrl = bt.get_controller_info()
                bt_info = {
                    "available": bool(ctrl.get("available")),
                    "powered": bool(ctrl.get("powered", False)),
                    "discoverable": bool(ctrl.get("discoverable", False)),
                    "name": ctrl.get("name", ""),
                    "address": ctrl.get("address", ""),
                }
            return jsonify({"bt": bt_info, "wifi": _wifi_ap_status()})

        @app.route("/api/radio/bt", methods=["POST"])
        def api_radio_bt():
            bt = viewer._bt_manager
            if not bt:
                return jsonify({"error": "BT not available"}), 503
            data = request.get_json(silent=True) or {}
            enabled = bool(data.get("enabled", True))
            ok = bt.set_powered(enabled)
            ctrl = bt.get_controller_info()
            return jsonify({
                "success": ok,
                "powered": bool(ctrl.get("powered", False)),
            })

        @app.route("/api/wifi/config", methods=["GET"])
        def api_wifi_config_get():
            cfg = viewer._config
            if cfg is None:
                return jsonify({})
            # wifi.*_runtime are set by wifi_ap.py when a P2P-GO group
            # comes up — wpa_supplicant assigns a random DIRECT-XX SSID
            # and WPA2 passphrase that override the YAML defaults. Show
            # those as the LIVE values; expose the YAML values too so
            # the user knows what gets used in hostapd mode.
            mode = cfg.get("wifi.mode", "p2p_go")
            live_ssid = cfg.get("wifi.ssid_runtime", "") or cfg.get("wifi.ssid", "")
            live_pwd = cfg.get("wifi.password_runtime", "") or cfg.get("wifi.password", "")
            live_bssid = cfg.get("wifi.bssid_runtime", "")
            return jsonify({
                # legacy fields — still the YAML values so the Save
                # button can write them back without overwriting the
                # auto-generated P2P-GO credentials.
                "ssid": cfg.get("wifi.ssid", ""),
                "password": cfg.get("wifi.password", ""),
                "channel": cfg.get("wifi.channel", 6),
                # live values (what the phone actually connects to)
                "mode": mode,
                "live_ssid": live_ssid,
                "live_password": live_pwd,
                "live_bssid": live_bssid,
                # ALFA-NET (still a regular hostapd AP, user-editable)
                "alfa_net_enabled": bool(
                    cfg.get("wifi.alfa_net.enabled", True)),
                "alfa_net_ssid": cfg.get("wifi.alfa_net.ssid", "ALFA-NET"),
                "alfa_net_password": cfg.get(
                    "wifi.alfa_net.password", "AlfaRomeo156"),
            })

        @app.route("/api/wifi/config", methods=["POST"])
        def api_wifi_config_set():
            cfg = viewer._config
            if cfg is None:
                return jsonify({"ok": False, "error": "no config"}), 500
            data = request.get_json(silent=True) or {}
            ssid = (data.get("ssid") or "").strip()
            password = data.get("password") or ""
            channel = data.get("channel")
            if not ssid or len(ssid) > 32:
                return jsonify({"ok": False,
                                "error": "ssid must be 1-32 chars"}), 400
            if not isinstance(password, str) or not (8 <= len(password) <= 63):
                return jsonify({"ok": False,
                                "error": "password must be 8-63 chars"}), 400
            try:
                channel = int(channel)
            except (TypeError, ValueError):
                return jsonify({"ok": False,
                                "error": "channel must be a number"}), 400
            # Channel range — accept 2.4 GHz (1-13) and 5 GHz UNII bands.
            valid_5ghz = {36, 40, 44, 48, 149, 153, 157, 161, 165}
            if not (1 <= channel <= 13 or channel in valid_5ghz):
                return jsonify({"ok": False,
                                "error": "channel must be 1-13 or "
                                         "36/40/44/48/149/153/157/161/165"
                                }), 400

            cfg.set("wifi.ssid", ssid)
            cfg.set("wifi.password", password)
            cfg.set("wifi.channel", channel)

            # Optional ALFA-NET fields — only update if explicitly provided
            # so calls from older clients don't blank the secondary AP.
            an_ssid = data.get("alfa_net_ssid")
            an_pwd = data.get("alfa_net_password")
            an_enabled = data.get("alfa_net_enabled")
            if an_ssid is not None:
                an_ssid = (an_ssid or "").strip()
                if an_ssid and len(an_ssid) <= 32:
                    cfg.set("wifi.alfa_net.ssid", an_ssid)
            if an_pwd is not None:
                if isinstance(an_pwd, str) and 8 <= len(an_pwd) <= 63:
                    cfg.set("wifi.alfa_net.password", an_pwd)
                elif an_pwd != "":
                    return jsonify({"ok": False,
                                    "error": "ALFA-NET password 8-63 chars"
                                    }), 400
            if an_enabled is not None:
                cfg.set("wifi.alfa_net.enabled", bool(an_enabled))
            try:
                cfg.save()
            except Exception as e:
                log.exception("Saving wifi config failed")
                return jsonify({"ok": False, "error": str(e)}), 500

            # Regenerate openauto.ini so the autoapp picks up new
            # credentials on next AA start. The file is tiny; we drop
            # it here and let openauto.start() recreate it.
            try:
                ini_path = os.path.join(os.getcwd(), "openauto.ini")
                if os.path.exists(ini_path):
                    os.remove(ini_path)
            except Exception:
                log.debug("Could not refresh openauto.ini", exc_info=True)

            if viewer._event_bus:
                viewer._event_bus.publish("config.wifi_changed", {
                    "ssid": ssid, "channel": channel,
                })

            # System hostapd needs a restart to pick up the new
            # /etc/hostapd/hostapd.conf. We don't auto-restart here —
            # the user toggles Wi-Fi AP off/on in the UI to apply,
            # which keeps the action visible (avoids surprising
            # connectivity drops).
            return jsonify({"ok": True, "restart_required": True})

        @app.route("/api/radio/wifi", methods=["POST"])
        def api_radio_wifi():
            data = request.get_json(silent=True) or {}
            enabled = bool(data.get("enabled", True))
            wa = viewer._wifi_ap
            # Path 1: WiFi AP managed by the BCM module (start/stop).
            if wa is not None:
                ok = wa.start() if enabled else (wa.stop() or True)
                return jsonify({
                    "success": bool(ok),
                    "running": wa.running,
                    "managed_by": "bcm",
                })
            # Path 2: hostapd-managed AP (the setup-x86.sh path). The
            # BCM process can't import hostapd state, but it can ask
            # systemd to flip it.
            try:
                action = "start" if enabled else "stop"
                if enabled:
                    # Unblock rfkill before hostapd start — without this
                    # the toggle "permanent disables" the WLAN: hostapd
                    # systemd unit reports active but the radio never
                    # transmits because the card is soft-blocked.
                    subprocess.run(["rfkill", "unblock", "wifi"],
                                   capture_output=True, timeout=3)
                    subprocess.run(["rfkill", "unblock", "all"],
                                   capture_output=True, timeout=3)
                subprocess.run(["systemctl", action, "hostapd"],
                               capture_output=True, timeout=10)
                if enabled:
                    subprocess.run(["systemctl", "start", "dnsmasq"],
                                   capture_output=True, timeout=5)
                else:
                    subprocess.run(["rfkill", "block", "wifi"],
                                   capture_output=True, timeout=3)
                rc = subprocess.run(
                    ["systemctl", "is-active", "hostapd"],
                    capture_output=True, text=True, timeout=3,
                ).stdout.strip()
                return jsonify({
                    "success": True,
                    "running": rc == "active",
                    "managed_by": "hostapd",
                })
            except Exception as e:
                log.exception("WiFi AP toggle via systemd failed")
                return jsonify({"success": False, "error": str(e)}), 500

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

        @app.route("/api/media/<action>", methods=["POST"])
        def api_media_control(action):
            """AVRCP transport control for the now-playing media cards.

            Republishes on bt.cmd.media; BluetoothManager drives the
            phone's MediaPlayer1 over D-Bus.
            """
            action = (action or "").lower()
            if action not in ("play", "pause", "playpause", "next", "previous"):
                return jsonify({"ok": False, "error": "bad action"}), 400
            if viewer._event_bus:
                viewer._event_bus.publish("bt.cmd.media", action)
            return jsonify({"ok": True, "action": action})

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

        # --- Travel plan API (A3 Trip screen "Travel Plan" toggle) ---

        @app.route("/api/trip/search")
        def api_trip_search():
            """Geocode a city name for destination selection.

            Reuses the OpenWeatherMap Geocoding API since BCM already
            depends on it for weather search. Results share the same
            shape as /api/weather/search.
            """
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
                results = [{
                    "name": r.get("name", ""),
                    "country": r.get("country", ""),
                    "state": r.get("state", ""),
                    "lat": r.get("lat", 0),
                    "lon": r.get("lon", 0),
                } for r in raw]
                return jsonify({"results": results})
            except Exception as e:
                return jsonify({"results": [], "error": str(e)}), 500

        @app.route("/api/trip/destination", methods=["POST"])
        def api_trip_set_destination():
            """Set travel-plan destination and trigger RoutePlanner.plan()."""
            if viewer._trip_computer is None:
                return jsonify({"error": "trip computer not available"}), 503
            data = request.get_json(silent=True) or {}
            lat = data.get("lat")
            lon = data.get("lon")
            name = data.get("name") or data.get("city") or "Destination"
            if lat is None or lon is None:
                return jsonify({"error": "missing lat/lon"}), 400
            viewer._trip_computer.set_destination(
                float(lat), float(lon), str(name),
            )
            return jsonify({"ok": True, "name": name})

        @app.route("/api/trip/clear", methods=["POST"])
        def api_trip_clear():
            """Clear the active travel plan."""
            if viewer._trip_computer is None:
                return jsonify({"error": "trip computer not available"}), 503
            viewer._trip_computer.clear_destination()
            return jsonify({"ok": True})

        @app.route("/api/trip/route")
        def api_trip_route():
            """Return the current computed travel plan (or null)."""
            if viewer._trip_computer is None:
                return jsonify(None)
            return jsonify(viewer._trip_computer.get_plan_dict())

        # --- Debug endpoints ---

        @app.route("/api/debug/weather")
        def api_debug_weather():
            """Debug endpoint: dump weather module state for troubleshooting."""
            bus = viewer._event_bus
            if not bus:
                return jsonify({"error": "no event bus"})
            def _last(topic):
                r = bus.get_last(topic)
                return r[0] if r else None
            return jsonify({
                "weather_current": _last("weather.current"),
                "weather_city": _last("weather.city"),
                "weather_lat": _last("weather.lat"),
                "weather_lon": _last("weather.lon"),
                "weather_forecast": _last("weather.forecast"),
                "gps_lat": _last("gps.lat"),
                "gps_lon": _last("gps.lon"),
                "gps_fix": _last("gps.fix"),
                "lte_connected": _last("lte.connected"),
                "config_api_key_set": bool(viewer._config.get("weather", {}).get("api_key", "")) if viewer._config else False,
                "config_platform": viewer._config.get("system", {}).get("platform", "?") if viewer._config else "?",
                "hint": "If weather_current is null and api_key is set, check server logs for HTTP errors. New OWM keys take up to 2h to activate.",
            })

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
            """MJPEG stream from a role-addressed USB camera.

            Query param ``cam`` selects the camera role
            (``front`` | ``rear`` | ``left`` | ``right``). The role is
            resolved to a /dev/videoN device via the master config.
            Defaults to ``rear`` for backwards compatibility with the
            original reverse-camera-only endpoint.
            """
            try:
                import cv2
            except ImportError:
                return "opencv not available", 503

            role = (request.args.get("cam") or "rear").lower()
            if role not in ("front", "rear", "left", "right"):
                return "invalid cam role", 400

            device_path = viewer._config.get(
                f"camera.{role}_device", None
            ) if viewer._config else None

            def _open_capture():
                # Prefer config-supplied /dev/videoN; fall back to 0 for legacy.
                if device_path:
                    c = cv2.VideoCapture(device_path)
                    if c.isOpened():
                        return c
                return cv2.VideoCapture(0)

            def gen_frames():
                cap = _open_capture()
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
            """Check which cameras are available.

            Returns a dict keyed by role (front/rear/left/right) with
            bool values. Legacy callers that ignore keys still see
            ``available`` set to True iff any camera is reachable.
            """
            try:
                import cv2
            except ImportError:
                return jsonify({"available": False})

            result: dict[str, bool] = {}
            for role in ("front", "rear", "left", "right"):
                dev = viewer._config.get(
                    f"camera.{role}_device", None
                ) if viewer._config else None
                if not dev:
                    result[role] = False
                    continue
                try:
                    c = cv2.VideoCapture(dev)
                    result[role] = bool(c.isOpened())
                    c.release()
                except Exception:
                    result[role] = False
            result["available"] = any(result.values())
            return jsonify(result)

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

        # threaded=True: the dashboard renders fire many concurrent
        # GETs (radio status, wifi config, BT lists, music, weather…)
        # plus the touch input WS. A single-threaded werkzeug serializes
        # everything, so a slow handler (e.g. bluetoothctl scan, nmcli)
        # stalls every other endpoint and the UI feels frozen on touch.
        app.run(host=self.host, port=self.port, debug=False,
                use_reloader=False, threaded=True)
