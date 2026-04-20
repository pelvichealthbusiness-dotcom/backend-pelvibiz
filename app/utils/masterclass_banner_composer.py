"""Pillow compositor for the masterclass-banner post template.

Layer stack (bottom → top):
  1. Background image  (1080×1350, center-cropped)
  2. Dark overlay      (brand-tinted, 70% opacity, full canvas)
  3. Person image      (380×480, rounded-rect, bottom-left)
  4. Logo              (120×120 max, top of right column, aspect-preserved)
  5. event_label       (small, brand secondary, Montserrat Regular)
  6. title             (large white bold, Montserrat Black, auto-shrink)
  7. subtitle          (medium white, Montserrat Regular)
  8. date_time         (small white, Montserrat Regular)
  9. venue             (small white, Montserrat Regular)
 10. via               (small white, Montserrat Regular)
 11. cta               (brand primary pill button + white text)
"""

from __future__ import annotations

import asyncio
import io
import logging
import textwrap

from PIL import Image, ImageDraw, ImageFont, ImageOps

from app.utils.fonts import get_montserrat, get_montserrat_sync

logger = logging.getLogger(__name__)

# ── Canvas ────────────────────────────────────────────────────────────────────
CANVAS_W, CANVAS_H = 1080, 1350

# ── Overlay ───────────────────────────────────────────────────────────────────
OVERLAY_OPACITY = 0.72
BRAND_TINT_RATIO = 0.15

# ── Person image ──────────────────────────────────────────────────────────────
PERSON_W, PERSON_H = 380, 480
PERSON_X, PERSON_Y = 55, 780   # bottom-left
PERSON_CORNER_R = 24

# ── Right column ─────────────────────────────────────────────────────────────
RIGHT_X = 490
RIGHT_MAX_W = 520  # max text width
LOGO_MAX = 110    # max logo dimension

# ── Font sizes (px) ───────────────────────────────────────────────────────────
LABEL_SIZE = 28
TITLE_SIZE = 86
SUBTITLE_SIZE = 38
META_SIZE = 30
CTA_SIZE = 32

# ── Y positions (starting point — advance dynamically) ────────────────────────
LOGO_Y = 690
LABEL_Y = 830


# ── Helpers ───────────────────────────────────────────────────────────────────

def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    c = hex_color.lstrip("#")
    if len(c) != 6:
        return (26, 158, 143)
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def _blend_to_dark(brand_hex: str) -> tuple[int, int, int]:
    br, bg, bb = _hex_to_rgb(brand_hex)
    return int(br * BRAND_TINT_RATIO), int(bg * BRAND_TINT_RATIO), int(bb * BRAND_TINT_RATIO)


def _ensure_visible_on_dark(hex_color: str) -> tuple[int, int, int]:
    """Return an RGB that reads clearly on a dark/black overlay."""
    r, g, b = _hex_to_rgb(hex_color)
    luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    if luminance >= 0.30:
        return r, g, b

    factor = 0.0
    while luminance < 0.35 and factor < 0.85:
        factor += 0.12
        r2 = int(r + (255 - r) * factor)
        g2 = int(g + (255 - g) * factor)
        b2 = int(b + (255 - b) * factor)
        luminance = (0.299 * r2 + 0.587 * g2 + 0.114 * b2) / 255
        r, g, b = r2, g2, b2

    return r, g, b


def _force_1080x1350(img: Image.Image) -> Image.Image:
    target_ratio = CANVAS_W / CANVAS_H
    src_ratio = img.width / img.height
    if src_ratio > target_ratio:
        new_w = int(img.height * target_ratio)
        left = (img.width - new_w) // 2
        img = img.crop((left, 0, left + new_w, img.height))
    else:
        new_h = int(img.width / target_ratio)
        top = (img.height - new_h) // 2
        img = img.crop((0, top, img.width, top + new_h))
    return img.resize((CANVAS_W, CANVAS_H), Image.LANCZOS)


def _make_rounded_rect_mask(width: int, height: int, radius: int) -> Image.Image:
    """Return an L-mode mask image with a white rounded rectangle on black."""
    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle([(0, 0), (width - 1, height - 1)], radius=radius, fill=255)
    return mask


def _draw_left_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    x: int,
    y: int,
    fill: tuple,
    max_width: int,
) -> int:
    """Draw left-aligned text, wrapping to fit max_width. Returns y after last line."""
    # Wrap text to fit within max_width pixels
    words = text.split()
    lines: list[str] = []
    current_line = ""
    for word in words:
        test = (current_line + " " + word).strip()
        bb = draw.textbbox((0, 0), test, font=font)
        if bb[2] - bb[0] <= max_width:
            current_line = test
        else:
            if current_line:
                lines.append(current_line)
            current_line = word
    if current_line:
        lines.append(current_line)

    if not lines:
        lines = [text]

    line_gap = 6
    for line in lines:
        bb = draw.textbbox((0, 0), line, font=font)
        h = bb[3] - bb[1]
        draw.text((x, y), line, font=font, fill=fill)
        y += h + line_gap

    return y


def _shrink_title_to_fit(
    text: str,
    max_size: int,
    min_size: int,
    max_width: int,
    draw: ImageDraw.ImageDraw,
) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    """Shrink font until title fits within max_width, wrapping if needed."""
    size = max_size
    while size >= min_size:
        font = get_montserrat_sync("black", size)
        bb = draw.textbbox((0, 0), text, font=font)
        if (bb[2] - bb[0]) <= max_width:
            return font, [text]
        size -= 6

    # At min_size: wrap into 2 lines
    font = get_montserrat_sync("black", min_size)
    words = text.split()
    mid = max(1, len(words) // 2)
    lines = [" ".join(words[:mid]), " ".join(words[mid:])]
    return font, lines


def _draw_title_lines(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    font: ImageFont.FreeTypeFont,
    x: int,
    y: int,
    fill: tuple,
    line_gap: int = 8,
) -> int:
    """Draw title lines left-aligned. Returns y after last line."""
    for line in lines:
        bb = draw.textbbox((0, 0), line, font=font)
        h = bb[3] - bb[1]
        draw.text((x, y), line, font=font, fill=fill)
        y += h + line_gap
    return y


def _draw_cta_button(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    x: int,
    y: int,
    brand_rgb: tuple[int, int, int],
    max_width: int,
) -> int:
    """Draw a filled rounded-rect CTA button. Returns y after the button."""
    padding_h = 24
    padding_v = 14
    radius = 16

    bb = draw.textbbox((0, 0), text, font=font)
    text_w = bb[2] - bb[0]
    text_h = bb[3] - bb[1]

    btn_w = min(text_w + padding_h * 2, max_width)
    btn_h = text_h + padding_v * 2

    # Draw filled rounded rectangle
    draw.rounded_rectangle(
        [(x, y), (x + btn_w, y + btn_h)],
        radius=radius,
        fill=(*brand_rgb, 255),
    )

    # Center text in button
    text_x = x + (btn_w - text_w) // 2
    text_y = y + padding_v
    draw.text((text_x, text_y), text, font=font, fill=(255, 255, 255, 255))

    return y + btn_h + 12


# ── Main compositor ───────────────────────────────────────────────────────────

async def compose(
    background_bytes: bytes,
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

    font_label = await get_montserrat("regular", LABEL_SIZE)
    font_subtitle = await get_montserrat("regular", SUBTITLE_SIZE)
    font_meta = await get_montserrat("regular", META_SIZE)
    font_cta = await get_montserrat("bold", CTA_SIZE)

    def _sync_compose() -> bytes:
        # 1. Background
        bg = Image.open(io.BytesIO(background_bytes)).convert("RGBA")
        bg = _force_1080x1350(bg)

        # 2. Dark overlay (full canvas)
        overlay_rgb = _blend_to_dark(brand_color_primary)
        overlay = Image.new("RGBA", (CANVAS_W, CANVAS_H), (*overlay_rgb, int(255 * OVERLAY_OPACITY)))
        img = Image.alpha_composite(bg, overlay)
        draw = ImageDraw.Draw(img)

        # 3. Person image (bottom-left, rounded-rect mask)
        text_x = RIGHT_X
        if person_bytes is not None:
            try:
                person_img = Image.open(io.BytesIO(person_bytes)).convert("RGBA")
                person_img = ImageOps.fit(person_img, (PERSON_W, PERSON_H), Image.LANCZOS)
                mask = _make_rounded_rect_mask(PERSON_W, PERSON_H, PERSON_CORNER_R)
                img.paste(person_img, (PERSON_X, PERSON_Y), mask)
            except Exception as exc:
                logger.warning("Could not paste person image: %s", exc)
        else:
            # No person image — shift text further left
            text_x = 80

        # 4. Logo (top of right column, aspect-preserved)
        logo_y_end = LOGO_Y
        if logo_bytes is not None:
            try:
                logo_img = Image.open(io.BytesIO(logo_bytes)).convert("RGBA")
                ratio = min(LOGO_MAX / logo_img.width, LOGO_MAX / logo_img.height)
                new_w = int(logo_img.width * ratio)
                new_h = int(logo_img.height * ratio)
                logo_img = logo_img.resize((new_w, new_h), Image.LANCZOS)
                logo_x = CANVAS_W - 60 - new_w  # right-align near canvas edge
                img.paste(logo_img, (logo_x, LOGO_Y), logo_img)
                logo_y_end = LOGO_Y + new_h + 12
            except Exception as exc:
                logger.warning("Could not paste logo: %s", exc)

        # 5. event_label
        label_color = _ensure_visible_on_dark(brand_color_secondary)
        y = max(LABEL_Y, logo_y_end)
        if event_label:
            y = _draw_left_text(
                draw,
                event_label.upper(),
                font_label,
                text_x,
                y,
                (*label_color, 220),
                RIGHT_MAX_W,
            )
            y += 8

        # Divider line after label
        if event_label:
            draw.line([(text_x, y), (text_x + RIGHT_MAX_W, y)], fill=(*label_color, 100), width=1)
            y += 16

        # 6. title (large bold white, auto-shrink)
        if title:
            font_title, title_lines = _shrink_title_to_fit(
                title,
                TITLE_SIZE, 52,
                RIGHT_MAX_W,
                draw,
            )
            y = _draw_title_lines(draw, title_lines, font_title, text_x, y, (255, 255, 255, 255), line_gap=8)
            y += 16

        # 7. subtitle
        if subtitle:
            y = _draw_left_text(
                draw,
                subtitle,
                font_subtitle,
                text_x,
                y,
                (255, 255, 255, 200),
                RIGHT_MAX_W,
            )
            y += 20

        # 8. date_time
        if date_time:
            y = _draw_left_text(
                draw,
                date_time,
                font_meta,
                text_x,
                y,
                (255, 255, 255, 180),
                RIGHT_MAX_W,
            )
            y += 8

        # 9. venue
        if venue:
            y = _draw_left_text(
                draw,
                venue,
                font_meta,
                text_x,
                y,
                (255, 255, 255, 180),
                RIGHT_MAX_W,
            )
            y += 8

        # 10. via
        if via:
            y = _draw_left_text(
                draw,
                via,
                font_meta,
                text_x,
                y,
                (255, 255, 255, 160),
                RIGHT_MAX_W,
            )
            y += 20

        # 11. CTA button
        if cta:
            brand_rgb = _hex_to_rgb(brand_color_primary)
            _draw_cta_button(img, draw, cta, font_cta, text_x, y, brand_rgb, RIGHT_MAX_W)

        # 12. Export
        out = io.BytesIO()
        img.convert("RGB").save(out, format="PNG")
        return out.getvalue()

    return await asyncio.to_thread(_sync_compose)
