"""Pillow compositor for the masterclass-banner post template.

Two-panel split layout (inspired by professional event banner design):

Layer stack:
  1. Left panel  — solid brand_color_primary (lightened), full height left half
  2. Right panel — solid dark color (brand_color_primary darkened), full height right half
  3. Arch divider — large filled circle from left-panel color bulging into right panel,
                    creating an organic curved boundary
  4. Person image — fills the left panel area, clipped to the arch mask
  5. Dark gradient on person — subtle fade on right edge for blending
  6. Logo         — small, top-right of text column
  7. event_label  — small caps, brand_color_secondary (accent)
  8. Divider line — thin, accent color
  9. title        — very large bold white (Montserrat Black, auto-shrink)
 10. subtitle     — medium white
 11. Date badge   — bordered rounded rectangle with date_time inside
 12. venue / via  — small white meta text
 13. CTA button   — filled rounded rect in brand_color_primary + white text
"""

from __future__ import annotations

import asyncio
import io
import logging

from PIL import Image, ImageDraw, ImageFont, ImageOps

from app.utils.fonts import get_montserrat, get_montserrat_sync

logger = logging.getLogger(__name__)

# ── Canvas ────────────────────────────────────────────────────────────────────
CANVAS_W, CANVAS_H = 1080, 1350

# ── Panel split ───────────────────────────────────────────────────────────────
SPLIT_X = 460          # vertical split point
ARCH_CENTER_X = 400    # arch circle center x (left of split)
ARCH_CENTER_Y = 800    # arch circle center y (lower half bias)
ARCH_RADIUS = 820      # large circle — creates the organic curved boundary

# ── Right column ──────────────────────────────────────────────────────────────
TEXT_X = 510           # text starts here
TEXT_MAX_W = 510       # max text width before wrapping
LOGO_MAX = 90          # max logo size (px)

# ── Font sizes (px) ───────────────────────────────────────────────────────────
LABEL_SIZE = 30
TITLE_MAX_SIZE = 96
TITLE_MIN_SIZE = 54
SUBTITLE_SIZE = 36
META_SIZE = 28
CTA_SIZE = 34
DATE_BADGE_SIZE = 32

# ── Y positions ───────────────────────────────────────────────────────────────
LOGO_TOP = 80
TEXT_TOP = 200         # where text block starts (advances dynamically)


# ── Color helpers ─────────────────────────────────────────────────────────────

def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    c = h.lstrip("#")
    if len(c) != 6:
        return (26, 120, 110)
    return int(c[:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def _lighten(rgb: tuple[int, int, int], factor: float = 0.35) -> tuple[int, int, int]:
    """Mix color with white."""
    r, g, b = rgb
    return (
        int(r + (255 - r) * factor),
        int(g + (255 - g) * factor),
        int(b + (255 - b) * factor),
    )


def _darken(rgb: tuple[int, int, int], factor: float = 0.25) -> tuple[int, int, int]:
    """Darken by mixing towards black."""
    r, g, b = rgb
    return int(r * factor), int(g * factor), int(b * factor)


def _ensure_visible_on_dark(h: str) -> tuple[int, int, int]:
    r, g, b = _hex_to_rgb(h)
    luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    if luminance >= 0.30:
        return r, g, b
    factor = 0.0
    while luminance < 0.40 and factor < 0.85:
        factor += 0.12
        r = int(r + (255 - r) * factor)
        g = int(g + (255 - g) * factor)
        b = int(b + (255 - b) * factor)
        luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return r, g, b


# ── Text helpers ──────────────────────────────────────────────────────────────

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


def _draw_left_block(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    x: int,
    y: int,
    fill: tuple,
    max_w: int,
    line_gap: int = 6,
) -> int:
    """Draw left-aligned wrapped text. Returns y after last line."""
    for line in _wrap_text(draw, text, font, max_w):
        bb = draw.textbbox((0, 0), line, font=font)
        draw.text((x, y), line, font=font, fill=fill)
        y += (bb[3] - bb[1]) + line_gap
    return y


def _shrink_title(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_w: int,
) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    size = TITLE_MAX_SIZE
    while size >= TITLE_MIN_SIZE:
        font = get_montserrat_sync("black", size)
        bb = draw.textbbox((0, 0), text, font=font)
        if (bb[2] - bb[0]) <= max_w:
            return font, [text]
        size -= 6
    font = get_montserrat_sync("black", TITLE_MIN_SIZE)
    words = text.split()
    mid = max(1, len(words) // 2)
    return font, [" ".join(words[:mid]), " ".join(words[mid:])]


def _draw_title_lines(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    font: ImageFont.FreeTypeFont,
    x: int,
    y: int,
    fill: tuple,
) -> int:
    for line in lines:
        bb = draw.textbbox((0, 0), line, font=font)
        draw.text((x, y), line, font=font, fill=fill)
        y += (bb[3] - bb[1]) + 8
    return y


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
    """Draw date/time inside a rounded-border badge. Returns y after badge."""
    pad_h, pad_v, r = 20, 12, 14
    lines = _wrap_text(draw, text, font, max_w - pad_h * 2)
    line_heights = []
    for line in lines:
        bb = draw.textbbox((0, 0), line, font=font)
        line_heights.append(bb[3] - bb[1])

    total_text_h = sum(line_heights) + 6 * (len(lines) - 1)
    badge_h = total_text_h + pad_v * 2

    # Use longest line for badge width (cap at max_w)
    max_line_w = 0
    for line in lines:
        bb = draw.textbbox((0, 0), line, font=font)
        max_line_w = max(max_line_w, bb[2] - bb[0])
    badge_w = min(max_line_w + pad_h * 2, max_w)

    draw.rounded_rectangle(
        [(x, y), (x + badge_w, y + badge_h)],
        radius=r,
        outline=(*border_color, 200),
        width=2,
    )
    ty = y + pad_v
    for i, line in enumerate(lines):
        draw.text((x + pad_h, ty), line, font=font, fill=text_color)
        ty += line_heights[i] + 6

    return y + badge_h + 16


def _draw_cta(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    x: int,
    y: int,
    bg_color: tuple,
    max_w: int,
) -> int:
    pad_h, pad_v, r = 32, 16, 18
    bb = draw.textbbox((0, 0), text, font=font)
    btn_w = min(bb[2] - bb[0] + pad_h * 2, max_w)
    btn_h = (bb[3] - bb[1]) + pad_v * 2
    draw.rounded_rectangle([(x, y), (x + btn_w, y + btn_h)], radius=r, fill=(*bg_color, 255))
    text_x = x + (btn_w - (bb[2] - bb[0])) // 2
    draw.text((text_x, y + pad_v), text, font=font, fill=(255, 255, 255, 255))
    return y + btn_h + 12


# ── Main compositor ───────────────────────────────────────────────────────────

async def compose(
    person_bytes: bytes | None,
    logo_bytes: bytes | None,
    event_label: str,
    title: str,
    subtitle: str,
    date_time: str,
    venue: str,
    via: str,
    cta: str,
    brand_color_primary: str,
    brand_color_secondary: str,
) -> bytes:
    """Compose the masterclass-banner image and return raw PNG bytes."""

    font_label = await get_montserrat("bold", LABEL_SIZE)
    font_subtitle = await get_montserrat("regular", SUBTITLE_SIZE)
    font_meta = await get_montserrat("regular", META_SIZE)
    font_cta = await get_montserrat("bold", CTA_SIZE)
    font_date = await get_montserrat("bold", DATE_BADGE_SIZE)

    def _sync_compose() -> bytes:
        primary_rgb = _hex_to_rgb(brand_color_primary)
        left_bg = _lighten(primary_rgb, 0.55)   # very light brand color for left panel
        right_bg = _darken(primary_rgb, 0.20)    # very dark for right panel
        accent_rgb = _ensure_visible_on_dark(brand_color_secondary)

        # ── 1 & 2. Two-panel background ──────────────────────────────────────
        img = Image.new("RGBA", (CANVAS_W, CANVAS_H), (*right_bg, 255))
        left_panel = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
        left_draw = ImageDraw.Draw(left_panel)

        # Fill left rectangle
        left_draw.rectangle([(0, 0), (SPLIT_X, CANVAS_H)], fill=(*left_bg, 255))

        # ── 3. Arch divider ───────────────────────────────────────────────────
        # Large circle centered at ARCH_CENTER that bulges right from SPLIT_X
        left_draw.ellipse(
            [
                (ARCH_CENTER_X - ARCH_RADIUS, ARCH_CENTER_Y - ARCH_RADIUS),
                (ARCH_CENTER_X + ARCH_RADIUS, ARCH_CENTER_Y + ARCH_RADIUS),
            ],
            fill=(*left_bg, 255),
        )
        img = Image.alpha_composite(img, left_panel)

        # ── 4. Person image — fills left panel area clipped by arch ───────────
        if person_bytes is not None:
            try:
                person_img = Image.open(io.BytesIO(person_bytes)).convert("RGBA")

                # Fit person to fill the full left panel height
                person_target_w = SPLIT_X + 120   # a bit wider than split
                person_target_h = CANVAS_H
                person_img = ImageOps.fit(
                    person_img, (person_target_w, person_target_h), Image.LANCZOS
                )

                # Build arch mask matching the arch shape on the left panel
                arch_mask = Image.new("L", (CANVAS_W, CANVAS_H), 0)
                mask_draw = ImageDraw.Draw(arch_mask)
                mask_draw.rectangle([(0, 0), (SPLIT_X, CANVAS_H)], fill=230)
                mask_draw.ellipse(
                    [
                        (ARCH_CENTER_X - ARCH_RADIUS, ARCH_CENTER_Y - ARCH_RADIUS),
                        (ARCH_CENTER_X + ARCH_RADIUS, ARCH_CENTER_Y + ARCH_RADIUS),
                    ],
                    fill=230,
                )

                # Paste person with arch mask
                person_canvas = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
                person_canvas.paste(person_img, (0, 0))
                img = Image.composite(person_canvas, img, arch_mask)

                # ── 5. Subtle right-edge gradient on person ───────────────────
                fade = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
                fade_draw = ImageDraw.Draw(fade)
                fade_width = 120
                fade_start_x = SPLIT_X - fade_width + 80
                for i in range(fade_width):
                    alpha = int((i / fade_width) * 160)
                    fade_draw.line(
                        [(fade_start_x + i, 0), (fade_start_x + i, CANVAS_H)],
                        fill=(*right_bg, alpha),
                    )
                img = Image.alpha_composite(img, fade)

            except Exception as exc:
                logger.warning("Could not paste person image: %s", exc)

        draw = ImageDraw.Draw(img)

        # ── 6. Logo (top-right of text column, small) ─────────────────────────
        text_x = TEXT_X
        y = TEXT_TOP

        if logo_bytes is not None:
            try:
                logo_img = Image.open(io.BytesIO(logo_bytes)).convert("RGBA")
                ratio = min(LOGO_MAX / logo_img.width, LOGO_MAX / logo_img.height)
                logo_w = int(logo_img.width * ratio)
                logo_h = int(logo_img.height * ratio)
                logo_img = logo_img.resize((logo_w, logo_h), Image.LANCZOS)
                logo_x = CANVAS_W - 60 - logo_w
                img.paste(logo_img, (logo_x, LOGO_TOP), logo_img)
            except Exception as exc:
                logger.warning("Could not paste logo: %s", exc)

        # ── 7. event_label (small caps, accent color) ─────────────────────────
        if event_label:
            y = _draw_left_block(
                draw, event_label.upper(), font_label,
                text_x, y, (*accent_rgb, 230), TEXT_MAX_W, line_gap=4,
            )
            y += 8

        # ── 8. Divider line ───────────────────────────────────────────────────
        draw.line([(text_x, y), (text_x + TEXT_MAX_W, y)], fill=(*accent_rgb, 120), width=2)
        y += 18

        # ── 9. Title (very large bold white, auto-shrink) ─────────────────────
        if title:
            font_title, title_lines = _shrink_title(draw, title, TEXT_MAX_W)
            y = _draw_title_lines(draw, title_lines, font_title, text_x, y, (255, 255, 255, 255))
            y += 20

        # ── 10. Subtitle ──────────────────────────────────────────────────────
        if subtitle:
            y = _draw_left_block(
                draw, subtitle, font_subtitle,
                text_x, y, (255, 255, 255, 190), TEXT_MAX_W, line_gap=6,
            )
            y += 24

        # ── 11. Date badge ────────────────────────────────────────────────────
        if date_time:
            y = _draw_date_badge(
                draw, date_time, font_date,
                text_x, y, accent_rgb, (255, 255, 255, 240), TEXT_MAX_W,
            )

        # ── 12. venue / via ───────────────────────────────────────────────────
        if venue:
            y = _draw_left_block(
                draw, venue, font_meta,
                text_x, y, (255, 255, 255, 180), TEXT_MAX_W,
            )
            y += 4
        if via:
            y = _draw_left_block(
                draw, via, font_meta,
                text_x, y, (255, 255, 255, 160), TEXT_MAX_W,
            )
            y += 24

        # ── 13. CTA button ────────────────────────────────────────────────────
        if cta:
            cta_rgb = _hex_to_rgb(brand_color_primary)
            # Make CTA button color visible against dark background
            cta_btn_rgb = _lighten(cta_rgb, 0.15) if max(cta_rgb) > 150 else _lighten(cta_rgb, 0.45)
            _draw_cta(draw, cta, font_cta, text_x, y, cta_btn_rgb, TEXT_MAX_W)

        # ── Export ────────────────────────────────────────────────────────────
        out = io.BytesIO()
        img.convert("RGB").save(out, format="PNG")
        return out.getvalue()

    return await asyncio.to_thread(_sync_compose)
