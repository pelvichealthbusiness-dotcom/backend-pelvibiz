"""Brand stories CRUD endpoints."""
from __future__ import annotations
import logging
from typing import Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from app.core.auth import UserContext, get_current_user
from app.core.responses import success
from app.core.exceptions import NotFoundError, DatabaseError
from app.core.supabase_client import get_service_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/brand", tags=["brand-stories"])


class CreateStoryRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    content: str = Field(..., min_length=1, max_length=5000)


@router.get("/stories")
async def list_stories(user: UserContext = Depends(get_current_user)):
    """List all stories for the current user."""
    client = get_service_client()
    try:
        result = (
            client.table("brand_stories")
            .select("id, title, content, created_at")
            .eq("user_id", user.user_id)
            .order("created_at", desc=False)
            .execute()
        )
        return success(result.data or [])
    except Exception as exc:
        logger.error("Failed to list stories: %s", exc)
        raise DatabaseError(f"Failed to list stories: {exc}")


@router.post("/stories", status_code=201)
async def create_story(
    body: CreateStoryRequest,
    user: UserContext = Depends(get_current_user),
):
    """Create a new brand story."""
    client = get_service_client()
    try:
        result = (
            client.table("brand_stories")
            .insert({"user_id": user.user_id, "title": body.title, "content": body.content})
            .execute()
        )
        return success(result.data[0])
    except Exception as exc:
        logger.error("Failed to create story: %s", exc)
        raise DatabaseError(f"Failed to create story: {exc}")


@router.delete("/stories/{story_id}")
async def delete_story(story_id: str, user: UserContext = Depends(get_current_user)):
    """Delete a story (ownership verified)."""
    client = get_service_client()
    existing = (
        client.table("brand_stories")
        .select("id")
        .eq("id", story_id)
        .eq("user_id", user.user_id)
        .maybe_single()
        .execute()
    )
    if not existing.data:
        raise NotFoundError("Story")
    try:
        client.table("brand_stories").delete().eq("id", story_id).eq("user_id", user.user_id).execute()
        return success({"deleted": True})
    except Exception as exc:
        raise DatabaseError(f"Failed to delete story: {exc}")
