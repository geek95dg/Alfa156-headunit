"""C2: SERWIS — Oil level, TPMS tires, service interval. Long push = confirm."""

import pygame
from src.dashboard.themes.theme_base import ThemeBase
from src.dashboard.i18n import t
from .base_screen import BaseScreen, DashboardData, _font


class ServiceScreen(BaseScreen):
    screen_id = "c2"

    def draw(self, surface: pygame.Surface, theme: ThemeBase,
             data: DashboardData) -> None:
        self.draw_side_gauges(surface, theme, data)
        x, y, w, h = self.content_rect(theme, surface)
        lang = data.lang

        font_label = _font(theme.font_name, 14)
        font_value = _font(theme.font_name, 22)
        font_sm = _font(theme.font_name, 12)

        cy = y + 15
        lx = x + 30
        vx = x + w // 2 + 20

        # --- Engine Oil ---
        lbl = font_label.render(t("engine_oil", lang) + ":", True, theme.value_label_color)
        surface.blit(lbl, (lx, cy))
        if data.oil_level_pct >= 0:
            pct = f"{t('ok', lang)} ({data.oil_level_pct:.0f}%)"
            color = theme.service_ok
        else:
            pct = t("no_sensor", lang)
            color = theme.text_secondary
        val = font_value.render(pct, True, color)
        surface.blit(val, (vx, cy - 4))
        cy += 38

        # --- TPMS Tires ---
        lbl2 = font_label.render(t("tires", lang) + ":", True, theme.value_label_color)
        surface.blit(lbl2, (lx, cy))
        if data.tpms_available:
            tpms_text = t("pressure_ok", lang)
            tpms_color = theme.service_ok
        else:
            tpms_text = t("tpms_future", lang)
            tpms_color = theme.text_secondary
        val2 = font_value.render(tpms_text, True, tpms_color)
        surface.blit(val2, (vx, cy - 4))
        cy += 38

        # --- Service interval ---
        lbl3 = font_label.render(t("service_interval", lang) + ":", True, theme.value_label_color)
        surface.blit(lbl3, (lx, cy))
        km_text = f"{data.service_km} {t('km', lang)}"
        km_color = theme.service_ok if data.service_km > 1000 else (
            theme.service_warn if data.service_km > 0 else theme.service_danger)
        val3 = font_value.render(km_text, True, km_color)
        surface.blit(val3, (vx, cy - 4))
        cy += 50

        # --- Oil level bar (placeholder when no sensor) ---
        bar_y = cy
        bar_x = lx
        bar_w = w - 60
        bar_h = 18

        font_bar_label = _font(theme.font_name, 11)
        ol_lbl = font_bar_label.render(t("oil_level", lang), True, theme.text_secondary)
        surface.blit(ol_lbl, (bar_x, bar_y - 2))
        bar_y += 16

        pygame.draw.rect(surface, theme.service_bar_bg,
                         (bar_x, bar_y, bar_w, bar_h), border_radius=3)
        if data.oil_level_pct >= 0:
            fill_w = int((data.oil_level_pct / 100.0) * bar_w)
            if fill_w > 0:
                color = theme.service_bar_fill
                if data.oil_level_pct < 20:
                    color = theme.service_danger
                elif data.oil_level_pct < 40:
                    color = theme.service_warn
                pygame.draw.rect(surface, color,
                                 (bar_x, bar_y, fill_w, bar_h), border_radius=3)
        else:
            # No sensor — draw diagonal lines indicating N/A
            for i in range(0, bar_w, 12):
                x1 = bar_x + i
                x2 = bar_x + i + bar_h
                pygame.draw.line(surface, theme.service_bar_bg,
                                 (x1, bar_y + bar_h), (min(x2, bar_x + bar_w), bar_y), 1)

        bar_y += bar_h + 14

        # --- Oil wear bar ---
        ow_lbl = font_bar_label.render(t("oil_wear", lang), True, theme.text_secondary)
        surface.blit(ow_lbl, (bar_x, bar_y - 2))
        bar_y += 16

        pygame.draw.rect(surface, theme.service_bar_bg,
                         (bar_x, bar_y, bar_w, bar_h), border_radius=3)
        # Simulated wear (based on service_km — lower km = more wear)
        max_interval = 15000
        wear_frac = max(0, min(1, 1.0 - data.service_km / max_interval))
        fill_w = int(wear_frac * bar_w)
        if fill_w > 0:
            color = theme.service_bar_fill
            if wear_frac > 0.8:
                color = theme.service_danger
            elif wear_frac > 0.6:
                color = theme.service_warn
            pygame.draw.rect(surface, color,
                             (bar_x, bar_y, fill_w, bar_h), border_radius=3)

        # --- TPMS tire pressures (future) ---
        if data.tpms_available:
            bar_y += bar_h + 20
            self._draw_tpms_grid(surface, theme, bar_x, bar_y, data)

        # Bottom bar
        self.draw_bottom_bar(surface, theme, [
            (t("long_push_confirm", lang), ""),
        ])

    def _draw_tpms_grid(self, surface, theme, x, y, data):
        """Draw 4 tire pressure indicators in 2x2 grid."""
        font = _font(theme.font_name, 12)
        positions = [("FL", 0), ("FR", 1), ("RL", 2), ("RR", 3)]
        for i, (label, idx) in enumerate(positions):
            col = i % 2
            row = i // 2
            tx = x + col * 120
            ty = y + row * 24
            pressure = data.tpms_pressures[idx] if idx < len(data.tpms_pressures) else 0
            color = theme.service_ok if 1.8 < pressure < 3.0 else theme.service_warn
            text = f"{label}: {pressure:.1f} bar"
            surf = font.render(text, True, color)
            surface.blit(surf, (tx, ty))

    def on_long_press(self, data: DashboardData) -> str | None:
        return "service.confirm"
