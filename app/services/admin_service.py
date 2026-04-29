"""Admin service — user CRUD operations via Supabase Auth + profiles table."""

from __future__ import annotations

import logging
from typing import Any

from app.core.supabase_client import get_service_client
from app.core.exceptions import NotFoundError, ConflictError, DatabaseError

logger = logging.getLogger(__name__)


async def list_users(
    page: int,
    limit: int,
    offset: int,
    sort_by: str,
    order: str,
    search: str | None = None,
) -> dict[str, Any]:
    """List all users with pagination and optional search."""
    client = get_service_client()

    # Build query for total count
    count_query = client.table("profiles").select("id", count="exact")
    if search:
        count_query = count_query.or_(f"full_name.ilike.%{search}%,id.in.({_email_search_subquery(search)})")

    count_result = count_query.execute()
    total = count_result.count if count_result.count is not None else 0

    # Build query for data
    data_query = client.table("profiles").select("*")
    if search:
        data_query = data_query.or_(f"full_name.ilike.%{search}%")

    # Apply sorting
    data_query = data_query.order(sort_by, desc=(order == "desc"))
    data_query = data_query.range(offset, offset + limit - 1)

    result = data_query.execute()

    # Enrich with email from auth if possible
    users = result.data or []
    if users:
        try:
            auth_users = client.auth.admin.list_users()
            email_map = {}
            # Handle both list and paginated response
            user_list = auth_users if isinstance(auth_users, list) else getattr(auth_users, "users", auth_users)
            if isinstance(user_list, list):
                for au in user_list:
                    uid = getattr(au, "id", None) or (au.get("id") if isinstance(au, dict) else None)
                    email = getattr(au, "email", None) or (au.get("email") if isinstance(au, dict) else None)
                    if uid and email:
                        email_map[uid] = email
            for u in users:
                u["email"] = email_map.get(u["id"], "")
        except Exception as e:
            logger.warning("Could not enrich users with emails: %s", e)
            for u in users:
                u.setdefault("email", "")

    return {"users": users, "total": total}


def _email_search_subquery(search: str) -> str:
    """Helper — we can not filter auth users from profiles query directly.
    For search by email we rely on full_name as a proxy or do it in-memory."""
    return ""


async def create_user(
    email: str,
    password: str,
    full_name: str | None = None,
    role: str = "user",
    brand_name: str | None = None,
    credits_limit: int | None = None,
) -> dict[str, Any]:
    """Create a new user in Supabase Auth + profiles table."""
    client = get_service_client()

    # 1. Create auth user
    try:
        auth_result = client.auth.admin.create_user(
            {
                "email": email,
                "password": password,
                "email_confirm": True,
                "app_metadata": {"role": role},
            }
        )
    except Exception as e:
        err_msg = str(e)
        if "already" in err_msg.lower() or "duplicate" in err_msg.lower():
            raise ConflictError(f"User with email {email} already exists")
        raise DatabaseError(f"Failed to create auth user: {err_msg}")

    user = auth_result.user
    if not user:
        raise DatabaseError("Auth user creation returned no user object")

    user_id = user.id

    # 2. Create profile
    profile_data: dict[str, Any] = {
        "id": user_id,
        "role": role,
    }
    if full_name:
        profile_data["full_name"] = full_name
    if brand_name:
        profile_data["brand_name"] = brand_name
    if credits_limit is not None:
        profile_data["credits_limit"] = credits_limit

    try:
        profile_result = client.table("profiles").insert(profile_data).execute()
        profile = profile_result.data[0] if profile_result.data else profile_data
    except Exception as e:
        # Profile might already exist (DB trigger), try upsert
        if "duplicate" in str(e).lower() or "23505" in str(e):
            logger.info("Profile already exists for %s, updating instead", user_id)
            try:
                update_fields = {k: v for k, v in profile_data.items() if k != "id"}
                if update_fields:
                    profile_result = client.table("profiles").update(update_fields).eq("id", user_id).execute()
                    profile = profile_result.data[0] if profile_result.data else profile_data
                else:
                    profile_result = client.table("profiles").select("*").eq("id", user_id).execute()
                    profile = profile_result.data[0] if profile_result.data else profile_data
            except Exception as update_err:
                logger.error("Profile update also failed for %s: %s", user_id, update_err)
                raise DatabaseError(f"Failed to create/update user profile: {update_err}")
        else:
            # Rollback: delete the auth user
            logger.error("Profile creation failed, rolling back auth user %s: %s", user_id, e)
            try:
                client.auth.admin.delete_user(user_id)
            except Exception as rollback_err:
                logger.error("Rollback failed for user %s: %s", user_id, rollback_err)
            raise DatabaseError(f"Failed to create user profile: {e}")
    profile["email"] = email
    return profile


async def get_user(user_id: str) -> dict[str, Any]:
    """Get a single user profile by ID."""
    client = get_service_client()
    result = client.table("profiles").select("*").eq("id", user_id).execute()
    if not result.data:
        raise NotFoundError("User")
    user = result.data[0]

    # Enrich with email
    try:
        auth_user = client.auth.admin.get_user_by_id(user_id)
        if auth_user and auth_user.user:
            user["email"] = auth_user.user.email
    except Exception:
        user.setdefault("email", "")

    return user


async def update_user(
    user_id: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    """Update user profile and optionally auth metadata."""
    client = get_service_client()

    # Separate auth fields from profile fields
    email = data.pop("email", None)
    role = data.pop("role", None)

    # Update auth user if email or role changed
    if email or role:
        auth_update: dict[str, Any] = {}
        if email:
            auth_update["email"] = email
        if role:
            auth_update["app_metadata"] = {"role": role}
        try:
            client.auth.admin.update_user_by_id(user_id, auth_update)
        except Exception as e:
            raise DatabaseError(f"Failed to update auth user: {e}")

    # Update profile fields
    profile_update = {k: v for k, v in data.items() if v is not None}
    if role:
        profile_update["role"] = role

    if profile_update:
        try:
            result = client.table("profiles").update(profile_update).eq("id", user_id).execute()
            if not result.data:
                raise NotFoundError("User")
        except NotFoundError:
            raise
        except Exception as e:
            raise DatabaseError(f"Failed to update profile: {e}")

    return await get_user(user_id)


async def delete_user(user_id: str, hard: bool = False) -> None:
    """Delete a user. Soft delete sets role to deleted, hard delete removes auth user."""
    client = get_service_client()

    # Verify user exists
    result = client.table("profiles").select("id").eq("id", user_id).execute()
    if not result.data:
        raise NotFoundError("User")

    if hard:
        # Delete profile first, then auth user
        try:
            client.table("profiles").delete().eq("id", user_id).execute()
        except Exception as e:
            raise DatabaseError(f"Failed to delete profile: {e}")
        try:
            client.auth.admin.delete_user(user_id)
        except Exception as e:
            logger.warning("Auth user deletion failed for %s: %s", user_id, e)
    else:
        # Soft delete — mark role as deleted
        try:
            client.table("profiles").update({"role": "deleted"}).eq("id", user_id).execute()
            client.auth.admin.update_user_by_id(
                user_id, {"app_metadata": {"role": "deleted"}}
            )
        except Exception as e:
            raise DatabaseError(f"Failed to soft-delete user: {e}")


async def change_password(user_id: str, new_password: str) -> None:
    """Change a user's password via admin API."""
    client = get_service_client()
    try:
        client.auth.admin.update_user_by_id(user_id, {"password": new_password})
    except Exception as e:
        raise DatabaseError(f"Failed to change password: {e}")


async def reset_credits(user_id: str) -> dict[str, Any]:
    """Reset a user's credits_used to 0."""
    client = get_service_client()

    try:
        result = (
            client.table("profiles")
            .update({"credits_used": 0})
            .eq("id", user_id)
            .execute()
        )
        if not result.data:
            raise NotFoundError("User")
    except NotFoundError:
        raise
    except Exception as e:
        raise DatabaseError(f"Failed to reset credits: {e}")

    return result.data[0]
