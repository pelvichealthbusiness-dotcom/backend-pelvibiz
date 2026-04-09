import logging
from fastapi import APIRouter, Depends, Query
from app.services.auth import get_current_user
from app.services.content_service import ContentService
from app.models.content_models import (
    UpdateContentRequest,
    PublishRequest, ScheduleRequest,
)
from app.core.responses import paginated

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/content", tags=["content"])


@router.get("/list")
async def list_content(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    agent_type: str | None = Query(default=None),
    published: bool | None = Query(default=None),
    user: dict = Depends(get_current_user),
):
    """List user's content with pagination and filters."""
    service = ContentService()
    result = await service.list_content(user["id"], page, limit, agent_type, published)
    return paginated(result["items"], result["total"], page, limit)


@router.get("/{content_id}")
async def get_content(
    content_id: str,
    user: dict = Depends(get_current_user),
):
    """Get a single content item."""
    service = ContentService()
    try:
        data = await service.get_content(user["id"], content_id)
        return {"data": data, "error": None, "meta": None}
    except Exception:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=404, content={"data": None, "error": {"code": "NOT_FOUND", "message": "Content not found"}, "meta": None})


@router.patch("/{content_id}")
async def update_content(
    content_id: str,
    request: UpdateContentRequest,
    user: dict = Depends(get_current_user),
):
    """Update title and/or caption."""
    service = ContentService()
    return await service.update_content(user["id"], content_id, request.title, request.caption)


@router.delete("/{content_id}")
async def delete_content(
    content_id: str,
    user: dict = Depends(get_current_user),
):
    """Delete content and associated storage files."""
    service = ContentService()
    await service.delete_content(user["id"], content_id)
    return {"data": {"deleted": True}, "error": None, "meta": None}


@router.post("/{content_id}/publish")
async def publish_content(
    content_id: str,
    request: PublishRequest | None = None,
    user: dict = Depends(get_current_user),
):
    """Mark content as published."""
    service = ContentService()
    caption = request.caption if request else None
    return await service.publish_content(user["id"], content_id, caption)


@router.post("/{content_id}/schedule")
async def schedule_content(
    content_id: str,
    request: ScheduleRequest,
    user: dict = Depends(get_current_user),
):
    """Schedule content for future publication."""
    service = ContentService()
    return await service.schedule_content(user["id"], content_id, request.scheduled_date, request.caption)


@router.post("/{content_id}/unpublish")
async def unpublish_content(
    content_id: str,
    user: dict = Depends(get_current_user),
):
    """Unmark content as published."""
    service = ContentService()
    return await service.unpublish_content(user["id"], content_id)
