"""Gauge renderers — circular arc, horizontal bar, and digital gauges.

Each gauge reads its style from the active theme and renders via PyGame.
"""

import math
import pygame
from src.dashboard.themes.theme_base import ThemeBase, GaugeStyle


def _get_font(name: str, size: int) -> pygame.font.Font:
    """Get a system font, falling back to default if not found."""
    try:
        return pygame.font.SysFont(name, size)
    except Exception:
        return pygame.font.Font(None, size)


def draw_arc_gauge(
    surface: pygame.Surface,
    theme: ThemeBase,
    style: GaugeStyle,
    rect: tuple[int, int, int, int],
    value: float,
    min_val: float,
    max_val: float,
    label: str,
    unit: str,
    redzone_start: float | None = None,
    fmt: str = "{:.0f}",
) -> None:
    """Draw a circular arc gauge with needle and value text."""
    x, y, w, h = rect
    cx = x + w // 2
    cy = y + h // 2
    radius = min(w, h) // 2 - 10

    # Clamp value
    clamped = max(min_val, min(max_val, value))
    fraction = (clamped - min_val) / (max_val - min_val) if max_val > min_val else 0

    # Background arc
    _draw_arc(surface, theme.gauge_bg, cx, cy, radius, style.arc_width,
              style.start_angle, style.sweep_angle)

    # Redzone arc (if specified)
    if redzone_start is not None and redzone_start < max_val:
        rz_frac = (redzone_start - min_val) / (max_val - min_val)
        rz_start = style.start_angle - rz_frac * style.sweep_angle
        rz_sweep = (1.0 - rz_frac) * style.sweep_angle
        _draw_arc(surface, theme.gauge_redzone, cx, cy, radius, style.arc_width,
                  rz_start, rz_sweep)

    # Value arc
    val_sweep = fraction * style.sweep_angle
    color = theme.gauge_fg
    if redzone_start is not None and clamped >= redzone_start:
        color = theme.danger_color
    _draw_arc(surface, color, cx, cy, radius, style.arc_width,
              style.start_angle, val_sweep)

    # Tick marks
    num_ticks = 10
    for i in range(num_ticks + 1):
        tick_frac = i / num_ticks
        angle_deg = style.start_angle - tick_frac * style.sweep_angle
        angle_rad = math.radians(angle_deg)
        inner_r = radius - style.tick_length
        outer_r = radius + 2
        x1 = cx + inner_r * math.cos(angle_rad)
        y1 = cy - inner_r * math.sin(angle_rad)
        x2 = cx + outer_r * math.cos(angle_rad)
        y2 = cy - outer_r * math.sin(angle_rad)
        tick_color = theme.gauge_tick if i % 2 == 0 else (
            theme.gauge_tick[0] // 2, theme.gauge_tick[1] // 2, theme.gauge_tick[2] // 2
        )
        pygame.draw.line(surface, tick_color, (x1, y1), (x2, y2), style.tick_width)

    # Needle
    needle_angle_deg = style.start_angle - fraction * style.sweep_angle
    needle_angle_rad = math.radians(needle_angle_deg)
    needle_len = radius - 15
    nx = cx + needle_len * math.cos(needle_angle_rad)
    ny = cy - needle_len * math.sin(needle_angle_rad)
    pygame.draw.line(surface, theme.gauge_needle, (cx, cy), (nx, ny), style.needle_width)
    pygame.draw.circle(surface, theme.gauge_needle, (cx, cy), 5)

    # Value text (centered)
    font_val = _get_font(theme.font_name, style.value_size)
    val_text = fmt.format(value)
    val_surf = font_val.render(val_text, True, theme.gauge_text)
    val_rect = val_surf.get_rect(center=(cx, cy + radius // 3))
    surface.blit(val_surf, val_rect)

    # Unit label
    font_unit = _get_font(theme.font_name, style.unit_size)
    unit_surf = font_unit.render(unit, True, theme.text_secondary)
    unit_rect = unit_surf.get_rect(center=(cx, cy + radius // 3 + style.value_size // 2 + 4))
    surface.blit(unit_surf, unit_rect)

    # Label above gauge
    font_label = _get_font(theme.font_name, style.label_size)
    label_surf = font_label.render(label, True, theme.text_secondary)
    label_rect = label_surf.get_rect(center=(cx, y + 8))
    surface.blit(label_surf, label_rect)


def draw_bar_gauge(
    surface: pygame.Surface,
    theme: ThemeBase,
    style: GaugeStyle,
    rect: tuple[int, int, int, int],
    value: float,
    min_val: float,
    max_val: float,
    label: str,
    unit: str,
    redzone_start: float | None = None,
    fmt: str = "{:.0f}",
) -> None:
    """Draw a horizontal bar gauge with value text."""
    x, y, w, h = rect
    bar_h = style.arc_width
    bar_y = y + h // 2
    bar_x = x + 10
    bar_w = w - 20

    # Clamp value
    clamped = max(min_val, min(max_val, value))
    fraction = (clamped - min_val) / (max_val - min_val) if max_val > min_val else 0

    # Background bar
    pygame.draw.rect(surface, theme.gauge_bg, (bar_x, bar_y, bar_w, bar_h), border_radius=bar_h // 2)

    # Redzone portion
    if redzone_start is not None and redzone_start < max_val:
        rz_frac = (redzone_start - min_val) / (max_val - min_val)
        rz_x = bar_x + int(rz_frac * bar_w)
        rz_w = bar_w - int(rz_frac * bar_w)
        if rz_w > 0:
            pygame.draw.rect(surface, theme.gauge_redzone,
                             (rz_x, bar_y, rz_w, bar_h), border_radius=bar_h // 2)

    # Value bar
    fill_w = int(fraction * bar_w)
    if fill_w > 0:
        color = theme.gauge_fg
        if redzone_start is not None and clamped >= redzone_start:
            color = theme.danger_color
        pygame.draw.rect(surface, color, (bar_x, bar_y, fill_w, bar_h), border_radius=bar_h // 2)

    # Label (top left)
    font_label = _get_font(theme.font_name, style.label_size)
    label_surf = font_label.render(label, True, theme.text_secondary)
    surface.blit(label_surf, (bar_x, y + 4))

    # Value (top right, large)
    font_val = _get_font(theme.font_name, style.value_size)
    val_text = f"{fmt.format(value)} {unit}"
    val_surf = font_val.render(val_text, True, theme.gauge_text)
    val_rect = val_surf.get_rect(topright=(bar_x + bar_w, y + 2))
    surface.blit(val_surf, val_rect)


def draw_digital_gauge(
    surface: pygame.Surface,
    theme: ThemeBase,
    style: GaugeStyle,
    rect: tuple[int, int, int, int],
    value: float,
    label: str,
    unit: str,
    fmt: str = "{:.0f}",
) -> None:
    """Draw a digital-only gauge (value + label, no graphical element)."""
    x, y, w, h = rect
    cx = x + w // 2

    # Label
    font_label = _get_font(theme.font_name, style.label_size)
    label_surf = font_label.render(label, True, theme.text_secondary)
    label_rect = label_surf.get_rect(center=(cx, y + 8))
    surface.blit(label_surf, label_rect)

    # Value
    font_val = _get_font(theme.font_name, style.value_size)
    val_text = fmt.format(value)
    val_surf = font_val.render(val_text, True, theme.gauge_text)
    val_rect = val_surf.get_rect(center=(cx, y + h // 2))
    surface.blit(val_surf, val_rect)

    # Unit
    font_unit = _get_font(theme.font_name, style.unit_size)
    unit_surf = font_unit.render(unit, True, theme.text_secondary)
    unit_rect = unit_surf.get_rect(center=(cx, y + h // 2 + style.value_size // 2 + 4))
    surface.blit(unit_surf, unit_rect)


def draw_gauge(
    surface: pygame.Surface,
    theme: ThemeBase,
    style: GaugeStyle,
    rect: tuple[int, int, int, int],
    value: float,
    min_val: float,
    max_val: float,
    label: str,
    unit: str,
    redzone_start: float | None = None,
    fmt: str = "{:.0f}",
) -> None:
    """Draw a gauge using the style specified in the GaugeStyle object."""
    if style.style == "bar":
        draw_bar_gauge(surface, theme, style, rect, value, min_val, max_val,
                       label, unit, redzone_start, fmt)
    elif style.style == "digital":
        draw_digital_gauge(surface, theme, style, rect, value, label, unit, fmt)
    else:  # "arc" (default)
        draw_arc_gauge(surface, theme, style, rect, value, min_val, max_val,
                       label, unit, redzone_start, fmt)


# ---------------------------------------------------------------------------
# Helper: draw thick arc (PyGame doesn't have a built-in thick arc)
# ---------------------------------------------------------------------------

def _draw_arc(
    surface: pygame.Surface,
    color: tuple,
    cx: int, cy: int,
    radius: int,
    width: int,
    start_angle_deg: float,
    sweep_deg: float,
    segments: int = 60,
) -> None:
    """Draw a thick arc using line segments."""
    if sweep_deg <= 0 or radius <= 0:
        return
    step = sweep_deg / segments
    points_outer = []
    points_inner = []
    for i in range(segments + 1):
        angle = math.radians(start_angle_deg - i * step)
        ox = cx + radius * math.cos(angle)
        oy = cy - radius * math.sin(angle)
        ix = cx + (radius - width) * math.cos(angle)
        iy = cy - (radius - width) * math.sin(angle)
        points_outer.append((ox, oy))
        points_inner.append((ix, iy))
    # Build polygon from outer arc + reversed inner arc
    polygon = points_outer + list(reversed(points_inner))
    if len(polygon) >= 3:
        pygame.draw.polygon(surface, color, polygon)
