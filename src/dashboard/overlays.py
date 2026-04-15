"""Overlays — reverse camera + parking sensors, icing alert popup."""

import time
import threading
import pygame
from src.dashboard.themes.theme_base import ThemeBase
from src.dashboard.i18n import t
from src.core.logger import get_logger

log = get_logger("dashboard.overlays")


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


class CameraCapture:
    """Captures frames from a USB/V4L2 camera using OpenCV.

    Runs in a background thread to avoid blocking the render loop.
    Falls back to a placeholder when no camera or OpenCV is not available.
    """

    def __init__(self) -> None:
        self._capture = None
        self._frame_surface: pygame.Surface | None = None
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None
        self._available = False
        self._device_index = -1

    @property
    def available(self) -> bool:
        return self._available

    def start(self, device: str | None = None) -> bool:
        """Start capturing from camera. Returns True if camera opened."""
        if self._running:
            return self._available

        try:
            import cv2
        except ImportError:
            log.warning("OpenCV not available — camera feed disabled. "
                        "Install: pip install opencv-python-headless")
            return False

        # Try to open camera
        dev = device or "/dev/video0"
        # Try V4L2 device path, then index 0
        cap = None
        for target in [dev, 0]:
            try:
                cap = cv2.VideoCapture(target)
                if cap.isOpened():
                    self._device_index = target
                    break
                cap.release()
                cap = None
            except Exception:
                cap = None

        if not cap or not cap.isOpened():
            log.warning("No camera found — showing placeholder")
            return False

        self._capture = cap
        self._available = True
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        log.info("Camera capture started: %s", self._device_index)
        return True

    def stop(self) -> None:
        """Stop capturing."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None
        if self._capture:
            self._capture.release()
            self._capture = None
        self._available = False
        self._frame_surface = None

    def get_surface(self, target_w: int, target_h: int) -> pygame.Surface | None:
        """Get the latest camera frame as a PyGame surface, scaled to target size."""
        with self._lock:
            if self._frame_surface is None:
                return None
            return pygame.transform.scale(self._frame_surface, (target_w, target_h))

    def _capture_loop(self) -> None:
        """Background thread: grab frames from camera."""
        try:
            import cv2
            import numpy as np
        except ImportError:
            return

        while self._running and self._capture and self._capture.isOpened():
            ret, frame = self._capture.read()
            if not ret:
                time.sleep(0.05)
                continue

            # Convert BGR → RGB
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w = frame_rgb.shape[:2]

            # Convert numpy array to PyGame surface
            surface = pygame.image.frombuffer(
                frame_rgb.tobytes(), (w, h), "RGB"
            )

            with self._lock:
                self._frame_surface = surface

            # ~20 FPS capture rate
            time.sleep(0.05)


class ParkingOverlay:
    """Reverse screen overlay: 2/3 camera feed (top) + 1/3 parking sensors (bottom).

    When no camera is available, shows a placeholder graphic in the camera area.
    """

    def __init__(self) -> None:
        # Distances in meters for 4 rear sensors (left to right)
        self.distances: list[float] = [2.0, 2.0, 2.0, 2.0]
        self.active: bool = False
        self.camera = CameraCapture()
        self._camera_started = False

    def _ensure_camera(self, device: str | None = None) -> None:
        """Start camera capture on first activation."""
        if not self._camera_started:
            self._camera_started = True
            self.camera.start(device)

    def release_camera(self) -> None:
        """Stop camera capture when leaving reverse."""
        if self._camera_started:
            self.camera.stop()
            self._camera_started = False

    def draw(self, surface: pygame.Surface, theme: ThemeBase,
             lang: str = "pl") -> None:
        """Draw reverse overlay: camera feed (2/3) + parking sensors (1/3)."""
        if not self.active:
            return

        self._ensure_camera()

        w, h = surface.get_size()

        # Layout: camera area = top 2/3, sensors = bottom 1/3
        cam_h = int(h * 2 / 3)  # ~320px on 480p
        sensor_h = h - cam_h    # ~160px

        # --- Camera area (top 2/3) ---
        self._draw_camera_area(surface, theme, lang, w, cam_h)

        # --- Parking sensors area (bottom 1/3) ---
        self._draw_sensor_area(surface, theme, lang, w, cam_h, sensor_h)

    def _draw_camera_area(self, surface: pygame.Surface, theme: ThemeBase,
                          lang: str, w: int, cam_h: int) -> None:
        """Draw the camera feed or placeholder in the top 2/3."""
        cam_surface = self.camera.get_surface(w, cam_h)

        if cam_surface:
            surface.blit(cam_surface, (0, 0))
            # Semi-transparent guidelines overlay
            self._draw_guidelines(surface, w, cam_h, theme)
        else:
            # No camera — draw placeholder
            self._draw_camera_placeholder(surface, theme, lang, w, cam_h)

        # "R" gear indicator — top right corner
        font_gear = _get_font(theme.font_name, 32)
        gear_surf = font_gear.render("R", True, theme.danger_color)
        gear_rect = gear_surf.get_rect(topright=(w - 16, 8))
        # Background circle
        pygame.draw.circle(surface, (0, 0, 0, 180),
                           (gear_rect.centerx, gear_rect.centery), 24)
        pygame.draw.circle(surface, theme.danger_color,
                           (gear_rect.centerx, gear_rect.centery), 24, 2)
        surface.blit(gear_surf, gear_rect)

    def _draw_guidelines(self, surface: pygame.Surface, w: int, cam_h: int,
                         theme: ThemeBase) -> None:
        """Draw parking guideline overlay on camera feed."""
        # Trapezoid guidelines showing expected car width at distances
        guide_alpha = pygame.Surface((w, cam_h), pygame.SRCALPHA)

        # Bottom wide, top narrow — perspective lines
        bottom_left = (w * 0.15, cam_h - 5)
        bottom_right = (w * 0.85, cam_h - 5)
        top_left = (w * 0.35, cam_h * 0.3)
        top_right = (w * 0.65, cam_h * 0.3)

        # Green zone (far)
        mid1_l = (bottom_left[0] * 0.5 + top_left[0] * 0.5,
                  bottom_left[1] * 0.5 + top_left[1] * 0.5)
        mid1_r = (bottom_right[0] * 0.5 + top_right[0] * 0.5,
                  bottom_right[1] * 0.5 + top_right[1] * 0.5)

        # Yellow zone (mid)
        mid2_l = (bottom_left[0] * 0.7 + top_left[0] * 0.3,
                  bottom_left[1] * 0.7 + top_left[1] * 0.3)
        mid2_r = (bottom_right[0] * 0.7 + top_right[0] * 0.3,
                  bottom_right[1] * 0.7 + top_right[1] * 0.3)

        # Draw guide lines with distance coloring
        line_w = 2
        # Far lines (green)
        pygame.draw.line(guide_alpha, (*theme.parking_green, 120),
                         top_left, mid1_l, line_w)
        pygame.draw.line(guide_alpha, (*theme.parking_green, 120),
                         top_right, mid1_r, line_w)
        # Cross bar at green zone
        pygame.draw.line(guide_alpha, (*theme.parking_green, 80),
                         (int(mid1_l[0]), int(mid1_l[1])),
                         (int(mid1_r[0]), int(mid1_r[1])), 1)

        # Mid lines (yellow)
        pygame.draw.line(guide_alpha, (*theme.parking_yellow, 140),
                         mid1_l, mid2_l, line_w)
        pygame.draw.line(guide_alpha, (*theme.parking_yellow, 140),
                         mid1_r, mid2_r, line_w)
        # Cross bar at yellow zone
        pygame.draw.line(guide_alpha, (*theme.parking_yellow, 100),
                         (int(mid2_l[0]), int(mid2_l[1])),
                         (int(mid2_r[0]), int(mid2_r[1])), 1)

        # Close lines (red)
        pygame.draw.line(guide_alpha, (*theme.parking_red, 160),
                         mid2_l, bottom_left, line_w + 1)
        pygame.draw.line(guide_alpha, (*theme.parking_red, 160),
                         mid2_r, bottom_right, line_w + 1)

        surface.blit(guide_alpha, (0, 0))

    def _draw_camera_placeholder(self, surface: pygame.Surface, theme: ThemeBase,
                                 lang: str, w: int, cam_h: int) -> None:
        """Draw a placeholder when no camera is connected."""
        # Dark background for camera area
        cam_bg = pygame.Surface((w, cam_h))
        cam_bg.fill((15, 18, 25))
        surface.blit(cam_bg, (0, 0))

        # Centered camera icon and message
        cx, cy = w // 2, cam_h // 2

        # Camera icon (rounded rectangle with lens circle)
        icon_w, icon_h = 80, 56
        icon_rect = pygame.Rect(cx - icon_w // 2, cy - 40 - icon_h // 2,
                                icon_w, icon_h)
        pygame.draw.rect(surface, (60, 65, 80), icon_rect, 0, border_radius=10)
        pygame.draw.rect(surface, (80, 85, 100), icon_rect, 2, border_radius=10)
        # Lens
        pygame.draw.circle(surface, (40, 45, 55), icon_rect.center, 18)
        pygame.draw.circle(surface, (80, 85, 100), icon_rect.center, 18, 2)
        pygame.draw.circle(surface, (60, 65, 80), icon_rect.center, 8)
        # Flash
        pygame.draw.circle(surface, (100, 105, 120),
                           (icon_rect.right - 16, icon_rect.top + 14), 5)

        # Text
        font_msg = _get_font(theme.font_name, 16)
        font_hint = _get_font(theme.font_name, 12)

        msg = t("reverse_no_camera", lang)
        hint = t("reverse_camera_hint", lang)

        msg_surf = font_msg.render(msg, True, (120, 130, 150))
        hint_surf = font_hint.render(hint, True, (80, 85, 100))

        surface.blit(msg_surf, msg_surf.get_rect(center=(cx, cy + 20)))
        surface.blit(hint_surf, hint_surf.get_rect(center=(cx, cy + 46)))

        # Still draw guidelines on placeholder for visual reference
        self._draw_guidelines(surface, w, cam_h, theme)

    def _draw_sensor_area(self, surface: pygame.Surface, theme: ThemeBase,
                          lang: str, w: int, y_offset: int, area_h: int) -> None:
        """Draw compact parking sensor display in bottom 1/3."""
        # Background
        sensor_bg = pygame.Surface((w, area_h), pygame.SRCALPHA)
        sensor_bg.fill((10, 12, 18, 220))
        surface.blit(sensor_bg, (0, y_offset))

        # Separator line
        pygame.draw.line(surface, theme.accent_color, (0, y_offset), (w, y_offset), 2)

        # Title
        font_title = _get_font(theme.font_name, 13)
        title_surf = font_title.render(t("parking", lang), True, theme.overlay_text)
        surface.blit(title_surf, (12, y_offset + 6))

        # Layout: car outline on left, 4 sensor bars in center, distance labels on right
        # Available height for bars: area_h - title(24) - padding(16)
        bar_area_top = y_offset + 26
        bar_area_h = area_h - 36
        bar_max_h = min(bar_area_h, 100)

        # Car outline (left side, ~120px wide)
        car_x = 30
        car_w_px = 90
        car_h_px = min(60, bar_max_h)
        car_y = bar_area_top + (bar_area_h - car_h_px) // 2
        self._draw_car_outline(surface, theme, car_x, car_y, car_w_px, car_h_px)

        # 4 sensor bars (center area)
        bar_width = 50
        bar_spacing = 16
        total_bars_w = 4 * bar_width + 3 * bar_spacing
        bar_start_x = (w - total_bars_w) // 2 + 40  # shift right from center

        labels = ["L", "CL", "CR", "R"]
        font_label = _get_font(theme.font_name, 11)
        font_dist = _get_font(theme.font_name, 14)

        for i, dist in enumerate(self.distances):
            bx = bar_start_x + i * (bar_width + bar_spacing)
            by = bar_area_top + 2

            # Background bar
            pygame.draw.rect(surface, theme.gauge_bg,
                             (bx, by, bar_width, bar_max_h), border_radius=3)

            # Fill bar (inversely proportional to distance)
            max_dist = 2.0
            clamped = max(0.05, min(max_dist, dist))
            fill_frac = 1.0 - (clamped / max_dist)
            fill_h = int(fill_frac * bar_max_h)
            color = _distance_color(dist, theme)

            if fill_h > 0:
                pygame.draw.rect(surface, color,
                                 (bx, by + bar_max_h - fill_h, bar_width, fill_h),
                                 border_radius=3)

            # Label below bar
            lbl_surf = font_label.render(labels[i], True, theme.text_secondary)
            lbl_rect = lbl_surf.get_rect(center=(bx + bar_width // 2,
                                                  by + bar_max_h + 12))
            surface.blit(lbl_surf, lbl_rect)

            # Distance value below label
            dist_str = f"{dist:.1f}m" if dist < 2.0 else ">2m"
            dist_surf = font_dist.render(dist_str, True, color)
            dist_rect = dist_surf.get_rect(center=(bx + bar_width // 2,
                                                    by + bar_max_h + 28))
            surface.blit(dist_surf, dist_rect)

        # Closest distance warning (right side)
        closest = min(self.distances)
        closest_color = _distance_color(closest, theme)

        warn_x = w - 130
        warn_cy = bar_area_top + bar_area_h // 2

        font_big = _get_font(theme.font_name, 36)
        font_lbl = _get_font(theme.font_name, 11)

        closest_str = f"{closest:.1f}m" if closest < 2.0 else ">2m"
        big_surf = font_big.render(closest_str, True, closest_color)
        lbl_surf = font_lbl.render(t("reverse_closest", lang), True, theme.text_secondary)

        surface.blit(lbl_surf, lbl_surf.get_rect(center=(warn_x + 50, warn_cy - 22)))
        surface.blit(big_surf, big_surf.get_rect(center=(warn_x + 50, warn_cy + 10)))

        # Flash red border when very close
        if closest < 0.3:
            pulse = int(abs(time.time() % 1.0 - 0.5) * 2 * 255)
            flash_color = (255, 0, 0, pulse)
            flash_surf = pygame.Surface((w, 4), pygame.SRCALPHA)
            flash_surf.fill(flash_color)
            surface.blit(flash_surf, (0, y_offset))

    def _draw_car_outline(self, surface: pygame.Surface, theme: ThemeBase,
                          x: int, y: int, w: int, h: int) -> None:
        """Draw a simple top-down car outline."""
        # Body
        body = pygame.Rect(x, y, w, h)
        pygame.draw.rect(surface, (50, 55, 65), body, 0, border_radius=8)
        pygame.draw.rect(surface, theme.text_secondary, body, 1, border_radius=8)

        # Rear bumper (highlighted — this is the sensor side)
        rear_y = y + h - 6
        pygame.draw.line(surface, theme.accent_color,
                         (x + 4, rear_y), (x + w - 4, rear_y), 3)

        # Sensor dots on rear bumper
        dot_spacing = w // 5
        for i in range(4):
            dx = x + dot_spacing * (i + 1)
            color = _distance_color(self.distances[i], theme)
            pygame.draw.circle(surface, color, (dx, rear_y), 3)

        # "REAR" label
        font_tiny = _get_font(theme.font_name, 9)
        rear_surf = font_tiny.render("REAR", True, theme.text_secondary)
        surface.blit(rear_surf, rear_surf.get_rect(center=(x + w // 2, y + h // 2 - 4)))

        # Arrow pointing down (direction of reversing)
        arrow_y = y + h // 2 + 8
        pygame.draw.polygon(surface, theme.text_secondary, [
            (x + w // 2, arrow_y + 8),
            (x + w // 2 - 6, arrow_y),
            (x + w // 2 + 6, arrow_y),
        ])


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

    def draw(self, surface: pygame.Surface, theme: ThemeBase,
             lang: str = "pl") -> None:
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

        title_surf = font_title.render(t("icing_title", lang), True, theme.warning_color)
        msg_surf = font_msg.render(t("icing_msg", lang), True, theme.overlay_text)
        msg2_surf = font_msg.render(t("icing_msg2", lang), True, theme.text_secondary)

        surface.blit(title_surf, (px + 80, py + 20))
        surface.blit(msg_surf, (px + 80, py + 55))
        surface.blit(msg2_surf, (px + 80, py + 78))
