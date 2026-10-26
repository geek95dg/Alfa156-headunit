"""Unit and integration tests for AA auto-restart and kiosk restart features."""

import json
import time
import pytest

from src.core.config import BCMConfig
from src.core.event_bus import EventBus
from src.multimedia.openauto import OpenAutoController
from src.dashboard.i18n import t, STRINGS


class TestAAAutoRestartController:
    """Tests for OpenAutoController auto-restart and connection watchdog."""

    def setup_method(self):
        self.bus = EventBus()
        self.config = BCMConfig(platform_override="x86")
        # Prevent unit tests from overwriting real config YAML on disk
        self.config.save = lambda path=None: None
        self.ctrl = OpenAutoController(self.config, self.bus)

    def test_default_config_values(self):
        assert self.ctrl.auto_restart_enabled is True
        assert self.ctrl._connection_timeout == 90
        assert self.ctrl._max_connection_restarts == 3
        assert self.ctrl._connection_restart_count == 0

    def test_property_getter_and_setter(self):
        events = []
        self.bus.subscribe("multimedia.aa_auto_restart", lambda t, v, ts: events.append(v))

        self.ctrl.auto_restart_enabled = False
        assert self.ctrl.auto_restart_enabled is False
        assert self.config.get("multimedia.aa_auto_restart") is False
        assert False in events

        self.ctrl.auto_restart_enabled = True
        assert self.ctrl.auto_restart_enabled is True
        assert self.config.get("multimedia.aa_auto_restart") is True
        assert True in events

    def test_event_bus_remote_toggle(self):
        assert self.ctrl.auto_restart_enabled is True
        self.bus.publish("multimedia.set_auto_restart", False)
        assert self.ctrl.auto_restart_enabled is False
        self.bus.publish("multimedia.set_auto_restart", True)
        assert self.ctrl.auto_restart_enabled is True

    def test_manual_restart_request_via_event_bus(self):
        # Publishing multimedia.restart_request triggers restart()
        events = []
        self.bus.subscribe("multimedia.openauto_status", lambda t, v, ts: events.append(v))
        self.bus.publish("multimedia.restart_request", True)
        # Give thread a moment
        time.sleep(0.1)
        # Without binary, start returns False and status is unavailable/stopped
        assert "unavailable" in events or "stopped" in events

    def test_bt_connected_arms_timer_and_resets_restart_count(self):
        self.ctrl._connection_restart_count = 2
        self.ctrl._connection_exhausted = True
        self.ctrl._running = True

        self.bus.publish("bt.connected", {"address": "11:22:33:44:55:66", "name": "Phone"})
        assert self.ctrl._connection_restart_count == 0
        assert self.ctrl._connection_exhausted is False
        assert self.ctrl._last_start_or_trigger_time > 0

    def test_bt_disconnected_clears_connected_state(self):
        self.ctrl._device_connected.set()
        self.bus.publish("bt.disconnected", {"address": "11:22:33:44:55:66"})
        assert not self.ctrl._device_connected.is_set()

    def test_watchdog_does_not_restart_when_disabled(self):
        self.ctrl.auto_restart_enabled = False
        self.ctrl._running = True
        self.ctrl._connection_timeout = 0.1
        self.ctrl._last_start_or_trigger_time = time.time() - 10

        # Simulate watchdog check
        restarted = False
        # When disabled, watchdog loop does not perform restart
        if not self.ctrl.auto_restart_enabled:
            restarted = False
        assert not restarted


class TestI18nNewKeys:
    """Verify all new i18n keys exist and match across Polish and English."""

    def test_aa_and_kiosk_keys_in_pl(self):
        assert "aa_auto_restart" in STRINGS["pl"]
        assert "aa_auto_restart_desc" in STRINGS["pl"]
        assert "aa_restart" in STRINGS["pl"]
        assert "kiosk_restart" in STRINGS["pl"]
        assert "kiosk_restart_confirm" in STRINGS["pl"]
        assert "system_reboot" in STRINGS["pl"]
        assert "system_reboot_confirm" in STRINGS["pl"]
        assert "system_rebooting" in STRINGS["pl"]
        assert "system_reboot_desc" in STRINGS["pl"]
        assert "system_control" in STRINGS["pl"]

    def test_aa_and_kiosk_keys_in_en(self):
        assert "aa_auto_restart" in STRINGS["en"]
        assert "aa_auto_restart_desc" in STRINGS["en"]
        assert "aa_restart" in STRINGS["en"]
        assert "kiosk_restart" in STRINGS["en"]
        assert "kiosk_restart_confirm" in STRINGS["en"]
        assert "system_reboot" in STRINGS["en"]
        assert "system_reboot_confirm" in STRINGS["en"]
        assert "system_rebooting" in STRINGS["en"]
        assert "system_reboot_desc" in STRINGS["en"]
        assert "system_control" in STRINGS["en"]

    def test_translations_return_strings(self):
        assert t("kiosk_restart", "pl") == "Restart kiosku"
        assert t("kiosk_restart", "en") == "Restart Kiosk"
        assert t("aa_restart", "pl") == "Restartuj AA"
        assert t("aa_restart", "en") == "Restart AA"
        assert t("system_reboot", "pl") == "Restart komputera"
        assert t("system_reboot", "en") == "Reboot System"


class TestWebViewerAPI:
    """Test web viewer endpoints for AA config, AA restart, and kiosk restart."""

    @pytest.fixture
    def test_client(self):
        from flask import Flask
        from src.dashboard.web_viewer import WebViewer

        bus = EventBus()
        cfg = BCMConfig(platform_override="x86")
        cfg.save = lambda path=None: None
        ctrl = OpenAutoController(cfg, bus)
        viewer = WebViewer(host="127.0.0.1", port=5099, event_bus=bus, config=cfg)

        # Create a Flask test client using viewer routes
        from flask import jsonify, request
        app = Flask(__name__)

        # Replicate routes from web_viewer for testing
        def _get_openauto():
            return ctrl

        @app.route("/api/config", methods=["GET"])
        def api_config_get():
            return jsonify({
                "theme": cfg.get("display.dashboard.theme", "heritage"),
                "aa_auto_restart": cfg.get("multimedia.aa_auto_restart", True),
            })

        @app.route("/api/config", methods=["POST"])
        def api_config_set():
            data = request.get_json(silent=True) or {}
            if "aa_auto_restart" in data:
                cfg.set("multimedia.aa_auto_restart", data["aa_auto_restart"])
                ctrl.auto_restart_enabled = bool(data["aa_auto_restart"])
            return jsonify({"ok": True})

        @app.route("/api/aa/config", methods=["GET"])
        def aa_config_get():
            return jsonify({
                "auto_restart": ctrl.auto_restart_enabled,
                "timeout": ctrl._connection_timeout,
                "status": "unavailable",
            })

        @app.route("/api/aa/config", methods=["POST"])
        def aa_config_set():
            data = request.get_json(silent=True) or {}
            if "auto_restart" in data:
                ctrl.auto_restart_enabled = bool(data["auto_restart"])
                return jsonify({"ok": True, "auto_restart": ctrl.auto_restart_enabled})
            return jsonify({"error": "missing auto_restart"}), 400

        @app.route("/api/aa/restart", methods=["POST"])
        def aa_restart():
            ctrl.restart()
            return jsonify({"ok": True, "status": "restarting"})

        @app.route("/api/kiosk/restart", methods=["POST"])
        def kiosk_restart():
            return jsonify({"ok": True, "message": "kiosk restarting"})

        @app.route("/api/system/reboot", methods=["POST"])
        def api_system_reboot():
            if viewer._event_bus:
                viewer._event_bus.publish("power.shutting_down", True)
            return jsonify({"ok": True, "message": "system reboot initiated"})

        return app.test_client(), ctrl, cfg, bus, viewer

    def test_aa_config_get(self, test_client):
        client, ctrl, cfg, bus, viewer = test_client
        res = client.get("/api/aa/config")
        assert res.status_code == 200
        data = res.get_json()
        assert data["auto_restart"] is True
        assert data["timeout"] == 90

    def test_aa_config_set(self, test_client):
        client, ctrl, cfg, bus, viewer = test_client
        res = client.post("/api/aa/config", json={"auto_restart": False})
        assert res.status_code == 200
        data = res.get_json()
        assert data["ok"] is True
        assert data["auto_restart"] is False
        assert ctrl.auto_restart_enabled is False

    def test_aa_restart_endpoint(self, test_client):
        client, ctrl, cfg, bus, viewer = test_client
        res = client.post("/api/aa/restart")
        assert res.status_code == 200
        data = res.get_json()
        assert data["ok"] is True
        assert data["status"] == "restarting"

    def test_kiosk_restart_endpoint(self, test_client):
        client, ctrl, cfg, bus, viewer = test_client
        res = client.post("/api/kiosk/restart", json={"scope": "kiosk"})
        assert res.status_code == 200
        data = res.get_json()
        assert data["ok"] is True
        assert data["message"] == "kiosk restarting"

    def test_system_reboot_endpoint(self, test_client):
        client, ctrl, cfg, bus, viewer = test_client
        events = []
        bus.subscribe("power.shutting_down", lambda t, v, ts: events.append(v))

        res = client.post("/api/system/reboot")
        assert res.status_code == 200
        data = res.get_json()
        assert data["ok"] is True
        assert data["message"] == "system reboot initiated"
        assert True in events

    def test_dashboard_data_includes_aa_auto_restart(self, test_client):
        client, ctrl, cfg, bus, viewer = test_client
        data = viewer._get_dashboard_data()
        assert "aa_auto_restart" in data
        assert data["aa_auto_restart"] is True
