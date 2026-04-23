from pydantic import BaseModel, Field
from typing import Optional


class ContentItem(BaseModel):
    id: str
    agent_type: str
    title: Optional[str] = None
    caption: Optional[str] = None
    reply: Optional[str] = None
    media_urls: list[str] = Field(default_factory=list)
    published: bool = False
    scheduled_date: Optional[str] = None
    reel_category: Optional[str] = None
    created_at: str


class ContentListResponse(BaseModel):
    items: list[ContentItem]
    total: int
    page: int
    limit: int
    has_more: bool


class UpdateContentRequest(BaseModel):
    title: Optional[str] = Field(default=None, max_length=500)
    caption: Optional[str] = Field(default=None)


class PublishRequest(BaseModel):
    caption: Optional[str] = None


class ScheduleRequest(BaseModel):
    scheduled_date: str  # ISO datetime
    caption: Optional[str] = None
    timezone: Optional[str] = None  # client timezone hint (used for display only)
