"""Dashboard themes — switchable UI styles.

v7.1: Heritage, Modern, Autodelta card-based themes.
v8.0: Removed legacy gauge-based themes (ClassicAlfa, ModernDark, OEMDigital).
"""

from .theme_base import ThemeBase
from .heritage import HeritageTheme
from .modern import ModernTheme
from .autodelta import AutodeltaTheme

THEMES = {
    "heritage": HeritageTheme,
    "modern": ModernTheme,
    "autodelta": AutodeltaTheme,
}

# Instantiated theme list for settings screen iteration
ALL_THEMES = [cls() for cls in THEMES.values()]

__all__ = [
    "ThemeBase",
    "HeritageTheme", "ModernTheme", "AutodeltaTheme",
    "THEMES", "ALL_THEMES",
]
