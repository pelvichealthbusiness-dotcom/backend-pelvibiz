"""Auth router — login, register, session, profile, refresh, logout, reset-password."""

import logging
from fastapi import APIRouter, Depends
from supabase import create_client

from app.config import get_settings
from app.core.auth import UserContext, get_current_user, require_admin
from app.core.supabase_client import get_service_client
from app.core.responses import success
from app.core.exceptions import AuthError, NotFoundError, AppError
from app.services.brand import BrandService
from app.services.blotato import build_blotato_connections, fetch_blotato_connections
from app.services.credits import CreditsService
from app.services.exceptions import AgentAPIError
from app.models.auth_models import (
    LoginRequest, RegisterRequest, RefreshRequest,
    ResetPasswordRequest, LogoutRequest, AuthResponse, UserProfile,
    FullUserProfile, ProfileUpdateRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_anon_client():
    """Create a Supabase client with anon key for user-level auth operations."""
    settings = get_settings()
    return create_client(settings.supabase_url, settings.supabase_anon_key)
def _build_user_profile(user_data: dict, profile_data: dict | None = None) -> UserProfile:
    """Build UserProfile from auth user + optional profile data."""
    p = profile_data or {}
    return UserProfile(
        id=user_data.get("id", ""),
        email=user_data.get("email", ""),
        display_name=user_data.get("user_metadata", {}).get("display_name") or p.get("full_name"),
        brand_name=p.get("brand_name"),
        role=p.get("role", "client"),
        onboarding_completed=p.get("onboarding_completed", False),
        credits_used=p.get("credits_used", 0),
        credits_limit=p.get("credits_limit", 40),
        timezone=p.get("timezone"),
        logo_url=p.get("logo_url"),
        blotato_connections=build_blotato_connections(p),
    )


def _build_full_profile(user: UserContext, profile_data: dict) -> FullUserProfile:
    """Build FullUserProfile with brand settings from DB row."""
    p = profile_data or {}
    return FullUserProfile(
        id=user.user_id,
        email=user.email,
        display_name=p.get("full_name"),
        brand_name=p.get("brand_name"),
        role=p.get("role", user.role),
        onboarding_completed=p.get("onboarding_completed", False),
        credits_used=p.get("credits_used", 0),
        credits_limit=p.get("credits_limit", 40),
        timezone=p.get("timezone"),
        logo_url=p.get("logo_url"),
        brand_voice=p.get("brand_voice"),
        brand_color_primary=p.get("brand_color_primary"),
        brand_color_accent=p.get("brand_color_secondary"),  # DB column → accent
        brand_color_background=p.get("brand_color_background"),
        font_style=p.get("font_style"),
        font_size=p.get("font_size"),
        font_prompt=p.get("font_prompt"),
        font_style_secondary=p.get("font_style_secondary"),
        font_prompt_secondary=p.get("font_prompt_secondary"),
        business_name=p.get("brand_name"),  # alias
        services_offered=p.get("services_offered"),
        target_audience=p.get("target_audience"),
        visual_identity=p.get("visual_identity"),
        keywords=p.get("keywords"),
        cta=p.get("cta"),
        content_style_brief=p.get("content_style_brief"),
        brand_playbook=p.get("content_style_brief") or p.get("brand_playbook"),
        visual_environment_setup=p.get("visual_environment_setup"),
        visual_subject_outfit_face=p.get("visual_subject_outfit_face"),
        visual_subject_outfit_generic=p.get("visual_subject_outfit_generic"),
        blotato_connections=build_blotato_connections(p),
    )


# ---------------------------------------------------------------------------
# TASK-010: Session & Refresh
# ---------------------------------------------------------------------------

@router.get("/session")
async def get_session(user: UserContext = Depends(get_current_user)):
    """
    Validate current JWT and return user profile data.
    GET /api/v1/auth/session
    """
    admin = get_service_client()
    profile_result = (
        admin.table("profiles")
        .select("*")
        .eq("id", user.user_id)
        .maybe_single()
        .execute()
    )

    profile = profile_result.data or {}
    user_data = UserProfile(
        id=user.user_id,
        email=user.email,
        display_name=profile.get("full_name"),
        brand_name=profile.get("brand_name"),
        role=profile.get("role", user.role),
        onboarding_completed=profile.get("onboarding_completed", False),
        credits_used=profile.get("credits_used", 0),
        credits_limit=profile.get("credits_limit", 40),
        timezone=profile.get("timezone"),
        logo_url=profile.get("logo_url"),
        blotato_connections=build_blotato_connections(profile),
    )
    return success(user_data.model_dump())


@router.post("/refresh")
async def refresh_token(request: RefreshRequest):
    """
    Refresh access token using refresh token.
    POST /api/v1/auth/refresh
    """
    try:
        client = _get_anon_client()
        result = client.auth.refresh_session(request.refresh_token)
    except Exception as e:
        raise AuthError(f"Token refresh failed: {e}")

    if not result.session:
        raise AuthError("Token refresh failed — invalid refresh token")

    # Load profile for response
    admin = get_service_client()
    profile_result = (
        admin.table("profiles")
        .select("*")
        .eq("id", result.user.id)
        .maybe_single()
        .execute()
    )

    user_profile = _build_user_profile(
        {"id": result.user.id, "email": result.user.email, "user_metadata": result.user.user_metadata},
        profile_result.data,
    )

    return success({
        "access_token": result.session.access_token,
        "refresh_token": result.session.refresh_token,
        "user": user_profile.model_dump(),
        "expires_at": result.session.expires_at or 0,
    })


# ---------------------------------------------------------------------------
# TASK-011: Profile endpoints
# ---------------------------------------------------------------------------

@router.get("/profile")
async def get_profile(user: UserContext = Depends(get_current_user)):
    """
    Full user profile with brand settings.
    GET /api/v1/auth/profile
    """
    admin = get_service_client()
    profile_result = (
        admin.table("profiles")
        .select("*")
        .eq("id", user.user_id)
        .maybe_single()
        .execute()
    )

    if not profile_result.data:
        raise NotFoundError("Profile")

    full_profile = _build_full_profile(user, profile_result.data)
    return success(full_profile.model_dump())


@router.post("/blotato/refresh-connections")
async def refresh_blotato_connections(user: UserContext = Depends(require_admin)):
    """Import connected Blotato account IDs into the current user's profile."""
    settings = get_settings()
    if not settings.blotato_api_key:
        raise AppError("CONFIG_ERROR", "Blotato API key is not configured", 500)

    admin = get_service_client()
    profile_result = (
        admin.table("profiles")
        .select("*")
        .eq("id", user.user_id)
        .maybe_single()
        .execute()
    )
    if not profile_result.data:
        raise NotFoundError("Profile")

    imported = await fetch_blotato_connections(settings.blotato_api_key)
    current = profile_result.data or {}
    current_connections = build_blotato_connections(current) or {}
    merged_connections = {**current_connections, **imported}

    update_data: dict[str, object] = {"blotato_connections": merged_connections}

    admin.table("profiles").update(update_data).eq("id", user.user_id).execute()

    updated = (
        admin.table("profiles")
        .select("*")
        .eq("id", user.user_id)
        .single()
        .execute()
    )

    full_profile = _build_full_profile(user, updated.data)
    return success(full_profile.model_dump())


@router.put("/profile")
async def update_profile(
    body: ProfileUpdateRequest,
    user: UserContext = Depends(get_current_user),
):
    """
    Update user profile fields (partial update — only provided fields).
    PUT /api/v1/auth/profile
    """
    # Build update dict from provided fields only
    update_data = body.model_dump(exclude_unset=True)
    logger.info(f"DEBUG - Profile Update Data: {update_data}")
    if not update_data:
        raise AppError("VALIDATION_ERROR", "No fields provided for update", 422)

    # Map frontend field names to DB column names
    field_mapping = {
        "brand_color_primary": "brand_color_primary",
        "brand_color_accent": "brand_color_secondary",
        "brand_color_secondary": "brand_color_secondary",
        "display_name": "full_name",
        "blotato_connections": "blotato_connections",
    }
    db_data = {}
    for key, value in update_data.items():
        db_key = field_mapping.get(key, key)
        db_data[db_key] = value

    admin = get_service_client()

    # Verify profile exists
    existing = (
        admin.table("profiles")
        .select("id")
        .eq("id", user.user_id)
        .maybe_single()
        .execute()
    )
    if not existing.data:
        raise NotFoundError("Profile")

    # Update
    result = (
        admin.table("profiles")
        .update(db_data)
        .eq("id", user.user_id)
        .execute()
    )

    # Invalidate brand cache
    brand_service = BrandService(admin)
    brand_service.invalidate_cache(user.user_id)

    # Re-fetch full profile
    updated = (
        admin.table("profiles")
        .select("*")
        .eq("id", user.user_id)
        .single()
        .execute()
    )

    full_profile = _build_full_profile(user, updated.data)
    return success(full_profile.model_dump())


# ---------------------------------------------------------------------------
# TASK-012: Enhanced Logout
# ---------------------------------------------------------------------------

@router.post("/logout")
async def logout(
    body: LogoutRequest | None = None,
    user: UserContext = Depends(get_current_user),
):
    """
    Logout — invalidate session server-side via Supabase Auth.
    POST /api/v1/auth/logout
    """
    try:
        admin = get_service_client()
        # Sign out all sessions for this user on server side
        admin.auth.admin.sign_out(user.user_id)
    except Exception as e:
        logger.warning(f"Logout server-side invalidation failed for {user.user_id}: {e}")

    return success({"logged_out": True, "message": "Session invalidated"})


# ---------------------------------------------------------------------------
# Existing endpoints (login, register, me, reset-password)
# ---------------------------------------------------------------------------

@router.post("/login")
async def login(request: LoginRequest):
    """Login with email + password. Returns JWT + user profile."""
    try:
        client = _get_anon_client()
        result = client.auth.sign_in_with_password({
            "email": request.email,
            "password": request.password,
        })
    except Exception as e:
        error_msg = str(e)
        if "Invalid login" in error_msg or "invalid" in error_msg.lower():
            raise AuthError("Invalid email or password")
        raise AuthError(f"Login failed: {error_msg}")

    if not result.session:
        raise AuthError("Invalid email or password")

    # Load profile
    admin = get_service_client()
    profile_result = admin.table("profiles").select("*").eq("id", result.user.id).maybe_single().execute()

    user_profile = _build_user_profile(
        {"id": result.user.id, "email": result.user.email, "user_metadata": result.user.user_metadata},
        profile_result.data,
    )

    return success({
        "access_token": result.session.access_token,
        "refresh_token": result.session.refresh_token,
        "user": user_profile.model_dump(),
        "expires_at": result.session.expires_at or 0,
    })


@router.post("/register")
async def register(request: RegisterRequest):
    """Register new user. Creates auth user + profile."""
    admin = get_service_client()

    # Validate password strength server-side
    password = request.password
    errors = []
    if len(password) < 12:
        errors.append("at least 12 characters")
    if not any(c.isupper() for c in password):
        errors.append("an uppercase letter")
    if not any(c.isdigit() for c in password):
        errors.append("a number")
    if not any(c in "!@#$%^&*()_+-=[]{}|;':\",./<>?" for c in password):
        errors.append("a special character")
    if errors:
        raise AppError(
            code="WEAK_PASSWORD",
            message=f"Password must contain: {', '.join(errors)}",
            status_code=400,
        )

    try:
        result = admin.auth.admin.create_user({
            "email": request.email,
            "password": request.password,
            "email_confirm": True,
            "user_metadata": {"display_name": request.display_name},
        })
    except Exception as e:
        error_msg = str(e)
        if "already" in error_msg.lower() or "exists" in error_msg.lower():
            from app.core.exceptions import ConflictError
            raise ConflictError("An account with this email already exists")
        raise AppError(code="REGISTER_FAILED", message=f"Registration failed: {error_msg}", status_code=400)

    user_id = result.user.id

    # Create profile
    try:
        admin.table("profiles").insert({
            "id": user_id,
            "full_name": request.display_name,
            "role": "client",
            "credits_used": 0,
            "credits_limit": 40,
            "onboarding_completed": False,
        }).execute()
    except Exception as e:
        logger.error(f"Failed to create profile for {user_id}: {e}")

    # Sign in to get a session
    try:
        client = _get_anon_client()
        login_result = client.auth.sign_in_with_password({
            "email": request.email,
            "password": request.password,
        })
    except Exception:
        raise AppError(
            code="AUTO_LOGIN_FAILED",
            message="Account created but auto-login failed. Please log in manually.",
            status_code=201,
        )

    user_profile = _build_user_profile(
        {"id": user_id, "email": request.email, "user_metadata": {"display_name": request.display_name}},
        {"role": "client", "credits_used": 0, "credits_limit": 40, "onboarding_completed": False},
    )

    return success({
        "access_token": login_result.session.access_token,
        "refresh_token": login_result.session.refresh_token,
        "user": user_profile.model_dump(),
        "expires_at": login_result.session.expires_at or 0,
    })


@router.get("/me")
async def get_me(user: UserContext = Depends(get_current_user)):
    """Get current user's full profile (legacy endpoint — prefer /profile)."""
    brand_service = BrandService()
    profile = await brand_service.load_profile(user.user_id)

    return success({
        "id": user.user_id,
        "email": user.email,
        **profile,
    })


@router.post("/reset-password")
async def reset_password(request: ResetPasswordRequest):
    """Send password reset email."""
    admin = get_service_client()

    try:
        admin.auth.admin.generate_link({
            "type": "recovery",
            "email": request.email,
        })
    except Exception as e:
        logger.warning(f"Reset password failed: {e}")
        # Don't reveal if email exists

    return success({"sent": True, "message": "If an account with this email exists, a reset link has been sent."})


@router.post("/credits/increment")
async def increment_credits(user: UserContext = Depends(get_current_user)):
    """Increment the current user's credits_used by 1."""
    credits_service = CreditsService()
    new_value = await credits_service.increment_credits(user.user_id)
    return success({"credits_used": new_value})
