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


# ---------------------------------------------------------------------------
# Competitor intelligence models (Phase 2)
# ---------------------------------------------------------------------------

class BenchmarkMetrics(BaseModel):
    avg_likes: float
    median_likes: float
    avg_comments: float
    avg_views: float
    engagement_rate: float | None  # null when avg_views = 0
    posts_per_week: float


class HookGap(BaseModel):
    hook_structure: str
    competitor_frequency: int
    own_frequency: int
    avg_views: float = 0.0
    avg_likes: float = 0.0
    avg_engagement_rate: float | None = None
    performance_score: float | None = None


class TopicGap(BaseModel):
    topic: str
    competitor_frequency: int
    own_frequency: int


class ContentTypeGap(BaseModel):
    content_type: str
    competitor_frequency: int
    own_frequency: int


class WhiteSpaceEntry(BaseModel):
    topic: str
    signal_source: str  # "trending" | "inferred"
    demand_score: float | None = None
    recommendation: str = ""
    summary: str | None = None


class CompetitorResult(BaseModel):
    handle: str
    followers_count: int
    benchmarks: BenchmarkMetrics | None
    hook_gaps: list[HookGap]
    topic_gaps: list[TopicGap]
    content_type_gaps: list[ContentTypeGap]
    white_space: list[WhiteSpaceEntry]
    cadence_delta_per_week: float | None
    style_diff: dict | None
    cached: bool
    computed_at: str | None
    status: str  # "ok" | "insufficient_data"


class CompareRequest(BaseModel):
    own_handle: str
    competitor_handles: list[str]  # 1-2 entries
    window_days: int = 30
    force_recompute: bool = False


class CompareResponse(BaseModel):
    own: dict
    competitors: list[CompetitorResult]
    status: str
