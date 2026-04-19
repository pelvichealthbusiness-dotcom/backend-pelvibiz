from pydantic import BaseModel, Field
from typing import Optional, Literal
from enum import Enum
from uuid import uuid4


class SlideType(str, Enum):
    GENERIC = "generic"
    CARD = "card"
    FACE = "face"  # Treated as generic until KIE.ai is integrated
    CUSTOM_PHOTO = "custom_photo"  # User-uploaded photo — bypasses image generation


class AiSlideInput(BaseModel):
    number: int = Field(ge=1, le=10)
    slide_type: SlideType = SlideType.GENERIC
    text: Optional[str] = None
    text_position: Optional[str] = None


class GenerateAiCarouselRequest(BaseModel):
    agent_type: Literal["ai-carousel"] = "ai-carousel"
    message_id: str = Field(default_factory=lambda: str(uuid4()))
    client_id: str = ""
    message: str = Field(min_length=1, max_length=2000)
    slides: list[AiSlideInput] = Field(default_factory=list, max_length=10)
    slide_count: int = Field(default=5, ge=1, le=10)


class AiSlideContent(BaseModel):
    number: int
    slide_type: SlideType
    text: str
    text_position: str = "Bottom Center"
    visual_prompt: str = ""


class AiContentPlan(BaseModel):
    slides: list[AiSlideContent]
    reply: str
    caption: str
    reasoning: str = ""


class GenerationMetadata(BaseModel):
    slide_types: list[str] = Field(default_factory=list)
    prompts: list[str] = Field(default_factory=list)
    texts: list[str] = Field(default_factory=list)
    positions: list[str] = Field(default_factory=list)
    brand_snapshot: dict = Field(default_factory=dict)


class AiCarouselGenerateResponse(BaseModel):
    reply: str
    caption: str
    media_urls: list[str]
    message_id: str
    is_fix: bool = False
    slide_types: list[str] = Field(default_factory=list)
    failed_slides: list[int] = Field(default_factory=list)
    partial: bool = False


class AiCarouselFixRequest(BaseModel):
    fix_slide: Literal[True] = True
    action_type: Literal["fix_image"] = "fix_image"
    Slide_Number: int = Field(ge=1, le=10)
    slide_type: Optional[SlideType] = None
    New_Text_Content: Optional[str] = None
    Row_ID: str
    message_id: str = Field(default_factory=lambda: str(uuid4()))
