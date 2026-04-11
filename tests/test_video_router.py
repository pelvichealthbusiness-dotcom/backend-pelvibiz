import pytest

from app.models.video import VideoTemplate
from app.routers.video import _should_force_renderscript, _validate_video_urls
from app.services.exceptions import AgentAPIError


@pytest.mark.parametrize('template', list(VideoTemplate))
def test_all_templates_use_renderscript(template):
    assert _should_force_renderscript(template) is True


def test_validate_video_urls_raises_clear_error():
    with pytest.raises(AgentAPIError) as exc:
        _validate_video_urls(VideoTemplate.DEEP_DIVE, ["one.mp4"])

    assert exc.value.code == "MISSING_VIDEO_URLS"
    assert "requires 7 video(s)" in exc.value.message
