"""Modern Dark Minimal theme — clean flat gauges, Tesla-like."""

from dataclasses import dataclass, field
from .theme_base import ThemeBase, GaugeStyle


@dataclass
class ModernDarkTheme(ThemeBase):
    name: str = "modern_dark"
    display_name: str = "Modern Dark"

    # Pure dark background
    bg_color: tuple = (12, 12, 16)
    text_color: tuple = (230, 235, 240)
    text_secondary: tuple = (120, 130, 140)

    # Cool blue accent
    accent_color: tuple = (0, 150, 255)
    warning_color: tuple = (255, 190, 0)
    danger_color: tuple = (255, 60, 60)
    ok_color: tuple = (0, 210, 100)

    # Minimal status bar
    status_bar_bg: tuple = (18, 18, 22)
    status_bar_text_color: tuple = (160, 170, 180)

    # Flat bar gauges
    gauge_bg: tuple = (30, 32, 38)
    gauge_fg: tuple = (0, 150, 255)
    gauge_text: tuple = (230, 235, 240)
    gauge_tick: tuple = (80, 85, 95)
    gauge_needle: tuple = (0, 180, 255)
    gauge_redzone: tuple = (255, 60, 60)

    # Horizontal bar style gauges
    rpm_gauge: GaugeStyle = field(default_factory=lambda: GaugeStyle(
        style="bar", arc_width=16, value_size=36,
    ))
    speed_gauge: GaugeStyle = field(default_factory=lambda: GaugeStyle(
        style="bar", arc_width=16, value_size=36,
    ))
    temp_gauge: GaugeStyle = field(default_factory=lambda: GaugeStyle(
        style="bar", arc_width=10, value_size=22,
    ))
    fuel_gauge: GaugeStyle = field(default_factory=lambda: GaugeStyle(
        style="bar", arc_width=10, value_size=22,
    ))

    # Layout — bars stacked vertically on left, big digital readouts on right
    rpm_rect: tuple = (30, 70, 350, 130)
    speed_rect: tuple = (30, 210, 350, 130)
    temp_rect: tuple = (420, 70, 350, 90)
    fuel_rect: tuple = (420, 175, 350, 90)
    trip_rect: tuple = (30, 350, 740, 100)

    # Trip
    trip_bg: tuple = (18, 18, 22)
    trip_text: tuple = (120, 130, 140)
    trip_value_color: tuple = (230, 235, 240)

    # Settings
    settings_bg: tuple = (14, 14, 18)
    settings_highlight: tuple = (0, 80, 160)
    settings_value_color: tuple = (0, 150, 255)
