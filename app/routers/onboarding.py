import logging
from fastapi import APIRouter, Depends
from app.services.auth import get_current_user
from app.services.profile_engine import ProfileEngine
from app.services.brand import BrandService
from app.models.brand import ProfileGenerationInput, RegenerateFieldRequest, SaveProfileRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


@router.post("/generate-profile")
async def generate_profile(
    request: ProfileGenerationInput,
    user: dict = Depends(get_current_user),
):
    """Generate a complete brand profile from minimal input. Does NOT save to DB."""
    engine = ProfileEngine()
    result = await engine.generate_profile(request.model_dump())
    return result


@router.post("/regenerate-field")
async def regenerate_field(
    request: RegenerateFieldRequest,
    user: dict = Depends(get_current_user),
):
    """Regenerate a single profile field with user instruction."""
    engine = ProfileEngine()
    result = await engine.regenerate_field(
        field_name=request.field_name,
        current_profile=request.current_profile,
        instruction=request.instruction,
    )
    return result


@router.post("/save-profile")
async def save_profile(
    request: SaveProfileRequest,
    user: dict = Depends(get_current_user),
):
    """Save confirmed profile to DB. Sets onboarding_completed=true."""
    brand_service = BrandService()
    profile_data = {k: v for k, v in request.model_dump().items() if v is not None}
    saved = await brand_service.save_profile(user["id"], profile_data)
    return {"saved": True, "profile": saved}
