"""Real-time 16-band spectrum analyser for the A1 equalizer strip.

What it listens to
------------------
The MONITOR of the sink the music is played into — never a microphone:

* ``bcm_eq_sink`` while the EQ filter-chain is running (the normal case),
* otherwise the hardware sink the :class:`PipeWireController` picked.

The controller passed in by ``src/audio/volume.py`` decides which one
(:meth:`PipeWireController.music_sink`); nothing is hard-coded here.

Why it never showed real sound before v8.5.x (PARTIA 11):

* the capture child was started without ``_pipewire_env()``. BCM runs as
  root, PipeWire lives in the session of uid 1000, so the child never reached
  it and the strip fell back to a fake animation;
* ``pw-record --target 0`` means "do not link" — ``read()`` blocked forever;
* without a target it would have recorded the DEFAULT SOURCE, which is the
  microphone / ``bcm_null_mic`` once the mic router runs, not the music;
* nothing relaunched the child when ``bcm_eq_sink`` disappeared, and it does
  on every preset/gain change and every AEC retarget (the EQ chain restarts);
* ``stop()`` left the process running; every frame was normalised to its own
  peak (an AGC: a quiet passage looked as loud as a loud one); band 0 was the
  DC bin.

How it works now
----------------
``pw-record --target <sink>`` with ``stream.capture.sink=true`` (``parec -d
<sink>.monitor`` as a fallback), f32 stereo at 48 kHz on a pipe; reads are
non-blocking (``select`` with a timeout) so a stalled child can never hang the
thread. A watchdog relaunches the child with backoff on EOF, when the target
node is gone or replaced (new node id = the EQ chain restarted), or after a
long stretch without any data.

DSP: 4096-sample Hann frames with 50 % overlap (a new frame every 2048
samples = 23.4 per second), 16 log-spaced bands 30 Hz - 16 kHz, power per band
in dBFS mapped onto a fixed floor..ceiling window (``audio.spectrum_db_floor``
/ ``audio.spectrum_db_ceiling``), time-based attack/release, published at a
fixed 15 Hz (the dashboard WebSocket rate) rounded to 2 decimals. Silence is
exactly zeros.

Topics
------
* ``audio.spectrum``       — list of 16 floats 0..1
* ``audio.spectrum_state`` — ``{mode: real|simulated|waiting, target, tool,
  reason}``, published on change. ``simulated`` is used ONLY when numpy or
  both capture tools are missing, or PipeWire never came up; it is logged once.
"""

import math
import os
import random
import select
import shutil
import subprocess
import threading
import time
from typing import Any, Optional

from src.audio import pipewire_ctrl
from src.core.event_bus import EventBus
from src.core.logger import get_logger

log = get_logger("audio.spectrum")

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:  # pragma: no cover - numpy is installed on the car
    np = None
    HAS_NUMPY = False

SPECTRUM_BANDS = 16
SAMPLE_RATE = 48000
CHANNELS = 2
# 4096, not 2048: at 48 kHz a 2048-point FFT has 23.4 Hz bins, so the two
# lowest log bands (30-44 Hz, 44-66 Hz) would contain no bin centre at all
# and a 36 Hz kick would light the 50 Hz bar. 4096 gives 11.7 Hz bins (every
# band gets its own bins); the 50 % overlap keeps 23 fresh frames per second,
# more than the 15 Hz publish rate.
FRAME_SIZE = 4096
HOP_SIZE = FRAME_SIZE // 2
BYTES_PER_SAMPLE = 4                     # f32
HOP_BYTES = HOP_SIZE * CHANNELS * BYTES_PER_SAMPLE

BAND_LOW_HZ = 30.0
BAND_HIGH_HZ = 16000.0

PUBLISH_HZ = 15.0                        # = web_viewer broadcast rate
ATTACK_S = 0.03                          # rise time constant
RELEASE_S = 0.30                         # fall time constant
DEFAULT_DB_FLOOR = -70.0
DEFAULT_DB_CEILING = 0.0

# Watchdog / lifecycle. node.passive=true means our stream does not keep the
# sink awake: in a pause the sink suspends and the pipe simply goes quiet. So
# "no data" is first treated as silence; the node is re-checked (pw-dump) on a
# growing interval, and only a long stall relaunches unconditionally.
SILENCE_AFTER_S = 0.25                   # no bytes this long = show silence
NODE_CHECK_MIN_S = 1.5                   # first node re-check after data stops
NODE_CHECK_MAX_S = 15.0                  # longest gap between idle re-checks
STALL_RESTART_S = 30.0                   # relaunch even if the node looks fine
BACKOFF_MIN_S = 0.5
BACKOFF_MAX_S = 10.0
HEALTHY_SESSION_S = 5.0                  # data this long resets the backoff
TOOL_FAIL_WINDOW_S = 2.0                 # exit this soon, node intact = tool broken
TARGET_POLL_S = 1.0                      # waiting for the sink to appear ...
TARGET_POLL_MAX_S = 5.0                  # ... growing to this (pw-dump is not free)
RETARGET_DEBOUNCE_S = 1.0                # EQ restart = a short hw-sink blip
PW_GIVE_UP_S = 120.0                     # ~ PipeWireController background retry
SIMULATED_RECHECK_S = 5.0

CAPTURE_NODE_NAME = "bcm_spectrum"
# _node_id() result when the sink list could not be read at all (pw-dump and
# wpctl both failed). Distinct from None = "listed, but not there".
_NODE_UNKNOWN = object()
CAPTURE_TOOLS = ("pw-record", "parec")


# --------------------------------------------------------------------------- #
# DSP helpers (pure, unit-tested)                                             #
# --------------------------------------------------------------------------- #

def band_edges_hz(n_bands: int = SPECTRUM_BANDS, lo: float = BAND_LOW_HZ,
                  hi: float = BAND_HIGH_HZ) -> list[float]:
    """``n_bands + 1`` log-spaced edges from ``lo`` to ``hi``."""
    ratio = (hi / lo) ** (1.0 / n_bands)
    return [lo * ratio ** i for i in range(n_bands + 1)]


def band_bins(frame_size: int = FRAME_SIZE, rate: int = SAMPLE_RATE,
              edges: Optional[list[float]] = None) -> list[tuple[int, int]]:
    """rfft bin ranges ``[lo, hi)`` for each band.

    A bin belongs to the band its centre frequency falls in. Guarantees, also
    for other frame sizes: bin 0 (DC) is never used, ranges do not overlap,
    every band has at least one bin, nothing runs past Nyquist.
    """
    edges = edges or band_edges_hz()
    df = rate / frame_size
    n_bins = frame_size // 2 + 1
    out: list[tuple[int, int]] = []
    prev_hi = 1                                   # skip DC
    for i in range(len(edges) - 1):
        lo = max(prev_hi, math.ceil(edges[i] / df))
        hi = max(lo + 1, math.ceil(edges[i + 1] / df))
        lo = min(lo, n_bins - 1)
        hi = min(hi, n_bins)
        if hi <= lo:                              # only at absurd sizes
            lo, hi = n_bins - 1, n_bins
        out.append((lo, hi))
        prev_hi = hi
    return out


class SpectrumDSP:
    """Frames -> band dBFS -> 0..1 levels with attack/release smoothing."""

    def __init__(self, db_floor: float = DEFAULT_DB_FLOOR,
                 db_ceiling: float = DEFAULT_DB_CEILING,
                 tilt_db_per_oct: float = 0.0,
                 frame_size: int = FRAME_SIZE, rate: int = SAMPLE_RATE):
        if db_ceiling <= db_floor:
            log.warning("spectrum: db ceiling %.1f <= floor %.1f — using defaults",
                        db_ceiling, db_floor)
            db_floor, db_ceiling = DEFAULT_DB_FLOOR, DEFAULT_DB_CEILING
        self.db_floor = float(db_floor)
        self.db_ceiling = float(db_ceiling)
        self.frame_size = frame_size
        self.rate = rate
        self.bins = band_bins(frame_size, rate)
        self.window = np.hanning(frame_size).astype(np.float64)
        # One-sided power of a full-scale sine (amplitude 1) through this
        # window, summed over its bins: N * sum(w^2) / 4 (Parseval). Dividing
        # by it makes a full-scale sine read 0 dBFS in its band.
        self._ref = frame_size * float(np.sum(self.window ** 2)) / 4.0
        edges = band_edges_hz()
        centres = [math.sqrt(edges[i] * edges[i + 1]) for i in range(SPECTRUM_BANDS)]
        # Optional mild tilt around 1 kHz (+x dB per octave up, -x down). Log
        # bands already make pink noise flat, so the default is 0.
        self._tilt = np.array([tilt_db_per_oct * math.log2(c / 1000.0) for c in centres])
        self._starts = np.array([b[0] for b in self.bins])
        self._stops = np.array([b[1] for b in self.bins])
        self.levels = np.zeros(SPECTRUM_BANDS)

    def band_db(self, mono: "np.ndarray") -> "np.ndarray":
        """dBFS per band for one frame of ``frame_size`` mono samples."""
        x = np.nan_to_num(np.asarray(mono, dtype=np.float64), nan=0.0,
                          posinf=0.0, neginf=0.0)
        x = np.clip(x, -1.0, 1.0)
        spec = np.fft.rfft(x * self.window)
        power = spec.real ** 2 + spec.imag ** 2
        csum = np.concatenate(([0.0], np.cumsum(power)))
        band_p = (csum[self._stops] - csum[self._starts]) / self._ref
        return 10.0 * np.log10(band_p + 1e-20) + self._tilt

    def db_to_level(self, db: "np.ndarray") -> "np.ndarray":
        lvl = (np.asarray(db) - self.db_floor) / (self.db_ceiling - self.db_floor)
        return np.clip(lvl, 0.0, 1.0)

    def smooth(self, target: "np.ndarray", dt: float) -> "np.ndarray":
        """Move ``levels`` toward ``target``: fast up, slow down, by time."""
        dt = max(0.0, float(dt))
        a_up = 1.0 - math.exp(-dt / ATTACK_S)
        a_dn = 1.0 - math.exp(-dt / RELEASE_S)
        rising = target > self.levels
        alpha = np.where(rising, a_up, a_dn)
        self.levels = self.levels + alpha * (target - self.levels)
        # Snap tiny tails to exact zero so silence really publishes zeros.
        self.levels[self.levels < 0.005] = 0.0
        return self.levels

    def feed(self, mono_frame: "np.ndarray", dt: float) -> "np.ndarray":
        return self.smooth(self.db_to_level(self.band_db(mono_frame)), dt)

    def feed_silence(self, dt: float) -> "np.ndarray":
        return self.smooth(np.zeros(SPECTRUM_BANDS), dt)


def capture_argv(tool: str, target: str) -> list[str]:
    """Command line that records the MONITOR of sink ``target`` to stdout.

    Never ``--target 0`` ("do not link") and never without a target (that
    records the default source = the microphone).
    """
    if tool == "pw-record":
        # stream.capture.sink: --target names a sink, record its monitor.
        # node.passive: do not keep the sink/card awake just for the bars.
        # node.dont-reconnect: when the EQ chain restarts, do not let
        # WirePlumber move us somewhere else — go idle, the watchdog
        # relaunches us on the new node.
        props = ("{ stream.capture.sink=true node.name=%s node.passive=true "
                 "node.dont-reconnect=true }" % CAPTURE_NODE_NAME)
        return ["pw-record", "--target", target, "-P", props,
                "--format", "f32", "--rate", str(SAMPLE_RATE),
                "--channels", str(CHANNELS), "-"]
    if tool == "parec":
        return ["parec", "-d", f"{target}.monitor", "--format=float32le",
                f"--rate={SAMPLE_RATE}", f"--channels={CHANNELS}", "--raw",
                f"--client-name={CAPTURE_NODE_NAME}", "--latency-msec=50",
                # --no-move (PA_STREAM_DONT_MOVE -> node.dont-reconnect in
                # pipewire-pulse): same reason as on pw-record. Without it,
                # when the EQ chain restarts the stream is moved to another
                # source and keeps delivering data, so the watchdog would
                # never notice. With it parec ends and is relaunched on the
                # new node. (Standard pacat option; not yet checked with
                # `parec --help` on the car.)
                "--no-move"]
    raise ValueError(f"unknown capture tool {tool!r}")


# --------------------------------------------------------------------------- #
# Analyser                                                                    #
# --------------------------------------------------------------------------- #

class SpectrumAnalyzer:
    """Owns the capture child, the watchdog and the 15 Hz publisher."""

    def __init__(self, event_bus: EventBus, controller: Any = None,
                 config: Any = None):
        self._event_bus = event_bus
        self._pw = controller
        cfg = (lambda k, d: config.get(k, d)) if config is not None else (lambda k, d: d)
        self._db_floor = _as_float(cfg("audio.spectrum_db_floor", DEFAULT_DB_FLOOR),
                                   DEFAULT_DB_FLOOR)
        self._db_ceiling = _as_float(cfg("audio.spectrum_db_ceiling", DEFAULT_DB_CEILING),
                                     DEFAULT_DB_CEILING)
        self._tilt = _as_float(cfg("audio.spectrum_tilt_db_per_oct", 0.0), 0.0)

        self._thread: Optional[threading.Thread] = None
        # The thread that currently owns the capture state. stop() may give
        # up waiting for a thread stuck in pw-dump (up to ~13 s); a later
        # start() then makes a new owner and the old thread exits at its
        # next check instead of running a second capture loop on the same
        # _proc / _dsp / _tool_idx.
        self._owner: Optional[threading.Thread] = None
        self._running = False
        self._stop_evt = threading.Event()
        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None
        self._state: Optional[dict] = None
        self._last_pub_zero = False
        self._tool_idx = 0
        self._backoff = BACKOFF_MIN_S
        self._pw_down_since: Optional[float] = None
        self._wait_s = TARGET_POLL_S
        self._last_launch: Optional[tuple] = None
        self._simulated_logged = False
        self._dsp: Optional[SpectrumDSP] = None
        # Injectable for tests.
        self._clock = time.monotonic
        self._popen = subprocess.Popen
        self._which = shutil.which

    # ------------------------------------------------------------------ #
    # Lifecycle                                                           #
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._stop_evt.clear()
        self._thread = threading.Thread(target=self._run, name="spectrum",
                                        daemon=True)
        self._owner = self._thread
        self._thread.start()
        log.info("SpectrumAnalyzer started")

    def stop(self, timeout: float = 3.0) -> None:
        """Stop the thread AND the capture child (terminate, wait, kill)."""
        self._running = False
        self._owner = None
        self._stop_evt.set()
        with self._lock:
            proc = self._proc
        if proc is not None:
            # Only signal here. Closing the pipe is left to the capture thread
            # (its finally) — closing an fd another thread is select()ing on
            # lets the number be reused and read by the wrong owner.
            _terminate(proc, close=False)
        t = self._thread
        if t is not None and t is not threading.current_thread():
            t.join(timeout)
            if t.is_alive():
                log.warning("Spectrum thread did not stop within %.1f s", timeout)
        self._thread = None
        if t is None or not t.is_alive():
            self._kill_proc()            # thread gone: safe to close the pipe

    def _alive(self) -> bool:
        """True while this thread is the current, running owner."""
        return self._running and threading.current_thread() is self._owner

    @property
    def state(self) -> Optional[dict]:
        return dict(self._state) if self._state else None

    # ------------------------------------------------------------------ #
    # Main loop                                                           #
    # ------------------------------------------------------------------ #

    def _run(self) -> None:
        try:
            self._loop()
        except Exception:
            log.exception("Spectrum thread crashed")
        finally:
            # A superseded thread must not kill the new owner's child.
            if self._owner is None or self._owner is threading.current_thread():
                self._kill_proc()

    def _loop(self) -> None:
        while self._alive():
            reason = self._simulated_reason()
            if reason:
                self._run_simulated(reason)
                continue
            if self._dsp is None:
                self._dsp = SpectrumDSP(self._db_floor, self._db_ceiling, self._tilt)
            if not self._pw.available:
                self._set_state("waiting", None, None, "PipeWire not reachable yet")
                self._publish_zero_once()
                self._wait()
                continue
            target = self._resolve_target()
            node_id = self._node_id(target) if target else None
            if not target or node_id is None or node_id is _NODE_UNKNOWN:
                self._set_state("waiting", target, None,
                                "sink not present yet" if target else "no output sink chosen")
                self._publish_zero_once()
                self._wait()
                continue
            self._wait_s = TARGET_POLL_S
            failed = self._capture_session(target, node_id)
            if self._alive():
                self._sleep(self._backoff)
                # Grow the backoff only for real failures. Routine relaunches
                # (pause stall, EQ restart, retarget) must come back fast, or
                # the bars stay dead for up to BACKOFF_MAX_S after the music
                # resumes / after a few quick preset taps.
                self._backoff = (min(BACKOFF_MAX_S, self._backoff * 2) if failed
                                 else BACKOFF_MIN_S)

    def _pw_down_for(self) -> float:
        """How long PipeWire has been unreachable in the CURRENT outage.

        Measured from when it was last seen down after being up (or from the
        thread start), not from the thread start alone — otherwise a later
        outage would skip the PW_GIVE_UP_S grace and go simulated at once.
        """
        if self._pw.available:
            self._pw_down_since = None
            return 0.0
        now = self._clock()
        if self._pw_down_since is None:
            self._pw_down_since = now
        return now - self._pw_down_since

    def _simulated_reason(self) -> Optional[str]:
        """Why real capture is impossible, or None. Only hard facts count."""
        if not HAS_NUMPY:
            return "numpy not installed"
        if self._pw is None:
            return "no PipeWire controller"
        if not self._tools():
            return "neither pw-record nor parec installed"
        if self._pw_down_for() >= PW_GIVE_UP_S:
            return "PipeWire did not come up"
        return None

    def _tools(self) -> list[str]:
        return [t for t in CAPTURE_TOOLS if self._which(t)]

    def _resolve_target(self) -> Optional[str]:
        try:
            if hasattr(self._pw, "music_sink"):
                return self._pw.music_sink() or None
            return self._pw.hardware_sink or None
        except Exception:
            log.debug("music_sink() failed", exc_info=True)
            return None

    def _node_id(self, name: str):
        """Node id of `name`, None if it is not listed, or _NODE_UNKNOWN.

        list_sink_nodes() returns [] when pw-dump AND the wpctl fallback
        fail (a timeout under load), so an empty list means "could not
        list", not "node gone" — otherwise one pw-dump hiccup would kill a
        capture that works fine. A real removal still ends the child (EOF)
        and is caught on the next successful listing.
        """
        try:
            sinks = self._pw.list_sink_nodes()
        except Exception:
            log.debug("list_sink_nodes() failed", exc_info=True)
            return _NODE_UNKNOWN
        if not sinks:
            return _NODE_UNKNOWN
        for sink in sinks:
            if sink.get("name") == name:
                return str(sink.get("id") or "") or "?"
        return None

    # ------------------------------------------------------------------ #
    # Capture session                                                     #
    # ------------------------------------------------------------------ #

    def _launch(self, tool: str, target: str) -> Optional[subprocess.Popen]:
        argv = capture_argv(tool, target)
        try:
            proc = self._popen(argv, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL,
                               # root -> uid 1000 PipeWire session
                               env=pipewire_ctrl._pipewire_env())
        except (OSError, ValueError) as e:
            log.warning("Spectrum: cannot start %s: %s", tool, e)
            return None
        with self._lock:
            if self._alive():
                self._proc = proc
                return proc
        _terminate(proc)                   # stop() / a newer start() raced the launch
        return None

    def _capture_session(self, target: str, node_id: str) -> bool:
        """Run one capture child. Returns True if it ended in a real failure."""
        tools = self._tools()
        if not tools:
            return True
        tool = tools[self._tool_idx % len(tools)]
        proc = self._launch(tool, target)
        if proc is None:
            self._tool_idx += 1
            return True
        # Info once per tool+target; the routine relaunches during a long
        # pause (see STALL_RESTART_S) would otherwise fill the journal.
        key = (tool, target)
        (log.info if key != self._last_launch else log.debug)(
            "Spectrum capture: %s on monitor of %s (node %s)", tool, target, node_id)
        self._last_launch = key
        self._set_state("real", target, tool, "")
        got_data = False
        reason = "stopped"
        t0 = self._clock()
        try:
            got_data, reason = self._pump(proc, target, node_id, tool)
        except Exception as e:
            reason = f"error: {e}"
            log.warning("Spectrum capture error: %s", e)
        finally:
            self._kill_proc(proc)
        if not self._alive():
            return False
        lasted = self._clock() - t0
        node_changed = reason in ("retarget", "target gone", "target replaced")
        failed = False
        if reason in ("eof", "exited") or reason.startswith("error"):
            # Did the child end because its node went away (EQ restart with
            # dont-reconnect / --no-move — expected), or did it break by
            # itself? Only the latter is a failure.
            current = self._node_id(target)
            if current is not _NODE_UNKNOWN and current != node_id:
                node_changed = True
                reason = "target gone" if current is None else "target replaced"
            else:
                failed = not (got_data and lasted >= HEALTHY_SESSION_S)
                if not got_data and lasted < TOOL_FAIL_WINDOW_S:
                    # Exits right away with the node intact: the tool itself
                    # does not work here — try the other one next.
                    self._tool_idx += 1
        if node_changed:
            # Prefer pw-record again: it is the passive stream (lets the sink
            # and DAC suspend in a pause). A single EOF caused by a node
            # replacement must not leave us on parec for good.
            self._tool_idx = 0
        if reason == "stall":
            log.debug("Spectrum capture idle for %.0f s — relaunching", STALL_RESTART_S)
            return False                           # still "real": just a pause
        log.info("Spectrum capture ended (%s) — relaunching", reason)
        self._set_state("waiting", target, None, reason)
        if failed:
            # A real failure is followed by a growing backoff (up to
            # BACKOFF_MAX_S): drop the bars instead of freezing the last
            # frame mid-height while nothing is captured. Routine relaunches
            # keep the frame so an EQ preset tap does not flicker.
            self._publish_zero_once()
        return failed

    def _pump(self, proc: subprocess.Popen, target: str,
              node_id: str, tool: str = "pw-record") -> tuple[bool, str]:
        """Read, analyse, publish until something calls for a relaunch."""
        dsp = self._dsp
        fd = proc.stdout.fileno()
        buf = bytearray()
        history = np.zeros(FRAME_SIZE - HOP_SIZE)
        hop_dt = HOP_SIZE / SAMPLE_RATE
        period = 1.0 / PUBLISH_HZ
        now = self._clock()
        last_data = now
        last_tick = now
        next_pub = now
        next_check = now + NODE_CHECK_MIN_S
        check_every = NODE_CHECK_MIN_S
        # pw-record: no pw-dump while data flows. It used to re-check the
        # node every 15 s even during music, but a full pw-dump walks every
        # node's params in the user's PipeWire and, with the mic router's
        # own dump, was the periodic load BCM put on the graph while music
        # played (suspected in the "music stutters now and then" report).
        # Not needed: the stream is node.dont-reconnect, so a replaced EQ
        # chain ends the child (EOF) instead of moving it, and a retarget is
        # caught by _resolve_target() below, which reads BCM's own state.
        # parec (fallback only): --no-move is not verified on the car, so a
        # moved stream could keep delivering data — keep the slow live check.
        live_every = NODE_CHECK_MAX_S if tool == "parec" else None
        next_live_check = now + live_every if live_every else None
        got_data = False
        mismatch_since: Optional[float] = None
        while self._alive():
            timeout = min(0.1, max(0.0, next_pub - self._clock()))
            try:
                ready, _, _ = select.select([fd], [], [], timeout)
            except (OSError, ValueError):
                return got_data, "eof"          # fd closed by stop()
            now = self._clock()
            if ready:
                try:
                    chunk = os.read(fd, 65536)
                except OSError:
                    return got_data, "eof"
                if not chunk:
                    return got_data, "eof"
                buf += chunk
                last_data = now
                got_data = True
                check_every = NODE_CHECK_MIN_S
                next_check = now + check_every
                while len(buf) >= HOP_BYTES:
                    block = np.frombuffer(bytes(buf[:HOP_BYTES]), dtype="<f4")
                    del buf[:HOP_BYTES]
                    mono = block.reshape(-1, CHANNELS).mean(axis=1)
                    frame = np.concatenate((history, mono))
                    history = frame[HOP_SIZE:]
                    dsp.feed(frame, hop_dt)
                last_tick = now
            elif proc.poll() is not None:
                return got_data, "exited"

            idle = now - last_data
            if idle >= SILENCE_AFTER_S:
                dsp.feed_silence(now - last_tick)
                last_tick = now

            if now >= next_pub:
                self._publish(dsp.levels)
                next_pub += period
                if next_pub < now:                   # fell behind: resync
                    next_pub = now + period

            # The EQ child is restarted by stopping the old one first, so
            # music_sink() reads "hardware sink" for a moment; only a lasting
            # change of target is a real retarget.
            if self._resolve_target() != target:
                if mismatch_since is None:
                    mismatch_since = now
                elif now - mismatch_since >= RETARGET_DEBOUNCE_S:
                    return got_data, "retarget"
            else:
                mismatch_since = None
            idle_check = idle >= NODE_CHECK_MIN_S and now >= next_check
            live_check = next_live_check is not None and now >= next_live_check
            if idle_check or live_check:
                current = self._node_id(target)
                if current is not _NODE_UNKNOWN and current != node_id:
                    return got_data, "target gone" if current is None else "target replaced"
                if idle_check:
                    check_every = min(NODE_CHECK_MAX_S, check_every * 2)
                    next_check = now + check_every
                if live_every:
                    next_live_check = now + live_every
            if idle >= STALL_RESTART_S:
                return got_data, "stall"
        return got_data, "stopped"

    def _kill_proc(self, own: Optional[subprocess.Popen] = None) -> None:
        """Terminate the capture child. With `own`, terminate that one and
        clear the shared slot only if it still holds it (a newer owner may
        have launched its own child meanwhile)."""
        with self._lock:
            if own is None:
                proc, self._proc = self._proc, None
            else:
                proc = own
                if self._proc is own:
                    self._proc = None
        if proc is not None:
            _terminate(proc)

    # ------------------------------------------------------------------ #
    # Publishing                                                          #
    # ------------------------------------------------------------------ #

    def _publish(self, levels) -> None:
        values = [round(float(v), 2) for v in levels]
        zero = not any(values)
        if zero and self._last_pub_zero:
            return                       # one zero frame is enough
        self._last_pub_zero = zero
        self._event_bus.publish("audio.spectrum", values)

    def _publish_zero_once(self) -> None:
        if self._dsp is not None:
            self._dsp.levels = np.zeros(SPECTRUM_BANDS)
        self._publish([0.0] * SPECTRUM_BANDS)

    def _set_state(self, mode: str, target: Optional[str], tool: Optional[str],
                   reason: str) -> None:
        state = {"mode": mode, "target": target, "tool": tool, "reason": reason}
        if state == self._state:
            return
        self._state = state
        self._event_bus.publish("audio.spectrum_state", dict(state))

    def _sleep(self, seconds: float) -> None:
        self._stop_evt.wait(max(0.0, seconds))

    def _wait(self) -> None:
        """Sleep while waiting for PipeWire / the sink, polling less and less."""
        self._sleep(self._wait_s)
        self._wait_s = min(TARGET_POLL_MAX_S, self._wait_s * 2)

    # ------------------------------------------------------------------ #
    # Simulated mode — only when real capture is impossible               #
    # ------------------------------------------------------------------ #

    def _run_simulated(self, reason: str) -> None:
        if not self._simulated_logged:
            log.warning("Spectrum: no real capture (%s) — showing a simulated "
                        "animation", reason)
            self._simulated_logged = True
        self._set_state("simulated", None, None, reason)
        bands = [0.0] * SPECTRUM_BANDS
        t = 0.0
        period = 1.0 / PUBLISH_HZ
        next_check = self._clock() + SIMULATED_RECHECK_S
        while self._alive():
            if self._clock() >= next_check:
                next_check = self._clock() + SIMULATED_RECHECK_S
                if self._simulated_reason() != reason:
                    return               # e.g. PipeWire came up late: go real
            ev = self._event_bus.get_last("bt.media_playing")
            playing = bool(ev[0]) if ev else False
            new = []
            for i in range(SPECTRUM_BANDS):
                if playing:
                    base = 0.3 + 0.4 * math.sin(t * 1.5 + i * 0.7)
                    new.append(max(0.0, min(1.0, base + random.uniform(-0.15, 0.15))))
                else:
                    new.append(0.0)
            bands = [max(b, old * 0.7) for b, old in zip(new, bands)]
            bands = [b if b >= 0.005 else 0.0 for b in bands]
            self._publish(bands)
            t += period
            self._sleep(period)


def _terminate(proc: subprocess.Popen, close: bool = True) -> None:
    """terminate -> wait -> kill -> wait, then close our end of the pipe."""
    try:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=1.5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=1.5)
    except Exception:
        log.debug("Spectrum: killing capture child failed", exc_info=True)
    if not close:
        return
    try:
        if proc.stdout:
            proc.stdout.close()
    except Exception:
        pass


def _as_float(value: Any, default: float) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default
