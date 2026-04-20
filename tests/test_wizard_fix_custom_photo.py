"""Tests for WizardFixAgent custom_photo fix type."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_custom_photo_skips_image_generator():
    """custom_photo fix type must not call ImageGeneratorService at all."""
    from app.agents.wizard_fix import WizardFixAgent

    fix_data = {
        "row_id": "test-row-id",
        "slide_number": 1,
        "slide_type": "custom_photo",
        "photo_url": "https://storage.example.com/user/custom.jpg",
        "new_text": "",
        "topic": "pelvic floor recovery",
    }

    mock_profile = {
        "brand_color_primary": "#000000",
        "brand_color_secondary": "#FFFFFF",
        "font_prompt": "Anton",
        "font_style": "bold",
    }

    mock_row = {
        "id": "test-row-id",
        "user_id": "test-user-id",
        "media_urls": ["https://storage.example.com/old1.jpg", "https://storage.example.com/old2.jpg"],
        "title": "Test Carousel",
        "metadata": {},
    }

    with (
        patch("app.agents.wizard_fix.BrandService") as MockBrandService,
        patch("app.agents.wizard_fix.get_supabase_admin") as mock_supabase_admin,
        patch("app.agents.wizard_fix.ImageGeneratorService") as MockImageGen,
        patch("app.agents.wizard_fix.WatermarkService") as MockWatermark,
        patch("app.agents.wizard_fix.StorageService") as MockStorage,
    ):
        MockBrandService.return_value.load_profile = AsyncMock(return_value=mock_profile)

        mock_supabase = MagicMock()
        mock_supabase_admin.return_value = mock_supabase
        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = mock_row
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

        agent = WizardFixAgent(user_id="test-user-id", agent_type="ai-carousel")
        events = []
        async for event in agent.stream(json.dumps(fix_data)):
            events.append(event)

        MockImageGen.assert_not_called()


@pytest.mark.asyncio
async def test_custom_photo_uses_provided_url():
    """custom_photo fix type must save the provided photo_url into media_urls."""
    from app.agents.wizard_fix import WizardFixAgent

    custom_url = "https://storage.example.com/user/custom.jpg"
    fix_data = {
        "row_id": "test-row-id",
        "slide_number": 1,
        "slide_type": "custom_photo",
        "photo_url": custom_url,
        "new_text": "",
        "topic": "pelvic floor recovery",
    }

    mock_profile = {
        "brand_color_primary": "#000000",
        "brand_color_secondary": "#FFFFFF",
        "font_prompt": "Anton",
        "font_style": "bold",
    }

    original_urls = ["https://storage.example.com/old1.jpg", "https://storage.example.com/old2.jpg"]
    mock_row = {
        "id": "test-row-id",
        "user_id": "test-user-id",
        "media_urls": original_urls,
        "title": "Test Carousel",
        "metadata": {},
    }

    saved_urls = []

    def capture_update(data):
        saved_urls.extend(data.get("media_urls", []))
        mock_chain = MagicMock()
        mock_chain.eq.return_value.execute.return_value = MagicMock()
        return mock_chain

    with (
        patch("app.agents.wizard_fix.BrandService") as MockBrandService,
        patch("app.agents.wizard_fix.get_supabase_admin") as mock_supabase_admin,
        patch("app.agents.wizard_fix.ImageGeneratorService"),
        patch("app.agents.wizard_fix.WatermarkService"),
        patch("app.agents.wizard_fix.StorageService"),
    ):
        MockBrandService.return_value.load_profile = AsyncMock(return_value=mock_profile)

        mock_supabase = MagicMock()
        mock_supabase_admin.return_value = mock_supabase
        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = mock_row
        mock_supabase.table.return_value.update.side_effect = capture_update

        agent = WizardFixAgent(user_id="test-user-id", agent_type="ai-carousel")
        events = []
        async for event in agent.stream(json.dumps(fix_data)):
            events.append(event)

        assert custom_url in saved_urls, f"Expected {custom_url} in saved_urls {saved_urls}"
