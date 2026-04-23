"""CarouselP1Agent — Real Photo Carousel generation via chat.

CHAT-404: Wraps the existing carousel generation pipeline (brand profile,
content strategy, Gemini image generation) behind a conversational agent
that streams progress via the Vercel AI SDK protocol.

The agent operates in conversational mode — it chats with the user about
their carousel needs. Actual slide generation is triggered when the user
provides image URLs, at which point the agent calls the existing service
layer and streams progress as metadata events.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, AsyncGenerator

from app.agents.base import BaseStreamingAgent
from app.config import get_settings
from app.core.streaming import (
    metadata_event,
    text_chunk,
    finish_event,
    error_event,
)
import base64

from app.services.brand import BrandService
from app.services.content_strategy import ContentStrategyService
from app.services.credits import CreditsService
from app.services.slide_renderer import SlideRenderer
from app.services.storage import StorageService
from app.dependencies import get_supabase_admin

logger = logging.getLogger(__name__)


class CarouselP1Agent(BaseStreamingAgent):
    """Conversational agent for P1 Real Photo Carousel generation.

    Uses Gemini to chat with the user about their carousel needs, then
    delegates to the existing carousel service pipeline for generation.
    """

    @property
    def system_prompt(self) -> str:
        return (
            "You are PelviBiz Carousel Creator, a professional Instagram carousel designer "
            "for health & wellness professionals.\n\n"
            "YOUR CAPABILITIES:\n"
            "- Create stunning Instagram carousel slides using real photos with text overlays\n"
            "- Each slide gets a branded text overlay on top of the user's photo\n"
            "- You follow the brand's visual identity (colors, fonts, style)\n\n"
            "HOW YOU WORK:\n"
            "1. The user describes what carousel they want (topic, number of slides, etc.)\n"
            "2. You plan the content strategy (hook, problem, solution, CTA)\n"
            "3. You generate each slide with branded text overlays on their real photos\n\n"
            "IMPORTANT RULES:\n"
            "- When the user wants to CREATE a carousel, call the `generate_carousel` tool "
            "with their message and image URLs\n"
            "- When the user wants to FIX a specific slide, call the `fix_slide` tool\n"
            "- P1 carousels REQUIRE real photos uploaded by the user\n"
            "- If no images are provided, ask the user to upload photos first\n"
            "- Keep responses concise and action-oriented\n\n"
            "RESPONSE FORMAT:\n"
            "- Brief acknowledgment of the request\n"
            "- Summary of what you will create\n"
            "- Then call the appropriate tool to generate\n"
            "- After generation, present results with the caption\n\n"
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
        """Define Gemini function calling tools for carousel operations."""
        from google.genai import types

        generate_carousel = types.FunctionDeclaration(
            name="generate_carousel",
            description=(
                "Generate a full Instagram carousel with branded text overlays on real photos. "
                "Call this when the user wants to create a new carousel."
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
                    "image_urls": types.Schema(
                        type="ARRAY",
                        items=types.Schema(type="STRING"),
                        description="URLs of user-uploaded photos for each slide",
                    ),
                },
                required=["message"],
            ),
        )

        fix_slide = types.FunctionDeclaration(
            name="fix_slide",
            description=(
                "Fix a single slide from an existing carousel. "
                "Call this when the user wants to change text or image on a specific slide."
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
                        description="New text content for the slide (optional)",
                    ),
                    "new_image_url": types.Schema(
                        type="STRING",
                        description="URL of the new image for the slide",
                    ),
                },
                required=["row_id", "slide_number", "new_image_url"],
            ),
        )

        return [types.Tool(function_declarations=[generate_carousel, fix_slide])]

    async def execute_tool(
        self, name: str, args: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any]:
        """Execute carousel tools by delegating to existing services."""
        user_id = kwargs.get("user_id", self.user_id)

        if name == "generate_carousel":
            return await self._generate_carousel(user_id, args)
        elif name == "fix_slide":
            return await self._fix_slide(user_id, args)
        else:
            return {"error": f"Unknown tool: {name}"}

    # ------------------------------------------------------------------
    # Tool: generate_carousel
    # ------------------------------------------------------------------

    async def _generate_carousel(
        self, user_id: str, args: dict[str, Any]
    ) -> dict[str, Any]:
        """Generate a full carousel using the existing pipeline."""
        message = args.get("message", "Create a carousel")
        slide_count = args.get("slide_count", 5)
        image_urls = args.get("image_urls", [])

        if not image_urls:
            return {
                "error": (
                    "No images provided. P1 Real Carousel requires user-uploaded photos. "
                    "Please upload images and try again."
                ),
                "status": "missing_images",
            }

        try:
            credits_service = CreditsService()
            await credits_service.check_credits(user_id)

            brand_service = BrandService()
            profile = await brand_service.load_profile(user_id)

            strategy_service = ContentStrategyService()
            content_plan = await strategy_service.plan(
                message=message,
                brand_profile=profile,
                slides_count=min(slide_count, len(image_urls)),
            )

            storage = StorageService()
            media_urls: list[str] = []
            failed_slides: list[int] = []
            slides_detail: list[dict] = []

            for i in range(min(slide_count, len(image_urls))):
                slide_content = (
                    content_plan.slides[i] if i < len(content_plan.slides) else None
                )
                slide_text = slide_content.text if slide_content else f"Slide {i + 1}"
                slide_position = (
                    slide_content.text_position if slide_content else "Bottom Center"
                )

                try:
                    renderer = SlideRenderer()
                    image_bytes = await renderer.download_image(image_urls[i])
                    if not image_bytes:
                        raise Exception(f"Failed to download image from {image_urls[i]}")
                    slide_bytes = renderer.render_slide(
                        image_bytes=image_bytes,
                        text=slide_text,
                        position=slide_position,
                        font_style=profile.get("font_style", "editorial-mixed"),
                        color_primary=profile.get("brand_color_primary", "#000000"),
                        color_secondary=profile.get("brand_color_secondary", "#FFFFFF"),
                        color_background=profile.get("brand_color_background"),
                        slide_index=i,
                    )
                    generated_base64 = base64.b64encode(slide_bytes).decode()
                    public_url = await storage.upload_image(generated_base64, user_id)
                    media_urls.append(public_url)
                    slides_detail.append({
                        "number": i + 1,
                        "text": slide_text,
                        "url": public_url,
                        "status": "success",
                    })
                except Exception as e:
                    logger.error("Slide %d failed: %s", i + 1, e)
                    failed_slides.append(i + 1)
                    slides_detail.append({
                        "number": i + 1,
                        "text": slide_text,
                        "status": "failed",
                        "error": str(e),
                    })

            if not media_urls:
                return {
                    "error": "All slides failed to generate",
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
                        "agent_type": "real-carousel",
                        "title": "Generated Carousel",
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
                    await credits_service.increment_credits(user_id, "real-carousel")
                except Exception as e:
                    logger.error("Failed to increment credits: %s", e)

            return {
                "status": "success",
                "reply": content_plan.reply,
                "caption": content_plan.caption,
                "media_urls": media_urls,
                "message_id": message_id,
                "slides": slides_detail,
                "failed_slides": failed_slides,
            }

        except Exception as e:
            logger.error("Carousel generation failed: %s", e, exc_info=True)
            return {"error": str(e), "status": "failed"}

    # ------------------------------------------------------------------
    # Tool: fix_slide
    # ------------------------------------------------------------------

    async def _fix_slide(
        self, user_id: str, args: dict[str, Any]
    ) -> dict[str, Any]:
        """Fix a single slide from an existing carousel."""
        row_id = args.get("row_id")
        slide_number = args.get("slide_number", 1)
        new_text = args.get("new_text")
        new_image_url = args.get("new_image_url")

        if not row_id or not new_image_url:
            return {"error": "row_id and new_image_url are required for fixing a slide"}

        try:
            brand_service = BrandService()
            profile = await brand_service.load_profile(user_id)

            supabase = get_supabase_admin()
            result = (
                supabase.table("requests_log")
                .select("id, media_urls, user_id, title")
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

            renderer = SlideRenderer()
            storage = StorageService()

            image_bytes = await renderer.download_image(new_image_url)
            if not image_bytes:
                return {"error": f"Failed to download image from {new_image_url}"}
            slide_bytes = renderer.render_slide(
                image_bytes=image_bytes,
                text=new_text or topic or "Fixed Slide",
                position="Bottom Center",
                font_style=profile.get("font_style", "editorial-mixed"),
                color_primary=profile.get("brand_color_primary", "#000000"),
                color_secondary=profile.get("brand_color_secondary", "#FFFFFF"),
                color_background=profile.get("brand_color_background"),
            )
            generated_base64 = base64.b64encode(slide_bytes).decode()
            public_url = await storage.upload_image(generated_base64, user_id)

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
            logger.error("Fix slide failed: %s", e, exc_info=True)
            return {"error": str(e), "status": "failed"}
