"""Pydantic models for the Instagram Style Analyzer feature."""

from __future__ import annotations

from pydantic import BaseModel, Field


# ── Request models ────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    username: str = Field(..., min_length=2, description="Instagram username (without @)")
    max_posts: int = Field(default=30, ge=1, le=50, description="Max posts to scrape")
    generate_voice_summary: bool = Field(default=True, description="Generate AI voice summary")


class ApplyStyleRequest(BaseModel):
    scrape_id: str = Field(..., description="ID of the content account or analysis source to apply")


# ── Original 8 sub-models ────────────────────────────────────────

class CaptionStats(BaseModel):
    caption_avg_length: float = 0
    caption_avg_sentences: float = 0
    caption_length_distribution: dict[str, float] = Field(default_factory=dict)


class HookStats(BaseModel):
    hook_types: dict[str, float] = Field(default_factory=dict)
    hook_first_person_rate: float = 0
    hook_second_person_rate: float = 0


class HashtagStats(BaseModel):
    hashtag_avg_count: float = 0
    hashtag_top_20: list[str] = Field(default_factory=list)
    hashtag_niche_vs_broad: dict[str, float] = Field(default_factory=dict)


class EngagementStats(BaseModel):
    avg_likes: float = 0
    avg_comments: float = 0
    engagement_rate: float = 0
    top_performing_posts: list[dict] = Field(default_factory=list)


class PostingPatterns(BaseModel):
    posts_per_week: float = 0
    best_days: list[str] = Field(default_factory=list)
    best_hours: list[int] = Field(default_factory=list)


class EmojiStats(BaseModel):
    emoji_frequency: float = 0
    top_emojis: list[str] = Field(default_factory=list)
    emoji_position: dict[str, float] = Field(default_factory=dict)


class CTAStats(BaseModel):
    cta_rate: float = 0
    cta_types: dict[str, float] = Field(default_factory=dict)


class ContentThemes(BaseModel):
    top_keywords: list[dict] = Field(default_factory=list)
    content_categories: dict[str, float] = Field(default_factory=dict)


# ── New cross-analysis sub-models ────────────────────────────────

class ProfileStats(BaseModel):
    profile_followers: int = 0
    profile_following: int = 0
    profile_followers_following_ratio: float = 0
    profile_total_posts: int = 0
    profile_is_verified: bool = False
    profile_biography: str = ""
    profile_avg_days_between_posts: float | None = None


class ContentTypePerformance(BaseModel):
    content_type_performance: dict[str, dict] = Field(default_factory=dict)
    best_content_type: str | None = None


class EngagementDepth(BaseModel):
    comments_to_likes_ratio: float = 0
    conversation_score: str = "low"
    viral_outliers: list[dict] = Field(default_factory=list)


class CaptionOptimization(BaseModel):
    caption_length_vs_engagement: dict[str, dict] = Field(default_factory=dict)
    optimal_caption_length: str | None = None


class HashtagPerformance(BaseModel):
    hashtag_count_vs_engagement: dict[str, dict] = Field(default_factory=dict)
    optimal_hashtag_count: str | None = None


class ConsistencyScore(BaseModel):
    consistency_score: int = 0
    avg_days_between_posts: float | None = None
    max_gap_days: int | None = None
    current_streak_days: int | None = None
    posting_regularity: str = "insufficient_data"


class TopPostsAnalysis(BaseModel):
    top_posts: list[dict] = Field(default_factory=list)
    top_posts_patterns: dict = Field(default_factory=dict)


# ── Composite metrics ────────────────────────────────────────────

class StyleMetrics(BaseModel):
    """Combines all 15 analysis modules into a single object."""

    # ── Original 8 modules ──────────────────────────────────────

    # Caption analysis
    caption_avg_length: float = 0
    caption_avg_sentences: float = 0
    caption_length_distribution: dict[str, float] = Field(default_factory=dict)

    # Hook analysis
    hook_types: dict[str, float] = Field(default_factory=dict)
    hook_first_person_rate: float = 0
    hook_second_person_rate: float = 0

    # Hashtag analysis
    hashtag_avg_count: float = 0
    hashtag_top_20: list[str] = Field(default_factory=list)
    hashtag_niche_vs_broad: dict[str, float] = Field(default_factory=dict)

    # Engagement analysis
    avg_likes: float = 0
    avg_comments: float = 0
    engagement_rate: float = 0
    top_performing_posts: list[dict] = Field(default_factory=list)

    # Posting patterns
    posts_per_week: float = 0
    best_days: list[str] = Field(default_factory=list)
    best_hours: list[int] = Field(default_factory=list)

    # Emoji analysis
    emoji_frequency: float = 0
    top_emojis: list[str] = Field(default_factory=list)
    emoji_position: dict[str, float] = Field(default_factory=dict)

    # CTA analysis
    cta_rate: float = 0
    cta_types: dict[str, float] = Field(default_factory=dict)

    # Content themes
    top_keywords: list[dict] = Field(default_factory=list)
    content_categories: dict[str, float] = Field(default_factory=dict)

    # ── New cross-analysis modules ───────────────────────────────

    # Profile stats
    profile_followers: int = 0
    profile_following: int = 0
    profile_followers_following_ratio: float = 0
    profile_total_posts: int = 0
    profile_is_verified: bool = False
    profile_biography: str = ""
    profile_avg_days_between_posts: float | None = None

    # Content type performance
    content_type_performance: dict[str, dict] = Field(default_factory=dict)
    best_content_type: str | None = None

    # Engagement depth
    comments_to_likes_ratio: float = 0
    conversation_score: str = "low"
    viral_outliers: list[dict] = Field(default_factory=list)

    # Caption length optimization
    caption_length_vs_engagement: dict[str, dict] = Field(default_factory=dict)
    optimal_caption_length: str | None = None

    # Hashtag count performance
    hashtag_count_vs_engagement: dict[str, dict] = Field(default_factory=dict)
    optimal_hashtag_count: str | None = None

    # Consistency score
    consistency_score: int = 0
    avg_days_between_posts: float | None = None
    max_gap_days: int | None = None
    current_streak_days: int | None = None
    posting_regularity: str = "insufficient_data"

    # Top posts
    top_posts: list[dict] = Field(default_factory=list)
    top_posts_patterns: dict = Field(default_factory=dict)


# ── Response models ───────────────────────────────────────────────

class AnalyzeResponse(BaseModel):
    scrape_id: str
    username: str
    post_count: int
    followers: int
    metrics: StyleMetrics
    voice_summary: str | None = None
    ai_recommendations: list[str] = Field(default_factory=list)
    analyzed_at: str | None = None


class ApplyStyleResponse(BaseModel):
    applied: bool
    content_style_brief: str
    source_username: str = ""
