from __future__ import annotations

from fastapi import APIRouter, Depends

from app.models.video_trim import VideoTrimRequest, VideoTrimResponse
from app.services.auth import get_current_user
from app.services.video_trim_service import VideoTrimService

router = APIRouter(prefix='/video-trim', tags=['video-trim'])


@router.post('', response_model=VideoTrimResponse)
async def trim_video(request: VideoTrimRequest, user: dict = Depends(get_current_user)):
    service = VideoTrimService()
    trimmed_url = await service.trim_and_store(
        source_url=str(request.source_url),
        user_id=user['id'],
        start_seconds=request.start_seconds,
        end_seconds=request.end_seconds,
    )
    return VideoTrimResponse(
        source_url=str(request.source_url),
        trimmed_url=trimmed_url,
        template_key=request.template_key,
        mode=request.mode,
        start_seconds=request.start_seconds,
        end_seconds=request.end_seconds,
        duration_seconds=request.end_seconds - request.start_seconds,
    )
