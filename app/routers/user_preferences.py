"""User preferences and learning endpoints — Batch 2c."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel, Field

from app.core.auth import get_current_user, UserContext
from app.core.responses import success, error_response
from app.services.user_preferences_service import UserPreferencesService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/user", tags=["user-preferences"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class UpdatePreferencesRequest(BaseModel):
    """Fields the client can update on user_preferences."""
    preferred_topics: list[str] | None = None
    preferred_slide_count: int | None = None
    preferred_position: str | None = None
    caption_edit_style: str | None = None


class TrackLearningEventRequest(BaseModel):
    """Fire-and-forget learning event."""
    event_type: str = Field(..., min_length=1, max_length=100)
    event_data: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/preferences")
async def get_preferences(user: UserContext = Depends(get_current_user)):
    """Get user preferences and learning brief."""
    service = UserPreferencesService()
    prefs = await service.get_preferences(user.user_id)
    if prefs is None:
        # Return empty defaults rather than 404
        return success(data={
            "user_id": user.user_id,
            "preferred_topics": [],
            "preferred_slide_count": None,
            "preferred_position": None,
            "draft_approval_rate": None,
            "avg_caption_edits": None,
            "caption_edit_style": None,
            "topic_history": [],
            "rejected_topics": [],
            "total_carousels": 0,
            "total_fixes": 0,
            "learning_brief": "",
        })
    return success(data=prefs)


@router.put("/preferences")
async def update_preferences(
    body: UpdatePreferencesRequest,
    user: UserContext = Depends(get_current_user),
):
    """Update user preferences (partial update)."""
    service = UserPreferencesService()
    # Only send non-None fields
    update_data = body.model_dump(exclude_none=True)
    if not update_data:
        return error_response("VALIDATION_ERROR", "No fields to update", status_code=400)

    result = await service.upsert_preferences(user.user_id, update_data)
    return success(data=result)


@router.post("/learning/track")
async def track_learning_event(
    body: TrackLearningEventRequest,
    background_tasks: BackgroundTasks,
    user: UserContext = Depends(get_current_user),
):
    """
    Track a learning event. Fire-and-forget — returns immediately
    while the INSERT happens in the background.
    """
    service = UserPreferencesService()

    async def _insert():
        try:
            await service.track_learning_event(
                user_id=user.user_id,
                event_type=body.event_type,
                event_data=body.event_data,
            )
        except Exception as exc:
            logger.error("Background learning event insert failed: %s", exc)

    background_tasks.add_task(_insert)
    return success(data={"tracked": True})


@router.get("/learning/patterns")
async def get_learning_patterns(user: UserContext = Depends(get_current_user)):
    """
    Get user learning patterns from learning events.
    This is a NEW endpoint that works with user_learning_events table
    (complementary to wizard/learning/patterns which uses user_interactions).
    """
    service = UserPreferencesService()
    events = await service.get_learning_events(user.user_id, limit=100)

    if len(events) < 3:
        return success(data={
            "patterns": {
                "event_types": {},
                "total_events": len(events),
                "learning_summary": "",
            },
            "has_enough_data": False,
        })

    # Aggregate event types
    event_types: dict[str, int] = {}
    for ev in events:
        et = ev.get("event_type", "unknown")
        event_types[et] = event_types.get(et, 0) + 1

    # Build summary
    sorted_types = sorted(event_types.items(), key=lambda x: -x[1])
    summary_parts = [f"{et}: {count} events" for et, count in sorted_types[:5]]

    return success(data={
        "patterns": {
            "event_types": event_types,
            "total_events": len(events),
            "learning_summary": "; ".join(summary_parts),
        },
        "has_enough_data": len(events) >= 3,
    })


@router.post("/learning/brief")
async def generate_learning_brief(user: UserContext = Depends(get_current_user)):
    """
    Generate a learning brief using Gemini.
    Analyzes user learning events and preferences, generates a brief,
    and saves it to user_preferences.
    """
    service = UserPreferencesService()
    result = await service.generate_learning_brief(user.user_id)
    return success(data=result)
