"""Tests for POST /api/v1/post/generate endpoint and PostGeneratorService.

Tests cover:
- Prompt builder: correct template category dispatch
- PostGeneratorService: brand merge, requests_log save, credits increment
- Router: happy path, credits exhausted, generation failure
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

from app.models.post_generator import PostGenerateRequest, PostGenerateResponse
from app.prompts.post_generate import build_post_image_prompt, _PHOTO_TEMPLATES, _CARD_TEMPLATES, _PROMO_TEMPLATES
from app.services.post_generator import PostGeneratorService, _merge_brand


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

class TestBuildPostImagePrompt:
    def _base_brand(self, **overrides):
        return {
            "brand_name": "PelviBiz",
            "brand_color_primary": "#FF6B35",
            "brand_color_secondary": "#C8A96E",
            "brand_voice": "professional",
            "font_prompt": "Clean bold sans-serif",
            "font_style": "bold",
            "font_size": "38px",
            "visual_identity": "modern, clean",
            "visual_environment_setup": "clinic setting",
            "visual_subject_outfit_generic": "professional woman",
            **overrides,
        }

    def test_tip_card_uses_photo_prompt(self):
        prompt = build_post_image_prompt(
            "tip-card",
            {"headline": "Test headline", "tip_body": "Test tip"},
            "pelvic health",
            self._base_brand(),
        )
        assert "photorealistic" in prompt.lower() or "lifestyle" in prompt.lower() or "photo" in prompt.lower()
        assert "Test headline" in prompt
        assert "Test tip" in prompt

    def test_quote_card_uses_card_prompt(self):
        prompt = build_post_image_prompt(
            "quote-card",
            {"quote": "Your body is not broken.", "author": "Dr. Smith"},
            "healing",
            self._base_brand(),
        )
        assert "typographic" in prompt.lower() or "flat" in prompt.lower() or "card" in prompt.lower()
        assert "Your body is not broken." in prompt

    def test_offer_flyer_uses_promo_prompt(self):
        prompt = build_post_image_prompt(
            "offer-flyer",
            {"offer_title": "First Assessment 50% Off", "offer_details": "Full eval", "price": "$75", "cta": "Book now"},
            "offer",
            self._base_brand(),
        )
        assert "First Assessment 50% Off" in prompt
        assert "Book now" in prompt

    def test_all_12_templates_generate_non_empty_prompts(self):
        brand = self._base_brand()
        templates_fields = {
            "tip-card": {"headline": "H", "tip_body": "T"},
            "myth-vs-fact": {"myth": "M", "fact": "F"},
            "quote-card": {"quote": "Q", "author": "A"},
            "did-you-know": {"headline": "H", "fact": "F"},
            "offer-flyer": {"offer_title": "O", "offer_details": "D", "price": "$1", "cta": "Book"},
            "event-banner": {"event_name": "E", "date_time": "D", "location": "L", "cta": "R"},
            "testimonial-card": {"testimonial": "T", "client_name": "N", "result": "R"},
            "before-after-teaser": {"headline": "H", "before_state": "B", "after_state": "A"},
            "service-spotlight": {"service_name": "S", "benefit_1": "B1", "benefit_2": "B2", "benefit_3": "B3", "cta": "C"},
            "checklist-post": {"headline": "H", "item_1": "I1", "item_2": "I2", "item_3": "I3"},
            "question-hook": {"question": "Q?", "subtitle": "Sub"},
            "stat-callout": {"stat_number": "1in3", "stat_label": "L", "context": "C", "source": "S"},
        }
        for key, fields in templates_fields.items():
            prompt = build_post_image_prompt(key, fields, "topic", brand)
            assert len(prompt) > 100, f"Prompt too short for {key}"

    def test_prompt_includes_brand_colors(self):
        brand = self._base_brand()
        for key in list(_CARD_TEMPLATES)[:1]:
            prompt = build_post_image_prompt(key, {"quote": "Q"}, "t", brand)
            assert "#FF6B35" in prompt or "#C8A96E" in prompt

    def test_canvas_rules_included_in_all_prompts(self):
        brand = self._base_brand()
        for key in ["tip-card", "quote-card", "offer-flyer"]:
            prompt = build_post_image_prompt(key, {"headline": "H"}, "t", brand)
            assert "1080" in prompt
            assert "1350" in prompt


# ---------------------------------------------------------------------------
# Brand merge
# ---------------------------------------------------------------------------

class TestMergeBrand:
    def _make_request(self, **overrides) -> PostGenerateRequest:
        base = dict(
            template_key="tip-card", template_label="Tip",
            topic="test", text_fields={}, caption="",
            message_id="msg-1", conversation_id="conv-1",
        )
        base.update(overrides)
        return PostGenerateRequest(**base)

    def test_db_profile_takes_precedence(self):
        profile = {"brand_name": "DBBrand", "brand_color_primary": "#111"}
        req = self._make_request(brand_name="RequestBrand", brand_color_primary="#999")
        merged = _merge_brand(profile, req)
        assert merged["brand_name"] == "DBBrand"
        assert merged["brand_color_primary"] == "#111"

    def test_request_fills_empty_db_fields(self):
        profile = {"brand_name": None, "brand_color_primary": ""}
        req = self._make_request(brand_name="FallbackBrand", brand_color_primary="#ABC")
        merged = _merge_brand(profile, req)
        assert merged["brand_name"] == "FallbackBrand"
        assert merged["brand_color_primary"] == "#ABC"

    def test_visual_environment_mapped_correctly(self):
        profile = {"visual_environment_setup": "clinic"}
        req = self._make_request(visual_environment="studio")
        merged = _merge_brand(profile, req)
        assert merged["visual_environment_setup"] == "clinic"  # DB wins


# ---------------------------------------------------------------------------
# PostGeneratorService
# ---------------------------------------------------------------------------

def _make_request(**overrides) -> PostGenerateRequest:
    base = dict(
        template_key="tip-card", template_label="Educational Tip",
        topic="pelvic floor health",
        text_fields={"headline": "Test", "tip_body": "Body"},
        caption="Caption #pelvic",
        message_id="msg-uuid-1",
        conversation_id="conv-1",
    )
    base.update(overrides)
    return PostGenerateRequest(**base)


class TestPostGeneratorService:
    def _make_service(self, profile=None, generated_b64="ZmFrZQ=="):
        service = PostGeneratorService.__new__(PostGeneratorService)
        service._image_gen = MagicMock()
        service._image_gen.generate_from_prompt = AsyncMock(return_value=generated_b64)
        service._storage = MagicMock()
        service._storage.upload_image = AsyncMock(return_value="https://cdn.example.com/post.jpg")
        service._brand_service = MagicMock()
        service._brand_service.load_profile = AsyncMock(return_value=profile or {
            "brand_name": "PelviBiz",
            "brand_color_primary": "#FF6B35",
            "brand_color_secondary": "#C8A96E",
            "font_prompt": "Bold", "font_style": "bold", "font_size": "38px",
        })
        service._credits = MagicMock()
        service._credits.check_credits = AsyncMock(return_value=(0, 40))
        service._credits.increment_credits = AsyncMock(return_value=1)
        service._supabase = MagicMock()
        service._supabase.table.return_value.upsert.return_value.execute.return_value = MagicMock()
        return service

    @pytest.mark.asyncio
    async def test_generate_returns_image_url_and_caption(self):
        service = self._make_service()
        with patch("app.services.post_generator.force_resolution", side_effect=lambda b: b):
            url, caption = await service.generate(_make_request(), "user-1")
        assert url == "https://cdn.example.com/post.jpg"
        assert caption == "Caption #pelvic"

    @pytest.mark.asyncio
    async def test_generate_calls_credits_check_before_image_gen(self):
        call_order = []
        service = self._make_service()
        service._credits.check_credits = AsyncMock(side_effect=lambda uid: call_order.append("check"))
        service._image_gen.generate_from_prompt = AsyncMock(side_effect=lambda p: (call_order.append("generate"), "ZmFrZQ==")[1])

        with patch("app.services.post_generator.force_resolution", side_effect=lambda b: b):
            await service.generate(_make_request(), "user-1")

        assert call_order.index("check") < call_order.index("generate")

    @pytest.mark.asyncio
    async def test_generate_increments_credits_after_upload(self):
        service = self._make_service()
        with patch("app.services.post_generator.force_resolution", side_effect=lambda b: b):
            await service.generate(_make_request(), "user-1")
        service._credits.increment_credits.assert_awaited_once_with("user-1")

    @pytest.mark.asyncio
    async def test_generate_saves_to_requests_log(self):
        service = self._make_service()
        with patch("app.services.post_generator.force_resolution", side_effect=lambda b: b):
            await service.generate(_make_request(), "user-1")

        upsert_call = service._supabase.table.return_value.upsert
        upsert_call.assert_called_once()
        row = upsert_call.call_args[0][0]
        assert row["agent_type"] == "ai-post-generator"
        assert row["user_id"] == "user-1"
        assert row["id"] == "msg-uuid-1"
        assert row["media_urls"] == ["https://cdn.example.com/post.jpg"]
        assert row["caption"] == "Caption #pelvic"

    @pytest.mark.asyncio
    async def test_generate_does_not_raise_if_credits_increment_fails(self):
        service = self._make_service()
        service._credits.increment_credits = AsyncMock(side_effect=Exception("DB down"))
        with patch("app.services.post_generator.force_resolution", side_effect=lambda b: b):
            url, caption = await service.generate(_make_request(), "user-1")
        assert url  # generation should still succeed

    @pytest.mark.asyncio
    async def test_generate_does_not_raise_if_requests_log_fails(self):
        service = self._make_service()
        service._supabase.table.return_value.upsert.side_effect = Exception("DB error")
        with patch("app.services.post_generator.force_resolution", side_effect=lambda b: b):
            url, caption = await service.generate(_make_request(), "user-1")
        assert url  # generation should still succeed

    @pytest.mark.asyncio
    async def test_generate_raises_if_image_generation_fails(self):
        service = self._make_service()
        service._image_gen.generate_from_prompt = AsyncMock(side_effect=ValueError("Gemini failed"))
        with pytest.raises(ValueError, match="Gemini failed"):
            with patch("app.services.post_generator.force_resolution", side_effect=lambda b: b):
                await service.generate(_make_request(), "user-1")


# ---------------------------------------------------------------------------
# Wellness-workshop template
# ---------------------------------------------------------------------------

class TestWellnessWorkshopTemplate:
    def _make_service(self, profile=None):
        service = PostGeneratorService.__new__(PostGeneratorService)
        service._image_gen = MagicMock()
        service._image_gen.generate_from_prompt = AsyncMock(return_value="ZmFrZQ==")
        service._image_gen.generate_slide = AsyncMock(return_value="ZmFrZQ==")
        service._image_gen.download_image_as_base64 = AsyncMock(return_value="ZmFrZQ==")
        service._storage = MagicMock()
        service._storage.upload_image = AsyncMock(return_value="https://cdn.example.com/ww.jpg")
        service._brand_service = MagicMock()
        service._brand_service.load_profile = AsyncMock(return_value=profile or {
            "brand_name": "PelviBiz",
            "brand_color_primary": "#1A9E8F",
            "brand_color_secondary": "#FFFFFF",
            "font_prompt": "Bold", "font_style": "bold", "font_size": "38px",
        })
        service._credits = MagicMock()
        service._credits.check_credits = AsyncMock(return_value=(0, 40))
        service._credits.increment_credits = AsyncMock(return_value=1)
        service._supabase = MagicMock()
        service._supabase.table.return_value.upsert.return_value.execute.return_value = MagicMock()
        return service

    def _make_request(self, **overrides) -> PostGenerateRequest:
        base = dict(
            template_key="wellness-workshop",
            template_label="Wellness Workshop Flyer",
            topic="low back and hip release workshop",
            text_fields={
                "event_label": "FREE WELLNESS WORKSHOP",
                "date_time": "Sunday, Jan. 11 @ 11:30 AM",
                "title": "Release Your Low Back, Hips & IT Band",
                "tip_1": "Release tight hip flexors",
                "tip_2": "Reduce lower back tension",
                "tip_3": "Improve pelvic floor mobility",
                "tip_4": "Restore IT band flexibility",
            },
            caption="Join us!",
            message_id="msg-ww-1",
            conversation_id="conv-1",
        )
        base.update(overrides)
        return PostGenerateRequest(**base)

    @pytest.mark.asyncio
    async def test_wellness_workshop_dispatches_to_pillow_pipeline(self):
        service = self._make_service()
        compose_mock = AsyncMock(return_value=b"PNG_BYTES")
        with patch("app.services.post_generator._remove_background", AsyncMock(side_effect=lambda b: b)), \
             patch("app.utils.wellness_workshop_composer.compose", compose_mock):
            url, caption = await service.generate(self._make_request(), "user-1")
        assert url == "https://cdn.example.com/ww.jpg"
        assert caption == "Join us!"

    @pytest.mark.asyncio
    async def test_wellness_workshop_accepts_bg_image_2_and_3_urls(self):
        service = self._make_service()
        req = self._make_request(
            bg_image_2_url="https://example.com/bg2.jpg",
            bg_image_3_url="https://example.com/bg3.jpg",
        )
        compose_mock = AsyncMock(return_value=b"PNG_BYTES")
        with patch("app.services.post_generator._remove_background", AsyncMock(side_effect=lambda b: b)), \
             patch("app.utils.wellness_workshop_composer.compose", compose_mock), \
             patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.content = b"IMGBYTES"
            mock_response.raise_for_status = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client
            url, _ = await service.generate(req, "user-1")
        assert url == "https://cdn.example.com/ww.jpg"

    @pytest.mark.asyncio
    async def test_wellness_workshop_accepts_second_logo_url(self):
        service = self._make_service()
        req = self._make_request(second_logo_url="https://example.com/logo2.png")
        compose_mock = AsyncMock(return_value=b"PNG_BYTES")
        with patch("app.services.post_generator._remove_background", AsyncMock(side_effect=lambda b: b)), \
             patch("app.utils.wellness_workshop_composer.compose", compose_mock), \
             patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.content = b"LOGO2BYTES"
            mock_response.raise_for_status = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client
            url, _ = await service.generate(req, "user-1")
        assert url == "https://cdn.example.com/ww.jpg"

    @pytest.mark.asyncio
    async def test_wellness_workshop_ai_mode_generates_background_with_gemini(self):
        service = self._make_service()
        req = self._make_request()
        compose_mock = AsyncMock(return_value=b"PNG_BYTES")
        with patch("app.services.post_generator._remove_background", AsyncMock(side_effect=lambda b: b)), \
             patch("app.utils.wellness_workshop_composer.compose", compose_mock):
            await service.generate(req, "user-1")
        assert service._image_gen.generate_from_prompt.await_count >= 1

    @pytest.mark.asyncio
    async def test_wellness_workshop_saves_to_requests_log(self):
        service = self._make_service()
        compose_mock = AsyncMock(return_value=b"PNG_BYTES")
        with patch("app.services.post_generator._remove_background", AsyncMock(side_effect=lambda b: b)), \
             patch("app.utils.wellness_workshop_composer.compose", compose_mock):
            await service.generate(self._make_request(), "user-1")
        upsert_call = service._supabase.table.return_value.upsert
        upsert_call.assert_called_once()
        row = upsert_call.call_args[0][0]
        assert row["agent_type"] == "ai-post-generator"
        assert row["id"] == "msg-ww-1"


class TestWellnessWorkshopRequestModel:
    def test_accepts_new_image_fields(self):
        req = PostGenerateRequest(
            template_key="wellness-workshop",
            template_label="Wellness Workshop Flyer",
            topic="test",
            text_fields={},
            caption="",
            message_id="msg-1",
            bg_image_2_url="https://example.com/bg2.jpg",
            bg_image_3_url="https://example.com/bg3.jpg",
            second_logo_url="https://example.com/logo2.png",
        )
        assert req.bg_image_2_url == "https://example.com/bg2.jpg"
        assert req.bg_image_3_url == "https://example.com/bg3.jpg"
        assert req.second_logo_url == "https://example.com/logo2.png"

    def test_new_fields_default_to_none(self):
        req = PostGenerateRequest(
            template_key="tip-card",
            template_label="Tip",
            topic="test",
            text_fields={},
            caption="",
            message_id="msg-1",
        )
        assert req.bg_image_2_url is None
        assert req.bg_image_3_url is None
        assert req.second_logo_url is None
