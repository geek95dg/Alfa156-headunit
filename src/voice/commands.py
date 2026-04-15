"""Command grammar and dispatch to BCM modules.

Maps recognized voice commands to event bus actions.
Handles fuzzy matching for robustness against recognition errors.
"""

from typing import Any, Optional

from src.core.event_bus import EventBus
from src.core.logger import get_logger
from src.voice.languages import get_commands, get_response, LANGUAGES

log = get_logger("voice.commands")


def _similarity(a: str, b: str) -> float:
    """Simple word-overlap similarity (0.0 to 1.0)."""
    words_a = set(a.lower().split())
    words_b = set(b.lower().split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    return len(intersection) / max(len(words_a), len(words_b))


FUZZY_THRESHOLD = 0.6  # Minimum similarity to accept a command


class CommandDispatcher:
    """Matches recognized speech to commands and dispatches actions.

    Supports exact match and fuzzy matching for robustness.
    Publishes the matched action to the event bus.
    """

    def __init__(self, event_bus: EventBus, tts: Any, lang_code: str = "en"):
        self._event_bus = event_bus
        self._tts = tts
        self._lang_code = lang_code
        self._commands = get_commands(lang_code)

        self._event_bus.subscribe("voice.language_changed", self._on_language_changed)

    @property
    def language(self) -> str:
        return self._lang_code

    def dispatch(self, text: str) -> Optional[str]:
        """Match text to a command and dispatch the action.

        Args:
            text: Recognized command text (lowercased).

        Returns:
            The action event name if matched, None otherwise.
        """
        text = text.lower().strip()

        # Try exact match first
        action = self._commands.get(text)
        if action:
            log.info("Exact match: '%s' → %s", text, action)
            self._execute(action)
            return action

        # Try fuzzy match
        best_match = None
        best_score = 0.0
        for phrase, act in self._commands.items():
            score = _similarity(text, phrase)
            if score > best_score:
                best_score = score
                best_match = act

        if best_match and best_score >= FUZZY_THRESHOLD:
            log.info("Fuzzy match (%.0f%%): '%s' → %s", best_score * 100, text, best_match)
            self._execute(best_match)
            return best_match

        log.warning("No match for: '%s' (best score: %.0f%%)", text, best_score * 100)
        if self._tts:
            self._tts.respond("command_unknown")
        return None

    def _execute(self, action: str) -> None:
        """Publish the action event and give TTS feedback."""
        # Special handling for volume commands (pass step value)
        if action in ("input.volume_up", "input.volume_down"):
            self._event_bus.publish(action, 10)  # 10% step for voice
        else:
            self._event_bus.publish(action, True)

        if self._tts:
            self._tts.respond("command_ok")

    def _on_language_changed(self, topic: str, value: Any, timestamp: float) -> None:
        if isinstance(value, str) and value in ("pl", "en"):
            self._lang_code = value
            self._commands = get_commands(value)
            log.info("Command language changed to: %s", value)
