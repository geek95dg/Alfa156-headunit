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
* weather_escape_smoke.js: screens/weather.js — geocoder place names and
  the weather city / condition never become markup, results are picked via
  data-weather-idx + one delegated listener, and only valid coordinates reach
  the map and POST /api/weather/location.
"""

import json
import os
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


@pytest.mark.parametrize("harness", ["app_smoke.js", "aa_screen_smoke.js",
                                     "call_nav_smoke.js", "settings_tether_smoke.js",
                                     "appbar_phone_smoke.js", "phone_escape_smoke.js",
                                     "gps_visibility_smoke.js", "dial_result_smoke.js",
                                     "settings_modules_smoke.js", "weather_escape_smoke.js",
                                     "settings_car_phone_smoke.js",
                                     "settings_car_phone_agent_smoke.js"])
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
        "before": {"modules": before, "restart_required": False},
        "after": {"modules": after, "restart_required": True, "enabled_also": ["bluetooth"]},
    }), encoding="utf-8")
    res = subprocess.run([NODE, str(JS / "settings_modules_browser_smoke.js"), str(fixture)],
                         capture_output=True, text=True, timeout=120)
    out = res.stdout.strip()
    if res.returncode == 0 and out.startswith("SKIP:"):
        pytest.skip(out[5:].strip())
    assert res.returncode == 0, res.stderr or res.stdout
    assert out.endswith("ok"), out


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
