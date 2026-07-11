# =====================================================================
# LEGACY — KOD NIEUŻYWANY W PRODUKCJI. Nie importowany przez main.py.
# Powód i kontekst: legacy/README.md oraz AUDYT_I_PLAN.md.
# =====================================================================
"""Remote vehicle status API — query via LTE.

Exposes a simple REST endpoint for remote vehicle status queries.
Protected by API key. Returns: location, temperature, lock state.
"""

import threading
from src.core.logger import get_logger

log = get_logger("remote_status")

try:
    from flask import Flask, jsonify, request
    HAS_FLASK = True
except ImportError:
    HAS_FLASK = False


class RemoteStatusServer:
    """Simple REST API for remote vehicle status over LTE."""

    def __init__(self, config, event_bus, port=5004):
        self.config = config
        self.bus = event_bus
        self.port = port
        self._api_key = config.get("remote_status.api_key", "")
        self._thread = None

    def start(self):
        if not HAS_FLASK:
            return
        if not self._api_key:
            log.warning("Remote status API key not configured — disabled")
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        log.info("Remote status API started on port %d", self.port)

    def _run(self):
        app = Flask(__name__)
        server = self

        @app.route("/api/remote/status")
        def status():
            key = request.args.get("key", "")
            if key != server._api_key:
                return jsonify({"error": "unauthorized"}), 401

            bus = server.bus

            def v(topic, default=None):
                r = bus.get_last(topic)
                return r[0] if r is not None else default

            pos = v("gps.position", {})
            return jsonify({
                "lat": pos.get("lat") if isinstance(pos, dict) else None,
                "lon": pos.get("lon") if isinstance(pos, dict) else None,
                "speed": v("obd.speed", 0),
                "ext_temp": v("env.temperature"),
                "coolant_temp": v("obd.coolant_temp"),
                "fuel_level": v("obd.fuel_level"),
                "locked": v("vehicle.locked"),
                "battery_voltage": v("obd.battery_voltage"),
                "lte_signal": v("lte.signal", 0),
            })

        app.run(host="0.0.0.0", port=self.port, debug=False, use_reloader=False)


def start_remote_status(config, event_bus, hal=None, **kwargs):
    server = RemoteStatusServer(config, event_bus)
    server.start()
    return server
