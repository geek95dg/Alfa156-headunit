"""Real-time FFT spectrum analyzer — captures PipeWire audio, computes 16-band spectrum.

Uses pw-record (or parec fallback) to capture the default sink monitor,
then bins FFT output into 16 frequency bands for the dashboard visualizer.
Falls back to simulated data if capture or numpy is unavailable.
"""

import struct
import subprocess
import threading
import time
from typing import Any, Optional

from src.core.event_bus import EventBus
from src.core.logger import get_logger

log = get_logger("audio.spectrum")

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    log.info("numpy not available — spectrum will use simulated data")

SPECTRUM_BANDS = 16
SAMPLE_RATE = 22050
CHUNK_SIZE = 1024

BAND_EDGES = [
    20, 40, 60, 90, 130, 180, 250, 350,
    500, 700, 1000, 1400, 2000, 3200, 5500, 10000, 11025,
]


def _bin_indices() -> list[tuple[int, int]]:
    """Precompute FFT bin index ranges for each of the 16 bands."""
    n = CHUNK_SIZE // 2 + 1
    freq_per_bin = SAMPLE_RATE / CHUNK_SIZE
    indices = []
    for i in range(SPECTRUM_BANDS):
        lo = int(BAND_EDGES[i] / freq_per_bin)
        hi = int(BAND_EDGES[i + 1] / freq_per_bin)
        lo = max(0, min(lo, n - 1))
        hi = max(lo + 1, min(hi, n))
        indices.append((lo, hi))
    return indices


class SpectrumAnalyzer:
    def __init__(self, event_bus: EventBus):
        self._event_bus = event_bus
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._bands = [0.0] * SPECTRUM_BANDS
        self._bin_idx = _bin_indices()
        self._decay = 0.7

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        log.info("SpectrumAnalyzer started")

    def stop(self) -> None:
        self._running = False

    def _run(self) -> None:
        proc = self._try_capture()
        if proc and HAS_NUMPY:
            self._run_real(proc)
        else:
            if proc:
                proc.terminate()
            self._run_simulated()

    def _try_capture(self) -> Optional[subprocess.Popen]:
        for cmd in [
            ["pw-record", "--target", "0", "--format", "f32",
             "--rate", str(SAMPLE_RATE), "--channels", "1", "-"],
            ["parec", "--format=float32le", "--channels=1",
             f"--rate={SAMPLE_RATE}", "--raw"],
        ]:
            try:
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                )
                time.sleep(0.3)
                if proc.poll() is not None:
                    continue
                log.info("Audio capture via: %s", cmd[0])
                return proc
            except FileNotFoundError:
                continue
            except Exception as e:
                log.debug("Capture attempt failed (%s): %s", cmd[0], e)
        log.info("No audio capture available — using simulated spectrum")
        return None

    def _run_real(self, proc: subprocess.Popen) -> None:
        bytes_per_chunk = CHUNK_SIZE * 4  # float32
        try:
            while self._running:
                raw = proc.stdout.read(bytes_per_chunk)
                if not raw or len(raw) < bytes_per_chunk:
                    break
                samples = np.frombuffer(raw, dtype=np.float32)
                spectrum = np.abs(np.fft.rfft(samples * np.hanning(CHUNK_SIZE)))
                bands = []
                for lo, hi in self._bin_idx:
                    mag = float(np.mean(spectrum[lo:hi])) if hi > lo else 0.0
                    bands.append(mag)
                peak = max(bands) if bands else 1.0
                if peak > 0:
                    bands = [min(1.0, b / peak) for b in bands]
                self._bands = [
                    max(b, old * self._decay)
                    for b, old in zip(bands, self._bands)
                ]
                self._event_bus.publish("audio.spectrum", list(self._bands))
        except Exception as e:
            log.warning("Spectrum capture error: %s — falling back to simulated", e)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except Exception:
                proc.kill()
        if self._running:
            self._run_simulated()

    def _run_simulated(self) -> None:
        import random
        t = 0.0
        while self._running:
            playing = False
            ev = self._event_bus.get_last("bt.media_playing")
            if ev:
                playing = bool(ev[0])
            bands = []
            for i in range(SPECTRUM_BANDS):
                if playing:
                    import math
                    base = 0.3 + 0.4 * math.sin(t * 1.5 + i * 0.7)
                    jitter = random.uniform(-0.15, 0.15)
                    bands.append(max(0.0, min(1.0, base + jitter)))
                else:
                    bands.append(random.uniform(0.0, 0.05))
            self._bands = [
                max(b, old * self._decay)
                for b, old in zip(bands, self._bands)
            ]
            self._event_bus.publish("audio.spectrum", list(self._bands))
            t += 0.066
            time.sleep(0.066)
