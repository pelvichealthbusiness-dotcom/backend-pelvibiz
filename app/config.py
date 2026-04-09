from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Required
    supabase_url: str
    supabase_service_role_key: str
    google_gemini_api_key: str
    llm_api_key: str

    # Optional with defaults
    llm_base_url: str = "https://openrouter.ai/api/v1"
    llm_model: str = "openai/gpt-4.1-mini"
    gemini_model: str = "gemini-3-pro-image-preview"
    port: int = 8100
    host: str = "0.0.0.0"
    workers: int = 2
    allowed_origins: str = "https://healthcareai.pelvibiz.live"
    log_level: str = "info"
    storage_bucket: str = "chat-media"
    gemini_timeout: int = 60
    gemini_max_retries: int = 1
    image_download_timeout: int = 30
    max_image_size_mb: int = 20

    # Gemini model tiers
    gemini_model_default: str = "gemini-2.5-flash"
    gemini_model_lite: str = "gemini-2.5-flash-lite"

    # P2 AI Carousel
    watermark_logo_cache_ttl: int = 600
    target_image_width: int = 1080
    target_image_height: int = 1350
    p2_gemini_concurrency: int = 3

    # P2 Image QA Loop
    enable_image_qa: bool = True
    image_qa_max_attempts: int = 2

    # P3 Real Video / Creatomate
    creatomate_api_key: str = ""
    creatomate_base_url: str = "https://api.creatomate.com/v1"
    creatomate_poll_interval: int = 5
    creatomate_max_wait: int = 180
    renderscript_templates: str = ""
    # Instagram scraper
    apify_api_key: str = ""
    ig_private_api_rate_limit: int = 6  # requests per minute
    ig_cache_profile_ttl: int = 86400  # 24h
    ig_cache_posts_ttl: int = 21600  # 6h

    # P4 Instagram Style Analyzer
    rapidapi_key: str = ""

    # Supabase auth (used by JWT verification)
    supabase_jwt_secret: str = ""
    supabase_anon_key: str = ""

    # n8n publisher webhook
    n8n_publisher_webhook_url: str = ""

    @property
    def google_api_key(self) -> str:
        """Alias for google_gemini_api_key — used by Gemini client."""
        return self.google_gemini_api_key

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",")]

    @property
    def gemini_endpoint(self) -> str:
        return f"https://generativelanguage.googleapis.com/v1beta/models/{self.gemini_model}:generateContent"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
