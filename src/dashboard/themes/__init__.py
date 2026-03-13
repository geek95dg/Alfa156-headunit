"""Dashboard themes — switchable UI styles."""

from .theme_base import ThemeBase
from .classic_alfa import ClassicAlfaTheme
from .modern_dark import ModernDarkTheme
from .oem_digital import OEMDigitalTheme

THEMES = {
    "classic_alfa": ClassicAlfaTheme,
    "modern_dark": ModernDarkTheme,
    "oem_digital": OEMDigitalTheme,
}

__all__ = ["ThemeBase", "ClassicAlfaTheme", "ModernDarkTheme", "OEMDigitalTheme", "THEMES"]
