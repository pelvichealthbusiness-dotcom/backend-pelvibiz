from __future__ import annotations

from pydantic import BaseModel, SecretStr


class ConnectRequest(BaseModel):
    username: str
    password: SecretStr


class ConnectResponse(BaseModel):
    connected: bool
    handle: str
    followers: int
    post_count: int
    avg_engagement_rate: float
    top_topics: list[str]
    scraped_at: str


class InstagramStatus(BaseModel):
    connected: bool
    handle: str | None
    post_count: int
    last_sync_at: str | None
    can_sync_at: str | None  # last_sync_at + ig_min_resync_minutes


class SyncResponse(BaseModel):
    handle: str
    post_count: int
    new_posts: int
    scraped_at: str
    account_type: str  # "own" | "competitor"
