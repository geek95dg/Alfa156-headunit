"""Modern Dark theme — cool cyan/blue, clean minimal flat design."""

from dataclasses import dataclass, field
from .theme_base import ThemeBase, GaugeStyle


@dataclass
class ModernDarkTheme(ThemeBase):
    name: str = "modern_dark"
    display_name: str = "Modern Dark"

    # Pure dark background
    bg_color: tuple = (10, 12, 18)
    text_color: tuple = (230, 235, 245)
    text_secondary: tuple = (110, 120, 140)

    # Cool cyan accent
    accent_color: tuple = (0, 180, 255)
    warning_color: tuple = (255, 200, 0)
    danger_color: tuple = (255, 60, 60)
    ok_color: tuple = (0, 220, 110)

    # Status bar
    status_bar_bg: tuple = (14, 16, 22)
    status_bar_text_color: tuple = (150, 160, 180)
    screen_title_color: tuple = (0, 180, 255)

    # Flat bar gauges
    gauge_bg: tuple = (25, 28, 38)
    gauge_fg: tuple = (0, 180, 255)
    gauge_text: tuple = (230, 235, 245)
    gauge_tick: tuple = (70, 80, 100)
    gauge_needle: tuple = (0, 200, 255)
    gauge_redzone: tuple = (255, 60, 60)

    # Bar style gauges
    rpm_gauge: GaugeStyle = field(default_factory=lambda: GaugeStyle(
        style="arc", arc_width=10, needle_width=2, tick_length=12,
        value_size=34, start_angle=135, sweep_angle=270,
    ))
    speed_gauge: GaugeStyle = field(default_factory=lambda: GaugeStyle(
        style="arc", arc_width=10, needle_width=2, tick_length=12,
        value_size=32, start_angle=135, sweep_angle=270,
    ))
    temp_gauge: GaugeStyle = field(default_factory=lambda: GaugeStyle(
        style="bar", arc_width=10, value_size=22,
    ))
    fuel_gauge: GaugeStyle = field(default_factory=lambda: GaugeStyle(
        style="bar", arc_width=10, value_size=22,
    ))

    # Layout
    rpm_rect: tuple = (30, 70, 350, 130)
    speed_rect: tuple = (30, 210, 350, 130)
    temp_rect: tuple = (420, 70, 350, 90)
    fuel_rect: tuple = (420, 175, 350, 90)
    trip_rect: tuple = (30, 350, 740, 100)

    # Large values
    value_large_color: tuple = (230, 240, 255)
    value_medium_color: tuple = (0, 200, 255)
    value_label_color: tuple = (110, 120, 140)

    # Bottom bar
    bottom_bar_bg: tuple = (14, 16, 22)
    bottom_bar_text: tuple = (110, 120, 140)
    bottom_bar_value: tuple = (0, 200, 255)

    # Side mini-gauges
    side_gauge_bg: tuple = (20, 24, 32)
    side_gauge_hot: tuple = (255, 80, 60)
    side_gauge_warm: tuple = (0, 200, 255)
    side_gauge_cold: tuple = (60, 140, 220)
    side_gauge_fuel_ok: tuple = (0, 220, 110)
    side_gauge_fuel_low: tuple = (255, 80, 60)

    # Gradient arc
    arc_gradient_start: tuple = (0, 40, 80)
    arc_gradient_end: tuple = (0, 200, 255)
    arc_glow_color: tuple = (0, 180, 255)
    arc_glow_alpha: int = 20

    # Tachometer
    tacho_number_color: tuple = (150, 160, 180)

    # Clock
    clock_face_color: tuple = (18, 22, 30)
    clock_hand_color: tuple = (230, 235, 245)
    clock_hour_hand_color: tuple = (0, 200, 255)
    clock_tick_color: tuple = (110, 120, 140)
    clock_center_color: tuple = (0, 180, 255)

    # Fuel tank
    fuel_tank_body: tuple = (40, 100, 160)
    fuel_tank_highlight: tuple = (60, 140, 200)
    fuel_tank_outline: tuple = (30, 80, 130)

    # Service
    service_ok: tuple = (0, 220, 110)
    service_warn: tuple = (255, 200, 0)
    service_danger: tuple = (255, 60, 60)
    service_bar_bg: tuple = (25, 28, 38)
    service_bar_fill: tuple = (0, 180, 255)

    # Badge
    badge_circle: tuple = (150, 160, 180)
    badge_cross: tuple = (0, 180, 255)

    # Trip
    trip_bg: tuple = (14, 16, 22)
    trip_text: tuple = (110, 120, 140)
    trip_value_color: tuple = (230, 235, 245)

    # Settings
    settings_bg: tuple = (12, 14, 20)
    settings_highlight: tuple = (0, 60, 120)
    settings_value_color: tuple = (0, 180, 255)

    # Overlays
    overlay_text: tuple = (230, 235, 245)
