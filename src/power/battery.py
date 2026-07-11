"""Battery backup monitor — Li-ion battery status via Arduino ADC.

Monitors backup battery voltage, manages power switching between
car battery and Li-ion backup for suspend mode.
"""

from src.core.logger import get_logger

log = get_logger("battery")


class BatteryBackup:
    """Monitor Li-ion backup battery and manage power switching."""

    # 18650 Li-ion voltage thresholds
    FULL_V = 4.2
    NOMINAL_V = 3.7
    LOW_V = 3.3
    CRITICAL_V = 3.0

    def __init__(self, event_bus):
        self.bus = event_bus
        self._running = False
        self._thread = None
        self._voltage = 0.0
        self._on_backup = False

        self.bus.subscribe("arduino.battery_voltage", self._on_adc)

    def _on_adc(self, topic, voltage, ts):
        self._voltage = voltage
        pct = max(0, min(100, int((voltage - self.CRITICAL_V) / (self.FULL_V - self.CRITICAL_V) * 100)))
        self.bus.publish("battery.backup_voltage", voltage)
        self.bus.publish("battery.backup_pct", pct)

        if voltage < self.LOW_V:
            self.bus.publish("battery.backup_low", True)
            log.warning("Backup battery LOW: %.2fV (%d%%)", voltage, pct)
        if voltage < self.CRITICAL_V:
            self.bus.publish("battery.backup_critical", True)
            log.error("Backup battery CRITICAL: %.2fV — forcing shutdown", voltage)

    def start(self):
        self._running = True
        log.info("Battery backup monitor started")

    def stop(self):
        self._running = False


def start_battery(config=None, event_bus=None, **kwargs):
    mon = BatteryBackup(event_bus)
    mon.start()
    return mon
