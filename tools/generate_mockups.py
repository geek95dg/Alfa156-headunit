#!/usr/bin/env python3
"""Generate high-quality PNG mockups of the BCM dashboard for all 3 themes.

Uses Pillow with 3x supersampling for smooth anti-aliased arcs, soft glow
effects, gradient fills, and classical ornamental drawings.
"""

import math
import os
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 800, 480
SS = 3
SW, SH = W * SS, H * SS
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "mockups")

_font_cache = {}
FONT_PATHS = {
    "regular": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "bold": "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "serif": "/usr/share/fonts/truetype/freefont/FreeSerif.ttf",
    "serif_bold": "/usr/share/fonts/truetype/freefont/FreeSerifBoldItalic.ttf",
    "light": "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
}


def _font(variant, size):
    key = (variant, size)
    if key not in _font_cache:
        path = FONT_PATHS.get(variant, FONT_PATHS["regular"])
        _font_cache[key] = ImageFont.truetype(path, size)
    return _font_cache[key]


def lerp(c1, c2, t):
    t = max(0.0, min(1.0, t))
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def rgba(color, alpha):
    return (*color[:3], alpha)


def text_centered(draw, x, y, text, font, fill):
    bb = font.getbbox(text)
    draw.text((x - (bb[2] - bb[0]) / 2, y - (bb[3] - bb[1]) / 2), text, font=font, fill=fill)


def draw_grad_rect(draw, x, y, w, h, c_top, c_bot):
    for row in range(h):
        draw.line([(x, y + row), (x + w - 1, y + row)], fill=lerp(c_top, c_bot, row / max(h - 1, 1)))


def draw_rrect(draw, x, y, w, h, r, **kw):
    r = min(r, w // 2, h // 2)
    draw.rounded_rectangle([x, y, x + w, y + h], radius=r, **kw)


def draw_thick_arc(draw, cx, cy, radius, width, start_deg, sweep_deg,
                   c_start, c_end=None, segments=100):
    if sweep_deg <= 0 or radius <= 0:
        return
    if c_end is None:
        c_end = c_start
    step = sweep_deg / segments
    for i in range(segments):
        c = lerp(c_start, c_end, i / segments)
        a1 = math.radians(start_deg - i * step)
        a2 = math.radians(start_deg - (i + 1) * step)
        draw.polygon([
            (cx + radius * math.cos(a1), cy - radius * math.sin(a1)),
            (cx + radius * math.cos(a2), cy - radius * math.sin(a2)),
            (cx + (radius - width) * math.cos(a2), cy - (radius - width) * math.sin(a2)),
            (cx + (radius - width) * math.cos(a1), cy - (radius - width) * math.sin(a1)),
        ], fill=c)


def draw_glow_arc(img, cx, cy, radius, width, start_deg, sweep_deg,
                  color, alpha=35, blur=None):
    s = SS
    if blur is None:
        blur = 15 * s
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    draw_thick_arc(gd, cx, cy, radius + width, width * 3,
                   start_deg, sweep_deg, rgba(color, alpha), rgba(color, alpha))
    glow = glow.filter(ImageFilter.GaussianBlur(blur))
    img.paste(Image.alpha_composite(Image.new("RGBA", img.size, (0, 0, 0, 0)), glow), mask=glow)


def draw_needle(draw, cx, cy, angle_deg, length, base_w, color):
    a = math.radians(angle_deg)
    tip = (cx + length * math.cos(a), cy - length * math.sin(a))
    p = a + math.pi / 2
    bw = base_w / 2
    b1 = (cx + bw * math.cos(p), cy - bw * math.sin(p))
    b2 = (cx - bw * math.cos(p), cy + bw * math.sin(p))
    tail = (cx - length * 0.12 * math.cos(a), cy + length * 0.12 * math.sin(a))
    draw.polygon([b1, tip, b2, tail], fill=color)


# ---------------------------------------------------------------------------
# Classical ornaments for Classic Alfa
# ---------------------------------------------------------------------------

def draw_classical_ornaments(img, draw, theme):
    s = SS
    c = theme.accent_soft
    cd = rgba(theme.accent_soft, 120)

    # Large laurel wreath around the tachometer
    cx, cy = SW // 2, SH // 2 - 20 * s
    _draw_laurel_wreath(draw, cx, cy, 195 * s, s, c)

    # Corner flourishes
    for sx_sign, sy_sign in [(-1, -1), (1, -1), (-1, 1), (1, 1)]:
        _draw_corner_flourish(draw,
                              SW // 2 + sx_sign * 320 * s,
                              SH // 2 + sy_sign * 180 * s,
                              s, cd, sx_sign, sy_sign)

    # Decorative divider line above bottom bar with classical pattern
    by = SH - 40 * s
    _draw_classical_divider(draw, 60 * s, by, SW - 120 * s, s, rgba(c, 90))

    # "ALFA ROMEO" watermark text very faintly
    f = _font("serif", 9 * s)
    text_centered(draw, SW // 2, 44 * s, "A L F A   R O M E O   1 5 6", f, rgba(c, 50))


def _draw_laurel_wreath(draw, cx, cy, radius, s, color):
    """Laurel wreath: pairs of leaves along an arc on both sides."""
    for side in [-1, 1]:
        for i in range(12):
            angle = math.radians(200 + i * 13) if side == -1 else math.radians(340 - i * 13)
            lx = cx + radius * math.cos(angle)
            ly = cy - radius * math.sin(angle)

            # Leaf pair
            leaf_angle = angle + side * math.radians(40)
            leaf_len = (10 - abs(i - 6)) * s
            tip_x = lx + leaf_len * math.cos(leaf_angle)
            tip_y = ly - leaf_len * math.sin(leaf_angle)

            # Leaf as thin polygon
            perp = leaf_angle + math.pi / 2
            w = 2.5 * s
            p1 = (lx + w * math.cos(perp), ly - w * math.sin(perp))
            p2 = (lx - w * math.cos(perp), ly + w * math.sin(perp))
            alpha_val = 50 + i * 5
            draw.polygon([p1, (tip_x, tip_y), p2], fill=rgba(color, min(alpha_val, 120)))

            # Stem
            draw.line([(lx, ly), (tip_x, tip_y)], fill=rgba(color, 80), width=max(1, s))


def _draw_corner_flourish(draw, x, y, s, color, sx, sy):
    """Small spiral flourish at a corner."""
    pts = []
    for t in range(0, 80, 2):
        r = (20 - t * 0.2) * s
        a = math.radians(t * 3)
        pts.append((x + sx * r * math.cos(a), y + sy * r * math.sin(a)))
    for i in range(len(pts) - 1):
        alpha_val = max(40, 120 - i * 2)
        draw.line([pts[i], pts[i + 1]], fill=rgba(color[:3], alpha_val), width=max(1, s))
    # Dot at start
    draw.ellipse([x - 2 * s, y - 2 * s, x + 2 * s, y + 2 * s], fill=rgba(color[:3], 100))


def _draw_classical_divider(draw, x, y, w, s, color):
    """Classical ornamental divider: center diamond with radiating lines."""
    cx = x + w // 2
    # Center diamond
    d = 5 * s
    draw.polygon([(cx, y - d), (cx + d, y), (cx, y + d), (cx - d, y)], fill=color)
    # Lines outward
    draw.line([(x, y), (cx - d - 4 * s, y)], fill=color, width=s)
    draw.line([(cx + d + 4 * s, y), (x + w, y)], fill=color, width=s)
    # Small dots
    for offset in [60, 120, 180]:
        for sign in [-1, 1]:
            dx = cx + sign * offset * s
            draw.ellipse([dx - s, y - s, dx + s, y + s], fill=color)


# ---------------------------------------------------------------------------
# Modern Dark decorations
# ---------------------------------------------------------------------------

def draw_modern_decorations(draw, theme):
    s = SS
    c = theme.accent
    # Thin horizontal accent lines flanking content
    gw = 48 * s
    for yy in [38 * s, (H - 38) * s]:
        draw.line([(gw + 5 * s, yy), (gw + 50 * s, yy)], fill=rgba(c, 35), width=s)
        draw.line([(SW - gw - 50 * s, yy), (SW - gw - 5 * s, yy)], fill=rgba(c, 35), width=s)

    # Subtle dot grid in background
    for gx in range(80 * s, SW - 80 * s, 30 * s):
        for gy in range(50 * s, SH - 50 * s, 30 * s):
            draw.ellipse([gx - s // 2, gy - s // 2, gx + s // 2, gy + s // 2],
                         fill=rgba(c, 8))


# ---------------------------------------------------------------------------
# OEM Digital decorations
# ---------------------------------------------------------------------------

def draw_oem_decorations(draw, theme):
    s = SS
    c = theme.accent
    # Alfa badge crest at top center
    bcx, bcy = SW // 2, 32 * s + 16 * s
    br = 12 * s
    draw.ellipse([bcx - br, bcy - br, bcx + br, bcy + br],
                 outline=rgba(c, 90), width=max(1, s + 1))
    # Cross
    draw.line([(bcx, bcy - br + 3 * s), (bcx, bcy + br - 3 * s)],
              fill=rgba(c, 90), width=s)
    draw.line([(bcx - br + 3 * s, bcy), (bcx + br - 3 * s, bcy)],
              fill=rgba(c, 90), width=s)
    # Red left quadrant hint
    draw.pieslice([bcx - br, bcy - br, bcx, bcy],
                  180, 270, fill=rgba(theme.danger, 40))

    # Thin double-line border around content area
    gw = 48 * s
    cx0 = gw + 2 * s
    cy0 = 34 * s
    cw0 = SW - 2 * gw - 4 * s
    ch0 = SH - 34 * s - 38 * s
    draw.rounded_rectangle([cx0, cy0, cx0 + cw0, cy0 + ch0],
                           radius=8 * s, outline=rgba(c, 25), width=s)
    draw.rounded_rectangle([cx0 + 3 * s, cy0 + 3 * s, cx0 + cw0 - 3 * s, cy0 + ch0 - 3 * s],
                           radius=6 * s, outline=rgba(c, 15), width=s)


# ---------------------------------------------------------------------------
# Side gauge
# ---------------------------------------------------------------------------

def draw_side_gauge(draw, x, y, w, h, theme, value, min_v, max_v,
                    top_lbl, bot_lbl, c_low, c_mid, c_high):
    s = SS
    draw_rrect(draw, x, y, w, h, 8 * s, fill=theme.side_bg)

    # Subtle inner border
    draw_rrect(draw, x + s, y + s, w - 2 * s, h - 2 * s, 7 * s,
               outline=rgba(theme.accent, 20), width=s)

    f = _font(theme.font_variant, 11 * s)
    text_centered(draw, x + w // 2, y + 12 * s, top_lbl, f, theme.text_dim)

    bx, bw = x + 12 * s, w - 24 * s
    by, bh = y + 28 * s, h - 56 * s
    draw_rrect(draw, bx, by, bw, bh, 4 * s, fill=rgba(theme.bg, 180))

    frac = max(0, min(1, (value - min_v) / (max_v - min_v)))
    fh = int(frac * bh)
    if fh > 2:
        fc = lerp(c_low, c_mid, frac * 2) if frac < 0.5 else lerp(c_mid, c_high, (frac - 0.5) * 2)
        fy = by + bh - fh
        # Gradient fill vertically
        for row in range(fh):
            row_frac = row / max(fh - 1, 1)
            rc = lerp(rgba(fc, 140), fc, row_frac)
            draw.line([(bx + 2 * s, fy + row), (bx + bw - 2 * s, fy + row)], fill=rc)

    text_centered(draw, x + w // 2, y + h - 14 * s, bot_lbl, f, theme.text_mid)


# ---------------------------------------------------------------------------
# Main render
# ---------------------------------------------------------------------------

def render_main_screen(theme):
    s = SS
    img = Image.new("RGBA", (SW, SH), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Background gradient
    draw_grad_rect(draw, 0, 0, SW, SH, theme.bg_gradient_top, theme.bg_gradient_bottom)

    # Subtle radial vignette (lighter center, darker edges)
    vig = Image.new("RGBA", (SW, SH), (0, 0, 0, 0))
    vd = ImageDraw.Draw(vig)
    max_r = int(math.hypot(SW, SH) / 2)
    for r in range(max_r, 0, -4 * s):
        a = int(50 * (1 - r / max_r) ** 1.5)
        vd.ellipse([SW // 2 - r, SH // 2 - r, SW // 2 + r, SH // 2 + r], fill=(0, 0, 0, a))
    img = Image.alpha_composite(img, vig)
    draw = ImageDraw.Draw(img)

    # --- Status bar ---
    sb_h = 32 * s
    draw_rrect(draw, 0, 0, SW, sb_h, 0, fill=theme.status_bg)
    draw.line([(0, sb_h - s), (SW, sb_h - s)], fill=rgba(theme.accent, 80), width=s)

    f_st = _font(theme.font_variant, 13 * s)
    draw.text((14 * s, 7 * s), "14:32", font=f_st, fill=theme.text_mid)
    draw.text((SW - 105 * s, 7 * s), "22.5\u00b0C", font=f_st, fill=theme.text_mid)
    f_bt = _font("bold", 11 * s)
    draw.text((SW - 148 * s, 9 * s), "BT", font=f_bt, fill=theme.accent)

    # --- Side gauges ---
    gw = 48 * s
    cy0 = sb_h + 8 * s
    gh = SH - cy0 - 42 * s

    draw_side_gauge(draw, 4 * s, cy0, gw, gh, theme,
                    85, 40, 130, "H", "85\u00b0",
                    theme.side_cold, theme.side_warm, theme.side_hot)
    draw_side_gauge(draw, SW - gw - 4 * s, cy0, gw, gh, theme,
                    62, 0, 100, "F", "62%",
                    theme.side_fuel_low, theme.side_fuel_ok, theme.side_fuel_ok)

    # --- Tachometer ---
    cx0 = gw + 12 * s
    cw = SW - 2 * (gw + 12 * s)
    tcx = cx0 + cw // 2
    tcy = cy0 + gh // 2 - 12 * s
    tr = min(cw, gh) // 2 - 22 * s

    rpm, max_rpm = 2800, 5500
    frac = rpm / max_rpm
    val_sweep = frac * 270

    # Outer glow
    draw_glow_arc(img, tcx, tcy, tr, 16 * s, 135, val_sweep,
                  theme.accent_glow, alpha=30, blur=18 * s)
    draw = ImageDraw.Draw(img)

    # Thin outer ring
    draw_thick_arc(draw, tcx, tcy, tr + 6 * s, 2 * s, 135, 270,
                   rgba(theme.accent, 30), rgba(theme.accent, 30))

    # Background arc
    draw_thick_arc(draw, tcx, tcy, tr, 16 * s, 135, 270,
                   theme.gauge_bg, theme.gauge_bg)

    # Inner thin ring
    draw_thick_arc(draw, tcx, tcy, tr - 16 * s, s, 135, 270,
                   rgba(theme.gauge_tick_dim, 60), rgba(theme.gauge_tick_dim, 60))

    # Redzone
    rz_frac = 4500 / max_rpm
    rz_start = 135 - rz_frac * 270
    rz_sweep = (1.0 - rz_frac) * 270
    draw_thick_arc(draw, tcx, tcy, tr, 16 * s, rz_start, rz_sweep,
                   rgba(theme.redzone, 60), theme.redzone)

    # Value arc (gradient)
    draw_thick_arc(draw, tcx, tcy, tr, 16 * s, 135, val_sweep,
                   theme.arc_start, theme.arc_end)

    # Tick marks + numbers
    f_tick = _font(theme.font_variant, 14 * s)
    for k in range(6):
        tf = k * 1000 / max_rpm
        ad = 135 - tf * 270
        ar = math.radians(ad)
        inner = tr - 18 * s
        outer = tr + 4 * s
        draw.line([(tcx + inner * math.cos(ar), tcy - inner * math.sin(ar)),
                   (tcx + outer * math.cos(ar), tcy - outer * math.sin(ar))],
                  fill=theme.gauge_tick, width=2 * s)
        nr = tr + 20 * s
        text_centered(draw, tcx + nr * math.cos(ar), tcy - nr * math.sin(ar),
                      str(k), f_tick, theme.text_mid)

    # Minor ticks
    for i in range(int(max_rpm / 500) + 1):
        v = i * 500
        if v % 1000 == 0:
            continue
        tf = v / max_rpm
        ar = math.radians(135 - tf * 270)
        draw.line([(tcx + (tr - 10 * s) * math.cos(ar), tcy - (tr - 10 * s) * math.sin(ar)),
                   (tcx + (tr + 2 * s) * math.cos(ar), tcy - (tr + 2 * s) * math.sin(ar))],
                  fill=theme.gauge_tick_dim, width=s)

    # Needle with glow
    na = 135 - frac * 270
    # Needle glow layer
    ng = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ngd = ImageDraw.Draw(ng)
    draw_needle(ngd, tcx, tcy, na, tr - 22 * s, 12 * s, rgba(theme.gauge_needle, 60))
    ng = ng.filter(ImageFilter.GaussianBlur(6 * s))
    img = Image.alpha_composite(img, ng)
    draw = ImageDraw.Draw(img)

    draw_needle(draw, tcx, tcy, na, tr - 22 * s, 8 * s, theme.gauge_needle)
    # Center cap (3 layers for depth)
    for cr, cc in [(9 * s, rgba(theme.gauge_needle, 180)),
                   (7 * s, theme.gauge_needle),
                   (4 * s, theme.bg)]:
        draw.ellipse([tcx - cr, tcy - cr, tcx + cr, tcy + cr], fill=cc)

    # RPM x1000 label
    f_sm = _font(theme.font_variant, 10 * s)
    text_centered(draw, tcx, tcy - tr + 38 * s, "RPM x1000", f_sm, theme.text_dim)

    # Speed (large centered)
    f_spd = _font(theme.font_value, 64 * s)
    text_centered(draw, tcx, tcy + 10 * s, "87", f_spd, theme.text)
    f_unit = _font(theme.font_variant, 15 * s)
    text_centered(draw, tcx, tcy + 50 * s, "km/h", f_unit, theme.text_dim)

    # --- Theme-specific decorations ---
    if theme.ornament_style == "classical":
        draw_classical_ornaments(img, draw, theme)
        draw = ImageDraw.Draw(img)
    elif theme.ornament_style == "minimal":
        draw_modern_decorations(draw, theme)
    elif theme.ornament_style == "oem":
        draw_oem_decorations(draw, theme)

    # --- Bottom bar ---
    bb_y = SH - 36 * s
    draw_rrect(draw, 0, bb_y, SW, 36 * s, 0, fill=theme.bottom_bg)
    draw.line([(0, bb_y), (SW, bb_y)], fill=rgba(theme.accent, 100), width=s)

    f_bl = _font(theme.font_variant, 12 * s)
    f_bv = _font("bold", 13 * s)

    lbl1 = "Zu\u017cycie: "
    val1 = "7.2 l/100km"
    draw.text((32 * s, bb_y + 9 * s), lbl1, font=f_bl, fill=theme.text_dim)
    w1 = f_bl.getbbox(lbl1)[2]
    draw.text((32 * s + w1, bb_y + 8 * s), val1, font=f_bv, fill=theme.accent)

    lbl2 = "RPM: "
    val2 = "2800"
    w2l = f_bl.getbbox(lbl2)[2]
    w2v = f_bv.getbbox(val2)[2]
    rx = SW - 32 * s - w2l - w2v
    draw.text((rx, bb_y + 9 * s), lbl2, font=f_bl, fill=theme.text_dim)
    draw.text((rx + w2l, bb_y + 8 * s), val2, font=f_bv, fill=theme.accent)

    # Gear indicator
    f_gear = _font("bold", 18 * s)
    text_centered(draw, SW // 2, bb_y + 18 * s, "3", f_gear, theme.accent)

    # Theme name watermark
    f_wm = _font(theme.font_variant, 8 * s)
    text_centered(draw, SW // 2, SH - 6 * s, theme.display_name, f_wm, rgba(theme.text_dim, 60))

    # Downsample
    return img.resize((W, H), Image.LANCZOS)


# ---------------------------------------------------------------------------
# Theme definitions
# ---------------------------------------------------------------------------

class Theme:
    def __init__(self, name, display_name, **kw):
        self.name = name
        self.display_name = display_name
        for k, v in kw.items():
            setattr(self, k, v)


CLASSIC_ALFA = Theme(
    "classic_alfa", "Classic Alfa Racing",
    bg=(14, 10, 12), bg_gradient_top=(20, 14, 18), bg_gradient_bottom=(8, 5, 7),
    accent=(220, 120, 20), accent_soft=(180, 100, 30), accent_glow=(255, 140, 30),
    text=(245, 235, 220), text_dim=(140, 125, 105), text_mid=(200, 180, 155),
    danger=(220, 40, 30), ok=(80, 200, 90), warning=(255, 200, 0),
    gauge_bg=(40, 28, 22), gauge_fg=(220, 120, 20),
    gauge_needle=(255, 90, 35), gauge_tick=(160, 140, 120), gauge_tick_dim=(90, 75, 60),
    redzone=(180, 30, 20), arc_start=(70, 35, 8), arc_end=(255, 150, 25),
    status_bg=(20, 14, 16), bottom_bg=(20, 14, 16),
    side_bg=(32, 24, 20), side_cold=(80, 160, 220), side_warm=(220, 160, 60),
    side_hot=(255, 80, 30), side_fuel_ok=(120, 200, 80), side_fuel_low=(255, 80, 30),
    badge_circle=(200, 180, 160), badge_cross=(200, 40, 30),
    font_variant="serif", font_value="serif_bold", ornament_style="classical",
)

MODERN_DARK = Theme(
    "modern_dark", "Modern Dark",
    bg=(12, 14, 22), bg_gradient_top=(18, 20, 32), bg_gradient_bottom=(6, 8, 14),
    accent=(0, 180, 255), accent_soft=(0, 130, 200), accent_glow=(0, 200, 255),
    text=(230, 235, 248), text_dim=(90, 100, 125), text_mid=(150, 160, 185),
    danger=(255, 65, 65), ok=(0, 220, 120), warning=(255, 200, 0),
    gauge_bg=(28, 32, 45), gauge_fg=(0, 180, 255),
    gauge_needle=(0, 210, 255), gauge_tick=(80, 90, 115), gauge_tick_dim=(45, 50, 65),
    redzone=(255, 65, 65), arc_start=(0, 50, 100), arc_end=(0, 210, 255),
    status_bg=(16, 18, 28), bottom_bg=(16, 18, 28),
    side_bg=(22, 26, 38), side_cold=(60, 140, 220), side_warm=(0, 200, 255),
    side_hot=(255, 80, 60), side_fuel_ok=(0, 220, 120), side_fuel_low=(255, 80, 60),
    badge_circle=(120, 140, 170), badge_cross=(0, 180, 255),
    font_variant="light", font_value="bold", ornament_style="minimal",
)

OEM_DIGITAL = Theme(
    "oem_digital", "OEM Digital",
    bg=(10, 14, 24), bg_gradient_top=(16, 20, 34), bg_gradient_bottom=(5, 8, 16),
    accent=(180, 192, 220), accent_soft=(140, 155, 185), accent_glow=(200, 210, 235),
    text=(220, 228, 245), text_dim=(100, 112, 140), text_mid=(155, 165, 195),
    danger=(220, 42, 42), ok=(80, 200, 110), warning=(255, 195, 0),
    gauge_bg=(22, 28, 42), gauge_fg=(180, 192, 220),
    gauge_needle=(220, 42, 42), gauge_tick=(100, 112, 140), gauge_tick_dim=(55, 62, 80),
    redzone=(200, 35, 35), arc_start=(50, 60, 95), arc_end=(185, 195, 225),
    status_bg=(14, 18, 32), bottom_bg=(14, 18, 32),
    side_bg=(20, 26, 40), side_cold=(80, 140, 200), side_warm=(180, 192, 220),
    side_hot=(220, 65, 45), side_fuel_ok=(100, 200, 110), side_fuel_low=(220, 65, 45),
    badge_circle=(160, 172, 200), badge_cross=(220, 42, 42),
    font_variant="regular", font_value="bold", ornament_style="oem",
)

ALL_THEMES = [CLASSIC_ALFA, MODERN_DARK, OEM_DIGITAL]


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    for theme in ALL_THEMES:
        print(f"Rendering {theme.display_name}...")
        img = render_main_screen(theme)
        path = os.path.join(OUTPUT_DIR, f"mockup_{theme.name}.png")
        img.save(path, "PNG", optimize=True)
        print(f"  -> {path}")
    print("Done!")


if __name__ == "__main__":
    main()
