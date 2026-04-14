from __future__ import annotations

from fastapi import APIRouter, Depends

from app.services.auth import get_current_user
from app.models.scripting import HookPackRequest, ScriptRequest
from app.services.scripting import ScriptingService


router = APIRouter(prefix='/scripting', tags=['scripting'])


@router.post('/hooks')
async def generate_hooks(body: HookPackRequest, user: dict = Depends(get_current_user)):
    service = ScriptingService()
    return await service.generate_hook_pack(
        user_id=user['id'],
        topic=body.topic,
        research_topic_id=body.research_topic_id,
        idea_variation_id=body.idea_variation_id,
        count=body.count,
        competitor_handle=body.competitor_handle,
    )


@router.post('/script')
async def generate_script(body: ScriptRequest, user: dict = Depends(get_current_user)):
    service = ScriptingService()
    return await service.generate_script(
        user_id=user['id'],
        topic=body.topic,
        research_topic_id=body.research_topic_id,
        idea_variation_id=body.idea_variation_id,
        selected_hook=body.selected_hook,
        competitor_handle=body.competitor_handle,
    )


@router.get('/hooks/latest')
async def latest_hooks(user: dict = Depends(get_current_user), limit: int = 20):
    service = ScriptingService()
    return {'items': await service.list_latest_hooks(user_id=user['id'], limit=limit)}


@router.get('/scripts/latest')
async def latest_scripts(user: dict = Depends(get_current_user), limit: int = 20):
    service = ScriptingService()
    return {'items': await service.list_latest_scripts(user_id=user['id'], limit=limit)}
