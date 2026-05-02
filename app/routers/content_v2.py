"""Content REST API v2 — Batch 2b.

New content endpoints using core infrastructure (auth, responses, pagination, exceptions).
Operates on the requests_log table. Coexists with legacy content.py router.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone as dt_timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.core.auth import UserContext, get_current_user
from app.core.pagination import PaginationParams, pagination_params
from app.core.responses import success, paginated
from app.core.exceptions import ValidationError, ExternalServiceError
from app.core.supabase_client import get_service_client
from app.config import get_settings
from app.services.blotato import build_blotato_connections, agent_type_to_media_type
from app.services.blotato_client import BlotatoAPIError, BlotatoClient
from app.services.blotato_publisher import (
    publish_content as blotato_publish,
    reschedule_all_platforms,
    cancel_all_platforms,
    validate_connections,
    derive_publish_status,
)
from app.services.content_crud import ContentCRUD
from app.services.publish_audit import log_attempt as audit_log_attempt

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/content", tags=["content-v2"])


def _load_blotato_connections_for_user(profile: dict) -> dict | None:
    """Return the user's admin-assigned Blotato connections.

    Connections are admin-controlled — never auto-imported from the master
    Blotato account. Auto-import was removed to prevent accounts from being
    silently re-attached after admin unassignment.
    """
    return build_blotato_connections(profile) or None


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class CreateContentRequest(BaseModel):
    id: Optional[str] = Field(None, description="Client-generated content ID")
    agent_type: str = Field(..., description="Agent type that generated this content")
    title: Optional[str] = Field(None, max_length=500)
    caption: Optional[str] = Field(None)
    reply: Optional[str] = Field(None, description="Full AI reply text")
    media_urls: Optional[list[str]] = Field(None, description="Generated media URLs")
    reel_category: Optional[str] = Field(None, max_length=100)
    metadata: Optional[dict[str, object]] = Field(None, description="Additional metadata")


class UpdateContentV2Request(BaseModel):
    title: Optional[str] = Field(None, max_length=500)
    caption: Optional[str] = Field(None)
    published: Optional[bool] = Field(None, description="Publish status")
    scheduled_date: Optional[str] = Field(None, description="ISO datetime for scheduling")


class ScheduleContentRequest(BaseModel):
    scheduled_date: str = Field(..., description="ISO datetime string for scheduling")
    timezone: str = Field("UTC", description="User's timezone")
    caption: Optional[str] = Field(None)


class RescheduleRequest(BaseModel):
    scheduled_date: str = Field(..., description="New ISO datetime string")
    timezone: Optional[str] = Field(None, description="User's IANA timezone (e.g. America/Los_Angeles)")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/calendar")
async def content_calendar(
    date_from: Optional[str] = Query(None, description="Start date (ISO) — alias: start_date"),
    date_to: Optional[str] = Query(None, description="End date (ISO) — alias: end_date"),
    start_date: Optional[str] = Query(None, description="Start date (ISO) — alias for date_from"),
    end_date: Optional[str] = Query(None, description="End date (ISO) — alias for date_to"),
    agent_type: Optional[str] = Query(None, description="Filter by agent type"),
    user: UserContext = Depends(get_current_user),
):
    """Calendar view: flat list of scheduled content ordered by scheduled_date."""
    crud = ContentCRUD()
    data = crud.get_calendar(
        user_id=user.user_id,
        date_from=date_from,
        date_to=date_to,
        start_date=start_date,
        end_date=end_date,
        agent_type=agent_type,
    )
    return success(data)


@router.get("/usage")
async def content_usage(
    user: UserContext = Depends(get_current_user),
):
    """User usage stats: credits used, total generated, by agent type."""
    crud = ContentCRUD()
    data = crud.get_usage(user_id=user.user_id)
    return success(data)


@router.get("/grid")
async def list_content_grid(
    agent_type: Optional[str] = Query(None, description="Filter by agent type"),
    status: Optional[str] = Query(None, pattern="^(draft|published|scheduled)$", description="Filter by status"),
    date_from: Optional[str] = Query(None, description="Start date (ISO)"),
    date_to: Optional[str] = Query(None, description="End date (ISO)"),
    pag: PaginationParams = Depends(pagination_params),
    user: UserContext = Depends(get_current_user),
):
    """Paginated content grid with filters (agent_type, status, date range)."""
    crud = ContentCRUD()
    items, total = crud.list_content(
        user_id=user.user_id,
        agent_type=agent_type,
        status=status,
        date_from=date_from,
        date_to=date_to,
        limit=pag.limit,
        offset=pag.offset,
        sort_by=pag.sort_by,
        order=pag.order,
    )
    return paginated(items, total, pag.page, pag.limit)


@router.get("/detail/{content_id}")
async def get_content_detail(
    content_id: str,
    user: UserContext = Depends(get_current_user),
):
    """Get single content item by ID."""
    crud = ContentCRUD()
    item = crud.get_content(content_id, user.user_id)
    return success(item)


@router.post("/new", status_code=201)
async def create_content(
    body: CreateContentRequest,
    user: UserContext = Depends(get_current_user),
):
    """Save new content/asset from generation results."""
    crud = ContentCRUD()
    item = crud.create_content(
        user_id=user.user_id,
        content_id=body.id,
        agent_type=body.agent_type,
        title=body.title,
        caption=body.caption,
        reply=body.reply,
        media_urls=body.media_urls,
        reel_category=body.reel_category,
        metadata=body.metadata,
    )
    return success(item)


@router.patch("/detail/{content_id}")
async def update_content_detail(
    content_id: str,
    body: UpdateContentV2Request,
    user: UserContext = Depends(get_current_user),
):
    """Update content: publish status, schedule date, caption, title."""
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise ValidationError("No fields provided for update")
    crud = ContentCRUD()
    item = crud.update_content(content_id, user.user_id, updates)
    return success(item)


@router.delete("/detail/{content_id}")
async def delete_content_detail(
    content_id: str,
    user: UserContext = Depends(get_current_user),
):
    """Delete content item and associated storage files.

    Cancels any scheduled Blotato posts before deleting (best-effort).
    """
    settings = get_settings()
    crud = ContentCRUD()
    content = crud.get_content(content_id, user.user_id)

    blotato_post_ids: dict = content.get("blotato_post_ids") or {}
    is_scheduled = content.get("published") and content.get("scheduled_date")
    if blotato_post_ids and is_scheduled and settings.blotato_api_key:
        blotato = BlotatoClient(
            api_key=settings.blotato_api_key,
            max_retries=settings.blotato_max_retries,
        )
        try:
            await cancel_all_platforms(client=blotato, blotato_post_ids=blotato_post_ids)
        except BlotatoAPIError as exc:
            logger.warning("Blotato cancel failed for %s: %s", content_id, exc)
            try:
                db = get_service_client()
                db.table("pending_cancellations").insert({
                    "content_id": content_id,
                    "user_id": str(user.user_id),
                    "blotato_schedule_ids": blotato_post_ids,
                    "last_error": str(exc),
                }).execute()
            except Exception as insert_exc:
                logger.error("Failed to insert pending_cancellation for %s: %s", content_id, insert_exc)
        finally:
            await blotato.aclose()

    crud.delete_content(content_id, user.user_id)
    return success({"deleted": True})


@router.patch("/{content_id}/pause")
async def pause_content(
    content_id: str,
    user: UserContext = Depends(get_current_user),
):
    """Pause a scheduled publication by cancelling Blotato and clearing schedule state."""
    settings = get_settings()
    crud = ContentCRUD()
    content = crud.get_content(content_id, user.user_id)

    blotato_post_ids: dict = content.get("blotato_post_ids") or {}
    if blotato_post_ids and content.get("scheduled_date") and settings.blotato_api_key:
        blotato = BlotatoClient(
            api_key=settings.blotato_api_key,
            max_retries=settings.blotato_max_retries,
        )
        try:
            await cancel_all_platforms(client=blotato, blotato_post_ids=blotato_post_ids)
        except BlotatoAPIError as exc:
            logger.warning("Blotato pause cancel failed for %s: %s", content_id, exc)
        finally:
            await blotato.aclose()

    updates = {
        "published": False,
        "scheduled_date": None,
        "publish_status": None,
        "publish_error": None,
        "blotato_post_ids": {},
    }
    updated = crud.update_content(content_id, user.user_id, updates)
    return success(updated)

async def _do_schedule_background(
    content_id: str,
    user_id: str,
    media_urls: list,
    caption: str,
    connections: dict,
    scheduled_date: str,
    timezone: str,
    media_type: str,
    settings,
    update_caption: bool,
    original_caption: str | None,
) -> None:
    """Background task: call Blotato, then update the DB record."""
    crud = ContentCRUD()
    blotato = BlotatoClient(
        api_key=settings.blotato_api_key,
        max_retries=settings.blotato_max_retries,
    )
    try:
        valid_connections, stale_platforms = await validate_connections(blotato, connections)
        if not valid_connections:
            raise ValueError(f"All connected accounts are stale: {stale_platforms}")

        post_ids = await blotato_publish(
            client=blotato,
            media_urls=media_urls,
            caption=caption,
            connections=valid_connections,
            scheduled_date=scheduled_date,
            timezone=timezone,
            media_type=media_type,
        )
        overall_status = derive_publish_status(post_ids)
        updates: dict = {
            "published": True,
            "scheduled_date": scheduled_date,
            "blotato_post_ids": post_ids,
            "publish_status": overall_status,
            "publish_error": None,
            "published_at": datetime.now(dt_timezone.utc).isoformat(),
        }
        if update_caption and original_caption is not None:
            updates["caption"] = original_caption
            updates["reply"] = original_caption
        crud.update_content(content_id, user_id, updates)
        for platform, entry in post_ids.items():
            try:
                audit_status = "success" if entry["status"] == "scheduled" else "failed"
                await audit_log_attempt(
                    content_id=content_id, user_id=user_id,
                    action="schedule", platform=platform,
                    status=audit_status, error=entry.get("error"),
                    blotato_post_id=entry.get("id"),
                )
            except Exception:
                pass
    except (ValueError, BlotatoAPIError) as exc:
        error_detail = str(exc)
        logger.error("Background schedule failed content=%s: %s", content_id, error_detail)
        try:
            crud.update_content(content_id, user_id, {
                "publish_status": "failed",
                "publish_error": error_detail,
            })
        except Exception:
            pass
        try:
            await audit_log_attempt(
                content_id=content_id, user_id=user_id,
                action="schedule", platform="all",
                status="failed", error=error_detail,
            )
        except Exception:
            pass
    finally:
        await blotato.aclose()


@router.post("/{content_id}/schedule")
async def schedule_content(
    content_id: str,
    body: ScheduleContentRequest,
    user: UserContext = Depends(get_current_user),
):
    """Schedule content for publishing via Blotato API.

    Calls Blotato synchronously and returns the updated content record.
    """
    settings = get_settings()
    if not settings.blotato_api_key:
        raise ExternalServiceError("blotato", "BLOTATO_API_KEY is not configured")

    crud = ContentCRUD()
    content = crud.get_content(content_id, user.user_id)

    # Idempotency: same date + already fully scheduled → return early
    if (
        content.get("published") is True
        and content.get("publish_status") == "scheduled"
        and content.get("scheduled_date") == body.scheduled_date
    ):
        result = dict(content)
        result["idempotent"] = True
        return success(result)

    admin = get_service_client()
    profile_result = (
        admin.table("profiles")
        .select("blotato_connections, timezone")
        .eq("id", user.user_id)
        .maybe_single()
        .execute()
    )
    raw_profile = profile_result.data if profile_result else None
    profile: dict = raw_profile if isinstance(raw_profile, dict) else {}
    blotato_connections = _load_blotato_connections_for_user(profile)

    if not blotato_connections:
        raise ValidationError(
            "No social media account connected. Go to Settings → Social Accounts to connect Instagram or Facebook."
        )

    content_agent_type = content.get("agent_type", "")
    media_type = agent_type_to_media_type(content_agent_type)
    caption = body.caption or content.get("reply", "")
    timezone = profile.get("timezone") or body.timezone or "UTC"
    logger.warning(
        "SCHEDULE DEBUG content=%s profile_tz=%r body_tz=%r resolved_tz=%r scheduled_date=%r",
        content_id, profile.get("timezone"), body.timezone, timezone, body.scheduled_date,
    )

    blotato = BlotatoClient(
        api_key=settings.blotato_api_key,
        max_retries=settings.blotato_max_retries,
    )
    try:
        valid_connections, stale_platforms = await validate_connections(blotato, blotato_connections)

        if not valid_connections:
            imported = _load_blotato_connections_for_user(profile)
            if imported and imported != blotato_connections:
                valid_connections, stale_platforms = await validate_connections(blotato, imported)

        publish_connections = valid_connections or blotato_connections
        if not publish_connections:
            raise ValidationError(
                "No social media account connected. Go to Settings → Social Accounts to connect Instagram or Facebook."
            )

        post_ids = await blotato_publish(
            client=blotato,
            media_urls=content.get("media_urls") or [],
            caption=caption,
            connections=publish_connections,
            scheduled_date=body.scheduled_date,
            timezone=timezone,
            media_type=media_type,
        )
    except BlotatoAPIError as exc:
        error_detail = str(exc)
        logger.error(
            "Blotato schedule failed for content=%s user=%s: %s",
            content_id, user.user_id, error_detail,
        )
        raise ExternalServiceError("blotato", error_detail)
    finally:
        await blotato.aclose()

    overall_status = derive_publish_status(post_ids)
    updates: dict = {
        "published": True,
        "scheduled_date": body.scheduled_date,
        "blotato_post_ids": post_ids,
        "publish_status": overall_status,
        "publish_error": None,
        "published_at": datetime.now(dt_timezone.utc).isoformat(),
    }
    if body.caption is not None:
        updates["caption"] = body.caption
        updates["reply"] = body.caption
    updated = crud.update_content(content_id, user.user_id, updates)

    for platform, entry in post_ids.items():
        try:
            audit_status = "success" if entry["status"] == "scheduled" else "failed"
            await audit_log_attempt(
                content_id=content_id, user_id=str(user.user_id),
                action="schedule", platform=platform,
                status=audit_status, error=entry.get("error"),
                blotato_post_id=entry.get("id"),
            )
        except Exception:
            pass

    warnings: list[str] = [
        f"{p} account is stale and was skipped. Go to Settings to reconnect."
        for p in stale_platforms
    ]
    return success(updated, warnings=warnings or None)


@router.post("/{content_id}/republish")
async def republish_content(
    content_id: str,
    user: UserContext = Depends(get_current_user),
):
    """Retry publishing for failed or partially failed content.

    Identifies platforms with status='failed' in blotato_post_ids and retries
    only those. Merges new results and re-derives overall publish_status.
    """
    settings = get_settings()
    if not settings.blotato_api_key:
        raise ExternalServiceError("blotato", "BLOTATO_API_KEY is not configured")

    crud = ContentCRUD()
    content = crud.get_content(content_id, user.user_id)

    publish_status = content.get("publish_status")
    if publish_status not in ("failed", "partial"):
        if publish_status == "scheduled":
            raise ValidationError("Content is already scheduled")
        raise ValidationError("No failed platforms to retry")

    admin = get_service_client()
    profile_result = (
        admin.table("profiles")
        .select("blotato_connections, timezone")
        .eq("id", user.user_id)
        .maybe_single()
        .execute()
    )
    raw_profile = profile_result.data if profile_result else None
    profile: dict = raw_profile if isinstance(raw_profile, dict) else {}
    blotato_connections = _load_blotato_connections_for_user(profile)

    if not blotato_connections:
        raise ValidationError(
            "No social media account connected. Go to Settings → Social Accounts to connect Instagram or Facebook."
        )

    existing: dict = content.get("blotato_post_ids") or {}

    # Filter to only platforms that failed or are missing from existing results
    failed_connections = {
        platform: conn
        for platform, conn in blotato_connections.items()
        if existing.get(platform, {}).get("status") != "scheduled"
    }

    publish_connections = failed_connections or blotato_connections
    if not publish_connections:
        raise ValidationError("No failed platforms to retry")

    content_agent_type = content.get("agent_type", "")
    media_type = agent_type_to_media_type(content_agent_type)
    caption = content.get("reply") or ""
    scheduled_date = content.get("scheduled_date") or ""
    timezone = profile.get("timezone") or "UTC"

    blotato = BlotatoClient(
        api_key=settings.blotato_api_key,
        max_retries=settings.blotato_max_retries,
    )
    try:
        new_results = await blotato_publish(
            client=blotato,
            media_urls=content.get("media_urls") or [],
            caption=caption,
            connections=publish_connections,
            scheduled_date=scheduled_date,
            timezone=timezone,
            media_type=media_type,
        )
    except BlotatoAPIError as exc:
        error_detail = str(exc)
        logger.error(
            "Blotato republish failed for content=%s user=%s: %s",
            content_id, user.user_id, error_detail,
        )
        raise ExternalServiceError("blotato", error_detail)
    finally:
        await blotato.aclose()

    for platform, entry in new_results.items():
        try:
            audit_status = "success" if entry["status"] == "scheduled" else "failed"
            await audit_log_attempt(
                content_id=content_id, user_id=user.user_id,
                action="republish", platform=platform,
                status=audit_status, error=entry.get("error"),
                blotato_post_id=entry.get("id"),
            )
        except Exception:
            pass

    merged = {**existing, **new_results}
    updates: dict = {
        "blotato_post_ids": merged,
        "publish_status": derive_publish_status(merged),
        "publish_error": None,
    }
    updated = crud.update_content(content_id, user.user_id, updates)
    return success(updated)


@router.patch("/{content_id}/reschedule")
async def reschedule_content(
    content_id: str,
    body: RescheduleRequest,
    user: UserContext = Depends(get_current_user),
):
    """Update the scheduled_date of an already-scheduled post.

    Calls Blotato to update the schedule if IDs are stored (soft failure — DB is
    source of truth). Always updates scheduled_date in DB.
    """
    settings = get_settings()
    crud = ContentCRUD()
    content = crud.get_content(content_id, user.user_id)

    admin = get_service_client()
    profile_result = (
        admin.table("profiles")
        .select("timezone")
        .eq("id", user.user_id)
        .maybe_single()
        .execute()
    )
    raw_profile = profile_result.data if profile_result else None
    _tz_raw = (raw_profile if isinstance(raw_profile, dict) else {}).get("timezone")
    profile_tz: str = str(_tz_raw) if _tz_raw else (body.timezone or "UTC")
    logger.warning(
        "RESCHEDULE DEBUG content=%s profile_tz=%r body_tz=%r resolved_tz=%r scheduled_date=%r",
        content_id, _tz_raw, body.timezone, profile_tz, body.scheduled_date,
    )

    blotato_post_ids: dict = content.get("blotato_post_ids") or {}
    reschedule_results: dict[str, str | None] = {}
    if blotato_post_ids and settings.blotato_api_key:
        blotato = BlotatoClient(
            api_key=settings.blotato_api_key,
            max_retries=settings.blotato_max_retries,
        )
        try:
            reschedule_results = await reschedule_all_platforms(
                client=blotato,
                blotato_post_ids=blotato_post_ids,
                new_scheduled_date=body.scheduled_date,
                timezone=profile_tz,
            )
        finally:
            await blotato.aclose()

    # Merge reschedule_error into blotato_post_ids entries
    updated_ids = dict(blotato_post_ids)
    for platform, err in reschedule_results.items():
        if platform in updated_ids and isinstance(updated_ids[platform], dict):
            updated_ids[platform] = {**updated_ids[platform], "reschedule_error": err}

    db_updates: dict = {"scheduled_date": body.scheduled_date}
    if updated_ids:
        db_updates["blotato_post_ids"] = updated_ids

    warnings = [
        f"Blotato reschedule failed for {p}: {err}"
        for p, err in reschedule_results.items()
        if err is not None
    ]

    for platform, err in reschedule_results.items():
        try:
            await audit_log_attempt(
                content_id=content_id, user_id=user.user_id,
                action="reschedule", platform=platform,
                status="failed" if err else "success", error=err,
                blotato_post_id=(
                    blotato_post_ids.get(platform, {}).get("id")
                    if isinstance(blotato_post_ids.get(platform), dict)
                    else blotato_post_ids.get(platform)
                ),
            )
        except Exception:
            pass

    updated = crud.update_content(content_id, user.user_id, db_updates)
    return success(updated, warnings=warnings or None)
