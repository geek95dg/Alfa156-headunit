"""Module ``voice_announce``: spoken warnings (Piper / espeak-ng) with ducking.

Weather warnings (src/weather/weather_alerts.py) and traffic incidents
(src/trip/traffic_alerts.py) publish ``voice.announce`` requests (contract:
src/audio/announce_api.py). Until now nothing read them. This module:

1. **Queue** — every request is re-validated (:func:`announce_api.
   validate_request`, the bus may carry anything) and cleaned again for the
   engine (src/audio/tts.py). Then:

   * category switch (``voice_announce.categories.{weather, traffic,
     system}``) and the runtime switch ``voice_announce.enabled`` (Settings
     → "Komunikaty głosowe", live through ``config.changed``);
   * dedupe: the same key (or, without one, the same text) is not spoken
     twice within ``dedupe_s``; a newer request with the key of a queued
     one replaces it;
   * priority: ``high`` (danger — ice, accident, closed road) before
     ``normal`` before ``low``, FIFO within a priority;
   * nothing older than ``max_age_s`` (60 s) is spoken, nor anything past
     the producer's ``expires_ts``;
   * rate limit: at most ``max_per_min`` per minute (``high`` exempt) and
     ``min_gap_s`` between two;
   * never during a phone call (``bt.call_state`` not idle, or
     ``audio.phone_call``): a request waits up to ``call_defer_s`` and is
     then dropped; optionally also while reversing (``parking.active``,
     ``quiet_when_parking``). A call that starts while a phrase plays stops
     the player.

2. **Synthesis** — src/audio/tts.py (Piper → espeak-ng, text on stdin,
   private temp file, hash cache). No engine: logged once, the module
   keeps running and only drops the requests (the producers' toasts stay).

3. **Playback** — ``pw-play`` (else ``paplay``) with the user session's
   PipeWire environment (BCM runs as root — pipewire_ctrl._pipewire_env(),
   without BCM's ``BCM_*`` secrets), as stream ``bcm_voice`` with
   media.role Notification, targeted at
   :meth:`PipeWireController.voice_sink` — the hardware sink, NOT
   ``bcm_eq_sink``, so ducking the music does not duck the voice. Volume
   ``voice_announce.volume`` (0–100 %). An optional chime first.

4. **Ducking** — ``audio.voice_announcement`` True before the chime and
   False after the phrase (always: ``finally``), so DuckingManager (-12 dB,
   smooth 1 s fade back) runs; pipewire_ctrl.MusicDucker, started here,
   applies its ``audio.music_gain`` to the EQ chain's output stream. It
   restores 1.0 at every end of ducking, on stop and at start-up.

Publishes ``voice.status`` (engine, player, queue length, speaking, last
result) for the Settings row. ``POST /api/voice/test`` (web_viewer,
loopback only, rate-limited) calls :meth:`VoiceAnnouncer.speak_test`, which
speaks a FIXED phrase — never text from the request.

Needs ``modules.audio`` (catalog ``requires``): without it the module is not
started (one warning from main.py). Without PipeWire it still synthesises
and the player fails — reported in ``voice.status``.
"""

from __future__ import annotations

import collections
import hashlib
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from src.audio import announce_api
from src.audio import pipewire_ctrl
from src.audio.pipewire_ctrl import VOICE_NODE_NAME, MusicDucker
from src.audio.tts import (DEFAULT_AZURE_VOICE, DEFAULT_CACHE_DIR, DEFAULT_CACHE_MAX_MB,
                           DEFAULT_MODEL, DEFAULT_PIPER_BIN, Synthesizer, tts_text,
                           wav_duration)
from src.core.logger import get_logger
from src.core.notifications import publish_notification

log = get_logger("audio.voice")

STATUS_TOPIC = "voice.status"
VOICE_TOPIC = "audio.voice_announcement"
#: Categories with a Settings switch ("test" is the button, always allowed).
USER_CATEGORIES = ("weather", "traffic", "system")
PRIORITY_RANK = {"high": 0, "normal": 1, "low": 2}
TEST_PHRASE = "Test komunikatów głosowych. Tak będą brzmiały ostrzeżenia."
TEST_KEY = "voice_test"
PLAYERS = ("pw-play", "paplay", "none")
STATUS_RESULTS = ("", "spoken", "no_engine", "synth_failed", "no_player", "play_failed",
                  "interrupted")
#: Volume bounds of the Settings slider — web_viewer validates against these.
VOLUME_MIN = 10
#: Above 100 % the WAV itself is amplified (amplified_wav), never past full
#: scale — the voice gets louder without clipping into distortion.
VOLUME_MAX = 200
#: Defaults (also the bounds the config is clamped to).
DEFAULTS = {
    "volume": 80,             # %, 10–100
    "max_age_s": 60.0,        # 10–300
    "dedupe_s": 300.0,        # 0–3600
    "call_defer_s": 45.0,     # 0–max_age_s
    "max_per_min": 4,         # 1–20
    "min_gap_s": 3.0,         # 0–60
    "max_queue": 16,          # 1–50
}
#: Pause after "ducking on" before the chime: DuckingManager drops the music
#: at once, the wpctl call needs a moment.
DUCK_LEAD_S = 0.3
#: How long a player may run beyond the WAV's length before it is killed.
PLAY_SLACK_S = 5.0
MAX_PLAY_S = 90.0


def _num(value: Any, default: float, lo: float, hi: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    value = float(value)
    if value != value:            # NaN
        return default
    return max(lo, min(hi, value))


@dataclass
class Settings:
    """``voice_announce.*`` clamped; read again on every config.changed."""
    enabled: bool = True
    volume: int = DEFAULTS["volume"]
    categories: dict = field(default_factory=lambda: {c: True for c in USER_CATEGORIES})
    chime: bool = True
    quiet_when_parking: bool = True
    max_age_s: float = DEFAULTS["max_age_s"]
    dedupe_s: float = DEFAULTS["dedupe_s"]
    call_defer_s: float = DEFAULTS["call_defer_s"]
    max_per_min: int = DEFAULTS["max_per_min"]
    min_gap_s: float = DEFAULTS["min_gap_s"]
    max_queue: int = DEFAULTS["max_queue"]


def _azure_args(get: Callable[[str, Any], Any]) -> dict:
    """voice_announce.azure.* → Synthesizer keyword arguments. The key comes
    from /etc/bcm/bcm.env (BCM_AZURE_TTS_KEY → voice_announce.azure.key,
    src/core/config.py SECRET_ENV_MAP); the Synthesizer validates it all."""
    return {
        "azure_key": get("voice_announce.azure.key", "") or "",
        "azure_region": get("voice_announce.azure.region", "") or "",
        "azure_voice": get("voice_announce.azure.voice", DEFAULT_AZURE_VOICE) or DEFAULT_AZURE_VOICE,
        "azure_rate": get("voice_announce.azure.rate", 0),
        "azure_pitch": get("voice_announce.azure.pitch", 0),
    }


def load_settings(get: Callable[[str, Any], Any]) -> Settings:
    cats_raw = get("voice_announce.categories", None)
    cats = {c: True for c in USER_CATEGORIES}
    if isinstance(cats_raw, dict):
        for c in USER_CATEGORIES:
            if isinstance(cats_raw.get(c), bool):
                cats[c] = cats_raw[c]
    max_age = _num(get("voice_announce.max_age_s", None), DEFAULTS["max_age_s"], 10, 300)
    return Settings(
        enabled=get("voice_announce.enabled", True) is not False,
        volume=int(_num(get("voice_announce.volume", None), DEFAULTS["volume"],
                        VOLUME_MIN, VOLUME_MAX)),
        categories=cats,
        chime=get("voice_announce.chime", True) is not False,
        quiet_when_parking=get("voice_announce.quiet_when_parking", True) is not False,
        max_age_s=max_age,
        dedupe_s=_num(get("voice_announce.dedupe_s", None), DEFAULTS["dedupe_s"], 0, 3600),
        call_defer_s=_num(get("voice_announce.call_defer_s", None), DEFAULTS["call_defer_s"],
                          0, max_age),
        max_per_min=int(_num(get("voice_announce.max_per_min", None),
                             DEFAULTS["max_per_min"], 1, 20)),
        min_gap_s=_num(get("voice_announce.min_gap_s", None), DEFAULTS["min_gap_s"], 0, 60),
        max_queue=int(_num(get("voice_announce.max_queue", None), DEFAULTS["max_queue"], 1, 50)),
    )


def amplified_wav(path: str, gain: float) -> str:
    """A copy of the 16-bit WAV ``path`` amplified by ``gain`` but never past
    full scale (the gain is capped at what the loudest sample allows — no
    clipping, no distortion). Cached next to the original
    (``<name>.g<gain>.wav``); on any problem the original path is returned."""
    import os
    import tempfile
    import wave

    import numpy as np

    gain = max(1.0, min(4.0, float(gain)))
    root, _ext = os.path.splitext(path)
    target = f"{root}.g{int(round(gain * 100))}.wav"
    if os.path.isfile(target):
        return target
    try:
        with wave.open(path, "rb") as w:
            params = w.getparams()
            frames = w.readframes(w.getnframes())
        if params.sampwidth != 2 or not frames:
            return path
        data = np.frombuffer(frames, dtype="<i2").astype(np.float32)
        peak = float(np.max(np.abs(data))) if data.size else 0.0
        g = min(gain, 32000.0 / peak) if peak > 0 else gain
        out = np.clip(data * g, -32768, 32767).astype("<i2").tobytes()
        fd, tmp = tempfile.mkstemp(prefix=".amp.", suffix=".wav",
                                   dir=os.path.dirname(path) or ".")
        os.close(fd)
        with wave.open(tmp, "wb") as w:
            w.setparams(params)
            w.writeframes(out)
        os.chmod(tmp, 0o600)
        os.replace(tmp, target)
        return target
    except Exception:
        log.debug("Voice: amplifying %s failed — playing it as is", path, exc_info=True)
        return path


# ── queue (pure: a clock in, decisions out) ───────────────────────────────

@dataclass
class Item:
    req: dict
    dedupe: str
    received: float
    seq: int
    blocked_since: Optional[float] = None


class AnnounceQueue:
    """Priority queue with dedupe, staleness, call deferral and a rate limit.

    Not thread-safe by itself — VoiceAnnouncer holds its lock around it.
    ``clock`` is monotonic, ``wall`` the epoch clock of ``expires_ts``.
    """

    def __init__(self, settings: Settings, *, clock: Callable[[], float] = time.monotonic,
                 wall: Callable[[], float] = time.time):
        self.settings = settings
        self._clock = clock
        self._wall = wall
        self._items: list[Item] = []
        self._seq = 0
        # key → (monotonic time, priority rank, text hash) of what was spoken.
        # WHY rank + text: producers keep one key across an escalation
        # (weather_icing warning → danger, a traffic jam that got worse), and
        # a key-only dedupe would silently swallow the more urgent message.
        self._spoken_keys: dict[str, tuple[float, int, str]] = {}
        self._spoken_at: collections.deque = collections.deque(maxlen=64)
        self.dropped = 0

    def __len__(self) -> int:
        return len(self._items)

    @staticmethod
    def dedupe_key(req: dict) -> str:
        if req.get("key"):
            return "k:" + req["key"]
        return "t:" + hashlib.sha256(req["text"].encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _text_hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]

    def _recently_spoken(self, key: str, req: dict, now: float) -> bool:
        """A duplicate = same key spoken within dedupe_s, not more urgent and
        with the same text. An escalation (higher priority, or new text such
        as a grown traffic delay) gets through — both producers already
        rate-limit escalations upstream, so this does not turn into spam."""
        prev = self._spoken_keys.get(key)
        if prev is None:
            return False
        at, rank, text_hash = prev
        if now - at >= self.settings.dedupe_s:
            return False
        if PRIORITY_RANK[req["priority"]] < rank:     # lower rank = more urgent
            return False
        return self._text_hash(req["text"]) == text_hash

    def offer(self, req: dict) -> str:
        """Queue a VALIDATED request → 'queued' | 'replaced' | 'duplicate' | 'full'."""
        now = self._clock()
        key = self.dedupe_key(req)
        test = req.get("category") == "test"
        if not test and self._recently_spoken(key, req, now):
            return "duplicate"
        for i, it in enumerate(self._items):
            if it.dedupe == key:
                # Newer text for the same thing (e.g. an incident that got
                # worse) replaces the queued one; keeps the higher priority.
                if PRIORITY_RANK[it.req["priority"]] < PRIORITY_RANK[req["priority"]]:
                    req = dict(req, priority=it.req["priority"])
                self._items[i] = Item(req, key, now, it.seq, it.blocked_since)
                return "replaced"
        self._seq += 1
        item = Item(req, key, now, self._seq)
        if len(self._items) >= self.settings.max_queue:
            worst = max(self._items, key=self._order)
            if self._order(item) >= self._order(worst):
                self.dropped += 1
                return "full"
            self._items.remove(worst)
            self.dropped += 1
        self._items.append(item)
        return "queued"

    @staticmethod
    def _order(item: Item) -> tuple:
        return (PRIORITY_RANK[item.req["priority"]], item.seq)

    def _prune(self, now: float, blocked: bool) -> None:
        wall = self._wall()
        keep = []
        for it in self._items:
            if now - it.received > self.settings.max_age_s or it.req["expires_ts"] < wall:
                self.dropped += 1
                continue
            if blocked:
                if it.blocked_since is None:
                    it.blocked_since = now
                elif now - it.blocked_since > self.settings.call_defer_s:
                    self.dropped += 1
                    continue
            keep.append(it)
        self._items = keep
        horizon = max(self.settings.dedupe_s, 60.0)
        for k, (at, _rank, _hash) in list(self._spoken_keys.items()):
            if now - at > horizon:
                del self._spoken_keys[k]

    def _rate_ok(self, item: Item, now: float) -> bool:
        if self._spoken_at and now - self._spoken_at[-1] < self.settings.min_gap_s:
            return False
        if item.req["priority"] == "high" or item.req["category"] == "test":
            return True
        recent = sum(1 for t in self._spoken_at if now - t < 60.0)
        return recent < self.settings.max_per_min

    def next(self, blocked: bool) -> Optional[Item]:
        """The item to speak now (removed from the queue), or None: empty,
        blocked (call / reversing) or rate-limited."""
        now = self._clock()
        self._prune(now, blocked)
        if blocked or not self._items:
            return None
        item = min(self._items, key=self._order)
        if not self._rate_ok(item, now):
            return None
        self._items.remove(item)
        return item

    def requeue(self, item: Item) -> None:
        """Back in front (a call started while it was being synthesised)."""
        if item not in self._items:
            self._items.append(item)

    def mark_spoken(self, item: Item) -> None:
        now = self._clock()
        self._spoken_at.append(now)
        if item.req.get("category") != "test":
            self._spoken_keys[item.dedupe] = (
                now, PRIORITY_RANK[item.req["priority"]],
                self._text_hash(item.req["text"]))

    def clear(self) -> None:
        self.dropped += len(self._items)
        self._items = []


# ── playback ──────────────────────────────────────────────────────────────

def _player_env() -> dict:
    """The user session's PipeWire env, minus BCM's secrets (BCM_* from
    /etc/bcm/bcm.env): a player has no business seeing API keys."""
    env = pipewire_ctrl._pipewire_env()
    return {k: v for k, v in env.items() if not k.startswith("BCM_")}


class Player:
    """Plays one WAV on a given sink; ``stop()`` interrupts it.
    ``popen`` / ``which`` are the test seams."""

    def __init__(self, *, popen: Callable[..., Any] = subprocess.Popen,
                 which: Callable[[str], Optional[str]] = shutil.which,
                 env: Callable[[], dict] = _player_env):
        self._popen = popen
        self._which = which
        self._env = env
        self._lock = threading.Lock()
        self._proc: Any = None
        self._interrupted = False

    def backend(self) -> str:
        for name in ("pw-play", "paplay"):
            if self._which(name):
                return name
        return "none"

    @staticmethod
    def argv(backend: str, path: str, target: Optional[str], volume: float) -> list[str]:
        vol = max(0.0, min(1.0, float(volume)))
        if backend == "pw-play":
            argv = ["pw-play", "--media-role", "Notification",
                    "-P", "{ node.name = " + VOICE_NODE_NAME
                    + " media.name = " + VOICE_NODE_NAME + " }",
                    "--volume", f"{vol:.2f}"]
            if target:
                argv += ["--target", target]
            return argv + [path]
        argv = ["paplay", f"--client-name={VOICE_NODE_NAME}",
                f"--stream-name={VOICE_NODE_NAME}", "--property=media.role=event",
                f"--volume={int(round(vol * 65536))}"]
        if target:
            argv.append(f"--device={target}")
        return argv + [path]

    def play(self, path: str, target: Optional[str], volume: float) -> str:
        """'ok' | 'no_player' | 'failed' | 'interrupted' (timeout = failed)."""
        backend = self.backend()
        if backend == "none":
            return "no_player"
        duration = wav_duration(path) or 10.0
        timeout = min(MAX_PLAY_S, duration + PLAY_SLACK_S)
        with self._lock:
            if self._interrupted:
                return "interrupted"
            try:
                proc = self._popen(self.argv(backend, path, target, volume),
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, env=self._env(),
                                   close_fds=True)
            except OSError:
                return "failed"
            self._proc = proc
        try:
            rc = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self._kill(proc)
            return "failed"
        finally:
            with self._lock:
                self._proc = None
        if self._interrupted:
            return "interrupted"
        return "ok" if rc == 0 else "failed"

    @staticmethod
    def _kill(proc: Any) -> None:
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            try:
                proc.kill()
                proc.wait(timeout=2)
            except Exception:
                pass

    def begin(self) -> None:
        with self._lock:
            self._interrupted = False

    def stop(self) -> None:
        with self._lock:
            self._interrupted = True
            proc = self._proc
        if proc is not None:
            self._kill(proc)


# ── runtime ───────────────────────────────────────────────────────────────

_CALL_IDLE = ("", "idle", "ended", "disconnected", "none")
_INSTANCE: Optional["VoiceAnnouncer"] = None
_INSTANCE_LOCK = threading.Lock()


def get_voice_announcer() -> Optional["VoiceAnnouncer"]:
    """The running module, or None."""
    with _INSTANCE_LOCK:
        return _INSTANCE


class VoiceAnnouncer:
    """Queue consumer thread + synthesis + playback + ducking signal."""

    TICK_S = 0.5

    def __init__(self, event_bus: Any, config: Any = None, *,
                 synth: Optional[Synthesizer] = None, player: Optional[Player] = None,
                 clock: Callable[[], float] = time.monotonic,
                 wall: Callable[[], float] = time.time,
                 sleep: Callable[[float], None] = time.sleep,
                 ducker_factory: Optional[Callable[[Any, Any], Any]] = None):
        self._bus = event_bus
        self._config = config
        get = config.get if config is not None else (lambda _k, d=None: d)
        self.settings = load_settings(get)
        self.synth = synth or Synthesizer(
            piper_bin=get("voice_announce.piper_bin", DEFAULT_PIPER_BIN) or DEFAULT_PIPER_BIN,
            model=get("voice_announce.model", DEFAULT_MODEL) or DEFAULT_MODEL,
            espeak_voice=get("voice_announce.espeak_voice", "pl") or "pl",
            cache_dir=get("voice_announce.cache_dir", DEFAULT_CACHE_DIR) or DEFAULT_CACHE_DIR,
            cache_max_mb=_num(get("voice_announce.cache_max_mb", None),
                              DEFAULT_CACHE_MAX_MB, 1, 500),
            **_azure_args(get))
        self.player = player or Player()
        self._clock = clock
        self._wall = wall
        self._sleep = sleep
        self._ducker_factory = ducker_factory or (lambda pw, bus: MusicDucker(pw, bus))
        self._ducker: Any = None
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.queue = AnnounceQueue(self.settings, clock=clock, wall=wall)
        self._call_state = False
        self._call_bus = False
        self._parking = False
        self._speaking = False
        self._last_result = ""
        self._last_spoken_ts: Optional[float] = None
        self._no_engine_told = False
        self._subs = (
            (announce_api.TOPIC, self._on_request),
            ("bt.call_state", self._on_call_state),
            ("audio.phone_call", self._on_phone_call),
            ("parking.active", self._on_parking),
            ("config.changed", self._on_config_changed),
            ("power.shutting_down", self._on_shutdown),
        )

    # -- bus ---------------------------------------------------------------
    def _on_request(self, topic: str, value: Any, timestamp: float) -> None:
        self.offer(value)

    def offer(self, value: Any) -> str:
        """Validate and queue one request; returns why it was (not) queued."""
        req = announce_api.validate_request(value, now=self._wall())
        if req is None:
            return "invalid"
        if req["category"] == "test":
            # Only speak_test() may use "test" (it bypasses the switches);
            # from the bus it is just another invalid request.
            return "invalid"
        with self._lock:
            if not self.settings.enabled:
                return "disabled"
            if not self.settings.categories.get(req["category"], False):
                return "category_off"
            result = self.queue.offer(req)
        self._wake.set()
        return result

    def speak_test(self) -> str:
        """The Settings button: a FIXED phrase, high priority, ahead of the
        queue. Spoken even with voice_announce.enabled off (the driver asked
        for it), never during a call."""
        req = announce_api.make_request("test", TEST_PHRASE, priority="high",
                                        key=TEST_KEY, ttl_s=60, now=self._wall())
        if req is None:
            return "invalid"
        if self.synth.engine() == "none":
            return "no_engine"
        with self._lock:
            if self._call_active():
                return "call_active"
            result = self.queue.offer(req)
        self._wake.set()
        self._publish_status()
        return result

    def _call_active(self) -> bool:
        return self._call_state or self._call_bus

    def _blocked(self) -> bool:
        return self._call_active() or (self.settings.quiet_when_parking and self._parking)

    def _on_call_state(self, topic: str, value: Any, timestamp: float) -> None:
        state = value.strip().lower() if isinstance(value, str) else ""
        self._call_state = state not in _CALL_IDLE
        self._call_changed()

    def _on_phone_call(self, topic: str, value: Any, timestamp: float) -> None:
        self._call_bus = bool(value)
        self._call_changed()

    def _call_changed(self) -> None:
        if self._call_active():
            # Never over a call: stop the phrase now. Always, not only while
            # _speaking — step() may be between its blocked re-check and
            # begin(); the flag above is set first, so either the re-check
            # sees the call or this stop() lands after begin() and play()
            # returns 'interrupted'. A stop() with nothing playing only marks
            # the player; the next step's begin() clears it.
            self.player.stop()
        self._wake.set()

    def _on_parking(self, topic: str, value: Any, timestamp: float) -> None:
        self._parking = bool(value)
        if self._parking and self.settings.quiet_when_parking:
            self.player.stop()          # same ordering as _call_changed
        self._wake.set()

    def _on_config_changed(self, topic: str, value: Any, timestamp: float) -> None:
        if self._config is None:
            return
        new = load_settings(self._config.get)
        # The voice picked in Settings applies to the next phrase.
        if hasattr(self.synth, "configure_azure"):
            a = _azure_args(self._config.get)
            self.synth.configure_azure(a["azure_key"], a["azure_region"], a["azure_voice"],
                                       a["azure_rate"], a["azure_pitch"])
        with self._lock:
            self.settings = new
            self.queue.settings = new
            if not new.enabled:
                self.queue.clear()
        if not new.enabled and self._speaking:
            self.player.stop()
        self._publish_status()

    def _on_shutdown(self, topic: str, value: Any, timestamp: float) -> None:
        if not value:
            return
        # Never block the shared bus dispatcher (cf. mic_router.stop): the
        # joins (a Piper run, the ducker's wpctl restores) go to a thread;
        # only the instant signals happen here.
        self._wake.set()
        self.player.stop()
        threading.Thread(target=self.stop, name="bcm-voice-stop", daemon=True).start()

    # -- lifecycle -----------------------------------------------------------
    def start(self) -> None:
        global _INSTANCE
        for topic, cb in self._subs:
            self._bus.subscribe(topic, cb)
        with _INSTANCE_LOCK:
            _INSTANCE = self
        self._thread = threading.Thread(target=self._loop, name="bcm-voice", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        global _INSTANCE
        if self._stop.is_set():
            return
        self._stop.set()
        self._wake.set()
        with _INSTANCE_LOCK:
            if _INSTANCE is self:
                _INSTANCE = None
        for topic, cb in self._subs:
            try:
                self._bus.unsubscribe(topic, cb)
            except Exception:
                pass
        self.player.stop()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(5.0)
        if self._speaking:
            self._set_speaking(False)
        # Truthy check: a failed factory leaves False here (see _ensure_ducker).
        if self._ducker:
            self._ducker.stop()

    # -- ducker (needs the audio module's PipeWireController) ----------------
    def _ensure_ducker(self) -> None:
        if self._ducker is not None:
            return
        last = self._bus.get_last("audio._internals")
        internals = last[0] if last else None
        pw = internals.get("pipewire") if isinstance(internals, dict) else None
        if pw is None:
            return
        try:
            self._ducker = self._ducker_factory(pw, self._bus)
            self._ducker.start()
        except Exception:
            log.exception("Voice: cannot start the music ducker — the voice plays "
                          "without ducking")
            self._ducker = False         # do not retry every tick

    def _target(self) -> Optional[str]:
        last = self._bus.get_last("audio._internals")
        internals = last[0] if last else None
        pw = internals.get("pipewire") if isinstance(internals, dict) else None
        try:
            return pw.voice_sink() if pw is not None else None
        except Exception:
            return None

    # -- worker --------------------------------------------------------------
    def _loop(self) -> None:
        self.synth.engine()
        self._publish_status()
        while not self._stop.is_set():
            self._ensure_ducker()
            try:
                self.step()
            except Exception:
                log.exception("Voice: announcement failed")
                if self._speaking:
                    self._set_speaking(False)
            self._wake.wait(self.TICK_S)
            self._wake.clear()

    def _set_speaking(self, on: bool) -> None:
        self._speaking = on
        self._bus.publish(VOICE_TOPIC, on)

    def step(self) -> bool:
        """Speak at most one item; True if something was attempted."""
        with self._lock:
            item = self.queue.next(self._blocked())
        if item is None:
            return False
        engine = self.synth.engine()
        if engine == "none":
            self._last_result = "no_engine"
            if not self._no_engine_told:
                self._no_engine_told = True
                publish_notification(self._bus, "Komunikaty głosowe nie działają",
                                     "Brak syntezatora mowy (Piper, espeak-ng) — "
                                     "uruchom apply-fixes.sh", severity="warning",
                                     icon="volume_off", key="voice_no_engine", ttl=20)
            self._publish_status()
            return True
        self._no_engine_told = False
        path, used = self.synth.synthesize(item.req["text"])
        if path is None:
            self._last_result = "no_engine" if used == "no_engine" else "synth_failed"
            self._publish_status()
            return True
        chime = self.synth.chime() if self.settings.chime else None
        target = self._target()
        volume = self.settings.volume / 100.0
        if volume > 1.0:
            # The player's stream volume stops at 100 %: louder = a gained copy.
            path = amplified_wav(path, volume)
            volume = 1.0
        with self._lock:
            # begin() BEFORE the re-check (see _call_changed): a call that
            # starts from here on interrupts play(); one that started while
            # synthesising (or in chime()/_target()) is caught below.
            self.player.begin()
            self._speaking = True
            if self._blocked():
                # Back in the queue (its deferral clock keeps running there).
                self._speaking = False
                self.queue.requeue(item)
                return True
        self._bus.publish(VOICE_TOPIC, True)
        self._publish_status()
        result = "failed"
        try:
            self._sleep(DUCK_LEAD_S)
            if chime:
                result = self.player.play(chime, target, volume)
            if result in ("ok", "failed") or not chime:
                result = self.player.play(path, target, volume)
        finally:
            self._set_speaking(False)
        with self._lock:
            if result == "ok":
                self.queue.mark_spoken(item)
                self._last_spoken_ts = self._wall()
            elif result == "interrupted" and self._call_active() and self.settings.enabled:
                # Cut off by a call: try again after it (within call_defer_s).
                self.queue.requeue(item)
        self._last_result = {"ok": "spoken", "no_player": "no_player",
                             "interrupted": "interrupted"}.get(result, "play_failed")
        if result not in ("ok", "interrupted"):
            log.warning("Voice: playback %s (player %s, target %s)", result,
                        self.player.backend(), target or "default")
        self._publish_status()
        return True

    # -- status --------------------------------------------------------------
    def status(self) -> dict:
        ducker = self._ducker if self._ducker else None
        with self._lock:
            s = self.settings
            return {
                "enabled": s.enabled,
                "volume": s.volume,
                "categories": dict(s.categories),
                "engine": self.synth.engine(),
                # Engines without the cloud voice (tests' fakes) report "off".
                "azure": self.synth.azure_state() if hasattr(self.synth, "azure_state") else "off",
                "azure_voice": getattr(self.synth, "azure_voice", ""),
                "player": self.player.backend(),
                "queue": len(self.queue),
                "speaking": self._speaking,
                "call_active": self._call_active(),
                "last_result": self._last_result,
                "last_spoken_ts": self._last_spoken_ts,
                "ducking": ducker.mode if ducker is not None else "off",
            }

    def _publish_status(self) -> None:
        try:
            self._bus.publish(STATUS_TOPIC, self.status())
        except Exception:
            log.debug("Voice: status publish failed", exc_info=True)


def start_voice_announce(config=None, event_bus=None, hal=None, **kwargs) -> VoiceAnnouncer:
    """Module entry point — called by main.py's module registry."""
    module = VoiceAnnouncer(event_bus, config)
    module.start()
    return module


__all__ = ["AnnounceQueue", "Player", "VoiceAnnouncer", "Settings", "load_settings",
           "start_voice_announce", "get_voice_announcer", "tts_text", "TEST_PHRASE",
           "STATUS_TOPIC", "USER_CATEGORIES", "VOLUME_MIN", "VOLUME_MAX"]
