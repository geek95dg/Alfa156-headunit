"""B1: KLIMAT — Date, time (analog clock), exterior temperature, climate info."""

import math
import time as _time
import pygame
from src.dashboard.themes.theme_base import ThemeBase
from src.dashboard.i18n import t, format_date
from .base_screen import BaseScreen, DashboardData, _font


class ClimateScreen(BaseScreen):
    screen_id = "b1"

    def draw(self, surface: pygame.Surface, theme: ThemeBase,
             data: DashboardData) -> None:
        self.draw_side_gauges(surface, theme, data)
        x, y, w, h = self.content_rect(theme, surface)
        lang = data.lang
        cx = x + w // 2

        # Analog clock
        clock_r = 90
        clock_cx = cx
        clock_cy = y + 20 + clock_r
        self._draw_analog_clock(surface, theme, clock_cx, clock_cy, clock_r)

        # Date below clock (CZW 14 MAR 2026)
        date_y = clock_cy + clock_r + 16
        font_date = _font(theme.font_name, 26)
        date_str = format_date(lang)
        date_surf = font_date.render(date_str, True, theme.text_color)
        date_rect = date_surf.get_rect(center=(cx, date_y))
        surface.blit(date_surf, date_rect)

        # Exterior temperature
        temp_y = date_y + 36
        font_temp_label = _font(theme.font_name, 14)
        font_temp_val = _font(theme.font_name, 32)

        lbl = font_temp_label.render(t("ext_temp", lang) + ":", True, theme.value_label_color)
        surface.blit(lbl, (x + 40, temp_y))

        if data.ext_temp is not None:
            sign = "+" if data.ext_temp >= 0 else ""
            temp_text = f"{sign}{data.ext_temp:.0f}°C"
            temp_color = theme.text_color
            if data.ext_temp <= 3:
                temp_color = theme.warning_color
            if data.ext_temp <= 0:
                temp_color = theme.danger_color
            val_surf = font_temp_val.render(temp_text, True, temp_color)
            surface.blit(val_surf, (x + 40 + lbl.get_width() + 12, temp_y - 8))

            # Snowflake indicator
            if data.ext_temp <= 3:
                snow = _font(theme.font_name, 20).render("*", True, theme.warning_color)
                surface.blit(snow, (x + 40 + lbl.get_width() + 12 + val_surf.get_width() + 6,
                                    temp_y - 2))
        else:
            val_surf = font_temp_val.render("---", True, theme.text_secondary)
            surface.blit(val_surf, (x + 40 + lbl.get_width() + 12, temp_y - 8))

        # Bottom bar: defrost + auto air
        defrost_str = t("active", lang) if data.defrost_active else t("inactive", lang)
        air_str = f"{data.auto_air_temp:.0f}°C"
        self.draw_bottom_bar(surface, theme, [
            (t("defrost", lang), defrost_str),
            (t("auto_air", lang), air_str),
        ])

    def _draw_analog_clock(self, surface, theme, cx, cy, radius):
        """Draw an analog clock face with hour/minute/second hands."""
        # Face
        pygame.draw.circle(surface, theme.clock_face_color, (cx, cy), radius)
        pygame.draw.circle(surface, theme.clock_tick_color, (cx, cy), radius, 2)

        # Hour markers
        font_h = _font(theme.font_name, 14)
        for i in range(12):
            angle = math.radians(90 - i * 30)
            # Tick
            inner_r = radius - 12
            outer_r = radius - 4
            x1 = cx + inner_r * math.cos(angle)
            y1 = cy - inner_r * math.sin(angle)
            x2 = cx + outer_r * math.cos(angle)
            y2 = cy - outer_r * math.sin(angle)
            w = 2 if i % 3 == 0 else 1
            pygame.draw.line(surface, theme.clock_tick_color, (x1, y1), (x2, y2), w)

            # Number for 12, 3, 6, 9
            if i % 3 == 0:
                num = 12 if i == 0 else i
                num_r = radius - 22
                nx = cx + num_r * math.cos(angle)
                ny = cy - num_r * math.sin(angle)
                num_surf = font_h.render(str(num), True, theme.clock_tick_color)
                num_rect = num_surf.get_rect(center=(nx, ny))
                surface.blit(num_surf, num_rect)

        # Current time
        now = _time.localtime()
        h = now.tm_hour % 12
        m = now.tm_min
        s = now.tm_sec

        # Hour hand
        h_angle = math.radians(90 - (h + m / 60) * 30)
        h_len = radius * 0.5
        hx = cx + h_len * math.cos(h_angle)
        hy = cy - h_len * math.sin(h_angle)
        pygame.draw.line(surface, theme.clock_hour_hand_color, (cx, cy), (hx, hy), 3)

        # Minute hand
        m_angle = math.radians(90 - m * 6)
        m_len = radius * 0.7
        mx = cx + m_len * math.cos(m_angle)
        my = cy - m_len * math.sin(m_angle)
        pygame.draw.line(surface, theme.clock_hand_color, (cx, cy), (mx, my), 2)

        # Second hand
        s_angle = math.radians(90 - s * 6)
        s_len = radius * 0.75
        sx = cx + s_len * math.cos(s_angle)
        sy = cy - s_len * math.sin(s_angle)
        pygame.draw.line(surface, theme.accent_color, (cx, cy), (sx, sy), 1)

        # Center dot
        pygame.draw.circle(surface, theme.clock_center_color, (cx, cy), 4)
