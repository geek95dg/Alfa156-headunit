"""Volume control — master and per-source volume management.

Handles volume up/down from BT remote and rotary encoder inputs.
Publishes volume changes to event bus for status bar display.

Also serves as the module entry point (start_audio) called from main.py.
"""

from typing import Any

from src.core.event_bus import EventBus
from src.core.logger import get_logger
from src.audio.pipewire_ctrl import PipeWireController
from src.audio.source_manager import SourceManager
from src.audio.ducking import DuckingManager

log = get_logger("audio.volume")

VOLUME_STEP = 5    # Percentage per step
VOLUME_MIN = 0
VOLUME_MAX = 100


class VolumeController:
    """Master volume control with event bus integration.

    Subscribes to:
        - input.volume_up: increase volume by VOLUME_STEP
        - input.volume_down: decrease volume by VOLUME_STEP

    Publishes:
        - audio.volume: current volume percentage (0-100)
    """

    def __init__(self, pipewire: PipeWireController, event_bus: EventBus,
                 initial_volume: int = 70):
        self._pw = pipewire
        self._event_bus = event_bus
        self._volume = max(VOLUME_MIN, min(VOLUME_MAX, initial_volume))

        # Subscribe to input events
        self._event_bus.subscribe("input.volume_up", self._on_volume_up)
        self._event_bus.subscribe("input.volume_down", self._on_volume_down)

        # Set initial volume
        self._pw.set_volume(self._volume)
        self._event_bus.publish("audio.volume", self._volume)

        log.info("VolumeController initialized at %d%%", self._volume)

    def _on_volume_up(self, topic: str, value: Any, timestamp: float) -> None:
        step = value if isinstance(value, int) else VOLUME_STEP
        self.set_volume(self._volume + step)

    def _on_volume_down(self, topic: str, value: Any, timestamp: float) -> None:
        step = value if isinstance(value, int) else VOLUME_STEP
        self.set_volume(self._volume - step)

    def set_volume(self, volume: int) -> None:
        """Set master volume (0-100)."""
        volume = max(VOLUME_MIN, min(VOLUME_MAX, volume))
        if volume == self._volume:
            return

        self._volume = volume
        self._pw.set_volume(volume)
        self._event_bus.publish("audio.volume", volume)
        log.info("Volume: %d%%", volume)

    @property
    def volume(self) -> int:
        return self._volume

    def mute(self) -> None:
        """Mute audio output."""
        self._pw.set_mute(True)
        log.info("Audio muted")

    def unmute(self) -> None:
        """Unmute audio output."""
        self._pw.set_mute(False)
        log.info("Audio unmuted")


def start_audio(config: Any, event_bus: EventBus, hal: Any = None,
                **kwargs) -> None:
    """Entry point called from main.py to start the audio module.

    Initializes PipeWire controller, source manager, ducking, and volume.
    """
    # PipeWire controller
    pw = PipeWireController(config, event_bus)

    # Source manager
    source_mgr = SourceManager(event_bus)

    # Ducking manager
    ducking = DuckingManager(event_bus)

    # Volume controller
    initial_vol = config.get("audio.master_volume", 70)
    volume = VolumeController(pw, event_bus, initial_volume=initial_vol)

    # Apply initial EQ preset
    eq_preset = config.get("audio.eq_preset", "flat")
    pw.apply_eq_preset(eq_preset)

    log.info("Audio module running (PipeWire %s)",
             "active" if pw.available else "simulated")

    # Store references for cleanup
    event_bus.publish("audio._internals", {
        "pipewire": pw,
        "source_manager": source_mgr,
        "ducking": ducking,
        "volume": volume,
    })
