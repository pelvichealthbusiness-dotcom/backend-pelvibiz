"""PostGeneratorService — orchestrates the two-step post image generation pipeline.

1. Builds a Gemini image prompt from template + text fields + brand context.
2. Calls ImageGeneratorService to generate the image.
3. Forces 1080x1350 resolution.
4. Uploads to Supabase Storage.
5. Saves to requests_log table.
6. Increments user credits.
"""

from __future__ import annotations

import asyncio
import base64
import logging

import httpx

from app.dependencies import get_supabase_admin
from app.models.post_generator import PostGenerateRequest
from app.prompts.post_generate import build_post_image_prompt
from app.services.brand import BrandService
from app.services.content_service import ContentService
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

        # Hero-title: Pillow-composited pipeline (background + overlay + text)
        if request.template_key == "hero-title":
            return await self._generate_hero_title(request, user_id, brand)

        # Masterclass-banner: Pillow-composited pipeline (background + person + logo)
        if request.template_key == "masterclass-banner":
            return await self._generate_masterclass_banner(request, user_id, brand)

        # Wellness-workshop: 3-image collage + tips + person + dual logo
        if request.template_key == "wellness-workshop":
            return await self._generate_wellness_workshop(request, user_id, brand)

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
        )
        ContentService._invalidate_cache(user_id)

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
                },
                on_conflict="id",
            ).execute()
        except Exception as exc:
            logger.error("Failed to save post to requests_log: %s", exc)


# ---------------------------------------------------------------------------
# Brand merge helper
# ---------------------------------------------------------------------------

    async def _generate_hero_title(
        self,
        request: PostGenerateRequest,
        user_id: str,
        brand: dict,
    ) -> tuple[str, str]:
        """Hero-title pipeline: background (Gemini or upload) + Pillow compositing."""
        from app.utils.hero_title_composer import compose as compose_hero_title

        pre_title = request.text_fields.get("pre_title", "")
        main_title = request.text_fields.get("main_title", "")
        accent_word = request.text_fields.get("accent_word", "")
        brand_color = brand.get("brand_color_primary") or "#1A9E8F"
        handle = brand.get("brand_name") or "brand"

        # ── Background ──────────────────────────────────────────────────────
        if request.reference_image_url:
            logger.info("Hero-title: using user-uploaded background %s", request.reference_image_url)
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                resp = await client.get(request.reference_image_url)
                resp.raise_for_status()
                background_bytes = resp.content
        else:
            logger.info("Hero-title: generating background with Gemini for user=%s", user_id)
            prompt = build_post_image_prompt(
                template_key="hero-title",
                text_fields=request.text_fields,
                topic=request.topic,
                brand=brand,
            )
            bg_b64 = await self._image_gen.generate_from_prompt(prompt)
            background_bytes = base64.b64decode(bg_b64)

        # ── Pillow compositing ───────────────────────────────────────────────
        image_bytes = await compose_hero_title(
            background_bytes=background_bytes,
            pre_title=pre_title,
            main_title=main_title,
            accent_word=accent_word,
            brand_color_primary=brand_color,
            handle=handle,
        )

        # ── Upload + save ────────────────────────────────────────────────────
        upload_b64 = base64.b64encode(image_bytes).decode("utf-8")
        image_url = await self._storage.upload_image(upload_b64, user_id)

        self._save_to_requests_log(request=request, user_id=user_id, image_url=image_url)
        ContentService._invalidate_cache(user_id)

        try:
            await self._credits.increment_credits(user_id)
        except Exception as exc:
            logger.error("Failed to increment credits for %s: %s", user_id, exc)

        return image_url, request.caption

    async def _generate_masterclass_banner(
        self,
        request: PostGenerateRequest,
        user_id: str,
        brand: dict,
    ) -> tuple[str, str]:
        """Masterclass-banner: background + person + logo → Pillow compositor."""
        from app.utils.masterclass_banner_composer import compose as compose_masterclass
        from app.prompts.post_generate import (
            build_masterclass_background_prompt,
            build_masterclass_face_mode_prompt,
            build_masterclass_person_prompt,
        )

        tf = request.text_fields
        brand_color = brand.get("brand_color_primary") or "#1A9E8F"
        brand_color_sec = brand.get("brand_color_secondary") or "#FFFFFF"

        # ── Background image ──────────────────────────────────────────────────
        if request.reference_image_url:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                resp = await client.get(request.reference_image_url)
                resp.raise_for_status()
                background_bytes: bytes | None = resp.content
        else:
            try:
                prompt = build_masterclass_background_prompt(tf, brand)
                bg_b64 = await self._image_gen.generate_from_prompt(prompt)
                background_bytes = base64.b64decode(bg_b64)
            except Exception as exc:
                logger.warning("Background generation failed: %s", exc)
                background_bytes = None

        # ── Person image ─────────────────────────────────────────────────────
        mode = (request.person_image_mode or "ai").lower()

        if mode == "face" and request.person_image_url:
            face_b64 = await self._image_gen.download_image_as_base64(request.person_image_url)
            person_prompt = build_masterclass_face_mode_prompt(brand)
            person_b64 = await self._image_gen.generate_slide(person_prompt, face_b64)
            person_bytes = base64.b64decode(person_b64)
        elif mode == "upload" and request.person_image_url:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                resp = await client.get(request.person_image_url)
                resp.raise_for_status()
                person_bytes = resp.content
        else:
            person_prompt = build_masterclass_person_prompt(brand)
            person_b64 = await self._image_gen.generate_from_prompt(person_prompt)
            person_bytes = base64.b64decode(person_b64)

        person_bytes = await _remove_background(person_bytes)

        # ── Logo ─────────────────────────────────────────────────────────────
        logo_bytes: bytes | None = None
        logo_url = request.logo_url or brand.get("logo_url")
        if logo_url:
            try:
                async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                    resp = await client.get(logo_url)
                    resp.raise_for_status()
                    logo_bytes = resp.content
            except Exception as exc:
                logger.warning("Could not fetch logo %s: %s", logo_url, exc)

        # ── QR code ──────────────────────────────────────────────────────────
        qr_bytes: bytes | None = None
        if request.qr_image_url:
            try:
                async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                    resp = await client.get(request.qr_image_url)
                    resp.raise_for_status()
                    qr_bytes = resp.content
            except Exception as exc:
                logger.warning("Could not fetch QR image %s: %s", request.qr_image_url, exc)

        # ── Compose ──────────────────────────────────────────────────────────
        image_bytes = await compose_masterclass(
            background_bytes=background_bytes,
            person_bytes=person_bytes,
            logo_bytes=logo_bytes,
            qr_bytes=qr_bytes,
            event_label=tf.get("event_label", ""),
            title=tf.get("title", ""),
            subtitle=tf.get("subtitle", ""),
            date_time=tf.get("date_time", ""),
            venue=tf.get("venue", ""),
            via=tf.get("via", ""),
            cta=tf.get("cta", ""),
            brand_color_primary=brand_color,
            brand_color_secondary=brand_color_sec,
        )

        upload_b64 = base64.b64encode(image_bytes).decode("utf-8")
        image_url = await self._storage.upload_image(upload_b64, user_id)

        self._save_to_requests_log(request=request, user_id=user_id, image_url=image_url)
        ContentService._invalidate_cache(user_id)

        try:
            await self._credits.increment_credits(user_id)
        except Exception as exc:
            logger.error("Failed to increment credits for %s: %s", user_id, exc)

        return image_url, request.caption


    async def _generate_wellness_workshop(
        self,
        request: PostGenerateRequest,
        user_id: str,
        brand: dict,
    ) -> tuple[str, str]:
        """Wellness-workshop: 3-image top collage + tips checklist + person + dual logo."""
        from app.utils.wellness_workshop_composer import compose as compose_wellness
        from app.prompts.post_generate import (
            build_wellness_workshop_background_prompt,
            build_wellness_workshop_content_bg_prompt,
        )

        tf = request.text_fields
        brand_color = brand.get("brand_color_primary") or "#1A9E8F"
        brand_color_sec = brand.get("brand_color_secondary") or "#FFFFFF"

        # ── Collage panels 1–3 (can have people — lifestyle photos) ──────────
        async def _fetch_or_generate(url: str | None, slot: int) -> bytes | None:
            if url:
                try:
                    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                        resp = await client.get(url)
                        resp.raise_for_status()
                        return resp.content
                except Exception as exc:
                    logger.warning("Could not fetch bg panel %d (%s): %s", slot, url, exc)
            try:
                prompt = build_wellness_workshop_background_prompt(slot, tf, brand)
                b64 = await self._image_gen.generate_from_prompt(prompt)
                return base64.b64decode(b64)
            except Exception as exc:
                logger.warning("Background generation failed for panel %d: %s", slot, exc)
                return None

        # ── Content-area background (people-free ambient scene) ───────────────
        async def _generate_content_bg() -> bytes | None:
            try:
                prompt = build_wellness_workshop_content_bg_prompt(tf, brand)
                b64 = await self._image_gen.generate_from_prompt(prompt)
                return base64.b64decode(b64)
            except Exception as exc:
                logger.warning("Content background generation failed: %s", exc)
                return None

        bg1, bg2, bg3, content_bg = await asyncio.gather(
            _fetch_or_generate(request.reference_image_url, 1),
            _fetch_or_generate(request.bg_image_2_url, 2),
            _fetch_or_generate(request.bg_image_3_url, 3),
            _generate_content_bg(),
        )

        # ── Person image ──────────────────────────────────────────────────────
        from app.prompts.post_generate import (
            build_masterclass_face_mode_prompt,
            build_masterclass_person_prompt,
        )

        mode = (request.person_image_mode or "ai").lower()
        try:
            if mode == "face" and request.person_image_url:
                face_b64 = await self._image_gen.download_image_as_base64(request.person_image_url)
                person_prompt = build_masterclass_face_mode_prompt(brand)
                person_b64 = await self._image_gen.generate_slide(person_prompt, face_b64)
                person_bytes: bytes | None = base64.b64decode(person_b64)
            elif mode == "upload" and request.person_image_url:
                async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                    resp = await client.get(request.person_image_url)
                    resp.raise_for_status()
                    person_bytes = resp.content
            else:
                person_prompt = build_masterclass_person_prompt(brand)
                person_b64 = await self._image_gen.generate_from_prompt(person_prompt)
                person_bytes = base64.b64decode(person_b64)
        except Exception as exc:
            logger.warning("Person image generation failed: %s", exc)
            person_bytes = None

        if person_bytes is not None:
            person_bytes = await _remove_background(person_bytes)

        # ── Primary logo ──────────────────────────────────────────────────────
        logo_bytes: bytes | None = None
        logo_url = request.logo_url or brand.get("logo_url")
        if logo_url:
            try:
                async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                    resp = await client.get(logo_url)
                    resp.raise_for_status()
                    logo_bytes = resp.content
            except Exception as exc:
                logger.warning("Could not fetch primary logo: %s", exc)

        # ── Second logo ───────────────────────────────────────────────────────
        second_logo_bytes: bytes | None = None
        if request.second_logo_url:
            try:
                async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                    resp = await client.get(request.second_logo_url)
                    resp.raise_for_status()
                    second_logo_bytes = resp.content
            except Exception as exc:
                logger.warning("Could not fetch second logo: %s", exc)

        # ── Compose ───────────────────────────────────────────────────────────
        image_bytes = await compose_wellness(
            bg1_bytes=bg1,
            bg2_bytes=bg2,
            bg3_bytes=bg3,
            content_bg_bytes=content_bg,
            person_bytes=person_bytes,
            logo_bytes=logo_bytes,
            second_logo_bytes=second_logo_bytes,
            event_label=tf.get("event_label", ""),
            date_time=tf.get("date_time", ""),
            title=tf.get("title", ""),
            tip_1=tf.get("tip_1", ""),
            tip_2=tf.get("tip_2", ""),
            tip_3=tf.get("tip_3", ""),
            tip_4=tf.get("tip_4", ""),
            venue=tf.get("venue", ""),
            brand_color_primary=brand_color,
            brand_color_secondary=brand_color_sec,
        )

        upload_b64 = base64.b64encode(image_bytes).decode("utf-8")
        image_url = await self._storage.upload_image(upload_b64, user_id)

        self._save_to_requests_log(request=request, user_id=user_id, image_url=image_url)
        ContentService._invalidate_cache(user_id)

        try:
            await self._credits.increment_credits(user_id)
        except Exception as exc:
            logger.error("Failed to increment credits for %s: %s", user_id, exc)

        return image_url, request.caption


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
        "logo_url": profile.get("logo_url"),
    }


async def _remove_background(img_bytes: bytes) -> bytes:
    """Remove background from person image using rembg. Gracefully degrades if unavailable."""
    import asyncio
    try:
        from rembg import remove as rembg_remove
        result: bytes = await asyncio.to_thread(rembg_remove, img_bytes)
        return result
    except ImportError:
        logger.warning("rembg not installed — skipping background removal")
        return img_bytes
    except Exception as exc:
        logger.warning("Background removal failed: %s", exc)
        return img_bytes
