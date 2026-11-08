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
#
# USB comes first because that is the documented hardware chain (USB DAC ->
# RCA -> car amp). The on-board Realtek jack is the fallback, not the target:
# on the M910q it is a front headphone socket whose "Headphone" ALSA control
# ships muted at 0%, so preferring it meant "auto" picked the one output that
# needs extra coaxing to make a sound.
_SINK_PREFER = (
    r"alsa_output\.usb-.*",            # karta/DAC USB — docelowe wyjście
    r"alsa_output\..*analog-stereo",   # wbudowane wyjście analogowe (Realtek)
    r"alsa_output\..*\.analog",
    r"alsa_output\..*",
)
_SINK_EXCLUDE = re.compile(r"hdmi|displayport|iec958", re.I)

# Ile razy i jak często dopytywać o PipeWire w tle, gdy nie było go przy
# starcie modułu. 60 × 2 s ≈ 2 minuty — z zapasem na wolny autologin.
PW_BACKGROUND_ATTEMPTS = 60
PW_BACKGROUND_DELAY = 2.0

# Profil, w którym musi być podłączony telefon, żeby jego muzyka do nas
# dotarła: "audio-gateway" = telefon jest źródłem A2DP i bramką HSP/HFP, a BCM
# odbiornikiem. Obejmuje media i rozmowy naraz, więc nie wybieramy między
# muzyką a dzwonieniem.
BT_AUDIO_PROFILE = "audio-gateway"
BT_SOURCE_PREFIX = "bluez_input."
# Węzeł źródła pojawia się dopiero po przełączeniu profilu, z opóźnieniem
# zależnym od telefonu — 10 × 1 s wystarcza z zapasem.
BT_ATTACH_ATTEMPTS = 10
BT_ATTACH_DELAY = 1.0
# Po bt.call_state=active węzły SCO pojawiają się z opóźnieniem — tyle czekamy
# na nie, zanim zgłosimy w logu, że rozmowa nie jest podłączona.
CALL_ROUTE_WAIT_S = 3.0


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


def _pw_dump_objects(text: str) -> list[dict]:
    """Parse ``pw-dump`` output into its list of objects; [] on garbage.

    pw-dump prints one JSON array. Anything else (empty output, a
    truncated dump after a timeout, an error message) is treated as "no
    objects" rather than raised — callers then simply find nothing.
    """
    if not text or not text.strip():
        return []
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    return [obj for obj in data if isinstance(obj, dict)]


def _obj_props(obj: dict) -> dict:
    """``info.props`` of a pw-dump object, always a dict."""
    info = obj.get("info")
    props = info.get("props") if isinstance(info, dict) else None
    return props if isinstance(props, dict) else {}


def _parse_enum_profiles(info: Any) -> list[dict[str, Any]]:
    """The ``EnumProfile`` params of a pw-dump Device ``info`` block.

    Returns ``[{index, name, available, priority, description}]``, skipping
    entries without a name or index. Shared by the Bluetooth card handling
    below and by src/audio/mic_router.py (ALSA card output-only/duplex
    profiles), so both read the same structure the same way.
    """
    if not isinstance(info, dict):
        return []
    params = info.get("params")
    entries = params.get("EnumProfile") if isinstance(params, dict) else None
    out = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        name, index = entry.get("name"), entry.get("index")
        if not isinstance(name, str) or not isinstance(index, int) or isinstance(index, bool):
            continue
        priority = entry.get("priority", 0)
        out.append({
            "index": index,
            "name": name,
            "available": str(entry.get("available", "unknown")),
            "priority": priority if isinstance(priority, int) else 0,
            "description": str(entry.get("description", "")),
        })
    return out


def _is_a2dp_node(props: dict) -> bool:
    """True for a Bluetooth A2DP node, False for SCO (HFP/HSP) and unknowns.

    PipeWire sets ``api.bluez5.profile`` on every bluez node (``a2dp-source``,
    ``a2dp-sink``, ``headset-audio-gateway``, ``headset-head-unit`` …). The
    factory name is the fallback for builds that do not. Anything that cannot
    be positively identified as A2DP counts as "not A2DP": linking a SCO node
    by hand next to WirePlumber's own link doubles the call audio.
    """
    profile = str(props.get("api.bluez5.profile") or "").lower()
    if profile:
        return profile.startswith("a2dp")
    factory = str(props.get("factory.name") or "").lower()
    if factory:
        return "a2dp" in factory
    return "a2dp" in str(props.get("node.name") or "").lower()


def _is_sco_node(props: dict) -> bool:
    """True for a Bluetooth SCO (HFP/HSP call audio) node.

    Only bluez nodes carry ``api.bluez5.profile`` (``headset-audio-gateway``
    / ``headset-head-unit`` for SCO); the factory name
    (``api.bluez5.sco.source`` / ``.sink``) is the fallback.
    """
    profile = str(props.get("api.bluez5.profile") or "").lower()
    if profile:
        return profile.startswith("headset")
    factory = str(props.get("factory.name") or "").lower()
    return "bluez5.sco" in factory


def _call_route(objects: list[dict]) -> dict[str, Any]:
    """What WirePlumber linked for a phone call, from one pw-dump.

    With the phone as audio gateway, PipeWire exposes the call as two
    streams: the downlink (caller's voice, ``Stream/Output/Audio``, played
    like an app into the default sink) and the uplink (our microphone,
    ``Stream/Input/Audio``, recording from the default source). WirePlumber
    links both by itself. Returns ``{downlink, uplink, linked,
    downlink_peers, uplink_peers}`` with node names; ``linked`` is True only
    when both directions have at least one link.
    """
    names: dict[int, str] = {}
    sco: list[tuple[int, dict]] = []
    links: list[tuple[int, int]] = []
    for obj in objects:
        otype = str(obj.get("type", ""))
        oid = obj.get("id")
        if otype.endswith("Interface:Node") and isinstance(oid, int):
            props = _obj_props(obj)
            names[oid] = str(props.get("node.name") or oid)
            if _is_sco_node(props):
                sco.append((oid, props))
        elif otype.endswith("Interface:Link"):
            info = obj.get("info") or {}
            out_id, in_id = info.get("output-node-id"), info.get("input-node-id")
            if isinstance(out_id, int) and isinstance(in_id, int):
                links.append((out_id, in_id))

    down = up = None
    for oid, props in sco:
        mclass = str(props.get("media.class") or "")
        # Output stream / source = audio coming FROM the phone.
        if down is None and (mclass.startswith("Stream/Output") or mclass.startswith("Audio/Source")):
            down = oid
        elif up is None and (mclass.startswith("Stream/Input") or mclass.startswith("Audio/Sink")):
            up = oid
    down_peers = sorted({names.get(i, str(i)) for o, i in links if o == down}) if down is not None else []
    up_peers = sorted({names.get(o, str(o)) for o, i in links if i == up}) if up is not None else []
    return {
        "downlink": names.get(down, "") if down is not None else "",
        "uplink": names.get(up, "") if up is not None else "",
        "linked": bool(down_peers and up_peers),
        "downlink_peers": down_peers,
        "uplink_peers": up_peers,
    }


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
        # Where the EQ chain's output goes instead of the hardware sink —
        # set by the mic router while echo cancellation is running (the
        # canceller needs to hear what the speakers play). None = hw sink.
        self._eq_target_override: Optional[str] = None
        # Set once _configure_output() has finished (sink chosen, unmuted,
        # levelled, EQ started). The mic router waits for it before it
        # switches a card profile, which recreates the sink under a new id.
        self.output_configured = threading.Event()

        # A phone that connects later needs its card taken out of the "off"
        # profile and wired to our sink — see attach_bt_audio().
        self._event_bus.subscribe("bt.connected", self._on_bt_connected)

        # Calls: only VERIFY what WirePlumber linked (see _check_call_route).
        # One check at a time — a flapping call state must not pile up
        # pw-dump workers.
        self._call_check_lock = threading.Lock()
        self._event_bus.subscribe("bt.call_state", self._on_call_state)

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
                        # ALSA card index — needed to aim amixer at the right
                        # card. Without it the unmute pass hits card 0.
                        "card": str(props.get("alsa.card",
                                              props.get("api.alsa.card", ""))),
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

    def _amixer_unmute(self, card: Optional[str] = None) -> None:
        """Best-effort ALSA-level unmute of the card we actually play through.

        PipeWire's set-mute does not reach every ALSA control. A fresh Realtek
        typically ships with Auto-Mute Mode on and Headphone muted at 0%, which
        keeps the jack silent no matter what the PipeWire volume says.

        ``card`` is the ALSA card index of the chosen sink. It matters: without
        it every amixer call defaulted to card 0, so on a machine where card 0
        is a USB adapter and card 1 the on-board codec (the normal order once a
        USB card is plugged in) the codec's muted Headphone control was never
        touched — the jack stayed dead while the log claimed an unmute had run.

        Controls that do not exist on a given card fail harmlessly; that is
        expected and stays at debug level. Playback level is raised to 100%
        alongside the unmute because a control can also be "on" at 0%, which
        sounds exactly like a mute.
        """
        base = ["amixer", "-q"]
        if card:
            base += ["-c", str(card)]
        for ctl in ("Master", "Headphone", "Speaker", "PCM", "Front"):
            rc, _, err = _run_cmd(base + ["sset", ctl, "unmute"])
            if rc != 0:
                log.debug("amixer sset %s unmute: %s", ctl, err.strip())
                continue
            rc, _, err = _run_cmd(base + ["sset", ctl, "100%"])
            if rc != 0:
                log.debug("amixer sset %s 100%%: %s", ctl, err.strip())
        _run_cmd(base + ["sset", "Auto-Mute Mode", "Disabled"])

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
            self._amixer_unmute(sink.get("card") or None)

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
        try:
            self.prepare_output()
            if self._eq_dsp_enabled:
                self.apply_eq_preset(self._current_eq)
            # A phone paired before BCM started is already connected by now,
            # so do not wait for a bt.connected edge that will never come.
            self.attach_bt_audio()
        finally:
            self.output_configured.set()

    # ------------------------------------------------------------------ #
    # Bluetooth media audio (phone -> BCM speakers)                       #
    # ------------------------------------------------------------------ #

    def _on_bt_connected(self, topic: str, value: Any, timestamp: float) -> None:
        self.attach_bt_audio()

    def attach_bt_audio(self) -> None:
        """Put connected phones into the audio profile and route them to output.

        Two separate things have to be true before music started on the phone
        comes out of the car speakers, and neither happened by itself:

          1. The phone's ``bluez_card`` has to be in the ``audio-gateway``
             profile. WirePlumber leaves it at ``off`` when nothing has ever
             asked for its audio, and a card in ``off`` exposes no nodes at all
             — there is nothing to route, which reads exactly like "Bluetooth
             is connected but silent".
          2. The resulting ``bluez_input.*`` source is a device source, not an
             application stream, so the session policy does not necessarily
             link it anywhere. We link it to the EQ sink ourselves, which puts
             phone audio under the same volume slider and EQ as everything else.

        Runs on a worker thread: it polls for the source node to appear, and
        this is called straight from an event-bus callback.
        """
        if not self._available:
            return
        threading.Thread(target=self._attach_bt_audio_worker, daemon=True,
                         name="pipewire-bt-attach").start()

    def _bluez_cards(self) -> list[dict[str, Any]]:
        """Return connected bluez5 Audio/Device cards with their profiles."""
        rc, out, _ = _run_cmd(["pw-dump"], timeout=8.0)
        if rc != 0:
            return []

        cards = []
        for obj in _pw_dump_objects(out):
            info = obj.get("info") or {}
            props = _obj_props(obj)
            if props.get("device.api") != "bluez5":
                continue
            if props.get("media.class") != "Audio/Device":
                continue
            profiles = {p["name"]: p["index"] for p in _parse_enum_profiles(info)}
            cards.append({
                "id": obj.get("id"),
                "alias": props.get("device.alias", ""),
                "profile": props.get("bluez5.profile", ""),
                "profiles": profiles,
            })
        return cards

    def _attach_bt_audio_worker(self) -> None:
        for card in self._bluez_cards():
            if card["profile"] != BT_AUDIO_PROFILE:
                index = card["profiles"].get(BT_AUDIO_PROFILE)
                if index is None:
                    log.info(
                        "BT %s exposes no %r profile (has: %s) — no media "
                        "audio from this device",
                        card["alias"] or card["id"], BT_AUDIO_PROFILE,
                        ", ".join(card["profiles"]) or "none",
                    )
                    continue
                rc, _, err = _run_cmd(
                    ["wpctl", "set-profile", str(card["id"]), str(index)])
                if rc != 0:
                    log.warning("BT %s: could not select %s profile: %s",
                                card["alias"] or card["id"],
                                BT_AUDIO_PROFILE, err.strip())
                    continue
                log.info("BT %s -> %s profile", card["alias"] or card["id"],
                         BT_AUDIO_PROFILE)
        self._link_bt_sources()

    def _link_bt_sources(self) -> None:
        """Link every bluez A2DP source's output to our sink, once it shows up.

        A2DP only. During a call the phone also exposes SCO nodes, and
        WirePlumber 0.5 links those itself (downlink -> default sink, uplink
        <- default source); a second, hand-made pw-link would play the caller
        twice. :func:`_is_a2dp_node` refuses anything it cannot positively
        identify as A2DP.
        """
        target = EQ_SINK_NAME if self._eq_proc is not None else self._hw_sink
        if not target:
            return

        for _ in range(BT_ATTACH_ATTEMPTS):
            if self._stopping:
                return
            sources = [s for s in self._list_source_nodes()
                       if s["name"].startswith(BT_SOURCE_PREFIX)
                       and _is_a2dp_node(s.get("props") or {})]
            if sources:
                for src in sources:
                    self._link_stereo(src["name"], target)
                return
            time.sleep(BT_ATTACH_DELAY)
        log.debug("No %s* source appeared — phone may not be streaming yet",
                  BT_SOURCE_PREFIX)

    def _list_source_nodes(self) -> list[dict[str, Any]]:
        """Enumerate Audio/Source nodes as [{id, name, props}]."""
        rc, out, _ = _run_cmd(["pw-dump"], timeout=8.0)
        if rc != 0:
            return []
        sources = []
        for obj in _pw_dump_objects(out):
            props = _obj_props(obj)
            if props.get("media.class") != "Audio/Source":
                continue
            name = props.get("node.name")
            if name:
                sources.append({"id": str(obj.get("id", "")), "name": name,
                                "props": props})
        return sources

    def _link_stereo(self, source: str, sink: str) -> None:
        """pw-link both channels of ``source`` into ``sink``.

        A link that already exists makes pw-link fail; that is the normal case
        when the session policy got there first, so it is not an error.
        """
        for src_port, dst_port in (("output_FL", "playback_FL"),
                                   ("output_FR", "playback_FR")):
            rc, _, err = _run_cmd(
                ["pw-link", f"{source}:{src_port}", f"{sink}:{dst_port}"])
            if rc == 0:
                log.info("Linked %s:%s -> %s:%s",
                         source, src_port, sink, dst_port)
            else:
                log.debug("pw-link %s -> %s: %s", source, sink, err.strip())

    # ------------------------------------------------------------------ #
    # Phone calls (HFP/SCO) — verify only                                 #
    # ------------------------------------------------------------------ #

    def _on_call_state(self, topic: str, value: Any, timestamp: float) -> None:
        if value != "active" or not self._available:
            return
        if not self._call_check_lock.acquire(blocking=False):
            return  # a check is already running for this call
        threading.Thread(target=self._call_route_worker, daemon=True,
                         name="pipewire-call-route").start()

    def _call_route_worker(self) -> None:
        try:
            self._check_call_route()
        except Exception:
            log.exception("Call route check failed")
        finally:
            self._call_check_lock.release()

    def _check_call_route(self, wait_s: float = CALL_ROUTE_WAIT_S,
                          poll_s: float = 0.5) -> dict[str, Any]:
        """Log (and publish) how the call audio is wired. Never links anything.

        WirePlumber 0.5 links the SCO streams itself: downlink -> default
        sink (bcm_eq_sink), uplink <- default source (the mic router's
        choice). Adding our own pw-link here would only double the audio.
        What this does is make a broken call diagnosable from the log: the
        SCO nodes may take a moment to appear after the call goes active, so
        it polls for up to ``wait_s`` seconds, then publishes
        ``audio.call_route`` and warns when either direction is unlinked.
        """
        deadline = time.monotonic() + max(0.0, wait_s)
        route: dict[str, Any] = {"downlink": "", "uplink": "", "linked": False,
                                 "downlink_peers": [], "uplink_peers": []}
        while True:
            rc, out, _ = _run_cmd(["pw-dump"], timeout=8.0)
            if rc == 0:
                route = _call_route(_pw_dump_objects(out))
                if route["linked"]:
                    break
            if self._stopping or time.monotonic() >= deadline:
                break
            time.sleep(poll_s)

        self._event_bus.publish("audio.call_route", route)
        if route["linked"]:
            log.info("Call audio: downlink %s -> %s; uplink %s <- %s",
                     route["downlink"], ", ".join(route["downlink_peers"]),
                     route["uplink"], ", ".join(route["uplink_peers"]))
        elif not route["downlink"] and not route["uplink"]:
            log.warning(
                "Call active but no Bluetooth SCO nodes in PipeWire after %.0f s "
                "— call audio stays on the phone. Check that WirePlumber uses the "
                "oFono backend (51-bcm-hfp-ofono.conf) and the D-Bus policy "
                "bcm-ofono-pipewire.conf; tools/bcm-audio-diag.sh shows both.",
                wait_s)
        else:
            log.warning(
                "Call audio NOT fully linked: downlink %s -> [%s], uplink %s <- [%s]. "
                "WirePlumber normally links SCO by itself — see "
                "tools/bcm-audio-diag.sh (default source, oFono agent).",
                route["downlink"] or "-", ", ".join(route["downlink_peers"]),
                route["uplink"] or "-", ", ".join(route["uplink_peers"]))
        return route

    # ------------------------------------------------------------------ #
    # Hooks for src/audio/mic_router.py                                   #
    # ------------------------------------------------------------------ #

    def refresh_hw_sink_id(self) -> Optional[str]:
        """Re-resolve the hardware sink's node id after a card profile change.

        Switching a card's profile recreates its nodes under new ids. The EQ
        chain targets the sink by NAME, so it follows by itself; the cached
        ``_hw_sink_id`` (volume, unmute, fallback default) is what would go
        stale. Returns the new id, or None if the sink is not there (yet).
        """
        if not (self._available and self._hw_sink):
            return None
        for sink in self.list_sink_nodes():
            if sink["name"] == self._hw_sink:
                if sink["id"] and sink["id"] != self._hw_sink_id:
                    log.info("Hardware sink %s now id %s (was %s)",
                             self._hw_sink, sink["id"], self._hw_sink_id)
                    self._hw_sink_id = sink["id"]
                    # prepare_output()/_settle_levels() may have unmuted and
                    # levelled the OLD node (rc ignored) — re-apply on the new.
                    self._apply_hw_levels(self._hw_sink_id)
                return self._hw_sink_id
        return None

    def _apply_hw_levels(self, target: str) -> None:
        """audio.force_unmute + audio.hw_volume on the hardware sink node."""
        if self._config.get("audio.force_unmute", True):
            _run_cmd(["wpctl", "set-mute", str(target), "0"])
        hw_vol = max(0, min(100, int(self._config.get("audio.hw_volume", 100))))
        _run_cmd(["wpctl", "set-volume", str(target), f"{hw_vol / 100.0:.2f}"])

    def set_eq_output_target(self, target: Optional[str]) -> bool:
        """Point the EQ chain's output at ``target`` (None = hardware sink).

        Used by the echo canceller, whose reference sink must receive what
        the speakers play. Restarts the EQ child with the current gains.
        Returns True when the target changed.
        """
        target = target or None
        if target == self._eq_target_override:
            return False
        self._eq_target_override = target
        log.info("EQ output -> %s", target or self._hw_sink or "default")
        if self._available and self._eq_dsp_enabled:
            self._apply_eq_dsp(self._effective_gains(EQ_PRESETS[self._current_eq]))
        return True

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
        if not (self._available and self._eq_dsp_enabled) or self._stopping:
            # _stopping: a late caller (mic router, preset change) must not
            # start a fresh `pipewire -c` child that outlives BCM.
            return

        # Make sure we know where the sound is supposed to come out before
        # building a chain that has to point at it.
        if self._hw_sink is None:
            self.prepare_output()

        target = self._eq_target_override or self._hw_sink
        try:
            with open(EQ_FILTER_CONF, "w") as f:
                f.write(_build_filter_chain_conf(gains, target))
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
                     self._eq_proc.pid, EQ_SINK_NAME, target or "default")
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
                    self._settle_levels()
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

    def _settle_levels(self) -> None:
        """Re-apply hw_volume and master_volume once the EQ sink is default.

        Both levels are set during startup, but the EQ sink only becomes the
        default 0.3-3 s later, from the routing thread above. Until then
        ``@DEFAULT_AUDIO_SINK@`` still means the hardware sink, so
        VolumeController's initial master volume lands on the hardware stage:
        the card ends up attenuated to the master level while the EQ sink sits
        at 100%. Sound comes out either way, which is why this went unnoticed —
        the cost is silent: ``audio.hw_volume`` never actually sticks and the
        available headroom is master × hw instead of master.

        Re-applying in this order — hardware first, then the new default — puts
        each level on the node it was meant for without a volume jump.
        """
        if self._hw_sink_id or self._hw_sink:
            target = self._hw_sink_id or self._hw_sink
            hw_vol = max(0, min(100, int(self._config.get("audio.hw_volume", 100))))
            _run_cmd(["wpctl", "set-volume", str(target), f"{hw_vol / 100.0:.2f}"])
        self.set_volume(int(self._config.get("audio.master_volume", 70)))

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
