from pydantic import BaseModel, Field
from typing import Optional


class LoginRequest(BaseModel):
    email: str = Field(pattern=r"^[^@]+@[^@]+\.[^@]+$")
    password: str = Field(min_length=8)


class RegisterRequest(BaseModel):
    email: str = Field(pattern=r"^[^@]+@[^@]+\.[^@]+$")
    password: str = Field(min_length=12)
    display_name: str = Field(min_length=1, max_length=100)


class RefreshRequest(BaseModel):
    refresh_token: str


class ResetPasswordRequest(BaseModel):
    email: str = Field(pattern=r"^[^@]+@[^@]+\.[^@]+$")


class LogoutRequest(BaseModel):
    access_token: Optional[str] = None  # Optional — if not provided, uses current session


class UserProfile(BaseModel):
    id: str
    email: str
    display_name: Optional[str] = None
    brand_name: Optional[str] = None
    brand_color_secondary: Optional[str] = None
    brand_name: Optional[str] = None
    role: str = "client"
    onboarding_completed: bool = False
    credits_used: int = 0
    credits_limit: int = 40
    timezone: Optional[str] = None
    logo_url: Optional[str] = None


class FullUserProfile(BaseModel):
    """Extended profile with brand settings — returned by GET /auth/profile."""
    id: str
    email: str
    display_name: Optional[str] = None
    brand_name: Optional[str] = None
    brand_color_secondary: Optional[str] = None
    brand_name: Optional[str] = None
    role: str = "client"
    onboarding_completed: bool = False
    credits_used: int = 0
    credits_limit: int = 40
    timezone: Optional[str] = None
    logo_url: Optional[str] = None
    # Brand settings
    brand_voice: Optional[str] = None
    brand_color_primary: Optional[str] = None
    brand_color_accent: Optional[str] = None  # maps to brand_color_secondary in DB
    brand_color_background: Optional[str] = None
    font_style: Optional[str] = None
    font_size: Optional[str] = None
    font_prompt: Optional[str] = None
    business_name: Optional[str] = None  # alias for brand_name
    services_offered: Optional[str] = None
    target_audience: Optional[str] = None
    visual_identity: Optional[str] = None
    keywords: Optional[str] = None
    cta: Optional[str] = None
    content_style_brief: Optional[str] = None
    brand_playbook: Optional[str] = None
    brand_stories: Optional[str] = None
    visual_environment_setup: Optional[str] = None
    visual_subject_outfit_face: Optional[str] = None
    visual_subject_outfit_generic: Optional[str] = None
    font_style_secondary: Optional[str] = None
    font_prompt_secondary: Optional[str] = None
    logo_url: Optional[str] = None


class ProfileUpdateRequest(BaseModel):
    """Partial update for user profile fields."""
    display_name: Optional[str] = None
    brand_name: Optional[str] = None
    brand_color_secondary: Optional[str] = None
    brand_name: Optional[str] = None
    timezone: Optional[str] = None
    brand_voice: Optional[str] = None
    brand_color_primary: Optional[str] = None
    brand_color_accent: Optional[str] = None
    brand_color_background: Optional[str] = None
    font_style: Optional[str] = None
    font_size: Optional[str] = None
    font_prompt: Optional[str] = None
    services_offered: Optional[str] = None
    target_audience: Optional[str] = None
    visual_identity: Optional[str] = None
    keywords: Optional[str] = None
    cta: Optional[str] = None
    content_style_brief: Optional[str] = None
    brand_stories: Optional[str] = None
    visual_environment_setup: Optional[str] = None
    visual_subject_outfit_face: Optional[str] = None
    visual_subject_outfit_generic: Optional[str] = None
    font_style_secondary: Optional[str] = None
    font_prompt_secondary: Optional[str] = None
    logo_url: Optional[str] = None


class AuthResponse(BaseModel):
    access_token: str
    refresh_token: str
    user: UserProfile
    expires_at: int
