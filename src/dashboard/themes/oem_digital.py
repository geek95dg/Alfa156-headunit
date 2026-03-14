"""OEM Digital theme — Alfa Romeo Giulia/Stelvio inspired, silver with red needle."""

from dataclasses import dataclass, field
from .theme_base import ThemeBase, GaugeStyle


@dataclass
class OEMDigitalTheme(ThemeBase):
    name: str = "oem_digital"
    display_name: str = "OEM Digital"

    # Dark with deep blue undertone
    bg_color: tuple = (8, 12, 20)
    text_color: tuple = (220, 225, 240)
    text_secondary: tuple = (120, 130, 155)

    # Silver/white accent with red highlights
    accent_color: tuple = (180, 190, 215)
    warning_color: tuple = (255, 190, 0)
    danger_color: tuple = (220, 40, 40)
    ok_color: tuple = (0, 200, 100)

    # Status bar
    status_bar_bg: tuple = (12, 16, 28)
    status_bar_text_color: tuple = (160, 170, 195)
    screen_title_color: tuple = (180, 190, 215)

    # Thin arc gauges with digital readouts
    gauge_bg: tuple = (18, 22, 35)
    gauge_fg: tuple = (180, 190, 215)
    gauge_text: tuple = (220, 225, 240)
    gauge_tick: tuple = (90, 100, 125)
    gauge_needle: tuple = (220, 40, 40)
    gauge_redzone: tuple = (200, 30, 30)

    # Gauges
    rpm_gauge: GaugeStyle = field(default_factory=lambda: GaugeStyle(
        style="arc", arc_width=8, needle_width=2, tick_length=10,
        value_size=34, start_angle=150, sweep_angle=240,
    ))
    speed_gauge: GaugeStyle = field(default_factory=lambda: GaugeStyle(
        style="arc", arc_width=8, needle_width=2, tick_length=10,
        value_size=32, start_angle=150, sweep_angle=240,
    ))
    temp_gauge: GaugeStyle = field(default_factory=lambda: GaugeStyle(
        style="digital", value_size=24,
    ))
    fuel_gauge: GaugeStyle = field(default_factory=lambda: GaugeStyle(
        style="digital", value_size=24,
    ))

    # Layout
    rpm_rect: tuple = (30, 60, 220, 220)
    speed_rect: tuple = (290, 60, 220, 220)
    temp_rect: tuple = (560, 90, 100, 80)
    fuel_rect: tuple = (680, 90, 100, 80)
    trip_rect: tuple = (30, 340, 740, 100)

    # Large values
    value_large_color: tuple = (220, 225, 240)
    value_medium_color: tuple = (180, 190, 215)
    value_label_color: tuple = (120, 130, 155)

    # Bottom bar
    bottom_bar_bg: tuple = (12, 16, 28)
    bottom_bar_text: tuple = (120, 130, 155)
    bottom_bar_value: tuple = (180, 190, 215)

    # Side mini-gauges
    side_gauge_bg: tuple = (15, 20, 32)
    side_gauge_hot: tuple = (220, 60, 40)
    side_gauge_warm: tuple = (180, 190, 215)
    side_gauge_cold: tuple = (80, 140, 200)
    side_gauge_fuel_ok: tuple = (100, 200, 100)
    side_gauge_fuel_low: tuple = (220, 60, 40)

    # Gradient arc
    arc_gradient_start: tuple = (40, 50, 80)
    arc_gradient_end: tuple = (180, 190, 215)
    arc_glow_color: tuple = (180, 190, 215)
    arc_glow_alpha: int = 18

    # Tachometer
    tacho_number_color: tuple = (160, 170, 195)

    # Clock
    clock_face_color: tuple = (15, 20, 32)
    clock_hand_color: tuple = (220, 225, 240)
    clock_hour_hand_color: tuple = (180, 190, 215)
    clock_tick_color: tuple = (120, 130, 155)
    clock_center_color: tuple = (220, 40, 40)

    # Fuel tank
    fuel_tank_body: tuple = (80, 100, 140)
    fuel_tank_highlight: tuple = (120, 140, 180)
    fuel_tank_outline: tuple = (60, 80, 120)

    # Service
    service_ok: tuple = (80, 200, 100)
    service_warn: tuple = (255, 190, 0)
    service_danger: tuple = (220, 40, 40)
    service_bar_bg: tuple = (18, 22, 35)
    service_bar_fill: tuple = (180, 190, 215)

    # Badge
    badge_circle: tuple = (160, 170, 195)
    badge_cross: tuple = (220, 40, 40)

    # Trip
    trip_bg: tuple = (12, 16, 26)
    trip_text: tuple = (120, 130, 155)
    trip_value_color: tuple = (220, 225, 240)

    # Settings
    settings_bg: tuple = (10, 14, 24)
    settings_highlight: tuple = (35, 45, 75)
    settings_value_color: tuple = (180, 190, 215)

    # Overlays
    overlay_text: tuple = (220, 225, 240)
