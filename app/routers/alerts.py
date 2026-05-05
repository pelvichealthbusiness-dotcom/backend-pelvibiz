"""Failure alert endpoints — surfaces publishing failures to the user."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.auth import UserContext, get_current_user
from app.core.responses import success
from app.services.content_crud import ContentCRUD

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("")
async def get_alerts(user: UserContext = Depends(get_current_user)):
    """Return unacknowledged publishing failures for the current user."""
    crud = ContentCRUD()
    items = crud.get_unacked_failures(user_id=user.user_id)
    return success(items)


@router.post("/{content_id}/ack")
async def ack_alert(content_id: str, user: UserContext = Depends(get_current_user)):
    """Acknowledge a failure alert — removes it from GET /alerts."""
    crud = ContentCRUD()
    crud.ack_failure(content_id=content_id, user_id=user.user_id)
    return success({"acknowledged": True})
