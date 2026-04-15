from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.openclaw_agent import OPENCLAW_AGENT_PROMPT, TOOLS, _ToolExecutor


def test_openclaw_prompt_is_direct_and_tool_first():
    prompt = OPENCLAW_AGENT_PROMPT.lower()

    assert "greet briefly" in prompt
    assert "use the relevant tool immediately" in prompt
    assert "brand-setting" in prompt


def test_openclaw_tools_include_core_backend_actions():
    names = {tool["function"]["name"] for tool in TOOLS}

    assert "get_workspace_context" in names
    assert "update_brand_profile" in names
    assert "generate_post" in names
    assert "generate_video" in names
    assert "trim_video" in names
    assert "social_research" in names
    assert "social_ideate" in names
    assert "social_script" in names
    assert "compare_social_accounts" in names


@pytest.mark.asyncio
async def test_workspace_context_aggregates_backend_sections():
    with patch("app.agents.openclaw_agent.get_settings", return_value=SimpleNamespace(internal_api_key="test-key")):
        executor = _ToolExecutor("user-123")

    async def fake_get(path: str, params: dict | None = None, timeout: float = 30.0):
        mapping = {
            "/auth/profile": {"data": {"brand_name": "PelviBiz"}},
            "/user/preferences": {"data": {"preferred_topics": ["pelvic floor"]}},
            "/content/usage": {"data": {"total_generated": 4}},
            "/content/list": {"items": [{"id": "content-1"}]},
            "/research/latest": {"items": [{"id": "research-1"}]},
            "/ideation/latest": {"items": [{"id": "idea-1"}]},
            "/scripting/hooks/latest": {"items": [{"id": "hook-1"}]},
            "/scripting/scripts/latest": {"items": [{"id": "script-1"}]},
            "/brand/stories": {"data": [{"id": "story-1"}]},
            "/competitors": {"items": [{"id": "competitor-1"}]},
            "/conversations": {"items": [{"id": "conversation-1"}]},
            "/user/learning/patterns": {"data": {"has_enough_data": True}},
        }
        return mapping[path]

    executor._get = AsyncMock(side_effect=fake_get)  # type: ignore[method-assign]

    raw = await executor.run("get_workspace_context", {"limit": 1})
    data = json.loads(raw)

    assert data["brand_profile"]["data"]["brand_name"] == "PelviBiz"
    assert data["preferences"]["data"]["preferred_topics"] == ["pelvic floor"]
    assert data["content"]["items"][0]["id"] == "content-1"
    assert data["learning"]["data"]["has_enough_data"] is True
