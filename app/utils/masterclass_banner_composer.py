"""Pillow compositor for the masterclass-banner post template.

Two-panel split layout:
  1. Right panel  — solid dark (brand_color_primary darkened), full canvas
  2. Left panel   — solid brand_color_primary (lighter), left half + arch bulge
  3. Person       — background-removed cutout, full height, anchored bottom-left
  4. Bottom fade  — subtle gradient on person bottom edge for grounding
  5. Logo         — top-right corner, small
  6. event_label  — small caps accent color
  7. Divider line — accent color
  8. title        — large bold white, auto-wrap + auto-shrink
  9. subtitle     — medium white
 10. Date badge   — bordered rounded rect
 11. venue / via  — small meta text
 12. CTA button   — filled rounded rect
"""

from __future__ import annotations

import asyncio
import io
import logging

from PIL import Image, ImageDraw, ImageFont

from app.utils.fonts import get_montserrat, get_montserrat_sync

logger = logging.getLogger(__name__)

# ── Canvas ────────────────────────────────────────────────────────────────────
CANVAS_W, CANVAS_H = 1080, 1350

# ── Panel split ───────────────────────────────────────────────────────────────
SPLIT_X = 470
ARCH_CENTER_X = 410
ARCH_CENTER_Y = 750
ARCH_RADIUS = 830

# ── Right column (text area) ──────────────────────────────────────────────────
TEXT_X = 500
TEXT_RIGHT_MARGIN = 50
TEXT_MAX_W = CANVAS_W - TEXT_X - TEXT_RIGHT_MARGIN   # 530 px
LOGO_MAX = 80

# ── Font sizes (px) ───────────────────────────────────────────────────────────
LABEL_SIZE = 28
TITLE_MAX_SIZE = 72
TITLE_MIN_SIZE = 36
SUBTITLE_SIZE = 34
META_SIZE = 26
CTA_SIZE = 32
DATE_BADGE_SIZE = 28

# ── Y start ───────────────────────────────────────────────────────────────────
LOGO_TOP = 70
TEXT_TOP = 180


# ── Color helpers ─────────────────────────────────────────────────────────────

def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    c = h.lstrip("#")
    if len(c) != 6:
        return (26, 120, 110)
    return int(c[:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def _lighten(rgb: tuple[int, int, int], factor: float = 0.35) -> tuple[int, int, int]:
    r, g, b = rgb
    return (
        int(r + (255 - r) * factor),
        int(g + (255 - g) * factor),
        int(b + (255 - b) * factor),
    )


def _darken(rgb: tuple[int, int, int], factor: float = 0.25) -> tuple[int, int, int]:
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
    for line in _wrap_text(draw, text, font, max_w):
        bb = draw.textbbox((0, 0), line, font=font)
        draw.text((x, y), line, font=font, fill=fill)
        y += (bb[3] - bb[1]) + line_gap
    return y


def _auto_fit_title(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_w: int,
    max_lines: int = 3,
) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    """Find largest font size where the title wraps to at most max_lines."""
    for size in range(TITLE_MAX_SIZE, TITLE_MIN_SIZE - 1, -4):
        font = get_montserrat_sync("black", size)
        lines = _wrap_text(draw, text, font, max_w)
        if len(lines) <= max_lines:
            return font, lines
    font = get_montserrat_sync("black", TITLE_MIN_SIZE)
    return font, _wrap_text(draw, text, font, max_w)


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
    pad_h, pad_v, r = 18, 10, 12
    lines = _wrap_text(draw, text, font, max_w - pad_h * 2)
    line_heights = []
    for line in lines:
        bb = draw.textbbox((0, 0), line, font=font)
        line_heights.append(bb[3] - bb[1])

    total_text_h = sum(line_heights) + 6 * (len(lines) - 1)
    badge_h = total_text_h + pad_v * 2

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

    return y + badge_h + 14


def _draw_cta(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    x: int,
    y: int,
    bg_color: tuple,
    max_w: int,
) -> int:
    pad_h, pad_v, r = 30, 14, 16
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
        left_bg = _lighten(primary_rgb, 0.45)
        right_bg = _darken(primary_rgb, 0.18)
        accent_rgb = _ensure_visible_on_dark(brand_color_secondary)

        # ── 1 & 2. Two-panel background with arch divider ─────────────────────
        img = Image.new("RGBA", (CANVAS_W, CANVAS_H), (*right_bg, 255))
        left_panel = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
        left_draw = ImageDraw.Draw(left_panel)

        left_draw.rectangle([(0, 0), (SPLIT_X, CANVAS_H)], fill=(*left_bg, 255))
        left_draw.ellipse(
            [
                (ARCH_CENTER_X - ARCH_RADIUS, ARCH_CENTER_Y - ARCH_RADIUS),
                (ARCH_CENTER_X + ARCH_RADIUS, ARCH_CENTER_Y + ARCH_RADIUS),
            ],
            fill=(*left_bg, 255),
        )
        img = Image.alpha_composite(img, left_panel)

        # ── 3. Person cutout — placed bottom-left, full height ────────────────
        if person_bytes is not None:
            try:
                person_img = Image.open(io.BytesIO(person_bytes)).convert("RGBA")

                # Scale to fill the full canvas height, keep aspect ratio
                scale = CANVAS_H / person_img.height
                pw = int(person_img.width * scale)
                ph = CANVAS_H
                person_img = person_img.resize((pw, ph), Image.LANCZOS)

                # Center the person in the left panel area
                paste_x = max(0, (SPLIT_X - pw) // 2)

                # ── 4. Bottom fade for grounding the cutout ───────────────────
                fade_h = 180
                fade_overlay = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
                fade_draw = ImageDraw.Draw(fade_overlay)
                for i in range(fade_h):
                    alpha = int((i / fade_h) ** 1.5 * 200)
                    fade_draw.line(
                        [(0, ph - fade_h + i), (pw, ph - fade_h + i)],
                        fill=(*right_bg, alpha),
                    )
                person_img = Image.alpha_composite(person_img, fade_overlay)

                img.paste(person_img, (paste_x, 0), person_img)

            except Exception as exc:
                logger.warning("Could not paste person image: %s", exc)

        draw = ImageDraw.Draw(img)

        # ── 5. Logo (top-right corner) ────────────────────────────────────────
        text_x = TEXT_X
        y = TEXT_TOP

        if logo_bytes is not None:
            try:
                logo_img = Image.open(io.BytesIO(logo_bytes)).convert("RGBA")
                ratio = min(LOGO_MAX / logo_img.width, LOGO_MAX / logo_img.height)
                logo_w = int(logo_img.width * ratio)
                logo_h = int(logo_img.height * ratio)
                logo_img = logo_img.resize((logo_w, logo_h), Image.LANCZOS)
                logo_x = CANVAS_W - 50 - logo_w
                img.paste(logo_img, (logo_x, LOGO_TOP), logo_img)
            except Exception as exc:
                logger.warning("Could not paste logo: %s", exc)

        # ── 6. event_label ────────────────────────────────────────────────────
        if event_label:
            y = _draw_left_block(
                draw, event_label.upper(), font_label,
                text_x, y, (*accent_rgb, 230), TEXT_MAX_W, line_gap=4,
            )
            y += 10

        # ── 7. Divider line ───────────────────────────────────────────────────
        draw.line([(text_x, y), (text_x + TEXT_MAX_W, y)], fill=(*accent_rgb, 120), width=2)
        y += 20

        # ── 8. Title ──────────────────────────────────────────────────────────
        if title:
            font_title, title_lines = _auto_fit_title(draw, title, TEXT_MAX_W)
            y = _draw_title_lines(draw, title_lines, font_title, text_x, y, (255, 255, 255, 255))
            y += 18

        # ── 9. Subtitle ───────────────────────────────────────────────────────
        if subtitle:
            y = _draw_left_block(
                draw, subtitle, font_subtitle,
                text_x, y, (255, 255, 255, 190), TEXT_MAX_W, line_gap=6,
            )
            y += 22

        # ── 10. Date badge ────────────────────────────────────────────────────
        if date_time:
            y = _draw_date_badge(
                draw, date_time, font_date,
                text_x, y, accent_rgb, (255, 255, 255, 240), TEXT_MAX_W,
            )

        # ── 11. venue / via ───────────────────────────────────────────────────
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
            y += 22

        # ── 12. CTA button ────────────────────────────────────────────────────
        if cta:
            cta_btn_rgb = _lighten(primary_rgb, 0.15) if max(primary_rgb) > 150 else _lighten(primary_rgb, 0.45)
            _draw_cta(draw, cta, font_cta, text_x, y, cta_btn_rgb, TEXT_MAX_W)

        out = io.BytesIO()
        img.convert("RGB").save(out, format="PNG")
        return out.getvalue()

    return await asyncio.to_thread(_sync_compose)
