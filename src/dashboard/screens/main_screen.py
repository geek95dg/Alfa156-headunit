"""A1: GŁÓWNY — Main dashboard screen with tachometer, speed, gauges."""

import math
import pygame
from src.dashboard.themes.theme_base import ThemeBase
from src.dashboard.i18n import t
from .base_screen import BaseScreen, DashboardData, _font, _lerp_color


class MainScreen(BaseScreen):
    screen_id = "a1"

    def draw(self, surface: pygame.Surface, theme: ThemeBase,
             data: DashboardData) -> None:
        self.draw_side_gauges(surface, theme, data)
        cx_area, cy_area, cw, ch = self.content_rect(theme, surface)

        # Tachometer center
        tacho_cx = cx_area + cw // 2
        tacho_cy = cy_area + ch // 2 - 20
        tacho_r = min(cw, ch) // 2 - 30

        self._draw_tachometer(surface, theme, tacho_cx, tacho_cy, tacho_r, data)

        # Speed (large centered)
        speed_val = data.speed
        if data.speed_unit == "mph":
            speed_val = data.speed * 0.621371
        font_speed = _font(theme.font_name, theme.value_large_size)
        speed_text = f"{speed_val:.0f}"
        speed_surf = font_speed.render(speed_text, True, theme.value_large_color)
        speed_rect = speed_surf.get_rect(center=(tacho_cx, tacho_cy + 15))
        surface.blit(speed_surf, speed_rect)

        # km/h label
        font_unit = _font(theme.font_name, 16)
        unit_surf = font_unit.render(data.speed_unit, True, theme.text_secondary)
        unit_rect = unit_surf.get_rect(center=(tacho_cx, speed_rect.bottom + 6))
        surface.blit(unit_surf, unit_rect)

        # Bottom bar
        inst_cons = f"{data.instant_consumption:.1f} {t('l_100km', data.lang)}"
        rpm_text = f"{data.rpm:.0f}"
        self.draw_bottom_bar(surface, theme, [
            (t("instant_cons", data.lang), inst_cons),
            (t("rpm", data.lang), rpm_text),
        ])

    def _draw_tachometer(self, surface: pygame.Surface, theme: ThemeBase,
                         cx: int, cy: int, radius: int,
                         data: DashboardData) -> None:
        """Draw a semicircular tachometer with number scale."""
        start_angle = 135.0
        sweep_angle = 270.0
        max_rpm = 5500.0 if data.rpm < 6000 else 7000.0
        rpm = max(0, min(max_rpm, data.rpm))
        frac = rpm / max_rpm

        # Background arc
        self._draw_gradient_arc(surface, theme.gauge_bg, theme.gauge_bg,
                                cx, cy, radius, 12, start_angle, sweep_angle)

        # Redzone (above 4500)
        rz_frac = 4500 / max_rpm
        rz_start = start_angle - rz_frac * sweep_angle
        rz_sweep = (1.0 - rz_frac) * sweep_angle
        self._draw_gradient_arc(surface, (80, 20, 15), theme.gauge_redzone,
                                cx, cy, radius, 12, rz_start, rz_sweep)

        # Value arc (gradient)
        if frac > 0.01:
            val_sweep = frac * sweep_angle
            glow_r = radius + 3
            # Glow
            glow_surf = pygame.Surface((surface.get_width(), surface.get_height()), pygame.SRCALPHA)
            self._draw_gradient_arc(glow_surf,
                                    (*theme.arc_glow_color, theme.arc_glow_alpha),
                                    (*theme.arc_glow_color, theme.arc_glow_alpha + 15),
                                    cx, cy, glow_r, 18, start_angle, val_sweep)
            surface.blit(glow_surf, (0, 0))

            # Main arc
            end_color = theme.danger_color if rpm >= 4500 else theme.arc_gradient_end
            self._draw_gradient_arc(surface, theme.arc_gradient_start, end_color,
                                    cx, cy, radius, 12, start_angle, val_sweep)

        # Tick marks and numbers
        tick_values = [0, 1, 2, 3, 4, 5]
        if max_rpm > 6000:
            tick_values.append(6)
        tick_values_thousands = tick_values

        font_num = _font(theme.font_name, theme.tacho_number_size)
        for val_k in tick_values_thousands:
            val = val_k * 1000
            tick_frac = val / max_rpm
            angle_deg = start_angle - tick_frac * sweep_angle
            angle_rad = math.radians(angle_deg)

            # Tick line
            inner_r = radius - 14
            outer_r = radius + 2
            x1 = cx + inner_r * math.cos(angle_rad)
            y1 = cy - inner_r * math.sin(angle_rad)
            x2 = cx + outer_r * math.cos(angle_rad)
            y2 = cy - outer_r * math.sin(angle_rad)
            pygame.draw.line(surface, theme.gauge_tick, (x1, y1), (x2, y2), 2)

            # Number label
            num_r = radius + 14
            nx = cx + num_r * math.cos(angle_rad)
            ny = cy - num_r * math.sin(angle_rad)
            num_surf = font_num.render(str(val_k), True, theme.tacho_number_color)
            num_rect = num_surf.get_rect(center=(nx, ny))
            surface.blit(num_surf, num_rect)

        # Minor ticks
        for i in range(int(max_rpm / 500) + 1):
            val = i * 500
            if val % 1000 == 0:
                continue
            tick_frac = val / max_rpm
            angle_deg = start_angle - tick_frac * sweep_angle
            angle_rad = math.radians(angle_deg)
            inner_r = radius - 8
            outer_r = radius + 1
            x1 = cx + inner_r * math.cos(angle_rad)
            y1 = cy - inner_r * math.sin(angle_rad)
            x2 = cx + outer_r * math.cos(angle_rad)
            y2 = cy - outer_r * math.sin(angle_rad)
            half_tick = (theme.gauge_tick[0] // 2, theme.gauge_tick[1] // 2,
                         theme.gauge_tick[2] // 2)
            pygame.draw.line(surface, half_tick, (x1, y1), (x2, y2), 1)

        # Needle
        needle_angle_deg = start_angle - frac * sweep_angle
        needle_angle_rad = math.radians(needle_angle_deg)
        needle_len = radius - 18
        nx = cx + needle_len * math.cos(needle_angle_rad)
        ny = cy - needle_len * math.sin(needle_angle_rad)
        pygame.draw.line(surface, theme.gauge_needle, (cx, cy), (nx, ny), 3)
        pygame.draw.circle(surface, theme.gauge_needle, (cx, cy), 5)

        # RPM x1000 label
        font_lbl = _font(theme.font_name, 10)
        lbl_surf = font_lbl.render(t("rpm_x1000", data.lang), True, theme.text_secondary)
        lbl_rect = lbl_surf.get_rect(center=(cx, cy - radius + 30))
        surface.blit(lbl_surf, lbl_rect)

    def _draw_gradient_arc(self, surface, color_start, color_end,
                           cx, cy, radius, width, start_deg, sweep_deg,
                           segments=48):
        """Draw an arc with gradient color from start to end."""
        if sweep_deg <= 0 or radius <= 0:
            return
        step = sweep_deg / segments
        for i in range(segments):
            frac = i / segments
            if len(color_start) == 4:
                c = (
                    int(color_start[0] + (color_end[0] - color_start[0]) * frac),
                    int(color_start[1] + (color_end[1] - color_start[1]) * frac),
                    int(color_start[2] + (color_end[2] - color_start[2]) * frac),
                    int(color_start[3] + (color_end[3] - color_start[3]) * frac),
                )
            else:
                c = _lerp_color(color_start, color_end, frac)

            a1 = math.radians(start_deg - i * step)
            a2 = math.radians(start_deg - (i + 1) * step)

            points = []
            points.append((cx + radius * math.cos(a1), cy - radius * math.sin(a1)))
            points.append((cx + radius * math.cos(a2), cy - radius * math.sin(a2)))
            points.append((cx + (radius - width) * math.cos(a2),
                           cy - (radius - width) * math.sin(a2)))
            points.append((cx + (radius - width) * math.cos(a1),
                           cy - (radius - width) * math.sin(a1)))
            pygame.draw.polygon(surface, c, points)
