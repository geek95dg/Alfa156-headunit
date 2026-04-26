"""Status bar / App bar — top bar with screen title, brand, clock.

v7.1: Theme-aware — renders themed app bar for Heritage/Modern/Autodelta,
falls back to legacy status bar for classic themes.

Heritage: Black bg, time left zinc-400, "ALFA ROMEO" center in red, temp + BT right
Modern:   Black bg, time bold + date left, "Alfa Romeo" italic red center, icons right
Autodelta: #111 bg, time + date left, orange screen label center, icons right
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
    """Renders the top status/app bar on the dashboard."""

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
        # Detect card-based theme
        if hasattr(theme, "card_bg") and theme.card_bg is not None:
            self._draw_themed_appbar(surface, theme, data, screen_title_key)
        else:
            self._draw_legacy(surface, theme, data, screen_title_key)

    def _draw_themed_appbar(self, surface, theme, data, screen_title_key):
        """Card-based themed app bar."""
        w, h_surface = surface.get_size()
        appbar_h = getattr(theme, "appbar_height", 48)
        appbar_bg = getattr(theme, "appbar_bg", (0, 0, 0))
        theme_name = getattr(theme, "name", "heritage")

        # Background
        pygame.draw.rect(surface, appbar_bg, (0, 0, w, appbar_h))

        # Bottom border line
        accent = getattr(theme, "accent_color", (245, 158, 11))
        border_color = getattr(theme, "appbar_border", accent)
        pygame.draw.line(surface, border_color, (0, appbar_h - 1), (w, appbar_h - 1), 1)

        lang = data.lang if data else "pl"
        pad = 12
        cy = appbar_h // 2

        # ── Left: Time + Date ──
        clock_str = time.strftime("%H:%M")
        date_str = time.strftime("%b %d")

        text_color = getattr(theme, "text_primary", (244, 244, 245))
        text_dim = getattr(theme, "text_dim", (120, 120, 120))

        font_time = _get_font("sans-serif", 16)
        font_date = _get_font("sans-serif", 11)

        time_surf = font_time.render(clock_str, True, text_color)
        surface.blit(time_surf, (pad, cy - time_surf.get_height() // 2))

        date_surf = font_date.render(date_str, True, text_dim)
        surface.blit(date_surf, (pad + time_surf.get_width() + 8, cy - date_surf.get_height() // 2))

        # ── Center: Brand text ──
        brand_color = getattr(theme, "brand_text_color", (220, 38, 38))
        if theme_name == "autodelta":
            # Orange screen label
            screen_label = screen_title_key.replace("screen.", "").upper() if screen_title_key else "HOME"
            font_brand = _get_font("sans-serif", 13)
            brand_surf = font_brand.render(screen_label, True, accent)
            brand_rect = brand_surf.get_rect(center=(w // 2, cy))

            # Orange circle behind
            circle_r = max(brand_surf.get_width() // 2 + 12, 20)
            pygame.draw.circle(surface, accent, (w // 2, cy), circle_r, 1)
            surface.blit(brand_surf, brand_rect)
        else:
            brand_text = "ALFA ROMEO"
            font_brand = _get_font("sans-serif", 12)
            brand_surf = font_brand.render(brand_text, True, brand_color)
            brand_rect = brand_surf.get_rect(center=(w // 2, cy))
            surface.blit(brand_surf, brand_rect)

        # ── Right: Temp + BT + LTE ──
        right_x = w - pad

        # Temperature
        if self.temperature is not None:
            temp_str = f"{self.temperature:.0f}°"
            temp_color = text_color
            if self.icing_warning:
                temp_color = getattr(theme, "warning_color", (245, 158, 11))
            if self.temperature <= 0:
                temp_color = getattr(theme, "danger_color", (220, 38, 38))
                temp_str = f"*{self.temperature:.0f}°"
            font_temp = _get_font("sans-serif", 14)
            temp_surf = font_temp.render(temp_str, True, temp_color)
            right_x -= temp_surf.get_width()
            surface.blit(temp_surf, (right_x, cy - temp_surf.get_height() // 2))
            right_x -= 10

        # BT icon
        font_icon = _get_font("sans-serif", 12)
        bt_color = accent if self.bluetooth_connected else (60, 60, 60)
        bt_surf = font_icon.render("BT", True, bt_color)
        right_x -= bt_surf.get_width()
        surface.blit(bt_surf, (right_x, cy - bt_surf.get_height() // 2))
        right_x -= 10

        # LTE signal indicator
        if data and hasattr(data, "lte_connected"):
            lte_color = (34, 197, 94) if data.lte_connected else (60, 60, 60)
            bars = getattr(data, "lte_signal_strength", 0) if data.lte_connected else 0
            for i in range(5):
                bar_h = 4 + i * 3
                bar_x = right_x - (5 - i) * 5
                bar_y = cy + 8 - bar_h
                color = lte_color if i < bars else (40, 40, 40)
                pygame.draw.rect(surface, color, (bar_x, bar_y, 3, bar_h))

    def _draw_legacy(self, surface, theme, data, screen_title_key):
        """Legacy status bar for classic themes."""
        x, y, w, h = theme.status_rect

        pygame.draw.rect(surface, theme.status_bar_bg, (x, y, w, h))
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

        # Center: Badge + gear
        center_x = w // 2
        font = _get_font(theme.font_name, theme.status_bar_font_size)

        badge_cx = center_x - 20
        badge_cy = y + h // 2
        self._draw_badge(surface, theme, badge_cx, badge_cy, 9)

        gear_icon_x = center_x
        gear_surf = font.render("\u2699", True, theme.text_secondary)
        surface.blit(gear_surf, (gear_icon_x, text_y))

        gear_x = center_x + 24
        gear_text = data.gear if data else "N"
        gear_color = theme.accent_color if gear_text == "R" else theme.text_color
        font_gear = _get_font(theme.font_name, theme.status_bar_font_size + 2)
        gear_surf = font_gear.render(gear_text, True, gear_color)
        surface.blit(gear_surf, (gear_x, text_y - 1))

        # Right: Clock + temp + BT
        right_x = w - pad

        clock_str = time.strftime("%H:%M")
        font_clock = _get_font(theme.font_name, theme.status_bar_font_size + 2)
        clock_surf = font_clock.render(clock_str, True, theme.status_bar_text_color)
        right_x -= clock_surf.get_width()
        surface.blit(clock_surf, (right_x, text_y - 1))
        right_x -= pad * 2

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

        if self.recording:
            rec_surf = font.render("REC", True, theme.danger_color)
            right_x -= rec_surf.get_width()
            surface.blit(rec_surf, (right_x, text_y))
            pygame.draw.circle(surface, theme.danger_color, (right_x - 6, text_y + 7), 3)
            right_x -= pad + 8

        if self.bluetooth_connected:
            bt_surf = font.render("BT", True, theme.accent_color)
        else:
            bt_surf = font.render("BT", True, (60, 60, 60))
        right_x -= bt_surf.get_width()
        surface.blit(bt_surf, (right_x, text_y))

    def _draw_badge(self, surface, theme, cx, cy, radius):
        """Draw simplified Alfa Romeo badge."""
        pygame.draw.circle(surface, theme.badge_circle, (cx, cy), radius, 1)
        pygame.draw.line(surface, theme.badge_circle,
                         (cx, cy - radius + 3), (cx, cy + radius - 3), 1)
        pygame.draw.line(surface, theme.badge_circle,
                         (cx - radius + 3, cy), (cx + radius - 3, cy), 1)
        pygame.draw.circle(surface, theme.badge_cross, (cx - 3, cy - 3), 2)
