#!/usr/bin/env python3
"""Generate PNG mockups matching the PDF wireframe layout (4 screens × 3 themes).

Phase 1: Common chrome (status bar, side gauges) + A1 Dashboard.
"""

import math
import os
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# --- Constants ---
W, H = 800, 480
SS = 3  # supersampling factor
SW, SH = W * SS, H * SS
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "mockups", "renders")

# --- Font helpers ---
_font_cache = {}
FONT_PATHS = {
    "regular":    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "bold":       "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "light":      "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "light_bold": "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "serif":      "/usr/share/fonts/truetype/freefont/FreeSerif.ttf",
    "serif_bold": "/usr/share/fonts/truetype/freefont/FreeSerifBold.ttf",
    "mono":       "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "mono_bold":  "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
}


def _font(variant, size):
    key = (variant, size)
    if key not in _font_cache:
        path = FONT_PATHS.get(variant, FONT_PATHS["regular"])
        try:
            _font_cache[key] = ImageFont.truetype(path, size)
        except OSError:
            _font_cache[key] = ImageFont.truetype(FONT_PATHS["regular"], size)
    return _font_cache[key]


# --- Drawing primitives ---

def lerp(c1, c2, t):
    t = max(0.0, min(1.0, t))
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def rgba(color, alpha):
    return (*color[:3], alpha)


def text_centered(draw, x, y, text, font, fill):
    bb = draw.textbbox((0, 0), text, font=font)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    draw.text((x - tw / 2, y - th / 2), text, font=font, fill=fill)


def text_right(draw, x, y, text, font, fill):
    bb = draw.textbbox((0, 0), text, font=font)
    tw = bb[2] - bb[0]
    draw.text((x - tw, y), text, font=font, fill=fill)


def rrect(draw, x, y, w, h, r, **kw):
    r = min(r, w // 2, h // 2)
    draw.rounded_rectangle([x, y, x + w, y + h], radius=r, **kw)


def grad_rect(draw, x, y, w, h, c_top, c_bot):
    for row in range(h):
        c = lerp(c_top, c_bot, row / max(h - 1, 1))
        draw.line([(x, y + row), (x + w - 1, y + row)], fill=c)


def thick_arc(draw, cx, cy, radius, width, start_deg, sweep_deg,
              c_start, c_end=None, segments=120):
    """Draw a thick arc from start_deg sweeping counter-clockwise."""
    if sweep_deg <= 0 or radius <= 0:
        return
    if c_end is None:
        c_end = c_start
    step = sweep_deg / segments
    for i in range(segments):
        t = i / segments
        c = lerp(c_start, c_end, t)
        a1 = math.radians(start_deg - i * step)
        a2 = math.radians(start_deg - (i + 1) * step)
        ro, ri = radius, radius - width
        draw.polygon([
            (cx + ro * math.cos(a1), cy - ro * math.sin(a1)),
            (cx + ro * math.cos(a2), cy - ro * math.sin(a2)),
            (cx + ri * math.cos(a2), cy - ri * math.sin(a2)),
            (cx + ri * math.cos(a1), cy - ri * math.sin(a1)),
        ], fill=c)


def draw_needle(draw, cx, cy, angle_deg, length, base_w, color):
    a = math.radians(angle_deg)
    tip = (cx + length * math.cos(a), cy - length * math.sin(a))
    p = a + math.pi / 2
    bw = base_w / 2
    b1 = (cx + bw * math.cos(p), cy - bw * math.sin(p))
    b2 = (cx - bw * math.cos(p), cy + bw * math.sin(p))
    tail_len = length * 0.15
    tail = (cx - tail_len * math.cos(a), cy + tail_len * math.sin(a))
    draw.polygon([b1, tip, b2, tail], fill=color)


def glow_arc(img, cx, cy, radius, width, start_deg, sweep_deg,
             color, alpha=30, blur_r=None):
    s = SS
    if blur_r is None:
        blur_r = 12 * s
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    thick_arc(gd, cx, cy, radius + width, width * 3,
              start_deg, sweep_deg, rgba(color, alpha))
    glow = glow.filter(ImageFilter.GaussianBlur(blur_r))
    return Image.alpha_composite(img, glow)


# --- Theme dataclass ---

class Theme:
    def __init__(self, name, display_name, **kw):
        self.name = name
        self.display_name = display_name
        for k, v in kw.items():
            setattr(self, k, v)


# =========================================================================
#  THEMES — 3 palettes
# =========================================================================

CLASSIC_ALFA = Theme(
    "classic_alfa", "Classic Alfa 156",
    # Background
    bg=(12, 8, 10),
    bg_top=(20, 10, 14),
    bg_bot=(6, 4, 6),
    # Accent — warm amber/red like real 156 backlit dials
    accent=(210, 60, 30),
    accent_dim=(140, 40, 20),
    accent_glow=(240, 80, 35),
    # Text
    text=(245, 235, 218),
    text_dim=(140, 105, 80),
    text_mid=(200, 160, 125),
    # Status bar
    status_bg=(18, 10, 12),
    status_line=(210, 60, 30),
    # Gauge
    gauge_bg=(30, 16, 14),
    gauge_fg=(210, 60, 30),
    gauge_tick=(165, 120, 95),
    gauge_tick_dim=(90, 60, 45),
    gauge_needle=(240, 50, 25),
    gauge_needle_glow=(255, 80, 30),
    redzone=(200, 25, 15),
    arc_start=(90, 20, 8),
    arc_end=(240, 75, 25),
    # Side bars
    side_bg=(28, 16, 14),
    side_border=(60, 30, 22),
    temp_cold=(70, 140, 200),
    temp_warm=(210, 130, 40),
    temp_hot=(240, 55, 25),
    fuel_ok=(90, 185, 70),
    fuel_low=(240, 55, 25),
    # Danger / OK
    ok=(90, 190, 80),
    warning=(245, 190, 30),
    danger=(230, 35, 25),
    # Bottom bar
    bottom_bg=(18, 10, 12),
    # Icon tint
    icon_color=(210, 60, 30),
    # Font style
    font="regular",
    font_bold="bold",
)

MODERN_DARK = Theme(
    "modern_dark", "Modern Dark",
    bg=(10, 12, 18),
    bg_top=(16, 18, 28),
    bg_bot=(5, 7, 12),
    accent=(0, 180, 255),
    accent_dim=(0, 100, 160),
    accent_glow=(0, 210, 255),
    text=(228, 235, 248),
    text_dim=(85, 95, 120),
    text_mid=(145, 155, 180),
    status_bg=(14, 16, 24),
    status_line=(0, 180, 255),
    gauge_bg=(24, 28, 40),
    gauge_fg=(0, 180, 255),
    gauge_tick=(75, 85, 110),
    gauge_tick_dim=(40, 48, 62),
    gauge_needle=(0, 210, 255),
    gauge_needle_glow=(0, 230, 255),
    redzone=(255, 60, 60),
    arc_start=(0, 45, 90),
    arc_end=(0, 210, 255),
    side_bg=(18, 22, 34),
    side_border=(35, 42, 60),
    temp_cold=(60, 130, 210),
    temp_warm=(0, 190, 255),
    temp_hot=(255, 75, 55),
    fuel_ok=(0, 215, 115),
    fuel_low=(255, 75, 55),
    ok=(0, 215, 115),
    warning=(255, 200, 0),
    danger=(255, 60, 60),
    bottom_bg=(14, 16, 24),
    icon_color=(0, 180, 255),
    font="light",
    font_bold="light_bold",
)

OEM_DIGITAL = Theme(
    "oem_digital", "OEM Digital",
    bg=(8, 12, 20),
    bg_top=(14, 18, 30),
    bg_bot=(4, 7, 14),
    accent=(175, 188, 215),
    accent_dim=(110, 125, 155),
    accent_glow=(200, 210, 235),
    text=(218, 225, 242),
    text_dim=(95, 108, 135),
    text_mid=(150, 162, 190),
    status_bg=(12, 16, 28),
    status_line=(175, 188, 215),
    gauge_bg=(20, 26, 40),
    gauge_fg=(175, 188, 215),
    gauge_tick=(95, 108, 135),
    gauge_tick_dim=(50, 58, 76),
    gauge_needle=(220, 42, 42),
    gauge_needle_glow=(255, 60, 50),
    redzone=(200, 32, 32),
    arc_start=(45, 55, 85),
    arc_end=(180, 195, 225),
    side_bg=(16, 22, 36),
    side_border=(32, 40, 58),
    temp_cold=(75, 135, 195),
    temp_warm=(175, 188, 215),
    temp_hot=(220, 60, 42),
    fuel_ok=(95, 195, 105),
    fuel_low=(220, 60, 42),
    ok=(80, 200, 105),
    warning=(255, 192, 0),
    danger=(220, 42, 42),
    bottom_bg=(12, 16, 28),
    icon_color=(175, 188, 215),
    font="regular",
    font_bold="bold",
)

ALL_THEMES = [CLASSIC_ALFA, MODERN_DARK, OEM_DIGITAL]


# =========================================================================
#  COMMON CHROME — status bar + side gauges
# =========================================================================

# Layout constants (in SS-scaled pixels)
STATUS_H = 34  # status bar height (base)
SIDE_W = 52    # side gauge width (base)
BOTTOM_H = 0   # no separate bottom bar — info goes inside content
CONTENT_PAD = 8


def draw_status_bar(img, draw, theme, screen_label="A1"):
    """Top status bar matching PDF: date | consumption | screen+logo | icons."""
    s = SS
    sh = STATUS_H * s

    # Background
    rrect(draw, 0, 0, SW, sh, 0, fill=theme.status_bg)
    # Bottom accent line
    draw.line([(0, sh - s), (SW, sh - s)], fill=rgba(theme.accent, 120), width=s)

    f_date = _font(theme.font, 12 * s)
    f_label = _font(theme.font_bold, 11 * s)
    f_icon = _font(theme.font, 10 * s)

    # Left: date + time
    draw.text((10 * s, 9 * s), "23/03/26  13:04", font=f_date, fill=theme.text_mid)

    # Center-left: consumption
    text_centered(draw, SW * 0.28, 15 * s, "7.2 L/100km", f_date, theme.text_dim)

    # Center: screen label + "ALFA ROMEO" below
    text_centered(draw, SW // 2, 10 * s, screen_label, f_label, theme.accent)
    f_ar = _font(theme.font, 7 * s)
    text_centered(draw, SW // 2, 24 * s, "ALFA ROMEO 156", f_ar, rgba(theme.accent_dim, 150))

    # Right: status icons as text (BT, temp, weather hints)
    icons_x = SW - 14 * s
    text_right(draw, icons_x, 6 * s, "22.5°C", f_icon, theme.text_dim)
    text_right(draw, icons_x, 18 * s, "BT  AA", f_icon, rgba(theme.accent, 180))

    # Small weather icon hint
    f_wx = _font(theme.font, 9 * s)
    text_right(draw, icons_x - 70 * s, 11 * s, "❄", f_wx, rgba(theme.temp_cold, 160))


def draw_side_gauge_left(img, draw, theme, value=85, min_v=40, max_v=130):
    """Left vertical temperature bar gauge matching PDF layout."""
    s = SS
    sh = STATUS_H * s
    gw = SIDE_W * s
    gy = sh + 6 * s
    gh = SH - gy - 6 * s

    # Background panel
    rrect(draw, 3 * s, gy, gw, gh, 6 * s, fill=theme.side_bg)
    rrect(draw, 3 * s, gy, gw, gh, 6 * s, outline=rgba(theme.side_border, 100), width=s)

    # Labels
    f_lbl = _font(theme.font, 10 * s)
    text_centered(draw, 3 * s + gw // 2, gy + 10 * s, "°C", f_lbl, theme.text_dim)

    # Bar track
    bx = 3 * s + 14 * s
    bw = gw - 28 * s
    by = gy + 24 * s
    bh = gh - 52 * s
    rrect(draw, bx, by, bw, bh, 4 * s, fill=rgba(theme.bg, 200))

    # Fill
    frac = max(0, min(1, (value - min_v) / (max_v - min_v)))
    fill_h = int(frac * bh)
    if fill_h > 2:
        fy = by + bh - fill_h
        # Color gradient based on temperature
        if frac < 0.3:
            fc = theme.temp_cold
        elif frac < 0.7:
            fc = theme.temp_warm
        else:
            fc = theme.temp_hot
        for row in range(fill_h):
            row_f = row / max(fill_h - 1, 1)
            rc = lerp(rgba(fc, 100), fc, row_f)
            draw.line([(bx + 2 * s, fy + fill_h - 1 - row),
                       (bx + bw - 2 * s, fy + fill_h - 1 - row)], fill=rc)

    # Digital value in center of bar
    f_val = _font(theme.font_bold, 14 * s)
    text_centered(draw, 3 * s + gw // 2, by + bh // 2, f"{value}°", f_val, theme.text)

    # Min/max labels
    f_mm = _font(theme.font, 8 * s)
    text_centered(draw, 3 * s + gw // 2, by + bh + 8 * s, "C", f_mm, theme.temp_cold)
    text_centered(draw, 3 * s + gw // 2, by - 8 * s, "H", f_mm, theme.temp_hot)


def draw_side_gauge_right(img, draw, theme, value=62, min_v=0, max_v=100):
    """Right vertical fuel bar gauge matching PDF layout."""
    s = SS
    sh = STATUS_H * s
    gw = SIDE_W * s
    gx = SW - gw - 3 * s
    gy = sh + 6 * s
    gh = SH - gy - 6 * s

    # Background panel
    rrect(draw, gx, gy, gw, gh, 6 * s, fill=theme.side_bg)
    rrect(draw, gx, gy, gw, gh, 6 * s, outline=rgba(theme.side_border, 100), width=s)

    # Labels
    f_lbl = _font(theme.font, 10 * s)
    text_centered(draw, gx + gw // 2, gy + 10 * s, "FUEL", f_lbl, theme.text_dim)

    # Bar track
    bx = gx + 14 * s
    bw = gw - 28 * s
    by = gy + 24 * s
    bh = gh - 52 * s
    rrect(draw, bx, by, bw, bh, 4 * s, fill=rgba(theme.bg, 200))

    # Fill
    frac = max(0, min(1, (value - min_v) / (max_v - min_v)))
    fill_h = int(frac * bh)
    if fill_h > 2:
        fy = by + bh - fill_h
        fc = theme.fuel_ok if frac > 0.2 else theme.fuel_low
        for row in range(fill_h):
            row_f = row / max(fill_h - 1, 1)
            rc = lerp(rgba(fc, 100), fc, row_f)
            draw.line([(bx + 2 * s, fy + fill_h - 1 - row),
                       (bx + bw - 2 * s, fy + fill_h - 1 - row)], fill=rc)

    # Digital value
    f_val = _font(theme.font_bold, 14 * s)
    text_centered(draw, gx + gw // 2, by + bh // 2, f"{value}%", f_val, theme.text)

    # E/F labels
    f_mm = _font(theme.font, 8 * s)
    text_centered(draw, gx + gw // 2, by + bh + 8 * s, "E", f_mm, theme.fuel_low)
    text_centered(draw, gx + gw // 2, by - 8 * s, "F", f_mm, theme.fuel_ok)


def render_chrome(theme, screen_label="A1"):
    """Render common frame. Returns (img, draw, content_rect)."""
    s = SS
    img = Image.new("RGBA", (SW, SH), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Background gradient
    grad_rect(draw, 0, 0, SW, SH, theme.bg_top, theme.bg_bot)

    # Subtle radial vignette
    vig = Image.new("RGBA", (SW, SH), (0, 0, 0, 0))
    vd = ImageDraw.Draw(vig)
    max_r = int(math.hypot(SW, SH) / 2)
    for r in range(max_r, 0, -5 * s):
        a = int(45 * (1 - r / max_r) ** 1.6)
        vd.ellipse([SW // 2 - r, SH // 2 - r, SW // 2 + r, SH // 2 + r],
                   fill=(0, 0, 0, a))
    img = Image.alpha_composite(img, vig)
    draw = ImageDraw.Draw(img)

    # Status bar
    draw_status_bar(img, draw, theme, screen_label)
    # Side gauges
    draw_side_gauge_left(img, draw, theme)
    draw_side_gauge_right(img, draw, theme)

    # Content rect (between side gauges, below status bar)
    cx0 = (SIDE_W + CONTENT_PAD) * s
    cy0 = (STATUS_H + CONTENT_PAD) * s
    cw = SW - 2 * cx0
    ch = SH - cy0 - CONTENT_PAD * s

    return img, draw, (cx0, cy0, cw, ch)


# =========================================================================
#  A1 — MAIN DASHBOARD: RPM (left) + Speedometer (right)
# =========================================================================

def draw_round_gauge(img, draw, theme, cx, cy, radius,
                     value, max_val, num_major, num_label_fn,
                     unit_text="", redzone_start=None,
                     start_angle=225, sweep_angle=270):
    """Draw a classic analog round gauge with arc, ticks, numbers, needle."""
    s = SS
    arc_w = 14 * s
    frac = max(0, min(1, value / max_val))

    # --- Outer glow ---
    val_sweep = frac * sweep_angle
    img2 = glow_arc(img, cx, cy, radius, arc_w, start_angle, val_sweep,
                    theme.accent_glow, alpha=25, blur_r=14 * s)
    draw2 = ImageDraw.Draw(img2)

    # --- Gauge face circle (subtle) ---
    face_r = radius + 8 * s
    draw2.ellipse([cx - face_r, cy - face_r, cx + face_r, cy + face_r],
                  fill=rgba(theme.gauge_bg, 60))
    # Outer ring
    draw2.ellipse([cx - face_r, cy - face_r, cx + face_r, cy + face_r],
                  outline=rgba(theme.gauge_tick_dim, 50), width=s)

    # --- Background arc ---
    thick_arc(draw2, cx, cy, radius, arc_w, start_angle, sweep_angle,
              theme.gauge_bg, theme.gauge_bg)

    # --- Inner thin ring ---
    thick_arc(draw2, cx, cy, radius - arc_w, s, start_angle, sweep_angle,
              rgba(theme.gauge_tick_dim, 50))

    # --- Redzone ---
    if redzone_start is not None:
        rz_frac = redzone_start / max_val
        rz_deg_start = start_angle - rz_frac * sweep_angle
        rz_sweep = (1.0 - rz_frac) * sweep_angle
        thick_arc(draw2, cx, cy, radius, arc_w, rz_deg_start, rz_sweep,
                  rgba(theme.redzone, 55), theme.redzone)

    # --- Value arc (gradient) ---
    thick_arc(draw2, cx, cy, radius, arc_w, start_angle, val_sweep,
              theme.arc_start, theme.arc_end)

    # --- Tick marks + numbers ---
    f_num = _font(theme.font, 13 * s)
    for i in range(num_major + 1):
        tf = i / num_major
        ad = start_angle - tf * sweep_angle
        ar = math.radians(ad)

        # Major tick
        inner = radius - arc_w - 2 * s
        outer = radius + 3 * s
        draw2.line([(cx + inner * math.cos(ar), cy - inner * math.sin(ar)),
                    (cx + outer * math.cos(ar), cy - outer * math.sin(ar))],
                   fill=theme.gauge_tick, width=2 * s)

        # Number
        label = num_label_fn(i)
        if label is not None:
            nr = radius + 18 * s
            text_centered(draw2,
                          cx + nr * math.cos(ar),
                          cy - nr * math.sin(ar),
                          str(label), f_num, theme.text_mid)

    # --- Minor ticks ---
    minor_count = num_major * 5
    for i in range(minor_count + 1):
        if i % 5 == 0:
            continue
        tf = i / minor_count
        ar = math.radians(start_angle - tf * sweep_angle)
        inner = radius - arc_w + 4 * s
        outer = radius + 1 * s
        draw2.line([(cx + inner * math.cos(ar), cy - inner * math.sin(ar)),
                    (cx + outer * math.cos(ar), cy - outer * math.sin(ar))],
                   fill=theme.gauge_tick_dim, width=s)

    # --- Needle with glow ---
    na = start_angle - frac * sweep_angle
    needle_len = radius - arc_w - 8 * s

    # Glow layer
    ng = Image.new("RGBA", img2.size, (0, 0, 0, 0))
    ngd = ImageDraw.Draw(ng)
    draw_needle(ngd, cx, cy, na, needle_len, 12 * s,
                rgba(theme.gauge_needle_glow, 50))
    ng = ng.filter(ImageFilter.GaussianBlur(6 * s))
    img2 = Image.alpha_composite(img2, ng)
    draw2 = ImageDraw.Draw(img2)

    # Needle
    draw_needle(draw2, cx, cy, na, needle_len, 7 * s, theme.gauge_needle)

    # Center cap
    for cr, cc in [(8 * s, rgba(theme.gauge_needle, 160)),
                   (6 * s, theme.gauge_needle),
                   (3 * s, theme.bg)]:
        draw2.ellipse([cx - cr, cy - cr, cx + cr, cy + cr], fill=cc)

    # --- Unit text below center ---
    if unit_text:
        f_unit = _font(theme.font, 10 * s)
        text_centered(draw2, cx, cy + radius * 0.45, unit_text, f_unit, theme.text_dim)

    return img2, draw2


def render_a1_dashboard(theme):
    """A1: Two round gauges — RPM (left) + Speedometer (right)."""
    s = SS
    img, draw, (cx0, cy0, cw, ch) = render_chrome(theme, "A1  DASHBOARD")

    content_cx = cx0 + cw // 2
    content_cy = cy0 + ch // 2

    # Two gauges side by side
    gauge_r = min(cw // 4 - 14 * s, ch // 2 - 30 * s)
    gap = 20 * s

    # RPM gauge — left
    rpm_cx = content_cx - gauge_r - gap
    rpm_cy = content_cy - 8 * s
    rpm_val = 2800
    rpm_max = 7000

    def rpm_label(i):
        return i  # 0,1,2,3,4,5,6,7

    img, draw = draw_round_gauge(
        img, draw, theme, rpm_cx, rpm_cy, gauge_r,
        rpm_val, rpm_max, num_major=7,
        num_label_fn=rpm_label,
        unit_text="RPM ×1000",
        redzone_start=5500,
    )

    # Speed gauge — right
    spd_cx = content_cx + gauge_r + gap
    spd_cy = content_cy - 8 * s
    spd_val = 87
    spd_max = 260

    def spd_label(i):
        v = i * 20
        return v if v % 40 == 0 else None  # 0,40,80,120,160,200,240

    img, draw = draw_round_gauge(
        img, draw, theme, spd_cx, spd_cy, gauge_r,
        spd_val, spd_max, num_major=13,
        num_label_fn=spd_label,
        unit_text="km/h",
        redzone_start=220,
    )

    # Large speed value between the two gauges
    f_spd = _font(theme.font_bold, 48 * s)
    text_centered(draw, content_cx, content_cy - 20 * s, "87", f_spd, theme.text)
    f_unit = _font(theme.font, 14 * s)
    text_centered(draw, content_cx, content_cy + 20 * s, "km/h", f_unit, theme.text_dim)

    # Gear indicator below
    f_gear = _font(theme.font_bold, 28 * s)
    text_centered(draw, content_cx, content_cy + 52 * s, "3", f_gear, theme.accent)
    f_gl = _font(theme.font, 10 * s)
    text_centered(draw, content_cx, content_cy + 72 * s, "GEAR", f_gl, theme.text_dim)

    return img.resize((W, H), Image.LANCZOS)


# =========================================================================
#  MAIN — Phase 1 only renders A1
# =========================================================================

def main():
    import sys
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    screens = [
        ("a1_dashboard", render_a1_dashboard),
    ]

    for theme in ALL_THEMES:
        for sid, render_fn in screens:
            label = f"{theme.display_name} / {sid}"
            print(f"Rendering {label} ...")
            img = render_fn(theme)
            path = os.path.join(OUTPUT_DIR, f"mockup_{sid}_{theme.name}.png")
            img.save(path, "PNG", optimize=True)
            print(f"  -> {path}")

    print("Phase 1 done!")


if __name__ == "__main__":
    main()
