"""Concurrent stream tracking with per-user and global limits.

Provides acquire/release semantics for stream slots, plus a context
manager for automatic cleanup.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from app.core.exceptions import RateLimitError

logger = logging.getLogger(__name__)


class StreamTracker:
    """Track active SSE streams with per-user and global limits.

    Thread-safe via asyncio.Lock (no Redis needed for single-process).
    """

    def __init__(self, max_per_user: int = 1, max_total: int = 50):
        self._active: dict[str, int] = {}
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

    async def acquire(self, user_id: str) -> None:
        """Acquire a stream slot for the given user.

        Raises
        ------
        RateLimitError
            If the user already has max concurrent streams or the
            server is at global capacity.
        """
        async with self._lock:
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
