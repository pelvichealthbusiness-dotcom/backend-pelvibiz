"""Tests for PelvibizAiAgent — tool calling and routing.

Covers:
- Agent routing: pelvibiz-ai → PelvibizAiAgent
- Agent calls tools when prompted (suggest_ideas, check_profile, check_content_library)
- Tool results are fed back and produce a final text response
- display_name is NOT in PROFILE_FIELDS (regression for DB error)
- System prompt includes brand context and capability guide
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.agents.pelvibiz_ai_agent import PelvibizAiAgent, _build_system_prompt
from app.agents.router import get_agent
from app.services.brand import PROFILE_FIELDS


# ---------------------------------------------------------------------------
# Agent routing
# ---------------------------------------------------------------------------

class TestAgentRouting:
    def test_pelvibiz_ai_routes_correctly(self):
        agent = get_agent("pelvibiz-ai", None, "user-123")
        assert isinstance(agent, PelvibizAiAgent)

    def test_agent_carries_user_id(self):
        agent = get_agent("pelvibiz-ai", None, "user-abc")
        assert agent.user_id == "user-abc"


# ---------------------------------------------------------------------------
# PROFILE_FIELDS regression — display_name must NOT be present
# ---------------------------------------------------------------------------

class TestProfileFields:
    def test_display_name_not_in_profile_fields(self):
        assert "display_name" not in PROFILE_FIELDS, (
            "display_name was added to PROFILE_FIELDS but the column does not exist in the DB"
        )

    def test_brand_name_in_profile_fields(self):
        assert "brand_name" in PROFILE_FIELDS


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

class TestSystemPrompt:
    def test_prompt_includes_brand_name(self):
        profile = {"brand_name": "Kelly Health", "credits_used": 5, "credits_limit": 40}
        prompt = _build_system_prompt(profile)
        assert "Kelly Health" in prompt

    def test_prompt_includes_tool_names(self):
        profile = {"brand_name": "Test Brand"}
        prompt = _build_system_prompt(profile)
        assert "generate_ai_carousel" in prompt
        assert "suggest_ideas" in prompt
        assert "research_content" in prompt
        assert "analyze_instagram" in prompt

    def test_prompt_shows_credits_remaining(self):
        profile = {"brand_name": "Test", "credits_used": 10, "credits_limit": 40}
        prompt = _build_system_prompt(profile)
        assert "30" in prompt  # 40 - 10 = 30 remaining

    def test_prompt_always_english_rule(self):
        profile = {}
        prompt = _build_system_prompt(profile)
        assert "English" in prompt

    def test_prompt_uses_brand_name_as_display_name_fallback(self):
        profile = {"brand_name": "Pelvi Studio"}
        prompt = _build_system_prompt(profile)
        assert "Pelvi Studio" in prompt


# ---------------------------------------------------------------------------
# Tool calling — agent dispatches tools and feeds results back
# ---------------------------------------------------------------------------

FAKE_PROFILE = {
    "id": "user-test",
    "brand_name": "Kelly Health",
    "brand_voice": "warm and professional",
    "target_audience": "women with pelvic floor issues",
    "services_offered": "pelvic floor therapy",
    "credits_used": 5,
    "credits_limit": 40,
    "brand_color_primary": "#FF5733",
    "brand_color_secondary": "#FFFFFF",
}


def _make_tool_call_chunk(name: str, args: dict, call_id: str = "call-1") -> dict:
    return {"type": "tool_call", "id": call_id, "name": name, "args": args}


def _make_text_chunk(content: str) -> dict:
    return {"type": "text", "content": content}


@pytest.fixture
def agent():
    return PelvibizAiAgent(user_id="user-test", agent_type="pelvibiz-ai")


@pytest.mark.asyncio
class TestToolCalling:

    async def test_suggest_ideas_tool_is_called_and_streamed(self, agent):
        """Agent calls suggest_ideas when user asks for ideas."""
        fake_ideas = {"ideas": ["Idea 1", "Idea 2", "Idea 3"], "reasoning": "test"}

        async def mock_stream(*args, **kwargs):
            yield _make_tool_call_chunk("suggest_ideas", {"topic": "pelvic floor", "count": 3})
            yield _make_text_chunk("Here are your ideas!")

        with (
            patch("app.agents.pelvibiz_ai_agent.BrandService") as MockBrand,
            patch("app.agents.pelvibiz_ai_agent.LearningService") as MockLearning,
            patch("app.agents.pelvibiz_ai_agent.stream_chat_with_retry", side_effect=mock_stream),
            patch.object(agent, "_tool_suggest_ideas", new=AsyncMock(return_value=fake_ideas)),
        ):
            MockBrand.return_value.load_profile = AsyncMock(return_value=FAKE_PROFILE)
            MockLearning.return_value.get_patterns = AsyncMock(return_value={})

            chunks = []
            async for chunk in agent.stream("Give me 3 ideas for pelvic floor content"):
                chunks.append(chunk)

        raw = "".join(chunks)
        assert "suggest_ideas" in raw       # tool call SSE chunk (9: prefix)
        assert "toolCallId" in raw           # Vercel AI SDK format
        assert "Here are your ideas!" in raw

    async def test_check_profile_tool_is_called(self, agent):
        """Agent calls check_profile when user asks about their brand."""
        fake_result = {"brand_name": "Kelly Health", "credits_used": 5}

        async def mock_stream(*args, **kwargs):
            yield _make_tool_call_chunk("check_profile", {}, call_id="call-profile")
            yield _make_text_chunk("Here is your brand profile.")

        with (
            patch("app.agents.pelvibiz_ai_agent.BrandService") as MockBrand,
            patch("app.agents.pelvibiz_ai_agent.LearningService") as MockLearning,
            patch("app.agents.pelvibiz_ai_agent.stream_chat_with_retry", side_effect=mock_stream),
            patch.object(agent, "_tool_check_profile", new=AsyncMock(return_value=fake_result)),
        ):
            MockBrand.return_value.load_profile = AsyncMock(return_value=FAKE_PROFILE)
            MockLearning.return_value.get_patterns = AsyncMock(return_value={})

            chunks = []
            async for chunk in agent.stream("What does my brand profile look like?"):
                chunks.append(chunk)

        raw = "".join(chunks)
        assert "check_profile" in raw
        assert "Here is your brand profile." in raw

    async def test_tool_error_is_caught_and_streamed(self, agent):
        """Tool execution errors don't crash the agent — they stream a tool_result with error."""
        async def mock_stream(*args, **kwargs):
            yield _make_tool_call_chunk("check_content_library", {}, call_id="call-lib")
            yield _make_text_chunk("Something went wrong but I recovered.")

        async def failing_tool(*args, **kwargs):
            raise RuntimeError("Supabase timeout")

        with (
            patch("app.agents.pelvibiz_ai_agent.BrandService") as MockBrand,
            patch("app.agents.pelvibiz_ai_agent.LearningService") as MockLearning,
            patch("app.agents.pelvibiz_ai_agent.stream_chat_with_retry", side_effect=mock_stream),
            patch.object(agent, "_tool_check_content_library", new=failing_tool),
        ):
            MockBrand.return_value.load_profile = AsyncMock(return_value=FAKE_PROFILE)
            MockLearning.return_value.get_patterns = AsyncMock(return_value={})

            chunks = []
            async for chunk in agent.stream("Show me my content library"):
                chunks.append(chunk)

        raw = "".join(chunks)
        assert "toolCallId" in raw          # tool result SSE chunk (a: prefix)
        assert "Supabase timeout" in raw

    async def test_unknown_tool_returns_error_result(self, agent):
        """Dispatching an unknown tool name returns an error dict — no exception."""
        result = await agent.execute_tool(name="non_existent_tool", args={})
        assert "error" in result
        assert "non_existent_tool" in result["error"]

    async def test_multiple_tool_calls_in_one_turn(self, agent):
        """Agent handles multiple tool calls in a single turn."""
        async def mock_stream(*args, **kwargs):
            yield _make_tool_call_chunk("suggest_ideas", {"topic": "posture"}, call_id="c1")
            yield _make_tool_call_chunk("check_profile", {}, call_id="c2")
            yield _make_text_chunk("Done.")

        with (
            patch("app.agents.pelvibiz_ai_agent.BrandService") as MockBrand,
            patch("app.agents.pelvibiz_ai_agent.LearningService") as MockLearning,
            patch("app.agents.pelvibiz_ai_agent.stream_chat_with_retry", side_effect=mock_stream),
            patch.object(agent, "_tool_suggest_ideas", new=AsyncMock(return_value={"ideas": []})),
            patch.object(agent, "_tool_check_profile", new=AsyncMock(return_value={"brand_name": "Kelly"})),
        ):
            MockBrand.return_value.load_profile = AsyncMock(return_value=FAKE_PROFILE)
            MockLearning.return_value.get_patterns = AsyncMock(return_value={})

            chunks = []
            async for chunk in agent.stream("Ideas for posture and show me my profile"):
                chunks.append(chunk)

        raw = "".join(chunks)
        assert raw.count("toolCallId") >= 2   # two tool call SSE chunks
        assert "Done." in raw

    async def test_stream_ends_with_finish_event(self, agent):
        """Stream always ends with a finish event."""
        async def mock_stream(*args, **kwargs):
            yield _make_text_chunk("Hello!")

        with (
            patch("app.agents.pelvibiz_ai_agent.BrandService") as MockBrand,
            patch("app.agents.pelvibiz_ai_agent.LearningService") as MockLearning,
            patch("app.agents.pelvibiz_ai_agent.stream_chat_with_retry", side_effect=mock_stream),
        ):
            MockBrand.return_value.load_profile = AsyncMock(return_value=FAKE_PROFILE)
            MockLearning.return_value.get_patterns = AsyncMock(return_value={})

            chunks = []
            async for chunk in agent.stream("Hi"):
                chunks.append(chunk)

        raw = "".join(chunks)
        assert "finish" in raw
