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
#  A2 — CONSUMPTION: Fuel pump icon + consumption/distance/range rows
# =========================================================================

def draw_fuel_pump_icon(draw, cx, cy, size, theme):
    """Draw a stylized fuel pump icon."""
    s = SS
    sz = size * s
    color = theme.accent
    dim = rgba(theme.accent, 120)

    # Pump body (rounded rect)
    bw, bh = int(sz * 0.55), int(sz * 0.7)
    bx, by = cx - bw // 2, cy - bh // 2 + int(sz * 0.05)
    rrect(draw, bx, by, bw, bh, 8 * s, fill=rgba(theme.gauge_bg, 180),
          outline=color, width=2 * s)

    # Fuel level inside (partial fill)
    fill_h = int(bh * 0.55)
    fy = by + bh - fill_h - 3 * s
    rrect(draw, bx + 4 * s, fy, bw - 8 * s, fill_h, 4 * s,
          fill=rgba(color, 60))

    # Nozzle on top
    nw = int(bw * 0.35)
    nh = int(sz * 0.15)
    nx = cx - nw // 2
    ny = by - nh
    rrect(draw, nx, ny, nw, nh + 4 * s, 3 * s, fill=rgba(theme.gauge_bg, 200),
          outline=color, width=2 * s)

    # Hose from top-right, curving right and down
    hx = bx + bw
    hy = by + int(bh * 0.15)
    # Vertical line up
    draw.line([(hx, hy), (hx + 12 * s, hy)], fill=dim, width=2 * s)
    draw.line([(hx + 12 * s, hy), (hx + 12 * s, hy + int(bh * 0.5))],
              fill=dim, width=2 * s)
    # Nozzle tip
    draw.line([(hx + 12 * s, hy + int(bh * 0.5)),
               (hx + 6 * s, hy + int(bh * 0.65))],
              fill=dim, width=2 * s)

    # Base
    base_w = int(bw * 1.1)
    draw.line([(cx - base_w // 2, by + bh + 2 * s),
               (cx + base_w // 2, by + bh + 2 * s)],
              fill=color, width=3 * s)


def draw_info_row(draw, x, y, w, label, value, unit, theme, f_label, f_value, f_unit,
                  value_color=None):
    """Draw a labeled info row: LABEL ........................ VALUE UNIT"""
    s = SS
    if value_color is None:
        value_color = theme.text

    draw.text((x, y + 2 * s), label, font=f_label, fill=theme.text_dim)

    # Value + unit right-aligned
    unit_text = f" {unit}" if unit else ""
    vbb = draw.textbbox((0, 0), value, font=f_value)
    ubb = draw.textbbox((0, 0), unit_text, font=f_unit) if unit_text else (0, 0, 0, 0)
    vw = vbb[2] - vbb[0]
    uw = ubb[2] - ubb[0]
    vx = x + w - vw - uw
    draw.text((vx, y), value, font=f_value, fill=value_color)
    if unit_text:
        draw.text((vx + vw, y + 6 * s), unit_text, font=f_unit, fill=theme.text_dim)

    # Dotted separator line
    lbb = draw.textbbox((0, 0), label, font=f_label)
    lw = lbb[2] - lbb[0]
    dot_x0 = x + lw + 8 * s
    dot_x1 = vx - 8 * s
    dot_y = y + 14 * s
    for dx in range(int(dot_x0), int(dot_x1), 6 * s):
        draw.ellipse([dx, dot_y, dx + s, dot_y + s],
                     fill=rgba(theme.text_dim, 60))


def render_a2_consumption(theme):
    """A2: Fuel pump icon + avg/instant consumption + distance + range."""
    s = SS
    img, draw, (cx0, cy0, cw, ch) = render_chrome(theme, "A2  CONSUMPTION")

    # Left half: fuel pump icon
    icon_cx = cx0 + cw * 3 // 10
    icon_cy = cy0 + ch // 3
    draw_fuel_pump_icon(draw, icon_cx, icon_cy, 80, theme)

    # Right section: consumption values near the icon
    f_big = _font(theme.font_bold, 42 * s)
    f_med = _font(theme.font_bold, 26 * s)
    f_lbl = _font(theme.font, 13 * s)
    f_unit = _font(theme.font, 12 * s)

    # Average consumption — large, right of icon
    avg_x = cx0 + cw * 0.52
    avg_y = cy0 + 20 * s
    draw.text((avg_x, avg_y), "ŚR. SPALANIE", font=f_lbl, fill=theme.text_dim)
    draw.text((avg_x, avg_y + 18 * s), "8.5", font=f_big, fill=theme.text)
    bw = draw.textbbox((0, 0), "8.5", font=f_big)[2]
    draw.text((avg_x + bw + 6 * s, avg_y + 36 * s), "L/100km",
              font=f_unit, fill=theme.text_dim)

    # Instant consumption
    inst_y = avg_y + 72 * s
    draw.text((avg_x, inst_y), "CHW. SPALANIE", font=f_lbl, fill=theme.text_dim)
    draw.text((avg_x, inst_y + 18 * s), "12.4", font=f_med, fill=theme.accent)
    bw2 = draw.textbbox((0, 0), "12.4", font=f_med)[2]
    draw.text((avg_x + bw2 + 6 * s, inst_y + 24 * s), "L/100km",
              font=f_unit, fill=theme.text_dim)

    # Bottom rows with dotted separators — spanning full content width
    row_x = cx0 + 20 * s
    row_w = cw - 40 * s
    f_row_lbl = _font(theme.font, 14 * s)
    f_row_val = _font(theme.font_bold, 22 * s)
    f_row_unit = _font(theme.font, 12 * s)

    # Separator line
    sep_y = cy0 + ch * 0.58
    draw.line([(row_x, sep_y), (row_x + row_w, sep_y)],
              fill=rgba(theme.accent, 40), width=s)

    # Row 1: Distance traveled
    ry1 = cy0 + ch * 0.62
    draw_info_row(draw, row_x, ry1, row_w,
                  "PRZEJECHANY DYSTANS", "127.4", "km",
                  theme, f_row_lbl, f_row_val, f_row_unit)

    # Row 2: Range
    ry2 = ry1 + 40 * s
    draw_info_row(draw, row_x, ry2, row_w,
                  "ZASIĘG", "412", "km",
                  theme, f_row_lbl, f_row_val, f_row_unit,
                  value_color=theme.ok)

    # Row 3: Trip time
    ry3 = ry2 + 40 * s
    draw_info_row(draw, row_x, ry3, row_w,
                  "CZAS JAZDY", "01:42", "h",
                  theme, f_row_lbl, f_row_val, f_row_unit)

    return img.resize((W, H), Image.LANCZOS)


# =========================================================================
#  A3 — ENVIRONMENT: Thermometer + weather icons + temp/humidity/icing/pressure
# =========================================================================

def draw_thermometer_icon(draw, cx, cy, height, theme):
    """Draw a stylized thermometer icon."""
    s = SS
    h = height * s
    color = theme.accent
    w = int(h * 0.18)

    # Stem (tall narrow rect)
    stem_h = int(h * 0.65)
    stem_x = cx - w // 2
    stem_y = cy - h // 2
    rrect(draw, stem_x, stem_y, w, stem_h + w // 2, w // 2,
          fill=rgba(theme.gauge_bg, 180), outline=color, width=2 * s)

    # Mercury fill inside stem
    fill_h = int(stem_h * 0.6)
    fy = stem_y + stem_h - fill_h
    merc_w = w - 6 * s
    rrect(draw, cx - merc_w // 2, fy, merc_w, fill_h + w // 2, merc_w // 2,
          fill=rgba(theme.temp_hot, 180))

    # Bulb at bottom
    bulb_r = int(w * 0.9)
    bulb_cy = stem_y + stem_h + bulb_r - 2 * s
    draw.ellipse([cx - bulb_r, bulb_cy - bulb_r,
                  cx + bulb_r, bulb_cy + bulb_r],
                 fill=rgba(theme.temp_hot, 200),
                 outline=color, width=2 * s)

    # Tick marks on stem
    for i in range(5):
        ty = stem_y + 8 * s + i * (stem_h - 16 * s) // 4
        tw = w // 3
        draw.line([(stem_x - tw, ty), (stem_x, ty)],
                  fill=rgba(color, 100), width=s)


def draw_weather_icons_grid(draw, x, y, w, h, theme):
    """Draw a grid of weather-related icons using drawing primitives."""
    s = SS
    color = theme.icon_color
    dim = rgba(theme.icon_color, 100)
    cols, rows = 4, 2
    cell_w = w // cols
    cell_h = h // rows

    icons = [
        ("sun", theme.warning),
        ("cloud_sun", theme.text_mid),
        ("cloud", theme.text_dim),
        ("rain", theme.temp_cold),
        ("snow", (200, 220, 255)),
        ("fog", theme.text_dim),
        ("temp", theme.temp_hot),
        ("wind", theme.accent),
    ]

    for idx, (icon_type, ic) in enumerate(icons):
        col = idx % cols
        row = idx // cols
        icx = x + col * cell_w + cell_w // 2
        icy = y + row * cell_h + cell_h // 2
        ir = 14 * s

        if icon_type == "sun":
            # Circle + rays
            draw.ellipse([icx - ir // 2, icy - ir // 2,
                          icx + ir // 2, icy + ir // 2], fill=ic)
            for a in range(0, 360, 45):
                ar = math.radians(a)
                r1, r2 = ir * 0.7, ir * 1.1
                draw.line([(icx + r1 * math.cos(ar), icy - r1 * math.sin(ar)),
                           (icx + r2 * math.cos(ar), icy - r2 * math.sin(ar))],
                          fill=ic, width=2 * s)

        elif icon_type == "cloud_sun":
            # Small sun behind
            sx, sy = icx - 6 * s, icy - 6 * s
            draw.ellipse([sx - 5 * s, sy - 5 * s, sx + 5 * s, sy + 5 * s],
                         fill=rgba(theme.warning, 150))
            # Cloud in front
            draw.ellipse([icx - 10 * s, icy - 5 * s, icx + 10 * s, icy + 6 * s],
                         fill=ic)
            draw.ellipse([icx - 4 * s, icy - 10 * s, icx + 8 * s, icy],
                         fill=ic)

        elif icon_type == "cloud":
            draw.ellipse([icx - 12 * s, icy - 4 * s, icx + 12 * s, icy + 8 * s],
                         fill=ic)
            draw.ellipse([icx - 5 * s, icy - 10 * s, icx + 8 * s, icy + 2 * s],
                         fill=ic)

        elif icon_type == "rain":
            # Cloud
            draw.ellipse([icx - 10 * s, icy - 8 * s, icx + 10 * s, icy],
                         fill=rgba(theme.text_dim, 180))
            # Rain drops
            for dx in [-6, 0, 6]:
                draw.line([(icx + dx * s, icy + 3 * s),
                           (icx + dx * s - 2 * s, icy + 10 * s)],
                          fill=ic, width=2 * s)

        elif icon_type == "snow":
            # Snowflake — 3 crossing lines + dots
            for a in [0, 60, 120]:
                ar = math.radians(a)
                draw.line([(icx - ir * 0.8 * math.cos(ar), icy - ir * 0.8 * math.sin(ar)),
                           (icx + ir * 0.8 * math.cos(ar), icy + ir * 0.8 * math.sin(ar))],
                          fill=ic, width=2 * s)
            draw.ellipse([icx - 3 * s, icy - 3 * s, icx + 3 * s, icy + 3 * s],
                         fill=ic)

        elif icon_type == "fog":
            # Horizontal lines
            for i in range(-2, 3):
                lw = ir * (1.0 - abs(i) * 0.15)
                ly = icy + i * 5 * s
                draw.line([(icx - lw, ly), (icx + lw, ly)],
                          fill=rgba(ic, 140 - abs(i) * 20), width=2 * s)

        elif icon_type == "temp":
            # Mini thermometer
            draw.line([(icx, icy - ir), (icx, icy + ir * 0.4)],
                      fill=ic, width=3 * s)
            draw.ellipse([icx - 5 * s, icy + ir * 0.2,
                          icx + 5 * s, icy + ir * 0.2 + 10 * s],
                         fill=ic)

        elif icon_type == "wind":
            # Curved lines
            for i, dy in enumerate([-5, 0, 5]):
                ww = ir * (1.0 - i * 0.1)
                wy = icy + dy * s
                pts = [(icx - ww, wy)]
                for t in range(1, 6):
                    px = icx - ww + t * ww * 0.4
                    py = wy + math.sin(t * 1.2) * 3 * s
                    pts.append((px, py))
                for j in range(len(pts) - 1):
                    draw.line([pts[j], pts[j + 1]], fill=ic, width=2 * s)

        # Label below icon
        f_il = _font(theme.font, 7 * s)
        labels = {"sun": "SŁOŃCE", "cloud_sun": "ZACHM.", "cloud": "POCHMURNO",
                  "rain": "DESZCZ", "snow": "ŚNIEG", "fog": "MGŁA",
                  "temp": "°C / °F", "wind": "WIATR"}
        text_centered(draw, icx, icy + ir + 8 * s,
                      labels.get(icon_type, ""), f_il, rgba(theme.text_dim, 120))


def render_a3_environment(theme):
    """A3: Thermometer + weather icons + environment data rows."""
    s = SS
    img, draw, (cx0, cy0, cw, ch) = render_chrome(theme, "A3  ENVIRONMENT")

    # Left side: thermometer icon
    therm_cx = cx0 + cw * 0.12
    therm_cy = cy0 + ch * 0.35
    draw_thermometer_icon(draw, int(therm_cx), int(therm_cy), 100, theme)

    # Environment data rows — left column below thermometer
    f_lbl = _font(theme.font, 13 * s)
    f_val = _font(theme.font_bold, 20 * s)
    f_unit = _font(theme.font, 11 * s)

    row_x = cx0 + 20 * s
    row_w = cw * 0.42
    base_y = cy0 + ch * 0.58

    # Row 1: Temperature + Humidity
    draw.text((row_x, base_y), "TEMP. + WILGOTNOŚĆ ZEW.", font=f_lbl, fill=theme.text_dim)
    draw.text((row_x + 12 * s, base_y + 20 * s), "+7°C", font=f_val, fill=theme.text)
    bw = draw.textbbox((0, 0), "+7°C", font=f_val)[2]
    draw.text((row_x + 12 * s + bw + 10 * s, base_y + 26 * s), "65%",
              font=f_val, fill=theme.accent)

    # Row 2: Icing risk
    ry2 = base_y + 52 * s
    draw.text((row_x, ry2), "RYZYKO OBLODZENIA", font=f_lbl, fill=theme.text_dim)
    draw.text((row_x + 12 * s, ry2 + 20 * s), "NISKIE", font=f_val, fill=theme.ok)

    # Row 3: Atmospheric pressure
    ry3 = ry2 + 52 * s
    draw.text((row_x, ry3), "CIŚNIENIE ATMOSF.", font=f_lbl, fill=theme.text_dim)
    draw.text((row_x + 12 * s, ry3 + 20 * s), "1013", font=f_val, fill=theme.text)
    bw3 = draw.textbbox((0, 0), "1013", font=f_val)[2]
    draw.text((row_x + 12 * s + bw3 + 4 * s, ry3 + 26 * s), "hPa",
              font=f_unit, fill=theme.text_dim)

    # Separator between left info and right icon grid
    sep_x = cx0 + cw * 0.48
    draw.line([(sep_x, cy0 + 16 * s), (sep_x, cy0 + ch - 16 * s)],
              fill=rgba(theme.accent, 35), width=s)

    # Right side: weather icons grid
    grid_x = cx0 + cw * 0.52
    grid_y = cy0 + 14 * s
    grid_w = cw * 0.45
    grid_h = ch - 28 * s
    draw_weather_icons_grid(draw, int(grid_x), int(grid_y),
                            int(grid_w), int(grid_h), theme)

    # Subtitle under icon grid
    f_note = _font(theme.font, 9 * s)
    text_centered(draw, int(grid_x + grid_w // 2), int(cy0 + ch - 10 * s),
                  "Ikony zmieniają się wg warunków", f_note,
                  rgba(theme.text_dim, 100))

    return img.resize((W, H), Image.LANCZOS)


# =========================================================================
#  A4 — SERVICE: Next service, TPMS, pressure + error codes + wrench icon
# =========================================================================

def draw_wrench_icon(draw, cx, cy, size, theme):
    """Draw a crossed wrench + screwdriver service icon."""
    s = SS
    sz = size * s
    color = theme.accent
    dim = rgba(theme.accent, 140)

    # Wrench (left-leaning \)
    angle1 = math.radians(45)
    half = sz * 0.45
    # Shaft
    x1 = cx - half * math.cos(angle1)
    y1 = cy - half * math.sin(angle1)
    x2 = cx + half * math.cos(angle1)
    y2 = cy + half * math.sin(angle1)
    draw.line([(x1, y1), (x2, y2)], fill=color, width=4 * s)

    # Wrench head (top-left)
    hr = 8 * s
    draw.arc([x1 - hr, y1 - hr, x1 + hr, y1 + hr],
             start=180 + 45, end=360 + 45, fill=color, width=4 * s)
    # Wrench head (bottom-right)
    draw.arc([x2 - hr, y2 - hr, x2 + hr, y2 + hr],
             start=45, end=180 + 45, fill=color, width=4 * s)

    # Screwdriver (right-leaning /)
    angle2 = math.radians(-45)
    x3 = cx - half * math.cos(angle2)
    y3 = cy - half * math.sin(angle2)
    x4 = cx + half * math.cos(angle2)
    y4 = cy + half * math.sin(angle2)
    draw.line([(x3, y3), (x4, y4)], fill=dim, width=4 * s)

    # Screwdriver tip (top-right) — flat head
    tip_len = 6 * s
    draw.line([(x3, y3),
               (x3 - tip_len * math.cos(angle2 + math.pi / 2),
                y3 - tip_len * math.sin(angle2 + math.pi / 2))],
              fill=dim, width=3 * s)
    draw.line([(x3, y3),
               (x3 + tip_len * math.cos(angle2 + math.pi / 2),
                y3 + tip_len * math.sin(angle2 + math.pi / 2))],
              fill=dim, width=3 * s)

    # Handle (bottom-left)
    hx, hy = x4, y4
    hw = 5 * s
    hl = 12 * s
    perp = angle2 + math.pi / 2
    p1 = (hx + hw * math.cos(perp), hy + hw * math.sin(perp))
    p2 = (hx - hw * math.cos(perp), hy - hw * math.sin(perp))
    p3 = (hx - hw * math.cos(perp) + hl * math.cos(angle2),
          hy - hw * math.sin(perp) + hl * math.sin(angle2))
    p4 = (hx + hw * math.cos(perp) + hl * math.cos(angle2),
          hy + hw * math.sin(perp) + hl * math.sin(angle2))
    draw.polygon([p1, p2, p3, p4], fill=rgba(color, 100))

    # Center bolt
    draw.ellipse([cx - 4 * s, cy - 4 * s, cx + 4 * s, cy + 4 * s],
                 fill=theme.bg, outline=color, width=2 * s)


def render_a4_service(theme):
    """A4: Service info (left) + error codes (right) + wrench icon."""
    s = SS
    img, draw, (cx0, cy0, cw, ch) = render_chrome(theme, "A4  SERVICE")

    # --- Left column: service info ---
    lx = cx0 + 20 * s
    col_w = cw * 0.45

    f_lbl = _font(theme.font, 13 * s)
    f_val = _font(theme.font_bold, 22 * s)
    f_unit = _font(theme.font, 11 * s)

    # Section title
    f_sect = _font(theme.font_bold, 12 * s)
    ry = cy0 + 16 * s
    draw.text((lx, ry), "INFORMACJE SERWISOWE", font=f_sect, fill=theme.accent)
    ry += 28 * s

    # Separator
    draw.line([(lx, ry), (lx + col_w - 20 * s, ry)],
              fill=rgba(theme.accent, 50), width=s)
    ry += 12 * s

    # Row: Next service
    draw.text((lx + 10 * s, ry), "NASTĘPNY SERWIS:", font=f_lbl, fill=theme.text_dim)
    ry += 20 * s
    draw.text((lx + 16 * s, ry), "4 500", font=f_val, fill=theme.ok)
    bw = draw.textbbox((0, 0), "4 500", font=f_val)[2]
    draw.text((lx + 16 * s + bw + 6 * s, ry + 6 * s), "km", font=f_unit, fill=theme.text_dim)
    ry += 38 * s

    # Row: TPMS sensors
    draw.text((lx + 10 * s, ry), "CZUJNIKI TPMS:", font=f_lbl, fill=theme.text_dim)
    ry += 20 * s

    # TPMS grid (2x2)
    tpms_vals = [("FL", "2.3"), ("FR", "2.3"), ("RL", "2.1"), ("RR", "2.1")]
    f_tpms_lbl = _font(theme.font, 10 * s)
    f_tpms_val = _font(theme.font_bold, 16 * s)
    for i, (pos, pressure) in enumerate(tpms_vals):
        col = i % 2
        row = i // 2
        tx = lx + 16 * s + col * 80 * s
        ty = ry + row * 34 * s
        draw.text((tx, ty), pos, font=f_tpms_lbl, fill=theme.text_dim)
        draw.text((tx + 22 * s, ty - 2 * s), pressure, font=f_tpms_val, fill=theme.text)
        draw.text((tx + 22 * s + draw.textbbox((0, 0), pressure, font=f_tpms_val)[2] + 2 * s,
                   ty + 4 * s), "bar", font=f_tpms_lbl, fill=theme.text_dim)
    ry += 76 * s

    # Row: Atmospheric pressure
    draw.text((lx + 10 * s, ry), "CIŚNIENIE ATMOSF.:", font=f_lbl, fill=theme.text_dim)
    ry += 20 * s
    draw.text((lx + 16 * s, ry), "1013", font=f_val, fill=theme.text)
    bw4 = draw.textbbox((0, 0), "1013", font=f_val)[2]
    draw.text((lx + 16 * s + bw4 + 4 * s, ry + 6 * s), "hPa",
              font=f_unit, fill=theme.text_dim)

    # --- Vertical separator ---
    sep_x = cx0 + cw * 0.48
    draw.line([(sep_x, cy0 + 16 * s), (sep_x, cy0 + ch - 16 * s)],
              fill=rgba(theme.accent, 35), width=s)

    # --- Right column: error codes + wrench icon ---
    rx = cx0 + cw * 0.52
    rw = cw * 0.45

    f_sect2 = _font(theme.font_bold, 12 * s)
    ery = cy0 + 16 * s
    draw.text((rx, ery), "BŁĘDY STEROWNIKA", font=f_sect2, fill=theme.accent)
    ery += 28 * s
    draw.line([(rx, ery), (rx + rw - 10 * s, ery)],
              fill=rgba(theme.accent, 50), width=s)
    ery += 12 * s

    # Error code list
    f_err = _font(theme.font, 12 * s)
    f_err_code = _font(theme.font_bold, 13 * s)
    errors = [
        ("P0100", "MAF sensor circuit"),
        ("P0340", "CMP sensor A circuit"),
        ("P1130", "Swirl flap actuator"),
    ]
    for code, desc in errors:
        # Colored dot
        draw.ellipse([rx + 4 * s, ery + 4 * s, rx + 10 * s, ery + 10 * s],
                     fill=theme.warning)
        draw.text((rx + 16 * s, ery), code, font=f_err_code, fill=theme.warning)
        cw_code = draw.textbbox((0, 0), code, font=f_err_code)[2]
        draw.text((rx + 16 * s + cw_code + 6 * s, ery + 1 * s), desc,
                  font=f_err, fill=theme.text_dim)
        ery += 22 * s

    # "Brak krytycznych" (no critical) status
    ery += 8 * s
    f_status = _font(theme.font_bold, 14 * s)
    draw.text((rx + 4 * s, ery), "Brak krytycznych błędów", font=f_status, fill=theme.ok)

    # Wrench icon — bottom right of right column
    wrench_cx = int(rx + rw * 0.5)
    wrench_cy = int(cy0 + ch * 0.78)
    draw_wrench_icon(draw, wrench_cx, wrench_cy, 55, theme)

    return img.resize((W, H), Image.LANCZOS)


# =========================================================================
#  MAIN — All 4 screens × 3 themes
# =========================================================================

ALL_SCREENS = [
    ("a1_dashboard",   render_a1_dashboard),
    ("a2_consumption", render_a2_consumption),
    ("a3_environment", render_a3_environment),
    ("a4_service",     render_a4_service),
]


def main():
    import sys
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    total = len(ALL_THEMES) * len(ALL_SCREENS)
    n = 0
    for theme in ALL_THEMES:
        for sid, render_fn in ALL_SCREENS:
            n += 1
            label = f"[{n}/{total}] {theme.display_name} / {sid}"
            print(f"Rendering {label} ...")
            img = render_fn(theme)
            path = os.path.join(OUTPUT_DIR, f"mockup_{sid}_{theme.name}.png")
            img.save(path, "PNG", optimize=True)
            print(f"  -> {path}")

    print(f"\nDone! {total} mockups generated.")


if __name__ == "__main__":
    main()
