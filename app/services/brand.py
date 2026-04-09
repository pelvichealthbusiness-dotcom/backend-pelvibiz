import time
from app.dependencies import get_supabase_admin
from supabase import Client

# In-memory cache with TTL
_brand_cache: dict[str, tuple[dict, float]] = {}
_CACHE_TTL = 300  # 5 minutes

PROFILE_FIELDS = [
    "id", "brand_name", "brand_voice", "services_offered", "target_audience",
    "visual_identity", "keywords", "brand_color_primary", "brand_color_secondary", "brand_color_background",
    "visual_environment_setup", "visual_subject_outfit_face", "visual_subject_outfit_generic",
    "cta", "font_style", "font_size", "font_prompt", "font_style_secondary", "font_prompt_secondary", "content_style_brief", "brand_stories",
    "logo_url", "credits_used", "credits_limit", "role", "onboarding_completed",
]

class BrandService:
    def __init__(self, supabase: Client | None = None):
        self.supabase = supabase or get_supabase_admin()

    async def load_profile(self, user_id: str) -> dict:
        """Load brand profile with 5-min TTL cache."""
        now = time.time()
        if user_id in _brand_cache:
            cached, ts = _brand_cache[user_id]
            if now - ts < _CACHE_TTL:
                return cached

        result = self.supabase.table("profiles").select(", ".join(PROFILE_FIELDS)).eq("id", user_id).single().execute()

        if not result.data:
            # Return defaults if no profile
            return self._defaults(user_id)

        profile = result.data
        _brand_cache[user_id] = (profile, now)
        return profile

    def invalidate_cache(self, user_id: str) -> None:
        _brand_cache.pop(user_id, None)

    @staticmethod
    def _defaults(user_id: str) -> dict:
        return {
            "id": user_id,
            "brand_name": None,
            "brand_voice": None,
            "brand_color_primary": "#000000",
            "brand_color_secondary": "#FFFFFF",
            "font_style": "bold",
            "font_size": "38px",
            "font_prompt": "Clean, bold, geometric sans-serif",
            "font_style_secondary": None,
            "font_prompt_secondary": None,
            "logo_url": None,
            "credits_used": 0,
            "credits_limit": 40,
            "cta": None,
            "keywords": None,
            "target_audience": None,
            "services_offered": None,
            "visual_identity": None,
            "content_style_brief": None,
            "brand_stories": None,
        }

    async def save_profile(self, user_id: str, profile_data: dict) -> dict:
        """Save/upsert profile data to Supabase. Sets onboarding_completed=true."""
        # Map fields, filter out None values
        update_data = {k: v for k, v in profile_data.items() if v is not None}
        update_data["onboarding_completed"] = True

        result = self.supabase.table("profiles").upsert(
            {"id": user_id, **update_data},
            on_conflict="id"
        ).execute()

        # Invalidate cache
        self.invalidate_cache(user_id)

        return result.data[0] if result.data else update_data
