"""Conversations & Messages REST API — Batch 2a.

CRUD endpoints for conversations and their messages.
All endpoints require authentication and enforce user ownership.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.core.auth import UserContext, get_current_user
from app.core.pagination import PaginationParams, pagination_params
from app.core.responses import success, paginated
from app.services.conversations_crud import ConversationsCRUD

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/conversations", tags=["conversations"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class CreateConversationRequest(BaseModel):
    agent_type: str = Field(..., description="Agent type: real-carousel, ai-carousel, reels-edited-by-ai, etc.")
    title: Optional[str] = Field(None, max_length=200, description="Optional conversation title")


class UpdateConversationRequest(BaseModel):
    title: Optional[str] = Field(None, max_length=200, description="New title")


class CreateMessageRequest(BaseModel):
    role: str = Field(..., pattern="^(user|assistant|system)$", description="Message role")
    content: str = Field(..., min_length=1, description="Message content")
    media_urls: Optional[list[str]] = Field(None, description="Attached media URLs")
    metadata: Optional[dict] = Field(None, description="Extra metadata (tool_calls, etc.)")


class ConversationOut(BaseModel):
    id: str
    user_id: str
    agent_type: str
    title: Optional[str] = None
    created_at: str
    updated_at: str


class MessageOut(BaseModel):
    id: str
    conversation_id: str
    user_id: str
    agent_type: Optional[str] = None
    role: str
    content: Optional[str] = None
    media_urls: Optional[list[str]] = None
    metadata: Optional[dict] = None
    created_at: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("")
async def list_conversations(
    agent_type: Optional[str] = Query(None, description="Filter by agent type"),
    pag: PaginationParams = Depends(pagination_params),
    user: UserContext = Depends(get_current_user),
):
    """List user conversations with pagination and optional agent_type filter."""
    crud = ConversationsCRUD()
    items, total = crud.list_conversations(
        user_id=user.user_id,
        agent_type=agent_type,
        limit=pag.limit,
        offset=pag.offset,
        sort_by=pag.sort_by,
        order=pag.order,
    )
    return paginated(items, total, pag.page, pag.limit)


@router.post("", status_code=201)
async def create_conversation(
    body: CreateConversationRequest,
    user: UserContext = Depends(get_current_user),
):
    """Create a new conversation."""
    crud = ConversationsCRUD()
    conv = crud.create_conversation(
        user_id=user.user_id,
        agent_type=body.agent_type,
        title=body.title,
    )
    return success(conv)


@router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    user: UserContext = Depends(get_current_user),
):
    """Get a single conversation by ID."""
    crud = ConversationsCRUD()
    conv = crud.get_conversation(conversation_id, user.user_id)
    return success(conv)


@router.patch("/{conversation_id}")
async def update_conversation(
    conversation_id: str,
    body: UpdateConversationRequest,
    user: UserContext = Depends(get_current_user),
):
    """Update conversation title."""
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        from app.core.exceptions import ValidationError
        raise ValidationError("No fields provided for update")
    crud = ConversationsCRUD()
    conv = crud.update_conversation(conversation_id, user.user_id, updates)
    return success(conv)


@router.delete("/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    user: UserContext = Depends(get_current_user),
):
    """Delete a conversation and all its messages."""
    crud = ConversationsCRUD()
    crud.delete_conversation(conversation_id, user.user_id)
    return success({"deleted": True})


# ---------------------------------------------------------------------------
# Messages sub-resource
# ---------------------------------------------------------------------------

@router.get("/{conversation_id}/messages")
async def list_messages(
    conversation_id: str,
    pag: PaginationParams = Depends(pagination_params),
    user: UserContext = Depends(get_current_user),
):
    """List messages for a conversation (newest first, paginated)."""
    crud = ConversationsCRUD()
    items, total = crud.list_messages(
        conversation_id=conversation_id,
        user_id=user.user_id,
        limit=pag.limit,
        offset=pag.offset,
    )
    return paginated(items, total, pag.page, pag.limit)


@router.post("/{conversation_id}/messages", status_code=201)
async def create_message(
    conversation_id: str,
    body: CreateMessageRequest,
    user: UserContext = Depends(get_current_user),
):
    """Save a message to a conversation."""
    crud = ConversationsCRUD()
    msg = crud.create_message(
        conversation_id=conversation_id,
        user_id=user.user_id,
        role=body.role,
        content=body.content,
        media_urls=body.media_urls,
        metadata=body.metadata,
    )
    return success(msg)
