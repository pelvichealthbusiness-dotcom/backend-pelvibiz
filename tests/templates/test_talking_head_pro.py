"""Talking-head-pro: caption position wiring + voice volume.

Tasks 2.1-2.4 (RED phase):
- S2.1: text_position='bottom' → caption y="78%"
- S2.2: text_position='center' → caption y="50%"
- S2.3: text_position=None → default "78%"
- S3.2: voice_volume flows to video element volume
"""
import pytest
from unittest.mock import MagicMock
from app.templates.brand_theme import BrandTheme
from app.templates.renderscript_builders import build_talking_head, build_talking_head_v2
from app.models.video import PhraseBlock


def _make_theme() -> BrandTheme:
    return BrandTheme(
        primary_color="#FF0000", secondary_color="#FFFFFF",
        background_color="#000000", font_family="Anton",
        font_weight="900", font_size_vmin="5 vmin",
        logo_url=None, music_url=None,
    )


def _make_request(**kwargs) -> MagicMock:
    req = MagicMock()
    req.video_urls = kwargs.get("video_urls", ["https://storage.example.com/video.mp4"])
    req.text_1 = kwargs.get("text_1", None)
    req.text_2 = kwargs.get("text_2", None)
    req.body_font = None
    req.body_color = None
    req.caption_font = None
    req.caption_color = None
    req.caption_weight = None
    req.caption_stroke = None
    req.hook_font = None
    req.hook_color = None
    req.text_position = kwargs.get("text_position", "bottom")
    req.voice_volume = kwargs.get("voice_volume", 85.0)
    req.music_track = None
    req.target_duration = None
    return req


def _phrase_blocks() -> list[PhraseBlock]:
    return [
        PhraseBlock(text="Hello world.", start=0.0, end=1.0),
        PhraseBlock(text="This is a test.", start=1.0, end=2.5),
    ]


def _caption_elements(source: dict) -> list[dict]:
    """Extract all text elements (captions) from the renderscript, excluding hook/title."""
    return [
        e for e in source["elements"]
        if e.get("type") == "text" and e.get("track", 0) >= 30
    ]


def _video_element(source: dict) -> dict | None:
    return next((e for e in source["elements"] if e.get("type") == "video"), None)


# ── Group 2: Caption position ─────────────────────────────────────────────

class TestCaptionPositionV1:
    """S2.1, S2.2, S2.3 for build_talking_head (v1)."""

    def test_bottom_uses_78_percent(self):
        """S2.1: text_position='bottom' → y='78%' for all caption elements."""
        req = _make_request(text_position="bottom")
        source = build_talking_head(req, _make_theme(), phrase_blocks=_phrase_blocks())
        captions = _caption_elements(source)
        assert len(captions) > 0, "Expected caption elements in output"
        for el in captions:
            assert el.get("y") == "78%", (
                f"Expected y='78%' for bottom position, got {el.get('y')!r}"
            )

    def test_center_uses_50_percent(self):
        """S2.2: text_position='center' → y='50%' for all caption elements."""
        req = _make_request(text_position="center")
        source = build_talking_head(req, _make_theme(), phrase_blocks=_phrase_blocks())
        captions = _caption_elements(source)
        assert len(captions) > 0
        for el in captions:
            assert el.get("y") == "50%", (
                f"Expected y='50%' for center position, got {el.get('y')!r}"
            )

    def test_none_defaults_to_78_percent(self):
        """S2.3: text_position=None → defaults to '78%'."""
        req = _make_request(text_position=None)
        source = build_talking_head(req, _make_theme(), phrase_blocks=_phrase_blocks())
        captions = _caption_elements(source)
        assert len(captions) > 0
        for el in captions:
            assert el.get("y") == "78%", (
                f"Expected y='78%' for None position, got {el.get('y')!r}"
            )

    def test_bottom_with_legacy_segments(self):
        """S2.1 triangulation: legacy segment path also respects text_position='bottom'."""
        analysis = MagicMock()
        analysis.duration_seconds = 3.0
        analysis.transcript_segments = [
            {"text": "Hello", "start": 0.0, "end": 1.0},
            {"text": "World", "start": 1.0, "end": 2.0},
        ]
        req = _make_request(text_position="bottom")
        source = build_talking_head(req, _make_theme(), analysis=analysis)
        captions = _caption_elements(source)
        assert len(captions) > 0
        for el in captions:
            assert el.get("y") == "78%"


class TestCaptionPositionV2:
    """S2.4: build_talking_head_v2 also respects text_position."""

    def test_bottom_uses_78_percent(self):
        req = _make_request(text_position="bottom")
        source = build_talking_head_v2(req, _make_theme(), phrase_blocks=_phrase_blocks())
        captions = _caption_elements(source)
        assert len(captions) > 0
        for el in captions:
            assert el.get("y") == "78%", (
                f"v2: Expected y='78%' for bottom, got {el.get('y')!r}"
            )

    def test_center_uses_50_percent(self):
        req = _make_request(text_position="center")
        source = build_talking_head_v2(req, _make_theme(), phrase_blocks=_phrase_blocks())
        captions = _caption_elements(source)
        assert len(captions) > 0
        for el in captions:
            assert el.get("y") == "50%", (
                f"v2: Expected y='50%' for center, got {el.get('y')!r}"
            )


# ── Group 3: Voice volume ─────────────────────────────────────────────────

class TestVoiceVolume:
    """S3.2: voice_volume flows to video element volume."""

    def test_default_voice_volume_85(self):
        """voice_volume=85 → video element volume='85%'."""
        req = _make_request(voice_volume=85.0)
        source = build_talking_head(req, _make_theme(), phrase_blocks=_phrase_blocks())
        video = _video_element(source)
        assert video is not None, "Expected a video element"
        assert video.get("volume") == "85%", (
            f"Expected volume='85%', got {video.get('volume')!r}"
        )

    def test_voice_volume_50(self):
        """Triangulation: voice_volume=50 → volume='50%'."""
        req = _make_request(voice_volume=50.0)
        source = build_talking_head(req, _make_theme(), phrase_blocks=_phrase_blocks())
        video = _video_element(source)
        assert video is not None
        assert video.get("volume") == "50%", (
            f"Expected volume='50%', got {video.get('volume')!r}"
        )

    def test_voice_volume_100(self):
        """Triangulation: voice_volume=100 → volume='100%'."""
        req = _make_request(voice_volume=100.0)
        source = build_talking_head(req, _make_theme(), phrase_blocks=_phrase_blocks())
        video = _video_element(source)
        assert video is not None
        assert video.get("volume") == "100%"

    def test_voice_volume_zero(self):
        """Edge: voice_volume=0 → volume='0%' (muted voice)."""
        req = _make_request(voice_volume=0.0)
        source = build_talking_head(req, _make_theme(), phrase_blocks=_phrase_blocks())
        video = _video_element(source)
        assert video is not None
        assert video.get("volume") == "0%"

    def test_v2_voice_volume_85(self):
        """S3.2 for v2: voice_volume=85 → volume='85%'."""
        req = _make_request(voice_volume=85.0)
        source = build_talking_head_v2(req, _make_theme(), phrase_blocks=_phrase_blocks())
        video = _video_element(source)
        assert video is not None
        assert video.get("volume") == "85%"
