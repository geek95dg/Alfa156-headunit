"""Wake word detection — activates voice command listening window.

Monitors continuous Vosk recognition output for the wake word.
When detected, opens a 5-second listening window for commands.
"""

import time
from typing import Any, Callable, Optional

from src.core.event_bus import EventBus
from src.core.logger import get_logger
from src.voice.languages import get_wake_word

log = get_logger("voice.wake_word")

LISTEN_WINDOW_SECONDS = 5.0


class WakeWordDetector:
    """Detects wake word in recognized text and manages listening window.

    The detector is fed partial/final recognition results. When the
    wake word is found, it activates a listening window and publishes
    a 'voice.wake_detected' event.
    """

    def __init__(self, event_bus: EventBus, lang_code: str = "en"):
        self._event_bus = event_bus
        self._lang_code = lang_code
        self._wake_word = get_wake_word(lang_code)
        self._listening = False
        self._listen_until: float = 0.0
        self._on_command_callback: Optional[Callable[[str], None]] = None

        self._event_bus.subscribe("voice.language_changed", self._on_language_changed)

    @property
    def wake_word(self) -> str:
        return self._wake_word

    @property
    def is_listening(self) -> bool:
        """True if we're in the command listening window."""
        if self._listening and time.monotonic() > self._listen_until:
            self._listening = False
            self._event_bus.publish("voice.listen_timeout", True)
            log.debug("Listening window expired")
        return self._listening

    def set_command_callback(self, callback: Callable[[str], None]) -> None:
        """Set callback for when text is received during listening window."""
        self._on_command_callback = callback

    def feed_text(self, text: str) -> bool:
        """Feed recognized text for wake word / command detection.

        Args:
            text: Recognized text from Vosk (lowercased).

        Returns:
            True if wake word was detected or command was captured.
        """
        text_lower = text.lower().strip()
        if not text_lower:
            return False

        # Check if we're in listening window
        if self.is_listening:
            # Remove wake word from text if it's repeated
            command_text = text_lower.replace(self._wake_word, "").strip()
            if command_text:
                log.info("Command captured: '%s'", command_text)
                if self._on_command_callback:
                    self._on_command_callback(command_text)
                self._listening = False
                return True
            return False

        # Check for wake word
        if self._wake_word in text_lower:
            self._activate_listening()
            # Check if command follows wake word in same utterance
            after_wake = text_lower.split(self._wake_word, 1)[-1].strip()
            if after_wake and self._on_command_callback:
                self._on_command_callback(after_wake)
                self._listening = False
            return True

        return False

    def _activate_listening(self) -> None:
        """Open the listening window."""
        self._listening = True
        self._listen_until = time.monotonic() + LISTEN_WINDOW_SECONDS
        self._event_bus.publish("voice.wake_detected", True)
        log.info("Wake word detected — listening for %ds", LISTEN_WINDOW_SECONDS)

    def cancel_listening(self) -> None:
        """Cancel the current listening window."""
        self._listening = False
        self._event_bus.publish("voice.listen_cancelled", True)

    def _on_language_changed(self, topic: str, value: Any, timestamp: float) -> None:
        if isinstance(value, str) and value in ("pl", "en"):
            self._lang_code = value
            self._wake_word = get_wake_word(value)
            log.info("Wake word changed to: '%s'", self._wake_word)
