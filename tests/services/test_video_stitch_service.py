"""VideoStitchService — Phase 3 TDD tests.

Tasks 3.1-3.3 (RED phase):
- S3.1: single URL → passthrough, no ffmpeg called
- S3.2: 2 URLs → ffmpeg concat called, stitched URL returned
- S3.3: 3 URLs → all 3 paths appear in concat demuxer list
"""
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from app.services.video_stitch_service import VideoStitchService


FAKE_URL_1 = "https://storage.example.com/clip1.mp4"
FAKE_URL_2 = "https://storage.example.com/clip2.mp4"
FAKE_URL_3 = "https://storage.example.com/clip3.mp4"
STITCHED_URL = "https://storage.example.com/stitched_abc123.mp4"


def _make_service(storage_upload_return: str = STITCHED_URL) -> VideoStitchService:
    svc = VideoStitchService.__new__(VideoStitchService)
    svc.storage = MagicMock()
    svc.storage.upload_video_bytes = AsyncMock(return_value=storage_upload_return)
    return svc


# ── S3.1: single URL passthrough ─────────────────────────────────────────────

class TestSingleUrlPassthrough:
    """S3.1: single clip → returns original URL, no ffmpeg."""

    @pytest.mark.asyncio
    async def test_single_url_returns_input_url(self):
        svc = _make_service()
        with patch("app.services.video_stitch_service.shutil.which", return_value="/usr/bin/ffmpeg"):
            result = await svc.concatenate_clips([FAKE_URL_1], user_id="user_1")
        assert result == FAKE_URL_1

    @pytest.mark.asyncio
    async def test_single_url_does_not_call_ffmpeg(self):
        svc = _make_service()
        with patch("app.services.video_stitch_service.shutil.which", return_value="/usr/bin/ffmpeg"), \
             patch("app.services.video_stitch_service.asyncio.to_thread") as mock_thread:
            await svc.concatenate_clips([FAKE_URL_1], user_id="user_1")
        mock_thread.assert_not_called()

    @pytest.mark.asyncio
    async def test_single_url_does_not_upload(self):
        svc = _make_service()
        with patch("app.services.video_stitch_service.shutil.which", return_value="/usr/bin/ffmpeg"):
            await svc.concatenate_clips([FAKE_URL_1], user_id="user_1")
        svc.storage.upload_video_bytes.assert_not_called()


# ── S3.2: 2 URLs → ffmpeg concat ─────────────────────────────────────────────

class TestTwoUrlConcat:
    """S3.2: 2 clips → ffmpeg concat called, stitched URL returned."""

    @pytest.mark.asyncio
    async def test_returns_stitched_url(self):
        svc = _make_service(STITCHED_URL)
        with patch("app.services.video_stitch_service.shutil.which", return_value="/usr/bin/ffmpeg"), \
             patch.object(svc, "_download_to_file", new_callable=AsyncMock) as mock_dl, \
             patch("app.services.video_stitch_service.asyncio.to_thread", new_callable=AsyncMock) as mock_thread, \
             patch("builtins.open", MagicMock()), \
             patch.object(Path, "read_bytes", return_value=b"fake_video_bytes"), \
             patch.object(Path, "exists", return_value=True), \
             patch.object(Path, "stat", return_value=MagicMock(st_size=12345)):
            result = await svc.concatenate_clips([FAKE_URL_1, FAKE_URL_2], user_id="user_1")
        assert result == STITCHED_URL

    @pytest.mark.asyncio
    async def test_ffmpeg_called_once(self):
        svc = _make_service()
        with patch("app.services.video_stitch_service.shutil.which", return_value="/usr/bin/ffmpeg"), \
             patch.object(svc, "_download_to_file", new_callable=AsyncMock), \
             patch("app.services.video_stitch_service.asyncio.to_thread", new_callable=AsyncMock) as mock_thread, \
             patch("builtins.open", MagicMock()), \
             patch.object(Path, "read_bytes", return_value=b"bytes"), \
             patch.object(Path, "exists", return_value=True), \
             patch.object(Path, "stat", return_value=MagicMock(st_size=1)):
            await svc.concatenate_clips([FAKE_URL_1, FAKE_URL_2], user_id="user_1")
        mock_thread.assert_called_once()

    @pytest.mark.asyncio
    async def test_downloads_both_clips(self):
        svc = _make_service()
        with patch("app.services.video_stitch_service.shutil.which", return_value="/usr/bin/ffmpeg"), \
             patch.object(svc, "_download_to_file", new_callable=AsyncMock) as mock_dl, \
             patch("app.services.video_stitch_service.asyncio.to_thread", new_callable=AsyncMock), \
             patch("builtins.open", MagicMock()), \
             patch.object(Path, "read_bytes", return_value=b"bytes"), \
             patch.object(Path, "exists", return_value=True), \
             patch.object(Path, "stat", return_value=MagicMock(st_size=1)):
            await svc.concatenate_clips([FAKE_URL_1, FAKE_URL_2], user_id="user_1")
        assert mock_dl.call_count == 2
        downloaded_urls = {c.args[0] for c in mock_dl.call_args_list}
        assert FAKE_URL_1 in downloaded_urls
        assert FAKE_URL_2 in downloaded_urls

    @pytest.mark.asyncio
    async def test_uploads_result_to_storage(self):
        svc = _make_service()
        with patch("app.services.video_stitch_service.shutil.which", return_value="/usr/bin/ffmpeg"), \
             patch.object(svc, "_download_to_file", new_callable=AsyncMock), \
             patch("app.services.video_stitch_service.asyncio.to_thread", new_callable=AsyncMock), \
             patch("builtins.open", MagicMock()), \
             patch.object(Path, "read_bytes", return_value=b"video_data"), \
             patch.object(Path, "exists", return_value=True), \
             patch.object(Path, "stat", return_value=MagicMock(st_size=1)):
            await svc.concatenate_clips([FAKE_URL_1, FAKE_URL_2], user_id="user_42")
        svc.storage.upload_video_bytes.assert_called_once()
        call_kwargs = svc.storage.upload_video_bytes.call_args
        assert call_kwargs.args[1] == "user_42" or call_kwargs.kwargs.get("user_id") == "user_42"


# ── S3.3: 3 URLs → all 3 in demuxer ─────────────────────────────────────────

class TestThreeUrlConcat:
    """S3.3: 3 clips → concat demuxer contains all 3 file paths."""

    @pytest.mark.asyncio
    async def test_ffmpeg_concat_command_uses_concat_flag(self):
        """ffmpeg command must use -f concat (not just -i for each file)."""
        svc = _make_service()
        captured_cmd: list[list[str]] = []

        async def fake_to_thread(fn, cmd, *args, **kwargs):
            captured_cmd.append(cmd)

        with patch("app.services.video_stitch_service.shutil.which", return_value="/usr/bin/ffmpeg"), \
             patch.object(svc, "_download_to_file", new_callable=AsyncMock), \
             patch("app.services.video_stitch_service.asyncio.to_thread", side_effect=fake_to_thread), \
             patch("builtins.open", MagicMock()), \
             patch.object(Path, "read_bytes", return_value=b"bytes"), \
             patch.object(Path, "exists", return_value=True), \
             patch.object(Path, "stat", return_value=MagicMock(st_size=1)):
            await svc.concatenate_clips([FAKE_URL_1, FAKE_URL_2, FAKE_URL_3], user_id="user_1")

        assert len(captured_cmd) == 1
        cmd = captured_cmd[0]
        assert "ffmpeg" in cmd[0]
        assert "-f" in cmd
        concat_idx = cmd.index("-f")
        assert cmd[concat_idx + 1] == "concat"

    @pytest.mark.asyncio
    async def test_downloads_all_three_clips(self):
        svc = _make_service()
        with patch("app.services.video_stitch_service.shutil.which", return_value="/usr/bin/ffmpeg"), \
             patch.object(svc, "_download_to_file", new_callable=AsyncMock) as mock_dl, \
             patch("app.services.video_stitch_service.asyncio.to_thread", new_callable=AsyncMock), \
             patch("builtins.open", MagicMock()), \
             patch.object(Path, "read_bytes", return_value=b"bytes"), \
             patch.object(Path, "exists", return_value=True), \
             patch.object(Path, "stat", return_value=MagicMock(st_size=1)):
            await svc.concatenate_clips([FAKE_URL_1, FAKE_URL_2, FAKE_URL_3], user_id="user_1")
        assert mock_dl.call_count == 3
