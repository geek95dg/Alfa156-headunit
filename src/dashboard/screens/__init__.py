"""BCM dashboard screens — A1 through C2."""

from .base_screen import BaseScreen, DashboardData
from .main_screen import MainScreen
from .consumption_screen import ConsumptionScreen
from .climate_screen import ClimateScreen
from .fuel_screen import FuelScreen
from .trip_screen import TripScreen
from .service_screen import ServiceScreen

# Screen order matching rotary encoder navigation
SCREEN_ORDER = ["a1", "a2", "b1", "b2", "c1", "c2"]

SCREEN_CLASSES = {
    "a1": MainScreen,
    "a2": ConsumptionScreen,
    "b1": ClimateScreen,
    "b2": FuelScreen,
    "c1": TripScreen,
    "c2": ServiceScreen,
}

__all__ = [
    "BaseScreen", "DashboardData", "SCREEN_ORDER", "SCREEN_CLASSES",
    "MainScreen", "ConsumptionScreen", "ClimateScreen",
    "FuelScreen", "TripScreen", "ServiceScreen",
]
