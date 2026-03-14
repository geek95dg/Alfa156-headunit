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
from src.dashboard.i18n import t, format_date, STRINGS
from src.dashboard.screens import (
    SCREEN_ORDER, SCREEN_CLASSES, DashboardData, BaseScreen,
)


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

    def test_classic_alfa_has_warm_accent(self):
        theme = THEMES["classic_alfa"]()
        # Amber/orange accent — red channel should be dominant
        assert theme.accent_color[0] > theme.accent_color[2]

    def test_modern_dark_has_cyan_accent(self):
        theme = THEMES["modern_dark"]()
        # Cyan accent — blue channel dominant
        assert theme.accent_color[2] > theme.accent_color[0]

    def test_oem_digital_uses_digital_for_small_gauges(self):
        theme = THEMES["oem_digital"]()
        assert theme.temp_gauge.style == "digital"
        assert theme.fuel_gauge.style == "digital"

    def test_theme_has_screen_properties(self):
        """All themes must have the new screen-based properties."""
        for cls in THEMES.values():
            theme = cls()
            assert hasattr(theme, "screen_title_color")
            assert hasattr(theme, "value_large_color")
            assert hasattr(theme, "bottom_bar_bg")
            assert hasattr(theme, "side_gauge_width")
            assert hasattr(theme, "arc_gradient_start")
            assert hasattr(theme, "clock_face_color")
            assert hasattr(theme, "fuel_tank_body")
            assert hasattr(theme, "service_ok")
            assert hasattr(theme, "badge_circle")
            assert hasattr(theme, "content_y")
            assert hasattr(theme, "content_h")


class TestI18n:
    def test_translate_polish(self):
        assert t("screen.a1", "pl") == "A1: GŁÓWNY"
        assert t("screen.a2", "pl") == "A2: SPALANIE"
        assert t("parking", "pl") == "PARKOWANIE"

    def test_translate_english(self):
        assert t("screen.a1", "en") == "A1: MAIN"
        assert t("screen.a2", "en") == "A2: CONSUMPTION"
        assert t("parking", "en") == "PARKING"

    def test_missing_key_returns_key(self):
        assert t("nonexistent.key", "pl") == "nonexistent.key"

    def test_unknown_lang_falls_back_to_polish(self):
        assert t("screen.a1", "xx") == "A1: GŁÓWNY"

    def test_all_pl_keys_exist_in_en(self):
        pl_keys = set(STRINGS["pl"].keys())
        en_keys = set(STRINGS["en"].keys())
        missing = pl_keys - en_keys
        assert not missing, f"EN missing keys: {missing}"

    def test_all_en_keys_exist_in_pl(self):
        pl_keys = set(STRINGS["pl"].keys())
        en_keys = set(STRINGS["en"].keys())
        missing = en_keys - pl_keys
        assert not missing, f"PL missing keys: {missing}"

    def test_format_date_returns_string(self):
        date_pl = format_date("pl")
        assert isinstance(date_pl, str)
        assert len(date_pl) > 5
        date_en = format_date("en")
        assert isinstance(date_en, str)


class TestScreenSystem:
    def test_screen_order(self):
        assert SCREEN_ORDER == ["a1", "a2", "b1", "b2", "c1", "c2"]

    def test_all_screens_registered(self):
        for sid in SCREEN_ORDER:
            assert sid in SCREEN_CLASSES

    def test_screen_classes_instantiate(self):
        for sid, cls in SCREEN_CLASSES.items():
            screen = cls()
            assert isinstance(screen, BaseScreen)
            assert screen.screen_id == sid

    def test_dashboard_data_defaults(self):
        data = DashboardData()
        assert data.rpm == 0.0
        assert data.speed == 0.0
        assert data.lang == "pl"
        assert data.gear == "N"
        assert data.reverse is False
        assert data.oil_level_pct == -1.0
        assert data.tpms_available is False

    def test_screen_long_press(self):
        from src.dashboard.screens.trip_screen import TripScreen
        from src.dashboard.screens.service_screen import ServiceScreen
        from src.dashboard.screens.main_screen import MainScreen

        data = DashboardData()
        assert TripScreen().on_long_press(data) == "trip.reset"
        assert ServiceScreen().on_long_press(data) == "service.confirm"
        assert MainScreen().on_long_press(data) is None


class TestTripComputer:
    def test_initial_values(self):
        trip = TripComputer()
        assert trip.distance_km == 0.0
        assert trip.fuel_used_l == 0.0
        assert trip.avg_speed == 0.0

    def test_update_accumulates_distance(self):
        trip = TripComputer()
        trip.update(100.0, 5.0, dt=1.0)
        assert 0.027 < trip.distance_km < 0.029

    def test_update_accumulates_fuel(self):
        trip = TripComputer()
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
        assert trip.instant_consumption == pytest.approx(7.0)

    def test_instant_consumption_at_standstill(self):
        trip = TripComputer()
        trip.update(0.0, 1.0, dt=1.0)
        assert trip.instant_consumption == 0.0

    def test_estimated_range(self):
        trip = TripComputer()
        trip.fuel_level_pct = 50.0
        for _ in range(100):
            trip.update(80.0, 6.0, dt=1.0)
        assert trip.estimated_range_km > 0

    def test_trip_time_str(self):
        trip = TripComputer()
        time_str = trip.trip_time_str
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
        trip.update(100.0, 5.0, dt=10.0)
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
        settings.cycle_value(1)
        new_theme = cfg.get("display.dashboard.theme")
        assert new_theme in ["classic_alfa", "modern_dark", "oem_digital"]

    def test_all_settings_have_valid_config_keys(self):
        cfg = BCMConfig(platform_override="x86")
        for key, label, options in SETTINGS:
            val = cfg.get(key)
            assert val is not None, f"Config key {key} returned None"
