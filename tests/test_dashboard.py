"""Tests for dashboard module (Part 2)."""

import time
import pytest
from src.core.config import BCMConfig
from src.core.event_bus import EventBus
from src.dashboard.themes import THEMES, ThemeBase
from src.dashboard.trip_computer import TripComputer
from src.dashboard.status_bar import StatusBar
from src.dashboard.overlays import ParkingOverlay, IcingAlert
from src.dashboard.settings_screen import SettingsScreen, SETTINGS


class TestThemes:
    def test_all_themes_registered(self):
        assert "classic_alfa" in THEMES
        assert "modern_dark" in THEMES
        assert "oem_digital" in THEMES

    def test_themes_instantiate(self):
        for name, cls in THEMES.items():
            theme = cls()
            assert theme.name == name
            assert theme.width == 800
            assert theme.height == 480
            assert isinstance(theme.bg_color, tuple)

    def test_theme_inherits_base(self):
        for cls in THEMES.values():
            assert issubclass(cls, ThemeBase)

    def test_classic_alfa_has_red_accent(self):
        theme = THEMES["classic_alfa"]()
        # Red channel should be dominant in accent color
        assert theme.accent_color[0] > theme.accent_color[1]
        assert theme.accent_color[0] > theme.accent_color[2]

    def test_modern_dark_uses_bar_gauges(self):
        theme = THEMES["modern_dark"]()
        assert theme.rpm_gauge.style == "bar"
        assert theme.speed_gauge.style == "bar"

    def test_oem_digital_uses_digital_for_small_gauges(self):
        theme = THEMES["oem_digital"]()
        assert theme.temp_gauge.style == "digital"
        assert theme.fuel_gauge.style == "digital"


class TestTripComputer:
    def test_initial_values(self):
        trip = TripComputer()
        assert trip.distance_km == 0.0
        assert trip.fuel_used_l == 0.0
        assert trip.avg_speed == 0.0

    def test_update_accumulates_distance(self):
        trip = TripComputer()
        # Simulate 100 km/h for 1 second
        trip.update(100.0, 5.0, dt=1.0)
        # distance = 100/3600 * 1 ≈ 0.0278 km
        assert 0.027 < trip.distance_km < 0.029

    def test_update_accumulates_fuel(self):
        trip = TripComputer()
        # 5 L/h for 1 second = 5/3600 ≈ 0.00139 L
        trip.update(100.0, 5.0, dt=1.0)
        assert 0.001 < trip.fuel_used_l < 0.002

    def test_avg_speed(self):
        trip = TripComputer()
        trip.update(60.0, 3.0, dt=1.0)
        trip.update(80.0, 4.0, dt=1.0)
        assert trip.avg_speed == pytest.approx(70.0)

    def test_instant_consumption(self):
        trip = TripComputer()
        trip.update(100.0, 7.0, dt=1.0)
        # 7 L/h at 100 km/h = 7.0 L/100km
        assert trip.instant_consumption == pytest.approx(7.0)

    def test_instant_consumption_at_standstill(self):
        trip = TripComputer()
        trip.update(0.0, 1.0, dt=1.0)
        assert trip.instant_consumption == 0.0

    def test_estimated_range(self):
        trip = TripComputer()
        trip.fuel_level_pct = 50.0
        # Drive to get some avg consumption
        for _ in range(100):
            trip.update(80.0, 6.0, dt=1.0)
        assert trip.estimated_range_km > 0

    def test_trip_time_str(self):
        trip = TripComputer()
        time_str = trip.trip_time_str
        # Should be HH:MM:SS format
        parts = time_str.split(":")
        assert len(parts) == 3

    def test_reset(self):
        trip = TripComputer()
        trip.update(100.0, 5.0, dt=1.0)
        trip.reset()
        assert trip.distance_km == 0.0
        assert trip.fuel_used_l == 0.0

    def test_skip_unreasonable_dt(self):
        trip = TripComputer()
        trip.update(100.0, 5.0, dt=10.0)  # >5s, should be skipped
        assert trip.distance_km == 0.0


class TestStatusBar:
    def test_initial_state(self):
        sb = StatusBar()
        assert sb.bluetooth_connected is False
        assert sb.temperature is None
        assert sb.icing_warning is False

    def test_set_values(self):
        sb = StatusBar()
        sb.bluetooth_connected = True
        sb.temperature = 22.5
        sb.audio_source = "BT Audio"
        assert sb.bluetooth_connected is True
        assert sb.temperature == 22.5


class TestParkingOverlay:
    def test_initial_inactive(self):
        po = ParkingOverlay()
        assert po.active is False
        assert len(po.distances) == 4

    def test_set_distances(self):
        po = ParkingOverlay()
        po.distances = [0.5, 0.8, 1.2, 2.0]
        assert po.distances[0] == 0.5


class TestIcingAlert:
    def test_initial_inactive(self):
        alert = IcingAlert()
        assert alert.active is False

    def test_trigger(self):
        alert = IcingAlert()
        alert.trigger(duration=2.0)
        assert alert.active is True

    def test_expires(self):
        alert = IcingAlert()
        alert.trigger(duration=0.01)
        time.sleep(0.05)
        assert alert.active is False


class TestSettingsScreen:
    def test_initial_inactive(self):
        cfg = BCMConfig(platform_override="x86")
        settings = SettingsScreen(cfg)
        assert settings.active is False

    def test_toggle(self):
        cfg = BCMConfig(platform_override="x86")
        settings = SettingsScreen(cfg)
        settings.toggle()
        assert settings.active is True
        settings.toggle()
        assert settings.active is False

    def test_navigate(self):
        cfg = BCMConfig(platform_override="x86")
        settings = SettingsScreen(cfg)
        settings.toggle()
        settings.navigate(1)
        assert settings.selected_index == 1
        settings.navigate(-1)
        assert settings.selected_index == 0

    def test_cycle_value(self):
        cfg = BCMConfig(platform_override="x86")
        settings = SettingsScreen(cfg)
        settings.toggle()
        # First setting is theme
        settings.cycle_value(1)
        new_theme = cfg.get("display.dashboard.theme")
        assert new_theme in ["classic_alfa", "modern_dark", "oem_digital"]

    def test_all_settings_have_valid_config_keys(self):
        cfg = BCMConfig(platform_override="x86")
        for key, label, options in SETTINGS:
            val = cfg.get(key)
            assert val is not None, f"Config key {key} returned None"
