from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.services.exceptions import AgentAPIError, StorageUploadError
from app.services.storage import StorageService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TrimWindow:
    start_seconds: float
    end_seconds: float
    duration_seconds: float


def validate_trim_window(*, mode: str, start_seconds: float, end_seconds: float, duration_seconds: float) -> TrimWindow:
    if start_seconds < 0:
        raise ValueError('trim start must be >= 0')
    if end_seconds <= start_seconds:
        raise ValueError('trim start must be less than end')
    if duration_seconds <= 0:
        raise ValueError('media duration must be positive')
    if end_seconds > duration_seconds:
        raise ValueError('trim end must be within media duration')
    return TrimWindow(start_seconds=start_seconds, end_seconds=end_seconds, duration_seconds=duration_seconds)


def build_ffmpeg_trim_command(input_path: str, output_path: str, start_seconds: float, end_seconds: float) -> list[str]:
    return [
        'ffmpeg',
        '-y',
        '-ss', f'{start_seconds}',
        '-to', f'{end_seconds}',
        '-i', input_path,
        '-c:v', 'libx264',
        '-c:a', 'aac',
        '-movflags', '+faststart',
        output_path,
    ]


class VideoTrimService:
    def __init__(self) -> None:
        self.storage = StorageService()

    async def trim_and_store(self, *, source_url: str, user_id: str, start_seconds: float, end_seconds: float) -> str:
        duration = await self._probe_duration(source_url)
        window = validate_trim_window(mode='manual', start_seconds=start_seconds, end_seconds=end_seconds, duration_seconds=duration)

        if shutil.which('ffmpeg') is None:
            raise AgentAPIError(
                message='Video trimming is unavailable on this server',
                code='TRIM_UNAVAILABLE',
                status_code=503,
                details={'missing': 'ffmpeg'},
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            input_path = tmp_path / 'input.mp4'
            output_path = tmp_path / 'output.mp4'

            await self._download_to_file(source_url, input_path)
            cmd = build_ffmpeg_trim_command(str(input_path), str(output_path), window.start_seconds, window.end_seconds)
            await asyncio.to_thread(self._run_command, cmd)
            video_bytes = output_path.read_bytes()
            return await self.storage.upload_video_bytes(video_bytes, user_id)

    async def _download_to_file(self, url: str, destination: Path) -> None:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.get(url)
            response.raise_for_status()
            destination.write_bytes(response.content)

    async def _probe_duration(self, url: str) -> float:
        if shutil.which('ffprobe') is None:
            return 60.0

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            input_path = tmp_path / 'probe.mp4'
            await self._download_to_file(url, input_path)
            cmd = [
                'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                '-of', 'json', str(input_path),
            ]
            output = await asyncio.to_thread(subprocess.check_output, cmd, text=True)
            data = json.loads(output)
            duration = float(data.get('format', {}).get('duration', 0))
            if duration <= 0:
                raise AgentAPIError(message='Could not determine video duration', code='TRIM_PROBE_FAILED', status_code=422)
            return duration

    def _run_command(self, cmd: list[str]) -> None:
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:
            logger.error('Video trim failed: %s', exc.stderr)
            raise StorageUploadError(path='video-trim', reason=exc.stderr or 'trim failed') from exc
