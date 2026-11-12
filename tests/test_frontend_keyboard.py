"""On-screen keyboard (web/js/components/keyboard.js + web/css/themes.css).

Zgłoszenie B: since commit 2e3baaf (6th key row, 17 px root font) the 50vh
keyboard needed ~386 px of a 300 px panel on the 1024x600 screen, so the
bottom row (shift, z..m, backspace, SPACE, OK) sat below the screen. It also
closed itself right after opening for fields in the lower half and for every
password field. Covered here:

* oskLayout() — the pure geometry, as invariants over window heights
  300..1440 px for 6 and 7 rows (osk_layout_eval.js, plain node);
* isOskInput() — which fields open the keyboard;
* the CSS variables keyboard.js sets are the ones themes.css reads, and the
  rem-sized classes are gone from the keyboard markup;
* osk_dom_smoke.js — open/close/scroll behaviour against a fake DOM (plain
  node, so it also runs in CI);
* osk_browser_smoke.js — the real dashboard in headless Chromium at 1024x600
  (mouse and touch), 800x480 and 1280x800: every key inside the window and
  hit at its own centre, the field above the keys, typing, closing; and a
  picked trip/weather suggestion closes the keyboard (also on touch, where
  the trip planner suppresses the click) without the list coming back.
  Skipped without the playwright package or its Chromium.

Everything is skipped without node.
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "tests" / "js"
KEYBOARD_JS = ROOT / "src/dashboard/web/js/components/keyboard.js"
THEMES_CSS = ROOT / "src/dashboard/web/css/themes.css"


def _node():
    found = shutil.which("node")
    if found:
        return found
    for candidate in ("/opt/node22/bin/node", "/usr/local/bin/node"):
        if os.access(candidate, os.X_OK):
            return candidate
    return None


NODE = _node()
needs_node = pytest.mark.skipif(NODE is None, reason="node not installed")


def _eval(layouts=(), inputs=()):
    res = subprocess.run(
        [NODE, str(JS / "osk_layout_eval.js")],
        input=json.dumps({"layouts": list(layouts), "inputs": list(inputs)}),
        capture_output=True, text=True, timeout=60,
    )
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


# ── oskLayout ────────────────────────────────────────────────────────────

HEIGHTS = range(300, 1441, 10)


@needs_node
@pytest.mark.parametrize("n_rows", [6, 7])
def test_layout_invariants(n_rows):
    cases = [[vh, n_rows] for vh in HEIGHTS]
    out = _eval(layouts=cases)["layouts"]
    prev_height = 0
    for (vh, n), lay in zip(cases, out):
        h, pad, gap, row, font = (lay[k] for k in ("height", "pad", "gap", "rowH", "font"))
        where = f"vh={vh} n={n}: {lay}"
        assert all(isinstance(v, int) for v in lay.values()), where
        # Everything fits: padding + rows + gaps inside the panel, the panel
        # inside the window, with >= 150 px left above it for the field.
        assert 2 * pad + n * row + (n - 1) * gap <= h <= vh, where
        assert h <= vh - 150, where
        assert pad >= 4 and gap >= 3, where
        assert 14 <= font <= 26, where
        assert font <= row, where              # the label fits its row
        if vh >= 480:
            assert row >= 34, where            # still a finger-sized key
        if vh == 600:
            assert row >= 40, where            # the car's 1024x600 panel
        assert h >= prev_height, where         # never shrinks on a taller window
        prev_height = h


@needs_node
def test_layout_on_the_car_panel():
    """1024x600 with the keyboard's real row count: 6 rows of 50 px keys,
    348 px panel (58%), 252 px left above it."""
    res = _eval(layouts=[[600, 6], [600, 7], [480, 7]])
    assert res["rows"] == 6
    assert res["keys"] == 50
    assert res["layouts"][0] == {"height": 348, "pad": 7, "gap": 6, "rowH": 50, "font": 23}
    assert res["layouts"][1]["rowH"] == 42
    assert res["layouts"][2]["rowH"] == 34


@needs_node
def test_layout_degenerate_input():
    """Unusable heights fall back to the 7" panel; tiny ones never produce
    negative sizes; a bad row count counts as one row."""
    fallback = _eval(layouts=[[600, 6]])["layouts"][0]
    out = _eval(layouts=[[0, 6], [None, 6], ["abc", 6], [-5, 6],
                         [100, 7], [10, 7], [600, 0], [600, None], [599.7, 6]])["layouts"]
    assert out[:4] == [fallback] * 4
    for lay, vh in ((out[4], 100), (out[5], 10)):
        assert all(v >= 0 for v in lay.values()), lay
        assert lay["height"] <= vh
    one_row = out[6]
    assert one_row == out[7]
    assert 2 * one_row["pad"] + one_row["rowH"] <= one_row["height"]
    assert out[8]["height"] <= 599


# ── isOskInput ───────────────────────────────────────────────────────────

INPUTS = [
    ({"tagName": "INPUT", "type": "text"}, True),
    ({"tagName": "INPUT", "type": "password"}, True),
    ({"tagName": "INPUT", "type": "search"}, True),
    ({"tagName": "INPUT", "type": "email"}, True),
    ({"tagName": "INPUT", "type": "url"}, True),
    ({"tagName": "INPUT", "type": "tel"}, True),
    ({"tagName": "INPUT"}, True),                          # no type = text
    ({"tagName": "input", "type": "TEXT"}, True),
    ({"tagName": "TEXTAREA"}, True),
    # number: .value= turns letters into "" → the OSK buffer and the field
    # would disagree, so it is left to its own spin buttons.
    ({"tagName": "INPUT", "type": "number"}, False),
    ({"tagName": "INPUT", "type": "checkbox"}, False),
    ({"tagName": "INPUT", "type": "range"}, False),
    ({"tagName": "INPUT", "type": "hidden"}, False),
    ({"tagName": "INPUT", "type": "file"}, False),
    ({"tagName": "INPUT", "type": "submit"}, False),
    ({"tagName": "INPUT", "type": "text", "readOnly": True}, False),
    ({"tagName": "INPUT", "type": "text", "disabled": True}, False),
    ({"tagName": "TEXTAREA", "readOnly": True}, False),
    ({"tagName": "SELECT"}, False),
    ({"tagName": "BUTTON"}, False),
    ({"tagName": "DIV"}, False),
    ({"tagName": "BODY"}, False),
    (None, False),
    ({}, False),
]


@needs_node
def test_is_osk_input():
    out = _eval(inputs=[el for el, _ in INPUTS])["inputs"]
    for (el, expected), got in zip(INPUTS, out):
        assert got is expected, f"isOskInput({el}) = {got}"


# ── keyboard.js ↔ themes.css ─────────────────────────────────────────────

def test_css_variables_match_between_js_and_css():
    js = KEYBOARD_JS.read_text(encoding="utf-8")
    css = THEMES_CSS.read_text(encoding="utf-8")
    set_in_js = set(re.findall(r'setProperty\("(--osk-[a-z-]+)"', js))
    read_in_css = set(re.findall(r"var\((--osk-[a-z-]+)", css))
    assert set_in_js == {"--osk-h", "--osk-pad", "--osk-gap", "--osk-font"}
    assert read_in_css == set_in_js


def test_css_sizes_the_keyboard_from_the_variables():
    css = THEMES_CSS.read_text(encoding="utf-8")

    def rule(selector):
        m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
        assert m, f"no rule for {selector}"
        return re.sub(r"\s+", "", m.group(1))

    overlay = rule("#osk-overlay")
    for decl in ("height:var(--osk-h", "max-height:100dvh", "box-sizing:border-box",
                 "overflow:hidden", "padding:var(--osk-pad", "gap:var(--osk-gap",
                 "position:fixed", "bottom:0"):
        assert decl in overlay, decl
    row = rule("#osk-overlay .osk-row")
    assert "flex:110" in row and "min-height:0" in row
    key = rule("#osk-overlay .osk-key")
    assert "height:100%" in key and "font-size:var(--osk-font" in key and "line-height:1" in key
    icon = rule("#osk-overlay .osk-key .material-symbols-outlined")
    assert "font-size:calc(var(--osk-font" in icon
    # The content padding follows the keyboard height, not a fixed 54vh.
    pad = rule("body.osk-open .content-area")
    assert "padding-bottom:calc(var(--osk-h" in pad
    assert "54vh" not in css


def test_keyboard_markup_has_no_rem_sizes():
    """The rem classes overflowed the panel once the root font went to 17 px;
    sizes now come only from the --osk-* variables."""
    js = KEYBOARD_JS.read_text(encoding="utf-8")
    m = re.search(r"function _render\(overlay\) \{(.*?)\n    \}\n", js, re.S)
    assert m
    body = m.group(1)
    for cls in ("p-3", "gap-2", "gap-1.5", "mb-1", "py-2", "text-lg", "text-base", "text-sm"):
        assert not re.search(r"[\s\"'`]" + re.escape(cls) + r"[\s\"'`]", body), cls
    assert "height:50vh" not in js
    assert "font-size:22px" not in body
    # scrollIntoView({block: "center"}) left the field under the keyboard.
    assert not re.search(r"\.scrollIntoView\(", js)


# ── behaviour ────────────────────────────────────────────────────────────

@needs_node
def test_dom_behaviour():
    res = subprocess.run([NODE, str(JS / "osk_dom_smoke.js")], capture_output=True,
                         text=True, timeout=60)
    assert res.returncode == 0, res.stderr or res.stdout
    assert res.stdout.strip().endswith("ok")


# pytest.ini's 60 s per-test limit is too tight for six browser runs on a
# slow host (~20 s here). The subprocess limit stays below this mark, so a
# hang ends in TimeoutExpired — node killed cleanly, a readable failure —
# rather than pytest-timeout killing the test with node still running.
@needs_node
@pytest.mark.timeout(240)
def test_real_dashboard_in_chromium():
    res = subprocess.run([NODE, str(JS / "osk_browser_smoke.js")], capture_output=True,
                         text=True, timeout=200)
    out = res.stdout.strip()
    if res.returncode == 0 and out.startswith("SKIP:"):
        pytest.skip(out[5:].strip())
    assert res.returncode == 0, res.stderr or res.stdout
    assert out.endswith("ok"), out
