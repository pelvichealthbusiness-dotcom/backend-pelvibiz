"""Publish audit service — insert one row per Blotato action attempt."""

from __future__ import annotations

import logging

from app.core.supabase_client import get_service_client

logger = logging.getLogger(__name__)


async def log_attempt(
    *,
    content_id: str,
    user_id: str,
    action: str,
    platform: str,
    status: str,
    error: str | None = None,
    blotato_post_id: str | None = None,
    duration_ms: int | None = None,
) -> None:
    """Insert one row into publish_attempts.

    Never raises — wraps DB call in try/except and logs WARNING on failure.
    Callers are responsible for wrapping in try/except if fire-and-forget pattern is needed.
    """
    try:
        db = get_service_client()
        payload: dict = {
            "content_id": content_id,
            "user_id": user_id,
            "action": action,
            "platform": platform,
            "status": status,
        }
        if error is not None:
            payload["error"] = error
        if blotato_post_id is not None:
            payload["blotato_post_id"] = blotato_post_id
        if duration_ms is not None:
            payload["duration_ms"] = duration_ms
        db.table("publish_attempts").insert(payload).execute()
    except Exception as exc:
        logger.warning("publish_audit.log_attempt failed: %s", exc)
