from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


AccountType = Literal['personal', 'competitor']
AnalysisStatus = Literal['pending', 'processed', 'failed']


class ContentAccount(BaseModel):
    id: str
    user_id: str
    handle: str
    display_name: str | None = None
    platform: str = 'instagram'
    account_type: AccountType = 'personal'
    active: bool = True
    metadata: dict = Field(default_factory=dict)
    created_at: str
    updated_at: str


class ContentRecord(BaseModel):
    id: str
    user_id: str
    account_id: str
    source_post_id: str
    permalink: str | None = None
    caption: str | None = None
    posted_at: str | None = None
    media_type: str = 'reel'
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    saves: int = 0
    watch_time_seconds: int = 0
    reach: int = 0
    transcript: str | None = None
    spoken_hook: str | None = None
    hook_framework: str | None = None
    hook_structure: str | None = None
    text_hook: str | None = None
    visual_format: str | None = None
    audio_hook: str | None = None
    topic: str | None = None
    topic_summary: str | None = None
    content_structure: str | None = None
    content_type: str | None = None
    call_to_action: str | None = None
    analysis_status: AnalysisStatus = 'pending'
    analysis_error: str | None = None
    raw_data: dict = Field(default_factory=dict)
    scraped_at: str
    updated_at: str


class ContentSnapshot(BaseModel):
    id: str
    user_id: str
    account_id: str
    content_id: str
    snapshot_date: str
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    saves: int = 0
    watch_time_seconds: int = 0
    reach: int = 0
    analysis_status: AnalysisStatus = 'pending'
    raw_data: dict = Field(default_factory=dict)
    created_at: str
    updated_at: str


class AccountStats(BaseModel):
    account_id: str
    user_id: str
    handle: str
    display_name: str | None = None
    platform: str
    account_type: AccountType
    active: bool
    post_count: int
    total_views: int
    avg_views: float
    avg_engagement: float
    last_posted_at: str | None = None
    last_scraped_at: str | None = None


class ContentWithScores(ContentRecord):
    account_handle: str
    account_display_name: str | None = None
    account_avg_views: float
    outlier_score: float
    outlier_category: str
    engagement_rate: float
