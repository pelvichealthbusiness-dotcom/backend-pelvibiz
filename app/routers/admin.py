"""Admin endpoints — user management (CRUD, password, credits) + Blotato sync."""

from __future__ import annotations

from datetime import datetime, timezone as dt_timezone
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, EmailStr, Field

from app.core.auth import UserContext, require_admin
from app.core.pagination import PaginationParams, pagination_params
from app.core.responses import success, paginated, error_response
from app.core.supabase_client import get_service_client
from app.config import get_settings
from app.core.exceptions import ExternalServiceError, NotFoundError
from app.services import admin_service
from app.services import blotato_admin_service
from app.services.blotato_client import BlotatoAPIError, BlotatoClient
from app.services.blotato_publisher import cancel_all_platforms

router = APIRouter(prefix="/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class CreateUserRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = None
    role: str = Field(default="client", pattern="^(admin|client|user)$")
    brand_name: str | None = None


class UpdateUserRequest(BaseModel):
    email: EmailStr | None = None
    full_name: str | None = None
    role: str | None = Field(default=None, pattern="^(admin|client|user)$")
    brand_name: str | None = None
    brand_voice: str | None = None
    target_audience: str | None = None
    services_offered: str | None = None
    credits_limit: int | None = None


class ChangePasswordRequest(BaseModel):
    new_password: str = Field(min_length=8, max_length=128)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/users")
async def list_users(
    pagination: PaginationParams = Depends(pagination_params),
    search: str | None = Query(default=None, description="Search by name or email"),
    admin: UserContext = Depends(require_admin),
):
    """List all users (paginated, searchable). Admin only."""
    result = await admin_service.list_users(
        page=pagination.page,
        limit=pagination.limit,
        offset=pagination.offset,
        sort_by=pagination.sort_by,
        order=pagination.order,
        search=search,
    )
    return paginated(
        data=result["users"],
        total=result["total"],
        page=pagination.page,
        limit=pagination.limit,
    )


@router.post("/users", status_code=201)
async def create_user(
    body: CreateUserRequest,
    admin: UserContext = Depends(require_admin),
):
    """Create a new user (Supabase Auth + profile). Admin only."""
    user = await admin_service.create_user(
        email=body.email,
        password=body.password,
        full_name=body.full_name,
        role=body.role,
        brand_name=body.brand_name,
    )
    return success(data=user)


@router.put("/users/{user_id}")
async def update_user(
    user_id: str,
    body: UpdateUserRequest,
    admin: UserContext = Depends(require_admin),
):
    """Update user profile and/or auth settings. Admin only."""
    update_data = body.model_dump(exclude_unset=True)
    if not update_data:
        return error_response("VALIDATION_ERROR", "No fields to update", 422)

    user = await admin_service.update_user(user_id, update_data)
    return success(data=user)


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    hard: bool = Query(default=False, description="Hard delete (removes auth user too)"),
    admin: UserContext = Depends(require_admin),
):
    """Delete a user. Soft delete by default. Admin only."""
    await admin_service.delete_user(user_id, hard=hard)
    return success(data={"deleted": True, "user_id": user_id, "hard": hard})


@router.post("/users/{user_id}/password")
async def change_password(
    user_id: str,
    body: ChangePasswordRequest,
    admin: UserContext = Depends(require_admin),
):
    """Change a user's password. Admin only."""
    await admin_service.change_password(user_id, body.new_password)
    return success(data={"message": "Password updated successfully"})


@router.post("/users/{user_id}/reset-credits")
async def reset_credits(
    user_id: str,
    admin: UserContext = Depends(require_admin),
):
    """Reset a user's credits_used to 0. Admin only."""
    profile = await admin_service.reset_credits(user_id)
    return success(data=profile)


# ---------------------------------------------------------------------------
# Blotato social accounts sync
# ---------------------------------------------------------------------------

class AssignBlotatoRequest(BaseModel):
    user_id: str
    platform: str = Field(
        description="Platform key: instagram | facebook | linkedin | tiktok | youtube | threads | twitter | bluesky | pinterest"
    )
    account_id: str
    page_id: str | None = None


@router.get("/blotato/accounts")
async def list_blotato_accounts(
    admin: UserContext = Depends(require_admin),
):
    """Fetch all social accounts from the master Blotato account.

    Returns each account enriched with the PelviBiz user it is assigned to
    (if any). Admin only.
    """
    result = await blotato_admin_service.list_accounts_with_assignments()
    return success(data=result)


@router.post("/blotato/assign")
async def assign_blotato_account(
    body: AssignBlotatoRequest,
    admin: UserContext = Depends(require_admin),
):
    """Assign a Blotato social account to a PelviBiz user.

    Writes the platform connection into profiles.blotato_connections JSONB.
    Admin only.
    """
    updated = await blotato_admin_service.assign_account(
        user_id=body.user_id,
        platform=body.platform,
        account_id=body.account_id,
        page_id=body.page_id,
    )
    return success(data=updated)


@router.delete("/blotato/assign/{user_id}/{platform}")
async def unassign_blotato_account(
    user_id: str,
    platform: str,
    admin: UserContext = Depends(require_admin),
):
    """Remove a platform connection from a user's blotato_connections. Admin only."""
    updated = await blotato_admin_service.unassign_account(
        user_id=user_id,
        platform=platform,
    )
    return success(data=updated)


# ---------------------------------------------------------------------------
# Publish logs
# ---------------------------------------------------------------------------

@router.get("/publish-logs")
async def list_publish_logs(
    status: str | None = Query(None, pattern="^(scheduled|failed)$", description="Filter by publish_status"),
    user_id: str | None = Query(None, description="Filter by user"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin: UserContext = Depends(require_admin),
):
    """List content publish attempts with status, error, and user info. Admin only.

    Returns items from requests_log that have a publish_status set, joined with
    the user email from profiles. Ordered by published_at DESC (most recent first).
    """
    db = get_service_client()

    query = (
        db.table("requests_log")
        .select(
            "id, user_id, agent_type, title, caption, media_urls, "
            "scheduled_date, publish_status, publish_error, published_at, "
            "blotato_post_ids, created_at"
        )
        .not_.is_("publish_status", "null")
        .order("published_at", desc=True)
        .limit(limit)
        .offset(offset)
    )

    if status:
        query = query.eq("publish_status", status)
    if user_id:
        query = query.eq("user_id", user_id)

    result = query.execute()
    rows: list = result.data if result else []

    count_query = (
        db.table("requests_log")
        .select("id", count="exact")  # type: ignore[call-arg]
        .not_.is_("publish_status", "null")
    )
    if status:
        count_query = count_query.eq("publish_status", status)
    if user_id:
        count_query = count_query.eq("user_id", user_id)

    count_result = count_query.execute()
    total: int = count_result.count if count_result and count_result.count is not None else len(rows)

    page = (offset // limit) + 1
    return paginated(data=rows, total=total, page=page, limit=limit)


@router.get("/publish-attempts")
async def list_publish_attempts(
    content_id: str = Query(..., description="Content item ID"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin: UserContext = Depends(require_admin),
):
    """List publish_attempts rows for a given content item. Admin only.

    Returns rows ordered by created_at DESC (most recent first), paginated.
    """
    db = get_service_client()
    result = (
        db.table("publish_attempts")
        .select("*")
        .eq("content_id", content_id)
        .order("created_at", desc=True)
        .limit(limit)
        .offset(offset)
        .execute()
    )
    rows = result.data if result else []
    return success(data=rows)


@router.post("/publish-logs/{content_id}/sync-status")
async def sync_publish_status(
    content_id: str,
    admin: UserContext = Depends(require_admin),
):
    """Sync Blotato schedule status for a content item. Admin only.

    Calls GET /schedules/{id} for each platform in blotato_post_ids,
    updates statuses in requests_log, and returns the diff.
    """
    settings = get_settings()
    if not settings.blotato_api_key:
        raise ExternalServiceError("blotato", "BLOTATO_API_KEY not configured")
    try:
        result = await blotato_admin_service.sync_content_publish_status(
            content_id, settings.blotato_api_key
        )
    except KeyError as exc:
        raise NotFoundError(str(exc))
    return success(data=result)


# ---------------------------------------------------------------------------
# Deferred cancel — pending_cancellations
# ---------------------------------------------------------------------------

@router.get("/pending-cancellations")
async def list_pending_cancellations(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin: UserContext = Depends(require_admin),
):
    """List all rows in pending_cancellations. Admin only."""
    db = get_service_client()
    result = (
        db.table("pending_cancellations")
        .select("*")
        .order("created_at", desc=True)
        .limit(limit)
        .offset(offset)
        .execute()
    )
    return success(data=result.data if result else [])


@router.post("/pending-cancellations/retry")
async def retry_pending_cancellations(
    admin: UserContext = Depends(require_admin),
):
    """Retry all pending Blotato cancel operations. Admin only.

    For each row: attempt cancel_all_platforms, delete on success,
    increment retry_count on failure. Runs synchronously.
    """
    settings = get_settings()
    if not settings.blotato_api_key:
        raise ExternalServiceError("blotato", "BLOTATO_API_KEY not configured")

    db = get_service_client()
    rows_result = (
        db.table("pending_cancellations")
        .select("*")
        .order("created_at")
        .limit(100)
        .execute()
    )
    items = rows_result.data if rows_result else []

    succeeded: list[str] = []
    failed: list[dict] = []

    blotato = BlotatoClient(api_key=settings.blotato_api_key, max_retries=2)
    try:
        for item in items:
            try:
                await cancel_all_platforms(
                    client=blotato,
                    blotato_post_ids=item["blotato_schedule_ids"],
                )
                db.table("pending_cancellations").delete().eq("id", item["id"]).execute()
                succeeded.append(item["content_id"])
            except BlotatoAPIError as exc:
                db.table("pending_cancellations").update({
                    "retry_count": item["retry_count"] + 1,
                    "last_error": str(exc),
                    "updated_at": datetime.now(dt_timezone.utc).isoformat(),
                }).eq("id", item["id"]).execute()
                failed.append({"id": item["id"], "error": str(exc)})
    finally:
        await blotato.aclose()

    return success({"retried": len(items), "succeeded": succeeded, "failed": failed})
