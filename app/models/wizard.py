from pydantic import BaseModel, Field
from typing import Optional, Literal
from uuid import uuid4


class ContentIdea(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    title: str
    hook: str
    angle: str
    content_type: str
    engagement_score: float = Field(ge=0.0, le=1.0)
    slides_suggestion: int = Field(default=5, ge=1, le=10)


class WizardIdeasRequest(BaseModel):
    agent_type: Literal["real-carousel", "ai-carousel", "reels-edited-by-ai"]
    wizard_mode: Literal["ideas", "video-ideas"] = "ideas"
    message: str = Field(min_length=1, max_length=2000)
    exclude_ids: list[str] = Field(default_factory=list)
    video_template: Optional[str] = None
    count: int = Field(default=5, ge=1, le=10)


class ContextUsed(BaseModel):
    brand_profile: bool = True
    learning_patterns: bool = False
    anti_repetition_count: int = 0
    content_style_brief: bool = False


class WizardIdeasResponse(BaseModel):
    ideas: list[ContentIdea]
    reasoning: str
    message_id: str = Field(default_factory=lambda: str(uuid4()))
    context_used: ContextUsed = Field(default_factory=ContextUsed)


class WizardDraftRequest(BaseModel):
    agent_type: str
    wizard_mode: Literal["draft", "slides", "video-draft"]
    message: str = Field(min_length=1, max_length=2000)
    slide_count: int = Field(default=5, ge=1, le=10)
    template: Optional[str] = None
    template_key: Optional[str] = None  # alias for template (sent by older frontend)
    template_label: Optional[str] = None
    text_fields: Optional[list[dict]] = None

    @property
    def resolved_template(self) -> Optional[str]:
        return self.template or self.template_key
