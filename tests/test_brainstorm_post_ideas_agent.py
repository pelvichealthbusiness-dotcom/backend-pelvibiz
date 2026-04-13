"""Tests for BrainstormPostIdeasAgent — wizard_mode='brainstorm_post_ideas'.

Tests cover:
1. Agent returns JSON array from streamed chunks
2. System prompt contains the template description when template_key is passed
3. System prompt contains brand_name from profile
4. Defaults to 'tip-card' when template_key is missing from metadata
5. Handles brand load failure gracefully (still streams)
6. LLM 429 → yields error_event with LLM_RATE_LIMIT code
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.brainstorm_post_ideas import BrainstormPostIdeasAgent, TEMPLATE_DESCRIPTIONS
from app.agents.router import get_agent
from app.routers.chat_stream import ChatStreamRequest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def agent():
    return BrainstormPostIdeasAgent(user_id="user-test", agent_type="ai-post-generator")


def _mock_profile(brand_name="TestBrand", **overrides):
    return {
        "brand_name": brand_name,
        "brand_voice": "warm and professional",
        "target_audience": "postpartum women",
        "services_offered": "pelvic floor physiotherapy",
        "cta": "Book your session",
        "keywords": "pelvic floor, postpartum",
        "content_style_brief": "",
        **overrides,
    }


# ---------------------------------------------------------------------------
# 1. Agent returns JSON array
# ---------------------------------------------------------------------------

class TestAgentReturnsJsonArray:
    @pytest.mark.asyncio
    async def test_agent_returns_json_array(self, agent):
        """Streamed output should contain the ideas from the mocked LLM response."""
        json_payload = '["idea 1", "idea 2", "idea 3", "idea 4"]'

        async def mock_stream(*args, **kwargs):
            yield {"type": "text", "content": json_payload}

        with patch.object(agent._brand_service, "load_profile", new=AsyncMock(return_value=_mock_profile())):
            with patch("app.agents.brainstorm_post_ideas.stream_chat_with_retry", side_effect=mock_stream):
                chunks = []
                async for chunk in agent.stream(
                    "generate ideas",
                    metadata={"template_key": "tip-card"},
                ):
                    chunks.append(chunk)

        text_chunks = [c for c in chunks if c.startswith("0:")]
        finish_chunks = [c for c in chunks if c.startswith("d:")]
        assert len(text_chunks) >= 1
        assert len(finish_chunks) == 1
        # The full text output should include the ideas
        full_text = "".join(text_chunks)
        assert "idea 1" in full_text
        assert "idea 2" in full_text


# ---------------------------------------------------------------------------
# 2. System prompt contains template description
# ---------------------------------------------------------------------------

class TestAgentUsesTemplateKey:
    @pytest.mark.asyncio
    async def test_agent_uses_template_key_from_metadata(self, agent):
        """System prompt must contain the template description for the given key."""
        captured = {}

        async def capture_stream(messages, system_prompt, **kwargs):
            captured["system_prompt"] = system_prompt
            yield {"type": "text", "content": '["idea"]'}

        with patch.object(agent._brand_service, "load_profile", new=AsyncMock(return_value=_mock_profile())):
            with patch("app.agents.brainstorm_post_ideas.stream_chat_with_retry", side_effect=capture_stream):
                async for _ in agent.stream(
                    "generate ideas",
                    metadata={"template_key": "myth-vs-fact"},
                ):
                    pass

        assert "myth-vs-fact" in captured["system_prompt"]
        assert TEMPLATE_DESCRIPTIONS["myth-vs-fact"] in captured["system_prompt"]


# ---------------------------------------------------------------------------
# 3. System prompt contains brand context
# ---------------------------------------------------------------------------

class TestAgentUsesBrandContext:
    @pytest.mark.asyncio
    async def test_agent_uses_brand_context(self, agent):
        """System prompt must reference the brand_name from the loaded profile."""
        captured = {}

        async def capture_stream(messages, system_prompt, **kwargs):
            captured["system_prompt"] = system_prompt
            yield {"type": "text", "content": '["idea"]'}

        profile = _mock_profile(brand_name="PelvaCare Clinic")

        with patch.object(agent._brand_service, "load_profile", new=AsyncMock(return_value=profile)):
            with patch("app.agents.brainstorm_post_ideas.stream_chat_with_retry", side_effect=capture_stream):
                async for _ in agent.stream(
                    "generate ideas",
                    metadata={"template_key": "tip-card"},
                ):
                    pass

        assert "PelvaCare Clinic" in captured["system_prompt"]


# ---------------------------------------------------------------------------
# 4. Defaults to tip-card when template_key is missing
# ---------------------------------------------------------------------------

class TestAgentHandlesMissingTemplateKey:
    @pytest.mark.asyncio
    async def test_agent_handles_missing_template_key(self, agent):
        """Should default to 'tip-card' gracefully when template_key absent."""
        captured = {}

        async def capture_stream(messages, system_prompt, **kwargs):
            captured["system_prompt"] = system_prompt
            yield {"type": "text", "content": '["idea"]'}

        with patch.object(agent._brand_service, "load_profile", new=AsyncMock(return_value=_mock_profile())):
            with patch("app.agents.brainstorm_post_ideas.stream_chat_with_retry", side_effect=capture_stream):
                chunks = []
                async for chunk in agent.stream("generate ideas", metadata={}):
                    chunks.append(chunk)

        # Should still stream without error
        assert any(c.startswith("0:") or c.startswith("d:") for c in chunks)
        # Defaults to tip-card
        assert "tip-card" in captured["system_prompt"]
        assert TEMPLATE_DESCRIPTIONS["tip-card"] in captured["system_prompt"]


# ---------------------------------------------------------------------------
# 5. Handles brand load failure gracefully
# ---------------------------------------------------------------------------

class TestAgentHandlesBrandLoadFailure:
    @pytest.mark.asyncio
    async def test_agent_handles_brand_load_failure(self, agent):
        """BrandService failure should use defaults and still produce output."""
        async def mock_stream(*args, **kwargs):
            yield {"type": "text", "content": '["fallback idea"]'}

        with patch.object(agent._brand_service, "load_profile", side_effect=Exception("DB down")):
            with patch("app.agents.brainstorm_post_ideas.stream_chat_with_retry", side_effect=mock_stream):
                chunks = []
                async for chunk in agent.stream(
                    "generate ideas",
                    metadata={"template_key": "tip-card"},
                ):
                    chunks.append(chunk)

        # Should not raise — should produce text or finish event
        assert any(c.startswith("0:") or c.startswith("d:") or c.startswith("e:") for c in chunks)


# ---------------------------------------------------------------------------
# 6. LLM rate limit → error_event with LLM_RATE_LIMIT
# ---------------------------------------------------------------------------

class TestAgentHandlesLlmRateLimit:
    @pytest.mark.asyncio
    async def test_agent_handles_llm_rate_limit(self, agent):
        """stream_chat_with_retry raising 429 → error_event with LLM_RATE_LIMIT code."""
        async def rate_limited_stream(*args, **kwargs):
            raise Exception("429 RESOURCE_EXHAUSTED")
            yield  # make it an async generator

        with patch.object(agent._brand_service, "load_profile", new=AsyncMock(return_value=_mock_profile())):
            with patch("app.agents.brainstorm_post_ideas.stream_chat_with_retry", side_effect=rate_limited_stream):
                chunks = []
                async for chunk in agent.stream(
                    "generate ideas",
                    metadata={"template_key": "tip-card"},
                ):
                    chunks.append(chunk)

        error_chunks = [c for c in chunks if c.startswith("e:")]
        assert len(error_chunks) == 1
        assert "LLM_RATE_LIMIT" in error_chunks[0]


# ---------------------------------------------------------------------------
# Agent routing
# ---------------------------------------------------------------------------

class TestAgentRouting:
    def test_brainstorm_post_ideas_routes_to_correct_agent(self):
        agent = get_agent("ai-post-generator", "brainstorm_post_ideas", "user-1")
        assert isinstance(agent, BrainstormPostIdeasAgent)

    def test_brainstorm_post_ideas_with_any_agent_type(self):
        # wizard_mode overrides agent_type
        agent = get_agent("general", "brainstorm_post_ideas", "user-1")
        assert isinstance(agent, BrainstormPostIdeasAgent)


# ---------------------------------------------------------------------------
# ChatStreamRequest validation
# ---------------------------------------------------------------------------

class TestChatStreamRequestValidation:
    def test_accepts_brainstorm_post_ideas_wizard_mode(self):
        req = ChatStreamRequest(
            agent_type="ai-post-generator",
            message="generate ideas",
            wizard_mode="brainstorm_post_ideas",
        )
        assert req.wizard_mode == "brainstorm_post_ideas"

    def test_rejects_unknown_wizard_mode(self):
        with pytest.raises(Exception):
            ChatStreamRequest(
                agent_type="ai-post-generator",
                message="test",
                wizard_mode="invalid_mode",
            )
