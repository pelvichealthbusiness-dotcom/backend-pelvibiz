from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class BrandProfile(BaseModel):
    id: str
    brand_name: str | None = None
    brand_voice: str | None = None
    services_offered: str | None = None
    target_audience: str | None = None
    visual_identity: str | None = None
    keywords: str | None = None
    brand_color_primary: str = "#000000"
    brand_color_secondary: str = "#FFFFFF"
    visual_environment_setup: str | None = None
    visual_subject_outfit_face: str | None = None
    visual_subject_outfit_generic: str | None = None
    cta: str | None = None
    font_style: str = "bold"
    font_size: str = "38px"
    font_prompt: str = "Clean, bold, geometric sans-serif"
    content_style_brief: str | None = None
    logo_url: str | None = None
    credits_used: int = 0
    credits_limit: int = 40
    role: str = "client"
    onboarding_completed: bool = False


VALID_CONTENT_GOALS = {"educate", "sell", "build_trust", "entertain", "drive_traffic", "community"}
REGENERABLE_FIELDS = {
    "brand_voice", "target_audience", "services_offered", "visual_identity",
    "keywords", "cta", "content_style_brief", "visual_environment_setup",
    "visual_subject_outfit_face", "visual_subject_outfit_generic", "font_style", "font_prompt",
}


class ProfileGenerationInput(BaseModel):
    brand_name: str = Field(min_length=1, max_length=200)
    services_description: str = Field(min_length=10, max_length=2000)
    personal_preferences: str = Field(default="", max_length=2000)
    brand_color_primary: str = Field(default="#000000")
    brand_color_secondary: str = Field(default="#FFFFFF")
    niche: str = Field(default="", max_length=200)
    content_goals: list[str] = Field(default_factory=list)


class GeneratedField(BaseModel):
    value: str
    confidence: float = Field(ge=0.0, le=1.0)


class GenerateProfileResponse(BaseModel):
    brand_voice: GeneratedField
    target_audience: GeneratedField
    services_offered: GeneratedField
    visual_identity: GeneratedField
    keywords: GeneratedField
    cta: GeneratedField
    content_style_brief: GeneratedField
    brand_playbook: GeneratedField
    visual_environment_setup: GeneratedField
    visual_subject_outfit_face: GeneratedField
    visual_subject_outfit_generic: GeneratedField
    font_style: GeneratedField
    font_prompt: GeneratedField
    message_id: str = Field(default_factory=lambda: str(uuid4()))


class RegenerateFieldRequest(BaseModel):
    field_name: str
    instruction: str = Field(min_length=1, max_length=1000)
    current_profile: dict = Field(default_factory=dict)


class RegenerateFieldResponse(BaseModel):
    field_name: str
    old_value: str
    new_value: str
    reasoning: str


class SaveProfileRequest(BaseModel):
    brand_voice: Optional[str] = None
    target_audience: Optional[str] = None
    services_offered: Optional[str] = None
    visual_identity: Optional[str] = None
    keywords: Optional[str] = None
    cta: Optional[str] = None
    content_style_brief: Optional[str] = None
    visual_environment_setup: Optional[str] = None
    visual_subject_outfit_face: Optional[str] = None
    visual_subject_outfit_generic: Optional[str] = None
    font_style: Optional[str] = None
    font_prompt: Optional[str] = None
    brand_name: Optional[str] = None
    brand_color_primary: Optional[str] = None
    brand_color_secondary: Optional[str] = None
    niche: Optional[str] = None
    logo_url: Optional[str] = None
    timezone: Optional[str] = None
