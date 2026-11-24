"""The car's final config (config/bcm_config.yaml, 23.11) and the move to it.

bcm_config.yaml became the base the units run: everything that ran on the
test config plus the car's own local.yaml settings, with the safety flags
still in their safe mode. These tests pin that state explicitly, and the
base-change path: BCM freezes a local.yaml written for bcm_config_test.yaml
with a one-line migrate instruction (log + Settings), and
tools/migrate_local_config.py rewrites it.
"""

from __future__ import annotations

import importlib.util
import logging
import re
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from src.core import config as config_mod
from src.core import modules_catalog as mc
from src.core.config import LOCAL_HEADER, SECRET_ENV_MAP, BCMConfig, iter_leaves
from src.core.event_bus import EventBus
from src.dashboard.web_viewer import WebViewer

REPO = Path(__file__).resolve().parent.parent
FINAL = REPO / "config" / "bcm_config.yaml"
BENCH = REPO / "config" / "bcm_config_test.yaml"
TOOL = REPO / "tools" / "migrate_local_config.py"

# Made-up phone address with the shape of the real one — never a real MAC.
FAKE_MAC = "AA:BB:CC:DD:EE:42"


def _load(path=FINAL):
    return BCMConfig(config_path=str(path), platform_override="x86", local_path=None, env={})


def _raw(path=FINAL):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


# ── what the final config contains ───────────────────────────────────────

#: Modules the car runs on the final config (test-config modules + the car's
#: local.yaml toggles + this batch's modules; owner decisions applied).
ON = {
    "dashboard", "multimedia", "input", "audio", "bluetooth", "phonebook", "phone_status",
    "wifi_ap", "net_diag", "weather", "weather_alerts", "route_planner", "traffic_alerts",
    "voice_announce", "location", "tracking", "trip_gps", "fuel_log", "car_phone",
    "car_phone_hotspot", "phone_sensors", "car_phone_agent", "traccar", "auto_brightness",
    "blinker_monitor", "performance", "last_park",
}


class TestFinalModules:
    def test_every_catalog_module_is_listed_explicitly(self):
        # No toggle falls back to a code default the reader cannot see.
        assert set(_raw()["modules"]) == set(mc.MODULES)

    def test_exactly_these_modules_are_on(self):
        cfg = _load()
        on = {name for name in mc.MODULES if mc.is_enabled(cfg, name)}
        assert on == ON
        states = mc.module_states(cfg)
        assert {n for n, st in states.items() if st.runs} == ON   # no dependency missing

    @pytest.mark.parametrize("name", ["network", "crash_detect", "phone_tether"])
    def test_owner_decisions_are_off(self, name):
        # network / crash_detect: off in the car's local.yaml; phone_tether:
        # decision 23.11 (the Redmi stays in the car, BT PAN only a fallback).
        assert mc.is_enabled(_load(), name) is False

    def test_phone_tether_comment_says_it_is_the_fallback(self):
        lines = FINAL.read_text(encoding="utf-8").splitlines()
        i = next(n for n, l in enumerate(lines) if l.strip().startswith("phone_tether:"))
        block = [lines[i]]
        for l in lines[i + 1:]:
            if not l.strip().startswith("#"):
                break
            block.append(l)
        comment = " ".join(block)
        assert "ZAPASOWA" in comment and "23.11" in comment

    def test_traccar_is_on_but_inert_without_url_and_device_id(self):
        cfg = _load()
        assert mc.is_enabled(cfg, "traccar") is True
        assert cfg.get("traccar.url") == ""
        assert not cfg.get("traccar.device_id")                    # env only
        text = FINAL.read_text(encoding="utf-8")
        assert "NIC NIE" in text and "BCM_TRACCAR_DEVICE_ID" in text

    @pytest.mark.parametrize("name", ["crash_sms", "call112", "parking_guard", "cabin_watch",
                                      "remote_session"])
    def test_nothing_that_sends_or_dials_by_itself_is_on(self, name):
        assert mc.module_states(_load())[name].runs is False


class TestFinalSafety:
    def test_safety_flags_stay_safe(self):
        cfg = _load()
        assert cfg.get("crash_detection.sms.dry_run") is True
        assert cfg.get("parking_guard.log_only") is True
        assert cfg.get("safety.call112.test_mode") is True
        assert cfg.get("safety.call112.test_number") == ""

    def test_arming_is_explained_next_to_each_flag(self):
        text = FINAL.read_text(encoding="utf-8")
        for snippet in ("crash_detection: {sms: {dry_run: false}}",
                        "safety: {call112: {test_mode: false}}",
                        "parking_guard: {log_only: false}"):
            assert snippet in text, snippet

    def test_network_access_is_tracking_only(self):
        cfg = _load()
        assert cfg.get("dashboard.remote_access") == "tracking"
        assert cfg.get("dashboard.allowed_networks") == ["10.0.0.0/8", "172.16.0.0/12",
                                                         "192.168.0.0/16"]

    def test_no_secret_values(self):
        raw = _raw()
        for dotpath in SECRET_ENV_MAP:
            if dotpath.startswith("wifi."):
                continue              # the AA Wi-Fi Direct PSK is a shipped default
            assert not config_mod.get_path(raw, dotpath), dotpath
        text = FINAL.read_text(encoding="utf-8")
        assert not re.search(r"\b[0-9a-fA-F]{32}\b", text)         # OWM-style key

    def test_no_macs_phone_numbers_or_runtime_values(self):
        raw = _raw()
        assert raw["multimedia"]["last_bt_device"] == ""          # runtime, local.yaml only
        for path, value in iter_leaves(raw):
            if not isinstance(value, str):
                continue
            assert not re.fullmatch(r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", value), path
            assert not re.fullmatch(r"\+?[0-9]{9,15}", value), path
            if path.endswith("_runtime"):
                assert value == "", path
        # comments use placeholders only (AA:BB:…, +48601234567 style examples)
        text = FINAL.read_text(encoding="utf-8")
        macs = set(re.findall(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}", text))
        assert macs <= {"AA:BB:CC:DD:EE:FF"}, macs


class TestFinalContent:
    def test_every_bench_key_is_in_the_final_config(self):
        bench = dict(iter_leaves(_raw(BENCH)))
        final = dict(iter_leaves(_raw()))
        assert set(bench) <= set(final), sorted(set(bench) - set(final))

    def test_prod_only_blocks_are_kept(self):
        raw = _raw()
        assert raw["esp32_display"]["port"] == "/dev/ttyACM_display"
        assert len(raw["swc"]["buttons"]) == 12
        assert raw["multimedia"]["aa_connection_timeout"] == 90

    def test_car_settings_moved_from_local_yaml(self):
        cfg = _load()
        assert cfg.get("audio.sink") == "alsa_output.usb-"
        assert cfg.get("display.dashboard.theme") == "autodelta"
        assert cfg.get("display.dashboard.brightness") == 62
        assert cfg.get("fuel_sender.enabled") is False
        assert cfg.get("multimedia.aa_auto_restart") is True
        assert cfg.get("swc.mapping.mute") == ["SWC_VOICE", "SWC2_MUTE"]

    def test_screen_is_7_inch_with_the_10_inch_values_in_comments(self):
        cfg = _load()
        for key in ("dashboard", "multimedia"):
            assert (cfg.get(f"display.{key}.width"), cfg.get(f"display.{key}.height")) == (1024, 600)
        text = FINAL.read_text(encoding="utf-8")
        assert text.count('# 10,1": 1280') == 2 and text.count('# 10,1": 800') == 2

    def test_bench_config_says_what_it_is(self):
        head = BENCH.read_text(encoding="utf-8").split("system:", 1)[0]
        assert "ROZWOJOWA / STANOWISKOWA" in head
        assert "config/bcm_config.yaml" in head
        assert "BCM_CONFIG=config/bcm_config_test.yaml" in head

    def test_final_header_explains_rollback(self):
        head = FINAL.read_text(encoding="utf-8").split("system:", 1)[0]
        assert "BCM_CONFIG=config/bcm_config_test.yaml" in head
        assert "Przejście na konfigurację docelową" in head


# ── BCM under the new base with a local.yaml for the old one ─────────────

def _tmp_bases(tmp_path):
    """Copies of both shipped bases next to one local.yaml (as in config/)."""
    final = tmp_path / "bcm_config.yaml"
    bench = tmp_path / "bcm_config_test.yaml"
    shutil.copy(FINAL, final)
    shutil.copy(BENCH, bench)
    return final, bench


CAR_LOCAL = {
    "audio": {"sink": "alsa_output.usb-"},
    "display": {"dashboard": {"brightness": 62, "theme": "autodelta"}},
    "fuel_sender": {"enabled": False},
    "modules": {"auto_brightness": True, "blinker_monitor": True, "car_phone": True,
                "car_phone_agent": True, "car_phone_hotspot": True, "crash_detect": False,
                "network": False, "performance": True, "phone_sensors": True,
                "phone_tether": True},
    "multimedia": {"aa_auto_restart": True, "last_bt_device": FAKE_MAC},
    "swc": {"mapping": {"mute": ["SWC_VOICE", "SWC2_MUTE"]}},
}


def _write_car_local(path):
    """The car's local.yaml as BCM wrote it under bcm_config_test.yaml."""
    path.write_text(config_mod.render_overlay(CAR_LOCAL, base_name="bcm_config_test.yaml"),
                    encoding="utf-8")
    path.chmod(0o600)


class TestBaseChangeOnLoad:
    def test_frozen_with_the_exact_migrate_command(self, tmp_path, caplog):
        final, _ = _tmp_bases(tmp_path)
        local = tmp_path / "local.yaml"
        _write_car_local(local)
        before = local.read_bytes()
        with caplog.at_level(logging.INFO):
            cfg = BCMConfig(str(final), "x86", local_path=local, env={})
        # overrides still apply (absolute values) ...
        assert cfg.get("multimedia.last_bt_device") == FAKE_MAC
        assert cfg.get("modules.phone_tether") is True
        # ... but nothing is saved until the overlay is migrated
        cfg.set("display.dashboard.theme", "modern")
        assert cfg.save() is False
        assert local.read_bytes() == before
        info = cfg.base_migration
        assert info["recorded"] == "bcm_config_test.yaml" and info["base"] == "bcm_config.yaml"
        assert info["command"].endswith(f"--source {local} --base {final}")
        assert "tools/migrate_local_config.py" in info["command"]
        lines = [w for w in cfg.load_warnings if "bcm_config_test.yaml" in w]
        assert len(lines) == 1 and "\n" not in lines[0]
        assert info["command"] in lines[0] and "--write" in lines[0]
        assert FAKE_MAC not in lines[0]                      # never a value

    def test_repo_paths_are_relative_in_the_command(self):
        cmd = config_mod.migration_command(REPO / "config" / "local.yaml", FINAL)
        assert cmd == (f"cd {REPO} && sudo .venv/bin/python tools/migrate_local_config.py "
                       f"--source config/local.yaml --base config/bcm_config.yaml")

    def test_rollback_direction_is_frozen_without_a_migration_hint(self, tmp_path):
        # local.yaml already for bcm_config.yaml, BCM_CONFIG back on the test
        # config: frozen as before, but no invitation to migrate backwards.
        _, bench = _tmp_bases(tmp_path)
        local = tmp_path / "local.yaml"
        local.write_text(config_mod.render_overlay({"multimedia": {"last_bt_device": FAKE_MAC}},
                                                   base_name="bcm_config.yaml"))
        cfg = BCMConfig(str(bench), "x86", local_path=local, env={})
        assert cfg.base_migration is None
        assert cfg.save() is False
        assert any("saving is disabled" in w for w in cfg.load_warnings)

    def test_rollback_after_migration_names_the_backup(self, tmp_path):
        # After --write the overlay holds almost nothing; on the old base the
        # car would run without its settings — the log line says how to put
        # the pre-migration copy back (paths only, never a value).
        _, bench = _tmp_bases(tmp_path)
        local = tmp_path / "local.yaml"
        local.write_text(config_mod.render_overlay({"multimedia": {"last_bt_device": FAKE_MAC}},
                                                   base_name="bcm_config.yaml"))
        bak = tmp_path / "local.yaml.bcm_config_test.bak"
        _write_car_local(bak)
        cfg = BCMConfig(str(bench), "x86", local_path=local, env={})
        assert cfg.base_migration is None and cfg.save() is False
        lines = [w for w in cfg.load_warnings if "sudo cp -p" in w]
        assert len(lines) == 1 and "\n" not in lines[0]
        assert f"sudo cp -p {bak} {local}" in lines[0] and FAKE_MAC not in lines[0]

    def test_temp_era_overlay_migrates_from_the_temp_file(self):
        # An overlay for bcm_config_temp.yaml holds only differences from that
        # file; the car's settings are in the temp file itself — so the
        # source is the temp file and --merge-existing keeps the overlay.
        cmd = config_mod.migration_command(REPO / "config" / "local.yaml", FINAL,
                                           "bcm_config_temp.yaml")
        assert cmd.endswith("--source config/bcm_config_temp.yaml --base config/bcm_config.yaml"
                            " --out config/local.yaml --merge-existing")

    def test_command_names_a_non_default_overlay_as_out(self, tmp_path):
        other = tmp_path / "elsewhere.yaml"
        cmd = config_mod.migration_command(other, FINAL)
        assert cmd.endswith(f"--source {other} --base config/bcm_config.yaml --out {other}")

    def test_matching_base_has_no_hint(self, tmp_path):
        final, _ = _tmp_bases(tmp_path)
        local = tmp_path / "local.yaml"
        local.write_text(config_mod.render_overlay({"language": "en"},
                                                   base_name="bcm_config.yaml"))
        cfg = BCMConfig(str(final), "x86", local_path=local, env={})
        assert cfg.base_migration is None and cfg.load_warnings == []


class TestModulesApiBanner:
    def _client(self, cfg):
        cfg.save = lambda path=None: False
        viewer = WebViewer(host="127.0.0.1", port=5099, event_bus=EventBus(), config=cfg)
        return SimpleNamespace(client=viewer._build_app().test_client())

    def test_get_modules_carries_the_migration(self, tmp_path):
        final, _ = _tmp_bases(tmp_path)
        local = tmp_path / "local.yaml"
        _write_car_local(local)
        cfg = BCMConfig(str(final), "x86", local_path=local, env={})
        body = self._client(cfg).client.get("/api/modules").get_json()
        mig = body["config_migration"]
        assert set(mig) == {"recorded", "base", "command"}
        assert mig["command"] == cfg.base_migration["command"]
        assert FAKE_MAC not in str(body)

    def test_none_without_a_base_change(self):
        body = self._client(_load()).client.get("/api/modules").get_json()
        assert body["config_migration"] is None


# ── tools/migrate_local_config.py: test → final ──────────────────────────

def _tool():
    spec = importlib.util.spec_from_file_location("migrate_local_config_final", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tool = _tool()


def _run(capsys, *argv):
    code = tool.main([str(a) for a in argv])
    out = capsys.readouterr()
    return code, out.out + out.err


class TestMigrateTestToFinal:
    def test_dry_run_shows_the_plan_and_writes_nothing(self, tmp_path, capsys):
        final, _ = _tmp_bases(tmp_path)
        local = tmp_path / "local.yaml"
        _write_car_local(local)
        before = local.read_bytes()
        listing = sorted(p.name for p in tmp_path.iterdir())
        code, text = _run(capsys, "--source", local, "--base", final)
        assert code == 0
        assert local.read_bytes() == before
        assert sorted(p.name for p in tmp_path.iterdir()) == listing
        assert "overlay for base bcm_config_test.yaml" in text
        assert "WRITE (1)" in text and "multimedia.last_bt_device" in text
        assert "SKIPPED (1)" in text and "modules.phone_tether" in text
        assert "IN BASE (15)" in text and "audio.sink" in text and "swc.mapping.mute" in text
        assert "Dry run" in text and "local.yaml.bcm_config_test.bak" in text

    def test_write_gives_the_minimal_diff_with_the_new_header(self, tmp_path, capsys):
        final, _ = _tmp_bases(tmp_path)
        local = tmp_path / "local.yaml"
        _write_car_local(local)
        before = local.read_bytes()
        code, _ = _run(capsys, "--source", local, "--base", final, "--write")
        assert code == 0
        text = local.read_text(encoding="utf-8")
        assert text.startswith(LOCAL_HEADER + "# base: bcm_config.yaml\n")
        assert yaml.safe_load(text) == {"multimedia": {"last_bt_device": FAKE_MAC}}
        assert (local.stat().st_mode & 0o777) == 0o600
        backup = tmp_path / "local.yaml.bcm_config_test.bak"
        assert backup.read_bytes() == before and (backup.stat().st_mode & 0o777) == 0o600
        # BCM now saves again, and the effective config is the car's
        cfg = BCMConfig(str(final), "x86", local_path=local, env={})
        assert cfg.base_migration is None
        assert cfg.get("modules.phone_tether") is False
        assert cfg.get("multimedia.last_bt_device") == FAKE_MAC
        for path, value in iter_leaves(CAR_LOCAL):
            if path != "modules.phone_tether":
                assert cfg.get(path) == value, path
        cfg.set("display.dashboard.theme", "modern")
        assert cfg.save() is True
        # a second run finds nothing to do
        code, text = _run(capsys, "--source", local, "--base", final)
        assert code == 2 and "already written for base bcm_config.yaml" in text

    def test_keep_source_keeps_bluetooth_pan(self, tmp_path, capsys):
        final, _ = _tmp_bases(tmp_path)
        local = tmp_path / "local.yaml"
        _write_car_local(local)
        code, _ = _run(capsys, "--source", local, "--base", final, "--write",
                       "--keep-source", "modules.phone_tether")
        assert code == 0
        assert yaml.safe_load(local.read_text())["modules"] == {"phone_tether": True}

    def test_values_the_user_never_set_follow_the_new_base(self, tmp_path, capsys):
        # crash_detect is on in the test base and off in the final one; an
        # overlay that never mentioned it must not carry the old base along.
        final, _ = _tmp_bases(tmp_path)
        local = tmp_path / "local.yaml"
        local.write_text(config_mod.render_overlay({"language": "en"},
                                                   base_name="bcm_config_test.yaml"))
        code, _ = _run(capsys, "--source", local, "--base", final, "--write")
        assert code == 0
        assert yaml.safe_load(local.read_text()) == {"language": "en"}

    def test_overlay_equal_to_the_base_still_gets_the_new_header(self, tmp_path, capsys):
        final, _ = _tmp_bases(tmp_path)
        local = tmp_path / "local.yaml"
        local.write_text(config_mod.render_overlay({"audio": {"sink": "alsa_output.usb-"}},
                                                   base_name="bcm_config_test.yaml"))
        code, _ = _run(capsys, "--source", local, "--base", final, "--write")
        assert code == 0
        text = local.read_text()
        assert "# base: bcm_config.yaml" in text and yaml.safe_load(text) == {}
        cfg = BCMConfig(str(final), "x86", local_path=local, env={})
        assert cfg.base_migration is None
        cfg.set("language", "en")
        assert cfg.save() is True

    def test_secret_in_the_overlay_blocks_write_until_drop_secrets(self, tmp_path, capsys):
        # A key typed in the UI lives in the overlay; dropping it silently
        # would leave the feature keyless after the rewrite.
        final, _ = _tmp_bases(tmp_path)
        local = tmp_path / "local.yaml"
        secret = "f00dfeed" * 4
        local.write_text(config_mod.render_overlay({"weather": {"api_key": secret}},
                                                   base_name="bcm_config_test.yaml"))
        before = local.read_bytes()
        code, text = _run(capsys, "--source", local, "--base", final)
        assert code == 0 and "would refuse" in text and "BCM_OWM_API_KEY" in text
        assert secret not in text
        code, text = _run(capsys, "--source", local, "--base", final, "--write")
        assert code == 1 and "--drop-secrets" in text and "BCM_OWM_API_KEY" in text
        assert secret not in text and local.read_bytes() == before
        assert not (tmp_path / "local.yaml.bcm_config_test.bak").exists()
        code, text = _run(capsys, "--source", local, "--base", final, "--write",
                          "--drop-secrets")
        assert code == 0 and secret not in text and "BCM_OWM_API_KEY" in text
        assert secret not in local.read_text()

    def test_non_default_overlay_is_rewritten_in_place_with_out(self, tmp_path, capsys):
        final, _ = _tmp_bases(tmp_path)
        other = tmp_path / "sub" / "car.yaml"
        other.parent.mkdir()
        _write_car_local(other)
        code, _ = _run(capsys, "--source", other, "--base", final, "--out", other, "--write")
        assert code == 0 and not (tmp_path / "local.yaml").exists()
        assert "# base: bcm_config.yaml" in other.read_text()

    def test_in_place_rewrite_needs_an_overlay_header(self, tmp_path, capsys):
        final, _ = _tmp_bases(tmp_path)
        device = tmp_path / "device.yaml"
        device.write_text(yaml.safe_dump({"language": "en"}))
        code, text = _run(capsys, "--source", device, "--base", final, "--out", device)
        assert code == 1 and "only an overlay" in text

    def test_merge_existing_in_place_is_refused(self, tmp_path, capsys):
        final, _ = _tmp_bases(tmp_path)
        local = tmp_path / "local.yaml"
        _write_car_local(local)
        code, text = _run(capsys, "--source", local, "--base", final, "--merge-existing")
        assert code == 1 and "--merge-existing" in text

    def test_decisions_are_short_and_known(self):
        for base, decisions in tool.BASE_DECISIONS.items():
            assert (REPO / "config" / base).is_file()
            for path, why in decisions.items():
                assert path.startswith("modules.") and path[8:] in mc.MODULES
                assert why and len(why) < 120
