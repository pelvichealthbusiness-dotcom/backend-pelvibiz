import logging
from fastapi import APIRouter, Depends
from app.services.auth import get_current_user
from app.services.ideas_engine import IdeasEngine
from app.services.draft_engine import DraftEngine
from app.services.learning import LearningService
from app.models.wizard import WizardIdeasRequest, WizardDraftRequest
from app.models.learning import TrackInteractionRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/wizard", tags=["wizard"])


@router.post("/ideas")
async def generate_ideas(
    request: WizardIdeasRequest,
    user: dict = Depends(get_current_user),
):
    """Generate content ideas with full context awareness."""
    engine = IdeasEngine()
    result = await engine.generate_ideas(
        user_id=user["id"],
        message=request.message,
        agent_type=request.agent_type,
        wizard_mode=request.wizard_mode,
        exclude_ids=request.exclude_ids,
        video_template=request.video_template,
        count=request.count,
    )
    return result


@router.post("/draft")
async def generate_draft(
    request: WizardDraftRequest,
    user: dict = Depends(get_current_user),
):
    """Generate carousel slide text + caption, or video text fields + caption."""
    print(f"DEBUG /wizard/draft received slide_count={request.slide_count} wizard_mode={request.wizard_mode}", flush=True)
    engine = DraftEngine()

    if request.wizard_mode == "video-draft" and request.resolved_template:
        result = await engine.generate_video_draft(
            user_id=user["id"],
            topic=request.message,
            template_key=request.resolved_template,
            template_label=request.template_label or request.resolved_template,
            text_fields=request.text_fields or [],
        )
    else:
        result = await engine.generate_draft(
            user_id=user["id"],
            topic=request.message,
            slide_count=request.slide_count,
            agent_type=request.agent_type,
        )

    return result


@router.post("/learning/track")
async def track_interaction(
    request: TrackInteractionRequest,
    user: dict = Depends(get_current_user),
):
    """Record a user interaction for learning."""
    service = LearningService()
    interaction_id = await service.track(
        user_id=user["id"],
        interaction_type=request.interaction_type.value,
        reference_id=request.reference_id,
        reference_type=request.reference_type.value,
        metadata=request.metadata,
    )
    return {"id": interaction_id, "tracked": True}


@router.get("/learning/patterns")
async def get_patterns(
    user: dict = Depends(get_current_user),
):
    """Get extracted learning patterns for the current user."""
    service = LearningService()
    patterns = await service.get_patterns(user["id"])

    if not patterns:
        return {
            "patterns": {
                "preferred_content_types": [],
                "rejected_themes": [],
                "preferred_hooks": [],
                "total_interactions": 0,
                "learning_summary": "",
            },
            "has_enough_data": False,
        }

    return {
        "patterns": patterns,
        "has_enough_data": patterns.get("has_enough_data", False),
    }
