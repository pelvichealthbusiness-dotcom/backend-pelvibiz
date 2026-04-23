"""
Gemini prompts for fixing individual carousel slides.
Ported from pelvi-ai-hub/api/_lib/carousel-prompts.ts
"""
from app.utils.color_utils import ensure_contrast, is_light


def build_fix_slide_prompt(
    new_text_content: str | None = None,
    font_prompt: str = "Clean, bold, geometric sans-serif",
    font_style: str = "bold",
    color_primary: str = "#000000",
    color_secondary: str | None = None,
    color_background: str | None = None,
    topic: str = "",
    text_position: str | None = None,
) -> str:
    if new_text_content:
        text_rule = f"REPLACE the text with EXACTLY this text: {new_text_content}"
    else:
        text_rule = "KEEP the EXACT same text already visible on this image. Read it and render it back IDENTICALLY."

    topic_block = ""
    if topic:
        topic_block = f"""
CAROUSEL TOPIC: {topic}
The text on this slide must be relevant to this topic. If generating new text, it MUST relate to: {topic}
"""

    effective_bg = color_background or (color_secondary if color_secondary and is_light(color_secondary) else '#FFFDF5')

    if font_style == 'editorial-mixed':
        color_accent = color_secondary or '#C9A84C'
        validated_bold = ensure_contrast(color_primary, effective_bg, 4.5)
        validated_script = ensure_contrast(color_accent, effective_bg, 3.0)
        typography_block = f"""MIXED TYPOGRAPHY — alternating line styles:
- Odd-numbered lines: ultra-bold condensed sans-serif (Bebas Neue / Impact), color: {validated_bold}, uppercase
- Even-numbered lines: flowing cursive script (Playlist Script / Great Vibes), color: {validated_script}, normal case
- Both types centered horizontally"""
    else:
        validated_text = ensure_contrast(color_primary, effective_bg, 4.5)
        typography_block = f"""- Font: {font_prompt}
- Style: {font_style}
- Weight: Bold 700
- Color: {validated_text}"""

    pos_lower = (text_position or "").lower()
    if "top" in pos_lower:
        position_rule = "PLACE the text box at the TOP of the image — vertically centered in the top 25% of the canvas."
    elif pos_lower in ("center", "centre", "middle"):
        position_rule = "PLACE the text box at the CENTER of the image — vertically centered on the canvas."
    else:
        position_rule = "PLACE the text box near the BOTTOM of the image — in the lower 30% of the canvas."

    return f"""You are fixing a single slide from an existing carousel. Output: 1080x1350 portrait (4:5).
{topic_block}
RULE: The original photograph MUST remain IDENTICAL. Do NOT regenerate, move, crop, filter, or alter ANY part of the photo. Only upscale/fit to canvas and overlay text.
IMPORTANT: If the input image already contains a text overlay, REMOVE IT completely before placing the new text box. The final slide must have exactly ONE text box.

TEXT RULES: {text_rule}

Text box: {effective_bg} rectangular box with ROUNDED CORNERS (radius 15px), 80 percent width, centered.
{position_rule} Bottom 120px reserved for logo.

Typography:
{typography_block}
- Alignment: Centered, Sentence case

TEXT FORMATTING: If the text contains hyphens (-), em dashes (—), or en dashes (–) used as separators between ideas, replace them with a line break. Each line should be a clean thought without dash separators.

EVERY slide MUST have the text overlay. Never return without text."""
