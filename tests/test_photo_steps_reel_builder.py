import pytest
from app.templates.renderscript_builders import build_photo_steps_reel
from app.templates.brand_theme import BrandTheme
from app.models.video import GenerateVideoRequest


def _make_request(urls, texts=None):
    data = {
        "template": "photo-steps-reel",
        "video_urls": urls,
        "message_id": "test-msg",
        "client_id": "test-client",
    }
    if texts:
        for i, t in enumerate(texts, 1):
            if t is not None:
                data[f"text_{i}"] = t
    return GenerateVideoRequest(**data)


def _make_theme(primary="#7C3AED", bg="#0F0F0F"):
    return BrandTheme(
        primary_color=primary,
        secondary_color="#FFFFFF",
        background_color=bg,
        font_family="Anton",
        font_weight="700",
        font_size_vmin="4.5 vmin",
        logo_url=None,
        music_url=None,
    )

def _clips(elements):
    return [e for e in elements if "Clip" in e.get("name", "")]


def test_four_clips_total_duration_16s():
    req = _make_request(["http://img1.jpg", "http://img2.jpg", "http://img3.jpg", "http://img4.jpg"])
    result = build_photo_steps_reel(req, _make_theme())
    assert pytest.approx(result["duration"], abs=1e-4) == 16.0


def test_seven_clips_total_duration_28s():
    urls = [f"http://img{i}.jpg" for i in range(7)]
    req = _make_request(urls)
    result = build_photo_steps_reel(req, _make_theme())
    assert pytest.approx(result["duration"], abs=1e-4) == 28.0


def test_clips_capped_at_7():
    urls = [f"http://img{i}.jpg" for i in range(10)]
    req = _make_request(urls)
    result = build_photo_steps_reel(req, _make_theme())
    assert len(_clips(result["elements"])) == 7


def test_clips_minimum_uses_provided_count():
    req = _make_request(["http://img1.jpg", "http://img2.jpg"])
    result = build_photo_steps_reel(req, _make_theme())
    assert len(_clips(result["elements"])) == 2


def test_clip_fit_is_contain():
    urls = ["http://img1.jpg", "http://img2.jpg", "http://img3.jpg", "http://img4.jpg"]
    req = _make_request(urls)
    result = build_photo_steps_reel(req, _make_theme())
    assert all(c.get("fit") == "contain" for c in _clips(result["elements"]))


def test_image_url_uses_image_type():
    req = _make_request(["http://cdn.example.com/photo.jpg"])
    result = build_photo_steps_reel(req, _make_theme())
    clip = _clips(result["elements"])[0]
    assert clip["type"] == "image"


def test_video_url_uses_video_type_and_is_muted():
    req = _make_request(["http://cdn.example.com/clip.mp4"])
    result = build_photo_steps_reel(req, _make_theme())
    clip = _clips(result["elements"])[0]
    assert clip["type"] == "video"
    assert clip.get("volume") == "0%"


def test_image_url_has_no_volume_field():
    req = _make_request(["http://cdn.example.com/photo.png"])
    result = build_photo_steps_reel(req, _make_theme())
    clip = _clips(result["elements"])[0]
    assert "volume" not in clip


def test_clip_time_offsets():
    urls = ["http://img1.jpg", "http://img2.jpg", "http://img3.jpg", "http://img4.jpg"]
    req = _make_request(urls)
    result = build_photo_steps_reel(req, _make_theme())
    clips = sorted(_clips(result["elements"]), key=lambda e: e["time"])
    assert clips[0]["time"] == pytest.approx(0.0, abs=1e-4)
    assert clips[1]["time"] == pytest.approx(4.0, abs=1e-4)
    assert clips[2]["time"] == pytest.approx(8.0, abs=1e-4)


def test_caption_uses_primary_color_background():
    urls = ["http://img1.jpg", "http://img2.jpg", "http://img3.jpg", "http://img4.jpg"]
    req = _make_request(urls, texts=["Step one", None, None, None])
    result = build_photo_steps_reel(req, _make_theme(primary="#FF0000"))
    texts = [e for e in result["elements"] if e.get("type") == "text"]
    assert texts[0].get("background_color") == "#FF0000"


def test_caption_text_appears_at_correct_time():
    urls = ["http://img1.jpg", "http://img2.jpg", "http://img3.jpg", "http://img4.jpg"]
    req = _make_request(urls, texts=["Caption", None, None, None])
    result = build_photo_steps_reel(req, _make_theme())
    text_el = next(e for e in result["elements"] if e.get("type") == "text")
    assert text_el["time"] == pytest.approx(0.0, abs=1e-4)
    assert text_el["duration"] == pytest.approx(4.0, abs=1e-4)


def test_no_caption_element_when_text_missing():
    urls = ["http://img1.jpg", "http://img2.jpg", "http://img3.jpg", "http://img4.jpg"]
    req = _make_request(urls)
    result = build_photo_steps_reel(req, _make_theme())
    texts = [e for e in result["elements"] if e.get("type") == "text"]
    assert len(texts) == 0


def test_caption_fill_color_contrasts_with_light_primary():
    urls = ["http://img1.jpg", "http://img2.jpg", "http://img3.jpg", "http://img4.jpg"]
    req = _make_request(urls, texts=["Step one", None, None, None])
    result = build_photo_steps_reel(req, _make_theme(primary="#FFFFFF"))
    texts = [e for e in result["elements"] if e.get("type") == "text"]
    assert texts[0].get("fill_color") == "#000000"


def test_caption_fill_color_is_white_on_dark_primary():
    urls = ["http://img1.jpg", "http://img2.jpg", "http://img3.jpg", "http://img4.jpg"]
    req = _make_request(urls, texts=["Step one", None, None, None])
    result = build_photo_steps_reel(req, _make_theme(primary="#1a1a1a"))
    texts = [e for e in result["elements"] if e.get("type") == "text"]
    assert texts[0].get("fill_color") == "#FFFFFF"


def test_output_dimensions_are_portrait():
    urls = ["http://img1.jpg", "http://img2.jpg", "http://img3.jpg", "http://img4.jpg"]
    req = _make_request(urls)
    result = build_photo_steps_reel(req, _make_theme())
    assert result["width"] == 1080
    assert result["height"] == 1920
