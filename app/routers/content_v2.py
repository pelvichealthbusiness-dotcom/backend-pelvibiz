"""Content REST API v2 — Batch 2b.

New content endpoints using core infrastructure (auth, responses, pagination, exceptions).
Operates on the requests_log table. Coexists with legacy content.py router.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.core.auth import UserContext, get_current_user
from app.core.pagination import PaginationParams, pagination_params
from app.core.responses import success, paginated
from app.core.exceptions import ValidationError
from app.services.content_crud import ContentCRUD
import asyncio
import os
import httpx

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/content", tags=["content-v2"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class CreateContentRequest(BaseModel):
    agent_type: str = Field(..., description="Agent type that generated this content")
    title: Optional[str] = Field(None, max_length=500)
    caption: Optional[str] = Field(None, max_length=5000)
    reply: Optional[str] = Field(None, description="Full AI reply text")
    media_urls: Optional[list[str]] = Field(None, description="Generated media URLs")
    reel_category: Optional[str] = Field(None, max_length=100)


class UpdateContentV2Request(BaseModel):
    title: Optional[str] = Field(None, max_length=500)
    caption: Optional[str] = Field(None, max_length=5000)
    published: Optional[bool] = Field(None, description="Publish status")
    scheduled_date: Optional[str] = Field(None, description="ISO datetime for scheduling")


class ScheduleContentRequest(BaseModel):
    scheduled_date: str = Field(..., description="ISO datetime string for scheduling")
    timezone: str = Field("UTC", description="User's timezone")
    caption: Optional[str] = Field(None, max_length=5000)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/calendar")
async def content_calendar(
    date_from: Optional[str] = Query(None, description="Start date (ISO) — alias: start_date"),
    date_to: Optional[str] = Query(None, description="End date (ISO) — alias: end_date"),
    start_date: Optional[str] = Query(None, description="Start date (ISO) — alias for date_from"),
    end_date: Optional[str] = Query(None, description="End date (ISO) — alias for date_to"),
    agent_type: Optional[str] = Query(None, description="Filter by agent type"),
    user: UserContext = Depends(get_current_user),
):
    """Calendar view: flat list of scheduled content ordered by scheduled_date."""
    crud = ContentCRUD()
    data = crud.get_calendar(
        user_id=user.user_id,
        date_from=date_from,
        date_to=date_to,
        start_date=start_date,
        end_date=end_date,
        agent_type=agent_type,
    )
    return success(data)


@router.get("/usage")
async def content_usage(
    user: UserContext = Depends(get_current_user),
):
    """User usage stats: credits used, total generated, by agent type."""
    crud = ContentCRUD()
    data = crud.get_usage(user_id=user.user_id)
    return success(data)


@router.get("/grid")
async def list_content_grid(
    agent_type: Optional[str] = Query(None, description="Filter by agent type"),
    status: Optional[str] = Query(None, pattern="^(draft|published|scheduled)$", description="Filter by status"),
    date_from: Optional[str] = Query(None, description="Start date (ISO)"),
    date_to: Optional[str] = Query(None, description="End date (ISO)"),
    pag: PaginationParams = Depends(pagination_params),
    user: UserContext = Depends(get_current_user),
):
    """Paginated content grid with filters (agent_type, status, date range)."""
    crud = ContentCRUD()
    items, total = crud.list_content(
        user_id=user.user_id,
        agent_type=agent_type,
        status=status,
        date_from=date_from,
        date_to=date_to,
        limit=pag.limit,
        offset=pag.offset,
        sort_by=pag.sort_by,
        order=pag.order,
    )
    return paginated(items, total, pag.page, pag.limit)


@router.get("/detail/{content_id}")
async def get_content_detail(
    content_id: str,
    user: UserContext = Depends(get_current_user),
):
    """Get single content item by ID."""
    crud = ContentCRUD()
    item = crud.get_content(content_id, user.user_id)
    return success(item)


@router.post("/new", status_code=201)
async def create_content(
    body: CreateContentRequest,
    user: UserContext = Depends(get_current_user),
):
    """Save new content/asset from generation results."""
    crud = ContentCRUD()
    item = crud.create_content(
        user_id=user.user_id,
        agent_type=body.agent_type,
        title=body.title,
        caption=body.caption,
        reply=body.reply,
        media_urls=body.media_urls,
        reel_category=body.reel_category,
    )
    return success(item)


@router.patch("/detail/{content_id}")
async def update_content_detail(
    content_id: str,
    body: UpdateContentV2Request,
    user: UserContext = Depends(get_current_user),
):
    """Update content: publish status, schedule date, caption, title."""
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise ValidationError("No fields provided for update")
    crud = ContentCRUD()
    item = crud.update_content(content_id, user.user_id, updates)
    return success(item)


@router.delete("/detail/{content_id}")
async def delete_content_detail(
    content_id: str,
    user: UserContext = Depends(get_current_user),
):
    """Delete content item and associated storage files."""
    crud = ContentCRUD()
    crud.delete_content(content_id, user.user_id)
    return success({"deleted": True})

@router.post("/{content_id}/schedule")
async def schedule_content(
    content_id: str,
    body: ScheduleContentRequest,
    user: UserContext = Depends(get_current_user),
):
    """Schedule content for publishing via n8n → Blotato pipeline.
    
    Calls the n8n blotato-native-publisher webhook, then updates
    the content record with published=True, scheduled_date, and caption.
    """
    crud = ContentCRUD()
    # Verify ownership
    content = crud.get_content(content_id, user.user_id)

    # Build n8n payload (same format as Vercel Edge Function)
    n8n_payload = {
        "client_id": user.user_id,
        "asset_id": content_id,
        "scheduled_date": body.scheduled_date,
        "timezone": body.timezone,
        "caption": body.caption or content.get("reply", ""),
        "action": "schedule_post",
    }

    # Call n8n webhook with retry
    n8n_url = os.environ.get("N8N_PUBLISHER_WEBHOOK_URL", "")
    if not n8n_url:
        logger.warning("N8N_PUBLISHER_WEBHOOK_URL not set — skipping n8n call")
    else:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=35.0) as client:
                    resp = await client.post(n8n_url, json=n8n_payload)
                    resp.raise_for_status()
                    break
            except httpx.HTTPStatusError as exc:
                logger.error("n8n webhook HTTP error (attempt %d): %s", attempt + 1, exc)
                last_error = exc
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
            except Exception as exc:
                logger.error("n8n webhook error (attempt %d): %s", attempt + 1, exc)
                last_error = exc
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
        else:
            raise ValidationError(f"Failed to reach publisher: {last_error}")

    # Update content record
    updates = {
        "published": True,
        "scheduled_date": body.scheduled_date,
    }
    if body.caption is not None:
        updates["caption"] = body.caption
        updates["reply"] = body.caption

    updated = crud.update_content(content_id, user.user_id, updates)
    return success(updated)
