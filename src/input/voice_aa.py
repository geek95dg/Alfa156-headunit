"""Voice-AA handler — duck audio, tap the AA mic icon, unduck on timeout.

When the SWC voice button is pressed, BCM:
1. Ducks audio to a configurable % of normal volume
2. Sends a synthetic tap to the AA microphone icon via /aa/touch
3. Auto-unducks after a timeout (default 8s)

Pressing the button again while active cancels early.
"""

import threading

from src.core.event_bus import EventBus
from src.core.logger import get_logger

log = get_logger("input.voice_aa")


class VoiceAAHandler:

    def __init__(self, config, event_bus: EventBus):
        self._bus = event_bus
        self._active = False
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self._duck_pct = config.get("audio.voice_duck_pct", 40)
        self._timeout = config.get("audio.voice_listen_sec", 8)
        event_bus.subscribe("input.voice_aa_trigger", self._on_trigger)
        log.info("VoiceAAHandler ready (duck=%d%%, timeout=%ds)",
                 self._duck_pct, self._timeout)

    def _on_trigger(self, topic: str, value, timestamp: float) -> None:
        with self._lock:
            if self._active:
                self._deactivate()
            else:
                self._activate()

    def _activate(self) -> None:
        self._active = True
        self._bus.publish("audio.duck", self._duck_pct)
        self._bus.publish("aa.voice_trigger", True)
        log.info("Voice-AA activated (ducked to %d%%)", self._duck_pct)
        self._timer = threading.Timer(self._timeout, self._timeout_deactivate)
        self._timer.daemon = True
        self._timer.start()

    def _deactivate(self) -> None:
        self._active = False
        if self._timer:
            self._timer.cancel()
            self._timer = None
        self._bus.publish("audio.duck", 0)
        self._bus.publish("aa.voice_trigger", False)
        log.info("Voice-AA deactivated")

    def _timeout_deactivate(self) -> None:
        with self._lock:
            if self._active:
                log.info("Voice-AA auto-deactivating after %ds timeout",
                         self._timeout)
                self._deactivate()
