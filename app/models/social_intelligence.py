from __future__ import annotations

from typing import Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


SocialPlatform = Literal["instagram", "facebook", "tiktok", "google"]


class SocialResearchRequest(BaseModel):
    topic: str = Field(min_length=2, max_length=200)
    platforms: list[SocialPlatform] = Field(default_factory=lambda: ["instagram", "facebook", "tiktok", "google"])
    limit: int = Field(default=12, ge=1, le=30)
    language: str = Field(default="en", min_length=2, max_length=8)


class SocialResearchItem(BaseModel):
    id: str
    platform: SocialPlatform
    source_kind: str
    title: str
    url: Optional[str] = None
    author: Optional[str] = None
    summary: Optional[str] = None
    published_at: Optional[str] = None
    viral_score: float = 0
    engagement: dict = Field(default_factory=dict)
    raw_data: dict = Field(default_factory=dict)
    created_at: str


class SocialResearchResponse(BaseModel):
    ready: bool
    run_id: Optional[str] = None
    topic: str
    platforms: list[SocialPlatform] = Field(default_factory=list)
    items: list[SocialResearchItem] = Field(default_factory=list)
    brief_markdown: str = ""
    summary: dict = Field(default_factory=dict)


class SocialIdeationRequest(BaseModel):
    topic: Optional[str] = None
    research_run_id: Optional[str] = None
    research_item_id: Optional[str] = None
    variations: int = Field(default=6, ge=1, le=6)


class SocialIdeaVariation(BaseModel):
    id: str
    source_topic: str
    title: str
    hook: str
    angle: str
    content_type: str
    slides_suggestion: int
    score: float
    why_it_works: Optional[str] = None
    best_hooks: list[str] = Field(default_factory=list)
    raw_data: dict = Field(default_factory=dict)
    created_at: str


class SocialIdeationResponse(BaseModel):
    ready: bool
    run_id: Optional[str] = None
    source_topic: str
    variations: list[SocialIdeaVariation] = Field(default_factory=list)
    brief_markdown: str = ""
    summary: dict = Field(default_factory=dict)


class SocialScriptRequest(BaseModel):
    topic: Optional[str] = None
    research_run_id: Optional[str] = None
    idea_variation_id: Optional[str] = None
    selected_hook: Optional[str] = None


class SocialScriptResponse(BaseModel):
    ready: bool
    run_id: Optional[str] = None
    source_topic: str
    selected_hook: str
    hook_pack: list[str] = Field(default_factory=list)
    script_body: str
    filming_card: str
    caption: str
    cta: str
    recording_instructions: str
    raw_data: dict = Field(default_factory=dict)


class SocialCompareRequest(BaseModel):
    own_handle: str
    competitor_handles: list[str] = Field(min_length=1, max_length=2)
    platform: SocialPlatform = "instagram"
    window_days: int = Field(default=30, ge=1, le=365)
    force_recompute: bool = False
