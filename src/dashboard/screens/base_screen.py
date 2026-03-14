"""Base screen class — common elements for all BCM screens.

Provides: side gauge drawing (coolant temp left, fuel level right),
bottom info bar, Alfa Romeo badge, and content area helpers.
"""

import math
import pygame
from dataclasses import dataclass, field
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
        """Return (x, y, w, h) of the main content area."""
        w, _ = surface.get_size()
        gw = theme.side_gauge_width
        return (gw, theme.content_y, w - 2 * gw, theme.content_h)
