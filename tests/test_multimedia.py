"""Tests for Multimedia module (Part 11) — Bluetooth + OpenAuto + AA Display."""

import pathlib
import re
import shutil
import subprocess

import pytest

from src.core.event_bus import EventBus
from src.core.config import BCMConfig
from src.multimedia.bluetooth import BluetoothManager
from src.multimedia.openauto import OpenAutoController, _find_openauto
from legacy.src.multimedia.aa_display import AADisplaySimulator


# ---------------------------------------------------------------------------
# Bluetooth Manager tests
# ---------------------------------------------------------------------------

class TestBluetoothManager:
    def setup_method(self):
        self.bus = EventBus()
        self.config = BCMConfig(platform_override="x86")

    def test_initial_state(self):
        bt = BluetoothManager(self.config, self.bus)
        assert bt.connected is False
        assert bt.connected_device is None
        assert bt.a2dp_active is False
        assert bt.hfp_active is False

    def test_simulated_connect(self):
        bt = BluetoothManager(self.config, self.bus)
        # On x86 without real BT, will be simulated
        events = []
        self.bus.subscribe("bt.connected", lambda t, v, ts: events.append(("connected", v)))
        self.bus.subscribe("bt.a2dp_active", lambda t, v, ts: events.append(("a2dp", v)))

        result = bt.connect("AA:BB:CC:DD:EE:FF")

        if not bt.available:
            # Simulated mode — always succeeds
            assert result is True
            assert bt.connected is True
            assert bt.a2dp_active is True
            assert bt.connected_device["address"] == "AA:BB:CC:DD:EE:FF"
            assert any(e[0] == "connected" for e in events)
            assert any(e[0] == "a2dp" and e[1] is True for e in events)
        # If real BT is available, result depends on actual device

    def test_simulated_disconnect(self):
        bt = BluetoothManager(self.config, self.bus)
        bt.connect("AA:BB:CC:DD:EE:FF")

        events = []
        self.bus.subscribe("bt.disconnected", lambda t, v, ts: events.append(("disconnected", v)))
        self.bus.subscribe("bt.a2dp_active", lambda t, v, ts: events.append(("a2dp", v)))

        bt.disconnect()

        assert bt.connected is False
        assert bt.a2dp_active is False
        assert bt.connected_device is None
        assert any(e[0] == "disconnected" for e in events)

    def test_disconnect_when_not_connected(self):
        bt = BluetoothManager(self.config, self.bus)
        # Should not raise
        bt.disconnect()
        assert bt.connected is False

    def test_paired_devices_simulated_when_unavailable(self):
        """Without a real controller, a simulated device list is returned."""
        bt = BluetoothManager(self.config, self.bus)
        if not bt.available:
            devices = bt.get_paired_devices()
            assert isinstance(devices, list)
            assert len(devices) > 0
            for dev in devices:
                assert "address" in dev and "name" in dev

    def test_hfp_call_events(self):
        bt = BluetoothManager(self.config, self.bus)
        bt.connect("AA:BB:CC:DD:EE:FF")

        hfp_events = []
        self.bus.subscribe("bt.hfp_active", lambda t, v, ts: hfp_events.append(v))
        call_events = []
        self.bus.subscribe("audio.phone_call", lambda t, v, ts: call_events.append(v))

        # Simulate incoming call
        self.bus.publish("bt.call_incoming", True)

        assert bt.hfp_active is True
        assert True in hfp_events
        assert True in call_events

        # Simulate call end
        self.bus.publish("bt.call_ended", True)

        assert bt.hfp_active is False
        assert False in hfp_events
        assert False in call_events

    def test_discoverable_simulated(self):
        bt = BluetoothManager(self.config, self.bus)
        if not bt.available:
            assert bt.enable_discoverable(timeout=10) is True

    def test_monitor_start_stop(self):
        bt = BluetoothManager(self.config, self.bus)
        bt.start_monitor()
        bt.stop_monitor()
        # Should not raise

    def test_scanning_property(self):
        bt = BluetoothManager(self.config, self.bus)
        assert bt.scanning is False

    def test_simulated_scan(self):
        bt = BluetoothManager(self.config, self.bus)
        if not bt.available:
            scan_events = []
            self.bus.subscribe("bt.scan_result", lambda t, v, ts: scan_events.append(v))
            result = bt.start_scan(duration=1)
            assert result is True
            assert bt.scanning is False  # simulated completes immediately
            assert len(bt.discovered_devices) > 0
            assert len(scan_events) == 1

    def test_simulated_pair(self):
        bt = BluetoothManager(self.config, self.bus)
        if not bt.available:
            assert bt.pair("AA:BB:CC:DD:EE:01") is True

    def test_simulated_remove(self):
        bt = BluetoothManager(self.config, self.bus)
        if not bt.available:
            assert bt.remove("AA:BB:CC:DD:EE:01") is True

    def test_controller_info_simulated(self):
        bt = BluetoothManager(self.config, self.bus)
        if not bt.available:
            info = bt.get_controller_info()
            assert info["available"] is False
            assert "address" in info
            assert "name" in info

    def test_device_info_simulated(self):
        bt = BluetoothManager(self.config, self.bus)
        if not bt.available:
            info = bt.get_device_info("AA:BB:CC:DD:EE:FF")
            assert info["address"] == "AA:BB:CC:DD:EE:FF"
            assert info["connected"] is False

    def test_stop_scan(self):
        bt = BluetoothManager(self.config, self.bus)
        bt.stop_scan()
        assert bt.scanning is False


# ---------------------------------------------------------------------------
# OpenAuto Controller tests
# ---------------------------------------------------------------------------

class TestOpenAutoController:
    def setup_method(self):
        self.bus = EventBus()
        self.config = BCMConfig(platform_override="x86")

    def test_find_openauto_not_installed(self):
        """On test machines, OpenAuto is typically not installed."""
        # _find_openauto may or may not find it
        result = _find_openauto()
        # We just ensure it returns str or None
        assert result is None or isinstance(result, str)

    def test_initial_state(self):
        ctrl = OpenAutoController(self.config, self.bus)
        assert ctrl.running is False

    def test_start_without_binary(self):
        ctrl = OpenAutoController(self.config, self.bus)
        if not ctrl.available:
            events = []
            self.bus.subscribe("multimedia.openauto_status",
                               lambda t, v, ts: events.append(v))
            result = ctrl.start()
            assert result is False
            assert "unavailable" in events

    def test_stop_when_not_running(self):
        ctrl = OpenAutoController(self.config, self.bus)
        # Should not raise
        ctrl.stop()
        assert ctrl.running is False

    def test_shutdown_event_stops_openauto(self):
        ctrl = OpenAutoController(self.config, self.bus)
        self.bus.publish("power.shutting_down", True)
        assert ctrl.running is False

    def test_auto_restart_enabled_property(self):
        ctrl = OpenAutoController(self.config, self.bus)
        assert ctrl.auto_restart_enabled is True

        events = []
        self.bus.subscribe("multimedia.aa_auto_restart", lambda t, v, ts: events.append(v))

        ctrl.auto_restart_enabled = False
        assert ctrl.auto_restart_enabled is False
        assert False in events

        ctrl.auto_restart_enabled = True
        assert ctrl.auto_restart_enabled is True
        assert True in events

    def test_manual_restart_without_binary(self, openauto_sandbox):
        # restart() runs pgrep/fuser/kill and a Bluetooth power cycle; the
        # conftest sandbox records those instead of running them.
        ctrl = OpenAutoController(self.config, self.bus)
        if not ctrl.available:
            result = ctrl.restart()
            assert result is False
            assert ctrl.running is False
            assert openauto_sandbox.kills == []
            assert ["fuser", "5000/tcp"] in openauto_sandbox.calls

    def test_bt_connection_events_rearm(self):
        ctrl = OpenAutoController(self.config, self.bus)
        # Should not raise when phone connects/disconnects
        self.bus.publish("bt.connected", {"address": "11:22:33:44:55:66", "name": "Pixel"})
        self.bus.publish("bt.disconnected", {"address": "11:22:33:44:55:66"})

    def test_auto_restart_event_bus_toggle(self):
        ctrl = OpenAutoController(self.config, self.bus)
        assert ctrl.auto_restart_enabled is True
        self.bus.publish("multimedia.set_auto_restart", False)
        assert ctrl.auto_restart_enabled is False
        self.bus.publish("multimedia.set_auto_restart", True)
        assert ctrl.auto_restart_enabled is True


# ---------------------------------------------------------------------------
# Integration: start_multimedia entry point
# ---------------------------------------------------------------------------

class TestMultimediaEntryPoint:
    def test_start_multimedia_runs(self):
        from src.multimedia.openauto import start_multimedia
        bus = EventBus()
        config = BCMConfig(platform_override="x86")

        internals = []
        bus.subscribe("multimedia._internals", lambda t, v, ts: internals.append(v))

        start_multimedia(config, bus)

        assert len(internals) == 1
        assert "openauto" in internals[0]
        assert "bluetooth" in internals[0]

        # Cleanup
        internals[0]["openauto"].stop()
        internals[0]["bluetooth"].stop_monitor()


# ---------------------------------------------------------------------------
# AA Display + BT Web UI tests
# ---------------------------------------------------------------------------

class TestAADisplay:
    def setup_method(self):
        self.bus = EventBus()
        self.config = BCMConfig(platform_override="x86")

    def test_initial_state(self):
        disp = AADisplaySimulator(self.config, self.bus)
        assert disp._aa_connected is False
        assert disp._bt_connected is False
        assert disp._phone_active is False
        assert disp.bt is None

    def test_with_bt_manager(self):
        bt = BluetoothManager(self.config, self.bus)
        disp = AADisplaySimulator(self.config, self.bus, bt_manager=bt)
        assert disp.bt is bt

    def test_event_updates_aa_status(self):
        disp = AADisplaySimulator(self.config, self.bus)
        self.bus.publish("multimedia.openauto_status", "running")
        assert disp._aa_connected is True
        assert disp._aa_status == "running"

    def test_event_updates_bt_connected(self):
        disp = AADisplaySimulator(self.config, self.bus)
        self.bus.publish("bt.connected", {"name": "TestPhone", "address": "AA:BB:CC:DD:EE:FF"})
        assert disp._bt_connected is True
        assert disp._bt_device == "TestPhone"

    def test_event_updates_bt_disconnected(self):
        disp = AADisplaySimulator(self.config, self.bus)
        self.bus.publish("bt.connected", {"name": "TestPhone"})
        self.bus.publish("bt.disconnected", {"address": "AA:BB:CC:DD:EE:FF"})
        assert disp._bt_connected is False
        assert disp._bt_device == "---"

    def test_event_updates_phone(self):
        disp = AADisplaySimulator(self.config, self.bus)
        self.bus.publish("bt.hfp_active", True)
        assert disp._phone_active is True

    def test_get_local_ips(self):
        ips = AADisplaySimulator._get_local_ips()
        assert isinstance(ips, list)

    def test_display_dimensions(self):
        disp = AADisplaySimulator(self.config, self.bus)
        # Main display is the 10.1" 1280x800 panel (display.multimedia in config).
        assert disp.width == 1280
        assert disp.height == 800


# ---------------------------------------------------------------------------
# Wi-Fi Direct credentials → openauto.ini
#
# A P2P group invents its SSID and passphrase when it is created, so the values
# that matter are only known at runtime. Nothing subscribed to
# wifi.ap_credentials before v8.5.3, so openauto.ini kept whatever the YAML
# held — and the YAML held a stale DIRECT-xx pair from an earlier session. The
# phone was handed credentials for a network that no longer existed.
# ---------------------------------------------------------------------------

class TestAPCredentialRefresh:
    def test_controller_subscribes_to_ap_credentials(self):
        from src.core.config import BCMConfig
        from src.core.event_bus import EventBus
        from src.multimedia.openauto import OpenAutoController

        bus = EventBus()
        config = BCMConfig(platform_override="x86")
        OpenAutoController(config, bus)

        assert "wifi.ap_credentials" in bus._subscribers, (
            "OpenAutoController must react to live AP credentials, otherwise "
            "openauto.ini keeps stale Wi-Fi Direct details"
        )

    def test_refresh_is_a_noop_without_binary(self):
        """No autoapp means no openauto.ini to rewrite — must not raise."""
        from src.core.config import BCMConfig
        from src.core.event_bus import EventBus
        from src.multimedia.openauto import OpenAutoController

        bus = EventBus()
        ctrl = OpenAutoController(BCMConfig(platform_override="x86"), bus)
        if ctrl.available:
            pytest.skip("autoapp actually installed on this machine")
        ctrl._on_ap_credentials(
            "wifi.ap_credentials",
            {"ssid": "DIRECT-zz", "password": "secret12", "bssid": "aa:bb"},
            0.0,
        )

    def test_ini_is_private_and_stale_temporaries_are_swept(self, tmp_path):
        """openauto.ini holds the PSK: 0600, and a temporary orphaned by a
        power cut mid-write is removed on the next write (a fresh one, which
        may belong to a write in progress, is left alone)."""
        import os
        import stat
        from src.multimedia.openauto import _create_openauto_config

        stale = tmp_path / ".openauto.ini.old1.tmp"
        stale.write_text("[WiFi]\nPassword=testpsk1\n")
        os.utime(stale, (1, 1))
        fresh = tmp_path / ".openauto.ini.new1.tmp"
        fresh.write_text("partial")

        _create_openauto_config(str(tmp_path), app_config=None)

        assert stat.S_IMODE(os.stat(tmp_path / "openauto.ini").st_mode) == 0o600
        assert not stale.exists()
        assert fresh.exists()


_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

# The OpenWeatherMap key format: a run of exactly 32 hex digits.
_HEX32_RE = re.compile(r"(?<![0-9a-fA-F])[0-9a-fA-F]{32}(?![0-9a-fA-F])")


def _repo_files(root, pathspecs=()):
    """Files git would commit under ``root``: tracked plus untracked files
    that are not git-ignored.

    Going through git matters: once BCM has run on a machine, config/ also
    holds the git-ignored runtime overlay (local.yaml, .bak, .broken-*) with
    the paired phone's address and maybe a Wi-Fi password — those are
    *meant* to be there and must not fail the shipped-file guards. Untracked
    but not-ignored files are included so a leak fails before it is
    committed. Returns ``None`` when git is unavailable or ``root`` is not a
    work tree.
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others",
             "--exclude-standard", "--", *pathspecs],
            capture_output=True, timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    names = {n for n in proc.stdout.decode("utf-8", "surrogateescape").split("\0") if n}
    # --cached also lists files deleted in the work tree
    return sorted(p for p in (root / n for n in names) if p.is_file())


def _shipped_configs(root=_REPO_ROOT, use_git=True):
    """The config/*.yaml files that ship in git (not the runtime overlay)."""
    config_dir = root / "config"
    files = _repo_files(root, ["config"]) if use_git else None
    if files is None:
        # No git: fall back to the directory, minus the overlay family
        # (local.yaml, local.yaml.bak, .local.yaml.XXXX.tmp …).
        return sorted(p for p in config_dir.glob("*.yaml")
                      if not p.name.startswith(("local", ".")))
    return [p for p in files if p.parent == config_dir and p.suffix == ".yaml"]


def _secret_scan_files(root=_REPO_ROOT):
    """Text files to scan for leaked tokens: everything git would commit,
    except third-party vendor code."""
    files = _repo_files(root)
    if files is None:
        files = [p for d in ("src", "tests", "tools", "config", "docs")
                 for p in (root / d).rglob("*")
                 if p.is_file() and "__pycache__" not in p.parts
                 and not p.name.startswith(("local", ".local"))]
        files.append(root / "main.py")
    return [p for p in files if "vendor" not in p.relative_to(root).parts]


def _walk(node, prefix=""):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _walk(value, f"{prefix}{key}.")
    yield prefix.rstrip("."), node


# Wi-Fi passwords are in SECRET_ENV_MAP so they CAN come from bcm.env, but
# the shipped values are factory defaults (wifi_ap.py has its own
# hard-coded fallback too) and blanking them would leave hostapd/openauto.ini
# without a passphrase. Only the API keys must never ship non-empty.
_SHIPPED_DEFAULT_SECRETS = {"wifi.password", "wifi.alfa_net.password"}


class TestShippedConfigCredentials:
    """The shipped YAMLs (every config/*.yaml, the deprecated temp one too)
    must not carry runtime credentials, API keys or a paired phone."""

    @pytest.mark.parametrize("cfg_path", _shipped_configs(), ids=lambda p: p.name)
    def test_runtime_credentials_are_blank(self, cfg_path):
        import yaml

        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
        for dotpath, value in _walk(cfg):
            if dotpath.rsplit(".", 1)[-1].endswith("_runtime"):
                assert not value, (
                    f"{cfg_path.name}: {dotpath} must ship empty — a stale P2P "
                    f"credential sends the phone to a network that no longer exists"
                )

    @pytest.mark.parametrize("cfg_path", _shipped_configs(), ids=lambda p: p.name)
    def test_no_secrets_in_tracked_yaml(self, cfg_path):
        import yaml
        from src.core.config import SECRET_ENV_MAP, get_path

        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
        for dotpath, var in SECRET_ENV_MAP.items():
            if dotpath in _SHIPPED_DEFAULT_SECRETS:
                continue
            assert not get_path(cfg, dotpath), (
                f"{cfg_path.name}: {dotpath} must ship empty — put it in "
                f"/etc/bcm/bcm.env as {var}"
            )

    def test_no_32_hex_tokens_anywhere_in_repo(self):
        """The OpenWeatherMap key format; a match is almost certainly a leak.

        Scans every file git would commit (tests, tools and docs too — a
        test fixture with a pasted real key leaks it just as well as a
        YAML). The failure message names path:line only, never the token:
        CI logs are public-ish.
        """
        offenders = []
        for path in _secret_scan_files():
            try:
                data = path.read_bytes()
            except OSError:
                continue
            if b"\0" in data[:8192]:
                continue  # binary (images, PDFs, firmware)
            text = data.decode("utf-8", "replace")
            for match in _HEX32_RE.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                offenders.append(f"{path.relative_to(_REPO_ROOT)}:{line}")
        assert not offenders, (
            "32-hex token(s) that look like an API key — move real keys to "
            "/etc/bcm/bcm.env, build fake ones in tests as e.g. 'a1b2c3d4' * 4: "
            + ", ".join(offenders)
        )

    @pytest.mark.parametrize("cfg_path", _shipped_configs(), ids=lambda p: p.name)
    def test_no_paired_phone_address(self, cfg_path):
        import yaml
        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
        assert not (cfg.get("multimedia") or {}).get("last_bt_device"), (
            f"{cfg_path.name}: multimedia.last_bt_device is per-car state and "
            f"belongs in config/local.yaml"
        )


class TestShippedConfigSelection:
    """The guards above must look at shipped files only: the runtime overlay
    family next to them is git-ignored and legitimately holds per-car data."""

    _OVERLAY_FAMILY = ("local.yaml", "local.yaml.bak", "local.yaml.broken-20260101-000000",
                       ".local.yaml.abc123.tmp", "local-temp.yaml")

    def _tree(self, root):
        cfg = root / "config"
        cfg.mkdir()
        (cfg / "bcm_config.yaml").write_text("multimedia:\n  last_bt_device: ''\n")
        for name in self._OVERLAY_FAMILY:
            (cfg / name).write_text("multimedia:\n  last_bt_device: AA:BB:CC:DD:EE:01\n")
        return cfg

    def test_fallback_without_git_skips_local_overlay(self, tmp_path):
        cfg = self._tree(tmp_path)
        assert _shipped_configs(tmp_path, use_git=False) == [cfg / "bcm_config.yaml"]

    def test_not_a_work_tree_uses_fallback(self, tmp_path):
        cfg = self._tree(tmp_path)
        if _repo_files(tmp_path) is not None:
            pytest.skip("tmp_path is inside a git work tree")
        assert _shipped_configs(tmp_path) == [cfg / "bcm_config.yaml"]

    @pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
    def test_git_path_honours_the_repo_gitignore(self, tmp_path):
        """With the repo's real .gitignore, the overlay family (and the
        atomic-write temporaries) are invisible to the guards."""
        cfg = self._tree(tmp_path)
        (tmp_path / ".openauto.ini.x1y2.tmp").write_text("[WiFi]\nPassword=testpsk1\n")
        shutil.copy(_REPO_ROOT / ".gitignore", tmp_path / ".gitignore")
        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, timeout=30)
        assert _shipped_configs(tmp_path) == [cfg / "bcm_config.yaml"]
        listed = {p.name for p in _repo_files(tmp_path)}
        assert listed == {"bcm_config.yaml", ".gitignore"}
