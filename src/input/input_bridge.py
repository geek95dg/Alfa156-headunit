"""Bridge SWC action topics to the subsystems that actually act on them.

`action_dispatch.py` turns Arduino keycodes into `input.*` topics, but a few
of those topics historically had **no subscriber**, so the steering-wheel
buttons did nothing:

    input.next_track / input.prev_track  → AVRCP media skip (bt.cmd.media)
    input.phone_pickup / input.phone_hangup → HFP answer/hangup (bt.cmd.*)

(`input.volume_up/down` and `input.mute` are handled by VolumeController;
`input.voice_aa_trigger` by VoiceAAHandler; `input.navigate_aa`/`input.home`
by the web UI via the dashboard payload.)

This bridge just republishes the orphaned topics onto the topics their
owners already listen on. Instantiated from `bt_remote.start_input()`.

The SWC action ``crash_cancel`` has no keycode of its own (the Arduino
sends fixed keycodes per button): a press of a button that ``swc.mapping``
maps to it publishes ``crash.cmd.cancel {"source": "swc"}``. The button
keeps its fixed action too (ActionDispatcher), so it is also pressed for
other reasons — src/safety/crash_sms.py therefore takes it ONLY while a
crash SMS countdown runs (armed/pending with time left): never while the
SMS is being sent and never as the "Jestem OK" follow-up after it went out
(that would send "ODWOLANE..." to everybody). The mapping is read at every
press, so a change in Settings → SWC works at once. Never anything that
dials (plan H: no SWC action calls 112).
"""

from typing import Any, Optional

from src.core.event_bus import EventBus
from src.core.logger import get_logger

log = get_logger("input.bridge")


class InputBridge:
    """Route SWC action topics without a native consumer to real handlers."""

    def __init__(self, event_bus: EventBus, config: Optional[Any] = None):
        self._event_bus = event_bus
        self._config = config
        event_bus.subscribe("input.next_track", self._on_next)
        event_bus.subscribe("input.prev_track", self._on_prev)
        event_bus.subscribe("input.phone_pickup", self._on_pickup)
        event_bus.subscribe("input.phone_hangup", self._on_hangup)
        event_bus.subscribe("input.raw_keycode", self._on_raw_keycode)
        log.info("InputBridge initialized (media skip + HFP answer/hangup + crash_cancel)")

    def _on_raw_keycode(self, topic: str, value: Any, timestamp: float) -> None:
        """A SWC button mapped to ``crash_cancel`` → ``crash.cmd.cancel``."""
        if isinstance(value, bool) or not isinstance(value, int):
            return
        from src.input.swc_remote import KEYCODE_TO_BUTTON, build_button_to_action_map
        buttons = KEYCODE_TO_BUTTON.get(value)
        if not buttons:
            return
        try:
            mapping = build_button_to_action_map(self._config)
        except Exception:
            log.debug("swc.mapping unreadable", exc_info=True)
            return
        if any(mapping.get(b) == "crash_cancel" for b in buttons):
            self._event_bus.publish("crash.cmd.cancel", {"source": "swc"})

    # AVRCP media skip — BluetoothManager._on_cmd_media accepts these strings.
    def _on_next(self, topic: str, value: Any, timestamp: float) -> None:
        self._event_bus.publish("bt.cmd.media", "next")

    def _on_prev(self, topic: str, value: Any, timestamp: float) -> None:
        self._event_bus.publish("bt.cmd.media", "previous")

    # HFP call control — BluetoothManager subscribes to bt.cmd.answer/hangup.
    def _on_pickup(self, topic: str, value: Any, timestamp: float) -> None:
        self._event_bus.publish("bt.cmd.answer", True)

    def _on_hangup(self, topic: str, value: Any, timestamp: float) -> None:
        self._event_bus.publish("bt.cmd.hangup", True)
