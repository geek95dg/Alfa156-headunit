"""A3: USTAWIENIA — Settings screen with theme selection and unit toggles."""

import pygame
from src.dashboard.themes.theme_base import ThemeBase
from src.dashboard.i18n import t
from .base_screen import BaseScreen, DashboardData, _font


class SettingsScreen(BaseScreen):
    screen_id = "a3"

    def draw(self, surface: pygame.Surface, theme: ThemeBase,
             data: DashboardData) -> None:
        self.draw_side_gauges(surface, theme, data)
        x, y, w, h = self.content_rect(theme, surface)
        lang = data.lang

        font_label = _font(theme.font_name, 17)
        font_value = _font(theme.font_name, 20)
        font_header = _font(theme.font_name, 22)
        font_sm = _font(theme.font_name, 13)

        cy = y + 15

        # Header
        hdr = font_header.render(t("settings", lang), True, theme.text_color)
        surface.blit(hdr, (x + w // 2 - hdr.get_width() // 2, cy))
        cy += 40

        # Separator
        pygame.draw.line(surface, theme.gauge_tick_dim,
                         (x + 30, cy), (x + w - 30, cy), 1)
        cy += 20

        # Theme row
        lbl = font_label.render(t("theme", lang) + ":", True, theme.value_label_color)
        surface.blit(lbl, (x + 30, cy))
        # Show current theme name (right-aligned)
        from src.dashboard.themes import ALL_THEMES
        theme_idx = 0
        for i, th in enumerate(ALL_THEMES):
            if th.display_name == theme.display_name:
                theme_idx = i
                break
        val = font_value.render(theme.display_name, True, theme.accent_color)
        surface.blit(val, (x + w - 30 - val.get_width(), cy - 2))
        # Nav arrows
        arr_l = font_sm.render("\u25c0", True, theme.text_secondary)
        arr_r = font_sm.render("\u25b6", True, theme.text_secondary)
        surface.blit(arr_l, (x + w - 30 - val.get_width() - 24, cy + 2))
        surface.blit(arr_r, (x + w - 30 + 8, cy + 2))
        cy += 42

        # Units row: km/h vs mph
        lbl2 = font_label.render(t("units_speed", lang) + ":", True, theme.value_label_color)
        surface.blit(lbl2, (x + 30, cy))
        unit_text = data.speed_unit
        val2 = font_value.render(unit_text, True, theme.accent_color)
        surface.blit(val2, (x + w - 30 - val2.get_width(), cy - 2))
        cy += 42

        # Temp units row: °C vs °F
        lbl3 = font_label.render(t("units_temp", lang) + ":", True, theme.value_label_color)
        surface.blit(lbl3, (x + 30, cy))
        temp_text = "°" + data.temp_unit
        val3 = font_value.render(temp_text, True, theme.accent_color)
        surface.blit(val3, (x + w - 30 - val3.get_width(), cy - 2))
        cy += 42

        # Language row
        lbl4 = font_label.render(t("language", lang) + ":", True, theme.value_label_color)
        surface.blit(lbl4, (x + 30, cy))
        lang_display = {"pl": "Polski", "en": "English", "de": "Deutsch"}.get(lang, lang)
        val4 = font_value.render(lang_display, True, theme.accent_color)
        surface.blit(val4, (x + w - 30 - val4.get_width(), cy - 2))
        cy += 42

        # Brightness row
        lbl5 = font_label.render(t("brightness", lang) + ":", True, theme.value_label_color)
        surface.blit(lbl5, (x + 30, cy))
        # Brightness bar
        bar_x = x + w // 2
        bar_w = w // 2 - 40
        bar_h = 14
        bar_y = cy + 4
        pygame.draw.rect(surface, theme.gauge_bg,
                         (bar_x, bar_y, bar_w, bar_h), border_radius=3)
        fill_w = int(0.7 * bar_w)  # Example: 70%
        if fill_w > 0:
            pygame.draw.rect(surface, theme.accent_color,
                             (bar_x, bar_y, fill_w, bar_h), border_radius=3)

        # Bottom bar
        self.draw_bottom_bar(surface, theme, [
            (t("back", lang), ""),
        ])

    def on_long_press(self, data: DashboardData) -> str | None:
        return "a1"
