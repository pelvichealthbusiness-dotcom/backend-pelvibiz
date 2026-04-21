"""Admin-only Blotato service — sync master accounts and manage per-user assignments."""

from __future__ import annotations

import json
from typing import Any

from app.config import get_settings
from app.core.exceptions import NotFoundError, DatabaseError
from app.core.supabase_client import get_service_client
from app.services.blotato import fetch_blotato_accounts, normalize_blotato_connections

# Platforms that need subaccount fetch to get pageId/playlistIds
_SUBACCOUNT_PLATFORMS = {"facebook", "linkedin", "youtube"}

# All platforms Blotato supports
BLOTATO_PLATFORMS = frozenset(
    ["instagram", "facebook", "linkedin", "tiktok", "youtube", "threads", "twitter", "bluesky", "pinterest"]
)


async def list_accounts_with_assignments() -> dict[str, Any]:
    """Fetch master Blotato accounts and enrich with PelviBiz assignment info.

    Returns:
        {
            "accounts": [
                {
                    "id": "29577",
                    "platform": "instagram",
                    "name": "...",
                    "assigned_to": {"user_id": "...", "display_name": "...", "email": "..."}
                    | None,
                }
            ],
            "users": [{"id": "...", "display_name": "...", "email": "...", "blotato_connections": {...}}]
        }
    """
    settings = get_settings()
    if not settings.blotato_api_key:
        raise DatabaseError("BLOTATO_API_KEY is not configured")

    # 1. Fetch all accounts from master Blotato account + subaccounts for FB/LinkedIn/YT
    raw_accounts = await fetch_blotato_accounts(settings.blotato_api_key)

    # Resolve pageId and page_name for platforms that need subaccounts
    subaccount_data: dict[str, dict[str, str]] = {}
    import httpx as _httpx
    async with _httpx.AsyncClient(base_url="https://backend.blotato.com/v2", timeout=30.0, headers={"blotato-api-key": settings.blotato_api_key}) as client:
        for acc in raw_accounts:
            acc_id = str(acc.get("id") or acc.get("accountId") or "").strip()
            platform = str(acc.get("platform") or acc.get("type") or "").strip().lower()
            if not acc_id or platform not in _SUBACCOUNT_PLATFORMS:
                continue
            try:
                resp = await client.get(f"/users/me/accounts/{acc_id}/subaccounts")
                resp.raise_for_status()
                items = list((resp.json() or {}).get("items") or [])
                if items:
                    first = items[0]
                    page_id = str(first.get("id") or first.get("pageId") or "").strip()
                    page_name = str(first.get("name") or first.get("displayName") or first.get("username") or "").strip()
                    subaccount_data[acc_id] = {"page_id": page_id, "page_name": page_name}
            except Exception:
                pass

    # 2. Fetch all PelviBiz users with blotato_connections
    client = get_service_client()
    profiles_result = client.table("profiles").select("id, full_name, blotato_connections").execute()
    profiles: list[dict[str, Any]] = profiles_result.data or []

    # Enrich profiles with emails
    email_map: dict[str, str] = {}
    try:
        auth_users = client.auth.admin.list_users()
        user_list = auth_users if isinstance(auth_users, list) else getattr(auth_users, "users", auth_users)
        if isinstance(user_list, list):
            for au in user_list:
                uid = getattr(au, "id", None) or (au.get("id") if isinstance(au, dict) else None)
                email = getattr(au, "email", None) or (au.get("email") if isinstance(au, dict) else None)
                if uid and email:
                    email_map[uid] = email
    except Exception:
        pass

    for p in profiles:
        p["email"] = email_map.get(p["id"], "")

    # 3. Build reverse index: accountId → {user_id, display_name, email}
    account_assignment: dict[str, dict[str, str]] = {}
    for profile in profiles:
        connections: dict[str, Any] = profile.get("blotato_connections") or {}
        for platform, conn in connections.items():
            if not isinstance(conn, dict):
                continue
            acc_id = str(conn.get("accountId") or "").strip()
            if acc_id:
                account_assignment[acc_id] = {
                    "user_id": profile["id"],
                    "display_name": profile.get("full_name") or "",
                    "email": profile.get("email") or "",
                }
            # Also index by pageId for Facebook/LinkedIn
            page_id = str(conn.get("pageId") or "").strip()
            if page_id:
                account_assignment[page_id] = account_assignment.get(acc_id, {
                    "user_id": profile["id"],
                    "display_name": profile.get("full_name") or "",
                    "email": profile.get("email") or "",
                })

    # 4. Enrich raw accounts with assignment info
    enriched: list[dict[str, Any]] = []
    for acc in raw_accounts:
        acc_id = str(acc.get("id") or acc.get("accountId") or "").strip()
        platform = str(acc.get("platform") or acc.get("type") or "").strip().lower()
        name = str(acc.get("name") or acc.get("username") or acc.get("displayName") or "").strip()
        if not acc_id or not platform:
            continue
        sub = subaccount_data.get(acc_id, {})
        enriched.append({
            "id": acc_id,
            "platform": platform,
            "name": name,
            "page_id": sub.get("page_id") or None,
            "page_name": sub.get("page_name") or None,
            "assigned_to": account_assignment.get(acc_id),
        })

    # 5. Build user summary list (for the assign dropdown)
    user_summaries = [
        {
            "id": p["id"],
            "display_name": p.get("full_name") or "",
            "email": p.get("email") or "",
            "blotato_connections": p.get("blotato_connections") or {},
        }
        for p in profiles
        if p.get("id")
    ]

    return {"accounts": enriched, "users": user_summaries}


async def assign_account(
    *,
    user_id: str,
    platform: str,
    account_id: str,
    page_id: str | None = None,
) -> dict[str, Any]:
    """Assign a Blotato social account to a PelviBiz user.

    Merges the platform entry into profiles.blotato_connections JSONB.
    Returns the updated blotato_connections dict.
    """
    platform = platform.lower().strip()
    if platform not in BLOTATO_PLATFORMS:
        raise DatabaseError(f"Unsupported platform: {platform}")

    client = get_service_client()

    # Fetch current connections
    result = client.table("profiles").select("id, blotato_connections").eq("id", user_id).execute()
    if not result.data:
        raise NotFoundError("User")

    profile = result.data[0]
    connections: dict[str, Any] = dict(profile.get("blotato_connections") or {})

    # Build the new platform entry
    entry: dict[str, str] = {"accountId": account_id}
    if page_id:
        entry["pageId"] = page_id

    connections[platform] = entry

    # Persist
    update_result = (
        client.table("profiles")
        .update({"blotato_connections": connections})
        .eq("id", user_id)
        .execute()
    )
    if not update_result.data:
        raise DatabaseError("Failed to update blotato_connections")

    return {"user_id": user_id, "blotato_connections": connections}


async def unassign_account(*, user_id: str, platform: str) -> dict[str, Any]:
    """Remove a platform entry from profiles.blotato_connections.

    Returns the updated blotato_connections dict.
    """
    platform = platform.lower().strip()
    client = get_service_client()

    result = client.table("profiles").select("id, blotato_connections").eq("id", user_id).execute()
    if not result.data:
        raise NotFoundError("User")

    profile = result.data[0]
    connections: dict[str, Any] = dict(profile.get("blotato_connections") or {})
    connections.pop(platform, None)

    update_result = (
        client.table("profiles")
        .update({"blotato_connections": connections})
        .eq("id", user_id)
        .execute()
    )
    if not update_result.data:
        raise DatabaseError("Failed to update blotato_connections")

    return {"user_id": user_id, "blotato_connections": connections}
