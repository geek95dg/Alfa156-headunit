"""PipeWire control interface — route sources to DAC, manage EQ profiles.

Uses pw-cli / pw-link / wpctl command-line tools to control PipeWire.
On x86: uses default sound card (laptop/desktop speakers).
On OPi: targets USB DAC (ES9038Q2M) as default sink.

Audio hardware chain:
  ES9038Q2M USB DAC → RCA → TDA7388 4ch Class AB amp (4×41W) → front/rear speakers
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

# Where the generated filter-chain config lives (tmpfs — regenerated
# on every preset change and at audio module start).
EQ_FILTER_CONF = "/tmp/bcm_eq_filter.conf"
EQ_SINK_NAME = "bcm_eq_sink"


def _build_filter_chain_conf(gains: list[float]) -> str:
    """Render a PipeWire filter-chain config for a 10-band biquad EQ.

    The chain is: lowshelf(31 Hz) -> 8x peaking -> highshelf(16 kHz),
    exposed as an Audio/Sink named bcm_eq_sink. Audio played into that
    sink comes out equalized on the (real) default sink.
    """
    nodes = []
    links = []
    for i, (freq, gain) in enumerate(zip(EQ_FREQUENCIES, gains)):
        if i == 0:
            label = "bq_lowshelf"
        elif i == len(EQ_FREQUENCIES) - 1:
            label = "bq_highshelf"
        else:
            label = "bq_peaking"
        nodes.append(
            f'          {{ type = builtin name = eq_band_{i + 1} label = {label} '
            f'control = {{ "Freq" = {float(freq)} "Q" = 1.4 "Gain" = {float(gain)} }} }}'
        )
        if i > 0:
            links.append(
                f'          {{ output = "eq_band_{i}:Out" input = "eq_band_{i + 1}:In" }}'
            )
    nodes_s = "\n".join(nodes)
    links_s = "\n".join(links)
    return f"""# BCM v8.5 — generated 10-band EQ (do not edit; regenerated on preset change)
context.properties = {{ log.level = 0 }}
context.modules = [
  {{ name = libpipewire-module-filter-chain
    args = {{
      node.description = "BCM 10-band EQ"
      media.name = "BCM EQ"
      filter.graph = {{
        nodes = [
{nodes_s}
        ]
        links = [
{links_s}
        ]
      }}
      audio.channels = 2
      audio.position = [ FL FR ]
      capture.props = {{
        node.name = "{EQ_SINK_NAME}"
        media.class = Audio/Sink
      }}
      playback.props = {{
        node.name = "{EQ_SINK_NAME}_output"
        node.passive = true
      }}
    }}
  }}
]
"""


def _pipewire_env() -> dict:
    """Build env vars so wpctl/pw-cli reach the user's PipeWire socket.

    bcm-headunit runs as root via systemd, but PipeWire/wireplumber
    live in user session 1000. Without XDG_RUNTIME_DIR pointing at
    the user's runtime dir, `wpctl status` fails with rc=1 and BCM
    falls back to simulated audio — volume/mute/sink-switch are no-ops
    until this is fixed. PIPEWIRE_RUNTIME_DIR is also honored by some
    pipewire versions; setting both is safe.
    """
    import os
    env = os.environ.copy()
    for uid in (1000, os.getuid()):
        runtime = f"/run/user/{uid}"
        if os.path.isdir(f"{runtime}/pipewire-0") or os.path.exists(
                f"{runtime}/pipewire-0"):
            env["XDG_RUNTIME_DIR"] = runtime
            env["PIPEWIRE_RUNTIME_DIR"] = runtime
            return env
    # Fallback — XDG_RUNTIME_DIR set but socket may not exist
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    return env


def _run_cmd(cmd: list[str], timeout: float = 5.0) -> tuple[int, str, str]:
    """Run a shell command and return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            env=_pipewire_env(),
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
        self._bass: int = config.get("audio.bass", 0)
        self._treble: int = config.get("audio.treble", 0)
        self._fader: int = config.get("audio.fader", 0)
        self._balance: int = config.get("audio.balance", 0)

        # Real EQ DSP: a `pipewire -c <generated conf>` child process
        # hosting a filter-chain sink. None while PW unavailable or
        # audio.eq_dsp_enabled=false.
        self._eq_proc: Optional[subprocess.Popen] = None
        self._eq_dsp_enabled: bool = bool(config.get("audio.eq_dsp_enabled", True))

        # Check if PipeWire is running
        self._check_availability()

        # Bring the EQ up with the configured preset at start
        if self._available and self._eq_dsp_enabled:
            self.apply_eq_preset(self._current_eq)

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

        # Apply the gains to the actual audio path (filter-chain DSP).
        # Simulated (event-only) when PipeWire is absent — x86 dev.
        self._apply_eq_dsp(self._effective_gains(gains))

        log.info("EQ preset applied: %s %s", preset_name, gains)
        self._event_bus.publish("audio.eq_changed", {
            "preset": preset_name,
            "gains": gains,
            "frequencies": EQ_FREQUENCIES,
        })
        self._event_bus.publish("audio.eq_preset", preset_name)
        self._event_bus.publish("audio.eq_gains", gains)
        return True

    def set_custom_gains(self, gains: list[int]) -> bool:
        """Set individual band gains and switch to 'custom' preset."""
        gains = [max(-12, min(12, g)) for g in gains[:10]]
        while len(gains) < 10:
            gains.append(0)
        EQ_PRESETS["custom"] = list(gains)
        return self.apply_eq_preset("custom")

    def set_bass_treble(self, bass: int, treble: int) -> bool:
        """Shortcut: adjusts low bands (0-2) for bass and high bands (7-9) for treble."""
        bass = max(-12, min(12, bass))
        treble = max(-12, min(12, treble))
        self._bass = bass
        self._treble = treble
        # Fold bass/treble into the running DSP chain
        self._apply_eq_dsp(self._effective_gains(EQ_PRESETS[self._current_eq]))
        self._event_bus.publish("audio.bass", bass)
        self._event_bus.publish("audio.treble", treble)
        log.info("Bass/Treble: %+d / %+d", bass, treble)
        return True

    # ------------------------------------------------------------------
    # EQ DSP — PipeWire filter-chain child process
    # ------------------------------------------------------------------

    def _effective_gains(self, gains: list[float]) -> list[float]:
        """Preset gains with bass (bands 0-2) / treble (bands 7-9) folded in."""
        eff = list(gains)
        for i in (0, 1, 2):
            eff[i] = max(-12, min(12, eff[i] + self._bass))
        for i in (7, 8, 9):
            eff[i] = max(-12, min(12, eff[i] + self._treble))
        return eff

    def _apply_eq_dsp(self, gains: list[float]) -> None:
        """(Re)start the filter-chain process with the given band gains.

        Preset changes are rare, so restart-on-change is used instead of
        live pw-cli param pokes — simpler and version-proof. The sink
        appears as 'bcm_eq_sink'; source_manager routes audio into it.
        """
        if not (self._available and self._eq_dsp_enabled):
            return
        try:
            with open(EQ_FILTER_CONF, "w") as f:
                f.write(_build_filter_chain_conf(gains))
        except OSError as e:
            log.error("EQ: cannot write filter config: %s", e)
            return

        self._stop_eq_dsp()
        try:
            self._eq_proc = subprocess.Popen(
                ["pipewire", "-c", EQ_FILTER_CONF],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                env=_pipewire_env(),
            )
            log.info("EQ filter-chain started (pid=%d, sink=%s)",
                     self._eq_proc.pid, EQ_SINK_NAME)
        except FileNotFoundError:
            log.warning("EQ: pipewire binary not found — DSP disabled")
            self._eq_proc = None
            return

        # Route everything through the EQ: make bcm_eq_sink the default
        # sink once it appears (the filter-chain's playback side follows
        # the real hardware sink automatically).
        def _route():
            import time as _time
            for _ in range(10):
                _time.sleep(0.3)
                if self._set_default_sink_by_name(EQ_SINK_NAME):
                    log.info("Default sink -> %s (EQ in path)", EQ_SINK_NAME)
                    return
            log.warning("EQ sink did not appear — audio not equalized")

        import threading as _threading
        _threading.Thread(target=_route, daemon=True).start()

    def _set_default_sink_by_name(self, name: str) -> bool:
        """Find a sink id by node name in `wpctl status` and set default."""
        rc, out, _ = _run_cmd(["wpctl", "status", "--name"])
        if rc != 0:
            rc, out, _ = _run_cmd(["wpctl", "status"])
            if rc != 0:
                return False
        for line in out.splitlines():
            if name in line:
                for tok in line.replace("*", " ").split():
                    if tok.rstrip(".").isdigit():
                        sink_id = tok.rstrip(".")
                        rc2, _, _ = _run_cmd(["wpctl", "set-default", sink_id])
                        return rc2 == 0
        return False

    def _stop_eq_dsp(self) -> None:
        if self._eq_proc is None:
            return
        try:
            self._eq_proc.terminate()
            try:
                self._eq_proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._eq_proc.kill()
                self._eq_proc.wait(timeout=2)
        except Exception:
            pass
        self._eq_proc = None

    def stop(self) -> None:
        """Cleanup — stop the EQ DSP child process."""
        self._stop_eq_dsp()

    def set_fader(self, fader: int) -> bool:
        """Set front/rear balance (-10=rear to +10=front). Requires multi-channel DAC."""
        fader = max(-10, min(10, fader))
        self._fader = fader
        self._event_bus.publish("audio.fader", fader)
        log.info("Fader: %+d", fader)
        return True

    def set_balance(self, balance: int) -> bool:
        """Set left/right balance (-10=left to +10=right)."""
        balance = max(-10, min(10, balance))
        self._balance = balance
        self._event_bus.publish("audio.balance", balance)
        log.info("Balance: %+d", balance)
        return True

    @property
    def bass(self) -> int:
        return self._bass

    @property
    def treble(self) -> int:
        return self._treble

    @property
    def fader(self) -> int:
        return self._fader

    @property
    def balance(self) -> int:
        return self._balance

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
