from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import UserContext, get_current_user
from app.core.responses import success
from app.models.competitors import CompareRequest, CompetitorAccountCreate
from app.services.competitors import CompetitorService


router = APIRouter(prefix='/competitors', tags=['competitors'])


@router.get('')
async def list_competitors(user: UserContext = Depends(get_current_user)):
    service = CompetitorService()
    return {'items': await service.list_competitors(user_id=user.user_id)}


@router.post('')
async def add_competitor(body: CompetitorAccountCreate, user: UserContext = Depends(get_current_user)):
    service = CompetitorService()
    return await service.add_competitor(
        user_id=user.user_id,
        handle=body.handle,
        display_name=body.display_name,
        platform=body.platform,
        active=body.active,
    )


# NOTE: /compare must be declared BEFORE /compare/{handle} to avoid routing conflicts.
@router.post('/compare')
async def compare_competitors(
    request: CompareRequest,
    user: UserContext = Depends(get_current_user),
):
    """Compare own account vs 1-2 competitors. Cached for 24h."""
    if len(request.competitor_handles) < 1 or len(request.competitor_handles) > 2:
        raise HTTPException(status_code=422, detail='competitor_handles must have 1 or 2 entries')

    service = CompetitorService()
    result = service.compare_accounts(
        user_id=user.user_id,
        own_handle=request.own_handle,
        competitor_handles=request.competitor_handles,
        window_days=request.window_days,
        force_recompute=request.force_recompute,
    )
    return success(result.model_dump())


@router.get('/compare/{handle}')
async def compare_competitor(handle: str, user: UserContext = Depends(get_current_user)):
    service = CompetitorService()
    return await service.compare_user_vs_competitor(user_id=user.user_id, handle=handle)
