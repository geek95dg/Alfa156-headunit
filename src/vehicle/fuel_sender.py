"""Fuel sender ADC-to-percentage calibration.

Converts raw Arduino ADC readings from the resistive fuel tank sender
into a fuel level percentage (0-100%). The Alfa Romeo 156 uses a
resistive float sender (approx 7-180 ohm range) read through a
voltage divider on Arduino analog pin A4.

Calibration curve is configurable via bcm_config.yaml. Default values
are estimates — adjust after measuring your sender at known fill levels.

Circuit:
    5V ──[Rref 330Ω]──┬── Fuel Sender ── GND (car chassis)
                       │
                    Arduino A4

ADC = 1023 × R_sender / (R_ref + R_sender)
  Full tank (7Ω):   ADC ≈ 21
  Empty tank (180Ω): ADC ≈ 361
"""

from src.core.event_bus import EventBus
from src.core.logger import get_logger

log = get_logger("vehicle.fuel_sender")

# Default calibration points: (ADC_value, fuel_percentage)
# Sorted by ADC ascending. Linear interpolation between points.
# Alfa 156 1.9 JTD sender: lower resistance = more fuel = lower ADC
DEFAULT_CALIBRATION = [
    (20, 100),   # Full tank (~7Ω)
    (50, 75),    # 3/4
    (120, 50),   # Half
    (220, 25),   # 1/4
    (360, 5),    # Reserve
    (400, 0),    # Empty / sender disconnected
]


class FuelSender:
    """Reads raw fuel ADC from Arduino and publishes calibrated percentage."""

    def __init__(self, config, event_bus: EventBus):
        self._bus = event_bus
        self._calibration = self._load_calibration(config)
        self._last_pct = -1.0
        self._smoothed_adc = -1.0

        self._bus.subscribe("vehicle.fuel_raw", self._on_raw)
        log.info("FuelSender initialized (%d calibration points)",
                 len(self._calibration))

    def _load_calibration(self, config):
        points = config.get("fuel_sender.calibration", None)
        if points and isinstance(points, list):
            try:
                return sorted([(int(p[0]), float(p[1])) for p in points])
            except (ValueError, IndexError):
                log.warning("Invalid fuel calibration in config, using defaults")
        return list(DEFAULT_CALIBRATION)

    def _on_raw(self, topic: str, adc_value: int, ts: float = 0) -> None:
        if self._smoothed_adc < 0:
            self._smoothed_adc = float(adc_value)
        else:
            self._smoothed_adc = self._smoothed_adc * 0.8 + adc_value * 0.2

        pct = self._adc_to_percent(self._smoothed_adc)
        pct = max(0.0, min(100.0, pct))

        if abs(pct - self._last_pct) > 0.5:
            self._last_pct = pct
            self._bus.publish("obd.fuel_level", round(pct, 1))
            log.debug("Fuel: ADC=%d smoothed=%.0f → %.1f%%",
                      adc_value, self._smoothed_adc, pct)

    def _adc_to_percent(self, adc: float) -> float:
        cal = self._calibration
        if adc <= cal[0][0]:
            return cal[0][1]
        if adc >= cal[-1][0]:
            return cal[-1][1]
        for i in range(len(cal) - 1):
            a0, p0 = cal[i]
            a1, p1 = cal[i + 1]
            if a0 <= adc <= a1:
                frac = (adc - a0) / (a1 - a0)
                return p0 + frac * (p1 - p0)
        return 0.0
