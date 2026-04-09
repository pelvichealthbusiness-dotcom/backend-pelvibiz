from pydantic import BaseModel, Field
from typing import Optional, Literal
from enum import Enum


class InteractionType(str, Enum):
    IDEA_SELECTED = "idea_selected"
    IDEA_REJECTED = "idea_rejected"
    IDEA_EDITED = "idea_edited"
    CONTENT_PUBLISHED = "content_published"
    CONTENT_DELETED = "content_deleted"
    FIELD_REGENERATED = "field_regenerated"


class ReferenceType(str, Enum):
    IDEA = "idea"
    CAROUSEL = "carousel"
    VIDEO = "video"
    PROFILE_FIELD = "profile_field"


class TrackInteractionRequest(BaseModel):
    interaction_type: InteractionType
    reference_id: str
    reference_type: ReferenceType
    metadata: dict = Field(default_factory=dict)


class TrackInteractionResponse(BaseModel):
    id: str
    tracked: bool = True


class ContentTypePreference(BaseModel):
    content_type: str
    frequency: float = Field(ge=0.0, le=1.0)


class UserPatterns(BaseModel):
    preferred_content_types: list[ContentTypePreference] = Field(default_factory=list)
    rejected_themes: list[str] = Field(default_factory=list)
    preferred_hooks: list[str] = Field(default_factory=list)
    total_interactions: int = 0
    learning_summary: str = ""


class LearningPatternsResponse(BaseModel):
    patterns: UserPatterns
    has_enough_data: bool = False
