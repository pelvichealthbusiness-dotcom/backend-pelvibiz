import time
import logging
from app.dependencies import get_supabase_admin

logger = logging.getLogger(__name__)

_patterns_cache: dict[str, tuple[dict, float]] = {}
_CACHE_TTL = 600  # 10 minutes

class LearningService:
    def __init__(self):
        self.supabase = get_supabase_admin()

    async def track(self, user_id: str, interaction_type: str, reference_id: str, reference_type: str, metadata: dict | None = None) -> str:
        """Record a user interaction. Returns the interaction ID."""
        result = self.supabase.table("user_interactions").insert({
            "user_id": user_id,
            "interaction_type": interaction_type,
            "reference_id": reference_id,
            "reference_type": reference_type,
            "metadata": metadata or {},
        }).execute()
        
        # Invalidate cache for this user
        _patterns_cache.pop(user_id, None)
        
        row_id = result.data[0]["id"] if result.data else ""
        logger.info(f"Tracked {interaction_type} for user {user_id}: {reference_id}")
        return row_id

    async def get_patterns(self, user_id: str) -> dict | None:
        """Get learning patterns for a user. Returns None if insufficient data (<3 interactions)."""
        now = time.time()
        if user_id in _patterns_cache:
            cached, ts = _patterns_cache[user_id]
            if now - ts < _CACHE_TTL:
                return cached

        # Count total interactions
        count_result = self.supabase.table("user_interactions").select("id", count="exact").eq("user_id", user_id).execute()
        total = count_result.count or 0
        
        if total < 3:
            return None

        # Get interaction type counts for content type preferences
        all_interactions = self.supabase.table("user_interactions").select("interaction_type, reference_type, metadata").eq("user_id", user_id).order("created_at", desc=True).limit(100).execute()
        
        rows = all_interactions.data or []
        
        # Extract preferred content types from selected ideas
        selected = [r for r in rows if r["interaction_type"] == "idea_selected"]
        content_types: dict[str, int] = {}
        for s in selected:
            ct = (s.get("metadata") or {}).get("content_type", "unknown")
            content_types[ct] = content_types.get(ct, 0) + 1
        
        total_selected = max(len(selected), 1)
        preferred_types = [
            {"content_type": ct, "frequency": round(count / total_selected, 2)}
            for ct, count in sorted(content_types.items(), key=lambda x: -x[1])[:5]
        ]
        
        # Extract rejected themes
        rejected = [r for r in rows if r["interaction_type"] == "idea_rejected"]
        rejected_themes = list(set(
            (r.get("metadata") or {}).get("title", "")
            for r in rejected
            if (r.get("metadata") or {}).get("title")
        ))[:10]
        
        # Extract preferred hooks from selected ideas
        hooks: dict[str, int] = {}
        for s in selected:
            hook_type = (s.get("metadata") or {}).get("angle", "")
            if hook_type:
                hooks[hook_type] = hooks.get(hook_type, 0) + 1
        preferred_hooks = [h for h, _ in sorted(hooks.items(), key=lambda x: -x[1])[:5]]
        
        # Build natural language summary
        summary_parts = []
        if preferred_types:
            top = preferred_types[0]
            summary_parts.append(f"User prefers {top['content_type']} content ({int(top['frequency']*100)}% of selections)")
        if rejected_themes:
            summary_parts.append(f"User tends to reject: {', '.join(rejected_themes[:3])}")
        if preferred_hooks:
            summary_parts.append(f"Preferred angles: {', '.join(preferred_hooks[:3])}")
        
        patterns = {
            "preferred_content_types": preferred_types,
            "rejected_themes": rejected_themes,
            "preferred_hooks": preferred_hooks,
            "total_interactions": total,
            "learning_summary": ". ".join(summary_parts) if summary_parts else "",
            "has_enough_data": total >= 3,
        }
        
        _patterns_cache[user_id] = (patterns, now)
        return patterns

    async def get_recent_titles(self, user_id: str, limit: int = 30) -> list[str]:
        """Get recent content titles for anti-repetition."""
        result = self.supabase.table("requests_log").select("title").eq("user_id", user_id).order("created_at", desc=True).limit(limit).execute()
        return [r["title"] for r in (result.data or []) if r.get("title")]

    def build_learning_prompt_section(self, patterns: dict | None) -> str:
        """Convert patterns to a prompt section string. Returns '' for cold start."""
        if not patterns or not patterns.get("has_enough_data"):
            return ""
        
        from app.prompts.ideas_generate import build_learning_section
        return build_learning_section(patterns)
