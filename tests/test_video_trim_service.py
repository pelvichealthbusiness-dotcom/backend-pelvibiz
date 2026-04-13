from pathlib import Path

from app.services.exceptions import StorageUploadError
from app.services.video_trim_service import validate_trim_window, build_ffmpeg_trim_command


def test_validate_trim_window_accepts_manual_range():
    window = validate_trim_window(mode='manual', start_seconds=3.5, end_seconds=9.25, duration_seconds=12.0)

    assert window.start_seconds == 3.5
    assert window.end_seconds == 9.25


def test_validate_trim_window_rejects_invalid_range():
    try:
        validate_trim_window(mode='manual', start_seconds=8.0, end_seconds=8.0, duration_seconds=12.0)
        assert False, 'Expected invalid range to fail'
    except ValueError as exc:
        assert 'start must be less than end' in str(exc)


def test_build_ffmpeg_command_uses_requested_range():
    cmd = build_ffmpeg_trim_command('/tmp/in.mp4', '/tmp/out.mp4', 4.0, 10.0)

    assert cmd[0] == 'ffmpeg'
    assert '-ss' in cmd and '4.0' in cmd
    assert '-t' in cmd and '6.0' in cmd
    assert '-c' in cmd and 'copy' in cmd
    assert cmd[-1] == '/tmp/out.mp4'


def test_build_ffmpeg_reencode_command_uses_requested_range():
    from app.services.video_trim_service import build_ffmpeg_reencode_command

    cmd = build_ffmpeg_reencode_command('/tmp/in.mp4', '/tmp/out.mp4', 4.0, 10.0)

    assert cmd[0] == 'ffmpeg'
    assert '-i' in cmd and '/tmp/in.mp4' in cmd
    assert '-ss' in cmd and '4.0' in cmd
    assert '-t' in cmd and '6.0' in cmd
    assert '-preset' in cmd and 'veryfast' in cmd
    assert '-pix_fmt' in cmd and 'yuv420p' in cmd
    assert cmd[-1] == '/tmp/out.mp4'


def test_trim_and_store_prefers_fast_copy_then_falls_back_to_reencode(tmp_path, monkeypatch):
    from app.services.video_trim_service import VideoTrimService

    service = VideoTrimService.__new__(VideoTrimService)
    calls = []

    class _Storage:
        async def upload_video_bytes(self, video_bytes, user_id):
            assert user_id == 'user-1'
            assert video_bytes == b'video-bytes'
            return 'https://example.com/trimmed.mp4'

    async def fake_download(_url, destination: Path):
        destination.write_bytes(b'input-video')

    async def fake_probe(_path: Path):
        return 20.0

    def fake_run(cmd):
        calls.append(cmd)
        output_path = Path(cmd[-1])
        if '-c' in cmd and 'copy' in cmd:
          # Fast path produces no output in this test, forcing the fallback.
            return
        output_path.write_bytes(b'video-bytes')

    service.storage = _Storage()
    service._download_to_file = fake_download  # type: ignore[assignment]
    service._probe_duration = fake_probe  # type: ignore[assignment]
    service._run_command = fake_run  # type: ignore[assignment]

    monkeypatch.setattr('app.services.video_trim_service.shutil.which', lambda name: '/usr/bin/ffmpeg' if name == 'ffmpeg' else '/usr/bin/ffprobe')

    result = __import__('asyncio').run(service.trim_and_store(source_url='https://example.com/input.mp4', user_id='user-1', start_seconds=2.0, end_seconds=5.0))

    assert result == 'https://example.com/trimmed.mp4'
    assert len(calls) == 2
    assert '-c' in calls[0] and 'copy' in calls[0]
    assert '-preset' in calls[1] and 'veryfast' in calls[1]
