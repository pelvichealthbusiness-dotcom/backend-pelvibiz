"""PostContentAgent — generates structured text fields + caption for a post template.

Handles wizard_mode='generate_content' in the /chat/stream endpoint.
Returns ONLY a JSON object so the frontend can parse it directly from
text-delta events (PostApiService fallback path).
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncGenerator

from app.agents.base import BaseStreamingAgent
from app.core.gemini_stream import stream_chat_with_retry
from app.core.streaming import text_chunk, finish_event, error_event
from app.services.brand import BrandService

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Template field registry (mirrors post-templates.ts on the frontend)
# ---------------------------------------------------------------------------

_TEMPLATE_FIELDS: dict[str, dict[str, str]] = {
    "hero-title": {
        "pre_title": "Short setup line above the main title, e.g. 'Stop surviving. Start' (max 40 chars)",
        "main_title": "Powerful main title, 3–6 words, ALL CAPS impact, e.g. 'BUILDING YOUR EMPIRE' (max 40 chars)",
        "accent_word": "ONE high-impact word displayed in brand color — makes the phrase complete, e.g. 'THRIVING' (max 25 chars)",
    },
    "tip-card": {
        "headline": "Bold, actionable headline (max 60 chars)",
        "tip_body": "Clear, concise tip (max 160 chars)",
    },
    "myth-vs-fact": {
        "myth": "Common false belief (max 80 chars)",
        "fact": "The truth / correction (max 160 chars)",
    },
    "quote-card": {
        "quote": "Inspiring quote (max 200 chars)",
        "author": "Author attribution, e.g. 'Dr. Smith, PT' (max 50 chars, optional)",
    },
    "did-you-know": {
        "headline": "Scroll-stopping hook headline (max 60 chars)",
        "fact": "Supporting educational detail (max 200 chars)",
    },
    "offer-flyer": {
        "offer_title": "Offer name (max 60 chars)",
        "offer_details": "What is included (max 140 chars)",
        "price": "Price display, e.g. '$75 (reg. $150)' (max 30 chars, optional)",
        "cta": "Action-oriented CTA (max 40 chars)",
    },
    "event-banner": {
        "event_name": "Event title (max 60 chars)",
        "date_time": "Date and time, e.g. 'Saturday, May 10 · 10am–12pm' (max 50 chars)",
        "location": "Location or 'Online via Zoom' (max 60 chars)",
        "cta": "Registration CTA (max 40 chars)",
    },
    "testimonial-card": {
        "testimonial": "Authentic client quote (max 200 chars)",
        "client_name": "Client name, e.g. 'María G., 34' (max 40 chars)",
        "result": "Key measurable result, e.g. 'Leak-free in 6 sessions' (max 60 chars, optional)",
    },
    "before-after-teaser": {
        "headline": "Transformation headline (max 60 chars)",
        "before_state": "How the client felt / struggled before (max 100 chars)",
        "after_state": "What they achieved after treatment (max 100 chars)",
    },
    "service-spotlight": {
        "service_name": "Service name (max 60 chars)",
        "benefit_1": "Top benefit (max 70 chars)",
        "benefit_2": "Second benefit (max 70 chars)",
        "benefit_3": "Third benefit (max 70 chars)",
        "cta": "Next step CTA (max 40 chars)",
    },
    "checklist-post": {
        "headline": "Checklist title that promises value (max 70 chars)",
        "item_1": "Checklist item 1 (max 70 chars)",
        "item_2": "Checklist item 2 (max 70 chars)",
        "item_3": "Checklist item 3 (max 70 chars)",
        "item_4": "Checklist item 4 (max 70 chars, optional — leave empty if not needed)",
    },
    "question-hook": {
        "question": "Personal, relatable question (max 150 chars)",
        "subtitle": "Follow-up or context line (max 120 chars, optional)",
    },
    "stat-callout": {
        "stat_number": "Big number, e.g. '1 in 3' (max 15 chars)",
        "stat_label": "What the number represents (max 60 chars)",
        "context": "Why it matters and what to do (max 160 chars)",
        "source": "Source citation, e.g. 'WHO, 2023' (max 40 chars, optional)",
    },
    "masterclass-banner": {
        "event_label": "Short event category label, e.g. 'FREE MASTERCLASS' or 'LIVE WORKSHOP' (max 30 chars, ALL CAPS)",
        "title": "Compelling masterclass title that promises transformation (max 60 chars)",
        "subtitle": "One-line value proposition or who it's for (max 80 chars)",
        "date_time": "Date and time, e.g. 'Thursday, May 15 · 7:00 PM EST' (max 50 chars)",
        "venue": "Location or platform, e.g. 'Online via Zoom' or 'Miami Wellness Center' (max 50 chars)",
        "via": "Platform or host detail, e.g. 'Register via link in bio' (max 50 chars)",
        "cta": "Action CTA for the button, e.g. 'Secure Your Spot' (max 30 chars)",
    },
    "patient-story": {
        "section_label": "Category label above the title, e.g. 'PATIENT STORIES' or 'CLIENT WINS' (max 30 chars, ALL CAPS)",
        "testimonial": "Authentic client testimonial — specific, vivid, emotionally resonant. Reference a real transformation or outcome (max 380 chars)",
        "client_name": "Client identifier, e.g. 'Sarah M. — postpartum mom' or 'María G., 3 months postpartum' (max 60 chars)",
        "result": "Key measurable outcome, e.g. 'Leak-free in 6 sessions' or 'Back at the gym in 8 weeks' (max 60 chars, optional — leave empty if testimonial already states the result)",
    },
    "wellness-workshop": {
        "event_label": "Short uppercase event label, e.g. 'FREE WELLNESS WORKSHOP' or 'LIVE MOVEMENT CLASS' (max 40 chars, ALL CAPS)",
        "date_time": "Date and time, e.g. 'Sunday, Jan. 11 @ 11:30 AM' (max 60 chars)",
        "title": "Workshop title describing the physical benefit, warm and inviting, e.g. 'Release Your Low Back, Hips & IT Band' (max 70 chars)",
        "tip_1": "First topic or benefit covered in the workshop, short and punchy (max 60 chars)",
        "tip_2": "Second topic or benefit (max 60 chars)",
        "tip_3": "Third topic or benefit (max 60 chars)",
        "tip_4": "Fourth topic or benefit — optional, leave empty if not needed (max 60 chars)",
        "venue": "Where the event takes place, e.g. 'Online via Zoom' or 'Downtown Wellness Studio' (max 50 chars)",
    },
}


def _build_fields_spec(template_key: str) -> str:
    """Build a JSON example showing the expected field keys."""
    fields = _TEMPLATE_FIELDS.get(template_key, {})
    if not fields:
        return '"headline": "...", "body": "..."'
    lines = [f'    "{k}": "{v}"' for k, v in fields.items()]
    return ",\n".join(lines)


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class PostContentAgent(BaseStreamingAgent):
    """Generates post text fields + caption as pure JSON output.

    Called via wizard_mode='generate_content'. Returns a single JSON object:
        {
            "text_fields": { <field_key>: <value>, ... },
            "caption": "<Instagram caption with hashtags>"
        }
    """

    def __init__(self, user_id: str, agent_type: str) -> None:
        super().__init__(user_id=user_id, agent_type=agent_type)
        self._brand_service = BrandService()

    @property
    def model(self) -> str:
        return self._settings.gemini_model_text

    @property
    def temperature(self) -> float:
        return 0.75

    @property
    def max_tokens(self) -> int:
        return 1024

    @property
    def system_prompt(self) -> str:
        # Overridden dynamically in stream() — this is the fallback
        return (
            "You are a social media copywriter. Respond ONLY with a valid JSON object. "
            "No markdown, no explanation, no code fences."
        )

    async def execute_tool(
        self, name: str, args: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any]:
        return {"error": f"Unknown tool: {name}"}

    async def stream(
        self,
        message: str,
        history: list[dict] | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        """Override to inject brand profile and build template-aware prompt."""
        metadata = kwargs.get("metadata") or {}
        template_key = metadata.get("template_key", "tip-card")
        topic = metadata.get("topic") or message

        # Load brand profile
        try:
            profile = await self._brand_service.load_profile(self.user_id)
        except Exception as exc:
            logger.warning("Failed to load brand profile for %s: %s", self.user_id, exc)
            profile = BrandService._defaults(self.user_id)

        brand_name = profile.get("brand_name") or "the brand"
        brand_voice = profile.get("brand_voice") or "professional and empathetic"
        target_audience = profile.get("target_audience") or "women with pelvic health concerns"
        services = profile.get("services_offered") or "pelvic floor therapy"
        cta = profile.get("cta") or "Book a free consultation"
        keywords = profile.get("keywords") or ""
        content_style = profile.get("content_style_brief") or ""

        fields_spec = _build_fields_spec(template_key)

        style_block = ""
        if content_style and content_style.strip():
            style_block = (
                f"\n\nContent style DNA (match this voice closely):\n{content_style.strip()}"
            )

        hero_extra = ""
        if template_key == "hero-title":
            hero_extra = """

HERO-TITLE SPECIAL RULES:
The 3 fields form a single visual sentence read top-to-bottom:
  [pre_title]  ← sentence case setup, no period
  [main_title] ← ALL CAPS core claim
  [accent_word] ← 1-2 ALL CAPS words in brand color that COMPLETE the phrase

The three together must form ONE powerful thought. Vary the structure:
- Contrast: "Most providers are..." / "WORKING HARDER," / "NOT SMARTER."
- Question resolved: "What separates $5k from $20k months?" / "YOUR SYSTEMS," / "NOT YOUR SKILLS."
- Identity shift: "You weren't trained to be" / "AN ENTREPRENEUR." / "UNTIL NOW."
- Direct provocation: "The thing keeping you stuck" / "ISN'T YOUR NICHE." / "IT'S YOUR PRICE."

BANNED phrases (never use these):
- "you didn't go to school for 8 years"
- "burnout"
- "work-life balance"
- "hustle"
- Any phrase you used in a previous generation

Make the pre_title feel like a fresh setup specific to the topic below."""

        system = f"""You are an expert social media copywriter for health and wellness businesses.
Your task: generate post copy for a '{template_key}' Instagram post.

BRAND CONTEXT:
- Brand: {brand_name}
- Voice: {brand_voice}
- Audience: {target_audience}
- Services: {services}
- CTA: {cta}
- Keywords: {keywords}{style_block}{hero_extra}

OUTPUT FORMAT — CRITICAL:
Respond with ONLY a valid JSON object. No markdown. No code fences. No explanation. Start directly with {{.

The JSON must have this exact shape:
{{
  "text_fields": {{
{fields_spec}
  }},
  "caption": "<full caption with \\n\\n between sections>"
}}

COPY RULES:
1. Text fields: match the character limits in the spec. Be punchy and specific to the topic.
2. Caption — CRITICAL format and content rules:
   STRUCTURE (use \\n\\n between each section — NOT one solid block):
   Line 1: scroll-stopping hook that DIRECTLY references the main idea from text_fields.
   \\n\\n
   2-3 short sentences that EXPAND on the specific content — the "why it matters". Each sentence on its own line or grouped naturally.
   \\n\\n
   Brand CTA line: {cta}
   \\n\\n
   Exactly 3 hashtags (no more — Instagram penalizes caption spam). Niche, relevant to the topic.

   CONTENT rules:
   - Hook must reference the specific text_fields content, not a generic opener.
   - Body adds context, NEVER duplicates exact wording from text_fields.
   - 3 hashtags MAX — quality over quantity.
3. Voice: {brand_voice}. No generic wellness platitudes.
4. All copy — text_fields AND caption — must feel like one coherent piece about the same topic.
5. Write in the same language as the topic below."""

        user_message = f"Topic: {topic}\nTemplate: {template_key}"

        # Stream directly from Gemini — no history needed for this wizard step
        try:
            full_response = ""
            async for chunk in stream_chat_with_retry(
                messages=[{"role": "user", "content": user_message}],
                system_prompt=system,
                model=self.model,
                temperature=self.temperature,
                max_output_tokens=self.max_tokens,
            ):
                if chunk["type"] == "text":
                    full_response += chunk["content"]
                    yield text_chunk(chunk["content"])

            yield finish_event("stop")

        except Exception as exc:
            logger.error(
                "PostContentAgent stream error [%s]: %s",
                self.user_id,
                exc,
                exc_info=True,
            )
            exc_str = str(exc).lower()
            if "429" in exc_str or "resourceexhausted" in exc_str:
                yield error_event("Rate limit exceeded, please try again", "LLM_RATE_LIMIT")
            elif "timeout" in exc_str:
                yield error_event("Request timed out, please try again", "LLM_TIMEOUT")
            else:
                yield error_event("Content generation failed. Please try again.", "INTERNAL_ERROR")
