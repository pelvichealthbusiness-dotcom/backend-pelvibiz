from unittest.mock import MagicMock

from app.models.video import VideoTemplate
from app.templates.creatomate_mappings import (
    TEMPLATE_MAPPERS,
    ANALYSIS_MAPPERS,
    map_big_quote,
    map_viral_informative,
)


def make_request(**kwargs):
    mock = MagicMock()
    mock.video_urls = kwargs.get("video_urls", ["https://video.mp4"])
    mock.text_1 = kwargs.get("text_1", "Text 1")
    mock.text_2 = kwargs.get("text_2", "Text 2")
    mock.text_3 = kwargs.get("text_3", "Text 3")
    mock.text_4 = kwargs.get("text_4", "Text 4")
    mock.text_5 = kwargs.get("text_5", "Text 5")
    mock.text_6 = kwargs.get("text_6", "Text 6")
    mock.text_7 = kwargs.get("text_7", "Text 7")
    mock.text_8 = kwargs.get("text_8", "Text 8")
    mock.brand_settings = kwargs.get("brand_settings", {"primary_color": "#123456", "font_family": "Montserrat", "logo_url": None, "music_url": None})
    mock.brand_color_primary = kwargs.get("brand_color_primary", "#123456")
    mock.logo_url = kwargs.get("logo_url", None)
    mock.music_track = kwargs.get("music_track", None)
    return mock


def test_template_dispatch_tables_cover_expected_templates():
    assert set(TEMPLATE_MAPPERS.keys()) == {
        VideoTemplate.MYTH_BUSTER,
        VideoTemplate.BULLET_SEQUENCE,
        VideoTemplate.BIG_QUOTE,
        VideoTemplate.DEEP_DIVE,
        VideoTemplate.VIRAL_INFORMATIVE,
    }
    assert set(ANALYSIS_MAPPERS.keys()) == {
        VideoTemplate.VIRAL_REACTION,
        VideoTemplate.TESTIMONIAL_STORY,
    }


def test_viral_informative_returns_renderscript_source():
    mods, extra = map_viral_informative(make_request())

    assert "source" in mods
    assert extra == {}
    assert mods["source"]["output_format"] == "mp4"
    assert mods["source"]["elements"][0]["type"] == "video"


def test_big_quote_text_is_centered_and_readable():
    mods, extra = map_big_quote(make_request())

    assert mods["Text-1.visible"] is True
    assert mods["Text-1.x"] == "50%"
    assert mods["Text-1.y"] == "50%"
    assert mods["Text-1.width"] == "76%"
    assert mods["Text-1.x_anchor"] == "50%"
    assert mods["Text-1.y_anchor"] == "50%"
    assert mods["Text-1.text_align"] == "center"
    assert mods["Text-1.font_size"] == "5.2 vmin"
    assert mods["Video-1.volume"] == "0%"
    assert extra == {"output_format": "mp4", "width": 1080, "height": 1920}
