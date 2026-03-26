"""A4: Service Screen — Vehicle diagnostics + TPMS + car sketch.

Card-based layout for Heritage/Modern/Autodelta themes.
Falls back to legacy list layout for classic themes.
Long press = confirm service reset.
"""

import pygame
from src.dashboard.themes.theme_base import ThemeBase
from src.dashboard.i18n import t
from .base_screen import BaseScreen, DashboardData, _font
from .assets import draw_car_silhouette


class ServiceScreen(BaseScreen):
    screen_id = "a4"

    def draw(self, surface: pygame.Surface, theme: ThemeBase,
             data: DashboardData) -> None:
        if hasattr(theme, "card_bg") and theme.card_bg is not None:
            self._draw_card_based(surface, theme, data)
        else:
            self._draw_legacy(surface, theme, data)

    def on_long_press(self, data: DashboardData) -> str | None:
        return "service.confirm"

    def _draw_card_based(self, surface, theme, data):
        x, y, cw, ch = self.card_content_rect(theme, surface)
        pad = 8

        accent = getattr(theme, "accent_color", (245, 158, 11))
        card_bg = getattr(theme, "card_bg", (20, 20, 20))
        card_border = getattr(theme, "card_border", (50, 50, 50))
        text_color = getattr(theme, "text_primary", (244, 244, 245))
        text_dim = getattr(theme, "text_dim", (120, 120, 120))
        ok_color = getattr(theme, "ok_color", (34, 197, 94))
        warning_color = getattr(theme, "warning_color", (245, 158, 11))
        danger_color = getattr(theme, "danger_color", (220, 38, 38))

        # Left column: Diagnostic items (55%)
        left_w = int(cw * 0.55) - pad
        self._draw_diagnostics(surface, theme, data, x, y, left_w, ch)

        # Right column: Car sketch + status (45%)
        right_x = x + left_w + pad * 2
        right_w = cw - left_w - pad * 2
        self._draw_car_status(surface, theme, data, right_x, y, right_w, ch)

    def _draw_diagnostics(self, surface, theme, data, x, y, w, h):
        accent = getattr(theme, "accent_color", (245, 158, 11))
        card_bg = getattr(theme, "card_bg", (20, 20, 20))
        card_border = getattr(theme, "card_border", (50, 50, 50))
        text_color = getattr(theme, "text_primary", (244, 244, 245))
        text_dim = getattr(theme, "text_dim", (120, 120, 120))
        ok_color = getattr(theme, "ok_color", (34, 197, 94))
        warning_color = getattr(theme, "warning_color", (245, 158, 11))
        danger_color = getattr(theme, "danger_color", (220, 38, 38))

        font_header = _font("sans-serif", 13)
        font_label = _font("sans-serif", 11)
        font_value = _font("sans-serif", 13)
        font_status = _font("sans-serif", 10)

        # Header
        header = font_header.render("SYSTEM STATUS", True, text_color)
        surface.blit(header, (x, y))

        # Last checked badge
        badge_surf = font_status.render("Last checked: 2 min ago", True, text_dim)
        badge_rect = badge_surf.get_rect(right=x + w, centery=y + 8)
        surface.blit(badge_surf, badge_rect)

        # Diagnostic rows
        diagnostics = [
            ("Engine Mechanics", self._engine_status(data), self._engine_color(data, ok_color, warning_color, danger_color)),
            ("Engine Temp", f"{data.coolant_temp:.0f}°C", ok_color if data.coolant_temp < 105 else danger_color),
            ("Oil Pressure", f"{data.oil_level_pct:.0f}%" if data.oil_level_pct >= 0 else "N/A",
             ok_color if data.oil_level_pct > 20 else warning_color),
            ("Battery", f"{data.battery_voltage:.1f}V",
             ok_color if data.battery_voltage > 12.0 else danger_color),
            ("Service Due", f"{data.service_km} km",
             ok_color if data.service_km > 2000 else (warning_color if data.service_km > 0 else danger_color)),
        ]

        # Add TPMS if available
        if data.tpms_available:
            avg_pressure = sum(data.tpms_pressures) / 4 if data.tpms_pressures else 0
            tpms_status = f"{avg_pressure:.1f} BAR avg"
            tpms_color = ok_color if 1.8 < avg_pressure < 3.0 else warning_color
            diagnostics.append(("Tire Pressure", tpms_status, tpms_color))

        row_h = max(42, (h - 24) // len(diagnostics))
        for i, (label, value, color) in enumerate(diagnostics):
            ry = y + 24 + i * row_h
            if ry + row_h > y + h:
                break

            self.draw_card(surface, x, ry, w, row_h - 4, card_bg, card_border)

            # Status indicator dot
            pygame.draw.circle(surface, color, (x + 14, ry + row_h // 2 - 2), 4)

            # Label
            lbl_surf = font_label.render(label, True, text_color)
            surface.blit(lbl_surf, (x + 26, ry + 6))

            # Value
            val_surf = font_value.render(value, True, color)
            val_rect = val_surf.get_rect(right=x + w - 12, centery=ry + row_h // 2 - 2)
            surface.blit(val_surf, val_rect)

    def _draw_car_status(self, surface, theme, data, x, y, w, h):
        accent = getattr(theme, "accent_color", (245, 158, 11))
        card_bg = getattr(theme, "card_bg", (20, 20, 20))
        card_border = getattr(theme, "card_border", (50, 50, 50))
        text_color = getattr(theme, "text_primary", (244, 244, 245))
        text_dim = getattr(theme, "text_dim", (120, 120, 120))
        theme_name = getattr(theme, "name", "heritage")

        self.draw_card(surface, x, y, w, h, card_bg, card_border)

        # Car silhouette — uses shared 22-point profile from assets.py (1:1 with mockups)
        cx = x + w // 2
        cy = y + h // 2 - 30
        car_w = int(w * 0.85)
        car_h = int(car_w * 0.46)  # Maintain aspect ratio

        if theme_name == "autodelta":
            draw_car_silhouette(surface, cx, cy, car_w, car_h,
                                accent, "inverted")
        elif theme_name == "modern":
            draw_car_silhouette(surface, cx, cy, car_w, car_h,
                                (*accent[:3], 60) if len(accent) >= 3 else accent,
                                "filled")
        else:
            draw_car_silhouette(surface, cx, cy, car_w, car_h,
                                accent, "outline")

        # Car model label
        font_model = _font("sans-serif", 11)
        model_surf = font_model.render("Alfa Romeo 156", True, text_dim)
        model_rect = model_surf.get_rect(centerx=cx, top=cy + car_h // 2 + 12)
        surface.blit(model_surf, model_rect)

        # TPMS display (if available)
        if data.tpms_available:
            font_tpms = _font("sans-serif", 10)
            positions = [
                ("FL", -35, -10, 0), ("FR", 35, -10, 1),
                ("RL", -35, 20, 2), ("RR", 35, 20, 3),
            ]
            ok_color = getattr(theme, "ok_color", (34, 197, 94))
            warning_color = getattr(theme, "warning_color", (245, 158, 11))

            for label, dx, dy, idx in positions:
                pressure = data.tpms_pressures[idx] if idx < len(data.tpms_pressures) else 0
                color = ok_color if 1.8 < pressure < 3.0 else warning_color
                text = f"{pressure:.1f}"
                p_surf = font_tpms.render(text, True, color)
                p_rect = p_surf.get_rect(centerx=cx + dx, centery=cy + dy + 55)
                surface.blit(p_surf, p_rect)

        # Service countdown at bottom
        font_service = _font("sans-serif", 12)
        service_text = f"Next Service: {data.service_km} km"
        service_color = accent if data.service_km > 2000 else (220, 38, 38)
        sv_surf = font_service.render(service_text, True, service_color)
        sv_rect = sv_surf.get_rect(centerx=cx, bottom=y + h - 10)
        surface.blit(sv_surf, sv_rect)

    @staticmethod
    def _engine_status(data):
        if data.coolant_temp > 110:
            return "OVERHEATING"
        if data.coolant_temp < 60:
            return "WARMING UP"
        return "OK"

    @staticmethod
    def _engine_color(data, ok, warn, danger):
        if data.coolant_temp > 110:
            return danger
        if data.coolant_temp < 60:
            return warn
        return ok

    # ── Legacy layout ──

    def _draw_legacy(self, surface, theme, data):
        self.draw_side_gauges(surface, theme, data)
        x, y, w, h = self.content_rect(theme, surface)
        lang = data.lang

        font_label = _font(theme.font_name, 14)
        font_value = _font(theme.font_name, 22)
        font_sm = _font(theme.font_name, 12)
        font_bar_label = _font(theme.font_name, 11)

        cy = y + 15
        lx = x + 30
        vx = x + w // 2 + 20

        # Engine Oil
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

        # TPMS
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

        # Service interval
        lbl3 = font_label.render(t("service_interval", lang) + ":", True, theme.value_label_color)
        surface.blit(lbl3, (lx, cy))
        km_text = f"{data.service_km} {t('km', lang)}"
        km_color = theme.service_ok if data.service_km > 1000 else (
            theme.service_warn if data.service_km > 0 else theme.service_danger)
        val3 = font_value.render(km_text, True, km_color)
        surface.blit(val3, (vx, cy - 4))
        cy += 50

        # Oil level bar
        bar_y = cy
        bar_x = lx
        bar_w = w - 60
        bar_h = 18

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
            for i in range(0, bar_w, 12):
                x1 = bar_x + i
                x2 = bar_x + i + bar_h
                pygame.draw.line(surface, theme.service_bar_bg,
                                 (x1, bar_y + bar_h), (min(x2, bar_x + bar_w), bar_y), 1)

        bar_y += bar_h + 14

        # Oil wear bar
        ow_lbl = font_bar_label.render(t("oil_wear", lang), True, theme.text_secondary)
        surface.blit(ow_lbl, (bar_x, bar_y - 2))
        bar_y += 16

        pygame.draw.rect(surface, theme.service_bar_bg,
                         (bar_x, bar_y, bar_w, bar_h), border_radius=3)
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

        if data.tpms_available:
            bar_y += bar_h + 20
            self._draw_tpms_grid(surface, theme, bar_x, bar_y, data)

        self.draw_bottom_bar(surface, theme, [
            (t("long_push_confirm", lang), ""),
        ])

    def _draw_tpms_grid(self, surface, theme, x, y, data):
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
