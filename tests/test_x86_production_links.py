"""Lokalne linki w docs/x86-production/*.html muszą prowadzić do istniejących stron i kotwic.

Pasek boczny i nawigacja „poprzednia / następna” były kopiowane między
stronami i wskazywały pliki ze starego podziału rozdziałów (02-power.html,
08-kiosk.html, …), których już nie ma. Ten test łapie takie martwe linki
oraz pilnuje, żeby każda strona miała pełny, jednakowy spis rozdziałów.
"""

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parent.parent / "docs" / "x86-production"
PAGES = sorted(DOCS.glob("*.html"))


class _Collector(HTMLParser):
    """Zbiera atrybuty href i id oraz linki z paska bocznego (<aside><nav>)."""

    def __init__(self):
        super().__init__()
        self.hrefs, self.ids, self.sidebar = [], set(), []
        self._aside = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "aside":
            self._aside += 1
        if "id" in a:
            self.ids.add(a["id"])
        if tag == "a" and a.get("href"):
            self.hrefs.append(a["href"])
            if self._aside:
                self.sidebar.append(a["href"])

    def handle_endtag(self, tag):
        if tag == "aside":
            self._aside -= 1


def _parse(path):
    c = _Collector()
    c.feed(path.read_text(encoding="utf-8"))
    return c


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_local_links_resolve(page):
    parsed = {p.name: _parse(p) for p in PAGES}
    broken = []
    for href in parsed[page.name].hrefs:
        if re.match(r"^[a-z][a-z0-9+.-]*:", href):    # http:, mailto: itd. — poza zakresem
            continue
        path, _, frag = href.partition("#")
        target = (page.parent / path).resolve() if path else page
        if not target.exists():
            broken.append(href)
        elif frag and target.suffix == ".html":
            ids = parsed[target.name].ids if target.parent == DOCS else _parse(target).ids
            if frag not in ids:
                broken.append(href)
    assert not broken, f"{page.name}: martwe linki {broken}"


def test_sidebar_identical_and_complete():
    expected = [p.name for p in PAGES]
    expected.remove("index.html")
    expected.insert(0, "index.html")
    for page in PAGES:
        assert _parse(page).sidebar == expected, f"{page.name}: pasek boczny niezgodny ze spisem stron"
