from __future__ import annotations
from typing import Optional, Any
from app.models.video import GenerateVideoRequest, VideoTemplate, PhraseBlock
from app.templates.brand_theme import BrandTheme, CAPTION_FONT

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
               x_alignment: str = "50%", y_anchor: str = "50%",
               bg_color: Optional[str] = "rgba(0,0,0,0.75)",
               bg_x_padding: str = "8%", bg_y_padding: str = "4%") -> dict:
    el = {"type": "text", "track": track, "name": name, "text": text,
          "time": time, "duration": duration,
          "x": x, "y": y, "width": width,
          "x_anchor": "0%", "y_anchor": y_anchor,
          "font_family": theme.font_family, "font_weight": theme.font_weight,
          "font_size": font_size or theme.font_size_vmin,
          "fill_color": fill_color or theme.primary_color,
          "stroke_color": "#000000",
          "stroke_width": "1.2 vmin"}
    if x_alignment and x_alignment != "50%":
        el["x_alignment"] = x_alignment
    if bg_color is not None:
        el["background_color"] = bg_color
        el["background_x_padding"] = bg_x_padding
        el["background_y_padding"] = bg_y_padding
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

def _audio_elem(theme: BrandTheme, duration: float, track: int = 11) -> Optional[dict]:
    if not theme.music_url:
        return None
    return {"type": "audio", "track": track, "name": "Background Music",
            "source": theme.music_url, "time": 0, "volume": f"{int(theme.music_volume)}%",
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
        "x": "50%", "y": "50%", "width": "80%",
        "x_anchor": "50%", "y_anchor": "50%",
        "x_alignment": "50%",
        "font_family": theme.font_family, "font_weight": "700",
        "font_size": "5.5 vmin", "fill_color": "#FFFFFF",
        "background_color": "rgba(0,0,0,0.75)",
        "background_x_padding": "8%", "background_y_padding": "4%",
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
                          x="4%", width="92%", x_alignment="50%", bg_color=None))
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
                          font_size="3.9 vmin", x="7%", width="86%", bg_color=None))
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


# ── Helpers for new social-first templates ────────────────────────────────

_DURATION_MAP: dict[str, float] = {"15s": 15.0, "30s": 30.0, "60s": 60.0, "90s": 90.0}


def _resolve_target_duration(request, default: float = 30.0) -> float:
    raw = getattr(request, "target_duration", None) or ""
    return _DURATION_MAP.get(raw, default)


def _resolve_clip_count(request, default: int = 3, minimum: int = 1) -> int:
    val = getattr(request, "clip_count", None)
    return max(minimum, int(val)) if val else default


def _word_chunks(text: str, size: int = 3) -> list[str]:
    """Split text into groups of `size` words."""
    words = (text or "").split()
    return [" ".join(words[i : i + size]) for i in range(0, len(words), size)] or [""]


def _y_for_position(position: str | None, top: str = "15%", center: str = "50%", bottom: str = "78%") -> str:
    """Resolve a text position string to a CSS y% value."""
    if position == "top":
        return top
    if position == "bottom":
        return bottom
    return center  # default: center


def _y_caption_safe(position: str | None, has_captions: bool) -> str:
    """Return a y% that is guaranteed not to collide with caption zone (y > 65%).

    When captions are enabled, bottom position is remapped to center so
    template text never lands in the subtitle safe zone.
    """
    if has_captions and position == "bottom":
        return "50%"   # remap bottom → center when captions occupy the bottom
    return _y_for_position(position)


def _caption_elements(
    text: str,
    dur: float,
    start_track: int,
    theme: BrandTheme,
    y: str = "72%",
    font_size: str = "8 vmin",
    chunk_size: int = 3,
) -> list[dict]:
    """Split a caption into timed word-group elements for word-by-word animation.

    Always uses CAPTION_FONT (Anton) regardless of brand theme — captions must be
    legible over any video background.
    """
    chunks = _word_chunks(text, chunk_size)
    chunk_dur = dur / len(chunks)
    elements = []
    for i, chunk in enumerate(chunks):
        elements.append({
            "type": "text",
            "track": start_track + i,
            "name": f"Caption-{i}",
            "text": chunk,
            "time": round(i * chunk_dur, 3),
            "duration": round(chunk_dur - 0.08, 3),
            "x": "50%", "y": y,
            "x_anchor": "50%", "y_anchor": "50%",
            "x_alignment": "50%",
            "width": "85%",
            "font_family": CAPTION_FONT,   # Anton — always, never brand font
            "font_weight": "900",
            "font_size": font_size,
            "fill_color": "#FFFFFF",
            "stroke_color": "#000000",
            "stroke_width": "1.5 vmin",
            "background_color": "rgba(0,0,0,0.75)",
            "background_x_padding": "5%",
            "background_y_padding": "3%",
        })
    return elements


def _caption_elem(
    track: int,
    text: str,
    time: float,
    duration: float,
    y: str = "78%",
) -> dict:
    """OpusClip-style caption element.

    Heavy font (Anton 900), white text, thick black stroke, dark pill background.
    Max _MAX_CAPTION_WORDS words per block — split by _split_phrase before calling.
    """
    return {
        "type": "text",
        "track": track,
        "name": f"Sub-{track}",
        "text": text,
        "time": round(time, 3),
        "duration": round(max(duration, 0.5), 3),
        "x": "50%", "y": y,
        "x_anchor": "50%", "y_anchor": "50%",
        "x_alignment": "50%",
        "width": "85%",
        "font_family": CAPTION_FONT,   # Anton
        "font_weight": "900",
        "font_size": "8 vmin",
        "fill_color": "#FFFFFF",
        "stroke_color": "#000000",
        "stroke_width": "1.5 vmin",
        "background_color": "rgba(0,0,0,0.75)",
        "background_x_padding": "5%",
        "background_y_padding": "3%",
    }


_MAX_CAPTION_WORDS = 3


def _split_phrase(block: PhraseBlock, max_words: int = _MAX_CAPTION_WORDS) -> list[PhraseBlock]:
    """Split a long PhraseBlock into shorter sub-blocks of ≤ max_words.

    Time is distributed proportionally by word count so each sub-block
    gets a duration proportional to how many words it contains.
    """
    words = block.text.split()
    if len(words) <= max_words:
        return [block]

    total_dur = block.end - block.start
    chunks: list[list[str]] = []
    for i in range(0, len(words), max_words):
        chunks.append(words[i : i + max_words])

    result: list[PhraseBlock] = []
    cursor = block.start
    for chunk in chunks:
        chunk_dur = total_dur * len(chunk) / len(words)
        result.append(PhraseBlock(
            text=" ".join(chunk),
            start=round(cursor, 3),
            end=round(cursor + chunk_dur, 3),
        ))
        cursor += chunk_dur
    return result


def _append_captions(
    elements: list,
    phrase_blocks: list[PhraseBlock],
    y: str = "78%",
    base_track: int = 500,
) -> None:
    """Append OpusClip-style caption elements to `elements` in-place.

    Long phrase blocks are automatically split so no caption shows
    more than _MAX_CAPTION_WORDS words at once.
    """
    track = base_track
    for block in phrase_blocks:
        for sub in _split_phrase(block):
            duration = sub.end - sub.start
            elements.append(_caption_elem(
                track=track,
                text=sub.text,
                time=sub.start,
                duration=duration,
                y=y,
            ))
            track += 1


# ── Talking Head ──────────────────────────────────────────────────────────
#
# Layout:
#   TOP   → Hook card: white box, black bold text (static throughout)
#   BOTTOM → Caption: 3-word groups rotating (word-by-word animation)
#   Audio:  video audio ON (person is speaking)

def build_talking_head(
    request: GenerateVideoRequest,
    theme: BrandTheme,
    analysis=None,
    phrase_blocks: list[PhraseBlock] | None = None,
) -> dict:
    # Use actual video duration from Gemini analysis; fall back to target_duration or 30s
    if analysis and analysis.duration_seconds:
        dur = float(analysis.duration_seconds)
    elif phrase_blocks:
        # When using the new TranscriptionService we don't have a separate duration;
        # derive from the last block end + small tail buffer
        dur = phrase_blocks[-1].end + 0.5 if phrase_blocks else 30.0
    else:
        dur = _resolve_target_duration(request, 30.0)

    source = _base_source(dur)
    els = source["elements"]

    # Video — full duration, audio ON (person is speaking)
    url = request.video_urls[0] if request.video_urls else ""
    if url:
        els.append(_video_elem("Video", 1, url, 0.0, dur, volume="100%"))

    # HOOK card — TOP zone (10–20%), white box with dark text, static throughout
    # text_1 is optional; if not provided, no hook card shown
    hook = (request.text_1 or "").strip()
    if hook:
        els.append({
            "type": "text", "track": 20, "name": "Hook",
            "text": hook.upper(),
            "time": 0.0, "duration": dur,
            # Fixed at top zone — captions occupy bottom, hook occupies top
            "x": "50%", "y": "15%",
            "x_anchor": "50%", "y_anchor": "50%",
            "x_alignment": "50%",
            "width": "88%",
            "font_family": theme.font_family, "font_weight": "800",
            "font_size": "5.0 vmin",
            "fill_color": "#0A0A0A",
            "background_color": "#FFFFFF",
            "background_x_padding": "8%",
            "background_y_padding": "4%",
        })

    # CAPTIONS — bottom safe zone (70–90%), never overlaps hook at top
    # Priority: OpusClip phrase_blocks > legacy Gemini segments > manual text_2 fallback
    caption_y = "78%"   # Fixed for Talking Head — bottom safe zone per spec S3.2

    if phrase_blocks:
        # New pipeline: OpusClip-style phrase blocks from TranscriptionService
        _append_captions(els, phrase_blocks, y=caption_y, base_track=300)
    elif analysis and analysis.transcript_segments:
        # Legacy: raw Gemini segments (3-5 word chunks, no grouping)
        for i, seg in enumerate(analysis.transcript_segments):
            text = seg.get("text", "").strip()
            t_start = float(seg.get("start", 0))
            t_end = float(seg.get("end", t_start + 0.5))
            seg_dur = max(t_end - t_start - 0.05, 0.1)
            if not text:
                continue
            els.append(_caption_elem(
                track=30 + i,
                text=text,
                time=t_start,
                duration=seg_dur,
                y=caption_y,
            ))
    else:
        # Fallback: manual text_2 split into timed groups (no analysis available)
        caption_text = (request.text_2 or "").strip()
        if caption_text:
            caption_dur = dur - 1.0
            els.extend(_caption_elements(
                caption_text, caption_dur,
                start_track=30, theme=theme,
                y=caption_y, font_size="5.5 vmin", chunk_size=3,
            ))

    if theme.music_url:
        els.append(_audio_elem(theme, dur, track=200))

    return source


# ── Bullet Reel ───────────────────────────────────────────────────────────
#
# Layout:
#   Each clip = one big phrase CENTER SCREEN (hook → bullet 1 → bullet 2 …)
#   Text appears as 2-word micro-groups that pop on/off within each clip.
#   Overlay: dark semi-transparent. Audio: music only.

def build_bullet_reel(
    request: GenerateVideoRequest,
    theme: BrandTheme,
    analysis=None,
    phrase_blocks: list[PhraseBlock] | None = None,
) -> dict:
    clip_count = _resolve_clip_count(request, 3, 2)
    dur = _resolve_target_duration(request, 30.0)
    clip_dur = dur / clip_count

    source = _base_source(dur)
    els = source["elements"]

    videos = request.video_urls or []
    for i in range(clip_count):
        url = videos[i] if i < len(videos) else (videos[-1] if videos else "")
        if url:
            els.append(_video_elem(f"Video-{i + 1}", i + 1, url,
                                   round(i * clip_dur, 3), round(clip_dur, 3), volume="0%"))

    # Dark overlay across the whole video
    els.append(_rect_elem("Overlay", 20, 0, dur, "#000000", opacity="52%"))

    has_captions = bool(phrase_blocks)
    text_y = _y_caption_safe(getattr(request, "text_position", None), has_captions)

    if has_captions:
        # CAPTION LAYOUT — hook at top, captions carry the content at bottom.
        # Bullet text (text_2..6) is omitted — the captions are the narrative.
        # Hook (text_1) shown as a static top badge for the full duration.
        hook = (request.text_1 or "").strip()
        if hook:
            els.append({
                "type": "text",
                "track": 21,
                "name": "Hook",
                "text": hook.upper(),
                "time": 0.15,
                "duration": round(dur - 0.3, 3),
                "x": "50%", "y": "15%",
                "x_anchor": "50%", "y_anchor": "50%",
                "x_alignment": "50%",
                "width": "88%",
                "font_family": theme.font_family, "font_weight": "800",
                "font_size": "5.5 vmin",
                "fill_color": "#FFFFFF",
                "stroke_color": "#000000",
                "stroke_width": "1.2 vmin",
                "background_color": "rgba(0,0,0,0.55)",
                "background_x_padding": "6%", "background_y_padding": "3%",
            })
        _append_captions(els, phrase_blocks, y="78%", base_track=500)
    else:
        # ORIGINAL LAYOUT — 2-word micro-animation per clip, no captions.
        texts = [
            request.text_1, request.text_2, request.text_3,
            request.text_4, request.text_5, request.text_6,
        ]
        track_base = 21
        for clip_idx in range(clip_count):
            raw = (texts[clip_idx] or "").strip() if clip_idx < len(texts) else ""
            if not raw:
                continue
            t_start = clip_idx * clip_dur
            chunks = _word_chunks(raw, size=2)
            sub_dur = (clip_dur - 0.3) / len(chunks)
            for k, chunk in enumerate(chunks):
                els.append({
                    "type": "text",
                    "track": track_base + clip_idx * 10 + k,
                    "name": f"Text-{clip_idx + 1}-{k}",
                    "text": chunk.upper(),
                    "time": round(t_start + 0.15 + k * sub_dur, 3),
                    "duration": round(sub_dur - 0.08, 3),
                    "x": "50%", "y": text_y,
                    "x_anchor": "50%", "y_anchor": "50%",
                    "x_alignment": "50%",
                    "width": "88%",
                    "font_family": theme.font_family, "font_weight": "800",
                    "font_size": "7 vmin",
                    "fill_color": "#FFFFFF",
                    "stroke_color": "#000000",
                    "stroke_width": "1.2 vmin",
                })

    els.extend(_add_optional(_logo_elem(theme, dur, track=200), _audio_elem(theme, dur, track=201)))
    return source


# ── Hook Reveal ───────────────────────────────────────────────────────────
#
# Layout:
#   First ~45%: Hook words pop one-by-one (curiosity gap) — huge, white
#   Pause "..." beat
#   Next ~45%: Reveal phrase in brand primary color
#   Last ~10%: CTA

def build_hook_reveal(
    request: GenerateVideoRequest,
    theme: BrandTheme,
    analysis=None,
    phrase_blocks: list[PhraseBlock] | None = None,
) -> dict:
    dur = _resolve_target_duration(request, 20.0)
    hook_end = dur * 0.45
    reveal_start = dur * 0.48
    reveal_end = dur * 0.90
    cta_start = dur * 0.92

    source = _base_source(dur)
    els = source["elements"]

    videos = request.video_urls or []
    if len(videos) >= 2:
        els.append(_video_elem("Video-1", 1, videos[0], 0, hook_end, volume="0%"))
        els.append(_video_elem("Video-2", 2, videos[1], hook_end, dur - hook_end, volume="0%"))
    elif videos:
        els.append(_video_elem("Video", 1, videos[0], 0, dur, volume="0%"))

    els.append(_rect_elem("Overlay", 3, 0, dur, "#000000", opacity="55%"))

    has_captions = bool(phrase_blocks)
    text_y = _y_caption_safe(getattr(request, "text_position", None), has_captions)

    # HOOK: word by word (2-word groups) — first 45%
    hook = (request.text_1 or "").strip()
    if hook:
        chunks = _word_chunks(hook, size=2)
        sub_dur = (hook_end - 0.3) / len(chunks)
        for i, chunk in enumerate(chunks):
            els.append({
                "type": "text", "track": 10 + i, "name": f"Hook-{i}",
                "text": chunk.upper(),
                "time": round(0.2 + i * sub_dur, 3),
                "duration": round(sub_dur - 0.08, 3),
                "x": "50%", "y": text_y,
                "x_anchor": "50%", "y_anchor": "50%",
                "x_alignment": "50%", "width": "88%",
                "font_family": theme.font_family, "font_weight": "800",
                "font_size": "7.5 vmin", "fill_color": "#FFFFFF",
                "stroke_color": "#000000", "stroke_width": "1.2 vmin",
            })

    # Pause beat "..."
    els.append({
        "type": "text", "track": 30, "name": "Pause",
        "text": "...",
        "time": round(hook_end - 0.1, 3), "duration": 0.6,
        "x": "50%", "y": text_y,
        "x_anchor": "50%", "y_anchor": "50%",
        "x_alignment": "50%", "width": "50%",
        "font_family": theme.font_family, "font_weight": "700",
        "font_size": "6 vmin", "fill_color": theme.primary_color,
        "stroke_color": "#000000", "stroke_width": "1.2 vmin",
    })

    # REVEAL: big impactful text — 3-word groups
    reveal = (request.text_2 or "").strip()
    cta = (request.text_3 or "").strip()

    if reveal:
        reveal_dur = reveal_end - reveal_start
        chunks = _word_chunks(reveal, size=3)
        chunk_dur = reveal_dur / len(chunks)
        reveal_elements = []
        for i, chunk in enumerate(chunks):
            t = round(reveal_start + i * chunk_dur, 3)
            reveal_elements.append({
                "type": "text", "track": 40 + i, "name": f"Reveal-{i}",
                "text": chunk,
                "time": t,
                "duration": round(chunk_dur - 0.08, 3),
                "x": "50%", "y": text_y,
                "x_anchor": "50%", "y_anchor": "50%",
                "x_alignment": "50%", "width": "86%",
                "font_family": theme.font_family, "font_weight": "800",
                "font_size": "7 vmin",
                "fill_color": "#FFFFFF",
                "stroke_color": "#000000",
                "stroke_width": "1.2 vmin",
            })

        if not cta and reveal_elements:
            last = reveal_elements[-1]
            last["duration"] = round(dur - last["time"] - 0.1, 3)

        els.extend(reveal_elements)

    # CTA at end — layout depends on whether captions are present
    if cta:
        t_cta = round(cta_start, 3)
        cta_dur = round(dur - cta_start - 0.1, 3)

        if has_captions:
            # TOP ZONE CTA — captions own the bottom; CTA goes to a small top badge
            els.append({
                "type": "text", "track": 60, "name": "CTA",
                "text": cta,
                "time": t_cta, "duration": cta_dur,
                "x": "50%", "y": "12%",
                "x_anchor": "50%", "y_anchor": "50%",
                "x_alignment": "50%", "width": "88%",
                "font_family": theme.font_family, "font_weight": "700",
                "font_size": "4.5 vmin", "fill_color": "#FFFFFF",
                "stroke_color": "#000000", "stroke_width": "1 vmin",
                "background_color": theme.primary_color,
                "background_x_padding": "6%", "background_y_padding": "3%",
            })
        else:
            # ORIGINAL BOTTOM BAND CTA — no captions, bottom is free
            els.append(_rect_elem(
                "CTA-Accent", 58, t_cta, cta_dur,
                theme.primary_color, opacity="100%",
                width="100%", height="0.8%", x="0%", y="72%",
            ))
            els.append(_rect_elem(
                "CTA-Band", 59, t_cta, cta_dur,
                "#000000", opacity="88%",
                width="100%", height="20%", x="0%", y="73%",
            ))
            els.append({
                "type": "text", "track": 60, "name": "CTA",
                "text": cta,
                "time": t_cta, "duration": cta_dur,
                "x": "50%", "y": "83%",
                "x_anchor": "50%", "y_anchor": "50%",
                "x_alignment": "50%", "width": "88%",
                "font_family": theme.font_family, "font_weight": "700",
                "font_size": "5.5 vmin", "fill_color": "#FFFFFF",
                "stroke_color": "#000000", "stroke_width": "1.2 vmin",
            })

    if has_captions:
        _append_captions(els, phrase_blocks, y="78%", base_track=500)

    els.extend(_add_optional(_logo_elem(theme, dur, track=100), _audio_elem(theme, dur, track=101)))
    return source


# ── Edu Steps ─────────────────────────────────────────────────────────────
#
# Layout:
#   Title (text_1): TOP colored band, static throughout
#   Each clip: step number (①②③) + step text CENTER SCREEN

def build_edu_steps(
    request: GenerateVideoRequest,
    theme: BrandTheme,
    analysis=None,
    phrase_blocks: list[PhraseBlock] | None = None,
) -> dict:
    clip_count = _resolve_clip_count(request, 4, 2)
    dur = _resolve_target_duration(request, 30.0)

    videos = request.video_urls or []
    # Cap clip_count to number of uploaded videos — prevents silent URL reuse
    # when user uploads fewer videos than the template default (4 clips)
    if videos:
        clip_count = min(clip_count, len(videos))

    clip_dur = dur / clip_count

    source = _base_source(dur)
    els = source["elements"]

    for i in range(clip_count):
        url = videos[i]
        els.append(_video_elem(f"Video-{i + 1}", i + 1, url,
                               round(i * clip_dur, 3), round(clip_dur, 3), volume="0%"))

    els.append(_rect_elem("Overlay", 20, 0, dur, "#000000", opacity="48%"))

    # Title band — TOP, brand primary, static
    title = (request.text_1 or "").strip()
    if title:
        els.append({
            "type": "text", "track": 21, "name": "Title",
            "text": title.upper(),
            "time": 0.0, "duration": dur,
            "x": "50%", "y": "7%",
            "x_anchor": "50%", "y_anchor": "0%",
            "x_alignment": "50%", "width": "90%",
            "font_family": theme.font_family, "font_weight": "800",
            "font_size": "4.5 vmin",
            "fill_color": "#FFFFFF",
            "stroke_color": "#000000", "stroke_width": "1 vmin",
            "background_color": theme.primary_color,
            "background_x_padding": "8%", "background_y_padding": "4%",
        })

    # Steps — y positions shift up when captions occupy the bottom zone
    has_captions = bool(phrase_blocks)
    step_num_y = "25%" if has_captions else "36%"   # number: 36% → 25%
    step_text_y = "42%" if has_captions else "55%"  # text:   55% → 42%

    steps = [request.text_2, request.text_3, request.text_4, request.text_5, request.text_6]
    step_nums = ["①", "②", "③", "④", "⑤"]
    for i in range(clip_count):
        step_text = (steps[i] or "").strip() if i < len(steps) else ""
        if not step_text:
            continue
        t = round(i * clip_dur, 3)
        els.append({
            "type": "text", "track": 22 + i * 2, "name": f"StepNum-{i + 1}",
            "text": step_nums[i] if i < len(step_nums) else str(i + 1),
            "time": round(t + 0.15, 3), "duration": round(clip_dur - 0.3, 3),
            "x": "50%", "y": step_num_y,
            "x_anchor": "50%", "y_anchor": "50%",
            "x_alignment": "50%", "width": "88%",
            "font_family": theme.font_family, "font_weight": "800",
            "font_size": "8 vmin", "fill_color": theme.primary_color,
            "stroke_color": "#000000", "stroke_width": "1.2 vmin",
        })
        els.append({
            "type": "text", "track": 23 + i * 2, "name": f"Step-{i + 1}",
            "text": step_text,
            "time": round(t + 0.15, 3), "duration": round(clip_dur - 0.3, 3),
            "x": "50%", "y": step_text_y,
            "x_anchor": "50%", "y_anchor": "50%",
            "x_alignment": "50%", "width": "84%",
            "font_family": theme.font_family, "font_weight": "700",
            "font_size": "4.8 vmin", "fill_color": "#FFFFFF",
            "stroke_color": "#000000", "stroke_width": "1.2 vmin",
        })

    if has_captions:
        _append_captions(els, phrase_blocks, y="78%", base_track=500)

    els.extend(_add_optional(_logo_elem(theme, dur, track=200), _audio_elem(theme, dur, track=201)))
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
    VideoTemplate.BULLET_REEL: build_bullet_reel,
    VideoTemplate.TALKING_HEAD: build_talking_head,
    VideoTemplate.HOOK_REVEAL: build_hook_reveal,
    VideoTemplate.EDU_STEPS: build_edu_steps,
}
