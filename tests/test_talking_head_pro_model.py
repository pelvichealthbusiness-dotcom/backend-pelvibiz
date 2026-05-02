"""Phase 6: talking-head-pro model validation tests (task 1.4 + 6.1-6.3)."""
import pytest
from pydantic import ValidationError

from app.models.video import GenerateVideoRequest


def _base() -> dict:
    return {"template": "talking-head", "video_urls": ["https://example.com/v.mp4"]}


# ── 6.1: voice_volume range ───────────────────────────────────────────────────

class TestVoiceVolumeValidation:
    def test_voice_volume_default_is_85(self):
        req = GenerateVideoRequest(**_base())
        assert req.voice_volume == 85.0

    def test_voice_volume_zero_is_valid(self):
        req = GenerateVideoRequest(**_base(), voice_volume=0)
        assert req.voice_volume == 0.0

    def test_voice_volume_100_is_valid(self):
        req = GenerateVideoRequest(**_base(), voice_volume=100)
        assert req.voice_volume == 100.0

    def test_voice_volume_above_100_raises(self):
        with pytest.raises(ValidationError):
            GenerateVideoRequest(**_base(), voice_volume=101)

    def test_voice_volume_below_0_raises(self):
        with pytest.raises(ValidationError):
            GenerateVideoRequest(**_base(), voice_volume=-1)


# ── 6.2: music_volume default ─────────────────────────────────────────────────

class TestMusicVolumeDefault:
    def test_music_volume_default_is_30(self):
        req = GenerateVideoRequest(**_base())
        assert req.music_volume == 30.0

    def test_music_volume_accepts_custom_value(self):
        req = GenerateVideoRequest(**_base(), music_volume=50)
        assert req.music_volume == 50.0


# ── 6.3: text_position ────────────────────────────────────────────────────────

class TestTextPositionValidation:
    def test_text_position_default_is_center(self):
        req = GenerateVideoRequest(**_base())
        assert req.text_position == "center"

    def test_text_position_bottom_accepted(self):
        req = GenerateVideoRequest(**_base(), text_position="bottom")
        assert req.text_position == "bottom"

    def test_text_position_none_accepted(self):
        req = GenerateVideoRequest(**_base(), text_position=None)
        assert req.text_position is None
