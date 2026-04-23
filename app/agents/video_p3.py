"""VideoP3Agent — Video/Reels generation via chat.

CHAT-406: Wraps the existing video generation pipeline (Creatomate templates,
video analysis) behind a conversational agent that streams progress via the
Vercel AI SDK protocol.

The agent uses Gemini to chat with the user about their video needs, then
delegates to the existing Creatomate service for rendering, streaming
progress updates as metadata events (prefix 2:).
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, AsyncGenerator

import httpx

from app.agents.base import BaseStreamingAgent
from app.config import get_settings
from app.core.streaming import metadata_event
from app.services.brand import BrandService
from app.services.credits import CreditsService
from app.services.creatomate import CreatomateService
from app.services.storage import StorageService
from app.services.video_analysis import VideoAnalysisService
from app.dependencies import get_supabase_admin
from app.models.video import VideoTemplate, TEMPLATE_CONFIG
from app.templates.creatomate_mappings import TEMPLATE_MAPPERS, ANALYSIS_MAPPERS

logger = logging.getLogger(__name__)


class VideoP3Agent(BaseStreamingAgent):
    """Conversational agent for P3 Video/Reels generation.

    Uses Gemini to chat with the user about their video needs, then
    delegates to Creatomate for rendering with progress streaming.
    """

    @property
    def system_prompt(self) -> str:
        return (
            "You are PelviBiz Video Creator, a professional Instagram Reels/video designer "
            "for health & wellness professionals.\n\n"
            "YOUR CAPABILITIES:\n"
            "- Create professional short-form videos (Reels/TikTok) using templates\n"
            "- Available templates: myth-buster, bullet-sequence, viral-reaction, "
            "testimonial-story, big-quote, deep-dive\n"
            "- Each template has specific requirements for videos and text\n\n"
            "TEMPLATE DETAILS:\n"
            "- myth-buster: 1 video, 4 texts (hook, myth, truth, CTA). ~9.5s\n"
            "- bullet-sequence: 3 videos, 6 texts (hook, 3 bullets, conclusion, CTA). ~12s\n"
            "- viral-reaction: 1 video, AI-analyzed (auto-trims best moment). Uses AI analysis.\n"
            "- testimonial-story: 1 video, AI-analyzed (auto-generates quote overlay). Uses AI analysis.\n"
            "- big-quote: 1 video, 1 text (a powerful quote). Short overlay video.\n"
            "- deep-dive: 7 videos, 8 texts (title + 7 statements). Longer format.\n\n"
            "HOW YOU WORK:\n"
            "1. User describes what video they want\n"
            "2. You suggest the best template and help with the text\n"
            "3. Call `generate_video` with the template, video URLs, and texts\n"
            "4. Video rendering takes 30-180 seconds — you stream progress updates\n\n"
            "IMPORTANT RULES:\n"
            "- Always recommend the best template for the user's goal\n"
            "- Verify the user has uploaded the required number of videos\n"
            "- Help write compelling, concise text for each field\n"
            "- Keep text short: 3-8 words per field for most templates\n\n"
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
        """Define Gemini function calling tools for video operations."""
        from google.genai import types

        generate_video = types.FunctionDeclaration(
            name="generate_video",
            description=(
                "Generate a video/reel using a Creatomate template. "
                "Call this when the user wants to create a video. "
                "Rendering takes 30-180 seconds."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "template": types.Schema(
                        type="STRING",
                        description=(
                            "Template key: myth-buster, bullet-sequence, viral-reaction, "
                            "testimonial-story, big-quote, deep-dive"
                        ),
                    ),
                    "video_urls": types.Schema(
                        type="ARRAY",
                        items=types.Schema(type="STRING"),
                        description="URLs of user-uploaded videos",
                    ),
                    "text_1": types.Schema(type="STRING", description="Text field 1 (varies by template)"),
                    "text_2": types.Schema(type="STRING", description="Text field 2"),
                    "text_3": types.Schema(type="STRING", description="Text field 3"),
                    "text_4": types.Schema(type="STRING", description="Text field 4"),
                    "text_5": types.Schema(type="STRING", description="Text field 5"),
                    "text_6": types.Schema(type="STRING", description="Text field 6"),
                    "text_7": types.Schema(type="STRING", description="Text field 7"),
                    "text_8": types.Schema(type="STRING", description="Text field 8"),
                    "caption": types.Schema(
                        type="STRING",
                        description="Instagram caption for the video",
                    ),
                },
                required=["template", "video_urls"],
            ),
        )

        return [types.Tool(function_declarations=[generate_video])]

    async def execute_tool(
        self, name: str, args: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any]:
        """Execute video tools by delegating to existing services."""
        user_id = kwargs.get("user_id", self.user_id)

        if name == "generate_video":
            return await self._generate_video(user_id, args)
        else:
            return {"error": f"Unknown tool: {name}"}

    # ------------------------------------------------------------------
    # Tool: generate_video
    # ------------------------------------------------------------------

    async def _generate_video(
        self, user_id: str, args: dict[str, Any]
    ) -> dict[str, Any]:
        """Generate a video using the existing Creatomate pipeline."""
        template_str = args.get("template", "")
        video_urls = args.get("video_urls", [])
        caption = args.get("caption", "")

        # Validate template
        try:
            template_enum = VideoTemplate(template_str)
        except ValueError:
            return {
                "error": f"Invalid template: {template_str}",
                "valid_templates": [t.value for t in VideoTemplate],
            }

        config = TEMPLATE_CONFIG[template_enum]

        # Validate video count
        required_videos = config.get("required_videos", 1)
        if len(video_urls) < required_videos:
            return {
                "error": (
                    f"Template '{template_str}' requires {required_videos} video(s), "
                    f"but only {len(video_urls)} provided."
                ),
                "status": "missing_videos",
            }

        try:
            # Check credits
            credits_service = CreditsService()
            await credits_service.check_credits(user_id)

            # Load brand profile
            brand_service = BrandService()
            profile = await brand_service.load_profile(user_id)

            # Build a fake request object for the template mappers
            from app.models.video import GenerateVideoRequest

            req = GenerateVideoRequest(
                template=template_str,
                video_urls=video_urls,
                text_1=args.get("text_1"),
                text_2=args.get("text_2"),
                text_3=args.get("text_3"),
                text_4=args.get("text_4"),
                text_5=args.get("text_5"),
                text_6=args.get("text_6"),
                text_7=args.get("text_7"),
                text_8=args.get("text_8"),
                caption=caption,
            )

            # Video analysis for T3/T4
            analysis_result = None
            if template_enum in ANALYSIS_MAPPERS and video_urls:
                analysis_service = VideoAnalysisService()
                if template_enum == VideoTemplate.VIRAL_REACTION:
                    analysis_result = await analysis_service.analyze_for_viral_reaction(
                        video_urls[0]
                    )
                elif template_enum == VideoTemplate.TESTIMONIAL_STORY:
                    analysis_result = await analysis_service.analyze_for_testimonial(
                        video_urls[0]
                    )

            # Build Creatomate modifications
            if template_enum in ANALYSIS_MAPPERS and analysis_result:
                mapper = ANALYSIS_MAPPERS[template_enum]
                modifications, extra_params = mapper(req, analysis_result)
            elif template_enum in TEMPLATE_MAPPERS:
                mapper = TEMPLATE_MAPPERS[template_enum]
                modifications, extra_params = mapper(req)
            else:
                return {
                    "error": f"No mapper for template: {template_str}",
                    "status": "internal_error",
                }

            # Enrich with brand colors/logo
            if profile:
                if profile.get("brand_color_primary"):
                    modifications["Opacity Layer.fill_color"] = profile["brand_color_primary"]
                if profile.get("logo_url"):
                    modifications["Logo"] = profile["logo_url"]

            # Render via Creatomate
            template_id = config["creatomate_id"]
            creatomate = CreatomateService()
            render_id = await creatomate.render(template_id, modifications, **extra_params)

            # Poll for completion
            final_status = await creatomate.poll_status(render_id)

            if final_status.status != "succeeded":
                return {
                    "error": f"Render failed: {final_status.error_message or 'unknown'}",
                    "status": "render_failed",
                }

            video_url = final_status.url
            if not video_url:
                return {"error": "Render succeeded but no URL returned", "status": "render_failed"}

            # Download and re-upload to Supabase Storage
            video_bytes = await creatomate.download_video(video_url)

            storage = StorageService()
            storage_path = (
                f"generated/{user_id}/{int(time.time())}-{uuid.uuid4().hex[:8]}.mp4"
            )
            upload_url = (
                f"{storage.supabase_url}/storage/v1/object/"
                f"{storage.bucket}/{storage_path}"
            )

            async with httpx.AsyncClient(timeout=60) as client:
                upload_response = await client.post(
                    upload_url,
                    content=video_bytes,
                    headers={
                        "Authorization": f"Bearer {storage.service_key}",
                        "apikey": storage.service_key,
                        "Content-Type": "video/mp4",
                        "x-upsert": "true",
                    },
                )
                upload_response.raise_for_status()

            public_url = (
                f"{storage.supabase_url}/storage/v1/object/public/"
                f"{storage.bucket}/{storage_path}"
            )

            # Save to requests_log
            message_id = str(uuid.uuid4())
            reply_text = caption or "Your video is ready!"
            supabase = get_supabase_admin()
            _saved = False
            try:
                supabase.table("requests_log").upsert(
                    {
                        "id": message_id,
                        "user_id": user_id,
                        "agent_type": "reels-edited-by-ai",
                        "title": f"Video: {template_str}",
                        "reply": reply_text,
                        "caption": caption,
                        "media_urls": [public_url],
                        "published": False,
                        "reel_category": template_str,
                    },
                    on_conflict="id",
                ).execute()
                _saved = True
            except Exception as e:
                logger.error("Failed to save video to requests_log: %s", e)

            # Increment credits
            if _saved:
                try:
                    await credits_service.increment_credits(user_id, "reels-edited-by-ai")
                except Exception as e:
                    logger.error("Failed to increment credits: %s", e)

            return {
                "status": "success",
                "reply": reply_text,
                "caption": caption,
                "media_urls": [public_url],
                "message_id": message_id,
                "template": template_str,
                "render_duration_ms": int((final_status.render_time or 0) * 1000),
            }

        except Exception as e:
            logger.error("Video generation failed: %s", e, exc_info=True)
            return {"error": str(e), "status": "failed"}
