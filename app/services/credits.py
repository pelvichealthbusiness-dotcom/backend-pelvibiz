from app.dependencies import get_supabase_admin
from app.services.exceptions import CreditsExhaustedError
from supabase import Client

class CreditsService:
    def __init__(self, supabase: Client | None = None):
        self.supabase = supabase or get_supabase_admin()

    async def check_credits(self, user_id: str) -> tuple[int, int]:
        """Check if user has credits. Returns (used, limit). Raises CreditsExhaustedError."""
        result = (
            self.supabase.table("profiles")
            .select("credits_used, credits_limit")
            .eq("id", user_id)
            .single()
            .execute()
        )

        if not result.data:
            return (0, 40)  # Default

        used = result.data.get("credits_used", 0) or 0
        limit = result.data.get("credits_limit", 40) or 40

        if used >= limit:
            raise CreditsExhaustedError(credits_used=used, credits_limit=limit)

        return (used, limit)

    async def increment_credits(self, user_id: str) -> int:
        """Atomically increment credits_used. Returns new value."""
        # Use RPC or raw SQL for atomic increment
        result = (
            self.supabase.table("profiles")
            .select("credits_used")
            .eq("id", user_id)
            .single()
            .execute()
        )

        current = (result.data or {}).get("credits_used", 0) or 0
        new_value = current + 1

        self.supabase.table("profiles").update(
            {"credits_used": new_value}
        ).eq("id", user_id).execute()

        return new_value
