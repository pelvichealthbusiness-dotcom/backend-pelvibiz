"""Admin-only Blotato service — sync master accounts and manage per-user assignments."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_settings
from app.core.exceptions import ConflictError, NotFoundError, DatabaseError
from app.core.supabase_client import get_service_client
from app.services.blotato import BLOTATO_BASE_URL, fetch_blotato_accounts
from app.services.blotato_client import BlotatoClient, BlotatoAPIError, BlotatoScheduleNotFound
from app.services.blotato_publisher import derive_publish_status

logger = logging.getLogger(__name__)

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
    playlist_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Assign a Blotato social account to a PelviBiz user.

    Merges the platform entry into profiles.blotato_connections JSONB.
    Returns the updated blotato_connections dict.
    """
    platform = platform.lower().strip()
    if platform not in BLOTATO_PLATFORMS:
        raise DatabaseError(f"Unsupported platform: {platform}")

    client = get_service_client()

    # Prevent assigning the same Blotato account to multiple users.
    profiles_result = client.table("profiles").select("id, full_name, blotato_connections").execute()
    profiles: list[dict[str, Any]] = profiles_result.data or []
    for profile in profiles:
        if str(profile.get("id") or "") == user_id:
            continue
        connections: dict[str, Any] = profile.get("blotato_connections") or {}
        for conn in connections.values():
            if not isinstance(conn, dict):
                continue
            existing_account_id = str(conn.get("accountId") or "").strip()
            existing_page_id = str(conn.get("pageId") or "").strip()
            if existing_account_id == account_id or (page_id and existing_page_id == page_id):
                owner = profile.get("full_name") or profile.get("id") or "another user"
                raise ConflictError(f"Blotato account is already assigned to {owner}")

    # Fetch current connections
    result = client.table("profiles").select("id, blotato_connections").eq("id", user_id).execute()
    if not result.data:
        raise NotFoundError("User")

    profile = result.data[0]
    connections: dict[str, Any] = dict(profile.get("blotato_connections") or {})

    # For YouTube, auto-fetch playlistIds from Blotato if not provided
    if platform == "youtube" and not playlist_ids:
        settings = get_settings()
        try:
            async with httpx.AsyncClient(base_url=BLOTATO_BASE_URL, timeout=30.0, headers={"blotato-api-key": settings.blotato_api_key}) as http:
                resp = await http.get(f"/users/me/accounts/{account_id}/subaccounts")
                resp.raise_for_status()
                items = list((resp.json() or {}).get("items") or [])
                playlist_ids = [str(item.get("id") or "").strip() for item in items if str(item.get("id") or "").strip()]
        except Exception:
            logger.warning("assign_account: failed to auto-fetch YouTube playlistIds for account %s", account_id)

    # Build the new platform entry
    entry: dict[str, Any] = {"accountId": account_id}
    if page_id:
        entry["pageId"] = page_id
    if playlist_ids:
        entry["playlistIds"] = playlist_ids

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


# ---------------------------------------------------------------------------
# Blotato status sync
# ---------------------------------------------------------------------------

# Blotato → internal status mapping (best-effort)
_BLOTATO_STATUS_MAP: dict[str, str] = {
    "scheduled": "scheduled",
    "published": "published",
    "failed": "failed",
}


async def sync_content_publish_status(content_id: str, api_key: str) -> dict[str, Any]:
    """Sync Blotato schedule status for all platforms of a content item.

    For each platform entry in blotato_post_ids that has a non-null id:
    - Calls GET /schedules/{id}
    - Maps Blotato status to internal status
    - 404 → treats as "published" (post was published and schedule expired)
    - Other errors → logs WARNING, keeps existing status, records in errors dict

    Updates blotato_post_ids and publish_status in requests_log.
    Returns a summary dict: content_id, synced_platforms, errors, updated_blotato_post_ids.
    Raises KeyError if content_id is not found.
    """
    db = get_service_client()
    row_result = (
        db.table("requests_log")
        .select("blotato_post_ids")
        .eq("id", content_id)
        .maybe_single()
        .execute()
    )
    if not row_result or not row_result.data:
        raise KeyError(f"Content {content_id} not found")

    blotato_post_ids: dict[str, Any] = row_result.data.get("blotato_post_ids") or {}
    updated_ids: dict[str, Any] = dict(blotato_post_ids)
    synced: list[str] = []
    errors: dict[str, str] = {}

    blotato = BlotatoClient(api_key=api_key, max_retries=2)
    try:
        for platform, entry in blotato_post_ids.items():
            schedule_id = entry.get("id") if isinstance(entry, dict) else entry
            if not schedule_id:
                continue
            try:
                data = await blotato.get_schedule(schedule_id)
                blotato_status = data.get("status", "")
                existing_status = entry.get("status") if isinstance(entry, dict) else "scheduled"
                internal_status = _BLOTATO_STATUS_MAP.get(blotato_status, existing_status)
                if isinstance(updated_ids[platform], dict):
                    updated_ids[platform] = {**updated_ids[platform], "status": internal_status}
                synced.append(platform)
                logger.info(
                    "sync_status: %s/%s blotato_status=%s → internal=%s",
                    content_id, platform, blotato_status, internal_status,
                )
            except BlotatoScheduleNotFound:
                logger.info(
                    "Schedule %s for platform %s returned 404 — treating as published",
                    schedule_id, platform,
                )
                if isinstance(updated_ids[platform], dict):
                    updated_ids[platform] = {**updated_ids[platform], "status": "published"}
                synced.append(platform)
            except BlotatoAPIError as exc:
                logger.warning(
                    "sync_status failed for %s/%s: %s", content_id, platform, exc
                )
                errors[platform] = str(exc)
    finally:
        await blotato.aclose()

    new_status = derive_publish_status(updated_ids) if updated_ids else None
    update_payload: dict[str, Any] = {"blotato_post_ids": updated_ids}
    if new_status:
        update_payload["publish_status"] = new_status
    db.table("requests_log").update(update_payload).eq("id", content_id).execute()

    return {
        "content_id": content_id,
        "synced_platforms": synced,
        "errors": errors,
        "updated_blotato_post_ids": updated_ids,
    }
