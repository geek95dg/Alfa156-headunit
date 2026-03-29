"""Central lock module — Arduino serial communication.

Communicates with the central lock Arduino (Nano/Pro Mini) via Serial JSON.
Controls: lock, unlock, windows, trunk, blinkers, headlights.
433MHz RF remote learning via Arduino.
"""

import json
import threading
import time
from src.core.logger import get_logger

log = get_logger("central_lock")


class CentralLockModule:
    """Central lock + lighting via Arduino serial."""

    def __init__(self, config, event_bus, hal):
        self.config = config
        self.bus = event_bus
        self.hal = hal
        self._running = False
        self._thread = None
        self._serial = None
        self._port = config.get("central_lock.port", "/dev/ttyUSB1")
        self._baud = config.get("central_lock.baudrate", 9600)

        # Subscribe to commands from UI/event bus
        bus.subscribe("vehicle.cmd.lock", lambda t, v, ts: self.lock())
        bus.subscribe("vehicle.cmd.unlock", lambda t, v, ts: self.unlock())
        bus.subscribe("vehicle.cmd.trunk", lambda t, v, ts: self.trunk_release())
        bus.subscribe("vehicle.cmd.window_up", lambda t, v, ts: self.window_up())
        bus.subscribe("vehicle.cmd.window_down", lambda t, v, ts: self.window_down())
        bus.subscribe("vehicle.cmd.learn_rf", lambda t, v, ts: self.learn_rf())

    def start(self):
        self._running = True
        self._connect()
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()
        log.info("Central lock started (port %s)", self._port)

    def stop(self):
        self._running = False
        if self._serial:
            try:
                self._serial.close()
            except Exception:
                pass

    def _connect(self):
        try:
            import serial
            self._serial = serial.Serial(self._port, self._baud, timeout=1)
            log.info("Connected to lock Arduino on %s", self._port)
        except Exception:
            log.warning("Lock Arduino not available on %s (mock mode)", self._port)
            self._serial = None

    def _send(self, cmd_dict):
        if self._serial and self._serial.is_open:
            try:
                msg = json.dumps(cmd_dict) + "\n"
                self._serial.write(msg.encode())
                log.debug("Lock cmd: %s", cmd_dict)
            except Exception:
                log.exception("Serial write failed")
        else:
            log.debug("Lock cmd (mock): %s", cmd_dict)

    def _read_loop(self):
        while self._running:
            if not self._serial:
                time.sleep(2)
                self._connect()
                continue
            try:
                line = self._serial.readline()
                if line:
                    data = json.loads(line.decode().strip())
                    self._handle_response(data)
            except json.JSONDecodeError:
                pass
            except Exception:
                time.sleep(1)

    def _handle_response(self, data):
        event = data.get("event")
        if event == "locked":
            self.bus.publish("vehicle.locked", True)
        elif event == "unlocked":
            self.bus.publish("vehicle.locked", False)
        elif event == "rf_learned":
            self.bus.publish("vehicle.rf_learned", data.get("code"))
            log.info("RF remote learned: %s", data.get("code"))

    def lock(self):
        self._send({"cmd": "lock"})
        self.bus.publish("vehicle.locked", True)

    def unlock(self):
        self._send({"cmd": "unlock"})
        self.bus.publish("vehicle.locked", False)

    def trunk_release(self):
        self._send({"cmd": "trunk"})
        self.bus.publish("vehicle.trunk", True)

    def window_up(self):
        self._send({"cmd": "window_up"})

    def window_down(self):
        self._send({"cmd": "window_down"})

    def learn_rf(self):
        self._send({"cmd": "learn"})
        log.info("RF learning mode activated (10s window)")

    def blink(self, count=2):
        self._send({"cmd": "blink", "count": count})

    def headlights(self, duration_sec=60):
        self._send({"cmd": "headlights", "duration": duration_sec})


def start_central_lock(config, event_bus, hal, **kwargs):
    """Module registry entry point."""
    mod = CentralLockModule(config, event_bus, hal)
    mod.start()
    return mod
