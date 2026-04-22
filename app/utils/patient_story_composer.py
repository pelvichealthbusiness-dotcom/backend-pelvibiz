"""Pillow compositor for the patient-story post template.

Layout (1080 × 1350 canvas):

  TOP SECTION (y 0 – 490)
    Brand gradient background
    ┌─────────────────────────────────────────────────────┐
    │           SECTION LABEL (small, centered)           │  ← y=70
    │                                                     │
    │               "patient"  ← title line 1            │  ← y=115
    │               "stories." ← title line 2            │  ← y=235
    │      ○──────────────────────────────────────○       │  ← ellipse
    │                                       [LOGO]        │  ← top-right
    └─────────────────────────────────────────────────────┘

  CARD SECTION (y 490 – 1290)
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

import numpy as np
from PIL import Image, ImageDraw

from app.utils.fonts import get_montserrat, get_montserrat_sync

logger = logging.getLogger(__name__)

# ── Canvas ──────────────────────────────────────────────────────────────────────
CANVAS_W, CANVAS_H = 1080, 1350

# ── Title section ───────────────────────────────────────────────────────────────
LABEL_Y      = 70
LABEL_SIZE   = 22
TITLE_1_Y    = 118
TITLE_1_SIZE = 108
TITLE_2_MAX  = 156
TITLE_2_MIN  = 80
ELLIPSE_PAD_V = 28
ELLIPSE_PAD_H = 60

# ── Logo (top-right) ────────────────────────────────────────────────────────────
LOGO_MAX_H   = 88
LOGO_MAX_W   = 200
LOGO_MARGIN  = 42

# ── Card ────────────────────────────────────────────────────────────────────────
CARD_X       = 52
CARD_Y       = 490
CARD_W       = CANVAS_W - CARD_X * 2   # 976
CARD_H       = 800
CARD_RADIUS  = 30
CARD_PAD_H   = 52
CARD_PAD_V   = 44

# ── Card content ────────────────────────────────────────────────────────────────
STAR_R_OUTER = 15
STAR_R_INNER = 6
STAR_COUNT   = 5
STAR_GAP     = 40
STAR_COLOR   = (255, 190, 0)
CLIENT_SIZE  = 28
BODY_MAX     = 34
BODY_MIN     = 20
LINE_GAP     = 10
RESULT_SIZE  = 28


# ── Helpers ─────────────────────────────────────────────────────────────────────

def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    c = h.lstrip("#")
    if len(c) != 6:
        return (26, 120, 110)
    return int(c[:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def _lighten(rgb: tuple[int, int, int], f: float) -> tuple[int, int, int]:
    return (
        int(rgb[0] + (255 - rgb[0]) * f),
        int(rgb[1] + (255 - rgb[1]) * f),
        int(rgb[2] + (255 - rgb[2]) * f),
    )


def _make_gradient_bg(
    w: int,
    h: int,
    brand: tuple[int, int, int],
) -> Image.Image:
    """Vertical gradient: light tint (top) → brand color (bottom) + radial bloom."""
    light = _lighten(brand, 0.58)
    arr = np.zeros((h, w, 3), dtype=np.float32)
    mid = int(h * 0.50)
    for c in range(3):
        arr[:mid, :, c] = np.linspace(light[c], brand[c], mid, dtype=np.float32)[:, np.newaxis]
        arr[mid:, :, c] = brand[c]

    # Soft radial bloom at upper-center for depth
    Y, X = np.mgrid[0:h, 0:w]
    cy, cx = h * 0.22, w * 0.5
    dist = np.sqrt(((Y - cy) / (h * 0.38)) ** 2 + ((X - cx) / (w * 0.50)) ** 2)
    bloom = np.clip(1.0 - dist, 0.0, 1.0) ** 1.8 * 60.0
    for c in range(3):
        arr[:, :, c] = np.clip(arr[:, :, c] + bloom, 0, 255)

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


def _auto_fit_title2(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_w: int,
) -> tuple:
    for size in range(TITLE_2_MAX, TITLE_2_MIN - 1, -6):
        f = get_montserrat_sync("black", size)
        bb = draw.textbbox((0, 0), text, font=f)
        if bb[2] - bb[0] <= max_w:
            return f, size
    f = get_montserrat_sync("black", TITLE_2_MIN)
    return f, TITLE_2_MIN


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
    brand_color_secondary: str,
) -> bytes:
    """Compose a patient-story card and return PNG bytes."""

    font_label  = await get_montserrat("medium",   LABEL_SIZE)
    font_title1 = await get_montserrat("black",    TITLE_1_SIZE)
    font_client = await get_montserrat("semibold", CLIENT_SIZE)
    font_result = await get_montserrat("semibold", RESULT_SIZE)

    def _sync_compose() -> bytes:
        primary_rgb = _hex_to_rgb(brand_color_primary)
        white       = (255, 255, 255, 255)
        white_dim   = (255, 255, 255, 170)
        dark_text   = (28, 28, 28, 255)

        # ── 1. Gradient background ─────────────────────────────────────────
        img  = _make_gradient_bg(CANVAS_W, CANVAS_H, primary_rgb).convert("RGBA")
        draw = ImageDraw.Draw(img)

        # ── 2. Section label ───────────────────────────────────────────────
        lbl = (section_label or "patient stories").upper()
        lb  = draw.textbbox((0, 0), lbl, font=font_label)
        draw.text(((CANVAS_W - (lb[2] - lb[0])) // 2, LABEL_Y), lbl, font=font_label, fill=white_dim)

        # ── 3. Title lines ─────────────────────────────────────────────────
        words    = (section_label or "patient stories").lower().split()
        title_l1 = words[0] if words else "patient"
        title_l2 = (" ".join(words[1:]) if len(words) > 1 else "stories") + "."

        # Line 1
        t1b = draw.textbbox((0, 0), title_l1, font=font_title1)
        t1w, t1h = t1b[2] - t1b[0], t1b[3] - t1b[1]
        draw.text(((CANVAS_W - t1w) // 2, TITLE_1_Y), title_l1, font=font_title1, fill=white)

        # Line 2 — auto-fit to canvas width
        t2_max_w = CANVAS_W - 80
        font_t2, _t2_size = _auto_fit_title2(draw, title_l2, t2_max_w)
        t2b = draw.textbbox((0, 0), title_l2, font=font_t2)
        t2w, t2h = t2b[2] - t2b[0], t2b[3] - t2b[1]
        t2_y = TITLE_1_Y + t1h + 10
        draw.text(((CANVAS_W - t2w) // 2, t2_y), title_l2, font=font_t2, fill=white)

        title_bottom = t2_y + t2h

        # ── 4. Ellipse decoration around title ─────────────────────────────
        el_x1 = ELLIPSE_PAD_H
        el_x2 = CANVAS_W - ELLIPSE_PAD_H
        el_y1 = TITLE_1_Y - ELLIPSE_PAD_V
        el_y2 = title_bottom + ELLIPSE_PAD_V
        draw.ellipse([(el_x1, el_y1), (el_x2, el_y2)], outline=(255, 255, 255, 140), width=2)

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
        shadow_off = 8
        draw.rounded_rectangle(
            [(CARD_X + shadow_off, CARD_Y + shadow_off),
             (CARD_X + CARD_W + shadow_off, CARD_Y + CARD_H + shadow_off)],
            radius=CARD_RADIUS,
            fill=(0, 0, 0, 35),
        )

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
            fill=(*primary_rgb, 55),
            width=1,
        )

        # ── 10. Testimonial body ──────────────────────────────────────────
        body_x   = CARD_X + CARD_PAD_H
        body_y   = sep_y + 22
        body_w   = CARD_W - CARD_PAD_H * 2
        res_reserve = RESULT_SIZE + 36 if (result and result.strip()) else 0
        body_max_h = (CARD_Y + CARD_H - CARD_PAD_V) - body_y - res_reserve

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
