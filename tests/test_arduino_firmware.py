"""Static checks for the sensor_hub firmware and its build plumbing.

There is no arduino-cli in the test environment (the CI ``arduino`` job
compiles for real), so these tests pin the text: the optional variants are
built by ``make -C arduino sensor_hub-variants`` and CI calls it, the sketch
keeps its pin-conflict guards, and the switches stay commented out so a
``-DFEATURE_…`` flag (``SENSOR_HUB_FEATURES=…`` for a normal build/upload) is
the only thing turning them on.

A host-side ``g++ -fsyntax-only`` pass over the sketch with tiny stand-ins for
the Arduino headers additionally catches typos in the ``#ifdef`` blocks and
checks that the ``#error`` guards fire. It is a smoke test, not a substitute
for the AVR build (skipped when g++ is missing).

The power-button decisions live in ``sensor_hub/power_logic.h`` (plain C++);
``test_power_logic.cpp`` drives them on a simulated M910q, across the
``millis()`` wrap (~49.7 days — the Nano runs 24/7 from the buffer) and is run
here too, so CI's pytest job executes it (skipped without g++). Static checks
make sure no deadline is compared as ``now < deadline`` again.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
ARDUINO = REPO / "arduino"
SKETCH = ARDUINO / "sensor_hub" / "sensor_hub.ino"
POWER_LOGIC = ARDUINO / "sensor_hub" / "power_logic.h"
POWER_TEST = ARDUINO / "sensor_hub" / "test" / "test_power_logic.cpp"
MAKEFILE = ARDUINO / "Makefile"
CI = REPO / ".github" / "workflows" / "ci.yml"
UDEV = REPO / "config" / "udev" / "99-bcm-sensor-hub.rules"


@pytest.fixture(scope="module")
def ino() -> str:
    return SKETCH.read_text(encoding="utf-8")


def _code(text: str) -> str:
    """The sketch without // and /* */ comments (string literals have no
    comment markers in this sketch)."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


# ── Makefile / CI ──────────────────────────────────────────────────────────


class TestBuildPlumbing:
    def test_makefile_has_variants_target(self):
        mk = MAKEFILE.read_text(encoding="utf-8")
        assert re.search(r"^sensor_hub-variants:", mk, flags=re.M)
        assert re.search(r"^SENSOR_HUB_VARIANTS \?=.*\bBATT_ADC\b.*\bBATT_INA226\b", mk, flags=re.M)
        body = mk.split("sensor_hub-variants:", 2)[-1].split("\n\n", 1)[0]
        assert "compiler.cpp.extra_flags=-DFEATURE_$$v" in body
        assert "--build-path" in body and "sensor_hub-$$v" in body   # one dir per variant
        assert "--profile default" in body
        assert "|| exit 1" in body                                  # a failing variant fails make
        phony = re.search(r"^\.PHONY:(.*?)(?<!\\)\n", mk, flags=re.M | re.S).group(1)
        assert "sensor_hub-variants" in phony

    def test_clean_removes_variant_builds(self):
        mk = MAKEFILE.read_text(encoding="utf-8")
        clean = mk.split("\nclean:", 1)[1]
        assert "$(VARIANTS_BUILD_DIR)" in clean

    def test_variant_build_dirs_are_git_ignored(self):
        # arduino/build/… — covered by the unanchored "build/" rule.
        mk = MAKEFILE.read_text(encoding="utf-8")
        assert re.search(r"^VARIANTS_BUILD_DIR := \$\(CURDIR\)/build$", mk, flags=re.M)
        assert re.search(r"^build/$", (REPO / ".gitignore").read_text(), flags=re.M)

    def test_features_variable_defaults_to_empty(self):
        # Empty by default: `make` / `make sensor_hub` build the sketch as
        # committed, exactly like before.
        mk = MAKEFILE.read_text(encoding="utf-8")
        assert re.search(r"^SENSOR_HUB_FEATURES \?=\s*$", mk, flags=re.M)

    def test_upload_rule_works_for_phony_targets(self):
        # make never searches pattern rules for .PHONY targets, so a plain
        # "%-upload: %" made every *-upload a silent no-op.
        mk = MAKEFILE.read_text(encoding="utf-8")
        assert re.search(r"^\$\(addsuffix -upload,\$\(SKETCHES\)\): %-upload: %$", mk, flags=re.M)
        assert not re.search(r"^%-upload:", mk, flags=re.M)

    def test_host_test_target(self):
        mk = MAKEFILE.read_text(encoding="utf-8")
        assert re.search(r"^sensor_hub-test:", mk, flags=re.M)
        assert re.search(r"^test: .*\bsensor_hub-test\b", mk, flags=re.M)
        body = mk.split("\nsensor_hub-test:", 1)[1].split("\n\n", 1)[0]
        assert "sensor_hub/test/test_power_logic.cpp" in body
        assert "$(HOST_CXXFLAGS)" in body                          # -Werror like esp32

    def test_ci_compiles_the_variants(self):
        ci = CI.read_text(encoding="utf-8")
        arduino_job = ci.split("\n  arduino:", 1)[1]
        runs = re.findall(r"run:\s*(.+)", arduino_job)
        assert "make -C arduino" in runs
        assert "make -C arduino sensor_hub-variants" in runs


# ── sketch text ────────────────────────────────────────────────────────────


class TestSketch:
    def test_switches_are_off_by_default(self, ino):
        code = _code(ino)
        assert not re.search(r"#\s*define\s+FEATURE_BATT_", code)
        assert "#undef" not in code          # a -D flag must not be cancelled
        assert re.search(r"^// #define FEATURE_BATT_ADC\b", ino, flags=re.M)
        assert re.search(r"^// #define FEATURE_BATT_INA226\b", ino, flags=re.M)

    def test_conflict_guards(self, ino):
        assert re.search(r"#if defined\(FEATURE_BATT_INA226\) && \(defined\(FEATURE_CRUISE\) "
                         r"\|\| defined\(FEATURE_IMMO\)\)\n#error", ino)
        assert re.search(r"#if defined\(FEATURE_BATT_INA226\) && defined\(FEATURE_BATT_ADC\)\n#error", ino)

    def test_batt_blocks_and_hooks(self, ino):
        assert "#ifdef FEATURE_BATT_ADC" in ino and "#ifdef FEATURE_BATT_INA226" in ino
        assert re.search(r"#ifdef FEATURE_BATT_INA226\n#include <Wire.h>\n#endif", ino)
        setup = ino.split("void setup() {", 1)[1].split("\n}\n", 1)[0]
        # battInit before the banner, and both before the watchdog starts.
        assert setup.index("battInit();") < setup.index('"BCM v8.5 Sensor Hub ready"') \
            < setup.index("wdt_enable(")

    def test_batt_report_rides_on_the_full_state(self, ino):
        full = ino.split("void reportFullState() {", 1)[1].split("\n}\n", 1)[0]
        # Last thing in the full-state report, right after the PWR: block.
        assert re.search(r"PWR_NAMES\[pwr\.state\]\);\n#endif\n#if defined\(FEATURE_BATT_ADC\) "
                         r"\|\| defined\(FEATURE_BATT_INA226\)\n  battReport\(\);\n#endif$", full)
        # …and NOT in the power-state setter, which prints PWR: on change only.
        setter = ino.split("void pwrReportState() {", 1)[1].split("\n}\n", 1)[0]
        assert "battReport" not in setter

    def test_protocol_line_documented(self, ino):
        header = ino.split("*/", 1)[0]
        assert "BATT:12650,-3400" in header

    def test_ina226_details(self, ino):
        assert "INA_CONFIG_VALUE  0x4527" in ino
        assert "Wire.setWireTimeout(" in ino
        # The two bytes are read in separate statements (operand order of
        # "read() << 8 | read()" is unspecified in C++).
        assert not re.search(r"Wire\.read\(\)[^;\n]*Wire\.read\(\)", _code(ino))

    def test_divider_alternative_documented(self, ino):
        assert "10k/2,2k" in ino and "R1_K=100, R2_K=22" in ino

    def test_wire_timeout_needs_avr_core_183(self):
        # Wire.setWireTimeout appeared in arduino:avr 1.8.3.
        y = (ARDUINO / "sensor_hub" / "sketch.yaml").read_text(encoding="utf-8")
        m = re.search(r"platform: arduino:avr \((\d+)\.(\d+)\.(\d+)\)", y)
        assert m and tuple(map(int, m.groups())) >= (1, 8, 3)


# ── power button (FEATURE_PWRBTN) ──────────────────────────────────────────


@pytest.fixture(scope="module")
def logic() -> str:
    return POWER_LOGIC.read_text(encoding="utf-8")


class TestPowerButton:
    # "now < deadline" / "deadline > now" — wrong once millis() wraps: the old
    # deadline stays huge while now restarts from 0 (bug: "now < pwrSettleUntil"
    # froze power control for weeks after ~49.7 days of uptime).
    _DEADLINE_CMP = re.compile(r"\bnow\s*<(?!<)\s*[A-Za-z_][\w.]*|[A-Za-z_][\w.]*\s*>(?!>)\s*now\b")

    def test_no_absolute_time_comparisons(self, ino, logic):
        for name, text in (("sensor_hub.ino", ino), ("power_logic.h", logic)):
            bad = [m.group(0) for m in self._DEADLINE_CMP.finditer(_code(text))]
            assert bad == [], f"{name}: {bad}"
        assert "pwrSettleUntil" not in ino

    def test_settle_deadline_is_rollover_safe(self, logic):
        code = _code(logic)
        assert "if ((int32_t)(now - s.settleUntil) < 0) return PWR_ACT_NONE;" in code
        # The signed difference only works for deadlines < 2^31 ms (~24.8 days)
        # away, so the deadline is dropped once it has passed.
        settle = code.split("if (s.settling) {", 1)[1].split("}", 1)[0]
        assert "s.settling = false;" in settle
        # 32-bit time on the host too, or the wrap tests would test nothing.
        assert "unsigned long" not in code

    def test_pulse_end_uses_a_flag_not_zero(self, ino):
        code = _code(ino)
        assert "if ((long)(now - pwrPulseUntil) >= 0) {" in code
        assert "bool          pwrPulsing" in code
        assert not re.search(r"if\s*\(\s*pwrPulseUntil\s*\)", code)

    def test_long_only_from_sleep(self, logic):
        code = _code(logic)
        assert code.count("return PWR_ACT_LONG;") == 1
        escalation = code.split("switch (s.state) {", 1)[1]
        sleep_case = escalation.split("case PWR_SLEEP:", 1)[1].split("case ", 1)[0]
        assert "return PWR_ACT_LONG;" in sleep_case
        running_case = escalation.split("case PWR_RUNNING:", 1)[1].split("default:", 1)[0]
        assert "return pwrShort(s, now, PWR_SLEEP);" in running_case
        assert "LONG" not in running_case
        # …and only from a state that has really HELD, never inside the
        # host's suspend window.
        before = code.split("switch (s.state) {", 1)[0].rsplit("if (!s.ignLevel && s.escDue", 1)[1]
        assert "if (!steady) return PWR_ACT_NONE;" in before
        assert "if (s.grace) return PWR_ACT_NONE;" in before

    def test_steady_means_held_not_just_equal(self, logic):
        # Review finding: "stable == state" alone passes every flicker window
        # that happens to read the old stable value (S3 woken every hour).
        steady = _code(logic).split("inline bool pwrSteady(", 1)[1].split("\n}\n", 1)[0]
        assert "s.state == s.stable" in steady
        assert "(uint32_t)(now - s.stateSince) >= PWR_STABLE_MS" in steady
        assert "s.state != PWR_UNKNOWN" in steady

    def test_suspend_grace_covers_the_host_stop_timeout(self, logic):
        # bcm-power-toggle.sh stops bcm-headunit (TimeoutStopSec) before it
        # suspends; the window in which no second SHORT is sent must be longer.
        grace = int(re.search(r"#define PWR_SUSPEND_GRACE_MS\s+(\d+)UL", logic).group(1))
        unit = (REPO / "config" / "systemd" / "bcm-headunit-x86.service").read_text(encoding="utf-8")
        stop_s = int(re.search(r"^TimeoutStopSec=(\d+)$", unit, flags=re.M).group(1))
        assert grace >= (stop_s + 30) * 1000
        script = (REPO / "config" / "scripts" / "bcm-power-toggle.sh").read_text(encoding="utf-8")
        assert "systemctl stop bcm-headunit.service" in script

    def test_external_wake_rearms_escalation(self, logic):
        code = _code(logic)
        assert re.search(r"s\.stable == PWR_RUNNING && prev != PWR_RUNNING && s\.ignKnown && "
                         r"!s\.ignLevel\) \{\s*pwrArmEscalation\(s, now\);", code)
        arm = code.split("inline void pwrArmEscalation(", 1)[1].split("\n}\n", 1)[0]
        assert "s.offDone = false;" in arm and "s.ignOffAt = now;" in arm

    def test_sketch_uses_the_logic(self, ino):
        assert re.search(r'#ifdef FEATURE_PWRBTN\n#include "power_logic.h"\n#endif', ino)
        # LED decoding lives in the header too (host-tested), not in the sketch.
        observe = ino.split("void pwrObserveLed(unsigned long now) {", 1)[1].split("\n}\n", 1)[0]
        assert "if (pwrLedSample(pwrLed, lit, now)) pwrObserve(pwr, pwrLed.decoded, now);" in observe
        assert "pwrLedEdges" not in ino and "PWR_LED_WINDOW_MS     1600UL" not in ino
        assert "pwrLedInit(pwrLed, millis());" in ino
        handler = ino.split("void handlePwrButton(unsigned long now) {", 1)[1].split("\n}\n", 1)[0]
        assert "pwrStep(pwr, now, inIgn.state)" in handler
        assert "pwrPulseDone(pwr, now);" in handler
        setup = ino.split("void setup() {", 1)[1].split("\n}\n", 1)[0]
        assert "pwrInit(pwr, PWR_CLOSED_LOOP, millis());" in setup


def test_udev_template_is_inert_until_filled():
    text = UDEV.read_text(encoding="utf-8")
    rules = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    assert len(rules) == 1
    rule = rules[0]
    for part in ('SUBSYSTEM=="tty"', 'ATTRS{idVendor}=="1a86"', 'ATTRS{idProduct}=="7523"',
                 'SYMLINK+="ttyBCM_SENSOR"', 'GROUP="dialout"', 'MODE="0660"'):
        assert part in rule
    m = re.search(r'ENV\{ID_PATH\}=="([^"]*)"', rule)
    assert m and m.group(1).startswith("UZUPELNIJ")   # never matches a real path
    assert "udevadm info -q property -n /dev/ttyUSB" in text


# ── host syntax smoke test ─────────────────────────────────────────────────

_STUBS = {
    "Arduino.h": """
#pragma once
#include <stdint.h>
#include <stddef.h>
class __FlashStringHelper;
#define F(s) (reinterpret_cast<const __FlashStringHelper*>(s))
enum { LOW = 0, HIGH = 1, INPUT = 0, OUTPUT = 1, INPUT_PULLUP = 2 };
enum { A0 = 14, A1, A2, A3, A4, A5, A6, A7 };
struct SerialStub {
  void begin(long) {}
  template <class T> void print(T) {}
  template <class T> void println(T) {}
  void print(float, int) {}
  void println(float, int) {}
  void println() {}
};
extern SerialStub Serial;
void pinMode(uint8_t, uint8_t);
void digitalWrite(uint8_t, uint8_t);
int digitalRead(uint8_t);
int analogRead(uint8_t);
void delayMicroseconds(unsigned int);
void delay(unsigned long);
unsigned long millis();
unsigned long pulseIn(uint8_t, uint8_t, unsigned long);
""",
    "avr/wdt.h": """
#pragma once
#define WDTO_2S 7
void wdt_disable(); void wdt_enable(int); void wdt_reset();
""",
    "Wire.h": """
#pragma once
#include <stdint.h>
#include <stddef.h>
struct TwoWire {
  void begin() {}
  void setWireTimeout(uint32_t, bool) {}
  void beginTransmission(uint8_t) {}
  size_t write(uint8_t) { return 1; }
  uint8_t endTransmission(bool = true) { return 0; }
  uint8_t requestFrom(uint8_t, uint8_t) { return 2; }
  int read() { return 0; }
};
extern TwoWire Wire;
""",
    "OneWire.h": "#pragma once\nstruct OneWire { OneWire(int) {} };\n",
    "DallasTemperature.h": """
#pragma once
struct OneWire;
struct DallasTemperature {
  DallasTemperature(OneWire*) {}
  void begin() {}
  void setWaitForConversion(bool) {}
  void requestTemperatures() {}
  float getTempCByIndex(int) { return 0; }
};
""",
}


@pytest.fixture(scope="module")
def host_tree(tmp_path_factory):
    gxx = shutil.which("g++")
    if not gxx:
        pytest.skip("g++ not available")
    root = tmp_path_factory.mktemp("sensor_hub_host")
    for name, body in _STUBS.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    # arduino-cli prepends Arduino.h to the .ino the same way.
    src = root / "sensor_hub.cpp"
    src.write_text("#include <Arduino.h>\n" + SKETCH.read_text(encoding="utf-8"),
                   encoding="utf-8")
    return gxx, root, src


def _syntax(host_tree, *defines):
    gxx, root, src = host_tree
    # -I sketch dir: the copied .ino includes "power_logic.h" next to it.
    return subprocess.run(
        [gxx, "-std=gnu++11", "-fsyntax-only", f"-I{root}", f"-I{SKETCH.parent}",
         *defines, str(src)],
        capture_output=True, text=True, timeout=60)


@pytest.mark.parametrize("defines", [(), ("-DFEATURE_BATT_ADC",), ("-DFEATURE_BATT_INA226",)])
def test_host_syntax_of_each_variant(host_tree, defines):
    res = _syntax(host_tree, *defines)
    assert res.returncode == 0, res.stderr


@pytest.mark.parametrize("defines, message", [
    (("-DFEATURE_BATT_ADC", "-DFEATURE_BATT_INA226"), "Wybierz jedno zrodlo"),
    (("-DFEATURE_BATT_INA226", "-DFEATURE_CRUISE"), "FEATURE_BATT_INA226 uzywa A4/A5"),
    (("-DFEATURE_BATT_INA226", "-DFEATURE_IMMO"), "FEATURE_BATT_INA226 uzywa A4/A5"),
])
def test_host_guards_fire(host_tree, defines, message):
    res = _syntax(host_tree, *defines)
    assert res.returncode != 0
    assert message in res.stderr


# ── power_logic.h on the host ──────────────────────────────────────────────


def test_power_logic_host_harness(tmp_path):
    """make -C arduino sensor_hub-test, run from pytest so CI executes it."""
    gxx = shutil.which("g++")
    if not gxx:
        pytest.skip("g++ not available")
    exe = tmp_path / "test_power_logic"
    build = subprocess.run(
        [gxx, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-o", str(exe), str(POWER_TEST)],
        capture_output=True, text=True, timeout=120)
    assert build.returncode == 0, build.stderr
    run = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    assert "sensor_hub power_logic: OK" in run.stdout


def test_power_logic_compiles_as_gnu11(tmp_path):
    """The AVR core builds with -std=gnu++11; the header must not need more."""
    gxx = shutil.which("g++")
    if not gxx:
        pytest.skip("g++ not available")
    src = tmp_path / "t.cpp"
    src.write_text('#include "power_logic.h"\nint main() { PwrLogic s; pwrInit(s, true, 0); '
                   'PwrLed d; pwrLedInit(d, 0); if (pwrLedSample(d, true, 0)) '
                   'pwrObserve(s, d.decoded, 0); return pwrStep(s, 0, false); }\n',
                   encoding="utf-8")
    res = subprocess.run(
        [gxx, "-std=gnu++11", "-Wall", "-Wextra", "-Werror", "-fsyntax-only",
         f"-I{POWER_LOGIC.parent}", str(src)],
        capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stderr


# ── SENSOR_HUB_FEATURES through make (dry run, nothing is compiled) ────────


def _make_dry(*args):
    make = shutil.which("make")
    if not make:
        pytest.skip("make not available")
    return subprocess.run([make, "-n", "-C", str(ARDUINO), "ARDUINO_CLI=arduino-cli", *args],
                          capture_output=True, text=True, timeout=60)


def test_make_sensor_hub_without_features_is_unchanged():
    res = _make_dry("sensor_hub")
    assert res.returncode == 0, res.stderr
    assert "arduino-cli compile --profile default --warnings default" in res.stdout
    assert "--build-property" not in res.stdout


def test_make_sensor_hub_with_features():
    res = _make_dry("sensor_hub", "SENSOR_HUB_FEATURES=BATT_ADC")
    assert res.returncode == 0, res.stderr
    assert '--build-property "compiler.cpp.extra_flags=-DFEATURE_BATT_ADC"' in res.stdout


def test_make_upload_compiles_with_the_same_features():
    res = _make_dry("sensor_hub-upload", "PORT=/dev/ttyUSB0",
                    "SENSOR_HUB_FEATURES=BATT_INA226 AIRBAG")
    assert res.returncode == 0, res.stderr
    out = res.stdout
    compile_at = out.index('"compiler.cpp.extra_flags=-DFEATURE_BATT_INA226 -DFEATURE_AIRBAG"')
    upload_at = out.index("arduino-cli upload --profile default -p /dev/ttyUSB0")
    assert compile_at < upload_at


@pytest.mark.parametrize("bad", ["BAT_ADC", "FEATURE_BATT_ADC", "batt_adc", "DOORS"])
def test_make_rejects_unknown_features(bad):
    # A typo would otherwise build firmware WITHOUT the feature, silently.
    res = _make_dry("sensor_hub", f"SENSOR_HUB_FEATURES={bad}")
    assert res.returncode != 0
    assert "SENSOR_HUB_FEATURES: nieznane" in res.stderr
