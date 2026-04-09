"""Pillow-based slide renderer for P1 real-photo carousels.

Replaces Gemini image editing with programmatic text overlay.
Handles smart cropping, quality enhancement, and text rendering.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import textwrap
from pathlib import Path

import httpx
from PIL import (
    Image,
    ImageDraw,
    ImageEnhance,
    ImageFilter,
    ImageFont,
    ImageStat,
)

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────
TARGET_WIDTH = 1080
TARGET_HEIGHT = 1350
TARGET_RATIO = TARGET_WIDTH / TARGET_HEIGHT  # 0.8 (4:5 portrait)

FONTS_DIR = Path(__file__).resolve().parent.parent.parent / "fonts"
FONT_STYLE_TO_PILLOW: dict[str, str] = {
    "minimalist-sans": "regular",
    "geometric-sans": "bold",
    "editorial-serif": "semibold",
    "bold-display": "condensed",
    "creative-script": "script",
    "friendly-sans": "regular",
    "editorial-mixed": "bold",
    # Legacy short names (already used internally)
    "bold": "bold",
    "regular": "regular",
    "semibold": "semibold",
    "italic": "italic",
    "condensed": "condensed",
    "script": "script",
    "clean": "regular",
    "elegant": "semibold",
}

# ── Font Registry ────────────────────────────────────────────────────
_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def _resolve_font(name: str, size: int) -> ImageFont.FreeTypeFont:
    """Resolve a font by logical name and size, with caching."""
    key = (name, size)
    if key in _font_cache:
        return _font_cache[key]

    font_map = {
        "bold": "Montserrat-Bold.ttf",
        "regular": "Montserrat-Regular.ttf",
        "semibold": "Montserrat-SemiBold.ttf",
        "italic": "Montserrat-BoldItalic.ttf",
        "condensed": "BebasNeue-Regular.ttf",
        "script": "GreatVibes-Regular.ttf",
    }

    filename = font_map.get(name, "Montserrat-Bold.ttf")
    font_path = FONTS_DIR / filename

    try:
        if font_path.exists():
            font = ImageFont.truetype(str(font_path), size)
        else:
            # Fallback to system DejaVu
            for fallback in [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            ]:
                if os.path.exists(fallback):
                    font = ImageFont.truetype(fallback, size)
                    break
            else:
                font = ImageFont.load_default()
                logger.warning("No TTF fonts found, using Pillow default")
    except Exception as e:
        logger.warning("Font load failed for %s: %s", name, e)
        font = ImageFont.load_default()

    _font_cache[key] = font
    return font


# ── Color Helpers ────────────────────────────────────────────────────

def _hex_to_rgba(hex_color: str, alpha: int = 255) -> tuple[int, int, int, int]:
    """Convert hex color string to RGBA tuple."""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 3:
        hex_color = "".join(c * 2 for c in hex_color)
    r, g, b = int(hex_color[:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    return (r, g, b, alpha)


def _is_light(hex_color: str) -> bool:
    """Check if a color is light (luminance > 0.5)."""
    r, g, b, _ = _hex_to_rgba(hex_color)
    luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return luminance > 0.5


# ── Smart Crop ───────────────────────────────────────────────────────

def _smart_crop(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """Smart crop to target aspect ratio, keeping the interesting region.

    Uses edge density heuristics to find the region of interest.
    Falls back to center crop with upward bias for tall images.
    """
    target_ratio = target_w / target_h
    current_ratio = img.width / img.height

    if abs(current_ratio - target_ratio) < 0.01:
        return img.resize((target_w, target_h), Image.LANCZOS)

    if current_ratio > target_ratio:
        # Wider than target — crop sides
        new_width = int(img.height * target_ratio)
        # Try to find subject using edge detection on center strip
        offset = _find_horizontal_interest(img, new_width)
        cropped = img.crop((offset, 0, offset + new_width, img.height))
    else:
        # Taller than target — crop top/bottom
        new_height = int(img.width / target_ratio)
        # Slight upward bias (faces tend to be in upper portion)
        offset = _find_vertical_interest(img, new_height)
        cropped = img.crop((0, offset, img.width, offset + new_height))

    return cropped.resize((target_w, target_h), Image.LANCZOS)


def _find_horizontal_interest(img: Image.Image, crop_width: int) -> int:
    """Find best horizontal crop offset using edge density."""
    excess = img.width - crop_width
    if excess <= 0:
        return 0

    try:
        gray = img.convert("L")
        edges = gray.filter(ImageFilter.FIND_EDGES)

        best_offset = excess // 2  # default: center
        best_score = 0

        # Sample 5 positions
        for i in range(5):
            offset = int(excess * i / 4)
            region = edges.crop((offset, 0, offset + crop_width, img.height))
            score = ImageStat.Stat(region).mean[0]
            if score > best_score:
                best_score = score
                best_offset = offset

        return best_offset
    except Exception:
        return excess // 2


def _find_vertical_interest(img: Image.Image, crop_height: int) -> int:
    """Find best vertical crop offset with upward bias."""
    excess = img.height - crop_height
    if excess <= 0:
        return 0

    try:
        gray = img.convert("L")
        edges = gray.filter(ImageFilter.FIND_EDGES)

        best_offset = int(excess * 0.35)  # slight upward bias default
        best_score = 0

        # Sample 5 positions with upward bias
        for i in range(5):
            offset = int(excess * i / 4)
            region = edges.crop((0, offset, img.width, offset + crop_height))
            score = ImageStat.Stat(region).mean[0]
            # Bias: upper positions get a 10% bonus
            bias = 1.0 + 0.1 * (1.0 - i / 4)
            if score * bias > best_score:
                best_score = score * bias
                best_offset = offset

        return best_offset
    except Exception:
        return int(excess * 0.35)


# ── Quality Enhancement ──────────────────────────────────────────────

def _enhance_quality(img: Image.Image) -> Image.Image:
    """Apply subtle quality enhancements. Returns enhanced copy."""
    try:
        # 1. Unsharp mask for sharpening
        enhanced = img.filter(ImageFilter.UnsharpMask(radius=1.2, percent=110, threshold=3))

        # 2. Auto-contrast (subtle)
        from PIL import ImageOps
        enhanced = ImageOps.autocontrast(enhanced, cutoff=0.5)

        # 3. Brightness: bump if too dark
        stat = ImageStat.Stat(enhanced)
        avg_brightness = sum(stat.mean[:3]) / 3
        if avg_brightness < 85:
            enhancer = ImageEnhance.Brightness(enhanced)
            factor = min(1.15, 100 / max(avg_brightness, 1))
            enhanced = enhancer.enhance(factor)

        # 4. Subtle saturation boost (+8%)
        enhancer = ImageEnhance.Color(enhanced)
        enhanced = enhancer.enhance(1.12)

        return enhanced
    except Exception as e:
        logger.warning("Quality enhancement failed: %s", e)
        return img


# ── Rounded Rectangle ───────────────────────────────────────────────

def _draw_rounded_rect(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int, int, int],
    radius: int,
    fill: tuple[int, int, int, int],
) -> None:
    """Draw a rounded rectangle on an RGBA overlay."""
    x0, y0, x1, y1 = xy
    # Pillow >= 10 has native rounded_rectangle
    if hasattr(draw, "rounded_rectangle"):
        draw.rounded_rectangle(xy, radius=radius, fill=fill)
    else:
        # Manual fallback for older Pillow
        draw.rectangle([x0 + radius, y0, x1 - radius, y1], fill=fill)
        draw.rectangle([x0, y0 + radius, x1, y1 - radius], fill=fill)
        draw.pieslice([x0, y0, x0 + 2 * radius, y0 + 2 * radius], 180, 270, fill=fill)
        draw.pieslice([x1 - 2 * radius, y0, x1, y0 + 2 * radius], 270, 360, fill=fill)
        draw.pieslice([x0, y1 - 2 * radius, x0 + 2 * radius, y1], 90, 180, fill=fill)
        draw.pieslice([x1 - 2 * radius, y1 - 2 * radius, x1, y1], 0, 90, fill=fill)


# ── Text Wrapping ────────────────────────────────────────────────────

def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Word-wrap text to fit within max_width pixels."""
    # Replace dash separators with newlines (same as Gemini prompt logic)
    for sep in (" — ", " – ", " - "):
        text = text.replace(sep, "\n")

    result_lines: list[str] = []
    for paragraph in text.split("\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue

        words = paragraph.split()
        if not words:
            continue

        current_line = words[0]
        for word in words[1:]:
            test_line = current_line + " " + word
            bbox = font.getbbox(test_line)
            line_width = bbox[2] - bbox[0]
            if line_width <= max_width:
                current_line = test_line
            else:
                result_lines.append(current_line)
                current_line = word
        result_lines.append(current_line)

    return result_lines or [text]


def _wrap_text_raw(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Word-wrap text WITHOUT splitting on dash separators (preserves raw text)."""
    result_lines: list[str] = []
    for paragraph in text.split("\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue

        words = paragraph.split()
        if not words:
            continue

        current_line = words[0]
        for word in words[1:]:
            test_line = current_line + " " + word
            bbox = font.getbbox(test_line)
            line_width = bbox[2] - bbox[0]
            if line_width <= max_width:
                current_line = test_line
            else:
                result_lines.append(current_line)
                current_line = word
        result_lines.append(current_line)

    return result_lines or [text]


# ── Hook/Body Split ──────────────────────────────────────────────────

def _split_hook_body(text: str) -> tuple[str, str]:
    """Split text into hook headline and body copy."""
    for sep in [" — ", " – ", " - "]:
        if sep in text:
            parts = text.split(sep, 1)
            return parts[0].strip(), parts[1].strip()
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if len(lines) >= 2:
        return lines[0], " ".join(lines[1:])
    return text.strip(), ""


# ── Main Renderer ────────────────────────────────────────────────────

class SlideRenderer:
    """Renders text overlays on photos for P1 real-photo carousels."""

    def __init__(
        self,
        width: int = TARGET_WIDTH,
        height: int = TARGET_HEIGHT,
        jpeg_quality: int = 95,
    ):
        self.width = width
        self.height = height
        self.jpeg_quality = jpeg_quality

    async def download_image(self, url: str, retries: int = 2) -> bytes | None:
        """Download image from URL with retry. Returns raw bytes or None on failure."""
        for attempt in range(retries + 1):
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.get(url, follow_redirects=True)
                    resp.raise_for_status()
                    return resp.content
            except Exception as e:
                if attempt == retries:
                    logger.error('Photo download failed after %d attempts: %s', retries + 1, e)
                    return None
                await asyncio.sleep(2 ** attempt)

    def render_slide(
        self,
        image_bytes: bytes,
        text: str,
        position: str = "Bottom Center",
        font_style: str = "bold",
        color_primary: str = "#000000",
        color_secondary: str = "#FFFFFF",
        color_background: str | None = None,
        enhance_quality: bool = True,
        slide_index: int = 0,
        font_style_secondary: str | None = None,
    ) -> bytes:
        """Render a complete slide: crop + enhance + text overlay.

        Parameters
        ----------
        image_bytes : raw image bytes (JPEG, PNG, HEIC, etc.)
        text : text to overlay on the image
        position : "Top Center", "Center", or "Bottom Center"
        font_style : "bold", "editorial-mixed", "clean", "elegant"
        color_primary : hex color for primary text
        color_secondary : hex color for secondary text / accents
        color_background : hex color for text box background (auto if None)
        enhance_quality : whether to apply quality enhancements
        slide_index : index of this slide (0-based) for rotating layout templates

        Returns
        -------
        JPEG bytes at target resolution.
        """
        # 1. Open image
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode == "RGBA":
            # Flatten RGBA to RGB on white background
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[3])
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")

        # 2. Smart crop to target dimensions
        img = _smart_crop(img, self.width, self.height)

        # 3. Quality enhancement
        if enhance_quality:
            img = _enhance_quality(img)

        # 4. Text overlay
        img = self._render_text_overlay(
            img, text, position, font_style,
            color_primary, color_secondary, color_background,
            slide_index=slide_index,
            font_style_secondary=font_style_secondary,
        )

        # 5. Export as JPEG
        output = io.BytesIO()
        img.save(output, format="JPEG", quality=self.jpeg_quality, optimize=True)
        return output.getvalue()

    def _select_layout_mode(self, font_style: str) -> str:
        """Deterministically select layout mode based on brand font_style.

        condensed (Bebas Neue) and script (Great Vibes) use editorial-mixed
        (alternating bold/script lines). All others use single-style layout.
        """
        pillow_name = FONT_STYLE_TO_PILLOW.get(font_style, "bold")
        if pillow_name in ("condensed", "script"):
            return "editorial-mixed"
        return "single"

    def _render_text_overlay(
        self,
        img: Image.Image,
        text: str,
        position: str,
        font_style: str,
        color_primary: str,
        color_secondary: str,
        color_background: str | None,
        slide_index: int = 0,
        font_style_secondary: str | None = None,
    ) -> Image.Image:
        """Render text box overlay on top of the image."""
        # Create RGBA overlay for semi-transparent box
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        # ── Box dimensions ───────────────────────────────────────
        box_width = int(self.width * 0.82)
        box_x = (self.width - box_width) // 2
        pad_h = 28  # horizontal padding
        pad_v = 22  # vertical padding
        text_area_width = box_width - 2 * pad_h
        line_spacing = 8

        # ── Determine box background color ───────────────────────
        if color_background:
            effective_bg = color_background
        elif _is_light(color_secondary):
            effective_bg = color_secondary
        else:
            effective_bg = "#FFFDF5"

        box_fill = _hex_to_rgba(effective_bg, alpha=int(255 * 0.88))

        # ── Prepare text lines and measure ───────────────────────
        accent_color: str | None = None

        layout_mode = self._select_layout_mode(font_style)

        if layout_mode == "editorial-mixed":
            lines, line_fonts, line_colors, total_height = self._prepare_editorial_mixed(
                text, text_area_width, color_primary, color_secondary,
            )
            layout = None
        else:
            lines, line_fonts, line_colors, total_height, accent_color = self._prepare_dynamic_layout(
                *_split_hook_body(text),
                max_width=text_area_width,
                color_primary=color_primary,
                color_secondary=color_secondary,
                font_style=font_style,
            )
            layout = "top_accent"  # always top accent bar, no rotation

        if not lines:
            return img

        # ── Box height ───────────────────────────────────────────
        box_height = total_height + 2 * pad_v

        # ── Box Y position ───────────────────────────────────────
        position_lower = position.lower().replace("_", " ").strip()
        if "top" in position_lower:
            box_y = int(self.height * 0.08)
        elif "center" in position_lower and "top" not in position_lower and "bottom" not in position_lower:
            box_y = (self.height - box_height) // 2
        else:  # bottom center (default)
            box_y = int(self.height * 0.70) - box_height
            # Never below 75% height
            max_y = int(self.height * 0.75) - box_height
            box_y = min(box_y, max_y)
            # Never too high either
            box_y = max(box_y, int(self.height * 0.50))

        box_x1 = box_x + box_width
        box_y1 = box_y + box_height

        # ── Draw rounded rect ────────────────────────────────────
        # Box shadow (4px offset, ~24% opacity) -- overlay is RGBA
        shadow_box = (box_x + 4, box_y + 4, box_x1 + 4, box_y1 + 4)
        shadow_fill = (0, 0, 0, 60)
        _draw_rounded_rect(draw, shadow_box, radius=12, fill=shadow_fill)
        # Actual box on top
        _draw_rounded_rect(
            draw,
            (box_x, box_y, box_x1, box_y1),
            radius=12,
            fill=box_fill,
        )

        # ── Draw accent bar ──────────────────────────────────────
        if accent_color is not None:
            accent_fill = _hex_to_rgba(accent_color, alpha=230)
            draw.rectangle([box_x, box_y, box_x + box_width, box_y + 4], fill=accent_fill)

        # ── Draw text lines ──────────────────────────────────────
        hook_body_gap = 14
        current_y = box_y + pad_v
        prev_font = None
        for i, (line, font, color_hex) in enumerate(zip(lines, line_fonts, line_colors)):
            bbox = font.getbbox(line)
            line_w = bbox[2] - bbox[0]
            line_h = bbox[3] - bbox[1]
            text_x = box_x + (box_width - line_w) // 2
            text_color = _hex_to_rgba(color_hex)[:3]
            # Shadow pass (1px offset, ~20% opacity) — overlay is RGBA
            draw.text((text_x + 1, current_y + 1), line, font=font, fill=text_color + (51,))
            # Actual text
            draw.text((text_x, current_y), line, font=font, fill=text_color + (255,))
            # Add hook→body gap when font switches from hook to body
            if prev_font is not None and font is not prev_font and i > 0:
                current_y += hook_body_gap
            current_y += line_h + line_spacing
            prev_font = font

        # Composite overlay onto image
        img_rgba = img.convert("RGBA")
        composited = Image.alpha_composite(img_rgba, overlay)
        return composited.convert("RGB")

    def _get_hook_flags(
        self,
        lines: list[str],
        fonts: list[ImageFont.FreeTypeFont],
        colors: list[str],
    ) -> list[bool]:
        """Return a bool list: True = hook line, False = body line.

        Heuristic: hook lines use the first unique font; once we see a
        different font, that's the body section.
        """
        if not fonts:
            return []
        hook_font = fonts[0]
        flags = []
        in_body = False
        for f in fonts:
            if not in_body and f != hook_font:
                in_body = True
            flags.append(not in_body)
        return flags

    def _prepare_dynamic_layout(
        self,
        hook: str,
        body: str,
        max_width: int,
        color_primary: str,
        color_secondary: str,
        font_style: str = "bold",
        font_style_secondary: str | None = None,  # kept for compat, ignored
    ) -> tuple[list[str], list[ImageFont.FreeTypeFont], list[str], int, str]:
        """Prepare lines using a single layout derived from the brand font_style.

        Returns (lines, fonts, colors, total_height, accent_color).
        """
        # Map brand font_style key to Pillow font name
        primary_pillow = FONT_STYLE_TO_PILLOW.get(font_style, "bold")
        is_condensed = primary_pillow == "condensed"

        hook_size = 62 if is_condensed else 48
        body_size = 34 if is_condensed else 30

        hook_font = _resolve_font(primary_pillow, hook_size)
        body_font = _resolve_font(primary_pillow, body_size)

        # Uppercase for Bebas Neue (display font), title case for others
        hook_display = hook.upper() if is_condensed else hook

        # ALWAYS color_primary for text — NEVER invert to color_secondary (could be white)
        hook_color = color_primary
        body_color = color_primary  # same color, smaller size provides hierarchy

        # Accent bar always color_secondary (used for the box accent line, not text)
        accent_color = color_secondary

        line_spacing = 8
        hook_body_gap = 14

        # Build lines list
        lines: list[str] = []
        fonts: list[ImageFont.FreeTypeFont] = []
        colors: list[str] = []
        total_height = 0

        hook_lines = _wrap_text_raw(hook_display, hook_font, max_width)
        for line in hook_lines:
            lines.append(line)
            fonts.append(hook_font)
            colors.append(hook_color)
            bbox = hook_font.getbbox(line)
            total_height += bbox[3] - bbox[1] + line_spacing

        if body:
            total_height += hook_body_gap
            body_display = body.upper() if is_condensed else body
            body_lines = _wrap_text_raw(body_display, body_font, max_width)
            for line in body_lines:
                lines.append(line)
                fonts.append(body_font)
                colors.append(body_color)
                bbox = body_font.getbbox(line)
                total_height += bbox[3] - bbox[1] + line_spacing

        return lines, fonts, colors, total_height, accent_color

    def _prepare_editorial_mixed(
        self,
        text: str,
        max_width: int,
        color_primary: str,
        color_secondary: str,
    ) -> tuple[list[str], list[ImageFont.FreeTypeFont], list[str], int]:
        """Prepare lines for editorial-mixed style (alternating bold/script)."""
        bold_font = _resolve_font("condensed", 48)  # Bebas Neue
        script_font = _resolve_font("script", 44)   # Great Vibes

        # Wrap text
        all_lines = _wrap_text(text, bold_font, max_width)

        lines: list[str] = []
        fonts: list[ImageFont.FreeTypeFont] = []
        colors: list[str] = []
        total_height = 0

        for i, line in enumerate(all_lines):
            if i % 2 == 0:
                # Odd lines (1st, 3rd...) -> bold condensed, uppercase, primary
                display_line = line.upper()
                font = bold_font
                color = color_primary
            else:
                # Even lines (2nd, 4th...) -> script, normal case, secondary
                display_line = line
                font = script_font
                color = color_secondary

            lines.append(display_line)
            fonts.append(font)
            colors.append(color)

            bbox = font.getbbox(display_line)
            total_height += bbox[3] - bbox[1] + 6  # +6 line spacing

        return lines, fonts, colors, total_height

    def _prepare_single_style(
        self,
        text: str,
        max_width: int,
        font_style: str,
        color_primary: str,
    ) -> tuple[list[str], list[ImageFont.FreeTypeFont], list[str], int]:
        """Prepare lines for a single font style."""
        style_font_map = {
            "bold": ("bold", 42),
            "clean": ("regular", 40),
            "elegant": ("semibold", 40),
        }
        font_name, font_size = style_font_map.get(font_style, ("bold", 42))
        font = _resolve_font(font_name, font_size)

        all_lines = _wrap_text(text, font, max_width)

        total_height = 0
        for line in all_lines:
            bbox = font.getbbox(line)
            total_height += bbox[3] - bbox[1] + 6

        colors = [color_primary] * len(all_lines)
        fonts = [font] * len(all_lines)

        return all_lines, fonts, colors, total_height
