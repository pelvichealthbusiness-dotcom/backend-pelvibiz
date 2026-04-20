"""Pillow compositor for the hero-title post template.

Layer stack (bottom → top):
  1. Background image  (1080×1350 center-cropped)
  2. Dark overlay      (brand color tinted, 62% opacity)
  3. pre_title text    (small, white, Montserrat Regular, centered)
  4. main_title text   (large, white, Montserrat Black, centered)
  5. accent_word text  (large, brand primary color, Montserrat Black, centered)
  6. handle/logo       (small, white, Montserrat Regular, bottom center)
"""

from __future__ import annotations

import asyncio
import io
import logging

from PIL import Image, ImageDraw

from app.utils.fonts import get_montserrat

logger = logging.getLogger(__name__)

# ── Canvas ────────────────────────────────────────────────────────────────────
CANVAS_W, CANVAS_H = 1080, 1350

# ── Overlay ───────────────────────────────────────────────────────────────────
OVERLAY_OPACITY = 0.62      # 62% black overlay
BRAND_TINT_RATIO = 0.18     # how much brand color bleeds into the black overlay

# ── Font sizes (px) ───────────────────────────────────────────────────────────
PRE_TITLE_SIZE = 44
MAIN_TITLE_SIZE = 112
ACCENT_SIZE = 132
HANDLE_SIZE = 30

# ── Spacing ───────────────────────────────────────────────────────────────────
GAP_PRE_MAIN = 6       # px between pre_title and main_title
GAP_MAIN_ACCENT = 0    # px between main_title and accent_word
VERTICAL_BIAS = -40    # shift text group upward from true center
HANDLE_BOTTOM_PAD = 56 # px from bottom edge


# ── Helpers ───────────────────────────────────────────────────────────────────

def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    c = hex_color.lstrip("#")
    if len(c) != 6:
        return (26, 158, 143)  # fallback teal
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def _blend_to_dark(brand_hex: str) -> tuple[int, int, int]:
    """Mix black with brand color at BRAND_TINT_RATIO for the overlay base."""
    br, bg, bb = _hex_to_rgb(brand_hex)
    return (
        int(br * BRAND_TINT_RATIO),
        int(bg * BRAND_TINT_RATIO),
        int(bb * BRAND_TINT_RATIO),
    )


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


def _text_x(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    """Return x offset to center text horizontally."""
    bbox = draw.textbbox((0, 0), text, font=font)
    return (CANVAS_W - (bbox[2] - bbox[0])) // 2


def _text_h(font, text: str) -> int:
    bbox = font.getbbox(text)
    return bbox[3] - bbox[1]


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

    font_pre, font_main, font_accent, font_handle = await asyncio.gather(
        get_montserrat("regular", PRE_TITLE_SIZE),
        get_montserrat("black", MAIN_TITLE_SIZE),
        get_montserrat("black", ACCENT_SIZE),
        get_montserrat("regular", HANDLE_SIZE),
    )

    def _sync_compose() -> bytes:
        # 1. Background
        bg = Image.open(io.BytesIO(background_bytes)).convert("RGBA")
        bg = _force_1080x1350(bg)

        # 2. Dark overlay (mostly black, slight brand tint)
        overlay_rgb = _blend_to_dark(brand_color_primary)
        overlay = Image.new(
            "RGBA",
            (CANVAS_W, CANVAS_H),
            (*overlay_rgb, int(255 * OVERLAY_OPACITY)),
        )
        img = Image.alpha_composite(bg, overlay)
        draw = ImageDraw.Draw(img)

        # 3. Measure text heights for vertical centering
        pre_h = _text_h(font_pre, pre_title)
        main_h = _text_h(font_main, main_title)
        accent_h = _text_h(font_accent, accent_word)
        group_h = pre_h + GAP_PRE_MAIN + main_h + GAP_MAIN_ACCENT + accent_h

        group_y = (CANVAS_H // 2) - (group_h // 2) + VERTICAL_BIAS
        pre_y = group_y
        main_y = pre_y + pre_h + GAP_PRE_MAIN
        accent_y = main_y + main_h + GAP_MAIN_ACCENT

        # 4. Draw text layers
        draw.text(
            (_text_x(draw, pre_title, font_pre), pre_y),
            pre_title, font=font_pre, fill=(255, 255, 255, 220),
        )
        draw.text(
            (_text_x(draw, main_title, font_main), main_y),
            main_title, font=font_main, fill=(255, 255, 255, 255),
        )
        draw.text(
            (_text_x(draw, accent_word, font_accent), accent_y),
            accent_word, font=font_accent, fill=(*_hex_to_rgb(brand_color_primary), 255),
        )

        # 5. Handle at bottom center
        handle_text = handle if handle.startswith("@") else f"@{handle}"
        handle_h = _text_h(font_handle, handle_text)
        handle_y = CANVAS_H - HANDLE_BOTTOM_PAD - handle_h
        draw.text(
            (_text_x(draw, handle_text, font_handle), handle_y),
            handle_text, font=font_handle, fill=(255, 255, 255, 180),
        )

        # 6. Export
        out = io.BytesIO()
        img.convert("RGB").save(out, format="PNG")
        return out.getvalue()

    return await asyncio.to_thread(_sync_compose)
