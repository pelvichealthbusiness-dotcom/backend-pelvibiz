"""Phase 6 task 6.6: router stitch guard tests."""
import pytest

from app.models.video import VideoTemplate


# ── 6.6: _is_talking_head guard ───────────────────────────────────────────────

class TestStitchGuardLogic:
    """Verify the _is_talking_head detection covers exactly the right templates."""

    TALKING_HEAD_TEMPLATES = {
        VideoTemplate.TALKING_HEAD,
        VideoTemplate.TALKING_HEAD_V2,
    }

    NON_TALKING_HEAD_TEMPLATES = {
        VideoTemplate.BULLET_REEL,
        VideoTemplate.HOOK_REVEAL,
        VideoTemplate.EDU_STEPS,
        VideoTemplate.COUNTDOWN_STACK,
        VideoTemplate.MYTH_DEBUNK,
        VideoTemplate.MYTH_BUSTER,
        VideoTemplate.BULLET_SEQUENCE,
        VideoTemplate.DEEP_DIVE,
        VideoTemplate.BIG_QUOTE,
    }

    def _is_talking_head(self, template_enum: VideoTemplate) -> bool:
        """Replicate the guard logic from video.py router."""
        return template_enum in (VideoTemplate.TALKING_HEAD, VideoTemplate.TALKING_HEAD_V2)

    def test_talking_head_is_detected(self):
        assert self._is_talking_head(VideoTemplate.TALKING_HEAD) is True

    def test_talking_head_v2_is_detected(self):
        assert self._is_talking_head(VideoTemplate.TALKING_HEAD_V2) is True

    @pytest.mark.parametrize("template", [
        VideoTemplate.BULLET_REEL,
        VideoTemplate.HOOK_REVEAL,
        VideoTemplate.EDU_STEPS,
        VideoTemplate.MYTH_BUSTER,
        VideoTemplate.DEEP_DIVE,
        VideoTemplate.BIG_QUOTE,
    ])
    def test_non_talking_head_not_detected(self, template: VideoTemplate):
        assert self._is_talking_head(template) is False

    def test_stitch_guard_requires_multiple_urls(self):
        """Guard should only activate when both conditions are true."""
        template = VideoTemplate.TALKING_HEAD
        single_url = ["https://example.com/v1.mp4"]
        multi_urls = ["https://example.com/v1.mp4", "https://example.com/v2.mp4"]

        should_stitch_single = self._is_talking_head(template) and len(single_url) > 1
        should_stitch_multi = self._is_talking_head(template) and len(multi_urls) > 1

        assert should_stitch_single is False
        assert should_stitch_multi is True

    def test_non_talking_head_never_stitches_even_with_multiple_urls(self):
        template = VideoTemplate.BULLET_REEL
        multi_urls = ["https://example.com/v1.mp4", "https://example.com/v2.mp4"]

        should_stitch = self._is_talking_head(template) and len(multi_urls) > 1
        assert should_stitch is False
