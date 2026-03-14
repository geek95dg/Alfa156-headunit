"""PipeWire control interface — route sources to DAC, manage EQ profiles.

Uses pw-cli / pw-link / wpctl command-line tools to control PipeWire.
On x86: uses default sound card (laptop/desktop speakers).
On OPi: targets USB DAC (PCM5102A) as default sink.

Audio hardware chain:
  PCM5102A USB DAC → RCA → TDA7388 4ch Class AB amp (4×41W) → front/rear speakers
                        └→ TDA2050 mono Class AB amp (32W) → subwoofer
"""

import json
import subprocess
from pathlib import Path
from typing import Any, Optional

from src.core.event_bus import EventBus
from src.core.logger import get_logger

log = get_logger("audio.pipewire")

# EQ preset definitions (10-band parametric)
EQ_PRESETS = {
    "flat": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    "rock": [4, 3, 1, -1, -2, 0, 2, 3, 4, 3],
    "jazz": [3, 2, 1, 2, -1, -1, 0, 1, 2, 3],
    "bass_boost": [6, 5, 4, 2, 0, 0, 0, 0, 0, 0],
    "custom": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
}

# Standard 10-band center frequencies (Hz)
EQ_FREQUENCIES = [31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]


def _run_cmd(cmd: list[str], timeout: float = 5.0) -> tuple[int, str, str]:
    """Run a shell command and return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        return result.returncode, result.stdout, result.stderr
    except FileNotFoundError:
        return -1, "", f"Command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return -2, "", f"Command timed out: {' '.join(cmd)}"


class PipeWireController:
    """Controls PipeWire audio routing and EQ.

    Wraps pw-cli, pw-link, and wpctl for audio management.
    Falls back gracefully if PipeWire is not available (x86 dev without PW).
    """

    def __init__(self, config: Any, event_bus: EventBus):
        self._config = config
        self._event_bus = event_bus
        self._available = False
        self._default_sink: Optional[str] = None
        self._current_eq: str = config.get("audio.eq_preset", "flat")

        # Check if PipeWire is running
        self._check_availability()

    def _check_availability(self) -> None:
        """Check if PipeWire is available and running."""
        rc, out, _ = _run_cmd(["wpctl", "status"])
        if rc == 0:
            self._available = True
            log.info("PipeWire detected and running")
            self._detect_default_sink()
        else:
            self._available = False
            log.warning("PipeWire not available — audio control will be simulated")

    def _detect_default_sink(self) -> None:
        """Detect the default audio sink."""
        rc, out, _ = _run_cmd(["wpctl", "inspect", "@DEFAULT_AUDIO_SINK@"])
        if rc == 0:
            # Parse sink name from output
            for line in out.splitlines():
                if "node.name" in line:
                    self._default_sink = line.split("=")[-1].strip().strip('"')
                    break
            log.info("Default sink: %s", self._default_sink)
        else:
            log.warning("Could not detect default audio sink")

    @property
    def available(self) -> bool:
        return self._available

    @property
    def default_sink(self) -> Optional[str]:
        return self._default_sink

    def set_volume(self, volume_pct: int) -> bool:
        """Set master volume (0-100%).

        Args:
            volume_pct: Volume percentage 0-100.

        Returns:
            True if successful.
        """
        volume_pct = max(0, min(100, volume_pct))
        volume_frac = volume_pct / 100.0

        if not self._available:
            log.debug("Simulated volume: %d%%", volume_pct)
            self._event_bus.publish("audio.volume_changed", volume_pct)
            return True

        rc, _, err = _run_cmd(
            ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{volume_frac:.2f}"]
        )
        if rc == 0:
            log.info("Volume set to %d%%", volume_pct)
            self._event_bus.publish("audio.volume_changed", volume_pct)
            return True
        else:
            log.error("Failed to set volume: %s", err)
            return False

    def get_volume(self) -> int:
        """Get current master volume percentage."""
        if not self._available:
            return self._config.get("audio.master_volume", 70)

        rc, out, _ = _run_cmd(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"])
        if rc == 0:
            # Output format: "Volume: 0.70"
            try:
                vol_str = out.strip().split(":")[-1].strip()
                return int(float(vol_str) * 100)
            except (ValueError, IndexError):
                pass
        return self._config.get("audio.master_volume", 70)

    def set_mute(self, mute: bool) -> bool:
        """Set or unset mute on default sink."""
        if not self._available:
            log.debug("Simulated mute: %s", mute)
            self._event_bus.publish("audio.mute_changed", mute)
            return True

        action = "1" if mute else "0"
        rc, _, err = _run_cmd(
            ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", action]
        )
        if rc == 0:
            self._event_bus.publish("audio.mute_changed", mute)
            return True
        log.error("Failed to set mute: %s", err)
        return False

    def apply_eq_preset(self, preset_name: str) -> bool:
        """Apply an EQ preset.

        Args:
            preset_name: One of: flat, rock, jazz, bass_boost, custom.

        Returns:
            True if successful.
        """
        if preset_name not in EQ_PRESETS:
            log.error("Unknown EQ preset: %s", preset_name)
            return False

        gains = EQ_PRESETS[preset_name]
        self._current_eq = preset_name

        log.info("EQ preset applied: %s %s", preset_name, gains)
        self._event_bus.publish("audio.eq_changed", {
            "preset": preset_name,
            "gains": gains,
            "frequencies": EQ_FREQUENCIES,
        })
        return True

    @property
    def current_eq_preset(self) -> str:
        return self._current_eq

    def list_sinks(self) -> list[dict[str, str]]:
        """List available audio sinks."""
        if not self._available:
            return [{"id": "0", "name": "simulated_sink", "description": "Simulated Output"}]

        sinks = []
        rc, out, _ = _run_cmd(["pw-cli", "list-objects", "Node"])
        if rc == 0:
            # Simplified parsing — in production would use pw-dump JSON
            for line in out.splitlines():
                if "node.name" in line:
                    name = line.split("=")[-1].strip().strip('"')
                    sinks.append({"name": name})
        return sinks
