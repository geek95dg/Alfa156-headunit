"""x86 parking sensor simulator — simulates approach/retreat to obstacles.

Provides two simulation modes:
    1. Auto demo: random-walk distances simulating a car reversing toward a wall
    2. Keyboard override: arrow keys adjust distances manually

Also serves as the module entry point (start_parking) called from main.py.
"""

import math
import random
import time
import threading
from typing import Any, Optional

from src.core.event_bus import EventBus
from src.core.logger import get_logger
from src.parking.hcsr04 import SensorArray, MAX_DISTANCE_M
from src.parking.distance import DistanceProcessor
from src.parking.buzzer import BuzzerController

log = get_logger("parking.simulator")


class ParkingSimulator:
    """Simulates 4 parking sensor distances for x86 testing.

    In auto mode, generates a realistic approach pattern:
    - Starts at ~2m, gradually approaches to ~0.1m, then retreats
    - Each sensor has slightly different timing (not perfectly aligned)
    - Small random noise added for realism
    """

    def __init__(self, sensor_array: SensorArray):
        self._sensor_array = sensor_array
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._t = 0.0
        self._manual_distances: Optional[list[float]] = None

    def set_distances(self, distances: list[float]) -> None:
        """Manually set sensor distances (for keyboard control)."""
        self._manual_distances = list(distances)

    def start(self) -> None:
        """Start the simulation thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        log.info("Parking simulator started (auto demo mode)")

    def stop(self) -> None:
        """Stop the simulation thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None
        log.info("Parking simulator stopped")

    def _run(self) -> None:
        """Generate simulated distances and inject into sensors."""
        while self._running:
            if self._manual_distances:
                distances = self._manual_distances
            else:
                distances = self._generate_auto()

            # Inject into mock sensors
            for i, sensor in enumerate(self._sensor_array.sensors):
                if i < len(distances):
                    sensor.set_mock_distance(distances[i])

            self._t += 0.05
            time.sleep(0.24)  # Match real scan cycle (~240ms)

    def _generate_auto(self) -> list[float]:
        """Generate auto-demo distances simulating approach and retreat."""
        # Sawtooth approach: 2.0m -> 0.1m over ~20s, then reset
        cycle = 20.0  # seconds per full approach cycle
        phase = (self._t % cycle) / cycle  # 0..1

        # Approach curve: starts slow, speeds up
        base_dist = MAX_DISTANCE_M * (1.0 - phase ** 0.7)
        base_dist = max(0.05, base_dist)

        distances = []
        for i in range(4):
            # Each sensor offset slightly (simulates angled bumper)
            offset = 0.15 * math.sin(self._t * 0.3 + i * 1.2)
            noise = random.gauss(0, 0.02)
            dist = max(0.03, min(MAX_DISTANCE_M, base_dist + offset + noise))
            distances.append(dist)

        return distances


class ParkingSystem:
    """Complete parking sensor system — ties together sensors, distance processing,
    buzzer, dashboard overlay, and simulator (on x86).
    """

    def __init__(self, config: Any, event_bus: EventBus, hal: Any):
        self._config = config
        self._event_bus = event_bus
        self._active = False

        # Create sensor array
        self._sensor_array = SensorArray(hal, config)

        # Distance processor with median filter
        self._processor = DistanceProcessor(event_bus, filter_size=3)

        # Buzzer controller
        self._buzzer = BuzzerController(hal, config, event_bus)

        # Simulator (x86 only)
        self._simulator: Optional[ParkingSimulator] = None
        if config.platform == "x86":
            self._simulator = ParkingSimulator(self._sensor_array)

        # Subscribe to reverse gear event to activate/deactivate
        self._event_bus.subscribe("power.reverse_gear", self._on_reverse_gear)

        log.info("ParkingSystem initialized (platform=%s)", config.platform)

    def activate(self) -> None:
        """Activate the parking system (called when reverse gear engaged)."""
        if self._active:
            return

        self._active = True
        log.info("Parking system ACTIVATED")

        # Start simulator on x86
        if self._simulator:
            self._simulator.start()

        # Start continuous measurement
        self._sensor_array.start_continuous(callback=self._on_measurement)

        # Start buzzer
        self._buzzer.start()

        # Notify dashboard to show parking overlay
        self._event_bus.publish("parking.active", True)

    def deactivate(self) -> None:
        """Deactivate the parking system (called when forward gear engaged)."""
        if not self._active:
            return

        self._active = False
        log.info("Parking system DEACTIVATED")

        # Stop everything
        self._sensor_array.stop_continuous()
        self._buzzer.stop()

        if self._simulator:
            self._simulator.stop()

        # Notify dashboard to hide parking overlay
        self._event_bus.publish("parking.active", False)

        # Reset processor filter
        self._processor.reset()

    def _on_measurement(self, distances: list[float]) -> None:
        """Called by SensorArray after each scan cycle."""
        result = self._processor.process(distances)

        # Update dashboard overlay distances
        self._event_bus.publish("parking.overlay_distances", result["distances"])

    def _on_reverse_gear(self, topic: str, value: Any, timestamp: float) -> None:
        """Handle reverse gear events from power module."""
        if value:
            self.activate()
        else:
            self.deactivate()


def start_parking(config: Any, event_bus: EventBus, hal: Any = None, **kwargs) -> None:
    """Entry point called from main.py to start the parking module.

    On x86: creates the system in standby (activated by reverse gear event).
            Also auto-activates for demo purposes.
    On OPi: waits for reverse gear signal.
    """
    system = ParkingSystem(config, event_bus, hal)

    # On x86, auto-activate for demo/testing
    if config.platform == "x86":
        log.info("x86 mode: auto-activating parking system for demo")
        system.activate()

    # Store reference for cleanup
    event_bus.publish("parking._internals", {
        "system": system,
    })
