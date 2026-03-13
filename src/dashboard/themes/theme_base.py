"""Base theme class — defines colors, fonts, gauge styles, and layout."""

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
    """Base theme — subclass and override to create custom themes."""

    name: str = "base"
    display_name: str = "Base Theme"

    # Screen dimensions
    width: int = 800
    height: int = 480

    # Colors (R, G, B)
    bg_color: tuple = (0, 0, 0)
    text_color: tuple = (255, 255, 255)
    text_secondary: tuple = (160, 160, 160)
    accent_color: tuple = (255, 0, 0)
    warning_color: tuple = (255, 200, 0)
    danger_color: tuple = (255, 50, 50)
    ok_color: tuple = (0, 200, 80)

    # Status bar
    status_bar_bg: tuple = (30, 30, 30)
    status_bar_height: int = 32
    status_bar_text_color: tuple = (200, 200, 200)
    status_bar_font_size: int = 14

    # Gauge colors
    gauge_bg: tuple = (40, 40, 40)
    gauge_fg: tuple = (255, 60, 60)
    gauge_text: tuple = (255, 255, 255)
    gauge_tick: tuple = (150, 150, 150)
    gauge_needle: tuple = (255, 255, 255)
    gauge_redzone: tuple = (255, 0, 0)

    # Gauge styles
    rpm_gauge: GaugeStyle = field(default_factory=lambda: GaugeStyle(style="arc"))
    speed_gauge: GaugeStyle = field(default_factory=lambda: GaugeStyle(style="arc"))
    temp_gauge: GaugeStyle = field(default_factory=lambda: GaugeStyle(style="arc", arc_width=6))
    fuel_gauge: GaugeStyle = field(default_factory=lambda: GaugeStyle(style="arc", arc_width=6))

    # Layout regions (x, y, w, h)
    rpm_rect: tuple = (50, 80, 200, 200)
    speed_rect: tuple = (300, 80, 200, 200)
    temp_rect: tuple = (550, 100, 120, 120)
    fuel_rect: tuple = (680, 100, 100, 120)
    trip_rect: tuple = (50, 340, 700, 100)
    status_rect: tuple = (0, 0, 800, 32)

    # Trip computer
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
