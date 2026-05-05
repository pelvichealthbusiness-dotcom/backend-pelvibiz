"""Tests for build_patient_review() — Real Video style, 1-7 clips."""
from __future__ import annotations
import pytest
from unittest.mock import MagicMock


def _make_request(video_urls, texts, hook_font="Anton", hook_color="#FFFFFF"):
    req = MagicMock()
    req.video_urls = video_urls
    req.hook_font = hook_font
    req.hook_color = hook_color
    req.logo_url = None
    for i, t in enumerate(texts, 1):
        setattr(req, f"text_{i}", t)
    for j in range(len(texts) + 1, 9):
        setattr(req, f"text_{j}", None)
    return req


def _make_theme(primary="#7C3AED", bg="#0F0F0F", font="Anton"):
    theme = MagicMock()
    theme.primary_color = primary
    theme.secondary_color = "#A78BFA"
    theme.background_color = bg
    theme.text_color = "#FFFFFF"
    theme.font_family = font
    theme.font_weight = "800"
    theme.font_size_vmin = "4.5 vmin"
    theme.logo_url = None
    theme.music_url = None
    theme.music_volume = 30
    return theme


# ── Duration tests ────────────────────────────────────────────────────────────

def test_single_clip_duration_6s():
    from app.templates.renderscript_builders import build_patient_review
    req = _make_request(["http://img1.png"], ["Headline 1"])
    result = build_patient_review(req, _make_theme())
    assert float(result["duration"]) == pytest.approx(6.0)


def test_three_clips_duration_18s():
    from app.templates.renderscript_builders import build_patient_review
    req = _make_request(
        ["http://img1.png", "http://img2.png", "http://img3.png"],
        ["H1", "H2", "H3"]
    )
    result = build_patient_review(req, _make_theme())
    assert float(result["duration"]) == pytest.approx(18.0)


def test_seven_clips_duration_42s():
    from app.templates.renderscript_builders import build_patient_review
    req = _make_request(["http://img.png"] * 7, [f"H{i}" for i in range(1, 8)])
    result = build_patient_review(req, _make_theme())
    assert float(result["duration"]) == pytest.approx(42.0)


def test_max_7_clips_caps_extra_images():
    from app.templates.renderscript_builders import build_patient_review
    req = _make_request(["http://img.png"] * 10, [f"H{i}" for i in range(1, 11)])
    result = build_patient_review(req, _make_theme())
    assert float(result["duration"]) == pytest.approx(42.0)  # 7 * 6s


# ── Image elements per clip ───────────────────────────────────────────────────

def test_review_images_have_correct_time_offset():
    from app.templates.renderscript_builders import build_patient_review
    req = _make_request(
        ["http://img1.png", "http://img2.png"],
        ["H1", "H2"]
    )
    result = build_patient_review(req, _make_theme())
    els = result["elements"]
    img_els = [e for e in els if e.get("type") == "image"
               and e.get("source") in ["http://img1.png", "http://img2.png"]]
    assert len(img_els) == 2
    times = sorted(float(e["time"]) for e in img_els)
    assert times[0] == pytest.approx(0.0)
    assert times[1] == pytest.approx(6.0)


def test_review_image_fit_is_contain():
    from app.templates.renderscript_builders import build_patient_review
    req = _make_request(["http://img1.png"], ["H1"])
    result = build_patient_review(req, _make_theme())
    els = result["elements"]
    img_el = next(e for e in els if e.get("type") == "image" and e.get("source") == "http://img1.png")
    assert img_el["fit"] == "contain"


# ── Headline elements ─────────────────────────────────────────────────────────

def test_headlines_stored_uppercase_at_correct_time():
    from app.templates.renderscript_builders import build_patient_review
    req = _make_request(
        ["http://img1.png", "http://img2.png"],
        ["great result", "amazing care"]
    )
    result = build_patient_review(req, _make_theme())
    els = result["elements"]
    text_els = [e for e in els if e.get("type") == "text"
                and e.get("text") in ["GREAT RESULT", "AMAZING CARE"]]
    assert len(text_els) == 2
    by_time = {round(float(e["time"]), 1): e["text"] for e in text_els}
    assert by_time[0.0] == "GREAT RESULT"
    assert by_time[6.0] == "AMAZING CARE"


def test_headline_uses_brand_primary_as_background():
    from app.templates.renderscript_builders import build_patient_review
    req = _make_request(["http://img1.png"], ["Headline"])
    theme = _make_theme(primary="#FF0000")
    result = build_patient_review(req, theme)
    els = result["elements"]
    text_el = next(e for e in els if e.get("type") == "text")
    assert text_el.get("background_color") == "#FF0000"


# ── No oval halo ──────────────────────────────────────────────────────────────

def test_no_oval_halo_elements():
    from app.templates.renderscript_builders import build_patient_review
    req = _make_request(["http://img1.png", "http://img2.png"], ["H1", "H2"])
    result = build_patient_review(req, _make_theme())
    els = result["elements"]
    ovals = [e for e in els if "halo" in str(e.get("name", "")).lower()
             or "oval" in str(e.get("name", "")).lower()
             or (e.get("type") == "shape" and e.get("shape") == "ellipse")]
    assert len(ovals) == 0


# ── Graceful fallback ─────────────────────────────────────────────────────────

def test_missing_text_no_crash():
    from app.templates.renderscript_builders import build_patient_review
    req = _make_request(
        ["http://img1.png", "http://img2.png"],
        ["Only one headline"]  # Fewer texts than images
    )
    result = build_patient_review(req, _make_theme())
    assert float(result["duration"]) == pytest.approx(12.0)
