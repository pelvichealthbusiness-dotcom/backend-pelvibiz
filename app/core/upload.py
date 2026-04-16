"""File upload utility — validates and uploads to Supabase Storage."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from fastapi import UploadFile

from app.core.supabase_client import get_service_client

logger = logging.getLogger(__name__)

BUCKET = "chat-media"

# Validation constants
MAX_IMAGE_SIZE = 10 * 1024 * 1024    # 10 MB
MAX_VIDEO_SIZE = 200 * 1024 * 1024   # 200 MB

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_VIDEO_TYPES = {
    "video/mp4", "video/quicktime", "video/webm", "video/x-m4v",
    "video/mpeg", "video/x-msvideo", "video/x-matroska",
}
ALLOWED_TYPES = ALLOWED_IMAGE_TYPES | ALLOWED_VIDEO_TYPES

# Extension → canonical MIME type (used when browser sends application/octet-stream)
_EXT_TO_MIME: dict[str, str] = {
    "mp4": "video/mp4",
    "mov": "video/quicktime",
    "webm": "video/webm",
    "m4v": "video/x-m4v",
    "mpg": "video/mpeg",
    "mpeg": "video/mpeg",
    "avi": "video/x-msvideo",
    "mkv": "video/x-matroska",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}


def _resolve_content_type(declared: str | None, filename: str | None) -> str:
    """
    Resolve the actual content type.
    Falls back to extension-based detection when the browser sends a
    generic type (application/octet-stream or empty).
    """
    if declared and declared not in ("application/octet-stream", "binary/octet-stream"):
        return declared
    if filename and "." in filename:
        ext = filename.rsplit(".", 1)[-1].lower()
        if ext in _EXT_TO_MIME:
            return _EXT_TO_MIME[ext]
    return declared or "application/octet-stream"


def _get_max_size(content_type: str) -> int:
    if content_type in ALLOWED_VIDEO_TYPES:
        return MAX_VIDEO_SIZE
    return MAX_IMAGE_SIZE


def _get_extension(filename: str | None, content_type: str) -> str:
    """Extract extension from filename, fallback to content_type mapping."""
    if filename and "." in filename:
        return filename.rsplit(".", 1)[-1].lower()
    reverse = {v: k for k, v in _EXT_TO_MIME.items()}
    return reverse.get(content_type, "bin")


async def validate_upload(file: UploadFile) -> tuple[bytes, str]:
    """
    Validate file type and size. Returns (content_bytes, resolved_content_type).
    Raises ValueError on invalid input.
    """
    content_type = _resolve_content_type(file.content_type, file.filename)

    if content_type not in ALLOWED_TYPES:
        raise ValueError(
            f"Invalid file type: {content_type}. Allowed: {', '.join(sorted(ALLOWED_TYPES))}"
        )

    content = await file.read()
    max_size = _get_max_size(content_type)

    if len(content) > max_size:
        raise ValueError(
            f"File too large: {len(content) / (1024 * 1024):.1f}MB. Max: {max_size // (1024 * 1024)}MB"
        )

    return content, content_type


async def upload_to_storage(
    content: bytes,
    content_type: str,
    filename: str | None,
    user_id: str,
    agent_type: str = "general",
) -> dict[str, Any]:
    """
    Upload file to Supabase Storage bucket.

    Path format: manual/{user_id}/{agent_type}/{uuid}.{ext}
    Returns dict with url, path, content_type, size.

    The Supabase storage client is synchronous (httpx under the hood).
    We run it in a thread pool to avoid blocking the async event loop,
    which is critical for large video files that take minutes to upload.
    """
    ext = _get_extension(filename, content_type)
    storage_path = f"manual/{user_id}/{agent_type}/{uuid.uuid4()}.{ext}"

    client = get_service_client()

    def _do_upload() -> None:
        client.storage.from_(BUCKET).upload(
            path=storage_path,
            file=content,
            file_options={"content-type": content_type, "upsert": "true"},
        )

    try:
        await asyncio.to_thread(_do_upload)
    except Exception as e:
        logger.error("Storage upload failed for %s: %s", storage_path, e)
        raise RuntimeError(f"Storage upload failed: {e}") from e

    public_url = client.storage.from_(BUCKET).get_public_url(storage_path)

    return {
        "url": public_url,
        "path": storage_path,
        "content_type": content_type,
        "size": len(content),
    }
