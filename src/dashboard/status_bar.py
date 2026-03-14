"""Status bar — top bar with screen title, Alfa badge, gear indicator, clock.

Layout: [A1: GŁÓWNY]  [Alfa badge] [gear icon] N   14:09
"""

import time
import pygame
from src.dashboard.themes.theme_base import ThemeBase
from src.dashboard.i18n import t


def _get_font(name: str, size: int) -> pygame.font.Font:
    try:
        return pygame.font.SysFont(name, size)
    except Exception:
        return pygame.font.Font(None, size)


class StatusBar:
    """Renders the top status bar on the dashboard."""

    def __init__(self) -> None:
        self.bluetooth_connected: bool = False
        self.audio_source: str = "---"
        self.temperature: float | None = None
        self.icing_warning: bool = False
        self.recording: bool = False
        self.voice_active: bool = False

    def draw(self, surface: pygame.Surface, theme: ThemeBase,
             data=None, screen_title_key: str = "") -> None:
        """Draw the status bar at the top of the screen."""
        x, y, w, h = theme.status_rect

        # Background
        pygame.draw.rect(surface, theme.status_bar_bg, (x, y, w, h))
        # Bottom separator line
        pygame.draw.line(surface, theme.accent_color, (x, y + h - 1), (x + w, y + h - 1), 1)

        lang = data.lang if data else "pl"
        pad = 8
        text_y = y + (h - theme.status_bar_font_size) // 2

        # Left: Screen title
        left_x = pad
        font_title = _get_font(theme.font_name, theme.screen_title_size)
        title_text = t(screen_title_key, lang) if screen_title_key else ""
        title_surf = font_title.render(title_text, True, theme.screen_title_color)
        surface.blit(title_surf, (left_x, text_y))
        left_x += title_surf.get_width() + pad * 2

        # Center area: Alfa badge + gear indicator
        center_x = w // 2
        font = _get_font(theme.font_name, theme.status_bar_font_size)

        # Alfa badge (simplified)
        badge_cx = center_x - 20
        badge_cy = y + h // 2
        self._draw_badge(surface, theme, badge_cx, badge_cy, 9)

        # Settings gear icon
        gear_icon_x = center_x
        gear_surf = font.render("\u2699", True, theme.text_secondary)
        surface.blit(gear_surf, (gear_icon_x, text_y))

        # Gear indicator (N / R)
        gear_x = center_x + 24
        gear_text = data.gear if data else "N"
        gear_color = theme.accent_color if gear_text == "R" else theme.text_color
        font_gear = _get_font(theme.font_name, theme.status_bar_font_size + 2)
        gear_surf = font_gear.render(gear_text, True, gear_color)
        surface.blit(gear_surf, (gear_x, text_y - 1))

        # Right side: temperature + clock
        right_x = w - pad

        # Clock
        clock_str = time.strftime("%H:%M")
        font_clock = _get_font(theme.font_name, theme.status_bar_font_size + 2)
        clock_surf = font_clock.render(clock_str, True, theme.status_bar_text_color)
        right_x -= clock_surf.get_width()
        surface.blit(clock_surf, (right_x, text_y - 1))
        right_x -= pad * 2

        # Temperature (if available)
        if self.temperature is not None:
            temp_str = f"{self.temperature:.1f}\u00b0C"
            temp_color = theme.status_bar_text_color
            if self.icing_warning:
                temp_color = theme.warning_color
            if self.temperature <= 0:
                temp_color = theme.danger_color
                temp_str = f"*{self.temperature:.1f}\u00b0C"
            temp_surf = font.render(temp_str, True, temp_color)
            right_x -= temp_surf.get_width()
            surface.blit(temp_surf, (right_x, text_y))
            right_x -= pad

        # Recording indicator
        if self.recording:
            rec_surf = font.render("REC", True, theme.danger_color)
            right_x -= rec_surf.get_width()
            surface.blit(rec_surf, (right_x, text_y))
            pygame.draw.circle(surface, theme.danger_color, (right_x - 6, text_y + 7), 3)
            right_x -= pad + 8

        # BT indicator
        if self.bluetooth_connected:
            bt_surf = font.render("BT", True, theme.accent_color)
        else:
            bt_surf = font.render("BT", True, (60, 60, 60))
        right_x -= bt_surf.get_width()
        surface.blit(bt_surf, (right_x, text_y))

    def _draw_badge(self, surface, theme, cx, cy, radius):
        """Draw simplified Alfa Romeo badge."""
        pygame.draw.circle(surface, theme.badge_circle, (cx, cy), radius, 1)
        # Cross
        pygame.draw.line(surface, theme.badge_circle,
                         (cx, cy - radius + 3), (cx, cy + radius - 3), 1)
        pygame.draw.line(surface, theme.badge_circle,
                         (cx - radius + 3, cy), (cx + radius - 3, cy), 1)
        # Red quadrant dot
        pygame.draw.circle(surface, theme.badge_cross, (cx - 3, cy - 3), 2)
