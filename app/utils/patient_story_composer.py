"""Pillow compositor for the patient-story post template.

Layout (1080 × 1350 canvas):

  TOP SECTION (y 0 – 560)
    Brand gradient background
    ┌─────────────────────────────────────────────────────┐
    │        SECTION LABEL (tiny, centered, subtle)       │  ← y=65
    │                                                     │
    │            "patient"  ← script title line 1         │  ← y=120
    │            "stories." ← script title line 2         │  ← y=285
    │    ○──────────────────────────────────────────○     │  ← golden ellipse
    │                                       [LOGO]        │  ← top-right
    └─────────────────────────────────────────────────────┘

  CARD SECTION (y 560 – 1300)
    White rounded-rectangle card
    ┌─────────────────────────────────────────────────────┐
    │ ★★★★★                                               │
    │ Client name / identifier                            │
    │ ───────────────────────────────────────────         │
    │ Testimonial text wrapped to fit card width…         │
    │                                                     │
    │ — Result highlight (accent color)                   │
    └─────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import asyncio
import io
import math
import logging

import colorsys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from app.utils.fonts import get_montserrat, get_montserrat_sync

logger = logging.getLogger(__name__)

# ── Canvas ──────────────────────────────────────────────────────────────────────
CANVAS_W, CANVAS_H = 1080, 1350

# ── Title section ───────────────────────────────────────────────────────────────
LABEL_Y      = 65
LABEL_SIZE   = 18
TITLE_1_Y    = 120
TITLE_1_SIZE = 138          # GreatVibes — script font, generous size
TITLE_2_MAX  = 170
TITLE_2_MIN  = 90
ELLIPSE_PAD_V = 32
ELLIPSE_PAD_H = 50

# ── Logo (top-right) ────────────────────────────────────────────────────────────
LOGO_MAX_H   = 80
LOGO_MAX_W   = 180
LOGO_MARGIN  = 38

# ── Card ────────────────────────────────────────────────────────────────────────
CARD_X       = 48
CARD_Y       = 560
CARD_W       = CANVAS_W - CARD_X * 2   # 984
CARD_H       = 740
CARD_RADIUS  = 28
CARD_PAD_H   = 48
CARD_PAD_V   = 40

# ── Card content ────────────────────────────────────────────────────────────────
STAR_R_OUTER = 14
STAR_R_INNER = 6
STAR_COUNT   = 5
STAR_GAP     = 38
STAR_COLOR   = (255, 190, 0)
CLIENT_SIZE  = 26
BODY_MAX     = 33
BODY_MIN     = 19
LINE_GAP     = 10
RESULT_SIZE  = 26


# ── Helpers ─────────────────────────────────────────────────────────────────────

def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    c = h.lstrip("#")
    if len(c) != 6:
        return (26, 120, 110)
    return int(c[:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def _ensure_vibrant(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    """Guarantee the brand color has enough saturation and brightness for a gradient.

    Dark neutrals (grays, near-blacks) are shifted to the default teal hue so the
    background never renders as a gray slab regardless of what the user stored.
    """
    r, g, b = rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0
    h, s, v = colorsys.rgb_to_hsv(r, g, b)

    if s < 0.12:        # achromatic / near-gray → use default brand teal
        h = 0.483
        s = 0.55
    else:
        s = max(s, 0.40)

    v = max(v, 0.32)    # never render as near-black

    r2, g2, b2 = colorsys.hsv_to_rgb(h, s, v)
    return int(r2 * 255), int(g2 * 255), int(b2 * 255)


def _make_gradient_bg(
    w: int,
    h: int,
    brand: tuple[int, int, int],
) -> Image.Image:
    """Vertical gradient: pastel tint (top) → vibrant brand color (bottom)."""
    brand = _ensure_vibrant(brand)

    r, g, b   = brand[0] / 255.0, brand[1] / 255.0, brand[2] / 255.0
    hue, s, v = colorsys.rgb_to_hsv(r, g, b)

    def _hsv(sat: float, val: float) -> tuple[int, int, int]:
        rc, gc, bc = colorsys.hsv_to_rgb(hue, sat, val)
        return int(rc * 255), int(gc * 255), int(bc * 255)

    light = _hsv(max(s * 0.30, 0.08), min(v + 0.45, 0.97))   # soft pastel top
    mid   = _hsv(s * 0.70,            min(v + 0.10, 0.85))    # mid tone
    dark  = _hsv(min(s * 1.10, 1.0),  max(v * 0.65, 0.25))    # deep bottom

    arr   = np.zeros((h, w, 3), dtype=np.float32)
    third = h // 3

    for c in range(3):
        top_c  = [light, mid, dark][0][c]
        mid_c  = [light, mid, dark][1][c]
        bot_c  = [light, mid, dark][2][c]
        arr[:third, :, c]        = np.linspace(top_c, mid_c, third, dtype=np.float32)[:, np.newaxis]
        arr[third:2*third, :, c] = np.linspace(mid_c, bot_c, third, dtype=np.float32)[:, np.newaxis]
        arr[2*third:, :, c]      = bot_c

    # Radial bloom at upper-center
    Y, X = np.mgrid[0:h, 0:w]
    dist  = np.sqrt(((Y - h * 0.20) / (h * 0.35)) ** 2 + ((X - w * 0.5) / (w * 0.48)) ** 2)
    bloom = np.clip(1.0 - dist, 0.0, 1.0) ** 1.6 * 65.0
    for c in range(3):
        arr[:, :, c] = np.clip(arr[:, :, c] + bloom, 0, 255)

    # Film-grain for depth
    rng   = np.random.default_rng(42)
    arr   = np.clip(arr + rng.normal(0, 3.5, arr.shape).astype(np.float32), 0, 255)

    return Image.fromarray(arr.astype(np.uint8), "RGB")


def _draw_star(
    draw: ImageDraw.ImageDraw,
    cx: float,
    cy: float,
    r_outer: int,
    r_inner: int,
    fill: tuple,
) -> None:
    pts = []
    for i in range(10):
        angle = math.pi / 5 * i - math.pi / 2
        r = r_outer if i % 2 == 0 else r_inner
        pts.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    draw.polygon(pts, fill=fill)


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font,
    max_w: int,
) -> list[str]:
    words = text.split()
    lines: list[str] = []
    cur = ""
    for word in words:
        candidate = (cur + " " + word).strip()
        bb = draw.textbbox((0, 0), candidate, font=font)
        if bb[2] - bb[0] <= max_w:
            cur = candidate
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines or [text]


def _auto_fit_script(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_w: int,
    size_max: int,
    size_min: int,
    step: int = 6,
) -> tuple:
    for size in range(size_max, size_min - 1, -step):
        f = get_montserrat_sync("script", size)
        bb = draw.textbbox((0, 0), text, font=f)
        if bb[2] - bb[0] <= max_w:
            return f, size
    f = get_montserrat_sync("script", size_min)
    return f, size_min


def _auto_fit_body(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_w: int,
    max_h: int,
) -> tuple:
    for size in range(BODY_MAX, BODY_MIN - 1, -2):
        f = get_montserrat_sync("regular", size)
        lines = _wrap_text(draw, text, f, max_w)
        total_h = len(lines) * (size + LINE_GAP)
        if total_h <= max_h:
            return f, lines
    f = get_montserrat_sync("regular", BODY_MIN)
    return f, _wrap_text(draw, text, f, max_w)


# ── Main compositor ─────────────────────────────────────────────────────────────

async def compose(
    logo_bytes: bytes | None,
    section_label: str,
    testimonial: str,
    client_name: str,
    result: str,
    brand_color_primary: str,
    brand_color_secondary: str,  # reserved for future accent use
) -> bytes:
    """Compose a patient-story card and return PNG bytes."""

    font_title1 = await get_montserrat("script",   TITLE_1_SIZE)
    font_client = await get_montserrat("semibold",  CLIENT_SIZE)
    font_result = await get_montserrat("semibold",  RESULT_SIZE)

    def _sync_compose() -> bytes:
        primary_rgb = _hex_to_rgb(brand_color_primary)
        white       = (255, 255, 255, 255)
        dark_text   = (28, 28, 28, 255)
        gold        = (220, 178, 60, 200)    # golden ellipse

        # ── 1. Solid brand color background ────────────────────────────────
        vibrant_rgb = _ensure_vibrant(primary_rgb)
        img  = Image.new("RGBA", (CANVAS_W, CANVAS_H), (*vibrant_rgb, 255))
        draw = ImageDraw.Draw(img)

        # ── 3. Script title lines ──────────────────────────────────────────
        words    = (section_label or "patient stories").lower().split()
        title_l1 = words[0] if words else "patient"
        title_l2 = (" ".join(words[1:]) if len(words) > 1 else "stories") + "."

        title_max_w = CANVAS_W - 80

        # Line 1 — fixed size
        t1b = draw.textbbox((0, 0), title_l1, font=font_title1)
        t1w = t1b[2] - t1b[0]
        t1h = t1b[3] - t1b[1]
        draw.text(((CANVAS_W - t1w) // 2, TITLE_1_Y), title_l1, font=font_title1, fill=white)

        # Line 2 — auto-fit script font
        font_t2, _ = _auto_fit_script(draw, title_l2, title_max_w, TITLE_2_MAX, TITLE_2_MIN)
        t2b = draw.textbbox((0, 0), title_l2, font=font_t2)
        t2w = t2b[2] - t2b[0]
        t2h = t2b[3] - t2b[1]

        # Script fonts have large descender space — use visual top offset
        t2_y = TITLE_1_Y + t1h - 12    # slight overlap looks good with script
        draw.text(((CANVAS_W - t2w) // 2, t2_y), title_l2, font=font_t2, fill=white)

        title_bottom = t2_y + t2h

        # ── 4. Golden ellipse around title ─────────────────────────────────
        el_x1 = ELLIPSE_PAD_H
        el_x2 = CANVAS_W - ELLIPSE_PAD_H
        el_y1 = TITLE_1_Y - ELLIPSE_PAD_V
        el_y2 = title_bottom + ELLIPSE_PAD_V
        draw.ellipse([(el_x1, el_y1), (el_x2, el_y2)], outline=gold, width=2)

        # ── 5. Logo (top-right) ───────────────────────────────────────────
        if logo_bytes is not None:
            try:
                logo = Image.open(io.BytesIO(logo_bytes)).convert("RGBA")
                scale = min(LOGO_MAX_W / logo.width, LOGO_MAX_H / logo.height)
                lw = int(logo.width * scale)
                lh = int(logo.height * scale)
                logo = logo.resize((lw, lh), Image.Resampling.LANCZOS)
                img.paste(logo, (CANVAS_W - LOGO_MARGIN - lw, LOGO_MARGIN), logo)
                draw = ImageDraw.Draw(img)
            except Exception as exc:
                logger.warning("Could not paste logo: %s", exc)

        # ── 6. Card shadow ─────────────────────────────────────────────────
        shadow_off = 10
        shadow_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        shadow_draw  = ImageDraw.Draw(shadow_layer)
        shadow_draw.rounded_rectangle(
            [(CARD_X + shadow_off, CARD_Y + shadow_off),
             (CARD_X + CARD_W + shadow_off, CARD_Y + CARD_H + shadow_off)],
            radius=CARD_RADIUS,
            fill=(0, 0, 0, 45),
        )
        shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius=8))
        img = Image.alpha_composite(img, shadow_layer)
        draw = ImageDraw.Draw(img)

        # ── 7. Card body ──────────────────────────────────────────────────
        draw.rounded_rectangle(
            [(CARD_X, CARD_Y), (CARD_X + CARD_W, CARD_Y + CARD_H)],
            radius=CARD_RADIUS,
            fill=(255, 255, 255, 255),
        )

        # ── 8. Stars ──────────────────────────────────────────────────────
        star_top = CARD_Y + CARD_PAD_V
        star_cy  = star_top + STAR_R_OUTER
        star_cx  = CARD_X + CARD_PAD_H + STAR_R_OUTER
        for _ in range(STAR_COUNT):
            _draw_star(draw, star_cx, star_cy, STAR_R_OUTER, STAR_R_INNER, STAR_COLOR)
            star_cx += STAR_GAP

        # ── 9. Client name ────────────────────────────────────────────────
        client_y = star_cy + STAR_R_OUTER + 14
        if client_name and client_name.strip():
            draw.text(
                (CARD_X + CARD_PAD_H, client_y),
                client_name.strip(),
                font=font_client,
                fill=(70, 70, 70, 255),
            )
            cl_bb    = draw.textbbox((0, 0), client_name.strip(), font=font_client)
            client_y += (cl_bb[3] - cl_bb[1]) + 14

        # thin separator
        sep_y = client_y + 4
        draw.line(
            [(CARD_X + CARD_PAD_H, sep_y), (CARD_X + CARD_W - CARD_PAD_H, sep_y)],
            fill=(*primary_rgb, 50),
            width=1,
        )

        # ── 10. Testimonial body ──────────────────────────────────────────
        body_x   = CARD_X + CARD_PAD_H
        body_y   = sep_y + 22
        body_w   = CARD_W - CARD_PAD_H * 2
        res_reserve = RESULT_SIZE + 36 if (result and result.strip()) else 0
        body_max_h = int((CARD_Y + CARD_H - CARD_PAD_V) - body_y - res_reserve)

        font_body, body_lines = _auto_fit_body(draw, testimonial or "", body_w, body_max_h)
        ty = body_y
        for line in body_lines:
            bb = draw.textbbox((0, 0), line, font=font_body)
            draw.text((body_x, ty), line, font=font_body, fill=dark_text)
            ty += (bb[3] - bb[1]) + LINE_GAP

        # ── 11. Result highlight (accent, bottom of card) ─────────────────
        if result and result.strip():
            res_y    = CARD_Y + CARD_H - CARD_PAD_V - RESULT_SIZE
            res_text = f"— {result.strip()}"
            draw.text(
                (CARD_X + CARD_PAD_H, res_y),
                res_text,
                font=font_result,
                fill=(*primary_rgb, 230),
            )

        out = io.BytesIO()
        img.convert("RGB").save(out, format="PNG")
        return out.getvalue()

    return await asyncio.to_thread(_sync_compose)
