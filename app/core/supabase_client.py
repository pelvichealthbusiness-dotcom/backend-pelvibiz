"""Supabase client factory — singleton service-role + per-request user-scoped."""

from __future__ import annotations

from supabase import create_client, Client
from app.config import get_settings

# Module-level singleton
_service_client: Client | None = None


def get_service_client() -> Client:
    """
    Supabase client with service_role key.
    Bypasses RLS. Use ONLY for admin operations.
    Singleton — supabase-py uses httpx internally for connection pooling.
    """
    global _service_client
    if _service_client is None:
        settings = get_settings()
        _service_client = create_client(
            settings.supabase_url,
            settings.supabase_service_role_key,
        )
    return _service_client


def get_user_client(jwt_token: str) -> Client:
    """
    Supabase client scoped to a specific user's JWT.
    Respects RLS policies. Created per-request.
    """
    settings = get_settings()
    client = create_client(
        settings.supabase_url,
        settings.supabase_anon_key,
    )
    client.postgrest.auth(jwt_token)
    return client
