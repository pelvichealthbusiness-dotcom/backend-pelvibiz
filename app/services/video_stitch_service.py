from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

import httpx

from app.services.exceptions import AgentAPIError, StorageUploadError
from app.services.storage import StorageService

logger = logging.getLogger(__name__)


def build_ffmpeg_concat_command(list_path: str, output_path: str) -> list[str]:
    return [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", list_path,
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-movflags", "+faststart",
        output_path,
    ]


class VideoStitchService:
    def __init__(self) -> None:
        self.storage = StorageService()

    async def concatenate_clips(self, video_urls: list[str], user_id: str) -> str:
        """Stitch multiple clips into one MP4 and return the public storage URL.

        Single URL: returned as-is (no download, no ffmpeg).
        Multiple URLs: downloaded, concatenated with ffmpeg, uploaded, URL returned.
        """
        if len(video_urls) == 1:
            return video_urls[0]

        if shutil.which("ffmpeg") is None:
            raise AgentAPIError(
                message="Video stitching is unavailable on this server",
                code="STITCH_UNAVAILABLE",
                status_code=503,
                details={"missing": "ffmpeg"},
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            # Download all clips
            input_paths: list[Path] = []
            for idx, url in enumerate(video_urls):
                dest = tmp_path / f"clip_{idx}.mp4"
                await self._download_to_file(url, dest)
                input_paths.append(dest)

            # Write ffmpeg concat demuxer list
            list_path = tmp_path / "concat_list.txt"
            with open(list_path, "w") as f:
                for p in input_paths:
                    f.write(f"file '{p}'\n")

            output_path = tmp_path / "stitched.mp4"
            cmd = build_ffmpeg_concat_command(str(list_path), str(output_path))
            await asyncio.to_thread(self._run_command, cmd)

            if not output_path.exists() or output_path.stat().st_size == 0:
                raise AgentAPIError(
                    message="Video stitch produced an empty file",
                    code="STITCH_EMPTY_OUTPUT",
                    status_code=500,
                )

            video_bytes = output_path.read_bytes()
            return await self.storage.upload_video_bytes(video_bytes, user_id)

    async def _download_to_file(self, url: str, destination: Path) -> None:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.get(url)
            response.raise_for_status()
            destination.write_bytes(response.content)

    def _run_command(self, cmd: list[str]) -> None:
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:
            logger.error("Video stitch failed: %s", exc.stderr)
            raise StorageUploadError(path="video-stitch", reason=exc.stderr or "stitch failed") from exc
