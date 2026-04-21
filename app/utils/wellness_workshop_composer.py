"""Pillow compositor for the wellness-workshop post template.

Layout (1080 × 1350 canvas):

  TOP COLLAGE (y 0–440, h=440)
    ┌──────────┬──────────┬──────────┐
    │  photo1  │  photo2  │  photo3  │   each 360 × 440
    └──────────┴──────────┴──────────┘

  CONTENT AREA (y 440–1350, h=910)
    Dark brand background
    ┌─────────────────────────┬────────┐
    │ event_label (accent)    │        │
    │ date badge              │ person │
    │ TITLE (large white)     │ cutout │
    │ ✓ tip_1                 │        │
    │ ✓ tip_2                 │        │
    │ ✓ tip_3                 │        │
    │ ✓ tip_4                 │        │
    │ [logo1]  [logo2]        │        │
    └─────────────────────────┴────────┘
"""

from __future__ import annotations

import asyncio
import io
import logging

from PIL import Image, ImageDraw, ImageFont, ImageOps

from app.utils.fonts import get_montserrat, get_montserrat_sync

logger = logging.getLogger(__name__)

# ── Canvas ─────────────────────────────────────────────────────────────────────
CANVAS_W, CANVAS_H = 1080, 1350

# ── Top collage ────────────────────────────────────────────────────────────────
COLLAGE_H = 440
PANEL_W   = CANVAS_W // 3   # 360
COLLAGE_GAP = 3              # gap between collage panels

# ── Content area ───────────────────────────────────────────────────────────────
CONTENT_Y = COLLAGE_H
CONTENT_H = CANVAS_H - CONTENT_Y   # 910

# ── Text column ────────────────────────────────────────────────────────────────
TEXT_X     = 48
TEXT_MAX_W = 580

# ── Person image ───────────────────────────────────────────────────────────────
PERSON_X     = 600   # left edge of person zone
PERSON_MAX_W = CANVAS_W - PERSON_X   # 480

# ── Logo row (bottom of content area) ──────────────────────────────────────────
LOGO_Y_FROM_BOTTOM = 70
LOGO_MAX_H = 64
LOGO_MAX_W = 160
LOGO_GAP   = 24

# ── Font sizes ─────────────────────────────────────────────────────────────────
LABEL_SIZE  = 22
BADGE_SIZE  = 32
TITLE_MAX   = 88
TITLE_MIN   = 44
TIP_SIZE    = 34
DOT_R       = 10   # radius of bullet dot


# ── Color helpers ──────────────────────────────────────────────────────────────

def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    c = h.lstrip("#")
    if len(c) != 6:
        return (26, 120, 110)
    return int(c[:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def _darken(rgb: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    r, g, b = rgb
    return int(r * (1 - factor)), int(g * (1 - factor)), int(b * (1 - factor))


def _lighten(rgb: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    r, g, b = rgb
    return (
        int(r + (255 - r) * factor),
        int(g + (255 - g) * factor),
        int(b + (255 - b) * factor),
    )


def _ensure_visible_on_dark(h: str) -> tuple[int, int, int]:
    r, g, b = _hex_to_rgb(h)
    luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    factor = 0.0
    while luminance < 0.40 and factor < 0.85:
        factor += 0.12
        r = int(r + (255 - r) * factor)
        g = int(g + (255 - g) * factor)
        b = int(b + (255 - b) * factor)
        luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return r, g, b


# ── Text helpers ───────────────────────────────────────────────────────────────

def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_w: int,
) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = (current + " " + word).strip()
        bb = draw.textbbox((0, 0), candidate, font=font)
        if bb[2] - bb[0] <= max_w:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [text]


def _draw_wrapped(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    x: int,
    y: int,
    fill: tuple,
    max_w: int,
    line_gap: int = 6,
) -> int:
    lines = _wrap_text(draw, text, font, max_w)
    for line in lines:
        bb = draw.textbbox((0, 0), line, font=font)
        draw.text((x, y), line, font=font, fill=fill)
        y += int(bb[3] - bb[1]) + line_gap
    return y


def _auto_fit_title(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_w: int,
    max_lines: int = 3,
) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    for size in range(TITLE_MAX, TITLE_MIN - 1, -4):
        font = get_montserrat_sync("black", size)
        lines = _wrap_text(draw, text, font, max_w)
        if len(lines) <= max_lines:
            return font, lines
    font = get_montserrat_sync("black", TITLE_MIN)
    return font, _wrap_text(draw, text, font, max_w)


def _draw_date_badge(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    x: int,
    y: int,
    border_color: tuple,
    text_color: tuple,
    max_w: int,
) -> int:
    pad_h, pad_v, r = 20, 12, 14
    lines = _wrap_text(draw, text, font, max_w - pad_h * 2)
    line_heights = [draw.textbbox((0, 0), l, font=font)[3] - draw.textbbox((0, 0), l, font=font)[1] for l in lines]
    total_h = sum(line_heights) + 6 * max(0, len(lines) - 1)
    badge_h = total_h + pad_v * 2
    max_lw = max((draw.textbbox((0, 0), l, font=font)[2] - draw.textbbox((0, 0), l, font=font)[0]) for l in lines)
    badge_w = min(max_lw + pad_h * 2, max_w)

    draw.rounded_rectangle(
        [(x, y), (x + badge_w, y + badge_h)],
        radius=r, outline=(*border_color, 200), width=3,
    )
    ty = y + pad_v
    for i, line in enumerate(lines):
        draw.text((x + pad_h, ty), line, font=font, fill=text_color)
        ty += line_heights[i] + 6
    return int(y + badge_h + 18)


def _paste_collage_panel(
    canvas: Image.Image,
    panel_bytes: bytes | None,
    x_offset: int,
    fallback_color: tuple[int, int, int],
) -> None:
    if panel_bytes is None:
        overlay = Image.new("RGB", (PANEL_W, COLLAGE_H), fallback_color)
        canvas.paste(overlay, (x_offset, 0))
        return
    try:
        img = Image.open(io.BytesIO(panel_bytes)).convert("RGB")
        img = ImageOps.fit(img, (PANEL_W, COLLAGE_H), Image.Resampling.LANCZOS)
        canvas.paste(img, (x_offset, 0))
    except Exception as exc:
        logger.warning("Could not paste collage panel at x=%d: %s", x_offset, exc)
        fallback = Image.new("RGB", (PANEL_W, COLLAGE_H), fallback_color)
        canvas.paste(fallback, (x_offset, 0))


# ── Main compositor ────────────────────────────────────────────────────────────

async def compose(
    bg1_bytes: bytes | None,
    bg2_bytes: bytes | None,
    bg3_bytes: bytes | None,
    person_bytes: bytes | None,
    logo_bytes: bytes | None,
    second_logo_bytes: bytes | None,
    event_label: str,
    date_time: str,
    title: str,
    tip_1: str,
    tip_2: str,
    tip_3: str,
    tip_4: str,
    brand_color_primary: str,
    brand_color_secondary: str,
) -> bytes:
    """Compose wellness-workshop flyer and return PNG bytes."""

    font_label  = await get_montserrat("bold", LABEL_SIZE)
    font_badge  = await get_montserrat("bold", BADGE_SIZE)
    font_tip    = await get_montserrat("regular", TIP_SIZE)

    def _sync_compose() -> bytes:
        primary_rgb = _hex_to_rgb(brand_color_primary)
        accent_rgb  = _ensure_visible_on_dark(brand_color_primary)
        dark_bg     = _darken(primary_rgb, 0.78)
        strip_color = primary_rgb

        # ── 1. Base canvas (dark background) ─────────────────────────────────
        img = Image.new("RGBA", (CANVAS_W, CANVAS_H), (*dark_bg, 255))

        # ── 2. Top collage — 3 panels ─────────────────────────────────────────
        light_fallback = _lighten(primary_rgb, 0.35)
        img_rgb = img.convert("RGB")
        _paste_collage_panel(img_rgb, bg1_bytes, 0, light_fallback)
        _paste_collage_panel(img_rgb, bg2_bytes, PANEL_W + COLLAGE_GAP, light_fallback)
        _paste_collage_panel(img_rgb, bg3_bytes, (PANEL_W + COLLAGE_GAP) * 2, light_fallback)
        img = img_rgb.convert("RGBA")

        # ── 3. Thin brand-color separator strip below collage ─────────────────
        strip = Image.new("RGBA", (CANVAS_W, 6), (*strip_color, 255))
        img.paste(strip, (0, COLLAGE_H))

        # ── 4. Person image (right zone, bottom-anchored) ─────────────────────
        if person_bytes is not None:
            try:
                person_img = Image.open(io.BytesIO(person_bytes)).convert("RGBA")
                bbox = person_img.getbbox()
                if bbox:
                    person_img = person_img.crop(bbox)

                # Scale to fill from COLLAGE_H to CANVAS_H
                target_h = CONTENT_H
                scale = target_h / person_img.height
                pw = int(person_img.width * scale)
                ph = target_h
                if pw > PERSON_MAX_W:
                    pw = PERSON_MAX_W
                    ph = int(person_img.height * (pw / person_img.width))
                person_img = person_img.resize((pw, ph), Image.Resampling.LANCZOS)

                # Bottom-anchor: feet at CANVAS_H - 20
                paste_x = PERSON_X + (PERSON_MAX_W - pw) // 2
                paste_y = CANVAS_H - ph - 10
                img.paste(person_img, (paste_x, paste_y), person_img)
            except Exception as exc:
                logger.warning("Could not paste person image: %s", exc)

        draw = ImageDraw.Draw(img)
        y = CONTENT_Y + 36

        # ── 5. event_label ────────────────────────────────────────────────────
        if event_label:
            y = _draw_wrapped(
                draw, event_label.upper(), font_label,
                TEXT_X, y, (*accent_rgb, 220), TEXT_MAX_W, line_gap=4,
            )
            y += 16

        # ── 6. date badge ─────────────────────────────────────────────────────
        if date_time:
            y = _draw_date_badge(
                draw, date_time, font_badge,
                TEXT_X, y, accent_rgb, (255, 255, 255, 245), TEXT_MAX_W,
            )
            y += 12

        # ── 7. Title ──────────────────────────────────────────────────────────
        if title:
            font_title, title_lines = _auto_fit_title(draw, title, TEXT_MAX_W - 20)
            for line in title_lines:
                bb = draw.textbbox((0, 0), line, font=font_title)
                draw.text((TEXT_X, y), line, font=font_title, fill=(255, 255, 255, 255))
                y += int(bb[3] - bb[1]) + 10
            y += 28

        # ── 8. Checklist tips ─────────────────────────────────────────────────
        tips = [t for t in [tip_1, tip_2, tip_3, tip_4] if t.strip()]
        for tip in tips:
            # Bullet dot
            dot_cx = TEXT_X + DOT_R
            dot_cy = y + TIP_SIZE // 2 + 4
            draw.ellipse(
                [(dot_cx - DOT_R, dot_cy - DOT_R), (dot_cx + DOT_R, dot_cy + DOT_R)],
                fill=(*accent_rgb, 230),
            )
            tip_x = TEXT_X + DOT_R * 2 + 14
            tip_max_w = TEXT_MAX_W - (tip_x - TEXT_X)
            y = _draw_wrapped(draw, tip, font_tip, tip_x, y, (255, 255, 255, 230), tip_max_w, line_gap=4)
            y += 14

        # ── 9. Logos (bottom of content area) ────────────────────────────────
        logo_y = CANVAS_H - LOGO_Y_FROM_BOTTOM - LOGO_MAX_H
        logo_cursor_x = TEXT_X

        for logo_data in [(logo_bytes, "primary logo"), (second_logo_bytes, "second logo")]:
            lbytes, lname = logo_data
            if lbytes is None:
                continue
            try:
                logo_img = Image.open(io.BytesIO(lbytes)).convert("RGBA")
                scale = min(LOGO_MAX_W / logo_img.width, LOGO_MAX_H / logo_img.height)
                lw = int(logo_img.width * scale)
                lh = int(logo_img.height * scale)
                logo_img = logo_img.resize((lw, lh), Image.Resampling.LANCZOS)
                paste_y = logo_y + (LOGO_MAX_H - lh) // 2
                img.paste(logo_img, (logo_cursor_x, paste_y), logo_img)
                logo_cursor_x += lw + LOGO_GAP
            except Exception as exc:
                logger.warning("Could not paste %s: %s", lname, exc)

        out = io.BytesIO()
        img.convert("RGB").save(out, format="PNG")
        return out.getvalue()

    return await asyncio.to_thread(_sync_compose)
