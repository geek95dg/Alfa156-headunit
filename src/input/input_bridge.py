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
"""

from typing import Any

from src.core.event_bus import EventBus
from src.core.logger import get_logger

log = get_logger("input.bridge")


class InputBridge:
    """Route SWC action topics without a native consumer to real handlers."""

    def __init__(self, event_bus: EventBus):
        self._event_bus = event_bus
        event_bus.subscribe("input.next_track", self._on_next)
        event_bus.subscribe("input.prev_track", self._on_prev)
        event_bus.subscribe("input.phone_pickup", self._on_pickup)
        event_bus.subscribe("input.phone_hangup", self._on_hangup)
        log.info("InputBridge initialized (media skip + HFP answer/hangup)")

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
