"""Initialization Screen — Full-screen splash on boot, no chrome.

Matches mockup renders 1:1:
- Heritage: Burl-textured bg, vignette, amber glow, car outline, "ALFA ROMEO"
- Modern: Charcoal bg, blue glow, car filled white, "CENTRO STILE ALFA ROMEO"
- Autodelta: Black bg, scanlines, crosshairs, car inverted orange, boot text
"""

import math
import time
import pygame
from src.dashboard.themes.theme_base import ThemeBase
from .base_screen import BaseScreen, DashboardData, _font
from .assets import draw_car_silhouette, draw_corner_accents


class InitializationScreen(BaseScreen):
    screen_id = "init"

    def __init__(self) -> None:
        super().__init__()
        self._start_time = time.time()
        self._progress = 0.0

    @property
    def elapsed(self) -> float:
        return time.time() - self._start_time

    def draw(self, surface: pygame.Surface, theme: ThemeBase,
             data: DashboardData) -> None:
        w, h = surface.get_size()
        self._progress = min(1.0, self.elapsed / 4.0)

        theme_name = getattr(theme, "name", "heritage")
        if theme_name == "modern":
            self._draw_modern(surface, w, h)
        elif theme_name == "autodelta":
            self._draw_autodelta(surface, w, h)
        else:
            self._draw_heritage(surface, w, h)

    def _draw_heritage(self, surface, w, h):
        """Heritage: burl texture bg + vignette + amber glow + car outline."""
        # Dark warm base
        surface.fill((26, 15, 10))

        # Burl wood grain effect — radial gradient spots
        import random
        rng = random.Random(7)
        grain_surf = pygame.Surface((w, h), pygame.SRCALPHA)
        for _ in range(12):
            sx = rng.randint(0, w)
            sy = rng.randint(0, h)
            sr = rng.randint(40, 120)
            for ring in range(sr, 0, -4):
                t = ring / sr
                a = int(10 * (1 - t))
                c = (int(61 * (1 - t) + 26 * t),
                     int(39 * (1 - t) + 15 * t),
                     int(22 * (1 - t) + 10 * t), a)
                pygame.draw.circle(grain_surf, c, (sx, sy), ring, 4)
        surface.blit(grain_surf, (0, 0))

        # Radial vignette (darken edges)
        vignette = pygame.Surface((w, h), pygame.SRCALPHA)
        cx, cy = w // 2, h // 2
        max_r = int(math.sqrt(cx * cx + cy * cy))
        for r in range(0, max_r, 4):
            alpha = int(min(220, (r / max_r) ** 1.5 * 280))
            pygame.draw.circle(vignette, (0, 0, 0, alpha), (cx, cy), max_r - r, 4)
        surface.blit(vignette, (0, 0))

        # Soft amber glow behind car
        glow = pygame.Surface((w, h), pygame.SRCALPHA)
        glow_r = 180
        for r in range(glow_r, 0, -3):
            a = int(25 * (1 - r / glow_r))
            pygame.draw.circle(glow, (255, 191, 0, a), (cx, cy - 20), r)
        surface.blit(glow, (0, 0))

        # Car silhouette — outline, amber
        draw_car_silhouette(surface, cx, cy - 20, 480, 220,
                            (255, 191, 0), "outline")

        # "ALFA ROMEO" spaced text with flanking lines
        brand_y = cy + 100
        font_brand = _font("sans-serif", 12)
        text = "A L F A   R O M E O"
        brand_surf = font_brand.render(text, True, (255, 191, 0))
        brand_rect = brand_surf.get_rect(center=(cx, brand_y))
        surface.blit(brand_surf, brand_rect)

        # Flanking lines
        line_surf = pygame.Surface((w, 4), pygame.SRCALPHA)
        line_color = (255, 191, 0, 100)
        line_w = 36
        gap = 10
        pygame.draw.line(line_surf, line_color,
                         (cx - brand_rect.width // 2 - line_w - gap, 1),
                         (cx - brand_rect.width // 2 - gap, 1), 1)
        pygame.draw.line(line_surf, line_color,
                         (cx + brand_rect.width // 2 + gap, 1),
                         (cx + brand_rect.width // 2 + line_w + gap, 1), 1)
        surface.blit(line_surf, (0, brand_y - 1))

        # Progress bar
        self._draw_progress(surface, w, h, (255, 191, 0), (30, 30, 30))

        # "CHECKING SYSTEMS..."
        font_status = _font("sans-serif", 10)
        status_text = "C H E C K I N G   S Y S T E M S . . ."
        st_surf = font_status.render(status_text, True, (255, 191, 0, 150))
        st_rect = st_surf.get_rect(center=(cx, h - 55))
        surface.blit(st_surf, st_rect)

        # Corner accents
        pad = 24
        draw_corner_accents(surface, pad, pad, w - 2 * pad, h - 2 * pad,
                            (255, 191, 0), size=24, lw=1)

    def _draw_modern(self, surface, w, h):
        """Modern: charcoal bg + blue glow + filled white car + dots."""
        surface.fill((22, 22, 24))
        cx, cy = w // 2, h // 2

        # Blue radial glow
        glow = pygame.Surface((w, h), pygame.SRCALPHA)
        glow_r = 200
        for r in range(glow_r, 0, -3):
            a = int(20 * (1 - r / glow_r))
            pygame.draw.circle(glow, (0, 85, 150, a), (cx, cy), r)
        surface.blit(glow, (0, 0))

        # Car silhouette — filled, semi-transparent white
        car_surf = pygame.Surface((w, h), pygame.SRCALPHA)
        draw_car_silhouette(car_surf, cx, cy - 10, 420, 200,
                            (255, 255, 255, 60), "filled")
        surface.blit(car_surf, (0, 0))

        # "CENTRO STILE ALFA ROMEO" top
        font_top = _font("sans-serif", 10)
        top_text = "C E N T R O   S T I L E   A L F A   R O M E O"
        top_surf = font_top.render(top_text, True, (255, 255, 255, 100))
        top_rect = top_surf.get_rect(center=(cx, 50))
        surface.blit(top_surf, top_rect)

        # Corner accents (blue)
        pad = 32
        draw_corner_accents(surface, pad, pad, w - 2 * pad, h - 2 * pad,
                            (0, 85, 150), size=28, lw=2)

        # Progress bar (blue)
        self._draw_progress(surface, w, h, (0, 85, 150), (40, 40, 45))

        # "SYSTEM INITIALIZING..."
        font_status = _font("sans-serif", 10)
        status_text = "S Y S T E M   I N I T I A L I Z I N G . . ."
        st_surf = font_status.render(status_text, True, (255, 255, 255, 120))
        st_rect = st_surf.get_rect(center=(cx, h - 55))
        surface.blit(st_surf, st_rect)

        # Dot indicators
        dot_y = h - 30
        for i in range(3):
            dx = cx + (i - 1) * 12
            c = (0, 85, 150) if self._progress * 3 > i else (60, 60, 65)
            pygame.draw.circle(surface, c, (dx, dot_y), 3)

    def _draw_autodelta(self, surface, w, h):
        """Autodelta: black bg + scanlines + crosshairs + inverted car + boot text."""
        surface.fill((0, 0, 0))
        cx, cy = w // 2, h // 2 - 20

        # Scanline texture
        scanline = pygame.Surface((w, h), pygame.SRCALPHA)
        for y_line in range(0, h, 4):
            pygame.draw.line(scanline, (236, 91, 19, 12), (0, y_line), (w, y_line), 1)
        surface.blit(scanline, (0, 0))

        # Full-screen crosshair lines
        cross_surf = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.line(cross_surf, (236, 91, 19, 40), (cx, 0), (cx, h), 1)
        pygame.draw.line(cross_surf, (236, 91, 19, 40), (0, cy), (w, cy), 1)
        surface.blit(cross_surf, (0, 0))

        # Car silhouette — inverted (orange body, dark windows)
        car_surf = pygame.Surface((w, h), pygame.SRCALPHA)
        draw_car_silhouette(car_surf, cx, cy, 400, 190,
                            (236, 91, 19, 100), "inverted")
        surface.blit(car_surf, (0, 0))

        # Corner accents (orange TL/BR, white TR/BL)
        pad = 24
        accent_size = 24
        lw = 2
        pygame.draw.line(surface, (236, 91, 19), (pad, pad), (pad + accent_size, pad), lw)
        pygame.draw.line(surface, (236, 91, 19), (pad, pad), (pad, pad + accent_size), lw)
        pygame.draw.line(surface, (236, 91, 19), (w - pad - accent_size, h - pad), (w - pad, h - pad), lw)
        pygame.draw.line(surface, (236, 91, 19), (w - pad, h - pad - accent_size), (w - pad, h - pad), lw)
        pygame.draw.line(surface, (255, 255, 255), (w - pad - accent_size, pad), (w - pad, pad), lw)
        pygame.draw.line(surface, (255, 255, 255), (w - pad, pad), (w - pad, pad + accent_size), lw)
        pygame.draw.line(surface, (255, 255, 255), (pad, h - pad - accent_size), (pad, h - pad), lw)
        pygame.draw.line(surface, (255, 255, 255), (pad, h - pad), (pad + accent_size, h - pad), lw)

        # "AUTODELTA CORE ENGAGED"
        font_header = _font("monospace", 14)
        header_text = "A U T O D E L T A   C O R E   E N G A G E D"
        header_surf = font_header.render(header_text, True, (236, 91, 19))
        header_rect = header_surf.get_rect(center=(w // 2, h // 2 + 100))
        surface.blit(header_surf, header_rect)

        # Boot text block
        font_boot = _font("monospace", 10)
        boot_lines = [
            ("UNIT_ID: BCM-ADF-0156", (113, 113, 122)),
            ("SENSORS: ONLINE", (236, 91, 19)),
            ("OBD-II:  CONNECTED", (236, 91, 19)),
            ("GPS:     ACQUIRING", (113, 113, 122)),
            ("LTE:     CONNECTED", (236, 91, 19)),
        ]
        boot_x = 60
        boot_y = h // 2 + 130
        for i, (line, color) in enumerate(boot_lines):
            if self._progress * 5 > i:
                line_surf = font_boot.render(line, True, color)
                surface.blit(line_surf, (boot_x, boot_y + i * 16))

        # Progress bar
        self._draw_progress(surface, w, h, (236, 91, 19), (30, 30, 30))

        # "INITIALIZING SYSTEMS..."
        font_status = _font("monospace", 9)
        st_text = "I N I T I A L I Z I N G   S Y S T E M S . . ."
        st_surf = font_status.render(st_text, True, (113, 113, 122))
        st_rect = st_surf.get_rect(center=(w // 2, h - 45))
        surface.blit(st_surf, st_rect)

    def _draw_progress(self, surface, w, h, fill_color, bg_color):
        """Draw thin progress bar near bottom — matches mockup."""
        bar_w = 200
        bar_h = 3
        bar_x = w // 2 - bar_w // 2
        bar_y = h - 70

        pygame.draw.rect(surface, bg_color, (bar_x, bar_y, bar_w, bar_h))
        fill_w = int(bar_w * self._progress)
        if fill_w > 0:
            pygame.draw.rect(surface, fill_color, (bar_x, bar_y, fill_w, bar_h))
