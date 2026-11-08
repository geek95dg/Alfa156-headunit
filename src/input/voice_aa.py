"""Voice-AA handler — the steering-wheel / dashboard voice button.

``input.voice_aa_trigger`` (SWC VOICE, F7) -> ``aa.voice_trigger`` True ->
web_viewer presses Android Auto's voice control on the AA display. How it
presses is ``multimedia.aa_voice_method``:

* ``key`` — ``xdotool key --clearmodifiers m`` on :99. openDsh's InputDevice
  maps Qt::Key_M to the MICROPHONE_1 button (forwarded only when
  openauto.ini enables VoiceCommandButton). Every press sends the key; a
  second press lets AA itself toggle/cancel the assistant, so BCM keeps no
  "listening" state that could disagree with the phone.
* ``tap`` (code default, the old behaviour) — a tap on the mic icon. A
  listening window of ``audio.voice_listen_sec`` is tracked; a second press
  inside it taps again (AA toggles listening off) and ends the window, so
  the next press starts a fresh one. Previously the second press only
  flipped BCM's own flag: nothing reached AA, the assistant kept listening,
  and BCM believed it had stopped. A timer generation counter also keeps a
  late timer of an old window from ending a new one.

No microphone: when the mic router reports ``audio.mic_state`` ``none`` and
``audio.voice_require_mic`` is true, the press does NOT reach AA — the
assistant with nothing to record only ever hung — and the dashboard shows
"Brak mikrofonu – sterowanie głosowe wyłączone" instead. With the router
disabled (no mic state at all) presses behave as before.

``audio.duck`` used to be published here; nothing consumed it, and ducking
around the assistant would also duck the assistant's own voice. Removed.
"""

import threading
from typing import Any, Callable

from src.core.event_bus import EventBus
from src.core.logger import get_logger
from src.core.notifications import publish_notification

log = get_logger("input.voice_aa")

VOICE_METHODS = ("key", "tap")
DEFAULT_VOICE_METHOD = "tap"

NO_MIC_TITLE = "Brak mikrofonu – sterowanie głosowe wyłączone"
NO_MIC_DESC = "Podłącz mikrofon i wpisz go w audio.mic_phone (config/local.yaml)."


def voice_method(config: Any) -> str:
    """``multimedia.aa_voice_method`` normalised to ``key`` | ``tap``."""
    value = DEFAULT_VOICE_METHOD
    if config is not None:
        value = str(config.get("multimedia.aa_voice_method", DEFAULT_VOICE_METHOD)
                    or DEFAULT_VOICE_METHOD).strip().lower()
    return value if value in VOICE_METHODS else DEFAULT_VOICE_METHOD


def _positive(value: Any, default: float) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


class VoiceAAHandler:

    def __init__(self, config, event_bus: EventBus,
                 timer_factory: Callable[..., Any] = threading.Timer):
        self._bus = event_bus
        self._config = config
        self._timer_factory = timer_factory
        self._active = False
        self._lock = threading.Lock()
        self._timer = None
        # Bumped for every listening window; a timer only ends its own.
        self._generation = 0
        get = config.get if config is not None else (lambda key, default=None: default)
        self._timeout = _positive(get("audio.voice_listen_sec", 8), 8.0)
        self._require_mic = bool(get("audio.voice_require_mic", True))
        method = str(get("multimedia.aa_voice_method", DEFAULT_VOICE_METHOD) or "").strip().lower()
        if method and method not in VOICE_METHODS:
            log.warning("multimedia.aa_voice_method=%r not understood — using %s",
                        method, DEFAULT_VOICE_METHOD)
        self._method = voice_method(config)
        event_bus.subscribe("input.voice_aa_trigger", self._on_trigger)
        log.info("VoiceAAHandler ready (method=%s, window=%ss, require_mic=%s)",
                 self._method, self._timeout, self._require_mic)

    @property
    def active(self) -> bool:
        return self._active

    # ── trigger ───────────────────────────────────────────────────────────

    def _mic_missing(self) -> bool:
        """True only when the mic router positively reports no microphone."""
        if not self._require_mic:
            return False
        last = self._bus.get_last("audio.mic_state")
        state = last[0] if last else None
        return isinstance(state, dict) and state.get("state") == "none"

    def _on_trigger(self, topic: str, value, timestamp: float) -> None:
        if self._mic_missing():
            log.info("Voice-AA: no microphone — not triggering the assistant")
            publish_notification(self._bus, NO_MIC_TITLE, NO_MIC_DESC,
                                 severity="warning", icon="mic_off",
                                 key="voice_no_mic")
            return

        if self._method == "key":
            # Stateless: AA toggles/cancels on a repeated press by itself.
            log.info("Voice-AA: voice key press")
            self._bus.publish("aa.voice_trigger", True)
            return

        with self._lock:
            if self._active:
                # Second press inside the window: tap again so AA stops
                # listening, and end our window to match.
                self._end_window()
                again = True
            else:
                self._start_window()
                again = False
        if again:
            log.info("Voice-AA: second press — tapping again (AA toggles), window closed")
        else:
            log.info("Voice-AA activated (window %ss)", self._timeout)
        self._bus.publish("aa.voice_trigger", True)

    # ── tap-method listening window ───────────────────────────────────────

    def _start_window(self) -> None:
        """Caller holds the lock."""
        self._active = True
        self._generation += 1
        generation = self._generation
        timer = self._timer_factory(self._timeout, self._timeout_deactivate,
                                    args=(generation,))
        timer.daemon = True
        self._timer = timer
        timer.start()

    def _end_window(self) -> None:
        """Caller holds the lock."""
        self._active = False
        self._generation += 1
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _timeout_deactivate(self, generation: int = None) -> None:
        with self._lock:
            if not self._active or (generation is not None and generation != self._generation):
                return  # a newer window owns the state
            self._end_window()
        log.info("Voice-AA window ended after %ss", self._timeout)
        # False = "window closed" (web_viewer only acts on True).
        self._bus.publish("aa.voice_trigger", False)
