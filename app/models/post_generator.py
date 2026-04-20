"""Pydantic models for the POST /api/v1/post/generate endpoint."""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


class PostGenerateRequest(BaseModel):
    """Full payload sent by the frontend PostWizardStore when triggering image generation."""

    # Template identification
    template_key: str = Field(..., description="e.g. 'tip-card', 'myth-vs-fact'")
    template_label: str = Field(..., description="Human-readable label, e.g. 'Educational Tip'")

    # Content
    topic: str = Field(..., min_length=1, max_length=500)
    text_fields: dict[str, str] = Field(default_factory=dict)
    caption: str = Field(default="")

    # Tracking
    message_id: str = Field(..., description="UUID for idempotency / requests_log row ID")
    conversation_id: str = Field(default="")

    # Optional reference image uploaded by user (used as background for hero-title)
    reference_image_url: Optional[str] = None

    # Second reference image for masterclass-banner (person/face photo)
    person_image_url: Optional[str] = None

    # How the person image should be processed: 'upload' | 'face' | 'ai'
    person_image_mode: Optional[str] = None

    # Brand logo URL (Supabase Storage public URL)
    logo_url: Optional[str] = None

    # Brand identity (sent from client; backend re-fetches from profile but
    # uses these as fallback if the DB field is empty)
    brand_name: Optional[str] = None
    brand_color_primary: Optional[str] = None
    brand_color_secondary: Optional[str] = None
    brand_voice: Optional[str] = None
    target_audience: Optional[str] = None
    services_offered: Optional[str] = None
    keywords: Optional[str] = None
    font_style: Optional[str] = None
    font_prompt: Optional[str] = None
    font_size: Optional[str] = None
    visual_environment: Optional[str] = None
    visual_subject_face: Optional[str] = None
    visual_subject_generic: Optional[str] = None
    visual_identity: Optional[str] = None
    content_style_brief: Optional[str] = None
    cta: Optional[str] = None


class PostGenerateResponse(BaseModel):
    """Response envelope for a successful post generation."""

    image_url: str
    caption: str
    message_id: str
