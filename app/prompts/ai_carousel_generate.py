"""
Gemini prompts for P2 AI Carousel image generation.
Unlike P1 (text overlay on photos), P2 generates ENTIRE images from AI.
"""

import random
from app.utils.color_utils import ensure_contrast, is_light

# -- Composition & lighting variety to prevent repetitive stock-photo look --

COMPOSITION_VARIATIONS = [
    "Shot from a slightly low angle, looking up",
    "Shot from above, bird's-eye perspective",
    "Close-up framing, intimate perspective",
    "Wide shot, showing the full environment",
    "Medium shot, waist-up framing",
    "Shot from the side, profile perspective",
    "Shot with shallow depth of field, blurred background",
    "Shot with leading lines drawing the eye to the subject",
]

LIGHTING_VARIATIONS = [
    "Golden hour warm lighting",
    "Soft natural window light",
    "Dramatic side lighting with shadows",
    "Bright, even studio lighting",
    "Cool blue-hour twilight lighting",
    "Warm candlelit ambiance",
]

# -- Card background patterns for visual variety --

CARD_PATTERNS = [
    "subtle diagonal lines at 15-degree angle",
    "soft concentric circles radiating from bottom-right corner",
    "minimal dot grid pattern with 40px spacing",
    "gentle wave curves flowing horizontally",
    "abstract geometric triangles in the corners",
    "subtle halftone gradient from one corner",
    "thin parallel horizontal lines with varying opacity",
    "soft bokeh-like circles scattered sparsely",
]

# -- Card layout variations --

CARD_LAYOUTS = [
    {"align": "left-aligned", "hook_pos": "upper-left area", "body_pos": "below the hook, left-aligned"},
    {"align": "centered", "hook_pos": "upper-center area", "body_pos": "below the hook, centered"},
    {"align": "right-aligned", "hook_pos": "upper-right area", "body_pos": "below the hook, right-aligned"},
    {"align": "centered", "hook_pos": "center of the card", "body_pos": "below the hook, centered"},
]


BRAND_VOICE_VISUAL_MOOD = {
    "profesional": "Clean lines, crisp composition, trustworthy corporate aesthetic. Minimal clutter.",
    "empático": "Warm soft lighting. Human connection visible. Welcoming body language.",
    "educativo": "Clear informative layout. Light academic tone. Easy to follow.",
    "inspirador": "Uplifting brightness. Open spaces. Strong natural light. Hope-driven color.",
    "clínico": "Medical-grade precision. White neutral tones. Hygienic aesthetics.",
    "cercano": "Candid authentic moments. Natural lifestyle photography. Unposed feel.",
    "luxury": "Premium materials, muted palette, sophisticated composition.",
    "professional": "Clean lines, crisp composition, trustworthy corporate aesthetic.",
    "empathetic": "Warm soft lighting. Human connection. Welcoming.",
    "educational": "Clear informative layout. Academic tone.",
    "inspiring": "Uplifting. Open spaces. Natural light.",
    "clinical": "Medical precision. White neutral tones.",
    "friendly": "Candid authentic moments. Natural feel.",
}

# -- Shared anti-effect and canvas rules --

ANTI_EFFECT_RULES = """CRITICAL ANTI-EFFECT RULES — NEVER VIOLATE:
- EVERY letter in a word MUST have the EXACT SAME font weight — NO per-letter weight variation
- NO glow, shine, blur, or shadow effects on any letter
- NO gradient fills on individual letters or words
- NO "kinetic typography" or "variable font" effects
- The typography must look like clean, flat, printed text — NOT an artistic/special effect
- If you add ANY per-letter graphic effect, this slide FAILS quality check"""

CANVAS_RULES = """CANVAS RULES — CRITICAL, NEVER VIOLATE:
- Fill the ENTIRE 1080x1350 canvas — NO white borders, NO white padding, NO empty margins at any edge
- The background must be CONTINUOUS from top to bottom — NO footer band, NO header band, NO color change near any edge
- The bottom edge must look EXACTLY like the middle of the image — same texture, same background, NO separate band or border
- NO slide counters, progress dots, or page numbers embedded in the image
- SINGLE UNIFIED SCENE ONLY — do NOT split the canvas into two halves, panels, or sections side by side
- NO split-screen, diptych, collage, mosaic, or multi-photo composite layouts — ONE single cohesive image
- Do NOT place two different photos or scenes side by side — the entire canvas is ONE photograph or ONE scene
- NO decorative UI chrome (app bars, bottom navigation, cards, rounded-rectangle overlays that look like app UI)
- NO gray or colored footer bar at the bottom — the bottom of the image is NOT a UI element
- If this rule is violated (footer bar, split image, counter visible), the image FAILS quality check and must be rejected"""


def _split_hook_body(text: str) -> tuple[str, str]:
    """Split text into HOOK (first sentence/line) and BODY (rest).

    Returns (hook, body). If text is a single sentence, hook = text, body = "".
    """
    # Try splitting by newline first
    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
    if len(lines) >= 2:
        return lines[0], "\n".join(lines[1:])

    # Try splitting by first sentence (period, ! or ?)
    for i, ch in enumerate(text):
        if ch in ".!?" and i > 10 and i < len(text) - 5:
            return text[: i + 1].strip(), text[i + 1 :].strip()

    # Can't split — entire text is the hook
    return text.strip(), ""


def _build_editorial_mixed_typography(
    color_primary: str,
    color_secondary: str,
    effective_bg: str,
    font_size: str,
) -> str:
    """Build the editorial-mixed typography block for AI-generated slides."""
    validated_bold = ensure_contrast(color_primary, effective_bg, 4.5)
    validated_script = ensure_contrast(color_secondary, effective_bg, 3.0)
    return f"""SIGNATURE MIXED TYPOGRAPHY — NON-NEGOTIABLE (this is the brand's visual identity):
- Line 1 (statement / hook): Clean bold sans-serif — weight 700-800, NOT condensed, NOT all-caps (sentence case), color {validated_bold}, size {font_size}
- Line 2 (twist / counterpoint): Elegant italic script — flowing cursive (Great Vibes / Playlist Script / Alex Brush style), sentence case, color {validated_script}, slightly larger than line 1 for visual balance
- If 3+ lines: continue alternating bold-sans / italic-script
- Both lines centered horizontally
- The two styles must be visually distinct: one is solid/geometric, the other is flowing/handwritten
- BOTH brand colors must appear — bold line in primary color, script line in secondary color

WHAT NOT TO DO:
- All lines in the same font style → WRONG
- Bebas Neue or Impact (all-caps condensed fonts) → WRONG — use clean bold sans, sentence case
- All lines same color → WRONG
- Script that looks too similar to sans-serif → WRONG, must be clearly cursive/handwritten"""



def build_per_slide_context(
    slide_topic: str,
    visual_prompt: str,
    brand_environment: str,
    brand_voice: str,
    slide_index: int,
    total_slides: int,
    slide_type: str,
    keywords: str = "",
    content_style: str = "",
    brand_playbook: str = "",
    font_prompt_secondary: str = "",
    visual_subject_outfit_face: str = "",
    visual_subject_outfit_generic: str = "",
    story_context: str = "",
) -> str:
    """Build a rich per-slide visual context for Gemini image generation.

    Combines slide topic, brand environment, and position context into
    a specific visual direction that produces on-brand, topic-relevant images.
    """
    parts: list[str] = []

    # 0. PRIMARY VISUAL DIRECTIVE — evoke concept, don't force literal elements
    parts.insert(0,
        f'VISUAL CONCEPT: The image should visually EVOKE and complement this idea: "{slide_topic}". '
        f'Choose a scene that feels connected to this concept — it does NOT need to show it literally. '
        f'A powerful, coherent, photorealistic scene is more important than forced literal representation. '
        f'Avoid compositing subjects onto mismatched backgrounds — generate ONE unified natural scene.'
    )
    # 1. Slide-specific visual direction
    if visual_prompt and len(visual_prompt.strip()) > 20:
        parts.append(visual_prompt.strip())

    # 2. Brand environment (lighting, setting, location)
    if brand_environment and brand_environment.strip():
        parts.append(f"Setting and environment: {brand_environment.strip()}")

    # 3. Slide position context
    if slide_index == 0:
        parts.append(
            "This is the OPENING HOOK slide — high visual impact, "
            "attention-grabbing composition, strong focal point."
        )
    elif slide_index == total_slides - 1:
        parts.append(
            "This is the CLOSING CTA slide — warm, inviting, "
            "emotionally resonant, action-oriented composition."
        )
    else:
        parts.append(
            f"Supporting informational slide {slide_index + 1} of {total_slides} — "
            "clear, professional, balanced composition."
        )

    # 4. Card slides: abstract background, no subjects
    if slide_type == "card":
        parts.append(
            "Abstract background only — NO human subjects. "
            "Soft bokeh, elegant texture, brand-palette colors dominate. "
            "Clean composition suitable for text overlay."
        )

    # 5. Brand voice → visual mood
    voice_mood = BRAND_VOICE_VISUAL_MOOD.get(brand_voice.lower().strip(), "") if brand_voice else ""
    if voice_mood:
        parts.append(f"Visual mood and aesthetic: {voice_mood}")

    # 6. Keywords
    if keywords:
        parts.append(f"Brand keywords to reinforce visually: {keywords}")

    # 7. Content style
    if content_style:
        parts.append(f"Visual style should feel: {content_style}")

    if font_prompt_secondary:
        parts.append(f"Secondary/body emphasis font: {font_prompt_secondary}")

    if brand_playbook:
        parts.append(f"Brand playbook / CTA rules: {brand_playbook}")

    if visual_subject_outfit_face:
        parts.append(f"Outfit when client face is attached: {visual_subject_outfit_face}")

    if visual_subject_outfit_generic:
        parts.append(f"Outfit for generic/stock model: {visual_subject_outfit_generic}")

    # 8. Story context (hook and closing slides only)
    if story_context and slide_index == 0:
        parts.append(f"Narrative inspiration for this hook: {story_context[:200]}")

    return " ".join(parts)

def build_generic_slide_prompt(
    visual_prompt: str,
    text: str,
    text_position: str,
    font_prompt: str,
    font_style: str,
    font_size: str,
    color_primary: str,
    color_secondary: str,
    subject_description: str = "",
    color_background: str = None,
    slide_index: int = 0,
    is_face_mode: bool = False,
    font_prompt_secondary: str | None = None,
) -> str:
    composition = random.choice(COMPOSITION_VARIATIONS)
    lighting = random.choice(LIGHTING_VARIATIONS)

    subject_block = (
        f"\nSUBJECT/MODEL DESCRIPTION (use if the scene includes a person):\n{subject_description}\n"
        if subject_description else ""
    )

    face_block = ""
    if is_face_mode:
        face_block = (
            "\nFACE REFERENCE (MANDATORY):\n"
            "A reference photo of the person is attached as an inline image. "
            "You MUST include this EXACT person in the generated scene — same face, same features, same skin tone. "
            "The person should be naturally integrated into the scene described above. "
            "Do NOT change their face or features. The reference photo is for likeness only — "
            "you may change their clothing, pose, and surroundings to match the scene.\n"
        )

    # Determine effective text box background
    effective_bg = color_background or (color_secondary if is_light(color_secondary) else "#FFFDF5")

    # Split text into hook and body for better visual hierarchy
    hook_text, body_text = _split_hook_body(text)

    # Build typography block based on font_style and whether body exists
    if body_text:
        # Two-part slide: hook + body
        if font_style == "editorial-mixed":
            # Generic slides are never dark-card alternating — always use primary for bold
            is_dark_card = False
            # Dark card: primary IS the bg — use secondary as bold, white as script
            # Light card: use primary as bold, secondary as script
            em_bold = color_secondary if is_dark_card else color_primary
            em_script = "#FFFFFF" if is_dark_card else color_secondary
            typography_block = _build_editorial_mixed_typography(
                em_bold, em_script, effective_bg, font_size,
            )
            text_display = f"""=== GLOBAL TYPOGRAPHY RULE (APPLIES TO ALL SLIDES) ===
- EVERY slide in this carousel MUST use EXACTLY the same font family: {font_prompt}
- EVERY slide MUST follow the same font style: {font_style}
- Do NOT change fonts between slides - use identical font for ALL slides
- This is MANDATORY for brand consistency

TEXT TO RENDER (already split for you):
HOOK LINE: "{hook_text}"
BODY TEXT: "{body_text}"

{typography_block}

{ANTI_EFFECT_RULES}

{CANVAS_RULES}"""
        else:
            validated_text = ensure_contrast(color_primary, effective_bg, 4.5)
            validated_accent = ensure_contrast(color_secondary, effective_bg, 3.0)
            secondary_font_rule_generic = ""
            if font_prompt_secondary and body_text:
                secondary_font_rule_generic = f"\n- BODY text specifically: {font_prompt_secondary} — DIFFERENT style from hook"

            text_display = f"""=== GLOBAL TYPOGRAPHY RULE (APPLIES TO ALL SLIDES) ===
- EVERY slide in this carousel MUST use EXACTLY the same font family: {font_prompt}
- EVERY slide MUST follow the same font style: {font_style}
- Do NOT change fonts between slides - use identical font for ALL slides
- This is MANDATORY for brand consistency

TEXT TO RENDER (already split for you):
HOOK LINE: "{hook_text}"
BODY TEXT: "{body_text}"

MANDATORY TYPOGRAPHY RULES (CRITICAL - NEVER IGNORE):
- USE ONLY the font specified in font_prompt — do NOT use any other font family
            - The font style must be: {font_style} — use that exact weight/style
- Never mix different font families — ONE font family only
- If you cannot find the exact font, use a similar bold sans-serif
- HOOK: {font_prompt}, extra-bold weight (800+), LARGE size ({font_size} or bigger), UPPERCASE, color {validated_accent}
- BODY: {font_prompt}, regular/light weight (400), smaller size (28-32px), normal case (Sentence case), color {validated_text}{secondary_font_rule_generic}
- These MUST look visually DIFFERENT — different weight, different size, different case, different color
- Add a thin accent divider line between hook and body: thin horizontal line in {validated_accent}, ~60% width
- Accent detail (thin decorative border or subtitle highlight): {validated_accent}
- IMPORTANT: Both brand colors ({color_primary} and {color_secondary}) must be visually present on the slide

MANDATORY COLOR RULES:
- The HOOK text MUST be rendered in {validated_accent} — this is NOT optional
- The BODY text MUST be rendered in {validated_text} — a DIFFERENT color from the hook
- The accent divider line MUST use {validated_accent}
- If ALL text appears in the same color, this slide FAILS quality check

WHAT NOT TO DO:
- All text same size -> WRONG
- All text same color -> WRONG
- All text same font weight -> WRONG
- No divider between hook and body -> WRONG
- Hook and body look identical -> WRONG

{ANTI_EFFECT_RULES}

{CANVAS_RULES}"""
    else:
        # Single-line slide: hook only
        validated_accent = ensure_contrast(color_secondary, effective_bg, 3.0)
        text_display = f"""TEXT TO RENDER — SINGLE LINE:
"{hook_text}"

This is a SINGLE-LINE slide. Render ONLY the hook text, centered, in large bold display. NO body text. NO second text block.

SINGLE-LINE TYPOGRAPHY RULES:
- Font: {font_prompt}, extra-bold weight (800+), size {font_size} or LARGER, UPPERCASE
- Color: {validated_accent}
- Centered both horizontally and vertically within the text box
- NO divider line (there is no body to separate from)

{ANTI_EFFECT_RULES}

{CANVAS_RULES}"""

    return f"""NO FOOTER WATERMARK: Do NOT reserve space for any logo footer or watermark. The image should use the full canvas naturally from top to bottom, with no blank footer band, no bottom-center logo area, and no decorative strip reserved for post-processing.

Generate a professional Instagram carousel slide image.

SCENE DESCRIPTION:
{visual_prompt}
{subject_block}{face_block}
COMPOSITION: {composition}
LIGHTING MOOD: {lighting}
IMPORTANT: Make this image UNIQUE — vary the angle, composition, and mood from typical stock photos.

IMAGE SPECS:
- Resolution: exactly 1080x1350 pixels (4:5 portrait)
- Style: Photorealistic, high quality, professional
- The image must look like a real photograph, not AI-generated

SCENE CONTENT REQUIREMENT:
The scene must visually represent the text: "{text}"
Extract the KEY SUBJECTS from that text and make sure they appear in the image:
- People or groups mentioned → must be visible in the scene
- Locations or settings mentioned → must be the backdrop
- Actions or processes mentioned → must be happening
- Objects or tools mentioned → must be present
This is NOT optional. A generic scenic background is NOT acceptable if the text describes specific subjects.

TEXT OVERLAY (MANDATORY — every slide MUST have text):
Add a text overlay card ON TOP of the generated scene.

Position: {text_position}
- 'Top Center': Text box in upper 25% of image, centered
- 'Center': Text box centered both ways (dead center)
- 'Bottom Center': Text box CENTER anchored at 65% height (877px from top). Max text box height: 260px. If text is long, REDUCE FONT SIZE to fit within 260px height — do NOT push the box lower. NEVER let the text box extend below 1040px from the top

Text box:
- Clean rectangular box with rounded corners (~12px radius)
- Background: {effective_bg} with 90% opacity
- Padding: 20px horizontal, 14px vertical
- Width: 80% of image width, centered

{text_display}

- Alignment: Centered

TEXT FORMATTING: If the text contains hyphens (-), em dashes (—), or en dashes (–) used as separators between ideas, replace them with a line break. Each line should be a clean thought without dash separators.

IMPORTANT: Do NOT place text in the bottom 150px of the image.

Output: exactly 1080x1350px, photorealistic scene with text overlay on top."""


def build_card_slide_prompt(
    text: str,
    text_position: str,
    font_prompt: str,
    font_style: str,
    font_size: str,
    color_primary: str,
    color_secondary: str,
    color_background: str = None,
    slide_index: int = 0,
    font_prompt_secondary: str | None = None,
) -> str:
    # -- Visual variety based on slide_index --
    pattern = CARD_PATTERNS[slide_index % len(CARD_PATTERNS)]
    layout = CARD_LAYOUTS[slide_index % len(CARD_LAYOUTS)]

    # Alternate between light-on-dark and dark-on-light
    is_dark_card = slide_index % 2 == 0

    if is_dark_card:
        bg_base = color_primary
        bg_accent = color_secondary
        default_text_color = color_secondary
        gradient_direction = "top-left to bottom-right"
        gradient_desc = f"gradient from {color_primary} (top-left) to a 15% lighter shade of {color_primary} (bottom-right)"
    else:
        bg_base = color_background or ("#FFFDF5" if is_light(color_secondary) else color_secondary)
        bg_accent = color_primary
        default_text_color = color_primary
        gradient_direction = "top-right to bottom-left"
        gradient_desc = f"gradient from {bg_base} (top-right) to a slightly warmer/cooler shade (bottom-left)"

    # Determine effective background for contrast checks
    effective_bg = bg_base

    # Split text into hook and body in Python — don't ask Gemini to do it
    hook_text, body_text = _split_hook_body(text)

    # -- Typography --
    if body_text:
        # Two-part slide: hook + body
        if font_style == "editorial-mixed":
            # Dark card: primary IS the bg — use secondary as bold, white as script
            # Light card: use primary as bold, secondary as script
            em_bold = color_secondary if is_dark_card else color_primary
            em_script = "#FFFFFF" if is_dark_card else color_secondary
            typography_block = _build_editorial_mixed_typography(
                em_bold, em_script, effective_bg, font_size,
            )
            text_section = f"""TEXT CONTENT — PRE-SPLIT INTO HOOK + BODY:
(Do NOT re-split — use exactly as provided below)

HOOK (render this BIG and bold at the {layout["hook_pos"]}):
"{hook_text}"

BODY (render this below in a DIFFERENT style at {layout["body_pos"]}):
"{body_text}"

{typography_block}

{ANTI_EFFECT_RULES}

{CANVAS_RULES}"""
        else:
            # Validate contrast
            validated_title = ensure_contrast(color_secondary if is_dark_card else color_primary, effective_bg, 4.5)
            validated_body = ensure_contrast(
                "#FFFFFF" if is_dark_card else color_primary,
                effective_bg,
                4.5,
            )
            validated_accent = ensure_contrast(color_secondary, effective_bg, 3.0)

            secondary_font_rule_card = ""
            if font_prompt_secondary and body_text:
                secondary_font_rule_card = f"\n- BODY text specifically: {font_prompt_secondary} — DIFFERENT style from hook"

            text_section = f"""TEXT CONTENT — PRE-SPLIT INTO HOOK + BODY:
(Do NOT re-split — use exactly as provided below)

HOOK (render this BIG and bold at the {layout["hook_pos"]}):
"{hook_text}"

BODY (render this below in a DIFFERENT style at {layout["body_pos"]}):
"{body_text}"

MANDATORY TYPOGRAPHY RULES (CRITICAL - NEVER IGNORE):
- USE ONLY the font specified in font_prompt — do NOT use any other font family
            - The font style must be: {font_style} — use that exact weight/style
- Never mix different font families — ONE font family only
- If you cannot find the exact font, use a similar bold sans-serif
- HOOK: {font_prompt}, MAXIMUM bold weight (900), size {font_size} or MUCH LARGER (at least 72px+), color {validated_title}, UPPERCASE — this must dominate the slide
- BODY: {font_prompt}, light or regular weight (300-400), size 30-36px, color {validated_body}, Sentence case — supporting, not competing{secondary_font_rule_card}
- These MUST look visually DIFFERENT — different weight, different size, different case
- If hook and body look the same, this slide FAILS quality check

MANDATORY COLOR RULES:
- The HOOK text MUST be rendered in {validated_title} — this is NOT optional
- The BODY text MUST be rendered in {validated_body} — a DIFFERENT shade/color from the hook
- The accent divider line MUST use {validated_accent}
- If I see ALL text in the SAME color, this slide FAILS quality check
- Both brand colors ({color_primary} and {color_secondary}) MUST be visually present

MANDATORY FONT RULES:
- HOOK: Extra-bold weight, LARGE size ({font_size} or bigger), UPPERCASE
- BODY: Regular/light weight, smaller size (28-32px), normal case
- These MUST look visually DIFFERENT — different weight, different size, different case
- If hook and body look the same, this slide FAILS

- Accent divider line between hook and body: thin horizontal line in {validated_accent}, ~60% width
- Text alignment: {layout["align"]}

WHAT NOT TO DO:
- All text same size -> WRONG
- All text same color -> WRONG
- All text same font weight -> WRONG
- No divider between hook and body -> WRONG
- Hook and body look identical -> WRONG, this FAILS

{ANTI_EFFECT_RULES}

{CANVAS_RULES}"""
    else:
        # Single-line slide: hook only
        # Dark card: secondary is visible against primary bg; light card: primary is visible
        validated_title = ensure_contrast(color_secondary if is_dark_card else color_primary, effective_bg, 4.5)

        text_section = f"""TEXT CONTENT — SINGLE LINE ONLY:
(This is a single-sentence slide — there is NO body text)

HOOK (render this centered, large, and bold):
"{hook_text}"

This is a SINGLE-LINE slide. Render ONLY the hook text, centered, in large bold display. NO body text. NO second text block.

SINGLE-LINE TYPOGRAPHY RULES:
- Font: {font_prompt}, extra-bold weight (800+), size {font_size} or LARGER, UPPERCASE
- Color: {validated_title}
- Centered horizontally and vertically on the card
- NO divider line — there is no body to separate from

{ANTI_EFFECT_RULES}

{CANVAS_RULES}"""

    return f"""NO FOOTER WATERMARK: Do NOT reserve space for a logo footer or watermark. The image should use the full canvas naturally from top to bottom.

Generate a BOLD, high-impact Instagram carousel card slide.

BACKGROUND — CRITICAL RULES (ZERO EXCEPTIONS):
- Resolution: exactly 1080x1350 pixels (4:5 portrait)
- EVERY SINGLE PIXEL of the background must be the color {bg_base} — uniform, flat, solid
- NO gradient of any kind (radial, linear, diagonal — NONE)
- NO concentric circles, NO wave lines, NO geometric shapes in the background
- NO vertical or horizontal stripes, NO side bars, NO corner accents
- NO texture, NO noise, NO grain, NO pattern, NO bokeh
- NO text box with white/light background behind the text — text goes DIRECTLY on the flat color
- The result should look like a solid {bg_base} paint fill with ONLY typography on top
- If you add ANY design element to the background other than flat {bg_base} color, this slide FAILS

{text_section}

TEXT FORMATTING: If the text contains hyphens (-), em dashes (—), or en dashes (–) used as separators between ideas, replace them with a line break. Each line should be a clean thought without dash separators.

LAYOUT:
- Text alignment: CENTER — always centered for maximum visual impact
- Position: CENTER of the canvas — vertically and horizontally centered
- Leave generous whitespace above and below the text — do NOT cram text

IMPORTANT: Do NOT place text in the bottom 150px of the card.

Output: exactly 1080x1350px, premium branded card with dynamic typography and visual hierarchy."""
