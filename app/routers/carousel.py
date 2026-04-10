import json
import logging

from fastapi import APIRouter, Depends

from app.dependencies import get_supabase_admin
from app.models.requests import FixSlideRequest, GenerateCarouselRequest
from app.models.responses import GenerateCarouselResponse
from app.prompts.carousel_fix import build_fix_slide_prompt
from app.prompts.carousel_generate import build_generate_slide_prompt
from app.services.auth import get_current_user
from app.services.brand import BrandService
from app.services.brand_context import build_brand_context_pack
from app.services.content_strategy import ContentStrategyService
from app.services.credits import CreditsService
from app.services.exceptions import AgentAPIError, GeminiError
from app.services.image_generator import ImageGeneratorService
from app.services.storage import StorageService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/carousel", tags=["carousel"])


@router.post("/generate", response_model=GenerateCarouselResponse)
async def generate_carousel(
    request: GenerateCarouselRequest,
    user: dict = Depends(get_current_user),
):
    """Generate a full carousel with LLM-driven content strategy."""
    user_id = user["id"]

    # 1. Check credits
    credits_service = CreditsService()
    await credits_service.check_credits(user_id)

    # 2. Load brand profile
    brand_service = BrandService()
    profile = await brand_service.load_profile(user_id)
    brand_context = build_brand_context_pack(profile)
    effective_profile = {
        **profile,
        "brand_playbook": brand_context["brand_brief"],
        "cta": brand_context["cta_rules"]["tone"],
    }

    # 3. Content strategy — LLM decides text, position, style
    strategy_service = ContentStrategyService()
    content_plan = await strategy_service.plan(
        message=request.message,
        brand_profile=effective_profile,
        slides_count=len(request.slides),
    )

    # 4. Generate each slide with Gemini
    image_gen = ImageGeneratorService()
    storage = StorageService()
    media_urls: list[str] = []
    failed_slides: list[int] = []

    for i, slide_input in enumerate(request.slides):
        slide_content = content_plan.slides[i] if i < len(content_plan.slides) else None
        slide_text = slide_input.text or (slide_content.text if slide_content else f"Slide {i+1}")
        slide_position = slide_input.text_position or (slide_content.text_position if slide_content else "Bottom Center")

        try:
            # Build Gemini prompt
            prompt = build_generate_slide_prompt(
                position=slide_position,
                text=slide_text,
                font_prompt=effective_profile.get("font_prompt", "Clean, bold, geometric sans-serif"),
                font_style=effective_profile.get("font_style", "bold"),
                font_size=effective_profile.get("font_size", "38px"),
                color_primary=effective_profile.get("brand_color_primary", "#000000"),
                color_secondary=effective_profile.get("brand_color_secondary", "#FFFFFF"),
                color_background=effective_profile.get("brand_color_background"),
                brand_playbook=effective_profile.get("brand_playbook") or effective_profile.get("content_style_brief") or "",
                font_prompt_secondary=effective_profile.get("font_prompt_secondary") or "",
                visual_environment_setup=effective_profile.get("visual_environment_setup") or "",
                visual_subject_outfit_face=effective_profile.get("visual_subject_outfit_face") or "",
                visual_subject_outfit_generic=effective_profile.get("visual_subject_outfit_generic") or "",
            )

            # Download source image
            image_base64 = await image_gen.download_image_as_base64(slide_input.image_url)

            # Generate with Gemini
            generated_base64 = await image_gen.generate_slide(prompt, image_base64)

            # Upload to storage
            public_url = await storage.upload_image(generated_base64, user_id)
            media_urls.append(public_url)

        except Exception as e:
            logger.error(f"Slide {i+1} failed: {e}")
            failed_slides.append(i + 1)

    if not media_urls:
        raise GeminiError("All slides failed to generate", details={"failed_slides": failed_slides})

    # 5. Save to requests_log
    supabase = get_supabase_admin()
    try:
        supabase.table("requests_log").upsert(
            {
                "id": request.message_id,
                "user_id": user_id,
                "agent_type": request.agent_type,
                "title": "Generated Carousel",
                "reply": content_plan.reply,
                "caption": content_plan.caption,
                "media_urls": media_urls,
                "published": False,
            },
            on_conflict="id",
        ).execute()
    except Exception as e:
        logger.error(f"Failed to save to requests_log: {e}")
        # Don't fail the request — carousel was generated

    # 6. Increment credits
    try:
        await credits_service.increment_credits(user_id)
    except Exception as e:
        logger.error(f"Failed to increment credits: {e}")

    # 7. Build reply with warning if partial
    reply = content_plan.reply
    if failed_slides:
        reply += f" (Note: slides {failed_slides} could not be generated)"

    return GenerateCarouselResponse(
        reply=reply,
        caption=content_plan.caption,
        media_urls=media_urls,
        message_id=request.message_id,
        is_fix=False,
    )


@router.post("/fix-slide", response_model=GenerateCarouselResponse)
async def fix_slide(
    request: FixSlideRequest,
    user: dict = Depends(get_current_user),
):
    """Fix a single slide from an existing carousel."""
    user_id = user["id"]

    # 1. Load brand profile
    brand_service = BrandService()
    profile = await brand_service.load_profile(user_id)

    # 2. Fetch original row
    supabase = get_supabase_admin()
    result = (
        supabase.table("requests_log")
        .select("id, media_urls, user_id, title")
        .eq("id", request.Row_ID)
        .single()
        .execute()
    )

    if not result.data:
        raise AgentAPIError(
            message=f"Row {request.Row_ID} not found",
            code="INVALID_ROW_ID",
            status_code=400,
        )

    # Verify ownership
    if result.data.get("user_id") != user_id:
        raise AgentAPIError(
            message="You don't own this carousel",
            code="UNAUTHORIZED",
            status_code=403,
        )

    original_urls: list[str] = result.data.get("media_urls", []) or []
    if isinstance(original_urls, str):
        try:
            original_urls = json.loads(original_urls)
        except (json.JSONDecodeError, TypeError):
            original_urls = []

    slide_idx = request.Slide_Number - 1
    if slide_idx < 0 or slide_idx >= len(original_urls):
        raise AgentAPIError(
            message=f"Slide number {request.Slide_Number} is out of range (1-{len(original_urls)})",
            code="INVALID_SLIDE_NUMBER",
            status_code=400,
        )

    # 3. Build fix prompt
    topic = result.data.get("title", "") or ""
    brand_context = build_brand_context_pack(profile)
    effective_profile = {
        **profile,
        "brand_playbook": brand_context["brand_brief"],
        "cta": brand_context["cta_rules"]["tone"],
    }

    prompt = build_fix_slide_prompt(
        new_text_content=request.New_Text_Content,
        font_prompt=effective_profile.get("font_prompt", "Clean bold sans-serif"),
        font_style=effective_profile.get("font_style", "bold"),
        color_primary=effective_profile.get("brand_color_primary", "#000000"),
        color_secondary=effective_profile.get("brand_color_secondary"),
        color_background=effective_profile.get("brand_color_background"),
        topic=topic,
    )

    # 4. Generate with Gemini
    image_gen = ImageGeneratorService()
    storage = StorageService()

    image_base64 = await image_gen.download_image_as_base64(request.New_Image_Link)
    generated_base64 = await image_gen.generate_slide(prompt, image_base64)
    public_url = await storage.upload_image(generated_base64, user_id)

    # 5. Splice into array
    updated_urls = list(original_urls)
    updated_urls[slide_idx] = public_url

    # 6. Update DB
    try:
        supabase.table("requests_log").update(
            {"media_urls": updated_urls}
        ).eq("id", request.Row_ID).execute()
    except Exception as e:
        logger.error(f"Failed to update requests_log: {e}")

    return GenerateCarouselResponse(
        reply="Slide fixed successfully",
        caption="",
        media_urls=updated_urls,
        message_id=request.message_id,
        is_fix=True,
    )


# ── SSE Streaming endpoint ──────────────────────────────────────────────────
from fastapi.responses import StreamingResponse


@router.post("/generate/stream")
async def generate_carousel_stream(
    request: GenerateCarouselRequest,
    user: dict = Depends(get_current_user),
):
    """Generate carousel with SSE streaming — each slide appears as it's ready."""
    user_id = user["id"]

    async def event_stream():
        # 1. Credits + Brand + Strategy (same as non-streaming)
        credits_service = CreditsService()
        await credits_service.check_credits(user_id)

        brand_service = BrandService()
        profile = await brand_service.load_profile(user_id)

        strategy_service = ContentStrategyService()
        content_plan = await strategy_service.plan(
            message=request.message,
            brand_profile=profile,
            slides_count=len(request.slides),
        )

        yield f"data: {json.dumps({'type': 'plan', 'reply': content_plan.reply, 'caption': content_plan.caption, 'total_slides': len(request.slides)})}\n\n"

        # 2. Generate each slide and stream as it completes
        image_gen = ImageGeneratorService()
        storage = StorageService()
        media_urls: list[str] = []

        for i, slide_input in enumerate(request.slides):
            slide_content = content_plan.slides[i] if i < len(content_plan.slides) else None
            slide_text = slide_input.text or (slide_content.text if slide_content else f"Slide {i+1}")
            slide_position = slide_input.text_position or (slide_content.text_position if slide_content else "Bottom Center")

            try:
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
                )

                image_base64 = await image_gen.download_image_as_base64(slide_input.image_url)
                generated_base64 = await image_gen.generate_slide(prompt, image_base64)
                public_url = await storage.upload_image(generated_base64, user_id)
                media_urls.append(public_url)

                yield f"data: {json.dumps({'type': 'slide', 'number': i + 1, 'url': public_url, 'text': slide_text})}\n\n"

            except Exception as e:
                logger.error(f"Stream slide {i+1} failed: {e}")
                yield f"data: {json.dumps({'type': 'slide_error', 'number': i + 1, 'error': str(e)})}\n\n"

        # 3. Save to DB + increment credits
        supabase = get_supabase_admin()
        try:
            supabase.table("requests_log").upsert({
                "id": request.message_id,
                "user_id": user_id,
                "agent_type": request.agent_type,
                "title": "Generated Carousel",
                "reply": content_plan.reply,
                "caption": content_plan.caption,
                "media_urls": media_urls,
                "published": False,
            }, on_conflict="id").execute()
        except Exception as e:
            logger.error(f"Stream: failed to save requests_log: {e}")

        try:
            await credits_service.increment_credits(user_id)
        except Exception as e:
            logger.error(f"Stream: failed to increment credits: {e}")

        # 4. Final event
        yield f"data: {json.dumps({'type': 'done', 'media_urls': media_urls, 'reply': content_plan.reply, 'caption': content_plan.caption, 'message_id': request.message_id})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
