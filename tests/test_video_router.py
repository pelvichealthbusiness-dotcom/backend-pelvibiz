import pytest

from app.models.video import VideoTemplate
from app.routers.video import _should_force_renderscript


@pytest.mark.parametrize('template', list(VideoTemplate))
def test_all_templates_use_renderscript(template):
    assert _should_force_renderscript(template) is True
