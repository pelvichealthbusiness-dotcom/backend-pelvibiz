from __future__ import annotations
from typing import Optional, Any
from app.models.video import GenerateVideoRequest, VideoTemplate
from app.templates.brand_theme import BrandTheme

# ── Helpers ────────────────────────────────────────────────────────────────

def _base_source(duration: float, width: int = 1080, height: int = 1920) -> dict:
    return {"output_format": "mp4", "width": width, "height": height,
            "duration": duration, "elements": []}

def _video_elem(name: str, track: int, source: str, time: float, duration: float,
                volume: str = "0%", fit: str = "cover",
                trim_start: Optional[float] = None) -> dict:
    el: dict[str, Any] = {"type": "video", "track": track, "name": name,
                           "source": source, "time": time, "duration": duration,
                           "fit": fit, "volume": volume}
    if trim_start is not None:
        el["trim_start"] = trim_start
    return el

def _rect_elem(name: str, track: int, time: float, duration: float,
               fill_color: str, opacity: str = "100%",
               width: str = "100%", height: str = "100%",
               x: str = "0%", y: str = "0%") -> dict:
    return {"type": "shape", "track": track, "name": name,
            "time": time, "duration": duration, "fill_color": fill_color,
            "opacity": opacity, "width": width, "height": height, "x": x, "y": y}

def _text_elem(name: str, track: int, text: str, time: float, duration: float,
               theme: BrandTheme, y: str, fill_color: Optional[str] = None,
               font_size: Optional[str] = None, x: str = "8%", width: str = "84%",
               x_alignment: str = "50%", y_anchor: str = "50%") -> dict:
    el = {"type": "text", "track": track, "name": name, "text": text,
          "time": time, "duration": duration,
          "x": x, "y": y, "width": width,
          "x_anchor": "0%", "y_anchor": y_anchor,
          "font_family": theme.font_family, "font_weight": theme.font_weight,
          "font_size": font_size or theme.font_size_vmin,
          "fill_color": fill_color or theme.primary_color}
    if x_alignment and x_alignment != "50%":
        el["x_alignment"] = x_alignment
    return el

def _logo_elem(theme: BrandTheme, duration: float, track: int = 10) -> Optional[dict]:
    if not theme.logo_url:
        return None
    return {"type": "image", "track": track, "name": "Logo",
            "source": theme.logo_url, "duration": duration,
            "width": "13%", "height": "7%",
            "x": "82%", "y": "6%",
            "x_anchor": "0%", "y_anchor": "0%",
            "fit": "contain"}

def _audio_elem(theme: BrandTheme, duration: float, volume: str = "40%", track: int = 11) -> Optional[dict]:
    if not theme.music_url:
        return None
    return {"type": "audio", "track": track, "name": "Background Music",
            "source": theme.music_url, "time": 0, "volume": volume,
            "duration": duration, "loop": True}

def _add_optional(*elements) -> list[dict]:
    """Filter out None values from optional elements."""
    return [el for el in elements if el is not None]


# ── T5 — Big Quote (simplest — reference implementation) ───────────────────

def build_big_quote(request: GenerateVideoRequest, theme: BrandTheme, analysis=None) -> dict:
    dur = 8.0
    source = _base_source(dur)
    els = source["elements"]

    els.append(_video_elem("Video", 1, request.video_urls[0], 0, dur))
    els.append(_rect_elem("Overlay", 2, 0, dur, "#000000", opacity="45%"))
    els.append(_rect_elem("Accent Bar", 3, 0.3, dur - 0.6, theme.primary_color,
                          width="1.2%", height="30%", x="8%", y="35%"))
    els.append({
        "type": "text", "track": 4, "name": "Quote",
        "text": request.text_1 or "",
        "time": 0.4, "duration": dur - 0.8,
        "x": "14%", "y": "50%", "width": "78%",
        "y_anchor": "50%", "x_alignment": "0%",
        "font_family": theme.font_family, "font_weight": "700",
        "font_size": "5.5 vmin", "fill_color": "#FFFFFF",
        "shadow_color": "rgba(0,0,0,0.85)",
        "shadow_blur": "6px", "shadow_x": "0px", "shadow_y": "2px",
    })
    if theme.logo_url:
        els.append({
            "type": "image", "track": 10, "name": "Logo",
            "source": theme.logo_url, "duration": dur,
            "width": "13%", "height": "7%",
            "x": "80%", "y": "6%", "x_anchor": "0%", "y_anchor": "0%", "fit": "contain",
        })
    if theme.music_url:
        els.append(_audio_elem(theme, dur))
    return source

def build_myth_buster(request: GenerateVideoRequest, theme: BrandTheme, analysis=None) -> dict:
    dur = 9.5
    source = _base_source(dur)
    els = source["elements"]

    # Video background
    els.append(_video_elem("Video", 1, request.video_urls[0], 0, dur))
    # Subtle overlay
    els.append(_rect_elem("Overlay", 2, 0, dur, "#000000", opacity="35%"))

    # ── Segment 1: THE MYTH (0.0-2.3s) ─────────────────────────────────
    # Full-width band — x/y = top-left in shape elements
    els.append(_rect_elem("Band-1", 3, 0.0, 2.3, theme.primary_color,
                          opacity="90%", width="100%", height="14%",
                          x="0%", y="18%"))
    els.append({
        "type": "text", "track": 4, "name": "Myth",
        "text": (request.text_1 or "").upper(),
        "time": 0.0, "duration": 2.3,
        "x": "5%", "y": "19%", "width": "90%",
        "x_anchor": "0%", "y_anchor": "0%",
        "font_family": theme.font_family, "font_weight": "800",
        "font_size": "4 vmin", "fill_color": "#FFFFFF",
        "font_size_minimum": "2.5 vmin",
    })

    # ── Segment 2: THE TWIST (2.5-4.7s) ─────────────────────────────────
    els.append(_rect_elem("Band-2", 5, 2.5, 2.2, "rgba(255,255,255,0.92)",
                          opacity="100%", width="100%", height="16%",
                          x="0%", y="40%"))
    els.append({
        "type": "text", "track": 6, "name": "Twist",
        "text": request.text_2 or "",
        "time": 2.5, "duration": 2.2,
        "x": "5%", "y": "41%", "width": "90%",
        "x_anchor": "0%", "y_anchor": "0%",
        "font_family": theme.font_family, "font_weight": "700",
        "font_size": "3.8 vmin", "fill_color": theme.primary_color,
        "font_size_minimum": "2.5 vmin",
    })

    # ── Segment 3: THE TRUTH (5.0-7.5s) ─────────────────────────────────
    els.append(_rect_elem("Band-3", 7, 5.0, 2.5, "#000000",
                          opacity="72%", width="100%", height="16%",
                          x="0%", y="57%"))
    els.append({
        "type": "text", "track": 8, "name": "Truth",
        "text": request.text_3 or "",
        "time": 5.0, "duration": 2.5,
        "x": "5%", "y": "58%", "width": "90%",
        "x_anchor": "0%", "y_anchor": "0%",
        "font_family": theme.font_family, "font_weight": "700",
        "font_size": "3.8 vmin", "fill_color": "#FFFFFF",
        "font_size_minimum": "2.5 vmin",
    })

    # ── CTA (7.8-9.5s) ───────────────────────────────────────────────────
    els.append(_rect_elem("Band-4", 9, 7.8, 1.5, theme.primary_color,
                          opacity="90%", width="100%", height="10%",
                          x="0%", y="80%"))
    els.append({
        "type": "text", "track": 10, "name": "CTA",
        "text": request.text_4 or "",
        "time": 7.8, "duration": 1.5,
        "x": "5%", "y": "81%", "width": "90%",
        "x_anchor": "0%", "y_anchor": "0%",
        "font_family": theme.font_family, "font_weight": "600",
        "font_size": "3.2 vmin", "fill_color": "#FFFFFF",
        "font_size_minimum": "2 vmin",
    })

    # Logo — 13% width, top-right corner safe inside canvas
    if theme.logo_url:
        els.append({
            "type": "image", "track": 11, "name": "Logo",
            "source": theme.logo_url, "duration": dur,
            "width": "13%", "height": "7%",
            "x": "82%", "y": "6%",
            "x_anchor": "0%", "y_anchor": "0%",
            "fit": "contain",
        })

    if theme.music_url:
        els.append(_audio_elem(theme, dur, track=12))

    return source


def build_bullet_sequence(request: GenerateVideoRequest, theme: BrandTheme, analysis=None) -> dict:
    dur = 12.4
    source = _base_source(dur)
    els = source["elements"]

    # 3 video segments (~4.1s each)
    seg_dur = 4.1
    offsets = [0.0, 4.2, 8.4]
    for i, (url, t) in enumerate(zip(request.video_urls[:3], offsets), start=1):
        seg_d = dur - t if i == 3 else seg_dur
        els.append(_video_elem(f"Video-{i}", i, url, t, seg_d))

    # Full overlay
    els.append(_rect_elem("Overlay", 4, 0, dur, theme.background_color, opacity="55%"))

    # Hook (text_1) at start
    els.append(_text_elem("Hook", 5, request.text_1 or "", 0.3, 3.6,
                          theme, y="20%", fill_color=theme.primary_color, font_size="5 vmin"))

    # 3 bullet pairs (title + bullet)
    bullet_data = [
        (request.text_2 or "", request.text_3 or "", 4.2),
        (request.text_4 or "", request.text_5 or "", 8.4),
    ]
    track = 6
    for title_txt, bullet_txt, t_start in bullet_data:
        els.append(_text_elem(f"Title-{track}", track, title_txt, t_start + 0.2, 1.8,
                              theme, y="35%", fill_color=theme.primary_color, font_size="4.5 vmin"))
        els.append(_text_elem(f"Bullet-{track+1}", track + 1, bullet_txt, t_start + 2.2, 1.8,
                              theme, y="55%", fill_color="#FFFFFF", font_size="4 vmin"))
        track += 2

    # CTA (text_6) near end
    els.append(_text_elem("CTA", track, request.text_6 or "", 11.2, 1.0,
                          theme, y="80%", fill_color=theme.primary_color, font_size="3.5 vmin"))

    els.extend(_add_optional(_logo_elem(theme, dur, track=11), _audio_elem(theme, dur, track=12)))
    return source


# ── T3 — Viral Reaction ───────────────────────────────────────────────────

def build_viral_reaction(request: GenerateVideoRequest, theme: BrandTheme, analysis=None) -> dict:
    dur = float(getattr(analysis, "duration_seconds", None) or 30.0)
    trim = float(getattr(analysis, "start_time_seconds", None) or 0.0)
    hook_text = getattr(analysis, "generated_hook", None) or getattr(request, "text_1", None) or ""

    source = _base_source(dur)
    els = source["elements"]

    els.append(_video_elem("Video", 1, request.video_urls[0], 0, dur,
                           volume="100%", trim_start=trim if trim > 0 else None))
    # Bottom-third hook bar
    els.append(_rect_elem("Hook Bar", 2, 0, dur, theme.primary_color,
                          opacity="80%", width="100%", height="22%", x="0%", y="78%"))
    els.append(_text_elem("Hook Text", 3, hook_text, 0, dur,
                          theme, y="89%", fill_color="#FFFFFF", font_size="3.8 vmin",
                          x="4%", width="92%", x_alignment="50%"))
    els.extend(_add_optional(_logo_elem(theme, dur),
                             _audio_elem(theme, dur)))
    return source


# ── T4 — Testimonial Story ────────────────────────────────────────────────

def build_testimonial_story(request: GenerateVideoRequest, theme: BrandTheme, analysis=None) -> dict:
    dur = float(getattr(analysis, "duration_seconds", None) or 30.0)
    story_text = getattr(analysis, "generated_hook", None) or getattr(request, "text_1", None) or ""

    source = _base_source(dur)
    els = source["elements"]

    els.append(_video_elem("Video", 1, request.video_urls[0], 0, dur, volume="100%"))
    # Center panel
    els.append(_rect_elem("Panel", 2, 0, dur, theme.background_color,
                          opacity="78%", width="90%", height="35%", x="5%", y="57%"))
    # Accent top bar
    els.append(_rect_elem("Accent", 3, 0, dur, theme.primary_color,
                          opacity="100%", width="90%", height="0.6%", x="5%", y="57%"))
    els.append(_text_elem("Story", 4, story_text, 0, dur,
                          theme, y="74%", fill_color=theme.secondary_color,
                          font_size="3.9 vmin", x="7%", width="86%"))
    els.extend(_add_optional(_logo_elem(theme, dur),
                             _audio_elem(theme, dur)))
    return source


# ── T6 — Deep Dive ────────────────────────────────────────────────────────

def build_deep_dive(request: GenerateVideoRequest, theme: BrandTheme, analysis=None) -> dict:
    seg_dur = 5.0
    num_segments = 7
    dur = seg_dur * num_segments  # 35.0s

    source = _base_source(dur)
    els = source["elements"]

    # Title (text_1) across first segment
    els.append(_text_elem("Title", 1, request.text_1 or "", 0.0, 4.5,
                          theme, y="50%", fill_color="#FFFFFF",
                          font_size="6 vmin", x_alignment="50%"))

    # 7 video + overlay + statement segments
    statements = [
        request.text_2, request.text_3, request.text_4, request.text_5,
        request.text_6, request.text_7, request.text_8,
    ]
    video_track = 2
    rect_track = 9
    text_track = 16
    for i in range(num_segments):
        t = i * seg_dur
        url = request.video_urls[i] if i < len(request.video_urls) else request.video_urls[-1]
        # Alternate text colors for visual rhythm
        txt_color = theme.primary_color if i % 2 == 0 else theme.secondary_color

        els.append(_video_elem(f"Video-{i+1}", video_track + i, url, t, seg_dur))
        els.append(_rect_elem(f"Overlay-{i+1}", rect_track + i, t, seg_dur,
                              theme.background_color, opacity="50%"))
        els.append(_text_elem(f"Statement-{i+1}", text_track + i,
                              statements[i] or "", t + 0.3, seg_dur - 0.6,
                              theme, y="60%", fill_color=txt_color,
                              font_size="4.2 vmin"))

    els.extend(_add_optional(_logo_elem(theme, dur, track=50), _audio_elem(theme, dur, track=51)))
    return source


def build_brand_spotlight(request: GenerateVideoRequest, theme: BrandTheme, analysis=None) -> dict:
    dur = 9.0
    source = _base_source(dur)
    els = source["elements"]

    els.append(_video_elem("Video", 1, request.video_urls[0], 0, dur, volume="0%"))
    els.append(_rect_elem("Overlay", 2, 0, dur, theme.background_color, opacity="60%"))
    els.append(_text_elem("Hook", 3, request.text_1 or "", 0.2, 2.5, theme, y="18%", fill_color=theme.secondary_color, font_size="4.8 vmin"))
    els.append(_text_elem("Promise", 4, request.text_2 or "", 2.2, 3.0, theme, y="38%", fill_color="#FFFFFF", font_size="4.1 vmin"))
    els.append(_text_elem("Proof", 5, request.text_3 or "", 4.5, 2.8, theme, y="58%", fill_color=theme.primary_color, font_size="4.1 vmin"))
    els.append(_text_elem("CTA", 6, request.text_4 or "", 6.9, 1.6, theme, y="80%", fill_color="#FFFFFF", font_size="3.2 vmin"))
    els.extend(_add_optional(_logo_elem(theme, dur, track=50), _audio_elem(theme, dur, track=51)))
    return source


def build_social_proof_stack(request: GenerateVideoRequest, theme: BrandTheme, analysis=None) -> dict:
    dur = 14.0
    source = _base_source(dur)
    els = source["elements"]

    els.append(_video_elem("Video-1", 1, request.video_urls[0], 0, dur / 2, volume="0%"))
    els.append(_video_elem("Video-2", 2, request.video_urls[1], dur / 2, dur / 2, volume="0%"))
    els.append(_rect_elem("Overlay", 3, 0, dur, theme.background_color, opacity="58%"))
    els.append(_text_elem("Problem", 4, request.text_1 or "", 0.1, 3.0, theme, y="18%", fill_color=theme.secondary_color, font_size="4.1 vmin"))
    els.append(_text_elem("Result", 5, request.text_2 or "", 2.8, 3.0, theme, y="34%", fill_color="#FFFFFF", font_size="4.1 vmin"))
    els.append(_text_elem("Testimonial", 6, request.text_3 or "", 5.7, 3.0, theme, y="52%", fill_color=theme.primary_color, font_size="3.8 vmin"))
    els.append(_text_elem("Stats", 7, request.text_4 or "", 8.5, 2.5, theme, y="67%", fill_color="#FFFFFF", font_size="3.6 vmin"))
    els.append(_text_elem("CTA", 8, request.text_5 or "", 11.4, 1.8, theme, y="82%", fill_color=theme.primary_color, font_size="3.2 vmin"))
    els.extend(_add_optional(_logo_elem(theme, dur, track=50), _audio_elem(theme, dur, track=51)))
    return source


def build_offer_drop(request: GenerateVideoRequest, theme: BrandTheme, analysis=None) -> dict:
    dur = 10.0
    source = _base_source(dur)
    els = source["elements"]

    els.append(_video_elem("Video", 1, request.video_urls[0], 0, dur, volume="0%"))
    els.append(_rect_elem("Overlay", 2, 0, dur, theme.background_color, opacity="52%"))
    els.append(_text_elem("Hook", 3, request.text_1 or "", 0.1, 2.2, theme, y="18%", fill_color="#FFFFFF", font_size="4.6 vmin"))
    els.append(_text_elem("Offer", 4, request.text_2 or "", 2.1, 3.0, theme, y="39%", fill_color=theme.primary_color, font_size="4.3 vmin"))
    els.append(_text_elem("Urgency", 5, request.text_3 or "", 4.8, 2.7, theme, y="58%", fill_color=theme.secondary_color, font_size="4.0 vmin"))
    els.append(_text_elem("CTA", 6, request.text_4 or "", 7.1, 2.3, theme, y="80%", fill_color="#FFFFFF", font_size="3.4 vmin"))
    els.extend(_add_optional(_logo_elem(theme, dur, track=50), _audio_elem(theme, dur, track=51)))
    return source


# ── Dispatch table ────────────────────────────────────────────────────────

RENDERSCRIPT_BUILDERS: dict[VideoTemplate, Any] = {
    VideoTemplate.MYTH_BUSTER: build_myth_buster,
    VideoTemplate.BULLET_SEQUENCE: build_bullet_sequence,
    VideoTemplate.VIRAL_REACTION: build_viral_reaction,
    VideoTemplate.TESTIMONIAL_STORY: build_testimonial_story,
    VideoTemplate.BIG_QUOTE: build_big_quote,
    VideoTemplate.DEEP_DIVE: build_deep_dive,
    VideoTemplate.BRAND_SPOTLIGHT: build_brand_spotlight,
    VideoTemplate.SOCIAL_PROOF_STACK: build_social_proof_stack,
    VideoTemplate.OFFER_DROP: build_offer_drop,
}
