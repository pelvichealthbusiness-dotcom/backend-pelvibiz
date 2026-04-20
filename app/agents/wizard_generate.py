"""WizardGenerateAgent — Direct carousel generation from wizard data.

Skips Gemini conversation entirely. Takes pre-built wizard payload
(slides, photos, positions, caption) and executes the image generation
pipeline directly, streaming progress via Vercel AI SDK SSE events.
"""

from __future__ import annotations

import asyncio
import base64

import httpx
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
from app.prompts.carousel_generate import build_generate_slide_prompt
from app.prompts.ai_carousel_generate import (
    build_generic_slide_prompt,
    build_card_slide_prompt,
    build_per_slide_context,
)
from app.services.brand import BrandService
from app.services.brand_context import build_brand_context_pack
from app.services.credits import CreditsService
from app.services.image_generator import ImageGeneratorService
from app.services.slide_renderer import SlideRenderer
from app.services.storage import StorageService
from app.services.watermark import WatermarkService
from app.utils.image import force_resolution
from app.services.image_qa import ImageQA
from PIL import Image
import io

logger = logging.getLogger(__name__)


class WizardGenerateAgent:
    """Handles carousel generation from wizard data.

    This is NOT a chat agent — it does not inherit from BaseStreamingAgent
    or use Gemini for conversation. It takes the wizard's pre-built data
    and runs the image generation pipeline directly.
    """

    def __init__(self, user_id: str, agent_type: str) -> None:
        self.user_id = user_id
        self.agent_type = agent_type  # 'real-carousel' or 'ai-carousel'

    async def stream(
        self,
        message: str,
        history: list[dict] | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        """Execute wizard generation pipeline, yielding SSE events.

        Parameters
        ----------
        message:
            JSON string with wizard payload, or plain text (ignored if
            metadata is present).
        history:
            Ignored — wizard generation has no conversation history.
        **kwargs:
            Must contain ``metadata`` dict with wizard data:
            - slides: list of {title, body, position, slide_type}
            - photos: list of image URLs (P1 only)
            - caption: str
            - topic: str
            - face_photo_url: str (P2 face slides)
            - font_style, font_prompt, color_primary, etc.
            - slide_count: int
            - message_id: str (optional)
        """
        metadata = kwargs.get("metadata") or {}

        # ── 1. Parse wizard data from message JSON or metadata ────────
        wizard_data = self._parse_wizard_data(message, metadata)
        slides = wizard_data.get("slides", [])
        message_id = wizard_data.get("message_id", str(uuid.uuid4()))

        if not slides:
            yield error_event("No slides provided in wizard data", "VALIDATION_ERROR")
            return

        # ── 2. Emit planning event ───────────────────────────────────
        yield metadata_event({
            "type": "generation_progress",
            "phase": "plan",
            "total_slides": len(slides),
            "message_id": message_id,
        })

        # ── 3. Check credits ─────────────────────────────────────────
        try:
            credits_service = CreditsService()
            await credits_service.check_credits(self.user_id)
        except Exception as e:
            yield error_event(str(e), "CREDITS_EXHAUSTED")
            return

        # ── 4. Load brand profile ────────────────────────────────────
        try:
            brand_service = BrandService()
            profile = await brand_service.load_profile(self.user_id)
            logger.info("Loaded brand profile for user %s: font_style=%s, brand_color_primary=%s", self.user_id, profile.get("font_style"), profile.get("brand_color_primary"))
        except Exception as e:
            logger.error("Failed to load brand profile: %s", e)
            yield error_event("Failed to load brand profile", "BRAND_ERROR")
            return

        # ── 5. Merge wizard overrides into profile ───────────────────
        # The wizard may send font/color overrides that take precedence
        profile_overrides = self._extract_profile_overrides(wizard_data)
        effective_profile = {**profile, **profile_overrides}
        brand_context = build_brand_context_pack(effective_profile)
        effective_profile = {
            **effective_profile,
            "brand_playbook": brand_context["brand_brief"],
            "cta": brand_context["cta_rules"]["tone"],
        }
        logger.info("Effective profile: font_style=%s, font_prompt=%s, color_primary=%s", effective_profile.get("font_style"), effective_profile.get("font_prompt"), effective_profile.get("brand_color_primary"))

        # ── 5b. Load brand stories for narrative context ─────────────
        try:
            from app.services.stories_service import load_user_stories
            _stories_list = await load_user_stories(self.user_id)
            story_context = " | ".join([
                f"{s.get('title', '')}: {s.get('content', '')[:180]}"
                for s in _stories_list[:2] if s.get("content")
            ]) if _stories_list else ""
        except Exception as _e:
            logger.warning("Could not load brand stories: %s", _e)
            story_context = ""

        # ── 6. Generate each slide ───────────────────────────────────
        yield text_chunk(f"Generating {len(slides)} slides...\n")

        generated_urls: list[str] = []
        failed_slides: list[int] = []
        generated_prompts: list[str] = []

        if self.agent_type == "ai-carousel":
            # Use a queue for real-time slide-by-slide streaming
            progress_queue: asyncio.Queue = asyncio.Queue()

            async def run_generation():
                urls, fails, prompts = await self._generate_ai_slides(
                    slides, wizard_data, effective_profile, progress_queue,
                    story_context=story_context,
                )
                await progress_queue.put(("DONE", urls, fails, prompts))

            gen_task = asyncio.create_task(run_generation())

            # Yield events as they arrive from concurrent generation
            while True:
                item = await progress_queue.get()
                if item[0] == "DONE":
                    generated_urls = list(item[1])
                    failed_slides = list(item[2])
                    generated_prompts = list(item[3])
                    break
                elif item[0] == "slide_complete":
                    idx, url = item[1], item[2]
                    yield metadata_event({
                        "type": "generation_progress",
                        "phase": "slide_complete",
                        "slide_index": idx,
                        "slide_url": url,
                        "total": len(slides),
                    })
                elif item[0] == "slide_failed":
                    idx, err = item[1], item[2]
                    yield metadata_event({
                        "type": "generation_progress",
                        "phase": "slide_failed",
                        "slide_index": idx,
                        "error": err,
                    })

            await gen_task
        else:
            # P1 real-carousel — sequential with streaming events via queue
            photos = wizard_data.get("photos", [])
            progress_queue: asyncio.Queue = asyncio.Queue()

            async def run_p1_generation():
                urls, fails = await self._generate_real_slides_streaming(
                    slides, photos, wizard_data, effective_profile, progress_queue,
                )
                await progress_queue.put(("DONE", urls, fails))

            gen_task = asyncio.create_task(run_p1_generation())

            while True:
                item = await progress_queue.get()
                if item[0] == "DONE":
                    generated_urls = list(item[1])
                    failed_slides = list(item[2])
                    break
                elif item[0] == "slide_complete":
                    idx, url = item[1], item[2]
                    yield metadata_event({
                        "type": "generation_progress",
                        "phase": "slide_complete",
                        "slide_index": idx,
                        "slide_url": url,
                        "total": len(slides),
                    })
                elif item[0] == "slide_failed":
                    idx, err = item[1], item[2]
                    yield metadata_event({
                        "type": "generation_progress",
                        "phase": "slide_failed",
                        "slide_index": idx,
                        "error": err,
                    })

            await gen_task

        # Filter out None entries from failed slides
        media_urls = [u for u in generated_urls if u]

        if not media_urls:
            yield error_event("All slides failed to generate", "GENERATION_FAILED")
            return

        # ── 7. Save to requests_log ──────────────────────────────────
        try:
            supabase = get_supabase_admin()
            slide_metadata = {
                "texts": [
                    s.get("body") or s.get("text") or s.get("title", "")
                    for s in slides
                ],
                "positions": [
                    s.get("position") or s.get("text_position", "")
                    for s in slides
                ],
                "prompts": generated_prompts,
            }
            supabase.table("requests_log").upsert(
                {
                    "id": message_id,
                    "user_id": self.user_id,
                    "agent_type": self.agent_type,
                    "title": wizard_data.get("topic", "Wizard Carousel"),
                    "reply": f"Generated {len(media_urls)} carousel slides",
                    "caption": wizard_data.get("caption", ""),
                    "media_urls": media_urls,
                    "metadata": slide_metadata,
                    "published": False,
                },
                on_conflict="id",
            ).execute()
        except Exception as e:
            logger.error("Failed to save to requests_log: %s", e)

        # ── 8. Increment credits ─────────────────────────────────────
        try:
            await credits_service.increment_credits(self.user_id)
        except Exception as e:
            logger.error("Failed to increment credits: %s", e)

        # ── 9. Emit done event ───────────────────────────────────────
        failed_count = len(failed_slides)
        total_count = len(slides)
        if failed_count > 0:
            yield metadata_event({
                "type": "warning",
                "message": f"{failed_count} slide(s) no pudieron generarse y fueron omitidos.",
                "failed_count": failed_count,
                "total_count": total_count,
            })
        yield metadata_event({
            "type": "generation_progress",
            "phase": "done",
            "media_urls": media_urls,
            "caption": wizard_data.get("caption", ""),
            "message_id": message_id,
            "failed_slides": failed_slides,
        })

        status_msg = f"Generated {len(media_urls)} carousel slides"
        if failed_slides:
            status_msg += f" ({len(failed_slides)} failed)"
        yield text_chunk(status_msg)
        yield finish_event("stop")

    # ------------------------------------------------------------------
    # P1 Real Carousel — sequential slide generation
    # ------------------------------------------------------------------

    async def _generate_real_slides_streaming(
        self,
        slides: list[dict],
        photos: list[str],
        wizard_data: dict,
        profile: dict,
        progress_queue: asyncio.Queue | None = None,
    ) -> tuple[list[str | None], list[int]]:
        """Generate P1 real-photo slides sequentially using Pillow renderer.

        Falls back to Gemini if USE_GEMINI_P1 env var is set.
        Returns (urls, failed).
        """
        import os

        use_gemini = os.environ.get("USE_GEMINI_P1", "").lower() in ("1", "true", "yes")

        if use_gemini:
            return await self._generate_real_slides_gemini(slides, photos, wizard_data, profile)

        renderer = SlideRenderer()
        storage = StorageService()

        generated_urls: list[str | None] = []
        failed_slides: list[int] = []

        for i, slide in enumerate(slides):
            photo_url = photos[i] if i < len(photos) else (photos[-1] if photos else None)

            if not photo_url:
                logger.error("Slide %d: no photo URL available", i + 1)
                generated_urls.append(None)
                failed_slides.append(i + 1)
                continue

            try:
                slide_text = slide.get("body") or slide.get("text") or slide.get("title", f"Slide {i + 1}")
                slide_position = slide.get("position") or slide.get("text_position", "Bottom Center")
                if slide_position == "Bottom Center":
                    slide_position = "Center"

                image_bytes = await renderer.download_image(photo_url)
                if not image_bytes:
                    raise ValueError(f"Failed to download photo for slide {i + 1}")
                result_bytes = renderer.render_slide(
                    image_bytes=image_bytes,
                    text=slide_text,
                    position=slide_position,
                    font_style=profile.get("font_style", "bold"),
                    color_primary=profile.get("brand_color_primary", "#000000"),
                    color_secondary=profile.get("brand_color_secondary", "#FFFFFF"),
                    color_background=profile.get("brand_color_background"),
                    enhance_quality=True,
                    slide_index=i,
                    font_style_secondary=profile.get("font_style_secondary"),
                )
                logo_url = profile.get("logo_url")
                if logo_url:
                    from app.services.watermark import WatermarkService
                    watermark_service = WatermarkService()
                    try:
                        result_bytes = await watermark_service.apply(result_bytes, logo_url, self.user_id)
                    except Exception as e:
                        logger.warning("Watermark failed for P1 slide %d, delivering without watermark: %s", i, e)
                result_base64 = base64.b64encode(result_bytes).decode("utf-8")
                public_url = await storage.upload_image(result_base64, self.user_id)
                generated_urls.append(public_url)
                if progress_queue:
                    await progress_queue.put(("slide_complete", i, public_url))

            except Exception as e:
                logger.error("P1 slide %d failed (Pillow): %s", i + 1, e)
                # Fallback to Gemini for this slide
                try:
                    logger.info("Falling back to Gemini for slide %d", i + 1)
                    fallback_url = await self._generate_single_slide_gemini(
                        slide, photo_url, profile,
                    )
                    generated_urls.append(fallback_url)
                    if progress_queue:
                        await progress_queue.put(("slide_complete", i, fallback_url))
                except Exception as e2:
                    logger.error("P1 slide %d Gemini fallback also failed: %s", i + 1, e2)
                    generated_urls.append(None)
                    failed_slides.append(i + 1)

        return generated_urls, failed_slides

    async def _generate_single_slide_gemini(
        self,
        slide: dict,
        photo_url: str,
        profile: dict,
    ) -> str:
        """Generate a single P1 slide using Gemini (fallback)."""
        image_gen = ImageGeneratorService()
        storage = StorageService()

        slide_text = slide.get("body") or slide.get("text") or slide.get("title", "Slide")
        slide_position = slide.get("position") or slide.get("text_position", "Bottom Center")
        if slide_position == "Bottom Center":
            slide_position = "Center"

        prompt = build_generate_slide_prompt(
            position=slide_position,
            text=slide_text,
            font_prompt=profile.get("font_prompt", "Clean, bold, geometric sans-serif"),
            font_style=profile.get("font_style", "bold"),
            font_size=profile.get("font_size", "38px"),
            color_primary=profile.get("brand_color_primary", "#000000"),
            color_secondary=profile.get("brand_color_secondary", "#FFFFFF"),
            color_background=profile.get("brand_color_background"),
            brand_playbook=profile.get("brand_playbook") or profile.get("content_style_brief") or "",
            visual_environment_setup=profile.get("visual_environment_setup") or "",
            visual_subject_outfit_face=profile.get("visual_subject_outfit_face") or "",
            visual_subject_outfit_generic=profile.get("visual_subject_outfit_generic") or "",
        )

        image_base64 = await image_gen.download_image_as_base64(photo_url)
        generated_base64 = await image_gen.generate_slide(prompt, image_base64)
        return await storage.upload_image(generated_base64, self.user_id)

    async def _generate_real_slides_gemini(
        self,
        slides: list[dict],
        photos: list[str],
        wizard_data: dict,
        profile: dict,
    ) -> tuple[list[str | None], list[int]]:
        """Original Gemini-based P1 generation (kept as fallback)."""
        image_gen = ImageGeneratorService()
        storage = StorageService()

        generated_urls: list[str | None] = []
        failed_slides: list[int] = []

        for i, slide in enumerate(slides):
            photo_url = photos[i] if i < len(photos) else (photos[-1] if photos else None)

            if not photo_url:
                logger.error("Slide %d: no photo URL available", i + 1)
                generated_urls.append(None)
                failed_slides.append(i + 1)
                continue

            try:
                slide_text = slide.get("body") or slide.get("text") or slide.get("title", f"Slide {i + 1}")
                slide_position = slide.get("position") or slide.get("text_position", "Bottom Center")
                if slide_position == "Bottom Center":
                    slide_position = "Center"

                prompt = build_generate_slide_prompt(
                    position=slide_position,
                    text=slide_text,
                    font_prompt=profile.get("font_prompt", "Clean, bold, geometric sans-serif"),
                    font_style=profile.get("font_style", "bold"),
                    font_size=profile.get("font_size", "38px"),
                    color_primary=profile.get("brand_color_primary", "#000000"),
                    color_secondary=profile.get("brand_color_secondary", "#FFFFFF"),
                    color_background=profile.get("brand_color_background"),
                    brand_playbook=profile.get("brand_playbook") or profile.get("content_style_brief") or "",
                font_prompt_secondary=profile.get("font_prompt_secondary") or "",
                    visual_environment_setup=profile.get("visual_environment_setup") or "",
                    visual_subject_outfit_face=profile.get("visual_subject_outfit_face") or "",
                    visual_subject_outfit_generic=profile.get("visual_subject_outfit_generic") or "",
                )

                image_base64 = await image_gen.download_image_as_base64(photo_url)
                generated_base64 = await image_gen.generate_slide(prompt, image_base64)
                public_url = await storage.upload_image(generated_base64, self.user_id)
                generated_urls.append(public_url)

            except Exception as e:
                logger.error("P1 slide %d failed: %s", i + 1, e)
                generated_urls.append(None)
                failed_slides.append(i + 1)

        return generated_urls, failed_slides

    # ------------------------------------------------------------------
    # P2 AI Carousel — concurrent slide generation
    # ------------------------------------------------------------------

    async def _generate_ai_slides(
        self,
        slides: list[dict],
        wizard_data: dict,
        profile: dict,
        progress_queue: asyncio.Queue,
        story_context: str = "",
    ) -> tuple[list[str | None], list[int], list[str]]:
        """Generate P2 AI slides concurrently. Returns (urls, failed, prompts)."""
        settings = get_settings()
        image_gen = ImageGeneratorService()
        watermark_service = WatermarkService()
        storage = StorageService()
        semaphore = asyncio.Semaphore(settings.p2_gemini_concurrency)

        # Pre-select one composition + lighting for ALL slides — visual coherence
        from app.prompts.ai_carousel_generate import COMPOSITION_VARIATIONS, LIGHTING_VARIATIONS
        import random as _random
        carousel_composition = _random.choice(COMPOSITION_VARIATIONS)
        carousel_lighting = _random.choice(LIGHTING_VARIATIONS)
        carousel_topic = wizard_data.get("topic", "")

        async def generate_single(i: int, slide: dict) -> tuple[int, str | None, str]:
            async with semaphore:
                try:
                    slide_text = slide.get("body") or slide.get("text") or slide.get("title", f"Slide {i + 1}")
                    slide_position = slide.get("position") or slide.get("text_position", "Bottom Center")
                    if slide_position == "Bottom Center":
                        slide_position = "Center"
                    slide_type = (slide.get("slide_type") or slide.get("type") or "generic").lower()
                    raw_visual = slide.get("visual_prompt", "") or ""
                    brand_environment = profile.get("visual_environment_setup", "") or ""
                    brand_voice = profile.get("brand_voice", "") or ""

                    visual_prompt = build_per_slide_context(
                        slide_topic=slide_text,
                        visual_prompt=raw_visual,
                        brand_environment=brand_environment,
                        brand_voice=brand_voice,
                        slide_index=i,
                        total_slides=len(slides),
                        slide_type=slide_type,
                        keywords=profile.get("keywords", "") or "",
                        content_style=profile.get("content_style_brief", "") or "",
                        brand_playbook=profile.get("brand_playbook") or profile.get("content_style_brief") or "",
                        font_prompt_secondary=profile.get("font_prompt_secondary") or "",
                        visual_subject_outfit_face=profile.get("visual_subject_outfit_face") or "",
                        visual_subject_outfit_generic=profile.get("visual_subject_outfit_generic") or "",
                        story_context=story_context,
                        topic=carousel_topic,
                    )

                    if slide_type == "card":
                        prompt = build_card_slide_prompt(
                            text=slide_text,
                            text_position=slide_position,
                            font_prompt=profile.get("font_prompt", "Clean, bold, geometric sans-serif"),
                            font_style=profile.get("font_style", "bold"),
                            font_size=profile.get("font_size", "42px"),
                            color_primary=profile.get("brand_color_primary", "#000000"),
                            color_secondary=profile.get("brand_color_secondary", "#FFFFFF"),
                            color_background=profile.get("brand_color_background") or "",
                            slide_index=i,
                            font_prompt_secondary=profile.get("font_prompt_secondary"),
                        )
                    else:
                        # generic or face
                        prompt = build_generic_slide_prompt(
                            visual_prompt=visual_prompt,
                            text=slide_text,
                            text_position=slide_position,
                            font_prompt=profile.get("font_prompt", "Clean, bold, geometric sans-serif"),
                            font_style=profile.get("font_style", "bold"),
                            font_size=profile.get("font_size", "38px"),
                            color_primary=profile.get("brand_color_primary", "#000000"),
                            color_secondary=profile.get("brand_color_secondary", "#FFFFFF"),
                            subject_description=(
                            profile.get("visual_subject_outfit_face", "")
                            if slide_type == "face" and profile.get("visual_subject_outfit_face")
                            else profile.get("visual_subject_outfit_generic", "")
                        ),
                            color_background=profile.get("brand_color_background") or "",
                            slide_index=i,
                            is_face_mode=(slide_type == "face" and bool(wizard_data.get("face_photo_url"))),
                            font_prompt_secondary=profile.get("font_prompt_secondary"),
                            composition=carousel_composition,
                            lighting=carousel_lighting,
                        )

                    # Face mode: send face photo as reference image to Gemini
                    face_photo_url = wizard_data.get("face_photo_url", "")
                    is_face_slide = slide_type == "face" and bool(face_photo_url)

                    # Pre-download face image once (outside QA loop)
                    face_base64: str | None = None
                    if is_face_slide:
                        face_bytes = await self._download_face_image(face_photo_url)
                        if face_bytes is None:
                            face_base64 = await image_gen.download_image_as_base64(face_photo_url)
                        else:
                            face_base64 = base64.b64encode(face_bytes).decode("utf-8")

                    # QA loop — retry generation if quality checks fail
                    _qa = ImageQA()
                    _qa_attempts = 0
                    _current_prompt = prompt
                    _qa_passed = False
                    image_bytes: bytes = b""

                    while True:
                        if is_face_slide and face_base64 is not None:
                            generated_base64 = await image_gen.generate_slide(_current_prompt, face_base64)
                        else:
                            generated_base64 = await image_gen.generate_from_prompt(_current_prompt)

                        image_bytes = base64.b64decode(generated_base64)
                        image_bytes = force_resolution(image_bytes)

                        if settings.enable_image_qa:
                            try:
                                _qa_img = Image.open(io.BytesIO(image_bytes))
                                _qa_passed, _qa_failures = _qa.check(_qa_img, slide_type)
                            except Exception:
                                _qa_passed = True
                                _qa_failures = []

                            if _qa_passed or _qa_attempts >= settings.image_qa_max_attempts - 1:
                                if not _qa_passed and _qa_attempts > 0:
                                    logger.warning(
                                        "Slide %d: QA loop exhausted after %d attempts, using last result",
                                        i, _qa_attempts + 1,
                                    )
                                break

                            _failure_hint = "; ".join(_qa_failures)
                            logger.warning(
                                "Slide %d QA attempt %d failed: %s", i, _qa_attempts + 1, _failure_hint
                            )
                            _bg_hint = (
                                "solid flat background with no gradient or pattern"
                                if slide_type == "card"
                                else "natural scene extending to all edges"
                            )
                            _current_prompt = _current_prompt + (
                                f"\n\n\u26a0\ufe0f QUALITY FIX REQUIRED: Previous generation failed quality check: "
                                f"{_failure_hint}. Fix these specific issues in this new attempt. "
                                f"Ensure complete coverage, proper brightness, and {_bg_hint}."
                            )
                            _qa_attempts += 1
                        else:
                            break

                    logo_url = profile.get("logo_url")
                    try:
                        image_bytes = await watermark_service.apply(image_bytes, logo_url, self.user_id)
                    except Exception as e:
                        logger.warning("Watermark failed for AI slide %d, delivering without watermark: %s", i, e)

                    upload_base64 = base64.b64encode(image_bytes).decode("utf-8")
                    public_url = await storage.upload_image(upload_base64, self.user_id)

                    await progress_queue.put(("slide_complete", i, public_url))
                    return (i, public_url, prompt)

                except Exception as e:
                    logger.error("AI slide %d failed: %s", i + 1, e)
                    await progress_queue.put(("slide_failed", i, str(e)))
                    return (i, None, "")

        tasks = [generate_single(i, slide) for i, slide in enumerate(slides)]
        results = await asyncio.gather(*tasks)

        # Sort by index and collect results
        sorted_results = sorted(results, key=lambda x: x[0])
        generated_urls: list[str | None] = [r[1] for r in sorted_results]
        failed_slides: list[int] = [r[0] + 1 for r in sorted_results if r[1] is None]
        slide_prompts: list[str] = [r[2] for r in sorted_results]

        return generated_urls, failed_slides, slide_prompts

    # ------------------------------------------------------------------
    # Face Image Download (with retry)
    # ------------------------------------------------------------------

    async def _download_face_image(self, url: str) -> bytes | None:
        """Download face reference image with retry. Returns bytes or None."""
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=20) as client:
                    resp = await client.get(url, follow_redirects=True)
                    resp.raise_for_status()
                    return resp.content
            except Exception as e:
                if attempt == 2:
                    logger.error('Face image download failed: %s', e)
                    return None
                await asyncio.sleep(2 ** attempt)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_wizard_data(message: str, metadata: dict) -> dict:
        """Parse wizard payload from message JSON or metadata."""
        # Try parsing message as JSON first
        if message and message.strip().startswith("{"):
            try:
                parsed = json.loads(message)
                # Merge with metadata (message JSON takes precedence)
                return {**metadata, **parsed}
            except (json.JSONDecodeError, TypeError):
                pass

        # Fall back to metadata
        return metadata

    @staticmethod
    def _extract_profile_overrides(wizard_data: dict) -> dict:

        mapping = {
            "font_style": "font_style",
            "font_prompt": "font_prompt",
            "color_primary": "brand_color_primary",
            "color_secondary": "brand_color_secondary",
            "color_background": "brand_color_background",
        }
        overrides = {}
        for wizard_key, profile_key in mapping.items():
            if wizard_key in wizard_data and wizard_data[wizard_key]:
                overrides[profile_key] = wizard_data[wizard_key]
        return overrides
