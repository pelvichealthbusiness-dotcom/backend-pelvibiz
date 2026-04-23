"""Credit management service.

50 shared credits/month across 4 tracked agents.
Auto-resets 30 days after credits_reset_at. Admin can also reset manually.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.dependencies import get_supabase_admin
from app.services.exceptions import CreditsExhaustedError
from supabase import Client

logger = logging.getLogger(__name__)

CREDIT_LIMIT = 50
CREDIT_PERIOD_DAYS = 30

TRACKED_AGENTS: frozenset[str] = frozenset({
    "real-carousel",
    "ai-carousel",
    "reels-edited-by-ai",
    "ai-post-generator",
})


class CreditsService:
    def __init__(self, supabase: Client | None = None):
        self.supabase = supabase or get_supabase_admin()

    async def check_credits(self, user_id: str, agent_type: str | None = None) -> tuple[int, int]:
        """Check if user has credits available.

        Returns (used, limit). Raises CreditsExhaustedError when exhausted.
        Non-tracked agents are always allowed (returns (0, CREDIT_LIMIT)).
        Auto-resets credits when the 30-day period expires.
        """
        if agent_type is not None and agent_type not in TRACKED_AGENTS:
            return (0, CREDIT_LIMIT)

        result = (
            self.supabase.table("profiles")
            .select("credits_used, credits_limit, credits_reset_at")
            .eq("id", user_id)
            .single()
            .execute()
        )

        row: dict = result.data if isinstance(result.data, dict) else {}
        if not row:
            return (0, CREDIT_LIMIT)

        used = row.get("credits_used", 0) or 0
        limit = row.get("credits_limit") or CREDIT_LIMIT
        reset_at_str = row.get("credits_reset_at")

        # Auto-reset when 30-day period has elapsed
        if reset_at_str:
            try:
                reset_at = datetime.fromisoformat(reset_at_str.replace("Z", "+00:00"))
                if datetime.now(timezone.utc) - reset_at >= timedelta(days=CREDIT_PERIOD_DAYS):
                    logger.info("Auto-resetting credits for user %s — period expired", user_id)
                    self._do_reset(user_id)
                    used = 0
            except (ValueError, TypeError):
                pass

        if used >= limit:
            raise CreditsExhaustedError(credits_used=used, credits_limit=limit)

        return (used, limit)

    async def increment_credits(self, user_id: str, agent_type: str | None = None) -> int:
        """Increment credits_used by 1. Only counts tracked agents.

        Returns new credits_used value (0 if agent is not tracked).
        """
        if agent_type is not None and agent_type not in TRACKED_AGENTS:
            return 0

        result = (
            self.supabase.table("profiles")
            .select("credits_used")
            .eq("id", user_id)
            .single()
            .execute()
        )

        row2: dict = result.data if isinstance(result.data, dict) else {}
        current = row2.get("credits_used", 0) or 0
        new_value = current + 1

        self.supabase.table("profiles").update(
            {"credits_used": new_value}
        ).eq("id", user_id).execute()

        logger.info("Credits incremented for user %s (agent=%s): %d → %d", user_id, agent_type, current, new_value)
        return new_value

    async def reset_credits(self, user_id: str) -> None:
        """Reset credits for a user. Used by admin panel."""
        self._do_reset(user_id)
        logger.info("Credits manually reset for user %s", user_id)

    def _do_reset(self, user_id: str) -> None:
        self.supabase.table("profiles").update({
            "credits_used": 0,
            "credits_reset_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", user_id).execute()
