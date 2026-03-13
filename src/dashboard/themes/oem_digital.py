"""OEM Digital theme — modern Alfa Romeo digital dashboard (Giulia/Stelvio inspired)."""

from dataclasses import dataclass, field
from .theme_base import ThemeBase, GaugeStyle


@dataclass
class OEMDigitalTheme(ThemeBase):
    name: str = "oem_digital"
    display_name: str = "OEM Digital"

    # Dark with slight blue undertone
    bg_color: tuple = (10, 14, 20)
    text_color: tuple = (220, 225, 235)
    text_secondary: tuple = (130, 140, 160)

    # White/silver accent with red highlights
    accent_color: tuple = (180, 190, 210)
    warning_color: tuple = (255, 180, 0)
    danger_color: tuple = (220, 40, 40)
    ok_color: tuple = (0, 190, 90)

    # Status bar
    status_bar_bg: tuple = (15, 20, 30)
    status_bar_text_color: tuple = (170, 180, 195)

    # Digital-style gauges with thin arcs
    gauge_bg: tuple = (20, 25, 35)
    gauge_fg: tuple = (180, 190, 210)
    gauge_text: tuple = (220, 225, 235)
    gauge_tick: tuple = (100, 110, 130)
    gauge_needle: tuple = (220, 40, 40)
    gauge_redzone: tuple = (200, 30, 30)

    # Thin arc gauges with digital readouts (Giulia-like)
    rpm_gauge: GaugeStyle = field(default_factory=lambda: GaugeStyle(
        style="arc", arc_width=6, needle_width=2, tick_length=8,
        value_size=34, start_angle=150, sweep_angle=240,
    ))
    speed_gauge: GaugeStyle = field(default_factory=lambda: GaugeStyle(
        style="arc", arc_width=6, needle_width=2, tick_length=8,
        value_size=34, start_angle=150, sweep_angle=240,
    ))
    temp_gauge: GaugeStyle = field(default_factory=lambda: GaugeStyle(
        style="digital", value_size=24,
    ))
    fuel_gauge: GaugeStyle = field(default_factory=lambda: GaugeStyle(
        style="digital", value_size=24,
    ))

    # Layout — two main arc gauges flanking center, digital readouts to the sides
    rpm_rect: tuple = (30, 60, 220, 220)
    speed_rect: tuple = (290, 60, 220, 220)
    temp_rect: tuple = (560, 90, 100, 80)
    fuel_rect: tuple = (680, 90, 100, 80)
    trip_rect: tuple = (30, 340, 740, 100)

    # Trip
    trip_bg: tuple = (15, 20, 28)
    trip_text: tuple = (130, 140, 160)
    trip_value_color: tuple = (220, 225, 235)

    # Settings
    settings_bg: tuple = (12, 16, 24)
    settings_highlight: tuple = (40, 50, 80)
    settings_value_color: tuple = (180, 190, 210)
