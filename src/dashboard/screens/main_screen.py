"""A1: Main Screen — Notification hub + engine/fuel cards + media player.

Card-based layout for Heritage/Modern/Autodelta themes.
Falls back to legacy tachometer view for classic themes.
"""

import math
import pygame
from src.dashboard.themes.theme_base import ThemeBase
from src.dashboard.i18n import t
from .base_screen import BaseScreen, DashboardData, _font, _lerp_color


class MainScreen(BaseScreen):
    screen_id = "a1"

    def draw(self, surface: pygame.Surface, theme: ThemeBase,
             data: DashboardData) -> None:
        # Detect card-based theme
        if hasattr(theme, "card_bg") and theme.card_bg is not None:
            self._draw_card_based(surface, theme, data)
        else:
            self._draw_legacy(surface, theme, data)

    # ── Card-based layout (Heritage/Modern/Autodelta) ──────────────

    def _draw_card_based(self, surface: pygame.Surface, theme: ThemeBase,
                         data: DashboardData) -> None:
        w, h = surface.get_size()
        x, y, cw, ch = self.card_content_rect(theme, surface)
        pad = 8
        theme_name = getattr(theme, "name", "heritage")

        # --- Left column: Engine Temp + Fuel ---
        left_w = cw // 4 - pad
        card_h = (ch - pad) // 2

        # Engine temp card
        self._draw_engine_card(surface, theme, data, x, y, left_w, card_h)

        # Fuel card
        self._draw_fuel_card(surface, theme, data, x, y + card_h + pad, left_w, card_h)

        # --- Center: Notifications ---
        center_x = x + left_w + pad * 2
        center_w = cw // 2 - pad * 2
        self._draw_notifications(surface, theme, data, center_x, y, center_w, ch)

        # --- Right column: Now Playing + Status ---
        right_x = center_x + center_w + pad * 2
        right_w = cw - (left_w + pad * 2 + center_w + pad * 2)

        # Now playing card
        self._draw_media_card(surface, theme, data, right_x, y, right_w, card_h)

        # Stats card
        self._draw_stats_card(surface, theme, data, right_x, y + card_h + pad,
                              right_w, card_h)

    def _draw_engine_card(self, surface, theme, data, x, y, w, h):
        accent = getattr(theme, "accent_color", (245, 158, 11))
        card_bg = getattr(theme, "card_bg", (20, 20, 20))
        card_border = getattr(theme, "card_border", (50, 50, 50))
        text_color = getattr(theme, "text_primary", (244, 244, 245))
        text_dim = getattr(theme, "text_dim", (120, 120, 120))

        self.draw_card(surface, x, y, w, h, card_bg, card_border)

        font_label = _font("sans-serif", 11)
        font_value = _font("sans-serif", 28)
        font_status = _font("sans-serif", 10)

        # Icon
        self.draw_icon_thermometer(surface, x + 20, y + 20, 12, accent)

        # Label
        lbl = font_label.render("ENGINE TEMP", True, text_dim)
        surface.blit(lbl, (x + 36, y + 14))

        # Value
        temp_val = f"{data.coolant_temp:.0f}°"
        val_surf = font_value.render(temp_val, True, text_color)
        val_rect = val_surf.get_rect(center=(x + w // 2, y + h // 2 + 5))
        surface.blit(val_surf, val_rect)

        # Progress bar
        bar_y = y + h - 24
        frac = max(0, min(1, (data.coolant_temp - 40) / 90))
        bar_color = accent if data.coolant_temp < 105 else (220, 38, 38)
        self.draw_progress_bar(surface, x + 12, bar_y, w - 24, 6, frac,
                               bar_color, (40, 40, 40))

        # Status text
        status = "OPTIMAL" if 80 <= data.coolant_temp <= 100 else (
            "WARMING" if data.coolant_temp < 80 else "HOT")
        status_color = (34, 197, 94) if status == "OPTIMAL" else (
            accent if status == "WARMING" else (220, 38, 38))
        st_surf = font_status.render(status, True, status_color)
        surface.blit(st_surf, (x + 12, bar_y - 14))

    def _draw_fuel_card(self, surface, theme, data, x, y, w, h):
        accent = getattr(theme, "accent_color", (245, 158, 11))
        card_bg = getattr(theme, "card_bg", (20, 20, 20))
        card_border = getattr(theme, "card_border", (50, 50, 50))
        text_color = getattr(theme, "text_primary", (244, 244, 245))
        text_dim = getattr(theme, "text_dim", (120, 120, 120))

        self.draw_card(surface, x, y, w, h, card_bg, card_border)

        font_label = _font("sans-serif", 11)
        font_value = _font("sans-serif", 28)
        font_small = _font("sans-serif", 10)

        # Icon
        self.draw_icon_fuel(surface, x + 20, y + 20, 12, accent)

        # Label
        lbl = font_label.render("FUEL", True, text_dim)
        surface.blit(lbl, (x + 36, y + 14))

        # Value
        val_surf = font_value.render(f"{data.fuel_level:.0f}%", True, text_color)
        val_rect = val_surf.get_rect(center=(x + w // 2, y + h // 2 + 5))
        surface.blit(val_surf, val_rect)

        # Progress bar
        bar_y = y + h - 24
        frac = max(0, min(1, data.fuel_level / 100))
        bar_color = accent if data.fuel_level > 15 else (220, 38, 38)
        self.draw_progress_bar(surface, x + 12, bar_y, w - 24, 6, frac,
                               bar_color, (40, 40, 40))

        # Range estimate
        range_text = f"EST RANGE: {data.estimated_range:.0f} KM"
        range_surf = font_small.render(range_text, True, text_dim)
        surface.blit(range_surf, (x + 12, bar_y - 14))

    def _draw_notifications(self, surface, theme, data, x, y, w, h):
        card_bg = getattr(theme, "card_bg", (20, 20, 20))
        card_border = getattr(theme, "card_border", (50, 50, 50))
        accent = getattr(theme, "accent_color", (245, 158, 11))
        text_color = getattr(theme, "text_primary", (244, 244, 245))
        text_dim = getattr(theme, "text_dim", (120, 120, 120))
        ok_color = getattr(theme, "ok_color", (34, 197, 94))
        warning_color = getattr(theme, "warning_color", (245, 158, 11))
        danger_color = getattr(theme, "danger_color", (220, 38, 38))

        self.draw_card(surface, x, y, w, h, card_bg, card_border)

        # Top accent line
        pygame.draw.rect(surface, accent, (x + 1, y + 1, w - 2, 3))

        font_header = _font("sans-serif", 12)
        font_item = _font("sans-serif", 11)
        font_sub = _font("sans-serif", 9)

        header_surf = font_header.render("NOTIFICATIONS", True, text_color)
        surface.blit(header_surf, (x + 12, y + 12))

        # Notification items (hardcoded for now)
        notifications = [
            {"title": "Systems Nominal", "subtitle": "All sensors reporting normal",
             "color": ok_color, "icon": "check"},
            {"title": "Next Service", "subtitle": f"{data.service_km} km remaining",
             "color": warning_color, "icon": "wrench"},
        ]

        # Add weather notification if available
        if data.weather_city:
            temp_str = f"{data.weather_temp:.0f}°" if data.weather_temp else ""
            notifications.append({
                "title": f"{data.weather_city} — {data.weather_condition}",
                "subtitle": f"{temp_str} | Wind {data.weather_wind_speed:.0f} km/h",
                "color": text_dim, "icon": "cloud",
            })

        item_h = 50
        for i, notif in enumerate(notifications[:4]):
            ny = y + 32 + i * item_h
            if ny + item_h > y + h - 8:
                break

            # Left color indicator
            pygame.draw.rect(surface, notif["color"], (x + 8, ny, 3, item_h - 8))

            # Icon
            icon_fn = {
                "check": self.draw_icon_check,
                "wrench": self.draw_icon_warning,
                "cloud": self.draw_icon_cloud,
            }.get(notif["icon"], self.draw_icon_check)
            icon_fn(surface, x + 24, ny + item_h // 2 - 4, 8, notif["color"])

            # Text
            title_surf = font_item.render(notif["title"], True, text_color)
            surface.blit(title_surf, (x + 40, ny + 4))
            sub_surf = font_sub.render(notif["subtitle"], True, text_dim)
            surface.blit(sub_surf, (x + 40, ny + 22))

    def _draw_media_card(self, surface, theme, data, x, y, w, h):
        card_bg = getattr(theme, "card_bg", (20, 20, 20))
        card_border = getattr(theme, "card_border", (50, 50, 50))
        accent = getattr(theme, "accent_color", (245, 158, 11))
        text_color = getattr(theme, "text_primary", (244, 244, 245))
        text_dim = getattr(theme, "text_dim", (120, 120, 120))

        self.draw_card(surface, x, y, w, h, card_bg, card_border)

        font_label = _font("sans-serif", 10)
        font_title = _font("sans-serif", 13)
        font_artist = _font("sans-serif", 11)

        # Music icon
        self.draw_icon_music(surface, x + 16, y + 16, 10, accent)

        lbl = font_label.render("NOW PLAYING", True, text_dim)
        surface.blit(lbl, (x + 32, y + 10))

        if data.bt_media_title:
            # Truncate long titles
            title = data.bt_media_title[:20]
            artist = data.bt_media_artist[:20]

            title_surf = font_title.render(title, True, text_color)
            surface.blit(title_surf, (x + 12, y + 32))

            artist_surf = font_artist.render(artist, True, text_dim)
            surface.blit(artist_surf, (x + 12, y + 50))

            # Playback progress bar
            if data.bt_media_duration > 0:
                frac = min(1.0, data.bt_media_position / data.bt_media_duration)
                bar_y = y + h - 20
                self.draw_progress_bar(surface, x + 12, bar_y, w - 24, 4, frac,
                                       accent, (40, 40, 40))

            # Play/pause indicator
            status_text = "▶" if data.bt_media_playing else "⏸"
            st_surf = font_label.render(status_text, True, accent)
            surface.blit(st_surf, (x + w - 24, y + 32))
        else:
            no_media = font_artist.render("No media", True, text_dim)
            surface.blit(no_media, (x + 12, y + 40))

    def _draw_stats_card(self, surface, theme, data, x, y, w, h):
        card_bg = getattr(theme, "card_bg", (20, 20, 20))
        card_border = getattr(theme, "card_border", (50, 50, 50))
        text_color = getattr(theme, "text_primary", (244, 244, 245))
        text_dim = getattr(theme, "text_dim", (120, 120, 120))

        self.draw_card(surface, x, y, w, h, card_bg, card_border)

        font_label = _font("sans-serif", 9)
        font_value = _font("sans-serif", 16)

        stats = [
            ("AVG SPEED", f"{data.avg_speed:.0f}", "km/h"),
            ("DRIVE TIME", data.trip_time_str[:5], ""),
            ("BATTERY", f"{data.battery_voltage:.1f}V", ""),
        ]

        row_h = (h - 16) // len(stats)
        for i, (label, value, unit) in enumerate(stats):
            sy = y + 8 + i * row_h
            lbl_surf = font_label.render(label, True, text_dim)
            surface.blit(lbl_surf, (x + 12, sy))
            val_text = f"{value} {unit}".strip()
            val_surf = font_value.render(val_text, True, text_color)
            surface.blit(val_surf, (x + 12, sy + 14))

    # ── Legacy tachometer layout (classic themes) ──────────────

    def _draw_legacy(self, surface: pygame.Surface, theme: ThemeBase,
                     data: DashboardData) -> None:
        self.draw_side_gauges(surface, theme, data)
        cx_area, cy_area, cw, ch = self.content_rect(theme, surface)

        tacho_cx = cx_area + cw // 2
        tacho_cy = cy_area + ch // 2 - 20
        tacho_r = min(cw, ch) // 2 - 30

        self._draw_tachometer(surface, theme, tacho_cx, tacho_cy, tacho_r, data)

        speed_val = data.speed
        if data.speed_unit == "mph":
            speed_val = data.speed * 0.621371
        font_speed = _font(theme.font_name, theme.value_large_size)
        speed_text = f"{speed_val:.0f}"
        speed_surf = font_speed.render(speed_text, True, theme.value_large_color)
        speed_rect = speed_surf.get_rect(center=(tacho_cx, tacho_cy + 15))
        surface.blit(speed_surf, speed_rect)

        font_unit = _font(theme.font_name, 16)
        unit_surf = font_unit.render(data.speed_unit, True, theme.text_secondary)
        unit_rect = unit_surf.get_rect(center=(tacho_cx, speed_rect.bottom + 6))
        surface.blit(unit_surf, unit_rect)

        inst_cons = f"{data.instant_consumption:.1f} {t('l_100km', data.lang)}"
        rpm_text = f"{data.rpm:.0f}"
        self.draw_bottom_bar(surface, theme, [
            (t("instant_cons", data.lang), inst_cons),
            (t("rpm", data.lang), rpm_text),
        ])

    def _draw_tachometer(self, surface, theme, cx, cy, radius, data):
        start_angle = 135.0
        sweep_angle = 270.0
        max_rpm = 5500.0 if data.rpm < 6000 else 7000.0
        rpm = max(0, min(max_rpm, data.rpm))
        frac = rpm / max_rpm

        self._draw_gradient_arc(surface, theme.gauge_bg, theme.gauge_bg,
                                cx, cy, radius, 12, start_angle, sweep_angle)

        rz_frac = 4500 / max_rpm
        rz_start = start_angle - rz_frac * sweep_angle
        rz_sweep = (1.0 - rz_frac) * sweep_angle
        self._draw_gradient_arc(surface, (80, 20, 15), theme.gauge_redzone,
                                cx, cy, radius, 12, rz_start, rz_sweep)

        if frac > 0.01:
            val_sweep = frac * sweep_angle
            glow_surf = pygame.Surface((surface.get_width(), surface.get_height()), pygame.SRCALPHA)
            self._draw_gradient_arc(glow_surf,
                                    (*theme.arc_glow_color, theme.arc_glow_alpha),
                                    (*theme.arc_glow_color, theme.arc_glow_alpha + 15),
                                    cx, cy, radius + 3, 18, start_angle, val_sweep)
            surface.blit(glow_surf, (0, 0))
            end_color = theme.danger_color if rpm >= 4500 else theme.arc_gradient_end
            self._draw_gradient_arc(surface, theme.arc_gradient_start, end_color,
                                    cx, cy, radius, 12, start_angle, val_sweep)

        tick_values = [0, 1, 2, 3, 4, 5]
        if max_rpm > 6000:
            tick_values.append(6)

        font_num = _font(theme.font_name, theme.tacho_number_size)
        for val_k in tick_values:
            val = val_k * 1000
            tick_frac = val / max_rpm
            angle_deg = start_angle - tick_frac * sweep_angle
            angle_rad = math.radians(angle_deg)

            inner_r = radius - 14
            outer_r = radius + 2
            x1 = cx + inner_r * math.cos(angle_rad)
            y1 = cy - inner_r * math.sin(angle_rad)
            x2 = cx + outer_r * math.cos(angle_rad)
            y2 = cy - outer_r * math.sin(angle_rad)
            pygame.draw.line(surface, theme.gauge_tick, (x1, y1), (x2, y2), 2)

            num_r = radius + 14
            nx = cx + num_r * math.cos(angle_rad)
            ny = cy - num_r * math.sin(angle_rad)
            num_surf = font_num.render(str(val_k), True, theme.tacho_number_color)
            num_rect = num_surf.get_rect(center=(nx, ny))
            surface.blit(num_surf, num_rect)

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

        needle_angle_deg = start_angle - frac * sweep_angle
        needle_angle_rad = math.radians(needle_angle_deg)
        needle_len = radius - 18
        nx = cx + needle_len * math.cos(needle_angle_rad)
        ny = cy - needle_len * math.sin(needle_angle_rad)
        pygame.draw.line(surface, theme.gauge_needle, (cx, cy), (nx, ny), 3)
        pygame.draw.circle(surface, theme.gauge_needle, (cx, cy), 5)

        font_lbl = _font(theme.font_name, 10)
        lbl_surf = font_lbl.render(t("rpm_x1000", data.lang), True, theme.text_secondary)
        lbl_rect = lbl_surf.get_rect(center=(cx, cy - radius + 30))
        surface.blit(lbl_surf, lbl_rect)

    def _draw_gradient_arc(self, surface, color_start, color_end,
                           cx, cy, radius, width, start_deg, sweep_deg,
                           segments=48):
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

            points = [
                (cx + radius * math.cos(a1), cy - radius * math.sin(a1)),
                (cx + radius * math.cos(a2), cy - radius * math.sin(a2)),
                (cx + (radius - width) * math.cos(a2),
                 cy - (radius - width) * math.sin(a2)),
                (cx + (radius - width) * math.cos(a1),
                 cy - (radius - width) * math.sin(a1)),
            ]
            pygame.draw.polygon(surface, c, points)
