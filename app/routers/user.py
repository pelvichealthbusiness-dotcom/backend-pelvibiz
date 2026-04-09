from fastapi import APIRouter, Depends

from app.services.auth import get_current_user
from app.services.brand import BrandService

router = APIRouter(prefix="/user", tags=["user"])


@router.get("/profile")
async def get_profile(user: dict = Depends(get_current_user)):
    """Get the current user's brand profile."""
    brand_service = BrandService()
    profile = await brand_service.load_profile(user["id"])
    return profile
