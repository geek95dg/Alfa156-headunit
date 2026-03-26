"""BCM dashboard screens — Init, A1 through A4 + Settings.

v7.1: New screen order: init → a1 (main) → a2 (trip) → a3 (weather) → a4 (service) → settings
Legacy screens (consumption, climate, fuel) kept for backward compatibility.
"""

from .base_screen import BaseScreen, DashboardData
from .initialization_screen import InitializationScreen
from .main_screen import MainScreen
from .consumption_screen import ConsumptionScreen
from .climate_screen import ClimateScreen
from .fuel_screen import FuelScreen
from .trip_screen import TripScreen
from .weather_screen import WeatherScreen
from .service_screen import ServiceScreen
from .settings_screen import SettingsScreen

# v7.1 screen order: Init → A1 Main → A2 Trip → A3 Weather → A4 Service → Settings
SCREEN_ORDER = ["a1", "a2", "a3", "a4", "settings"]

SCREEN_CLASSES = {
    "a1": MainScreen,
    "a2": TripScreen,
    "a3": WeatherScreen,
    "a4": ServiceScreen,
    "settings": SettingsScreen,
}

# Legacy screen mappings (for backward compat if referenced)
LEGACY_SCREEN_CLASSES = {
    "b1": ClimateScreen,
    "b2": FuelScreen,
    "c1": TripScreen,
    "c2": ServiceScreen,
}

__all__ = [
    "BaseScreen", "DashboardData", "SCREEN_ORDER", "SCREEN_CLASSES",
    "InitializationScreen", "MainScreen", "TripScreen",
    "WeatherScreen", "ServiceScreen", "SettingsScreen",
    "ConsumptionScreen", "ClimateScreen", "FuelScreen",
]
