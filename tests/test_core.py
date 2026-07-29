"""Tests for core infrastructure (Part 1)."""

import pytest
from src.core.config import BCMConfig
from src.core.event_bus import EventBus
from src.core.logger import setup_logging, get_logger
from src.core.hal import HAL, MockGPIOPin, MockUART, MockOneWire


class TestBCMConfig:
    def test_load_default_config(self):
        cfg = BCMConfig(platform_override="x86")
        assert cfg.platform == "x86"
        assert cfg.get("system.name") == "BCM v8.5"

    def test_dot_notation_access(self):
        cfg = BCMConfig(platform_override="x86")
        # Main panel is the 10.1" 1280x800 (see display.dashboard in config).
        assert cfg.get("display.dashboard.width") == 1280
        assert cfg.get("display.dashboard.height") == 800

    def test_default_value(self):
        cfg = BCMConfig(platform_override="x86")
        assert cfg.get("nonexistent.key", "fallback") == "fallback"

    def test_module_enabled(self):
        cfg = BCMConfig(platform_override="x86")
        assert cfg.is_module_enabled("dashboard") is True
        assert cfg.is_module_enabled("nonexistent") is False

    def test_set_value(self):
        cfg = BCMConfig(platform_override="x86")
        cfg.set("display.dashboard.fps", 30)
        assert cfg.get("display.dashboard.fps") == 30

    def test_missing_config_file(self):
        with pytest.raises(FileNotFoundError):
            BCMConfig(config_path="/nonexistent/config.yaml")


class TestEventBus:
    def test_publish_subscribe(self):
        bus = EventBus()
        received = []

        def handler(topic, value, ts):
            received.append((topic, value))

        bus.subscribe("obd.rpm", handler)
        bus.publish("obd.rpm", 3200)

        assert len(received) == 1
        assert received[0] == ("obd.rpm", 3200)

    def test_wildcard_subscriber(self):
        bus = EventBus()
        received = []

        def handler(topic, value, ts):
            received.append(topic)

        bus.subscribe("*", handler)
        bus.publish("obd.rpm", 3200)
        bus.publish("env.temperature", 22.5)

        assert received == ["obd.rpm", "env.temperature"]

    def test_get_last_value(self):
        bus = EventBus()
        bus.publish("obd.rpm", 3200)
        result = bus.get_last("obd.rpm")
        assert result is not None
        assert result[0] == 3200

    def test_unsubscribe(self):
        bus = EventBus()
        received = []

        def handler(topic, value, ts):
            received.append(value)

        bus.subscribe("test", handler)
        bus.publish("test", 1)
        bus.unsubscribe("test", handler)
        bus.publish("test", 2)

        assert received == [1]

    def test_subscriber_exception_doesnt_crash(self):
        bus = EventBus()

        def bad_handler(topic, value, ts):
            raise ValueError("boom")

        bus.subscribe("test", bad_handler)
        bus.publish("test", 1)  # Should not raise


class TestLogger:
    def test_setup_logging(self):
        log = setup_logging(level="DEBUG")
        assert log.name == "bcm"

    def test_get_module_logger(self):
        log = get_logger("obd")
        assert log.name == "bcm.obd"


class TestHAL:
    def test_x86_returns_mocks(self):
        hal = HAL(platform="x86")
        pin = hal.gpio(79, "out")
        assert isinstance(pin, MockGPIOPin)

        uart = hal.uart("/dev/ttyS3", 10400)
        assert isinstance(uart, MockUART)

    def test_mock_gpio(self):
        pin = MockGPIOPin(79, "out")
        pin.write(1)
        assert pin.read() == 1
        pin.write(0)
        assert pin.read() == 0

    def test_mock_uart(self):
        uart = MockUART("/dev/ttyS3", 10400)
        uart.inject_rx(b"\x81\x01")
        data = uart.read(2)
        assert data == b"\x81\x01"

    def test_mock_onewire(self):
        ow = MockOneWire()
        ow.add_device("28-abc123", 22.5)
        assert ow.list_devices() == ["28-abc123"]
        assert ow.read_temperature("28-abc123") == 22.5
        ow.set_mock_temperature("28-abc123", -3.0)
        assert ow.read_temperature("28-abc123") == -3.0


# ---------------------------------------------------------------------------
# Shipped module configuration
# ---------------------------------------------------------------------------

class TestShippedModuleConfig:
    """Guards on config/bcm_config.yaml — the file systemd actually loads.

    Deliberately does NOT pin the full on/off list: flipping a toggle is a
    normal thing to do. It pins the invariants that quietly break a build.
    """

    @staticmethod
    def _modules(name="bcm_config.yaml"):
        import pathlib
        import yaml
        root = pathlib.Path(__file__).resolve().parent.parent
        return yaml.safe_load((root / "config" / name).read_text())["modules"]

    @pytest.mark.parametrize("cfg_name", ["bcm_config.yaml", "bcm_config_test.yaml"])
    def test_every_toggle_is_a_known_module(self, cfg_name):
        """A typo in a toggle name is silent — the module just never starts."""
        from src.core import modules_catalog
        known = set(modules_catalog.MODULES)
        unknown = set(self._modules(cfg_name)) - known
        assert not unknown, f"{cfg_name}: nieznane przełączniki: {sorted(unknown)}"

    @pytest.mark.parametrize("cfg_name", ["bcm_config.yaml", "bcm_config_test.yaml"])
    def test_toggles_are_booleans(self, cfg_name):
        bad = {k: v for k, v in self._modules(cfg_name).items()
               if not isinstance(v, bool)}
        assert not bad, f"{cfg_name}: nie-boolowskie przełączniki: {bad}"

    def test_android_auto_has_its_whole_chain(self):
        """AA needs all three: the launcher, the BT bootstrap and the P2P link.
        Enabling multimedia alone gets you a screen that never connects."""
        m = self._modules()
        if not m.get("multimedia"):
            pytest.skip("Android Auto wyłączone w tej konfiguracji")
        for dep in ("bluetooth", "wifi_ap"):
            assert m.get(dep), f"multimedia=true wymaga {dep}=true"

    def test_swc_pods_need_the_input_module(self):
        """The steering-wheel pods arrive as USB HID via the Pro Micro; the
        input module is what turns those keycodes into BCM actions."""
        assert self._modules().get("input"), \
            "pody SWC nie zadziałają bez modules.input"

    def test_dashboard_is_on(self):
        """Weather, route planning and AA all render on it."""
        assert self._modules().get("dashboard")
