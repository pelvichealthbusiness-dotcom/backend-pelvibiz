import pytest

from app.routers.video import _maybe_trim_video_urls


@pytest.mark.asyncio
async def test_maybe_trim_video_urls_returns_original_list_when_trim_disabled(monkeypatch):
    called = False

    class DummyTrimService:
        async def trim_and_store(self, **kwargs):
            nonlocal called
            called = True
            return 'trimmed'

    monkeypatch.setattr('app.routers.video.VideoTrimService', DummyTrimService)

    class Req:
        trim_start_seconds = None
        trim_end_seconds = None

    urls = ['https://example.com/video.mp4']
    result = await _maybe_trim_video_urls(urls, 'user-1', Req())

    assert result == urls
    assert called is False
