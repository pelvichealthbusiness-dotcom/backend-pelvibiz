"""Pillow compositor for the hero-title post template.

Layer stack (bottom → top):
  1. Background image  (1080×1350 center-cropped)
  2. Dark overlay      (brand color tinted, 62% opacity)
  3. pre_title text    (small, white, Montserrat Regular, centered, wrapped)
  4. main_title text   (large, white, Montserrat Bold, centered, auto-shrink)
  5. accent_word text  (large, brand primary color, Montserrat Bold, centered, auto-shrink)
  6. handle            (small, white, Montserrat Regular, bottom center)
"""

from __future__ import annotations

import asyncio
import io
import logging
import textwrap

from PIL import Image, ImageDraw, ImageFont

from app.utils.fonts import get_montserrat

logger = logging.getLogger(__name__)

# ── Canvas ────────────────────────────────────────────────────────────────────
CANVAS_W, CANVAS_H = 1080, 1350
MAX_TEXT_W = 920   # max usable width for text (leave 80px padding each side)

# ── Overlay ───────────────────────────────────────────────────────────────────
OVERLAY_OPACITY = 0.65
BRAND_TINT_RATIO = 0.18

# ── Font sizes (px) ───────────────────────────────────────────────────────────
PRE_TITLE_SIZE = 40
MAIN_TITLE_SIZE = 108
ACCENT_SIZE = 128
HANDLE_SIZE = 28

# ── Spacing ───────────────────────────────────────────────────────────────────
GAP_PRE_MAIN   = 10
GAP_MAIN_ACCENT = 4
VERTICAL_BIAS  = -30
HANDLE_BOTTOM_PAD = 52


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
    """Return an RGB that reads clearly on a dark/black overlay.

    Relative luminance below 0.15 means the color is too dark — boost it
    by mixing with white until it's legible.
    """
    r, g, b = _hex_to_rgb(hex_color)
    # Relative luminance (sRGB approximation)
    luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    if luminance >= 0.30:
        return r, g, b  # already bright enough

    # Boost: mix with white until luminance is acceptable
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


def _text_block_size(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    font: ImageFont.FreeTypeFont,
    line_gap: int = 8,
) -> tuple[int, int]:
    """Return (max_width, total_height) for a list of text lines."""
    widths, heights = [], []
    for line in lines:
        bb = draw.textbbox((0, 0), line, font=font)
        widths.append(bb[2] - bb[0])
        heights.append(bb[3] - bb[1])
    total_h = sum(heights) + line_gap * (len(lines) - 1)
    return max(widths, default=0), total_h


def _draw_centered_lines(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    font: ImageFont.FreeTypeFont,
    start_y: int,
    fill: tuple,
    line_gap: int = 8,
) -> int:
    """Draw lines centered horizontally. Returns y position after last line."""
    y = start_y
    for line in lines:
        bb = draw.textbbox((0, 0), line, font=font)
        w = bb[2] - bb[0]
        h = bb[3] - bb[1]
        x = (CANVAS_W - w) // 2
        draw.text((x, y), line, font=font, fill=fill)
        y += h + line_gap
    return y


def _shrink_font_to_fit(
    font_loader,
    text: str,
    max_size: int,
    min_size: int,
    draw: ImageDraw.ImageDraw,
) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    """Shrink font size until text fits within MAX_TEXT_W, wrapping if needed."""
    size = max_size
    while size >= min_size:
        font = font_loader(size)
        # Try single line first
        bb = draw.textbbox((0, 0), text, font=font)
        w = bb[2] - bb[0]
        if w <= MAX_TEXT_W:
            return font, [text]
        size -= 6

    # At min_size still too wide — wrap into 2 lines
    font = font_loader(min_size)
    words = text.split()
    mid = max(1, len(words) // 2)
    lines = [" ".join(words[:mid]), " ".join(words[mid:])]
    return font, lines


def _wrap_pre_title(
    text: str,
    font: ImageFont.FreeTypeFont,
    draw: ImageDraw.ImageDraw,
    max_chars_hint: int = 36,
) -> list[str]:
    """Wrap pre_title to fit MAX_TEXT_W, using textwrap then verifying pixel width."""
    raw_lines = textwrap.wrap(text, width=max_chars_hint) or [text]
    result = []
    for line in raw_lines:
        bb = draw.textbbox((0, 0), line, font=font)
        w = bb[2] - bb[0]
        if w <= MAX_TEXT_W:
            result.append(line)
        else:
            # force narrower wrap
            result.extend(textwrap.wrap(line, width=max_chars_hint - 8) or [line])
    return result or [text]


# ── Main compositor ───────────────────────────────────────────────────────────

async def compose(
    background_bytes: bytes,
    pre_title: str,
    main_title: str,
    accent_word: str,
    brand_color_primary: str,
    handle: str,
) -> bytes:
    """Compose the hero-title image and return raw PNG bytes."""

    font_pre = await get_montserrat("regular", PRE_TITLE_SIZE)
    font_handle = await get_montserrat("regular", HANDLE_SIZE)

    def _sync_compose() -> bytes:
        from app.utils.fonts import get_montserrat_sync

        # 1. Background
        bg = Image.open(io.BytesIO(background_bytes)).convert("RGBA")
        bg = _force_1080x1350(bg)

        # 2. Dark overlay
        overlay_rgb = _blend_to_dark(brand_color_primary)
        overlay = Image.new("RGBA", (CANVAS_W, CANVAS_H), (*overlay_rgb, int(255 * OVERLAY_OPACITY)))
        img = Image.alpha_composite(bg, overlay)
        draw = ImageDraw.Draw(img)

        # 3. Resolve fonts with auto-shrink
        font_main, main_lines = _shrink_font_to_fit(
            lambda s: get_montserrat_sync("black", s),
            main_title.upper(),
            MAIN_TITLE_SIZE, 64, draw,
        )
        font_accent, accent_lines = _shrink_font_to_fit(
            lambda s: get_montserrat_sync("black", s),
            accent_word.upper(),
            ACCENT_SIZE, 72, draw,
        )

        # 4. Wrap pre_title
        pre_lines = _wrap_pre_title(pre_title, font_pre, draw)

        # 5. Measure total group height
        _, pre_h    = _text_block_size(draw, pre_lines,    font_pre,    line_gap=6)
        _, main_h   = _text_block_size(draw, main_lines,   font_main,   line_gap=8)
        _, accent_h = _text_block_size(draw, accent_lines, font_accent, line_gap=8)

        group_h = pre_h + GAP_PRE_MAIN + main_h + GAP_MAIN_ACCENT + accent_h
        group_y = (CANVAS_H // 2) - (group_h // 2) + VERTICAL_BIAS

        # 6. Draw text layers
        y = group_y
        y = _draw_centered_lines(draw, pre_lines, font_pre, y, (255, 255, 255, 210), line_gap=6)
        y += GAP_PRE_MAIN
        y = _draw_centered_lines(draw, main_lines, font_main, y, (255, 255, 255, 255), line_gap=8)
        y += GAP_MAIN_ACCENT
        accent_rgb = _ensure_visible_on_dark(brand_color_primary)
        _draw_centered_lines(draw, accent_lines, font_accent, y, (*accent_rgb, 255), line_gap=8)

        # 7. Handle at bottom
        handle_text = handle if handle.startswith("@") else f"@{handle}"
        bb = draw.textbbox((0, 0), handle_text, font=font_handle)
        handle_w = bb[2] - bb[0]
        handle_h_px = bb[3] - bb[1]
        handle_x = (CANVAS_W - handle_w) // 2
        handle_y = CANVAS_H - HANDLE_BOTTOM_PAD - handle_h_px
        draw.text((handle_x, handle_y), handle_text, font=font_handle, fill=(255, 255, 255, 170))

        # 8. Export
        out = io.BytesIO()
        img.convert("RGB").save(out, format="PNG")
        return out.getvalue()

    return await asyncio.to_thread(_sync_compose)
