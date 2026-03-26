"""Dashboard themes — switchable UI styles.

v7.1: Added Heritage, Modern, Autodelta card-based themes.
Legacy themes (ClassicAlfa, ModernDark, OEMDigital) kept for compatibility.
"""

from .theme_base import ThemeBase
from .classic_alfa import ClassicAlfaTheme
from .modern_dark import ModernDarkTheme
from .oem_digital import OEMDigitalTheme
from .heritage import HeritageTheme
from .modern import ModernTheme
from .autodelta import AutodeltaTheme

THEMES = {
    # New card-based themes (v7.1)
    "heritage": HeritageTheme,
    "modern": ModernTheme,
    "autodelta": AutodeltaTheme,
    # Legacy themes (v7.0)
    "classic_alfa": ClassicAlfaTheme,
    "modern_dark": ModernDarkTheme,
    "oem_digital": OEMDigitalTheme,
}

# Instantiated theme list for settings screen iteration
ALL_THEMES = [cls() for cls in THEMES.values()]

__all__ = [
    "ThemeBase",
    "HeritageTheme", "ModernTheme", "AutodeltaTheme",
    "ClassicAlfaTheme", "ModernDarkTheme", "OEMDigitalTheme",
    "THEMES", "ALL_THEMES",
]
