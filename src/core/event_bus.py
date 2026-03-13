"""Publish/subscribe message bus for inter-module communication.

Modules publish events (e.g. "obd.rpm", "env.temperature") and other
modules subscribe to them with callback functions. The bus runs in-process
using synchronous dispatch (suitable for Phase A single-process mode).
"""

import threading
import time
from collections import defaultdict
from typing import Any, Callable, Optional

from .logger import get_logger

log = get_logger("event_bus")

# Type alias for event callbacks
EventCallback = Callable[[str, Any, float], None]


class EventBus:
    """Thread-safe publish/subscribe event bus.

    Usage:
        bus = EventBus()

        def on_rpm(topic, value, timestamp):
            print(f"RPM: {value}")

        bus.subscribe("obd.rpm", on_rpm)
        bus.publish("obd.rpm", 3200)
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[EventCallback]] = defaultdict(list)
        self._wildcard_subscribers: list[EventCallback] = []
        self._lock = threading.Lock()
        self._last_values: dict[str, tuple[Any, float]] = {}

    def subscribe(self, topic: str, callback: EventCallback) -> None:
        """Subscribe to a specific topic.

        Args:
            topic: Event topic string (e.g. "obd.rpm", "env.temperature").
                   Use "*" to subscribe to all events.
            callback: Function called with (topic, value, timestamp).
        """
        with self._lock:
            if topic == "*":
                self._wildcard_subscribers.append(callback)
                log.debug("Wildcard subscriber added: %s", callback.__name__)
            else:
                self._subscribers[topic].append(callback)
                log.debug("Subscriber added for '%s': %s", topic, callback.__name__)

    def unsubscribe(self, topic: str, callback: EventCallback) -> None:
        """Remove a callback from a topic."""
        with self._lock:
            if topic == "*":
                try:
                    self._wildcard_subscribers.remove(callback)
                except ValueError:
                    pass
            else:
                try:
                    self._subscribers[topic].remove(callback)
                except ValueError:
                    pass

    def publish(self, topic: str, value: Any = None) -> None:
        """Publish an event to all subscribers.

        Args:
            topic: Event topic string.
            value: Payload data (any serializable type).
        """
        timestamp = time.time()

        with self._lock:
            self._last_values[topic] = (value, timestamp)
            callbacks = list(self._subscribers.get(topic, []))
            wildcards = list(self._wildcard_subscribers)

        for cb in callbacks + wildcards:
            try:
                cb(topic, value, timestamp)
            except Exception:
                log.exception("Error in subscriber %s for topic '%s'", cb.__name__, topic)

    def get_last(self, topic: str) -> Optional[tuple[Any, float]]:
        """Get the last published value for a topic.

        Returns:
            Tuple of (value, timestamp) or None if never published.
        """
        with self._lock:
            return self._last_values.get(topic)

    def topics(self) -> list[str]:
        """Return a list of all topics that have been published at least once."""
        with self._lock:
            return list(self._last_values.keys())

    def clear(self) -> None:
        """Remove all subscribers and cached values."""
        with self._lock:
            self._subscribers.clear()
            self._wildcard_subscribers.clear()
            self._last_values.clear()
