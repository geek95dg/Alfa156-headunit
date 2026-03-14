"""Android Auto second display simulation for VMware/x86 testing.

Opens a second PyGame window (1024x600) simulating the 7" multimedia
screen that normally runs OpenAuto Pro on the Orange Pi.

VMware Workstation supports multiple displays — this window can be
moved to the second virtual monitor for a realistic dual-screen setup.
"""

import os
import time
import threading
import pygame

from src.core.event_bus import EventBus
from src.core.config import BCMConfig
from src.core.logger import get_logger

log = get_logger("multimedia.aa_display")


class AADisplaySimulator:
    """Simulates the 7\" Android Auto display on x86/VMware.

    Shows connection status, simulated AA interface elements,
    and responds to Bluetooth/multimedia events from the event bus.
    """

    def __init__(self, config: BCMConfig, event_bus: EventBus) -> None:
        self.config = config
        self.bus = event_bus
        self._running = False
        self._thread: threading.Thread | None = None

        # Display config
        self.width = config.get("display.multimedia.width", 1024)
        self.height = config.get("display.multimedia.height", 600)

        # State
        self._aa_connected = False
        self._aa_status = "Waiting for device..."
        self._bt_connected = False
        self._bt_device = "---"
        self._audio_source = "---"
        self._phone_active = False

        # Subscribe to events
        self.bus.subscribe("multimedia.openauto_status", self._on_aa_status)
        self.bus.subscribe("bt.connected", self._on_bt_connected)
        self.bus.subscribe("bt.disconnected", self._on_bt_disconnected)
        self.bus.subscribe("audio.source_changed", self._on_source_changed)
        self.bus.subscribe("bt.hfp_active", self._on_phone)

    def _on_aa_status(self, topic, value, ts):
        self._aa_status = str(value)
        self._aa_connected = (value == "running")

    def _on_bt_connected(self, topic, value, ts):
        self._bt_connected = True
        if isinstance(value, dict):
            self._bt_device = value.get("name", "Unknown")
        else:
            self._bt_device = str(value)

    def _on_bt_disconnected(self, topic, value, ts):
        self._bt_connected = False
        self._bt_device = "---"

    def _on_source_changed(self, topic, value, ts):
        self._audio_source = str(value)

    def _on_phone(self, topic, value, ts):
        self._phone_active = bool(value)

    def start(self) -> None:
        """Start the AA display in a separate thread."""
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        log.info("Android Auto display simulator started (%dx%d)",
                 self.width, self.height)

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)

    def _run(self) -> None:
        """Render loop for the AA display window."""
        # Set window position offset for second monitor
        os.environ["SDL_VIDEO_WINDOW_POS"] = "850,100"

        # Use a separate pygame display (we need pygame.display for main dashboard,
        # so this uses a different approach with a separate surface + window)
        try:
            import ctypes
            # On some systems we need to init video separately
        except ImportError:
            pass

        # Create a separate window using SDL
        # Note: PyGame only supports one display window per process.
        # For true dual-display, we use a Flask web viewer as the second screen.
        self._run_web_viewer()

    def _run_web_viewer(self) -> None:
        """Run the AA display as a web page (works with VMware dual display)."""
        try:
            from flask import Flask, render_template_string, Response
        except ImportError:
            log.warning("Flask not available — AA display simulation disabled")
            return

        app = Flask(__name__)
        app.logger.disabled = True

        # Suppress Flask/werkzeug logs
        import logging
        werkzeug_log = logging.getLogger("werkzeug")
        werkzeug_log.setLevel(logging.ERROR)

        @app.route("/")
        def index():
            return render_template_string(AA_HTML_TEMPLATE,
                                          width=self.width, height=self.height)

        @app.route("/status")
        def status():
            import json
            return Response(json.dumps({
                "aa_connected": self._aa_connected,
                "aa_status": self._aa_status,
                "bt_connected": self._bt_connected,
                "bt_device": self._bt_device,
                "audio_source": self._audio_source,
                "phone_active": self._phone_active,
                "time": time.strftime("%H:%M"),
            }), mimetype="application/json")

        log.info("AA Display web viewer at http://localhost:5001")
        log.info("Open in browser on second VMware display for dual-screen simulation")

        try:
            app.run(host="0.0.0.0", port=5001, debug=False, use_reloader=False)
        except Exception as e:
            log.error("AA display web server error: %s", e)


AA_HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Android Auto — BCM v7 Multimedia Display</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    background: #111;
    color: #eee;
    font-family: 'Segoe UI', 'Roboto', sans-serif;
    width: {{ width }}px;
    height: {{ height }}px;
    overflow: hidden;
    display: flex;
    flex-direction: column;
}
.header {
    background: #1a1a2e;
    padding: 12px 20px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 2px solid #333;
}
.header .title {
    font-size: 18px;
    font-weight: 600;
    color: #4CAF50;
}
.header .clock {
    font-size: 24px;
    font-weight: 300;
    color: #ccc;
}
.main {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 20px;
}
.aa-logo {
    width: 120px;
    height: 120px;
    border-radius: 50%;
    background: linear-gradient(135deg, #1a73e8, #4285f4);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 48px;
    box-shadow: 0 0 40px rgba(66, 133, 244, 0.3);
}
.aa-logo.connected {
    background: linear-gradient(135deg, #0d47a1, #1565c0);
    box-shadow: 0 0 60px rgba(21, 101, 192, 0.5);
}
.status {
    font-size: 22px;
    color: #888;
    text-align: center;
}
.status.connected { color: #4CAF50; }
.status.error { color: #f44336; }
.info-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
    padding: 20px;
    max-width: 500px;
}
.info-item {
    background: #1a1a2e;
    padding: 12px 16px;
    border-radius: 8px;
    border: 1px solid #333;
}
.info-item .label { font-size: 11px; color: #666; text-transform: uppercase; }
.info-item .value { font-size: 16px; color: #ccc; margin-top: 4px; }
.info-item .value.active { color: #4CAF50; }
.info-item .value.warning { color: #ff9800; }
.footer {
    background: #1a1a2e;
    padding: 10px 20px;
    display: flex;
    justify-content: center;
    gap: 40px;
    border-top: 1px solid #333;
}
.footer-btn {
    width: 44px;
    height: 44px;
    border-radius: 50%;
    background: #2a2a3e;
    border: 1px solid #444;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 20px;
    cursor: pointer;
    color: #aaa;
}
.footer-btn:hover { background: #3a3a4e; color: #fff; }
.phone-overlay {
    display: none;
    position: fixed;
    top: 0; left: 0;
    width: 100%; height: 100%;
    background: rgba(0,0,0,0.85);
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 20px;
    z-index: 10;
}
.phone-overlay.active { display: flex; }
.phone-icon { font-size: 64px; }
.phone-text { font-size: 24px; color: #4CAF50; }
</style>
</head>
<body>
<div class="header">
    <div class="title">Android Auto</div>
    <div class="clock" id="clock">--:--</div>
</div>

<div class="main">
    <div class="aa-logo" id="aa-logo">A</div>
    <div class="status" id="aa-status">Waiting for device...</div>

    <div class="info-grid">
        <div class="info-item">
            <div class="label">Connection</div>
            <div class="value" id="aa-conn">Disconnected</div>
        </div>
        <div class="info-item">
            <div class="label">Bluetooth</div>
            <div class="value" id="bt-status">---</div>
        </div>
        <div class="info-item">
            <div class="label">Audio Source</div>
            <div class="value" id="audio-src">---</div>
        </div>
        <div class="info-item">
            <div class="label">Phone</div>
            <div class="value" id="phone-status">Idle</div>
        </div>
    </div>
</div>

<div class="footer">
    <div class="footer-btn" title="Home">&#8962;</div>
    <div class="footer-btn" title="Phone">&#9742;</div>
    <div class="footer-btn" title="Music">&#9835;</div>
    <div class="footer-btn" title="Navigation">&#9737;</div>
    <div class="footer-btn" title="Voice">&#9834;</div>
</div>

<div class="phone-overlay" id="phone-overlay">
    <div class="phone-icon">&#9742;</div>
    <div class="phone-text">Call in progress...</div>
</div>

<script>
function update() {
    fetch('/status')
        .then(r => r.json())
        .then(d => {
            document.getElementById('clock').textContent = d.time;
            document.getElementById('aa-status').textContent = d.aa_status;
            document.getElementById('aa-status').className =
                'status' + (d.aa_connected ? ' connected' : '');

            const logo = document.getElementById('aa-logo');
            logo.className = 'aa-logo' + (d.aa_connected ? ' connected' : '');

            document.getElementById('aa-conn').textContent =
                d.aa_connected ? 'Connected' : 'Waiting...';
            document.getElementById('aa-conn').className =
                'value' + (d.aa_connected ? ' active' : '');

            document.getElementById('bt-status').textContent =
                d.bt_connected ? d.bt_device : '---';
            document.getElementById('bt-status').className =
                'value' + (d.bt_connected ? ' active' : '');

            document.getElementById('audio-src').textContent = d.audio_source;
            document.getElementById('phone-status').textContent =
                d.phone_active ? 'Active' : 'Idle';
            document.getElementById('phone-status').className =
                'value' + (d.phone_active ? ' warning' : '');

            document.getElementById('phone-overlay').className =
                'phone-overlay' + (d.phone_active ? ' active' : '');
        })
        .catch(() => {});
}
setInterval(update, 500);
update();
</script>
</body>
</html>"""


def start_aa_display(config: BCMConfig, event_bus: EventBus) -> AADisplaySimulator:
    """Start the AA display simulator. Returns the controller."""
    display = AADisplaySimulator(config, event_bus)
    display.start()
    return display
