"""BrainstormPostIdeasAgent — generates 4-5 topic idea suggestions for a post template.

Handles wizard_mode='brainstorm_post_ideas' in the /chat/stream endpoint.
Returns a JSON array of strings streamed as text-delta events.
"""

from __future__ import annotations

import logging
import random
from typing import Any, AsyncGenerator

from app.agents.base import BaseStreamingAgent
from app.core.gemini_stream import stream_chat_with_retry
from app.core.streaming import text_chunk, finish_event, error_event
from app.services.brand import BrandService

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Template descriptions for context injection
# ---------------------------------------------------------------------------

TEMPLATE_DESCRIPTIONS: dict[str, str] = {
    "hero-title": "a bold 3-part title post (pre-title + main title + accent word forming one powerful phrase)",
    "tip-card": "a tip or piece of advice",
    "myth-vs-fact": "a common myth to bust",
    "quote-card": "an inspiring quote topic",
    "did-you-know": "a surprising fact",
    "offer-flyer": "a service or offer to promote",
    "event-banner": "an event or workshop",
    "testimonial-card": "a client success story",
    "before-after-teaser": "a transformation story",
    "service-spotlight": "a specific service to highlight",
    "checklist-post": "a checklist topic",
    "question-hook": "a question to engage the audience",
    "stat-callout": "a statistic to share",
}

# Rotating angle prompts to force variety across consecutive calls
_ANGLE_SEEDS = [
    "Focus on mindset and identity shifts for practitioners.",
    "Focus on business systems and time freedom.",
    "Focus on patient outcomes and transformation.",
    "Focus on the emotional cost of burnout and overwork.",
    "Focus on revenue, pricing, and financial independence.",
    "Focus on marketing and visibility for health practices.",
    "Focus on the contrast between old vs new ways of practicing.",
    "Focus on confidence, authority, and niche positioning.",
]


class BrainstormPostIdeasAgent(BaseStreamingAgent):
    """Generates 4-5 post idea suggestions as a JSON array.

    Called via wizard_mode='brainstorm_post_ideas'. Returns a JSON array:
        ["idea 1", "idea 2", "idea 3", "idea 4", "idea 5"]
    """

    def __init__(self, user_id: str, agent_type: str) -> None:
        super().__init__(user_id=user_id, agent_type=agent_type)
        self._brand_service = BrandService()

    @property
    def model(self) -> str:
        return self._settings.gemini_model_text

    @property
    def temperature(self) -> float:
        return 0.7  # More creative/varied

    @property
    def max_tokens(self) -> int:
        return 512

    @property
    def system_prompt(self) -> str:
        # Overridden dynamically in stream() — this is the fallback
        return (
            "You are a social media content strategist. "
            "Respond ONLY with a valid JSON array of strings. "
            "No markdown, no code fences, start with [."
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
        """Override to inject brand profile and template-aware prompt."""
        metadata = kwargs.get("metadata") or {}
        template_key = metadata.get("template_key") or "tip-card"

        # Load brand profile
        try:
            profile = await self._brand_service.load_profile(self.user_id)
        except Exception as exc:
            logger.warning("Failed to load brand profile for %s: %s", self.user_id, exc)
            profile = BrandService._defaults(self.user_id)

        brand_name = profile.get("brand_name") or "the brand"
        target_audience = profile.get("target_audience") or "women with pelvic health concerns"
        services = profile.get("services_offered") or "pelvic floor therapy"
        brand_voice = profile.get("brand_voice") or "professional and empathetic"

        template_description = TEMPLATE_DESCRIPTIONS.get(template_key, "a social media post")
        angle = random.choice(_ANGLE_SEEDS)

        hero_extra = ""
        if template_key == "hero-title":
            hero_extra = """

HERO-TITLE SPECIFIC RULES:
Each idea should be a theme that translates into a punchy 3-part title:
  [setup line] + [bold claim] + [powerful resolution word]
Think in terms of contrasts, provocations, or identity statements.
Example ideas: "The gap between working hard and working smart",
"Why most practices plateau at $10k/month", "Trading time for money is a trap"."""

        system = f"""You are an expert social media content strategist for health and wellness businesses.
Your task: brainstorm 5 DISTINCT topic ideas for a '{template_key}' Instagram post.

BRAND CONTEXT:
- Brand: {brand_name}
- Voice: {brand_voice}
- Audience: {target_audience}
- Services: {services}

POST FORMAT: {template_description}{hero_extra}

CREATIVE DIRECTION FOR THIS BATCH: {angle}

OUTPUT FORMAT — CRITICAL:
Respond ONLY with a valid JSON array. No markdown. No code fences. Start directly with [.
["idea 1", "idea 2", "idea 3", "idea 4", "idea 5"]

RULES:
1. Each idea: 6-14 words, specific and provocative — not generic
2. NEVER use phrases like "you didn't go to school", "burnout", or "work-life balance"
3. Each of the 5 ideas must explore a DIFFERENT angle — no repetition
4. Ideas must feel fresh, specific to {brand_name}'s audience
5. Make them scroll-stopping: provocative, counterintuitive, or deeply relatable"""

        user_message = f"Template: {template_key}. Brand: {brand_name}. Services: {services}."

        try:
            async for chunk in stream_chat_with_retry(
                messages=[{"role": "user", "content": user_message}],
                system_prompt=system,
                model=self.model,
                temperature=self.temperature,
                max_output_tokens=self.max_tokens,
            ):
                if chunk["type"] == "text":
                    yield text_chunk(chunk["content"])

            yield finish_event("stop")

        except Exception as exc:
            logger.error(
                "BrainstormPostIdeasAgent stream error [%s]: %s",
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
                yield error_event("Idea generation failed. Please try again.", "INTERNAL_ERROR")
