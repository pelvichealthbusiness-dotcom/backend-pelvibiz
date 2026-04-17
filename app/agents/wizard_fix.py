"""WizardFixAgent — Fix a single carousel slide from wizard data.

Takes fix parameters (slide number, new text, slide type, etc.)
and regenerates a single slide, streaming progress via SSE events.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import uuid
from typing import Any, AsyncGenerator

from app.config import get_settings
from app.core.streaming import (
    finish_event,
    error_event,
    metadata_event,
    text_chunk,
)
from app.dependencies import get_supabase_admin
from app.prompts.ai_carousel_fix import build_ai_fix_generic_prompt, build_ai_fix_card_prompt
from app.prompts.ai_carousel_generate import build_generic_slide_prompt, build_card_slide_prompt
from app.services.brand import BrandService
from app.services.image_generator import ImageGeneratorService
from app.services.storage import StorageService
from app.services.watermark import WatermarkService
from app.utils.image import force_resolution
from app.models.ai_carousel import SlideType

logger = logging.getLogger(__name__)


class WizardFixAgent:
    """Handles single slide fix from wizard data.

    NOT a chat agent — takes fix parameters and runs the image
    regeneration pipeline directly, streaming progress via SSE.
    """

    def __init__(self, user_id: str, agent_type: str) -> None:
        self.user_id = user_id
        self.agent_type = agent_type

    async def stream(
        self,
        message: str,
        history: list[dict] | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        """Execute fix pipeline, yielding SSE events."""
        metadata = kwargs.get("metadata") or {}

        # Parse fix data from message JSON or metadata
        fix_data = self._parse_fix_data(message, metadata)

        row_id = fix_data.get("row_id") or fix_data.get("last_asset_id", "")
        slide_number = int(fix_data.get("slide_number", fix_data.get("Slide_Number", 1)))
        new_text = fix_data.get("new_text") or fix_data.get("New_Text_Content", "")
        slide_type_str = (fix_data.get("slide_type") or fix_data.get("New_Slide_Type", "generic")).lower()
        topic = fix_data.get("topic", "")
        face_photo_url = fix_data.get("face_photo_url", "")

        if not row_id:
            yield error_event("No row_id provided for fix", "VALIDATION_ERROR")
            return

        yield metadata_event({
            "type": "generation_progress",
            "phase": "plan",
            "message": f"Fixing slide {slide_number}...",
        })

        try:
            brand_service = BrandService()
            profile = await brand_service.load_profile(self.user_id)

            supabase = get_supabase_admin()
            result = (
                supabase.table("requests_log")
                .select("id, media_urls, user_id, title, metadata")
                .eq("id", row_id)
                .single()
                .execute()
            )

            if not result.data:
                yield error_event(f"Row {row_id} not found", "NOT_FOUND")
                return
            if result.data.get("user_id") != self.user_id:
                yield error_event("You don't own this carousel", "FORBIDDEN")
                return

            original_urls = result.data.get("media_urls", []) or []
            # Use topic from fix data, fall back to DB title
            if not topic:
                topic = result.data.get("title", "") or ""

            slide_idx = slide_number - 1
            if slide_idx < 0 or slide_idx >= len(original_urls):
                yield error_event(
                    f"Slide {slide_number} out of range (1-{len(original_urls)})",
                    "VALIDATION_ERROR",
                )
                return

            metadata = result.data.get("metadata") or {}
            texts = (metadata.get("texts") or []) if isinstance(metadata, dict) else []
            positions = (metadata.get("positions") or []) if isinstance(metadata, dict) else []
            slide_prompts = (metadata.get("prompts") or []) if isinstance(metadata, dict) else []

            carousel_context_lines: list[str] = []
            for i, text in enumerate(texts[:10], 1):
                pos = positions[i - 1] if i - 1 < len(positions) else ""
                suffix = f" · position: {pos}" if pos else ""
                carousel_context_lines.append(f"Slide {i}: {text}{suffix}")

            carousel_context = "\n".join(carousel_context_lines)
            original_prompt = ""
            if isinstance(slide_prompts, list) and slide_idx < len(slide_prompts):
                original_prompt = str(slide_prompts[slide_idx] or "")

            # Determine slide type
            try:
                slide_type = SlideType(slide_type_str)
            except ValueError:
                slide_type = SlideType.GENERIC

            yield text_chunk(f"Regenerating slide {slide_number}...\n")

            # Use original slide URL as visual reference when available (preserves style)
            original_photo_url = fix_data.get("photo_url", "")
            preserve_visual = bool(original_photo_url and slide_type != SlideType.FACE)

            # Build prompt based on slide type
            if slide_type == SlideType.CARD:
                prompt = build_ai_fix_card_prompt(
                    new_text=new_text or None,
                    font_prompt=profile.get("font_prompt", "Sans-serif"),
                    font_style=profile.get("font_style", "bold"),
                    color_primary=profile.get("brand_color_primary", "#000000"),
                    color_secondary=profile.get("brand_color_secondary", "#FFFFFF"),
                    topic=topic,
                    carousel_context=carousel_context,
                )
            else:
                prompt = build_ai_fix_generic_prompt(
                    original_prompt=original_prompt or topic,
                    new_text=new_text or None,
                    font_prompt=profile.get("font_prompt", "Sans-serif"),
                    font_style=profile.get("font_style", "bold"),
                    color_primary=profile.get("brand_color_primary", "#000000"),
                    color_secondary=profile.get("brand_color_secondary", "#FFFFFF"),
                    topic=topic,
                    carousel_context=carousel_context,
                    preserve_visual=preserve_visual,
                )

            image_gen = ImageGeneratorService()

            # Face mode: face photo as reference
            # Non-face with original slide URL: pass it as visual reference to preserve style
            if slide_type == SlideType.FACE and face_photo_url:
                face_base64 = await image_gen.download_image_as_base64(face_photo_url)
                generated_base64 = await image_gen.generate_slide(prompt, face_base64)
            elif preserve_visual:
                original_base64 = await image_gen.download_image_as_base64(original_photo_url)
                generated_base64 = await image_gen.generate_slide(prompt, original_base64)
            else:
                generated_base64 = await image_gen.generate_from_prompt(prompt)

            image_bytes = base64.b64decode(generated_base64)
            image_bytes = force_resolution(image_bytes)

            watermark_service = WatermarkService()
            image_bytes = await watermark_service.apply(
                image_bytes, profile.get("logo_url"), self.user_id,
            )

            storage = StorageService()
            upload_base64 = base64.b64encode(image_bytes).decode("utf-8")
            public_url = await storage.upload_image(upload_base64, self.user_id)

            # Update requests_log
            updated_urls = list(original_urls)
            updated_urls[slide_idx] = public_url

            try:
                supabase.table("requests_log").update(
                    {"media_urls": updated_urls}
                ).eq("id", row_id).execute()
            except Exception as e:
                logger.error("Failed to update requests_log: %s", e)

            yield metadata_event({
                "type": "generation_progress",
                "phase": "slide_complete",
                "slide_index": slide_idx,
                "slide_url": public_url,
                "total": 1,
            })

            yield metadata_event({
                "type": "generation_progress",
                "phase": "done",
                "media_urls": updated_urls,
                "fixed_slide": slide_number,
                "new_url": public_url,
            })

            yield text_chunk(f"Slide {slide_number} fixed successfully")
            yield finish_event("stop")

        except Exception as e:
            logger.error("Wizard fix failed: %s", e, exc_info=True)
            yield error_event(str(e), "GENERATION_FAILED")

    @staticmethod
    def _parse_fix_data(message: str, metadata: dict) -> dict:
        """Parse fix payload from message JSON or metadata."""
        if message and message.strip().startswith("{"):
            try:
                parsed = json.loads(message)
                return {**metadata, **parsed}
            except (json.JSONDecodeError, TypeError):
                pass
        return metadata
