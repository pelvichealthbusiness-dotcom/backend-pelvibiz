"""P3 Real Video — generation endpoint."""

import logging
import time
import uuid

import httpx

from fastapi import APIRouter, Depends

from app.dependencies import get_supabase_admin
from app.models.video import (
    GenerateVideoRequest,
    GenerateVideoResponse,
    TEMPLATE_CONFIG,
    VideoTemplate,
)
from app.services.auth import get_current_user
from app.services.brand import BrandService
from app.services.creatomate import CreatomateService
from app.services.credits import CreditsService
from app.services.exceptions import AgentAPIError
from app.services.storage import StorageService
from app.services.video_analysis import VideoAnalysisService
from app.templates.creatomate_mappings import TEMPLATE_MAPPERS, ANALYSIS_MAPPERS
import os
from app.templates.brand_theme import resolve_theme
from app.templates.renderscript_builders import RENDERSCRIPT_BUILDERS

logger = logging.getLogger(__name__)


def _should_use_renderscript(template_key: str) -> bool:
    """Check RENDERSCRIPT_TEMPLATES env var to decide render path."""
    flag = os.getenv("RENDERSCRIPT_TEMPLATES", "").strip().lower()
    if not flag:
        return False
    if flag == "all":
        return True
    return template_key in {k.strip() for k in flag.split(",")}


def _should_force_renderscript(template_enum: VideoTemplate) -> bool:
    return template_enum in {
        VideoTemplate.BRAND_SPOTLIGHT,
        VideoTemplate.SOCIAL_PROOF_STACK,
        VideoTemplate.OFFER_DROP,
    }

router = APIRouter(prefix="/video", tags=["video"])


@router.post("/generate", response_model=GenerateVideoResponse)
async def generate_video(
    request: GenerateVideoRequest,
    user: dict = Depends(get_current_user),
):
    """Generate a video using Creatomate templates."""
    user_id = user["id"]

    # ---- Validate template ------------------------------------------------
    try:
        template_enum = VideoTemplate(request.template)
    except ValueError:
        raise AgentAPIError(
            message=f"Invalid template: {request.template}",
            code="INVALID_TEMPLATE",
            status_code=400,
            details={"valid_templates": [t.value for t in VideoTemplate]},
        )

    config = TEMPLATE_CONFIG[template_enum]
    template_id = config["creatomate_id"]

    # ---- Check credits ----------------------------------------------------
    credits_service = CreditsService()
    await credits_service.check_credits(user_id)

    # ---- Load brand profile -----------------------------------------------
    brand_service = BrandService()
    profile = await brand_service.load_profile(user_id)

    # ---- Video analysis for T3/T4 -----------------------------------------
    analysis_result = None
    if template_enum in ANALYSIS_MAPPERS and request.video_urls:
        analysis_service = VideoAnalysisService()
        if template_enum == VideoTemplate.VIRAL_REACTION:
            analysis_result = await analysis_service.analyze_for_viral_reaction(
                request.video_urls[0],
            )
        elif template_enum == VideoTemplate.TESTIMONIAL_STORY:
            analysis_result = await analysis_service.analyze_for_testimonial(
                request.video_urls[0],
            )

    # ---- Build modifications via template mappers -------------------------
    if template_enum in ANALYSIS_MAPPERS and analysis_result:
        mapper = ANALYSIS_MAPPERS[template_enum]
        modifications, extra_params = mapper(request, analysis_result)
    elif template_enum in TEMPLATE_MAPPERS:
        mapper = TEMPLATE_MAPPERS[template_enum]
        modifications, extra_params = mapper(request)
    else:
        raise AgentAPIError(
            message=f"No mapper for template: {request.template}",
            code="INTERNAL_ERROR",
            status_code=500,
        )

    # ---- Render via Creatomate --------------------------------------------
    creatomate = CreatomateService()
    if "source" in modifications:
        render_id = await creatomate.render_with_source(modifications["source"], **extra_params)
    else:
        render_id = await creatomate.render(template_id, modifications, **extra_params)

    # ---- Poll for completion ----------------------------------------------
    final_status = await creatomate.poll_status(render_id)

    if final_status.status != "succeeded":
        raise AgentAPIError(
            message=f"Render failed: {final_status.error_message or 'unknown'}",
            code="RENDER_FAILED",
            status_code=502,
        )

    # ---- Download rendered video ------------------------------------------
    video_url = final_status.url
    if not video_url:
        raise AgentAPIError(
            message="Render succeeded but no URL returned",
            code="RENDER_FAILED",
            status_code=502,
        )

    video_bytes = await creatomate.download_video(video_url)

    # ---- Upload to Supabase Storage ---------------------------------------
    storage = StorageService()
    storage_path = (
        f"generated/{user_id}/{int(time.time())}-{uuid.uuid4().hex[:8]}.mp4"
    )
    upload_url = (
        f"{storage.supabase_url}/storage/v1/object/"
        f"{storage.bucket}/{storage_path}"
    )

    async with httpx.AsyncClient(timeout=60) as client:
        upload_response = await client.post(
            upload_url,
            content=video_bytes,
            headers={
                "Authorization": f"Bearer {storage.service_key}",
                "apikey": storage.service_key,
                "Content-Type": "video/mp4",
                "x-upsert": "true",
            },
        )
        upload_response.raise_for_status()

    public_url = (
        f"{storage.supabase_url}/storage/v1/object/public/"
        f"{storage.bucket}/{storage_path}"
    )

    # ---- Save to requests_log ---------------------------------------------
    caption_text = request.caption or ""
    reply_text = caption_text or "Your video is ready!"

    supabase = get_supabase_admin()
    try:
        supabase.table("requests_log").upsert(
            {
                "id": request.message_id,
                "user_id": user_id,
                "agent_type": "reels-edited-by-ai",
                "title": f"Video: {request.template}",
                "reply": reply_text,
                "caption": caption_text,
                "media_urls": [public_url],
                "published": False,
                "reel_category": request.template,
            },
            on_conflict="id",
        ).execute()
    except Exception as e:
        logger.error("Failed to save video to requests_log: %s", e)

    # ---- Increment credits ------------------------------------------------
    try:
        await credits_service.increment_credits(user_id)
    except Exception as e:
        logger.error("Failed to increment credits: %s", e)

    # ---- Response ---------------------------------------------------------
    return GenerateVideoResponse(
        reply=reply_text,
        caption=caption_text,
        media_urls=[public_url],
        message_id=request.message_id,
        reel_category=request.template,
        render_duration_ms=int((final_status.render_time or 0) * 1000),
    )


# ---------------------------------------------------------------------------
# SSE streaming endpoint
# ---------------------------------------------------------------------------

import asyncio
import json
from fastapi.responses import StreamingResponse


@router.post("/generate-stream")
async def generate_video_stream(
    request: GenerateVideoRequest,
    user: dict = Depends(get_current_user),
):
    """Generate P3 video with SSE streaming — streams render progress in real time."""
    user_id = user["id"]

    async def event_stream():
        try:
            # ---- Emit: validating ------------------------------------------
            yield f'data: {json.dumps({"type": "progress", "phase": "validating", "message": "Checking credits and brand profile..."})}\n\n'

            # ---- Validate template -----------------------------------------
            try:
                template_enum = VideoTemplate(request.template)
            except ValueError:
                yield f'data: {json.dumps({"type": "error", "message": f"Invalid template: {request.template}", "code": "INVALID_TEMPLATE"})}\n\n'
                return

            config = TEMPLATE_CONFIG[template_enum]
            template_id = config["creatomate_id"]

            # ---- Check credits ---------------------------------------------
            credits_service = CreditsService()
            await credits_service.check_credits(user_id)

            # ---- Load brand profile ----------------------------------------
            brand_service = BrandService()
            profile = await brand_service.load_profile(user_id)

            # ---- Optional trim step --------------------------------------
            effective_video_urls = await _maybe_trim_video_urls(request.video_urls, user_id, request)
            request.video_urls = effective_video_urls

            # ---- Video analysis for T3/T4 ----------------------------------
            analysis_result = None
            if template_enum in ANALYSIS_MAPPERS and effective_video_urls:
                yield f'data: {json.dumps({"type": "progress", "phase": "analyzing", "message": "Analyzing your video with AI..."})}\n\n'
                analysis_service = VideoAnalysisService()
                if template_enum == VideoTemplate.VIRAL_REACTION:
                    analysis_result = await analysis_service.analyze_for_viral_reaction(
                        effective_video_urls[0],
                    )
                elif template_enum == VideoTemplate.TESTIMONIAL_STORY:
                    analysis_result = await analysis_service.analyze_for_testimonial(
                        effective_video_urls[0],
                    )

            # ---- RenderScript path (feature-flagged) --------------------------
            render_id = None
            theme = resolve_theme(profile, getattr(request, 'music_track', None))
            # Load brand info into request for mappers
            request.logo_url = profile.get("logo_url")
            request.brand_settings = {
                "font_family": theme.font_family if theme else None,
                "primary_color": theme.primary_color if theme else None,
                "logo_url": profile.get("logo_url"),
                "music_url": getattr(request, "music_track", None),
            }
            if _should_use_renderscript(request.template) or _should_force_renderscript(template_enum):
                builder = RENDERSCRIPT_BUILDERS.get(template_enum)
                if builder:
                    source_dict = builder(request, theme, analysis_result)
                    creatomate = CreatomateService()
                    render_id = await creatomate.render_with_source(source_dict)

            # ---- Build modifications via template mappers ------------------
            if template_enum in ANALYSIS_MAPPERS and analysis_result:
                mapper = ANALYSIS_MAPPERS[template_enum]
                modifications, extra_params = mapper(request, analysis_result)
            elif template_enum in TEMPLATE_MAPPERS:
                mapper = TEMPLATE_MAPPERS[template_enum]
                modifications, extra_params = mapper(request)
            else:
                yield f'data: {json.dumps({"type": "error", "message": f"No mapper for template: {request.template}", "code": "INTERNAL_ERROR"})}\n\n'
                return

            # ---- Render via Creatomate -------------------------------------
            if render_id is None:
                creatomate = CreatomateService()
            if "source" in modifications:
                render_id = await creatomate.render_with_source(modifications["source"], **extra_params)
            else:
                render_id = await creatomate.render(template_id, modifications, **extra_params)

            # ---- Emit: rendering (initial) ---------------------------------
            yield f'data: {json.dumps({"type": "progress", "phase": "rendering", "elapsed_seconds": 0, "message": "Sending to render pipeline..."})}\n\n'

            # ---- Inline poll loop with progress events ---------------------
            poll_interval = 5  # seconds
            max_wait = 300     # 5 minutes
            elapsed = 0
            final_status = None

            while elapsed < max_wait:
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval

                try:
                    resp = await creatomate._client.get(
                        f"{creatomate._base_url}/renders/{render_id}"
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        status = data.get("status", "unknown")
                        if status == "succeeded":
                            final_status = data
                            break
                        elif status == "failed":
                            error_msg = data.get("error_message", "Unknown render error")
                            yield f'data: {json.dumps({"type": "error", "message": f"Render failed: {error_msg}", "code": "RENDER_FAILED"})}\n\n'
                            return
                except Exception:
                    pass

                # Emit progress every 10s
                if elapsed % 10 == 0:
                    yield f'data: {json.dumps({"type": "progress", "phase": "rendering", "elapsed_seconds": elapsed, "message": f"Rendering your video... ({elapsed}s)"})}\n\n'

            if not final_status:
                yield f'data: {json.dumps({"type": "error", "message": "Video render timed out after 5 minutes", "code": "RENDER_TIMEOUT"})}\n\n'
                return

            # ---- Emit: uploading -------------------------------------------
            yield f'data: {json.dumps({"type": "progress", "phase": "uploading", "message": "Uploading your video..."})}\n\n'

            # ---- Download rendered video -----------------------------------
            video_url = final_status.get("url")
            if not video_url:
                yield f'data: {json.dumps({"type": "error", "message": "Render succeeded but no URL returned", "code": "RENDER_FAILED"})}\n\n'
                return

            video_bytes = await creatomate.download_video(video_url)

            # ---- Upload to Supabase Storage --------------------------------
            storage = StorageService()
            storage_path = (
                f"generated/{user_id}/{int(time.time())}-{uuid.uuid4().hex[:8]}.mp4"
            )
            upload_url = (
                f"{storage.supabase_url}/storage/v1/object/"
                f"{storage.bucket}/{storage_path}"
            )

            async with httpx.AsyncClient(timeout=60) as client:
                upload_response = await client.post(
                    upload_url,
                    content=video_bytes,
                    headers={
                        "Authorization": f"Bearer {storage.service_key}",
                        "apikey": storage.service_key,
                        "Content-Type": "video/mp4",
                        "x-upsert": "true",
                    },
                )
                upload_response.raise_for_status()

            public_url = (
                f"{storage.supabase_url}/storage/v1/object/public/"
                f"{storage.bucket}/{storage_path}"
            )

            # ---- Save to requests_log --------------------------------------
            caption_text = request.caption or ""
            reply_text = caption_text or "Your video is ready!"

            supabase = get_supabase_admin()
            try:
                supabase.table("requests_log").upsert(
                    {
                        "id": request.message_id,
                        "user_id": user_id,
                        "agent_type": "reels-edited-by-ai",
                        "title": f"Video: {request.template}",
                        "reply": reply_text,
                        "caption": caption_text,
                        "media_urls": [public_url],
                        "published": False,
                        "reel_category": request.template,
                    },
                    on_conflict="id",
                ).execute()
            except Exception as e:
                logger.error("Failed to save video to requests_log: %s", e)

            # ---- Increment credits -----------------------------------------
            try:
                await credits_service.increment_credits(user_id)
            except Exception as e:
                logger.error("Failed to increment credits: %s", e)

            # ---- Emit: done ------------------------------------------------
            yield f'data: {json.dumps({"type": "done", "media_urls": [public_url], "reply": reply_text, "caption": caption_text, "message_id": request.message_id})}\n\n'

        except Exception as e:
            logger.error("Video stream error: %s", e, exc_info=True)
            yield f'data: {json.dumps({"type": "error", "message": str(e), "code": "INTERNAL_ERROR"})}\n\n'

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
