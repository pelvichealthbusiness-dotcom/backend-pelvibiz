"""Tests for build_patient_review() multi-clip refactor."""
from __future__ import annotations
import pytest
from unittest.mock import MagicMock


def _make_request(video_urls, texts, hook_font="Anton", hook_color="#FFFFFF",
                  logo_url=None):
    req = MagicMock()
    req.video_urls = video_urls
    req.hook_font = hook_font
    req.hook_color = hook_color
    req.logo_url = logo_url
    for i, t in enumerate(texts, 1):
        setattr(req, f"text_{i}", t)
    # Set remaining text fields to None
    for j in range(len(texts) + 1, 7):
        setattr(req, f"text_{j}", None)
    return req

def _make_theme(primary="#7C3AED"):
    theme = MagicMock()
    theme.primary_color = primary
    theme.secondary_color = "#A78BFA"
    theme.background_color = "#0F0F0F"
    theme.text_color = "#FFFFFF"
    return theme


# Test 1: single review — total duration 6s
def test_single_review_duration_6s():
    from app.templates.renderscript_builders import build_patient_review
    req = _make_request(["http://img1.png"], ["What patients are saying"])
    result = build_patient_review(req, _make_theme())
    assert result["output_format"] == "mp4"
    assert float(result["duration"]) == pytest.approx(6.0)


# Test 2: 3 reviews — total duration 18s
def test_three_reviews_duration_18s():
    from app.templates.renderscript_builders import build_patient_review
    req = _make_request(
        ["http://img1.png", "http://img2.png", "http://img3.png"],
        ["Headline 1", "Headline 2", "Headline 3"]
    )
    result = build_patient_review(req, _make_theme())
    assert float(result["duration"]) == pytest.approx(18.0)


# Test 3: each review image appears at correct time
def test_review_images_have_correct_time_offset():
    from app.templates.renderscript_builders import build_patient_review
    req = _make_request(
        ["http://img1.png", "http://img2.png"],
        ["Headline 1", "Headline 2"]
    )
    result = build_patient_review(req, _make_theme())
    els = result["elements"]
    image_els = [e for e in els if e.get("type") == "image" and "screenshot" in str(e.get("name", "")).lower()]
    # Fallback: any images that are sources of our urls
    if not image_els:
        image_els = [e for e in els if e.get("type") == "image" and e.get("source") in ["http://img1.png", "http://img2.png"]]
    assert len(image_els) == 2
    times = sorted([float(e.get("time", 0)) for e in image_els])
    assert times[0] == pytest.approx(0.0)
    assert times[1] == pytest.approx(6.0)


# Test 4: headlines match their clip time
def test_headlines_match_clip_time():
    from app.templates.renderscript_builders import build_patient_review
    req = _make_request(
        ["http://img1.png", "http://img2.png"],
        ["Headline 1", "Headline 2"]
    )
    result = build_patient_review(req, _make_theme())
    els = result["elements"]
    text_els = [e for e in els if e.get("type") == "text" and "headline" in str(e.get("name", "")).lower()]
    # Alternative: find text elements containing our headline strings
    if not text_els:
        text_els = [e for e in els if e.get("type") == "text" and e.get("text") in ["Headline 1", "Headline 2"]]
    assert len(text_els) == 2
    # Headline 1 at t=0, Headline 2 at t=6 (text is uppercased by builder)
    texts_by_time = {round(float(e.get("time", 0)), 1): e.get("text") for e in text_els}
    assert texts_by_time.get(0.0) == "HEADLINE 1"
    assert texts_by_time.get(6.0) == "HEADLINE 2"


# Test 5: max 5 clips, ignore extra images
def test_max_5_clips_ignores_extra():
    from app.templates.renderscript_builders import build_patient_review
    req = _make_request(
        ["http://img1.png"] * 7,  # 7 images, should cap at 5
        ["H1", "H2", "H3", "H4", "H5", "H6", "H7"]
    )
    result = build_patient_review(req, _make_theme())
    assert float(result["duration"]) == pytest.approx(30.0)  # 5 * 6s


# Test 6: Oval halo appears once per clip at correct time
def test_oval_halo_per_clip():
    from app.templates.renderscript_builders import build_patient_review
    req = _make_request(
        ["http://img1.png", "http://img2.png", "http://img3.png"],
        ["H1", "H2", "H3"]
    )
    result = build_patient_review(req, _make_theme())
    els = result["elements"]
    halos = [e for e in els if "halo" in str(e.get("name", "")).lower() or "oval" in str(e.get("name", "")).lower()]
    assert len(halos) == 3
    times = sorted([round(float(e.get("time", 0)), 1) for e in halos])
    assert times == [0.0, 6.0, 12.0]


# Test 7: missing text falls back to empty string (no crash)
def test_missing_text_falls_back_to_empty():
    from app.templates.renderscript_builders import build_patient_review
    req = _make_request(
        ["http://img1.png", "http://img2.png"],
        ["Headline 1"]  # Only 1 text for 2 images
    )
    result = build_patient_review(req, _make_theme())
    assert result is not None
    assert float(result["duration"]) == pytest.approx(12.0)
