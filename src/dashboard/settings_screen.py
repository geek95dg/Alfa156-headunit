"""BCM Settings menu — general settings + SWC button configuration.

Two pages:
    Page 1 (GENERAL): Theme, language, units, brightness, EQ, wake sensitivity
    Page 2 (SWC BUTTONS): Remap each SWC button to a different action

Navigate between pages with LEFT/RIGHT on the page indicator row, or press
BACK to go from page 2 to page 1.
"""

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


# --- Page 1: General settings ---
# (config_key, display_label, options_list)
SETTINGS = [
    ("display.dashboard.theme", "Theme", ["classic_alfa", "modern_dark", "oem_digital"]),
    ("language", "Language", ["pl", "en"]),
    ("units.speed", "Speed Units", ["km/h", "mph"]),
    ("units.temperature", "Temp Units", ["C", "F"]),
    ("display.dashboard.brightness", "Brightness", list(range(0, 101, 10))),
    ("audio.eq_preset", "EQ Preset", ["flat", "rock", "jazz", "bass_boost", "custom"]),
    ("voice.wake_word_sensitivity", "Wake Sensitivity", ["low", "medium", "high"]),
]

# --- Page 2: SWC button configuration ---
# SWC button names and available actions they can be mapped to
SWC_BUTTON_NAMES = [
    "SWC_VOLUP", "SWC_VOLDN", "SWC_UP", "SWC_DOWN", "SWC_MUTE", "SWC_MODE",
    "SWC_NEXT", "SWC_PREV", "SWC_PICKUP", "SWC_HANGUP", "SWC_VOICE", "SWC_SRC",
]

# Short display names for SWC buttons
SWC_DISPLAY_NAMES = {
    "SWC_VOLUP": "VOL+",
    "SWC_VOLDN": "VOL-",
    "SWC_UP": "UP",
    "SWC_DOWN": "DOWN",
    "SWC_MUTE": "MUTE",
    "SWC_MODE": "MODE",
    "SWC_NEXT": "NEXT",
    "SWC_PREV": "PREV",
    "SWC_PICKUP": "PICKUP",
    "SWC_HANGUP": "HANGUP",
    "SWC_VOICE": "VOICE",
    "SWC_SRC": "SRC",
}

# Available actions that SWC buttons can be mapped to
SWC_AVAILABLE_ACTIONS = [
    "volume_up",
    "volume_down",
    "mute",
    "menu_up",
    "menu_down",
    "home",
    "back",
    "next_track",
    "prev_track",
    "play_pause",
    "phone_pickup",
    "phone_hangup",
    "voice_trigger",
    "source_cycle",
    "brightness_cycle",
    "disabled",
]

# Human-readable names for actions
ACTION_DISPLAY_NAMES = {
    "volume_up": "Volume Up",
    "volume_down": "Volume Down",
    "mute": "Mute",
    "menu_up": "Menu Up",
    "menu_down": "Menu Down",
    "home": "Home / Settings",
    "back": "Back",
    "next_track": "Next Track",
    "prev_track": "Prev Track",
    "play_pause": "Play/Pause",
    "phone_pickup": "Phone Pickup",
    "phone_hangup": "Phone Hangup",
    "voice_trigger": "Voice Assist",
    "source_cycle": "Source Cycle",
    "brightness_cycle": "Brightness",
    "disabled": "-- Disabled --",
}

# Display-friendly labels for page 1 values
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

# Page constants
PAGE_GENERAL = 0
PAGE_SWC = 1
PAGE_COUNT = 2
PAGE_TITLES = ["BCM SETTINGS", "SWC BUTTON MAPPING"]


class SettingsScreen:
    """Interactive settings menu drawn on the dashboard surface.

    Two pages:
        Page 0 (General): 7 settings (theme, lang, units, brightness, EQ, wake)
        Page 1 (SWC): 12 SWC button-to-action mappings (overridable)
    """

    def __init__(self, config: BCMConfig) -> None:
        self.config = config
        self.active: bool = False
        self.selected_index: int = 0
        self.page: int = PAGE_GENERAL

        # Initialize SWC overrides from config (or use defaults)
        self._init_swc_config()

    def _init_swc_config(self) -> None:
        """Load SWC button overrides from config, or set defaults."""
        from src.input.swc_remote import SWC_BUTTONS
        for btn_name in SWC_BUTTON_NAMES:
            config_key = f"swc.buttons.{btn_name}"
            current = self.config.get(config_key)
            if current is None:
                # Set default from SWC_BUTTONS
                default_action = SWC_BUTTONS.get(btn_name, "disabled")
                self.config.set(config_key, default_action)

    def _current_items(self) -> list:
        """Return the items list for the current page."""
        if self.page == PAGE_GENERAL:
            return SETTINGS
        else:
            return SWC_BUTTON_NAMES

    def toggle(self) -> None:
        """Show/hide settings menu."""
        self.active = not self.active
        if self.active:
            self.selected_index = 0
            self.page = PAGE_GENERAL
            log.info("Settings menu opened")
        else:
            log.info("Settings menu closed")

    def navigate(self, direction: int) -> None:
        """Move selection up (-1) or down (+1)."""
        if not self.active:
            return
        items = self._current_items()
        self.selected_index = (self.selected_index + direction) % len(items)

    def switch_page(self, direction: int) -> None:
        """Switch between settings pages."""
        if not self.active:
            return
        new_page = (self.page + direction) % PAGE_COUNT
        if new_page != self.page:
            self.page = new_page
            self.selected_index = 0
            log.info("Settings page: %s", PAGE_TITLES[self.page])

    def cycle_value(self, direction: int = 1) -> str | None:
        """Cycle the current setting's value. Returns changed config key or None."""
        if not self.active:
            return None

        if self.page == PAGE_GENERAL:
            return self._cycle_general(direction)
        else:
            return self._cycle_swc(direction)

    def _cycle_general(self, direction: int) -> str | None:
        """Cycle a general settings value."""
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

    def _cycle_swc(self, direction: int) -> str | None:
        """Cycle a SWC button's assigned action."""
        btn_name = SWC_BUTTON_NAMES[self.selected_index]
        config_key = f"swc.buttons.{btn_name}"
        current = self.config.get(config_key, "disabled")

        try:
            idx = SWC_AVAILABLE_ACTIONS.index(current)
        except ValueError:
            idx = 0

        new_idx = (idx + direction) % len(SWC_AVAILABLE_ACTIONS)
        new_action = SWC_AVAILABLE_ACTIONS[new_idx]
        self.config.set(config_key, new_action)
        log.info("SWC mapping changed: %s = %s", btn_name, new_action)
        return config_key

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

        # Title + page indicator
        font_title = _get_font(theme.font_name, 20)
        title_text = PAGE_TITLES[self.page]
        title_surf = font_title.render(title_text, True, theme.accent_color)
        title_rect = title_surf.get_rect(center=(w // 2, 25))
        surface.blit(title_surf, title_rect)

        # Page dots
        dot_y = 40
        dot_spacing = 14
        dot_start_x = w // 2 - (PAGE_COUNT - 1) * dot_spacing // 2
        for i in range(PAGE_COUNT):
            dx = dot_start_x + i * dot_spacing
            color = theme.accent_color if i == self.page else theme.text_secondary
            pygame.draw.circle(surface, color, (dx, dot_y), 4 if i == self.page else 3)

        # Separator
        pygame.draw.line(surface, theme.accent_color, (40, 50), (w - 40, 50), 1)

        if self.page == PAGE_GENERAL:
            self._draw_general(surface, theme, w, h)
        else:
            self._draw_swc(surface, theme, w, h)

        # Footer help text
        font_help = _get_font(theme.font_name, 10)
        if self.page == PAGE_GENERAL:
            help_text = "UP/DOWN: Navigate | LEFT/RIGHT: Change | BACK: SWC Page | HOME: Save & Close"
        else:
            help_text = "UP/DOWN: Navigate | LEFT/RIGHT: Remap | BACK: General | HOME: Save & Close"
        help_surf = font_help.render(help_text, True, theme.text_secondary)
        help_rect = help_surf.get_rect(center=(w // 2, h - 15))
        surface.blit(help_surf, help_rect)

    def _draw_general(self, surface: pygame.Surface, theme: ThemeBase,
                      w: int, h: int) -> None:
        """Draw page 1: general settings."""
        font_label = _get_font(theme.font_name, 15)
        font_value = _get_font(theme.font_name, 15)
        item_h = 44
        start_y = 58
        margin_x = 50

        for i, (key, label, options) in enumerate(SETTINGS):
            iy = start_y + i * item_h
            is_selected = (i == self.selected_index)

            if is_selected:
                pygame.draw.rect(surface, theme.settings_highlight,
                                 (margin_x - 8, iy, w - 2 * margin_x + 16, item_h - 4),
                                 border_radius=5)

            label_color = theme.settings_text if not is_selected else theme.text_color
            lbl_surf = font_label.render(label, True, label_color)
            surface.blit(lbl_surf, (margin_x, iy + 10))

            current = self.config.get(key)
            display_val = DISPLAY_LABELS.get(str(current), str(current))
            if isinstance(current, int) and key == "display.dashboard.brightness":
                display_val = f"{current}%"

            val_color = theme.settings_value_color if is_selected else theme.text_secondary
            val_surf = font_value.render(display_val, True, val_color)
            val_rect = val_surf.get_rect(right=w - margin_x, centery=iy + item_h // 2)
            surface.blit(val_surf, val_rect)

            if is_selected:
                arrow_font = _get_font(theme.font_name, 13)
                left_arrow = arrow_font.render("<", True, val_color)
                right_arrow = arrow_font.render(">", True, val_color)
                surface.blit(left_arrow, (val_rect.left - 16, iy + 11))
                surface.blit(right_arrow, (val_rect.right + 5, iy + 11))

    def _draw_swc(self, surface: pygame.Surface, theme: ThemeBase,
                  w: int, h: int) -> None:
        """Draw page 2: SWC button mapping."""
        font_label = _get_font(theme.font_name, 13)
        font_value = _get_font(theme.font_name, 13)

        # Two columns of 6 items each (buttons are small)
        col_w = w // 2
        item_h = 32
        start_y = 58
        margin_x = 20

        for i, btn_name in enumerate(SWC_BUTTON_NAMES):
            col = i // 6
            row = i % 6
            ix = col * col_w + margin_x
            iy = start_y + row * item_h
            cell_w = col_w - margin_x * 2

            is_selected = (i == self.selected_index)

            if is_selected:
                pygame.draw.rect(surface, theme.settings_highlight,
                                 (ix - 4, iy, cell_w + 8, item_h - 2),
                                 border_radius=4)

            # Button name
            display_name = SWC_DISPLAY_NAMES.get(btn_name, btn_name)
            label_color = theme.settings_text if not is_selected else theme.text_color
            lbl_surf = font_label.render(display_name, True, label_color)
            surface.blit(lbl_surf, (ix, iy + 6))

            # Current action
            config_key = f"swc.buttons.{btn_name}"
            current_action = self.config.get(config_key, "disabled")
            action_display = ACTION_DISPLAY_NAMES.get(current_action, current_action)

            val_color = theme.settings_value_color if is_selected else theme.text_secondary
            val_surf = font_value.render(action_display, True, val_color)
            val_rect = val_surf.get_rect(right=ix + cell_w, centery=iy + item_h // 2)
            surface.blit(val_surf, val_rect)

            if is_selected:
                arrow_font = _get_font(theme.font_name, 11)
                left_arrow = arrow_font.render("<", True, val_color)
                right_arrow = arrow_font.render(">", True, val_color)
                surface.blit(left_arrow, (val_rect.left - 14, iy + 7))
                surface.blit(right_arrow, (val_rect.right + 3, iy + 7))

        # Default hint
        font_hint = _get_font(theme.font_name, 10)
        hint_surf = font_hint.render(
            "Changes override default SWC mappings. Reset by setting to default action.",
            True, theme.text_secondary)
        hint_rect = hint_surf.get_rect(center=(w // 2, start_y + 6 * item_h + 12))
        surface.blit(hint_surf, hint_rect)
