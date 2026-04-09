"""
Gemini prompts for carousel slide generation.
Ported from pelvi-ai-hub/api/_lib/carousel-prompts.ts
"""
from app.utils.color_utils import ensure_contrast, is_light


def build_generate_slide_prompt(
    position: str,
    text: str,
    font_prompt: str,
    font_style: str,
    font_size: str,
    color_primary: str,
    color_secondary: str,
    color_background: str | None = None,
    brand_playbook: str = "",
    font_prompt_secondary: str = "",
    visual_environment_setup: str = "",
    visual_subject_outfit_face: str = "",
    visual_subject_outfit_generic: str = "",
) -> str:
    effective_bg = color_background or (color_secondary if is_light(color_secondary) else '#FFFDF5')
    
    if font_style == 'editorial-mixed':
        validated_bold = ensure_contrast(color_primary, effective_bg, 4.5)
        validated_script = ensure_contrast(color_secondary, effective_bg, 3.0)
        typography = f"""SIGNATURE MIXED TYPOGRAPHY — NON-NEGOTIABLE (this is the brand visual identity):

STEP 1 — Convert text to Sentence case: If the text is in ALL CAPS, convert every word to normal sentence case before rendering. Example: "DOWNLOAD THE APP TODAY" → "Download the app today".

STEP 2 — Split the text into exactly TWO parts at a natural semantic boundary:
- Find the most natural break point: a period, comma, "and", "but", "so", or the midpoint of a long sentence
- PART A (first half / hook / main statement)
- PART B (second half / twist / supporting thought)
- Example: "Download the app today and start exploring businesses" → Part A: "Download the app today" / Part B: "and start exploring businesses"

STEP 3 — Render the two parts with DIFFERENT FONTS:
- PART A: Clean bold sans-serif (Poppins Bold / Montserrat Bold style) — weight 700, NOT condensed, sentence case, color: {validated_bold}, size: {font_size}
- PART B: Elegant italic cursive script (Great Vibes / Playlist Script / Alex Brush style) — flowing, handwritten feel, sentence case, color: {validated_script}, slightly larger than Part A for visual rhythm

RULES:
- Both parts centered horizontally within the text box
- The two fonts must be VISUALLY VERY DIFFERENT — one solid/geometric, the other flowing/handwritten
- DO NOT use Bebas Neue, Impact, or condensed uppercase fonts
- BOTH brand colors must appear: Part A in primary ({validated_bold}), Part B in secondary ({validated_script})
- NEVER render both parts in the same font style — that is a quality failure"""
    else:
        validated_text = ensure_contrast(color_primary, effective_bg, 4.5)
        validated_accent = ensure_contrast(color_secondary, effective_bg, 3.0)
        typography = f"""- Font: {font_prompt}
- Style: {font_style}
- Size: {font_size} (scale down proportionally if text is long)
- Text color: {validated_text}
- Accent detail (thin decorative border or subtitle highlight): {validated_accent}
- IMPORTANT: Both brand colors must be visually present on the slide
- Secondary / body emphasis font: {font_prompt_secondary}"""

    playbook_block = f"""
BRAND PLAYBOOK:
{brand_playbook}

Use the playbook to keep the slide's tone, wording hierarchy, and CTA-style consistent with the same publication.
Do not invent a random style or conversion tone that conflicts with the playbook.
""" if brand_playbook else ""

    visual_reference_block = ""
    visual_lines = []
    if visual_environment_setup:
        visual_lines.append(f"- Setting & background: {visual_environment_setup}")
    if visual_subject_outfit_face:
        visual_lines.append(f"- Subject outfit (client face): {visual_subject_outfit_face}")
    if visual_subject_outfit_generic:
        visual_lines.append(f"- Subject outfit (generic/stock): {visual_subject_outfit_generic}")
    if visual_lines:
        visual_reference_block = """
VISUAL STYLE REFERENCES:
{lines}

Use these as the primary visual reference for the image generation. The scene, wardrobe, and lighting should feel consistent with this publication.
Do not replace them with random wardrobe or unrelated backgrounds.
""".format(lines="\n".join(visual_lines))

    return f"""You are an Expert Editorial Graphic Designer. You receive a REAL PHOTOGRAPH and must produce a finished carousel slide.

RULE 1 — PHOTO PRESERVATION:
The original photograph MUST remain IDENTICAL. Do NOT regenerate, recreate, reinterpret, move, crop, filter, color-grade, or alter ANY part of the photo. Every face, body, background, color, and detail stays exactly as-is. Only upscale/fit to 1080x1350.

RULE 2 — ALWAYS ADD TEXT:
Every single slide MUST have the text overlay. Never return a slide without text. If something fails, still add the text.

RULE 3 — TEXT GOES ON TOP OF THE IMAGE:
The text box is ALWAYS rendered ON TOP of the photograph, overlaying it. The text NEVER goes below the image, beside it, or in a separate area. It floats over the photo.

TASK:
1. Fit the photo into a 1080x1350 canvas (4:5 portrait). Preserve aspect ratio. Fill empty edges with content-aware color matching.
2. Enhance quality slightly — sharpen, improve clarity. Do NOT change colors or lighting.
3. Place a text overlay card ON TOP of the photo at the specified position.

{playbook_block}

{visual_reference_block}

TEXT OVERLAY SPECS:

Position: {position}
- 'Top Center': Text box centered horizontally in the upper 25% of the image
- 'Center': Text box centered horizontally AND vertically (dead center of image)
- 'Bottom Center': Text box centered horizontally in the lower third, bottom edge NEVER below 75% of image height (bottom 25% reserved for logo)

Text box design:
- Clean rectangular box with rounded corners (radius ~12px)
- Background: {effective_bg} with 90% opacity
- Padding: 20px horizontal, 14px vertical
- Width: 80% of image width, centered

Text content (convert ALL-CAPS to Sentence case before rendering):
"{text}"

TEXT FORMATTING: If the text contains hyphens (-), em dashes (—), or en dashes (–) used as separators between ideas, replace them with a line break. Each line should be a clean thought without dash separators.

Typography:
{typography}
- Alignment: Centered

Output: exactly 1080x1350px, photo unchanged underneath, text overlay on top."""
