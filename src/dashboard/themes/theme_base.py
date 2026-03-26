"""Base theme class — defines colors, fonts, gauge styles, and card-based layout.

v7.1: Added card-based UI properties for Heritage/Modern/Autodelta themes
alongside legacy gauge-based properties for backward compatibility.
"""

from dataclasses import dataclass, field


@dataclass
class GaugeStyle:
    """Visual style for a gauge."""
    arc_width: int = 8
    needle_width: int = 3
    tick_length: int = 10
    tick_width: int = 2
    label_size: int = 14
    value_size: int = 28
    unit_size: int = 12
    # "arc" = circular arc gauge, "bar" = horizontal/vertical bar, "digital" = numbers only
    style: str = "arc"
    start_angle: float = 135.0   # degrees, 0=right, counter-clockwise
    sweep_angle: float = 270.0   # degrees of arc sweep


@dataclass
class ThemeBase:
    """Base theme — subclass and override to create custom themes.

    Contains both legacy gauge-based properties (v7.0) and new card-based
    properties (v7.1) for Heritage/Modern/Autodelta screen designs.
    """

    name: str = "base"
    display_name: str = "Base Theme"

    # Screen dimensions
    width: int = 800
    height: int = 480

    # --- Core colors (R, G, B) ---
    bg_color: tuple = (0, 0, 0)
    text_color: tuple = (255, 255, 255)
    text_secondary: tuple = (160, 160, 160)
    accent_color: tuple = (255, 0, 0)
    warning_color: tuple = (255, 200, 0)
    danger_color: tuple = (255, 50, 50)
    ok_color: tuple = (0, 200, 80)

    # --- Card-based UI (v7.1) ---

    # App bar (replaces status bar in new screens)
    appbar_bg: tuple = (0, 0, 0)
    appbar_border: tuple = (39, 39, 42)
    appbar_height: int = 48
    brand_text_color: tuple = (220, 38, 38)
    brand_text_style: str = "serif_bold"  # "serif_bold", "bold_italic", etc.

    # Nav bar
    navbar_bg: tuple = (9, 9, 11)
    navbar_height: int = 64
    navbar_active_bg: tuple = (127, 29, 29, 76)
    navbar_active_color: tuple = (239, 68, 68)
    navbar_inactive_color: tuple = (113, 113, 122)

    # Content area (card-based)
    content_bg: tuple = (0, 0, 0)
    content_pad: int = 16

    # Card styling
    card_bg: tuple = (24, 24, 27)
    card_border: tuple = (39, 39, 42)
    card_shadow: tuple = (0, 0, 0, 40)
    card_radius: int = 8

    # Text hierarchy
    text_primary: tuple = (244, 244, 245)
    text_dim: tuple = (113, 113, 122)
    text_mid: tuple = (161, 161, 170)

    # Progress bars / charts
    progress_bg: tuple = (39, 39, 42)
    progress_fill: tuple = (245, 158, 11)
    chart_bar_active: tuple = (236, 91, 19)
    chart_bar_inactive: tuple = (39, 39, 42)
    chart_line: tuple = (0, 85, 150)

    # Map styling
    map_bg: tuple = (15, 15, 18)
    map_grid: tuple = (40, 40, 45)
    map_road: tuple = (245, 158, 11, 60)
    map_accent: tuple = (245, 158, 11)

    # Per-screen background overrides
    init_bg: tuple = (0, 0, 0)
    a1_bg: tuple = (0, 0, 0)
    a2_bg: tuple = (0, 0, 0)
    a3_bg: tuple = (0, 0, 0)
    a4_bg: tuple = (0, 0, 0)

    # Light mode flag
    is_light: bool = False

    # --- Legacy properties (v7.0 — kept for backward compatibility) ---

    # Status bar (legacy)
    status_bar_bg: tuple = (30, 30, 30)
    status_bar_height: int = 32
    status_bar_text_color: tuple = (200, 200, 200)
    status_bar_font_size: int = 14

    # Gauge colors (legacy)
    gauge_bg: tuple = (40, 40, 40)
    gauge_fg: tuple = (255, 60, 60)
    gauge_text: tuple = (255, 255, 255)
    gauge_tick: tuple = (150, 150, 150)
    gauge_needle: tuple = (255, 255, 255)
    gauge_redzone: tuple = (255, 0, 0)

    # Gauge styles (legacy)
    rpm_gauge: GaugeStyle = field(default_factory=lambda: GaugeStyle(style="arc"))
    speed_gauge: GaugeStyle = field(default_factory=lambda: GaugeStyle(style="arc"))
    temp_gauge: GaugeStyle = field(default_factory=lambda: GaugeStyle(style="arc", arc_width=6))
    fuel_gauge: GaugeStyle = field(default_factory=lambda: GaugeStyle(style="arc", arc_width=6))

    # Layout regions (legacy, x, y, w, h)
    rpm_rect: tuple = (50, 80, 200, 200)
    speed_rect: tuple = (300, 80, 200, 200)
    temp_rect: tuple = (550, 100, 120, 120)
    fuel_rect: tuple = (680, 100, 100, 120)
    trip_rect: tuple = (50, 340, 700, 100)
    status_rect: tuple = (0, 0, 800, 32)

    # Trip computer (legacy)
    trip_bg: tuple = (25, 25, 25)
    trip_text: tuple = (200, 200, 200)
    trip_value_color: tuple = (255, 255, 255)
    trip_font_size: int = 13
    trip_value_size: int = 18

    # Overlay colors
    overlay_bg: tuple = (0, 0, 0, 180)  # with alpha
    overlay_text: tuple = (255, 255, 255)

    # Parking distance bar colors
    parking_green: tuple = (0, 200, 80)
    parking_yellow: tuple = (255, 200, 0)
    parking_orange: tuple = (255, 130, 0)
    parking_red: tuple = (255, 30, 30)

    # Settings menu
    settings_bg: tuple = (20, 20, 25)
    settings_highlight: tuple = (60, 60, 80)
    settings_text: tuple = (220, 220, 220)
    settings_value_color: tuple = (100, 180, 255)

    # Font
    font_name: str = "freesans"

    # Screen header (legacy)
    screen_title_color: tuple = (200, 200, 200)
    screen_title_size: int = 14

    # Large value display (legacy)
    value_large_size: int = 72
    value_large_color: tuple = (255, 255, 255)
    value_medium_size: int = 36
    value_medium_color: tuple = (255, 200, 100)
    value_label_color: tuple = (180, 180, 180)

    # Bottom info bar (legacy)
    bottom_bar_height: int = 36
    bottom_bar_bg: tuple = (15, 15, 18)
    bottom_bar_text: tuple = (160, 160, 160)
    bottom_bar_value: tuple = (255, 200, 100)

    # Side mini-gauges (legacy)
    side_gauge_width: int = 44
    side_gauge_bg: tuple = (30, 30, 35)
    side_gauge_hot: tuple = (255, 80, 40)
    side_gauge_warm: tuple = (255, 180, 60)
    side_gauge_cold: tuple = (100, 180, 255)
    side_gauge_fuel_ok: tuple = (100, 200, 100)
    side_gauge_fuel_low: tuple = (255, 80, 40)

    # Gradient arc gauges (legacy)
    arc_gradient_start: tuple = (60, 30, 0)
    arc_gradient_end: tuple = (255, 140, 0)
    arc_glow_color: tuple = (255, 140, 0)
    arc_glow_alpha: int = 25

    # Tachometer specific (legacy)
    tacho_number_color: tuple = (200, 200, 200)
    tacho_number_size: int = 14

    # Analog clock (legacy)
    clock_face_color: tuple = (25, 30, 40)
    clock_hand_color: tuple = (240, 240, 240)
    clock_hour_hand_color: tuple = (200, 200, 200)
    clock_tick_color: tuple = (160, 160, 160)
    clock_center_color: tuple = (255, 200, 100)

    # Fuel tank (legacy)
    fuel_tank_body: tuple = (160, 100, 30)
    fuel_tank_highlight: tuple = (200, 140, 50)
    fuel_tank_outline: tuple = (120, 80, 20)

    # Service
    service_ok: tuple = (80, 200, 80)
    service_warn: tuple = (255, 180, 0)
    service_danger: tuple = (255, 50, 50)
    service_bar_bg: tuple = (40, 40, 45)
    service_bar_fill: tuple = (255, 160, 40)

    # Alfa Romeo badge colors
    badge_circle: tuple = (180, 180, 180)
    badge_cross: tuple = (200, 30, 30)

    # Content area constants (legacy)
    content_y: int = 32
    content_h: int = 412   # 480 - 32 - 36
