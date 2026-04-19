"""WizardDraftAgent — generates slide-by-slide draft text from a selected idea.

Implements CHAT-403: streaming draft agent using gemini-2.5-flash-lite.
Pure text generation, no tools.
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.base import BaseStreamingAgent
from app.config import get_settings
from app.services.brand import BrandService
from app.prompts.ideas_generate import build_brand_brief

logger = logging.getLogger(__name__)


class WizardDraftAgent(BaseStreamingAgent):
    """Generates slide-by-slide carousel text as streamed output.

    Uses gemini-2.5-flash-lite for fast, cheap draft generation.
    Loads brand profile from Supabase to match voice and style.
    """

    def __init__(self, user_id: str, agent_type: str) -> None:
        super().__init__(user_id=user_id, agent_type=agent_type)
        self._brand_service = BrandService()
        self._cached_prompt: str | None = None

    @property
    def model(self) -> str:
        return self._settings.gemini_model_text

    @property
    def system_prompt(self) -> str:
        if self._cached_prompt:
            return self._cached_prompt
        return (
            "You are a carousel copywriter. Generate slide-by-slide text "
            "for an Instagram carousel. Each slide should have a title and "
            "body text. Keep slides punchy and scannable."
        )

    @property
    def temperature(self) -> float:
        return 0.7

    @property
    def max_tokens(self) -> int:
        return 4096

    async def execute_tool(
        self, name: str, args: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any]:
        return {"error": f"Unknown tool: {name}"}

    async def stream(self, message: str, history: list[dict] | None = None, **kwargs: Any):
        """Override stream to inject brand-aware system prompt."""
        try:
            profile = await self._brand_service.load_profile(self.user_id)
        except Exception as exc:
            logger.warning("Failed to load brand profile for %s: %s", self.user_id, exc)
            profile = BrandService._defaults(self.user_id)

        # Load brand stories
        from app.services.stories_service import load_user_stories, build_stories_prompt_block
        stories = await load_user_stories(self.user_id)
        stories_block = build_stories_prompt_block(stories, topic=message)

        brand_brief = build_brand_brief(profile)
        brand_name = profile.get("brand_name") or "the brand"
        voice = profile.get("brand_voice") or "professional and approachable"
        cta = profile.get("cta") or ""

        style_section = ""
        csb = profile.get("content_style_brief")
        if csb and isinstance(csb, str) and csb.strip():
            style_section = (
                "\n\n## Writing Style DNA (captured from real Instagram posts)\n"
                "Use this as the PRIMARY voice guide for tone, hooks, CTAs, and caption structure.\n\n"
                + csb.strip()
            )

        if cta:
            cta_instruction = f'Weave in: "{cta}"'
        else:
            cta_instruction = "End with a specific next step."

        self._cached_prompt = f"""You are Brian Mark -- the copywriter behind carousels that generate millions in organic revenue. You write scroll-stopping micro-content that shifts beliefs, builds authority, and drives DMs. Every line passes one test: 'Would someone screenshot this?'

{brand_brief}{style_section}

## Your Task

Write carousel slides for the topic the user provides. This is for {brand_name}.

## Slide Structure

### Slide 1: THE HOOK
- One punchy line that stops the scroll. Max 10 words.
- NEVER start with 'I' or 'How to'
- Use brutal contrast: 'You are doing X. You should be doing Y.'

### Slides 2 to N-1: THE VALUE
- One bold statement per slide. 8-15 words max per slide.
- Lead with the insight, not the setup.
- Rotate formats: uncomfortable truths, contrast, stats, myth-busting.
- If it reads like a paragraph, cut it in half.

### Last Slide: THE CLOSE
- One powerful call to action. Direct. Personal.
- {cta_instruction}

## Voice
- Tone: {voice}
- Direct, confident, zero filler. Speak to ONE person.
- Specifics over adjectives. No corporate speak.

## Caption
After the slides, write an Instagram caption. The caption block MUST contain ALL of these parts in order:
1. Hook line (under 100 chars, different angle from slide 1)
2. Body/insight (2-3 sentences max)
3. CTA (1 sentence)
4. Exactly 5 relevant hashtags on the last line (no generic ones like #motivation #success #mindset)

CRITICAL: The 5 hashtags MUST appear at the end of the **Caption:** block. A caption without hashtags is INVALID.

## Format
Present slides as:
**Slide 1:** [text]
**Slide 2:** [text]
...
**Caption:** [hook line]

[body/insight]

[CTA]

[#hashtag1 #hashtag2 #hashtag3 #hashtag4 #hashtag5]

Write in the same language as the user message."""

        if stories_block:
            self._cached_prompt += "\n\n" + stories_block

        async for chunk in super().stream(message, history, **kwargs):
            yield chunk
