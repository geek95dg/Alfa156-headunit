"""A2: SPALANIE — Detailed fuel consumption, boost, and trip distance."""

import pygame
from src.dashboard.themes.theme_base import ThemeBase
from src.dashboard.i18n import t
from .base_screen import BaseScreen, DashboardData, _font


class ConsumptionScreen(BaseScreen):
    screen_id = "a2"

    def draw(self, surface: pygame.Surface, theme: ThemeBase,
             data: DashboardData) -> None:
        self.draw_side_gauges(surface, theme, data)
        x, y, w, h = self.content_rect(theme, surface)
        lang = data.lang

        # Average consumption (large)
        font_label = _font(theme.font_name, 14)
        font_value = _font(theme.font_name, 32)
        font_unit = _font(theme.font_name, 16)
        font_med = _font(theme.font_name, 22)
        font_sm = _font(theme.font_name, 13)

        cy = y + 20

        # ŚR. SPALANIE: 8.5 L/100KM
        lbl = font_label.render(t("avg_consumption", lang), True, theme.value_label_color)
        surface.blit(lbl, (x + 30, cy))
        cy += 20
        val_text = f"{data.avg_consumption:.1f}"
        val_surf = font_value.render(val_text, True, theme.value_medium_color)
        surface.blit(val_surf, (x + 30, cy))
        unit_surf = font_unit.render(t("l_100km", lang), True, theme.text_secondary)
        surface.blit(unit_surf, (x + 30 + val_surf.get_width() + 8, cy + 10))

        cy += 44

        # CHW. SPALANIE: 12.4 L/100KM
        lbl2 = font_sm.render(t("inst_consumption", lang), True, theme.value_label_color)
        surface.blit(lbl2, (x + 30, cy))
        val2 = font_med.render(f"{data.instant_consumption:.1f}", True, theme.text_color)
        surface.blit(val2, (x + 30 + lbl2.get_width() + 10, cy - 4))
        u2 = font_sm.render(t("l_100km", lang), True, theme.text_secondary)
        surface.blit(u2, (x + 30 + lbl2.get_width() + 10 + val2.get_width() + 6, cy + 2))

        cy += 35

        # Boost bar (0 - 1.5 BAR)
        bar_x = x + 30
        bar_w = w - 60
        bar_h = 20
        self._draw_boost_bar(surface, theme, bar_x, cy, bar_w, bar_h,
                             data.boost_bar, data.lang)

        cy += 40

        # Trip distance
        lbl_td = font_sm.render(t("trip_dist", lang) + ":", True, theme.value_label_color)
        surface.blit(lbl_td, (x + 30, cy))
        val_td = font_med.render(f"{data.trip_distance:.1f} {t('km', lang)}",
                                 True, theme.text_color)
        surface.blit(val_td, (x + 30 + lbl_td.get_width() + 10, cy - 4))

        # Bottom bar
        self.draw_bottom_bar(surface, theme, [
            (t("trip_time", lang), data.trip_time_str.replace(":", ":", 1)[:-3] + " H"
             if len(data.trip_time_str) > 5 else data.trip_time_str + " H"),
            (t("fuel_used", lang), f"{data.trip_fuel_used:.1f} {t('liters', lang)}"),
        ])

    def _draw_boost_bar(self, surface, theme, x, y, w, h, value, lang):
        """Draw turbo boost pressure bar (0.0 - 1.5+ BAR)."""
        font_s = _font(theme.font_name, 10)
        font_v = _font(theme.font_name, 13)

        max_boost = 1.8
        clamped = max(0, min(max_boost, value))
        frac = clamped / max_boost

        # Background
        pygame.draw.rect(surface, theme.gauge_bg, (x, y, w, h), border_radius=3)

        # Fill
        fill_w = int(frac * w)
        if fill_w > 0:
            color = theme.gauge_fg if value < 1.2 else theme.warning_color
            if value > 1.5:
                color = theme.danger_color
            pygame.draw.rect(surface, color, (x, y, fill_w, h), border_radius=3)

        # Scale markers
        for val in [0.0, 0.5, 1.0, 1.5]:
            mx = x + int((val / max_boost) * w)
            pygame.draw.line(surface, theme.gauge_tick, (mx, y), (mx, y + h), 1)
            lbl = font_s.render(f"{val:.1f}", True, theme.text_secondary)
            surface.blit(lbl, (mx - lbl.get_width() // 2, y + h + 2))

        # BAR label
        bar_label = font_s.render(t("bar", lang), True, theme.text_secondary)
        surface.blit(bar_label, (x + w + 5, y + 3))

        # Current value
        val_text = font_v.render(f"{value:.1f} BAR", True, theme.value_medium_color)
        surface.blit(val_text, (x + w - val_text.get_width(), y - 18))
