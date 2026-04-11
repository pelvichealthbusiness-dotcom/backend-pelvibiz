from __future__ import annotations

from fastapi import APIRouter, Depends

from app.services.auth import get_current_user
from app.models.competitors import CompetitorAccountCreate
from app.services.competitors import CompetitorService


router = APIRouter(prefix='/competitors', tags=['competitors'])


@router.get('')
async def list_competitors(user: dict = Depends(get_current_user)):
    service = CompetitorService()
    return {'items': await service.list_competitors(user_id=user['id'])}


@router.post('')
async def add_competitor(body: CompetitorAccountCreate, user: dict = Depends(get_current_user)):
    service = CompetitorService()
    return await service.add_competitor(
        user_id=user['id'],
        handle=body.handle,
        display_name=body.display_name,
        platform=body.platform,
        active=body.active,
    )


@router.get('/compare/{handle}')
async def compare_competitor(handle: str, user: dict = Depends(get_current_user)):
    service = CompetitorService()
    return await service.compare_user_vs_competitor(user_id=user['id'], handle=handle)
