from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from statistics import mean

from fastapi import APIRouter, Depends, Query

from app.config import get_settings
from app.core.auth import UserContext, get_current_user
from app.dependencies import get_supabase_admin
from app.models.instagram import (
    ConnectRequest,
    ConnectResponse,
    InstagramStatus,
    SyncResponse,
)
from app.services.content_intelligence import ContentIntelligenceService
from app.services.exceptions import AgentAPIError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/instagram", tags=["instagram"])


def _build_scraper():
    """Instantiate InstagramScraper (PrivateAPI → Apify → RapidAPI chain)."""
    from app.services.instagram_scraper import InstagramScraper

    return InstagramScraper()


def _normalize_posts(posts: list[dict]) -> list[dict]:
    """Convert InstagramScraper post format to ContentIntelligence format."""
    from datetime import datetime, timezone

    normalized = []
    for p in posts:
        # Convert epoch timestamp → ISO string
        ts = p.get("timestamp", 0) or p.get("taken_at", 0)
        posted_at: str | None = None
        if ts:
            try:
                posted_at = datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
            except (ValueError, OSError):
                pass

        # Map numeric media_type / is_carousel → content_type string
        if p.get("is_carousel"):
            content_type = "carousel"
        elif int(p.get("media_type", 1) or 1) == 2:
            content_type = "reel"
        else:
            content_type = "photo"

        normalized.append({
            "source_post_id": str(p.get("id") or p.get("source_post_id") or ""),
            "caption": p.get("caption") or "",
            "posted_at": posted_at or p.get("posted_at"),
            "likes": int(p.get("likes", 0) or 0),
            "comments": int(p.get("comments", 0) or 0),
            "views": int(p.get("views", 0) or 0),
            "content_type": content_type,
            "raw_data": p,
        })
    return normalized


def _compute_avg_engagement(posts: list[dict]) -> float:
    if not posts:
        return 0.0
    rates = [
        (float(p.get("likes", 0) or 0) + float(p.get("comments", 0) or 0))
        / max(float(p.get("views", 0) or 0), 1)
        for p in posts
    ]
    return round(mean(rates), 4)


def _extract_top_topics(posts: list[dict], top_n: int = 3) -> list[str]:
    from collections import Counter

    topics = [p.get("topic") for p in posts if p.get("topic")]
    if not topics:
        return []
    return [t for t, _ in Counter(topics).most_common(top_n)]


# ---------------------------------------------------------------------------
# POST /instagram/connect
# ---------------------------------------------------------------------------


@router.post("/connect", response_model=ConnectResponse)
async def connect_instagram(
    body: ConnectRequest,
    user: UserContext = Depends(get_current_user),
):
    user_id = user.user_id
    username = body.username.strip().lstrip("@").lower()

    scraper = _build_scraper()
    profile, raw_posts = await scraper.scrape(username, max_posts=30)
    posts = _normalize_posts(raw_posts)

    handle = profile.get("username", username)
    now_iso = datetime.now(timezone.utc).isoformat()

    # Persist connection metadata in profiles
    supabase = get_supabase_admin()
    supabase.table("profiles").update(
        {
            "ig_username": handle,
            "ig_connected_at": now_iso,
            "ig_last_sync_at": now_iso,
        }
    ).eq("id", user_id).execute()

    # Store scraped posts
    await ContentIntelligenceService(supabase).store_scrape(
        user_id=user_id,
        handle=handle,
        posts=posts,
        account_type="personal",
    )

    avg_engagement = _compute_avg_engagement(posts)
    top_topics = _extract_top_topics(posts)

    return ConnectResponse(
        connected=True,
        handle=handle,
        followers=int(profile.get("followers", 0)),
        post_count=len(posts),
        avg_engagement_rate=avg_engagement,
        top_topics=top_topics,
        scraped_at=now_iso,
    )


# ---------------------------------------------------------------------------
# GET /instagram/status
# ---------------------------------------------------------------------------


@router.get("/status", response_model=InstagramStatus)
async def instagram_status(
    user: UserContext = Depends(get_current_user),
):
    user_id = user.user_id
    settings = get_settings()
    supabase = get_supabase_admin()

    profile_row = (
        supabase.table("profiles")
        .select("ig_username, ig_connected_at, ig_last_sync_at")
        .eq("id", user_id)
        .maybe_single()
        .execute()
    )
    profile_data = (profile_row.data if profile_row else None) or {}
    ig_username: str | None = profile_data.get("ig_username")
    ig_last_sync_at: str | None = profile_data.get("ig_last_sync_at")

    if not ig_username:
        return InstagramStatus(
            connected=False,
            handle=None,
            post_count=0,
            last_sync_at=None,
            can_sync_at=None,
        )

    # Count own-account posts via content_accounts join
    accounts_row = (
        supabase.table("content_accounts")
        .select("id")
        .eq("user_id", user_id)
        .eq("account_type", "personal")
        .maybe_single()
        .execute()
    )
    post_count = 0
    if accounts_row and accounts_row.data:
        account_id = accounts_row.data["id"]
        count_row = (
            supabase.table("content")
            .select("id", count="exact")
            .eq("account_id", account_id)
            .execute()
        )
        post_count = count_row.count or 0

    # Compute can_sync_at
    can_sync_at: str | None = None
    if ig_last_sync_at:
        try:
            last_sync_dt = datetime.fromisoformat(ig_last_sync_at)
            can_sync_at = (
                last_sync_dt + timedelta(minutes=settings.ig_min_resync_minutes)
            ).isoformat()
        except ValueError:
            pass

    return InstagramStatus(
        connected=True,
        handle=ig_username,
        post_count=post_count,
        last_sync_at=ig_last_sync_at,
        can_sync_at=can_sync_at,
    )


# ---------------------------------------------------------------------------
# POST /instagram/sync/{handle}
# ---------------------------------------------------------------------------


@router.post("/sync/{handle}", response_model=SyncResponse)
async def sync_instagram(
    handle: str,
    force: bool = Query(default=False),
    user: UserContext = Depends(get_current_user),
):
    user_id = user.user_id
    settings = get_settings()
    supabase = get_supabase_admin()
    handle = handle.strip().lstrip("@").lower()

    # Determine account type
    profile_row = (
        supabase.table("profiles")
        .select("ig_username, ig_last_sync_at")
        .eq("id", user_id)
        .maybe_single()
        .execute()
    )
    profile_data = (profile_row.data if profile_row else None) or {}
    own_handle: str | None = profile_data.get("ig_username")
    ig_last_sync_at: str | None = profile_data.get("ig_last_sync_at")

    is_own = own_handle and own_handle.lower() == handle

    # Enforce resync cooldown for own account
    if is_own and ig_last_sync_at and not force:
        try:
            last_sync_dt = datetime.fromisoformat(ig_last_sync_at)
            elapsed = datetime.now(timezone.utc) - last_sync_dt
            wait_minutes = settings.ig_min_resync_minutes - int(elapsed.total_seconds() / 60)
            if elapsed.total_seconds() < settings.ig_min_resync_minutes * 60:
                raise AgentAPIError(
                    message=f"Wait {wait_minutes} minute(s) before resyncing",
                    code="SYNC_TOO_SOON",
                    status_code=429,
                )
        except AgentAPIError:
            raise
        except ValueError:
            pass

    account_type = "personal" if is_own else "competitor"
    scraper = _build_scraper()
    profile, raw_posts = await scraper.scrape(handle, max_posts=30)
    posts = _normalize_posts(raw_posts)

    # Build profile metadata to persist alongside scraped posts
    profile_metadata = {
        'followers': int(profile.get('followers', 0) or 0),
        'following': int(profile.get('following', 0) or 0),
        'biography': profile.get('biography') or profile.get('bio') or '',
        'is_verified': bool(profile.get('is_verified', False)),
        'full_name': profile.get('full_name') or profile.get('name') or '',
    }

    # Count existing posts before upsert
    accounts_row = (
        supabase.table("content_accounts")
        .select("id")
        .eq("user_id", user_id)
        .eq("handle", handle)
        .maybe_single()
        .execute()
    )
    total_before = 0
    if accounts_row and accounts_row.data:
        account_id = accounts_row.data["id"]
        count_row = (
            supabase.table("content")
            .select("id", count="exact")
            .eq("account_id", account_id)
            .execute()
        )
        total_before = count_row.count or 0

    await ContentIntelligenceService(supabase).store_scrape(
        user_id=user_id,
        handle=handle,
        posts=posts,
        account_type=account_type,
        metadata=profile_metadata,
    )

    # Recount after upsert
    accounts_row2 = (
        supabase.table("content_accounts")
        .select("id")
        .eq("user_id", user_id)
        .eq("handle", handle)
        .maybe_single()
        .execute()
    )
    total_after = 0
    if accounts_row2 and accounts_row2.data:
        account_id2 = accounts_row2.data["id"]
        count_row2 = (
            supabase.table("content")
            .select("id", count="exact")
            .eq("account_id", account_id2)
            .execute()
        )
        total_after = count_row2.count or 0

    new_posts = max(0, total_after - total_before)
    now_iso = datetime.now(timezone.utc).isoformat()

    # Update last sync timestamp for own account
    if is_own:
        supabase.table("profiles").update(
            {"ig_last_sync_at": now_iso}
        ).eq("id", user_id).execute()

    return SyncResponse(
        handle=handle,
        post_count=total_after,
        new_posts=new_posts,
        scraped_at=now_iso,
        account_type=account_type,
    )

