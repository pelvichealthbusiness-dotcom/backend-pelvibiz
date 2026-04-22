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
TEXT_MAX_W = 490   # stays within left column before person zone

# ── Person image ───────────────────────────────────────────────────────────────
PERSON_X     = 560   # left edge of person zone
PERSON_MAX_W = CANVAS_W - PERSON_X   # 520

# ── Logo row (bottom of content area) ──────────────────────────────────────────
LOGO_Y_FROM_BOTTOM = 50
LOGO_MAX_H = 160
LOGO_MAX_W = 340
LOGO_GAP   = 52

# ── Font sizes ─────────────────────────────────────────────────────────────────
LABEL_SIZE  = 28   # event label inside white box
DATE_SIZE   = 30   # date inside white box
TITLE_MAX   = 82   # display title — large but leaves room for person
TITLE_MIN   = 38
TIP_SIZE    = 42
VENUE_SIZE  = 28   # venue / platform line below tips
DOT_R       = 13   # radius of bullet dot

# ── White event box (overlaps collage bottom) ───────────────────────────────────
BOX_X       = 48
BOX_OVERLAP = 175  # how many px the box overlaps into the collage from below
BOX_PAD_H   = 28   # horizontal padding inside box
BOX_PAD_V   = 20   # vertical padding inside box
BOX_RADIUS  = 20
BOX_MAX_W   = 580


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
    content_bg_bytes: bytes | None,
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
    venue: str,
    brand_color_primary: str,
    brand_color_secondary: str,
) -> bytes:
    """Compose wellness-workshop flyer and return PNG bytes."""

    font_label = await get_montserrat("bold", LABEL_SIZE)
    font_date  = await get_montserrat("bold", DATE_SIZE)
    font_tip   = await get_montserrat("semibold", TIP_SIZE)
    font_venue = await get_montserrat("regular", VENUE_SIZE)

    def _sync_compose() -> bytes:
        primary_rgb = _hex_to_rgb(brand_color_primary)
        accent_rgb  = _ensure_visible_on_dark(brand_color_primary)
        dark_bg     = _darken(primary_rgb, 0.78)

        # ── 1. Base canvas (dark background) ─────────────────────────────────
        img = Image.new("RGBA", (CANVAS_W, CANVAS_H), (*dark_bg, 255))

        # ── 2. Top collage — 3 panels ─────────────────────────────────────────
        light_fallback = _lighten(primary_rgb, 0.35)
        img_rgb = img.convert("RGB")
        _paste_collage_panel(img_rgb, bg1_bytes, 0, light_fallback)
        _paste_collage_panel(img_rgb, bg2_bytes, PANEL_W + COLLAGE_GAP, light_fallback)
        _paste_collage_panel(img_rgb, bg3_bytes, (PANEL_W + COLLAGE_GAP) * 2, light_fallback)
        img = img_rgb.convert("RGBA")

        draw = ImageDraw.Draw(img)

        # ── 3. White event box (overlaps collage bottom) ──────────────────────
        # Measure content to compute box height dynamically
        label_lines = _wrap_text(draw, event_label.upper(), font_label, BOX_MAX_W - BOX_PAD_H * 2) if event_label else []
        date_lines  = _wrap_text(draw, date_time, font_date, BOX_MAX_W - BOX_PAD_H * 2) if date_time else []

        def _line_h(font, lines):
            return sum(draw.textbbox((0,0), l, font=font)[3] - draw.textbbox((0,0), l, font=font)[1] + 4 for l in lines)

        label_block_h = _line_h(font_label, label_lines)
        date_block_h  = _line_h(font_date,  date_lines)
        inner_gap     = 10 if (label_lines and date_lines) else 0
        box_h = BOX_PAD_V * 2 + label_block_h + inner_gap + date_block_h
        box_h = max(box_h, 100)

        box_y = COLLAGE_H - BOX_OVERLAP
        box_x = BOX_X

        draw.rounded_rectangle(
            [(box_x, box_y), (box_x + BOX_MAX_W, box_y + box_h)],
            radius=BOX_RADIUS,
            fill=(255, 255, 255, 248),
        )

        # event_label — brand accent color inside box
        ty = box_y + BOX_PAD_V
        for line in label_lines:
            draw.text((box_x + BOX_PAD_H, ty), line, font=font_label, fill=(*accent_rgb, 255))
            ty += draw.textbbox((0,0), line, font=font_label)[3] - draw.textbbox((0,0), line, font=font_label)[1] + 4

        ty += inner_gap

        # date_time — dark text inside box
        for line in date_lines:
            draw.text((box_x + BOX_PAD_H, ty), line, font=font_date, fill=(30, 30, 30, 255))
            ty += draw.textbbox((0,0), line, font=font_date)[3] - draw.textbbox((0,0), line, font=font_date)[1] + 4

        # ── 3b. Subtle content-area background (dedicated ambient, no people) ───
        _bg_overlay = content_bg_bytes
        if _bg_overlay is not None:
            try:
                bg_content = Image.open(io.BytesIO(_bg_overlay)).convert("RGBA")
                bg_content = bg_content.resize((CANVAS_W, CONTENT_H), Image.Resampling.LANCZOS)
                r_ch, g_ch, b_ch, a_ch = bg_content.split()
                a_ch = a_ch.point([int(i * 0.13) for i in range(256)])
                bg_content = Image.merge("RGBA", (r_ch, g_ch, b_ch, a_ch))
                img.paste(bg_content, (0, COLLAGE_H), bg_content)
                draw = ImageDraw.Draw(img)
            except Exception as exc:
                logger.warning("Could not paste content background: %s", exc)

        # ── 4. Person image — half body (head + torso), right zone ───────────
        if person_bytes is not None:
            try:
                person_img = Image.open(io.BytesIO(person_bytes)).convert("RGBA")
                bbox = person_img.getbbox()
                if bbox:
                    person_img = person_img.crop(bbox)

                # Use the LARGER of the two scales so the person fills either
                # full zone width OR full content height — whichever is bigger.
                # This makes the person as large as possible within the zone.
                scale_h = CONTENT_H / person_img.height
                scale_w = PERSON_MAX_W / person_img.width
                scale = max(scale_h, scale_w)
                pw = int(person_img.width * scale)
                ph = int(person_img.height * scale)
                person_img = person_img.resize((pw, ph), Image.Resampling.LANCZOS)

                # Center-crop horizontally if wider than zone
                if pw > PERSON_MAX_W:
                    left = (pw - PERSON_MAX_W) // 2
                    person_img = person_img.crop((left, 0, left + PERSON_MAX_W, ph))
                    pw = PERSON_MAX_W

                # Keep only top 52% — head + chest + waist (half-body)
                crop_h = int(ph * 0.52)
                person_img = person_img.crop((0, 0, pw, crop_h))

                paste_x = PERSON_X + (PERSON_MAX_W - pw) // 2
                paste_y = CANVAS_H - crop_h + 50  # pushed down — bottom clips naturally
                img.paste(person_img, (paste_x, paste_y), person_img)
                draw = ImageDraw.Draw(img)
            except Exception as exc:
                logger.warning("Could not paste person image: %s", exc)

        # ── 5. Title (large display, starts below the white box) ──────────────
        # Safeguard: never let the title start inside the collage photo area
        y = max(box_y + box_h + 32, COLLAGE_H + 20)
        if title:
            title_max_w = TEXT_MAX_W
            font_title, title_lines = _auto_fit_title(draw, title, title_max_w)
            for line in title_lines:
                bb = draw.textbbox((0, 0), line, font=font_title)
                draw.text((TEXT_X, y), line, font=font_title, fill=(255, 255, 255, 255))
                y += int(bb[3] - bb[1]) + 8
            y += 24

        # ── 6. Checklist tips ─────────────────────────────────────────────────
        tips = [t for t in [tip_1, tip_2, tip_3, tip_4] if t.strip()]
        for tip in tips:
            dot_cx = TEXT_X + DOT_R
            dot_cy = y + TIP_SIZE // 2 + 4
            draw.ellipse(
                [(dot_cx - DOT_R, dot_cy - DOT_R), (dot_cx + DOT_R, dot_cy + DOT_R)],
                fill=(*accent_rgb, 230),
            )
            tip_x = TEXT_X + DOT_R * 2 + 16
            tip_max_w = TEXT_MAX_W - (tip_x - TEXT_X)
            y = _draw_wrapped(draw, tip, font_tip, tip_x, int(y), (255, 255, 255, 230), tip_max_w, line_gap=4)
            y += 18

        # ── 6b. Venue line (below tips) ───────────────────────────────────────
        if venue and venue.strip():
            y += 4
            venue_dot_r = 6
            venue_dot_cx = TEXT_X + venue_dot_r
            venue_dot_cy = y + VENUE_SIZE // 2 + 2
            draw.ellipse(
                [(venue_dot_cx - venue_dot_r, venue_dot_cy - venue_dot_r),
                 (venue_dot_cx + venue_dot_r, venue_dot_cy + venue_dot_r)],
                fill=(*accent_rgb, 180),
            )
            venue_x = TEXT_X + venue_dot_r * 2 + 12
            venue_max_w = TEXT_MAX_W - (venue_x - TEXT_X)
            y = _draw_wrapped(
                draw, venue.strip(), font_venue, venue_x, int(y),
                (*accent_rgb, 200), venue_max_w, line_gap=4,
            )

        # ── 7. Logos (bottom left) ────────────────────────────────────────────
        logo_y = CANVAS_H - LOGO_Y_FROM_BOTTOM - LOGO_MAX_H
        logo_cursor_x = TEXT_X
        first_logo_placed = False

        for lbytes, lname in [(logo_bytes, "primary logo"), (second_logo_bytes, "second logo")]:
            if lbytes is None:
                continue
            try:
                logo_img = Image.open(io.BytesIO(lbytes)).convert("RGBA")
                scale = min(LOGO_MAX_W / logo_img.width, LOGO_MAX_H / logo_img.height)
                lw = int(logo_img.width * scale)
                lh = int(logo_img.height * scale)
                logo_img = logo_img.resize((lw, lh), Image.Resampling.LANCZOS)
                if first_logo_placed:
                    sep_x = logo_cursor_x + LOGO_GAP // 2
                    draw.line(
                        [(sep_x, logo_y + 10), (sep_x, logo_y + LOGO_MAX_H - 10)],
                        fill=(*accent_rgb, 70), width=2,
                    )
                    logo_cursor_x += LOGO_GAP
                paste_y = logo_y + (LOGO_MAX_H - lh) // 2
                img.paste(logo_img, (logo_cursor_x, paste_y), logo_img)
                logo_cursor_x += lw
                first_logo_placed = True
            except Exception as exc:
                logger.warning("Could not paste %s: %s", lname, exc)

        out = io.BytesIO()
        img.convert("RGB").save(out, format="PNG")
        return out.getvalue()

    return await asyncio.to_thread(_sync_compose)
