from pydantic import BaseModel, Field
from typing import Optional, Literal
from uuid import uuid4

class SlideInput(BaseModel):
    image_url: str
    text: Optional[str] = None
    text_position: Optional[str] = None
    number: Optional[int] = None

class GenerateCarouselRequest(BaseModel):
    agent_type: Literal["real-carousel"] = "real-carousel"
    message_id: str = Field(default_factory=lambda: str(uuid4()))
    client_id: str = ""
    action_type: Optional[Literal["create", "fix"]] = "create"
    message: str = ""
    slides: list[SlideInput] = Field(default_factory=list, max_length=10)
    # Optional brand overrides from frontend
    Brand_Name: Optional[str] = None
    Brand_Voice: Optional[str] = None
    Brand_Color_Primary: Optional[str] = None
    Brand_Color_Secondary: Optional[str] = None
    Font_Style: Optional[str] = None
    Font_Size: Optional[str] = None
    Font_Prompt: Optional[str] = None
    CTA: Optional[str] = None
    Keywords: Optional[str] = None
    Target_Audience: Optional[str] = None
    Services_Offered: Optional[str] = None
    Content_Style_Brief: Optional[str] = None
    Logo_URL: Optional[str] = None

class FixSlideRequest(BaseModel):
    fix_slide: Literal[True] = True
    action_type: Literal["fix_image"] = "fix_image"
    Slide_Number: int = Field(ge=1, le=10)
    New_Text_Content: Optional[str] = None
    New_Text_Position: Optional[str] = None
    New_Image_Link: Optional[str] = None
    Row_ID: str
    message_id: str = Field(default_factory=lambda: str(uuid4()))
