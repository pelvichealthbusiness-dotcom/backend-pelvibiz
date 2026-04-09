from pydantic import BaseModel, Field
from typing import Optional
from uuid import uuid4


class ChatCompletionsRequest(BaseModel):
    message: str = Field(min_length=1, max_length=5000)
    conversation_id: Optional[str] = None
    agent_type: str = "pelvibiz-ai"


class ToolCallResult(BaseModel):
    tool_name: str
    result: dict = Field(default_factory=dict)
    success: bool = True
    error: Optional[str] = None


class ChatCompletionsResponse(BaseModel):
    message: str
    conversation_id: str
    message_id: str = Field(default_factory=lambda: str(uuid4()))
    tool_calls: list[ToolCallResult] = Field(default_factory=list)
    media_urls: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
