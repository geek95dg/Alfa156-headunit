"""Shared drawing assets for BCM dashboard screens.

Provides car silhouette and stylized map drawing functions that match
the mockup generator renders 1:1. Used by initialization_screen.py,
service_screen.py, and weather_screen.py.
"""

import math
import pygame


# Normalized car profile points (0-1 range) — matches generate_mockups_v2.py
CAR_PROFILE = [
    (0.00, 0.65),  # front bumper bottom
    (0.05, 0.55),  # front grille
    (0.08, 0.48),  # hood start
    (0.25, 0.45),  # hood line
    (0.30, 0.42),  # windshield base
    (0.35, 0.22),  # windshield top
    (0.40, 0.18),  # roof front
    (0.55, 0.16),  # roof peak
    (0.65, 0.18),  # roof rear
    (0.72, 0.28),  # rear window top
    (0.78, 0.40),  # rear window base
    (0.82, 0.42),  # trunk start
    (0.90, 0.44),  # trunk line
    (0.95, 0.50),  # tail
    (1.00, 0.60),  # rear bumper bottom
    (0.95, 0.68),  # underside rear
    (0.82, 0.70),  # rear wheel well top
    (0.72, 0.68),  # between wheels
    (0.35, 0.68),  # front wheel well area
    (0.25, 0.70),  # front wheel well top
    (0.12, 0.68),  # underside front
    (0.00, 0.65),  # back to start
]

# Window cutout for "inverted" style
CAR_WINDOW = [
    (0.33, 0.24), (0.38, 0.20), (0.63, 0.18),
    (0.70, 0.20), (0.75, 0.36), (0.33, 0.38),
]

WHEEL_POSITIONS = [(0.22, 0.68), (0.78, 0.68)]


def _scale_pts(profile, cx, cy, w, h):
    """Scale normalized points to target rect centered at (cx, cy)."""
    hw, hh = w // 2, h // 2
    return [(cx - hw + int(px * w), cy - hh + int(py * h))
            for px, py in profile]


def draw_car_silhouette(surface, cx, cy, w, h, color, style="outline"):
    """Draw a classic Alfa side-profile car silhouette on a PyGame surface.

    style: "outline" — line drawing (Heritage init, Autodelta service)
           "filled" — solid fill (Modern init)
           "inverted" — filled with dark window cutout (Autodelta init)
    """
    pts = _scale_pts(CAR_PROFILE, cx, cy, w, h)
    wheel_r = int(w * 0.055)

    if style == "filled":
        if len(pts) >= 3:
            pygame.draw.polygon(surface, color, pts)
        for wx, wy in WHEEL_POSITIONS:
            wcx = cx - w // 2 + int(wx * w)
            wcy = cy - h // 2 + int(wy * h)
            pygame.draw.circle(surface, color, (wcx, wcy), wheel_r)

    elif style == "inverted":
        if len(pts) >= 3:
            pygame.draw.polygon(surface, color, pts)
        # Window cutout (darker)
        win_pts = _scale_pts(CAR_WINDOW, cx, cy, w, h)
        if len(win_pts) >= 3:
            pygame.draw.polygon(surface, (0, 0, 0), win_pts)
        for wx, wy in WHEEL_POSITIONS:
            wcx = cx - w // 2 + int(wx * w)
            wcy = cy - h // 2 + int(wy * h)
            pygame.draw.circle(surface, color, (wcx, wcy), wheel_r)
            inner_r = int(wheel_r * 0.5)
            pygame.draw.circle(surface, (0, 0, 0), (wcx, wcy), inner_r)

    else:  # outline
        lw = max(2, w // 120)
        for i in range(len(pts) - 1):
            pygame.draw.line(surface, color, pts[i], pts[i + 1], lw)
        for wx, wy in WHEEL_POSITIONS:
            wcx = cx - w // 2 + int(wx * w)
            wcy = cy - h // 2 + int(wy * h)
            pygame.draw.circle(surface, color, (wcx, wcy), wheel_r, lw)


def draw_stylized_map(surface, x, y, w, h, accent_color, theme_name="heritage"):
    """Draw a stylized map matching the mockup renders.

    Dark background, slightly randomized grid streets, diagonal accent road,
    horizontal main road, curved river, location dot with glow, edge vignette.
    """
    import random
    rng = random.Random(42)  # Deterministic — same as mockup generator

    # Base dark background
    map_bg = (15, 15, 18)
    pygame.draw.rect(surface, map_bg, (x, y, w, h))

    # Grid streets (thin, slightly randomized)
    grid_color = (40, 40, 45)
    spacing = 30
    for gx in range(0, w, spacing):
        offset = rng.randint(-5, 5)
        pygame.draw.line(surface, grid_color,
                         (x + gx + offset, y), (x + gx + offset, y + h), 1)
    for gy in range(0, h, spacing):
        offset = rng.randint(-5, 5)
        pygame.draw.line(surface, grid_color,
                         (x, y + gy + offset), (x + w, y + gy + offset), 1)

    # Main diagonal road (accent-tinted)
    road_alpha_surf = pygame.Surface((w, h), pygame.SRCALPHA)
    road_color = (*accent_color[:3], 60)
    lw = 3
    pygame.draw.line(road_alpha_surf, road_color,
                     (0, h * 3 // 4), (w, h // 4), lw)
    # Horizontal main road
    pygame.draw.line(road_alpha_surf, road_color,
                     (0, h // 2), (w, h // 2), lw)
    surface.blit(road_alpha_surf, (x, y))

    # Curved "river" — smooth sine wave
    river_surf = pygame.Surface((w, h), pygame.SRCALPHA)
    river_color = (40, 60, 80, 40)
    prev = None
    for i in range(20):
        rx = int(w * i / 19)
        ry = h // 3 + int(math.sin(i * 0.5) * 20)
        if prev:
            pygame.draw.line(river_surf, river_color, prev, (rx, ry), 4)
        prev = (rx, ry)
    surface.blit(river_surf, (x, y))

    # Location dot (with glow)
    dot_cx = x + w // 2 + 20
    dot_cy = y + h // 2 - 10
    # Outer glow
    glow_surf = pygame.Surface((50, 50), pygame.SRCALPHA)
    pygame.draw.circle(glow_surf, (*accent_color[:3], 40), (25, 25), 12)
    surface.blit(glow_surf, (dot_cx - 25, dot_cy - 25))
    # Inner dot
    pygame.draw.circle(surface, accent_color[:3], (dot_cx, dot_cy), 5)

    # Edge vignette — darken edges with semi-transparent overlay
    vignette = pygame.Surface((w, h), pygame.SRCALPHA)
    fade_w = 30
    for i in range(fade_w):
        a = int(200 * (1 - i / fade_w))
        # Left edge
        pygame.draw.line(vignette, (*map_bg, a), (i, 0), (i, h), 1)
        # Right edge
        pygame.draw.line(vignette, (*map_bg, a), (w - 1 - i, 0), (w - 1 - i, h), 1)
    for i in range(fade_w):
        a = int(200 * (1 - i / fade_w))
        # Top edge
        pygame.draw.line(vignette, (*map_bg, a), (0, i), (w, i), 1)
        # Bottom edge
        pygame.draw.line(vignette, (*map_bg, a), (0, h - 1 - i), (w, h - 1 - i), 1)
    surface.blit(vignette, (x, y))


def draw_corner_accents(surface, x, y, w, h, color, size=24, lw=2):
    """Draw L-shaped corner bracket accents — matches mockup renderer."""
    # Top-left
    pygame.draw.line(surface, color, (x, y), (x + size, y), lw)
    pygame.draw.line(surface, color, (x, y), (x, y + size), lw)
    # Top-right
    pygame.draw.line(surface, color, (x + w - size, y), (x + w, y), lw)
    pygame.draw.line(surface, color, (x + w, y), (x + w, y + size), lw)
    # Bottom-left
    pygame.draw.line(surface, color, (x, y + h - size), (x, y + h), lw)
    pygame.draw.line(surface, color, (x, y + h), (x + size, y + h), lw)
    # Bottom-right
    pygame.draw.line(surface, color, (x + w - size, y + h), (x + w, y + h), lw)
    pygame.draw.line(surface, color, (x + w, y + h - size), (x + w, y + h), lw)
