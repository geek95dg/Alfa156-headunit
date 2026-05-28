"""Always-on Nano (Domain A) serial bridge.

Talks to the always-on Arduino Nano running
``arduino/output_controller/output_controller.ino`` over USB serial
(``/dev/ttyUSB0`` by default, 9600 baud, JSON lines).

The module is named ``central_lock`` for historical reasons — the
original concept replaced the OEM Alfa 156 central lock. That has been
dropped: the original lock system stays untouched. This module now
handles the smaller set of features the Nano actually owns:

  - Display backlight PWM (forwarded from ``power.backlight_brightness``
    events, which originate in ``src/power/brightness.py``).
  - Window remote events from the secondary 433 MHz keyfob.
  - BLE-gated trunk events.
  - Window code / BLE tag learning (driven from the Settings screen or
    a console one-shot).
"""

import json
import threading
import time
from src.core.logger import get_logger

log = get_logger("nano_bridge")


class CentralLockModule:
    """Serial bridge to the always-on Nano (Domain A).

    Event bus subscriptions
    -----------------------
    - ``power.backlight_brightness`` (dict ``{display, brightness}``) →
      forwarded to the Nano as ``{"cmd":"backlight",…}``.
    - ``vehicle.cmd.trunk`` → no-op (the Nano fires its trunk relay
      autonomously when the BLE-gated button is pressed). Kept as a
      subscription so legacy callers don't blow up.
    - ``vehicle.cmd.learn_window`` (str slot, e.g. ``"FL_DOWN"``) →
      sends ``{"cmd":"learn_window","slot":…}``.
    - ``vehicle.cmd.learn_ble`` → sends ``{"cmd":"learn_ble"}``.
    - ``vehicle.cmd.set_ble_mac`` (str 12 hex chars) → sends
      ``{"cmd":"set_ble_mac","mac":…}``.
    - ``vehicle.cmd.set_ble_rssi`` (int dBm) → sends
      ``{"cmd":"set_ble_rssi","threshold":…}``.

    Events published
    ----------------
    - ``vehicle.window`` ({"slot": str, "phase": "press"|"release"})
    - ``vehicle.trunk`` (dict {"opened": True, "rssi": int})
    - ``vehicle.trunk_denied`` (dict {"reason": str, "rssi": int|None})
    - ``vehicle.ble_learned`` (dict {"mac": str, "rssi": int})
    - ``vehicle.window_code_learned`` (dict {"slot": str, "code": int})
    - ``vehicle.rf_unknown`` (int code)
    """

    def __init__(self, config, event_bus, hal):
        self.config = config
        self.bus = event_bus
        self.hal = hal
        self._running = False
        self._thread = None
        self._serial = None
        self._port = config.get("central_lock.port", "/dev/ttyUSB0")
        self._baud = config.get("central_lock.baudrate", 9600)
        self._write_lock = threading.Lock()

        # Backlight: forward from the BrightnessController's events
        self.bus.subscribe("power.backlight_brightness", self._on_backlight)

        # Configuration / learning entry points (driven from Settings UI)
        self.bus.subscribe(
            "vehicle.cmd.learn_window",
            lambda t, v, ts: self.learn_window(v if isinstance(v, str) else ""),
        )
        self.bus.subscribe(
            "vehicle.cmd.learn_ble",
            lambda t, v, ts: self.learn_ble(),
        )
        self.bus.subscribe(
            "vehicle.cmd.set_ble_mac",
            lambda t, v, ts: self.set_ble_mac(v if isinstance(v, str) else ""),
        )
        self.bus.subscribe(
            "vehicle.cmd.set_ble_rssi",
            lambda t, v, ts: self.set_ble_rssi(int(v) if v is not None else -80),
        )

    def start(self):
        self._running = True
        self._connect()
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()
        log.info("Nano bridge started (port %s)", self._port)

    def stop(self):
        self._running = False
        if self._serial:
            try:
                self._serial.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Serial plumbing
    # ------------------------------------------------------------------
    def _connect(self):
        try:
            import serial
            self._serial = serial.Serial(self._port, self._baud, timeout=1)
            log.info("Connected to Nano on %s", self._port)
        except Exception:
            log.warning("Nano not available on %s (mock mode)", self._port)
            self._serial = None

    def _send(self, cmd_dict):
        if self._serial and self._serial.is_open:
            try:
                msg = json.dumps(cmd_dict) + "\n"
                with self._write_lock:
                    self._serial.write(msg.encode())
                log.debug("Nano cmd: %s", cmd_dict)
            except Exception:
                log.exception("Serial write failed")
        else:
            log.debug("Nano cmd (mock): %s", cmd_dict)

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

    # ------------------------------------------------------------------
    # Inbound event dispatch
    # ------------------------------------------------------------------
    def _handle_response(self, data):
        event = data.get("event")
        if event == "window":
            self.bus.publish("vehicle.window", {
                "slot": data.get("slot"), "phase": "press",
            })
        elif event == "window_release":
            self.bus.publish("vehicle.window", {
                "slot": data.get("slot"), "phase": "release",
            })
        elif event == "trunk":
            self.bus.publish("vehicle.trunk", {
                "opened": True, "rssi": data.get("rssi"),
            })
        elif event == "trunk_denied":
            self.bus.publish("vehicle.trunk_denied", {
                "reason": data.get("reason"),
                "rssi": data.get("rssi"),
            })
        elif event == "ble_learned":
            self.bus.publish("vehicle.ble_learned", {
                "mac": data.get("mac"),
                "rssi": data.get("rssi"),
            })
            log.info("BLE tag learned: %s (RSSI %s)",
                     data.get("mac"), data.get("rssi"))
        elif event == "learned":
            self.bus.publish("vehicle.window_code_learned", {
                "slot": data.get("slot"),
                "code": data.get("code"),
            })
            log.info("Window code learned: %s = %s",
                     data.get("slot"), data.get("code"))
        elif event == "rf_unknown":
            self.bus.publish("vehicle.rf_unknown", data.get("code"))
        elif event == "ready":
            log.info("Nano ready: %s", data.get("fw"))
        elif event == "error":
            log.warning("Nano error: %s", data.get("msg"))

    # ------------------------------------------------------------------
    # Event-bus → Nano forwarders
    # ------------------------------------------------------------------
    def _on_backlight(self, topic, value, timestamp):
        if isinstance(value, dict):
            display = value.get("display")
            brightness = value.get("brightness")
            if display and brightness is not None:
                self._send({
                    "cmd": "backlight",
                    "display": display,
                    "brightness": int(brightness),
                })

    # ------------------------------------------------------------------
    # Public API (also driven via cmd.* event bus topics above)
    # ------------------------------------------------------------------
    def learn_window(self, slot):
        if not slot:
            log.warning("learn_window called with empty slot")
            return
        self._send({"cmd": "learn_window", "slot": slot})

    def learn_ble(self):
        self._send({"cmd": "learn_ble"})

    def set_ble_mac(self, mac):
        if not mac or len(mac) != 12:
            log.warning("set_ble_mac requires 12 hex chars, got %r", mac)
            return
        self._send({"cmd": "set_ble_mac", "mac": mac})

    def set_ble_rssi(self, threshold):
        self._send({"cmd": "set_ble_rssi", "threshold": int(threshold)})

    def ping(self):
        self._send({"cmd": "ping"})


def start_central_lock(config, event_bus, hal, **kwargs):
    """Module registry entry point."""
    mod = CentralLockModule(config, event_bus, hal)
    mod.start()
    return mod
