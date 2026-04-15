import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.middleware.request_id import RequestIdMiddleware, request_id_var
from app.routers import health, carousel, user, onboarding, wizard, ai_carousel, video, chat, analyzer, content, auth_router, video_trim
from app.routers import user_preferences, content_generator, conversations, content_v2, competitors, research, ideation, scripting, social_intelligence as social_intelligence_router
from app.routers import instagram as instagram_router
from app.routers import chat_test_stream
from app.routers import chat_stream, upload, admin
from app.routers import post_generator
from app.routers.brand_stories import router as brand_stories_router
from app.services.exceptions import AgentAPIError
from app.core.exceptions import AppError, register_exception_handlers

_start_time: float = 0.0


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _start_time
    settings = get_settings()
    _start_time = time.time()
    # Validate required settings at startup
    assert settings.supabase_url, "SUPABASE_URL is required"
    assert settings.supabase_service_role_key, "SUPABASE_SERVICE_ROLE_KEY is required"
    assert settings.google_gemini_api_key, "GOOGLE_GEMINI_API_KEY is required"

    if not settings.supabase_jwt_secret:
        logging.getLogger(__name__).warning(
            "SUPABASE_JWT_SECRET not set — auth will use Supabase API calls (slower). "
            "Set it from Supabase Dashboard > Settings > API > JWT Secret."
        )
    yield


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="PelviBiz Agent API",
        version="0.2.0",
        docs_url="/api/v1/docs",
        openapi_url="/api/v1/openapi.json",
        lifespan=lifespan,
    )

    # --- Exception Handlers ---
    # 1. Core exception handlers (new AppError hierarchy → standard envelope)
    register_exception_handlers(app)

    # 2. Legacy AgentAPIError handler (existing services still use this)
    @app.exception_handler(AgentAPIError)
    async def agent_api_error_handler(request: Request, exc: AgentAPIError):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "data": None,
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "detail": exc.details if exc.details else None,
                },
                "meta": {"request_id": request_id_var.get("")},
            },
        )

    # --- Middleware ---

    # CORS — includes production domain and local dev
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-Request-Id"],
    )
    app.add_middleware(RequestIdMiddleware)

    # --- Routers ---

    app.include_router(health.router, prefix="/api/v1")
    app.include_router(carousel.router, prefix="/api/v1")
    app.include_router(user.router, prefix="/api/v1")
    app.include_router(onboarding.router, prefix="/api/v1")
    app.include_router(wizard.router, prefix="/api/v1")
    app.include_router(ai_carousel.router, prefix="/api/v1")
    app.include_router(video.router, prefix="/api/v1")
    app.include_router(video_trim.router, prefix="/api/v1")
    app.include_router(chat.router, prefix="/api/v1")
    app.include_router(analyzer.router, prefix="/api/v1")
    app.include_router(content_v2.router, prefix="/api/v1")
    app.include_router(content.router, prefix="/api/v1")
    app.include_router(competitors.router, prefix="/api/v1")
    app.include_router(instagram_router.router, prefix="/api/v1")
    app.include_router(research.router, prefix="/api/v1")
    app.include_router(ideation.router, prefix="/api/v1")
    app.include_router(scripting.router, prefix="/api/v1")
    app.include_router(auth_router.router, prefix="/api/v1")
    app.include_router(conversations.router, prefix="/api/v1")
    app.include_router(chat_test_stream.router, prefix="/api/v1")
    app.include_router(upload.router, prefix="/api/v1")
    app.include_router(admin.router, prefix="/api/v1")
    app.include_router(user_preferences.router, prefix="/api/v1")
    app.include_router(content_generator.router, prefix="/api/v1")
    app.include_router(chat_stream.router, prefix="/api/v1")
    app.include_router(post_generator.router, prefix="/api/v1")
    app.include_router(brand_stories_router, prefix="/api/v1")
    app.include_router(social_intelligence_router.router, prefix="/api/v1")

    return app


app = create_app()


def get_uptime() -> float:
    return time.time() - _start_time
