"""Tests for PostContentAgent — wizard_mode='generate_content'.

Tests cover:
- Agent routing: generate_content → PostContentAgent
- System prompt includes template fields + brand context
- Stream produces JSON text chunks (no tool calls)
- chat_stream validator accepts generate_content + ai-post-generator
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.router import get_agent
from app.agents.post_content import PostContentAgent, _build_fields_spec, _TEMPLATE_FIELDS
from app.routers.chat_stream import ChatStreamRequest


# ---------------------------------------------------------------------------
# Agent routing
# ---------------------------------------------------------------------------

class TestAgentRouting:
    def test_generate_content_routes_to_post_content_agent(self):
        agent = get_agent("ai-post-generator", "generate_content", "user-1")
        assert isinstance(agent, PostContentAgent)

    def test_generate_content_with_any_agent_type(self):
        # wizard_mode overrides agent_type
        agent = get_agent("general", "generate_content", "user-1")
        assert isinstance(agent, PostContentAgent)


# ---------------------------------------------------------------------------
# Template fields registry
# ---------------------------------------------------------------------------

class TestTemplateFields:
    def test_all_12_templates_registered(self):
        expected = {
            "tip-card", "myth-vs-fact", "quote-card", "did-you-know",
            "offer-flyer", "event-banner", "testimonial-card", "before-after-teaser",
            "service-spotlight", "checklist-post", "question-hook", "stat-callout",
        }
        assert set(_TEMPLATE_FIELDS.keys()) == expected

    def test_tip_card_has_headline_and_tip_body(self):
        fields = _TEMPLATE_FIELDS["tip-card"]
        assert "headline" in fields
        assert "tip_body" in fields

    def test_stat_callout_has_four_fields(self):
        fields = _TEMPLATE_FIELDS["stat-callout"]
        assert "stat_number" in fields
        assert "stat_label" in fields
        assert "context" in fields
        assert "source" in fields

    def test_build_fields_spec_returns_json_keys(self):
        spec = _build_fields_spec("tip-card")
        assert '"headline"' in spec
        assert '"tip_body"' in spec

    def test_build_fields_spec_unknown_template_returns_fallback(self):
        spec = _build_fields_spec("nonexistent-template")
        assert '"headline"' in spec or '"body"' in spec


# ---------------------------------------------------------------------------
# ChatStreamRequest validation
# ---------------------------------------------------------------------------

class TestChatStreamRequestValidation:
    def test_accepts_ai_post_generator_agent_type(self):
        req = ChatStreamRequest(
            agent_type="ai-post-generator",
            message="Generate content",
            wizard_mode="generate_content",
        )
        assert req.agent_type == "ai-post-generator"
        assert req.wizard_mode == "generate_content"

    def test_rejects_unknown_agent_type(self):
        with pytest.raises(Exception):
            ChatStreamRequest(agent_type="unknown-agent", message="test")

    def test_accepts_all_wizard_modes(self):
        for mode in ("ideas", "draft", "generate", "fix", "generate_content"):
            req = ChatStreamRequest(
                agent_type="ai-post-generator",
                message="test",
                wizard_mode=mode,
            )
            assert req.wizard_mode == mode

    def test_rejects_unknown_wizard_mode(self):
        with pytest.raises(Exception):
            ChatStreamRequest(
                agent_type="ai-post-generator",
                message="test",
                wizard_mode="invalid_mode",
            )


# ---------------------------------------------------------------------------
# PostContentAgent streaming
# ---------------------------------------------------------------------------

@pytest.fixture
def agent():
    return PostContentAgent(user_id="user-test", agent_type="ai-post-generator")


class TestPostContentAgentStream:
    @pytest.mark.asyncio
    async def test_stream_yields_text_and_finish(self, agent):
        """Stream should yield text chunks (JSON) and end with finish event."""
        mock_profile = {
            "brand_name": "TestBrand",
            "brand_voice": "professional",
            "target_audience": "women",
            "services_offered": "therapy",
            "cta": "Book now",
            "keywords": "pelvic health",
            "content_style_brief": "",
            "font_prompt": "Bold sans",
        }

        json_payload = '{"text_fields": {"headline": "Test Headline", "tip_body": "Test tip"}, "caption": "Test caption #pelvic"}'

        async def mock_stream(*args, **kwargs):
            yield {"type": "text", "content": json_payload}

        with patch.object(agent._brand_service, "load_profile", new=AsyncMock(return_value=mock_profile)):
            with patch("app.agents.post_content.stream_chat_with_retry", side_effect=mock_stream):
                chunks = []
                async for chunk in agent.stream(
                    "3 signs your pelvic floor needs attention",
                    metadata={"template_key": "tip-card", "topic": "pelvic floor"},
                ):
                    chunks.append(chunk)

        text_chunks = [c for c in chunks if c.startswith("0:")]
        finish_chunks = [c for c in chunks if c.startswith("d:")]
        assert len(text_chunks) >= 1
        assert len(finish_chunks) == 1

    @pytest.mark.asyncio
    async def test_stream_uses_template_key_from_metadata(self, agent):
        """System prompt should reference the correct template."""
        captured_kwargs = {}

        mock_profile = {"brand_name": "B", "brand_voice": "v", "target_audience": "t",
                        "services_offered": "s", "cta": "c", "keywords": "", "content_style_brief": ""}

        async def capture_stream(messages, system_prompt, **kwargs):
            captured_kwargs["system_prompt"] = system_prompt
            yield {"type": "text", "content": "{}"}

        with patch.object(agent._brand_service, "load_profile", new=AsyncMock(return_value=mock_profile)):
            with patch("app.agents.post_content.stream_chat_with_retry", side_effect=capture_stream):
                async for _ in agent.stream(
                    "myth vs fact topic",
                    metadata={"template_key": "myth-vs-fact", "topic": "Kegels"},
                ):
                    pass

        assert "myth-vs-fact" in captured_kwargs["system_prompt"]
        assert '"myth"' in captured_kwargs["system_prompt"]

    @pytest.mark.asyncio
    async def test_stream_falls_back_to_brand_defaults_on_profile_error(self, agent):
        """Should not raise if brand profile load fails."""
        async def mock_stream(*args, **kwargs):
            yield {"type": "text", "content": '{"text_fields": {}, "caption": ""}'}

        with patch.object(agent._brand_service, "load_profile", side_effect=Exception("DB error")):
            with patch("app.agents.post_content.stream_chat_with_retry", side_effect=mock_stream):
                chunks = []
                async for chunk in agent.stream("topic", metadata={"template_key": "tip-card"}):
                    chunks.append(chunk)

        assert any(c.startswith("0:") or c.startswith("d:") or c.startswith("e:") for c in chunks)

    @pytest.mark.asyncio
    async def test_stream_emits_error_on_llm_failure(self, agent):
        """LLM errors should yield an error event, not raise."""
        async def failing_stream(*args, **kwargs):
            raise RuntimeError("Gemini exploded")
            yield  # make it a generator

        mock_profile = {"brand_name": "", "brand_voice": "", "target_audience": "",
                        "services_offered": "", "cta": "", "keywords": "", "content_style_brief": ""}

        with patch.object(agent._brand_service, "load_profile", new=AsyncMock(return_value=mock_profile)):
            with patch("app.agents.post_content.stream_chat_with_retry", side_effect=failing_stream):
                chunks = []
                async for chunk in agent.stream("topic", metadata={"template_key": "tip-card"}):
                    chunks.append(chunk)

        error_chunks = [c for c in chunks if c.startswith("e:")]
        assert len(error_chunks) == 1
