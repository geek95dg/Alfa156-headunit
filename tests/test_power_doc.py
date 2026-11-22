"""Consistency guards for docs/ZASILANIE_BUFOROWANE.md (the buffered power
reference). The document was rewritten for the 20 V potted step-up, two
XY-SK120 chargers and the bank in two baskets in the trunk; these checks keep
the parts that are easy to break on the next edit from drifting back:

* every in-page link (the table of contents, cross references) and every
  relative link resolves;
* the top-level sections are numbered in order and each ``### N.x`` sits under
  its own ``## N.`` (the old §5 had 5.1, 5.2, 5.5, 5.6, 5.3a …);
* every ``§N.x`` reference points at a heading that exists;
* the superseded hardware (XL6019, MBR2545CT, bank under the seat) appears only
  in an explicitly historical sentence, never as the current design.

The checks only read files; nothing is written anywhere.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DOC = REPO / "docs" / "ZASILANIE_BUFOROWANE.md"

FENCE_RE = re.compile(r"^```.*?^```[ \t]*$", re.M | re.S)
HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*$", re.M)
LINK_RE = re.compile(r"\]\(([^)\s]+)\)")
#: "§4.3", "§ 11", "§3.5a", "§8a.2" — but not "PCB §7" / "WDROZENIE_TESTOWE.md §3.1a",
#: which point into other documents.
SECTION_REF_RE = re.compile(r"(?<![\w.`)])(?<!\) )(?<!` )(?<!PCB )§ ?(\d+a?(?:\.\d+[a-z]?)?)")
#: Words that mark a passage as history ("the previous edition used …"). Kept
#: specific on purpose: a generic word such as "zamiast" would let a sentence
#: that presents old hardware as current slip through.
HISTORY_MARKERS = ("poprzedni", "wcześniej", "dawn", "zastąpi", "stary", "starsz",
                   "nie kupuj", "wypadły", "mogą jeszcze", "nie jest potrzebna",
                   "nie potrzeba")


def _text() -> str:
    return DOC.read_text(encoding="utf-8")


def _prose() -> str:
    return FENCE_RE.sub("", _text())


def _slug(heading: str) -> str:
    """GitHub's anchor for a heading (same rule as tests/test_docs_refs.py)."""
    text = heading.replace("`", "").strip().lower()
    kept = "".join(ch for ch in text
                   if ch in " -_" or unicodedata.category(ch)[0] in "LMN")
    return kept.replace(" ", "-")


def _headings() -> list[tuple[int, str]]:
    return [(len(h), t) for h, t in HEADING_RE.findall(_prose())]


def _section_numbers() -> set[str]:
    nums = set()
    for _, title in _headings():
        m = re.match(r"(\d+a?(?:\.\d+[a-z]?)?)[. ]", title)
        if m:
            nums.add(m.group(1).rstrip("."))
    return nums


def test_links_and_anchors_resolve():
    anchors = {_slug(t) for _, t in _headings()}
    bad = []
    for target in LINK_RE.findall(_prose()):
        if re.match(r"^[a-z]+://", target):
            continue
        path, _, anchor = target.partition("#")
        if path and not (DOC.parent / path).exists():
            bad.append(target)
        elif not path and anchor and anchor not in anchors:
            bad.append(target)
    assert not bad, f"linki donikąd: {bad}"


def test_sections_numbered_in_order():
    tops, current, subs_ok = [], None, []
    for level, title in _headings():
        m = re.match(r"(\d+)(a?)\.(\d+)?", title)
        if not m:
            continue
        if level == 2:
            num = int(m.group(1))
            if not m.group(2):
                tops.append(num)
            current = m.group(1) + m.group(2)
        elif level == 3 and m.group(3) is not None:
            subs_ok.append((current, m.group(1) + m.group(2), title))
    assert tops == list(range(1, len(tops) + 1)), f"numeracja rozdziałów: {tops}"
    wrong = [t for parent, own, t in subs_ok if parent != own]
    assert not wrong, f"podrozdziały pod obcym rozdziałem: {wrong}"
    minor = {}
    for level, title in _headings():
        m = re.match(r"(\d+a?)\.(\d+)[ a-z]", title)
        if level == 3 and m:
            minor.setdefault(m.group(1), []).append(int(m.group(2)))
    unordered = {k: v for k, v in minor.items() if v != sorted(v)}
    assert not unordered, f"podrozdziały nie po kolei: {unordered}"


def test_section_references_exist():
    nums = _section_numbers()
    missing = sorted({ref for ref in SECTION_REF_RE.findall(_prose())
                      if ref not in nums and ref.split(".")[0] not in nums})
    assert not missing, f"odsyłacze do nieistniejących sekcji: {missing}"
    # A sub-section reference must hit the exact sub-section, not only its chapter.
    sub_missing = sorted({ref for ref in SECTION_REF_RE.findall(_prose())
                          if "." in ref and ref not in nums})
    assert not sub_missing, f"odsyłacze do nieistniejących podrozdziałów: {sub_missing}"


def _passages(prose: str) -> list[str]:
    """Blank-line separated paragraphs; a table is split into its rows.

    The history marker has to sit in the same paragraph (or the same table
    row) as the old part name. A fixed character window would accept a marker
    from the neighbouring sentence or row.
    """
    out = []
    for para in re.split(r"\n[ \t>]*\n", prose):
        lines = para.splitlines()
        if lines and all(ln.lstrip("> ").startswith("|") for ln in lines if ln.strip()):
            out.extend(lines)
        else:
            out.append(para)
    return out


def test_superseded_hardware_only_as_history():
    # Same retired list as the guard for the other documents, so XL4016,
    # MBR2045, "Domena B" and "4-6 ×" cannot creep back into ZB either.
    from tests.test_power_docs import RETIRED
    offenders = []
    for passage in _passages(_prose()):
        low = passage.lower()
        for word, rx in RETIRED.items():
            if rx.search(passage) and not any(m in low for m in HISTORY_MARKERS):
                offenders.append(f"{word}: {passage.strip()[:90]!r}")
    assert not offenders, f"stary sprzęt opisany jak obecny: {offenders}"


def test_current_design_numbers_present():
    text = _text()
    for needle in ("12 → 20 V", "2 × XY-SK120", "CV 14,40 V, CC 5,0 A",
                   "kosze_HR1221W_4+3.pdf", "FLRY-B 2,5 mm²", "6 mm² (10 AWG)",
                   "nie wierć podłogi bagażnika"):
        assert needle in text, f"brak: {needle!r}"
