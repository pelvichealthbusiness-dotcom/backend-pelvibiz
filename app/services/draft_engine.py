import json
import logging
from openai import AsyncOpenAI
from app.config import get_settings
from app.services.brand import BrandService
from app.services.brand_harmony import review_plan
from app.services.learning import LearningService
from app.prompts.draft_generate import build_draft_system_prompt, build_video_draft_system_prompt, strip_extra_hashtags
from app.prompts.ideas_generate import build_learning_section

logger = logging.getLogger(__name__)


def _sanitize_json(raw: str) -> str:
    """Replace unescaped control characters inside JSON string values.

    LLMs sometimes output literal newlines (\x0a) inside JSON strings
    instead of the escaped sequence \\n, producing invalid JSON.
    This walks the string character-by-character, tracking string context,
    and replaces any bare control characters with their JSON escape sequences.
    """
    result: list[str] = []
    in_string = False
    escaped = False

    for ch in raw:
        if escaped:
            result.append(ch)
            escaped = False
        elif ch == '\\' and in_string:
            result.append(ch)
            escaped = True
        elif ch == '"':
            in_string = not in_string
            result.append(ch)
        elif in_string and ch == '\n':
            result.append('\\n')
        elif in_string and ch == '\r':
            result.append('\\r')
        elif in_string and ch == '\t':
            result.append('\\t')
        elif in_string and ord(ch) < 32:
            result.append(f'\\u{ord(ch):04x}')
        else:
            result.append(ch)

    return ''.join(result)


class DraftEngine:
    """Generates carousel slide text + caption, or video text fields + caption."""

    def __init__(self):
        settings = get_settings()
        self.client = AsyncOpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
        )
        self.model = settings.llm_model
        self.brand_service = BrandService()
        self.learning_service = LearningService()

    async def generate_draft(
        self,
        user_id: str,
        topic: str,
        slide_count: int,
        agent_type: str = "real-carousel",
    ) -> dict:
        """Generate carousel slide text + caption for a given topic."""
        print(f"DEBUG DraftEngine.generate_draft called with slide_count={slide_count}", flush=True)
        profile = await self.brand_service.load_profile(user_id)
        patterns = await self.learning_service.get_patterns(user_id)

        system_prompt = build_draft_system_prompt(profile, slide_count)

        # Add learning context if available
        if patterns and patterns.get("has_enough_data"):
            learning_section = build_learning_section(patterns)
            if learning_section:
                system_prompt += f"\n\n## User Preferences (from past behavior)\n{learning_section}"

        user_message = f"Create a {slide_count}-slide carousel about: \"{topic}\""

        try:
            return await self._call_llm(system_prompt, user_message, slide_count, profile)
        except Exception as e:
            logger.warning(f"Draft LLM failed, using fallback: {e}")
            return self._fallback_draft(topic, slide_count, profile)

    # Default field definitions per template key (used when frontend sends empty text_fields)
    _DEFAULT_TEXT_FIELDS: dict[str, list[dict]] = {
        "myth-buster": [
            {"key": "text_1", "label": "Hook", "maxLength": 80},
            {"key": "text_2", "label": "Myth", "maxLength": 80},
            {"key": "text_3", "label": "Truth", "maxLength": 80},
            {"key": "text_4", "label": "CTA", "maxLength": 60},
        ],
        "bullet-sequence": [
            {"key": "text_1", "label": "Hook", "maxLength": 80},
            {"key": "text_2", "label": "Bullet 1", "maxLength": 80},
            {"key": "text_3", "label": "Bullet 2", "maxLength": 80},
            {"key": "text_4", "label": "Bullet 3", "maxLength": 80},
            {"key": "text_5", "label": "Conclusion", "maxLength": 80},
            {"key": "text_6", "label": "CTA", "maxLength": 60},
        ],
        "big-quote": [
            {"key": "text_1", "label": "Quote", "maxLength": 150},
        ],
        "deep-dive": [
            {"key": "text_1", "label": "Title", "maxLength": 80},
            {"key": "text_2", "label": "Statement 1", "maxLength": 80},
            {"key": "text_3", "label": "Statement 2", "maxLength": 80},
            {"key": "text_4", "label": "Statement 3", "maxLength": 80},
            {"key": "text_5", "label": "Statement 4", "maxLength": 80},
            {"key": "text_6", "label": "Statement 5", "maxLength": 80},
            {"key": "text_7", "label": "Statement 6", "maxLength": 80},
            {"key": "text_8", "label": "Statement 7", "maxLength": 80},
        ],
    }

    async def generate_video_draft(
        self,
        user_id: str,
        topic: str,
        template_key: str,
        template_label: str,
        text_fields: list[dict],
    ) -> dict:
        # Use default fields if none provided (older frontend versions)
        if not text_fields and template_key in self._DEFAULT_TEXT_FIELDS:
            text_fields = self._DEFAULT_TEXT_FIELDS[template_key]
        """Generate video text fields + caption for a given topic and template."""
        profile = await self.brand_service.load_profile(user_id)
        patterns = await self.learning_service.get_patterns(user_id)

        system_prompt = build_video_draft_system_prompt(
            profile, template_key, template_label, text_fields
        )

        if patterns and patterns.get("has_enough_data"):
            learning_section = build_learning_section(patterns)
            if learning_section:
                system_prompt += f"\n\n## User Preferences\n{learning_section}"

        user_message = f"Create content for a \"{template_label}\" video about: \"{topic}\""

        try:
            return await self._call_llm_video(system_prompt, user_message, text_fields, profile)
        except Exception as e:
            logger.warning(f"Video draft LLM failed: {e}")
            return self._fallback_video_draft(topic, text_fields)

    async def _call_llm(
        self, system_prompt: str, user_message: str, slide_count: int, profile: dict
    ) -> dict:
        """Call LLM with retry at lower temperature on parse failure."""
        print(f"DEBUG _call_llm called with slide_count={slide_count}", flush=True)
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
                    raise ValueError("Empty response")

                data = json.loads(_sanitize_json(content))
                slides = data.get("slides", [])

                # Validate and normalize
                normalized_slides = []
                for i, s in enumerate(slides[:slide_count], 1):
                    normalized_slides.append({
                        "number": s.get("number", i),
                        "text": s.get("text", f"Slide {i}"),
                    })

                while len(normalized_slides) < slide_count:
                    n = len(normalized_slides) + 1
                    normalized_slides.append({"number": n, "text": f"Slide {n}"})

                reviewed = review_plan(profile, {
                    "slides": normalized_slides,
                    "caption": data.get("caption", ""),
                })

                reviewed_slides = [
                    {"number": s.get("number", i + 1), "text": s.get("text", f"Slide {i + 1}")}
                    for i, s in enumerate(reviewed.get("slides", []))
                ]

                return {
                    "slides": reviewed_slides,
                    "caption": strip_extra_hashtags(reviewed["caption"]),
                }
            except json.JSONDecodeError:
                if attempt == 1:
                    raise
                logger.warning(
                    f"Draft JSON parse failed (attempt {attempt + 1}), retrying at lower temp"
                )
        raise ValueError("All attempts failed")

    async def _call_llm_video(
        self, system_prompt: str, user_message: str, text_fields: list[dict], profile: dict
    ) -> dict:
        """Call LLM for video draft with retry."""
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
                    raise ValueError("Empty response")
                # Use raw_decode to parse only the first valid JSON object,
                # ignoring any extra text or second JSON the LLM appended after it.
                sanitized = _sanitize_json(content).lstrip()
                start = sanitized.find('{')
                if start == -1:
                    raise json.JSONDecodeError('No JSON object found', sanitized, 0)
                obj, _ = json.JSONDecoder().raw_decode(sanitized, start)
                return review_plan(profile, obj)
            except json.JSONDecodeError:
                if attempt == 1:
                    raise
                logger.warning(
                    f"Video draft JSON parse failed (attempt {attempt + 1}), retrying"
                )
        raise ValueError("All attempts failed")

    def _fallback_draft(self, topic: str, slide_count: int, profile: dict) -> dict:
        """Fallback draft when LLM fails."""
        brand_name = profile.get("brand_name") or "your brand"
        cta = profile.get("cta") or "Learn more"
        slides = [{"number": 1, "text": f"The truth about {topic}"}]
        for i in range(2, slide_count):
            slides.append({"number": i, "text": f"Key insight #{i - 1}"})
        slides.append({"number": slide_count, "text": cta})
        return {
            "slides": slides,
            "caption": f"Discover more about {topic} with {brand_name}",
        }

    def _fallback_video_draft(self, topic: str, text_fields: list[dict]) -> dict:
        """Fallback video draft when LLM fails."""
        result: dict = {"caption": f"Watch this about {topic}"}
        texts: dict = {}
        for f in text_fields:
            texts[f.get("key", "text")] = f"Content about {topic}"
        result["texts"] = texts
        return result
