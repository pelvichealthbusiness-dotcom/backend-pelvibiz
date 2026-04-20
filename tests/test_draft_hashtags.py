"""Tests for hashtag count enforcement in draft generation prompts."""

import pytest
from app.prompts.draft_generate import build_draft_system_prompt, strip_extra_hashtags


# ── Prompt content ────────────────────────────────────────────────────────


def _minimal_brand() -> dict:
    return {
        "brand_name": "TestBrand",
        "target_audience": "professionals",
        "brand_voice": "professional",
        "brand_color_primary": "#000000",
    }


def test_system_prompt_says_3_hashtags():
    prompt = build_draft_system_prompt(_minimal_brand(), 3)
    assert "Exactly 3 hashtags" in prompt


def test_system_prompt_does_not_say_5_hashtags():
    prompt = build_draft_system_prompt(_minimal_brand(), 3)
    assert "Exactly 5 hashtags" not in prompt
    assert "exactly 5" not in prompt.lower()


def test_system_prompt_example_has_3_hashtags():
    prompt = build_draft_system_prompt(_minimal_brand(), 3)
    # The example format line should show 3 hashtags, not 5
    assert "#hashtag4" not in prompt
    assert "#hashtag5" not in prompt


# ── strip_extra_hashtags ──────────────────────────────────────────────────


def test_strip_keeps_first_3_when_5_given():
    caption = "Great insight.\n\nBody text here.\n\nDo this now.\n\n#a #b #c #d #e"
    result = strip_extra_hashtags(caption)
    assert result == "Great insight.\n\nBody text here.\n\nDo this now.\n\n#a #b #c"


def test_strip_unchanged_when_3_given():
    caption = "Great insight.\n\n#a #b #c"
    assert strip_extra_hashtags(caption) == caption


def test_strip_unchanged_when_no_hashtags():
    caption = "Just some text without hashtags."
    assert strip_extra_hashtags(caption) == caption


def test_strip_unchanged_when_fewer_than_3():
    caption = "Body text.\n\n#a #b"
    assert strip_extra_hashtags(caption) == caption


def test_strip_handles_hashtags_inline():
    caption = "Intro #a #b #c #d #e end"
    result = strip_extra_hashtags(caption)
    assert "#d" not in result
    assert "#e" not in result
    assert result.count("#") == 3
