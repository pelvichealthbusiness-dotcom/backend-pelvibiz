"""Tests for the caption recommendation endpoint.

Tests call `_build_recommendation` directly — a pure function that maps
a brand profile dict to CaptionRecommendationResponse. No HTTP layer needed.

RED phase: these tests fail until the router and handler are created.
"""

import pytest

from app.routers.caption import (
    CaptionRecommendationResponse,
    _SAFE_DEFAULTS,
    _build_recommendation,
)


def _profile(**kwargs) -> dict:
    base = {
        "id": "test-user",
        "brand_voice": "bold",
        "brand_color_primary": "#FFFFFF",
        "font_style": "bold",
        "background_hint": None,
    }
    base.update(kwargs)
    return base


class TestCaptionRecommendation:
    def test_recommendation_returns_bold_for_bold_tone(self):
        profile = _profile(brand_voice="bold")
        result = _build_recommendation(profile)
        assert result.font == "Anton"
        assert result.weight == "900"

    def test_recommendation_returns_montserrat_for_calm_tone(self):
        profile = _profile(brand_voice="calm")
        result = _build_recommendation(profile)
        assert result.font == "Montserrat"
        assert result.weight == "700"

    def test_recommendation_uses_primary_color(self):
        profile = _profile(brand_color_primary="#00FFAA")
        result = _build_recommendation(profile)
        assert result.color == "#00FFAA"

    def test_recommendation_thick_stroke_for_dark_background(self):
        profile = _profile(background_hint="dark")
        result = _build_recommendation(profile)
        assert result.stroke == "thick"

    def test_recommendation_returns_defaults_on_missing_profile(self):
        result = _build_recommendation(None)
        assert result.font == _SAFE_DEFAULTS.font
        assert result.color == _SAFE_DEFAULTS.color
        assert result.weight == _SAFE_DEFAULTS.weight
        assert result.stroke == _SAFE_DEFAULTS.stroke

    def test_recommendation_returns_defaults_on_empty_profile(self):
        result = _build_recommendation({})
        assert result.font == _SAFE_DEFAULTS.font
        assert result.color == _SAFE_DEFAULTS.color
