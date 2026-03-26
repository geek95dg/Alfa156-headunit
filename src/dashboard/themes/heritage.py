"""Heritage Warmth theme — warm amber/walnut, classic Alfa heritage feel.

Inspired by classic instrument panels with warm wood grain and amber
backlighting. Dark burl walnut base with amber/gold accents.
Color palette from stitch_heritage_warmth_wood_glow_prd designs.
"""

from dataclasses import dataclass, field
from .theme_base import ThemeBase, GaugeStyle


@dataclass
class HeritageTheme(ThemeBase):
    name: str = "heritage"
    display_name: str = "Heritage Warmth"

    # --- Core colors ---
    bg_color: tuple = (26, 15, 10)           # #1a0f0a — burl walnut dark
    text_color: tuple = (244, 244, 245)      # zinc-100
    text_secondary: tuple = (113, 113, 122)  # zinc-500
    accent_color: tuple = (245, 158, 11)     # amber-500
    warning_color: tuple = (245, 158, 11)    # amber-500
    danger_color: tuple = (220, 38, 38)      # red-600
    ok_color: tuple = (34, 197, 94)          # green-500

    # --- Card-based UI (v7.1) ---

    # App bar
    appbar_bg: tuple = (0, 0, 0)
    appbar_border: tuple = (39, 39, 42)
    brand_text_color: tuple = (220, 38, 38)  # red-600
    brand_text_style: str = "serif_bold"

    # Nav bar
    navbar_bg: tuple = (9, 9, 11)            # zinc-950
    navbar_active_bg: tuple = (127, 29, 29, 76)
    navbar_active_color: tuple = (239, 68, 68)
    navbar_inactive_color: tuple = (113, 113, 122)

    # Content
    content_bg: tuple = (26, 15, 10)
    is_light: bool = False

    # Cards
    card_bg: tuple = (9, 9, 11)              # zinc-950
    card_border: tuple = (39, 39, 42)        # zinc-800
    card_shadow: tuple = (0, 0, 0, 0)        # no shadow on dark
    card_radius: int = 8

    # Text hierarchy
    text_primary: tuple = (244, 244, 245)    # zinc-100
    text_dim: tuple = (113, 113, 122)        # zinc-500
    text_mid: tuple = (161, 161, 170)        # zinc-400

    # Progress/charts
    progress_bg: tuple = (39, 39, 42)
    progress_fill: tuple = (245, 158, 11)    # amber-500
    chart_bar_active: tuple = (236, 91, 19)  # primary orange
    chart_bar_inactive: tuple = (39, 39, 42)
    chart_line: tuple = (245, 158, 11)

    # Map
    map_bg: tuple = (15, 15, 18)
    map_grid: tuple = (40, 40, 45)
    map_road: tuple = (245, 158, 11, 60)
    map_accent: tuple = (245, 158, 11)

    # Per-screen bg overrides
    init_bg: tuple = (26, 15, 10)
    a1_bg: tuple = (26, 15, 10)              # burl texture
    a2_bg: tuple = (248, 246, 246)           # light mode
    a3_bg: tuple = (26, 15, 10)              # burl texture
    a4_bg: tuple = (248, 246, 246)           # light mode

    # --- Legacy properties (v7.0 compatibility) ---

    # Status bar
    status_bar_bg: tuple = (18, 12, 14)
    status_bar_text_color: tuple = (200, 180, 160)
    screen_title_color: tuple = (220, 120, 20)

    # Gauge
    gauge_bg: tuple = (35, 25, 20)
    gauge_fg: tuple = (245, 158, 11)
    gauge_text: tuple = (244, 244, 245)
    gauge_tick: tuple = (160, 140, 120)
    gauge_needle: tuple = (255, 80, 30)
    gauge_redzone: tuple = (200, 30, 20)

    # Gauge styles
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
    ))
    fuel_gauge: GaugeStyle = field(default_factory=lambda: GaugeStyle(
        style="arc", arc_width=6, tick_length=8, value_size=22,
    ))

    # Large values
    value_large_color: tuple = (255, 220, 180)
    value_medium_color: tuple = (245, 158, 11)
    value_label_color: tuple = (161, 161, 170)

    # Bottom bar
    bottom_bar_bg: tuple = (18, 12, 14)
    bottom_bar_text: tuple = (161, 161, 170)
    bottom_bar_value: tuple = (245, 158, 11)

    # Side mini-gauges
    side_gauge_bg: tuple = (30, 22, 18)
    side_gauge_hot: tuple = (255, 80, 30)
    side_gauge_warm: tuple = (245, 158, 11)
    side_gauge_cold: tuple = (80, 160, 220)
    side_gauge_fuel_ok: tuple = (34, 197, 94)
    side_gauge_fuel_low: tuple = (255, 80, 30)

    # Gradient arc
    arc_gradient_start: tuple = (60, 30, 5)
    arc_gradient_end: tuple = (245, 158, 11)
    arc_glow_color: tuple = (255, 191, 0)
    arc_glow_alpha: int = 25

    # Tachometer
    tacho_number_color: tuple = (200, 170, 140)

    # Clock
    clock_face_color: tuple = (25, 18, 15)
    clock_hand_color: tuple = (244, 244, 245)
    clock_hour_hand_color: tuple = (245, 158, 11)
    clock_tick_color: tuple = (161, 161, 170)
    clock_center_color: tuple = (245, 158, 11)

    # Fuel tank
    fuel_tank_body: tuple = (180, 110, 30)
    fuel_tank_highlight: tuple = (220, 150, 50)
    fuel_tank_outline: tuple = (140, 90, 20)

    # Service
    service_ok: tuple = (34, 197, 94)
    service_warn: tuple = (245, 158, 11)
    service_danger: tuple = (220, 38, 38)
    service_bar_bg: tuple = (35, 25, 20)
    service_bar_fill: tuple = (245, 158, 11)

    # Badge
    badge_circle: tuple = (200, 180, 160)
    badge_cross: tuple = (220, 38, 38)

    # Trip
    trip_bg: tuple = (22, 16, 18)
    trip_text: tuple = (161, 161, 170)
    trip_value_color: tuple = (244, 244, 245)

    # Settings
    settings_bg: tuple = (18, 12, 14)
    settings_highlight: tuple = (80, 40, 25)
    settings_text: tuple = (220, 220, 220)
    settings_value_color: tuple = (245, 158, 11)

    # Overlays
    overlay_text: tuple = (244, 244, 245)
