"""JWT-based authentication — local PyJWT decode or Supabase API fallback."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import jwt
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.config import get_settings

logger = logging.getLogger(__name__)

security = HTTPBearer(auto_error=False)


@dataclass
class UserContext:
    """Authenticated user context injected into route handlers."""
    user_id: str       # Supabase auth.users.id (UUID)
    email: str
    role: str          # 'admin' | 'client' | 'user'
    token: str         # Raw JWT — for forwarding to user-scoped Supabase client


async def _get_role_from_profiles(user_id: str) -> str:
    """Fetch role from profiles table — authoritative source when JWT app_metadata lacks it."""
    try:
        from app.core.supabase_client import get_service_client
        result = get_service_client().from_("profiles").select("role").eq("id", user_id).single().execute()
        return result.data.get("role", "client") if result.data else "client"
    except Exception:
        return "client"


async def _decode_jwt_local(token: str) -> UserContext:
    """Decode Supabase JWT locally with PyJWT (fast, no network)."""
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "TOKEN_EXPIRED", "message": "Token has expired"},
        )
    except jwt.InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_TOKEN", "message": str(e)},
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_TOKEN", "message": "Missing sub claim"},
        )

    app_metadata = payload.get("app_metadata", {})
    role = app_metadata.get("role") or await _get_role_from_profiles(user_id)
    email = payload.get("email", "")

    return UserContext(user_id=user_id, email=email, role=role, token=token)


async def _validate_via_supabase(token: str) -> UserContext:
    """Fallback: validate token via Supabase auth.getUser() API call."""
    from app.core.supabase_client import get_service_client

    client = get_service_client()
    try:
        result = client.auth.get_user(token)
        if not result.user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "INVALID_TOKEN", "message": "Invalid token"},
            )
        user = result.user
        # Try to get role from app_metadata
        app_metadata = user.app_metadata or {}
        role = app_metadata.get("role") or await _get_role_from_profiles(user.id)
        return UserContext(
            user_id=user.id,
            email=user.email or "",
            role=role,
            token=token,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "TOKEN_EXPIRED", "message": f"Token validation failed: {e}"},
        )


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> UserContext:
    """
    Validate Supabase JWT and return UserContext.
    Supports internal service bypass via X-Internal-Key + X-User-Id headers.
    """
    settings = get_settings()

    # Internal service-to-service bypass (used by OpenClaw tool executor)
    internal_key = request.headers.get("X-Internal-Key", "")
    user_id_header = request.headers.get("X-User-Id", "")
    if (
        internal_key
        and settings.internal_api_key
        and internal_key == settings.internal_api_key
        and user_id_header
    ):
        return UserContext(user_id=user_id_header, email="", role="client", token="")

    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "MISSING_TOKEN", "message": "Authorization required"},
        )

    token = credentials.credentials
    if settings.supabase_jwt_secret:
        return await _decode_jwt_local(token)
    else:
        logger.debug("No SUPABASE_JWT_SECRET configured — using Supabase API fallback")
        return await _validate_via_supabase(token)


async def require_admin(user: UserContext = Depends(get_current_user)) -> UserContext:
    """Dependency that requires admin role."""
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Admin access required"},
        )
    return user
