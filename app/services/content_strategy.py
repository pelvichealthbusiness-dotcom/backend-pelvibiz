import json
import logging
from google.genai import types
from pydantic import BaseModel
from app.config import get_settings
from app.core.gemini_client import get_gemini_client
from app.services.brand_harmony import review_plan

logger = logging.getLogger(__name__)

class SlideContent(BaseModel):
    number: int
    text: str
    text_position: str  # "Top Center", "Center", "Bottom Center"
    gemini_prompt_context: str  # Additional context for Gemini prompt

class ContentPlan(BaseModel):
    slides: list[SlideContent]
    reply: str
    caption: str
    reasoning: str = ""

class ContentStrategyService:
    def __init__(self):
        settings = get_settings()
        self.client = get_gemini_client()
        self.model = settings.gemini_model_text

    async def plan(self, message: str, brand_profile: dict, slides_count: int) -> ContentPlan:
        """Use LLM to create intelligent content plan based on brand context."""
        try:
            return await self._llm_plan(message, brand_profile, slides_count)
        except Exception as e:
            logger.warning(f"LLM content strategy failed, using fallback: {e}")
            return self._fallback_plan(message, brand_profile, slides_count)

    async def _llm_plan(self, message: str, brand_profile: dict, slides_count: int) -> ContentPlan:
        system_prompt = self._build_system_prompt(brand_profile, slides_count)
        
        response = await self.client.aio.models.generate_content(
            model=self.model,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.7,
                max_output_tokens=2000,
                response_mime_type="application/json",
            ),
            contents=message,
        )

        content = response.text
        if not content:
            raise ValueError("LLM returned empty response")

        data = json.loads(content)

        # Validate and build ContentPlan
        slides = []
        for i, slide_data in enumerate(data.get("slides", [])[:slides_count], 1):
            slides.append(SlideContent(
                number=i,
                text=slide_data.get("text", f"Slide {i}"),
                text_position=slide_data.get("text_position", "Bottom Center"),
                gemini_prompt_context=slide_data.get("context", ""),
            ))
        
        # Fill remaining slides if LLM returned fewer
        while len(slides) < slides_count:
            n = len(slides) + 1
            slides.append(SlideContent(
                number=n,
                text=f"Slide {n}",
                text_position="Bottom Center",
                gemini_prompt_context="",
            ))

        reviewed = review_plan(brand_profile, {
            "slides": [s.model_dump() for s in slides],
            "reply": data.get("reply", "Your carousel is ready!"),
            "caption": data.get("caption", ""),
            "reasoning": data.get("reasoning", ""),
        })

        reviewed_slides = [
            SlideContent(
                number=s.get("number", i + 1),
                text=s.get("text", f"Slide {i + 1}"),
                text_position=s.get("text_position", "Bottom Center"),
                gemini_prompt_context=s.get("gemini_prompt_context", ""),
            )
            for i, s in enumerate(reviewed.get("slides", []))
        ]

        return ContentPlan(
            slides=reviewed_slides,
            reply=reviewed.get("reply", data.get("reply", "Your carousel is ready!")),
            caption=reviewed.get("caption", data.get("caption", "")),
            reasoning=reviewed.get("reasoning", data.get("reasoning", "")),
        )

    def _build_system_prompt(self, profile: dict, slides_count: int) -> str:
        brand_name = profile.get("brand_name") or "the brand"
        brand_voice = profile.get("brand_voice") or "professional and approachable"
        target_audience = profile.get("target_audience") or "general audience"
        services = profile.get("services_offered") or ""
        keywords = profile.get("keywords") or ""
        cta = profile.get("cta") or ""
        content_style = profile.get("content_style_brief") or ""
        color_primary = profile.get("brand_color_primary") or "#000000"
        color_secondary = profile.get("brand_color_secondary") or "#FFFFFF"
        cta_tone = cta or "warm, specific, low-friction, and on-brand"

        return f"""You are an expert social media content strategist for {brand_name}.

BRAND CONTEXT:
- Brand Voice: {brand_voice}
- Target Audience: {target_audience}
- Services: {services}
- Keywords: {keywords}
- CTA tone/rules: {cta_tone}
- Content Style: {content_style}
- Primary Color: {color_primary}
- Secondary Color: {color_secondary}

TASK: Create a {slides_count}-slide Instagram carousel content plan.

SLIDE ROLES (follow this narrative arc):
- Slide 1: HOOK — Attention-grabbing statement or question
- Slide 2: PROBLEM — Identify the pain point the audience faces
- Slide 3-{max(3, slides_count-2)}: SOLUTION/VALUE — Provide actionable tips, insights, or benefits
- Slide {slides_count-1}: BENEFIT — Show the transformation or result
- Slide {slides_count}: CTA — Call to action aligned with brand goals

TEXT RULES:
- Each slide text must be 5-15 words (short, punchy, scannable)
- Use the brand voice consistently
- Include relevant keywords naturally
- Text must work as standalone — each slide should make sense alone
- Use Sentence case (not ALL CAPS)

POSITION RULES:
- "Top Center": for slides where the main visual interest is in the lower half
- "Center": for slides with minimal visual detail or abstract backgrounds
- "Bottom Center": DEFAULT for most slides, works best with face/portrait photos

Return JSON with this EXACT structure:
{{
  "slides": [
    {{"text": "...", "text_position": "Bottom Center", "context": "brief note on this slide's role"}},
    ...
  ],
  "reply": "A friendly 1-2 sentence message to the user about what you created",
  "caption": "Instagram caption with hashtags (2-3 sentences + 5-10 hashtags)",
  "reasoning": "Brief explanation of your content strategy"
}}"""

    def _fallback_plan(self, message: str, brand_profile: dict, slides_count: int) -> ContentPlan:
        """Deterministic fallback when LLM is unavailable."""
        brand_name = brand_profile.get("brand_name") or "your brand"
        cta = brand_profile.get("cta") or "Learn more"
        
        roles = ["Hook", "Problem", "Solution", "Benefit", "CTA"]
        templates = [
            f"Discover {brand_name}",
            "The challenge you face",
            "Here's what works",
            "Transform your results",
            cta or "Take the next step",
        ]

        slides = []
        for i in range(slides_count):
            role_idx = min(i, len(templates) - 1)
            slides.append(SlideContent(
                number=i + 1,
                text=templates[role_idx] if i < len(templates) else f"Tip #{i + 1}",
                text_position="Bottom Center",
                gemini_prompt_context=roles[role_idx] if role_idx < len(roles) else "content",
            ))

        return ContentPlan(
            slides=slides,
            reply=f"Your {slides_count}-slide carousel for {brand_name} is ready!",
            caption=f"Elevate your {brand_name} journey ✨ #health #wellness #selfcare",
            reasoning="Fallback: LLM unavailable, using template-based content",
        )

    async def plan_ai(self, message: str, brand_profile: dict, slide_count: int, brand_stories: str = "") -> "AiContentPlan":
        """Use LLM to create AI carousel content plan with slide type decisions."""
        from app.models.ai_carousel import AiContentPlan, AiSlideContent, SlideType
        from app.prompts.ai_carousel_strategy import build_ai_strategy_prompt

        try:
            return await self._llm_plan_ai(message, brand_profile, slide_count, brand_stories)
        except Exception as e:
            logger.warning(f"LLM AI content strategy failed, using fallback: {e}")
            return self._fallback_plan_ai(message, brand_profile, slide_count)

    async def _llm_plan_ai(self, message: str, brand_profile: dict, slide_count: int, brand_stories: str = ""):
        from app.models.ai_carousel import AiContentPlan, AiSlideContent, SlideType
        from app.prompts.ai_carousel_strategy import build_ai_strategy_prompt

        system_prompt = build_ai_strategy_prompt(brand_profile, slide_count, brand_stories=brand_stories)

        response = await self.client.aio.models.generate_content(
            model=self.model,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.7,
                max_output_tokens=4096,
                response_mime_type="application/json",
            ),
            contents=message,
        )

        content = response.text
        if not content:
            raise ValueError("LLM returned empty response")

        data = json.loads(content)

        slides = []
        for i, s in enumerate(data.get("slides", [])[:slide_count], 1):
            raw_type = s.get("slide_type", "generic").lower()
            if raw_type == "face":
                slide_type = SlideType.FACE
            elif raw_type == "card":
                slide_type = SlideType.CARD
            else:
                slide_type = SlideType.GENERIC
            slides.append(AiSlideContent(
                number=i,
                slide_type=slide_type,
                text=s.get("text", f"Slide {i}"),
                text_position=s.get("text_position", "Bottom Center"),
                visual_prompt=s.get("visual_prompt", "") if slide_type in (SlideType.GENERIC, SlideType.FACE) else "",
            ))

        # Fill remaining if LLM returned fewer
        while len(slides) < slide_count:
            n = len(slides) + 1
            slides.append(AiSlideContent(
                number=n,
                slide_type=SlideType.CARD if n == slide_count else SlideType.GENERIC,
                text=f"Slide {n}",
                text_position="Center" if n == slide_count else "Bottom Center",
                visual_prompt="",
            ))

        reviewed = review_plan(brand_profile, {
            "slides": [
                {
                    "number": s.number,
                    "slide_type": s.slide_type.value,
                    "text": s.text,
                    "text_position": s.text_position,
                    "visual_prompt": s.visual_prompt,
                }
                for s in slides
            ],
            "reply": data.get("reply", "Your AI carousel is ready!"),
            "caption": data.get("caption", ""),
            "reasoning": data.get("reasoning", ""),
        })

        reviewed_slides = []
        for i, s in enumerate(reviewed.get("slides", [])):
            raw_type = s.get("slide_type", "generic").lower()
            from app.models.ai_carousel import SlideType, AiSlideContent
            slide_type = SlideType.FACE if raw_type == "face" else SlideType.CARD if raw_type == "card" else SlideType.GENERIC
            reviewed_slides.append(AiSlideContent(
                number=s.get("number", i + 1),
                slide_type=slide_type,
                text=s.get("text", f"Slide {i + 1}"),
                text_position=s.get("text_position", "Bottom Center"),
                visual_prompt=s.get("visual_prompt", "") if slide_type in (SlideType.GENERIC, SlideType.FACE) else "",
            ))

        return AiContentPlan(
            slides=reviewed_slides,
            reply=reviewed.get("reply", data.get("reply", "Your AI carousel is ready!")),
            caption=reviewed.get("caption", data.get("caption", "")),
            reasoning=reviewed.get("reasoning", data.get("reasoning", "")),
        )

    def _fallback_plan_ai(self, message: str, brand_profile: dict, slide_count: int):
        """Deterministic fallback for AI carousel planning."""
        from app.models.ai_carousel import AiContentPlan, AiSlideContent, SlideType

        brand_name = brand_profile.get("brand_name") or "your brand"
        cta = brand_profile.get("cta") or "Learn more"
        visual_env = brand_profile.get("visual_environment_setup") or "A professional, modern setting"

        slides = []
        for i in range(1, slide_count + 1):
            if i == 1:
                slides.append(AiSlideContent(number=i, slide_type=SlideType.GENERIC, text=f"Discover {brand_name}", text_position="Bottom Center", visual_prompt=visual_env))
            elif i == slide_count:
                slides.append(AiSlideContent(number=i, slide_type=SlideType.CARD, text=cta, text_position="Center", visual_prompt=""))
            else:
                slides.append(AiSlideContent(number=i, slide_type=SlideType.GENERIC, text=f"Tip #{i-1}", text_position="Bottom Center", visual_prompt=visual_env))

        return AiContentPlan(
            slides=slides,
            reply=f"Your {slide_count}-slide AI carousel for {brand_name} is ready!",
            caption=f"Transform your journey with {brand_name} ✨ #AI #content",
            reasoning="Fallback: LLM unavailable",
        )
