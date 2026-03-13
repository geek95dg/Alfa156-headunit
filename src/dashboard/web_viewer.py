"""Flask + WebSocket web viewer for x86 browser preview.

Captures PyGame surface as JPEG frames and streams via WebSocket
to a browser at http://localhost:5000.
"""

import io
import time
import base64
import threading
from typing import Optional

import pygame

from src.core.logger import get_logger

log = get_logger("web_viewer")

# Optional imports — Flask/gevent not required on OPi
try:
    from flask import Flask, render_template_string
    from flask_sock import Sock
    HAS_FLASK = True
except ImportError:
    HAS_FLASK = False
    log.debug("Flask not available — web viewer disabled")

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
    <title>BCM v7 — Dashboard Preview</title>
    <style>
        body { margin: 0; background: #111; display: flex; justify-content: center;
               align-items: center; min-height: 100vh; font-family: sans-serif; }
        #dash { border: 2px solid #333; image-rendering: pixelated; }
        .info { position: fixed; top: 10px; left: 10px; color: #666; font-size: 12px; }
        .disconnected { position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%);
                        color: #c33; font-size: 24px; display: none; }
    </style>
</head>
<body>
    <div class="info">BCM v7 Dashboard — Live Preview (WebSocket)</div>
    <img id="dash" width="800" height="480" />
    <div id="disc" class="disconnected">Disconnected</div>
    <script>
        const img = document.getElementById('dash');
        const disc = document.getElementById('disc');
        let ws;
        function connect() {
            ws = new WebSocket('ws://' + location.host + '/ws');
            ws.onmessage = function(e) {
                img.src = 'data:image/jpeg;base64,' + e.data;
                disc.style.display = 'none';
            };
            ws.onclose = function() {
                disc.style.display = 'block';
                setTimeout(connect, 2000);
            };
            ws.onerror = function() { ws.close(); };
        }
        connect();
    </script>
</body>
</html>"""


class WebViewer:
    """Streams PyGame surface frames to a browser via WebSocket."""

    def __init__(self, host: str = "0.0.0.0", port: int = 5000) -> None:
        self.host = host
        self.port = port
        self._latest_frame: Optional[str] = None
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def start(self) -> None:
        """Start the Flask web server in a background thread."""
        if not HAS_FLASK:
            log.warning("Flask not installed — web viewer disabled. Install flask and flask-sock.")
            return

        self._running = True
        self._thread = threading.Thread(target=self._run_server, daemon=True)
        self._thread.start()
        log.info("Web viewer started at http://%s:%d", self.host, self.port)

    def stop(self) -> None:
        self._running = False

    def update_frame(self, surface: pygame.Surface) -> None:
        """Capture current PyGame surface as JPEG base64 string."""
        try:
            raw = pygame.image.tostring(surface, "RGB")
            w, h = surface.get_size()

            if HAS_PIL:
                img = Image.frombytes("RGB", (w, h), raw)
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=70)
                frame_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
            else:
                # Fallback: BMP via PyGame (larger but no PIL needed)
                buf = io.BytesIO()
                pygame.image.save(surface, buf, "bmp")
                frame_b64 = base64.b64encode(buf.getvalue()).decode("ascii")

            with self._lock:
                self._latest_frame = frame_b64
        except Exception:
            log.exception("Failed to capture frame")

    def _run_server(self) -> None:
        app = Flask(__name__)
        sock = Sock(app)

        viewer = self

        @app.route("/")
        def index():
            return render_template_string(HTML_TEMPLATE)

        @sock.route("/ws")
        def ws_handler(ws):
            while viewer._running:
                with viewer._lock:
                    frame = viewer._latest_frame
                if frame:
                    try:
                        ws.send(frame)
                    except Exception:
                        break
                time.sleep(0.1)  # ~10 FPS to browser

        app.run(host=self.host, port=self.port, debug=False, use_reloader=False)
