"""
Template field mappings — converts GenerateVideoRequest fields to Creatomate
modification dicts.

IMPORTANT: Field names here MUST match the Creatomate template element names
exactly as used in the n8n workflow (verified 2026-04-04).

Wizard sends generic fields:
    video_urls[0..N]  →  video sources
    text_1..text_8    →  template-specific text overlays
    caption           →  social media caption (not sent to Creatomate)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.models.video import VideoAnalysisResult, VideoTemplate

if TYPE_CHECKING:
    from app.models.video import GenerateVideoRequest


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_OPACITY_LAYER = {
    "Opacity Layer.fill_color": "#575757",
    "Opacity Layer.opacity": "10%",
    "Opacity Layer.visible": True,
}


def _mute_video(key: str) -> dict:
    """Return volume=0% for a video element."""
    return {f"{key}.volume": "0%"}

def _apply_brand_identity(mods: dict, req: GenerateVideoRequest, is_background: bool = False) -> dict:
    """
    Centralized branding for all templates:
    1. Logo (Logo-1 or Logo)
    2. Music (Background Music or Music-1)
    3. Opacity Layer Color
    4. Fonts from brand_settings (Text-1..Text-10)
    """
    # 0. Colors
    if req.brand_settings and req.brand_settings.get('primary_color'):
        mods['Opacity Layer.fill_color'] = req.brand_settings['primary_color']
    # 1. Music
    music_vol = '20%' if is_background else '45%'
    if req.music_track and req.music_track.startswith('http'):
        mods['Background Music.source'] = req.music_track
        mods['Background Music.volume'] = music_vol
        mods['Music-1.source'] = req.music_track
        mods['Music-1.volume'] = music_vol

    # 2. Logo
    logo = req.logo_url or (req.brand_settings.get('logo_url') if req.brand_settings else None)
    if logo:
        mods['Logo.source'] = logo
        mods['Logo.visible'] = True
        mods['Logo-1.source'] = logo
        mods['Logo-1.visible'] = True

    # 3. Dynamic Styling (Fonts)
    if req.brand_settings:
        font_f = req.brand_settings.get('font_family')
        if font_f:
            for i in range(1, 11):
                key = f'Text-{i}'
                if key in mods or mods.get(f'{key}.visible') is True:
                    mods[f'{key}.font_family'] = font_f
    return mods

def _apply_music(mods: dict, req: GenerateVideoRequest) -> dict:
    return _apply_brand_identity(mods, req, is_background=False)

def _apply_music_background(mods: dict, req: 'GenerateVideoRequest') -> dict:
    return _apply_brand_identity(mods, req, is_background=True)
# ---------------------------------------------------------------------------
# T1 Myth Buster
# Creatomate elements: First Video, Text-1..Text-4
# Wizard: text_1=Hook, text_2=Myth, text_3=Truth, text_4=CTA
# ---------------------------------------------------------------------------

def map_myth_buster(req: GenerateVideoRequest) -> tuple[dict, dict]:
    """Returns (modifications, extra_params)."""
    mods = {
        **_OPACITY_LAYER,
        "First Video": req.video_urls[0],
        "First Video.volume": "0%",
        "Text-1": req.text_1 or "",
        "Text-1.visible": True,
        "Text-2": req.text_2 or "",
        "Text-2.visible": True,
        "Text-3": req.text_3 or "",
        "Text-3.visible": True,
        "Text-4": req.text_4 or "",
        "Text-4.visible": True,
    }
    extra = {
        "output_format": "mp4",
        "width": 1080,
        "height": 1920,
        "duration": 9.5,
        "snapshot_time": 3.18,
    }
    _apply_music(mods, req)
    return mods, extra


# ---------------------------------------------------------------------------
# T2 Bullet Sequence
# Creatomate elements: Video-1..Video-3, Text-1..Text-6
# Wizard: text_1=Hook, text_2=Bullet1, text_3=Bullet2, text_4=Bullet3,
#         text_5=Conclusion, text_6=CTA
# ---------------------------------------------------------------------------

def map_bullet_sequence(req: GenerateVideoRequest) -> tuple[dict, dict]:
    mods = {
        **_OPACITY_LAYER,
        "Video-1": req.video_urls[0],
        **_mute_video("Video-1"),
        "Video-2": req.video_urls[1],
        **_mute_video("Video-2"),
        "Video-3": req.video_urls[2],
        **_mute_video("Video-3"),
        "Text-1": req.text_1 or "",
        "Text-1.visible": True,
        "Text-2": req.text_2 or "",
        "Text-2.visible": True,
        "Text-3": req.text_3 or "",
        "Text-3.visible": True,
        "Text-4": req.text_4 or "",
        "Text-4.visible": True,
        "Text-5": req.text_5 or "",
        "Text-5.visible": True,
        "Text-6": req.text_6 or "",
        "Text-6.visible": True,
    }
    extra = {
        "output_format": "mp4",
        "width": 1080,
        "height": 1920,
        "duration": 12.388,
    }
    _apply_music(mods, req)
    return mods, extra


# ---------------------------------------------------------------------------
# T3 Viral Reaction
# Creatomate elements: Video-1, Video-1.trim_start, Text-1, duration
# Analysis provides: start_time_seconds, duration_seconds, generated_hook
# ---------------------------------------------------------------------------

def map_viral_reaction(
    req: GenerateVideoRequest, analysis: VideoAnalysisResult,
) -> tuple[dict, dict]:
    mods = {
        "Video-1": req.video_urls[0],
        "Video-1.trim_start": analysis.start_time_seconds or 0,
        "Text-1": analysis.generated_hook or "",
    }
    extra = {
        "output_format": "mp4",
        "duration": analysis.duration_seconds or 30,
    }
    _apply_music_background(mods, req)
    return mods, extra


# ---------------------------------------------------------------------------
# T4 Testimonial Story
# Creatomate elements: Video-1, Text-1 (multi-line via \n)
# Analysis provides: generated_hook (3 lines separated by \n)
# ---------------------------------------------------------------------------

def map_testimonial_story(
    req: GenerateVideoRequest, analysis: VideoAnalysisResult,
) -> tuple[dict, dict]:
    mods = {
        "Video-1": req.video_urls[0],
        "Text-1": analysis.generated_hook or "",
        "Text-1.visible": True,
        "Text-1.x_alignment": "50%",
        "Text-1.x_anchor": "50%",
        "Text-1.x": "50%",
        "Text-1.y_anchor": "50%",
        "Text-1.y": "71.6055%",
        "Text-1.font_size": "3.9 vmin",
    }
    extra = {
        "output_format": "mp4",
        "width": 1080,
        "height": 1920,
        "duration": analysis.duration_seconds or 30,
    }
    _apply_music_background(mods, req)
    return mods, extra


# ---------------------------------------------------------------------------
# T5 Big Quote
# Creatomate elements: Video-1, Text-1
# Wizard: text_1=Quote
# ---------------------------------------------------------------------------

def map_big_quote(req: GenerateVideoRequest) -> tuple[dict, dict]:
    mods = {
        **_OPACITY_LAYER,
        "Video-1": req.video_urls[0],
        **_mute_video("Video-1"),
        "Text-1": req.text_1 or "",
    }
    extra = {
        "output_format": "mp4",
        "width": 1080,
        "height": 1920,
    }
    _apply_music(mods, req)
    return mods, extra


# ---------------------------------------------------------------------------
# T6 Deep Dive (7 Lies Cycle)
# Creatomate elements: Title-Question, Text-1..Text-7, Video-1..Video-7
# Wizard: text_1=Title, text_2..text_8=Statement1..Statement7
# ---------------------------------------------------------------------------

def map_deep_dive(req: GenerateVideoRequest) -> tuple[dict, dict]:
    mods: dict = {
        "Title-Question": req.text_1 or "",
    }
    # Map text_2..text_8 → Text-1..Text-7
    for i in range(1, 8):
        text_val = getattr(req, f"text_{i + 1}", None) or ""
        mods[f"Text-{i}"] = text_val

    # Map video_urls[0..6] → Video-1..Video-7
    for i in range(7):
        mods[f"Video-{i + 1}"] = req.video_urls[i]
        mods[f"Video-{i + 1}.volume"] = "0%"

    extra = {
        "output_format": "mp4",
        "width": 1080,
        "height": 1920,
    }
    _apply_music(mods, req)
    return mods, extra


# ---------------------------------------------------------------------------
# Dispatcher tables
# ---------------------------------------------------------------------------

# Templates without Gemini analysis  →  (req) -> (mods, extra)

# ---------------------------------------------------------------------------
# T7 Viral Informative (Inspired by vaginadocs style)
# Elements: Video-Background, Hook-Box, Hook-Text, Music-1, Logo-1
# ---------------------------------------------------------------------------

def map_viral_informative(req: GenerateVideoRequest) -> tuple[dict, dict]:
    # Determine brand settings
    brand_color = "#000000"
    if req.brand_settings and req.brand_settings.get("brand_color_primary"):
        brand_color = req.brand_settings["brand_color_primary"]
    elif req.brand_color_primary:
        brand_color = req.brand_color_primary

    logo_url = req.logo_url or ""
    music_url = getattr(req, "music_track", None) or ""
    if req.brand_settings and req.brand_settings.get("music_url"):
        music_url = req.brand_settings["music_url"] or music_url

    video_bg = req.video_urls[0] if req.video_urls else ""
    hook_text = req.text_1 or ""

    source = {
        "output_format": "mp4",
        "width": 1080,
        "height": 1920,
        "elements": [
            {
                "type": "video",
                "source": video_bg,
                "duration": None,
                "audio_fade_out": 2,
                "z_index": 1
            }
        ]
    }

    # Add music if available
    if music_url:
        source["elements"].append({
            "type": "audio",
            "source": music_url,
            "volume": "25%",
            "loop": True,
            "z_index": 0
        })

    # Add Hook Box and Text if present
    if hook_text:
        source["elements"].append({
            "type": "shape",
            "shape": "rect",
            "fill_color": brand_color,
            "opacity": "85%",
            "width": "90%",
            "height": "400 px",
            "y": "35%",
            "border_radius": "20 px",
            "z_index": 10,
            "animations": [{ "type": "scale", "time": 0, "duration": 0.6, "easing": "quadratic-out" }]
        })
        source["elements"].append({
            "type": "text",
            "text": hook_text,
            "font_family": "Montserrat",
            "font_weight": "800",
            "font_size": "85 px",
            "fill_color": "#ffffff",
            "width": "80%",
            "y": "35%",
            "text_align": "center",
            "z_index": 11,
            "animations": [{ "type": "fade", "time": 0.2, "duration": 0.5 }]
        })

    # Add logo
    if logo_url:
        source["elements"].append({
            "type": "image",
            "source": logo_url,
            "width": "180 px",
            "x": "82%",
            "y": "8%".strip(),
            "opacity": "95%",
            "z_index": 20
        })

    # Add Captions element
    source["elements"].append({
        "type": "text",
        "text": "[[caption]]",
        "background_color": brand_color,
        "background_padding": "15 px",
        "fill_color": "#ffffff",
        "font_family": "Montserrat",
        "font_weight": "700",
        "font_size": "55 px",
        "y": "80%",
        "width": "85%",
        "text_align": "center",
        "z_index": 30
    })

    return {"source": source}, {}
TEMPLATE_MAPPERS = {
    VideoTemplate.MYTH_BUSTER: map_myth_buster,
    VideoTemplate.BULLET_SEQUENCE: map_bullet_sequence,
    VideoTemplate.BIG_QUOTE: map_big_quote,
    VideoTemplate.DEEP_DIVE: map_deep_dive,
    VideoTemplate.VIRAL_INFORMATIVE: map_viral_informative,
}

# Templates with Gemini analysis  →  (req, analysis) -> (mods, extra)
ANALYSIS_MAPPERS = {
    VideoTemplate.VIRAL_REACTION: map_viral_reaction,
    VideoTemplate.TESTIMONIAL_STORY: map_testimonial_story,
}
