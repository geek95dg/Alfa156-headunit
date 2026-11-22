"""Consistency guards for every document that repeats the buffered power design.

``docs/ZASILANIE_BUFOROWANE.md`` (ZB) is the authority for the power system
and has its own guard (``tests/test_power_doc.py``). The other Markdown files
and the two schematic generators repeat parts of it — and after the redesign
(20 V potted step-up, two XY-SK120 chargers, the bank on cable in two baskets
in the trunk) they drifted badly: an XL6019 still "feeding the M910q", a buck
XL4016 as the charger, the bank "under the passenger seat", "4-6 ×" packs,
an ignition-relay "Domena B". A reader who lands on the wrong file wires the
wrong car. These checks keep that from coming back:

* a retired part or claim may appear only in a passage that is explicitly
  historical ("poprzedni", "dawny", "wypadł", "superseded", …) or under a
  "Czego nie kupować" heading — never as the current design;
* every ``§N.x`` that points into ZB (``ZB §5.4``,
  ``ZASILANIE_BUFOROWANE.md`) §6.4``, ``§4.3 ZASILANIE_BUFOROWANE``) names a
  section that exists there — ZB was renumbered, and a reference to a
  vanished §5.3c sends the reader nowhere.

The checks only read files; nothing is written anywhere.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
ZB = REPO / "docs" / "ZASILANIE_BUFOROWANE.md"

#: Markdown documents checked: everything in docs/ (ZB has its own guard)
#: plus the schematics index. Archive/ is history by definition.
MD_FILES = sorted(p for p in (REPO / "docs").glob("*.md") if p != ZB) + [
    REPO / "schematics" / "README.md",
]
#: Generators whose strings end up as labels on the drawings.
PY_FILES = [
    REPO / "schematics" / "gen_pcb_power.py",
    REPO / "schematics" / "gen_test_schematics.py",
]

#: Retired hardware and claims of the superseded design.
RETIRED = {
    "XL6019": re.compile(r"XL6019"),
    "XL4016": re.compile(r"XL4016"),
    "MBR2045": re.compile(r"MBR2045"),
    "MBR2545CT": re.compile(r"MBR2545"),
    "pod fotelem": re.compile(r"pod\s+fotelem", re.I),
    "4-6 ×": re.compile(r"\b4\s*[-–]\s*6\s*[×x]"),
    "Domena B (za zapłonem)": re.compile(r"domen[aąy]\s+B\b|\bdomain\s+B\b", re.I),
}

#: Words that mark a passage as history. Kept specific on purpose: a generic
#: word such as "zamiast" would let a sentence that presents old hardware as
#: current slip through.
HISTORY_MARKERS = (
    "poprzedni", "wcześniej", "dawn", "starsz", "nie kupuj", "wypadł",
    "historyczn", "historical", "superseded", "earlier revision",
    "zostaje na półce", "do przerysowania", "porzucon", "posiadanego wtedy",
    "czego nie kupow",
)
#: Short, everyday words that also mark history, but only when they sit next
#: to the retired part itself. Anywhere in a long paragraph they would also
#: exempt an unrelated current-design claim ("stare kable odpadają … M910q
#: zasila XL6019").
NEAR_MARKERS = ("zastąpi", "stary", "stara ", "stare ", "odpada")
NEAR_CHARS = 80
#: Headings under which every row is a "do not buy / history" entry.
HISTORY_HEADINGS = ("czego nie kupow", "historical", "superseded")

FENCE_RE = re.compile(r"^```.*?^```[ \t]*$", re.M | re.S)
HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*$")


def _norm(text: str) -> str:
    return text.replace("*", "").replace("`", "").lower()


def _md_blocks(path: Path) -> list[tuple[int, str, str]]:
    """(line number, block text, nearest heading) — a block is one table row,
    one paragraph / blockquote paragraph / list run, or one code fence."""
    blocks: list[tuple[int, str, str]] = []
    heading = ""
    buf: list[str] = []
    start = 0
    in_fence = False

    def flush():
        nonlocal buf
        if buf:
            blocks.append((start, "\n".join(buf), heading))
        buf = []

    for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("```"):
            if not in_fence:
                flush()
                start, in_fence = no, True
                buf.append(line)
            else:
                buf.append(line)
                in_fence = False
                flush()
            continue
        if in_fence:
            buf.append(line)
            continue
        m = HEADING_RE.match(line)
        if m:
            flush()
            heading = m.group(2)
            blocks.append((no, line, heading))
            continue
        if stripped in ("", ">"):
            flush()
            continue
        if stripped.startswith("|"):
            flush()
            blocks.append((no, line, heading))
            continue
        if not buf:
            start = no
        buf.append(line)
    flush()
    return blocks


def _py_blocks(path: Path) -> list[tuple[int, str, str]]:
    """Each line with the line before it (wrapped string literals)."""
    lines = path.read_text(encoding="utf-8").splitlines()
    return [(no, (lines[no - 2] + "\n" if no > 1 else "") + line, "")
            for no, line in enumerate(lines, 1)]


def _is_historical(block: str, heading: str, rx: re.Pattern) -> bool:
    text = _norm(block)
    if any(m in text for m in HISTORY_MARKERS):
        return True
    if any(h in _norm(heading) for h in HISTORY_HEADINGS):
        return True
    # Every occurrence of the retired part needs its own nearby marker.
    # text is lower-cased by _norm, so match the part case-insensitively.
    spans = [m.span() for m in re.finditer(rx.pattern, text, rx.flags | re.I)]
    return bool(spans) and all(
        any(w in text[max(0, a - NEAR_CHARS):b + NEAR_CHARS] for w in NEAR_MARKERS)
        for a, b in spans)


def _retired_hits(path: Path, base: Path = REPO) -> list[str]:
    blocks = _py_blocks(path) if path.suffix == ".py" else _md_blocks(path)
    hits = []
    for no, block, heading in blocks:
        for name, rx in RETIRED.items():
            if rx.search(block) and not _is_historical(block, heading, rx):
                first = block.strip().splitlines()[-1 if path.suffix == ".py" else 0]
                hits.append(f"{path.relative_to(base)}:{no}: {name!r} w: {first[:110]}")
    return hits


@pytest.mark.parametrize("path", MD_FILES + PY_FILES,
                         ids=lambda p: str(p.relative_to(REPO)))
def test_no_retired_parts_as_current_design(path):
    hits = _retired_hits(path)
    assert not hits, ("wycofany sprzęt albo twierdzenie poza wyraźnie "
                      "historycznym fragmentem:\n" + "\n".join(hits))


def test_markers_catch_a_current_claim(tmp_path):
    """The guard itself: a plain current-design sentence must be flagged and
    the same sentence marked as history must pass."""
    doc = tmp_path / "x.md"
    doc.write_text("# Zasilanie\n\nM910q zasila przetwornica XL6019.\n\n"
                   "Bank stoi pod fotelem pasażera.\n\n"
                   "Poprzednie wydanie używało XL6019.\n\n"
                   "## Czego nie kupować\n\n| XL4016 | buck |\n",
                   encoding="utf-8")
    hits = _retired_hits(doc, tmp_path)
    assert len(hits) == 2, hits
    assert "XL6019" in hits[0] and "pod fotelem" in hits[1]


def test_near_marker_must_sit_next_to_the_part(tmp_path):
    """A weak marker ("odpada", "stare ") far from the retired part does not
    exempt the paragraph; right next to it, it does."""
    doc = tmp_path / "x.md"
    filler = "kabel idzie wzdłuż progu i dalej pod wykładziną do bagażnika " * 3
    doc.write_text("# Zasilanie\n\nStare kable odpadają. " + filler
                   + "M910q zasila XL6019.\n\n"
                   "Stara przetwornica XL6019 odpada.\n", encoding="utf-8")
    hits = _retired_hits(doc, tmp_path)
    assert len(hits) == 1 and ":3:" in hits[0], hits


#: Hand-drawn SVGs without a generator — their text was rewritten by hand to
#: the new design, so nothing but this check stops them drifting back. No
#: history exemption: a drawing shows the current design only.
SVG_FILES = [
    REPO / "schematics" / "power_buffered_m910q.svg",
    REPO / "schematics" / "vehicle_layout_m910q.svg",
]
SVG_RETIRED = {**RETIRED, "19,5 V": re.compile(r"\b19[,.]5\s*V")}


def _svg_text(path: Path) -> str:
    import html
    raw = path.read_text(encoding="utf-8")
    parts = re.findall(r"<text\b[^>]*>(.*?)</text>", raw, re.S)
    return "\n".join(html.unescape(re.sub(r"<[^>]+>", "", p)) for p in parts)


@pytest.mark.parametrize("path", SVG_FILES, ids=lambda p: p.name)
def test_hand_drawn_svgs_show_current_design(path):
    text = _svg_text(path)
    assert text.strip(), f"{path.name}: brak elementów <text>"
    bad = [name for name, rx in SVG_RETIRED.items() if rx.search(text)]
    assert not bad, f"{path.name}: wycofany sprzęt na rysunku: {bad}"


# ---------------------------------------------------------------- §-refs

SEC = r"\d+a?(?:\.\d+[a-z]?)?"
#: "ZB §5.2–§5.4, §6.3", "ZASILANIE_BUFOROWANE.md`) §6.4 pkt 6",
#: "ZASILANIE_BUFOROWANE.md § 11" — the anchor followed by a run of §-refs.
AFTER_RE = re.compile(
    r"(?:\bZB|ZASILANIE_BUFOROWANE\.md`?\)?|ZASILANIE_BUFOROWANE\b)\s*"
    r"((?:§\s?" + SEC + r"(?:\s*(?:,|i|oraz|and|–|-)\s*)?)+)")
#: "§4.3 [`ZASILANIE_BUFOROWANE.md`]", "§4.7 ZASILANIE_BUFOROWANE".
BEFORE_RE = re.compile(r"§\s?(" + SEC + r")\s+(?:\[`)?ZASILANIE_BUFOROWANE")


def _zb_sections() -> set[str]:
    nums = set()
    for line in FENCE_RE.sub("", ZB.read_text(encoding="utf-8")).splitlines():
        m = HEADING_RE.match(line)
        if m:
            n = re.match(r"(" + SEC + r")[. ]", m.group(2))
            if n:
                nums.add(n.group(1).rstrip("."))
    return nums


def _zb_refs(path: Path) -> list[tuple[int, str]]:
    refs = []
    for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        for m in AFTER_RE.finditer(line):
            refs += [(no, s) for s in re.findall(r"§\s?(" + SEC + r")", m.group(1))]
        refs += [(no, s) for s in BEFORE_RE.findall(line)]
    return refs


def test_zb_has_sections():
    nums = _zb_sections()
    assert {"3.4", "4.3", "4.7", "5.4", "6.4", "8.1", "8a.2", "11"} <= nums


@pytest.mark.parametrize("path", MD_FILES + PY_FILES,
                         ids=lambda p: str(p.relative_to(REPO)))
def test_references_into_zb_resolve(path):
    nums = _zb_sections()
    bad = [f"{path.relative_to(REPO)}:{no}: §{sec}"
           for no, sec in _zb_refs(path) if sec not in nums]
    assert not bad, "odsyłacze do nieistniejących sekcji ZB:\n" + "\n".join(bad)
