"""BCM Settings menu — theme, language, units, brightness, EQ, wake word sensitivity."""

import pygame
from src.core.config import BCMConfig
from src.core.logger import get_logger
from src.dashboard.themes.theme_base import ThemeBase

log = get_logger("settings")


def _get_font(name: str, size: int) -> pygame.font.Font:
    try:
        return pygame.font.SysFont(name, size)
    except Exception:
        return pygame.font.Font(None, size)


# Setting definitions: (config_key, display_label, options_list)
SETTINGS = [
    ("display.dashboard.theme", "Theme", ["classic_alfa", "modern_dark", "oem_digital"]),
    ("language", "Language", ["pl", "en"]),
    ("units.speed", "Speed Units", ["km/h", "mph"]),
    ("units.temperature", "Temp Units", ["C", "F"]),
    ("display.dashboard.brightness", "Brightness", list(range(0, 101, 10))),
    ("audio.eq_preset", "EQ Preset", ["flat", "rock", "jazz", "bass_boost", "custom"]),
    ("voice.wake_word_sensitivity", "Wake Sensitivity", ["low", "medium", "high"]),
]

# Display-friendly labels for option values
DISPLAY_LABELS = {
    "classic_alfa": "Classic Alfa Racing",
    "modern_dark": "Modern Dark",
    "oem_digital": "OEM Digital",
    "pl": "Polski",
    "en": "English",
    "flat": "Flat",
    "rock": "Rock",
    "jazz": "Jazz",
    "bass_boost": "Bass Boost",
    "custom": "Custom",
    "low": "Low",
    "medium": "Medium",
    "high": "High",
}


class SettingsScreen:
    """Interactive settings menu drawn on the dashboard surface."""

    def __init__(self, config: BCMConfig) -> None:
        self.config = config
        self.active: bool = False
        self.selected_index: int = 0

    def toggle(self) -> None:
        """Show/hide settings menu."""
        self.active = not self.active
        if self.active:
            self.selected_index = 0
            log.info("Settings menu opened")
        else:
            log.info("Settings menu closed")

    def navigate(self, direction: int) -> None:
        """Move selection up (-1) or down (+1)."""
        if not self.active:
            return
        self.selected_index = (self.selected_index + direction) % len(SETTINGS)

    def cycle_value(self, direction: int = 1) -> str | None:
        """Cycle the current setting's value. Returns changed config key or None."""
        if not self.active:
            return None

        key, label, options = SETTINGS[self.selected_index]
        current = self.config.get(key)

        try:
            idx = options.index(current)
        except ValueError:
            idx = 0

        new_idx = (idx + direction) % len(options)
        new_value = options[new_idx]
        self.config.set(key, new_value)
        log.info("Setting changed: %s = %s", key, new_value)
        return key

    def save(self) -> None:
        """Persist settings to config file."""
        self.config.save()
        log.info("Settings saved to %s", self.config.config_path)

    def draw(self, surface: pygame.Surface, theme: ThemeBase) -> None:
        """Draw settings menu overlay."""
        if not self.active:
            return

        w, h = surface.get_size()

        # Full-screen dark overlay
        overlay = pygame.Surface((w, h), pygame.SRCALPHA)
        overlay.fill((theme.settings_bg[0], theme.settings_bg[1], theme.settings_bg[2], 230))
        surface.blit(overlay, (0, 0))

        # Title
        font_title = _get_font(theme.font_name, 22)
        title_surf = font_title.render("BCM SETTINGS", True, theme.accent_color)
        title_rect = title_surf.get_rect(center=(w // 2, 35))
        surface.blit(title_surf, title_rect)

        # Separator
        pygame.draw.line(surface, theme.accent_color, (50, 55), (w - 50, 55), 1)

        # Settings items
        font_label = _get_font(theme.font_name, 16)
        font_value = _get_font(theme.font_name, 16)
        item_h = 48
        start_y = 70
        margin_x = 60

        for i, (key, label, options) in enumerate(SETTINGS):
            iy = start_y + i * item_h
            is_selected = (i == self.selected_index)

            # Highlight background
            if is_selected:
                pygame.draw.rect(surface, theme.settings_highlight,
                                 (margin_x - 10, iy, w - 2 * margin_x + 20, item_h - 4),
                                 border_radius=6)

            # Label
            label_color = theme.settings_text if not is_selected else theme.text_color
            lbl_surf = font_label.render(label, True, label_color)
            surface.blit(lbl_surf, (margin_x, iy + 12))

            # Current value
            current = self.config.get(key)
            display_val = DISPLAY_LABELS.get(str(current), str(current))
            if isinstance(current, int) and key == "display.dashboard.brightness":
                display_val = f"{current}%"

            val_color = theme.settings_value_color if is_selected else theme.text_secondary
            val_surf = font_value.render(display_val, True, val_color)
            val_rect = val_surf.get_rect(right=w - margin_x, centery=iy + item_h // 2)
            surface.blit(val_surf, val_rect)

            # Arrow indicators for selected item
            if is_selected:
                arrow_font = _get_font(theme.font_name, 14)
                left_arrow = arrow_font.render("<", True, val_color)
                right_arrow = arrow_font.render(">", True, val_color)
                surface.blit(left_arrow, (val_rect.left - 18, iy + 14))
                surface.blit(right_arrow, (val_rect.right + 6, iy + 14))

        # Footer help text
        font_help = _get_font(theme.font_name, 11)
        help_text = "UP/DOWN: Navigate  |  LEFT/RIGHT: Change  |  HOME: Close & Save"
        help_surf = font_help.render(help_text, True, theme.text_secondary)
        help_rect = help_surf.get_rect(center=(w // 2, h - 25))
        surface.blit(help_surf, help_rect)
