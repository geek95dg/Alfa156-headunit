"""The owner's guides may only name things that exist in the code.

``docs/WDROZENIE_TESTOWE_TELEFON.md`` and ``docs/PRZYGOTOWANIE_TELEFONU.md``
are copy-paste instructions for the car (Polish, one command per ```bash
block). A renamed script, a dropped agent flag, a module toggle that no
longer exists or a Settings label that changed sends the owner down a dead
end in a parked car, with no developer around — so every such reference is
checked against the code here:

* repo paths in backticks and code blocks (``config/…``, ``tools/…``,
  ``src/…``, ``docs/…``, ``arduino/…``, also under ``/opt/bcm/``) exist,
  except runtime files that are git-ignored by design (``config/local.yaml``);
  relative Markdown links and in-page anchors resolve;
* every ``modules.<name>`` and every toggle in a YAML ``modules:`` block is
  a catalog key, and the module table of the guide matches the catalog
  (requirements, every add-on listed) and both shipped configs (defaults);
* every flag given to ``bcm_agent.py``, ``migrate_local_config.py`` or
  ``main.py`` exists in its argparse (read from the source with ``ast`` —
  nothing is imported or run), flags of the shell scripts appear in them;
* every ```bash block parses (``bash -n`` reads stdin and never executes
  anything) unless it holds a ``<placeholder>``, none has a ``$`` prompt;
  nothing the owner can copy (block or inline code) can place a real
  emergency call or holds a dialable phone number (examples are
  ``+48XXXXXXXXX``, which every validator rejects); every ```yaml block
  parses;
* Settings labels quoted as „…” after „Ustawienia →” or „wiersz” are real
  Polish UI strings from ``src/dashboard/i18n.py``.

The 112 and phone-number checks also cover the technical references the
guides link to (``docs/WDROZENIE_TESTOWE.md``, ``docs/ZASILANIE_BUFOROWANE.md``).

The checks only read files; nothing is written anywhere.
"""

from __future__ import annotations

import ast
import functools
import re
import shutil
import subprocess
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

from src.core.config import BCMConfig
from src.core.modules_catalog import MODULES, is_enabled, requirement_groups

REPO = Path(__file__).resolve().parent.parent
DOCS = ("docs/WDROZENIE_TESTOWE_TELEFON.md", "docs/PRZYGOTOWANIE_TELEFONU.md")
#: The technical references both guides link to (the 112 test, the parking
#: guard, the buffered build). Not copy-paste guides — paths, flags and
#: labels are not checked there — but the owner copies from them too, so
#: nothing copyable in them may dial the real 112 or hold a dialable number.
REFERENCE_DOCS = ("docs/WDROZENIE_TESTOWE.md", "docs/ZASILANIE_BUFOROWANE.md")
GUARDED_DOCS = DOCS + REFERENCE_DOCS

#: Git-ignored files BCM (or the owner) creates on the car — they cannot be
#: in the repository, but the guides must talk about them.
RUNTIME_PATHS = frozenset({
    "config/local.yaml",
    "config/local.yaml.bak",
    "config/local-temp.yaml",
    # backup migrate_local_config.py writes when it moves local.yaml to a
    # new base (bcm_config_test.yaml → bcm_config.yaml)
    "config/local.yaml.bcm_config_test.bak",
})

#: Tools whose flags the guides give; python ones are parsed with ast.
PY_TOOLS = {
    "bcm_agent.py": REPO / "tools" / "car_phone" / "termux" / "bcm_agent.py",
    "migrate_local_config.py": REPO / "tools" / "migrate_local_config.py",
    "main.py": REPO / "main.py",
}
SH_TOOLS = {
    "bcm-harden.sh": REPO / "config" / "scripts" / "bcm-harden.sh",
    "apply-fixes.sh": REPO / "config" / "scripts" / "apply-fixes.sh",
    "install-openauto.sh": REPO / "config" / "scripts" / "install-openauto.sh",
    "cleanup-x86.sh": REPO / "config" / "scripts" / "cleanup-x86.sh",
    "setup-x86.sh": REPO / "config" / "scripts" / "setup-x86.sh",
    "bcm-audio-diag.sh": REPO / "tools" / "bcm-audio-diag.sh",
}

#: The heading of the module table in the main guide.
MODULE_TABLE_HEADING = "## 8. Przełączniki modułów"

FENCE_RE = re.compile(
    r"^(?P<indent>[ \t]*)```(?P<lang>[\w+-]*)[ \t]*\n(?P<body>.*?)^(?P=indent)```[ \t]*$",
    re.M | re.S)
INLINE_RE = re.compile(r"`([^`\n]+)`")
PATH_RE = re.compile(r"(?<![\w.~/-])(?:/opt/bcm/)?((?:config|tools|src|docs|arduino)/[\w./-]*)")
LINK_RE = re.compile(r"\]\(([^)\s]+)\)")
HEADING_RE = re.compile(r"^#{1,6}[ \t]+(.+?)[ \t]*$", re.M)
MODULE_REF_RE = re.compile(r"(?<![\w.])modules\.([A-Za-z_][A-Za-z0-9_]*)")
FLAG_RE = re.compile(r"(?<![\w-])(--?[A-Za-z][\w-]*)")
PLACEHOLDER_RE = re.compile(r"<[^<>\n]+>")
#: „Ustawienia → „Agent w telefonie”” / „wiersz „Postój”” — BCM UI labels.
LABEL_RE = re.compile(r"(?:Ustawienia\s*→\s*|wiersz[a-z]*\s+)„([^”\n]+)”")
#: Emergency numbers (EU 112, Polish 997/998/999, 911 forwarded to 112).
_EMERGENCY = r"(?:112|911|997|998|999)"
#: Anything copyable that could dial the real emergency number: a tel: URI,
#: Android's CALL intent (am start …), Termux's dialer with an emergency
#: number. The agent's fixed 112 intent lives in its code, never in a doc
#: (neither the guides nor the reference docs, :data:`GUARDED_DOCS`).
REAL_112_RE = re.compile(
    r"tel:\+?" + _EMERGENCY + r"\b"
    r"|android\.intent\.action\.CALL\b|\bACTION_CALL\b"
    r"|\bam\s+start\b[^\n]*\bCALL\b"
    r"|termux-telephony-call\s+['\"]?\+?" + _EMERGENCY + r"\b")
#: BCM's own dial route: from 127.0.0.1 it dials ANY number (emergency ones
#: included — the 403 is only for the network), so no copy-paste block may
#: call it, and no inline snippet may curl it.
DIAL_ROUTE_RE = re.compile(r"/api/phone/dial\b")
#: A dialable E.164 number. Examples in the guides must be placeholders the
#: validators reject (+48XXXXXXXXX): a realistic one pasted unchanged sends
#: park alarms / the 112 test call to a stranger.
E164_LITERAL_RE = re.compile(r"\+[1-9][0-9]{7,14}\b")


@dataclass(frozen=True)
class Doc:
    name: str
    text: str
    blocks: tuple[tuple[str, str], ...]   # (language, de-indented body)
    inline: tuple[str, ...]               # inline code spans outside blocks


def _dedent(body: str, indent: str) -> str:
    return "\n".join(line[len(indent):] if line.startswith(indent) else line
                     for line in body.splitlines())


@functools.lru_cache(maxsize=None)
def _doc(name: str) -> Doc:
    text = (REPO / name).read_text(encoding="utf-8")
    blocks = tuple((m["lang"].lower(), _dedent(m["body"], m["indent"]))
                   for m in FENCE_RE.finditer(text))
    rest = FENCE_RE.sub("", text)
    return Doc(name, text, blocks, tuple(INLINE_RE.findall(rest)))


def _code_texts(doc: Doc) -> list[str]:
    """Every piece of code the owner may copy: inline spans and blocks."""
    return [*doc.inline, *(body for _, body in doc.blocks)]


def _command_lines(doc: Doc) -> list[str]:
    lines = list(doc.inline)
    for lang, body in doc.blocks:
        if lang in ("bash", "sh", "shell", ""):
            lines.extend(body.splitlines())
    return lines


def _bash_blocks(doc: Doc) -> list[str]:
    return [body for lang, body in doc.blocks if lang in ("bash", "sh", "shell")]


@functools.lru_cache(maxsize=None)
def _py_flags(path: Path) -> frozenset:
    """Option strings of every ``add_argument`` call in the file — read with
    ast, so the tool is never imported or executed."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    flags = {"-h", "--help"}
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument"):
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str) \
                        and arg.value.startswith("-"):
                    flags.add(arg.value)
    return frozenset(flags)


@functools.lru_cache(maxsize=None)
def _sh_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _tool_flags(tool: str) -> set[str] | None:
    """Known flags of a tool, or None for a shell script (checked by text)."""
    if tool in PY_TOOLS:
        return set(_py_flags(PY_TOOLS[tool]))
    return None


def _all_known_flags() -> set[str]:
    flags: set[str] = set()
    for path in PY_TOOLS.values():
        flags |= _py_flags(path)
    for path in SH_TOOLS.values():
        flags |= set(re.findall(r"(?<![\w-])(--[A-Za-z][\w-]*)", _sh_text(path)))
    return flags


def _slug(heading: str) -> str:
    """GitHub's anchor for a heading: lower case, letters/digits/marks, '-',
    '_' and spaces kept (spaces become '-'), everything else dropped."""
    text = heading.replace("`", "").strip().lower()
    kept = "".join(ch for ch in text
                   if ch in " -_" or unicodedata.category(ch)[0] in "LMN")
    return kept.replace(" ", "-")


def _cfg(name: str) -> BCMConfig:
    # No overlay and no environment: exactly the shipped file, nothing written.
    return BCMConfig(config_path=str(REPO / "config" / name), platform_override="x86",
                     local_path=None, env={})


def _table_rows(doc: Doc, heading: str) -> tuple[list[str], list[list[str]]]:
    start = doc.text.index(heading)
    end = doc.text.find("\n## ", start + len(heading))
    section = doc.text[start:end if end != -1 else None]
    rows = [[c.strip() for c in line.strip().strip("|").split("|")]
            for line in section.splitlines() if line.lstrip().startswith("|")]
    header, body = rows[0], [r for r in rows[1:] if not set("".join(r)) <= set("-: ")]
    return header, body


# ── tests ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", DOCS)
def test_doc_exists_and_has_code(name):
    doc = _doc(name)
    assert _bash_blocks(doc), f"{name}: brak bloków ```bash"


@pytest.mark.parametrize("name", DOCS)
def test_repo_paths_exist(name):
    doc = _doc(name)
    missing = set()
    for code in _code_texts(doc):
        for m in PATH_RE.finditer(code):
            nxt = code[m.end():m.end() + 1]
            if nxt and nxt in "<*{":
                continue                    # placeholder or glob, not a path
            path = m.group(1).rstrip(".,-")
            if path.rstrip("/") in RUNTIME_PATHS:
                continue
            if not (REPO / path).exists():
                missing.add(path)
    assert not missing, f"{name}: ścieżki, których nie ma w repo: {sorted(missing)}"


@pytest.mark.parametrize("name", DOCS)
def test_links_and_anchors_resolve(name):
    doc = _doc(name)
    base = (REPO / name).parent
    anchors = {_slug(h) for h in HEADING_RE.findall(FENCE_RE.sub("", doc.text))}
    bad = []
    for target in LINK_RE.findall(FENCE_RE.sub("", doc.text)):
        if re.match(r"^[a-z]+://", target):
            continue
        path, _, anchor = target.partition("#")
        if path and not (base / path).exists():
            bad.append(target)
        elif not path and anchor and anchor not in anchors:
            bad.append(target)
    assert not bad, f"{name}: linki donikąd: {bad}"


@pytest.mark.parametrize("name", DOCS)
def test_module_references_are_catalog_keys(name):
    doc = _doc(name)
    unknown = set(MODULE_REF_RE.findall(doc.text)) - set(MODULES)
    for lang, body in doc.blocks:
        if lang not in ("yaml", "yml"):
            continue
        data = yaml.safe_load(body)
        if isinstance(data, dict) and isinstance(data.get("modules"), dict):
            unknown |= set(data["modules"]) - set(MODULES)
            assert all(isinstance(v, bool) for v in data["modules"].values()), \
                f"{name}: przełącznik modułu musi być true/false: {data['modules']}"
    assert not unknown, f"{name}: nieznane moduły: {sorted(unknown)}"


def _module_names_in_prose(doc: Doc) -> list[str]:
    """Bare names the guide tells the owner to switch in Settings → Moduły:
    every `name` in a paragraph or list item that mentions „Moduły”, and the
    first `name` of each item of a list introduced by such a line ending
    with ':' („Ustawienia → Moduły, po kolei:” + „1. `car_phone` — …”)."""
    rest = FENCE_RE.sub("", doc.text)
    chunks = re.split(r"\n[ \t]*\n|\n(?=[ \t]*(?:\d+\.|[-*])[ \t])", rest)
    bare = re.compile(r"[a-z][a-z0-9_]*")
    names: list[str] = []
    intro = False
    for chunk in chunks:
        is_item = re.match(r"[ \t]*(?:\d+\.|[-*])[ \t]", chunk) is not None
        spans = [s for s in INLINE_RE.findall(chunk) if bare.fullmatch(s)]
        if "Moduły" in chunk:
            names.extend(spans)
            intro = chunk.rstrip().endswith(":")
        elif intro and is_item:
            names.extend(spans[:1])
        else:
            intro = False
    return names


@pytest.mark.parametrize("name", DOCS)
def test_module_names_after_settings_moduly_are_catalog_keys(name):
    names = _module_names_in_prose(_doc(name))
    assert names, f"{name}: brak modułów przy „Ustawienia → Moduły”"
    unknown = sorted(set(names) - set(MODULES))
    assert not unknown, f"{name}: „Moduły” wymienia nieznane moduły: {unknown}"


@pytest.mark.parametrize("name", DOCS)
def test_yaml_blocks_parse(name):
    for lang, body in _doc(name).blocks:
        if lang in ("yaml", "yml"):
            yaml.safe_load(body)           # raises on a broken example


@pytest.mark.parametrize("name", DOCS)
def test_tool_flags_exist(name):
    doc = _doc(name)
    bad = []
    for line in _command_lines(doc):
        for tool in (*PY_TOOLS, *SH_TOOLS):
            for m in re.finditer(r"(?<![\w-])" + re.escape(tool) + r"(?P<rest>[^;|&\n]*)", line):
                for flag in FLAG_RE.findall(m["rest"]):
                    known = _tool_flags(tool)
                    if known is not None:
                        ok = flag in known
                    else:
                        ok = re.search(r"(?<![\w-])" + re.escape(flag) + r"(?![\w-])",
                                       _sh_text(SH_TOOLS[tool])) is not None
                    if not ok:
                        bad.append(f"{tool} {flag}")
    # A flag named on its own (`--park-setup`) must belong to one of the tools.
    known_all = _all_known_flags()
    for span in doc.inline:
        m = re.match(r"^(--[A-Za-z][\w-]*)$", span.strip())
        if m and m.group(1) not in known_all:
            bad.append(span)
    assert not bad, f"{name}: flagi, których narzędzia nie znają: {sorted(set(bad))}"


def test_agent_flags_in_phone_guide():
    """The phone guide walks through every agent action the owner runs."""
    doc = _doc("docs/PRZYGOTOWANIE_TELEFONU.md")
    used = set()
    for line in _command_lines(doc):
        for m in re.finditer(r"bcm_agent\.py(?P<rest>[^;|&\n]*)", line):
            used |= set(FLAG_RE.findall(m["rest"]))
    agent = _py_flags(PY_TOOLS["bcm_agent.py"])
    assert used <= agent
    for flag in ("--pair", "--park-setup", "--new", "--park-numbers"):
        assert flag in used, f"instrukcja telefonu nie pokazuje {flag}"


def test_agent_version_in_phone_guide_is_current():
    """„(obecna: X)” must follow bcm_agent.VERSION, and no required minimum
    (≥ 1.x.y) may be newer than the agent in the repo."""
    src = PY_TOOLS["bcm_agent.py"].read_text(encoding="utf-8")
    version = re.search(r'^VERSION = "(\d+\.\d+\.\d+)"', src, re.M).group(1)
    text = _doc("docs/PRZYGOTOWANIE_TELEFONU.md").text
    assert re.findall(r"obecna: (\d+\.\d+\.\d+)", text) == [version]

    def key(v):
        return tuple(int(x) for x in v.split("."))
    for needed in re.findall(r"≥ (\d+\.\d+\.\d+)", text):
        assert key(needed) <= key(version), f"wymagany agent {needed} > {version}"
    # The technical reference names minimums only — never "after this
    # update: X" (it went stale at every agent release).
    ref = _doc("docs/WDROZENIE_TESTOWE.md").text
    assert not re.search(r"po tej aktualizacji \*\*\d+\.\d+\.\d+\*\*", ref)
    for needed in re.findall(r"≥ (\d+\.\d+\.\d+)", ref):
        assert key(needed) <= key(version), f"WDROZENIE_TESTOWE: agent {needed} > {version}"


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not installed")
@pytest.mark.parametrize("name", DOCS)
def test_bash_blocks_parse(name):
    bad = []
    for body in _bash_blocks(_doc(name)):
        if PLACEHOLDER_RE.search(body):
            continue                        # <placeholder> — not runnable as is
        # Parse only: bash -n reads the script from stdin and executes nothing.
        res = subprocess.run(["bash", "-n"], input=body, capture_output=True, text=True,
                             timeout=10)
        if res.returncode != 0:
            bad.append(f"{body.strip()[:80]!r}: {res.stderr.strip()}")
    assert not bad, f"{name}: bloki bash ze złą składnią: {bad}"


@pytest.mark.parametrize("name", DOCS)
def test_bash_blocks_have_no_prompt(name):
    for body in _bash_blocks(_doc(name)):
        for line in body.splitlines():
            assert not line.startswith("$ "), \
                f"{name}: znak zachęty '$' w bloku do skopiowania: {line!r}"


@pytest.mark.parametrize("name", GUARDED_DOCS)
def test_no_copy_paste_block_can_dial_112(name):
    """Tests use a test number only — nothing the owner copies (a block of
    any language, or inline code) may place a real emergency call (the
    agent's fixed 112 intent lives in its code)."""
    doc = _doc(name)
    for body in [*doc.inline, *(b for _, b in doc.blocks)]:
        assert not REAL_112_RE.search(body), f"{name}: kod może wybrać 112: {body!r}"
        for m in re.finditer(r"/api/crash/call112[\w/]*", body):
            assert m.group(0) == "/api/crash/call112/test", \
                f"{name}: kod woła prawdziwą trasę 112: {m.group(0)}"
    for _, body in doc.blocks:
        assert not DIAL_ROUTE_RE.search(body), \
            f"{name}: blok woła /api/phone/dial (z 127.0.0.1 wybiera każdy numer): {body!r}"
    for span in doc.inline:
        assert not (DIAL_ROUTE_RE.search(span) and re.search(r"\b(curl|wget|POST)\b", span)), \
            f"{name}: polecenie do /api/phone/dial: {span!r}"


@pytest.mark.parametrize("name", GUARDED_DOCS)
def test_no_dialable_number_in_copyable_code(name):
    """``+48601234567`` passes every E.164 check — pasted unchanged it would
    send the car's position to a stranger or ring them for the 112 test."""
    doc = _doc(name)
    found = {m.group(0) for code in _code_texts(doc) for m in E164_LITERAL_RE.finditer(code)}
    assert not found, f"{name}: prawdziwe numery w kodzie do skopiowania: {sorted(found)}"


def test_guards_catch_what_they_are_for():
    """The guards themselves: each pattern catches its case (a guard that
    matches nothing would pass every doc)."""
    for bad in ("am start -a android.intent.action.CALL -d tel:112",
                "termux-telephony-call 112", "termux-telephony-call '+112'",
                "su -c 'am start -a android.intent.action.CALL'", "tel:+997"):
        assert REAL_112_RE.search(bad), bad
    for ok in ("termux-telephony-call +48XXXXXXXXX",
               "su -c 'am start -W -a android.intent.action.MAIN -c "
               "android.intent.category.LAUNCHER com.termux'",
               "START_CALL_WITH_SPEAKERPHONE"):
        assert not REAL_112_RE.search(ok), ok
    assert DIAL_ROUTE_RE.search("curl -X POST http://127.0.0.1:5002/api/phone/dial")
    assert E164_LITERAL_RE.search("--park-numbers '+48601234567'")
    assert not E164_LITERAL_RE.search("--park-numbers '+48XXXXXXXXX'")


@pytest.mark.parametrize("name", DOCS)
def test_settings_labels_are_ui_strings(name):
    from src.dashboard.i18n import STRINGS
    labels = set(STRINGS["pl"].values())
    unknown = {label for label in LABEL_RE.findall(_doc(name).text) if label not in labels}
    assert not unknown, f"{name}: etykiet nie ma w src/dashboard/i18n.py: {sorted(unknown)}"


def test_module_table_matches_catalog_and_configs():
    doc = _doc("docs/WDROZENIE_TESTOWE_TELEFON.md")
    header, rows = _table_rows(doc, MODULE_TABLE_HEADING)
    col = {h: i for i, h in enumerate(header)}
    # „Docelowa” = config/bcm_config.yaml (the car's config since 23.11),
    # „Test” = config/bcm_config_test.yaml (bench / the old test config).
    for needed in ("Moduł", "Wymaga", "Docelowa", "Test"):
        assert needed in col, f"tabela modułów bez kolumny {needed}"
    prod, test = _cfg("bcm_config.yaml"), _cfg("bcm_config_test.yaml")
    words = {"wł.": True, "wył.": False}
    listed = set()
    for row in rows:
        m = re.fullmatch(r"`([a-z0-9_]+)`", row[col["Moduł"]])
        assert m, f"pierwsza kolumna to nie nazwa modułu: {row}"
        name = m.group(1)
        assert name in MODULES, f"tabela: nieznany moduł {name}"
        listed.add(name)
        info = MODULES[name]
        expected = {dep for group in requirement_groups(info) for dep in group}
        given = set(re.findall(r"`([a-z0-9_]+)`", row[col["Wymaga"]]))
        assert given == expected, f"{name}: wymaga {sorted(expected)}, tabela: {sorted(given)}"
        for column, cfg in (("Docelowa", prod), ("Test", test)):
            value = row[col[column]]
            assert value in words, f"{name}: {column} = {value!r} (wł./wył.)"
            assert words[value] == bool(is_enabled(cfg, name)), \
                f"{name}: {column} w tabeli {value}, w configu {is_enabled(cfg, name)}"
        if info.get("planned"):
            assert "niedostępny" in row[col["Co robi"]], f"{name}: planowany bez „niedostępny”"
    # Every add-on with a Settings group (telefon w aucie, bezpieczeństwo,
    # zasilanie) is in the table — those are the toggles this guide is for.
    grouped = {n for n, info in MODULES.items() if info.get("group")}
    assert grouped <= listed, f"tabela bez modułów: {sorted(grouped - listed)}"


def test_no_stale_claims_about_the_final_config():
    # Since 23.11 config/bcm_config.yaml is the car's config with most new
    # modules on; these sentences were true only before that switch.
    stale = ("produkcyjnym `config/bcm_config.yaml` nic się nie zmienia",
             "jedną linią w `/etc/bcm/bcm.env`")
    for path in ("docs/WDROZENIE_TESTOWE_TELEFON.md", "docs/WDROZENIE_TESTOWE.md"):
        text = (REPO / path).read_text(encoding="utf-8")
        for phrase in stale:
            assert phrase not in text, f"{path}: nieaktualne zdanie „{phrase}”"
