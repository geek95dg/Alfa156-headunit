"""Modern Clean theme — light UI with Alfa Blue accents.

Clean, professional design inspired by modern automotive infotainment.
Light slate background with blue (#005596) accent and white cards.
Color palette from stitch modern_* designs.
"""

from dataclasses import dataclass, field
from .theme_base import ThemeBase, GaugeStyle


@dataclass
class ModernTheme(ThemeBase):
    name: str = "modern"
    display_name: str = "Modern Clean"

    # --- Core colors ---
    bg_color: tuple = (248, 250, 252)        # slate-50
    text_color: tuple = (15, 23, 42)         # slate-900
    text_secondary: tuple = (100, 116, 139)  # slate-500
    accent_color: tuple = (0, 85, 150)       # #005596 Alfa Blue
    warning_color: tuple = (245, 158, 11)
    danger_color: tuple = (239, 68, 68)      # red-500
    ok_color: tuple = (22, 163, 74)          # green-600

    # --- Card-based UI (v7.1) ---

    # App bar (black even on light theme)
    appbar_bg: tuple = (0, 0, 0)
    appbar_border: tuple = (39, 39, 42)
    brand_text_color: tuple = (220, 38, 38)  # red-600
    brand_text_style: str = "bold_italic"

    # Nav bar
    navbar_bg: tuple = (0, 0, 0)
    navbar_active_bg: tuple = (127, 29, 29, 51)
    navbar_active_color: tuple = (239, 68, 68)
    navbar_inactive_color: tuple = (113, 113, 122)

    # Content
    content_bg: tuple = (241, 245, 249)      # slate-100
    is_light: bool = True

    # Cards
    card_bg: tuple = (255, 255, 255)
    card_border: tuple = (226, 232, 240)     # slate-200
    card_shadow: tuple = (0, 0, 0, 20)
    card_radius: int = 12

    # Text hierarchy
    text_primary: tuple = (15, 23, 42)       # slate-900
    text_dim: tuple = (148, 163, 184)        # slate-400
    text_mid: tuple = (100, 116, 139)        # slate-500

    # Progress/charts
    progress_bg: tuple = (226, 232, 240)     # slate-200
    progress_fill: tuple = (0, 85, 150)      # Alfa Blue
    chart_bar_active: tuple = (0, 85, 150)
    chart_bar_inactive: tuple = (226, 232, 240)
    chart_line: tuple = (0, 85, 150)

    # Map
    map_bg: tuple = (30, 30, 35)
    map_grid: tuple = (50, 50, 55)
    map_road: tuple = (100, 116, 139, 60)
    map_accent: tuple = (0, 85, 150)

    # Per-screen bg overrides
    init_bg: tuple = (22, 22, 24)            # dark charcoal for init
    a1_bg: tuple = (241, 245, 249)           # slate-100
    a2_bg: tuple = (241, 245, 249)
    a3_bg: tuple = (0, 0, 0)                 # dark for map
    a4_bg: tuple = (255, 255, 255)

    # --- Legacy properties (v7.0 compatibility) ---

    # Status bar
    status_bar_bg: tuple = (14, 16, 22)
    status_bar_text_color: tuple = (150, 160, 180)
    screen_title_color: tuple = (0, 85, 150)

    # Gauge
    gauge_bg: tuple = (226, 232, 240)
    gauge_fg: tuple = (0, 85, 150)
    gauge_text: tuple = (15, 23, 42)
    gauge_tick: tuple = (148, 163, 184)
    gauge_needle: tuple = (0, 85, 150)
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
    value_large_color: tuple = (15, 23, 42)
    value_medium_color: tuple = (0, 85, 150)
    value_label_color: tuple = (148, 163, 184)

    # Bottom bar
    bottom_bar_bg: tuple = (14, 16, 22)
    bottom_bar_text: tuple = (148, 163, 184)
    bottom_bar_value: tuple = (0, 85, 150)

    # Side mini-gauges
    side_gauge_bg: tuple = (226, 232, 240)
    side_gauge_hot: tuple = (239, 68, 68)
    side_gauge_warm: tuple = (0, 85, 150)
    side_gauge_cold: tuple = (59, 130, 246)
    side_gauge_fuel_ok: tuple = (22, 163, 74)
    side_gauge_fuel_low: tuple = (239, 68, 68)

    # Gradient arc
    arc_gradient_start: tuple = (0, 40, 80)
    arc_gradient_end: tuple = (0, 85, 150)
    arc_glow_color: tuple = (0, 85, 150)
    arc_glow_alpha: int = 20

    # Tachometer
    tacho_number_color: tuple = (148, 163, 184)

    # Clock
    clock_face_color: tuple = (241, 245, 249)
    clock_hand_color: tuple = (15, 23, 42)
    clock_hour_hand_color: tuple = (0, 85, 150)
    clock_tick_color: tuple = (148, 163, 184)
    clock_center_color: tuple = (0, 85, 150)

    # Fuel tank
    fuel_tank_body: tuple = (40, 100, 160)
    fuel_tank_highlight: tuple = (60, 140, 200)
    fuel_tank_outline: tuple = (30, 80, 130)

    # Service
    service_ok: tuple = (22, 163, 74)
    service_warn: tuple = (245, 158, 11)
    service_danger: tuple = (239, 68, 68)
    service_bar_bg: tuple = (226, 232, 240)
    service_bar_fill: tuple = (0, 85, 150)

    # Badge
    badge_circle: tuple = (148, 163, 184)
    badge_cross: tuple = (239, 68, 68)

    # Trip
    trip_bg: tuple = (241, 245, 249)
    trip_text: tuple = (148, 163, 184)
    trip_value_color: tuple = (15, 23, 42)

    # Settings
    settings_bg: tuple = (248, 250, 252)
    settings_highlight: tuple = (0, 60, 120)
    settings_text: tuple = (15, 23, 42)
    settings_value_color: tuple = (0, 85, 150)

    # Overlays
    overlay_text: tuple = (15, 23, 42)
