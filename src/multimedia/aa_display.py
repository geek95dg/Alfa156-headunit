"""Android Auto second display + Bluetooth management web UI.

Runs a Flask web server (port 5001) providing:
  - Android Auto live video stream from Xvfb (MJPEG)
  - Full Bluetooth device management (scan, pair, connect, remove)
  - Touch-friendly responsive UI for use on second screen

VMware Workstation supports multiple displays — open this in a browser
on the second virtual monitor for a realistic dual-screen setup.
"""

import io
import time
import subprocess
import threading
from typing import Any, Optional

from src.core.event_bus import EventBus
from src.core.config import BCMConfig
from src.core.logger import get_logger

log = get_logger("multimedia.aa_display")


class AADisplaySimulator:
    """Web-based second display for AA status and Bluetooth management."""

    def __init__(self, config: BCMConfig, event_bus: EventBus,
                 bt_manager: Any = None) -> None:
        self.config = config
        self.bus = event_bus
        self.bt = bt_manager
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
        self._aa_connected = value in ("running", "connected")

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
        """Start the web server in a daemon thread."""
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        log.info("AA display thread started (%dx%d)", self.width, self.height)

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)

    @staticmethod
    def _get_local_ips() -> list[str]:
        """Get non-loopback IPv4 addresses for this machine."""
        ips = []
        try:
            import socket
            for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                ip = info[4][0]
                if not ip.startswith("127."):
                    ips.append(ip)
        except Exception:
            pass
        if not ips:
            try:
                import socket
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                ips.append(s.getsockname()[0])
                s.close()
            except Exception:
                pass
        return list(dict.fromkeys(ips))

    def _run(self) -> None:
        """Start Flask web server."""
        try:
            from flask import Flask, render_template_string, Response, request
            import json
        except ImportError:
            log.error("Flask not available — AA display disabled. "
                      "Install: pip install flask")
            return

        app = Flask(__name__)
        app.logger.disabled = True

        import logging as _logging
        _logging.getLogger("werkzeug").setLevel(_logging.ERROR)

        # --- AA status API ---

        @app.route("/")
        def index():
            return render_template_string(MAIN_HTML,
                                          width=self.width, height=self.height)

        @app.route("/status")
        def status():
            data = {
                "aa_connected": self._aa_connected,
                "aa_status": self._aa_status,
                "bt_connected": self._bt_connected,
                "bt_device": self._bt_device,
                "audio_source": self._audio_source,
                "phone_active": self._phone_active,
                "time": time.strftime("%H:%M"),
            }
            return Response(json.dumps(data), mimetype="application/json")

        # --- AA video stream (MJPEG from Xvfb via ffmpeg) ---

        def _mjpeg_generator():
            """Stream MJPEG frames from Xvfb using ffmpeg."""
            try:
                proc = subprocess.Popen(
                    ["ffmpeg", "-f", "x11grab", "-framerate", "15",
                     "-video_size",
                     f"{self.width}x{self.height}",
                     "-i", ":99",
                     "-f", "mjpeg", "-q:v", "5",
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
            return Response(_mjpeg_generator(),
                            mimetype="multipart/x-mixed-replace; boundary=frame")

        # --- Bluetooth management API ---

        @app.route("/bt/status")
        def bt_status():
            if not self.bt:
                return Response(json.dumps({"error": "BT manager not available"}),
                                status=503, mimetype="application/json")
            ctrl = self.bt.get_controller_info()
            ctrl["connected"] = self.bt.connected
            ctrl["connected_device"] = self.bt.connected_device
            ctrl["scanning"] = self.bt.scanning
            ctrl["a2dp_active"] = self.bt.a2dp_active
            ctrl["hfp_active"] = self.bt.hfp_active
            return Response(json.dumps(ctrl), mimetype="application/json")

        @app.route("/bt/devices")
        def bt_devices():
            if not self.bt:
                return Response(json.dumps({"paired": [], "discovered": []}),
                                mimetype="application/json")
            paired = self.bt.get_paired_devices()
            # Add connection status to each paired device
            for dev in paired:
                info = self.bt.get_device_info(dev["address"])
                dev["connected"] = info.get("connected", False)
            discovered = self.bt.discovered_devices
            return Response(json.dumps({"paired": paired, "discovered": discovered}),
                            mimetype="application/json")

        @app.route("/bt/scan", methods=["POST"])
        def bt_scan():
            if not self.bt:
                return Response(json.dumps({"error": "BT not available"}),
                                status=503, mimetype="application/json")
            duration = request.json.get("duration", 15) if request.is_json else 15
            ok = self.bt.start_scan(duration=duration)
            return Response(json.dumps({"started": ok, "scanning": self.bt.scanning}),
                            mimetype="application/json")

        @app.route("/bt/scan/stop", methods=["POST"])
        def bt_scan_stop():
            if not self.bt:
                return Response(json.dumps({"error": "BT not available"}),
                                status=503, mimetype="application/json")
            self.bt.stop_scan()
            return Response(json.dumps({"scanning": False}),
                            mimetype="application/json")

        @app.route("/bt/pair/<address>", methods=["POST"])
        def bt_pair(address):
            if not self.bt:
                return Response(json.dumps({"error": "BT not available"}),
                                status=503, mimetype="application/json")
            ok = self.bt.pair(address)
            return Response(json.dumps({"success": ok, "address": address}),
                            mimetype="application/json")

        @app.route("/bt/connect/<address>", methods=["POST"])
        def bt_connect(address):
            if not self.bt:
                return Response(json.dumps({"error": "BT not available"}),
                                status=503, mimetype="application/json")
            ok = self.bt.connect(address)
            return Response(json.dumps({"success": ok, "address": address}),
                            mimetype="application/json")

        @app.route("/bt/disconnect", methods=["POST"])
        def bt_disconnect():
            if not self.bt:
                return Response(json.dumps({"error": "BT not available"}),
                                status=503, mimetype="application/json")
            self.bt.disconnect()
            return Response(json.dumps({"success": True}),
                            mimetype="application/json")

        @app.route("/bt/remove/<address>", methods=["POST"])
        def bt_remove(address):
            if not self.bt:
                return Response(json.dumps({"error": "BT not available"}),
                                status=503, mimetype="application/json")
            ok = self.bt.remove(address)
            return Response(json.dumps({"success": ok, "address": address}),
                            mimetype="application/json")

        @app.route("/bt/discoverable", methods=["POST"])
        def bt_discoverable():
            if not self.bt:
                return Response(json.dumps({"error": "BT not available"}),
                                status=503, mimetype="application/json")
            timeout = request.json.get("timeout", 120) if request.is_json else 120
            ok = self.bt.enable_discoverable(timeout=timeout)
            return Response(json.dumps({"success": ok}),
                            mimetype="application/json")

        @app.route("/bt/connected")
        def bt_connected():
            """Get all currently connected Bluetooth devices."""
            if not self.bt:
                return Response(json.dumps({"connected": []}),
                                mimetype="application/json")
            connected = self.bt.get_connected_devices()
            return Response(json.dumps({"connected": connected}),
                            mimetype="application/json")

        @app.route("/bt/pairing")
        def bt_pairing_status():
            """Check if there's a pending pairing confirmation request."""
            from src.multimedia.bluetooth import get_pending_pairing
            req = get_pending_pairing()
            return Response(json.dumps({"pending": req is not None,
                                        "request": req}),
                            mimetype="application/json")

        @app.route("/bt/pairing/confirm", methods=["POST"])
        def bt_pairing_confirm():
            """Accept or reject the pending pairing request."""
            from src.multimedia.bluetooth import confirm_pairing
            accept = True
            if request.is_json:
                accept = request.json.get("accept", True)
            ok = confirm_pairing(accept)
            return Response(json.dumps({"success": ok}),
                            mimetype="application/json")

        # Show network IPs
        local_ips = self._get_local_ips()
        log.info("AA Display web viewer starting on port 5001")
        log.info("  Local:   http://localhost:5001")
        for ip in local_ips:
            log.info("  Network: http://%s:5001", ip)

        try:
            app.run(host="0.0.0.0", port=5001, debug=False, use_reloader=False)
        except Exception:
            log.exception("AA display web server failed to start")


# ---------------------------------------------------------------------------
# HTML template — combined AA display + Bluetooth management
# ---------------------------------------------------------------------------

MAIN_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BCM v7 — Multimedia Display</title>
<style>
:root {
    --bg: #0e0e14;
    --card: #16162a;
    --border: #2a2a40;
    --text: #ddd;
    --muted: #666;
    --accent: #4a8cff;
    --green: #4caf50;
    --orange: #ff9800;
    --red: #f44336;
    --radius: 12px;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    background: var(--bg);
    color: var(--text);
    font-family: 'Segoe UI', 'Roboto', 'Helvetica Neue', sans-serif;
    min-height: 100vh;
    overflow-x: hidden;
    -webkit-tap-highlight-color: transparent;
}

/* Tab navigation */
.tabs {
    display: flex;
    background: var(--card);
    border-bottom: 2px solid var(--border);
    position: sticky;
    top: 0;
    z-index: 20;
}
.tab {
    flex: 1;
    padding: 14px;
    text-align: center;
    font-size: 15px;
    font-weight: 600;
    color: var(--muted);
    cursor: pointer;
    border-bottom: 3px solid transparent;
    transition: all 0.2s;
    user-select: none;
}
.tab:hover { color: var(--text); }
.tab.active {
    color: var(--accent);
    border-bottom-color: var(--accent);
}

/* Pages */
.page { display: none; padding: 16px; }
.page.active { display: block; }

/* Cards */
.card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 16px;
    margin-bottom: 12px;
}
.card-title {
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: var(--muted);
    margin-bottom: 10px;
}

/* AA display */
.aa-hero {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 32px 0;
    gap: 16px;
}
.aa-icon {
    width: 100px;
    height: 100px;
    border-radius: 50%;
    background: linear-gradient(135deg, #1a73e8, #4285f4);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 42px;
    box-shadow: 0 0 40px rgba(66, 133, 244, 0.25);
    transition: all 0.3s;
}
.aa-icon.connected {
    background: linear-gradient(135deg, #0d47a1, #1565c0);
    box-shadow: 0 0 60px rgba(21, 101, 192, 0.5);
}
.aa-status-text {
    font-size: 20px;
    color: var(--muted);
}
.aa-status-text.connected { color: var(--green); }
.info-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
}
.info-cell {
    background: rgba(255,255,255,0.03);
    border-radius: 8px;
    padding: 12px;
}
.info-cell .lbl { font-size: 11px; color: var(--muted); text-transform: uppercase; }
.info-cell .val { font-size: 15px; margin-top: 4px; }
.info-cell .val.on { color: var(--green); }
.info-cell .val.warn { color: var(--orange); }

/* BT page */
.bt-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;
}
.bt-badge {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 20px;
    font-size: 11px;
    font-weight: 600;
}
.bt-badge.on { background: rgba(76,175,80,0.15); color: var(--green); }
.bt-badge.off { background: rgba(244,67,54,0.15); color: var(--red); }
.bt-badge.scanning { background: rgba(74,140,255,0.15); color: var(--accent); }

/* Buttons */
.btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    padding: 10px 18px;
    border: none;
    border-radius: 8px;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.15s;
    color: #fff;
    min-height: 44px;
    user-select: none;
}
.btn:active { transform: scale(0.97); }
.btn-primary { background: var(--accent); }
.btn-primary:hover { background: #5a9aff; }
.btn-success { background: var(--green); }
.btn-success:hover { background: #5cc060; }
.btn-danger { background: var(--red); }
.btn-danger:hover { background: #f55a50; }
.btn-outline {
    background: transparent;
    border: 1px solid var(--border);
    color: var(--text);
}
.btn-outline:hover { background: rgba(255,255,255,0.05); }
.btn-sm { padding: 6px 12px; font-size: 12px; min-height: 34px; }
.btn-group { display: flex; gap: 8px; flex-wrap: wrap; }

/* Device list */
.device-list { list-style: none; }
.device-item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px;
    border-bottom: 1px solid var(--border);
    gap: 10px;
}
.device-item:last-child { border-bottom: none; }
.dev-info { flex: 1; min-width: 0; }
.dev-name {
    font-size: 14px;
    font-weight: 500;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.dev-addr { font-size: 11px; color: var(--muted); font-family: monospace; }
.dev-status { font-size: 11px; margin-top: 2px; }
.dev-status.connected { color: var(--green); }
.dev-actions { display: flex; gap: 6px; flex-shrink: 0; }

/* Loading spinner */
.spinner {
    display: inline-block;
    width: 16px;
    height: 16px;
    border: 2px solid rgba(255,255,255,0.2);
    border-top-color: #fff;
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

.empty-msg {
    text-align: center;
    color: var(--muted);
    padding: 20px;
    font-size: 14px;
}

/* Toast */
.toast {
    position: fixed;
    bottom: 20px;
    left: 50%;
    transform: translateX(-50%) translateY(100px);
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 10px 20px;
    font-size: 14px;
    z-index: 100;
    transition: transform 0.3s;
    max-width: 90%;
}
.toast.show { transform: translateX(-50%) translateY(0); }
.toast.error { border-color: var(--red); color: var(--red); }
.toast.success { border-color: var(--green); color: var(--green); }

/* Pairing modal */
.modal-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,0.7);
    display: none;
    justify-content: center;
    align-items: center;
    z-index: 200;
}
.modal-overlay.show { display: flex; }
.modal {
    background: var(--card);
    border: 2px solid var(--accent);
    border-radius: 16px;
    padding: 28px;
    max-width: 400px;
    width: 90%;
    text-align: center;
    box-shadow: 0 0 60px rgba(74,140,255,0.3);
    animation: modalIn 0.3s ease;
}
@keyframes modalIn {
    from { transform: scale(0.9); opacity: 0; }
    to { transform: scale(1); opacity: 1; }
}
.modal-icon {
    font-size: 48px;
    margin-bottom: 12px;
}
.modal-title {
    font-size: 18px;
    font-weight: 700;
    margin-bottom: 8px;
}
.modal-device {
    font-size: 13px;
    color: var(--muted);
    margin-bottom: 16px;
}
.modal-passkey {
    font-size: 36px;
    font-weight: 700;
    letter-spacing: 8px;
    color: var(--accent);
    font-family: monospace;
    background: rgba(74,140,255,0.1);
    border-radius: 12px;
    padding: 16px;
    margin-bottom: 8px;
}
.modal-hint {
    font-size: 12px;
    color: var(--muted);
    margin-bottom: 20px;
}
.modal-buttons {
    display: flex;
    gap: 12px;
    justify-content: center;
}
.modal-buttons .btn { min-width: 120px; font-size: 16px; padding: 14px 24px; }
</style>
</head>
<body>

<div class="tabs">
    <div class="tab active" data-page="aa">Android Auto</div>
    <div class="tab" data-page="bt">Bluetooth</div>
</div>

<!-- Android Auto page -->
<div class="page active" id="page-aa">
    <!-- Live AA stream (shown when connected) -->
    <div id="aa-stream-container" style="display:none; width:100%; text-align:center; background:#000;">
        <img id="aa-stream" src="" style="width:100%; max-height:calc(100vh - 60px); object-fit:contain;">
    </div>
    <!-- Status panel (shown when waiting) -->
    <div id="aa-status-panel">
        <div class="aa-hero">
            <div class="aa-icon" id="aa-icon">A</div>
            <div class="aa-status-text" id="aa-status-text">Waiting for device...</div>
        </div>
        <div class="card">
            <div class="info-grid">
                <div class="info-cell">
                    <div class="lbl">Connection</div>
                    <div class="val" id="aa-conn">Disconnected</div>
                </div>
                <div class="info-cell">
                    <div class="lbl">Bluetooth</div>
                    <div class="val" id="aa-bt">---</div>
                </div>
                <div class="info-cell">
                    <div class="lbl">Audio Source</div>
                    <div class="val" id="aa-audio">---</div>
                </div>
                <div class="info-cell">
                    <div class="lbl">Phone</div>
                    <div class="val" id="aa-phone">Idle</div>
                </div>
            </div>
        </div>
        <div class="card" style="text-align:center; color:var(--muted); font-size:13px">
            <span id="clock-display">--:--</span> &nbsp;|&nbsp; BCM v7 Multimedia Display
        </div>
    </div>
</div>

<!-- Bluetooth management page -->
<div class="page" id="page-bt">
    <!-- Controller status -->
    <div class="card">
        <div class="bt-header">
            <div class="card-title">Controller</div>
            <span class="bt-badge off" id="bt-power-badge">OFF</span>
        </div>
        <div style="font-size:13px; color:var(--muted)" id="bt-ctrl-info">Loading...</div>
        <div class="btn-group" style="margin-top:12px">
            <button class="btn btn-outline btn-sm" onclick="btDiscoverable()">
                Make Discoverable (2 min)
            </button>
        </div>
    </div>

    <!-- Connected devices -->
    <div class="card" id="bt-connected-card">
        <div class="bt-header">
            <div class="card-title">Connected Devices</div>
            <span class="bt-badge off" id="bt-conn-count">0</span>
        </div>
        <ul class="device-list" id="connected-list">
            <li class="empty-msg">No devices connected</li>
        </ul>
    </div>

    <!-- Scan section -->
    <div class="card">
        <div class="bt-header">
            <div class="card-title">Scan for Devices</div>
            <span class="bt-badge" id="bt-scan-badge" style="display:none">
                <span class="spinner"></span> Scanning
            </span>
        </div>
        <div class="btn-group" style="margin-bottom:12px">
            <button class="btn btn-primary btn-sm" id="btn-scan" onclick="btScan()">
                Scan Nearby
            </button>
            <button class="btn btn-outline btn-sm" id="btn-scan-stop"
                    onclick="btScanStop()" style="display:none">
                Stop Scan
            </button>
        </div>
        <ul class="device-list" id="discovered-list">
            <li class="empty-msg">Press "Scan Nearby" to find devices</li>
        </ul>
    </div>

    <!-- Paired devices -->
    <div class="card">
        <div class="card-title">Paired Devices</div>
        <ul class="device-list" id="paired-list">
            <li class="empty-msg">No paired devices</li>
        </ul>
    </div>
</div>

<!-- Pairing confirmation modal -->
<div class="modal-overlay" id="pairing-modal">
    <div class="modal">
        <div class="modal-icon">&#x1F4F1;</div>
        <div class="modal-title">Bluetooth Pairing Request</div>
        <div class="modal-device" id="pairing-device">Device requesting to pair...</div>
        <div class="modal-passkey" id="pairing-passkey">------</div>
        <div class="modal-hint">Confirm this code matches the one shown on your phone</div>
        <div class="modal-buttons">
            <button class="btn btn-danger" onclick="pairingRespond(false)">Reject</button>
            <button class="btn btn-success" onclick="pairingRespond(true)">Accept</button>
        </div>
    </div>
</div>

<div class="toast" id="toast"></div>

<script>
// Tab switching
document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
        tab.classList.add('active');
        document.getElementById('page-' + tab.dataset.page).classList.add('active');
        if (tab.dataset.page === 'bt') refreshBT();
    });
});

// Toast notification
function showToast(msg, type) {
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.className = 'toast ' + (type || '') + ' show';
    setTimeout(() => t.classList.remove('show'), 3000);
}

// --- AA status polling ---
let aaStreamActive = false;
function updateAA() {
    fetch('/status').then(r => r.json()).then(d => {
        document.getElementById('clock-display').textContent = d.time;
        const icon = document.getElementById('aa-icon');
        const st = document.getElementById('aa-status-text');
        const streamEl = document.getElementById('aa-stream-container');
        const panelEl = document.getElementById('aa-status-panel');
        const streamImg = document.getElementById('aa-stream');

        st.textContent = d.aa_status;
        st.className = 'aa-status-text' + (d.aa_connected ? ' connected' : '');
        icon.className = 'aa-icon' + (d.aa_connected ? ' connected' : '');

        // Toggle between live stream and status panel
        if (d.aa_connected && !aaStreamActive) {
            streamEl.style.display = 'block';
            panelEl.style.display = 'none';
            streamImg.src = '/aa/stream';
            aaStreamActive = true;
        } else if (!d.aa_connected && aaStreamActive) {
            streamEl.style.display = 'none';
            panelEl.style.display = '';
            streamImg.src = '';
            aaStreamActive = false;
        }

        const conn = document.getElementById('aa-conn');
        conn.textContent = d.aa_connected ? 'Connected' : 'Waiting...';
        conn.className = 'val' + (d.aa_connected ? ' on' : '');

        const bt = document.getElementById('aa-bt');
        bt.textContent = d.bt_connected ? d.bt_device : '---';
        bt.className = 'val' + (d.bt_connected ? ' on' : '');

        document.getElementById('aa-audio').textContent = d.audio_source;

        const ph = document.getElementById('aa-phone');
        ph.textContent = d.phone_active ? 'Active' : 'Idle';
        ph.className = 'val' + (d.phone_active ? ' warn' : '');
    }).catch(() => {});
}
setInterval(updateAA, 1000);
updateAA();

// --- BT management ---
function refreshBT() {
    // Controller status
    fetch('/bt/status').then(r => r.json()).then(d => {
        const badge = document.getElementById('bt-power-badge');
        if (d.error) {
            badge.textContent = 'N/A';
            badge.className = 'bt-badge off';
            document.getElementById('bt-ctrl-info').textContent = d.error;
            return;
        }
        badge.textContent = d.powered ? 'ON' : 'OFF';
        badge.className = 'bt-badge ' + (d.powered ? 'on' : 'off');
        document.getElementById('bt-ctrl-info').textContent =
            (d.name || '?') + '  (' + (d.address || '?') + ')' +
            (d.discoverable ? '  [Discoverable]' : '');

        // Scan badge
        const scanBadge = document.getElementById('bt-scan-badge');
        const btnScan = document.getElementById('btn-scan');
        const btnStop = document.getElementById('btn-scan-stop');
        if (d.scanning) {
            scanBadge.style.display = 'inline-flex';
            scanBadge.className = 'bt-badge scanning';
            btnScan.style.display = 'none';
            btnStop.style.display = '';
        } else {
            scanBadge.style.display = 'none';
            btnScan.style.display = '';
            btnStop.style.display = 'none';
        }
    }).catch(() => {});

    // Connected devices
    fetch('/bt/connected').then(r => r.json()).then(d => {
        renderConnected(d.connected || []);
    }).catch(() => {});

    // Device lists
    fetch('/bt/devices').then(r => r.json()).then(d => {
        renderPaired(d.paired || []);
        renderDiscovered(d.discovered || []);
    }).catch(() => {});
}

function renderConnected(devices) {
    const ul = document.getElementById('connected-list');
    const badge = document.getElementById('bt-conn-count');
    badge.textContent = devices.length;
    badge.className = 'bt-badge ' + (devices.length > 0 ? 'on' : 'off');
    if (!devices.length) {
        ul.innerHTML = '<li class="empty-msg">No devices connected</li>';
        return;
    }
    ul.innerHTML = devices.map(dev => `
        <li class="device-item">
            <div class="dev-info">
                <div class="dev-name">${esc(dev.name)}</div>
                <div class="dev-addr">${esc(dev.address)}</div>
                <div class="dev-status connected">
                    ${dev.a2dp ? 'A2DP ' : ''}${dev.hfp ? 'HFP ' : ''}${dev.trusted ? 'Trusted' : ''}
                </div>
            </div>
            <div class="dev-actions">
                <button class="btn btn-danger btn-sm" onclick="btDisconnect()">Disconnect</button>
            </div>
        </li>`).join('');
}

function renderPaired(devices) {
    const ul = document.getElementById('paired-list');
    if (!devices.length) {
        ul.innerHTML = '<li class="empty-msg">No paired devices</li>';
        return;
    }
    ul.innerHTML = devices.map(dev => `
        <li class="device-item">
            <div class="dev-info">
                <div class="dev-name">${esc(dev.name)}</div>
                <div class="dev-addr">${esc(dev.address)}</div>
                ${dev.connected ? '<div class="dev-status connected">Connected</div>' : ''}
            </div>
            <div class="dev-actions">
                ${dev.connected
                    ? `<button class="btn btn-danger btn-sm" onclick="btDisconnect()">Disconnect</button>`
                    : `<button class="btn btn-success btn-sm" onclick="btConnect('${dev.address}')">Connect</button>`}
                <button class="btn btn-outline btn-sm" onclick="btRemove('${dev.address}')">Remove</button>
            </div>
        </li>`).join('');
}

function renderDiscovered(devices) {
    const ul = document.getElementById('discovered-list');
    if (!devices.length) {
        if (document.getElementById('bt-scan-badge').style.display !== 'none') {
            ul.innerHTML = '<li class="empty-msg">Scanning...</li>';
        } else {
            ul.innerHTML = '<li class="empty-msg">Press "Scan Nearby" to find devices</li>';
        }
        return;
    }
    ul.innerHTML = devices.map(dev => `
        <li class="device-item">
            <div class="dev-info">
                <div class="dev-name">${esc(dev.name)}</div>
                <div class="dev-addr">${esc(dev.address)}</div>
            </div>
            <div class="dev-actions">
                <button class="btn btn-primary btn-sm" onclick="btPair('${dev.address}')">Pair</button>
            </div>
        </li>`).join('');
}

function esc(s) {
    const d = document.createElement('div');
    d.textContent = s || '';
    return d.innerHTML;
}

// --- BT actions ---
function btScan() {
    fetch('/bt/scan', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({duration: 15})})
        .then(r => r.json())
        .then(d => {
            if (d.started) showToast('Scanning for 15 seconds...', 'success');
            else showToast('Scan already running', '');
            refreshBT();
        })
        .catch(() => showToast('Scan failed', 'error'));
}

function btScanStop() {
    fetch('/bt/scan/stop', {method: 'POST'})
        .then(() => { showToast('Scan stopped', ''); refreshBT(); })
        .catch(() => showToast('Failed to stop scan', 'error'));
}

function btPair(addr) {
    showToast('Pairing with ' + addr + '...', '');
    fetch('/bt/pair/' + addr, {method: 'POST'})
        .then(r => r.json())
        .then(d => {
            showToast(d.success ? 'Paired successfully' : 'Pairing failed', d.success ? 'success' : 'error');
            refreshBT();
        })
        .catch(() => showToast('Pairing failed', 'error'));
}

function btConnect(addr) {
    showToast('Connecting to ' + addr + '...', '');
    fetch('/bt/connect/' + addr, {method: 'POST'})
        .then(r => r.json())
        .then(d => {
            showToast(d.success ? 'Connected' : 'Connection failed', d.success ? 'success' : 'error');
            refreshBT();
        })
        .catch(() => showToast('Connection failed', 'error'));
}

function btDisconnect() {
    fetch('/bt/disconnect', {method: 'POST'})
        .then(() => { showToast('Disconnected', 'success'); refreshBT(); })
        .catch(() => showToast('Disconnect failed', 'error'));
}

function btRemove(addr) {
    if (!confirm('Remove device ' + addr + '?')) return;
    fetch('/bt/remove/' + addr, {method: 'POST'})
        .then(r => r.json())
        .then(d => {
            showToast(d.success ? 'Device removed' : 'Remove failed', d.success ? 'success' : 'error');
            refreshBT();
        })
        .catch(() => showToast('Remove failed', 'error'));
}

function btDiscoverable() {
    fetch('/bt/discoverable', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({timeout: 120})})
        .then(r => r.json())
        .then(d => {
            showToast(d.success ? 'Discoverable for 2 minutes' : 'Failed', d.success ? 'success' : 'error');
            refreshBT();
        })
        .catch(() => showToast('Failed', 'error'));
}

// --- Pairing confirmation popup ---
let pairingShown = false;

function checkPairing() {
    fetch('/bt/pairing').then(r => r.json()).then(d => {
        const modal = document.getElementById('pairing-modal');
        if (d.pending && d.request) {
            document.getElementById('pairing-device').textContent =
                'Device: ' + d.request.address;
            document.getElementById('pairing-passkey').textContent =
                d.request.passkey;
            modal.classList.add('show');
            if (!pairingShown) {
                pairingShown = true;
                // Switch to BT tab to show context
                document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
                document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
                document.querySelector('[data-page="bt"]').classList.add('active');
                document.getElementById('page-bt').classList.add('active');
            }
        } else {
            modal.classList.remove('show');
            pairingShown = false;
        }
    }).catch(() => {});
}

function pairingRespond(accept) {
    fetch('/bt/pairing/confirm', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({accept: accept})
    }).then(r => r.json()).then(d => {
        document.getElementById('pairing-modal').classList.remove('show');
        pairingShown = false;
        showToast(accept ? 'Pairing accepted' : 'Pairing rejected',
                  accept ? 'success' : 'error');
        setTimeout(refreshBT, 2000);
    }).catch(() => showToast('Failed to respond to pairing', 'error'));
}

// Poll for pairing requests every second
setInterval(checkPairing, 1000);

// Auto-refresh BT page every 3 seconds when visible
setInterval(() => {
    if (document.getElementById('page-bt').classList.contains('active')) refreshBT();
}, 3000);
</script>
</body>
</html>"""


def start_aa_display(config: BCMConfig, event_bus: EventBus,
                     bt_manager: Any = None) -> AADisplaySimulator:
    """Start the AA display simulator. Returns the controller."""
    display = AADisplaySimulator(config, event_bus, bt_manager=bt_manager)
    display.start()
    return display
