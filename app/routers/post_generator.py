"""POST /api/v1/post/generate — single-image post generation endpoint.

Accepts the full assembled payload from the PostWizardStore after the user
reviews text fields and caption. Generates the image, uploads it, saves to
requests_log, and returns the public URL + final caption.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from app.core.auth import UserContext, get_current_user
from app.core.exceptions import AppError
from app.core.responses import success
from app.models.post_generator import PostGenerateRequest
from app.services.post_generator import PostGeneratorService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/post", tags=["post-generator"])


@router.post("/generate")
async def generate_post(
    request: PostGenerateRequest,
    user: UserContext = Depends(get_current_user),
):
    """Generate a branded post image from assembled text fields.

    Flow:
    1. Check credits.
    2. Load brand profile from DB (authoritative).
    3. Build Gemini image-generation prompt.
    4. Generate image, force 1080×1350, upload to storage.
    5. Save to requests_log.
    6. Increment credits.
    7. Return image_url + caption.
    """
    user_id = user.user_id

    logger.info(
        "Post generate: user=%s template=%s topic=%s",
        user_id,
        request.template_key,
        request.topic[:60],
    )

    try:
        service = PostGeneratorService()
        image_url, caption = await service.generate(request, user_id)
    except AppError:
        raise
    except Exception as exc:
        logger.error("Post generation failed for %s: %s", user_id, exc, exc_info=True)
        raise AppError(
            status_code=500,
            code="POST_GENERATION_FAILED",
            message="Post image generation failed. Please try again.",
        ) from exc

    return success({
        "image_url": image_url,
        "caption": caption,
        "message_id": request.message_id,
    })
