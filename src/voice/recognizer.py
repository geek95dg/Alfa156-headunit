"""Vosk speech recognizer — microphone capture and continuous recognition.

Uses Vosk for offline speech recognition. Falls back to simulation
mode if Vosk or audio input is not available (e.g., x86 without mic).

Entry point: start_voice() is called from main.py.
"""

import json
import threading
from pathlib import Path
from typing import Any, Optional

from src.core.event_bus import EventBus
from src.core.logger import get_logger
from src.voice.languages import get_language, LANGUAGES
from src.voice.wake_word import WakeWordDetector
from src.voice.commands import CommandDispatcher
from src.voice.tts import TTSEngine

log = get_logger("voice.recognizer")

# Vosk models are expected in src/voice/models/
MODELS_DIR = Path(__file__).parent / "models"

try:
    import vosk
    _VOSK_AVAILABLE = True
except ImportError:
    _VOSK_AVAILABLE = False
    log.info("Vosk not installed — voice recognition will be simulated")

try:
    import sounddevice as sd
    _AUDIO_AVAILABLE = True
except (ImportError, OSError):
    _AUDIO_AVAILABLE = False
    log.info("sounddevice not available — microphone capture disabled")

SAMPLE_RATE = 16000
BLOCK_SIZE = 4000  # ~250ms at 16kHz


class VoskRecognizer:
    """Continuous speech recognizer using Vosk.

    Captures audio from USB microphone, runs through Vosk model,
    and feeds results to WakeWordDetector and CommandDispatcher.
    """

    def __init__(self, event_bus: EventBus, lang_code: str = "en"):
        self._event_bus = event_bus
        self._lang_code = lang_code
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._model: Optional[Any] = None
        self._recognizer: Optional[Any] = None

        # Sub-components
        self._tts = TTSEngine(event_bus, lang_code)
        self._wake = WakeWordDetector(event_bus, lang_code)
        self._dispatcher = CommandDispatcher(event_bus, self._tts, lang_code)

        # Wire up wake word → command dispatch
        self._wake.set_command_callback(self._on_command)

        # Subscribe to language toggle
        self._event_bus.subscribe("voice.cmd.change_language", self._on_toggle_language)

        # Try to load Vosk model
        self._load_model()

    @property
    def available(self) -> bool:
        return _VOSK_AVAILABLE and _AUDIO_AVAILABLE and self._model is not None

    @property
    def running(self) -> bool:
        return self._running

    @property
    def language(self) -> str:
        return self._lang_code

    @property
    def tts(self) -> TTSEngine:
        return self._tts

    @property
    def wake_detector(self) -> WakeWordDetector:
        return self._wake

    @property
    def dispatcher(self) -> CommandDispatcher:
        return self._dispatcher

    def _load_model(self) -> None:
        """Load the Vosk model for the current language."""
        if not _VOSK_AVAILABLE:
            return

        lang_def = get_language(self._lang_code)
        model_name = lang_def["vosk_model"]
        model_path = MODELS_DIR / model_name

        if model_path.exists():
            try:
                vosk.SetLogLevel(-1)  # Suppress verbose Vosk logs
                self._model = vosk.Model(str(model_path))
                self._recognizer = vosk.KaldiRecognizer(self._model, SAMPLE_RATE)
                log.info("Vosk model loaded: %s", model_name)
            except Exception as e:
                log.error("Failed to load Vosk model: %s", e)
                self._model = None
        else:
            log.warning("Vosk model not found at %s — download required", model_path)

    def start(self) -> None:
        """Start continuous recognition in a background thread."""
        if self._running:
            return

        self._running = True

        if self.available:
            self._thread = threading.Thread(target=self._recognition_loop, daemon=True)
            self._thread.start()
            log.info("Voice recognition started (lang=%s)", self._lang_code)
        else:
            log.info("Voice recognition in simulation mode (lang=%s)", self._lang_code)

        self._event_bus.publish("voice.status", "running")

    def stop(self) -> None:
        """Stop recognition."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._event_bus.publish("voice.status", "stopped")
        log.info("Voice recognition stopped")

    def _recognition_loop(self) -> None:
        """Main recognition loop — captures audio and feeds to Vosk."""
        try:
            with sd.RawInputStream(
                samplerate=SAMPLE_RATE,
                blocksize=BLOCK_SIZE,
                dtype="int16",
                channels=1,
            ) as stream:
                log.info("Microphone stream opened")
                while self._running:
                    data, overflowed = stream.read(BLOCK_SIZE)
                    if overflowed:
                        log.debug("Audio buffer overflow")

                    if self._recognizer.AcceptWaveform(bytes(data)):
                        result = json.loads(self._recognizer.Result())
                        text = result.get("text", "")
                        if text:
                            self._on_recognition(text)
                    else:
                        partial = json.loads(self._recognizer.PartialResult())
                        partial_text = partial.get("partial", "")
                        if partial_text:
                            self._on_partial(partial_text)

        except Exception as e:
            log.error("Recognition loop error: %s", e)
            self._running = False

    def _on_recognition(self, text: str) -> None:
        """Handle final recognition result."""
        log.debug("Recognized: '%s'", text)
        self._event_bus.publish("voice.recognized", text)
        self._wake.feed_text(text)

    def _on_partial(self, text: str) -> None:
        """Handle partial recognition result — check for wake word."""
        self._wake.feed_text(text)

    def _on_command(self, command_text: str) -> None:
        """Handle command text from wake word detector."""
        self._dispatcher.dispatch(command_text)

    def _on_toggle_language(self, topic: str, value: Any, timestamp: float) -> None:
        """Toggle between PL and EN."""
        new_lang = "en" if self._lang_code == "pl" else "pl"
        self._lang_code = new_lang
        self._event_bus.publish("voice.language_changed", new_lang)
        log.info("Language toggled to: %s", new_lang)

        # Reload model for new language
        self._load_model()

    def simulate_input(self, text: str) -> None:
        """Simulate voice input for testing (x86 dev mode)."""
        log.debug("Simulated input: '%s'", text)
        self._on_recognition(text)


def start_voice(config: Any, event_bus: EventBus, hal: Any = None,
                **kwargs) -> None:
    """Entry point called from main.py to start the voice module."""
    lang_code = config.get("voice.language", "en")
    recognizer = VoskRecognizer(event_bus, lang_code)
    recognizer.start()

    log.info("Voice module running (lang=%s, vosk=%s)",
             lang_code, "active" if recognizer.available else "simulated")

    event_bus.publish("voice._internals", {
        "recognizer": recognizer,
        "tts": recognizer.tts,
        "wake_detector": recognizer.wake_detector,
        "dispatcher": recognizer.dispatcher,
    })
