"""A3: Weather + Map Screen — Live weather data + OSM tile map.

Displays current weather conditions, 3-day forecast, and an interactive
map (when MapRenderer is available). Falls back to a stylized placeholder
when tiles are not loaded.
"""

import pygame
from src.dashboard.themes.theme_base import ThemeBase
from src.dashboard.i18n import t
from .base_screen import BaseScreen, DashboardData, _font


class WeatherScreen(BaseScreen):
    screen_id = "a3"

    def __init__(self) -> None:
        super().__init__()
        self._map_renderer = None
        self._tile_manager = None

    def set_map_renderer(self, map_renderer, tile_manager):
        """Inject map renderer (called from renderer.py if available)."""
        self._map_renderer = map_renderer
        self._tile_manager = tile_manager

    def draw(self, surface: pygame.Surface, theme: ThemeBase,
             data: DashboardData) -> None:
        if hasattr(theme, "card_bg") and theme.card_bg is not None:
            self._draw_card_based(surface, theme, data)
        else:
            self._draw_legacy(surface, theme, data)

    def _draw_card_based(self, surface, theme, data):
        w, h = surface.get_size()
        x, y, cw, ch = self.card_content_rect(theme, surface)
        pad = 8
        theme_name = getattr(theme, "name", "heritage")

        accent = getattr(theme, "accent_color", (245, 158, 11))
        card_bg = getattr(theme, "card_bg", (20, 20, 20))
        card_border = getattr(theme, "card_border", (50, 50, 50))
        text_color = getattr(theme, "text_primary", (244, 244, 245))
        text_dim = getattr(theme, "text_dim", (120, 120, 120))

        # Left column: Weather info (1/3)
        left_w = cw // 3 - pad
        self._draw_weather_panel(surface, theme, data, x, y, left_w, ch)

        # Right column: Map (2/3)
        map_x = x + left_w + pad * 2
        map_w = cw - left_w - pad * 2
        self._draw_map_panel(surface, theme, data, map_x, y, map_w, ch)

    def _draw_weather_panel(self, surface, theme, data, x, y, w, h):
        accent = getattr(theme, "accent_color", (245, 158, 11))
        card_bg = getattr(theme, "card_bg", (20, 20, 20))
        card_border = getattr(theme, "card_border", (50, 50, 50))
        text_color = getattr(theme, "text_primary", (244, 244, 245))
        text_dim = getattr(theme, "text_dim", (120, 120, 120))

        self.draw_card(surface, x, y, w, h, card_bg, card_border)

        font_city = _font("sans-serif", 14)
        font_condition = _font("sans-serif", 11)
        font_temp_large = _font("sans-serif", 40)
        font_small = _font("sans-serif", 10)
        font_forecast = _font("sans-serif", 11)

        # City name
        city = data.weather_city or "Waiting for GPS..."
        city_surf = font_city.render(city, True, text_color)
        surface.blit(city_surf, (x + 12, y + 12))

        # Condition
        condition = data.weather_condition or "---"
        cond_surf = font_condition.render(condition, True, text_dim)
        surface.blit(cond_surf, (x + 12, y + 32))

        # Cloud icon
        self.draw_icon_cloud(surface, x + w - 30, y + 30, 16, accent)

        # Temperature (large)
        if data.weather_temp is not None:
            temp_text = f"{data.weather_temp:.0f}°"
        else:
            temp_text = "--°"
        temp_surf = font_temp_large.render(temp_text, True, text_color)
        surface.blit(temp_surf, (x + 12, y + 52))

        # Feels like
        if data.weather_feels_like is not None:
            feels = f"Feels like {data.weather_feels_like:.0f}°"
            feels_surf = font_small.render(feels, True, text_dim)
            surface.blit(feels_surf, (x + 12, y + 96))

        # Wind + Humidity row
        wind_text = f"Wind {data.weather_wind_speed:.0f} km/h"
        hum_text = f"Humidity {data.weather_humidity}%"
        wind_surf = font_small.render(wind_text, True, text_dim)
        hum_surf = font_small.render(hum_text, True, text_dim)
        surface.blit(wind_surf, (x + 12, y + 114))
        surface.blit(hum_surf, (x + 12, y + 130))

        # Separator
        sep_y = y + 150
        pygame.draw.line(surface, card_border, (x + 12, sep_y), (x + w - 12, sep_y), 1)

        # 3-day forecast
        forecast = data.weather_forecast or []
        forecast_y = sep_y + 8
        row_h = 40
        for i, fc in enumerate(forecast[:3]):
            fy = forecast_y + i * row_h
            if fy + row_h > y + h - 8:
                break

            day = fc.get("day", "?")
            high = fc.get("high", 0)
            low = fc.get("low", 0)
            cond = fc.get("condition", "")

            day_surf = font_forecast.render(day, True, text_color)
            surface.blit(day_surf, (x + 12, fy + 2))

            temp_range = f"{high}° / {low}°"
            tr_surf = font_forecast.render(temp_range, True, accent)
            surface.blit(tr_surf, (x + 12, fy + 18))

            cond_short = cond[:15]
            cs_surf = font_small.render(cond_short, True, text_dim)
            cs_rect = cs_surf.get_rect(right=x + w - 12, centery=fy + 14)
            surface.blit(cs_surf, cs_rect)

    def _draw_map_panel(self, surface, theme, data, x, y, w, h):
        card_bg = getattr(theme, "card_bg", (20, 20, 20))
        card_border = getattr(theme, "card_border", (50, 50, 50))
        accent = getattr(theme, "accent_color", (245, 158, 11))
        text_color = getattr(theme, "text_primary", (244, 244, 245))
        text_dim = getattr(theme, "text_dim", (120, 120, 120))
        theme_name = getattr(theme, "name", "heritage")

        self.draw_card(surface, x, y, w, h, card_bg, card_border)

        # Try to render live map
        if self._map_renderer and data.gps_fix:
            self._map_renderer.render(surface, (x + 2, y + 2, w - 4, h - 4),
                                      data.gps_lat, data.gps_lon,
                                      data.gps_heading, theme_name)
        else:
            # Stylized map placeholder
            self._draw_map_placeholder(surface, x + 2, y + 2, w - 4, h - 4,
                                       accent, card_bg, theme_name)

        # Location overlay
        if data.weather_city:
            overlay = pygame.Surface((w - 20, 28), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 160))
            surface.blit(overlay, (x + 10, y + h - 38))
            font_loc = _font("sans-serif", 11)
            loc_surf = font_loc.render(data.weather_city, True, text_color)
            surface.blit(loc_surf, (x + 18, y + h - 34))

        # GPS status indicator
        font_tiny = _font("sans-serif", 9)
        if data.gps_fix:
            gps_text = f"GPS: {data.gps_satellites} sats"
            gps_color = (34, 197, 94)
        else:
            gps_text = "GPS: Searching..."
            gps_color = (245, 158, 11)
        gps_surf = font_tiny.render(gps_text, True, gps_color)
        surface.blit(gps_surf, (x + 10, y + 8))

    def _draw_map_placeholder(self, surface, x, y, w, h, accent, bg, theme_name):
        """Draw a stylized map placeholder with grid streets."""
        # Dark background
        map_bg = {
            "heritage": (30, 20, 12),
            "modern": (20, 25, 35),
            "autodelta": (15, 15, 15),
        }.get(theme_name, (20, 20, 20))
        pygame.draw.rect(surface, map_bg, (x, y, w, h))

        # Grid lines (streets)
        grid_color = tuple(min(255, c + 15) for c in map_bg)
        spacing = 30
        for gx in range(x, x + w, spacing):
            pygame.draw.line(surface, grid_color, (gx, y), (gx, y + h), 1)
        for gy in range(y, y + h, spacing):
            pygame.draw.line(surface, grid_color, (x, gy), (x + w, gy), 1)

        # Main roads (thicker, accent-colored)
        road_color = tuple(min(255, c // 2 + 30) for c in accent)
        pygame.draw.line(surface, road_color, (x + w // 3, y), (x + w // 3, y + h), 2)
        pygame.draw.line(surface, road_color, (x, y + h // 2), (x + w, y + h // 2), 2)

        # Curved "river" line
        import math
        river_color = (40, 80, 120) if theme_name == "modern" else (60, 50, 30)
        prev_point = None
        for i in range(0, w, 3):
            rx = x + i
            ry = y + h * 3 // 4 + int(20 * math.sin(i * 0.03))
            if prev_point:
                pygame.draw.line(surface, river_color, prev_point, (rx, ry), 2)
            prev_point = (rx, ry)

        # Location dot at center
        cx, cy = x + w // 2, y + h // 2
        glow = pygame.Surface((30, 30), pygame.SRCALPHA)
        pygame.draw.circle(glow, (*accent, 40), (15, 15), 12)
        surface.blit(glow, (cx - 15, cy - 15))
        pygame.draw.circle(surface, accent, (cx, cy), 5)
        pygame.draw.circle(surface, (255, 255, 255), (cx, cy), 3)

    def _draw_legacy(self, surface, theme, data):
        """Legacy weather display for classic themes."""
        self.draw_side_gauges(surface, theme, data)
        x, y, w, h = self.content_rect(theme, surface)

        font_header = _font(theme.font_name, 20)
        font_value = _font(theme.font_name, 32)
        font_label = _font(theme.font_name, 14)

        # Header
        header = font_header.render("Weather", True, theme.value_label_color)
        surface.blit(header, (x + 20, y + 10))

        cy = y + 50
        if data.weather_city:
            city_surf = font_label.render(data.weather_city, True, theme.text_secondary)
            surface.blit(city_surf, (x + 20, cy))
            cy += 25

        if data.weather_temp is not None:
            temp_surf = font_value.render(f"{data.weather_temp:.0f}°C", True,
                                          theme.value_large_color)
            surface.blit(temp_surf, (x + 20, cy))
            cy += 45

        if data.weather_condition:
            cond_surf = font_label.render(data.weather_condition, True,
                                          theme.text_secondary)
            surface.blit(cond_surf, (x + 20, cy))

        self.draw_bottom_bar(surface, theme, [
            ("Wind", f"{data.weather_wind_speed:.0f} km/h"),
            ("Humidity", f"{data.weather_humidity}%"),
        ])
