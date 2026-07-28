"""Volume control — master and per-source volume management.

Handles volume up/down from BT remote and SWC button inputs.
Publishes volume changes to event bus for status bar display.

Also serves as the module entry point (start_audio) called from main.py.
"""

from typing import Any

from src.core.event_bus import EventBus
from src.core.logger import get_logger
from src.audio.pipewire_ctrl import PipeWireController
from src.audio.source_manager import SourceManager
from src.audio.ducking import DuckingManager
from src.audio.spectrum import SpectrumAnalyzer

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
    # PipeWire controller.
    #
    # Order below is deliberate. start_output() waits for PipeWire, picks the
    # hardware sink, unmutes it and only then brings the EQ chain up pinned to
    # it. It has to run BEFORE VolumeController, which sets the initial level
    # on whatever is default at that moment — previously the EQ routing thread
    # was still racing and the level often landed on the wrong node.
    #
    # The constructor no longer applies the preset by itself; before v8.5.3 it
    # did, and start_audio() applied it a second time, so two routing threads
    # fought over the default sink.
    pw = PipeWireController(config, event_bus)
    pw.start_output()

    # Source manager
    source_mgr = SourceManager(event_bus)

    # Ducking manager
    ducking = DuckingManager(event_bus)

    # Volume controller
    initial_vol = config.get("audio.master_volume", 70)
    volume = VolumeController(pw, event_bus, initial_volume=initial_vol)

    # Nothing in the startup path used to unmute, so a card that came up muted
    # (a fresh Realtek usually does) stayed muted forever.
    volume.unmute()

    # Spectrum analyzer
    spectrum_enabled = config.get("audio.spectrum_enabled", True)
    spectrum = None
    if spectrum_enabled:
        spectrum = SpectrumAnalyzer(event_bus)
        spectrum.start()

    # Hand the output back and kill the filter-chain child on the way out.
    def _on_shutdown(topic: str, value: Any, timestamp: float) -> None:
        pw.stop()
        if spectrum is not None:
            spectrum.stop()

    event_bus.subscribe("power.shutting_down", _on_shutdown)

    log.info("Audio module running (PipeWire %s, output=%s)",
             "active" if pw.available else "simulated",
             pw.hardware_sink or "unknown")

    # Store references for cleanup
    event_bus.publish("audio._internals", {
        "pipewire": pw,
        "source_manager": source_mgr,
        "ducking": ducking,
        "volume": volume,
        "spectrum": spectrum,
    })
