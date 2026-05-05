"""Tests for build_photo_caption_reel — photo-caption-reel template."""
import pytest
from app.models.video import GenerateVideoRequest
from app.templates.brand_theme import BrandTheme
from app.templates.renderscript_builders import build_photo_caption_reel, CLIP_DURATION

def _base_theme(**kw) -> BrandTheme:
    defaults = dict(
        primary_color="#5A2D82", secondary_color="#A78BFA",
        background_color="#0F0F0F", font_family="Anton",
        font_weight="900", font_size_vmin="5 vmin",
        music_url=None, music_volume=30,
        logo_url=None,
    )
    defaults.update(kw)
    return BrandTheme(**defaults)

def _req(urls: list[str], **kw) -> GenerateVideoRequest:
    return GenerateVideoRequest(
        template="photo-caption-reel",
        video_urls=urls,
        **kw,
    )

FIVE_URLS = [f"https://cdn.example.com/p{i}.jpg" for i in range(1, 6)]
FOUR_URLS = [f"https://cdn.example.com/p{i}.jpg" for i in range(1, 5)]
SEVEN_URLS = [f"https://cdn.example.com/p{i}.jpg" for i in range(1, 8)]


class TestDuration:
    def test_five_clips_duration_is_7_5(self):
        result = build_photo_caption_reel(_req(FIVE_URLS), _base_theme())
        assert result["duration"] == pytest.approx(7.5)

    def test_four_clips_duration_is_6_0(self):
        result = build_photo_caption_reel(_req(FOUR_URLS), _base_theme())
        assert result["duration"] == pytest.approx(6.0)

    def test_seven_clips_duration_is_10_5(self):
        result = build_photo_caption_reel(_req(SEVEN_URLS), _base_theme())
        assert result["duration"] == pytest.approx(10.5)


class TestImageElements:
    def test_five_urls_produces_five_image_elements(self):
        result = build_photo_caption_reel(_req(FIVE_URLS), _base_theme())
        images = [e for e in result["elements"] if e.get("type") == "image" and "source" in e and "cdn.example" in e.get("source", "")]
        assert len(images) == 5

    def test_each_image_duration_is_1_5(self):
        result = build_photo_caption_reel(_req(FIVE_URLS), _base_theme())
        images = [e for e in result["elements"] if "cdn.example" in e.get("source", "")]
        for img in images:
            assert img["duration"] == pytest.approx(CLIP_DURATION)

    def test_image_timing_matches_clip_index(self):
        result = build_photo_caption_reel(_req(FIVE_URLS), _base_theme())
        images = sorted(
            [e for e in result["elements"] if "cdn.example" in e.get("source", "")],
            key=lambda e: e["time"],
        )
        for i, img in enumerate(images):
            assert img["time"] == pytest.approx(i * CLIP_DURATION)


class TestCaptionSynchronization:
    def test_caption_appears_at_same_time_as_image(self):
        req = _req(FIVE_URLS, text_1="First caption", text_2="Second caption")
        result = build_photo_caption_reel(req, _base_theme())
        texts = [e for e in result["elements"] if e.get("type") == "text"]
        times = [e["time"] for e in texts]
        assert 0.0 in times
        assert any(t == pytest.approx(1.5) for t in times)

    def test_missing_caption_produces_no_text_element_for_that_clip(self):
        # clip 3 has no caption (text_3 not set)
        req = _req(FIVE_URLS, text_1="A", text_2="B", text_4="D", text_5="E")
        result = build_photo_caption_reel(req, _base_theme())
        texts = [e for e in result["elements"] if e.get("type") == "text"]
        text_times = [e["time"] for e in texts]
        # clip 3 starts at 3.0 — no text should be at 3.0
        assert not any(t == pytest.approx(3.0) for t in text_times)

    def test_five_captions_produces_five_text_elements(self):
        req = _req(FIVE_URLS, text_1="A", text_2="B", text_3="C", text_4="D", text_5="E")
        result = build_photo_caption_reel(req, _base_theme())
        texts = [e for e in result["elements"] if e.get("type") == "text"]
        assert len(texts) == 5


class TestOptionalElements:
    def test_logo_present_when_logo_url_set(self):
        req = _req(FIVE_URLS, logo_url="https://cdn.example.com/logo.png")
        result = build_photo_caption_reel(req, _base_theme())
        logos = [e for e in result["elements"] if "logo.png" in e.get("source", "")]
        assert len(logos) == 1

    def test_no_logo_when_logo_url_not_set(self):
        req = _req(FIVE_URLS)
        result = build_photo_caption_reel(req, _base_theme())
        logos = [e for e in result["elements"] if "logo.png" in e.get("source", "")]
        assert len(logos) == 0

    def test_music_present_when_music_url_set(self):
        theme = _base_theme(music_url="https://cdn.example.com/music.mp3")
        result = build_photo_caption_reel(_req(FIVE_URLS), theme)
        audio = [e for e in result["elements"] if e.get("type") == "audio"]
        assert len(audio) == 1

    def test_no_music_when_music_url_not_set(self):
        result = build_photo_caption_reel(_req(FIVE_URLS), _base_theme())
        audio = [e for e in result["elements"] if e.get("type") == "audio"]
        assert len(audio) == 0


class TestFontAndColor:
    def test_caption_uses_hook_font_from_request(self):
        req = _req(FIVE_URLS, text_1="Hello", hook_font="Poppins")
        result = build_photo_caption_reel(req, _base_theme())
        texts = [e for e in result["elements"] if e.get("type") == "text"]
        assert all(t.get("font_family") == "Poppins" for t in texts)

    def test_caption_uses_hook_color_from_request(self):
        req = _req(FIVE_URLS, text_1="Hello", hook_color="#FF0000")
        result = build_photo_caption_reel(req, _base_theme())
        texts = [e for e in result["elements"] if e.get("type") == "text"]
        assert all(t.get("fill_color") == "#FF0000" for t in texts)

    def test_caption_falls_back_to_theme_font_when_hook_font_not_set(self):
        req = _req(FIVE_URLS, text_1="Hello")
        result = build_photo_caption_reel(req, _base_theme(font_family="Bebas Neue"))
        texts = [e for e in result["elements"] if e.get("type") == "text"]
        assert all(t.get("font_family") == "Bebas Neue" for t in texts)
