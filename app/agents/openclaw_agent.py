"""OpenClaw agent — routes to OpenClaw gateway with brand context injection."""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncGenerator

import httpx

from app.agents.base import BaseStreamingAgent
from app.core.streaming import text_chunk, finish_event, error_event
from app.services.brand import BrandService

logger = logging.getLogger(__name__)

_OPENCLAW_URL = "http://localhost:18789/v1/chat/completions"
_OPENCLAW_TOKEN = "c172820421a634220f606d737806ef2ee001072549f9fec4"
_API_BASE = "http://localhost:8100/api/v1"
_SVC_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    ".eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imx4dXFqaGJpdW13amxibXVlc21oIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3MTYyNzQ0NSwiZXhwIjoyMDg3MjAzNDQ1fQ"
    ".AT1hxgdX0luR8WUNgDphvzd8j0gonzNg2UWXrs7tgUQ"
)


class OpenClawAgent(BaseStreamingAgent):
    """Streaming agent that proxies to the OpenClaw gateway.

    Injects user brand context into the system message so OpenClaw
    can personalize responses and call the PelviBiz API on behalf of the user.
    """

    @property
    def system_prompt(self) -> str:
        return "You are PelviBiz AI."

    @property
    def model(self) -> str:
        return "openclaw/main"

    async def execute_tool(self, name: str, args: dict, **kwargs: Any) -> dict:
        # OpenClaw handles all tool execution internally via its agent
        return {"error": "OpenClaw agent handles tools natively"}

    async def stream(
        self,
        message: str,
        history: list[dict] | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        """Proxy to OpenClaw with brand context injected as system message."""
        try:
            brand_service = BrandService()
            profile = await brand_service.load_profile(self.user_id)
            system_ctx = _build_system_context(profile, self.user_id)

            messages: list[dict] = [{"role": "system", "content": system_ctx}]
            if history:
                messages.extend(history)
            messages.append({"role": "user", "content": message})

            # Stream from OpenClaw (standard OpenAI SSE) and transform
            # to Vercel AI SDK protocol on the fly.
            async with httpx.AsyncClient() as http:
                async with http.stream(
                    "POST",
                    _OPENCLAW_URL,
                    headers={
                        "Authorization": f"Bearer {_OPENCLAW_TOKEN}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "openclaw/main",
                        "messages": messages,
                        "stream": True,
                    },
                    timeout=120.0,
                ) as resp:
                    resp.raise_for_status()
                    async for raw_line in resp.aiter_lines():
                        line = raw_line.strip()
                        if not line or not line.startswith("data: "):
                            continue
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            content = (
                                chunk.get("choices", [{}])[0]
                                .get("delta", {})
                                .get("content") or ""
                            )
                            if content:
                                yield text_chunk(content)
                        except json.JSONDecodeError:
                            continue

            yield finish_event("stop")

        except Exception as exc:
            logger.error(
                "OpenClawAgent stream error [%s]: %s",
                self.user_id,
                exc,
                exc_info=True,
            )
            yield error_event(str(exc), "OPENCLAW_ERROR")


def _build_system_context(profile: dict, user_id: str) -> str:
    """Build brand-aware system context for OpenClaw."""
    brand_name = profile.get("brand_name") or "your brand"
    brand_voice = profile.get("brand_voice") or "professional"
    target_audience = profile.get("target_audience") or "your audience"
    services = profile.get("services_offered") or ""
    primary_color = profile.get("brand_color_primary") or ""
    logo_url = profile.get("logo_url") or ""
    category = profile.get("category") or ""

    return f"""You are PelviBiz AI — the intelligent content assistant for {brand_name}, a {category} health professional.

## Brand Context
- Brand: {brand_name}
- Voice: {brand_voice}
- Audience: {target_audience}
- Services: {services}
- Primary color: {primary_color}
- Logo: {logo_url}

## User ID
{user_id}

## Available Capabilities (call via curl/HTTP)
All API calls require the header: Authorization: Bearer {_SVC_KEY}
Include "user_id": "{user_id}" in all request bodies.

### AI Carousel
POST {_API_BASE}/ai-carousel/generate
{{"user_id": "{user_id}", "topic": "...", "slide_count": 5}}

### Video Generation (6 templates)
POST {_API_BASE}/video/generate
Available templates: myth-buster, bullet-sequence, viral-reaction, testimonial-story, big-quote, deep-dive
Example payload:
{{
  "user_id": "{user_id}",
  "agent_type": "reels-edited-by-ai",
  "template": "myth-buster",
  "text_1": "THE MYTH text",
  "text_2": "THE TRUTH text",
  "text_3": "Explanation detail",
  "text_4": "Call to action"
}}

### Content Ideas
POST {_API_BASE}/wizard/ideas
{{"user_id": "{user_id}", "count": 5, "content_type": "carousel"}}

### Brand Profile
GET {_API_BASE}/user/profile  (with Authorization header)

### Content Library
Database table: requests_log, filter: user_id = {user_id}

## Behavior Rules
- Be DIRECT and ACTION-ORIENTED. When asked to create → create immediately via API call.
- After calling an API, share the result and media_urls with the user.
- Keep responses SHORT (2-3 sentences before/after action).
- Language: respond in the same language the user writes in.
"""
