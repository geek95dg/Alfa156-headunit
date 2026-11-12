"""Static checks for the sensor_hub BATT: firmware and its build plumbing.

There is no arduino-cli in the test environment (the CI ``arduino`` job
compiles for real), so these tests pin the text: the optional variants are
built by ``make -C arduino sensor_hub-variants`` and CI calls it, the sketch
keeps its pin-conflict guards, and the switches stay commented out so a
``-DFEATURE_…`` flag is the only thing turning them on.

A host-side ``g++ -fsyntax-only`` pass over the sketch with tiny stand-ins for
the Arduino headers additionally catches typos in the ``#ifdef`` blocks and
checks that the ``#error`` guards fire. It is a smoke test, not a substitute
for the AVR build (skipped when g++ is missing).
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
ARDUINO = REPO / "arduino"
SKETCH = ARDUINO / "sensor_hub" / "sensor_hub.ino"
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
        assert re.search(r"PWR_NAMES\[pwrState\]\);\n#endif\n#if defined\(FEATURE_BATT_ADC\) "
                         r"\|\| defined\(FEATURE_BATT_INA226\)\n  battReport\(\);\n#endif$", full)
        # …and NOT in the power-state setter, which prints PWR: on change only.
        setter = ino.split("void pwrSetState(PwrState s) {", 1)[1].split("\n}\n", 1)[0]
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
    return subprocess.run(
        [gxx, "-std=gnu++11", "-fsyntax-only", f"-I{root}", *defines, str(src)],
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
