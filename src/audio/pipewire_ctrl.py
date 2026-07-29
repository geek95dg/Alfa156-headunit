"""PipeWire control interface — pick the output, unmute it, manage EQ profiles.

Uses pw-dump / pw-cli / wpctl command-line tools to control PipeWire. There is
no per-platform branching here: the same code runs on x86 and OPi, and which
device the sound comes out of is decided by ``audio.sink`` in the config.

Startup order matters and is deliberate (v8.5.3):

  1. pick a hardware sink   — ``audio.sink: auto`` prefers the analog output
                              and explicitly avoids HDMI
  2. make it the default, unmute it, set ``audio.hw_volume``
  3. only then bring up the EQ filter-chain, with its playback side **pinned**
     to that sink via ``target.object``
  4. make the EQ sink the default so apps land on it

Before v8.5.3 step 1-2 did not exist and step 3 had no pin. The only place
that ever wrote a default sink pointed it at the EQ chain, so a manual
``wpctl set-default <analog>`` was undone 0.3-3 s after BCM started, and on a
machine with HDMI connected the chain would happily play into HDMI. Nothing
ever unmuted anything, so a freshly installed Realtek with Auto-Mute Mode on
stayed silent no matter what. That is what "no sound on the front jack" was.

Audio hardware chain (target build):
  ES9038Q2M USB DAC → RCA → off-the-shelf 4-channel car amplifier → 4x 4 ohm speakers

The amplifier is a bought unit powered straight from the starter battery on
its own fused branch, not from the buffered bus — see
docs/ZASILANIE_BUFOROWANE.md and schematics/audio_system.svg. Nothing here
depends on which amplifier it is.
"""

import json
import re
import subprocess
import threading
import time
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

# Sink picking. "auto" walks these in order and takes the first match.
# HDMI is excluded outright — on the M910q it is almost always present and
# almost never what you want to hear the car through.
_SINK_PREFER = (
    r"alsa_output\..*analog-stereo",   # wbudowane wyjście analogowe (Realtek)
    r"alsa_output\..*\.analog",
    r"alsa_output\.usb-.*",            # DAC USB, gdy kiedyś wróci
    r"alsa_output\..*",
)
_SINK_EXCLUDE = re.compile(r"hdmi|displayport|iec958", re.I)

# Ile razy i jak często dopytywać o PipeWire w tle, gdy nie było go przy
# starcie modułu. 60 × 2 s ≈ 2 minuty — z zapasem na wolny autologin.
PW_BACKGROUND_ATTEMPTS = 60
PW_BACKGROUND_DELAY = 2.0


def _build_filter_chain_conf(gains: list[float],
                             target_sink: Optional[str] = None) -> str:
    """Render a PipeWire filter-chain config for a 10-band biquad EQ.

    The chain is: lowshelf(31 Hz) -> 8x peaking -> highshelf(16 kHz),
    exposed as an Audio/Sink named bcm_eq_sink.

    ``target_sink`` pins the chain's playback side to a specific hardware
    sink. Without it the chain follows whatever WirePlumber currently calls
    default — which, once we then make the EQ sink itself the default, is a
    good way to end up feeding HDMI.
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
    # Pin the playback side to a named sink when we know which one we want.
    target_s = (f'\n        target.object = "{target_sink}"'
                if target_sink else "")
    return f"""# BCM v8.5 — generated 10-band EQ (do not edit; regenerated on preset change)
context.properties = {{ log.level = 0 }}

# Bez tej mapy filter-chain nie znajdzie audioconvert i sink w ogóle się nie
# pojawi — a wtedy kod ma tylko wpis w logu i cichy komputer.
context.spa-libs = {{
  audio.convert.* = audioconvert/libspa-audioconvert
  support.*       = support/libspa-support
}}

context.modules = [
  {{ name = libpipewire-module-rt
    args = {{ nice.level = -11 }}
    flags = [ ifexists nofail ] }}
  {{ name = libpipewire-module-protocol-native }}
  {{ name = libpipewire-module-client-node }}
  {{ name = libpipewire-module-adapter }}
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
        node.passive = true{target_s}
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

        # The hardware sink we decided to play through. Everything else hangs
        # off this: the EQ chain is pinned to it, unmute targets it, and if the
        # EQ fails to come up we fall back to it.
        self._hw_sink: Optional[str] = None
        self._hw_sink_id: Optional[str] = None

        # Real EQ DSP: a `pipewire -c <generated conf>` child process
        # hosting a filter-chain sink. None while PW unavailable or
        # audio.eq_dsp_enabled=false.
        self._eq_proc: Optional[subprocess.Popen] = None
        self._eq_dsp_enabled: bool = bool(config.get("audio.eq_dsp_enabled", True))
        self._stopping = False

        self._check_availability()

    # ------------------------------------------------------------------ #
    # Availability                                                        #
    # ------------------------------------------------------------------ #

    def _check_availability(self) -> bool:
        """Probe PipeWire once. Returns True when wpctl answers."""
        rc, _, _ = _run_cmd(["wpctl", "status"])
        self._available = rc == 0
        if self._available:
            log.info("PipeWire detected and running")
            self._detect_default_sink()
        return self._available

    def wait_for_pipewire(self, attempts: int = 3, delay: float = 0.5) -> bool:
        """Retry the availability probe a few times, synchronously.

        bcm-headunit starts as root from systemd, while PipeWire lives in the
        user session. The unit does not wait for that session, so on a cold
        boot the very first probe can lose the race. Before v8.5.3 that single
        failed probe was final for the life of the process and every wpctl call
        silently became a no-op — the log line "audio control will be
        simulated" was the only hint.

        Kept short on purpose: this runs inside module startup, and a head unit
        that takes an extra 20 s to show a screen is worse than one whose sound
        arrives a few seconds late. The long wait lives in the background
        retry started by start_output().
        """
        if self._available:
            return True
        for i in range(max(1, attempts)):
            if self._check_availability():
                return True
            if i < attempts - 1:
                time.sleep(delay)
        return False

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

    # ------------------------------------------------------------------ #
    # Sink discovery and selection                                        #
    # ------------------------------------------------------------------ #

    def list_sink_nodes(self) -> list[dict[str, str]]:
        """Enumerate Audio/Sink nodes as [{id, name, description}].

        pw-dump gives structured JSON, which beats scraping `wpctl status`:
        that output is localised, changes between versions, and only shows
        node.name when --name is supported. wpctl remains the fallback.
        """
        rc, out, _ = _run_cmd(["pw-dump"], timeout=8.0)
        if rc == 0 and out.strip():
            try:
                sinks = []
                for obj in json.loads(out):
                    info = obj.get("info") or {}
                    props = info.get("props") or {}
                    if props.get("media.class") != "Audio/Sink":
                        continue
                    name = props.get("node.name")
                    if not name:
                        continue
                    sinks.append({
                        "id": str(obj.get("id", "")),
                        "name": name,
                        "description": props.get("node.description", ""),
                    })
                if sinks:
                    return sinks
            except (ValueError, TypeError) as e:
                log.debug("pw-dump parse failed (%s) — falling back to wpctl", e)

        # Fallback: `wpctl status --name` lists "   42. node.name  [vol: ...]"
        rc, out, _ = _run_cmd(["wpctl", "status", "--name"])
        if rc != 0:
            return []
        sinks, in_sinks = [], False
        for line in out.splitlines():
            stripped = line.strip(" │├─└*")
            if "Sinks:" in line:
                in_sinks = True
                continue
            if in_sinks and (":" in line and "Sinks:" not in line
                             and not stripped[:1].isdigit()):
                break
            m = re.match(r"(\d+)\.\s+(\S+)", stripped)
            if in_sinks and m:
                sinks.append({"id": m.group(1), "name": m.group(2),
                              "description": ""})
        return sinks

    def pick_hardware_sink(self) -> Optional[dict[str, str]]:
        """Choose the sink to play through, honouring ``audio.sink``.

        ``auto`` prefers the built-in analog output and skips HDMI outright.
        Any other value is matched against node.name as a substring, so a
        partial name from `wpctl status --name` is enough.
        """
        wanted = str(self._config.get("audio.sink", "auto") or "auto").strip()
        sinks = [s for s in self.list_sink_nodes()
                 if s["name"] != EQ_SINK_NAME]
        if not sinks:
            log.error("No hardware audio sinks found — is the codec driver loaded?")
            return None

        if wanted.lower() != "auto":
            for s in sinks:
                if wanted in s["name"]:
                    return s
            log.error(
                "audio.sink=%r matches none of the available sinks: %s — "
                "falling back to auto-detection",
                wanted, ", ".join(s["name"] for s in sinks),
            )

        usable = [s for s in sinks if not _SINK_EXCLUDE.search(s["name"])]
        for pattern in _SINK_PREFER:
            for s in usable:
                if re.match(pattern, s["name"]):
                    return s
        if usable:
            return usable[0]

        log.warning("Only HDMI-like sinks available — using %s", sinks[0]["name"])
        return sinks[0]

    def _amixer_unmute(self) -> None:
        """Best-effort ALSA-level unmute.

        PipeWire's set-mute does not reach every ALSA control. A fresh Realtek
        typically ships with Auto-Mute Mode on and Headphone muted, which
        keeps the jack silent no matter what the PipeWire volume says.
        Failures here are expected on non-ALSA setups and stay at debug level.
        """
        for ctl in ("Master", "Headphone", "Speaker", "PCM", "Front"):
            rc, _, err = _run_cmd(["amixer", "-q", "sset", ctl, "unmute"])
            if rc != 0:
                log.debug("amixer sset %s unmute: %s", ctl, err.strip())
        _run_cmd(["amixer", "-q", "sset", "Auto-Mute Mode", "Disabled"])

    def prepare_output(self) -> Optional[str]:
        """Pick, select, unmute and level the hardware sink. Returns its name.

        This is the step that never existed before v8.5.3, which is why the
        front-panel jack stayed silent: nothing chose the analog output and
        nothing ever unmuted anything.
        """
        if not self._available:
            return None

        sink = self.pick_hardware_sink()
        if sink is None:
            return None

        self._hw_sink = sink["name"]
        self._hw_sink_id = sink["id"] or None
        target = self._hw_sink_id or self._hw_sink

        if self._hw_sink_id:
            rc, _, err = _run_cmd(["wpctl", "set-default", self._hw_sink_id])
            if rc != 0:
                log.error("Could not select sink %s: %s", self._hw_sink, err.strip())
            else:
                log.info("Hardware sink -> %s", self._hw_sink)

        if self._config.get("audio.force_unmute", True):
            _run_cmd(["wpctl", "set-mute", str(target), "0"])
            self._amixer_unmute()

        hw_vol = int(self._config.get("audio.hw_volume", 100))
        hw_vol = max(0, min(100, hw_vol))
        _run_cmd(["wpctl", "set-volume", str(target), f"{hw_vol / 100.0:.2f}"])

        self._default_sink = self._hw_sink
        self._event_bus.publish("audio.output_sink", self._hw_sink)
        return self._hw_sink

    def start_output(self) -> None:
        """Select the output and bring the EQ up; never blocks for long.

        If PipeWire is not up yet we hand the job to a background thread and
        let the rest of BCM start. The session usually appears within seconds
        of the graphical login, and audio then configures itself without a
        service restart.
        """
        if self.wait_for_pipewire():
            self._configure_output()
            return

        log.warning(
            "PipeWire not up yet — continuing startup and retrying in the "
            "background (audio stays simulated until it appears)"
        )

        def _late():
            for _ in range(PW_BACKGROUND_ATTEMPTS):
                time.sleep(PW_BACKGROUND_DELAY)
                if self._stopping:
                    return
                if self._check_availability():
                    log.info("PipeWire appeared — configuring audio output now")
                    self._configure_output()
                    return
            log.error(
                "PipeWire never appeared (%d attempts over ~%d s) — there will "
                "be no sound. Check XDG_RUNTIME_DIR for the BCM process and "
                "whether the user session with pipewire-0 is running.",
                PW_BACKGROUND_ATTEMPTS,
                int(PW_BACKGROUND_ATTEMPTS * PW_BACKGROUND_DELAY),
            )

        threading.Thread(target=_late, daemon=True,
                         name="pipewire-wait").start()

    def _configure_output(self) -> None:
        """Pick the sink and start the EQ. Safe to call once PipeWire is up."""
        self.prepare_output()
        if self._eq_dsp_enabled:
            self.apply_eq_preset(self._current_eq)

    @property
    def hardware_sink(self) -> Optional[str]:
        return self._hw_sink

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

        # Make sure we know where the sound is supposed to come out before
        # building a chain that has to point at it.
        if self._hw_sink is None:
            self.prepare_output()

        try:
            with open(EQ_FILTER_CONF, "w") as f:
                f.write(_build_filter_chain_conf(gains, self._hw_sink))
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
            log.info("EQ filter-chain started (pid=%d, sink=%s, target=%s)",
                     self._eq_proc.pid, EQ_SINK_NAME, self._hw_sink or "default")
        except FileNotFoundError:
            log.warning("EQ: pipewire binary not found — DSP disabled")
            self._eq_proc = None
            return

        # Route everything through the EQ by making bcm_eq_sink the default,
        # but only once it actually exists. If it never shows up we put the
        # hardware sink back — leaving the default pointing at a chain that
        # failed to start is how you get a machine that is simply silent.
        def _route():
            for _ in range(10):
                time.sleep(0.3)
                if self._stopping:
                    return
                if self._set_default_sink_by_name(EQ_SINK_NAME):
                    log.info("Default sink -> %s (EQ in path, out via %s)",
                             EQ_SINK_NAME, self._hw_sink or "default")
                    return
            log.error(
                "EQ sink %s did not appear — restoring %s as default so there "
                "is still sound. Check `pipewire -c %s` by hand.",
                EQ_SINK_NAME, self._hw_sink or "the hardware sink",
                EQ_FILTER_CONF,
            )
            self._stop_eq_dsp()
            if self._hw_sink_id:
                _run_cmd(["wpctl", "set-default", self._hw_sink_id])

        threading.Thread(target=_route, daemon=True).start()

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
        """Cleanup — stop the EQ DSP child and hand the output back.

        Without this the `pipewire -c` child outlives BCM and WirePlumber is
        left with a default sink that points at a node about to disappear.
        """
        self._stopping = True
        self._stop_eq_dsp()
        if self._available and self._hw_sink_id:
            _run_cmd(["wpctl", "set-default", self._hw_sink_id])

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
