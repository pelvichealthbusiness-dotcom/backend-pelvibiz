"""CRUD service for content (requests_log table) — Batch 2b.

New service using core infrastructure. Separate from content_service.py
which is used by existing legacy endpoints.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.core.supabase_client import get_service_client
from app.core.exceptions import NotFoundError, DatabaseError, ValidationError

logger = logging.getLogger(__name__)


class ContentCRUD:
    """CRUD operations on the requests_log table via core infra."""

    def __init__(self):
        self.client = get_service_client()

    # ------------------------------------------------------------------
    # List / Grid
    # ------------------------------------------------------------------

    def list_content(
        self,
        user_id: str,
        agent_type: str | None = None,
        status: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 20,
        offset: int = 0,
        sort_by: str = "created_at",
        order: str = "desc",
    ) -> tuple[list[dict], int]:
        """Paginated content grid with filters. Returns (items, total)."""
        try:
            query = (
                self.client.table("requests_log")
                .select("*", count="exact")
                .eq("user_id", user_id)
                .neq("media_urls", "{}")
            )

            if agent_type:
                query = query.eq("agent_type", agent_type)

            # Status filter: draft / published / scheduled
            if status == "published":
                query = query.eq("published", True).is_("scheduled_date", "null")
            elif status == "scheduled":
                query = query.eq("published", True).neq("scheduled_date", None)
            elif status == "draft":
                query = query.eq("published", False)

            # Date range
            if date_from:
                query = query.gte("created_at", date_from)
            if date_to:
                query = query.lte("created_at", date_to)

            desc = order == "desc"
            query = query.order(sort_by, desc=desc).range(offset, offset + limit - 1)
            result = query.execute()
            return result.data or [], result.count or 0
        except Exception as exc:
            logger.error("Failed to list content: %s", exc)
            raise DatabaseError(f"Failed to list content: {exc}")

    # ------------------------------------------------------------------
    # Single item
    # ------------------------------------------------------------------

    def get_content(self, content_id: str, user_id: str) -> dict:
        """Get single content item with ownership check."""
        try:
            result = (
                self.client.table("requests_log")
                .select("*")
                .eq("id", content_id)
                .eq("user_id", user_id)
                .maybe_single()
                .execute()
            )
            if not result or not result.data:
                raise NotFoundError("Content")
            return result.data
        except NotFoundError:
            raise
        except Exception as exc:
            logger.error("Failed to get content %s: %s", content_id, exc)
            raise DatabaseError(f"Failed to get content: {exc}")

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create_content(
        self,
        user_id: str,
        content_id: str | None,
        agent_type: str,
        title: str | None = None,
        caption: str | None = None,
        reply: str | None = None,
        media_urls: list[str] | None = None,
        reel_category: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        """Save a new content/asset to requests_log."""
        payload = {
            "user_id": user_id,
            "agent_type": agent_type,
            "title": title or "Generated Content",
            "caption": caption or "",
            "reply": reply or caption or "",
            "media_urls": media_urls or [],
            "published": False,
            "scheduled_date": None,
            "reel_category": reel_category or "",
        }
        if content_id:
            payload["id"] = content_id
        if metadata:
            payload["reply"] = reply or caption or title or ""
        try:
            result = self.client.table("requests_log").insert(payload).execute()
            return result.data[0]
        except Exception as exc:
            logger.error("Failed to create content: %s", exc)
            raise DatabaseError(f"Failed to create content: {exc}")

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update_content(self, content_id: str, user_id: str, updates: dict) -> dict:
        """Update content fields (publish status, schedule date, caption, title)."""
        # Verify ownership
        self.get_content(content_id, user_id)

        # Keep reply in sync with caption if caption is updated
        if "caption" in updates and "reply" not in updates:
            updates["reply"] = updates["caption"]

        try:
            result = (
                self.client.table("requests_log")
                .update(updates)
                .eq("id", content_id)
                .eq("user_id", user_id)
                .execute()
            )
            return result.data[0] if result.data else updates
        except Exception as exc:
            logger.error("Failed to update content %s: %s", content_id, exc)
            raise DatabaseError(f"Failed to update content: {exc}")

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete_content(self, content_id: str, user_id: str) -> bool:
        """Delete content item. Also attempts to clean up storage files."""
        content = self.get_content(content_id, user_id)

        # Try to delete storage files
        media_urls = content.get("media_urls") or []
        for url in media_urls:
            try:
                if "/chat-media/" in url:
                    path = url.split("/chat-media/")[1]
                    self.client.storage.from_("chat-media").remove([path])
            except Exception as e:
                logger.warning("Failed to delete storage file %s: %s", url, e)

        try:
            self.client.table("requests_log").delete().eq(
                "id", content_id
            ).eq("user_id", user_id).execute()
            return True
        except Exception as exc:
            logger.error("Failed to delete content %s: %s", content_id, exc)
            raise DatabaseError(f"Failed to delete content: {exc}")

    # ------------------------------------------------------------------
    # Calendar view
    # ------------------------------------------------------------------

    def get_calendar(
        self,
        user_id: str,
        date_from: str | None = None,
        date_to: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        agent_type: str | None = None,
    ) -> list[dict]:
        """Flat list of scheduled content in date range, ordered by scheduled_date."""
        # Accept either date_from/date_to or start_date/end_date
        range_start = date_from or start_date
        range_end = date_to or end_date
        try:
            query = (
                self.client.table("requests_log")
                .select("id, agent_type, reply, title, media_urls, scheduled_date, published")
                .eq("user_id", user_id)
                .not_.is_("scheduled_date", "null")
            )
            if agent_type:
                query = query.eq("agent_type", agent_type)
            if range_start:
                query = query.gte("scheduled_date", range_start)
            if range_end:
                query = query.lte("scheduled_date", range_end)
            result = query.order("scheduled_date", desc=False).limit(500).execute()
            return result.data or []
        except Exception as exc:
            logger.error("Failed to get calendar: %s", exc)
            raise DatabaseError(f"Failed to get calendar: {exc}")

    # ------------------------------------------------------------------
    # Usage stats
    # ------------------------------------------------------------------

    def get_usage(self, user_id: str) -> dict:
        """User usage stats: total generated, by agent type, credits used."""
        try:
            # Total count
            total_result = (
                self.client.table("requests_log")
                .select("id", count="exact")
                .eq("user_id", user_id)
                .execute()
            )
            total = total_result.count or 0

            # Count by agent_type — fetch all IDs + agent_type
            by_type_result = (
                self.client.table("requests_log")
                .select("agent_type")
                .eq("user_id", user_id)
                .execute()
            )
            type_counts: dict[str, int] = {}
            for row in (by_type_result.data or []):
                at = row.get("agent_type", "unknown")
                type_counts[at] = type_counts.get(at, 0) + 1

            # Published count
            published_result = (
                self.client.table("requests_log")
                .select("id", count="exact")
                .eq("user_id", user_id)
                .eq("published", True)
                .execute()
            )
            published = published_result.count or 0

            # Get credits from profile
            profile_result = (
                self.client.table("profiles")
                .select("credits_used, credits_limit")
                .eq("id", user_id)
                .maybe_single()
                .execute()
            )
            profile = profile_result.data if profile_result else {}

            return {
                "total_generated": total,
                "total_published": published,
                "by_agent_type": type_counts,
                "credits_used": profile.get("credits_used", 0) if profile else 0,
                "credits_limit": profile.get("credits_limit", 40) if profile else 40,
            }
        except Exception as exc:
            logger.error("Failed to get usage stats: %s", exc)
            raise DatabaseError(f"Failed to get usage stats: {exc}")
