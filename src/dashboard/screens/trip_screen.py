"""A2: Trip Screen — Trip statistics + consumption chart.

Card-based layout for Heritage/Modern/Autodelta themes.
Falls back to legacy vertical layout for classic themes.
Long press = reset trip.
"""

import pygame
from src.dashboard.themes.theme_base import ThemeBase
from src.dashboard.i18n import t
from .base_screen import BaseScreen, DashboardData, _font


class TripScreen(BaseScreen):
    screen_id = "a2"

    def __init__(self) -> None:
        super().__init__()
        # Store consumption history for chart
        self._consumption_history = [6.8, 7.2, 6.5, 7.8, 8.1, 7.0, 6.4]

    def draw(self, surface: pygame.Surface, theme: ThemeBase,
             data: DashboardData) -> None:
        if hasattr(theme, "card_bg") and theme.card_bg is not None:
            self._draw_card_based(surface, theme, data)
        else:
            self._draw_legacy(surface, theme, data)

    def on_long_press(self, data: DashboardData) -> str | None:
        return "trip.reset"

    def _draw_card_based(self, surface, theme, data):
        x, y, cw, ch = self.card_content_rect(theme, surface)
        pad = 8

        accent = getattr(theme, "accent_color", (245, 158, 11))
        card_bg = getattr(theme, "card_bg", (20, 20, 20))
        card_border = getattr(theme, "card_border", (50, 50, 50))
        text_color = getattr(theme, "text_primary", (244, 244, 245))
        text_dim = getattr(theme, "text_dim", (120, 120, 120))

        # Left column: Trip stats (1/3)
        left_w = cw // 3 - pad
        self._draw_trip_stats(surface, theme, data, x, y, left_w, ch)

        # Right column: Consumption chart (2/3)
        chart_x = x + left_w + pad * 2
        chart_w = cw - left_w - pad * 2
        self._draw_consumption_chart(surface, theme, data, chart_x, y, chart_w, ch)

    def _draw_trip_stats(self, surface, theme, data, x, y, w, h):
        accent = getattr(theme, "accent_color", (245, 158, 11))
        card_bg = getattr(theme, "card_bg", (20, 20, 20))
        card_border = getattr(theme, "card_border", (50, 50, 50))
        text_color = getattr(theme, "text_primary", (244, 244, 245))
        text_dim = getattr(theme, "text_dim", (120, 120, 120))

        font_header = _font("sans-serif", 13)
        font_label = _font("sans-serif", 10)
        font_value = _font("sans-serif", 22)
        font_unit = _font("sans-serif", 10)

        # Header
        header = font_header.render("TRIP STATS", True, text_color)
        surface.blit(header, (x + 4, y))

        # Stat cards
        stats = [
            ("DISTANCE", f"{data.trip_distance:.1f}", "km"),
            ("AVG SPEED", f"{data.avg_speed:.0f}", "km/h"),
            ("TRAVEL TIME", data.trip_time_str[:5], ""),
        ]

        card_h = (h - 24) // len(stats) - 4
        for i, (label, value, unit) in enumerate(stats):
            cy = y + 22 + i * (card_h + 4)
            self.draw_card(surface, x, cy, w, card_h, card_bg, card_border)

            lbl_surf = font_label.render(label, True, text_dim)
            surface.blit(lbl_surf, (x + 10, cy + 6))

            val_surf = font_value.render(value, True, accent)
            surface.blit(val_surf, (x + 10, cy + 22))

            if unit:
                unit_surf = font_unit.render(unit, True, text_dim)
                unit_rect = unit_surf.get_rect(
                    left=val_surf.get_rect(left=x + 10).right + 4,
                    bottom=cy + 22 + val_surf.get_height() - 2
                )
                surface.blit(unit_surf, unit_rect)

    def _draw_consumption_chart(self, surface, theme, data, x, y, w, h):
        accent = getattr(theme, "accent_color", (245, 158, 11))
        card_bg = getattr(theme, "card_bg", (20, 20, 20))
        card_border = getattr(theme, "card_border", (50, 50, 50))
        text_color = getattr(theme, "text_primary", (244, 244, 245))
        text_dim = getattr(theme, "text_dim", (120, 120, 120))
        ok_color = getattr(theme, "ok_color", (34, 197, 94))

        self.draw_card(surface, x, y, w, h, card_bg, card_border)

        font_header = _font("sans-serif", 13)
        font_value = _font("sans-serif", 28)
        font_label = _font("sans-serif", 10)
        font_small = _font("sans-serif", 9)

        # Header
        header = font_header.render("AVG FUEL CONSUMPTION", True, text_color)
        surface.blit(header, (x + 14, y + 12))

        # Current consumption value
        cons_val = f"{data.avg_consumption:.1f}"
        val_surf = font_value.render(cons_val, True, accent)
        surface.blit(val_surf, (x + 14, y + 30))

        unit_surf = font_label.render("l/100km", True, text_dim)
        unit_rect = unit_surf.get_rect(
            left=val_surf.get_rect(left=x + 14).right + 6,
            bottom=y + 30 + val_surf.get_height() - 4
        )
        surface.blit(unit_surf, unit_rect)

        # Efficiency badge
        badge_text = "+1.2%"
        badge_color = ok_color
        badge_surf = font_small.render(badge_text, True, badge_color)
        badge_rect = badge_surf.get_rect(right=x + w - 14, centery=y + 50)
        # Badge background
        bg_rect = badge_rect.inflate(10, 4)
        pygame.draw.rect(surface, (*badge_color, 30), bg_rect, border_radius=3)
        surface.blit(badge_surf, badge_rect)

        # Bar chart
        chart_y = y + 80
        chart_h = h - 120
        chart_x = x + 40
        chart_w = w - 60

        # Update history with current value
        history = list(self._consumption_history)
        if data.avg_consumption > 0:
            history[-1] = data.avg_consumption

        if not history:
            return

        max_val = max(history) * 1.2
        if max_val <= 0:
            max_val = 10

        bar_count = len(history)
        bar_gap = 6
        bar_w = (chart_w - bar_gap * (bar_count - 1)) // bar_count

        for i, val in enumerate(history):
            bx = chart_x + i * (bar_w + bar_gap)
            bar_h = int((val / max_val) * chart_h)
            by = chart_y + chart_h - bar_h

            # Color gradient: dimmer for older, accent for recent
            alpha_frac = 0.3 + 0.7 * (i / (bar_count - 1)) if bar_count > 1 else 1.0
            bar_color = tuple(int(c * alpha_frac) for c in accent)

            pygame.draw.rect(surface, bar_color,
                             (bx, by, bar_w, bar_h), border_radius=3)

            # Value label on top
            val_text = f"{val:.1f}"
            vt_surf = font_small.render(val_text, True, text_dim)
            vt_rect = vt_surf.get_rect(centerx=bx + bar_w // 2, bottom=by - 2)
            surface.blit(vt_surf, vt_rect)

        # Bottom axis line
        pygame.draw.line(surface, text_dim,
                         (chart_x, chart_y + chart_h),
                         (chart_x + chart_w, chart_y + chart_h), 1)

        # Range + efficiency at bottom
        range_text = f"EST RANGE: {data.estimated_range:.0f} KM"
        range_surf = font_label.render(range_text, True, accent)
        range_rect = range_surf.get_rect(left=x + 14, bottom=y + h - 8)
        surface.blit(range_surf, range_rect)

    # ── Legacy layout ──

    def _draw_legacy(self, surface, theme, data):
        self.draw_side_gauges(surface, theme, data)
        x, y, w, h = self.content_rect(theme, surface)
        lang = data.lang

        font_label = _font(theme.font_name, 16)
        font_value = _font(theme.font_name, 38)
        font_unit = _font(theme.font_name, 16)

        items = [
            (t("distance", lang), f"{data.trip_distance:.1f}", t("km", lang)),
            (t("time", lang), data.trip_time_str[:5] if len(data.trip_time_str) >= 5
             else data.trip_time_str, t("hours", lang)),
            (t("avg_fuel", lang), f"{data.avg_consumption:.1f}", t("l_100km", lang)),
        ]

        row_h = h // 3
        for i, (label, value, unit) in enumerate(items):
            ry = y + i * row_h + 15

            lbl = font_label.render(label + ":", True, theme.value_label_color)
            surface.blit(lbl, (x + 50, ry + 8))

            val_surf = font_value.render(value, True, theme.value_large_color)
            unit_surf = font_unit.render(" " + unit, True, theme.text_secondary)

            total_w = val_surf.get_width() + unit_surf.get_width()
            vx = x + w - 60 - total_w
            surface.blit(val_surf, (vx, ry))
            surface.blit(unit_surf, (vx + val_surf.get_width(), ry + 16))

            if i < len(items) - 1:
                sep_y = ry + row_h - 5
                pygame.draw.line(surface, theme.gauge_bg,
                                 (x + 50, sep_y), (x + w - 50, sep_y), 1)

        self.draw_bottom_bar(surface, theme, [
            (t("long_push_reset", lang), ""),
        ])
