"""Tests for the layered config: base YAML + local.yaml overlay + env secrets.

Everything runs on small YAML files in tmp_path — the real config/*.yaml are
only read (and their checksums asserted unchanged).
"""

import argparse
import hashlib
import logging
import os
import stat
import threading
from pathlib import Path

import pytest
import yaml

import src.core.config as config_mod
from src.core.config import (
    LOCAL_HEADER,
    SECRET_ENV_MAP,
    BCMConfig,
    compute_overlay,
    is_never_persisted,
    parse_dotenv,
    prune_overlay,
)

REPO = Path(__file__).resolve().parent.parent

BASE = {
    "system": {"name": "BCM", "platform": "x86", "log_level": "INFO"},
    "display": {"dashboard": {"theme": "heritage", "brightness": 70, "width": 1024}},
    "modules": {"weather": False, "dashboard": True},
    "swc": {"mapping": {"mute": ["SWC_MUTE", "SWC2_MUTE"], "next_track": ["SWC_NEXT"]}},
    "brightness": {"steps": [15, 30, 45]},
    "wifi": {"ssid": "ALFA", "password": "87654321", "ssid_runtime": "",
             "password_runtime": "", "alfa_net": {"password": "AlfaRomeo156"}},
    "weather": {"api_key": "", "poll_interval_min": 15},
    "travel": {"openrouteservice_key": "", "tomtom_key": ""},
    "multimedia": {"last_bt_device": ""},
}


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


@pytest.fixture
def base_path(tmp_path):
    p = tmp_path / "base.yaml"
    p.write_text("# base with a comment that must survive\n" + yaml.safe_dump(BASE),
                 encoding="utf-8")
    return p


@pytest.fixture
def local_path(tmp_path):
    return tmp_path / "local.yaml"


def _write_local(path, data):
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


def _cfg(base_path, local_path=None, **kw):
    return BCMConfig(str(base_path), "x86", local_path=local_path, **kw)


def _read_local(path):
    text = Path(path).read_text(encoding="utf-8")
    assert text.startswith(LOCAL_HEADER)
    return yaml.safe_load(text)


# ── Pure helpers ──────────────────────────────────────────────────────────

class TestOverlayHelpers:
    def test_compute_overlay_recursive_diff(self):
        current = {"a": {"b": 1, "c": 2}, "l": [1, 2], "new": {"x": 1}}
        base = {"a": {"b": 1, "c": 3}, "l": [1, 2]}
        assert compute_overlay(base, current) == {"a": {"c": 2}, "new": {"x": 1}}

    def test_compute_overlay_list_change_stored_whole(self):
        assert compute_overlay({"l": [1, 2, 3]}, {"l": [1, 9, 3]}) == {"l": [1, 9, 3]}

    @pytest.mark.parametrize("path, expected", [
        ("system.platform", True),
        ("wifi.password_runtime", True),
        ("a.b.c.deep_runtime", True),
        ("x_runtime", True),
        ("wifi.runtime_note", False),
        ("system.platform_hint", False),
        ("display.dashboard.theme", False),
    ])
    def test_is_never_persisted(self, path, expected):
        assert is_never_persisted(path) is expected

    def test_secret_paths_are_never_persisted(self):
        assert is_never_persisted("weather.api_key", SECRET_ENV_MAP)
        assert not is_never_persisted("weather.api_key")

    def test_prune_drops_runtime_at_any_depth_and_emptied_parents(self):
        overlay = {
            "wifi": {"ssid_runtime": "DIRECT-x", "nested": {"bssid_runtime": "aa"}},
            "system": {"platform": "opi"},
            "keep": {"empty": {}},
            "dict_runtime": {"anything": 1},
        }
        pruned, dropped = prune_overlay(overlay)
        assert pruned == {"keep": {"empty": {}}}
        assert set(dropped) == {"wifi.ssid_runtime", "wifi.nested.bssid_runtime",
                                "system.platform", "dict_runtime"}


class TestDotenvParser:
    def test_parse_rules(self):
        text = "\n".join([
            "# comment",
            "; also a comment",
            "",
            "PLAIN=abc",
            "export EXPORTED=def",
            "SINGLE='with spaces'",
            'DOUBLE="x # not a comment"',
            "INLINE=abc # kept literally",
            "EMPTY=",
            "SPACED = padded ",
            "NOEQUALS",
            "1BAD=x",
            "INTERP=$HOME",
            "MISMATCH='abc\"",
        ])
        env = parse_dotenv(text)
        assert env == {
            "PLAIN": "abc", "EXPORTED": "def", "SINGLE": "with spaces",
            "DOUBLE": "x # not a comment", "INLINE": "abc # kept literally",
            "EMPTY": "", "SPACED": "padded", "INTERP": "$HOME",
            "MISMATCH": "'abc\"",
        }


# ── Loading and merging ───────────────────────────────────────────────────

class TestLoadAndMerge:
    def test_without_local_or_env_behaves_like_before(self, base_path):
        cfg = _cfg(base_path)
        assert cfg.local_path is None
        assert cfg.secret_sources == {}
        assert cfg.get("display.dashboard.theme") == "heritage"
        assert cfg.overlay() == {}

    def test_deep_merge(self, base_path, local_path):
        _write_local(local_path, {"display": {"dashboard": {"theme": "autodelta"}},
                                  "extra": {"k": 1}})
        cfg = _cfg(base_path, local_path)
        assert cfg.get("display.dashboard.theme") == "autodelta"
        assert cfg.get("display.dashboard.brightness") == 70   # sibling kept
        assert cfg.get("extra.k") == 1
        assert cfg.load_warnings == []

    def test_lists_are_replaced_not_merged(self, base_path, local_path):
        _write_local(local_path, {"brightness": {"steps": [50]}})
        assert _cfg(base_path, local_path).get("brightness.steps") == [50]

    def test_missing_local_is_fine(self, base_path, local_path):
        cfg = _cfg(base_path, local_path)
        assert cfg.load_warnings == []
        assert not local_path.exists()

    def test_null_section_does_not_wipe_base(self, base_path, local_path):
        local_path.write_text("display:\nmodules:\n  weather: true\n", encoding="utf-8")
        cfg = _cfg(base_path, local_path)
        assert cfg.get("display.dashboard.theme") == "heritage"
        assert cfg.get("modules.weather") is True
        assert any("display" in w for w in cfg.load_warnings)

    def test_comment_only_overlay_is_valid_and_empty(self, base_path, local_path):
        """Commenting out every override is how a user drops them by hand —
        not a broken file: no quarantine, and the older .bak is NOT restored."""
        bak = local_path.with_name("local.yaml.bak")
        _write_local(bak, {"display": {"dashboard": {"theme": "modern"}}})
        content = LOCAL_HEADER + "# display:\n#   dashboard:\n#     theme: autodelta\n"
        local_path.write_text(content, encoding="utf-8")

        cfg = _cfg(base_path, local_path)

        assert cfg.get("display.dashboard.theme") == "heritage"
        assert cfg.load_warnings == []
        assert not list(local_path.parent.glob("local.yaml.broken-*"))
        assert local_path.read_text(encoding="utf-8") == content
        # nothing overridden → saving does not rewrite the user's file
        assert cfg.save() is True
        assert local_path.read_text(encoding="utf-8") == content

    @pytest.mark.parametrize("content, key", [
        ("weather: true\n", "weather"),
        ("display: 1\n", "display"),
        ("display:\n  dashboard: [a, b]\n", "display.dashboard"),
        ("swc: oops\n", "swc"),
    ])
    def test_scalar_or_list_over_a_section_is_ignored(self, base_path, local_path, content, key):
        """A hand-edit typo (`weather: true` for `modules.weather: true`) must
        not replace a whole section — code does config.get('weather', {}).get()."""
        local_path.write_text(content + "modules:\n  weather: true\n", encoding="utf-8")
        cfg = _cfg(base_path, local_path)
        assert isinstance(cfg.get(key), dict)
        assert cfg.get("weather.poll_interval_min") == 15
        assert cfg.get("display.dashboard.theme") == "heritage"
        assert cfg.get("modules.weather") is True          # the valid part still applies
        assert any(f"'{key}'" in w and "ignored" in w for w in cfg.load_warnings)

    def test_new_scalar_keys_are_still_allowed(self, base_path, local_path):
        local_path.write_text("language: en\nnew_flag: true\n", encoding="utf-8")
        cfg = _cfg(base_path, local_path)
        assert cfg.get("language") == "en" and cfg.get("new_flag") is True
        assert cfg.load_warnings == []

    def test_local_path_equal_to_base_is_refused(self, base_path):
        cfg = _cfg(base_path, base_path)
        assert cfg.local_path is None
        assert cfg.load_warnings
        cfg.set("display.dashboard.theme", "modern")
        assert cfg.save() is False

    def test_stale_tmp_cleaned_on_load(self, base_path, local_path, tmp_path):
        stale = tmp_path / ".local.yaml.abc.tmp"
        stale.write_text("partial")
        os.utime(stale, (1, 1))
        _cfg(base_path, local_path)
        assert not stale.exists()


class TestBrokenOverlayFallback:
    @pytest.mark.parametrize("content", ["", "  \n\n\t\n", "\0" * 64, "{{{ not: yaml: [",
                                         "- a\n- list\n", "just a string\n"],
                             ids=["empty", "whitespace", "nul-filled", "not-yaml", "list",
                                  "string"])
    def test_broken_local_falls_back_to_bak(self, base_path, local_path, content):
        bak = local_path.with_name("local.yaml.bak")
        _write_local(bak, {"display": {"dashboard": {"theme": "modern"}}})
        local_path.write_text(content, encoding="utf-8")

        cfg = _cfg(base_path, local_path)

        assert cfg.get("display.dashboard.theme") == "modern"
        broken = list(local_path.parent.glob("local.yaml.broken-*"))
        assert len(broken) == 1 and broken[0].read_text(encoding="utf-8") == content
        # the good backup is restored as local.yaml
        assert _read_overlay(local_path) == {"display": {"dashboard": {"theme": "modern"}}}
        assert _mode(local_path) == 0o600
        assert any("recovered" in w for w in cfg.load_warnings)

    def test_both_broken_means_base_only_with_warning(self, base_path, local_path):
        local_path.write_text("", encoding="utf-8")
        local_path.with_name("local.yaml.bak").write_text("[1, 2]", encoding="utf-8")
        cfg = _cfg(base_path, local_path)
        assert cfg.get("display.dashboard.theme") == "heritage"
        assert any("base config only" in w for w in cfg.load_warnings)
        # and the next save starts a fresh overlay
        cfg.set("display.dashboard.theme", "autodelta")
        assert cfg.save() is True
        assert _read_local(local_path) == {"display": {"dashboard": {"theme": "autodelta"}}}

    def test_only_three_broken_copies_kept(self, base_path, local_path):
        for i in range(5):
            (local_path.parent / f"local.yaml.broken-2020010{i}-000000").write_text("x")
        local_path.write_text("", encoding="utf-8")
        _cfg(base_path, local_path)
        broken = sorted(p.name for p in local_path.parent.glob("local.yaml.broken-*"))
        old = {f"local.yaml.broken-2020010{i}-000000" for i in range(5)}
        assert len(broken) == 3
        # the two newest old copies survive, plus the one just quarantined
        assert broken[:2] == ["local.yaml.broken-20200103-000000",
                              "local.yaml.broken-20200104-000000"]
        assert broken[2] not in old

    def test_does_not_crash_on_unreadable_bytes(self, base_path, local_path):
        local_path.write_bytes(b"\xff\xfe\x00garbage")
        cfg = _cfg(base_path, local_path)
        assert cfg.get("display.dashboard.theme") == "heritage"
        assert cfg.load_warnings


def _read_overlay(path):
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


# ── Saving ────────────────────────────────────────────────────────────────

class TestSave:
    def test_save_writes_only_the_difference(self, base_path, local_path):
        cfg = _cfg(base_path, local_path)
        cfg.set("display.dashboard.theme", "autodelta")
        cfg.set("multimedia.last_bt_device", "AA:BB:CC:DD:EE:FF")
        assert cfg.save() is True
        assert _read_local(local_path) == {
            "display": {"dashboard": {"theme": "autodelta"}},
            "multimedia": {"last_bt_device": "AA:BB:CC:DD:EE:FF"},
        }
        assert _mode(local_path) == 0o600

    def test_value_equal_to_base_produces_no_entry(self, base_path, local_path):
        cfg = _cfg(base_path, local_path)
        cfg.set("display.dashboard.theme", "heritage")   # same as base
        assert cfg.save() is True
        assert not local_path.exists()                    # empty overlay → no file
        cfg.set("display.dashboard.theme", "modern")
        cfg.save()
        cfg.set("display.dashboard.theme", "heritage")    # back to base
        cfg.save()
        assert _read_local(local_path) == {}

    def test_runtime_keys_never_persisted_at_any_depth(self, base_path, local_path):
        cfg = _cfg(base_path, local_path)
        cfg.set("wifi.password_runtime", "testpsk1")
        cfg.set("wifi.ssid_runtime", "DIRECT-xy")
        cfg.set("a.b.deep_runtime", "x")
        cfg.set("display.dashboard.theme", "modern")
        cfg.save()
        text = local_path.read_text(encoding="utf-8")
        assert "_runtime" not in text and "testpsk1" not in text
        assert _read_local(local_path) == {"display": {"dashboard": {"theme": "modern"}}}

    def test_platform_never_persisted(self, base_path, local_path):
        cfg = BCMConfig(str(base_path), "opi", local_path=local_path)
        assert cfg.platform == "opi"
        cfg.set("display.dashboard.theme", "modern")
        cfg.save()
        assert "system" not in _read_local(local_path)

    def test_env_secret_visible_but_never_written(self, base_path, local_path):
        cfg = _cfg(base_path, local_path, env={"BCM_OWM_API_KEY": "0123456789abcdef" * 2})
        assert cfg.get("weather.api_key") == "0123456789abcdef" * 2
        assert cfg.secret_sources == {"weather.api_key": "BCM_OWM_API_KEY"}
        cfg.set("display.dashboard.theme", "modern")
        cfg.save()
        text = local_path.read_text(encoding="utf-8")
        assert "0123456789abcdef" not in text and "api_key" not in text

    def test_ui_change_of_env_secret_warns_and_is_not_persisted(self, base_path, local_path, caplog):
        cfg = _cfg(base_path, local_path, env={"BCM_WIFI_PASSWORD": "fromenv123"})
        cfg.set("wifi.password", "typed-in-ui")
        with caplog.at_level(logging.WARNING, logger="bcm.config"):
            cfg.save()
        assert any("BCM_WIFI_PASSWORD" in r.getMessage() for r in caplog.records)
        assert all("typed-in-ui" not in r.getMessage() for r in caplog.records)
        assert not local_path.exists() or "typed-in-ui" not in local_path.read_text()
        assert cfg.get("wifi.password") == "typed-in-ui"   # still effective in memory

    def test_secret_without_env_is_persisted_privately(self, base_path, local_path):
        """No env var for it → the UI value is a normal override (0600 file)."""
        cfg = _cfg(base_path, local_path, env={})
        cfg.set("wifi.password", "newpass123")
        cfg.save()
        assert _read_local(local_path) == {"wifi": {"password": "newpass123"}}
        assert _mode(local_path) == 0o600

    def test_identical_save_twice_writes_once(self, base_path, local_path, monkeypatch):
        calls = []
        real = config_mod.atomic_write_text

        def counting(*a, **kw):
            calls.append(a[0])
            return real(*a, **kw)

        monkeypatch.setattr(config_mod, "atomic_write_text", counting)
        cfg = _cfg(base_path, local_path)
        cfg.set("display.dashboard.theme", "modern")
        assert cfg.save() and cfg.save() and cfg.save()
        assert len(calls) == 1
        # a fresh instance loading the same file does not rewrite it either
        cfg2 = _cfg(base_path, local_path)
        cfg2.set("multimedia.last_bt_device", "")   # equal to base
        assert cfg2.save()
        assert len(calls) == 1

    def test_previous_version_goes_to_bak(self, base_path, local_path):
        cfg = _cfg(base_path, local_path)
        cfg.set("display.dashboard.theme", "modern")
        cfg.save()
        cfg.set("display.dashboard.theme", "autodelta")
        cfg.save()
        bak = local_path.with_name("local.yaml.bak")
        assert _read_local(bak) == {"display": {"dashboard": {"theme": "modern"}}}
        assert _read_local(local_path) == {"display": {"dashboard": {"theme": "autodelta"}}}
        assert _mode(bak) == 0o600

    def test_in_place_mutation_of_live_reference_is_saved(self, base_path, local_path):
        """SWC learn mode edits the list returned by get() in place."""
        cfg = _cfg(base_path, local_path)
        mapping = cfg.get("swc.mapping")
        mapping["mute"][0] = "SWC_VOICE"
        cfg.set("swc.mapping", mapping)
        cfg.save()
        assert _read_local(local_path) == {"swc": {"mapping": {"mute": ["SWC_VOICE", "SWC2_MUTE"]}}}
        # and the base copy kept for diffing was not mutated through it
        assert cfg._base["swc"]["mapping"]["mute"][0] == "SWC_MUTE"

    def test_overrides_survive_reload(self, base_path, local_path):
        cfg = _cfg(base_path, local_path)
        cfg.set("modules.weather", True)
        cfg.save()
        assert _cfg(base_path, local_path).get("modules.weather") is True

    def test_base_file_never_changes(self, base_path, local_path):
        before = _sha(base_path)
        cfg = _cfg(base_path, local_path, env={"BCM_OWM_API_KEY": "k" * 32})
        for i in range(25):
            cfg.set("display.dashboard.brightness", i)
            cfg.set("wifi.password_runtime", f"p{i}")
            cfg.save()
        assert _sha(base_path) == before
        assert base_path.read_text(encoding="utf-8").startswith("# base with a comment")

    def test_no_local_path_writes_nothing(self, base_path, tmp_path):
        before = sorted(p.name for p in tmp_path.iterdir())
        sha = _sha(base_path)
        cfg = _cfg(base_path)
        cfg.set("display.dashboard.theme", "modern")
        assert cfg.save() is False
        assert cfg.save() is False
        assert sorted(p.name for p in tmp_path.iterdir()) == before
        assert _sha(base_path) == sha

    def test_explicit_path_is_refused(self, base_path, local_path, tmp_path):
        cfg = _cfg(base_path, local_path)
        cfg.set("display.dashboard.theme", "modern")
        sha = _sha(base_path)
        assert cfg.save(str(base_path)) is False
        assert cfg.save(str(tmp_path / "elsewhere.yaml")) is False
        assert _sha(base_path) == sha
        assert not (tmp_path / "elsewhere.yaml").exists()

    def test_write_error_returns_false_without_raising(self, base_path, local_path, monkeypatch):
        def boom(*a, **kw):
            raise OSError(30, "Read-only file system")

        monkeypatch.setattr(config_mod, "atomic_write_text", boom)
        cfg = _cfg(base_path, local_path)
        cfg.set("display.dashboard.theme", "modern")
        assert cfg.save() is False

    def test_unserialisable_value_returns_false(self, base_path, local_path):
        cfg = _cfg(base_path, local_path)
        cfg.set("display.dashboard.theme", object())
        assert cfg.save() is False
        assert not local_path.exists()

    def test_tuples_are_written_as_lists(self, base_path, local_path):
        cfg = _cfg(base_path, local_path)
        cfg.set("brightness.steps", (10, 20))
        cfg.save()
        assert _read_local(local_path) == {"brightness": {"steps": [10, 20]}}

    def test_concurrent_set_and_save(self, base_path, local_path):
        cfg = _cfg(base_path, local_path)
        errors = []

        def worker(n):
            try:
                for i in range(100):
                    cfg.set(f"stress.t{n}", i)
                    cfg.set("wifi.password_runtime", f"{n}-{i}")
                    cfg.save()
            except Exception as e:  # pragma: no cover - failure path
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        assert errors == []
        cfg.save()
        data = _read_local(local_path)
        assert data == {"stress": {f"t{n}": 99 for n in range(4)}}
        assert not [p for p in local_path.parent.iterdir() if p.name.endswith(".tmp")]


# ── Overlay bound to its base (rollback to bcm_config_temp.yaml and back) ─

class TestOverlayBase:
    def _other_base(self, tmp_path, **changes):
        """A second base YAML in the same directory (shares local.yaml)."""
        import copy
        data = copy.deepcopy(BASE)
        for dotpath, value in changes.items():
            config_mod.set_path(data, dotpath.replace("__", "."), value)
        p = tmp_path / "other_base.yaml"
        p.write_text(yaml.safe_dump(data), encoding="utf-8")
        return p

    def test_save_records_the_base_name(self, base_path, local_path):
        cfg = _cfg(base_path, local_path)
        cfg.set("display.dashboard.theme", "modern")
        cfg.save()
        lines = local_path.read_text(encoding="utf-8").splitlines()
        assert lines[0] + "\n" == LOCAL_HEADER
        assert lines[1] == "# base: base.yaml"
        assert config_mod.overlay_base_name(local_path.read_bytes()) == "base.yaml"

    def test_overlay_for_another_base_is_applied_but_never_rewritten(
            self, base_path, local_path, tmp_path, caplog):
        """Rollback scenario: the overlay was saved against base.yaml; BCM now
        runs other_base.yaml whose theme equals the override. A save would
        drop the override and rolling forward would lose it — so the overlay
        is frozen instead (applied, not written)."""
        cfg = _cfg(base_path, local_path)
        cfg.set("display.dashboard.theme", "autodelta")
        cfg.set("modules.weather", True)
        cfg.save()
        sha = _sha(local_path)

        other = self._other_base(tmp_path, display__dashboard__theme="autodelta")
        rolled_back = _cfg(other, local_path)
        assert rolled_back.get("display.dashboard.theme") == "autodelta"
        assert rolled_back.get("modules.weather") is True
        assert any("saving is disabled" in w and "base.yaml" in w
                   for w in rolled_back.load_warnings)
        rolled_back.set("multimedia.last_bt_device", "AA:BB:CC:DD:EE:01")
        with caplog.at_level(logging.WARNING, logger="bcm.config"):
            assert rolled_back.save() is False
            assert rolled_back.save() is False       # BT reconnect: no new WARNING
        assert sum("not persisted" in r.getMessage() for r in caplog.records) == 1
        assert _sha(local_path) == sha

        # rolling forward: nothing was lost
        assert _cfg(base_path, local_path).get("display.dashboard.theme") == "autodelta"

    def test_overlay_without_base_line_is_adopted(self, base_path, local_path):
        _write_local(local_path, {"display": {"dashboard": {"theme": "modern"}}})
        cfg = _cfg(base_path, local_path)
        assert cfg.load_warnings == []
        cfg.set("display.dashboard.brightness", 40)
        assert cfg.save() is True
        assert config_mod.overlay_base_name(local_path.read_bytes()) == "base.yaml"

    def test_restored_backup_is_checked_too(self, base_path, local_path, tmp_path):
        other = self._other_base(tmp_path)
        bak = local_path.with_name("local.yaml.bak")
        bak.write_text(config_mod.render_overlay({"language": "en"}, base_name="base.yaml"))
        local_path.write_text("", encoding="utf-8")
        cfg = _cfg(other, local_path)
        assert cfg.get("language") == "en"
        assert cfg.save() is False

    def test_base_line_parsing(self):
        parse = config_mod.overlay_base_name
        assert parse(b"# Generated\n# base: bcm_config_test.yaml\nx: 1\n") == "bcm_config_test.yaml"
        assert parse(b"# Generated\nx: 1\n# base: other.yaml\n") is None   # not in the header
        assert parse(b"x: 1\n") is None
        assert parse(b"# base: ../evil path.yaml\n") is None

    @pytest.mark.parametrize("name", ["with space.yaml", "new\nline.yaml", "", None])
    def test_render_omits_unsafe_base_names(self, name):
        text = config_mod.render_overlay({"a": 1}, base_name=name)
        assert text == LOCAL_HEADER + "a: 1\n"


# ── Secrets from the environment ──────────────────────────────────────────

class TestEnvSecrets:
    def test_only_non_empty_values_apply(self, base_path):
        cfg = _cfg(base_path, env={"BCM_OWM_API_KEY": "   ", "BCM_ORS_API_KEY": "ors"})
        assert cfg.get("weather.api_key") == ""
        assert cfg.get("travel.openrouteservice_key") == "ors"
        assert cfg.secret_sources == {"travel.openrouteservice_key": "BCM_ORS_API_KEY"}

    def test_all_mapped_paths(self, base_path):
        env = {var: f"value-{i}-xyz" for i, var in enumerate(SECRET_ENV_MAP.values())}
        cfg = _cfg(base_path, env=env)
        for i, (dotpath, var) in enumerate(SECRET_ENV_MAP.items()):
            assert cfg.get(dotpath) == f"value-{i}-xyz"
            assert cfg.secret_sources[dotpath] == var

    def test_dotenv_used_and_real_env_wins(self, base_path, tmp_path):
        dotenv = tmp_path / ".env"
        dotenv.write_text("BCM_OWM_API_KEY=from-dotenv\nexport BCM_ORS_API_KEY='ors-dotenv'\n"
                          "BCM_TOMTOM_API_KEY=tt-dotenv\n")
        os.chmod(dotenv, 0o600)
        cfg = _cfg(base_path, env={"BCM_OWM_API_KEY": "from-env", "BCM_TOMTOM_API_KEY": ""},
                   dotenv_path=dotenv)
        assert cfg.get("weather.api_key") == "from-env"            # env beats .env
        assert cfg.get("travel.openrouteservice_key") == "ors-dotenv"
        assert cfg.get("travel.tomtom_key") == "tt-dotenv"        # empty env does not mask
        assert cfg.load_warnings == []

    def test_world_readable_dotenv_warns(self, base_path, tmp_path):
        dotenv = tmp_path / ".env"
        dotenv.write_text("BCM_OWM_API_KEY=k\n")
        os.chmod(dotenv, 0o644)
        cfg = _cfg(base_path, env={}, dotenv_path=dotenv)
        assert cfg.get("weather.api_key") == "k"
        assert any("chmod 600" in w for w in cfg.load_warnings)

    def test_missing_dotenv_is_fine(self, base_path, tmp_path):
        cfg = _cfg(base_path, env={}, dotenv_path=tmp_path / "absent.env")
        assert cfg.load_warnings == [] and cfg.secret_sources == {}

    def test_unpersisted_secret_changes(self, base_path, local_path):
        cfg = _cfg(base_path, local_path, env={"BCM_WIFI_PASSWORD": "fromenv123"})
        assert cfg.unpersisted_secret_changes() == []
        cfg.set("wifi.alfa_net.password", "notfromenv1")   # not env-provided → saved normally
        assert cfg.unpersisted_secret_changes() == []
        cfg.set("wifi.password", "typed-in-ui")
        assert cfg.unpersisted_secret_changes() == ["wifi.password"]
        cfg.set("wifi.password", "fromenv123")              # back to the env value
        assert cfg.unpersisted_secret_changes() == []

    def test_wifi_endpoint_reports_env_managed_password(self, base_path, local_path):
        """POST /api/wifi/config must not claim 'Saved' for a password that
        bcm.env overrides on the next start."""
        from src.dashboard.web_viewer import _unpersisted_wifi_secrets
        cfg = _cfg(base_path, local_path, env={"BCM_WIFI_PASSWORD": "fromenv123",
                                               "BCM_OWM_API_KEY": "k" * 32})
        cfg.set("wifi.password", "typed-in-ui")
        cfg.set("weather.api_key", "other")                 # not a Wi-Fi secret
        assert _unpersisted_wifi_secrets(cfg) == ["wifi.password"]
        assert _unpersisted_wifi_secrets(object()) == []    # no helper → none

        class Boom:
            def unpersisted_secret_changes(self):
                raise RuntimeError("x")

        assert _unpersisted_wifi_secrets(Boom()) == []

    def test_env_wins_over_local_overlay(self, base_path, local_path):
        _write_local(local_path, {"weather": {"api_key": "old-in-local"}})
        cfg = _cfg(base_path, local_path, env={"BCM_OWM_API_KEY": "new-env"})
        assert cfg.get("weather.api_key") == "new-env"
        # the next save drops the stale secret from the overlay
        cfg.set("display.dashboard.theme", "modern")
        cfg.save()
        assert "old-in-local" not in local_path.read_text()


# ── Shipped configs keep working ──────────────────────────────────────────

class TestShippedConfigs:
    @pytest.mark.parametrize("name", ["bcm_config.yaml", "bcm_config_test.yaml",
                                      "bcm_config_temp.yaml"])
    def test_loads_with_overlay_machinery(self, name, tmp_path):
        base = REPO / "config" / name
        sha = _sha(base)
        cfg = BCMConfig(str(base), "x86", local_path=tmp_path / "local.yaml", env={})
        assert cfg.overlay() == {}
        cfg.set("display.dashboard.theme", "modern")
        assert cfg.save() is True
        assert _sha(base) == sha

    def test_test_config_keeps_debug_module_levels(self):
        cfg = BCMConfig(str(REPO / "config" / "bcm_config_test.yaml"), "x86")
        levels = cfg.get("system.module_levels")
        for name in ("multimedia.bluetooth", "multimedia.openauto", "multimedia.wifi_ap"):
            assert levels[name] == "DEBUG"


# ── main.py wiring ────────────────────────────────────────────────────────

class TestMainLocalConfigResolution:
    def _args(self, **kw):
        return argparse.Namespace(no_local_config=kw.get("no", False),
                                  local_config=kw.get("path"))

    def test_precedence(self, monkeypatch, tmp_path):
        import main
        base = tmp_path / "cfg" / "base.yaml"
        monkeypatch.delenv("BCM_LOCAL_CONFIG", raising=False)
        assert main.resolve_local_config(self._args(), base) == tmp_path / "cfg" / "local.yaml"
        monkeypatch.setenv("BCM_LOCAL_CONFIG", str(tmp_path / "env.yaml"))
        assert main.resolve_local_config(self._args(), base) == tmp_path / "env.yaml"
        assert main.resolve_local_config(self._args(path="/x/l.yaml"), base) == Path("/x/l.yaml")
        assert main.resolve_local_config(self._args(no=True, path="/x/l.yaml"), base) is None


# ── Logging settings (system.log_max_mb / log_backups / module_levels) ────

class TestLoggingSettings:
    def test_rotation_defaults_and_validation(self):
        from src.core.logger import _sane_rotation
        assert _sane_rotation(5, 3) == (5 * 1024 * 1024, 3)
        assert _sane_rotation(0.5, 1) == (512 * 1024, 1)
        for bad_mb, bad_n in [(0, 0), (-1, -2), ("x", None), (True, True), (10**6, 10**6)]:
            assert _sane_rotation(bad_mb, bad_n) == (5 * 1024 * 1024, 3)

    @pytest.fixture
    def fresh_logging(self, monkeypatch):
        """setup_logging() as on a fresh start, isolated from handlers other
        tests left on the "bcm" logger; everything is restored afterwards."""
        import src.core.logger as logger_mod

        root = logging.getLogger("bcm")
        saved_handlers, saved_level = root.handlers[:], root.level
        for h in saved_handlers:
            root.removeHandler(h)
        monkeypatch.setattr(logger_mod, "_initialized", False)
        try:
            yield logger_mod
        finally:
            for h in root.handlers[:]:
                root.removeHandler(h)
                h.close()
            for h in saved_handlers:
                root.addHandler(h)
            root.setLevel(saved_level)

    def test_setup_installs_lazy_rotating_file_handler(self, tmp_path, fresh_logging):
        import logging.handlers

        log_file = tmp_path / "logs" / "bcm.log"
        fresh_logging.setup_logging(
            "INFO", str(log_file),
            {"test_overlay.mod": "DEBUG", 5: "INFO", "test_overlay.bad": ["x"]},
            max_mb=1, backups=2,
        )
        root = logging.getLogger("bcm")
        rotating = [h for h in root.handlers
                    if isinstance(h, logging.handlers.RotatingFileHandler)]
        assert len(rotating) == 1
        assert rotating[0].maxBytes == 1024 * 1024 and rotating[0].backupCount == 2
        assert not log_file.exists()          # delay=True: opened on first record
        assert logging.getLogger("bcm.test_overlay.mod").level == logging.DEBUG
        assert logging.getLogger("bcm.test_overlay.bad").level == logging.INFO

    def test_unwritable_log_file_warns_once_then_disables_itself(
            self, tmp_path, fresh_logging, capsys):
        """Read-only FS / full disk shows up at write time (delay=True). The
        stock handler prints a traceback per record — one warning instead,
        and the console (journal) keeps getting every record."""
        log_file = tmp_path / "logs" / "bcm.log"
        log_file.mkdir(parents=True)   # a directory where the file should be: fails even as root
        fresh_logging.setup_logging("DEBUG", str(log_file))
        flood = logging.getLogger("bcm.test_overlay.flood")
        for i in range(50):
            flood.debug("record %d", i)
        out = capsys.readouterr()
        assert "Traceback" not in out.err and "Logging error" not in out.err
        assert (out.out + out.err).count("file logging disabled") == 1
        assert "record 0" in out.out and "record 49" in out.out

    def test_bad_format_in_one_record_keeps_file_logging(self, tmp_path, fresh_logging, capsys,
                                                         monkeypatch):
        """Only I/O errors switch the file off — a programming error in one
        log call is that record's problem (stock handling)."""
        # pytest's capture handler on the root logger re-raises format
        # errors by design; keep the record within BCM's own handlers.
        monkeypatch.setattr(logging.getLogger("bcm"), "propagate", False)
        log_file = tmp_path / "bcm.log"
        fresh_logging.setup_logging("INFO", str(log_file))
        lg = logging.getLogger("bcm.test_overlay.fmt")
        lg.info("%d", "not a number")
        lg.info("after the bad one")
        capsys.readouterr()
        assert "after the bad one" in log_file.read_text(encoding="utf-8")

    def test_level_value(self):
        from src.core.logger import _level_value
        assert _level_value("debug", logging.INFO) == logging.DEBUG
        assert _level_value(" WARNING ", logging.INFO) == logging.WARNING
        assert _level_value(10, logging.INFO) == 10
        for bad in ("VERBOSE", "basicConfig", None, True, ["DEBUG"]):
            assert _level_value(bad, logging.INFO) == logging.INFO


# ── /api/config POST validation (web_viewer) ──────────────────────────────

class TestConfigEndpointValidation:
    def test_valid_update(self):
        from src.dashboard.web_viewer import _validate_config_update
        updates, error = _validate_config_update({
            "theme": "autodelta", "language": "en", "speed_unit": "mph",
            "temp_unit": "F", "brightness": 55.0, "aa_auto_restart": False,
            "unknown": "ignored",
        })
        assert error is None
        assert {k: v for k, _p, v in updates} == {
            "theme": "autodelta", "language": "en", "speed_unit": "mph",
            "temp_unit": "F", "brightness": 55, "aa_auto_restart": False,
        }

    @pytest.mark.parametrize("body, key", [
        ({"theme": "neon"}, "theme"),
        ({"theme": ["heritage"]}, "theme"),
        ({"language": "de"}, "language"),
        ({"speed_unit": "kmh"}, "speed_unit"),
        ({"temp_unit": "K"}, "temp_unit"),
        ({"brightness": 101}, "brightness"),
        ({"brightness": -1}, "brightness"),
        ({"brightness": "70"}, "brightness"),
        ({"brightness": True}, "brightness"),
        ({"brightness": 50.5}, "brightness"),
        ({"aa_auto_restart": "yes"}, "aa_auto_restart"),
        ({"aa_auto_restart": 1}, "aa_auto_restart"),
        ({"theme": "modern", "brightness": 500}, "brightness"),
    ])
    def test_invalid_rejected_all_or_nothing(self, body, key):
        from src.dashboard.web_viewer import _validate_config_update
        updates, error = _validate_config_update(body)
        assert updates == [] and error is not None and error[0] == key

    def test_non_object_body(self):
        from src.dashboard.web_viewer import _validate_config_update
        assert _validate_config_update(["theme"])[1] is not None

    def test_save_helper_never_raises(self):
        from src.dashboard.web_viewer import _save_config

        class Boom:
            def save(self):
                raise RuntimeError("disk on fire")

        assert _save_config(Boom(), "test") is False
