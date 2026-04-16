from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from app.core.auth import UserContext, get_current_user
from app.dependencies import get_supabase_admin
from app.models.social_intelligence import (
    SocialCompareRequest,
    SocialIdeationRequest,
    SocialResearchRequest,
    SocialScriptRequest,
)
from app.services.social_intelligence import SocialIntelligenceService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/social", tags=["social-intelligence"])


def _track_usage(user_id: str, feature: str) -> None:
    """Insert a usage row into requests_log for credit tracking. Fire-and-forget."""
    try:
        import uuid
        supabase = get_supabase_admin()
        supabase.table("requests_log").insert({
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "agent_type": feature,
            "message": "",
            "title": "",
            "reply": "",
            "caption": "",
            "media_urls": ["usage"],
            "published": False,
        }).execute()
    except Exception as e:
        logger.warning(f"Failed to track usage for {feature}: {e}")


@router.post("/research")
async def research(body: SocialResearchRequest, user: UserContext = Depends(get_current_user)):
    service = SocialIntelligenceService()
    result = await service.run_research(user_id=user.user_id, topic=body.topic, platforms=body.platforms, limit=body.limit, language=body.language)
    _track_usage(user.user_id, "content-studio")
    return result


@router.get("/research/latest")
async def latest_research(user: UserContext = Depends(get_current_user), limit: int = 10):
    service = SocialIntelligenceService()
    return {"items": await service.list_latest_research(user.user_id, limit=limit)}


@router.post("/ideas")
async def ideas(body: SocialIdeationRequest, user: UserContext = Depends(get_current_user)):
    service = SocialIntelligenceService()
    result = await service.generate_ideas(
        user_id=user.user_id,
        topic=body.topic,
        research_run_id=body.research_run_id,
        research_item_id=body.research_item_id,
        variations=body.variations,
    )
    _track_usage(user.user_id, "content-studio")
    return result


@router.get("/ideas/latest")
async def latest_ideas(user: UserContext = Depends(get_current_user), limit: int = 10):
    service = SocialIntelligenceService()
    return {"items": await service.list_latest_ideas(user.user_id, limit=limit)}


@router.post("/script")
async def script(body: SocialScriptRequest, user: UserContext = Depends(get_current_user)):
    service = SocialIntelligenceService()
    return await service.generate_script(
        user_id=user.user_id,
        topic=body.topic,
        research_run_id=body.research_run_id,
        idea_variation_id=body.idea_variation_id,
        selected_hook=body.selected_hook,
    )


@router.get("/scripts/latest")
async def latest_scripts(user: UserContext = Depends(get_current_user), limit: int = 10):
    service = SocialIntelligenceService()
    return {"items": await service.list_latest_scripts(user.user_id, limit=limit)}


@router.post("/compare")
async def compare(body: SocialCompareRequest, user: UserContext = Depends(get_current_user)):
    service = SocialIntelligenceService()
    return await service.compare_accounts(
        user_id=user.user_id,
        own_handle=body.own_handle,
        competitor_handles=body.competitor_handles,
        platform=body.platform,
        window_days=body.window_days,
        force_recompute=body.force_recompute,
    )
