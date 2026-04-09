"""
Gemini prompts for fixing individual P2 AI Carousel slides.
Unlike P1, there's no "preserve the photo" — we regenerate from scratch.
"""


def build_ai_fix_generic_prompt(
    original_prompt: str,
    new_text: str | None,
    font_prompt: str,
    font_style: str,
    color_primary: str,
    color_secondary: str,
    topic: str = "",
    carousel_context: str = "",
) -> str:
    if new_text:
        text_rule = f'Use this NEW text: "{new_text}"'
    elif topic:
        text_rule = f'Generate NEW text that is specifically about: {topic}. The text must clearly relate to this topic.'
    else:
        text_rule = "Use the same text concept as before but write it differently."

    topic_block = ""
    if topic:
        topic_block = f"""
CAROUSEL TOPIC: {topic}
CRITICAL: The regenerated slide MUST be relevant to this topic. ALL text and imagery must relate to: {topic}
Do NOT generate generic or unrelated content. Stay on-topic.
"""

    context_block = ""
    if carousel_context:
        context_block = f"""
CAROUSEL CONTEXT (same publication):
{carousel_context}

MATCH RULES:
- Keep the same publication style, tone, typography, and spacing as the other slides above.
- Do NOT invent a new look or random layout.
- Do NOT add a separate footer strip, white band, or blank bar below the image.
- Keep the composition full-bleed edge-to-edge.
"""

    return f"""Regenerate this Instagram carousel slide with improvements.
{topic_block}
{context_block}
ORIGINAL SCENE CONCEPT:
{original_prompt}

INSTRUCTIONS:
- Generate a FRESH version of this scene — same publication style, similar concept, but not an identical copy
- Make it look like a professional photograph
- 1080x1350 pixels, 4:5 portrait format
- Preserve the slide's visual language across the carousel

TEXT OVERLAY:
{text_rule}

Text box: {color_secondary} with 90% opacity, rounded corners, 80% width
Font: {font_prompt}, {font_style}, Color: {color_primary}, Centered

Do NOT create a separate footer bar or white band. If a logo is used, it must stay as a subtle overlay inside the image.

TEXT FORMATTING: If the text contains hyphens (-), em dashes (—), or en dashes (–) used as separators between ideas, replace them with a line break. Each line should be a clean thought without dash separators."""


def build_ai_fix_card_prompt(
    new_text: str | None,
    font_prompt: str,
    font_style: str,
    color_primary: str,
    color_secondary: str,
    topic: str = "",
    carousel_context: str = "",
) -> str:
    if new_text:
        text_content = new_text
    elif topic:
        text_content = f"Generate a fresh, engaging text specifically about: {topic}. The text MUST clearly relate to this topic."
    else:
        text_content = "Generate a fresh, engaging text for this card slide"

    topic_block = ""
    if topic:
        topic_block = f"""
CAROUSEL TOPIC: {topic}
CRITICAL: The card content MUST be relevant to this topic. Do NOT generate generic or unrelated content.
Every piece of text on this card must relate to: {topic}
"""

    context_block = ""
    if carousel_context:
        context_block = f"""
CAROUSEL CONTEXT (same publication):
{carousel_context}

MATCH RULES:
- Keep the same publication style, typography, spacing, and brand feel as the other slides.
- Do NOT invent a new look or random layout.
- Do NOT add a separate footer strip, white band, or blank bar below the card.
"""

    return f"""Regenerate this Instagram carousel card slide.
{topic_block}
{context_block}
DESIGN:
- 1080x1350 pixels, 4:5 portrait
- Background: solid {color_primary} (or subtle gradient)
- Clean, minimal, professional

TEXT: "{text_content}"
Font: {font_prompt}, {font_style}, Color: {color_secondary}, Centered
Do NOT create a separate footer bar or white band. If a logo is used, it must stay as a subtle overlay inside the image.

TEXT FORMATTING: If the text contains hyphens (-), em dashes (—), or en dashes (–) used as separators between ideas, replace them with a line break. Each line should be a clean thought without dash separators."""
