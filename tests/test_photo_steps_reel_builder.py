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


def test_four_clips_total_duration_6s():
    req = _make_request(["http://img1.jpg", "http://img2.jpg", "http://img3.jpg", "http://img4.jpg"])
    result = build_photo_steps_reel(req, _make_theme())
    assert pytest.approx(result["duration"], abs=1e-4) == 6.0


def test_seven_clips_total_duration_10_5s():
    urls = [f"http://img{i}.jpg" for i in range(7)]
    req = _make_request(urls)
    result = build_photo_steps_reel(req, _make_theme())
    assert pytest.approx(result["duration"], abs=1e-4) == 10.5


def test_clips_capped_at_7():
    urls = [f"http://img{i}.jpg" for i in range(10)]
    req = _make_request(urls)
    result = build_photo_steps_reel(req, _make_theme())
    clips = [e for e in result["elements"] if e.get("type") == "video" and "Clip" in e.get("name", "")]
    assert len(clips) == 7


def test_clips_minimum_uses_provided_count():
    # With 2 media files, builder uses what it has (frontend enforces min 4 in production)
    req = _make_request(["http://img1.jpg", "http://img2.jpg"])
    result = build_photo_steps_reel(req, _make_theme())
    clips = [e for e in result["elements"] if e.get("type") == "video" and "Clip" in e.get("name", "")]
    assert len(clips) == 2


def test_clip_fit_is_cover():
    urls = ["http://img1.jpg", "http://img2.jpg", "http://img3.jpg", "http://img4.jpg"]
    req = _make_request(urls)
    result = build_photo_steps_reel(req, _make_theme())
    clips = [e for e in result["elements"] if e.get("type") == "video" and "Clip" in e.get("name", "")]
    assert all(c.get("fit") == "cover" for c in clips)


def test_clip_is_muted():
    urls = ["http://img1.jpg", "http://img2.jpg", "http://img3.jpg", "http://img4.jpg"]
    req = _make_request(urls)
    result = build_photo_steps_reel(req, _make_theme())
    clips = [e for e in result["elements"] if e.get("type") == "video" and "Clip" in e.get("name", "")]
    assert all(c.get("volume") == "0%" for c in clips)


def test_clip_time_offsets():
    urls = ["http://img1.jpg", "http://img2.jpg", "http://img3.jpg", "http://img4.jpg"]
    req = _make_request(urls)
    result = build_photo_steps_reel(req, _make_theme())
    clips = sorted(
        [e for e in result["elements"] if e.get("type") == "video" and "Clip" in e.get("name", "")],
        key=lambda e: e["time"],
    )
    assert clips[0]["time"] == pytest.approx(0.0, abs=1e-4)
    assert clips[1]["time"] == pytest.approx(1.5, abs=1e-4)
    assert clips[2]["time"] == pytest.approx(3.0, abs=1e-4)


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
    assert text_el["duration"] == pytest.approx(1.5, abs=1e-4)


def test_no_caption_element_when_text_missing():
    urls = ["http://img1.jpg", "http://img2.jpg", "http://img3.jpg", "http://img4.jpg"]
    req = _make_request(urls)
    result = build_photo_steps_reel(req, _make_theme())
    texts = [e for e in result["elements"] if e.get("type") == "text"]
    assert len(texts) == 0


def test_output_dimensions_are_portrait():
    urls = ["http://img1.jpg", "http://img2.jpg", "http://img3.jpg", "http://img4.jpg"]
    req = _make_request(urls)
    result = build_photo_steps_reel(req, _make_theme())
    assert result["width"] == 1080
    assert result["height"] == 1920
