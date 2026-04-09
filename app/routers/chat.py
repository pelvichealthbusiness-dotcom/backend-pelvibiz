import logging

from fastapi import APIRouter, Depends

from app.models.chat import ChatCompletionsRequest
from app.services.auth import get_current_user
from app.services.chat_agent import ChatAgent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/completions")
async def chat_completions(
    request: ChatCompletionsRequest,
    user: dict = Depends(get_current_user),
):
    agent = ChatAgent()
    result = await agent.chat(
        user_id=user["id"],
        message=request.message,
        conversation_id=request.conversation_id,
    )
    return result
