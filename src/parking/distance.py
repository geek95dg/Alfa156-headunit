"""Distance zone logic — classify sensor distances into color-coded zones.

Zones:
    >1.0m    — GREEN  (safe)
    0.5-1.0m — YELLOW (caution)
    0.3-0.5m — ORANGE (warning)
    <0.3m    — RED    (danger / stop)
"""

from enum import Enum
from typing import Any

from src.core.event_bus import EventBus
from src.core.logger import get_logger

log = get_logger("parking.distance")


class Zone(Enum):
    """Parking distance zone classification."""
    SAFE = "safe"         # >1.0m — green
    CAUTION = "caution"   # 0.5-1.0m — yellow
    WARNING = "warning"   # 0.3-0.5m — orange
    DANGER = "danger"     # <0.3m — red


# Zone thresholds in meters
ZONE_THRESHOLDS = {
    Zone.SAFE: 1.0,
    Zone.CAUTION: 0.5,
    Zone.WARNING: 0.3,
    # Below 0.3m = DANGER
}

SENSOR_LABELS = ["rear_left", "rear_center_left", "rear_center_right", "rear_right"]


def classify_distance(distance_m: float) -> Zone:
    """Classify a distance reading into a zone.

    Args:
        distance_m: Distance in meters.

    Returns:
        Zone enum value.
    """
    if distance_m > ZONE_THRESHOLDS[Zone.SAFE]:
        return Zone.SAFE
    elif distance_m > ZONE_THRESHOLDS[Zone.CAUTION]:
        return Zone.CAUTION
    elif distance_m > ZONE_THRESHOLDS[Zone.WARNING]:
        return Zone.WARNING
    else:
        return Zone.DANGER


def minimum_distance(distances: list[float]) -> float:
    """Get the closest obstacle distance from all sensors."""
    if not distances:
        return 2.5
    return min(distances)


class DistanceProcessor:
    """Processes raw sensor distances and publishes zone events.

    Applies median filtering to reduce noise and publishes:
        - parking.distances: list of 4 distances in meters
        - parking.zones: list of 4 zone strings
        - parking.min_distance: closest obstacle distance
        - parking.min_zone: zone of closest obstacle
    """

    def __init__(self, event_bus: EventBus, filter_size: int = 3):
        """
        Args:
            event_bus: EventBus for publishing distance/zone events.
            filter_size: Number of readings to keep for median filter.
        """
        self._event_bus = event_bus
        self._filter_size = filter_size
        self._history: list[list[float]] = [[] for _ in range(4)]
        self._prev_zones: list[Zone] = [Zone.SAFE] * 4

    def process(self, raw_distances: list[float]) -> dict[str, Any]:
        """Process raw distance readings.

        Applies median filter, classifies zones, and publishes events.

        Args:
            raw_distances: List of 4 raw distance readings in meters.

        Returns:
            Dict with 'distances', 'zones', 'min_distance', 'min_zone'.
        """
        filtered = []
        for i, dist in enumerate(raw_distances):
            # Append to history
            self._history[i].append(dist)
            if len(self._history[i]) > self._filter_size:
                self._history[i].pop(0)

            # Median filter
            sorted_hist = sorted(self._history[i])
            median_val = sorted_hist[len(sorted_hist) // 2]
            filtered.append(median_val)

        # Classify zones
        zones = [classify_distance(d) for d in filtered]

        # Log zone transitions
        for i, (prev, curr) in enumerate(zip(self._prev_zones, zones)):
            if prev != curr:
                log.info("Sensor %s: %s -> %s (%.2fm)",
                         SENSOR_LABELS[i], prev.value, curr.value, filtered[i])
        self._prev_zones = list(zones)

        # Find closest obstacle
        min_dist = minimum_distance(filtered)
        min_zone = classify_distance(min_dist)

        # Publish events
        self._event_bus.publish("parking.distances", filtered)
        self._event_bus.publish("parking.zones", [z.value for z in zones])
        self._event_bus.publish("parking.min_distance", min_dist)
        self._event_bus.publish("parking.min_zone", min_zone.value)

        return {
            "distances": filtered,
            "zones": zones,
            "min_distance": min_dist,
            "min_zone": min_zone,
        }

    def reset(self) -> None:
        """Clear filter history."""
        self._history = [[] for _ in range(4)]
        self._prev_zones = [Zone.SAFE] * 4
