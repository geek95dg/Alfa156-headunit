"""Pro Micro v8.6: knob panel on A6, long PLAY → sleep, stalk → next screen.

* arduino/rotary_encoder/press_logic.h — host harness (g++), the same one
  ``make -C arduino rotary_encoder-test`` runs;
* the sketch — static checks (pins, keys, EEPROM layout) and a host
  ``g++ -fsyntax-only`` pass with tiny stand-ins for Arduino/HID-Project;
* BCM side — F13/F14 mapping, the sleep request (guards, debounce, argv,
  never inline) and the edge-triggered ``screen_next`` payload.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from src.core.event_bus import EventBus
from src.input import action_dispatch as ad
from src.input import input_bridge as ib

REPO = Path(__file__).resolve().parent.parent
SKETCH_DIR = REPO / "arduino" / "rotary_encoder"
SKETCH = SKETCH_DIR / "rotary_encoder.ino"
PRESS_TEST = SKETCH_DIR / "test" / "test_press_logic.cpp"


def _code(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


@pytest.fixture(scope="module")
def ino() -> str:
    return SKETCH.read_text(encoding="utf-8")


# ── firmware ───────────────────────────────────────────────────────────────

def test_press_logic_host_harness(tmp_path):
    gxx = shutil.which("g++")
    if not gxx:
        pytest.skip("g++ not available")
    exe = tmp_path / "t"
    build = subprocess.run([gxx, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-o", str(exe),
                            str(PRESS_TEST)], capture_output=True, text=True, timeout=120)
    assert build.returncode == 0, build.stderr
    run = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    assert "press_logic: OK" in run.stdout


def test_makefile_runs_the_harness():
    mk = (REPO / "arduino" / "Makefile").read_text(encoding="utf-8")
    assert re.search(r"^test: .*\brotary_encoder-test\b", mk, flags=re.M)
    assert "rotary_encoder/test/test_press_logic.cpp" in mk


class TestSketch:
    def test_panel_and_stalk_on_by_default(self, ino):
        code = _code(ino)
        assert re.search(r"^#define FEATURE_PANEL\b", code, flags=re.M)
        assert re.search(r"^#define FEATURE_STALK\b", code, flags=re.M)
        assert re.search(r"^#define FEATURE_SWC\b", code, flags=re.M)
        assert not re.search(r"^#define STALK_F9\b", code, flags=re.M)

    def test_panel_reads_a6_with_its_own_eeprom_block(self, ino):
        code = _code(ino)
        assert "#define SWC_PIN2  A6" in code
        assert re.search(r"panelPod = \{SWC_PIN2, PANEL_BUTTON_COUNT", code)
        # pod 1 keeps its v8.5.4 layout (1..20), the panel lives at 32..50
        assert "#define EEPROM_SWC_ADDR 1 " in code
        assert "#define EEPROM_PANEL_MAGIC_ADDR 32" in code
        assert "#define EEPROM_PANEL_ADDR 33" in code
        n = int(re.search(r"#define PANEL_BUTTON_COUNT (\d+)", code).group(1))
        assert 33 + 2 * n <= 64

    def test_panel_buttons_and_actions_match(self, ino):
        code = _code(ino)
        names = re.search(r"PANEL_NAMES\[PANEL_BUTTON_COUNT\] = \{(.*?)\};", code, re.S).group(1)
        acts = re.search(r"PANEL_ACTIONS\[PANEL_BUTTON_COUNT\] = \{(.*?)\};", code, re.S).group(1)
        names = re.findall(r'"([^"]+)"', names)
        acts = re.findall(r"ACT_\w+", acts)
        assert names == ["VOL+", "VOL-", "PLAY", "NEXT", "PREV", "MUTE", "PICKUP", "HANGUP",
                         "VOICE"]
        assert [a.replace("ACT_", "") for a in acts] == [
            "VOLUP", "VOLDN", "PLAY", "NEXT", "PREV", "MUTE", "PICKUP", "HANGUP", "VOICE"]

    def test_uncalibrated_panel_never_matches(self, ino):
        code = _code(ino)
        vals = re.search(r"panelValues\[PANEL_BUTTON_COUNT\] = \{(.*?)\};", code, re.S).group(1)
        assert set(re.findall(r"\w+", vals)) == {"ADC_UNSET"}
        assert "if (p.values[i] == ADC_UNSET) continue;" in code

    def test_long_play_sends_f13_and_stalk_f14(self, ino):
        code = _code(ino)
        assert "#define PLAY_LONG_MS 2000" in code
        assert re.search(r"ev == PRESS_LONG\)\s*\{.*?tapKey\(KEY_F13\)", code, re.S)
        assert "Keyboard.press(KEY_F14)" in code
        # F10 (old power toggle) is not sent by anything any more
        assert "KEY_F10" not in code

    def test_serial_commands(self, ino):
        code = _code(ino)
        for cmd in ("CAL", "CAL2", "ADC2"):
            assert f'equalsIgnoreCase("{cmd}")' in code


_STUBS = {
    "Arduino.h": """
#pragma once
#include <stdint.h>
#include <stdlib.h>
class __FlashStringHelper;
#define F(s) (reinterpret_cast<const __FlashStringHelper*>(s))
enum { LOW = 0, HIGH = 1, INPUT = 0, OUTPUT = 1, INPUT_PULLUP = 2, CHANGE = 1 };
enum { A0 = 18, A1, A2, A3, A4, A5, A6 = 24 };
struct String { void trim() {} bool equalsIgnoreCase(const char*) const { return false; } };
struct SerialStub {
  void begin(long) {} void setTimeout(long) {}
  int available() { return 0; }
  String readStringUntil(char) { return String(); }
  template <class T> void print(T) {}
  template <class T> void println(T) {}
  void println() {}
};
extern SerialStub Serial;
void pinMode(uint8_t, uint8_t); int digitalRead(uint8_t); int analogRead(uint8_t);
void delayMicroseconds(unsigned int); void delay(unsigned long); unsigned long millis();
int digitalPinToInterrupt(int); void attachInterrupt(int, void(*)(), int);
""",
    "avr/wdt.h": "#pragma once\n#define WDTO_2S 7\nvoid wdt_disable(); void wdt_enable(int); void wdt_reset();\n",
    "HID-Project.h": """
#pragma once
#include <stdint.h>
enum KeyboardKeycode : uint8_t { KEY_HOME, KEY_F5, KEY_F6, KEY_F7, KEY_F8, KEY_F9, KEY_F13,
  KEY_F14, KEY_RETURN, KEY_BACKSPACE, KEY_UP_ARROW, KEY_DOWN_ARROW };
enum ConsumerKeycode : uint16_t { MEDIA_VOLUME_UP, MEDIA_VOLUME_DOWN, MEDIA_VOLUME_MUTE,
  MEDIA_NEXT, MEDIA_PREVIOUS, MEDIA_PLAY_PAUSE };
struct KB { void begin() {} void press(KeyboardKeycode) {} void release(KeyboardKeycode) {} };
struct CS { void begin() {} void write(ConsumerKeycode) {} };
extern KB Keyboard; extern CS Consumer;
""",
    "EEPROM.h": "#pragma once\n#include <stdint.h>\n"
                "struct EE { uint8_t read(int) { return 0; } void write(int, uint8_t) {} };\n"
                "extern EE EEPROM;\n",
}


@pytest.mark.parametrize("defines", [(), ("-DSTALK_F9",),
                                     ("-DFEATURE_ENCODER", "-DFEATURE_BUTTONS",
                                      "-DFEATURE_MUSIC", "-DFEATURE_LIGHT")])
def test_sketch_host_syntax(tmp_path, defines):
    gxx = shutil.which("g++")
    if not gxx:
        pytest.skip("g++ not available")
    for name, body in _STUBS.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    src = tmp_path / "rotary_encoder.cpp"
    src.write_text("#include <Arduino.h>\n" + SKETCH.read_text(encoding="utf-8"),
                   encoding="utf-8")
    res = subprocess.run([gxx, "-std=gnu++11", "-Wall", "-fsyntax-only", f"-I{tmp_path}",
                          f"-I{SKETCH_DIR}", *defines, str(src)],
                         capture_output=True, text=True, timeout=120)
    assert res.returncode == 0, res.stderr


# ── BCM side ───────────────────────────────────────────────────────────────

def test_f13_f14_mapping():
    assert ad.KEYCODE_MAP[183] == "input.system_sleep"
    assert ad.KEYCODE_MAP[184] == "input.screen_next"
    assert ad.KEYBOARD_MAP["f13"] == 183 and ad.KEYBOARD_MAP["f14"] == 184


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class Runner:
    def __init__(self, rc=0):
        self.calls = []
        self.rc = rc

    def __call__(self, argv, **kw):
        self.calls.append(argv)
        return type("R", (), {"returncode": self.rc, "stderr": ""})()


@pytest.fixture
def bridge(monkeypatch):
    bus = EventBus()
    runner = Runner()
    clock = FakeClock()
    br = ib.InputBridge(bus, None, runner=runner, clock=clock)
    monkeypatch.setattr(ib.os.path, "isfile", lambda p: p == ib.SLEEP_SCRIPT)
    monkeypatch.setattr(ib.shutil, "which", lambda n: "/usr/bin/" + n)

    class Sync:   # run the worker inline
        def __init__(self, target, name=None, daemon=None):
            self._t = target

        def start(self):
            self._t()
    monkeypatch.setattr(ib.threading, "Thread", Sync)
    return bus, br, runner, clock


def test_long_play_runs_the_power_script_outside_the_service(bridge):
    bus, br, runner, clock = bridge
    bus.publish("input.system_sleep", True)
    assert runner.calls == [["systemd-run", "--no-block", "--collect", "--quiet",
                             "--unit", "bcm-sleep-request", ib.SLEEP_SCRIPT]]


def test_debounced(bridge):
    bus, br, runner, clock = bridge
    bus.publish("input.system_sleep", True)
    bus.publish("input.system_sleep", True)          # browser + evdev
    clock.t += 10
    bus.publish("input.system_sleep", True)
    assert len(runner.calls) == 1
    clock.t += ib.SLEEP_DEBOUNCE_S
    bus.publish("input.system_sleep", True)
    assert len(runner.calls) == 2


@pytest.mark.parametrize("topic, value", [
    ("bt.call_state", "active"),
    ("bt.call_state", "incoming"),
    ("crash.sms_state", {"state": "pending"}),
    ("crash.call112_state", {"state": "active", "started_ts": 5.0}),
])
def test_never_during_a_call_or_crash_window(bridge, topic, value):
    bus, br, runner, clock = bridge
    bus.publish(topic, value)
    bus.publish("input.system_sleep", True)
    assert runner.calls == []


def test_idle_call_state_allows(bridge):
    bus, br, runner, clock = bridge
    bus.publish("bt.call_state", "idle")
    bus.publish("input.system_sleep", True)
    assert len(runner.calls) == 1


def test_missing_script_does_nothing(bridge, monkeypatch):
    bus, br, runner, clock = bridge
    monkeypatch.setattr(ib.os.path, "isfile", lambda p: False)
    bus.publish("input.system_sleep", True)
    assert runner.calls == []


def test_false_is_ignored(bridge):
    bus, br, runner, clock = bridge
    bus.publish("input.system_sleep", False)
    assert runner.calls == []


def test_screen_next_is_edge_triggered_in_the_payload():
    src = (REPO / "src" / "dashboard" / "web_viewer.py").read_text(encoding="utf-8")
    assert '"screen_next": _val("input.screen_next", False)' in src
    assert '"input.screen_next")' in src
    js = (REPO / "src" / "dashboard" / "web" / "js" / "app.js").read_text(encoding="utf-8")
    assert re.search(r'subscribe\("screen_next".*?navCycleNext\(\)', js, re.S)
