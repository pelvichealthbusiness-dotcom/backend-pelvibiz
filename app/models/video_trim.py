from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, HttpUrl


class VideoTrimRequest(BaseModel):
    source_url: HttpUrl
    template_key: Optional[str] = None
    mode: Literal['template', 'manual'] = 'manual'
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)


class VideoTrimResponse(BaseModel):
    source_url: str
    trimmed_url: str
    template_key: Optional[str] = None
    mode: Literal['template', 'manual']
    start_seconds: float
    end_seconds: float
    duration_seconds: float
