"""CarouselP2Agent — AI-generated Carousel via chat.

CHAT-405: Wraps the existing AI carousel generation pipeline behind a
conversational agent. Unlike P1 (real photos), P2 generates entire images
from AI using text-only Gemini prompts.

The agent uses Gemini function calling to trigger generation, then
delegates to the existing AiCarousel service layer.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import uuid
from typing import Any, AsyncGenerator

from app.agents.base import BaseStreamingAgent
from app.config import get_settings
from app.core.streaming import metadata_event
from app.services.brand import BrandService
from app.services.content_strategy import ContentStrategyService
from app.services.credits import CreditsService
from app.services.image_generator import ImageGeneratorService
from app.services.storage import StorageService
from app.dependencies import get_supabase_admin
from app.prompts.ai_carousel_generate import build_generic_slide_prompt, build_card_slide_prompt
from app.utils.image import force_resolution
from app.models.ai_carousel import SlideType

logger = logging.getLogger(__name__)


class CarouselP2Agent(BaseStreamingAgent):
    """Conversational agent for P2 AI Carousel generation.

    Uses Gemini to chat with the user, then generates full AI images
    (no user photos needed) with branded text overlays.
    """

    @property
    def system_prompt(self) -> str:
        return (
            "You are PelviBiz AI Carousel Creator, a professional Instagram carousel designer "
            "for health & wellness professionals.\n\n"
            "YOUR CAPABILITIES:\n"
            "- Create stunning Instagram carousel slides using AI-generated images\n"
            "- No user photos needed — you generate photorealistic scenes from descriptions\n"
            "- Each slide can be a photorealistic scene (generic/face) or a clean card design\n"
            "- You follow the brand's visual identity (colors, fonts, style)\n\n"
            "HOW YOU WORK:\n"
            "1. The user describes what carousel they want (topic, number of slides)\n"
            "2. You plan the content (text, slide types, visual prompts)\n"
            "3. You generate each slide with AI — no photos required\n\n"
            "SLIDE TYPES:\n"
            "- 'generic': Photorealistic AI-generated scene with text overlay\n"
            "- 'card': Clean minimal card with text on solid/gradient background\n"
            "- 'face': Like generic but includes a person (uses brand's subject description)\n\n"
            "IMPORTANT RULES:\n"
            "- When the user wants to CREATE a carousel, call `generate_ai_carousel`\n"
            "- When the user wants to FIX a slide, call `fix_slide`\n"
            "- Keep responses concise and action-oriented\n"
            "- Suggest a mix of generic + card slides for visual variety\n\n"
            "You speak in a warm, professional tone."
        )

    @property
    def model(self) -> str:
        return get_settings().gemini_model_default

    @property
    def temperature(self) -> float:
        return 0.7

    @property
    def max_tokens(self) -> int:
        return 4096

    @property
    def tools(self) -> list:
        """Define Gemini function calling tools for AI carousel operations."""
        from google.genai import types

        generate_ai_carousel = types.FunctionDeclaration(
            name="generate_ai_carousel",
            description=(
                "Generate a full AI Instagram carousel with AI-generated images. "
                "No user photos needed. Call this when the user wants to create a carousel."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "message": types.Schema(
                        type="STRING",
                        description="Description of what the carousel should be about",
                    ),
                    "slide_count": types.Schema(
                        type="INTEGER",
                        description="Number of slides to generate (1-10, default 5)",
                    ),
                },
                required=["message"],
            ),
        )

        fix_slide = types.FunctionDeclaration(
            name="fix_slide",
            description=(
                "Fix a single slide from an existing AI carousel. "
                "Regenerates the slide with updated text or visual prompt."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "row_id": types.Schema(
                        type="STRING",
                        description="ID of the carousel in the database",
                    ),
                    "slide_number": types.Schema(
                        type="INTEGER",
                        description="Which slide to fix (1-based index)",
                    ),
                    "new_text": types.Schema(
                        type="STRING",
                        description="New text content for the slide",
                    ),
                    "slide_type": types.Schema(
                        type="STRING",
                        description="Slide type: generic, card, or face",
                    ),
                },
                required=["row_id", "slide_number"],
            ),
        )

        return [types.Tool(function_declarations=[generate_ai_carousel, fix_slide])]

    async def execute_tool(
        self, name: str, args: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any]:
        """Execute AI carousel tools by delegating to existing services."""
        user_id = kwargs.get("user_id", self.user_id)

        if name == "generate_ai_carousel":
            return await self._generate_ai_carousel(user_id, args)
        elif name == "fix_slide":
            return await self._fix_slide(user_id, args)
        else:
            return {"error": f"Unknown tool: {name}"}

    # ------------------------------------------------------------------
    # Tool: generate_ai_carousel
    # ------------------------------------------------------------------

    async def _generate_ai_carousel(
        self, user_id: str, args: dict[str, Any]
    ) -> dict[str, Any]:
        """Generate a full AI carousel using the existing pipeline."""
        message = args.get("message", "Create a carousel")
        slide_count = args.get("slide_count", 5)
        settings = get_settings()

        try:
            credits_service = CreditsService()
            await credits_service.check_credits(user_id)

            brand_service = BrandService()
            profile = await brand_service.load_profile(user_id)

            # Use LLM to plan AI carousel content
            strategy_service = ContentStrategyService()
            # Load brand stories for strategy context
            try:
                from app.services.stories_service import load_user_stories
                _stories_list = await load_user_stories(user_id)
                _story_context = " | ".join([
                    f"{s.get('title', '')}: {s.get('content', '')[:180]}"
                    for s in _stories_list[:2] if s.get("content")
                ]) if _stories_list else ""
            except Exception as _se:
                import logging as _logging
                _logging.getLogger(__name__).warning("Could not load brand stories: %s", _se)
                _story_context = ""
            content_plan = await strategy_service.plan_ai(
                message=message,
                brand_profile=profile,
                slide_count=slide_count,
                brand_stories=_story_context,
            )

            # Generate slides
            image_gen = ImageGeneratorService()
            storage = StorageService()
            semaphore = asyncio.Semaphore(settings.p2_gemini_concurrency)

            media_urls: list[str] = []
            failed_slides: list[int] = []
            slides_detail: list[dict] = []
            slide_types: list[str] = []

            async def generate_single(slide):
                async with semaphore:
                    try:
                        if slide.slide_type in (SlideType.GENERIC, SlideType.FACE):
                            prompt = build_generic_slide_prompt(
                                visual_prompt=slide.visual_prompt,
                                text=slide.text,
                                text_position=slide.text_position,
                                font_prompt=profile.get("font_prompt", "Clean, bold, geometric sans-serif"),
                                font_style="editorial-mixed",
                                font_size=profile.get("font_size", "38px"),
                                color_primary=profile.get("brand_color_primary", "#000000"),
                                color_secondary=profile.get("brand_color_secondary", "#FFFFFF"),
                                subject_description=profile.get("visual_subject_outfit_generic", ""),
                            )
                        else:
                            prompt = build_card_slide_prompt(
                                text=slide.text,
                                text_position=slide.text_position or "Center",
                                font_prompt=profile.get("font_prompt", "Clean, bold, geometric sans-serif"),
                                font_style="editorial-mixed",
                                font_size=profile.get("font_size", "42px"),
                                color_primary=profile.get("brand_color_primary", "#000000"),
                                color_secondary=profile.get("brand_color_secondary", "#FFFFFF"),
                            )

                        generated_base64 = await image_gen.generate_from_prompt(prompt)
                        image_bytes = base64.b64decode(generated_base64)
                        image_bytes = force_resolution(image_bytes)

                        upload_base64 = base64.b64encode(image_bytes).decode("utf-8")
                        public_url = await storage.upload_image(upload_base64, user_id)

                        return (slide.number, public_url, slide.slide_type.value, slide.text, "success", None)
                    except Exception as e:
                        logger.error("AI slide %d failed: %s", slide.number, e)
                        return (slide.number, None, slide.slide_type.value, slide.text, "failed", str(e))

            tasks = [generate_single(s) for s in content_plan.slides]
            results = await asyncio.gather(*tasks)

            for number, url, stype, text, status, error in sorted(results, key=lambda x: x[0]):
                slide_types.append(stype)
                if url:
                    media_urls.append(url)
                    slides_detail.append({
                        "number": number,
                        "text": text,
                        "slide_type": stype,
                        "url": url,
                        "status": "success",
                    })
                else:
                    failed_slides.append(number)
                    slides_detail.append({
                        "number": number,
                        "text": text,
                        "slide_type": stype,
                        "status": "failed",
                        "error": error,
                    })

            if not media_urls:
                return {
                    "error": "All AI slides failed to generate",
                    "failed_slides": failed_slides,
                }

            # Save to requests_log
            message_id = str(uuid.uuid4())
            supabase = get_supabase_admin()
            _saved = False
            try:
                supabase.table("requests_log").upsert(
                    {
                        "id": message_id,
                        "user_id": user_id,
                        "agent_type": "ai-carousel",
                        "title": message,
                        "reply": content_plan.reply,
                        "caption": content_plan.caption,
                        "media_urls": media_urls,
                        "published": False,
                    },
                    on_conflict="id",
                ).execute()
                _saved = True
            except Exception as e:
                logger.error("Failed to save to requests_log: %s", e)

            if _saved:
                try:
                    await credits_service.increment_credits(user_id, "ai-carousel")
                except Exception as e:
                    logger.error("Failed to increment credits: %s", e)

            return {
                "status": "success",
                "reply": content_plan.reply,
                "caption": content_plan.caption,
                "media_urls": media_urls,
                "message_id": message_id,
                "slides": slides_detail,
                "slide_types": slide_types,
                "failed_slides": failed_slides,
            }

        except Exception as e:
            logger.error("AI carousel generation failed: %s", e, exc_info=True)
            return {"error": str(e), "status": "failed"}

    # ------------------------------------------------------------------
    # Tool: fix_slide
    # ------------------------------------------------------------------

    async def _fix_slide(
        self, user_id: str, args: dict[str, Any]
    ) -> dict[str, Any]:
        """Fix a single slide from an existing AI carousel."""
        from app.prompts.ai_carousel_fix import build_ai_fix_generic_prompt, build_ai_fix_card_prompt

        row_id = args.get("row_id")
        slide_number = args.get("slide_number", 1)
        new_text = args.get("new_text")
        slide_type_str = args.get("slide_type", "generic")

        if not row_id:
            return {"error": "row_id is required for fixing a slide"}

        try:
            brand_service = BrandService()
            profile = await brand_service.load_profile(user_id)

            supabase = get_supabase_admin()
            result = (
                supabase.table("requests_log")
                .select("id, media_urls, user_id, metadata, title")
                .eq("id", row_id)
                .single()
                .execute()
            )

            if not result.data:
                return {"error": f"Row {row_id} not found"}
            if result.data.get("user_id") != user_id:
                return {"error": "You don't own this carousel"}

            original_urls = result.data.get("media_urls", []) or []
            topic = result.data.get("title", "") or ""
            slide_idx = slide_number - 1
            if slide_idx < 0 or slide_idx >= len(original_urls):
                return {
                    "error": f"Slide {slide_number} out of range (1-{len(original_urls)})"
                }

            # Determine slide type
            try:
                slide_type = SlideType(slide_type_str)
            except ValueError:
                slide_type = SlideType.GENERIC

            if slide_type in (SlideType.GENERIC, SlideType.FACE):
                prompt = build_ai_fix_generic_prompt(
                    original_prompt="",
                    new_text=new_text,
                    font_prompt=profile.get("font_prompt", "Sans-serif"),
                    font_style="editorial-mixed",
                    color_primary=profile.get("brand_color_primary", "#000000"),
                    color_secondary=profile.get("brand_color_secondary", "#FFFFFF"),
                    topic=topic,
                )
            else:
                prompt = build_ai_fix_card_prompt(
                    new_text=new_text,
                    font_prompt=profile.get("font_prompt", "Sans-serif"),
                    font_style="editorial-mixed",
                    color_primary=profile.get("brand_color_primary", "#000000"),
                    color_secondary=profile.get("brand_color_secondary", "#FFFFFF"),
                    topic=topic,
                )

            image_gen = ImageGeneratorService()
            generated_base64 = await image_gen.generate_from_prompt(prompt)

            image_bytes = base64.b64decode(generated_base64)
            image_bytes = force_resolution(image_bytes)

            storage = StorageService()
            upload_base64 = base64.b64encode(image_bytes).decode("utf-8")
            public_url = await storage.upload_image(upload_base64, user_id)

            updated_urls = list(original_urls)
            updated_urls[slide_idx] = public_url

            try:
                supabase.table("requests_log").update(
                    {"media_urls": updated_urls}
                ).eq("id", row_id).execute()
            except Exception as e:
                logger.error("Failed to update requests_log: %s", e)

            return {
                "status": "success",
                "media_urls": updated_urls,
                "fixed_slide": slide_number,
                "new_url": public_url,
            }

        except Exception as e:
            logger.error("AI fix slide failed: %s", e, exc_info=True)
            return {"error": str(e), "status": "failed"}
