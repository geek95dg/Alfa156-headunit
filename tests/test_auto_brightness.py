"""Automatic screen brightness (plan D3, ``modules.auto_brightness``):
src/power/brightness.py, its payload in web_viewer and the Settings switch.

Nothing real runs: the clock is fake, ddcutil / xrandr go to a fake runner
that records the argv (and fails the test if anything looks like a shell),
``which`` / the ``/dev/i2c-*`` glob are fakes, and the bus is the in-process
synchronous EventBus. The module's own threads are only started in one test,
with every tool call replaced by a tripwire.
"""

import math
import subprocess
import threading
import time
from types import SimpleNamespace

import pytest

from src.core.event_bus import EventBus
from src.dashboard import web_viewer as wv
from src.dashboard.web_viewer import WebViewer
from src.power import brightness as br
from src.power.brightness import (
    BrightnessController, DEFAULT_CURVE, TOPIC_DIM, TOPIC_STATE, css_level, curve_pct,
    load_settings, parse_curve, xrandr_config_error, xrandr_level,
)


class FakeClock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


class Res:
    def __init__(self, rc=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


DETECT_OK = "Display 1\n   I2C bus:  /dev/i2c-4\n   Monitor:  ABC:Panel:0001\n\n"
DETECT_INVALID = "Invalid display\n   I2C bus:  /dev/i2c-4\n   DDC communication failed\n"
VCP_OK = "VCP 10 C 60 100\n"


class FakeRunner:
    """``subprocess.run`` stand-in. ``script`` maps the 2nd argv word
    (detect / getvcp / setvcp, or the program for xrandr) to a Res, an
    exception instance, or a callable(argv) returning either."""

    def __init__(self, **script):
        self.calls = []
        self.script = {"detect": Res(0, DETECT_OK), "getvcp": Res(0, VCP_OK),
                       "setvcp": Res(0), "xrandr": Res(0)}
        self.script.update(script)

    def __call__(self, argv, **kw):
        assert isinstance(argv, list) and argv and all(isinstance(a, str) for a in argv), argv
        assert "shell" not in kw and argv[0] in ("ddcutil", "xrandr"), (argv, kw)
        self.calls.append((list(argv), kw))
        key = argv[1] if argv[0] == "ddcutil" else "xrandr"
        res = self.script[key]
        if callable(res) and not isinstance(res, Res):
            res = res(argv)
        if isinstance(res, BaseException):
            raise res
        return res

    def argvs(self, word=None):
        return [a for a, _ in self.calls if word is None or word in a]


def _cfg(**auto):
    cfg = {"display": {"dashboard": {"brightness": 70}}}
    if auto:
        cfg["display"]["auto_brightness"] = auto
    return cfg


def _make(cfg=None, *, runner=None, which=lambda p: "/usr/bin/" + p, i2c=("/dev/i2c-4",)):
    bus = EventBus()
    clock = FakeClock()
    runner = runner if runner is not None else FakeRunner()
    seen = {}
    for topic in ("power.brightness_level", "power.brightness_mode", TOPIC_DIM, TOPIC_STATE,
                  "power.backlight_brightness"):
        seen[topic] = []
        bus.subscribe(topic, lambda t, v, ts: seen[t].append(v))
    ctrl = BrightnessController(_cfg() if cfg is None else cfg, bus, clock=clock, runner=runner,
                                which=which, i2c_glob=lambda pattern: list(i2c))
    return SimpleNamespace(ctrl=ctrl, bus=bus, clock=clock, runner=runner, seen=seen)


def _run_for(m, seconds, lux=None, adc=None, step=0.5, every=2.0):
    """Advance the fake clock, ticking every ``step`` and feeding a sample
    every ``every`` seconds (a heartbeat, like the real sources)."""
    t, last = 0.0, -every
    while t < seconds - 1e-9:
        if t - last >= every - 1e-9:
            if lux is not None:
                m.ctrl.update_from_lux(lux)
            if adc is not None:
                m.ctrl.update_from_sensor(adc)
            last = t
        m.clock.advance(step)
        t += step
        m.ctrl.tick()


def _state(m):
    return m.ctrl.state


# ── the curve ────────────────────────────────────────────────────────────

class TestCurve:
    def test_breakpoints_are_exact(self):
        for lux, pct in DEFAULT_CURVE:
            assert curve_pct(DEFAULT_CURVE, lux) == pytest.approx(pct)

    def test_interpolated_on_a_log_scale(self):
        # the geometric middle (in 1 + lux) of 10 and 100 lux is the middle %
        mid = math.sqrt(11 * 101) - 1                       # ≈ 32.3 lux
        assert curve_pct(DEFAULT_CURVE, mid) == pytest.approx(35.0)
        x = math.log10(1 + 500)
        x0, x1 = math.log10(101), math.log10(1001)
        assert curve_pct(DEFAULT_CURVE, 500) == pytest.approx(45 + 25 * (x - x0) / (x1 - x0))
        values = [curve_pct(DEFAULT_CURVE, lux) for lux in range(0, 20000, 37)]
        assert values == sorted(values)                     # monotonic for this curve

    def test_flat_outside_the_points(self):
        assert curve_pct(DEFAULT_CURVE, -5) == 15
        assert curve_pct(DEFAULT_CURVE, 200000) == 100
        assert curve_pct(((5.0, 30.0), (50.0, 60.0)), 0) == 30

    @pytest.mark.parametrize("value", [
        None, "x", [], [[0, 15]], [[0, 15], [10]], [[0, 15], [0, 20]], [[10, 15], [5, 20]],
        [[0, 15], [10, 101]], [[0, -1], [10, 20]], [[-1, 15], [10, 20]],
        [[0, 15], [10, float("nan")]], [[0, 15], [float("inf"), 20]], [[0, True], [10, 20]],
        [[0, "15"], [10, 20]], [[0, 15], [300000, 20]], [[i, 20] for i in range(17)],
    ])
    def test_invalid_curves(self, value):
        assert parse_curve(value) is None

    def test_valid_curve(self):
        assert parse_curve([[0, 10], [5.5, 20], [100, 90]]) == ((0.0, 10.0), (5.5, 20.0),
                                                                (100.0, 90.0))


class TestSettings:
    def test_defaults(self):
        s = load_settings({})
        assert s.curve == DEFAULT_CURVE and s.min_pct == 15 and s.max_pct == 100
        assert s.smoothing_s == 3.0 and s.stale_s == 10.0 and s.manual_hold_s == 600.0
        assert s.hysteresis_ratio == pytest.approx(0.10) and s.hysteresis_pp == 5
        assert s.backend == "auto" and s.mode == "auto" and s.ddc_display is None

    def test_bad_values_fall_back_with_a_warning(self, caplog):
        s = load_settings(_cfg(curve=[[10, 1], [5, 2]], min_pct="x", backend="neon",
                               mode="night", ddc_display=True, smoothing_s=float("nan"),
                               manual_hold_min=True))
        assert s.curve == DEFAULT_CURVE and s.min_pct == 15 and s.backend == "auto"
        assert s.mode == "auto" and s.ddc_display is None and s.smoothing_s == 3.0
        assert s.manual_hold_s == 600.0
        text = caplog.text
        for key in ("curve", "min_pct", "backend", "mode", "ddc_display", "smoothing_s",
                    "manual_hold_min"):
            assert f"display.auto_brightness.{key}" in text, key

    def test_limits(self):
        s = load_settings(_cfg(min_pct=1, max_pct=3, hysteresis_pct=200, css_max_dim=0.99,
                               ddc_display=2, manual_hold_min=5))
        assert s.min_pct == br.MIN_PCT_FLOOR and s.max_pct == br.MIN_PCT_FLOOR
        assert s.hysteresis_ratio == pytest.approx(0.5)
        assert s.css_max_dim == br.CSS_MAX_DIM_LIMIT and s.ddc_display == 2
        assert s.manual_hold_s == 300.0
        assert load_settings(_cfg(min_pct=40, max_pct=20)).max_pct == 40

    def test_shipped_configs(self):
        from pathlib import Path

        from src.core.config import BCMConfig
        root = Path(__file__).resolve().parent.parent
        test = BCMConfig(config_path=str(root / "config" / "bcm_config_test.yaml"),
                         platform_override="x86", local_path=None, env={})
        s = load_settings(test)
        assert s.backend == "css" and s.curve == DEFAULT_CURVE and s.min_pct == 15
        final = BCMConfig(config_path=str(root / "config" / "bcm_config.yaml"),
                          platform_override="x86", local_path=None, env={})
        s = load_settings(final)                # same block in the car's final config
        assert s.backend == "css" and s.curve == DEFAULT_CURVE and s.min_pct == 15


# ── the automatic path ───────────────────────────────────────────────────

class TestAutoPath:
    def test_first_reading_applies_at_once(self):
        m = _make()
        assert m.ctrl.update_from_lux(0.0) == 15
        assert m.seen["power.brightness_level"] == [15]
        assert {d["display"] for d in m.seen["power.backlight_brightness"]} == {"small", "large"}
        st = _state(m)
        assert st["effective"] == "auto" and st["source"] == "phone" and st["lux"] == 0.0

    def test_smoothing_is_an_ema_of_about_3_s(self):
        m = _make()
        m.ctrl.update_from_lux(0.0)                           # 15 %
        m.ctrl.update_from_lux(10000.0)                       # target 100 %
        m.clock.advance(3.0)
        m.ctrl.tick()
        ema = 15 + 85 * (1 - math.exp(-1))                    # one time constant: 63 %
        assert ema - 5 < m.ctrl.brightness <= ema + 0.5
        # it glides in steps of >= 5 pp, then lands exactly on the target
        _run_for(m, 30, lux=10000.0)
        assert m.ctrl.brightness == 100
        steps = m.seen["power.brightness_level"][1:]
        diffs = [b - a for a, b in zip([15] + steps, steps)]
        assert all(d >= 5 for d in diffs[:-1]) and diffs[-1] > 0, steps

    def test_smoothing_is_symmetric(self):
        up, down = _make(), _make()
        up.ctrl.update_from_lux(0.0)
        up.ctrl.update_from_lux(10000.0)
        down.ctrl.update_from_lux(10000.0)
        down.ctrl.update_from_lux(0.0)
        for m in (up, down):
            m.clock.advance(3.0)
            m.ctrl.tick()
        assert abs((up.ctrl.brightness - 15) - (100 - down.ctrl.brightness)) <= 5

    def test_no_smoothing_when_switched_off(self):
        m = _make(_cfg(smoothing_s=0))
        m.ctrl.update_from_lux(0.0)
        m.ctrl.update_from_lux(10000.0)
        assert m.ctrl.brightness == 100

    def test_input_hysteresis_10_percent(self):
        m = _make()
        m.ctrl.update_from_lux(100.0)
        assert _state(m)["target_pct"] == 45
        m.ctrl.update_from_lux(109.0)                         # +9 %: same target
        assert _state(m)["target_pct"] == 45
        m.ctrl.update_from_lux(91.0)                          # -9 %
        assert _state(m)["target_pct"] == 45
        m.ctrl.update_from_lux(120.0)                         # +20 %: new target
        assert _state(m)["target_pct"] == round(curve_pct(DEFAULT_CURVE, 120.0))

    def test_low_lux_band_is_at_least_half_a_lux(self):
        m = _make(_cfg(curve=[[0, 15], [2, 60]]))
        m.ctrl.update_from_lux(0.0)
        m.ctrl.update_from_lux(0.4)
        assert _state(m)["target_pct"] == 15
        m.ctrl.update_from_lux(0.6)
        assert _state(m)["target_pct"] > 15

    def test_output_steps_while_gliding_then_one_small_step(self):
        m = _make()
        _run_for(m, 20, lux=100.0)
        assert m.ctrl.brightness == 45
        before = len(m.seen["power.brightness_level"])
        _run_for(m, 30, lux=125.0)                            # target ≈ 47.4 %
        assert m.seen["power.brightness_level"][before:] == [47]   # no 46 on the way

    def test_floor_and_ceiling(self):
        m = _make(_cfg(min_pct=25, max_pct=80))
        m.ctrl.update_from_lux(0.0)
        assert m.ctrl.brightness == 25
        m = _make(_cfg(min_pct=25, max_pct=80, smoothing_s=0))
        m.ctrl.update_from_lux(50000.0)
        assert m.ctrl.brightness == 80

    def test_stale_input_holds_the_last_value(self):
        m = _make()
        m.ctrl.update_from_lux(0.0)
        m.clock.advance(10.5)
        m.ctrl.tick()
        st = _state(m)
        assert st["effective"] == "stale" and st["source"] == "" and st["lux"] is None
        for _ in range(600):                                  # 5 minutes of ticks
            m.clock.advance(0.5)
            m.ctrl.tick()
        assert m.ctrl.brightness == 15 and _state(m)["effective"] == "stale"

    def test_no_source_means_the_manual_value(self):
        m = _make()
        m.ctrl.tick()
        assert m.ctrl.brightness == 70 and _state(m)["effective"] == "no_source"
        m.bus.publish("config.changed", {"brightness": 40})
        assert m.ctrl.brightness == 40

    def test_phone_wins_over_the_arduino_when_both_are_fresh(self):
        m = _make()
        m.ctrl.update_from_lux(0.0)                           # phone: 15 %
        m.ctrl.update_from_sensor(50)                         # LDR: bright → 100 %
        _run_for(m, 8, adc=50)                                # phone still fresh
        assert m.ctrl.brightness == 15 and _state(m)["source"] == "phone"
        _run_for(m, 30, adc=50)                               # phone stale → LDR
        assert _state(m)["source"] == "arduino" and m.ctrl.brightness == 100
        _run_for(m, 30, lux=0.0, adc=50)                      # phone back
        assert _state(m)["source"] == "phone" and m.ctrl.brightness == 15

    def test_arduino_alone_uses_the_old_table_with_hysteresis(self):
        m = _make(_cfg(smoothing_s=0))
        assert m.ctrl.update_from_sensor(350) == 60
        assert m.ctrl.update_from_sensor(380) is None          # within 30 counts
        assert m.ctrl.update_from_sensor(520) == 45
        assert _state(m)["adc"] == 520

    @pytest.mark.parametrize("bad", ["12", None, True, float("nan"), float("inf"), -1, 200001])
    def test_bad_lux_is_ignored(self, bad):
        m = _make()
        assert m.ctrl.update_from_lux(bad) is None
        m.bus.publish("phone.light_lux", {"lux": bad, "ts": 1})
        m.bus.publish("phone.light_lux", "100")
        assert m.seen["power.brightness_level"] == [] and _state(m) is None

    @pytest.mark.parametrize("bad", ["12", True, -1, 1024, float("nan")])
    def test_bad_adc_is_ignored(self, bad):
        m = _make()
        m.bus.publish("arduino.light_level", bad)
        assert m.seen["power.brightness_level"] == []


# ── manual ───────────────────────────────────────────────────────────────

class TestManual:
    def test_stalk_pauses_auto_for_10_min_then_resumes(self):
        m = _make()
        m.ctrl.update_from_lux(0.0)                           # 15 %
        m.bus.publish("input.brightness_cycle", True)         # closest step: 15
        m.bus.publish("input.brightness_cycle", True)         # → 30
        assert m.ctrl.brightness == 30 and m.ctrl.mode == "manual"
        st = _state(m)
        assert st["effective"] == "hold" and st["hold_left_min"] == 10
        _run_for(m, 9 * 60 + 50, lux=0.0, step=5.0)
        assert m.ctrl.brightness == 30 and _state(m)["hold_left_min"] == 1
        _run_for(m, 15, lux=0.0)
        assert m.ctrl.mode == "auto" and _state(m)["effective"] == "auto"
        assert "auto" in m.seen["power.brightness_mode"]
        _run_for(m, 30, lux=0.0)
        assert m.ctrl.brightness == 15                        # glided back

    def test_resume_glides_from_the_manual_value(self):
        m = _make(_cfg(manual_hold_min=1))
        m.ctrl.update_from_lux(0.0)
        m.ctrl.set_manual(100)
        _run_for(m, 60, lux=0.0)
        m.clock.advance(1.0)
        m.ctrl.update_from_lux(0.0)
        assert 60 < m.ctrl.brightness < 100                   # not a jump to 15

    def test_settings_value_pauses_auto(self):
        m = _make()
        m.ctrl.update_from_lux(0.0)
        m.bus.publish("config.changed", {"brightness": 80})
        assert m.ctrl.brightness == 80 and _state(m)["effective"] == "hold"
        _run_for(m, 601, lux=0.0, step=5.0)
        _run_for(m, 30, lux=0.0)
        assert m.ctrl.brightness == 15

    def test_mode_manual_ignores_the_sensor_until_auto(self):
        m = _make()
        m.ctrl.update_from_lux(0.0)
        m.bus.publish("config.changed", {"brightness_mode": "manual"})
        # frozen at what was on screen (15 %), not the older slider value 70
        assert m.ctrl.brightness == 15 and _state(m)["effective"] == "manual"
        assert _state(m)["hold_left_min"] is None and _state(m)["manual_pct"] == 15
        _run_for(m, 3600, lux=10000.0, step=5.0, every=5.0)
        assert m.ctrl.brightness == 15
        m.bus.publish("config.changed", {"brightness": 55})   # the slider in manual
        assert m.ctrl.brightness == 55 and _state(m)["effective"] == "manual"
        m.bus.publish("config.changed", {"brightness_mode": "auto"})
        assert _state(m)["effective"] == "auto"
        _run_for(m, 30, lux=0.0)
        assert m.ctrl.brightness == 15

    def test_manual_freezes_the_current_level_at_night(self):
        m = _make()                                           # slider value 70
        _run_for(m, 20, lux=3.0)
        night = m.ctrl.brightness
        assert 15 < night < 30
        n = len(m.seen["power.brightness_level"])
        m.ctrl.set_mode("manual")
        assert m.ctrl.brightness == night and _state(m)["manual_pct"] == night
        assert len(m.seen["power.brightness_level"]) == n     # no jump at all
        # the slider in the same change wins over the frozen level
        m = _make()
        _run_for(m, 20, lux=3.0)
        m.bus.publish("config.changed", {"brightness_mode": "manual", "brightness": 40})
        assert m.ctrl.brightness == 40 and _state(m)["effective"] == "manual"

    def test_manual_during_a_stalk_pause_keeps_the_stalk_value(self):
        m = _make()
        m.ctrl.update_from_lux(0.0)
        m.ctrl.cycle_brightness()
        m.ctrl.cycle_brightness()                             # 30 %
        m.ctrl.set_mode("manual")
        assert m.ctrl.brightness == 30 and _state(m)["effective"] == "manual"

    def test_mode_manual_from_the_config(self):
        m = _make(_cfg(mode="manual"))
        m.ctrl.update_from_lux(10000.0)
        assert m.ctrl.brightness == 70 and m.ctrl.mode == "manual"

    def test_floor_applies_to_manual_values(self):
        m = _make()
        m.bus.publish("config.changed", {"brightness": 0})
        assert m.ctrl.brightness == 15
        m = _make(_cfg(min_pct=30))
        m.ctrl.cycle_brightness()
        assert m.ctrl.cycle_brightness() >= 30 and m.ctrl.brightness >= 30

    def test_ignition_off_ends_the_pause(self):
        m = _make()
        m.ctrl.update_from_lux(0.0)
        m.ctrl.set_manual(90)
        m.bus.publish("power.ignition_off", True)
        assert m.ctrl.mode == "auto"
        assert m.seen["power.brightness_mode"][-1] == "auto"

    def test_ignition_off_in_manual_mode_reports_manual(self):
        m = _make(_cfg(mode="manual"))
        m.ctrl.cycle_brightness()
        m.bus.publish("power.ignition_off", True)
        assert m.ctrl.mode == "manual"
        assert m.seen["power.brightness_mode"][-1] == "manual"

    @pytest.mark.parametrize("value", [
        {"brightness": "80"}, {"brightness": True}, {"brightness": 101}, {"brightness": 50.5},
        {"brightness_backend": "xrandr"}, {"brightness_backend": "auto"},
        {"brightness_mode": "night"}, {"module": "auto_brightness", "enabled": True},
        "brightness", None, ["brightness", 1],
    ])
    def test_bad_config_changes_are_ignored(self, value):
        m = _make()
        m.ctrl.update_from_lux(0.0)
        before = (m.ctrl.brightness, dict(_state(m)))
        m.bus.publish("config.changed", value)
        assert (m.ctrl.brightness, _state(m)) == before


# ── css: the overlay payload ─────────────────────────────────────────────

class TestCss:
    def test_dim_payload(self):
        m = _make()
        m.ctrl.update_from_lux(0.0)
        dim = m.seen[TOPIC_DIM][-1]
        assert dim == {"level": css_level(15, 0.85), "brightness_pct": 15}
        assert dim["level"] == pytest.approx(0.85 * 0.85, abs=1e-3)
        m.ctrl.set_manual(100)
        assert m.seen[TOPIC_DIM][-1] == {"level": 0.0, "brightness_pct": 100}

    def test_published_only_on_change(self):
        m = _make()
        m.ctrl.update_from_lux(0.0)
        n = len(m.seen[TOPIC_DIM]), len(m.seen[TOPIC_STATE])
        for _ in range(20):
            m.clock.advance(0.5)
            m.ctrl.update_from_lux(0.0)
        assert (len(m.seen[TOPIC_DIM]), len(m.seen[TOPIC_STATE])) == n

    def test_level_formula_and_cap(self):
        assert css_level(100, 0.85) == 0.0
        assert css_level(0, 0.85) == 0.85
        assert css_level(0, 5.0) == br.CSS_MAX_DIM_LIMIT
        assert css_level(50, 0.5) == 0.25
        m = _make(_cfg(css_max_dim=0.5))
        m.ctrl.set_manual(20)
        assert m.seen[TOPIC_DIM][-1]["level"] == pytest.approx(0.4)

    def test_css_never_runs_a_tool(self):
        m = _make(_cfg(backend="css"))
        _run_for(m, 60, lux=50.0)
        m.ctrl.set_manual(40)
        for _ in range(5):
            assert m.ctrl.hw_step() is None
        assert m.runner.calls == []
        assert _state(m)["active"] == "css" and _state(m)["probe"] == "idle"


# ── ddc ──────────────────────────────────────────────────────────────────

def _ddc(cfg_extra=None, **kw):
    m = _make(_cfg(backend="ddc", **(cfg_extra or {})), **kw)
    m.ctrl.tick()
    return m


#: Manual mode: the slider value (70) is written right after the probe —
#: in automatic mode the monitor's own level is kept until the first light
#: reading (TestDdcBootLevel).
MANUAL = {"mode": "manual"}


def _drain(m, limit=10):
    for _ in range(limit):
        if m.ctrl.hw_step() != 0.0:
            return


class TestDdc:
    def test_overlay_stays_while_probing(self):
        m = _ddc()
        st = _state(m)
        assert st["backend"] == "ddc" and st["probe"] == "probing" and st["active"] == "css"
        assert m.seen[TOPIC_DIM][-1]["level"] > 0 and m.runner.calls == []

    def test_probe_then_write(self):
        m = _ddc(MANUAL)
        _drain(m)
        assert m.runner.argvs() == [["ddcutil", "detect", "--brief"],
                                    ["ddcutil", "getvcp", "10", "--brief"],
                                    ["ddcutil", "setvcp", "10", "70"]]
        kws = [kw for _a, kw in m.runner.calls]
        assert [kw["timeout"] for kw in kws] == [br.DDC_DETECT_TIMEOUT_S, br.DDC_TIMEOUT_S,
                                                 br.DDC_TIMEOUT_S]
        assert all(kw["env"]["LC_ALL"] == "C" and kw["capture_output"] for kw in kws)
        st = _state(m)
        assert st["active"] == "ddc" and st["probe"] == "ok" and st["reason"] == ""
        assert m.seen[TOPIC_DIM][-1] == {"level": 0.0, "brightness_pct": 70}   # overlay gone

    def test_value_scaled_to_the_monitors_max(self):
        m = _ddc(MANUAL, runner=FakeRunner(getvcp=Res(0, "VCP 10 C 10 50\n")))
        _drain(m)
        assert m.runner.argvs("setvcp") == [["ddcutil", "setvcp", "10", "35"]]

    def test_display_number_from_the_config(self):
        m = _ddc(dict(MANUAL, ddc_display=2), runner=FakeRunner(detect=Res(0, DETECT_OK.replace(
            "Display 1", "Display 1\n\nDisplay 2"))))
        _drain(m)
        assert m.runner.argvs()[1:] == [["ddcutil", "getvcp", "10", "--brief", "--display", "2"],
                                        ["ddcutil", "setvcp", "10", "70", "--display", "2"]]

    def test_rate_limit_and_coalescing(self):
        m = _ddc(MANUAL)
        _drain(m)
        n = len(m.runner.calls)
        m.clock.advance(1.0)
        m.ctrl.set_manual(40)
        wait = m.ctrl.hw_step()
        assert wait == pytest.approx(br.DDC_MIN_INTERVAL_S - 1.0)
        m.clock.advance(1.0)
        m.ctrl.set_manual(50)
        assert m.ctrl.hw_step() == pytest.approx(br.DDC_MIN_INTERVAL_S - 2.0)
        assert len(m.runner.calls) == n                         # nothing written yet
        m.clock.advance(3.0)
        _drain(m)
        assert m.runner.argvs("setvcp")[-1] == ["ddcutil", "setvcp", "10", "50"]
        assert len(m.runner.calls) == n + 1                     # 40 was never written

    def test_small_automatic_steps_are_not_written(self):
        m = _ddc()
        _run_for(m, 20, lux=100.0)                              # auto → 45 %
        _drain(m)
        m.clock.advance(10)
        _drain(m)
        assert m.runner.argvs("setvcp")[-1] == ["ddcutil", "setvcp", "10", "45"]
        n = len(m.runner.argvs("setvcp"))
        _run_for(m, 30, lux=125.0)                              # settles on 47 %
        assert m.ctrl.brightness == 47
        _drain(m)
        assert len(m.runner.argvs("setvcp")) == n               # 2 pp: not worth the EEPROM
        _run_for(m, 30, lux=1000.0)                             # → 70 %, >= 5 pp steps
        m.clock.advance(10)
        _drain(m)
        assert m.runner.argvs("setvcp")[-1] == ["ddcutil", "setvcp", "10", "70"]

    def test_manual_small_change_is_written(self):
        m = _ddc()
        _drain(m)
        m.clock.advance(10)
        m.ctrl.set_manual(72)
        _drain(m)
        assert m.runner.argvs("setvcp")[-1] == ["ddcutil", "setvcp", "10", "72"]

    @pytest.mark.parametrize("which, i2c, script, reason", [
        (lambda p: None, ("/dev/i2c-4",), {}, "no_ddcutil"),
        (lambda p: "/usr/bin/ddcutil", (), {}, "no_i2c"),
        (lambda p: "/usr/bin/ddcutil", ("/dev/i2c-4",), {"detect": Res(1, "", "x")}, "no_display"),
        (lambda p: "/usr/bin/ddcutil", ("/dev/i2c-4",), {"detect": Res(0, DETECT_INVALID)},
         "no_display"),
        (lambda p: "/usr/bin/ddcutil", ("/dev/i2c-4",), {"detect": Res(0, "No displays found.\n")},
         "no_display"),
        (lambda p: "/usr/bin/ddcutil", ("/dev/i2c-4",),
         {"detect": subprocess.TimeoutExpired("ddcutil", 15)}, "timeout"),
        (lambda p: "/usr/bin/ddcutil", ("/dev/i2c-4",), {"detect": FileNotFoundError()},
         "no_ddcutil"),
        (lambda p: "/usr/bin/ddcutil", ("/dev/i2c-4",), {"getvcp": Res(0, "garbage\n")}, "no_vcp"),
        (lambda p: "/usr/bin/ddcutil", ("/dev/i2c-4",), {"getvcp": Res(1, "", "DDC failed")},
         "no_vcp"),
        (lambda p: "/usr/bin/ddcutil", ("/dev/i2c-4",), {"getvcp": Res(0, "VCP 10 C 90 0\n")},
         "no_vcp"),
        (lambda p: "/usr/bin/ddcutil", ("/dev/i2c-4",),
         {"getvcp": subprocess.TimeoutExpired("ddcutil", 5)}, "timeout"),
    ])
    def test_probe_failure_falls_back_to_css(self, which, i2c, script, reason):
        m = _ddc(runner=FakeRunner(**script), which=which, i2c=i2c)
        _drain(m)
        st = _state(m)
        assert (st["active"], st["probe"], st["reason"]) == ("css", "failed", reason)
        assert m.seen[TOPIC_DIM][-1]["level"] > 0                # the overlay dims again
        assert m.runner.argvs("setvcp") == []
        if reason in ("no_i2c",) or which("ddcutil") is None:
            assert m.runner.calls == []                          # nothing run at all

    def test_wanted_display_missing_is_no_display(self):
        m = _ddc({"ddc_display": 3})
        _drain(m)
        assert _state(m)["reason"] == "no_display"

    def test_three_failed_writes_fall_back_and_restore(self):
        m = _ddc(MANUAL, runner=FakeRunner(setvcp=Res(1, "", "Verification failed")))
        _drain(m)                                                # write 1 fails
        for _ in range(br.DDC_MAX_FAILURES - 1):                 # writes 2 and 3 fail
            m.clock.advance(br.DDC_MIN_INTERVAL_S)
            _drain(m)
        st = _state(m)
        assert (st["active"], st["reason"]) == ("css", "write_failed")
        assert m.seen[TOPIC_DIM][-1]["level"] > 0                # overlay asked for first
        assert m.runner.argvs("setvcp") == [["ddcutil", "setvcp", "10", "70"]] * 3
        m.clock.advance(br.HW_RESTORE_DELAY_S)
        _drain(m)
        writes = m.runner.argvs("setvcp")
        assert writes[-1] == ["ddcutil", "setvcp", "10", "100"]   # one best-effort restore
        assert len(writes) == br.DDC_MAX_FAILURES + 1
        n = len(m.runner.calls)
        m.clock.advance(60)
        m.ctrl.set_manual(30)
        _drain(m)
        assert len(m.runner.calls) == n                          # no retry loop on the I2C bus

    def test_binary_gone_at_run_time(self):
        m = _ddc(MANUAL, runner=FakeRunner(setvcp=FileNotFoundError()))
        _drain(m)
        st = _state(m)
        assert (st["active"], st["reason"]) == ("css", "no_ddcutil")
        assert m.runner.argvs("setvcp") == [["ddcutil", "setvcp", "10", "70"]]   # no restore

    def test_switch_back_to_css_restores_full_brightness(self):
        m = _ddc(MANUAL)
        _drain(m)
        m.bus.publish("config.changed", {"brightness_backend": "css"})
        st = _state(m)
        assert (st["backend"], st["active"], st["probe"]) == ("css", "css", "idle")
        assert m.seen[TOPIC_DIM][-1]["level"] == css_level(70, 0.85)
        _drain(m)
        assert m.runner.argvs("setvcp")[-1] == ["ddcutil", "setvcp", "10", "70"]
        m.clock.advance(br.HW_RESTORE_DELAY_S)
        _drain(m)
        assert m.runner.argvs("setvcp")[-1] == ["ddcutil", "setvcp", "10", "100"]

    def test_reselecting_ddc_while_it_works_does_not_reprobe(self):
        m = _ddc()
        _drain(m)
        m.bus.publish("config.changed", {"brightness_backend": "ddc"})
        _drain(m)
        assert len(m.runner.argvs("detect")) == 1 and _state(m)["active"] == "ddc"

    def test_reselecting_after_a_failure_probes_again(self):
        m = _ddc(which=lambda p: None)
        _drain(m)
        assert _state(m)["reason"] == "no_ddcutil"
        m.ctrl._which = lambda p: "/usr/bin/ddcutil"            # installed meanwhile
        m.bus.publish("config.changed", {"brightness_backend": "ddc"})
        assert _state(m)["probe"] == "probing"
        _drain(m)
        assert _state(m)["active"] == "ddc"

    def test_probe_result_discarded_when_the_choice_changed(self):
        holder = {}

        def detect(argv):
            holder["m"].ctrl.set_backend("css")                 # the driver taps "Programowe"
            return Res(0, DETECT_OK)

        m = _make(_cfg(backend="ddc"), runner=FakeRunner(detect=detect))
        holder["m"] = m
        m.ctrl.tick()
        _drain(m)
        st = _state(m)
        assert (st["backend"], st["active"], st["probe"]) == ("css", "css", "idle")
        assert m.runner.argvs("setvcp") == []

    def test_settings_switch_applies_live(self):
        m = _make(_cfg(backend="css"))
        m.ctrl.tick()
        m.bus.publish("config.changed", {"brightness_backend": "ddc"})
        assert _state(m)["probe"] == "probing"
        _drain(m)
        assert _state(m)["active"] == "ddc"


class _Seq:
    """A runner script entry that answers from a list (the last one
    repeats)."""

    def __init__(self, *answers):
        self.answers = list(answers)

    def __call__(self, argv):
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]


class TestDdcBootLevel:
    """Every drive is a cold boot and the light reading comes only after the
    phone's adb forward: before it, the monitor keeps its own level from the
    last drive (no jump to the slider value at a night start)."""

    def test_the_monitors_level_is_kept_until_the_first_reading(self):
        m = _ddc(runner=FakeRunner(getvcp=Res(0, "VCP 10 C 15 100\n")))
        _drain(m)
        assert _state(m)["active"] == "ddc" and m.ctrl.brightness == 15
        assert m.runner.argvs("setvcp") == []                  # not raised to 70
        for _ in range(5):
            m.clock.advance(5)
            m.ctrl.tick()
            _drain(m)
        assert m.runner.argvs("setvcp") == [] and m.ctrl.brightness == 15
        _run_for(m, 40, lux=100.0)                              # the first reading decides
        _drain(m)
        m.clock.advance(10)
        _drain(m)
        assert m.runner.argvs("setvcp")[-1] == ["ddcutil", "setvcp", "10", "45"]

    def test_below_the_floor_is_raised_to_it(self):
        m = _ddc(runner=FakeRunner(getvcp=Res(0, "VCP 10 C 5 100\n")))
        _drain(m)
        assert m.ctrl.brightness == 15
        assert m.runner.argvs("setvcp") == [["ddcutil", "setvcp", "10", "15"]]

    def test_a_manual_choice_before_the_probe_is_written(self):
        m = _ddc(runner=FakeRunner(getvcp=Res(0, "VCP 10 C 15 100\n")))
        m.ctrl.set_manual(60)
        _drain(m)
        assert m.runner.argvs("setvcp") == [["ddcutil", "setvcp", "10", "60"]]


class TestDdcRetry:
    """A transient probe failure at boot (cold monitor) is retried by
    itself, a bounded number of times; a missing tool is not."""

    def test_timeout_then_ok_on_the_second_probe(self):
        runner = FakeRunner(detect=_Seq(subprocess.TimeoutExpired("ddcutil", 15),
                                        Res(0, DETECT_OK)))
        m = _ddc(MANUAL, runner=runner)
        _drain(m)
        st = _state(m)
        assert (st["active"], st["probe"], st["reason"]) == ("css", "failed", "timeout")
        assert m.ctrl.hw_step() == pytest.approx(br.DDC_PROBE_RETRY_S[0])
        assert len(runner.argvs("detect")) == 1
        m.clock.advance(br.DDC_PROBE_RETRY_S[0] - 1)
        assert m.ctrl.hw_step() == pytest.approx(1.0)
        assert len(runner.argvs("detect")) == 1                  # not before it is due
        m.clock.advance(1)
        _drain(m)
        st = _state(m)
        assert (st["active"], st["probe"], st["reason"]) == ("ddc", "ok", "")
        assert len(runner.argvs("detect")) == 2
        # the monitor (maybe left dim from the night drive) gets the value now
        assert runner.argvs("setvcp") == [["ddcutil", "setvcp", "10", "70"]]
        probes = [v["probe"] for v in m.seen[TOPIC_STATE]]
        assert probes.count("probing") >= 2                      # the row said so again
        assert m.seen[TOPIC_DIM][-1]["level"] == 0.0

    def test_permanent_failure_gives_exactly_three_retries(self):
        runner = FakeRunner(detect=Res(0, DETECT_INVALID))
        m = _ddc(runner=runner)
        _drain(m)
        for delay in br.DDC_PROBE_RETRY_S:
            assert m.ctrl.hw_step() == pytest.approx(delay)
            m.clock.advance(delay)
            _drain(m)
        assert len(runner.argvs("detect")) == 1 + len(br.DDC_PROBE_RETRY_S)
        assert m.ctrl.hw_step() is None                          # budget used up
        for _ in range(20):
            m.clock.advance(60)
            m.ctrl.tick()
            _drain(m)
        assert len(runner.argvs("detect")) == 4 and runner.argvs("setvcp") == []
        st = _state(m)
        assert (st["active"], st["probe"], st["reason"]) == ("css", "failed", "no_display")

    @pytest.mark.parametrize("which, i2c, reason", [
        (lambda p: None, ("/dev/i2c-4",), "no_ddcutil"),
        (lambda p: "/usr/bin/ddcutil", (), "no_i2c"),
    ])
    def test_missing_tool_or_bus_is_final(self, which, i2c, reason):
        m = _ddc(which=which, i2c=i2c)
        _drain(m)
        assert _state(m)["reason"] == reason
        assert m.ctrl.hw_step() is None
        m.clock.advance(1000)
        _drain(m)
        assert m.runner.calls == [] and _state(m)["probe"] == "failed"

    def test_missing_ddcutil_found_on_a_retry_is_final(self):
        runner = FakeRunner(detect=_Seq(subprocess.TimeoutExpired("ddcutil", 15),
                                        FileNotFoundError()))
        m = _ddc(runner=runner)
        _drain(m)
        m.clock.advance(br.DDC_PROBE_RETRY_S[0])
        _drain(m)
        assert _state(m)["reason"] == "no_ddcutil" and m.ctrl.hw_step() is None

    def test_choosing_css_cancels_a_pending_retry(self):
        runner = FakeRunner(detect=subprocess.TimeoutExpired("ddcutil", 15))
        m = _ddc(runner=runner)
        _drain(m)
        m.bus.publish("config.changed", {"brightness_backend": "css"})
        m.clock.advance(1000)
        _drain(m)
        assert len(runner.argvs("detect")) == 1
        assert (_state(m)["backend"], _state(m)["probe"]) == ("css", "idle")

    def test_tapping_ddc_again_resets_the_budget(self):
        runner = FakeRunner(detect=Res(0, DETECT_INVALID))
        m = _ddc(runner=runner)
        _drain(m)
        m.clock.advance(br.DDC_PROBE_RETRY_S[0])
        _drain(m)                                                # retry 1 used
        assert len(runner.argvs("detect")) == 2
        m.bus.publish("config.changed", {"brightness_backend": "ddc"})
        _drain(m)                                                # probes at once
        assert len(runner.argvs("detect")) == 3
        for delay in br.DDC_PROBE_RETRY_S:                       # the full budget again
            m.clock.advance(delay)
            _drain(m)
        assert len(runner.argvs("detect")) == 3 + len(br.DDC_PROBE_RETRY_S)
        assert m.ctrl.hw_step() is None

    def test_write_failure_after_a_good_probe_is_not_reprobed(self):
        m = _ddc(MANUAL, runner=FakeRunner(setvcp=Res(1, "", "Verification failed")))
        _drain(m)
        for _ in range(br.DDC_MAX_FAILURES):
            m.clock.advance(br.DDC_MIN_INTERVAL_S)
            _drain(m)
        m.clock.advance(1000)
        _drain(m)
        assert len(m.runner.argvs("detect")) == 1 and _state(m)["reason"] == "write_failed"


class TestRestoreDelay:
    def test_no_full_bright_write_before_the_overlay_faded_in(self):
        m = _ddc()
        m.ctrl.update_from_lux(0.0)                              # night: 15 %
        _drain(m)
        assert m.runner.argvs("setvcp")[-1] == ["ddcutil", "setvcp", "10", "15"]
        m.ctrl.set_backend("css")
        assert m.seen[TOPIC_DIM][-1]["level"] == css_level(15, 0.85)   # overlay at once
        wait = m.ctrl.hw_step()
        assert wait == pytest.approx(br.HW_RESTORE_DELAY_S)
        m.clock.advance(br.HW_RESTORE_DELAY_S - 0.1)
        assert m.ctrl.hw_step() == pytest.approx(0.1)
        assert m.runner.argvs("setvcp")[-1] == ["ddcutil", "setvcp", "10", "15"]
        m.clock.advance(0.1)
        _drain(m)
        assert m.runner.argvs("setvcp")[-1] == ["ddcutil", "setvcp", "10", "100"]

    def test_restore_comes_before_what_a_new_choice_writes(self):
        m = _ddc(MANUAL)
        _drain(m)
        m.ctrl.set_backend("css")
        m.ctrl.set_backend("ddc")                                # re-chosen at once
        m.clock.advance(br.HW_RESTORE_DELAY_S)
        _drain(m)
        words = [a[1] for a in m.runner.argvs()]
        assert words == ["detect", "getvcp", "setvcp", "setvcp", "detect", "getvcp", "setvcp"]
        assert m.runner.argvs("setvcp")[-2:] == [["ddcutil", "setvcp", "10", "100"],
                                                 ["ddcutil", "setvcp", "10", "70"]]


class TestModuleToggle:
    """Settings → Moduły switches the module off: it runs until the
    restart, but must give the monitor back now."""

    def test_switching_the_module_off_restores_the_monitor(self):
        m = _ddc()
        m.ctrl.update_from_lux(0.0)
        _drain(m)
        m.bus.publish("config.changed", {"module": "auto_brightness", "enabled": False,
                                         "also": []})
        st = _state(m)
        assert (st["backend"], st["active"], st["probe"]) == ("ddc", "css", "idle")
        assert m.seen[TOPIC_DIM][-1]["level"] == css_level(15, 0.85)
        m.clock.advance(br.HW_RESTORE_DELAY_S)
        _drain(m)
        assert m.runner.argvs("setvcp")[-1] == ["ddcutil", "setvcp", "10", "100"]
        n = len(m.runner.calls)
        m.ctrl.set_manual(40)                                    # still runs, overlay only
        m.bus.publish("config.changed", {"brightness_backend": "ddc"})
        m.clock.advance(100)
        _drain(m)
        assert len(m.runner.calls) == n and _state(m)["active"] == "css"

    def test_switching_it_on_again_probes_afresh(self):
        m = _ddc()
        _drain(m)
        m.bus.publish("config.changed", {"module": "auto_brightness", "enabled": False})
        m.clock.advance(br.HW_RESTORE_DELAY_S)
        _drain(m)
        m.bus.publish("config.changed", {"module": "auto_brightness", "enabled": True})
        assert _state(m)["probe"] == "probing"
        _drain(m)
        assert _state(m)["active"] == "ddc" and len(m.runner.argvs("detect")) == 2

    def test_xrandr_gamma_is_restored_too(self):
        m = _make(_cfg(**XR))
        m.ctrl.tick()
        _drain(m)
        m.bus.publish("config.changed", {"module": "auto_brightness", "enabled": False})
        m.clock.advance(br.HW_RESTORE_DELAY_S)
        _drain(m)
        assert m.runner.argvs()[-1] == ["xrandr", "--output", "HDMI-1", "--brightness", "1.00"]

    def test_an_in_flight_probe_result_is_dropped(self):
        holder = {}

        def detect(argv):
            holder["m"].bus.publish("config.changed", {"module": "auto_brightness",
                                                       "enabled": False})
            return Res(0, DETECT_OK)

        m = _make(_cfg(backend="ddc"), runner=FakeRunner(detect=detect))
        holder["m"] = m
        m.ctrl.tick()
        _drain(m)
        assert _state(m)["active"] == "css" and m.runner.argvs("setvcp") == []

    def test_css_or_other_modules_change_nothing(self):
        m = _make(_cfg(backend="css"))
        m.ctrl.update_from_lux(0.0)
        before = dict(_state(m))
        m.bus.publish("config.changed", {"module": "auto_brightness", "enabled": False})
        m.bus.publish("config.changed", {"module": "weather", "enabled": False})
        m.bus.publish("config.changed", {"module": "auto_brightness", "enabled": "false"})
        assert _state(m) == before and m.ctrl.hw_step() is None and m.runner.calls == []

    def test_a_light_source_switched_off_counts_via_the_catalog(self, tmp_path):
        from pathlib import Path

        from src.core.config import BCMConfig
        root = Path(__file__).resolve().parent.parent
        cfg = BCMConfig(config_path=str(root / "config" / "bcm_config_test.yaml"),
                        platform_override="x86", local_path=tmp_path / "local.yaml", env={})
        for name in ("auto_brightness", "phone_sensors", "car_phone"):
            cfg.set(f"modules.{name}", True)
        cfg.set("modules.input", False)
        cfg.set("display.auto_brightness.backend", "ddc")
        bus = EventBus()
        runner = FakeRunner()
        ctrl = BrightnessController(cfg, bus, clock=FakeClock(), runner=runner,
                                    which=lambda p: "/usr/bin/" + p,
                                    i2c_glob=lambda p: ["/dev/i2c-4"])
        m = SimpleNamespace(ctrl=ctrl, bus=bus, runner=runner, clock=ctrl._clock)
        ctrl.tick()
        _drain(m)
        assert ctrl.state["active"] == "ddc"
        bus.publish("config.changed", {"module": "weather", "enabled": False, "also": []})
        assert ctrl.state["active"] == "ddc"                     # still starts next time
        cfg.set("modules.phone_sensors", False)                  # what /api/modules does
        bus.publish("config.changed", {"module": "phone_sensors", "enabled": False, "also": []})
        assert ctrl.state["active"] == "css"
        ctrl._clock.advance(br.HW_RESTORE_DELAY_S)
        _drain(m)
        assert runner.argvs("setvcp")[-1] == ["ddcutil", "setvcp", "10", "100"]


# ── xrandr ───────────────────────────────────────────────────────────────

XR = {"backend": "xrandr", "xrandr": {"output": "HDMI-1", "display": ":0",
                                      "xauthority": "/home/kiosk/.Xauthority"}}


class TestXrandr:
    @pytest.mark.parametrize("xr, ok", [
        ({"output": "HDMI-1"}, True),
        ({"output": "eDP-1", "display": ":1.0"}, True),
        ({"output": "DP-2", "xauthority": "/run/user/1000/gdm/Xauthority"}, True),
        ({"output": ""}, False),
        ({"output": "HDMI-1; reboot"}, False),
        ({"output": "$(id)"}, False),
        ({"output": "-display"}, False),
        ({"output": "HDMI-1", "display": "0"}, False),
        ({"output": "HDMI-1", "display": ":0; rm"}, False),
        ({"output": "HDMI-1", "xauthority": "relative/.Xauthority"}, False),
        ({"output": "HDMI-1", "xauthority": "/home/../etc/shadow"}, False),
        ({"output": "HDMI-1", "xauthority": "/home/a b"}, False),
    ])
    def test_config_validation(self, xr, ok):
        s = load_settings(_cfg(backend="xrandr", xrandr=xr))
        assert (xrandr_config_error(s) == "") is ok

    def test_level_is_clamped(self):
        assert [xrandr_level(p) for p in (0, 15, 20, 45, 100)] == [
            "0.20", "0.20", "0.20", "0.45", "1.00"]

    def test_argv_and_environment(self):
        m = _make(_cfg(**XR))
        m.ctrl.tick()
        _drain(m)
        (argv, kw), = m.runner.calls
        assert argv == ["xrandr", "--output", "HDMI-1", "--brightness", "0.70"]
        assert kw["env"]["DISPLAY"] == ":0" and kw["env"]["XAUTHORITY"] == "/home/kiosk/.Xauthority"
        assert kw["timeout"] == br.XRANDR_TIMEOUT_S
        assert _state(m)["active"] == "xrandr" and m.seen[TOPIC_DIM][-1]["level"] == 0.0

    def test_spacing_between_calls(self):
        m = _make(_cfg(**XR))
        m.ctrl.tick()
        _drain(m)
        m.ctrl.set_manual(50)
        assert m.ctrl.hw_step() == pytest.approx(br.XRANDR_MIN_INTERVAL_S)
        m.clock.advance(1.0)
        _drain(m)
        assert m.runner.argvs()[-1][-1] == "0.50"

    def test_bad_config_never_runs_it(self):
        m = _make(_cfg(backend="xrandr", xrandr={"output": "HDMI-1 $(reboot)"}))
        m.ctrl.tick()
        _drain(m)
        st = _state(m)
        assert (st["active"], st["probe"], st["reason"]) == ("css", "failed", "xrandr_config")
        assert m.runner.calls == []

    @pytest.mark.parametrize("res, reason", [(Res(1, "", "Can't open display"), "xrandr_failed"),
                                             (FileNotFoundError(), "no_xrandr")])
    def test_failure_falls_back_to_css(self, res, reason):
        m = _make(_cfg(**XR), runner=FakeRunner(xrandr=res))
        m.ctrl.tick()
        _drain(m)
        st = _state(m)
        assert (st["active"], st["reason"]) == ("css", reason)
        assert m.seen[TOPIC_DIM][-1]["level"] > 0


# ── the module ───────────────────────────────────────────────────────────

class TestModule:
    def test_entry_point_threads_and_shutdown(self, monkeypatch):
        def tripwire(*a, **kw):
            raise AssertionError("no tool may run with the css backend")

        monkeypatch.setattr(br, "_run", tripwire)
        bus = EventBus()
        ctrl = br.start_auto_brightness(_cfg(backend="css"), bus)
        try:
            assert br.get_brightness_controller() is ctrl
            names = {t.name for t in threading.enumerate()}
            assert {"brightness-tick", "brightness-hw"} <= names
            deadline = time.monotonic() + 5
            while bus.get_last(TOPIC_STATE) is None and time.monotonic() < deadline:
                time.sleep(0.01)
            state, _ts = bus.get_last(TOPIC_STATE)
            assert state["effective"] == "no_source" and state["active"] == "css"
        finally:
            bus.publish("power.shutting_down", True)
        for t in ctrl._threads:
            t.join(timeout=5)
            assert not t.is_alive()
        assert br.get_brightness_controller() is None

    def test_module_off_means_no_overlay_and_no_row(self):
        bus = EventBus()
        viewer = WebViewer(host="127.0.0.1", port=5099, event_bus=bus, config=None)
        data = viewer._get_dashboard_data()
        assert data["display_dim"] is None and data["auto_brightness"] is None

    def test_final_config_starts_it_bench_config_does_not(self):
        import main
        from pathlib import Path

        from src.core.config import BCMConfig
        root = Path(__file__).resolve().parent.parent
        for name, runs in (("bcm_config.yaml", True), ("bcm_config_test.yaml", False)):
            cfg = BCMConfig(config_path=str(root / "config" / name), platform_override="x86",
                            local_path=None, env={})
            states = main.plan_modules(cfg)
            assert states["auto_brightness"].runs is runs
            assert ("auto_brightness" in [n for n, _ in main.registry_to_start(states)]) is runs


# ── web_viewer: payload and the Settings switch ─────────────────────────

GOOD_STATE = {"mode": "auto", "effective": "auto", "source": "phone", "lux": 120.0, "adc": None,
              "pct": 47, "target_pct": 47, "manual_pct": 70, "hold_left_min": None,
              "min_pct": 15, "max_pct": 100, "backend": "ddc", "active": "css",
              "probe": "failed", "reason": "no_i2c", "boost_pct": 20}


class TestPayload:
    def test_state_passes_through(self):
        assert wv._auto_brightness_summary(dict(GOOD_STATE)) == GOOD_STATE

    def test_state_is_whitelisted(self):
        bad = {"mode": "<b>", "effective": "x", "source": "nfc", "lux": "1", "adc": 5000,
               "pct": 101, "target_pct": True, "manual_pct": -1, "hold_left_min": 0,
               "min_pct": "15", "max_pct": None, "backend": "sh -c", "active": "ddc;",
               "probe": "<img>", "reason": "rm -rf", "extra": "dropped"}
        out = wv._auto_brightness_summary(bad)
        assert out == {"mode": "auto", "effective": "no_source", "source": "", "lux": None,
                       "adc": None, "pct": None, "target_pct": None, "manual_pct": None,
                       "hold_left_min": None, "min_pct": None, "max_pct": None,
                       "backend": "auto", "active": "css", "probe": "idle", "reason": "",
                       "boost_pct": 0}
        assert wv._auto_brightness_summary({"lux": float("nan")})["lux"] is None
        assert wv._auto_brightness_summary(None) is None
        assert wv._auto_brightness_summary("auto") is None

    @pytest.mark.parametrize("value, expected", [
        ({"level": 0.5, "brightness_pct": 41}, {"level": 0.5, "brightness_pct": 41}),
        ({"level": 0, "brightness_pct": 100}, {"level": 0.0, "brightness_pct": 100}),
        ({"level": 0.9, "brightness_pct": True}, {"level": 0.9, "brightness_pct": None}),
        ({"level": 0.95}, None), ({"level": 1.0}, None), ({"level": -0.1}, None),
        ({"level": float("nan")}, None), ({"level": True}, None), ({"level": "0.5"}, None),
        ({}, None), (None, None), ("dim", None),
    ])
    def test_dim_payload(self, value, expected):
        assert wv._display_dim_summary(value) == expected

    def test_live_values_reach_the_payload(self):
        bus = EventBus()
        ctrl = BrightnessController(_cfg(), bus, clock=FakeClock(), runner=FakeRunner())
        ctrl.update_from_lux(0.0)
        viewer = WebViewer(host="127.0.0.1", port=5099, event_bus=bus, config=None)
        data = viewer._get_dashboard_data()
        assert data["display_dim"] == {"level": css_level(15, 0.85), "brightness_pct": 15}
        assert data["auto_brightness"]["pct"] == 15 and data["auto_brightness"]["source"] == "phone"


def _web(tmp_path):
    from pathlib import Path

    from src.core.config import BCMConfig
    root = Path(__file__).resolve().parent.parent
    cfg = BCMConfig(config_path=str(root / "config" / "bcm_config_test.yaml"),
                    platform_override="x86", local_path=tmp_path / "local.yaml", env={})
    saved = []
    cfg.save = lambda path=None: saved.append(True) or True
    bus = EventBus()
    viewer = WebViewer(host="127.0.0.1", port=5099, event_bus=bus, config=cfg)
    runner = FakeRunner()
    ctrl = BrightnessController(cfg, bus, clock=FakeClock(), runner=runner,
                                which=lambda p: "/usr/bin/" + p, i2c_glob=lambda p: ["/dev/i2c-4"])
    return SimpleNamespace(cfg=cfg, saved=saved, ctrl=ctrl, runner=runner,
                           client=viewer._build_app().test_client())


class TestConfigApi:
    def test_get_lists_the_brightness_keys(self, tmp_path):
        web = _web(tmp_path)
        body = web.client.get("/api/config").get_json()
        assert body["brightness_backend"] == "css" and body["brightness_mode"] == "auto"

    def test_switch_to_ddc_is_saved_and_applied_live(self, tmp_path):
        web = _web(tmp_path)
        res = web.client.post("/api/config", json={"brightness_backend": "ddc"})
        assert res.status_code == 200 and res.get_json()["persisted"] is True
        assert web.cfg.get("display.auto_brightness.backend") == "ddc" and web.saved
        assert web.ctrl.state["probe"] == "probing"            # no restart needed
        _drain(SimpleNamespace(ctrl=web.ctrl))
        assert web.ctrl.state["active"] == "ddc"
        assert web.runner.argvs()[0] == ["ddcutil", "detect", "--brief"]

    def test_mode_and_slider(self, tmp_path):
        web = _web(tmp_path)
        web.ctrl.update_from_lux(0.0)
        assert web.client.post("/api/config", json={"brightness": 60}).status_code == 200
        assert web.ctrl.brightness == 60 and web.ctrl.state["effective"] == "hold"
        assert web.client.post("/api/config", json={"brightness_mode": "manual"}).status_code == 200
        assert web.cfg.get("display.auto_brightness.mode") == "manual"
        assert web.ctrl.state["effective"] == "manual"

    def test_manual_saves_the_frozen_level_as_the_slider_value(self, tmp_path, monkeypatch):
        web = _web(tmp_path)
        monkeypatch.setattr(br, "_INSTANCE", web.ctrl)          # the running module
        web.ctrl.update_from_lux(3.0)                           # night, ~21 %
        night = web.ctrl.brightness
        assert night != web.cfg.get("display.dashboard.brightness")
        assert web.client.post("/api/config", json={"brightness_mode": "manual"}).status_code == 200
        assert web.cfg.get("display.dashboard.brightness") == night   # also after the next boot
        assert web.ctrl.brightness == night and web.ctrl.state["effective"] == "manual"
        # a slider value in the same request wins
        web.ctrl.set_mode("auto")
        res = web.client.post("/api/config", json={"brightness_mode": "manual", "brightness": 50})
        assert res.status_code == 200 and web.cfg.get("display.dashboard.brightness") == 50
        assert web.ctrl.brightness == 50

    def test_manual_without_the_module_saves_no_slider_value(self, tmp_path):
        web = _web(tmp_path)                                    # get_brightness_controller() is None
        before = web.cfg.get("display.dashboard.brightness")
        assert web.client.post("/api/config", json={"brightness_mode": "manual"}).status_code == 200
        assert web.cfg.get("display.dashboard.brightness") == before

    @pytest.mark.parametrize("body, key", [
        ({"brightness_backend": "xrandr"}, "brightness_backend"),
        ({"brightness_backend": "auto"}, "brightness_backend"),
        ({"brightness_backend": ["ddc"]}, "brightness_backend"),
        ({"brightness_backend": 1}, "brightness_backend"),
        ({"brightness_mode": "night"}, "brightness_mode"),
        ({"brightness_mode": True}, "brightness_mode"),
        ({"theme": "modern", "brightness_backend": "ddc; reboot"}, "brightness_backend"),
    ])
    def test_invalid_values_are_refused_all_or_nothing(self, tmp_path, body, key):
        web = _web(tmp_path)
        res = web.client.post("/api/config", json=body)
        assert res.status_code == 400 and res.get_json()["key"] == key
        assert web.cfg.get("display.auto_brightness.backend") == "css" and web.saved == []
        assert web.ctrl.state is None or web.ctrl.state["backend"] == "css"


class TestBoost:
    """Calibration offset: the phone under the headliner sees less light."""

    def test_boost_clamped_on_load(self):
        from src.power import brightness as br
        assert br.load_settings(_cfg(boost_pct=99)).boost_pp == br.BOOST_MAX
        assert br.load_settings(_cfg(boost_pct=-99)).boost_pp == br.BOOST_MIN
        assert br.load_settings(_cfg(boost_pct=20)).boost_pp == 20
        assert br.load_settings({}).boost_pp == 0

    def test_payload_boost_whitelisted(self):
        bad = dict(GOOD_STATE, boost_pct="<b>")
        assert wv._auto_brightness_summary(bad)["boost_pct"] == 0
