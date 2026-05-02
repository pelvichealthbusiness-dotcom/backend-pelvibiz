"""Phase 6 tasks 6.4-6.5: VideoStitchService error path tests."""
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.video_stitch_service import VideoStitchService
from app.services.exceptions import AgentAPIError


def _make_service() -> VideoStitchService:
    svc = VideoStitchService.__new__(VideoStitchService)
    svc.storage = MagicMock()
    svc.storage.upload_video_bytes = AsyncMock(return_value="https://example.com/out.mp4")
    return svc


URLS = ["https://example.com/c1.mp4", "https://example.com/c2.mp4"]


# ── 6.4: ffmpeg unavailable ───────────────────────────────────────────────────

class TestFfmpegUnavailable:
    @pytest.mark.asyncio
    async def test_raises_agent_api_error_when_ffmpeg_missing(self):
        svc = _make_service()
        with patch("app.services.video_stitch_service.shutil.which", return_value=None):
            with pytest.raises(AgentAPIError) as exc:
                await svc.concatenate_clips(URLS, user_id="u1")
        assert exc.value.code == "STITCH_UNAVAILABLE"
        assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_single_url_skips_ffmpeg_check(self):
        svc = _make_service()
        # Even with ffmpeg missing, single URL should return without error
        with patch("app.services.video_stitch_service.shutil.which", return_value=None):
            result = await svc.concatenate_clips(["https://example.com/c1.mp4"], user_id="u1")
        assert result == "https://example.com/c1.mp4"


# ── 6.5: empty output file ────────────────────────────────────────────────────

class TestEmptyOutputFile:
    @pytest.mark.asyncio
    async def test_raises_agent_api_error_when_output_empty(self):
        svc = _make_service()
        with patch("app.services.video_stitch_service.shutil.which", return_value="/usr/bin/ffmpeg"), \
             patch.object(svc, "_download_to_file", new_callable=AsyncMock), \
             patch("app.services.video_stitch_service.asyncio.to_thread", new_callable=AsyncMock), \
             patch("builtins.open", MagicMock()), \
             patch.object(Path, "exists", return_value=False):
            with pytest.raises(AgentAPIError) as exc:
                await svc.concatenate_clips(URLS, user_id="u1")
        assert exc.value.code == "STITCH_EMPTY_OUTPUT"
        assert exc.value.status_code == 500

    @pytest.mark.asyncio
    async def test_raises_when_output_zero_bytes(self):
        svc = _make_service()
        with patch("app.services.video_stitch_service.shutil.which", return_value="/usr/bin/ffmpeg"), \
             patch.object(svc, "_download_to_file", new_callable=AsyncMock), \
             patch("app.services.video_stitch_service.asyncio.to_thread", new_callable=AsyncMock), \
             patch("builtins.open", MagicMock()), \
             patch.object(Path, "exists", return_value=True), \
             patch.object(Path, "stat", return_value=MagicMock(st_size=0)):
            with pytest.raises(AgentAPIError) as exc:
                await svc.concatenate_clips(URLS, user_id="u1")
        assert exc.value.code == "STITCH_EMPTY_OUTPUT"
