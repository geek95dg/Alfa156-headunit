"""Guards for the HTML documentation (``bcm_v85_docs.html`` and
``docs/x86-production/*.html``).

These pages were written for the retired ARM build (Orange Pi, Li-ion 18650
backup, 4-6 SLA packs behind a Schottky and a buck charger, an ignition relay
switching a "Domain B", DIY TDA amplifiers) and later corrected to the
current design, whose authority is ``docs/ZASILANIE_BUFOROWANE.md`` (ZB)
and ``docs/WDROZENIE_M910Q.md``. A reader who opens an HTML page instead of
the Markdown would otherwise wire the wrong car, so:

* every HTML file in the repo must parse with balanced tags — a stray
  ``</p>`` or an unescaped ``<mac>`` silently swallows the text after it in
  some browsers;
* in the documentation pages a retired part or claim may appear **only**
  inside an element with class ``historical`` / ``box-historical``, and each
  such block must say "Historyczne (nieaktualne)" so it cannot be mistaken
  for a current instruction (no keyword exemptions here, unlike the
  Markdown guard: the HTML has a dedicated, visible history block);
* the power facts the pages repeat must match their sources: the AGM
  thresholds of ``src/power/battery.py`` and the sections of ZB they cite.

The checks only read files; nothing is written anywhere.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

from src.power.battery import DEFAULTS as BATTERY_DEFAULTS
from tests.test_power_docs import AFTER_RE, BEFORE_RE, RETIRED, SEC, _zb_sections

REPO = Path(__file__).resolve().parent.parent

#: Pages that describe the hardware. Mock-ups and the dashboard UI are only
#: parsed, not scanned for parts.
DOC_PAGES = [REPO / "bcm_v85_docs.html"] + sorted(
    (REPO / "docs" / "x86-production").glob("*.html"))
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv"}
ALL_HTML = sorted(p for p in REPO.rglob("*.html")
                  if not _SKIP_DIRS & set(p.relative_to(REPO).parts))

HIST_CLASSES = {"historical", "box-historical"}
HIST_LABEL = "Historyczne (nieaktualne)"

#: The Markdown guard's list plus what only the HTML ever described.
RETIRED_HTML = {
    **RETIRED,
    "Orange Pi / OPi": re.compile(r"orange\s*pi|\bOPi\b", re.I),
    "RK3588": re.compile(r"RK3588"),
    "18650": re.compile(r"\b18650\b"),
    "TP4056": re.compile(r"TP4056"),
    "MT3608": re.compile(r"MT3608"),
    "Li-ion": re.compile(r"\bLi-ion\b", re.I),
    "TDA7388": re.compile(r"TDA7388"),
    "TDA2050": re.compile(r"TDA2050"),
    "SLA": re.compile(r"\bSLA\b"),
    "single AGM": re.compile(r"single\s+AGM", re.I),
    "19,5 V": re.compile(r"\b19[,.]5\s*V\b"),
    "under the passenger seat (bank)": re.compile(
        r"(bank|batter\w*)[^.]{0,60}under the passenger seat", re.I),
}

#: Stale data that may appear only as release history: rows of a
#: ``.changelog`` table describe the hardware of the day they shipped
#: (4.3" second screen, ARM GPIO pins).  Anywhere else outside a historical
#: block they would read as the current design, which has no GPIO header.
RETIRED_OUTSIDE_CHANGELOG = {
    '4.3" display': re.compile(r'\b4[.,]3\s*(?:"|″|”|cal|inch)', re.I),
    "ARM GPIO pin": re.compile(r"\bGPIO\s*\d+"),
}
RELEASE_CLASSES = {"changelog"}

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
        "meta", "source", "track", "wbr", "param"}
#: Raw-text elements: CSS colour names ("orange") are not prose.
RAW = {"style", "script"}


class _DocParser(HTMLParser):
    """Checks tag balance and splits text into current / historical."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, int, bool, bool]] = []
        # ^ tag, line, opens historical block, opens changelog
        self.errors: list[str] = []
        self.current: list[tuple[int, str]] = []       # (line, text)
        self.release: set[int] = set()                 # indices into current
        self.hist_blocks: list[tuple[int, list[str]]] = []
        self._hist_depth = 0
        self._raw_depth = 0
        self._release_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in VOID:
            return
        classes = set((dict(attrs).get("class") or "").split())
        opens = bool(classes & HIST_CLASSES)
        if opens:
            if self._hist_depth == 0:
                self.hist_blocks.append((self.getpos()[0], []))
            self._hist_depth += 1
        rel = bool(classes & RELEASE_CLASSES)
        self._release_depth += rel
        if tag in RAW:
            self._raw_depth += 1
        self.stack.append((tag, self.getpos()[0], opens, rel))

    def handle_endtag(self, tag):
        line = self.getpos()[0]
        if tag in VOID:
            return
        if not self.stack:
            self.errors.append(f"line {line}: stray </{tag}>")
            return
        top, start, opens, rel = self.stack[-1]
        if top != tag:
            self.errors.append(
                f"line {line}: </{tag}> closes <{top}> opened at line {start}")
            return
        self.stack.pop()
        if opens:
            self._hist_depth -= 1
        self._release_depth -= rel
        if tag in RAW:
            self._raw_depth -= 1

    def handle_data(self, data):
        if self._raw_depth or not data.strip():
            return
        if self._hist_depth:
            self.hist_blocks[-1][1].append(data)
        else:
            if self._release_depth:
                self.release.add(len(self.current))
            self.current.append((self.getpos()[0], data))

    def close(self):
        super().close()
        for tag, line, *_ in self.stack:
            self.errors.append(f"line {line}: <{tag}> never closed")


def _parse(path: Path) -> _DocParser:
    p = _DocParser()
    p.feed(path.read_text(encoding="utf-8"))
    p.close()
    return p


def _current_text(p: _DocParser) -> str:
    return " ".join(t for _, t in p.current)


def _retired_hits(path: Path, base: Path = REPO) -> list[str]:
    p = _parse(path)
    hits = []
    for i, (line, text) in enumerate(p.current):
        rules = dict(RETIRED_HTML)
        if i not in p.release:
            rules.update(RETIRED_OUTSIDE_CHANGELOG)
        for name, rx in rules.items():
            if rx.search(text):
                hits.append(f"{path.relative_to(base)}:{line}: {name!r} w: "
                            f"{' '.join(text.split())[:110]}")
    # A retired claim split over two inline elements ("4-6 <b>×</b>") would
    # slip through the per-node scan; catch it on the joined text too.
    joined = " ".join(_current_text(p).split())
    for name, rx in RETIRED_HTML.items():
        if rx.search(joined) and not any(f"{name!r}" in h for h in hits):
            hits.append(f"{path.relative_to(base)}: {name!r} (across tags)")
    return hits


# ------------------------------------------------------------------ parsing

@pytest.mark.parametrize("path", ALL_HTML, ids=lambda p: str(p.relative_to(REPO)))
def test_html_parses_with_balanced_tags(path):
    errors = _parse(path).errors
    assert not errors, f"{path.relative_to(REPO)}:\n" + "\n".join(errors[:10])


def test_doc_pages_are_found():
    names = {p.name for p in DOC_PAGES}
    assert {"bcm_v85_docs.html", "index.html", "01-bom.html", "02-assembly.html",
            "10-power-suspend.html"} <= names
    assert all(p.exists() for p in DOC_PAGES)


# ------------------------------------------------------------ retired parts

@pytest.mark.parametrize("path", DOC_PAGES, ids=lambda p: str(p.relative_to(REPO)))
def test_no_retired_parts_outside_historical_blocks(path):
    hits = _retired_hits(path)
    assert not hits, ("wycofany sprzęt albo twierdzenie poza blokiem "
                      f"„{HIST_LABEL}”:\n" + "\n".join(hits))


@pytest.mark.parametrize("path", DOC_PAGES, ids=lambda p: str(p.relative_to(REPO)))
def test_historical_blocks_are_labelled(path):
    bad = [f"{path.relative_to(REPO)}:{line}"
           for line, texts in _parse(path).hist_blocks
           if HIST_LABEL not in " ".join(" ".join(texts).split())]
    assert not bad, f"blok historyczny bez etykiety „{HIST_LABEL}”: {bad}"


def test_guard_flags_current_claim_and_spares_history(tmp_path):
    """The guard itself: a current-looking sentence is flagged, the same
    words inside a labelled historical block are not, and an unlabelled
    historical block is reported."""
    page = tmp_path / "x.html"
    page.write_text(
        "<!DOCTYPE html><html><head><style>.a{color:orange}</style></head><body>"
        "<p>M910q zasila przetwornica XL6019.</p>"
        "<p>Bufor 4-6 <b>× SLA</b>.</p>"
        "<div class=\"box box-historical\"><div class=\"box-title\">"
        "Historyczne (nieaktualne)</div><p>Orange Pi, TDA7388, Domain B.</p></div>"
        "<div class=\"historical\">TP4056</div>"
        "<!-- Orange Pi in a comment is not prose -->"
        "</body></html>", encoding="utf-8")
    hits = _retired_hits(page, tmp_path)
    assert any("XL6019" in h for h in hits), hits
    assert any("SLA" in h for h in hits), hits
    assert any("4-6" in h for h in hits), hits      # split over <b>
    assert not any("Orange" in h or "TDA" in h or "Domena" in h for h in hits), hits
    p = _parse(page)
    assert [HIST_LABEL in " ".join(t) for _, t in p.hist_blocks] == [True, False]


def test_guard_allows_old_displays_and_gpio_only_in_changelog(tmp_path):
    page = tmp_path / "x.html"
    page.write_text(
        "<div class=\"changelog\"><table><tr><td>Mały ekran 4.3\"</td>"
        "<td>GPIO 89</td></tr></table></div>"
        "<p>Drzwi: GPIO 86.</p><p>Drugi ekran 4,3\" HDMI.</p>",
        encoding="utf-8")
    hits = _retired_hits(page, tmp_path)
    assert len(hits) == 2, hits
    assert all(":1:" in h for h in hits) and any("GPIO" in h for h in hits), hits


#: udev matches idVendor/idProduct as exactly four hex digits; a value
#: mangled by a search-and-replace silently never matches.
_UDEV_ID_RE = re.compile(r'ATTRS\{id(?:Vendor|Product)\}=="([^"]*)"')


@pytest.mark.parametrize("path", ALL_HTML, ids=lambda p: str(p.relative_to(REPO)))
def test_udev_usb_ids_are_four_hex_digits(path):
    bad = [v for v in _UDEV_ID_RE.findall(path.read_text(encoding="utf-8"))
           if not re.fullmatch(r"[0-9a-f]{4}", v)]
    assert not bad, f"{path.relative_to(REPO)}: zły idVendor/idProduct: {bad}"


def test_parser_reports_unbalanced_tags(tmp_path):
    page = tmp_path / "x.html"
    page.write_text("<div><p>a</div><code>wlx<mac></code>", encoding="utf-8")
    errors = _parse(page).errors
    assert len(errors) >= 2, errors


# ------------------------------------------------------- facts vs. sources

def test_battery_thresholds_match_battery_py():
    """bcm_v85_docs.html §14 and 10-power-suspend.html quote the AGM
    thresholds of BatteryMonitor; they must be the ones in the code."""
    expected = [BATTERY_DEFAULTS[k] for k in ("full_v", "nominal_v", "low_v",
                                              "critical_v")]
    for path, dec in ((REPO / "bcm_v85_docs.html", ","),
                      (REPO / "docs" / "x86-production" / "10-power-suspend.html", ".")):
        text = " ".join(_current_text(_parse(path)).split())
        for v in expected:
            assert f"{v:.2f}".replace(".", dec) in text, (path.name, v)


@pytest.mark.parametrize("name", ["bcm_v85_docs.html", "02-assembly.html",
                                  "10-power-suspend.html", "01-bom.html"])
def test_power_pages_describe_current_bank_and_modules(name):
    path = next(p for p in DOC_PAGES if p.name == name)
    text = " ".join(_current_text(_parse(path)).split())
    for must in ("HR1221W", "XY-SK120", "XH-M603", "XH-M609", "20 V"):
        assert must in text, (name, must)
    assert re.search(r"35[,.]7\s*Ah", text), name
    assert re.search(r"\b7\s*(×|x|in parallel|szt)", text) or "7×" in text, name


@pytest.mark.parametrize("path", DOC_PAGES, ids=lambda p: str(p.relative_to(REPO)))
def test_references_into_zb_resolve(path):
    nums = _zb_sections()
    text = _current_text(_parse(path))
    bad = []
    for m in AFTER_RE.finditer(text):
        bad += [s for s in re.findall(r"§\s?(" + SEC + r")", m.group(1))
                if s not in nums]
    bad += [s for s in BEFORE_RE.findall(text) if s not in nums]
    assert not bad, f"{path.name}: odsyłacze do nieistniejących sekcji ZB: {bad}"
