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
