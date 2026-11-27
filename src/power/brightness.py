"""Screen brightness — manual stalk steps and, with ``modules.auto_brightness``,
automatic brightness from a light sensor through a display backend.

History
-------
This controller existed long before the module (the 6 stalk steps and the
LDR map below) but nothing ever created it, and on x86 the backlight is
simulated (src/power/backlight.py) — so neither the stalk nor the Settings
value changed anything on the M910q. Plan D3 ("Światło (lux)") finishes it
instead of adding a parallel controller: ``start_auto_brightness`` (the
``modules.auto_brightness`` entry point, off in code and in both configs)
creates it, feeds it a light source and gives it a backend that really
changes what the driver sees.

Sources (``requires_any`` phone_sensors | input in the module catalog)
----------------------------------------------------------------------
* ``phone.light_lux`` ``{lux, ts}`` — the car phone's light sensor
  (src/sensors/phone_sensors.py: median of 5, <= 2 Hz, 2 s heartbeat).
* ``arduino.light_level`` — ADC 0..1023 of the LDR (``LIGHT:`` lines read by
  arduino_serial, which the ``input`` module starts; every 2 s). Low ADC =
  bright; mapped with the old step table (:data:`LIGHT_SENSOR_MAP`).

Both fresh: the PHONE wins. It reports calibrated lux on a log scale that
the curve is written for and it looks at the cabin from the headliner; the
LDR is an uncalibrated step table whose reading depends on the divider.
A sample is fresh for ``stale_s`` (10 s) after it ARRIVED (this process's
monotonic clock — the phone's ``ts`` is wall time and may jump).

The automatic path (pure, on an injected clock — tested with a FakeClock)
-------------------------------------------------------------------------
1. Input hysteresis: the target is recomputed only when the lux moved more
   than ``hysteresis_pct`` (10 %, at least 0.5 lux) from the reading that
   produced the current target (ADC: more than :data:`ADC_HYSTERESIS`
   counts) — a cloud edge or a lamp post does not keep re-targeting.
2. Curve: ``display.auto_brightness.curve`` — ``[[lux, pct], …]``,
   interpolated linearly in ``log10(1 + lux)`` (eyes perceive light
   logarithmically; ``1 +`` keeps 0 lux defined). Below the first point the
   first pct, above the last the last pct; then clamped to
   ``[min_pct, max_pct]`` — the floor (default 15) means the screen is never
   unreadable whatever the sensor says.
3. Smoothing: an exponential moving average with time constant
   ``smoothing_s`` (3 s), SYMMETRIC. Entering a tunnel the screen dims
   within a few seconds (the eyes are still adapted to daylight, a bright
   screen for 3 s does no harm); leaving it the screen is too dark for a
   few seconds in the sun — accepted for one simple, predictable rule. The
   first sample after start applies at once (no 3 s glide from the boot
   value at night).
4. Output hysteresis: while the EMA glides, the applied value changes only
   by steps of at least ``hysteresis_pp`` (5 pp) — its small drift never
   reaches the backend (and the DDC monitor's EEPROM). Once it has settled
   (within 0.5 pp of the target) one last smaller step lands on the target
   exactly (DDC still skips that one: < :data:`DDC_MIN_STEP_PP`).

Stale input (no fresh sample from either source, but there were samples):
HOLD the last applied value. No source at all since start: the manual
value (``display.dashboard.brightness`` — the Settings slider).

Manual
------
* The stalk (``input.brightness_cycle``) steps through
  :data:`BRIGHTNESS_STEPS`; the slider in Settings → "Jasność ekranu"
  (``POST /api/config {"brightness": N}`` → ``config.changed``) sets a value.
  Either pauses the automatic path for ``manual_hold_min`` (10 min); then
  it resumes, gliding from the manual value.
* "Ręczna" in the same row (``display.auto_brightness.mode: manual``) turns
  the automatic path off until "Auto" is chosen again. It FREEZES what is
  on screen: the current level becomes the manual value (web_viewer also
  saves it as the slider value), not the older slider value — at night
  that could be a jump to a bright screen while driving.
* ``power.ignition_off`` ends a manual pause (old behaviour; the test car
  has no clean ignition-off — power is just cut).

Every value — automatic or manual — goes through the backend while the
module runs, and never below ``min_pct``.

Backends (``display.auto_brightness.backend``: auto | css | ddc | xrandr)
-------------------------------------------------------------------------
The screen in the test car is powered from USB and has NO brightness
control wired, so the default (``auto`` = ``css``) dims the IMAGE:

* ``css`` — publishes ``display.dim`` ``{level, brightness_pct}``; the
  kiosk draws ONE full-screen black overlay with ``opacity = level``
  (components/dim_overlay.js) BELOW the crash window, the 112 call view and
  the reverse camera (those stay fully bright). ``level`` =
  ``(100 - pct) / 100 × css_max_dim`` (0.85): 100 % = no overlay, and even
  0 % never makes the screen black. Less glare at night, but no power saved
  and no deeper black.
* ``ddc`` — ``ddcutil setvcp 10 <value>`` over DDC/CI (the video cable,
  independent of how the monitor is powered). Chosen in Settings
  ("Ściemnianie: Sprzętowe (DDC/CI)") it is first PROBED on the hardware
  worker: ``ddcutil detect --brief`` then ``ddcutil getvcp 10 --brief``
  (the max of VCP 10 scales the percentage). Until the probe says yes the
  overlay stays; any failure (no ddcutil, no ``/dev/i2c-*``, no monitor
  answering, no VCP 10) falls back to ``css`` with a reason the row shows.
  A TRANSIENT failure (timeout, no monitor answering, no VCP 10 —
  :data:`DDC_TRANSIENT`) is probed again by itself after 20 s, 60 s and
  180 s (:data:`DDC_PROBE_RETRY_S`; the monitor may still be waking up
  after the cold boot every drive is); no ddcutil / no ``/dev/i2c-*`` is
  final. Writes: only when the value moved >= :data:`DDC_MIN_STEP_PP` (a
  manual value always) and >= :data:`DDC_MIN_INTERVAL_S` after the
  previous write (coalesced to the latest value) — I2C traffic and EEPROM
  wear; timeout 5 s; :data:`DDC_MAX_FAILURES` failed writes in a row or a
  vanished binary → back to ``css``. Leaving ``ddc`` writes 100 % once
  (:data:`HW_RESTORE_DELAY_S` later, when the overlay has faded in), so
  the overlay does not dim an already dimmed monitor — also when the module
  is switched off in Settings → Moduły (it would not run after the restart
  to undo the monitor's last value).
* ``xrandr`` — ``xrandr --output <name> --brightness <0.20-1.00>`` with
  ``DISPLAY``/``XAUTHORITY`` from ``display.auto_brightness.xrandr``
  (validated: output name, ``:N[.M]``, an absolute path). A gamma change of
  the whole X screen, independent of the kiosk page: it also covers the
  boot splash, the cursor and X windows outside the kiosk. (Android Auto
  is no reason to pick it: on x86 it is an ``<img>`` in the kiosk, so the
  overlay dims it as well.) UNVERIFIED on the car (needs the kiosk's X
  authority — BCM runs as root); a bad config or a failed call → ``css``.
  Config only, not in the Settings switch.

The tools are argv lists through :func:`src.network._proc._run` (no
shell; values are validated integers / fixed strings) and run ONLY on the
``brightness-hw`` worker — never on the bus dispatcher or at module start.
A second thread, ``brightness-tick``, evaluates every :data:`TICK_S` (EMA,
stale input, end of the manual pause). Bus callbacks only record the input
and evaluate (cheap, non-blocking). Every evaluation publishes its result
while still holding the controller's lock, so the bus's "latest" state is
never an older one.

Topics
------
Consumed: ``phone.light_lux``, ``arduino.light_level``,
``input.brightness_cycle``, ``config.changed`` (``brightness``,
``brightness_mode``, ``brightness_backend`` — validated again here; and
the module toggles of Settings → Moduły: when this module will not run
after the next restart, the hardware backend is released at once),
``power.ignition_off``, ``power.shutting_down``.

Published: ``power.backlight_brightness`` ``{display, brightness}`` (both
panels, as before), ``power.brightness_level`` (int %),
``power.brightness_mode`` (``auto``/``manual``), ``display.dim`` (see
css), ``display.brightness_state`` (on change; the Settings row)::

    {mode, effective, source, lux, adc, pct, target_pct, manual_pct,
     hold_left_min, min_pct, max_pct, backend, active, probe, reason}

    effective: auto | hold | manual | no_source | stale
    probe:     idle | probing | ok | failed
    reason:    '' | no_ddcutil | no_i2c | no_display | no_vcp | timeout |
               write_failed | no_xrandr | xrandr_config | xrandr_failed

Brightness levels (manual, stalk):
    15% (night) · 30% · 45% · 60% · 80% · 100% (bright sun)

Light sensor mapping (Arduino LDR, low ADC = bright):
    ADC 0-100 → 100% · 100-300 → 80% · 300-500 → 60% · 500-700 → 45% ·
    700-900 → 30% · 900+ → 15%
"""

from __future__ import annotations

import glob
import math
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, replace
from typing import Any, Callable, Optional

from src.core.event_bus import EventBus
from src.core.logger import get_logger
from src.network._proc import RC_MISSING, RC_TIMEOUT, _cfg_get, _number, _run, clean_error

log = get_logger("power.brightness")

# Manual brightness steps (6 levels)
BRIGHTNESS_STEPS = [15, 30, 45, 60, 80, 100]

# Light sensor ADC thresholds → brightness (LDR: low ADC = bright, high ADC = dark)
# Sorted by ADC ascending (bright → dark)
LIGHT_SENSOR_MAP = [
    (100, 100),   # ADC < 100 → 100%
    (300, 80),    # ADC < 300 → 80%
    (500, 60),    # ADC < 500 → 60%
    (700, 45),    # ADC < 700 → 45%
    (900, 30),    # ADC < 900 → 30%
]
LIGHT_SENSOR_DARK = 15  # ADC >= 900 → 15%

CFG = "display.auto_brightness"
TOPIC_STATE = "display.brightness_state"
TOPIC_DIM = "display.dim"
TOPIC_LUX = "phone.light_lux"
TOPIC_ADC = "arduino.light_level"

#: Range of display.auto_brightness.boost_pct (percentage points).
BOOST_MIN, BOOST_MAX = -30, 50

#: lux → % (log-interpolated); the plan's example curve.
DEFAULT_CURVE: tuple[tuple[float, float], ...] = (
    (0.0, 15.0), (10.0, 25.0), (100.0, 45.0), (1000.0, 70.0), (10000.0, 100.0))
CURVE_MAX_POINTS = 16
#: Same bound phone_sensors validates the light sensor against.
LUX_MAX = 200000.0
ADC_MAX = 1023
#: LDR counts the reading must move before the target is recomputed.
ADC_HYSTERESIS = 30
#: Smallest lux band of the input hysteresis (phone_sensors itself publishes
#: changes of >= 0.5 lux).
HYST_LUX_MIN = 0.5
#: ``min_pct`` can never be configured below this.
MIN_PCT_FLOOR = 5
TICK_S = 0.5
#: How long the hardware worker sleeps with nothing to do (it is woken on
#: every new value anyway).
HW_IDLE_S = 30.0

BACKENDS = ("auto", "css", "ddc", "xrandr")
ACTIVE_BACKENDS = ("css", "ddc", "xrandr")
#: What the Settings switch can choose (POST /api/config brightness_backend).
UI_BACKENDS = ("css", "ddc")
MODES = ("auto", "manual")
EFFECTIVE = ("auto", "hold", "manual", "no_source", "stale")
SOURCES = ("", "phone", "arduino")
PROBE_STATES = ("idle", "probing", "ok", "failed")
REASONS = ("", "no_ddcutil", "no_i2c", "no_display", "no_vcp", "timeout",
           "write_failed", "no_xrandr", "xrandr_config", "xrandr_failed")

DDC_MIN_STEP_PP = 5
DDC_MIN_INTERVAL_S = 5.0
DDC_TIMEOUT_S = 5.0
#: ``detect`` walks every I2C bus — slower than one getvcp.
DDC_DETECT_TIMEOUT_S = 15.0
DDC_MAX_FAILURES = 3
#: Automatic re-probes after a TRANSIENT probe failure, seconds after each
#: failure (then no more). Every drive of the test car is a cold boot (the
#: power is cut at every engine stop), so the one probe per drive runs right
#: after the USB-powered monitor woke up, while the boot splash hands the
#: display to the kiosk — a first ``detect`` that times out or sees no
#: monitor is likely, and without a retry a monitor left dimmed from the
#: night drive (its EEPROM keeps the last DDC value) would stay dim all day.
#: Bounded: at most 3 extra probes per choice, so a monitor without DDC/CI
#: does not get a retry loop on its I2C bus.
DDC_PROBE_RETRY_S = (20.0, 60.0, 180.0)
#: Probe failures worth retrying. A missing ddcutil or ``/dev/i2c-*`` is
#: final (nothing changes until someone installs / loads it); a failed WRITE
#: after a good probe stays final as well.
DDC_TRANSIENT = ("timeout", "no_display", "no_vcp")
#: Leaving a hardware backend restores 100 % only this long after the
#: overlay was asked for: the kiosk gets the new ``display.dim`` within
#: ~0.1 s (15 FPS push) and fades it in over 1 s — restoring at once would
#: flash a full-bright monitor in a dark cabin for about a second.
HW_RESTORE_DELAY_S = 1.5
XRANDR_MIN_INTERVAL_S = 1.0
XRANDR_TIMEOUT_S = 5.0
#: xrandr --brightness never below this (0 = a black screen).
XRANDR_MIN = 0.2
CSS_MAX_DIM_DEFAULT = 0.85
#: Hard cap of the overlay's opacity — also enforced by web_viewer and the
#: kiosk: a bad value can dim the screen, never black it out.
CSS_MAX_DIM_LIMIT = 0.9
#: Longest tool output parsed.
_OUT_MAX = 65536

_XR_OUTPUT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,31}$")
_XR_DISPLAY_RE = re.compile(r"^:[0-9]{1,2}(?:\.[0-9]{1,2})?$")
_XR_XAUTH_RE = re.compile(r"^/[A-Za-z0-9._/-]{1,255}$")
#: ``ddcutil getvcp 10 --brief`` → ``VCP 10 C <current> <max>``.
_VCP_RE = re.compile(r"^VCP\s+(?:0x)?10\s+C\s+(\d{1,5})\s+(\d{1,5})\s*$", re.M)
#: ``ddcutil detect --brief``: a usable monitor is "Display N" (an
#: unusable one is "Invalid display").
_DISPLAY_LINE_RE = re.compile(r"^Display\s+(\d{1,2})\s*$", re.M)


# ── pure helpers ──────────────────────────────────────────────────────────

def _finite(v: Any) -> bool:
    return not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v)


def parse_curve(value: Any) -> Optional[tuple[tuple[float, float], ...]]:
    """``[[lux, pct], …]`` → tuple, or None when invalid: 2..16 points, lux
    0..200000 strictly increasing, pct 0..100, finite numbers (no bools)."""
    if not isinstance(value, (list, tuple)) or not 2 <= len(value) <= CURVE_MAX_POINTS:
        return None
    pts: list[tuple[float, float]] = []
    for p in value:
        if not isinstance(p, (list, tuple)) or len(p) != 2:
            return None
        lux, pct = p
        if not _finite(lux) or not _finite(pct):
            return None
        if not 0 <= lux <= LUX_MAX or not 0 <= pct <= 100:
            return None
        if pts and lux <= pts[-1][0]:
            return None
        pts.append((float(lux), float(pct)))
    return tuple(pts)


def curve_pct(curve: tuple[tuple[float, float], ...], lux: float) -> float:
    """Brightness % for ``lux``: linear in ``log10(1 + lux)`` between the
    points, flat outside them (no clamping to min/max here)."""
    x = math.log10(1.0 + max(0.0, float(lux)))
    xs = [math.log10(1.0 + p[0]) for p in curve]
    if x <= xs[0]:
        return curve[0][1]
    if x >= xs[-1]:
        return curve[-1][1]
    for i in range(1, len(curve)):
        if x <= xs[i]:
            x0, x1 = xs[i - 1], xs[i]
            p0, p1 = curve[i - 1][1], curve[i][1]
            return p0 + (p1 - p0) * (x - x0) / (x1 - x0)
    return curve[-1][1]                         # unreachable (x < xs[-1])


def adc_to_pct(adc: int) -> int:
    """The old LDR step table (low ADC = bright)."""
    for threshold, brightness in LIGHT_SENSOR_MAP:
        if adc < threshold:
            return brightness
    return LIGHT_SENSOR_DARK


def xrandr_level(pct: int) -> str:
    """``--brightness`` argument: pct/100 within [0.20, 1.00], 2 decimals."""
    return f"{max(XRANDR_MIN, min(1.0, pct / 100.0)):.2f}"


def css_level(pct: int, max_dim: float) -> float:
    """Overlay opacity for ``pct``: 0 at 100 %, ``max_dim`` at 0 %."""
    pct = max(0, min(100, int(pct)))
    return round((100 - pct) / 100.0 * max(0.0, min(CSS_MAX_DIM_LIMIT, max_dim)), 3)


@dataclass(frozen=True)
class AutoSettings:
    """``display.auto_brightness`` after validation (bad values → default
    with one warning naming the key)."""
    curve: tuple[tuple[float, float], ...] = DEFAULT_CURVE
    min_pct: int = 15
    max_pct: int = 100
    smoothing_s: float = 3.0
    stale_s: float = 10.0
    manual_hold_s: float = 600.0
    hysteresis_ratio: float = 0.10
    hysteresis_pp: int = 5
    backend: str = "auto"
    mode: str = "auto"
    css_max_dim: float = CSS_MAX_DIM_DEFAULT
    # Calibration: percentage points added to the curve's value (the phone
    # sits under the headliner and reads the cabin darker than the road —
    # in daylight the screen came out too dim). Settings "−5 / +5".
    boost_pp: int = 0
    ddc_display: Optional[int] = None
    xrandr_output: str = ""
    xrandr_display: str = ":0"
    xrandr_xauthority: str = ""


def load_settings(config: Any) -> AutoSettings:
    def get(key: str) -> Any:
        return _cfg_get(config, f"{CFG}.{key}")

    def num(key: str, default: float, lo: float, hi: float) -> float:
        return _number(CFG, get(key), default, lo, hi, key, log)

    curve_raw = get("curve")
    curve = DEFAULT_CURVE
    if curve_raw is not None:
        parsed = parse_curve(curve_raw)
        if parsed is None:
            log.warning("%s.curve is not a list of 2-16 [lux, pct] pairs with increasing lux "
                        "— using the default curve", CFG)
        else:
            curve = parsed
    min_pct = int(round(num("min_pct", 15, MIN_PCT_FLOOR, 100)))
    max_pct = int(round(num("max_pct", 100, min_pct, 100)))

    def choice(key: str, allowed: tuple, default: str) -> str:
        v = get(key)
        if v is None:
            return default
        if isinstance(v, str) and v in allowed:
            return v
        log.warning("%s.%s=%r is not one of %s — using %s", CFG, key, v, list(allowed), default)
        return default

    ddc_display = get("ddc_display")
    if ddc_display is not None and (isinstance(ddc_display, bool) or not isinstance(ddc_display, int)
                                    or not 1 <= ddc_display <= 16):
        log.warning("%s.ddc_display=%r is not 1..16 — ddcutil picks the display", CFG, ddc_display)
        ddc_display = None

    def text(key: str, default: str) -> str:
        v = _cfg_get(config, f"{CFG}.xrandr.{key}")
        return v if isinstance(v, str) else default

    return AutoSettings(
        curve=curve, min_pct=min_pct, max_pct=max_pct,
        smoothing_s=num("smoothing_s", 3.0, 0.0, 60.0),
        stale_s=num("stale_s", 10.0, 3.0, 600.0),
        manual_hold_s=num("manual_hold_min", 10.0, 1.0, 240.0) * 60.0,
        hysteresis_ratio=num("hysteresis_pct", 10.0, 0.0, 50.0) / 100.0,
        hysteresis_pp=int(round(num("hysteresis_pp", 5, 1, 20))),
        boost_pp=int(round(num("boost_pct", 0, BOOST_MIN, BOOST_MAX))),
        backend=choice("backend", BACKENDS, "auto"),
        mode=choice("mode", MODES, "auto"),
        css_max_dim=num("css_max_dim", CSS_MAX_DIM_DEFAULT, 0.3, CSS_MAX_DIM_LIMIT),
        ddc_display=ddc_display,
        xrandr_output=text("output", ""),
        xrandr_display=text("display", ":0"),
        xrandr_xauthority=text("xauthority", ""),
    )


def xrandr_config_error(s: AutoSettings) -> str:
    """'' when the xrandr settings may reach an argv / the environment."""
    if not _XR_OUTPUT_RE.match(s.xrandr_output):
        return "xrandr.output must be an output name such as HDMI-1"
    if not _XR_DISPLAY_RE.match(s.xrandr_display):
        return "xrandr.display must look like :0"
    xa = s.xrandr_xauthority
    if xa and (not _XR_XAUTH_RE.match(xa) or ".." in xa.split("/")):
        return "xrandr.xauthority must be an absolute path"
    return ""


def _pct_or_none(v: Any) -> Optional[int]:
    """A brightness % from untrusted input (bool rejected, 55.0 → 55)."""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 100:
        return None
    return v


def _round_lux(lux: Optional[float]) -> Optional[float]:
    if lux is None:
        return None
    return round(lux, 1) if lux < 10 else float(round(lux))


class BrightnessController:
    """Manages auto/manual brightness for both displays (see the module
    docstring). Both screens are always linked to the same level.

    Args:
        config: BCMConfig or nested dict.
        event_bus: EventBus — subscriptions are made here (no I/O, no
            thread); :meth:`start` starts the two workers.
        clock: monotonic seconds (tests pass a fake).
        runner: ``subprocess.run`` compatible — the only way ddcutil /
            xrandr are run (tests pass a fake; nothing real ever runs).
        which: ``shutil.which`` compatible (is ddcutil installed?).
        i2c_glob: ``glob.glob`` compatible (``/dev/i2c-*``).
    """

    def __init__(self, config: Any, event_bus: EventBus, *,
                 clock: Callable[[], float] = time.monotonic,
                 runner: Callable[..., Any] = subprocess.run,
                 which: Callable[[str], Optional[str]] = shutil.which,
                 i2c_glob: Callable[[str], list] = glob.glob) -> None:
        self._config = config
        self._bus = event_bus
        self._clock = clock
        self._runner = runner
        self._which = which
        self._i2c_glob = i2c_glob
        self.settings = load_settings(config)
        s = self.settings
        self._lock = threading.RLock()
        self._hw_cond = threading.Condition(self._lock)
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

        # Manual override state
        self._manual_override = False
        self._manual_step_index = 4  # Start at step 5 (80%) if manually cycled
        self._hold_until: Optional[float] = None
        self._mode = s.mode

        # Current brightness
        start = _pct_or_none(_cfg_get(config, "display.dashboard.brightness"))
        self._current_brightness = max(s.min_pct, start if start is not None else 80)
        self._manual_value = self._current_brightness
        self._last_light_adc = 500  # Mid-range default

        # Automatic path
        self._samples: dict[str, Optional[tuple[float, float]]] = {"phone": None, "arduino": None}
        self._ever_sample = False
        #: The DDC monitor's own level was adopted at boot (no sample yet).
        self._ddc_adopted = False
        self._source = ""
        self._anchor: Optional[tuple[str, float]] = None
        self._target: Optional[float] = None
        self._ema: Optional[float] = None
        self._last_eval: Optional[float] = None
        self._effective = "no_source"

        # Backend (hardware fields are touched by the hw worker under _lock;
        # the tool itself runs with the lock released)
        self._backend_req = "auto"
        self._active = "css"
        self._probe = "idle"
        self._reason = ""
        self._probe_requested = False
        self._probe_gen = 0
        # Bounded automatic re-probe after a transient failure
        # (DDC_PROBE_RETRY_S): when the next one is due, and how many of
        # them this choice has used.
        self._probe_retry_at: Optional[float] = None
        self._probe_retries = 0
        # The module was switched off in Settings → Moduły (it will not run
        # after the restart): no hardware backend until it is on again.
        self._hw_released = False
        self._hw_desired: Optional[tuple[int, bool]] = None
        self._hw_restore: Optional[str] = None
        self._hw_restore_at: Optional[float] = None
        self._ddc_max: Optional[int] = None
        self._ddc_last_pct: Optional[int] = None
        self._ddc_last_at: Optional[float] = None
        self._ddc_failures = 0
        self._xr_last_pct: Optional[int] = None
        self._xr_last_at: Optional[float] = None
        self._missing_logged: set[str] = set()
        self._published_dim: Optional[dict] = None
        self._published_state: Optional[dict] = None

        with self._lock:
            self._select_backend_locked(s.backend, initial=True)

        # Subscribe to events
        for topic, cb in self._subscriptions():
            self._bus.subscribe(topic, cb)

        log.info("BrightnessController initialized (mode=%s, brightness=%d%%, backend=%s)",
                 self._mode, self._current_brightness, s.backend)

    def _subscriptions(self) -> tuple:
        return (("input.brightness_cycle", self._on_stalk_press),
                (TOPIC_ADC, self._on_light_level),
                (TOPIC_LUX, self._on_lux),
                ("config.changed", self._on_config_changed),
                ("power.ignition_off", self._on_ignition_off),
                ("power.shutting_down", self._on_shutdown))

    # ── properties (old API) ──────────────────────────────────────────────

    @property
    def mode(self) -> str:
        return "manual" if (self._manual_override or self._mode == "manual") else "auto"

    @property
    def brightness(self) -> int:
        return self._current_brightness

    @property
    def manual_step(self) -> int:
        """Current manual step index (0-5), or -1 if in auto mode."""
        return self._manual_step_index if self._manual_override else -1

    @property
    def state(self) -> Optional[dict]:
        with self._lock:
            return dict(self._published_state) if self._published_state else None

    # ── lifecycle ─────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the tick and hardware workers; no I/O here."""
        with self._lock:
            if self._threads or self._stop.is_set():
                return
            self._threads = [
                threading.Thread(target=self._tick_loop, daemon=True, name="brightness-tick"),
                threading.Thread(target=self._hw_loop, daemon=True, name="brightness-hw"),
            ]
        for t in self._threads:
            t.start()

    def stop(self) -> None:
        global _INSTANCE
        if self._stop.is_set():
            return
        self._stop.set()
        with _INSTANCE_LOCK:
            if _INSTANCE is self:
                _INSTANCE = None
        for topic, cb in self._subscriptions():
            try:
                self._bus.unsubscribe(topic, cb)
            except Exception:
                pass
        with self._hw_cond:
            self._hw_cond.notify_all()

    def _tick_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                log.exception("Brightness: evaluation failed")
            if self._stop.wait(TICK_S):
                break

    def _hw_loop(self) -> None:
        while not self._stop.is_set():
            try:
                wait = self.hw_step()
            except Exception:
                log.exception("Brightness: hardware step failed")
                wait = DDC_MIN_INTERVAL_S
            if wait is not None and wait <= 0:
                continue
            with self._hw_cond:
                if self._stop.is_set():
                    break
                if wait is not None:
                    self._hw_cond.wait(wait)
                elif not self._hw_pending_locked():
                    self._hw_cond.wait(HW_IDLE_S)

    # ── public operations ─────────────────────────────────────────────────

    def tick(self, now: Optional[float] = None) -> Optional[int]:
        """One evaluation (EMA step, stale input, end of a manual pause).
        Returns the newly applied brightness, or None."""
        now = self._clock() if now is None else now
        with self._lock:
            out, applied = self._evaluate_locked(now)
            self._emit(out)
        return applied

    def cycle_brightness(self) -> int:
        """Cycle to next manual brightness step. Returns new brightness."""
        with self._lock:
            now = self._clock()
            if not self._manual_override:
                # First press: enter manual mode, find closest step to current
                self._manual_override = True
                self._manual_step_index = self._find_closest_step(self._current_brightness)
                log.info("Brightness: switched to manual mode (step %d = %d%%)",
                         self._manual_step_index + 1,
                         BRIGHTNESS_STEPS[self._manual_step_index])
            else:
                # Subsequent presses: cycle to next step
                self._manual_step_index = (self._manual_step_index + 1) % len(BRIGHTNESS_STEPS)
            new_brightness = max(self.settings.min_pct, BRIGHTNESS_STEPS[self._manual_step_index])
            self._manual_value = new_brightness
            self._hold_until = (now + self.settings.manual_hold_s) if self._mode == "auto" else None
            out, _applied = self._evaluate_locked(now)
            out.append(("power.brightness_mode", "manual"))
            self._emit(out)
        log.info("Brightness: manual step %d/%d = %d%%",
                 self._manual_step_index + 1, len(BRIGHTNESS_STEPS), new_brightness)
        return new_brightness

    def update_from_sensor(self, adc_value: int) -> Optional[int]:
        """Arduino LDR reading. Returns the newly applied brightness, or
        None (no change, manual mode, or the phone's lux has priority)."""
        if isinstance(adc_value, bool) or not isinstance(adc_value, (int, float)) \
                or not math.isfinite(adc_value) or not 0 <= adc_value <= ADC_MAX:
            return None
        with self._lock:
            now = self._clock()
            self._last_light_adc = int(adc_value)
            self._samples["arduino"] = (float(int(adc_value)), now)
            self._ever_sample = True
            out, applied = self._evaluate_locked(now)
            self._emit(out)
        return applied

    def update_from_lux(self, lux: Any) -> Optional[int]:
        """Phone light sensor reading (lux). Same return as
        :meth:`update_from_sensor`."""
        if not _finite(lux) or not 0 <= lux <= LUX_MAX:
            return None
        with self._lock:
            now = self._clock()
            self._samples["phone"] = (float(lux), now)
            self._ever_sample = True
            out, applied = self._evaluate_locked(now)
            self._emit(out)
        return applied

    def set_manual(self, pct: Any) -> Optional[int]:
        """A value from Settings (the slider): pauses auto for
        ``manual_hold_min`` (in "Ręczna" it just becomes the value)."""
        value = _pct_or_none(pct)
        if value is None:
            return None
        with self._lock:
            now = self._clock()
            self._set_manual_locked(value, now)
            out, applied = self._evaluate_locked(now)
            self._emit(out)
        return applied

    def set_mode(self, mode: Any) -> None:
        """``auto`` (resume now) or ``manual`` (freeze the current level
        until "Auto" is chosen again)."""
        if mode not in MODES:
            return
        with self._lock:
            now = self._clock()
            self._set_mode_locked(mode, keep_level=True)
            out, _ = self._evaluate_locked(now)
            self._emit(out)

    def set_backend(self, name: Any) -> None:
        """Live switch of the backend (Settings: css / ddc)."""
        if name not in BACKENDS:
            return
        with self._lock:
            self._select_backend_locked(name)
            out, _ = self._evaluate_locked(self._clock())
            self._emit(out)

    def reset_manual_override(self) -> None:
        """End a stalk / slider pause (called on ignition off). In "Ręczna"
        the mode stays manual — and is published as such."""
        with self._lock:
            if not self._manual_override:
                return
            self._resume_auto_locked()
            out, _ = self._evaluate_locked(self._clock())
            out.insert(0, ("power.brightness_mode", self.mode))
            self._emit(out)
        log.info("Brightness: manual pause ended (ignition off) — mode %s", self.mode)

    # ── evaluation (under _lock) ──────────────────────────────────────────

    def _fresh_source(self, now: float) -> str:
        for name in ("phone", "arduino"):      # the phone wins when both are fresh
            sample = self._samples[name]
            if sample is not None and 0 <= now - sample[1] <= self.settings.stale_s:
                return name
        return ""

    def _update_target_locked(self, source: str) -> None:
        s = self.settings
        sample = self._samples[source]
        if sample is None:
            return
        value = sample[0]
        a = self._anchor
        if source == "phone":
            moved = a is None or a[0] != "phone" or \
                abs(value - a[1]) > max(a[1] * s.hysteresis_ratio, HYST_LUX_MIN)
            if moved:
                self._anchor = ("phone", value)
                self._target = min(s.max_pct, max(s.min_pct,
                                                  curve_pct(s.curve, value) + s.boost_pp))
        else:
            moved = a is None or a[0] != "arduino" or abs(value - a[1]) > ADC_HYSTERESIS
            if moved:
                self._anchor = ("arduino", value)
                self._target = float(min(s.max_pct, max(s.min_pct, adc_to_pct(int(value)))))

    def _evaluate_locked(self, now: float) -> tuple[list, Optional[int]]:
        s = self.settings
        out: list = []
        dt = 0.0 if self._last_eval is None else max(0.0, now - self._last_eval)
        self._last_eval = now
        # End of a manual pause.
        if self._manual_override and self._hold_until is not None and now >= self._hold_until:
            self._resume_auto_locked()
            out.append(("power.brightness_mode", "auto"))
            log.info("Brightness: manual pause over — automatic again")
        source = self._fresh_source(now)
        if source != self._source:
            if source:
                log.info("Brightness: light from %s", "the car phone" if source == "phone"
                         else "the Arduino LDR")
            elif self._source:
                log.info("Brightness: no fresh light reading — holding %d%%",
                         self._current_brightness)
            self._source = source
            self._anchor = None
        if source:
            self._update_target_locked(source)
        desired: Optional[float]
        smooth = False
        if self._mode == "manual":
            eff, desired = "manual", float(self._manual_value)
        elif self._manual_override:
            eff, desired = "hold", float(self._manual_value)
        elif source and self._target is not None:
            eff, smooth = "auto", True
            if self._ema is None or s.smoothing_s <= 0:
                self._ema = self._target
            else:
                alpha = 1.0 - math.exp(-dt / s.smoothing_s)
                self._ema += (self._target - self._ema) * alpha
            desired = self._ema
        elif self._ever_sample:
            eff, desired = "stale", None
        elif self._ddc_adopted and self._active == "ddc":
            # The monitor's own level (from the last drive) until the first
            # light reading — see _ddc_adopt_locked.
            eff, desired = "no_source", None
        else:
            eff, desired = "no_source", float(self._manual_value)
        self._effective = eff
        applied = None
        if desired is not None:
            value = max(s.min_pct, min(100, int(round(desired))))
            diff = abs(value - self._current_brightness)
            # Settled (the EMA has reached its target): one last small step
            # to the exact value, so the deadband does not leave the screen
            # up to 4 pp off for good. No flicker: the target itself only
            # moves past the input hysteresis.
            settled = smooth and self._target is not None and abs(self._ema - self._target) < 0.5
            if diff and (not smooth or diff >= s.hysteresis_pp or settled):
                self._apply_locked(value, out, force=not smooth)
                applied = value
                log.debug("Brightness: %s %d%%", eff, value)
        self._outputs_locked(now, out)
        return out, applied

    def _ddc_adopt_locked(self) -> None:
        """After a good DDC probe. Every drive of the test car is a cold boot
        and the light reading comes only after the phone's adb forward, so
        before the first sample (automatic mode, no manual input) the level
        the monitor kept in its EEPROM from the last drive is adopted — a
        night start must not jump to the Settings slider value until the
        first lux reading decides (``_ddc_adopted`` makes "no_source" hold).
        Otherwise the current level is written as before."""
        last = self._ddc_last_pct
        if last is not None and self._mode == "auto" and not self._manual_override \
                and not self._ever_sample:
            value = max(self.settings.min_pct, min(100, last))
            self._current_brightness = value
            self._ddc_adopted = True
            self._hw_desired = None if value == last else (value, True)
            log.info("Brightness: keeping the monitor's %d%% until the first light reading",
                     value)
            return
        self._hw_desired = (self._current_brightness, True)

    def _apply_locked(self, value: int, out: list, force: bool) -> None:
        self._current_brightness = value
        # Both screens linked
        for display in ("small", "large"):
            out.append(("power.backlight_brightness", {"display": display, "brightness": value}))
        out.append(("power.brightness_level", value))
        if self._active in ("ddc", "xrandr"):
            prev = self._hw_desired
            self._hw_desired = (value, force or bool(prev and prev[1]))
            self._hw_cond.notify_all()

    def _resume_auto_locked(self) -> None:
        self._manual_override = False
        self._hold_until = None
        # Glide from what is on screen now; with no reading ever, stay on
        # the manual value (no_source).
        self._ema = float(self._current_brightness) if self._ever_sample else None

    def _set_manual_locked(self, value: int, now: float) -> None:
        self._manual_value = max(self.settings.min_pct, value)
        self._manual_override = True
        self._manual_step_index = self._find_closest_step(self._manual_value)
        self._hold_until = (now + self.settings.manual_hold_s) if self._mode == "auto" else None

    def _set_mode_locked(self, mode: str, keep_level: bool = False) -> None:
        """``keep_level``: on auto → manual, what is on screen NOW becomes
        the manual value (the driver taps "Ręczna" to freeze the brightness;
        the older slider value could be 70 % in a dark cabin). False when
        the same change also carries a slider value — that one wins."""
        if mode == self._mode:
            if mode == "auto" and self._manual_override:
                self._resume_auto_locked()
            return
        self._mode = mode
        log.info("Brightness: mode %s", mode)
        if mode == "auto":
            self._resume_auto_locked()
        else:
            if keep_level:
                self._manual_value = max(self.settings.min_pct, self._current_brightness)
                self._manual_step_index = self._find_closest_step(self._manual_value)
            self._manual_override = False
            self._hold_until = None

    def _outputs_locked(self, now: float, out: list) -> None:
        pct = self._current_brightness
        dim = {"level": css_level(pct, self.settings.css_max_dim) if self._active == "css" else 0.0,
               "brightness_pct": pct}
        if dim != self._published_dim:
            self._published_dim = dim
            out.append((TOPIC_DIM, dict(dim)))
        state = self._state_locked(now)
        if state != self._published_state:
            self._published_state = state
            out.append((TOPIC_STATE, dict(state)))

    def _state_locked(self, now: float) -> dict:
        s = self.settings
        phone, ard = self._samples["phone"], self._samples["arduino"]

        def fresh(smp: Optional[tuple[float, float]]) -> bool:
            return smp is not None and 0 <= now - smp[1] <= s.stale_s

        hold_left = None
        if self._manual_override and self._hold_until is not None and self._mode == "auto":
            hold_left = max(1, int(math.ceil((self._hold_until - now) / 60.0)))
        return {
            "mode": self._mode,
            "effective": self._effective,
            "source": self._source,
            "lux": _round_lux(phone[0]) if fresh(phone) else None,
            "adc": int(ard[0]) if fresh(ard) else None,
            "pct": self._current_brightness,
            "target_pct": int(round(self._target)) if self._source and self._target is not None
            else None,
            "manual_pct": self._manual_value,
            "hold_left_min": hold_left,
            "min_pct": s.min_pct,
            "max_pct": s.max_pct,
            "boost_pct": s.boost_pp,
            "backend": self._backend_req,
            "active": self._active,
            "probe": self._probe,
            "reason": self._reason,
        }

    def _emit(self, out: list) -> None:
        """Publish what one evaluation produced. Called WITH ``_lock``
        held: three threads evaluate (dispatcher, tick, hw), and a state
        computed first but published last would stay on the bus as the
        "latest" one. BCM's bus is async (publish only enqueues), so this
        never waits on a subscriber."""
        for topic, value in out:
            try:
                self._bus.publish(topic, value)
            except Exception:
                log.exception("Publishing %s failed", topic)

    # ── backend selection (under _lock) ───────────────────────────────────

    def _select_backend_locked(self, name: str, initial: bool = False) -> None:
        if name not in BACKENDS:
            name = "auto"
        prev_active = self._active
        if not initial and name == self._backend_req and name in ("ddc", "xrandr") \
                and self._active == name:
            return                      # already working: no re-probe, no flash
        self._backend_req = name
        self._probe_gen += 1
        self._probe_requested = False
        # A new choice gets the full retry budget again (and a pending retry
        # of the old one is dropped).
        self._probe_retry_at = None
        self._probe_retries = 0
        self._hw_desired = None
        if name in ("auto", "css") or self._hw_released:
            # (Released: the module is switched off for the next start —
            # the choice is remembered, the hardware is not touched.)
            self._active, self._probe, self._reason = "css", "idle", ""
        elif name == "ddc":
            # The overlay stays until the monitor has answered.
            self._active, self._probe, self._reason = "css", "probing", ""
            self._probe_requested = True
            log.info("Brightness: hardware dimming (DDC/CI) requested — probing the monitor")
        else:
            err = xrandr_config_error(self.settings)
            if err:
                self._active, self._probe, self._reason = "css", "failed", "xrandr_config"
                log.warning("Brightness: %s.%s — software dimming instead", CFG, err)
            else:
                self._active, self._probe, self._reason = "xrandr", "ok", ""
                self._xr_last_pct = None
                self._hw_desired = (self._current_brightness, True)
        if prev_active in ("ddc", "xrandr") and self._active != prev_active:
            self._schedule_restore_locked(prev_active)
        self._hw_cond.notify_all()

    def _schedule_restore_locked(self, backend: str) -> None:
        """One best-effort 100 % write to the backend just left, delayed by
        :data:`HW_RESTORE_DELAY_S` so the overlay has faded in first (no
        bright flash at night). Until it is done the hardware worker does
        nothing else, so a backend chosen meanwhile writes AFTER it."""
        self._hw_restore = backend
        self._hw_restore_at = self._clock() + HW_RESTORE_DELAY_S

    def _fallback_locked(self, reason: str, detail: str = "") -> None:
        """The hardware path failed: software dimming from now on (the row
        shows why). A transient probe failure is retried by ``hw_step``
        (:data:`DDC_PROBE_RETRY_S`); otherwise only a new choice in
        Settings / a restart retries."""
        prev = self._active
        self._active = "css"
        self._probe = "failed"
        self._reason = reason if reason in REASONS else "write_failed"
        self._hw_desired = None
        if prev in ("ddc", "xrandr") and reason not in ("no_ddcutil", "no_xrandr"):
            self._schedule_restore_locked(prev)
        log.warning("Brightness: hardware dimming unavailable (%s%s) — using the overlay",
                    self._reason, f": {detail}" if detail else "")

    def _release_hw_locked(self) -> None:
        """The module is switched off for the next start: give the monitor /
        the X gamma back now (100 %), while this process still runs — after
        the restart nothing would undo the last DDC value (a monitor keeps it
        in EEPROM). Until the restart the overlay dims instead."""
        if self._hw_released:
            return
        self._hw_released = True
        self._probe_gen += 1                 # an in-flight probe result is dropped
        self._probe_requested = False
        self._probe_retry_at = None
        self._hw_desired = None
        prev = self._active
        self._active, self._probe, self._reason = "css", "idle", ""
        if prev in ("ddc", "xrandr"):
            self._schedule_restore_locked(prev)
        log.info("Brightness: module switched off for the next start — hardware dimming "
                 "released (%s)", prev)
        self._hw_cond.notify_all()

    # ── hardware worker ───────────────────────────────────────────────────

    def _hw_pending_locked(self) -> bool:
        return bool(self._hw_restore or self._probe_requested
                    or (self._active in ("ddc", "xrandr") and self._hw_desired is not None))

    def _ddc_wait_locked(self, pct: int, force: bool, now: float) -> Optional[float]:
        """None = nothing to write; else seconds until the write is allowed
        (0 = now). >= DDC_MIN_STEP_PP (a manual value always) and
        >= DDC_MIN_INTERVAL_S apart."""
        last = self._ddc_last_pct
        if last is not None and (pct == last or (not force and abs(pct - last) < DDC_MIN_STEP_PP)):
            return None
        if self._ddc_last_at is not None:
            left = DDC_MIN_INTERVAL_S - (now - self._ddc_last_at)
            if left > 0:
                return left
        return 0.0

    def _xr_wait_locked(self, pct: int, now: float) -> Optional[float]:
        if self._xr_last_pct is not None and pct == self._xr_last_pct:
            return None
        if self._xr_last_at is not None:
            left = XRANDR_MIN_INTERVAL_S - (now - self._xr_last_at)
            if left > 0:
                return left
        return 0.0

    def hw_step(self, now: Optional[float] = None) -> Optional[float]:
        """One unit of hardware work (a probe, a write or a restore).

        Returns 0 when it did something (more may be due), the seconds until
        a rate-limited write / the delayed restore / the next automatic
        re-probe is due, or None when idle. The tool runs with the lock
        released; its result is applied only if the backend choice has not
        changed meanwhile.
        """
        now = self._clock() if now is None else now
        with self._lock:
            gen = self._probe_gen
            if self._hw_restore:
                # Nothing else before it (order: the old backend's 100 %
                # first, then whatever the new choice writes).
                left = (self._hw_restore_at or 0.0) - now
                if left > 0:
                    return left
                job, arg = "restore", self._hw_restore
                self._hw_restore = None
                self._hw_restore_at = None
            elif self._probe_requested:
                self._probe_requested = False
                job, arg = "probe", None
            elif self._active == "ddc" and self._hw_desired is not None:
                pct, force = self._hw_desired
                wait = self._ddc_wait_locked(pct, force, now)
                if wait is None:
                    self._hw_desired = None
                    return None
                if wait > 0:
                    return wait
                self._hw_desired = None
                job, arg = "ddc", pct
            elif self._active == "xrandr" and self._hw_desired is not None:
                pct, _force = self._hw_desired
                wait = self._xr_wait_locked(pct, now)
                if wait is None:
                    self._hw_desired = None
                    return None
                if wait > 0:
                    return wait
                self._hw_desired = None
                job, arg = "xrandr", pct
            elif self._probe_retry_at is not None and self._backend_req == "ddc" \
                    and self._active == "css" and not self._hw_released:
                # Automatic re-probe after a transient failure (bounded).
                left = self._probe_retry_at - now
                if left > 0:
                    return left
                self._probe_retry_at = None
                self._probe, self._reason = "probing", ""
                log.info("Brightness: probing the monitor again (DDC/CI, attempt %d of %d)",
                         self._probe_retries + 1, len(DDC_PROBE_RETRY_S) + 1)
                out, _ = self._evaluate_locked(now)
                self._emit(out)
                job, arg = "probe", None
            else:
                return None
            ddc_max = self._ddc_max
        if job == "probe":
            reason, mx, cur, detail = self._ddc_probe()
            with self._lock:
                if gen == self._probe_gen and self._backend_req == "ddc":
                    self._probe_retry_at = None
                    if reason:
                        self._fallback_locked(reason, detail)
                        if reason in DDC_TRANSIENT and \
                                self._probe_retries < len(DDC_PROBE_RETRY_S):
                            delay = DDC_PROBE_RETRY_S[self._probe_retries]
                            self._probe_retries += 1
                            self._probe_retry_at = self._clock() + delay
                            log.info("Brightness: DDC/CI probe failed (%s) — retrying in %.0f s",
                                     self._reason, delay)
                    else:
                        self._active, self._probe, self._reason = "ddc", "ok", ""
                        self._ddc_max = mx
                        self._ddc_last_pct = int(round(cur * 100 / mx)) if mx else None
                        self._ddc_last_at = None
                        self._ddc_failures = 0
                        self._ddc_adopt_locked()
                        log.info("Brightness: DDC/CI works (VCP 10 = %d of %d) — hardware dimming",
                                 cur, mx)
                out, _ = self._evaluate_locked(self._clock())
                self._emit(out)
            return 0.0
        if job == "restore":
            if arg == "ddc" and ddc_max:
                self._ddc_write(100, ddc_max)
            elif arg == "xrandr":
                self._xrandr_write(100)
            return 0.0
        if job == "ddc":
            rc, err = self._ddc_write(arg, ddc_max or 100)
            with self._lock:
                self._ddc_last_at = self._clock()
                if rc == 0:
                    self._ddc_last_pct = arg
                    self._ddc_failures = 0
                elif self._active == "ddc" and gen == self._probe_gen:
                    self._ddc_failures += 1
                    if rc == RC_MISSING:
                        self._fallback_locked("no_ddcutil")
                    elif self._ddc_failures >= DDC_MAX_FAILURES:
                        self._fallback_locked("write_failed", err)
                    else:
                        # retry the same value after the spacing
                        self._hw_desired = self._hw_desired or (arg, True)
                out, _ = self._evaluate_locked(self._clock())
                self._emit(out)
            return 0.0
        # xrandr
        rc, err = self._xrandr_write(arg)
        with self._lock:
            self._xr_last_at = self._clock()
            if rc == 0:
                self._xr_last_pct = arg
            elif self._active == "xrandr" and gen == self._probe_gen:
                self._fallback_locked("no_xrandr" if rc == RC_MISSING else "xrandr_failed", err)
            out, _ = self._evaluate_locked(self._clock())
            self._emit(out)
        return 0.0

    def _on_missing(self, prog: str) -> None:
        if prog not in self._missing_logged:
            self._missing_logged.add(prog)
            log.warning("Brightness: %s is not installed", prog)

    def _ddc_display_args(self) -> list[str]:
        d = self.settings.ddc_display
        return ["--display", str(int(d))] if d is not None else []

    def _ddc_probe(self) -> tuple[str, Optional[int], Optional[int], str]:
        """``(reason, max, current, detail)`` — reason '' = DDC/CI works."""
        try:
            if not self._which("ddcutil"):
                return "no_ddcutil", None, None, ""
        except Exception:
            return "no_ddcutil", None, None, ""
        try:
            buses = self._i2c_glob("/dev/i2c-*")
        except Exception:
            buses = []
        if not buses:
            return "no_i2c", None, None, ""
        rc, out, err = _run(self._runner, ["ddcutil", "detect", "--brief"],
                            DDC_DETECT_TIMEOUT_S, on_missing=self._on_missing)
        if rc == RC_MISSING:
            return "no_ddcutil", None, None, ""
        if rc == RC_TIMEOUT:
            return "timeout", None, None, err
        displays = _DISPLAY_LINE_RE.findall(out[:_OUT_MAX])
        wanted = self.settings.ddc_display
        if rc != 0 or not displays or (wanted is not None and str(wanted) not in displays):
            return "no_display", None, None, err
        rc, out, err = _run(self._runner,
                            ["ddcutil", "getvcp", "10", "--brief"] + self._ddc_display_args(),
                            DDC_TIMEOUT_S, on_missing=self._on_missing)
        if rc == RC_MISSING:
            return "no_ddcutil", None, None, ""
        if rc == RC_TIMEOUT:
            return "timeout", None, None, err
        m = _VCP_RE.search(out[:_OUT_MAX])
        if rc != 0 or not m:
            return "no_vcp", None, None, err
        cur, mx = int(m.group(1)), int(m.group(2))
        if not 1 <= mx <= 65535 or cur > mx:
            return "no_vcp", None, None, clean_error(f"VCP 10 = {cur} / {mx}")
        return "", mx, cur, ""

    def _ddc_write(self, pct: int, mx: int) -> tuple[int, str]:
        value = max(0, min(int(mx), int(round(int(pct) * int(mx) / 100.0))))
        rc, _out, err = _run(self._runner,
                             ["ddcutil", "setvcp", "10", str(value)] + self._ddc_display_args(),
                             DDC_TIMEOUT_S, on_missing=self._on_missing)
        if rc != 0:
            log.debug("Brightness: ddcutil setvcp 10 %d failed (%d): %s", value, rc, err)
        return rc, err

    def _xrandr_write(self, pct: int) -> tuple[int, str]:
        s = self.settings
        if xrandr_config_error(s):
            return 2, "invalid xrandr config"
        env = {"DISPLAY": s.xrandr_display}
        if s.xrandr_xauthority:
            env["XAUTHORITY"] = s.xrandr_xauthority
        rc, _out, err = _run(self._runner,
                             ["xrandr", "--output", s.xrandr_output, "--brightness",
                              xrandr_level(pct)],
                             XRANDR_TIMEOUT_S, env_extra=env, on_missing=self._on_missing)
        if rc != 0:
            log.debug("Brightness: xrandr --brightness failed (%d): %s", rc, err)
        return rc, err

    # ── helpers (old API) ─────────────────────────────────────────────────

    def _adc_to_brightness(self, adc: int) -> int:
        """Convert light sensor ADC value to brightness percentage."""
        return adc_to_pct(adc)

    def _find_closest_step(self, brightness: int) -> int:
        """Find the closest manual step to a given brightness."""
        best_idx = 0
        best_diff = abs(BRIGHTNESS_STEPS[0] - brightness)
        for i, step in enumerate(BRIGHTNESS_STEPS):
            diff = abs(step - brightness)
            if diff < best_diff:
                best_diff = diff
                best_idx = i
        return best_idx

    # --- Event handlers (bus dispatcher: record + cheap evaluation only) ---

    def _on_stalk_press(self, topic: str, value: Any, timestamp: float) -> None:
        self.cycle_brightness()

    def _on_light_level(self, topic: str, value: Any, timestamp: float) -> None:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            self.update_from_sensor(value)

    def _on_lux(self, topic: str, value: Any, timestamp: float) -> None:
        if isinstance(value, dict):
            self.update_from_lux(value.get("lux"))

    def _on_config_changed(self, topic: str, value: Any, timestamp: float) -> None:
        """``POST /api/config`` (validated there; checked again here). One
        evaluation for the whole change: backend, then the value, then the
        mode (so "Auto" with a value still means auto now). A module toggle
        (``/api/modules``) goes to :meth:`_on_module_toggle`."""
        if not isinstance(value, dict):
            return
        if "module" in value:
            self._on_module_toggle(value)
            return
        backend = value.get("brightness_backend")
        pct = _pct_or_none(value.get("brightness")) if "brightness" in value else None
        mode = value.get("brightness_mode")
        boost = value.get("brightness_boost")
        boost_ok = isinstance(boost, int) and not isinstance(boost, bool) \
            and BOOST_MIN <= boost <= BOOST_MAX
        if backend not in UI_BACKENDS and pct is None and mode not in MODES and not boost_ok:
            return
        with self._lock:
            now = self._clock()
            if boost_ok and boost != self.settings.boost_pp:
                self.settings = replace(self.settings, boost_pp=boost)
                self._anchor = None          # re-aim at once with the new offset
                log.info("Brightness: calibration %+d pp from Settings", boost)
            if backend in UI_BACKENDS:
                self._select_backend_locked(backend)
            if pct is not None:
                self._set_manual_locked(pct, now)
                log.info("Brightness: %d%% from Settings", self._manual_value)
            if mode in MODES:
                self._set_mode_locked(mode, keep_level=pct is None)
            out, _ = self._evaluate_locked(now)
            self._emit(out)

    def _runs_after_restart(self, value: dict) -> Optional[bool]:
        """Will this module start again after the next BCM restart, with
        the toggles just saved? The catalog decides (also a light source
        switched off: ``requires_any`` phone_sensors | input); without a
        BCMConfig (tests with a dict) only this module's own toggle counts.
        None = cannot tell — nothing changes then."""
        name, enabled = value.get("module"), value.get("enabled")
        if not isinstance(name, str) or not isinstance(enabled, bool):
            return None
        try:
            from src.core import modules_catalog
            return bool(modules_catalog.module_states(self._config)["auto_brightness"].runs)
        except Exception:
            return enabled if name == "auto_brightness" else None

    def _on_module_toggle(self, value: dict) -> None:
        """Settings → Moduły saved a toggle. The module keeps running until
        the restart, but if it will NOT start again, a dimmed monitor (DDC,
        EEPROM) or X gamma would stay dimmed with nothing left to undo it —
        so release the hardware now (100 %, the overlay dims until the
        restart). Switched on again before the restart: the saved choice is
        taken up again (a DDC choice is probed afresh)."""
        runs = self._runs_after_restart(value)
        if runs is None:
            return
        with self._lock:
            if runs is False:
                self._release_hw_locked()
            elif self._hw_released:
                self._hw_released = False
                log.info("Brightness: module on again — %s dimming as chosen", self._backend_req)
                self._select_backend_locked(self._backend_req)
            else:
                return
            out, _ = self._evaluate_locked(self._clock())
            self._emit(out)

    def _on_ignition_off(self, topic: str, value: Any, timestamp: float) -> None:
        self.reset_manual_override()

    def _on_shutdown(self, topic: str, value: Any, timestamp: float) -> None:
        if value:
            self.stop()


# ── the running instance ──────────────────────────────────────────────────

_INSTANCE: Optional[BrightnessController] = None
_INSTANCE_LOCK = threading.Lock()


def get_brightness_controller() -> Optional[BrightnessController]:
    """The running module, or None (not enabled, not started, stopped)."""
    with _INSTANCE_LOCK:
        return _INSTANCE


def start_auto_brightness(config, event_bus, hal=None, **kwargs) -> BrightnessController:
    """Module entry point (``modules.auto_brightness``): builds the
    controller (subscriptions only) and starts its two daemon threads; the
    first evaluation and any ddcutil / xrandr call happen there."""
    global _INSTANCE
    ctrl = BrightnessController(config, event_bus)
    with _INSTANCE_LOCK:
        _INSTANCE = ctrl
    ctrl.start()
    log.info("Auto brightness: running (backend %s, mode %s, floor %d%%)",
             ctrl.settings.backend, ctrl.settings.mode, ctrl.settings.min_pct)
    return ctrl
