"""PelviBiz AI Agent — unified Gemini-powered agent with full tool suite.

Exposes all platform capabilities via Gemini function calling:
  - Content ideas & drafting
  - AI carousel generation
  - Video generation (6 Creatomate templates)
  - Brand profile management
  - Content library (view, schedule, publish, delete, stats)
  - Instagram account analysis
  - Learning insights
  - Account & credits info
"""

from __future__ import annotations

import base64
import logging
from typing import Any, AsyncGenerator
from uuid import uuid4

from google.genai import types

from app.agents.base import BaseStreamingAgent
from app.core.gemini_stream import stream_chat_with_retry
from app.core.streaming import (
    error_event,
    finish_event,
    text_chunk,
    tool_call_event,
    tool_result_event,
)
from app.dependencies import get_supabase_admin
from app.services.brand import BrandService
from app.services.content_strategy import ContentStrategyService
from app.services.credits import CreditsService
from app.services.draft_engine import DraftEngine
from app.services.ideas_engine import IdeasEngine
from app.services.image_generator import ImageGeneratorService
from app.services.instagram_scraper import InstagramScraper
from app.services.learning import LearningService
from app.services.profile_engine import ProfileEngine
from app.services.storage import StorageService
from app.services.style_analyzer import StyleAnalyzer
from app.services.watermark import WatermarkService
from app.utils.image import force_resolution

logger = logging.getLogger(__name__)

# ── Gemini Tool Definitions ──────────────────────────────────────────────────

_TOOLS = [
    types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="suggest_ideas",
                description=(
                    "Generate creative content ideas for Instagram carousels or videos, "
                    "tailored to the user's brand and audience."
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "topic": types.Schema(
                            type="STRING",
                            description="Topic or theme to generate ideas about",
                        ),
                        "content_type": types.Schema(
                            type="STRING",
                            description="Type of content: carousel or video",
                            enum=["carousel", "video"],
                        ),
                        "count": types.Schema(
                            type="INTEGER",
                            description="Number of ideas to generate (1–10, default 5)",
                        ),
                    },
                    required=["topic"],
                ),
            ),
            types.FunctionDeclaration(
                name="generate_draft",
                description=(
                    "Create slide text and Instagram caption for a given topic. "
                    "Use after user picks an idea or topic."
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "topic": types.Schema(
                            type="STRING",
                            description="The topic for the carousel",
                        ),
                        "slide_count": types.Schema(
                            type="INTEGER",
                            description="Number of slides the user requested. EXTRACT from message (e.g. 6-slide carousel = 6). Required.",
                        ),
                    },
                    required=["topic", "slide_count"],
                ),
            ),
            types.FunctionDeclaration(
                name="generate_ai_carousel",
                description=(
                    "Generate a full AI carousel with AI-generated images. "
                    "No user photos needed. Use when user asks to create/generate a carousel or post."
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "topic": types.Schema(
                            type="STRING",
                            description="The topic for the carousel",
                        ),
                        "slide_count": types.Schema(
                            type="INTEGER",
                            description="Number of slides the user requested. EXTRACT from message (e.g. 6-slide carousel = 6). Required.",
                        ),
                    },
                    required=["topic", "slide_count"],
                ),
            ),
            types.FunctionDeclaration(
                name="generate_video",
                description=(
                    "Generate a branded short-form video using one of 6 Creatomate templates. "
                    "Requires video_urls for templates that need user footage."
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "template": types.Schema(
                            type="STRING",
                            description="Template key",
                            enum=[
                                "myth-buster",
                                "bullet-sequence",
                                "viral-reaction",
                                "testimonial-story",
                                "big-quote",
                                "deep-dive",
                            ],
                        ),
                        "text_1": types.Schema(
                            type="STRING",
                            description="First text (myth/title/hook/quote depending on template)",
                        ),
                        "text_2": types.Schema(
                            type="STRING",
                            description="Second text (truth/point-1/attribution)",
                        ),
                        "text_3": types.Schema(
                            type="STRING",
                            description="Third text (explanation/point-2)",
                        ),
                        "text_4": types.Schema(
                            type="STRING",
                            description="Fourth text (CTA/point-3)",
                        ),
                        "text_5": types.Schema(
                            type="STRING",
                            description="Fifth text (point-4 for bullet-sequence)",
                        ),
                        "video_urls": types.Schema(
                            type="ARRAY",
                            items=types.Schema(type="STRING"),
                            description=(
                                "Public video URLs. Required for: myth-buster, "
                                "bullet-sequence, viral-reaction, testimonial-story, deep-dive"
                            ),
                        ),
                        "caption": types.Schema(
                            type="STRING",
                            description="Instagram caption for the post",
                        ),
                    },
                    required=["template", "text_1"],
                ),
            ),
            types.FunctionDeclaration(
                name="check_profile",
                description=(
                    "View the user's brand profile — name, voice, audience, colors, "
                    "services, CTA, logo, and credit usage."
                ),
                parameters=types.Schema(type="OBJECT", properties={}),
            ),
            types.FunctionDeclaration(
                name="update_profile_field",
                description=(
                    "Update a specific brand profile field. Use when user asks to change "
                    "their brand voice, CTA, target audience, visual identity, keywords, "
                    "services, or content style."
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "field_name": types.Schema(
                            type="STRING",
                            description="The profile field to update",
                            enum=[
                                "brand_voice",
                                "target_audience",
                                "cta",
                                "visual_identity",
                                "keywords",
                                "services_offered",
                                "content_style_brief",
                            ],
                        ),
                        "instruction": types.Schema(
                            type="STRING",
                            description="What to change, e.g. 'make it more casual'",
                        ),
                    },
                    required=["field_name", "instruction"],
                ),
            ),
            types.FunctionDeclaration(
                name="check_content_library",
                description=(
                    "View recently generated content (carousels and videos) "
                    "from the user's content library."
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "limit": types.Schema(
                            type="INTEGER",
                            description="Number of items (default 5, max 20)",
                        ),
                        "content_type": types.Schema(
                            type="STRING",
                            description="Filter: carousel, ai-carousel, video, or all",
                            enum=["carousel", "ai-carousel", "video", "all"],
                        ),
                    },
                ),
            ),
            types.FunctionDeclaration(
                name="schedule_content",
                description="Schedule a content item for publishing on a specific date and time.",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "content_id": types.Schema(
                            type="STRING",
                            description="ID of the content to schedule",
                        ),
                        "scheduled_date": types.Schema(
                            type="STRING",
                            description="ISO 8601 datetime, e.g. 2026-04-15T10:00:00",
                        ),
                    },
                    required=["content_id", "scheduled_date"],
                ),
            ),
            types.FunctionDeclaration(
                name="publish_content",
                description="Mark a content item as published.",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "content_id": types.Schema(
                            type="STRING",
                            description="ID of the content item",
                        ),
                    },
                    required=["content_id"],
                ),
            ),
            types.FunctionDeclaration(
                name="delete_content",
                description="Delete a content item from the user's library.",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "content_id": types.Schema(
                            type="STRING",
                            description="ID of the content to delete",
                        ),
                    },
                    required=["content_id"],
                ),
            ),
            types.FunctionDeclaration(
                name="get_content_stats",
                description=(
                    "Get usage statistics — total content generated, breakdown by type, "
                    "published vs unpublished counts, and credits used."
                ),
                parameters=types.Schema(type="OBJECT", properties={}),
            ),
            types.FunctionDeclaration(
                name="get_account_info",
                description=(
                    "Get account information — credits used, credit limit, "
                    "credits remaining, and account role."
                ),
                parameters=types.Schema(type="OBJECT", properties={}),
            ),
            types.FunctionDeclaration(
                name="get_learning_summary",
                description=(
                    "Get a summary of the user's content patterns — what topics work, "
                    "preferred hooks, best-performing content types, and audience engagement insights."
                ),
                parameters=types.Schema(type="OBJECT", properties={}),
            ),
            types.FunctionDeclaration(
                name="analyze_instagram",
                description=(
                    "Analyze an Instagram account's posting style — hooks, captions, "
                    "hashtags, content categories, engagement rates, and CTA patterns."
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "username": types.Schema(
                            type="STRING",
                            description="Instagram username (without @)",
                        ),
                        "max_posts": types.Schema(
                            type="INTEGER",
                            description="Max posts to analyze (default 30)",
                        ),
                    },
                    required=["username"],
                ),
            ),
            types.FunctionDeclaration(
                name="unpublish_content",
                description="Unpublish (revert to draft) a content item that was previously published.",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "content_id": types.Schema(type="STRING", description="ID of the content item"),
                    },
                    required=["content_id"],
                ),
            ),
            types.FunctionDeclaration(
                name="research_content",
                description=(
                    "Research trending content topics for a niche. "
                    "Use when user asks to research, find trends, or explore ideas for a topic."
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "niche": types.Schema(type="STRING", description="Niche or topic to research"),
                        "limit": types.Schema(type="INTEGER", description="Number of topics (default 10)"),
                    },
                    required=["niche"],
                ),
            ),
            types.FunctionDeclaration(
                name="generate_hooks",
                description=(
                    "Generate scroll-stopping hook variations for a topic. "
                    "Use when user wants hooks, titles, or opening lines."
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "topic": types.Schema(type="STRING", description="Topic to generate hooks for"),
                        "count": types.Schema(type="INTEGER", description="Number of hooks (default 6)"),
                    },
                    required=["topic"],
                ),
            ),
            types.FunctionDeclaration(
                name="generate_script",
                description=(
                    "Write a full short-form video script and filming card for a topic. "
                    "Use when user wants a reel script, video script, or filming guide."
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "topic": types.Schema(type="STRING", description="Topic for the script"),
                        "selected_hook": types.Schema(type="STRING", description="The hook to open with (optional)"),
                    },
                    required=["topic"],
                ),
            ),
            types.FunctionDeclaration(
                name="social_research",
                description=(
                    "Research a topic across Instagram, TikTok, Facebook, and Google. "
                    "Returns a ranked brief of what's working. "
                    "Use for competitor research, trend scouting, or content strategy."
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "topic": types.Schema(type="STRING", description="Topic or niche to research"),
                        "platforms": types.Schema(
                            type="ARRAY",
                            items=types.Schema(type="STRING"),
                            description="Platforms: instagram, tiktok, facebook, google. Default: all.",
                        ),
                    },
                    required=["topic"],
                ),
            ),
            types.FunctionDeclaration(
                name="get_brand_stories",
                description="Get the user's saved brand stories — personal experiences used to humanize content.",
                parameters=types.Schema(type="OBJECT", properties={}),
            ),
            types.FunctionDeclaration(
                name="create_brand_story",
                description="Save a new brand story to use in future content generation.",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "title": types.Schema(type="STRING", description="Short title for the story"),
                        "content": types.Schema(type="STRING", description="The full story text"),
                    },
                    required=["title", "content"],
                ),
            ),
            types.FunctionDeclaration(
                name="creatomate_list_templates",
                description=(
                    "List all available Creatomate video templates. "
                    "Call this when the user asks what templates or video styles are available."
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={},
                ),
            ),
            types.FunctionDeclaration(
                name="creatomate_render_template",
                description=(
                    "Render a Creatomate template with custom text and media modifications. "
                    "Call this when the user wants to create a video from a specific template ID."
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "template_id": types.Schema(
                            type="STRING",
                            description="Creatomate template UUID to render",
                        ),
                        "modifications": types.Schema(
                            type="OBJECT",
                            description="Key-value pairs of element name to new value (text, URL, color, etc.)",
                        ),
                        "webhook_url": types.Schema(
                            type="STRING",
                            description="Optional URL to receive the result webhook when render completes",
                        ),
                    },
                    required=["template_id", "modifications"],
                ),
            ),
            types.FunctionDeclaration(
                name="creatomate_render_with_voice",
                description=(
                    "Render a Creatomate template that includes text-to-speech (TTS) voice elements. "
                    "Use this when the user wants a video with AI-generated voiceover. "
                    "The voice provider and voice ID must already be configured in the template on Creatomate dashboard."
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "template_id": types.Schema(
                            type="STRING",
                            description="Creatomate template UUID that has TTS elements configured",
                        ),
                        "modifications": types.Schema(
                            type="OBJECT",
                            description="Key-value pairs including the voiceover text element content",
                        ),
                        "webhook_url": types.Schema(
                            type="STRING",
                            description="Optional webhook URL for async delivery",
                        ),
                    },
                    required=["template_id", "modifications"],
                ),
            ),
            types.FunctionDeclaration(
                name="creatomate_get_render_status",
                description=(
                    "Check the current status of a Creatomate render by its ID. "
                    "Returns status, video URL (if succeeded), and any error message."
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "render_id": types.Schema(
                            type="STRING",
                            description="The render ID returned from a previous render call",
                        ),
                    },
                    required=["render_id"],
                ),
            ),
        ]
    )
]


# ── Agent Class ──────────────────────────────────────────────────────────────

class PelvibizAiAgent(BaseStreamingAgent):
    """Unified PelviBiz AI agent — full capability suite via Gemini function calling."""

    @property
    def system_prompt(self) -> str:
        return "You are PelviBiz AI, an intelligent content assistant for health professionals."

    @property
    def model(self) -> str:
        return "gemini-2.5-flash"

    @property
    def temperature(self) -> float:
        return 0.7

    @property
    def max_tokens(self) -> int:
        return 8192

    @property
    def tools(self) -> list:
        return _TOOLS

    async def stream(
        self,
        message: str,
        history: list[dict] | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        """Stream with brand context and learning patterns injected dynamically."""
        try:
            brand_svc = BrandService()
            learning_svc = LearningService()

            profile = await brand_svc.load_profile(self.user_id)
            patterns = await learning_svc.get_patterns(self.user_id)
            learning_summary = (patterns.get("learning_summary", "") if patterns else "")

            system_ctx = _build_system_prompt(profile, learning_summary)

            messages: list[dict] = []
            if history:
                messages.extend(history)

            # Support multimodal: extract attachments from request metadata
            metadata = kwargs.get("metadata") or {}
            attachments = metadata.get("attachments") or []
            user_msg: dict = {"role": "user", "content": message}
            if attachments:
                user_msg["attachments"] = [
                    {
                        "mime_type": att.get("mime_type") or att.get("mimeType", "image/jpeg"),
                        "data": att.get("data", ""),
                    }
                    for att in attachments
                    if att.get("data")
                ]
            messages.append(user_msg)

            # Agentic loop: up to MAX_TURNS rounds of tool calls
            MAX_TURNS = 5
            for _turn in range(MAX_TURNS):
                tool_calls_this_turn: list[dict] = []
                tool_results_this_turn: list[dict] = []

                async for chunk in stream_chat_with_retry(
                    messages=messages,
                    system_prompt=system_ctx,
                    model=self.model,
                    temperature=self.temperature,
                    max_output_tokens=self.max_tokens,
                    tools=self.tools,
                ):
                    if chunk["type"] == "text":
                        yield text_chunk(chunk["content"])

                    elif chunk["type"] == "tool_call":
                        tc_id = chunk["id"]
                        tc_name = chunk["name"]
                        tc_args = chunk["args"]

                        yield tool_call_event(tc_id, tc_name, tc_args)

                        try:
                            result = await self.execute_tool(
                                name=tc_name,
                                args=tc_args,
                                user_id=self.user_id,
                                profile=profile,
                            )
                        except Exception as exc:
                            logger.error("Tool %s failed: %s", tc_name, exc, exc_info=True)
                            result = {"error": str(exc)}

                        yield tool_result_event(tc_id, result)
                        tool_calls_this_turn.append(chunk)
                        tool_results_this_turn.append({
                            "id": tc_id,
                            "name": tc_name,
                            "result": result,
                        })

                # If no tool calls this turn, we're done
                if not tool_calls_this_turn:
                    break

                # Feed tool results back to Gemini for the next turn
                messages.append({
                    "role": "assistant",
                    "content": "",
                    "function_calls": [
                        {"id": tc["id"], "name": tc["name"], "args": tc["args"]}
                        for tc in tool_calls_this_turn
                    ],
                })
                messages.append({
                    "role": "tool",
                    "function_results": tool_results_this_turn,
                })

            yield finish_event("stop")

        except Exception as exc:
            logger.error(
                "PelvibizAiAgent stream error [%s]: %s",
                self.user_id,
                exc,
                exc_info=True,
            )
            yield error_event(str(exc), "INTERNAL_ERROR")

    async def execute_tool(
        self, name: str, args: dict, **kwargs: Any
    ) -> dict[str, Any]:
        user_id = kwargs.get("user_id", self.user_id)
        profile = kwargs.get("profile", {})

        dispatch = {
            "suggest_ideas": lambda: self._tool_suggest_ideas(args, user_id),
            "generate_draft": lambda: self._tool_generate_draft(args, user_id),
            "generate_ai_carousel": lambda: self._tool_generate_ai_carousel(args, user_id, profile),
            "generate_video": lambda: self._tool_generate_video(args, user_id, profile),
            "check_profile": lambda: self._tool_check_profile(user_id),
            "update_profile_field": lambda: self._tool_update_profile_field(args, user_id, profile),
            "check_content_library": lambda: self._tool_check_content_library(args, user_id),
            "schedule_content": lambda: self._tool_schedule_content(args, user_id),
            "publish_content": lambda: self._tool_publish_content(args, user_id),
            "delete_content": lambda: self._tool_delete_content(args, user_id),
            "get_content_stats": lambda: self._tool_get_content_stats(user_id),
            "get_account_info": lambda: self._tool_get_account_info(user_id),
            "get_learning_summary": lambda: self._tool_get_learning_summary(user_id),
            "analyze_instagram": lambda: self._tool_analyze_instagram(args),
            "unpublish_content": lambda: self._tool_unpublish_content(args, user_id),
            "research_content": lambda: self._tool_research_content(args, user_id),
            "generate_hooks": lambda: self._tool_generate_hooks(args, user_id),
            "generate_script": lambda: self._tool_generate_script(args, user_id),
            "social_research": lambda: self._tool_social_research(args, user_id),
            "get_brand_stories": lambda: self._tool_get_brand_stories(user_id),
            "create_brand_story": lambda: self._tool_create_brand_story(args, user_id),
            "creatomate_list_templates": lambda: self._tool_creatomate_list_templates(user_id),
            "creatomate_render_template": lambda: self._tool_creatomate_render_template(args, user_id),
            "creatomate_render_with_voice": lambda: self._tool_creatomate_render_with_voice(args, user_id),
            "creatomate_get_render_status": lambda: self._tool_creatomate_get_render_status(args, user_id),
        }

        handler = dispatch.get(name)
        if not handler:
            return {"error": f"Unknown tool: {name}"}
        return await handler()

    # ── Tool Implementations ─────────────────────────────────────────────────

    async def _tool_suggest_ideas(self, args: dict, user_id: str) -> dict:
        engine = IdeasEngine()
        count = min(int(args.get("count", 5)), 10)
        content_type = args.get("content_type", "carousel")
        agent_type = "ai-carousel" if content_type == "carousel" else "reels-edited-by-ai"
        result = await engine.generate_ideas(
            user_id=user_id,
            message=args.get("topic", ""),
            agent_type=agent_type,
            count=count,
        )
        return {
            "ideas": result.get("ideas", []),
            "reasoning": result.get("reasoning", ""),
        }

    async def _tool_generate_draft(self, args: dict, user_id: str) -> dict:
        engine = DraftEngine()
        result = await engine.generate_draft(
            user_id=user_id,
            topic=args.get("topic", ""),
            slide_count=int(args.get("slide_count", 5)),
        )
        return result

    async def _tool_generate_ai_carousel(
        self, args: dict, user_id: str, profile: dict
    ) -> dict:
        from app.models.ai_carousel import SlideType
        from app.prompts.ai_carousel_generate import (
            build_card_slide_prompt,
            build_generic_slide_prompt,
        )

        # Check credits
        credits = CreditsService()
        await credits.check_credits(user_id)

        strategy = ContentStrategyService()
        plan = await strategy.plan_ai(
            args.get("topic", ""), profile, int(args.get("slide_count", 5))
        )

        img_gen = ImageGeneratorService()
        storage = StorageService()
        watermark = WatermarkService()
        media_urls: list[str] = []
        supabase = get_supabase_admin()

        for slide in plan.slides:
            try:
                if slide.slide_type == SlideType.GENERIC:
                    prompt = build_generic_slide_prompt(
                        visual_prompt=slide.visual_prompt,
                        text=slide.text,
                        text_position=slide.text_position,
                        font_prompt=profile.get("font_prompt", "Sans-serif"),
                        font_style=profile.get("font_style", "bold"),
                        font_size=profile.get("font_size", "38px"),
                        color_primary=profile.get("brand_color_primary", "#000"),
                        color_secondary=profile.get("brand_color_secondary", "#FFF"),
                    )
                else:
                    prompt = build_card_slide_prompt(
                        text=slide.text,
                        text_position=slide.text_position or "Center",
                        font_prompt=profile.get("font_prompt", "Sans-serif"),
                        font_style=profile.get("font_style", "bold"),
                        font_size=profile.get("font_size", "42px"),
                        color_primary=profile.get("brand_color_primary", "#000"),
                        color_secondary=profile.get("brand_color_secondary", "#FFF"),
                    )

                gen_b64 = await img_gen.generate_from_prompt(prompt)
                img_bytes = force_resolution(base64.b64decode(gen_b64))
                img_bytes = await watermark.apply(
                    img_bytes, profile.get("logo_url"), user_id
                )
                url = await storage.upload_image(
                    base64.b64encode(img_bytes).decode(), user_id
                )
                media_urls.append(url)
            except Exception as exc:
                logger.error("AI carousel slide failed: %s", exc)

        msg_id = str(uuid4())
        try:
            supabase.table("requests_log").upsert(
                {
                    "id": msg_id,
                    "user_id": user_id,
                    "agent_type": "ai-carousel",
                    "title": args.get("topic", "AI Carousel"),
                    "reply": plan.reply,
                    "caption": plan.caption,
                    "media_urls": media_urls,
                    "published": False,
                },
                on_conflict="id",
            ).execute()
        except Exception as exc:
            logger.warning("Failed to save carousel to requests_log: %s", exc)

        try:
            await credits.increment_credits(user_id)
        except Exception:
            pass

        return {
            "content_id": msg_id,
            "media_urls": media_urls,
            "caption": plan.caption,
            "reply": plan.reply,
            "slides": len(media_urls),
        }

    async def _tool_generate_video(
        self, args: dict, user_id: str, profile: dict
    ) -> dict:
        """Generate a video via the Creatomate render pipeline."""
        from app.models.video import VideoTemplate, TEMPLATE_CONFIG
        from app.services.creatomate import CreatomateService
        from app.services.video_analysis import VideoAnalysisService
        from app.templates.creatomate_mappings import TEMPLATE_MAPPERS, ANALYSIS_MAPPERS
        from app.templates.brand_theme import resolve_theme
        from app.templates.renderscript_builders import RENDERSCRIPT_BUILDERS
        import os

        template_key = args.get("template", "")
        try:
            template_enum = VideoTemplate(template_key)
        except ValueError:
            return {
                "error": f"Invalid template '{template_key}'. Valid: myth-buster, bullet-sequence, viral-reaction, testimonial-story, big-quote, deep-dive"
            }

        # Check credits
        credits = CreditsService()
        await credits.check_credits(user_id)

        config = TEMPLATE_CONFIG[template_enum]
        template_id = config["creatomate_id"]

        # Build request-like object for mapper compatibility
        class _FakeReq:
            def __init__(self, args):
                self.template = args.get("template", "")
                self.text_1 = args.get("text_1") or ""
                self.text_2 = args.get("text_2") or ""
                self.text_3 = args.get("text_3") or ""
                self.text_4 = args.get("text_4") or ""
                self.text_5 = args.get("text_5") or ""
                self.text_6 = args.get("text_6") or ""
                self.text_7 = args.get("text_7") or ""
                self.text_8 = args.get("text_8") or ""
                self.caption = args.get("caption") or ""
                self.video_urls = args.get("video_urls") or []
                self.audio_url = args.get("audio_url")
                self.music_track = args.get("music_track")
                self.brand_name = profile.get("brand_name")
                self.brand_color_primary = profile.get("brand_color_primary")
                self.brand_color_secondary = profile.get("brand_color_secondary")
                self.font_style = profile.get("font_style")
                self.logo_url = profile.get("logo_url")
                self.agent_type = "reels-edited-by-ai"
                self.message_id = str(uuid4())

        req = _FakeReq(args)

        # Video analysis for T3/T4
        analysis_result = None
        if template_enum in ANALYSIS_MAPPERS and req.video_urls:
            analysis_svc = VideoAnalysisService()
            from app.models.video import VideoTemplate as VT
            if template_enum == VT.VIRAL_REACTION:
                analysis_result = await analysis_svc.analyze_for_viral_reaction(req.video_urls[0])
            elif template_enum == VT.TESTIMONIAL_STORY:
                analysis_result = await analysis_svc.analyze_for_testimonial(req.video_urls[0])

        # Build modifications
        flag = os.getenv("RENDERSCRIPT_TEMPLATES", "").strip().lower()
        use_renderscript = (flag == "all") or (template_key in {k.strip() for k in flag.split(",")})

        if use_renderscript and template_key in RENDERSCRIPT_BUILDERS:
            from app.templates.brand_theme import resolve_theme as _rt
            from app.dependencies import get_supabase_admin as _sb
            theme = _rt(profile)
            builder = RENDERSCRIPT_BUILDERS[template_key]
            renderscript, extra_params = builder(req, theme)
            modifications = None
        elif template_enum in ANALYSIS_MAPPERS and analysis_result:
            mapper = ANALYSIS_MAPPERS[template_enum]
            modifications, extra_params = mapper(req, analysis_result)
        elif template_enum in TEMPLATE_MAPPERS:
            mapper = TEMPLATE_MAPPERS[template_enum]
            modifications, extra_params = mapper(req)
        else:
            return {"error": f"No mapper found for template: {template_key}"}

        # Enrich with brand
        if modifications:
            if profile.get("brand_color_primary"):
                modifications["Opacity Layer.fill_color"] = profile["brand_color_primary"]
            if profile.get("logo_url"):
                modifications["Logo"] = profile["logo_url"]

        # Render via Creatomate
        creatomate = CreatomateService()
        if use_renderscript and template_key in RENDERSCRIPT_BUILDERS:
            render_id = await creatomate.render(
                template_id, modifications=None, renderscript=renderscript, **extra_params
            )
        else:
            render_id = await creatomate.render(template_id, modifications, **extra_params)

        final_status = await creatomate.poll_status(render_id)

        if final_status.status != "succeeded":
            return {"error": f"Render failed: {final_status.error_message or 'unknown'}"}

        video_url = final_status.url
        caption = args.get("caption", f"New video about {args.get('text_1', '')}") or ""

        # Save to DB
        supabase = get_supabase_admin()
        content_id = str(uuid4())
        try:
            supabase.table("requests_log").upsert(
                {
                    "id": content_id,
                    "user_id": user_id,
                    "agent_type": "reels-edited-by-ai",
                    "title": args.get("text_1", "Video")[:100],
                    "reply": f"Video generated using the {template_key} template.",
                    "caption": caption,
                    "media_urls": [video_url],
                    "published": False,
                },
                on_conflict="id",
            ).execute()
        except Exception as exc:
            logger.warning("Failed to save video to DB: %s", exc)

        try:
            await credits.increment_credits(user_id)
        except Exception:
            pass

        return {
            "content_id": content_id,
            "media_urls": [video_url],
            "caption": caption,
            "template": template_key,
        }

    async def _tool_check_profile(self, user_id: str) -> dict:
        brand = BrandService()
        profile = await brand.load_profile(user_id)
        return {
            "brand_name": profile.get("brand_name"),
            "brand_voice": profile.get("brand_voice"),
            "target_audience": profile.get("target_audience"),
            "services_offered": profile.get("services_offered"),
            "cta": profile.get("cta"),
            "keywords": profile.get("keywords"),
            "content_style_brief": profile.get("content_style_brief"),
            "brand_color_primary": profile.get("brand_color_primary"),
            "brand_color_secondary": profile.get("brand_color_secondary"),
            "logo_url": profile.get("logo_url"),
            "credits_used": profile.get("credits_used"),
            "credits_limit": profile.get("credits_limit"),
        }

    async def _tool_update_profile_field(
        self, args: dict, user_id: str, profile: dict
    ) -> dict:
        engine = ProfileEngine()
        result = await engine.regenerate_field(
            field_name=args.get("field_name", ""),
            current_profile=profile,
            instruction=args.get("instruction", ""),
        )
        supabase = get_supabase_admin()
        field = args["field_name"]
        supabase.table("profiles").update({field: result["new_value"]}).eq("id", user_id).execute()
        BrandService().invalidate_cache(user_id)
        return {
            "field": field,
            "old_value": result.get("old_value"),
            "new_value": result.get("new_value"),
            "success": True,
        }

    async def _tool_check_content_library(self, args: dict, user_id: str) -> dict:
        supabase = get_supabase_admin()
        limit = min(int(args.get("limit", 5)), 20)
        content_type = args.get("content_type", "all")

        query = (
            supabase.table("requests_log")
            .select("id, agent_type, title, caption, media_urls, published, scheduled_date, created_at")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(limit)
        )
        if content_type and content_type != "all":
            agent_map = {
                "carousel": "real-carousel",
                "ai-carousel": "ai-carousel",
                "video": "reels-edited-by-ai",
            }
            mapped = agent_map.get(content_type, content_type)
            query = query.eq("agent_type", mapped)

        result = query.execute()
        items = []
        for r in result.data or []:
            items.append({
                "id": r["id"],
                "type": r["agent_type"],
                "title": r.get("title", ""),
                "media_count": len(r.get("media_urls") or []),
                "media_urls": r.get("media_urls") or [],
                "caption": (r.get("caption") or "")[:200],
                "published": r.get("published", False),
                "scheduled_date": str(r.get("scheduled_date", "")),
                "created_at": str(r.get("created_at", "")),
            })
        return {"items": items, "total": len(items)}

    async def _tool_schedule_content(self, args: dict, user_id: str) -> dict:
        supabase = get_supabase_admin()
        content_id = args.get("content_id", "")
        scheduled_date = args.get("scheduled_date", "")

        # Verify ownership
        check = (
            supabase.table("requests_log")
            .select("id, title")
            .eq("id", content_id)
            .eq("user_id", user_id)
            .execute()
        )
        if not check.data:
            return {"error": "Content not found or access denied"}

        supabase.table("requests_log").update(
            {"scheduled_date": scheduled_date}
        ).eq("id", content_id).execute()

        return {
            "content_id": content_id,
            "scheduled_date": scheduled_date,
            "title": check.data[0].get("title", ""),
            "success": True,
        }

    async def _tool_publish_content(self, args: dict, user_id: str) -> dict:
        supabase = get_supabase_admin()
        content_id = args.get("content_id", "")

        check = (
            supabase.table("requests_log")
            .select("id, title")
            .eq("id", content_id)
            .eq("user_id", user_id)
            .execute()
        )
        if not check.data:
            return {"error": "Content not found or access denied"}

        supabase.table("requests_log").update({"published": True}).eq("id", content_id).execute()

        return {
            "content_id": content_id,
            "title": check.data[0].get("title", ""),
            "published": True,
            "success": True,
        }

    async def _tool_delete_content(self, args: dict, user_id: str) -> dict:
        supabase = get_supabase_admin()
        content_id = args.get("content_id", "")

        check = (
            supabase.table("requests_log")
            .select("id, title")
            .eq("id", content_id)
            .eq("user_id", user_id)
            .execute()
        )
        if not check.data:
            return {"error": "Content not found or access denied"}

        title = check.data[0].get("title", "")
        supabase.table("requests_log").delete().eq("id", content_id).execute()

        return {"content_id": content_id, "title": title, "deleted": True, "success": True}

    async def _tool_get_content_stats(self, user_id: str) -> dict:
        supabase = get_supabase_admin()
        result = (
            supabase.table("requests_log")
            .select("agent_type, published")
            .eq("user_id", user_id)
            .execute()
        )
        items = result.data or []
        by_type: dict[str, int] = {}
        published = 0
        unpublished = 0
        for item in items:
            t = item.get("agent_type", "unknown")
            by_type[t] = by_type.get(t, 0) + 1
            if item.get("published"):
                published += 1
            else:
                unpublished += 1

        return {
            "total": len(items),
            "by_type": by_type,
            "published": published,
            "unpublished": unpublished,
        }

    async def _tool_get_account_info(self, user_id: str) -> dict:
        supabase = get_supabase_admin()
        result = (
            supabase.table("profiles")
            .select("brand_name, credits_used, credits_limit, role, onboarding_completed")
            .eq("id", user_id)
            .execute()
        )
        if not result.data:
            return {"error": "Profile not found"}
        p = result.data[0]
        credits_used = p.get("credits_used", 0) or 0
        credits_limit = p.get("credits_limit", 0) or 0
        return {
            "brand_name": p.get("brand_name"),
            "credits_used": credits_used,
            "credits_limit": credits_limit,
            "credits_remaining": max(0, credits_limit - credits_used),
            "role": p.get("role", "user"),
            "onboarding_completed": p.get("onboarding_completed", False),
        }

    async def _tool_get_learning_summary(self, user_id: str) -> dict:
        learning = LearningService()
        patterns = await learning.get_patterns(user_id)
        if not patterns:
            return {"summary": "No learning data yet. Generate some content to start building patterns."}
        return {
            "summary": patterns.get("learning_summary", ""),
            "patterns": patterns,
        }

    async def _tool_analyze_instagram(self, args: dict) -> dict:
        scraper = InstagramScraper()
        analyzer = StyleAnalyzer()
        username = args.get("username", "")
        max_posts = int(args.get("max_posts", 30))

        profile_data, posts = await scraper.scrape(username, max_posts)
        if not posts:
            return {"error": f"No posts found for @{username}. Account may be private or not exist."}

        metrics = analyzer.analyze(posts, profile_data)
        return {
            "username": username,
            "followers": profile_data.get("followers", 0),
            "post_count": len(posts),
            "hook_types": metrics.get("hook_types", {}),
            "content_categories": metrics.get("content_categories", {}),
            "caption_avg_length": metrics.get("caption_avg_length", 0),
            "hashtag_avg_count": metrics.get("hashtag_avg_count", 0),
            "engagement_rate": metrics.get("engagement_rate", 0),
            "cta_types": metrics.get("cta_types", {}),
            "top_keywords": [k["word"] for k in metrics.get("top_keywords", [])[:10]],
            "emoji_frequency": metrics.get("emoji_frequency", 0),
            "posts_per_week": metrics.get("posts_per_week", 0),
        }


    async def _tool_unpublish_content(self, args: dict, user_id: str) -> dict:
        supabase = get_supabase_admin()
        content_id = args.get("content_id", "")
        check = (
            supabase.table("requests_log")
            .select("id, title")
            .eq("id", content_id)
            .eq("user_id", user_id)
            .execute()
        )
        if not check.data:
            return {"error": "Content not found or access denied"}
        supabase.table("requests_log").update({"published": False}).eq("id", content_id).execute()
        return {"content_id": content_id, "title": check.data[0].get("title", ""), "published": False, "success": True}

    async def _tool_research_content(self, args: dict, user_id: str) -> dict:
        from app.services.research import ResearchService
        service = ResearchService()
        result = await service.run_research(
            user_id=user_id,
            niche=args.get("niche", ""),
            sources=["reddit", "news", "youtube"],
            limit=int(args.get("limit", 10)),
            competitor_handle=None,
        )
        return result

    async def _tool_generate_hooks(self, args: dict, user_id: str) -> dict:
        from app.services.scripting import ScriptingService
        service = ScriptingService()
        return await service.generate_hook_pack(
            user_id=user_id,
            topic=args.get("topic", ""),
            research_topic_id=None,
            idea_variation_id=None,
            count=int(args.get("count", 6)),
            competitor_handle=None,
        )

    async def _tool_generate_script(self, args: dict, user_id: str) -> dict:
        from app.services.scripting import ScriptingService
        service = ScriptingService()
        return await service.generate_script(
            user_id=user_id,
            topic=args.get("topic", ""),
            research_topic_id=None,
            idea_variation_id=None,
            selected_hook=args.get("selected_hook"),
            competitor_handle=None,
        )

    async def _tool_social_research(self, args: dict, user_id: str) -> dict:
        from app.services.social_intelligence import SocialIntelligenceService
        service = SocialIntelligenceService()
        platforms = args.get("platforms") or ["instagram", "tiktok", "facebook", "google"]
        return await service.run_research(
            user_id=user_id,
            topic=args.get("topic", ""),
            platforms=platforms,
            limit=12,
            language="es",
        )

    async def _tool_get_brand_stories(self, user_id: str) -> dict:
        supabase = get_supabase_admin()
        result = (
            supabase.table("brand_stories")
            .select("id, title, content, created_at")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(20)
            .execute()
        )
        return {"stories": result.data or []}

    async def _tool_create_brand_story(self, args: dict, user_id: str) -> dict:
        from uuid import uuid4
        supabase = get_supabase_admin()
        story_id = str(uuid4())
        supabase.table("brand_stories").insert({
            "id": story_id,
            "user_id": user_id,
            "title": args.get("title", ""),
            "content": args.get("content", ""),
        }).execute()
        return {"id": story_id, "title": args.get("title", ""), "success": True}

    async def _tool_creatomate_list_templates(self, user_id: str) -> dict:
        """List available Creatomate templates (cached 5 min)."""
        from app.tools.creatomate_tools import CreatomateToolkit
        toolkit = CreatomateToolkit()
        templates = await toolkit.list_available_templates()
        return {"templates": templates, "count": len(templates)}

    async def _tool_creatomate_render_template(
        self, args: dict, user_id: str
    ) -> dict:
        """Render a Creatomate template with modifications."""
        from app.tools.creatomate_tools import CreatomateToolkit
        template_id = args.get("template_id", "")
        modifications = args.get("modifications") or {}
        webhook_url = args.get("webhook_url")

        if not template_id:
            return {"error": "template_id is required"}

        toolkit = CreatomateToolkit()
        return await toolkit.render_template(
            template_id=template_id,
            modifications=modifications,
            webhook_url=webhook_url,
            poll_timeout=10,
        )

    async def _tool_creatomate_render_with_voice(
        self, args: dict, user_id: str
    ) -> dict:
        """Render a TTS-enabled Creatomate template."""
        from app.tools.creatomate_tools import CreatomateToolkit
        template_id = args.get("template_id", "")
        modifications = args.get("modifications") or {}
        webhook_url = args.get("webhook_url")

        if not template_id:
            return {"error": "template_id is required"}

        toolkit = CreatomateToolkit()
        return await toolkit.render_video_with_voice(
            template_id=template_id,
            modifications=modifications,
            webhook_url=webhook_url,
        )

    async def _tool_creatomate_get_render_status(
        self, args: dict, user_id: str
    ) -> dict:
        """Fetch current status of a render."""
        from app.tools.creatomate_tools import CreatomateToolkit
        render_id = args.get("render_id", "")
        if not render_id:
            return {"error": "render_id is required"}
        toolkit = CreatomateToolkit()
        return await toolkit.get_render_status(render_id)

# ── System Prompt Builder ────────────────────────────────────────────────────

def _build_system_prompt(profile: dict, learning_summary: str = "") -> str:
    brand_name = profile.get("brand_name") or "your brand"
    brand_voice = profile.get("brand_voice") or "professional"
    target_audience = profile.get("target_audience") or "health professionals' patients"
    services = profile.get("services_offered") or ""
    cta = profile.get("cta") or ""

    learning_block = ""
    if learning_summary:
        learning_block = f"\n## User Preferences & Learning\n{learning_summary}\n"

    return f"""You are PelviBiz AI — the unified content creation assistant for {brand_name}.

## Brand Context
- **Brand:** {brand_name}
- **Voice & Tone:** {brand_voice}
- **Target Audience:** {target_audience}
- **Services:** {services}
- **CTA:** {cta}
{learning_block}
## Your Full Capability Suite

### Content Creation
- **`suggest_ideas`** — Generate ideas for carousels or videos
- **`generate_draft`** — Create slide copy + caption for a topic
- **`generate_ai_carousel`** — Full AI carousel with generated images (NO photos needed)
- **`generate_video`** — Short-form video using 6 templates (myth-buster, bullet-sequence, viral-reaction, testimonial-story, big-quote, deep-dive)

### Brand Management
- **`check_profile`** — View full brand profile
- **`update_profile_field`** — Update brand voice, audience, CTA, services, visual identity, keywords, or content style

### Content Library
- **`check_content_library`** — View recent carousels and videos
- **`schedule_content`** — Schedule a post for a future date
- **`publish_content`** — Mark content as published
- **`unpublish_content`** — Revert published content back to draft
- **`delete_content`** — Delete content from the library
- **`get_content_stats`** — Usage stats by type

### Research & Scripts
- **`research_content`** — Research trending topics for a niche (Reddit, news, YouTube)
- **`generate_hooks`** — Generate scroll-stopping hook variations for any topic
- **`generate_script`** — Write a full video script + filming card
- **`social_research`** — Research what's trending on Instagram, TikTok, Facebook, Google

### Brand Stories
- **`get_brand_stories`** — View saved brand stories (personal experiences for content)
- **`create_brand_story`** — Save a new brand story

### Analytics & Insights
- **`analyze_instagram`** — Analyze any IG account's style (competitors, inspiration accounts)
- **`get_learning_summary`** — Review patterns from past content
- **`get_account_info`** — Credits remaining and account details

## Critical Behavior Rules

1. **BE DIRECT AND ACT IMMEDIATELY**: When user says "create a carousel about X" → call `generate_ai_carousel` NOW with that topic. Don't ask what style. DO extract slide_count from their message ('6-slide' = 6, '7-slide' = 7). Default is 5 only when not mentioned.

2. **DEFAULT to AI Carousel** for any "create/make/generate a post/carousel" request. Only ask for photos if they specifically mention "my photos" or "real photos".

3. **For video requests**: Explain which template fits best (myth-buster for debunking, bullet-sequence for tips, big-quote for inspiration, etc.), then generate. If they have no video, use big-quote (no video needed) or suggest they record a short clip.

4. **NEVER ask more than ONE clarifying question** at a time. Prefer to use defaults and generate.

5. **After generating content**: Confirm what was created and show the caption. If `media_urls` are in the result, tell the user their content is ready.

6. **Keep responses SHORT**: 2-3 sentences max before/after tool calls.

7. **Language**: Respond in the same language the user writes in.
"""
