from __future__ import annotations

from fastapi import APIRouter, Depends

from app.services.auth import get_current_user
from app.models.research import ResearchRunRequest
from app.services.research import ResearchService


router = APIRouter(prefix='/research', tags=['research'])


@router.post('/daily')
async def run_daily_research(body: ResearchRunRequest, user: dict = Depends(get_current_user)):
    service = ResearchService()
    return await service.run_research(user_id=user['id'], niche=body.niche, sources=body.sources, limit=body.limit)


@router.get('/latest')
async def latest_research(user: dict = Depends(get_current_user), limit: int = 20):
    service = ResearchService()
    return {'items': await service.list_latest_topics(user_id=user['id'], limit=limit)}
