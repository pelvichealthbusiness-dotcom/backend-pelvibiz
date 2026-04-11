from __future__ import annotations

from pydantic import BaseModel, Field


class CompetitorAccountCreate(BaseModel):
    handle: str = Field(min_length=2, max_length=100)
    display_name: str | None = None
    platform: str = 'instagram'
    active: bool = True


class CompetitorAccountResponse(BaseModel):
    id: str
    handle: str
    display_name: str | None = None
    platform: str
    active: bool


class CompetitorComparisonResponse(BaseModel):
    user_summary: dict
    competitor_summary: dict
    gaps: list[str]
    shared_topics: list[str]
    top_competitor_posts: list[dict] = Field(default_factory=list)
