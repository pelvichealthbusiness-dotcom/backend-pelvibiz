"""Unit tests for app/templates/brand_theme.py"""
import pytest
from app.templates.brand_theme import (
    BrandTheme, resolve_theme, _resolve_font, _resolve_weight, _px_to_vmin, FONT_MAP
)


class TestResolveTheme:
    def test_empty_profile_returns_all_defaults(self):
        theme = resolve_theme({})
        assert theme.primary_color == "#1A1A2E"
        assert theme.secondary_color == "#FFFFFF"
        assert theme.background_color == "#0D0D0D"
        assert theme.font_family == "Montserrat"
        assert theme.font_weight == "700"
        assert theme.font_size_vmin == "4.0 vmin"
        assert theme.logo_url is None
        assert theme.music_url is None

    def test_full_profile_values_override_defaults(self):
        profile = {
            "brand_color_primary": "#FF0000",
            "brand_color_secondary": "#00FF00",
            "brand_color_background": "#0000FF",
            "logo_url": "https://example.com/logo.png",
        }
        theme = resolve_theme(profile, music_url="https://example.com/music.mp3")
        assert theme.primary_color == "#FF0000"
        assert theme.secondary_color == "#00FF00"
        assert theme.background_color == "#0000FF"
        assert theme.logo_url == "https://example.com/logo.png"
        assert theme.music_url == "https://example.com/music.mp3"

    def test_none_values_fall_through_to_defaults(self):
        profile = {"brand_color_primary": None, "logo_url": None}
        theme = resolve_theme(profile)
        assert theme.primary_color == "#1A1A2E"
        assert theme.logo_url is None

    def test_no_side_effects(self):
        profile = {}
        theme1 = resolve_theme(profile)
        profile["brand_color_primary"] = "#AABBCC"
        theme2 = resolve_theme(profile)
        assert theme1.primary_color == "#1A1A2E"
        assert theme2.primary_color == "#AABBCC"


class TestResolveFont:
    def test_known_keyword_returns_creatomate_name(self):
        assert _resolve_font("clean modern minimal") == "Inter"  # "clean" matches first

    def test_geometric_keyword(self):
        assert _resolve_font("geometric sans-serif bold") == "Montserrat"

    def test_playfair_keyword(self):
        assert _resolve_font("elegant serif display") == "Playfair Display"  # "serif" matches before "elegant" in FONT_MAP

    def test_unknown_returns_montserrat(self, caplog):
        import logging
        with caplog.at_level(logging.WARNING, logger="app.templates.brand_theme"):
            result = _resolve_font("xyzzy completely unknown font string")
        assert result == "Montserrat"
        assert "No font match" in caplog.text

    def test_none_returns_montserrat(self):
        assert _resolve_font(None) == "Montserrat"

    def test_empty_string_returns_montserrat(self):
        assert _resolve_font("") == "Montserrat"


class TestResolveWeight:
    def test_light_style(self):
        assert _resolve_weight("light sans") == "300"

    def test_regular_style(self):
        assert _resolve_weight("regular weight") == "400"

    def test_semibold_style(self):
        assert _resolve_weight("semibold modern") == "600"

    def test_black_style(self):
        assert _resolve_weight("black impact") == "900"

    def test_default_is_bold(self):
        assert _resolve_weight(None) == "700"
        assert _resolve_weight("some other text") == "700"


class TestPxToVmin:
    def test_basic_conversion(self):
        # 54px / 1080 * 100 = 5.0
        assert _px_to_vmin("54px") == "5.0 vmin"

    def test_integer_input(self):
        assert _px_to_vmin(54) == "5.0 vmin"

    def test_clamp_max(self):
        # 1000px would be 92.6 vmin → clamped to 8.0
        result = _px_to_vmin(1000)
        assert result == "8.0 vmin"

    def test_clamp_min(self):
        # 1px would be ~0.09 vmin → clamped to 2.5
        result = _px_to_vmin(1)
        assert result == "2.5 vmin"

    def test_none_returns_default(self):
        assert _px_to_vmin(None) == "4.0 vmin"

    def test_invalid_string_returns_default(self):
        assert _px_to_vmin("not_a_number") == "4.0 vmin"
