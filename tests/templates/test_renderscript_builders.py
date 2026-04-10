"""Unit tests for app/templates/renderscript_builders.py"""
import pytest
from unittest.mock import MagicMock
from app.templates.brand_theme import BrandTheme
from app.templates.renderscript_builders import (
    build_big_quote, build_myth_buster, build_bullet_sequence,
    build_viral_reaction, build_testimonial_story, build_deep_dive,
    build_brand_spotlight, build_social_proof_stack, build_offer_drop,
    RENDERSCRIPT_BUILDERS,
)
from app.models.video import VideoTemplate


def make_theme(logo_url=None, music_url=None) -> BrandTheme:
    return BrandTheme(
        primary_color="#FF0000",
        secondary_color="#FFFFFF",
        background_color="#000000",
        font_family="Poppins",
        font_weight="700",
        font_size_vmin="4.5 vmin",
        logo_url=logo_url,
        music_url=music_url,
    )


def make_request(**kwargs):
    mock = MagicMock()
    mock.video_urls = kwargs.get("video_urls", ["https://video.mp4"])
    mock.text_1 = kwargs.get("text_1", "Text 1")
    mock.text_2 = kwargs.get("text_2", "Text 2")
    mock.text_3 = kwargs.get("text_3", "Text 3")
    mock.text_4 = kwargs.get("text_4", "Text 4")
    mock.text_5 = kwargs.get("text_5", "Text 5")
    mock.text_6 = kwargs.get("text_6", "Text 6")
    mock.text_7 = kwargs.get("text_7", "Text 7")
    mock.text_8 = kwargs.get("text_8", "Text 8")
    mock.music_track = kwargs.get("music_track", None)
    return mock


class TestBigQuote:
    def test_base_structure(self):
        source = build_big_quote(make_request(), make_theme())
        assert source["output_format"] == "mp4"
        assert source["width"] == 1080
        assert source["height"] == 1920
        assert source["duration"] == 8.0

    def test_element_types_no_logo_no_audio(self):
        source = build_big_quote(make_request(), make_theme())
        types = [e["type"] for e in source["elements"]]
        assert types.count("video") == 1
        assert types.count("shape") == 2
        assert types.count("text") == 1
        assert "audio" not in types
        assert "image" not in types

    def test_with_logo_and_audio(self):
        theme = make_theme(logo_url="https://logo.png", music_url="https://music.mp3")
        source = build_big_quote(make_request(), theme)
        types = [e["type"] for e in source["elements"]]
        assert "audio" in types
        assert "image" in types

    def test_brand_colors_applied(self):
        theme = make_theme()
        source = build_big_quote(make_request(), theme)
        rects = [e for e in source["elements"] if e["type"] == "shape"]
        colors = {e["fill_color"] for e in rects}
        assert "#000000" in colors  # background_color
        assert "#FF0000" in colors  # primary_color (accent bar)

    def test_font_applied_to_text(self):
        theme = make_theme()
        source = build_big_quote(make_request(), theme)
        texts = [e for e in source["elements"] if e["type"] == "text"]
        assert all(e["font_family"] == "Poppins" for e in texts)
        assert all(e["font_weight"] == "700" for e in texts)


class TestMythBuster:
    def test_has_4_text_elements(self):
        source = build_myth_buster(make_request(), make_theme())
        texts = [e for e in source["elements"] if e["type"] == "text"]
        assert len(texts) == 4

    def test_duration(self):
        source = build_myth_buster(make_request(), make_theme())
        assert source["duration"] == 9.5

    def test_has_1_video(self):
        source = build_myth_buster(make_request(), make_theme())
        videos = [e for e in source["elements"] if e["type"] == "video"]
        assert len(videos) == 1


class TestBulletSequence:
    def test_has_3_videos(self):
        req = make_request(video_urls=["v1.mp4", "v2.mp4", "v3.mp4"])
        source = build_bullet_sequence(req, make_theme())
        videos = [e for e in source["elements"] if e["type"] == "video"]
        assert len(videos) == 3

    def test_duration(self):
        req = make_request(video_urls=["v1.mp4", "v2.mp4", "v3.mp4"])
        source = build_bullet_sequence(req, make_theme())
        assert source["duration"] == 12.4


class TestViralReaction:
    def test_duration_from_analysis(self):
        analysis = MagicMock()
        analysis.duration_seconds = 25.0
        analysis.start_time_seconds = 5.0
        analysis.generated_hook = "Hook text"
        source = build_viral_reaction(make_request(), make_theme(), analysis)
        assert source["duration"] == 25.0

    def test_duration_fallback_when_none(self):
        analysis = MagicMock()
        analysis.duration_seconds = None
        analysis.start_time_seconds = None
        analysis.generated_hook = None
        source = build_viral_reaction(make_request(), make_theme(), analysis)
        assert source["duration"] == 30.0

    def test_no_analysis_uses_fallback(self):
        source = build_viral_reaction(make_request(), make_theme(), None)
        assert source["duration"] == 30.0

    def test_video_preserves_audio(self):
        analysis = MagicMock()
        analysis.duration_seconds = 20.0
        analysis.start_time_seconds = 0.0
        analysis.generated_hook = "Hook"
        source = build_viral_reaction(make_request(), make_theme(), analysis)
        videos = [e for e in source["elements"] if e["type"] == "video"]
        assert videos[0]["volume"] == "100%"


class TestTestimonialStory:
    def test_duration_fallback(self):
        source = build_testimonial_story(make_request(), make_theme(), None)
        assert source["duration"] == 30.0

    def test_has_panel_and_accent(self):
        source = build_testimonial_story(make_request(), make_theme())
        rects = [e for e in source["elements"] if e["type"] == "shape"]
        assert len(rects) == 2  # panel + accent bar


class TestDeepDive:
    def test_has_7_videos(self):
        req = make_request(video_urls=[f"v{i}.mp4" for i in range(7)])
        source = build_deep_dive(req, make_theme())
        videos = [e for e in source["elements"] if e["type"] == "video"]
        assert len(videos) == 7

    def test_has_8_text_elements(self):
        req = make_request(video_urls=[f"v{i}.mp4" for i in range(7)])
        source = build_deep_dive(req, make_theme())
        texts = [e for e in source["elements"] if e["type"] == "text"]
        assert len(texts) == 8  # 1 title + 7 statements

    def test_duration_is_35s(self):
        req = make_request(video_urls=[f"v{i}.mp4" for i in range(7)])
        source = build_deep_dive(req, make_theme())
        assert source["duration"] == 35.0

    def test_logo_audio_high_tracks(self):
        theme = make_theme(logo_url="https://logo.png", music_url="https://music.mp3")
        req = make_request(video_urls=[f"v{i}.mp4" for i in range(7)])
        source = build_deep_dive(req, theme)
        img = next(e for e in source["elements"] if e["type"] == "image")
        audio = next(e for e in source["elements"] if e["type"] == "audio")
        assert img["track"] == 50
        assert audio["track"] == 51


class TestBrandSpotlight:
    def test_has_1_video_and_4_text_elements(self):
        source = build_brand_spotlight(make_request(), make_theme())
        videos = [e for e in source["elements"] if e["type"] == "video"]
        texts = [e for e in source["elements"] if e["type"] == "text"]
        assert source["duration"] == 9.0
        assert len(videos) == 1
        assert len(texts) == 4


class TestSocialProofStack:
    def test_has_2_videos_and_5_text_elements(self):
        req = make_request(video_urls=["v1.mp4", "v2.mp4"])
        source = build_social_proof_stack(req, make_theme())
        videos = [e for e in source["elements"] if e["type"] == "video"]
        texts = [e for e in source["elements"] if e["type"] == "text"]
        assert source["duration"] == 14.0
        assert len(videos) == 2
        assert len(texts) == 5


class TestOfferDrop:
    def test_has_1_video_and_4_text_elements(self):
        source = build_offer_drop(make_request(), make_theme())
        videos = [e for e in source["elements"] if e["type"] == "video"]
        texts = [e for e in source["elements"] if e["type"] == "text"]
        assert source["duration"] == 10.0
        assert len(videos) == 1
        assert len(texts) == 4


class TestDispatchTable:
    def test_all_templates_have_builders(self):
        expected = {
            VideoTemplate.MYTH_BUSTER, VideoTemplate.BULLET_SEQUENCE,
            VideoTemplate.VIRAL_REACTION, VideoTemplate.TESTIMONIAL_STORY,
            VideoTemplate.BIG_QUOTE, VideoTemplate.DEEP_DIVE,
            VideoTemplate.BRAND_SPOTLIGHT, VideoTemplate.SOCIAL_PROOF_STACK,
            VideoTemplate.OFFER_DROP,
        }
        assert set(RENDERSCRIPT_BUILDERS.keys()) == expected

    def test_builders_are_callable(self):
        for template, builder in RENDERSCRIPT_BUILDERS.items():
            assert callable(builder), f"{template} builder is not callable"
