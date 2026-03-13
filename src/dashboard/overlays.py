"""Overlays — parking distance bars, icing alert popup, reverse camera overlay."""

import time
import pygame
from src.dashboard.themes.theme_base import ThemeBase


def _get_font(name: str, size: int) -> pygame.font.Font:
    try:
        return pygame.font.SysFont(name, size)
    except Exception:
        return pygame.font.Font(None, size)


def _distance_color(distance_m: float, theme: ThemeBase) -> tuple:
    """Get color based on distance zone."""
    if distance_m > 1.0:
        return theme.parking_green
    elif distance_m > 0.5:
        return theme.parking_yellow
    elif distance_m > 0.3:
        return theme.parking_orange
    else:
        return theme.parking_red


class ParkingOverlay:
    """Full-screen parking overlay with distance bars for 4 rear sensors."""

    def __init__(self) -> None:
        # Distances in meters for 4 rear sensors (left to right)
        self.distances: list[float] = [2.0, 2.0, 2.0, 2.0]
        self.active: bool = False

    def draw(self, surface: pygame.Surface, theme: ThemeBase) -> None:
        """Draw parking sensor overlay."""
        if not self.active:
            return

        w, h = surface.get_size()

        # Semi-transparent background
        overlay = pygame.Surface((w, h), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 160))
        surface.blit(overlay, (0, 0))

        # Title
        font_title = _get_font(theme.font_name, 20)
        title_surf = font_title.render("PARKING", True, theme.overlay_text)
        title_rect = title_surf.get_rect(center=(w // 2, 50))
        surface.blit(title_surf, title_rect)

        # Draw 4 vertical distance bars
        bar_width = 60
        bar_max_height = 250
        bar_spacing = 30
        total_width = 4 * bar_width + 3 * bar_spacing
        start_x = (w - total_width) // 2
        bar_y = 90

        labels = ["L", "CL", "CR", "R"]
        font_label = _get_font(theme.font_name, 14)
        font_dist = _get_font(theme.font_name, 18)

        for i, dist in enumerate(self.distances):
            bx = start_x + i * (bar_width + bar_spacing)

            # Background bar
            pygame.draw.rect(surface, theme.gauge_bg,
                             (bx, bar_y, bar_width, bar_max_height), border_radius=4)

            # Fill bar (inversely proportional to distance — closer = more fill)
            max_dist = 2.0
            clamped = max(0.05, min(max_dist, dist))
            fill_frac = 1.0 - (clamped / max_dist)
            fill_h = int(fill_frac * bar_max_height)
            color = _distance_color(dist, theme)

            if fill_h > 0:
                pygame.draw.rect(surface, color,
                                 (bx, bar_y + bar_max_height - fill_h, bar_width, fill_h),
                                 border_radius=4)

            # Sensor label
            lbl_surf = font_label.render(labels[i], True, theme.overlay_text)
            lbl_rect = lbl_surf.get_rect(center=(bx + bar_width // 2, bar_y + bar_max_height + 20))
            surface.blit(lbl_surf, lbl_rect)

            # Distance value
            dist_str = f"{dist:.2f}m" if dist < 2.0 else ">2m"
            dist_surf = font_dist.render(dist_str, True, color)
            dist_rect = dist_surf.get_rect(center=(bx + bar_width // 2, bar_y + bar_max_height + 42))
            surface.blit(dist_surf, dist_rect)

        # Car outline (simplified)
        car_y = bar_y + bar_max_height + 65
        car_w, car_h = 100, 50
        car_x = (w - car_w) // 2
        pygame.draw.rect(surface, theme.text_secondary, (car_x, car_y, car_w, car_h), 2, border_radius=8)
        # rear bumper
        pygame.draw.line(surface, theme.accent_color,
                         (car_x, car_y + car_h), (car_x + car_w, car_y + car_h), 3)

        font_car = _get_font(theme.font_name, 10)
        car_label = font_car.render("REAR", True, theme.text_secondary)
        car_rect = car_label.get_rect(center=(w // 2, car_y + car_h // 2))
        surface.blit(car_label, car_rect)


class IcingAlert:
    """Icing alert popup overlay."""

    def __init__(self) -> None:
        self._show_until: float = 0.0

    def trigger(self, duration: float = 5.0) -> None:
        """Show icing alert for given seconds."""
        self._show_until = time.time() + duration

    @property
    def active(self) -> bool:
        return time.time() < self._show_until

    def draw(self, surface: pygame.Surface, theme: ThemeBase) -> None:
        """Draw icing alert popup if active."""
        if not self.active:
            return

        w, h = surface.get_size()
        popup_w, popup_h = 400, 120
        px = (w - popup_w) // 2
        py = (h - popup_h) // 2

        # Background
        overlay = pygame.Surface((popup_w, popup_h), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 200))
        surface.blit(overlay, (px, py))

        # Border
        pygame.draw.rect(surface, theme.warning_color, (px, py, popup_w, popup_h), 2, border_radius=8)

        # Warning icon
        font_icon = _get_font(theme.font_name, 36)
        icon_surf = font_icon.render("!", True, theme.warning_color)
        icon_rect = icon_surf.get_rect(center=(px + 40, py + popup_h // 2))
        surface.blit(icon_surf, icon_rect)
        pygame.draw.circle(surface, theme.warning_color, (px + 40, py + popup_h // 2), 25, 2)

        # Text
        font_title = _get_font(theme.font_name, 20)
        font_msg = _get_font(theme.font_name, 14)

        title_surf = font_title.render("ICING WARNING", True, theme.warning_color)
        msg_surf = font_msg.render("Temperature dropping below 3\u00b0C", True, theme.overlay_text)
        msg2_surf = font_msg.render("Possible ice on road", True, theme.text_secondary)

        surface.blit(title_surf, (px + 80, py + 20))
        surface.blit(msg_surf, (px + 80, py + 55))
        surface.blit(msg2_surf, (px + 80, py + 78))
