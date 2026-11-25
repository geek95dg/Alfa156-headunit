"""Speech synthesis for the spoken announcements (``modules.voice_announce``).

Three engines, tried in this order:

* **Azure Neural** (``voice_announce.azure``: key in /etc/bcm/bcm.env as
  ``BCM_AZURE_TTS_KEY``, region, voice) — a natural, pleasant voice from
  Microsoft's cloud (default ``pl-PL-AgnieszkaNeural``). Needs internet;
  every phrase is cached, so the repeating warnings are fetched once and
  later play offline. A wrong key (401/403) switches it off until the key
  changes; a network error, 429 or 5xx backs off (1 → 15 min) and Piper
  speaks meanwhile;
* **Piper** (``voice_announce.piper_bin`` + ``voice_announce.model``, by
  default the release binary and the Polish voice ``pl_PL-gosia-medium``
  that config/scripts/install-piper.sh puts into /opt/bcm/piper) — a
  natural voice, about 0.3–1 s per sentence on the M910q;
* **espeak-ng** ``-v pl`` (Debian package) — robotic but always there.

Neither present → :meth:`Synthesizer.engine` is ``"none"`` and the module
only logs it (the producers show their own toast anyway).

Security: the text comes from network data (weather, traffic incidents).
It is passed on the child's STDIN, never in argv (no option injection, not
visible in ``ps``), it is cleaned again here (single line, no control
characters, no markup — neither engine is asked to parse SSML: espeak-ng
reads markup only with ``-m``, Piper never), and the children get a minimal
environment — never BCM's, which holds the API keys from /etc/bcm/bcm.env.

Output: a WAV written to a private temporary file (``mkstemp`` = 0600 in a
0700 directory), checked (RIFF/WAVE header, size), then atomically renamed
into a cache keyed by the hash of engine + voice + text. Weather and
traffic warnings repeat the same phrases, so most of them are synthesised
once. The cache is bounded (``cache_max_mb``, the oldest files go first).
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import shutil
import struct
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
import wave
from xml.sax.saxutils import escape as _xml_escape
from typing import Any, Callable, Optional

from src.core.logger import get_logger
from src.core.notifications import clean_text

log = get_logger("audio.tts")

ENGINES = ("azure", "piper", "espeak", "none")

# ── Azure Neural (cloud) ─────────────────────────────────────────────────────
#: Voices offered in Settings (the ones that read Polish well). The two
#: Multilingual ones are English-born voices speaking Polish (lighter, a bit
#: of an accent); Agnieszka and Zofia are native Polish.
AZURE_VOICES = ("pl-PL-AgnieszkaNeural", "pl-PL-ZofiaNeural",
                "en-US-AvaMultilingualNeural", "en-US-EmmaMultilingualNeural")
DEFAULT_AZURE_VOICE = "pl-PL-AgnieszkaNeural"
#: Azure resource regions are lower-case words (westeurope, polandcentral…).
_AZURE_REGION_RE = re.compile(r"[a-z][a-z0-9]{2,30}")
#: Keys are 32 hex characters (older resources) or longer alphanumerics.
_AZURE_KEY_RE = re.compile(r"[A-Za-z0-9]{32,128}")
AZURE_FORMAT = "riff-24khz-16bit-mono-pcm"      # a WAV: wav_ok() checks it
AZURE_TIMEOUT_S = 8.0
AZURE_BACKOFF_S = (60.0, 120.0, 300.0, 900.0)
#: Azure state for the Settings row: why the cloud voice is (not) used.
AZURE_STATES = ("off", "ok", "no_key", "bad_config", "auth", "backoff")
#: The longest text ever handed to an engine (announce_api already caps
#: requests at 240; the fixed test phrase is shorter).
MAX_TTS_TEXT = 300
DEFAULT_PIPER_BIN = "/opt/bcm/piper/piper/piper"
DEFAULT_MODEL = "/opt/bcm/piper/voices/pl_PL-gosia-medium.onnx"
DEFAULT_CACHE_DIR = "data/voice_cache"
DEFAULT_CACHE_MAX_MB = 20
_CACHE_LEAF = "voice_cache"


def cache_subdir(path: str) -> str:
    """The cache always lives in its own ``voice_cache`` directory.

    BCM runs as root and the cache is chmod 0700 and pruned of *.wav: a
    misconfigured ``cache_dir: data`` (or /tmp) must not have its mode
    changed nor unrelated WAV files deleted — so a path that does not end
    in ``voice_cache`` gets it appended.
    """
    path = os.path.normpath(path)
    if os.path.basename(path) != _CACHE_LEAF:
        path = os.path.join(path, _CACHE_LEAF)
    return path
DEFAULT_TIMEOUT_S = 20.0
#: A sane WAV for one sentence is well under this (22 kHz mono ≈ 44 kB/s).
MAX_WAV_BYTES = 8 * 1024 * 1024
_MIN_WAV_BYTES = 44 + 200
#: Markup-like characters are dropped: neither engine should ever be asked
#: to interpret tags, and a reader does not pronounce them anyway.
_MARKUP_RE = re.compile(r"[<>{}\[\]\\`|^~*#_=]")
_CHIME_NAME = "chime_v1.wav"


def tts_text(value: Any) -> str:
    """The text as it may reach an engine: one printable line, no markup,
    at most :data:`MAX_TTS_TEXT` characters ('' = nothing to say)."""
    if not isinstance(value, str):
        return ""
    text = _MARKUP_RE.sub(" ", clean_text(value, MAX_TTS_TEXT * 2))
    text = " ".join(text.split())
    return text[:MAX_TTS_TEXT].strip()


def _child_env() -> dict:
    """A minimal environment for the TTS children — no BCM_* secrets."""
    return {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "HOME": "/nonexistent"}


def _run_stdin(argv: list[str], data: bytes, timeout: float) -> tuple[int, str]:
    """Run ``argv`` with ``data`` on stdin → (returncode, stderr tail).
    -1 = binary missing / not runnable, -2 = timeout (child killed)."""
    try:
        res = subprocess.run(argv, input=data, stdout=subprocess.DEVNULL,
                             stderr=subprocess.PIPE, timeout=timeout,
                             env=_child_env(), close_fds=True)
    except FileNotFoundError:
        return -1, "not found"
    except PermissionError:
        return -1, "not executable"
    except subprocess.TimeoutExpired:
        return -2, "timeout"
    except OSError as exc:
        return -1, type(exc).__name__
    tail = (res.stderr or b"")[-300:].decode("utf-8", "replace")
    return res.returncode, tail


def _azure_post(url: str, headers: dict, body: bytes, timeout: float) -> tuple[int, bytes]:
    """POST to Azure → (HTTP status, body). -1 network error, -2 timeout.
    The answer is read up to MAX_WAV_BYTES + 1 (a larger one is rejected).
    The key travels only in the header; it is never logged."""
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(MAX_WAV_BYTES + 1)
    except urllib.error.HTTPError as exc:
        return exc.code, b""
    except TimeoutError:
        return -2, b""
    except (urllib.error.URLError, OSError, ValueError):
        return -1, b""


def wav_ok(path: str) -> bool:
    """RIFF/WAVE header and a plausible size."""
    try:
        size = os.path.getsize(path)
        if not _MIN_WAV_BYTES <= size <= MAX_WAV_BYTES:
            return False
        with open(path, "rb") as fh:
            head = fh.read(12)
        return head[:4] == b"RIFF" and head[8:12] == b"WAVE"
    except OSError:
        return False


def wav_duration(path: str) -> Optional[float]:
    """Length in seconds, or None when the file cannot be parsed."""
    try:
        with wave.open(path, "rb") as w:
            rate = w.getframerate()
            frames = w.getnframes()
    except (OSError, EOFError, wave.Error):
        return None
    if rate <= 0:
        return None
    return frames / float(rate)


def write_chime(path: str, rate: int = 22050) -> bool:
    """A short two-tone "ding-dong" (≈ 0.35 s, mono 16 bit) so the driver
    knows a message follows. Generated, not shipped: no binary asset."""
    tones = ((880.0, 0.14), (660.0, 0.20))
    frames = bytearray()
    for freq, dur in tones:
        n = int(rate * dur)
        fade = max(1, int(rate * 0.015))
        for i in range(n):
            env = min(1.0, i / fade, (n - i) / fade)
            sample = 0.35 * env * math.sin(2 * math.pi * freq * i / rate)
            frames += struct.pack("<h", int(sample * 32767))
    try:
        fd, tmp = tempfile.mkstemp(prefix=".chime.", suffix=".wav",
                                   dir=os.path.dirname(path) or ".")
        os.close(fd)
        with wave.open(tmp, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(bytes(frames))
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
        return True
    except OSError:
        log.warning("Voice: cannot write the chime to %s", path)
        return False


class Synthesizer:
    """Text → WAV path, with the Piper → espeak-ng fallback and the cache.

    ``runner(argv, stdin_bytes, timeout) -> (rc, stderr)`` and ``which`` are
    seams for the tests (no process is ever started there).
    """

    def __init__(self, *, piper_bin: str = DEFAULT_PIPER_BIN, model: str = DEFAULT_MODEL,
                 espeak_bin: str = "espeak-ng", espeak_voice: str = "pl",
                 cache_dir: str = DEFAULT_CACHE_DIR,
                 cache_max_mb: float = DEFAULT_CACHE_MAX_MB,
                 timeout_s: float = DEFAULT_TIMEOUT_S,
                 azure_key: str = "", azure_region: str = "",
                 azure_voice: str = DEFAULT_AZURE_VOICE,
                 azure_rate: Any = 0, azure_pitch: Any = 0,
                 runner: Optional[Callable[[list, bytes, float], tuple]] = None,
                 which: Callable[[str], Optional[str]] = shutil.which,
                 http: Optional[Callable[[str, dict, bytes, float], tuple]] = None,
                 clock: Callable[[], float] = time.monotonic):
        self.piper_bin = str(piper_bin or "")
        self.model = str(model or "")
        self.espeak_bin = str(espeak_bin or "espeak-ng")
        self.espeak_voice = espeak_voice if re.fullmatch(r"[a-z]{2,3}(-[a-z0-9]{1,8})?",
                                                         str(espeak_voice)) else "pl"
        self.cache_dir = cache_subdir(str(cache_dir or DEFAULT_CACHE_DIR))
        self.cache_max_bytes = int(max(1.0, min(500.0, float(cache_max_mb))) * 1024 * 1024)
        self.timeout_s = max(2.0, min(120.0, float(timeout_s)))
        self._run = runner or _run_stdin
        self._which = which
        self._http = http or _azure_post
        self._clock = clock
        self._azure_fail = 0               # consecutive soft failures
        self._azure_until = 0.0            # backoff deadline (monotonic)
        self._azure_auth_bad = ""          # the key that got 401/403
        self.configure_azure(azure_key, azure_region, azure_voice, azure_rate, azure_pitch)
        self._lock = threading.Lock()
        self._last_engine: Optional[str] = None
        self.last_error = ""

    # -- engine detection ----------------------------------------------------
    def piper_ready(self) -> bool:
        return (bool(self.piper_bin) and os.path.isfile(self.piper_bin)
                and os.access(self.piper_bin, os.X_OK)
                and bool(self.model) and os.path.isfile(self.model)
                # Piper reads the voice's settings from <model>.json; without
                # it the binary fails on every sentence.
                and os.path.isfile(self.model + ".json"))

    def espeak_path(self) -> Optional[str]:
        return self._which(self.espeak_bin)

    # -- Azure ---------------------------------------------------------------
    def configure_azure(self, key: Any, region: Any, voice: Any = DEFAULT_AZURE_VOICE,
                        rate: Any = 0, pitch: Any = 0) -> None:
        """(Re)set the cloud voice; live from config.changed. Invalid values
        are not used (bad_config), never sent anywhere."""
        key = key.strip() if isinstance(key, str) else ""
        region = region.strip().lower() if isinstance(region, str) else ""
        self.azure_key = key if _AZURE_KEY_RE.fullmatch(key) else ""
        self._azure_key_given = bool(key)
        self.azure_region = region if _AZURE_REGION_RE.fullmatch(region) else ""
        self.azure_voice = voice if voice in AZURE_VOICES else DEFAULT_AZURE_VOICE

        def pct(v: Any) -> int:
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                return 0
            return int(max(-30, min(30, round(v))))
        self.azure_rate = pct(rate)
        self.azure_pitch = pct(pitch)
        if self.azure_key != self._azure_auth_bad:
            self._azure_auth_bad = ""      # a new key gets a fresh chance

    def azure_state(self) -> str:
        if not self._azure_key_given:
            return "no_key"
        if not self.azure_key or not self.azure_region:
            return "bad_config"
        if self._azure_auth_bad:
            return "auth"
        if self._clock() < self._azure_until:
            return "backoff"
        return "ok"

    def azure_ssml(self, text: str) -> bytes:
        """The request body. The text is XML-escaped (it is already a single
        clean line without markup, see tts_text) — nothing in it can become
        an SSML tag. Prosody only from the validated integers."""
        body = _xml_escape(text)
        if "Multilingual" in self.azure_voice:
            body = f'<lang xml:lang="pl-PL">{body}</lang>'
        prosody = f'<prosody rate="{self.azure_rate:+d}%" pitch="{self.azure_pitch:+d}%">{body}</prosody>'
        return ('<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
                f'xml:lang="pl-PL"><voice name="{self.azure_voice}">{prosody}</voice></speak>'
                ).encode("utf-8")

    def _synth_azure(self, text: str, out_path: str) -> bool:
        url = f"https://{self.azure_region}.tts.speech.microsoft.com/cognitiveservices/v1"
        headers = {"Ocp-Apim-Subscription-Key": self.azure_key,
                   "Content-Type": "application/ssml+xml",
                   "X-Microsoft-OutputFormat": AZURE_FORMAT,
                   "User-Agent": "bcm-headunit"}
        status, data = self._http(url, headers, self.azure_ssml(text), AZURE_TIMEOUT_S)
        if status == 200 and isinstance(data, (bytes, bytearray)) \
                and _MIN_WAV_BYTES <= len(data) <= MAX_WAV_BYTES:
            with open(out_path, "wb") as fh:
                fh.write(data)
            if wav_ok(out_path):
                self._azure_fail = 0
                self._azure_until = 0.0
                return True
            status = -3
        if status in (401, 403):
            if self._azure_auth_bad != self.azure_key:
                log.error("Voice: Azure refused the key (HTTP %s) — check "
                          "BCM_AZURE_TTS_KEY and voice_announce.azure.region "
                          "(the key belongs to one region). Piper speaks meanwhile.",
                          status)
            self._azure_auth_bad = self.azure_key
            self.last_error = "azure_auth"
            return False
        # Network / 429 / 5xx / bad answer: back off, Piper speaks meanwhile.
        delay = AZURE_BACKOFF_S[min(self._azure_fail, len(AZURE_BACKOFF_S) - 1)]
        self._azure_fail += 1
        self._azure_until = self._clock() + delay
        self.last_error = "azure_unavailable"
        log.warning("Voice: Azure unavailable (%s) — Piper for %.0f s",
                    status if status > 0 else {-1: "network", -2: "timeout",
                                               -3: "bad audio"}.get(status, status), delay)
        return False

    def engines(self) -> list[str]:
        out = []
        if self.azure_state() == "ok":
            out.append("azure")
        if self.piper_ready():
            out.append("piper")
        if self.espeak_path():
            out.append("espeak")
        return out

    def engine(self) -> str:
        """The engine the next phrase would use ('none' = cannot speak).
        Logged once per change (installing Piper later is noticed)."""
        found = self.engines()
        name = found[0] if found else "none"
        if name != self._last_engine:
            if name == "none":
                log.warning("Voice: neither Piper (%s, model %s) nor espeak-ng found — "
                            "announcements are not spoken (only the notifications "
                            "remain). Install: config/scripts/install-piper.sh / "
                            "apt-get install espeak-ng", self.piper_bin, self.model)
            else:
                log.info("Voice: speech engine %s", name)
            self._last_engine = name
        return name

    # -- cache ---------------------------------------------------------------
    def _ensure_dir(self) -> bool:
        try:
            os.makedirs(self.cache_dir, mode=0o700, exist_ok=True)
            os.chmod(self.cache_dir, 0o700)
            return True
        except OSError:
            self.last_error = "cache_dir"
            log.warning("Voice: cannot create the cache directory %s", self.cache_dir)
            return False

    def cache_path(self, engine: str, text: str) -> str:
        if engine == "azure":
            ident = f"{self.azure_voice}|{self.azure_rate}|{self.azure_pitch}"
        elif engine == "piper":
            ident = self.model
        else:
            ident = f"{self.espeak_bin}:{self.espeak_voice}"
        digest = hashlib.sha256(f"{engine}\0{ident}\0{text}".encode("utf-8")).hexdigest()
        return os.path.join(self.cache_dir, f"{digest[:40]}.wav")

    def _prune(self) -> None:
        """Keep the cache under ``cache_max_bytes`` (oldest use first)."""
        try:
            entries = []
            total = 0
            with os.scandir(self.cache_dir) as it:
                for e in it:
                    if not e.name.endswith(".wav") or e.name == _CHIME_NAME \
                            or not e.is_file(follow_symlinks=False):
                        continue
                    st = e.stat(follow_symlinks=False)
                    entries.append((st.st_mtime, st.st_size, e.path))
                    total += st.st_size
            entries.sort()
            for _mtime, size, path in entries:
                if total <= self.cache_max_bytes:
                    break
                try:
                    os.unlink(path)
                    total -= size
                except OSError:
                    pass
        except OSError:
            pass

    # -- synthesis -----------------------------------------------------------
    def _argv(self, engine: str, out_path: str) -> list[str]:
        # argv holds only OUR paths and fixed options — the text goes on stdin.
        if engine == "piper":
            return [self.piper_bin, "--model", self.model, "--output_file", out_path]
        return [self.espeak_path() or self.espeak_bin, "-v", self.espeak_voice,
                "-s", "160", "--stdin", "-w", out_path]

    def _synth_with(self, engine: str, text: str) -> Optional[str]:
        target = self.cache_path(engine, text)
        if wav_ok(target):
            try:
                os.utime(target)          # most recently used = kept longest
            except OSError:
                pass
            return target
        try:
            fd, tmp = tempfile.mkstemp(prefix=".tts.", suffix=".wav", dir=self.cache_dir)
            os.close(fd)
        except OSError:
            self.last_error = "cache_dir"
            return None
        try:
            if engine == "azure":
                if not self._synth_azure(text, tmp):
                    return None
                os.chmod(tmp, 0o600)
                os.replace(tmp, target)
                tmp = ""
                self._prune()
                return target
            rc, err = self._run(self._argv(engine, tmp), (text + "\n").encode("utf-8"),
                                self.timeout_s)
            if rc != 0 or not wav_ok(tmp):
                self.last_error = "timeout" if rc == -2 else "synth_failed"
                log.warning("Voice: %s failed (rc=%s): %s", engine, rc,
                            clean_text(err, 160))
                return None
            os.chmod(tmp, 0o600)
            os.replace(tmp, target)
            tmp = ""
            self._prune()
            return target
        finally:
            if tmp:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

    def synthesize(self, text: Any) -> tuple[Optional[str], str]:
        """``(wav path, engine used)``; ``(None, reason)`` when nothing came out.
        Piper first; if it fails for this phrase, espeak-ng."""
        clean = tts_text(text)
        if not clean:
            return None, "empty"
        with self._lock:
            if not self._ensure_dir():
                return None, "cache_dir"
            engines = self.engines()
            # A phrase Azure already said plays from the cache even while the
            # cloud is unreachable (the point of caching the nice voice).
            if "azure" not in engines and self.azure_key and self.azure_region \
                    and wav_ok(self.cache_path("azure", clean)):
                engines = ["azure"] + engines
            self.engine()                 # log a change of availability once
            if not engines:
                self.last_error = "no_engine"
                return None, "no_engine"
            for name in engines:
                path = self._synth_with(name, clean)
                if path:
                    self.last_error = ""
                    return path, name
            return None, "synth_failed"

    def chime(self) -> Optional[str]:
        """Path of the (generated once) chime WAV, None if it cannot be written."""
        with self._lock:
            if not self._ensure_dir():
                return None
            path = os.path.join(self.cache_dir, _CHIME_NAME)
            if wav_ok(path) or write_chime(path):
                return path
            return None
