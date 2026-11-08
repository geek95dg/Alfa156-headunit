"""Tests for src/core/fsutil.py — crash-safe atomic writes."""

import json
import os
import stat
import time

import pytest

from src.core import fsutil
from src.core.fsutil import (
    atomic_write_bytes,
    atomic_write_json,
    atomic_write_text,
    cleanup_stale_tmp,
)


def _mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


def _tmp_leftovers(directory):
    return [p.name for p in directory.iterdir() if p.name.endswith(".tmp")]


class TestAtomicWrite:
    def test_writes_bytes_text_json(self, tmp_path):
        atomic_write_bytes(tmp_path / "a.bin", b"\x00\x01")
        atomic_write_text(tmp_path / "b.txt", "zażółć")
        atomic_write_json(tmp_path / "c.json", {"x": [1, 2]}, indent=1)
        assert (tmp_path / "a.bin").read_bytes() == b"\x00\x01"
        assert (tmp_path / "b.txt").read_text(encoding="utf-8") == "zażółć"
        assert json.loads((tmp_path / "c.json").read_text()) == {"x": [1, 2]}
        assert _tmp_leftovers(tmp_path) == []

    def test_replaces_existing_content(self, tmp_path):
        target = tmp_path / "f.txt"
        target.write_text("old")
        atomic_write_text(target, "new")
        assert target.read_text() == "new"

    @pytest.mark.parametrize("mode", [0o600, 0o644, 0o640])
    def test_mode_bits_honoured_regardless_of_umask(self, tmp_path, mode):
        old_umask = os.umask(0o077)
        try:
            atomic_write_text(tmp_path / "m.txt", "x", mode=mode)
        finally:
            os.umask(old_umask)
        assert _mode(tmp_path / "m.txt") == mode

    def test_mode_applies_when_replacing_a_more_open_file(self, tmp_path):
        target = tmp_path / "secret.ini"
        target.write_text("old")
        os.chmod(target, 0o666)
        atomic_write_text(target, "psk", mode=0o600)
        assert _mode(target) == 0o600

    def test_creates_missing_parent_directory(self, tmp_path):
        target = tmp_path / "a" / "b" / "c.json"
        atomic_write_json(target, [1])
        assert json.loads(target.read_text()) == [1]

    def test_replace_failure_keeps_original_and_no_tmp(self, tmp_path, monkeypatch):
        target = tmp_path / "local.yaml"
        target.write_text("original")

        def boom(src, dst):
            raise OSError("simulated power loss before rename")

        monkeypatch.setattr(fsutil.os, "replace", boom)
        with pytest.raises(OSError):
            atomic_write_text(target, "new content")
        assert target.read_text() == "original"
        assert _tmp_leftovers(tmp_path) == []

    def test_write_failure_keeps_original_and_no_tmp(self, tmp_path, monkeypatch):
        target = tmp_path / "data.json"
        target.write_text("[1]")

        def boom(fd, data):
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(fsutil.os, "write", boom)
        with pytest.raises(OSError):
            atomic_write_json(target, [2])
        assert target.read_text() == "[1]"
        assert _tmp_leftovers(tmp_path) == []

    def test_unserialisable_json_touches_nothing(self, tmp_path):
        target = tmp_path / "data.json"
        target.write_text("[1]")
        with pytest.raises(TypeError):
            atomic_write_json(target, {"x": object()})
        assert target.read_text() == "[1]"
        assert _tmp_leftovers(tmp_path) == []

    def test_rejects_non_bytes(self, tmp_path):
        with pytest.raises(TypeError):
            atomic_write_bytes(tmp_path / "x", "text, not bytes")

    def test_symlink_is_replaced_not_followed(self, tmp_path):
        """A root-owned writer must not clobber whatever a link points to."""
        victim = tmp_path / "victim.txt"
        victim.write_text("keep me")
        link = tmp_path / "link.txt"
        link.symlink_to(victim)
        atomic_write_text(link, "new")
        assert victim.read_text() == "keep me"
        assert not link.is_symlink()
        assert link.read_text() == "new"

    def test_fsync_false_still_writes(self, tmp_path):
        atomic_write_text(tmp_path / "x.txt", "fast", fsync=False)
        assert (tmp_path / "x.txt").read_text() == "fast"


class TestCleanupStaleTmp:
    def _make(self, directory, name, age_s):
        p = directory / name
        p.write_text("x")
        old = time.time() - age_s
        os.utime(p, (old, old))
        return p

    def test_removes_only_old_matching_temporaries(self, tmp_path):
        stale = self._make(tmp_path, ".local.yaml.abc123.tmp", 7200)
        stale_bak = self._make(tmp_path, ".local.yaml.bak.def456.tmp", 7200)
        young = self._make(tmp_path, ".local.yaml.zzz.tmp", 10)
        other = self._make(tmp_path, ".weather.json.abc.tmp", 7200)
        real = self._make(tmp_path, "local.yaml", 7200)

        removed = cleanup_stale_tmp(tmp_path, ".local.yaml.", max_age_s=3600)

        assert removed == 2
        assert not stale.exists() and not stale_bak.exists()
        assert young.exists() and other.exists() and real.exists()

    def test_ignores_directories_and_symlinks(self, tmp_path):
        d = tmp_path / ".local.yaml.dir.tmp"
        d.mkdir()
        target = self._make(tmp_path, "target", 7200)
        link = tmp_path / ".local.yaml.link.tmp"
        link.symlink_to(target)
        assert cleanup_stale_tmp(tmp_path, ".local.yaml.", max_age_s=0) == 0
        assert d.exists() and link.is_symlink() and target.exists()

    def test_missing_directory_is_fine(self, tmp_path):
        assert cleanup_stale_tmp(tmp_path / "nope", ".x.") == 0

    def test_empty_prefix_refused(self, tmp_path):
        with pytest.raises(ValueError):
            cleanup_stale_tmp(tmp_path, "")
