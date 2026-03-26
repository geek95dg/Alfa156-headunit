"""Initialization Screen — Full-screen splash on boot, no chrome.

Three theme variants:
- Heritage: Burl texture bg, car silhouette with amber glow, "ALFA ROMEO"
- Modern: Charcoal bg, car silhouette, "CENTRO STILE ALFA ROMEO"
- Autodelta: Black bg, scanlines, "AUTODELTA CORE ENGAGED" boot text
"""

import math
import time
import pygame
from src.dashboard.themes.theme_base import ThemeBase
from .base_screen import BaseScreen, DashboardData, _font


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

        # Update progress (0-1 over ~4 seconds)
        self._progress = min(1.0, self.elapsed / 4.0)

        theme_name = getattr(theme, "name", "heritage")

        if theme_name == "modern":
            self._draw_modern(surface, theme, w, h)
        elif theme_name == "autodelta":
            self._draw_autodelta(surface, theme, w, h)
        else:
            self._draw_heritage(surface, theme, w, h)

    def _draw_heritage(self, surface: pygame.Surface, theme: ThemeBase,
                       w: int, h: int) -> None:
        # Dark warm background
        surface.fill((26, 15, 10))

        # Radial vignette effect
        vignette = pygame.Surface((w, h), pygame.SRCALPHA)
        cx, cy = w // 2, h // 2
        max_r = int(math.sqrt(cx * cx + cy * cy))
        for i in range(0, max_r, 4):
            alpha = int(min(255, (i / max_r) * 200))
            pygame.draw.circle(vignette, (0, 0, 0, alpha), (cx, cy), max_r - i, 4)
        surface.blit(vignette, (0, 0))

        # Amber glow at center
        glow = pygame.Surface((300, 200), pygame.SRCALPHA)
        for r in range(100, 0, -2):
            alpha = int(20 * (r / 100))
            pygame.draw.ellipse(glow, (255, 191, 0, alpha),
                                (150 - r, 100 - r * 2 // 3, r * 2, r * 4 // 3))
        surface.blit(glow, (w // 2 - 150, h // 2 - 100))

        # Car silhouette (simple polygon)
        self._draw_car_silhouette(surface, w // 2, h // 2, (245, 158, 11))

        # "ALFA ROMEO" text
        font_brand = _font("sans-serif", 24)
        text = "ALFA ROMEO"
        brand_surf = font_brand.render(text, True, (245, 158, 11))
        brand_rect = brand_surf.get_rect(center=(w // 2, h // 2 + 80))
        surface.blit(brand_surf, brand_rect)

        # Progress bar
        self._draw_progress(surface, w, h, (245, 158, 11), (60, 40, 20))

        # Status text
        font_status = _font("sans-serif", 14)
        status = "CHECKING SYSTEMS..."
        status_surf = font_status.render(status, True, (245, 158, 11, 150))
        status_rect = status_surf.get_rect(center=(w // 2, h - 50))
        surface.blit(status_surf, status_rect)

    def _draw_modern(self, surface: pygame.Surface, theme: ThemeBase,
                     w: int, h: int) -> None:
        # Charcoal background
        surface.fill((22, 22, 24))

        # Blue glow at center
        glow = pygame.Surface((400, 300), pygame.SRCALPHA)
        for r in range(150, 0, -3):
            alpha = int(15 * (r / 150))
            pygame.draw.ellipse(glow, (59, 130, 246, alpha),
                                (200 - r, 150 - r * 2 // 3, r * 2, r * 4 // 3))
        surface.blit(glow, (w // 2 - 200, h // 2 - 150))

        # Car silhouette
        self._draw_car_silhouette(surface, w // 2, h // 2, (100, 130, 180))

        # "CENTRO STILE ALFA ROMEO" top
        font_top = _font("sans-serif", 12)
        top_surf = font_top.render("CENTRO STILE ALFA ROMEO", True, (255, 255, 255, 100))
        top_rect = top_surf.get_rect(center=(w // 2, 60))
        surface.blit(top_surf, top_rect)

        # Corner accents
        accent = (59, 130, 246, 80)
        sz = 30
        lw = 2
        # Top-left
        pygame.draw.line(surface, accent[:3], (20, 20), (20 + sz, 20), lw)
        pygame.draw.line(surface, accent[:3], (20, 20), (20, 20 + sz), lw)
        # Top-right
        pygame.draw.line(surface, accent[:3], (w - 20, 20), (w - 20 - sz, 20), lw)
        pygame.draw.line(surface, accent[:3], (w - 20, 20), (w - 20, 20 + sz), lw)
        # Bottom-left
        pygame.draw.line(surface, accent[:3], (20, h - 20), (20 + sz, h - 20), lw)
        pygame.draw.line(surface, accent[:3], (20, h - 20), (20, h - 20 - sz), lw)
        # Bottom-right
        pygame.draw.line(surface, accent[:3], (w - 20, h - 20), (w - 20 - sz, h - 20), lw)
        pygame.draw.line(surface, accent[:3], (w - 20, h - 20), (w - 20, h - 20 - sz), lw)

        # "SYSTEM INITIALIZING..."
        font_status = _font("sans-serif", 14)
        status_surf = font_status.render("SYSTEM INITIALIZING...", True, (200, 200, 200))
        status_rect = status_surf.get_rect(center=(w // 2, h - 60))
        surface.blit(status_surf, status_rect)

        # Progress bar (blue)
        self._draw_progress(surface, w, h, (59, 130, 246), (40, 40, 50))

    def _draw_autodelta(self, surface: pygame.Surface, theme: ThemeBase,
                        w: int, h: int) -> None:
        # Black background
        surface.fill((0, 0, 0))

        # Scanline texture
        scanline = pygame.Surface((w, h), pygame.SRCALPHA)
        for y in range(0, h, 4):
            pygame.draw.line(scanline, (236, 91, 19, 12), (0, y), (w, y), 1)
        surface.blit(scanline, (0, 0))

        # Crosshair lines at center
        cx, cy = w // 2, h // 2
        pygame.draw.line(surface, (236, 91, 19, 30), (cx - 60, cy), (cx + 60, cy), 1)
        pygame.draw.line(surface, (236, 91, 19, 30), (cx, cy - 40), (cx, cy + 40), 1)

        # Car silhouette
        self._draw_car_silhouette(surface, cx, cy, (236, 91, 19))

        # Corner accents (orange TL/BR, white TR/BL)
        sz = 25
        lw = 2
        pygame.draw.line(surface, (236, 91, 19), (15, 15), (15 + sz, 15), lw)
        pygame.draw.line(surface, (236, 91, 19), (15, 15), (15, 15 + sz), lw)
        pygame.draw.line(surface, (255, 255, 255), (w - 15, 15), (w - 15 - sz, 15), lw)
        pygame.draw.line(surface, (255, 255, 255), (w - 15, 15), (w - 15, 15 + sz), lw)
        pygame.draw.line(surface, (255, 255, 255), (15, h - 15), (15 + sz, h - 15), lw)
        pygame.draw.line(surface, (255, 255, 255), (15, h - 15), (15, h - 15 - sz), lw)
        pygame.draw.line(surface, (236, 91, 19), (w - 15, h - 15), (w - 15 - sz, h - 15), lw)
        pygame.draw.line(surface, (236, 91, 19), (w - 15, h - 15), (w - 15, h - 15 - sz), lw)

        # "AUTODELTA CORE ENGAGED"
        font_title = _font("monospace", 20)
        title_surf = font_title.render("AUTODELTA CORE ENGAGED", True, (236, 91, 19))
        title_rect = title_surf.get_rect(center=(cx, cy + 70))
        surface.blit(title_surf, title_rect)

        # Boot text block
        font_boot = _font("monospace", 11)
        boot_lines = [
            "UNIT_ID: AUTODELTA-156-GTA",
            f"SENSORS: ONLINE ({int(self._progress * 100)}%)",
            "ECU LINK: ACTIVE",
            "DIAG: READY",
        ]
        for i, line in enumerate(boot_lines):
            if self._progress * 4 > i:
                color = (236, 91, 19) if i < 3 else (34, 197, 94)
                line_surf = font_boot.render(line, True, color)
                surface.blit(line_surf, (60, h - 120 + i * 18))

        # Progress bar (orange)
        self._draw_progress(surface, w, h, (236, 91, 19), (30, 30, 30))

    def _draw_car_silhouette(self, surface: pygame.Surface, cx: int, cy: int,
                             color: tuple) -> None:
        """Draw a simplified classic car side profile."""
        # Relative coordinates scaled to fit ~200x60px area
        points = [
            (-80, 10), (-70, -5), (-55, -20), (-30, -25),
            (-10, -25), (10, -25), (30, -20), (50, -15),
            (70, -5), (80, 10), (75, 15), (-75, 15),
        ]
        scaled = [(cx + px, cy + py) for px, py in points]
        if len(scaled) >= 3:
            pygame.draw.polygon(surface, color, scaled, 2)

        # Wheels
        pygame.draw.circle(surface, color, (cx - 50, cy + 15), 10, 2)
        pygame.draw.circle(surface, color, (cx + 50, cy + 15), 10, 2)

    def _draw_progress(self, surface: pygame.Surface, w: int, h: int,
                       fill_color: tuple, bg_color: tuple) -> None:
        """Draw a thin progress bar near the bottom."""
        bar_w = 200
        bar_h = 3
        bar_x = w // 2 - bar_w // 2
        bar_y = h - 30

        # Background
        pygame.draw.rect(surface, bg_color, (bar_x, bar_y, bar_w, bar_h))
        # Fill
        fill_w = int(bar_w * self._progress)
        if fill_w > 0:
            pygame.draw.rect(surface, fill_color, (bar_x, bar_y, fill_w, bar_h))
