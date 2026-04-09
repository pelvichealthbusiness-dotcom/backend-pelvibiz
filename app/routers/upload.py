"""File upload endpoints — media & logo uploads to Supabase Storage."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.core.auth import UserContext, get_current_user
from app.core.responses import success, error_response
from app.core.upload import (
    ALLOWED_IMAGE_TYPES,
    ALLOWED_TYPES,
    BUCKET,
    MAX_IMAGE_SIZE,
    validate_upload,
    upload_to_storage,
)
from app.core.supabase_client import get_service_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/upload", tags=["upload"])

MAX_LOGO_SIZE = 5 * 1024 * 1024  # 5 MB


@router.post("/media")
async def upload_media(
    file: UploadFile = File(...),
    agent_type: str = Form(default="general"),
    metadata: str | None = Form(default=None),
    user: UserContext = Depends(get_current_user),
):
    try:
        content, content_type = await validate_upload(file)
    except ValueError as e:
        return error_response("VALIDATION_ERROR", str(e), 422)

    try:
        result = await upload_to_storage(
            content=content,
            content_type=content_type,
            filename=file.filename,
            user_id=user.user_id,
            agent_type=agent_type,
        )
    except RuntimeError as e:
        logger.error("Media upload failed for user %s: %s", user.user_id, e)
        return error_response("UPLOAD_FAILED", str(e), 500)

    return success(
        data={
            "url": result["url"], "public_url": result["url"],
            "path": result["path"],
            "size": result["size"],
        }
    )


@router.post("/logo")
async def upload_logo(
    file: UploadFile = File(...),
    user: UserContext = Depends(get_current_user),
):
    content_type = file.content_type or "application/octet-stream"

    if content_type not in ALLOWED_IMAGE_TYPES:
        allowed = ", ".join(sorted(ALLOWED_IMAGE_TYPES))
        return error_response(
            "VALIDATION_ERROR",
            f"Invalid file type: {content_type}. Allowed: {allowed}",
            422,
        )

    content = await file.read()

    if len(content) > MAX_LOGO_SIZE:
        size_mb = len(content) / (1024 * 1024)
        max_mb = MAX_LOGO_SIZE // (1024 * 1024)
        return error_response(
            "VALIDATION_ERROR",
            f"File too large: {size_mb:.1f}MB. Max: {max_mb}MB",
            422,
        )

    # Determine extension
    ext = "jpg"
    if file.filename and "." in file.filename:
        ext = file.filename.rsplit(".", 1)[-1].lower()
    else:
        ext_map = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
        ext = ext_map.get(content_type, "jpg")

    storage_path = f"logos/{user.user_id}/{uuid.uuid4()}.{ext}"

    client = get_service_client()
    try:
        client.storage.from_(BUCKET).upload(
            path=storage_path,
            file=content,
            file_options={"content-type": content_type, "upsert": "true"},
        )
    except Exception as e:
        logger.error("Logo upload failed for user %s: %s", user.user_id, e)
        return error_response("UPLOAD_FAILED", f"Storage upload failed: {e}", 500)

    public_url = client.storage.from_(BUCKET).get_public_url(storage_path)

    return success(
        data={
            "url": public_url, "public_url": public_url,
            "path": storage_path,
            "size": len(content),
        }
    )


MAX_PDF_SIZE = 10 * 1024 * 1024  # 10 MB
MAX_STORIES_CHARS = 3000


@router.post("/extract-pdf")
async def extract_pdf_text(
    file: UploadFile = File(...),
    user: UserContext = Depends(get_current_user),
):
    """Extract text from a PDF file for use as brand stories context."""
    import pdfplumber
    import io

    if not (file.filename or "").lower().endswith(".pdf") and file.content_type not in (
        "application/pdf", "application/octet-stream"
    ):
        return error_response("INVALID_FILE", "Only PDF files are supported", status_code=400)

    content = await file.read()
    if len(content) > MAX_PDF_SIZE:
        return error_response("FILE_TOO_LARGE", "PDF must be under 10 MB", status_code=400)

    try:
        text_parts: list[str] = []
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text.strip())

        full_text = "\n\n".join(text_parts).strip()
        if not full_text:
            return error_response("NO_TEXT", "Could not extract text from PDF", status_code=422)

        truncated = full_text[:MAX_STORIES_CHARS]
        was_truncated = len(full_text) > MAX_STORIES_CHARS
        return success({"text": truncated, "char_count": len(truncated), "was_truncated": was_truncated})
    except Exception as exc:
        logger.error("PDF extraction failed: %s", exc)
        return error_response("EXTRACTION_FAILED", f"Failed to extract PDF text: {exc}", status_code=500)
