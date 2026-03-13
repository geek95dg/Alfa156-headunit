"""Classic Alfa Racing theme — red/dark, circular analog gauges, Alfa heritage."""

from dataclasses import dataclass, field
from .theme_base import ThemeBase, GaugeStyle


@dataclass
class ClassicAlfaTheme(ThemeBase):
    name: str = "classic_alfa"
    display_name: str = "Classic Alfa Racing"

    # Deep dark background with subtle warm tint
    bg_color: tuple = (15, 10, 12)
    text_color: tuple = (240, 230, 220)
    text_secondary: tuple = (160, 140, 130)

    # Alfa red accent
    accent_color: tuple = (200, 30, 30)
    warning_color: tuple = (255, 180, 0)
    danger_color: tuple = (255, 40, 40)
    ok_color: tuple = (40, 180, 60)

    # Status bar — dark with red accent line
    status_bar_bg: tuple = (25, 15, 18)
    status_bar_text_color: tuple = (200, 190, 180)

    # Gauge — classic racing instrument look
    gauge_bg: tuple = (30, 20, 22)
    gauge_fg: tuple = (200, 30, 30)
    gauge_text: tuple = (240, 230, 220)
    gauge_tick: tuple = (180, 160, 150)
    gauge_needle: tuple = (255, 50, 50)
    gauge_redzone: tuple = (200, 0, 0)

    # Circular analog-style gauges
    rpm_gauge: GaugeStyle = field(default_factory=lambda: GaugeStyle(
        style="arc", arc_width=10, needle_width=4, tick_length=12,
        value_size=32, start_angle=135, sweep_angle=270,
    ))
    speed_gauge: GaugeStyle = field(default_factory=lambda: GaugeStyle(
        style="arc", arc_width=10, needle_width=4, tick_length=12,
        value_size=32, start_angle=135, sweep_angle=270,
    ))
    temp_gauge: GaugeStyle = field(default_factory=lambda: GaugeStyle(
        style="arc", arc_width=6, tick_length=8, value_size=22,
        start_angle=135, sweep_angle=270,
    ))
    fuel_gauge: GaugeStyle = field(default_factory=lambda: GaugeStyle(
        style="arc", arc_width=6, tick_length=8, value_size=22,
        start_angle=135, sweep_angle=270,
    ))

    # Trip computer — warm dark
    trip_bg: tuple = (25, 18, 20)
    trip_text: tuple = (180, 160, 150)
    trip_value_color: tuple = (240, 230, 220)

    # Settings
    settings_bg: tuple = (20, 12, 15)
    settings_highlight: tuple = (80, 30, 35)
    settings_value_color: tuple = (200, 30, 30)
