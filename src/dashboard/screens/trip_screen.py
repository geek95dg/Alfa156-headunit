"""C1: TRIP — Distance, time, average consumption. Long push = reset."""

import pygame
from src.dashboard.themes.theme_base import ThemeBase
from src.dashboard.i18n import t
from .base_screen import BaseScreen, DashboardData, _font


class TripScreen(BaseScreen):
    screen_id = "c1"

    def draw(self, surface: pygame.Surface, theme: ThemeBase,
             data: DashboardData) -> None:
        self.draw_side_gauges(surface, theme, data)
        x, y, w, h = self.content_rect(theme, surface)
        lang = data.lang
        cx = x + w // 2

        font_label = _font(theme.font_name, 16)
        font_value = _font(theme.font_name, 38)
        font_unit = _font(theme.font_name, 16)

        # Three main trip values, stacked vertically
        items = [
            (t("distance", lang), f"{data.trip_distance:.1f}", t("km", lang)),
            (t("time", lang), data.trip_time_str[:5] if len(data.trip_time_str) >= 5
             else data.trip_time_str, t("hours", lang)),
            (t("avg_fuel", lang), f"{data.avg_consumption:.1f}", t("l_100km", lang)),
        ]

        row_h = h // 3
        for i, (label, value, unit) in enumerate(items):
            ry = y + i * row_h + 15

            # Label (left)
            lbl = font_label.render(label + ":", True, theme.value_label_color)
            surface.blit(lbl, (x + 50, ry + 8))

            # Value (right, large)
            val_surf = font_value.render(value, True, theme.value_large_color)
            unit_surf = font_unit.render(" " + unit, True, theme.text_secondary)

            # Right-align value + unit
            total_w = val_surf.get_width() + unit_surf.get_width()
            vx = x + w - 60 - total_w
            surface.blit(val_surf, (vx, ry))
            surface.blit(unit_surf, (vx + val_surf.get_width(), ry + 16))

            # Separator line
            if i < len(items) - 1:
                sep_y = ry + row_h - 5
                pygame.draw.line(surface, theme.gauge_bg,
                                 (x + 50, sep_y), (x + w - 50, sep_y), 1)

        # Bottom bar
        self.draw_bottom_bar(surface, theme, [
            (t("long_push_reset", lang), ""),
        ])

    def on_long_press(self, data: DashboardData) -> str | None:
        return "trip.reset"
