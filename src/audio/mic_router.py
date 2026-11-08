"""Microphone routing for Android Auto voice and HFP calls (PipeWire).

Why this exists
---------------
Nothing in BCM used to choose a capture source. ``audio.mic_phone`` was read
by no code, and PipeWire's default source was whatever WirePlumber happened
to pick. That is the root of three faults seen in the car:

* autoapp (openDsh) opens ``QAudioDeviceInfo::defaultInputDevice()`` ONCE per
  AA session, when the session's QtAudioInput is created. A floating input
  on a cheap USB card then hands the assistant (and the phone call uplink)
  pure noise.
* With no real source at all, pipewire-pulse falls back to a sink MONITOR as
  the default source — AA would send the car's own playback back to the
  assistant.
* During HFP calls WirePlumber links the uplink stream to the default source,
  so the same wrong choice ruins calls.

What it does (only when ``audio.mic_router: true``; code default false, so
the production config keeps its old behaviour):

a) no mic (``audio.mic_phone`` empty or not present): make sure a silent
   ``bcm_null_mic`` node exists in the user's PipeWire graph and make it the
   default source. The assistant then hears silence and ends cleanly;
b) mic found: make it the default source. If it sits on a different card than
   the one we play through and ``audio.mic_disable_unused_inputs`` is true,
   the output card is switched to an output-only profile (its floating input
   is what produced the noise), then PipeWireController's cached sink id is
   refreshed;
c) optional echo cancellation (``audio.mic_echo_cancel: true``, or ``auto``
   when libspa-aec-webrtc.so is installed): a separate ``pipewire -c`` child
   with libpipewire-module-echo-cancel, exactly like the EQ child. Any failure
   falls back to the raw mic with one ERROR in the log. Off by default.

A watchdog re-checks every 10 s: default source drifted (WirePlumber or a
user changed it), mic unplugged (-> silent mode) or plugged back (-> mic).
It publishes ``audio.mic_state`` ``{state: ok|none|error, source, aec}`` and
``audio.input_source`` (node.name), both only on change, and logs one
snapshot of autoapp's streams and links when AA connects (``audio.diag``).

Everything runs on a background thread; every command is an argv list with
a timeout, run in the PipeWire user session (BCM runs as root). A missing
tool degrades to ``state: error`` in the log — never an exception.
"""

from __future__ import annotations

import glob
import json
import re
import subprocess
import threading
import time
from typing import Any, Callable, Optional

from src.audio.pipewire_ctrl import (
    _obj_props,
    _parse_enum_profiles,
    _pipewire_env,
    _pw_dump_objects,
)
from src.core.fsutil import atomic_write_text
from src.core.logger import get_logger

log = get_logger("audio.mic_router")

#: Silent source used when there is no microphone.
NULL_MIC_NAME = "bcm_null_mic"
#: Echo-cancelled source / reference sink created by the AEC child.
AEC_SOURCE_NAME = "bcm_mic"
AEC_REF_SINK_NAME = "bcm_aec_ref"
AEC_CONF_PATH = "/tmp/bcm_aec.conf"
AEC_LIB_GLOBS = (
    "/usr/lib/*/spa-0.2/aec/libspa-aec-webrtc.so",
    "/usr/lib64/spa-0.2/aec/libspa-aec-webrtc.so",
    "/usr/lib/spa-0.2/aec/libspa-aec-webrtc.so",
)

#: SPA-JSON properties for ``pw-cli create-node adapter``. A null-audio-sink
#: whose media.class is a (virtual) source has nothing linked into it, so it
#: produces silence; object.linger keeps it after pw-cli exits.
NULL_MIC_PROPS = (
    "{ factory.name=support.null-audio-sink"
    f" node.name={NULL_MIC_NAME}"
    ' node.description="BCM: brak mikrofonu (cisza)"'
    " media.class=Audio/Source/Virtual"
    " audio.position=[MONO]"
    " object.linger=true }"
)

WATCHDOG_INTERVAL_S = 10.0
#: Retry spacing while PipeWire has not answered yet (cold boot race).
STARTUP_RETRY_S = 1.0
#: Failed pw-dump rounds before ``state: error`` is published. Keeps a slow
#: user session from flashing "error" while still unblocking openauto's
#: 5 s wait for a mic state.
ERROR_AFTER_FAILURES = 3
SET_DEFAULT_ATTEMPTS = 10
SET_DEFAULT_DELAY_S = 0.3
#: How long the AEC child gets to show its nodes before we give up on it.
AEC_APPEAR_TIMEOUT_S = 4.0
#: Wait for PipeWireController to finish its output setup before the first
#: pass (prepare_output's unmute/volume and the EQ start use the sink id a
#: profile switch would replace).
SINK_WAIT_S = 3.0
#: bcm_null_mic could not be created (e.g. pw-cli during a PipeWire /
#: WirePlumber restart): retry after this long, doubling up to the cap. A
#: one-off failure must not leave the router without a silent source — and
#: pipewire-pulse falling back to a sink monitor — until BCM restarts.
NULL_RETRY_S = 60.0
NULL_RETRY_MAX_S = 600.0
#: autoapp opens its streams a moment after "Device Connected".
DIAG_DELAY_S = 3.0
CMD_TIMEOUT_S = 8.0

#: What we accept as a node name in argv and in the generated AEC config.
#: PipeWire already sanitises ALSA names to this set; anything else (a quote,
#: a brace) could break out of the SPA-JSON string, so it is refused.
_SAFE_NODE_NAME = re.compile(r"^[A-Za-z0-9_.:+@-]{1,200}$")

_MAX_PATTERN_LEN = 200


def _as_int(value: Any) -> Optional[int]:
    """``device.id`` & co. — int in pw-dump, sometimes a string."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def aec_mode(value: Any) -> str:
    """``audio.mic_echo_cancel`` as ``off`` | ``auto`` | ``on``."""
    if value is True:
        return "on"
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("auto",):
            return "auto"
        if v in ("true", "on", "yes", "1"):
            return "on"
    return "off"


def find_aec_lib(patterns: tuple[str, ...] = AEC_LIB_GLOBS) -> Optional[str]:
    """Path of libspa-aec-webrtc.so, or None (pipewire's AEC plugin missing)."""
    for pattern in patterns:
        for path in sorted(glob.glob(pattern)):
            return path
    return None


# ── pw-dump model ─────────────────────────────────────────────────────────


class PwGraph:
    """The parts of one ``pw-dump`` the router needs, as plain dicts.

    ``nodes``: id -> props; ``devices``: id -> {props, profiles, profile};
    ``links``: [(output-node-id, input-node-id)]; ``defaults``: metadata key
    (``default.audio.source`` …) -> node name.
    """

    def __init__(self, objects: list[dict]) -> None:
        self.nodes: dict[int, dict] = {}
        self.devices: dict[int, dict] = {}
        self.links: list[tuple[int, int]] = []
        self.defaults: dict[str, str] = {}
        for obj in objects:
            otype = str(obj.get("type", ""))
            oid = obj.get("id")
            if otype.endswith("Interface:Node") and isinstance(oid, int):
                self.nodes[oid] = _obj_props(obj)
            elif otype.endswith("Interface:Device") and isinstance(oid, int):
                info = obj.get("info") if isinstance(obj.get("info"), dict) else {}
                params = info.get("params") if isinstance(info.get("params"), dict) else {}
                active = ""
                for entry in params.get("Profile") or []:
                    if isinstance(entry, dict) and isinstance(entry.get("name"), str):
                        active = entry["name"]
                        break
                self.devices[oid] = {
                    "props": _obj_props(obj),
                    "profiles": _parse_enum_profiles(info),
                    "profile": active,
                }
            elif otype.endswith("Interface:Link"):
                info = obj.get("info") if isinstance(obj.get("info"), dict) else {}
                out_id = info.get("output-node-id")
                in_id = info.get("input-node-id")
                if isinstance(out_id, int) and isinstance(in_id, int):
                    self.links.append((out_id, in_id))
            elif otype.endswith("Interface:Metadata"):
                props = obj.get("props") if isinstance(obj.get("props"), dict) else {}
                if props.get("metadata.name") != "default":
                    continue
                for entry in obj.get("metadata") or []:
                    if not isinstance(entry, dict):
                        continue
                    name = _metadata_name(entry.get("value"))
                    key = entry.get("key")
                    if isinstance(key, str) and name:
                        self.defaults[key] = name

    @classmethod
    def from_text(cls, text: str) -> "PwGraph":
        return cls(_pw_dump_objects(text))

    def node_id(self, name: str) -> Optional[int]:
        """Id of the node whose node.name is EXACTLY ``name``."""
        for nid, props in self.nodes.items():
            if props.get("node.name") == name:
                return nid
        return None

    def node_name(self, nid: Optional[int]) -> str:
        if nid is None:
            return ""
        return str((self.nodes.get(nid) or {}).get("node.name") or nid)

    def device_of(self, nid: Optional[int]) -> Optional[int]:
        if nid is None:
            return None
        return _as_int((self.nodes.get(nid) or {}).get("device.id"))

    @property
    def default_source(self) -> str:
        return self.defaults.get("default.audio.source", "")

    @property
    def default_sink(self) -> str:
        return self.defaults.get("default.audio.sink", "")


def _metadata_name(value: Any) -> str:
    """``{"name": "x"}`` (pw-dump) or its JSON string form -> ``x``."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return ""
    if isinstance(value, dict) and isinstance(value.get("name"), str):
        return value["name"]
    return ""


# ── pure selection rules ──────────────────────────────────────────────────


def is_mic_candidate(props: dict) -> bool:
    """A real capture device: ALSA ``Audio/Source`` only.

    Never ``bluez_*`` (the phone itself), never a ``.monitor`` (the car's
    own playback), never a virtual/filter node (including our own
    bcm_null_mic / bcm_mic): they all fail the ``alsa_input.`` prefix or the
    explicit checks below.
    """
    if props.get("media.class") != "Audio/Source":
        return False
    name = str(props.get("node.name") or "")
    if not name.startswith("alsa_input."):
        return False
    if ".monitor" in name or "bluez" in name:
        return False
    if str(props.get("node.virtual", "")).lower() == "true":
        return False
    return True


def select_mic(graph: PwGraph, pattern: str,
               output_device: Optional[int]) -> Optional[int]:
    """Node id of the microphone matching ``pattern`` (node.name substring).

    When several inputs match (``alsa_input.usb-`` with a USB DAC that has
    an input of its own AND a dedicated USB mic), the one NOT on the output
    card wins — a separate mic is exactly why someone adds one. Ties are
    broken by name so the choice is stable between watchdog rounds.
    """
    pattern = (pattern or "").strip()
    if not pattern:
        return None
    matches = [(nid, props) for nid, props in graph.nodes.items()
               if is_mic_candidate(props) and pattern in str(props.get("node.name"))]
    if not matches:
        return None

    def rank(item: tuple[int, dict]) -> tuple[bool, str]:
        on_output = (output_device is not None
                     and _as_int(item[1].get("device.id")) == output_device)
        return (on_output, str(item[1].get("node.name")))

    return min(matches, key=rank)[0]


def is_output_only_profile(name: str) -> bool:
    return name.startswith("output:") and "+input:" not in name


def is_duplex_profile(name: str) -> bool:
    return name.startswith("output:") and "+input:" in name


def _output_part(name: str) -> str:
    return name.split("+", 1)[0] if name.startswith("output:") else ""


def _best(profiles: list[dict]) -> Optional[dict]:
    if not profiles:
        return None
    return max(profiles, key=lambda p: (p.get("priority", 0), -p["index"]))


def pick_output_only_profile(profiles: list[dict], current: str) -> Optional[dict]:
    """Output-only profile for a card, keeping the current output if possible.

    ``output:analog-stereo+input:mono-fallback`` -> ``output:analog-stereo``.
    Profiles reported ``available: no`` are never chosen.
    """
    usable = [p for p in profiles
              if is_output_only_profile(p["name"]) and p.get("available") != "no"]
    if not usable:
        return None
    keep = _output_part(current)
    for p in usable:
        if p["name"] == keep:
            return p
    return _best(usable)


def pick_duplex_profile(profiles: list[dict], current: str) -> Optional[dict]:
    """Duplex (output+input) profile, keeping the current output if possible."""
    usable = [p for p in profiles
              if is_duplex_profile(p["name"]) and p.get("available") != "no"]
    if not usable:
        return None
    keep = _output_part(current)
    same = [p for p in usable if _output_part(p["name"]) == keep]
    return _best(same or usable)


def build_aec_conf(mic: str, hw_sink: str) -> str:
    """``pipewire -c`` config hosting libpipewire-module-echo-cancel.

    * capture <- the raw mic (``target.object``),
    * source ``bcm_mic`` = the cleaned mic (what becomes the default source),
    * sink ``bcm_aec_ref`` = the echo reference: the EQ output is retargeted
      here so the canceller hears exactly what the speakers play,
    * playback -> the hardware sink.

    Both names are validated by the caller (_SAFE_NODE_NAME) because they are
    embedded in SPA-JSON strings.
    """
    return f"""# BCM v8.5 — generated echo canceller (do not edit; regenerated by mic_router)
context.properties = {{ log.level = 0 }}

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
  {{ name = libpipewire-module-echo-cancel
    args = {{
      library.name = aec/libspa-aec-webrtc
      monitor.mode = false
      node.description = "BCM AEC"
      capture.props = {{
        node.name = "bcm_aec_capture"
        target.object = "{mic}"
        node.passive = true
      }}
      source.props = {{
        node.name = "{AEC_SOURCE_NAME}"
        node.description = "BCM: mikrofon (AEC)"
        media.class = Audio/Source
      }}
      sink.props = {{
        node.name = "{AEC_REF_SINK_NAME}"
        node.description = "BCM: referencja AEC"
        media.class = Audio/Sink
      }}
      playback.props = {{
        node.name = "bcm_aec_playback"
        target.object = "{hw_sink}"
        node.passive = true
      }}
    }}
  }}
]
"""


def autoapp_snapshot(graph: PwGraph) -> dict[str, Any]:
    """Default sink/source plus autoapp's streams and what they link to."""
    streams = []
    for nid, props in sorted(graph.nodes.items()):
        app = " ".join(str(props.get(k) or "") for k in (
            "application.process.binary", "application.name")).lower()
        if "autoapp" not in app and "openauto" not in app:
            continue
        if not str(props.get("media.class") or "").startswith("Stream/"):
            continue
        peers_out = sorted(graph.node_name(i) for o, i in graph.links if o == nid)
        peers_in = sorted(graph.node_name(o) for o, i in graph.links if i == nid)
        streams.append({
            "id": nid,
            "name": str(props.get("node.name") or nid),
            "media_class": str(props.get("media.class") or ""),
            "to": peers_out,
            "from": peers_in,
        })
    return {"default_sink": graph.default_sink,
            "default_source": graph.default_source,
            "autoapp_streams": streams}


# ── router ────────────────────────────────────────────────────────────────


class MicRouter:
    """Keeps PipeWire's default source on the right microphone (or silence).

    Args:
        config: BCMConfig-like (``get``).
        event_bus: EventBus.
        controller: the PipeWireController (output sink name, sink-id
            refresh, EQ retarget for AEC). Optional — without it profile
            switching and AEC are skipped.
        runner: ``subprocess.run`` compatible (test seam).
        clock / sleep: time seams.
        popen: ``subprocess.Popen`` compatible, for the AEC child.
        aec_lib_finder: returns the libspa-aec-webrtc.so path or None.
    """

    def __init__(self, config: Any, event_bus: Any, controller: Any = None,
                 runner: Callable[..., Any] = subprocess.run,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep,
                 popen: Callable[..., Any] = subprocess.Popen,
                 aec_lib_finder: Callable[[], Optional[str]] = find_aec_lib,
                 aec_conf_path: str = AEC_CONF_PATH) -> None:
        self._config = config
        self._bus = event_bus
        self._controller = controller
        self._runner = runner
        self._clock = clock
        self._sleep = sleep
        self._popen = popen
        self._aec_lib_finder = aec_lib_finder
        self._aec_conf_path = aec_conf_path

        get = config.get if config is not None else (lambda k, d=None: d)
        self.enabled = bool(get("audio.mic_router", False))
        self._pattern = str(get("audio.mic_phone", "") or "").strip()[:_MAX_PATTERN_LEN]
        self._aec_mode = aec_mode(get("audio.mic_echo_cancel", False))
        self._disable_unused = bool(get("audio.mic_disable_unused_inputs", True))

        # _lock: one routing pass at a time (tick() holds it for the whole
        # pass, which can take seconds when PipeWire is slow). stop() never
        # takes it — see stop().
        self._lock = threading.RLock()
        # _aec_lock: only _aec_proc/_aec_mic, held for short spans (Popen,
        # terminate+wait ≤ 4 s), so stop() can kill the AEC child while a
        # pass is still stuck in pw-dump.
        self._aec_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._diag_lock = threading.Lock()

        # Published state (only re-published on change).
        self._state: Optional[dict[str, Any]] = None
        self._input_source: Optional[str] = None
        self._failures = 0
        self._ever_ok = False

        # Memos so a failing step is not retried every 10 s.
        self._null_retry_at: Optional[float] = None    # None = no failure pending
        self._null_backoff = NULL_RETRY_S
        self._null_failures = 0
        self._profile_done: set[tuple[int, str]] = set()
        self._restore_tried: set[int] = set()
        self._sink_refresh_pending = False
        self._last_drift_log: Optional[str] = None
        self._warned: set[str] = set()

        # AEC child.
        self._aec_proc: Any = None
        self._aec_mic: Optional[str] = None
        self._aec_failed_for: Optional[str] = None

    # ── lifecycle ─────────────────────────────────────────────────────────

    @property
    def state(self) -> Optional[dict[str, Any]]:
        return dict(self._state) if self._state else None

    def start(self) -> bool:
        """Start the watchdog thread. False (and no side effects) if disabled."""
        if not self.enabled:
            log.debug("Mic router disabled (audio.mic_router=false)")
            return False
        if self._thread is not None:
            return True
        self._bus.subscribe("multimedia.openauto_status", self._on_openauto_status)
        self._bus.subscribe("power.shutting_down", self._on_shutdown)
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="mic-router")
        self._thread.start()
        log.info("Mic router started (mic_phone=%r, echo_cancel=%s, "
                 "disable_unused_inputs=%s)", self._pattern, self._aec_mode,
                 self._disable_unused)
        return True

    def stop(self, restore_eq: bool = True) -> None:
        """Stop the watchdog and the AEC child; hand the EQ back to the hw sink.

        Never waits for a routing pass: both ``power.shutting_down`` handlers
        (ours and volume.py's) run on the shared event-bus dispatcher thread,
        and a pass blocked in pw-dump on a wedged PipeWire — the very "audio
        hangs" case — would stall shutdown for tens of seconds. ``_stop``
        makes the pass bail out at its next check; the AEC child is killed
        here under its own small lock, and a pass that was about to start one
        sees ``_stop`` under that lock and does not.
        """
        self._stop.set()
        self._stop_aec(restore_eq=False)
        if restore_eq:
            self._controller_call("set_eq_output_target", None)

    def _on_shutdown(self, topic: str, value: Any, timestamp: float) -> None:
        # The EQ child is being stopped too — retargeting it now would only
        # start a fresh one that outlives BCM.
        if value:
            self.stop(restore_eq=False)

    def _output_ready(self) -> bool:
        """PipeWireController has finished its output setup (or has no flag).

        Its ``output_configured`` event is set at the end of
        _configure_output(): sink chosen, unmuted, levelled, EQ started. A
        card profile switch before that would recreate the sink under a new
        id while prepare_output() still unmutes/levels the old one.
        """
        event = getattr(self._controller, "output_configured", None)
        return not isinstance(event, threading.Event) or event.is_set()

    def _run(self) -> None:
        # Give PipeWireController a moment to set the output up — the first
        # pass decides which input is "unused" by comparing cards.
        deadline = self._clock() + SINK_WAIT_S
        while (self._controller is not None and not self._stop.is_set()
               and (getattr(self._controller, "hardware_sink", None) is None
                    or not self._output_ready())
               and self._clock() < deadline):
            self._stop.wait(0.2)
        while not self._stop.is_set():
            try:
                ok = self.tick()
            except Exception:
                log.exception("Mic router pass failed")
                ok = False
            interval = WATCHDOG_INTERVAL_S if (ok or self._ever_ok or
                                               self._failures >= ERROR_AFTER_FAILURES) \
                else STARTUP_RETRY_S
            self._stop.wait(interval)

    # ── one pass ──────────────────────────────────────────────────────────

    def tick(self) -> bool:
        """One routing pass. Returns False when PipeWire did not answer."""
        if not self.enabled or self._stop.is_set():
            return False
        with self._lock:
            graph = self._dump()
            if self._stop.is_set():
                return False   # stop() arrived while pw-dump ran: touch nothing
            if graph is None:
                self._failures += 1
                if self._failures >= ERROR_AFTER_FAILURES:
                    self._warn_once("pw", "Mic router: pw-dump does not answer — is "
                                    "the PipeWire user session running?")
                    self._publish("error", "", False)
                return False
            self._failures = 0
            self._ever_ok = True

            if self._sink_refresh_pending and self._controller is not None:
                if self._controller_call("refresh_hw_sink_id") is not None:
                    self._sink_refresh_pending = False

            out_sink = getattr(self._controller, "hardware_sink", None) if self._controller else None
            out_dev = graph.device_of(graph.node_id(out_sink)) if out_sink else None
            mic_id = select_mic(graph, self._pattern, out_dev)

            if mic_id is None:
                self._route_none(graph, out_dev)
            else:
                self._route_mic(graph, mic_id, out_dev, out_sink)
            return True

    def _route_none(self, graph: PwGraph, out_dev: Optional[int]) -> None:
        self._stop_aec(restore_eq=True)
        if self._pattern:
            self._warn_once(f"nomic:{self._pattern}",
                            f"Mic router: no input matches audio.mic_phone={self._pattern!r} "
                            "— using silence (bcm_null_mic)")
            if self._output_ready():
                self._restore_output_input(graph, out_dev)
        null_id = graph.node_id(NULL_MIC_NAME)
        if null_id is None:
            null_id = self._create_null_mic()
            if null_id is None:
                if not self._stop.is_set():
                    self._publish("error", NULL_MIC_NAME, False)
                return
            graph = self._dump() or graph
        if self._ensure_default(graph, NULL_MIC_NAME):
            self._publish("none", NULL_MIC_NAME, False)
        else:
            self._publish("error", NULL_MIC_NAME, False)

    def _route_mic(self, graph: PwGraph, mic_id: int, out_dev: Optional[int],
                   out_sink: Optional[str]) -> None:
        mic = graph.node_name(mic_id)
        mic_dev = graph.device_of(mic_id)
        if self._disable_unused and out_dev is not None and mic_dev is not None \
                and mic_dev != out_dev and self._output_ready():
            self._make_output_only(graph, out_dev, mic)

        source = mic
        aec = False
        if self._aec_wanted() and out_sink and _SAFE_NODE_NAME.match(mic) \
                and _SAFE_NODE_NAME.match(out_sink):
            if self._ensure_aec(mic, out_sink):
                source, aec = AEC_SOURCE_NAME, True
        else:
            self._stop_aec(restore_eq=True)

        if self._ensure_default(graph, source):
            self._publish("ok", source, aec)
        else:
            self._publish("error", source, aec)

    # ── steps ─────────────────────────────────────────────────────────────

    def _ensure_default(self, graph: PwGraph, name: str) -> bool:
        """Make ``name`` the default source (re-assert after drift)."""
        current = graph.default_source
        if current == name:
            self._last_drift_log = None
            return True
        if current and self._state is not None and self._last_drift_log != current:
            log.info("Default source drifted to %s — re-asserting %s", current, name)
            self._last_drift_log = current
        return self._set_default_source(name, graph)

    def _set_default_source(self, name: str, graph: Optional[PwGraph] = None) -> bool:
        """Make ``name`` the configured default source; id by EXACT node.name.

        ``wpctl set-default <id>`` for real sources. wpctl (WirePlumber 0.5.8,
        src/tools/wpctl.c) accepts only an exact ``Audio/Source`` class and
        exits 3 ("is not a device node") for ``Audio/Source/Virtual`` — our
        bcm_null_mic. WirePlumber's default-nodes logic does accept virtual
        sources, so for those the same metadata key wpctl would write
        (``default.configured.audio.source``) is set with pw-metadata, as
        pipewire-pulse does for ``pactl set-default-source``.

        Retries (10 × 0.3 s): a node created a moment ago (bcm_null_mic, the
        AEC source, a re-plugged mic) is not always in the graph yet.
        """
        for attempt in range(SET_DEFAULT_ATTEMPTS):
            if self._stop.is_set():
                return False
            if graph is None or attempt > 0:
                graph = self._dump()
            nid = graph.node_id(name) if graph is not None else None
            if nid is not None:
                mclass = str((graph.nodes.get(nid) or {}).get("media.class") or "")
                if mclass == "Audio/Source":
                    argv = ["wpctl", "set-default", str(nid)]
                else:
                    argv = ["pw-metadata", "-n", "default", "0",
                            "default.configured.audio.source",
                            json.dumps({"name": name}), "Spa:String:JSON"]
                rc, _, err = self._run(argv)
                if rc == 0:
                    log.info("Default source -> %s (id %d)", name, nid)
                    return True
                log.debug("%s: rc=%d %s", " ".join(argv[:3]), rc, err.strip())
            if attempt < SET_DEFAULT_ATTEMPTS - 1:
                self._sleep(SET_DEFAULT_DELAY_S)
        self._warn_once(f"default:{name}",
                        f"Mic router: could not make {name} the default source")
        return False

    def _create_null_mic(self) -> Optional[int]:
        """Create the silent source; returns its node id (or None).

        After a failure the next attempt waits NULL_RETRY_S (doubling up to
        NULL_RETRY_MAX_S): bounded cost, but a transient failure — pw-cli
        during a PipeWire/WirePlumber restart — heals by itself. ERROR is
        logged for the first failure only.
        """
        if self._null_retry_at is not None and self._clock() < self._null_retry_at:
            return None
        rc, _, err = self._run(["pw-cli", "create-node", "adapter", NULL_MIC_PROPS])
        if rc != 0:
            self._null_failed(f"pw-cli rc={rc}: {err.strip()}")
            return None
        for attempt in range(SET_DEFAULT_ATTEMPTS):
            if self._stop.is_set():
                return None
            graph = self._dump()
            nid = graph.node_id(NULL_MIC_NAME) if graph is not None else None
            if nid is not None:
                if self._null_failures:
                    log.info("Created silent source %s (id %d) after %d failed "
                             "attempt(s)", NULL_MIC_NAME, nid, self._null_failures)
                else:
                    log.info("Created silent source %s (id %d)", NULL_MIC_NAME, nid)
                self._null_retry_at = None
                self._null_backoff = NULL_RETRY_S
                self._null_failures = 0
                return nid
            if attempt < SET_DEFAULT_ATTEMPTS - 1:
                self._sleep(SET_DEFAULT_DELAY_S)
        self._null_failed("created but never appeared in pw-dump")
        return None

    def _null_failed(self, why: str) -> None:
        self._null_failures += 1
        delay = self._null_backoff
        self._null_retry_at = self._clock() + delay
        self._null_backoff = min(NULL_RETRY_MAX_S, delay * 2)
        if self._null_failures == 1:
            log.error("Mic router: could not create %s (%s) — AA may record the "
                      "speakers' monitor instead of silence; retrying in %.0f s",
                      NULL_MIC_NAME, why, delay)
        else:
            log.debug("Mic router: %s still not created (%s, attempt %d); next "
                      "try in %.0f s", NULL_MIC_NAME, why, self._null_failures, delay)

    def _make_output_only(self, graph: PwGraph, out_dev: int, mic: str) -> None:
        """Drop the output card's (floating, unused) input — once per mic."""
        key = (out_dev, mic)
        if key in self._profile_done:
            return
        device = graph.devices.get(out_dev)
        if device is None:
            return
        self._profile_done.add(key)
        current = device["profile"]
        if not current.startswith("output:") or is_output_only_profile(current):
            return  # already output-only, or pro-audio/off: not ours to judge
        target = pick_output_only_profile(device["profiles"], current)
        if target is None:
            log.info("Output card %d has no output-only profile (current %s) — "
                     "leaving its input enabled", out_dev, current)
            return
        if self._set_profile(out_dev, target, current, "mic is on another card"):
            self._sink_refresh_pending = True
            self._sleep(0.5)
            if self._controller_call("refresh_hw_sink_id") is not None:
                self._sink_refresh_pending = False

    def _restore_output_input(self, graph: PwGraph, out_dev: Optional[int]) -> None:
        """A mic is configured but missing, and the output card is output-only.

        WirePlumber persists profiles set with ``wpctl set-profile``, so a card
        this router once switched to output-only (dedicated mic present back
        then) would hide a mic plugged into its own jack forever. Give its
        input back ONCE per run; the next pass then finds the mic or not.
        """
        if out_dev is None or out_dev in self._restore_tried:
            return
        device = graph.devices.get(out_dev)
        if device is None:
            return
        self._restore_tried.add(out_dev)
        current = device["profile"]
        if not is_output_only_profile(current):
            return
        target = pick_duplex_profile(device["profiles"], current)
        if target is not None and self._set_profile(
                out_dev, target, current, "configured mic not found"):
            self._sink_refresh_pending = True
            # If a dedicated mic comes back later, its input-less profile is
            # wanted again (bounded: this restore runs once per card).
            self._profile_done = {k for k in self._profile_done if k[0] != out_dev}

    def _set_profile(self, dev_id: int, profile: dict, current: str, why: str) -> bool:
        rc, _, err = self._run(["wpctl", "set-profile", str(dev_id), str(profile["index"])])
        if rc != 0:
            log.warning("Card %d: could not switch %s -> %s: %s",
                        dev_id, current, profile["name"], err.strip())
            return False
        log.info("Card %d profile %s -> %s (%s)", dev_id, current, profile["name"], why)
        return True

    # ── echo cancellation (isolated, off by default) ──────────────────────

    def _aec_wanted(self) -> bool:
        if self._aec_mode == "on":
            return True
        if self._aec_mode == "auto":
            try:
                return self._aec_lib_finder() is not None
            except Exception:
                return False
        return False

    def _ensure_aec(self, mic: str, hw_sink: str) -> bool:
        """Run the AEC child for ``mic``; False = use the raw mic."""
        if self._aec_failed_for == mic:
            return False
        with self._aec_lock:
            proc, running_for = self._aec_proc, self._aec_mic
        if proc is not None and running_for == mic and proc.poll() is None:
            return True
        if proc is not None:
            if proc.poll() is not None:
                log.warning("AEC child exited (code %s) — back to the raw mic",
                            proc.poll())
                self._stop_aec(restore_eq=True)
                self._aec_failed_for = mic
                return False
            self._stop_aec(restore_eq=False)   # mic changed: restart below

        start_error = ""
        with self._aec_lock:
            if self._stop.is_set():
                return False   # stop() ran: never leave a child behind
            try:
                atomic_write_text(self._aec_conf_path, build_aec_conf(mic, hw_sink),
                                  mode=0o644)
                proc = self._popen(
                    ["pipewire", "-c", self._aec_conf_path],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    env=_pipewire_env(),
                )
                self._aec_proc, self._aec_mic = proc, mic
            except Exception as e:
                proc, start_error = None, str(e)
        if proc is None:
            return self._aec_give_up(mic, f"cannot start pipewire -c: {start_error}")

        deadline = self._clock() + AEC_APPEAR_TIMEOUT_S
        while not self._stop.is_set():
            graph = self._dump()
            if graph is not None and graph.node_id(AEC_SOURCE_NAME) is not None \
                    and graph.node_id(AEC_REF_SINK_NAME) is not None:
                if self._stop.is_set():
                    break
                self._controller_call("set_eq_output_target", AEC_REF_SINK_NAME)
                log.info("Echo cancellation on: %s -> %s (reference %s -> %s)",
                         mic, AEC_SOURCE_NAME, AEC_REF_SINK_NAME, hw_sink)
                return True
            if proc.poll() is not None or self._clock() >= deadline:
                break
            self._sleep(0.3)
        if self._stop.is_set():
            self._stop_aec(restore_eq=False)   # shutting down: no verdict, no EQ restart
            return False
        return self._aec_give_up(mic, f"{AEC_SOURCE_NAME} never appeared")

    def _aec_give_up(self, mic: str, why: str) -> bool:
        self._stop_aec(restore_eq=True)
        self._aec_failed_for = mic
        log.error("Echo cancellation unavailable (%s) — using the raw mic %s. "
                  "Is libspa-aec-webrtc.so installed? (tools/bcm-audio-diag.sh)",
                  why, mic)
        return False

    def _stop_aec(self, restore_eq: bool) -> None:
        """Kill the AEC child (if any). ``restore_eq`` hands the EQ output
        back to the hardware sink — never while stopping: that would restart
        the EQ child BCM is about to kill (stop() decides that itself)."""
        with self._aec_lock:
            proc, self._aec_proc = self._aec_proc, None
            self._aec_mic = None
            if proc is not None:
                try:
                    proc.terminate()
                    try:
                        proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=2)
                except Exception:
                    log.debug("Stopping the AEC child failed", exc_info=True)
        if restore_eq and not self._stop.is_set():
            self._controller_call("set_eq_output_target", None)

    # ── diagnostics ───────────────────────────────────────────────────────

    def _on_openauto_status(self, topic: str, value: Any, timestamp: float) -> None:
        if value != "connected" or self._stop.is_set():
            return
        if not self._diag_lock.acquire(blocking=False):
            return
        threading.Thread(target=self._diag_worker, daemon=True,
                         name="mic-router-diag").start()

    def _diag_worker(self) -> None:
        try:
            self._sleep(DIAG_DELAY_S)
            self.log_snapshot()
        except Exception:
            log.debug("Audio snapshot failed", exc_info=True)
        finally:
            self._diag_lock.release()

    def log_snapshot(self) -> Optional[dict[str, Any]]:
        """One INFO line with default sink/source and autoapp's links."""
        graph = self._dump()
        if graph is None:
            return None
        snap = autoapp_snapshot(graph)
        snap["mic_state"] = self.state
        streams = "; ".join(
            f"{s['name']} [{s['media_class']}] -> {','.join(s['to']) or '-'}"
            f" <- {','.join(s['from']) or '-'}" for s in snap["autoapp_streams"]
        ) or "no autoapp streams yet"
        log.info("AA audio: default sink=%s source=%s | %s",
                 snap["default_sink"] or "?", snap["default_source"] or "?", streams)
        self._bus.publish("audio.diag", snap)
        return snap

    # ── helpers ───────────────────────────────────────────────────────────

    def _publish(self, state: str, source: str, aec: bool) -> None:
        payload = {"state": state, "source": source, "aec": bool(aec)}
        if payload != self._state:
            self._state = payload
            log.info("Mic state: %s (source=%s, aec=%s)", state, source or "-", aec)
            self._bus.publish("audio.mic_state", dict(payload))
        if source and state != "error" and source != self._input_source:
            self._input_source = source
            self._bus.publish("audio.input_source", source)

    def _controller_call(self, method: str, *args: Any) -> Any:
        fn = getattr(self._controller, method, None) if self._controller else None
        if not callable(fn):
            return None
        try:
            return fn(*args)
        except Exception:
            log.exception("PipeWireController.%s failed", method)
            return None

    def _warn_once(self, key: str, message: str) -> None:
        if key not in self._warned:
            self._warned.add(key)
            log.warning(message)

    def _dump(self) -> Optional[PwGraph]:
        rc, out, _ = self._run(["pw-dump"], timeout=CMD_TIMEOUT_S)
        if rc != 0:
            return None
        objects = _pw_dump_objects(out)
        if not objects:
            return None
        return PwGraph(objects)

    def _run(self, argv: list[str], timeout: float = 5.0) -> tuple[int, str, str]:
        """Run one PipeWire tool in the user session. Never raises."""
        try:
            result = self._runner(argv, capture_output=True, text=True,
                                  timeout=timeout, env=_pipewire_env())
        except FileNotFoundError:
            self._warn_once(f"missing:{argv[0]}",
                            f"Mic router: {argv[0]} not installed — microphone "
                            "routing is limited")
            return -1, "", f"{argv[0]} not found"
        except subprocess.TimeoutExpired:
            return -2, "", f"{argv[0]} timed out"
        except Exception as e:
            return -3, "", str(e)
        return (getattr(result, "returncode", 1),
                getattr(result, "stdout", "") or "",
                getattr(result, "stderr", "") or "")
