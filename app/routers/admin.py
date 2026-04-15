"""Admin endpoints — user management (CRUD, password, credits) + Blotato sync."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, EmailStr, Field

from app.core.auth import UserContext, require_admin
from app.core.pagination import PaginationParams, pagination_params
from app.core.responses import success, paginated, error_response
from app.services import admin_service
from app.services import blotato_admin_service

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
