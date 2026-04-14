from __future__ import annotations

from pydantic import BaseModel, Field


class IdeationRequest(BaseModel):
    niche: str = Field(min_length=2, max_length=200)
    research_topic_id: str | None = None
    research_run_id: str | None = None
    variations_per_topic: int = Field(default=5, ge=1, le=5)
    topic_limit: int = Field(default=3, ge=1, le=10)
    competitor_handle: str | None = None


class IdeaVariationResponse(BaseModel):
    id: str
    source_topic: str
    title: str
    hook: str
    angle: str
    content_type: str
    slides_suggestion: int
    score: float
    why_it_works: str | None = None


class IdeationResponse(BaseModel):
    ready: bool
    reason: str | None = None
    run_id: str | None = None
    niche: str
    variations: list[IdeaVariationResponse] = Field(default_factory=list)
    brief_markdown: str = ''
    used_competitor_handle: str | None = None
