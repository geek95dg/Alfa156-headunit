"""Frontend gesture logic, run in plain node (skipped without node).

* the pure classifier in web/js/components/gestures.js — edge zones,
  pull / navbar / pass decisions and the finish rules — as a table;
* the AA edge state machine (createEdgeTracker) on scripted touches;
* smoke harnesses that load app.js+appbar.js and screens/android_auto.js in
  a node vm with DOM stubs (tests/js/*.js, plain node + assert);
* call_nav_smoke.js: app.js + screens/phone.js — an incoming call switches to
  A8 from any screen (not A2), Phone state never goes stale, caller text is
  escaped, and the kiosk returns to the previous screen when the call ends;
* settings_tether_smoke.js: screens/settings.js — the "Internet z telefonu"
  row (state label, IP only when connected, values escaped, inline styles, no
  row without a payload, hint + "Ponów" when failed) and update(), which
  redraws only that row while Settings is open;
* settings_car_phone_smoke.js: screens/settings.js — the "Telefon w aucie"
  row (data.car_phone: state label, IP only when connected, battery / °C /
  GPS / hotspot, heat colour from the module's own level, hints instead of
  raw adb errors, escaping, inline styles, "Ponów") and its update() slot;
* settings_car_phone_agent_smoke.js: screens/settings.js — the "Agent w
  telefonie" row (data.car_phone_agent: state label, version / SIM / last
  contact type-checked, a hint by reason instead of the raw error, "Sparuj"
  only while unpaired and posting no body, escaping, inline styles) and its
  update() slot;
* settings_parking_guard_smoke.js: screens/settings.js — the "Postój" row
  (data.parking_guard: state labels, Uzbrój only when disarmed, Rozbrój with
  a TOTP code field unless the owner's phone is connected, the last event,
  hints, the command outcome, escaping, inline styles, one delegated
  listener, the code only in the POST body and cleared after) and its
  update() slot, not redrawn while typing;
* settings_cabin_watch_smoke.js: screens/settings.js — the "Czuwanie
  kabiny" row (data.cabin_watch: state labels, why the camera is off, the
  last event with reasons / photos / analysis / outcome, hints, escaping,
  inline styles, read-only — no buttons) and its update() slot; the park
  row's "ruch w kabinie" event;
* settings_traccar_smoke.js: screens/settings.js — the "Traccar" row (states,
  queue, error classes, hints, the command outcome, escaping, one delegated
  listener, "Wyślij pozycję teraz" = one POST with {}) and "Ostatni postój"
  (time, coordinates, the map URL as text — no navigation away from the
  kiosk) with their update() slots;
* settings_voice_smoke.js: screens/settings.js — the "Komunikaty głosowe"
  row (whitelisted clicks, slider bounds, the fixed-phrase test button);
* settings_voice_browser_smoke.js: the same row in headless Chromium at
  1024x600 (fits, "Powiedz test" tappable). Skipped without playwright;
* settings_traccar_browser_smoke.js: the "Traccar" and "Ostatni postój"
  rows in headless Chromium at 1024x600 (fit, the send button tappable).
  Skipped without playwright;
* settings_brightness_smoke.js: screens/settings.js — the "Jasność ekranu"
  row (data.auto_brightness: status per mode with the current lux, Auto /
  Ręczna, the slider, "Programowe / Sprzętowe (DDC/CI)" with the probe's
  verdict and reason, escaping, inline styles, no inline handlers, only the
  whitelisted /api/config bodies from the delegated listeners) and its
  update() slot — numbers in place, nothing under the finger; plus
  components/dim_overlay.js's level rules;
* dim_overlay_browser_smoke.js: the software dimming overlay on the real
  dashboard in headless Chromium at 1024x600 (mouse and touch): one fixed
  black layer, z-index 190, pointer-events none, over A1 and Android Auto
  but UNDER the reverse camera view and the crash window (paint order), taps
  go through it, removed for level 0 / no payload; the Settings row posts
  the switch, the mode and the slider value. Skipped without playwright;
* appbar_phone_smoke.js: components/appbar.js — the phone cluster (signal /
  operator / battery from data.phone_status): hidden without a phone, glyphs
  by level, the operator only ever via textContent, change-only updates;
  the glyph names it can produce are checked against the bundled font;
* phone_escape_smoke.js: text from the phone or any Bluetooth device in range
  (PBAP contacts/history, call overlays, AVRCP title, BT device names, the
  pairing popup, notification cards) never becomes markup or script, and a
  phonebook number reaches the dialer only through data-dial + a validated
  delegated click;
* gps_visibility_smoke.js: the Settings "GPS" row (source, fix, sender, the
  "send NMEA to <bnep0 IP>:10110" hint, escaping, change-only update()), the
  weather map badge following gps_fix, and the travel plan's
  "start: domyślny (brak GPS)";
* dial_result_smoke.js: screens/phone.js drops its instant "ringing"
  overlay when the backend reports a failed dial (bt.dial_result);
* settings_modules_smoke.js: Settings → Moduły — hardware note,
  "niedostępny w tej wersji", "nie wystartuje" and "wymaga restartu BCM",
  the explicit question before enabling a module whose dependencies are off
  (or disabling one others need), escaping, inline styles only; module
  actions redraw only the card, with the question under the tapped row;
* settings_modules_browser_smoke.js: the same card on the real dashboard in
  headless Chromium at 1024x600 (mouse and touch), fed from the real
  catalog: the question and the save status stay on screen when the card is
  scrolled into view (a full re-render used to reset the scroll and draw
  them below the panel). Skipped without the playwright package/Chromium;
* crash_modal_smoke.js: the crash SMS window (components/crash_modal.js) —
  which payloads open it, its texts (DRY RUN, forced test-mode reason, "Brak
  połączenia z telefonem – SMS NIE zostanie wysłany", results), escaping,
  ANULUJ >= 1/3 of the screen and the reserved 112 slot >= 15% away (from the
  inline styles); app.js lists #crash-modal in GESTURE_OVERLAYS and syncs it
  on every screen; the Settings "SMS po stłuczce" row and recipients editor;
* crash_modal_browser_smoke.js: the same window on the real dashboard in
  headless Chromium at 1024x600 (mouse and touch): on A2 and A1 without
  navigating, nothing off-screen, ANULUJ >= 1/3 and on top, an edge pull
  does not navigate, beeps while pending, one POST {event_id} per tap, the
  result closes on a tap. Skipped without the playwright package/Chromium;
* hold_eval.js: components/hold.js — the hold-to-confirm of the 112 and
  "Rozłącz" buttons on a fake clock: too short, finger left, pointercancel,
  the arm delay, a second finger, a late or early timer, rearm, destroy;
* call112_browser_smoke.js: "Zadzwoń 112" in the crash window on the real
  dashboard in headless Chromium at 1024x600 (mouse and a real touch): the
  red button >= 15% away from ANULUJ / Zamknij, naming the path, hold
  rules, one POST with an empty body, the call view, "Rozłącz" held 1 s,
  "Odbierz", the dispatcher panel >= 48 px that fits, test-mode label, no
  button without the module or off the kiosk. Skipped without playwright;
* settings_phone_sensors_smoke.js: Settings "Czujniki telefonu" (Hz per
  sensor, lux and its age, forward hints, test verdicts, "Test" button).
* settings_phone_sensors_browser_smoke.js: the same row on the real
  dashboard in headless Chromium at 1024x600 with its longest payload and
  a steady-light verdict: fits the width, "Test" on screen and tappable.
  Skipped without playwright;
* settings_net_diag_smoke.js: Settings "Internet i usługi" (uplink, internet
  probe, key presence and last result per service, "Test" with its answers),
  "połączono, bez internetu" on the phone rows, the trip plan error banner
  and approximate-route hint, the weather "dane przykładowe" line instead of
  Milan;
* weather_escape_smoke.js: screens/weather.js — geocoder place names and
  the weather city / condition never become markup, results are picked via
  data-weather-idx + one delegated listener, and only valid coordinates reach
  the map and POST /api/weather/location;
* spectrum_smoke.js: the A1 spectrum strip in screens/main.js — rAF easing
  toward the last frame, falling peak caps, 2 px baseline at silence,
  fillRect without roundRect, whole-pixel canvas, cached gradient, theme CSS
  colours, garbage payloads, loop stops on unmount / missing canvas;
* spectrum_browser_smoke.js: the same strip in headless Chromium at
  1024x600 in all three themes (pixels: baseline at silence, bars with
  music), without roundRect, and a throwing screen update() that must not
  keep the reverse-camera view from opening. Skipped without playwright.
* trip_fuel_smoke.js: the A3 refuel panel (data.fuel_log) in all three
  themes — real values, "—" instead of 0 without a source, no made-up chart,
  module off / read-only states, escaping;
* trip_fuel_browser_smoke.js: the "Zatankowano" form in headless Chromium at
  1024x600 — fields above the on-screen keyboard, "," key, "Do pełna"
  default, odometer confirmation, POST body. Skipped without playwright.
* weather_alerts_smoke.js: A4 forecast rows from data.weather_forecast in
  all three themes (no values made up from the current temperature), the
  warning strip (escaped, most severe first, updated in place) and the
  top-bar warning icon; the kiosk icing popup stays disabled;
* weather_alerts_browser_smoke.js: the same at 1024x600 in headless
  Chromium — strip inside the map, icon clear of logo and temperature, tap
  opens A4. Skipped without playwright.
* trip_traffic_browser_smoke.js: the live TomTom list on the A3 travel
  plan overlay (data.traffic_alerts) at 1024x600 in all three themes —
  hidden with the module off, escaped network text, refreshed in place
  (overlay not rebuilt), status lines. Skipped without playwright.
"""

import json
import os
import re
import shutil
import struct
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


def _hold(scripts):
    res = subprocess.run(
        [NODE, str(JS / "hold_eval.js")],
        input=json.dumps({"scripts": scripts}), capture_output=True, text=True, timeout=60,
    )
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)["scripts"]


ARMED = ["advance", 800]          # past the 700 ms arm delay
# (name, opts, ops, expected events) — see tests/js/hold_eval.js
HOLD_SCRIPTS = [
    ("2 s hold fires once", {}, [
        ARMED, ["press", 1], ["advance", 1999], ["state"], ["advance", 1], ["state"],
        ["advance", 5000]],
     [["press", "holding"], ["state", "holding"], ["fire"], ["state", "fired"]]),
    ("too short", {}, [
        ARMED, ["press", 1], ["advance", 1500], ["release", 1], ["advance", 3000], ["state"]],
     [["press", "holding"], ["reset", "released"], ["state", "idle"]]),
    ("finger slid off the button", {}, [
        ARMED, ["press", 1], ["advance", 1000], ["leave", 1], ["advance", 3000]],
     [["press", "holding"], ["reset", "left"]]),
    ("pointercancel (browser took the touch)", {}, [
        ARMED, ["press", 1], ["advance", 1900], ["cancel", 1], ["advance", 3000]],
     [["press", "holding"], ["reset", "cancelled"]]),
    ("inactive during the arm delay", {}, [
        ["advance", 699], ["press", 1], ["advance", 5000], ["state"]],
     [["press", "not_armed"], ["state", "idle"]]),
    ("armed right after the delay", {}, [
        ["advance", 700], ["press", 1], ["advance", 2000]],
     [["press", "holding"], ["fire"]]),
    ("a second finger neither restarts nor fires twice", {}, [
        ARMED, ["press", 1], ["advance", 1000], ["press", 2], ["release", 2],
        ["advance", 1000], ["press", 1], ["advance", 5000]],
     [["press", "holding"], ["press", "busy"], ["fire"], ["press", "fired"]]),
    ("double trigger: fired stays fired until rearm", {}, [
        ARMED, ["press", 1], ["advance", 2000], ["release", 1], ["press", 1],
        ["advance", 3000], ["rearm", 700], ["press", 1], ["advance", 700], ["press", 1],
        ["advance", 2000]],
     [["press", "holding"], ["fire"], ["press", "fired"], ["press", "not_armed"],
      ["press", "holding"], ["fire"]]),
    ("a late timer after the release does nothing", {}, [
        ARMED, ["press", 1], ["advance", 1000], ["snap"], ["release", 1], ["advance", 1500],
        ["late"], ["state"]],
     [["press", "holding"], ["reset", "released"], ["state", "idle"]]),
    ("a timer that fires early waits for the rest", {}, [
        ARMED, ["press", 1], ["snap"], ["advance", 500], ["late"], ["state"],
        ["advance", 1500], ["state"], ["advance", 5000]],
     [["press", "holding"], ["state", "holding"], ["fire"], ["state", "fired"]]),
    ("progress follows the hold", {}, [
        ARMED, ["press", 1], ["advance", 500], ["progress"], ["advance", 500], ["progress"]],
     [["press", "holding"], ["progress", 0.25], ["progress", 0.5]]),
    ("Rozłącz: 1 s", {"holdMs": 1000, "armDelayMs": 0}, [
        ["press", 1], ["advance", 999], ["state"], ["advance", 1]],
     [["press", "holding"], ["state", "holding"], ["fire"]]),
    ("destroyed: nothing fires", {}, [
        ARMED, ["press", 1], ["advance", 1000], ["destroy"], ["advance", 3000], ["press", 1]],
     [["press", "holding"], ["press", "dead"]]),
    ("nonsense options fall back to 2 s / 0.7 s", {"holdMs": "x", "armDelayMs": -5}, [
        ["advance", 600], ["press", 1], ["advance", 200], ["press", 1], ["advance", 1999],
        ["state"], ["advance", 1]],
     [["press", "not_armed"], ["press", "holding"], ["state", "holding"], ["fire"]]),
]


@pytest.mark.parametrize("name, opts, ops, expected", HOLD_SCRIPTS,
                         ids=[s[0] for s in HOLD_SCRIPTS])
def test_hold_to_confirm(name, opts, ops, expected):
    assert _hold([{"opts": opts, "ops": ops}])[0] == expected


def test_hold_js_has_no_dom_at_load_and_blocks_the_long_press_menu():
    src = (ROOT / "src/dashboard/web/js/components/hold.js").read_text(encoding="utf-8")
    for needle in ('"contextmenu"', "setPointerCapture", 'touchAction = "none"',
                   '"pointercancel"', '"lostpointercapture"', "passive: false"):
        assert needle in src, needle
    html = (ROOT / "src/dashboard/web/index.html").read_text(encoding="utf-8")
    assert html.index("components/hold.js") < html.index("components/crash_modal.js")


@pytest.mark.timeout(200)
def test_refuel_form_in_chromium():
    """A3 "Zatankowano" form at 1024x600 in headless Chromium, every theme,
    mouse and touch: touch-sized fields lifted above the on-screen keyboard,
    "45,5" typed on it, "Do pełna" on by default, the odometer confirmation
    and the POST body (see the harness). Nothing is stored anywhere."""
    res = subprocess.run([NODE, str(JS / "trip_fuel_browser_smoke.js")],
                         capture_output=True, text=True, timeout=180)
    out = res.stdout.strip()
    if res.returncode == 0 and out.startswith("SKIP:"):
        pytest.skip(out[5:].strip())
    assert res.returncode == 0, res.stderr or res.stdout
    assert out.endswith("ok"), out


@pytest.mark.timeout(150)
def test_weather_alerts_in_chromium():
    """modules.weather_alerts: the A4 strip and the top-bar icon at 1024x600
    in all three themes (see the harness)."""
    res = subprocess.run([NODE, str(JS / "weather_alerts_browser_smoke.js")],
                         capture_output=True, text=True, timeout=120)
    out = res.stdout.strip()
    if res.returncode == 0 and out.startswith("SKIP:"):
        pytest.skip(out[5:].strip())
    assert res.returncode == 0, res.stderr or res.stdout
    assert out.endswith("ok"), out


@pytest.mark.timeout(150)
def test_traffic_list_in_chromium():
    """modules.traffic_alerts: the live list on the A3 travel plan overlay
    at 1024x600 in all three themes (see the harness)."""
    res = subprocess.run([NODE, str(JS / "trip_traffic_browser_smoke.js")],
                         capture_output=True, text=True, timeout=120)
    out = res.stdout.strip()
    if res.returncode == 0 and out.startswith("SKIP:"):
        pytest.skip(out[5:].strip())
    assert res.returncode == 0, res.stderr or res.stdout
    assert out.endswith("ok"), out


def test_traffic_glyphs_exist_in_the_bundled_font():
    """Every icon the live traffic list (trip.js) and the traffic toasts
    (src/trip/traffic_alerts.py) can draw."""
    from src.trip import traffic_alerts
    src = (ROOT / "src/dashboard/web/js/screens/trip.js").read_text(encoding="utf-8")
    block = re.search(r"const _TRAFFIC_ICONS = \{([^}]*)\}", src).group(1)
    icons = set(re.findall(r'[a-z]+: "([a-z_]+)"', block)) | set(traffic_alerts._ICONS.values())
    assert {"traffic", "car_crash", "block", "construction"} <= icons
    missing = sorted(icons - _font_ligatures(FONT))
    assert not missing, f"not in {FONT.name}: {missing}"


def test_weather_alert_glyphs_exist_in_the_bundled_font():
    """Every icon the warning strip, the top-bar icon and the forecast rows
    can draw (the harness prints them on its first line)."""
    res = subprocess.run([NODE, str(JS / "weather_alerts_smoke.js")], capture_output=True,
                         text=True, timeout=60)
    assert res.returncode == 0, res.stderr or res.stdout
    glyphs = set(json.loads(res.stdout.strip().splitlines()[0]))
    assert {"ac_unit", "air", "foggy", "weather_snowy"} <= glyphs
    src = (ROOT / "src/dashboard/web/js/screens/weather.js").read_text(encoding="utf-8")
    block = re.search(r"const _OWM_GLYPHS = \{([^}]*)\}", src).group(1)
    glyphs |= set(re.findall(r'"([a-z_]+)"', block))
    missing = sorted(glyphs - _font_ligatures(FONT))
    assert not missing, f"not in {FONT.name}: {missing}"


@pytest.mark.timeout(200)
def test_call112_in_chromium():
    """The 112 button, call view and dispatcher panel at 1024x600 in
    headless Chromium (see the harness). Nothing can dial: every request is
    answered by the harness."""
    res = subprocess.run([NODE, str(JS / "call112_browser_smoke.js")],
                         capture_output=True, text=True, timeout=180)
    out = res.stdout.strip()
    if res.returncode == 0 and out.startswith("SKIP:"):
        pytest.skip(out[5:].strip())
    assert res.returncode == 0, res.stderr or res.stdout
    assert out.endswith("ok"), out


@pytest.mark.parametrize("harness", ["app_smoke.js", "aa_screen_smoke.js",
                                     "call_nav_smoke.js", "settings_tether_smoke.js",
                                     "appbar_phone_smoke.js", "phone_escape_smoke.js",
                                     "gps_visibility_smoke.js", "dial_result_smoke.js",
                                     "settings_modules_smoke.js", "weather_escape_smoke.js",
                                     "settings_car_phone_smoke.js",
                                     "settings_car_phone_agent_smoke.js",
                                     "settings_parking_guard_smoke.js",
                                     "settings_cabin_watch_smoke.js",
                                     "settings_brightness_smoke.js",
                                     "crash_modal_smoke.js", "wake_banner_smoke.js",
                                     "spectrum_smoke.js", "settings_net_diag_smoke.js",
                                     "settings_phone_sensors_smoke.js",
                                     "trip_fuel_smoke.js", "weather_alerts_smoke.js",
                                     "settings_voice_smoke.js",
                                     "settings_traccar_smoke.js"])
def test_screen_harness(harness):
    res = subprocess.run([NODE, str(JS / harness)], capture_output=True, text=True,
                         timeout=60)
    assert res.returncode == 0, res.stderr or res.stdout
    assert res.stdout.strip().endswith("ok")


# pytest.ini's 60 s per-test limit is tight for two browser runs on a slow
# host; the subprocess limit stays below this mark so a hang ends in a
# readable TimeoutExpired with node killed, not in pytest-timeout.
@pytest.mark.timeout(150)
def test_modules_card_in_chromium(tmp_path):
    """Settings → Moduły at 1024x600: the dependency question and the save
    status are drawn where the driver is looking. The fixture is the real
    catalog_state — test config with bluetooth and phone_status off, then
    the reply after "Włącz z zależnościami" on phone_status."""
    from src.core import config as config_mod
    from src.core import modules_catalog as mc
    from src.core.config import BCMConfig

    cfg = BCMConfig(config_path=str(ROOT / "config" / "bcm_config_test.yaml"),
                    platform_override="x86", local_path=None, env={})
    for key in ("modules.bluetooth", "bluetooth.enabled", "modules.phone_status"):
        cfg.set(key, False)
    boot = {n: st.runs for n, st in mc.module_states(cfg).items()}
    before = mc.catalog_state(cfg, boot)
    assert {m["name"]: m["needs"] for m in before}["phone_status"] == ["bluetooth"]
    for key in ("modules.bluetooth", "bluetooth.enabled", "modules.phone_status"):
        cfg.set(key, True)
    after = mc.catalog_state(cfg, boot)
    fixture = tmp_path / "modules.json"
    fixture.write_text(json.dumps({
        # local.yaml still for bcm_config_test.yaml: the banner at the top of
        # the card (the real command shape) must not break the layout.
        "before": {"modules": before, "restart_required": False,
                   "config_migration": {
                       "recorded": "bcm_config_test.yaml", "base": "bcm_config.yaml",
                       "command": config_mod.migration_command(
                           ROOT / "config" / "local.yaml",
                           ROOT / "config" / "bcm_config.yaml")}},
        "after": {"modules": after, "restart_required": True, "enabled_also": ["bluetooth"]},
    }), encoding="utf-8")
    res = subprocess.run([NODE, str(JS / "settings_modules_browser_smoke.js"), str(fixture)],
                         capture_output=True, text=True, timeout=120)
    out = res.stdout.strip()
    if res.returncode == 0 and out.startswith("SKIP:"):
        pytest.skip(out[5:].strip())
    assert res.returncode == 0, res.stderr or res.stdout
    assert out.endswith("ok"), out


@pytest.mark.timeout(150)
def test_crash_modal_in_chromium():
    """The crash window at 1024x600 in headless Chromium (see the harness)."""
    res = subprocess.run([NODE, str(JS / "crash_modal_browser_smoke.js")],
                         capture_output=True, text=True, timeout=120)
    out = res.stdout.strip()
    if res.returncode == 0 and out.startswith("SKIP:"):
        pytest.skip(out[5:].strip())
    assert res.returncode == 0, res.stderr or res.stdout
    assert out.endswith("ok"), out


@pytest.mark.timeout(150)
def test_dim_overlay_in_chromium():
    """modules.auto_brightness: the dimming overlay under the safety views
    and the "Jasność ekranu" row at 1024x600 (see the harness)."""
    res = subprocess.run([NODE, str(JS / "dim_overlay_browser_smoke.js")],
                         capture_output=True, text=True, timeout=120)
    out = res.stdout.strip()
    if res.returncode == 0 and out.startswith("SKIP:"):
        pytest.skip(out[5:].strip())
    assert res.returncode == 0, res.stderr or res.stdout
    assert out.endswith("ok"), out


@pytest.mark.timeout(150)
def test_phone_sensors_row_in_chromium():
    """Settings "Czujniki telefonu" at 1024x600: no overflow with every
    optional line, "Test" visible and posting once (see the harness)."""
    res = subprocess.run([NODE, str(JS / "settings_phone_sensors_browser_smoke.js")],
                         capture_output=True, text=True, timeout=120)
    out = res.stdout.strip()
    if res.returncode == 0 and out.startswith("SKIP:"):
        pytest.skip(out[5:].strip())
    assert res.returncode == 0, res.stderr or res.stdout
    assert out.endswith("ok"), out


@pytest.mark.timeout(150)
def test_voice_row_in_chromium():
    """Settings "Komunikaty głosowe" at 1024x600: no overflow with the
    longest status, "Powiedz test" visible, posting once with no body, a
    category tap posting one whitelisted change (see the harness)."""
    res = subprocess.run([NODE, str(JS / "settings_voice_browser_smoke.js")],
                         capture_output=True, text=True, timeout=120)
    out = res.stdout.strip()
    if res.returncode == 0 and out.startswith("SKIP:"):
        pytest.skip(out[5:].strip())
    assert res.returncode == 0, res.stderr or res.stdout
    assert out.endswith("ok"), out


@pytest.mark.timeout(150)
def test_traccar_rows_in_chromium():
    """Settings "Traccar" and "Ostatni postój" at 1024x600: no overflow with
    the longest hints and map URL, "Wyślij pozycję teraz" visible and
    posting "{}" once (see the harness)."""
    res = subprocess.run([NODE, str(JS / "settings_traccar_browser_smoke.js")],
                         capture_output=True, text=True, timeout=120)
    out = res.stdout.strip()
    if res.returncode == 0 and out.startswith("SKIP:"):
        pytest.skip(out[5:].strip())
    assert res.returncode == 0, res.stderr or res.stdout
    assert out.endswith("ok"), out


@pytest.mark.timeout(150)
def test_spectrum_strip_in_chromium():
    """A1 spectrum canvas: baseline at silence, bars with music, no roundRect,
    and a renderer exception cannot skip the reverse view (see the harness)."""
    res = subprocess.run([NODE, str(JS / "spectrum_browser_smoke.js")],
                         capture_output=True, text=True, timeout=120)
    out = res.stdout.strip()
    if res.returncode == 0 and out.startswith("SKIP:"):
        pytest.skip(out[5:].strip())
    assert res.returncode == 0, res.stderr or res.stdout
    assert out.endswith("ok"), out


def test_dim_overlay_sits_below_every_safety_layer():
    """The z-index the overlay uses is below the reverse camera view and the
    crash window as their code sets them (the browser test checks the paint
    order; this pins the numbers the comments promise)."""
    dim = (ROOT / "src/dashboard/web/js/components/dim_overlay.js").read_text(encoding="utf-8")
    z = int(re.search(r"const Z_INDEX = (\d+);", dim).group(1))
    app = (ROOT / "src/dashboard/web/js/app.js").read_text(encoding="utf-8")
    reverse = int(re.search(r'overlay\.id = "reverse-overlay";\s*overlay\.className = "[^"]*z-\[(\d+)\]',
                            app).group(1))
    crash = (ROOT / "src/dashboard/web/js/components/crash_modal.js").read_text(encoding="utf-8")
    modal = int(re.search(r'_el\.style\.cssText = "position:fixed;inset:0;z-index:(\d+);', crash).group(1))
    assert 0 < z < reverse < modal, (z, reverse, modal)
    assert "pointer-events:none" in dim and "MAX_LEVEL = 0.9" in dim
    html = (ROOT / "src/dashboard/web/index.html").read_text(encoding="utf-8")
    assert html.index("components/dim_overlay.js") < html.index("/js/app.js")


def test_brightness_row_glyph_exists_in_the_bundled_font():
    src = (ROOT / "src/dashboard/web/js/screens/settings.js").read_text(encoding="utf-8")
    assert ">brightness_6</span>" in src
    assert "brightness_6" in _font_ligatures(FONT)


def test_crash_window_glyphs_exist_in_the_bundled_font():
    """Every icon name the crash window and its Settings row can draw."""
    names = _font_ligatures(FONT)
    src = (ROOT / "src/dashboard/web/js/components/crash_modal.js").read_text(encoding="utf-8")
    block = re.search(r"const icons = \{([^}]*)\}", src).group(1)
    icons = set(re.findall(r'[a-z_]+: "([a-z_]+)"', block))
    icons |= {"info", "car_crash", "help"}                # help: "unconfirmed"
    assert len(icons) >= 7
    assert icons <= names, icons - names


# ── Material Symbols: the glyphs the top-bar phone cluster asks for ──────

FONT = ROOT / "src/dashboard/web/assets/fonts/material-symbols-latin.ttf"


def _font_ligatures(path):
    """Names the font turns into icons: the GSUB ligature table (lookup type
    4, also behind extension lookups, type 7) read with plain struct — no
    fontTools in the venv. Letters are mapped back through the cmap."""
    data = path.read_bytes()

    def u16(o):
        return struct.unpack(">H", data[o:o + 2])[0]

    def u32(o):
        return struct.unpack(">I", data[o:o + 4])[0]

    tables = {}
    for i in range(u16(4)):
        rec = 12 + 16 * i
        tables[data[rec:rec + 4].decode("latin-1")] = u32(rec + 8)

    gid2ch = {}
    cmap = tables["cmap"]
    for i in range(u16(cmap + 2)):
        sub = cmap + u32(cmap + 4 + 8 * i + 4)
        if u16(sub) != 4:
            continue
        segs = u16(sub + 6) // 2
        ends, starts = sub + 14, sub + 16 + 2 * segs
        deltas, ranges = starts + 2 * segs, starts + 4 * segs
        for k in range(segs):
            start, end = u16(starts + 2 * k), u16(ends + 2 * k)
            delta = struct.unpack(">h", data[deltas + 2 * k:deltas + 2 * k + 2])[0]
            ro = u16(ranges + 2 * k)
            for c in range(start, min(end, 0x7F) + 1):
                if ro:
                    g = u16(ranges + 2 * k + ro + 2 * (c - start))
                    g = (g + delta) & 0xFFFF if g else 0
                else:
                    g = (c + delta) & 0xFFFF
                if g:
                    gid2ch.setdefault(g, chr(c).lower())

    def coverage(o):
        if u16(o) == 1:
            return [u16(o + 4 + 2 * i) for i in range(u16(o + 2))]
        out = []
        for i in range(u16(o + 2)):
            out.extend(range(u16(o + 4 + 6 * i), u16(o + 6 + 6 * i) + 1))
        return out

    names = set()
    gsub = tables["GSUB"]
    lookups = gsub + u16(gsub + 8)
    for li in range(u16(lookups)):
        lo = lookups + u16(lookups + 2 + 2 * li)
        for si in range(u16(lo + 4)):
            so, kind = lo + u16(lo + 6 + 2 * si), u16(lo)
            if kind == 7:
                kind, so = u16(so + 2), so + u32(so + 4)
            if kind != 4:
                continue
            for k, first in enumerate(coverage(so + u16(so + 2))):
                ls = so + u16(so + 6 + 2 * k)
                for j in range(u16(ls)):
                    lig = ls + u16(ls + 2 + 2 * j)
                    comps = [u16(lig + 4 + 2 * c) for c in range(u16(lig + 2) - 1)]
                    chars = [gid2ch.get(g) for g in [first] + comps]
                    if None not in chars:
                        names.add("".join(chars))
    return names


def test_phone_cluster_glyphs_exist_in_the_bundled_font():
    """A glyph name the font does not know renders as its literal text
    ("signal_cellular_3_bar") in the top bar."""
    ligatures = _font_ligatures(FONT)
    # The parser itself works: icons the dashboard has always used.
    assert {"bluetooth", "equalizer", "settings", "restart_alt", "call"} <= ligatures
    res = subprocess.run([NODE, str(JS / "appbar_phone_smoke.js")], capture_output=True,
                         text=True, timeout=60)
    assert res.returncode == 0, res.stderr or res.stdout
    glyphs = set(json.loads(res.stdout.strip().splitlines()[0]))
    assert len(glyphs) == 14
    missing = sorted(glyphs - ligatures)
    assert not missing, f"not in {FONT.name}: {missing}"


@pytest.mark.timeout(150)
def test_wake_banner_in_chromium():
    """modules.remote_session (plan E): the non-modal "Wybudzono" banner and
    the "Wybudzanie" row at 1024x600 (see the harness)."""
    res = subprocess.run([NODE, str(JS / "wake_banner_browser_smoke.js")],
                         capture_output=True, text=True, timeout=120)
    out = res.stdout.strip()
    if res.returncode == 0 and out.startswith("SKIP:"):
        pytest.skip(out[5:].strip())
    assert res.returncode == 0, res.stderr or res.stdout
    assert out.endswith("ok"), out


def test_wake_banner_layering_and_wiring():
    """The banner sits above the dimming overlay and the reverse camera /
    keyboard (200), below the crash window (300) and the notifications
    (400); it is loaded before app.js and is NOT a gesture overlay (the
    screen under it keeps working)."""
    banner = (ROOT / "src/dashboard/web/js/components/wake_banner.js").read_text(encoding="utf-8")
    z = int(re.search(r"const Z_INDEX = (\d+);", banner).group(1))
    dim = (ROOT / "src/dashboard/web/js/components/dim_overlay.js").read_text(encoding="utf-8")
    dim_z = int(re.search(r"const Z_INDEX = (\d+);", dim).group(1))
    crash = (ROOT / "src/dashboard/web/js/components/crash_modal.js").read_text(encoding="utf-8")
    modal = int(re.search(r'_el\.style\.cssText = "position:fixed;inset:0;z-index:(\d+);', crash).group(1))
    assert dim_z < 200 < z < modal < 400, (dim_z, z, modal)
    app = (ROOT / "src/dashboard/web/js/app.js").read_text(encoding="utf-8")
    overlays = re.search(r"const GESTURE_OVERLAYS = ([^;]+);", app).group(1)
    assert "wake-banner" not in overlays
    assert "try { _syncWakeBanner(data); } catch (e)" in app
    html = (ROOT / "src/dashboard/web/index.html").read_text(encoding="utf-8")
    assert html.index("components/wake_banner.js") < html.index("/js/app.js")
    # buttons by data-* and one delegated listener; texts never as HTML
    assert "onclick" not in banner and "data-wake-action" in banner
    assert 'body: "{}"' in banner                  # the step is the server's, never the client's
    # Above the autohiding NavBar (h-14 = 56 px) and out of the bottom
    # gesture strip, and it never swallows a touch: the bar's buttons and
    # the swipe up from the bottom edge keep working during a session.
    bottom = int(re.search(r"const BOTTOM_PX = (\d+);", banner).group(1))
    gestures = (ROOT / "src/dashboard/web/js/components/gestures.js").read_text(encoding="utf-8")
    edge = int(re.search(r"const EDGE_PX = (\d+);", gestures).group(1))
    assert bottom >= 56 + 12 and bottom > edge, (bottom, edge)
    assert ".stopPropagation(" not in banner
