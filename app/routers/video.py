"""P3 Real Video — generation endpoint."""

import asyncio
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
from app.services.transcription_service import TranscriptionService
from app.services.video_analysis import VideoAnalysisService
from app.templates.creatomate_mappings import TEMPLATE_MAPPERS, ANALYSIS_MAPPERS
import inspect
import os
from app.templates.brand_theme import resolve_theme
from app.templates.renderscript_builders import RENDERSCRIPT_BUILDERS

logger = logging.getLogger(__name__)


def _trim_black_tail(source_dict: dict, phrase_blocks=None) -> dict:
    """Cap source duration at actual content end to avoid black tail padding."""
    current_dur = float(source_dict.get("duration", 0))
    if phrase_blocks:
        content_end = phrase_blocks[-1].end + 0.5
    else:
        elements = source_dict.get("elements", [])
        ends = [
            float(el.get("time", 0)) + float(el.get("duration", 0))
            for el in elements
            if el.get("type") in ("video", "audio") and el.get("duration", 0) > 0
        ]
        content_end = max(ends) if ends else current_dur
    if content_end < current_dur:
        source_dict["duration"] = round(content_end, 3)
    return source_dict


def _should_use_renderscript(template_key: str) -> bool:
    """Check RENDERSCRIPT_TEMPLATES env var to decide render path."""
    flag = os.getenv("RENDERSCRIPT_TEMPLATES", "").strip().lower()
    if not flag:
        return False
    if flag == "all":
        return True
    return template_key in {k.strip() for k in flag.split(",")}


def _should_force_renderscript(template_enum: VideoTemplate) -> bool:
    return template_enum in set(VideoTemplate)


def _required_video_count(template_enum: VideoTemplate) -> int:
    return int(TEMPLATE_CONFIG[template_enum].get("required_videos", 1))


def _validate_video_urls(template_enum: VideoTemplate, video_urls: list[str]) -> None:
    required_videos = _required_video_count(template_enum)
    if len(video_urls) < required_videos:
        raise AgentAPIError(
            message=(
                f"Template '{template_enum.value}' requires {required_videos} video(s), "
                f"but only {len(video_urls)} provided."
            ),
            code="MISSING_VIDEO_URLS",
            status_code=422,
            details={"required_videos": required_videos, "provided_videos": len(video_urls)},
        )

router = APIRouter(prefix="/video", tags=["video"])

_STREAM_TIMEOUT = httpx.Timeout(connect=30.0, read=300.0, write=300.0, pool=30.0)


async def _stream_video_to_storage(
    video_url: str,
    upload_url: str,
    service_key: str,
) -> None:
    """Stream video from Creatomate CDN directly to Supabase — no full-file buffering."""
    async with httpx.AsyncClient(timeout=_STREAM_TIMEOUT) as dl_client:
        async with dl_client.stream("GET", video_url) as dl_resp:
            dl_resp.raise_for_status()
            upload_headers: dict[str, str] = {
                "Authorization": f"Bearer {service_key}",
                "apikey": service_key,
                "Content-Type": "video/mp4",
                "x-upsert": "true",
            }
            content_length = dl_resp.headers.get("content-length")
            if content_length:
                upload_headers["Content-Length"] = content_length

            async with httpx.AsyncClient(timeout=_STREAM_TIMEOUT) as ul_client:
                upload_response = await ul_client.post(
                    upload_url,
                    content=dl_resp.aiter_bytes(),
                    headers=upload_headers,
                )
                upload_response.raise_for_status()


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

    _validate_video_urls(template_enum, request.video_urls)

    # ---- Check credits ----------------------------------------------------
    credits_service = CreditsService()
    await credits_service.check_credits(user_id)

    # ---- Load brand profile -----------------------------------------------
    brand_service = BrandService()
    profile = await brand_service.load_profile(user_id)

    effective_video_urls = request.video_urls

    theme = resolve_theme(profile, getattr(request, "music_track", None),
                          music_volume=getattr(request, "music_volume", 40.0) or 40.0)
    request.logo_url = profile.get("logo_url")
    request.brand_settings = {
        "font_family": theme.font_family if theme else None,
        "primary_color": theme.primary_color if theme else None,
        "logo_url": profile.get("logo_url"),
        "music_url": getattr(request, "music_track", None),
    }

    # ---- Video analysis (templates with needs_analysis: True) ---------------
    analysis_result = None
    phrase_blocks = []
    needs_analysis = config.get("needs_analysis", False)

    # Only transcribe for Talking Head — B-roll templates must not caption their own audio
    if request.enable_captions and effective_video_urls and template_enum == VideoTemplate.TALKING_HEAD:
        # OpusClip subtitle pipeline: transcribe speech → phrase blocks
        phrase_blocks = await TranscriptionService().transcribe(effective_video_urls[0])

    if needs_analysis and effective_video_urls:
        analysis_service = VideoAnalysisService()
        if template_enum == VideoTemplate.VIRAL_REACTION:
            analysis_result = await analysis_service.analyze_for_viral_reaction(
                effective_video_urls[0],
            )
        elif template_enum == VideoTemplate.TESTIMONIAL_STORY:
            analysis_result = await analysis_service.analyze_for_testimonial(
                effective_video_urls[0],
            )
        elif template_enum == VideoTemplate.TALKING_HEAD and not phrase_blocks:
            # Only run legacy Gemini analysis when captions pipeline didn't run
            analysis_result = await analysis_service.analyze_for_talking_head(
                effective_video_urls[0],
            )

    # ---- Render via Creatomate (renderscript path first) ------------------
    creatomate = CreatomateService()
    render_id = None
    if _should_use_renderscript(request.template) or _should_force_renderscript(template_enum):
        builder = RENDERSCRIPT_BUILDERS.get(template_enum)
        if builder:
            _bkw = (
                {"phrase_blocks": phrase_blocks or None}
                if "phrase_blocks" in inspect.signature(builder).parameters
                else {}
            )
            source_dict = builder(request, theme, analysis_result, **_bkw)
            _trim_black_tail(source_dict, phrase_blocks or None)
            logger.info("creatomate render source (truncated): template=%s audio_elements=%s",
                request.template,
                [e for e in source_dict.get('elements', []) if e.get('type') == 'audio']
            )
            render_id = await creatomate.render_with_source(source_dict)

    # ---- Build modifications via template mappers (legacy fallback) -------
    if render_id is None:
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

    # ---- Upload to Supabase Storage (stream — no full-file buffering) --------
    storage = StorageService()
    storage_path = (
        f"generated/{user_id}/{int(time.time())}-{uuid.uuid4().hex[:8]}.mp4"
    )
    upload_url = (
        f"{storage.supabase_url}/storage/v1/object/"
        f"{storage.bucket}/{storage_path}"
    )

    await _stream_video_to_storage(video_url, upload_url, storage.service_key)

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

            _validate_video_urls(template_enum, request.video_urls)

            # ---- Video URLs already validated; no inline trim step ---------
            effective_video_urls = request.video_urls

            # ---- Video analysis (templates with needs_analysis: True) --------
            analysis_result = None
            phrase_blocks = []
            needs_analysis = config.get("needs_analysis", False)

            # Only transcribe for Talking Head — B-roll templates must not caption their own audio
            if request.enable_captions and effective_video_urls and template_enum == VideoTemplate.TALKING_HEAD:
                yield f'data: {json.dumps({"type": "progress", "phase": "transcribing", "message": "Transcribing audio for captions..."})}\n\n'
                # Run transcription concurrently and send SSE keepalives every 8s so
                # browsers / network proxies don't close the idle stream (Files API
                # upload + polling can take 60-180s with no output otherwise).
                _transcription_task = asyncio.create_task(
                    TranscriptionService().transcribe(effective_video_urls[0])
                )
                while not _transcription_task.done():
                    try:
                        await asyncio.wait_for(asyncio.shield(_transcription_task), timeout=8.0)
                    except asyncio.TimeoutError:
                        yield ': keepalive\n\n'
                phrase_blocks = await _transcription_task
                logger.info("generate-stream: transcription returned %d phrase blocks for template %s", len(phrase_blocks), request.template)

            if needs_analysis and effective_video_urls:
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
                elif template_enum == VideoTemplate.TALKING_HEAD and not phrase_blocks:
                    analysis_result = await analysis_service.analyze_for_talking_head(
                        effective_video_urls[0],
                    )

            # ---- RenderScript path (feature-flagged) --------------------------
            creatomate = CreatomateService()
            render_id = None
            theme = resolve_theme(profile, getattr(request, 'music_track', None),
                                  music_volume=getattr(request, 'music_volume', 40.0) or 40.0)
            logger.info(
                "generate-stream: template=%s music_track=%r music_url=%r",
                request.template, getattr(request, 'music_track', None), theme.music_url,
            )
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
                    _bkw = (
                        {"phrase_blocks": phrase_blocks or None}
                        if "phrase_blocks" in inspect.signature(builder).parameters
                        else {}
                    )
                    source_dict = builder(request, theme, analysis_result, **_bkw)
                    _trim_black_tail(source_dict, phrase_blocks or None)
                    logger.info("creatomate render source (truncated): template=%s audio_elements=%s",
                        request.template,
                        [e for e in source_dict.get('elements', []) if e.get('type') == 'audio']
                    )
                    render_id = await creatomate.render_with_source(source_dict)

            # ---- Build modifications via template mappers (legacy path) -------
            # Only needed when render_id was not already set by the renderscript path
            if render_id is None:
                if template_enum in ANALYSIS_MAPPERS and analysis_result:
                    mapper = ANALYSIS_MAPPERS[template_enum]
                    modifications, extra_params = mapper(request, analysis_result)
                elif template_enum in TEMPLATE_MAPPERS:
                    mapper = TEMPLATE_MAPPERS[template_enum]
                    modifications, extra_params = mapper(request)
                else:
                    yield f'data: {json.dumps({"type": "error", "message": f"No mapper for template: {request.template}", "code": "INTERNAL_ERROR"})}\n\n'
                    return

                # ---- Render via Creatomate (legacy mapper path) ----------------
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

            # ---- Build storage path ----------------------------------------
            video_url = final_status.get("url")
            if not video_url:
                yield f'data: {json.dumps({"type": "error", "message": "Render succeeded but no URL returned", "code": "RENDER_FAILED"})}\n\n'
                return

            storage = StorageService()
            storage_path = (
                f"generated/{user_id}/{int(time.time())}-{uuid.uuid4().hex[:8]}.mp4"
            )
            upload_url = (
                f"{storage.supabase_url}/storage/v1/object/"
                f"{storage.bucket}/{storage_path}"
            )

            # ---- Stream Creatomate → Supabase (keepalive SSE while uploading) --
            # asyncio.create_task lets us emit progress events while the transfer runs.
            upload_task = asyncio.create_task(
                _stream_video_to_storage(video_url, upload_url, storage.service_key)
            )
            elapsed_upload = 0
            while not upload_task.done():
                await asyncio.sleep(5)
                elapsed_upload += 5
                yield f'data: {json.dumps({"type": "progress", "phase": "uploading", "elapsed_seconds": elapsed_upload, "message": f"Uploading video... ({elapsed_upload}s)"})}\n\n'

            # Re-raises if the task threw (timeout, HTTP error, etc.)
            await upload_task

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
