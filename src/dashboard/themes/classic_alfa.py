"""Classic Alfa Racing theme — warm amber/orange, analog gauges, Alfa heritage.

Inspired by classic racing instruments with warm amber illumination.
"""

from dataclasses import dataclass, field
from .theme_base import ThemeBase, GaugeStyle


@dataclass
class ClassicAlfaTheme(ThemeBase):
    name: str = "classic_alfa"
    display_name: str = "Classic Alfa Racing"

    # Deep dark background with warm tint
    bg_color: tuple = (12, 8, 10)
    text_color: tuple = (245, 235, 220)
    text_secondary: tuple = (160, 140, 120)

    # Amber/orange accent (warm racing instruments)
    accent_color: tuple = (220, 120, 20)
    warning_color: tuple = (255, 200, 0)
    danger_color: tuple = (255, 40, 40)
    ok_color: tuple = (60, 200, 80)

    # Status bar
    status_bar_bg: tuple = (18, 12, 14)
    status_bar_text_color: tuple = (200, 180, 160)
    screen_title_color: tuple = (220, 120, 20)

    # Gauge — warm amber racing instrument look
    gauge_bg: tuple = (35, 25, 20)
    gauge_fg: tuple = (220, 120, 20)
    gauge_text: tuple = (245, 235, 220)
    gauge_tick: tuple = (160, 140, 120)
    gauge_needle: tuple = (255, 80, 30)
    gauge_redzone: tuple = (200, 30, 20)

    # Circular analog-style gauges
    rpm_gauge: GaugeStyle = field(default_factory=lambda: GaugeStyle(
        style="arc", arc_width=12, needle_width=3, tick_length=14,
        value_size=34, start_angle=135, sweep_angle=270,
    ))
    speed_gauge: GaugeStyle = field(default_factory=lambda: GaugeStyle(
        style="arc", arc_width=10, needle_width=3, tick_length=12,
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

    # Large values
    value_large_color: tuple = (255, 220, 180)
    value_medium_color: tuple = (220, 160, 80)
    value_label_color: tuple = (160, 140, 120)

    # Bottom bar
    bottom_bar_bg: tuple = (18, 12, 14)
    bottom_bar_text: tuple = (160, 140, 120)
    bottom_bar_value: tuple = (220, 160, 80)

    # Side mini-gauges
    side_gauge_bg: tuple = (30, 22, 18)
    side_gauge_hot: tuple = (255, 80, 30)
    side_gauge_warm: tuple = (220, 160, 60)
    side_gauge_cold: tuple = (80, 160, 220)
    side_gauge_fuel_ok: tuple = (120, 200, 80)
    side_gauge_fuel_low: tuple = (255, 80, 30)

    # Gradient arc
    arc_gradient_start: tuple = (60, 30, 5)
    arc_gradient_end: tuple = (255, 140, 20)
    arc_glow_color: tuple = (255, 120, 20)
    arc_glow_alpha: int = 25

    # Tachometer
    tacho_number_color: tuple = (200, 170, 140)

    # Clock
    clock_face_color: tuple = (25, 18, 15)
    clock_hand_color: tuple = (245, 235, 220)
    clock_hour_hand_color: tuple = (220, 160, 80)
    clock_tick_color: tuple = (160, 140, 120)
    clock_center_color: tuple = (220, 120, 20)

    # Fuel tank
    fuel_tank_body: tuple = (180, 110, 30)
    fuel_tank_highlight: tuple = (220, 150, 50)
    fuel_tank_outline: tuple = (140, 90, 20)

    # Service
    service_ok: tuple = (80, 200, 80)
    service_warn: tuple = (255, 180, 0)
    service_danger: tuple = (255, 50, 50)
    service_bar_bg: tuple = (35, 25, 20)
    service_bar_fill: tuple = (220, 140, 30)

    # Badge
    badge_circle: tuple = (200, 180, 160)
    badge_cross: tuple = (200, 40, 30)

    # Trip computer
    trip_bg: tuple = (22, 16, 18)
    trip_text: tuple = (160, 140, 120)
    trip_value_color: tuple = (245, 235, 220)

    # Settings
    settings_bg: tuple = (18, 12, 14)
    settings_highlight: tuple = (80, 40, 25)
    settings_value_color: tuple = (220, 120, 20)

    # Overlays
    overlay_text: tuple = (245, 235, 220)
