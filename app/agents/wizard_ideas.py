"""WizardIdeasAgent — generates content ideas based on brand profile.

Implements CHAT-402: streaming ideas agent using gemini-2.5-flash-lite.
Pure text generation, no tools.
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.base import BaseStreamingAgent
from app.config import get_settings
from app.services.brand import BrandService
from app.prompts.ideas_generate import (
    build_brand_brief,
    build_ideas_system_prompt,
)

logger = logging.getLogger(__name__)


class WizardIdeasAgent(BaseStreamingAgent):
    """Generates 5-10 content ideas as streamed text.

    Uses gemini-2.5-flash-lite for fast, cheap idea generation.
    Loads brand profile from Supabase to personalize ideas.
    """

    def __init__(self, user_id: str, agent_type: str) -> None:
        super().__init__(user_id=user_id, agent_type=agent_type)
        self._brand_service = BrandService()
        self._cached_prompt: str | None = None

    @property
    def model(self) -> str:
        return self._settings.gemini_model_lite

    @property
    def system_prompt(self) -> str:
        """Return cached prompt or a sensible default.

        The real prompt is built async in ``stream()`` after loading the
        brand profile.  This property satisfies the ABC contract and is
        used only if ``stream()`` somehow skips the async build.
        """
        if self._cached_prompt:
            return self._cached_prompt
        return (
            "You are a creative content strategist. Generate a rich batch of "
            "content ideas based on the user request. Each idea should have "
            "a catchy title and a one-line hook. Be specific, not generic, "
            "and do not number the ideas."
        )

    @property
    def temperature(self) -> float:
        return 0.8  # slightly higher for creative ideas

    @property
    def max_tokens(self) -> int:
        return 4096

    async def execute_tool(
        self, name: str, args: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any]:
        """No tools — pure text generation."""
        return {"error": f"Unknown tool: {name}"}

    async def stream(self, message: str, history: list[dict] | None = None, **kwargs: Any):
        """Override stream to inject brand-aware system prompt."""
        # Load brand profile
        try:
            profile = await self._brand_service.load_profile(self.user_id)
        except Exception as exc:
            logger.warning("Failed to load brand profile for %s: %s", self.user_id, exc)
            profile = BrandService._defaults(self.user_id)

        # Load brand stories
        from app.services.stories_service import load_user_stories, build_stories_prompt_block
        stories = await load_user_stories(self.user_id)
        stories_block = build_stories_prompt_block(stories, topic=message)

        # Build personalized system prompt
        brand_brief = build_brand_brief(profile)
        brand_name = profile.get("brand_name") or "the brand"

        self._cached_prompt = f"""You are a creative content strategist for {brand_name}. Your job is to generate scroll-stopping content ideas personalized to this brand.

{brand_brief}

## Your Task

Generate a rich batch of content ideas based on what the user asks. For each idea, provide:
- A punchy title (specific, under 60 characters, never starting with a number)
- A one-line hook (the scroll-stopping opening line)
- The content type (educational, myth-busting, client-story, uncomfortable-truth, viral-shareable, direct-cta)
- A brief angle description

## Quality Rules
- Every idea MUST be specific to {brand_name} and their audience
- No generic listicle-style ideas — be creative and edgy
- Mix at least 3 different content types across the ideas
- Each title must pass the specificity test: would this work for ANY brand? If yes, rewrite it.

## Format
Present ideas as a clean bullet list with no numbering. Be conversational but professional.
Write in the same language as the user message."""

        if stories_block:
            self._cached_prompt += "\n\n" + stories_block

        # Delegate to parent stream with the now-cached prompt
        async for chunk in super().stream(message, history, **kwargs):
            yield chunk
