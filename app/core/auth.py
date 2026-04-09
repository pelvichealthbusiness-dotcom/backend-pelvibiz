"""JWT-based authentication — local PyJWT decode or Supabase API fallback."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.config import get_settings

logger = logging.getLogger(__name__)

security = HTTPBearer()


@dataclass
class UserContext:
    """Authenticated user context injected into route handlers."""
    user_id: str       # Supabase auth.users.id (UUID)
    email: str
    role: str          # 'admin' | 'client' | 'user'
    token: str         # Raw JWT — for forwarding to user-scoped Supabase client


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
    role = app_metadata.get("role", "client")
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
        role = app_metadata.get("role", "client")
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
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> UserContext:
    """
    Validate Supabase JWT and return UserContext.
    Uses local PyJWT if SUPABASE_JWT_SECRET is configured, else falls back to API call.
    """
    settings = get_settings()
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
