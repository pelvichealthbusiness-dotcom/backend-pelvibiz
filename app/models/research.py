from __future__ import annotations

from pydantic import BaseModel, Field


class ResearchRunRequest(BaseModel):
    niche: str = Field(min_length=2, max_length=200)
    limit: int = Field(default=10, ge=1, le=20)
    sources: list[str] = Field(default_factory=lambda: ['reddit', 'github', 'news'])
    competitor_handle: str | None = None


class ResearchTopicResponse(BaseModel):
    id: str
    source: str
    topic: str
    title: str
    summary: str | None = None
    tam_score: float
    demo_score: float
    hook_score: float
    total_score: float


class ResearchRunResponse(BaseModel):
    ready: bool
    reason: str | None = None
    run_id: str | None = None
    niche: str
    topics: list[ResearchTopicResponse] = Field(default_factory=list)
    brief_markdown: str = ''
    used_competitor_handle: str | None = None
