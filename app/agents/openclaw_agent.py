"""OpenClaw agent — PelviBiz AI with real tool calling via OpenClaw gateway."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncGenerator, Awaitable, Callable

import httpx

from app.agents.base import BaseStreamingAgent
from app.core.streaming import text_chunk, finish_event, error_event
from app.services.brand import BrandService
from app.config import get_settings

logger = logging.getLogger(__name__)

_API_BASE = "http://localhost:8100/api/v1"
_MAX_TOOL_ROUNDS = 5

_TOOL_LABELS: dict[str, str] = {
    "get_workspace_context": "Loading your workspace...",
    "get_brand_profile": "Checking your brand profile...",
    "update_brand_profile": "Updating brand profile...",
    "refresh_blotato_connections": "Connecting to Blotato...",
    "get_user_preferences": "Checking your preferences...",
    "update_user_preferences": "Updating preferences...",
    "list_content_library": "Browsing your content library...",
    "get_content_detail": "Loading content...",
    "publish_content": "Publishing content...",
    "schedule_content": "Scheduling post...",
    "unpublish_content": "Unpublishing content...",
    "generate_research": "Researching topics...",
    "latest_research": "Loading recent research...",
    "generate_ideation": "Generating ideas...",
    "latest_ideas": "Loading latest ideas...",
    "generate_hooks": "Crafting hooks...",
    "generate_script": "Writing script...",
    "latest_hooks": "Loading recent hooks...",
    "latest_scripts": "Loading recent scripts...",
    "compare_competitors": "Analyzing competitors...",
    "get_competitor_gaps": "Finding content gaps...",
    "get_brand_stories": "Loading brand stories...",
    "create_brand_story": "Saving brand story...",
    "list_conversations": "Loading conversations...",
    "get_conversation": "Loading conversation...",
    "get_conversation_messages": "Loading messages...",
    "generate_carousel": "Generating carousel...",
    "fix_carousel_slide": "Fixing slide...",
    "generate_ai_carousel": "Generating AI carousel...",
    "fix_ai_carousel_slide": "Fixing AI slide...",
    "generate_post": "Generating post...",
    "generate_video": "Generating video...",
    "trim_video": "Trimming video...",
    "social_research": "Researching social media...",
    "social_ideate": "Brainstorming viral ideas...",
    "social_script": "Writing social script...",
    "compare_social_accounts": "Comparing social accounts...",
}

OPENCLAW_AGENT_PROMPT = """You are PelviBiz AI, the fast concierge for this app.

- Help clients use the backend tools quickly and well.
- Be friendly, direct, and useful. Greet briefly, then get to the point.
- Prefer action over explanation.
- Ask at most one short clarifying question only when a required input is missing.
- For brand-setting or profile questions, inspect the profile and preferences first, then update them or give a concrete next step.
- When the user wants a carousel, post, video, trim, research, ideas, hooks, or scripts, use the relevant tool immediately.
- When the user asks for social research, use the social intelligence tools to research Instagram, Facebook, TikTok, and Google, then turn that into ideas and scripts.
- Return the generated asset or the exact next action, not a long essay.
"""


def _dump(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False)


def _tool(name: str, description: str, properties: dict[str, Any], required: list[str] | None = None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required or [],
            },
        },
    }

# ── Tool Definitions ──────────────────────────────────────────────────────────

TOOLS: list[dict] = [
    _tool("get_workspace_context", "Get a fast, combined snapshot of the user's brand, preferences, content, research, ideas, scripts, conversations, stories, and competitors.", {
        "sections": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": ["brand_profile", "preferences", "content_usage", "content", "research", "ideas", "hooks", "scripts", "stories", "competitors", "conversations", "learning", "social_research", "social_ideas", "social_scripts"],
            },
            "description": "Optional sections to include. Leave empty for the default full snapshot.",
        },
        "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5, "description": "How many rows to fetch for list-style sections."},
    }),
    _tool("get_brand_profile", "Get the current brand profile and all stored brand settings.", {}),
    _tool("update_brand_profile", "Update brand settings, brand voice, colors, CTA, visual identity, logo, and Blotato connection data.", {
        "display_name": {"type": "string"},
        "brand_name": {"type": "string"},
        "brand_color_primary": {"type": "string"},
        "brand_color_secondary": {"type": "string"},
        "brand_color_background": {"type": "string"},
        "font_style": {"type": "string"},
        "font_size": {"type": "string"},
        "font_prompt": {"type": "string"},
        "services_offered": {"type": "string"},
        "target_audience": {"type": "string"},
        "visual_identity": {"type": "string"},
        "keywords": {"type": "string"},
        "cta": {"type": "string"},
        "content_style_brief": {"type": "string"},
        "brand_stories": {"type": "string"},
        "visual_environment_setup": {"type": "string"},
        "visual_subject_outfit_face": {"type": "string"},
        "visual_subject_outfit_generic": {"type": "string"},
        "font_style_secondary": {"type": "string"},
        "font_prompt_secondary": {"type": "string"},
        "logo_url": {"type": "string"},
        "timezone": {"type": "string"},
        "blotato_connections": {"type": "object"},
        "blotato_ig_id": {"type": "string"},
        "blotato_fb_id": {"type": "string"},
        "blotato_fb_account_id": {"type": "string"},
    }),
    _tool("refresh_blotato_connections", "Import the user's connected Blotato account IDs into the profile.", {}),
    _tool("get_user_preferences", "Get the user's preferences and learning brief.", {}),
    _tool("update_user_preferences", "Update user learning preferences and content defaults.", {
        "preferred_topics": {"type": "array", "items": {"type": "string"}},
        "preferred_slide_count": {"type": "integer"},
        "preferred_position": {"type": "string"},
        "caption_edit_style": {"type": "string"},
    }),
    _tool("list_content_library", "List recent generated content, including carousels, reels, and posts.", {
        "agent_type": {"type": "string"},
        "published": {"type": "boolean"},
        "page": {"type": "integer", "minimum": 1, "default": 1},
        "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 10},
    }),
    _tool("get_content_detail", "Get a single content item by ID.", {"content_id": {"type": "string"}}, ["content_id"]),
    _tool("publish_content", "Mark a content item as published and optionally override the caption.", {
        "content_id": {"type": "string"},
        "caption": {"type": "string"},
    }, ["content_id"]),
    _tool("schedule_content", "Schedule a content item for future publication.", {
        "content_id": {"type": "string"},
        "scheduled_date": {"type": "string"},
        "caption": {"type": "string"},
    }, ["content_id", "scheduled_date"]),
    _tool("unpublish_content", "Mark a content item as unpublished.", {"content_id": {"type": "string"}}, ["content_id"]),
    _tool("generate_research", "Run content research for a niche and return the strongest topics.", {
        "niche": {"type": "string"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 10},
        "sources": {"type": "array", "items": {"type": "string"}},
        "competitor_handle": {"type": "string"},
    }, ["niche"]),
    _tool("latest_research", "Get the user's latest research runs.", {
        "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
    }),
    _tool("generate_ideation", "Create content idea variations from research.", {
        "niche": {"type": "string"},
        "research_topic_id": {"type": "string"},
        "research_run_id": {"type": "string"},
        "variations_per_topic": {"type": "integer", "minimum": 1, "maximum": 5, "default": 5},
        "topic_limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 3},
        "competitor_handle": {"type": "string"},
    }, ["niche"]),
    _tool("latest_ideas", "Get the user's latest idea variations.", {
        "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
    }),
    _tool("generate_hooks", "Generate hook options for a topic.", {
        "topic": {"type": "string"},
        "research_topic_id": {"type": "string"},
        "idea_variation_id": {"type": "string"},
        "count": {"type": "integer", "minimum": 1, "maximum": 6, "default": 6},
        "competitor_handle": {"type": "string"},
    }),
    _tool("generate_script", "Generate a short-form script and filming card.", {
        "topic": {"type": "string"},
        "research_topic_id": {"type": "string"},
        "idea_variation_id": {"type": "string"},
        "selected_hook": {"type": "string"},
        "competitor_handle": {"type": "string"},
    }),
    _tool("latest_hooks", "Get the user's latest hook packs.", {
        "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
    }),
    _tool("latest_scripts", "Get the user's latest scripts.", {
        "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
    }),
    _tool("compare_competitors", "Compare the user's account against one or two competitor handles.", {
        "own_handle": {"type": "string"},
        "competitor_handles": {"type": "array", "items": {"type": "string"}},
        "window_days": {"type": "integer", "minimum": 1, "maximum": 365, "default": 30},
        "force_recompute": {"type": "boolean", "default": False},
    }, ["own_handle", "competitor_handles"]),
    _tool("get_competitor_gaps", "Get hook, topic, and white-space gaps for a competitor.", {"handle": {"type": "string"}}, ["handle"]),
    _tool("get_brand_stories", "List the user's brand stories.", {}),
    _tool("create_brand_story", "Create a new brand story for future brand context.", {
        "title": {"type": "string"},
        "content": {"type": "string"},
    }, ["title", "content"]),
    _tool("list_conversations", "List recent conversations for the user.", {
        "agent_type": {"type": "string"},
        "page": {"type": "integer", "minimum": 1, "default": 1},
        "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 10},
    }),
    _tool("get_conversation", "Get a single conversation and its metadata.", {"conversation_id": {"type": "string"}}, ["conversation_id"]),
    _tool("get_conversation_messages", "List messages for a conversation.", {
        "conversation_id": {"type": "string"},
        "page": {"type": "integer", "minimum": 1, "default": 1},
        "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
    }, ["conversation_id"]),
    _tool("generate_carousel", "Generate a manual carousel from uploaded images and slide text.", {
        "message": {"type": "string"},
        "slides": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "image_url": {"type": "string"},
                    "text": {"type": "string"},
                    "text_position": {"type": "string"},
                    "number": {"type": "integer"},
                },
            },
        },
        "Brand_Name": {"type": "string"},
        "Brand_Voice": {"type": "string"},
        "Brand_Color_Primary": {"type": "string"},
        "Brand_Color_Secondary": {"type": "string"},
        "Font_Style": {"type": "string"},
        "Font_Size": {"type": "string"},
        "Font_Prompt": {"type": "string"},
        "CTA": {"type": "string"},
        "Keywords": {"type": "string"},
        "Target_Audience": {"type": "string"},
        "Services_Offered": {"type": "string"},
        "Content_Style_Brief": {"type": "string"},
        "Logo_URL": {"type": "string"},
    }, ["message", "slides"]),
    _tool("fix_carousel_slide", "Fix a single slide in an existing carousel.", {
        "Slide_Number": {"type": "integer", "minimum": 1, "maximum": 10},
        "New_Text_Content": {"type": "string"},
        "New_Text_Position": {"type": "string"},
        "New_Image_Link": {"type": "string"},
        "Row_ID": {"type": "string"},
    }, ["Slide_Number", "New_Image_Link", "Row_ID"]),
    _tool("generate_ai_carousel", "Generate an AI carousel with generic or card slides.", {
        "message": {"type": "string"},
        "slide_count": {"type": "integer", "minimum": 3, "maximum": 8, "default": 5},
        "slides": {"type": "array", "items": {"type": "object"}},
    }, ["message"]),
    _tool("fix_ai_carousel_slide", "Fix a single slide in an AI carousel.", {
        "Slide_Number": {"type": "integer", "minimum": 1, "maximum": 10},
        "New_Text_Content": {"type": "string"},
        "Row_ID": {"type": "string"},
        "slide_type": {"type": "string"},
    }, ["Slide_Number", "New_Text_Content", "Row_ID"]),
    _tool("generate_post", "Generate a branded post image from text fields and caption.", {
        "template_key": {"type": "string"},
        "template_label": {"type": "string"},
        "topic": {"type": "string"},
        "text_fields": {"type": "object"},
        "caption": {"type": "string"},
        "message_id": {"type": "string"},
        "conversation_id": {"type": "string"},
        "reference_image_url": {"type": "string"},
        "brand_name": {"type": "string"},
        "brand_color_primary": {"type": "string"},
        "brand_color_secondary": {"type": "string"},
        "brand_voice": {"type": "string"},
        "target_audience": {"type": "string"},
        "services_offered": {"type": "string"},
        "keywords": {"type": "string"},
        "font_style": {"type": "string"},
        "font_prompt": {"type": "string"},
        "font_size": {"type": "string"},
        "visual_environment": {"type": "string"},
        "visual_subject_face": {"type": "string"},
        "visual_subject_generic": {"type": "string"},
        "visual_identity": {"type": "string"},
        "content_style_brief": {"type": "string"},
        "cta": {"type": "string"},
    }, ["template_key", "template_label", "topic", "message_id"]),
    _tool("generate_video", "Generate a branded video from templates, clips, text, music, and captions.", {
        "template": {"type": "string"},
        "video_urls": {"type": "array", "items": {"type": "string"}},
        "text_1": {"type": "string"},
        "text_2": {"type": "string"},
        "text_3": {"type": "string"},
        "text_4": {"type": "string"},
        "text_5": {"type": "string"},
        "text_6": {"type": "string"},
        "text_7": {"type": "string"},
        "text_8": {"type": "string"},
        "caption": {"type": "string"},
        "music_track": {"type": "string"},
        "music_volume": {"type": "number"},
        "text_position": {"type": "string"},
        "enable_captions": {"type": "boolean"},
        "message_id": {"type": "string"},
        "client_id": {"type": "string"},
    }, ["template", "video_urls"]),
    _tool("trim_video", "Trim a video and store the resulting asset.", {
        "source_url": {"type": "string"},
        "template_key": {"type": "string"},
        "mode": {"type": "string", "enum": ["template", "manual"], "default": "manual"},
        "start_seconds": {"type": "number"},
        "end_seconds": {"type": "number"},
    }, ["source_url", "start_seconds", "end_seconds"]),
    _tool("social_research", "Research a topic across Instagram, Facebook, TikTok, and Google, save the context, and return a ranked brief.", {
        "topic": {"type": "string"},
        "platforms": {"type": "array", "items": {"type": "string", "enum": ["instagram", "facebook", "tiktok", "google"]}},
        "limit": {"type": "integer", "minimum": 1, "maximum": 30, "default": 12},
        "language": {"type": "string", "default": "en"},
    }, ["topic"]),
    _tool("social_ideate", "Turn a saved social research run into 6 strong viral ideas with hooks and reasoning.", {
        "topic": {"type": "string"},
        "research_run_id": {"type": "string"},
        "research_item_id": {"type": "string"},
        "variations": {"type": "integer", "minimum": 1, "maximum": 6, "default": 6},
    }),
    _tool("social_script", "Turn a selected social idea into a specialized hook pack and script for carousel, reel, or post.", {
        "topic": {"type": "string"},
        "research_run_id": {"type": "string"},
        "idea_variation_id": {"type": "string"},
        "selected_hook": {"type": "string"},
    }),
    _tool("compare_social_accounts", "Compare Instagram accounts analytically after ensuring they are stored in the content intelligence layer.", {
        "own_handle": {"type": "string"},
        "competitor_handles": {"type": "array", "items": {"type": "string"}},
        "platform": {"type": "string", "enum": ["instagram", "facebook", "tiktok", "google"], "default": "instagram"},
        "window_days": {"type": "integer", "minimum": 1, "maximum": 365, "default": 30},
        "force_recompute": {"type": "boolean", "default": False},
    }, ["own_handle", "competitor_handles"]),
]


# ── Tool Executor ─────────────────────────────────────────────────────────────

class _ToolExecutor:
    """Executes PelviBiz API tools on behalf of the agent."""

    def __init__(self, user_id: str):
        self._user_id = user_id
        settings = get_settings()
        self._headers = {
            "X-Internal-Key": settings.internal_api_key,
            "X-User-Id": user_id,
            "Content-Type": "application/json",
        }
        self._handlers: dict[str, Callable[[dict], Awaitable[str]]] = {
            "get_workspace_context": self._get_workspace_context,
            "get_brand_profile": self._get_brand_profile,
            "update_brand_profile": self._update_brand_profile,
            "refresh_blotato_connections": self._refresh_blotato_connections,
            "get_user_preferences": self._get_user_preferences,
            "update_user_preferences": self._update_user_preferences,
            "list_content_library": self._list_content_library,
            "get_content_detail": self._get_content_detail,
            "publish_content": self._publish_content,
            "schedule_content": self._schedule_content,
            "unpublish_content": self._unpublish_content,
            "generate_research": self._generate_research,
            "latest_research": self._latest_research,
            "generate_ideation": self._generate_ideation,
            "latest_ideas": self._latest_ideas,
            "generate_hooks": self._generate_hooks,
            "generate_script": self._generate_script,
            "latest_hooks": self._latest_hooks,
            "latest_scripts": self._latest_scripts,
            "compare_competitors": self._compare_competitors,
            "get_competitor_gaps": self._get_competitor_gaps,
            "get_brand_stories": self._get_brand_stories,
            "create_brand_story": self._create_brand_story,
            "list_conversations": self._list_conversations,
            "get_conversation": self._get_conversation,
            "get_conversation_messages": self._get_conversation_messages,
            "generate_carousel": self._generate_carousel,
            "fix_carousel_slide": self._fix_carousel_slide,
            "generate_ai_carousel": self._generate_ai_carousel,
            "fix_ai_carousel_slide": self._fix_ai_carousel_slide,
            "generate_post": self._generate_post,
            "generate_video": self._generate_video,
            "trim_video": self._trim_video,
            "social_research": self._social_research,
            "social_ideate": self._social_ideate,
            "social_script": self._social_script,
            "compare_social_accounts": self._compare_social_accounts,
        }

    async def run(self, name: str, args: dict) -> str:
        """Execute a tool and return a JSON string result."""
        try:
            handler = self._handlers.get(name)
            if not handler:
                return _dump({"error": f"Unknown tool: {name}"})
            return await handler(args)
        except Exception as exc:
            logger.error("Tool %s failed: %s", name, exc)
            return _dump({"error": str(exc)})

    async def _request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        params: dict | None = None,
        timeout: float = 30.0,
    ) -> dict:
        async with httpx.AsyncClient() as http:
            r = await http.request(
                method,
                f"{_API_BASE}{path}",
                headers=self._headers,
                json=body,
                params=params,
                timeout=timeout,
            )
            r.raise_for_status()
            if not r.content:
                return {}
            return r.json()

    async def _get(self, path: str, params: dict | None = None, timeout: float = 30.0) -> dict:
        return await self._request("GET", path, params=params, timeout=timeout)

    async def _post(self, path: str, body: dict, timeout: float = 120.0) -> dict:
        return await self._request("POST", path, body=body, timeout=timeout)

    async def _put(self, path: str, body: dict, timeout: float = 30.0) -> dict:
        return await self._request("PUT", path, body=body, timeout=timeout)

    async def _patch(self, path: str, body: dict, timeout: float = 30.0) -> dict:
        return await self._request("PATCH", path, body=body, timeout=timeout)

    async def _delete(self, path: str, timeout: float = 30.0) -> dict:
        return await self._request("DELETE", path, timeout=timeout)

    async def _get_workspace_context(self, args: dict) -> str:
        sections = args.get("sections") or [
            "brand_profile",
            "preferences",
            "content_usage",
            "content",
            "research",
            "ideas",
            "hooks",
            "scripts",
            "stories",
            "competitors",
            "conversations",
            "learning",
        ]
        limit = int(args.get("limit", 5) or 5)
        limit = max(1, min(limit, 20))

        tasks: list[tuple[str, Awaitable[dict]]] = []
        if "brand_profile" in sections:
            tasks.append(("brand_profile", self._get("/auth/profile")))
        if "preferences" in sections:
            tasks.append(("preferences", self._get("/user/preferences")))
        if "content_usage" in sections:
            tasks.append(("content_usage", self._get("/content/usage")))
        if "content" in sections:
            tasks.append(("content", self._get("/content/list", params={"page": 1, "limit": limit})))
        if "research" in sections:
            tasks.append(("research", self._get("/research/latest", params={"limit": limit})))
        if "ideas" in sections:
            tasks.append(("ideas", self._get("/ideation/latest", params={"limit": limit})))
        if "hooks" in sections:
            tasks.append(("hooks", self._get("/scripting/hooks/latest", params={"limit": limit})))
        if "scripts" in sections:
            tasks.append(("scripts", self._get("/scripting/scripts/latest", params={"limit": limit})))
        if "stories" in sections:
            tasks.append(("stories", self._get("/brand/stories")))
        if "competitors" in sections:
            tasks.append(("competitors", self._get("/competitors")))
        if "conversations" in sections:
            tasks.append(("conversations", self._get("/conversations", params={"page": 1, "limit": limit})))
        if "learning" in sections:
            tasks.append(("learning", self._get("/user/learning/patterns")))
        if "social_research" in sections:
            tasks.append(("social_research", self._get("/social/research/latest", params={"limit": limit})))
        if "social_ideas" in sections:
            tasks.append(("social_ideas", self._get("/social/ideas/latest", params={"limit": limit})))
        if "social_scripts" in sections:
            tasks.append(("social_scripts", self._get("/social/scripts/latest", params={"limit": limit})))

        results = await asyncio.gather(*(task for _, task in tasks), return_exceptions=True)
        payload: dict[str, Any] = {}
        for (name, _), result in zip(tasks, results, strict=False):
            if isinstance(result, Exception):
                payload[name] = {"error": str(result)}
            else:
                payload[name] = result
        return _dump(payload)

    async def _get_brand_profile(self, args: dict | None = None) -> str:
        data = await self._get("/auth/profile")
        return _dump(data)

    async def _update_brand_profile(self, args: dict) -> str:
        data = await self._put("/auth/profile", args)
        return _dump(data)

    async def _refresh_blotato_connections(self, args: dict) -> str:
        data = await self._post("/auth/blotato/refresh-connections", {})
        return _dump(data)

    async def _get_user_preferences(self, args: dict) -> str:
        data = await self._get("/user/preferences")
        return _dump(data)

    async def _update_user_preferences(self, args: dict) -> str:
        data = await self._put("/user/preferences", args)
        return _dump(data)

    async def _list_content_library(self, args: dict) -> str:
        params = {
            "page": int(args.get("page", 1) or 1),
            "limit": int(args.get("limit", 10) or 10),
        }
        if args.get("agent_type"):
            params["agent_type"] = args["agent_type"]
        if args.get("published") is not None:
            params["published"] = args["published"]
        data = await self._get("/content/list", params=params)
        return _dump(data)

    async def _get_content_detail(self, args: dict) -> str:
        data = await self._get(f"/content/{args['content_id']}")
        return _dump(data)

    async def _publish_content(self, args: dict) -> str:
        payload = {"caption": args.get("caption")}
        data = await self._post(f"/content/{args['content_id']}/publish", payload)
        return _dump(data)

    async def _schedule_content(self, args: dict) -> str:
        payload = {
            "scheduled_date": args["scheduled_date"],
            "caption": args.get("caption"),
        }
        data = await self._post(f"/content/{args['content_id']}/schedule", payload)
        return _dump(data)

    async def _unpublish_content(self, args: dict) -> str:
        data = await self._post(f"/content/{args['content_id']}/unpublish", {})
        return _dump(data)

    async def _generate_research(self, args: dict) -> str:
        payload = {
            "niche": args["niche"],
            "limit": args.get("limit", 10),
            "sources": args.get("sources") or ["reddit", "news", "youtube"],
            "competitor_handle": args.get("competitor_handle"),
        }
        data = await self._post("/research/daily", payload, timeout=120.0)
        return _dump(data)

    async def _latest_research(self, args: dict) -> str:
        data = await self._get("/research/latest", params={"limit": int(args.get("limit", 5) or 5)})
        return _dump(data)

    async def _generate_ideation(self, args: dict) -> str:
        payload = {
            "niche": args["niche"],
            "research_topic_id": args.get("research_topic_id"),
            "research_run_id": args.get("research_run_id"),
            "variations_per_topic": args.get("variations_per_topic", 5),
            "topic_limit": args.get("topic_limit", 3),
            "competitor_handle": args.get("competitor_handle"),
        }
        data = await self._post("/ideation/from-research", payload, timeout=120.0)
        return _dump(data)

    async def _latest_ideas(self, args: dict) -> str:
        data = await self._get("/ideation/latest", params={"limit": int(args.get("limit", 5) or 5)})
        return _dump(data)

    async def _generate_hooks(self, args: dict) -> str:
        payload = {
            "topic": args.get("topic"),
            "research_topic_id": args.get("research_topic_id"),
            "idea_variation_id": args.get("idea_variation_id"),
            "count": args.get("count", 6),
            "competitor_handle": args.get("competitor_handle"),
        }
        data = await self._post("/scripting/hooks", payload, timeout=120.0)
        return _dump(data)

    async def _generate_script(self, args: dict) -> str:
        payload = {
            "topic": args.get("topic"),
            "research_topic_id": args.get("research_topic_id"),
            "idea_variation_id": args.get("idea_variation_id"),
            "selected_hook": args.get("selected_hook"),
            "competitor_handle": args.get("competitor_handle"),
        }
        data = await self._post("/scripting/script", payload, timeout=120.0)
        return _dump(data)

    async def _latest_hooks(self, args: dict) -> str:
        data = await self._get("/scripting/hooks/latest", params={"limit": int(args.get("limit", 5) or 5)})
        return _dump(data)

    async def _latest_scripts(self, args: dict) -> str:
        data = await self._get("/scripting/scripts/latest", params={"limit": int(args.get("limit", 5) or 5)})
        return _dump(data)

    async def _compare_competitors(self, args: dict) -> str:
        payload = {
            "own_handle": args["own_handle"],
            "competitor_handles": args.get("competitor_handles") or [],
            "window_days": args.get("window_days", 30),
            "force_recompute": args.get("force_recompute", False),
        }
        data = await self._post("/competitors/compare", payload, timeout=120.0)
        return _dump(data)

    async def _get_competitor_gaps(self, args: dict) -> str:
        data = await self._get(f"/competitors/{args['handle']}/gaps")
        return _dump(data)

    async def _get_brand_stories(self, args: dict) -> str:
        data = await self._get("/brand/stories")
        return _dump(data)

    async def _create_brand_story(self, args: dict) -> str:
        data = await self._post("/brand/stories", {"title": args["title"], "content": args["content"]}, timeout=120.0)
        return _dump(data)

    async def _list_conversations(self, args: dict) -> str:
        params = {
            "page": int(args.get("page", 1) or 1),
            "limit": int(args.get("limit", 10) or 10),
        }
        if args.get("agent_type"):
            params["agent_type"] = args["agent_type"]
        data = await self._get("/conversations", params=params)
        return _dump(data)

    async def _get_conversation(self, args: dict) -> str:
        data = await self._get(f"/conversations/{args['conversation_id']}")
        return _dump(data)

    async def _get_conversation_messages(self, args: dict) -> str:
        params = {
            "page": int(args.get("page", 1) or 1),
            "limit": int(args.get("limit", 20) or 20),
        }
        data = await self._get(f"/conversations/{args['conversation_id']}/messages", params=params)
        return _dump(data)

    async def _generate_carousel(self, args: dict) -> str:
        payload = {
            "agent_type": "real-carousel",
            "message": args["message"],
            "slides": args["slides"],
            "Brand_Name": args.get("Brand_Name"),
            "Brand_Voice": args.get("Brand_Voice"),
            "Brand_Color_Primary": args.get("Brand_Color_Primary"),
            "Brand_Color_Secondary": args.get("Brand_Color_Secondary"),
            "Font_Style": args.get("Font_Style"),
            "Font_Size": args.get("Font_Size"),
            "Font_Prompt": args.get("Font_Prompt"),
            "CTA": args.get("CTA"),
            "Keywords": args.get("Keywords"),
            "Target_Audience": args.get("Target_Audience"),
            "Services_Offered": args.get("Services_Offered"),
            "Content_Style_Brief": args.get("Content_Style_Brief"),
            "Logo_URL": args.get("Logo_URL"),
        }
        data = await self._post("/carousel/generate", payload, timeout=180.0)
        return _dump(data)

    async def _fix_carousel_slide(self, args: dict) -> str:
        payload = {
            "fix_slide": True,
            "action_type": "fix_image",
            "Slide_Number": args["Slide_Number"],
            "New_Text_Content": args.get("New_Text_Content"),
            "New_Text_Position": args.get("New_Text_Position"),
            "New_Image_Link": args["New_Image_Link"],
            "Row_ID": args["Row_ID"],
        }
        data = await self._post("/carousel/fix-slide", payload, timeout=180.0)
        return _dump(data)

    async def _generate_ai_carousel(self, args: dict) -> str:
        payload = {
            "message": args["message"],
            "slide_count": args.get("slide_count", 5),
        }
        if args.get("slides") is not None:
            payload["slides"] = args["slides"]
        data = await self._post("/ai-carousel/generate", payload, timeout=180.0)
        return _dump(data)

    async def _fix_ai_carousel_slide(self, args: dict) -> str:
        payload = {
            "Slide_Number": args["Slide_Number"],
            "New_Text_Content": args.get("New_Text_Content"),
            "Row_ID": args["Row_ID"],
            "slide_type": args.get("slide_type"),
        }
        data = await self._post("/ai-carousel/fix-slide", payload, timeout=180.0)
        return _dump(data)

    async def _generate_post(self, args: dict) -> str:
        data = await self._post("/post/generate", args, timeout=180.0)
        return _dump(data)

    async def _generate_video(self, args: dict) -> str:
        data = await self._post("/video/generate", args, timeout=300.0)
        return _dump(data)

    async def _trim_video(self, args: dict) -> str:
        data = await self._post("/video-trim", args, timeout=180.0)
        return _dump(data)

    async def _social_research(self, args: dict) -> str:
        payload = {
            "topic": args["topic"],
            "platforms": args.get("platforms") or ["instagram", "facebook", "tiktok", "google"],
            "limit": args.get("limit", 12),
            "language": args.get("language", "en"),
        }
        data = await self._post("/social/research", payload, timeout=180.0)
        return _dump(data)

    async def _social_ideate(self, args: dict) -> str:
        payload = {
            "topic": args.get("topic"),
            "research_run_id": args.get("research_run_id"),
            "research_item_id": args.get("research_item_id"),
            "variations": args.get("variations", 6),
        }
        data = await self._post("/social/ideas", payload, timeout=180.0)
        return _dump(data)

    async def _social_script(self, args: dict) -> str:
        payload = {
            "topic": args.get("topic"),
            "research_run_id": args.get("research_run_id"),
            "idea_variation_id": args.get("idea_variation_id"),
            "selected_hook": args.get("selected_hook"),
        }
        data = await self._post("/social/script", payload, timeout=180.0)
        return _dump(data)

    async def _compare_social_accounts(self, args: dict) -> str:
        payload = {
            "own_handle": args["own_handle"],
            "competitor_handles": args.get("competitor_handles") or [],
            "platform": args.get("platform", "instagram"),
            "window_days": args.get("window_days", 30),
            "force_recompute": args.get("force_recompute", False),
        }
        data = await self._post("/social/compare", payload, timeout=180.0)
        return _dump(data)


# ── Agent ─────────────────────────────────────────────────────────────────────

class OpenClawAgent(BaseStreamingAgent):
    """Streaming agent that proxies to the OpenClaw pelvibiz-users agent.

    Implements a full tool-calling agentic loop:
    1. Non-streaming call with tool definitions
    2. Execute tool calls if present, append results
    3. Repeat up to _MAX_TOOL_ROUNDS
    4. Stream the final text response
    """

    @property
    def system_prompt(self) -> str:
        return OPENCLAW_AGENT_PROMPT

    @property
    def model(self) -> str:
        return "openclaw/pelvibiz-users"

    async def execute_tool(self, name: str, args: dict, **kwargs: Any) -> dict:
        executor = _ToolExecutor(self.user_id)
        result_str = await executor.run(name, args)
        return json.loads(result_str)

    async def stream(
        self,
        message: str,
        history: list[dict] | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        try:
            brand_service = BrandService()
            profile = await brand_service.load_profile(self.user_id)
            system_ctx = f"{self.system_prompt}\n\n{_build_system_context(profile, self.user_id)}"
            executor = _ToolExecutor(self.user_id)

            messages: list[dict] = [{"role": "system", "content": system_ctx}]
            if history:
                messages.extend(history)
            messages.append({"role": "user", "content": message})

            for _round in range(_MAX_TOOL_ROUNDS):
                response = await _call_openclaw(messages)
                choice = (response.get("choices") or [{}])[0]
                msg = choice.get("message") or {}
                tool_calls = msg.get("tool_calls") or []

                if not tool_calls:
                    final_content = msg.get("content") or ""
                    if final_content:
                        yield text_chunk(final_content)
                    break

                messages.append({
                    "role": "assistant",
                    "content": msg.get("content"),
                    "tool_calls": tool_calls,
                })

                for tc in tool_calls:
                    tc_id = tc.get("id") or "call_0"
                    tc_name = tc.get("function", {}).get("name", "")
                    tc_args_raw = tc.get("function", {}).get("arguments", "{}")

                    label = _TOOL_LABELS.get(tc_name, f"Using {tc_name.replace('_', ' ')}...")
                    yield text_chunk(f"\n_{label}_\n\n")

                    try:
                        tc_args = json.loads(tc_args_raw)
                    except json.JSONDecodeError:
                        tc_args = {}

                    logger.info("Tool call: %s(%s)", tc_name, tc_args)
                    result_str = await executor.run(tc_name, tc_args)

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": result_str,
                    })
            else:
                yield text_chunk("\n\nDemasiados pasos. Por favor intentá de nuevo.")

            yield finish_event("stop")

        except Exception as exc:
            logger.error("OpenClawAgent stream error [%s]: %s", self.user_id, exc, exc_info=True)
            yield error_event(str(exc), "OPENCLAW_ERROR")


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _call_openclaw(messages: list[dict]) -> dict:
    """Blocking call to the OpenClaw gateway — returns full JSON response."""
    settings = get_settings()
    async with httpx.AsyncClient() as http:
        r = await http.post(
            settings.openclaw_url,
            headers={
                "Authorization": f"Bearer {settings.openclaw_token}",
                "Content-Type": "application/json",
            },
            json={
                "model": "openclaw/pelvibiz-users",
                "messages": messages,
                "tools": TOOLS,
                "tool_choice": "auto",
                "stream": False,
            },
            timeout=120.0,
        )
        r.raise_for_status()
        return r.json()


async def _stream_openclaw(
    messages: list[dict],
) -> AsyncGenerator[tuple[str, Any], None]:
    """Stream from the OpenClaw gateway, yielding (type, data) tuples.

    Yields:
        ("text", str) — text delta to forward to the client
        ("tool_calls", dict[int, dict]) — accumulated tool call map when the
            model decides to invoke tools instead of producing text
    """
    settings = get_settings()
    tool_calls_acc: dict[int, dict] = {}
    has_tool_calls = False

    async with httpx.AsyncClient() as http:
        async with http.stream(
            "POST",
            settings.openclaw_url,
            headers={
                "Authorization": f"Bearer {settings.openclaw_token}",
                "Content-Type": "application/json",
            },
            json={
                "model": "openclaw/pelvibiz-users",
                "messages": messages,
                "tools": TOOLS,
                "tool_choice": "auto",
                "stream": True,
            },
            timeout=120.0,
        ) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                choice = (data.get("choices") or [{}])[0]
                delta = choice.get("delta") or {}

                content = delta.get("content")
                if content:
                    yield ("text", content)

                for tc_delta in delta.get("tool_calls") or []:
                    has_tool_calls = True
                    idx = tc_delta.get("index", 0)
                    if idx not in tool_calls_acc:
                        tool_calls_acc[idx] = {
                            "id": "",
                            "type": "function",
                            "function": {"name": "", "arguments": ""},
                        }
                    if tc_delta.get("id"):
                        tool_calls_acc[idx]["id"] = tc_delta["id"]
                    fn = tc_delta.get("function") or {}
                    if fn.get("name"):
                        tool_calls_acc[idx]["function"]["name"] += fn["name"]
                    if fn.get("arguments"):
                        tool_calls_acc[idx]["function"]["arguments"] += fn["arguments"]

    if has_tool_calls:
        yield ("tool_calls", tool_calls_acc)


def _build_system_context(profile: dict, user_id: str) -> str:
    """Build brand-aware system context injected before the SOUL.md."""
    brand_name = profile.get("brand_name") or "your brand"
    brand_voice = profile.get("brand_voice") or "professional"
    target_audience = profile.get("target_audience") or "your audience"
    services = profile.get("services_offered") or ""
    niche = profile.get("niche") or ""
    cta = profile.get("cta") or ""

    return f"""## User Brand Context (pre-loaded)
- **Brand**: {brand_name}
- **Niche**: {niche}
- **Voice**: {brand_voice}
- **Audience**: {target_audience}
- **Services**: {services}
- **CTA**: {cta}
- **User ID**: {user_id}

You have tools available to fetch the profile, content library, generate ideas, carousels, captions, and hooks.
Use them immediately when relevant. Do not explain what you are about to do — just do it."""
