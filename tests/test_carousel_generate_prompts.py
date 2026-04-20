"""Tests for AI carousel image generation prompts."""

import pytest
from app.prompts.ai_carousel_generate import (
    build_per_slide_context,
    build_generic_slide_prompt,
    COMPOSITION_VARIATIONS,
    LIGHTING_VARIATIONS,
)


# ── build_per_slide_context — topic injection ─────────────────────────────


def _base_context(**overrides) -> dict:
    defaults = dict(
        slide_topic="pelvic floor recovery",
        visual_prompt="",
        brand_environment="bright clinical studio",
        brand_voice="profesional",
        slide_index=0,
        total_slides=5,
        slide_type="generic",
    )
    defaults.update(overrides)
    return defaults


def test_topic_prefix_present_when_topic_given():
    result = build_per_slide_context(**_base_context(), topic="pelvic floor recovery after birth")
    assert result.startswith("The carousel is about: pelvic floor recovery after birth.")


def test_topic_prefix_absent_when_topic_empty():
    result = build_per_slide_context(**_base_context(), topic="")
    assert "The carousel is about:" not in result


def test_topic_prefix_absent_when_topic_not_passed():
    result = build_per_slide_context(**_base_context())
    assert "The carousel is about:" not in result


def test_slide_topic_still_present_with_topic():
    result = build_per_slide_context(**_base_context(), topic="anxiety in perimenopause")
    assert "pelvic floor recovery" in result


# ── build_generic_slide_prompt — shared composition/lighting ─────────────


def test_explicit_composition_appears_in_prompt():
    result = build_generic_slide_prompt(
        visual_prompt="",
        text="Test slide",
        text_position="center",
        font_prompt="Anton",
        font_style="bold",
        font_size="48px",
        color_primary="#FFFFFF",
        color_secondary="#000000",
        composition="Close-up framing, intimate perspective",
        lighting="Golden hour warm lighting",
    )
    assert "Close-up framing, intimate perspective" in result
    assert "Golden hour warm lighting" in result


def test_explicit_lighting_overrides_random():
    result = build_generic_slide_prompt(
        visual_prompt="",
        text="Test slide",
        text_position="center",
        font_prompt="Anton",
        font_style="bold",
        font_size="48px",
        color_primary="#FFFFFF",
        color_secondary="#000000",
        composition="Wide shot, showing the full environment",
        lighting="Cool blue-hour twilight lighting",
    )
    assert "Cool blue-hour twilight lighting" in result


def test_no_composition_falls_back_to_random():
    result = build_generic_slide_prompt(
        visual_prompt="",
        text="Test slide",
        text_position="center",
        font_prompt="Anton",
        font_style="bold",
        font_size="48px",
        color_primary="#FFFFFF",
        color_secondary="#000000",
    )
    assert isinstance(result, str)
    assert len(result) > 50
