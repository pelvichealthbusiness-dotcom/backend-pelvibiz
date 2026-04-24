"""Caption recommendation endpoint."""

from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import Optional

router = APIRouter(prefix="/video", tags=["video-captions"])


class CaptionRecommendationRequest(BaseModel):
    brand_profile_id: Optional[str] = Field(None)
    template_id: str = Field(..., min_length=1)


class CaptionRecommendationResponse(BaseModel):
    font: str
    color: str
    weight: str
    stroke: str


_SAFE_DEFAULTS = CaptionRecommendationResponse(
    font="Anton", color="#FFE600", weight="900", stroke="medium"
)

_VOICE_TO_FONT_WEIGHT: dict[str, tuple[str, str]] = {
    "bold": ("Anton", "900"),
    "energetic": ("Anton", "900"),
    "calm": ("Montserrat", "700"),
    "professional": ("Montserrat", "700"),
}


def _build_recommendation(profile: Optional[dict]) -> CaptionRecommendationResponse:
    """Pure function: maps a brand profile dict to caption recommendations.

    Accepts None or empty dict — always returns safe defaults in that case.
    Uses brand_voice for font/weight mapping and brand_color_primary for color.
    """
    if not profile:
        return _SAFE_DEFAULTS

    voice = (profile.get("brand_voice") or "").lower().strip()
    font, weight = _VOICE_TO_FONT_WEIGHT.get(voice, (_SAFE_DEFAULTS.font, _SAFE_DEFAULTS.weight))

    color = profile.get("brand_color_primary") or _SAFE_DEFAULTS.color

    bg_hint = (profile.get("background_hint") or "").lower().strip()
    stroke = "thick" if bg_hint == "dark" else _SAFE_DEFAULTS.stroke

    return CaptionRecommendationResponse(font=font, color=color, weight=weight, stroke=stroke)


@router.post("/caption-recommendation", response_model=CaptionRecommendationResponse)
async def caption_recommendation(payload: CaptionRecommendationRequest) -> CaptionRecommendationResponse:
    if not payload.brand_profile_id:
        return _SAFE_DEFAULTS

    try:
        from app.services.brand import BrandService
        service = BrandService()
        profile = await service.load_profile(payload.brand_profile_id)
    except Exception:
        return _SAFE_DEFAULTS

    return _build_recommendation(profile)
