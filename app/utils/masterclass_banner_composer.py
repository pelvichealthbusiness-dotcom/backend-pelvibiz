"""Pillow compositor for the masterclass-banner post template.

Reference design: two-panel event poster
  Left panel  — light brand color (lavender-style), ~40% width
  Right panel — dark brand color (teal-style), ~60% width
  Decorative circle — right-panel color, bottom-left corner of left panel
  Person — no-background cutout, full height, left side overlapping split
  Text column — right panel, large title + mixed-color subtitle + date badge + cta
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
SPLIT_X = 430          # left panel width (~40%)

# ── Decorative circle — bottom-left, right-panel color ────────────────────────
CIRCLE_CX = 260        # center x
CIRCLE_CY = 1200       # center y (bottom area)
CIRCLE_R  = 390        # radius

# ── Text column ────────────────────────────────────────────────────────────────
TEXT_X      = 460
TEXT_MAX_W  = CANVAS_W - TEXT_X - 40    # 580 px
TEXT_TOP    = 80

# ── Logo ───────────────────────────────────────────────────────────────────────
LOGO_MAX    = 150          # doubled from 75
LOGO_BOTTOM = 60           # anchor to bottom instead of top
LOGO_RIGHT  = 60

# ── Font sizes (px) ───────────────────────────────────────────────────────────
LABEL_SIZE   = 26
TITLE_MAX    = 130
TITLE_MIN    = 52
SUBTITLE_SIZE = 58      # large — "en tiempos" line
SUBTITLE_ACCENT_SIZE = 68  # accent line — "de IA"
META_SIZE    = 26
DATE_SIZE    = 38
CTA_SIZE     = 38


# ── Color helpers ─────────────────────────────────────────────────────────────

def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    c = h.lstrip("#")
    if len(c) != 6:
        return (26, 120, 110)
    return int(c[:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def _lighten(rgb: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    r, g, b = rgb
    return (
        int(r + (255 - r) * factor),
        int(g + (255 - g) * factor),
        int(b + (255 - b) * factor),
    )


def _darken(rgb: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    r, g, b = rgb
    return int(r * (1 - factor)), int(g * (1 - factor)), int(b * (1 - factor))


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


def _auto_fit_title(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_w: int,
    max_lines: int = 3,
) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    """Find largest font size where title wraps to at most max_lines."""
    for size in range(TITLE_MAX, TITLE_MIN - 1, -4):
        font = get_montserrat_sync("black", size)
        lines = _wrap_text(draw, text, font, max_w)
        if len(lines) <= max_lines:
            return font, lines
    font = get_montserrat_sync("black", TITLE_MIN)
    return font, _wrap_text(draw, text, font, max_w)


def _draw_lines(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    font: ImageFont.FreeTypeFont,
    x: int,
    y: int,
    fill: tuple,
    line_gap: int = 8,
) -> int:
    for line in lines:
        bb = draw.textbbox((0, 0), line, font=font)
        draw.text((x, y), line, font=font, fill=fill)
        y += int(bb[3] - bb[1]) + line_gap
    return y


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
    return _draw_lines(draw, _wrap_text(draw, text, font, max_w), font, x, y, fill, line_gap)


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
    pad_h, pad_v, r = 24, 14, 18
    lines = _wrap_text(draw, text, font, max_w - pad_h * 2)
    line_heights = [draw.textbbox((0, 0), l, font=font)[3] - draw.textbbox((0, 0), l, font=font)[1] for l in lines]
    total_h = sum(line_heights) + 8 * (len(lines) - 1)
    badge_h = total_h + pad_v * 2
    max_lw = max((draw.textbbox((0, 0), l, font=font)[2] - draw.textbbox((0, 0), l, font=font)[0]) for l in lines)
    badge_w = min(max_lw + pad_h * 2, max_w)

    draw.rounded_rectangle(
        [(x, y), (x + badge_w, y + badge_h)],
        radius=r, outline=(*border_color, 220), width=3,
    )
    ty = y + pad_v
    for i, line in enumerate(lines):
        draw.text((x + pad_h, ty), line, font=font, fill=text_color)
        ty += line_heights[i] + 8
    return int(y + badge_h + 20)


# ── Main compositor ───────────────────────────────────────────────────────────

async def compose(
    background_bytes: bytes | None,
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
    """Compose masterclass-banner and return PNG bytes."""

    font_subtitle = await get_montserrat("regular", SUBTITLE_SIZE)
    font_sub_acc  = await get_montserrat("bold", SUBTITLE_ACCENT_SIZE)
    font_meta     = await get_montserrat("regular", META_SIZE)
    font_date     = await get_montserrat("bold", DATE_SIZE)
    font_cta      = await get_montserrat("bold", CTA_SIZE)

    def _sync_compose() -> bytes:
        primary_rgb = _hex_to_rgb(brand_color_primary)
        # Left panel: very light brand color (lavender-like for teal, etc.)
        left_bg  = _lighten(primary_rgb, 0.72)
        # Right panel: very dark brand color
        right_bg = _darken(primary_rgb, 0.50)
        # Accent: secondary color, ensured visible on dark
        accent_rgb = _ensure_visible_on_dark(brand_color_secondary)

        # ── 1. Base: background photo (or solid fallback) ─────────────────────
        if background_bytes is not None:
            try:
                bg_img = Image.open(io.BytesIO(background_bytes)).convert("RGBA")
                bg_img = ImageOps.fit(bg_img, (CANVAS_W, CANVAS_H), Image.Resampling.LANCZOS)
                img = bg_img
            except Exception as exc:
                logger.warning("Could not load background: %s", exc)
                img = Image.new("RGBA", (CANVAS_W, CANVAS_H), (*right_bg, 255))
        else:
            img = Image.new("RGBA", (CANVAS_W, CANVAS_H), (*right_bg, 255))

        # ── 2. Single overlay layer: left light + right dark, one composite ──────
        overlay = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        od.rectangle([(0, 0), (SPLIT_X, CANVAS_H)], fill=(*left_bg, 185))
        od.rectangle([(SPLIT_X, 0), (CANVAS_W, CANVAS_H)], fill=(*right_bg, 220))
        img = Image.alpha_composite(img, overlay)

        # ── 3. Decorative circle — bottom-left, right-panel color ─────────────
        circ_layer = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
        cd = ImageDraw.Draw(circ_layer)
        cd.ellipse(
            [
                (CIRCLE_CX - CIRCLE_R, CIRCLE_CY - CIRCLE_R),
                (CIRCLE_CX + CIRCLE_R, CIRCLE_CY + CIRCLE_R),
            ],
            fill=(*right_bg, 230),
        )
        img = Image.alpha_composite(img, circ_layer)

        # ── 4. Person cutout — full height, centered in left panel ────────────
        if person_bytes is not None:
            try:
                person_img = Image.open(io.BytesIO(person_bytes)).convert("RGBA")

                # Scale to 80% canvas height, cap width to left panel
                target_h = int(CANVAS_H * 0.75)
                scale = target_h / person_img.height
                pw = int(person_img.width * scale)
                ph = target_h
                # If wider than the left panel, constrain by width instead
                if pw > SPLIT_X - 20:
                    pw = SPLIT_X - 20
                    ph = int(person_img.height * (pw / person_img.width))
                person_img = person_img.resize((pw, ph), Image.Resampling.LANCZOS)

                # Center in left panel, anchor to bottom
                paste_x = (SPLIT_X - pw) // 2
                paste_y = CANVAS_H - ph

                img.paste(person_img, (paste_x, paste_y), person_img)
            except Exception as exc:
                logger.warning("Could not paste person image: %s", exc)

        draw = ImageDraw.Draw(img)
        text_x = TEXT_X
        y = TEXT_TOP

        # ── 5. Logo — top right ───────────────────────────────────────────────
        if logo_bytes is not None:
            try:
                logo_img = Image.open(io.BytesIO(logo_bytes)).convert("RGBA")
                ratio = min(LOGO_MAX / logo_img.width, LOGO_MAX / logo_img.height)
                lw = int(logo_img.width * ratio)
                lh = int(logo_img.height * ratio)
                logo_img = logo_img.resize((lw, lh), Image.Resampling.LANCZOS)
                img.paste(logo_img, (CANVAS_W - LOGO_RIGHT - lw, CANVAS_H - LOGO_BOTTOM - lh), logo_img)
            except Exception as exc:
                logger.warning("Could not paste logo: %s", exc)

        # ── 6. event_label — italic small caps accent ─────────────────────────
        if event_label:
            font_lbl_it = get_montserrat_sync("bold", LABEL_SIZE)
            y = _draw_wrapped(draw, event_label.upper(), font_lbl_it,
                              text_x, y, (*accent_rgb, 210), TEXT_MAX_W, line_gap=4)
            y += 12

        # ── 7. Title — massive white ───────────────────────────────────────────
        if title:
            font_title, title_lines = _auto_fit_title(draw, title, TEXT_MAX_W)
            y = _draw_lines(draw, title_lines, font_title,
                            text_x, y, (255, 255, 255, 255), line_gap=6)
            y += 16

        # ── 8. Subtitle — split at \n: first part white, last part accent ─────
        if subtitle:
            parts = subtitle.split("\n", 1)
            if len(parts) == 2:
                # First line: regular white
                y = _draw_wrapped(draw, parts[0], font_subtitle,
                                  text_x, y, (255, 255, 255, 230), TEXT_MAX_W, line_gap=6)
                # Second line: bold accent (larger)
                y = _draw_wrapped(draw, parts[1], font_sub_acc,
                                  text_x, y, (*accent_rgb, 255), TEXT_MAX_W, line_gap=6)
            else:
                # No split: render all in white
                y = _draw_wrapped(draw, subtitle, font_subtitle,
                                  text_x, y, (255, 255, 255, 230), TEXT_MAX_W, line_gap=6)
            y += 24

        # ── 9. Date badge — bordered rounded rect ────────────────────────────
        if date_time:
            y = _draw_date_badge(draw, date_time, font_date,
                                 text_x, y, accent_rgb, (255, 255, 255, 245), TEXT_MAX_W)

        # ── 10. venue ─────────────────────────────────────────────────────────
        if venue:
            y = _draw_wrapped(draw, venue, font_meta,
                              text_x, y, (255, 255, 255, 180), TEXT_MAX_W)
            y += 6

        # ── 11. via — small caps accent ───────────────────────────────────────
        if via:
            y = _draw_wrapped(draw, via.upper(), font_meta,
                              text_x, y, (*accent_rgb, 200), TEXT_MAX_W)
            y += 16

        # ── 12. CTA — bold text, no button background ─────────────────────────
        if cta:
            y = _draw_wrapped(draw, cta, font_cta,
                              text_x, y, (255, 255, 255, 255), TEXT_MAX_W)

        out = io.BytesIO()
        img.convert("RGB").save(out, format="PNG")
        return out.getvalue()

    return await asyncio.to_thread(_sync_compose)
