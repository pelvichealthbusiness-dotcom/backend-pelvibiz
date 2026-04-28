"""P3 Real Video — Pydantic models and template configuration."""

from dataclasses import dataclass
from enum import Enum
from typing import Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Caption / Transcription
# ---------------------------------------------------------------------------

@dataclass
class PhraseBlock:
    """A subtitle phrase block produced by TranscriptionService."""

    text: str
    start: float  # seconds
    end: float    # seconds


# ---------------------------------------------------------------------------
# Template enum & config
# ---------------------------------------------------------------------------

class VideoTemplate(str, Enum):
    MYTH_BUSTER = "myth-buster"
    BULLET_SEQUENCE = "bullet-sequence"
    VIRAL_REACTION = "viral-reaction"
    TESTIMONIAL_STORY = "testimonial-story"
    BIG_QUOTE = "big-quote"
    DEEP_DIVE = "deep-dive"
    VIRAL_INFORMATIVE = "viral-informative"
    BRAND_SPOTLIGHT = "brand-spotlight"
    SOCIAL_PROOF_STACK = "social-proof-stack"
    OFFER_DROP = "offer-drop"
    # New social-first templates
    BULLET_REEL = "bullet-reel"
    TALKING_HEAD = "talking-head"
    TALKING_HEAD_V2 = "talking-head-v2"
    HOOK_REVEAL = "hook-reveal"
    EDU_STEPS = "edu-steps"


TEMPLATE_CONFIG: dict[VideoTemplate, dict] = {
    VideoTemplate.VIRAL_INFORMATIVE: {
        "creatomate_id": "REPLACE_WITH_REAL_ID",
        "required_videos": 1,
        "required_text_count": 1,   # text_1 = Hook
        "needs_analysis": False,
        "output_format": "mp4",
        "width": 1080,
        "height": 1920,
    },
    VideoTemplate.MYTH_BUSTER: {
        "creatomate_id": "483fad02-e841-4a2b-b426-13bdaa403c3c",
        "required_videos": 1,
        "required_text_count": 4,   # text_1..text_4
        "needs_analysis": False,
        "output_format": "mp4",
        "width": 1080,
        "height": 1920,
        "duration": 9.5,
        "snapshot_time": 3.18,
    },
    VideoTemplate.BULLET_SEQUENCE: {
        "creatomate_id": "d74c192b-e963-4779-a07b-7d3ff9a579c9",
        "required_videos": 3,
        "required_text_count": 6,   # text_1..text_6
        "needs_analysis": False,
        "output_format": "mp4",
        "width": 1080,
        "height": 1920,
        "duration": 12.388,
    },
    VideoTemplate.VIRAL_REACTION: {
        "creatomate_id": "b3aa0d23-0976-4f20-9f93-2b33ca203adf",
        "required_videos": 1,
        "required_text_count": 0,
        "needs_analysis": True,
        "output_format": "mp4",
    },
    VideoTemplate.TESTIMONIAL_STORY: {
        "creatomate_id": "99f744cc-2511-4034-8b03-2ec8ad9b5db9",
        "required_videos": 1,
        "required_text_count": 0,
        "needs_analysis": True,
        "output_format": "mp4",
        "width": 1080,
        "height": 1920,
    },
    VideoTemplate.BIG_QUOTE: {
        "creatomate_id": "bdd71705-e4ec-4151-9468-50612c6d4de8",
        "required_videos": 1,
        "required_text_count": 1,   # text_1 = Quote
        "needs_analysis": False,
        "output_format": "mp4",
        "width": 1080,
        "height": 1920,
    },
    VideoTemplate.DEEP_DIVE: {
        "creatomate_id": "8aa55efd-9983-462b-ad37-c3eafb90c8d2",
        "required_videos": 7,
        "required_text_count": 8,   # text_1=Title, text_2..text_8=Statements
        "needs_analysis": False,
        "output_format": "mp4",
        "width": 1080,
        "height": 1920,
    },
    VideoTemplate.BRAND_SPOTLIGHT: {
        "creatomate_id": "REPLACE_WITH_REAL_ID",
        "required_videos": 1,
        "required_text_count": 4,
        "needs_analysis": False,
        "output_format": "mp4",
        "width": 1080,
        "height": 1920,
        "duration": 9,
    },
    VideoTemplate.SOCIAL_PROOF_STACK: {
        "creatomate_id": "REPLACE_WITH_REAL_ID",
        "required_videos": 2,
        "required_text_count": 5,
        "needs_analysis": False,
        "output_format": "mp4",
        "width": 1080,
        "height": 1920,
        "duration": 14,
    },
    VideoTemplate.OFFER_DROP: {
        "creatomate_id": "REPLACE_WITH_REAL_ID",
        "required_videos": 1,
        "required_text_count": 4,
        "needs_analysis": False,
        "output_format": "mp4",
        "width": 1080,
        "height": 1920,
        "duration": 10,
    },
    VideoTemplate.BULLET_REEL: {
        "creatomate_id": "RENDERSCRIPT",
        "required_videos": 2,       # minimum; builder uses all provided URLs
        "required_text_count": 2,   # hook + at least one bullet
        "needs_analysis": False,
        "output_format": "mp4",
        "width": 1080,
        "height": 1920,
    },
    VideoTemplate.TALKING_HEAD: {
        "creatomate_id": "RENDERSCRIPT",
        "required_videos": 1,
        "required_text_count": 1,   # text_1=Hook (optional); captions auto-generated from audio
        "needs_analysis": True,
        "output_format": "mp4",
        "width": 1080,
        "height": 1920,
    },
    VideoTemplate.TALKING_HEAD_V2: {
        "creatomate_id": "RENDERSCRIPT",
        "required_videos": 1,
        "required_text_count": 1,   # text_1=Title (optional); captions auto-generated from audio
        "needs_analysis": True,
        "output_format": "mp4",
        "width": 1080,
        "height": 1920,
    },
    VideoTemplate.HOOK_REVEAL: {
        "creatomate_id": "RENDERSCRIPT",
        "required_videos": 1,
        "required_text_count": 2,   # text_1=Hook, text_2=Reveal
        "needs_analysis": False,
        "output_format": "mp4",
        "width": 1080,
        "height": 1920,
    },
    VideoTemplate.EDU_STEPS: {
        "creatomate_id": "RENDERSCRIPT",
        "required_videos": 2,       # minimum; builder uses all provided URLs
        "required_text_count": 2,   # title + at least one step
        "needs_analysis": False,
        "output_format": "mp4",
        "width": 1080,
        "height": 1920,
    },
}


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class GenerateVideoRequest(BaseModel):
    """Payload from the wizard / frontend for P3 Real Video generation."""

    agent_type: Literal["reels-edited-by-ai"] = "reels-edited-by-ai"
    message_id: str = Field(default_factory=lambda: str(uuid4()))
    client_id: str = ""

    # Template selection  (wizard key, e.g. "myth-buster")
    template: str = Field(
        ...,
        description="Template key: myth-buster, bullet-sequence, viral-reaction, "
                    "testimonial-story, big-quote, deep-dive, brand-spotlight, social-proof-stack, offer-drop",
    )

    # Video URLs (uploaded to Supabase Storage by wizard)
    video_urls: list[str] = Field(
        default_factory=list,
        description="Public URLs of user-uploaded videos. Count varies by template.",
    )

    # Generic numbered text fields — wizard sends text_1..text_8
    text_1: Optional[str] = Field(None, max_length=300)
    text_2: Optional[str] = Field(None, max_length=300)
    text_3: Optional[str] = Field(None, max_length=300)
    text_4: Optional[str] = Field(None, max_length=300)
    text_5: Optional[str] = Field(None, max_length=300)
    text_6: Optional[str] = Field(None, max_length=300)
    text_7: Optional[str] = Field(None, max_length=300)
    text_8: Optional[str] = Field(None, max_length=300)

    # Clip configuration — set by the wizard's clip_config phase
    clip_count: Optional[int] = Field(None, ge=1, le=10, description="Number of clips selected by the user")
    target_duration: Optional[str] = Field(None, description="Target video duration: 15s | 30s | 60s | 90s")
    text_position: Optional[str] = Field("center", description="Text vertical position: top | center | bottom")

    # Caption (all templates)
    caption: Optional[str] = Field(None, max_length=2200)

    # Auto-subtitle pipeline — transcribe audio and add OpusClip-style captions
    enable_captions: bool = Field(
        False,
        description="Transcribe video audio and overlay OpusClip-style subtitles on all templates",
    )

    # Background music track ID from the curated library (optional)
    music_track: Optional[str] = Field(None, max_length=200)
    music_volume: Optional[float] = Field(40.0, ge=0, le=100)
    logo_url: Optional[str] = Field(None, description="Public URL of the business logo")
    brand_settings: Optional[dict] = Field(None, description="Dynamic brand settings (colors, fonts, etc.)")

    # Brand fields (enriched by frontend generate.ts or loaded from profile)
    caption_font: Optional[str] = Field(None, max_length=50, description="Creatomate font name for captions. Defaults to Anton.")
    caption_color: Optional[str] = Field(None, max_length=20, description="Hex color for caption text. Defaults to #FFFFFF.")
    caption_weight: Optional[str] = Field(None, max_length=10, description="Font weight for captions: 400, 700, 900. Defaults to 900.")
    caption_stroke: Optional[str] = Field(
        None,
        max_length=10,
        description="Caption stroke semantic token: 'thin' | 'medium' | 'thick'. "
                    "Server maps to vmin units via CAPTION_STROKE_MAP. Defaults to 'medium'.",
    )

    brand_name: Optional[str] = None
    brand_color_primary: Optional[str] = None
    brand_color_secondary: Optional[str] = None
    font_style: Optional[str] = None


class GenerateVideoResponse(BaseModel):
    """Matches existing frontend expectations."""

    reply: str
    caption: str
    media_urls: list[str]
    message_id: str
    reel_category: Optional[str] = None
    render_duration_ms: Optional[int] = None


class VideoStatusResponse(BaseModel):
    """Status check for recovery polling."""

    status: Literal["pending", "rendering", "completed", "failed"]
    message_id: str
    media_urls: Optional[list[str]] = None
    reply: Optional[str] = None
    caption: Optional[str] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Internal models
# ---------------------------------------------------------------------------

class VideoAnalysisResult(BaseModel):
    """Parsed Gemini video analysis output (T3/T4/Talking Head)."""

    # T3 Viral Reaction
    start_time_seconds: Optional[float] = None
    duration_seconds: Optional[float] = None
    generated_hook: Optional[str] = None

    # Shared
    analysis_summary: Optional[str] = None

    # Talking Head — auto-caption segments from speech transcription
    # Each item: {"text": "phrase", "start": 0.0, "end": 1.2}
    transcript_segments: Optional[list[dict]] = None

    # Word-level timestamps for karaoke captions (preferred over transcript_segments)
    # Each item: {"word": "Hello", "start": 0.3, "end": 0.6}
    word_timestamps: Optional[list[dict]] = None


class CreatomateRenderStatus(BaseModel):
    """Status from Creatomate polling."""

    id: str
    status: Literal["planned", "rendering", "succeeded", "failed"]
    url: Optional[str] = None
    error_message: Optional[str] = None
    render_time: Optional[float] = None
