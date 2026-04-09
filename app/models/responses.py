from pydantic import BaseModel
from typing import Optional

class GenerateCarouselResponse(BaseModel):
    reply: str
    caption: str
    media_urls: list[str]
    message_id: str
    is_fix: bool = False

class ErrorDetail(BaseModel):
    field: Optional[str] = None
    message: str

class ErrorResponse(BaseModel):
    error: str
    message: str
    details: Optional[list[ErrorDetail]] = None
    request_id: Optional[str] = None

class HealthResponse(BaseModel):
    status: str
    version: str
    uptime_seconds: float
