"""Frontend gesture logic, run in plain node (skipped without node).

* the pure classifier in web/js/components/gestures.js — edge zones,
  pull / navbar / pass decisions and the finish rules — as a table;
* the AA edge state machine (createEdgeTracker) on scripted touches;
* smoke harnesses that load app.js+appbar.js and screens/android_auto.js in
  a node vm with DOM stubs (tests/js/*.js, plain node + assert);
* call_nav_smoke.js: app.js + screens/phone.js — an incoming call switches to
  A8 from any screen (not A2), Phone state never goes stale, caller text is
  escaped, and the kiosk returns to the previous screen when the call ends.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "tests" / "js"


def _node():
    found = shutil.which("node")
    if found:
        return found
    for candidate in ("/opt/node22/bin/node", "/usr/local/bin/node"):
        if os.access(candidate, os.X_OK):
            return candidate
    return None


NODE = _node()
pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")


def _eval(calls=(), scripts=()):
    res = subprocess.run(
        [NODE, str(JS / "gestures_eval.js")],
        input=json.dumps({"calls": list(calls), "scripts": list(scripts)}),
        capture_output=True, text=True, timeout=60,
    )
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


H = 600  # screen height used in the tables

# (function, args, expected)
TABLE = [
    # edge zones (40 px)
    ("edgeZone", [0, H], "top"),
    ("edgeZone", [40, H], "top"),
    ("edgeZone", [41, H], None),
    ("edgeZone", [300, H], None),
    ("edgeZone", [559, H], None),
    ("edgeZone", [560, H], "bottom"),
    ("edgeZone", [600, H], "bottom"),
    ("edgeZone", [10, 0], None),
    ("edgeZone", [None, H], None),
    # classify: within the 10 px slop nothing is decided
    ("classify", ["top", 0, 0], "pending"),
    ("classify", ["top", 5, 5], "pending"),
    ("classify", ["bottom", 0, -9], "pending"),
    # top zone: down and mostly vertical → pull
    ("classify", ["top", 0, 10], "pull"),
    ("classify", ["top", 20, 40], "pull"),
    ("classify", ["top", 21, 40], "pass"),     # |dx| > dy/2
    ("classify", ["top", -20, 40], "pull"),
    ("classify", ["top", 30, 0], "pass"),      # horizontal → AA
    ("classify", ["top", 0, -20], "pass"),     # upward from the top
    # bottom zone: up and more vertical than horizontal → navbar
    ("classify", ["bottom", 0, -10], "navbar"),
    ("classify", ["bottom", 10, -20], "navbar"),
    ("classify", ["bottom", 20, -20], "pass"),
    ("classify", ["bottom", 30, 0], "pass"),
    ("classify", ["bottom", 0, 20], "pass"),
    # no zone → never ours
    ("classify", [None, 0, 50], "pass"),
    ("classify", [None, 0, -50], "pass"),
    ("classify", ["top", None, 50], "pass"),
    # pull finish rule: dy >= 80, |dx| <= dy/2, <= 800 ms
    ("pullDone", [0, 80, 800], True),
    ("pullDone", [40, 80, 100], True),
    ("pullDone", [41, 80, 100], False),
    ("pullDone", [0, 79, 100], False),
    ("pullDone", [0, 200, 801], False),
    ("pullDone", [0, 200, -1], False),
    ("pullDone", [0, -200, 100], False),
    # navbar finish rule: dy <= -40, more vertical than horizontal
    ("navbarDone", [0, -40], True),
    ("navbarDone", [30, -40], True),
    ("navbarDone", [40, -40], False),
    ("navbarDone", [0, -39], False),
    ("navbarDone", [0, 40], False),
]


def test_classifier_table():
    out = _eval(calls=[[fn, *args] for fn, args, _ in TABLE])["calls"]
    for (fn, args, expected), got in zip(TABLE, out):
        assert got == expected, f"{fn}{tuple(args)} = {got!r}, expected {expected!r}"


def test_constants_match_plan():
    res = subprocess.run(
        [NODE, "-e",
         "const G=require(process.argv[1]);"
         "process.stdout.write(JSON.stringify([G.EDGE_PX,G.PULL_MIN,G.PULL_MAX_MS,"
         "G.TAP_SLOP,G.HOLD_PASS_MS,G.NAVBAR_MIN]))",
         str(ROOT / "src/dashboard/web/js/components/gestures.js")],
        capture_output=True, text=True, timeout=60,
    )
    assert res.returncode == 0, res.stderr
    assert json.loads(res.stdout) == [40, 80, 800, 10, 500, 40]


# (name, ops, expected events) — ops/events as documented in gestures_eval.js
SCRIPTS = [
    ("top tap → tap(p0)",
     [["down", 500, 20, 0, H], ["move", 503, 22, 50], ["up", 503, 22, 100]],
     [["send", "tap", 500, 20]]),
    ("pull down → onPull, nothing to AA",
     [["down", 500, 10, 0, H], ["move", 505, 30, 50], ["move", 510, 150, 200],
      ["up", 510, 160, 300]],
     [["pull"]]),
    ("pull too slow → discarded",
     [["down", 500, 10, 0, H], ["move", 505, 30, 50], ["up", 510, 160, 900]],
     []),
    ("pull too short → discarded",
     [["down", 500, 10, 0, H], ["move", 505, 30, 50], ["up", 505, 60, 100]],
     []),
    ("pull that drifts sideways later is still swallowed",
     [["down", 500, 10, 0, H], ["move", 502, 30, 50], ["move", 700, 100, 200],
      ["up", 700, 110, 300]],
     []),
    ("bottom swipe up → onNavbar",
     [["down", 500, 590, 0, H], ["move", 500, 570, 50], ["up", 500, 520, 100]],
     [["navbar"]]),
    ("bottom swipe up too short → discarded",
     [["down", 500, 590, 0, H], ["move", 500, 575, 50], ["up", 500, 565, 100]],
     []),
    ("horizontal drag from the bottom edge → replayed to AA",
     [["down", 500, 590, 0, H], ["move", 530, 588, 50], ["move", 600, 588, 80],
      ["up", 650, 588, 120]],
     [["send", "down", 500, 590], ["send", "move", 530, 588],
      ["send", "move", 600, 588], ["send", "up", 650, 588]]),
    ("horizontal drag from the top edge → replayed to AA",
     [["down", 100, 30, 0, H], ["move", 140, 32, 50], ["up", 200, 32, 120]],
     [["send", "down", 100, 30], ["send", "move", 140, 32], ["send", "up", 200, 32]]),
    ("edge long press (timer) → down(p0), then up",
     [["down", 500, 20, 0, H], ["timer"], ["state"], ["move", 504, 22, 600],
      ["up", 504, 22, 900]],
     [["send", "down", 500, 20], ["state", "pass"], ["send", "move", 504, 22],
      ["send", "up", 504, 22]]),
    ("edge long press (move clock, throttled timer) → down(p0)",
     [["down", 500, 20, 0, H], ["move", 502, 21, 600], ["state"]],
     [["send", "down", 500, 20], ["state", "pass"]]),
    ("middle touch passes straight through",
     [["down", 500, 300, 0, H], ["move", 520, 330, 30], ["up", 540, 360, 60]],
     [["send", "down", 500, 300], ["send", "move", 520, 330], ["send", "up", 540, 360]]),
    ("cancel while passing → cancel; while held → nothing",
     [["down", 500, 300, 0, H], ["cancel"], ["down", 500, 10, 0, H], ["cancel"],
      ["timer"], ["state"]],
     [["send", "down", 500, 300], ["send", "cancel", None, None], ["state", "idle"]]),
    ("second down while a touch is active is ignored",
     [["down", 500, 300, 0, H], ["down", 10, 10, 5, H], ["up", 500, 300, 50]],
     [["send", "down", 500, 300], ["send", "up", 500, 300]]),
    ("timer after a pull decision does nothing",
     [["down", 500, 10, 0, H], ["move", 500, 40, 50], ["timer"], ["state"]],
     [["state", "pull"]]),
]


@pytest.mark.parametrize("name, ops, expected", SCRIPTS, ids=[s[0] for s in SCRIPTS])
def test_edge_tracker(name, ops, expected):
    events = _eval(scripts=[ops])["scripts"][0]
    assert events == expected


@pytest.mark.parametrize("harness", ["app_smoke.js", "aa_screen_smoke.js",
                                     "call_nav_smoke.js"])
def test_screen_harness(harness):
    res = subprocess.run([NODE, str(JS / harness)], capture_output=True, text=True,
                         timeout=60)
    assert res.returncode == 0, res.stderr or res.stdout
    assert res.stdout.strip().endswith("ok")
