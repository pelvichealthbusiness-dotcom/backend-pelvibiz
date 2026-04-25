"""Blotato publisher — schedules content to all connected social platforms."""

from __future__ import annotations

import zoneinfo
from datetime import datetime, timezone as dt_timezone
from typing import TypedDict

from app.services.blotato_client import BlotatoAPIError, BlotatoClient


class PlatformEntry(TypedDict, total=False):
    id: str | None
    status: str
    error: str | None
    reschedule_error: str | None


def to_utc_iso(local_dt_str: str, tz_name: str) -> str:
    """Convert a local datetime string + IANA timezone name to UTC ISO 8601."""
    try:
        tz = zoneinfo.ZoneInfo(tz_name)
    except (zoneinfo.ZoneInfoNotFoundError, Exception):
        tz = dt_timezone.utc
    local_dt = datetime.fromisoformat(local_dt_str).replace(tzinfo=tz)
    return local_dt.astimezone(dt_timezone.utc).isoformat()


def media_type_for_platform(platform: str, media_type: str) -> str | None:
    """Return Blotato mediaType string, or None if not applicable."""
    if media_type.upper() == "REEL" and platform in ("instagram", "facebook"):
        return "reel"
    return None


def derive_publish_status(results: dict[str, PlatformEntry]) -> str:
    """Derive overall publish_status from per-platform results.

    all "scheduled" → "scheduled"
    all "failed"    → "failed"
    mixed           → "partial"
    """
    statuses = {v["status"] for v in results.values()}
    if statuses == {"scheduled"}:
        return "scheduled"
    if statuses == {"failed"}:
        return "failed"
    return "partial"


async def publish_content(
    client: BlotatoClient,
    media_urls: list[str],
    caption: str,
    connections: dict,
    scheduled_date: str,
    timezone: str,
    media_type: str = "IMAGE",
) -> dict[str, PlatformEntry]:
    """Schedule content to all platforms in connections.

    Returns a dict mapping platform name to a PlatformEntry rich dict.
    Raises BlotatoAPIError only when ALL platforms fail.
    Raises ValueError for invalid inputs before making any HTTP calls.
    """
    if not media_urls:
        raise ValueError("media_urls cannot be empty")
    if not connections:
        raise ValueError("connections cannot be empty")

    scheduled_time = to_utc_iso(scheduled_date, timezone)
    results: dict[str, PlatformEntry] = {}

    for platform, conn in connections.items():
        account_id = (conn.get("accountId") or "").strip()
        if not account_id:
            continue

        try:
            sub_id = await client.create_post(
                platform=platform,
                account_id=account_id,
                text=caption,
                media_urls=media_urls,
                scheduled_time=scheduled_time,
                page_id=conn.get("pageId") or None,
                media_type=media_type_for_platform(platform, media_type),
            )
            results[platform] = {"id": sub_id, "status": "scheduled", "error": None}
        except BlotatoAPIError as exc:
            results[platform] = {"id": None, "status": "failed", "error": str(exc)}

    if results and all(v["status"] == "failed" for v in results.values()):
        errors = "; ".join(f"{p}: {v['error']}" for p, v in results.items())
        raise BlotatoAPIError(f"All platforms failed: {errors}")

    return results


def _extract_schedule_id(entry) -> str | None:
    """Extract schedule ID from a rich dict or legacy plain string."""
    if isinstance(entry, dict):
        return entry.get("id") or None
    return entry or None


async def reschedule_all_platforms(
    client: BlotatoClient,
    blotato_post_ids: dict,
    new_scheduled_date: str,
    timezone: str,
) -> dict[str, str | None]:
    """Call reschedule_post for each platform that has a submission ID.

    Returns a dict mapping platform → error_message_or_None.
    None means success; non-None means the PATCH failed with that error string.
    Does NOT raise — all errors are captured per-platform.
    """
    new_scheduled_time = to_utc_iso(new_scheduled_date, timezone)
    results: dict[str, str | None] = {}
    for platform, entry in blotato_post_ids.items():
        schedule_id = _extract_schedule_id(entry)
        if not schedule_id:
            continue
        try:
            await client.reschedule_post(schedule_id, new_scheduled_time)
            results[platform] = None
        except BlotatoAPIError as exc:
            results[platform] = str(exc)
    return results


async def cancel_all_platforms(
    client: BlotatoClient,
    blotato_post_ids: dict,
) -> None:
    """Call cancel_post for each platform that has a submission ID."""
    for entry in blotato_post_ids.values():
        schedule_id = _extract_schedule_id(entry)
        if not schedule_id:
            continue
        await client.cancel_post(schedule_id)


async def validate_connections(
    client: BlotatoClient,
    connections: dict,
) -> tuple[dict, list[str]]:
    """Check each platform in connections against Blotato accounts list.

    Returns (valid_connections, stale_platforms).
    On any error during validation, returns (connections, []) — best-effort.
    """
    try:
        accounts = await client.list_accounts()
        valid_account_ids: set[str] = set()
        for account in accounts:
            for key in ("id", "accountId", "pageId", "subaccountId", "subId"):
                value = str(account.get(key, "") or "").strip()
                if value:
                    valid_account_ids.add(value)
            for playlist_id in account.get("playlistIds") or []:
                value = str(playlist_id or "").strip()
                if value:
                    valid_account_ids.add(value)

        valid: dict = {}
        stale: list[str] = []
        for platform, conn in connections.items():
            candidates = {
                str(conn.get("accountId") or "").strip(),
                str(conn.get("pageId") or "").strip(),
            }
            for playlist_id in conn.get("playlistIds") or []:
                value = str(playlist_id or "").strip()
                if value:
                    candidates.add(value)

            if any(candidate and candidate in valid_account_ids for candidate in candidates):
                valid[platform] = conn
            else:
                stale.append(platform)
        return valid, stale
    except Exception:
        return connections, []
