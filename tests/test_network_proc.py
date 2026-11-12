"""Shared helpers for modules that drive nmcli/adb (src/network/_proc.py).

Nothing is executed: every test passes a fake ``subprocess.run`` compatible
runner. ``phone_tether`` must keep using exactly these objects (its own
suite, tests/test_phone_tether.py, pins its behaviour end to end).
"""

import logging
import math
import subprocess
from types import SimpleNamespace

import pytest

from src.network import _proc
from src.network import phone_tether as pt


class Runner:
    """Records calls; returns ``result`` or raises ``exc``."""

    def __init__(self, result=None, exc=None):
        self.calls = []
        self.result = result if result is not None else subprocess.CompletedProcess([], 0, "", "")
        self.exc = exc

    def __call__(self, argv, **kw):
        self.calls.append((argv, kw))
        if self.exc is not None:
            raise self.exc
        return self.result


@pytest.fixture(autouse=True)
def fresh_missing_set(monkeypatch):
    monkeypatch.setattr(_proc, "_missing_warned", set())


class TestRun:
    def test_argv_list_timeout_and_untranslated_env(self, monkeypatch):
        monkeypatch.setenv("LANGUAGE", "pl_PL")
        monkeypatch.setenv("LC_ALL", "pl_PL.UTF-8")
        runner = Runner(subprocess.CompletedProcess([], 0, "running\n", ""))
        assert _proc._run(runner, ("nmcli", "-t", "general"), 5) == (0, "running\n", "")
        argv, kw = runner.calls[0]
        assert argv == ["nmcli", "-t", "general"] and isinstance(argv, list)
        assert "shell" not in kw
        assert kw["timeout"] == 5 and kw["capture_output"] is True and kw["text"] is True
        assert kw["env"]["LC_ALL"] == "C" and "LANGUAGE" not in kw["env"]

    def test_env_extra(self):
        runner = Runner()
        _proc._run(runner, ["adb", "devices"], env_extra={"HOME": "/root"})
        assert runner.calls[0][1]["env"]["HOME"] == "/root"
        assert runner.calls[0][1]["env"]["LC_ALL"] == "C"

    def test_stderr_is_cleaned_stdout_kept(self):
        runner = Runner(subprocess.CompletedProcess([], 3, "a\nb\n", "Error:\n\x1b[31mx" + "y" * 500))
        rc, out, err = _proc._run(runner, ["nmcli"])
        assert (rc, out) == (3, "a\nb\n")
        assert "\n" not in err and "\x1b" not in err and len(err) == _proc.ERROR_MAX

    def test_raw_stderr_keeps_lines_and_is_bounded(self):
        # adb's getFunctions answer is a line of its own on stderr, after
        # whatever the ROM's linker warns about — cleaned it would be lost.
        text = "WARNING: linker: /system/bin/svc: unused DT entry\nrndis,adb\n"
        runner = Runner(subprocess.CompletedProcess([], 0, "", text))
        assert _proc._run(runner, ["adb"], raw_stderr=True) == (0, "", text)
        assert _proc._run(runner, ["adb"])[2] == " ".join(text.split())   # default: cleaned
        runner = Runner(subprocess.CompletedProcess([], 0, "", "x" * 10000))
        assert len(_proc._run(runner, ["adb"], raw_stderr=True)[2]) == _proc.RAW_STDERR_MAX
        # Errors of the runner itself stay the short, cleaned messages.
        runner = Runner(exc=subprocess.TimeoutExpired(["adb"], 3))
        assert _proc._run(runner, ["adb"], 3, raw_stderr=True) == (
            _proc.RC_TIMEOUT, "", "adb timed out after 3 s")

    def test_bytes_and_odd_results_never_raise(self):
        runner = Runner(SimpleNamespace(returncode=0, stdout=b"ok\xff", stderr=b"warn"))
        assert _proc._run(runner, ["adb"]) == (0, "ok�", "warn")
        runner = Runner(SimpleNamespace(returncode="0", stdout=object(), stderr=None))
        rc, out, err = _proc._run(runner, ["adb"])
        assert rc == 1 and isinstance(out, str) and err == ""
        runner = Runner(SimpleNamespace(returncode=True, stdout="", stderr=""))
        assert _proc._run(runner, ["adb"])[0] == 1       # bool is not an exit status

    def test_missing_binary_is_127_with_one_warning(self, caplog):
        runner = Runner(exc=FileNotFoundError("adb"))
        with caplog.at_level(logging.WARNING):
            for _ in range(3):
                assert _proc._run(runner, ["adb", "devices"]) == (127, "", "adb not installed")
        assert sum("adb is not installed" in r.getMessage() for r in caplog.records) == 1

    def test_missing_binary_callback_replaces_the_default_warning(self, caplog):
        seen = []
        runner = Runner(exc=FileNotFoundError("nmcli"))
        with caplog.at_level(logging.WARNING):
            rc, _out, _err = _proc._run(runner, ["nmcli"], on_missing=seen.append)
        assert rc == _proc.RC_MISSING and seen == ["nmcli"]
        assert not any("not installed" in r.getMessage() for r in caplog.records)
        # a broken callback must not break the caller's loop
        assert _proc._run(runner, ["nmcli"], on_missing=lambda p: 1 / 0)[0] == 127

    def test_timeout_is_124(self):
        runner = Runner(exc=subprocess.TimeoutExpired(["adb"], 8))
        assert _proc._run(runner, ["adb", "shell", "dumpsys", "battery"], 8.0) == \
            (124, "", "adb timed out after 8 s")

    def test_other_errors_are_1_and_cleaned(self):
        runner = Runner(exc=ValueError("embedded null\nbyte"))
        assert _proc._run(runner, ["adb"]) == (1, "", "adb: embedded null byte")

    @pytest.mark.parametrize("argv", ["nmcli general", b"nmcli", [], (), None,
                                      ["nmcli", 5], ["adb", None], {"adb": 1}])
    def test_anything_but_a_list_of_strings_is_refused(self, argv):
        runner = Runner()
        rc, out, err = _proc._run(runner, argv)
        assert rc == _proc.RC_BAD_ARGV and out == "" and err
        assert runner.calls == []


class TestNumber:
    def test_clamps_and_falls_back(self):
        assert _proc._number("network.car_phone", 5, 30, 10, 60, "check_sec") == 10
        assert _proc._number("network.car_phone", 90.5, 30, 10, 60, "check_sec") == 60
        assert _proc._number("network.car_phone", 20, 30, 10, 60, "check_sec") == 20
        assert _proc._number("network.car_phone", None, 30, 10, 60, "check_sec") == 30

    @pytest.mark.parametrize("bad", [True, False, "15", float("nan"), math.inf, [1]])
    def test_rejects_non_numbers_with_the_full_key(self, bad, caplog):
        with caplog.at_level(logging.WARNING):
            assert _proc._number("network.car_phone", bad, 30, 10, 60, "check_sec") == 30
        assert any(r.getMessage().startswith("network.car_phone.check_sec=")
                   for r in caplog.records)

    def test_phone_tether_keeps_its_prefix(self, caplog):
        with caplog.at_level(logging.WARNING):
            assert pt._number("x", 60, 5, 3600, "retry_sec") == 60
        assert any(r.getMessage().startswith("network.phone_tether.retry_sec=")
                   for r in caplog.records)


class TestCfgGet:
    def test_dict_and_dotted_getter(self):
        cfg = {"network": {"car_phone": {"serial": "abc"}}}
        assert _proc._cfg_get(cfg, "network.car_phone.serial") == "abc"
        assert _proc._cfg_get(cfg, "network.car_phone.nope", 7) == 7
        assert _proc._cfg_get(None, "a.b", 1) == 1

        class Cfg:
            def get(self, path):
                return {"a.b": 2}.get(path)

        assert _proc._cfg_get(Cfg(), "a.b") == 2
        assert _proc._cfg_get(Cfg(), "a.c", 3) == 3

        class Broken:
            def get(self, path):
                raise RuntimeError("boom")

        assert _proc._cfg_get(Broken(), "a.b", 4) == 4


class TestPhoneTetherReexports:
    def test_same_objects(self):
        for name in ("clean_error", "split_terse", "parse_ip_status", "_cfg_get",
                     "proc_env", "ERROR_MAX", "IFACE_RE", "PROBE_TIMEOUT_S"):
            assert getattr(pt, name) is getattr(_proc, name), name

    def test_nm_uses_the_shared_runner(self, caplog):
        tether = pt.PhoneTether({}, SimpleNamespace(), runner=Runner(exc=FileNotFoundError("nmcli")))
        with caplog.at_level(logging.WARNING):
            assert tether._nm(["nmcli", "general"]) == (127, "", "nmcli not installed")
            assert tether._nm(["nmcli", "device"])[0] == 127
        msgs = [r.getMessage() for r in caplog.records]
        assert sum("Phone tether: nmcli not installed" in m for m in msgs) == 1
        assert not any("nmcli is not installed" in m for m in msgs)   # no second, generic one
