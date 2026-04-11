from __future__ import annotations

from fastapi import APIRouter, Depends

from app.services.auth import get_current_user
from app.models.ideation import IdeationRequest
from app.services.ideation import IdeationService


router = APIRouter(prefix='/ideation', tags=['ideation'])


@router.post('/from-research')
async def ideate_from_research(body: IdeationRequest, user: dict = Depends(get_current_user)):
    service = IdeationService()
    return await service.generate_from_research(
        user_id=user['id'],
        niche=body.niche,
        research_topic_id=body.research_topic_id,
        research_run_id=body.research_run_id,
        topic_limit=body.topic_limit,
        variations_per_topic=body.variations_per_topic,
    )


@router.get('/latest')
async def latest_ideas(user: dict = Depends(get_current_user), limit: int = 20):
    service = IdeationService()
    return {'items': await service.list_latest_variations(user_id=user['id'], limit=limit)}
