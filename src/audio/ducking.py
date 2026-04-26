"""Audio priority & ducking system.

Priority levels (highest to lowest):
    1. Parking sensor beeps — music ducked to -18dB
    2. Voice announcements (TTS) — music ducked to -12dB
    3. Phone calls (HFP) — music ducked to -15dB
    4. Music/radio — normal playback (0dB)

Ducking behavior:
    - Instant duck on trigger
    - Smooth 1-second fade-back when priority event ends
    - Multiple priorities stack (highest wins)
"""

import time
import threading
from enum import IntEnum
from typing import Any, Optional

from src.core.event_bus import EventBus
from src.core.logger import get_logger

log = get_logger("audio.ducking")

FADE_BACK_DURATION = 1.0  # seconds for smooth fade-back


class Priority(IntEnum):
    """Audio priority levels (lower number = higher priority)."""
    PARKING = 1
    VOICE = 2
    PHONE = 3
    MUSIC = 4


# Duck level in dB for each priority (applied to music)
DUCK_LEVELS: dict[Priority, float] = {
    Priority.PARKING: -18.0,
    Priority.VOICE: -12.0,
    Priority.PHONE: -15.0,
    Priority.MUSIC: 0.0,
}

# Gain boost for the priority source itself (dB)
SOURCE_BOOST: dict[Priority, float] = {
    Priority.PARKING: 0.0,
    Priority.VOICE: 3.0,
    Priority.PHONE: 0.0,
    Priority.MUSIC: 0.0,
}


class DuckingManager:
    """Manages audio ducking based on active priority events.

    Tracks which priority events are active and applies the
    appropriate duck level to the music stream.

    Events consumed:
        - parking.active: bool — parking sensors active
        - audio.voice_announcement: bool — TTS playing
        - audio.phone_call: bool — HFP call active

    Events published:
        - audio.duck_level: float — current duck level in dB
        - audio.music_gain: float — gain to apply to music (dB)
        - audio.priority_source_boost: float — boost for active priority source
    """

    def __init__(self, event_bus: EventBus):
        self._event_bus = event_bus
        self._active_priorities: set[Priority] = set()
        self._lock = threading.Lock()
        self._current_duck_db: float = 0.0
        self._fade_thread: Optional[threading.Thread] = None
        self._fade_cancel = False

        # Subscribe to priority trigger events
        self._event_bus.subscribe("parking.active", self._on_parking)
        self._event_bus.subscribe("audio.voice_announcement", self._on_voice)
        self._event_bus.subscribe("audio.phone_call", self._on_phone)

        log.info("DuckingManager initialized")

    def _on_parking(self, topic: str, value: Any, timestamp: float) -> None:
        if value:
            self.activate(Priority.PARKING)
        else:
            self.deactivate(Priority.PARKING)

    def _on_voice(self, topic: str, value: Any, timestamp: float) -> None:
        if value:
            self.activate(Priority.VOICE)
        else:
            self.deactivate(Priority.VOICE)

    def _on_phone(self, topic: str, value: Any, timestamp: float) -> None:
        if value:
            self.activate(Priority.PHONE)
        else:
            self.deactivate(Priority.PHONE)

    def activate(self, priority: Priority) -> None:
        """Activate a priority event — instantly duck music."""
        with self._lock:
            self._active_priorities.add(priority)
            self._cancel_fade()
            self._apply_duck()

        log.info("Priority activated: %s (duck=%.0fdB)",
                 priority.name, self._current_duck_db)

    def deactivate(self, priority: Priority) -> None:
        """Deactivate a priority event — fade back if no other priorities active."""
        with self._lock:
            self._active_priorities.discard(priority)

            if not self._active_priorities:
                # No more priorities — smooth fade back
                self._start_fade_back()
            else:
                # Other priorities still active — recalculate
                self._apply_duck()

        log.info("Priority deactivated: %s", priority.name)

    def _apply_duck(self) -> None:
        """Apply the highest-priority duck level."""
        if self._active_priorities:
            highest = min(self._active_priorities)  # Lower number = higher priority
            duck_db = DUCK_LEVELS[highest]
            boost_db = SOURCE_BOOST[highest]
        else:
            duck_db = 0.0
            boost_db = 0.0

        self._current_duck_db = duck_db
        self._event_bus.publish("audio.duck_level", duck_db)
        self._event_bus.publish("audio.music_gain", duck_db)
        self._event_bus.publish("audio.priority_source_boost", boost_db)

    def _start_fade_back(self) -> None:
        """Start a smooth fade-back to normal volume."""
        self._fade_cancel = False
        self._fade_thread = threading.Thread(target=self._fade_back_loop, daemon=True)
        self._fade_thread.start()

    def _cancel_fade(self) -> None:
        """Cancel an in-progress fade-back."""
        self._fade_cancel = True

    def _fade_back_loop(self) -> None:
        """Smoothly fade music gain from current duck level back to 0dB."""
        start_db = self._current_duck_db
        if start_db >= 0:
            return  # Already at normal

        steps = 20
        step_duration = FADE_BACK_DURATION / steps
        db_per_step = -start_db / steps

        for i in range(steps):
            if self._fade_cancel:
                return  # New priority activated, cancel fade

            current = start_db + db_per_step * (i + 1)
            self._current_duck_db = min(0.0, current)
            self._event_bus.publish("audio.music_gain", self._current_duck_db)
            time.sleep(step_duration)

        self._current_duck_db = 0.0
        self._event_bus.publish("audio.music_gain", 0.0)
        self._event_bus.publish("audio.duck_level", 0.0)
        self._event_bus.publish("audio.priority_source_boost", 0.0)
        log.debug("Fade-back complete")

    @property
    def current_duck_db(self) -> float:
        return self._current_duck_db

    @property
    def active_priorities(self) -> set[Priority]:
        with self._lock:
            return set(self._active_priorities)

    @property
    def highest_priority(self) -> Optional[Priority]:
        with self._lock:
            if self._active_priorities:
                return min(self._active_priorities)
            return None
