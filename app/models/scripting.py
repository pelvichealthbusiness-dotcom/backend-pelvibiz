from __future__ import annotations

from pydantic import BaseModel, Field


class HookPackRequest(BaseModel):
    topic: str | None = None
    research_topic_id: str | None = None
    idea_variation_id: str | None = None
    count: int = Field(default=6, ge=1, le=6)
    competitor_handle: str | None = None


class ScriptRequest(BaseModel):
    topic: str | None = None
    research_topic_id: str | None = None
    idea_variation_id: str | None = None
    selected_hook: str | None = None
    competitor_handle: str | None = None


class HookPackResponse(BaseModel):
    id: str
    source_topic: str
    hook_text: str
    hook_framework: str
    hook_type: str
    content_type: str
    score: float
    why_it_works: str | None = None


class ScriptResponse(BaseModel):
    id: str
    source_topic: str
    selected_hook: str
    hook_framework: str
    hook_type: str
    content_type: str
    hook: str
    script_body: str
    filming_card: str
    caption: str
    cta: str
    recording_instructions: str
