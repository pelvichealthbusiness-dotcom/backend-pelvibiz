import json
import logging
from openai import AsyncOpenAI
from app.config import get_settings
from app.prompts.profile_generate import build_profile_generation_prompt, build_field_regeneration_prompt, resolve_category
from app.models.brand import REGENERABLE_FIELDS
from app.services.exceptions import ProfileGenerationError, InvalidFieldError
from app.services.brand_context import build_brand_context_pack

logger = logging.getLogger(__name__)

class ProfileEngine:
    def __init__(self):
        settings = get_settings()
        self.client = AsyncOpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
        )
        self.model = settings.llm_model

    async def generate_profile(self, input_data: dict) -> dict:
        """Generate a complete brand profile from minimal input."""
        niche = input_data.get("niche", "")
        services = input_data.get("services_description", "")
        content_goals = input_data.get("content_goals", [])

        # Resolve business category
        category = resolve_category(niche, services)

        # Build system prompt
        system_prompt = build_profile_generation_prompt(niche, content_goals, category)

        # Build user message
        user_msg = self._build_user_message(input_data)

        try:
            return await self._call_llm_with_retry(system_prompt, user_msg, input_data)
        except Exception as e:
            logger.error(f"Profile generation failed: {e}")
            raise ProfileGenerationError(str(e))

    async def regenerate_field(self, field_name: str, current_profile: dict, instruction: str) -> dict:
        """Regenerate a single profile field with user instruction."""
        if field_name not in REGENERABLE_FIELDS:
            raise InvalidFieldError(field_name)

        old_value = current_profile.get(field_name, "")
        system_prompt = build_field_regeneration_prompt(field_name, current_profile, instruction)

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Regenerate the {field_name} field. Instruction: {instruction}"},
                ],
                temperature=0.6,
                max_tokens=1000,
                timeout=30,
            )

            new_value = response.choices[0].message.content or ""
            new_value = new_value.strip().strip('"').strip("'")

            return {
                "field_name": field_name,
                "old_value": old_value or "",
                "new_value": new_value,
                "reasoning": f"Adjusted {field_name} based on instruction: {instruction}",
            }
        except Exception as e:
            logger.error(f"Field regeneration failed: {e}")
            raise ProfileGenerationError(f"Failed to regenerate {field_name}: {e}")

    async def _call_llm_with_retry(self, system_prompt: str, user_msg: str, input_data: dict) -> dict:
        """Call LLM with retry at lower temperature on parse failure."""
        for attempt, temp in enumerate([0.6, 0.4]):
            try:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_msg},
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
                return self._build_response(data, input_data)

            except json.JSONDecodeError as e:
                logger.warning(f"JSON parse failed (attempt {attempt+1}, temp {temp}): {e}")
                if attempt == 1:
                    raise
            except Exception as e:
                if attempt == 1:
                    raise
                logger.warning(f"LLM call failed (attempt {attempt+1}): {e}")

        raise ProfileGenerationError("All retry attempts failed")

    def _value(self, data: dict, field: str, fallback: str = "") -> str:
        value = data.get(field, "")
        if isinstance(value, dict):
            value = value.get("value", "")
        if isinstance(value, str) and value.strip():
            return value.strip()
        return fallback

    def _build_brand_playbook(self, data: dict, input_data: dict) -> str:
        merged = {**input_data, **data}
        return build_brand_context_pack(merged)["brand_brief"]

    def _build_user_message(self, input_data: dict) -> str:
        parts = [f"Brand Name: {input_data.get('brand_name', 'Unknown')}"]
        if input_data.get("services_description"):
            parts.append(f"Services: {input_data['services_description']}")
        if input_data.get("personal_preferences"):
            parts.append(f"Preferences: {input_data['personal_preferences']}")
        if input_data.get("brand_color_primary"):
            parts.append(f"Primary Color: {input_data['brand_color_primary']}")
        if input_data.get("brand_color_secondary"):
            parts.append(f"Secondary Color: {input_data['brand_color_secondary']}")
        if input_data.get("niche"):
            parts.append(f"Niche: {input_data['niche']}")
        if input_data.get("content_goals"):
            parts.append(f"Content Goals: {', '.join(input_data['content_goals'])}")
        return "\n".join(parts)

    def _build_response(self, data: dict, input_data: dict) -> dict:
        """Build response with confidence scores."""
        # Calculate confidence based on input richness
        input_richness = sum([
            bool(input_data.get("brand_name")),
            bool(input_data.get("services_description")),
            bool(input_data.get("personal_preferences")),
            bool(input_data.get("niche")),
            len(input_data.get("content_goals", [])) > 0,
            bool(input_data.get("brand_color_primary") and input_data["brand_color_primary"] != "#000000"),
        ])
        base_confidence = 0.70 + (input_richness / 6) * 0.25  # 0.70 to 0.95

        fields = [
            "brand_voice", "target_audience", "services_offered", "visual_identity",
            "keywords", "cta", "content_style_brief", "visual_environment_setup",
            "visual_subject_outfit_face", "visual_subject_outfit_generic",
            "font_style", "font_prompt",
        ]

        result = {}
        for field in fields:
            value = data.get(field, "")
            if isinstance(value, dict):
                value = value.get("value", str(value))
            result[field] = {
                "value": str(value) if value else "",
                "confidence": round(base_confidence, 2) if value else 0.5,
            }

        result["brand_playbook"] = {
            "value": self._build_brand_playbook(data, input_data),
            "confidence": round(base_confidence, 2),
        }

        return result
