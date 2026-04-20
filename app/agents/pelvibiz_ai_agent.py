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
            # ── Real Carousel ─────────────────────────────────────────────────
            types.FunctionDeclaration(
                name="generate_real_carousel",
                description=(
                    "Generate a branded carousel using the user's own photos. "
                    "Renders text overlays with brand colors/fonts on top of the provided images. "
                    "Use when user provides their own photos/images and wants a carousel."
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "topic": types.Schema(type="STRING", description="Topic or message for the carousel"),
                        "image_urls": types.Schema(
                            type="ARRAY",
                            items=types.Schema(type="STRING"),
                            description="Public URLs of the user's photos (one per slide)",
                        ),
                        "slide_count": types.Schema(
                            type="INTEGER",
                            description="Number of slides (defaults to number of images provided)",
                        ),
                        "caption": types.Schema(type="STRING", description="Instagram caption (auto-generated if omitted)"),
                    },
                    required=["topic", "image_urls"],
                ),
            ),
            types.FunctionDeclaration(
                name="fix_carousel_slide",
                description=(
                    "Fix a single slide in an existing carousel — change the text or replace the image. "
                    "Use when user wants to edit one slide without regenerating the whole carousel."
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "content_id": types.Schema(type="STRING", description="ID of the carousel to fix"),
                        "slide_number": types.Schema(type="INTEGER", description="1-based slide index to replace"),
                        "new_text": types.Schema(type="STRING", description="New text for the slide"),
                        "new_image_url": types.Schema(type="STRING", description="New image URL (optional — keeps original if omitted)"),
                    },
                    required=["content_id", "slide_number", "new_text"],
                ),
            ),
            # ── Video Trim ────────────────────────────────────────────────────
            types.FunctionDeclaration(
                name="trim_video",
                description=(
                    "Trim a video clip to a specific start and end time. "
                    "Use when user wants to cut a video, extract a segment, or shorten footage."
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "source_url": types.Schema(type="STRING", description="Public URL of the source video"),
                        "start_seconds": types.Schema(type="NUMBER", description="Start time in seconds (e.g. 5.0)"),
                        "end_seconds": types.Schema(type="NUMBER", description="End time in seconds (e.g. 30.0)"),
                    },
                    required=["source_url", "start_seconds", "end_seconds"],
                ),
            ),
            # ── Competitors ───────────────────────────────────────────────────
            types.FunctionDeclaration(
                name="list_competitors",
                description="List all competitor Instagram accounts the user is tracking.",
                parameters=types.Schema(type="OBJECT", properties={}),
            ),
            types.FunctionDeclaration(
                name="add_competitor",
                description=(
                    "Add an Instagram account as a competitor to track. "
                    "Use when user wants to monitor or benchmark against another account."
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "handle": types.Schema(type="STRING", description="Instagram username (without @)"),
                        "display_name": types.Schema(type="STRING", description="Optional friendly name for this competitor"),
                    },
                    required=["handle"],
                ),
            ),
            types.FunctionDeclaration(
                name="compare_with_competitor",
                description=(
                    "Compare the user's content performance against a specific competitor. "
                    "Returns gaps, shared topics, viral posts, and strategic insights."
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "handle": types.Schema(type="STRING", description="Competitor Instagram handle (without @)"),
                    },
                    required=["handle"],
                ),
            ),
            types.FunctionDeclaration(
                name="get_competitor_gaps",
                description=(
                    "Get specific content gaps vs a competitor — what topics, hooks, and "
                    "content types the user is missing compared to them."
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "handle": types.Schema(type="STRING", description="Competitor Instagram handle"),
                    },
                    required=["handle"],
                ),
            ),
            types.FunctionDeclaration(
                name="delete_competitor",
                description="Remove a competitor from the tracking list.",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "handle": types.Schema(type="STRING", description="Competitor Instagram handle"),
                    },
                    required=["handle"],
                ),
            ),
            # ── Style Analyzer ────────────────────────────────────────────────
            types.FunctionDeclaration(
                name="analyze_account_style",
                description=(
                    "Run a full style analysis on any Instagram account — hooks, captions, "
                    "hashtags, posting patterns, engagement, and AI recommendations. "
                    "Saves the analysis so it can be applied to the user's brand profile."
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "username": types.Schema(type="STRING", description="Instagram username to analyze (without @)"),
                        "max_posts": types.Schema(type="INTEGER", description="Max posts to analyze (default 30)"),
                        "account_type": types.Schema(
                            type="STRING",
                            description="Type of account: competitor, inspiration, own",
                            enum=["competitor", "inspiration", "own"],
                        ),
                    },
                    required=["username"],
                ),
            ),
            types.FunctionDeclaration(
                name="apply_account_style",
                description=(
                    "Apply the content style from a previously analyzed account to the user's brand profile. "
                    "Updates content_style_brief with insights from the analysis. "
                    "Call after analyze_account_style — use the scrape_id from that result."
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "scrape_id": types.Schema(type="STRING", description="The account ID returned from analyze_account_style"),
                    },
                    required=["scrape_id"],
                ),
            ),
            types.FunctionDeclaration(
                name="list_analyzed_accounts",
                description="List all Instagram accounts that have been previously analyzed.",
                parameters=types.Schema(type="OBJECT", properties={}),
            ),
            types.FunctionDeclaration(
                name="get_content_brief",
                description=(
                    "Get the content strategy brief generated from an analyzed account. "
                    "Returns posting patterns, hook styles, and content recommendations."
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "account_id": types.Schema(type="STRING", description="Account ID from list_analyzed_accounts (optional — uses most recent if omitted)"),
                    },
                ),
            ),
            # ── Social Intelligence Full Flow ──────────────────────────────────
            types.FunctionDeclaration(
                name="social_generate_ideas",
                description=(
                    "Generate content ideas from a social research run. "
                    "Use after social_research to turn research findings into actionable post ideas."
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "topic": types.Schema(type="STRING", description="Topic to generate ideas for"),
                        "research_run_id": types.Schema(type="STRING", description="Run ID from a previous social_research call (optional)"),
                        "variations": types.Schema(type="INTEGER", description="Number of idea variations (default 6)"),
                    },
                    required=["topic"],
                ),
            ),
            types.FunctionDeclaration(
                name="social_generate_script",
                description=(
                    "Generate a full video script + filming card from a topic or idea. "
                    "More complete than generate_script — includes caption, CTA, and recording instructions."
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "topic": types.Schema(type="STRING", description="Topic for the script"),
                        "idea_variation_id": types.Schema(type="STRING", description="Specific idea ID from social_generate_ideas (optional)"),
                        "selected_hook": types.Schema(type="STRING", description="Opening hook to use (optional)"),
                    },
                    required=["topic"],
                ),
            ),
            # ── Brand Profile Full Management ──────────────────────────────────
            types.FunctionDeclaration(
                name="generate_brand_profile",
                description=(
                    "Generate a complete brand profile from scratch using AI. "
                    "Use when user wants to set up or completely redo their brand identity."
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "brand_name": types.Schema(type="STRING", description="Name of the brand"),
                        "niche": types.Schema(type="STRING", description="The niche or industry (e.g. pelvic floor therapy)"),
                        "services_description": types.Schema(type="STRING", description="What services the brand offers"),
                        "content_goals": types.Schema(type="STRING", description="What the brand wants to achieve with content"),
                        "target_audience": types.Schema(type="STRING", description="Who the content is for"),
                    },
                    required=["brand_name", "niche"],
                ),
            ),
            types.FunctionDeclaration(
                name="regenerate_profile_field",
                description=(
                    "Regenerate any brand profile field with a specific instruction. "
                    "More fields available than update_profile_field — includes visual identity, "
                    "outfit descriptions, font style, and brand playbook."
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "field_name": types.Schema(
                            type="STRING",
                            description="Field to regenerate",
                            enum=[
                                "brand_voice", "target_audience", "services_offered",
                                "visual_identity", "keywords", "cta", "content_style_brief",
                                "visual_environment_setup", "visual_subject_outfit_face",
                                "visual_subject_outfit_generic", "font_style", "font_prompt",
                            ],
                        ),
                        "instruction": types.Schema(type="STRING", description="What to change or improve"),
                    },
                    required=["field_name", "instruction"],
                ),
            ),
            # ── Content Library v2 ────────────────────────────────────────────
            types.FunctionDeclaration(
                name="list_content_paginated",
                description=(
                    "List content library with pagination and filters. "
                    "More powerful than check_content_library — supports paging through large libraries."
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "page": types.Schema(type="INTEGER", description="Page number (default 1)"),
                        "limit": types.Schema(type="INTEGER", description="Items per page (default 20, max 50)"),
                        "content_type": types.Schema(
                            type="STRING",
                            description="Filter by type: real-carousel, ai-carousel, reels-edited-by-ai",
                            enum=["real-carousel", "ai-carousel", "reels-edited-by-ai"],
                        ),
                        "published": types.Schema(type="BOOLEAN", description="Filter by published status (omit for all)"),
                    },
                ),
            ),
            types.FunctionDeclaration(
                name="get_content_detail",
                description="Get full details of a specific content item including all slides, caption, and metadata.",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "content_id": types.Schema(type="STRING", description="ID of the content item"),
                    },
                    required=["content_id"],
                ),
            ),
            types.FunctionDeclaration(
                name="update_content_metadata",
                description="Update the title and/or caption of a content item.",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "content_id": types.Schema(type="STRING", description="ID of the content item"),
                        "title": types.Schema(type="STRING", description="New title"),
                        "caption": types.Schema(type="STRING", description="New Instagram caption"),
                    },
                    required=["content_id"],
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
            # Real carousel
            "generate_real_carousel": lambda: self._tool_generate_real_carousel(args, user_id, profile),
            "fix_carousel_slide": lambda: self._tool_fix_carousel_slide(args, user_id, profile),
            # Video trim
            "trim_video": lambda: self._tool_trim_video(args, user_id),
            # Competitors
            "list_competitors": lambda: self._tool_list_competitors(user_id),
            "add_competitor": lambda: self._tool_add_competitor(args, user_id),
            "compare_with_competitor": lambda: self._tool_compare_with_competitor(args, user_id),
            "get_competitor_gaps": lambda: self._tool_get_competitor_gaps(args, user_id),
            "delete_competitor": lambda: self._tool_delete_competitor(args, user_id),
            # Style analyzer
            "analyze_account_style": lambda: self._tool_analyze_account_style(args, user_id),
            "apply_account_style": lambda: self._tool_apply_account_style(args, user_id),
            "list_analyzed_accounts": lambda: self._tool_list_analyzed_accounts(user_id),
            "get_content_brief": lambda: self._tool_get_content_brief(args, user_id),
            # Social intelligence
            "social_generate_ideas": lambda: self._tool_social_generate_ideas(args, user_id),
            "social_generate_script": lambda: self._tool_social_generate_script(args, user_id),
            # Brand profile
            "generate_brand_profile": lambda: self._tool_generate_brand_profile(args, user_id),
            "regenerate_profile_field": lambda: self._tool_regenerate_profile_field(args, user_id, profile),
            # Content v2
            "list_content_paginated": lambda: self._tool_list_content_paginated(args, user_id),
            "get_content_detail": lambda: self._tool_get_content_detail(args, user_id),
            "update_content_metadata": lambda: self._tool_update_content_metadata(args, user_id),
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

    # ── Real Carousel ────────────────────────────────────────────────────────

    async def _tool_generate_real_carousel(
        self, args: dict, user_id: str, profile: dict
    ) -> dict:
        from app.services.slide_renderer import SlideRenderer

        image_urls: list[str] = args.get("image_urls") or []
        if not image_urls:
            return {"error": "image_urls is required — provide at least one photo URL"}

        topic = args.get("topic", "")
        slide_count = int(args.get("slide_count") or len(image_urls))

        credits = CreditsService()
        await credits.check_credits(user_id)

        strategy = ContentStrategyService()
        plan = await strategy.plan(topic, profile, slide_count)

        renderer = SlideRenderer()
        storage = StorageService()
        supabase = get_supabase_admin()
        media_urls: list[str] = []
        failed = 0

        slides = plan.slides if hasattr(plan, "slides") else []
        for i, img_url in enumerate(image_urls[:slide_count]):
            try:
                text = slides[i].text if i < len(slides) else ""
                position = slides[i].text_position if i < len(slides) else "Center"
                img_bytes = await renderer.download_image(img_url)
                rendered = renderer.render_slide(
                    image_bytes=img_bytes,
                    text=text,
                    position=position,
                    font_style=profile.get("font_style", "bold"),
                    color_primary=profile.get("brand_color_primary", "#000000"),
                    color_secondary=profile.get("brand_color_secondary", "#FFFFFF"),
                    color_background=profile.get("brand_color_background", "#FFFFFF"),
                    slide_index=i,
                )
                url = await storage.upload_image(
                    base64.b64encode(rendered).decode(), user_id
                )
                media_urls.append(url)
            except Exception as exc:
                logger.error("Real carousel slide %d failed: %s", i, exc)
                failed += 1

        if not media_urls:
            return {"error": "All slides failed to render. Check that image URLs are publicly accessible."}

        msg_id = str(uuid4())
        caption = args.get("caption") or getattr(plan, "caption", "")
        try:
            supabase.table("requests_log").upsert(
                {
                    "id": msg_id,
                    "user_id": user_id,
                    "agent_type": "real-carousel",
                    "title": topic[:100],
                    "reply": getattr(plan, "reply", ""),
                    "caption": caption,
                    "media_urls": media_urls,
                    "published": False,
                },
                on_conflict="id",
            ).execute()
        except Exception as exc:
            logger.warning("Failed to save real carousel: %s", exc)

        try:
            await credits.increment_credits(user_id)
        except Exception:
            pass

        return {
            "content_id": msg_id,
            "media_urls": media_urls,
            "caption": caption,
            "slides": len(media_urls),
            "failed_slides": failed,
        }

    async def _tool_fix_carousel_slide(
        self, args: dict, user_id: str, profile: dict
    ) -> dict:
        from app.services.slide_renderer import SlideRenderer

        content_id = args.get("content_id", "")
        slide_number = int(args.get("slide_number", 1))
        new_text = args.get("new_text", "")
        new_image_url = args.get("new_image_url")

        supabase = get_supabase_admin()
        check = (
            supabase.table("requests_log")
            .select("id, media_urls, agent_type")
            .eq("id", content_id)
            .eq("user_id", user_id)
            .execute()
        )
        if not check.data:
            return {"error": "Content not found or access denied"}

        row = check.data[0]
        media_urls: list[str] = list(row.get("media_urls") or [])
        idx = slide_number - 1

        if idx < 0 or idx >= len(media_urls):
            return {"error": f"Slide {slide_number} does not exist. Carousel has {len(media_urls)} slides."}

        source_url = new_image_url or media_urls[idx]
        renderer = SlideRenderer()
        storage = StorageService()

        try:
            img_bytes = await renderer.download_image(source_url)
            rendered = renderer.render_slide(
                image_bytes=img_bytes,
                text=new_text,
                position="Center",
                font_style=profile.get("font_style", "bold"),
                color_primary=profile.get("brand_color_primary", "#000000"),
                color_secondary=profile.get("brand_color_secondary", "#FFFFFF"),
                color_background=profile.get("brand_color_background", "#FFFFFF"),
                slide_index=idx,
            )
            new_url = await storage.upload_image(
                base64.b64encode(rendered).decode(), user_id
            )
        except Exception as exc:
            return {"error": f"Failed to render slide: {exc}"}

        media_urls[idx] = new_url
        supabase.table("requests_log").update({"media_urls": media_urls}).eq("id", content_id).execute()

        return {
            "content_id": content_id,
            "slide_number": slide_number,
            "new_url": new_url,
            "media_urls": media_urls,
            "success": True,
        }

    # ── Video Trim ───────────────────────────────────────────────────────────

    async def _tool_trim_video(self, args: dict, user_id: str) -> dict:
        from app.services.video_trim_service import VideoTrimService

        source_url = args.get("source_url", "")
        start = float(args.get("start_seconds", 0))
        end = float(args.get("end_seconds", 0))

        if not source_url:
            return {"error": "source_url is required"}
        if end <= start:
            return {"error": "end_seconds must be greater than start_seconds"}

        service = VideoTrimService()
        try:
            trimmed_url = await service.trim_and_store(
                source_url=source_url,
                user_id=user_id,
                start_seconds=start,
                end_seconds=end,
            )
        except Exception as exc:
            return {"error": f"Trim failed: {exc}"}

        return {
            "trimmed_url": trimmed_url,
            "start_seconds": start,
            "end_seconds": end,
            "duration_seconds": round(end - start, 2),
        }

    # ── Competitors ──────────────────────────────────────────────────────────

    async def _tool_list_competitors(self, user_id: str) -> dict:
        from app.services.competitors import CompetitorService
        service = CompetitorService()
        competitors = await service.list_competitors(user_id)
        return {"competitors": competitors, "total": len(competitors)}

    async def _tool_add_competitor(self, args: dict, user_id: str) -> dict:
        from app.services.competitors import CompetitorService
        service = CompetitorService()
        handle = args.get("handle", "").lstrip("@")
        if not handle:
            return {"error": "handle is required"}
        result = await service.add_competitor(
            user_id=user_id,
            handle=handle,
            display_name=args.get("display_name"),
        )
        return {"competitor": result, "success": True}

    async def _tool_compare_with_competitor(self, args: dict, user_id: str) -> dict:
        from app.services.competitors import CompetitorService
        service = CompetitorService()
        handle = args.get("handle", "").lstrip("@")
        if not handle:
            return {"error": "handle is required"}
        result = await service.compare_user_vs_competitor(user_id=user_id, handle=handle)
        return result

    async def _tool_get_competitor_gaps(self, args: dict, user_id: str) -> dict:
        from app.services.content_intelligence import ContentIntelligenceService
        service = ContentIntelligenceService()
        handle = args.get("handle", "").lstrip("@")
        if not handle:
            return {"error": "handle is required"}
        result = await service.get_competitor_gaps(user_id=user_id, competitor_handle=handle)
        return result

    async def _tool_delete_competitor(self, args: dict, user_id: str) -> dict:
        from app.services.competitors import CompetitorService
        service = CompetitorService()
        handle = args.get("handle", "").lstrip("@")
        if not handle:
            return {"error": "handle is required"}
        await service.delete_competitor(user_id=user_id, handle=handle)
        return {"handle": handle, "deleted": True, "success": True}

    # ── Style Analyzer ───────────────────────────────────────────────────────

    async def _tool_analyze_account_style(self, args: dict, user_id: str) -> dict:
        from app.services.content_intelligence import ContentIntelligenceService
        username = args.get("username", "").lstrip("@")
        max_posts = int(args.get("max_posts", 30))
        account_type = args.get("account_type", "inspiration")

        if not username:
            return {"error": "username is required"}

        scraper = InstagramScraper()
        analyzer = StyleAnalyzer()
        content_intel = ContentIntelligenceService()

        profile_data, posts = await scraper.scrape(username, max_posts, user_id)
        if not posts:
            return {"error": f"No posts found for @{username}. Account may be private or not exist."}

        metrics = analyzer.analyze(posts, profile_data)

        saved = await content_intel.store_scrape(
            user_id=user_id,
            handle=username,
            account_type=account_type,
            display_name=profile_data.get("full_name", username),
            metadata={
                "followers": profile_data.get("followers", 0),
                "style_metrics": metrics,
            },
            posts=posts,
        )
        scrape_id = saved.get("account", {}).get("id", "")

        return {
            "scrape_id": scrape_id,
            "username": username,
            "followers": profile_data.get("followers", 0),
            "post_count": len(posts),
            "engagement_rate": metrics.get("engagement_rate", 0),
            "best_content_type": metrics.get("best_content_type"),
            "hook_types": metrics.get("hook_types", {}),
            "content_categories": metrics.get("content_categories", {}),
            "top_keywords": [k["word"] for k in metrics.get("top_keywords", [])[:10]],
            "posts_per_week": metrics.get("posts_per_week", 0),
            "optimal_caption_length": metrics.get("optimal_caption_length"),
            "optimal_hashtag_count": metrics.get("optimal_hashtag_count"),
            "consistency_score": metrics.get("consistency_score"),
            "note": "Analysis saved. Call apply_account_style with scrape_id to apply this style to your brand profile.",
        }

    async def _tool_apply_account_style(self, args: dict, user_id: str) -> dict:
        from app.services.content_intelligence import ContentIntelligenceService
        scrape_id = args.get("scrape_id", "")
        if not scrape_id:
            return {"error": "scrape_id is required — call analyze_account_style first"}

        content_intel = ContentIntelligenceService()
        brief = await content_intel.generate_brief(user_id=user_id, account_id=scrape_id)

        if not brief.get("ready"):
            return {"error": "Brief not ready. Try again in a moment."}

        content_style_brief = brief.get("content_style_brief") or brief.get("brief", "")
        supabase = get_supabase_admin()
        supabase.table("profiles").update(
            {"content_style_brief": content_style_brief}
        ).eq("id", user_id).execute()
        BrandService().invalidate_cache(user_id)

        return {
            "applied": True,
            "content_style_brief": content_style_brief,
            "scrape_id": scrape_id,
        }

    async def _tool_list_analyzed_accounts(self, user_id: str) -> dict:
        supabase = get_supabase_admin()
        result = (
            supabase.table("content_accounts")
            .select("id, handle, display_name, account_type, last_analyzed_at, metadata")
            .eq("user_id", user_id)
            .not_.is_("metadata", "null")
            .order("last_analyzed_at", desc=True)
            .limit(20)
            .execute()
        )
        accounts = []
        for row in result.data or []:
            meta = row.get("metadata") or {}
            accounts.append({
                "id": row["id"],
                "handle": row.get("handle"),
                "display_name": row.get("display_name"),
                "account_type": row.get("account_type"),
                "followers": meta.get("followers", 0),
                "last_analyzed_at": str(row.get("last_analyzed_at", "")),
            })
        return {"accounts": accounts, "total": len(accounts)}

    async def _tool_get_content_brief(self, args: dict, user_id: str) -> dict:
        from app.services.content_intelligence import ContentIntelligenceService
        account_id = args.get("account_id")

        if not account_id:
            # Use most recently analyzed account
            supabase = get_supabase_admin()
            result = (
                supabase.table("content_accounts")
                .select("id")
                .eq("user_id", user_id)
                .not_.is_("metadata", "null")
                .order("last_analyzed_at", desc=True)
                .limit(1)
                .execute()
            )
            if not result.data:
                return {"error": "No analyzed accounts found. Run analyze_account_style first."}
            account_id = result.data[0]["id"]

        content_intel = ContentIntelligenceService()
        brief = await content_intel.generate_brief(user_id=user_id, account_id=account_id)
        return brief

    # ── Social Intelligence Full Flow ────────────────────────────────────────

    async def _tool_social_generate_ideas(self, args: dict, user_id: str) -> dict:
        from app.services.social_intelligence import SocialIntelligenceService
        service = SocialIntelligenceService()
        return await service.generate_ideas(
            user_id=user_id,
            topic=args.get("topic"),
            research_run_id=args.get("research_run_id"),
            variations=int(args.get("variations", 6)),
        )

    async def _tool_social_generate_script(self, args: dict, user_id: str) -> dict:
        from app.services.social_intelligence import SocialIntelligenceService
        service = SocialIntelligenceService()
        return await service.generate_script(
            user_id=user_id,
            topic=args.get("topic"),
            idea_variation_id=args.get("idea_variation_id"),
            selected_hook=args.get("selected_hook"),
        )

    # ── Brand Profile Full Management ────────────────────────────────────────

    async def _tool_generate_brand_profile(self, args: dict, user_id: str) -> dict:
        engine = ProfileEngine()
        input_data = {
            "brand_name": args.get("brand_name", ""),
            "niche": args.get("niche", ""),
            "services_description": args.get("services_description", ""),
            "content_goals": args.get("content_goals", ""),
            "target_audience": args.get("target_audience", ""),
        }
        result = await engine.generate_profile(input_data)

        save_data = {}
        for field, value in result.items():
            if isinstance(value, dict) and "value" in value:
                save_data[field] = value["value"]
            elif isinstance(value, str):
                save_data[field] = value

        if args.get("brand_name"):
            save_data["brand_name"] = args["brand_name"]

        supabase = get_supabase_admin()
        supabase.table("profiles").upsert(
            {"id": user_id, **save_data}, on_conflict="id"
        ).execute()
        BrandService().invalidate_cache(user_id)

        return {"generated": save_data, "saved": True, "success": True}

    async def _tool_regenerate_profile_field(
        self, args: dict, user_id: str, profile: dict
    ) -> dict:
        engine = ProfileEngine()
        field = args.get("field_name", "")
        instruction = args.get("instruction", "")

        if not field:
            return {"error": "field_name is required"}

        result = await engine.regenerate_field(
            field_name=field,
            current_profile=profile,
            instruction=instruction,
        )

        supabase = get_supabase_admin()
        supabase.table("profiles").update(
            {field: result["new_value"]}
        ).eq("id", user_id).execute()
        BrandService().invalidate_cache(user_id)

        return {
            "field": field,
            "old_value": result.get("old_value"),
            "new_value": result.get("new_value"),
            "reasoning": result.get("reasoning"),
            "success": True,
        }

    # ── Content Library v2 ───────────────────────────────────────────────────

    async def _tool_list_content_paginated(self, args: dict, user_id: str) -> dict:
        from app.services.content_service import ContentService
        service = ContentService()
        page = int(args.get("page", 1))
        limit = min(int(args.get("limit", 20)), 50)
        content_type = args.get("content_type")
        published = args.get("published")

        result = await service.list_content(
            user_id=user_id,
            page=page,
            limit=limit,
            agent_type=content_type,
            published=published,
        )
        return result

    async def _tool_get_content_detail(self, args: dict, user_id: str) -> dict:
        from app.services.content_service import ContentService
        service = ContentService()
        content_id = args.get("content_id", "")
        if not content_id:
            return {"error": "content_id is required"}
        try:
            result = await service.get_content(user_id=user_id, content_id=content_id)
            return result
        except Exception as exc:
            return {"error": str(exc)}

    async def _tool_update_content_metadata(self, args: dict, user_id: str) -> dict:
        from app.services.content_service import ContentService
        service = ContentService()
        content_id = args.get("content_id", "")
        if not content_id:
            return {"error": "content_id is required"}
        try:
            result = await service.update_content(
                user_id=user_id,
                content_id=content_id,
                title=args.get("title"),
                caption=args.get("caption"),
            )
            return {"updated": result, "success": True}
        except Exception as exc:
            return {"error": str(exc)}

# ── System Prompt Builder ────────────────────────────────────────────────────

def _build_system_prompt(profile: dict, learning_summary: str = "") -> str:
    brand_name = profile.get("brand_name") or "tu marca"
    display_name = brand_name
    brand_voice = profile.get("brand_voice") or "professional"
    target_audience = profile.get("target_audience") or "health professionals' patients"
    services = profile.get("services_offered") or ""
    cta = profile.get("cta") or ""
    credits_used = profile.get("credits_used") or 0
    credits_limit = profile.get("credits_limit") or 0
    credits_remaining = max(0, credits_limit - credits_used)

    learning_block = ""
    if learning_summary:
        learning_block = f"\n## Preferencias aprendidas del usuario\n{learning_summary}\n"

    return f"""You are PelviBiz AI — the content creation assistant for {brand_name}.

## Who you're talking to
- **Brand:** {brand_name}
- **Voice & Tone:** {brand_voice}
- **Target Audience:** {target_audience}
- **Services:** {services}
- **CTA:** {cta}
- **Credits available:** {credits_remaining} of {credits_limit}
{learning_block}
## Your full tool suite

### Content Creation
- **`generate_ai_carousel`** — AI carousel with AI-generated images (no user photos needed)
- **`generate_real_carousel`** — Carousel using the user's own photos with brand overlays
- **`fix_carousel_slide`** — Replace text or image on a single carousel slide
- **`generate_draft`** — Slide texts + caption for any topic
- **`suggest_ideas`** — Creative ideas for carousels or videos
- **`generate_video`** — Short video with 6 templates (myth-buster, bullet-sequence, viral-reaction, testimonial-story, big-quote, deep-dive)
- **`trim_video`** — Trim a video clip to a specific start/end time
- **`creatomate_list_templates`** — List all available Creatomate video templates
- **`creatomate_render_template`** — Render any Creatomate template with custom content
- **`creatomate_render_with_voice`** — Render a template with AI voiceover
- **`creatomate_get_render_status`** — Check render progress

### Research & Scripts
- **`research_content`** — Research trending topics (Reddit, news, YouTube)
- **`social_research`** — What's working on IG, TikTok, Facebook, Google
- **`social_generate_ideas`** — Turn research results into content ideas
- **`social_generate_script`** — Full video script + filming card + caption + CTA
- **`generate_hooks`** — Scroll-stopping hooks for any topic
- **`generate_script`** — Reel script + filming guide

### Competitors & Style Analysis
- **`list_competitors`** — List all tracked competitor accounts
- **`add_competitor`** — Add an Instagram account to track
- **`compare_with_competitor`** — Full comparison vs a competitor (gaps, shared topics, viral posts)
- **`get_competitor_gaps`** — Content gaps vs a specific competitor
- **`delete_competitor`** — Remove a competitor from tracking
- **`analyze_account_style`** — Full style analysis of any IG account (hooks, captions, hashtags, AI recommendations)
- **`apply_account_style`** — Apply analyzed style to brand profile
- **`list_analyzed_accounts`** — List previously analyzed accounts
- **`get_content_brief`** — Content strategy brief from an analyzed account

### Brand & Profile
- **`generate_brand_profile`** — Generate a complete brand profile from scratch with AI
- **`check_profile`** — View full brand profile
- **`update_profile_field`** — Update brand voice, CTA, audience, services, keywords
- **`regenerate_profile_field`** — Regenerate any profile field with specific instruction (more fields than update)
- **`get_brand_stories`** — View saved brand stories
- **`create_brand_story`** — Save a new personal story

### Content Library
- **`list_content_paginated`** — Paginated content library with filters
- **`check_content_library`** — Quick view of recent content
- **`get_content_detail`** — Full details of a specific content item
- **`update_content_metadata`** — Update title or caption of any content
- **`schedule_content`** — Schedule a post for a future date
- **`publish_content`** — Mark content as published
- **`unpublish_content`** — Revert published content to draft
- **`delete_content`** — Delete content from library
- **`get_content_stats`** — Usage statistics by type

### Analytics & Insights
- **`analyze_instagram`** — Quick Instagram account analysis
- **`get_learning_summary`** — Patterns learned from past content
- **`get_account_info`** — Credits and account details

## Behavior rules

1. **ON FIRST MESSAGE**: Greet {display_name} by name. Give ONE summary of what you can do. Ask what they want to start with TODAY — offer 3 concrete options based on their profile ({brand_name}, {services}).

2. **ACT IMMEDIATELY**: When user says "create a carousel about X" → call `generate_ai_carousel` NOW. Don't ask for style confirmation. Extract slide_count from message ('6 slides' = 6). Default: 5.

3. **GUIDE STEP BY STEP**: After generating content, explain what they can do next (publish, schedule, generate more). Always offer the logical next step.

4. **NEVER more than ONE question** at a time. Prefer using defaults and generating.

5. **After generating**: Confirm what was created and show the caption. If there are `media_urls`, tell them the content is ready.

6. **SHORT responses**: max 3-4 sentences before/after tool calls.

7. **Language**: ALWAYS respond in English, regardless of what language the user writes in.

8. **Recommended workflow** for new users:
   - Step 1: Research niche trends → `research_content` or `social_research`
   - Step 2: Generate ideas → `social_generate_ideas` or `suggest_ideas`
   - Step 3: Create carousel or video → `generate_ai_carousel` or `generate_video`
   - Step 4: Schedule publishing → `schedule_content`

9. **For competitors**: When user asks to analyze competition → `add_competitor` + `compare_with_competitor` + `get_competitor_gaps`.

10. **For brand setup**: If profile seems incomplete → offer `generate_brand_profile` to set everything at once.
"""
