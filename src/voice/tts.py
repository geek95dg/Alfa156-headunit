"""Text-to-speech engine for voice announcements.

Uses pyttsx3 for offline TTS. Falls back to logging if pyttsx3 unavailable.
Triggers audio ducking before speaking and releases after.
"""

import threading
from typing import Any, Optional

from src.core.event_bus import EventBus
from src.core.logger import get_logger
from src.voice.languages import get_announcement, get_response

log = get_logger("voice.tts")

try:
    import pyttsx3
    _TTS_AVAILABLE = True
except ImportError:
    _TTS_AVAILABLE = False
    log.warning("pyttsx3 not installed — TTS will be simulated")


class TTSEngine:
    """Text-to-speech engine with audio ducking integration.

    Speaks announcements and responses in the active language.
    Triggers audio.voice_announcement events for ducking.
    """

    def __init__(self, event_bus: EventBus, lang_code: str = "en"):
        self._event_bus = event_bus
        self._lang_code = lang_code
        self._engine: Optional[Any] = None
        self._lock = threading.Lock()
        self._speaking = False

        if _TTS_AVAILABLE:
            try:
                self._engine = pyttsx3.init()
                self._engine.setProperty("rate", 160)
                self._engine.setProperty("volume", 0.9)
                log.info("TTS engine initialized")
            except Exception as e:
                log.warning("TTS init failed: %s", e)
                self._engine = None

        # Subscribe to language change events
        self._event_bus.subscribe("voice.language_changed", self._on_language_changed)

        # Subscribe to BCM alert events for voice announcements
        self._event_bus.subscribe("env.icing_warning", self._on_icing_warning)
        self._event_bus.subscribe("env.overheat_warning", self._on_overheat_warning)
        self._event_bus.subscribe("obd.low_fuel", self._on_low_fuel)
        self._event_bus.subscribe("service.reminder", self._on_service_reminder)

    @property
    def language(self) -> str:
        return self._lang_code

    @language.setter
    def language(self, code: str) -> None:
        self._lang_code = code

    def speak(self, text: str) -> None:
        """Speak text asynchronously with audio ducking.

        Args:
            text: The text to speak.
        """
        thread = threading.Thread(target=self._speak_sync, args=(text,), daemon=True)
        thread.start()

    def _speak_sync(self, text: str) -> None:
        """Speak text synchronously (runs in background thread)."""
        with self._lock:
            self._speaking = True
            # Trigger ducking
            self._event_bus.publish("audio.voice_announcement", True)

            log.info("TTS: %s", text)

            if self._engine is not None:
                try:
                    self._engine.say(text)
                    self._engine.runAndWait()
                except Exception as e:
                    log.error("TTS speak failed: %s", e)
            else:
                log.debug("TTS (simulated): %s", text)

            # Release ducking
            self._speaking = False
            self._event_bus.publish("audio.voice_announcement", False)

    def announce(self, key: str) -> None:
        """Speak a predefined announcement by key.

        Args:
            key: Announcement key (e.g. 'icing_warning', 'low_fuel').
        """
        text = get_announcement(self._lang_code, key)
        self.speak(text)

    def respond(self, key: str) -> None:
        """Speak a predefined response by key.

        Args:
            key: Response key (e.g. 'wake_ack', 'command_ok').
        """
        text = get_response(self._lang_code, key)
        self.speak(text)

    # --- BCM alert event handlers ---

    def _on_icing_warning(self, topic: str, value: Any, timestamp: float) -> None:
        if value:
            self.announce("icing_warning")

    def _on_overheat_warning(self, topic: str, value: Any, timestamp: float) -> None:
        if value:
            self.announce("engine_overheat")

    def _on_low_fuel(self, topic: str, value: Any, timestamp: float) -> None:
        if value:
            self.announce("low_fuel")

    def _on_service_reminder(self, topic: str, value: Any, timestamp: float) -> None:
        if value:
            self.announce("service_reminder")

    def _on_language_changed(self, topic: str, value: Any, timestamp: float) -> None:
        if isinstance(value, str) and value in ("pl", "en"):
            self._lang_code = value
            log.info("TTS language changed to: %s", value)
