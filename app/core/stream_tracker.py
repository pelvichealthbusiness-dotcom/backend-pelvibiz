"""Concurrent stream tracking with per-user and global limits.

Provides acquire/release semantics for stream slots, plus a context
manager for automatic cleanup.
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from app.core.exceptions import RateLimitError

logger = logging.getLogger(__name__)

# Slots older than this are considered stale and auto-expired on next acquire.
_SLOT_TTL_SECONDS = 300  # 5 minutes


class StreamTracker:
    """Track active SSE streams with per-user and global limits.

    Thread-safe via asyncio.Lock (no Redis needed for single-process).
    Stale slots (client disconnected without proper release) are auto-expired
    after _SLOT_TTL_SECONDS to prevent users from being permanently locked out.
    """

    def __init__(self, max_per_user: int = 2, max_total: int = 50):
        self._active: dict[str, int] = {}
        # Track acquire timestamps per user for stale-slot detection
        self._last_acquire: dict[str, float] = {}
        self._lock = asyncio.Lock()
        self.max_per_user = max_per_user
        self.max_total = max_total

    @property
    async def total_active(self) -> int:
        async with self._lock:
            return sum(self._active.values())

    @property
    def active_users(self) -> dict[str, int]:
        """Snapshot of active streams per user (for monitoring)."""
        return dict(self._active)

    def _expire_stale(self, user_id: str) -> None:
        """Clear stale slots for user_id if TTL has elapsed. Must be called under lock."""
        last = self._last_acquire.get(user_id)
        if last and (time.monotonic() - last) > _SLOT_TTL_SECONDS:
            count = self._active.pop(user_id, 0)
            self._last_acquire.pop(user_id, None)
            if count:
                logger.warning(
                    "Auto-expired %d stale stream slot(s) for %s (idle >%ds)",
                    count,
                    user_id,
                    _SLOT_TTL_SECONDS,
                )

    async def acquire(self, user_id: str) -> None:
        """Acquire a stream slot for the given user.

        Raises
        ------
        RateLimitError
            If the user already has max concurrent streams or the
            server is at global capacity.
        """
        async with self._lock:
            # Expire stale slots before checking limits
            self._expire_stale(user_id)

            total = sum(self._active.values())
            if total >= self.max_total:
                logger.warning(
                    "Global stream limit reached (%d/%d)",
                    total,
                    self.max_total,
                )
                raise RateLimitError(
                    message="Server at capacity, please retry in a moment",
                    retry_after=10,
                )

            user_count = self._active.get(user_id, 0)
            if user_count >= self.max_per_user:
                logger.warning(
                    "Per-user stream limit reached for %s (%d/%d)",
                    user_id,
                    user_count,
                    self.max_per_user,
                )
                raise RateLimitError(
                    message="You already have an active stream",
                    retry_after=5,
                )

            self._active[user_id] = user_count + 1
            self._last_acquire[user_id] = time.monotonic()
            logger.debug(
                "Stream acquired for %s (user: %d, total: %d)",
                user_id,
                user_count + 1,
                total + 1,
            )

    async def release(self, user_id: str) -> None:
        """Release a stream slot for the given user."""
        async with self._lock:
            if user_id in self._active:
                self._active[user_id] -= 1
                if self._active[user_id] <= 0:
                    del self._active[user_id]
                    self._last_acquire.pop(user_id, None)
                logger.debug("Stream released for %s", user_id)

    @asynccontextmanager
    async def track(self, user_id: str) -> AsyncGenerator[None, None]:
        """Context manager that acquires on entry and releases on exit.

        Usage::

            async with stream_tracker.track(user_id):
                async for chunk in agent.stream(...):
                    yield chunk
        """
        await self.acquire(user_id)
        try:
            yield
        finally:
            await self.release(user_id)


# ---------------------------------------------------------------------------
# Singleton instance
# ---------------------------------------------------------------------------
stream_tracker = StreamTracker()
