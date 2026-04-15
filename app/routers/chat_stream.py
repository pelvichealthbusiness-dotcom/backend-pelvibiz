"""Unified streaming chat endpoint — POST /api/v1/chat/stream.

Implements CHAT-301: the single SSE entry point for all agent types.
Routes through the agent router, persists messages, and emits
Vercel AI SDK-compatible SSE events.

Updated: wizard_mode "generate" skips conversation/message persistence.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator

from app.agents.router import get_agent
from app.core.auth import UserContext, get_current_user
from app.core.exceptions import RateLimitError
from app.core.sse_middleware import sse_stream_with_heartbeat
from app.core.streaming import error_event, finish_event, metadata_event
from app.core.stream_tracker import stream_tracker
from app.services.conversation_service import ConversationService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat-stream"])


# ---------------------------------------------------------------------------
# Request model (CHAT-303)
# ---------------------------------------------------------------------------

class ChatStreamRequest(BaseModel):
    """Request body for the unified streaming chat endpoint."""

    agent_type: str = Field(
        ...,
        description="Agent type: general, real-carousel, ai-carousel, reels-edited-by-ai",
    )
    message: str = Field(..., min_length=1, max_length=10000)
    conversation_id: Optional[str] = None
    wizard_mode: Optional[str] = None  # ideas, draft, generate, fix
    metadata: Optional[dict] = None

    @field_validator("message")
    @classmethod
    def message_not_empty(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("message must not be empty")
        return stripped

    @field_validator("agent_type")
    @classmethod
    def validate_agent_type(cls, v: str) -> str:
        valid = {"real-carousel", "ai-carousel", "reels-edited-by-ai", "general", "pelvibiz-ai", "ai-post-generator"}
        if v not in valid:
            raise ValueError(f"Invalid agent_type: {v}. Must be one of: {', '.join(sorted(valid))}")
        return v

    @field_validator("wizard_mode")
    @classmethod
    def validate_wizard_mode(cls, v: Optional[str]) -> Optional[str]:
        valid = {"ideas", "draft", "generate", "fix", "generate_content", "brainstorm_post_ideas"}
        if v is not None and v not in valid:
            raise ValueError(f"Invalid wizard_mode: {v}. Must be one of: {', '.join(sorted(valid))}")
        return v


# ---------------------------------------------------------------------------
# Helper: extract text from SSE chunks (CHAT-304)
# ---------------------------------------------------------------------------

def extract_text_from_chunks(chunks: list[str]) -> str:
    """Extract plain text from Vercel AI SDK formatted SSE chunks.

    Parses lines with prefix 0: (text deltas), removes JSON encoding,
    and concatenates into the full response text.
    """
    text_parts: list[str] = []
    for chunk in chunks:
        if chunk.startswith("0:"):
            # Remove prefix and decode the JSON string so unicode survives intact.
            content = json.loads(chunk[2:].strip())
            if isinstance(content, str):
                text_parts.append(content)
    return "".join(text_parts)


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.post("/stream")
async def chat_stream(
    request: Request,
    body: ChatStreamRequest,
    user: UserContext = Depends(get_current_user),
):
    """Unified streaming chat endpoint. Returns SSE stream.

    Flow:
    1. Acquire stream slot (rate limiting)
    2. Get or create conversation (skipped for wizard_mode=generate)
    3. Save user message BEFORE LLM call (skipped for wizard_mode=generate)
    4. Load conversation history (skipped for wizard_mode=generate)
    5. Route to correct agent
    6. Stream response as Vercel AI SDK SSE events
    7. Save assistant message AFTER stream completes (skipped for wizard_mode=generate)
    8. Auto-generate title for new conversations (skipped for wizard_mode=generate)
    """
    # Wizard generate mode skips conversation persistence entirely.
    # "generate"/"fix" save to requests_log inside the agent.
    # "generate_content" is a one-shot LLM call for the post wizard — no conversation needed.
    is_wizard_generate = body.wizard_mode in ("generate", "fix", "generate_content", "brainstorm_post_ideas")

    # 1. Acquire stream slot
    await stream_tracker.acquire(user.user_id)

    conversation_id = None
    user_msg_id = None
    is_new_conversation = False
    history_dicts: list[dict] = []

    if not is_wizard_generate:
        # 2. Get or create conversation
        conv_service = ConversationService()
        conversation = await conv_service.get_or_create(
            user.user_id, body.agent_type, body.conversation_id,
        )
        conversation_id = conversation["id"]
        is_new_conversation = body.conversation_id is None

        # 3. Save user message BEFORE LLM call
        user_msg_id = await conv_service.save_user_message(
            user_id=user.user_id,
            conversation_id=conversation_id,
            agent_type=body.agent_type,
            content=body.message,
            metadata=body.metadata,
        )

        # 4. Load conversation history (exclude the just-saved user message)
        history = await conv_service.get_history(
            conversation_id, user.user_id, limit=20,
        )
        # Convert to Gemini-compatible Content objects
        if history and len(history) > 1:
            gemini_history = conv_service.history_to_gemini_contents(history[:-1])
        else:
            gemini_history = []

        # Convert Gemini Content objects to simple dicts for BaseStreamingAgent
        for content_obj in gemini_history:
            role = "assistant" if content_obj.role == "model" else "user"
            text_parts = [p.text for p in content_obj.parts if p.text]
            history_dicts.append({"role": role, "content": " ".join(text_parts)})

    logger.info(
        "Chat stream: user=%s agent=%s wizard=%s conv=%s",
        user.user_id, body.agent_type, body.wizard_mode, conversation_id,
    )

    # 5. Route to correct agent
    agent = get_agent(body.agent_type, body.wizard_mode, user.user_id)

    # 6. Create streaming generator
    async def generate():
        try:
            if not is_wizard_generate:
                # Send metadata first (conversation_id for frontend)
                yield metadata_event({"conversationId": conversation_id, "messageId": user_msg_id})

            collected_chunks: list[str] = []

            async for chunk in agent.stream(
                body.message,
                history=history_dicts if history_dicts else None,
                metadata=body.metadata,
            ):
                collected_chunks.append(chunk)
                yield chunk

            if not is_wizard_generate:
                # 7. Save assistant message AFTER stream completes
                full_response = extract_text_from_chunks(collected_chunks)
                if full_response:
                    await conv_service.save_assistant_message(
                        user_id=user.user_id,
                        conversation_id=conversation_id,
                        agent_type=body.agent_type,
                        content=full_response,
                    )

                # 8. Auto-title for new conversations
                if is_new_conversation and full_response:
                    asyncio.create_task(
                        conv_service.generate_title(
                            conversation_id, body.message, full_response,
                        )
                    )

                # Bump updated_at
                await conv_service.bump_updated_at(conversation_id)

        except Exception as exc:
            logger.error("Stream generation error: %s", exc, exc_info=True)
            yield error_event(str(exc), "INTERNAL_ERROR")
        finally:
            # Always release the stream slot
            await stream_tracker.release(user.user_id)

    # 7. Return SSE response with heartbeat
    return await sse_stream_with_heartbeat(request, generate())
