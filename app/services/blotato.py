from __future__ import annotations

from collections import defaultdict
from typing import Any

import httpx


BLOTATO_BASE_URL = "https://backend.blotato.com/v2"

# Mapping from agent_type to Blotato media_type.
# Carousels and static images → IMAGE; video reels → REEL.
_AGENT_TYPE_MEDIA_TYPE: dict[str, str] = {
    "real-carousel": "IMAGE",
    "ai-carousel": "IMAGE",
    "reels-edited-by-ai": "REEL",
    "ai-video-reels": "REEL",
    "ai-post-generator": "IMAGE",
}


def agent_type_to_media_type(agent_type: str | None) -> str:
    """Return the Blotato media_type for a given agent_type.

    Defaults to 'IMAGE' for unknown or missing types — never raises.
    """
    if not agent_type:
        return "IMAGE"
    return _AGENT_TYPE_MEDIA_TYPE.get(agent_type, "IMAGE")


def build_blotato_connections(profile: dict | None = None) -> dict | None:
    """Return structured Blotato connections, falling back to legacy IDs."""
    p = profile or {}
    connections = p.get("blotato_connections") or {}
    if connections:
        return connections

    legacy: dict[str, dict[str, str]] = {}
    if p.get("blotato_ig_id"):
        legacy["instagram"] = {"accountId": p.get("blotato_ig_id")}
    if p.get("blotato_fb_account_id") or p.get("blotato_fb_id"):
        legacy["facebook"] = {
            **({"accountId": p.get("blotato_fb_account_id")} if p.get("blotato_fb_account_id") else {}),
            **({"pageId": p.get("blotato_fb_id")} if p.get("blotato_fb_id") else {}),
        }
    return legacy or None


def normalize_blotato_connections(accounts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Normalize Blotato account payloads into profile-ready connection data."""
    normalized: dict[str, dict[str, Any]] = {}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for account in accounts:
        platform = str(account.get("platform") or account.get("type") or "").strip().lower()
        account_id = str(account.get("id") or account.get("accountId") or "").strip()
        if not platform or not account_id:
            continue
        grouped[platform].append(account)

    for platform, items in grouped.items():
        account = items[0]
        account_id = str(account.get("id") or account.get("accountId") or "").strip()
        if platform in {"instagram", "threads", "tiktok", "bluesky"}:
            normalized[platform] = {"accountId": account_id}
        elif platform in {"facebook", "linkedin"}:
            page_id = str(account.get("pageId") or account.get("subaccountId") or account.get("subId") or "").strip()
            payload: dict[str, Any] = {"accountId": account_id}
            if page_id:
                payload["pageId"] = page_id
            normalized[platform] = payload
        elif platform == "youtube":
            playlist_ids = [str(item.get("id") or item.get("playlistId") or "").strip() for item in items if str(item.get("id") or item.get("playlistId") or "").strip()]
            payload = {"accountId": account_id}
            if playlist_ids:
                payload["playlistIds"] = playlist_ids
            normalized[platform] = payload

    return normalized


async def fetch_blotato_accounts(api_key: str) -> list[dict[str, Any]]:
    """Fetch the connected Blotato accounts using the API key."""
    headers = {"blotato-api-key": api_key}
    async with httpx.AsyncClient(base_url=BLOTATO_BASE_URL, timeout=30.0, headers=headers) as client:
        response = await client.get("/users/me/accounts")
        response.raise_for_status()
        payload = response.json() or {}
        return list(payload.get("items") or [])


async def fetch_blotato_connections(api_key: str) -> dict[str, dict[str, Any]]:
    accounts = await fetch_blotato_accounts(api_key)
    connections = normalize_blotato_connections(accounts)

    # Facebook and LinkedIn need page/company page subaccounts.
    async with httpx.AsyncClient(base_url=BLOTATO_BASE_URL, timeout=30.0, headers={"blotato-api-key": api_key}) as client:
        for platform in ("facebook", "linkedin", "youtube"):
            account = connections.get(platform)
            if not account or not account.get("accountId"):
                continue
            response = await client.get(f"/users/me/accounts/{account['accountId']}/subaccounts")
            response.raise_for_status()
            payload = response.json() or {}
            items = list(payload.get("items") or [])
            if platform == "youtube":
                playlist_ids = [str(item.get("id") or "").strip() for item in items if str(item.get("id") or "").strip()]
                if playlist_ids:
                    account["playlistIds"] = playlist_ids
            else:
                page_id = next((str(item.get("id") or "").strip() for item in items if str(item.get("id") or "").strip()), "")
                if page_id:
                    account["pageId"] = page_id

    return connections
