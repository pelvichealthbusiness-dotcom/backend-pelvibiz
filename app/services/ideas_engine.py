import json
import logging
import asyncio
from difflib import SequenceMatcher
from uuid import uuid4
from openai import AsyncOpenAI
from app.config import get_settings
from app.services.brand import BrandService
from app.services.learning import LearningService
from app.services.exceptions import IdeasGenerationError
from app.prompts.ideas_generate import (
    build_brand_brief,
    build_learning_section,
    build_anti_repetition_section,
    build_ideas_system_prompt,
    build_video_ideas_prompt,
)

logger = logging.getLogger(__name__)

SIMILARITY_THRESHOLD = 0.8

# Music track IDs must match the frontend music-tracks.ts definitions
_BRAND_VOICE_MUSIC: dict[str, str] = {
    # energetic / bold voices
    "empowering": "rise",
    "energetic": "energize",
    "motivational": "rise",
    "bold": "impact",
    "powerful": "impact",
    "dynamic": "energize",
    # calm / professional voices
    "clinical": "flow",
    "scientific": "flow",
    "educational": "inspire",
    "informative": "inspire",
    "calm": "flow",
    "soft": "inspire",
    "warm": "inspire",
    # modern / trendy voices
    "conversational": "chill",
    "friendly": "chill",
    "casual": "chill",
    "modern": "pulse",
    "trendy": "pulse",
    # epic / premium voices
    "inspirational": "triumph",
    "premium": "triumph",
    "luxury": "triumph",
}

_TEMPLATE_MUSIC_DEFAULTS: dict[str, str] = {
    "myth-buster": "impact",
    "bullet-sequence": "energize",
    "viral-reaction": "pulse",
    "testimonial-story": "inspire",
    "big-quote": "triumph",
    "deep-dive": "rise",
}

def _recommend_music_track(brand_voice: str, template_key: str) -> str:
    """Return the best music track ID for the given brand voice + template combination."""
    voice_lower = (brand_voice or "").lower()
    # Check brand voice keywords first
    for keyword, track_id in _BRAND_VOICE_MUSIC.items():
        if keyword in voice_lower:
            return track_id
    # Fall back to template default
    return _TEMPLATE_MUSIC_DEFAULTS.get(template_key, "rise")


class IdeasEngine:
    def __init__(self):
        settings = get_settings()
        self.client = AsyncOpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
        )
        self.model = settings.llm_model
        self.brand_service = BrandService()
        self.learning_service = LearningService()

    async def generate_ideas(
        self,
        user_id: str,
        message: str,
        agent_type: str,
        wizard_mode: str = "ideas",
        exclude_ids: list[str] | None = None,
        video_template: str | None = None,
        count: int = 5,
    ) -> dict:
        """Generate content ideas with full context awareness."""
        
        # Parallel load: brand profile + learning patterns + recent titles
        profile_task = self.brand_service.load_profile(user_id)
        patterns_task = self.learning_service.get_patterns(user_id)
        titles_task = self.learning_service.get_recent_titles(user_id, limit=30)
        
        profile, patterns, recent_titles = await asyncio.gather(
            profile_task, patterns_task, titles_task
        )
        
        if not profile or not profile.get("brand_name"):
            raise IdeasGenerationError("No brand profile found. Complete onboarding first.")
        
        # Build context sections
        brand_brief = build_brand_brief(profile)
        learning_section = build_learning_section(patterns) if patterns else ""
        anti_repetition = build_anti_repetition_section(recent_titles)
        
        # Track what context was used
        context_used = {
            "brand_profile": True,
            "learning_patterns": patterns is not None and patterns.get("has_enough_data", False),
            "anti_repetition_count": len(recent_titles),
            "content_style_brief": bool(profile.get("content_style_brief")),
        }
        
        # Build system prompt
        if wizard_mode == "video-ideas" and video_template:
            system_prompt = build_video_ideas_prompt(
                brand_brief, learning_section, anti_repetition, count, video_template,
                brand_stories=profile.get("brand_stories", ""),
            )
        else:
            system_prompt = build_ideas_system_prompt(
                brand_brief, learning_section, anti_repetition, count, wizard_mode
            )
        
        # Call LLM with retry
        try:
            ideas = await self._call_llm_with_retry(system_prompt, message, count)
        except Exception as e:
            logger.error(f"Ideas generation failed: {e}")
            raise IdeasGenerationError(str(e))
        
        # Post-filter: remove ideas too similar to recent titles
        ideas = self._filter_similar(ideas, recent_titles)
        
        # Post-filter: remove excluded ideas
        if exclude_ids:
            ideas = [i for i in ideas if i.get("id") not in set(exclude_ids)]
        
        # Ensure we have at least some ideas
        if not ideas:
            ideas = [{"id": str(uuid4()), "title": "Fresh content idea", "hook": "Something new", "angle": "creative", "content_type": "educational", "engagement_score": 0.5, "slides_suggestion": 5}]
        
        return {
            "ideas": ideas[:count],
            "reasoning": f"Generated {len(ideas)} ideas using brand context for {profile.get('brand_name', 'your brand')}",
            "message_id": str(uuid4()),
            "context_used": context_used,
            "recommended_music_id": _recommend_music_track(
                profile.get("brand_voice", ""),
                video_template or "",
            ),
        }

    async def _call_llm_with_retry(self, system_prompt: str, user_message: str, count: int) -> list[dict]:
        """Call LLM with retry at lower temperature on parse failure."""
        for attempt, temp in enumerate([0.7, 0.5]):
            try:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                    response_format={"type": "json_object"},
                    temperature=temp,
                    max_tokens=4096,
                    timeout=30,
                )
                
                content = response.choices[0].message.content
                if not content:
                    raise ValueError("LLM returned empty response")
                
                data = json.loads(content)
                
                # Handle both {ideas: [...]} and [...] formats
                if isinstance(data, list):
                    ideas_list = data
                elif isinstance(data, dict):
                    ideas_list = data.get("ideas", data.get("results", []))
                else:
                    raise ValueError(f"Unexpected response format: {type(data)}")
                
                # Ensure each idea has required fields and an ID
                validated = []
                for i, idea in enumerate(ideas_list[:count]):
                    validated.append({
                        "id": idea.get("id", str(uuid4())),
                        "title": idea.get("title", f"Idea {i+1}"),
                        "hook": idea.get("hook", idea.get("title", "")),
                        "angle": idea.get("angle", "creative"),
                        "content_type": idea.get("content_type", "educational"),
                        "engagement_score": min(max(float(idea.get("engagement_score", 0.5)), 0.0), 1.0),
                        "slides_suggestion": min(max(int(idea.get("slides_suggestion", 5)), 1), 10),
                    })
                
                return validated
                
            except json.JSONDecodeError as e:
                logger.warning(f"JSON parse failed (attempt {attempt+1}, temp {temp}): {e}")
                if attempt == 1:
                    raise
            except Exception as e:
                if attempt == 1:
                    raise
                logger.warning(f"LLM call failed (attempt {attempt+1}): {e}")
        
        raise IdeasGenerationError("All retry attempts failed")

    def _filter_similar(self, ideas: list[dict], recent_titles: list[str]) -> list[dict]:
        """Remove ideas too similar to recent titles using string similarity."""
        if not recent_titles:
            return ideas
        
        filtered = []
        for idea in ideas:
            title = idea.get("title", "").lower()
            is_similar = any(
                SequenceMatcher(None, title, existing.lower()).ratio() > SIMILARITY_THRESHOLD
                for existing in recent_titles
            )
            if not is_similar:
                filtered.append(idea)
            else:
                logger.debug(f"Filtered similar idea: {idea.get('title')}")
        
        return filtered
