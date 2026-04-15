"""Audio source switching — manage active audio source.

Sources:
    - android_auto: Android Auto / CarPlay audio (via OpenAuto)
    - bluetooth: BT A2DP streaming from phone
    - fm_radio: FM radio via RTL-SDR (optional)
    - system: System sounds (beeps, alerts, TTS)

Routing: selected source -> PipeWire mixer -> EQ -> DAC -> amplifier
"""

from enum import Enum
from typing import Any

from src.core.event_bus import EventBus
from src.core.logger import get_logger

log = get_logger("audio.source")


class AudioSource(Enum):
    """Available audio sources."""
    ANDROID_AUTO = "android_auto"
    BLUETOOTH = "bluetooth"
    FM_RADIO = "fm_radio"
    SYSTEM = "system"


# Display names for UI
SOURCE_LABELS = {
    AudioSource.ANDROID_AUTO: "Android Auto",
    AudioSource.BLUETOOTH: "BT Audio",
    AudioSource.FM_RADIO: "FM Radio",
    AudioSource.SYSTEM: "System",
}

# Ordered list for cycling through sources
SOURCE_ORDER = [
    AudioSource.ANDROID_AUTO,
    AudioSource.BLUETOOTH,
    AudioSource.FM_RADIO,
]


class SourceManager:
    """Manages audio source selection and switching.

    Publishes events:
        - audio.source_changed: current AudioSource value string
        - audio.source_label: display label for status bar
    """

    def __init__(self, event_bus: EventBus):
        self._event_bus = event_bus
        self._current = AudioSource.BLUETOOTH
        self._available: set[AudioSource] = {
            AudioSource.BLUETOOTH,
            AudioSource.SYSTEM,
        }

        # Subscribe to source availability events
        self._event_bus.subscribe("audio.source_available", self._on_source_available)
        self._event_bus.subscribe("input.media_button", self._on_media_button)

        log.info("SourceManager initialized (default: %s)", self._current.value)

    @property
    def current(self) -> AudioSource:
        return self._current

    @property
    def current_label(self) -> str:
        return SOURCE_LABELS.get(self._current, "Unknown")

    @property
    def available_sources(self) -> list[AudioSource]:
        return [s for s in SOURCE_ORDER if s in self._available]

    def switch_to(self, source: AudioSource) -> bool:
        """Switch to a specific audio source.

        Args:
            source: Target audio source.

        Returns:
            True if switch was successful.
        """
        if source not in self._available and source != AudioSource.SYSTEM:
            log.warning("Source %s not available", source.value)
            return False

        prev = self._current
        self._current = source

        log.info("Audio source: %s -> %s", prev.value, source.value)
        self._event_bus.publish("audio.source_changed", source.value)
        self._event_bus.publish("audio.source_label", self.current_label)

        return True

    def cycle_next(self) -> AudioSource:
        """Cycle to the next available source.

        Returns:
            The new active source.
        """
        available = self.available_sources
        if not available:
            return self._current

        try:
            idx = available.index(self._current)
            next_idx = (idx + 1) % len(available)
        except ValueError:
            next_idx = 0

        self.switch_to(available[next_idx])
        return self._current

    def add_source(self, source: AudioSource) -> None:
        """Mark a source as available."""
        if source not in self._available:
            self._available.add(source)
            log.info("Source now available: %s", source.value)

    def remove_source(self, source: AudioSource) -> None:
        """Mark a source as unavailable."""
        self._available.discard(source)
        if self._current == source:
            # Fall back to bluetooth or first available
            fallback = AudioSource.BLUETOOTH if AudioSource.BLUETOOTH in self._available else None
            if fallback:
                self.switch_to(fallback)
            elif self._available:
                self.switch_to(next(iter(self._available)))

    def _on_source_available(self, topic: str, value: Any, timestamp: float) -> None:
        """Handle source availability events."""
        if isinstance(value, dict):
            source_name = value.get("source")
            available = value.get("available", True)
            try:
                source = AudioSource(source_name)
                if available:
                    self.add_source(source)
                else:
                    self.remove_source(source)
            except ValueError:
                log.warning("Unknown source: %s", source_name)

    def _on_media_button(self, topic: str, value: Any, timestamp: float) -> None:
        """Handle media button press — cycle to next source."""
        self.cycle_next()
