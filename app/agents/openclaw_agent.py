"""OpenClaw agent — PelviBiz AI with real tool calling via OpenClaw gateway."""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncGenerator

import httpx

from app.agents.base import BaseStreamingAgent
from app.core.streaming import text_chunk, finish_event, error_event
from app.services.brand import BrandService
from app.config import get_settings

logger = logging.getLogger(__name__)

_OPENCLAW_URL = "http://localhost:18789/v1/chat/completions"
_OPENCLAW_TOKEN = "c172820421a634220f606d737806ef2ee001072549f9fec4"
_API_BASE = "http://localhost:8100/api/v1"
_MAX_TOOL_ROUNDS = 5

# ── Tool Definitions ──────────────────────────────────────────────────────────

TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_brand_profile",
            "description": "Get the user's brand profile: name, voice, audience, colors, services, niche, logo.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_content_library",
            "description": "Get the user's recent generated content (carousels, reels, posts). Returns up to 10 most recent items.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_type": {
                        "type": "string",
                        "description": "Filter by type: 'real-carousel', 'ai-carousel', 'reels-edited-by-ai'. Leave empty for all.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_ideas",
            "description": "Generate content ideas for carousels or reels based on a topic or niche. Returns 3-5 ready-to-use ideas.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "The topic or niche to generate ideas for. E.g. 'pelvic floor exercises', 'postpartum recovery'.",
                    },
                    "content_type": {
                        "type": "string",
                        "enum": ["carousel", "reel"],
                        "description": "Type of content to generate ideas for.",
                    },
                },
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_ai_carousel",
            "description": "Generate a fully AI-generated image carousel on any topic. Returns slide images and a caption. Use this when the user wants to create a carousel.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "The carousel topic. Be specific. E.g. '5 signs your pelvic floor needs attention'.",
                    },
                    "slide_count": {
                        "type": "integer",
                        "description": "Number of slides. Default: 5. Range: 3-8.",
                        "default": 5,
                    },
                },
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_caption",
            "description": "Generate an Instagram caption for a piece of content. Returns a ready-to-publish caption with hashtags.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "What the content is about.",
                    },
                    "tone": {
                        "type": "string",
                        "description": "Caption tone: educational, motivational, conversational, provocative. Defaults to the brand voice.",
                    },
                },
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_hooks",
            "description": "Generate 5 viral hook options for a given topic. Hooks are the first line of a caption or the opening of a reel.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "The topic to generate hooks for.",
                    }
                },
                "required": ["topic"],
            },
        },
    },
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

    async def run(self, name: str, args: dict) -> str:
        """Execute a tool and return a JSON string result."""
        try:
            match name:
                case "get_brand_profile":
                    return await self._get_brand_profile()
                case "get_content_library":
                    return await self._get_content_library(args.get("agent_type"))
                case "generate_ideas":
                    return await self._generate_ideas(
                        args.get("topic", ""),
                        args.get("content_type", "carousel"),
                    )
                case "generate_ai_carousel":
                    return await self._generate_ai_carousel(
                        args.get("topic", ""),
                        args.get("slide_count", 5),
                    )
                case "generate_caption":
                    return await self._generate_caption(
                        args.get("topic", ""),
                        args.get("tone", ""),
                    )
                case "generate_hooks":
                    return await self._generate_hooks(args.get("topic", ""))
                case _:
                    return json.dumps({"error": f"Unknown tool: {name}"})
        except Exception as exc:
            logger.error("Tool %s failed: %s", name, exc)
            return json.dumps({"error": str(exc)})

    async def _get(self, path: str) -> dict:
        async with httpx.AsyncClient() as http:
            r = await http.get(f"{_API_BASE}{path}", headers=self._headers, timeout=30.0)
            r.raise_for_status()
            return r.json()

    async def _post(self, path: str, body: dict) -> dict:
        async with httpx.AsyncClient() as http:
            r = await http.post(
                f"{_API_BASE}{path}", headers=self._headers,
                json=body, timeout=120.0,
            )
            r.raise_for_status()
            return r.json()

    async def _get_brand_profile(self) -> str:
        data = await self._get("/user/profile")
        profile = data.get("data") or data
        # Return only the useful fields, not the full raw object
        return json.dumps({
            "brand_name": profile.get("brand_name"),
            "brand_voice": profile.get("brand_voice"),
            "target_audience": profile.get("target_audience"),
            "services_offered": profile.get("services_offered"),
            "niche": profile.get("niche"),
            "cta": profile.get("cta"),
            "brand_color_primary": profile.get("brand_color_primary"),
            "content_style_brief": profile.get("content_style_brief"),
        })

    async def _get_content_library(self, agent_type: str | None) -> str:
        path = "/content/list?limit=10"
        if agent_type:
            path += f"&agent_type={agent_type}"
        data = await self._get(path)
        items = data.get("data") or data.get("items") or []
        # Summarize to avoid bloating context
        summary = [
            {
                "id": item.get("id"),
                "title": item.get("title"),
                "agent_type": item.get("agent_type"),
                "created_at": item.get("created_at"),
                "published": item.get("published"),
            }
            for item in (items[:10] if isinstance(items, list) else [])
        ]
        return json.dumps({"items": summary, "total": len(summary)})

    async def _generate_ideas(self, topic: str, content_type: str) -> str:
        agent_type = "ai-carousel" if content_type == "carousel" else "reels-edited-by-ai"
        data = await self._post("/wizard/ideas", {
            "message": topic,
            "agent_type": agent_type,
            "count": 5,
        })
        ideas = data.get("ideas") or data.get("data") or data
        return json.dumps({"ideas": ideas})

    async def _generate_ai_carousel(self, topic: str, slide_count: int) -> str:
        slide_count = max(3, min(8, slide_count))
        data = await self._post("/ai-carousel/generate", {
            "topic": topic,
            "slide_count": slide_count,
        })
        result = data.get("data") or data
        media_urls = result.get("media_urls") or result.get("slide_urls") or []
        caption = result.get("caption") or ""
        return json.dumps({
            "status": "generated",
            "topic": topic,
            "slide_count": len(media_urls),
            "media_urls": media_urls,
            "caption": caption,
        })

    async def _generate_caption(self, topic: str, tone: str) -> str:
        body: dict = {"topic": topic}
        if tone:
            body["tone"] = tone
        data = await self._post("/post/generate", body)
        result = data.get("data") or data
        return json.dumps({
            "caption": result.get("caption") or result.get("content") or str(result),
        })

    async def _generate_hooks(self, topic: str) -> str:
        data = await self._post("/scripting/hooks", {"topic": topic, "count": 5})
        result = data.get("data") or data
        hooks = result.get("hooks") or result.get("items") or result
        return json.dumps({"hooks": hooks})


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
        return "You are PelviBiz AI."

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
            system_ctx = _build_system_context(profile, self.user_id)
            executor = _ToolExecutor(self.user_id)

            messages: list[dict] = [{"role": "system", "content": system_ctx}]
            if history:
                messages.extend(history)
            messages.append({"role": "user", "content": message})

            # ── Agentic loop: tool calling rounds ─────────────────────────
            for _round in range(_MAX_TOOL_ROUNDS):
                response = await _call_openclaw(messages, stream=False)
                choice = (response.get("choices") or [{}])[0]
                msg = choice.get("message") or {}
                tool_calls = msg.get("tool_calls") or []

                if not tool_calls:
                    # No tools needed — stream the final response
                    final_content = msg.get("content") or ""
                    if final_content:
                        # Simulate streaming by yielding the full text
                        yield text_chunk(final_content)
                    break

                # Append assistant's tool call message
                messages.append({"role": "assistant", "content": msg.get("content"), "tool_calls": tool_calls})

                # Execute each tool call and append results
                for tc in tool_calls:
                    tc_id = tc.get("id") or "call_0"
                    tc_name = tc.get("function", {}).get("name", "")
                    tc_args_raw = tc.get("function", {}).get("arguments", "{}")
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
                # Exceeded max rounds — stream whatever we have
                yield text_chunk("I ran too many steps. Please try again.")

            yield finish_event("stop")

        except Exception as exc:
            logger.error("OpenClawAgent stream error [%s]: %s", self.user_id, exc, exc_info=True)
            yield error_event(str(exc), "OPENCLAW_ERROR")


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _call_openclaw(messages: list[dict], stream: bool = False) -> dict:
    """Make a single call to the OpenClaw gateway."""
    async with httpx.AsyncClient() as http:
        r = await http.post(
            _OPENCLAW_URL,
            headers={
                "Authorization": f"Bearer {_OPENCLAW_TOKEN}",
                "Content-Type": "application/json",
            },
            json={
                "model": "openclaw/pelvibiz-users",
                "messages": messages,
                "tools": TOOLS,
                "tool_choice": "auto",
                "stream": stream,
            },
            timeout=120.0,
        )
        r.raise_for_status()
        return r.json()


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
