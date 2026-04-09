"""Admin endpoints — user management (CRUD, password, credits)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, EmailStr, Field

from app.core.auth import UserContext, require_admin
from app.core.pagination import PaginationParams, pagination_params
from app.core.responses import success, paginated, error_response
from app.services import admin_service

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
