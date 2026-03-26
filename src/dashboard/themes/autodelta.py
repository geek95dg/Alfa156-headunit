"""Autodelta Sport theme — dark black with orange racing accents.

Aggressive motorsport design inspired by Autodelta racing heritage.
Pure black background with vivid orange (#ec5b13) accents, bento-grid layout.
Color palette from stitch autodelta_* designs.
"""

from dataclasses import dataclass, field
from .theme_base import ThemeBase, GaugeStyle


@dataclass
class AutodeltaTheme(ThemeBase):
    name: str = "autodelta"
    display_name: str = "Autodelta Sport"

    # --- Core colors ---
    bg_color: tuple = (0, 0, 0)
    text_color: tuple = (255, 255, 255)
    text_secondary: tuple = (113, 113, 122)  # zinc-500
    accent_color: tuple = (236, 91, 19)      # #ec5b13
    warning_color: tuple = (236, 91, 19)
    danger_color: tuple = (239, 68, 68)      # red-500
    ok_color: tuple = (34, 197, 94)          # green-500

    # --- Card-based UI (v7.1) ---

    # App bar
    appbar_bg: tuple = (17, 17, 17)
    appbar_border: tuple = (39, 39, 42)
    brand_text_color: tuple = (185, 28, 28)  # red-800
    brand_text_style: str = "serif_bold"

    # Nav bar
    navbar_bg: tuple = (9, 9, 11)            # zinc-950
    navbar_active_bg: tuple = (127, 29, 29, 76)
    navbar_active_color: tuple = (239, 68, 68)
    navbar_inactive_color: tuple = (113, 113, 122)

    # Content
    content_bg: tuple = (0, 0, 0)
    is_light: bool = False

    # Cards
    card_bg: tuple = (24, 24, 27)            # zinc-900
    card_border: tuple = (39, 39, 42)        # zinc-800
    card_shadow: tuple = (0, 0, 0, 0)
    card_radius: int = 12

    # Text hierarchy
    text_primary: tuple = (255, 255, 255)
    text_dim: tuple = (113, 113, 122)        # zinc-500
    text_mid: tuple = (161, 161, 170)        # zinc-400

    # Progress/charts
    progress_bg: tuple = (39, 39, 42)
    progress_fill: tuple = (236, 91, 19)
    chart_bar_active: tuple = (236, 91, 19)
    chart_bar_inactive: tuple = (39, 39, 42)
    chart_line: tuple = (236, 91, 19)

    # Map
    map_bg: tuple = (15, 15, 18)
    map_grid: tuple = (40, 40, 45)
    map_road: tuple = (236, 91, 19, 60)
    map_accent: tuple = (236, 91, 19)

    # Per-screen bg overrides
    init_bg: tuple = (0, 0, 0)
    a1_bg: tuple = (0, 0, 0)
    a2_bg: tuple = (0, 0, 0)
    a3_bg: tuple = (0, 0, 0)
    a4_bg: tuple = (0, 0, 0)

    # --- Legacy properties (v7.0 compatibility) ---

    # Status bar
    status_bar_bg: tuple = (17, 17, 17)
    status_bar_text_color: tuple = (161, 161, 170)
    screen_title_color: tuple = (236, 91, 19)

    # Gauge
    gauge_bg: tuple = (24, 24, 27)
    gauge_fg: tuple = (236, 91, 19)
    gauge_text: tuple = (255, 255, 255)
    gauge_tick: tuple = (113, 113, 122)
    gauge_needle: tuple = (236, 91, 19)
    gauge_redzone: tuple = (239, 68, 68)

    # Gauge styles
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

    # Large values
    value_large_color: tuple = (255, 255, 255)
    value_medium_color: tuple = (236, 91, 19)
    value_label_color: tuple = (113, 113, 122)

    # Bottom bar
    bottom_bar_bg: tuple = (9, 9, 11)
    bottom_bar_text: tuple = (113, 113, 122)
    bottom_bar_value: tuple = (236, 91, 19)

    # Side mini-gauges
    side_gauge_bg: tuple = (24, 24, 27)
    side_gauge_hot: tuple = (236, 91, 19)
    side_gauge_warm: tuple = (255, 95, 0)
    side_gauge_cold: tuple = (59, 130, 246)
    side_gauge_fuel_ok: tuple = (34, 197, 94)
    side_gauge_fuel_low: tuple = (236, 91, 19)

    # Gradient arc
    arc_gradient_start: tuple = (60, 20, 0)
    arc_gradient_end: tuple = (236, 91, 19)
    arc_glow_color: tuple = (236, 91, 19)
    arc_glow_alpha: int = 25

    # Tachometer
    tacho_number_color: tuple = (161, 161, 170)

    # Clock
    clock_face_color: tuple = (17, 17, 17)
    clock_hand_color: tuple = (255, 255, 255)
    clock_hour_hand_color: tuple = (236, 91, 19)
    clock_tick_color: tuple = (113, 113, 122)
    clock_center_color: tuple = (236, 91, 19)

    # Fuel tank
    fuel_tank_body: tuple = (120, 50, 10)
    fuel_tank_highlight: tuple = (180, 70, 15)
    fuel_tank_outline: tuple = (100, 40, 8)

    # Service
    service_ok: tuple = (34, 197, 94)
    service_warn: tuple = (236, 91, 19)
    service_danger: tuple = (239, 68, 68)
    service_bar_bg: tuple = (24, 24, 27)
    service_bar_fill: tuple = (236, 91, 19)

    # Badge
    badge_circle: tuple = (161, 161, 170)
    badge_cross: tuple = (236, 91, 19)

    # Trip
    trip_bg: tuple = (9, 9, 11)
    trip_text: tuple = (113, 113, 122)
    trip_value_color: tuple = (255, 255, 255)

    # Settings
    settings_bg: tuple = (9, 9, 11)
    settings_highlight: tuple = (60, 25, 5)
    settings_text: tuple = (255, 255, 255)
    settings_value_color: tuple = (236, 91, 19)

    # Overlays
    overlay_text: tuple = (255, 255, 255)
