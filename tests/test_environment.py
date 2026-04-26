"""Tests for Temperature & Environment Monitoring (Part 5)."""

import pytest

from src.core.event_bus import EventBus
from src.core.hal import HAL
from src.environment.ds18b20 import TemperatureReader, DEFAULT_READ_INTERVAL
from src.environment.icing import (
    IcingDetector,
    ICING_ALERT_THRESHOLD,
    ICING_ICON_THRESHOLD,
    ICING_RESET_THRESHOLD,
    MIN_TREND_SAMPLES,
)


# ---------------------------------------------------------------------------
# DS18B20 Temperature Reader tests
# ---------------------------------------------------------------------------

class TestTemperatureReader:
    def setup_method(self):
        self.hal = HAL(platform="x86")
        self.bus = EventBus()
        self.reader = TemperatureReader(self.hal, self.bus)

    def test_no_device_initially(self):
        """No mock device registered yet — read returns None."""
        assert self.reader.read_once() is None

    def test_read_with_mock_device(self):
        """Register a mock device and read temperature."""
        self.reader.onewire.add_device("28-test001", 22.5)
        # Re-discover after adding
        self.reader._discover_device()
        temp = self.reader.read_once()
        assert temp == 22.5
        assert self.reader.last_temperature == 22.5

    def test_publishes_event(self):
        """Temperature reading should publish to event bus."""
        received = {}

        def capture(topic, value, ts):
            received[topic] = value

        self.bus.subscribe("env.temperature", capture)
        self.reader.onewire.add_device("28-test002", 18.3)
        self.reader._discover_device()
        self.reader.read_once()

        assert "env.temperature" in received
        assert received["env.temperature"] == 18.3

    def test_callback(self):
        """Custom callback should be called on each reading."""
        temps = []
        self.reader.set_callback(lambda t: temps.append(t))
        self.reader.onewire.add_device("28-test003", 10.0)
        self.reader._discover_device()
        self.reader.read_once()

        assert temps == [10.0]

    def test_last_temperature_none_initially(self):
        assert self.reader.last_temperature is None

    def test_mock_temperature_update(self):
        """Injecting new mock temperature should reflect on next read."""
        self.reader.onewire.add_device("28-test004", 20.0)
        self.reader._discover_device()
        self.reader.read_once()
        assert self.reader.last_temperature == 20.0

        self.reader.onewire.set_mock_temperature("28-test004", 5.0)
        self.reader.read_once()
        assert self.reader.last_temperature == 5.0


# ---------------------------------------------------------------------------
# Icing Detector tests
# ---------------------------------------------------------------------------

class TestIcingDetector:
    def setup_method(self):
        self.bus = EventBus()
        self.detector = IcingDetector(self.bus)

    def _publish_temp(self, temp: float):
        """Helper to simulate a temperature reading."""
        self.bus.publish("env.temperature", temp)

    def test_no_alert_above_threshold(self):
        """No alert when temperature is well above threshold."""
        self._publish_temp(10.0)
        self._publish_temp(9.0)
        self._publish_temp(8.0)
        assert not self.detector.alert_active

    def test_alert_triggers_below_3c_falling(self):
        """Alert should trigger when temp drops below 3°C with falling trend."""
        for t in [6.0, 5.0, 4.0, 2.5]:
            self._publish_temp(t)
        assert self.detector.alert_active

    def test_alert_published_to_bus(self):
        """Icing alert event should be published."""
        received = {}

        def capture(topic, value, ts):
            received[topic] = value

        self.bus.subscribe("env.icing_alert", capture)

        for t in [5.0, 4.0, 2.0]:
            self._publish_temp(t)

        assert received.get("env.icing_alert") is True

    def test_icon_at_zero(self):
        """Snowflake icon should show when temp <= 0°C."""
        received = {}

        def capture(topic, value, ts):
            received[topic] = value

        self.bus.subscribe("env.icing_icon", capture)

        self._publish_temp(0.0)
        assert self.detector.icon_active
        assert received.get("env.icing_icon") is True

    def test_icon_off_above_zero(self):
        """Snowflake icon should not show when temp > 0°C."""
        self._publish_temp(5.0)
        assert not self.detector.icon_active

    def test_icon_toggles(self):
        """Icon should toggle on/off as temp crosses 0°C."""
        self._publish_temp(-2.0)
        assert self.detector.icon_active

        self._publish_temp(1.0)
        assert not self.detector.icon_active

    def test_hysteresis_prevents_retrigger(self):
        """Alert should not re-trigger until temp rises above reset threshold."""
        # Trigger alert
        for t in [5.0, 4.0, 2.0]:
            self._publish_temp(t)
        assert self.detector.alert_active

        # Temp slightly above 3°C — should NOT re-arm
        self._publish_temp(4.0)
        # Still below reset threshold (5°C), alert stays but won't re-trigger
        assert not self.detector._alert_armed

    def test_rearm_after_reset_threshold(self):
        """Alert should re-arm after temp rises above 5°C."""
        # Trigger first alert
        for t in [5.0, 4.0, 2.0]:
            self._publish_temp(t)
        assert self.detector.alert_active

        # Rise above reset threshold
        self._publish_temp(6.0)
        assert self.detector._alert_armed
        assert not self.detector.alert_active

        # Drop again — should trigger new alert
        for t in [4.0, 2.5]:
            self._publish_temp(t)
        assert self.detector.alert_active

    def test_no_alert_rising_temp(self):
        """No alert when temp is below threshold but trend is clearly rising."""
        # Pre-populate history with rising sub-threshold values so the
        # trend detector has enough data and sees a rising pattern.
        self.detector._history = [1.0, 1.5, 2.0]
        # Now publish a rising reading below 3°C
        self._publish_temp(2.5)
        # Last 3 in history: [1.5, 2.0, 2.5] — rising, so no alert
        assert not self.detector.alert_active

    def test_reset(self):
        """Reset should clear all state."""
        for t in [5.0, 4.0, 2.0]:
            self._publish_temp(t)
        assert self.detector.alert_active

        self.detector.reset()
        assert not self.detector.alert_active
        assert not self.detector.icon_active
        assert self.detector._alert_armed

    def test_non_numeric_value_ignored(self):
        """Non-numeric values should be silently ignored."""
        self._publish_temp("invalid")
        assert not self.detector.alert_active


# ---------------------------------------------------------------------------
# Threshold constants tests
# ---------------------------------------------------------------------------

class TestThresholds:
    def test_alert_threshold(self):
        assert ICING_ALERT_THRESHOLD == 3.0

    def test_icon_threshold(self):
        assert ICING_ICON_THRESHOLD == 0.0

    def test_reset_threshold_above_alert(self):
        assert ICING_RESET_THRESHOLD > ICING_ALERT_THRESHOLD

    def test_min_trend_samples(self):
        assert MIN_TREND_SAMPLES >= 2
