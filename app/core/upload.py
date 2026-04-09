"""File upload utility — validates and uploads to Supabase Storage."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import UploadFile

from app.core.supabase_client import get_service_client

logger = logging.getLogger(__name__)

BUCKET = "chat-media"

# Validation constants
MAX_IMAGE_SIZE = 10 * 1024 * 1024    # 10 MB
MAX_VIDEO_SIZE = 100 * 1024 * 1024   # 100 MB

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_VIDEO_TYPES = {"video/mp4", "video/quicktime", "video/webm", "video/x-m4v", "video/mpeg", "video/x-msvideo"}
ALLOWED_TYPES = ALLOWED_IMAGE_TYPES | ALLOWED_VIDEO_TYPES


def _get_max_size(content_type: str) -> int:
    if content_type in ALLOWED_VIDEO_TYPES:
        return MAX_VIDEO_SIZE
    return MAX_IMAGE_SIZE


def _get_extension(filename: str | None, content_type: str) -> str:
    """Extract extension from filename, fallback to content_type mapping."""
    if filename and "." in filename:
        return filename.rsplit(".", 1)[-1].lower()
    # Fallback mapping
    mapping = {
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
        "video/mp4": "mp4",
    }
    return mapping.get(content_type, "bin")


async def validate_upload(file: UploadFile) -> tuple[bytes, str]:
    """
    Validate file type and size. Returns (content_bytes, content_type).
    Raises ValueError on invalid input.
    """
    content_type = file.content_type or "application/octet-stream"

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
    """
    ext = _get_extension(filename, content_type)
    storage_path = f"manual/{user_id}/{agent_type}/{uuid.uuid4()}.{ext}"

    client = get_service_client()

    try:
        client.storage.from_(BUCKET).upload(
            path=storage_path,
            file=content,
            file_options={"content-type": content_type, "upsert": "true"},
        )
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
