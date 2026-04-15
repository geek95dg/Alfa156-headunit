"""B2: PALIWO — Graphical fuel tank, estimated range, reserve indicator."""

import math
import pygame
from src.dashboard.themes.theme_base import ThemeBase
from src.dashboard.i18n import t
from .base_screen import BaseScreen, DashboardData, _font, _lerp_color


class FuelScreen(BaseScreen):
    screen_id = "b2"

    def draw(self, surface: pygame.Surface, theme: ThemeBase,
             data: DashboardData) -> None:
        self.draw_side_gauges(surface, theme, data)
        x, y, w, h = self.content_rect(theme, surface)
        lang = data.lang
        cx = x + w // 2

        # Fuel tank graphic
        tank_cx = cx
        tank_cy = y + h // 2 - 20
        self._draw_fuel_tank(surface, theme, tank_cx, tank_cy, data.fuel_level)

        # Range (large text)
        range_y = tank_cy + 80
        font_label = _font(theme.font_name, 16)
        font_val = _font(theme.font_name, 48)

        lbl = font_label.render(t("range", lang) + ":", True, theme.value_label_color)
        lbl_rect = lbl.get_rect(center=(cx, range_y))
        surface.blit(lbl, lbl_rect)

        range_text = f"{data.estimated_range:.0f} {t('km', lang)}"
        val_surf = font_val.render(range_text, True, theme.value_large_color)
        val_rect = val_surf.get_rect(center=(cx, range_y + 44))
        surface.blit(val_surf, val_rect)

        # Bottom bar
        avg_text = f"{data.avg_consumption:.1f} {t('l_100km', lang)}"
        reserve = data.fuel_level < 15
        if reserve:
            reserve_text = t("reserve_active", lang) + " !"
        else:
            reserve_text = t("reserve_off", lang)
        self.draw_bottom_bar(surface, theme, [
            (t("avg_used", lang), avg_text),
            ("", reserve_text),
        ])

        # Reserve warning flash
        if reserve:
            font_warn = _font(theme.font_name, 13)
            import time
            if int(time.time() * 2) % 2:
                warn_surf = font_warn.render("!", True, theme.warning_color)
                sw, sh = surface.get_size()
                surface.blit(warn_surf, (sw - theme.side_gauge_width - 20,
                                         sh - theme.bottom_bar_height - 18))

    def _draw_fuel_tank(self, surface, theme, cx, cy, fuel_pct):
        """Draw stylized fuel tank graphic with fill level."""
        # Tank body (rounded rectangle)
        tw, th = 220, 100
        tx = cx - tw // 2
        ty = cy - th // 2

        # Shadow
        shadow = pygame.Surface((tw + 4, th + 4), pygame.SRCALPHA)
        pygame.draw.rect(shadow, (0, 0, 0, 60), (0, 0, tw + 4, th + 4), border_radius=16)
        surface.blit(shadow, (tx - 2, ty + 2))

        # Tank outline
        pygame.draw.rect(surface, theme.fuel_tank_outline, (tx, ty, tw, th), border_radius=14)

        # Tank body fill (background)
        inner_margin = 3
        pygame.draw.rect(surface, theme.bg_color,
                         (tx + inner_margin, ty + inner_margin,
                          tw - 2 * inner_margin, th - 2 * inner_margin),
                         border_radius=12)

        # Fuel fill
        frac = max(0, min(1, fuel_pct / 100.0))
        fill_w = int(frac * (tw - 2 * inner_margin - 4))
        if fill_w > 0:
            fill_color = theme.fuel_tank_body
            if fuel_pct < 15:
                fill_color = theme.danger_color
            elif fuel_pct < 25:
                fill_color = theme.warning_color

            fill_x = tx + inner_margin + 2
            fill_y = ty + inner_margin + 2
            fill_h = th - 2 * inner_margin - 4
            pygame.draw.rect(surface, fill_color,
                             (fill_x, fill_y, fill_w, fill_h),
                             border_radius=10)

            # Highlight on fuel surface
            hl_h = 4
            hl_color = theme.fuel_tank_highlight
            pygame.draw.rect(surface, hl_color,
                             (fill_x + 4, fill_y + 4, fill_w - 8, hl_h),
                             border_radius=2)

        # Tank cap (right side nub)
        cap_w, cap_h = 12, 24
        cap_x = tx + tw - 2
        cap_y = cy - cap_h // 2
        pygame.draw.rect(surface, theme.fuel_tank_outline,
                         (cap_x, cap_y, cap_w, cap_h), border_radius=4)

        # Fuel level percentage in tank
        font_pct = _font(theme.font_name, 28)
        pct_text = f"{fuel_pct:.0f}%"
        pct_surf = font_pct.render(pct_text, True, theme.text_color)
        pct_rect = pct_surf.get_rect(center=(cx, cy))
        surface.blit(pct_surf, pct_rect)
