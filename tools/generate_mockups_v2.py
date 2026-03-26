#!/usr/bin/env python3
"""Generate PNG mockups for BCM headunit — card-based UI, 3 themes × 5 screens.

Phase 1, Step 1.1: Foundation — constants, fonts, base primitives.
"""

import math
import os
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# --- Constants ---
W, H = 800, 480
SS = 3  # supersampling factor
SW, SH = W * SS, H * SS
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "mockups", "renders")

# Layout constants (logical pixels, multiply by SS for drawing)
APPBAR_H = 48
NAVBAR_H = 64
CONTENT_PAD = 16
CONTENT_H = H - APPBAR_H - NAVBAR_H  # 368

# --- Font helpers ---
_font_cache = {}
FONT_PATHS = {
    "regular":      "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "bold":         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "light":        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "light_bold":   "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "serif":        "/usr/share/fonts/truetype/freefont/FreeSerif.ttf",
    "serif_bold":   "/usr/share/fonts/truetype/freefont/FreeSerifBold.ttf",
    "mono":         "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "mono_bold":    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    "italic":       "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf",
    "bold_italic":  "/usr/share/fonts/truetype/dejavu/DejaVuSans-BoldOblique.ttf",
    "serif_italic": "/usr/share/fonts/truetype/freefont/FreeSerifItalic.ttf",
    "serif_bold_italic": "/usr/share/fonts/truetype/freefont/FreeSerifBoldItalic.ttf",
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
    """Linear interpolation between two color tuples."""
    t = max(0.0, min(1.0, t))
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def rgba(color, alpha):
    """Return color tuple with alpha channel."""
    return (*color[:3], alpha)


def text_bbox_size(draw, text, font):
    """Return (width, height) of text bounding box."""
    bb = draw.textbbox((0, 0), text, font=font)
    return bb[2] - bb[0], bb[3] - bb[1]


def text_centered(draw, x, y, text, font, fill):
    """Draw text centered at (x, y)."""
    tw, th = text_bbox_size(draw, text, font)
    draw.text((x - tw / 2, y - th / 2), text, font=font, fill=fill)


def text_right(draw, x, y, text, font, fill):
    """Draw text right-aligned at (x, y)."""
    bb = draw.textbbox((0, 0), text, font=font)
    tw = bb[2] - bb[0]
    draw.text((x - tw, y), text, font=font, fill=fill)


def text_spaced(draw, x, y, text, font, fill, spacing=0):
    """Draw text with extra letter-spacing (for tracking-widest style).

    Args:
        spacing: Extra pixels between each character (in supersampled coords).
    """
    if spacing <= 0:
        draw.text((x, y), text, font=font, fill=fill)
        return
    cx = x
    for ch in text:
        draw.text((cx, y), ch, font=font, fill=fill)
        bb = draw.textbbox((0, 0), ch, font=font)
        cx += (bb[2] - bb[0]) + spacing


def text_spaced_centered(draw, cx, cy, text, font, fill, spacing=0):
    """Draw letter-spaced text centered at (cx, cy)."""
    # Calculate total width
    total_w = 0
    for i, ch in enumerate(text):
        bb = draw.textbbox((0, 0), ch, font=font)
        total_w += (bb[2] - bb[0])
        if i < len(text) - 1:
            total_w += spacing
    bb = draw.textbbox((0, 0), text[0], font=font)
    th = bb[3] - bb[1]
    text_spaced(draw, cx - total_w / 2, cy - th / 2, text, font, fill, spacing)


def rrect(draw, x, y, w, h, r, **kw):
    """Draw a rounded rectangle."""
    r = min(r, w // 2, h // 2)
    draw.rounded_rectangle([x, y, x + w, y + h], radius=r, **kw)


def grad_rect(draw, x, y, w, h, c_top, c_bot):
    """Draw a vertical gradient rectangle."""
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
    """Draw a gauge needle."""
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
    """Draw a glowing arc effect using Gaussian blur."""
    s = SS
    if blur_r is None:
        blur_r = 12 * s
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    thick_arc(gd, cx, cy, radius + width, width * 3,
              start_deg, sweep_deg, rgba(color, alpha))
    glow = glow.filter(ImageFilter.GaussianBlur(blur_r))
    return Image.alpha_composite(img, glow)


def draw_shadow_rrect(img, x, y, w, h, r, fill, shadow_color=(0, 0, 0, 40),
                      shadow_offset=4, shadow_blur=8):
    """Draw a rounded rectangle card with a drop shadow.

    Args:
        img: RGBA Image to draw onto (composited in place).
        x, y, w, h: Card position and size.
        r: Corner radius.
        fill: Card fill color (RGB or RGBA tuple).
        shadow_color: Shadow RGBA color.
        shadow_offset: Shadow Y offset in pixels.
        shadow_blur: Shadow blur radius.

    Returns:
        Modified image with shadow + card drawn.
    """
    s = SS
    # Draw shadow layer
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sx = x
    sy = y + shadow_offset * s
    sd.rounded_rectangle([sx, sy, sx + w, sy + h], radius=r,
                         fill=shadow_color)
    shadow = shadow.filter(ImageFilter.GaussianBlur(shadow_blur * s))
    result = Image.alpha_composite(img, shadow)
    # Draw card on top
    d = ImageDraw.Draw(result)
    d.rounded_rectangle([x, y, x + w, y + h], radius=r, fill=fill)
    return result


# --- Theme dataclass ---

class Theme:
    def __init__(self, name, display_name, **kw):
        self.name = name
        self.display_name = display_name
        for k, v in kw.items():
            setattr(self, k, v)


# =========================================================================
#  THEMES — 3 palettes (extracted from stitch HTML sources)
# =========================================================================

HERITAGE = Theme(
    "heritage", "Heritage Warmth",
    # Core backgrounds
    bg=(26, 15, 10),               # #1a0f0a — burl walnut dark
    bg_light=(248, 246, 246),      # #f8f6f6 — light mode (A2/A4)
    appbar_bg=(0, 0, 0),
    navbar_bg=(9, 9, 11),          # zinc-950
    # Accent colors
    accent=(245, 158, 11),         # #f59e0b — amber-500
    accent_dim=(217, 119, 6),      # amber-600
    amber_glow=(255, 191, 0),      # #FFBF00 — splash accent
    brand_red=(220, 38, 38),       # red-600
    # Text
    text=(244, 244, 245),          # zinc-100
    text_dim=(113, 113, 122),      # zinc-500
    text_mid=(161, 161, 170),      # zinc-400
    text_dark=(39, 39, 42),        # zinc-800 (for light bg screens)
    text_dark_dim=(113, 113, 122), # zinc-500
    # Card
    card_bg=(9, 9, 11),            # zinc-950
    card_border=(39, 39, 42),      # zinc-800
    card_bg_light=(255, 255, 255), # white (for light bg screens)
    card_border_light=(236, 91, 19, 25),  # primary/10
    # Status
    ok=(34, 197, 94),              # green-500
    warning=(245, 158, 11),        # amber-500
    danger=(220, 38, 38),          # red-600
    # Special
    burl_dark=(61, 39, 22),
    burl_light=(124, 80, 45),
    primary_orange=(236, 91, 19),  # #ec5b13 — heritage A2/A4 primary
    is_light=False,
)

MODERN = Theme(
    "modern", "Modern Clean",
    # Core backgrounds
    bg=(248, 250, 252),            # #f8fafc — slate-50
    bg_content=(241, 245, 249),    # #f1f5f9 — slate-100
    appbar_bg=(0, 0, 0),
    navbar_bg=(0, 0, 0),
    # Accent colors
    accent=(0, 85, 150),           # #005596 — Alfa Blue
    accent_light=(59, 130, 246),   # #3b82f6 — blue-500
    brand_red=(239, 68, 68),       # red-500
    # Text
    text=(15, 23, 42),             # slate-900
    text_dim=(148, 163, 184),      # slate-400
    text_mid=(100, 116, 139),      # slate-500
    text_light=(255, 255, 255),
    # Card
    card_bg=(255, 255, 255),
    card_border=(226, 232, 240),   # slate-200
    card_shadow=(0, 0, 0, 20),
    # Status
    ok=(22, 163, 74),              # green-600
    warning=(245, 158, 11),
    danger=(239, 68, 68),          # red-500
    # Special
    init_bg=(22, 22, 24),          # #161618 — dark charcoal for init screen
    is_light=True,
)

AUTODELTA = Theme(
    "autodelta", "Autodelta Sport",
    # Core backgrounds
    bg=(0, 0, 0),
    appbar_bg=(17, 17, 17),        # zinc-950-ish
    navbar_bg=(9, 9, 11),          # zinc-950
    # Accent colors
    accent=(236, 91, 19),          # #ec5b13 — Autodelta orange
    accent_alt=(255, 95, 0),       # #FF5F00 — brand orange
    brand_red=(185, 28, 28),       # red-800
    # Text
    text=(255, 255, 255),
    text_dim=(113, 113, 122),      # zinc-500
    text_mid=(161, 161, 170),      # zinc-400
    # Card
    card_bg=(24, 24, 27),          # zinc-900
    card_border=(39, 39, 42),      # zinc-800
    card_border_accent=(236, 91, 19, 76),  # orange/30
    # Status
    ok=(34, 197, 94),
    warning=(236, 91, 19),
    danger=(239, 68, 68),
    # Special
    is_light=False,
)

ALL_THEMES = [HERITAGE, MODERN, AUTODELTA]

# =========================================================================
#  Shared Chrome — App Bar + Nav Bar + Frame (Step 1.3)
# =========================================================================

def _draw_bt_icon(draw, cx, cy, size, color):
    """Draw a simple Bluetooth icon (geometric approximation)."""
    s = size
    # Vertical line
    draw.line([(cx, cy - s), (cx, cy + s)], fill=color, width=max(2, s // 5))
    # Upper-right arrow
    draw.line([(cx, cy - s), (cx + s * 0.5, cy - s * 0.4)], fill=color, width=max(2, s // 5))
    draw.line([(cx + s * 0.5, cy - s * 0.4), (cx, cy)], fill=color, width=max(2, s // 5))
    # Lower-right arrow
    draw.line([(cx, cy + s), (cx + s * 0.5, cy + s * 0.4)], fill=color, width=max(2, s // 5))
    draw.line([(cx + s * 0.5, cy + s * 0.4), (cx, cy)], fill=color, width=max(2, s // 5))


def _draw_signal_icon(draw, cx, cy, size, color):
    """Draw a simple antenna/signal icon."""
    s = size
    # Vertical antenna line
    draw.line([(cx, cy - s), (cx, cy + s * 0.3)], fill=color, width=max(2, s // 5))
    # Signal arcs (simplified as small lines)
    for i, offset in enumerate([0.3, 0.6]):
        a = int(200 * (1 - i * 0.3))
        c = (*color[:3], a) if len(color) >= 3 else color
        draw.arc([cx - s * offset, cy - s * (0.5 + offset * 0.5),
                  cx + s * offset, cy - s * 0.1],
                 start=200, end=340, fill=c, width=max(1, s // 6))


def _draw_phone_icon(draw, cx, cy, size, color):
    """Draw a simple smartphone icon."""
    s = size
    w, h = int(s * 0.6), int(s * 1.2)
    rrect(draw, cx - w // 2, cy - h // 2, w, h, max(2, s // 6), outline=color,
          width=max(1, s // 6))
    # Screen button
    draw.ellipse([cx - s * 0.1, cy + h // 2 - s * 0.35,
                  cx + s * 0.1, cy + h // 2 - s * 0.15], fill=color)


def _draw_nav_icon_home(draw, cx, cy, size, color):
    """Draw a simple house icon."""
    s = size
    # Roof triangle
    pts = [(cx, cy - s), (cx - s, cy), (cx + s, cy)]
    draw.polygon(pts, fill=color)
    # Body rectangle
    bw = int(s * 0.7)
    bh = int(s * 0.8)
    draw.rectangle([cx - bw // 2, cy, cx + bw // 2, cy + bh], fill=color)


def _draw_nav_icon_car(draw, cx, cy, size, color):
    """Draw a simple car icon."""
    s = size
    # Body
    draw.rounded_rectangle([cx - s, cy - s * 0.2, cx + s, cy + s * 0.5],
                           radius=max(2, s // 4), fill=color)
    # Roof
    draw.rounded_rectangle([cx - s * 0.6, cy - s * 0.7, cx + s * 0.6, cy],
                           radius=max(2, s // 4), fill=color)
    # Wheels
    r = int(s * 0.25)
    draw.ellipse([cx - s * 0.65 - r, cy + s * 0.3 - r,
                  cx - s * 0.65 + r, cy + s * 0.3 + r], fill=color)
    draw.ellipse([cx + s * 0.65 - r, cy + s * 0.3 - r,
                  cx + s * 0.65 + r, cy + s * 0.3 + r], fill=color)


def _draw_nav_icon_cloud(draw, cx, cy, size, color):
    """Draw a simple cloud icon."""
    s = size
    # Main ellipse
    draw.ellipse([cx - s * 0.7, cy - s * 0.3, cx + s * 0.7, cy + s * 0.5], fill=color)
    # Top bump
    draw.ellipse([cx - s * 0.4, cy - s * 0.7, cx + s * 0.4, cy + s * 0.1], fill=color)
    # Left bump
    draw.ellipse([cx - s, cy - s * 0.2, cx - s * 0.2, cy + s * 0.5], fill=color)


def _draw_nav_icon_wrench(draw, cx, cy, size, color):
    """Draw a simple wrench/build icon."""
    s = size
    lw = max(2, int(s * 0.25))
    # Diagonal shaft
    draw.line([(cx - s * 0.6, cy + s * 0.6), (cx + s * 0.3, cy - s * 0.3)],
              fill=color, width=lw)
    # Wrench head circle
    draw.ellipse([cx + s * 0.1, cy - s * 0.7, cx + s * 0.7, cy - s * 0.1],
                 outline=color, width=lw)


NAV_ICONS = [_draw_nav_icon_home, _draw_nav_icon_car,
             _draw_nav_icon_cloud, _draw_nav_icon_wrench]


def draw_app_bar(img, draw, theme, time_str="10:45", date_str="Oct 24",
                 temp_str="21°C"):
    """Draw the themed top app bar (48px height)."""
    s = SS
    bar_h = APPBAR_H * s
    bar_w = W * s

    # Background
    draw.rectangle([0, 0, bar_w, bar_h], fill=theme.appbar_bg)
    # Bottom border
    border_color = (39, 39, 42) if not theme.is_light else (39, 39, 42)
    draw.line([(0, bar_h - 1), (bar_w, bar_h - 1)], fill=border_color)

    pad = 24 * s
    mid_x = bar_w // 2
    mid_y = bar_h // 2

    if theme.name == "heritage":
        # Left: time in zinc-400 bold + date dim
        f_time = _font("bold", 13 * s)
        f_date = _font("regular", 10 * s)
        draw.text((pad, mid_y - 8 * s), time_str, font=f_time, fill=(161, 161, 170))
        draw.text((pad + 80 * s, mid_y - 5 * s), date_str, font=f_date,
                  fill=(113, 113, 122))
        # Center: "ALFA ROMEO" in red, uppercase, tracking-widest
        f_brand = _font("serif_bold", 14 * s)
        text_spaced_centered(draw, mid_x, mid_y, "ALFA ROMEO", f_brand,
                             theme.brand_red, spacing=6 * s)
        # Right: temp + BT icon
        f_temp = _font("bold", 13 * s)
        text_right(draw, bar_w - pad, mid_y - 7 * s, temp_str, f_temp,
                   (255, 255, 255))
        _draw_bt_icon(draw, bar_w - pad - 70 * s, mid_y, 8 * s,
                      (161, 161, 170))

    elif theme.name == "modern":
        # Left: time bold white + date dim
        f_time = _font("bold", 13 * s)
        f_date = _font("regular", 9 * s)
        draw.text((pad, mid_y - 8 * s), time_str, font=f_time, fill=(255, 255, 255))
        draw.text((pad + 80 * s, mid_y - 4 * s), date_str, font=f_date,
                  fill=(113, 113, 122, 150))
        # Center: "Alfa Romeo" italic red
        f_brand = _font("bold_italic", 15 * s)
        text_centered(draw, mid_x, mid_y, "Alfa Romeo", f_brand, (220, 38, 38))
        # Right: temp + BT + signal icons
        f_temp = _font("bold", 13 * s)
        text_right(draw, bar_w - pad, mid_y - 7 * s, temp_str, f_temp,
                   (255, 255, 255))
        _draw_bt_icon(draw, bar_w - pad - 80 * s, mid_y, 7 * s,
                      (161, 161, 170))
        _draw_signal_icon(draw, bar_w - pad - 55 * s, mid_y, 7 * s,
                          (161, 161, 170))

    elif theme.name == "autodelta":
        # Left: time + date stacked
        f_time = _font("bold", 13 * s)
        f_date = _font("regular", 9 * s)
        draw.text((pad, mid_y - 8 * s), time_str, font=f_time, fill=(161, 161, 170))
        draw.text((pad + 80 * s, mid_y - 4 * s), date_str, font=f_date,
                  fill=(113, 113, 122))
        # Center: "Alfa Romeo" in red, serif italic bold, tracking-widest
        f_brand = _font("serif_bold", 14 * s)
        text_spaced_centered(draw, mid_x, mid_y, "ALFA ROMEO", f_brand,
                             (185, 28, 28), spacing=5 * s)
        # Right: temp in orange + BT + phone icons
        f_temp = _font("bold", 13 * s)
        text_right(draw, bar_w - pad, mid_y - 7 * s, temp_str, f_temp,
                   theme.accent)
        _draw_bt_icon(draw, bar_w - pad - 70 * s, mid_y, 7 * s,
                      (161, 161, 170))
        _draw_phone_icon(draw, bar_w - pad - 45 * s, mid_y, 6 * s,
                         (161, 161, 170))


def draw_nav_bar(img, draw, theme, active_index=0):
    """Draw the themed bottom navigation bar (64px height).

    active_index: 0=home, 1=drive, 2=climate, 3=service
    """
    s = SS
    bar_h = NAVBAR_H * s
    bar_w = W * s
    bar_y = (H - NAVBAR_H) * s

    # Background
    draw.rectangle([0, bar_y, bar_w, bar_y + bar_h], fill=theme.navbar_bg)
    # Top border
    draw.line([(0, bar_y), (bar_w, bar_y)], fill=(39, 39, 42))

    # 4 equally spaced nav items
    item_w = bar_w // 4
    icon_size = 12 * s
    item_cy = bar_y + bar_h // 2

    for i in range(4):
        item_cx = item_w * i + item_w // 2
        is_active = (i == active_index)

        if is_active:
            # Active pill background
            pill_w = 48 * s
            pill_h = 36 * s
            if theme.name == "heritage" or theme.name == "autodelta":
                pill_color = (127, 29, 29, 76)  # red-950/30
                icon_color = (239, 68, 68)       # red-500
            else:  # modern
                pill_color = (127, 29, 29, 51)   # red-600/20
                icon_color = (239, 68, 68)        # red-500
            rrect(draw, item_cx - pill_w // 2, item_cy - pill_h // 2,
                  pill_w, pill_h, 12 * s, fill=pill_color)
        else:
            icon_color = (113, 113, 122)  # zinc-500

        NAV_ICONS[i](draw, item_cx, item_cy, icon_size, icon_color)


def render_frame(theme, active_nav=0, bg_override=None):
    """Create a new image with app bar + nav bar drawn. Returns (img, draw, content_rect).

    content_rect: (x, y, w, h) of the drawable content area between bars.
    """
    s = SS
    img = Image.new("RGBA", (SW, SH), (0, 0, 0, 255))
    draw = ImageDraw.Draw(img)

    # Fill background
    bg = bg_override or theme.bg
    draw.rectangle([0, 0, SW, SH], fill=bg)

    # Draw chrome
    draw_app_bar(img, draw, theme)
    draw_nav_bar(img, draw, theme, active_index=active_nav)

    # Content rect (between app bar and nav bar, with padding)
    cx = CONTENT_PAD * s
    cy = APPBAR_H * s
    cw = (W - 2 * CONTENT_PAD) * s
    ch = CONTENT_H * s
    content_rect = (cx, cy, cw, ch)

    return img, draw, content_rect

# =========================================================================
#  Card, Progress, Icon, Notification Primitives (Step 1.4)
# =========================================================================

def draw_card(draw, x, y, w, h, fill, border_color=None, border_w=1, radius=None):
    """Draw a rounded rectangle card with optional border."""
    s = SS
    if radius is None:
        radius = 8 * s
    if border_color:
        draw.rounded_rectangle([x, y, x + w, y + h], radius=radius,
                               fill=fill, outline=border_color, width=border_w)
    else:
        draw.rounded_rectangle([x, y, x + w, y + h], radius=radius, fill=fill)


def draw_progress_bar(draw, x, y, w, h, fraction, fill_color, bg_color,
                      radius=0):
    """Draw a horizontal progress bar."""
    fraction = max(0.0, min(1.0, fraction))
    if radius > 0:
        rrect(draw, x, y, w, h, radius, fill=bg_color)
        fill_w = max(0, int(w * fraction))
        if fill_w > 0:
            rrect(draw, x, y, fill_w, h, radius, fill=fill_color)
    else:
        draw.rectangle([x, y, x + w, y + h], fill=bg_color)
        fill_w = max(0, int(w * fraction))
        if fill_w > 0:
            draw.rectangle([x, y, x + fill_w, y + h], fill=fill_color)


def draw_circle_gauge(draw, cx, cy, radius, fraction, color, bg_color, width):
    """Draw a thin-arc circular gauge (0-100%)."""
    # Background full circle
    thick_arc(draw, cx, cy, radius, width, 90, 360, bg_color)
    # Foreground arc
    if fraction > 0:
        thick_arc(draw, cx, cy, radius, width, 90, 360 * fraction, color)


def draw_icon_thermometer(draw, cx, cy, size, color):
    """Draw a thermometer icon."""
    s = size
    lw = max(2, int(s * 0.2))
    # Stem
    draw.rounded_rectangle([cx - s * 0.15, cy - s * 0.8, cx + s * 0.15, cy + s * 0.2],
                           radius=max(2, int(s * 0.1)), outline=color, width=lw)
    # Bulb
    draw.ellipse([cx - s * 0.3, cy + s * 0.1, cx + s * 0.3, cy + s * 0.7],
                 outline=color, width=lw)
    # Fill level
    draw.rectangle([cx - s * 0.08, cy - s * 0.3, cx + s * 0.08, cy + s * 0.3],
                   fill=color)


def draw_icon_fuel(draw, cx, cy, size, color):
    """Draw a fuel pump icon."""
    s = size
    lw = max(2, int(s * 0.18))
    # Pump body
    draw.rounded_rectangle([cx - s * 0.5, cy - s * 0.6, cx + s * 0.2, cy + s * 0.7],
                           radius=max(2, int(s * 0.1)), outline=color, width=lw)
    # Nozzle arm
    draw.line([(cx + s * 0.2, cy - s * 0.3), (cx + s * 0.5, cy - s * 0.6),
               (cx + s * 0.5, cy)], fill=color, width=lw)
    # Fill window
    draw.rectangle([cx - s * 0.35, cy - s * 0.35, cx + s * 0.05, cy - s * 0.05],
                   fill=color)


def draw_icon_warning(draw, cx, cy, size, color):
    """Draw a warning triangle icon."""
    s = size
    pts = [(cx, cy - s * 0.7), (cx - s * 0.7, cy + s * 0.5),
           (cx + s * 0.7, cy + s * 0.5)]
    draw.polygon(pts, outline=color, width=max(2, int(s * 0.15)))
    # Exclamation
    lw = max(2, int(s * 0.12))
    draw.line([(cx, cy - s * 0.25), (cx, cy + s * 0.1)], fill=color, width=lw)
    draw.ellipse([cx - s * 0.06, cy + s * 0.2, cx + s * 0.06, cy + s * 0.32],
                 fill=color)


def draw_icon_music(draw, cx, cy, size, color):
    """Draw a music note icon."""
    s = size
    lw = max(2, int(s * 0.15))
    # Stem
    draw.line([(cx + s * 0.15, cy - s * 0.7), (cx + s * 0.15, cy + s * 0.3)],
              fill=color, width=lw)
    # Note head
    draw.ellipse([cx - s * 0.25, cy + s * 0.1, cx + s * 0.15, cy + s * 0.5],
                 fill=color)
    # Flag
    draw.line([(cx + s * 0.15, cy - s * 0.7), (cx + s * 0.5, cy - s * 0.4)],
              fill=color, width=lw)


def draw_icon_check(draw, cx, cy, size, color):
    """Draw a checkmark icon."""
    s = size
    lw = max(2, int(s * 0.2))
    draw.line([(cx - s * 0.4, cy), (cx - s * 0.1, cy + s * 0.3),
               (cx + s * 0.5, cy - s * 0.4)], fill=color, width=lw)


def draw_icon_route(draw, cx, cy, size, color):
    """Draw a route/navigation icon."""
    s = size
    lw = max(2, int(s * 0.15))
    # Arrow pointing up-right
    draw.line([(cx - s * 0.3, cy + s * 0.5), (cx, cy - s * 0.5),
               (cx + s * 0.3, cy + s * 0.5)], fill=color, width=lw)
    draw.line([(cx, cy - s * 0.5), (cx, cy + s * 0.5)], fill=color, width=lw)


def draw_icon_eco(draw, cx, cy, size, color):
    """Draw a leaf/eco icon."""
    s = size
    # Leaf shape using ellipse + stem
    draw.ellipse([cx - s * 0.4, cy - s * 0.6, cx + s * 0.4, cy + s * 0.2],
                 fill=color)
    lw = max(2, int(s * 0.12))
    draw.line([(cx, cy + s * 0.2), (cx, cy + s * 0.6)], fill=color, width=lw)


def draw_notification_item(draw, x, y, w, h, theme, border_color,
                           icon_fn, title, subtitle):
    """Draw a single notification row with left border accent.

    Args:
        draw: ImageDraw instance
        x, y, w, h: Position and dimensions
        theme: Theme object
        border_color: Left border accent color (RGB tuple)
        icon_fn: Icon drawing function (draw, cx, cy, size, color)
        title: Title text
        subtitle: Subtitle text
    """
    s = SS
    # Card background
    draw_card(draw, x, y, w, h, fill=theme.card_bg,
              border_color=theme.card_border)
    # Left accent border
    accent_w = 3 * s
    draw.rectangle([x, y, x + accent_w, y + h], fill=border_color)

    # Icon
    icon_cx = x + 28 * s
    icon_cy = y + h // 2
    if icon_fn:
        icon_fn(draw, icon_cx, icon_cy, 8 * s, border_color)

    # Title
    f_title = _font("bold", 10 * s)
    f_sub = _font("regular", 8 * s)
    text_x = x + 48 * s
    draw.text((text_x, y + 8 * s), title, font=f_title, fill=theme.text)
    draw.text((text_x, y + 22 * s), subtitle, font=f_sub, fill=theme.text_dim)

# =========================================================================
#  Complex Drawing Primitives — Charts, Maps, Car, Burl (Step 1.5)
# =========================================================================

def draw_bar_chart(draw, x, y, w, h, values, colors, gap=None,
                   x_labels=None, y_labels=None, label_color=(113, 113, 122)):
    """Draw a vertical bar chart.

    Args:
        values: List of floats (0.0 to 1.0 representing fraction of max height).
        colors: List of color tuples (one per bar, or single color for all).
        gap: Gap between bars (default: auto).
        x_labels: Labels below each bar (list of strings).
        y_labels: Labels on left side (list of strings, top to bottom).
    """
    s = SS
    n = len(values)
    if n == 0:
        return

    # Layout
    label_margin = 30 * s if y_labels else 0
    bottom_margin = 18 * s if x_labels else 0
    chart_x = x + label_margin
    chart_y = y
    chart_w = w - label_margin
    chart_h = h - bottom_margin

    if gap is None:
        gap = max(2, int(chart_w / n * 0.15))
    bar_w = max(4, (chart_w - gap * (n + 1)) // n)

    # Y-axis labels
    if y_labels:
        f_label = _font("bold", 7 * s)
        for i, lbl in enumerate(y_labels):
            ly = chart_y + int(chart_h * i / max(len(y_labels) - 1, 1))
            text_right(draw, x + label_margin - 4 * s, ly - 4 * s, lbl,
                       f_label, label_color)
            # Grid line
            draw.line([(chart_x, ly), (chart_x + chart_w, ly)],
                      fill=(*label_color[:3], 40), width=1)

    # Bars
    if isinstance(colors, tuple) and not isinstance(colors[0], (tuple, list)):
        colors = [colors] * n
    while len(colors) < n:
        colors.append(colors[-1])

    for i in range(n):
        bx = chart_x + gap + i * (bar_w + gap)
        bar_h = max(1, int(chart_h * values[i]))
        by = chart_y + chart_h - bar_h
        rrect(draw, bx, by, bar_w, bar_h, max(2, 3 * s), fill=colors[i])

    # X-axis labels
    if x_labels:
        f_label = _font("regular", 7 * s)
        for i, lbl in enumerate(x_labels):
            if i < n:
                bx = chart_x + gap + i * (bar_w + gap) + bar_w // 2
                text_centered(draw, bx, chart_y + chart_h + 8 * s,
                              lbl, f_label, label_color)


def draw_line_graph(img, draw, x, y, w, h, points, line_color,
                    fill_color=None, highlight_idx=None):
    """Draw a line graph with optional area fill and highlight dot.

    Args:
        points: List of floats (0.0=bottom to 1.0=top).
        fill_color: RGBA tuple for area fill below line.
        highlight_idx: Index of point to highlight with a dot.
    """
    s = SS
    n = len(points)
    if n < 2:
        return

    # Compute pixel coordinates
    coords = []
    for i, v in enumerate(points):
        px = x + int(w * i / (n - 1))
        py = y + int(h * (1.0 - v))
        coords.append((px, py))

    # Area fill (using polygon)
    if fill_color:
        fill_pts = list(coords) + [(x + w, y + h), (x, y + h)]
        # Draw on overlay for alpha support
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        od.polygon(fill_pts, fill=fill_color)
        img_result = Image.alpha_composite(img, overlay)
        # Copy pixels back (crude but works)
        img.paste(img_result)

    # Line
    lw = max(2, 3 * s)
    for i in range(n - 1):
        draw.line([coords[i], coords[i + 1]], fill=line_color, width=lw)

    # Highlight dot
    if highlight_idx is not None and 0 <= highlight_idx < n:
        hx, hy = coords[highlight_idx]
        r = 4 * s
        draw.ellipse([hx - r, hy - r, hx + r, hy + r], fill=line_color)
        # Outer ring
        r2 = 8 * s
        draw.ellipse([hx - r2, hy - r2, hx + r2, hy + r2],
                     outline=line_color, width=2 * s)


def draw_simple_map(img, draw, x, y, w, h, theme):
    """Draw a stylized map placeholder with theme-specific tinting.

    Draws a dark base with grid streets, thicker main roads, and a location dot.
    """
    s = SS
    import random
    rng = random.Random(42)  # Deterministic for consistent renders

    # Base dark background
    map_bg = (15, 15, 18) if not theme.is_light else (30, 30, 35)
    draw.rectangle([x, y, x + w, y + h], fill=map_bg)

    # Grid streets (thin lines)
    grid_color = (40, 40, 45) if not theme.is_light else (50, 50, 55)
    spacing = 30 * s
    for gx in range(0, w, spacing):
        offset = rng.randint(-5 * s, 5 * s)
        draw.line([(x + gx + offset, y), (x + gx + offset, y + h)],
                  fill=grid_color, width=1)
    for gy in range(0, h, spacing):
        offset = rng.randint(-5 * s, 5 * s)
        draw.line([(x, y + gy + offset), (x + w, y + gy + offset)],
                  fill=grid_color, width=1)

    # Main roads (thicker, accent-tinted)
    accent = theme.accent
    road_color = (*accent[:3], 60)
    lw = 3 * s
    # Diagonal main road
    draw.line([(x, y + h * 3 // 4), (x + w, y + h // 4)],
              fill=road_color, width=lw)
    # Horizontal main road
    draw.line([(x, y + h // 2), (x + w, y + h // 2)],
              fill=road_color, width=lw)
    # Curved "river" — approximate with line segments
    river_color = (40, 60, 80, 40)
    prev = None
    for i in range(20):
        rx = x + int(w * i / 19)
        ry = y + h // 3 + int(math.sin(i * 0.5) * 20 * s)
        if prev:
            draw.line([prev, (rx, ry)], fill=river_color, width=4 * s)
        prev = (rx, ry)

    # Location dot (pulsing effect — just static for mockup)
    dot_cx = x + w // 2 + 20 * s
    dot_cy = y + h // 2 - 10 * s
    r1 = 5 * s
    r2 = 12 * s
    draw.ellipse([dot_cx - r2, dot_cy - r2, dot_cx + r2, dot_cy + r2],
                 fill=(*accent[:3], 40))
    draw.ellipse([dot_cx - r1, dot_cy - r1, dot_cx + r1, dot_cy + r1],
                 fill=accent)

    # Edge gradient fade overlay (vignette)
    fade = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    fd = ImageDraw.Draw(fade)
    fade_w = 30 * s
    for i in range(fade_w):
        a = int(200 * (1 - i / fade_w))
        fd.line([(i, 0), (i, h)], fill=(map_bg[0], map_bg[1], map_bg[2], a))
        fd.line([(w - i, 0), (w - i, h)], fill=(map_bg[0], map_bg[1], map_bg[2], a))
    for i in range(fade_w):
        a = int(200 * (1 - i / fade_w))
        fd.line([(0, i), (w, i)], fill=(map_bg[0], map_bg[1], map_bg[2], a))
        fd.line([(0, h - i), (w, h - i)], fill=(map_bg[0], map_bg[1], map_bg[2], a))
    img.paste(Image.alpha_composite(
        img.crop((x, y, x + w, y + h)).convert("RGBA"), fade), (x, y))


def draw_car_silhouette(draw, cx, cy, w, h, color, style="outline"):
    """Draw a classic Alfa side-profile car silhouette.

    style: "outline", "filled", or "inverted"
    """
    # Normalized points for a classic coupe profile (0-1 range)
    # Hood → windshield → roof → rear window → trunk → underside
    profile = [
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

    # Scale and translate to target rect
    half_w = w // 2
    half_h = h // 2
    pts = [(cx - half_w + int(px * w), cy - half_h + int(py * h))
           for px, py in profile]

    if style == "filled":
        draw.polygon(pts, fill=color)
    elif style == "inverted":
        draw.polygon(pts, fill=color)
        # Add window cutout (darker)
        win_pts = [
            (0.33, 0.24), (0.38, 0.20), (0.63, 0.18),
            (0.70, 0.20), (0.75, 0.36), (0.33, 0.38),
        ]
        wpts = [(cx - half_w + int(px * w), cy - half_h + int(py * h))
                for px, py in win_pts]
        draw.polygon(wpts, fill=(0, 0, 0))
    else:  # outline
        lw = max(2, w // 120)
        for i in range(len(pts) - 1):
            draw.line([pts[i], pts[i + 1]], fill=color, width=lw)

    # Wheels
    wheel_r = int(w * 0.055)
    wheel_positions = [(0.22, 0.68), (0.78, 0.68)]
    for wx, wy in wheel_positions:
        wcx = cx - half_w + int(wx * w)
        wcy = cy - half_h + int(wy * h)
        if style == "outline":
            draw.ellipse([wcx - wheel_r, wcy - wheel_r,
                          wcx + wheel_r, wcy + wheel_r],
                         outline=color, width=max(2, lw))
        else:
            draw.ellipse([wcx - wheel_r, wcy - wheel_r,
                          wcx + wheel_r, wcy + wheel_r], fill=color)
            if style == "inverted":
                inner_r = int(wheel_r * 0.5)
                draw.ellipse([wcx - inner_r, wcy - inner_r,
                              wcx + inner_r, wcy + inner_r], fill=(0, 0, 0))


def draw_burl_texture(img, draw, x=0, y=0, w=None, h=None):
    """Draw a warm walnut burl wood texture background.

    Uses radial gradient spots and subtle noise for warmth.
    """
    s = SS
    if w is None:
        w = img.width
    if h is None:
        h = img.height

    import random
    rng = random.Random(7)  # Deterministic

    # Base dark walnut
    base = (26, 15, 10)
    draw.rectangle([x, y, x + w, y + h], fill=base)

    # Radial gradient spots (lighter wood grain)
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    for _ in range(15):
        sx = rng.randint(0, w)
        sy = rng.randint(0, h)
        sr = rng.randint(40 * s, 120 * s)
        for ring in range(sr, 0, -2):
            t = ring / sr
            a = int(12 * (1 - t))  # Very subtle
            c = lerp((61, 39, 22), (26, 15, 10), t)
            od.ellipse([sx - ring, sy - ring, sx + ring, sy + ring],
                       fill=(*c, a))

    img.paste(Image.alpha_composite(
        img.crop((x, y, x + w, y + h)).convert("RGBA"), overlay), (x, y))


def draw_corner_accents(draw, x, y, w, h, color, size=None, line_w=None):
    """Draw L-shaped corner bracket accents."""
    s = SS
    if size is None:
        size = 8 * s
    if line_w is None:
        line_w = max(1, s)

    # Top-left
    draw.line([(x, y), (x + size, y)], fill=color, width=line_w)
    draw.line([(x, y), (x, y + size)], fill=color, width=line_w)
    # Top-right
    draw.line([(x + w - size, y), (x + w, y)], fill=color, width=line_w)
    draw.line([(x + w, y), (x + w, y + size)], fill=color, width=line_w)
    # Bottom-left
    draw.line([(x, y + h - size), (x, y + h)], fill=color, width=line_w)
    draw.line([(x, y + h), (x + size, y + h)], fill=color, width=line_w)
    # Bottom-right
    draw.line([(x + w - size, y + h), (x + w, y + h)], fill=color, width=line_w)
    draw.line([(x + w, y + h - size), (x + w, y + h)], fill=color, width=line_w)


def draw_radial_vignette(img, cx, cy, inner_frac=0.6, color=(0, 0, 0)):
    """Draw a radial vignette (transparent center → opaque edges)."""
    w, h = img.size
    vignette = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    vd = ImageDraw.Draw(vignette)
    max_r = math.sqrt(w * w + h * h) / 2
    inner_r = max_r * inner_frac
    steps = 80
    for i in range(steps):
        t = i / steps
        r = inner_r + (max_r - inner_r) * t
        a = int(255 * t * t)  # Quadratic fade
        vd.ellipse([cx - r, cy - r, cx + r, cy + r],
                   fill=(*color[:3], 0), outline=(*color[:3], a), width=max(2, int(max_r / steps)))
    # Simpler approach: draw filled rings from outside in
    vignette2 = Image.new("RGBA", (w, h), (*color[:3], 255))
    mask = Image.new("L", (w, h), 255)
    md = ImageDraw.Draw(mask)
    for i in range(steps + 1):
        t = i / steps
        r = max_r * (1 - t * (1 - inner_frac))
        a = int(255 * (1 - t))
        md.ellipse([cx - r, cy - r, cx + r, cy + r], fill=a)
    vignette2.putalpha(mask)
    return Image.alpha_composite(img, vignette2)


# =========================================================================
#  Screen Renderers
# =========================================================================

# --- Initialization Screens (Step 1.6) ---

def render_init_heritage():
    """Heritage initialization: burl texture + vignette + car sketch + amber glow."""
    s = SS
    img = Image.new("RGBA", (SW, SH), (8, 8, 8, 255))
    draw = ImageDraw.Draw(img)

    # Burl walnut texture background
    draw_burl_texture(img, draw)

    # Radial vignette (transparent center → black 90%)
    img = draw_radial_vignette(img, SW // 2, SH // 2, inner_frac=0.4)
    draw = ImageDraw.Draw(img)

    # Soft amber glow behind car
    glow = Image.new("RGBA", (SW, SH), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    glow_r = 180 * s
    for r in range(glow_r, 0, -3):
        a = int(25 * (1 - r / glow_r))
        gd.ellipse([SW // 2 - r, SH // 2 - 20 * s - r,
                     SW // 2 + r, SH // 2 - 20 * s + r],
                    fill=(255, 191, 0, a))
    glow = glow.filter(ImageFilter.GaussianBlur(30 * s))
    img = Image.alpha_composite(img, glow)
    draw = ImageDraw.Draw(img)

    # Car silhouette (outline, amber, mix-blend-screen look)
    draw_car_silhouette(draw, SW // 2, SH // 2 - 20 * s,
                        480 * s, 220 * s, (255, 191, 0, 200), "outline")

    # "ALFA ROMEO" text with flanking lines
    brand_y = SH // 2 + 100 * s
    f_brand = _font("regular", 9 * s)
    line_w = 36 * s
    line_color = (255, 191, 0, 100)
    text_spaced_centered(draw, SW // 2, brand_y, "ALFA ROMEO", f_brand,
                         (255, 191, 0), spacing=10 * s)
    # Flanking gradient lines
    text_hw = 80 * s  # approx half-width of text
    draw.line([(SW // 2 - text_hw - line_w - 10 * s, brand_y),
               (SW // 2 - text_hw - 10 * s, brand_y)],
              fill=line_color, width=1)
    draw.line([(SW // 2 + text_hw + 10 * s, brand_y),
               (SW // 2 + text_hw + line_w + 10 * s, brand_y)],
              fill=line_color, width=1)

    # Bottom: progress bar + status text
    bar_y = SH - 100 * s
    bar_w = 144 * s
    bar_h = 2 * s
    draw_progress_bar(draw, SW // 2 - bar_w // 2, bar_y, bar_w, bar_h,
                      0.33, (255, 191, 0, 150), (30, 30, 30))

    # "CHECKING SYSTEMS..." text
    f_status = _font("bold", 8 * s)
    text_spaced_centered(draw, SW // 2, bar_y + 24 * s,
                         "CHECKING SYSTEMS...", f_status,
                         (255, 191, 0, 150), spacing=5 * s)

    # Corner accents
    pad = 24 * s
    draw_corner_accents(draw, pad, pad, SW - 2 * pad, SH - 2 * pad,
                        (255, 191, 0, 50), size=24 * s)

    return img


def render_init_modern():
    """Modern initialization: charcoal bg + blue glow + car + status dots."""
    s = SS
    img = Image.new("RGBA", (SW, SH), (22, 22, 24, 255))
    draw = ImageDraw.Draw(img)

    # Blue radial glow at center
    glow = Image.new("RGBA", (SW, SH), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    glow_r = 200 * s
    for r in range(glow_r, 0, -3):
        a = int(20 * (1 - r / glow_r))
        gd.ellipse([SW // 2 - r, SH // 2 - r, SW // 2 + r, SH // 2 + r],
                    fill=(0, 85, 150, a))
    glow = glow.filter(ImageFilter.GaussianBlur(25 * s))
    img = Image.alpha_composite(img, glow)
    draw = ImageDraw.Draw(img)

    # Car silhouette (filled, white/gray, semi-transparent)
    draw_car_silhouette(draw, SW // 2, SH // 2 - 10 * s,
                        420 * s, 200 * s, (255, 255, 255, 60), "filled")

    # "CENTRO STILE ALFA ROMEO" top text
    f_top = _font("regular", 8 * s)
    text_spaced_centered(draw, SW // 2, 60 * s,
                         "CENTRO STILE ALFA ROMEO", f_top,
                         (255, 255, 255, 100), spacing=6 * s)

    # Corner accents (blue/30)
    pad = 32 * s
    draw_corner_accents(draw, pad, pad, SW - 2 * pad, SH - 2 * pad,
                        (0, 85, 150, 76), size=28 * s)

    # Bottom: "SYSTEM INITIALIZING..." + dot indicators + progress bar
    bar_y = SH - 100 * s
    # Progress bar (blue)
    bar_w = 160 * s
    bar_h = 3 * s
    draw_progress_bar(draw, SW // 2 - bar_w // 2, bar_y, bar_w, bar_h,
                      0.5, (0, 85, 150), (40, 40, 45))

    f_status = _font("regular", 8 * s)
    text_spaced_centered(draw, SW // 2, bar_y + 24 * s,
                         "SYSTEM INITIALIZING...", f_status,
                         (255, 255, 255, 120), spacing=4 * s)

    # Dot indicators
    dot_y = bar_y + 50 * s
    for i in range(3):
        dx = SW // 2 + (i - 1) * 12 * s
        r = 3 * s
        c = (0, 85, 150) if i < 2 else (60, 60, 65)
        draw.ellipse([dx - r, dot_y - r, dx + r, dot_y + r], fill=c)

    return img


def render_init_autodelta():
    """Autodelta initialization: black bg + scanlines + crosshair + boot text."""
    s = SS
    img = Image.new("RGBA", (SW, SH), (0, 0, 0, 255))
    draw = ImageDraw.Draw(img)

    # Scanline texture (horizontal lines at low opacity)
    scanline = Image.new("RGBA", (SW, SH), (0, 0, 0, 0))
    sd = ImageDraw.Draw(scanline)
    for y_line in range(0, SH, 4 * s):
        sd.line([(0, y_line), (SW, y_line)],
                fill=(236, 91, 19, 12), width=1)
    img = Image.alpha_composite(img, scanline)
    draw = ImageDraw.Draw(img)

    # Crosshair lines at center
    cx, cy = SW // 2, SH // 2 - 20 * s
    line_color = (236, 91, 19, 40)
    draw.line([(cx, 0), (cx, SH)], fill=line_color, width=1)
    draw.line([(0, cy), (SW, cy)], fill=line_color, width=1)

    # Car silhouette (inverted — orange filled with dark windows)
    draw_car_silhouette(draw, cx, cy, 400 * s, 190 * s,
                        (236, 91, 19, 100), "inverted")

    # Corner accents (orange TL/BR, white TR/BL)
    pad = 24 * s
    accent_size = 24 * s
    lw = max(1, 2 * s)
    # Top-left & bottom-right: orange
    draw.line([(pad, pad), (pad + accent_size, pad)], fill=(236, 91, 19, 120), width=lw)
    draw.line([(pad, pad), (pad, pad + accent_size)], fill=(236, 91, 19, 120), width=lw)
    draw.line([(SW - pad - accent_size, SH - pad), (SW - pad, SH - pad)],
              fill=(236, 91, 19, 120), width=lw)
    draw.line([(SW - pad, SH - pad - accent_size), (SW - pad, SH - pad)],
              fill=(236, 91, 19, 120), width=lw)
    # Top-right & bottom-left: white
    draw.line([(SW - pad - accent_size, pad), (SW - pad, pad)], fill=(255, 255, 255, 80), width=lw)
    draw.line([(SW - pad, pad), (SW - pad, pad + accent_size)], fill=(255, 255, 255, 80), width=lw)
    draw.line([(pad, SH - pad - accent_size), (pad, SH - pad)], fill=(255, 255, 255, 80), width=lw)
    draw.line([(pad, SH - pad), (pad + accent_size, SH - pad)], fill=(255, 255, 255, 80), width=lw)

    # "AUTODELTA CORE ENGAGED" header
    f_header = _font("bold", 12 * s)
    text_spaced_centered(draw, SW // 2, SH // 2 + 120 * s,
                         "AUTODELTA CORE ENGAGED", f_header,
                         (236, 91, 19), spacing=6 * s)

    # Boot text block (left aligned, mono font)
    f_boot = _font("mono", 7 * s)
    boot_lines = [
        "UNIT_ID: BCM-ADF-0156",
        "SENSORS: ONLINE",
        "OBD-II:  CONNECTED",
        "GPS:     ACQUIRING",
        "LTE:     CONNECTED",
    ]
    boot_x = 60 * s
    boot_y = SH // 2 + 150 * s
    for i, line in enumerate(boot_lines):
        c = (236, 91, 19, 180) if "ONLINE" in line or "CONNECTED" in line else (113, 113, 122)
        draw.text((boot_x, boot_y + i * 14 * s), line, font=f_boot, fill=c)

    # Bottom: progress bar + status
    bar_y = SH - 80 * s
    bar_w = 200 * s
    bar_h = 3 * s
    draw_progress_bar(draw, SW // 2 - bar_w // 2, bar_y, bar_w, bar_h,
                      0.66, (236, 91, 19), (30, 30, 30))

    f_status = _font("bold", 7 * s)
    text_spaced_centered(draw, SW // 2, bar_y + 18 * s,
                         "INITIALIZING SYSTEMS...", f_status,
                         (113, 113, 122), spacing=4 * s)

    return img


def render_initialization(theme):
    """Dispatch to theme-specific initialization renderer."""
    if theme.name == "heritage":
        return render_init_heritage()
    elif theme.name == "modern":
        return render_init_modern()
    elif theme.name == "autodelta":
        return render_init_autodelta()


# --- A1 Main Screens (Step 1.7) ---

def render_a1_heritage():
    """Heritage A1: Engine temp + notifications + fuel + media + stats."""
    s = SS
    img, draw, (cx, cy, cw, ch) = render_frame(HERITAGE, active_nav=0,
                                                 bg_override=(26, 15, 10))
    # Apply burl texture to content area
    draw_burl_texture(img, draw, cx - 16 * s, cy, cw + 32 * s, ch)
    draw = ImageDraw.Draw(img)

    pad = 12 * s
    # 3-column layout: engine | notifications | fuel
    col1_w = int(cw * 0.22)
    col3_w = int(cw * 0.22)
    col2_w = cw - col1_w - col3_w - pad * 2
    col1_x = cx
    col2_x = col1_x + col1_w + pad
    col3_x = col2_x + col2_w + pad

    # --- Column 1: Engine Temp ---
    card_h = int(ch * 0.55)
    draw_card(draw, col1_x, cy + pad, col1_w, card_h,
              fill=(9, 9, 11), border_color=(39, 39, 42))
    # Label
    f_label = _font("bold", 7 * s)
    f_value = _font("bold", 20 * s)
    f_unit = _font("regular", 8 * s)
    draw.text((col1_x + 12 * s, cy + pad + 10 * s), "ENGINE",
              font=f_label, fill=(113, 113, 122))
    draw.text((col1_x + 12 * s, cy + pad + 22 * s), "TEMP",
              font=f_label, fill=(113, 113, 122))
    # Circular gauge
    gauge_cx = col1_x + col1_w // 2
    gauge_cy = cy + pad + card_h // 2 + 15 * s
    gauge_r = int(col1_w * 0.32)
    draw_circle_gauge(draw, gauge_cx, gauge_cy, gauge_r, 0.72,
                      (245, 158, 11), (39, 39, 42), 5 * s)
    text_centered(draw, gauge_cx, gauge_cy - 5 * s, "92°",
                  f_value, (244, 244, 245))
    # "OPTIMAL" label below gauge
    f_small = _font("bold", 6 * s)
    text_centered(draw, gauge_cx, gauge_cy + gauge_r + 12 * s,
                  "OPTIMAL", f_small, (34, 197, 94))

    # --- Column 2: Notification Hub ---
    notif_h = int(ch * 0.55)
    draw_card(draw, col2_x, cy + pad, col2_w, notif_h,
              fill=(9, 9, 11), border_color=(39, 39, 42))
    # Red gradient top accent line
    grad_rect(draw, col2_x, cy + pad, col2_w, 3 * s,
              (220, 38, 38), (220, 38, 38, 0))
    # Header
    f_header = _font("bold", 9 * s)
    draw.text((col2_x + 12 * s, cy + pad + 10 * s), "NOTIFICATIONS",
              font=f_header, fill=(244, 244, 245))
    # 3 notification items
    notifs = [
        ((245, 158, 11), draw_icon_warning, "Tire Pressure Alert", "Front right: 28 psi"),
        ((113, 113, 122), draw_icon_check, "Service Reminder", "Oil change in 1,200 km"),
        ((220, 38, 38), draw_icon_thermometer, "Coolant Warning", "Temperature rising"),
    ]
    item_h = 36 * s
    item_y = cy + pad + 30 * s
    for border_c, icon_fn, title, subtitle in notifs:
        draw_notification_item(draw, col2_x + 8 * s, item_y,
                               col2_w - 16 * s, item_h,
                               HERITAGE, border_c, icon_fn, title, subtitle)
        item_y += item_h + 6 * s

    # --- Column 3: Fuel Level ---
    fuel_h = int(ch * 0.55)
    draw_card(draw, col3_x, cy + pad, col3_w, fuel_h,
              fill=(9, 9, 11), border_color=(39, 39, 42))
    draw.text((col3_x + 12 * s, cy + pad + 10 * s), "FUEL",
              font=f_label, fill=(113, 113, 122))
    draw.text((col3_x + 12 * s, cy + pad + 22 * s), "LEVEL",
              font=f_label, fill=(113, 113, 122))
    # Vertical fuel bar
    bar_x = col3_x + col3_w // 2 - 10 * s
    bar_w_px = 20 * s
    bar_h_px = fuel_h - 80 * s
    bar_y = cy + pad + 50 * s
    draw_progress_bar(draw, bar_x, bar_y, bar_w_px, bar_h_px, 0.0,
                      (0, 0, 0, 0), (39, 39, 42), radius=4 * s)
    # Fill from bottom
    fill_h = int(bar_h_px * 0.64)
    rrect(draw, bar_x, bar_y + bar_h_px - fill_h, bar_w_px, fill_h, 4 * s,
          fill=(245, 158, 11))
    # Percentage
    f_pct = _font("bold", 14 * s)
    text_centered(draw, col3_x + col3_w // 2,
                  bar_y + bar_h_px + 14 * s, "64%", f_pct, (244, 244, 245))
    f_range = _font("regular", 6 * s)
    text_centered(draw, col3_x + col3_w // 2,
                  bar_y + bar_h_px + 30 * s, "EST RANGE: 342 KM",
                  f_range, (113, 113, 122))

    # --- Bottom Row: Now Playing + Stats ---
    bottom_y = cy + pad + int(ch * 0.58)
    bottom_h = ch - int(ch * 0.58) - pad * 2

    # Now playing (left ~30%)
    np_w = int(cw * 0.30)
    draw_card(draw, col1_x, bottom_y, np_w, bottom_h,
              fill=(9, 9, 11), border_color=(39, 39, 42))
    draw_icon_music(draw, col1_x + 20 * s, bottom_y + bottom_h // 2,
                    10 * s, (245, 158, 11))
    f_track = _font("regular", 8 * s)
    f_artist = _font("regular", 7 * s)
    draw.text((col1_x + 38 * s, bottom_y + 10 * s), "Vivere la Vita",
              font=f_track, fill=(244, 244, 245))
    draw.text((col1_x + 38 * s, bottom_y + 24 * s), "Alessandro",
              font=f_artist, fill=(113, 113, 122))

    # Stats (right ~68%)
    stats_x = col1_x + np_w + pad
    stats_w = cw - np_w - pad
    draw_card(draw, stats_x, bottom_y, stats_w, bottom_h,
              fill=(9, 9, 11), border_color=(39, 39, 42))
    # 3 stat items evenly spaced
    stats = [("Avg Speed", "84 km/h"), ("Drive Time", "1h 42m"), ("G-Force", "0.82")]
    stat_item_w = stats_w // 3
    f_stat_label = _font("bold", 6 * s)
    f_stat_val = _font("bold", 11 * s)
    for i, (label, val) in enumerate(stats):
        sx = stats_x + i * stat_item_w + stat_item_w // 2
        text_centered(draw, sx, bottom_y + 10 * s, label, f_stat_label,
                      (113, 113, 122))
        text_centered(draw, sx, bottom_y + 28 * s, val, f_stat_val,
                      (244, 244, 245))

    return img


def render_a1_modern():
    """Modern A1: Light bg, white cards, engine/fuel left, notifications center, status right."""
    s = SS
    img, draw, (cx, cy, cw, ch) = render_frame(MODERN, active_nav=0,
                                                 bg_override=(241, 245, 249))
    pad = 12 * s
    # 3-column layout
    col1_w = int(cw * 0.25)
    col3_w = int(cw * 0.25)
    col2_w = cw - col1_w - col3_w - pad * 2
    col1_x = cx
    col2_x = col1_x + col1_w + pad
    col3_x = col2_x + col2_w + pad

    # --- Column 1: Engine Temp + Fuel (stacked cards) ---
    half_h = (ch - pad * 3) // 2

    # Engine Temp card
    draw_card(draw, col1_x, cy + pad, col1_w, half_h,
              fill=(255, 255, 255), border_color=(226, 232, 240))
    f_label = _font("bold", 7 * s)
    f_value = _font("bold", 18 * s)
    draw.text((col1_x + 12 * s, cy + pad + 8 * s), "ENGINE TEMP",
              font=f_label, fill=(148, 163, 184))
    text_centered(draw, col1_x + col1_w // 2, cy + pad + half_h // 2,
                  "92°C", f_value, (15, 23, 42))
    # Blue progress bar
    bar_y = cy + pad + half_h - 20 * s
    draw_progress_bar(draw, col1_x + 12 * s, bar_y, col1_w - 24 * s, 6 * s,
                      0.72, (0, 85, 150), (226, 232, 240), radius=3 * s)

    # Fuel card
    fuel_y = cy + pad + half_h + pad
    draw_card(draw, col1_x, fuel_y, col1_w, half_h,
              fill=(255, 255, 255), border_color=(226, 232, 240))
    draw.text((col1_x + 12 * s, fuel_y + 8 * s), "FUEL LEVEL",
              font=f_label, fill=(148, 163, 184))
    text_centered(draw, col1_x + col1_w // 2, fuel_y + half_h // 2,
                  "74%", f_value, (15, 23, 42))
    bar_y2 = fuel_y + half_h - 20 * s
    draw_progress_bar(draw, col1_x + 12 * s, bar_y2, col1_w - 24 * s, 6 * s,
                      0.74, (0, 85, 150), (226, 232, 240), radius=3 * s)

    # --- Column 2: Notification Hub ---
    notif_h = ch - pad * 2
    draw_card(draw, col2_x, cy + pad, col2_w, notif_h,
              fill=(255, 255, 255), border_color=(226, 232, 240))
    f_header = _font("bold", 10 * s)
    draw.text((col2_x + 12 * s, cy + pad + 10 * s), "Notifications",
              font=f_header, fill=(15, 23, 42))
    # 3 items
    notifs = [
        ((0, 85, 150), draw_icon_warning, "Tire Pressure Low", "Front right sensor alert"),
        ((148, 163, 184), draw_icon_check, "Service Due", "Oil change in 1,200 km"),
        ((0, 85, 150), draw_icon_route, "Navigation Ready", "Route to Milano set"),
    ]
    item_h = 36 * s
    item_y = cy + pad + 35 * s
    modern_theme_for_notif = Theme("mod_notif", "", card_bg=(248, 250, 252),
                                    card_border=(226, 232, 240),
                                    text=(15, 23, 42), text_dim=(148, 163, 184))
    for border_c, icon_fn, title, subtitle in notifs:
        draw_notification_item(draw, col2_x + 8 * s, item_y,
                               col2_w - 16 * s, item_h,
                               modern_theme_for_notif, border_c, icon_fn, title, subtitle)
        item_y += item_h + 6 * s

    # "View All Notifications" link
    f_link = _font("bold", 7 * s)
    text_centered(draw, col2_x + col2_w // 2, item_y + 8 * s,
                  "View All Notifications", f_link, (0, 85, 150))

    # --- Column 3: Album art placeholder + System Ready ---
    # Album art placeholder
    art_h = int(ch * 0.45)
    draw_card(draw, col3_x, cy + pad, col3_w, art_h,
              fill=(226, 232, 240), border_color=(226, 232, 240))
    draw_icon_music(draw, col3_x + col3_w // 2, cy + pad + art_h // 2,
                    20 * s, (148, 163, 184))
    f_track = _font("bold", 8 * s)
    text_centered(draw, col3_x + col3_w // 2, cy + pad + art_h - 20 * s,
                  "Now Playing", f_track, (100, 116, 139))

    # System Ready card
    sys_y = cy + pad + art_h + pad
    sys_h = ch - art_h - pad * 3
    draw_card(draw, col3_x, sys_y, col3_w, sys_h,
              fill=(255, 255, 255), border_color=(226, 232, 240))
    f_sys = _font("bold", 8 * s)
    text_centered(draw, col3_x + col3_w // 2, sys_y + 12 * s,
                  "SYSTEM READY", f_sys, (22, 163, 74))
    draw_icon_check(draw, col3_x + col3_w // 2, sys_y + sys_h // 2 + 5 * s,
                    15 * s, (22, 163, 74))

    return img


def render_a1_autodelta():
    """Autodelta A1: Black bg, orange accents, coolant/fuel/oil left, status + media right."""
    s = SS
    img, draw, (cx, cy, cw, ch) = render_frame(AUTODELTA, active_nav=0)

    pad = 12 * s
    col1_w = int(cw * 0.30)
    col2_w = cw - col1_w - pad
    col1_x = cx
    col2_x = col1_x + col1_w + pad

    # --- Left Column: 3 vertical gauge bars ---
    gauges = [
        ("COOLANT", "195°F", 0.78, (236, 91, 19)),
        ("FUEL", "82%", 0.82, (236, 91, 19)),
        ("OIL PRESS", "45 psi", 0.60, (255, 255, 255)),
    ]
    gauge_h = (ch - pad * 4) // 3
    f_label = _font("bold", 7 * s)
    f_value = _font("bold", 14 * s)

    for i, (label, val, frac, color) in enumerate(gauges):
        gy = cy + pad + i * (gauge_h + pad)
        draw_card(draw, col1_x, gy, col1_w, gauge_h,
                  fill=(24, 24, 27), border_color=(39, 39, 42))
        draw.text((col1_x + 10 * s, gy + 8 * s), label,
                  font=f_label, fill=(113, 113, 122))
        draw.text((col1_x + 10 * s, gy + 22 * s), val,
                  font=f_value, fill=(255, 255, 255))
        # Progress bar
        bar_y = gy + gauge_h - 16 * s
        draw_progress_bar(draw, col1_x + 10 * s, bar_y,
                          col1_w - 20 * s, 6 * s, frac, color,
                          (39, 39, 42), radius=3 * s)

    # --- Right Column ---
    # "CURRENT STATUS" header
    f_header = _font("bold", 10 * s)
    draw.text((col2_x + 10 * s, cy + pad + 4 * s), "CURRENT STATUS",
              font=f_header, fill=(236, 91, 19))

    # Systems Nominal card
    status_y = cy + pad + 28 * s
    status_h = int(ch * 0.35)
    draw_card(draw, col2_x, status_y, col2_w, status_h,
              fill=(24, 24, 27), border_color=(39, 39, 42))
    # Green check + "Systems Nominal"
    check_cx = col2_x + 30 * s
    check_cy = status_y + status_h // 2
    draw.ellipse([check_cx - 14 * s, check_cy - 14 * s,
                  check_cx + 14 * s, check_cy + 14 * s],
                 fill=(34, 197, 94, 40))
    draw_icon_check(draw, check_cx, check_cy, 10 * s, (34, 197, 94))
    f_nominal = _font("bold", 12 * s)
    draw.text((check_cx + 24 * s, check_cy - 8 * s), "Systems Nominal",
              font=f_nominal, fill=(255, 255, 255))
    f_sub = _font("regular", 7 * s)
    draw.text((check_cx + 24 * s, check_cy + 8 * s),
              "All diagnostics passed", font=f_sub, fill=(113, 113, 122))

    # Media player card at bottom
    media_y = status_y + status_h + pad
    media_h = ch - (media_y - cy) - pad
    draw_card(draw, col2_x, media_y, col2_w, media_h,
              fill=(24, 24, 27), border_color=(39, 39, 42))
    draw_icon_music(draw, col2_x + 24 * s, media_y + media_h // 2,
                    10 * s, (236, 91, 19))
    f_track = _font("bold", 9 * s)
    f_artist = _font("regular", 7 * s)
    draw.text((col2_x + 44 * s, media_y + 12 * s), "Nightcall (Drive OST)",
              font=f_track, fill=(255, 255, 255))
    draw.text((col2_x + 44 * s, media_y + 26 * s), "Kavinsky",
              font=f_artist, fill=(113, 113, 122))
    # Simple playback bar
    pb_y = media_y + media_h - 16 * s
    draw_progress_bar(draw, col2_x + 10 * s, pb_y, col2_w - 20 * s, 3 * s,
                      0.35, (236, 91, 19), (39, 39, 42), radius=2 * s)

    return img


def render_a1_main(theme):
    """Dispatch to theme-specific A1 main renderer."""
    if theme.name == "heritage":
        return render_a1_heritage()
    elif theme.name == "modern":
        return render_a1_modern()
    elif theme.name == "autodelta":
        return render_a1_autodelta()


# --- A2 Trip Screens (Step 1.8) ---

def render_a2_heritage():
    """Heritage A2: Light bg, stat cards left, bar chart right."""
    s = SS
    # Heritage A2 uses light background (#f8f6f6)
    img = Image.new("RGBA", (SW, SH), (248, 246, 246, 255))
    draw = ImageDraw.Draw(img)

    # Custom header (dark bg, heritage style)
    bar_h = 56 * s
    draw.rectangle([0, 0, SW, bar_h], fill=(34, 22, 16))
    draw.line([(0, bar_h - 1), (SW, bar_h - 1)], fill=(236, 91, 19, 50))
    # Header content
    f_time = _font("bold", 14 * s)
    f_date = _font("regular", 10 * s)
    f_brand = _font("bold", 14 * s)
    f_temp = _font("bold", 14 * s)
    draw.text((24 * s, 16 * s), "10:42 AM", font=f_time, fill=(248, 246, 246))
    draw.text((120 * s, 20 * s), "Oct 24", font=f_date, fill=(248, 246, 246, 178))
    text_spaced_centered(draw, SW // 2, bar_h // 2, "ALFA ROMEO", f_brand,
                         (236, 91, 19), spacing=5 * s)
    text_right(draw, SW - 24 * s, 16 * s, "68°F", f_temp, (248, 246, 246))
    # BT + Android icons
    _draw_bt_icon(draw, SW - 100 * s, bar_h // 2, 7 * s, (236, 91, 19))

    # Content area
    content_y = bar_h + 8 * s
    content_h = SH - bar_h - 72 * s

    # Left column: stat cards (300px wide)
    left_w = 300 * s
    left_x = 24 * s
    pad = 12 * s

    f_title = _font("bold", 18 * s)
    f_label = _font("bold", 9 * s)
    f_value = _font("bold", 24 * s)
    f_unit = _font("regular", 12 * s)

    draw.text((left_x, content_y), "Trip A2", font=f_title, fill=(34, 22, 16))

    cards = [
        ("Distance", "142.5", "mi"),
        ("Avg Speed", "48", "mph"),
        ("Travel Time", "2h 58m", ""),
    ]
    card_y = content_y + 30 * s
    card_h = (content_h - 50 * s) // 3 - pad
    for label, val, unit in cards:
        draw_card(draw, left_x, card_y, left_w - 24 * s, card_h,
                  fill=(255, 255, 255), border_color=(236, 91, 19, 25))
        draw.text((left_x + 16 * s, card_y + 8 * s), label.upper(),
                  font=f_label, fill=(34, 22, 16, 178))
        draw.text((left_x + 16 * s, card_y + 24 * s), val,
                  font=f_value, fill=(34, 22, 16))
        if unit:
            tw, _ = text_bbox_size(draw, val, f_value)
            draw.text((left_x + 20 * s + tw, card_y + 32 * s), unit,
                      font=f_unit, fill=(34, 22, 16, 127))
        card_y += card_h + pad

    # Right column: Fuel consumption chart
    right_x = left_x + left_w
    right_w = SW - right_x - 24 * s

    # Header
    f_chart_title = _font("bold", 10 * s)
    f_mpg = _font("bold", 28 * s)
    f_mpg_unit = _font("regular", 14 * s)
    draw.text((right_x + 16 * s, content_y + 4 * s),
              "Avg Fuel Consumption", font=f_chart_title, fill=(34, 22, 16, 178))
    draw.text((right_x + 16 * s, content_y + 20 * s), "28.4",
              font=f_mpg, fill=(236, 91, 19))
    tw_mpg, _ = text_bbox_size(draw, "28.4", f_mpg)
    draw.text((right_x + 20 * s + tw_mpg, content_y + 30 * s), "MPG",
              font=f_mpg_unit, fill=(34, 22, 16, 127))

    # "+1.2%" badge
    badge_x = right_x + right_w - 80 * s
    badge_y = content_y + 10 * s
    rrect(draw, badge_x, badge_y, 65 * s, 18 * s, 9 * s,
          fill=(220, 252, 231))
    f_badge = _font("bold", 7 * s)
    text_centered(draw, badge_x + 32 * s, badge_y + 9 * s, "+1.2%",
                  f_badge, (22, 163, 74))

    # Bar chart
    chart_y = content_y + 60 * s
    chart_h = content_h - 70 * s
    vals = [0.15, 0.25, 0.45, 0.60, 0.75, 0.55, 0.85]
    bar_colors = []
    for i, v in enumerate(vals):
        if i < 3:
            bar_colors.append((34, 22, 16, 50))
        else:
            a = int(100 + 155 * (i - 3) / 3)
            bar_colors.append((236, 91, 19, a))

    draw_card(draw, right_x, chart_y, right_w, chart_h,
              fill=(255, 255, 255), border_color=(236, 91, 19, 25))
    draw_bar_chart(draw, right_x + 10 * s, chart_y + 10 * s,
                   right_w - 20 * s, chart_h - 30 * s, vals, bar_colors,
                   x_labels=["-50m", "-40m", "-30m", "-20m", "-10m", "-5m", "Now"],
                   y_labels=["50", "40", "30", "20", "10"],
                   label_color=(34, 22, 16, 127))

    # Bottom nav (heritage style but light)
    nav_y = SH - 72 * s
    draw.rectangle([0, nav_y, SW, SH], fill=(34, 22, 16))
    draw.line([(0, nav_y), (SW, nav_y)], fill=(236, 91, 19, 50))
    # Nav icons
    item_w = SW // 4
    for i in range(4):
        ix = item_w * i + item_w // 2
        iy = nav_y + 36 * s
        is_active = (i == 3)  # car/trip active
        if is_active:
            c = (236, 91, 19)
        else:
            c = (248, 246, 246, 178)
        NAV_ICONS[i](draw, ix, iy, 12 * s, c)

    return img


def render_a2_modern():
    """Modern A2: Slate bg, trip stats left, line graph right."""
    s = SS
    img, draw, (cx, cy, cw, ch) = render_frame(MODERN, active_nav=1,
                                                 bg_override=(241, 245, 249))
    pad = 12 * s

    # Left column: 1/3
    col1_w = int(cw * 0.33)
    col1_x = cx
    col2_x = col1_x + col1_w + pad
    col2_w = cw - col1_w - pad

    # --- Trip Distance Card ---
    top_h = int(ch * 0.55)
    draw_card(draw, col1_x, cy + pad, col1_w, top_h,
              fill=(255, 255, 255), border_color=(226, 232, 240))
    f_label = _font("bold", 7 * s)
    f_value = _font("bold", 22 * s)
    f_unit = _font("regular", 10 * s)
    draw.text((col1_x + 12 * s, cy + pad + 10 * s), "TRIP A2 DISTANCE",
              font=f_label, fill=(148, 163, 184))
    draw.text((col1_x + 12 * s, cy + pad + 28 * s), "142.8",
              font=f_value, fill=(0, 85, 150))
    tw, _ = text_bbox_size(draw, "142.8", f_value)
    draw.text((col1_x + 16 * s + tw, cy + pad + 36 * s), "km",
              font=f_unit, fill=(148, 163, 184))
    # Duration / Avg Speed at bottom of card
    f_small = _font("bold", 8 * s)
    f_small_val = _font("bold", 11 * s)
    bottom_area = cy + pad + top_h - 40 * s
    draw.text((col1_x + 12 * s, bottom_area), "DURATION",
              font=_font("bold", 6 * s), fill=(148, 163, 184))
    draw.text((col1_x + 12 * s, bottom_area + 12 * s), "01:45 h",
              font=f_small_val, fill=(15, 23, 42))
    text_right(draw, col1_x + col1_w - 12 * s, bottom_area, "AVG SPEED",
               _font("bold", 6 * s), (148, 163, 184))
    text_right(draw, col1_x + col1_w - 12 * s, bottom_area + 12 * s,
               "82 km/h", f_small_val, (15, 23, 42))

    # --- Fuel card (blue accent bg) ---
    fuel_y = cy + pad + top_h + pad
    fuel_h = ch - top_h - pad * 3
    draw_card(draw, col1_x, fuel_y, col1_w, fuel_h,
              fill=(0, 85, 150), border_color=None)
    f_fuel_label = _font("bold", 7 * s)
    f_fuel_val = _font("bold", 18 * s)
    draw.text((col1_x + 12 * s, fuel_y + 10 * s), "AVERAGE FUEL",
              font=f_fuel_label, fill=(255, 255, 255, 178))
    draw.text((col1_x + 12 * s, fuel_y + 28 * s), "6.4",
              font=f_fuel_val, fill=(255, 255, 255))
    tw, _ = text_bbox_size(draw, "6.4", f_fuel_val)
    draw.text((col1_x + 16 * s + tw, fuel_y + 34 * s), "l/100km",
              font=_font("regular", 8 * s), fill=(255, 255, 255, 178))
    # Fuel icon (right side, dim)
    draw_icon_fuel(draw, col1_x + col1_w - 28 * s, fuel_y + fuel_h // 2,
                   16 * s, (255, 255, 255, 76))

    # --- Right Column: Consumption History ---
    draw_card(draw, col2_x, cy + pad, col2_w, ch - pad * 2,
              fill=(255, 255, 255), border_color=(226, 232, 240))
    f_header = _font("bold", 10 * s)
    draw.text((col2_x + 12 * s, cy + pad + 10 * s), "Consumption History",
              font=f_header, fill=(15, 23, 42))
    # "LAST 30 MIN" badge
    badge_x = col2_x + col2_w - 90 * s
    rrect(draw, badge_x, cy + pad + 8 * s, 78 * s, 16 * s, 4 * s,
          fill=(241, 245, 249))
    f_badge = _font("bold", 6 * s)
    text_centered(draw, badge_x + 39 * s, cy + pad + 16 * s,
                  "LAST 30 MIN", f_badge, (148, 163, 184))

    # Line graph
    graph_y = cy + pad + 40 * s
    graph_h = ch - 130 * s
    pts = [0.3, 0.5, 0.35, 0.6, 0.45, 0.7, 0.35, 0.55, 0.8, 0.45, 0.65]
    draw_line_graph(img, draw, col2_x + 30 * s, graph_y,
                    col2_w - 50 * s, graph_h, pts,
                    (0, 85, 150), fill_color=(0, 85, 150, 30),
                    highlight_idx=8)
    draw = ImageDraw.Draw(img)

    # Y-axis labels
    f_axis = _font("bold", 6 * s)
    for i, lbl in enumerate(["15L", "10L", "5L", "0L"]):
        ly = graph_y + int(graph_h * i / 3)
        draw.text((col2_x + 10 * s, ly - 4 * s), lbl, font=f_axis,
                  fill=(148, 163, 184))

    # Bottom stats
    stat_y = cy + ch - pad - 40 * s
    draw.line([(col2_x + 12 * s, stat_y), (col2_x + col2_w - 12 * s, stat_y)],
              fill=(241, 245, 249))
    f_stat_l = _font("bold", 6 * s)
    f_stat_v = _font("bold", 9 * s)
    draw.text((col2_x + 16 * s, stat_y + 6 * s), "CURRENT", font=f_stat_l,
              fill=(148, 163, 184))
    draw.text((col2_x + 16 * s, stat_y + 18 * s), "7.1 l/100km",
              font=f_stat_v, fill=(15, 23, 42))
    draw.text((col2_x + 120 * s, stat_y + 6 * s), "PEAK", font=f_stat_l,
              fill=(148, 163, 184))
    draw.text((col2_x + 120 * s, stat_y + 18 * s), "12.4 l/100km",
              font=f_stat_v, fill=(15, 23, 42))

    # "DRIVING STYLE: DYNAMIC" badge (red)
    dyn_x = col2_x + col2_w - 170 * s
    dyn_y = stat_y + 8 * s
    rrect(draw, dyn_x, dyn_y, 158 * s, 22 * s, 6 * s, fill=(254, 242, 242))
    draw_icon_eco(draw, dyn_x + 12 * s, dyn_y + 11 * s, 6 * s, (239, 68, 68))
    f_dyn = _font("bold", 6 * s)
    draw.text((dyn_x + 24 * s, dyn_y + 5 * s), "DRIVING STYLE: DYNAMIC",
              font=f_dyn, fill=(220, 38, 38))

    return img


def render_a2_autodelta():
    """Autodelta A2: Black bg, bento grid, bar chart, speed, efficiency ring, range."""
    s = SS
    img, draw, (cx, cy, cw, ch) = render_frame(AUTODELTA, active_nav=1)

    pad = 10 * s

    # Dashboard header
    f_title = _font("bold", 14 * s)
    f_subtitle = _font("regular", 7 * s)
    f_dist = _font("bold", 18 * s)
    f_dist_unit = _font("regular", 8 * s)
    draw.text((cx, cy + 6 * s), "Autodelta Sport A2", font=f_title,
              fill=(236, 91, 19))
    draw.text((cx, cy + 24 * s), "TRIP STATISTICS & ANALYTICS",
              font=f_subtitle, fill=(113, 113, 122))
    text_right(draw, cx + cw, cy + 6 * s, "142.8", font=f_dist,
               fill=(255, 255, 255))
    text_right(draw, cx + cw, cy + 26 * s, "KM · CURRENT SESSION",
               font=f_subtitle, fill=(113, 113, 122))

    # Bento grid starts below header
    grid_y = cy + 44 * s
    grid_h = ch - 48 * s

    # Row 1 (60% height): consumption chart (left 2/3) + speed/efficiency (right 1/3)
    r1_h = int(grid_h * 0.58)
    r2_h = grid_h - r1_h - pad

    left_w = int(cw * 0.64)
    right_w = cw - left_w - pad

    # --- Consumption bar chart ---
    draw_card(draw, cx, grid_y, left_w, r1_h,
              fill=(24, 24, 27, 127), border_color=(39, 39, 42))
    f_chart_label = _font("bold", 7 * s)
    draw.text((cx + 12 * s, grid_y + 8 * s), "FUEL CONSUMPTION L/100KM",
              font=f_chart_label, fill=(113, 113, 122))
    # Bars
    bar_vals = [0.3, 0.4, 0.6, 0.5, 0.35, 0.45, 0.7, 0.8, 0.25, 0.55, 0.4, 0.5]
    bar_cols = []
    for i, v in enumerate(bar_vals):
        if v > 0.6:
            bar_cols.append((236, 91, 19, int(255 * min(1, v + 0.2))))
        else:
            bar_cols.append((39, 39, 42))
    draw_bar_chart(draw, cx + 10 * s, grid_y + 28 * s,
                   left_w - 20 * s, r1_h - 60 * s, bar_vals, bar_cols,
                   x_labels=["0km", "40km", "80km", "120km", "Cur"],
                   label_color=(113, 113, 122))

    # --- Avg Speed card ---
    speed_h = (r1_h - pad) // 2
    draw_card(draw, cx + left_w + pad, grid_y, right_w, speed_h,
              fill=(24, 24, 27, 127), border_color=(39, 39, 42))
    draw.text((cx + left_w + pad + 12 * s, grid_y + 8 * s), "AVG SPEED",
              font=_font("bold", 6 * s), fill=(113, 113, 122))
    f_big = _font("bold", 24 * s)
    draw.text((cx + left_w + pad + 12 * s, grid_y + 22 * s), "84",
              font=f_big, fill=(255, 255, 255))
    tw84, _ = text_bbox_size(draw, "84", f_big)
    draw.text((cx + left_w + pad + 16 * s + tw84, grid_y + 30 * s), "KM/H",
              font=_font("bold", 8 * s), fill=(236, 91, 19))

    # --- Efficiency gauge card ---
    eff_y = grid_y + speed_h + pad
    draw_card(draw, cx + left_w + pad, eff_y, right_w, speed_h,
              fill=(24, 24, 27, 127), border_color=(39, 39, 42))
    draw.text((cx + left_w + pad + 12 * s, eff_y + 8 * s), "EFFICIENCY",
              font=_font("bold", 6 * s), fill=(113, 113, 122))
    # Circle gauge
    gauge_cx = cx + left_w + pad + 36 * s
    gauge_cy = eff_y + speed_h // 2 + 8 * s
    gauge_r = 18 * s
    draw_circle_gauge(draw, gauge_cx, gauge_cy, gauge_r, 0.75,
                      (236, 91, 19), (39, 39, 42), 4 * s)
    text_centered(draw, gauge_cx, gauge_cy, "75", _font("bold", 8 * s),
                  (255, 255, 255))
    draw.text((gauge_cx + gauge_r + 8 * s, gauge_cy - 8 * s), "OPTIMAL",
              font=_font("bold", 7 * s), fill=(255, 255, 255))
    draw.text((gauge_cx + gauge_r + 8 * s, gauge_cy + 4 * s), "ZONE",
              font=_font("regular", 7 * s), fill=(113, 113, 122))

    # --- Row 2: Range + Active Driving ---
    r2_y = grid_y + r1_h + pad
    half_w = (cw - pad) // 2

    # Range Remaining (orange border)
    draw_card(draw, cx, r2_y, half_w, r2_h,
              fill=(9, 9, 11), border_color=(236, 91, 19, 76))
    draw.text((cx + 12 * s, r2_y + 8 * s), "RANGE REMAINING",
              font=_font("bold", 6 * s), fill=(113, 113, 122))
    draw.text((cx + 12 * s, r2_y + 22 * s), "412",
              font=_font("bold", 18 * s), fill=(255, 255, 255))
    tw412, _ = text_bbox_size(draw, "412", _font("bold", 18 * s))
    draw.text((cx + 16 * s + tw412, r2_y + 28 * s), "KM",
              font=_font("bold", 8 * s), fill=(236, 91, 19))
    # Fuel icon in circle
    icon_cx = cx + half_w - 28 * s
    icon_cy = r2_y + r2_h // 2
    draw.ellipse([icon_cx - 16 * s, icon_cy - 16 * s,
                  icon_cx + 16 * s, icon_cy + 16 * s],
                 outline=(236, 91, 19, 50), width=2 * s)
    draw_icon_fuel(draw, icon_cx, icon_cy, 10 * s, (236, 91, 19))

    # Active Driving
    draw_card(draw, cx + half_w + pad, r2_y, half_w, r2_h,
              fill=(24, 24, 27, 127), border_color=(39, 39, 42))
    draw.text((cx + half_w + pad + 12 * s, r2_y + 8 * s), "ACTIVE DRIVING",
              font=_font("bold", 6 * s), fill=(113, 113, 122))
    draw.text((cx + half_w + pad + 12 * s, r2_y + 22 * s), "01:54",
              font=_font("bold", 18 * s), fill=(255, 255, 255))
    tw_time, _ = text_bbox_size(draw, "01:54", _font("bold", 18 * s))
    draw.text((cx + half_w + pad + 16 * s + tw_time, r2_y + 28 * s), "HRS",
              font=_font("bold", 8 * s), fill=(113, 113, 122))

    return img


def render_a2_trip(theme):
    """Dispatch to theme-specific A2 trip renderer."""
    if theme.name == "heritage":
        return render_a2_heritage()
    elif theme.name == "modern":
        return render_a2_modern()
    elif theme.name == "autodelta":
        return render_a2_autodelta()


# --- A3 Weather Screens (Step 1.9) ---

def _draw_cloud_icon_large(draw, cx, cy, size, color):
    """Draw a larger, more detailed cloud icon for weather displays."""
    s = size
    # Main body
    draw.ellipse([cx - s * 0.8, cy - s * 0.1, cx + s * 0.8, cy + s * 0.6], fill=color)
    # Top bump
    draw.ellipse([cx - s * 0.3, cy - s * 0.6, cx + s * 0.5, cy + s * 0.2], fill=color)
    # Left bump
    draw.ellipse([cx - s * 0.9, cy - s * 0.2, cx - s * 0.1, cy + s * 0.5], fill=color)
    # Right bump
    draw.ellipse([cx + s * 0.1, cy - s * 0.4, cx + s * 0.7, cy + s * 0.3], fill=color)


def _draw_sun_partial(draw, cx, cy, size, sun_color, cloud_color):
    """Draw a sun partially hidden by cloud."""
    s = size
    # Sun circle (top-right)
    draw.ellipse([cx + s * 0.2, cy - s * 0.7, cx + s * 0.9, cy],
                 fill=sun_color)
    # Sun rays
    for angle in range(0, 360, 45):
        a = math.radians(angle)
        rx = cx + s * 0.55 + int(s * 0.5 * math.cos(a))
        ry = cy - s * 0.35 + int(s * 0.5 * math.sin(a))
        draw.line([(cx + s * 0.55, cy - s * 0.35), (rx, ry)],
                  fill=(*sun_color[:3], 100), width=max(1, s // 10))
    # Cloud on top
    _draw_cloud_icon_large(draw, cx - s * 0.2, cy + s * 0.1, s * 0.6, cloud_color)


def render_a3_heritage():
    """Heritage A3: Dark burl bg, weather left, map placeholder right."""
    s = SS
    img, draw, (cx, cy, cw, ch) = render_frame(HERITAGE, active_nav=2,
                                                 bg_override=(26, 15, 10))
    draw_burl_texture(img, draw, cx - 16 * s, cy, cw + 32 * s, ch)
    draw = ImageDraw.Draw(img)

    pad = 12 * s
    col1_w = int(cw * 0.33)
    col2_w = cw - col1_w - pad
    col1_x = cx
    col2_x = col1_x + col1_w + pad

    # --- Left: Weather Info ---
    weather_h = ch - pad * 2
    draw_card(draw, col1_x, cy + pad, col1_w, weather_h,
              fill=(9, 9, 11, 200), border_color=(39, 39, 42))

    f_city = _font("bold", 12 * s)
    f_cond = _font("regular", 8 * s)
    f_temp = _font("bold", 32 * s)
    f_feels = _font("regular", 7 * s)

    draw.text((col1_x + 14 * s, cy + pad + 10 * s), "Milan, IT",
              font=f_city, fill=(244, 244, 245))
    draw.text((col1_x + 14 * s, cy + pad + 28 * s), "Partly Cloudy",
              font=f_cond, fill=(161, 161, 170))

    # Cloud icon
    _draw_sun_partial(draw, col1_x + col1_w // 2, cy + pad + 70 * s,
                      20 * s, (245, 158, 11), (161, 161, 170))

    # Temperature
    draw.text((col1_x + 14 * s, cy + pad + 100 * s), "72°",
              font=f_temp, fill=(244, 244, 245))
    draw.text((col1_x + 14 * s, cy + pad + 140 * s), "Feels like 74°",
              font=f_feels, fill=(113, 113, 122))

    # 3-day forecast
    forecast = [("Today", "75°", "55°"), ("Wed", "68°", "52°"), ("Thu", "62°", "48°")]
    f_day = _font("bold", 7 * s)
    f_hi = _font("bold", 9 * s)
    f_lo = _font("regular", 7 * s)
    fc_y = cy + pad + 170 * s
    for day, hi, lo in forecast:
        draw.line([(col1_x + 14 * s, fc_y), (col1_x + col1_w - 14 * s, fc_y)],
                  fill=(39, 39, 42))
        draw.text((col1_x + 14 * s, fc_y + 6 * s), day, font=f_day,
                  fill=(161, 161, 170))
        text_right(draw, col1_x + col1_w - 14 * s, fc_y + 4 * s,
                   f"{hi}/{lo}", f_hi, (244, 244, 245))
        fc_y += 32 * s

    # --- Right: Map Placeholder ---
    draw_card(draw, col2_x, cy + pad, col2_w, weather_h,
              fill=(15, 15, 18), border_color=(39, 39, 42))
    draw_simple_map(img, draw, col2_x + 2 * s, cy + pad + 2 * s,
                    col2_w - 4 * s, weather_h - 4 * s, HERITAGE)
    draw = ImageDraw.Draw(img)

    # Search bar overlay at top of map
    search_y = cy + pad + 10 * s
    search_w = col2_w - 30 * s
    rrect(draw, col2_x + 15 * s, search_y, search_w, 24 * s, 6 * s,
          fill=(0, 0, 0, 150))
    draw.text((col2_x + 26 * s, search_y + 5 * s), "Search location...",
              font=_font("regular", 8 * s), fill=(113, 113, 122))

    # "Weather Radar" button at bottom
    btn_y = cy + pad + weather_h - 34 * s
    btn_w = 120 * s
    rrect(draw, col2_x + col2_w // 2 - btn_w // 2, btn_y, btn_w, 22 * s,
          8 * s, fill=(245, 158, 11, 50))
    text_centered(draw, col2_x + col2_w // 2, btn_y + 11 * s,
                  "Weather Radar", _font("bold", 7 * s), (245, 158, 11))

    return img


def render_a3_modern():
    """Modern A3: Black bg, map left, glass weather card right."""
    s = SS
    # Modern A3 uses dark bg for the map area
    img = Image.new("RGBA", (SW, SH), (0, 0, 0, 255))
    draw = ImageDraw.Draw(img)

    # App bar (modern style)
    draw_app_bar(img, draw, MODERN)
    draw_nav_bar(img, draw, MODERN, active_index=2)

    cy = APPBAR_H * s
    ch = CONTENT_H * s
    pad = 12 * s

    # Layout: map 8/12 left, weather 4/12 right
    map_w = int(SW * 8 / 12)
    card_w = SW - map_w

    # --- Map (left side, full height) ---
    draw_simple_map(img, draw, 0, cy, map_w, ch, MODERN)
    draw = ImageDraw.Draw(img)

    # Glass location card on map
    loc_card_w = 220 * s
    loc_card_h = 40 * s
    loc_x = 20 * s
    loc_y = cy + ch - 60 * s
    # Glass effect
    glass = Image.new("RGBA", (loc_card_w, loc_card_h), (255, 255, 255, 200))
    gd = ImageDraw.Draw(glass)
    gd.rounded_rectangle([0, 0, loc_card_w, loc_card_h], radius=8 * s,
                         fill=(255, 255, 255, 200))
    img.paste(Image.alpha_composite(
        img.crop((loc_x, loc_y, loc_x + loc_card_w, loc_y + loc_card_h)).convert("RGBA"),
        glass), (loc_x, loc_y))
    draw = ImageDraw.Draw(img)
    draw.text((loc_x + 12 * s, loc_y + 6 * s),
              "Via Alessandro Volta, Milan",
              font=_font("bold", 8 * s), fill=(15, 23, 42))
    draw.text((loc_x + 12 * s, loc_y + 22 * s), "Current Location",
              font=_font("regular", 6 * s), fill=(100, 116, 139))

    # --- Weather Card (right side) ---
    card_x = map_w
    draw.rectangle([card_x, cy, SW, cy + ch], fill=(15, 15, 20))

    # Glass-style background
    glass_bg = Image.new("RGBA", (card_w, ch), (255, 255, 255, 20))
    img.paste(Image.alpha_composite(
        img.crop((card_x, cy, card_x + card_w, cy + ch)).convert("RGBA"),
        glass_bg), (card_x, cy))
    draw = ImageDraw.Draw(img)

    f_cond = _font("regular", 9 * s)
    f_temp = _font("bold", 36 * s)
    f_small = _font("regular", 7 * s)
    f_label = _font("bold", 6 * s)

    draw.text((card_x + 16 * s, cy + 16 * s), "Partly Cloudy",
              font=f_cond, fill=(200, 200, 210))
    draw.text((card_x + 16 * s, cy + 36 * s), "18°",
              font=f_temp, fill=(255, 255, 255))
    draw.text((card_x + 16 * s, cy + 80 * s), "L:14°  H:21°",
              font=f_small, fill=(148, 163, 184))

    # Cloud icon
    _draw_sun_partial(draw, card_x + card_w - 50 * s, cy + 50 * s,
                      18 * s, (245, 200, 60), (180, 180, 190))

    # Hourly forecast (3 columns)
    hour_y = cy + 110 * s
    draw.line([(card_x + 16 * s, hour_y), (card_x + card_w - 16 * s, hour_y)],
              fill=(255, 255, 255, 30))
    hours = [("14:00", "18°"), ("15:00", "17°"), ("16:00", "16°")]
    col_w = (card_w - 32 * s) // 3
    for i, (hr, tmp) in enumerate(hours):
        hx = card_x + 16 * s + i * col_w + col_w // 2
        draw.text((hx - 12 * s, hour_y + 8 * s), hr, font=f_label,
                  fill=(148, 163, 184))
        draw.text((hx - 8 * s, hour_y + 22 * s), tmp,
                  font=_font("bold", 10 * s), fill=(255, 255, 255))

    # Wind + Humidity
    info_y = hour_y + 50 * s
    draw.line([(card_x + 16 * s, info_y), (card_x + card_w - 16 * s, info_y)],
              fill=(255, 255, 255, 30))
    draw.text((card_x + 16 * s, info_y + 8 * s), "WIND", font=f_label,
              fill=(148, 163, 184))
    draw.text((card_x + 16 * s, info_y + 20 * s), "12 km/h",
              font=_font("bold", 9 * s), fill=(255, 255, 255))
    draw.text((card_x + 16 * s, info_y + 42 * s), "HUMIDITY", font=f_label,
              fill=(148, 163, 184))
    draw.text((card_x + 16 * s, info_y + 54 * s), "42%",
              font=_font("bold", 9 * s), fill=(255, 255, 255))

    return img


def render_a3_autodelta():
    """Autodelta A3: Black bg, bento grid, weather hero + map + forecast strip."""
    s = SS
    img, draw, (cx, cy, cw, ch) = render_frame(AUTODELTA, active_nav=2)

    pad = 10 * s
    # Top row (65% height): weather hero (left 5/12) + map (right 7/12)
    r1_h = int(ch * 0.62)
    r2_h = ch - r1_h - pad

    hero_w = int(cw * 5 / 12)
    map_w = cw - hero_w - pad

    # --- Weather Hero Card ---
    draw_card(draw, cx, cy + pad, hero_w, r1_h,
              fill=(24, 24, 27, 127), border_color=(39, 39, 42))

    f_city = _font("bold", 10 * s)
    f_cond = _font("regular", 8 * s)
    f_temp = _font("bold", 36 * s)

    draw.text((cx + 14 * s, cy + pad + 10 * s), "MILANO, IT",
              font=f_city, fill=(236, 91, 19))
    draw.text((cx + 14 * s, cy + pad + 26 * s), "Partly Cloudy",
              font=f_cond, fill=(161, 161, 170))

    # Cloud bg (faded)
    _draw_cloud_icon_large(draw, cx + hero_w - 40 * s, cy + pad + 50 * s,
                           30 * s, (236, 91, 19, 30))

    draw.text((cx + 14 * s, cy + pad + 60 * s), "24°",
              font=f_temp, fill=(255, 255, 255))
    draw.text((cx + 14 * s, cy + pad + 100 * s), "Feels like 26°",
              font=_font("regular", 7 * s), fill=(113, 113, 122))

    # Wind + humidity in hero
    info_y = cy + pad + r1_h - 40 * s
    draw.text((cx + 14 * s, info_y), "Wind: 15 km/h",
              font=_font("regular", 7 * s), fill=(161, 161, 170))
    draw.text((cx + 14 * s, info_y + 14 * s), "Humidity: 38%",
              font=_font("regular", 7 * s), fill=(161, 161, 170))

    # --- Map Placeholder ---
    map_x = cx + hero_w + pad
    draw_card(draw, map_x, cy + pad, map_w, r1_h,
              fill=(15, 15, 18), border_color=(39, 39, 42))
    draw_simple_map(img, draw, map_x + 2 * s, cy + pad + 2 * s,
                    map_w - 4 * s, r1_h - 4 * s, AUTODELTA)
    draw = ImageDraw.Draw(img)

    # Location label on map
    label_y = cy + pad + r1_h - 28 * s
    rrect(draw, map_x + 10 * s, label_y, map_w - 20 * s, 20 * s, 4 * s,
          fill=(0, 0, 0, 180))
    draw.text((map_x + 20 * s, label_y + 4 * s),
              "Live Tracking \u2022 Viale Monza",
              font=_font("bold", 7 * s), fill=(236, 91, 19))

    # --- Bottom row: Forecast strip ---
    strip_y = cy + pad + r1_h + pad
    draw_card(draw, cx, strip_y, cw, r2_h,
              fill=(24, 24, 27, 127), border_color=(39, 39, 42))

    # 3 day forecast cards + stats
    days = [("TODAY", "26°", "18°"), ("WED", "22°", "15°"), ("THU", "19°", "13°")]
    day_w = int(cw * 0.18)
    f_day = _font("bold", 7 * s)
    f_hi = _font("bold", 12 * s)
    f_lo = _font("regular", 8 * s)

    for i, (day, hi, lo) in enumerate(days):
        dx = cx + 10 * s + i * (day_w + 8 * s)
        dy = strip_y + 8 * s
        draw_card(draw, dx, dy, day_w, r2_h - 16 * s,
                  fill=(9, 9, 11), border_color=(39, 39, 42))
        text_centered(draw, dx + day_w // 2, dy + 10 * s, day, f_day,
                      (236, 91, 19))
        text_centered(draw, dx + day_w // 2, dy + 30 * s, hi, f_hi,
                      (255, 255, 255))
        text_centered(draw, dx + day_w // 2, dy + 48 * s, lo, f_lo,
                      (113, 113, 122))

    # Stats at right side of strip
    stats = [("WIND", "15 km/h"), ("HUMIDITY", "38%"), ("UV INDEX", "6")]
    stat_x = cx + 10 * s + 3 * (day_w + 8 * s) + 10 * s
    stat_w = (cw - stat_x + cx) // 3
    for i, (label, val) in enumerate(stats):
        sx = stat_x + i * stat_w
        sy = strip_y + 14 * s
        draw.text((sx, sy), label, font=_font("bold", 6 * s),
                  fill=(113, 113, 122))
        draw.text((sx, sy + 14 * s), val, font=_font("bold", 10 * s),
                  fill=(255, 255, 255))

    return img


def render_a3_weather(theme):
    """Dispatch to theme-specific A3 weather renderer."""
    if theme.name == "heritage":
        return render_a3_heritage()
    elif theme.name == "modern":
        return render_a3_modern()
    elif theme.name == "autodelta":
        return render_a3_autodelta()


# --- A4 Service Screens (Step 1.10) ---

def render_a4_heritage():
    """Heritage A4: Light bg, car silhouette left, diagnostics right."""
    s = SS
    # Light bg like Heritage A2
    img = Image.new("RGBA", (SW, SH), (248, 246, 246, 255))
    draw = ImageDraw.Draw(img)

    # Custom header
    bar_h = 56 * s
    draw.rectangle([0, 0, SW, bar_h], fill=(34, 22, 16))
    draw.line([(0, bar_h - 1), (SW, bar_h - 1)], fill=(236, 91, 19, 50))
    f_time = _font("bold", 14 * s)
    f_brand = _font("bold", 14 * s)
    draw.text((24 * s, 16 * s), "10:42 AM", font=f_time, fill=(248, 246, 246))
    text_spaced_centered(draw, SW // 2, bar_h // 2, "ALFA ROMEO", f_brand,
                         (236, 91, 19), spacing=5 * s)
    text_right(draw, SW - 24 * s, 16 * s, "68°F", f_time, (248, 246, 246))

    cy = bar_h + 8 * s
    ch = SH - bar_h - 72 * s
    pad = 12 * s

    # Left ~45%: Car silhouette in white card
    left_w = int(SW * 0.45)
    left_x = 24 * s
    car_card_h = ch - pad
    draw_card(draw, left_x, cy + pad, left_w - 24 * s, car_card_h,
              fill=(255, 255, 255), border_color=(236, 91, 19, 25))
    draw_car_silhouette(draw, left_x + (left_w - 24 * s) // 2,
                        cy + pad + car_card_h // 2 - 20 * s,
                        int(left_w * 0.75), int(car_card_h * 0.45),
                        (34, 22, 16, 60), "outline")
    # Car label
    f_car_label = _font("bold", 9 * s)
    text_centered(draw, left_x + (left_w - 24 * s) // 2,
                  cy + pad + car_card_h - 30 * s,
                  "Giulia GTA (1965)", f_car_label, (34, 22, 16, 127))

    # Right ~55%: Diagnostics
    right_x = left_x + left_w
    right_w = SW - right_x - 24 * s

    f_header = _font("bold", 12 * s)
    f_label = _font("bold", 8 * s)
    f_status = _font("bold", 8 * s)
    f_detail = _font("regular", 7 * s)

    draw.text((right_x, cy + pad), "System Status", font=f_header,
              fill=(34, 22, 16))
    # "Last checked" badge
    badge_y = cy + pad + 2 * s
    rrect(draw, right_x + 150 * s, badge_y, 100 * s, 16 * s, 8 * s,
          fill=(226, 232, 240))
    text_centered(draw, right_x + 200 * s, badge_y + 8 * s,
                  "2 min ago", _font("regular", 6 * s), (100, 116, 139))

    # Diagnostic rows
    diags = [
        ("Engine Mechanics", "OK", (34, 197, 94), None),
        ("Tire Pressure", "WARNING", (245, 158, 11), "Front Right Low 28 psi"),
        ("Fluid Levels", "OK", (34, 197, 94), None),
        ("Electrical", "OK", (34, 197, 94), "14.2V"),
    ]
    row_h = 44 * s
    row_y = cy + pad + 28 * s
    for name, status, color, detail in diags:
        draw_card(draw, right_x, row_y, right_w, row_h,
                  fill=(255, 255, 255), border_color=(236, 91, 19, 25))
        # Left accent
        draw.rectangle([right_x, row_y, right_x + 3 * s, row_y + row_h],
                       fill=color)
        # Status icon
        if status == "OK":
            draw_icon_check(draw, right_x + 20 * s, row_y + row_h // 2,
                            8 * s, color)
        else:
            draw_icon_warning(draw, right_x + 20 * s, row_y + row_h // 2,
                              8 * s, color)
        # Text
        draw.text((right_x + 38 * s, row_y + 8 * s), name, font=f_label,
                  fill=(34, 22, 16))
        text_right(draw, right_x + right_w - 12 * s, row_y + 8 * s,
                   status, f_status, color)
        if detail:
            draw.text((right_x + 38 * s, row_y + 24 * s), detail,
                      font=f_detail, fill=(34, 22, 16, 127))
        row_y += row_h + 8 * s

    # Bottom nav
    nav_y = SH - 72 * s
    draw.rectangle([0, nav_y, SW, SH], fill=(34, 22, 16))
    draw.line([(0, nav_y), (SW, nav_y)], fill=(236, 91, 19, 50))
    item_w = SW // 4
    for i in range(4):
        ix = item_w * i + item_w // 2
        iy = nav_y + 36 * s
        c = (236, 91, 19) if i == 3 else (248, 246, 246, 178)
        NAV_ICONS[i](draw, ix, iy, 12 * s, c)

    return img


def render_a4_modern():
    """Modern A4: White bg, engine analytics, oil life, tire pressure cards."""
    s = SS
    img, draw, (cx, cy, cw, ch) = render_frame(MODERN, active_nav=3,
                                                 bg_override=(255, 255, 255))
    pad = 12 * s

    # Header
    f_header = _font("bold", 10 * s)
    f_sub = _font("regular", 7 * s)
    draw.text((cx, cy + 8 * s), "A4 SERVICE", font=f_header, fill=(15, 23, 42))
    draw.text((cx + 100 * s, cy + 10 * s), "/ Detailed Vehicle Diagnostics",
              font=f_sub, fill=(148, 163, 184))

    content_y = cy + 30 * s
    content_h = ch - 34 * s

    # Top row: Engine Analytics (8/12) + Oil Life (4/12)
    top_h = int(content_h * 0.45)
    eng_w = int(cw * 8 / 12) - pad // 2
    oil_w = cw - eng_w - pad

    # Engine Analytics card
    draw_card(draw, cx, content_y, eng_w, top_h,
              fill=(248, 250, 252), border_color=(226, 232, 240))
    draw.text((cx + 14 * s, content_y + 10 * s), "Engine Analytics",
              font=_font("bold", 9 * s), fill=(15, 23, 42))
    # Big PSI value
    draw.text((cx + 14 * s, content_y + 30 * s), "92",
              font=_font("bold", 28 * s), fill=(15, 23, 42))
    tw92, _ = text_bbox_size(draw, "92", _font("bold", 28 * s))
    draw.text((cx + 18 * s + tw92, content_y + 42 * s), "PSI",
              font=_font("bold", 10 * s), fill=(148, 163, 184))
    # Thermal load bar
    draw.text((cx + 14 * s, content_y + top_h - 32 * s), "THERMAL LOAD 78%",
              font=_font("bold", 6 * s), fill=(148, 163, 184))
    draw_progress_bar(draw, cx + 14 * s, content_y + top_h - 18 * s,
                      eng_w - 28 * s, 8 * s, 0.78,
                      (0, 85, 150), (226, 232, 240), radius=4 * s)

    # Oil Life card (dark)
    oil_x = cx + eng_w + pad
    draw_card(draw, oil_x, content_y, oil_w, top_h,
              fill=(15, 23, 42), border_color=None)
    draw.text((oil_x + 14 * s, content_y + 10 * s), "OIL LIFE",
              font=_font("bold", 7 * s), fill=(255, 255, 255, 178))
    draw.text((oil_x + 14 * s, content_y + 30 * s), "84%",
              font=_font("bold", 28 * s), fill=(255, 255, 255))
    # Circle gauge
    gauge_cx = oil_x + oil_w // 2
    gauge_cy = content_y + top_h - 35 * s
    draw_circle_gauge(draw, gauge_cx, gauge_cy, 20 * s, 0.84,
                      (34, 197, 94), (50, 50, 60), 4 * s)

    # Bottom row: 4 tire pressure cards
    tire_y = content_y + top_h + pad
    tire_h = content_h - top_h - pad
    tire_w = (cw - pad * 3) // 4
    tires = [("FL", "2.4", "BAR"), ("FR", "2.4", "BAR"),
             ("RL", "2.2", "BAR"), ("RR", "2.2", "BAR")]
    for i, (pos, val, unit) in enumerate(tires):
        tx = cx + i * (tire_w + pad)
        draw_card(draw, tx, tire_y, tire_w, tire_h,
                  fill=(255, 255, 255), border_color=(226, 232, 240))
        draw.text((tx + 10 * s, tire_y + 6 * s), pos,
                  font=_font("bold", 8 * s), fill=(148, 163, 184))
        text_centered(draw, tx + tire_w // 2, tire_y + tire_h // 2,
                      val, _font("bold", 16 * s), (15, 23, 42))
        text_centered(draw, tx + tire_w // 2, tire_y + tire_h - 16 * s,
                      unit, _font("regular", 7 * s), (148, 163, 184))

    # "EXPORT LOG" button
    btn_w = 100 * s
    btn_x = cx + cw - btn_w
    btn_y = cy + 4 * s
    rrect(draw, btn_x, btn_y, btn_w, 20 * s, 6 * s, fill=(0, 85, 150))
    text_centered(draw, btn_x + btn_w // 2, btn_y + 10 * s,
                  "EXPORT LOG", _font("bold", 7 * s), (255, 255, 255))

    return img


def render_a4_autodelta():
    """Autodelta A4: Black bg, diagnostic cards left, car silhouette right."""
    s = SS
    img, draw, (cx, cy, cw, ch) = render_frame(AUTODELTA, active_nav=3)

    pad = 10 * s
    col1_w = int(cw * 0.35)
    col2_w = cw - col1_w - pad
    col1_x = cx
    col2_x = col1_x + col1_w + pad

    # --- Left: A4 Diagnostics header + 4 cards ---
    f_header = _font("bold", 11 * s)
    draw.text((col1_x, cy + 8 * s), "A4 Diagnostics", font=f_header,
              fill=(236, 91, 19))

    diags = [
        ("Engine Temp", "195°F", 0.78),
        ("Oil Pressure", "45 PSI", 0.60),
        ("Battery", "13.8V", 0.92),
        ("Tire Pressure", "34 PSI", 0.85),
    ]
    card_h = (ch - 40 * s - pad * 3) // 4
    card_y = cy + 30 * s
    f_label = _font("bold", 7 * s)
    f_value = _font("bold", 14 * s)

    for name, val, frac in diags:
        draw_card(draw, col1_x, card_y, col1_w, card_h,
                  fill=(24, 24, 27), border_color=(236, 91, 19, 76))
        draw.text((col1_x + 10 * s, card_y + 6 * s), name.upper(),
                  font=f_label, fill=(113, 113, 122))
        draw.text((col1_x + 10 * s, card_y + 20 * s), val,
                  font=f_value, fill=(255, 255, 255))
        # Progress bar
        bar_y = card_y + card_h - 12 * s
        draw_progress_bar(draw, col1_x + 10 * s, bar_y,
                          col1_w - 20 * s, 4 * s, frac,
                          (236, 91, 19), (39, 39, 42), radius=2 * s)
        card_y += card_h + pad

    # --- Right: Car silhouette in orange-bordered card ---
    car_card_h = ch - pad
    draw_card(draw, col2_x, cy + pad, col2_w, car_card_h,
              fill=(9, 9, 11), border_color=(236, 91, 19, 76))

    # Car silhouette (orange outline)
    draw_car_silhouette(draw, col2_x + col2_w // 2,
                        cy + pad + car_card_h // 2 - 20 * s,
                        int(col2_w * 0.75), int(car_card_h * 0.40),
                        (236, 91, 19, 180), "outline")

    # Car label
    f_car = _font("bold", 9 * s)
    f_car_sub = _font("regular", 7 * s)
    text_centered(draw, col2_x + col2_w // 2,
                  cy + pad + car_card_h - 40 * s,
                  "1600 Junior Z", f_car, (255, 255, 255))
    text_centered(draw, col2_x + col2_w // 2,
                  cy + pad + car_card_h - 24 * s,
                  "Autodelta Sport", f_car_sub, (113, 113, 122))

    return img


def render_a4_service(theme):
    """Dispatch to theme-specific A4 service renderer."""
    if theme.name == "heritage":
        return render_a4_heritage()
    elif theme.name == "modern":
        return render_a4_modern()
    elif theme.name == "autodelta":
        return render_a4_autodelta()


# =========================================================================
#  Main entry point — generate all 15 renders
# =========================================================================

ALL_SCREENS = [
    ("init", render_initialization),
    ("a1_main", render_a1_main),
    ("a2_trip", render_a2_trip),
    ("a3_weather", render_a3_weather),
    ("a4_service", render_a4_service),
]


def generate_all():
    """Generate all 15 PNG mockups (5 screens × 3 themes)."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    count = 0
    for screen_name, render_fn in ALL_SCREENS:
        for theme in ALL_THEMES:
            img = render_fn(theme)
            filename = f"{screen_name}_{theme.name}.png"
            path = os.path.join(OUTPUT_DIR, filename)
            img.resize((W, H), Image.LANCZOS).save(path)
            print(f"  [{count + 1:2d}/15] {filename}")
            count += 1
    print(f"\nDone — {count} renders saved to {OUTPUT_DIR}")


# --- Self-test ---
if __name__ == "__main__":
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    s = SS
    print(f"Step 1.1 self-test: W={W}, H={H}, SS={SS}, SW={SW}, SH={SH}")
    print(f"Layout: APPBAR_H={APPBAR_H}, NAVBAR_H={NAVBAR_H}, CONTENT_H={CONTENT_H}")

    # Test font loading
    f = _font("bold", 36 * s)
    print(f"Font loaded: {f.getname()}")

    # Test drawing primitives on a test image
    img = Image.new("RGBA", (SW, SH), (20, 12, 8, 255))
    draw = ImageDraw.Draw(img)

    # Test rrect
    rrect(draw, 20 * s, 20 * s, 200 * s, 100 * s, 12 * s,
          fill=(40, 30, 25, 255), outline=(255, 191, 0, 100))

    # Test grad_rect
    grad_rect(draw, 240 * s, 20 * s, 200 * s, 100 * s,
              (255, 191, 0), (200, 100, 0))

    # Test text primitives
    font_lg = _font("bold", 24 * s)
    font_sm = _font("regular", 12 * s)
    text_centered(draw, 400 * s, 180 * s, "ALFA ROMEO", font_lg, (255, 191, 0))
    text_right(draw, 780 * s, 200 * s, "21°C", font_sm, (200, 200, 200))
    text_spaced(draw, 20 * s, 250 * s, "HERITAGE", _font("bold", 14 * s),
                (255, 191, 0), spacing=8 * s)
    text_spaced_centered(draw, 400 * s, 300 * s, "CHECKING SYSTEMS",
                         _font("bold", 10 * s), (255, 191, 0, 150), spacing=6 * s)

    # Test thick_arc
    thick_arc(draw, 600 * s, 300 * s, 60 * s, 8 * s, 180, 180,
              (255, 191, 0), (200, 50, 0))

    # Test shadow card
    img = draw_shadow_rrect(img, 20 * s, 340 * s, 300 * s, 100 * s,
                            12 * s, (30, 20, 15, 255))

    # Test text_bbox_size
    tw, th = text_bbox_size(draw, "Test", font_lg)
    print(f"text_bbox_size('Test'): {tw}x{th}")

    # Downsample and save
    out = img.resize((W, H), Image.LANCZOS)
    test_path = os.path.join(OUTPUT_DIR, "_test_step1_1.png")
    out.save(test_path)
    print(f"Saved test image: {test_path}")
    print("Step 1.1 PASSED — all primitives working.")

    # Step 1.2: Verify themes
    print(f"\nStep 1.2: {len(ALL_THEMES)} themes defined")
    for t in ALL_THEMES:
        assert hasattr(t, 'bg'), f"{t.name} missing bg"
        assert hasattr(t, 'accent'), f"{t.name} missing accent"
        assert hasattr(t, 'card_bg'), f"{t.name} missing card_bg"
        assert hasattr(t, 'appbar_bg'), f"{t.name} missing appbar_bg"
        assert hasattr(t, 'navbar_bg'), f"{t.name} missing navbar_bg"
        assert hasattr(t, 'is_light'), f"{t.name} missing is_light"
        print(f"  {t.name}: bg={t.bg} accent={t.accent} is_light={t.is_light}")
    print("Step 1.2 PASSED — all themes verified.")

    # Step 1.3: Verify render_frame for each theme
    print("\nStep 1.3: Testing render_frame for all themes...")
    for t in ALL_THEMES:
        frame_img, frame_draw, cr = render_frame(t, active_nav=1)
        assert frame_img.size == (SW, SH), f"{t.name} wrong size"
        assert len(cr) == 4, f"{t.name} bad content_rect"
        test_path = os.path.join(OUTPUT_DIR, f"_test_step1_3_{t.name}.png")
        frame_img.resize((W, H), Image.LANCZOS).save(test_path)
        print(f"  {t.name}: content_rect={cr} -> {test_path}")
    print("Step 1.3 PASSED — all frames rendered.")

    # Step 1.4: Test card/icon primitives
    print("\nStep 1.4: Testing card, progress, icon primitives...")
    test_img = Image.new("RGBA", (SW, SH), (20, 12, 8, 255))
    td = ImageDraw.Draw(test_img)
    draw_card(td, 20 * s, 20 * s, 200 * s, 80 * s, (40, 30, 25),
              border_color=(245, 158, 11))
    draw_progress_bar(td, 20 * s, 120 * s, 200 * s, 12 * s, 0.65,
                      (245, 158, 11), (40, 40, 40), radius=6 * s)
    draw_circle_gauge(td, 350 * s, 80 * s, 40 * s, 0.75,
                      (0, 85, 150), (40, 40, 40), 6 * s)
    # Test all icons
    icons = [draw_icon_thermometer, draw_icon_fuel, draw_icon_warning,
             draw_icon_music, draw_icon_check, draw_icon_route, draw_icon_eco]
    for i, icon_fn in enumerate(icons):
        icon_fn(td, (50 + i * 60) * s, 200 * s, 15 * s, (245, 158, 11))
    # Test notification
    draw_notification_item(td, 20 * s, 260 * s, 400 * s, 40 * s,
                           HERITAGE, (245, 158, 11), draw_icon_warning,
                           "Tire Pressure Low", "Front right: 28 psi")
    test_path = os.path.join(OUTPUT_DIR, "_test_step1_4.png")
    test_img.resize((W, H), Image.LANCZOS).save(test_path)
    print(f"  Saved: {test_path}")
    print("Step 1.4 PASSED — card/icon primitives working.")

    # Step 1.5: Test charts, map, car silhouette, burl texture
    print("\nStep 1.5: Testing complex drawing primitives...")
    test_img = Image.new("RGBA", (SW, SH), (20, 12, 8, 255))
    td = ImageDraw.Draw(test_img)

    # Bar chart
    vals = [0.15, 0.25, 0.45, 0.6, 0.75, 0.55, 0.85]
    bar_colors = [(40, 40, 40)] * 3 + [(236, 91, 19, 100), (236, 91, 19, 150),
                  (236, 91, 19, 200), (236, 91, 19)]
    draw_bar_chart(td, 20 * s, 20 * s, 300 * s, 150 * s, vals, bar_colors,
                   x_labels=["-50m", "-40m", "-30m", "-20m", "-10m", "-5m", "Now"],
                   y_labels=["50", "40", "30", "20", "10"])

    # Line graph
    pts = [0.3, 0.5, 0.4, 0.7, 0.35, 0.6, 0.8, 0.45, 0.65]
    draw_line_graph(test_img, td, 350 * s, 20 * s, 400 * s, 150 * s,
                    pts, (0, 85, 150), fill_color=(0, 85, 150, 50),
                    highlight_idx=6)

    # Car silhouette
    draw_car_silhouette(td, 200 * s, 300 * s, 250 * s, 120 * s,
                        (245, 158, 11), "outline")
    draw_car_silhouette(td, 500 * s, 300 * s, 250 * s, 120 * s,
                        (236, 91, 19, 80), "filled")

    # Corner accents
    draw_corner_accents(td, 20 * s, 380 * s, 200 * s, 80 * s,
                        (255, 191, 0, 50), size=20 * s)

    test_path = os.path.join(OUTPUT_DIR, "_test_step1_5.png")
    test_img.resize((W, H), Image.LANCZOS).save(test_path)
    print(f"  Saved: {test_path}")

    # Burl texture test
    burl_img = Image.new("RGBA", (SW, SH), (0, 0, 0, 255))
    burl_draw = ImageDraw.Draw(burl_img)
    draw_burl_texture(burl_img, burl_draw)
    burl_path = os.path.join(OUTPUT_DIR, "_test_step1_5_burl.png")
    burl_img.resize((W, H), Image.LANCZOS).save(burl_path)
    print(f"  Burl texture: {burl_path}")

    # Map test
    map_img = Image.new("RGBA", (SW, SH), (0, 0, 0, 255))
    map_draw = ImageDraw.Draw(map_img)
    draw_simple_map(map_img, map_draw, 0, 0, SW, SH, HERITAGE)
    map_path = os.path.join(OUTPUT_DIR, "_test_step1_5_map.png")
    map_img.resize((W, H), Image.LANCZOS).save(map_path)
    print(f"  Map: {map_path}")

    # Vignette test
    vig_img = Image.new("RGBA", (SW, SH), (26, 15, 10, 255))
    vig_img = draw_radial_vignette(vig_img, SW // 2, SH // 2)
    vig_path = os.path.join(OUTPUT_DIR, "_test_step1_5_vignette.png")
    vig_img.resize((W, H), Image.LANCZOS).save(vig_path)
    print(f"  Vignette: {vig_path}")

    print("Step 1.5 PASSED — complex primitives working.")

    # Step 1.6: Initialization screens
    print("\nStep 1.6: Rendering initialization screens...")
    for t in ALL_THEMES:
        init_img = render_initialization(t)
        out_path = os.path.join(OUTPUT_DIR, f"init_{t.name}.png")
        init_img.resize((W, H), Image.LANCZOS).save(out_path)
        print(f"  {t.name}: {out_path}")
    print("Step 1.6 PASSED — 3 initialization screens rendered.")

    # Step 1.7: A1 Main screens
    print("\nStep 1.7: Rendering A1 main screens...")
    for t in ALL_THEMES:
        a1_img = render_a1_main(t)
        out_path = os.path.join(OUTPUT_DIR, f"a1_main_{t.name}.png")
        a1_img.resize((W, H), Image.LANCZOS).save(out_path)
        print(f"  {t.name}: {out_path}")
    print("Step 1.7 PASSED — 3 A1 main screens rendered.")

    # Step 1.8: A2 Trip screens
    print("\nStep 1.8: Rendering A2 trip screens...")
    for t in ALL_THEMES:
        a2_img = render_a2_trip(t)
        out_path = os.path.join(OUTPUT_DIR, f"a2_trip_{t.name}.png")
        a2_img.resize((W, H), Image.LANCZOS).save(out_path)
        print(f"  {t.name}: {out_path}")
    print("Step 1.8 PASSED — 3 A2 trip screens rendered.")

    # Step 1.9: A3 Weather screens
    print("\nStep 1.9: Rendering A3 weather screens...")
    for t in ALL_THEMES:
        a3_img = render_a3_weather(t)
        out_path = os.path.join(OUTPUT_DIR, f"a3_weather_{t.name}.png")
        a3_img.resize((W, H), Image.LANCZOS).save(out_path)
        print(f"  {t.name}: {out_path}")
    print("Step 1.9 PASSED — 3 A3 weather screens rendered.")

    # Step 1.10: A4 Service screens
    print("\nStep 1.10: Rendering A4 service screens...")
    for t in ALL_THEMES:
        a4_img = render_a4_service(t)
        out_path = os.path.join(OUTPUT_DIR, f"a4_service_{t.name}.png")
        a4_img.resize((W, H), Image.LANCZOS).save(out_path)
        print(f"  {t.name}: {out_path}")
    print("Step 1.10 PASSED — 3 A4 service screens rendered.")

    # Final: Generate all 15 via generate_all()
    print("\n=== Generating all 15 renders via generate_all() ===")
    generate_all()
    print("\n=== Phase 1 COMPLETE — All 15 mockup PNGs generated ===")
