"""Prompts for AI post image generation.

Builds Gemini image-generation prompts for each of the 12 post template types,
incorporating brand colors, fonts, visual identity, and assembled text fields.
"""

from __future__ import annotations

import random
from typing import Any


def _blend_with_white(hex_color: str, opacity: float) -> str:
    """Return hex color as if hex_color was painted at `opacity` over white.

    Example: _blend_with_white("#000000", 0.80) → "#333333"
    Avoids passing "at X% opacity" phrases to Gemini, which renders them as
    literal text in the generated image.
    """
    c = hex_color.lstrip("#")
    if len(c) != 6:
        return hex_color
    r = int(c[0:2], 16)
    g = int(c[2:4], 16)
    b = int(c[4:6], 16)
    r2 = int(r * opacity + 255 * (1 - opacity))
    g2 = int(g * opacity + 255 * (1 - opacity))
    b2 = int(b * opacity + 255 * (1 - opacity))
    return f"#{r2:02X}{g2:02X}{b2:02X}"

# ---------------------------------------------------------------------------
# Template visual categories
# ---------------------------------------------------------------------------

# Photo-based: lifestyle photography with text overlay
_PHOTO_TEMPLATES = {
    "tip-card", "did-you-know", "before-after-teaser",
    "question-hook", "testimonial-card",
}

# Graphic card: flat/solid background, bold typography only
_CARD_TEMPLATES = {
    "quote-card", "myth-vs-fact", "stat-callout",
}

# Promo/info: structured promotional or informational layout
_PROMO_TEMPLATES = {
    "offer-flyer", "event-banner", "service-spotlight", "checklist-post",
}

# ---------------------------------------------------------------------------
# Shared quality rules (reused from ai_carousel_generate)
# ---------------------------------------------------------------------------

_ANTI_EFFECT_RULES = """CRITICAL ANTI-EFFECT RULES — NEVER VIOLATE:
- EVERY letter in a word MUST have the EXACT SAME font weight — NO per-letter weight variation
- NO glow, shine, blur, or shadow effects on any letter
- NO gradient fills on individual letters or words
- The typography must look like clean, flat, printed text — NOT an artistic effect"""

_CANVAS_RULES = """CANVAS RULES — CRITICAL:
- Fill the ENTIRE 1080x1350 canvas — NO white borders, NO white padding at any edge
- NO slide counters, progress dots, watermarks, or page numbers
- NO split-screen or multi-panel layouts — ONE single cohesive image
- NO footer bar or header band with separate color"""

_COMPOSITION_VARIATIONS = [
    "Shot from a slightly low angle, looking up",
    "Close-up framing, intimate perspective",
    "Medium shot, waist-up framing",
    "Shot with shallow depth of field, blurred background",
    "Wide shot showing the full environment",
]

_LIGHTING_VARIATIONS = [
    "Soft natural window light",
    "Golden hour warm lighting",
    "Bright, even studio lighting",
    "Warm candlelit ambiance",
]


# ---------------------------------------------------------------------------
# Text assembly helpers
# ---------------------------------------------------------------------------

def _assemble_overlay_text(template_key: str, text_fields: dict[str, str]) -> str:
    """Assemble the text overlay content for a template."""
    tf = text_fields

    if template_key == "tip-card":
        headline = tf.get("headline", "")
        tip = tf.get("tip_body", "")
        return f"{headline}\n{tip}" if tip else headline

    if template_key == "myth-vs-fact":
        return (
            f"MYTH: {tf.get('myth', '')}\n"
            f"FACT: {tf.get('fact', '')}"
        )

    if template_key == "quote-card":
        quote = tf.get("quote", "")
        author = tf.get("author", "")
        return f'"{quote}"\n— {author}' if author else f'"{quote}"'

    if template_key == "did-you-know":
        return f"Did You Know?\n{tf.get('headline', '')}\n{tf.get('fact', '')}"

    if template_key == "before-after-teaser":
        return (
            f"{tf.get('headline', '')}\n"
            f"BEFORE: {tf.get('before_state', '')}\n"
            f"AFTER: {tf.get('after_state', '')}"
        )

    if template_key == "question-hook":
        q = tf.get("question", "")
        sub = tf.get("subtitle", "")
        return f"{q}\n{sub}" if sub else q

    if template_key == "testimonial-card":
        t = tf.get("testimonial", "")
        name = tf.get("client_name", "")
        result = tf.get("result", "")
        parts = [f'"{t}"', f"— {name}" if name else ""]
        if result:
            parts.append(f"✓ {result}")
        return "\n".join(p for p in parts if p)

    if template_key == "offer-flyer":
        lines = [tf.get("offer_title", "")]
        if tf.get("offer_details"):
            lines.append(tf["offer_details"])
        if tf.get("price"):
            lines.append(tf["price"])
        if tf.get("cta"):
            lines.append(tf["cta"])
        return "\n".join(l for l in lines if l)

    if template_key == "event-banner":
        lines = [
            tf.get("event_name", ""),
            tf.get("date_time", ""),
            tf.get("location", ""),
            tf.get("cta", ""),
        ]
        return "\n".join(l for l in lines if l)

    if template_key == "service-spotlight":
        lines = [tf.get("service_name", "")]
        for k in ["benefit_1", "benefit_2", "benefit_3"]:
            if tf.get(k):
                lines.append(f"✓ {tf[k]}")
        if tf.get("cta"):
            lines.append(tf["cta"])
        return "\n".join(l for l in lines if l)

    if template_key == "checklist-post":
        lines = [tf.get("headline", "")]
        for i in range(1, 5):
            item = tf.get(f"item_{i}", "")
            if item:
                lines.append(f"{i}. {item}")
        return "\n".join(l for l in lines if l)

    if template_key == "stat-callout":
        num = tf.get("stat_number", "")
        label = tf.get("stat_label", "")
        ctx = tf.get("context", "")
        src = tf.get("source", "")
        lines = [f"{num}\n{label}", ctx]
        if src:
            lines.append(f"Source: {src}")
        return "\n".join(l for l in lines if l)

    # Fallback: join all non-empty values
    return "\n".join(v for v in text_fields.values() if v)


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def _build_photo_prompt(
    template_key: str,
    text_fields: dict[str, str],
    topic: str,
    brand: dict[str, Any],
) -> str:
    """Photo-based template: lifestyle photography with text box overlay."""
    color_primary = brand.get("brand_color_primary") or "#000000"
    color_secondary = brand.get("brand_color_secondary") or "#FFFFFF"
    font_prompt = brand.get("font_prompt") or "Clean bold sans-serif"
    font_style = brand.get("font_style") or "bold"
    font_size = brand.get("font_size") or "38px"
    brand_voice = brand.get("brand_voice") or "professional"
    env = brand.get("visual_environment") or brand.get("visual_environment_setup") or "clean studio or clinic setting"
    subject_generic = brand.get("visual_subject_generic") or brand.get("visual_subject_outfit_generic") or "professional woman in wellness context"
    visual_identity = brand.get("visual_identity") or "modern, clean, trustworthy"

    overlay_text = _assemble_overlay_text(template_key, text_fields)
    composition = random.choice(_COMPOSITION_VARIATIONS)
    lighting = random.choice(_LIGHTING_VARIATIONS)

    scene_direction = {
        "tip-card": f"A calm, focused health/wellness scene evoking the concept: '{topic}'.",
        "did-you-know": f"A striking health awareness scene that visually represents: '{topic}'.",
        "before-after-teaser": f"A transformation story — show the 'after' state: someone confident and empowered in a health context related to: '{topic}'.",
        "question-hook": f"An intimate, relatable moment of a person reflecting on their health. Context: '{topic}'.",
        "testimonial-card": f"A warm, authentic portrait of a satisfied client in a wellness setting. Topic: '{topic}'.",
    }.get(template_key, f"Professional wellness/health scene related to: '{topic}'.")

    return f"""NO FOOTER WATERMARK: Do NOT reserve space for a logo footer or watermark.

Generate a professional Instagram post image (1080x1350px, 4:5 portrait).

SCENE DESCRIPTION:
{scene_direction}
Environment: {env}
Subject (if present): {subject_generic}
Visual identity: {visual_identity}
Composition: {composition}
Lighting: {lighting}

IMAGE SPECS:
- Resolution: exactly 1080x1350 pixels
- Style: Photorealistic, professional, high quality
- Brand voice mood: {brand_voice}

TEXT OVERLAY (MANDATORY — must appear on top of the scene):
Add a clean text overlay card over the lower 40% of the image.

Text box:
- Background: {_blend_with_white(color_secondary, 0.90)}
- Padding: 20px horizontal, 14px vertical
- Width: 85% of image width, centered
- Rounded corners (~12px)

TYPOGRAPHY:
- Font: {font_prompt}, style: {font_style}
- Primary text color: {color_primary}, size: {font_size}
- Second line (if any): slightly smaller, same font, lighter weight

TEXT TO RENDER (render exactly as given, splitting on newlines):
{overlay_text}

{_ANTI_EFFECT_RULES}

{_CANVAS_RULES}

Output: exactly 1080x1350px photorealistic post with text overlay."""


def _build_card_prompt(
    template_key: str,
    text_fields: dict[str, str],
    topic: str,
    brand: dict[str, Any],
) -> str:
    """Graphic card template: flat colored background with bold typography."""
    color_primary = brand.get("brand_color_primary") or "#000000"
    color_secondary = brand.get("brand_color_secondary") or "#FFFFFF"
    font_prompt = brand.get("font_prompt") or "Clean bold sans-serif"
    font_style = brand.get("font_style") or "bold"
    font_size = brand.get("font_size") or "38px"

    overlay_text = _assemble_overlay_text(template_key, text_fields)

    # Two-color alternating: even→ primary bg, odd → secondary bg
    use_dark = True  # primary bg
    bg = color_primary if use_dark else color_secondary
    text_color = color_secondary if use_dark else color_primary
    accent = color_secondary if use_dark else color_primary

    template_instructions = {
        "quote-card": (
            f"Large italic quote mark at top-left in {accent}. "
            f"Quote text centered, elegant. Attribution below in smaller size."
        ),
        "myth-vs-fact": (
            f"TWO clearly separated panels. "
            f"Top panel labeled 'MYTH' with a ✗ icon in red/warning color. "
            f"Bottom panel labeled 'FACT' with a ✓ icon in {accent}. "
            f"Clear visual separation between panels."
        ),
        "stat-callout": (
            f"The STAT NUMBER must be ENORMOUS — at least 3× larger than other text, centered top-half. "
            f"Stat label below in medium size. Context in smaller text. Source in tiny text at bottom."
        ),
    }.get(template_key, "Bold centered typography with visual hierarchy.")

    return f"""NO FOOTER WATERMARK. Do NOT reserve space for logo footer.

Generate a BOLD typographic Instagram post card (1080x1350px).

BACKGROUND — CRITICAL:
- Solid flat color: {bg}
- NO gradients, NO textures, NO patterns, NO photos
- Every pixel must be exactly {bg}

LAYOUT DIRECTION:
{template_instructions}

TYPOGRAPHY:
- Primary font: {font_prompt}, style: {font_style}
- Main text color: {text_color}
- Accent / highlight color: {accent}
- Main font size: {font_size} or larger for impact
- Brand colors present: {color_primary} and {color_secondary}

TEXT TO RENDER (split on newlines, render each as a distinct visual block):
{overlay_text}

VISUAL HIERARCHY:
- First line: LARGEST, bold, uppercase if it's a label or stat
- Middle content: medium size, sentence case
- Last line (if CTA): bold, can be in accent color with underline or border

{_ANTI_EFFECT_RULES}

{_CANVAS_RULES}

Output: exactly 1080x1350px premium typographic card."""


def _build_promo_prompt(
    template_key: str,
    text_fields: dict[str, str],
    topic: str,
    brand: dict[str, Any],
) -> str:
    """Promotional / informational template."""
    color_primary = brand.get("brand_color_primary") or "#000000"
    color_secondary = brand.get("brand_color_secondary") or "#FFFFFF"
    font_prompt = brand.get("font_prompt") or "Clean bold sans-serif"
    font_style = brand.get("font_style") or "bold"
    font_size = brand.get("font_size") or "38px"
    brand_name = brand.get("brand_name") or ""
    visual_identity = brand.get("visual_identity") or "modern, clean"

    overlay_text = _assemble_overlay_text(template_key, text_fields)

    layout_spec = {
        "offer-flyer": (
            "Promotional flyer layout. Offer title at top in large bold text. "
            "Price in a highlighted badge (accent color circle or pill). "
            "Details in medium text. CTA at bottom in a filled button shape."
        ),
        "event-banner": (
            "Event announcement. Event name prominently at top. "
            "Date/time in a colored badge or bar. Location with pin icon. "
            "CTA at bottom in a filled button with high contrast."
        ),
        "service-spotlight": (
            "Service feature card. Service name as headline. "
            "Benefits as checkmark list items, each on its own line. "
            "CTA button at bottom."
        ),
        "checklist-post": (
            "Checklist / numbered list post. Headline at top in bold. "
            "Each item numbered (1, 2, 3...) with slight indent. "
            "Alternating text colors for readability."
        ),
    }.get(template_key, "Clean professional card layout.")

    body_color = _blend_with_white(color_primary, 0.80)
    divider_color = _blend_with_white(color_primary, 0.40)

    return f"""NO FOOTER WATERMARK. Do NOT add logo footer area.

Generate a professional branded {template_key} Instagram post (1080x1350px).

BACKGROUND:
- Primary background color: {color_secondary} (light)
- Accent elements, borders, and highlights use: {color_primary}
- Keep it clean and airy — lots of white space

BRAND: {brand_name}
Visual identity: {visual_identity}

LAYOUT:
{layout_spec}

TYPOGRAPHY:
- Font family: {font_prompt}, style: {font_style}
- Headlines: {color_primary}, size: {font_size} or larger
- Body text: {body_color}, smaller size
- CTA elements: filled with {color_primary}, text {color_secondary}
- Accent dividers: thin horizontal rule in {divider_color}

TEXT CONTENT (render each line as a distinct visual element, splitting on newlines):
{overlay_text}

{_ANTI_EFFECT_RULES}

{_CANVAS_RULES}

Output: exactly 1080x1350px professional branded post."""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def build_post_image_prompt(
    template_key: str,
    text_fields: dict[str, str],
    topic: str,
    brand: dict[str, Any],
) -> str:
    """Build the full Gemini image-generation prompt for a post.

    Parameters
    ----------
    template_key:
        One of the 12 PostTemplateKey values.
    text_fields:
        Map of field keys → generated text values.
    topic:
        The content topic (used for scene direction on photo templates).
    brand:
        User's brand profile dict (colors, fonts, visual identity, etc.).

    Returns
    -------
    str
        Full prompt string ready for ImageGeneratorService.generate_from_prompt().
    """
    if template_key == "hero-title":
        return _build_hero_title_background_prompt(brand)
    elif template_key in _PHOTO_TEMPLATES:
        return _build_photo_prompt(template_key, text_fields, topic, brand)
    elif template_key in _CARD_TEMPLATES:
        return _build_card_prompt(template_key, text_fields, topic, brand)
    else:
        return _build_promo_prompt(template_key, text_fields, topic, brand)


def build_masterclass_background_prompt(text_fields: dict[str, str], brand: dict) -> str:
    """Background scene for masterclass-banner: elegant, professional, topic-relevant."""
    topic_hint = text_fields.get("title", text_fields.get("event_label", "masterclass"))
    color = brand.get("brand_color_primary") or "#1A9E8F"
    identity = brand.get("visual_identity") or "modern clean health professional aesthetic"
    env = brand.get("visual_environment_setup") or "modern wellness studio or professional setting"
    return (
        f"Create a high-quality 1080x1350 background photograph for a professional masterclass promotion. "
        f"Topic: {topic_hint}. "
        f"Setting: {env}, {identity}. "
        f"Style: cinematic, professional, slight bokeh. "
        f"Mood: aspirational, authoritative, warm. "
        f"Brand accent color present subtly in the scene: {color}. "
        f"NO text, NO people, NO logos in the image — BACKGROUND ONLY. "
        f"Fill the ENTIRE 1080x1350 canvas with no white borders."
    )


def build_masterclass_person_prompt(brand: dict) -> str:
    """Professional portrait for the person slot in masterclass-banner (AI mode)."""
    outfit_face = brand.get("visual_subject_outfit_face") or brand.get("visual_subject_outfit_generic") or "professional health practitioner"
    identity = brand.get("visual_identity") or "modern, clean, health-focused"
    return (
        f"Professional portrait photograph of {outfit_face}. "
        f"Style: {identity}, confident and approachable expression, slight smile. "
        f"Framing: head and upper body (portrait style), centered subject. "
        f"Background: solid white or very light neutral — NO complex backgrounds. "
        f"Lighting: soft, flattering studio or natural light. "
        f"High quality, photorealistic. "
        f"NO text, NO watermarks."
    )


def build_masterclass_face_mode_prompt(brand: dict) -> str:
    """Face mode: generates full-body professional character preserving the reference face."""
    outfit = brand.get("visual_subject_outfit_face") or brand.get("visual_subject_outfit_generic") or "business casual professional attire"
    identity = brand.get("visual_identity") or "modern, clean, health professional"
    return (
        f"FACE REFERENCE (MANDATORY): A reference photo of a person is attached. "
        f"You MUST preserve this exact person's face, features, skin tone, and likeness in the output. "
        f"Generate a full-body professional photograph of this person. "
        f"Outfit: {outfit}. "
        f"Style: {identity}, confident posture, natural smile, standing or slight three-quarter pose. "
        f"Framing: full body from head to toe, centered, vertical portrait orientation. "
        f"Background: solid white or very light neutral — NO complex backgrounds, NO furniture, NO props. "
        f"Lighting: soft studio light, even and flattering. "
        f"High quality, photorealistic. NO text, NO watermarks, NO background patterns."
    )


def _build_hero_title_background_prompt(brand: dict) -> str:
    """Background-only scene for the hero-title template.

    No text, no overlays — Pillow adds them programmatically.
    """
    visual_env = brand.get("visual_environment_setup") or "a modern, professional health and wellness environment"
    visual_identity = brand.get("visual_identity") or "clean, professional, health-focused aesthetic"
    brand_color = brand.get("brand_color_primary") or "#1A9E8F"
    subject = brand.get("visual_subject_outfit_generic") or "a professional healthcare setting"

    return (
        f"Professional full-bleed social media background photograph for a health and wellness brand. "
        f"Scene: {visual_env}. Subject context: {subject}. "
        f"Visual style: {visual_identity}. "
        f"Color temperature that complements the brand color {brand_color}. "
        "Composition: vertical 4:5 ratio, cinematic, editorial quality. "
        "Slight shallow depth of field — foreground slightly blurred to give depth. "
        "The image will have text overlaid programmatically so keep the center-left area visually calm with minimal busy detail. "
        "NO text, NO overlays, NO watermarks, NO borders, NO typography of any kind. "
        "Fill the entire 1080x1350 canvas. Photorealistic. High production quality."
    )
