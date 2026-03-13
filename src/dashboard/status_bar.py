"""Status bar — top bar with BT icon, temperature, icing warning, clock, audio source."""

import time
import pygame
from src.dashboard.themes.theme_base import ThemeBase


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

    def draw(self, surface: pygame.Surface, theme: ThemeBase) -> None:
        """Draw the status bar at the top of the screen."""
        x, y, w, h = theme.status_rect

        # Background
        pygame.draw.rect(surface, theme.status_bar_bg, (x, y, w, h))
        # Bottom separator line
        pygame.draw.line(surface, theme.accent_color, (x, y + h - 1), (x + w, y + h - 1), 1)

        font = _get_font(theme.font_name, theme.status_bar_font_size)
        pad = 8
        text_y = y + (h - theme.status_bar_font_size) // 2

        # Left side: BT icon + audio source
        left_x = pad
        if self.bluetooth_connected:
            bt_text = "BT"
            bt_surf = font.render(bt_text, True, theme.accent_color)
        else:
            bt_text = "BT"
            bt_surf = font.render(bt_text, True, theme.text_secondary)
        surface.blit(bt_surf, (left_x, text_y))
        left_x += bt_surf.get_width() + pad

        # Audio source
        src_surf = font.render(self.audio_source, True, theme.status_bar_text_color)
        surface.blit(src_surf, (left_x, text_y))
        left_x += src_surf.get_width() + pad

        # Recording indicator
        if self.recording:
            rec_surf = font.render("REC", True, theme.danger_color)
            surface.blit(rec_surf, (left_x, text_y))
            # Red dot
            pygame.draw.circle(surface, theme.danger_color, (left_x - 6, text_y + 7), 4)
            left_x += rec_surf.get_width() + pad

        # Voice indicator
        if self.voice_active:
            mic_surf = font.render("MIC", True, theme.ok_color)
            surface.blit(mic_surf, (left_x, text_y))

        # Right side: temperature + clock
        right_x = w - pad

        # Clock
        clock_str = time.strftime("%H:%M")
        clock_surf = font.render(clock_str, True, theme.status_bar_text_color)
        right_x -= clock_surf.get_width()
        surface.blit(clock_surf, (right_x, text_y))
        right_x -= pad * 2

        # Temperature
        if self.temperature is not None:
            temp_str = f"{self.temperature:.1f}\u00b0C"
            temp_color = theme.status_bar_text_color
            if self.icing_warning:
                temp_color = theme.warning_color
            if self.temperature <= 0:
                temp_color = theme.danger_color
                temp_str = f"*{self.temperature:.1f}\u00b0C"  # snowflake placeholder
            temp_surf = font.render(temp_str, True, temp_color)
            right_x -= temp_surf.get_width()
            surface.blit(temp_surf, (right_x, text_y))
