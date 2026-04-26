"""Car alarm system — arm/disarm, door/motion/tilt/shock detection, siren.

Integrates with central lock Arduino for siren + LED control.
Sends SMS alerts via LTE modem when triggered.
"""

import threading
import time
from enum import Enum
from src.core.logger import get_logger

log = get_logger("alarm")


class AlarmState(Enum):
    DISARMED = "disarmed"
    ARMING = "arming"      # 30s delay before armed
    ARMED = "armed"
    TRIGGERED = "triggered"
    SILENCING = "silencing"


class AlarmSystem:
    """Car alarm with multiple sensors and siren."""

    def __init__(self, config, event_bus):
        self.config = config
        self.bus = event_bus
        self._state = AlarmState.DISARMED
        self._lock = threading.Lock()
        self._siren_duration = config.get("alarm.siren_duration", 60)
        self._arming_delay = config.get("alarm.arming_delay", 30)
        self._siren_thread = None

        # Subscribe to sensor events
        bus.subscribe("vehicle.locked", self._on_lock_change)
        bus.subscribe("alarm.sensor.door", self._on_sensor)
        bus.subscribe("alarm.sensor.motion", self._on_sensor)
        bus.subscribe("alarm.sensor.tilt", self._on_sensor)
        bus.subscribe("alarm.sensor.shock", self._on_sensor)
        bus.subscribe("alarm.cmd.arm", lambda t, v, ts: self.arm())
        bus.subscribe("alarm.cmd.disarm", lambda t, v, ts: self.disarm())

    @property
    def state(self):
        return self._state

    def arm(self):
        with self._lock:
            if self._state != AlarmState.DISARMED:
                return
            self._state = AlarmState.ARMING
            self.bus.publish("alarm.state", "arming")
            log.info("Alarm arming (delay %ds)", self._arming_delay)

        def _delayed_arm():
            time.sleep(self._arming_delay)
            with self._lock:
                if self._state == AlarmState.ARMING:
                    self._state = AlarmState.ARMED
                    self.bus.publish("alarm.state", "armed")
                    self.bus.publish("alarm.led", True)  # Blink LED
                    log.info("Alarm ARMED")

        threading.Thread(target=_delayed_arm, daemon=True).start()

    def disarm(self):
        with self._lock:
            prev = self._state
            self._state = AlarmState.DISARMED
            self.bus.publish("alarm.state", "disarmed")
            self.bus.publish("alarm.led", False)
            if prev == AlarmState.TRIGGERED:
                self.bus.publish("vehicle.cmd.siren_off", True)
            log.info("Alarm DISARMED")

    def trigger(self, source="unknown"):
        with self._lock:
            if self._state != AlarmState.ARMED:
                return
            self._state = AlarmState.TRIGGERED
            self.bus.publish("alarm.state", "triggered")
            self.bus.publish("alarm.trigger_source", source)
            log.warning("ALARM TRIGGERED by: %s", source)

        # Activate siren
        self.bus.publish("vehicle.cmd.siren_on", True)
        self.bus.publish("vehicle.cmd.blink_alarm", True)

        # Send SMS alert
        self.bus.publish("alarm.sms_alert", f"ALARM! {source}")

        # Auto-silence after duration
        def _silence():
            time.sleep(self._siren_duration)
            with self._lock:
                if self._state == AlarmState.TRIGGERED:
                    self.bus.publish("vehicle.cmd.siren_off", True)
                    self._state = AlarmState.ARMED  # Re-arm
                    self.bus.publish("alarm.state", "armed")
                    log.info("Alarm re-armed after siren timeout")

        self._siren_thread = threading.Thread(target=_silence, daemon=True)
        self._siren_thread.start()

    def _on_lock_change(self, topic, locked, ts):
        if locked:
            self.arm()
        else:
            self.disarm()

    def _on_sensor(self, topic, value, ts):
        if not value:
            return
        source_map = {
            "alarm.sensor.door": "door opened",
            "alarm.sensor.motion": "motion detected",
            "alarm.sensor.tilt": "tilt/tow detected",
            "alarm.sensor.shock": "shock/impact detected",
        }
        source = source_map.get(topic, topic)
        self.trigger(source)

    def start(self):
        log.info("Alarm system started (siren: %ds, arming delay: %ds)",
                 self._siren_duration, self._arming_delay)
        self.bus.publish("alarm.state", self._state.value)

    def stop(self):
        self.disarm()


def start_alarm(config, event_bus, hal=None, **kwargs):
    alarm = AlarmSystem(config, event_bus)
    alarm.start()
    return alarm
