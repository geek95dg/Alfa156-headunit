"""Base screen class — common elements for all BCM screens.

Provides: side gauge drawing (coolant temp left, fuel level right),
bottom info bar, Alfa Romeo badge, card-based drawing helpers,
and content area helpers.

v7.1: Added GPS, weather, BT media, LTE fields to DashboardData.
Added card-based drawing helpers for new screen designs.
"""

import math
import pygame
from dataclasses import dataclass, field
from typing import Optional
from src.dashboard.themes.theme_base import ThemeBase
from src.dashboard.i18n import t


def _font(name: str, size: int) -> pygame.font.Font:
    try:
        return pygame.font.SysFont(name, size)
    except Exception:
        return pygame.font.Font(None, size)


def _lerp_color(c1: tuple, c2: tuple, frac: float) -> tuple:
    """Linearly interpolate between two RGB colors."""
    frac = max(0.0, min(1.0, frac))
    return (
        int(c1[0] + (c2[0] - c1[0]) * frac),
        int(c1[1] + (c2[1] - c1[1]) * frac),
        int(c1[2] + (c2[2] - c1[2]) * frac),
    )


@dataclass
class DashboardData:
    """All current dashboard values passed to screens."""
    rpm: float = 0.0
    speed: float = 0.0
    coolant_temp: float = 0.0
    fuel_level: float = 50.0
    fuel_rate: float = 0.0
    ext_temp: float | None = None
    battery_voltage: float = 12.6
    boost_bar: float = 0.0

    # Trip
    trip_distance: float = 0.0
    trip_time_str: str = "00:00:00"
    trip_fuel_used: float = 0.0
    avg_speed: float = 0.0
    avg_consumption: float = 0.0
    instant_consumption: float = 0.0
    estimated_range: float = 0.0

    # Service
    service_km: int = 4500
    oil_level_pct: float = -1.0  # -1 = no sensor
    tpms_available: bool = False
    tpms_pressures: list = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])

    # State
    gear: str = "N"
    reverse: bool = False
    defrost_active: bool = False
    auto_air_temp: float = 22.0

    # Config-derived
    speed_unit: str = "km/h"
    temp_unit: str = "C"
    lang: str = "pl"

    # --- v7.1: GPS/GNSS ---
    gps_lat: float = 0.0
    gps_lon: float = 0.0
    gps_speed: float = 0.0         # km/h from GPS
    gps_heading: float = 0.0       # degrees (0=N, 90=E)
    gps_fix: bool = False
    gps_satellites: int = 0

    # --- v7.1: Weather ---
    weather_condition: str = ""     # e.g. "Partly Cloudy"
    weather_temp: Optional[float] = None
    weather_feels_like: Optional[float] = None
    weather_humidity: int = 0       # percentage
    weather_wind_speed: float = 0.0  # km/h
    weather_city: str = ""
    weather_forecast: list = field(default_factory=list)
    # forecast entries: [{"day": "Wed", "high": 22, "low": 15, "condition": "..."}]

    # --- v7.1: BT Media (AVRCP) ---
    bt_media_title: str = ""
    bt_media_artist: str = ""
    bt_media_album: str = ""
    bt_media_playing: bool = False
    bt_media_position: int = 0     # seconds
    bt_media_duration: int = 0     # seconds

    # --- v7.1: LTE/Cellular ---
    lte_connected: bool = False
    lte_signal_strength: int = 0   # 0-5 bars


class BaseScreen:
    """Base class for all BCM screens."""

    screen_id: str = ""  # e.g., "a1"

    def __init__(self) -> None:
        pass

    def draw(self, surface: pygame.Surface, theme: ThemeBase,
             data: DashboardData) -> None:
        """Draw the screen content (override in subclass)."""
        pass

    def on_long_press(self, data: DashboardData) -> str | None:
        """Handle long press. Returns event name or None."""
        return None

    # --- Common drawing helpers ---

    def draw_side_gauges(self, surface: pygame.Surface, theme: ThemeBase,
                         data: DashboardData) -> None:
        """Draw left (coolant temp) and right (fuel level) mini-gauges."""
        w, h = surface.get_size()
        gw = theme.side_gauge_width
        cy = theme.content_y + 10
        gh = theme.content_h - 20

        # Left: coolant temperature (40-130°C)
        self._draw_vertical_gauge(
            surface, theme, 4, cy, gw - 8, gh,
            data.coolant_temp, 40, 130,
            "H", f"{data.coolant_temp:.0f}°",
            theme.side_gauge_cold, theme.side_gauge_warm, theme.side_gauge_hot,
        )

        # Right: fuel level (0-100%)
        fuel_color_low = theme.side_gauge_fuel_low
        fuel_color_ok = theme.side_gauge_fuel_ok
        self._draw_vertical_gauge(
            surface, theme, w - gw + 4, cy, gw - 8, gh,
            data.fuel_level, 0, 100,
            "F", f"{data.fuel_level:.0f}%",
            fuel_color_low, fuel_color_ok, fuel_color_ok,
        )

    def _draw_vertical_gauge(
        self, surface: pygame.Surface, theme: ThemeBase,
        x: int, y: int, w: int, h: int,
        value: float, min_val: float, max_val: float,
        top_label: str, bottom_label: str,
        color_low: tuple, color_mid: tuple, color_high: tuple,
    ) -> None:
        """Draw a vertical bar gauge with gradient fill."""
        font_s = _font(theme.font_name, 11)
        font_v = _font(theme.font_name, 10)

        # Top label
        lbl = font_s.render(top_label, True, theme.text_secondary)
        surface.blit(lbl, (x + (w - lbl.get_width()) // 2, y))

        bar_y = y + 16
        bar_h = h - 34
        bar_x = x + 4
        bar_w = w - 8

        # Background
        pygame.draw.rect(surface, theme.side_gauge_bg,
                         (bar_x, bar_y, bar_w, bar_h), border_radius=3)

        # Fill
        frac = max(0, min(1, (value - min_val) / (max_val - min_val))) if max_val > min_val else 0
        fill_h = int(frac * bar_h)
        if fill_h > 1:
            # Color based on fraction
            if frac < 0.5:
                color = _lerp_color(color_low, color_mid, frac * 2)
            else:
                color = _lerp_color(color_mid, color_high, (frac - 0.5) * 2)
            pygame.draw.rect(surface, color,
                             (bar_x, bar_y + bar_h - fill_h, bar_w, fill_h),
                             border_radius=3)

        # Bottom value label
        val = font_v.render(bottom_label, True, theme.text_secondary)
        surface.blit(val, (x + (w - val.get_width()) // 2, y + h - 16))

    def draw_bottom_bar(self, surface: pygame.Surface, theme: ThemeBase,
                        items: list[tuple[str, str]]) -> None:
        """Draw bottom info bar with label:value pairs."""
        w, h = surface.get_size()
        by = h - theme.bottom_bar_height

        pygame.draw.rect(surface, theme.bottom_bar_bg, (0, by, w, theme.bottom_bar_height))
        pygame.draw.line(surface, theme.accent_color, (0, by), (w, by), 1)

        if not items:
            return

        font_l = _font(theme.font_name, 12)
        font_v = _font(theme.font_name, 14)

        seg_w = w // len(items)
        for i, (label, value) in enumerate(items):
            cx = i * seg_w + seg_w // 2
            text = f"{label}: "
            lbl_surf = font_l.render(text, True, theme.bottom_bar_text)
            val_surf = font_v.render(value, True, theme.bottom_bar_value)
            total_w = lbl_surf.get_width() + val_surf.get_width()
            sx = cx - total_w // 2
            ty = by + (theme.bottom_bar_height - lbl_surf.get_height()) // 2
            surface.blit(lbl_surf, (sx, ty + 1))
            surface.blit(val_surf, (sx + lbl_surf.get_width(), ty - 1))

    def draw_alfa_badge(self, surface: pygame.Surface, theme: ThemeBase,
                        cx: int, cy: int, radius: int = 10) -> None:
        """Draw simplified Alfa Romeo badge (circle with cross)."""
        pygame.draw.circle(surface, theme.badge_circle, (cx, cy), radius, 1)
        # Vertical line
        pygame.draw.line(surface, theme.badge_circle,
                         (cx, cy - radius + 2), (cx, cy + radius - 2), 1)
        # Horizontal line
        pygame.draw.line(surface, theme.badge_circle,
                         (cx - radius + 2, cy), (cx + radius - 2, cy), 1)
        # Left half tint (red cross quadrant)
        pygame.draw.circle(surface, theme.badge_cross, (cx - 3, cy - 3), 3)

    def content_rect(self, theme: ThemeBase, surface: pygame.Surface) -> tuple:
        """Return (x, y, w, h) of the main content area (legacy layout)."""
        w, _ = surface.get_size()
        gw = theme.side_gauge_width
        return (gw, theme.content_y, w - 2 * gw, theme.content_h)

    def card_content_rect(self, theme: ThemeBase, surface: pygame.Surface) -> tuple:
        """Return (x, y, w, h) of the card-based content area (v7.1 layout)."""
        w, _ = surface.get_size()
        pad = theme.content_pad
        return (pad, theme.appbar_height, w - 2 * pad, theme.height - theme.appbar_height - theme.navbar_height)

    # --- v7.1: Card-based drawing helpers ---

    @staticmethod
    def draw_card(surface: pygame.Surface, x: int, y: int, w: int, h: int,
                  fill: tuple, border_color: tuple = None, radius: int = 8) -> None:
        """Draw a rounded rectangle card with optional border."""
        rect = pygame.Rect(x, y, w, h)
        pygame.draw.rect(surface, fill, rect, border_radius=radius)
        if border_color:
            pygame.draw.rect(surface, border_color, rect, width=1, border_radius=radius)

    @staticmethod
    def draw_progress_bar(surface: pygame.Surface, x: int, y: int, w: int, h: int,
                          fraction: float, fill_color: tuple, bg_color: tuple,
                          radius: int = 0) -> None:
        """Draw a horizontal progress bar."""
        fraction = max(0.0, min(1.0, fraction))
        rect = pygame.Rect(x, y, w, h)
        pygame.draw.rect(surface, bg_color, rect, border_radius=radius)
        fill_w = max(0, int(w * fraction))
        if fill_w > 0:
            fill_rect = pygame.Rect(x, y, fill_w, h)
            pygame.draw.rect(surface, fill_color, fill_rect, border_radius=radius)

    @staticmethod
    def draw_app_bar(surface: pygame.Surface, theme: ThemeBase,
                     time_str: str = "10:45", date_str: str = "Oct 24",
                     temp_str: str = "21°C") -> None:
        """Draw the themed top app bar."""
        w = surface.get_width()
        bar_h = theme.appbar_height
        pygame.draw.rect(surface, theme.appbar_bg, (0, 0, w, bar_h))
        pygame.draw.line(surface, theme.appbar_border, (0, bar_h - 1), (w, bar_h - 1))

        font_time = _font(theme.font_name, 13)
        font_date = _font(theme.font_name, 10)
        font_brand = _font(theme.font_name, 14)
        font_temp = _font(theme.font_name, 13)

        # Left: time + date
        time_surf = font_time.render(time_str, True, theme.text_mid)
        date_surf = font_date.render(date_str, True, theme.text_dim)
        surface.blit(time_surf, (16, (bar_h - time_surf.get_height()) // 2))
        surface.blit(date_surf, (80, (bar_h - date_surf.get_height()) // 2))

        # Center: brand name
        brand_text = "ALFA ROMEO" if not theme.is_light else "Alfa Romeo"
        brand_surf = font_brand.render(brand_text, True, theme.brand_text_color)
        surface.blit(brand_surf, (w // 2 - brand_surf.get_width() // 2,
                                  (bar_h - brand_surf.get_height()) // 2))

        # Right: temp
        temp_surf = font_temp.render(temp_str, True, (255, 255, 255))
        surface.blit(temp_surf, (w - 16 - temp_surf.get_width(),
                                 (bar_h - temp_surf.get_height()) // 2))

    @staticmethod
    def draw_nav_bar(surface: pygame.Surface, theme: ThemeBase,
                     active_index: int = 0) -> None:
        """Draw the themed bottom navigation bar."""
        w, h = surface.get_size()
        bar_h = theme.navbar_height
        bar_y = h - bar_h
        pygame.draw.rect(surface, theme.navbar_bg, (0, bar_y, w, bar_h))
        pygame.draw.line(surface, theme.appbar_border, (0, bar_y), (w, bar_y))

        # 4 nav items with labels
        labels = ["Home", "Drive", "Weather", "Service"]
        item_w = w // 4
        font = _font(theme.font_name, 10)

        for i, label in enumerate(labels):
            cx = item_w * i + item_w // 2
            cy = bar_y + bar_h // 2

            is_active = (i == active_index)
            if is_active:
                # Active pill
                pill_w, pill_h = 56, 32
                pill_rect = pygame.Rect(cx - pill_w // 2, cy - pill_h // 2, pill_w, pill_h)
                pill_surf = pygame.Surface((pill_w, pill_h), pygame.SRCALPHA)
                pygame.draw.rect(pill_surf, theme.navbar_active_bg, (0, 0, pill_w, pill_h),
                                 border_radius=10)
                surface.blit(pill_surf, pill_rect.topleft)
                color = theme.navbar_active_color
            else:
                color = theme.navbar_inactive_color

            lbl_surf = font.render(label, True, color)
            surface.blit(lbl_surf, (cx - lbl_surf.get_width() // 2,
                                    cy - lbl_surf.get_height() // 2))

    @staticmethod
    def draw_icon_thermometer(surface: pygame.Surface, cx: int, cy: int,
                              size: int, color: tuple) -> None:
        """Draw a simple thermometer icon."""
        # Stem
        pygame.draw.rect(surface, color,
                         (cx - size // 6, cy - size, size // 3, int(size * 1.4)),
                         border_radius=2)
        # Bulb
        pygame.draw.circle(surface, color, (cx, cy + int(size * 0.4)), size // 3)

    @staticmethod
    def draw_icon_fuel(surface: pygame.Surface, cx: int, cy: int,
                       size: int, color: tuple) -> None:
        """Draw a simple fuel pump icon."""
        # Pump body
        rect = pygame.Rect(cx - size // 2, cy - size // 2, int(size * 0.7), size)
        pygame.draw.rect(surface, color, rect, width=2, border_radius=2)
        # Nozzle
        pygame.draw.line(surface, color,
                         (cx + int(size * 0.2), cy - size // 3),
                         (cx + size // 2, cy - size // 2), 2)
        pygame.draw.line(surface, color,
                         (cx + size // 2, cy - size // 2),
                         (cx + size // 2, cy), 2)

    @staticmethod
    def draw_icon_check(surface: pygame.Surface, cx: int, cy: int,
                        size: int, color: tuple) -> None:
        """Draw a checkmark icon."""
        lw = max(2, size // 5)
        points = [(cx - size * 0.4, cy),
                  (cx - size * 0.1, cy + size * 0.3),
                  (cx + size * 0.5, cy - size * 0.4)]
        pygame.draw.lines(surface, color, False, points, lw)

    @staticmethod
    def draw_icon_warning(surface: pygame.Surface, cx: int, cy: int,
                          size: int, color: tuple) -> None:
        """Draw a warning triangle icon."""
        points = [(cx, cy - int(size * 0.7)),
                  (cx - int(size * 0.7), cy + int(size * 0.5)),
                  (cx + int(size * 0.7), cy + int(size * 0.5))]
        pygame.draw.polygon(surface, color, points, max(2, size // 7))

    @staticmethod
    def draw_icon_music(surface: pygame.Surface, cx: int, cy: int,
                        size: int, color: tuple) -> None:
        """Draw a music note icon."""
        lw = max(2, size // 7)
        # Stem
        pygame.draw.line(surface, color,
                         (cx + size // 6, cy - int(size * 0.7)),
                         (cx + size // 6, cy + int(size * 0.3)), lw)
        # Note head
        pygame.draw.ellipse(surface, color,
                            (cx - size // 4, cy + size // 10,
                             int(size * 0.4), int(size * 0.4)))

    @staticmethod
    def draw_icon_cloud(surface: pygame.Surface, cx: int, cy: int,
                        size: int, color: tuple) -> None:
        """Draw a cloud icon."""
        pygame.draw.ellipse(surface, color,
                            (cx - int(size * 0.7), cy - int(size * 0.1),
                             int(size * 1.4), int(size * 0.7)))
        pygame.draw.ellipse(surface, color,
                            (cx - int(size * 0.3), cy - int(size * 0.6),
                             int(size * 0.7), int(size * 0.6)))
        pygame.draw.ellipse(surface, color,
                            (cx - int(size * 0.8), cy - int(size * 0.15),
                             int(size * 0.8), int(size * 0.6)))
