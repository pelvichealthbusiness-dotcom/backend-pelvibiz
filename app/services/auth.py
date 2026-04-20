from fastapi import Depends, Request
from app.dependencies import get_supabase_admin
from app.services.exceptions import AuthError, TokenExpiredError
from supabase import Client

class AuthService:
    def __init__(self, supabase: Client):
        self.supabase = supabase

    async def validate_token(self, token: str) -> dict:
        """Validate JWT and return user data."""
        try:
            result = self.supabase.auth.get_user(token)
            if not result.user:
                raise AuthError()
            return {"id": result.user.id, "email": result.user.email}
        except AuthError:
            raise
        except Exception:
            raise TokenExpiredError()

async def get_current_user(request: Request) -> dict:
    """FastAPI dependency — extracts and validates Bearer token.
    Supports internal service bypass via X-Internal-Key + X-User-Id headers.
    """
    from app.config import get_settings
    settings = get_settings()

    internal_key = request.headers.get("X-Internal-Key", "")
    user_id_header = request.headers.get("X-User-Id", "")
    if (
        internal_key
        and settings.internal_api_key
        and internal_key == settings.internal_api_key
        and user_id_header
    ):
        return {"id": user_id_header, "email": ""}

    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer ") or auth_header == "Bearer ":
        raise AuthError("Authorization header required")

    token = auth_header[7:]
    supabase = get_supabase_admin()
    auth_service = AuthService(supabase)
    return await auth_service.validate_token(token)
