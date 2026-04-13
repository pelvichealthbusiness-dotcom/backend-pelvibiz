"""PostGeneratorService — orchestrates the two-step post image generation pipeline.

1. Builds a Gemini image prompt from template + text fields + brand context.
2. Calls ImageGeneratorService to generate the image.
3. Forces 1080x1350 resolution.
4. Uploads to Supabase Storage.
5. Saves to requests_log table.
6. Increments user credits.
"""

from __future__ import annotations

import base64
import logging

from app.dependencies import get_supabase_admin
from app.models.post_generator import PostGenerateRequest
from app.prompts.post_generate import build_post_image_prompt
from app.services.brand import BrandService
from app.services.credits import CreditsService
from app.services.image_generator import ImageGeneratorService
from app.services.storage import StorageService
from app.utils.image import force_resolution

logger = logging.getLogger(__name__)


class PostGeneratorService:
    """Handles the full post image generation flow."""

    def __init__(self) -> None:
        self._image_gen = ImageGeneratorService()
        self._storage = StorageService()
        self._brand_service = BrandService()
        self._credits = CreditsService()
        self._supabase = get_supabase_admin()

    async def generate(
        self,
        request: PostGenerateRequest,
        user_id: str,
    ) -> tuple[str, str]:
        """Run the full generation pipeline.

        Returns
        -------
        tuple[str, str]
            (image_url, caption)
        """
        # 1. Check credits before spending Gemini quota
        await self._credits.check_credits(user_id)

        # 2. Load brand profile from DB (authoritative source)
        profile = await self._brand_service.load_profile(user_id)

        # Merge: DB is authoritative, fall back to values sent by the client
        # for fields that might be empty in the DB.
        brand = _merge_brand(profile, request)

        # 3. Build the image generation prompt
        prompt = build_post_image_prompt(
            template_key=request.template_key,
            text_fields=request.text_fields,
            topic=request.topic,
            brand=brand,
        )

        # 4. Generate image with Gemini
        logger.info(
            "Generating post image: user=%s template=%s topic=%s",
            user_id,
            request.template_key,
            request.topic[:50],
        )
        generated_b64 = await self._image_gen.generate_from_prompt(prompt)

        # 5. Force 1080×1350 resolution (same as ai-carousel)
        image_bytes = base64.b64decode(generated_b64)
        image_bytes = force_resolution(image_bytes)
        upload_b64 = base64.b64encode(image_bytes).decode("utf-8")

        # 6. Upload to Supabase Storage
        image_url = await self._storage.upload_image(upload_b64, user_id)

        # 7. Save to requests_log
        self._save_to_requests_log(
            request=request,
            user_id=user_id,
            image_url=image_url,
            brand=brand,
        )

        # 8. Increment credits
        try:
            await self._credits.increment_credits(user_id)
        except Exception as exc:
            logger.error("Failed to increment credits for %s: %s", user_id, exc)

        return image_url, request.caption

    def _save_to_requests_log(
        self,
        request: PostGenerateRequest,
        user_id: str,
        image_url: str,
        brand: dict,
    ) -> None:
        """Upsert a row into requests_log using message_id as idempotency key."""
        try:
            self._supabase.table("requests_log").upsert(
                {
                    "id": request.message_id,
                    "user_id": user_id,
                    "agent_type": "ai-post-generator",
                    "title": f"{request.template_label} — {request.topic[:60]}",
                    "reply": f"Your {request.template_label} post is ready!",
                    "caption": request.caption,
                    "media_urls": [image_url],
                    "published": False,
                    "metadata": {
                        "template_key": request.template_key,
                        "template_label": request.template_label,
                        "topic": request.topic,
                        "text_fields": request.text_fields,
                        "conversation_id": request.conversation_id,
                        "brand_snapshot": {
                            "brand_color_primary": brand.get("brand_color_primary"),
                            "brand_color_secondary": brand.get("brand_color_secondary"),
                            "font_style": brand.get("font_style"),
                            "font_prompt": brand.get("font_prompt"),
                        },
                    },
                },
                on_conflict="id",
            ).execute()
        except Exception as exc:
            logger.error("Failed to save post to requests_log: %s", exc)


# ---------------------------------------------------------------------------
# Brand merge helper
# ---------------------------------------------------------------------------

def _merge_brand(profile: dict, req: PostGenerateRequest) -> dict:
    """Return merged brand dict: DB profile takes precedence, request fills gaps."""

    def _pick(db_key: str, req_val) -> object:
        db_val = profile.get(db_key)
        if db_val and isinstance(db_val, str) and db_val.strip():
            return db_val
        if req_val and isinstance(req_val, str) and req_val.strip():
            return req_val
        return db_val  # might be None

    return {
        "brand_name": _pick("brand_name", req.brand_name),
        "brand_color_primary": _pick("brand_color_primary", req.brand_color_primary),
        "brand_color_secondary": _pick("brand_color_secondary", req.brand_color_secondary),
        "brand_voice": _pick("brand_voice", req.brand_voice),
        "target_audience": _pick("target_audience", req.target_audience),
        "services_offered": _pick("services_offered", req.services_offered),
        "keywords": _pick("keywords", req.keywords),
        "font_style": _pick("font_style", req.font_style),
        "font_prompt": _pick("font_prompt", req.font_prompt),
        "font_size": _pick("font_size", req.font_size),
        "visual_environment_setup": _pick("visual_environment_setup", req.visual_environment),
        "visual_subject_outfit_face": _pick("visual_subject_outfit_face", req.visual_subject_face),
        "visual_subject_outfit_generic": _pick("visual_subject_outfit_generic", req.visual_subject_generic),
        "visual_identity": _pick("visual_identity", req.visual_identity),
        "content_style_brief": _pick("content_style_brief", req.content_style_brief),
        "cta": _pick("cta", req.cta),
    }
