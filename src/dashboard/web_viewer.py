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
import select
import shutil
import subprocess
import time
import threading
from pathlib import Path
from typing import Optional, Any, Hashable
from urllib.parse import urlsplit

from src.core.logger import get_logger
from src.core.notifications import active_notifications
from src.network.phone_tether import HINTS as _TETHER_HINTS
from src.network.phone_tether import RETRY_TOPIC as _TETHER_RETRY_TOPIC
from src.network.phone_tether import STATES as _TETHER_STATES
from src.weather.weather import valid_coords

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
#
# The media entries are what makes the steering-wheel pod's NEXT/PREV/VOL/MUTE
# buttons do anything. The Arduino sends those as HID consumer-page keys, which
# Chromium reports as "MediaTrackNext", "AudioVolumeUp" and friends — names
# that were in neither this table nor KEYBOARD_MAP, so they fell through to the
# lowercased-key fallback ("mediatracknext"), matched nothing and were dropped.
# The wheel buttons that use ordinary keys (Home, F5-F9) worked all along,
# which is why the pod looked half-wired: phone and nav responded, tracks did
# not.
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
    "MediaTrackNext": "n",
    "MediaTrackPrevious": "p",
    "MediaPlayPause": "space",
    "AudioVolumeUp": "+",
    "AudioVolumeDown": "-",
    "AudioVolumeMute": "0",
}


# ── /ws/input + /aa/touch ────────────────────────────────────────────────
#: Larger input messages are dropped unparsed. A real one is ~80 bytes.
_MAX_INPUT_MESSAGE = 4096
#: KeyboardEvent.key values are short ("MediaTrackPrevious" is the longest
#: one we map); anything longer is not a key.
_MAX_KEY_NAME = 32
#: Actions accepted by the HTTP fallback POST /aa/touch (no "move": see there).
_AA_HTTP_TOUCH_ACTIONS = ("tap", "down", "up", "cancel")


def _ws_origin_allowed(origin: Optional[str], host: Optional[str]) -> bool:
    """Is a WebSocket handshake with this ``Origin`` from our own page?

    Browsers do no CORS check on WebSockets: any page the browser opens —
    e.g. the phone browsing while joined to the head unit's AP — could open
    /ws/input and inject keys and, since AA drags go over it too, touches
    into the phone's AA session. Browsers always send ``Origin`` on a
    WebSocket handshake, so a present Origin must name this server (scheme
    http/https, host:port equal to the ``Host`` header; the kiosk uses
    http://localhost:5002 and connects to ``location.host``). A missing
    Origin is a non-browser client and stays allowed. Not a defence against
    DNS rebinding (there Origin and Host agree) — the network access policy
    is the layer for that.
    """
    if origin is None:
        return True
    try:
        parts = urlsplit(origin.strip())
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or not parts.netloc or not host:
        return False
    default_port = ":443" if parts.scheme == "https" else ":80"

    def _norm(netloc: str) -> str:
        netloc = netloc.strip().lower()
        return netloc[:-len(default_port)] if netloc.endswith(default_port) else netloc

    return _norm(parts.netloc) == _norm(host)

# ── /aa/stream (MJPEG from Xvfb) ─────────────────────────────────────────
# Each stream is one ffmpeg x11grab process. The old generator did a blocking
# read(): if Xvfb wedged or vanished during an AA restart, the request thread
# and its ffmpeg hung forever, and every kiosk reload added another pair.
#: poll() timeout on ffmpeg's stdout (poll, not select: select() raises
#: ValueError for any fd >= FD_SETSIZE (1024), so a 24/7 process that ever
#: held ~1000 descriptors would end every stream at once).
_AA_STREAM_READ_TIMEOUT_S = 5.0
#: End the stream after this long without a complete JPEG frame; the kiosk
#: reconnects with backoff.
_AA_STREAM_STALL_S = 10.0
#: Concurrent streams kept alive; the newest win (a reloaded kiosk must not be
#: refused because its previous incarnation is still draining). A retired
#: stream's ffmpeg is terminated directly, because its request thread may be
#: stuck inside a write to a client that stopped reading.
_AA_STREAM_MAX_CLIENTS = 2
#: A partial frame bigger than this is garbage — drop it instead of growing.
_AA_STREAM_MAX_BUFFER = 8 * 1024 * 1024


# ── /api/config POST validation ──────────────────────────────────────────
# The endpoint used to store whatever JSON it received; since the values now
# persist to config/local.yaml, a bogus theme or a string brightness would
# survive restarts. Allowed values mirror the Settings screen
# (web/js/screens/settings.js) and settings_screen.py.
_CONFIG_THEMES = ("heritage", "modern", "autodelta")
_CONFIG_SPEED_UNITS = ("km/h", "mph")
_CONFIG_TEMP_UNITS = ("C", "F")

# request key → config dot-path, in the order they are applied
_CONFIG_FIELDS = (
    ("theme", "display.dashboard.theme"),
    ("language", "language"),
    ("speed_unit", "units.speed"),
    ("temp_unit", "units.temperature"),
    ("brightness", "display.dashboard.brightness"),
    ("aa_auto_restart", "multimedia.aa_auto_restart"),
)


def _available_languages() -> tuple:
    from src.dashboard.i18n import STRINGS
    return tuple(STRINGS)


def _validate_config_update(data: Any) -> tuple[list[tuple[str, str, Any]], Optional[tuple[str, str]]]:
    """Validate a POST /api/config body.

    Returns ``(updates, error)``: ``updates`` is a list of
    ``(request_key, config_path, value)`` to apply; ``error`` is
    ``(request_key, message)`` for the first invalid field, in which case
    nothing may be applied (all-or-nothing). Unknown keys are ignored, as
    before.
    """
    if not isinstance(data, dict):
        return [], ("", "body must be a JSON object")
    updates: list[tuple[str, str, Any]] = []
    for key, config_key in _CONFIG_FIELDS:
        if key not in data:
            continue
        value = data[key]
        if key == "theme":
            if value not in _CONFIG_THEMES:
                return [], (key, f"theme must be one of {list(_CONFIG_THEMES)}")
        elif key == "language":
            languages = _available_languages()
            if value not in languages:
                return [], (key, f"language must be one of {list(languages)}")
        elif key == "speed_unit":
            if value not in _CONFIG_SPEED_UNITS:
                return [], (key, f"speed_unit must be one of {list(_CONFIG_SPEED_UNITS)}")
        elif key == "temp_unit":
            if value not in _CONFIG_TEMP_UNITS:
                return [], (key, f"temp_unit must be one of {list(_CONFIG_TEMP_UNITS)}")
        elif key == "brightness":
            # bool is an int subclass — True must not become brightness 1.
            if isinstance(value, float) and value.is_integer():
                value = int(value)
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
                return [], (key, "brightness must be an integer 0-100")
        elif key == "aa_auto_restart":
            if not isinstance(value, bool):
                return [], (key, "aa_auto_restart must be true or false")
        updates.append((key, config_key, value))
    return updates, None


#: Wi-Fi secrets that may be provided by /etc/bcm/bcm.env (SECRET_ENV_MAP).
_WIFI_SECRET_PATHS = ("wifi.password", "wifi.alfa_net.password")


def _unpersisted_wifi_secrets(cfg: Any) -> list[str]:
    """Wi-Fi secret paths changed at runtime that bcm.env overrides on restart.

    Never raises; a config object without the helper (tests, older code)
    simply reports none.
    """
    changed = getattr(cfg, "unpersisted_secret_changes", None)
    if not callable(changed):
        return []
    try:
        return [p for p in changed() if p in _WIFI_SECRET_PATHS]
    except Exception:
        log.debug("unpersisted_secret_changes failed", exc_info=True)
        return []


def _save_config(cfg: Any, what: str) -> bool:
    """Persist ``cfg`` to the local overlay; never raises.

    Returns True if the change is on disk. A save failure must not turn a
    successful in-memory change into an HTTP 500 or kill an event-bus
    callback — it is logged and reported as ``persisted: false``.
    """
    try:
        return bool(cfg.save())
    except Exception:
        log.exception("Saving config (%s) failed", what)
        return False


#: Minimum spacing of POST /api/phone_tether/retry (one nmcli attempt each).
_TETHER_RETRY_MIN_INTERVAL_S = 10.0


def _phone_tether_summary(value: Any) -> Optional[dict]:
    """``net.phone_tether`` → ``{state, ip, iface, hint}`` for the payload.

    Only what the Settings row shows, and only known states / hints and
    plausible lengths: the values come from nmcli output (the frontend
    escapes them too). Never published = the module is not running (the
    production config) = None, and Settings shows no row at all.
    """
    if not isinstance(value, dict):
        return None
    state = value.get("state")
    ip = value.get("ip")
    iface = value.get("iface")
    hint = value.get("hint")
    return {
        "state": state if isinstance(state, str) and state in _TETHER_STATES else "unknown",
        "ip": ip if isinstance(ip, str) and len(ip) <= 45 else "",
        "iface": iface if isinstance(iface, str) and len(iface) <= 15 else "",
        "hint": hint if isinstance(hint, str) and hint in _TETHER_HINTS else "",
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
        # Kiosk readiness gate for the boot/wake splash. Starts False so the
        # splash always waits for a fresh paint; flipped True by App.init()
        # POSTing /api/ready, and reset to False (e.g. from the resume hook
        # via /api/ready-reset) so the splash replays on every wake instead
        # of self-dismissing against a stale flag from the previous boot.
        self._kiosk_ready = False

        # Path to the web frontend files
        self._web_dir = os.path.join(os.path.dirname(__file__), "web")

        # AA touch injection (src/multimedia/aa_input.py), built on first use
        # so a dashboard without AA never starts the worker thread.
        self._aa_injector = None
        self._aa_injector_lock = threading.Lock()

        # POST /api/phone_tether/retry rate limit (monotonic: bcm-timesync
        # may move the wall clock right after the link comes up).
        self._tether_retry_lock = threading.Lock()
        self._tether_retry_last: Optional[float] = None

        # /aa/stream bookkeeping: generation ids of the live MJPEG streams
        # (oldest first) and each one's ffmpeg, so a newer stream can stop an
        # older one's capture even while that request thread is blocked.
        self._aa_stream_lock = threading.Lock()
        self._aa_stream_seq = 0
        self._aa_stream_active: list[int] = []
        self._aa_stream_procs: dict[int, Any] = {}

        # Forward voice-AA trigger to autoapp (M key or tap on the mic icon)
        if event_bus:
            event_bus.subscribe("aa.voice_trigger", self._on_aa_voice_trigger)
            # Xvfb is torn down on stop/restart — drop queued touches and the
            # pressed-button state that belonged to the old X server.
            event_bus.subscribe("multimedia.openauto_status",
                                self._on_openauto_status)

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
        injector = self._aa_injector
        if injector is not None:
            injector.stop()

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

        data = {
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
            # Reverse / camera routing. The reverse view now lives on the MAIN
            # display (rear large + L/R side-cam insets + sensor bar + beep);
            # camera_active is the CameraController's resolved feed
            # ("rear"/"left"/"right"/None), reverse_gear the raw signal.
            "reverse_gear": _val("power.reverse_gear", False),
            "camera_active": _val("camera.active_feed", None),
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
            "aa_auto_restart": _val("multimedia.aa_auto_restart",
                                   self._config.get("multimedia.aa_auto_restart", True) if self._config else True),
            # Bumped by OpenAutoController each time Xvfb (re)starts; A2
            # reconnects its MJPEG <img> when it changes.
            "aa_stream_epoch": _val("multimedia.aa_stream_epoch", 0),
            "lte_connected": _val("lte.connected", False),
            # src/network/lte.py publishes lte.signal (0-5 bars); the old
            # lte.signal_strength key was never published, so this was 0.
            "lte_signal": _val("lte.signal", 0),
            # Internet from the phone (src/network/phone_tether.py).
            "phone_tether": _phone_tether_summary(_val("net.phone_tether")),
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
            # Notifications (src/core/notifications.py) — expired entries are
            # dropped here, the topic itself is only republished on news.
            "notifications": active_notifications(_val("system.notifications", [])),
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
            # SWC navigation (edge-triggered — see reset below)
            "navigate_aa": _val("input.navigate_aa", False),
            "home": _val("input.home", False),
        }
        # The browser's DataStore only fires subscribers on value *change*, so
        # a latched True would navigate once and never again (and would nav
        # spuriously on reload). Emit True for exactly one broadcast frame then
        # reset to False, so every HOME/NAV press re-fires.
        for _nav in ("input.navigate_aa", "input.home"):
            if _val(_nav, False):
                bus.publish(_nav, False)
        return data

    def _handle_browser_key(self, key: str) -> None:
        """Map browser key to event bus input."""
        if self._event_bus is None:
            return
        mapped = _BROWSER_KEY_MAP.get(key, key.lower())
        self._event_bus.publish("input.raw_keyname", mapped)
        log.debug("Browser key: %s -> %s", key, mapped)

    def _on_aa_voice_trigger(self, topic: str, value, timestamp: float) -> None:
        """Press AA's voice control when the voice button is pressed.

        ``multimedia.aa_voice_method``: ``key`` sends the M key (autoapp:
        Qt::Key_M -> MICROPHONE_1), ``tap`` (default) taps the AA mic icon.
        The key only works when the running autoapp was started with
        VoiceCommandButton=true (there was a mic at the time); otherwise
        this falls back to the tap. Whether a press may reach AA at all
        (no mic -> notification) is decided upstream in VoiceAAHandler.

        Goes through the touch injector: same canvas size as Xvfb and the
        touch path (this used to read display.multimedia.* with a 504 px
        fallback), serialised with touches, and no 2 s subprocess call on
        the event-bus thread.
        """
        if not value:
            return
        from src.input.voice_aa import voice_method
        method = voice_method(self._config)
        injector = self._get_aa_injector()
        if method == "key":
            openauto = self._openauto()
            if openauto is not None and getattr(openauto, "voice_button_enabled", True) is False:
                log.info("Voice-AA: VoiceCommandButton is off in the running "
                         "autoapp (no mic when AA started) — tapping instead")
            elif injector is None or not injector.submit_key("m", client="voice"):
                log.warning("Voice-AA: key could not be queued (xdotool missing?)")
                return
            else:
                log.info("Voice-AA: sending the voice key (M) to autoapp")
                return
        rel_x, rel_y = 0.05, 0.08
        if injector is None or not injector.submit("tap", rel_x, rel_y, client="voice"):
            log.warning("Voice-AA: tap could not be queued (xdotool missing?)")
            return
        px, py = injector.to_pixels(rel_x, rel_y) or (0, 0)
        log.info("Voice-AA: tapping AA mic icon at (%d, %d)", px, py)

    # ── Android Auto helpers ─────────────────────────────────────────────

    def _openauto(self) -> Any:
        """The running OpenAutoController, if the multimedia module is up."""
        if self._event_bus:
            result = self._event_bus.get_last("multimedia._internals")
            if result and result[0]:
                return result[0].get("openauto")
        return None

    def _aa_canvas_size(self) -> tuple[int, int]:
        """AA canvas size — the one Xvfb, the MJPEG capture and touch use.

        Imported lazily so the web viewer doesn't hard-fail if the
        multimedia module is missing (e.g. when AA is disabled).
        """
        cfg = self._config
        try:
            from src.multimedia.openauto import _aa_canvas_size
            return _aa_canvas_size(cfg) if cfg else (1024, 504)
        except Exception:
            w = cfg.get("display.multimedia.width", 1024) if cfg else 1024
            h = cfg.get("display.multimedia.height", 504) if cfg else 504
            try:
                return int(w), int(h)
            except (TypeError, ValueError):
                return 1024, 504

    def _get_aa_injector(self) -> Any:
        """The touch injector, created on first use; None if it can't be."""
        if self._aa_injector is None:
            with self._aa_injector_lock:
                if self._aa_injector is None:
                    try:
                        from src.multimedia.aa_input import AATouchInjector
                        self._aa_injector = AATouchInjector(size_fn=self._aa_canvas_size)
                    except Exception:
                        log.exception("AA touch injector unavailable")
                        return None
        return self._aa_injector

    def _release_aa_touch(self, client_key: Hashable) -> None:
        """Release the AA button if ``client_key`` holds it. Never raises."""
        injector = self._aa_injector
        if injector is None:
            return
        try:
            injector.release(client_key)
        except Exception:
            log.debug("AA touch release failed", exc_info=True)

    def _on_openauto_status(self, topic: str, value: Any, timestamp: float) -> None:
        if value in ("stopped", "restarting"):
            injector = self._aa_injector
            if injector is not None:
                injector.reset()

    def _handle_input_message(self, msg: Any, client_key: Hashable = None) -> bool:
        """Dispatch one /ws/input message. Never raises; True if acted on.

        Accepts the raw WebSocket payload (str/bytes) or an already decoded
        dict. Messages:
          ``{"type": "keydown", "key": "<KeyboardEvent.key>"}``
          ``{"type": "aa_touch", "action": "down|move|up|cancel|tap",
             "x": 0..1, "y": 0..1}``
        Anything else — oversized, not JSON, wrong types — is dropped.
        """
        try:
            if isinstance(msg, (bytes, bytearray)):
                if len(msg) > _MAX_INPUT_MESSAGE:
                    return False
                msg = bytes(msg).decode("utf-8")
            if isinstance(msg, str):
                if len(msg) > _MAX_INPUT_MESSAGE:
                    return False
                data = json.loads(msg)
            else:
                data = msg
            if not isinstance(data, dict):
                return False
            kind = data.get("type")
            if kind == "keydown":
                key = data.get("key")
                if not isinstance(key, str) or not key or len(key) > _MAX_KEY_NAME:
                    return False
                self._handle_browser_key(key)
                return True
            if kind == "aa_touch":
                injector = self._get_aa_injector()
                if injector is None:
                    return False
                return injector.submit(data.get("action"), data.get("x"),
                                       data.get("y"), client=client_key)
            return False
        except Exception:
            log.debug("Dropped malformed /ws/input message", exc_info=True)
            return False

    def _serve_input_ws(self, ws: Any) -> None:
        """Read loop of one /ws/input connection.

        Keyboard (SWC pod, OSK) and AA touch share this socket. Message
        handling lives in _handle_input_message(), which never raises: this
        loop used to break on ANY exception, so one malformed message
        silently killed keyboard input until the page was reloaded.
        """
        client_key = id(ws)
        log.info("WebSocket client connected (input)")
        try:
            while self._running:
                try:
                    msg = ws.receive(timeout=1)
                except Exception:
                    break  # connection closed
                if msg is None:
                    continue
                self._handle_input_message(msg, client_key)
        finally:
            # A finger still down when the socket drops would leave the AA
            # button pressed — release whatever this client holds.
            self._release_aa_touch(client_key)
            log.info("WebSocket client disconnected (input)")

    def _aa_stream_alive(self, generation: int) -> bool:
        with self._aa_stream_lock:
            return generation in self._aa_stream_active

    @staticmethod
    def _terminate_stream_proc(proc: Any) -> None:
        """SIGTERM a retired stream's ffmpeg without waiting. Never raises.

        Reaping (wait/kill) stays with the generator that owns ``proc``: the
        newer request must not block on it.
        """
        try:
            proc.terminate()
        except Exception:
            log.debug("AA stream: terminating a retired ffmpeg failed", exc_info=True)

    def _aa_mjpeg_frames(self, popen: Any = None):
        """Yield multipart MJPEG parts captured from Xvfb (:99) by ffmpeg.

        * reads with poll() (``_AA_STREAM_READ_TIMEOUT_S``) and ends the
          stream after ``_AA_STREAM_STALL_S`` without a complete frame, so a
          dead X server frees the thread and ffmpeg;
        * at most ``_AA_STREAM_MAX_CLIENTS`` streams live at once — a new one
          retires the oldest and terminates its ffmpeg right away (that
          generator may be blocked in ``yield`` behind a stalled client and
          would otherwise keep x11grab + JPEG encoding running); the old
          loop then ends on EOF / the liveness check once its write returns.

        ``popen`` is a test seam (``subprocess.Popen`` by default).
        """
        w, h = self._aa_canvas_size()
        retired_procs = []
        with self._aa_stream_lock:
            self._aa_stream_seq += 1
            generation = self._aa_stream_seq
            self._aa_stream_active.append(generation)
            while len(self._aa_stream_active) > _AA_STREAM_MAX_CLIENTS:
                retired = self._aa_stream_active.pop(0)
                retired_proc = self._aa_stream_procs.pop(retired, None)
                if retired_proc is not None:
                    retired_procs.append(retired_proc)
                log.info("AA stream %d retired by newer stream %d", retired, generation)
        for retired_proc in retired_procs:
            self._terminate_stream_proc(retired_proc)
        proc = None
        try:
            try:
                # bufsize=0: a raw pipe, so poll() readiness and os.read()
                # agree (a buffered reader can hide data from poll()).
                proc = (popen or subprocess.Popen)(
                    ["ffmpeg", "-f", "x11grab", "-framerate", "25",
                     "-video_size", f"{w}x{h}",
                     "-draw_mouse", "0",
                     "-i", ":99",
                     "-f", "mjpeg", "-q:v", "3",
                     "-an", "pipe:1"],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    bufsize=0,
                )
            except Exception as e:
                log.warning("AA stream: ffmpeg could not start: %s", e)
                return
            with self._aa_stream_lock:
                # Retired while ffmpeg was starting? Then the loop below ends
                # at once and the finally block stops this proc.
                if generation in self._aa_stream_active:
                    self._aa_stream_procs[generation] = proc
            fd = proc.stdout.fileno()
            poller = select.poll()
            poller.register(fd, select.POLLIN | select.POLLHUP)
            timeout_ms = int(_AA_STREAM_READ_TIMEOUT_S * 1000)
            buf = b""
            SOI = b"\xff\xd8"
            EOI = b"\xff\xd9"
            last_frame = time.monotonic()
            while self._aa_stream_alive(generation):
                if time.monotonic() - last_frame > _AA_STREAM_STALL_S:
                    log.info("AA stream %d: no frame for %.0fs — closing",
                             generation, _AA_STREAM_STALL_S)
                    break
                try:
                    if not poller.poll(timeout_ms):
                        continue
                    # Readable, hung up or invalid: os.read() returns data,
                    # b"" (EOF) or raises — each handled below.
                    chunk = os.read(fd, 65536)
                except (OSError, ValueError) as e:
                    log.debug("AA stream %d: read failed: %s", generation, e)
                    break
                if not chunk:
                    break  # ffmpeg exited (no X server, killed, …)
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
                    last_frame = time.monotonic()
                    yield (b"--frame\r\n"
                           b"Content-Type: image/jpeg\r\n\r\n"
                           + frame + b"\r\n")
                if len(buf) > _AA_STREAM_MAX_BUFFER:
                    buf = b""
        finally:
            with self._aa_stream_lock:
                if generation in self._aa_stream_active:
                    self._aa_stream_active.remove(generation)
                self._aa_stream_procs.pop(generation, None)
            if proc is not None:
                try:
                    proc.terminate()
                    try:
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        proc.kill()  # ffmpeg ignored SIGTERM — don't leak it
                        proc.wait(timeout=3)
                except Exception:
                    log.debug("AA stream: ffmpeg cleanup failed", exc_info=True)
                try:
                    proc.stdout.close()
                except Exception:
                    pass

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
        app = self._build_app()
        # threaded=True: the dashboard renders fire many concurrent
        # GETs (radio status, wifi config, BT lists, music, weather…)
        # plus the touch input WS. A single-threaded werkzeug serializes
        # everything, so a slow handler (e.g. bluetoothctl scan, nmcli)
        # stalls every other endpoint and the UI feels frozen on touch.
        app.run(host=self.host, port=self.port, debug=False,
                use_reloader=False, threaded=True)

    def _build_app(self) -> "Flask":
        """Create the Flask app with every route, without serving it.

        Split from _run_server() so tests can drive the real routes through
        ``_build_app().test_client()`` instead of copying them.
        """
        app = Flask(__name__, static_folder=self._web_dir)
        # Bound what a browser may send over a WebSocket: the client never
        # sends anything on /ws, and /ws/input messages are ~100 bytes
        # (_handle_input_message drops anything over _MAX_INPUT_MESSAGE).
        # simple-websocket's default is unlimited; a larger frame now closes
        # that one socket and the page reconnects.
        app.config.setdefault("SOCK_SERVER_OPTIONS", {"max_message_size": 64 * 1024})
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

        @app.route("/splash/<path:filename>")
        def splash_asset(filename):
            # The boot/wake splash videos live outside the web dir, in the
            # repo's assets/splash/. The in-browser splash overlay
            # (components/splash.js) plays small.mp4 from here on page load
            # and on every WebSocket reconnect-after-sleep.
            splash_dir = os.path.join(
                os.path.dirname(__file__), "..", "..", "assets", "splash"
            )
            return send_from_directory(os.path.abspath(splash_dir), filename)

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
                "aa_auto_restart": cfg.get("multimedia.aa_auto_restart", True),
            })

        @app.route("/api/config", methods=["POST"])
        def api_config_set():
            cfg = viewer._config
            if cfg is None:
                return jsonify({"error": "no config"}), 500

            data = request.get_json(silent=True)
            if data is None:
                data = {}
            updates, error = _validate_config_update(data)
            if error is not None:
                key, message = error
                return jsonify({"ok": False, "error": message, "key": key}), 400

            for _key, config_key, value in updates:
                cfg.set(config_key, value)
            applied = {key: value for key, _ck, value in updates}

            if "aa_auto_restart" in applied:
                openauto = _get_openauto()
                if openauto:
                    openauto.auto_restart_enabled = applied["aa_auto_restart"]
                elif viewer._event_bus:
                    viewer._event_bus.publish("multimedia.aa_auto_restart",
                                              applied["aa_auto_restart"])

            # Persist (until now this endpoint never saved, so theme /
            # language / units reverted on every restart).
            persisted = _save_config(cfg, "settings") if applied else False

            # Notify event bus of config change (validated values only)
            if viewer._event_bus:
                viewer._event_bus.publish("config.changed", applied)

            return jsonify({"ok": True, "persisted": persisted})

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
            persisted = _save_config(cfg, f"module {name}")
            if viewer._event_bus:
                viewer._event_bus.publish("config.changed",
                                          {"module": name, "enabled": enabled})
            return jsonify({"ok": True, "restart_required": True,
                            "persisted": persisted})

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
            persisted = _save_config(cfg, "swc mapping")
            if viewer._event_bus:
                viewer._event_bus.publish("input.swc_config_changed", mapping)
            return jsonify({"ok": True, "persisted": persisted})

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
                    # Runs on the event-bus thread: a save error must not
                    # propagate into the dispatcher.
                    _save_config(cfg, "swc learn")

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

        @app.route("/api/ready-reset", methods=["POST"])
        def api_ready_reset():
            # Clears the readiness flag so the next splash run waits for a
            # fresh paint. The resume hook calls this before replaying the
            # splash on wake-from-sleep (the Flask process survives an
            # in-process wake, so the flag would otherwise still be True).
            viewer._kiosk_ready = False
            return ("", 204)

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

        @app.route("/aa/stream")
        def aa_stream():
            """Direct MJPEG stream from Xvfb (:99) — no port 5001 proxy."""
            return Response(viewer._aa_mjpeg_frames(),
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
            """Forward a touch to Xvfb (HTTP fallback of the /ws/input path).

            Body ``{"x": 0..1, "y": 0..1, "action"?: ...}``. Without
            ``action`` it is a tap, exactly as before. The kiosk only falls
            back here for tap/down/up/cancel while the input WebSocket is
            down; ``move`` is refused — a drag over HTTP would be one request
            (and one server thread) per frame.
            """
            data = request.get_json(silent=True)
            if data is None:
                data = {}
            if not isinstance(data, dict):
                return jsonify({"ok": False, "error": "body must be a JSON object"}), 400
            action = data.get("action", "tap")
            if action not in _AA_HTTP_TOUCH_ACTIONS:
                return jsonify({"ok": False,
                                "error": f"action must be one of {list(_AA_HTTP_TOUCH_ACTIONS)}"}), 400
            injector = viewer._get_aa_injector()
            if injector is None:
                return jsonify({"ok": False, "error": "touch injection unavailable"}), 503
            px = py = None
            if action != "cancel":
                # Missing coordinates keep the old default (canvas centre);
                # present-but-invalid ones (NaN, strings, bools) are a 400.
                pixels = injector.to_pixels(data.get("x", 0.5), data.get("y", 0.5))
                if pixels is None:
                    return jsonify({"ok": False, "error": "x and y must be finite numbers"}), 400
                px, py = pixels
            if not injector.submit(action, data.get("x", 0.5), data.get("y", 0.5),
                                   client="http"):
                return jsonify({"ok": False, "error": "touch injection unavailable"}), 503
            return jsonify({"ok": True, "action": action, "x": px, "y": py})

        def _get_openauto():
            return viewer._openauto()

        @app.route("/aa/restart", methods=["POST"])
        @app.route("/api/aa/restart", methods=["POST"])
        def aa_restart():
            """Manually restart OpenAuto process and Xvfb."""
            log.info("Manual AA restart requested via API")
            openauto = _get_openauto()
            if openauto:
                # A second tap while restart() runs must not start another
                # thread (the controller would refuse it anyway, but the UI
                # deserves to know it is already happening).
                if getattr(openauto, "restart_in_progress", False) is True:
                    return jsonify({"ok": True, "status": "already_restarting"})
                threading.Thread(target=openauto.restart, daemon=True, name="aa-http-restart").start()
                return jsonify({"ok": True, "status": "restarting"})
            elif viewer._event_bus:
                viewer._event_bus.publish("multimedia.restart_request", True)
                return jsonify({"ok": True, "status": "restarting"})
            return jsonify({"ok": False, "error": "openauto not available"}), 503

        @app.route("/api/aa/config", methods=["GET"])
        def aa_config_get():
            """Get Android Auto configuration and auto-restart setting."""
            openauto = _get_openauto()
            auto_restart = openauto.auto_restart_enabled if openauto else (
                viewer._config.get("multimedia.aa_auto_restart", True) if viewer._config else True
            )
            timeout = getattr(openauto, "_connection_timeout", 90) if openauto else (
                viewer._config.get("multimedia.aa_connection_timeout", 90) if viewer._config else 90
            )
            status = "unavailable"
            if viewer._event_bus:
                st = viewer._event_bus.get_last("multimedia.openauto_status")
                if st:
                    status = st[0]
            return jsonify({
                "auto_restart": auto_restart,
                "timeout": timeout,
                "status": status,
            })

        @app.route("/api/aa/config", methods=["POST"])
        def aa_config_set():
            """Update Android Auto settings (auto-restart toggle)."""
            data = request.get_json(silent=True) or {}
            if "auto_restart" in data:
                enabled = bool(data["auto_restart"])
                if viewer._config:
                    viewer._config.set("multimedia.aa_auto_restart", enabled)
                    _save_config(viewer._config, "aa auto_restart")
                openauto = _get_openauto()
                if openauto:
                    openauto.auto_restart_enabled = enabled
                elif viewer._event_bus:
                    viewer._event_bus.publish("multimedia.aa_auto_restart", enabled)
                return jsonify({"ok": True, "auto_restart": enabled})
            return jsonify({"error": "missing auto_restart"}), 400

        @app.route("/api/kiosk/restart", methods=["POST"])
        def api_kiosk_restart():
            """Restart the kiosk UI and display processes.

            On baremetal (systemd): restarts bcm-kiosk or kills chromium so xinitrc
            respawns it fresh, and notifies the UI.
            """
            log.info("Kiosk restart requested via API")
            data = request.get_json(silent=True) or {}
            scope = data.get("scope", "kiosk")

            def _perform_restart():
                time.sleep(0.5)
                # 1. Try systemd service restart for bcm-kiosk if active
                try:
                    rc = subprocess.run(
                        ["systemctl", "is-active", "--quiet", "bcm-kiosk.service"],
                        timeout=3
                    ).returncode
                    if rc == 0:
                        subprocess.run(["systemctl", "restart", "bcm-kiosk.service"], timeout=5)
                        log.info("Restarted bcm-kiosk.service via systemctl")
                        return
                except Exception as e:
                    log.debug("systemctl bcm-kiosk check failed: %s", e)

                # 2. On x86 setup where bcm-kiosk is masked and Chromium runs via xinitrc:
                # Killing chromium causes xinitrc to finish wait and relaunch clean Chromium.
                try:
                    subprocess.run(["pkill", "-f", "chromium"], timeout=3)
                    log.info("Sent pkill to chromium processes for kiosk relaunch")
                except Exception as e:
                    log.debug("pkill chromium failed: %s", e)

                # 3. If scope is 'system' or 'bcm', also restart bcm-headunit service
                if scope in ("system", "all", "bcm"):
                    try:
                        subprocess.run(["systemctl", "restart", "bcm-headunit.service"], timeout=5)
                    except Exception as e:
                        log.debug("systemctl bcm-headunit restart failed: %s", e)

            threading.Thread(target=_perform_restart, daemon=True, name="kiosk-restart-worker").start()
            return jsonify({"ok": True, "message": "kiosk restarting"})

        @app.route("/api/system/reboot", methods=["POST"])
        def api_system_reboot():
            """Reboot the entire baremetal computer (host OS).

            Gracefully notifies power.shutting_down (sync disk, flush configs),
            then issues a system reboot command.
            """
            log.warning("System reboot requested via API")
            if viewer._event_bus:
                try:
                    viewer._event_bus.publish("power.shutting_down", True)
                except Exception as e:
                    log.warning("Failed to publish power.shutting_down: %s", e)

            def _perform_reboot():
                time.sleep(1.2)
                commands = [
                    ["systemctl", "reboot"],
                    ["sudo", "systemctl", "reboot"],
                    ["reboot"],
                    ["sudo", "reboot"],
                ]
                for cmd in commands:
                    try:
                        log.info("Executing system reboot command: %s", " ".join(cmd))
                        res = subprocess.run(cmd, timeout=8)
                        if res.returncode == 0:
                            return
                    except Exception as e:
                        log.warning("Command %s failed: %s", cmd, e)

            threading.Thread(target=_perform_reboot, daemon=True, name="system-reboot-worker").start()
            return jsonify({"ok": True, "message": "system reboot initiated"})

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
            # pair() runs bluetoothctl pair + a post-pair connect, which can
            # block for tens of seconds. Never run it inline — the kiosk Flask
            # server is effectively single-threaded, so a blocking handler
            # freezes the whole UI. Fire-and-forget; the UI learns the result
            # from the bt.connected/bt.disconnected events + /bt/connected poll.
            threading.Thread(
                target=bt.pair, args=(address,),
                daemon=True, name=f"bt-http-pair-{address}",
            ).start()
            return jsonify({"started": True, "address": address}), 202

        @app.route("/bt/connect/<address>", methods=["POST"])
        def bt_connect(address):
            bt = viewer._bt_manager
            if not bt:
                return jsonify({"error": "BT not available"}), 503
            # connect() can block ~40s (connect + verify + back-off). Run it on
            # a daemon thread so the request returns immediately and the UI
            # stays responsive; the real outcome arrives via the event bus.
            threading.Thread(
                target=bt.connect, args=(address,),
                daemon=True, name=f"bt-http-connect-{address}",
            ).start()
            return jsonify({"started": True, "address": address}), 202

        @app.route("/bt/disconnect", methods=["POST"])
        def bt_disconnect():
            bt = viewer._bt_manager
            if not bt:
                return jsonify({"error": "BT not available"}), 503
            threading.Thread(
                target=bt.disconnect,
                daemon=True, name="bt-http-disconnect",
            ).start()
            return jsonify({"started": True}), 202

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
                # Internet Share is only viable on a second radio (USB WiFi
                # dongle); the Settings row is greyed out when this is False
                # because a second AP VIF on the MT7921 collapses AA P2P-GO.
                "internet_share_available": bool(
                    viewer._wifi_ap.second_radio_available)
                    if viewer._wifi_ap else False,
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
            # The change is live either way; report honestly whether it
            # survives a restart. A password provided by /etc/bcm/bcm.env is
            # never written to local.yaml (env wins on the next start), and
            # with --no-local-config nothing is written at all.
            persisted = _save_config(cfg, "wifi")
            env_managed = _unpersisted_wifi_secrets(cfg)

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
            return jsonify({"ok": True, "restart_required": True,
                            "persisted": persisted, "env_managed": env_managed})

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
            # Browser input -> log, event bus and oFono's Dial(): only a plain
            # dial string passes (separators from phonebook entries dropped,
            # then 1-32 of 0-9 + * #). Anything else is a 400, never echoed raw.
            from src.multimedia.bluetooth import normalize_dial_number
            data = request.get_json(silent=True)
            raw = data.get("number", "") if isinstance(data, dict) else ""
            number = normalize_dial_number(raw)
            if not number:
                return jsonify({"ok": False, "error": "invalid number"}), 400
            if viewer._event_bus:
                viewer._event_bus.publish("bt.cmd.dial", number)
            return jsonify({"ok": True, "number": number})

        @app.route("/api/phone_tether/retry", methods=["POST"])
        def api_phone_tether_retry():
            """"Ponów" in Settings: retry the phone's Bluetooth internet now.

            Takes no arguments (the body is ignored — nothing from the
            browser reaches nmcli) and only publishes
            net.phone_tether.cmd.retry; src/network/phone_tether.py drops its
            backoff. At most one per _TETHER_RETRY_MIN_INTERVAL_S, as each
            one can cost a `connection up` of up to 30 s.
            """
            if not viewer._event_bus:
                return jsonify({"ok": False, "error": "event bus unavailable"}), 503
            now = time.monotonic()
            with viewer._tether_retry_lock:
                last = viewer._tether_retry_last
                if last is not None and now - last < _TETHER_RETRY_MIN_INTERVAL_S:
                    wait = int(_TETHER_RETRY_MIN_INTERVAL_S - (now - last)) + 1
                    res = jsonify({"ok": False, "error": "too many requests",
                                   "retry_after": wait})
                    res.headers["Retry-After"] = str(wait)
                    return res, 429
                viewer._tether_retry_last = now
            viewer._event_bus.publish(_TETHER_RETRY_TOPIC, True)
            return jsonify({"ok": True})

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
                if s:
                    state = s[0] or "idle"
                i = viewer._event_bus.get_last("bt.call_info")
                if i:
                    info = i[0] or {}
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
            data = request.get_json(silent=True)
            if not isinstance(data, dict):
                data = {}
            lat = data.get("lat")
            lon = data.get("lon")
            city = data.get("city", "")
            if lat is None or lon is None:
                return jsonify({"error": "missing lat/lon"}), 400
            # The coordinates end up in the OpenWeatherMap URL.
            coords = valid_coords(lat, lon)
            if coords is None:
                return jsonify({"error": "lat/lon must be numbers in range"}), 400
            if viewer._event_bus:
                viewer._event_bus.publish("weather.search_location", {
                    "lat": coords[0], "lon": coords[1],
                    "city": city[:100] if isinstance(city, str) else "",
                })
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
            """Read DTC error codes from ECU.

            Publishes obd.dtc.read_request; the EDC15C7Reader services
            it inside its polling thread and answers with obd.dtc.codes.
            Wait (up to 3 s) for an answer FRESHER than our request —
            get_last alone would return the previous read.
            """
            bus = viewer._event_bus
            if not bus:
                return jsonify({"codes": [], "error": "no bus"})
            requested_at = time.time()      # compared with bus timestamps
            bus.publish("obd.dtc.read_request", True)
            # The wait itself on the monotonic clock: a wall-clock jump
            # (bcm-timesync) must not keep this request thread spinning.
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline:
                result = bus.get_last("obd.dtc.codes")
                if result and result[1] >= requested_at:
                    codes = result[0]
                    if codes is None:
                        return jsonify({"codes": [],
                                        "error": "ECU communication failed"})
                    return jsonify({"codes": codes})
                time.sleep(0.05)
            # Timeout — OBD module disabled or ECU not answering
            stale = bus.get_last("obd.dtc.codes")
            return jsonify({"codes": (stale[0] if stale and stale[0] else []),
                            "error": "timeout"})

        @app.route("/api/dtc/clear", methods=["POST"])
        def api_dtc_clear():
            """Clear DTC error codes from ECU (confirmed by re-read)."""
            bus = viewer._event_bus
            if not bus:
                return jsonify({"ok": False, "error": "no bus"})
            requested_at = time.time()      # compared with bus timestamps
            bus.publish("obd.dtc.clear_request", True)
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline:
                result = bus.get_last("obd.dtc.cleared")
                if result and result[1] >= requested_at:
                    return jsonify({"ok": bool(result[0])})
                time.sleep(0.05)
            return jsonify({"ok": False, "error": "timeout"})

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
            origin = request.headers.get("Origin")
            if not _ws_origin_allowed(origin, request.host):
                # Returning closes the socket before a single message is read.
                log.debug("Rejected /ws/input from foreign Origin %r (host %r)",
                          origin, request.host)
                return
            viewer._serve_input_ws(ws)

        return app
