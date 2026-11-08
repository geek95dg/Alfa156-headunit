"""Tests for tools/migrate_local_config.py (device config → local.yaml)."""

import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from src.core.config import LOCAL_HEADER, BCMConfig

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "tools" / "migrate_local_config.py"

# Made-up values with the shape of the real ones (32-hex OWM key, MAC,
# DIRECT-xx SSID, 8-char PSK). Never paste real credentials here: tests
# are tracked, and the repo-wide 32-hex guard in test_multimedia.py would
# fail on a literal token anyway.
OWM_KEY = "a1b2c3d4" * 4
PHONE_MAC = "AA:BB:CC:DD:EE:01"
P2P_SSID = "DIRECT-xy"
P2P_PSK = "testpsk1"
P2P_BSSID = "02:00:00:00:00:01"
OTHER_TOKEN = "deadbeef" * 4


def _load_tool():
    spec = importlib.util.spec_from_file_location("migrate_local_config", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tool = _load_tool()

BASE = {
    "system": {"platform": "x86", "log_level": "INFO"},
    "modules": {"weather": True, "phonebook": True, "network": True,
                "blinker_monitor": False, "dashboard": True},
    "display": {"dashboard": {"theme": "heritage", "brightness": 70}},
    "audio": {"sink": "auto", "master_volume": 70},
    "gpio": {"buzzer": 84},
    "serial": {"kline": {"port_x86": "/dev/ttyUSB_kline"}},
    "wifi": {"ssid": "ALFA", "password": "87654321", "ssid_runtime": "",
             "password_runtime": "", "bssid_runtime": ""},
    "weather": {"api_key": ""},
    "travel": {"openrouteservice_key": "", "tomtom_key": ""},
    "traffic": {"api_key": ""},
    "multimedia": {"last_bt_device": ""},
}


def _device():
    """What the car's bcm_config_temp.yaml looks like after months of use."""
    import copy
    d = copy.deepcopy(BASE)
    d["system"]["platform"] = "opi"
    d["modules"].update(weather=False, phonebook=False, network=False, blinker_monitor=True)
    d["display"]["dashboard"]["theme"] = "autodelta"
    d["audio"]["sink"] = "alsa_output.usb-"
    d["gpio"]["buzzer"] = 12
    d["serial"]["kline"]["port_x86"] = "/dev/ttyUSB3"
    d["wifi"].update(ssid_runtime=P2P_SSID, password_runtime=P2P_PSK,
                     bssid_runtime=P2P_BSSID)
    d["weather"]["api_key"] = OWM_KEY
    d["travel"]["openrouteservice_key"] = "PASTE_ORS_KEY_HERE"
    d["travel"]["tomtom_key"] = "XXXXXXXX"
    d["traffic"]["api_key"] = OTHER_TOKEN       # sensitive-looking, not in SECRET_ENV_MAP
    d["multimedia"]["last_bt_device"] = PHONE_MAC
    d["multimedia"]["aa_resolution"] = "720p"
    return d


@pytest.fixture
def files(tmp_path):
    base = tmp_path / "base.yaml"
    source = tmp_path / "device.yaml"
    out = tmp_path / "local.yaml"
    base.write_text(yaml.safe_dump(BASE), encoding="utf-8")
    source.write_text(yaml.safe_dump(_device()), encoding="utf-8")
    return base, source, out


def _run(capsys, *argv):
    code = tool.main([str(a) for a in argv])
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def _run_json(capsys, *argv):
    code = tool.main([str(a) for a in argv] + ["--json"])
    captured = capsys.readouterr()
    return code, json.loads(captured.out), captured.out + captured.err


EXPECTED_OVERLAY = {
    "display": {"dashboard": {"theme": "autodelta"}},
    "audio": {"sink": "alsa_output.usb-"},
    "gpio": {"buzzer": 12},
    "serial": {"kline": {"port_x86": "/dev/ttyUSB3"}},
    "modules": {"blinker_monitor": True},
    "traffic": {"api_key": OTHER_TOKEN},
    "multimedia": {"last_bt_device": PHONE_MAC, "aa_resolution": "720p"},
}


class TestMigrate:
    def test_dry_run_writes_nothing(self, files, capsys):
        base, source, out = files
        before = sorted(p.name for p in out.parent.iterdir())
        code, text = _run(capsys, "--source", source, "--base", base, "--out", out)
        assert code == 0
        assert sorted(p.name for p in out.parent.iterdir()) == before
        assert "Dry run" in text and "WRITE" in text

    def test_write_produces_expected_overlay(self, files, capsys):
        base, source, out = files
        code, _text = _run(capsys, "--source", source, "--base", base, "--out", out, "--write")
        assert code == 0
        content = out.read_text(encoding="utf-8")
        assert content.startswith(LOCAL_HEADER + "# base: base.yaml\n")
        assert yaml.safe_load(content) == EXPECTED_OVERLAY
        assert stat.S_IMODE(os.stat(out).st_mode) == 0o600

    def test_written_overlay_loads_in_bcm_config(self, files, capsys):
        base, source, out = files
        _run(capsys, "--source", source, "--base", base, "--out", out, "--write")
        cfg = BCMConfig(str(base), "x86", local_path=out)
        assert cfg.get("display.dashboard.theme") == "autodelta"
        assert cfg.get("modules.weather") is True      # skipped: base wins
        assert cfg.get("wifi.password_runtime") == ""
        assert cfg.load_warnings == []
        # nothing for BCM to rewrite: identical to what save() would produce
        assert cfg.overlay() == EXPECTED_OVERLAY

    def test_groups_reported(self, files, capsys):
        base, source, out = files
        code, report, _raw = _run_json(capsys, "--source", source, "--base", base, "--out", out)
        assert code == 0 and report["dry_run"] and not report["written"]
        paths = {g: {i["path"] for i in report[g]} for g in ("write", "review", "dropped", "skipped")}
        assert paths["review"] == {"audio.sink", "gpio.buzzer", "serial.kline.port_x86",
                                   "modules.blinker_monitor"}
        assert paths["skipped"] == {"modules.weather", "modules.phonebook", "modules.network"}
        assert paths["dropped"] == {"system.platform", "wifi.ssid_runtime",
                                    "wifi.password_runtime", "wifi.bssid_runtime",
                                    "weather.api_key", "travel.openrouteservice_key",
                                    "travel.tomtom_key"}
        assert paths["write"] == {"display.dashboard.theme", "traffic.api_key",
                                  "multimedia.last_bt_device", "multimedia.aa_resolution"}
        owm = next(i for i in report["dropped"] if i["path"] == "weather.api_key")
        assert owm["env_var"] == "BCM_OWM_API_KEY" and "ROTATE" in owm["reason"]
        ors = next(i for i in report["dropped"] if i["path"] == "travel.openrouteservice_key")
        assert ors["reason"] == "placeholder value"

    @pytest.mark.parametrize("as_json", [False, True])
    def test_secrets_never_printed(self, files, capsys, as_json):
        base, source, out = files
        argv = ["--source", source, "--base", base, "--out", out, "--write"]
        if as_json:
            _code, _report, text = _run_json(capsys, *argv)
        else:
            _code, text = _run(capsys, *argv)
        for secret in (OWM_KEY, OTHER_TOKEN, P2P_PSK, P2P_SSID):
            assert secret not in text
        assert "BCM_OWM_API_KEY" in text
        assert "<redacted, 32 chars>" in text
        # the OWM key never reaches the overlay; the unmapped token does (0600)
        content = out.read_text()
        assert OWM_KEY not in content and OTHER_TOKEN in content

    def test_keep_source_overrides_skip(self, files, capsys):
        base, source, out = files
        code, report, _ = _run_json(capsys, "--source", source, "--base", base, "--out", out,
                                    "--keep-source", "modules.weather", "--write")
        assert code == 0
        assert yaml.safe_load(out.read_text())["modules"] == {"blinker_monitor": True,
                                                              "weather": False}
        assert "modules.weather" not in {i["path"] for i in report["skipped"]}

    def test_base_wins_only_for_device_false_over_base_true(self):
        """An old `false` must not switch off what the base enables — but a
        feature the user turned on (device true, base false) is migrated."""
        base = {"modules": {"weather": False, "route_planner": False, "phonebook": True,
                            "tracking": True}}
        device = {"modules": {"weather": True, "route_planner": True, "phonebook": False,
                              "tracking": True}}
        plan = tool.build_plan(device, base)
        assert {i["path"] for i in plan["write"]} == {"modules.weather", "modules.route_planner"}
        assert {i["path"] for i in plan["skipped"]} == {"modules.phonebook"}
        assert plan["overlay"] == {"modules": {"weather": True, "route_planner": True}}

    def test_old_default_of_a_deliberately_changed_value_is_skipped(self):
        """tracking.interval_sec: the car's file still says 30 (the old
        default) — copying it would undo the base's 5 s; a value somebody
        actually chose is migrated."""
        base = {"tracking": {"interval_sec": 5, "trip_start_kmh": 5}}
        plan = tool.build_plan({"tracking": {"interval_sec": 30, "trip_start_kmh": 5}}, base)
        assert plan["overlay"] == {}
        assert [i["path"] for i in plan["skipped"]] == ["tracking.interval_sec"]
        assert plan["skipped"][0]["base"] == 5 and plan["skipped"][0]["source"] == 30
        plan = tool.build_plan({"tracking": {"interval_sec": 10}}, base)
        assert plan["overlay"] == {"tracking": {"interval_sec": 10}}
        plan = tool.build_plan({"tracking": {"interval_sec": 30}}, base,
                               keep_source=["tracking.interval_sec"])
        assert plan["overlay"] == {"tracking": {"interval_sec": 30}}

    def test_real_device_file_does_not_undo_the_gpx_interval(self):
        """Dry run on the tracked device file against the tracked test base."""
        source = yaml.safe_load((REPO / "config" / "bcm_config_temp.yaml").read_text())
        base = yaml.safe_load((REPO / "config" / "bcm_config_test.yaml").read_text())
        plan = tool.build_plan(source, base)
        assert "interval_sec" not in plan["overlay"].get("tracking", {})
        assert "tracking.interval_sec" in {i["path"] for i in plan["skipped"]}

    def test_exclude(self, files, capsys):
        base, source, out = files
        _run(capsys, "--source", source, "--base", base, "--out", out,
             "--exclude", "gpio", "--exclude", "multimedia.aa_resolution", "--write")
        data = yaml.safe_load(out.read_text())
        assert "gpio" not in data and "aa_resolution" not in data["multimedia"]

    def test_refuses_to_overwrite_existing(self, files, capsys):
        base, source, out = files
        out.write_text("display:\n  dashboard:\n    theme: modern\n")
        code, text = _run(capsys, "--source", source, "--base", base, "--out", out, "--write")
        assert code == 1 and "already exists" in text
        assert out.read_text() == "display:\n  dashboard:\n    theme: modern\n"
        # a dry run only warns
        code, text = _run(capsys, "--source", source, "--base", base, "--out", out)
        assert code == 0 and "would refuse" in text

    def test_force_overwrites_and_keeps_backup(self, files, capsys):
        base, source, out = files
        out.write_text("display:\n  dashboard:\n    theme: modern\n")
        code, _ = _run(capsys, "--source", source, "--base", base, "--out", out, "--write", "--force")
        assert code == 0
        assert yaml.safe_load(out.read_text()) == EXPECTED_OVERLAY
        bak = out.with_name("local.yaml.bak")
        assert yaml.safe_load(bak.read_text()) == {"display": {"dashboard": {"theme": "modern"}}}

    def test_merge_existing_values_win(self, files, capsys):
        base, source, out = files
        out.write_text("display:\n  dashboard:\n    theme: modern\nextra: 1\n")
        code, _ = _run(capsys, "--source", source, "--base", base, "--out", out,
                       "--write", "--merge-existing")
        assert code == 0
        data = yaml.safe_load(out.read_text())
        assert data["display"]["dashboard"]["theme"] == "modern"
        assert data["extra"] == 1
        assert data["audio"]["sink"] == "alsa_output.usb-"

    def test_merge_into_broken_file_is_an_error(self, files, capsys):
        base, source, out = files
        out.write_text("- not\n- a mapping\n")
        code, _ = _run(capsys, "--source", source, "--base", base, "--out", out,
                       "--write", "--merge-existing")
        assert code == 1
        assert out.read_text() == "- not\n- a mapping\n"

    def test_force_and_merge_are_exclusive(self, files, capsys):
        base, source, out = files
        code, _ = _run(capsys, "--source", source, "--base", base, "--out", out,
                       "--force", "--merge-existing")
        assert code == 1

    def test_nothing_to_migrate(self, files, capsys):
        base, _source, out = files
        code, _ = _run(capsys, "--source", base, "--base", base, "--out", out, "--write")
        assert code == 2 and not out.exists()

    def test_only_dropped_values_is_nothing_to_migrate(self, files, capsys, tmp_path):
        base, _source, out = files
        import copy
        d = copy.deepcopy(BASE)
        d["wifi"]["password_runtime"] = P2P_PSK
        d["weather"]["api_key"] = OWM_KEY
        src = tmp_path / "only_dropped.yaml"
        src.write_text(yaml.safe_dump(d))
        code, text = _run(capsys, "--source", src, "--base", base, "--out", out, "--write")
        assert code == 2 and not out.exists()
        assert OWM_KEY not in text and "BCM_OWM_API_KEY" in text

    @pytest.mark.parametrize("bad", ["- list\n", "a: [unclosed\n"])
    def test_bad_source_is_an_error_without_echoing_content(self, files, capsys, tmp_path, bad):
        base, _source, out = files
        src = tmp_path / "bad.yaml"
        src.write_text(bad + f"# {OWM_KEY}\n")
        code, text = _run(capsys, "--source", src, "--base", base, "--out", out)
        assert code == 1 and OWM_KEY not in text

    def test_missing_source(self, files, capsys, tmp_path):
        base, _source, out = files
        code, _ = _run(capsys, "--source", tmp_path / "nope.yaml", "--base", base, "--out", out)
        assert code == 1

    def test_out_must_not_be_base(self, files, capsys):
        base, source, _out = files
        before = base.read_text()
        code, _ = _run(capsys, "--source", source, "--base", base, "--out", base, "--write", "--force")
        assert code == 1 and base.read_text() == before

    def test_invalid_dotpath_rejected(self, files, capsys):
        base, source, out = files
        code, _ = _run(capsys, "--source", source, "--base", base, "--out", out,
                       "--exclude", "../etc")
        assert code == 1

    def test_runs_as_a_script(self, files):
        """sys.path handling: `python tools/migrate_local_config.py` from any cwd."""
        base, source, out = files
        proc = subprocess.run(
            [sys.executable, str(TOOL), "--source", str(source), "--base", str(base),
             "--out", str(out), "--json"],
            capture_output=True, text=True, timeout=60, cwd=str(out.parent),
        )
        assert proc.returncode == 0, proc.stderr
        assert json.loads(proc.stdout)["dry_run"] is True
        assert OWM_KEY not in proc.stdout + proc.stderr
        assert not out.exists()
