import asyncio
import base64
import logging
from fastapi import APIRouter, Depends
from app.services.auth import get_current_user
from app.services.brand import BrandService
from app.services.credits import CreditsService
from app.services.content_strategy import ContentStrategyService
from app.services.image_generator import ImageGeneratorService
from app.services.storage import StorageService
from app.services.watermark import WatermarkService
from app.services.exceptions import AgentAPIError, GeminiError
from app.models.ai_carousel import (
    GenerateAiCarouselRequest, AiCarouselGenerateResponse,
    AiCarouselFixRequest, AiSlideContent, SlideType, GenerationMetadata,
)
from app.prompts.ai_carousel_generate import build_generic_slide_prompt, build_card_slide_prompt
from app.prompts.ai_carousel_fix import build_ai_fix_generic_prompt, build_ai_fix_card_prompt
from app.utils.image import force_resolution
from app.dependencies import get_supabase_admin
from app.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai-carousel", tags=["ai-carousel"])


async def _generate_single_slide(
    slide: AiSlideContent,
    profile: dict,
    image_gen: ImageGeneratorService,
    watermark: WatermarkService,
    storage: StorageService,
    user_id: str,
    semaphore: asyncio.Semaphore,
) -> tuple[int, str | None, str]:
    """Generate a single AI slide. Returns (number, url_or_none, prompt_used)."""
    async with semaphore:
        try:
            # Build Gemini prompt based on slide type
            if slide.slide_type in (SlideType.GENERIC, SlideType.FACE):
                prompt = build_generic_slide_prompt(
                    visual_prompt=slide.visual_prompt,
                    text=slide.text,
                    text_position=slide.text_position,
                    font_prompt=profile.get("font_prompt", "Clean, bold, geometric sans-serif"),
                    font_style=profile.get("font_style", "bold"),
                    font_size=profile.get("font_size", "38px"),
                    color_primary=profile.get("brand_color_primary", "#000000"),
                    color_secondary=profile.get("brand_color_secondary", "#FFFFFF"),
                    subject_description=profile.get("visual_subject_outfit_generic", ""),
                )
            else:  # CARD
                prompt = build_card_slide_prompt(
                    text=slide.text,
                    text_position=slide.text_position or "Center",
                    font_prompt=profile.get("font_prompt", "Clean, bold, geometric sans-serif"),
                    font_style=profile.get("font_style", "bold"),
                    font_size=profile.get("font_size", "42px"),
                    color_primary=profile.get("brand_color_primary", "#000000"),
                    color_secondary=profile.get("brand_color_secondary", "#FFFFFF"),
                )

            # Generate with Gemini (text-only, no source image)
            generated_base64 = await image_gen.generate_from_prompt(prompt)
            
            # Force resolution to 1080x1350
            image_bytes = base64.b64decode(generated_base64)
            image_bytes = force_resolution(image_bytes)
            
            # Apply watermark
            logo_url = profile.get("logo_url")
            image_bytes = await watermark.apply(image_bytes, logo_url, user_id)
            
            # Upload to storage
            upload_base64 = base64.b64encode(image_bytes).decode("utf-8")
            public_url = await storage.upload_image(upload_base64, user_id)
            
            return (slide.number, public_url, prompt)

        except Exception as e:
            logger.error(f"AI slide {slide.number} ({slide.slide_type}) failed: {e}")
            return (slide.number, None, "")


@router.post("/generate", response_model=AiCarouselGenerateResponse)
async def generate_ai_carousel(
    request: GenerateAiCarouselRequest,
    user: dict = Depends(get_current_user),
):
    """Generate a full AI carousel with Generic and Card slide types."""
    user_id = user["id"]
    settings = get_settings()
    
    # 1. Check credits
    credits_service = CreditsService()
    await credits_service.check_credits(user_id)
    
    # 2. Load brand profile
    brand_service = BrandService()
    profile = await brand_service.load_profile(user_id)
    
    # 3. Content strategy — LLM decides slide types + text
    strategy = ContentStrategyService()
    
    if request.slides:
        # User specified slides — convert to AiSlideContent
        from app.models.ai_carousel import AiContentPlan
        plan_slides = []
        for s in request.slides:
            plan_slides.append(AiSlideContent(
                number=s.number,
                slide_type=s.slide_type,
                text=s.text or f"Slide {s.number}",
                text_position=s.text_position or "Bottom Center",
                visual_prompt=profile.get("visual_environment_setup", "") if s.slide_type in (SlideType.GENERIC, SlideType.FACE) else "",
            ))
        content_plan = AiContentPlan(
            slides=plan_slides,
            reply="Your AI carousel is ready!",
            caption="",
            reasoning="User-directed slides",
        )
    else:
        # Auto-plan with LLM
        content_plan = await strategy.plan_ai(
            message=request.message,
            brand_profile=profile,
            slide_count=request.slide_count,
        )
    
    # 4. Generate slides in parallel with semaphore
    image_gen = ImageGeneratorService()
    watermark_service = WatermarkService()
    storage = StorageService()
    semaphore = asyncio.Semaphore(settings.p2_gemini_concurrency)
    
    tasks = [
        _generate_single_slide(slide, profile, image_gen, watermark_service, storage, user_id, semaphore)
        for slide in content_plan.slides
    ]
    results = await asyncio.gather(*tasks)
    
    # 5. Collect results
    media_urls: list[str] = []
    failed_slides: list[int] = []
    prompts_used: list[str] = []
    slide_types: list[str] = []
    
    for number, url, prompt in sorted(results, key=lambda x: x[0]):
        if url:
            media_urls.append(url)
        else:
            failed_slides.append(number)
        prompts_used.append(prompt)
        slide_types.append(content_plan.slides[number - 1].slide_type.value if number <= len(content_plan.slides) else "generic")
    
    if not media_urls:
        raise GeminiError("All AI slides failed to generate", details={"failed_slides": failed_slides})
    
    # 6. Save to requests_log with metadata
    supabase = get_supabase_admin()
    metadata = {
        "slide_types": slide_types,
        "prompts": prompts_used,
        "texts": [s.text for s in content_plan.slides],
        "positions": [s.text_position for s in content_plan.slides],
        "brand_snapshot": {
            "brand_color_primary": profile.get("brand_color_primary"),
            "brand_color_secondary": profile.get("brand_color_secondary"),
            "font_style": profile.get("font_style"),
            "font_prompt": profile.get("font_prompt"),
            "font_size": profile.get("font_size"),
        },
    }
    
    try:
        supabase.table("requests_log").upsert({
            "id": request.message_id,
            "user_id": user_id,
            "agent_type": "ai-carousel",
            "title": "AI Generated Carousel",
            "reply": content_plan.reply,
            "caption": content_plan.caption,
            "media_urls": media_urls,
            "published": False,
        }, on_conflict="id").execute()
    except Exception as e:
        logger.error(f"Failed to save to requests_log: {e}")
    
    # 7. Increment credits
    try:
        await credits_service.increment_credits(user_id)
    except Exception as e:
        logger.error(f"Failed to increment credits: {e}")
    
    # 8. Build response
    reply = content_plan.reply
    if failed_slides:
        reply += f" (Note: slides {failed_slides} could not be generated)"
    
    return AiCarouselGenerateResponse(
        reply=reply,
        caption=content_plan.caption,
        media_urls=media_urls,
        message_id=request.message_id,
        is_fix=False,
        slide_types=slide_types,
        failed_slides=failed_slides,
        partial=len(failed_slides) > 0,
    )


@router.post("/fix-slide", response_model=AiCarouselGenerateResponse)
async def fix_ai_slide(
    request: AiCarouselFixRequest,
    user: dict = Depends(get_current_user),
):
    """Fix a single slide from an AI carousel."""
    user_id = user["id"]
    
    # 1. Load brand profile
    brand_service = BrandService()
    profile = await brand_service.load_profile(user_id)
    
    # 2. Fetch original row
    supabase = get_supabase_admin()
    result = supabase.table("requests_log").select("id, media_urls, user_id, metadata").eq("id", request.Row_ID).single().execute()
    
    if not result.data:
        raise AgentAPIError(message=f"Row {request.Row_ID} not found", code="INVALID_ROW_ID", status_code=400)
    
    if result.data.get("user_id") != user_id:
        raise AgentAPIError(message="You don't own this carousel", code="UNAUTHORIZED", status_code=403)
    
    original_urls = result.data.get("media_urls", []) or []
    metadata = result.data.get("metadata") or {}
    
    slide_idx = request.Slide_Number - 1
    if slide_idx < 0 or slide_idx >= len(original_urls):
        raise AgentAPIError(
            message=f"Slide {request.Slide_Number} out of range (1-{len(original_urls)})",
            code="INVALID_SLIDE_NUMBER", status_code=400,
        )
    
    # Determine slide type from metadata or request
    slide_types = metadata.get("slide_types", [])
    slide_type = request.slide_type
    if not slide_type and slide_idx < len(slide_types):
        slide_type = SlideType(slide_types[slide_idx])
    if not slide_type:
        slide_type = SlideType.GENERIC
    
    # Get original prompt if available
    original_prompts = metadata.get("prompts", [])
    original_prompt = original_prompts[slide_idx] if slide_idx < len(original_prompts) else ""
    
    # 3. Build fix prompt
    if slide_type in (SlideType.GENERIC, SlideType.FACE):
        prompt = build_ai_fix_generic_prompt(
            original_prompt=original_prompt,
            new_text=request.New_Text_Content,
            font_prompt=profile.get("font_prompt", "Sans-serif"),
            font_style=profile.get("font_style", "bold"),
            color_primary=profile.get("brand_color_primary", "#000000"),
            color_secondary=profile.get("brand_color_secondary", "#FFFFFF"),
        )
    else:
        prompt = build_ai_fix_card_prompt(
            new_text=request.New_Text_Content,
            font_prompt=profile.get("font_prompt", "Sans-serif"),
            font_style=profile.get("font_style", "bold"),
            color_primary=profile.get("brand_color_primary", "#000000"),
            color_secondary=profile.get("brand_color_secondary", "#FFFFFF"),
        )
    
    # 4. Generate
    image_gen = ImageGeneratorService()
    generated_base64 = await image_gen.generate_from_prompt(prompt)
    
    image_bytes = base64.b64decode(generated_base64)
    image_bytes = force_resolution(image_bytes)
    
    watermark_service = WatermarkService()
    image_bytes = await watermark_service.apply(image_bytes, profile.get("logo_url"), user_id)
    
    storage = StorageService()
    upload_base64 = base64.b64encode(image_bytes).decode("utf-8")
    public_url = await storage.upload_image(upload_base64, user_id)
    
    # 5. Update DB
    updated_urls = list(original_urls)
    updated_urls[slide_idx] = public_url
    
    try:
        supabase.table("requests_log").update({"media_urls": updated_urls}).eq("id", request.Row_ID).execute()
    except Exception as e:
        logger.error(f"Failed to update requests_log: {e}")
    
    return AiCarouselGenerateResponse(
        reply="AI slide fixed successfully",
        caption="",
        media_urls=updated_urls,
        message_id=request.message_id,
        is_fix=True,
        slide_types=slide_types,
    )


# ── SSE Streaming endpoint ──────────────────────────────────────────────────
from fastapi.responses import StreamingResponse
import json


@router.post("/generate/stream")
async def generate_ai_carousel_stream(
    request: GenerateAiCarouselRequest,
    user: dict = Depends(get_current_user),
):
    """Generate AI carousel with SSE streaming — each slide appears as it's ready."""
    user_id = user["id"]
    settings = get_settings()

    async def event_stream():
        # 1. Credits + Brand + Strategy
        credits_service = CreditsService()
        await credits_service.check_credits(user_id)

        brand_service = BrandService()
        profile = await brand_service.load_profile(user_id)

        strategy = ContentStrategyService()

        if request.slides:
            from app.models.ai_carousel import AiContentPlan
            plan_slides = []
            for s in request.slides:
                plan_slides.append(AiSlideContent(
                    number=s.number,
                    slide_type=s.slide_type,
                    text=s.text or f"Slide {s.number}",
                    text_position=s.text_position or "Bottom Center",
                    visual_prompt=profile.get("visual_environment_setup", "") if s.slide_type in (SlideType.GENERIC, SlideType.FACE) else "",
                ))
            content_plan = AiContentPlan(
                slides=plan_slides,
                reply="Your AI carousel is ready!",
                caption="",
                reasoning="User-directed slides",
            )
        else:
            content_plan = await strategy.plan_ai(
                message=request.message,
                brand_profile=profile,
                slide_count=request.slide_count,
            )

        yield f"data: {json.dumps({'type': 'plan', 'reply': content_plan.reply, 'caption': content_plan.caption, 'total_slides': len(content_plan.slides), 'slide_types': [s.slide_type.value for s in content_plan.slides]})}\n\n"

        # 2. Generate slides sequentially and stream each one
        image_gen = ImageGeneratorService()
        watermark_service = WatermarkService()
        storage = StorageService()
        media_urls: list[str] = []
        slide_types: list[str] = []
        prompts_used: list[str] = []

        for slide in content_plan.slides:
            try:
                if slide.slide_type in (SlideType.GENERIC, SlideType.FACE):
                    prompt = build_generic_slide_prompt(
                        visual_prompt=slide.visual_prompt,
                        text=slide.text,
                        text_position=slide.text_position,
                        font_prompt=profile.get("font_prompt", "Clean, bold, geometric sans-serif"),
                        font_style=profile.get("font_style", "bold"),
                        font_size=profile.get("font_size", "38px"),
                        color_primary=profile.get("brand_color_primary", "#000000"),
                        color_secondary=profile.get("brand_color_secondary", "#FFFFFF"),
                        subject_description=profile.get("visual_subject_outfit_generic", ""),
                    )
                else:
                    prompt = build_card_slide_prompt(
                        text=slide.text,
                        text_position=slide.text_position or "Center",
                        font_prompt=profile.get("font_prompt", "Clean, bold, geometric sans-serif"),
                        font_style=profile.get("font_style", "bold"),
                        font_size=profile.get("font_size", "42px"),
                        color_primary=profile.get("brand_color_primary", "#000000"),
                        color_secondary=profile.get("brand_color_secondary", "#FFFFFF"),
                    )

                generated_base64 = await image_gen.generate_from_prompt(prompt)
                image_bytes = base64.b64decode(generated_base64)
                image_bytes = force_resolution(image_bytes)

                logo_url = profile.get("logo_url")
                image_bytes = await watermark_service.apply(image_bytes, logo_url, user_id)

                upload_base64 = base64.b64encode(image_bytes).decode("utf-8")
                public_url = await storage.upload_image(upload_base64, user_id)
                media_urls.append(public_url)
                slide_types.append(slide.slide_type.value)
                prompts_used.append(prompt)

                yield f"data: {json.dumps({'type': 'slide', 'number': slide.number, 'url': public_url, 'slide_type': slide.slide_type.value, 'text': slide.text})}\n\n"

            except Exception as e:
                logger.error(f"Stream AI slide {slide.number} ({slide.slide_type}) failed: {e}")
                slide_types.append(slide.slide_type.value)
                prompts_used.append("")
                yield f"data: {json.dumps({'type': 'slide_error', 'number': slide.number, 'error': str(e)})}\n\n"

        # 3. Save to DB + increment credits
        supabase = get_supabase_admin()
        try:
            supabase.table("requests_log").upsert({
                "id": request.message_id,
                "user_id": user_id,
                "agent_type": "ai-carousel",
                "title": "AI Generated Carousel",
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
