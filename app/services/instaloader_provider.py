"""Instagram scraping provider backed by the instaloader library."""

from __future__ import annotations

import asyncio
import itertools
import logging
import os
import tempfile
import time
from typing import TYPE_CHECKING

import instaloader
import instaloader.exceptions

if TYPE_CHECKING:
    from app.services.session_store import SessionStore

logger = logging.getLogger(__name__)

# Module-level per-user rate-limit state
# Maps user_id -> asyncio.Lock (guards last_scrape_ts access)
_user_locks: dict[str, asyncio.Lock] = {}
_last_competitor_scrape: dict[str, float] = {}
_MIN_COMPETITOR_DELAY = 30.0  # seconds


def _get_user_lock(user_id: str) -> asyncio.Lock:
    if user_id not in _user_locks:
        _user_locks[user_id] = asyncio.Lock()
    return _user_locks[user_id]


def _make_instaloader() -> instaloader.Instaloader:
    return instaloader.Instaloader(
        download_pictures=False,
        download_videos=False,
        download_video_thumbnails=False,
        save_metadata=False,
        compress_json=False,
    )


_TYPENAME_MAP = {
    "GraphVideo": "reel",
    "GraphImage": "photo",
    "GraphSidecar": "carousel",
}


def _map_content_type(typename: str) -> str:
    return _TYPENAME_MAP.get(typename, "photo")


def _build_profile_dict(profile: instaloader.Profile) -> dict:
    return {
        "username": profile.username,
        "full_name": profile.full_name,
        "biography": profile.biography,
        "followers": profile.followers,
        "following": profile.followees,
        "posts_count": profile.mediacount,
        "is_verified": profile.is_verified,
        "profile_pic_url": profile.profile_pic_url,
    }


def _build_post_dict(post: instaloader.Post) -> dict:
    return {
        "source_post_id": post.shortcode,
        "caption": post.caption or "",
        "posted_at": post.date_utc.isoformat(),
        "views": post.video_view_count if post.is_video else 0,
        "likes": post.likes,
        "comments": post.comments,
        "saves": 0,              # not available via public Instaloader API
        "watch_time_seconds": 0, # not available via public Instaloader API
        "reach": 0,              # not available via public Instaloader API
        "content_type": _map_content_type(post.typename),
        "raw_data": {
            "shortcode": post.shortcode,
            "typename": post.typename,
            "is_video": post.is_video,
            "video_url": post.video_url if post.is_video else None,
            "url": post.url,
        },
    }


class InstagramScraperError(Exception):
    """Raised for all Instagram scraping failures."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class InstaloaderProvider:
    """Instagram scraping via instaloader (synchronous calls run in executor)."""

    def __init__(self, session_store: "SessionStore") -> None:
        self._session_store = session_store

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def login(self, username: str, password: str, user_id: str) -> None:
        """Login to Instagram and persist the session for future scrapes."""
        loop = asyncio.get_event_loop()

        def _do_login():
            L = _make_instaloader()
            try:
                L.login(username, password)
            except instaloader.exceptions.LoginException as exc:
                raise InstagramScraperError(
                    code="INVALID_CREDENTIALS",
                    message=f"Login failed for {username}: {exc}",
                ) from exc
            except instaloader.exceptions.TwoFactorAuthRequiredException as exc:
                raise InstagramScraperError(
                    code="REQUIRES_2FA",
                    message="Two-factor authentication required.",
                ) from exc
            except Exception as exc:
                raise InstagramScraperError(
                    code="SCRAPE_FAILED",
                    message=f"Unexpected error during login: {exc}",
                ) from exc

            # Dump session to a temp file, read bytes, then clean up
            with tempfile.NamedTemporaryFile(delete=False, suffix=".session") as tf:
                tmp_path = tf.name

            try:
                L.save_session_to_filename(tmp_path)
                with open(tmp_path, "rb") as f:
                    return f.read()
            finally:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

        session_bytes = await loop.run_in_executor(None, _do_login)
        await self._session_store.save(user_id, session_bytes)
        logger.info("Session saved for user %s (%s)", user_id, username)

    async def scrape_own(
        self,
        user_id: str,
        max_posts: int = 30,
    ) -> tuple[dict, list[dict]]:
        """Scrape the authenticated user's own account using their saved session."""
        session_bytes = await self._session_store.load(user_id)
        if not session_bytes:
            raise InstagramScraperError(
                code="SCRAPE_FAILED",
                message=f"No saved session found for user {user_id}. Call login first.",
            )

        loop = asyncio.get_event_loop()

        def _do_scrape():
            with tempfile.NamedTemporaryFile(delete=False, suffix=".session") as tf:
                tmp_path = tf.name
                tf.write(session_bytes)

            try:
                L = _make_instaloader()
                L.load_session_from_filename(tmp_path)
                username = L.test_login()
                if not username:
                    raise InstagramScraperError(
                        code="INVALID_CREDENTIALS",
                        message="Loaded session is no longer valid.",
                    )
                profile = instaloader.Profile.from_username(L.context, username)
                profile_dict = _build_profile_dict(profile)
                posts = [
                    _build_post_dict(p)
                    for p in itertools.islice(profile.get_posts(), max_posts)
                ]
                return profile_dict, posts
            except InstagramScraperError:
                raise
            except instaloader.exceptions.LoginException as exc:
                raise InstagramScraperError(
                    code="INVALID_CREDENTIALS",
                    message=str(exc),
                ) from exc
            except instaloader.exceptions.TwoFactorAuthRequiredException as exc:
                raise InstagramScraperError(
                    code="REQUIRES_2FA",
                    message="Two-factor authentication required.",
                ) from exc
            except instaloader.exceptions.ProfileNotExistsException as exc:
                raise InstagramScraperError(
                    code="PROFILE_NOT_FOUND",
                    message=str(exc),
                ) from exc
            except instaloader.exceptions.PrivateProfileNotFollowedException as exc:
                raise InstagramScraperError(
                    code="PRIVATE_PROFILE",
                    message=str(exc),
                ) from exc
            except instaloader.exceptions.TooManyRequestsException as exc:
                raise InstagramScraperError(
                    code="RATE_LIMITED",
                    message=str(exc),
                ) from exc
            except Exception as exc:
                raise InstagramScraperError(
                    code="SCRAPE_FAILED",
                    message=f"Unexpected scrape error: {exc}",
                ) from exc
            finally:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

        return await loop.run_in_executor(None, _do_scrape)

    async def scrape_public(
        self,
        handle: str,
        max_posts: int = 30,
        user_id: str | None = None,
    ) -> tuple[dict, list[dict]] | tuple[None, None]:
        """
        Scrape a public Instagram profile without authentication.

        When user_id is provided, enforces a 30s rate limit between calls from
        the same user. Returns (None, None) and logs a warning if rate-limited.
        """
        if user_id is not None:
            lock = _get_user_lock(user_id)
            async with lock:
                last = _last_competitor_scrape.get(user_id, 0.0)
                elapsed = time.monotonic() - last
                if elapsed < _MIN_COMPETITOR_DELAY:
                    logger.warning(
                        "Rate limit hit for user %s scraping @%s — %.1fs since last call (min: %ss)",
                        user_id,
                        handle,
                        elapsed,
                        _MIN_COMPETITOR_DELAY,
                    )
                    return None, None
                _last_competitor_scrape[user_id] = time.monotonic()

        loop = asyncio.get_event_loop()

        def _do_scrape():
            try:
                L = _make_instaloader()
                profile = instaloader.Profile.from_username(L.context, handle)
                profile_dict = _build_profile_dict(profile)
                posts = [
                    _build_post_dict(p)
                    for p in itertools.islice(profile.get_posts(), max_posts)
                ]
                return profile_dict, posts
            except instaloader.exceptions.LoginException as exc:
                raise InstagramScraperError(
                    code="INVALID_CREDENTIALS",
                    message=str(exc),
                ) from exc
            except instaloader.exceptions.TwoFactorAuthRequiredException as exc:
                raise InstagramScraperError(
                    code="REQUIRES_2FA",
                    message="Two-factor authentication required.",
                ) from exc
            except instaloader.exceptions.ProfileNotExistsException as exc:
                raise InstagramScraperError(
                    code="PROFILE_NOT_FOUND",
                    message=f"Profile @{handle} does not exist.",
                ) from exc
            except instaloader.exceptions.PrivateProfileNotFollowedException as exc:
                raise InstagramScraperError(
                    code="PRIVATE_PROFILE",
                    message=f"Profile @{handle} is private.",
                ) from exc
            except instaloader.exceptions.TooManyRequestsException as exc:
                raise InstagramScraperError(
                    code="RATE_LIMITED",
                    message=str(exc),
                ) from exc
            except Exception as exc:
                raise InstagramScraperError(
                    code="SCRAPE_FAILED",
                    message=f"Unexpected scrape error for @{handle}: {exc}",
                ) from exc

        return await loop.run_in_executor(None, _do_scrape)
