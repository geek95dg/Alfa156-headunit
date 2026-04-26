"""Tests for Parking Sensors System (Part 4)."""

import time
import pytest

from src.core.event_bus import EventBus
from src.core.hal import HAL
from src.core.config import BCMConfig
from src.parking.distance import (
    Zone, classify_distance, minimum_distance, DistanceProcessor,
    ZONE_THRESHOLDS, SENSOR_LABELS,
)
from src.parking.hcsr04 import HCSR04, SensorArray, MAX_DISTANCE_M
from src.parking.buzzer import BuzzerController, BEEP_PATTERNS


# ---------------------------------------------------------------------------
# Distance zone classification tests
# ---------------------------------------------------------------------------

class TestZoneClassification:
    def test_safe_zone(self):
        assert classify_distance(1.5) == Zone.SAFE
        assert classify_distance(2.0) == Zone.SAFE
        assert classify_distance(1.01) == Zone.SAFE

    def test_caution_zone(self):
        assert classify_distance(0.8) == Zone.CAUTION
        assert classify_distance(0.51) == Zone.CAUTION
        assert classify_distance(1.0) == Zone.CAUTION

    def test_warning_zone(self):
        assert classify_distance(0.4) == Zone.WARNING
        assert classify_distance(0.31) == Zone.WARNING
        assert classify_distance(0.5) == Zone.WARNING

    def test_danger_zone(self):
        assert classify_distance(0.2) == Zone.DANGER
        assert classify_distance(0.1) == Zone.DANGER
        assert classify_distance(0.0) == Zone.DANGER
        assert classify_distance(0.3) == Zone.DANGER

    def test_boundary_values(self):
        # Exact boundaries — at threshold = belongs to closer zone
        assert classify_distance(1.0) == Zone.CAUTION
        assert classify_distance(0.5) == Zone.WARNING
        assert classify_distance(0.3) == Zone.DANGER


class TestMinimumDistance:
    def test_normal_values(self):
        assert minimum_distance([1.0, 0.5, 0.8, 1.2]) == 0.5

    def test_all_same(self):
        assert minimum_distance([1.0, 1.0, 1.0, 1.0]) == 1.0

    def test_empty_list(self):
        assert minimum_distance([]) == 2.5

    def test_single_value(self):
        assert minimum_distance([0.3]) == 0.3


# ---------------------------------------------------------------------------
# Distance processor tests
# ---------------------------------------------------------------------------

class TestDistanceProcessor:
    def setup_method(self):
        self.bus = EventBus()
        self.processor = DistanceProcessor(self.bus, filter_size=3)

    def test_single_reading(self):
        result = self.processor.process([1.0, 0.8, 0.5, 0.3])
        assert result["distances"] == [1.0, 0.8, 0.5, 0.3]
        assert result["zones"] == [Zone.CAUTION, Zone.CAUTION, Zone.WARNING, Zone.DANGER]
        assert result["min_distance"] == 0.3
        assert result["min_zone"] == Zone.DANGER

    def test_median_filter(self):
        # Feed 3 readings — median should smooth noise
        self.processor.process([1.0, 1.0, 1.0, 1.0])
        self.processor.process([1.0, 1.0, 1.0, 1.0])
        # Spike on sensor 0 should be filtered by median
        result = self.processor.process([0.1, 1.0, 1.0, 1.0])
        # Median of [1.0, 1.0, 0.1] = 1.0 (middle value)
        assert result["distances"][0] == 1.0

    def test_publishes_events(self):
        received = {}

        def capture(topic, value, ts):
            received[topic] = value

        self.bus.subscribe("parking.distances", capture)
        self.bus.subscribe("parking.min_distance", capture)
        self.bus.subscribe("parking.min_zone", capture)
        self.bus.subscribe("parking.zones", capture)

        self.processor.process([1.5, 0.8, 0.4, 0.2])

        assert "parking.distances" in received
        assert "parking.min_distance" in received
        assert received["parking.min_distance"] == 0.2
        assert received["parking.min_zone"] == "danger"
        assert received["parking.zones"] == ["safe", "caution", "warning", "danger"]

    def test_reset_clears_history(self):
        self.processor.process([1.0, 1.0, 1.0, 1.0])
        self.processor.process([1.0, 1.0, 1.0, 1.0])
        self.processor.reset()
        # After reset, no history — first reading is used directly
        result = self.processor.process([0.5, 0.5, 0.5, 0.5])
        assert result["distances"] == [0.5, 0.5, 0.5, 0.5]


# ---------------------------------------------------------------------------
# HC-SR04 sensor tests (mock GPIO)
# ---------------------------------------------------------------------------

class TestHCSR04:
    def setup_method(self):
        self.hal = HAL(platform="x86")
        self.trig = self.hal.gpio(79, "out")
        self.echo = self.hal.gpio(80, "in")

    def test_mock_distance_injection(self):
        sensor = HCSR04(self.trig, self.echo, sensor_id=0)
        sensor.set_mock_distance(0.75)
        assert sensor.measure() == 0.75

    def test_mock_distance_clamping(self):
        sensor = HCSR04(self.trig, self.echo, sensor_id=0)
        sensor.set_mock_distance(5.0)
        assert sensor.measure() == MAX_DISTANCE_M
        sensor.set_mock_distance(-1.0)
        assert sensor.measure() == 0.0

    def test_last_distance_property(self):
        sensor = HCSR04(self.trig, self.echo, sensor_id=0)
        sensor.set_mock_distance(1.2)
        sensor.measure()
        assert sensor.last_distance == 1.2

    def test_default_distance(self):
        sensor = HCSR04(self.trig, self.echo, sensor_id=0)
        assert sensor.last_distance == MAX_DISTANCE_M


# ---------------------------------------------------------------------------
# Sensor array tests
# ---------------------------------------------------------------------------

class TestSensorArray:
    def setup_method(self):
        self.hal = HAL(platform="x86")
        self.config = BCMConfig(platform_override="x86")

    def test_initialization(self):
        array = SensorArray(self.hal, self.config)
        assert len(array.sensors) == 4
        assert len(array.distances) == 4

    def test_measure_all_with_mocks(self):
        array = SensorArray(self.hal, self.config)
        # Inject mock distances
        for i, d in enumerate([1.0, 0.8, 0.5, 0.3]):
            array.sensors[i].set_mock_distance(d)

        distances = array.measure_all()
        assert len(distances) == 4
        assert distances[0] == 1.0
        assert distances[3] == 0.3

    def test_get_distances_thread_safe(self):
        array = SensorArray(self.hal, self.config)
        for s in array.sensors:
            s.set_mock_distance(1.5)
        array.measure_all()
        result = array.get_distances()
        assert result == [1.5, 1.5, 1.5, 1.5]
        # Should return a copy
        result[0] = 999
        assert array.get_distances()[0] == 1.5


# ---------------------------------------------------------------------------
# Buzzer controller tests
# ---------------------------------------------------------------------------

class TestBuzzerController:
    def test_beep_pattern_definitions(self):
        # Verify all zones have patterns defined
        for zone in Zone:
            assert zone in BEEP_PATTERNS

    def test_safe_zone_no_beep(self):
        on, off = BEEP_PATTERNS[Zone.SAFE]
        assert on == 0

    def test_danger_continuous(self):
        on, off = BEEP_PATTERNS[Zone.DANGER]
        assert on > 0
        assert off == 0

    def test_buzzer_init(self):
        hal = HAL(platform="x86")
        bus = EventBus()
        config = BCMConfig(platform_override="x86")
        buzzer = BuzzerController(hal, config, bus)
        # Should initialize without error
        assert buzzer is not None

    def test_force_off(self):
        hal = HAL(platform="x86")
        bus = EventBus()
        config = BCMConfig(platform_override="x86")
        buzzer = BuzzerController(hal, config, bus)
        buzzer.force_off()
        # Should not raise


# ---------------------------------------------------------------------------
# Sensor labels
# ---------------------------------------------------------------------------

class TestSensorLabels:
    def test_four_labels(self):
        assert len(SENSOR_LABELS) == 4
        assert "rear_left" in SENSOR_LABELS
        assert "rear_right" in SENSOR_LABELS
