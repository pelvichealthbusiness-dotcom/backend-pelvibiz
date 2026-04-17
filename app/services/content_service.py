import logging
from app.dependencies import get_supabase_admin
from app.services.exceptions import AgentAPIError

logger = logging.getLogger(__name__)

# In-memory cache for content lists: {user_id: (result, timestamp)}
import time
_content_cache: dict[str, tuple[dict, float]] = {}
_CACHE_TTL = 30  # 30 seconds — short TTL, just to avoid duplicate requests

class ContentService:
    @staticmethod
    def _invalidate_cache(user_id: str) -> None:
        keys_to_remove = [k for k in _content_cache if k.startswith(f"{user_id}:")]
        for k in keys_to_remove:
            _content_cache.pop(k, None)

    def __init__(self):
        self.supabase = get_supabase_admin()
    
    async def list_content(self, user_id: str, page: int = 1, limit: int = 20, 
                           agent_type: str | None = None, published: bool | None = None) -> dict:
        """List user's content with pagination and filters."""
        # Check cache (30s TTL)
        cache_key = f"{user_id}:{page}:{limit}:{agent_type}:{published}"
        now = time.time()
        if cache_key in _content_cache:
            cached, ts = _content_cache[cache_key]
            if now - ts < _CACHE_TTL:
                return cached

        # Select only essential fields for list view (no reply — saves bandwidth)
        query = self.supabase.table("requests_log").select(
            "id, agent_type, title, caption, media_urls, published, scheduled_date, reel_category, created_at",
            count="exact"
        ).eq("user_id", user_id).order("created_at", desc=True)
        
        if agent_type:
            query = query.eq("agent_type", agent_type)
        if published is not None:
            query = query.eq("published", published)
        
        # Filter out empty media_urls
        # Filter out empty media_urls via neq
        query = query.neq("media_urls", "{}")
        
        offset = (page - 1) * limit
        query = query.range(offset, offset + limit - 1)
        
        result = query.execute()
        total = result.count or 0
        items = result.data or []
        
        result = {
            "items": items,
            "total": total,
            "page": page,
            "limit": limit,
            "has_more": offset + limit < total,
        }
        _content_cache[cache_key] = (result, now)
        return result
    
    async def get_content(self, user_id: str, content_id: str) -> dict:
        """Get a single content item. Validates ownership."""
        result = self.supabase.table("requests_log").select("*").eq("id", content_id).maybe_single().execute()
        
        if not result.data:
            raise AgentAPIError(message="Content not found", code="NOT_FOUND", status_code=404)
        
        if result.data.get("user_id") != user_id:
            raise AgentAPIError(message="Content not found", code="NOT_FOUND", status_code=404)
        
        return result.data
    
    async def update_content(self, user_id: str, content_id: str, title: str | None = None, caption: str | None = None) -> dict:
        """Update title and/or caption. Validates ownership."""
        # Verify ownership first
        await self.get_content(user_id, content_id)
        
        update_data = {}
        if title is not None:
            update_data["title"] = title
        if caption is not None:
            update_data["caption"] = caption
            update_data["reply"] = caption  # Keep reply in sync
        
        if not update_data:
            raise AgentAPIError(message="Nothing to update", code="NO_CHANGES", status_code=400)
        
        result = self.supabase.table("requests_log").update(update_data).eq("id", content_id).execute()
        self._invalidate_cache(user_id)
        return result.data[0] if result.data else update_data
    
    async def delete_content(self, user_id: str, content_id: str) -> bool:
        """Delete content + storage files. Validates ownership."""
        content = await self.get_content(user_id, content_id)
        
        # Delete storage files first
        media_urls = content.get("media_urls") or []
        for url in media_urls:
            try:
                # Extract storage path from URL
                # URL format: https://xxx.supabase.co/storage/v1/object/public/chat-media/generated/...
                if "/chat-media/" in url:
                    path = url.split("/chat-media/")[1]
                    self.supabase.storage.from_("chat-media").remove([path])
            except Exception as e:
                logger.warning(f"Failed to delete storage file {url}: {e}")
        
        # Delete from DB
        self.supabase.table("requests_log").delete().eq("id", content_id).eq("user_id", user_id).execute()
        self._invalidate_cache(user_id)
        return True
    
    async def publish_content(self, user_id: str, content_id: str, caption: str | None = None) -> dict:
        """Mark content as published."""
        content = await self.get_content(user_id, content_id)
        
        if not content.get("media_urls"):
            raise AgentAPIError(message="Cannot publish content without media", code="NO_MEDIA", status_code=400)
        
        update_data = {"published": True}
        if caption is not None:
            update_data["caption"] = caption
        
        result = self.supabase.table("requests_log").update(update_data).eq("id", content_id).execute()
        return result.data[0] if result.data else update_data
    
    async def schedule_content(self, user_id: str, content_id: str, scheduled_date: str, caption: str | None = None) -> dict:
        """Schedule content for future publication."""
        await self.get_content(user_id, content_id)
        
        # Validate date is in the future
        from datetime import datetime, timezone
        try:
            dt = datetime.fromisoformat(scheduled_date.replace("Z", "+00:00"))
            # Make naive datetimes UTC-aware so comparison never raises TypeError
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt <= datetime.now(timezone.utc):
                raise AgentAPIError(message="Scheduled date must be in the future", code="INVALID_DATE", status_code=400)
        except (ValueError, TypeError):
            raise AgentAPIError(message="Invalid date format. Use ISO 8601.", code="INVALID_DATE", status_code=400)
        
        update_data = {"published": False, "scheduled_date": scheduled_date}
        if caption is not None:
            update_data["caption"] = caption
        
        result = self.supabase.table("requests_log").update(update_data).eq("id", content_id).execute()
        return result.data[0] if result.data else update_data
    
    async def unpublish_content(self, user_id: str, content_id: str) -> dict:
        """Unmark content as published."""
        await self.get_content(user_id, content_id)
        
        result = self.supabase.table("requests_log").update({
            "published": False,
            "scheduled_date": None,
        }).eq("id", content_id).execute()
        return result.data[0] if result.data else {"published": False}
