"""Crash detection — GPS speed delta + accelerometer + DVR protection.

Detects potential crashes and protects DVR recording segments.
"""

import json
import os
import time
import threading
from src.core.logger import get_logger

log = get_logger("crash_detect")


class CrashDetector:
    """Detects crashes via GPS speed delta and protects DVR segments."""

    SPEED_DROP_THRESHOLD = 30   # km/h drop in 2 seconds
    G_FORCE_THRESHOLD = 3.0     # G threshold for accelerometer
    POST_CRASH_RECORD_SEC = 60  # Continue recording after crash

    def __init__(self, config, event_bus):
        self.config = config
        self.bus = event_bus
        # Thresholds configurable via the crash_detection.* YAML block
        self.SPEED_DROP_THRESHOLD = config.get(
            "crash_detection.speed_drop_threshold", self.SPEED_DROP_THRESHOLD)
        self.G_FORCE_THRESHOLD = config.get(
            "crash_detection.g_force_threshold", self.G_FORCE_THRESHOLD)
        self.POST_CRASH_RECORD_SEC = config.get(
            "crash_detection.post_crash_record_sec", self.POST_CRASH_RECORD_SEC)
        self._running = False
        self._last_speed = 0
        self._last_speed_ts = 0
        self._crash_detected = False
        self._metadata_dir = "data/crash_events"

        self.bus.subscribe("gps.speed", self._on_speed)
        self.bus.subscribe("alarm.sensor.tilt", self._on_accel)  # MPU6050 G-force

    def _on_speed(self, topic, speed, ts):
        now = time.time()
        dt = now - self._last_speed_ts
        if dt > 0 and dt < 3 and self._last_speed > 20:
            speed_drop = self._last_speed - speed
            if speed_drop > self.SPEED_DROP_THRESHOLD:
                self._trigger_crash("gps_speed_drop", {
                    "prev_speed": self._last_speed,
                    "curr_speed": speed,
                    "drop": speed_drop,
                    "dt": dt,
                })

        self._last_speed = speed
        self._last_speed_ts = now

    def _on_accel(self, topic, g_force, ts):
        if isinstance(g_force, (int, float)) and g_force > self.G_FORCE_THRESHOLD:
            self._trigger_crash("accelerometer", {"g_force": g_force})

    def _trigger_crash(self, source, data):
        if self._crash_detected:
            return  # Already handling a crash

        self._crash_detected = True
        log.critical("CRASH DETECTED via %s: %s", source, data)

        # Protect current DVR segments
        self.bus.publish("dvr.protect_segment", True)
        self.bus.publish("crash.detected", {"source": source, **data})

        # Save crash metadata
        self._save_metadata(source, data)

        # Trigger alarm (if car was moving)
        self.bus.publish("alarm.sensor.shock", True)

        # Keep recording for 60s after crash
        def _post_crash():
            time.sleep(self.POST_CRASH_RECORD_SEC)
            self._crash_detected = False
            log.info("Post-crash recording period ended")

        threading.Thread(target=_post_crash, daemon=True).start()

    def _save_metadata(self, source, data):
        os.makedirs(self._metadata_dir, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        pos = self.bus.get_last("gps.position")
        meta = {
            "timestamp": ts,
            "source": source,
            "data": data,
            "gps": pos[0] if pos else None,
        }
        path = os.path.join(self._metadata_dir, f"crash_{ts}.json")
        try:
            with open(path, "w") as f:
                json.dump(meta, f, indent=2, default=str)
            log.info("Crash metadata saved: %s", path)
        except Exception:
            log.exception("Failed to save crash metadata")

    def start(self):
        self._running = True
        log.info("Crash detector started (speed threshold: %d km/h, G threshold: %.1f)",
                 self.SPEED_DROP_THRESHOLD, self.G_FORCE_THRESHOLD)

    def stop(self):
        self._running = False


def start_crash_detect(config, event_bus, hal=None, **kwargs):
    detector = CrashDetector(config, event_bus)
    detector.start()
    return detector
